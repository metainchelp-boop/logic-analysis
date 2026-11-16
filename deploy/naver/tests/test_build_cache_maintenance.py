"""Synthetic command seams: never contact a Docker daemon or modify a cache."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('cache_maintenance', ROOT / 'deploy/naver/build_cache_maintenance.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
CANARY = 'secret-content-must-never-be-published'
CONTAINER = {'id': 'a' * 64, 'image': 'sha256:' + 'b' * 64,
             'running': True, 'pid': 321, 'started': '2026-11-02T15:00:00.000000000Z', 'restarts': 0}


class Docker:
    def __init__(self, active=0, drift=False, prune_exit=0, timeout=False):
        self.active = active
        self.drift = drift
        self.pruned = False
        self.prune_exit = prune_exit
        self.timeout = timeout
        self.calls = []

    def __call__(self, args, timeout=30):
        self.calls.append(tuple(args))
        if tuple(args) == M.DF:
            output = json.dumps({'Type': 'Build Cache', 'Active': str(self.active),
                'Size': '1GB' if self.pruned else '3.15GB',
                'Reclaimable': '0B' if self.pruned else '1.489GB (47%)',
                'TotalCount': '100' if self.pruned else '291'})
        elif tuple(args) == M.PS:
            output = CONTAINER['id'] + '\n'
        elif tuple(args)[:len(M.DOCKER) + 1] == (*M.DOCKER, 'inspect'):
            row = copy.deepcopy(CONTAINER)
            if self.pruned and self.drift:
                row['restarts'] += 1
            output = json.dumps(row)
        elif tuple(args) == M.PRUNE:
            self.pruned = True
            if self.timeout:
                raise subprocess.TimeoutExpired(args, timeout, output=CANARY, stderr=CANARY)
            return subprocess.CompletedProcess(args, self.prune_exit, CANARY.encode(), CANARY.encode())
        else:
            raise AssertionError('UNAPPROVED_COMMAND')
        return subprocess.CompletedProcess(args, 0, output.encode(), CANARY.encode())


class MaintenanceTest(unittest.TestCase):
    def plan(self, docker=None):
        return M.execute('plan', runner=docker or Docker(), free=lambda: 3340681216)

    def apply(self, docker=None, **kwargs):
        docker = docker or Docker()
        free = iter((3340681216, 4829681216))
        return M.execute('apply', kwargs.get('plan_sha', self.plan()['plan_sha256']),
                         kwargs.get('confirm', M.CONFIRM), runner=docker, free=lambda: next(free))

    def test_plan_has_no_prune_or_data_commands(self):
        docker = Docker()
        result = self.plan(docker)
        self.assertEqual(result['status'], 'planned')
        self.assertEqual(result['cache_reclaimable_before_bytes'], 1489000000)
        self.assertEqual(result['cache_size_before_bytes'], 3150000000)
        self.assertEqual(result['cache_count_before'], 291)
        self.assertFalse(result['prune_attempted'])
        self.assertNotIn(M.PRUNE, docker.calls)
        self.assertEqual(len(docker.calls), 3)

    def test_hash_bound_apply_exactly_one_fixed_prune_only(self):
        docker = Docker()
        result = self.apply(docker)
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(result['free_change_bytes'], 1489000000)
        self.assertTrue(result['container_unchanged'])
        self.assertEqual(docker.calls.count(M.PRUNE), 1)
        self.assertEqual(M.PRUNE, ('/usr/bin/docker', '--host=unix:///var/run/docker.sock',
                                 'builder', 'prune', '--all', '--force', '--filter', 'until=24h'))
        self.assertFalse(any(word in ('rm', 'rmi', 'volume', 'image', 'stop', 'kill')
                             for command in docker.calls for word in command))

    def test_wrong_confirmation_and_plan_hash_refuse_without_prune(self):
        for arguments in ({'confirm': CANARY}, {'plan_sha': 'f' * 64}, {'plan_sha': CANARY}):
            with self.subTest(arguments=arguments):
                docker = Docker()
                result = self.apply(docker, **arguments)
                self.assertEqual(result['status'], 'refused')
                self.assertNotIn(M.PRUNE, docker.calls)
                self.assertNotIn(CANARY, M.canonical(result))

    def test_active_cache_refused_in_plan_and_apply(self):
        for operation in (self.plan, self.apply):
            docker = Docker(active=1)
            result = operation(docker)
            self.assertEqual(result['reason'], 'ACTIVE_CACHE')
            self.assertNotIn(M.PRUNE, docker.calls)

    def test_container_drift_during_prune_is_failure(self):
        result = self.apply(Docker(drift=True))
        self.assertEqual(result['reason'], 'CONTAINER_CHANGED')
        self.assertEqual(result['status'], 'refused')
        self.assertFalse(result['container_unchanged'])

    def test_changed_container_before_prune_invalidates_hash(self):
        with patch.dict(CONTAINER, {'pid': 777}):
            changed_hash = self.plan()['plan_sha256']
        docker = Docker()
        result = self.apply(docker, plan_sha=changed_hash)
        self.assertEqual(result['reason'], 'PLAN_MISMATCH')
        self.assertNotIn(M.PRUNE, docker.calls)

    def test_failed_or_ambiguous_prune_is_never_retried_or_disclosed(self):
        for docker, reason in ((Docker(prune_exit=1), 'PRUNE_FAILED'),
                               (Docker(timeout=True), 'PRUNE_OUTCOME_UNKNOWN')):
            result = self.apply(docker)
            self.assertEqual(result['reason'], reason)
            self.assertEqual(docker.calls.count(M.PRUNE), 1)
            self.assertTrue(result['container_unchanged'])
            self.assertNotIn(CANARY, M.canonical(result))

    def test_raw_docker_failure_never_disclosed(self):
        def bad(args, **kwargs):
            return subprocess.CompletedProcess(args, 1, CANARY.encode(), CANARY.encode())
        result = M.execute('plan', runner=bad, free=lambda: 10)
        self.assertEqual(result['reason'], 'DOCKER_READ_FAILED')
        self.assertNotIn(CANARY, M.canonical(result))

    def test_unexpected_docker_shape_never_disclosed(self):
        def bad(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, json.dumps({'Type': CANARY}).encode(), b'')
        result = M.execute('plan', runner=bad, free=lambda: 10)
        self.assertEqual(result['reason'], 'SNAPSHOT_REFUSED')
        self.assertNotIn(CANARY, M.canonical(result))

    def test_public_validator_rejects_extra_field_and_unbounded_strings(self):
        for key, value in (('extra', CANARY), ('reason', CANARY), ('plan_sha256', CANARY),
                           ('free_before_bytes', CANARY), ('prune_attempted', 1),
                           ('container_unchanged', 1)):
            result = self.plan()
            result[key] = value
            with self.assertRaises(M.Refused):
                M.validate_report(result)

    def test_not_root_and_lock_failure_are_closed(self):
        for root, failure, reason in ((1, None, 'NOT_ROOT'), (0, M.Refused('LOCKED'), 'LOCKED')):
            with patch.object(M.os, 'geteuid', return_value=root), \
                    patch.object(M, 'deployment_lock', side_effect=failure), \
                    patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertEqual(M.main(['plan', '', '']), 2)
                self.assertEqual(json.loads(out.getvalue())['reason'], reason)

    def test_real_flock_refuses_second_holder_and_releases(self):
        original_open = M.os.open
        original_fstat = M.os.fstat
        with tempfile.TemporaryDirectory() as directory:
            lock = str(Path(directory) / 'lock')
            def open_lock(path, flags, mode):
                self.assertEqual(path, '/var/lib/metainc/naver-deploy/lock')
                self.assertTrue(flags & M.os.O_NOFOLLOW)
                return original_open(lock, flags, mode)
            def fstat_root(fd):
                info = original_fstat(fd)
                return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_nlink=info.st_nlink)
            with patch.object(M.os, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)), \
                    patch.object(M.os, 'open', side_effect=open_lock), \
                    patch.object(M.os, 'fstat', side_effect=fstat_root):
                with M.deployment_lock():
                    with self.assertRaisesRegex(M.Refused, '^LOCKED$'):
                        with M.deployment_lock():
                            self.fail('second holder acquired lock')
                with M.deployment_lock():
                    pass

    def test_symlink_or_writable_lock_ancestor_refused_before_open(self):
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFDIR | 0o777):
            with patch.object(M.os, 'lstat', return_value=SimpleNamespace(st_mode=mode, st_uid=0)), \
                    patch.object(M.os, 'open') as opened:
                with self.assertRaisesRegex(M.Refused, '^LOCK_PATH_REFUSED$'):
                    with M.deployment_lock():
                        self.fail('unsafe path accepted')
                opened.assert_not_called()


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / '.github/workflows/naver-build-cache-maintenance.yml').read_text()

    def test_manual_main_owner_first_attempt_only_with_shared_lock_group(self):
        header = self.text.split('\npermissions:', 1)[0]
        self.assertEqual(re.findall(r'^  ([a-z_]+):', header, re.M), ['workflow_dispatch'])
        self.assertIn('group: deploy-logic-analysis\n  cancel-in-progress: false', self.text)
        for phrase in ('"$ACTOR" != metainchelp-boop', '"$TRIGGERING_ACTOR" != metainchelp-boop',
                       '"$REF" != refs/heads/main', '"$ATTEMPT" != 1', 'contents: read'):
            self.assertIn(phrase, self.text)
        self.assertNotIn('secrets.NAVER_PRODUCT', self.text)

    def test_pinned_verified_ssh_and_closed_output_before_print(self):
        self.assertTrue(all(re.fullmatch('[0-9a-f]{40}', x) for x in re.findall(r'uses: [^@\s]+@(\S+)', self.text)))
        self.assertEqual(self.text.count('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}'), 4)
        self.assertLess(self.text.index('unittest discover'), self.text.index('uses: appleboy/'))
        self.assertLess(self.text.index('ns["validate_report"](value)'),
                        self.text.index("printf 'NAVER_BUILD_CACHE_MAINTENANCE="))
        self.assertIn('hashlib.sha256(code).hexdigest()==expected', self.text)
        self.assertIn('O_NOFOLLOW', self.text)
        self.assertIn('st_nlink==1', self.text)
        self.assertNotRegex(self.text, r'rm\s+-rf|docker\s+(system|image|volume)\s+prune')

    def test_input_gate_rejects_injection_without_echo(self):
        match = re.search(r'        run: \|\n(.*?)\n      - uses: actions/checkout@', self.text, re.S)
        script = '\n'.join(line[10:] for line in match[1].splitlines())
        base = dict(ACTOR='metainchelp-boop', TRIGGERING_ACTOR='metainchelp-boop',
                    REF='refs/heads/main', ATTEMPT='1', HOST_FINGERPRINT='SHA256:' + 'a' * 43,
                    MODE='plan', PLAN_SHA='', CONFIRM='')
        for change, expected in (({}, 0), ({'MODE': 'apply', 'PLAN_SHA': 'a' * 64, 'CONFIRM': M.CONFIRM}, 0),
                                 ({'MODE': CANARY}, 1), ({'PLAN_SHA': CANARY}, 1),
                                 ({'MODE': 'apply', 'PLAN_SHA': 'a' * 64, 'CONFIRM': CANARY}, 1),
                                 ({'ACTOR': CANARY}, 1), ({'ATTEMPT': '2'}, 1)):
            result = subprocess.run(['/bin/bash', '-c', script], env={**base, **change},
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, expected, result.stderr)
            self.assertNotIn(CANARY, result.stdout + result.stderr)

    def test_all_embedded_shell_blocks_parse(self):
        lines = self.text.splitlines()
        count = 0
        for number, line in enumerate(lines):
            if not re.fullmatch(r'\s+(run|script): \|', line):
                continue
            indent = len(line) - len(line.lstrip())
            body = []
            for part in lines[number + 1:]:
                if part.strip() and len(part) - len(part.lstrip()) <= indent:
                    break
                body.append(part[indent + 2:])
            result = subprocess.run(['/bin/bash', '-n'], input='\n'.join(body),
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            count += 1
        self.assertEqual(count, 5)


if __name__ == '__main__':
    unittest.main()
