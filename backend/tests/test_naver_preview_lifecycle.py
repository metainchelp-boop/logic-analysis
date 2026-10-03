"""Lifecycle controller tests, not a running Docker/systemd installation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('lifecycle', Path(__file__).parents[1]/'tools/naver_preview_lifecycle.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
RELEASE_SPEC = importlib.util.spec_from_file_location('release_lifecycle', Path(__file__).parents[1]/'tools/naver_preview_release.py')
R = importlib.util.module_from_spec(RELEASE_SPEC)
RELEASE_SPEC.loader.exec_module(R)


class UnitTest(unittest.TestCase):
    def test_units_attach_without_build_or_recreation_and_recover_runtime_folders(self):
        class Release:
            def compose(self, path, name):
                return ['docker', 'compose', '--project-name', 'naver-'+name, '-f', str(path/'compose.yml')]
        files = M.unit_files(Path('/approved/release'), 33, Release())
        self.assertEqual(len(files), 3)
        engine = files[M.UNIT_DIR/M.UNITS[0]].decode()
        relay = files[M.UNIT_DIR/M.UNITS[1]].decode()
        for body in (engine, relay):
            self.assertIn('up --no-build --no-recreate --abort-on-container-exit', body)
            self.assertNotIn('--detach', body)
            self.assertIn('Restart=always', body)
            self.assertIn('StandardOutput=null\nStandardError=null', body)
            self.assertIn('ExecStartPre=/usr/bin/systemd-tmpfiles --create', body)
            self.assertNotIn('restart docker', body)
        self.assertIn(M.TUNNEL, engine)
        self.assertIn('Requires=docker.service '+M.UNITS[0], relay)
        self.assertIn(b'd /run/metainc/naver-engine 0750 10001 10001 -', files[M.TMPFILES])
        self.assertIn(b'd /run/metainc/naver-relay 0750 10001 33 -', files[M.TMPFILES])


class LifecycleTest(unittest.TestCase):
    def scenario(self, *, failure=None, cleanup_failure=None, prior='disabled', drift=False, container_drift=False):
        package = dict(baseline='a'*64, source_commit='b'*40, ciphertext_sha256='c'*64,
                       source_tar_gz_sha256='d'*64, run_id='123456', operation='start')
        calls, enabled, active = [], {M.TUNNEL: prior}, {M.TUNNEL: 'active', 'docker.service': 'active'}
        real_lstat = Path.lstat
        def root_metadata(path, *args, **kwargs):
            value = list(real_lstat(path, *args, **kwargs)); value[4:6] = [0, 0]
            return os.stat_result(value)
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root, secrets = base/'staging', base/'secrets'
            path = root/'releases'/('naver-'+package['source_commit'])
            for directory in (root, root/'releases', root/'receipts', path, secrets):
                directory.mkdir(mode=0o700)
            unit_dir, tmp_dir = base/'systemd', base/'tmpfiles'
            unit_dir.mkdir(mode=0o755); tmp_dir.mkdir(mode=0o755)
            paths = {path/'deploy/naver-engine-backup.override.yml'}
            paths.update(path/(prefix+name+suffix) for name in ('engine', 'relay')
                         for prefix, suffix in (('compose.naver-', '.yml'), ('preview-', '.override.yml')))
            paths.update(secrets/name for name in R.SECRET_OWNERS)
            for filename in paths:
                filename.parent.mkdir(parents=True, exist_ok=True)
                filename.write_bytes(b'synthetic approval fixture')
            receipt = dict(ok=True, stage='prepared', source_commit=package['source_commit'],
                           package={k: v for k, v in package.items() if k != 'operation'},
                           files={str(p): R.sha(p.read_bytes()) for p in paths},
                           images={'engine': 'sha256:'+'e'*64, 'relay': 'sha256:'+'e'*64})
            for prefix, body in (('preview-', receipt), ('preview-start-', dict(ok=True, stage='internal_ready',
                                                                            source_commit=package['source_commit']))):
                filename = root/'receipts'/(prefix+package['source_commit']+'.json')
                filename.write_text(json.dumps(body)); filename.chmod(0o600)

            def execute(args, **kwargs):
                calls.append(args)
                code, output = 0, ''
                if args[:3] == ['docker', 'image', 'inspect']:
                    output = json.dumps('sha256:'+'e'*64)
                elif args[:2] == ['docker', 'compose']:
                    output = ('1' if args[3] == 'naver-engine' else '2')*64
                elif args[:2] == ['docker', 'inspect']:
                    name = 'engine' if args[-1] == '1'*64 else 'relay'
                    started_at = 'changed' if container_drift and active.get(M.UNITS[0]) == 'active' else 'initial'
                    output = json.dumps(dict(id=args[-1], image='sha256:'+'e'*64, running=True,
                                             started=started_at, restarts=0, project='naver-'+name, service='naver-'+name))
                elif args[0] == '/usr/bin/systemctl':
                    action = args[1]
                    if action == 'show':
                        unit, field = args[2], args[4]
                        output = {'ActiveState': active.get(unit, 'inactive'),
                                  'UnitFileState': enabled.get(unit, 'disabled'), 'LoadState': 'not-found'}[field]
                    elif action == 'enable':
                        enabled.update({unit: 'enabled' for unit in args[2:]})
                        code = int(failure == ('enable', None))
                    elif action == 'start':
                        active[args[2]] = 'active'
                        code = int(failure == ('start', args[2]))
                    elif action in ('stop', 'disable'):
                        if cleanup_failure == (action, args[2]):
                            code = 1
                        elif action == 'stop':
                            active[args[2]] = 'inactive'
                        else:
                            enabled[args[2]] = 'disabled'
                    elif action != 'daemon-reload':
                        raise AssertionError('unexpected mutation')
                else:
                    raise AssertionError('unexpected command')
                return subprocess.CompletedProcess(args, code, output.encode(), b'')

            host = Mock()
            host.baseline.side_effect = lambda: ('f'*64 if drift and active.get(M.UNITS[0]) == 'active' else package['baseline'])
            with patch.object(R, 'ROOT', root), patch.object(R, 'SECRET_ROOT', secrets), \
                 patch.object(M, 'UNIT_DIR', unit_dir), patch.object(M, 'TMPFILES', tmp_dir/'preview.conf'), \
                 patch.object(Path, 'lstat', root_metadata), patch.object(os, 'geteuid', return_value=0), \
                 patch.object(os, 'fchown'), patch.object(M.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_gid=33)), \
                 patch.object(R.subprocess, 'run', side_effect=execute), patch.object(M.time, 'sleep'):
                try:
                    result = M.install(package, host, R)
                except Exception as error:
                    result = error
        for args in calls:
            if args[:2] in (['/usr/bin/systemctl', 'stop'], ['/usr/bin/systemctl', 'start']):
                self.assertIn(args[2], M.UNITS)
            self.assertNotIn('restart', args)
        self.assertEqual(active[M.TUNNEL], 'active')
        return result, calls, enabled, active

    def test_existing_containers_are_attached_and_tunnel_is_only_enabled(self):
        result, calls, enabled, active = self.scenario()
        self.assertIsInstance(result, dict)
        self.assertTrue(result['ok'])
        self.assertTrue(all(active[unit] == 'active' and enabled[unit] == 'enabled' for unit in M.UNITS))
        self.assertFalse(any(args[1] == 'stop' for args in calls if args[0] == '/usr/bin/systemctl'))

    def test_partial_enable_is_disabled_and_prior_tunnel_state_restored(self):
        for prior in ('enabled', 'disabled'):
            result, _, enabled, _ = self.scenario(failure=('enable', None), prior=prior)
            self.assertIsInstance(result, RuntimeError)
            self.assertEqual(enabled[M.TUNNEL], prior)
            self.assertTrue(all(enabled[unit] == 'disabled' for unit in M.UNITS))

    def test_partial_start_failure_stops_attempted_new_units_only(self):
        for unit in M.UNITS:
            result, calls, enabled, active = self.scenario(failure=('start', unit))
            self.assertIsInstance(result, RuntimeError)
            stops = [args[2] for args in calls if args[:2] == ['/usr/bin/systemctl', 'stop']]
            self.assertEqual(stops, list(reversed(M.UNITS[:M.UNITS.index(unit)+1])))
            self.assertTrue(all(active[name] == 'inactive' for name in stops))
            self.assertEqual(enabled[M.TUNNEL], 'disabled')

    def test_cleanup_failure_does_not_prevent_remaining_stop_disable_and_tunnel_restore(self):
        result, calls, enabled, active = self.scenario(failure=('start', M.UNITS[1]),
                                                     cleanup_failure=('stop', M.UNITS[1]))
        self.assertEqual(str(result), 'LIFECYCLE_ROLLBACK_FAILED')
        self.assertEqual(active[M.UNITS[0]], 'inactive')
        self.assertTrue(all(enabled[unit] == 'disabled' for unit in (*M.UNITS, M.TUNNEL)))

    def test_changed_legacy_baseline_refuses_success_and_runs_cleanup(self):
        result, _, enabled, active = self.scenario(drift=True)
        self.assertEqual(str(result), 'CONTAINER_BASELINE_CHANGED')
        self.assertTrue(all(active[unit] == 'inactive' for unit in M.UNITS))
        self.assertEqual(enabled[M.TUNNEL], 'disabled')

    def test_changed_new_container_started_at_is_not_reported_as_a_safe_attachment(self):
        result, _, enabled, active = self.scenario(container_drift=True)
        self.assertEqual(str(result), 'CONTAINER_BASELINE_CHANGED')
        self.assertTrue(all(active[unit] == 'inactive' for unit in M.UNITS))
        self.assertEqual(enabled[M.TUNNEL], 'disabled')

    def test_module_can_be_loaded_without_file_attribute(self):
        module = types.ModuleType('memory_lifecycle')
        exec(compile(SPEC.loader.get_source('lifecycle'), '<approved-lifecycle>', 'exec'), module.__dict__)
        self.assertNotIn('__file__', module.__dict__)
        self.assertEqual(module.UNITS, M.UNITS)


if __name__ == '__main__':
    unittest.main()
