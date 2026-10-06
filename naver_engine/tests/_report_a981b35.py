"""시험 전용 대조 사본 — 배포되지 않는다(봉인은 tests 폴더를 싣지 않는다 · discover 의 test*.py 에도 안 잡힌다).

NV-S00(직원 로그인 감사가 쓰기 줄에서 15초를 넘겨 막힘) 수정 전 판(a981b35)의 보고서 생성·최신 판 목록·검토 조회를
**글자 그대로** 옮겨 둔다. 바꾼 곳은 패키지 상대 가져오기 한 줄뿐이다(원문은 ``from . import store as S``).
새 생성(지도·불변 사실 기억·업체별 조각)이 같은 입력에서 같은 판·같은 dirty·같은 대조 상태를 쓰는지 표 해시로 대조할 때
이 사본이 「정답」이다. 이 파일이 쓰는 도우미(``_report_validation`` 등)는 이번 수정이 손대지 않았다 — 시험이 그것도 고정한다.
"""
import json
from datetime import timedelta

from naver_engine import management as P, reporting as R
from naver_engine.store import (_report_period, _report_present, _report_public_validation, _report_read_snapshot,
                                _report_source_fingerprint, _report_validation)

# 이 사본이 기대는 도우미의 a981b35 원문 지문(inspect.getsource SHA-256). 시험이 지금 소스와 대조한다 —
# 도우미가 바뀌면 이 사본은 더는 옛 판의 정답이 아니다(그때는 사본도 새로 옮겨야 한다).
HELPER_SHA256 = {
    "_report_read_snapshot": "9a947bd8e8d6c764bbd56bf02071d9dc3f2cc7155693f5b777552ac35b216588",
    "_report_period": "2dbdf9cdee64568414891ed861867bc159076548052e2ec12f45d5d2900d0174",
    "_report_source_fingerprint": "26b48ca66736da74689094d5613ad75544b106c86bcba09f27a3a2453c558920",
    "_report_validation": "9ca21635ce67bef60c9b47bd85d720eb151b75e69ace733de390de60ecf0721c",
    "_report_public_validation": "27df312e6af07274875e8177b6073155f58bfc5ee9718f7c1eba123697c99601",
    "_report_mark_dirty": "12b81740c465bf0c4b875b9a722226800e0924e4441a6ef231d807c94b2d73b2",
    "_report_present": "30f87316dd404c0606b44fc2d886f6f8a7e970c5130f08685cd610734e237b13",
    "_report_stored_payload": "a7881177dfc4139353479316b482c5aca5ae96b1e8564503879077be9c806f2e",
}


def _report_generate(store, now):
    from naver_engine import store as S   # 원문: from . import store as S (시험 패키지 위치만 다름)
    store._need_writer()
    at = S._kst_text(now, "생성 시각")
    store._not_future(now, "생성 시각")
    decisions = store.synchronize_management(now)
    confirmed = {d.customer_id: d.possibility_id for d in store.current_decisions() if d.decision == "confirmed"}
    groups = {}
    for cid, value in decisions.items():
        pid, cadence = value["possibility_id"], value["decision"].cadence
        stage = "".join((value.get("stage") or "").split())
        # 고유 번호 자동 연결도 수집과 같은 귀속 판정을 사용한다. 사람의 승인 이력을 만들지는 않는다.
        # 비관리 계정의 원장은 보존하지만 새 업무 보고서를 계속 만들지는 않는다.
        if pid is not None and value["decision"].attributable and cadence == "daily" and stage in P.DAILY_STAGES:
            groups.setdefault(pid, []).append(cid)
    boundaries = {(pid, cid): store._performance_attribution_start(cid, pid)
                  for pid, cids in groups.items() for cid in cids}

    def current_accounts(pid, period):
        return {cid for cid in groups[pid] if boundaries[(pid, cid)] is None
                or boundaries[(pid, cid)] <= period.end.isoformat()}

    today = now.astimezone(S.KST).date()
    periods = R.due_periods(now, (today.replace(day=1)-timedelta(days=1)).replace(day=1))
    issues = {row["possibility_id"] for row in store.issues(open_only=True)}
    # 초판 및 최근 보고서의 검토정책 변화만 등록한다. 원천 정정은 수집 거래의 dirty가 담당한다.
    with store._tx() as connection:
        for pid in groups:
            legacy_periods = connection.execute("""SELECT r.period_key FROM naver_auto_report_snapshot r
                WHERE r.possibility_id=? AND COALESCE(json_extract(r.payload_json,'$.format_version'),1)<?
                AND r.report_id=(SELECT MAX(n.report_id) FROM naver_auto_report_snapshot n
                    WHERE n.possibility_id=r.possibility_id AND n.period_key=r.period_key)""", (pid, R.FORMAT_VERSION))
            for legacy in legacy_periods:
                connection.execute("""INSERT INTO naver_auto_report_dirty(possibility_id,period_key,updated_at,pending)
                    VALUES(?,?,?,1) ON CONFLICT(possibility_id,period_key) DO UPDATE SET pending=1,updated_at=excluded.updated_at""",
                    (pid, legacy[0], at))
            for period in periods:
                connection.execute("""INSERT INTO naver_auto_report_dirty
                    (possibility_id,period_key,updated_at,pending) VALUES(?,?,?,1)
                    ON CONFLICT(possibility_id,period_key) DO NOTHING""", (pid, period.key, at))
                latest = connection.execute("""SELECT review_status,payload_json FROM naver_auto_report_snapshot
                    WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1""",
                    (pid, period.key)).fetchone()
                required = "needs_staff_review" if period.kind == "monthly" or pid in issues else "not_required"
                if latest and (latest[0] != required or json.loads(latest[1]).get("format_version", 1) < R.FORMAT_VERSION):
                    # 승인 기록은 별도 표에 있으므로 당시 승인과 현재 요구정책을 혼동하지 않는다.
                    connection.execute("""UPDATE naver_auto_report_dirty SET pending=1,updated_at=?
                        WHERE possibility_id=? AND period_key=? AND pending=0""", (at, pid, period.key))
                expected_row = connection.execute("""SELECT expected_customers_json FROM naver_auto_report_validation
                    WHERE possibility_id=? AND period_key=?""", (pid, period.key)).fetchone()
                if expected_row and current_accounts(pid, period) - set(json.loads(expected_row[0])):
                    # 새 연결의 실적이 아직 없어도 분모에서 빼서 완결로 보이지 않는다.
                    connection.execute("""UPDATE naver_auto_report_dirty SET pending=1,updated_at=?
                        WHERE possibility_id=? AND period_key=?""", (at, pid, period.key))
        # 구형 writer가 남긴 dirty도 그 기간을 비교하는 기존 다음 판으로 전달한다.
        # 한 단계만 확장하며 숫자·원천 지문이 같으면 실제 새 판은 만들지 않는다.
        waiting = S._rows(connection.execute("SELECT possibility_id,period_key,updated_at FROM naver_auto_report_dirty WHERE pending=1"))
        for item in waiting:
            changed = _report_period(item["period_key"])
            following = R.period(changed.kind, changed.end+timedelta(days=1))
            if connection.execute("""SELECT 1 FROM naver_auto_report_snapshot
                WHERE possibility_id=? AND period_key=? LIMIT 1""", (item["possibility_id"], following.key)).fetchone():
                connection.execute("""INSERT INTO naver_auto_report_dirty(possibility_id,period_key,updated_at,pending)
                    VALUES(?,?,?,1) ON CONFLICT(possibility_id,period_key) DO UPDATE SET pending=1,updated_at=excluded.updated_at""",
                    (item["possibility_id"], following.key, item["updated_at"]))
    # 한 업체의 주간·월간을 절단하지 않는다. 대기 업체는 오래된 순서로 계속 배출한다.
    dirty = S._rows(store._conn.execute("""SELECT possibility_id,period_key,updated_at
        FROM naver_auto_report_dirty WHERE pending=1 ORDER BY updated_at,possibility_id,period_key"""))
    batches = {}
    for item in dirty:
        period = _report_period(item["period_key"])
        if period.due_at > now:
            continue
        pid = item["possibility_id"]
        if pid not in groups:
            # 단계가 돌아오면 보충할 수 있게 dirty와 이전 판/실적은 그대로 둔다.
            continue
        if pid not in batches and len(batches) >= 20:
            continue
        batches.setdefault(pid, []).append(period)
    made = 0
    for pid, targets in batches.items():
        with store._tx() as connection:
            prepared, batch_rows = [], {}
            def source_scope(period):
                saved = connection.execute("""SELECT expected_customers_json FROM naver_auto_report_validation
                    WHERE possibility_id=? AND period_key=?""", (pid, period.key)).fetchone()
                historical = [row[0] for row in connection.execute("""SELECT DISTINCT customer_id
                    FROM naver_auto_daily_performance WHERE possibility_id=? AND day BETWEEN ? AND ?""",
                    (pid, period.start.isoformat(), period.end.isoformat()))]
                return sorted(set(json.loads(saved[0]) if saved else ()) | set(historical) | current_accounts(pid, period))

            for period in sorted(targets, key=lambda value: (value.due_at, value.key)):
                state = connection.execute("""SELECT expected_customers_json,payload_json
                    FROM naver_auto_report_validation WHERE possibility_id=? AND period_key=?""",
                    (pid, period.key)).fetchone()
                expected = source_scope(period)
                rows = store.daily_performance(expected, period.start, period.end, possibility_id=pid)
                prior_period = R.previous_period(period)
                prior_expected = source_scope(prior_period)
                prior_rows = store.daily_performance(prior_expected, prior_period.start, prior_period.end, possibility_id=pid)
                batch_rows.update({(row["customer_id"], row["day"]): row for row in rows})
                previous = S._rows(connection.execute("""SELECT * FROM naver_auto_report_snapshot
                    WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1""", (pid, period.key)))
                report = R.snapshot(period, expected, rows, now, has_open_issues=pid in issues,
                                    previous_customers=prior_expected, previous_rows=prior_rows)
                if len(previous) > 0 and json.loads(previous[0]["payload_json"]).get("format_version", 1) < R.FORMAT_VERSION \
                        and not (report["coverage"]["basic_complete_account_days"] or
                                 report["coverage"]["conversion_complete_account_days"]):
                    # 입증할 원천이 없는 옛 판은 미보관 표시로 남긴다. 빈 새 판으로 대체하지 않는다.
                    connection.execute("""UPDATE naver_auto_report_dirty SET pending=0
                        WHERE possibility_id=? AND period_key=?""", (pid, period.key))
                    continue
                prepared.append((period, expected, rows, previous[0] if len(previous) > 0 else None, report, state))
            source = _report_source_fingerprint(list(batch_rows.values()))
            for period, expected, rows, previous, report, state in prepared:
                required_after = {}
                for cid in expected:
                    required = period.due_at.replace(hour=0, minute=1)
                    decision = decisions.get(cid, {}).get("decision")
                    if decision is not None and decision.cadence == "weekly":
                        # 실관리 업체 보고서에 남아 있는 과거 비관리 계정분은 직전 일요일 대조를 재사용한다.
                        required -= timedelta(days=(required.weekday()+1) % 7)
                    required_after[str(cid)] = required.isoformat()
                validation = _report_validation(store, pid, period, expected, rows, now,
                                         source_fingerprint=source, required_after=required_after)
                prior_validation = json.loads(state[1]) if state else {}
                if validation["last_checked_at"] is None:
                    validation["last_checked_at"] = prior_validation.get("last_checked_at")
                if previous is None or previous["revision_fingerprint"] != report["revision_fingerprint"]:
                    old_payload = json.loads(previous["payload_json"]) if previous is not None else None
                    # 기존 판은 수정하지 않는다. 되돌아온 값도 새 판으로 보존한다.
                    revision = connection.execute("""SELECT COUNT(*) FROM naver_auto_report_snapshot
                        WHERE possibility_id=? AND period_key=?""", (pid, period.key)).fetchone()[0]+1
                    report.update(revision_no=revision,
                                  change_summary=R.revision_metadata(old_payload, report, previous["report_id"] if previous is not None else None),
                                  validation=_report_public_validation(validation))
                    prior_snapshot = connection.execute("""SELECT report_id,payload_json FROM naver_auto_report_snapshot
                        WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1""",
                        (pid, R.previous_period(period).key)).fetchone()
                    prior_payload = json.loads(prior_snapshot[1]) if prior_snapshot else None

                    def reference_for(payload, prior):
                        comparison = payload["details"]["comparison"]
                        if prior and prior.get("_data_fingerprint") == comparison["_data_fingerprint"]:
                            comparison["reference"] = {"report_id": prior_snapshot[0],
                                "revision_no": prior.get("revision_no"), "period_key": prior["period_key"]}

                    reference_for(report, prior_payload)
                    for cid, account in report["_account_reports"].items():
                        account_rows = [row for row in rows if row["customer_id"] == int(cid)]
                        account_validation = _report_validation(store, pid, period, [int(cid)], account_rows, now,
                                                               required_after={cid: required_after[cid]})
                        old_account = (old_payload or {}).get("_account_reports", {}).get(cid)
                        account.update(revision_no=revision,
                            change_summary=R.revision_metadata(old_account, account, previous["report_id"] if previous is not None else None),
                            validation=_report_public_validation(account_validation))
                        reference_for(account, (prior_payload or {}).get("_account_reports", {}).get(cid))
                    if old_payload is not None and old_payload.get("format_version", 1) < R.FORMAT_VERSION:
                        report["details"]["status"] = "reconstructed"
                        for account in report["_account_reports"].values():
                            account["details"]["status"] = "reconstructed"
                    connection.execute("""INSERT INTO naver_auto_report_snapshot
                        (possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
                        VALUES(?,?,?,?,?,?,?)""", (pid, period.key, report["revision_fingerprint"], at,
                                                  report["status"], report["review_status"], S._json(report)))
                    made += 1
                validation["_required_after"] = required_after
                connection.execute("""INSERT INTO naver_auto_report_validation
                    (possibility_id,period_key,expected_customers_json,payload_json) VALUES(?,?,?,?)
                    ON CONFLICT(possibility_id,period_key) DO UPDATE SET
                    expected_customers_json=excluded.expected_customers_json,payload_json=excluded.payload_json""",
                    (pid, period.key, S._json(expected), S._json(validation)))
                connection.execute("""UPDATE naver_auto_report_dirty SET pending=0
                    WHERE possibility_id=? AND period_key=?""", (pid, period.key))
    return {"generated": made, "accounts_confirmed": len(confirmed), "advertisers": len(batches)}


def _report_snapshots(store):
    from naver_engine.store import _rows   # 원문: from .store import _rows
    with _report_read_snapshot(store):
        rows = _rows(store._conn.execute("""SELECT r.* FROM naver_auto_report_snapshot r
            WHERE r.report_id=(SELECT MAX(n.report_id) FROM naver_auto_report_snapshot n
                WHERE n.possibility_id=r.possibility_id AND n.period_key=r.period_key)
            ORDER BY generated_at DESC,report_id DESC"""))
        return _report_present(store, rows, current=True)


def review_current(store, report_id):
    """a981b35 record_report_review 의 「지금 판」 찾기 — 최신 판 전체 목록을 만든 뒤 번호로 고른다."""
    return next((r for r in _report_snapshots(store) if r["report_id"] == report_id), None)
