"""공통 의존성 — 현재 로그인 사용자 추출 + RBAC(권한) 헬퍼."""
import re

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db
from . import security, models

bearer = HTTPBearer(auto_error=False)
_SUB = re.compile(r"[1-9][0-9]{0,11}")


def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User:
    if not cred:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        payload = security.decode_token(cred.credentials)
    except Exception:
        raise HTTPException(401, "세션이 만료되었거나 유효하지 않습니다")
    sub = payload.get("sub") if isinstance(payload, dict) else None
    # 주인 번호는 1 이상 숫자 글자만(S0 — 예전엔 sub 가 없거나 숫자가 아니면 401 이 아니라 500 이 났다)
    if not isinstance(sub, str) or not _SUB.fullmatch(sub):
        raise HTTPException(401, "세션이 만료되었거나 유효하지 않습니다")
    user = db.get(models.User, int(sub))
    if not user:
        raise HTTPException(401, "사용자를 찾을 수 없습니다")
    return user


# 역할: admin(대표,전체) / lead(팀장,팀) / staff(광고팀 담당자,본인) / viewer(전 직원,읽기 전용)
EDITOR_ROLES = ("staff", "lead", "admin")


def visible_clients(db: Session, user: models.User):
    """RBAC 조회 범위: viewer·대표=전체 / 팀장=팀 / 담당자=본인. (서버에서 강제)"""
    q = db.query(models.Client)
    if user.role in ("admin", "viewer"):
        return q  # viewer는 전체를 '읽기 전용'으로 봄
    if user.role == "lead":
        return q.filter(models.Client.team_id == user.team_id)
    return q.filter(models.Client.owner_id == user.id)


def can_edit(user: models.User, client: models.Client) -> bool:
    if user.role == "viewer":
        return False
    if user.role == "admin":
        return True
    if user.role == "lead":
        return client.team_id == user.team_id
    return client.owner_id == user.id


def require_editor(user: models.User = Depends(get_current_user)) -> models.User:
    """쓰기(등록·수정·삭제)는 광고 관리팀(staff/lead) + 대표만. viewer는 차단."""
    if user.role not in EDITOR_ROLES:
        raise HTTPException(403, "읽기 전용 권한입니다. 광고 관리팀만 수정할 수 있어요.")
    return user
