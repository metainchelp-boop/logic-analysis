"""조직 수락본 신선도(설계 §9 · M12) — 3시간 넘으면 노랑 · 26시간 넘으면 올리기 멈춤 · 믿을 수 없는 미래는 낡음."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.naver_auto import org_snapshot as O

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=KST)
US = timedelta(microseconds=1)


class FreshnessTest(unittest.TestCase):
    def test_bands_and_edges(self):
        cases = (
            (None, O.FRESH_NONE),
            (NOW, O.FRESH_OK),
            (NOW - timedelta(hours=3), O.FRESH_OK),
            (NOW - timedelta(hours=3) - US, O.FRESH_YELLOW),
            (NOW - timedelta(hours=26), O.FRESH_YELLOW),
            (NOW - timedelta(hours=26) - US, O.FRESH_STALE),
            (NOW + O.FUTURE_TOLERANCE, O.FRESH_OK),
            (NOW + O.FUTURE_TOLERANCE + US, O.FRESH_STALE),
        )
        for gen, want in cases:
            self.assertEqual(O.org_freshness(gen, NOW), want, gen)

    def test_other_time_zone_is_the_same_moment(self):
        utc = (NOW - timedelta(hours=4)).astimezone(timezone.utc)
        self.assertEqual(O.org_freshness(utc, NOW), O.FRESH_YELLOW)

    def test_raising_only_when_fresh_or_yellow(self):
        allowed = {s for s in (O.FRESH_NONE, O.FRESH_OK, O.FRESH_YELLOW, O.FRESH_STALE, "", "FRESH", None)
                   if O.allows_raising(s)}
        self.assertEqual(allowed, {O.FRESH_OK, O.FRESH_YELLOW})

    def test_design_hours(self):
        self.assertEqual(O.ORG_YELLOW_AFTER, timedelta(hours=3))
        self.assertEqual(O.ORG_STALE_AFTER, timedelta(hours=26))

    def test_naive_or_wrong_types_are_caller_errors(self):
        for gen, now in ((NOW, NOW.replace(tzinfo=None)), (NOW.replace(tzinfo=None), NOW), ("2026-09-29", NOW),
                         (NOW, "지금")):
            with self.assertRaises(ValueError):
                O.org_freshness(gen, now)


if __name__ == "__main__":
    unittest.main()
