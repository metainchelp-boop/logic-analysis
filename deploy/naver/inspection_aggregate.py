#!/usr/bin/env python3
"""One fixed, read-only inspection snapshot. Only a sealed frame leaves the host.

Stored logical-scope counts and structural checkpoint counts are deliberately
separate from current-source completion. They are not HTTP demand or attempts.
The private product is imported from its verified existing release, never copied.
"""
import base64
import contextlib
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import selectors
import signal
import sqlite3
import stat
import subprocess
import sys
import time

SOURCE = 'd633ff4450bb74206ecce5dda157387336256097'
ARCHIVE_SHA = '7155c42159555c7de2e70f21f991a8e10551cef394972c3b8a40786a203f0f73'
MANIFEST_SHA = '28fff31776da0a1309b6ebae3e12292be59fb1752f680993f612d5793d0c5fb9'
IMAGE_MANIFEST_SHA = 'c09b7c97840c89f3921b044b1770d4b23eacdc014b1e9dbe84d600f1c0c31683'
IMAGE = 'sha256:33410088d429bcf21a6c85386f04b56eb504e4065cd702590aec20bc1c39e22c'
RELEASE = Path('/srv/metainc/ad-deploy-staging/releases') / ('naver-' + SOURCE)
DATABASE = Path('/var/lib/metainc/naver-engine/engine.db')
IMAGE_ROOT = Path('/opt/naver-engine')
CHILD_DATABASE = Path('/var/lib/naver-engine/engine.db')
DEPLOY_LOCK = Path('/var/lib/metainc/naver-deploy/lock')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
FRAME_PREFIX = 'NAVER_INSPECTION_CMS_V1='
MAGIC = b'NIAGG01\n'
FRAME_BYTES = 16384
JSON_BYTES = 12288
CIPHER_BYTES = 32768
MAX_POLICIES = 5000
MAX_JOBS = 50000
MAX_PROGRESS_BYTES = 64 * 1024 * 1024
EVENTS = ('policy_blocked', 'retry_wait', 'weekly_not_due', 'account_wait',
          'account_scope_invalid', 'manual_quota', 'behind_window')
STATUSES = ('missing', 'scope_invalid', 'ok', 'reading', 'partial', 'retry', 'limited', 'reauth', 'source_wait', 'other')
BUCKETS = ('0', '1_4', '5_16', '17_64', '65_plus')
STAT_KEYS = frozenset((
    'policies_total daily_policy_total weekly_policy_total blocked_policy_total '
    'daily_effective_manual daily_touched_today daily_stored_retry_counter_sum '
    'daily_progress_missing daily_progress_invalid daily_progress_structurally_valid '
    'daily_progress_confirmed_complete daily_oldest_stored_check_age_seconds '
    'daily_oldest_stored_check_available daily_generation_age_seconds '
    'selector_eligible_pre_quota selector_returned_window '
    'authoritative_complete_available attempt_count_available http_demand_available '
    'checkpoint_source_binding_checked').split()
    + ['daily_stored_scope_' + s for s in STATUSES]
    + ['daily_remaining_' + s for s in BUCKETS]
    + ['selector_' + s for s in EVENTS])
BIND_KEYS = frozenset(('run_id', 'run_attempt', 'source', 'workflow_sha',
                       'helper_sha256', 'recipient_sha256', 'nonce'))
ERRORS = frozenset(('arguments_refused', 'host_refused', 'source_refused', 'source_unavailable',
    'database_refused', 'limit_refused', 'deadline', 'crypto_refused', 'output_refused',
    'runtime_refused', 'sqlite_refused', 'cleanup_refused', 'internal_refused'))


class Refused(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'internal_refused'
        super().__init__(self.code)


def require(ok, code='output_refused'):
    if not ok:
        raise Refused(code)


def decode(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out)
            out[k] = v
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(Refused('output_refused')))
    except (ValueError, UnicodeError, RecursionError):
        raise Refused('output_refused') from None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def validate_binding(value):
    require(type(value) is dict and set(value) == BIND_KEYS)
    require(type(value['run_id']) is str and re.fullmatch(r'[1-9][0-9]{0,19}', value['run_id']))
    require(type(value['run_attempt']) is int and value['run_attempt'] == 1)
    require(value['source'] == SOURCE)
    for key, size in (('workflow_sha', 40), ('helper_sha256', 64), ('recipient_sha256', 64), ('nonce', 64)):
        require(type(value[key]) is str and re.fullmatch('[0-9a-f]{%d}' % size, value[key]))
    return value


def validate_envelope(value, expected):
    validate_binding(expected)
    require(type(value) is dict and set(value) == {'version', 'binding', 'observed_at', 'stats'})
    require(type(value['version']) is int and value['version'] == 1)
    require(validate_binding(value['binding']) == expected)
    at = value['observed_at']
    require(type(at) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00', at))
    try:
        require(datetime.fromisoformat(at).utcoffset() == timedelta(0))
    except ValueError:
        raise Refused('output_refused') from None
    stats = value['stats']
    require(type(stats) is dict and set(stats) == STAT_KEYS)
    require(all(type(v) is int and 0 <= v <= 2**53-1 for v in stats.values()))
    require(stats['policies_total'] <= MAX_POLICIES)
    require(sum(stats[k] for k in ('daily_policy_total', 'weekly_policy_total', 'blocked_policy_total'))
            == stats['policies_total'])
    require(sum(stats['daily_stored_scope_' + k] for k in STATUSES) == stats['daily_policy_total'])
    require(sum(stats['daily_remaining_' + k] for k in BUCKETS) == stats['daily_progress_structurally_valid'])
    require(stats['daily_progress_missing'] + stats['daily_progress_invalid']
            + stats['daily_progress_structurally_valid'] == stats['daily_policy_total'])
    require(stats['daily_progress_confirmed_complete'] <= stats['daily_progress_structurally_valid'])
    require(stats['selector_returned_window'] <= 24)
    require(stats['selector_eligible_pre_quota'] == stats['selector_returned_window']
            + stats['selector_manual_quota'] + stats['selector_behind_window'])
    require(stats['selector_eligible_pre_quota'] <= stats['policies_total'])
    require(stats['daily_oldest_stored_check_available'] in (0, 1))
    for key in ('authoritative_complete_available', 'attempt_count_available',
                'http_demand_available', 'checkpoint_source_binding_checked'):
        require(stats[key] == 0)
    require(len(canonical(value)) <= JSON_BYTES)
    return value


def pack(value):
    raw = canonical(value)
    require(0 < len(raw) <= JSON_BYTES)
    return MAGIC + len(raw).to_bytes(4, 'big') + raw + os.urandom(FRAME_BYTES - 12 - len(raw))


def unpack(raw):
    require(type(raw) is bytes and len(raw) == FRAME_BYTES and raw[:8] == MAGIC)
    size = int.from_bytes(raw[8:12], 'big')
    require(0 < size <= JSON_BYTES)
    return decode(raw[12:12 + size])


def command(argv, *, data=b'', limit=65536, timeout=5, env=ENV, allowed_codes=(0,)):
    """Bound both output streams; never echo a command's stderr or exception."""
    require(len(data) <= CIPHER_BYTES, 'limit_refused')
    child = None
    try:
        child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, shell=False, start_new_session=True)
        end, result, errors = time.monotonic() + timeout, bytearray(), bytearray()
        # Our largest input is 16 KiB; keep stdin nonblocking as well as output.
        with selectors.DefaultSelector() as poll:
            for stream in (child.stdin, child.stdout, child.stderr):
                os.set_blocking(stream.fileno(), False)
            if data:
                poll.register(child.stdin, selectors.EVENT_WRITE, 'in')
            else:
                child.stdin.close()
            poll.register(child.stdout, selectors.EVENT_READ, 'out')
            poll.register(child.stderr, selectors.EVENT_READ, 'err')
            offset = 0
            while poll.get_map():
                require(time.monotonic() < end, 'deadline')
                for key, _ in poll.select(min(.1, max(.001, end-time.monotonic()))):
                    if key.data == 'in':
                        offset += os.write(key.fd, data[offset:])
                        if offset == len(data):
                            poll.unregister(key.fileobj)
                            child.stdin.close()
                        continue
                    part = os.read(key.fd, 8192)
                    if not part:
                        poll.unregister(key.fileobj)
                    elif key.data == 'out':
                        result.extend(part)
                    else:
                        errors.extend(part)
                    require(len(result) + len(errors) <= limit, 'limit_refused')
        require(child.wait(timeout=max(.001, end-time.monotonic())) in allowed_codes, 'runtime_refused')
        return bytes(result)
    except (OSError, subprocess.SubprocessError):
        raise Refused('runtime_refused') from None
    finally:
        if child is not None:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            child.wait(timeout=2)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()


def safe_file(path, limit, owner=0):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner and before.st_nlink == 1
                and not before.st_mode & 0o022 and before.st_size <= limit, 'source_refused')
        raw = bytearray()
        while len(raw) <= limit:
            part = os.read(fd, min(65536, limit + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns,
                              s.st_uid, s.st_mode, s.st_nlink)
        require(len(raw) <= limit and identity(before) == identity(os.fstat(fd)), 'source_refused')
        return bytes(raw)
    finally:
        os.close(fd)


def safe_parents(path, *, leaf_owner=0):
    current = Path('/')
    for part in path.parts[1:]:
        current /= part
        item = current.lstat()
        require(stat.S_ISDIR(item.st_mode) and item.st_uid == (leaf_owner if current == path else 0)
                and not item.st_mode & 0o022, 'host_refused')


def verify_release(root=RELEASE, expected=MANIFEST_SHA, count=167, overrides=True):
    safe_parents(root)
    rows, total = [], 0
    for folder, dirs, files in os.walk(root, followlinks=False):
        require(len(rows) <= 200, 'source_refused')
        for name in dirs:
            info = (Path(folder) / name).lstat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022, 'source_refused')
        for name in files:
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            if overrides and relative in ('preview-engine.override.yml', 'preview-relay.override.yml'):
                safe_file(path, 65536)
                continue
            raw = safe_file(path, 16 * 1024 * 1024)
            total += len(raw)
            require(total <= 16 * 1024 * 1024, 'source_refused')
            rows.append((relative, hashlib.sha256(raw).digest()))
    digest = hashlib.sha256()
    for name, hashed in sorted(rows):
        digest.update(name.encode() + b'\0' + hashed)
    require(len(rows) == count and digest.hexdigest() == expected, 'source_refused')
    return digest.hexdigest()


def engine_identity():
    base = ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', '--config', str(Path(__file__).absolute().parent)]
    ids = command(base + ['ps', '--no-trunc', '--quiet', '--filter',
        'label=com.docker.compose.project=naver-engine', '--filter',
        'label=com.docker.compose.service=naver-engine']).decode('ascii').split()
    require(len(ids) == 1 and re.fullmatch(r'[0-9a-f]{64}', ids[0]), 'host_refused')
    template = ('{"id":{{json .Id}},"image":{{json .Image}},"pid":{{json .State.Pid}},'
        '"running":{{json .State.Running}},"paused":{{json .State.Paused}},'
        '"restarting":{{json .State.Restarting}},"started":{{json .State.StartedAt}},'
        '"restarts":{{json .RestartCount}},"user":{{json .Config.User}},'
        '"readonly":{{json .HostConfig.ReadonlyRootfs}},'
        '"source":{{json (index .Config.Labels "metainc.naver.preview.source")}},'
        '"schema":{{json (index .Config.Labels "metainc.naver.schema")}},'
        '"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}{{json .}}{{end}}{{end}}]}')
    value = decode(command(base + ['inspect', '--format', template, ids[0]]))
    require(type(value) is dict and set(value) == set(
        'id image pid running paused restarting started restarts user readonly source schema data'.split()), 'host_refused')
    require(value['id'] == ids[0] and value['image'] == IMAGE and value['source'] == SOURCE
        and value['schema'] == '21' and value['user'] == '10001:10001' and value['readonly'] is True
        and value['running'] is True and value['paused'] is False and value['restarting'] is False
        and type(value['pid']) is int and value['pid'] > 0, 'host_refused')
    require(type(value['data']) is list and len(value['data']) == 1 and all(
        value['data'][0].get(k) == v for k, v in {'Type': 'bind',
        'Source': str(DATABASE.parent), 'Destination': '/var/lib/naver-engine', 'RW': True}.items()), 'host_refused')
    return value


def forbid_side_effects(event, args, allowed_database=DATABASE):
    if event.startswith('socket.') or event in ('os.system', 'os.exec', 'os.posix_spawn'):
        raise Refused('runtime_refused')
    if event == 'open':
        flags = args[2]
        if type(flags) is int and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise Refused('runtime_refused')
    if event == 'sqlite3.connect':
        require(args[0] == allowed_database.as_uri() + '?mode=ro', 'database_refused')


def require_sqlite_runtime():
    """Old SQLite JSON functions cannot read this schema with trusted_schema=OFF.

    Inspect function flags in an empty memory connection before opening any
    product database. Never enable trusted_schema or substitute an unsafe reader.
    """
    try:
        with sqlite3.connect(':memory:') as connection:
            flags = {row[0]: row[5] for row in connection.execute('PRAGMA function_list')}
        require(all(flags.get(name, 0) & 0x200000 for name in ('json_extract', 'json_valid')), 'sqlite_refused')
    except sqlite3.Error:
        raise Refused('sqlite_refused') from None


def preflight_rows(conn, day):
    schema = conn.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()
    require(schema is not None and schema[0] == '21', 'database_refused')
    for table in ('naver_auto_account', 'naver_auto_manual_read'):
        require(conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] <= MAX_POLICIES, 'limit_refused')
    row = conn.execute('SELECT count(*),coalesce(sum(length(CAST(progress_json AS BLOB))),0),'
        'coalesce(max(length(CAST(progress_json AS BLOB))),0) FROM naver_auto_inspection_job WHERE cycle_day>=?',
        ((day-timedelta(days=8)).isoformat(),)).fetchone()
    require(row[0] <= MAX_JOBS and row[1] <= MAX_PROGRESS_BYTES and row[2] <= 8*1024*1024, 'limit_refused')


def aggregate(reader, now, product):
    """Caller owns one read_snapshot and its deadline; no Store write method is used."""
    S, MS, P, IS, R = product
    require(not reader.writer and reader._conn.in_transaction, 'database_refused')
    day = now.astimezone(S.KST).date()
    require(now.astimezone(S.KST).time().replace(tzinfo=None) >= P.COLLECTION_START, 'source_unavailable')
    preflight_rows(reader._conn, day)
    policies = MS.snapshot(reader, now)
    require(0 < len(policies) <= MAX_POLICIES and all(r['source_current'] for r in policies.values()), 'source_unavailable')
    requests = {r['customer_id']: r for r in S._rows(reader._conn.execute('SELECT * FROM naver_auto_manual_read'))}
    source = reader._performance_selection_source(now, policies, requests)
    require(source.snapshot is not None and source.catalog is not None, 'source_unavailable')
    stats = dict.fromkeys(STAT_KEYS, 0)
    stats['policies_total'] = len(policies)
    midnight = datetime.combine(day, datetime.min.time(), tzinfo=S.KST)
    stats['daily_generation_age_seconds'] = max(0, int((now-midnight-timedelta(minutes=1)).total_seconds()))
    for cid, policy in policies.items():
        cadence = policy['decision'].cadence
        require(cadence in ('daily', 'weekly', 'blocked'), 'source_unavailable')
        stats[cadence + '_policy_total'] += 1
        if cadence != 'daily':
            continue
        manual = reader._inspection_manual_job(requests.get(cid), policy, source.snapshot,
            source.catalog['generated_at'], source.fingerprint, now, source)
        period = P.period_for(cadence, day)
        job = reader._performance_job(cid, cadence, period.cycle_day, period.since, period.until,
            policy, source.snapshot, source.catalog['generated_at'], matching_fingerprint=source.fingerprint)
        job['job_key'] = 'inspection:' + job['job_key']
        job = manual or job
        stats['daily_effective_manual'] += int(manual is not None)
        rows = S._rows(reader._conn.execute('SELECT * FROM naver_auto_inspection_job WHERE job_key=?', (job['job_key'],)))
        old = rows[0] if rows else None
        # Same exact logical work item; source timestamps/fingerprints are NOT silently
        # promoted to current authority. The original ordering helper proves this scope.
        attempted = IS._inspection_order_attempt(old, job, policy['possibility_id'], now)
        if old is not None and not attempted:
            stats['daily_stored_scope_scope_invalid'] += 1
            stats['daily_progress_invalid'] += 1
            continue
        status = old['status'] if old else 'missing'
        stats['daily_stored_scope_' + (status if status in STATUSES else 'other')] += 1
        if old is None:
            stats['daily_progress_missing'] += 1
            continue
        checked = datetime.fromisoformat(attempted)
        stats['daily_touched_today'] += int(midnight <= checked <= now)
        stats['daily_oldest_stored_check_available'] = 1
        stats['daily_oldest_stored_check_age_seconds'] = max(stats['daily_oldest_stored_check_age_seconds'],
            int((now-checked).total_seconds()))
        require(type(old['attempts']) is int and 0 <= old['attempts'] <= 2**31, 'database_refused')
        stats['daily_stored_retry_counter_sum'] += old['attempts']
        raw = old['progress_json']
        if raw is None:
            stats['daily_progress_missing'] += 1
            continue
        try:
            require(type(raw) is str and len(raw.encode()) <= 8*1024*1024)
            require(hashlib.sha256(raw.encode()).hexdigest() == old['progress_hash'])
            progress = decode(raw)
            R.validate_progress(progress, IS._job(old))
            require(all(datetime.fromisoformat(t) <= now for t in IS._observed_times(progress)))
            remaining = len(progress['queue']) - progress['next_index']
            stats['daily_progress_structurally_valid'] += 1
            stats['daily_progress_confirmed_complete'] += int(progress['confirmed'] and remaining == 0)
            bucket = '0' if remaining == 0 else '1_4' if remaining <= 4 else '5_16' if remaining <= 16 else '17_64' if remaining <= 64 else '65_plus'
            stats['daily_remaining_' + bucket] += 1
        except (Refused, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            stats['daily_progress_invalid'] += 1
    seen = {'started': False, 'invalid': False}
    def observe(event, **fields):
        if event == 'selection_started':
            seen['started'] = True
        elif event.startswith('selection_') and event[10:] in EVENTS:
            stats['selector_' + event[10:]] += 1
        else:
            seen['invalid'] = True
    selected = reader.collection_candidates('inspection_work', now, 24, observe=observe)
    require(seen['started'] and not seen['invalid'], 'source_unavailable')
    stats['selector_returned_window'] = len(selected)
    stats['selector_eligible_pre_quota'] = len(selected) + stats['selector_manual_quota'] + stats['selector_behind_window']
    return stats


def encrypt(value, certificate, expected, runner=command, certificate_owner=None):
    validate_envelope(value, expected)
    cert = safe_file(certificate, 8192, owner=os.geteuid() if certificate_owner is None else certificate_owner)
    require(hashlib.sha256(cert).hexdigest() == expected['recipient_sha256'], 'crypto_refused')
    require(cert.count(b'-----BEGIN CERTIFICATE-----') == cert.count(b'-----END CERTIFICATE-----') == 1
            and b'PRIVATE KEY' not in cert, 'crypto_refused')
    # Pin an RSA-3072 SPKI, not an arbitrary recipient algorithm or huge certificate.
    try:
        pem = runner(['/usr/bin/openssl', 'x509', '-in', str(certificate), '-pubkey', '-noout'], limit=8192)
        public = runner(['/usr/bin/openssl', 'pkey', '-pubin', '-text_pub', '-noout'], data=pem, limit=8192)
        require(b'Public-Key: (3072 bit)' in public and b'Exponent: 65537 ' in public, 'crypto_refused')
        cipher = runner(['/usr/bin/openssl', 'cms', '-encrypt', '-binary', '-aes-256-gcm',
            '-outform', 'DER', '-recip', str(certificate), '-keyopt', 'rsa_padding_mode:oaep',
            '-keyopt', 'rsa_oaep_md:sha256', '-keyopt', 'rsa_mgf1_md:sha256'],
            data=pack(value), limit=CIPHER_BYTES, timeout=5)
    except BaseException:
        raise Refused('crypto_refused') from None
    require(0 < len(cipher) <= CIPHER_BYTES, 'crypto_refused')
    return FRAME_PREFIX + base64.b64encode(cipher).decode('ascii')


def limits(seconds):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024, 512*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    def expired(*_):
        raise Refused('deadline')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)


def database_identity(path):
    safe_parents(path.parent, leaf_owner=10001)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 10001 and info.st_nlink == 1
            and not info.st_mode & 0o077, 'database_refused')
    return info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink


def read_child(payload):
    require(type(payload) is dict and set(payload) == {'binding', 'deadline'}, 'arguments_refused')
    binding, deadline = validate_binding(payload['binding']), payload['deadline']
    require(sys.platform == 'linux' and os.geteuid() == os.getegid() == 10001
            and sys.version_info >= (3, 10), 'host_refused')
    require(type(deadline) in (int, float) and 0 < deadline-time.monotonic() <= 26, 'deadline')
    limits(deadline-time.monotonic())
    require_sqlite_runtime()
    sys.addaudithook(lambda event, args: forbid_side_effects(event, args, CHILD_DATABASE))
    helper = Path(__file__).absolute()
    require(hashlib.sha256(safe_file(helper, 131072)).hexdigest() == binding['helper_sha256'], 'source_refused')
    verify_release(IMAGE_ROOT, IMAGE_MANIFEST_SHA, 110, False)
    before = database_identity(CHILD_DATABASE)
    sys.path[:0] = [str(IMAGE_ROOT / 'backend'), str(IMAGE_ROOT)]
    from naver_engine import store as S, management_store as MS, management as P
    from naver_engine import inspection_store as IS, inspection_reads as R
    require(S.SCHEMA_VERSION == 21, 'source_refused')
    now = datetime.now(timezone.utc).replace(microsecond=0)
    query_deadline = min(deadline-3, time.monotonic()+20)
    try:
        with S.open_reader(str(CHILD_DATABASE)) as reader:
            reader._conn.set_progress_handler(lambda: int(time.monotonic() >= query_deadline), 1000)
            before_changes = reader._conn.total_changes
            with reader.read_snapshot():
                stats = aggregate(reader, now, (S, MS, P, IS, R))
            require(reader._conn.total_changes == before_changes == 0, 'database_refused')
    except BaseException:
        if time.monotonic() >= query_deadline:
            raise Refused('deadline') from None
        raise
    require(database_identity(CHILD_DATABASE) == before, 'database_refused')
    verify_release(IMAGE_ROOT, IMAGE_MANIFEST_SHA, 110, False)
    value = {'version': 1, 'binding': binding, 'observed_at': now.isoformat(), 'stats': stats}
    result = encrypt(value, helper.with_name('recipient.pem'), binding, certificate_owner=0)
    signal.alarm(0)
    return result


def child_arguments(binding, helper, certificate):
    return ['create', '--pull', 'never', '--interactive', '--name',
        'naver-inspection-'+binding['run_id']+'-1', '--label',
        'metainc.naver.inspection.run='+binding['run_id']+'-1',
        '--label', 'metainc.naver.inspection.binding='+hashlib.sha256(canonical(binding)).hexdigest(),
        '--network', 'none', '--read-only', '--user', '10001:10001',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--pids-limit', '32', '--memory', '512m', '--memory-swap', '512m', '--cpus', '0.5',
        '--mount', 'type=bind,src='+str(DATABASE.parent)+',dst='+str(CHILD_DATABASE.parent)+',readonly',
        '--mount', 'type=bind,src='+str(helper)+',dst=/probe/inspection_aggregate.py,readonly',
        '--mount', 'type=bind,src='+str(certificate)+',dst=/probe/recipient.pem,readonly',
        '--entrypoint', '/usr/local/bin/python', IMAGE, '-I', '-B', '/probe/inspection_aggregate.py', '--child']


@contextlib.contextmanager
def deployment_lock(path=DEPLOY_LOCK, owner=0):
    """Share the existing deploy lock without creating, truncating or writing it."""
    safe_parents(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner and before.st_nlink == 1
                and not before.st_mode & 0o022, 'host_refused')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            raise Refused('host_refused') from None
        yield
        after = path.lstat()
        require((before.st_dev, before.st_ino, before.st_uid, before.st_mode, before.st_nlink)
                == (after.st_dev, after.st_ino, after.st_uid, after.st_mode, after.st_nlink), 'host_refused')
    finally:
        os.close(descriptor)


def listed_child(base, binding):
    name = 'naver-inspection-'+binding['run_id']+'-1'
    rows = command(base + ['ps', '--all', '--no-trunc', '--quiet', '--filter', 'name=^/'+name+'$'],
                   timeout=2, limit=512).decode('ascii').split()
    require(len(rows) <= 1 and all(re.fullmatch(r'[0-9a-f]{64}', row) for row in rows), 'cleanup_refused')
    return rows[0] if rows else None


def cleanup_child(base, binding, identifier):
    # A create response may time out after Docker created the stopped container.
    # Recover only the exact one-use name, image and binding; never remove a foreign match.
    identifier = identifier or listed_child(base, binding)
    if identifier is None:
        return
    template = ('{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
        '"binding":{{json (index .Config.Labels "metainc.naver.inspection.binding")}}}')
    value = decode(command(base + ['inspect', '--format', template, identifier], timeout=2, limit=2048))
    require(value == {'id': identifier, 'name': '/naver-inspection-'+binding['run_id']+'-1',
        'image': IMAGE, 'binding': hashlib.sha256(canonical(binding)).hexdigest()}, 'cleanup_refused')
    command(base + ['rm', '--force', identifier], timeout=3)


def run(binding):
    """Host validates identity; an isolated fixed-image child performs the read."""
    validate_binding(binding)
    require(sys.platform == 'linux' and os.geteuid() == 0 and sys.version_info >= (3, 10), 'host_refused')
    limits(30)
    with deployment_lock():
        return run_locked(binding)


def run_locked(binding):
    started = time.monotonic()
    helper, certificate = Path(__file__).absolute(), Path(__file__).absolute().with_name('recipient.pem')
    require(hashlib.sha256(safe_file(helper, 131072)).hexdigest() == binding['helper_sha256'], 'source_refused')
    require(hashlib.sha256(safe_file(certificate, 8192)).hexdigest() == binding['recipient_sha256'], 'crypto_refused')
    before, database_before = engine_identity(), database_identity(DATABASE)
    verify_release()
    base = ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', '--config', str(helper.parent)]
    require(listed_child(base, binding) is None, 'host_refused')
    identifier = None
    try:
        receipt = command(base + child_arguments(binding, helper, certificate)).decode('ascii').strip()
        require(re.fullmatch(r'[0-9a-f]{64}', receipt), 'host_refused')
        identifier = receipt
        payload = canonical({'binding': binding, 'deadline': started+25})
        raw = command(base + ['start', '--attach', '--interactive', identifier], data=payload,
            limit=48000, timeout=max(.001, started+26-time.monotonic()), allowed_codes=(0, 2))
        text = raw.decode('ascii').strip()
        failure = re.fullmatch(r'NAVER_INSPECTION_REFUSED=([a-z_]+)', text)
        if failure:
            raise Refused(failure[1])
        require(re.fullmatch(re.escape(FRAME_PREFIX)+r'[A-Za-z0-9+/=]{1,43692}', text))
        cipher = base64.b64decode(text[len(FRAME_PREFIX):], validate=True)
        require(0 < len(cipher) <= CIPHER_BYTES)
    finally:
        cleanup_child(base, binding, identifier)
        require(engine_identity() == before and database_identity(DATABASE) == database_before, 'host_refused')
        verify_release()
    signal.alarm(0)
    return text


def main():
    try:
        require(sys.argv[1:] in ([], ['--child']), 'arguments_refused')
        raw = sys.stdin.buffer.read(8193)
        require(0 < len(raw) <= 8192, 'arguments_refused')
        # Third-party import/SQLite/crypto stderr never reaches the public workflow.
        with open(os.devnull, 'w') as sink:
            saved = (os.dup(1), os.dup(2))
            try:
                os.dup2(sink.fileno(), 1)
                os.dup2(sink.fileno(), 2)
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    line = (read_child if sys.argv[1:] == ['--child'] else run)(decode(raw))
            finally:
                sink.flush()
                os.dup2(saved[0], 1)
                os.dup2(saved[1], 2)
                os.close(saved[0])
                os.close(saved[1])
        require(type(line) is str and re.fullmatch(re.escape(FRAME_PREFIX) + r'[A-Za-z0-9+/=]{1,43692}', line))
        print(line)
        return 0
    except BaseException as exc:
        code = exc.code if isinstance(exc, Refused) else 'internal_refused'
        print('NAVER_INSPECTION_REFUSED=' + code)
        return 2
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    sys.exit(main())
