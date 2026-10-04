"""Exact schema11 code replacement gates; no operational files or network are used."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_naver_preview_code_upgrade import load, StoreScopeTest


class SameSchemaContractTest(unittest.TestCase):
    def test_repinned_method_change_cannot_remove_the_existing_monitoring_schema(self):
        code = load('naver_preview_code_upgrade')
        source = StoreScopeTest.SOURCE + b'\ndef reviewed_method():\n    return 1\n'
        target = source.replace(b'return 1', b'return 2').replace(b'naver_auto_morning_chunk',b'unreviewed_chunk')
        with tempfile.TemporaryDirectory() as directory:
            old, new = (Path(directory).resolve() / name for name in ('old', 'new'))
            for root, body in ((old, source), (new, target)):
                for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml',
                             'deploy/naver-engine-backup.override.yml', 'Dockerfile.naver-engine',
                             'Dockerfile.naver-relay', 'backend/requirements.txt', 'naver_runtime/bootstrap.py'):
                    file = root / name
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(b'unchanged')
                file = root / 'naver_engine/store.py'
                file.parent.mkdir(parents=True)
                file.write_bytes(body)
                for role in ('engine', 'relay'):
                    (root / ('preview-' + role + '.override.yml')).write_bytes(
                        ('image: ' + (code.OLD_COMMIT if root == old else code.TARGET_COMMIT)).encode())
            upgrade = Mock(read_file=lambda path, **kwargs: Path(path).read_bytes())
            hashes = {'old': hashlib.sha256(source).hexdigest(), 'target': hashlib.sha256(target).hexdigest()}
            with patch.object(code, 'STORE_SHA256', hashes):
                with self.assertRaisesRegex(ValueError, 'CODE_SCHEMA_CHANGED'):
                    code.compatible_source(old, new, upgrade)


if __name__ == '__main__':
    unittest.main()
