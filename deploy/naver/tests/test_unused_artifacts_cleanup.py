"""The new cleanup scope preserves logs and reuses the existing destructive guards."""
import contextlib
import hashlib
import io
import json
import os
import stat
import sys
import unittest
from unittest import mock

import test_naver_deploy as D


STATE = '/var/lib/metainc/naver-deploy'
SCOPE = 'unused-naver-artifacts-v1'


class ArtifactsCleanupTest(unittest.TestCase):
    # Reuse the fake host and the original safety assertions, without inheriting
    # unrelated deployment tests or changing the legacy mode's expectations.
    tearDown = D.DeployScriptTest.tearDown
    output = D.DeployScriptTest.output
    assertExit = D.DeployScriptTest.assertExit
    add_cleanup_fixture = D.DeployScriptTest.add_cleanup_fixture
    plan = D.DeployScriptTest.plan
    swap_fixture = D.DeployScriptTest.swap_fixture
    assert_swap_refused = D.DeployScriptTest.assert_swap_refused

    def setUp(self):
        D.DeployScriptTest.setUp(self)
        self.host.file(STATE + '/state.json', '{"phase":"done"}', 0o600)
        self.host.file(STATE + '/lock', '', 0o640)
        os.chmod(self.host.root + STATE, 0o750)
        self.raw_run = self.host.run
        modes = {'cleanup': 'cleanup-artifacts', 'cleanup-plan': 'cleanup-artifacts-plan'}
        self.host.run = lambda mode, *args, **env: self.raw_run(modes.get(mode, mode), *args, **env)

    def logs(self):
        for index in range(20):
            path = STATE + '/logs/commands-20260101T%06dZ.log' % index
            self.host.file(path, 'synthetic private command %d\n' % index, 0o640)
            os.utime(self.host.root + path, ns=(1000000000 + index, 2000000000 + index))
        os.chmod(self.host.root + STATE + '/logs', 0o750)
        os.utime(self.host.root + STATE + '/logs', ns=(3000000000, 4000000000))

    def log_snapshot(self):
        folder = self.host.root + STATE + '/logs'
        paths = [folder] + ([os.path.join(folder, name) for name in sorted(os.listdir(folder))]
                            if os.path.isdir(folder) else [])
        result = {}
        for path in paths:
            if not os.path.lexists(path):
                result[path] = None
                continue
            info = os.lstat(path)
            with open(path, 'rb') if stat.S_ISREG(info.st_mode) else contextlib.nullcontext(None) as handle:
                digest = hashlib.sha256(handle.read()).hexdigest() if handle else None
            result[path] = (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, digest)
        return result

    def result(self, done):
        lines = self.output(done).splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith('NAVER_DEPLOY_CLEANUP_RESULT='))
        for value in D.CANARIES:
            self.assertNotIn(value, lines[0])
        return json.loads(lines[0].split('=', 1)[1])

    def test_scope_hash_and_additional_path_image_protection(self):
        self.add_cleanup_fixture()
        before = self.host.tree()
        new = self.plan()
        legacy = json.loads(self.output(self.raw_run('cleanup-plan')).split('=', 1)[1])
        self.assertEqual(before, self.host.tree())
        expected = [c for c in legacy['candidates'] if not
                    (c['type'] == 'image' and c['ref'].endswith(':' + D.OLD4))]
        self.assertEqual(new['candidates'], expected)
        self.assertEqual(new['path_references'], legacy['path_references'])
        self.assertEqual(new['scope'], SCOPE)
        self.assertIs(new['read_only'], True)
        self.assertIs(new['reclaim_is_estimate'], True)
        identities = sorted([c['type'], c['ref'], c['id']] for c in expected)
        canonical = json.dumps({'scope': SCOPE, 'candidates': identities}, separators=(',', ':'))
        self.assertEqual(new['allowlist_sha256'], hashlib.sha256(canonical.encode()).hexdigest())
        self.assertNotEqual(new['allowlist_sha256'], legacy['allowlist_sha256'])

    def test_hash_scopes_cannot_be_cross_applied_even_for_identical_candidates(self):
        # No extra path-only image in this fixture: different scopes alone must refuse.
        new = self.plan()
        legacy = json.loads(self.output(self.raw_run('cleanup-plan')).split('=', 1)[1])
        self.assertEqual(new['candidates'], legacy['candidates'])
        before_tags = self.host.tags()
        for mode, digest in [('cleanup-artifacts', legacy['allowlist_sha256']),
                             ('cleanup', new['allowlist_sha256'])]:
            done = self.raw_run(mode, digest)
            self.assertExit(done, 10)
            self.assertEqual(self.result(done)['status'], 'REFUSED_HASH_MISMATCH')
            self.assertEqual(self.host.tags(), before_tags)

    def test_existing_logs_and_state_permissions_unchanged_on_success(self):
        self.add_cleanup_fixture()
        self.logs()
        before, state_mode = self.log_snapshot(), os.stat(self.host.root + STATE).st_mode
        plan = self.plan()
        done = self.host.run('cleanup', plan['allowlist_sha256'])
        self.assertExit(done, 0)
        result = self.result(done)
        self.assertEqual(result['scope'], SCOPE)
        self.assertEqual(result['mode'], 'cleanup-artifacts')
        self.assertEqual(result['status'], 'CLEANED')
        self.assertEqual(set(result['removed']), {c['ref'] for c in plan['candidates']})
        self.assertEqual(self.log_snapshot(), before)
        self.assertEqual(os.stat(self.host.root + STATE).st_mode, state_mode)
        self.assertIn('metainc/naver-engine:' + D.OLD4, self.host.tags())
        self.assertIn('metainc/naver-relay:' + D.OLD4, self.host.tags())

    def test_no_log_directory_created_and_non_candidates_unchanged(self):
        self.add_cleanup_fixture()
        self.host.file('/var/backups/other-app/archive.enc', 'synthetic preserved archive', 0o600)
        before = self.host.tree()
        state = self.host.load_state()
        plan = self.plan()
        self.assertExit(self.host.run('cleanup', plan['allowlist_sha256']), 0)
        after = self.host.tree()
        removed_roots = tuple(c['ref'].lstrip('/') for c in plan['candidates'] if c['type'] == 'release')
        self.assertEqual({k: v for k, v in before.items() if not k.startswith(removed_roots)}, after)
        current = self.host.load_state()
        # Fake docker inspect increments a test-only counter on each read.
        containers = lambda value: {key: {k: v for k, v in row.items() if k != 'inspects'}
                                    for key, row in value['containers'].items()}
        self.assertEqual(containers(current), containers(state))
        self.assertEqual(current['units'], state['units'])
        self.assertFalse(os.path.exists(self.host.root + STATE + '/logs'))
        for call in self.host.calls():
            self.assertFalse(call[0] in ('cp', 'sqlite3', 'curl'), call)
            self.assertFalse(call[0] == 'systemctl' and call[1] in D.MUTATING_SYSTEMCTL, call)
            self.assertFalse('prune' in call, call)

    def test_logs_unchanged_on_hash_failure_partial_and_plan_failure(self):
        self.add_cleanup_fixture()
        self.logs()
        before = self.log_snapshot()
        done = self.host.run('cleanup', '0' * 64)
        self.assertExit(done, 10)
        self.assertEqual(self.result(done)['status'], 'REFUSED_HASH_MISMATCH')
        self.assertEqual(self.log_snapshot(), before)
        plan = self.plan()
        self.host.set(in_use_on_rm=['metainc/naver-relay:' + D.OLD2])
        done = self.host.run('cleanup', plan['allowlist_sha256'])
        self.assertExit(done, 5)
        self.assertEqual(self.result(done)['status'], 'PARTIAL')
        self.assertEqual(self.log_snapshot(), before)
        self.host.file(STATE + '/state.json', 'not json', 0o600)
        done = self.host.run('cleanup', '0' * 64)
        self.assertExit(done, 10)
        self.assertEqual(self.result(done)['status'], 'REFUSED_PLAN_FAILED')
        self.assertEqual(self.log_snapshot(), before)

    def test_shared_lock_and_unfinished_state_refuse_without_log_changes(self):
        self.add_cleanup_fixture()
        self.logs()
        before = self.log_snapshot()
        plan = self.plan()
        with open(self.host.root + STATE + '/lock', 'a') as lock:
            D.fcntl.flock(lock, D.fcntl.LOCK_EX | D.fcntl.LOCK_NB)
            done = self.host.run('cleanup', plan['allowlist_sha256'])
        self.assertExit(done, 11)
        self.assertEqual(self.result(done)['status'], 'LOCKED')
        self.host.file(STATE + '/state.json', '{"phase":"starting"}', 0o600)
        done = self.host.run('cleanup', plan['allowlist_sha256'])
        self.assertExit(done, 10)
        self.assertEqual(self.result(done)['status'], 'REFUSED_DEPLOY_NOT_FINISHED')
        self.assertEqual(self.log_snapshot(), before)

    def test_missing_state_and_extra_path_input_refused_without_creation(self):
        D.shutil.rmtree(self.host.root + STATE)
        before = self.host.tree()
        done = self.host.run('cleanup', '0' * 64)
        self.assertExit(done, 10)
        self.assertEqual(self.result(done)['status'], 'REFUSED_LAYOUT')
        for args in [('cleanup-artifacts-plan', '/tmp/untrusted'),
                     ('cleanup-artifacts', '0' * 64, '/tmp/untrusted'),
                     ('cleanup-artifacts', '$(touch /tmp/untrusted)')]:
            self.assertIn(self.raw_run(*args).returncode, (10, 64))
        self.assertEqual(before, self.host.tree())

    def test_companion_and_container_mount_protect_images_in_new_mode_only(self):
        self.add_cleanup_fixture()
        self.host.file(D.COMPANION, self.host.read(D.COMPANION) +
                       '\n# ' + D.RELEASES + '/naver-' + D.OLD1 + '/source\n')
        state = self.host.load_state()
        container = next(iter(state['containers'].values()))
        container['mounts'] = [['bind', D.RELEASES + '/naver-' + D.OLD2 + '/source', '/source', False]]
        self.host.state = state
        self.host.save_state()
        new = self.plan()
        legacy = json.loads(self.output(self.raw_run('cleanup-plan')).split('=', 1)[1])
        for commit, reason in [(D.OLD1, 'companion'), (D.OLD2, 'container-mount')]:
            self.assertIn(reason, new['path_references'][commit])
            self.assertTrue(any(c['type'] == 'image' and c['ref'].endswith(commit) for c in legacy['candidates']))
            self.assertFalse(any(c['ref'].endswith(commit) for c in new['candidates']))

    def test_path_protected_image_identity_also_protects_other_naver_tag(self):
        self.add_cleanup_fixture()
        state = self.host.load_state()
        identity = next(key for key, image in state['images'].items()
                        if 'metainc/naver-engine:' + D.OLD4 in image['tags'])
        alias = 'metainc/naver-engine:' + 'a9' * 20
        state['images'][identity]['tags'].append(alias)
        self.host.state = state
        self.host.save_state()
        legacy = json.loads(self.output(self.raw_run('cleanup-plan')).split('=', 1)[1])
        self.assertIn(alias, {c['ref'] for c in legacy['candidates']})
        self.assertNotIn(alias, {c['ref'] for c in self.plan()['candidates']})

    def test_late_unit_reference_protects_image_before_rm(self):
        self.add_cleanup_fixture()
        self.logs()
        before = self.log_snapshot()
        plan = self.plan()
        images = [c for c in plan['candidates'] if c['type'] == 'image']
        target = images[-1]
        called = []

        def transform(namespace):
            original = namespace['docker']
            def docker(args, *a, **kw):
                called.append(args)
                result = original(args, *a, **kw)
                if args == ['image', 'rm', images[0]['ref']]:
                    self.host.file('/etc/systemd/system/naver-late-image.service',
                                   '[Service]\nExecStart=/bin/true ' + D.RELEASES +
                                   '/naver-' + target['ref'].rsplit(':', 1)[1] + '/source\n')
                return result
            namespace['docker'] = docker

        code, result = self.run_cleanup_in_process(plan, [], transform)
        self.assertEqual(code, 5)
        self.assertIn(target['ref'], result['refused'])
        self.assertNotIn(['image', 'rm', target['ref']], called)
        self.assertIn(target['ref'], self.host.tags())
        self.assertEqual(before, self.log_snapshot())

    def test_docker_failure_output_is_discarded_without_log_creation(self):
        self.add_cleanup_fixture()
        plan = self.plan()
        target = next(c['ref'] for c in plan['candidates'] if c['type'] == 'image')
        canary = 'SYNTHETIC_PRIVATE_DOCKER_OUTPUT_DO_NOT_EMIT'
        def transform(namespace):
            original = namespace['docker']
            def docker(args, *a, **kw):
                if args == ['image', 'rm', target]:
                    return 1, canary, canary
                return original(args, *a, **kw)
            namespace['docker'] = docker
        code, result = self.run_cleanup_in_process(plan, [], transform)
        self.assertEqual(code, 5)
        self.assertIn(target, result['failed'])
        self.assertNotIn(canary, json.dumps(result))
        self.assertFalse(os.path.exists(self.host.root + STATE + '/logs'))

    def run_cleanup_in_process(self, plan, patches, transform=None):
        with open(D.SCRIPT) as handle:
            source = handle.read().split("PY_HELPER=$(cat <<'PYEOF'\n", 1)[1].split('\nPYEOF', 1)[0]
        namespace = {'__name__': 'naver_deploy_helper'}
        exec(source, namespace)
        namespace['ROOT'] = self.host.root
        if transform is not None:
            transform(namespace)
        env = {'PATH': self.host.bin + ':' + os.path.dirname(sys.executable) + ':/usr/bin:/bin:/usr/sbin:/sbin'}
        output, code = io.StringIO(), None
        with mock.patch.dict(os.environ, env), contextlib.ExitStack() as stack:
            for target, replacement in patches:
                stack.enter_context(mock.patch(target, replacement))
            stack.enter_context(contextlib.redirect_stdout(output))
            try:
                namespace['cleanup'](plan['allowlist_sha256'], None, artifacts_only=True)
            except SystemExit as error:
                code = error.code
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1, 'cleanup must emit only its closed result')
        self.assertTrue(lines[0].startswith('NAVER_DEPLOY_CLEANUP_RESULT='))
        return code, json.loads(lines[0].split('=', 1)[1])

    # Same assertions as the legacy safety regressions; only mode routing changes.
    test_cleanup_removes_exactly_the_allowlist = D.DeployScriptTest.test_cleanup_removes_exactly_the_allowlist
    test_cleanup_refuses_image_in_use = D.DeployScriptTest.test_cleanup_refuses_image_in_use
    test_cleanup_refuses_release_referenced_after_approval = D.DeployScriptTest.test_cleanup_refuses_release_referenced_after_approval
    test_cleanup_refuses_retagged_image = D.DeployScriptTest.test_cleanup_refuses_retagged_image
    test_cleanup_reads_dropins = D.DeployScriptTest.test_cleanup_reads_dropins
    test_cleanup_unreadable_dropin_refuses_plan = D.DeployScriptTest.test_cleanup_unreadable_dropin_refuses_plan
    test_incomplete_systemctl_show_refuses_plan = D.DeployScriptTest.test_incomplete_systemctl_show_refuses_plan
    test_release_swapped_before_open_is_refused = D.DeployScriptTest.test_release_swapped_before_open_is_refused
    test_release_swapped_before_final_rmdir_is_refused = D.DeployScriptTest.test_release_swapped_before_final_rmdir_is_refused
    test_child_dir_swapped_during_recursion_is_refused = D.DeployScriptTest.test_child_dir_swapped_during_recursion_is_refused


if __name__ == '__main__':
    unittest.main()
