"""공유 성과: 합성 30일 원천·전송만. DB 시험은 Linux 격리 환경에서 실행한다."""
import copy
import sqlite3
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from naver_engine import metrics as G
from naver_engine import erp_alert as EA
from naver_engine import erp_read as E
from naver_engine import links as L
from naver_engine import morning as M
from naver_engine import naver_read as N
from naver_engine import store as S
from naver_engine.tests.test_morning import Base, FakeErp, A, B, T0, TODAY, steady, srow, kids

NOW = T0.replace(hour=8, minute=20)


def days(value=1):
    return {d.isoformat(): dict.fromkeys(G.FIELDS, value) for d in G.window(TODAY)[2]}


def account(cid=A, campaign_id="cmp-a001", value=1):
    return {"customer_id": cid, "campaigns": [{"campaign_id": campaign_id,
            "cycle_base_tm": NOW.isoformat(), "summary": dict.fromkeys(G.FIELDS, value * 30), "days": days(value)}]}


class Poster:
    def __init__(self, fail=False, no_client=False):
        self.sent, self.fail, self.no_client = [], fail, no_client

    def send_metrics(self, payload):
        self.sent.append(payload.body())
        if self.fail:
            raise EA.AlertSendError("network", EA.PATH_METRICS)
        return SimpleNamespace(recorded=not self.no_client)


class PureMetricsTest(unittest.TestCase):
    def test_thirty_days_does_not_change_morning_window(self):
        self.assertEqual(len(G.window(TODAY)[2]), 30)
        self.assertEqual(G.window(TODAY)[1], TODAY - timedelta(days=1))
        self.assertEqual(len(M.window(TODAY)[2]), 29)

    def test_minimum_calls_includes_both_inventories_and_summary_chunks(self):
        self.assertEqual(G._minimum_calls((77,)), 80)
        self.assertEqual(G._minimum_calls((78,)), 81)
        self.assertEqual(G._minimum_calls((38, 38)), 82)
        self.assertEqual(G._minimum_calls((101,)), 105)

    def test_exact_zero_reconciliation_only(self):
        source = days()
        missing = next(iter(source))
        source.pop(missing)
        self.assertTrue(all(v == 0 for v in G.reconcile(source, dict.fromkeys(G.FIELDS, 29), TODAY)[missing].values()))
        with self.assertRaises(G.MetricsIncomplete):
            G.reconcile(source, dict.fromkeys(G.FIELDS, 30), TODAY)

    def test_wrong_summary_is_not_accepted_even_with_all_days(self):
        with self.assertRaises(G.MetricsIncomplete):
            G.reconcile(days(), dict.fromkeys(G.FIELDS, 31), TODAY)

    def test_fractions_booleans_negative_unknown_and_overflow_refused(self):
        for value in (None, True, -1, 1.5, float("nan"), float("inf"), G.MAX_NUMBER + 1, 10 ** 500, "1"):
            with self.subTest(value=repr(value)), self.assertRaises(G.MetricsIncomplete):
                G.number(value)
        self.assertEqual(G.number(2.0), 2)  # 값이 정확한 정수인 네이버 실수만 허용한다.

    def test_all_accounts_and_all_days_required(self):
        payload = G.aggregate(11, (A, B), [account(), account(B, "cmp-b001")], TODAY, NOW)
        self.assertEqual(payload["impressions"], 60)
        self.assertEqual(set(payload), {"possibility_id", "period_start", "period_end", "impressions", "clicks", "spend", "conversions"})
        for source in ([account()], [account(), account()], []):
            with self.subTest(source=len(source)), self.assertRaises(G.MetricsIncomplete):
                G.aggregate(11, (A, B), source, TODAY, NOW)
        source = account()
        source["campaigns"][0]["days"].pop(next(iter(source["campaigns"][0]["days"])))
        with self.assertRaises(G.MetricsIncomplete):
            G.aggregate(11, (A,), [source], TODAY, NOW)

    def test_empty_campaigns_late_unknown_future_cycle_and_extras_refused(self):
        for mode in ("empty", "late", "unknown", "future", "extra", "duplicate"):
            source = account()
            if mode == "empty":
                source["campaigns"] = []
            elif mode == "late":
                source["campaigns"][0]["cycle_base_tm"] = (NOW - timedelta(days=1)).isoformat()
            elif mode == "unknown":
                source["campaigns"][0]["cycle_base_tm"] = None
            elif mode == "future":
                source["campaigns"][0]["cycle_base_tm"] = (NOW + timedelta(days=1)).isoformat()
            elif mode == "extra":
                source["campaigns"][0]["days"][TODAY.isoformat()] = dict.fromkeys(G.FIELDS, 1)
            else:
                source["campaigns"].append(copy.deepcopy(source["campaigns"][0]))
            with self.subTest(mode=mode), self.assertRaises(G.MetricsIncomplete):
                G.aggregate(11, (A,), [source], TODAY, NOW)

    def test_accumulated_overflow_refused(self):
        with self.assertRaises(G.MetricsIncomplete):
            G.aggregate(11, (A,), [account(value=G.MAX_NUMBER)], TODAY, NOW)

    def test_one_unknown_field_and_duplicate_campaign_across_accounts_refused(self):
        source = account()
        source["campaigns"][0]["days"][next(iter(days()))]["ccnt"] = None
        with self.assertRaises(G.MetricsIncomplete):
            G.aggregate(11, (A,), [source], TODAY, NOW)
        with self.assertRaises(G.MetricsIncomplete):
            G.aggregate(11, (A, B), [account(), account(B)], TODAY, NOW)

    def test_reconciliation_uses_exact_large_integer_sum_not_float_tolerance(self):
        source = days(0)
        first, second = list(source)[:2]
        source[first]["impCnt"] = 1000000000000
        source.pop(second)
        total = dict.fromkeys(G.FIELDS, 0)
        total["impCnt"] = 1000000000001  # 1 차이를 isclose로 같다고 보지 않는다.
        with self.assertRaises(G.MetricsIncomplete):
            G.reconcile(source, total, TODAY)

    def test_snapshot_keeps_missing_day_zero_proof_and_rechecks_it(self):
        source = account()
        campaign = source["campaigns"][0]
        campaign["days"].pop(next(iter(days())))
        campaign["summary"] = dict.fromkeys(G.FIELDS, 29)
        self.assertEqual(G.aggregate(11, (A,), [source], TODAY, NOW)["impressions"], 29)
        campaign["summary"]["impCnt"] = 30
        with self.assertRaises(G.MetricsIncomplete):
            G.aggregate(11, (A,), [source], TODAY, NOW)


class ReadMetricsTest(unittest.TestCase):
    class Reader:
        def __init__(self):
            self.calls = 0
            self.campaigns = [{"nccCampaignId": "cmp-a001", "customerId": A}]
            self.daily = days()
            self.total = dict.fromkeys(G.FIELDS, 30)
            self.cycle = NOW
            self.after = None
            self.periods = []

        def get_campaigns(self, handle):
            self.calls += 1
            return self.after if self.calls > 1 and self.after is not None else self.campaigns

        def get_stats_summary(self, handle, ids, start, end, *, fields):
            self.calls += 1
            self.periods.append((start, end))
            return SimpleNamespace(cycle_base_tm=self.cycle,
                rows={} if self.total is None else {"cmp-a001": self.total})

        def get_stats_daily(self, handle, campaign_id, start, end, *, fields):
            self.calls += 1
            self.periods.append((start, end))
            return SimpleNamespace(cycle_base_tm=self.cycle, days=self.daily)

    def read(self, reader, guard=lambda: None):
        row = dict(customer_id=A, possibility_id=11, state="auto", stage_key="진행중", latest_end_date=None)
        context = dict(stage_as_of=NOW)
        return G._read_account(reader, row, context, TODAY, lambda: NOW, guard)

    def test_explicit_thirty_day_request_and_source_whitelist(self):
        reader = self.Reader()
        reader.campaigns[0]["name"] = "MUST-NOT-BE-RETAINED"
        result = self.read(reader)
        self.assertEqual(reader.calls, 4)
        self.assertEqual(reader.periods, [G.window(TODAY)[:2]] * 2)
        self.assertNotIn("MUST-NOT-BE-RETAINED", repr(result))

    def test_missing_summary_even_for_stopped_campaign_is_not_zero(self):
        reader = self.Reader()
        reader.total = None
        reader.campaigns[0]["status"] = "PAUSED"
        with self.assertRaises(G.MetricsIncomplete):
            self.read(reader)

    def test_campaign_change_during_read_and_stale_cycle_refused(self):
        for mode in ("removed", "added", "wrong_customer", "late"):
            reader = self.Reader()
            if mode == "removed":
                reader.after = []
            elif mode == "added":
                reader.after = reader.campaigns + [{"nccCampaignId": "cmp-b001", "customerId": A}]
            elif mode == "wrong_customer":
                reader.after = [{"nccCampaignId": "cmp-a001", "customerId": B}]
            else:
                reader.cycle -= timedelta(days=1)
            with self.subTest(mode=mode), self.assertRaises(G.MetricsIncomplete):
                self.read(reader)


class MetricsStoreTest(Base):
    def prepare(self, pairs=((11, A),)):
        self.scene(confirmed=pairs, auto=())
        rid = self.st.begin_run(TODAY, T0)
        self.st.finish_run(rid, status=S.RUN_DONE, finished_at=T0 + timedelta(minutes=1))
        self.at(NOW)
        return self.st.metrics_context(NOW)

    def test_snapshot_is_full_and_morning_storage_untouched(self):
        ctx = self.prepare(((11, A), (11, B)))
        self.st.begin_metrics_attempt(11, ctx["fingerprint"], NOW)
        self.st.record_metrics_snapshot(11, ctx["fingerprint"], [account(), account(B, "cmp-b001")], NOW)
        payload = self.st.metrics_payload(11, ctx["fingerprint"], NOW)
        self.assertEqual(payload["impressions"], 60)
        self.assertEqual(self.st.campaign_days(A, G.window(TODAY)[0], TODAY), [])
        self.assertEqual(len(self.st.runs_on(TODAY)), 1)

    def test_partial_snapshot_does_not_create_payload(self):
        ctx = self.prepare(((11, A), (11, B)))
        self.st.begin_metrics_attempt(11, ctx["fingerprint"], NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.record_metrics_snapshot(11, ctx["fingerprint"], [account()], NOW)
        self.assertIsNone(self.st.metrics_payload(11, ctx["fingerprint"], NOW))

    def test_frozen_retry_survives_reopen_and_stored_is_not_resent(self):
        ctx = self.prepare()
        fp = ctx["fingerprint"]
        self.st.begin_metrics_attempt(11, fp, NOW)
        self.st.record_metrics_snapshot(11, fp, [account()], NOW)
        expected = self.st.metrics_payload(11, fp, NOW)
        self.st.finish_metrics_attempt(11, fp, NOW, "retry", error_kind="network")
        self.st.close()
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.assertEqual(self.st.metrics_payload(11, fp, NOW), expected)
        self.assertEqual(self.st.metrics_work(fp, NOW, 2), [])
        later = self.at(NOW + timedelta(minutes=3))
        self.assertEqual(self.st.metrics_work(fp, later, 2), [11])
        self.st.begin_metrics_attempt(11, fp, later)
        self.st.finish_metrics_attempt(11, fp, later, "stored")
        self.assertEqual(self.st.metrics_work(fp, later + timedelta(hours=1), 2), [])

    def test_new_decision_or_stale_accounts_blocks_saved_payload(self):
        ctx = self.prepare()
        fp = ctx["fingerprint"]
        self.st.begin_metrics_attempt(11, fp, NOW)
        self.st.record_metrics_snapshot(11, fp, [account()], NOW)
        self.st.record_decision(11, A, "rejected", 0, NOW)
        self.assertIsNone(self.st.metrics_context(NOW))
        with self.assertRaises(S.StoreRefused):
            self.st.metrics_payload(11, fp, NOW)

    def test_attempt_before_external_read_prevents_starvation(self):
        ctx = self.prepare(((11, A), (12, B)))
        fp = ctx["fingerprint"]
        self.assertEqual(self.st.metrics_work(fp, NOW, 1), [11])
        self.st.begin_metrics_attempt(11, fp, NOW)
        self.st.finish_metrics_attempt(11, fp, NOW, "held", error_kind="incomplete")
        self.assertEqual(self.st.metrics_work(fp, NOW, 1), [12])

    def test_real_read_gate_to_numeric_only_payload_and_no_bizmoney(self):
        self.prepare(((11, A), (11, B)))
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        self.ads.add(B, [(1, "ELIGIBLE", False, steady())])
        poster = Poster()
        result = G.run_metrics(self.reader(max_calls=80), self.st, self.fc.now, poster)
        self.assertEqual(result.counts, {"stored": 1})
        self.assertEqual(len(poster.sent), 1)
        self.assertEqual(poster.sent[0]["impressions"], 60000)
        self.assertEqual(poster.sent[0]["conversions"], 120)
        self.assertEqual(poster.sent[0]["period_start"], G.window(TODAY)[0].isoformat())
        self.assertTrue(all("bizmoney" not in call.path for call in self.naver.calls))
        again = G.run_metrics(self.reader(), self.st, self.fc.now, poster)
        self.assertEqual((again.code, again.counts), ("RETRY_WAIT", {}))
        self.assertEqual(len(poster.sent), 1)

    def test_one_account_missing_blocks_whole_possibility(self):
        self.prepare(((11, A), (11, B)))
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        self.ads.add(B, [])
        poster = Poster()
        result = G.run_metrics(self.reader(), self.st, self.fc.now, poster)
        self.assertEqual(result.counts, {"held": 1})
        self.assertEqual(poster.sent, [])
        again = G.run_metrics(self.reader(), self.st, self.fc.now, poster)
        self.assertEqual((again.code, again.counts), ("RETRY_WAIT", {"held": 1}))

    def test_response_lost_retries_exact_frozen_payload_without_naver_reread(self):
        self.prepare()
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        poster = Poster(fail=True)
        first = G.run_metrics(self.reader(), self.st, self.fc.now, poster)
        self.assertEqual(first.counts, {"retry": 1})
        frozen = poster.sent[0]
        self.st.close()
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.at(self.fc.now() + timedelta(minutes=3))
        reader = self.reader()
        poster.fail = False
        second = G.run_metrics(reader, self.st, self.fc.now, poster)
        self.assertEqual(second.counts, {"stored": 1})
        self.assertEqual(reader.calls, 0)
        self.assertEqual(poster.sent, [frozen, frozen])

    def test_same_semantic_refresh_keeps_frozen_snapshot(self):
        context = self.prepare()
        fp = context["fingerprint"]
        self.st.begin_metrics_attempt(11, fp, NOW)
        self.st.record_metrics_snapshot(11, fp, [account()], NOW)
        self.st.finish_metrics_attempt(11, fp, NOW, "retry", error_kind="network")
        later = self.at(NOW + timedelta(minutes=35))
        self.st.record_prospects(E.StageSnapshot({11: srow(11)}, later, {}, ()))
        self.st.record_accounts(kids(A), later)
        self.assertEqual(L.pair_links(FakeErp(), self.st, later).outcome, S.SYNC_ACCEPTED)
        current = self.st.metrics_context(later)
        self.assertEqual(current["fingerprint"], fp)
        self.assertIsNotNone(self.st.metrics_payload(11, fp, later))

    def test_forged_source_or_changed_payload_is_not_sent(self):
        context = self.prepare()
        fp = context["fingerprint"]
        self.st.begin_metrics_attempt(11, fp, NOW)
        self.st.record_metrics_snapshot(11, fp, [account()], NOW)
        self.st._conn.execute("UPDATE naver_auto_metrics_delivery SET source_json = '[]'")
        with self.assertRaises(S.StoreError):
            self.st.metrics_payload(11, fp, NOW)

    def test_no_client_is_not_stored_and_remains_visible(self):
        self.prepare()
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        result = G.run_metrics(self.reader(), self.st, self.fc.now, Poster(no_client=True))
        self.assertEqual(result.counts, {"no_client": 1})
        again = G.run_metrics(self.reader(), self.st, self.fc.now, Poster())
        self.assertEqual((again.code, again.counts), ("RETRY_WAIT", {"no_client": 1}))

    def test_no_work_before_window_or_without_done_morning(self):
        self.scene(confirmed=((11, A),), auto=())
        reader, poster = self.reader(), Poster()
        self.assertEqual(G.run_metrics(reader, self.st, self.fc.now, poster).code, "OUTSIDE_WINDOW")
        self.at(NOW)
        self.assertEqual(G.run_metrics(reader, self.st, self.fc.now, poster).code, "NOT_READY")
        self.assertEqual((reader.calls, poster.sent), (0, []))

    def test_auto_and_confirmed_accounts_for_same_possibility_are_both_included(self):
        self.scene(confirmed=((11, A),), auto=((11, B),))
        rid = self.st.begin_run(TODAY, T0)
        self.st.finish_run(rid, S.RUN_DONE, T0 + timedelta(minutes=1))
        self.at(NOW)
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        self.ads.add(B, [(1, "ELIGIBLE", False, steady())])
        poster = Poster()
        self.assertEqual(G.run_metrics(self.reader(), self.st, self.fc.now, poster).counts, {"stored": 1})
        self.assertEqual(poster.sent[0]["impressions"], 60000)

    def test_decision_changes_during_read_prevent_send(self):
        self.prepare()
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        def change(call):
            if call.path == "/stats" and "timeIncrement" in call.query:
                self.st.record_decision(11, A, "rejected", 0, self.fc.now())
        self.naver.tick = change
        poster = Poster()
        result = G.run_metrics(self.reader(), self.st, self.fc.now, poster)
        self.assertEqual(result.code, "SOURCE_CHANGED")
        self.assertEqual(poster.sent, [])

    def test_most_recent_refused_sync_blocks_even_with_previous_good_snapshot(self):
        self.prepare()
        self.st.record_sync_event(S.SYNC_ACCOUNTS, S.SYNC_FAILED, ["NETWORK"], NOW)
        self.assertIsNone(self.st.metrics_context(NOW))

    def test_budget_records_attempt_and_moves_to_next_possibility(self):
        context = self.prepare(((11, A), (12, B)))
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        self.naver.tick = lambda call: self.fc.advance(46)
        poster = Poster()
        result = G.run_metrics(self.reader(), self.st, self.fc.now, poster)
        self.assertEqual((result.code, poster.sent), ("BUDGET", []))
        self.assertEqual(self.st.metrics_work(context["fingerprint"], self.fc.now(), 1), [12])

    def test_capacity_stops_before_statistics_and_does_not_starve_next_possibility(self):
        context = self.prepare(((11, A), (12, B)))
        self.ads.add(A, [(n, "ELIGIBLE", False, steady()) for n in range(1, 79)])
        self.ads.add(B, [(1, "ELIGIBLE", False, steady())])
        poster, reader = Poster(), self.reader(max_calls=80)
        result = G.run_metrics(reader, self.st, self.fc.now, poster)
        self.assertEqual(result.counts, {"held": 1, "stored": 1})
        self.assertEqual([p["possibility_id"] for p in poster.sent], [12])
        self.assertEqual(reader.calls, 5)  # 큰 가망은 첫 목록 한 번만 읽는다.
        self.assertFalse(any(int(c.customer) == A and c.path == "/stats" for c in self.naver.calls))
        row = self.st._metrics_delivery(11, TODAY)
        self.assertEqual((row["status"], row["error_kind"], row["attempts"], row["payload_json"]),
                         ("held", "capacity", 1, None))
        self.st.close()
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.at(self.fc.now() + timedelta(minutes=31))
        reader = self.reader(max_calls=80)
        again = G.run_metrics(reader, self.st, self.fc.now, poster)
        self.assertEqual((again.code, again.counts, reader.calls), ("RETRY_WAIT", {"held": 1}, 0))
        with self.assertRaises(S.StoreRefused):
            self.st.begin_metrics_attempt(11, context["fingerprint"], self.fc.now())

    def test_capacity_counts_all_accounts_before_any_statistics(self):
        self.prepare(((11, A), (11, B)))
        for cid in (A, B):
            self.ads.add(cid, [(n, "ELIGIBLE", False, steady()) for n in range(1, 39)])
        poster, reader = Poster(), self.reader(max_calls=80)
        result = G.run_metrics(reader, self.st, self.fc.now, poster)
        self.assertEqual((result.counts, reader.calls, poster.sent), ({"held": 1}, 2, []))
        self.assertEqual(self.ads.stats_calls, [])

    def test_eightieth_completed_request_can_be_saved_and_sent_without_eighty_first(self):
        self.prepare()
        self.ads.add(A, [(n, "ELIGIBLE", False, steady()) for n in range(1, 78)])
        poster, reader = Poster(), self.reader(max_calls=80)
        result = G.run_metrics(reader, self.st, self.fc.now, poster)
        self.assertEqual((result.code, result.counts, reader.calls), ("DONE", {"stored": 1}, 80))
        self.assertEqual(len(self.naver.calls), 80)
        self.assertEqual(poster.sent[0]["impressions"], 77 * 30000)

    def test_feasible_possibility_with_small_remaining_batch_is_not_terminal_capacity(self):
        self.prepare(((11, A), (12, B)))
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        self.ads.add(B, [(n, "ELIGIBLE", False, steady()) for n in range(1, 78)])
        poster, reader = Poster(), self.reader(max_calls=80)
        first = G.run_metrics(reader, self.st, self.fc.now, poster)
        self.assertEqual((first.code, reader.calls), ("BUDGET", 5))
        self.assertEqual([p["possibility_id"] for p in poster.sent], [11])
        self.assertEqual(self.st._metrics_delivery(12, TODAY)["error_kind"], "budget")
        self.at(self.fc.now() + timedelta(minutes=3))
        reader = self.reader(max_calls=80)
        second = G.run_metrics(reader, self.st, self.fc.now, poster)
        self.assertEqual((second.counts, reader.calls), ({"stored": 1}, 80))
        self.assertEqual([p["possibility_id"] for p in poster.sent], [11, 12])

    def test_transport_retry_cap_persists_and_new_context_can_retry(self):
        context = self.prepare(((11, A), (12, B)))
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        self.ads.add(B, [(1, "ELIGIBLE", False, steady())])
        self.ads.fail[(A, "camps")] = (500, {})
        poster = Poster()
        for attempt in range(1, 9):
            result = G.run_metrics(self.reader(max_calls=80), self.st, self.fc.now, poster)
            self.assertEqual(self.st._metrics_delivery(11, TODAY)["attempts"], attempt)
            self.assertEqual(result.counts.get("held" if attempt == 8 else "retry"), 1)
            self.at(self.fc.now() + timedelta(minutes=31))
        self.assertEqual([p["possibility_id"] for p in poster.sent], [12])
        row = self.st._metrics_delivery(11, TODAY)
        self.assertEqual((row["status"], row["error_kind"], row["payload_json"]), ("held", "attempt-cap", None))
        self.st.close()
        self.st = S.open_writer(self.path, clock=self.fc.now)
        reader = self.reader(max_calls=80)
        result = G.run_metrics(reader, self.st, self.fc.now, poster)
        self.assertEqual((result.code, result.counts, reader.calls), ("RETRY_WAIT", {"held": 1}, 0))
        with self.assertRaises(S.StoreRefused):
            self.st.begin_metrics_attempt(11, context["fingerprint"], self.fc.now())
        self.st.record_decision(11, A, "confirmed", 0, self.fc.now())
        self.assertEqual(L.pair_links(FakeErp(), self.st, self.fc.now()).outcome, S.SYNC_ACCEPTED)
        current = self.st.metrics_context(self.fc.now())
        self.assertNotEqual(current["fingerprint"], context["fingerprint"])
        G.run_metrics(self.reader(max_calls=80), self.st, self.fc.now, poster)
        self.assertEqual(self.st._metrics_delivery(11, TODAY)["attempts"], 1)

    def test_budget_retry_cap_has_no_partial_payload_or_unbounded_new_reads(self):
        self.prepare()
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        self.naver.tick = lambda call: self.fc.advance(46)
        poster = Poster()
        for attempt in range(1, 9):
            reader = self.reader(max_calls=80)
            result = G.run_metrics(reader, self.st, self.fc.now, poster)
            self.assertEqual((result.code, reader.calls, poster.sent), ("BUDGET", 1, []))
            self.at(self.fc.now() + timedelta(minutes=31))
        row = self.st._metrics_delivery(11, TODAY)
        self.assertEqual((row["status"], row["error_kind"], row["attempts"], row["payload_json"]),
                         ("held", "attempt-cap", 8, None))
        reader = self.reader(max_calls=80)
        self.assertEqual(G.run_metrics(reader, self.st, self.fc.now, poster).counts, {"held": 1})
        self.assertEqual(reader.calls, 0)

    def test_crash_in_last_allowed_attempt_cannot_start_a_ninth_after_reopen(self):
        context = self.prepare()
        fp = context["fingerprint"]
        for attempt in range(1, 9):
            self.st.begin_metrics_attempt(11, fp, self.fc.now())
            if attempt < 8:
                self.st.finish_metrics_attempt(11, fp, self.fc.now(), "retry", error_kind="transport")
            self.at(self.fc.now() + timedelta(minutes=31))
        self.st.close()  # 8회째 reading 중 종료; 완료 기록조차 못 남긴 경우도 재시도하지 않는다.
        self.st = S.open_writer(self.path, clock=self.fc.now)
        reader, poster = self.reader(max_calls=80), Poster()
        result = G.run_metrics(reader, self.st, self.fc.now, poster)
        self.assertEqual((result.code, result.counts, reader.calls, poster.sent),
                         ("RETRY_WAIT", {"held": 1}, 0, []))
        with self.assertRaises(S.StoreRefused):
            self.st.begin_metrics_attempt(11, fp, self.fc.now())

    def test_capacity_hold_is_reset_by_new_day(self):
        self.prepare()
        self.ads.add(A, [(n, "ELIGIBLE", False, steady()) for n in range(1, 79)])
        poster = Poster()
        self.assertEqual(G.run_metrics(self.reader(max_calls=80), self.st, self.fc.now, poster).counts, {"held": 1})
        tomorrow = T0 + timedelta(days=1)
        self.scene(confirmed=((11, A),), auto=(), t=tomorrow)
        rid = self.st.begin_run(tomorrow.date(), tomorrow)
        self.st.finish_run(rid, S.RUN_DONE, tomorrow + timedelta(minutes=1))
        self.at(NOW + timedelta(days=1))
        self.ads.cycle += timedelta(days=1)
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())])
        result = G.run_metrics(self.reader(max_calls=80), self.st, self.fc.now, poster)
        self.assertEqual(result.counts, {"stored": 1})
        self.assertEqual(self.st._metrics_delivery(11, tomorrow.date())["attempts"], 1)

    def test_next_day_cannot_send_yesterday_payload(self):
        context = self.prepare()
        fp = context["fingerprint"]
        self.st.begin_metrics_attempt(11, fp, NOW)
        self.st.record_metrics_snapshot(11, fp, [account()], NOW)
        tomorrow = self.at(NOW + timedelta(days=1))
        with self.assertRaises(S.StoreRefused):
            self.st.metrics_payload(11, fp, tomorrow)

    def test_migration_keeps_existing_data(self):
        context = self.prepare()
        self.st.close()
        self.st = None
        # 제품 writer의 DROP 금지는 유지한다. 닫힌 임시 시험 파일에 옛 판 fixture를 준비한다.
        with sqlite3.connect(self.path) as raw:
            raw.execute("DROP TABLE naver_auto_metrics_delivery")
            raw.execute("UPDATE naver_auto_meta SET value = '6' WHERE key = 'schema_version'")
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.assertEqual(self.st.meta("schema_version"), str(S.SCHEMA_VERSION))
        self.assertEqual(len(self.st.runs_on(TODAY)), 1)
        self.assertEqual(len(self.st.link_decisions()[0]), 1)
        self.assertEqual(self.st.metrics_work(context["fingerprint"], NOW, 2), [11])


if __name__ == "__main__":
    unittest.main()
