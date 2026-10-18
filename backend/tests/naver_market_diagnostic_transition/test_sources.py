"""Test-only fixed repository layout; read public pinned source bytes only.

No runtime import, environment override, parent search, or fallback resolution.
Private *_at functions support isolated filesystem fixtures in resolver tests.
This registry is a schema candidate projection, not release qualification.
"""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat

_ROOT = Path(__file__).absolute().parents[3]
MODULE_NAMES = ('transition', 'journal', 'preflight', 'systemd_boundary',
                'publication', 'host_port', 'current_guard', 'provisioning', 'entrypoint')
BASELINE_ROLES = ('exports_binding', 'exports_helper', 'product_exporter', 'market_exporter')
PUBLIC_ROLES = BASELINE_ROLES + ('diagnostic_exporter',)
FILES = {'bootstrap': {'bytes': 3974,
               'path': 'backend/tools/naver_market_diagnostic_transition/bootstrap.py',
               'sha256': 'c7031553808146394ccc899a67e8ef76fbae7946ff4a389f874d0c041feb098c'},
 'current_guard': {'bytes': 10836,
                   'path': 'backend/tools/naver_market_diagnostic_transition/current_guard.py',
                   'sha256': '6a9377b6ed3d511e054c1234b0b830314331ddadad3b5887b79a8c36e611e5d8'},
 'delivery': {'bytes': 8446,
              'path': 'backend/tools/naver_market_diagnostic_transition/delivery.py',
              'sha256': '3026d83baa140cd45b0e9361c40a50274fd41bd914885aa46011f904a99b7bcc'},
 'diagnostic_exporter': {'bytes': 19540,
                         'path': 'backend/tools/naver_market_diagnostic_transition/diagnostic_market_export.py',
                         'sha256': '9bb25d4acda4edca44aa71c238a6bf53be7dab5e093bc4f0c69d45c0d0891851'},
 'diagnostic_failure_consumer': {'bytes': 23009,
                                 'path': 'backend/tools/naver_market_diagnostic_transition/diagnostic_failure_consumer.py',
                                 'sha256': '8011a44a6f7965e1dfc9b0c17cfeb766dca0c31107494da1bcfc862d1b8598d8'},
 'diagnostic_product_sibling': {'bytes': 20647,
                                'path': 'backend/tools/naver_market_diagnostic_transition/naver_product_export.py',
                                'sha256': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59'},
 'entrypoint': {'bytes': 4181,
                'path': 'backend/tools/naver_market_diagnostic_transition/entrypoint.py',
                'sha256': 'b24302665afb5623b8c466f563b3c50c236dfbbabcebc6a3be3519d77df7c162'},
 'exports_binding': {'bytes': 10121,
                     'path': 'backend/tools/naver_completion_exports.py',
                     'sha256': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed'},
 'exports_helper': {'bytes': 37216,
                    'path': 'backend/tools/naver_saved_exports.py',
                    'sha256': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737'},
 'host_port': {'bytes': 7744,
               'path': 'backend/tools/naver_market_diagnostic_transition/host_port.py',
               'sha256': 'f4ed31a5e40db1593358295d30119b95e5ce2d8b3bc3cc97680f94e724562500'},
 'journal': {'bytes': 11244,
             'path': 'backend/tools/naver_market_diagnostic_transition/journal.py',
             'sha256': '27e2ec8c7b332951151dcb19bd60ec527eb768d1b1711f40069b8dd1ac191333'},
 'market_exporter': {'bytes': 17992,
                     'path': 'backend/naver_market_export.py',
                     'sha256': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'},
 'preflight': {'bytes': 11165,
               'path': 'backend/tools/naver_market_diagnostic_transition/preflight.py',
               'sha256': '0a48d024d352bb2d32cfa920ee530501001bb889d32219ff8b14dcca0984b7c3'},
 'product_exporter': {'bytes': 20647,
                      'path': 'backend/naver_product_export.py',
                      'sha256': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59'},
 'provisioning': {'bytes': 10009,
                  'path': 'backend/tools/naver_market_diagnostic_transition/provisioning.py',
                  'sha256': '651927b4a93bc68f57dfac3645bd9a2c4fbdf4a0f0ec32beef94389e40a19ad0'},
 'publication': {'bytes': 11483,
                 'path': 'backend/tools/naver_market_diagnostic_transition/publication.py',
                 'sha256': 'da60c15bca0dc48c9dda794ade7e87877f5fec13678a908a3f58657bb34be8a1'},
 'strict_receiver': {'bytes': 13955,
                     'path': 'backend/tools/naver_market_diagnostic_transition/strict_receiver.py',
                     'sha256': '30ed12d72c185df61a69494d7368b1f80030c53a6958ed213b067d99653d29c7'},
 'systemd_boundary': {'bytes': 15655,
                      'path': 'backend/tools/naver_market_diagnostic_transition/systemd_boundary.py',
                      'sha256': 'a0559bdca3bee319a8bc3d37425a6854185ec06245b69ec494a4513221fe72ac'},
 'transition': {'bytes': 16085,
                'path': 'backend/tools/naver_market_diagnostic_transition/transition.py',
                'sha256': '89ab4f61004846a90ec75a147b398d5f17eae016a268e375e7c44433143c3a92'}}


def _path_at(root, name):
    if type(name) is not str or name not in FILES:
        raise ValueError('PORTABLE_SOURCE_NAME')
    item = FILES[name]
    if type(item) is not dict or set(item) != {'path', 'sha256', 'bytes'}:
        raise ValueError('PORTABLE_REGISTRY_SHAPE')
    rel = item['path']
    if (type(rel) is not str or '\\' in rel or not rel
            or PurePosixPath(rel).is_absolute() or '..' in PurePosixPath(rel).parts
            or str(PurePosixPath(rel)) != rel or not rel.startswith('backend/')
            or not rel.endswith('.py')):
        raise ValueError('PORTABLE_SOURCE_PATH')
    if (type(item['bytes']) is not int or not 0 < item['bytes'] <= 131072
            or type(item['sha256']) is not str
            or re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is None):
        raise ValueError('PORTABLE_REGISTRY_PIN')
    root = Path(root)
    if not root.is_absolute():
        raise ValueError('PORTABLE_SOURCE_ROOT')
    current = root
    try:
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise ValueError('PORTABLE_SOURCE_DIRECTORY')
        parts = PurePosixPath(rel).parts
        for part in parts[:-1]:
            current = current / part
            if not stat.S_ISDIR(current.lstat().st_mode):
                raise ValueError('PORTABLE_SOURCE_DIRECTORY')
        target = current / parts[-1]
        value = target.lstat()
        if not stat.S_ISREG(value.st_mode) or value.st_size != item['bytes']:
            raise ValueError('PORTABLE_SOURCE_FILE')
    except OSError:
        raise ValueError('PORTABLE_SOURCE_UNAVAILABLE') from None
    return target


def _read_at(root, name):
    target = _path_at(root, name)
    expected = FILES[name]
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != expected['bytes']:
                raise ValueError('PORTABLE_SOURCE_FILE')
            value = stream.read(expected['bytes'] + 1)
    except OSError:
        raise ValueError('PORTABLE_SOURCE_UNAVAILABLE') from None
    if len(value) != expected['bytes'] or hashlib.sha256(value).hexdigest() != expected['sha256']:
        raise ValueError('PORTABLE_SOURCE_CHANGED')
    return value


def baseline_sources():
    return {role: _read_at(_ROOT, role) for role in BASELINE_ROLES}


def transition_sources():
    mapping = {'helper': 'exports_helper', 'product': 'product_exporter',
               'old_market': 'market_exporter', 'market': 'diagnostic_exporter'}
    return {role: _read_at(_ROOT, name) for role, name in mapping.items()}


def delivery_materials():
    return ({name: _read_at(_ROOT, name) for name in MODULE_NAMES},
            {role: _read_at(_ROOT, role) for role in PUBLIC_ROLES},
            _read_at(_ROOT, 'delivery'))


def renderer_source():
    return _read_at(_ROOT, 'bootstrap')


def producer_source_path():
    _read_at(_ROOT, 'diagnostic_exporter')
    _read_at(_ROOT, 'diagnostic_product_sibling')
    return _path_at(_ROOT, 'diagnostic_exporter')


def consumer_source_path():
    _read_at(_ROOT, 'diagnostic_failure_consumer')
    return _path_at(_ROOT, 'diagnostic_failure_consumer')


def validate_layout():
    """Hashes only; this does not import or execute any candidate runtime."""
    return {name: hashlib.sha256(_read_at(_ROOT, name)).hexdigest() for name in FILES}
