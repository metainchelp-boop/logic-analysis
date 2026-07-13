"""전산(ERP) 계약 연동 수신 — Webhook + 관리자 수동 동기화.

명세: ERP_CONTRACT_SYNC_API.md. 전산 API 준비 전까지 골격(수신 준비) 상태.
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Header, Body
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from .. import models, erp_sync

router = APIRouter(tags=["erp"])


@router.post("/erp/contract-webhook")
def contract_webhook(
    payload: dict = Body(...),
    x_webhook_secret: str = Header(None),
    db: Session = Depends(get_db),
):
    """전산 푸시 수신 — 업무단계 '진행중' 전환/계약 등록 시 계약기간 반영.

    인증: 헤더 X-Webhook-Secret == env ERP_WEBHOOK_SECRET. (로그인 불필요 — 서버간 호출)
    """
    secret = os.environ.get("ERP_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(503, "webhook 시크릿이 아직 설정되지 않았습니다(전산 연동 준비 전).")
    if x_webhook_secret != secret:
        raise HTTPException(401, "인증 실패")
    company = payload.get("company") or {}
    res = erp_sync.upsert_company(db, company, apply_status=erp_sync.status_enabled())
    return {"ok": True, "event": payload.get("event"), "result": res}


@router.post("/admin/sync-contracts")
def sync_contracts(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """전산 계약 정보 수동 동기화(대표 전용). env 설정되면 실제 조회·반영."""
    if user.role != "admin":
        raise HTTPException(403, "관리자만 실행할 수 있습니다")
    return erp_sync.pull_sync(db)
