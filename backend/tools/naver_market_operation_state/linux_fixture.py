"""One GitHub-hosted disposable VM fixture; NEVER a production observation.

Only this fixture creates/removes temporary FS objects and two disposable units.
It never calls observe(), touches the fixed failed pair, or starts any unit.
"""
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

CONFIRM = 'github-hosted-empty-operation-state-v1'
CORE_SHA256 = '2b3c8bdc78bc65f97045951bffb6df3a0c103e0280a8ece3f429518786f36895'
CHECK_NAMES = (
    'hosted_linux_root', 'source_pin', 'opath_kernel', 'root_anchor_nofollow',
    'absent_metadata', 'regular_hardlink_two', 'mask_target_exact', 'wrong_mask_rejected',
    'ancestor_symlink_rejected', 'ancestor_replacement_detected', 'leaf_replacement_detected',
    'unit_absent_schema', 'unit_service_ten', 'unit_timer_nine', 'cleanup_verified',
)
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
FIXTURE_UNITS = ('naver-operation-state-fixture.service', 'naver-operation-state-fixture.timer')
UNIT_ROOT = Path('/run/systemd/system')
STAGES = ('host', 'pin', 'filesystem', 'systemd', 'cleanup', 'complete')

def _require(value):
    if not value:
        raise ValueError('FIXTURE_REFUSED')

def _load_core():
    path = Path(__file__).resolve().with_name('core.py')
    if not path.exists():
        path = path.with_name('operation_state_readonly.py')
    raw = path.read_bytes()
    _require(type(CORE_SHA256) is str and len(raw) <= 32768
             and hashlib.sha256(raw).hexdigest() == CORE_SHA256)
    # Execute the exact verified bytes once; no second source read.
    module = __import__('types').ModuleType('readonly_fixture_core')
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module

def _reload():
    result = subprocess.run(['/usr/bin/systemctl', 'daemon-reload'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=ENV, close_fds=True, timeout=10)
    _require(result.returncode == 0)

def _metadata(M, path, kind='regular', mode=0o644):
    with patch.object(M, 'FILES', {'code_market': (str(path), kind, mode, 'root')}):
        return M._metadata_pair('code_market', None, time.monotonic()+4)

def _files(M, checks):
    with tempfile.TemporaryDirectory(prefix='naver-readonly-fixture-', dir='/run') as directory:
        root = Path(directory)
        _require(root.lstat().st_uid == 0 and stat.S_IMODE(root.lstat().st_mode) == 0o700)
        fd = os.open(root, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            checks['opath_kernel'] = bool(fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_PATH)
        finally:
            os.close(fd)
        original_open = os.open
        opened = []
        def tracked(path, flags, *args, **kwargs):
            opened.append((path, flags))
            return original_open(path, flags, *args, **kwargs)
        with patch.object(M.os, 'open', side_effect=tracked):
            value = _metadata(M, root/'absent')
        checks['absent_metadata'] = value['presence'] == 'absent' and value['stable'] is True
        checks['root_anchor_nofollow'] = bool(opened) and all(
            flags & os.O_PATH and flags & os.O_DIRECTORY and flags & os.O_NOFOLLOW
            for _, flags in opened) and opened[0][0] == '/'
        leaf = root/'regular'
        leaf.write_bytes(b'public synthetic fixture')
        leaf.chmod(0o644)
        os.link(leaf, root/'private-link')
        value = _metadata(M, leaf)
        checks['regular_hardlink_two'] = value['issue'] == 'none' and value['links'] == 'two'
        mask = root/'mask'
        mask.symlink_to('/dev/null')
        value = _metadata(M, mask, 'symlink', 0o777)
        checks['mask_target_exact'] = value['issue'] == 'none' and value['kind'] == 'symlink'
        mask.unlink()
        mask.symlink_to('/dev/zero')
        checks['wrong_mask_rejected'] = _metadata(M, mask, 'symlink', 0o777)['issue'] == 'unsafe_type'
        (root/'real').mkdir(mode=0o700)
        (root/'ancestor-link').symlink_to(root/'real')
        checks['ancestor_symlink_rejected'] = _metadata(M, root/'ancestor-link'/'leaf')['issue'] == 'unsafe_parent'
        ancestor = root/'ancestor'
        ancestor.mkdir(mode=0o700)
        (ancestor/'leaf').write_bytes(b'x')
        (ancestor/'leaf').chmod(0o644)
        replaced = []
        def replace_ancestor(path, flags, *args, **kwargs):
            if path == 'ancestor' and 'dir_fd' in kwargs and not replaced:
                replaced.append(True)
                ancestor.rename(root/'saved-ancestor')
                ancestor.mkdir(mode=0o700)
                (ancestor/'leaf').write_bytes(b'x')
                (ancestor/'leaf').chmod(0o644)
            return original_open(path, flags, *args, **kwargs)
        with patch.object(M.os, 'open', side_effect=replace_ancestor):
            result = _metadata(M, ancestor/'leaf')
        checks['ancestor_replacement_detected'] = result['issue'] == 'changed'
        original_stat = os.stat
        seen = []
        def replace_leaf(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            if path == 'leaf' and 'dir_fd' in kwargs and not seen:
                seen.append(True)
                (ancestor/'leaf').rename(ancestor/'old-leaf')
                (ancestor/'leaf').write_bytes(b'x')
                (ancestor/'leaf').chmod(0o644)
            return info
        with patch.object(M.os, 'stat', side_effect=replace_leaf):
            result = _metadata(M, ancestor/'leaf')
        checks['leaf_replacement_detected'] = result['issue'] == 'changed'
        _require(all(checks[name] for name in CHECK_NAMES[2:11]))
    _require(not root.exists())

def _systemd(M, checks, absent_service):
    created = {}
    originals = {k: v for k, v in M.UNITS.items()}
    service, timer = FIXTURE_UNITS
    bodies = {
        service: b'[Unit]\nDescription=Disposable readonly schema fixture\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n',
        timer: ('[Unit]\nDescription=Disposable readonly timer fixture\n[Timer]\nOnActiveSec=1d\nUnit='+service+'\n').encode(),
    }
    # Exact new fixture names only; never replace any existing file or loaded unit.
    units = dict(originals)
    units['original_reader'], units['original_timer'] = service, timer
    cleanup_ok = False
    try:
        with patch.object(M, 'UNITS', units):
            for role in ('original_reader', 'original_timer'):
                code, body = M._capture_show(role, time.monotonic()+4)
                if role == 'original_reader':
                    absent_service['exit_status'] = code if type(code) is int and 0 <= code <= 255 else None
                try:
                    value, _ = M._parse_show(body, role)
                except M.Fault as error:
                    if role == 'original_reader':
                        absent_service['schema_issue'] = error.issue
                    raise
                if role == 'original_reader':
                    absent_service.update(schema_issue=value['issue'],
                        load_not_found=value['load'] == 'not-found',
                        invocation_format=value['invocation_format'])
                    checks['unit_absent_schema'] = value['issue'] == 'none' and value['load'] == 'not-found'
                _require(value['load'] == 'not-found' and value['fragment'] == 'empty')
        for name, body in bodies.items():
            path = UNIT_ROOT/name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            try:
                os.fchmod(fd, 0o644)
                info = os.fstat(fd)
                created[name] = (info.st_dev, info.st_ino)
                _require(os.write(fd, body) == len(body))
            finally:
                os.close(fd)
        _reload()
        with patch.object(M, 'UNITS', units):
            for role, check, count in (('original_reader', 'unit_service_ten', 10),
                                       ('original_timer', 'unit_timer_nine', 9)):
                public, private = M._parse_show(M._run_show(role, time.monotonic()+4), role)
                checks[check] = (len(private) == count and public['issue'] == 'none'
                    and public['load'] == 'loaded' and public['active'] == 'inactive'
                    and public['job'] == 'idle')
                _require(checks[check])
    finally:
        for name, identity in created.items():
            path = UNIT_ROOT/name
            info = path.lstat()
            _require(stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity)
            path.unlink()
        if created:
            _reload()
        cleanup_ok = all(not (UNIT_ROOT/name).exists() for name in FIXTURE_UNITS)
        checks['cleanup_verified'] = cleanup_ok
    _require(cleanup_ok)

def run():
    checks = {name: False for name in CHECK_NAMES}
    absent_service = dict(exit_status=None, schema_issue='unobserved',
                          load_not_found=None, invocation_format='unobserved')
    stage, status = 'host', 'failed'
    try:
        _require(sys.platform == 'linux' and os.geteuid() == 0 and hasattr(os, 'O_PATH'))
        _require(os.environ.get('GITHUB_ACTIONS') == 'true'
                 and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
                 and os.environ.get('RUNNER_OS') == 'Linux')
        _require(sys.argv == [sys.argv[0], '--confirm', CONFIRM])
        with open('/proc/1/comm', 'rb') as handle:
            _require(handle.read(16).strip() == b'systemd')
        _require(UNIT_ROOT.is_dir() and not UNIT_ROOT.is_symlink())
        checks['hosted_linux_root'] = True
        stage = 'pin'
        M = _load_core()
        checks['source_pin'] = True
        stage = 'filesystem'
        _files(M, checks)
        stage = 'systemd'
        _systemd(M, checks, absent_service)
        stage = 'cleanup'
        _require(all(checks.values()))
        stage, status = 'complete', 'passed'
    except BaseException:
        # No exception/command/path/raw value escapes the fixed stage projection.
        pass
    return dict(version=1, status=status, stage=stage, core_sha256=CORE_SHA256,
                checks=checks, absent_service=absent_service, operating_observe_called=False,
                production_units_touched=False, database_opened=False)

def main():
    result = run()
    print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False))
    return 0 if result['status'] == 'passed' else 1

if __name__ == '__main__':
    raise SystemExit(main())

