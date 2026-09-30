"""공유 성과: 합성 30일 원천·전송만. DB 시험은 Linux 격리 환경에서 실행한다."""
import copy
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
            "cycle_base_tm": NOW.isoformat(), "days": days(value)}]}


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
        for value in (None, True, -1, 1.5, float("nan"), float("inf"), G.MAX_NUMBER + 1, "1"):
            with self.subTest(value=repr(value)), self.assertRaises(G.MetricsIncomplete):
                G.number(value)
        self.assertEqual(G.number(2.0), 2)  # 관문은 네이버 숫자를 float로 해석한다.

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


class MetricsStoreTest(Base):
    def prepare(self, pairs=((11, A),)):
        self.scene(confirmed=pairs, auto=())
        rid = self.st.begin_run(T0)
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


if __name__ == "__main__":
    unittest.main()
