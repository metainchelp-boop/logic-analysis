"""Pinned upgrade of the two isolated preview services only; no nginx or secret rewrite."""
import http.client
import json
import os
from pathlib import Path
import pwd
import re
import stat
import time
from datetime import datetime, timedelta, timezone

OLD_COMMIT = '607f537b4dad65ae2e937042443d3d727155de1a'
REQUEST = Path('/var/lib/metainc/naver-engine/bootstrap-request.json')
ENVELOPE_KEY = Path('/etc/metainc/naver-deploy-envelope/private.pem')
KST = timezone(timedelta(hours=9))
STAGE = 'input'


def validate_request(request, now=None):
    if not isinstance(request, dict) or set(request) != {'request_id', 'hold_id', 'hold_sha256',
            'expected_rows', 'approved_by', 'expires_at', 'max_seconds'}:
        raise ValueError('REQUEST_FIELDS')
    for key, pattern in (('request_id', '[0-9a-f]{32}'), ('hold_sha256', '[0-9a-f]{64}')):
        if not isinstance(request[key], str) or not re.fullmatch(pattern, request[key]):
            raise ValueError('REQUEST_SHAPE')
    for key, maximum in (('hold_id', 2**63-1), ('expected_rows', 100000), ('max_seconds', 600)):
        if type(request[key]) is not int or not 1 <= request[key] <= maximum:
            raise ValueError('REQUEST_SHAPE')
    if type(request['approved_by']) is not int or request['approved_by'] != 0:
        raise ValueError('REQUEST_APPROVER')
    now = now or datetime.now(timezone.utc)
    try:
        expires = datetime.fromisoformat(request['expires_at'])
        if expires.tzinfo is None or not now < expires <= now+timedelta(hours=3) or expires.astimezone(KST).date() != now.astimezone(KST).date():
            raise ValueError('REQUEST_EXPIRY')
    except (TypeError, ValueError):
        raise ValueError('REQUEST_EXPIRY') from None
    return request


def read_file(path, *, uid=0, gid=0, mode=None, maximum=3*1024*1024):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('FILE_PATH')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (info.st_uid, info.st_gid) != (uid, gid)
                or info.st_mode & 0o022 or (mode is not None and stat.S_IMODE(info.st_mode) != mode)
                or not 0 < info.st_size <= maximum):
            raise ValueError('FILE_POLICY')
        return source.read(maximum+1)


def manifest(release, commit, package=None, started=False):
    path, receipt_path = release.prepared_paths(commit)
    receipt = json.loads(read_file(receipt_path, mode=0o600, maximum=32768), object_pairs_hook=release.unique)
    expected = {str(path/'deploy/naver-engine-backup.override.yml')}
    expected.update(str(path/(prefix+name+suffix)) for name in ('engine', 'relay')
                    for prefix, suffix in (('compose.naver-', '.yml'), ('preview-', '.override.yml')))
    expected.update(str(release.SECRET_ROOT/name) for name in release.SECRET_OWNERS)
    if (receipt.get('ok') is not True or receipt.get('stage') != 'prepared' or receipt.get('source_commit') != commit
            or not isinstance(receipt.get('files'), dict) or set(receipt['files']) != expected
            or not isinstance(receipt.get('images'), dict) or set(receipt['images']) != {'engine', 'relay'}
            or not isinstance(receipt.get('package'), dict) or receipt['package'].get('source_commit') != commit
            or package is not None and receipt['package'] != {k:v for k,v in package.items() if k!='operation'}):
        raise ValueError('PREPARED_MANIFEST')
    for filename, digest in receipt['files'].items():
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('PREPARED_DIGEST')
        file = Path(filename)
        secret = file.parent == release.SECRET_ROOT
        uid, gid = release.SECRET_OWNERS[file.name] if secret else (0, 0)
        if release.sha(read_file(file, uid=uid, gid=gid, mode=0o600 if secret else None)) != digest:
            raise ValueError('PREPARED_FILE_CHANGED')
    for name, digest in receipt['images'].items():
        if not isinstance(digest, str) or not re.fullmatch('sha256:[0-9a-f]{64}', digest):
            raise ValueError('PREPARED_IMAGE')
        fmt = '{"id":{{json .Id}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}'
        image = json.loads(release.command(['docker','image','inspect','--format',fmt,'metainc/naver-'+name+':'+commit]))
        if image != {'id':digest,'user':'10001:10001','source':commit}:
            raise ValueError('PREPARED_IMAGE_CHANGED')
    if started:
        start = receipt_path.with_name('preview-start-'+commit+'.json')
        data = json.loads(read_file(start, mode=0o600, maximum=32768), object_pairs_hook=release.unique)
        if data.get('ok') is not True or data.get('stage') != 'internal_ready' or data.get('source_commit') != commit:
            raise ValueError('SOURCE_NOT_READY')
    return path, receipt


def old_state(package, host, release, lifecycle):
    if os.geteuid()!=0 or host.baseline()!=package['baseline']:
        raise ValueError('HOST_BASELINE')
    path, receipt = manifest(release, OLD_COMMIT, started=True)
    if receipt['package'].get('baseline') != package['baseline']:
        raise ValueError('OLD_BASELINE')
    files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    for parent in (lifecycle.UNIT_DIR, lifecycle.TMPFILES.parent):
        release.trusted_dir(parent)
    for filename, body in files.items():
        if read_file(filename, mode=0o644, maximum=32768) != body:
            raise ValueError('OLD_UNIT_CHANGED')
    for unit in ('docker.service', lifecycle.TUNNEL, *lifecycle.UNITS):
        if lifecycle._state(release, unit, 'ActiveState') != 'active':
            raise ValueError('DEPENDENCY_NOT_ACTIVE')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release, unit, 'UnitFileState') != 'enabled':
            raise ValueError('OLD_UNIT_NOT_ENABLED')
    return path, receipt, files, lifecycle._snapshot(release, path, receipt['images'])


def validate_package(package, release):
    release.validate_package(package)
    if package['operation']!='upgrade-prepare' or package['source_commit']==OLD_COMMIT:
        raise ValueError('UPGRADE_PACKAGE')


def prepare(package, host, release, lifecycle):
    global STAGE
    STAGE='upgrade_preflight'
    validate_package(package, release)
    old = old_state(package, host, release, lifecycle)
    commit=package['source_commit']
    destination=release.ROOT/'releases'/('naver-'+commit)
    receipt_path=release.ROOT/'receipts'/('preview-'+commit+'.json')
    if os.path.lexists(destination) or os.path.lexists(receipt_path):
        raise ValueError('PREEXISTING_RELEASE')
    for folder in (release.ROOT, release.ROOT/'incoming', release.ROOT/'releases', release.ROOT/'receipts',
                   release.ROOT/'incoming'/package['run_id']):
        if folder.resolve()!=folder:
            raise ValueError('SYMLINKED_PARENT')
        release.trusted_dir(folder,mode=0o700)
    incoming=release.ROOT/'incoming'/package['run_id']/'runtime-secrets.cms'
    ciphertext=release.received_ciphertext(incoming,package['ciphertext_sha256'])
    key=ENVELOPE_KEY
    if key.parent.resolve()!=key.parent:
        raise ValueError('SYMLINKED_ENVELOPE_PARENT')
    release.trusted_dir(key.parent,mode=0o700)
    release.trusted_private_file(key)
    plain=release.command(['openssl','cms','-decrypt','-binary','-inform','DER','-inkey',str(key)],data=ciphertext)
    if len(plain)>3*1024*1024:
        raise ValueError('PLAINTEXT_SIZE')
    source, files=release.validate_payload(json.loads(plain,object_pairs_hook=release.unique),commit,package['source_tar_gz_sha256'])
    release.source_members(source)[0].close()
    for item in files:
        if read_file(item['path'],uid=item['uid'],gid=item['gid'],mode=0o600) != item['content'].encode():
            raise ValueError('RUNTIME_SECRET_CHANGED')
    STAGE='upgrade_prepare_files'
    release.extract_source(source,destination)
    overrides={
        'engine': 'services:\n  naver-engine:\n    image: metainc/naver-engine:'+commit+'\n    environment:\n      NAVER_ENGINE_BOOTSTRAP_REQUEST: /var/lib/naver-engine/bootstrap-request.json\n',
        'relay': 'services:\n  naver-relay:\n    image: metainc/naver-relay:'+commit+'\n    environment:\n      NAVER_AUTO_WEB: "on"\n'}
    for name, body in overrides.items():
        release.write_new(destination/('preview-'+name+'.override.yml'),body.encode())
    for name in ('engine','relay'):
        STAGE='upgrade_build_'+name
        release.command(['docker','build','--label','metainc.naver.preview.source='+commit,'-t','metainc/naver-'+name+':'+commit,
                         '-f',str(destination/('Dockerfile.naver-'+name)),str(destination)],timeout=600)
        release.command(release.compose(destination,name)+['config','--quiet'])
    STAGE='upgrade_check_config'
    release.command(release.compose(destination,'engine')+['run','--rm','--no-deps','naver-engine','python','-m','naver_runtime','check-config'],timeout=60)
    if old_state(package,host,release,lifecycle) != old:
        raise ValueError('OLD_STATE_CHANGED')
    images={name:json.loads(release.command(['docker','image','inspect','--format','{{json .Id}}','metainc/naver-'+name+':'+commit])) for name in ('engine','relay')}
    paths={str(destination/'deploy/naver-engine-backup.override.yml')}
    paths.update(str(destination/(prefix+name+suffix)) for name in ('engine','relay') for prefix,suffix in
                 (('compose.naver-','.yml'),('preview-','.override.yml')))
    paths.update(item['path'] for item in files)
    receipt={'ok':True,'stage':'prepared','source_commit':commit,'containers_unchanged':True,'services_started':False,
             'nginx_changed':False,'secret_values_exported':False,'package':{k:v for k,v in package.items() if k!='operation'},
             'images':images,'files':{path:release.sha(Path(path).read_bytes()) for path in sorted(paths)}}
    release.write_new(receipt_path,json.dumps(receipt,sort_keys=True).encode())
    manifest(release,commit,package)
    return {key:receipt[key] for key in ('ok','stage','source_commit','containers_unchanged','services_started','nginx_changed','secret_values_exported')}


def replace_unit(path, expected, body, request_id, release):
    if read_file(path,mode=0o644,maximum=32768)!=expected:
        raise ValueError('UNIT_CHANGED')
    temporary=path.with_name('.naver-upgrade-'+request_id+'-'+path.name)
    release.write_new(temporary,body,mode=0o644)
    if read_file(path,mode=0o644,maximum=32768)!=expected:
        raise ValueError('UNIT_CHANGED')
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def probe(release):
    deadline=time.monotonic()+45
    while True:
        try:
            status,_,body=release.unix_request('/run/metainc/naver-engine/engine.sock','/_engine/health')
            if status==503:
                raise OSError('NOT_READY')
            if status!=200 or not isinstance(json.loads(body),dict):
                raise ValueError('ENGINE_NOT_READY')
            relay='/run/metainc/naver-relay/relay.sock'
            status,headers,body=release.unix_request(relay,'/naver/')
            if status==503:
                raise OSError('NOT_READY')
            headers={key.lower():value for key,value in headers.items()}
            if status!=200 or b'verificationNotice' not in body or headers.get('referrer-policy')!='no-referrer' or headers.get('cache-control')!='no-store':
                raise ValueError('PAGE_NOT_READY')
            if release.unix_request(relay,'/api/naver-auto/me')[0]!=401:
                raise ValueError('UNAUTHENTICATED_READ_NOT_DENIED')
            for route in ('/issues/1/ack','/settings/thresholds','/links/confirm'):
                if release.unix_request(relay,'/api/naver-auto'+route,'POST')[0]!=403:
                    raise ValueError('BUSINESS_WRITE_NOT_DENIED')
            return
        except (OSError,http.client.HTTPException):
            pass
        if time.monotonic()>=deadline:
            raise ValueError('SERVICES_NOT_READY')
        time.sleep(1)


def apply(package,host,release,lifecycle):
    global STAGE
    STAGE='upgrade_apply_preflight'
    if not isinstance(package,dict) or set(package)!={'release','request'}:
        raise ValueError('APPLY_FIELDS')
    prepared,request=package['release'],validate_request(package['request'])
    validate_package(prepared,release)
    old_path,old_receipt,old_files,_=old_state(prepared,host,release,lifecycle)
    path,receipt=manifest(release,prepared['source_commit'],prepared)
    new_files=lifecycle.unit_files(path,pwd.getpwnam('www-data').pw_gid,release)
    if new_files[lifecycle.TMPFILES]!=old_files[lifecycle.TMPFILES]:
        raise ValueError('TMPFILES_CHANGED')
    if REQUEST.parent.resolve()!=REQUEST.parent:
        raise ValueError('REQUEST_PARENT')
    release.trusted_dir(REQUEST.parent,uid=10001,gid=10001,mode=0o750)
    started_path=release.ROOT/'receipts'/('preview-start-'+prepared['source_commit']+'.json')
    backup=release.ROOT/'receipts'/('upgrade-'+request['request_id']+'.json')
    if any(os.path.lexists(p) for p in (REQUEST,started_path,backup)):
        raise ValueError('UPGRADE_ALREADY_ATTEMPTED')
    release.write_new(backup,json.dumps({'source_commit':OLD_COMMIT,'units':{str(p):v.decode() for p,v in old_files.items() if p!=lifecycle.TMPFILES}},sort_keys=True).encode())
    release.write_new(REQUEST,json.dumps(request,sort_keys=True).encode(),uid=0,gid=10001,mode=0o440)
    validate_request(request)
    stopped=False
    replaced=[]
    try:
        STAGE='upgrade_stop_isolated'
        stopped=True
        for unit in reversed(lifecycle.UNITS):
            release.command(['/usr/bin/systemctl','stop',unit],timeout=90)
        STAGE='upgrade_create_isolated'
        for name in ('engine','relay'):
            release.command(release.compose(path,name)+['up','--no-start','--no-build','--force-recreate'],timeout=90)
        STAGE='upgrade_replace_units'
        for unit in lifecycle.UNITS:
            target=lifecycle.UNIT_DIR/unit
            replaced.append(target)
            replace_unit(target,old_files[target],new_files[target],request['request_id'],release)
        release.command(['/usr/bin/systemctl','daemon-reload'])
        for unit in lifecycle.UNITS:
            release.command(['/usr/bin/systemctl','start',unit],timeout=90)
        STAGE='upgrade_verify'
        probe(release)
        lifecycle._snapshot(release,path,receipt['images'])
        if host.baseline()!=prepared['baseline']:
            raise ValueError('POST_BASELINE')
        result={'ok':True,'stage':'internal_ready','source_commit':prepared['source_commit'],
                'nginx_changed':False,'legacy_containers_unchanged':True,'bootstrap_completion_not_asserted':True,
                'request_id':request['request_id'],'unauthenticated_read_status':401,'business_post_status':403}
        release.write_new(started_path,json.dumps(result,sort_keys=True).encode())
        return result
    except Exception:
        STAGE='upgrade_rollback'
        failed=False
        def attempt(function,*args,**kwargs):
            nonlocal failed
            try:
                function(*args,**kwargs)
                return True
            except Exception:
                failed=True
                return False
        def restore_unit(target):
            if read_file(target,mode=0o644,maximum=32768)!=old_files[target]:
                replace_unit(target,new_files[target],old_files[target],request['request_id']+'-rollback',release)
        if stopped:
            for unit in reversed(lifecycle.UNITS):
                attempt(release.command,['/usr/bin/systemctl','stop',unit],timeout=90)
            for target in reversed(replaced):
                attempt(restore_unit,target)
            if attempt(manifest,release,OLD_COMMIT,started=True):
                for name in ('engine','relay'):
                    attempt(release.command,release.compose(old_path,name)+['up','--no-start','--no-build','--force-recreate'],timeout=90)
            attempt(release.command,['/usr/bin/systemctl','daemon-reload'])
            # Relay Requires=engine; starting either after an incomplete rollback could
            # restart a new container under an old unit. Leave both stopped on any failure.
            if not failed:
                for unit in lifecycle.UNITS:
                    if not attempt(release.command,['/usr/bin/systemctl','start',unit],timeout=90):
                        break
                attempt(lifecycle._snapshot,release,old_path,old_receipt['images'])
            try:
                if host.baseline()!=prepared['baseline']:
                    failed=True
            except Exception:
                failed=True
        if failed:
            raise RuntimeError('UPGRADE_ROLLBACK_FAILED') from None
        raise RuntimeError('UPGRADE_FAILED_ROLLED_BACK_DB_PRESERVED') from None
