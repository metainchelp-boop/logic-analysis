"""Fixed public-source envelope for one existing-export read-only diagnosis.

No network, file, subprocess, export, deployment or database operation is defined
here. The reviewed diagnostic core owns the narrow read-only observation.
"""
import base64
import contextlib
import hashlib
import json
import lzma
import re
import types

CORE_SHA256 = '63f3a3c2b4a1cd0537eeae76d625fa47e916decc59b883b2d04d39431aa5aa4a'  # Root registers the independently reviewed final core.
SOURCE_FILES = {
    'exports_binding': 'backend/tools/naver_completion_exports.py',
    'exports_helper': 'backend/tools/naver_saved_exports.py',
    'product_exporter': 'backend/naver_product_export.py',
    'market_exporter': 'backend/naver_market_export.py',
}
SOURCE_PINS = {
    'exports_binding': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed',
    'exports_helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737',
    'product_exporter': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59',
    'market_exporter': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8',
}
MAX_CORE = 32768
MAX_HOST = 32768
MAX_SOURCE = 65536
MAX_JSON = 131072
MAX_WIRE = 65536
MAX_RESULT = 4096
DECODER_MEMORY = 32 * 1024 * 1024


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('PACKAGE_JSON')
        value[key] = item
    return value


def strict_json(raw):
    return json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('PACKAGE_JSON')))


def require_sources(core, sources):
    if type(CORE_SHA256) is not str or re.fullmatch('[0-9a-f]{64}', CORE_SHA256) is None:
        raise ValueError('CORE_PIN_REQUIRED')
    if (type(core) is not bytes or not 0 < len(core) <= MAX_CORE or
            hashlib.sha256(core).hexdigest() != CORE_SHA256):
        raise ValueError('CORE_CHANGED')
    if type(sources) is not dict or set(sources) != set(SOURCE_PINS):
        raise ValueError('SOURCES_SHAPE')
    for role, pin in SOURCE_PINS.items():
        body = sources[role]
        if (type(body) is not bytes or not 0 < len(body) <= MAX_SOURCE or
                hashlib.sha256(body).hexdigest() != pin):
            raise ValueError('SOURCE_CHANGED')


def encode(core, sources, host):
    require_sources(core, sources)
    if type(host) is not bytes or not 0 < len(host) <= MAX_HOST:
        raise ValueError('HOST_SIZE')
    package = {'version': 1, 'host': host.decode('utf-8'), 'core': core.decode('utf-8'),
               'sources': {key: body.decode('utf-8') for key, body in sources.items()}}
    raw = json.dumps(package, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_JSON:
        raise ValueError('PACKAGE_SIZE')
    wire = base64.b85encode(lzma.compress(raw, format=lzma.FORMAT_XZ, preset=6)).decode('ascii')
    if len(wire) > MAX_WIRE:
        raise ValueError('WIRE_SIZE')
    return wire


def decode(wire):
    if type(wire) is not str or not 0 < len(wire) <= MAX_WIRE or not wire.isascii():
        raise ValueError('WIRE_SIZE')
    compressed = base64.b85decode(wire)
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=DECODER_MEMORY)
    raw = decoder.decompress(compressed, max_length=MAX_JSON + 1)
    if len(raw) > MAX_JSON or not decoder.eof or decoder.unused_data:
        raise ValueError('PACKAGE_SIZE')
    package = strict_json(raw)
    if (type(package) is not dict or set(package) != {'version', 'host', 'core', 'sources'} or
            type(package['version']) is not int or package['version'] != 1 or
            type(package['host']) is not str or type(package['core']) is not str or
            type(package['sources']) is not dict or
            any(type(item) is not str for item in package['sources'].values())):
        raise ValueError('PACKAGE_SHAPE')
    return package


class _Discard:
    def write(self, value):
        return len(value)

    def flush(self):
        return None


def run(core, sources):
    require_sources(core, sources)
    module = types.ModuleType('fixed_export_binding_readonly')
    # Do not copy, retain or emit a diagnostic's accidental print or exception.
    with contextlib.redirect_stdout(_Discard()), contextlib.redirect_stderr(_Discard()):
        exec(compile(core, '<pinned-export-binding-readonly>', 'exec'), module.__dict__)
        result = module.diagnose(sources)
        closed = module.closed_json(result)
    if type(closed) is not str or len(closed.encode('utf-8')) > MAX_RESULT:
        raise ValueError('RESULT_SIZE')
    value = strict_json(closed)
    if type(value) is not dict:
        raise ValueError('RESULT_SHAPE')
    return {'version': 1, 'transport': 'existing-export-binding-readonly',
            'transport_ok': True, 'error_code': None, 'result': value}


if __name__ == '__main__':
    raise SystemExit('PINNED_WORKFLOW_REQUIRED')
