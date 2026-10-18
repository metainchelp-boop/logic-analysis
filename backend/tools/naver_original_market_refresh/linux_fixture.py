"""Disposable hosted-VM qualification of the original-market refresh only.

Never an operating host entrypoint. The four fixed roots and all six original
unit names must be absent before writes. Original exporter/coordinator bytes,
systemd, UID/GID, timer timestamp, helper.verify, and private ledger IO are real.
Historical receipt/Docker/install identities and restored history are explicit
fixture seams; timer calendar times are moved into the future only in this VM.
The source SQLite database contains fixture rows only. No diagnostic output is
read. This does not qualify a production receipt or the cause of SOURCE_LIMIT.
"""
import argparse
import contextlib
from datetime import datetime, timezone
import grp
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
SCHEMA = 'original-market-refresh-empty-linux-vm-v1'
CORE_PIN = '8b999336179d1fcec89bd7b8f066909ca6b106854843c843a3b96035d66c1a33'
MODULES = {
    'transition': '89ab4f61004846a90ec75a147b398d5f17eae016a268e375e7c44433143c3a92',
    'journal': '27e2ec8c7b332951151dcb19bd60ec527eb768d1b1711f40069b8dd1ac191333',
    'preflight': '0a48d024d352bb2d32cfa920ee530501001bb889d32219ff8b14dcca0984b7c3',
    'systemd_boundary': 'a0559bdca3bee319a8bc3d37425a6854185ec06245b69ec494a4513221fe72ac',
    'current_guard': '6a9377b6ed3d511e054c1234b0b830314331ddadad3b5887b79a8c36e611e5d8',
}
SOURCES = {
    'helper': ('backend/tools/naver_saved_exports.py', '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737'),
    'product': ('backend/naver_product_export.py', '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59'),
    'old_market': ('backend/naver_market_export.py', 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'),
    'market': ('backend/tools/naver_market_diagnostic_transition/diagnostic_market_export.py', '9bb25d4acda4edca44aa71c238a6bf53be7dab5e093bc4f0c69d45c0d0891851'),
    'exports_binding': ('backend/tools/naver_completion_exports.py', '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed'),
}
EMPTY_ROOTS = ('/root/logic-analysis-deploy', '/opt/metainc', '/var/lib/metainc', '/srv/metainc')
OLD_NAMES = tuple('naver-' + kind + '-export' + suffix for kind in ('product', 'market')
                  for suffix in ('.service', '-reader.service', '.timer'))
CHECKS = ('empty_host_gate', 'exact_public_pins', 'real_root_systemd',
    'timer_unix_output', 'timer_300s_refused', 'original_failure_preserved',
    'durable_intent_before_start', 'single_original_start', 'same_id_replay_refused',
    'interrupted_intent_replay_refused', 'original_helper_verified',
    'original_files_db_preserved')
FAILURES = frozenset(('fixture_unavailable', 'fixture_assertion', 'REFRESH_TIMER_NEXT',
    'REFRESH_TIMER_NEAR', 'REFRESH_REUSED', 'REFRESH_REFUSED', 'REFRESH_START_FAILED',
    'REFRESH_START_AMBIGUOUS', 'REFRESH_PLAN', 'REFRESH_PROOF', 'REFRESH_NOT_RESTORED',
    'REFRESH_CLEANUP', 'REFRESH_VERIFY', 'REFRESH_CLOCK', 'REFRESH_DEADLINE',
    'EXPORT_RUN_NOT_VERIFIED', 'EXPORT_BUNDLE_INVALID', 'EXPORT_BUNDLE_STALE',
    'EXPORT_FILE_POLICY', 'EXPORT_INSTALLED_CHANGED', 'EXPORT_DIRECTORY_POLICY',
    'CURRENT_FAILURE_UNIT', 'CURRENT_FAILURE_CHANGED', 'CURRENT_FAILURE_RESULT',
    'SYSTEMD_COMMAND_FAILED', 'SYSTEMD_COMMAND_AMBIGUOUS', 'SYSTEMD_COMMAND_LIMIT',
    'SYSTEMD_COMMAND_UNAVAILABLE', 'SYSTEMD_UNIT_PATH', 'SYSTEMD_SNAPSHOT',
    'ORIGINAL_TIMER', 'ORIGINAL_UNIT', 'JOURNAL_CHANGED', 'JOURNAL_FILE',
    'JOURNAL_DIRECTORY', 'JOURNAL_INVOCATION', 'JOURNAL_RESULT'))


class Refused(Exception):
    pass


def require(value):
    if value is not True:
        raise Refused('fixture_assertion')


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
    for kind in ('product', 'market'):
        p = Path('/var/lib/systemd/timers/stamp-naver-' + kind + '-export.timer')
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
    installed = Path(__file__).resolve()
    require(installed.name == 'linux_fixture.py')
    require(installed.parent.name == 'naver_original_market_refresh')
    repository = installed.parents[3]
    require(installed.parent == repository / 'backend/tools/naver_original_market_refresh')
    runtime = repository / 'backend/tools/naver_market_diagnostic_transition'
    bodies = {n: public_bytes(runtime / (n + '.py'), h) for n, h in MODULES.items()}
    raw_core = public_bytes(installed.parent / 'core.py', CORE_PIN)
    sources = {k: public_bytes(repository / n, h) for k, (n, h) in SOURCES.items()}
    modules = {}
    # All bytes are verified first; preserve dependency order when executing.
    for name, body in bodies.items():
        require(name not in sys.modules)
        m = types.ModuleType(name)
        m.__file__ = '<pinned-refresh-fixture-' + name + '>'
        sys.modules[name] = m
        exec(compile(body, m.__file__, 'exec'), m.__dict__)
        modules[name] = m
    core = types.ModuleType('fixture_original_market_refresh')
    exec(compile(raw_core, '<pinned-refresh-core>', 'exec'), core.__dict__)
    helper = types.ModuleType('fixture_exact_original_helper')
    exec(compile(sources['helper'], '<pinned-original-helper>', 'exec'), helper.__dict__)
    return modules, core, sources, helper


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


@contextlib.contextmanager
def replaced(obj, name, value):
    old = getattr(obj, name); setattr(obj, name, value)
    try: yield
    finally: setattr(obj, name, old)


def secure_fixture_opt():
    fd = os.open('/opt', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    changed = False
    try:
        before, current = os.fstat(fd), os.stat('/opt', follow_symlinks=False)
        require(stat.S_ISDIR(before.st_mode) and (before.st_uid, before.st_gid) == (0, 0))
        require((before.st_dev, before.st_ino) == (current.st_dev, current.st_ino))
        mode = stat.S_IMODE(before.st_mode)
        require(mode in (0o755, 0o777))
        if mode == 0o777:
            os.fchmod(fd, 0o755); changed = True; os.fsync(fd)
        checked = os.fstat(fd)
        require(stat.S_IMODE(checked.st_mode) == 0o755
                and (checked.st_dev, checked.st_ino, checked.st_uid, checked.st_gid)
                == (before.st_dev, before.st_ino, 0, 0))
        return (fd, before.st_dev, before.st_ino, mode)
    except BaseException:
        if changed: restore_fixture_opt((fd, before.st_dev, before.st_ino, mode))
        else: os.close(fd)
        raise


def restore_fixture_opt(saved):
    fd, dev, ino, mode = saved
    try:
        current, opened = os.stat('/opt', follow_symlinks=False), os.fstat(fd)
        require(all(stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino, info.st_uid, info.st_gid)
                    == (dev, ino, 0, 0) and stat.S_IMODE(info.st_mode) == 0o755
                    for info in (current, opened)))
        if mode == 0o777: os.fchmod(fd, mode); os.fsync(fd)
        require(stat.S_IMODE(os.fstat(fd).st_mode) == mode)
    finally: os.close(fd)


def timer_fixture(body, epoch):
    """Fixture-only schedule seam; leave original coordinator and reader intact."""
    lines = body.decode('ascii').splitlines()
    require(sum(line.startswith('OnCalendar=') for line in lines) == 1)
    require(lines.count('RandomizedDelaySec=60') == 1)
    when = datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    return ('\n'.join('OnCalendar=' + when if x.startswith('OnCalendar=') else
        'RandomizedDelaySec=0' if x == 'RandomizedDelaySec=60' else x for x in lines) + '\n').encode()


def seed_restored(ledger, plan, T):
    """Synthetic valid history only, not a rerun or claim about a live pair."""
    history = [dict(action='apply', state='intent', apply_id=plan['apply_id'],
                    rollback_id=plan['rollback_id'])]
    for step in T.STEPS:
        history.append(dict(action=step, state='intent'))
        done = dict(action=step, state='done')
        if step == 'observe':
            done['observation'] = dict(reader=plan['reader'], invocation_id='d'*32,
                status='diagnostic_unavailable', limit_issue=None, exit_status=0)
        history.append(done)
    history += [dict(action='apply', state='done'), dict(action='rollback', state='intent')]
    for step in T.CLEANUP:
        history.extend([dict(action=step, state='intent'), dict(action=step, state='done')])
    history.append(dict(action='rollback', state='done'))
    digest = T.sha(T.canonical(plan))
    with ledger.lock():
        for event in history: ledger.append(digest, event)
        require(T.validate_history(ledger.read(digest), plan) == 'restored')


def failure_code(error, modules):
    allowed_types = (Refused,)
    if modules:
        allowed_types += (modules['transition'].Invalid, modules['preflight'].Invalid)
    if (type(error) in allowed_types and len(error.args) == 1
            and type(error.args[0]) is str and error.args[0] in FAILURES):
        return error.args[0]
    return 'fixture_unavailable'


def run(confirm):
    stage = 'empty_host_gate'
    done = {key: False for key in CHECKS}
    modules, saved, cleanup_command = {}, None, None
    outcome = None
    try:
        gate(confirm); done[stage] = True
        saved = secure_fixture_opt()
        stage = 'exact_public_pins'
        modules, C, all_sources, helper = load_public(); done[stage] = True
        T, J, B, S, G = (modules[n] for n in
                        ('transition', 'journal', 'preflight', 'systemd_boundary', 'current_guard'))
        sources = {k: all_sources[k] for k in ('helper', 'product', 'old_market', 'market')}
        baseline_sources = dict(exports_binding=all_sources['exports_binding'],
            exports_helper=sources['helper'], product_exporter=sources['product'],
            market_exporter=sources['old_market'])
        real_bounded = S.bounded
        def command(args, *, accept=(0,), timeout=75):
            code, raw = real_bounded(args, limit=32768, timeout=timeout)
            require(code in accept)
            return raw
        # Refuse cached units before creating any unit or fixture source root.
        for name in OLD_NAMES:
            require(command(['/usr/bin/systemctl', 'show', name, '--property=LoadState'])
                    == b'LoadState=not-found\n')
        stage = 'real_root_systemd'
        uid = pwd.getpwnam('nobody').pw_uid
        require(type(uid) is int and uid > 0)
        try: grp.getgrgid(10001)
        except KeyError:
            command(['/usr/sbin/groupadd', '--gid', '10001', 'naver-fixture-readers'])
        require(grp.getgrgid(10001).gr_gid == 10001)
        for root in EMPTY_ROOTS: mkdir(root)
        mkdir('/root/logic-analysis-deploy/data')
        for path in ('/opt/metainc/naver-saved-exports', '/var/lib/metainc/naver-product-source',
                     '/var/lib/metainc/naver-market-source'):
            mkdir(path, uid=uid if '/var/lib/' in path else 0,
                  gid=10001 if '/var/lib/' in path else 0,
                  mode=0o750 if '/var/lib/' in path else 0o755)
        mkdir(C.CONTROL, mode=0o700); mkdir(C.LEDGER_ROOT, mode=0o700)
        prepared_folder = mkdir(C.CONTROL / 'fixture-prepared', mode=0o700)
        profile = helper.build_plan(**T.PROFILE)
        original = helper.artifacts(profile,
            {'naver_product_export.py': sources['product'], 'naver_market_export.py': sources['old_market']},
            {'naver_product_export.py': T.PRODUCT_PIN, 'naver_market_export.py': T.OLD_MARKET_PIN})
        old_root = mkdir(helper.INSTALL / profile['ops_commit'])
        python, _ = helper._python_snapshot(profile)
        original[helper.INTERPRETER] = python
        write_new(old_root / helper.INTERPRETER, python, mode=0o550, gid=10001)
        # Both timers are synthetic future calendars; no clock manipulation or
        # past Persistent catch-up is used. Core never changes this schedule.
        far_epoch = int(time.time()) + 3600
        for kind in ('product', 'market'):
            name = 'naver-' + kind + '-export.timer'
            original[name] = timer_fixture(original[name], far_epoch)
        original_files = {}
        for name, body in original.items():
            if name in (helper.COMPANION, helper.INTERPRETER): continue
            path = old_root / name if name in (*helper.SCRIPTS, *helper.COORDINATORS.values()) else helper.UNITS / name
            write_new(path, body); original_files[path] = body
        original_files[old_root / helper.INTERPRETER] = python
        _, interpreter_identity = helper._binary(old_root / helper.INTERPRETER, mode=0o550, group=10001)
        write_new(prepared_folder / 'installed.json', canonical(dict(interpreter_identity=interpreter_identity)), mode=0o600)
        # The only DB open/writes in this fixture target its newly created DB.
        import sqlite3
        database = Path(T.PROFILE['source_directory']) / T.PROFILE['database_name']
        conn = sqlite3.connect(database)
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''CREATE TABLE clients(id,naver_store_url,main_keywords,role,vertical);
CREATE TABLE client_analyses(client_id,product_url,updated_at,analysis_json,advertiser_json);
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
        cleanup_command = command
        command(['/usr/bin/systemctl', 'daemon-reload'])
        for kind in ('product', 'market'):
            command(['/usr/bin/systemctl', 'enable', '--now', 'naver-' + kind + '-export.timer'])
        done[stage] = True
        # Historical check name retained: the pinned core now queries typed
        # busctl uint64 epoch microseconds; this fixture does not rewrite output.
        stage = 'timer_unix_output'
        code, raw = real_bounded(C.NEXT, limit=128, timeout=8)
        require(code == 0 and C.next_epoch(raw) - time.time() > 300)
        done[stage] = True
        stage = 'timer_300s_refused'
        timer_path = helper.UNITS / T.OLD_TIMER
        command(['/usr/bin/systemctl', 'stop', T.OLD_TIMER])
        timer_path.unlink()
        near = timer_fixture(helper._timer('market'), int(time.time()) + 180)
        write_new(timer_path, near)
        command(['/usr/bin/systemctl', 'daemon-reload'])
        command(['/usr/bin/systemctl', 'start', T.OLD_TIMER])
        try: C._Attempt().next()
        except T.Invalid as error: require(error.args == ('REFRESH_TIMER_NEAR',))
        else: raise Refused('fixture_assertion')
        command(['/usr/bin/systemctl', 'stop', T.OLD_TIMER])
        timer_path.unlink(); write_new(timer_path, original[T.OLD_TIMER])
        command(['/usr/bin/systemctl', 'daemon-reload'])
        command(['/usr/bin/systemctl', 'start', T.OLD_TIMER])
        require(C._Attempt().next()[0] - time.time() > 300)
        done[stage] = True
        # Setup creates a genuine original product success and market failure;
        # these are not refresh attempts and are not counted as core starts.
        stage = 'original_failure_preserved'
        command(['/usr/bin/systemctl', 'start', 'naver-product-export.service'])
        command(list(C.START), accept=(1,))
        command(['/usr/bin/journalctl', '--sync'])
        original_hashes = {str(p): sha(body) for p, body in original_files.items()}
        expected_db = [sha(database.read_bytes())]
        digest = sha(canonical(original_hashes))
        proofs = {key: digest for key in T.PROOF_KEYS}
        receipt = dict(operation_id='9'*32, source_identity={'fixture': True}, runtime_identity={'fixture': True})
        def baseline(_sources):
            require(all(sha(Path(p).read_bytes()) == h for p, h in original_hashes.items()))
            require(sha(database.read_bytes()) == expected_db[0])
            return dict(proofs), types.SimpleNamespace(runtime_uid=uid, prepared_receipt=receipt)
        def deployment(_self):
            baseline(None)
            return dict(prepared_sha256=digest, started_sha256=digest,
                        containers_sha256=sha(b'explicit fixture Docker seam; no Docker query'))
        # Real helper.verify and its file/bundle readers stay unchanged. Only
        # signed installation identity/receipt loading is replaced in this VM.
        verify_function = helper.verify
        with contextlib.ExitStack() as stack:
            for obj, key, value in ((B, 'collect', baseline), (G.CurrentGuard, '_deployment', deployment),
                (C, 'RESTORED_APPLY', '1'*32), (C, 'RESTORED_ROLLBACK', '2'*32),
                (helper, '_prepared', lambda r: (profile, prepared_folder, original)),
                (helper, '_source_identity', lambda p: receipt['source_identity']),
                (helper, '_identity', lambda p: receipt['runtime_identity']), (C, '_helper', lambda _: helper)):
                stack.enter_context(replaced(obj, key, value))
            plan, files = T.compile_plan(apply_id=C.RESTORED_APPLY, rollback_id=C.RESTORED_ROLLBACK,
                                        sources=sources, previous=proofs)
            stack.enter_context(replaced(C, 'RESTORED_PLAN', T.sha(T.canonical(plan))))
            ledger = J.Ledger(C.LEDGER_ROOT, plan)
            seed_restored(ledger, plan, T)
            stage = 'original_failure_preserved'
            proof = G.CurrentGuard(proofs).capture()
            require(type(proof['invocation_id']) is str)
            try: C._verify_original(helper, receipt, C._Attempt())
            except T.Invalid as error: require(error.args == ('EXPORT_RUN_NOT_VERIFIED',))
            else: raise Refused('fixture_assertion')
            require(helper.verify is verify_function)
            done[stage] = True
            # Correct the intentionally oversized synthetic keyword. This is
            # fixture setup, not a refresh action or a production DB repair.
            conn = sqlite3.connect(database)
            try:
                conn.execute("UPDATE clients SET main_keywords='fixture'")
                conn.commit()
            finally: conn.close()
            expected_db[0] = sha(database.read_bytes())
            refreshed_id, interrupted_id = 'a'*32, 'b'*32
            start_marker = C.CONTROL / 'fixture-started.json'
            def counted(argv, *, limit, timeout):
                if argv == C.START:
                    folder = C.LEDGER_ROOT / ('refresh-' + refreshed_id)
                    intent_path = folder / 'intent.json'
                    raw_intent, info = ledger._file(intent_path)
                    intent = J.decode(raw_intent)
                    require(info.st_uid == 0 and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600)
                    require(intent['refresh_id'] == refreshed_id and intent['start_attempts_max'] == 1
                            and intent['command'] == C.START and intent['source'] == T.OPERATING_SOURCE
                            and intent['restored_plan_sha256'] == C.RESTORED_PLAN)
                    # O_EXCL is also a cross-process proof of a single start.
                    write_new(start_marker, canonical(dict(start_count=1)), mode=0o600)
                    done['durable_intent_before_start'] = True
                return real_bounded(argv, limit=limit, timeout=timeout)
            stack.enter_context(replaced(S, 'bounded', counted))
            stage = 'interrupted_intent_replay_refused'
            original_atomic = J.Ledger._atomic_new
            child = os.fork()
            if child == 0:
                def interrupt_after_intent(self, path, raw):
                    original_atomic(self, path, raw)
                    if path.name == 'intent.json': os._exit(73)
                try:
                    with replaced(J.Ledger, '_atomic_new', interrupt_after_intent):
                        C.run(dict(version=1, refresh_id=interrupted_id), sources=sources, baseline_sources=baseline_sources)
                except BaseException: os._exit(74)
                os._exit(75)
            child_deadline = time.monotonic() + 180
            while True:
                waited, status = os.waitpid(child, os.WNOHANG)
                if waited == child: break
                if time.monotonic() >= child_deadline:
                    os.kill(child, signal.SIGKILL)
                    os.waitpid(child, 0)
                    raise Refused('fixture_assertion')
                time.sleep(0.05)
            require(waited == child and os.WIFEXITED(status) and os.WEXITSTATUS(status) == 73)
            interrupted_folder = C.LEDGER_ROOT / ('refresh-' + interrupted_id)
            require((interrupted_folder / 'intent.json').is_file()
                    and not (interrupted_folder / 'result.json').exists() and not start_marker.exists())
            replay = C.run(dict(version=1, refresh_id=interrupted_id), sources=sources, baseline_sources=baseline_sources)
            require(replay['error_code'] == 'REFRESH_REUSED' and replay['attempt_consumed']
                    and not replay['start_requested'] and not start_marker.exists())
            done[stage] = True
            stage = 'single_original_start'
            result = C.run(dict(version=1, refresh_id=refreshed_id), sources=sources, baseline_sources=baseline_sources)
            require(start_marker.read_bytes() == canonical(dict(start_count=1)))
            require(result['attempt_consumed'] and result['start_requested'])
            done[stage] = True
            stage = 'original_helper_verified'
            if result['status'] != 'verified': raise T.Invalid(result['error_code'])
            require(result['original_export_success_verified'] and helper.verify is verify_function)
            require(all(not result[k] for k in ('database_opened', 'diagnostic_output_read', 'product_deployed', 'ads_written')))
            done[stage] = True
            stage = 'same_id_replay_refused'
            result_path = C.LEDGER_ROOT / ('refresh-' + refreshed_id) / 'result.json'
            previous_result = result_path.read_bytes()
            replay = C.run(dict(version=1, refresh_id=refreshed_id), sources=sources, baseline_sources=baseline_sources)
            require(replay['error_code'] == 'REFRESH_REUSED' and replay['attempt_consumed']
                    and not replay['start_requested'] and result_path.read_bytes() == previous_result
                    and start_marker.read_bytes() == canonical(dict(start_count=1)))
            done[stage] = True
            stage = 'original_files_db_preserved'
            baseline(None)
            require(all(sha(Path(p).read_bytes()) == h for p, h in original_hashes.items()))
            done[stage] = True
        require(all(done.values()))
        outcome = dict(schema=SCHEMA, status='passed', checks=done, operating_host_access=False,
            production_receipt_verified=False, current_docker_verified=False,
            original_SOURCE_LIMIT_cause_verified=False)
    except BaseException as error:
        outcome = dict(schema=SCHEMA, status='failed', failed_stage=stage,
            failure_code=failure_code(error, modules), checks=done, operating_host_access=False)
    finally:
        # Only names created after the empty-host gate are stopped. No output
        # files or evidence are deleted. The whole VM is disposable.
        if cleanup_command is not None:
            try:
                cleanup_command(['/usr/bin/systemctl', 'stop', *OLD_NAMES], accept=(0,))
            except BaseException:
                outcome = dict(schema=SCHEMA, status='failed', failed_stage='fixture_unit_stop',
                    failure_code='fixture_unavailable', checks=done, operating_host_access=False)
        if saved is not None:
            try: restore_fixture_opt(saved)
            except BaseException:
                outcome = dict(schema=SCHEMA, status='failed', failed_stage='fixture_opt_restore',
                    failure_code='fixture_unavailable', checks=done, operating_host_access=False)
    return outcome


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm', required=True, choices=[CONFIRM])
    result = run(parser.parse_args().confirm)
    print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False))
    raise SystemExit(0 if result['status'] == 'passed' else 1)
