"""네이버 자동운영 1차 — 보는 범위 판정(scope.py) · 조직 스냅숏 검사(org_snapshot.py) 시험.

설계 v1.4 §12 의 2·3·4·7·8 번을 순수 함수 단위로 고정한다(v1.5 착수 순서).
돌리는 법(backend 폴더에서):  python3 -m unittest -v tests.test_naver_auto_scope

예시 조직은 시안 v5 와 같다(이름·숫자 모두 예시):
  관리 본부(한본부장 2곳) › 관리 1팀(이팀장 3 · 김담당 8 · 박담당 5 — 그중 1곳은 김담당이 서브)
                         › 관리 2팀(최팀장 4 · 정담당 6 · 퇴사한 오담당 1 = 담당 공백)
  담당 미정 2곳(빈칸 · 모르는 번호) · 박관리(관리자 · 0곳) · 대표 · 합계 31곳
  시스템 팀: 미분류(0) · 「퇴사자」(900) — 둘 다 팀장이 앉아 있어도 범위의 뿌리가 될 수 없다.
"""
from __future__ import annotations

import ast
import copy
import itertools
import json
import pathlib
import random
import re
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.naver_auto import org_snapshot as snap  # noqa: E402
from app.naver_auto import scope as sc  # noqa: E402

# ── 예시 조직 ───────────────────────────────────────────────────────
T_UNSORTED, T_RESIGNED, T_HQ, T_1, T_2, T_CEO = 0, 900, 10, 11, 12, 30

# 대표 = 0번 — 운영 전산 실측(2026-09-28): 대표 계정은 employee.idx 0 · 대표 표시 · 팀장 표시 · 팀 0(미분류) · ACTIVE.
# 예시 조직도 그 모양 그대로 둔다(0 을 「없음」으로 읽는 실수가 모든 시험에서 드러나게).
CEO, HAN, PARK, LEE, KIM, BAK, CHOI, JEONG, OH = 0, 101, 102, 111, 112, 113, 121, 122, 123
SUSPENDED, DELETED = 124, 125          # 정지 · 삭제(상태는 ACTIVE) — 둘 다 재직 아님
SYS_MGR_RESIGNED_TEAM, SYS_MGR_UNSORTED = 901, 902  # 시스템 팀에 앉은 팀장(재직)
YOON = 555                             # 조직 표에 없는 사람(영업)
UNKNOWN_OWNER = 777                    # 담당 칸에 있지만 직원 표에 없는 번호
PID_BASE = 5000

# (광고주 번호, 시안 이름, 메인, 서브)
MOCKUP_CLIENTS = [
    (1, "dara", KIM, None), (2, "zacha", KIM, None), (3, "maba", KIM, None), (4, "saa", KIM, None),
    (5, "aja", KIM, None), (6, "gana", KIM, None), (7, "kata", KIM, None), (8, "bada", KIM, None),
    (9, "chaka", LEE, None), (10, "haga", LEE, None), (11, "nada", LEE, None),
    (12, "tapa", BAK, KIM), (13, "rama", BAK, None), (14, "basa", BAK, None), (15, "aka", BAK, None),
    (16, "jaha", BAK, None),
    (17, "gaha", HAN, None), (18, "nama", HAN, None),
    (19, "dasa", CHOI, None), (20, "raja", CHOI, None), (21, "maka", CHOI, None), (22, "bata", CHOI, None),
    (23, "paha", JEONG, None), (24, "saja", JEONG, None), (25, "acha", JEONG, None), (26, "jata", JEONG, None),
    (27, "chapa", JEONG, None), (28, "kaha", JEONG, None),
    (29, "taga", OH, None),                 # 담당 공백(퇴사)
    (30, "hana", None, None),               # 담당 미정 — 빈칸
    (31, "gada", UNKNOWN_OWNER, None),      # 담당 미정 — 모르는 번호
]
CID = {name: cid for cid, name, _, _ in MOCKUP_CLIENTS}
PREV_CLIENT, CEO_CLIENT = 32, 33  # 확장 예시: 계약 만료(① 모양: 관리 담당 null · 출처 prev · 직전 김담당) · 대표 본인 담당

KST = timezone(timedelta(hours=9))
_T0 = datetime(2026, 9, 28, 9, 0, tzinfo=KST)
_tick = itertools.count()


def _next_time():
    """부를 때마다 1분씩 늦은 스냅숏 시각 — 나중에 만든 응답이 늘 더 새것이다(STALE 검사)."""
    return (_T0 + timedelta(minutes=next(_tick))).isoformat()


def _team(idx, name, level, parent, system=False):
    return {"idx": idx, "name": name, "level": level, "parent_idx": parent, "is_system": system}


def _emp(idx, name, team, manager=False, top=False, status="ACTIVE", deleted=False):
    return {"idx": idx, "name": name, "team_idx": team, "is_manager": manager,
            "is_top_manager": top, "status": status, "is_deleted": deleted}


def _pn(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _owner(cid, main, sub=None, prev=None):
    """① ``AdSyncOrgSnapshotService.toOwner`` 과 같은 모양 — 사람 번호 음수는 null(-1 을 보내지 않음 · 0 은 대표) · 출처는 소문자."""
    if main is not None and main >= 0:
        src = "manage"
    elif main == -1 and _pn(prev) is not None:
        src = "prev"
    else:
        src = "none"
    return {"possibility_id": PID_BASE + cid, "manage_emp_idx": _pn(main), "sub_manage_emp_idx": _pn(sub),
            "prev_manage_owner_idx": _pn(prev), "sales_emp_idx": None, "owner_source": src}


def mockup_payload(extended=False, at=None):
    teams = [
        _team(T_UNSORTED, "미분류", 0, 0, True),
        _team(T_RESIGNED, "퇴사자", 0, 0, True),
        _team(T_HQ, "관리 본부", 1, 0),
        _team(T_1, "관리 1팀", 2, T_HQ),
        _team(T_2, "관리 2팀", 2, T_HQ),
        _team(T_CEO, "대표실", 1, 0),
    ]
    employees = [
        _emp(CEO, "대표", T_UNSORTED, manager=True, top=True),   # 운영과 같은 모양(0번 · 팀 0 · 팀장 표시)
        _emp(HAN, "한본부장", T_HQ, manager=True),
        _emp(PARK, "박관리", T_HQ),
        _emp(LEE, "이팀장", T_1, manager=True),
        _emp(KIM, "김담당", T_1),
        _emp(BAK, "박담당", T_1),
        _emp(CHOI, "최팀장", T_2, manager=True),
        _emp(JEONG, "정담당", T_2),
        _emp(OH, "오담당", T_2, status="RESIGNED"),
        _emp(SUSPENDED, "정지된 직원", T_2, status="SUSPENDED"),
        _emp(DELETED, "삭제된 직원", T_2, deleted=True),
        _emp(SYS_MGR_RESIGNED_TEAM, "퇴사자팀 팀장", T_RESIGNED, manager=True),
        _emp(SYS_MGR_UNSORTED, "미분류 팀장", T_UNSORTED, manager=True),
    ]
    owners = [_owner(cid, main, sub) for cid, _, main, sub in MOCKUP_CLIENTS]
    if extended:
        owners.append(_owner(PREV_CLIENT, -1, None, KIM))
        owners.append(_owner(CEO_CLIENT, CEO))
    return {"generated_at": at or _next_time(), "teams": teams,
            "employees": employees, "owners": owners}


def rows_of(org):
    return {row.possibility_id - PID_BASE: sc.ownership_for_client(org, row.possibility_id - PID_BASE,
                                                                   row.possibility_id, sc.MATCH_PID)
            for row in org.owners}


def build(extended=False, payload=None, prev=None):
    decision = snap.accept_snapshot(payload if payload is not None else mockup_payload(extended), prev)
    assert decision.ok, decision.reasons
    org = decision.org
    return org, rows_of(org)


def ids(names):
    return frozenset(CID[n] for n in names)


def visible(org, rows, who, selection="all"):
    return sc.clients_in(org, sc.scope_of(org, who), rows, selection)


def viewers_of(org, own):
    """그 광고주를 여는 사람 — 조직 표의 모든 번호 중 can_see 가 참인 사람."""
    return frozenset(p for p in org.people if sc.can_see(org, sc.scope_of(org, p), own))


# ── 시안 숫자 ──────────────────────────────────────────────────────

class MockupNumbersTest(unittest.TestCase):
    def setUp(self):
        self.org, self.rows = build()

    def test_보이는_광고주_수가_시안과_같다(self):
        expect = {KIM: 9, LEE: 16, HAN: 29, CEO: 31, PARK: 0, CHOI: 11, JEONG: 6, BAK: 5}
        got = {who: len(visible(self.org, self.rows, who)) for who in expect}
        self.assertEqual(got, expect)

    def test_김담당은_메인_8곳과_서브_1곳(self):
        kim = visible(self.org, self.rows, KIM)
        mains = frozenset(c for c, _, m, _ in MOCKUP_CLIENTS if m == KIM)
        self.assertEqual(len(mains), 8)
        self.assertEqual(kim, mains | {CID["tapa"]})
        s = sc.scope_of(self.org, KIM)
        self.assertEqual(sc.relation(self.org, s, self.rows[CID["tapa"]]), sc.REL_SUB)
        self.assertEqual(sc.relation(self.org, s, self.rows[CID["dara"]]), sc.REL_MAIN)
        self.assertEqual(sc.allowed_actions(self.org, s, self.rows[CID["tapa"]]), sc.FULL_ACTIONS)

    def test_범위_종류(self):
        kinds = {who: sc.scope_of(self.org, who).kind for who in
                 (CEO, HAN, LEE, CHOI, KIM, BAK, JEONG, PARK, OH, SUSPENDED, DELETED, YOON,
                  SYS_MGR_RESIGNED_TEAM, SYS_MGR_UNSORTED)}
        self.assertEqual(kinds, {
            CEO: sc.ALL, HAN: sc.TEAM, LEE: sc.TEAM, CHOI: sc.TEAM,
            KIM: sc.MINE, BAK: sc.MINE, JEONG: sc.MINE, PARK: sc.MINE,
            OH: sc.NONE, SUSPENDED: sc.NONE, DELETED: sc.NONE, YOON: sc.NONE,
            SYS_MGR_RESIGNED_TEAM: sc.MINE, SYS_MGR_UNSORTED: sc.MINE,
        })

    def test_번호가_아니거나_사람이_아니면_범위_없음(self):
        self.assertEqual(sc.scope_of(self.org, 0).kind, sc.ALL)   # 0 = 대표 계정(운영 실측) — 「없음」이 아니다
        for bad in (-1, -2, None, True, False, "0", 0.0, "112", 112.0, UNKNOWN_OWNER):
            s = sc.scope_of(self.org, bad)
            self.assertEqual(s.kind, sc.NONE, bad)
            self.assertEqual(sc.clients_in(self.org, s, self.rows, "all"), frozenset())

    def test_팀_범위는_본인_팀과_하부_팀(self):
        self.assertEqual(sc.scope_of(self.org, LEE).teams, {T_1})
        self.assertEqual(sc.scope_of(self.org, CHOI).teams, {T_2})
        self.assertEqual(sc.scope_of(self.org, HAN).teams, {T_HQ, T_1, T_2})

    def test_좁히기(self):
        o, r = self.org, self.rows
        self.assertEqual(visible(o, r, LEE, "me"), ids(["chaka", "haga", "nada"]))
        self.assertEqual(len(visible(o, r, LEE, f"person:{KIM}")), 8)       # 메인 기준(서브 곳은 박담당 몫)
        self.assertEqual(len(visible(o, r, LEE, f"person:{BAK}")), 5)
        self.assertEqual(len(visible(o, r, HAN, f"team:{T_1}")), 16)
        self.assertEqual(len(visible(o, r, HAN, f"team:{T_2}")), 11)
        self.assertEqual(visible(o, r, HAN, f"person:{OH}"), ids(["taga"]))  # 담당 공백도 사람으로 고른다
        self.assertEqual(visible(o, r, CHOI, f"person:{OH}"), ids(["taga"]))
        self.assertEqual(visible(o, r, CEO, "unassigned"), ids(["hana", "gada"]))
        self.assertEqual(len(visible(o, r, CEO, f"team:{T_HQ}")), 29)
        self.assertEqual(visible(o, r, CEO, f"person:{HAN}"), ids(["gaha", "nama"]))
        self.assertEqual(len(visible(o, r, KIM, "me")), 9)
        self.assertEqual(len(visible(o, r, KIM, f"person:{KIM}")), 8)
        self.assertEqual(visible(o, r, CEO, "me"), frozenset())

    def test_담당_상태(self):
        st = {n: sc.owner_state(self.org, self.rows[CID[n]]) for n in ("dara", "taga", "hana", "gada")}
        self.assertEqual(st, {"dara": sc.NORMAL, "taga": sc.VACANT, "hana": sc.UNASSIGNED, "gada": sc.UNASSIGNED})

    def test_이름으로만_이어진_광고주는_담당_미정(self):
        base = self.rows[CID["dara"]]
        for match in (sc.MATCH_NAME, sc.MATCH_UNKNOWN):
            own = sc.Ownership(client_id=base.client_id, main=KIM, match=match)
            self.assertEqual(sc.owner_state(self.org, own), sc.UNASSIGNED)
            self.assertFalse(sc.can_see(self.org, sc.scope_of(self.org, KIM), own))
            self.assertTrue(sc.can_see(self.org, sc.scope_of(self.org, CEO), own))
        # 사전에서 만들 때 연결 방법이 없으면 닫힌 쪽(담당 미정)
        own = sc.ownership_from_mapping(99, {"main": KIM, "sub": None, "prev": None, "source": "MANAGE"})
        self.assertEqual(own.match, sc.MATCH_UNKNOWN)
        self.assertEqual(sc.owner_state(self.org, own), sc.UNASSIGNED)

    def test_연결_방법은_기본값이_없다(self):
        with self.assertRaises(TypeError):
            sc.Ownership(client_id=1, main=KIM)  # type: ignore[call-arg]
        with self.assertRaises(ValueError):
            sc.Ownership(client_id=1, main=KIM, match="maybe")
        with self.assertRaises(ValueError):
            sc.Ownership(client_id=0, main=KIM, match=sc.MATCH_PID)


# ── 고르기 — 좁히기만 · 넓히면 400 · 범위 밖/없음은 같은 404 ─────────

class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.org, self.rows = build(extended=True)

    def _err(self, who, selection):
        try:
            visible(self.org, self.rows, who, selection)
        except sc.ScopeError as e:
            return type(e), str(e)
        return None

    def test_최대_범위보다_넓으면_거절(self):
        for who in (LEE, HAN, CHOI, KIM, PARK):
            self.assertEqual(self._err(who, "unassigned"), (sc.SelectionRejected, sc.SELECTION_REJECTED), who)

    def test_틀린_글자는_거절(self):
        for sel in ("ALL", "global", "company", "", "person:", "person:-1", "team:abc", "person:1:2",
                    "team: 11", "person:١١٢", None, 5, ["all"]):
            self.assertEqual(self._err(CEO, sel), (sc.SelectionRejected, sc.SELECTION_REJECTED), sel)

    def test_범위_밖과_없는_사람_팀은_같은_예외_같은_문구(self):
        cases = [
            (LEE, f"person:{JEONG}"), (LEE, f"person:{CEO}"), (LEE, "person:99999"), (LEE, f"person:{YOON}"),
            (LEE, f"team:{T_2}"), (LEE, f"team:{T_HQ}"), (LEE, "team:99999"),
            (KIM, f"team:{T_1}"), (KIM, f"person:{BAK}"), (KIM, "person:99999"), (KIM, "team:99999"),
            (CHOI, f"person:{KIM}"), (HAN, f"team:{T_CEO}"), (HAN, f"person:{CEO}"),
            (CEO, f"team:{T_RESIGNED}"), (CEO, f"team:{T_UNSORTED}"), (CEO, "team:99999"),
            (CEO, f"person:{UNKNOWN_OWNER}"), (CEO, f"person:{YOON}"),
            (OH, f"person:{OH}"), (YOON, f"team:{T_1}"),
        ]
        errors = {(who, sel): self._err(who, sel) for who, sel in cases}
        self.assertEqual(set(errors.values()), {(sc.TargetNotVisible, sc.TARGET_NOT_VISIBLE)}, errors)

    def test_고르면_늘_좁아진다(self):
        rnd = random.Random(20260928)
        people = list(self.org.people) + [YOON, 0, -1]
        sels = ["all", "me", "unassigned"] + [f"person:{p}" for p in list(self.org.people) + [UNKNOWN_OWNER, YOON]] \
            + [f"team:{t}" for t in list(self.org.teams) + [99999]]
        for _ in range(600):
            who, sel = rnd.choice(people), rnd.choice(sels)
            full = visible(self.org, self.rows, who, "all")
            try:
                part = visible(self.org, self.rows, who, sel)
            except sc.ScopeError:
                continue
            self.assertLessEqual(part, full, (who, sel))


# ── 단건 — 범위 밖과 없는 광고주는 같은 404 ───────────────────────────

class RequireClientTest(unittest.TestCase):
    def test_무작위_사람과_번호(self):
        org, rows = build(extended=True)
        rnd = random.Random(7)
        people = list(org.people) + [YOON, 0, -1, None]
        client_ids = list(range(-3, 60)) + ["1", None, 1.0, True]
        failures, kinds = set(), set()
        for _ in range(3000):
            who, cid = rnd.choice(people), rnd.choice(client_ids)
            s = sc.scope_of(org, who)
            try:
                own = sc.require_client(org, s, rows, cid, sc.ACT_VIEW)
            except sc.ScopeError as e:
                failures.add((type(e), str(e)))
                kinds.add("없음" if (not isinstance(cid, int) or isinstance(cid, bool) or cid not in rows) else "범위 밖")
                continue
            self.assertIn(own.client_id, sc.clients_in(org, s, rows, "all"))
        self.assertEqual(failures, {(sc.ClientNotVisible, sc.CLIENT_NOT_VISIBLE)})
        self.assertEqual(kinds, {"없음", "범위 밖"})  # 두 경우 모두 실제로 나왔다(시험이 헛돌지 않음)

    def test_보이는_것과_단건이_같다(self):
        org, rows = build(extended=True)
        for who in list(org.people) + [YOON]:
            s = sc.scope_of(org, who)
            ok = set()
            for cid in rows:
                try:
                    sc.require_client(org, s, rows, cid, sc.ACT_VIEW)
                    ok.add(cid)
                except sc.ClientNotVisible:
                    pass
            self.assertEqual(ok, set(sc.clients_in(org, s, rows, "all")), who)


# ── 알림 ────────────────────────────────────────────────────────────

class AlertRecipientsTest(unittest.TestCase):
    def setUp(self):
        self.org, self.rows = build(extended=True)

    def rcpt(self, name_or_cid, level):
        cid = CID.get(name_or_cid, name_or_cid)
        return sc.alert_recipients(self.org, self.rows[cid], level)

    def test_시안과_같은_받는_사람(self):
        self.assertEqual(self.rcpt("dara", sc.URGENT), {KIM, LEE, CEO})
        self.assertEqual(self.rcpt("dara", sc.CAUTION), {KIM})
        self.assertEqual(sc.digest_recipients(self.org, self.rows[CID["dara"]]), {LEE})
        self.assertEqual(self.rcpt("paha", sc.URGENT), {JEONG, CHOI, CEO})
        self.assertEqual(self.rcpt("chaka", sc.URGENT), {LEE, HAN, CEO})   # 팀장 본인 담당 → 다음 윗사람
        self.assertEqual(sc.digest_recipients(self.org, self.rows[CID["chaka"]]), {HAN})
        self.assertEqual(self.rcpt("gaha", sc.URGENT), {HAN, CEO})
        self.assertEqual(self.rcpt("taga", sc.CAUTION), {CHOI})            # 담당 공백 → 팀장이 대신
        self.assertEqual(self.rcpt("taga", sc.URGENT), {CHOI, CEO})
        for n in ("hana", "gada"):
            self.assertEqual(self.rcpt(n, sc.URGENT), {CEO})
            self.assertEqual(self.rcpt(n, sc.CAUTION), {CEO})

    def test_서브는_긴급만_받는다(self):
        self.assertEqual(self.rcpt("tapa", sc.URGENT), {BAK, KIM, LEE, CEO})
        self.assertEqual(self.rcpt("tapa", sc.CAUTION), {BAK})
        self.assertIn(KIM, self.rcpt("tapa", sc.URGENT))
        self.assertNotIn(KIM, self.rcpt("tapa", sc.CAUTION))

    def test_이전_담당(self):
        own = self.rows[PREV_CLIENT]
        self.assertEqual(sc.owner_state(self.org, own), sc.PREV)
        self.assertEqual(sc.alert_recipients(self.org, own, sc.CAUTION), {LEE})
        self.assertEqual(sc.alert_recipients(self.org, own, sc.URGENT), {KIM, LEE, CEO})

    def test_받는_사람은_그_광고주를_여는_사람(self):
        for cid, own in self.rows.items():
            can = viewers_of(self.org, own)
            for level in (sc.URGENT, sc.CAUTION):
                got = sc.alert_recipients(self.org, own, level)
                self.assertTrue(got, (cid, level))
                self.assertLessEqual(got, can, (cid, level))
                self.assertTrue(all(self.org.people[p].active for p in got), (cid, level))
            self.assertLessEqual(sc.digest_recipients(self.org, own), can, cid)

    def test_등급이_틀리면_거절(self):
        with self.assertRaises(ValueError):
            sc.alert_recipients(self.org, self.rows[1], "info")


# ── 승인 ────────────────────────────────────────────────────────────

class ApproversTest(unittest.TestCase):
    def setUp(self):
        self.org, self.rows = build(extended=True)

    def chain(self, cid, level, requester):
        return sc.approvers(self.org, self.rows[CID.get(cid, cid)], level, requester)

    def test_팀장_등급_사슬(self):
        self.assertEqual(self.chain("maba", sc.LEVEL_LEAD, KIM), ({LEE}, {HAN}, {CEO}))
        self.assertEqual(self.chain("chaka", sc.LEVEL_LEAD, LEE), ({HAN}, {CEO}))   # 자기 광고주 → 윗사람
        self.assertEqual(self.chain("gaha", sc.LEVEL_LEAD, HAN), ({CEO},))
        self.assertEqual(self.chain("taga", sc.LEVEL_LEAD, CHOI), ({HAN}, {CEO}))
        self.assertEqual(self.chain("hana", sc.LEVEL_LEAD, None), ({CEO},))
        self.assertEqual(self.chain(CEO_CLIENT, sc.LEVEL_LEAD, CEO), ({CEO},))     # 대표는 위가 없다
        self.assertEqual(self.chain(PREV_CLIENT, sc.LEVEL_LEAD, None), ({LEE}, {HAN}, {CEO}))

    def test_담당자_등급_사슬(self):
        self.assertEqual(self.chain("dara", sc.LEVEL_STAFF, None), ({KIM}, {LEE}, {HAN}, {CEO}))
        self.assertEqual(self.chain("tapa", sc.LEVEL_STAFF, None), ({BAK, KIM}, {LEE}, {HAN}, {CEO}))
        self.assertEqual(self.chain("taga", sc.LEVEL_STAFF, None), ({CHOI}, {HAN}, {CEO}))
        self.assertEqual(self.chain(PREV_CLIENT, sc.LEVEL_STAFF, None), ({LEE}, {HAN}, {CEO}))

    def test_이전_담당은_보기와_멈추기만(self):
        own = self.rows[PREV_CLIENT]
        s = sc.scope_of(self.org, KIM)
        self.assertTrue(sc.can_see(self.org, s, own))
        self.assertEqual(sc.relation(self.org, s, own), sc.REL_PREV)
        self.assertEqual(sc.allowed_actions(self.org, s, own), {sc.ACT_VIEW, sc.ACT_STOP})
        self.assertFalse(sc.can_see(self.org, sc.scope_of(self.org, BAK), own))
        self.assertEqual(len(visible(self.org, self.rows, KIM)), 10)
        self.assertEqual(len(visible(self.org, self.rows, LEE)), 17)

    def _requesters(self):
        return list(self.org.people) + [None, YOON]

    def test_승인자는_그_광고주를_여는_사람(self):
        for cid, own in self.rows.items():
            can = viewers_of(self.org, own)
            for level in (sc.LEVEL_STAFF, sc.LEVEL_LEAD):
                for req in self._requesters():
                    tiers = sc.approvers(self.org, own, level, req)
                    union = frozenset().union(*tiers)
                    self.assertTrue(union, (cid, level, req))
                    self.assertLessEqual(union, can, (cid, level, req))
                    self.assertEqual(sum(len(t) for t in tiers), len(union), "묶음끼리 겹치면 안 된다")

    def test_담당자_등급_승인자는_승인_권한이_있는_재직자와_같다(self):
        for cid, own in self.rows.items():
            union = frozenset().union(*sc.approvers(self.org, own, sc.LEVEL_STAFF, None))
            allowed = frozenset(p for p in self.org.people
                                if sc.ACT_APPROVE in sc.allowed_actions(self.org, sc.scope_of(self.org, p), own))
            self.assertEqual(union, allowed, cid)

    def test_팀장_등급은_자기_승인_금지(self):
        assert_no_self_approval(self, self.org, self.rows, self._requesters())

    def test_누를_때_다시_판정(self):
        own = self.rows[CID["maba"]]
        self.assertTrue(sc.can_approve(self.org, own, sc.LEVEL_LEAD, KIM, LEE))
        self.assertTrue(sc.can_approve(self.org, own, sc.LEVEL_LEAD, KIM, HAN))   # 상위 팀장은 언제든
        self.assertFalse(sc.can_approve(self.org, own, sc.LEVEL_LEAD, KIM, KIM))
        self.assertFalse(sc.can_approve(self.org, own, sc.LEVEL_LEAD, KIM, CHOI))
        self.assertFalse(sc.can_approve(self.org, own, sc.LEVEL_LEAD, LEE, LEE))


def owners_of(org, own):
    """시험 쪽에서 따로 센 「그 광고주의 담당」(메인·서브 · 이전 담당이면 직전 담당) — 모듈 속 함수를 쓰지 않는다."""
    st = sc.owner_state(org, own)
    if st == sc.UNASSIGNED:
        return frozenset()
    out = {own.prev} if st == sc.PREV else {own.main}
    if own.sub is not None and own.sub != own.main and own.sub in org.people:
        out.add(own.sub)
    return frozenset(out)


def assert_no_self_approval(tc, org, rows, requesters):
    """팀장 등급: 요청자·담당(메인·서브·직전)은 승인자가 아니다. 예외는 하나 — 대표이고 비켜 줄 다른 대표가 없을 때(마지막 묶음).
    요청자 본인은 다른 대표가 한 명이라도 있으면 끝까지 빠진다."""
    ceos = org.top_managers()
    for cid, own in rows.items():
        owners = owners_of(org, own)
        for req in requesters:
            tiers = sc.approvers(org, own, sc.LEVEL_LEAD, req)
            union = frozenset().union(*tiers)
            if req is not None and req in union:
                tc.assertIn(req, ceos, (cid, req))
                tc.assertFalse(ceos - {req}, (cid, req))
                tc.assertIn(req, tiers[-1], (cid, req))
            for who in owners - {req}:
                if who in union:
                    tc.assertIn(who, ceos, (cid, req, who))
                    tc.assertIn(who, tiers[-1], (cid, req, who))
                    tc.assertFalse(ceos - owners - {req}, (cid, req, who))
            for who in union:
                tc.assertTrue(sc.can_approve(org, own, sc.LEVEL_LEAD, req, who), (cid, req, who))


# ── 비상 정지 ────────────────────────────────────────────────────────

class KillSetTest(unittest.TestCase):
    def setUp(self):
        self.org, self.rows = build()

    def test_범위별_정지_집합(self):
        lee = sc.kill_set(self.org, sc.scope_of(self.org, LEE), self.rows)
        self.assertEqual((lee.kind, len(lee.client_ids), lee.by_idx), ("TEAM", 16, LEE))
        han = sc.kill_set(self.org, sc.scope_of(self.org, HAN), self.rows)
        self.assertEqual((han.kind, len(han.client_ids)), ("TEAM", 29))
        ceo = sc.kill_set(self.org, sc.scope_of(self.org, CEO), self.rows)
        self.assertEqual((ceo.kind, ceo.client_ids), ("GLOBAL", None))

    def test_정지는_보기_좁히기와_무관(self):
        self.assertEqual(len(visible(self.org, self.rows, LEE, "me")), 3)
        lee = sc.kill_set(self.org, sc.scope_of(self.org, LEE), list(self.rows.values()))
        self.assertEqual(lee.client_ids, visible(self.org, self.rows, LEE, "all"))

    def test_담당자와_범위_없음은_묶음_정지_불가(self):
        for who in (KIM, PARK, BAK, OH, YOON, SYS_MGR_RESIGNED_TEAM):
            with self.assertRaises(sc.StopNotAllowed):
                sc.kill_set(self.org, sc.scope_of(self.org, who), self.rows)


# ── 시스템 팀 · 뿌리 0 · 순환 ──────────────────────────────────────────

class TeamTreeTest(unittest.TestCase):
    def test_시스템_팀에_앉은_팀장은_팀_범위가_아니다(self):
        org, rows = build()
        for who in (SYS_MGR_RESIGNED_TEAM, SYS_MGR_UNSORTED):
            s = sc.scope_of(org, who)
            self.assertEqual(s.kind, sc.MINE, who)
            self.assertEqual(sc.clients_in(org, s, rows, "all"), frozenset(), who)
        # ① 가 is_system 을 놓쳐도 이름 「퇴사자」 면 시스템 팀
        p = mockup_payload()
        for t in p["teams"]:
            if t["idx"] == T_RESIGNED:
                t["is_system"] = False
        org2, rows2 = build(payload=p)
        self.assertEqual(sc.scope_of(org2, SYS_MGR_RESIGNED_TEAM).kind, sc.MINE)

    def test_부모_0에서_전사로_퍼지지_않는다(self):
        org, rows = build(extended=True)
        self.assertNotIn(0, org.children)
        self.assertEqual(org.subtree(0), frozenset())
        self.assertEqual(org.subtree(T_RESIGNED), frozenset())
        self.assertEqual(org.subtree(T_HQ), {T_HQ, T_1, T_2})
        # 최상위 팀(부모 0) 팀장은 다른 최상위 팀(대표실)의 광고주를 보지 못한다
        self.assertNotIn(CEO_CLIENT, visible(org, rows, HAN))
        self.assertEqual(len(visible(org, rows, HAN)), 30)   # 29 + 이전 담당(1팀) 1곳
        self.assertEqual(len(visible(org, rows, CEO)), 33)

    def test_퇴사자_팀으로_옮겨진_공백_담당은_대표만(self):
        p = mockup_payload()
        for e in p["employees"]:
            if e["idx"] == OH:
                e["team_idx"] = T_RESIGNED
        org, rows = build(payload=p)
        own = rows[CID["taga"]]
        self.assertEqual(viewers_of(org, own), {CEO})
        self.assertEqual(sc.alert_recipients(org, own, sc.CAUTION), {CEO})
        self.assertEqual(sc.approvers(org, own, sc.LEVEL_STAFF, None), ({CEO},))

    def test_시스템_팀_아래_팀은_위로_새지_않는다(self):
        # ① 조직도가 잘못 걸려 시스템 팀 밑에 보통 팀이 달린 경우 — 하부 팀 훑기는 시스템 팀을 지나 내려가지 않으므로
        # 그 위 팀장(한본부장)은 이 팀을 보지 못한다. 그러면 알림·승인 사슬도 그를 건너뛰어야 한다(받는 사람 ⊆ 여는 사람).
        p = mockup_payload()
        p["teams"] += [_team(61, "잘못 걸린 시스템 팀", 2, T_HQ, True), _team(62, "그 아래 팀", 3, 61)]
        p["employees"] += [_emp(620, "아래 팀장", 62, manager=True), _emp(621, "아래 담당", 62)]
        p["owners"] += [_owner(62, 621)]
        org, rows = build(payload=p)
        own = rows[62]
        self.assertNotIn(62, visible(org, rows, HAN))
        self.assertEqual(viewers_of(org, own), {621, 620, CEO})
        self.assertEqual(sc.approvers(org, own, sc.LEVEL_LEAD, 620), ({CEO},))
        self.assertEqual(sc.approvers(org, own, sc.LEVEL_STAFF, None), ({621}, {620}, {CEO}))
        for level in (sc.URGENT, sc.CAUTION):
            self.assertLessEqual(sc.alert_recipients(org, own, level), viewers_of(org, own))
        for req in list(org.people) + [None]:
            for level in (sc.LEVEL_STAFF, sc.LEVEL_LEAD):
                union = frozenset().union(*sc.approvers(org, own, level, req))
                self.assertLessEqual(union, viewers_of(org, own), (req, level))

    def _cycle_payload(self):
        p = mockup_payload()
        p["teams"] += [_team(40, "순환 A", 2, 41), _team(41, "순환 B", 2, 40), _team(42, "순환 아래", 3, 40),
                       _team(43, "제자리", 2, 43)]
        p["employees"] += [_emp(401, "A 팀장", 40, manager=True), _emp(402, "A 담당", 40),
                           _emp(421, "아래 팀장", 42, manager=True), _emp(422, "아래 담당", 42),
                           _emp(431, "제자리 팀장", 43, manager=True)]
        p["owners"] += [_owner(40, 402), _owner(42, 422)]
        return p

    def test_순환_팀은_막고_멈추지_않는다(self):
        p = self._cycle_payload()
        org = snap.parse_org_snapshot(p)
        self.assertEqual(org.cyclic_teams, {40, 41, 43})
        rows = {row.possibility_id - PID_BASE: sc.ownership_from_owner_row(row.possibility_id - PID_BASE, row, sc.MATCH_PID)
                for row in org.owners}
        self.assertEqual(sc.scope_of(org, 401).kind, sc.MINE)       # 순환 팀 팀장 → 본인 범위
        self.assertEqual(sc.scope_of(org, 431).kind, sc.MINE)
        s421 = sc.scope_of(org, 421)
        self.assertEqual((s421.kind, s421.teams), (sc.TEAM, {42}))
        self.assertEqual(sc.clients_in(org, s421, rows, "all"), {42})
        self.assertEqual(viewers_of(org, rows[40]), {402, CEO})
        self.assertEqual(sc.alert_recipients(org, rows[42], sc.URGENT), {422, 421, CEO})
        self.assertEqual(sc.approvers(org, rows[42], sc.LEVEL_LEAD, 422), ({421}, {CEO}))
        self.assertIsInstance(sc.clients_in(org, sc.scope_of(org, CEO), rows, "team:40"), frozenset)
        # 건전성 검사는 순환을 버린다 — 이전 조직을 그대로 쓴다
        prev, _ = build()
        d = snap.accept_snapshot(p, prev)
        self.assertFalse(d.ok)
        self.assertIs(d.org, prev)
        self.assertIn("CYCLE", {f.code for f in d.reasons})


# ── 조직 스냅숏 — 형식 · 건전성 · 전부 받거나 전부 버린다 ─────────────

def _with_extra_staff(n):
    p = mockup_payload()
    p["employees"] += [_emp(1000 + i, f"추가 직원 {i}", T_2) for i in range(n)]
    return p


def _resign(p, n):
    q = copy.deepcopy(p)
    extra = [e for e in q["employees"] if e["idx"] >= 1000]
    for e in extra[:n]:
        e["status"] = "RESIGNED"
    q["generated_at"] = _next_time()
    return q


class SnapshotTest(unittest.TestCase):
    def codes(self, decision):
        return {f.code for f in decision.reasons}

    def test_처음_받기와_래핑(self):
        d = snap.accept_snapshot(mockup_payload(), None)
        self.assertTrue(d.ok)
        wrapped = snap.accept_snapshot({"status": 200, "result": mockup_payload()}, None)
        self.assertTrue(wrapped.ok)
        self.assertEqual(len(wrapped.org.people), len(d.org.people))
        self.assertEqual(len(wrapped.org.owners), 31)
        self.assertEqual(d.org.active_count(), 10)

    def test_재직_직원_감소(self):
        base = _with_extra_staff(30)                       # 재직 40명
        prev = snap.accept_snapshot(base, None).org
        self.assertEqual(prev.active_count(), 40)
        drop25 = snap.accept_snapshot(_resign(base, 10), prev)
        self.assertFalse(drop25.ok)
        self.assertIn("ACTIVE_DROP", self.codes(drop25))
        self.assertIs(drop25.org, prev)
        self.assertTrue(snap.accept_snapshot(_resign(base, 4), prev).ok)   # 10% 감소 — 받음
        self.assertTrue(snap.accept_snapshot(_resign(base, 8), prev).ok)   # 딱 20% — 받음(넘어야 버림)
        self.assertFalse(snap.accept_snapshot(_resign(base, 9), prev).ok)  # 22.5% — 버림

    def test_있던_팀의_부모가_사라짐(self):
        prev = snap.accept_snapshot(mockup_payload(), None).org
        p = mockup_payload()
        p["teams"] = [t for t in p["teams"] if t["idx"] != T_HQ]
        d = snap.accept_snapshot(p, prev)
        self.assertFalse(d.ok)
        self.assertIn("PARENT_LOST", self.codes(d))
        self.assertIs(d.org, prev)

    def test_새_팀의_부모가_없으면_경고만_그_팀장은_본인_범위(self):
        prev = snap.accept_snapshot(mockup_payload(), None).org
        p = mockup_payload()
        p["teams"].append(_team(50, "새 팀", 2, 49))
        p["employees"].append(_emp(501, "새 팀장", 50, manager=True))
        d = snap.accept_snapshot(p, prev)
        self.assertTrue(d.ok, d.reasons)
        self.assertIn("ORPHAN_TEAM", {f.code for f in d.check.warnings})
        self.assertEqual(sc.scope_of(d.org, 501).kind, sc.MINE)

    def test_담당_빈칸_급증(self):
        prev = snap.accept_snapshot(mockup_payload(), None).org            # 빈칸 1/31
        p = mockup_payload()
        for o in p["owners"][:5]:
            o["manage_emp_idx"] = None                                     # 6/31 = +16%p
        d = snap.accept_snapshot(p, prev)
        self.assertFalse(d.ok)
        self.assertIn("OWNER_BLANK_SPIKE", self.codes(d))
        q = mockup_payload()
        for o in q["owners"][:3]:
            o["manage_emp_idx"] = None                                     # 4/31 = +9.7%p
        self.assertTrue(snap.accept_snapshot(q, prev).ok)

    def test_담당_줄_급감(self):
        prev = snap.accept_snapshot(mockup_payload(), None).org
        p = mockup_payload()
        p["owners"] = p["owners"][:24]                                     # 31 → 24 (22.6%)
        d = snap.accept_snapshot(p, prev)
        self.assertFalse(d.ok)
        self.assertIn("OWNER_DROP", self.codes(d))
        q = mockup_payload()
        q["owners"] = q["owners"][:26]                                     # 31 → 26 (16%)
        self.assertTrue(snap.accept_snapshot(q, prev).ok)

    def test_빈_조직(self):
        p = mockup_payload()
        for e in p["employees"]:
            e["status"] = "RESIGNED"
        d = snap.accept_snapshot(p, None)
        self.assertFalse(d.ok)
        self.assertIn("EMPTY", self.codes(d))
        self.assertIsNone(d.org)

    def test_한_줄만_틀려도_전부_버린다(self):
        prev = snap.accept_snapshot(mockup_payload(), None).org
        before = {i: (p.status, p.team_idx, p.is_manager) for i, p in prev.people.items()}

        def broken(fn):
            p = mockup_payload()
            fn(p)
            return p

        bads = {
            "팀장 칸이 글자": broken(lambda p: p["employees"][-1].__setitem__("is_manager", "Y")),
            "상태가 숫자": broken(lambda p: p["employees"][3].__setitem__("status", 1)),
            "시스템 계정": broken(lambda p: p["employees"].append(_emp(-1, "시스템", T_UNSORTED))),
            "직원 번호 중복": broken(lambda p: p["employees"].append(_emp(KIM, "김담당2", T_1))),
            "팀 번호 중복": broken(lambda p: p["teams"].append(_team(T_1, "관리 1팀", 2, T_HQ))),
            "가망 번호 중복": broken(lambda p: p["owners"].append(_owner(1, KIM))),
            "담당 번호가 글자": broken(lambda p: p["owners"][-1].__setitem__("manage_emp_idx", "112")),
            "칸 없음": broken(lambda p: p["teams"][2].pop("parent_idx")),
            "목록 없음": broken(lambda p: p.pop("owners")),
            "시각 없음": broken(lambda p: p.__setitem__("generated_at", "")),
            "시각 글자 아님": broken(lambda p: p.__setitem__("generated_at", "not-a-time")),
            "시간대 없음": broken(lambda p: p.__setitem__("generated_at", "2026-09-28T23:00:00")),
            "참거짓 대신 숫자": broken(lambda p: p["employees"][0].__setitem__("is_top_manager", 1)),
        }
        bads["래핑 status 500"] = {"status": 500, "result": mockup_payload()}
        bads["래핑 status 글자"] = {"status": "200", "result": mockup_payload()}
        for label, payload in bads.items():
            keep = copy.deepcopy(payload)
            d = snap.accept_snapshot(payload, prev)
            self.assertFalse(d.ok, label)
            self.assertEqual(self.codes(d), {"FORMAT"}, label)
            self.assertIs(d.org, prev, label)
            self.assertEqual(payload, keep, f"{label}: 받은 응답을 고치면 안 된다")
        self.assertEqual({i: (p.status, p.team_idx, p.is_manager) for i, p in prev.people.items()}, before)
        self.assertIsNone(snap.accept_snapshot("not json", None).org)
        with self.assertRaises(snap.SnapshotFormatError):
            snap.parse_org_snapshot(bads["시스템 계정"])

    def test_모르는_상태는_재직_아님(self):
        p = mockup_payload()
        for e in p["employees"]:
            if e["idx"] == KIM:
                e["status"] = "active"   # 소문자 — ① 에 없는 글자
        d = snap.accept_snapshot(p, None)
        self.assertTrue(d.ok)
        self.assertIn("UNKNOWN_STATUS", {f.code for f in d.check.warnings})
        self.assertEqual(sc.scope_of(d.org, KIM).kind, sc.NONE)

    def test_조직은_바뀌지_않는다(self):
        org, _ = build()
        with self.assertRaises(TypeError):
            org.people[KIM] = None  # type: ignore[index]
        with self.assertRaises(TypeError):
            org.teams[99] = None  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            org.people[KIM].is_manager = True  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            org.generated_at = "x"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            sc.scope_of(org, LEE).kind = sc.ALL  # type: ignore[misc]


# ── 검토 반영(2026-09-28) ─────────────────────────────────────────────
# ① 계약 모양 · 낡은 Scope · 번호 형식 · 대표 위는 없음 · 서브 팀장 · 대표 둘 · 할 일 줄 · 팀 정지 · 예시 조직 빈 곳 · 권한 확대 스냅숏

# ① ERP_CONTRACT_SYNC_API.md §9.2 응답 예시 원문 그대로(이름·번호 예시)
ERP_EXAMPLE_JSON = """
{
  "status": 200,
  "result": {
    "generated_at": "2026-09-28T14:00:00+09:00",
    "teams": [
      { "idx": 0,  "name": "미분류",    "level": 0, "parent_idx": 0,  "is_system": true  },
      { "idx": 10, "name": "관리 본부", "level": 1, "parent_idx": 0,  "is_system": false },
      { "idx": 11, "name": "관리 1팀",  "level": 2, "parent_idx": 10, "is_system": false }
    ],
    "employees": [
      { "idx": 0,   "name": "대표",   "team_idx": 0,  "is_manager": true,  "is_top_manager": true,  "status": "ACTIVE",   "is_deleted": false },
      { "idx": 101, "name": "가팀장", "team_idx": 11, "is_manager": true,  "is_top_manager": false, "status": "ACTIVE",   "is_deleted": false },
      { "idx": 102, "name": "나담당", "team_idx": 11, "is_manager": false, "is_top_manager": false, "status": "RESIGNED", "is_deleted": false }
    ],
    "owners": [
      { "possibility_id": 5001, "manage_emp_idx": 101,  "sub_manage_emp_idx": 102,  "prev_manage_owner_idx": null, "sales_emp_idx": 101,  "owner_source": "manage" },
      { "possibility_id": 5002, "manage_emp_idx": null, "sub_manage_emp_idx": null, "prev_manage_owner_idx": 102,  "sales_emp_idx": null, "owner_source": "prev" }
    ]
  }
}
"""


class ErpContractShapeTest(unittest.TestCase):
    """① 가 실제로 보내는 모양(-1 대신 null + owner_source 'prev' · status null)을 그대로 읽는다."""

    def test_전산_예시_응답을_그대로_읽는다(self):
        d = snap.accept_snapshot(json.loads(ERP_EXAMPLE_JSON), None)
        self.assertTrue(d.ok, d.reasons)
        org = d.org
        own1 = sc.ownership_for_client(org, 1, 5001, sc.MATCH_PID)
        own2 = sc.ownership_for_client(org, 2, 5002, sc.MATCH_PID)
        self.assertEqual(sc.owner_state(org, own1), sc.NORMAL)
        self.assertEqual(sc.owner_state(org, own2), sc.PREV)         # -1 이 아니라 null + prev
        lead = sc.scope_of(org, 101)
        self.assertEqual((lead.kind, lead.teams), (sc.TEAM, {11}))
        self.assertEqual(sc.clients_in(org, lead, [own1, own2]), {1, 2})
        self.assertEqual(sc.relation(org, lead, own2), sc.REL_TEAM)
        self.assertEqual(sc.scope_of(org, 102).kind, sc.NONE)        # 퇴사 → 범위 없음
        self.assertEqual(sc.alert_recipients(org, own2, sc.CAUTION), {101})
        self.assertNotIn("TOP_MANAGER_COUNT", {f.code for f in d.check.warnings})   # 대표는 0번 한 명
        ceo = sc.scope_of(org, 0)                                                  # 0 = 대표 — 전사
        self.assertEqual(ceo.kind, sc.ALL)
        self.assertEqual(sc.clients_in(org, ceo, [own1, own2]), {1, 2})
        # 스냅숏에 없는 가망 · 가망 번호 없음 → 담당 미정
        self.assertEqual(sc.owner_state(org, sc.ownership_for_client(org, 3, 9999, sc.MATCH_PID)), sc.UNASSIGNED)
        self.assertEqual(sc.owner_state(org, sc.ownership_for_client(org, 3, None, sc.MATCH_PID)), sc.UNASSIGNED)

    def test_계약_만료는_이전_담당(self):
        org, rows = build(extended=True)
        own = rows[PREV_CLIENT]
        self.assertEqual((own.main, own.prev, own.source), (None, KIM, "prev"))
        self.assertEqual(sc.owner_state(org, own), sc.PREV)
        s = sc.scope_of(org, KIM)
        self.assertEqual(sc.allowed_actions(org, s, own), {sc.ACT_VIEW, sc.ACT_STOP})
        self.assertTrue(sc.can_see(org, sc.scope_of(org, LEE), own))
        self.assertEqual(viewers_of(org, own), {KIM, LEE, HAN, CEO})

    def test_출처가_prev_가_아니면_이전_담당이_아니다(self):
        org, _ = build()
        for src in (None, "none", "manage", "PREV", "Prev"):
            own = sc.Ownership(client_id=99, main=None, prev=KIM, source=src, match=sc.MATCH_PID)
            self.assertEqual(sc.owner_state(org, own), sc.UNASSIGNED, src)
        # 손으로 만든 자료의 -1 도 출처가 prev 일 때만
        self.assertEqual(sc.owner_state(org, sc.Ownership(client_id=99, main=-1, prev=KIM, source="prev",
                                                          match=sc.MATCH_PID)), sc.PREV)
        self.assertEqual(sc.owner_state(org, sc.Ownership(client_id=99, main=-1, prev=KIM, match=sc.MATCH_PID)),
                         sc.UNASSIGNED)
        # 직전 담당이 직원 표에 없으면 담당 미정
        self.assertEqual(sc.owner_state(org, sc.Ownership(client_id=99, main=None, prev=UNKNOWN_OWNER,
                                                          source="prev", match=sc.MATCH_PID)), sc.UNASSIGNED)

    def test_계약_만료가_늘어도_빈칸_급증이_아니다(self):
        prev = snap.accept_snapshot(mockup_payload(), None).org
        p = mockup_payload()
        expired = [1, 2, 3, 4, 5]                                      # 김담당 5곳 계약 만료
        p["owners"] = [(_owner(cid, -1, None, KIM) if row["possibility_id"] - PID_BASE in expired else row)
                       for cid, row in ((r["possibility_id"] - PID_BASE, r) for r in p["owners"])]
        d = snap.accept_snapshot(p, prev)
        self.assertTrue(d.ok, d.reasons)
        self.assertAlmostEqual(d.org.blank_owner_ratio(), prev.blank_owner_ratio())
        rows = rows_of(d.org)
        self.assertEqual({sc.owner_state(d.org, rows[c]) for c in expired}, {sc.PREV})
        self.assertEqual(len(visible(d.org, rows, LEE)), 16)

    def test_모르는_출처_글자는_경고(self):
        p = mockup_payload()
        p["owners"][0]["owner_source"] = "MANAGE"
        d = snap.accept_snapshot(p, None)
        self.assertTrue(d.ok)
        self.assertIn("UNKNOWN_OWNER_SOURCE", {f.code for f in d.check.warnings})

    def test_상태_빈칸은_받되_재직_아님(self):
        prev = snap.accept_snapshot(mockup_payload(), None).org
        p = mockup_payload()
        for e in p["employees"]:
            if e["idx"] == KIM:
                e["status"] = None
        d = snap.accept_snapshot(p, prev)
        self.assertTrue(d.ok, d.reasons)
        self.assertIn("UNKNOWN_STATUS", {f.code for f in d.check.warnings})
        self.assertEqual(sc.scope_of(d.org, KIM).kind, sc.NONE)
        rows = rows_of(d.org)
        self.assertEqual(sc.owner_state(d.org, rows[CID["dara"]]), sc.VACANT)


class StaleScopeTest(unittest.TestCase):
    """판정 함수는 받은 Scope 를 믿지 않고 이 조직에서 다시 계산한 것과 견준다."""

    def setUp(self):
        self.old_org, self.old_rows = build()
        self.old_lee = sc.scope_of(self.old_org, LEE)
        p = mockup_payload()
        for e in p["employees"]:
            if e["idx"] == LEE:
                e["status"] = "RESIGNED"
        self.new_org, self.new_rows = build(payload=p, prev=self.old_org)

    def assert_none_behaviour(self, org, rows, scope):
        self.assertEqual(sc.clients_in(org, scope, rows, "all"), frozenset())
        self.assertEqual(sc.clients_in(org, scope, rows, "me"), frozenset())
        with self.assertRaises(sc.StopNotAllowed):
            sc.kill_set(org, scope, rows)
        for cid, own in rows.items():
            self.assertFalse(sc.can_see(org, scope, own))
            self.assertIsNone(sc.relation(org, scope, own))
            self.assertEqual(sc.allowed_actions(org, scope, own), frozenset())
            with self.assertRaises(sc.ClientNotVisible):
                sc.require_client(org, scope, rows, cid, sc.ACT_VIEW)

    def test_퇴사한_팀장의_옛_범위(self):
        self.assertEqual(sc.scope_of(self.new_org, LEE).kind, sc.NONE)
        self.assert_none_behaviour(self.new_org, self.new_rows, self.old_lee)

    def test_내용이_같아도_다른_스냅숏의_범위는_안_받는다(self):
        org2, rows2 = build(payload=mockup_payload(), prev=self.old_org)
        old_han = sc.scope_of(self.old_org, HAN)
        self.assert_none_behaviour(org2, rows2, old_han)
        self.assertEqual(len(sc.clients_in(org2, sc.scope_of(org2, HAN), rows2)), 29)   # 새로 계산하면 그대로

    def test_손으로_만든_범위(self):
        org, rows = self.old_org, self.old_rows
        forged = [
            sc.Scope(sc.ALL, KIM, frozenset(org.teams), frozenset(org.people), org.generated_at),
            sc.Scope(sc.TEAM, KIM, frozenset({T_1}), frozenset({KIM}), org.generated_at),
            sc.Scope(sc.ALL, None, frozenset(org.teams), frozenset(org.people), org.generated_at),
            {"kind": sc.ALL, "viewer_idx": CEO},
            None,
        ]
        for scope in forged:
            self.assert_none_behaviour(org, rows, scope)
        self.assertEqual(len(sc.clients_in(org, sc.scope_of(org, KIM), rows)), 9)


class IdTypeTest(unittest.TestCase):
    """글자 '111'(토큰 sub) · 111.0 · 참/거짓은 사람 번호가 아니다 — 승인 판정도 보기 판정만큼 엄격하다."""

    def setUp(self):
        self.org, self.rows = build(extended=True)
        self.own = self.rows[CID["maba"]]

    def test_요청자_번호가_정수가_아니면(self):
        for bad in ("111", 111.0, True, False, "112"):
            with self.assertRaises(ValueError):
                sc.approvers(self.org, self.own, sc.LEVEL_LEAD, bad)
            with self.assertRaises(ValueError):
                sc.todo_chain(self.org, self.own, sc.LEVEL_LEAD, bad)
            for approver in (LEE, HAN, CEO):
                self.assertFalse(sc.can_approve(self.org, self.own, sc.LEVEL_LEAD, bad, approver), (bad, approver))
        # 이팀장 본인 요청(정수)은 이팀장이 승인하지 못한다 — 글자로 바꿔도 풀리지 않는다
        chaka = self.rows[CID["chaka"]]
        self.assertFalse(sc.can_approve(self.org, chaka, sc.LEVEL_LEAD, LEE, LEE))
        self.assertFalse(sc.can_approve(self.org, chaka, sc.LEVEL_LEAD, str(LEE), LEE))

    def test_승인자_번호가_정수가_아니면(self):
        self.assertTrue(sc.can_approve(self.org, self.own, sc.LEVEL_LEAD, KIM, CEO))
        self.assertTrue(sc.can_approve(self.org, self.own, sc.LEVEL_LEAD, KIM, 0))      # 0 = 대표 번호 — 사람이다
        for bad in (True, False, 1.0, 0.0, "0", "1", None, -1, "111", 111.0):
            self.assertFalse(sc.can_approve(self.org, self.own, sc.LEVEL_LEAD, KIM, bad), bad)
            self.assertFalse(sc.can_approve(self.org, self.own, sc.LEVEL_STAFF, None, bad), bad)
        for bad in (True, 1.0):
            self.assertEqual(sc.scope_of(self.org, bad).kind, sc.NONE)

    def test_엄청_긴_번호는_400(self):
        for who in (CEO, LEE, KIM, YOON):
            for sel in ("person:" + "9" * 5000, "team:" + "9" * 5000, "person:" + "1" * 19):
                with self.assertRaises(sc.SelectionRejected):
                    visible(self.org, self.rows, who, sel)
        self.assertEqual(sc.parse_selection("person:" + "1" * 18), ("person", int("1" * 18)))


def _payload_with(extra_teams=(), extra_emps=(), extra_owners=(), mutate=None, extended=True):
    p = mockup_payload(extended)
    p["teams"] += list(extra_teams)
    p["employees"] += list(extra_emps)
    p["owners"] += list(extra_owners)
    if mutate:
        mutate(p)
    return p


class CeoHasNoOneAboveTest(unittest.TestCase):
    """대표실에 팀장이 있어도 대표 본인 광고주 · 대표 요청은 대표 묶음만(위가 없음)."""

    CEO_TEAM_LEAD, CEO_TEAM_STAFF, CEO_STAFF_CLIENT = 131, 132, 35

    def setUp(self):
        # 운영의 대표는 팀 0(미분류 · 시스템)이지만, 나중에 대표실 같은 보통 팀으로 옮겨도 「위가 없음」이 지켜지는지 본다.
        def ceo_in_ceo_team(p):
            for e in p["employees"]:
                if e["idx"] == CEO:
                    e["team_idx"], e["is_manager"] = T_CEO, False
        self.org, self.rows = build(payload=_payload_with(
            extra_emps=[_emp(self.CEO_TEAM_LEAD, "대표실 팀장", T_CEO, manager=True),
                        _emp(self.CEO_TEAM_STAFF, "대표실 담당", T_CEO)],
            extra_owners=[_owner(self.CEO_STAFF_CLIENT, self.CEO_TEAM_STAFF)],
            mutate=ceo_in_ceo_team))

    def test_대표_본인_광고주(self):
        own = self.rows[CEO_CLIENT]
        for req in (CEO, self.CEO_TEAM_LEAD, None):
            self.assertEqual(sc.approvers(self.org, own, sc.LEVEL_LEAD, req), ({CEO},), req)
        self.assertFalse(sc.can_approve(self.org, own, sc.LEVEL_LEAD, CEO, self.CEO_TEAM_LEAD))
        self.assertEqual(sc.digest_recipients(self.org, own), frozenset())
        self.assertEqual(sc.alert_recipients(self.org, own, sc.URGENT), {CEO})
        self.assertEqual(sc.todo_chain(self.org, own, sc.LEVEL_STAFF), ({CEO},))
        # 담당자 등급은 보는 사람이면 누를 수 있다(대표실 팀장은 팀 범위로 이 광고주를 본다)
        self.assertEqual(sc.approvers(self.org, own, sc.LEVEL_STAFF, None), ({CEO}, {self.CEO_TEAM_LEAD}))

    def test_대표실_직원_광고주는_대표실_팀장부터(self):
        own = self.rows[self.CEO_STAFF_CLIENT]
        self.assertEqual(sc.approvers(self.org, own, sc.LEVEL_LEAD, self.CEO_TEAM_STAFF),
                         ({self.CEO_TEAM_LEAD}, {CEO}))

    def test_대표가_올린_팀장_등급은_대표_묶음만(self):
        own = self.rows[CID["maba"]]
        self.assertEqual(sc.approvers(self.org, own, sc.LEVEL_LEAD, CEO), ({CEO},))
        self.assertFalse(sc.can_approve(self.org, own, sc.LEVEL_LEAD, CEO, LEE))

    def test_불변식(self):
        assert_invariants(self, self.org, self.rows)


class SubLeadTest(unittest.TestCase):
    """P1 ⓑ — 팀장이 서브여도 메인일 때와 같게 「담당」으로 빠진다(가장 가까운 팀장 · 자기 승인)."""

    def setUp(self):
        self.org, self.rows = build(payload=_payload_with(
            extra_owners=[_owner(40, KIM, LEE), _owner(41, LEE, KIM)]))

    def test_메인과_서브가_뒤바뀌어도_같다(self):
        for cid in (40, 41):
            own = self.rows[cid]
            self.assertEqual(sc.alert_recipients(self.org, own, sc.URGENT), {KIM, LEE, HAN, CEO}, cid)
            self.assertEqual(sc.digest_recipients(self.org, own), {HAN}, cid)
            self.assertEqual(sc.approvers(self.org, own, sc.LEVEL_LEAD, KIM), ({HAN}, {CEO}), cid)
            self.assertEqual(sc.approvers(self.org, own, sc.LEVEL_LEAD, LEE), ({HAN}, {CEO}), cid)
        self.assertFalse(sc.can_approve(self.org, self.rows[40], sc.LEVEL_LEAD, KIM, LEE))
        self.assertEqual(sc.alert_recipients(self.org, self.rows[40], sc.CAUTION), {KIM})

    def test_불변식(self):
        assert_invariants(self, self.org, self.rows)


class TwoTopManagersTest(unittest.TestCase):
    """재직 대표 표시가 둘이면 요청자 본인은 끝까지 빠진다(다른 대표가 승인)."""

    CEO2 = 2

    def setUp(self):
        self.org, self.rows = build(payload=_payload_with(
            extra_emps=[_emp(self.CEO2, "대표 2", T_CEO, top=True)],
            extra_owners=[_owner(36, self.CEO2), _owner(37, -1, None, self.CEO2)]))

    def test_요청자는_빠진다(self):
        self.assertEqual(sc.owner_state(self.org, self.rows[37]), sc.PREV)
        for cid in (36, 37):
            own = self.rows[cid]
            self.assertEqual(sc.approvers(self.org, own, sc.LEVEL_LEAD, CEO), ({self.CEO2},), cid)
            self.assertFalse(sc.can_approve(self.org, own, sc.LEVEL_LEAD, CEO, CEO), cid)
        self.assertEqual(sc.approvers(self.org, self.rows[36], sc.LEVEL_LEAD, self.CEO2), ({CEO},))
        self.assertEqual(sc.approvers(self.org, self.rows[CEO_CLIENT], sc.LEVEL_LEAD, CEO), ({self.CEO2},))

    def test_무작위(self):
        rnd = random.Random(4)
        people = list(self.org.people) + [None, YOON]
        cids = list(self.rows)
        ceos = self.org.top_managers()
        self.assertEqual(ceos, {CEO, self.CEO2})
        for _ in range(2000):
            own, req = self.rows[rnd.choice(cids)], rnd.choice(people)
            union = frozenset().union(*sc.approvers(self.org, own, sc.LEVEL_LEAD, req))
            if req is not None:
                self.assertNotIn(req, union, (own.client_id, req))

    def test_불변식(self):
        assert_invariants(self, self.org, self.rows)


class TodoChainTest(unittest.TestCase):
    """할 일 줄은 승인자와 따로 — P1 ⓑ 로 서브에게 가지 않는다 · 담당 공백은 팀장 사슬."""

    VACANT_WITH_SUB = 38

    def setUp(self):
        self.org, self.rows = build(payload=_payload_with(extra_owners=[_owner(self.VACANT_WITH_SUB, OH, JEONG)]))

    def test_서브가_있는_광고주(self):
        own = self.rows[CID["tapa"]]
        self.assertEqual(sc.todo_recipients(self.org, own, sc.LEVEL_STAFF), {BAK})
        self.assertEqual(sc.todo_chain(self.org, own, sc.LEVEL_STAFF), ({BAK}, {LEE}, {HAN}, {CEO}))
        self.assertEqual(sc.approvers(self.org, own, sc.LEVEL_STAFF, None), ({BAK, KIM}, {LEE}, {HAN}, {CEO}))

    def test_담당_공백에_서브가_있으면_할_일은_팀장(self):
        own = self.rows[self.VACANT_WITH_SUB]
        self.assertEqual(sc.owner_state(self.org, own), sc.VACANT)
        self.assertEqual(sc.todo_recipients(self.org, own, sc.LEVEL_STAFF), {CHOI})
        self.assertEqual(sc.todo_chain(self.org, own, sc.LEVEL_STAFF), ({CHOI}, {HAN}, {CEO}))
        self.assertEqual(sc.approvers(self.org, own, sc.LEVEL_STAFF, None), ({JEONG}, {CHOI}, {HAN}, {CEO}))
        self.assertEqual(sc.alert_recipients(self.org, own, sc.CAUTION), {CHOI})       # 주의도 팀장 사슬
        self.assertEqual(sc.alert_recipients(self.org, own, sc.URGENT), {CHOI, JEONG, CEO})

    def test_이전_담당과_담당_미정(self):
        self.assertEqual(sc.todo_chain(self.org, self.rows[PREV_CLIENT], sc.LEVEL_STAFF), ({LEE}, {HAN}, {CEO}))
        self.assertEqual(sc.todo_chain(self.org, self.rows[CID["hana"]], sc.LEVEL_STAFF), ({CEO},))
        self.assertEqual(sc.todo_chain(self.org, self.rows[CID["maba"]], sc.LEVEL_LEAD, KIM),
                         sc.approvers(self.org, self.rows[CID["maba"]], sc.LEVEL_LEAD, KIM))

    def test_불변식(self):
        assert_invariants(self, self.org, self.rows)


class RequireClientActionTest(unittest.TestCase):
    """require_client(…, action) 통과 ⇔ action ∈ allowed_actions · 볼 수 없으면 action 과 무관하게 같은 404."""

    def setUp(self):
        self.org, self.rows = build(extended=True)

    def test_이전_담당은_보기_멈추기만(self):
        s = sc.scope_of(self.org, KIM)
        for a in (sc.ACT_VIEW, sc.ACT_STOP):
            self.assertIs(sc.require_client(self.org, s, self.rows, PREV_CLIENT, a), self.rows[PREV_CLIENT])
        for a in (sc.ACT_REVERT, sc.ACT_APPROVE):
            with self.assertRaises(sc.ActionNotAllowed):
                sc.require_client(self.org, s, self.rows, PREV_CLIENT, a)
        with self.assertRaises(ValueError):
            sc.require_client(self.org, s, self.rows, PREV_CLIENT, "delete")
        with self.assertRaises(ValueError):
            sc.require_client(self.org, s, self.rows, PREV_CLIENT, None)  # type: ignore[arg-type]

    def test_무작위(self):
        rnd = random.Random(11)
        people = list(self.org.people) + [YOON, None]
        cids = list(range(-2, 40)) + ["1", 1.0, True]
        actions = sorted(sc.FULL_ACTIONS)
        seen = set()
        for _ in range(4000):
            who, cid, a = rnd.choice(people), rnd.choice(cids), rnd.choice(actions)
            s = sc.scope_of(self.org, who)
            own = self.rows.get(cid) if isinstance(cid, int) and not isinstance(cid, bool) else None
            allowed = sc.allowed_actions(self.org, s, own) if own is not None else frozenset()
            try:
                sc.require_client(self.org, s, self.rows, cid, a)
                got = "ok"
            except sc.ClientNotVisible as e:
                self.assertEqual(str(e), sc.CLIENT_NOT_VISIBLE)
                got = "404"
            except sc.ActionNotAllowed as e:
                self.assertEqual(str(e), sc.ACTION_NOT_ALLOWED)
                got = "action"
            want = "404" if not allowed else ("ok" if a in allowed else "action")
            self.assertEqual(got, want, (who, cid, a))
            seen.add(got)
        self.assertEqual(seen, {"ok", "404", "action"})


class TeamKillSetScopeTest(unittest.TestCase):
    """팀 정지는 주인 팀 기준 — 팀장이 다른 팀 광고주의 서브로만 보이는 곳은 넣지 않는다(P3 ⓐ)."""

    def test_다른_팀_서브는_팀_정지에서_빠진다(self):
        def lee_sub_of_paha(p):
            for row in p["owners"]:
                if row["possibility_id"] == PID_BASE + CID["paha"]:
                    row["sub_manage_emp_idx"] = LEE
        org, rows = build(payload=_payload_with(mutate=lee_sub_of_paha, extended=False))
        lee = sc.scope_of(org, LEE)
        self.assertIn(CID["paha"], sc.clients_in(org, lee, rows))          # 보이기는 한다(서브)
        self.assertEqual(sc.relation(org, lee, rows[CID["paha"]]), sc.REL_SUB)
        ks = sc.kill_set(org, lee, rows)
        self.assertEqual(len(ks.client_ids), 16)
        self.assertNotIn(CID["paha"], ks.client_ids)
        self.assertIn(CID["paha"], sc.kill_set(org, sc.scope_of(org, CHOI), rows).client_ids)
        self.assertEqual(len(sc.kill_set(org, sc.scope_of(org, HAN), rows).client_ids), 29)


class FixtureGapTest(unittest.TestCase):
    """예시 조직에 빠져 있던 셋 — 재직이 아닌 대표 표시 · 같은 팀 팀장 둘 · 서브가 있는 이전 담당 광고주."""

    RESIGNED_TOP, DELETED_TOP, LEE2, PREV_WITH_SUB = 5, 6, 114, 34

    def setUp(self):
        self.org, self.rows = build(payload=_payload_with(
            extra_emps=[_emp(self.RESIGNED_TOP, "옛 대표 계정", T_CEO, top=True, status="RESIGNED"),
                        _emp(self.DELETED_TOP, "삭제된 대표 계정", T_CEO, top=True, deleted=True),
                        _emp(self.LEE2, "이팀장2", T_1, manager=True)],
            extra_owners=[_owner(self.PREV_WITH_SUB, -1, BAK, KIM)]))

    def test_재직이_아닌_대표_표시는_아무것도_아니다(self):
        for who in (self.RESIGNED_TOP, self.DELETED_TOP):
            self.assertEqual(sc.scope_of(self.org, who).kind, sc.NONE, who)
        self.assertEqual(self.org.top_managers(), {CEO})
        for n in ("hana", "gada"):
            own = self.rows[CID[n]]
            self.assertEqual(sc.alert_recipients(self.org, own, sc.URGENT), {CEO})
            self.assertEqual(sc.approvers(self.org, own, sc.LEVEL_LEAD, None), ({CEO},))

    def test_같은_팀_팀장_둘은_둘_다(self):
        s2 = sc.scope_of(self.org, self.LEE2)
        self.assertEqual((s2.kind, s2.teams), (sc.TEAM, {T_1}))
        self.assertEqual(sc.clients_in(self.org, s2, self.rows), sc.clients_in(self.org, sc.scope_of(self.org, LEE), self.rows))
        self.assertEqual(len(sc.clients_in(self.org, s2, self.rows)), 18)
        maba, dara = self.rows[CID["maba"]], self.rows[CID["dara"]]
        self.assertEqual(sc.approvers(self.org, maba, sc.LEVEL_LEAD, KIM), ({LEE, self.LEE2}, {HAN}, {CEO}))
        self.assertLessEqual({LEE, self.LEE2}, sc.alert_recipients(self.org, dara, sc.URGENT))
        self.assertEqual(sc.digest_recipients(self.org, dara), {LEE, self.LEE2})
        # 팀장 본인 광고주의 팀장 등급 — 같은 팀 다른 팀장이 먼저 받는다(① teamManagersOf 방식: 요청자만 빠짐)
        self.assertEqual(sc.approvers(self.org, self.rows[CID["chaka"]], sc.LEVEL_LEAD, LEE), ({self.LEE2}, {HAN}, {CEO}))

    def test_이전_담당_광고주의_서브도_보기_멈추기만(self):
        own = self.rows[self.PREV_WITH_SUB]
        self.assertEqual(sc.owner_state(self.org, own), sc.PREV)
        for who in (KIM, BAK):
            s = sc.scope_of(self.org, who)
            self.assertEqual(sc.relation(self.org, s, own), sc.REL_PREV, who)
            self.assertEqual(sc.allowed_actions(self.org, s, own), {sc.ACT_VIEW, sc.ACT_STOP}, who)
        for level in (sc.LEVEL_STAFF, sc.LEVEL_LEAD):
            union = frozenset().union(*sc.approvers(self.org, own, level, None))
            self.assertFalse(union & {KIM, BAK}, level)
        self.assertEqual(sc.todo_recipients(self.org, own, sc.LEVEL_STAFF), {LEE, self.LEE2})
        self.assertEqual(sc.alert_recipients(self.org, own, sc.URGENT), {KIM, BAK, LEE, self.LEE2, CEO})
        self.assertEqual(sc.alert_recipients(self.org, own, sc.CAUTION), {LEE, self.LEE2})

    def test_불변식(self):
        assert_invariants(self, self.org, self.rows)


def assert_invariants(tc, org, rows):
    """받는 사람 · 승인자 · 할 일 줄 ⊆ 여는 사람 · 받는 사람은 재직자 · 할 일 ⊆ 승인자 · 서브는 할 일 첫 묶음에 없음 · 자기 승인 금지."""
    requesters = list(org.people) + [None, YOON]
    for cid, own in rows.items():
        can = viewers_of(org, own)
        for level in (sc.URGENT, sc.CAUTION):
            got = sc.alert_recipients(org, own, level)
            tc.assertLessEqual(got, can, (cid, level))
            tc.assertTrue(all(org.people[p].active for p in got), (cid, level))
        tc.assertLessEqual(sc.digest_recipients(org, own), can, cid)
        for level in (sc.LEVEL_STAFF, sc.LEVEL_LEAD):
            for req in requesters:
                appr = frozenset().union(*sc.approvers(org, own, level, req))
                todo = sc.todo_chain(org, own, level, req)
                tc.assertLessEqual(appr, can, (cid, level, req))
                tc.assertLessEqual(frozenset().union(*todo), appr, (cid, level, req))
                if level == sc.LEVEL_STAFF and todo and own.sub is not None and own.sub != own.main:
                    tc.assertNotIn(own.sub, todo[0], (cid, req))
        staff = frozenset().union(*sc.approvers(org, own, sc.LEVEL_STAFF, None))
        allowed = frozenset(p for p in org.people
                            if sc.ACT_APPROVE in sc.allowed_actions(org, sc.scope_of(org, p), own))
        tc.assertEqual(staff, allowed, cid)
    assert_no_self_approval(tc, org, rows, requesters)


class SnapshotReviewTest(unittest.TestCase):
    """스냅숏 검사 보강 — 옛 응답 · 미래 시각 · 고아 팀 되풀이 · 권한 확대."""

    def codes(self, d):
        return {f.code for f in d.reasons}

    def test_옛_스냅숏은_버린다(self):
        older_at, newer_at = _next_time(), _next_time()
        newer = mockup_payload(at=newer_at)
        for row in newer["owners"]:
            if row["possibility_id"] == PID_BASE + CID["dara"]:
                row["manage_emp_idx"] = BAK                       # 9시 이후 dara 가 박담당에게 넘어감
        org_new = snap.accept_snapshot(newer, None).org
        d = snap.accept_snapshot(mockup_payload(at=older_at), org_new)   # 늦게 도착한 옛 응답
        self.assertFalse(d.ok)
        self.assertEqual(self.codes(d), {"STALE"})
        self.assertIs(d.org, org_new)
        self.assertEqual(sc.owner_key(d.org, rows_of(d.org)[CID["dara"]]), BAK)
        again = snap.accept_snapshot(copy.deepcopy(newer), org_new)       # 같은 응답 다시 → 같은 시각이라 버림
        self.assertEqual(self.codes(again), {"STALE"})
        self.assertIs(again.org, org_new)

    def test_미래_시각은_버린다(self):
        now = _T0 + timedelta(days=2)
        far = (now + timedelta(hours=1)).isoformat()
        near = (now + timedelta(minutes=5)).isoformat()
        self.assertEqual(self.codes(snap.accept_snapshot(mockup_payload(at=far), None, now=now)), {"FUTURE"})
        self.assertTrue(snap.accept_snapshot(mockup_payload(at=near), None, now=now).ok)
        with self.assertRaises(ValueError):
            snap.accept_snapshot(mockup_payload(), None, now=datetime(2026, 9, 28))

    def test_고아_팀은_받은_뒤_다시_받아도_받는다(self):
        orphan = dict(extra_teams=[_team(50, "새 팀", 2, 49)], extra_emps=[_emp(501, "새 팀장", 50, manager=True)])
        first = snap.accept_snapshot(_payload_with(**orphan, extended=False), None)
        self.assertTrue(first.ok, first.reasons)
        second = snap.accept_snapshot(_payload_with(**orphan, extended=False), first.org)
        self.assertTrue(second.ok, second.reasons)
        self.assertIn("ORPHAN_TEAM", {f.code for f in second.check.warnings})
        # 정상 조직 → 고아 팀 더함(받음) → 같은 스냅숏 다시(받음)
        base = snap.accept_snapshot(mockup_payload(), None).org
        added = snap.accept_snapshot(_payload_with(**orphan, extended=False), base)
        self.assertTrue(added.ok, added.reasons)
        self.assertTrue(snap.accept_snapshot(_payload_with(**orphan, extended=False), added.org).ok)
        # 있던 팀의 부모가 새로 사라지면 여전히 버린다
        p = mockup_payload()
        p["teams"] = [t for t in p["teams"] if t["idx"] != T_HQ]
        self.assertIn("PARENT_LOST", self.codes(snap.accept_snapshot(p, added.org)))

    def test_권한이_넓어지는_스냅숏은_버린다(self):
        base_payload = _payload_with(extra_teams=[_team(950, "시스템 예비", 0, 0, True)],
                                     extra_emps=[_emp(951, "예비 팀장", 950, manager=True)], extended=False)
        prev = snap.accept_snapshot(base_payload, None).org
        self.assertEqual(sc.scope_of(prev, 951).kind, sc.MINE)

        def variant(fn):
            q = copy.deepcopy(base_payload)
            q["generated_at"] = _next_time()
            fn(q)
            return snap.accept_snapshot(q, prev)

        everyone_top = variant(lambda q: [e.__setitem__("is_top_manager", True) for e in q["employees"]])
        self.assertFalse(everyone_top.ok)
        self.assertLessEqual({"TOP_MANAGER_LIMIT", "TOP_MANAGER_ADDED"}, self.codes(everyone_top))
        self.assertIs(everyone_top.org, prev)
        self.assertEqual(sc.scope_of(everyone_top.org, KIM).kind, sc.MINE)

        one_more = variant(lambda q: [e.__setitem__("is_top_manager", True) for e in q["employees"] if e["idx"] == PARK])
        self.assertEqual(self.codes(one_more), {"TOP_MANAGER_ADDED"})

        everyone_mgr = variant(lambda q: [e.__setitem__("is_manager", True) for e in q["employees"]])
        self.assertIn("MANAGER_SPIKE", self.codes(everyone_mgr))

        def unsystem(q):
            for t in q["teams"]:
                if t["idx"] == 950:
                    t["is_system"] = False
        lost = variant(unsystem)
        self.assertEqual(self.codes(lost), {"SYSTEM_TEAM_LOST"})

        def rename_resigned(q):
            for t in q["teams"]:
                if t["idx"] == T_RESIGNED:
                    t["name"], t["is_system"] = "퇴사 보관", False
        self.assertEqual(self.codes(variant(rename_resigned)), {"SYSTEM_TEAM_LOST"})

        promote_one = variant(lambda q: [e.__setitem__("is_manager", True) for e in q["employees"] if e["idx"] == KIM])
        self.assertTrue(promote_one.ok, promote_one.reasons)                  # 한 명 승진은 평소 일

        # 퇴사·삭제된 대표 표시는 세지 않는다
        retired = variant(lambda q: q["employees"].extend([_emp(7, "옛 대표", T_CEO, top=True, status="RESIGNED"),
                                                          _emp(8, "삭제 대표", T_CEO, top=True, deleted=True)]))
        self.assertTrue(retired.ok, retired.reasons)

    def test_처음_받기의_대표_수(self):
        two = _payload_with(extra_emps=[_emp(2, "대표 2", T_CEO, top=True)], extended=False)
        d2 = snap.accept_snapshot(two, None)
        self.assertTrue(d2.ok, d2.reasons)
        self.assertIn("TOP_MANAGER_COUNT", {f.code for f in d2.check.warnings})
        three = _payload_with(extra_emps=[_emp(2, "대표 2", T_CEO, top=True), _emp(3, "대표 3", T_CEO, top=True)],
                              extended=False)
        self.assertEqual(self.codes(snap.accept_snapshot(three, None)), {"TOP_MANAGER_LIMIT"})


# ── 격리 — 순수 · ③ 역할 칸 안 읽음 · main.py 미연결 ──────────────────

NAVER_AUTO = BACKEND / "app" / "naver_auto"
FORBIDDEN_IMPORT_ROOTS = {
    "sqlalchemy", "fastapi", "starlette", "pydantic", "requests", "httpx", "aiohttp", "urllib", "http",
    "socket", "sqlite3", "subprocess", "jose", "passlib",
}
FORBIDDEN_NAMES = {"role", "team_id", "owner_id", "sales_manager"}  # ③ users.role · team_id · clients.owner_id


class IsolationTest(unittest.TestCase):
    def files(self):
        out = sorted(NAVER_AUTO.glob("*.py"))
        self.assertGreaterEqual(len(out), 3)
        return out

    def test_가져오는_것은_표준_라이브러리와_naver_auto_뿐(self):
        for path in self.files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        root = a.name.split(".")[0]
                        self.assertNotIn(root, FORBIDDEN_IMPORT_ROOTS, f"{path.name}: import {a.name}")
                        if root in ("app", "backend"):
                            self.assertTrue(a.name.startswith(("app.naver_auto", "backend.app.naver_auto")),
                                            f"{path.name}: import {a.name}")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    self.assertLessEqual(node.level, 1, f"{path.name}: naver_auto 밖 상대 import ({'.' * node.level}{mod})")
                    if node.level == 0:
                        root = mod.split(".")[0]
                        self.assertNotIn(root, FORBIDDEN_IMPORT_ROOTS, f"{path.name}: from {mod}")
                        if root in ("app", "backend"):
                            self.assertTrue(mod.startswith(("app.naver_auto", "backend.app.naver_auto")),
                                            f"{path.name}: from {mod}")

    def test_광고센터_역할_팀_담당_칸을_읽지_않는다(self):
        for path in self.files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                name = None
                if isinstance(node, ast.Attribute):
                    name = node.attr
                elif isinstance(node, ast.Name):
                    name = node.id
                elif isinstance(node, ast.keyword):
                    name = node.arg
                elif isinstance(node, ast.arg):
                    name = node.arg
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    name = node.value
                self.assertNotIn(name, FORBIDDEN_NAMES, f"{path.name}:{getattr(node, 'lineno', '?')} — {name}")

    def test_웹_프레임워크_없이_불러진다(self):
        code = (
            "import sys; import app.naver_auto.scope, app.naver_auto.org_snapshot;"
            "bad=[m for m in sys.modules if m.split('.')[0] in ('fastapi','sqlalchemy','starlette','pydantic','requests')];"
            "own=sorted(m for m in sys.modules if m=='app' or m.startswith('app.'));"
            "print(repr((bad, own)))"
        )
        out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=True)
        bad, own = ast.literal_eval(out.stdout.strip())
        self.assertEqual(bad, [])
        self.assertEqual(own, ["app", "app.naver_auto", "app.naver_auto.org_snapshot", "app.naver_auto.scope"])

    def test_1차는_서비스에_연결하지_않는다(self):
        # 3차에서 /naver/ API 를 연결할 때 이 시험을 「연결 지점이 한 곳인지」로 바꾼다.
        for path in (BACKEND / "app").rglob("*.py"):
            if NAVER_AUTO in path.parents:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("naver_auto", text, path.relative_to(BACKEND))
            self.assertNotIn("org_snapshot", text, path.relative_to(BACKEND))


# ── 대표 계정 = 0번 (운영 읽기 전용 실측 2026-09-28) ─────────────────────
# ① 전산: 대표는 employee.idx 0(대표 표시 · 팀장 표시 · 팀 0 · ACTIVE). 시스템 계정 -1 에도 대표 표시가 켜져 있다.
# 0 을 「없음」으로 읽으면 대표가 사라지고, -1 을 받으면 「대표가 둘」이 된다.

class CeoAccountZeroTest(unittest.TestCase):

    def setUp(self):
        self.org, self.rows = build(extended=True)

    def test_0번은_사람이고_음수는_아니다(self):
        self.assertTrue(snap.is_person_idx(0))
        self.assertTrue(snap.is_person_idx(KIM))
        for bad in (-1, -2, None, True, False, 0.0, "0", 1.5):
            self.assertFalse(snap.is_person_idx(bad), bad)

    def test_대표_0번은_전사를_본다_담당_미정까지(self):
        s = sc.scope_of(self.org, 0)
        self.assertEqual(s.kind, sc.ALL)
        self.assertEqual(sc.clients_in(self.org, s, self.rows, "all"), frozenset(self.rows))
        self.assertIn(CID["hana"], sc.clients_in(self.org, s, self.rows, "all"))   # 담당 빈칸
        self.assertIn(CID["gada"], sc.clients_in(self.org, s, self.rows, "all"))   # 모르는 번호
        self.assertEqual(sc.kill_set(self.org, s, self.rows).kind, "GLOBAL")

    def test_팀_0_의_팀장_표시는_대표를_팀장으로_만들지_않는다(self):
        # 대표는 팀 0(미분류 · 시스템)에 팀장 표시로 앉아 있다 — 같은 팀 0 의 다른 팀장이 대표 광고주를 보면 안 된다.
        other = sc.scope_of(self.org, SYS_MGR_UNSORTED)
        self.assertEqual(other.kind, sc.MINE)
        self.assertNotIn(CEO_CLIENT, sc.clients_in(self.org, other, self.rows, "all"))

    def test_대표가_메인_담당이면_정상이고_0_이_받는_사람으로_나간다(self):
        own = self.rows[CEO_CLIENT]
        self.assertEqual(own.main, 0)
        self.assertEqual(sc.owner_state(self.org, own), sc.NORMAL)
        self.assertEqual(sc.alert_recipients(self.org, own, sc.URGENT), {0})
        self.assertEqual(sc.alert_recipients(self.org, own, sc.CAUTION), {0})
        self.assertEqual(sc.todo_chain(self.org, own, sc.LEVEL_STAFF), ({0},))
        self.assertTrue(sc.can_approve(self.org, own, sc.LEVEL_STAFF, None, 0))

    def test_대표는_모든_승인_사슬의_끝에_있다(self):
        for cid in (CID["maba"], CID["chaka"], CID["taga"], CID["hana"], PREV_CLIENT):
            own = self.rows[cid]
            for lv in (sc.LEVEL_STAFF, sc.LEVEL_LEAD):
                chain = sc.approvers(self.org, own, lv, KIM if cid == CID["maba"] else None)
                self.assertIn(0, chain[-1], (cid, lv))
                self.assertTrue(sc.can_approve(self.org, own, lv, KIM if cid == CID["maba"] else None, 0), (cid, lv))

    def test_직전_담당이_대표_0번이면_이전_담당(self):
        p = _payload_with(extra_owners=[_owner(40, -1, None, 0)])
        org, rows = build(payload=p)
        own = rows[40]
        self.assertEqual((own.main, own.prev, own.source), (None, 0, "prev"))
        self.assertEqual(sc.owner_state(org, own), sc.PREV)
        self.assertEqual(sc.owner_key(org, own), 0)

    def test_대표가_담당인_줄은_빈칸으로_세지_않는다(self):
        base = mockup_payload()
        base["owners"] = [_owner(1, 0), _owner(2, KIM)]
        org, _ = build(payload=base)
        self.assertEqual(org.blank_owner_ratio(), 0.0)

    def test_음수_직원은_대표_표시가_있어도_스냅숏째_버린다(self):
        p = mockup_payload()
        p["employees"].append(_emp(-1, "시스템", T_UNSORTED, top=True))   # 운영의 -1 은 대표 표시 · ACTIVE
        with self.assertRaises(snap.SnapshotFormatError):
            snap.parse_org_snapshot(p)
        self.assertFalse(snap.accept_snapshot(p, None).ok)

    def test_재직_대표가_없으면_버린다(self):
        # ① 가 0번을 빠뜨리는 회귀(「idx > 0」 관례를 옮겨 쓰는 실수) — 받으면 담당 미정 광고주를 아무도 못 본다.
        p = mockup_payload()
        p["employees"] = [e for e in p["employees"] if e["idx"] != CEO]
        d = snap.accept_snapshot(p, None)
        self.assertFalse(d.ok)
        self.assertIn("TOP_MANAGER_NONE", {f.code for f in d.check.reasons})
        # 대표가 퇴사 표시여도 재직 대표 0명 — 같은 이유로 버린다.
        q = mockup_payload()
        for e in q["employees"]:
            if e["idx"] == CEO:
                e["status"] = "RESIGNED"
        self.assertIn("TOP_MANAGER_NONE", {f.code for f in snap.accept_snapshot(q, None).check.reasons})

    def test_번호를_참거짓으로_읽는_코드가_없다(self):
        # 0 = 대표. 「if not idx」 · 「idx or 기본값」 · 「if idx:」 는 대표를 지운다 — 사람 번호를 참거짓으로 읽지 않는다.
        # 글자가 아니라 구문 나무로 본다(설명문·주석의 경고 문장은 걸리지 않게).
        person_name = re.compile(r"(idx|main|sub|prev|viewer|requester|approver)", re.I)

        def name_of(node):
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                return node.attr
            return None

        def risky(node):
            n = name_of(node)
            return n is not None and person_name.search(n) is not None

        for path in sorted(NAVER_AUTO.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                where = f"{path.name}:{getattr(node, 'lineno', '?')}"
                if isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert)):
                    t = node.test
                    if isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not):
                        t = t.operand
                    self.assertFalse(risky(t), where)
                if isinstance(node, ast.BoolOp):
                    for v in node.values:
                        inner = v.operand if isinstance(v, ast.UnaryOp) and isinstance(v.op, ast.Not) else v
                        self.assertFalse(risky(inner), where)
                if isinstance(node, ast.comprehension):
                    for cond in node.ifs:
                        inner = cond.operand if isinstance(cond, ast.UnaryOp) and isinstance(cond.op, ast.Not) else cond
                        self.assertFalse(risky(inner), where)


class ScreenAdditionsTest(unittest.TestCase):
    """S11 가산 — 로그인 때 좁히기(v1.4 §9) · 이슈 손길 층 · 이슈 처리·짝 확인 권한(이전 담당은 못 함)."""

    def setUp(self):
        self.org, self.rows = build(extended=True)

    def test_좁힌_범위는_늘_본인_담당의_부분집합(self):
        for who in list(self.org.people) + [YOON]:
            wide = sc.clients_in(self.org, sc.scope_of(self.org, who), self.rows)
            n = sc.narrowed_scope_of(self.org, who)
            got = sc.clients_in(self.org, n, self.rows)
            self.assertLessEqual(got, wide, who)
            if sc.scope_of(self.org, who).kind in (sc.TEAM, sc.MINE):
                self.assertEqual(n.kind, sc.MINE)
                self.assertTrue(n.narrowed)
                # 좁힌 범위 = 좁히기 전 범위의 「내 담당」(메인·서브·직전) — 좁힌 범위도 판정 함수가 믿어야 한다
                self.assertEqual(got, sc.clients_in(self.org, sc.scope_of(self.org, who), self.rows, "me"), who)
        lead_own = [w for w in self.org.people if sc.scope_of(self.org, w).kind == sc.TEAM
                    and sc.clients_in(self.org, sc.scope_of(self.org, w), self.rows, "me")]
        self.assertTrue(lead_own)                                   # 자기 담당이 있는 팀장이 예시에 있다
        for w in lead_own:
            self.assertTrue(sc.clients_in(self.org, sc.narrowed_scope_of(self.org, w), self.rows), w)

    def test_좁힘_표시를_떼거나_붙인_손_범위는_범위_없음(self):
        for who in self.org.people:
            s = sc.scope_of(self.org, who)
            if s.kind != sc.TEAM:
                continue
            forged = sc.Scope(s.kind, s.viewer_idx, s.teams, s.people, s.generated_at, True)
            self.assertEqual(sc.clients_in(self.org, forged, self.rows), frozenset())
            n = sc.narrowed_scope_of(self.org, who)
            unmarked = sc.Scope(n.kind, n.viewer_idx, n.teams, n.people, n.generated_at, False)
            self.assertEqual(sc.clients_in(self.org, unmarked, self.rows), frozenset())
            weird = sc.Scope(n.kind, n.viewer_idx, n.teams, n.people, n.generated_at, 1)
            self.assertEqual(sc.clients_in(self.org, weird, self.rows), frozenset())

    def test_이슈_손길_층(self):
        from app.naver_auto import issues as iss
        seen = set()
        for who in self.org.people:
            s = sc.scope_of(self.org, who)
            for cid, own in self.rows.items():
                a = sc.issue_actor(self.org, s, own)
                seen.add(a)
                if not sc.can_see(self.org, s, own):
                    self.assertIsNone(a, (who, cid))
                elif sc.relation(self.org, s, own) == sc.REL_PREV:
                    self.assertIsNone(a, (who, cid))    # 이전 담당은 보기·멈추기만
                else:
                    self.assertEqual(a, iss.ACTOR_LEAD if sc.can_approve(self.org, own, sc.LEVEL_LEAD, None, who)
                                     else iss.ACTOR_OWNER, (who, cid))
        self.assertEqual(seen, {None, iss.ACTOR_OWNER, iss.ACTOR_LEAD})
        self.assertEqual(sc.issue_actor(self.org, sc.scope_of(self.org, KIM), self.rows[CID["dara"]]), iss.ACTOR_OWNER)
        self.assertEqual(sc.issue_actor(self.org, sc.scope_of(self.org, CEO), self.rows[CID["dara"]]), iss.ACTOR_LEAD)

    def test_새_동작은_이전_담당에게_없다(self):
        self.assertTrue({sc.ACT_HANDLE_ISSUE, sc.ACT_CONFIRM_LINK} <= sc.FULL_ACTIONS)
        self.assertFalse({sc.ACT_HANDLE_ISSUE, sc.ACT_CONFIRM_LINK} & sc.PREV_ACTIONS)
        s = sc.scope_of(self.org, KIM)
        for a in (sc.ACT_HANDLE_ISSUE, sc.ACT_CONFIRM_LINK):
            with self.assertRaises(sc.ActionNotAllowed):
                sc.require_client(self.org, s, self.rows, PREV_CLIENT, a)

    def test_my_profile_좁히기_판단(self):
        leads = [w for w in self.org.people if sc.scope_of(self.org, w).kind == sc.TEAM]
        self.assertTrue(leads)
        for w in leads:
            team = self.org.people[w].team_idx
            self.assertFalse(sc.profile_narrows(self.org, w, True, team))
            self.assertTrue(sc.profile_narrows(self.org, w, False, team))
            self.assertTrue(sc.profile_narrows(self.org, w, True, None))
            self.assertTrue(sc.profile_narrows(self.org, w, None, team))
            self.assertTrue(sc.profile_narrows(self.org, w, 1, team))
        self.assertFalse(sc.profile_narrows(self.org, CEO, False, None))   # 대표는 my-profile 로 좁히지 않는다
        self.assertFalse(sc.profile_narrows(self.org, KIM, False, None))   # 담당은 좁힐 것이 없다

if __name__ == "__main__":
    unittest.main()
