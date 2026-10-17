"""Fixture-only provenance; fixed core and its acceptance guards remain unchanged."""
import ctypes
import hashlib
import importlib.util
import json
import mmap
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from naver_market_probe_namespace_fixture import independent_writer

try:
    from test_naver_market_source_limit_probe import D, SOURCES, BACKEND, tables
except ModuleNotFoundError as error:
    if error.name != 'test_naver_market_source_limit_probe':
        raise
    fixture = Path(__file__).resolve().parents[1] / 'market-limit-probe-draft/test_naver_market_source_limit_probe.py'
    spec = importlib.util.spec_from_file_location('fixed_market_probe_fixtures', fixture)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    D, SOURCES, BACKEND, tables = module.D, module.SOURCES, module.BACKEND, module.tables

CORE_SHA256 = 'd41d674a9db1a9d6317e2ff4a3587a2d29cbef5278bda5e330c3d471bcfe6c90'
# In this isolated draft only, use the adjacent candidate core. Installed CI
# loads backend/tools through the original fixture module above.
_candidate = Path(__file__).with_name('naver_market_source_limit_probe.py')
if not _candidate.is_file():
    _candidate = Path(__file__).resolve().parents[1] / 'market-limit-probe-linux-fix-draft/naver_market_source_limit_probe.py'
if _candidate.is_file():
    _body = _candidate.read_bytes()
    if hashlib.sha256(_body).hexdigest() != CORE_SHA256:
        raise ValueError('FIXTURE_CORE_PIN')
    _candidate_module = types.ModuleType('fixed_candidate_namespace_core')
    _candidate_module.__file__ = str(_candidate)
    exec(compile(_body, str(_candidate), 'exec'), _candidate_module.__dict__)
    D = _candidate_module
    del _body
PHASES = ('none', 'source_load', 'namespace', 'connect', 'collect', 'file_family', 'fd_bind', 'fd_snapshot')
STAGES = (
    'none', 'unmapped_fixed_frame', 'source_load', 'connect', 'collect',
    'linux_root', 'source_family', 'parent_mount_namespace', 'parent_network_namespace',
    'libc_load', 'source_directory_fd', 'unshare', 'namespace_identity', 'private_propagation',
    'private_tmpfs', 'alias_directory', 'source_bind', 'readonly_remount', 'source_fd_close',
    'readonly_family_before_drop', 'user_database', 'user_lookup', 'group_lookup', 'nonroot_identity',
    'limit_core', 'limit_file', 'limit_memory', 'limit_cpu', 'limit_fds', 'bounding_capability_drop',
    'ambient_capability_clear', 'set_groups', 'set_gid', 'set_uid', 'no_new_privileges',
    'capability_structures', 'capability_clear', 'capability_status_read', 'capability_status_check',
    'environment_clear', 'readonly_family_after_drop', 'file_family', 'fd_bind', 'fd_snapshot',
)
NS_LINES = {358: 'linux_root', 359: 'linux_root', 360: 'source_family', 361: 'source_family', 362: 'source_family', 363: 'parent_mount_namespace', 364: 'parent_network_namespace', 365: 'libc_load', 366: 'libc_load', 367: 'libc_load', 378: 'source_directory_fd', 374: 'unshare', 375: 'unshare', 376: 'namespace_identity', 377: 'namespace_identity', 379: 'private_propagation', 380: 'private_tmpfs', 381: 'alias_directory', 382: 'source_bind', 383: 'readonly_remount', 386: 'source_fd_close', 387: 'readonly_family_before_drop', 388: 'readonly_family_before_drop', 389: 'user_database', 390: 'user_lookup', 393: 'group_lookup', 394: 'nonroot_identity', 395: 'nonroot_identity', 396: 'limit_core', 397: 'limit_file', 398: 'limit_memory', 399: 'limit_cpu', 400: 'limit_fds', 402: 'bounding_capability_drop', 403: 'bounding_capability_drop', 404: 'ambient_capability_clear', 405: 'ambient_capability_clear', 406: 'set_groups', 407: 'set_gid', 408: 'set_uid', 409: 'no_new_privileges', 410: 'no_new_privileges', 412: 'capability_structures', 413: 'capability_structures', 415: 'capability_structures', 416: 'capability_structures', 417: 'capability_structures', 418: 'capability_clear', 419: 'capability_clear', 420: 'capability_status_read', 422: 'capability_status_check', 423: 'capability_status_check', 424: 'capability_status_check', 425: 'environment_clear', 426: 'readonly_family_after_drop', 427: 'readonly_family_after_drop'}
FAMILY_CHECKS = ('none', 'directory_identity', 'readonly_directory', 'file_stat', 'file_identity_access')
FAMILY_LINES = {326: 'directory_identity', 327: 'directory_identity', 328: 'readonly_directory',
                329: 'readonly_directory', 333: 'file_stat', 334: 'file_identity_access', 335: 'file_identity_access'}
SUFFIXES = ('none', 'main', 'wal', 'shm')
CAP_FIELDS = ('none', 'inheritable', 'permitted', 'effective', 'ambient', 'bounding')
EXCEPTIONS = ('none', 'probe_stop', 'os_error', 'memory', 'key', 'value', 'sqlite', 'other')
WORDS = struct.Struct('!18i')


def verify_core():
    if hashlib.sha256(Path(D.__file__).read_bytes()).hexdigest() != CORE_SHA256:
        raise ValueError('FIXTURE_CORE_PIN')
    if D._namespace.__code__.co_firstlineno != 357 or D._file_family.__code__.co_firstlineno != 325:
        raise ValueError('FIXTURE_CORE_LAYOUT')


class Provenance:
    """Only fixed integers cross fork, with no traceback or raw values retained."""
    def __init__(self):
        verify_core()
        self.shared = mmap.mmap(-1, 96, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE)
        self.namespace_code = D._namespace.__code__
        self.family_code = D._file_family.__code__
        self.fd_bind_code = D._bind_sqlite_fds.__code__
        self.mount_codes = {value for value in self.namespace_code.co_consts
                            if isinstance(value, types.CodeType) and value.co_name == 'mount'}
        self.shared[:WORDS.size] = WORDS.pack(0, 0, 0, 0, 0, 0, 0, -1, 0, -1, 0, 0, -1, -1, -1, -1, -1, -1)

    def _get(self):
        return list(WORDS.unpack(self.shared[:WORDS.size]))

    def entered(self, phase):
        values = self._get()
        values[0] |= 1 << PHASES.index(phase)
        self.shared[:WORDS.size] = WORDS.pack(*values)

    def passed(self, phase):
        values = self._get()
        values[1] |= 1 << PHASES.index(phase)
        self.shared[:WORDS.size] = WORDS.pack(*values)

    def failed(self, phase, error):
        values = self._get()
        # Preserve the innermost first exception, while allowing the outer namespace
        # wrapper to refine a family failure to its exact before/after-drop call.
        outer_refinement = values[2] == PHASES.index('file_family') and phase == 'namespace'
        if values[2] and not outer_refinement:
            return
        values[2] = PHASES.index(phase)
        values[3] = STAGES.index(phase if phase in STAGES else 'unmapped_fixed_frame')
        values[6] = EXCEPTIONS.index('probe_stop' if type(error) is D.ProbeStop else
            'os_error' if isinstance(error, OSError) else 'memory' if isinstance(error, MemoryError) else
            'key' if isinstance(error, KeyError) else 'value' if isinstance(error, ValueError) else
            'sqlite' if isinstance(error, sqlite3.Error) else 'other')
        if isinstance(error, OSError) and type(error.errno) is int and 0 <= error.errno <= 4095:
            values[7] = error.errno
        tb, namespace_line, c_failure = error.__traceback__, None, False
        while tb is not None:
            frame, line = tb.tb_frame, tb.tb_lineno
            if frame.f_code is self.namespace_code:
                namespace_line = line
                values[3] = STAGES.index(NS_LINES.get(line, 'unmapped_fixed_frame'))
                if line in (375, 403, 405, 419):
                    c_failure = True
                if line == 403 and type(frame.f_locals.get('capability')) is int and 0 <= frame.f_locals['capability'] <= 63:
                    values[9] = frame.f_locals['capability']
                if line in (423, 424):
                    field = frame.f_locals.get('field')
                    values[8] = {'CapInh:': 1, 'CapPrm:': 2, 'CapEff:': 3, 'CapAmb:': 4, 'CapBnd:': 5}.get(field, 0)
            elif frame.f_code is self.family_code:
                values[4] = FAMILY_CHECKS.index(FAMILY_LINES.get(line, 'none'))
                values[5] = {'': 1, '-wal': 2, '-shm': 3}.get(frame.f_locals.get('suffix'), 0)
            elif frame.f_code is self.fd_bind_code:
                local = frame.f_locals
                actual, family, before = local.get('actual'), local.get('family'), local.get('before')
                def metadata(value):
                    return type(value) is tuple and len(value) == 5 and all(type(x) is int and 0 <= x < 2**64 for x in value)
                if (type(actual) is list and len(actual) <= 64 and all(metadata(x) for x in actual)
                        and type(family) is dict and set(family) == {'', '-wal', '-shm'} and all(metadata(x) for x in family.values())
                        and type(before) is dict and len(before) <= 64 and all(metadata(x) for x in before.values())):
                    expected = tuple(family.values())
                    values[12:18] = [len(actual), actual.count(family['']), actual.count(family['-wal']),
                        actual.count(family['-shm']), sum(x not in expected for x in actual),
                        int(any(x in expected for x in before.values()))]
            elif frame.f_code in self.mount_codes and line == 371:
                c_failure = True
            tb = tb.tb_next
        if c_failure and type(error) is D.ProbeStop:
            number = ctypes.get_errno()
            if type(number) is int and 0 < number <= 4095:
                values[7] = number
        values[10] = int(namespace_line is not None)
        values[11] = 1
        self.shared[:WORDS.size] = WORDS.pack(*values)

    def wrap(self, phase, original):
        def invoke(*args, **kwargs):
            self.entered(phase)
            try:
                result = original(*args, **kwargs)
            except BaseException as error:
                self.failed(phase, error)
                raise
            self.passed(phase)
            return result
        return invoke

    def result(self):
        values = self._get()
        if (values[0] < 0 or values[0] >= 1 << len(PHASES) or values[1] < 0 or values[1] >= 1 << len(PHASES)
                or not 0 <= values[2] < len(PHASES) or not 0 <= values[3] < len(STAGES)
                or not 0 <= values[4] < len(FAMILY_CHECKS) or not 0 <= values[5] < len(SUFFIXES)
                or not 0 <= values[6] < len(EXCEPTIONS) or not -1 <= values[7] <= 4095
                or not 0 <= values[8] < len(CAP_FIELDS) or not -1 <= values[9] <= 63
                or values[10] not in (0, 1) or values[11] not in (0, 1)
                or any(not -1 <= x <= 64 for x in values[12:17]) or values[17] not in (-1, 0, 1)
                or (any(x == -1 for x in values[12:18]) and values[12:18] != [-1] * 6)):
            raise ValueError('FIXTURE_PROVENANCE_SHAPE')
        fd_summary = None if values[12] == -1 else dict(new_regular_count=values[12],
            main_matches=values[13], wal_matches=values[14], shm_matches=values[15],
            extra_regular_count=values[16], before_family_match=bool(values[17]))
        return dict(fd_summary=fd_summary, entered=[p for i, p in enumerate(PHASES) if values[0] & (1 << i)],
            passed=[p for i, p in enumerate(PHASES) if values[1] & (1 << i)],
            failure_phase=PHASES[values[2]], failure_stage=STAGES[values[3]],
            family_check=FAMILY_CHECKS[values[4]], family_member=SUFFIXES[values[5]],
            exception=EXCEPTIONS[values[6]], errno=values[7] if values[7] >= 0 else None,
            capability_field=CAP_FIELDS[values[8]], capability_number=values[9] if values[9] >= 0 else None,
            fixed_namespace_frame=bool(values[10]), exception_observed=bool(values[11]))

    def close(self):
        self.shared.close()


class MarketProbeLinuxNamespaceProvenanceTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Linux namespace fixture not executed on this platform')
    def test_real_private_readonly_wal_namespace_with_closed_provenance(self):
        self.assertEqual(os.geteuid(), 0, 'Linux fixture requires the explicit sudo test step')
        provenance = Provenance()
        try:
            with tempfile.TemporaryDirectory(prefix='naver-probe-fixture-') as temp:
                directory = Path(temp).resolve()
                os.chmod(directory, 0o755)
                source = directory / 'logic_data.db'
                with independent_writer(directory):
                    for suffix in ('', '-wal', '-shm'):
                        os.chmod(str(source) + suffix, 0o644)
                    originals = {suffix: hashlib.sha256(Path(str(source) + suffix).read_bytes()).hexdigest()
                                 for suffix in ('', '-wal', '-shm')}
                    family = D._file_family(directory, source.name)
                    before_mount = os.stat('/proc/self/ns/mnt').st_ino
                    before_net = os.stat('/proc/self/ns/net').st_ino
                    plan = dict(source_directory=str(directory), database_name=source.name,
                                exporter_user='nobody', source_group=None)
                    with patch.object(D, '_load_exporters', provenance.wrap('source_load', D._load_exporters)), \
                         patch.object(D, '_namespace', provenance.wrap('namespace', D._namespace)), \
                         patch.object(D, '_file_family', provenance.wrap('file_family', D._file_family)), \
                         patch.object(D, '_bind_sqlite_fds', provenance.wrap('fd_bind', D._bind_sqlite_fds)), \
                         patch.object(D, '_fd_snapshot', provenance.wrap('fd_snapshot', D._fd_snapshot)), \
                         patch.object(D.sqlite3, 'connect', provenance.wrap('connect', D.sqlite3.connect)), \
                         patch.object(D, '_collect_probe', provenance.wrap('collect', D._collect_probe)):
                        result = D._run_child(plan, SOURCES, family, BACKEND)
                    # Parent isolation and source-byte assertions still run on failed child results.
                    self.assertEqual(os.stat('/proc/self/ns/mnt').st_ino, before_mount)
                    self.assertEqual(os.stat('/proc/self/ns/net').st_ino, before_net)
                    for suffix, digest in originals.items():
                        self.assertEqual(hashlib.sha256(Path(str(source) + suffix).read_bytes()).hexdigest(), digest)
                    closed = {'probe': result, 'fixture_provenance': provenance.result()}
                    self.assertEqual(result['status'], 'original_collect_passed', json.dumps(closed, sort_keys=True))
                    self.assertTrue(result['database_opened'])
                    self.assertTrue(result['readonly_namespace_verified'])
                    self.assertTrue(result['read_transaction_fds_bound'])
                    self.assertTrue(result['path_identity_unchanged'])
                    self.assertEqual(result['collect_calls'], 1)
        finally:
            provenance.close()


if __name__ == '__main__':
    unittest.main()
