import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('envelope', Path(__file__).parents[1] / 'tools/naver_preview_envelope.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class EnvelopeTest(unittest.TestCase):
    def test_new_key_stays_local_and_receipt_contains_only_certificate(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'envelope'
            result = M.create_envelope(target)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
            for name in ('private.pem', 'recipient.pem'):
                self.assertEqual(stat.S_IMODE((target / name).stat().st_mode), 0o600)
            self.assertIn('BEGIN CERTIFICATE', result['certificate_pem'])
            self.assertNotIn('PRIVATE KEY', str(result))
            self.assertEqual(len(result['certificate_sha256']), 64)

    def test_existing_folder_or_symlink_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'envelope'
            target.mkdir()
            sentinel = target / 'keep'
            sentinel.write_text('unchanged')
            with self.assertRaises(FileExistsError):
                M.create_envelope(target)
            self.assertEqual(sentinel.read_text(), 'unchanged')
            link = Path(folder) / 'link'
            link.symlink_to(target)
            with self.assertRaises(FileExistsError):
                M.create_envelope(link)
