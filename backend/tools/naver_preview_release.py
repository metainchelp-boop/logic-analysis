"""Prepare an approved encrypted release; receipt-pinned hashes, existing runtime untouched."""
import base64
import hashlib
import io
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import socket
import stat
import subprocess
import tarfile
import time
import zlib

ROOT = Path('/srv/metainc/ad-deploy-staging')
SECRET_ROOT = Path('/etc/metainc/naver-engine')
SECRET_OWNERS = {'runtime.env': (0, 0), 'backup-recipient.pem': (10001, 10001),
                 'backup-upload-key': (10001, 10001), 'backup-known-hosts': (10001, 10001)}
EXACT = {'.dockerignore', 'Dockerfile.naver-engine', 'Dockerfile.naver-engine.dockerignore', 'Dockerfile.naver-relay', 'Dockerfile.naver-relay.dockerignore',
         'compose.naver-engine.yml', 'compose.naver-relay.yml', 'backend/app/__init__.py',
         'backend/app/naver_entry.py', 'backend/app/naver_relay.py', 'backend/app/routers/naver.py',
         'backend/app/routers/__init__.py', 'backend/requirements.txt'}
PREFIXES = ('naver_engine/', 'naver_runtime/', 'backend/app/naver_auto/', 'backend/naver_page/', 'deploy/')
STAGE = 'input'
CREATED = []


def sha(body):
    return hashlib.sha256(body).hexdigest()


def build_failure_code(args, result):
    """Exact build only; no raw diagnostics."""
    if (not isinstance(args, (list, tuple)) or len(args) != 9
            or not all(isinstance(arg, str) for arg in args)
            or list(args[:3]) != ['docker', 'build', '--label']):
        return 'COMMAND_FAILED'
    match = re.fullmatch(r'metainc\.naver\.preview\.source=([0-9a-f]{40})', args[3])
    if match is None:
        return 'COMMAND_FAILED'
    commit = match.group(1)
    source = ROOT/'releases'/('naver-'+commit)
    if not any(list(args[4:]) == ['-t', 'metainc/naver-'+name+':'+commit, '-f',
            str(source/('Dockerfile.naver-'+name)), str(source)] for name in ('engine', 'relay')):
        return 'COMMAND_FAILED'
    body = b'\n'.join((value or b'')[-65536:] for value in (result.stdout, result.stderr)).lower()
    for code, markers in (
            ('DENIED', (b'permission denied', b'access denied', b'denied:', b'unauthorized',
                        b'authentication required', b'authorization failed', b'403 forbidden')),
            ('TLS', (b'x509:', b'certificate_verify_failed', b'certificate verify failed', b'tls handshake', b'sslerror')),
            ('RATE', (b'toomanyrequests', b'too many requests', b'pull rate limit')),
            ('DISK', (b'no space left on device', b'disk quota exceeded')),
            ('NETWORK', (b'no such host', b'temporary failure in name resolution', b'network is unreachable',
                         b'connection refused', b'connection reset by peer', b'connection timed out', b'i/o timeout')),
            ('STEP', (b'did not complete successfully: exit code:', b'returned a non-zero code:', b'executor failed running'))):
        if any(marker in body for marker in markers):
            return 'DOCKER_BUILD_'+code
    return 'DOCKER_BUILD_UNKNOWN'


def compose_failure_code(args, result):
    """Pinned probes; no raw output."""
    if not isinstance(args, (list, tuple)) or not all(isinstance(arg, str) for arg in args):
        return 'COMMAND_FAILED'
    matched = False
    if len(args) > 5 and list(args[:3]) == ['docker', 'compose', '--project-name']:
        source_match = re.fullmatch(re.escape(str(ROOT/'releases'/'naver-'))+r'([0-9a-f]{40})/compose\.naver-(engine|relay)\.yml', args[5])
        if source_match:
            commit, name = source_match.groups()
            expected = compose(ROOT/'releases'/('naver-'+commit), name)
            if list(args) == expected+['config', '--quiet']:
                matched = True
            elif name == 'engine' and re.fullmatch('naver-check-'+commit+'-[0-9a-f]{32}', args[3]):
                expected[3] = args[3]
                offset = len(expected)
                if (len(args) > offset+1 and args[offset] == '-f' and re.fullmatch(
                        re.escape(str(ROOT/'incoming'))+r'/[0-9]{6,20}/check-config\.override\.yml', args[offset+1])):
                    expected += list(args[offset:offset+2])
                    matched = list(args) == expected+['run','--rm','--no-deps','--pull','never','naver-engine','python','-m','naver_runtime','check-config']
    if not matched:
        return 'COMMAND_FAILED'
    body = b'\n'.join((value or b'')[-65536:] for value in (result.stdout, result.stderr)).lower()
    for code, markers in (
            ('DENIED', (b'permission denied', b'access denied', b'denied:', b'403 forbidden')),
            ('NETWORK_POOL', (b'all predefined address pools have been fully subnetted', b'could not find an available, non-overlapping ipv4 address pool')),
            ('DISK', (b'no space left on device', b'disk quota exceeded')),
            ('MISSING_FILE', (b'no such file or directory', b'not a directory')),
            ('YAML', (b'yaml:', b'failed to parse', b'failed to interpolate', b'validating ')),
            ('CONFIG_REFUSED', (b'"error": "startup-refused"', b'"error":"startup-refused"'))):
        if any(marker in body for marker in markers):
            return 'COMPOSE_PROBE_'+code
    return 'COMPOSE_PROBE_UNKNOWN'


def command(args, *, timeout=45, data=None):
    result = subprocess.run(args, input=data, capture_output=True, timeout=timeout,
                            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
    if result.returncode:
        code = build_failure_code(args, result)
        raise RuntimeError(compose_failure_code(args, result) if code == 'COMMAND_FAILED' else code)
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
    if package['operation'] not in ('prepare', 'start', 'upgrade-prepare'):
        raise ValueError('PACKAGE_OPERATION')
    return package


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_FIELD')
        result[key] = value
    return result


def decode_payload(plain, commit, source_hash):
    """Bounded decode; payload policy unchanged."""
    magic = b'NAVER-PREVIEW-PAYLOAD-GZIP-1\n'
    maximum = 3*1024*1024
    if not isinstance(plain, bytes) or not 0 < len(plain) <= maximum:
        raise ValueError('PLAINTEXT_SIZE')
    if plain.startswith(magic):
        if len(plain) >= 2*1024*1024-4096:
            raise ValueError('PAYLOAD_WIRE_SIZE')
        try:
            decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
            raw = decoder.decompress(plain[len(magic):], maximum+1)
        except zlib.error:
            raise ValueError('PAYLOAD_COMPRESSION') from None
        if len(raw) > maximum or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('PAYLOAD_COMPRESSION')
        plain = raw
    try:
        payload = json.loads(plain, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise ValueError('PAYLOAD_JSON') from None
    return validate_payload(payload, commit, source_hash)


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
    CREATED.append(str(destination))
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
        CREATED.append(str(path))
        os.chown(path, uid, gid)
        path.chmod(mode)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, mode)):
        raise ValueError('DIRECTORY_POLICY')


def write_new(path, body, uid=0, gid=0, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    CREATED.append(str(path))
    with os.fdopen(fd, 'wb') as output:
        os.fchown(output.fileno(), uid, gid)
        os.fchmod(output.fileno(), mode)
        output.write(body)
        output.flush()
        os.fsync(output.fileno())


def trusted_private_file(path):
    path = Path(path)
    if path.resolve() != path:
        raise ValueError('SYMLINKED_PRIVATE_FILE')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode)
            or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink) != (0, 0, 0o600, 1)):
        raise ValueError('PRIVATE_FILE_POLICY')


def prepared_paths(commit):
    release = ROOT/'releases'/('naver-'+commit)
    for folder in (ROOT, ROOT/'releases', ROOT/'receipts', release):
        if folder.resolve() != folder:
            raise ValueError('SYMLINKED_PARENT')
        trusted_dir(folder, mode=0o700)
    receipt_path = ROOT/'receipts'/('preview-'+commit+'.json')
    trusted_private_file(receipt_path)
    return release, receipt_path


def received_ciphertext(path, expected_sha256):
    st = path.lstat()
    if (not stat.S_ISREG(st.st_mode) or (st.st_uid, st.st_gid) not in ((0, 0), (1000, 1000))
            or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1 or not 0 < st.st_size <= 2*1024*1024):
        raise ValueError('CIPHERTEXT_FILE')
    ciphertext = path.read_bytes()
    if sha(ciphertext) != expected_sha256:
        raise ValueError('CIPHERTEXT_HASH')
    # Approved 2026-10-01: only this newly received, verified ciphertext; never runtime secrets.
    if st.st_uid != 0:
        os.chown(path, 0, 0)
    return ciphertext


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
    ciphertext = received_ciphertext(incoming, package['ciphertext_sha256'])
    key = Path('/etc/metainc/naver-deploy-envelope/private.pem')
    if key.parent.resolve() != key.parent:
        raise ValueError('SYMLINKED_ENVELOPE_PARENT')
    trusted_dir(key.parent, mode=0o700)
    trusted_private_file(key)
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
    sealed=dict(receipt)
    sealed['package']={key:value for key,value in package.items() if key!='operation'}
    sealed['images']={name:json.loads(command(['docker','image','inspect','--format','{{json .Id}}',
                                             'metainc/naver-'+name+':'+commit])) for name in ('engine','relay')}
    paths={str(release/'deploy/naver-engine-backup.override.yml')}
    for name in ('engine','relay'):
        paths.update((str(release/('compose.naver-'+name+'.yml')),str(release/('preview-'+name+'.override.yml'))))
    paths.update(item['path'] for item in files)
    sealed['files']={path:sha(Path(path).read_bytes()) for path in sorted(paths)}
    write_new(ROOT/'receipts'/('preview-'+commit+'.json'),json.dumps(sealed,sort_keys=True).encode())
    return receipt


def compose(release,name):
    args=['docker','compose','--project-name','naver-'+name,'-f',str(release/('compose.naver-'+name+'.yml'))]
    if name=='engine':
        args+=['-f',str(release/'deploy/naver-engine-backup.override.yml')]
    return args+['-f',str(release/('preview-'+name+'.override.yml'))]


def unix_request(path, route, method='GET'):
    assets = {'/naver/report-ui.js', '/naver/report-pdf.js'} | {
        '/naver/vendor/report-pdf/'+name for name in (
            'NanumGothic-Regular.ttf.gz', 'pdf-lib-1.17.1.min.js',
            'fontkit-1.1.1.umd.min.js', 'sha256-1.0.0.min.js')}
    maximum = (1024*1024 if method == 'GET' and path == '/run/metainc/naver-relay/relay.sock'
               and route in assets else 65536)
    conn=http.client.HTTPConnection('localhost',timeout=5)
    conn.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    conn.sock.settimeout(5)
    try:
        conn.sock.connect(path)
        conn.request(method,route,headers={'Host':'dashboard.metainc.co.kr','Origin':'https://dashboard.metainc.co.kr',
                                         'X-Real-IP':'127.0.0.1'})
        response=conn.getresponse()
        body=response.read(maximum+1)
        if len(body)>maximum:
            raise ValueError('PROBE_RESPONSE_SIZE')
        return response.status,dict(response.getheaders()),body
    finally:
        conn.close()


def start(package,host):
    global STAGE
    validate_package(package)
    STAGE='start_preflight'
    if os.geteuid()!=0 or package['operation']!='start' or host.baseline()!=package['baseline']:
        raise ValueError('START_BASELINE')
    commit=package['source_commit']
    release, receipt_path=prepared_paths(commit)
    receipt=json.loads(receipt_path.read_text(), object_pairs_hook=unique)
    if receipt.get('stage')!='prepared' or receipt.get('source_commit')!=commit or receipt.get('ok') is not True:
        raise ValueError('NOT_PREPARED')
    if receipt.get('package')!={key:value for key,value in package.items() if key!='operation'}:
        raise ValueError('PREPARED_PACKAGE_MISMATCH')
    for path,value in receipt['files'].items():
        if sha(Path(path).read_bytes())!=value:
            raise ValueError('PREPARED_FILE_CHANGED')
    for name in ('engine','relay'):
        args=compose(release,name)
        if command(args+['ps','--all','--quiet']).strip():
            raise ValueError('PREEXISTING_PREVIEW_CONTAINER')
        marker=command(['docker','image','inspect','--format','{{index .Config.Labels "metainc.naver.preview.source"}}',
                        'metainc/naver-'+name+':'+commit]).decode().strip()
        if marker!=commit:
            raise ValueError('IMAGE_SOURCE_MISMATCH')
        image_id=json.loads(command(['docker','image','inspect','--format','{{json .Id}}','metainc/naver-'+name+':'+commit]))
        if image_id!=receipt['images'].get(name):
            raise ValueError('PREPARED_IMAGE_CHANGED')
    started=[]
    try:
        for name in ('engine','relay'):
            STAGE='start_'+name
            started.append(name)
            command(compose(release,name)+['up','--detach','--no-build'],timeout=90)
        STAGE='internal_probe'
        health=None
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            try:
                status,_,body=unix_request('/run/metainc/naver-engine/engine.sock','/_engine/health')
                candidate=json.loads(body)
                if status==200 and candidate.get('last_tick'):
                    health=candidate
                    break
            except (OSError,ValueError,http.client.HTTPException):
                pass
            time.sleep(1)
        if health is None:
            raise ValueError('ENGINE_NOT_READY')
        if health.get('state')!='ok' or health.get('errors'):
            raise ValueError('ENGINE_INITIAL_SYNC_FAILED')
        relay='/run/metainc/naver-relay/relay.sock'
        page=unix_request(relay,'/naver/')
        if page[0]!=200 or b'verificationNotice' not in page[2]:
            raise ValueError('PAGE_UNAVAILABLE')
        headers={key.lower():value for key,value in page[1].items()}
        if headers.get('referrer-policy')!='no-referrer' or headers.get('cache-control')!='no-store':
            raise ValueError('PAGE_HEADERS')
        if unix_request(relay,'/api/naver-auto/me')[0]!=401:
            raise ValueError('UNAUTHENTICATED_READ_NOT_DENIED')
        for route in ('/issues/1/ack','/settings/thresholds','/links/confirm'):
            if unix_request(relay,'/api/naver-auto'+route,'POST')[0]!=403:
                raise ValueError('BUSINESS_WRITE_NOT_DENIED')
        if host.baseline()!=package['baseline']:
            raise ValueError('POST_BASELINE')
        receipt={'ok':True,'stage':'internal_ready','source_commit':commit,'containers_unchanged':True,
                 'nginx_changed':False,'public_access_enabled':False,'last_tick':health.get('last_tick'),
                 'initial_sync_state':health.get('state'),'unauthenticated_read_status':401,'business_post_status':403}
        write_new(ROOT/'receipts'/('preview-start-'+commit+'.json'),json.dumps(receipt,sort_keys=True).encode())
        return receipt
    except Exception:
        stop_failed=False
        for name in reversed(started):
            try:
                command(compose(release,name)+['stop','--timeout','45'],timeout=60)
            except Exception:
                stop_failed=True
        if stop_failed:
            raise RuntimeError('NEW_SERVICE_STOP_FAILED') from None
        raise
