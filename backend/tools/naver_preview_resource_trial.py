"""Explicit, source-pinned engine CPU trial. No database or request probes.

This is a temporary Docker limit, not a change to the sealed compose release.
Apply writes a private recovery intent before its sole engine-only update.
Rollback needs that same operation ID and the same running container identity.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat

SOURCE_COMMIT = '7985925dcc4ed9d75c28ae43a456964cdc78c63f'
SOURCE_SHA256 = '47632d4d3403c24dd4988b80c1a0ada25cc155fc6048a7f2413fb72d84ea73ff'
STORE_SHA256 = 'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
OLD_NANO_CPUS, TRIAL_NANO_CPUS, MEMORY_BYTES = 500000000, 1000000000, 536870912
STAGE = 'input'
UPDATE_ATTEMPTED = False
STAGES = frozenset(('input','preflight','write_intent','cpu_update','postflight','write_completion'))
CODES = frozenset('RESOURCE_FIELDS RESOURCE_SOURCE RESOURCE_OPERATION_ID RESOURCE_ACTION '
    'RESOURCE_ROOT RESOURCE_HOST_BASELINE RESOURCE_FILE_POLICY RESOURCE_RECEIPT_SIZE '
    'RESOURCE_SOURCE_NOT_READY RESOURCE_COMPOSE_CHANGED RESOURCE_STORE_CHANGED '
    'RESOURCE_PREPARED_IMAGE RESOURCE_IMAGE_CHANGED RESOURCE_CONTAINER_ID '
    'RESOURCE_CONTAINER_CHANGED RESOURCE_DATA_MOUNT RESOURCE_LIMITS RESOURCE_DEPENDENCY '
    'RESOURCE_ALREADY_ATTEMPTED RESOURCE_RECEIPT_MISSING RESOURCE_RECEIPT_CHANGED '
    'RESOURCE_POST_STATE RESOURCE_LOCK_POLICY RESOURCE_BUSY COMMAND_FAILED'.split())


def failure_report(error):
    code = error.args[0] if len(error.args)==1 and type(error.args[0]) is str else None
    return dict(stage=STAGE if STAGE in STAGES else 'unknown',
        error_kind=type(error).__name__ if type(error).__name__ in
            ('ValueError','RuntimeError','OSError','PermissionError','TimeoutExpired','TimeoutError') else 'OtherError',
        error_code=code if code in CODES else 'UNRECOGNIZED',
        cpu_update_attempted=UPDATE_ATTEMPTED,database_opened=False)


def validate_package(package):
    if type(package) is not dict or set(package)!={'release','operation_id','action'}:
        raise ValueError('RESOURCE_FIELDS')
    expected=dict(source_commit=SOURCE_COMMIT,source_tar_gz_sha256=SOURCE_SHA256,baseline=BASELINE)
    if type(package['release']) is not dict or package['release']!=expected:
        raise ValueError('RESOURCE_SOURCE')
    if type(package['operation_id']) is not str or not re.fullmatch('[0-9a-f]{32}',package['operation_id']):
        raise ValueError('RESOURCE_OPERATION_ID')
    if type(package['action']) is not str or package['action'] not in ('apply','rollback'):
        raise ValueError('RESOURCE_ACTION')
    return package


def read_file(path, *, mode, maximum=32768):
    if path.resolve()!=path:
        raise ValueError('RESOURCE_FILE_POLICY')
    info=path.lstat()
    if (not stat.S_ISREG(info.st_mode) or
            (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode),info.st_nlink)!=(0,0,mode,1)):
        raise ValueError('RESOURCE_FILE_POLICY')
    if not 0<info.st_size<=maximum:
        raise ValueError('RESOURCE_RECEIPT_SIZE')
    return path.read_bytes()


@contextmanager
def resource_lock(release):
    path=release.ROOT/'receipts'/'preview-resource-trial.lock'
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        link=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or
                (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode),info.st_nlink)!=(0,0,0o600,1)
                or (info.st_dev,info.st_ino)!=(link.st_dev,link.st_ino)):
            raise ValueError('RESOURCE_LOCK_POLICY')
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('RESOURCE_BUSY') from None
        yield
    finally:
        os.close(fd)


def json_file(path, release):
    release.trusted_private_file(path)
    return json.loads(read_file(path,mode=0o600),object_pairs_hook=release.unique)


def command(release,args):
    body=release.command(args,timeout=10)
    if not isinstance(body,bytes) or len(body)>16384:
        raise ValueError('RESOURCE_RECEIPT_SIZE')
    return body


def verified_source(package,release):
    path,receipt_path=release.prepared_paths(SOURCE_COMMIT)
    prepared=json_file(receipt_path,release)
    started=json_file(receipt_path.with_name('preview-start-'+SOURCE_COMMIT+'.json'),release)
    if (prepared.get('ok') is not True or prepared.get('stage')!='prepared'
            or prepared.get('source_commit')!=SOURCE_COMMIT
            or any(prepared.get('package',{}).get(k)!=v for k,v in package['release'].items())
            or started.get('ok') is not True or started.get('stage')!='internal_ready'
            or started.get('source_commit')!=SOURCE_COMMIT):
        raise ValueError('RESOURCE_SOURCE_NOT_READY')
    for name in ('compose.naver-engine.yml','preview-engine.override.yml',
                 'deploy/naver-engine-backup.override.yml','compose.naver-relay.yml','preview-relay.override.yml'):
        file=path/name
        body=read_file(file,mode=0o600 if name.startswith('preview-') else 0o644)
        if release.sha(body)!=prepared.get('files',{}).get(str(file)):
            raise ValueError('RESOURCE_COMPOSE_CHANGED')
    if release.sha(read_file(path/'naver_engine/store.py',mode=0o644,maximum=2*1024*1024))!=STORE_SHA256:
        raise ValueError('RESOURCE_STORE_CHANGED')
    for name in ('engine','relay'):
        image=prepared.get('images',{}).get(name)
        if type(image) is not str or not re.fullmatch('sha256:[0-9a-f]{64}',image):
            raise ValueError('RESOURCE_PREPARED_IMAGE')
        fmt='{"id":{{json .Id}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}'
        row=json.loads(command(release,['docker','image','inspect','--format',fmt,'metainc/naver-'+name+':'+SOURCE_COMMIT]))
        if row!={'id':image,'user':'10001:10001','source':SOURCE_COMMIT}:
            raise ValueError('RESOURCE_IMAGE_CHANGED')
    return path,prepared


def container(release,path,prepared,name):
    identity=command(release,release.compose(path,name)+['ps','--all','--quiet']).decode().strip()
    if not re.fullmatch('[0-9a-f]{64}',identity):
        raise ValueError('RESOURCE_CONTAINER_ID')
    fields={'id':'.Id','image':'.Image','running':'.State.Running','user':'.Config.User',
        'project':'(index .Config.Labels "com.docker.compose.project")',
        'service':'(index .Config.Labels "com.docker.compose.service")',
        'source':'(index .Config.Labels "metainc.naver.preview.source")',
        'started':'.State.StartedAt','restarts':'.RestartCount','readonly':'.HostConfig.ReadonlyRootfs'}
    parts=[json.dumps(k)+':{{json '+v+'}}' for k,v in fields.items()]
    if name=='engine':
        limits={'nano_cpus':'NanoCpus','cpu_period':'CpuPeriod','cpu_quota':'CpuQuota','cpu_shares':'CpuShares',
            'cpu_realtime_period':'CpuRealtimePeriod','cpu_realtime_runtime':'CpuRealtimeRuntime',
            'cpuset_cpus':'CpusetCpus','cpuset_mems':'CpusetMems','memory':'Memory','memory_swap':'MemorySwap',
            'memory_reservation':'MemoryReservation','memory_swappiness':'MemorySwappiness',
            'oom_kill_disable':'OomKillDisable','pids_limit':'PidsLimit'}
        parts.append('"oom_killed":{{json .State.OOMKilled}}')
        parts.append('"limits":{'+','.join(json.dumps(k)+':{{json .HostConfig.'+v+'}}' for k,v in limits.items())+'}')
        parts.append('"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}'
            '{"Type":{{json .Type}},"Destination":{{json .Destination}},"Source":{{json .Source}},"RW":{{json .RW}}}{{end}}{{end}}]')
    row=json.loads(command(release,['docker','inspect','--format','{'+','.join(parts)+'}',identity]))
    expected={'id':identity,'image':prepared['images'][name],'running':True,'user':'10001:10001',
        'project':'naver-'+name,'service':'naver-'+name,'source':SOURCE_COMMIT,'readonly':True}
    if (type(row) is not dict or any(row.get(k)!=v for k,v in expected.items())
            or row.get('running') is not True or row.get('readonly') is not True
            or type(row.get('started')) is not str or not re.fullmatch('[0-9TZ:.+-]{20,40}',row['started'])
            or type(row.get('restarts')) is not int or row['restarts']!=0):
        raise ValueError('RESOURCE_CONTAINER_CHANGED')
    if name=='engine':
        if row.get('oom_killed') is not False:
            raise ValueError('RESOURCE_CONTAINER_CHANGED')
        if row.get('data')!=[dict(Type='bind',Destination='/var/lib/naver-engine',Source='/var/lib/metainc/naver-engine',RW=True)]:
            raise ValueError('RESOURCE_DATA_MOUNT')
        caps=row.get('limits')
        if (type(caps) is not dict or set(caps)!=set(limits)
                or any(type(caps.get(k)) is not int or caps[k]!=v for k,v in
                    dict(cpu_period=0,cpu_quota=0,memory=MEMORY_BYTES,pids_limit=64).items())
                or type(caps.get('nano_cpus')) is not int or caps['nano_cpus'] not in (OLD_NANO_CPUS,TRIAL_NANO_CPUS)):
            raise ValueError('RESOURCE_LIMITS')
    return row


def state(release,path,prepared):
    for unit in ('docker.service','metainc-naver-erp-tunnel.service',
                 'metainc-naver-engine.service','metainc-naver-relay.service'):
        if command(release,['/usr/bin/systemctl','show',unit,'-p','ActiveState','--value']).decode().strip()!='active':
            raise ValueError('RESOURCE_DEPENDENCY')
    return dict(engine=container(release,path,prepared,'engine'),relay=container(release,path,prepared,'relay'))


def result_report(package,before,target,updates,release):
    return dict(ok=True,stage='resource_trial_complete',action=package['action'],operation_id=package['operation_id'],
        source_commit=SOURCE_COMMIT,source_archive_sha256=SOURCE_SHA256,store_source_sha256=STORE_SHA256,
        engine_identity_sha256=release.sha(before['engine']['id'].encode()),
        engine_image_sha256=release.sha(before['engine']['image'].encode()),
        before_nano_cpus=before['engine']['limits']['nano_cpus'],after_nano_cpus=target,
        memory_limit_bytes=MEMORY_BYTES,memory_and_other_limits_unchanged=True,relay_unchanged=True,
        existing_app_baseline_unchanged=True,cpu_updates_this_run=updates,
        temporary_container_limit=True,recreate_restores_sealed_limits=True,
        services_restarted=False,source_files_changed=False,database_opened=False,http_calls=0,
        naver_calls=0,secret_values_exported=False)


def run(package,host,release):
    global STAGE,UPDATE_ATTEMPTED
    STAGE,UPDATE_ATTEMPTED='input',False
    validate_package(package)
    STAGE='preflight'
    if os.geteuid()!=0: raise ValueError('RESOURCE_ROOT')
    if host.baseline()!=BASELINE: raise ValueError('RESOURCE_HOST_BASELINE')
    path,prepared=verified_source(package,release)
    with resource_lock(release):
        before=state(release,path,prepared)
        prefix=release.ROOT/'receipts'/('resource-trial-'+package['operation_id'])
        intent_path=prefix.with_suffix('.intent.json')
        done_path=prefix.with_suffix('.'+package['action']+'.json')
        active_path=release.ROOT/'receipts'/'preview-resource-trial.active.json'
        lease=dict(operation_id=package['operation_id'],source_commit=SOURCE_COMMIT,
            engine_identity_sha256=release.sha(before['engine']['id'].encode()))
        if package['action']=='apply':
            if any(os.path.lexists(p) for p in (intent_path,done_path,prefix.with_suffix('.rollback.json'))):
                raise ValueError('RESOURCE_ALREADY_ATTEMPTED')
            if os.path.lexists(active_path): raise ValueError('RESOURCE_BUSY')
            if before['engine']['limits']['nano_cpus']!=OLD_NANO_CPUS:
                raise ValueError('RESOURCE_LIMITS')
            intent=dict(schema=1,package=package,before=before)
            STAGE='write_intent'
            release.write_new(intent_path,json.dumps(intent,sort_keys=True).encode())
            release.write_new(active_path,json.dumps(lease,sort_keys=True).encode())
            target=TRIAL_NANO_CPUS
        else:
            if not os.path.lexists(intent_path): raise ValueError('RESOURCE_RECEIPT_MISSING')
            if os.path.lexists(active_path) and json_file(active_path,release)!=lease:
                raise ValueError('RESOURCE_RECEIPT_CHANGED')
            intent=json_file(intent_path,release)
            if (set(intent)!={'schema','package','before'} or type(intent.get('schema')) is not int or intent.get('schema')!=1
                    or intent.get('package')!=dict(package,action='apply')):
                raise ValueError('RESOURCE_RECEIPT_CHANGED')
            original=intent['before']
            old=dict(before,engine=dict(before['engine'],limits=dict(before['engine']['limits'],nano_cpus=OLD_NANO_CPUS)))
            if json.dumps(original,sort_keys=True)!=json.dumps(old,sort_keys=True):
                raise ValueError('RESOURCE_RECEIPT_CHANGED')
            target=OLD_NANO_CPUS
            if os.path.lexists(done_path):
                done=json_file(done_path,release)
                safe=result_report(package,before,target,done.get('cpu_updates_this_run'),release)
                safe['before_nano_cpus']=done.get('before_nano_cpus')
                if (before!=original or type(done.get('cpu_updates_this_run')) is not int
                        or done['cpu_updates_this_run'] not in (0,1)
                        or type(done.get('before_nano_cpus')) is not int
                        or done['before_nano_cpus'] not in (OLD_NANO_CPUS,TRIAL_NANO_CPUS)
                        or json.dumps(done,sort_keys=True)!=json.dumps(safe,sort_keys=True)):
                    raise ValueError('RESOURCE_RECEIPT_CHANGED')
                STAGE='postflight'
                verified_source(package,release)
                if state(release,path,prepared)!=before or host.baseline()!=BASELINE:
                    raise ValueError('RESOURCE_POST_STATE')
                if os.path.lexists(active_path): active_path.unlink()
                return dict(safe,already_rolled_back=True,cpu_updates_this_run=0)
            if not os.path.lexists(active_path) and before!=original:
                raise ValueError('RESOURCE_RECEIPT_CHANGED')
        expected=dict(before,engine=dict(before['engine'],limits=dict(before['engine']['limits'],nano_cpus=target)))
        updates=0
        if before['engine']['limits']['nano_cpus']!=target:
            STAGE,UPDATE_ATTEMPTED='cpu_update',True
            command(release,['docker','update','--cpus','1.0' if target==TRIAL_NANO_CPUS else '0.5',before['engine']['id']])
            updates=1
        STAGE='postflight'
        after=state(release,path,prepared)
        verified_source(package,release)
        if after!=expected or host.baseline()!=BASELINE:
            raise ValueError('RESOURCE_POST_STATE')
        result=result_report(package,before,target,updates,release)
        STAGE='write_completion'
        release.write_new(done_path,json.dumps(result,sort_keys=True).encode())
        if package['action']=='rollback' and os.path.lexists(active_path):
            if json_file(active_path,release)!=lease: raise ValueError('RESOURCE_RECEIPT_CHANGED')
            active_path.unlink()
        return result
