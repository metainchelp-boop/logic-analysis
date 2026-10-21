import builtins
import json
from pathlib import Path
import socket
import sqlite3
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.tools import naver_saved_exports_inspect as I


class SavedExportsInspectTests(unittest.TestCase):
    def setUp(self):
        self.reads = []
        self.paths = {}
        for path in (*I.SOURCE_DIRECTORY.parents, I.SOURCE_DIRECTORY, I.ENGINE_DIRECTORY):
            self.paths[str(path)] = self.info(stat.S_IFDIR | 0o750)
        for name in (I.DATABASE_NAME, I.DATABASE_NAME + '-wal', I.DATABASE_NAME + '-shm'):
            self.paths[str(I.SOURCE_DIRECTORY / name)] = self.info(stat.S_IFREG | 0o640)
        for path in (*I.PYTHONS, I.SYSTEMCTL, I.SYSTEMD_ANALYZE):
            self.paths[path] = self.info(stat.S_IFREG | 0o755, uid=0)
        self.ctx = []
        self.start(patch.object(I.os, 'lstat', side_effect=self.lstat))
        self.start(patch.object(I.os, 'stat', side_effect=self.runtime_stat))
        self.start(patch.object(I.pwd, 'getpwuid', return_value=self.account(10001, 'naver-engine')))
        self.start(patch.object(I.pwd, 'getpwnam', return_value=self.account(1200, I.EXPORTER_CANDIDATE)))
        self.start(patch.object(I.grp, 'getgrgid', side_effect=lambda gid: SimpleNamespace(gr_name='group-' + str(gid))))
        self.start(patch.object(I.os, 'getgrouplist', return_value=[10001, 1200]))
        self.process = self.start(patch.object(I.subprocess, 'run', return_value=SimpleNamespace(
            returncode=0, stdout=b'systemd 252 (252.36-1)\n+PRIVATE-FEATURE-FLAGS\n')))
        # Any unexpected file body, SQLite, environment or socket path fails.
        self.start(patch.object(builtins, 'open', side_effect=AssertionError('file-body-read')))
        self.start(patch.object(I.os, 'open', side_effect=AssertionError('file-body-read')))
        self.start(patch.object(sqlite3, 'connect', side_effect=AssertionError('database-open')))
        self.start(patch.object(socket, 'socket', side_effect=AssertionError('network')))
        self.start(patch.object(I.os, 'getenv', side_effect=AssertionError('environment-read')))

    def start(self, p):
        self.ctx.append(p)
        return p.start()

    def tearDown(self):
        for p in reversed(self.ctx):
            p.stop()

    @staticmethod
    def info(mode, *, uid=1200):
        return SimpleNamespace(st_mode=mode, st_uid=uid, st_gid=10001, st_dev=2, st_ino=3)

    @staticmethod
    def account(uid, name):
        return SimpleNamespace(pw_uid=uid, pw_gid=10001, pw_name=name)

    def lstat(self, path):
        self.reads.append(str(path))
        if str(path) not in self.paths:
            raise AssertionError('unregistered-path: ' + str(path))
        item = self.paths[str(path)]
        if isinstance(item, BaseException):
            raise item
        return item

    def runtime_stat(self, path):
        self.assertIn(str(path), (*I.PYTHONS, I.SYSTEMCTL, I.SYSTEMD_ANALYZE))
        item = self.paths[str(path)]
        if isinstance(item, BaseException):
            raise item
        return item

    def test_fixed_metadata_only_projection_has_no_source_body_or_engine_db_read(self):
        result = I.inspect_host()
        self.assertTrue(result['metadata_only'])
        self.assertTrue(result['source']['structure_valid'])
        self.assertFalse(result['source']['database_opened'])
        self.assertFalse(result['source']['readability_verified'])
        self.assertFalse(result['source']['readonly_namespace_verified'])
        self.assertEqual(result['source']['database_name'], 'logic_data.db')
        self.assertEqual(result['source']['database']['mode'], '0640')
        self.assertEqual(result['identity']['uid_10001']['name'], 'naver-engine')
        self.assertEqual(result['identity']['exporter_candidate']['name'], 'nobody')
        self.assertTrue(result['runtime']['systemctl']['binary_policy_ok'])
        self.assertNotIn('root_owned_nonwritable', result['runtime']['systemctl'])
        self.assertEqual(result['runtime']['systemd_version'], 252)
        self.assertEqual([p for p in self.reads if p.startswith(str(I.ENGINE_DIRECTORY))], [str(I.ENGINE_DIRECTORY)])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.process.assert_called_once_with([I.SYSTEMCTL, '--version'], check=False,
            stdout=I.subprocess.PIPE, stderr=I.subprocess.DEVNULL, timeout=3,
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})

    def test_symlink_source_ancestor_blocks_descendant_stat(self):
        parent = I.SOURCE_DIRECTORY.parent
        self.paths[str(parent)] = self.info(stat.S_IFLNK | 0o777)
        result = I.inspect_host()
        self.assertFalse(result['source']['structure_valid'])
        self.assertNotIn(str(I.SOURCE_DIRECTORY), self.reads)
        self.assertNotIn(str(I.SOURCE_DIRECTORY / I.DATABASE_NAME), self.reads)

    def test_symlink_database_or_wal_rejected_without_following_source(self):
        for name in (I.DATABASE_NAME, I.DATABASE_NAME + '-wal'):
            with self.subTest(name=name):
                path = str(I.SOURCE_DIRECTORY / name)
                old = self.paths[path]
                self.paths[path] = self.info(stat.S_IFLNK | 0o777)
                result = I.inspect_host()
                self.assertFalse(result['source']['structure_valid'])
                self.paths[path] = old

    def test_missing_optional_wal_shm_stays_unverified(self):
        self.paths[str(I.SOURCE_DIRECTORY / (I.DATABASE_NAME + '-wal'))] = FileNotFoundError()
        self.paths[str(I.SOURCE_DIRECTORY / (I.DATABASE_NAME + '-shm'))] = FileNotFoundError()
        result = I.inspect_host()
        self.assertTrue(result['source']['structure_valid'])
        self.assertFalse(result['source']['readonly_namespace_verified'])
        self.assertEqual(result['source']['wal']['kind'], 'missing')

    def test_missing_identities_and_runtime_are_explicit_unknown_not_created(self):
        self.start(patch.object(I.pwd, 'getpwuid', side_effect=KeyError()))
        self.start(patch.object(I.pwd, 'getpwnam', side_effect=KeyError()))
        self.start(patch.object(I.grp, 'getgrgid', side_effect=KeyError()))
        self.paths[I.SYSTEMCTL] = FileNotFoundError()
        result = I.inspect_host()
        self.assertFalse(result['identity']['uid_10001']['exists'])
        self.assertFalse(result['identity']['exporter_candidate']['exists'])
        self.assertIsNone(result['runtime']['systemd_version'])
        self.process.assert_not_called()

    def test_untrusted_version_binary_never_executes(self):
        for mode, uid in ((0o777, 0), (0o755, 1200)):
            with self.subTest(mode=mode, uid=uid):
                self.paths[I.SYSTEMCTL] = self.info(stat.S_IFREG | mode, uid=uid)
                self.assertIsNone(I.inspect_host()['runtime']['systemd_version'])
                self.process.assert_not_called()

    def test_version_output_failure_is_closed(self):
        for output in (b'secret=do-not-return', b'systemd 252\n' + b'x' * 4096):
            with self.subTest(output_len=len(output)):
                self.process.return_value = SimpleNamespace(returncode=0, stdout=output)
                self.assertIsNone(I.inspect_host()['runtime']['systemd_version'])

    def test_no_arbitrary_path_or_arguments_supported(self):
        with self.assertRaises(TypeError):
            I.inspect_host('/etc/shadow')
        with patch.object(I.sys, 'argv', ['inspector', '--source', '/etc/shadow']), patch('builtins.print') as output:
            self.assertEqual(I.main(), 2)
        self.assertEqual(json.loads(output.call_args.args[0]), {'version': 1, 'error': 'ARGUMENTS_NOT_SUPPORTED'})
        self.assertEqual(self.reads, [])


if __name__ == '__main__':
    unittest.main()
