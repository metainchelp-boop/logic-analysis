"""Actual pinned P9/lifecycle generators; only synthetic files and state values."""
import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from daily_v4_support import controller, load, pin_controller


def p9_proxy(release, folder, source):
    raw = (Path(__file__).parent/'fixtures/p9_export_proxy.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != 'a25dc18da6aa5caf9b881efe307d67efb4201edaba6800d5f6fb003bb7960c91':
        raise AssertionError('PINNED_P9_PROXY_CHANGED')
    scope = {'Path': Path, 'require_pins': lambda: None}
    exec(compile(raw, '<actual-pinned-p9-export-proxy>', 'exec'), scope)
    helper = types.SimpleNamespace(COMPANION='naver-saved-exports.override.yml',
        _prepared=lambda receipt: (None, folder, {}))
    binding = types.SimpleNamespace(h=helper, receipt={})
    return scope['ExportProxy'](release, binding, types.SimpleNamespace(
        OLD_COMMIT='32878e8ecec616772b619c23e796931d44f0bee1', TARGET_COMMIT=source))


class P9UnitContract(unittest.TestCase):
    def setUp(self):
        self.c = pin_controller(controller())
        self.life = load('naver_preview_lifecycle.py')
        self.real_release = load('naver_preview_release.py')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root/('naver-'+self.c.SOURCE)
        self.path.mkdir()
        (self.path/'deploy').mkdir()
        self.life.UNIT_DIR = self.root/'systemd'; self.life.UNIT_DIR.mkdir()
        self.life.TMPFILES = self.root/'tmpfiles.conf'
        self.release = types.SimpleNamespace(compose=self.real_release.compose,
            sha=lambda raw: hashlib.sha256(raw).hexdigest())
        self.prepared = {'files': {}}
        for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml',
                     'preview-engine.override.yml', 'preview-relay.override.yml',
                     'deploy/naver-engine-backup.override.yml'):
            item = self.path/name; item.write_bytes(b'fixed public compose')
            self.prepared['files'][str(item)] = self.release.sha(item.read_bytes())
        self.companion = self.root/'saved-exports'/('a'*32)
        self.companion.mkdir(parents=True)
        self.file = self.companion/'naver-saved-exports.override.yml'
        self.file.write_bytes(b'fixed authenticated public companion')
        self.proxy = p9_proxy(self.release, self.companion, self.c.SOURCE)
        self.expected = self.life.unit_files(self.path, 33, self.proxy)
        for item, raw in self.expected.items(): item.write_bytes(raw)

    def checked(self, *, states=None):
        def state(release, unit, field):
            return (states or {}).get((unit, field), 'active' if field == 'ActiveState' else 'enabled')
        with patch.object(self.c.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_gid=33)), \
             patch.object(self.c, 'verified_companion', return_value=(self.proxy, {self.file: self.file.read_bytes()}), create=True), \
             patch.object(self.life, '_state', side_effect=state):
            return self.c.safe_runtime_files(self.path, self.prepared, self.release, self.life)

    def test_actual_p9_generated_units_pass_same_byte_guard(self):
        result=self.checked()
        self.assertTrue(result)
        self.assertEqual(result[self.file],self.file.read_bytes())
        self.assertTrue(set(self.expected).issubset(result))

    def test_actual_proxy_changes_engine_only_start_and_stop(self):
        plain = self.life.unit_files(self.path, 33, self.release)
        self.assertEqual([str(p.name) for p in plain if plain[p] != self.expected[p]],
            ['metainc-naver-engine.service'])
        before = plain[self.life.UNIT_DIR/self.life.UNITS[0]].decode().splitlines()
        after = self.expected[self.life.UNIT_DIR/self.life.UNITS[0]].decode().splitlines()
        self.assertEqual([a.split('=', 1)[0] for a, b in zip(after, before) if a != b],
            ['ExecStart', 'ExecStop'])

    def test_pristine_engine_unit_is_rejected_instead_of_allowing_both(self):
        for item, raw in self.life.unit_files(self.path, 33, self.release).items(): item.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, '^D3_UNIT_BYTES$'): self.checked()

    def test_any_engine_relay_or_tmpfiles_byte_change_is_rejected(self):
        for item, raw in self.expected.items():
            with self.subTest(unit=item.name):
                item.write_bytes(raw+b'\n')
                with self.assertRaisesRegex(ValueError, '^D3_UNIT_BYTES$'): self.checked()
                item.write_bytes(raw)

    def test_active_predicate_remains_required_and_distinct(self):
        for unit in ('docker.service', self.life.TUNNEL, *self.life.UNITS):
            with self.subTest(unit=unit), self.assertRaisesRegex(ValueError, '^D3_UNIT_ACTIVE$'):
                self.checked(states={(unit, 'ActiveState'): 'inactive'})

    def test_enabled_predicate_remains_required_and_distinct(self):
        for unit in self.life.UNITS:
            with self.subTest(unit=unit), self.assertRaisesRegex(ValueError, '^D3_UNIT_ENABLED$'):
                self.checked(states={(unit, 'UnitFileState'): 'disabled'})


if __name__ == '__main__': unittest.main()
