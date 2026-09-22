"""Offline pacing behavior, serialized recovery and invalid-input boundaries."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector_pacing import update


class CollectorPacingTests(unittest.TestCase):
    def success(self, state=None, duration=30, count=1, base=40):
        return update(state, duration_seconds=duration, action_count=count,
                      outcome="success", base_interval=base)

    def test_slower_per_action_duration_increases_wait(self):
        normal = self.success(duration=120, count=4)
        slower = self.success(normal, duration=480, count=4)
        self.assertEqual(normal["intervalSeconds"], 40)
        self.assertGreater(slower["intervalSeconds"], normal["intervalSeconds"])
        self.assertLessEqual(slower["intervalSeconds"], 160)

    def test_gradual_recovery_never_accelerates_below_approved_base(self):
        state = self.success(duration=160)
        waits = [state["intervalSeconds"]]
        for _ in range(12):
            state = self.success(state, duration=0)
            waits.append(state["intervalSeconds"])
        self.assertGreater(waits[1], 40)
        self.assertLess(waits[1], waits[0])
        self.assertEqual(waits, sorted(waits, reverse=True))
        self.assertEqual(waits[-1], 40)

    def test_transient_penalty_survives_json_and_recovers_gradually(self):
        state = update(outcome="transient_error", base_interval=40)
        self.assertEqual(state["intervalSeconds"], 80)
        restored = json.loads(json.dumps(state, allow_nan=False))
        second = update(restored, outcome="transient_error", base_interval=40)
        self.assertEqual(second["intervalSeconds"], 160)
        recovered = self.success(second)
        self.assertEqual(recovered["intervalSeconds"], 120)
        self.assertFalse(recovered["paused"])

    def test_repeated_errors_and_very_slow_jobs_are_bounded(self):
        state = None
        for _ in range(20):
            state = update(state, outcome="transient_error", base_interval=40)
        self.assertEqual(state["intervalSeconds"], 160)
        slow = self.success(duration=1e308)
        self.assertEqual(slow["intervalSeconds"], 160)
        json.dumps(slow, allow_nan=False)

    def test_paused_outcomes_never_automatically_resume(self):
        for outcome in ["unknown", "blocked", "auth", "schema", "PAUSED_BLOCK", "unexpected"]:
            with self.subTest(outcome=outcome):
                state = update(outcome=outcome, base_interval=40)
                restored = json.loads(json.dumps(state))
                for _ in range(10):
                    restored = self.success(restored, duration=0)
                self.assertTrue(restored["paused"])
                self.assertEqual(restored["pauseReason"], state["pauseReason"])
                self.assertEqual(restored["intervalSeconds"], 160)

    def test_invalid_metrics_pause_without_nan_or_infinite_state(self):
        for duration, count in [(float("nan"), 1), (float("inf"), 1), (-1, 1),
                                (None, 1), (1, 0), (1, -1), (1, True), (1, 1.5),
                                (10 ** 1000, 1), (1, 10 ** 1000)]:
            with self.subTest(duration=duration, count=count):
                result = self.success(duration=duration, count=count)
                self.assertTrue(result["paused"])
                self.assertEqual(result["intervalSeconds"], 160)
                json.dumps(result, allow_nan=False)

    def test_invalid_persisted_state_fails_closed(self):
        for state in [{}, [], {**self.success(), "penalty": float("nan")},
                      {**self.success(), "paused": "false"}]:
            with self.subTest(state=state):
                result = self.success(state)
                self.assertTrue(result["paused"])
                self.assertEqual(result["pauseReason"], "INVALID_PACING_STATE")
                json.dumps(result, allow_nan=False)

    def test_invalid_base_interval_cannot_issue_a_wait(self):
        for base in [0, -1, True, None, float("nan"), float("inf"), 1e308, 10 ** 1000]:
            with self.subTest(base=base):
                with self.assertRaisesRegex(ValueError, "INVALID_BASE_INTERVAL"):
                    self.success(base=base)

    def test_input_state_is_not_mutated_and_new_workers_start_at_same_base(self):
        first, second = self.success(), self.success()
        self.assertEqual(first["intervalSeconds"], second["intervalSeconds"])
        before = json.dumps(first, sort_keys=True)
        self.success(first, duration=120)
        self.assertEqual(json.dumps(first, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
