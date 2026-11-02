"""Opaque synthetic files/fake proc/cgroups only. No Docker, GPG, DB or network."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import threading
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


s = module('data_archive', HERE.parent / 'retirement_data_archive.py')
fixtures = module('data_archive_fixtures', HERE / 'test_retirement_data_preflight.py')
p = fixtures.s
CANARY = fixtures.CANARY


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.Fixture('test_complete_fixture_reports_finite_coverage_without_stop_claim')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.files, self.proc, self.request = self.f.files, self.f.proc, self.f.request
        self.paused = True
        self.docker = p.Docker(time.monotonic() + 30, self.command)
        for alias, selection in self.request.items():
            pid = selection['pid']
            self.f.mkdir('/proc/' + str(pid) + '/task/' + str(pid))
            self.f.mkdir('/proc/' + str(pid) + '/map_files')
            relative = '/system.slice/docker-' + selection['id'] + '.scope'
            self.f.write('/proc/' + str(pid) + '/cgroup', ('0::' + relative + '\n').encode())
            folder = '/sys/fs/cgroup' + relative
            self.f.mkdir(folder)
            for name, data in {'cgroup.freeze': b'1\n', 'cgroup.events': b'populated 1\nfrozen 1\n',
                               'cgroup.procs': str(pid).encode(), 'cgroup.threads': str(pid).encode()}.items():
                self.f.write(folder + '/' + name, data)
        self.f.write(p.ROOTS['ad'] + '/app.db-wal', b'SYNTHETIC_COMMITTED_WAL')
        self.f.write(p.ROOTS['ad'] + '/app.db-shm', b'SYNTHETIC_SHARED_INDEX')
        self.f.write(p.ROOTS['content'] + '/copy.db-journal', b'SYNTHETIC_HOT_JOURNAL')
        self.f.write(p.ROOTS['content'] + '/nested/' + CANARY + '.json', b'{"opaque":true}')
        self.f.mkdir(p.ROOTS['content'] + '/empty-directory')
        self.f.write('/root/ad-dashboard-deploy/docker-compose.yml', b'services:\n  synthetic-ad: {}\n')
        self.f.write('/root/content-studio-deploy/docker-compose.yml', b'services:\n  synthetic-content: {}\n')
        for alias, format_name, path in s.CONFIG_FILES:
            if format_name == 'opaque-nginx':
                self.f.write(path, b'server { location /synthetic { return 503; } }\n')
        self.journal = {'schema': 'metainc-retirement-original-restart-v1', 'session': s.SESSION,
            'status': 'fence_complete', 'run': '123-1', 'operator_evidence_sha256': 'c' * 64,
            'control_policy_sha256': 'd' * 64,
            'daemon': {'version': '29.4.0', 'git_commit': 'abc1234', 'os': 'linux', 'arch': 'amd64'},
            'containers': {alias: {'id': value['id'], 'image': p.IMAGES[alias],
                'started_at': '2026-11-01T00:00:00.000000001Z',
                'restart_policy': {'Name': 'unless-stopped', 'MaximumRetryCount': 0}}
                for alias, value in self.request.items()}}
        self.write_journal()
        self.f.local('/root/.metainc-retirement-control').chmod(0o700)
        self.f.local(s.RESTART_JOURNAL).parent.chmod(0o700)
        self.payload = b''

    def write_journal(self):
        body = json.dumps(self.journal, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
        self.f.write(s.RESTART_JOURNAL, body)
        self.f.local(s.RESTART_JOURNAL).chmod(0o600)
        self.restart_evidence = {'sha256': hashlib.sha256(body).hexdigest(),
            'operator_evidence_sha256': 'c' * 64, 'control_policy_sha256': 'd' * 64}

    def command(self, args):
        if args[0] == 'inspect' and '"started_at"' in args[2]:
            alias = 'ad' if args[-1] == 'a' * 64 else 'content'
            return json.dumps({'id': self.request[alias]['id'], 'image': p.IMAGES[alias],
                'started_at': '2026-11-01T00:00:00.000000001Z',
                'restart_policy': {'Name': 'no', 'MaximumRetryCount': 0}}).encode()
        if args[0] == 'inspect' and '"paused"' in args[2]:
            value = self.request['ad' if args[-1] == 'a' * 64 else 'content']
            return json.dumps(dict(id=value['id'], pid=value['pid'], running=True,
                                  paused=self.paused, restarting=False)).encode()
        if args[0] == 'inspect' and '"host_config"' in args[2]:
            alias = 'ad' if args[-1] == 'a' * 64 else 'content'
            config = dict.fromkeys(s.CONFIG_FIELDS)
            config.update(Env=['SECRET=' + CANARY], Cmd=['synthetic-server'], WorkingDir='/app')
            host = dict.fromkeys(s.HOST_FIELDS)
            host['RestartPolicy'] = {'Name': 'no', 'MaximumRetryCount': 0}
            return json.dumps({'id': self.request[alias]['id'], 'name': p.NAMES[alias],
                'image': p.IMAGES[alias], 'config': config, 'host_config': host,
                'networks': {'synthetic': {'Aliases': [alias]}}}).encode()
        return self.f.run_docker(args)

    def group(self, alias='ad', version='v2'):
        return '/sys/fs/cgroup' + ('/freezer' if version == 'v1' else '') + '/system.slice/docker-' + self.request[alias]['id'] + '.scope'

    def run_archive(self):
        read, write = os.pipe()
        chunks = []
        def drain():
            try:
                while True:
                    block = os.read(read, 65536)
                    if not block:
                        return
                    chunks.append(block)
            finally:
                os.close(read)
        thread = threading.Thread(target=drain)
        thread.start()
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                return s.archive_snapshot(p, self.request, write, files=self.files, docker=self.docker,
                                          proc=self.proc, restart_evidence=self.restart_evidence)
        finally:
            os.close(write); thread.join(2)
            self.assertFalse(thread.is_alive())
            self.payload = b''.join(chunks)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue(), '')

    def manifest(self):
        archive = tarfile.open(fileobj=io.BytesIO(self.payload), mode='r:')
        members = archive.getmembers()
        self.assertEqual(members[-1].name, 'manifest.json')
        manifest = json.load(archive.extractfile(members[-1]))
        return archive, members, manifest

    def denied(self, code=None):
        with self.assertRaises(s.Refused) as caught:
            self.run_archive()
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertNotIn(CANARY, str(caught.exception))

    def test_complete_opaque_snapshot_canonical_objects_and_encrypted_manifest_contract(self):
        result = self.run_archive()
        self.assertEqual(result['status'], 'archive_stream_complete')
        self.assertFalse(result['application_restore_verified'])
        self.assertEqual(result['archive_bytes'], len(self.payload))
        self.assertNotIn(CANARY, json.dumps(result))
        archive, members, manifest = self.manifest()
        self.assertEqual(set(manifest), {'schema', 'session', 'consistency', 'application_restore_verified',
            'scopes', 'containers', 'entries', 'deleted', 'recovery_config', 'recovery_config_absent', 'object_count', 'source_bytes'})
        self.assertEqual(manifest['schema'], s.SCHEMA)
        self.assertEqual(manifest['scopes'], list(s.SCOPES))
        self.assertEqual(sum(row['relative_path'] == '' for row in manifest['entries']), 4)
        names = [row['relative_path'] for row in manifest['entries']]
        for name in ('app.db-wal', 'app.db-shm', 'copy.db-journal', 'empty-directory', 'nested/' + CANARY + '.json'):
            self.assertIn(name, names)
        files = [row for row in manifest['entries'] if row['kind'] == 'file']
        self.assertEqual([row['object'] for row in files], ['objects/' + str(i).zfill(8) for i in range(1, len(files) + 1)])
        self.assertEqual([row['alias'] for row in manifest['recovery_config']], ['original-restart-policy',
            'ad-container', 'content-container', 'ad-compose', 'content-compose', 'autobid-environment',
            'nginx-ad', 'nginx-logic', 'nginx-studio', 'content-dotenv'])
        self.assertEqual(manifest['recovery_config_absent'], [])
        for row in manifest['recovery_config']:
            body = archive.extractfile(row['object']).read()
            self.assertEqual(len(body), row['bytes'])
            self.assertEqual(hashlib.sha256(body).hexdigest(), row['sha256'])
            if row['format'] == 'docker-json':
                self.assertIsNone(row['source_metadata'])
                self.assertIn(CANARY, json.loads(body)['config']['Env'][0])
            else:
                self.assertEqual(len(row['source_metadata']), 9)
                self.assertEqual(row['source_metadata']['bytes'], len(body))
                self.assertEqual(row['source_metadata']['links'], 1)
        for row in files:
            data = archive.extractfile(row['object']).read()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'])
            self.assertEqual(len(data), row['metadata']['bytes'])
        for member in members:
            self.assertEqual((member.mode, member.uid, member.gid, member.mtime), (0o600, 0, 0, 0))
            self.assertTrue(member.isreg())
            self.assertEqual(member.pax_headers, {})
            self.assertNotIn(CANARY, member.name)
        tail = members[-1].offset_data + ((members[-1].size + 511) // 512) * 512
        self.assertEqual(self.payload[tail:], b'\0' * 1024)

    def test_not_paused_or_restarting_never_produces_bytes(self):
        self.paused = False
        self.denied('not_frozen')
        self.assertEqual(self.payload, b'')

    def test_cgroup_not_fully_frozen_missing_tasks_and_child_group_refused(self):
        for file, data, error in (('cgroup.freeze', b'0', 'not_frozen'),
                ('cgroup.events', b'populated 1\nfrozen 0', 'not_frozen'),
                ('cgroup.procs', b'101\n102', 'cgroup_tasks_changed'),
                ('cgroup.threads', b'101\n102', 'cgroup_tasks_changed')):
            target = self.f.local(self.group() + '/' + file); original = target.read_bytes()
            target.write_bytes(data)
            with self.subTest(file=file):
                self.denied(error); self.assertEqual(self.payload, b'')
            target.write_bytes(original)
        self.f.mkdir(self.group() + '/nested')
        self.denied('nested_cgroup_uncovered')

    def test_all_container_threads_must_match_frozen_group(self):
        self.f.mkdir('/proc/101/task/102')
        self.denied('cgroup_tasks_changed')
        self.f.write(self.group() + '/cgroup.threads', b'101\n102')
        self.assertEqual(self.run_archive()['status'], 'archive_stream_complete')

    def test_v1_freezer_exact_tasks_is_supported_without_v2_guessing(self):
        for alias, value in self.request.items():
            relative = '/system.slice/docker-' + value['id'] + '.scope'
            self.f.write('/proc/' + str(value['pid']) + '/cgroup', ('4:freezer:' + relative + '\n').encode())
            self.f.write(self.group(alias, 'v1') + '/freezer.state', b'FROZEN\n')
            self.f.write(self.group(alias, 'v1') + '/tasks', str(value['pid']).encode())
        self.assertEqual(self.run_archive()['status'], 'archive_stream_complete')
        self.f.write(self.group('content', 'v1') + '/freezer.state', b'FREEZING')
        self.denied('not_frozen')

    def test_unreviewed_cgroup_or_malformed_metadata_has_no_stream(self):
        for body in (b'0::/other\n', b'0::/../../outside\n', b'0::/docker/' + b'a' * 64 + b'\n0::/other\n', b'invalid'):
            self.f.write('/proc/101/cgroup', body)
            self.denied('cgroup_unconfirmed'); self.assertEqual(self.payload, b'')

    def test_root_tree_symlink_hardlink_fifo_and_name_are_never_skipped(self):
        folder = self.f.local(p.ROOTS['ad'])
        for kind in ('symlink', 'hardlink', 'fifo', 'control'):
            target = folder / (CANARY if kind != 'control' else 'bad\nname')
            if kind == 'symlink': target.symlink_to(folder / 'app.db')
            elif kind == 'hardlink': os.link(folder / 'app.db', target)
            elif kind == 'fifo': os.mkfifo(target)
            else: target.write_text(CANARY)
            with self.subTest(kind=kind): self.denied(); self.assertEqual(self.payload, b'')
            target.unlink()

    def test_total_data_and_entry_limits_fail_without_silently_truncating(self):
        with mock.patch.object(s, 'MAX_BYTES', 10): self.denied('data_size_limit')
        with mock.patch.object(s, 'MAX_ENTRIES', 5): self.denied('entry_limit')

    def test_incomplete_preflight_is_not_a_snapshot_even_when_paused(self):
        self.f.env['ad'] = ['DB_PATH=/uncovered/' + CANARY]
        self.denied('coverage_incomplete'); self.assertEqual(self.payload, b'')

    def test_copied_file_change_is_detected_before_manifest(self):
        original = s.Snapshot.content
        changed = [False]
        def mutate(snapshot, row, sink=None):
            answer = original(snapshot, row, sink)
            if sink is not None and not changed[0]:
                changed[0] = True
                self.f.local(p.ROOTS['ad'] + '/app.db').write_bytes(b'x' * len(CANARY))
            return answer
        with mock.patch.object(s.Snapshot, 'content', mutate): self.denied()
        self.assertNotIn(b'manifest.json', self.payload)

    def test_new_directory_member_during_copy_is_detected_before_manifest(self):
        original = s.Snapshot.content
        changed = [False]
        def mutate(snapshot, row, sink=None):
            answer = original(snapshot, row, sink)
            if sink is not None and not changed[0]:
                changed[0] = True; self.f.write(p.ROOTS['autobid'] + '/new.json', b'NEW')
            return answer
        with mock.patch.object(s.Snapshot, 'content', mutate): self.denied('tree_changed')
        self.assertNotIn(b'manifest.json', self.payload)

    def test_second_complete_content_hash_is_required(self):
        original = s.Snapshot.content
        def altered(snapshot, row, sink=None):
            answer = original(snapshot, row, sink)
            return '0' * 64 if sink is None else answer
        with mock.patch.object(s.Snapshot, 'content', altered): self.denied('content_changed')
        self.assertNotIn(b'manifest.json', self.payload)

    def test_unpause_during_copy_invalidates_entire_stream(self):
        original = s.Snapshot.content
        def unpause(snapshot, row, sink=None):
            answer = original(snapshot, row, sink)
            if sink is not None: self.paused = False
            return answer
        with mock.patch.object(s.Snapshot, 'content', unpause): self.denied('not_frozen')
        self.assertNotIn(b'manifest.json', self.payload)

    def test_final_external_writer_or_guard_change_blocks_manifest(self):
        original = p.collect
        count = [0]
        def changed(*args, **kwargs):
            result = original(*args, **kwargs); count[0] += 1
            if count[0] > 1: result['host']['external_writers'] = 1
            return result
        with mock.patch.object(p, 'collect', changed): self.denied('coverage_incomplete')
        self.assertNotIn(b'manifest.json', self.payload)

    def test_direct_io_is_explicitly_uncovered(self):
        self.f.fd(101, 3, p.ROOTS['ad'] + '/app.db', flags=2 | 0o40000)
        self.denied('direct_io_uncovered'); self.assertEqual(self.payload, b'')

    def test_named_shared_mapping_is_pinned_and_unpinnable_mapping_fails(self):
        path = p.ROOTS['ad'] + '/app.db-shm'
        self.f.map(101, path)
        self.denied('mapping_unpinned'); self.assertEqual(self.payload, b'')
        self.f.local('/proc/101/map_files/1000-2000').symlink_to(self.f.local(path))
        self.assertEqual(self.run_archive()['status'], 'archive_stream_complete')

    def test_regular_output_file_and_cli_are_refused_without_bytes(self):
        with self.f.local('/sink').open('wb') as sink, self.assertRaises(s.Refused) as caught:
            s.archive_snapshot(p, self.request, sink.fileno(), files=self.files, docker=self.docker, proc=self.proc)
        self.assertEqual(caught.exception.code, 'encrypted_pipe_required')
        self.assertEqual(self.f.local('/sink').read_bytes(), b'')
        result = subprocess.run([sys.executable, '-I', '-B', str(HERE.parent / 'retirement_data_archive.py')],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, b'', b''))

    def deleted_file(self, body=b'NONZERO_DELETED_OPAQUE_BYTES', references=(101,), number=3):
        if sys.platform == 'darwin' and not getattr(self, '_proc_fd_adapter', False):
            # macOS /dev/fd stat reports fdescfs st_dev, whereas Linux proc-fd
            # stat reports the backing file. Adapt only this synthetic link.
            real_stat = os.stat
            def proc_stat(path, *args, **kwargs):
                if kwargs.get('follow_symlinks', True):
                    try:
                        link = os.readlink(path, dir_fd=kwargs.get('dir_fd'))
                        if link.startswith('/dev/fd/') and link[8:].isdigit():
                            return os.fstat(int(link[8:]))
                    except OSError:
                        pass
                return real_stat(path, *args, **kwargs)
            self.f.stack.enter_context(mock.patch.object(os, 'stat', side_effect=proc_stat))
            self._proc_fd_adapter = True
        path = self.f.local('/deleted-holder')
        holder = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        self.addCleanup(os.close, holder)
        os.write(holder, body); os.unlink(path)
        os.lseek(holder, min(7, len(body)), os.SEEK_SET)
        target = ('/proc/self/fd/' if os.path.isdir('/proc/self/fd') else '/dev/fd/') + str(holder)
        for pid in references:
            self.f.local('/proc/' + str(pid) + '/fd/' + str(number)).symlink_to(target)
            self.f.write('/proc/' + str(pid) + '/fdinfo/' + str(number), b'flags:\t2\nmnt_id:\t1\n')
        return holder

    def test_eight_empty_deleted_identities_from_both_apps_keep_all_sixteen_refs(self):
        for pid in (101, 201):
            for number in (3, 5, 7, 9):
                self.deleted_file(b'', (pid,), number)
                folder = self.f.local('/proc/' + str(pid))
                (folder / 'fd' / str(number + 1)).symlink_to(os.readlink(folder / 'fd' / str(number)))
                self.f.write('/proc/' + str(pid) + '/fdinfo/' + str(number + 1), b'flags:\t2\nmnt_id:\t1\n')
        self.run_archive()
        archive, _, manifest = self.manifest()
        self.assertEqual(len(manifest['deleted']), 8)
        self.assertEqual(sum(len(row['refs']) for row in manifest['deleted']), 16)
        self.assertEqual({pid: sum(all(ref['pid'] == pid for ref in row['refs'])
                                  for row in manifest['deleted']) for pid in (101, 201)}, {101: 4, 201: 4})
        for row in manifest['deleted']:
            self.assertEqual(row['metadata']['bytes'], 0)
            self.assertEqual(archive.extractfile(row['object']).read(), b'')

    def test_deleted_nonzero_and_zero_bytes_are_kept_and_shared_refs_deduplicated(self):
        for body in (b'NONZERO_DELETED_OPAQUE_BYTES', b''):
            with self.subTest(bytes=len(body)):
                holder = self.deleted_file(body, (101, 201))
                offset = os.lseek(holder, 0, os.SEEK_CUR)
                self.run_archive()
                archive, _, manifest = self.manifest()
                self.assertEqual(len(manifest['deleted']), 1)
                row = manifest['deleted'][0]
                self.assertEqual(len(row['refs']), 2)
                self.assertEqual(row['metadata']['links'], 0)
                self.assertEqual(row['metadata']['bytes'], len(body))
                self.assertEqual(archive.extractfile(row['object']).read(), body)
                self.assertEqual(hashlib.sha256(body).hexdigest(), row['sha256'])
                self.assertEqual(os.lseek(holder, 0, os.SEEK_CUR), offset)
                self.assertEqual([ref['pid'] for ref in row['refs']], [101, 201])
                self.assertTrue(all(len(ref['process_identity']) == 6 and len(ref['file_identity']) == 9 for ref in row['refs']))
                for pid in (101, 201): self.f.local('/proc/' + str(pid) + '/fd/3').unlink()

    def test_deleted_fd_target_replacement_and_flag_change_fail_before_terminal(self):
        self.deleted_file()
        original = s.Snapshot.content
        changed = [False]
        def mutate(snapshot, row, sink=None):
            answer = original(snapshot, row, sink)
            if sink is not None and 'fd' in row and not changed[0]:
                changed[0] = True
                self.f.local('/proc/101/fd/3').unlink()
                self.f.local('/proc/101/fd/3').symlink_to(self.f.local(p.ROOTS['ad'] + '/app.db'))
            return answer
        with mock.patch.object(s.Snapshot, 'content', mutate): self.denied('deleted_changed')
        self.assertNotIn(b'manifest.json', self.payload)

    def test_deleted_pin_is_closed_on_success_and_failure(self):
        self.deleted_file()
        pins = []
        original = s.Snapshot.pin_deleted
        def remember(snapshot):
            original(snapshot); pins.extend(row['fd'] for row in snapshot.deleted)
        with mock.patch.object(s.Snapshot, 'pin_deleted', remember): self.run_archive()
        for fd in pins:
            with self.assertRaises(OSError): os.fstat(fd)
        pins.clear()
        with mock.patch.object(s.Snapshot, 'pin_deleted', remember), mock.patch.object(s, 'MAX_MANIFEST', 1): self.denied('manifest_size_limit')
        for fd in pins:
            with self.assertRaises(OSError): os.fstat(fd)

    def test_mapping_pin_replacement_during_copy_is_not_accepted(self):
        path = p.ROOTS['ad'] + '/app.db-shm'; self.f.map(101, path)
        link = self.f.local('/proc/101/map_files/1000-2000'); link.symlink_to(self.f.local(path))
        original = s.Snapshot.content
        changed = [False]
        def mutate(snapshot, row, sink=None):
            answer = original(snapshot, row, sink)
            if sink is not None and not changed[0]:
                changed[0] = True; link.unlink(); link.symlink_to(self.f.local(p.ROOTS['ad'] + '/app.db'))
            return answer
        with mock.patch.object(s.Snapshot, 'content', mutate): self.denied('mapping_changed')
        self.assertNotIn(b'manifest.json', self.payload)

    def test_process_starttime_change_during_copy_refuses_snapshot(self):
        original = s.Snapshot.content
        changed = [False]
        def mutate(snapshot, row, sink=None):
            answer = original(snapshot, row, sink)
            if sink is not None and not changed[0]:
                changed[0] = True
                path = self.f.local('/proc/101/stat'); body = path.read_bytes()
                path.write_bytes(body.replace(b'1101', b'1102'))
            return answer
        with mock.patch.object(s.Snapshot, 'content', mutate): self.denied('freeze_changed')
        self.assertNotIn(b'manifest.json', self.payload)

    def test_manifest_limit_and_deadline_never_make_complete_archive(self):
        with mock.patch.object(s, 'MAX_MANIFEST', 10): self.denied('manifest_size_limit')
        self.assertNotIn(b'manifest.json', self.payload)
        with mock.patch.object(s, 'TIMEOUT', 0): self.denied('archive_timeout')

    def test_pread_retains_original_regular_file_offset(self):
        path = self.f.local(p.ROOTS['ad'] + '/app.db')
        holder = os.open(path, os.O_RDONLY)
        self.addCleanup(os.close, holder)
        os.lseek(holder, 7, os.SEEK_SET)
        original = s.Snapshot.opened
        @contextlib.contextmanager
        def shared(snapshot, row):
            if row['scope'] == 'ad' and row['relative_path'] == 'app.db': yield holder
            else:
                with original(snapshot, row) as fd: yield fd
        with mock.patch.object(s.Snapshot, 'opened', shared): self.run_archive()
        self.assertEqual(os.lseek(holder, 0, os.SEEK_CUR), 7)

    def test_pipe_backpressure_deadline_restores_flags(self):
        read, write = os.pipe()
        self.addCleanup(os.close, read); self.addCleanup(os.close, write)
        was_blocking = os.get_blocking(write)
        with self.assertRaises(s.Refused) as caught:
            with s.Sink(write, time.monotonic() + .05) as sink: sink.write(b'x' * 1024 ** 2)
        self.assertEqual(caught.exception.code, 'archive_timeout')
        self.assertEqual(os.get_blocking(write), was_blocking)

    def test_effective_configuration_change_after_stream_refuses_manifest(self):
        original = self.command
        seen = [0]
        def changed(args):
            body = original(args)
            if args[0] == 'inspect' and '"host_config"' in args[2]:
                seen[0] += 1
                if seen[0] > 2:
                    value = json.loads(body); value['config']['Env'] = ['CHANGED_SECRET=' + CANARY]
                    return json.dumps(value).encode()
            return body
        self.docker.runner = changed
        self.denied('configuration_changed')
        self.assertNotIn(b'manifest.json', self.payload)

    def test_original_policy_is_preserved_and_current_fenced_policy_is_separate(self):
        self.run_archive()
        archive, _, manifest = self.manifest()
        row = next(row for row in manifest['recovery_config'] if row['alias'] == 'original-restart-policy')
        self.assertEqual(row['format'], 'restart-json')
        self.assertEqual(row['source_metadata']['mode'] & 0o777, 0o600)
        self.assertEqual(row['sha256'], self.restart_evidence['sha256'])
        self.assertEqual(json.load(archive.extractfile(row['object'])), self.journal)
        self.assertEqual(self.journal['containers']['ad']['restart_policy']['Name'], 'unless-stopped')

    def test_missing_unpinned_or_hash_changed_original_policy_has_no_archive(self):
        original = self.restart_evidence
        for evidence in (None, {}, {**original, 'sha256': '0' * 64}, {**original, 'sha256': 'f' * 64}):
            self.restart_evidence = evidence
            with self.subTest(evidence=evidence):
                self.denied('restart_evidence_unconfirmed'); self.assertEqual(self.payload, b'')
        self.restart_evidence = original
        self.f.local(s.RESTART_JOURNAL).unlink()
        self.denied(); self.assertEqual(self.payload, b'')

    def test_journal_is_bounded_root_private_regular_single_link(self):
        target = self.f.local(s.RESTART_JOURNAL)
        original = target.read_bytes()
        for kind in ('symlink', 'hardlink', 'fifo', 'oversize', 'mode'):
            target.unlink()
            extra = target.with_name('other')
            if kind == 'symlink': target.symlink_to('other')
            elif kind == 'hardlink':
                target.write_bytes(original); os.link(target, extra)
            elif kind == 'fifo': os.mkfifo(target)
            elif kind == 'oversize': target.write_bytes(b'x' * (s.MAX_RESTART_JOURNAL + 1))
            else: target.write_bytes(original); target.chmod(0o644)
            with self.subTest(kind=kind):
                self.denied('restart_evidence_unconfirmed'); self.assertEqual(self.payload, b'')
            target.unlink(); target.write_bytes(original); target.chmod(0o600)
            if extra.exists(): extra.unlink()

    def test_reviewed_journal_schema_ids_and_current_start_are_bound(self):
        original = json.loads(json.dumps(self.journal))
        changes = [lambda value: value.update(status='fence_partial'),
            lambda value: value.update(run='123-2'),
            lambda value: value.update(operator_evidence_sha256='e' * 64),
            lambda value: value['containers']['ad'].update(id='f' * 64),
            lambda value: value['containers']['content'].update(started_at='2026-11-02T00:00:00Z'),
            lambda value: value['containers']['ad']['restart_policy'].update(MaximumRetryCount=True)]
        for change in changes:
            self.journal = json.loads(json.dumps(original)); change(self.journal); self.write_journal()
            with self.subTest(change=change):
                self.denied('restart_evidence_unconfirmed'); self.assertEqual(self.payload, b'')

    def test_pinned_journal_descriptor_and_directory_identity_survive_whole_stream(self):
        original = s.Snapshot.content
        for kind in ('replace', 'content', 'directory'):
            changed = [False]
            def mutate(snapshot, row, sink=None):
                answer = original(snapshot, row, sink)
                if sink is not None and not changed[0]:
                    changed[0] = True
                    path = self.f.local(s.RESTART_JOURNAL)
                    if kind == 'replace':
                        body = path.read_bytes(); path.unlink(); path.write_bytes(body); path.chmod(0o600)
                    elif kind == 'content': path.write_bytes(path.read_bytes().replace(b'123-1', b'124-1'))
                    else: path.parent.chmod(0o755); path.parent.chmod(0o700)
                return answer
            self.write_journal()
            with self.subTest(kind=kind), mock.patch.object(s.Snapshot, 'content', mutate):
                self.denied('configuration_changed'); self.assertNotIn(b'manifest.json', self.payload)

    def test_all_three_observed_nginx_files_are_required_opaque_preimages(self):
        self.run_archive()
        archive, _, manifest = self.manifest()
        rows = [row for row in manifest['recovery_config'] if row['format'] == 'opaque-nginx']
        self.assertEqual([row['alias'] for row in rows], ['nginx-ad', 'nginx-logic', 'nginx-studio'])
        for row, (_, _, path) in zip(rows, [item for item in s.CONFIG_FILES if item[1] == 'opaque-nginx']):
            self.assertEqual(archive.extractfile(row['object']).read(), self.f.local(path).read_bytes())
        self.f.local('/etc/nginx/sites-enabled/logic-analysis').unlink()
        self.denied('configuration_missing'); self.assertEqual(self.payload, b'')

    def test_configuration_bound_and_wrong_identity_stop_before_any_bytes(self):
        with mock.patch.object(s, 'MAX_CONFIG_FILE', 32): self.denied('configuration_limit')
        self.assertEqual(self.payload, b'')
        original = self.command
        def changed(args):
            body = original(args)
            if args[0] == 'inspect' and '"host_config"' in args[2]:
                value = json.loads(body); value['image'] = 'sha256:' + '0' * 64
                return json.dumps(value).encode()
            return body
        self.docker.runner = changed
        self.denied('configuration_unconfirmed'); self.assertEqual(self.payload, b'')

    def test_optional_content_environment_absence_is_explicit(self):
        self.f.local('/containers/content/app/.env').unlink()
        self.run_archive()
        _, _, manifest = self.manifest()
        self.assertEqual(manifest['recovery_config_absent'], ['content-dotenv'])
        self.assertEqual(len(manifest['recovery_config']), 9)
        self.assertNotIn('content-dotenv', {row['alias'] for row in manifest['recovery_config']})

    def test_required_configuration_absence_has_no_stream(self):
        self.f.local('/root/ad-dashboard-deploy/docker-compose.yml').unlink()
        self.denied('configuration_missing'); self.assertEqual(self.payload, b'')

    def test_configuration_symlink_hardlink_fifo_and_oversize_are_refused(self):
        target = self.f.local('/root/ad-dashboard-deploy/docker-compose.yml')
        original = target.read_bytes()
        for kind in ('symlink', 'hardlink', 'fifo', 'oversize'):
            target.unlink()
            if kind == 'symlink': target.symlink_to(self.f.local(p.ROOTS['ad'] + '/app.db'))
            elif kind == 'hardlink': os.link(self.f.local(p.ROOTS['ad'] + '/app.db'), target)
            elif kind == 'fifo': os.mkfifo(target)
            else: target.write_bytes(b'x' * (s.MAX_CONFIG_FILE + 1))
            with self.subTest(kind=kind):
                self.denied(); self.assertEqual(self.payload, b'')
            target.unlink(); target.write_bytes(original)

    def test_content_environment_uses_pinned_container_root_not_host_app(self):
        self.f.write('/app/.env', b'HOST_ONLY_WRONG_CONTENT')
        self.run_archive()
        archive, _, manifest = self.manifest()
        row = next(row for row in manifest['recovery_config'] if row['alias'] == 'content-dotenv')
        self.assertEqual(archive.extractfile(row['object']).read(), self.f.local('/containers/content/app/.env').read_bytes())
        self.assertNotIn(b'HOST_ONLY_WRONG_CONTENT', self.payload)

    def test_config_replacement_and_optional_presence_drift_refuse_manifest(self):
        original = s.Snapshot.content
        for scenario in ('replace', 'appear', 'disappear'):
            content_env = self.f.local('/containers/content/app/.env')
            if scenario == 'appear': content_env.unlink()
            elif not content_env.exists(): content_env.write_bytes(('SECRET=' + CANARY).encode())
            changed = [False]
            def mutate(snapshot, row, sink=None):
                answer = original(snapshot, row, sink)
                if sink is not None and not changed[0]:
                    changed[0] = True
                    if scenario == 'replace':
                        path = self.f.local('/root/ad-dashboard-deploy/docker-compose.yml')
                        data = path.read_bytes(); path.unlink(); path.write_bytes(data)
                    elif scenario == 'appear': content_env.write_bytes(('SECRET=' + CANARY).encode())
                    else: content_env.unlink()
                return answer
            with self.subTest(scenario=scenario), mock.patch.object(s.Snapshot, 'content', mutate):
                self.denied('configuration_changed')
                self.assertNotIn(b'manifest.json', self.payload)

    def test_config_parent_ctime_change_even_with_mode_restored_is_refused(self):
        original = s.Snapshot.content
        changed = [False]
        def mutate(snapshot, row, sink=None):
            answer = original(snapshot, row, sink)
            if sink is not None and not changed[0]:
                changed[0] = True
                directory = self.f.local('/root/content-studio-deploy/autobid')
                mode = directory.stat().st_mode & 0o777
                directory.chmod(0o700 if mode != 0o700 else 0o755)
                directory.chmod(mode)
            return answer
        with mock.patch.object(s.Snapshot, 'content', mutate): self.denied('configuration_changed')
        self.assertNotIn(b'manifest.json', self.payload)

    def test_configuration_same_descriptor_reads_and_identity_checks(self):
        original = os.pread
        changed = [False]
        target = self.f.local('/root/ad-dashboard-deploy/docker-compose.yml')
        inode = target.stat().st_ino
        def mutate(fd, size, offset):
            answer = original(fd, size, offset)
            if os.fstat(fd).st_ino == inode and size > 1 and not changed[0]:
                changed[0] = True
                target.write_bytes(b'changed')
            return answer
        with mock.patch.object(os, 'pread', side_effect=mutate): self.denied('configuration_changed')
        self.assertEqual(self.payload, b'')

    def test_config_total_and_path_memory_budgets_are_bounded(self):
        with mock.patch.object(s, 'MAX_CONFIG_TOTAL', 1): self.denied('configuration_limit')
        self.assertEqual(self.payload, b'')
        with mock.patch.object(s, 'MAX_PATH_BYTES', 1): self.denied('manifest_size_limit')
        self.assertEqual(self.payload, b'')


if __name__ == '__main__':
    unittest.main()
