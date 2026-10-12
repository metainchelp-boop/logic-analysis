"""Pinned saved-export companion for the separate completion release entrypoint.

Only the exact new engine receives the companion. Existing manifests, compose
files, units and V26 routes remain byte-for-byte unchanged. Private export
receipts bind the package and are required again before apply/rollback.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess

PINS = {'plan': {'ops_commit': '19586caf7fe5579e7da70d4a2d4205c3ed603996', 'source_directory': '/root/logic-analysis-deploy/data', 'database_name': 'logic_data.db', 'exporter_user': 'nobody', 'source_group': None, 'python_executable': '/usr/bin/python3'}, 'helper_sha256': '3c39ba6270a964153d66457e0cf809c6f25ea8b3202c7e33e60e7f6568903982', 'scripts': {'naver_product_export.py': '385e11acd17a334f5a52e39663da00336f717f408a6983e7380edc82e043befc', 'naver_market_export.py': '229cdc9926683f6ffa12a7e7933c9cc27c1cac5f61ef5e4720221ee3a0e473a4'}, 'companion_sha256': '4569587ade5f0c6575e7c2504790dbb0efb300b3091d834c2d1471913c499c95'}


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def require_pins():
    if (type(PINS) is not dict or set(PINS)!={'plan','helper_sha256','scripts','companion_sha256'}
        or type(PINS['plan']) is not dict or type(PINS['scripts']) is not dict
        or set(PINS['scripts'])!={'naver_product_export.py','naver_market_export.py'}
        or any(type(v) is not str or re.fullmatch('[0-9a-f]{64}',v) is None for v in
               [PINS['helper_sha256'],PINS['companion_sha256'],*PINS['scripts'].values()])):
        raise ValueError('COMPLETION_EXPORTS_UNPINNED')


COMMAND_STAGES = frozenset(('unit_verify daemon_reload product_start market_start '
    'product_enable market_enable product_show market_show product_enabled market_enabled '
    'product_active market_active product_disable market_disable product_stop market_stop unknown').split())

def command_stage(args):
    if type(args) is not list or any(type(item) is not str for item in args): return 'unknown'
    units = ['/etc/systemd/system/naver-'+kind+'-export.'+suffix
             for kind in ('market','product') for suffix in ('service','timer')]
    if args == ['systemd-analyze','verify',*units]: return 'unit_verify'
    if args == ['systemctl','daemon-reload']: return 'daemon_reload'
    for kind in ('product','market'):
        service='naver-'+kind+'-export.service'; timer='naver-'+kind+'-export.timer'
        for action,tail,stage in (
            ('start',[service],'start'), ('enable',['--now',timer],'enable'),
            ('show',[service,'--property=Result','--property=ExecMainStatus'],'show'),
            ('is-enabled',[timer],'enabled'), ('is-active',[timer],'active'),
            ('disable',['--now',timer],'disable'), ('stop',[service],'stop')):
            if args == ['systemctl',action,*tail]: return kind+'_'+stage
    return 'unknown'

def command_diagnostic(args, error):
    # Diagnostics read only fixed units. Raw output stays in memory and is never
    # attached to an exception, receipt, file or log. No failed start is retried.
    stage=command_stage(args)
    result={'export_command_stage':stage,'export_command_issue':'unknown' if stage=='unknown' else 'command_failed'}
    if isinstance(error,subprocess.TimeoutExpired):
        result['export_command_issue']='command_timeout';return result
    if stage!='unit_verify' and stage not in ('product_start','market_start'):return result
    try:
        if stage=='unit_verify':probe=args
        else:
            unit='naver-'+stage.split('_')[0]+'-export.service'
            current=subprocess.run(['systemctl','show',unit,'--property=InvocationID','--value'],
                capture_output=True,timeout=8,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C'})
            invocation=current.stdout.strip() if type(current.stdout) is bytes else b''
            if current.returncode!=0 or re.fullmatch(b'[0-9a-f]{32}',invocation) is None:return result
            probe=['journalctl','--no-pager','--output=cat','-n','32','-u',unit,
                   '_SYSTEMD_INVOCATION_ID='+invocation.decode('ascii')]
        checked=subprocess.run(probe,capture_output=True,timeout=8,
            env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C'})
        if stage=='unit_verify' and type(checked.returncode) is int and 0<=checked.returncode<=255:
            result['export_command_status']=checked.returncode
        raw=b'\n'.join(body[-32768:] for body in (checked.stdout,checked.stderr) if type(body) is bytes).lower()
        for issue,markers in (
            ('namespace',(b'failed at step namespace',b'failed to set up mount namespacing')),
            ('permission_denied',(b'permission denied',b'access denied')),
            ('missing_file',(b'no such file or directory',b'not a directory')),
            ('disk_full',(b'no space left on device',b'disk quota exceeded')),
            ('unit_syntax',(b'failed to parse',b'invalid argument',b'bad unit file setting',b'unknown lvalue')),
            ('readonly',(b'read-only file system',b'attempt to write a readonly database')),
            ('sqlite_open',(b'unable to open database file',)),
            ('python_import',(b'modulenotfounderror:',b'importerror:'))):
            if any(marker in raw for marker in markers):result['export_command_issue']=issue;break
        del raw
    except Exception:
        pass
    return result


class ReleaseProxy:
    def __init__(self,release,helper,receipt,target):
        self._release=release;self._helper=helper;self._receipt=receipt;self._target=target
    def __getattr__(self,name):return getattr(self._release,name)
    def compose(self,path,name):
        result=self._release.compose(path,name)
        if name=='engine' and Path(path).name=='naver-'+self._target:
            _,folder,_=self._helper._prepared(self._receipt)
            companion=folder/self._helper.COMPANION
            result=result+['-f',str(companion)]
        return result


class Binding:
    def __init__(self,controller,helper,release,helper_source,scripts):
        require_pins()
        if hashlib.sha256(helper_source).hexdigest()!=PINS['helper_sha256']:
            raise ValueError('COMPLETION_EXPORTS_PIN')
        plan=helper.build_plan(**PINS['plan'])
        artifacts=helper.artifacts(plan,scripts,PINS['scripts'])
        if hashlib.sha256(artifacts[helper.COMPANION]).hexdigest()!=PINS['companion_sha256']:
            raise ValueError('COMPLETION_EXPORTS_PIN')
        self.c=controller;self.h=helper;self.r=release;self.plan=plan;self.scripts=scripts
        self.path=release.ROOT/'receipts'/('completion-exports-'+controller.TARGET_COMMIT+'.json')
        self.receipt=None;self._command_failure=None
    def identity(self,package):
        return {'source_commit':self.c.TARGET_COMMIT,'package_sha256':hashlib.sha256(canonical(package)).hexdigest(),
                'pins_sha256':hashlib.sha256(canonical(PINS)).hexdigest()}
    def prepare(self,package):
        identity=self.identity(package)
        self.receipt=self.h.prepare(self.plan,scripts=self.scripts,pins=PINS['scripts'],operation_id=identity['package_sha256'][:32])
        return ReleaseProxy(self.r,self.h,self.receipt,self.c.TARGET_COMMIT)
    def command(self,args):
        try:return self.r.command(args)
        except Exception as error:
            self._command_failure=command_diagnostic(args,error)
            raise
    def operation(self,callback):
        self._command_failure=None
        try:return callback()
        except Exception as error:
            if self._command_failure is not None:
                details=getattr(error,'failure_details',{})
                error.failure_details={**(details if type(details) is dict else {}),**self._command_failure}
            raise
    def install(self):
        if self.receipt is None:raise ValueError('COMPLETION_EXPORTS_RECEIPT')
        self.c.STAGE='saved_exports_install'
        return self.operation(lambda:self.h.install(self.receipt,command=self.command))
    def save(self,package):
        if self.receipt is None:raise ValueError('COMPLETION_EXPORTS_RECEIPT')
        self.r.write_new(self.path,canonical({**self.identity(package),'exports':self.receipt}))
    def load(self,package,*,verify=True):
        self.r.trusted_dir(self.path.parent,mode=0o700)
        self.r.trusted_private_file(self.path)
        raw=self.path.read_bytes()
        if len(raw)>32768:raise ValueError('COMPLETION_EXPORTS_RECEIPT')
        value=json.loads(raw,object_pairs_hook=self.r.unique)
        if (type(value) is not dict or set(value)!={'source_commit','package_sha256','pins_sha256','exports'}
            or {k:value[k] for k in self.identity(package)}!=self.identity(package)):
            raise ValueError('COMPLETION_EXPORTS_RECEIPT')
        self.receipt=value['exports'];self.h._prepared(self.receipt)
        if self.receipt['plan']!=self.plan:raise ValueError('COMPLETION_EXPORTS_RECEIPT')
        if verify:self.operation(lambda:self.h.verify(self.receipt,command=self.command))
        return ReleaseProxy(self.r,self.h,self.receipt,self.c.TARGET_COMMIT)
    def preflight_rollback(self):
        if self.receipt is None:raise ValueError('COMPLETION_EXPORTS_RECEIPT')
        self.h.validate_rollback(self.receipt)
    def rollback(self):
        if self.receipt is not None:
            folder=self.h.STAGING/self.receipt['operation_id']
            if (folder/'installed.json').exists():
                return self.operation(lambda:self.h.rollback(self.receipt,command=self.command))
