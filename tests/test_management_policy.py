"""실관리 수집 정책: 공개 판정만 검사하며 저장소나 원천 API를 호출하지 않는다."""
from datetime import date, datetime, timedelta, timezone
from dataclasses import FrozenInstanceError
import unittest

from naver_engine import management as M


class ManagementPolicyTest(unittest.TestCase):
    def classify(self, **changes):
        values = dict(stage="진행중", stage_revision="stage-1", matched=True,
                      authority_valid=True, source_current=True)
        values.update(changes)
        return M.classify(**values)

    def test_four_management_stages_are_daily_even_with_spacing(self):
        for stage in ("진행중", "사후 관리", "전략관리", "재계약 진행 중"):
            with self.subTest(stage=stage):
                decision = self.classify(stage=stage)
                self.assertEqual(decision.cadence, "daily")
                self.assertTrue(decision.attributable)
                self.assertEqual(decision.reason, "MANAGED_STAGE")

    def test_known_nonmanagement_stages_are_weekly(self):
        for stage in ("환불중", "홀딩 중", "환불 완료", "계약만료", "계약대기"):
            with self.subTest(stage=stage):
                decision = self.classify(stage=stage)
                self.assertEqual(decision.cadence, "weekly")
                self.assertTrue(decision.attributable)
                self.assertEqual(decision.reason, "NONMANAGED_STAGE")

    def test_unpaired_agency_accounts_are_weekly_without_erp_attribution(self):
        for stage in (None, "진행중", "계약만료"):
            with self.subTest(stage=stage):
                decision = self.classify(matched=False, stage=stage, stage_revision=None)
                self.assertEqual(decision.cadence, "weekly")
                self.assertFalse(decision.attributable)
                self.assertEqual(decision.reason, "UNMATCHED_ACCOUNT")

    def test_historical_exclusion_does_not_override_system_daily_stage(self):
        excluded = self.classify(excluded_revision="stage-1")
        self.assertEqual(excluded.cadence, "daily")
        self.assertEqual(excluded.reason, "MANAGED_STAGE")
        self.assertTrue(excluded.attributable)
        restored = self.classify(stage="사후관리", stage_revision="stage-2",
                                 excluded_revision="stage-1")
        self.assertEqual(restored.cadence, "daily")
        self.assertEqual(restored.reason, "MANAGED_STAGE")

    def test_invalid_authority_or_stale_source_blocks_every_cadence(self):
        for changes, reason in ((dict(authority_valid=False), "AUTHORITY_INVALID"),
                                (dict(source_current=False), "SOURCE_STALE")):
            for matched in (True, False):
                with self.subTest(changes=changes, matched=matched):
                    decision = self.classify(matched=matched, **changes)
                    self.assertEqual(decision.cadence, "blocked")
                    self.assertFalse(decision.attributable)
                    self.assertEqual(decision.reason, reason)

    def test_unconfirmed_stage_is_weekly_without_company_attribution(self):
        for changes in (dict(stage=None), dict(stage=" \t")):
            with self.subTest(changes=changes):
                decision = self.classify(**changes)
                self.assertEqual(decision.cadence, "weekly")
                self.assertEqual(decision.reason, "UNKNOWN_STAGE")
                self.assertFalse(decision.attributable)

    def test_known_stage_without_revision_cannot_apply_a_management_override(self):
        decision = self.classify(stage_revision=None)
        self.assertEqual(decision.cadence, "blocked")
        self.assertFalse(decision.attributable)

    def test_non_boolean_authority_inputs_are_rejected_instead_of_truthy(self):
        for field in ("matched", "authority_valid", "source_current"):
            for value in (1, "false", None):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.classify(**{field: value})

    def test_daily_period_uses_the_completed_korean_calendar_day(self):
        at = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
        period = M.period_for("daily", at)
        self.assertEqual(period.cycle_day, date(2026, 10, 4))
        self.assertEqual((period.since, period.until), (date(2026, 10, 3), date(2026, 10, 3)))
        self.assertEqual(M.period_for("daily", date(2026, 10, 4)), period)

    def test_weekly_period_is_frozen_from_sunday_through_saturday(self):
        expected = (date(2026, 10, 4), date(2026, 9, 27), date(2026, 10, 3))
        for offset in range(7):
            with self.subTest(offset=offset):
                period = M.period_for("weekly", date(2026, 10, 4) + timedelta(days=offset))
                self.assertEqual((period.cycle_day, period.since, period.until), expected)
        next_week = M.period_for("weekly", date(2026, 10, 11))
        self.assertEqual((next_week.cycle_day, next_week.since, next_week.until),
                         (date(2026, 10, 11), date(2026, 10, 4), date(2026, 10, 10)))

    def test_weekly_automatic_start_is_only_sunday_from_korean_midnight(self):
        decision = self.classify(stage="홀딩중")
        midnight = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
        self.assertFalse(M.is_due(decision, midnight - timedelta(seconds=1)))
        self.assertTrue(M.is_due(decision, midnight))
        self.assertTrue(M.is_due(decision, date(2026, 10, 4)))
        self.assertFalse(M.is_due(decision, date(2026, 10, 5)))

    def test_unfinished_weekly_cycle_resumes_monday_but_not_an_old_cycle(self):
        decision = self.classify(stage="환불완료")
        sunday = date(2026, 10, 4)
        monday = sunday + timedelta(days=1)
        self.assertTrue(M.is_due(decision, monday, started_cycle=sunday))
        self.assertFalse(M.is_due(decision, monday, started_cycle=sunday - timedelta(days=7)))

    def test_completed_weekly_cycle_does_not_repeat_until_next_sunday(self):
        decision = self.classify(stage="계약만료")
        sunday = date(2026, 10, 4)
        for offset in range(7):
            with self.subTest(offset=offset):
                self.assertFalse(M.is_due(decision, sunday + timedelta(days=offset),
                                          started_cycle=sunday, completed_cycle=sunday))
        self.assertTrue(M.is_due(decision, sunday + timedelta(days=7), completed_cycle=sunday))

    def test_daily_runs_each_calendar_day_and_reclassifies_after_stage_transition(self):
        monday = date(2026, 10, 5)
        daily = self.classify()
        self.assertTrue(M.is_due(daily, monday))
        self.assertFalse(M.is_due(daily, monday, completed_cycle=monday))
        self.assertTrue(M.is_due(daily, monday + timedelta(days=1), completed_cycle=monday))
        weekly = self.classify(stage="환불중", stage_revision="stage-2")
        self.assertFalse(M.is_due(weekly, monday))
        self.assertTrue(M.is_due(self.classify(stage_revision="stage-3"), monday))

    def test_blocked_authority_cannot_continue_an_already_started_sunday_cycle(self):
        sunday = date(2026, 10, 4)
        decision = self.classify(authority_valid=False)
        self.assertFalse(M.is_due(decision, sunday, started_cycle=sunday))
        self.assertFalse(M.is_due(decision, sunday + timedelta(days=1), started_cycle=sunday))

    def test_naive_timestamps_unknown_cadences_and_non_dates_are_rejected(self):
        for invalid in (datetime(2026, 10, 4), "2026-10-04", True, None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    M.period_for("daily", invalid)
                with self.assertRaises(ValueError):
                    M.is_due(self.classify(), invalid)
        for cadence in ("blocked", "monthly", "", None):
            with self.subTest(cadence=cadence):
                with self.assertRaises(ValueError):
                    M.period_for(cadence, date(2026, 10, 4))

    def test_cycle_evidence_must_be_a_date_for_that_cadence_and_not_the_future(self):
        sunday = date(2026, 10, 4)
        decision = self.classify(stage="홀딩중")
        for cycle in ("2026-10-04", datetime(2026, 10, 4, tzinfo=timezone.utc),
                      date(2026, 10, 3), date(2026, 10, 11)):
            for field in ("started_cycle", "completed_cycle"):
                with self.subTest(cycle=cycle, field=field):
                    with self.assertRaises(ValueError):
                        M.is_due(decision, sunday, **{field: cycle})

    def test_invalid_stage_or_revision_types_are_rejected(self):
        for changes in (dict(stage=1), dict(stage_revision=1), dict(stage_revision=" \t"),
                        dict(excluded_revision=False), dict(excluded_revision="")):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.classify(**changes)

    def test_decisions_and_periods_cannot_be_mutated_after_selection(self):
        decision = self.classify()
        period = M.period_for("weekly", date(2026, 10, 4))
        with self.assertRaises(FrozenInstanceError):
            decision.cadence = "weekly"
        with self.assertRaises(FrozenInstanceError):
            period.since = date(2026, 10, 1)

    def test_periods_include_leap_day_and_cross_year_without_current_day(self):
        leap = M.period_for("weekly", date(2024, 3, 3))
        self.assertEqual((leap.since, leap.until), (date(2024, 2, 25), date(2024, 3, 2)))
        year = M.period_for("weekly", date(2027, 1, 3))
        self.assertEqual((year.since, year.until), (date(2026, 12, 27), date(2027, 1, 2)))
        daily = M.period_for("daily", date(2024, 3, 1))
        self.assertEqual((daily.since, daily.until), (date(2024, 2, 29), date(2024, 2, 29)))

    def test_historical_inclusion_does_not_override_system_weekly_stage(self):
        included = self.classify(stage="환불완료", included_revision="stage-1")
        self.assertEqual((included.cadence, included.reason), ("weekly", "NONMANAGED_STAGE"))
        self.assertEqual(self.classify(stage="환불완료", included_revision="old-stage").cadence, "weekly")
        self.assertEqual(self.classify(matched=False, included_revision="stage-1").cadence, "weekly")
        unknown = self.classify(stage=None, included_revision="stage-1")
        self.assertEqual(unknown.cadence, "weekly")
        self.assertFalse(unknown.attributable)
        self.assertEqual(self.classify(included_revision="stage-1", excluded_revision="stage-1").cadence,
                         "daily")
