"""S10 시험 — 비서방 알림(``alerts``) · 저장소 판 5(알림 · 받는 사람별) · 심박 (설계 v1.8 S10 · §6 · D6 · M6 · Q4 ·
대표 결정 A1 · A2 · A3 · I1 · I3).

가짜 ① (``test_erp_alert.FakeAlertErp`` — ① 계약 §12·§13 흉내)로만 돈다 — 네트워크 0. 받는 사람 규칙은
``backend/app/naver_auto/scope.py`` 를 그대로 쓴다. 예시 번호·이름은 모두 지어낸 것이다.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone

ENGINE = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ENGINE.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.naver_auto import matching as M  # noqa: E402

from naver_engine import alerts as AL  # noqa: E402
from naver_engine import erp_alert as EA  # noqa: E402
from naver_engine import erp_read as E  # noqa: E402
from naver_engine import links as L  # noqa: E402
from naver_engine import morning as MO  # noqa: E402
from naver_engine import store as S  # noqa: E402
from naver_engine import sync as Y  # noqa: E402
from naver_engine.credentials import Secret  # noqa: E402
from naver_engine.tests.fake_naver import FakeClock  # noqa: E402
from naver_engine.tests.test_erp_alert import MARK_KEY, FakeAlertErp  # noqa: E402
from naver_engine.tests import test_morning as TM  # noqa: E402

KST = timezone(timedelta(hours=9))
TUE = date(2026, 9, 29)            # 화요일
SAT = date(2026, 10, 3)
MON = date(2026, 10, 5)
A, B, C_, D = 1234567, 2345678, 3456789, 4567890
SHOP = "가게"                       # 짝 맞추기 시험의 가게 이름 앞글자 — 비서방 본문에 나오면 안 된다

ON = AL.AlertPolicy(issue_alerts_from=date(2026, 9, 1), issue_alerts_on=True)


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), tzinfo=KST)


def team(idx, name, level=1, parent=0, system=False):
    return {"idx": idx, "name": name, "level": level, "parent_idx": parent, "is_system": system}


def emp(idx, name, team_idx, manager=False, top=False, status="ACTIVE", deleted=False):
    return {"idx": idx, "name": name, "team_idx": team_idx, "is_manager": manager, "is_top_manager": top,
            "status": status, "is_deleted": deleted}


def owner(pid, main, sub=None):
    return {"possibility_id": pid, "manage_emp_idx": main, "sub_manage_emp_idx": sub, "prev_manage_owner_idx": None,
            "sales_emp_idx": None, "owner_source": "manage" if main is not None else "none"}


def org_body(generated: datetime, extra_people=(), owners=None):
    """대표 0 · 관리 1팀 팀장 1 · 직원 100 · 101. 가망 11 → 100 · 12 → 101 · 13 → 담당 없음 · 14 → 100."""
    teams = [team(0, "미분류", 0, 0, True), team(1, "퇴사자", 0, 0, True), team(10, "관리 본부"),
             team(11, "관리 1팀", 2, 10)]
    people = [emp(0, "대표", 0, manager=True, top=True), emp(1, "팀장", 11, manager=True),
              emp(100, "직원가", 11), emp(101, "직원나", 11)] + list(extra_people)
    own = owners if owners is not None else [owner(11, 100), owner(12, 101), owner(13, None), owner(14, 100)]
    return {"generated_at": generated.isoformat(), "teams": teams, "employees": people, "owners": own}


class F:
    def __init__(self, rule, code, target, level, facts=()):
        self.rule, self.code, self.target, self.level, self.facts = rule, code, target, level, facts


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "engine.db")
        self.fc = FakeClock(at(TUE, 6, 0))
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.erp = FakeAlertErp(today=TUE)

    def tearDown(self):
        try:
            if self.st is not None:
                self.st.close()
        finally:
            self.dir.cleanup()

    def now(self, t):
        self.fc._now = t
        self.erp.today = t.astimezone(KST).date()
        return t

    def poster(self, **kw):
        return EA.ErpAlertPoster(Secret(MARK_KEY), transport=self.erp, **kw)

    def org(self, generated=None, **kw):
        g = generated or (self.fc.now() - timedelta(minutes=10))
        self.st.record_org(org_body(g, **kw), self.fc.now())

    def issues(self, day, items):
        """items = [(가망, 고객 번호, 등급)] — 그 날 06:40 점검 회차로 이슈를 연다."""
        keep = self.fc.now()
        self.now(at(day, 6, 40))
        rid = self.st.begin_run(day, self.fc.now())
        for pid, cid, level in items:
            self.st.record_account_check(rid, cid, possibility_id=pid, link="confirmed", status="ok",
                                         rules_run=("bizmoney", "link"), rules_not_run=(),
                                         checked_at=self.fc.now(),
                                         findings=(F("bizmoney", "bizmoney_low", f"acc:{cid}", level),))
        self.st.finish_run(rid, S.RUN_DONE, self.fc.now())
        self.now(max(keep, self.fc.now()))
        return rid

    def recips(self, kind, day=TUE):
        [a] = self.st.alerts_on(day, kind)
        return {r["emp_idx"]: r for r in self.st.alert_recipients(a["alert_id"])}

    def system_alerts(self, day=TUE):
        return self.st.alerts_on(day, S.ALERT_SYSTEM)


# ── 저장소 판 5 ─────────────────────────────────────────────────────
class StoreAlertTest(Base):
    def rec(self, **kw):
        base = dict(kind=S.ALERT_DIGEST, day=TUE, source="compose", template="digest", codes=(),
                    link_path=AL.LINK_ISSUES,
                    recipients=[{"emp_idx": 100, "severity": "NORMAL", "params": {"red": 0, "yellow": 1}}],
                    at=self.fc.now())
        base.update(kw)
        return self.st.record_alert(**base)

    def test_version_and_constants(self):
        self.assertEqual(S.SCHEMA_VERSION, 5)
        self.assertEqual(S.ALERT_SEVERITIES, EA.SEVERITIES)
        self.assertEqual(S.ALERT_TTL, timedelta(hours=12))
        for link in (AL.LINK_HOME, AL.LINK_ISSUES, AL.LINK_SYSTEM, AL.LINK_UNLINKED):
            S._alert_link(link)
            EA.build_payload(0, "NORMAL", "제목", [], link, "abcdefgh")   # 저장소 경로 규칙 ⊆ ① 경로 규칙

    def test_v4_file_gets_alert_tables(self):
        self.st.close()
        self.st = None
        raw = sqlite3.connect(self.path)
        for t in ("naver_auto_alert", "naver_auto_alert_recipient"):
            raw.execute(f"DROP TABLE {t}")
        raw.execute("UPDATE naver_auto_meta SET value = '4' WHERE key = 'schema_version'")
        raw.commit()
        raw.close()
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.assertEqual(self.st.meta("schema_version"), "5")
        self.assertEqual(self.st.alerts_on(TUE), [])
        self.rec()

    def test_record_and_read(self):
        aid = self.rec(recipients=[{"emp_idx": 100, "severity": "URGENT", "params": {"red": 1, "yellow": 2}},
                                   {"emp_idx": 0, "severity": "NORMAL", "params": {"red": 0, "yellow": 1},
                                    "held_reason": "shadow"}])
        [a] = self.st.alerts_on(TUE)
        self.assertEqual((a["kind"], a["day"], a["source"], a["template"], a["codes"], a["link_path"]),
                         ("digest", "2026-09-29", "compose", "digest", [], "/naver/issues"))
        rs = {r["emp_idx"]: r for r in self.st.alert_recipients(aid)}
        self.assertEqual((rs[100]["status"], rs[100]["params"], rs[100]["attempts"]), ("pending", {"red": 1, "yellow": 2}, 0))
        self.assertEqual((rs[0]["status"], rs[0]["held_reason"], rs[0]["next_try_at"]), ("held", "shadow", None))
        self.assertEqual(rs[100]["dedupe_key"], f"dg:20260929:{aid}:100")
        for r in rs.values():
            self.assertTrue(EA._DEDUPE_KEY.fullmatch(r["dedupe_key"]))
        [due] = self.st.due_deliveries(self.fc.now())
        self.assertEqual((due["emp_idx"], due["template"], due["params"]), (100, "digest", {"red": 1, "yellow": 2}))

    def test_daily_kinds_once_system_many(self):
        self.rec()
        with self.assertRaises(S.AlertExists):
            self.rec(recipients=[])
        self.rec(day=TUE + timedelta(days=1), at=self.now(at(TUE + timedelta(days=1), 8)))
        for _ in range(3):
            self.rec(kind=S.ALERT_SYSTEM, source="morning", template="system", codes=["RUN_ABORT"],
                     link_path=AL.LINK_SYSTEM, recipients=[{"emp_idx": 0, "severity": "URGENT", "params": {}}])
        self.assertEqual(len(self.st.alerts_on(TUE, S.ALERT_SYSTEM)), 3)
        self.assertEqual(self.st.system_alert_keys_on(TUE), {"morning:RUN_ABORT"})

    def test_refuses_bad_shapes(self):
        bad = [dict(kind="digest2"), dict(source="naver"), dict(template="Digest"), dict(template="a b"),
               dict(codes=["키"]), dict(codes="RUN_ABORT"), dict(link_path="/naver/?sso=1"), dict(link_path="/naver/x?y=1"),
               dict(link_path="/other/"), dict(link_path="/naver/" + "a" * 60), dict(link_path="/naver//x"),
               dict(link_path="/naver/sso"), dict(day=at(TUE, 8)), dict(at=datetime(2026, 9, 29, 8)),
               dict(at=self.fc.now() + timedelta(hours=1)),
               dict(recipients=[{"emp_idx": -1, "severity": "NORMAL", "params": {}}]),
               dict(recipients=[{"emp_idx": True, "severity": "NORMAL", "params": {}}]),
               dict(recipients=[{"emp_idx": 1, "severity": "urgent", "params": {}}]),
               dict(recipients=[{"emp_idx": 1, "severity": "NORMAL", "params": {}, "held_reason": "why"}]),
               dict(recipients=[{"emp_idx": 1, "severity": "NORMAL", "params": {"name": "표지상회"}}]),
               dict(recipients=[{"emp_idx": 1, "severity": "NORMAL", "params": {"n": -1}}]),
               dict(recipients=[{"emp_idx": 1, "severity": "NORMAL", "params": {"n": True}}]),
               dict(recipients=[{"emp_idx": 1, "severity": "NORMAL", "params": {"n": 1.5}}]),
               dict(recipients=[{"emp_idx": 1, "severity": "NORMAL", "params": {"n": 10 ** 7}}]),
               dict(recipients=[{"emp_idx": 1, "severity": "NORMAL", "params": {"Amount": 1}}]),
               dict(recipients=[{"emp_idx": 1, "severity": "NORMAL",
                                 "params": {f"p{i}": 1 for i in range(13)}}]),
               dict(recipients=[{"emp_idx": 1, "severity": "NORMAL", "params": {}}] * 2),
               dict(recipients=[[1, "NORMAL"]]), dict(recipients={"emp_idx": 1})]
        for kw in bad:
            with self.assertRaises(S.StoreRefused, msg=str(kw)[:80]):
                self.rec(**kw)
        self.assertEqual(self.st.alerts_on(TUE), [])   # 거절은 아무것도 적지 않았다

    def test_delivery_transitions(self):
        aid = self.rec(recipients=[{"emp_idx": 100, "severity": "NORMAL", "params": {}},
                                   {"emp_idx": 101, "severity": "NORMAL", "params": {}},
                                   {"emp_idx": 0, "severity": "NORMAL", "params": {}, "held_reason": "weekend"}])
        rs = {r["emp_idx"]: r["recipient_id"] for r in self.st.alert_recipients(aid)}
        t = self.fc.now()
        for kw in (dict(status="held"), dict(status="bogus"), dict(status="sent"), dict(status="sent", message_idx=0),
                   dict(status="duplicate", message_idx=5), dict(status="failed"),
                   dict(status="pending", error_kind="network"),
                   dict(status="pending", error_kind="network", next_try_at=t),
                   dict(status="pending", error_kind="network", next_try_at=datetime(2026, 9, 29, 9)),
                   dict(status="failed", error_kind="키 거절"), dict(status="sent", message_idx=9, next_try_at=t + timedelta(1))):
            with self.assertRaises(S.StoreRefused, msg=str(kw)):
                self.st.record_delivery(rs[100], at=t, **kw)
        self.st.record_delivery(rs[100], "pending", t, error_kind="network", next_try_at=t + timedelta(minutes=2))
        self.assertEqual(self.st.due_deliveries(t)[0]["emp_idx"], 101)            # 100 은 2분 뒤
        self.st.record_delivery(rs[100], "sent", t, message_idx=77)
        with self.assertRaises(S.DeliveryRefused):
            self.st.record_delivery(rs[100], "failed", t, error_kind="network")   # 끝난 줄은 다시 바뀌지 않는다
        with self.assertRaises(S.DeliveryRefused):
            self.st.record_delivery(rs[0], "sent", t, message_idx=1)             # 남겨 둔 줄은 보내지 않는다
        with self.assertRaises(S.DeliveryRefused):
            self.st.record_delivery(999, "sent", t, message_idx=1)
        r100 = {r["emp_idx"]: r for r in self.st.alert_recipients(aid)}[100]
        self.assertEqual((r100["status"], r100["attempts"], r100["message_idx"], r100["next_try_at"]), ("sent", 2, 77, None))
        self.assertEqual(self.st.delivery_counts_on(TUE), {"digest": {"sent": 1, "pending": 1, "held": 1}})

    def test_reader_refuses_writes(self):
        r = S.open_reader(self.path)
        try:
            with self.assertRaises(S.StoreRefused):
                r.record_alert(S.ALERT_DIGEST, TUE, "compose", "digest", (), AL.LINK_ISSUES, [], self.fc.now())
            with self.assertRaises(S.StoreRefused):
                r.record_heartbeat(TUE, "ok", self.fc.now(), sent=True)
        finally:
            r.close()

    def test_heartbeat_record(self):
        t = self.now(at(TUE, 8, 1))
        self.assertIsNone(self.st.heartbeat())
        for kw in (dict(status="fine", sent=True), dict(status="ok", sent=1), dict(status="ok", sent=True, error_kind="x"),
                   dict(status="ok", sent=False)):
            with self.assertRaises(S.StoreRefused, msg=str(kw)):
                self.st.record_heartbeat(TUE, at=t, **kw)
        self.st.record_heartbeat(TUE, "ok", t, sent=False, error_kind="network")
        hb = self.st.heartbeat()
        self.assertEqual((hb["day"], hb["tries"], hb["sent_at"], hb["error_kind"]), (TUE, 1, None, "network"))
        t2 = self.now(at(TUE, 8, 3))
        self.st.record_heartbeat(TUE, "trouble", t2, sent=True)
        hb = self.st.heartbeat()
        self.assertEqual((hb["tries"], hb["sent_at"], hb["status"], hb["error_kind"]), (2, t2, "trouble", None))
        with self.assertRaises(S.StoreRefused):
            self.st.record_heartbeat(TUE, "ok", t2, sent=True)
        t3 = self.now(at(TUE + timedelta(days=1), 8, 1))
        self.st.record_heartbeat(TUE + timedelta(days=1), "ok", t3, sent=True)
        self.assertEqual(self.st.heartbeat()["tries"], 1)   # 새 날은 새로 센다


# ── 문구 ───────────────────────────────────────────────────────────
class RenderTest(unittest.TestCase):
    BIG = 9_999_999

    def test_every_template_fits_erp_rules(self):
        cases = [("digest", {"red": self.BIG, "yellow": self.BIG}), ("lead_digest", {"count": self.BIG, "people": self.BIG}),
                 ("weekly_unlinked", {"count": self.BIG}),
                 ("shadow_summary", {k: self.BIG for k in ("ok", "partial", "missed", "link", "red", "yellow", "new",
                                                            "auto", "people", "msgs")})]
        for tpl, params in cases:
            title, lines = AL.render(tpl, "compose", (), params)
            EA.build_payload(0, "URGENT", title, lines, AL.LINK_ISSUES, "abcdefgh")
        for src in AL.SOURCE_NAMES:
            title, lines = AL.render("system", src, list(AL.CODE_TEXT)[:3], {})
            EA.build_payload(0, "URGENT", title, lines, AL.LINK_SYSTEM, "abcdefgh")
        for code, text in AL.CODE_TEXT.items():
            EA.build_payload(0, "NORMAL", "제목", [text], AL.LINK_SYSTEM, "abcdefgh")
            self.assertTrue(S.ERROR_CODE.fullmatch(code), code)   # 저장소가 받는 코드 모양

    def test_system_lines_capped_at_eight(self):
        codes = list(AL.CODE_TEXT)[:12]
        title, lines = AL.render("system", "morning", codes, {})
        self.assertEqual(len(lines), 8)
        self.assertEqual(lines[-1], "그 밖 5건")
        self.assertEqual(AL.render("system", "morning", ["abc"], {})[1], ("그 밖의 경보 (abc)",))

    def test_render_refuses(self):
        for tpl, params in (("digest", {"red": 1}), ("digest", {"red": 1, "yellow": -1}),
                            ("digest", {"red": True, "yellow": 1}), ("nope", {}), ("system", {})):
            with self.assertRaises(AL.RenderError, msg=tpl):
                AL.render(tpl, "morning", (), params)

    def test_digest_text(self):
        self.assertEqual(AL.render("digest", "compose", (), {"red": 2, "yellow": 3}),
                         ("오늘 확인할 광고주 5곳", ("🔴 긴급 2곳 · 🟡 주의 3곳", "관제 화면에서 확인해 주세요")))


# ── 시스템 경보 ─────────────────────────────────────────────────────
class SystemAlertTest(Base):
    def test_sync_alert_goes_to_ceo_once_a_day(self):
        self.org()
        res = Y.SyncResult(S.SYNC_STAGES, S.SYNC_BRAKED, (S.BRAKE_TOTAL,), needs_confirmation=True, alert=True, hold_id=3)
        aid = AL.note(self.st, self.now(at(TUE, 6, 10)), res)
        [a] = self.system_alerts()
        self.assertEqual((a["alert_id"], a["source"], a["codes"]), (aid, "stages", ["NEEDS_CONFIRMATION", "BRAKE"]))
        rs = {r["emp_idx"]: r for r in self.st.alert_recipients(aid)}
        self.assertEqual(set(rs), {0})
        self.assertEqual(rs[0]["severity"], "URGENT")
        self.assertIsNone(AL.note(self.st, self.now(at(TUE, 12, 0)), res))           # 같은 날 같은 코드 — 한 번
        res2 = Y.SyncResult(S.SYNC_STAGES, S.SYNC_FAILED, ("network", S.BRAKE_TOTAL), alert=True)
        aid2 = AL.note(self.st, self.fc.now(), res2)
        self.assertEqual(self.st.alerts_on(TUE, S.ALERT_SYSTEM)[-1]["codes"], ["network"])   # 새 코드만
        self.assertEqual(self.st.alert_recipients(aid2)[0]["severity"], "NORMAL")
        res_org = Y.SyncResult(S.SYNC_ORG, S.SYNC_FAILED, ("network",), alert=True)
        self.assertIsNotNone(AL.note(self.st, self.fc.now(), res_org))                  # 나온 곳이 다르면 따로
        self.assertIsNotNone(AL.note(self.st, self.now(at(TUE + timedelta(days=1), 6, 10)), res))   # 다음 날 다시

    def test_no_alert_flag_no_alert(self):
        self.assertIsNone(AL.note(self.st, self.fc.now(), Y.SyncResult(S.SYNC_ORG, S.SYNC_FAILED, ("network",))))
        self.assertIsNone(AL.note(self.st, self.fc.now(), L.PairingOutcome(S.SYNC_REFUSED, ("INPUTS_CHANGED",))))
        self.assertIsNone(AL.note(self.st, self.fc.now(), MO.MorningOutcome(MO.OUT_DONE, (MO.CODE_ACCOUNTS_OLD,))))
        self.assertEqual(self.system_alerts(), [])
        with self.assertRaises(TypeError):
            AL.note(self.st, self.fc.now(), object())

    def test_morning_forwards_alerting_codes_only(self):
        out = MO.MorningOutcome(MO.OUT_DONE, (MO.CODE_ACCOUNTS_OLD, MO.CODE_DATA_LATE, MO.CODE_SYSTEM_GAP), alert=True)
        aid = AL.note(self.st, self.now(at(TUE, 7, 20)), out)
        [a] = self.system_alerts()
        self.assertEqual(a["codes"], [MO.CODE_DATA_LATE, MO.CODE_SYSTEM_GAP])
        self.assertEqual(self.st.alert_recipients(aid)[0]["severity"], "NORMAL")
        stop = MO.MorningOutcome(MO.OUT_FAILED, (MO.CODE_KEY_REJECTED_ALL,), alert=True)
        aid2 = AL.note(self.st, self.fc.now(), stop)
        self.assertEqual(self.st.alert_recipients(aid2)[0]["severity"], "URGENT")

    def test_readiness_waits_for_not_ready_late(self):
        early = MO.Readiness((MO.CODE_PAIRING_NOT_TODAY,))
        self.assertIsNone(AL.note(self.st, self.now(at(TUE, 6, 45)), early))           # 짝 맞추기를 기다리는 잠깐
        late = MO.Readiness((MO.CODE_ACCOUNTS_OLD, MO.CODE_PAIRING_NOT_TODAY, MO.CODE_NOT_READY_LATE))
        aid = AL.note(self.st, self.now(at(TUE, 7, 31)), late)
        [a] = self.system_alerts()
        self.assertEqual(a["codes"], [MO.CODE_PAIRING_NOT_TODAY, MO.CODE_NOT_READY_LATE])
        self.assertEqual(self.st.alert_recipients(aid)[0]["severity"], "URGENT")
        self.assertIsNone(AL.note(self.st, self.now(at(TUE, 7, 45)), late))

    def test_readiness_unusable_is_immediate_and_done_day_ignores_blocking(self):
        self.assertIsNotNone(AL.note(self.st, self.now(at(TUE, 6, 35)), MO.Readiness((MO.CODE_ACCOUNTS_UNUSABLE,))))
        self.issues(TUE, [])                                              # 오늘 끝난 회차
        stale = MO.Readiness((MO.CODE_PAIRING_STALE, MO.CODE_NOT_READY_LATE))
        self.assertIsNone(AL.note(self.st, self.now(at(TUE, 7, 40)), stale))

    def test_recipients_are_active_ceos_or_zero(self):
        self.assertEqual(AL.ceo_recipients(None), {0})
        self.org(extra_people=[emp(7, "공동대표", 0, top=True), emp(8, "옛대표", 0, top=True, status="RESIGNED")])
        aid = AL.record_system_alert(self.st, self.fc.now(), "morning", [MO.CODE_RUN_ABORT])
        self.assertEqual({r["emp_idx"] for r in self.st.alert_recipients(aid)}, {0, 7})

    def test_odd_codes_become_other(self):
        aid = AL.record_system_alert(self.st, self.fc.now(), "org", ["status-4031", "키", "", None, "network"])
        [a] = self.system_alerts()
        self.assertEqual(a["codes"], ["OTHER_CODE", "network"])
        with self.assertRaises(ValueError):
            AL.record_system_alert(self.st, self.fc.now(), "naver", ["network"])
        self.assertTrue(aid)


# ── 아침 요약 · 팀장 묶음 · 그림자 · 주말 · 조직 ─────────────────────────
class ComposeTest(Base):
    def setUp(self):
        super().setUp()
        self.now(at(TUE, 6, 0))
        self.org()
        self.issues(TUE, [(11, A, "red"), (12, B, "yellow"), (13, C_, "yellow")])

    def test_due_times(self):
        self.assertEqual(AL.compose_due(self.st, self.now(at(TUE, 7, 59)), ON), ())
        self.assertEqual(AL.compose_due(self.st, self.now(at(TUE, 8, 0)), ON), (S.ALERT_DIGEST,))
        self.assertEqual(AL.compose_due(self.st, self.fc.now(), AL.SHADOW), (S.ALERT_DIGEST, S.ALERT_SHADOW_SUMMARY))
        self.assertEqual(AL.compose_due(self.st, self.now(at(TUE, 9, 30)), ON), (S.ALERT_DIGEST, S.ALERT_LEAD_DIGEST))
        self.assertEqual(AL.compose_due(self.st, self.now(at(TUE, 18, 0)), ON), ())

    def test_digest_people_and_levels(self):
        out = AL.compose(self.st, self.now(at(TUE, 8, 0)), ON)
        self.assertEqual(out.made, (S.ALERT_DIGEST,))
        rs = self.recips(S.ALERT_DIGEST)
        # 🔴 11 → 담당 100 + 팀장 1 + 대표 0 · 🟡 12 → 담당 101 · 🟡 13(담당 없음) → 대표
        self.assertEqual({p: (r["params"]["red"], r["params"]["yellow"], r["severity"]) for p, r in rs.items()},
                         {100: (1, 0, "URGENT"), 1: (1, 0, "URGENT"), 0: (1, 1, "URGENT"), 101: (0, 1, "NORMAL")})
        self.assertTrue(all(r["status"] == "pending" for r in rs.values()))
        self.assertEqual(AL.compose(self.st, self.fc.now(), ON).made, ())   # 하루 한 번

    def test_closed_excepted_and_info_not_counted(self):
        [i12] = [i for i in self.st.issues() if i["possibility_id"] == 12]
        self.st.except_issue(i12["issue_id"], 1, "lead", TUE + timedelta(days=3), "광고주 요청으로 잠시 보류", self.fc.now())
        [i13] = [i for i in self.st.issues() if i["possibility_id"] == 13]
        self.st.resolve_issue(i13["issue_id"], 0, self.fc.now())
        AL.compose(self.st, self.now(at(TUE, 8, 0)), ON)
        rs = self.recips(S.ALERT_DIGEST)
        self.assertNotIn(101, rs)
        self.assertEqual(rs[0]["params"], {"red": 1, "yellow": 0})

    def test_acked_still_counted(self):
        [i11] = [i for i in self.st.issues() if i["possibility_id"] == 11]
        self.st.ack_issue(i11["issue_id"], 100, self.fc.now())
        AL.compose(self.st, self.now(at(TUE, 8, 0)), ON)
        self.assertEqual(self.recips(S.ALERT_DIGEST)[100]["params"]["red"], 1)

    def test_waits_for_running_check_until_0805(self):
        rid = self.st.begin_run(TUE, self.now(at(TUE, 7, 58)))
        self.assertEqual(AL.compose_due(self.st, self.now(at(TUE, 8, 1)), ON), ())
        self.assertEqual(AL.compose_due(self.st, self.now(at(TUE, 8, 5)), ON), (S.ALERT_DIGEST,))
        self.st.finish_run(rid, S.RUN_DONE, self.fc.now())

    def test_lead_digest(self):
        self.org(owners=[owner(11, 100), owner(12, 101), owner(13, None), owner(15, 100)])
        self.issues(TUE, [(15, D, "yellow")])
        AL.compose(self.st, self.now(at(TUE, 9, 30)), ON)
        rs = self.recips(S.ALERT_LEAD_DIGEST)
        self.assertEqual({p: r["params"] for p, r in rs.items()}, {1: {"count": 2, "people": 2}})   # 12(101) · 15(100)
        self.assertEqual(rs[1]["severity"], "NORMAL")

    def test_shadow_holds_issue_alerts_and_sends_ceo_summary(self):
        out = AL.compose(self.st, self.now(at(TUE, 8, 0)), AL.SHADOW)
        self.assertEqual(out.made, (S.ALERT_DIGEST, S.ALERT_SHADOW_SUMMARY))
        rs = self.recips(S.ALERT_DIGEST)
        self.assertEqual({r["status"] for r in rs.values()}, {"held"})
        self.assertEqual({r["held_reason"] for r in rs.values()}, {"shadow"})
        sm = self.recips(S.ALERT_SHADOW_SUMMARY)
        self.assertEqual(set(sm), {0})
        p = sm[0]["params"]
        self.assertEqual((p["ok"], p["red"], p["yellow"], p["new"], p["people"], p["msgs"]), (3, 1, 2, 3, 4, 4))
        self.assertEqual((sm[0]["status"], sm[0]["severity"]), ("pending", "NORMAL"))
        AL.compose(self.st, self.now(at(TUE, 9, 30)), AL.SHADOW)
        self.assertEqual({r["held_reason"] for r in self.recips(S.ALERT_LEAD_DIGEST).values()}, {"shadow"})

    def test_shadow_needs_date_and_switch(self):
        self.assertTrue(AL.AlertPolicy().in_shadow(TUE))
        self.assertTrue(AL.AlertPolicy(issue_alerts_on=True).in_shadow(TUE))
        self.assertTrue(AL.AlertPolicy(issue_alerts_from=date(2026, 9, 1)).in_shadow(TUE))
        self.assertTrue(AL.AlertPolicy(issue_alerts_from=date(2026, 9, 30), issue_alerts_on=True).in_shadow(TUE))
        self.assertFalse(AL.AlertPolicy(issue_alerts_from=TUE, issue_alerts_on=True).in_shadow(TUE))
        for bad in (dict(issue_alerts_from=at(TUE, 0)), dict(issue_alerts_from="2026-09-29"), dict(issue_alerts_on=1)):
            with self.assertRaises(ValueError):
                AL.AlertPolicy(**bad)

    def test_weekend_only_red(self):
        self.issues(SAT, [(11, A, "red"), (12, B, "yellow"), (13, C_, "yellow")])
        self.org()
        AL.compose(self.st, self.now(at(SAT, 8, 0)), ON)
        rs = self.recips(S.ALERT_DIGEST, SAT)
        self.assertEqual({p: (r["status"], r["held_reason"]) for p, r in rs.items()},
                         {100: ("pending", None), 1: ("pending", None), 0: ("pending", None), 101: ("held", "weekend")})
        AL.compose(self.st, self.now(at(SAT, 9, 30)), ON)
        self.assertEqual({r["held_reason"] for r in self.recips(S.ALERT_LEAD_DIGEST, SAT).values()}, {"weekend"})

    def test_weekend_shadow_summary_only_with_red(self):
        AL.compose(self.st, self.now(at(SAT, 8, 0)), AL.SHADOW)   # 🔴 가 열려 있다(화요일부터)
        self.assertEqual(self.recips(S.ALERT_SHADOW_SUMMARY, SAT)[0]["status"], "pending")
        [i11] = [i for i in self.st.issues() if i["possibility_id"] == 11]
        self.st.resolve_issue(i11["issue_id"], 0, self.fc.now())
        sun = SAT + timedelta(days=1)
        AL.compose(self.st, self.now(at(sun, 8, 0)), AL.SHADOW)
        self.assertEqual(self.recips(S.ALERT_SHADOW_SUMMARY, sun)[0]["held_reason"], "weekend")

    def test_stale_org_holds_and_alerts_ceo(self):
        self.now(at(TUE + timedelta(days=1), 8, 0))   # 화요일 05:50 조직 — 26시간 넘게 낡음
        AL.compose(self.st, self.fc.now(), ON)
        day = TUE + timedelta(days=1)
        self.assertEqual({r["held_reason"] for r in self.recips(S.ALERT_DIGEST, day).values()}, {"org_stale"})
        [a] = self.st.alerts_on(day, S.ALERT_SYSTEM)
        self.assertEqual((a["source"], a["codes"]), ("compose", ["ORG_STALE"]))

    def test_no_org_digest_empty_and_zero_alerted(self):
        with tempfile.TemporaryDirectory() as d:
            st = S.open_writer(os.path.join(d, "e.db"), clock=self.fc.now)
            try:
                out = AL.compose(st, self.now(at(TUE, 8, 0)), ON)
                self.assertEqual(out.made, (S.ALERT_DIGEST,))
                [dg] = st.alerts_on(TUE, S.ALERT_DIGEST)
                self.assertEqual(st.alert_recipients(dg["alert_id"]), [])
                [a] = st.alerts_on(TUE, S.ALERT_SYSTEM)
                self.assertEqual(a["codes"], ["ORG_UNAVAILABLE"])
                self.assertEqual([r["emp_idx"] for r in st.alert_recipients(a["alert_id"])], [0])
            finally:
                st.close()


class WeeklyTest(TM.Base):
    """매주 월요일 「이관 받을 곳」(I3 ⓐ) — 짝 맞추기 막힘 ``not-linked`` 을 담당에게."""

    def test_monday_list_to_owner(self):
        t = TM.T0.replace(year=2026, month=10, day=5)
        self.at(t)
        rows = [TM.srow(p) for p in (11, 14)]
        self.st.record_prospects(E.StageSnapshot({r.possibility_id: r for r in rows}, t - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(TM.kids(TM.A), t - timedelta(minutes=4))
        self.st.record_decision(11, TM.A, "confirmed", 0, t - timedelta(minutes=3))
        erp = TM.FakeErp([E.NaverIdRow(14, M.VENDOR_NAVER, "9876543")])   # 연결 목록에 없는 계정
        res = L.pair_links(erp, self.st, t - timedelta(minutes=2))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)
        self.st.record_org(org_body(t - timedelta(minutes=10)), t)
        self.assertEqual(AL.compose_due(self.st, self.at(at(MON, 8, 0)), ON), (S.ALERT_DIGEST, S.ALERT_WEEKLY_UNLINKED))
        AL.compose(self.st, self.fc.now(), ON)
        [a] = self.st.alerts_on(MON, S.ALERT_WEEKLY_UNLINKED)
        rs = {r["emp_idx"]: r for r in self.st.alert_recipients(a["alert_id"])}
        self.assertEqual({p: r["params"] for p, r in rs.items()}, {100: {"count": 1}})
        self.assertEqual(AL.compose_due(self.st, self.at(at(MON + timedelta(days=1), 8, 0)), ON), (S.ALERT_DIGEST,))


# ── 보내기 ──────────────────────────────────────────────────────────
class DispatchTest(Base):
    def setUp(self):
        super().setUp()
        self.org()
        self.issues(TUE, [(11, A, "red"), (12, B, "yellow")])
        AL.compose(self.st, self.now(at(TUE, 8, 0)), ON)

    def statuses(self):
        return {r["emp_idx"]: r["status"] for r in self.recips(S.ALERT_DIGEST).values()}

    def test_sends_all_urgent_first_and_text_has_no_names(self):
        out = AL.dispatch(self.st, self.fc.now(), self.poster())
        self.assertEqual(out.counts, {"sent": 4})
        self.assertEqual(self.statuses(), {100: "sent", 1: "sent", 0: "sent", 101: "sent"})
        order = [c["body"]["target_emp_idx"] for c in self.erp.calls]
        self.assertEqual(order[-1], 101)                                  # 🟡 만인 사람이 마지막
        for _d, _t, key, sev, content in self.erp.messages:
            self.assertNotIn(SHOP, content)
            self.assertNotIn("직원", content)
            self.assertTrue(content.startswith("[네이버 관제] 오늘 확인할 광고주"))
        self.assertEqual(AL.dispatch(self.st, self.fc.now(), self.poster()).counts, {})   # 다시 불러도 보낼 것이 없다

    def test_retry_backoff_then_fail(self):
        self.erp.override[EA.PATH_ALERTS] = (503, b"busy")
        t = self.fc.now()
        out = AL.dispatch(self.st, t, self.poster())
        self.assertEqual(out.counts, {"retry": 4})
        self.assertEqual(AL.dispatch(self.st, t + timedelta(minutes=1), self.poster()).counts, {})   # 2분 기다림
        gaps = [2, 5, 15, 30]
        for g in gaps:
            t = self.now(t + timedelta(minutes=g))
            AL.dispatch(self.st, t, self.poster())
        self.assertEqual(set(self.statuses().values()), {"failed"})
        rs = self.recips(S.ALERT_DIGEST)
        self.assertEqual({(r["attempts"], r["error_kind"]) for r in rs.values()}, {(5, "status-503")})

    def test_bad_request_fails_at_once(self):
        self.erp.active = {0, 1, 100}                                     # 101 은 퇴사(① 이 400)
        AL.dispatch(self.st, self.fc.now(), self.poster())
        self.assertEqual(self.statuses()[101], "failed")
        self.assertEqual(self.recips(S.ALERT_DIGEST)[101]["error_kind"], "status-400")

    def test_key_rejected_stops_the_pass(self):
        p = EA.ErpAlertPoster(Secret("WRONG-KEY-0123456789abcdef0123456789"), transport=self.erp)
        out = AL.dispatch(self.st, self.fc.now(), p)
        self.assertEqual((out.counts, out.stopped), ({"retry": 1}, "status-401"))
        self.assertEqual(len(self.erp.calls), 1)
        self.assertEqual(sorted(self.statuses().values()), ["pending"] * 4)

    def test_caps_and_duplicate_recorded(self):
        self.erp.cap_target = 0
        out = AL.dispatch(self.st, self.fc.now(), self.poster())
        self.assertEqual(out.counts, {"cap_target": 4})
        self.assertEqual(set(self.statuses().values()), {"cap_target"})

    def test_total_cap_stops(self):
        self.erp.cap_total = 1
        out = AL.dispatch(self.st, self.fc.now(), self.poster())
        self.assertEqual((out.counts, out.stopped), ({"sent": 1, "cap_total": 1}, "cap_total"))

    def test_lost_response_becomes_duplicate(self):
        rows = self.st.due_deliveries(self.fc.now())
        first = rows[0]
        title, lines = AL.render(first["template"], first["source"], first["codes"], first["params"])
        self.poster().send_alert(EA.build_payload(first["emp_idx"], first["severity"], title, lines,
                                                  first["link_path"], first["dedupe_key"]))   # 응답을 잃은 첫 시도
        AL.dispatch(self.st, self.fc.now(), self.poster())
        self.assertEqual(self.statuses()[first["emp_idx"]], "duplicate")
        self.assertEqual(len(self.erp.sent_to(first["emp_idx"])), 1)   # 한 번만 들어갔다

    def test_expired_not_sent(self):
        out = AL.dispatch(self.st, self.now(at(TUE, 20, 1)), self.poster())
        self.assertEqual(out.counts, {"expired": 4})
        self.assertEqual(self.erp.calls, [])

    def test_held_never_sent(self):
        AL.compose(self.st, self.now(at(TUE, 9, 30)), AL.SHADOW)   # 팀장 묶음 — 그림자라 남겨 둠
        AL.dispatch(self.st, self.fc.now(), self.poster())
        self.assertEqual({r["status"] for r in self.recips(S.ALERT_LEAD_DIGEST).values()}, {"held"})

    def test_broken_row_fails_as_render(self):
        aid = self.st.record_alert(S.ALERT_SYSTEM, TUE, "morning", "no_such", ["RUN_ABORT"], AL.LINK_SYSTEM,
                                   [{"emp_idx": 0, "severity": "URGENT", "params": {}}], self.fc.now())
        AL.dispatch(self.st, self.fc.now(), self.poster())
        [r] = self.st.alert_recipients(aid)
        self.assertEqual((r["status"], r["error_kind"]), ("failed", "render"))


# ── 심박(A3) ─────────────────────────────────────────────────────────
class HeartbeatTest(Base):
    def setUp(self):
        super().setUp()
        self.org()

    def test_after_digest_once_a_day(self):
        self.assertFalse(AL.heartbeat_due(self.st, self.now(at(TUE, 7, 59))))
        made, sent, hb = AL.run_alerts(self.st, self.now(at(TUE, 8, 0)), self.poster(), ON)
        self.assertEqual(made.made, (S.ALERT_DIGEST,))
        self.assertEqual(hb, AL.HeartbeatOutcome(True, "ok"))
        self.assertEqual(self.erp.heartbeats, {TUE: "ok"})
        self.assertFalse(AL.heartbeat_due(self.st, self.now(at(TUE, 8, 3))))
        self.assertIsNone(AL.run_alerts(self.st, self.fc.now(), self.poster(), ON)[2])
        wed = TUE + timedelta(days=1)
        self.assertFalse(AL.heartbeat_due(self.st, self.now(at(wed, 7, 0))))
        self.org()                                          # 조직이 낡으면 trouble 이 된다(그 시험은 따로)
        AL.run_alerts(self.st, self.now(at(wed, 8, 0)), self.poster(), ON)
        self.assertEqual(self.erp.heartbeats[wed], "ok")

    def test_trouble_when_system_alert_today(self):
        AL.record_system_alert(self.st, self.now(at(TUE, 7, 10)), "morning", [MO.CODE_DEADLINE_CUT])
        AL.run_alerts(self.st, self.now(at(TUE, 8, 0)), self.poster(), ON)
        self.assertEqual(self.erp.heartbeats, {TUE: "trouble"})
        self.assertEqual(len(self.erp.sent_to(0)), 1)   # 시스템 경보도 같은 차례에 갔다

    def test_failure_retries_after_two_minutes(self):
        self.erp.override[EA.PATH_HEARTBEAT] = (502, b"x")
        _m, _s, hb = AL.run_alerts(self.st, self.now(at(TUE, 8, 0)), self.poster(), ON)
        self.assertEqual(hb, AL.HeartbeatOutcome(False, "ok", "status-502"))
        self.assertFalse(AL.heartbeat_due(self.st, self.now(at(TUE, 8, 1))))
        del self.erp.override[EA.PATH_HEARTBEAT]
        self.assertTrue(AL.heartbeat_due(self.st, self.now(at(TUE, 8, 2))))
        self.assertEqual(AL.send_heartbeat(self.st, self.fc.now(), self.poster()), AL.HeartbeatOutcome(True, "ok"))
        self.assertEqual(self.st.heartbeat()["tries"], 2)

    def test_shadow_day_also_beats(self):
        AL.run_alerts(self.st, self.now(at(TUE, 8, 0)), self.poster(), AL.SHADOW)
        self.assertEqual(self.erp.heartbeats, {TUE: "ok"})
        self.assertEqual({m[1] for m in self.erp.messages}, {0})     # 이슈 0 → 아침 요약 0 통 · 그림자 요약만 대표에게
        self.assertEqual(self.recips(S.ALERT_SHADOW_SUMMARY)[0]["status"], "sent")


if __name__ == "__main__":
    unittest.main()
