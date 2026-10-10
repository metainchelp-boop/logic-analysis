"""Synthetic procfs/cgroup fixtures only; no host kernel metadata or operating calls."""
import contextlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_naver_preview_collection_status as previous

M = previous.M


CID = 'd'*64
PID = 1234
CGROUP = ('system.slice', 'docker-'+CID+'.scope')


class PassiveKernelResourcesTest(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            proc = root/'proc'/str(PID)
            proc.mkdir(parents=True)
            cgroup = root/'sys/fs/cgroup'/Path(*CGROUP)
            cgroup.mkdir(parents=True)
            (root/'proc/meminfo').write_bytes(b'MemTotal: 2048 kB\nMemAvailable: 512 kB\nSwapFree: 64 kB\nPrivate: SECRET\n')
            # comm can contain spaces and parentheses; field 22 is starttime.
            (proc/'stat').write_bytes(str(PID).encode()+b' (private (comm)) S '+b'0 '*18+b'777 0\n')
            (proc/'cgroup').write_bytes(('0::/'+ '/'.join(CGROUP)+'\n').encode())
            (cgroup/'cpu.stat').write_bytes(b'usage_usec 1000\nnr_periods 20\nnr_throttled 3\nthrottled_usec 50\nfuture 17\n')
            (cgroup/'cpu.max').write_bytes(b'50000 100000\n')
            (cgroup/'memory.current').write_bytes(b'134217728\n')
            (cgroup/'memory.max').write_bytes(b'536870912\n')
            (cgroup/'memory.events').write_bytes(b'low 0\nhigh 1\nmax 2\noom 0\noom_kill 0\noom_group_kill 0\n')
            opened = []
            original = os.open
            def synthetic_open(name, flags, *args, **kwargs):
                opened.append(str(name))
                # Anchor all relative openat traversal in this synthetic tree.
                if name == '/': name = root
                return original(name, flags, *args, **kwargs)
            with patch.object(M.os, 'open', side_effect=synthetic_open):
                yield root, proc, cgroup, opened

    def state(self, **extra):
        return dict(running=True, pid=PID, **extra)

    def test_host_memory_is_three_numeric_fields_with_kernel_kib_units(self):
        with self.fixture() as (_, _, _, opened):
            result = M.host_memory_metadata(deadline=float('inf'))
        self.assertEqual(result, dict(available=True, mem_total_bytes=2097152,
                                     mem_available_bytes=524288, swap_free_bytes=65536))
        self.assertEqual(opened, ['/', 'proc', 'meminfo'])
        self.assertNotIn('SECRET', json.dumps(result))

    def test_host_memory_refuses_bad_units_duplicates_missing_overflow_and_symlink(self):
        cases = (b'MemTotal: 1 MB\nMemAvailable: 0 kB\nSwapFree: 0 kB\n',
                 b'MemTotal: 1 kB\nMemTotal: 1 kB\nMemAvailable: 0 kB\nSwapFree: 0 kB\n',
                 b'MemTotal: 1 kB\nMemAvailable: 2 kB\nSwapFree: 0 kB\n',
                 b'MemTotal: 9999999999999999999 kB\nMemAvailable: 0 kB\nSwapFree: 0 kB\n',
                 b'MemTotal: 1 kB\n', b'\xff', b'x'*16385)
        for raw in cases:
            with self.subTest(size=len(raw)), self.fixture() as (root, _, _, _):
                (root/'proc/meminfo').write_bytes(raw)
                self.assertEqual(M.host_memory_metadata(deadline=float('inf')),
                                 dict(available=False, code='HOST_MEMORY_UNAVAILABLE'))
        with self.fixture() as (root, _, _, _):
            (root/'private').write_bytes(b'SECRET')
            (root/'proc/meminfo').unlink()
            (root/'proc/meminfo').symlink_to(root/'private')
            self.assertFalse(M.host_memory_metadata(deadline=float('inf'))['available'])

    def test_engine_limits_and_counters_are_exact_numbers_and_private_guard_is_not_output(self):
        guard = {}
        with self.fixture():
            result = M.engine_cgroup_resources(CID, self.state(), guard, deadline=float('inf'))
            self.assertTrue(M.resource_identity_unchanged(CID, self.state(), guard))
        self.assertEqual(result, dict(available=True, cpu_quota_usec=50000, cpu_period_usec=100000,
            usage_usec=1000, nr_periods=20, nr_throttled=3, throttled_usec=50,
            memory_current_bytes=134217728, memory_max_bytes=536870912,
            memory_events=dict(low=0, high=1, max=2, oom=0, oom_kill=0)))
        for private in (CID, '1234', '777', 'system.slice', 'docker-', 'private', 'SECRET'):
            self.assertNotIn(private, json.dumps(result))
        self.assertTrue(guard)

    def test_unbounded_limits_are_null_and_real_zero_counters_remain_zero(self):
        with self.fixture() as (_, _, cgroup, _):
            (cgroup/'cpu.max').write_bytes(b'max 100000\n')
            (cgroup/'memory.max').write_bytes(b'max\n')
            (cgroup/'memory.current').write_bytes(b'0\n')
            result = M.engine_cgroup_resources(CID, self.state(), {}, deadline=float('inf'))
        self.assertTrue(result['available'])
        self.assertIsNone(result['cpu_quota_usec'])
        self.assertIsNone(result['memory_max_bytes'])
        self.assertEqual(result['memory_current_bytes'], 0)

    def test_unverified_stopped_missing_and_invalid_pid_never_open_kernel_files(self):
        for identity, state in ((CID, None), ('private', self.state()),
                                (CID, dict(running=False,pid=PID)),
                                (CID, dict(running=True,pid=True)),
                                (CID, dict(running=True,pid=0)),
                                (CID, dict(running=True,pid=2**31))):
            with self.subTest(state=state), patch.object(M.os, 'open') as opened:
                result = M.engine_cgroup_resources(identity, state, {}, deadline=float('inf'))
            opened.assert_not_called()
            self.assertEqual(result, dict(available=False,code='CGROUP_RESOURCE_UNAVAILABLE'))

    def test_v1_root_wrong_container_and_traversal_paths_never_open_cgroup_tree(self):
        raws = (b'1:cpu:/docker/'+CID.encode()+b'\n', b'0::/\n',
                b'0::/system.slice/docker-'+b'e'*64+b'.scope\n',
                b'0::/../system.slice/docker-'+CID.encode()+b'.scope\n',
                b'0::/system.slice/./docker-'+CID.encode()+b'.scope\n',
                b'0::/system.slice//docker-'+CID.encode()+b'.scope\n',
                b'0::/system.slice/docker-'+CID.encode()+b'.scope\n0::/other\n',
                b'x'*4097, b'\xff')
        for raw in raws:
            with self.subTest(size=len(raw)), self.fixture() as (_, proc, _, opened):
                (proc/'cgroup').write_bytes(raw)
                result = M.engine_cgroup_resources(CID, self.state(), {}, deadline=float('inf'))
                self.assertFalse(result['available'])
                self.assertNotIn('sys', opened)

    def test_cgroupfs_driver_is_supported_without_directory_search(self):
        with self.fixture() as (root, proc, cgroup, opened):
            destination = root/'sys/fs/cgroup/docker'/CID
            destination.parent.mkdir()
            cgroup.rename(destination)
            (proc/'cgroup').write_bytes(('0::/docker/'+CID+'\n').encode())
            result = M.engine_cgroup_resources(CID, self.state(), {}, deadline=float('inf'))
        self.assertTrue(result['available'])
        self.assertNotIn('private', opened)

    def test_symlink_directory_file_and_fifo_are_rejected(self):
        for mode in ('directory', 'file', 'fifo'):
            with self.subTest(mode=mode), self.fixture() as (root, _, cgroup, _):
                if mode == 'directory':
                    target = root/'elsewhere'
                    cgroup.rename(target)
                    cgroup.symlink_to(target, target_is_directory=True)
                else:
                    (cgroup/'cpu.stat').unlink()
                    if mode == 'file': (cgroup/'cpu.stat').symlink_to(root/'proc/meminfo')
                    else: os.mkfifo(cgroup/'cpu.stat')
                result = M.engine_cgroup_resources(CID, self.state(), {}, deadline=float('inf'))
                self.assertFalse(result['available'])

    def test_invalid_numbers_duplicate_known_fields_missing_and_oversize_fail_closed(self):
        for filename, raw in (('cpu.stat', b'usage_usec -1\nnr_periods 1\nnr_throttled 0\nthrottled_usec 0\n'),
                               ('cpu.stat', b'usage_usec 1\nusage_usec 2\n'),
                               ('cpu.stat', b'x'*4097), ('cpu.max',b'0 100000\n'),
                               ('cpu.max',b'50000 0\n'), ('cpu.max',b'50000 100000 private\n'),
                               ('memory.current', b'9223372036854775808\n'),
                               ('memory.max', b'NaN\n'), ('memory.events',b'oom private\n')):
            with self.subTest(filename=filename), self.fixture() as (_, _, cgroup, _):
                (cgroup/filename).write_bytes(raw)
                result = M.engine_cgroup_resources(CID, self.state(), {}, deadline=float('inf'))
                self.assertEqual(result, dict(available=False, code='CGROUP_RESOURCE_UNAVAILABLE'))
                self.assertNotIn('private', json.dumps(result))

    def test_postflight_refuses_pid_reuse_cgroup_move_and_replaced_cgroup_directory(self):
        for change in ('pid', 'start', 'mapping', 'directory', 'missing'):
            with self.subTest(change=change), self.fixture() as (_, proc, cgroup, _):
                guard = {}
                self.assertTrue(M.engine_cgroup_resources(CID, self.state(), guard, deadline=float('inf'))['available'])
                state = self.state()
                if change == 'pid': state['pid'] += 1
                elif change == 'start': (proc/'stat').write_bytes(str(PID).encode()+b' (private) S '+b'0 '*18+b'888 0\n')
                elif change == 'mapping': (proc/'cgroup').write_bytes(b'0::/other\n')
                elif change == 'directory':
                    cgroup.rename(cgroup.with_name('old'))
                    cgroup.mkdir()
                else: (proc/'stat').unlink()
                self.assertFalse(M.resource_identity_unchanged(CID, state, guard))

    def test_exhausted_budget_never_opens_metadata_and_stats_keeps_four_second_total(self):
        with patch.object(M.time,'monotonic',return_value=14.), patch.object(M.os,'open') as opened:
            self.assertFalse(M.host_memory_metadata(deadline=14.)['available'])
            self.assertFalse(M.engine_cgroup_resources(CID,self.state(),{},deadline=14.)['available'])
        opened.assert_not_called()
        capture = dict(reason=None,exit_code=0,stdout=previous.CollectionTest().resource_raw(),stderr=b'')
        with patch.object(M,'host_resources',return_value={}), \
                patch.object(M,'host_memory_metadata',return_value=dict(available=False,code='HOST_MEMORY_UNAVAILABLE')) as host, \
                patch.object(M,'engine_cgroup_resources',return_value=dict(available=False,code='CGROUP_RESOURCE_UNAVAILABLE')) as cgroup, \
                patch.object(M.time,'monotonic',side_effect=(10.,11.)), \
                patch.object(M,'capture_process',return_value=capture) as command:
            M.runtime_resource_sample(CID,'7'*64,engine_state=self.state(),identity_guard={})
        self.assertEqual(host.call_args.kwargs,dict(deadline=14.))
        self.assertEqual(cgroup.call_args.kwargs,dict(deadline=14.))
        self.assertEqual(command.call_args.kwargs['timeout'],3.)
        self.assertEqual(command.call_args.kwargs['absolute_deadline'],14.)


if __name__ == '__main__':
    unittest.main()
