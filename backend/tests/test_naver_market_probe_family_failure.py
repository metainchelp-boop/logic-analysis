"""Fixed first-failure role/type; fake filesystem, no actual source or DB."""
from contextlib import ExitStack
from pathlib import Path
import stat
import types
import unittest
from unittest.mock import patch
from test_naver_market_probe_preflight_phases import D, Fixture, diagnose_with_probe

FAMILY = D._file_family
ROLES = ('dir', 'main', 'wal', 'shm')

class FamilyFailureTests(unittest.TestCase):
    def run_family(self, role=None, kind=None):
        calls = []
        with Fixture() as f, ExitStack() as stack:
            directory = Path(f.plan['source_directory'])
            members = {directory: 'dir'}
            for suffix, r in zip(('', '-wal', '-shm'), ROLES[1:]):
                members[directory / (f.plan['database_name'] + suffix)] = r
            def lstat(path):
                r = members[path]; calls.append(('lstat', r))
                if r == role and kind in ('missing', 'denied', 'other'):
                    error = {'missing': FileNotFoundError, 'denied': PermissionError, 'other': RuntimeError}[kind]
                    raise error('SECRET /private/source/raw')
                info = types.SimpleNamespace(st_mode=(stat.S_IFDIR if r == 'dir' else stat.S_IFREG) | 0o600,
                    st_dev=1, st_ino=ROLES.index(r)+1, st_uid=0, st_gid=0, st_nlink=1)
                if r == role and kind == 'regular': info.st_mode = stat.S_IFLNK | 0o777
                if r == role and kind == 'link': info.st_nlink = 2
                return info
            def resolve(path):
                r = members[path]; calls.append(('resolve', r))
                return Path('/private/SECRET') if r == role and kind == 'path' else path
            stack.enter_context(patch.object(D, '_file_family', FAMILY))
            stack.enter_context(patch.object(Path, 'lstat', lstat))
            stack.enter_context(patch.object(Path, 'resolve', resolve))
            with patch.object(D.os, 'statvfs', side_effect=AssertionError('unexpected statvfs')), \
                 patch.object(D.os, 'access', side_effect=AssertionError('unexpected access')):
                try:
                    result = f.run(); error = None
                except D.ProbeStop as e:
                    error = e; result = None
            return error, result, calls, f.child.call_count

    def check_refusal(self, role, kind, expected):
        error, result, calls, child = self.run_family(role, kind)
        self.assertIsNone(result); self.assertEqual(child, 0)
        self.assertIs(type(error), D.ProbeStop)
        self.assertEqual(error.args, (expected,))
        self.assertTrue(error.__suppress_context__)
        self.assertNotIn('SECRET', str(error))
        for later in ROLES[ROLES.index(role)+1:]:
            self.assertFalse(any(r == later for op, r in calls), calls)
        return calls

    def test_missing_each_member_is_closed_and_shortcircuits(self):
        for role in ROLES:
            with self.subTest(role=role): self.check_refusal(role, 'missing', 'probe_family_'+role+'_missing')

    def test_permission_each_member_is_closed_and_shortcircuits(self):
        for role in ROLES:
            with self.subTest(role=role): self.check_refusal(role, 'denied', 'probe_family_'+role+'_denied')

    def test_nonregular_guards_preserved_for_directory_and_files(self):
        for role in ROLES:
            with self.subTest(role=role): self.check_refusal(role, 'regular', 'probe_family_'+role+'_guard')

    def test_hardlink_guards_preserved(self):
        for role in ROLES[1:]:
            with self.subTest(role=role): self.check_refusal(role, 'link', 'probe_family_'+role+'_guard')

    def test_resolved_alias_guards_preserved(self):
        for role in ROLES:
            with self.subTest(role=role): self.check_refusal(role, 'path', 'probe_family_'+role+'_guard')

    def test_unknown_exception_remains_generic_and_never_leaks(self):
        for role in ROLES:
            with self.subTest(role=role): self.check_refusal(role, 'other', 'probe_source_family')

    def test_success_has_original_calls_and_child_result(self):
        error, result, calls, child = self.run_family()
        self.assertIsNone(error); self.assertEqual(child, 1)
        self.assertEqual(result['status'], 'original_collect_passed')
        self.assertEqual(calls, [('resolve','dir'),('lstat','dir')] +
            [(op, r) for r in ROLES[1:] for op in ('lstat','resolve')])

    def test_all_twelve_phases_are_valid_and_keep_database_unopened(self):
        self.assertEqual(len(D.FAMILY_PHASES), 12)
        self.assertEqual(len(set(D.FAMILY_PHASES)), 12)
        for phase in D.FAMILY_PHASES:
            result = diagnose_with_probe(D.ProbeStop(phase))
            self.assertEqual(result['phase'], phase)
            self.assertFalse(result['probe']['database_opened'])
            self.assertEqual(result['probe']['collect_calls'], 0)
            self.assertLessEqual(len(D.closed_json(result).encode()), 4096)

    def test_unlisted_phase_and_forged_exception_rejected(self):
        class Forged(D.ProbeStop): pass
        for error in [Forged('probe_family_wal_missing'), D.ProbeStop('probe_family_wal_SECRET')]:
            result = diagnose_with_probe(error)
            self.assertEqual(result['phase'], 'probe')
            self.assertNotIn('SECRET', D.closed_json(result))
        result = diagnose_with_probe(D.ProbeStop('probe_family_wal_missing'), early=True)
        self.assertEqual(result['phase'], 'pins')
        result['phase'] = 'probe_family_wal_SECRET'
        with self.assertRaises(ValueError): D.closed_json(result)

    def test_preceding_failures_do_not_receive_family_labels(self):
        with Fixture('probe_interpreter_open') as f:
            f.open.side_effect = FileNotFoundError('SECRET')
            with self.assertRaisesRegex(D.ProbeStop, '^probe_interpreter_open$'): f.run()
            f.family.assert_not_called(); f.child.assert_not_called()

if __name__ == '__main__': unittest.main()
