"""Exact schema11 code replacement gates; no operational files or network are used."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_naver_preview_code_upgrade import load


class SameSchemaContractTest(unittest.TestCase):
    def test_reviewed_method_change_accepts_identical_schema11_sql_and_initializer(self):
        code = load('naver_preview_code_upgrade')
        contract = json.loads((Path(__file__).with_name('fixtures') / 'naver_schema10_11_contract.json').read_text())['new_observed_unsealed']
        source = ('SCHEMA_VERSION=11\n_SCHEMA=' + repr(tuple(contract['sql'])) + '\n' +
                  '_REVISION_COLUMNS=' + repr(contract['revision_columns']) + '\n' +
                  contract['migrate'] + '\ndef reviewed_method():\n    return 1\n').encode()
        target = source.replace(b'return 1', b'return 2')
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
                code.compatible_source(old, new, upgrade)


if __name__ == '__main__':
    unittest.main()
