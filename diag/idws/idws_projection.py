"""광고 계정 ID 확인 작업표용 읽기 전용 추출 — 대표님 「이관 현황」 화면과 같은 함수(대표 전체 범위)로 계산한다.

운영: 관제 엔진 컨테이너 안에서 사용자 10001 로 `python -I -B -` 에 이 파일을 넣어 실행한다.
  - 저장소는 엔진의 읽기 전용 열기(open_reader: mode=ro · 읽기만 허용하는 권한 검사)와 한 번의 읽기 거래로만 연다.
  - 쓰기·재시작·외부 호출 없음. 결과 JSON 은 표준 출력(호스트가 곧바로 압축·암호화)으로, 건수만 표준 오류로 낸다.
v2(2026-10-06): 작업표에 필요한 칸만 짧은 배열로 낸다 — 실관리 업체 전부 · 광고 계정 전부 ·
  실관리 업체의 짝 줄 전부 · 그 밖 업체는 지금 있는 광고 계정과 이어진 짝 줄만 · 전산 네이버 번호 칸.
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

# 배열 칸 순서(받는 쪽이 같은 이름표로 읽는다)
COVERAGE_FIELDS = ["pid", "name", "workflow", "owner", "team", "state", "codes", "matched", "candidates"]
ACCOUNT_FIELDS = ["cid", "ad_no", "name", "mapping", "pid", "company", "workflow", "owner", "cadence",
                  "status", "spend", "bizmoney", "checked_at"]
PAIR_FIELDS = ["pid", "cid", "state", "code", "same_name", "claimed_elsewhere", "link"]
COMPANY_FIELDS = ["pid", "name", "stage", "stage_known", "stage_hidden", "owner"]
CRED_FIELDS = ["pid", "ad_no_raw", "has_customer_id"]


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return value


def run(db_path, now=None):
    from naver_engine import store as S, views as W, inventory as INV, catalog_links as CL
    from app.naver_auto import scope as SC, matching as M

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

    cov = inv.get("managed_coverage") or {}
    coverage = []
    for i in cov.get("items", []):
        owner = i.get("owner") or {}
        coverage.append([i.get("possibility_id"), i.get("company_name"), i.get("workflow"), owner.get("name"),
                         owner.get("team_name"), i.get("state"), i.get("codes"),
                         i.get("matched_account_count"), i.get("candidate_count")])
    managed = {row[0] for row in coverage}

    rows_by_cid = {r.get("customer_id"): r for r in inv.get("rows", [])}
    accounts = []
    for cid, a in sorted(ctx.accounts.items()):
        if a.get("present") != 1:
            continue
        r = rows_by_cid.get(cid, {})
        col = r.get("collection") or {}
        accounts.append([cid, None if a.get("ad_account_no") is None else str(a.get("ad_account_no")),
                         a.get("account_name"), r.get("mapping"), r.get("possibility_id"), r.get("company_name"),
                         r.get("workflow"), (r.get("owner") or {}).get("name"),
                         (r.get("management") or {}).get("cadence"), col.get("status"),
                         _num(col.get("spend")), _num(col.get("bizmoney")), _iso(col.get("checked_at"))])
    present = {row[0] for row in accounts}

    creds = []
    if catalog is not None:
        for c in catalog.get("ids", []):
            if c.get("vendor") != M.VENDOR_NAVER:
                continue
            creds.append([c.get("possibility_id"), c.get("ad_account_no_raw"),
                          c.get("customer_id_raw") not in (None, "")])
    cred_pids = {row[0] for row in creds}

    pairs, companies, other = [], [], set()
    links_state = None
    if links is not None:
        links_state = links.source_state
        for pid, rows in sorted(links.ctx.rows_by_pid.items()):
            for r in rows:
                cid = r.get("customer_id")
                if pid in managed or cid in present:
                    pairs.append([pid, cid, r.get("state"), r.get("code"), r.get("same_name"),
                                  bool(r.get("claimed_elsewhere")), r.get("link")])
                    if pid not in managed:
                        other.add(pid)
        lctx = links.ctx
        for pid, row in sorted(links.companies.items()):
            if pid in managed or not (pid in other or pid in cred_pids):
                continue
            own = lctx.owns.get(pid)
            owner = W._owner(lctx, own) if own is not None else None
            companies.append([pid, row.get("company_name"), row.get("stage"), bool(row.get("stage_known")),
                              bool(row.get("stage_hidden")), None if owner is None else owner.get("name")])

    summary = {"generated_at": now.isoformat(), "catalog_state": catalog_state,
               "catalog_at": None if catalog is None else catalog.get("generated_at"),
               "accounts_at": inv.get("accounts_at"), "matching_ready": inv.get("matching_ready"),
               "links_state": links_state, "counts": inv.get("counts"), "workflows": inv.get("workflows"),
               "collection_plan": inv.get("collection_plan"),
               "coverage": {"ready": cov.get("ready"), "total": cov.get("total"),
                            "matched": cov.get("matched"), "missing": cov.get("missing")},
               "sizes": {"coverage": len(coverage), "accounts": len(accounts), "pairs": len(pairs),
                         "companies": len(companies), "creds": len(creds)}}
    return {"v": 2, "summary": summary,
            "fields": {"coverage": COVERAGE_FIELDS, "accounts": ACCOUNT_FIELDS, "pairs": PAIR_FIELDS,
                       "companies": COMPANY_FIELDS, "creds": CRED_FIELDS},
            "coverage": coverage, "accounts": accounts, "pairs": pairs, "companies": companies, "creds": creds}


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
    sys.stdout.write(json.dumps(out, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    _main()
