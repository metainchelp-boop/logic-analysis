"""계정 목록 이름 인덱스: 포함 관계 보존과 공통 접두어 퇴화 방지. 외부 요청 없음."""
import random
import time
import unittest
from types import SimpleNamespace

from app.naver_auto import matching as M
from naver_engine import inventory as I


def scene(company_names, account_names, *, credential_count=0):
    ctx = SimpleNamespace(accounts={1000000+i: dict(ad_account_no=2000000+i, account_name=name, present=1)
                                    for i, name in enumerate(account_names)}, live_decisions=[])
    catalog = dict(items=[dict(possibility_id=i+1, company_name=name) for i, name in enumerate(company_names)],
                   ids=[dict(possibility_id=i+1, vendor=M.VENDOR_NAVER, customer_id_raw=str(1000000+i),
                             ad_account_no_raw=None) for i in range(credential_count)])
    return ctx, catalog


class NameIndexTest(unittest.TestCase):
    def assert_matches_brute_force(self, companies, accounts, *, credential_count=0, decisions=()):
        ctx, catalog = scene(companies, accounts, credential_count=credential_count)
        ctx.live_decisions = decisions
        result, possible = I._matching(ctx, catalog)
        expected = M.match(
            [M.ErpProspect(r["possibility_id"], r["company_name"]) for r in catalog["items"]],
            [M.ErpCredential(r["possibility_id"], r["vendor"], r["customer_id_raw"],
                             ad_account_no_raw=r["ad_account_no_raw"]) for r in catalog["ids"]],
            {cid: {"customerId": cid, "adAccountNo": a["ad_account_no"], "adAccountName": a["account_name"]}
             for cid, a in ctx.accounts.items()}, decisions, accounts_complete=True)
        expected_possible = {1000000+i for i, account in enumerate(accounts) if any(
            M.name_relation(company, account, M.CANDIDATE_CONTAIN_MIN) in (M.REL_SAME, M.REL_CONTAINS)
            for company in companies)}
        self.assertEqual(result, expected)
        self.assertEqual(possible, expected_possible)

    def test_both_contains_directions_exact_short_and_normalization_match_brute_force(self):
        self.assert_matches_brute_force(
            ["가상식품", "(주)오후", "오후마트", "ABＣＤ", "한강상점온라인", "abcxyz", "xyz", None, "!", "가상식품"],
            ["가상식품온라인", "오후", "오후", "abcd", "한강상점", "abcxyzdef", "xyz", None, "!", "가상식품"])

    def test_randomized_candidates_credentials_and_human_decisions_match_brute_force(self):
        rng = random.Random(172)
        words = ["가상식품", "한강상점", "abcxyz", "오후", "ABＣＤ", None, "!", "공통문구"]
        for _ in range(12):
            accounts = [rng.choice(words) for _ in range(35)]
            companies = [rng.choice(words) for _ in range(80)]
            for values in (accounts, companies):
                for i, name in enumerate(values):
                    if name is not None and rng.random() < .6:
                        values[i] = rng.choice(["", "온라인", "(주)"]) + name + rng.choice(["", "몰", "상점"])
            decisions = [M.HumanDecision(79, 1000001, "confirmed"), M.HumanDecision(80, 1000002, "rejected")]
            self.assert_matches_brute_force(companies, accounts, credential_count=8, decisions=decisions)

    def test_common_prefix_catalog_has_bounded_cpu_cost(self):
        names = [f"가상업체{i:08d}" for i in range(100000)]
        ctx, catalog = scene(names, names[:1800], credential_count=1800)
        start = time.process_time()
        result, possible = I._matching(ctx, catalog)
        elapsed = time.process_time() - start
        self.assertEqual(len(result.pairs), 1800)
        self.assertEqual(len(possible), 1800)
        # 180M 포함 비교였던 재현은 로컬 CPU 약18초. 큐/네트워크 대기는 측정하지 않는다.
        self.assertLess(elapsed, 8.0, "공통 접두어가 전체 업체×계정 순회로 퇴화했습니다")


if __name__ == "__main__":
    unittest.main()
