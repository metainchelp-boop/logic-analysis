#!/usr/bin/env python3
"""Bounded read-only nginx/control facts. Never changes ingress or containers.

Only chosen preimages are returned through private=; never serialize that object.
Direct local-upstream selectors are observed, not a proof of nginx's full routing.
"""
import argparse
import contextlib
import hashlib
import json
import os
import posixpath
import re
import resource
import selectors as io_selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

TIMEOUT=45
MAX_FILE=256*1024
MAX_TOTAL=2*1024*1024
MAX_FILES=16
ENABLED='/etc/nginx/sites-enabled'
AVAILABLE='/etc/nginx/sites-available'
FIXED={'ad':'ad.metainc.co.kr','logic':'logic-analysis'}
IMAGES={'ad':'sha256:959001525d45612e0c5cc1045291c7b6caefa768c14d37cc1070c26584cb8922',
        'content':'sha256:b52374a33084ea20386af2380478a38cff92eebdbeff97c616ad7d80a112a0dc'}
NAMES={'ad':'/ad-api','content':'/content-studio'}
READ=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK
DIR=READ|os.O_DIRECTORY
BASENAME=re.compile(r'[A-Za-z0-9._-]{1,96}\Z')
RELAY='/run/metainc/naver-relay/relay.sock'


class Refused(Exception):
    def __init__(self,code):self.code=code


def check(value,code):
    if not value:raise Refused(code)


def stamp(v):
    return v.st_dev,v.st_ino,v.st_mode,v.st_uid,v.st_gid,v.st_nlink,v.st_size,v.st_mtime_ns,v.st_ctime_ns


def meta(v):
    return {'device':v.st_dev,'inode':v.st_ino,'mode':stat.S_IMODE(v.st_mode),'uid':v.st_uid,
            'gid':v.st_gid,'links':v.st_nlink,'bytes':v.st_size}


def basename(value):
    check(isinstance(value,str) and BASENAME.fullmatch(value) and value not in ('.','..') and 'root' not in value,'basename_refused')
    return value


def unique(pairs):
    value={}
    for k,v in pairs:
        check(k not in value,'metadata_invalid');value[k]=v
    return value


class Files:
    """Alternative base/owner are synthetic fixtures, not CLI options."""
    def __init__(self,base='/',owner=0):self.base,self.owner=base,owner

    @contextlib.contextmanager
    def directory(self,path):
        check(path.startswith('/') and all(p not in ('.','..') for p in path.split('/')),'path_refused')
        with contextlib.ExitStack() as stack:
            fd=os.open(self.base,DIR);stack.callback(os.close,fd);chain=[]
            for part in path.split('/'):
                if not part:continue
                before=os.stat(part,dir_fd=fd,follow_symlinks=False)
                check(stat.S_ISDIR(before.st_mode) and before.st_uid==self.owner and not before.st_mode&0o022,'directory_refused')
                child=os.open(part,DIR,dir_fd=fd);stack.callback(os.close,child)
                check(stamp(os.fstat(child))==stamp(before),'path_changed')
                chain.append((fd,part,child,stamp(before)));fd=child
            yield fd
            for parent,name,child,expected in chain:
                # Directory contents may change only in the enabled directory;
                # callers additionally compare its complete inventory below.
                check(stamp(os.stat(name,dir_fd=parent,follow_symlinks=False))==expected and stamp(os.fstat(child))==expected,'path_changed')

    def names(self):
        with self.directory(ENABLED) as fd:
            rows=os.listdir(fd)
            check(len(rows)<=MAX_FILES,'candidate_limit')
            for value in rows:basename(value)
            return tuple(sorted(rows))

    def read(self,name):
        name=basename(name);entry_path=ENABLED+'/'+name
        with self.directory(ENABLED) as enabled:
            before=os.stat(name,dir_fd=enabled,follow_symlinks=False);link=None
            check(before.st_uid==self.owner,'file_refused')
            if stat.S_ISLNK(before.st_mode):
                link=os.readlink(name,dir_fd=enabled)
                check(isinstance(link,str) and len(link)<=256 and '\\' not in link and not any(ord(c)<32 for c in link),'symlink_refused')
                resolved=posixpath.normpath(link if link.startswith('/') else ENABLED+'/'+link)
                check(posixpath.dirname(resolved)==AVAILABLE,'symlink_refused')
                leaf=basename(posixpath.basename(resolved));parent=AVAILABLE
            else:
                check(stat.S_ISREG(before.st_mode),'file_refused')
                parent,leaf,resolved=ENABLED,name,entry_path
            with self.directory(parent) as folder:
                initial=os.stat(leaf,dir_fd=folder,follow_symlinks=False)
                check(stat.S_ISREG(initial.st_mode) and initial.st_uid==self.owner and initial.st_nlink==1 and
                      not initial.st_mode&0o022 and 0<initial.st_size<=MAX_FILE,'file_refused')
                fd=os.open(leaf,READ,dir_fd=folder)
                try:
                    check(stamp(os.fstat(fd))==stamp(initial),'path_changed');body=bytearray()
                    while True:
                        block=os.read(fd,min(65536,MAX_FILE+1-len(body)))
                        if not block:break
                        body.extend(block);check(len(body)<=MAX_FILE,'file_limit')
                    check(stamp(os.fstat(fd))==stamp(initial) and stamp(os.stat(leaf,dir_fd=folder,follow_symlinks=False))==stamp(initial),'path_changed')
                finally:os.close(fd)
            check(stamp(os.stat(name,dir_fd=enabled,follow_symlinks=False))==stamp(before),'path_changed')
            if link is not None:check(os.readlink(name,dir_fd=enabled)==link,'path_changed')
        return {'enabled_path':entry_path,'resolved_path':resolved,'entry_metadata':meta(before),
                'entry_identity':stamp(before),'metadata':meta(initial),'identity':stamp(initial),
                'link':link,'body':bytes(body),'sha256':hashlib.sha256(body).hexdigest()}

    def verify(self,row):
        name=posixpath.basename(row['enabled_path'])
        with self.directory(ENABLED) as enabled:
            check(stamp(os.stat(name,dir_fd=enabled,follow_symlinks=False))==row['entry_identity'],'configuration_changed')
            if row['link'] is not None:check(os.readlink(name,dir_fd=enabled)==row['link'],'configuration_changed')
        parent,leaf=posixpath.split(row['resolved_path'])
        with self.directory(parent) as folder:
            check(stamp(os.stat(leaf,dir_fd=folder,follow_symlinks=False))==row['identity'],'configuration_changed')


def parse(raw):
    """Small strict lexer retaining byte offsets, including quoted brace handling."""
    tokens=[];i=0;n=len(raw)
    while i<n:
        if raw[i] in b' \t\r\n':i+=1;continue
        if raw[i]==35:
            end=raw.find(b'\n',i);i=n if end<0 else end+1;continue
        start=i
        if raw[i] in b'{};':tokens.append((chr(raw[i]),i,i+1,False));i+=1;continue
        data=bytearray();quote=None;quoted=False
        while i<n:
            c=raw[i]
            if c==92:
                check(i+1<n,'nginx_syntax_unsupported');data.extend(raw[i:i+2]);i+=2;continue
            if quote:
                if c==quote:quote=None;quoted=True;i+=1;continue
                data.append(c);i+=1;continue
            if c in (34,39):quote=c;i+=1;continue
            if c in b' \t\r\n{};#':break
            check(not quoted,'nginx_syntax_unsupported');data.append(c);i+=1
        check(quote is None and (data or quoted),'nginx_syntax_unsupported')
        try:value=data.decode('utf-8','strict')
        except UnicodeError:raise Refused('nginx_syntax_unsupported') from None
        tokens.append((value,start,i,True));check(len(tokens)<=32768,'nginx_token_limit')
    index=0
    def block(depth,nested):
        nonlocal index
        check(depth<=32,'nginx_depth_limit');out=[];args=[];start=None
        while index<len(tokens):
            value,a,b,word=tokens[index];index+=1
            if word:
                if start is None:start=a
                args.append(value);continue
            if value=='}':
                check(nested and not args,'nginx_syntax_unsupported');return out,b
            check(bool(args),'nginx_syntax_unsupported')
            if value=='{':children,end=block(depth+1,True)
            else:children,end=None,b
            out.append({'args':tuple(args),'children':children,'start':start,'end':end});args=[];start=None
        check(not nested and not args,'nginx_syntax_unsupported');return out,n
    return block(0,False)[0]


def values(nodes,directive):
    return [node['args'][1:] for node in nodes if node['children'] is None and node['args'][0]==directive]


def port_of(value):
    match=re.fullmatch(r'(?:(?:127\.0\.0\.1|0\.0\.0\.0|\[::\]|\*):)?([0-9]{1,5})',value)
    return int(match[1]) if match else None


def local_proxy(node,port):
    rows=values(node['children'],'proxy_pass')
    return len(rows)==1 and len(rows[0])==1 and re.fullmatch(r'http://(?:127\.0\.0\.1|localhost|\[::1\]):'+str(port)+r'/?',rows[0][0]) is not None


def location(node):
    args=node['args']
    if args[0]!='location' or node['children'] is None:return None
    if len(args)==2:return '',args[1]
    if len(args)==3 and args[1] in ('=','^~','~','~*'):return args[1],args[2]
    raise Refused('location_unsupported')


def selectors(raw,alias):
    selected=[];protected=[];matched_servers=0
    for server in parse(raw):
        if server['args']!=('server',) or server['children'] is None:continue
        nodes=server['children'];names={name for row in values(nodes,'server_name') for name in row}
        ports={port_of(row[0]) for row in values(nodes,'listen') if row}
        hosts={'ad':{'ad.metainc.co.kr','dashboard.metainc.co.kr'},'logic':{'logic.metainc.co.kr'},'studio':{'studio.metainc.co.kr'}}[alias]
        if not names&hosts or (80 if alias=='studio' else 443) not in ports:continue
        check(names==hosts,'vhost_names_unresolved')
        matched_servers+=1;check(matched_servers==1,'vhost_ambiguous');locations=[(node,location(node)) for node in nodes if node['args'][0]=='location']
        wanted={'ad':{('', '/'):5051},'studio':{('', '/'):5060},
                'logic':{('', '/studio/'):5060,('', '/autobid/'):5070,('=', '/autobid'):5070}}[alias]
        matched=set()
        for node,selector in locations:
            if selector in wanted and local_proxy(node,wanted[selector]):selected.append(node);matched.add(selector)
        required={'ad':{('', '/')},'studio':{('', '/')},'logic':{('', '/studio/'),('', '/autobid/')}}[alias]
        check(required<=matched,'app_location_unresolved')
        if alias=='logic':
            for path in ('/studio','/autobid'):
                exact=[node for node,sel in locations if sel==('=',path)]
                check(len(exact)==1,'app_location_unresolved')
                node=exact[0]
                if node in selected:continue
                returns=values(node['children'],'return')
                check(len(returns)==1 and len(returns[0])==2 and returns[0][0] in ('301','302','307','308') and
                      returns[0][1]==path+'/','app_location_unresolved')
                selected.append(node)
        if alias=='ad':
            relay_selectors={('=','/naver'),('^~','/naver/'),('=','/api/naver-auto'),('^~','/api/naver-auto/')}
            found=set()
            for node,sel in locations:
                if sel not in relay_selectors:continue
                proxies=values(node['children'],'proxy_pass')
                check(sel not in found and len(proxies)==1 and len(proxies[0])==1 and
                      proxies[0][0] in ('http://unix:'+RELAY,'http://unix:'+RELAY+':'),'relay_location_unresolved')
                found.add(sel);protected.append(node)
            check(found==relay_selectors,'relay_location_unresolved')
    check(matched_servers>0,'vhost_missing')
    selected.sort(key=lambda node:node['start']);protected.sort(key=lambda node:node['start'])
    check(len(selected)<=16 and all(a['end']<=b['start'] for a,b in zip(selected,selected[1:])),'location_unsupported')
    # Hash every byte not selected for mutation: this includes all other logic
    # locations, TLS, relay blocks, comments, server wrappers and directives.
    digest=hashlib.sha256();cursor=0
    for node in selected:digest.update(raw[cursor:node['start']]);cursor=node['end']
    digest.update(raw[cursor:])
    def public(node):
        modifier,path=location(node)
        return {'modifier':modifier,'path':path,'start':node['start'],'end':node['end'],
                'sha256':hashlib.sha256(raw[node['start']:node['end']]).hexdigest()}
    return {'locations':[public(node) for node in selected],'protected_locations':[public(node) for node in protected],
            'protected_bytes_sha256':digest.hexdigest(),'matching_servers':matched_servers}


class Docker:
    def __init__(self,end):self.end=end
    def inspect(self,alias,selection):
        # Own exclusive scratch only; never read the operator's Docker context.
        with tempfile.TemporaryDirectory(prefix='metainc-control-docker-',dir='/tmp') as config:
            info=os.stat(config,follow_symlinks=False)
            check(stat.S_ISDIR(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o700,'docker_config_refused')
            return self.inspect_local(alias,selection,config)

    def inspect_local(self,alias,selection,config):
        template=('{"id":{{json .Id}},"image":{{json .Image}},"name":{{json .Name}},"pid":{{json .State.Pid}},'
                  '"running":{{json .State.Running}},"paused":{{json .State.Paused}},'
                  '"restarting":{{json .State.Restarting}},"restart":{{json .HostConfig.RestartPolicy}}}')
        child=subprocess.Popen(['/usr/bin/docker','--host','unix:///var/run/docker.sock','--config',config,
                                'inspect','--format',template,selection['id']],stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,start_new_session=True,
                               env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','HOME':config})
        body=bytearray()
        try:
            with io_selectors.DefaultSelector() as selected:
                selected.register(child.stdout,io_selectors.EVENT_READ)
                while True:
                    check(time.monotonic()<self.end,'time_limit')
                    if not selected.select(min(.2,max(.001,self.end-time.monotonic()))):continue
                    block=os.read(child.stdout.fileno(),min(4096,16385-len(body)))
                    if not block:break
                    body.extend(block);check(len(body)<=16384,'command_limit')
            check(child.wait(timeout=max(.01,self.end-time.monotonic()))==0,'container_inspect_failed')
        finally:
            cleanup_failed=False
            if child.poll() is None:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                except OSError:cleanup_failed=True
            try:child.wait(timeout=5)
            except (OSError,subprocess.TimeoutExpired):cleanup_failed=True
            finally:child.stdout.close()
            check(not cleanup_failed,'child_teardown_failed')
        try:return json.loads(body,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(Refused('metadata_invalid')))
        except (ValueError,UnicodeError):raise Refused('metadata_invalid') from None



def container(docker,alias,selection):
    check(isinstance(selection,dict) and set(selection)=={'id','pid'} and isinstance(selection['id'],str) and
          re.fullmatch('[0-9a-f]{64}',selection['id']) and type(selection['pid']) is int and 0<selection['pid']<2**32,'request_refused')
    row=docker.inspect(alias,selection)
    check(isinstance(row,dict) and set(row)=={'id','image','name','pid','running','paused','restarting','restart'} and
          row['id']==selection['id'] and row['image']==IMAGES[alias] and row['name']==NAMES[alias] and
          type(row['pid']) is int and row['pid']==selection['pid'] and row['running'] is True and
          row['restarting'] is False and type(row['paused']) is bool,'container_changed')
    policy=row['restart']
    check(isinstance(policy,dict) and set(policy)=={'Name','MaximumRetryCount'} and
          policy['Name'] in ('no','always','unless-stopped','on-failure') and type(policy['MaximumRetryCount']) is int and
          0<=policy['MaximumRetryCount']<2**32,'restart_unconfirmed')
    return row


def collect(request,files=None,docker=None,private=None):
    files=files or Files();end=time.monotonic()+TIMEOUT;docker=docker or Docker(end)
    report={'status':'incomplete','error':None,'read_only':True,'changes_applied':False,
            'routing_scope':'direct_selected_locations_only','startup_scope':'known_controls_only',
            'loaded_config_verified':False,'workflow_state_observed':False,
            'files':[],'containers':[]}
    if private is not None:private.clear()
    try:
        check(isinstance(request,dict) and set(request)=={'ad','content'},'request_refused')
        controls={alias:container(docker,alias,request[alias]) for alias in ('ad','content')}
        names=files.names();check(set(FIXED.values())<=set(names),'fixed_source_missing')
        chosen={};studio=[];total=0;observed=[]
        for name in names:
            check(time.monotonic()<end,'time_limit');row=files.read(name);total+=len(row['body'])
            check(total<=MAX_TOTAL,'candidate_total_limit')
            observed.append({key:row[key] for key in ('enabled_path','resolved_path','entry_identity','identity','link')})
            if name in FIXED.values():
                alias=next(key for key,value in FIXED.items() if value==name)
                row['selectors']=selectors(row['body'],alias);chosen[alias]=row
            # Unrelated bytes are only transient discovery inputs and are never
            # retained in the private preimage object or public result.
            try:selection=selectors(row['body'],'studio')
            except Refused as error:
                if error.code=='vhost_missing':continue
                raise
            studio.append(dict(row,selectors=selection))
        check(len(studio)==1,'studio_source_ambiguous');chosen['studio']=studio[0]
        check(files.names()==names,'candidate_set_changed')
        for row in observed:files.verify(row)
        grouped={}
        for alias,row in chosen.items():
            grouped.setdefault(row['resolved_path'],[]).append((alias,row))
        for path,rows in grouped.items():
            row=rows[0][1]
            check(all(other['body']==row['body'] and other['identity']==row['identity'] for _,other in rows),'configuration_changed')
            current=files.read(posixpath.basename(row['enabled_path']))
            check(all(current[key]==row[key] for key in ('body','identity','entry_identity','link','resolved_path')),'configuration_changed')
            selections={};protected={}
            for _,other in rows:
                for node in other['selectors']['locations']:selections[(node['start'],node['end'])]=node
                for node in other['selectors']['protected_locations']:protected[(node['start'],node['end'])]=node
            locations=sorted(selections.values(),key=lambda value:value['start'])
            check(all(a['end']<=b['start'] for a,b in zip(locations,locations[1:])),'location_unsupported')
            digest=hashlib.sha256();cursor=0
            for node in locations:digest.update(row['body'][cursor:node['start']]);cursor=node['end']
            digest.update(row['body'][cursor:])
            report['files'].append({'aliases':sorted(alias for alias,_ in rows),
                'enabled_paths':sorted({other['enabled_path'] for _,other in rows}),'resolved_path':path,
                'metadata':row['metadata'],'sha256':row['sha256'],'locations':locations,
                'protected_locations':sorted(protected.values(),key=lambda value:value['start']),
                'protected_bytes_sha256':digest.hexdigest(),
                'matching_servers':sum(other['selectors']['matching_servers'] for _,other in rows)})
        for alias,row in controls.items():
            check(container(docker,alias,request[alias])==row,'container_changed')
            report['containers'].append({'alias':alias,'pid':row['pid'],'paused':row['paused'],
                'restart_policy':row['restart']['Name'],'maximum_retry_count':row['restart']['MaximumRetryCount']})
        if private is not None:private['preimages']=chosen
        report['status']='observed'
    except Refused as error:report['error']=error.code
    except BaseException:report['error']='observation_failed'
    if report['status']!='observed' and private is not None:private.clear()
    return report


class SafeParser(argparse.ArgumentParser):
    def error(self,message):raise Refused('request_refused')


def main():
    try:
        check(os.geteuid()==0,'privilege_required');resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        parser=SafeParser(add_help=False)
        for alias in ('ad','content'):
            parser.add_argument('--'+alias+'-container-id',required=True)
            parser.add_argument('--'+alias+'-init-pid',required=True,type=int)
        args=parser.parse_args()
        signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(Refused('time_limit')))
        signal.setitimer(signal.ITIMER_REAL,TIMEOUT)
        request={alias:{'id':getattr(args,alias+'_container_id'),'pid':getattr(args,alias+'_init_pid')} for alias in ('ad','content')}
        report=collect(request)
    except Refused as error:report={'status':'incomplete','error':error.code,'read_only':True,'changes_applied':False}
    except BaseException:report={'status':'incomplete','error':'observation_failed','read_only':True,'changes_applied':False}
    finally:signal.setitimer(signal.ITIMER_REAL,0)
    raw=json.dumps(report,separators=(',',':'))
    if len(raw)>65536:
        report['status']='incomplete'
        raw='{"status":"incomplete","error":"output_limit","read_only":true,"changes_applied":false}'
    print(raw)
    return 0 if report['status']=='observed' and len(raw)<=65536 else 2


if __name__=='__main__':sys.exit(main())
