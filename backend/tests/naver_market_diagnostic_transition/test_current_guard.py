import copy
import json
import unittest
from unittest.mock import patch
import current_guard as G
import transition as T
import systemd_boundary as S


class CurrentGuardTests(unittest.TestCase):
    """Closed Docker/systemd/receipt seams; no operating commands are run."""
    def setUp(self):
        self.prepared = dict(ok=True, stage='prepared', source_commit=T.OPERATING_SOURCE,
            package=dict(baseline=G.BASELINE, source_commit=T.OPERATING_SOURCE,
                source_tar_gz_sha256=G.ARCHIVE, ciphertext_sha256=G.CIPHER, run_id=G.RUN),
            images={'engine': 'sha256:' + 'a' * 64, 'relay': 'sha256:' + 'b' * 64})
        self.started = dict(ok=True, stage='internal_ready', source_commit=T.OPERATING_SOURCE,
            previous_commit='513e52eaee4d1bb722461961639cd588df9080cd',
            operation_id=T.OPERATING_OPERATION, database_policy='preserve-in-place', execution_enabled=False)
        self.previous = {k: 'c' * 64 for k in T.PROOF_KEYS}
        self.previous['operating_receipt_sha256'] = T.sha(T.canonical(self.started))
        self.rows = {name: dict(id=c * 64, image=self.prepared['images'][name],
            running=True, started='2026-10-16T05:03:44.111111111Z', restarts=0,
            user='10001:10001', readonly=True, project='naver-' + name,
            service='naver-' + name, source=T.OPERATING_SOURCE)
            for name, c in [('engine', 'd'), ('relay', 'e')]}
        self.reader = dict(LoadState='loaded', UnitFileState='static',
            FragmentPath=T.UNIT_ROOT + '/' + T.OLD_READER, DropInPaths='', Job='0',
            Result='exit-code', ExecMainStatus='1', ActiveState='failed', SubState='failed',
            InvocationID='f' * 32)
        self.messages = [dict(_SYSTEMD_UNIT=T.OLD_READER, _SYSTEMD_INVOCATION_ID='f' * 32,
            MESSAGE='{"status":"failed","code":"SOURCE_LIMIT"}')]
        self.calls = []
        self.hook = None
        self.multiple = False
        self.code = 0
        def snapshot(path):
            value = self.started if path.name.startswith('preview-start-') else self.prepared
            return T.canonical(value), ('isolated-metadata',)
        for p in (patch.object(G.B, 'trusted_dir'), patch.object(G.B, 'snapshot', side_effect=snapshot)):
            p.start(); self.addCleanup(p.stop)
        self.guard = G.CurrentGuard(self.previous, command=self.command)

    def command(self, argv, *, limit, timeout):
        self.calls.append(argv)
        self.assertEqual(timeout, 8)
        self.assertIn(limit, (4096, 32768))
        if argv[0] == '/usr/bin/docker':
            if argv[1] == 'ps':
                name = 'engine' if 'label=com.docker.compose.service=naver-engine' in argv else 'relay'
                raw = (self.rows[name]['id'] + '\n' + ('1' * 64 + '\n' if self.multiple else '')).encode()
            elif argv[1:3] == ['image', 'inspect']:
                name = next(k for k, v in self.prepared['images'].items() if v == argv[-1])
                raw = T.canonical(dict(id=argv[-1], user='10001:10001', source=self.rows[name]['source']))
            else:
                name = next(k for k, v in self.rows.items() if v['id'] == argv[-1])
                raw = T.canonical(self.rows[name])
            self.assertNotIn('exec', argv)
            self.assertNotIn('compose', argv)
            self.assertFalse(any('.Env' in a or '.Mounts' in a for a in argv))
        elif argv[0] == '/usr/bin/systemctl':
            self.assertEqual(argv[1:3], ['show', T.OLD_READER])
            raw = ''.join(k + '=' + self.reader[k] + '\n' for k in S.PROPERTIES).encode()
        else:
            self.assertEqual(argv[0], '/usr/bin/journalctl')
            self.assertIn('_SYSTEMD_INVOCATION_ID=' + 'f' * 32, argv)
            raw = b'\n'.join(T.canonical(v) for v in self.messages)
        if self.hook: self.hook(argv)
        return self.code, raw

    def test_capture_and_reload_require_current_containers_not_receipt_alone(self):
        proof = self.guard.capture()
        again = G.CurrentGuard(self.previous, proof=proof, command=self.command)
        self.assertTrue(again(require_failure=True)['source_limit_invocation_verified'])
        self.assertEqual(set(proof), G.PROOF_KEYS)
        self.rows['engine']['running'] = False
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_CONTAINER'): again(require_failure=False)

    def test_foreign_source_restart_or_privileged_container_rejected(self):
        for field, value in [('source', '9' * 40), ('restarts', 1), ('user', '0'), ('readonly', False)]:
            with self.subTest(field=field):
                original = self.rows['engine'][field];self.rows['engine'][field] = value
                with self.assertRaises(T.Invalid): self.guard.capture()
                self.rows['engine'][field] = original

    def test_two_matching_containers_are_not_arbitrarily_selected(self):
        self.multiple = True
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_CONTAINER'): self.guard.capture()
        self.assertFalse(any(v[0] == '/usr/bin/journalctl' for v in self.calls))

    def test_receipt_archive_and_operation_must_be_exact(self):
        self.prepared['package']['source_tar_gz_sha256'] = '0' * 64
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_PREPARED'): self.guard.capture()
        self.prepared['package']['source_tar_gz_sha256'] = G.ARCHIVE
        self.started['operation_id'] = '0' * 32
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_STARTED'): self.guard.capture()

    def test_stable_proof_detects_recreated_same_source_container(self):
        proof = self.guard.capture()
        self.rows['relay']['id'] = '8' * 64
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_CHANGED'):
            G.CurrentGuard(self.previous, proof=proof, command=self.command)(require_failure=False)

    def test_container_drift_during_failure_read_is_rejected(self):
        self.hook = lambda a: self.rows['engine'].update(started='2026-10-18T00:00:00Z') if a[0] == '/usr/bin/journalctl' else None
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_CHANGED'): self.guard.capture()
        self.assertIsNone(self.guard.proof)

    def test_invocation_change_during_journal_read_is_rejected(self):
        self.hook = lambda a: self.reader.update(InvocationID='1' * 32) if a[0] == '/usr/bin/journalctl' else None
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_FAILURE_CHANGED'): self.guard.capture()

    def test_fresh_capture_requires_loaded_failed_original_not_masked_history(self):
        self.reader.update(LoadState='masked', UnitFileState='masked-runtime', FragmentPath=S.MASK_ROOT + '/' + T.OLD_READER)
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_FAILURE_UNIT'): self.guard.capture()

    def test_owned_mask_phase_uses_original_bound_invocation_after_cache_clear(self):
        self.guard.capture()
        self.reader.update(LoadState='masked', UnitFileState='masked-runtime',
            FragmentPath=S.MASK_ROOT + '/' + T.OLD_READER, InvocationID='', Result='success', ExecMainStatus='0',
            ActiveState='inactive', SubState='dead')
        self.assertTrue(self.guard(require_failure=True)['source_limit_invocation_verified'])
        self.reader['Job'] = '77'
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_FAILURE_UNIT'): self.guard(require_failure=True)

    def test_new_diagnostic_or_mixed_failure_cannot_be_original_prerequisite(self):
        for message in ['{"status":"failed","code":"SOURCE_LIMIT","limit_issue":"unknown"}',
                        '{"status":"failed","code":"SOURCE_READ"}']:
            with self.subTest(message=message):
                self.messages.append(dict(self.messages[0], MESSAGE=message))
                with self.assertRaises(T.Invalid): self.guard.capture()
                self.messages.pop()

    def test_wrong_journal_unit_or_invocation_rejects(self):
        for field, value in [('_SYSTEMD_UNIT', 'other.service'), ('_SYSTEMD_INVOCATION_ID', '8' * 32)]:
            original = self.messages[0][field];self.messages[0][field] = value
            with self.assertRaisesRegex(T.Invalid, 'JOURNAL_INVOCATION'): self.guard.capture()
            self.messages[0][field] = original

    def test_restore_does_not_require_old_failure_after_natural_timer_catchup(self):
        self.guard.capture();self.calls.clear()
        self.reader.update(InvocationID='2' * 32, Result='success', ExecMainStatus='0')
        self.assertFalse(self.guard(require_failure=False)['source_limit_invocation_verified'])
        self.assertTrue(all(v[0] == '/usr/bin/docker' for v in self.calls))

    def test_proof_type_alias_and_container_bool_integer_alias_reject(self):
        proof = self.guard.capture();proof['version'] = True
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_PROOF'):
            G.CurrentGuard(self.previous, proof=proof, command=self.command)
        self.rows['engine']['running'] = 1
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_CONTAINER'): self.guard(require_failure=False)

    def test_nonzero_command_and_oversized_capture_fail_without_publication(self):
        self.code = 1
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_COMMAND'): self.guard.capture()
        with patch.object(self.guard, 'command', return_value=(0, b'x' * 4097)):
            with self.assertRaisesRegex(T.Invalid, 'CURRENT_COMMAND'): self.guard.capture()


if __name__ == '__main__': unittest.main()
