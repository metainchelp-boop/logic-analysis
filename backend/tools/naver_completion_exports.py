"""Pinned saved-export companion for the separate completion release entrypoint.

Only the exact new engine receives the companion. Existing manifests, compose
files, units and V26 routes remain byte-for-byte unchanged. Private export
receipts bind the package and are required again before apply/rollback.
"""
import hashlib
import json
from pathlib import Path
import re

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
        self.receipt=None
    def identity(self,package):
        return {'source_commit':self.c.TARGET_COMMIT,'package_sha256':hashlib.sha256(canonical(package)).hexdigest(),
                'pins_sha256':hashlib.sha256(canonical(PINS)).hexdigest()}
    def prepare(self,package):
        identity=self.identity(package)
        self.receipt=self.h.prepare(self.plan,scripts=self.scripts,pins=PINS['scripts'],operation_id=identity['package_sha256'][:32])
        return ReleaseProxy(self.r,self.h,self.receipt,self.c.TARGET_COMMIT)
    def install(self):
        if self.receipt is None:raise ValueError('COMPLETION_EXPORTS_RECEIPT')
        return self.h.install(self.receipt,command=self.r.command)
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
        if verify:self.h.verify(self.receipt,command=self.r.command)
        return ReleaseProxy(self.r,self.h,self.receipt,self.c.TARGET_COMMIT)
    def preflight_rollback(self):
        if self.receipt is None:raise ValueError('COMPLETION_EXPORTS_RECEIPT')
        self.h.validate_rollback(self.receipt)
    def rollback(self):
        if self.receipt is not None:
            folder=self.h.STAGING/self.receipt['operation_id']
            if (folder/'installed.json').exists():
                return self.h.rollback(self.receipt,command=self.r.command)
