"""Linux root-only real private-namespace fixture; never production source paths."""
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from test_naver_market_source_limit_probe_namespace_provenance import D, SOURCES, BACKEND
from naver_market_probe_namespace_fixture import independent_writer


class MarketProbeLinuxNamespaceTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Linux mount/network namespace fixture not executed on this platform')
    def test_real_private_readonly_wal_namespace(self):
        self.assertEqual(os.geteuid(), 0, 'Linux fixture requires the explicit sudo test step')
        with tempfile.TemporaryDirectory(prefix='naver-probe-fixture-') as temp:
            directory = Path(temp).resolve(); os.chmod(directory, 0o755)
            source = directory/'logic_data.db'
            with independent_writer(directory):
                for suffix in ('', '-wal', '-shm'):
                    os.chmod(str(source)+suffix, 0o644)
                originals = {suffix: hashlib.sha256(Path(str(source)+suffix).read_bytes()).hexdigest() for suffix in ('', '-wal', '-shm')}
                family = D._file_family(directory, source.name)
                before_mount = os.stat('/proc/self/ns/mnt').st_ino
                before_net = os.stat('/proc/self/ns/net').st_ino
                plan = dict(source_directory=str(directory), database_name=source.name, exporter_user='nobody', source_group=None)
                result = D._run_child(plan, SOURCES, family, BACKEND)
                self.assertEqual(result['status'], 'original_collect_passed', result)
                self.assertTrue(result['database_opened'])
                self.assertTrue(result['readonly_namespace_verified'])
                self.assertTrue(result['read_transaction_fds_bound'])
                self.assertTrue(result['path_identity_unchanged'])
                self.assertEqual(result['collect_calls'], 1)
                self.assertEqual(os.stat('/proc/self/ns/mnt').st_ino, before_mount)
                self.assertEqual(os.stat('/proc/self/ns/net').st_ino, before_net)
                for suffix, digest in originals.items():
                    self.assertEqual(hashlib.sha256(Path(str(source)+suffix).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
