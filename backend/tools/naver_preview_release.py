"""Install only the approved, separately encrypted Naver preview release.

Ciphertext/source hashes come from the authenticated build receipt, not the envelope.
No existing application, environment or database is replaced by preparation.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import stat
import subprocess
import tarfile

ROOT = Path('/srv/metainc/ad-deploy-staging')
SECRET_ROOT = Path('/etc/metainc/naver-engine')
SECRET_OWNERS = {'runtime.env': (0, 0), 'backup-recipient.pem': (10001, 10001),
                 'backup-upload-key': (10001, 10001), 'backup-known-hosts': (10001, 10001)}
EXACT = {'Dockerfile.naver-engine', 'Dockerfile.naver-relay', 'Dockerfile.naver-relay.dockerignore',
         'compose.naver-engine.yml', 'compose.naver-relay.yml', 'backend/app/__init__.py',
         'backend/app/naver_entry.py', 'backend/app/naver_relay.py', 'backend/app/routers/naver.py',
         'backend/app/routers/__init__.py', 'backend/requirements.txt'}
PREFIXES = ('naver_engine/', 'naver_runtime/', 'backend/app/naver_auto/', 'backend/naver_page/', 'deploy/')
STAGE = 'input'


def sha(body):
    return hashlib.sha256(body).hexdigest()


def command(args, *, timeout=45, data=None):
    result = subprocess.run(args, input=data, capture_output=True, timeout=timeout,
                            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
    if result.returncode:
        raise RuntimeError('COMMAND_FAILED')
    return result.stdout


def validate_package(package):
    if not isinstance(package, dict) or set(package) != {
            'baseline', 'source_commit', 'ciphertext_sha256', 'source_tar_gz_sha256', 'run_id', 'operation'}:
        raise ValueError('PACKAGE_FIELDS')
    for field, pattern in (('baseline', '[0-9a-f]{64}'), ('source_commit', '[0-9a-f]{40}'),
                           ('ciphertext_sha256', '[0-9a-f]{64}'), ('source_tar_gz_sha256', '[0-9a-f]{64}'),
                           ('run_id', '[0-9]{6,20}')):
        if not isinstance(package[field], str) or not re.fullmatch(pattern, package[field]):
            raise ValueError('PACKAGE_SHAPE')
    if package['operation'] not in ('prepare', 'start'):
        raise ValueError('PACKAGE_OPERATION')
    return package


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_FIELD')
        result[key] = value
    return result


def validate_payload(payload, commit, source_hash):
    if not isinstance(payload, dict) or set(payload) != {
            'schema', 'purpose', 'source_commit', 'source_tar_gz_b64', 'files'}:
        raise ValueError('PAYLOAD_FIELDS')
    if (payload['schema'] != 1 or payload['purpose'] != 'naver-owner-verification-runtime'
            or payload['source_commit'] != commit):
        raise ValueError('PAYLOAD_SOURCE')
    source = base64.b64decode(payload['source_tar_gz_b64'], validate=True)
    if not 0 < len(source) <= 2*1024*1024 or sha(source) != source_hash:
        raise ValueError('PAYLOAD_HASH')
    files = payload['files']
    if not isinstance(files, list) or len(files) != 4:
        raise ValueError('PAYLOAD_FILES')
    found = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {'path', 'mode', 'uid', 'gid', 'content'}:
            raise ValueError('FILE_FIELDS')
        name = Path(item['path']).name
        if name not in SECRET_OWNERS or item['path'] != str(SECRET_ROOT / name) or name in found:
            raise ValueError('FILE_PATH')
        if (item['uid'], item['gid']) != SECRET_OWNERS[name] or item['mode'] != 0o600:
            raise ValueError('FILE_OWNER')
        if not isinstance(item['content'], str) or not 0 < len(item['content'].encode()) <= 32768:
            raise ValueError('FILE_CONTENT')
        found.add(name)
    return source, files


def source_members(body):
    archive = tarfile.open(fileobj=io.BytesIO(body), mode='r:gz')
    members, seen, total = [], set(), 0
    for member in archive:
        name = member.name.rstrip('/')
        parts = PurePosixPath(name).parts
        if (not name or name.startswith('/') or '..' in parts or '.' in parts
                or '\\' in name or name in seen or not (member.isdir() or member.isfile())):
            raise ValueError('SOURCE_PATH')
        allowed_file = name in EXACT or name.startswith(PREFIXES)
        allowed_dir = any(path.startswith(name + '/') for path in EXACT | set(PREFIXES)) or name.startswith(PREFIXES)
        if not (allowed_dir if member.isdir() else allowed_file):
            raise ValueError('SOURCE_SCOPE')
        total += member.size
        if member.size > 1024*1024 or total > 16*1024*1024 or len(seen) >= 1000:
            raise ValueError('SOURCE_SIZE')
        seen.add(name)
        members.append(member)
    if not members:
        raise ValueError('EMPTY_SOURCE')
    return archive, members


def extract_source(body, destination):
    archive, members = source_members(body)  # Validate everything before the first write.
    destination = Path(destination)
    destination.mkdir(mode=0o700)
    with archive:
        for member in members:
            path = destination / member.name.rstrip('/')
            if member.isdir():
                path.mkdir(mode=0o755, parents=True, exist_ok=True)
            else:
                path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                with path.open('xb') as output, archive.extractfile(member) as source:
                    output.write(source.read())
                path.chmod(0o755 if member.mode & 0o111 else 0o644)


def trusted_dir(path, *, uid=0, gid=0, mode=0o755, new=False):
    path = Path(path)
    if new:
        path.mkdir(mode=mode)
        os.chown(path, uid, gid)
        path.chmod(mode)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, mode)):
        raise ValueError('DIRECTORY_POLICY')


def write_new(path, body, uid=0, gid=0, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as output:
        os.fchown(output.fileno(), uid, gid)
        os.fchmod(output.fileno(), mode)
        output.write(body)
        output.flush()
        os.fsync(output.fileno())


def prepare(package, host):
    global STAGE
    STAGE = 'preflight'
    validate_package(package)
    if os.geteuid() != 0 or package['operation'] != 'prepare' or host.baseline() != package['baseline']:
        raise ValueError('HOST_BASELINE')
    for folder in (ROOT, ROOT/'incoming', ROOT/'releases', ROOT/'receipts'):
        if folder.resolve()!=folder:
            raise ValueError('SYMLINKED_PARENT')
        trusted_dir(folder, mode=0o700)
    trusted_dir(ROOT/'incoming'/package['run_id'],mode=0o700)
    incoming = ROOT / 'incoming' / package['run_id'] / 'runtime-secrets.cms'
    st = incoming.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1
            or not 0 < st.st_size <= 2*1024*1024):
        raise ValueError('CIPHERTEXT_FILE')
    ciphertext = incoming.read_bytes()
    if sha(ciphertext) != package['ciphertext_sha256']:
        raise ValueError('CIPHERTEXT_HASH')
    key = Path('/etc/metainc/naver-deploy-envelope/private.pem')
    st = key.lstat()
    if not stat.S_ISREG(st.st_mode) or (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode), st.st_nlink) != (0,0,0o600,1):
        raise ValueError('ENVELOPE_KEY_POLICY')
    plain = command(['openssl','cms','-decrypt','-binary','-inform','DER','-inkey',str(key)], data=ciphertext)
    if len(plain) > 3*1024*1024:
        raise ValueError('PLAINTEXT_SIZE')
    source, files = validate_payload(json.loads(plain, object_pairs_hook=unique), package['source_commit'], package['source_tar_gz_sha256'])
    source_members(source)[0].close()
    release = ROOT / 'releases' / ('naver-' + package['source_commit'])
    nginx = command(['nginx','-T']).decode()
    users = re.findall(r'(?m)^\s*user\s+([a-zA-Z0-9_-]+)\s*;',nginx)
    if users!=['www-data']:
        raise ValueError('NGINX_WORKER_IDENTITY')
    nginx_gid = pwd.getpwnam(users[0]).pw_gid
    folders = [(SECRET_ROOT,0,0,0o700), (Path('/var/lib/metainc/naver-engine'),10001,10001,0o750),
        (Path('/run/metainc/naver-engine'),10001,10001,0o750),
        (Path('/run/metainc/naver-relay'),10001,nginx_gid,0o750),
        (Path('/var/backups/metainc/naver-engine'),10001,10001,0o700)]
    if release.exists() or any(os.path.lexists(path) for path,_,_,_ in folders):
        raise ValueError('PREEXISTING_RELEASE')
    for path,_,_,_ in folders:
        parent = path.parent
        if not parent.exists():
            trusted_dir(parent, new=True)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode)&0o022:
            raise ValueError('UNSAFE_PARENT')
    STAGE = 'new_files'
    extract_source(source, release)
    for path,uid,gid,mode in folders:
        trusted_dir(path,uid=uid,gid=gid,mode=mode,new=True)
    for item in files:
        write_new(item['path'],item['content'].encode(),item['uid'],item['gid'])
    commit=package['source_commit']
    override='services:\n  naver-engine:\n    image: metainc/naver-engine:'+commit+'\n'
    write_new(release/'preview-engine.override.yml',override.encode())
    override='services:\n  naver-relay:\n    image: metainc/naver-relay:'+commit+'\n    environment:\n      NAVER_AUTO_WEB: "on"\n'
    write_new(release/'preview-relay.override.yml',override.encode())
    for name in ('engine','relay'):
        STAGE = 'build_' + name
        command(['docker','build','--label','metainc.naver.preview.source='+commit,
                 '-t','metainc/naver-'+name+':'+commit,'-f',str(release/('Dockerfile.naver-'+name)),str(release)], timeout=600)
    for name in ('engine','relay'):
        STAGE = 'compose_' + name
        command(compose(release,name)+['config','--quiet'])
    STAGE = 'check_config'
    command(compose(release,'engine')+['run','--rm','--no-deps','naver-engine','python','-m','naver_runtime','check-config'],timeout=60)
    if host.baseline() != package['baseline']:
        raise ValueError('POST_BASELINE')
    receipt={'ok':True,'stage':'prepared','source_commit':commit,'containers_unchanged':True,
             'services_started':False,'nginx_changed':False,'secret_values_exported':False}
    write_new(ROOT/'receipts'/('preview-'+commit+'.json'),json.dumps(receipt,sort_keys=True).encode())
    return receipt


def compose(release,name):
    args=['docker','compose','--project-name','naver-'+name,'-f',str(release/('compose.naver-'+name+'.yml'))]
    if name=='engine':
        args+=['-f',str(release/'deploy/naver-engine-backup.override.yml')]
    return args+['-f',str(release/('preview-'+name+'.override.yml'))]
