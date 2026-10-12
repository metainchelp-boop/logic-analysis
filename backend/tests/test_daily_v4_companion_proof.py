"""Closed persisted P9 proof cases; synthetic bytes, no actual host/DB/env reads."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import types
import unittest
from unittest.mock import Mock, patch

from daily_v4_support import controller, pin_controller, package, pin_transport, transport


def companion_bytes():
    value = {'services': {'naver-engine': {
        'environment': {'NAVER_ENGINE_PRODUCT_EXPORT_FILE': '/var/lib/naver-product-source/bundle.json',
                        'NAVER_ENGINE_MARKET_EXPORT_FILE': '/var/lib/naver-market-source/bundle.json'},
        'volumes': [{'type': 'bind', 'source': '/var/lib/metainc/naver-'+kind+'-source',
            'target': '/var/lib/naver-'+kind+'-source', 'read_only': True,
            'bind': {'create_host_path': False}} for kind in ('product', 'market')]}}}
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()+b'\n'


class CompanionProofTests(unittest.TestCase):
    def setUp(self):
        self.c = pin_controller(controller())
        self.release = Mock()
        self.release.ROOT = Path('/srv/metainc/ad-deploy-staging')
        self.release.unique = lambda pairs: dict(pairs)
        self.original = self.release.ROOT/'receipts'/('preview-'+self.c.EXPORT_SOURCE+'.json')
        self.release.prepared_paths.return_value = (Path('/unused'), self.original)
        self.path = self.release.ROOT/'releases'/('naver-'+self.c.SOURCE)
        self.original_value = {'ok': True, 'stage': 'prepared', 'source_commit': self.c.EXPORT_SOURCE,
            'package': {'baseline': self.c.BASELINE, 'source_commit': self.c.EXPORT_SOURCE,
                'source_tar_gz_sha256': self.c.EXPORT_ARCHIVE, 'run_id': self.c.EXPORT_PREPARE_RUN,
                'ciphertext_sha256': 'a'*64}}
        package_digest = self.c.digest(self.c.canonical(dict(self.original_value['package'], operation='code-prepare')))
        self.binding_path = self.release.ROOT/'receipts'/('completion-exports-'+self.c.EXPORT_SOURCE+'.json')
        self.exports = {'version': 4, 'operation_id': package_digest[:32],
            'plan': deepcopy(self.c.EXPORT_PINS['plan']),
            'plan_sha256': self.c.digest(self.c.canonical(self.c.EXPORT_PINS['plan'])),
            'source_identity': {'synthetic': True}, 'runtime_identity': {'synthetic': True},
            'manifest': {name: 'a'*64 for name in self.c.EXPORT_NAMES},
            'companion_sha256': self.c.EXPORT_PINS['companion_sha256'], 'interpreter': {'synthetic': True}}
        self.exports['manifest'][self.c.EXPORT_COMPANION] = self.c.EXPORT_PINS['companion_sha256']
        self.binding = {'source_commit': self.c.EXPORT_SOURCE, 'package_sha256': package_digest,
            'pins_sha256': self.c.digest(self.c.canonical(self.c.EXPORT_PINS)), 'exports': self.exports}
        self.folder = self.c.EXPORT_STAGE/package_digest[:32]
        self.prepared_path = self.folder/'prepared.json'
        self.companion_path = self.folder/self.c.EXPORT_COMPANION

    def bodies(self):
        return {self.original: self.c.canonical(self.original_value),
                self.binding_path: self.c.canonical(self.binding),
                self.prepared_path: self.c.canonical(self.exports),
                self.companion_path: companion_bytes()}

    def read(self, bodies=None):
        bodies = self.bodies() if bodies is None else bodies
        reader = Mock(side_effect=lambda item, release, private: bodies[item])
        with patch.object(self.c, 'read_export_artifact', reader):
            result = self.c.verified_companion(self.path, self.release)
        return result, reader

    def test_real_p9_companion_render_hash_and_authenticated_proxy_are_exact(self):
        self.assertEqual(hashlib.sha256(companion_bytes()).hexdigest(), self.c.EXPORT_PINS['companion_sha256'])
        (proxy, proof), reader = self.read()
        self.assertEqual(proof, self.bodies())
        self.assertEqual(reader.call_count, 4)
        self.release.compose.return_value = ['docker', 'compose', 'fixed']
        self.assertEqual(proxy.compose(self.path, 'engine'), ['docker', 'compose', 'fixed', '-f', str(self.companion_path)])
        self.assertEqual(proxy.compose(self.path, 'relay'), ['docker', 'compose', 'fixed'])
        self.release.command.assert_not_called()

    def test_pending_pin_rejects_before_file_directory_or_helper_access(self):
        c = controller()
        with patch.object(c, 'read_export_artifact') as read, self.assertRaisesRegex(ValueError, '^D3_PINS_PENDING$'):
            c.verified_companion(self.path, self.release)
        read.assert_not_called(); self.release.prepared_paths.assert_not_called()

    def test_original_source_package_has_no_alternate_source_or_shape(self):
        for key, value in [('baseline', 'b'*64), ('source_commit', self.c.SOURCE),
                           ('source_tar_gz_sha256', 'b'*64), ('run_id', True), ('ciphertext_sha256', 'bad')]:
            original = deepcopy(self.original_value); original['package'][key] = value
            bodies = self.bodies(); bodies[self.original] = self.c.canonical(original)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, '^D3_COMPANION$'): self.read(bodies)
        bodies = self.bodies(); wrong = deepcopy(self.original_value); wrong['package']['extra'] = 'x'
        bodies[self.original] = self.c.canonical(wrong)
        with self.assertRaises(ValueError): self.read(bodies)

    def test_binding_source_package_and_pins_cannot_be_substituted(self):
        for key, value in [('source_commit', self.c.SOURCE), ('package_sha256', 'b'*64),
                           ('pins_sha256', 'b'*64), ('extra', 'x')]:
            binding = deepcopy(self.binding); binding[key] = value
            bodies = self.bodies(); bodies[self.binding_path] = self.c.canonical(binding)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, '^D3_COMPANION$'): self.read(bodies)

    def test_export_receipt_shape_and_exact_companion_relationship_are_required(self):
        mutations = [('version', True), ('operation_id', 'b'*32), ('plan', {}),
            ('plan_sha256', 'b'*64), ('companion_sha256', 'b'*64), ('manifest', {}), ('extra', 'x')]
        for key, value in mutations:
            binding = deepcopy(self.binding); binding['exports'][key] = value
            bodies = self.bodies(); bodies[self.binding_path] = self.c.canonical(binding)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, '^D3_COMPANION$'): self.read(bodies)
        binding = deepcopy(self.binding); binding['exports']['manifest'][self.c.EXPORT_COMPANION] = 'b'*64
        bodies = self.bodies(); bodies[self.binding_path] = self.c.canonical(binding)
        with self.assertRaises(ValueError): self.read(bodies)

    def test_staged_prepared_must_equal_whole_bound_receipt(self):
        for body in (b'{}', self.c.canonical(self.exports)+b'\n'):
            bodies = self.bodies(); bodies[self.prepared_path] = body
            with self.subTest(size=len(body)), self.assertRaisesRegex(ValueError, '^D3_COMPANION$'): self.read(bodies)

    def test_companion_bytes_are_fixed_not_accepted_from_receipt_digest(self):
        bodies = self.bodies(); bodies[self.companion_path] += b'\n'
        with self.assertRaisesRegex(ValueError, '^D3_COMPANION$'): self.read(bodies)

    def test_proxy_never_extends_other_source_type_or_path(self):
        (proxy, _), _ = self.read()
        for path, kind in ((self.path, 'other'), (self.path.parent/('naver-'+self.c.PREVIOUS), 'engine'),
                           (Path('/elsewhere')/self.path.name, 'engine')):
            with self.subTest(path=str(path), kind=kind), self.assertRaisesRegex(ValueError, '^D3_COMPANION$'):
                proxy.compose(path, kind)
        self.release.compose.assert_not_called()

    def test_failure_does_not_disclose_exception_body_or_allow_partial_proof(self):
        with patch.object(self.c, 'read_export_artifact', side_effect=RuntimeError('private-body-do-not-copy')):
            with self.assertRaisesRegex(ValueError, '^D3_COMPANION$') as found:
                self.c.verified_companion(self.path, self.release)
        self.assertNotIn('private-body', str(found.exception))
        self.assertIsNone(found.exception.__cause__)

    def test_fixed_four_paths_exclude_env_key_db_log_and_other_export_content(self):
        (_, proof), reader = self.read()
        self.assertEqual(set(proof), {self.original, self.binding_path, self.prepared_path, self.companion_path})
        self.assertEqual([call.kwargs['private'] for call in reader.call_args_list], [True, True, True, False])
        self.release.command.assert_not_called()

    def test_new_closed_codes_roundtrip_without_raw_details(self):
        t = pin_transport(transport()); r = Mock()
        from daily_v4_support import failed
        for code in ('D3_COMPANION', 'D3_UNIT_BYTES', 'D3_UNIT_ACTIVE', 'D3_UNIT_ENABLED'):
            self.assertEqual(t.project_result(failed(code), r)['failure']['primary_code'], code)
        with self.assertRaises(ValueError): t.project_result(failed('D3_UNIT_BYTES:private-body'), r)


class ArtifactMetadataTests(unittest.TestCase):
    def setUp(self):
        self.c = pin_controller(controller()); self.release = Mock()
        self.info = dict(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_gid=0, st_nlink=1,
            st_size=4, st_dev=1, st_ino=2, st_mtime_ns=3)
        self.path = Mock(); self.path.resolve.return_value = self.path
        self.path.is_symlink.return_value = False; self.path.read_bytes.return_value = b'body'
        self.path.lstat.side_effect = lambda: types.SimpleNamespace(**self.info)

    def test_public_metadata_positive_and_private_mode_are_distinct(self):
        self.assertEqual(self.c.read_export_artifact(self.path, self.release, private=False), b'body')
        self.info['st_mode'] = stat.S_IFREG | 0o600
        self.assertEqual(self.c.read_export_artifact(self.path, self.release, private=True), b'body')
        self.release.trusted_private_file.assert_called_once_with(self.path)

    def test_owner_group_mode_type_hardlink_size_and_symlink_are_rejected(self):
        for key, value in [('st_uid', 1), ('st_gid', 1), ('st_mode', stat.S_IFREG|0o666),
                           ('st_mode', stat.S_IFDIR|0o644), ('st_nlink', 2), ('st_size', 32769), ('st_size', 0)]:
            old = self.info[key]; self.info[key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, '^D3_COMPANION$'):
                self.c.read_export_artifact(self.path, self.release, private=False)
            self.info[key] = old
        self.path.read_bytes.assert_not_called(); self.path.is_symlink.return_value = True
        with self.assertRaises(ValueError): self.c.read_export_artifact(self.path, self.release, private=False)

    def test_read_length_or_inode_change_is_rejected(self):
        self.path.read_bytes.return_value = b'changed-length'
        with self.assertRaises(ValueError): self.c.read_export_artifact(self.path, self.release, private=False)
        self.path.read_bytes.return_value = b'body'
        self.path.lstat.side_effect = [types.SimpleNamespace(**self.info), types.SimpleNamespace(**dict(self.info, st_ino=5))]
        with self.assertRaises(ValueError): self.c.read_export_artifact(self.path, self.release, private=False)


if __name__ == '__main__': unittest.main()
