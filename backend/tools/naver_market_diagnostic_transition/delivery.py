"""Pinned, bounded envelope for the separately qualified diagnostic transition.

No host call on import/decode. The SSH bootstrap must pin this file's exact
SHA256 before executing it. All nine module and five public-source pins are
checked before any module import; requests expose only action and paired IDs.
Existing product release helper/dependencies and budgets are untouched.
"""
import base64
import contextlib
import hashlib
import json
import lzma
import re
import sys
import types

MODULE_PINS = {
    'transition': '89ab4f61004846a90ec75a147b398d5f17eae016a268e375e7c44433143c3a92',
    'journal': '27e2ec8c7b332951151dcb19bd60ec527eb768d1b1711f40069b8dd1ac191333',
    'preflight': '0a48d024d352bb2d32cfa920ee530501001bb889d32219ff8b14dcca0984b7c3',
    'systemd_boundary': 'a0559bdca3bee319a8bc3d37425a6854185ec06245b69ec494a4513221fe72ac',
    'publication': 'da60c15bca0dc48c9dda794ade7e87877f5fec13678a908a3f58657bb34be8a1',
    'host_port': 'f4ed31a5e40db1593358295d30119b95e5ce2d8b3bc3cc97680f94e724562500',
    'current_guard': '6a9377b6ed3d511e054c1234b0b830314331ddadad3b5887b79a8c36e611e5d8',
    'provisioning': '651927b4a93bc68f57dfac3645bd9a2c4fbdf4a0f0ec32beef94389e40a19ad0',
    'entrypoint': 'b24302665afb5623b8c466f563b3c50c236dfbbabcebc6a3be3519d77df7c162',
}
SOURCE_PINS = {
    'exports_binding': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed',
    'exports_helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737',
    'product_exporter': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59',
    'market_exporter': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8',
    'diagnostic_exporter': '9bb25d4acda4edca44aa71c238a6bf53be7dab5e093bc4f0c69d45c0d0891851',
}
MAX_MODULE = MAX_HOST = MAX_BOOT = 32768
MAX_SOURCE, MAX_JSON, MAX_WIRE, MAX_SSH = 65536, 393216, 102400, 131072
MAX_RESULT, DECODER_MEMORY = 4096, 32 * 1024 * 1024
ISSUES = {'input_bytes', 'rows', 'time', 'cell', 'clients', 'unknown'}


def fail(code): raise ValueError(code)


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value: fail('PACKAGE_JSON')
        value[key] = item
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def strict(raw):
    return json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: fail('PACKAGE_JSON'))


def request(value):
    if (type(value) is not dict or set(value) != {'version', 'action', 'apply_id', 'rollback_id'}
            or type(value['version']) is not int or value['version'] != 1
            or type(value['action']) is not str or value['action'] not in ('apply', 'rollback')):
        fail('REQUEST')
    for key in ('apply_id', 'rollback_id'):
        v = value[key]
        if type(v) is not str or not re.fullmatch('[0-9a-f]{32}', v) or v == '0' * 32:
            fail('REQUEST')
    if value['apply_id'] == value['rollback_id']: fail('REQUEST')
    return strict(canonical(value))


def exact(values, pins, maximum):
    if type(values) is not dict or set(values) != set(pins): fail('SOURCE_SHAPE')
    result = {}
    for role, pin in pins.items():
        body = values[role]
        if (type(body) is not str or not 0 < len(body.encode()) <= maximum
                or hashlib.sha256(body.encode()).hexdigest() != pin): fail('SOURCE_CHANGED')
        result[role] = body.encode()
    return result


def validate(package):
    if (type(package) is not dict or set(package) != {'version', 'host', 'modules', 'sources', 'request'}
            or type(package['version']) is not int or package['version'] != 1
            or type(package['host']) is not str or not 0 < len(package['host'].encode()) <= MAX_HOST):
        fail('PACKAGE_SHAPE')
    value = request(package['request'])
    modules = exact(package['modules'], MODULE_PINS, MAX_MODULE)
    sources = exact(package['sources'], SOURCE_PINS, MAX_SOURCE)
    if len(canonical(package)) > MAX_JSON: fail('PACKAGE_SIZE')
    return value, modules, sources


def encode(modules, sources, host, value):
    if (type(modules) is not dict or type(sources) is not dict or type(host) is not bytes
            or any(type(x) is not bytes for x in (*modules.values(), *sources.values()))):
        fail('PACKAGE_SHAPE')
    package = dict(version=1, host=host.decode(), modules={k:v.decode() for k,v in modules.items()},
                   sources={k:v.decode() for k,v in sources.items()}, request=value)
    validate(package)
    raw = canonical(package)
    wire = base64.b85encode(lzma.compress(raw, format=lzma.FORMAT_XZ, preset=6)).decode('ascii')
    if len(wire) > MAX_WIRE: fail('WIRE_SIZE')
    return wire


def decode(wire):
    if type(wire) is not str or not 0 < len(wire) <= MAX_WIRE or not wire.isascii(): fail('WIRE_SIZE')
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=DECODER_MEMORY)
    raw = decoder.decompress(base64.b85decode(wire), max_length=MAX_JSON + 1)
    if len(raw) > MAX_JSON or not decoder.eof or decoder.unused_data: fail('PACKAGE_SIZE')
    package = strict(raw); validate(package)
    return package


def closed_result(value, req):
    keys = {'version', 'action', 'apply_id', 'rollback_id', 'preparation_sha256', 'result',
            'original_export_success_verified', 'product_deployed', 'ads_written'}
    if type(value) is not dict or set(value) != keys: fail('RESULT')
    if (request({k:value[k] for k in req}) != req
            or any(value[k] is not False for k in ('original_export_success_verified', 'product_deployed', 'ads_written'))):
        fail('RESULT')
    for digest in (value['preparation_sha256'], value['result'].get('plan_sha256') if type(value['result']) is dict else None):
        if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest): fail('RESULT')
    result = value['result']
    if req['action'] == 'apply':
        if (set(result) != {'plan_sha256', 'rollback_required', 'observation', 'product_export_verified'}
                or result['rollback_required'] is not True or result['product_export_verified'] is not False): fail('RESULT')
        obs = result['observation']
        if type(obs) is not dict or set(obs) != {'status', 'limit_issue', 'exit_status'}: fail('RESULT')
        if type(obs['exit_status']) is not int or not 0 <= obs['exit_status'] <= 255: fail('RESULT')
        if obs['status'] == 'source_limit':
            if type(obs['limit_issue']) is not str or obs['limit_issue'] not in ISSUES or obs['exit_status'] != 1: fail('RESULT')
        elif obs['status'] == 'diagnostic_unavailable':
            if obs['limit_issue'] is not None: fail('RESULT')
        else: fail('RESULT')  # Production reader never promotes unit success.
    elif (set(result) != {'plan_sha256', 'restored', 'natural_timer_catchup_possible', 'product_export_verified'}
            or result['restored'] is not True or result['natural_timer_catchup_possible'] is not True
            or result['product_export_verified'] is not False): fail('RESULT')
    if len(canonical(value)) > MAX_RESULT: fail('RESULT_SIZE')
    return strict(canonical(value))


class Discard:
    def write(self, value): return len(value)
    def flush(self): pass


def run(package):
    """No retry or implicit rollback. Invoke only in an isolated pinned process."""
    req, bodies, sources = validate(package)
    if any(name in sys.modules for name in MODULE_PINS): fail('MODULE_COLLISION')
    loaded = {}
    try:
        with contextlib.redirect_stdout(Discard()), contextlib.redirect_stderr(Discard()):
            for name, body in bodies.items():
                module = types.ModuleType(name); loaded[name] = module; sys.modules[name] = module
                exec(compile(body, '<pinned-diagnostic-' + name + '>', 'exec'), module.__dict__)
            baseline = {k:v for k,v in sources.items() if k != 'diagnostic_exporter'}
            compiled = dict(helper=sources['exports_helper'], product=sources['product_exporter'],
                            old_market=sources['market_exporter'], market=sources['diagnostic_exporter'])
            value = loaded['entrypoint'].run(req, sources=compiled, baseline_sources=baseline)
            return closed_result(value, req)
    finally:
        for name, module in loaded.items():
            if sys.modules.get(name) is module: del sys.modules[name]


if __name__ == '__main__': raise SystemExit('PINNED_WORKFLOW_REQUIRED')
