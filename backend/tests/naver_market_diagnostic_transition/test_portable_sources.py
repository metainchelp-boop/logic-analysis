"""New source-resolution cases only; never import production or existing tests."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_sources as S


class PortableSourcesTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve() / 'relocated'
        root.mkdir()
        for record in S.FILES.values():
            target = root / record['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(S._ROOT / record['path'], target)
        helper = root / 'backend/tests/naver_market_diagnostic_transition/test_sources.py'
        helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(S.__file__), helper)
        return root, helper

    def test_pinned_layout_preserves_public_roles_and_unchanged_producer_sibling(self):
        self.assertEqual(len(S.validate_layout()), 19)
        modules, sources, host = S.delivery_materials()
        self.assertEqual(set(modules), set(S.MODULE_NAMES))
        self.assertEqual(len(modules), 9)
        self.assertEqual(set(sources), set(S.PUBLIC_ROLES))
        self.assertEqual(len(sources), 5)
        self.assertEqual(S.baseline_sources(), {k: sources[k] for k in S.BASELINE_ROLES})
        self.assertEqual(S.transition_sources()['market'], sources['diagnostic_exporter'])
        self.assertNotEqual(sources['market_exporter'], sources['diagnostic_exporter'])
        producer = S.producer_source_path()
        self.assertEqual(producer.with_name('naver_product_export.py').read_bytes(), sources['product_exporter'])
        self.assertEqual(hashlib.sha256(host).hexdigest(), S.FILES['delivery']['sha256'])
        self.assertEqual(hashlib.sha256(S.renderer_source()).hexdigest(), S.FILES['bootstrap']['sha256'])
        self.assertEqual(S.consumer_source_path().read_bytes(), S._read_at(S._ROOT, 'diagnostic_failure_consumer'))

    def test_relocated_layout_is_cwd_and_env_independent_without_runtime_imports(self):
        root, helper = self.fixture()
        script = '''import importlib.util,json,sys
spec=importlib.util.spec_from_file_location("portable_test_sources",sys.argv[1])
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
before=set(sys.modules);m,p,h=s.delivery_materials();s.validate_layout()
assert not (set(s.MODULE_NAMES)&set(sys.modules))
assert not {"delivery","bootstrap","strict_receiver"}&set(sys.modules)
assert set(sys.modules)==before
print(json.dumps({"modules":len(m),"public":len(p),"pins":len(s.FILES)}))
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(helper)],
            cwd=root.parent, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'modules': 9, 'public': 5, 'pins': 19})
        self.assertEqual(result.stderr, '')

    def test_missing_exact_file_refuses_even_when_an_alternate_copy_exists(self):
        root, _ = self.fixture()
        file = root / S.FILES['market_exporter']['path']
        file.rename(file.with_name('old_market_export.py'))
        with self.assertRaisesRegex(ValueError, '^PORTABLE_SOURCE_UNAVAILABLE$'):
            S._read_at(root, 'market_exporter')

    def test_same_length_tamper_and_baseline_candidate_swap_refuse(self):
        root, _ = self.fixture()
        path = root / S.FILES['delivery']['path']
        data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        with self.assertRaisesRegex(ValueError, '^PORTABLE_SOURCE_CHANGED$'):
            S._read_at(root, 'delivery')
        old = root / S.FILES['market_exporter']['path']
        new = root / S.FILES['diagnostic_exporter']['path']
        old_data, new_data = old.read_bytes(), new.read_bytes()
        old.write_bytes(new_data); new.write_bytes(old_data)
        for role in ('market_exporter', 'diagnostic_exporter'):
            with self.subTest(role=role), self.assertRaises(ValueError):
                S._read_at(root, role)

    def test_source_or_ancestor_symlink_refuses_without_following(self):
        root, _ = self.fixture()
        path = root / S.FILES['market_exporter']['path']
        saved = path.with_name('saved_market.py')
        path.rename(saved); path.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, '^PORTABLE_SOURCE_FILE$'):
            S._read_at(root, 'market_exporter')
        path.unlink(); saved.rename(path)
        folder = root / 'backend/tools/naver_market_diagnostic_transition'
        moved = folder.with_name('moved_diagnostic')
        folder.rename(moved); folder.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '^PORTABLE_SOURCE_DIRECTORY$'):
            S._read_at(root, 'delivery')

    def test_registry_unknown_roles_path_escapes_and_alias_pins_refuse(self):
        for name in ('unknown', '../delivery', True, 1, None):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, '^PORTABLE_SOURCE_NAME$'):
                S._read_at(S._ROOT, name)
        changes = [{'path': p} for p in ('/tmp/private.py', '../private.py',
            'backend/../private.py', 'backend//private.py', 'backend/./private.py',
            'backend\\private.py', 'elsewhere/private.py')]
        changes += [{'bytes': True}, {'bytes': 0}, {'bytes': 131073}, {'sha256': 'A' * 64},
                    {'sha256': True}, {'extra': 'unexpected'}]
        for delta in changes:
            records = copy.deepcopy(S.FILES)
            records['delivery'].update(delta)
            with self.subTest(delta=delta), patch.object(S, 'FILES', records), self.assertRaises(ValueError):
                S._read_at(S._ROOT, 'delivery')


if __name__ == '__main__':
    unittest.main()
