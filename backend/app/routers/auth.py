"""로그인 / 내 정보."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from .. import models, schemas, security

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not security.verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다")
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
    user.password_hash = security.hash_password(payload.new_password)
    db.commit()
    return {"ok": True}


class SSOIn(schemas.BaseModel):
    token: str


# 전산(ERP) 내정보 API — 로직분석과 동일 검증 방식
ERP_BASE_URL = "http://api.metainc.co.kr"  # 전산 서버 이전(구 metainc01.cafe24.com 중지)
ERP_MY_PROFILE_PATH = "/api/employee-management/my-profile"


@router.post("/auth/sso", response_model=schemas.TokenOut)
def sso_login(payload: SSOIn, db: Session = Depends(get_db)):
    """전산 로그인 토큰으로 자동 로그인.
    전산 '내 정보' API로 토큰을 검증 → 사용자 자동 매핑(없으면 자동 가입).
    권한: 직위/팀에 '대표'→admin, 팀명에 '광고'→staff, 그 외→viewer(읽기전용)."""
    import requests as rq
    import secrets as pysecrets

    tok = (payload.token or "").strip().strip("/").strip()
    if not tok:
        raise HTTPException(401, "SSO 토큰이 없습니다")
    bearer = tok if tok.lower().startswith("bearer ") else "Bearer " + tok
    try:
        resp = rq.get(
            ERP_BASE_URL + ERP_MY_PROFILE_PATH,
            headers={"Authorization": bearer},
            timeout=8,
        )
    except Exception:
        raise HTTPException(502, "전산 인증 서버에 연결할 수 없습니다")
    if resp.status_code != 200:
        raise HTTPException(401, "전산 로그인이 유효하지 않습니다. 전산에 먼저 로그인해주세요.")
    result = (resp.json() or {}).get("result") or {}
    login_id = str(result.get("id") or "").strip()
    if not login_id or len(login_id) > 100:
        raise HTTPException(401, "전산 사용자 식별에 실패했습니다")
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
