"""요청 안의 이름 후보 색인 재사용: 기존 순수 결과·전체 건수·공개 권한 응답 보존."""
import copy
from dataclasses import asdict
import random
import unittest
from unittest.mock import patch

from app.naver_auto import matching as M
from naver_engine import inventory as I
from naver_engine.tests import test_accounts_match_reuse as AR, test_catalog_links as CL
from naver_engine.tests.test_inventory_name_index import scene


MATCH = M.match


def legacy_match(*args, **kwargs):
    kwargs.pop("_candidate_ids_by_name", None)
    return MATCH(*args, **kwargs)


def name_index(prospects, accounts):
    # 시험의 독립적인 전수 비교. 제품의 trigram/anchor 구현을 복제하지 않는다.
    return {M.loose_name(p.name): tuple(cid for cid, account in accounts.items()
            if M.name_relation(p.name, account["adAccountName"], M.CANDIDATE_CONTAIN_MIN)
            in (M.REL_SAME, M.REL_CONTAINS)) for p in prospects}


def account(cid, name):
    return {"customerId": cid, "adAccountNo": cid + 5000000, "adAccountName": name}


class Visited(tuple):
    def __new__(cls, values):
        result = super().__new__(cls, values)
        result.visits = 0
        return result

    def __iter__(self):
        for item in super().__iter__():
            self.visits += 1
            yield item


class CandidateIndexReuseTest(unittest.TestCase):
    def equivalent(self, prospects, accounts, credentials=(), decisions=(), index=None, **kwargs):
        if index is None:
            index = name_index(prospects, accounts)
        inputs = (prospects, accounts, credentials, decisions, index, kwargs)
        # tuple 계측 자체가 복사 순회로 방문 수를 늘리지 않게 먼저 보존한다.
        before = copy.deepcopy(inputs)
        for related in index.values():
            if isinstance(related, Visited):
                related.visits = 0
        expected = MATCH(prospects, credentials, accounts, decisions, accounts_complete=True, **kwargs)
        actual = MATCH(prospects, credentials, accounts, decisions, accounts_complete=True,
                       _candidate_ids_by_name=index, **kwargs)
        # Pair.auto_identity_fingerprint는 dataclass compare=False이므로 필드 전체를 비교한다.
        self.assertEqual(asdict(actual), asdict(expected))
        self.assertEqual(inputs, before)
        return actual

    def test_sparse_index_visits_only_related_accounts(self):
        prospects = [M.ErpProspect(1, "합성식품")]
        accounts = {1000000+i: account(1000000+i, f"다른상점{i}") for i in range(100)}
        accounts[1000000]["adAccountName"] = "합성식품"
        accounts[1000001]["adAccountName"] = "합성식품상점"
        related = Visited((1000001, 1000000))
        result = self.equivalent(prospects, accounts, index={"합성식품": related})
        self.assertEqual(related.visits, 2)
        self.assertEqual([r.customer_id for r in result.candidates], [1000000, 1000001])

    def test_dense_equal_or_larger_index_uses_original_loop(self):
        prospects = [M.ErpProspect(1, "합성식품")]
        accounts = {1000000+i: account(1000000+i, "합성식품") for i in range(8)}
        for extra in ((), (9999999,)):
            with self.subTest(extra=extra):
                related = Visited(tuple(accounts) + extra)
                result = self.equivalent(prospects, accounts, index={"합성식품": related})
                self.assertEqual(related.visits, 0)
                self.assertEqual(len(result.candidates), M.CANDIDATE_MAX)

    def test_missing_all_or_some_name_keys_falls_back_per_name(self):
        prospects = [M.ErpProspect(1, "합성식품"), M.ErpProspect(2, "다른상점")]
        accounts = {1000000+i: account(1000000+i, f"무관상점{i}") for i in range(20)}
        accounts[1000000]["adAccountName"] = "합성식품"
        accounts[1000001]["adAccountName"] = "다른상점"
        for index in ({}, {"합성식품": (1000000,)}):
            with self.subTest(index=index):
                result = self.equivalent(prospects, accounts, index=index)
                self.assertEqual(len(result.candidates), 2)

    def test_index_still_checks_membership_pairing_name_relation_and_rejections(self):
        prospects = [M.ErpProspect(1, "합성식품"), M.ErpProspect(2, "합성식품")]
        accounts = {1000000+i: account(1000000+i, f"무관상점{i}") for i in range(20)}
        for cid in (1000000, 1000001, 1000002):
            accounts[cid]["adAccountName"] = "합성식품"
        accounts[1000003]["adAccountName"] = None
        decisions = [M.HumanDecision(2, 1000000), M.HumanDecision(1, 1000001, M.DECISION_REJECTED)]
        related = Visited((9999999, 1000000, 1000001, 1000002, 1000003, 1000004))
        result = self.equivalent(prospects, accounts, decisions=decisions, index={"합성식품": related})
        self.assertEqual(related.visits, 6)
        self.assertEqual([(c.customer_id, c.same_name_accounts) for c in result.candidates], [(1000002, 3)])

    def test_both_contains_directions_unicode_short_names_and_duplicate_companies(self):
        names = ["가상식품", "(주)오후", "오후마트", "ABＣＤ", "한강상점온라인", "abcxyz", "xyz",
                 None, "!", "가상식품", "𠀀", "㈜메타", "Ⅻ", "Α1Σ"]
        prospects = [M.ErpProspect(i+1, name) for i, name in enumerate(names)]
        accounts = {1000000+i: account(1000000+i, name) for i, name in enumerate(
            ["가상식품온라인", "오후", "오후", "abcd", "한강상점", "abcxyzdef", "xyz", None, "!",
             "가상식품", "𠀀", "메타", "xii", "α1σ"])}
        self.equivalent(prospects, accounts)

    def test_multiple_confirmed_accounts_and_companies_remain_separate(self):
        prospects = [M.ErpProspect(1, "합성식품"), M.ErpProspect(2, "합성식품")]
        accounts = {1000000+i: account(1000000+i, "합성식품") for i in range(8)}
        decisions = [M.HumanDecision(1, 1000000), M.HumanDecision(1, 1000001)]
        result = self.equivalent(prospects, accounts, decisions=decisions)
        self.assertEqual([(p.possibility_id, p.customer_id) for p in result.pairs], [(1, 1000000), (1, 1000001)])
        self.assertEqual({c.possibility_id for c in result.candidates}, {2})
        self.assertTrue(all(c.same_name_accounts == 8 for c in result.candidates))

    def test_empty_free_and_missing_confirmed_account_keep_full_result(self):
        prospects = [M.ErpProspect(1, "합성식품"), M.ErpProspect(2, "합성식품")]
        accounts = {1000000: account(1000000, "합성식품")}
        decisions = [M.HumanDecision(1, 1000000), M.HumanDecision(2, 9999999)]
        related = Visited((1000000,))
        result = self.equivalent(prospects, accounts, decisions=decisions, index={"합성식품": related},
                                 previous_ad_accounts={9999999: 8000000})
        self.assertEqual(related.visits, 0)
        self.assertTrue(result.confirmed_missing)
        self.assertEqual(result.candidates, ())

    def test_randomized_claims_decisions_and_all_result_fields_match_original_path(self):
        rng = random.Random(205)
        names = ["합성식품", "합성식품온라인", "오후", "오후마트", "ABＣＤ", None, "!", "한강상점"]
        for _ in range(24):
            prospects = [M.ErpProspect(i+1, rng.choice(names)) for i in range(24)]
            accounts = {1000000+i: account(1000000+i, rng.choice(names)) for i in range(30)}
            credentials = [M.ErpCredential(i+1, M.VENDOR_NAVER, str(1000000+rng.randrange(8)))
                           for i in range(8)]
            decisions = [M.HumanDecision(20, 1000001), M.HumanDecision(21, 1000002, M.DECISION_REJECTED)]
            self.equivalent(prospects, accounts, credentials, decisions)

    def test_inventory_counts_include_all_candidates_beyond_display_limit(self):
        ctx, catalog = scene(["합성식품", "합성식품"], ["합성식품상점" + str(n) for n in range(8)] + ["무관업체"])
        ctx.live_decisions = [M.HumanDecision(1, 1000000, M.DECISION_REJECTED)]
        counts = {}
        result, possible = I._matching(ctx, catalog, candidate_counts=counts)
        expected_counts = {}
        with patch.object(M, "match", side_effect=legacy_match):
            expected, expected_possible = I._matching(ctx, catalog, candidate_counts=expected_counts)
        self.assertEqual((asdict(result), possible, counts), (asdict(expected), expected_possible, expected_counts))
        self.assertEqual(counts, {1: 7, 2: 8})
        self.assertEqual(len(result.candidates), M.CANDIDATE_MAX * 2)
        self.assertEqual(len(possible), 8)

    def test_current_and_absent_account_universes_use_separate_indexes_without_mutation(self):
        ctx, catalog = scene(["합성식품"], ["합성식품", "합성식품상점", "무관업체"])
        ctx.accounts[1000000]["present"] = 0
        before = copy.deepcopy((ctx.accounts, catalog))
        for include_absent, expected_count in ((False, 1), (True, 2)):
            with self.subTest(include_absent=include_absent):
                counts, expected_counts = {}, {}
                actual, possible = I._matching(ctx, catalog, include_absent=include_absent, candidate_counts=counts)
                with patch.object(M, "match", side_effect=legacy_match):
                    expected, expected_possible = I._matching(ctx, catalog, include_absent=include_absent,
                                                              candidate_counts=expected_counts)
                self.assertEqual((asdict(actual), possible, counts), (asdict(expected), expected_possible, expected_counts))
                self.assertEqual(counts, {1: expected_count})
        self.assertEqual((ctx.accounts, catalog), before)


class CandidatePublicResponseTest(unittest.TestCase):
    setUp = AR.AccountsMatchReuseTest.setUp
    call = AR.AccountsMatchReuseTest.call

    def test_full_responses_keep_roles_selection_totals_codes_and_source_bound_refs(self):
        for actor, narrowed in ((0, False), (1, False), (100, False), (101, False), (0, True)):
            for path in ("/accounts", "/accounts?selection=person:100", "/accounts?selection=team:11",
                         "/accounts?selection=unassigned", "/accounts?mapping=matched", "/accounts?view=lost",
                         "/me", "/links/pending", "/links/pending?selection=person:100"):
                with self.subTest(actor=actor, narrowed=narrowed, path=path):
                    with patch.object(M, "match", side_effect=legacy_match):
                        expected = self.call(path, actor, narrowed=narrowed)
                    self.assertEqual(self.call(path, actor, narrowed=narrowed), expected)

    def test_accounts_return_full_total_above_one_screen_page(self):
        fixture = CL.make_fixture(accounts=121, managed=121, campaigns=0)
        self.addCleanup(fixture.store.close)
        # setUp의 reader는 self.store를 매 요청 시 참조한다.
        self.store, self.clock = fixture.store, fixture.clock
        with patch.object(M, "match", side_effect=legacy_match):
            expected = self.call("/accounts")
        actual = self.call("/accounts")
        self.assertEqual(actual, expected)
        self.assertEqual(actual[0], 200)
        self.assertEqual((actual[1]["total"], len(actual[1]["rows"])), (121, 121))
        account_numbers = [row["ad_account_no"] for row in actual[1]["rows"]]
        self.assertEqual(len(set(account_numbers)), 121)


if __name__ == "__main__":
    unittest.main()
