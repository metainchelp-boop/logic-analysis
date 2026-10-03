"""Authenticated runtime indicator: synthetic public WSGI, no external calls."""
import unittest
import pathlib
import shutil
import subprocess
from unittest.mock import patch

from naver_engine.tests import test_catalog_links as fixture
from naver_engine import web as WEB


class RuntimeStatusWebTest(unittest.TestCase):
    setUp = fixture.CatalogLinksTest.setUp
    call = fixture.CatalogLinksTest.call
    save_catalog = fixture.CatalogLinksTest.save_catalog
    pair = fixture.CatalogLinksTest.pair

    def status(self):
        return {"state": "collecting", "indicator": "green", "reason_code": "COLLECTING",
                "verified_at": self.clock.now().isoformat(), "valid_for_seconds": 25,
                "retry_at": None}

    def install(self, getter):
        self.app = WEB.App(open_read=self.app._open_read, write=self.app._write_fn,
            signer=self.signer, profiles=None, clock=self.clock.now,
            owner_verification=True, verified_linking=True, runtime_status=getter)

    def test_staff_and_representative_read_same_nonpersonal_live_status(self):
        self.install(self.status)
        for actor in (0, 100, 101):
            with self.subTest(actor=actor), patch.object(WEB.W, "health", side_effect=AssertionError("no board scan")):
                code, data = self.call("GET", "/health?runtime=1", actor)
                self.assertEqual(code, 200)
                self.assertEqual(data, {"runtime": self.status()})

    def test_missing_or_failed_status_is_red_not_an_http_health_failure(self):
        for getter in (None, lambda: (_ for _ in ()).throw(RuntimeError("secret"))):
            self.install(getter)
            code, data = self.call("GET", "/health?runtime=1")
            self.assertEqual(code, 200)
            self.assertEqual(data["runtime"]["indicator"], "red")
            self.assertEqual(data["runtime"]["state"], "unavailable")
            self.assertNotIn("secret", str(data))

    def test_malformed_callback_fails_closed_and_never_leaks_extra_fields(self):
        for changed in ({"indicator": "green", "state": "stopped"}, {"reason_code": "secret"},
                        {"valid_for_seconds": float("inf")}, {"valid_for_seconds": True},
                        {"verified_at": "yesterday"}, {"account_name": "private"}):
            with self.subTest(changed=changed):
                self.install(lambda: {**self.status(), **changed})
                code, data = self.call("GET", "/health?runtime=1")
                self.assertEqual(code, 200)
                self.assertEqual(data["runtime"]["indicator"], "red")
                self.assertNotIn("secret", str(data))
                self.assertNotIn("private", str(data))

    def test_validity_expired_is_red(self):
        self.install(lambda: {**self.status(), "valid_for_seconds": 0})
        self.assertEqual(self.call("GET", "/health?runtime=1")[1]["runtime"]["indicator"], "red")

    def test_nonstaff_cannot_read_or_invoke_getter(self):
        with patch.object(self, "status", side_effect=AssertionError("unauthorized getter")):
            self.install(self.status)
            self.assertIn(self.call("GET", "/health?runtime=1", 999)[0], (401, 403))

    def test_existing_health_payload_remains_and_bad_runtime_query_refused(self):
        self.install(self.status)
        with patch.object(WEB.W, "health", return_value={"ok": True, "runs": []}):
            self.assertEqual(self.call("GET", "/health"),
                (200, {"ok": True, "runs": [], "runtime": self.status()}))
        for query in ("runtime=0", "runtime=1&selection=all"):
            self.assertEqual(self.call("GET", "/health?" + query)[0], 400)


class RuntimeDisplayModelTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_display_state_and_expiry_contract(self):
        subprocess.run([shutil.which("node"), str(pathlib.Path(__file__).with_name("runtime_indicator_unit.js"))],
                       check=True, capture_output=True, text=True, timeout=10)
