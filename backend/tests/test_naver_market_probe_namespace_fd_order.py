"""Only the new namespace descriptor lifetime regression; no real mount or DB."""
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve()
CORE = HERE.with_name('naver_market_source_limit_probe.py')
if not CORE.is_file():
    CORE = HERE.parents[1] / 'tools/naver_market_source_limit_probe.py'
SPEC = importlib.util.spec_from_file_location('market_probe_namespace_fd_order', CORE)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)


class FixtureMountReached(Exception):
    pass


class NamespaceDescriptorOrderTests(unittest.TestCase):
    def run_namespace(self, unshare_result=0, identity_changes=True, open_error=None):
        events = []
        def unshare(flags):
            self.assertEqual(flags, 131072 | 1073741824)
            events.append('unshare')
            return unshare_result
        def open_directory(path, flags):
            events.append('open_current_namespace_directory')
            self.assertEqual(path, Path('/fixture'))
            self.assertEqual(flags, D.os.O_PATH | D.os.O_DIRECTORY | D.os.O_NOFOLLOW)
            if open_error is not None:
                raise open_error
            return 19
        def mount(*args):
            events.append('first_mount')
            self.assertEqual(args, (None, b'/', None, 1 << 18 | 16384, None))
            raise FixtureMountReached()
        def close(fd):
            self.assertEqual(fd, 19)
            events.append('close_directory')
        libc = types.SimpleNamespace(unshare=Mock(side_effect=unshare), mount=Mock(side_effect=mount))
        inodes = (1, 2, 3, 4) if identity_changes else (1, 2, 1)
        with ExitStack() as stack:
            for target, name, value in (
                (D.sys, 'platform', 'linux'), (D.os, 'geteuid', Mock(return_value=0)),
                (D, '_file_family', Mock(return_value={})),
                (D.os, 'stat', Mock(side_effect=[types.SimpleNamespace(st_ino=i) for i in inodes])),
                (D.ctypes, 'CDLL', Mock(return_value=libc)),
                (D.os, 'open', Mock(side_effect=open_directory)), (D.os, 'close', Mock(side_effect=close)),
            ):
                stack.enter_context(patch.object(target, name, value))
            stack.enter_context(patch.object(D.os, 'O_PATH', 2097152, create=True))
            try:
                D._namespace({'source_directory': '/fixture', 'database_name': 'fixture.db'}, {})
            except (D.ProbeStop, FixtureMountReached, OSError) as error:
                return events, type(error)
        self.fail('fixture must stop before any actual mount')

    def test_descriptor_opened_in_new_namespace_before_first_mount(self):
        events, error = self.run_namespace()
        self.assertIs(error, FixtureMountReached)
        self.assertEqual(events, ['unshare', 'open_current_namespace_directory', 'first_mount', 'close_directory'])

    def test_failed_unshare_never_opens_source_descriptor(self):
        events, error = self.run_namespace(unshare_result=-1)
        self.assertIs(error, D.ProbeStop)
        self.assertEqual(events, ['unshare'])

    def test_namespace_identity_guard_still_precedes_source_open(self):
        events, error = self.run_namespace(identity_changes=False)
        self.assertIs(error, D.ProbeStop)
        self.assertEqual(events, ['unshare'])

    def test_source_open_failure_has_no_mount_or_unowned_descriptor_close(self):
        events, error = self.run_namespace(open_error=PermissionError(13, 'fixture'))
        self.assertIs(error, PermissionError)
        self.assertEqual(events, ['unshare', 'open_current_namespace_directory'])

    def test_updated_pinned_provenance_identifies_source_bind(self):
        import ctypes
        import test_naver_market_source_limit_probe_namespace_provenance as F
        provenance = F.Provenance()
        self.addCleanup(provenance.close)
        libc = types.SimpleNamespace(unshare=Mock(return_value=0), mount=Mock(side_effect=[0, 0, -1]))
        with patch.object(F.D.sys, 'platform', 'linux'), patch.object(F.D.os, 'geteuid', return_value=0), \
             patch.object(F.D, '_file_family', return_value={}), \
             patch.object(F.D.os, 'stat', side_effect=[types.SimpleNamespace(st_ino=i) for i in (1, 2, 3, 4)]), \
             patch.object(F.D.ctypes, 'CDLL', return_value=libc), \
             patch.object(F.D.os, 'O_PATH', 2097152, create=True), \
             patch.object(F.D.os, 'open', return_value=19), patch.object(F.D.os, 'close'), \
             patch.object(F.D.Path, 'mkdir'):
            ctypes.set_errno(22)
            with self.assertRaises(F.D.ProbeStop):
                provenance.wrap('namespace', F.D._namespace)({'source_directory': '/fixture', 'database_name': 'fixture.db'}, {})
        result = provenance.result()
        self.assertEqual(result['failure_stage'], 'source_bind')
        self.assertEqual(result['errno'], 22)
        self.assertTrue(result['fixed_namespace_frame'])
        self.assertEqual(libc.mount.call_count, 3)


if __name__ == '__main__':
    unittest.main()
