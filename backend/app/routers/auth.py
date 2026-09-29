"""로그인 / 내 정보."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from .. import login_guard, models, schemas, security

router = APIRouter(tags=["auth"])
log = logging.getLogger("app.auth")

# 없는 이메일도 비밀번호 확인과 같은 시간이 걸리게(있는 이메일을 시간으로 알아내지 못하게 · S0)
_DUMMY_HASH = security.hash_password("s0-no-such-user")


def _source(request: Request):
    """로그인 실패를 셀 「곳」 — 공인 주소만(없으면 계정 기준만 센다 · login_guard 설명)."""
    return login_guard.public_source(request.headers.get("x-real-ip"),
                                     request.client.host if request.client else None)


def _too_many(wait: int):
    return HTTPException(429, login_guard.BLOCKED_MSG, headers={"Retry-After": str(wait)})


@router.post("/auth/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, request: Request, db: Session = Depends(get_db)):
    buckets = login_guard.password_buckets(payload.email, _source(request))
    wait = login_guard.blocked(db, buckets)
    if wait is not None:
        log.warning("비밀번호 로그인 막음(실패 상한) — 묶음 %d개 · %d초 뒤", len(buckets), wait)
        raise _too_many(wait)
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    ok = security.verify_password(payload.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        login_guard.record(db, buckets)
        raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다")
    decision = login_guard.demo_decision(db, user, payload.password)
    if decision == "block":
        log.warning("데모 계정 로그인 막음(공개된 비밀번호 그대로) — 계정 번호 %d", user.id)
        raise HTTPException(403, login_guard.DEMO_MSG)
    if decision == "warn":
        log.warning("데모 관리자 로그인 들여보냄(공개된 비밀번호 그대로 · 쓸 수 있는 다른 관리자 없음) — 계정 번호 %d · "
                    "비밀번호를 바꾸거나 전산 SSO 관리자를 지정하세요", user.id)
    token = security.create_token(user.id, user.role)
    return schemas.TokenOut(access_token=token, user=schemas.UserOut.model_validate(user))


@router.get("/auth/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


class ChangePwIn(schemas.BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password")
def change_password(
    payload: ChangePwIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """내 비밀번호 변경 — 현재 비밀번호 확인 후 교체."""
    if not security.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "현재 비밀번호가 올바르지 않습니다")
    if len((payload.new_password or "").strip()) < 6:
        raise HTTPException(400, "새 비밀번호는 6자 이상이어야 합니다")
    if any(login_guard.is_published_demo(e, payload.new_password) for e in login_guard.seed.DEMO_PASSWORDS):
        raise HTTPException(400, "처음 설치 때 공개된 비밀번호는 쓸 수 없습니다. 다른 비밀번호를 정해 주세요.")
    user.password_hash = security.hash_password(payload.new_password)
    db.commit()
    return {"ok": True}


class SSOIn(schemas.BaseModel):
    token: str


# 전산(ERP) 내정보 API — 로직분석과 동일 검증 방식
ERP_BASE_URL = "http://api.metainc.co.kr"  # 전산 서버 이전(구 metainc01.cafe24.com 중지)
ERP_MY_PROFILE_PATH = "/api/employee-management/my-profile"


@router.post("/auth/sso", response_model=schemas.TokenOut)
def sso_login(payload: SSOIn, request: Request, db: Session = Depends(get_db)):
    """전산 로그인 토큰으로 자동 로그인.
    전산 '내 정보' API로 토큰을 검증 → 사용자 자동 매핑(없으면 자동 가입).
    권한: 직위/팀에 '대표'→admin, 팀명에 '광고'→staff, 그 외→viewer(읽기전용).
    실패(토큰 없음 · ① 이 거절 · 사용자 식별 실패)만 한 곳 10분 30번까지 센다(S0) — ① 이 안 받는 것(502)은 세지 않는다."""
    import requests as rq
    import secrets as pysecrets

    buckets = login_guard.sso_buckets(_source(request))
    wait = login_guard.blocked(db, buckets)
    if wait is not None:
        log.warning("SSO 로그인 막음(실패 상한) — %d초 뒤", wait)
        raise _too_many(wait)

    def fail(msg):
        login_guard.record(db, buckets)
        return HTTPException(401, msg)

    tok = (payload.token or "").strip().strip("/").strip()
    if not tok:
        raise fail("SSO 토큰이 없습니다")
    bearer = tok if tok.lower().startswith("bearer ") else "Bearer " + tok
    try:
        resp = rq.get(
            ERP_BASE_URL + ERP_MY_PROFILE_PATH,
            headers={"Authorization": bearer},
            timeout=8,
        )
    except Exception:
        raise HTTPException(502, "전산 인증 서버에 연결할 수 없습니다")
    if resp.status_code in (401, 403):
        raise fail("전산 로그인이 유효하지 않습니다. 전산에 먼저 로그인해주세요.")
    if resp.status_code != 200:
        # ① 쪽 사정(점검·장애) — 사용자 실패가 아니라 세지 않는다(S0)
        raise HTTPException(502, "전산 인증 서버가 지금 답하지 않습니다. 잠시 뒤 다시 들어와 주세요.")
    try:
        body = resp.json()
    except ValueError:
        raise HTTPException(502, "전산 인증 서버의 답을 읽을 수 없습니다. 잠시 뒤 다시 들어와 주세요.")
    result = (body.get("result") if isinstance(body, dict) else None) or {}
    if not isinstance(result, dict):
        raise fail("전산 사용자 식별에 실패했습니다")
    login_id = str(result.get("id") or "").strip()
    if not login_id or len(login_id) > 100:
        raise fail("전산 사용자 식별에 실패했습니다")
    name = (str(result.get("name") or login_id)).strip()[:100]

    # 직위·팀 문자열 수집 → 권한 판별
    strings = []
    auth_obj = result.get("authority") or {}
    if isinstance(auth_obj, dict) and auth_obj.get("name"):
        strings.append(str(auth_obj["name"]))
    for t in result.get("teamList") or []:
        if isinstance(t, dict):
            strings.extend(str(v) for v in t.values() if isinstance(v, str))
        elif isinstance(t, str):
            strings.append(t)
    # 권한 정책(2026-06-15 보안 수정): ★admin은 SSO로 자동 부여하지 않는다(대표가 설정에서 수동 지정).
    # 광고 "관리"팀(마케터)=staff(본인 광고주 수정) / 그 외 전 직원=viewer(읽기전용).
    # 공백 제거 후 매칭(띄어쓰기 차이 흡수). 기존 manual admin은 아래 동기화에서 보존(강등 안 함).
    norm = [s.replace(" ", "") for s in strings]
    sso_role = "staff" if any("광고관리" in s for s in norm) else "viewer"

    email = f"erp:{login_id}"  # 전산 로그인ID 기반 식별(중복 방지 프리픽스)
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        team = db.query(models.Team).first()
        user = models.User(
            email=email, name=name, role=sso_role,
            password_hash=security.hash_password(pysecrets.token_hex(16)),
            team_id=team.id if team else None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # 권한 동기화 — 단 admin은 절대 강등하지 않음
        if user.role != "admin" and user.role != sso_role:
            user.role = sso_role
            db.commit()
    token = security.create_token(user.id, user.role)
    return schemas.TokenOut(access_token=token, user=schemas.UserOut.model_validate(user))
