"""전산(ERP) 계약 연동 — Webhook 수신 + 정기 조회 동기화 공용 로직.

명세: 리포지토리 루트 ERP_CONTRACT_SYNC_API.md.
전산 API가 준비되면 env 설정으로 활성화된다(미설정 시 graceful no-op).
  - ERP_SYNC_URL       : 전산 조회 API URL (GET /api/ad-sync/contracts)
  - ERP_SYNC_API_KEY   : 전산 조회 API 키 (헤더 X-Api-Key)
  - ERP_WEBHOOK_SECRET : 전산→광고센터 webhook 공유 비밀(헤더 X-Webhook-Secret)
  - ERP_SYNC_STATUS=1  : 업무단계→광고센터 상태 자동 반영(기본 꺼짐, 안전)
"""
import os

import requests
from sqlalchemy.orm import Session

from . import models

# 전산 업무 진행 단계 → 광고센터 status
STAGE_MAP = {
    "진행중": "active", "홀딩중": "paused", "환불중": "paused",
    "계약만료": "ended", "계약 만료": "ended",
    "사후관리": "archived", "사후 관리": "archived",
    "전략관리": "active", "전략 관리": "active",
}

# 동기화 시 전산에서 끌어올 단계 목록(양방향 상태전환을 위해 진행중 외 단계도 조회).
# 미존재 단계명은 전산이 빈 목록을 반환하므로 안전.
SYNC_STAGES = [
    "진행중", "전략관리", "전략 관리",
    "홀딩중", "환불중",
    "계약만료", "계약 만료",
    "사후관리", "사후 관리",
]


def _contract_period(contracts):
    """계약 차수들에서 (가장 이른 시작일, 가장 늦은 종료일) 추출."""
    starts = [c.get("start_date") for c in (contracts or []) if c.get("start_date")]
    ends = [c.get("end_date") for c in (contracts or []) if c.get("end_date")]
    return (min(starts) if starts else None, max(ends) if ends else None)


def status_enabled() -> bool:
    return os.environ.get("ERP_SYNC_STATUS") == "1"


def autocreate_enabled() -> bool:
    """전산 '광고센터 등록'(ad_center_registered) 켜진 업체를 자동 생성할지(기본 꺼짐)."""
    return os.environ.get("ERP_SYNC_AUTOCREATE") == "1"


def _match_owner(db: Session, sales_manager: str):
    """전산 영업담당자 이름 → 광고센터 직원(User) 매칭. 동명이인/없으면 None(미배정)."""
    mgr = (sales_manager or "").strip()
    if not mgr:
        return None
    users = db.query(models.User).filter(models.User.name == mgr).all()
    return users[0].id if len(users) == 1 else None  # 유일 일치만 자동배정(애매하면 미배정)


def upsert_company(db: Session, company: dict, apply_status: bool = False,
                   autocreate: bool = False) -> dict:
    """전산 company 1건 → 광고센터 client 매칭 후 계약기간·기본정보 upsert.

    매칭: erp_possibility_id 우선, 없으면 상호명(company_name)==client.name.
    일치 광고주 없을 때: autocreate=True 이고 전산 'ad_center_registered'가 켜진 경우에만
    신규 client 생성(전산에서 광고센터 대상으로 표시한 업체만). 그 외엔 matched=False.
    """
    name = (company.get("company_name") or "").strip()
    pid = company.get("possibility_id")
    client = None
    if pid:
        client = db.query(models.Client).filter(models.Client.erp_possibility_id == pid).first()
    if not client and name:
        client = db.query(models.Client).filter(models.Client.name == name).first()

    created = False
    if not client:
        # 자동 생성 게이트: 스위치 ON + 전산 '광고센터 등록' 플래그 ON + 상호명 존재
        if not (autocreate and company.get("ad_center_registered") and name):
            return {"matched": False, "name": name}
        client = models.Client(name=name)
        client.owner_id = _match_owner(db, company.get("sales_manager"))
        # 신규는 단계에 맞는 상태로 출생(없으면 active 기본)
        client.status = STAGE_MAP.get((company.get("stage") or "").strip()) or "active"
        db.add(client)
        created = True

    start, end = _contract_period(company.get("contracts"))
    if start:
        client.contract_start = start
    if end:
        client.contract_end = end
    if pid:
        client.erp_possibility_id = pid
    if company.get("biz_reg_name"):
        client.biz_reg_name = company["biz_reg_name"]
    if company.get("sales_manager"):
        client.sales_manager = company["sales_manager"]
    if company.get("db_grade"):
        client.db_grade = company["db_grade"]

    status_changed = None
    if apply_status and not created:
        mapped = STAGE_MAP.get((company.get("stage") or "").strip())
        # 삭제요청 대기 건은 자동 변경하지 않음(대표 처리 보호)
        if mapped and mapped != client.status and client.status != "delete_requested":
            client.status = mapped
            status_changed = mapped
    db.commit()
    return {"matched": True, "created": created, "client_id": client.id,
            "contract_start": start, "contract_end": end, "status_changed": status_changed}


def pull_sync(db: Session) -> dict:
    """전산 조회 API를 단계별로 호출 → 계약 등록 건 전수 upsert.

    상태 자동반영(ERP_SYNC_STATUS=1)이 양방향으로 작동하도록 진행중 외 단계
    (사후관리·계약만료 등)도 함께 조회한다. env 미설정 시 graceful no-op.
    """
    url = os.environ.get("ERP_SYNC_URL")
    key = os.environ.get("ERP_SYNC_API_KEY")
    if not url or not key:
        return {"ok": False, "reason": "ERP_SYNC_URL/API_KEY 미설정 — 전산 API 준비 후 활성화됩니다.",
                "matched": 0, "total": 0}
    apply_status = status_enabled()
    autocreate = autocreate_enabled()
    matched = total = created = 0
    per_stage = {}
    for stage in SYNC_STAGES:
        try:
            r = requests.get(url, headers={"X-Api-Key": key},
                             params={"stage": stage, "has_contract": "true"}, timeout=30)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"전산 연결 실패: {str(e)[:200]}",
                    "matched": matched, "total": total, "per_stage": per_stage}
        if r.status_code != 200:
            # 해당 단계만 건너뛰고 계속(미존재 단계 등). 전체 중단하지 않음.
            per_stage[stage] = f"skip({r.status_code})"
            continue
        data = r.json() or {}
        # 전산 응답은 {"status":200,"result":{"total":N,"items":[...]}} 형태 → result 언랩.
        body = data.get("result", data) if isinstance(data, dict) else {}
        items = body.get("items", []) if isinstance(body, dict) else []
        stage_matched = stage_created = 0
        for it in items:
            total += 1
            res = upsert_company(db, it, apply_status=apply_status, autocreate=autocreate)
            if res.get("matched"):
                matched += 1
                stage_matched += 1
                if res.get("created"):
                    created += 1
                    stage_created += 1
        per_stage[stage] = {"items": len(items), "matched": stage_matched, "created": stage_created}
    return {"ok": True, "total": total, "matched": matched, "created": created,
            "autocreate": autocreate,
            "apply_status": apply_status, "per_stage": per_stage}
