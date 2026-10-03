"""Synthetic-only backup upload from the prepared engine image; no scheduler or DB mount.

Invoke run(package, approved_host.NativeHost()) through the reviewed management job.
This does not perform BE readback or recovery: those existing, separate jobs remain required.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from datetime import date

ROOT = Path('/srv/metainc/ad-deploy-staging')
SECRET_ROOT = Path('/etc/metainc/naver-engine')
MOUNTS = {'backup-recipient.pem': 'naver-backup-recipient.pem',
          'backup-upload-key': 'naver-backup-upload-key',
          'backup-known-hosts': 'naver-backup-known-hosts'}
STAGE = 'input'
COMMAND_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'}
COMMAND_CODES = frozenset({'INSPECT_TEMPLATE_ERROR', 'DOCKER_ACCESS_DENIED', 'IMAGE_MISSING',
                           'DOCKER_DAEMON_UNAVAILABLE', 'COMMAND_FAILED', 'OUTPUT_TOO_LARGE'})


def validate_package(package):
    if not isinstance(package, dict) or set(package) != {'baseline', 'source_commit', 'run_id'}:
        raise ValueError('PACKAGE_FIELDS')
    for name, pattern in [('baseline', '[0-9a-f]{64}'), ('source_commit', '[0-9a-f]{40}'), ('run_id', '[0-9]{6,20}')]:
        if not isinstance(package[name], str) or not re.fullmatch(pattern, package[name]):
            raise ValueError('PACKAGE_SHAPE')
    return package


def read_trusted(path, *, uid=0, gid=0, maximum=32768):
    path = Path(path)
    if not path.is_absolute() or path != path.resolve():
        raise ValueError('FILE_PATH')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, 0o600)
                or not 0 < info.st_size <= maximum):
            raise ValueError('FILE_POLICY')
        return stream.read(maximum + 1)


def command(args, *, data=None, timeout=30):
    inspecting = args[:3] == ['/usr/bin/docker', 'image', 'inspect']
    result = subprocess.run(args, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE if inspecting else subprocess.DEVNULL,
                            timeout=timeout, env=COMMAND_ENV, check=False)
    if len(result.stdout) > 8192:
        raise RuntimeError('OUTPUT_TOO_LARGE')
    if result.returncode:
        code = 'COMMAND_FAILED'
        # Inspect diagnostics stay in memory; only fixed codes can reach the receipt.
        stderr = (result.stderr or b'')[:8192].lower() if inspecting else b''
        for marker, candidate in [(b'permission denied', 'DOCKER_ACCESS_DENIED'),
                                  (b'template parsing error', 'INSPECT_TEMPLATE_ERROR'),
                                  (b'no such image', 'IMAGE_MISSING'),
                                  (b'cannot connect to the docker daemon', 'DOCKER_DAEMON_UNAVAILABLE')]:
            if marker in stderr:
                code = candidate
                break
        raise RuntimeError(code)
    return result.stdout


def container_command(image_id, run_id):
    if not re.fullmatch('sha256:[0-9a-f]{64}', image_id) or not re.fullmatch('[0-9]{6,20}', run_id):
        raise ValueError('CONTAINER_INPUT')
    args = ['/usr/bin/docker', 'create', '--interactive', '--name', 'naver-backup-probe-' + run_id,
            '--label', 'metainc.naver.backup.synthetic=' + run_id, '--read-only', '--user', '10001:10001',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--pids-limit', '32',
            '--memory', '128m', '--cpus', '0.25', '--network', 'bridge', '--log-driver', 'none',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777', '--entrypoint', 'python']
    for source, target in MOUNTS.items():
        args += ['--mount', f'type=bind,src={SECRET_ROOT / source},dst=/run/secrets/{target},readonly']
    return args + [image_id, '-I', '-B', '-']


def validate_receipt(value):
    if not isinstance(value, dict) or set(value) != {'status', 'ciphertext', 'expected_kst_date', 'expected_row_counts'}:
        raise ValueError('UPLOAD_RECEIPT')
    cipher = value['ciphertext']
    if (value['status'] != 'synthetic_transfer_verified' or not isinstance(cipher, dict)
            or set(cipher) != {'sha256', 'size'} or not isinstance(cipher['sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', cipher['sha256']) or type(cipher['size']) is not int
            or not 0 < cipher['size'] <= 32768
            or not isinstance(value['expected_kst_date'], str)
            or not re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}', value['expected_kst_date'])
            or value['expected_row_counts'] != {'synthetic_leads': 3, 'synthetic_events': 2}
            or any(type(count) is not int for count in value['expected_row_counts'].values())):
        raise ValueError('UPLOAD_RECEIPT')
    date.fromisoformat(value['expected_kst_date'])
    return value


def probe(package, host):
    global STAGE
    STAGE = 'preflight'
    validate_package(package)
    if os.geteuid() != 0 or host.baseline() != package['baseline']:
        raise ValueError('HOST_BASELINE')
    commit = package['source_commit']
    STAGE = 'preflight_receipt'
    receipt = json.loads(read_trusted(ROOT / 'receipts' / ('preview-' + commit + '.json')))
    if (receipt.get('ok') is not True or receipt.get('stage') != 'prepared'
            or receipt.get('source_commit') != commit):
        raise ValueError('NOT_PREPARED')
    STAGE = 'preflight_backup_files'
    for name in MOUNTS:
        path = SECRET_ROOT / name
        body = read_trusted(path, uid=10001, gid=10001)
        if hashlib.sha256(body).hexdigest() != receipt.get('files', {}).get(str(path)):
            raise ValueError('PREPARED_FILE_CHANGED')
    STAGE = 'preflight_image_inspect'
    image_format = ('{"Id":{{json .Id}},"Config":{"User":{{json .Config.User}},'
                    '"Labels":{"metainc.naver.preview.source":{{json (index .Config.Labels "metainc.naver.preview.source")}}},'
                    '"Volumes":{{json (index .Config "Volumes")}}}}')
    image = json.loads(command(['/usr/bin/docker', 'image', 'inspect', '--format',
                               image_format, 'metainc/naver-engine:' + commit]))
    image_id = image.get('Id', '')
    if (not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or image_id != receipt.get('images', {}).get('engine')
            or image.get('Config', {}).get('Labels', {}).get('metainc.naver.preview.source') != commit
            or image.get('Config', {}).get('User') != '10001:10001'
            or image.get('Config', {}).get('Volumes')):
        raise ValueError('PREPARED_IMAGE_CHANGED')
    STAGE = 'create_synthetic_container'
    container = command(container_command(image_id, package['run_id'])).decode().strip()
    if not re.fullmatch('[0-9a-f]{64}', container):
        raise ValueError('CONTAINER_ID')
    try:
        STAGE = 'synthetic_upload'
        result = validate_receipt(json.loads(command(['/usr/bin/docker', 'start', '--attach', '--interactive', container],
                                                     data=PROBE_SCRIPT.encode(), timeout=450)))
    finally:
        previous_stage = STAGE
        STAGE = 'remove_synthetic_container'
        # Only the exact ID returned by this create; never a name, glob, existing service or volume.
        command(['/usr/bin/docker', 'rm', '--force', container])
        STAGE = previous_stage
    STAGE = 'postflight'
    if host.baseline() != package['baseline']:
        raise ValueError('POST_BASELINE')
    result.update(ok=True, source_commit=commit, engine_image_id=image_id, engine_host_sender_verified=True,
                  operating_data_used=False, production_data_mounted=False, scheduler_started=False,
                  recovery_key_used=False, receiver_readback_verified=False, isolated_restore_verified=False,
                  synthetic_container_removed=True, existing_app_baseline_unchanged=True)
    return result


def run(package, host):
    try:
        return probe(package, host)
    except Exception as error:
        # Do not echo exception text: Docker/SSH/config failures may contain sensitive material.
        code = (error.args[0] if type(error) is RuntimeError and len(error.args) == 1
                and isinstance(error.args[0], str) and error.args[0] in COMMAND_CODES else 'UNCLASSIFIED')
        return {'ok': False, 'stage': STAGE, 'error_kind': type(error).__name__,
                'error_code': code,
                'secret_values_exported': False, 'manual_review_required': True}


PROBE_SCRIPT = r'''
import hashlib,json,os,pathlib,sqlite3,sys,tempfile
from contextlib import closing
from datetime import datetime,timezone,timedelta
sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
os.environ.clear()
os.environ.update(PATH='/usr/bin:/bin',OPENSSL_CONF='/dev/null')
from naver_engine import backup as B
from naver_runtime import backup_transport as T

def snapshot(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('CREATE TABLE synthetic_leads (id INTEGER PRIMARY KEY, score INTEGER)')
        connection.executemany('INSERT INTO synthetic_leads VALUES (?, ?)',[(1,10),(2,20),(3,30)])
        connection.execute('CREATE TABLE synthetic_events (id INTEGER PRIMARY KEY, label TEXT)')
        connection.executemany('INSERT INTO synthetic_events VALUES (?, ?)',[(1,'test-only'),(2,'not-operating-data')])
    return {'synthetic_leads':3,'synthetic_events':2}

try:
    if os.geteuid()!=10001:
        raise ValueError('IDENTITY')
    with tempfile.TemporaryDirectory(prefix='naver-synthetic-',dir='/tmp') as directory:
        root=pathlib.Path(directory)
        now=datetime.now(timezone.utc)
        result=B.create_backup(snapshot,root/'local',root/'outgoing',now=now,
            encrypt=T.OpenSslEncryptor('/run/secrets/naver-backup-recipient.pem'))
        if result.code!='READY' or not 0<result.encrypted_path.stat().st_size<=32768:
            raise ValueError('SYNTHETIC_ARCHIVE')
        cipher={'sha256':B.file_digest(result.encrypted_path),'size':result.encrypted_path.stat().st_size}
        result=B.publish_backup(result,T.SshSender('/run/secrets/naver-backup-upload-key','/run/secrets/naver-backup-known-hosts'))
        if result.code!='OFFSITE_OK' or not result.offsite_verified:
            raise ValueError('UPLOAD')
        print(json.dumps({'status':'synthetic_transfer_verified','ciphertext':cipher,
            'expected_kst_date':now.astimezone(timezone(timedelta(hours=9))).date().isoformat(),
            'expected_row_counts':{'synthetic_leads':3,'synthetic_events':2}},sort_keys=True))
except Exception:
    print('SYNTHETIC_BACKUP_PROBE_FAILED',file=sys.stderr)
    sys.exit(1)
'''
