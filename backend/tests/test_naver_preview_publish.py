"""Publish controller tests: synthetic nginx files and command/identity adapters only."""
import importlib.util
import contextlib
import json
import os
from pathlib import Path
import stat
import types
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('publish', Path(__file__).parents[1]/'tools/naver_preview_publish.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

CONFIG = b'''server {
    listen 80;
    server_name dashboard.metainc.co.kr;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name dashboard.metainc.co.kr;
    ssl_certificate /etc/letsencrypt/live/example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:5051;
        proxy_set_header Host $host;
    }
}
'''


class CandidateTest(unittest.TestCase):
    def test_only_dashboard_tls_gains_exact_and_delimited_naver_routes(self):
        candidate = M.build_config(CONFIG)
        self.assertIn(CONFIG.split(b'server {', 2)[1], candidate)
        old_root = CONFIG[CONFIG.index(b'    location / {'):CONFIG.rindex(b'\n}')]
        self.assertIn(old_root, candidate)
        self.assertEqual(candidate.count(b'proxy_pass http://unix:/run/metainc/naver-relay/relay.sock:'), 4)
        for route in (b'location = /naver {', b'location ^~ /naver/ {',
                      b'location = /api/naver-auto {', b'location ^~ /api/naver-auto/ {'):
            self.assertIn(route, candidate)
        self.assertIn(b'access_log off;', candidate)
        self.assertIn(b'error_log /dev/null crit;', candidate)
        self.assertEqual(candidate.count(b'add_header Referrer-Policy no-referrer always;'), 4)
        self.assertEqual(candidate.count(b'add_header Cache-Control no-store always;'), 4)

    def test_ambiguous_or_sensitive_overrides_are_refused(self):
        for change in (b'include /etc/nginx/snippets/unknown.conf;',
                       b'location ^~ /naver/ { return 404; }',
                       b'location ~ .php$ { return 404; }',
                       b'access_log /var/log/nginx/private.log;',
                       b'error_log /var/log/nginx/private.log;',
                       b'error_page 413 /legacy-error;',
                       b'return 301 https://other.example;'):
            body = CONFIG.replace(b'    location / {', b'    '+change+b'\n    location / {')
            with self.subTest(change=change), self.assertRaises(ValueError):
                M.build_config(body)
        with self.assertRaises(ValueError):
            M.build_config(CONFIG+CONFIG)
        with self.assertRaises(ValueError):
            M.build_config(CONFIG.replace(b':5051;', b':5052;'))


class SyntheticSystem:
    """External filesystem/nginx adapter, never executes a host command."""
    def __init__(self, package, fail=None):
        self.body, self.calls, self.fail = CONFIG, [], fail
        self.files = {
            str(M.ROOT/'receipts'/('preview-'+package['source_commit']+'.json')): json.dumps({
                'ok': True, 'stage': 'prepared', 'source_commit': package['source_commit'],
                'package': {k: package[k] for k in ('baseline', 'source_commit', 'source_tar_gz_sha256')}
            }).encode(),
            str(M.ROOT/'receipts'/('preview-start-'+package['source_commit']+'.json')): json.dumps({
                'ok': True, 'stage': 'internal_ready', 'source_commit': package['source_commit']}).encode()}

    def root(self):
        return True

    def config(self):
        return '/etc/nginx/sites-available/ad.metainc.co.kr', self.body

    def read_private(self, path):
        return self.files[str(path)]

    def new_private(self, path, body):
        if str(path) in self.files:
            raise FileExistsError()
        self.files[str(path)] = body

    @contextlib.contextmanager
    def locked(self):
        yield

    def replace_config(self, target, expected, body):
        if target != self.config()[0] or M.sha(self.body) != expected:
            raise ValueError('CONFIG_CHANGED')
        self.calls.append('replace')
        self.body = body

    def command(self, args):
        self.calls.append(tuple(args))
        if args == ['nginx', '-T']:
            return ('# configuration file '+str(M.CONFIG)+':\n').encode()+self.body+b'\n'
        if args == self.fail:
            self.fail = None
            raise RuntimeError('NGINX_COMMAND_FAILED')
        return b''


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.package = {'baseline': 'a'*64, 'source_commit': 'b'*40,
                        'source_tar_gz_sha256': 'c'*64, 'nginx_sha256': M.sha(CONFIG)}
        self.host = type('Host', (), {'baseline': lambda obj: 'a'*64})()

    def test_plan_has_no_writes_and_no_config_or_receipt_secrets(self):
        system = SyntheticSystem(self.package)
        before = dict(system.files)
        result = M.plan(self.package, self.host, system=system)
        self.assertEqual(system.files, before)
        self.assertNotIn('replace', system.calls)
        self.assertEqual(result['mutations'], 0)
        self.assertEqual(result['original_sha256'], M.sha(CONFIG))
        self.assertNotIn('ssl_certificate', json.dumps(result))

    def test_plan_can_discover_raw_hash_but_writes_require_an_exact_pin(self):
        for discovered in (dict(self.package, nginx_sha256=''),
                           {k: v for k, v in self.package.items() if k != 'nginx_sha256'}):
            system = SyntheticSystem(self.package)
            with self.subTest(package=discovered):
                result = M.plan(discovered, self.host, system=system)
                self.assertEqual(result['original_sha256'], M.sha(CONFIG))
                self.assertEqual(system.body, CONFIG)
                for operation in (M.apply, M.rollback):
                    with self.assertRaises(ValueError):
                        operation(discovered, self.host, system=system)

    def test_apply_and_explicit_rollback_preserve_exact_original(self):
        system = SyntheticSystem(self.package)
        result = M.apply(self.package, self.host, system=system)
        self.assertTrue(result['reload_requested'])
        self.assertFalse(result['public_access_verified'])
        self.assertEqual(system.body, M.build_config(CONFIG))
        result = M.rollback(self.package, self.host, system=system)
        self.assertTrue(result['rolled_back'])
        self.assertEqual(system.body, CONFIG)

    def test_failed_test_or_reload_restores_exact_original_and_reloads(self):
        for failing in (['nginx', '-t'], ['nginx', '-s', 'reload']):
            with self.subTest(failing=failing):
                system = SyntheticSystem(self.package, fail=failing)
                with self.assertRaisesRegex(RuntimeError, 'PUBLISH_FAILED_ROLLED_BACK'):
                    M.apply(self.package, self.host, system=system)
                self.assertEqual(system.body, CONFIG)
                self.assertEqual(system.calls[-2:], [('nginx', '-t'), ('nginx', '-s', 'reload')])

    def test_bad_source_or_original_hash_never_changes_files(self):
        for field in ('source_tar_gz_sha256', 'nginx_sha256', 'baseline'):
            system = SyntheticSystem(self.package)
            changed = dict(self.package, **{field: 'd'*64})
            before = dict(system.files)
            with self.subTest(field=field), self.assertRaises(ValueError):
                M.apply(changed, self.host, system=system)
            self.assertEqual(system.files, before)
            self.assertEqual(system.body, CONFIG)

    def test_rollback_never_overwrites_a_subsequent_edit(self):
        system = SyntheticSystem(self.package)
        M.apply(self.package, self.host, system=system)
        system.body += b'# later authorized change\n'
        changed = system.body
        with self.assertRaisesRegex(ValueError, 'CONFIG_CHANGED'):
            M.rollback(self.package, self.host, system=system)
        self.assertEqual(system.body, changed)

    def test_same_hostname_in_a_different_loaded_file_is_not_our_target(self):
        system = SyntheticSystem(self.package)
        command = system.command
        system.command = lambda args: (b'# configuration file /etc/nginx/other.conf:\n'+CONFIG
                                       if args == ['nginx', '-T'] else command(args))
        with self.assertRaisesRegex(ValueError, 'CONFIG_NOT_LOADED'):
            M.plan(self.package, self.host, system=system)


class NativeGuardTest(unittest.TestCase):
    def test_module_runs_from_memory_without_a_file_attribute(self):
        module = types.ModuleType('in_memory_publish')
        exec(compile(SPEC.loader.get_source('publish'), '<approved-publish>', 'exec'), module.__dict__)
        self.assertNotIn('__file__', module.__dict__)
        self.assertEqual(module.build_config(CONFIG), M.build_config(CONFIG))

    def test_untrusted_symlink_owner_and_outside_target_are_refused_before_open(self):
        def info(path, *, link_uid=0):
            is_link = path == M.CONFIG
            return os.stat_result(((stat.S_IFLNK | 0o777) if is_link else (stat.S_IFDIR | 0o755),
                                   1, 1, 1, link_uid if is_link else 0, 0, 1, 0, 0, 0))
        with patch.object(Path, 'lstat', lambda path: info(path, link_uid=1000)), \
             patch.object(M.os, 'open') as opened:
            with self.assertRaisesRegex(ValueError, 'CONFIG_LINK_POLICY'):
                M.NativeSystem().config()
            opened.assert_not_called()
        with patch.object(Path, 'lstat', info), \
             patch.object(Path, 'resolve', return_value=Path('/tmp/not-approved')), \
             patch.object(M.os, 'open') as opened:
            with self.assertRaisesRegex(ValueError, 'CONFIG_TARGET_SCOPE'):
                M.NativeSystem().config()
            opened.assert_not_called()

    def test_process_adapter_cannot_execute_an_arbitrary_command(self):
        with patch.object(M.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'COMMAND_SCOPE'):
                M.NativeSystem().command(['sh', '-c', 'unexpected'])
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
