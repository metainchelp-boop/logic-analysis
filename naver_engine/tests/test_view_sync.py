"""화면 변경분 모듈의 공개 응답 계약. 합성 객체만 사용한다."""
import unittest
import json
from datetime import datetime, timezone

from naver_engine import view_sync as VS


NOW = datetime(2026, 10, 3, 10, tzinfo=timezone.utc)


class ViewSyncTest(unittest.TestCase):
    def test_envelope_over_relay_limit_preserves_legacy_payload_without_cursor(self):
        payload = {"rows": [], "note": "x" * (VS.RESPONSE_MAX_BYTES-40)}
        self.assertLess(len(json.dumps(payload).encode()), VS.RESPONSE_MAX_BYTES)
        result = VS.ViewSync().respond("/accounts", payload, context="viewer", view_cursor=None, now=NOW)
        self.assertEqual(result, payload)
        self.assertNotIn("cursor", result)

    def test_expired_cursor_returns_a_fresh_full_response(self):
        clock = [0]
        cache = VS.ViewSync(ttl=10, monotonic=lambda: clock[0])
        payload = {"rows": [{"ad_account_no": "123", "amount": 1}]}
        first = cache.respond("/accounts", payload, context="viewer", view_cursor=None, now=NOW)
        clock[0] = 10
        result = cache.respond("/accounts", payload, context="viewer", view_cursor=first["cursor"], now=NOW)
        self.assertEqual(result["mode"], "full")
        self.assertIsNone(result["base_cursor"])
        self.assertEqual(result["data"], payload)

    def test_unusable_row_keys_never_return_unchanged_or_delta(self):
        for values in ([None], ["same", "same"], [True], [9007199254740992], [1.5], [""]):
            with self.subTest(values=values):
                cache = VS.ViewSync()
                payload = {"rows": [{"ad_account_no": value} for value in values]}
                first = cache.respond("/accounts", payload, context="viewer", view_cursor=None, now=NOW)
                result = cache.respond("/accounts", payload, context="viewer", view_cursor=first["cursor"], now=NOW)
                self.assertEqual(result["mode"], "full")
                self.assertIsNone(result["cursor"])

    def test_serialized_byte_limit_does_not_retain_oversized_snapshot(self):
        cache = VS.ViewSync(max_bytes=100)
        payload = {"rows": [{"ad_account_no": "123", "note": "한글" * 50}]}
        result = cache.respond("/accounts", payload, context="viewer", view_cursor=None, now=NOW)
        self.assertEqual(result["mode"], "full")
        self.assertIsNone(result["cursor"])
        self.assertEqual(result["data"], payload)

    def test_entry_limit_evicts_old_snapshots_without_losing_current_data(self):
        cache = VS.ViewSync(max_entries=1)
        payload = {"rows": [{"ad_account_no": "123"}]}
        first = cache.respond("/accounts", payload, context="first", view_cursor=None, now=NOW)
        cache.respond("/accounts", payload, context="second", view_cursor=None, now=NOW)
        result = cache.respond("/accounts", payload, context="first", view_cursor=first["cursor"], now=NOW)
        self.assertEqual(result["mode"], "full")
        self.assertEqual(result["data"], payload)

    def test_total_serialized_bytes_evict_even_below_entry_limit(self):
        cache = VS.ViewSync(max_entries=10, max_bytes=240)
        payload = {"rows": [{"ad_account_no": "123", "note": "x" * 70}]}
        first = cache.respond("/accounts", payload, context="first", view_cursor=None, now=NOW)
        self.assertIsNotNone(first["cursor"])
        second = cache.respond("/accounts", payload, context="second", view_cursor=None, now=NOW)
        self.assertIsNotNone(second["cursor"])
        result = cache.respond("/accounts", payload, context="first", view_cursor=first["cursor"], now=NOW)
        self.assertEqual(result["mode"], "full")

    def test_dashboard_correction_replaces_aggregate_and_cached_payload_is_detached(self):
        cache = VS.ViewSync()
        payload = {"totals": {"spend": 200}, "ready": True}
        first = cache.respond("/dashboard", payload, context="viewer", view_cursor=None, now=NOW)
        payload["totals"]["spend"] = 100
        result = cache.respond("/dashboard", payload, context="viewer", view_cursor=first["cursor"], now=NOW)
        self.assertEqual(result["mode"], "delta")
        self.assertEqual(result["data"], payload)
        self.assertIsNone(result["rows"])
        self.assertEqual(result["base_cursor"], first["cursor"])
