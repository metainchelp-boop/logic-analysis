"""The unchanged frozen 45 cases, using authenticated source4d temporary files.

Only the class's unittest namespace and its ROOT data path are rebound. The
three frozen Python sources, all test bodies, and historical proof stay exact.
"""
import importlib.util
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location('_daily_current_fixture_v3', _HERE / 'source_fixture.py')
SF = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SF)
_FROZEN = SF.frozen_bytes()
_FOLDER = SF.ASSETS / 'frozen-reader'
_D = SF.frozen_module('reader', _FROZEN['reader.py'], _FOLDER / 'reader.py')
_F = SF.frozen_module('fixtures', _FROZEN['fixtures.py'], _FOLDER / 'fixtures.py')
with patch.dict(sys.modules, {'reader': _D, 'fixtures': _F}):
    _TESTS = SF.frozen_module('_frozen_daily_current_reader_v3', _FROZEN['test_reader.py'], _FOLDER / 'test_reader.py')
ReaderTests = _TESTS.ReaderTests
ReaderTests.__module__ = __name__

_OLD_PATH = None
_OLD_MODULES = None
_TEMP = None
_BLOCKS = []


def _product_module(name):
    return any(name == prefix or name.startswith(prefix + '.') for prefix in ('naver_engine', 'naver_runtime', 'app'))


def _denied(*args, **kwargs):
    raise AssertionError('D3_FIXTURE_EXTERNAL_IO_DISABLED')


def setUpModule():
    global _OLD_PATH, _OLD_MODULES, _TEMP
    _OLD_PATH = list(sys.path)
    _OLD_MODULES = {name: value for name, value in sys.modules.copy().items() if _product_module(name)}
    for name in _OLD_MODULES:
        del sys.modules[name]
    try:
        for obj, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                (socket, 'create_connection'), (subprocess, 'run'), (subprocess, 'Popen')):
            block = patch.object(obj, name, side_effect=_denied)
            block.start()
            _BLOCKS.append(block)
        _TEMP = tempfile.TemporaryDirectory(prefix='d3-frozen-source4d-')
        root = SF.extract_source(Path(_TEMP.name).resolve() / 'source4d')
        _TESTS.ROOT = root
        SF.refuse(len([n for n in vars(ReaderTests) if n.startswith('test_')]) == 45)
        SF.refuse(_D.verify_source(root) == root)
    except BaseException:
        tearDownModule()
        raise


def tearDownModule():
    global _TEMP, _OLD_MODULES, _OLD_PATH
    for name in tuple(sys.modules):
        if _product_module(name):
            del sys.modules[name]
    if _OLD_MODULES is not None:
        sys.modules.update(_OLD_MODULES)
        _OLD_MODULES = None
    if _OLD_PATH is not None:
        sys.path[:] = _OLD_PATH
        _OLD_PATH = None
    while _BLOCKS:
        _BLOCKS.pop().stop()
    if _TEMP is not None:
        _TEMP.cleanup()
        _TEMP = None
