"""정기 수집기 — 연동된 광고주×채널을 돌며 성과를 가져와 DB에 저장.

- 매일 06:00(Asia/Seoul) 자동 실행 (main.py에서 백그라운드 스레드로 구동)
- 수동 실행: POST /api/admin/collect (관리자)
- 광고주 사이에 짧은 대기를 둬 호출 폭주(429)를 방지(추후 큐로 승격).
"""
import json
import time
import threading
from datetime import datetime, timedelta, timezone

from .database import SessionLocal
from . import models, security

KST = timezone(timedelta(hours=9))
COLLECT_HOUR = 6  # 매일 06:00 KST
SLEEP_BETWEEN_CLIENTS = 1.5  # 초


def _collect_searchad(fields: dict) -> dict:
    from .adapters import naver_searchad

    return naver_searchad.fetch_performance(
        fields["api_license"], fields["secret_key"], fields["customer_id"]
    )


def _collect_meta_chehum(fields: dict) -> dict:
    from .adapters import meta_chehum

    return meta_chehum.fetch_performance(fields["advertiser_id"])


def _collect_youtube(fields: dict) -> dict:
    from .adapters import youtube

    return youtube.fetch_performance(fields["video_url"])


def _collect_meta_ads(fields: dict) -> dict:
    from .adapters import meta_ads

    return meta_ads.fetch_performance(fields["account_id"], fields["access_token"])


def _collect_kakao(fields: dict) -> dict:
    from .adapters import kakao

    return kakao.fetch_performance(fields["account_id"], fields["rest_key"])


def _collect_coupang_ads(fields: dict) -> dict:
    from .adapters import coupang_ads

    return coupang_ads.fetch_performance(
        fields["vendor_id"], fields["access_key"], fields["secret_key"]
    )


def _collect_naver_gfa(fields: dict) -> dict:
    from .adapters import naver_gfa

    return naver_gfa.fetch_performance(fields["account_id"], fields["api_key"])


COLLECTORS = {
    "naver_searchad": _collect_searchad,
    "meta_chehum": _collect_meta_chehum,
    "youtube": _collect_youtube,
    "meta_ads": _collect_meta_ads,
    "kakao": _collect_kakao,
    "coupang_ads": _collect_coupang_ads,
    "naver_gfa": _collect_naver_gfa,
}


def collect_all() -> dict:
    """연동된 모든 자격으로 수집 실행. 결과 요약을 반환."""
    db = SessionLocal()
    ok, failed = [], []
    try:
        creds = (
            db.query(models.ChannelCredential)
            .join(models.Client, models.Client.id == models.ChannelCredential.client_id)
            .filter(
                models.ChannelCredential.status == "connected",
                models.ChannelCredential.channel.in_(list(COLLECTORS.keys())),
                models.Client.status != "archived",  # 보관소 광고주는 수집 일시정지
            )
            .all()
        )
        for cred in creds:
            try:
                fields = {
                    k: security.decrypt(v)
                    for k, v in json.loads(cred.fields_json or "{}").items()
                }
                data = COLLECTORS[cred.channel](fields)
                db.add(
                    models.ChannelMetric(
                        client_id=cred.client_id,
                        channel=cred.channel,
                        payload_json=json.dumps(data, ensure_ascii=False),
                    )
                )
                db.commit()
                ok.append({"client_id": cred.client_id, "channel": cred.channel})
            except Exception as e:  # noqa: BLE001 — 한 광고주 실패가 전체를 막지 않게
                db.rollback()
                failed.append(
                    {"client_id": cred.client_id, "channel": cred.channel, "error": str(e)[:200]}
                )
            time.sleep(SLEEP_BETWEEN_CLIENTS)
    finally:
        db.close()
    print(f"[collector] 수집 완료 — 성공 {len(ok)} / 실패 {len(failed)}")
    return {"ok": ok, "failed": failed, "collected_at": datetime.now(KST).isoformat()}


def _seconds_until_next_run() -> float:
    now = datetime.now(KST)
    nxt = now.replace(hour=COLLECT_HOUR, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def _loop():
    while True:
        wait = _seconds_until_next_run()
        print(f"[collector] 다음 자동수집까지 {int(wait)}초 대기 (매일 {COLLECT_HOUR:02d}:00 KST)")
        time.sleep(wait)
        try:
            collect_all()
        except Exception as e:  # noqa: BLE001
            print(f"[collector] 자동수집 오류: {e}")
        try:
            from . import erp_sync
            db = SessionLocal()
            try:
                res = erp_sync.pull_sync(db)  # 전산 계약기간 자동 동기화 (env 미설정 시 no-op)
                print(f"[collector] 전산 계약 동기화 — {res}")
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001
            print(f"[collector] 전산 계약 동기화 오류: {e}")
        try:
            from .routers import insights
            insights.run_due_reports()  # #10 예약 정기 리포트 자동 생성
        except Exception as e:  # noqa: BLE001
            print(f"[collector] 정기 리포트 오류: {e}")


def start_scheduler():
    """워커 여러 개 중 1개만 스케줄러를 갖도록 파일 잠금으로 보장."""
    import fcntl
    import os
    from pathlib import Path

    lock_path = Path(os.environ.get("DB_PATH", "/tmp/app.db")).parent / "collector.lock"
    try:
        fh = open(lock_path, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # 다른 워커가 이미 스케줄러 보유
    # fh를 닫으면 잠금이 풀리므로 전역으로 유지
    globals()["_lock_fh"] = fh
    t = threading.Thread(target=_loop, daemon=True, name="metric-collector")
    t.start()
    print("[collector] 스케줄러 시작 (이 워커가 담당)")
