"""광고주 등록·조회·수정·삭제 (RBAC 적용, 채널 키 암호화 저장)."""
import os
import json
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_editor, visible_clients, can_edit
from .. import models, schemas, security

router = APIRouter(tags=["clients"])


def _channel_out(row: models.ChannelCredential) -> schemas.ChannelOut:
    enc = json.loads(row.fields_json or "{}")
    masked = {k: security.mask(security.decrypt(v)) for k, v in enc.items()}
    return schemas.ChannelOut(
        channel=row.channel, mode=row.mode, status=row.status, fields_masked=masked
    )


def _client_out(db: Session, client: models.Client) -> schemas.ClientOut:
    chans = (
        db.query(models.ChannelCredential)
        .filter(models.ChannelCredential.client_id == client.id)
        .all()
    )
    owner = db.get(models.User, client.owner_id) if client.owner_id else None
    connected = sum(1 for c in chans if c.status == "connected")
    return schemas.ClientOut(
        id=client.id,
        name=client.name,
        category=client.category,
        status=client.status,
        owner_id=client.owner_id,
        owner_name=owner.name if owner else None,
        contact=client.contact,
        contract_start=client.contract_start,
        contract_end=client.contract_end,
        biz_reg_name=client.biz_reg_name,
        sales_manager=client.sales_manager,
        db_grade=client.db_grade,
        memo=client.memo,
        channels=[_channel_out(c) for c in chans],
        connected_count=connected,
    )


def _save_channels(db: Session, client_id: int, channels: list[schemas.ChannelIn]):
    """채널 키 병합 저장 — 입력된 값만 갱신, 빈 칸은 기존 키 유지(편집 시 비밀키 보존)."""
    existing = {
        c.channel: c
        for c in db.query(models.ChannelCredential)
        .filter(models.ChannelCredential.client_id == client_id)
        .all()
    }
    touched = []  # 이번 호출에서 값이 들어와 (재)연동된 채널 키
    for ch in channels:
        row = existing.get(ch.channel)
        cur = json.loads(row.fields_json) if row else {}
        applied = False
        for k, v in ch.fields.items():
            if v:  # 입력된 값만 암호화·갱신
                cur[k] = security.encrypt(v)
                applied = True
        status = "connected" if cur else "disconnected"
        if row:
            row.fields_json = json.dumps(cur)
            row.status = status
            row.mode = ch.mode
        else:
            db.add(
                models.ChannelCredential(
                    client_id=client_id,
                    channel=ch.channel,
                    mode=ch.mode,
                    status=status,
                    fields_json=json.dumps(cur),
                )
            )
        if applied and status == "connected":
            touched.append(ch.channel)
    return touched


def log_activity(db: Session, client_id: int, user, type_: str, message: str, meta: dict = None):
    """광고주 진행 이력 한 줄 기록(커밋은 호출부에서). 내역서·홈 경고의 원천."""
    db.add(models.ActivityLog(
        client_id=client_id,
        user_id=getattr(user, "id", None),
        user_name=(getattr(user, "name", None) or "시스템"),
        type=type_, message=message,
        meta_json=json.dumps(meta or {}, ensure_ascii=False),
    ))


@router.get("/clients", response_model=list[schemas.ClientOut])
def list_clients(
    scope: str = "home",
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    """scope=home(기본): 담당자 홈용 — 삭제요청·보관 광고주 제외 / scope=all: 현황 페이지용 전체."""
    q = visible_clients(db, user)
    if scope != "all":
        q = q.filter(~models.Client.status.in_(["delete_requested", "archived"]))
    rows = q.order_by(models.Client.created_at.desc()).all()
    return [_client_out(db, c) for c in rows]


@router.get("/clients/{client_id}", response_model=schemas.ClientOut)
def get_client(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    return _client_out(db, client)


@router.post("/clients", response_model=schemas.ClientOut)
def create_client(
    payload: schemas.ClientIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    # 담당자 지정: 팀장/대표만 타인 지정 가능, 그 외엔 본인
    owner_id = user.id
    if payload.owner_id and user.role in ("lead", "admin"):
        owner_id = payload.owner_id
    owner = db.get(models.User, owner_id)
    client = models.Client(
        name=payload.name,
        category=payload.category,
        status=payload.status,
        owner_id=owner_id,
        team_id=owner.team_id if owner else user.team_id,
        contact=payload.contact,
        contract_start=payload.contract_start,
        contract_end=payload.contract_end,
        memo=payload.memo,
    )
    db.add(client)
    db.flush()  # client.id 확보
    touched = _save_channels(db, client.id, payload.channels)
    log_activity(db, client.id, user, "client_created", f"광고주 '{client.name}' 등록")
    for ch in touched:
        log_activity(db, client.id, user, "channel_connected", f"{CHANNEL_LABELS.get(ch, ch)} 연동")
    db.commit()
    db.refresh(client)
    return _client_out(db, client)


@router.put("/clients/{client_id}", response_model=schemas.ClientOut)
def update_client(
    client_id: int,
    payload: schemas.ClientIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    client.name = payload.name
    client.category = payload.category
    client.status = payload.status
    client.contact = payload.contact
    client.contract_start = payload.contract_start
    client.contract_end = payload.contract_end
    client.memo = payload.memo
    if payload.owner_id and user.role in ("lead", "admin"):
        client.owner_id = payload.owner_id
        owner = db.get(models.User, payload.owner_id)
        if owner:
            client.team_id = owner.team_id
    touched = _save_channels(db, client.id, payload.channels)
    log_activity(db, client.id, user, "client_updated", "광고주 정보 수정")
    for ch in touched:
        log_activity(db, client.id, user, "channel_connected", f"{CHANNEL_LABELS.get(ch, ch)} 연동 갱신")
    db.commit()
    db.refresh(client)
    return _client_out(db, client)


@router.delete("/clients/{client_id}")
def delete_client(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """전면 삭제 — 학습 데이터 보존 정책상 관리자(대표) 전용 비상 수단. 일반 흐름은 삭제요청→보관."""
    if user.role != "admin":
        raise HTTPException(403, "전면 삭제는 대표(관리자)만 가능합니다. '삭제 요청'을 사용하세요.")
    client = db.get(models.Client, client_id)
    if not client:
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    db.query(models.ChannelCredential).filter(
        models.ChannelCredential.client_id == client_id
    ).delete()
    db.delete(client)
    db.commit()
    return {"ok": True}


# ===== 삭제 요청 워크플로 (요청 → 대표 승인 → 보관소) =====

@router.post("/clients/{client_id}/request-delete")
def request_delete(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    """마케터가 삭제 요청 — 즉시 담당자 홈에서 숨겨지고, 대표 승인 대기."""
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    if client.status == "archived":
        raise HTTPException(400, "이미 보관된 광고주입니다")
    from datetime import datetime, timezone, timedelta

    client.status = "delete_requested"
    client.delete_requested_by = user.id
    client.delete_requested_at = datetime.now(timezone(timedelta(hours=9))).isoformat()
    log_activity(db, client_id, user, "status_changed", "삭제 요청(대표 승인 대기)", {"to": "delete_requested"})
    db.commit()
    return {"ok": True, "status": client.status}


def _admin_only(user: models.User):
    if user.role != "admin":
        raise HTTPException(403, "대표(관리자)만 처리할 수 있습니다")


@router.post("/clients/{client_id}/confirm-delete")
def confirm_delete(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """대표 승인 → 보관소로 이동(모든 기능 일시정지, 데이터는 학습용 보존)."""
    _admin_only(user)
    client = db.get(models.Client, client_id)
    if not client or client.status != "delete_requested":
        raise HTTPException(400, "삭제 요청 상태의 광고주가 아닙니다")
    client.status = "archived"
    log_activity(db, client_id, user, "status_changed", "삭제 승인 → 보관소 이동(기능 일시정지)", {"to": "archived"})
    db.commit()
    return {"ok": True, "status": "archived"}


@router.post("/clients/{client_id}/reject-delete")
def reject_delete(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """대표 거부 → 다시 진행중으로 복귀."""
    _admin_only(user)
    client = db.get(models.Client, client_id)
    if not client or client.status != "delete_requested":
        raise HTTPException(400, "삭제 요청 상태의 광고주가 아닙니다")
    client.status = "active"
    client.delete_requested_by = None
    client.delete_requested_at = None
    log_activity(db, client_id, user, "status_changed", "삭제 요청 거부 → 진행중 복귀", {"to": "active"})
    db.commit()
    return {"ok": True, "status": "active"}


@router.post("/clients/{client_id}/restore")
def restore_client(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """보관소에서 복원 (대표 전용)."""
    _admin_only(user)
    client = db.get(models.Client, client_id)
    if not client or client.status != "archived":
        raise HTTPException(400, "보관 상태의 광고주가 아닙니다")
    client.status = "active"
    client.delete_requested_by = None
    client.delete_requested_at = None
    log_activity(db, client_id, user, "status_changed", "보관소에서 복원 → 진행중", {"to": "active"})
    db.commit()
    return {"ok": True, "status": "active"}


@router.get("/learning/collection-status")
def collection_status(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """학습센터 — 회사에 '실제로 쌓이는' 데이터 수집 현황(포괄)."""
    _admin_only(user)
    from sqlalchemy import func as F
    M = models.ChannelMetric
    CC = models.ChannelCredential

    total_snapshots = db.query(M).count()
    clients_with_data = db.query(F.count(F.distinct(M.client_id))).scalar() or 0
    first_at = db.query(F.min(M.collected_at)).scalar()
    last_at = db.query(F.max(M.collected_at)).scalar()
    connected = db.query(CC).filter(CC.status == "connected").count()
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # collected_at은 naive UTC

    # 채널별 수집 현황(스냅샷·마지막수집·신선도) + 연동 수
    conn_by_ch = dict(
        db.query(CC.channel, F.count(CC.id)).filter(CC.status == "connected")
        .group_by(CC.channel).all()
    )
    snap_rows = db.query(M.channel, F.count(M.id), F.max(M.collected_at)).group_by(M.channel).all()
    by_channel = []
    seen = set()
    for ch, cnt, mx in snap_rows:
        seen.add(ch)
        fresh = bool(mx and (now - mx).total_seconds() < 48 * 3600)
        by_channel.append({"channel": ch, "label": CHANNEL_LABELS.get(ch, ch),
                           "snapshots": cnt, "connected_clients": conn_by_ch.get(ch, 0),
                           "last_at": (mx.isoformat() + "Z") if mx else None, "fresh": fresh})
    for ch, cc in conn_by_ch.items():  # 연동했지만 수집 0인 채널
        if ch not in seen:
            by_channel.append({"channel": ch, "label": CHANNEL_LABELS.get(ch, ch),
                               "snapshots": 0, "connected_clients": cc,
                               "last_at": None, "fresh": False})
    by_channel.sort(key=lambda x: -x["snapshots"])

    # 최근 14일 일별 수집 건수
    tl = dict(db.query(F.date(M.collected_at), F.count(M.id)).group_by(F.date(M.collected_at)).all())
    today = datetime.now(timezone(timedelta(hours=9))).date()
    timeline = [{"date": (today - timedelta(days=i)).isoformat(),
                 "count": int(tl.get((today - timedelta(days=i)).isoformat(), 0))}
                for i in range(13, -1, -1)]

    # 업종별 분포(광고주 수·스냅샷 수)
    cli_by_cat = dict(db.query(models.Client.category, F.count(F.distinct(models.Client.id)))
                      .group_by(models.Client.category).all())
    snap_by_cat = dict(db.query(models.Client.category, F.count(M.id))
                       .join(M, M.client_id == models.Client.id)
                       .group_by(models.Client.category).all())
    by_category = sorted(
        [{"category": c or "미분류", "clients": n, "snapshots": int(snap_by_cat.get(c, 0))}
         for c, n in cli_by_cat.items()],
        key=lambda x: -x["snapshots"])

    # 학습 활용(오토파일럿·예약 켜진 수)
    autopilot_on = schedule_on = 0
    for s in db.query(models.ClientSetting).all():
        try:
            v = json.loads(s.value_json or "{}")
        except Exception:  # noqa: BLE001
            continue
        if s.key == "autopilot" and v.get("enabled"):
            autopilot_on += 1
        elif s.key == "report_schedule" and v.get("enabled"):
            schedule_on += 1

    proposals = db.query(models.CampaignProposal).count()
    applied = db.query(models.CampaignProposal).filter(models.CampaignProposal.status == "applied").count()
    reports = db.query(models.Report).count()
    activities = db.query(models.ActivityLog).count()
    days_span = ((last_at - first_at).days + 1) if (first_at and last_at) else 0

    return {
        "summary": {
            "snapshots": total_snapshots, "clients_with_data": clients_with_data,
            "connected_credentials": connected, "days_span": days_span,
            "first_at": (first_at.isoformat() + "Z") if first_at else None,
            "last_at": (last_at.isoformat() + "Z") if last_at else None,
        },
        "by_channel": by_channel, "timeline": timeline, "by_category": by_category,
        "data_types": {
            "snapshots": total_snapshots, "reports": reports, "proposals": proposals,
            "proposals_applied": applied, "activities": activities,
            "autopilot_on": autopilot_on, "schedule_on": schedule_on,
        },
    }


@router.get("/learning/stats")
def learning_stats(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """학습센터 — 회사에 축적된 광고 데이터 현황(추후 AI 캠페인 자동화·전략 학습의 재료)."""
    _admin_only(user)
    from sqlalchemy import func as safunc

    by_status = dict(
        db.query(models.Client.status, safunc.count()).group_by(models.Client.status).all()
    )
    per_client = (
        db.query(
            models.Client.id, models.Client.name, models.Client.status,
            safunc.count(models.ChannelMetric.id),
        )
        .outerjoin(models.ChannelMetric, models.ChannelMetric.client_id == models.Client.id)
        .group_by(models.Client.id)
        .all()
    )
    return {
        "clients_total": db.query(models.Client).count(),
        "clients_by_status": by_status,
        "connected_credentials": db.query(models.ChannelCredential)
            .filter(models.ChannelCredential.status == "connected").count(),
        "metric_snapshots": db.query(models.ChannelMetric).count(),
        "reports": db.query(models.Report).count(),
        "per_client": [
            {"id": i, "name": n, "status": s, "snapshots": c} for i, n, s, c in per_client
        ],
    }


CHANNEL_LABELS = {
    "naver_searchad": "네이버 검색광고",
    "naver_commerce": "네이버 커머스",
    "meta_chehum": "메타체험단(체험단 캠페인)",
    "youtube": "유튜브(영상 성과)",
    "meta_ads": "메타 광고(인스타·페북)",
    "kakao": "카카오모먼트",
    "coupang_ads": "쿠팡애즈",
    "naver_gfa": "네이버 GFA(성과형 디스플레이)",
    "daangn": "당근",
    "toss_ads": "토스애즈",
    "mobon": "모비온",
}


def _fetch_ads_channel(channel: str, fields: dict, days: int = 30, date_from=None, date_to=None) -> dict:
    """광고비 집행형 채널(메타·카카오·쿠팡·GFA) 공용 디스패치 — 정규화 형태 반환.

    필수 입력값이 없으면 KeyError를 던진다(호출부에서 처리).
    """
    if channel == "meta_ads":
        from ..adapters import meta_ads

        return meta_ads.fetch_performance(
            fields["account_id"], fields["access_token"],
            date_from=date_from, date_to=date_to, days=days,
        )
    if channel == "kakao":
        from ..adapters import kakao

        return kakao.fetch_performance(
            fields["account_id"], fields["rest_key"],
            date_from=date_from, date_to=date_to, days=days,
        )
    if channel == "coupang_ads":
        from ..adapters import coupang_ads

        return coupang_ads.fetch_performance(
            fields["vendor_id"], fields["access_key"], fields["secret_key"],
            date_from=date_from, date_to=date_to, days=days,
        )
    if channel == "naver_gfa":
        from ..adapters import naver_gfa

        return naver_gfa.fetch_performance(
            fields["account_id"], fields["api_key"],
            date_from=date_from, date_to=date_to, days=days,
        )
    raise ValueError(f"unknown ads channel: {channel}")


def _gather_perf(db: Session, client_id: int, date_from: str, date_to: str) -> dict:
    """연동(connected)된 모든 채널의 성과를 {channel: {label, data|error}}로 모은다.

    AI 리포트·대시보드 공용. 새 매체는 어댑터 분기만 추가하면 자동으로 리포트에 반영된다.
    """
    rows = (
        db.query(models.ChannelCredential)
        .filter(
            models.ChannelCredential.client_id == client_id,
            models.ChannelCredential.status == "connected",
        )
        .all()
    )
    out: dict = {}
    for row in rows:
        fields = {
            k: security.decrypt(v) for k, v in json.loads(row.fields_json or "{}").items()
        }
        label = CHANNEL_LABELS.get(row.channel, row.channel)
        try:
            if row.mode == "upload":
                # 엑셀/일괄 업로드로 채운 채널(GFA 등 API 미개통 포함) — 마지막 스냅샷 사용
                latest = (
                    db.query(models.ChannelMetric)
                    .filter(
                        models.ChannelMetric.client_id == client_id,
                        models.ChannelMetric.channel == row.channel,
                    )
                    .order_by(models.ChannelMetric.id.desc())
                    .first()
                )
                if not latest:
                    continue
                data = json.loads(latest.payload_json or "{}")
            elif row.channel == "naver_searchad":
                from ..adapters import naver_searchad

                data = naver_searchad.fetch_performance(
                    fields["api_license"], fields["secret_key"], fields["customer_id"],
                    date_from=date_from, date_to=date_to,
                )
            elif row.channel == "meta_chehum":
                from ..adapters import meta_chehum

                data = meta_chehum.fetch_performance(fields["advertiser_id"])
            elif row.channel == "youtube":
                from ..adapters import youtube

                data = youtube.fetch_performance(fields["video_url"])
            elif row.channel in ("meta_ads", "kakao", "coupang_ads", "naver_gfa"):
                data = _fetch_ads_channel(
                    row.channel, fields, date_from=date_from, date_to=date_to
                )
            elif row.channel in MANUAL_CHANNELS:
                # API 없는 채널 — 마지막 업로드/수동 스냅샷을 사용
                latest = (
                    db.query(models.ChannelMetric)
                    .filter(
                        models.ChannelMetric.client_id == client_id,
                        models.ChannelMetric.channel == row.channel,
                    )
                    .order_by(models.ChannelMetric.id.desc())
                    .first()
                )
                if not latest:
                    continue
                data = json.loads(latest.payload_json or "{}")
            else:
                continue  # 아직 어댑터가 없는 채널은 건너뜀(연동 추가 시 분기만 보강)
            out[row.channel] = {"label": label, "data": data}
        except Exception as e:  # noqa: BLE001 — 한 채널 실패가 보고서 전체를 막지 않게
            out[row.channel] = {"label": label, "error": str(e)[:300]}
    return out


@router.post("/clients/{client_id}/reports")
def create_report(
    client_id: int,
    date_from: str,
    date_to: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    """기간 지정 AI 결과보고서 생성 — 성과 수집 → AI 코멘트(피드백 4단계) → 저장."""
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")

    from .. import report_ai

    perf = _gather_perf(db, client_id, date_from, date_to)
    if not perf:
        raise HTTPException(400, "연동된 채널이 없습니다. 먼저 채널을 연동하세요.")
    ai = report_ai.generate(client.name, client.category, date_from, date_to, perf)
    row = models.Report(
        client_id=client_id, date_from=date_from, date_to=date_to,
        data_json=json.dumps(perf, ensure_ascii=False),
        report_json=json.dumps(ai, ensure_ascii=False),
        created_by=user.id,
    )
    db.add(row)
    log_activity(db, client_id, user, "report_created",
                 f"AI 결과보고서 생성 ({date_from}~{date_to})",
                 {"channels": list(perf.keys())})
    db.commit()
    db.refresh(row)
    return {
        "id": row.id, "client_id": client_id, "client_name": client.name,
        "date_from": date_from, "date_to": date_to,
        "created_at": row.created_at.isoformat() + "Z",
        "data": perf, "report": ai,
    }


@router.get("/clients/{client_id}/reports")
def list_reports(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    client = db.get(models.Client, client_id)
    if not client or (not can_edit(user, client) and user.role != "viewer"):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    rows = (
        db.query(models.Report)
        .filter(models.Report.client_id == client_id)
        .order_by(models.Report.created_at.desc())
        .limit(30)
        .all()
    )
    return [
        {
            "id": r.id, "date_from": r.date_from, "date_to": r.date_to,
            "created_at": (r.created_at.isoformat() + "Z") if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/reports/{report_id}")
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    r = db.get(models.Report, report_id)
    if not r:
        raise HTTPException(404, "보고서를 찾을 수 없습니다")
    client = db.get(models.Client, r.client_id)
    if not client or (not can_edit(user, client) and user.role != "viewer"):
        raise HTTPException(404, "보고서를 찾을 수 없습니다")
    return {
        "id": r.id, "client_id": r.client_id, "client_name": client.name,
        "date_from": r.date_from, "date_to": r.date_to,
        "created_at": (r.created_at.isoformat() + "Z") if r.created_at else None,
        "data": json.loads(r.data_json or "{}"),
        "report": json.loads(r.report_json or "{}"),
    }


# ════════════════════════════════════════════════════════════════════════
# AI 캠페인 제안 → (대표 승인) → 검색광고 실제 적용
# ════════════════════════════════════════════════════════════════════════

def _proposal_out(db: Session, row: models.CampaignProposal) -> dict:
    return {
        "id": row.id, "client_id": row.client_id,
        "objective": row.objective, "monthly_budget": row.monthly_budget,
        "status": row.status,
        "proposal": json.loads(row.proposal_json or "{}"),
        "apply_result": json.loads(row.apply_result_json or "{}"),
        "created_at": (row.created_at.isoformat() + "Z") if row.created_at else None,
        "applied_at": row.applied_at,
    }


@router.post("/clients/{client_id}/campaign-proposals")
def create_campaign_proposal(
    client_id: int,
    objective: str = Body("", embed=True),
    monthly_budget: int = Body(..., embed=True),
    channels: list = Body(None, embed=True),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    """실제 광고주 데이터로 AI 캠페인안 생성(제안만, 실제 세팅 안 함). channels=진행할 매체 키 목록."""
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    if not monthly_budget or monthly_budget <= 0:
        raise HTTPException(400, "월 광고 예산을 입력하세요")

    from .. import campaign_ai

    allowed = set(campaign_ai.CH_LABELS.keys())
    chosen = [c for c in (channels or []) if c in allowed]
    if not chosen:
        raise HTTPException(400, "진행할 매체를 1개 이상 선택하세요")

    # 최근 30일 성과를 근거로 사용(연동 채널 자동 종합)
    today = datetime.now(timezone(timedelta(hours=9))).date()
    perf = _gather_perf(db, client_id,
                        (today - timedelta(days=30)).isoformat(), today.isoformat())
    proposal = campaign_ai.generate(
        client.name, client.category, objective, monthly_budget, perf, channels=chosen
    )
    proposal["selected_channels"] = chosen  # 선택 매체 기록(표시·적용 분기용)
    row = models.CampaignProposal(
        client_id=client_id, objective=objective, monthly_budget=monthly_budget,
        proposal_json=json.dumps(proposal, ensure_ascii=False),
        status="draft", created_by=user.id,
    )
    db.add(row)
    log_activity(db, client_id, user, "campaign_proposal_created",
                 f"AI 캠페인안 생성 (월 예산 {monthly_budget:,}원)",
                 {"objective": objective})
    db.commit()
    db.refresh(row)
    return _proposal_out(db, row)


@router.get("/clients/{client_id}/campaign-proposals")
def list_campaign_proposals(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    client = db.get(models.Client, client_id)
    if not client or (not can_edit(user, client) and user.role != "viewer"):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    rows = (
        db.query(models.CampaignProposal)
        .filter(models.CampaignProposal.client_id == client_id)
        .order_by(models.CampaignProposal.created_at.desc())
        .limit(30)
        .all()
    )
    return [_proposal_out(db, r) for r in rows]


@router.post("/campaign-proposals/{pid}/apply")
def apply_campaign_proposal(
    pid: int,
    dry_run: bool = Body(True, embed=True),
    confirm: bool = Body(False, embed=True),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """캠페인안을 검색광고에 적용. dry_run=True(기본)=미리보기, False=실제 생성(대표만·일시중지).

    가드레일: 실제 적용은 admin만 + confirm=True 필수 + 예산 한도 검사 + 일시중지 생성.
    """
    row = db.get(models.CampaignProposal, pid)
    if not row:
        raise HTTPException(404, "캠페인안을 찾을 수 없습니다")
    client = db.get(models.Client, row.client_id)
    if not client:
        raise HTTPException(404, "광고주를 찾을 수 없습니다")

    live = not dry_run
    if live:
        if user.role != "admin":
            raise HTTPException(403, "실제 적용은 대표(관리자)만 할 수 있습니다")
        if not confirm:
            raise HTTPException(400, "실제 적용은 확인(confirm)이 필요합니다")
    elif not can_edit(user, client) and user.role != "viewer":
        raise HTTPException(403, "권한이 없습니다")

    cred = (
        db.query(models.ChannelCredential)
        .filter(
            models.ChannelCredential.client_id == row.client_id,
            models.ChannelCredential.channel == "naver_searchad",
            models.ChannelCredential.status == "connected",
        )
        .first()
    )
    if not cred:
        raise HTTPException(400, "검색광고가 연동돼 있어야 적용할 수 있습니다. 먼저 검색광고 키를 연동하세요.")
    fields = {k: security.decrypt(v) for k, v in json.loads(cred.fields_json or "{}").items()}

    from ..adapters import naver_searchad

    proposal = json.loads(row.proposal_json or "{}")
    result = naver_searchad.apply_plan(
        fields["api_license"], fields["secret_key"], fields["customer_id"],
        proposal, live=live, monthly_budget=row.monthly_budget or 0,
    )
    if live:
        row.status = "applied"
        row.applied_by = user.id
        row.applied_at = datetime.now(timezone(timedelta(hours=9))).isoformat()
        row.apply_result_json = json.dumps(result, ensure_ascii=False)
        log_activity(db, row.client_id, user, "campaign_applied",
                     "AI 캠페인안 실제 적용(검색광고·일시중지 생성)",
                     {"proposal_id": pid})
        db.commit()
    return result


# ════════════════════════════════════════════════════════════════════════
# 팀·전체 현황 / 시스템 키 / 직원·권한 (설정·관리)
# ════════════════════════════════════════════════════════════════════════

# 관제 허브: 광고주 연동 상태를 한 단어로 판정한다.
#   connected(연동완료) / link_sent(요청 링크 발송, 미제출) / link_expired(링크 만료)
#   / not_requested(아직 요청 안 함)
# ★'보이는 매체' 기준이 아니라 전체 연동 여부로 판정하되, 화면 쪽에서 네이버 계열만 따로 센다.
def _connect_state(conn_channels: list, link, now_iso: str) -> str:
    if conn_channels:
        return "connected"
    if link is None:
        return "not_requested"
    if (link.expires_at or "") and link.expires_at < now_iso:
        return "link_expired"
    return "link_sent"


@router.get("/team/overview")
def team_overview(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """전사/팀 광고주 현황 — 광고주별 최신 KPI 합산 + 경고. 범위는 visible_clients가 강제."""
    clients = visible_clients(db, user).all()
    ids = [c.id for c in clients]
    # 관제 허브용 부가정보를 한 번에 모아둔다(광고주마다 개별 조회하면 수백 쿼리가 된다).
    links = {}      # client_id -> 가장 최근 연동요청 링크
    notes = {}      # client_id -> 최신 담당자 메모
    if ids:
        for lk in (db.query(models.ConnectLink)
                   .filter(models.ConnectLink.client_id.in_(ids))
                   .order_by(models.ConnectLink.id.desc()).all()):
            links.setdefault(lk.client_id, lk)
        for lg in (db.query(models.ActivityLog)
                   .filter(models.ActivityLog.client_id.in_(ids),
                           models.ActivityLog.type == "note")
                   .order_by(models.ActivityLog.id.desc()).all()):
            notes.setdefault(lg.client_id, lg)
    now_iso = _now_kst_iso()
    rows = []
    totals = {"clients": 0, "spend": 0, "revenue": 0, "connected": 0, "alerts": 0}
    status_cnt = {"active": 0, "paused": 0, "archived": 0, "delete_requested": 0}
    chan_agg = {}  # 채널별 합산(전 광고주 최신 스냅샷)
    for c in clients:
        status_cnt[c.status] = status_cnt.get(c.status, 0) + 1
        metrics = (
            db.query(models.ChannelMetric)
            .filter(models.ChannelMetric.client_id == c.id)
            .order_by(models.ChannelMetric.id.desc())
            .all()
        )
        latest, prev = {}, {}
        for m in metrics:
            if m.channel not in latest:
                latest[m.channel] = m
            elif m.channel not in prev:
                prev[m.channel] = m
        spend = revenue = 0
        anomalies = []
        for ch, m in latest.items():
            try:
                data = json.loads(m.payload_json or "{}")
            except Exception:  # noqa: BLE001
                continue
            k = _extract_kpi(ch, data)
            if k:
                spend += k.get("spend") or 0
                rev_ch = (k.get("spend") or 0) * (k.get("roas") or 0) / 100 if k.get("roas") else 0
                revenue += rev_ch
                a = chan_agg.setdefault(ch, {"imp": 0, "clk": 0, "spend": 0, "rev": 0, "clients": 0})
                a["imp"] += k.get("imp") or 0
                a["clk"] += k.get("clk") or 0
                a["spend"] += k.get("spend") or 0
                a["rev"] += rev_ch
                a["clients"] += 1
            pdata = None
            if ch in prev:
                try:
                    pdata = json.loads(prev[ch].payload_json)
                except Exception:  # noqa: BLE001
                    pdata = None
            for sev, reason in _channel_anomalies(ch, data, pdata):
                anomalies.append({"severity": sev, "reason": reason})
        conn_rows = (
            db.query(models.ChannelCredential.channel)
            .filter(
                models.ChannelCredential.client_id == c.id,
                models.ChannelCredential.status == "connected",
            )
            .all()
        )
        # 연동 채널 키 목록도 함께 내려준다 — 화면에서 '보이는 채널'만 세려면 키가 필요하다
        # (숫자만 주면 숨긴 매체까지 포함돼 연동 실태가 과대표시된다).
        conn_channels = [r[0] for r in conn_rows]
        connected = len(conn_channels)
        owner = db.get(models.User, c.owner_id) if c.owner_id else None
        roas = round(revenue / spend * 100, 1) if spend > 0 else None
        rows.append({
            "id": c.id, "name": c.name, "category": c.category, "status": c.status,
            "owner_name": owner.name if owner else None,
            "connected": connected, "connected_channels": conn_channels,
            "spend": round(spend), "roas": roas,
            "alerts": anomalies,
            "connect_state": _connect_state(conn_channels, links.get(c.id), now_iso),
            "note": (notes[c.id].message if c.id in notes else None),
            "note_at": (notes[c.id].created_at.strftime("%m/%d") if c.id in notes and notes[c.id].created_at else None),
            "last_collected": max((m.collected_at for m in latest.values() if m.collected_at), default=None),
        })
        totals["clients"] += 1
        totals["spend"] += spend
        totals["revenue"] += revenue
        totals["connected"] += connected
        totals["alerts"] += len(anomalies)
    avg_roas = round(totals["revenue"] / totals["spend"] * 100, 1) if totals["spend"] > 0 else None
    rows.sort(key=lambda r: (0 if r["alerts"] else 1, -(r["spend"] or 0)))
    by_channel = sorted(
        [{"channel": ch, "label": CHANNEL_LABELS.get(ch, ch), "clients": a["clients"],
          "impressions": round(a["imp"]), "clicks": round(a["clk"]), "spend": round(a["spend"]),
          "roas": round(a["rev"] / a["spend"] * 100, 1) if a["spend"] > 0 else None}
         for ch, a in chan_agg.items()],
        key=lambda x: -(x["spend"] or 0))
    return {
        "clients": rows,
        "totals": {
            "clients": totals["clients"], "spend": round(totals["spend"]),
            "revenue": round(totals["revenue"]), "avg_roas": avg_roas,
            "connected": totals["connected"], "alerts": totals["alerts"],
        },
        "by_channel": by_channel,
        "status_counts": status_cnt,
    }


@router.get("/team/spend-by-month")
def spend_by_month(
    month: str = "",
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """선택 월의 광고주별 광고비 소진액 합산 — 그 달 기간으로 각 매체에 직접 조회(정확).

    범위는 visible_clients가 강제(담당자=본인 광고주). API 매체는 기간 조회로 정확,
    엑셀 업로드 매체(당근 등)는 최근 업로드값 기준(기간 조회 불가).
    """
    now = datetime.now(timezone(timedelta(hours=9)))
    if not month:
        month = now.strftime("%Y-%m")
    try:
        y, m = int(month[:4]), int(month[5:7])
        start = datetime(y, m, 1)
        end = (datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)) - timedelta(days=1)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "월 형식이 올바르지 않습니다 (YYYY-MM)")
    df, dt = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    clients = visible_clients(db, user).filter(
        models.Client.status.in_(["active", "paused"])).all()
    rows, total, chan_tot = [], 0, {}
    for c in clients:
        perf = _gather_perf(db, c.id, df, dt)
        spend, by_ch = 0, {}
        for ch, info in perf.items():
            data = info.get("data")
            if not data:
                continue
            k = _extract_kpi(ch, data)
            if k and (k.get("spend") or 0) > 0:
                sp = k["spend"]
                spend += sp
                by_ch[ch] = round(by_ch.get(ch, 0) + sp)
                chan_tot[ch] = chan_tot.get(ch, 0) + sp
        if spend > 0:
            rows.append({
                "id": c.id, "name": c.name, "spend": round(spend),
                "channels": [{"channel": ch, "label": CHANNEL_LABELS.get(ch, ch), "spend": v}
                             for ch, v in sorted(by_ch.items(), key=lambda x: -x[1])],
            })
        total += spend
    rows.sort(key=lambda r: -r["spend"])
    by_channel = [{"channel": ch, "label": CHANNEL_LABELS.get(ch, ch), "spend": round(v)}
                  for ch, v in sorted(chan_tot.items(), key=lambda x: -x[1])]
    return {"month": month, "date_from": df, "date_to": dt,
            "total": round(total), "clients": rows, "by_channel": by_channel,
            "client_count": len(clients)}


def _cur_month():
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m")


@router.post("/records/monthly/close")
def close_monthly(month: str = "", db: Session = Depends(get_db),
                  user: models.User = Depends(require_editor)):
    """현재(실시간) 월별 소진을 '확정 기록'으로 스냅샷 저장. 같은 달 재마감 시 덮어쓴다(visible 범위)."""
    m = month or _cur_month()
    live = spend_by_month(m, db, user)  # 실시간 누적값
    vis_ids = [c.id for c in visible_clients(db, user).all()]
    if vis_ids:
        db.query(models.MonthlyRecord).filter(
            models.MonthlyRecord.month == m,
            models.MonthlyRecord.client_id.in_(vis_ids),
        ).delete(synchronize_session=False)
    for r in live["clients"]:
        db.add(models.MonthlyRecord(
            month=m, client_id=r["id"], client_name=r["name"],
            total_spend=r["spend"], channels_json=json.dumps(r["channels"], ensure_ascii=False),
            recorded_by=user.id, recorded_by_name=user.name,
        ))
    db.commit()
    return {"ok": True, "month": m, "saved": len(live["clients"]), "total": live["total"]}


@router.get("/records/monthly")
def get_monthly(month: str = "", db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    """저장된 월별 확정 기록 조회(읽기 — 전 직원). 없으면 빈 목록."""
    m = month or _cur_month()
    vis_ids = [c.id for c in visible_clients(db, user).all()]
    rows = []
    if vis_ids:
        rows = (db.query(models.MonthlyRecord)
                .filter(models.MonthlyRecord.month == m,
                        models.MonthlyRecord.client_id.in_(vis_ids))
                .all())
    clients = [{"id": r.client_id, "name": r.client_name, "spend": r.total_spend,
                "channels": json.loads(r.channels_json or "[]")} for r in rows]
    clients.sort(key=lambda x: -x["spend"])
    chan = {}
    for c in clients:
        for ch in c["channels"]:
            chan[ch["channel"]] = chan.get(ch["channel"], 0) + ch["spend"]
    by_channel = [{"channel": k, "label": CHANNEL_LABELS.get(k, k), "spend": v}
                  for k, v in sorted(chan.items(), key=lambda x: -x[1])]
    rec = rows[0] if rows else None
    return {"month": m, "total": sum(c["spend"] for c in clients), "clients": clients,
            "by_channel": by_channel, "count": len(clients),
            "recorded_by": rec.recorded_by_name if rec else None,
            "recorded_at": rec.recorded_at.isoformat() if (rec and rec.recorded_at) else None}


@router.get("/records/monthly/months")
def monthly_months(db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    """확정 기록이 있는 월 목록(최신순)."""
    vis_ids = [c.id for c in visible_clients(db, user).all()]
    months = []
    if vis_ids:
        rows = (db.query(models.MonthlyRecord.month)
                .filter(models.MonthlyRecord.client_id.in_(vis_ids))
                .distinct().all())
        months = sorted({r[0] for r in rows}, reverse=True)
    return {"months": months}


@router.get("/admin/system-keys")
def system_keys(user: models.User = Depends(get_current_user)):
    """회사 공용 키 설정 현황(값은 노출하지 않고 설정 여부만). 관리자 전용."""
    _admin_only(user)
    keys = [
        ("ANTHROPIC_API_KEY", "AI(Claude) — 보고서·캠페인 설계", "claude"),
        ("YOUTUBE_API_KEY", "유튜브 — 영상 조회수·좋아요 수집", "youtube"),
        ("MC_AD_API_TOKEN", "메타체험단 — 캠페인 결과 연동", "chehum"),
        ("JWT_SECRET", "로그인 보안(세션 서명)", "security"),
    ]
    return {"keys": [
        {"name": n, "label": label, "icon": icon, "set": bool(os.environ.get(n, "").strip())}
        for n, label, icon in keys
    ]}


@router.get("/admin/users")
def list_users(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """직원·권한 목록 — 담당 광고주 수 포함. 관리자 전용."""
    _admin_only(user)
    users = db.query(models.User).order_by(models.User.id).all()
    out = []
    for u in users:
        cnt = db.query(models.Client).filter(models.Client.owner_id == u.id).count()
        team = db.get(models.Team, u.team_id) if u.team_id else None
        out.append({
            "id": u.id, "name": u.name, "email": u.email, "role": u.role,
            "team": team.name if team else None, "clients": cnt,
            "is_me": u.id == user.id,
        })
    return out


@router.put("/admin/users/{uid}/role")
def set_user_role(
    uid: int,
    role: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """직원 권한 변경 — 관리자 전용. 본인 변경·마지막 관리자 강등 차단."""
    _admin_only(user)
    if role not in ("admin", "lead", "staff", "viewer"):
        raise HTTPException(400, "권한 값이 올바르지 않습니다")
    target = db.get(models.User, uid)
    if not target:
        raise HTTPException(404, "직원을 찾을 수 없습니다")
    if target.id == user.id:
        raise HTTPException(400, "본인 권한은 바꿀 수 없습니다")
    if target.role == "admin" and role != "admin":
        admins = db.query(models.User).filter(models.User.role == "admin").count()
        if admins <= 1:
            raise HTTPException(400, "마지막 관리자는 강등할 수 없습니다")
    target.role = role
    db.commit()
    return {"ok": True, "role": role}


@router.post("/admin/collect")
def trigger_collect(user: models.User = Depends(get_current_user)):
    """전체 광고주 성과 수동 수집(관리자 전용). 매일 06:00 자동수집과 동일 로직."""
    if user.role != "admin":
        raise HTTPException(403, "관리자만 실행할 수 있습니다")
    from .. import collector

    return collector.collect_all()


@router.get("/clients/{client_id}/metrics/latest")
def latest_metrics(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """채널별 최신 수집 스냅샷 — 대시보드가 먼저 읽는 빠른 저장본."""
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client) and user.role != "viewer":
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    rows = (
        db.query(models.ChannelMetric)
        .filter(models.ChannelMetric.client_id == client_id)
        .order_by(models.ChannelMetric.collected_at.desc())
        .limit(50)
        .all()
    )
    latest = {}
    for r in rows:
        if r.channel not in latest:
            latest[r.channel] = {
                "channel": r.channel,
                # SQLite func.now()는 UTC(naive) → 'Z'를 붙여 브라우저가 KST로 변환하게 함
                "collected_at": (r.collected_at.isoformat() + "Z") if r.collected_at else None,
                "data": json.loads(r.payload_json or "{}"),
            }
    return {"client_id": client_id, "metrics": list(latest.values())}


@router.post("/clients/{client_id}/channels/{channel}/test")
def test_channel(
    client_id: int,
    channel: str,
    days: int = 7,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """저장된 채널 키로 실제 외부 API에 인증·조회해 연결을 검증한다(읽기 전용)."""
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    row = (
        db.query(models.ChannelCredential)
        .filter(
            models.ChannelCredential.client_id == client_id,
            models.ChannelCredential.channel == channel,
        )
        .first()
    )
    if not row:
        raise HTTPException(400, "해당 채널의 키가 아직 없습니다")
    fields = {
        k: security.decrypt(v) for k, v in json.loads(row.fields_json or "{}").items()
    }

    if channel == "naver_commerce":
        from ..adapters import naver_commerce

        app_id = fields.get("app_id")
        app_secret = fields.get("app_secret")
        if not (app_id and app_secret):
            raise HTTPException(400, "애플리케이션 ID/시크릿이 비어 있습니다")
        try:
            data = naver_commerce.fetch_summary(app_id, app_secret)
            return {"ok": True, "channel": channel, "data": data}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "channel": channel, "error": str(e)}

    if channel == "naver_searchad":
        from ..adapters import naver_searchad

        api_key = fields.get("api_license")
        secret_key = fields.get("secret_key")
        customer_id = fields.get("customer_id")
        if not (api_key and secret_key and customer_id):
            raise HTTPException(400, "검색광고 키(라이선스/비밀키/CUSTOMER_ID)가 비어 있습니다")
        try:
            data = naver_searchad.fetch_performance(
                api_key, secret_key, customer_id,
                days=days, date_from=date_from, date_to=date_to,
            )
            return {"ok": True, "channel": channel, "data": data}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "channel": channel, "error": str(e)}

    if channel == "meta_chehum":
        from ..adapters import meta_chehum

        advertiser_id = fields.get("advertiser_id")
        if not advertiser_id:
            raise HTTPException(400, "체험단 광고주 ID가 비어 있습니다")
        try:
            data = meta_chehum.fetch_performance(advertiser_id)
            return {"ok": True, "channel": channel, "data": data}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "channel": channel, "error": str(e)}

    if channel == "youtube":
        from ..adapters import youtube

        video_url = fields.get("video_url")
        if not video_url:
            raise HTTPException(400, "영상 URL이 비어 있습니다")
        try:
            data = youtube.fetch_performance(video_url)
            return {"ok": True, "channel": channel, "data": data}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "channel": channel, "error": str(e)}

    if channel in ("meta_ads", "kakao", "coupang_ads", "naver_gfa"):
        try:
            data = _fetch_ads_channel(channel, fields, days=days, date_from=date_from, date_to=date_to)
            return {"ok": True, "channel": channel, "data": data}
        except KeyError:
            raise HTTPException(400, "이 채널의 필수 입력값이 비어 있습니다")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "channel": channel, "error": str(e)}

    return {"ok": False, "channel": channel, "error": "이 채널 연동은 아직 준비 중입니다"}


# API가 없어 엑셀 업로드/수동입력으로 채우는 채널
MANUAL_CHANNELS = {"daangn", "toss_ads", "mobon"}


def _store_manual_metric(db: Session, client: models.Client, channel: str, data: dict,
                         user=None, action: str = "upload"):
    """업로드/수동 데이터를 ChannelMetric 스냅샷으로 저장하고 채널을 connected로 표시."""
    db.add(models.ChannelMetric(
        client_id=client.id, channel=channel,
        payload_json=json.dumps(data, ensure_ascii=False),
    ))
    label = CHANNEL_LABELS.get(channel, channel)
    verb = "엑셀/CSV 업로드" if action == "upload" else "수동 입력"
    t = (data or {}).get("totals", {})
    log_activity(db, client.id, user, action, f"{label} {verb}",
                 {"impressions": t.get("impressions"), "clicks": t.get("clicks"),
                  "spend": t.get("spend"), "roas": (data or {}).get("roas")})
    cred = (
        db.query(models.ChannelCredential)
        .filter(
            models.ChannelCredential.client_id == client.id,
            models.ChannelCredential.channel == channel,
        )
        .first()
    )
    if not cred:
        db.add(models.ChannelCredential(
            client_id=client.id, channel=channel, mode="upload",
            status="connected", fields_json="{}",
        ))
    else:
        cred.status = "connected"
        cred.mode = "upload"
    # 이력 기록(호출부에서 user 전달)
    db.commit()


@router.post("/clients/{client_id}/channels/{channel}/upload")
def upload_channel(
    client_id: int,
    channel: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    """엑셀/CSV 업로드 → 파싱 → 스냅샷 저장(API 없는 채널용)."""
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    from ..adapters import manual_upload

    raw = file.file.read()
    try:
        data = manual_upload.parse_upload(channel, raw, file.filename)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "channel": channel, "error": str(e)}
    _store_manual_metric(db, client, channel, data, user=user, action="upload")
    return {"ok": True, "channel": channel, "data": data}


@router.post("/clients/{client_id}/channels/{channel}/manual")
def manual_channel(
    client_id: int,
    channel: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    """수동 입력(기간 합계) → 스냅샷 저장(API 없는 채널용)."""
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    from ..adapters import manual_upload

    try:
        data = manual_upload.manual_entry(
            channel, payload.get("totals", payload),
            payload.get("items"), payload.get("period", ""),
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "channel": channel, "error": str(e)}
    _store_manual_metric(db, client, channel, data, user=user, action="manual_entry")
    return {"ok": True, "channel": channel, "data": data}


def _bulk_match_index(db: Session, user, channel: str):
    """일괄 업로드 자동매칭 인덱스 — {광고계정ID: client} + {광고주명: client} (visible 범위).

    계정ID는 해당 채널 자격(ChannelCredential.fields의 account_id, 암호화됨)을 복호화해 만든다.
    """
    clients = visible_clients(db, user).all()
    by_name = {(c.name or "").strip(): c for c in clients if (c.name or "").strip()}
    by_acct, cmap = {}, {c.id: c for c in clients}
    if cmap:
        creds = db.query(models.ChannelCredential).filter(
            models.ChannelCredential.channel == channel,
            models.ChannelCredential.client_id.in_(list(cmap.keys())),
        ).all()
        for cr in creds:
            try:
                raw = json.loads(cr.fields_json or "{}").get("account_id")
                aid = str(security.decrypt(raw) if raw else "").strip()
            except Exception:  # noqa: BLE001
                aid = ""
            if aid and cr.client_id in cmap:
                by_acct[aid] = cmap[cr.client_id]
    return by_acct, by_name


@router.post("/bulk-upload/{channel}")
def bulk_upload(
    channel: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    """여러 리포트 파일 일괄 업로드 → 광고 계정 ID(없으면 계정 이름)로 광고주 자동매칭 후 저장.

    한 파일에 여러 계정이 섞여 있어도 계정별로 분리해 각 광고주에 대입한다.
    매칭 안 된 건은 unmatched로 돌려주어 사용자가 계정ID 등록 후 재시도할 수 있게 한다.
    """
    from ..adapters import manual_upload
    by_acct, by_name = _bulk_match_index(db, user, channel)
    matched, unmatched, errors = [], [], []
    for f in files:
        try:
            raw = f.file.read()
            groups = manual_upload.parse_upload_multi(channel, raw, f.filename)
        except Exception as e:  # noqa: BLE001
            errors.append({"file": f.filename, "error": str(e)[:200]})
            continue
        for g in groups:
            aid = str(g.get("account_id") or "").strip()
            anm = str(g.get("account_name") or "").strip()
            tot = (g.get("data") or {}).get("totals", {})
            client = (by_acct.get(aid) if aid else None) or (by_name.get(anm) if anm else None)
            if not client:
                unmatched.append({"file": f.filename, "account_id": aid or None,
                                  "account_name": anm or None, "reason": "일치하는 광고주 없음", "totals": tot})
                continue
            if not can_edit(user, client):
                unmatched.append({"file": f.filename, "account_id": aid or None,
                                  "account_name": anm or None, "reason": "권한 없음", "client": client.name})
                continue
            _store_manual_metric(db, client, channel, g["data"], user=user, action="upload")
            matched.append({"client_id": client.id, "client": client.name, "account_id": aid or None,
                            "matched_by": "계정ID" if (aid and aid in by_acct) else "이름", "totals": tot})
    return {"ok": True, "channel": channel,
            "summary": {"matched": len(matched), "unmatched": len(unmatched), "errors": len(errors)},
            "matched": matched, "unmatched": unmatched, "errors": errors}


# ===== 활동 이력 · 홈 경고 · 운영 내역서 =====

def _extract_kpi(channel: str, data: dict):
    """채널별 데이터에서 (노출·클릭·광고비·ROAS) 공통 추출. 해당 없으면 None."""
    if not isinstance(data, dict):
        return None
    if channel == "naver_searchad":
        t = data.get("totals", {})
        return {"imp": t.get("impCnt", 0), "clk": t.get("clkCnt", 0),
                "spend": t.get("salesAmt", 0), "roas": data.get("roas")}
    if data.get("source"):  # 정규화 광고채널(메타·카카오·쿠팡·GFA) + 업로드/수동
        t = data.get("totals", {})
        return {"imp": t.get("impressions", 0), "clk": t.get("clicks", 0),
                "spend": t.get("spend", 0), "roas": data.get("roas")}
    return None


def _channel_anomalies(channel: str, data: dict, prev: dict):
    """한 채널 최신(+직전) 스냅샷에서 특이사항 목록 [(severity, reason)]."""
    out = []
    label = CHANNEL_LABELS.get(channel, channel)
    if channel == "meta_chehum":
        s = (data or {}).get("summary", {})
        rate = s.get("avg_review_rate")
        sel = (s.get("funnel_total", {}) or {}).get("selected", 0)
        if rate is not None and sel > 0 and rate < 50:
            out.append(("warn", f"{label}: 리뷰 이행률 {rate}% (저조)"))
        return out
    if channel == "youtube":
        return out
    k = _extract_kpi(channel, data)
    if not k:
        return out
    if (k["imp"] or 0) == 0 and (k["clk"] or 0) == 0:
        out.append(("warn", f"{label}: 노출·클릭 0 (미집행 의심)"))
        return out
    pk = _extract_kpi(channel, prev) if prev else None
    if pk:
        if k.get("roas") is not None and pk.get("roas") and pk["roas"] > 0 and k["roas"] < pk["roas"] * 0.5:
            out.append(("warn", f"{label}: ROAS 급락 ({pk['roas']}%→{k['roas']}%)"))
        if (pk["spend"] or 0) > 0 and (k["spend"] or 0) > (pk["spend"] or 0) * 2:
            out.append(("info", f"{label}: 광고비 급증 ({int(pk['spend']):,}→{int(k['spend']):,}원)"))
    return out


@router.get("/alerts")
def alerts(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """담당자 홈 경고 — 특이사항(미집행·ROAS급락·리뷰저조·삭제요청 대기) 발생 광고주."""
    clients = visible_clients(db, user).filter(
        models.Client.status.in_(["active", "paused", "delete_requested"])
    ).all()
    out = []
    for c in clients:
        if c.status == "delete_requested":
            if user.role == "admin":
                out.append({"client_id": c.id, "name": c.name, "severity": "info",
                            "reason": "삭제 요청 — 대표 승인 대기"})
            continue
        metrics = (
            db.query(models.ChannelMetric)
            .filter(models.ChannelMetric.client_id == c.id)
            .order_by(models.ChannelMetric.id.desc())
            .all()
        )
        latest, prev = {}, {}
        for m in metrics:
            if m.channel not in latest:
                latest[m.channel] = m
            elif m.channel not in prev:
                prev[m.channel] = m
        for ch, m in latest.items():
            try:
                data = json.loads(m.payload_json or "{}")
                pdata = json.loads(prev[ch].payload_json) if ch in prev else None
            except Exception:  # noqa: BLE001
                continue
            for sev, reason in _channel_anomalies(ch, data, pdata):
                out.append({"client_id": c.id, "name": c.name, "severity": sev, "reason": reason})
    # 경고(warn) 먼저
    out.sort(key=lambda x: 0 if x["severity"] == "warn" else 1)
    return {"count": len(out), "alerts": out}


# ══════════════════════════════════════════════════════════════════════════
# 네이버 검색광고 — AI 진단 · AI 세팅(제안 → 담당자 승인 → 실계정 적용)
# ══════════════════════════════════════════════════════════════════════════
ALLOWED_SETUP_TYPES = {"bid", "kw_off", "kw_add", "budget"}


def _searchad_creds(db: Session, client_id: int) -> dict:
    """광고주의 검색광고 자격증명을 복호화해 돌려준다. 없으면 400."""
    cred = (
        db.query(models.ChannelCredential)
        .filter(models.ChannelCredential.client_id == client_id,
                models.ChannelCredential.channel == "naver_searchad",
                models.ChannelCredential.status == "connected")
        .first()
    )
    if not cred:
        raise HTTPException(400, "네이버 검색광고가 연동돼 있어야 합니다. 먼저 키를 연동하세요.")
    f = {k: security.decrypt(v) for k, v in json.loads(cred.fields_json or "{}").items()}
    if not all(f.get(k) for k in ("api_license", "secret_key", "customer_id")):
        raise HTTPException(400, "검색광고 키가 불완전합니다(라이선스·비밀키·Customer ID 확인).")
    return f


def _client_notes(db: Session, client_id: int, limit: int = 3) -> list:
    rows = (db.query(models.ActivityLog)
            .filter(models.ActivityLog.client_id == client_id,
                    models.ActivityLog.type == "note")
            .order_by(models.ActivityLog.id.desc()).limit(limit).all())
    return [r.message for r in rows if r.message]


@router.post("/clients/{client_id}/searchad/diagnose")
def searchad_diagnose(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """AI 진단 — 캠페인·키워드 성과를 읽고 원인을 진단한다(쓰기 없음)."""
    c = db.get(models.Client, client_id)
    if not c or not (user.role in ("admin", "viewer") or can_edit(user, c)):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    f = _searchad_creds(db, client_id)
    from ..adapters import naver_searchad
    from .. import ai_insights
    try:
        perf = naver_searchad.collect_keyword_performance(
            f["api_license"], f["secret_key"], f["customer_id"], days=30)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"검색광고 데이터를 가져오지 못했습니다: {str(e)[:200]}")
    if not perf.get("keyword_count"):
        raise HTTPException(400, "집행 중인 키워드가 없어 진단할 수 없습니다.")
    payload = {
        "client": c.name, "category": c.category,
        "notes": _client_notes(db, client_id),
        "period_days": perf.get("days"),
        "campaigns": perf.get("campaigns"),
        "adgroups": perf.get("adgroups"),
        "keywords": perf.get("keywords", [])[:60],
    }
    try:
        diag = ai_insights.diagnose_searchad(payload)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)[:300])
    return {"diagnosis": diag, "keyword_count": perf.get("keyword_count"),
            "measured": perf.get("measured"), "days": perf.get("days")}


@router.post("/clients/{client_id}/setup-proposals")
def create_setup_proposal(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    """AI 세팅 제안 생성 — 진단 + 변경안을 만들어 draft 로 저장(집행 없음)."""
    c = db.get(models.Client, client_id)
    if not c or not can_edit(user, c):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    f = _searchad_creds(db, client_id)
    from ..adapters import naver_searchad
    from .. import ai_insights
    try:
        perf = naver_searchad.collect_keyword_performance(
            f["api_license"], f["secret_key"], f["customer_id"], days=30)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"검색광고 데이터를 가져오지 못했습니다: {str(e)[:200]}")
    if not perf.get("keyword_count"):
        raise HTTPException(400, "집행 중인 키워드가 없어 제안할 수 없습니다.")
    payload = {
        "client": c.name, "category": c.category,
        "notes": _client_notes(db, client_id),
        "period_days": perf.get("days"),
        "campaigns": perf.get("campaigns"),
        "adgroups": perf.get("adgroups"),
        "keywords": perf.get("keywords", [])[:60],
    }
    try:
        diag = ai_insights.diagnose_searchad(payload)
        prop = ai_insights.propose_searchad_setup(payload)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)[:300])

    # AI 응답 정규화 — 허용 타입·필수값만 남기고 안전값을 미리 계산해 보여준다.
    kw_by_id = {k["keyword_id"]: k for k in perf.get("keywords", [])}
    ag_by_id = {g["adgroup_id"]: g for g in perf.get("adgroups", [])}
    items = []
    for raw in (prop.get("items") or [])[:8]:
        t = (raw.get("type") or "").strip()
        if t not in ALLOWED_SETUP_TYPES:
            continue
        tid = str(raw.get("target_id") or "").strip()
        agid = str(raw.get("adgroup_id") or "").strip()
        it = {
            "type": t, "target_id": tid, "adgroup_id": agid,
            "label": raw.get("label") or "", "why": raw.get("why") or "",
            "current": raw.get("current") or "", "proposed": raw.get("proposed") or "",
            "keyword": (raw.get("keyword") or "").strip(),
            "checked": bool(raw.get("checked")),
            "clamped": False, "clamp_note": "",
        }
        try:
            val = int(raw.get("proposed_value") or 0)
        except (TypeError, ValueError):
            val = 0
        if t == "bid":
            if tid not in kw_by_id:
                continue
            cur = int(kw_by_id[tid].get("bid") or 0)
            safe, clamped, note = naver_searchad.clamp_bid(cur, val)
            it.update({"value": safe, "current_value": cur, "clamped": clamped, "clamp_note": note})
        elif t == "budget":
            if tid not in ag_by_id:
                continue
            cur = int(ag_by_id[tid].get("daily_budget") or 0)
            safe, clamped, note = naver_searchad.clamp_budget(cur, val)
            it.update({"value": safe, "current_value": cur, "clamped": clamped, "clamp_note": note})
        elif t == "kw_off":
            if tid not in kw_by_id:
                continue
            it.update({"value": 0, "current_value": 0})
        elif t == "kw_add":
            if not agid or not it["keyword"]:
                continue
            safe, clamped, note = naver_searchad.clamp_bid(0, val or naver_searchad.MIN_BID)
            it.update({"value": safe, "current_value": 0, "clamped": clamped, "clamp_note": note})
        items.append(it)

    row = models.SetupProposal(
        client_id=client_id, summary=prop.get("summary") or "",
        diagnosis_json=json.dumps(diag, ensure_ascii=False),
        items_json=json.dumps(items, ensure_ascii=False),
        status="draft", created_by=user.id,
    )
    db.add(row)
    log_activity(db, client_id, user, "setup_proposal", f"AI 세팅 제안 생성 — {len(items)}건")
    db.commit()
    db.refresh(row)
    return {"id": row.id, "summary": row.summary, "diagnosis": diag, "items": items,
            "status": row.status, "keyword_count": perf.get("keyword_count")}


@router.get("/clients/{client_id}/setup-proposals")
def list_setup_proposals(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    c = db.get(models.Client, client_id)
    if not c or not (user.role in ("admin", "viewer") or can_edit(user, c)):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    rows = (db.query(models.SetupProposal)
            .filter(models.SetupProposal.client_id == client_id)
            .order_by(models.SetupProposal.id.desc()).limit(10).all())
    return {"items": [{
        "id": r.id, "summary": r.summary, "status": r.status,
        "diagnosis": json.loads(r.diagnosis_json or "{}"),
        "items": json.loads(r.items_json or "[]"),
        "result": json.loads(r.result_json or "{}"),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "applied_at": r.applied_at,
    } for r in rows]}


class SetupApplyIn(schemas.BaseModel):
    item_indexes: list[int] = []
    confirm: bool = False


@router.post("/setup-proposals/{pid}/apply")
def apply_setup_proposal(
    pid: int,
    payload: SetupApplyIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    """선택한 변경만 네이버 실계정에 적용한다.
    ★confirm=True 가 없으면 절대 집행하지 않는다. 항목별로 성공/실패를 기록한다."""
    row = db.get(models.SetupProposal, pid)
    if not row:
        raise HTTPException(404, "제안을 찾을 수 없습니다")
    c = db.get(models.Client, row.client_id)
    if not c or not can_edit(user, c):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    if row.status == "applied":
        raise HTTPException(400, "이미 적용된 제안입니다. 새로 제안을 생성하세요.")
    if not payload.confirm:
        raise HTTPException(400, "확인(confirm)이 필요합니다.")

    items = json.loads(row.items_json or "[]")
    picked = [i for i in (payload.item_indexes or []) if 0 <= i < len(items)]
    if not picked:
        raise HTTPException(400, "적용할 항목을 하나 이상 선택하세요.")

    f = _searchad_creds(db, row.client_id)
    from ..adapters import naver_searchad
    ak, sk, cid = f["api_license"], f["secret_key"], f["customer_id"]

    results, ok_n, fail_n = [], 0, 0
    for i in picked:
        it = items[i]
        t = it.get("type")
        entry = {"index": i, "type": t, "label": it.get("label") or ""}
        try:
            if t == "bid":
                safe, _, _ = naver_searchad.clamp_bid(it.get("current_value") or 0, it.get("value") or 0)
                naver_searchad.set_keyword_bid(ak, sk, cid, it["target_id"], safe)
                entry.update({"ok": True, "applied": f"입찰가 {safe}원"})
            elif t == "kw_off":
                naver_searchad.set_keyword_enabled(ak, sk, cid, it["target_id"], False)
                entry.update({"ok": True, "applied": "키워드 중지"})
            elif t == "budget":
                safe, _, _ = naver_searchad.clamp_budget(it.get("current_value") or 0, it.get("value") or 0)
                naver_searchad.set_adgroup_budget(ak, sk, cid, it["target_id"], safe)
                entry.update({"ok": True, "applied": f"일 예산 {safe}원"})
            elif t == "kw_add":
                safe, _, _ = naver_searchad.clamp_bid(0, it.get("value") or naver_searchad.MIN_BID)
                naver_searchad.add_keywords(ak, sk, cid, it["adgroup_id"],
                                            [{"keyword": it.get("keyword"), "bid": safe}])
                entry.update({"ok": True, "applied": f"키워드 추가(중지 상태) {safe}원"})
            else:
                entry.update({"ok": False, "error": "알 수 없는 변경 유형"})
            if entry.get("ok"):
                ok_n += 1
            else:
                fail_n += 1
        except Exception as e:  # noqa: BLE001
            fail_n += 1
            entry.update({"ok": False, "error": str(e)[:200]})
        results.append(entry)

    result = {"ok": ok_n, "failed": fail_n, "details": results}
    row.result_json = json.dumps(result, ensure_ascii=False)
    if ok_n:
        row.status = "applied"
        row.applied_by = user.id
        row.applied_at = _now_kst_iso()
    done = " · ".join(f"{r['type']}:{'성공' if r.get('ok') else '실패'}" for r in results)
    log_activity(db, row.client_id, user, "setup_applied",
                 f"AI 세팅 적용 — 성공 {ok_n}건 · 실패 {fail_n}건 ({done})")
    db.commit()
    return result


# ── 담당자 메모(특이사항) ──────────────────────────────────────────────
# 별도 테이블을 만들지 않고 ActivityLog(type="note")에 쌓는다.
# 작성자·시각이 기존 필드로 해결되고, 활동 이력·내역서에 자동으로 함께 노출된다.
class NoteIn(schemas.BaseModel):
    body: str


@router.post("/clients/{client_id}/notes")
def add_note(
    client_id: int,
    payload: NoteIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    """광고주 특이사항 메모 한 줄 기록 — 관제 허브·상세에 최신 1건이 표시된다."""
    c = db.get(models.Client, client_id)
    if not c or not can_edit(user, c):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(400, "메모 내용을 입력하세요")
    if len(body) > 500:
        raise HTTPException(400, "메모는 500자 이내로 입력하세요")
    log_activity(db, c.id, user, "note", body)
    db.commit()
    return {"ok": True, "body": body}


@router.get("/clients/{client_id}/activity")
def client_activity(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """광고주 진행 이력(시간순)."""
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    rows = (
        db.query(models.ActivityLog)
        .filter(models.ActivityLog.client_id == client_id)
        .order_by(models.ActivityLog.id.desc())
        .all()
    )
    return [
        {"id": r.id, "type": r.type, "message": r.message, "user": r.user_name,
         "at": (r.created_at.isoformat() + "Z") if r.created_at else None,
         "meta": json.loads(r.meta_json or "{}")}
        for r in rows
    ]


@router.get("/clients/{client_id}/dossier")
def client_dossier(
    client_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """운영 내역서 — 등록부터 현재까지 진행한 모든 기록(이력·데이터 스냅샷·보고서). 환불/정산 대응용."""
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    acts = (
        db.query(models.ActivityLog).filter(models.ActivityLog.client_id == client_id)
        .order_by(models.ActivityLog.id.asc()).all()
    )
    metrics = (
        db.query(models.ChannelMetric).filter(models.ChannelMetric.client_id == client_id)
        .order_by(models.ChannelMetric.collected_at.asc()).all()
    )
    reports = (
        db.query(models.Report).filter(models.Report.client_id == client_id)
        .order_by(models.Report.created_at.asc()).all()
    )
    snapshots = []
    for m in metrics:
        try:
            data = json.loads(m.payload_json or "{}")
        except Exception:  # noqa: BLE001
            data = {}
        k = _extract_kpi(m.channel, data)
        kpi = None
        if k:
            kpi = {"노출": k["imp"], "클릭": k["clk"], "광고비": k["spend"], "ROAS": k.get("roas")}
        elif m.channel == "meta_chehum":
            s = data.get("summary", {})
            kpi = {"캠페인": s.get("campaign_count"), "모집": s.get("recruit_total"),
                   "리뷰": (s.get("funnel_total", {}) or {}).get("reviewed")}
        elif m.channel == "youtube":
            t = data.get("totals", {})
            kpi = {"영상": data.get("video_count"), "조회수": t.get("views")}
        snapshots.append({
            "channel": m.channel, "label": CHANNEL_LABELS.get(m.channel, m.channel),
            "at": (m.collected_at.isoformat() + "Z") if m.collected_at else None,
            "kpi": kpi,
        })
    connected = [
        CHANNEL_LABELS.get(r.channel, r.channel)
        for r in db.query(models.ChannelCredential).filter(
            models.ChannelCredential.client_id == client_id,
            models.ChannelCredential.status == "connected",
        ).all()
    ]
    return {
        "client": {
            "id": client.id, "name": client.name, "category": client.category,
            "status": client.status, "contact": client.contact,
            "contract_start": client.contract_start,
            "created_at": (client.created_at.isoformat() + "Z") if client.created_at else None,
            "memo": client.memo,
        },
        "connected_channels": connected,
        "activities": [
            {"type": r.type, "message": r.message, "user": r.user_name,
             "at": (r.created_at.isoformat() + "Z") if r.created_at else None}
            for r in acts
        ],
        "data_snapshots": snapshots,
        "reports": [
            {"date_from": r.date_from, "date_to": r.date_to,
             "created_at": (r.created_at.isoformat() + "Z") if r.created_at else None,
             "conclusion": (json.loads(r.report_json or "{}") or {}).get("conclusion", "")}
            for r in reports
        ],
        "summary": {
            "activity_count": len(acts), "snapshot_count": len(metrics),
            "report_count": len(reports),
        },
    }


# ===== 광고주 자가 키 입력 링크 =====
# 광고주에게서 직접 받아야 하는(API 키가 필요한) 채널 + 입력 필드·발급 가이드
CONNECT_CHANNEL_META = {
    "naver_searchad": {"name": "네이버 검색광고",
        "fields": [{"k": "customer_id", "label": "Customer ID"}, {"k": "api_license", "label": "API 라이선스"}, {"k": "secret_key", "label": "비밀키", "pw": True}],
        "guide": ["searchad.naver.com 광고주 계정으로 로그인", "우측 상단 도구 › API 사용 관리", "Customer ID = 로그인 후 우측 상단 계정 번호(숫자)", "액세스 라이선스와 비밀키를 발급받아 입력"]},
    "naver_commerce": {"name": "네이버 커머스(스토어)",
        "fields": [{"k": "app_id", "label": "애플리케이션 ID"}, {"k": "app_secret", "label": "시크릿", "pw": True}],
        "guide": ["스마트스토어 판매자센터 로그인", "커머스 API센터 › 애플리케이션 등록", "애플리케이션 ID와 시크릿을 입력"]},
    "naver_gfa": {"name": "네이버 GFA(성과형 디스플레이)",
        "fields": [{"k": "account_id", "label": "GFA 광고계정 ID"}, {"k": "api_key", "label": "API 키", "pw": True}],
        "guide": ["GFA 공식 파트너 등록 후 Beta API 신청", "광고계정 ID와 API 키를 입력"]},
    "kakao": {"name": "카카오모먼트",
        "fields": [{"k": "account_id", "label": "광고계정 ID"}, {"k": "rest_key", "label": "액세스 토큰", "pw": True}],
        "guide": ["business.kakao.com › 카카오모먼트에서 광고계정 ID 확인", "카카오 디벨로퍼스에서 액세스 토큰 발급", "광고계정 ID와 토큰을 입력"]},
    "meta_ads": {"name": "메타 광고(인스타·페북)",
        "fields": [{"k": "account_id", "label": "광고계정 ID(act_...)"}, {"k": "access_token", "label": "액세스 토큰", "pw": True}],
        "guide": ["Meta 비즈니스 관리자에서 광고계정 ID 확인", "시스템 사용자 ads_read 토큰 생성", "광고계정 ID와 액세스 토큰을 입력"]},
    "coupang_ads": {"name": "쿠팡애즈",
        "fields": [{"k": "vendor_id", "label": "업체 ID(Vendor)"}, {"k": "access_key", "label": "액세스 키"}, {"k": "secret_key", "label": "시크릿 키", "pw": True}],
        "guide": ["쿠팡 WING › 광고센터 › Open API", "업체 ID·액세스키·시크릿키 발급 후 입력"]},
}
REQUESTABLE_CHANNELS = list(CONNECT_CHANNEL_META.keys())


def _now_kst_iso():
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


@router.post("/clients/{client_id}/connect-link")
def create_connect_link(
    client_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_editor),
):
    """광고주에게 보낼 '키 입력 요청' 보안 링크 생성."""
    client = db.get(models.Client, client_id)
    if not client or not can_edit(user, client):
        raise HTTPException(404, "광고주를 찾을 수 없습니다")
    channels = [c for c in (payload.get("channels") or REQUESTABLE_CHANNELS) if c in CONNECT_CHANNEL_META]
    if not channels:
        channels = REQUESTABLE_CHANNELS
    days = int(payload.get("days") or 7)
    token = secrets.token_urlsafe(24)
    exp = (datetime.now(timezone(timedelta(hours=9))) + timedelta(days=days)).isoformat()
    db.add(models.ConnectLink(client_id=client_id, token=token,
                              channels_json=json.dumps(channels), created_by=user.id, expires_at=exp))
    log_activity(db, client_id, user, "connect_link", f"API 키 요청 링크 생성 ({len(channels)}개 채널)")
    db.commit()
    base = os.environ.get("DASHBOARD_BASE_URL", "https://dashboard.metainc.co.kr")
    return {"ok": True, "token": token, "url": f"{base}/connect/{token}",
            "channels": channels, "expires_at": exp, "days": days}


@router.get("/connect/{token}/info")
def connect_info(token: str, db: Session = Depends(get_db)):
    """광고주용(공개) — 링크가 요청하는 채널·입력칸·발급 안내. 기존 키는 노출하지 않음."""
    link = db.query(models.ConnectLink).filter(models.ConnectLink.token == token).first()
    if not link:
        raise HTTPException(404, "유효하지 않은 링크입니다")
    client = db.get(models.Client, link.client_id)
    expired = bool(link.expires_at and link.expires_at < _now_kst_iso())
    chans = [c for c in json.loads(link.channels_json or "[]") if c in CONNECT_CHANNEL_META]
    return {
        "agency": "메타아이앤씨",
        "client_name": client.name if client else "",
        "expired": expired,
        "already_submitted": (link.submit_count or 0) > 0,
        "channels": [{"key": c, **CONNECT_CHANNEL_META[c]} for c in chans],
    }


@router.post("/connect/{token}")
def connect_submit(token: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    """광고주용(공개) — 입력한 키를 암호화 저장. payload={channels:{ch:{field:value}}}."""
    link = db.query(models.ConnectLink).filter(models.ConnectLink.token == token).first()
    if not link:
        raise HTTPException(404, "유효하지 않은 링크입니다")
    if link.expires_at and link.expires_at < _now_kst_iso():
        raise HTTPException(400, "만료된 링크입니다. 담당자에게 새 링크를 요청해주세요.")
    allowed = set(json.loads(link.channels_json or "[]"))
    submissions = payload.get("channels") or {}
    saved = []
    for ch, fields in submissions.items():
        if ch not in allowed or ch not in CONNECT_CHANNEL_META or not isinstance(fields, dict):
            continue
        clean = {k: v for k, v in fields.items() if isinstance(v, str) and v.strip()}
        if not clean:
            continue
        row = (
            db.query(models.ChannelCredential)
            .filter(models.ChannelCredential.client_id == link.client_id,
                    models.ChannelCredential.channel == ch)
            .first()
        )
        cur = json.loads(row.fields_json) if row else {}
        for k, v in clean.items():
            cur[k] = security.encrypt(v.strip())
        if row:
            row.fields_json = json.dumps(cur)
            row.status = "connected"
            row.mode = "direct"
        else:
            db.add(models.ChannelCredential(client_id=link.client_id, channel=ch, mode="direct",
                                            status="connected", fields_json=json.dumps(cur)))
        saved.append(ch)
    if not saved:
        raise HTTPException(400, "입력된 키가 없습니다")
    link.used_at = _now_kst_iso()
    link.submit_count = (link.submit_count or 0) + 1
    log_activity(db, link.client_id, None, "credential_submitted",
                 f"광고주가 직접 API 키 입력 ({len(saved)}개 채널)", {"channels": saved})
    db.commit()
    return {"ok": True, "saved": saved}


@router.get("/integrations/meta-chehum/advertisers")
def meta_chehum_advertisers(user: models.User = Depends(get_current_user)):
    """메타체험단 광고주(공급사) 목록 — 광고주 등록 시 체험단 ID 선택용."""
    from ..adapters import meta_chehum

    try:
        return {"ok": True, "advertisers": meta_chehum.list_advertisers()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
