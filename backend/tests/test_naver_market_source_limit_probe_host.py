"""The new probe fits the unchanged reviewed transport and rejects altered input."""
import builtins
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock

import naver_market_source_limit_probe_host as H


class MarketProbeDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        here = Path(__file__).resolve()
        if here.parent.name == 'tests':
            cls.root = here.parents[2]
            cls.folder = cls.root / 'backend/tools'
        else:
            cls.root = next(p for p in here.parents if (p / 'work/naver-claude-reference-ops-20261011').is_dir()) / 'work/naver-claude-reference-ops-20261011'
            cls.folder = here.parent
        cls.core = (cls.folder / 'naver_market_source_limit_probe.py').read_bytes()
        cls.host = (cls.folder / 'naver_market_source_limit_probe_host.py').read_bytes()
        cls.sources = {role: (cls.root / path).read_bytes() for role, path in H.SOURCE_FILES.items()}

    def test_exact_new_packet_roundtrip_original_limits(self):
        self.assertEqual((H.MAX_CORE, H.MAX_HOST, H.MAX_SOURCE, H.MAX_JSON, H.MAX_WIRE, H.MAX_RESULT, H.DECODER_MEMORY),
                         (32768, 32768, 65536, 131072, 65536, 4096, 33554432))
        wire = H.encode(self.core, self.sources, self.host)
        result = H.decode(wire)
        self.assertEqual(result['core'].encode(), self.core)
        self.assertEqual(result['host'].encode(), self.host)
        self.assertEqual({k: v.encode() for k, v in result['sources'].items()}, self.sources)
        self.assertLessEqual(len(wire), H.MAX_WIRE)
        self.assertEqual(hashlib.sha256(self.core).hexdigest(), H.CORE_SHA256)

    def test_different_core_or_historical_source_refused_before_execution(self):
        with self.assertRaisesRegex(ValueError, 'CORE_CHANGED'):
            H.encode(self.core + b'\n', self.sources, self.host)
        for role in self.sources:
            altered = dict(self.sources); altered[role] += b'\n'
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
                H.encode(self.core, altered, self.host)

    def test_actual_pinned_closed_projection_survives_host_contract(self):
        observations = []
        def execute_with_readonly_fixture(code, namespace):
            builtins.exec(code, namespace)
            # Only the operating read is replaced. The pinned compiler and actual
            # closed_json implementation execute unchanged through host.run.
            def fixture(_sources):
                value = dict(version=1, diagnostic='market-source-limit-readonly-probe',
                             ok=False, phase='pins', operating_receipt_match=False,
                             source_pins_match=True, original_verify_error=None,
                             probe=namespace['empty_probe']())
                observations.append(value)
                return value
            namespace['diagnose'] = fixture
        with mock.patch.object(H, 'exec', execute_with_readonly_fixture, create=True):
            result = H.run(self.core, self.sources)
        self.assertEqual(len(observations), 1)
        self.assertTrue(result['transport_ok'])
        self.assertIsNone(result['error_code'])
        self.assertEqual(result['result'], observations[0])
        self.assertFalse(result['result']['probe']['database_opened'])

    def test_extra_source_and_duplicate_json_refused(self):
        extra = dict(self.sources); extra['unreviewed'] = b'pass'
        with self.assertRaisesRegex(ValueError, 'SOURCES_SHAPE'):
            H.encode(self.core, extra, self.host)
        with self.assertRaisesRegex(ValueError, 'PACKAGE_JSON'):
            H.strict_json('{"version":1,"version":1}')


if __name__ == '__main__':
    unittest.main()
