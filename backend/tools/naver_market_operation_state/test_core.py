"""New local boundaries. O_PATH is mocked on macOS; not a Linux qualification."""
import ast
import contextlib
import copy
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SOURCE = HERE / ('core.py' if (HERE / 'core.py').exists() else 'operation_state_readonly.py')
SPEC = importlib.util.spec_from_file_location('readonly_under_test', SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

def raw(role='original_reader', **changes):
    values = dict(LoadState='loaded', UnitFileState='static',
        FragmentPath=M.UNIT_ROOT + '/' + M.UNITS[role], DropInPaths='', Job='',
        Result='exit-code', ExecMainStatus='1', ActiveState='failed', SubState='failed',
        InvocationID='1234567890abcdef1234567890abcdef')
    values.update(changes)
    return ('\n'.join(k + '=' + values[k] for k in M._properties(role)) + '\n').encode()

def absent():
    v = M._file_empty('absent')
    v.update(presence='absent', stable=True)
    return v

def complete():
    v = M._base()
    v['refusal'] = 'none'
    for role in M.UNITS:
        first = M._parse_show(raw(role), role)
        second = M._parse_show(raw(role), role)
        v['units'][role] = M._unit_pair(first, second)
    v['files'] = {r: absent() for r in M.FILES}
    return M._finish(v)

@contextlib.contextmanager
def host_seam():
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(M.sys, 'platform', 'linux'))
        stack.enter_context(patch.object(M.os, 'geteuid', return_value=0))
        stack.enter_context(patch.object(M.os, 'O_PATH', getattr(os, 'O_PATH', os.O_RDONLY), create=True))
        stack.enter_context(patch.object(M.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_uid=65534)))
        yield

@contextlib.contextmanager
def filesystem_seam(folder, role='code_market', kind='regular', mode=0o644):
    """Real temp FS, virtual / and local owner check; explicitly not kernel O_PATH."""
    original_open, original_stat = os.open, os.stat
    root = str(Path(folder))
    def opened(path, flags, *args, **kwargs):
        return original_open(root if path == '/' and 'dir_fd' not in kwargs else path, flags, *args, **kwargs)
    def stated(path, *args, **kwargs):
        return original_stat(root if path == '/' and 'dir_fd' not in kwargs else path, *args, **kwargs)
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(M, 'FILES', {role: ('/safe/leaf', kind, mode, 'root')}))
        stack.enter_context(patch.object(M.os, 'O_PATH', os.O_RDONLY, create=True))
        stack.enter_context(patch.object(M.os, 'open', side_effect=opened))
        stack.enter_context(patch.object(M.os, 'stat', side_effect=stated))
        stack.enter_context(patch.object(M, '_safe_parent', side_effect=lambda v:
            stat.S_ISDIR(v.st_mode) and v.st_uid == os.getuid() and not stat.S_IMODE(v.st_mode) & 0o022))
        yield

class LocalBoundaries(unittest.TestCase):
    def test_exact_fixed_scope_and_no_mutating_calls(self):
        self.assertEqual(len(M.UNITS), 5)
        self.assertEqual(len(M.FILES), 22)
        self.assertEqual(M.FILES['pair_reservation'][0], M.LEDGER + '/identities/' + M.APPLY + '.json')
        self.assertEqual(M.FILES['output_directory'][1:], ('directory', 0o750, 'nobody'))
        tree = ast.parse(SOURCE.read_text())
        imports = {x.names[0].name for x in ast.walk(tree) if isinstance(x, ast.Import)}
        self.assertFalse(imports & {'transition', 'journal', 'provisioning', 'current_guard', 'sqlite3'})
        forbidden = {'write', 'fsync', 'mkdir', 'chmod', 'chown', 'unlink', 'remove', 'rename',
                     'replace', 'link', 'symlink', 'listdir', 'scandir', 'read_text', 'read_bytes'}
        calls = {x.func.attr for x in ast.walk(tree) if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)}
        self.assertFalse(calls & forbidden)
        self.assertEqual(len(__import__('inspect').signature(M.observe).parameters), 0)

    def test_invocation_categories_no_identifiers_escape(self):
        cases = [('', 'empty'), ('0'*32, 'zero32'), ('a'*32, 'lower_hex32'),
                 ('A'*32, 'upper_hex32'), ('Aa'*16, 'other'), ('bad value', 'other')]
        for value, expected in cases:
            with self.subTest(expected=expected):
                projected, private = M._parse_show(raw(InvocationID=value), 'original_reader')
                self.assertEqual(projected['invocation_format'], expected)
                self.assertEqual(private['InvocationID'], value)
                self.assertNotIn('InvocationID', projected)
        self.assertEqual(M._invocation(None), 'missing')

    def test_timer_nine_and_service_ten_without_defaults(self):
        timer, _ = M._parse_show(raw('original_timer'), 'original_timer')
        self.assertEqual(timer['exit_kind'], 'absent_by_kind')
        self.assertIsNone(timer['exit_status'])
        for text, kind in [('', 'empty'), ('-1', 'invalid'), ('256', 'invalid'), ('true', 'invalid')]:
            value, _ = M._parse_show(raw(ExecMainStatus=text), 'original_reader')
            self.assertEqual(value['exit_kind'], kind)
            self.assertIsNone(value['exit_status'])
        value, _ = M._parse_show(raw().replace(b'ExecMainStatus=1\n', b''), 'original_reader')
        self.assertEqual((value['issue'], value['exit_kind']), ('schema_missing', 'missing'))

    def test_schema_duplicate_extra_control_and_size(self):
        cases = [(raw()+b'Result=success\n', 'schema_duplicate'),
                 (raw()+b'Secret=value\n', 'schema_extra'),
                 (raw().replace(b'loaded', b'lo\taded'), 'schema_invalid'),
                 (b'x'*4097, 'command_size')]
        for body, issue in cases:
            with self.subTest(issue=issue), self.assertRaises(M.Fault) as cm:
                M._parse_show(body, 'original_reader')
            self.assertEqual(cm.exception.issue, issue)

    def test_fixed_fragment_and_unknown_values_closed(self):
        value, _ = M._parse_show(raw(FragmentPath=M.MASK_ROOT+'/'+M.UNITS['original_reader'],
            DropInPaths='/private/raw', Result='SECRET', Job='9 /org/freedesktop/systemd1/job/9'),
            'original_reader')
        self.assertEqual(value['fragment'], 'exact_owned_control_mask')
        self.assertEqual(value['result'], 'unknown')
        self.assertEqual(value['dropins'], 'nonempty')
        self.assertEqual(value['job'], 'present')
        self.assertNotIn('SECRET', str(value))
        self.assertNotIn('/private', str(value))

    def test_before_after_changes_and_initial_failure_not_hidden(self):
        a = M._parse_show(raw(), 'original_reader')
        b = M._parse_show(raw(InvocationID='b'*32), 'original_reader')
        paired = M._unit_pair(a, b)
        self.assertEqual(paired['issue'], 'changed')
        self.assertIs(paired['invocation_same'], False)
        okay = M._parse_show(raw(), 'original_reader')
        paired = M._unit_pair((M._unit_empty('original_reader', 'command_timeout'), None), okay)
        self.assertEqual(paired['issue'], 'command_timeout')
        self.assertIsNone(paired['state_same'])

    def test_strict_result_extra_roles_types_and_enums(self):
        valid = complete()
        self.assertEqual(M.validate(valid), valid)
        for mutate in [
            lambda x: x.update(secret='raw'),
            lambda x: x['files'].update(other=absent()),
            lambda x: x['units']['original_reader'].update(exit_status=True),
            lambda x: x['units']['original_reader'].update(invocation_format='a'*32),
            lambda x: x.update(version=True),
            lambda x: x['files']['code_market'].update(stable=1),
            lambda x: x.update(summary='public_trace_observed'),
        ]:
            value = copy.deepcopy(valid)
            mutate(value)
            with self.assertRaises(ValueError): M.closed_json(value)

    def test_closed_result_contains_no_pair_path_invocation_or_raw(self):
        body = M.closed_json(complete())
        self.assertLessEqual(len(body), M.MAX_JSON)
        for forbidden in (M.APPLY, M.ROLLBACK, '/var/', '/etc/', '/opt/',
                          '1234567890abcdef1234567890abcdef', 'InvocationID'):
            self.assertNotIn(forbidden, body)

    def test_observe_fixed_sequence_and_no_writes(self):
        sequence = []
        def show(role, deadline):
            sequence.append(('show', role))
            return M._parse_show(raw(role), role)
        def metadata(role, uid, deadline):
            sequence.append(('file', role))
            self.assertEqual(uid, 65534)
            return absent(), ('absent',)
        with host_seam(), patch.object(M, '_show', side_effect=show), patch.object(M, '_metadata_once', side_effect=metadata), contextlib.ExitStack() as stack:
            for name in ('fsync', 'write', 'mkdir', 'unlink', 'chmod', 'chown', 'link'):
                stack.enter_context(patch.object(M.os, name, side_effect=AssertionError('mutation')))
            value = M.observe()
        self.assertEqual(value['state'], 'observed_stable')
        self.assertEqual(sequence, [('show', r) for r in M.UNITS]+[('file', r) for r in M.FILES]*2+[('show', r) for r in M.UNITS])
        M.validate(value)

    def test_global_deadline_interrupts_filesystem_seam(self):
        with host_seam(), patch.object(M, 'GLOBAL_SECONDS', 0.06), patch.object(M, '_show',
            side_effect=lambda role, end: M._parse_show(raw(role), role)), patch.object(
                M, '_metadata_once', side_effect=lambda *_: time.sleep(2)):
            start = time.monotonic()
            value = M.observe()
        self.assertLess(time.monotonic()-start, 0.5)
        self.assertEqual(value['refusal'], 'global_deadline')
        M.validate(value)

    def test_unsupported_host_refuses_before_reads(self):
        with patch.object(M.sys, 'platform', 'darwin'), patch.object(M, '_show', side_effect=AssertionError()), patch.object(M.pwd, 'getpwnam', side_effect=AssertionError()):
            value = M.observe()
        self.assertEqual(value['refusal'], 'platform')
        M.validate(value)

    def test_command_argv_and_cap_during_live_subprocess(self):
        real = subprocess.Popen
        captured = []
        def spawn(argv, **kwargs):
            captured.append((argv, kwargs.copy()))
            return real([sys.executable, '-I', '-B', '-c',
                         "import os,time; os.write(1,b'x'*4097); time.sleep(2)"], **kwargs)
        with patch.object(M.subprocess, 'Popen', side_effect=spawn):
            start = time.monotonic()
            with self.assertRaises(M.Fault) as cm:
                M._run_show('original_timer', time.monotonic()+3)
        self.assertEqual(cm.exception.issue, 'command_size')
        self.assertLess(time.monotonic()-start, 1.5)
        argv, kwargs = captured[0]
        self.assertEqual(argv, ['/usr/bin/systemctl', 'show', M.UNITS['original_timer']] +
                         ['--property='+p for p in M.TIMER_PROPERTIES])
        self.assertEqual(kwargs['env'], M.ENV)
        self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)

    def test_command_timeout_and_nonzero_closed(self):
        real = subprocess.Popen
        for code, expected in [("import time; time.sleep(2)", 'command_timeout'),
                               ("raise SystemExit(3)", 'command_failed')]:
            with self.subTest(expected=expected), patch.object(M, 'COMMAND_SECONDS', .1), patch.object(
                M.subprocess, 'Popen', side_effect=lambda argv, **kw:
                    real([sys.executable, '-I', '-B', '-c', code], **kw)):
                with self.assertRaises(M.Fault) as cm:
                    M._run_show('original_reader', time.monotonic()+2)
                self.assertEqual(cm.exception.issue, expected)

    def test_metadata_absent_and_hardlink_two_mocked_opath(self):
        with tempfile.TemporaryDirectory() as tmp:
            safe = Path(tmp)/'safe'
            safe.mkdir(mode=0o700)
            with filesystem_seam(tmp):
                value = M._metadata_pair('code_market', None, time.monotonic()+2)
                self.assertEqual(value['presence'], 'absent')
            leaf = safe/'leaf'
            leaf.write_bytes(b'fixture only')
            leaf.chmod(0o644)
            os.link(leaf, safe/'private')
            with filesystem_seam(tmp):
                value = M._metadata_pair('code_market', None, time.monotonic()+2)
            self.assertEqual(value['links'], 'two')
            self.assertTrue(value['stable'])
            self.assertEqual(value['issue'], 'none' if os.getuid() == 0 else 'owner_mismatch')

    def test_metadata_symlink_parent_and_nonmask_leaf_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp)/'real'
            real.mkdir(mode=0o700)
            (Path(tmp)/'safe').symlink_to(real)
            with filesystem_seam(tmp):
                value = M._metadata_pair('code_market', None, time.monotonic()+2)
            self.assertEqual(value['issue'], 'unsafe_parent')
            (Path(tmp)/'safe').unlink()
            (Path(tmp)/'safe').mkdir(mode=0o700)
            (Path(tmp)/'safe'/'leaf').symlink_to('/dev/null')
            with filesystem_seam(tmp):
                value = M._metadata_pair('code_market', None, time.monotonic()+2)
            self.assertEqual(value['issue'], 'unsafe_type')

    def test_metadata_mask_readlink_and_race_mocked_opath(self):
        with tempfile.TemporaryDirectory() as tmp:
            safe = Path(tmp)/'safe'
            safe.mkdir(mode=0o700)
            (safe/'leaf').symlink_to('/dev/null')
            with filesystem_seam(tmp, 'mask_reader', 'symlink', 0o777):
                value = M._metadata_pair('mask_reader', None, time.monotonic()+2)
            self.assertEqual(value['kind'], 'symlink')
            self.assertTrue(value['stable'])
            first, second = absent(), absent()
            with patch.object(M, '_metadata_once', side_effect=[(first, ('a',)), (second, ('b',))]):
                value = M._metadata_pair('code_market', None, time.monotonic()+2)
            self.assertEqual(value['issue'], 'changed')

    def test_metadata_initial_error_not_hidden(self):
        with patch.object(M, '_metadata_once', side_effect=[
            (M._file_empty('permission_denied'), None), (absent(), ('absent',))]):
            value = M._metadata_pair('code_market', None, time.monotonic()+2)
        self.assertEqual(value['issue'], 'permission_denied')
        self.assertIsNone(value['stable'])

    def test_partial_observation_does_not_claim_absence(self):
        value = complete()
        value['units']['original_reader']['state_same'] = None
        value = M._finish(value)
        self.assertEqual(value['state'], 'partial_observation')
        self.assertEqual(value['summary'], 'undetermined')

    def test_all_files_before_after_detects_later_role_change(self):
        seen = []
        def metadata(role, uid, deadline):
            changed = role == 'preparation' and bool(seen)
            seen.append(role)
            return absent(), ('changed' if changed else 'initial',)
        with host_seam(), patch.object(M, '_show', side_effect=lambda r, d:
                M._parse_show(raw(r), r)), patch.object(M, '_metadata_once', side_effect=metadata):
            value = M.observe()
        self.assertEqual(value['files']['preparation']['issue'], 'changed')
        self.assertEqual(value['state'], 'context_changed')
        M.validate(value)

    def test_result_metadata_and_timer_contradictions_rejected(self):
        for mutate in [
            lambda v: v['files']['code_market'].update(kind='regular'),
            lambda v: v['files']['code_market'].update(stable=False),
            lambda v: v['files']['code_market'].update(issue='none'),
            lambda v: v['units']['original_timer'].update(exit_kind='valid', exit_status=0),
            lambda v: v['units']['original_reader'].update(exit_kind='absent_by_kind', exit_status=None),
        ]:
            value = complete()
            mutate(value)
            with self.assertRaises(ValueError): M.validate(value)

if __name__ == '__main__':
    unittest.main()

