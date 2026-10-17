"""Only new fixture provenance checks; no namespace/DB or old probe test reruns."""
import ctypes
import json
import os
import types
import unittest
from unittest.mock import Mock, patch

import test_naver_market_source_limit_probe_namespace_provenance as F


class FixtureProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.p = F.Provenance()
        self.addCleanup(self.p.close)

    def test_core_pin_is_required_before_shared_observation(self):
        with patch.object(F, 'CORE_SHA256', '0' * 64), self.assertRaisesRegex(ValueError, '^FIXTURE_CORE_PIN$'):
            F.Provenance()

    def test_original_called_once_and_untrusted_error_text_not_serialized(self):
        private = 'private-fixture-string-not-for-output'
        call = Mock(side_effect=OSError(13, private))
        with self.assertRaises(OSError):
            self.p.wrap('connect', call)()
        call.assert_called_once_with()
        result = self.p.result()
        self.assertEqual(result['failure_stage'], 'connect')
        self.assertEqual(result['errno'], 13)
        self.assertNotIn(private, json.dumps(result))

    def test_actual_pinned_namespace_root_guard_maps_without_running_namespace(self):
        with patch.object(F.D.sys, 'platform', 'fixture'), self.assertRaises(F.D.ProbeStop):
            self.p.wrap('namespace', F.D._namespace)({}, {})
        result = self.p.result()
        self.assertEqual(result['failure_stage'], 'linux_root')
        self.assertTrue(result['fixed_namespace_frame'])
        self.assertIsNone(result['errno'])

    def test_pinned_unshare_failure_has_fixed_stage_and_kernel_errno(self):
        libc = types.SimpleNamespace(unshare=Mock(return_value=-1), mount=Mock())
        with patch.object(F.D.sys, 'platform', 'linux'), patch.object(F.D.os, 'geteuid', return_value=0), \
             patch.object(F.D, '_file_family', return_value={}), \
             patch.object(F.D.os, 'stat', return_value=types.SimpleNamespace(st_ino=1)), \
             patch.object(F.D.ctypes, 'CDLL', return_value=libc), \
             patch.object(F.D.os, 'O_PATH', 2097152, create=True), \
             patch.object(F.D.os, 'open', return_value=19), patch.object(F.D.os, 'close'):
            ctypes.set_errno(1)
            with self.assertRaises(F.D.ProbeStop):
                self.p.wrap('namespace', F.D._namespace)({'source_directory': '/fixture', 'database_name': 'fixture.db'}, {})
        result = self.p.result()
        self.assertEqual(result['failure_stage'], 'unshare')
        self.assertEqual(result['errno'], 1)
        libc.unshare.assert_called_once_with(131072 | 1073741824)
        libc.mount.assert_not_called()

    def test_first_failure_and_success_return_are_preserved(self):
        self.assertEqual(self.p.wrap('source_load', lambda: 7)(), 7)
        self.p.failed('connect', ValueError('private'))
        self.p.failed('collect', OSError(5, 'private'))
        result = self.p.result()
        self.assertEqual(result['failure_stage'], 'connect')
        self.assertEqual(result['passed'], ['source_load'])
        self.assertEqual(result['exception'], 'value')
        self.assertIsNone(result['errno'])

    @unittest.skipUnless(hasattr(os, 'fork'), 'fork transport is unavailable')
    def test_closed_integer_provenance_survives_child_exit(self):
        pid = os.fork()
        if pid == 0:
            self.p.failed('connect', OSError(30, 'private'))
            os._exit(0)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(status, 0)
        result = self.p.result()
        self.assertEqual(result['errno'], 30)
        self.assertEqual(result['failure_stage'], 'connect')


if __name__ == '__main__':
    unittest.main()
