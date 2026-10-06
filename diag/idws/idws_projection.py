"""광고 계정 ID 확인 작업표용 읽기 전용 추출 — 대표님 「이관 현황」 화면과 같은 함수(대표 전체 범위)로 계산한다.

운영: 관제 엔진 컨테이너 안에서 사용자 10001 로 `python -I -B -` 에 이 파일을 넣어 실행한다.
  - 저장소는 엔진의 읽기 전용 열기(open_reader: mode=ro · 읽기만 허용하는 권한 검사)와 한 번의 읽기 거래로만 연다.
  - 쓰기·재시작·외부 호출 없음. 결과 JSON 은 표준 출력(호스트가 곧바로 압축·암호화)으로, 건수만 표준 오류로 낸다.
로컬 시험: `run(경로, now)` 를 직접 부른다.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
DB_PATH = "/var/lib/naver-engine/engine.db"
DEADLINE_SECONDS = 90
# 엔진 컨테이너 메모리 한도(512MB)를 엔진과 나눠 쓴다 — 넘으면 엔진이 아니라 이 추출만 MemoryError 로 멈춘다.
# 운영 규모(계정 1,800 · 업체 1,500) 시험에서 최대 약 50MB.
DATA_LIMIT_BYTES = 192 * 1024 * 1024


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return value


def run(db_path, now=None):
    from naver_engine import store as S, views as W, inventory as INV, catalog_links as CL
    from app.naver_auto import scope as SC

    reader = S.open_reader(db_path)
    try:
        deadline = time.monotonic() + DEADLINE_SECONDS
        reader._conn.set_progress_handler(lambda: time.monotonic() >= deadline, 10000)
        with reader.read_snapshot():
            now = now or datetime.now(KST)
            org = W.load_org(reader)
            scope = SC.scope_of(org, 0)
            if scope.kind != SC.ALL:
                raise ValueError("SCOPE_NOT_ALL")
            ctx = W.load(reader, now, org)
            inv = INV.board(ctx, reader, scope, "all", "all", "all", "current", _include_customer_ids=True)
            links = CL.load(reader, now, org, scope, "all")
            catalog, catalog_state = INV.catalog_status(reader, now)
    finally:
        reader.close()

    companies, creds, pairs = [], [], []
    if links is not None:
        lctx = links.ctx
        for pid, row in sorted(links.companies.items()):
            own = lctx.owns.get(pid)
            owner = W._owner(lctx, own) if own is not None else None
            companies.append({
                "pid": pid, "name": row.get("company_name"), "stage": row.get("stage"),
                "stage_known": bool(row.get("stage_known")), "stage_hidden": bool(row.get("stage_hidden")),
                "owner": None if owner is None else {"idx": owner.get("idx"), "name": owner.get("name"),
                                                     "team": owner.get("team_name"), "state": owner.get("state")}})
        for pid, rows in sorted(lctx.rows_by_pid.items()):
            for r in rows:
                pairs.append({"pid": pid, "cid": r.get("customer_id"), "state": r.get("state"), "code": r.get("code"),
                              "link": r.get("link"), "same_name": r.get("same_name"),
                              "claimed_elsewhere": r.get("claimed_elsewhere")})
    if catalog is not None:
        for c in catalog.get("ids", []):
            creds.append({"pid": c.get("possibility_id"), "vendor": c.get("vendor"),
                          "has_customer_id": c.get("customer_id_raw") not in (None, ""),
                          "ad_no": c.get("ad_account_no_raw")})

    rows_by_cid = {r.get("customer_id"): r for r in inv.get("rows", [])}
    accounts = []
    for cid, a in sorted(ctx.accounts.items()):
        if a.get("present") != 1:
            continue
        r = rows_by_cid.get(cid, {})
        col = r.get("collection") or {}
        mgmt = r.get("management") or {}
        owner = r.get("owner") or {}
        accounts.append({
            "cid": cid, "ad_no": None if a.get("ad_account_no") is None else str(a.get("ad_account_no")),
            "name": a.get("account_name"), "mapping": r.get("mapping"), "pid": r.get("possibility_id"),
            "company": r.get("company_name"), "workflow": r.get("workflow"), "erp_stage": r.get("erp_stage"),
            "owner": owner.get("name") if owner else None, "reason": r.get("reason"),
            "cadence": mgmt.get("cadence"),
            "check": {"status": col.get("status"), "spend": _num(col.get("spend")), "clk": _num(col.get("clk")),
                      "period_start": col.get("period_start"), "period_end": col.get("period_end"),
                      "bizmoney": _num(col.get("bizmoney")), "bizmoney_at": _iso(col.get("bizmoney_at")),
                      "checked_at": _iso(col.get("checked_at"))}})

    cov = inv.get("managed_coverage") or {}
    coverage = [{"pid": i.get("possibility_id"), "name": i.get("company_name"), "workflow": i.get("workflow"),
                 "owner": (i.get("owner") or {}).get("name"), "state": i.get("state"), "codes": i.get("codes"),
                 "matched": i.get("matched_account_count"), "candidates": i.get("candidate_count")}
                for i in cov.get("items", [])]

    summary = {"generated_at": now.isoformat(), "catalog_state": catalog_state,
               "catalog_at": None if catalog is None else catalog.get("generated_at"),
               "accounts_at": inv.get("accounts_at"), "matching_ready": inv.get("matching_ready"),
               "links_state": None if links is None else links.source_state,
               "counts": inv.get("counts"), "workflows": inv.get("workflows"),
               "collection_plan": inv.get("collection_plan"),
               "coverage": {"ready": cov.get("ready"), "total": cov.get("total"),
                            "matched": cov.get("matched"), "missing": cov.get("missing")},
               "sizes": {"companies": len(companies), "creds": len(creds), "pairs": len(pairs),
                         "accounts": len(accounts), "coverage": len(coverage)}}
    return {"v": 1, "summary": summary, "companies": companies, "creds": creds, "pairs": pairs,
            "accounts": accounts, "coverage": coverage}


def _main():
    if os.geteuid() != 10001:
        raise SystemExit("READER_IDENTITY")
    import resource
    resource.setrlimit(resource.RLIMIT_DATA, (DATA_LIMIT_BYTES, DATA_LIMIT_BYTES))
    os.environ.clear()
    sys.path[:0] = ["/opt/naver-engine", "/opt/naver-engine/backend"]
    out = run(DB_PATH)
    # 표준 오류에는 건수·상태만(이름·번호 없음) — 공개 기록에 남아도 되는 것만.
    sys.stderr.write("IDWS_SUMMARY=" + json.dumps(out["summary"], ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    _main()
