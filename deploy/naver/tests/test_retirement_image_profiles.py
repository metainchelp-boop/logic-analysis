"""Fixed identity registry and exact-byte module loading, using public synthetic files."""
import dataclasses
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'retirement_images_source.py'
SPEC = importlib.util.spec_from_file_location('profiles_source_test', SOURCE)
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.profiles = source.load_profiles()

    def test_four_exact_distinct_identities_sessions_and_sizes(self):
        expected = (
            ('autobid-web', '075e4cd227777d7ea5347c27c0842067bc963cead5c6b6cc60b71897105140ec', 84303740),
            ('autobid-engine', '3b86b60dd010faba75e910bdac4d8acc1678a3eabf1f54463fe5a64bf1cc0f6d', 84303743),
            ('autobid-watchdog', '935ce49a4c3981eda46e1ae39c76daf831fd90107410d1823ea133f7b86cffad', 84303745),
            ('content-studio', 'b52374a33084ea20386af2380478a38cff92eebdbeff97c616ad7d80a112a0dc', 1381032080),
        )
        self.assertEqual(tuple(self.profiles.PROFILES), self.profiles.ORDER)
        self.assertEqual(len(self.profiles.PROFILES), 4)
        for name, digest, size in expected:
            profile = self.profiles.lookup(name)
            self.assertEqual((profile.image_id, profile.expected_size_bytes), ('sha256:' + digest, size))
            self.assertEqual(profile.session, name + '-image-20261102-v1')
            self.assertEqual(profile.command, 'receive-' + profile.session)
        self.assertEqual(len({p.session for p in self.profiles.PROFILES.values()}), 4)

    def test_only_content_has_a_larger_separate_inflation_budget(self):
        gib=1024**3
        content=self.profiles.lookup('content-studio')
        self.assertEqual(content.max_expanded_bytes,8*gib)
        self.assertEqual((content.max_archive_bytes,content.max_cipher_bytes),(2*gib,2*gib))
        self.assertEqual((content.max_image_bytes,content.source_min_free_bytes,
                          content.receiver_min_free_bytes),(1536*1024**2,3*gib,4*gib))
        self.assertEqual((content.source_timeout_seconds,content.receiver_timeout_seconds,
                          content.verify_timeout_seconds,content.workflow_timeout_seconds),(1800,1800,1800,1830))
        for name in self.profiles.ORDER[:3]:
            profile=self.profiles.lookup(name)
            self.assertEqual((profile.max_expanded_bytes,profile.max_archive_bytes,profile.max_cipher_bytes),
                             (512*1024**2,)*3)

    def test_registry_and_profile_cannot_be_mutated(self):
        with self.assertRaises(TypeError):
            self.profiles.PROFILES['ad'] = self.profiles.lookup('autobid-web')
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.profiles.lookup('autobid-web').image_id = 'sha256:' + 'f' * 64

    def test_no_ad_legacy_session_paths_tags_or_external_configuration(self):
        for value in ('ad-image-20261102-v1', 'ad', '../autobid-web', '/root', '',
                      'content-studio:latest', 'autobid-web\n', None, 1, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.profiles.lookup(value)

    def test_large_profile_requires_reviewed_version_and_limits_cover_known_metadata(self):
        for profile in self.profiles.PROFILES.values():
            self.assertLess(profile.expected_size_bytes, profile.max_image_bytes)
            self.assertGreater(profile.source_min_free_bytes, profile.max_image_bytes)
            self.assertGreater(profile.workflow_timeout_seconds, profile.source_timeout_seconds)
        self.assertTrue(self.profiles.lookup('content-studio').large_export_enabled)
        self.assertEqual(source.CONTENT_EXPORT_VERSION, (29, 4, 0))
        self.assertEqual(source.CONTENT_TAR_STAGING_BYTES + source.CONTENT_METADATA_RESERVE_BYTES,
                         1024 * 1024 * 1024)


class LoaderTest(unittest.TestCase):
    module_file = 'retirement_images_source.py'

    def setUp(self):
        spec = importlib.util.spec_from_file_location('fixed_loader_test_' + self.module_file,
                                                     SOURCE.parent / self.module_file)
        self.loader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.loader)
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(os.path.realpath(self.temp.name))
        self.file = self.folder / self.loader.PROFILE_FILE
        self.data = (SOURCE.parent / self.loader.PROFILE_FILE).read_bytes()
        self.file.write_bytes(self.data)
        self.file.chmod(0o600)
        self.patched = mock.patch.object(self.loader, '__file__', str(self.folder / 'helper.py'))
        self.patched.start()

    def tearDown(self):
        self.patched.stop()
        self.temp.cleanup()

    def test_hash_bound_same_bytes_load_with_isolated_path(self):
        self.assertEqual(hashlib.sha256(self.data).hexdigest(), self.loader.PROFILE_SHA256)
        self.assertEqual(self.loader.load_profiles().ORDER[0], 'autobid-web')

    def test_modified_module_is_refused_before_compile_or_execution(self):
        self.file.write_bytes(b'raise RuntimeError("UNTRUSTED_CANARY")\n')
        with mock.patch('builtins.compile', side_effect=AssertionError('must not compile')):
            with self.assertRaises(ValueError):
                self.loader.load_profiles()

    def test_symlink_and_hardlink_are_refused(self):
        other = self.folder / 'other'
        self.file.rename(other)
        self.file.symlink_to(other)
        with self.assertRaises(OSError):
            self.loader.load_profiles()
        self.file.unlink()
        os.link(other, self.file)
        with self.assertRaises(ValueError):
            self.loader.load_profiles()

    def test_fifo_empty_oversized_and_writable_module_are_refused(self):
        self.file.unlink()
        os.mkfifo(self.file, 0o600)
        with self.assertRaises(ValueError):
            self.loader.load_profiles()
        self.file.unlink()
        for data, mode in ((b'', 0o600), (b'x' * 32769, 0o600), (self.data, 0o660)):
            self.file.write_bytes(data)
            self.file.chmod(mode)
            with self.assertRaises(ValueError):
                self.loader.load_profiles()

    def test_filename_replacement_after_read_is_refused(self):
        real_read = os.read
        moved = False

        def replaced(fd, count):
            nonlocal moved
            data = real_read(fd, count)
            if not moved and data:
                moved = True
                self.file.rename(self.folder / 'original')
                self.file.write_bytes(self.data)
                self.file.chmod(0o600)
            return data

        with mock.patch.object(self.loader.os, 'read', side_effect=replaced):
            with self.assertRaises(ValueError):
                self.loader.load_profiles()


class ReceiverLoaderTest(LoaderTest):
    module_file = 'retirement_images_receiver.py'


class ValidatorLoaderTest(LoaderTest):
    module_file = 'retirement_images_verify.py'


if __name__ == '__main__':
    unittest.main()
