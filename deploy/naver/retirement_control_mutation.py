#!/usr/bin/env python3
"""Fixed retirement controls. All execution is blocked until reviewed proof pins exist.

No container/file/volume removal, direct host kill, cgroup kill or unpause path.
Only selected nginx blocks, two restart policies and a proven final KILL are mutable.
"""
import argparse
import contextlib
import ctypes
import datetime
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time
import types

SESSION='data-snapshot-20261102-v1'
BASE='/root/.metainc-retirement-control/'+SESSION
# Only transport changes: the frozen snapshot and original fence keep their session.
TRANSFER_SESSION='data-snapshot-continuation-20261102-v1'
TRANSFER='/root/.metainc-retirement-transfer/'+TRANSFER_SESSION+'/transfer-receipt.json'
CONTROL_SHA='16483b62c97d6780e8a7b04ffde9a445aa8b14f75b8f2a29ca6285036238dcb0'
PREFLIGHT_SHA='562582ebf91b82c84f6a728bd2fd2afd9a7cc59d8346deb40b110c20578fec8c'
ARCHIVE_SHA='d1e61d7a51e1ec955625ef03ce312cf5299630718615479bd20d09a0630ad269'
OPERATOR_DOCUMENT={'actor': 'metainchelp-boop', 'checked_at': '2026-11-02T07:06:25.189157+00:00', 'other_workflows': [{'id': 267160662, 'path': '.github/workflows/validate.yml', 'state': 'active'}], 'other_workflows_unchanged': True, 'repository': 'metainchelp-boop/metainc-content-studio', 'schema': 1, 'session': 'data-snapshot-20261102-v1', 'status': 'known_deployments_disabled', 'workflows': [{'active_runs': 0, 'after': 'disabled_manually', 'before': 'active', 'id': 265254896, 'path': '.github/workflows/deploy.yml'}, {'active_runs': 0, 'after': 'disabled_manually', 'before': 'active', 'id': 322623002, 'path': '.github/workflows/deploy-autobid.yml'}]}
OPERATOR_SHA='9069e12e55d6c2a3b9ade3ef95b451d3ed6aac084a5e32319948b59a556455ba'
SEND_SHA='1518e95f2f14dc82354bb1979f2691a0074f0a6453a289473e3d030a80f52b24'
LOCAL_RESTORE_SHA='b26844ab0dfdb1bf4a2bf69326cbb0d653405e147ad805771a0f51047e657985'
SEMANTICS_SHA='7e8d0e90596ae941855e6cc966a8f418a075dcb7057530213fb0a86d0436003a'
# Exact public control facts from workflow41403670586; no private body.
PROTECTED=[{'id': 'e6014922a842d9f9a699182510aa47363cef4e12b09bcb338e8cd49f3bf1785f', 'image': 'sha256:e4650c343f7395068d551138ba9d1ae963fff28b203542457d683814862fca28'}, {'id': '1141302033f38224116e03506edf33d9279f2b6633df30d330721f808cdc624f', 'image': 'sha256:171e5bb8aa1673c3d1e0aefa7c48f1e1f72201f2b93c2dcdeb2f9d3134523960'}, {'id': '1d6f986d95a2c1fce2aaeac7a872edaf4e8519e9c99acddebc1cc3a0d6e48291', 'image': 'sha256:3b75795280e53fae096a26b735bd324c7ba76e7aa1d5c4b8a76ed5b7569b195a'}]
POLICY={'request': {'ad': {'id': '6f37ec7da0dea75b4630fd177ff0f51ae0087e6b310d68df5a6e6803c015890f', 'pid': 1679637}, 'content': {'id': '740ea62adf12d41571a1297ea4bb623ca62177f1c4def4d2c290f7b5ee07c9b5', 'pid': 1669091}}, 'files': [{'aliases': ['ad'], 'enabled_paths': ['/etc/nginx/sites-enabled/ad.metainc.co.kr'], 'locations': [{'end': 745, 'modifier': '', 'path': '/', 'sha256': '375cef8b18bbe4ee9d11c3fcdbddd36e330512ca224de8c17ec0346201b7e967', 'start': 422}], 'matching_servers': 1, 'metadata': {'bytes': 4700, 'device': 64769, 'gid': 0, 'inode': 917201, 'links': 1, 'mode': 420, 'uid': 0}, 'protected_bytes_sha256': '4878a9972995b66863aa5b9ac8134fb7bab0bef3a99fbd263d5d421fde5ce990', 'protected_locations': [{'end': 1992, 'modifier': '=', 'path': '/naver', 'sha256': 'c29741ab74b50d2179157602480e5db9c5099192455f73844c6109341eff97f9', 'start': 1221}, {'end': 2770, 'modifier': '^~', 'path': '/naver/', 'sha256': 'da371418392851ab2f0a8f2d6c5c74d5034b3a3f1ad424fb0fb2f6a5a480f8b3', 'start': 1997}, {'end': 3555, 'modifier': '=', 'path': '/api/naver-auto', 'sha256': '779f650946aeaa333da7c8ba6fdc779d1c548fc65298142af9e872c5137afa5d', 'start': 2775}, {'end': 4342, 'modifier': '^~', 'path': '/api/naver-auto/', 'sha256': '07fcc86d58e48eebd268210f1416e259597b1923204a9d53eae39c123f65d819', 'start': 3560}], 'resolved_path': '/etc/nginx/sites-available/ad.metainc.co.kr', 'sha256': 'f48e0a389974d3b070f9c132d65bf9a776f289541ac5def778936496cd11a89c'}, {'aliases': ['logic'], 'enabled_paths': ['/etc/nginx/sites-enabled/logic-analysis'], 'locations': [{'end': 1464, 'modifier': '=', 'path': '/autobid', 'sha256': 'aead532583115a336d5786a7c37370f64937addf9f9e2e094d1c6e5d7d41ef6a', 'start': 1419}, {'end': 1730, 'modifier': '', 'path': '/autobid/', 'sha256': 'c5df16221f8339254fdbc56827dc8d060be14ed614a89ee8da2dc3eff75b648e', 'start': 1469}, {'end': 3036, 'modifier': '', 'path': '/studio/', 'sha256': '83ed22a01d892d593f7b99fb6dd4a8cd6da8e94c5c170e15b85f2c21c549f407', 'start': 2370}, {'end': 3096, 'modifier': '=', 'path': '/studio', 'sha256': '37f35efee5a022d8da4eba70d180903e258e62c87b1cb0e10ba9e34c09cad45f', 'start': 3041}], 'matching_servers': 1, 'metadata': {'bytes': 3099, 'device': 64769, 'gid': 0, 'inode': 917065, 'links': 1, 'mode': 420, 'uid': 0}, 'protected_bytes_sha256': '892890bfb2ed64ac46ca8f5ca941454e254f2b2e9b82b7de1439c7f36fcb9c93', 'protected_locations': [], 'resolved_path': '/etc/nginx/sites-enabled/logic-analysis', 'sha256': 'a8c1a4f6e2c2012aacdf73ba04dd0082ad8c0eeb5685b43e345d838e2b1e3aea'}, {'aliases': ['studio'], 'enabled_paths': ['/etc/nginx/sites-enabled/studio.metainc.co.kr.conf'], 'locations': [{'end': 891, 'modifier': '', 'path': '/', 'sha256': '3fba238fa0f3633f14fc74d726331aa3e292e582e936fbab854b0cb87bb1558b', 'start': 235}], 'matching_servers': 1, 'metadata': {'bytes': 894, 'device': 64769, 'gid': 0, 'inode': 947735, 'links': 1, 'mode': 420, 'uid': 0}, 'protected_bytes_sha256': '1d93ca0b112f10f5cbcf992a1023cf7e850c3b0293a63477087cd39a326002c4', 'protected_locations': [], 'resolved_path': '/etc/nginx/sites-available/studio.metainc.co.kr.conf', 'sha256': '4db230394a0609739da7516084e3a2b7960cc8a8056914d1d804c5a12f4ecf22'}], 'protected': [{'id': 'e6014922a842d9f9a699182510aa47363cef4e12b09bcb338e8cd49f3bf1785f', 'image': 'sha256:e4650c343f7395068d551138ba9d1ae963fff28b203542457d683814862fca28'}, {'id': '1141302033f38224116e03506edf33d9279f2b6633df30d330721f808cdc624f', 'image': 'sha256:171e5bb8aa1673c3d1e0aefa7c48f1e1f72201f2b93c2dcdeb2f9d3134523960'}, {'id': '1d6f986d95a2c1fce2aaeac7a872edaf4e8519e9c99acddebc1cc3a0d6e48291', 'image': 'sha256:3b75795280e53fae096a26b735bd324c7ba76e7aa1d5c4b8a76ed5b7569b195a'}]}
LOCAL_RESTORE_EXPECTED=None
SOURCE_RUN='41417973833-1'
FIXED_IMAGES={"ad":"sha256:959001525d45612e0c5cc1045291c7b6caefa768c14d37cc1070c26584cb8922","content":"sha256:b52374a33084ea20386af2380478a38cff92eebdbeff97c616ad7d80a112a0dc"}
FIXED_NAMES={"ad":"/ad-api","content":"/content-studio"}
MAX_SOURCE=2147483648
MAX_ARCHIVE=2283523072
MAX_CIPHER=2300300288
MAX_OBJECTS=100080
HEX=re.compile(r'[0-9a-f]{64}\Z')
RUN=re.compile(r'[1-9][0-9]{0,19}-1\Z')
DIR=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
READ=os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','LC_ALL':'C'}
PHASES=('fence','maintenance','stop')


class Refused(Exception):
    def __init__(self,code):self.code=code


def require(value,code):
    if not value:raise Refused(code)


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'json_refused');result[key]=value
    return result


def decode(body):
    try:return json.loads(body,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(Refused('json_refused')))
    except (ValueError,UnicodeError,RecursionError):raise Refused('json_refused') from None


def digest(body):return hashlib.sha256(body).hexdigest()


def pin(value):require(isinstance(value,str) and HEX.fullmatch(value) and value!='0'*64,'proof_not_pinned')


def fields(value,names):require(isinstance(value,dict) and set(value)==set(names.split()),'proof_refused')


def integer(value,high=2**32-1):return type(value) is int and 0<=value<=high


def stamp(value):
    return value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_gid,value.st_nlink,value.st_size,value.st_mtime_ns,value.st_ctime_ns


def cfg_path(value):
    require(isinstance(value,str) and re.fullmatch(r'/etc/nginx/sites-(?:enabled|available)/[A-Za-z0-9._-]{1,96}',value) and value.rsplit('/',1)[1] not in ('.','..'),'config_path_refused')
    return value


class Files:
    """Alternate filesystem/owner/exchange are synthetic adapters, never CLI inputs."""
    def __init__(self,base='/',uid=0,gid=0,exchange=None,staging=None):
        self.base,self.uid,self.gid,self.exchanger=base,uid,gid,exchange
        require(staging is None or isinstance(staging,str) and re.fullmatch(r'/tmp/metainc-control-mutation-[1-9][0-9]{0,19}-1',staging),'path_refused')
        self.staging=staging
    @contextlib.contextmanager
    def directory(self,path):
        require(isinstance(path,str) and path.startswith('/') and all(p not in ('.','..') for p in path.split('/')),'path_refused')
        with contextlib.ExitStack() as stack:
            fd=os.open(self.base,DIR);stack.callback(os.close,fd);chain=[]
            parts=list(filter(None,path.split('/')))
            scoped_staging=self.staging is not None and path==self.staging
            for index,name in enumerate(parts):
                before=os.stat(name,dir_fd=fd,follow_symlinks=False)
                # /tmp is traversable only toward this helper's exact run staging.
                # Its sticky parent never grants access to another /tmp child.
                if scoped_staging and index==0 and name=='tmp':
                    expected_uid,expected_gid=(0,0) if self.base=='/' else (self.uid,self.gid)
                    allowed=before.st_uid==expected_uid and before.st_gid==expected_gid and stat.S_IMODE(before.st_mode)==0o1777
                else:
                    allowed=before.st_uid==self.uid and before.st_gid==self.gid and not before.st_mode&0o022
                    if scoped_staging:allowed=allowed and stat.S_IMODE(before.st_mode)==0o700
                require(stat.S_ISDIR(before.st_mode) and allowed,'directory_refused')
                child=os.open(name,DIR,dir_fd=fd);stack.callback(os.close,child)
                require(stamp(os.fstat(child))[:5]==stamp(before)[:5],'path_changed')
                chain.append((fd,name,child,stamp(before)[:5]));fd=child
            yield fd
            for parent,name,child,expected in chain:
                require(stamp(os.stat(name,dir_fd=parent,follow_symlinks=False))[:5]==expected and stamp(os.fstat(child))[:5]==expected,'path_changed')
    def read(self,path,limit=8192,private=False):
        parent,name=path.rsplit('/',1)
        with self.directory(parent) as fd:
            before=os.stat(name,dir_fd=fd,follow_symlinks=False)
            require(stat.S_ISREG(before.st_mode) and before.st_uid==self.uid and before.st_gid==self.gid and
                    before.st_nlink==1 and not before.st_mode&0o022 and before.st_size<=limit and
                    (not private or stat.S_IMODE(before.st_mode)==0o600),'file_refused')
            child=os.open(name,READ,dir_fd=fd)
            try:
                require(stamp(os.fstat(child))==stamp(before),'path_changed');body=bytearray()
                while True:
                    block=os.read(child,min(65536,limit+1-len(body)))
                    if not block:break
                    body.extend(block);require(len(body)<=limit,'file_limit')
                require(stamp(os.fstat(child))==stamp(before) and stamp(os.stat(name,dir_fd=fd,follow_symlinks=False))==stamp(before),'path_changed')
                return bytes(body),stamp(before)
            finally:os.close(child)
    def absent(self,path):
        parent,name=path.rsplit('/',1)
        with self.directory(parent) as fd:
            try:os.stat(name,dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError:return True
            return False
    def mkdir(self,path,existing=False):
        parent,name=path.rsplit('/',1)
        with self.directory(parent) as fd:
            try:os.mkdir(name,0o700,dir_fd=fd)
            except FileExistsError:require(existing,'journal_exists')
            with self.directory(path) as child:require(stat.S_IMODE(os.fstat(child).st_mode)==0o700,'directory_refused')
            os.fsync(fd)
    def initialize(self):
        self.mkdir('/root/.metainc-retirement-control',True);self.mkdir(BASE,True)
    @contextlib.contextmanager
    def lock(self):
        with self.directory(BASE) as parent:
            fd=os.open('control.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
            try:
                info=os.fstat(fd)
                require(stat.S_ISREG(info.st_mode) and info.st_uid==self.uid and info.st_gid==self.gid and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600,'lock_refused')
                try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise Refused('lock_busy') from None
                require(stamp(os.stat('control.lock',dir_fd=parent,follow_symlinks=False))==stamp(info),'path_changed')
                os.fsync(parent);yield
            finally:os.close(fd)
    def write(self,path,body,mode=0o600):
        parent,name=path.rsplit('/',1)
        with self.directory(parent) as folder:
            fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,mode,dir_fd=folder)
            try:
                view=memoryview(body)
                while view:
                    count=os.write(fd,view);require(count>0,'write_failed');view=view[count:]
                os.fchmod(fd,mode);os.fsync(fd)
            finally:os.close(fd)
            os.fsync(folder)
        actual,identity=self.read(path,max(8192,len(body)));require(actual==body,'write_failed');return identity
    def exchange(self,folder,left,right):
        if self.exchanger:return self.exchanger(folder,left,right)
        library=ctypes.CDLL(None,use_errno=True)
        try:rename=library.renameat2
        except AttributeError:raise Refused('exchange_unavailable') from None
        rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];rename.restype=ctypes.c_int
        require(rename(folder,left.encode(),folder,right.encode(),2)==0,'exchange_failed')
        os.fsync(folder)
    def swap(self,path,candidate,expected_body,expected_identity,new_body):
        body,current=self.read(path,262144)
        require(body==expected_body and current==expected_identity,'configuration_changed')
        mode=stat.S_IMODE(expected_identity[2]);self.write(candidate,new_body,mode)
        parent,name=path.rsplit('/',1);other=candidate.rsplit('/',1)[1]
        require(candidate.rsplit('/',1)[0]==parent,'config_path_refused')
        with self.directory(parent) as folder:
            body,current=self.read(path,262144)
            require(body==expected_body and current==expected_identity,'configuration_changed')
            # Exchange preserves a concurrently changed original instead of
            # overwriting it. Both original and candidate remain recoverable.
            new_identity=stamp(os.stat(other,dir_fd=folder,follow_symlinks=False))
            try:
                self.exchange(folder,other,name)
                old,old_identity=self.read(candidate,262144)
                now,now_identity=self.read(path,262144)
                require(old==expected_body and old_identity[:8]==expected_identity[:8] and now==new_body and now_identity[:8]==new_identity[:8],'configuration_changed')
            except BaseException:
                # Restore only while the installed candidate is still our inode.
                current=os.stat(name,dir_fd=folder,follow_symlinks=False)
                if (current.st_dev,current.st_ino)==new_identity[:2]:self.exchange(folder,other,name)
                raise
        return {'path':path,'candidate':candidate,'old_sha256':digest(expected_body),'new_sha256':digest(new_body),
                'old_identity':old_identity,'new_identity':now_identity}
    def rollback(self,record):
        before,old=self.read(record['candidate'],262144);now,current=self.read(record['path'],262144)
        require(digest(before)==record['old_sha256'] and digest(now)==record['new_sha256'] and
                old==tuple(record['old_identity']) and current==tuple(record['new_identity']),'rollback_changed')
        parent,name=record['path'].rsplit('/',1)
        with self.directory(parent) as folder:self.exchange(folder,record['candidate'].rsplit('/',1)[1],name)
        require(digest(self.read(record['path'],262144)[0])==record['old_sha256'],'rollback_failed')


@contextlib.contextmanager
def cleanup_signals():
    numbers=(signal.SIGINT,signal.SIGHUP,signal.SIGTERM,signal.SIGALRM);previous={}
    mask=signal.pthread_sigmask(signal.SIG_BLOCK,numbers)
    try:
        for number in numbers:previous[number]=signal.signal(number,signal.SIG_IGN)
    finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
    try:yield
    finally:
        mask=signal.pthread_sigmask(signal.SIG_BLOCK,numbers)
        try:
            for number,handler in previous.items():signal.signal(number,handler)
        finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)


def registered(factory,records):
    """Do not expose a completed swap before rollback owns its result."""
    numbers=(signal.SIGINT,signal.SIGHUP,signal.SIGTERM,signal.SIGALRM);pending=[];previous={}
    mask=signal.pthread_sigmask(signal.SIG_BLOCK,numbers)
    try:
        for number in numbers:previous[number]=signal.signal(number,lambda number,frame:pending.append(number))
    finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
    try:
        result=factory();records.append(result)
    finally:
        mask=signal.pthread_sigmask(signal.SIG_BLOCK,numbers)
        try:
            for number,handler in previous.items():signal.signal(number,handler)
        finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
    require(not pending,'interrupted');return result


def command(argv,limit=16384,timeout=30):
    child=None;previous={};state={'spawning':False,'pending':False};raw=bytearray();errors=0
    def stop(*_):
        state['pending']=True
        for number in previous:signal.signal(number,signal.SIG_IGN)
        if not state['spawning']:raise Refused('interrupted')
    try:
        numbers=(signal.SIGINT,signal.SIGHUP,signal.SIGTERM,signal.SIGALRM)
        mask=signal.pthread_sigmask(signal.SIG_BLOCK,numbers)
        try:
            for number in numbers:
                previous[number]=signal.getsignal(number)
                if previous[number]!=signal.SIG_IGN:signal.signal(number,stop)
        finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
        state['spawning']=True
        try:child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env=ENV,shell=False,start_new_session=True)
        finally:state['spawning']=False
        require(not state['pending'],'interrupted');end=time.monotonic()+timeout
        with selectors.DefaultSelector() as selected:
            selected.register(child.stdout,selectors.EVENT_READ,True);selected.register(child.stderr,selectors.EVENT_READ,False)
            while selected.get_map():
                require(time.monotonic()<end,'command_timeout')
                for key,_ in selected.select(min(.2,max(.001,end-time.monotonic()))):
                    block=os.read(key.fd,8192)
                    if not block:selected.unregister(key.fileobj);continue
                    if key.data:raw.extend(block);require(len(raw)<=limit,'command_limit')
                    else:errors+=len(block);require(errors<=65536,'command_limit')
        return bytes(raw),child.wait(timeout=max(.01,end-time.monotonic()))
    finally:
        mask=signal.pthread_sigmask(signal.SIG_BLOCK,tuple(previous))
        try:
            for number in previous:signal.signal(number,signal.SIG_IGN)
        finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
        safe=True
        try:
            if child is not None:
                try:
                    if child.poll() is None:
                        try:os.killpg(child.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                except OSError:safe=False
                try:child.wait(timeout=5)
                except Exception:safe=False
                for stream in (child.stdout,child.stderr):
                    try:stream.close()
                    except Exception:safe=False
            require(safe,'child_cleanup_failed')
        finally:
            mask=signal.pthread_sigmask(signal.SIG_BLOCK,tuple(previous))
            try:
                for number,handler in previous.items():signal.signal(number,handler)
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)


class Docker:
    def __init__(self,config,runner=command):self.config,self.runner=config,runner
    def run(self,*args,limit=16384):
        raw,code=self.runner(['/usr/bin/docker','--host','unix:///var/run/docker.sock','--config',self.config,*args],limit=limit)
        require(code==0,'docker_failed');return raw
    def state(self,identifier):
        template=('{"id":{{json .Id}},"image":{{json .Image}},"name":{{json .Name}},"pid":{{json .State.Pid}},'
                  '"running":{{json .State.Running}},"paused":{{json .State.Paused}},"restarting":{{json .State.Restarting}},'
                  '"started_at":{{json .State.StartedAt}},"restart":{{json .HostConfig.RestartPolicy}}}')
        value=decode(self.run('inspect','--format',template,identifier))
        fields(value,'id image name pid running paused restarting started_at restart')
        require(value['id']==identifier and isinstance(value['image'],str) and re.fullmatch(r'sha256:[0-9a-f]{64}',value['image']) and isinstance(value['name'],str) and 0<len(value['name'])<=256 and
                integer(value['pid']) and all(type(value[k]) is bool for k in ('running','paused','restarting')) and
                isinstance(value['started_at'],str) and re.fullmatch(r'[0-9T:.+Z-]{20,40}',value['started_at']),'container_changed')
        fields(value['restart'],'Name MaximumRetryCount')
        require(value['restart']['Name'] in ('no','always','unless-stopped','on-failure') and integer(value['restart']['MaximumRetryCount']),'container_changed')
        return value
    def inspect(self,alias,selection):return {k:v for k,v in self.state(selection['id']).items() if k!='started_at'}
    def version(self):
        value=decode(self.run('version','--format','{"version":{{json .Server.Version}},"git_commit":{{json .Server.GitCommit}},"os":{{json .Server.Os}},"arch":{{json .Server.Arch}}}'))
        fields(value,'version git_commit os arch')
        require(isinstance(value['version'],str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9_.-]+)?',value['version']) and
                isinstance(value['git_commit'],str) and re.fullmatch(r'[0-9a-f]{7,40}',value['git_commit']) and
                value['os']=='linux' and value['arch'] in ('amd64','arm64'),'daemon_metadata_refused')
        return value
    def auto_remove(self,identifier):
        require(isinstance(identifier,str) and HEX.fullmatch(identifier),'container_changed')
        value=decode(self.run('inspect','--format','{{json .HostConfig.AutoRemove}}',identifier,limit=64))
        require(type(value) is bool,'container_changed');return value
    def update_no(self,identifier):self.run('update','--restart=no',identifier,limit=256)
    def kill(self,identifier):self.run('kill','--signal','KILL',identifier,limit=256)
    def running_names(self):
        rows=self.run('ps','--no-trunc','--format','{{.ID}} {{.Names}}',limit=65536).decode('ascii').splitlines()
        require(len(rows)<=256,'container_limit')
        out=[]
        for row in rows:
            parts=row.split();require(len(parts)==2 and HEX.fullmatch(parts[0]),'container_changed');out.append(tuple(parts))
        return out

    def listeners(self):
        raw,code=self.runner(['/usr/bin/ss','-H','-ltn'],limit=65536,timeout=10)
        require(code==0,'listener_unconfirmed');ports=set()
        for line in raw.splitlines():
            columns=line.split();require(len(columns)>=5,'listener_unconfirmed')
            match=re.search(rb':([0-9]{1,5})$',columns[3])
            require(match is not None,'listener_unconfirmed')
            number=int(match[1])
            if number in (5051,5060,5070):ports.add(number)
        return ports


def load_module(files,directory,name,expected):
    pin(expected);body,_=files.read(directory+'/'+name,262144);require(digest(body)==expected,'module_refused')
    module=types.ModuleType('_retirement_mutation_'+expected);module.__file__=directory+'/'+name
    exec(compile(body,module.__file__,'exec'),module.__dict__);return module


def evidence(files,directory,name,expected):
    pin(expected);body,_=files.read(directory+'/'+name,65536,True);require(digest(body)==expected,'proof_refused')
    return decode(body)


def rewritten(body,spans):
    out=bytearray();cursor=0;outside=hashlib.sha256()
    for row in spans:
        fields(row,'modifier path start end sha256')
        a,b=row['start'],row['end'];require(integer(a,len(body)) and integer(b,len(body)) and cursor<=a<b<=len(body),'span_refused')
        require(digest(body[a:b])==row['sha256'],'configuration_changed')
        outside.update(body[cursor:a]);out.extend(body[cursor:a])
        modifier=row['modifier'];path=row['path']
        require(modifier in ('','=') and path in ('/','/studio','/studio/','/autobid','/autobid/'),'span_refused')
        out.extend(('location '+(modifier+' ' if modifier else '')+path+' { return 503; }').encode('ascii'));cursor=b
    outside.update(body[cursor:]);out.extend(body[cursor:]);require(len(out)<=262144,'file_limit')
    return bytes(out),outside.hexdigest()


class Mutation:
    def __init__(self,files=None,docker=None,control=None,frozen=None,runner=command,directory=None,sleep=time.sleep):
        self.directory=directory or os.path.dirname(os.path.abspath(__file__))
        staging=self.directory if re.fullmatch(r'/tmp/metainc-control-mutation-[1-9][0-9]{0,19}-1',self.directory) else None
        self.files=files or Files(staging=staging)
        self.docker,self.control,self.freeze=docker,control,frozen
        self.runner,self.sleep=runner,sleep;self.policy=POLICY
        self.report={'status':'blocked','error':None,'phase':None,'execute':False,'session':SESSION,
                     'run':None,'changed_containers':0,'changed_files':0,'protected_count':0,'daemon':None,
                     'local_restore_verified':False,'application_restore_verified':False,'data_deleted':False,
                     'fence_journal_sha256':None,'control_policy_sha256':None}
    def policy_check(self):
        p=self.policy;require(p is not None,'policy_not_pinned');fields(p,'request files protected')
        require(set(p['request'])=={'ad','content'} and isinstance(p['files'],list) and 1<=len(p['files'])<=3 and
                isinstance(p['protected'],list) and 1<=len(p['protected'])<=8,'policy_not_pinned')
        for alias,row in p['request'].items():
            fields(row,'id pid');require(isinstance(row['id'],str) and HEX.fullmatch(row['id']) and integer(row['pid']) and row['pid']>0,'policy_not_pinned')
        for row in p['files']:cfg_path(row['resolved_path'])
        require(p['protected']==PROTECTED and len({row['id'] for row in p['protected']})==len(p['protected']),'policy_not_pinned')
        for row in p['protected']:
            fields(row,'id image');require(isinstance(row['id'],str) and HEX.fullmatch(row['id']) and
                    isinstance(row['image'],str) and re.fullmatch(r'sha256:[0-9a-f]{64}',row['image']),'policy_not_pinned')
    def operator(self,phase):
        if OPERATOR_DOCUMENT is None:value=evidence(self.files,self.directory,'deployment-fence-operator-evidence.json',OPERATOR_SHA)
        else:
            pin(OPERATOR_SHA);require(digest(canonical(OPERATOR_DOCUMENT))==OPERATOR_SHA,'operator_refused');value=OPERATOR_DOCUMENT
        fields(value,'schema session status actor checked_at repository workflows other_workflows other_workflows_unchanged')
        require(type(value['schema']) is int and value['schema']==1 and value['session']==SESSION and value['status']=='known_deployments_disabled' and
                value['actor']=='metainchelp-boop' and value['repository']=='metainchelp-boop/metainc-content-studio' and
                value['other_workflows_unchanged'] is True,'operator_refused')
        expected=[{'id':265254896,'path':'.github/workflows/deploy.yml'},
                  {'id':322623002,'path':'.github/workflows/deploy-autobid.yml'}]
        require(isinstance(value['workflows'],list) and len(value['workflows'])==2,'operator_refused')
        for row,known in zip(value['workflows'],expected):
            fields(row,'id path before after active_runs')
            require(type(row['id']) is int and row['id']==known['id'] and row['path']==known['path'] and row['before']=='active' and
                    row['after']=='disabled_manually' and type(row['active_runs']) is int and row['active_runs']==0,'operator_refused')
        require(value['other_workflows']==[{'id':267160662,'path':'.github/workflows/validate.yml','state':'active'}],'operator_refused')
        require(isinstance(value['checked_at'],str) and len(value['checked_at'])<=40,'operator_refused')
        try:checked=datetime.datetime.fromisoformat(value['checked_at'])
        except ValueError:raise Refused('operator_refused') from None
        require(checked.tzinfo is not None,'operator_refused')
        if phase=='fence':require(-60<=(datetime.datetime.now(datetime.timezone.utc)-checked).total_seconds()<=7200,'operator_stale')
    def protected(self):
        out={}
        for row in self.policy['protected']:
            state=self.docker.state(row['id'])
            require(all(state[k]==row[k] for k in ('id','image')) and state['running'] is True and state['paused'] is False and state['restarting'] is False,'protected_changed')
            out[row['id']]=state
        self.report['protected_count']=len(out);return out
    def states(self,paused):
        out={}
        for alias,selection in self.policy['request'].items():
            row=self.docker.state(selection['id'])
            require(row['id']==selection['id'] and row['image']==FIXED_IMAGES[alias] and row['name']==FIXED_NAMES[alias] and row['pid']==selection['pid'] and row['running'] is True and
                    row['paused'] is paused and row['restarting'] is False,'container_changed')
            out[alias]=row
        return out
    def no_restart(self,states):require(all(row['restart']=={'Name':'no','MaximumRetryCount':0} for row in states.values()),'restart_not_fenced')
    def no_auto_remove(self):
        for selection in self.policy['request'].values():
            require(self.docker.auto_remove(selection['id']) is False,'container_changed')
    def frozen(self):
        if self.freeze is not None:return self.freeze()
        preflight=load_module(self.files,self.directory,'retirement_data_preflight.py',PREFLIGHT_SHA)
        archive=load_module(self.files,self.directory,'retirement_data_archive.py',ARCHIVE_SHA)
        def run(args):return self.docker.run(*args,limit=131072)
        adapter=preflight.Docker(time.monotonic()+45,runner=run)
        snapshot=archive.Snapshot(preflight,self.policy['request'],docker=adapter)
        return snapshot.frozen()
    def control_current(self):
        if self.control is None:self.control=load_module(self.files,self.directory,'retirement_control_preflight.py',CONTROL_SHA)
        result=self.control.collect(self.policy['request'],docker=self.docker)
        require(result.get('status')=='observed' and result.get('error') is None and result.get('files')==self.policy['files'],'configuration_changed')
    def fence_journal(self):
        body,_=self.files.read(BASE+'/fence-complete.json',8192,True);value=decode(body)
        fields(value,'schema session status run operator_evidence_sha256 control_policy_sha256 daemon containers')
        require(value['schema']=='metainc-retirement-original-restart-v1' and value['session']==SESSION and value['status']=='fence_complete' and
                RUN.fullmatch(value['run']) and value['operator_evidence_sha256']==OPERATOR_SHA and value['control_policy_sha256']==digest(canonical(self.policy)) and
                isinstance(value['containers'],dict) and set(value['containers'])=={'ad','content'},'fence_proof_refused')
        for alias,row in value['containers'].items():
            fields(row,'id image started_at restart_policy');fields(row['restart_policy'],'Name MaximumRetryCount')
            require(row['id']==self.policy['request'][alias]['id'] and isinstance(row['image'],str) and re.fullmatch(r'sha256:[0-9a-f]{64}',row['image']) and
                    row['restart_policy']['Name'] in ('no','always','unless-stopped','on-failure') and integer(row['restart_policy']['MaximumRetryCount']),'fence_proof_refused')
        return value
    def transfer_proof(self):
        require(isinstance(SOURCE_RUN,str) and RUN.fullmatch(SOURCE_RUN),'source_run_not_pinned')
        pin(SEND_SHA);body,_=self.files.read(TRANSFER,8192,True);require(digest(body)==SEND_SHA,'transfer_proof_refused');value=decode(body)
        fields(value,'phase status session error ssh_public_key bytes sha256 process_rc backup_verified source_bytes archive_bytes object_count paused operator_evidence_sha256 run')
        require(value['phase']=='send' and value['status']=='transferred_unverified' and value['session']==TRANSFER_SESSION and value['error'] is None and
                value['ssh_public_key'] is None and value['backup_verified'] is False and value['run']==SOURCE_RUN and
                value['operator_evidence_sha256']==OPERATOR_SHA and value['paused']=={'ad':'paused','content':'paused'} and
                value['process_rc']=={'archive':0,'gpg':0,'ssh':0} and all(type(v) is int for v in value['process_rc'].values()),'transfer_proof_refused')
        for key,maximum in (('bytes',MAX_CIPHER),('source_bytes',MAX_SOURCE),('archive_bytes',MAX_ARCHIVE),('object_count',MAX_OBJECTS)):
            require(integer(value[key],maximum) and value[key]>0,'transfer_proof_refused')
        require(isinstance(value['sha256'],str) and HEX.fullmatch(value['sha256']) and value['archive_bytes']%512==0 and value['archive_bytes']>=value['source_bytes'],'transfer_proof_refused')
        return value
    def local_proof(self,transfer):
        value=evidence(self.files,self.directory,'retirement-local-restore-proof.json',LOCAL_RESTORE_SHA)
        counts={'database_count','table_count','row_count','foreign_key_violations','decrypted_fields','content_json_checked',
                'content_json_failed','ad_decrypted_fields','autobid_decrypted_fields','decryption_failures','files_verified',
                'source_bytes','memory_only_files','deleted_objects','recovery_config_objects','recovery_config_absent'}
        truths={'archive_authenticated','second_pass_identical','pristine_unchanged','sqlite_schema_counts_equal','ad_key_capsule_equal'}
        falsehoods={'production_sql_baseline_compared','dynamic_references_checked','application_restore_verified'}
        extra={'status','session','gpg_return_codes','children_reaped','agent_cache_cleared','restore_sha256','data_cipher_sha256','capsule_cipher_sha256'}
        require(isinstance(value,dict) and set(value)==counts|truths|falsehoods|extra,'restore_proof_refused')
        require(value['status']=='isolated_data_checks_passed' and value['session']==SESSION and
                all(integer(value[k],2**63-1) for k in counts) and all(value[k] is True for k in truths) and
                all(value[k] is False for k in falsehoods) and value['decryption_failures']==value['content_json_failed']==0 and
                value['source_bytes']==transfer['source_bytes'] and value['files_verified']==transfer['object_count'] and
                value['data_cipher_sha256']==transfer['sha256'] and value['gpg_return_codes']==[0,0,0] and
                all(type(v) is int for v in value['gpg_return_codes']) and value['children_reaped'] is True and value['agent_cache_cleared'] is True and
                value['restore_sha256']=='3b4afdfb35db024c0b3203becd487bc9502d48384ecf4218515c266c95b41da7' and
                isinstance(value['capsule_cipher_sha256'],str) and HEX.fullmatch(value['capsule_cipher_sha256']),'restore_proof_refused')
        if LOCAL_RESTORE_EXPECTED is not None:require(value==LOCAL_RESTORE_EXPECTED,'restore_proof_refused')
        self.report['local_restore_verified']=True
    def semantics(self,daemon):
        value=evidence(self.files,self.directory,'retirement-kill-semantics.json',SEMANTICS_SHA)
        fields(value,'schema daemon_version daemon_git_commit signal order source_commit source_sha256')
        require(value['schema']=='metainc-retirement-kill-v1' and value['daemon_version']==daemon['version'] and
                value['daemon_git_commit']==daemon['git_commit'] and value['signal']=='KILL' and value['order']=='task_kill_before_resume' and
                isinstance(value['source_commit'],str) and re.fullmatch('[0-9a-f]{40}',value['source_commit']) and
                value['source_commit'].startswith(daemon['git_commit']) and isinstance(value['source_sha256'],str) and HEX.fullmatch(value['source_sha256']),'semantics_unproven')
    def record(self,name,value):self.files.write(BASE+'/'+name,canonical(value))
    def run(self,phase,execute,run):
        require(self.files.staging is None or self.files.staging=='/tmp/metainc-control-mutation-'+run,'arguments_refused')
        if execute:
            self.perform(phase,False,run)
            self.files.initialize()
            with self.files.lock():return self.perform(phase,True,run)
        return self.perform(phase,False,run)

    def perform(self,phase,execute,run):
        self.report.update(phase=phase,execute=execute,run=run)
        require(phase in PHASES and type(execute) is bool and isinstance(run,str) and RUN.fullmatch(run),'arguments_refused')
        self.policy_check();self.operator(phase);daemon=self.docker.version();self.report['daemon']=daemon
        protected=self.protected();paused=phase!='fence';states=self.states(paused)
        frozen=self.frozen() if paused else None
        if phase=='fence':self.control_current()
        else:
            self.no_restart(states);original=self.fence_journal();transfer=self.transfer_proof()
            require(all(states[a]['id']==original['containers'][a]['id'] and states[a]['image']==original['containers'][a]['image'] and
                        states[a]['started_at']==original['containers'][a]['started_at'] for a in states),'container_changed')
            if phase=='maintenance':
                self.control_current()
                _,test_code=self.runner(['/usr/sbin/nginx','-t'],limit=4096,timeout=15)
                require(test_code==0,'nginx_pretest_failed')
            else:
                self.no_auto_remove()
                self.local_proof(transfer);self.semantics(daemon)
                maintenance=decode(self.files.read(BASE+'/maintenance-complete.json',65536,True)[0])
                fields(maintenance,'schema session status run transfer_sha256 records')
                require(maintenance['schema']=='metainc-retirement-maintenance-v1' and maintenance['session']==SESSION and maintenance['status']=='maintenance_complete' and
                        maintenance['transfer_sha256']==SEND_SHA and RUN.fullmatch(maintenance['run']) and isinstance(maintenance['records'],list) and len(maintenance['records'])==len(self.policy['files']),'maintenance_proof_refused')
                for record in maintenance['records']:
                    cfg_path(record['path']);require(digest(self.files.read(record['path'],262144)[0])==record['new_sha256'],'configuration_changed')
        require(self.protected()==protected,'protected_changed')
        try:require(self.files.absent(BASE+'/'+phase+'-attempt.json'),'attempt_exists')
        except FileNotFoundError:pass
        if not execute:self.report['status']='ready';return self.report
        try:require(self.files.absent(BASE+'/'+phase+'-attempt.json'),'attempt_exists')
        except FileNotFoundError:pass
        self.files.initialize()
        attempt={'schema':'metainc-retirement-control-attempt-v1','session':SESSION,'phase':phase,'run':run,
                 'operator_evidence_sha256':OPERATOR_SHA,'control_policy_sha256':digest(canonical(self.policy))}
        if phase=='fence':
            attempt.update(daemon=daemon,original_containers={alias:{'id':row['id'],'image':row['image'],'started_at':row['started_at'],
                'restart_policy':row['restart']} for alias,row in states.items()})
        self.record(phase+'-attempt.json',attempt)
        if phase=='fence':
            require(self.states(False)==states,'container_changed')
            original={alias:{'id':row['id'],'image':row['image'],'started_at':row['started_at'],'restart_policy':row['restart']} for alias,row in states.items()}
            self.record('fence-original.json',{'containers':original,'daemon':daemon})
            for alias,row in states.items():self.docker.update_no(row['id']);self.report['changed_containers']+=1
            now=self.states(False);self.no_restart(now)
            require(all({k:v for k,v in now[a].items() if k!='restart'}=={k:v for k,v in states[a].items() if k!='restart'} for a in states),'container_changed')
            require(self.protected()==protected,'protected_changed')
            self.record('fence-complete.json',{'schema':'metainc-retirement-original-restart-v1','session':SESSION,'status':'fence_complete','run':run,
                'operator_evidence_sha256':OPERATOR_SHA,'control_policy_sha256':digest(canonical(self.policy)),'daemon':daemon,'containers':original})
            stored,_=self.files.read(BASE+'/fence-complete.json',8192,True)
            require(decode(stored)==self.fence_journal(),'fence_proof_refused')
            self.report.update(fence_journal_sha256=digest(stored),control_policy_sha256=digest(canonical(self.policy)))
        elif phase=='maintenance':
            records=[];reload_attempted=False
            try:
                for number,row in enumerate(self.policy['files'],1):
                    path=cfg_path(row['resolved_path']);body,identity=self.files.read(path,262144)
                    require(digest(body)==row['sha256'],'configuration_changed')
                    replacement,outside=rewritten(body,row['locations']);require(outside==row['protected_bytes_sha256'],'protected_changed')
                    self.files.write(BASE+'/nginx-before-'+str(number)+'.bin',body)
                    candidate=path.rsplit('/',1)[0]+'/.metainc-retirement-'+SESSION+'-'+str(number)+'.pending'
                    self.record('maintenance-plan-'+str(number)+'.json',{'path':path,'candidate':candidate,'old_sha256':digest(body),'new_sha256':digest(replacement)})
                    record=registered(lambda:self.files.swap(path,candidate,body,identity,replacement),records);self.report['changed_files']+=1
                    self.record('maintenance-file-'+str(number)+'.json',record)
                require(self.frozen()==frozen and self.protected()==protected,'container_changed')
                _,code=self.runner(['/usr/sbin/nginx','-t'],limit=4096,timeout=15);require(code==0,'nginx_test_failed')
                reload_attempted=True
                _,code=self.runner(['/usr/bin/systemctl','reload','nginx'],limit=4096,timeout=20);require(code==0,'nginx_reload_unconfirmed')
                require(self.frozen()==frozen and self.protected()==protected,'protected_changed')
                self.record('maintenance-complete.json',{'schema':'metainc-retirement-maintenance-v1','session':SESSION,'status':'maintenance_complete',
                    'run':run,'transfer_sha256':SEND_SHA,'records':records})
            except BaseException:
                restored=True
                with cleanup_signals():
                    for record in reversed(records):
                        try:self.files.rollback(record)
                        except BaseException:restored=False
                    if records and restored:
                        try:
                            _,code=self.runner(['/usr/sbin/nginx','-t'],limit=4096,timeout=15)
                            restored=code==0
                            if restored and reload_attempted:
                                _,code=self.runner(['/usr/bin/systemctl','reload','nginx'],limit=4096,timeout=20)
                                restored=code==0
                        except BaseException:restored=False
                require(restored,'rollback_unconfirmed')
                raise
        else:
            require(self.frozen()==frozen and self.protected()==protected,'container_changed')
            self.no_auto_remove()
            for alias,selection in self.policy['request'].items():self.docker.kill(selection['id']);self.report['changed_containers']+=1
            for delay in (0,10,20):
                if delay:self.sleep(delay)
                for alias,selection in self.policy['request'].items():
                    row=self.docker.state(selection['id']);require(row['running'] is False and row['paused'] is False and row['pid']==0 and row['restart']=={'Name':'no','MaximumRetryCount':0},'stop_unconfirmed')
                if delay:require(not self.docker.listeners(),'writer_reappeared')
                names=self.docker.running_names();require(not any(name in ('ad-api','content-studio','autobid-web','autobid-engine','autobid-watchdog') for _,name in names),'writer_reappeared')
                require(self.protected()==protected,'protected_changed')
            self.record('stop-complete.json',{'schema':'metainc-retirement-stop-v1','session':SESSION,'status':'stop_complete','run':run,
                        'transfer_sha256':SEND_SHA,'local_restore_sha256':LOCAL_RESTORE_SHA,'semantics_sha256':SEMANTICS_SHA})
        self.report['status']='completed';return self.report


class SafeParser(argparse.ArgumentParser):
    def error(self,message):raise Refused('arguments_refused')


def main():
    helper=None
    try:
        require(os.geteuid()==0 and sys.platform=='linux','platform_refused');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
        parser=SafeParser(add_help=False);parser.add_argument('phase',choices=PHASES);parser.add_argument('mode',choices=('check','execute'));parser.add_argument('run')
        args=parser.parse_args();helper=Mutation()
        for number in (signal.SIGINT,signal.SIGHUP,signal.SIGTERM,signal.SIGALRM):signal.signal(number,lambda *_:(_ for _ in ()).throw(Refused('interrupted')))
        signal.setitimer(signal.ITIMER_REAL,240)
        # Use the same empty, private Docker CLI config adapter as control probe.
        import tempfile
        with tempfile.TemporaryDirectory(prefix='metainc-mutation-docker-',dir='/tmp') as config:
            helper.docker=Docker(config);report=helper.run(args.phase,args.mode=='execute',args.run)
    except BaseException as error:
        report=helper.report if helper is not None else {'status':'blocked','session':SESSION,'data_deleted':False}
        report.update(status='blocked',error=error.code if isinstance(error,Refused) else 'operation_failed')
    finally:signal.setitimer(signal.ITIMER_REAL,0)
    print(canonical(report).decode());return 0 if report['status'] in ('ready','completed') else 2


if __name__=='__main__':sys.exit(main())
