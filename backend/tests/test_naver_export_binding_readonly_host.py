import ast
import base64
import contextlib
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import textwrap
import types
import unittest
from unittest import mock

import naver_export_binding_readonly_host as H


SOURCES = {key: ('public synthetic ' + key).encode() for key in H.SOURCE_PINS}
PINS = {key: hashlib.sha256(body).hexdigest() for key, body in SOURCES.items()}
CORE = b'''import json,os,sys
calls=0
def diagnose(sources):
    global calls
    calls+=1
    print('DO_NOT_EMIT_CORE_STDOUT')
    print('DO_NOT_EMIT_CORE_STDERR',file=sys.stderr)
    assert set(os.environ)=={'PATH','LANG'}
    return {'ok':True,'calls':calls,'source_count':len(sources)}
def closed_json(value):
    return json.dumps(value)
'''


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def wire_raw(raw, preset=6):
    return base64.b85encode(lzma.compress(raw, format=lzma.FORMAT_XZ, preset=preset)).decode()


def workflow_path():
    local = Path(__file__).resolve().with_name('naver-export-binding-readonly.yml')
    if local.exists():
        return local
    return Path(__file__).resolve().parents[2]/'.github/workflows/naver-export-binding-readonly.yml'


def bootstrap():
    workflow = workflow_path().read_text()
    tail = workflow.split('          script: |\n', 1)[1]
    program = tail.split("            /usr/bin/python3 -I -B - <<'PYCODE'\n", 1)[1].split('            PYCODE', 1)[0]
    return textwrap.dedent(program)


def bind_fixture(core=CORE):
    """Change pins only inside synthetic memory; deployed source is untouched."""
    source = Path(H.__file__).read_text()
    tree = ast.parse(source)
    changes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CORE_SHA256' for t in node.targets):
            changes.append((node.lineno, node.end_lineno, 'CORE_SHA256 = ' + repr(hashlib.sha256(core).hexdigest())))
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SOURCE_PINS' for t in node.targets):
            changes.append((node.lineno, node.end_lineno, 'SOURCE_PINS = ' + repr(PINS)))
    if len(changes) != 2:
        raise AssertionError('SYNTHETIC_PIN_SHAPE')
    lines = source.splitlines(keepends=True)
    for start, end, replacement in sorted(changes, reverse=True):
        lines[start-1:end] = [replacement+'\n']
    raw = ''.join(lines).encode()
    host = types.ModuleType('synthetic_pinned_host')
    exec(compile(raw, '<synthetic-pinned-host>', 'exec'), host.__dict__)
    return raw, host, host.encode(core, SOURCES, raw)


def execute_bootstrap(wire, host_raw, *, pin=True):
    source = bootstrap()
    pin_value = repr(hashlib.sha256(host_raw).hexdigest()) if pin else 'None'
    # Root may register the production pin later; the synthetic memory is exact.
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == 'EXPECTED_HOST_SHA256' for t in n.targets))
    lines = source.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno] = ['EXPECTED_HOST_SHA256 = '+pin_value+'\n']
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {'EXPORT_BINDING_READONLY_WIRE': wire,
                                     'DO_NOT_EMIT_ENV_SECRET': 'SYNTHETIC_SECRET'}, clear=True):
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exec(compile(''.join(lines), '<actual-workflow-bootstrap>', 'exec'), {})
    text = out.getvalue()
    assert text.count('\n') == 1 and text.startswith('NAVER_EXPORT_BINDING_READONLY_V1=')
    assert err.getvalue() == ''
    assert 'DO_NOT_EMIT' not in text and 'SYNTHETIC_SECRET' not in text
    return json.loads(text.split('=', 1)[1])


class HostBoundaryTests(unittest.TestCase):
    def test_missing_core_pin_stops_before_encoding_or_exec(self):
        with mock.patch.object(H, 'CORE_SHA256', None), mock.patch.object(H.lzma, 'compress') as compress:
            with self.assertRaisesRegex(ValueError, '^CORE_PIN_REQUIRED$'):
                H.encode(b'raise AssertionError()', SOURCES, b'host')
            compress.assert_not_called()

    def test_each_public_source_and_core_mutation_is_rejected(self):
        with mock.patch.object(H, 'CORE_SHA256', hashlib.sha256(CORE).hexdigest()), mock.patch.object(H, 'SOURCE_PINS', PINS):
            with self.assertRaisesRegex(ValueError, '^CORE_CHANGED$'):
                H.require_sources(CORE+b'\n', SOURCES)
            for role in SOURCES:
                with self.subTest(role=role):
                    changed = dict(SOURCES); changed[role] += b'\n'
                    with self.assertRaisesRegex(ValueError, '^SOURCE_CHANGED$'):
                        H.require_sources(CORE, changed)
            with self.assertRaisesRegex(ValueError, '^SOURCES_SHAPE$'):
                H.require_sources(CORE, dict(SOURCES, extra=b'no'))

    def test_roundtrip_is_exact_and_payload_caps_are_enforced(self):
        host_raw, host, wire = bind_fixture()
        package = host.decode(wire)
        self.assertEqual(package['host'].encode(), host_raw)
        self.assertEqual(package['core'].encode(), CORE)
        self.assertEqual({k:v.encode() for k,v in package['sources'].items()}, SOURCES)
        for bound in ('MAX_JSON', 'MAX_WIRE'):
            with self.subTest(bound=bound), mock.patch.object(host, bound, 1):
                with self.assertRaises(ValueError):
                    host.encode(CORE, SOURCES, host_raw)

    def test_invalid_json_duplicate_nonfinite_and_boolean_version_rejected(self):
        invalid = [b'{"version":1,"version":1}', b'{"version":NaN}',
                   compact({'version':True,'host':'h','core':'c','sources':{}})]
        for raw in invalid:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    H.decode(wire_raw(raw))

    def test_truncated_appended_oversize_and_large_dictionary_rejected(self):
        raw = compact({'version':1,'host':'h','core':'c','sources':{}})
        compressed = lzma.compress(raw)
        wires = [base64.b85encode(compressed[:-1]).decode(),
                 base64.b85encode(compressed+b'x').decode(),
                 wire_raw(b'x'*(H.MAX_JSON+1)), wire_raw(raw, preset=9),
                 'a'*(H.MAX_WIRE+1)]
        for wire in wires:
            with self.subTest(size=len(wire)):
                with self.assertRaises((ValueError, lzma.LZMAError)):
                    H.decode(wire)

    def test_actual_bootstrap_runs_core_once_with_environment_cleared_and_no_leaks(self):
        host_raw, _, wire = bind_fixture()
        result = execute_bootstrap(wire, host_raw)
        self.assertIs(result['transport_ok'], True)
        self.assertEqual(result['result'], {'ok':True,'calls':1,'source_count':4})

    def test_actual_bootstrap_rejects_unset_pin_host_core_and_source_tampering(self):
        host_raw, host, wire = bind_fixture()
        self.assertIs(execute_bootstrap(wire, host_raw, pin=False)['transport_ok'], False)
        for field in ('host', 'core', 'exports_binding'):
            package = host.decode(wire)
            if field in ('host', 'core'):
                package[field] += '\n'
            else:
                package['sources'][field] += '\n'
            with self.subTest(field=field):
                result = execute_bootstrap(wire_raw(compact(package)), host_raw)
                self.assertEqual(result['error_code'], 'HOST_REFUSED')
                self.assertIsNone(result['result'])

    def test_actual_bootstrap_failure_discards_raw_exception_and_prints(self):
        core = CORE.replace(b"return {'ok':True,'calls':calls,'source_count':len(sources)}", b"raise RuntimeError('DO_NOT_EMIT_ERROR_SECRET')")
        host_raw, _, wire = bind_fixture(core)
        result = execute_bootstrap(wire, host_raw)
        self.assertFalse(result['transport_ok'])
        self.assertEqual(result['error_code'], 'HOST_REFUSED')

    def test_result_size_and_strict_json_boundaries(self):
        for return_code in ("return 'x'*4097", "return '{\"ok\":true,\"ok\":false}'", "return 'NaN'", "return '[]'"):
            core = CORE.replace(b'return json.dumps(value)', return_code.encode())
            host_raw, _, wire = bind_fixture(core)
            with self.subTest(return_code=return_code):
                self.assertFalse(execute_bootstrap(wire, host_raw)['transport_ok'])

    def test_workflow_auth_native_gate_and_frozen_sources(self):
        text = workflow_path().read_text()
        self.assertIn("options: [READ_EXISTING_EXPORT_BINDING_ONCE]", text)
        self.assertIn("github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/codex/naver-claude-reference-ops-20261011' && inputs.confirm == 'READ_EXISTING_EXPORT_BINDING_ONCE'", text)
        self.assertIn('needs: synthetic', text)
        self.assertIn("r['head_sha']==os.environ['GITHUB_SHA']", text)
        self.assertIn("r['head_branch']=='codex/naver-claude-reference-ops-20261011'", text)
        self.assertIn("r['status']=='completed' and r['conclusion']=='success'", text)
        self.assertIn('naver-product-export-tests.yml/runs?head_sha=', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertNotIn('continue-on-error', text)
        self.assertNotIn('workflow_run:', text)
        self.assertEqual(H.SOURCE_FILES['product_exporter'], 'backend/naver_product_export.py')
        self.assertEqual(H.SOURCE_FILES['market_exporter'], 'backend/naver_market_export.py')
        self.assertLess(len(bootstrap().encode()), 32768)
        self.assertLess(H.MAX_WIRE+len(bootstrap().encode())+1024, 131072)


if __name__ == '__main__':
    unittest.main()
