"""네이버 관제 짝 규칙(matching.py) 시험 — ① 이름 정리 정답표 · 번호 두 공간 · 자동 짝 · 이름 후보.

돌리는 법(backend 폴더에서 · 서버와 같은 판):  python3.12 -m unittest -v tests.test_naver_auto_matching
번호·이름은 모두 지어낸 값이다.
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.naver_auto import matching as M  # noqa: E402
from app.naver_auto import verdict as V  # noqa: E402

VECTORS = BACKEND / "tests" / "fixtures" / "prospect_match_keys_vectors.json"


def acc(cid, no=None, name="가게"):
    return cid, {"customerId": cid, "adAccountNo": no if no is not None else cid + 5000000, "adAccountName": name}


def accounts(*rows):
    return dict(acc(*r) if isinstance(r, tuple) else acc(r) for r in rows)


def run(prospects, creds=(), accs=None, decisions=()):
    return M.match(prospects, creds, accs if accs is not None else {}, decisions, accounts_complete=True)


def P(pid, name):
    return M.ErpProspect(pid, name)


def C(pid, raw, vendor=M.VENDOR_NAVER):
    return M.ErpCredential(pid, vendor, raw)


def reasons(res):
    return sorted((b.possibility_id, b.reason) for b in res.blocked)


class VectorParityTest(unittest.TestCase):
    """① 자바 코드를 그대로 돌린 정답표와 한 글자까지 같다."""

    def test_vectors_match_java(self):
        doc = json.loads(VECTORS.read_text(encoding="utf-8"))
        self.assertIn("ProspectMatchKeys.java", doc["_출처"]["파일"])
        vec = doc["vectors"]
        self.assertGreaterEqual(len(vec), 60)
        for v in vec:
            with self.subTest(v=repr(v["in"])):
                self.assertEqual(M.normalize_name(v["in"]), v["name"])
                self.assertEqual(M.loose_name(v["in"]), v["loose"])

    def test_vectors_cover_the_traps(self):
        ins = {v["in"] for v in json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"]}
        for trap in (None, "", "𠀀", "Ⅻ", "㈜메타", "（주）메타", "ΟΔΟΣ", "İstanbul", "ｱｲｳ", "메\u200b타"):
            self.assertIn(trap, ins)

    def test_utf16_length_like_java(self):
        self.assertEqual(M.normalize_name("𠀀"), "𠀀")    # 자바 길이 2 → 남는다
        self.assertIsNone(M.normalize_name("Ⅻ"))          # 자바 길이 1 → 사라진다
        self.assertEqual(M.loose_name("Ⅻ"), "xii")


    def test_known_difference_final_sigma(self):
        # ① 자바는 숫자 뒤 끝의 Σ 를 ς 로, 파이썬은 σ 로 바꾼다(끝 글자 판정 방식 차이 · 2026-09-28 자바 21 로 확인).
        # 짝 규칙은 양쪽을 같은 파이썬 함수로 정리하므로 영향이 없다. 이 차이가 바뀌면(파이썬이 자바를 따르면) 알 수 있게 고정한다.
        self.assertEqual(M.loose_name("Α1Σ"), "α1σ")
        self.assertEqual(M.loose_name("ΟΔΟΣ"), "οδος")   # 글자 바로 뒤 끝이면 둘 다 ς

    def test_server_python_version(self):
        # 정답표는 자바 21(유니코드 15)로 만들었다 — 서버와 같은 파이썬 3.12(유니코드 15)에서 돌려야 뜻이 있다
        import unicodedata
        if sys.version_info[:2] != (3, 12):
            self.skipTest("서버와 같은 python3.12 로 돌린다: python3.12 -m unittest tests.test_naver_auto_matching")
        self.assertEqual(unicodedata.unidata_version, "15.0.0")


class ParseCustomerIdTest(unittest.TestCase):
    def test_accepts(self):
        for raw in ("1234567", " 1234567 ", "123-4567", "123 4567", "\t1234567\n", "123\u20134567", "1234",
                    1234567, "12345678", "123\u30004567", "123\u00a04567", "123－4567"):
            with self.subTest(raw=raw):
                cid, why = M.parse_customer_id(raw)
                self.assertIsNone(why)
                self.assertIsInstance(cid, int)
        self.assertEqual(M.parse_customer_id("123-4567"), (1234567, None))

    def test_rejects(self):
        cases = [
            ("１２３４５６７", M.B_FORMAT), ("①②③④", M.B_FORMAT), ("1234567a", M.B_FORMAT), ("12.34567", M.B_FORMAT),
            ("٣٤٥٦٧٨٩", M.B_FORMAT), ("-", M.B_FORMAT), ("123\n4567", M.B_FORMAT), ("ID:1234567", M.B_FORMAT),
            ("0123456", M.B_LENGTH), ("123", M.B_LENGTH), ("123456789", M.B_LENGTH), ("123-45-67890", M.B_LENGTH),
            ("010-1234-5678", M.B_LENGTH), (True, M.B_FORMAT), (12.5, M.B_FORMAT), (["1234567"], M.B_FORMAT),
        ]
        for raw, why in cases:
            with self.subTest(raw=raw):
                self.assertEqual(M.parse_customer_id(raw), (None, why))

    def test_blank_is_not_a_claim(self):
        for raw in (None, "", "   ", "\u3000"):
            self.assertEqual(M.parse_customer_id(raw), (None, None))


class AutoPairTest(unittest.TestCase):
    def test_happy_path(self):
        r = run([P(11, "(주)메타상회")], [C(11, "1234567")], accounts((1234567, 7654321, "메타상회")))
        self.assertEqual(len(r.pairs), 1)
        p = r.pairs[0]
        self.assertEqual((p.possibility_id, p.customer_id, p.link, p.name_relation), (11, 1234567, V.LINK_AUTO, M.REL_SAME))
        self.assertEqual(r.checkable(), {11: ((1234567, V.LINK_AUTO),)})
        self.assertEqual(r.blocked, ())
        self.assertEqual(r.candidates, ())

    def test_ignored_rows(self):
        r = run([P(11, "메타")], [C(11, "1234567", vendor="KAKAO_MOMENT"), C(11, "1234567", vendor=None),
                                  C(11, "1234567", vendor="naver_searchad"), C(99, "1234567"), C(11, "  ")],
                accounts((1234567, 7654321, "메타")))
        self.assertEqual(r.pairs, ())
        self.assertEqual(r.ignored_rows, 5)

    def test_format_and_length_blocked(self):
        r = run([P(11, "메타"), P(12, "상회")], [C(11, "12345a"), C(12, "0123456")])
        self.assertEqual(reasons(r), [(11, M.B_FORMAT), (12, M.B_LENGTH)])

    def test_not_linked(self):
        r = run([P(11, "메타")], [C(11, "1234567")], accounts((2222222, 3333333, "메타")))
        self.assertEqual(reasons(r), [(11, M.B_NOT_LINKED)])
        self.assertEqual(r.pairs, ())

    def test_ad_account_number_space(self):
        # ① 에 광고계정 번호를 적었다 — 자릿수로는 못 가른다(둘 다 7자리) · 공간으로만 가른다
        r = run([P(11, "메타")], [C(11, "7654321")], accounts((1234567, 7654321, "메타")))
        self.assertEqual(reasons(r), [(11, M.B_AD_ACCOUNT_NO)])
        self.assertEqual(r.pairs, ())

    def test_ambiguous_space(self):
        # 1234567 이 A 의 고객 번호이면서 B 의 광고계정 번호
        r = run([P(11, "메타")], [C(11, "1234567")], accounts((1234567, 7000001, "메타"), (2345678, 1234567, "다른곳")))
        self.assertEqual(reasons(r), [(11, M.B_AMBIGUOUS_SPACE)])

    def test_same_account_both_numbers_ok(self):
        r = run([P(11, "메타")], [C(11, "1234567")], accounts((1234567, 1234567, "메타")))
        self.assertEqual(len(r.pairs), 1)

    def test_claimed_by_several(self):
        r = run([P(11, "메타 스토어"), P(12, "메타 플레이스")], [C(11, "1234567"), C(12, "1234567")],
                accounts((1234567, 7654321, "메타")))
        self.assertEqual(reasons(r), [(11, M.B_CLAIMED_BY_SEVERAL), (12, M.B_CLAIMED_BY_SEVERAL)])
        self.assertEqual(r.pairs, ())

    def test_duplicate_claim_same_prospect_once(self):
        r = run([P(11, "메타")], [C(11, "1234567"), C(11, "123-4567")], accounts((1234567, 7654321, "메타")))
        self.assertEqual(len(r.pairs), 1)
        self.assertEqual(r.blocked, ())
        # 막힌 경우도 한 번만 올린다(같은 번호를 두 번 적어도 짝 확인 화면에 한 줄)
        r = run([P(11, "메타")], [C(11, "1234567"), C(11, "123 4567")], accounts((2222222, 3333333, "메타")))
        self.assertEqual(reasons(r), [(11, M.B_NOT_LINKED)])

    def test_two_accounts_for_one_prospect(self):
        r = run([P(11, "메타")], [C(11, "1234567"), C(11, "2345678")],
                accounts((1234567, 7654321, "메타"), (2345678, 8765432, "메타 2호점")))
        self.assertEqual(sorted(p.customer_id for p in r.pairs), [1234567, 2345678])

    def test_name_rules(self):
        cases = [
            ("메타상회", "메타상회", M.REL_SAME, None),
            ("메타", "메타상회_네이버", M.REL_CONTAINS, None),
            ("메타상회", "x", M.REL_UNKNOWN, None),
            ("메타상회", "홍길동", M.REL_DIFFERENT, M.B_NAME_DIFFERENT),
        ]
        for pname, aname, rel, block in cases:
            with self.subTest(pname=pname, aname=aname):
                r = run([P(11, pname)], [C(11, "1234567")], accounts((1234567, 7654321, aname)))
                if block:
                    self.assertEqual(reasons(r), [(11, block)])
                else:
                    self.assertEqual([(p.link, p.name_relation) for p in r.pairs], [(V.LINK_AUTO, rel)])

    def test_name_points_elsewhere(self):
        # 계정 이름이 이 가망(「메타」)을 품기는 하지만, 딱 같은 상호의 다른 가망이 있다
        r = run([P(11, "메타"), P(12, "메타상회")], [C(11, "1234567")], accounts((1234567, 7654321, "메타상회")))
        self.assertEqual(reasons(r), [(11, M.B_NAME_ELSEWHERE)])
        # 이름이 이 가망과 딱 같으면 다른 가망이 같은 이름이어도 통과(스토어·플레이스 두 가망)
        r = run([P(11, "메타상회"), P(12, "메타상회")], [C(11, "1234567")], accounts((1234567, 7654321, "메타상회")))
        self.assertEqual([p.possibility_id for p in r.pairs], [11])


    def test_out_of_scope_claim_counts_as_conflict(self):
        # 관리 대상 밖 가망(끝난 계약 등)이 ① 에 같은 번호를 적었으면, 활성 가망도 자동 짝이 되지 않는다(규칙 4)
        r = run([P(11, "메타")], [C(11, "1234567"), C(99, "1234567")], accounts((1234567, 7654321, "메타상회")))
        self.assertEqual(reasons(r), [(11, M.B_CLAIMED_BY_SEVERAL)])
        self.assertEqual(r.pairs, ())
        self.assertEqual(r.ignored_rows, 1, "관리 대상 밖 행은 짝을 안 만들지만 충돌 판정에는 센다")
        # 관리 대상 밖 가망의 번호가 형식이 틀려도 막힘 줄은 올리지 않는다(그 가망은 화면에 없다)
        r = run([P(11, "메타")], [C(11, "1234567"), C(99, "12a")], accounts((1234567, 7654321, "메타상회")))
        self.assertEqual(len(r.pairs), 1)
        self.assertEqual(r.blocked, ())

    def test_same_account_via_two_number_spaces_is_conflict(self):
        # 11 은 광고계정 번호로 · 12 는 고객 번호로 같은 계정을 가리킨다 — 한 계정을 두고 다투는 것
        r = run([P(11, "메타상회"), P(12, "메타")], [C(11, "7654321"), C(12, "1234567")],
                accounts((1234567, 7654321, "메타상회 강남")))
        self.assertEqual(reasons(r), [(11, M.B_AD_ACCOUNT_NO), (12, M.B_CLAIMED_BY_SEVERAL)])
        self.assertEqual(r.pairs, ())

    def test_unknown_name_pointing_elsewhere_blocked(self):
        # 이름이 없거나 한 글자라 관계를 모르는데, 계정 이름이 다른 가망의 상호와 같다 — 누구 계정인지 모르면 들어가지 않는다
        for pname in (None, "메"):
            with self.subTest(pname=pname):
                r = run([P(11, pname), P(12, "메타상회")], [C(11, "1234567")], accounts((1234567, 7654321, "메타상회")))
                self.assertEqual(reasons(r), [(11, M.B_NAME_ELSEWHERE)])

class HumanDecisionTest(unittest.TestCase):
    def test_confirmed_wins_and_missing(self):
        d = [M.HumanDecision(11, 1234567), M.HumanDecision(11, 2345678)]
        r = run([P(11, "메타")], [], accounts((1234567, 7654321, "전혀다른이름")), d)
        self.assertEqual([(p.customer_id, p.link) for p in r.pairs], [(1234567, V.LINK_CONFIRMED)])
        self.assertEqual(r.confirmed_missing, ((11, 2345678),))

    def test_confirmed_out_of_scope_prospect_not_read(self):
        # 관리 대상 밖 가망(끝난 지 14일 넘음 등)은 확인한 짝이 있어도 점검하지 않는다
        r = run([P(11, "메타")], [], accounts((1234567, 7654321, "메타")), [M.HumanDecision(99, 1234567)])
        self.assertEqual(r.pairs, ())
        self.assertEqual(r.confirmed_missing, ())

    def test_confirmed_and_claimed_same(self):
        r = run([P(11, "메타")], [C(11, "1234567")], accounts((1234567, 7654321, "홍길동")),
                [M.HumanDecision(11, 1234567)])
        self.assertEqual([(p.customer_id, p.link) for p in r.pairs], [(1234567, V.LINK_CONFIRMED)])
        self.assertEqual(r.blocked, ())

    def test_confirmed_elsewhere(self):
        r = run([P(11, "메타"), P(12, "메타")], [C(11, "1234567")], accounts((1234567, 7654321, "메타")),
                [M.HumanDecision(12, 1234567)])
        self.assertEqual(reasons(r), [(11, M.B_CONFIRMED_ELSEWHERE)])
        self.assertEqual([(p.possibility_id, p.link) for p in r.pairs], [(12, V.LINK_CONFIRMED)])

    def test_rejected(self):
        r = run([P(11, "메타")], [C(11, "1234567")], accounts((1234567, 7654321, "메타")),
                [M.HumanDecision(11, 1234567, M.DECISION_REJECTED)])
        self.assertEqual(reasons(r), [(11, M.B_REJECTED)])
        self.assertEqual(r.candidates, (), "아니라고 한 계정은 이름 후보로도 다시 올리지 않는다")

    def test_bad_decisions(self):
        with self.assertRaises(M.BadInput):
            run([P(11, "메타")], [], {}, [M.HumanDecision(11, 1234567), M.HumanDecision(11, 1234567, M.DECISION_REJECTED)])
        with self.assertRaises(M.BadInput):
            run([P(11, "메타")], [], {}, [M.HumanDecision(11, 1234567, "maybe")])


class CandidateTest(unittest.TestCase):
    def test_same_then_contains_and_cap(self):
        accs = accounts((1000001, 2000001, "메타상회"), (1000002, 2000002, "메타상회 2호점"), (1000003, 2000003, "(주)메타상회"),
                        (1000004, 2000004, "메타상회본점"), (1000005, 2000005, "메타상회A"), (1000006, 2000006, "메타상회B"),
                        (1000007, 2000007, "전혀다름"))
        r = run([P(11, "메타상회")], [], accs)
        self.assertEqual(M.CANDIDATE_MAX, 5)
        self.assertEqual(len(r.candidates), 5, "6개 중 5개만")
        self.assertEqual([c.relation for c in r.candidates[:2]], [M.REL_SAME, M.REL_SAME])
        self.assertEqual({c.customer_id for c in r.candidates[:2]}, {1000001, 1000003})
        self.assertEqual(r.candidates[0].same_name_accounts, 2, "같은 정리 이름 계정이 둘 — 여럿 중 하나 표시")
        self.assertNotIn(1000007, [c.customer_id for c in r.candidates])
        self.assertEqual(r.pairs, (), "이름 후보는 절대 자동 짝이 아니다")
        self.assertEqual(r.checkable(), {})

    def test_short_contains_not_candidate(self):
        r = run([P(11, "메타")], [], accounts((1000001, 2000001, "메타상회")))
        self.assertEqual(r.candidates, (), "두 글자 품음은 이름 후보로 올리지 않는다(번호 근거 없음)")
        r = run([P(11, "메타상")], [], accounts((1000001, 2000001, "메타상회")))
        self.assertEqual([c.relation for c in r.candidates], [M.REL_CONTAINS])

    def test_paired_excluded(self):
        accs = accounts((1234567, 7654321, "메타상회"), (2345678, 8765432, "메타상회"))
        r = run([P(11, "메타상회"), P(12, "메타상회")], [C(11, "1234567")], accs)
        self.assertEqual([p.possibility_id for p in r.pairs], [11])
        self.assertEqual([(c.possibility_id, c.customer_id) for c in r.candidates], [(12, 2345678)],
                         "짝이 된 계정은 후보에서 빼고 · 짝이 있는 가망은 후보를 찾지 않는다")

    def test_blocked_prospect_still_gets_candidates(self):
        accs = accounts((1234567, 7654321, "홍길동"), (2345678, 8765432, "메타상회"))
        r = run([P(11, "메타상회")], [C(11, "1234567")], accs)
        self.assertEqual(reasons(r), [(11, M.B_NAME_DIFFERENT)])
        self.assertEqual([c.customer_id for c in r.candidates], [2345678])

    def test_candidate_flags_accounts_owned_elsewhere(self):
        accs = accounts((1234567, 7654321, "메타상회"), (2345678, 8765432, "메타상회"))
        r = run([P(11, "메타상회")], [C(98, "2345678")], accs, [M.HumanDecision(99, 1234567)])
        flags = {c.customer_id: c.claimed_elsewhere for c in r.candidates}
        self.assertEqual(flags, {1234567: True, 2345678: True},
                         "관리 대상 밖 가망이 확인했거나 ① 에 적은 계정은 「다른 가망 것」 표시와 함께 보인다")
        r = run([P(11, "메타상회")], [], accs)
        self.assertEqual({c.claimed_elsewhere for c in r.candidates}, {False})

    def test_prospect_without_name(self):
        r = run([P(11, None), P(12, "메")], [], accounts((1000001, 2000001, "메타상회")))
        self.assertEqual(r.candidates, ())


class GuardTest(unittest.TestCase):
    def test_incomplete_accounts_refused(self):
        with self.assertRaises(M.IncompleteAccounts):
            M.match([P(11, "메타")], [], {}, (), accounts_complete=False)
        with self.assertRaises(M.IncompleteAccounts):
            M.match([P(11, "메타")], [], {}, (), accounts_complete=1)
        with self.assertRaises(TypeError):
            M.match([P(11, "메타")], [], {}, ())   # 표시를 빼먹으면 부를 수 없다

    def test_bad_inputs(self):
        bad = [
            lambda: run([P(11, "a"), P(11, "b")]),
            lambda: run([P(True, "a")]),
            lambda: run([P(0, "a")]),
            lambda: run([P(11, "a")], accs={1234567: {"customerId": 7654321, "adAccountNo": 1, "adAccountName": "a"}}),
            lambda: run([P(11, "a")], accs={1234567: {"adAccountNo": 5, "adAccountName": "a"},
                                           2345678: {"adAccountNo": 5, "adAccountName": "b"}}),
            lambda: run([P(11, "a")], accs={True: {"adAccountNo": 5, "adAccountName": "a"}}),
            lambda: run([P(11, "a")], accs={1234567: {"adAccountNo": "5", "adAccountName": "a"}}),
            lambda: run([P(11, "a")], accs={1234567: {"adAccountNo": None, "adAccountName": "a"}}),
            lambda: run([P(11, "a")], accs={1234567: {"adAccountName": "a"}}),
            lambda: run([P(11, "a")], accs={1234567: {"adAccountNo": 5}}),
            lambda: run([P(11, "a")], accs={1234567: {"adAccountNo": 5, "adAccountName": 12345}}),
            lambda: run([P(11, "a")], accs={1234567: {"adAccountNo": 5, "adAccountName": b"a"}}),
            lambda: run([P(11, b"a")]),
            lambda: run([P(11, 5)]),
            lambda: run([P(11, "a")], accs={1234567: "x"}),
            lambda: run([{"possibility_id": 11}]),
            lambda: run([P(11, "a")], [("11", "1234567")]),
        ]
        for i, f in enumerate(bad):
            with self.subTest(i=i):
                with self.assertRaises(M.BadInput):
                    f()

    def test_repr_hides_numbers_and_names(self):
        r = run([P(11, "비밀상호")], [C(11, "1234567"), C(11, "9999999")],
                accounts((1234567, 7654321, "비밀상호"), (8888888, 6666666, "비밀상호점")),
                [M.HumanDecision(11, 8888888, M.DECISION_REJECTED)])
        self.assertRegex(repr(r), r"^PairingResult\(pairs=\d+, blocked=\d+, candidates=\d+, "
                                  r"confirmed_missing=\d+, ignored=\d+\)$", "결과 표시는 개수만")
        texts = [repr(r)] + [repr(x) for x in r.pairs + r.blocked + r.candidates]
        texts += [repr(P(11, "비밀상호")), repr(C(11, "1234567")), repr(M.HumanDecision(11, 1234567))]
        for t in texts:
            for secret in ("1234567", "7654321", "9999999", "8888888", "비밀"):
                self.assertNotIn(secret, t)

    def test_link_constants_same_as_engine(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from naver_engine import handles as H
        self.assertEqual((V.LINK_CONFIRMED, V.LINK_AUTO), (H.LINK_CONFIRMED, H.LINK_AUTO))

    def test_pure_module(self):
        src = (BACKEND / "app" / "naver_auto" / "matching.py").read_text(encoding="utf-8")
        for bad in ("import requests", "urllib", "sqlite", "sqlalchemy", "datetime.now", "time.time", "open(",
                    "from app", "import app", "naver_engine", "print("):
            self.assertNotIn(bad, src, bad)

    def test_scale(self):
        # 실측 규모(계정 1,784 · 관리 대상 약 940)에서 한 번에 끝난다
        import time
        accs = {1000000 + i: {"customerId": 1000000 + i, "adAccountNo": 3000000 + i, "adAccountName": f"가게{i}호"}
                for i in range(1784)}
        pros = [P(10 + i, f"가게{i}호") for i in range(940)]
        creds = [C(10 + i, str(1000000 + i)) for i in range(0, 940, 3)]
        t = time.perf_counter()
        r = run(pros, creds, accs)
        self.assertLess(time.perf_counter() - t, 20)
        self.assertEqual(len([p for p in r.pairs if p.link == V.LINK_AUTO]), len(creds))


if __name__ == "__main__":
    unittest.main()
