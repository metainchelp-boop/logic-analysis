"""Single empty-host provisioning classification; not an operating entrypoint.

All nine current runtime and four compiler source pins are checked before loading.
Only compiler/provisioning dependencies execute. No database, exporter, unit,
publication/controller, Docker, journal or group-account command runs.
Only the inherited three fixed systemctl show reads precede new filesystem effects.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import signal
import stat
import sys
import time
import types

CONFIRM = 'github-hosted-empty-vm-only-v1'
MODULES = {'transition': 'acd5636795506381c89ac0aa8657c7ea1b4f6a26985f50b0297fba62c7d5591a',
 'journal': '27e2ec8c7b332951151dcb19bd60ec527eb768d1b1711f40069b8dd1ac191333',
 'preflight': '0a48d024d352bb2d32cfa920ee530501001bb889d32219ff8b14dcca0984b7c3',
 'systemd_boundary': '3f96d25bacb7555cee39af4a6d8b73e4148a9587eb15411c728fd12eac839444',
 'publication': 'da60c15bca0dc48c9dda794ade7e87877f5fec13678a908a3f58657bb34be8a1',
 'host_port': 'f4ed31a5e40db1593358295d30119b95e5ce2d8b3bc3cc97680f94e724562500',
 'provisioning': '651927b4a93bc68f57dfac3645bd9a2c4fbdf4a0f0ec32beef94389e40a19ad0',
 'current_guard': '670f62086a89134f66117541bad5537a21c5c15cd2fcef5478b3792a99d62eb7',
 'entrypoint': 'b24302665afb5623b8c466f563b3c50c236dfbbabcebc6a3be3519d77df7c162'}
SOURCES = {'helper': ('backend/tools/naver_saved_exports.py',
            '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737'),
 'product': ('backend/naver_product_export.py',
             '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59'),
 'old_market': ('backend/naver_market_export.py',
                'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'),
 'market': ('backend/tools/naver_market_diagnostic_transition/naver_market_export_diagnostic.py',
            '9bb25d4acda4edca44aa71c238a6bf53be7dab5e093bc4f0c69d45c0d0891851')}
EMPTY_ROOTS = ('/root/logic-analysis-deploy', '/opt/metainc', '/var/lib/metainc', '/srv/metainc')
OLD_NAMES = ('naver-market-export.service', 'naver-market-export-reader.service', 'naver-market-export.timer')
LOAD_ORDER = ('transition', 'journal', 'systemd_boundary', 'publication', 'provisioning')
CHECKS = ('empty_host_gate', 'exact_public_pins', 'real_nobody_identity',
          'cached_units_absent', 'fixed_synthetic_plan', 'fresh_fixture_parents', 'prepare_receipt', 'real_uid_gid_output')
ROLES = frozenset(('root', 'etc', 'systemd_etc', 'unit_root', 'opt', 'install_parent',
    'var', 'var_lib', 'data_parent', 'run', 'systemd_run', 'control_root',
    'ledger_root', 'preparations_root', 'install_root', 'output_root', 'mask_root',
    'operation_root', 'ownership_root', 'code_root', 'operation_output',
    'unit_stage', 'mask_stage', 'code_stage', 'unregistered'))
FAILURES = frozenset(('PROVISION_DIRECTORY', 'PROVISION_PATH', 'PROVISION_CHANGED',
    'PROVISION_EXISTS', 'PROVISION_ROOT', 'PROVISION_RUNTIME', 'PROVISION_PLAN',
    'PROVISION_RECEIPT', 'PROVISION_RECEIPT_LIMIT', 'PROVISION_RECEIPT_LINK',
    'PROVISION_INVENTORY', 'PROVISION_GUARD', 'PROVISION_WRITE'))


class Refused(Exception):
    pass


def require(value):
    if value is not True:
        raise Refused()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def gate(confirm):
    require(confirm == CONFIRM)
    require(sys.platform == 'linux' and os.geteuid() == 0)
    require(os.environ.get('GITHUB_ACTIONS') == 'true')
    require(os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted')
    require(os.environ.get('RUNNER_OS') == 'Linux')
    require(Path('/proc/1/comm').read_bytes() == b'systemd\n')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines()
                   if '=' in line)
    require(release.get('ID', '').strip('"') == 'ubuntu')
    require(release.get('VERSION_ID', '').strip('"') == '24.04')
    for name in EMPTY_ROOTS:
        p = Path(name)
        require(not p.exists() and not p.is_symlink())
    for root in ('/etc/systemd/system', '/run/systemd/system', '/run/systemd/system.control',
                 '/usr/lib/systemd/system', '/lib/systemd/system'):
        for name in OLD_NAMES:
            for suffix in ('', '.d'):
                p = Path(root) / (name + suffix)
                require(not p.exists() and not p.is_symlink())
    for name in ('stamp-naver-market-export.timer',):
        p = Path('/var/lib/systemd/timers') / name
        require(not p.exists() and not p.is_symlink())


def public_bytes(path, pin):
    path = Path(path)
    require(path.resolve() == path)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 262144)
    value = path.read_bytes()
    require(sha(value) == pin)
    return value


def load_public():
    installed = Path(__file__).resolve()
    require(installed.name == 'provision_schema_fixture.py')
    repository = installed.parents[3]
    require(installed.parent == repository / 'backend/tools/naver_market_diagnostic_transition')
    bodies = {name: public_bytes(installed.parent / (name + '.py'), pin)
              for name, pin in MODULES.items()}
    sources = {role: public_bytes(repository / path, pin)
               for role, (path, pin) in SOURCES.items()}
    require(not (set(MODULES) & set(sys.modules)))
    # Verify all nine, but execute only the five compiler/provisioning dependencies.
    modules = {}
    for name in LOAD_ORDER:
        module = types.ModuleType(name)
        module.__file__ = '<pinned-provision-schema-' + name + '>'
        sys.modules[name] = module
        exec(compile(bodies[name], module.__file__, 'exec'), module.__dict__)
        modules[name] = module
    return modules, sources



def cached_units_absent(S):
    # Preserve the full fixture's pre-write cached-unit refusal with read-only calls.
    for name in OLD_NAMES:
        code, value = S.bounded(['/usr/bin/systemctl', 'show', name, '--property=LoadState'],
                                limit=32768, timeout=15)
        require(code == 0 and value == b'LoadState=not-found\n')


def fixed_roles(T, Q, plan):
    # Values are closed roles; paths/operation identifiers never leave this map.
    paths = {'/': 'root', '/etc': 'etc', '/etc/systemd': 'systemd_etc',
        T.UNIT_ROOT: 'unit_root', '/opt': 'opt', '/opt/metainc': 'install_parent',
        '/var': 'var', '/var/lib': 'var_lib', '/var/lib/metainc': 'data_parent',
        '/run': 'run', '/run/systemd': 'systemd_run', str(Q.CONTROL): 'control_root',
        str(Q.CONTROL / 'ledger'): 'ledger_root',
        str(Q.CONTROL / 'preparations'): 'preparations_root',
        T.INSTALL: 'install_root', T.OUTPUT: 'output_root', Q.MASK_ROOT: 'mask_root',
        str(Q.CONTROL / 'preparations' / plan['apply_id']): 'operation_root',
        str(Q.CONTROL / 'preparations' / plan['apply_id'] / 'ownership'): 'ownership_root',
        plan['code_root']: 'code_root', plan['output_root']: 'operation_output',
        str(Path(T.UNIT_ROOT) / ('.naver-diag-' + plan['apply_id'])): 'unit_stage',
        str(Path(Q.MASK_ROOT) / ('.naver-diag-' + plan['apply_id'])): 'mask_stage',
        str(Path(plan['code_root']) / ('.naver-diag-' + plan['apply_id'])): 'code_stage'}
    require(set(paths.values()) <= ROLES)
    return {Path(path): role for path, role in paths.items()}


def unavailable():
    return dict(role='unregistered', exact_directory_frame=False, stat_type='unavailable',
        mode_class='unavailable', owner_uid_matches=False, owner_gid_matches=False,
        group_writable=False, other_writable=False, exact_mode_required=False,
        requested_mode_matches=False)


def classify_directory(error, original, roles):
    result = unavailable()
    trace = error.__traceback__
    for _ in range(32):
        if trace is None:
            return result
        frame = trace.tb_frame
        if frame.f_code is original.__code__:
            values = frame.f_locals
            info = values.get('info')
            path, uid, gid, mode = (values.get(k) for k in ('path', 'uid', 'gid', 'mode'))
            if (type(info) is not os.stat_result or not isinstance(path, Path)
                    or type(uid) is not int or type(gid) is not int
                    or (mode is not None and type(mode) is not int)):
                return result
            role = roles.get(path, 'unregistered')
            require(role in ROLES)
            permissions = stat.S_IMODE(info.st_mode)
            kind = ('directory' if stat.S_ISDIR(info.st_mode) else
                    'regular' if stat.S_ISREG(info.st_mode) else
                    'symlink' if stat.S_ISLNK(info.st_mode) else 'other')
            mode_class = {0o700: 'private_0700', 0o750: 'reader_0750',
                          0o755: 'shared_0755'}.get(permissions, 'other_mode')
            return dict(role=role, exact_directory_frame=True, stat_type=kind,
                mode_class=mode_class, owner_uid_matches=info.st_uid == uid,
                owner_gid_matches=info.st_gid == gid,
                group_writable=bool(permissions & 0o020), other_writable=bool(permissions & 0o002),
                exact_mode_required=mode is not None,
                requested_mode_matches=mode is None or permissions == mode)
        trace = trace.tb_next
    return result


class DirectoryObserver:
    """Call the unchanged directory guard exactly once; re-raise its same error."""
    def __init__(self, original, roles, invalid):
        self.original, self.roles, self.invalid = original, roles, invalid
        self.first = None

    def __call__(self, path, uid, gid, mode=None):
        try:
            return self.original(path, uid, gid, mode)
        except self.invalid as error:
            if error.args == ('PROVISION_DIRECTORY',) and self.first is None:
                try:
                    self.first = classify_directory(error, self.original, self.roles)
                except Exception:
                    self.first = unavailable()
            raise


def new_parent(path):
    # Only two already-gated, absent roots needed by provisioning are created.
    path = Path(path)
    require(str(path) in ('/opt/metainc', '/var/lib/metainc'))
    path.mkdir(mode=0o700)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o755)
        os.fsync(fd)
    finally:
        os.close(fd)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def real_output_probe(output, uid, gid):
    """Write one synthetic marker as real nobody/10001, with no executable launch."""
    require(sys.platform == 'linux' and os.geteuid() == 0)
    require(type(uid) is int and uid > 0 and uid == pwd.getpwnam('nobody').pw_uid)
    require(type(gid) is int and gid == 10001)
    info = output.lstat()
    require(stat.S_ISDIR(info.st_mode) and (info.st_uid, info.st_gid) == (uid, gid)
            and stat.S_IMODE(info.st_mode) == 0o750)
    target = output / 'nobody-write.fixture'
    pid = os.fork()
    if pid == 0:
        try:
            os.setgroups([gid]); os.setgid(gid); os.setuid(uid); os.umask(0o027)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
            try:
                require(os.write(fd, b'x') == 1)
                os.fsync(fd)
            finally:
                os.close(fd)
            os._exit(0)
        except BaseException:
            os._exit(1)
    status = None
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            seen, value = os.waitpid(pid, os.WNOHANG)
            if seen == pid:
                status = value
                break
            time.sleep(0.02)
    finally:
        if status is None:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
    require(status is not None and os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0)
    value = target.lstat()
    require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and value.st_size == 1
            and (value.st_uid, value.st_gid) == (uid, gid) and stat.S_IMODE(value.st_mode) == 0o640)
    return True


def run(confirm):
    stage = 'empty_host_gate'
    done = {key: False for key in CHECKS}
    observer = None
    result = dict(schema='diagnostic-provision-schema-v1', status='failed', checks=done,
        first_directory_failure=None, operating_host_access=False, database_opened=False,
        exporter_executed=False, systemctl_mutations=False, units_published=False,
        product_export_verified=False, operating_SOURCE_LIMIT_cause_verified=False)
    try:
        gate(confirm); done[stage] = True
        stage = 'exact_public_pins'
        modules, sources = load_public(); done[stage] = True
        T, Q = modules['transition'], modules['provisioning']
        stage = 'cached_units_absent'
        cached_units_absent(modules['systemd_boundary']); done[stage] = True
        stage = 'real_nobody_identity'
        uid = pwd.getpwnam('nobody').pw_uid
        require(type(uid) is int and 0 < uid < 2**32)
        done[stage] = True
        stage = 'fixed_synthetic_plan'
        plan, files = T.compile_plan(apply_id='1' * 32, rollback_id='2' * 32,
            sources=sources, previous={key: 'a' * 64 for key in T.PROOF_KEYS})
        done[stage] = True
        stage = 'fresh_fixture_parents'
        new_parent('/opt/metainc'); new_parent('/var/lib/metainc'); done[stage] = True
        stage = 'prepare_receipt'
        original = Q._directory
        observer = DirectoryObserver(original, fixed_roles(T, Q, plan), T.Invalid)
        Q._directory = observer
        try:
            Q.prepare(plan, files, sources=sources, runtime_uid=uid,
                      guard_proof={'version': 1, 'synthetic_fixture_only': True})
        finally:
            Q._directory = original
        done[stage] = True
        stage = 'real_uid_gid_output'
        done[stage] = real_output_probe(Path(plan['output_root']), uid, 10001)
        require(all(done.values()))
        result['status'] = 'passed'
    except BaseException as error:
        code = error.args[0] if len(error.args) == 1 and type(error.args[0]) is str else None
        result.update(failed_stage=stage,
                      failure_code=code if code in FAILURES else 'fixture_unavailable')
    if observer is not None:
        result['first_directory_failure'] = observer.first
    return result


if __name__ == '__main__':
    expected = ['--confirm', CONFIRM]
    result = run(CONFIRM if sys.argv[1:] == expected else 'invalid-confirmation')
    sys.stdout.buffer.write(canonical(result) + b'\n')
    raise SystemExit(0 if result['status'] == 'passed' else 1)
