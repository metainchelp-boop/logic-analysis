"""고객 상세 개별 계정 조회 — 모든 이름·번호·금액은 합성 자료다."""
import copy
import json
import pathlib
import hashlib
import unittest
from datetime import timedelta
from naver_engine.tests import test_web as TW
from naver_engine.tests import test_morning as TM
from naver_engine.tests import test_alerts as TA
from naver_engine import store as S
from naver_engine import views as W
from naver_engine import report_views as RV
from app.naver_auto import scope as SC

E = 5678901

def key(cid):
    return hashlib.sha256(str(cid).encode('ascii')).hexdigest()

def add_split_accounts(self):
    self.st.record_decision(11, E, 'confirmed', 0, self.fc.now())
    self.repair([(12, TW.B), (14, 9999999)], extra={E: {'customerId': E, 'adAccountNo': 8678901, 'adAccountName': '별도 계정'}})
    rid = self.st.begin_run(TW.TODAY, self.fc.now())
    for cid, spend, imp, clk, money, level in ((TW.A, 40, 100, 10, 80, 'red'), (E, 60, 200, 20, 120, 'yellow')):
        self.st.record_account_check(rid, cid, possibility_id=11, link='confirmed', status='ok',
            rules_run=('bizmoney', 'link'), rules_not_run=(), checked_at=self.fc.now(),
            yday_spend=spend, yday_imp=imp, yday_clk=clk, bizmoney=money,
            findings=(TA.F('bizmoney', 'bizmoney_low', f'acc:{cid}', level),))
    self.st.finish_run(rid, S.RUN_DONE, self.fc.now())


def put_catalog(self, ids, names=None):
    from naver_engine.tests.test_account_catalog import company
    rows = [company(pid, '진행중', company_name=(names or {}).get(pid, TM.shop(pid))) for pid in (11, 12, 13, 14)]
    self.st.record_account_catalog({'generated_at': self.fc.now().isoformat(), 'total': len(rows), 'complete': True, 'items': rows}, ids, self.fc.now())


class ClientAccountSelectionTest(TW.WebBase):
    def setUp(self):
        super().setUp()
        add_split_accounts(self)

    def test_company_default_and_individual_accounts_remain_separate(self):
        status, company = self.get('/clients/11', 100)
        self.assertEqual(status, 200)
        self.assertEqual((company['yday_spend'], company['yday_imp'], company['yday_clk'], company['bizmoney']), (100, 300, 30, 200))
        for cid, expected in ((TW.A, (40, 100, 10, 80)), (E, (60, 200, 20, 120))):
            status, detail = self.get('/clients/11', 100, query='account_key=' + key(cid))
            self.assertEqual(status, 200)
            self.assertEqual((detail['yday_spend'], detail['yday_imp'], detail['yday_clk'], detail['bizmoney']), expected)
            self.assertEqual(len(detail['accounts']), 1)
            self.assertEqual(detail['accounts'][0]['tail'], str(cid)[-4:])
            self.assertEqual(detail['account_selection'], {'kind': 'account', 'account_key': key(cid)})
            self.assertEqual({a['account_key'] for a in detail['account_choices']}, {key(TW.A), key(E)})
            self.assertTrue(all(i['target_tail'] == str(cid)[-4:] for i in detail['issues']))
        self.assertEqual(self.get('/clients/11', 100)[1], company)

    def test_invalid_foreign_candidate_and_raw_keys_are_same_404_without_fallback(self):
        expected = self.call('GET', '/clients/999999', self.token(100))[3]
        for pid, chosen, who in ((11, key(TW.B), 100), (11, key(TW.C_), 100), (11, key(TW.D), 100),
                                  (11, key(99999), 100), (12, key(TW.A), 0), (11, key(TW.A), 101),
                                  (11, '', 100), (11, str(TW.A), 100), (11, 'A' * 64, 100), (11, key(TW.A) + '0', 100)):
            with self.subTest(pid=pid, chosen=chosen, who=who):
                status, body, headers, raw = self.call('GET', '/clients/' + str(pid), self.token(who), query='account_key=' + chosen)
                self.assertEqual(status, 404)
                self.assertEqual(raw, expected)
                self.assertNotIn('accounts', body)

    def test_default_business_body_is_identical_to_original_9bfc(self):
        # 고정 9bfc 원본 client 함수만 비교한다. 다른 기존 helper는 이번 패치에서 변경하지 않는다.
        reference_path = pathlib.Path(__file__).with_name('fixtures') / 'client_9bfc_reference.txt'
        namespace = dict(vars(W))
        exec(compile(reference_path.read_text(), str(reference_path), 'exec'), namespace)
        old_client = namespace['client']
        ctx = W.load(self.st, self.fc.now())
        for who in (0, 100):
            scope = SC.scope_of(ctx.org, who)
            old = json.loads(json.dumps(old_client(ctx, self.st, scope, 11)))
            status, new = self.get('/clients/11', who)
            self.assertEqual(status, 200)
            new = copy.deepcopy(new)
            setup = new.pop('setup_checks')
            self.assertEqual(set(setup), {'version', 'items', 'counts', 'source'})
            self.assertEqual(setup['version'], 1)
            self.assertEqual([item['key'] for item in setup['items']], [
                'structure', 'inspection', 'suspension', 'delivery', 'campaign_budget',
                'campaign_period', 'time_targeting', 'region_targeting', 'age_targeting',
                'negative_keywords', 'creative_copy', 'goal', 'budget_plan', 'setup_completeness'])
            self.assertEqual(len(setup['items']), 14)
            self.assertEqual(set(setup['counts']), {'attention', 'unknown', 'verified', 'not_applicable'})
            self.assertEqual(sum(setup['counts'].values()), 14)
            for item in setup['items']:
                self.assertEqual(set(item), {'key', 'label', 'state', 'summary', 'next_action'})
                self.assertIn(item['state'], setup['counts'])
                self.assertTrue(all(isinstance(item[field], str) and item[field]
                                    for field in ('label', 'summary', 'next_action')))
            self.assertEqual(new.pop('account_selection'), {'kind': 'company', 'account_key': None})
            choices = new.pop('account_choices')
            self.assertEqual(len(choices), len(old['accounts']))
            for account in new['accounts']:
                chosen = account.pop('account_key')
                self.assertIn(chosen, {key(TW.A), key(E)})
            self.assertEqual(new, old)
        self.assertEqual(key(TW.A), RV.account_key(TW.A))

    def test_scope_and_ownership_are_rechecked_for_current_request(self):
        token = self.token(100)
        self.assertEqual(self.call('GET', '/clients/11', token, query='account_key=' + key(E))[0], 200)
        body = TA.org_body(self.fc.now(), owners=[TA.owner(11, 101), TA.owner(12, 101), TA.owner(13, None), TA.owner(14, 100)])
        self.st.record_org(body, self.fc.now())
        self.assertEqual(self.call('GET', '/clients/11', token, query='account_key=' + key(E))[0], 404)
        self.assertEqual(self.get('/clients/11', 101, query='account_key=' + key(E))[0], 200)
        self.assertEqual(self.get('/clients/11', 1, query='account_key=' + key(E), narrowed=True)[0], 404)

    def test_rematched_account_old_key_is_rejected_and_accounts_not_replaced(self):
        before = self.get('/clients/11', 100)[1]
        self.at(self.fc.now() + timedelta(minutes=1))
        self.st.record_decision(12, E, 'confirmed', 0, self.fc.now())
        self.repair([(12, TW.B), (14, 9999999)], extra={E: {'customerId': E, 'adAccountNo': 8678901, 'adAccountName': '별도 계정'}})
        self.assertEqual(self.get('/clients/11', 100, query='account_key=' + key(E))[0], 404)
        after = self.get('/clients/11', 100)[1]
        self.assertEqual([a['account_key'] for a in after['accounts']], [key(TW.A)])
        self.assertEqual(len(before['accounts']), 2)
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(E))[0], 200)

    def test_missing_values_remain_null_and_zero_remains_zero(self):
        rid = self.st.begin_run(TW.TODAY, self.fc.now())
        self.st.record_account_check(rid, E, possibility_id=11, link='confirmed', status='partial',
            rules_run=(), rules_not_run=(('stats', 'unavailable'),), checked_at=self.fc.now(),
            yday_spend=None, yday_imp=0, yday_clk=None, bizmoney=0)
        self.st.finish_run(rid, S.RUN_DONE, self.fc.now())
        company = self.get('/clients/11', 100)[1]
        one = self.get('/clients/11', 100, query='account_key=' + key(E))[1]
        other = self.get('/clients/11', 100, query='account_key=' + key(TW.A))[1]
        self.assertEqual((one['yday_spend'], one['yday_imp'], one['yday_clk'], one['bizmoney']), (None, 0, None, 0))
        self.assertIsNone(company['yday_spend'])
        self.assertEqual(other['yday_spend'], 40)
        self.assertIsNone(one['days'][-1]['yday_spend'])
        self.assertFalse(one['days'][-1]['complete'])

    def test_history_window_does_not_expose_other_company_days(self):
        saved_now = self.fc.now()
        for back, pid, spend in ((1, 11, 17), (2, 12, 900), (13, 11, 13), (14, 11, 14)):
            moment = TW.at(TW.TODAY - timedelta(days=back), 9)
            self.at(moment)
            rid = self.st.begin_run(moment.date(), moment)
            self.st.record_account_check(rid, E, possibility_id=pid, link='confirmed', status='ok',
                rules_run=(), rules_not_run=(), checked_at=moment, yday_spend=spend)
            self.st.finish_run(rid, S.RUN_DONE, moment)
        self.at(saved_now)
        status, one = self.get('/clients/11', 100, query='account_key=' + key(E))
        self.assertEqual(status, 200)
        history = {d['day']: d for d in one['accounts'][0]['history']}
        self.assertEqual(len(history), 14)
        self.assertEqual(history[(TW.TODAY - timedelta(days=1)).isoformat()]['yday_spend'], 17)
        self.assertEqual(history[(TW.TODAY - timedelta(days=2)).isoformat()], {'day': (TW.TODAY - timedelta(days=2)).isoformat(), 'status': None})
        self.assertIn((TW.TODAY - timedelta(days=13)).isoformat(), history)
        self.assertNotIn((TW.TODAY - timedelta(days=14)).isoformat(), history)

    def test_original_context_is_not_mutated_and_raw_customer_ids_are_not_exported(self):
        ctx = W.load(self.st, self.fc.now())
        original_rows, original_issues = copy.deepcopy(ctx.rows_by_pid), copy.deepcopy(ctx.open_issues)
        scope = SC.scope_of(ctx.org, 100)
        company = W.client(ctx, self.st, scope, 11)
        selected = W.client(ctx, self.st, scope, 11, key(E))
        self.assertEqual(ctx.rows_by_pid, original_rows)
        self.assertEqual(ctx.open_issues, original_issues)
        self.assertEqual(W.client(ctx, self.st, scope, 11), company)
        wire = json.dumps(selected)
        for cid in (TW.A, TW.B, TW.C_, TW.D, E):
            self.assertNotIn(str(cid), wire)
        self.assertNotIn('customer_id', wire)

    def test_holding_and_expired_policies_are_not_changed_by_account_selection(self):
        for stage, end in (('홀딩중', None), ('계약만료', TW.TODAY - timedelta(days=2))):
            self.repair([(12, TW.B), (14, 9999999)], stages={11: TM.srow(11, stage=stage, end=end)},
                extra={E: {'customerId': E, 'adAccountNo': 8678901, 'adAccountName': '별도 계정'}})
            s, company = self.get('/clients/11', 100)
            t, one = self.get('/clients/11', 100, query='account_key=' + key(E))
            self.assertEqual((s, t), (200, 200))
            for field in ('stage', 'managed', 'latest_end_date', 'relation', 'owner', 'actions'):
                self.assertEqual(one[field], company[field], field)
            self.assertEqual(one['stage'], stage)

    def test_hidden_or_unknown_stage_reuses_existing_access_policy(self):
        from naver_engine.tests.test_account_catalog import company
        for flags in ({'stage_hidden': True}, {'stage_known': False}):
            rows = [company(11, '진행중', **flags), company(12, '진행중'), company(13, '진행중'), company(14, '진행중')]
            self.st.record_account_catalog({'generated_at': self.fc.now().isoformat(), 'total': len(rows), 'complete': True, 'items': rows}, (), self.fc.now())
            self.assertEqual(self.get('/clients/11', 100, query='account_key=' + key(E))[0], 404)
            self.assertEqual(self.get('/clients/11', 0, query='account_key=' + key(E))[0], 200)

    def test_yesterday_pairing_does_not_become_fresh_by_selecting_account(self):
        self.at(TW.at(TW.TODAY + timedelta(days=1), 9))
        self.st.record_org(TA.org_body(self.fc.now()), self.fc.now())
        company = self.get('/clients/11', 100)[1]
        status, one = self.get('/clients/11', 100, query='account_key=' + key(E))
        self.assertEqual(status, 200)
        self.assertIsNone(company['yday_spend'])
        self.assertIsNone(one['yday_spend'])
        self.assertEqual(one['link'], 'pending')
        self.assertEqual(one['verdict']['color'], 'white')
        self.assertEqual(one['accounts'][0]['history'][0], {'day': (TW.TODAY + timedelta(days=1)).isoformat(), 'status': None})

    def test_authentication_and_current_employee_status_are_required(self):
        self.assertEqual(self.call('GET', '/clients/11', query='account_key=' + key(E))[0], 401)
        token = self.token(100)
        self.resign(100)
        self.assertEqual(self.call('GET', '/clients/11', token, query='account_key=' + key(E))[0], 401)

    def test_current_confirmed_decision_revoke_reject_or_other_company_blocks_before_repair(self):
        from unittest import mock
        for change in ('revoke', 'reject', 'remap'):
            with self.subTest(change=change):
                # 현재 짝은 그대로 두고 최신 사람 판단만 바꾼다.
                live, _ = self.st.link_decisions()
                active = next(d for d in live if d.customer_id == E and d.possibility_id == 11 and d.decision == 'confirmed')
                try:
                    if change == 'revoke':
                        self.st.revoke_decision(active.decision_id, 0, self.fc.now(), '합성 회수')
                    else:
                        self.st.record_decision(11 if change == 'reject' else 12, E, 'rejected' if change == 'reject' else 'confirmed', 0, self.fc.now())
                    with mock.patch.object(S.Store, 'account_day', side_effect=AssertionError('무효 선택은 이력을 읽으면 안 됨')):
                        self.assertEqual(self.get('/clients/11', 100, query='account_key=' + key(E))[0], 404)
                    # 기본 회사 합계의 기존 수락 pairing 의미는 건드리지 않는다.
                    self.assertEqual(self.get('/clients/11', 100)[1]['yday_spend'], 100)
                finally:
                    self.at(self.fc.now() + timedelta(seconds=1))
                    self.st.record_decision(11, E, 'confirmed', 0, self.fc.now())
                self.assertEqual(self.get('/clients/11', 100, query='account_key=' + key(E))[0], 200)

    def test_auto_decision_conflict_rejects_before_repair(self):
        from unittest import mock
        put_catalog(self, (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)),))
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 200)
        self.st.record_decision(12, TW.B, 'rejected', 0, self.fc.now())
        with mock.patch.object(S.Store, 'account_day', side_effect=AssertionError('무효 선택 이력 조회')):
            self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)
        self.at(self.fc.now() + timedelta(seconds=1))
        self.st.record_decision(11, TW.B, 'confirmed', 0, self.fc.now())
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)

    def test_auto_mapping_refresh_before_repair_and_all_number_spaces(self):
        from unittest import mock
        ad_b = self.st.accounts()[1]['ad_account_no']
        # 고객 번호와 광고계정 번호 각각 현재 일치할 때만 연다.
        for credential in (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)),
                           TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, None, ad_account_no_raw=str(ad_b))):
            put_catalog(self, (credential,))
            self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 200)
        for ids in ((TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.D)),),
                    (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, None, ad_account_no_raw='9999999'),),
                    (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B), ad_account_no_raw='8567890'),),
                    (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)), TW.E.NaverIdRow(14, TW.M.VENDOR_NAVER, str(TW.B))),
                    (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)), TW.E.NaverIdRow(14, TW.M.VENDOR_NAVER, None, ad_account_no_raw=str(ad_b)))):
            with self.subTest(ids=ids):
                put_catalog(self, ids)
                with mock.patch.object(S.Store, 'account_day', side_effect=AssertionError('변경된 자동 연결의 이력을 읽으면 안 됨')):
                    self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)
                self.assertEqual(len(self.get('/clients/12', 101)[1]['accounts']), 1)
        # 다른 계정의 광고계정 번호가 선택 CID와 같은 번호 공간 충돌도 빼놓지 않는다.
        kids = TM.kids(TW.A, TW.B, TW.C_, TW.D, E)
        kids.accounts[TW.D]['adAccountNo'] = TW.B
        self.at(self.fc.now() + timedelta(seconds=1))
        self.st.record_accounts(kids, self.fc.now())
        put_catalog(self, (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)),))
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)

    def test_retained_auto_evidence_must_have_same_current_identity(self):
        put_catalog(self, (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)),))
        # 운영 원문 대신 실제 writer 동기화를 합성 fixture에 수행해 공식 identity 지문을 저장한다.
        self.st.synchronize_management(self.fc.now())
        self.assertIn((12, TW.B), self.st.automatic_link_evidence())
        put_catalog(self, (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)),), {12: '전혀다른합성업체'})
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 200)
        ad_b = next(a['ad_account_no'] for a in self.st.accounts() if a['customer_id'] == TW.B)
        put_catalog(self, (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, None, ad_account_no_raw=str(ad_b)),), {12: '전혀다른합성업체'})
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)

    def test_current_name_claim_and_missing_catalog_cannot_open_auto_account(self):
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)
        put_catalog(self, (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)),), {12: '전혀다른합성업체', 14: TM.shop(12)})
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)
        # 사람의 현재 확인은 ERP 자동 입력보다 우선하며 기본 회사 응답은 그대로다.
        self.st.record_decision(12, TW.B, 'confirmed', 0, self.fc.now())
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 200)

    def test_retained_evidence_cannot_bypass_other_current_prospect_name(self):
        from unittest import mock
        credential = TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B))
        put_catalog(self, (credential,))
        self.st.synchronize_management(self.fc.now())
        rows = {pid: TM.srow(pid, name=TM.shop(12) if pid == 14 else None) for pid in (11, 12, 13, 14)}
        self.st.record_prospects(TW.E.StageSnapshot(rows, self.fc.now(), {}, ()))
        for name, relation in ((TM.shop(12) + '별도합성', TW.M.REL_CONTAINS),
                               ('X', TW.M.REL_UNKNOWN), ('전혀다른합성업체', TW.M.REL_DIFFERENT)):
            with self.subTest(relation=relation):
                self.assertEqual(TW.M.name_relation(name, TM.shop(12)), relation)
                put_catalog(self, (credential,), {12: name})
                self.assertIn((12, TW.B), self.st.automatic_link_evidence())
                with mock.patch.object(S.Store, 'account_day', side_effect=AssertionError('다른 업체 이름 주장 이력 조회 금지')):
                    self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)
                self.assertEqual(len(self.get('/clients/12', 101)[1]['accounts']), 1)
        put_catalog(self, (credential,))
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 200)

    def test_missing_or_broken_auto_requires_official_current_pair_and_manual_confirm_survives(self):
        put_catalog(self, (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)),))
        for back, wanted in ((0, S.PAIR_MISSING), (1, S.PAIR_BROKEN)):
            self.at(TW.at(TW.TODAY + timedelta(days=back), 10))
            self.st.record_org(TA.org_body(self.fc.now()), self.fc.now())
            self.st.record_accounts(TM.kids(TW.A, TW.C_, TW.D, E), self.fc.now())
            outcome = TW.L.pair_links(TM.FakeErp([TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B))]), self.st, self.fc.now())
            self.assertEqual(outcome.outcome, S.SYNC_ACCEPTED)
            ctx = W.load(self.st, self.fc.now())
            self.assertEqual(ctx.rows_by_pid[12][0]['state'], wanted)
            self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)
            self.assertEqual(len(self.get('/clients/12', 101)[1]['accounts']), 1)
        self.st.record_decision(12, TW.B, 'confirmed', 0, self.fc.now())
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 200)

    def test_auto_catalog_failure_and_staleness_reject_without_new_snapshot(self):
        from unittest import mock
        from naver_engine import management_store as MS
        put_catalog(self, (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)),))
        with mock.patch.object(MS, 'snapshot', side_effect=AssertionError('개별 상세는 새 전체 snapshot 금지')):
            self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 200)
        self.st.record_account_catalog_failure(self.fc.now(), 'CATALOG_FAILED')
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)
        put_catalog(self, (TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B)),))
        self.at(self.fc.now() + timedelta(hours=2, seconds=1))
        self.st.record_org(TA.org_body(self.fc.now()), self.fc.now())
        self.assertEqual(self.get('/clients/12', 101, query='account_key=' + key(TW.B))[0], 404)

if __name__ == '__main__':
    unittest.main()
