"""Disposable hosted-VM qualification only. Never invokes production observe()."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import types
import uuid

CORE_SHA256 = 'b03caa1cb0b886e3098b1446dd70c953f05da90abbc449a901ffd74b7449f8e1'
CONFIRM = 'github-hosted-empty-operation-invocation-v1'
CHECKS = ('hosted_root_gate', 'fixed_core_pin', 'unit_paths_initially_absent',
    'exact_created_files', 'two_single_start_attempts', 'pid1_metadata_without_message',
    'success_terminal', 'failure_terminal', 'parser_closed_result', 'owned_cleanup')
UNIT_ROOT = Path('/run/systemd/system')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC'}


def _hash(body): return hashlib.sha256(body).hexdigest()


def _identity(path):
    st = path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_gid != 0
            or stat.S_IMODE(st.st_mode) != 0o644 or st.st_nlink != 1):
        raise ValueError('fixture_identity')
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _command(argv, *, accept=(0,)):
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, env=ENV, close_fds=True, start_new_session=True)
    try:
        code = process.wait(timeout=10)
        if code not in accept: raise ValueError('fixture_command')
        return code
    finally:
        if process.poll() is None:
            process.kill()
            try: process.wait(timeout=1)
            except subprocess.TimeoutExpired: pass


def _create(path, body):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    owned = os.fstat(fd)
    try:
        os.fchmod(fd, 0o644)
        os.fchown(fd, 0, 0)
        view = memoryview(body)
        while view:
            size = os.write(fd, view)
            if size <= 0: raise ValueError('fixture_write')
            view = view[size:]
        os.fsync(fd)
        info = os.fstat(fd)
        identity = _identity(path)
        if (identity[0], identity[1]) != (info.st_dev, info.st_ino): raise ValueError('fixture_race')
        return identity
    except BaseException:
        current = path.lstat()
        if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
            path.unlink()
        raise
    finally:
        os.close(fd)


def _gate():
    if (sys.argv[1:] != ['--confirm', CONFIRM] or not sys.platform.startswith('linux')
            or os.geteuid() != 0 or os.getegid() != 0
            or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('RUNNER_OS') != 'Linux'
            or Path('/proc/1/comm').read_text().strip() != 'systemd'):
        raise ValueError('fixture_gate')
    for path in (Path('/run'), Path('/run/systemd'), UNIT_ROOT):
        st = path.lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_gid != 0
                or st.st_mode & 0o022 or path.resolve() != path):
            raise ValueError('fixture_directory')


def run():
    checks = dict.fromkeys(CHECKS, False)
    stage, created, module, prior = 'hosted_root_gate', {}, None, None
    result = dict(version=1, status='failed', stage=stage, checks=checks,
        core_sha256=CORE_SHA256, operating_observed=False, database_opened=False,
        message_requested=False, fixture_units_started=0)
    try:
        _gate(); checks[stage] = True
        stage = 'fixed_core_pin'
        body = (Path(__file__).resolve().parent / 'core.py').read_bytes()
        if CORE_SHA256 is None or _hash(body) != CORE_SHA256: raise ValueError('fixture_pin')
        module = types.ModuleType('fixed_invocation_fixture_core')
        exec(compile(body, '<fixed-invocation-core>', 'exec'), module.__dict__)
        checks[stage] = True
        # These units and this time range are fixture-only substitutions in RAM.
        # Their names cannot reach production observe(), which is never called.
        prefix = 'naver-invocation-ro-fixture-' + uuid.uuid4().hex
        units = {'coordinator': prefix + '-success.service', 'reader': prefix + '-failure.service'}
        stage = 'unit_paths_initially_absent'
        for unit in units.values():
            for parent in (Path('/etc/systemd/system'), Path('/run/systemd/system.control'), UNIT_ROOT):
                p = parent / unit
                if p.exists() or p.is_symlink(): raise ValueError('fixture_present')
            data = module._capture(['/usr/bin/systemctl', 'show', unit, '--property=LoadState'])
            if data != b'LoadState=not-found\n': raise ValueError('fixture_loaded')
        checks[stage] = True
        stage = 'exact_created_files'
        for role, unit in units.items():
            executable = '/usr/bin/true' if role == 'coordinator' else '/usr/bin/false'
            body = ('[Unit]\nDescription=Isolated invocation metadata fixture\n'
                '[Service]\nType=oneshot\nExecStart=' + executable + '\n'
                'User=nobody\nGroup=nogroup\nNoNewPrivileges=yes\nProtectSystem=strict\n'
                'PrivateTmp=yes\nStandardOutput=null\nStandardError=null\n').encode()
            path = UNIT_ROOT / unit
            identity = _create(path, body)
            created[path] = (identity, body)
        checks[stage] = all(_identity(p) == meta[0] and p.read_bytes() == meta[1]
                            for p, meta in created.items())
        if not checks[stage]: raise ValueError('fixture_identity')
        _command(['/usr/bin/systemctl', 'daemon-reload'])
        start = time.time_ns() // 1000
        stage = 'two_single_start_attempts'
        for role, unit in units.items():
            code = _command(['/usr/bin/systemctl', 'start', unit], accept=(0, 1))
            result['fixture_units_started'] += 1
            if code != (0 if role == 'coordinator' else 1): raise ValueError('fixture_exit')
        checks[stage] = result['fixture_units_started'] == 2
        end = time.time_ns() // 1000
        stage = 'pid1_metadata_without_message'
        prior = module.UNITS, module.START_US, module.END_US
        module.UNITS, module.START_US, module.END_US = units, start, end
        argv = module._argv()
        def stamp(micros):
            return datetime.datetime.fromtimestamp(micros / 1000000, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f UTC')
        argv = [('--since=' + stamp(start)) if arg.startswith('--since=') else
                ('--until=' + stamp(end)) if arg.startswith('--until=') else arg for arg in argv]
        fields = next(arg.split('=', 1)[1] for arg in argv if arg.startswith('--output-fields='))
        if 'MESSAGE' in fields.split(',') or 'COMMAND' in fields.split(','):
            raise ValueError('fixture_payload')
        observed = module.parse(module._capture(argv))
        checks[stage] = True
        stage = 'success_terminal'
        checks[stage] = observed['roles']['coordinator']['state'] == 'unit_success'
        if not checks[stage]: raise ValueError('fixture_success')
        stage = 'failure_terminal'
        failure = observed['roles']['reader']
        checks[stage] = (failure['state'] == 'unit_failure' and failure['unit_result'] == 'exit-code'
                         and failure['exit_kind'] == 'exited' and failure['exit_status'] == 1)
        if not checks[stage]: raise ValueError('fixture_failure')
        stage = 'parser_closed_result'
        encoded = module.closed_json(observed)
        checks[stage] = all(value not in encoded for value in units.values()) and all(observed[k] is False for k in module.FLAGS)
        if not checks[stage]: raise ValueError('fixture_output')
    except Exception:
        result['stage'] = stage
    finally:
        if prior is not None: module.UNITS, module.START_US, module.END_US = prior
        cleanup = True
        for path, (identity, body) in reversed(list(created.items())):
            try:
                if _identity(path) != identity or path.read_bytes() != body: raise ValueError('fixture_changed')
                _command(['/usr/bin/systemctl', 'stop', path.name])
                _command(['/usr/bin/systemctl', 'reset-failed', path.name], accept=(0, 1))
                if _identity(path) != identity or path.read_bytes() != body: raise ValueError('fixture_changed')
                path.unlink()
            except Exception:
                cleanup = False
        if created:
            try: _command(['/usr/bin/systemctl', 'daemon-reload'])
            except Exception: cleanup = False
        checks['owned_cleanup'] = bool(created) and cleanup and all(not p.exists() and not p.is_symlink() for p in created)
    if all(checks.values()): result.update(status='passed', stage='complete')
    elif not checks['owned_cleanup'] and all(checks[k] for k in CHECKS if k != 'owned_cleanup'):
        result['stage'] = 'owned_cleanup'
    elif result['stage'] == 'hosted_root_gate' and checks['hosted_root_gate']:
        result['stage'] = stage
    return result


if __name__ == '__main__':
    value = run()
    print(json.dumps(value, sort_keys=True, separators=(',', ':')))
    raise SystemExit(0 if value['status'] == 'passed' else 1)
