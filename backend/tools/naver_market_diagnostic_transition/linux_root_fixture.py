"""One-use, destructive synthetic qualification on an empty GitHub-hosted VM.

NEVER an operating host entrypoint. Exact reviewed modules are installed beside
linux_root_fixture.py under backend/tools/naver_market_diagnostic_transition/.
Only baseline receipts/current Docker metadata are fixture seams. All path,
UID/GID, publication, controller, systemd and exporter operations below are real
on fixture-owned paths. Original source DB values are entirely synthetic.
No raw command/journal/exception or invocation identifier is emitted.
"""
import argparse
import contextlib
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import sys
import time
import types

CONFIRM = 'github-hosted-empty-vm-only-v1'
MODULES = {
    'transition': 'acd5636795506381c89ac0aa8657c7ea1b4f6a26985f50b0297fba62c7d5591a',
    'journal': '27e2ec8c7b332951151dcb19bd60ec527eb768d1b1711f40069b8dd1ac191333',
    'preflight': '0a48d024d352bb2d32cfa920ee530501001bb889d32219ff8b14dcca0984b7c3',
    'systemd_boundary': '3f96d25bacb7555cee39af4a6d8b73e4148a9587eb15411c728fd12eac839444',
    'publication': 'da60c15bca0dc48c9dda794ade7e87877f5fec13678a908a3f58657bb34be8a1',
    'host_port': 'f4ed31a5e40db1593358295d30119b95e5ce2d8b3bc3cc97680f94e724562500',
    'provisioning': '651927b4a93bc68f57dfac3645bd9a2c4fbdf4a0f0ec32beef94389e40a19ad0',
    'current_guard': '670f62086a89134f66117541bad5537a21c5c15cd2fcef5478b3792a99d62eb7',
    'entrypoint': 'b24302665afb5623b8c466f563b3c50c236dfbbabcebc6a3be3519d77df7c162',
}
SOURCES = {
    'helper': ('backend/tools/naver_saved_exports.py', '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737'),
    'product': ('backend/naver_product_export.py', '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59'),
    'old_market': ('backend/naver_market_export.py', 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'),
    'market': ('backend/tools/naver_market_diagnostic_transition/naver_market_export_diagnostic.py', '9bb25d4acda4edca44aa71c238a6bf53be7dab5e093bc4f0c69d45c0d0891851'),
}
EMPTY_ROOTS = ('/root/logic-analysis-deploy', '/opt/metainc', '/var/lib/metainc', '/srv/metainc')
OLD_NAMES = ('naver-market-export.service', 'naver-market-export-reader.service', 'naver-market-export.timer')
FIXTURE_IDS = (('1'*32, '2'*32), ('3'*32, '4'*32), ('5'*32, '6'*32))
CHECKS = ('empty_host_gate', 'exact_public_pins', 'real_uid_gid', 'unitpath_control_precedence',
    'persistent_natural_activation', 'original_failure_bound', 'compiled_unit_sandbox',
    'apply_source_limit_cell', 'owned_runtime_masks', 'paired_rollback',
    'partial_unit_publication_rollback', 'cached_active_removal_refused',
    'original_files_and_db_preserved', 'private_ids_not_emitted')
FAILURES = frozenset(('SYSTEMD_UNIT_PATH', 'SYSTEMD_COMMAND_FAILED', 'SYSTEMD_SNAPSHOT',
    'SYSTEMD_COMMAND_AMBIGUOUS', 'SYSTEMD_COMMAND_LIMIT', 'SYSTEMD_COMMAND_UNAVAILABLE',
    'ORIGINAL_TIMER', 'ORIGINAL_UNIT', 'ORIGINAL_NOT_MASKED_IDLE', 'DIAGNOSTIC_NOT_IDLE',
    'DIAGNOSTIC_CONTEXT', 'DIAGNOSTIC_CONTEXT_CHANGED', 'CURRENT_FAILURE_UNIT',
    'CURRENT_FAILURE_CHANGED', 'CURRENT_FAILURE_RESULT', 'JOURNAL_INVOCATION',
    'JOURNAL_RESULT', 'JOURNAL_MULTIPLE_RESULTS', 'PROVISION_DIRECTORY',
    'PROVISION_CHANGED', 'HOST_BASELINE_CHANGED', 'HOST_OUTPUT', 'HOST_PUBLIC_STATE',
    'HOST_RESTORE_UNVERIFIED', 'ORIGINAL_TIMER_NOT_RESTORED'))


class Refused(Exception):
    pass


def require(value):
    if value is not True:
        raise Refused()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(body):
    return hashlib.sha256(body).hexdigest()


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
    body = path.read_bytes()
    require(sha(body) == pin)
    return body


def load_public():
    # Verify every byte before any module execution, then compile the same RAM buffers.
    installed = Path(__file__).resolve()
    require(installed.name == 'linux_root_fixture.py')
    require(installed.parent.name == 'naver_market_diagnostic_transition')
    repository = installed.parents[3]
    require(installed.parent == repository / 'backend/tools/naver_market_diagnostic_transition')
    bodies = {n: public_bytes(installed.parent / (n + '.py'), h) for n, h in MODULES.items()}
    sources = {k: public_bytes(repository / n, h) for k, (n, h) in SOURCES.items()}
    modules = {}
    for name, body in bodies.items():
        require(name not in sys.modules)
        m = types.ModuleType(name)
        m.__file__ = '<pinned-fixture-' + name + '>'
        sys.modules[name] = m
        exec(compile(body, m.__file__, 'exec'), m.__dict__)
        modules[name] = m
    helper = types.ModuleType('fixture_exact_helper')
    exec(compile(sources['helper'], '<exact-fixture-helper>', 'exec'), helper.__dict__)
    return modules, sources, helper


def mkdir(path, *, uid=0, gid=0, mode=0o755):
    path = Path(path)
    path.mkdir(mode=0o700)
    os.chown(path, uid, gid)
    os.chmod(path, mode)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)
    return path


def write_new(path, body, *, mode=0o644, gid=0):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.fchown(fd, 0, gid); os.fchmod(fd, mode)
        view = memoryview(body)
        while view:
            written = os.write(fd, view)
            require(written > 0); view = view[written:]
        os.fsync(fd)
    finally: os.close(fd)


def wait_for(predicate, *, timeout=75):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(0.5)
    raise Refused()


@contextlib.contextmanager
def replaced(obj, name, value):
    old = getattr(obj, name); setattr(obj, name, value)
    try: yield
    finally: setattr(obj, name, old)


def run(confirm):
    stage = 'empty_host_gate'
    done = {k: False for k in CHECKS}
    try:
        gate(confirm); done[stage] = True
        stage = 'exact_public_pins'
        m, sources, helper = load_public(); done[stage] = True
        T, S, B, G, E, P = (m[n] for n in ('transition', 'systemd_boundary', 'preflight',
                                         'current_guard', 'entrypoint', 'publication'))
        def command(args, *, accept=(0,), timeout=15):
            code, raw = S.bounded(args, limit=32768, timeout=timeout)
            require(code in accept)
            return raw
        # Even a stale cached manager unit is refused before any fixture writes.
        for name in OLD_NAMES:
            raw = command(['/usr/bin/systemctl', 'show', name, '--property=LoadState'])
            require(raw == b'LoadState=not-found\n')
        stage = 'real_uid_gid'
        uid = pwd.getpwnam('nobody').pw_uid
        require(type(uid) is int and uid > 0)
        try: grp.getgrgid(10001)
        except KeyError:
            command(['/usr/sbin/groupadd', '--gid', '10001', 'naver-fixture-readers'])
        require(grp.getgrgid(10001).gr_gid == 10001)
        # Only wholly absent fixture roots are created; nothing pre-existing is removed.
        for root in EMPTY_ROOTS: mkdir(root)
        mkdir('/root/logic-analysis-deploy/data')
        for path in ('/opt/metainc/naver-saved-exports', '/var/lib/metainc/naver-product-source',
                     '/var/lib/metainc/naver-market-source'):
            mkdir(path, uid=uid if '/var/lib/' in path else 0,
                  gid=10001 if '/var/lib/' in path else 0,
                  mode=0o750 if '/var/lib/' in path else 0o755)
        profile = helper.build_plan(**T.PROFILE)
        original = helper.artifacts(profile, {'naver_product_export.py': sources['product'],
            'naver_market_export.py': sources['old_market']},
            {'naver_product_export.py': T.PRODUCT_PIN, 'naver_market_export.py': T.OLD_MARKET_PIN})
        old_root = mkdir(helper.INSTALL / profile['ops_commit'])
        python, _ = helper._python_snapshot(profile)
        write_new(old_root / 'python-export', python, mode=0o755, gid=10001)
        original_files = {old_root / n: original[n] for n in
            ('naver_product_export.py', 'naver_market_export.py', 'naver_market_coordinate.py')}
        original_files.update({Path(T.UNIT_ROOT) / n: original[n] for n in OLD_NAMES})
        for path, body in original_files.items(): write_new(path, body)
        sentinel = Path('/var/lib/metainc/naver-market-source/original.fixture')
        write_new(sentinel, b'fixture original output remains unchanged\n')
        # Only this newly created synthetic DB is opened; production paths were absent.
        import sqlite3
        database = Path(T.PROFILE['source_directory']) / T.PROFILE['database_name']
        conn = sqlite3.connect(database)
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''CREATE TABLE clients(id,naver_store_url,main_keywords,role,vertical);
CREATE TABLE client_keyword_product(client_id,keyword,product_url);
CREATE TABLE client_keyword_mute(client_id,keyword);
CREATE TABLE collector_observations(observation_id,keyword,collected_date,status,kind,reason,
 received_at,payload_hash,products_json,meta_json);
CREATE TABLE collected_serp(keyword,collected_date,total,products_json,meta_json);''')
            conn.execute('INSERT INTO clients VALUES(?,?,?,?,?)',
                ('fixture', 'https://smartstore.naver.com/fixture', 'x'*8193, 'advertiser', 'store'))
            conn.commit()
        finally: conn.close()
        os.chmod(database, 0o644)
        initial_database = sha(database.read_bytes())
        original_hashes = {str(p): sha(p.read_bytes()) for p in original_files}
        original_hashes[str(old_root / 'python-export')] = sha(python)
        original_hashes[str(sentinel)] = sha(sentinel.read_bytes())
        done[stage] = True
        # Baseline receipt and current container proofs are explicit fixture seams.
        # All installed bytes/main DB preservation are nevertheless checked each call.
        base_digest = sha(canonical(original_hashes))
        proofs = {k: base_digest for k in T.PROOF_KEYS}
        def baseline(_sources):
            require(all(sha(Path(p).read_bytes()) == h for p, h in original_hashes.items()))
            require(sha(database.read_bytes()) == initial_database)
            return dict(proofs), types.SimpleNamespace(runtime_uid=uid)
        def deployment(_self):
            baseline(None)
            return dict(prepared_sha256=base_digest, started_sha256=base_digest,
                        containers_sha256=sha(b'explicit synthetic Docker proof; no Docker request'))
        plan, files = T.compile_plan(apply_id=FIXTURE_IDS[0][0], rollback_id=FIXTURE_IDS[0][1],
                                    sources=sources, previous=proofs)
        systemd = S.Systemd(plan, files, sources=sources)
        stage = 'unitpath_control_precedence'
        require(systemd.mask_search_path() == S.MASK_ROOT); done[stage] = True
        stage = 'persistent_natural_activation'
        timers = Path('/var/lib/systemd/timers')
        if not timers.exists(): mkdir(timers)
        stamp = timers / 'stamp-naver-market-export.timer'
        write_new(stamp, b'', mode=0o644)
        os.utime(stamp, (946684800, 946684800))  # Synthetic missed event; never alter system clock.
        systemd.reload()
        command(['/usr/bin/systemctl', 'enable', T.OLD_TIMER])
        systemd.timer_restore()
        wait_for(lambda: systemd.show(T.OLD_READER)['InvocationID'] not in ('', '0'*32)
            and S.idle(systemd.show(T.OLD_COORDINATOR)) and S.idle(systemd.show(T.OLD_READER)))
        require(systemd.show(T.OLD_TIMER)['ActiveState'] == 'active')
        done[stage] = True
        stage = 'original_failure_bound'
        with replaced(B, 'collect', baseline), replaced(G.CurrentGuard, '_deployment', deployment):
            proof = G.CurrentGuard(proofs).capture()
            require(type(proof['invocation_id']) is str); done[stage] = True
            def action(kind, pair):
                return E.run(dict(version=1, action=kind, apply_id=pair[0], rollback_id=pair[1]),
                             sources=sources, baseline_sources={})
            stage = 'apply_source_limit_cell'
            applied = action('apply', FIXTURE_IDS[0])
            require(applied['result']['observation'] == dict(status='source_limit', limit_issue='cell', exit_status=1))
            require(applied['result']['product_export_verified'] is False)
            done[stage] = True
            stage = 'compiled_unit_sandbox'
            for key in ('coordinator', 'reader'):
                unit = plan[key]
                require(Path(T.UNIT_ROOT, unit).read_bytes() == files[T.UNIT_ROOT + '/' + unit])
                raw = command(['/usr/bin/systemctl', 'show', unit, '--property=NoNewPrivileges',
                    '--property=PrivateNetwork', '--property=PrivateTmp', '--property=ProtectSystem',
                    '--property=ProtectHome', '--property=User', '--property=Group'])
                data = dict(line.split('=', 1) for line in raw.decode('ascii').splitlines())
                require(data == dict(NoNewPrivileges='yes', PrivateNetwork='yes', PrivateTmp='yes',
                    ProtectSystem='strict', ProtectHome='tmpfs',
                    User='root' if key == 'coordinator' else 'nobody', Group='10001'))
            # Actual original coordinator refuses non-RO main/non-RW directory;
            # actual reader ExecStartPre refuses a source directory that is not kernel RO.
            output = Path(plan['output_root']).lstat()
            require((output.st_uid, output.st_gid, stat.S_IMODE(output.st_mode)) == (uid, 10001, 0o750))
            require(not Path(plan['output_root'], 'bundle.json').exists())
            done[stage] = True
            stage = 'owned_runtime_masks'
            systemd.masked_idle()
            require(all(Path(S.MASK_ROOT, u).is_symlink() and os.readlink(Path(S.MASK_ROOT, u)) == '/dev/null'
                        for u in (T.OLD_COORDINATOR, T.OLD_READER)))
            done[stage] = True
            stage = 'paired_rollback'
            restored = action('rollback', FIXTURE_IDS[0])
            require(restored['result']['restored'] is True)
            require(all(not Path(p).exists() for p in files))
            done[stage] = True
            # New synthetic original execution establishes a fresh real failure
            # for a DIFFERENT operation's interruption qualification only.
            command(['/usr/bin/systemctl', 'start', T.OLD_COORDINATOR], accept=(0,1), timeout=75)
            stage = 'partial_unit_publication_rollback'
            partial_plan, partial_files = T.compile_plan(apply_id=FIXTURE_IDS[1][0], rollback_id=FIXTURE_IDS[1][1],
                                                       sources=sources, previous=proofs)
            link = os.link
            interrupted = [False]
            def interrupt_link(src, dst, **kwargs):
                link(src, dst, **kwargs)
                if str(dst) in partial_files and str(dst).startswith(T.UNIT_ROOT + '/') and not interrupted[0]:
                    interrupted[0] = True
                    raise InterruptedError()
            with replaced(P.os, 'link', interrupt_link):
                try: action('apply', FIXTURE_IDS[1])
                except InterruptedError: pass
                else: raise Refused()
            require(interrupted[0])
            require(action('rollback', FIXTURE_IDS[1])['result']['restored'] is True)
            require(all(not Path(p).exists() for p in partial_files))
            done[stage] = True
            stage = 'private_ids_not_emitted'
            body = canonical(applied)
            require(b'invocation' not in body and b'reader' not in body and proof['invocation_id'].encode() not in body)
            done[stage] = True
        stage = 'cached_active_removal_refused'
        active_plan, active_files = T.compile_plan(apply_id=FIXTURE_IDS[2][0], rollback_id=FIXTURE_IDS[2][1],
                                                 sources=sources, previous=proofs)
        active = S.Systemd(active_plan, active_files, sources=sources)
        target = Path(T.UNIT_ROOT, active_plan['coordinator'])
        # Intentionally different fixture-only unit: never claim compiled reader
        # qualification from this cached-manager-state adversarial check.
        write_new(target, b'[Unit]\nDescription=Disposable cached-state fixture\n[Service]\nType=simple\nExecStart=/usr/bin/sleep 30\n')
        active.reload()
        command(['/usr/bin/systemctl', 'start', active_plan['coordinator']])
        try:
            require(active.show(active_plan['coordinator'])['ActiveState'] == 'active')
            target.unlink(); active.reload()
            try: active.cleanup_idle()
            except T.Invalid as error: require(error.args == ('DIAGNOSTIC_NOT_IDLE',))
            else: raise Refused()
        finally:
            # The fixture owns this sleep unit; production cleanup never stops a running unit.
            command(['/usr/bin/systemctl', 'stop', active_plan['coordinator']])
            if target.exists(): target.unlink()
            active.reload()
        done[stage] = True
        stage = 'original_files_and_db_preserved'
        baseline(None); done[stage] = True
        require(all(done.values()))
        return dict(schema='diagnostic-empty-linux-vm-qualification-v1', status='passed', checks=done,
            operating_host_access=False, production_receipt_verified=False,
            current_docker_verified=False, operating_SOURCE_LIMIT_cause_verified=False)
    except BaseException as error:
        # All input/output/body and exception strings remain private. Stage is
        # assigned only from CHECKS; a failed run is never replayed blindly.
        code = error.args[0] if len(error.args) == 1 and type(error.args[0]) is str else None
        return dict(schema='diagnostic-empty-linux-vm-qualification-v1', status='failed',
                    failed_stage=stage, failure_code=code if code in FAILURES else 'fixture_unavailable',
                    checks=done, operating_host_access=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm', required=True, choices=[CONFIRM])
    args = parser.parse_args()
    result = run(args.confirm)
    sys.stdout.buffer.write(canonical(result) + b'\n')
    raise SystemExit(0 if result['status'] == 'passed' else 1)
