"""계정우선 수집: 가짜 HTTP와 임시 저장소만 사용한다."""
from datetime import timedelta

from naver_engine import inventory_reads as I
from naver_engine.tests.test_morning import Base, A, B, kids, steady


class InventoryTest(Base):
    def test_unmatched_account_collects_without_erp_and_preserves_existing_history(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())], biz=12000)
        result = I.run_inventory(self.reader(), self.st, self.fc.now)
        self.assertEqual(result.counts, {"ok": 1})
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual((row["status"], row["bizmoney"], row["yday_spend"], row["yday_imp"], row["yday_clk"]),
                         ("ok", 12000, 20000, 1000, 50))
        self.assertIsNone(self.st.account_day(A, self.fc.now().date()))
        self.assertIsNone(self.st.last_pairing())

    def test_permission_denied_is_explicit_and_does_not_starve_other_accounts_after_restart(self):
        self.st.record_accounts(kids(A, B), self.fc.now())
        self.ads.add(B, [], biz=10)
        self.ads.fail[(A, "camps")] = (403, {"code": 1006})
        I.run_inventory(self.reader(), self.st, self.fc.now, limit=1)
        self.assertEqual(self.st.inventory_checks_on(self.fc.now().date())[A]["status"], "reauth_required")
        self.st.close()
        from naver_engine import store as S
        self.st = S.open_writer(self.path, clock=self.fc.now)
        I.run_inventory(self.reader(), self.st, self.fc.now, limit=1)
        self.assertEqual(self.st.inventory_checks_on(self.fc.now().date())[B]["status"], "ok")

    def test_missing_stats_are_unknown_not_zero_and_retry_is_bounded(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(1, "ELIGIBLE", False, steady(0, 0, 0, 0))], biz=10)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual(row["status"], "retry")
        self.assertIsNone(row["yday_spend"])
        requests = len(self.naver.calls)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        self.assertEqual(len(self.naver.calls), requests)

    def test_request_budget_counts_internal_retries_and_moves_to_next_account(self):
        self.st.record_accounts(kids(A, B), self.fc.now())
        self.ads.add(B, [], biz=20)
        self.ads.fail[(A, "camps")] = (500, {"code": 500})
        I.run_inventory(self.reader(), self.st, self.fc.now, per_account_calls=3)
        first = [c for c in self.naver.calls if c.customer == str(A)]
        self.assertEqual(len(first), 3)
        rows = self.st.inventory_checks_on(self.fc.now().date())
        self.assertEqual(rows[A]["error_code"], "REQUEST_BUDGET")
        self.assertEqual(rows[B]["status"], "ok")

    def test_stale_or_revoked_snapshot_makes_no_requests_and_revocation_between_calls_stops(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [], biz=10)
        self.fc.advance(31 * 3600)
        self.assertEqual(I.run_inventory(self.reader(), self.st, self.fc.now).code, "NOT_READY")
        self.assertEqual(self.naver.calls, [])
        self.st.record_accounts(kids(A), self.fc.now())
        def revoke(call):
            self.fc.advance(1)
            self.st.record_accounts(kids(B), self.fc.now())
        self.naver.tick = revoke
        self.assertEqual(I.run_inventory(self.reader(), self.st, self.fc.now).code, "SOURCE_CHANGED")
        self.assertEqual(len(self.naver.calls), 1)

    def test_large_account_resumes_verified_batches_after_restart_without_double_counting(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(n, "ELIGIBLE", False, steady()) for n in range(601)], biz=10)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual(row["status"], "partial")
        self.assertIsNone(row["yday_spend"])
        self.assertLessEqual(len(self.naver.calls), 8)
        self.st.close()
        from naver_engine import store as S
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.fc.advance(60)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["yday_spend"], 601 * 20000)
        self.assertEqual(row["yday_imp"], 601 * 1000)
        ids = [cid for kind, chunk in self.ads.stats_calls for cid in chunk if kind == "summary"]
        self.assertEqual(len(ids), 601)
        self.assertEqual(len(set(ids)), 601)

    def test_expired_contract_does_not_prevent_source_reading(self):
        self.scene(confirmed=((11, A),), auto=(), ends={11: self.fc.now().date() - timedelta(days=90)})
        self.ads.add(A, [], biz=10)
        self.assertEqual(I.run_inventory(self.reader(), self.st, self.fc.now).counts, {"ok": 1})

    def test_deadline_also_bounds_transport_timeout_and_retry_sleep(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.fail[(A, "camps")] = (429, {"code": 1016})
        before = self.fc.now()
        result = I.run_inventory(self.reader(), self.st, self.fc.now, max_seconds=1)
        self.assertLess((self.fc.now() - before).total_seconds(), 1)
        self.assertEqual(len(self.naver.calls), 1)
        self.assertEqual(result.counts, {"retry": 1})

    def test_response_after_deadline_is_not_reported_as_success(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [], biz=10)
        self.naver.tick = lambda call: self.fc.advance(2)
        result = I.run_inventory(self.reader(), self.st, self.fc.now, max_seconds=1)
        self.assertEqual(result.counts, {"retry": 1})
        self.assertEqual(len(self.naver.calls), 1)

    def test_four_failed_attempts_are_limited_and_next_day_is_independent(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(1, "ELIGIBLE", False, steady(0, 0, 0, 0))], biz=10)
        day = self.fc.now().date()
        for _ in range(4):
            result = I.run_inventory(self.reader(), self.st, self.fc.now)
            self.fc.advance(1800)
        self.assertEqual(result.counts, {"limited": 1})
        self.assertEqual(self.st.inventory_checks_on(day)[A]["error_code"], "RETRY_EXHAUSTED")
        requests = len(self.naver.calls)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        self.assertEqual(len(self.naver.calls), requests)
        self.fc.advance(24 * 3600)
        self.st.record_accounts(kids(A), self.fc.now())
        I.run_inventory(self.reader(), self.st, self.fc.now)
        self.assertGreater(len(self.naver.calls), requests)
        self.assertEqual(self.st.inventory_checks_on(day)[A]["status"], "limited")

    def test_inventory_handle_cannot_be_forged_or_used_for_extra_endpoints(self):
        from naver_engine import handles as H
        self.st.record_accounts(kids(A), self.fc.now())
        handle = H.issue_inventory_handle(customer_id=A, snapshot_at=self.fc.now(), now=self.fc.now(),
                                          validate=self.st.inventory_account_valid)
        with self.assertRaises(H.HandleInvalid):
            self.reader().get_channels(handle)
        object.__setattr__(handle, "customer_id", B)
        with self.assertRaises(H.HandleInvalid):
            self.reader().get_campaigns(handle)
        self.assertEqual(self.naver.calls, [])

    def test_latest_failed_inventory_refresh_blocks_the_previous_accepted_list(self):
        from naver_engine import store as S
        self.st.record_accounts(kids(A), self.fc.now())
        self.fc.advance(1)
        self.st.record_sync_event(S.SYNC_ACCOUNTS, S.SYNC_FAILED, ("INCOMPLETE_LIST",), self.fc.now())
        self.assertEqual(I.run_inventory(self.reader(), self.st, self.fc.now).code, "NOT_READY")
        self.assertEqual(self.naver.calls, [])

    def test_campaign_list_change_discards_old_partial_sum(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(n, "ELIGIBLE", False, steady()) for n in range(601)], biz=10)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        self.ads.add(A, [(700, "ELIGIBLE", False, steady(5, 2, 11, 1))], biz=10)
        self.fc.advance(60)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual((row["status"], row["yday_spend"], row["yday_imp"]), ("ok", 11, 5))

    def test_tampered_checkpoint_is_not_used_or_exposed_and_requires_review(self):
        import sqlite3
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(n, "ELIGIBLE", False, steady()) for n in range(601)], biz=10)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        # 저장 파일 훼손을 외부 저장 경계에서 주입한다. 제품 경로는 사용하지 않는다.
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE naver_auto_inventory_check SET progress_json = '{}' WHERE customer_id = ?", (A,))
        requests = len(self.naver.calls)
        self.fc.advance(60)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual((row["status"], row["error_code"]), ("limited", "CHECKPOINT_INVALID"))
        self.assertIsNone(row["yday_spend"])
        self.assertEqual(len(self.naver.calls), requests)

    def test_failed_batch_resumes_without_repeating_verified_batches(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(n, "ELIGIBLE", False, steady()) for n in range(201)], biz=10)
        def fail_after_first_batch(call):
            if call.path == "/stats":
                self.naver.tick = None
                self.naver.script("/stats", (200, {"unexpected": "shape"}))
        self.naver.tick = fail_after_first_batch
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual(row["status"], "retry")
        self.assertIsNone(row["yday_spend"])
        self.fc.advance(300)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual((row["status"], row["yday_spend"]), ("ok", 201 * 20000))
        self.assertEqual(sum(len(chunk) for kind, chunk in self.ads.stats_calls if kind == "summary"), 201)

    def test_many_progress_rounds_do_not_consume_failure_budget(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(n, "ELIGIBLE", False, steady()) for n in range(601)], biz=10)
        # 3회 HTTP = 캠페인/잔액/100개 합계. 4회차를 넘어도 이어 읽는다.
        for _ in range(8):
            I.run_inventory(self.reader(), self.st, self.fc.now, per_account_calls=3)
            self.fc.advance(60)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual((row["status"], row["yday_spend"]), ("ok", 601 * 20000))

    def test_interrupted_process_keeps_only_verified_batches_for_restart(self):
        from naver_engine import store as S
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(n, "ELIGIBLE", False, steady()) for n in range(201)], biz=10)
        def interrupt_second_batch(call):
            if call.path == "/stats" and self.ads.stats_calls:
                raise KeyboardInterrupt()
        self.naver.tick = interrupt_second_batch
        with self.assertRaises(KeyboardInterrupt):
            I.run_inventory(self.reader(), self.st, self.fc.now)
        self.assertEqual(self.st.inventory_checks_on(self.fc.now().date())[A]["status"], "reading")
        self.st.close()
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.naver.tick = None
        self.fc.advance(180)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual((row["status"], row["yday_spend"]), ("ok", 201 * 20000))
        self.assertEqual(sum(len(chunk) for kind, chunk in self.ads.stats_calls if kind == "summary"), 201)

    def test_campaign_change_during_final_verification_does_not_publish_old_sum(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())], biz=10)
        def mutate_at_final_list(call):
            if call.path == "/ncc/campaigns" and self.ads.stats_calls:
                self.ads.add(A, [(2, "ELIGIBLE", False, steady(7, 3, 13, 1))], biz=10)
                self.naver.tick = None
        self.naver.tick = mutate_at_final_list
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual((row["status"], row["error_code"], row["yday_spend"]), ("retry", "CAMPAIGNS_CHANGED", None))
        self.fc.advance(180)
        I.run_inventory(self.reader(), self.st, self.fc.now)
        self.assertEqual(self.st.inventory_checks_on(self.fc.now().date())[A]["yday_spend"], 13)

    def test_final_response_over_deadline_does_not_expose_partial_totals(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())], biz=10)
        def late_final_list(call):
            if call.path == "/ncc/campaigns" and self.ads.stats_calls:
                self.fc.advance(20)
        self.naver.tick = late_final_list
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertNotEqual(row["status"], "ok")
        self.assertIsNone(row["yday_spend"])

    def test_run_budget_after_verified_batch_is_progress_not_failure(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())], biz=10)
        result = I.run_inventory(self.reader(), self.st, self.fc.now, max_calls=3)
        self.assertEqual(result.counts, {"partial": 1})
        self.assertIsNone(self.st.inventory_checks_on(self.fc.now().date())[A]["yday_spend"])

    def test_empty_list_becoming_nonempty_is_not_published_as_zero(self):
        self.st.record_accounts(kids(A), self.fc.now())
        self.ads.add(A, [], biz=10)
        def add_during_balance(call):
            if call.path == "/billing/bizmoney":
                self.ads.add(A, [(1, "ELIGIBLE", False, steady())], biz=10)
        self.naver.tick = add_during_balance
        I.run_inventory(self.reader(), self.st, self.fc.now)
        row = self.st.inventory_checks_on(self.fc.now().date())[A]
        self.assertEqual(row["status"], "retry")
        self.assertIsNone(row["yday_spend"])
