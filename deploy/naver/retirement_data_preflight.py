#!/usr/bin/env python3
"""Finite, read-only data coverage observations. Never an authorization to stop."""
import argparse
import contextlib
import hashlib
import json
import os
import posixpath
import re
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time

TIMEOUT = 60
MAX_READ = 65536
MAX_COMMAND = 131072
MAX_FILES = 100000
MAX_DEPTH = 32
MAX_PIDS = 4096
MAX_FDS = 131072
MAX_PID_FDS = 4096
MAX_MAPS = 262144
MAX_DELETED = 64
MAX_DELETED_REFS = 256
ROOTS = {'ad': '/root/ad-dashboard-deploy/data', 'content': '/root/content-studio-deploy/data',
         'autobid': '/var/lib/docker/volumes/autobid_autobid-data/_data'}
VOLUME = 'autobid_autobid-data'
IMAGES = {'ad': 'sha256:959001525d45612e0c5cc1045291c7b6caefa768c14d37cc1070c26584cb8922',
          'content': 'sha256:b52374a33084ea20386af2380478a38cff92eebdbeff97c616ad7d80a112a0dc'}
NAMES = {'ad': '/ad-api', 'content': '/content-studio'}
DBS = (('STUDIO_AUTH_DB', 'auth.db'), ('STUDIO_CLIENTS_DB', 'clients.db'),
       ('STUDIO_CATEGORIES_DB', 'categories.db'), ('STUDIO_COPY_DB', 'copy_library.db'),
       ('STUDIO_REFERENCES_DB', 'references.db'), ('STUDIO_FEEDBACK_DB', 'feedback.db'),
       ('STUDIO_SHARE_DB', 'share.db'), ('STUDIO_USAGE_DB', 'usage.db'), ('STUDIO_SUPPORT_DB', 'support.db'))
FALLBACKS = ('studio_clients.db', 'studio_copy_library.db', 'studio_references.db',
             'studio_feedback.db', 'studio_share.db', 'studio_support.db')
CANDIDATES = tuple('/tmp/' + name + suffix for name in FALLBACKS + ('auth.db', 'categories.db')
                   for suffix in ('', '-wal', '-shm', '-journal'))
DB_KEYS = frozenset(key for key, _ in DBS) | {'DB_PATH', 'AUTOBID_DATABASE_URL'}
SOURCE_PINS = (
('ad', '/app/app/database.py', 'b0c59a14241e6e5faeab04a5dc6d128e7cd7b008b345f4c2e08b0acd343f92f4'),
('content', '/app/app.py', '9504c86436adfbfd2a8d4f3869c868f3a685ca29884c3246bd5ad194aa505d5e'),
('content', '/app/core/auth_db.py', '5a2ffa47215d72c682af7f5c27d0b3add91ddae6d5648b3a6f4b51900e5ffad7'),  # gitleaks:allow -- verified source-file SHA-256
('content', '/app/core/clients_db.py', '9b5e77deaf4e93c3558503958d0ce0abe4a3c415f3ccefe794dc795d460a72e5'),
('content', '/app/core/categories_db.py', 'c1c3117a48a6db4f610c6fb77b6d6a82b1d894a304a771dd7fccc36346313388'),
('content', '/app/core/copy_library_db.py', 'ff57fc487e760a324f928243fb3bfd69425f2014c49ba68c17ee68b26ed5c039'),
('content', '/app/core/references_db.py', 'e762ea01ef6367339678740365085dcee2624bca906414e03d1e54e8ccf7e054'),
('content', '/app/core/feedback_db.py', '9782e46b81ebdc280485bf020edefaf96e46fa434176647658cf290f1706ab9c'),
('content', '/app/core/share_db.py', '43ef13d1e7050f57d967cc9b4957d37807570a4344d001696227f62fe1c343e5'),
('content', '/app/core/usage_tracker.py', 'b84ea644fab584742f4362fd4fd19b8728fbec758703dccf2dc043446600b092'),
('content', '/app/core/support_db.py', '0c03fa10578b8e4fb7bd8c17f1e489a23d161c73874cbb9bb0310d62f82eb4f7'),
)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class Refused(Exception):
    def __init__(self, code): self.code = code


class Deadline(BaseException):
    pass


def tick(end):
    if time.monotonic() >= end: raise Refused('time_limit')


def ident(s): return s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid


def stamp(s): return ident(s) + (s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def numbers(s):
    return {'device': s.st_dev, 'inode': s.st_ino, 'mode': stat.S_IMODE(s.st_mode),
            'uid': s.st_uid, 'gid': s.st_gid, 'links': s.st_nlink, 'bytes': s.st_size}


def json_read(raw):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out: raise Refused('invalid_metadata')
            out[k] = v
        return out
    try: return json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError): raise Refused('invalid_metadata') from None


def path_parts(path):
    if (not isinstance(path, str) or not path.startswith('/') or len(path) > 4096 or
            '\\' in path or any(ord(c) < 32 or ord(c) == 127 for c in path) or
            any(p in ('.', '..') for p in path.split('/'))):
        raise Refused('path_uncovered')
    return [p for p in path.split('/') if p]


def directory_allowed(info,path,owner,host):
    observed_parent=(host and owner==0 and path=='/root/ad-dashboard-deploy' and
                     info.st_uid==501 and info.st_gid==50 and stat.S_IMODE(info.st_mode)==0o755)
    return (stat.S_ISDIR(info.st_mode) and not info.st_mode&0o022 and
            (info.st_uid==owner or observed_parent))


class Files:
    """Alternative root/owner are synthetic-fixture seams, never CLI options."""
    def __init__(self, root='/', uid=0): self.root, self.uid = root, uid

    @contextlib.contextmanager
    def directory(self, path, base=None, secure=True):
        with contextlib.ExitStack() as stack:
            fd = os.open(self.root, DIR_FLAGS) if base is None else os.dup(base)
            stack.callback(os.close, fd)
            chain = [];current=''
            for part in path_parts(path):
                current+='/'+part
                before = os.stat(part, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISDIR(before.st_mode) or (secure and not directory_allowed(before,current,self.uid,base is None)):
                    raise Refused('unsafe_directory')
                child = os.open(part, DIR_FLAGS, dir_fd=fd); stack.callback(os.close, child)
                if ident(os.fstat(child)) != ident(before): raise Refused('path_changed')
                chain.append((fd, part, child, ident(before))); fd = child
            yield fd
            for parent, name, child, expected in chain:
                if ident(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected or ident(os.fstat(child)) != expected:
                    raise Refused('path_changed')

    def read(self, path, limit=MAX_READ, base=None, optional=False, secure=True):
        parent, name = path.rsplit('/', 1)
        with self.directory(parent or '/', base, secure) as directory:
            try: before = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                if optional: return None
                raise
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
                raise Refused('unsafe_file')
            fd = os.open(name, READ_FLAGS, dir_fd=directory)
            try:
                if ident(os.fstat(fd)) != ident(before): raise Refused('path_changed')
                out = bytearray()
                while True:
                    block = os.read(fd, min(8192, limit + 1 - len(out)))
                    if not block: break
                    out.extend(block)
                    if len(out) > limit: raise Refused('read_limit')
                if stamp(os.fstat(fd)) != stamp(before) or stamp(os.stat(name, dir_fd=directory, follow_symlinks=False)) != stamp(before):
                    raise Refused('path_changed')
                return bytes(out)
            finally: os.close(fd)

    def mount_id(self, fd):
        if self.root != '/': return 1  # Synthetic filesystem fixture only.
        with open('/proc/self/fdinfo/' + str(fd), 'rb') as stream: raw = stream.read(4097)
        if len(raw) > 4096: raise Refused('mount_unconfirmed')
        rows = re.findall(rb'^mnt_id:\s*([0-9]+)\s*$', raw, re.M)
        if len(rows) != 1: raise Refused('mount_unconfirmed')
        return int(rows[0])

    def bind_identity(self,path,container_base):
        with self.directory(path) as host,self.directory('/app/data',container_base) as inside:
            a,b=os.fstat(host),os.fstat(inside)
            if (a.st_dev,a.st_ino)!=(b.st_dev,b.st_ino):raise Refused('mount_identity_mismatch')
            return numbers(a)


def scan_tree(files, path, end, base=None, identities=None, budget=None):
    identities = identities if identities is not None else set()
    budget = budget if budget is not None else {'files': 0}
    result = {'files': 0, 'directories': 0, 'bytes': 0, 'blocks_bytes': 0}
    with files.directory(path, base, secure=base is None) as root:
        device, mount = os.fstat(root).st_dev, files.mount_id(root)
        result['directory_identity'] = numbers(os.fstat(root))
        def walk(fd, depth):
            tick(end)
            if depth > MAX_DEPTH: raise Refused('depth_limit')
            before = os.fstat(fd)
            with os.scandir(fd) as entries:
                for row in entries:
                    tick(end); budget['files'] += 1
                    if budget['files'] > MAX_FILES: raise Refused('file_count_limit')
                    s = os.stat(row.name, dir_fd=fd, follow_symlinks=False)
                    if s.st_dev != device: raise Refused('filesystem_boundary')
                    if stat.S_ISDIR(s.st_mode):
                        child = os.open(row.name, DIR_FLAGS, dir_fd=fd)
                        try:
                            if ident(os.fstat(child)) != ident(s): raise Refused('path_changed')
                            if files.mount_id(child) != mount: raise Refused('filesystem_boundary')
                            result['directories'] += 1; walk(child, depth + 1)
                        finally: os.close(child)
                    elif stat.S_ISREG(s.st_mode):
                        if s.st_nlink != 1: raise Refused('hardlink_unresolved')
                        result['files'] += 1; result['bytes'] += s.st_size
                        result['blocks_bytes'] += s.st_blocks * 512
                        identities.add((s.st_dev, s.st_ino))
                    else: raise Refused('link_or_special_uncovered')
                    if stamp(os.stat(row.name, dir_fd=fd, follow_symlinks=False)) != stamp(s): raise Refused('tree_changed')
            if stamp(os.fstat(fd)) != stamp(before): raise Refused('tree_changed')
        walk(root, 0)
    return result


def dotenv(raw):
    """Strict relevant-key subset. Complex expansion/quoting is refused, never guessed."""
    out = {}
    if raw is None: return out
    for line in raw.decode('utf-8', 'strict').splitlines():
        candidate = line.strip()
        if candidate.startswith('export '): candidate = candidate[7:].lstrip()
        key, separator, value = candidate.partition('=')
        key = key.strip()
        if key not in DB_KEYS: continue
        if not separator or key in out: raise Refused('db_config_ambiguous')
        value = value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]: raise Refused('db_config_ambiguous')
            value = value[1:-1]
        elif any(c.isspace() for c in value) or '#' in value: raise Refused('db_config_ambiguous')
        if any(c in value for c in ('$','`','\\','\0','\r','\n')) or len(value) > 4096:
            raise Refused('db_config_ambiguous')
        out[key] = value
    return out


def initial_env(rows):
    if not isinstance(rows, list) or len(rows) > len(DB_KEYS): raise Refused('db_config_ambiguous')
    out = {}
    for row in rows:
        if not isinstance(row, str) or len(row) > 8192: raise Refused('db_config_ambiguous')
        key, sep, value = row.partition('=')
        if key not in DB_KEYS or not sep or key in out: raise Refused('db_config_ambiguous')
        out[key] = value
    return out


def covered_path(value, cwd, prefix):
    if not isinstance(value, str) or not value or any(c in value for c in ('$','`','\\','?','#','\0')):
        raise Refused('db_config_ambiguous')
    path_parts(value if value.startswith('/') else '/' + value)
    value = posixpath.join(cwd, value) if not value.startswith('/') else value
    if not value.startswith(prefix + '/') or value.endswith('/'):
        raise Refused('database_path_uncovered')
    return value


def resolve_routes(ad_env, content_env, content_dotenv, autobid_dotenv, cwd):
    if cwd != {'ad': '/app', 'content': '/app'}: raise Refused('cwd_unconfirmed')
    covered_path(ad_env.get('DB_PATH') or '/app/app.db', cwd['ad'], '/app/data')
    merged = dict(content_dotenv); merged.update(content_env)  # load_dotenv override=False.
    for key, default in DBS:
        value = merged.get(key, '/app/data/' + default)
        covered_path(value, cwd['content'], '/tmp' if value.startswith('/tmp/') else '/app/data')
    url = autobid_dotenv.get('AUTOBID_DATABASE_URL', '')
    if not url.startswith('sqlite:////'): raise Refused('database_driver_or_path_uncovered')
    covered_path(url[len('sqlite:///'):], '/srv/autobid', '/srv/autobid/data')
    return {'configured_routes': 11, 'fallback_routes': len(FALLBACKS),
            'coverage': 'configured_and_all_known_fallbacks_covered', 'runtime_selection': 'not_proven'}


class Docker:
    def __init__(self, end, runner=None): self.end, self.runner = end, runner
    def run(self, args):
        tick(self.end)
        if self.runner is not None: return self.runner(args)
        p = subprocess.Popen(['/usr/bin/docker', *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, shell=False, start_new_session=True,
                             env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','LC_ALL':'C'})
        try:
            out, count = bytearray(), 0
            with selectors.DefaultSelector() as selected:
                selected.register(p.stdout, selectors.EVENT_READ, True); selected.register(p.stderr, selectors.EVENT_READ, False)
                while selected.get_map():
                    tick(self.end)
                    for key, _ in selected.select(.1):
                        block = os.read(key.fd, 8192)
                        if not block: selected.unregister(key.fileobj); continue
                        count += len(block)
                        if count > MAX_COMMAND: raise Refused('command_limit')
                        if key.data: out.extend(block)
            if p.wait(timeout=max(.01, self.end-time.monotonic())) != 0: raise Refused('command_failed')
            return bytes(out)
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL); p.wait(timeout=2)
            p.stdout.close(); p.stderr.close()

    def inspect(self, alias, container, pid):
        conditions = ' '.join('(eq (index (split $e "=") 0) "' + key + '")' for key in sorted(DB_KEYS))
        env = '{{$first := true}}[{{range $e := .Config.Env}}{{if or '+conditions+'}}{{if not $first}},{{end}}{{json $e}}{{$first = false}}{{end}}{{end}}]'
        template = ('{"id":{{json .Id}},"image":{{json .Image}},"name":{{json .Name}},"pid":{{json .State.Pid}},'
                    '"running":{{json .State.Running}},"workdir":{{json .Config.WorkingDir}},"mounts":{{json .Mounts}},"env":'+env+'}')
        value = json_read(self.run(['inspect','--format',template,container]))
        if (not isinstance(value,dict) or value.get('id') != container or value.get('image') != IMAGES[alias] or
                value.get('name') != NAMES[alias] or value.get('running') is not True or value.get('pid') != pid or type(value.get('pid')) is not int or
                value.get('workdir') != '/app'): raise Refused('container_changed')
        mounts = value.get('mounts')
        if (not isinstance(mounts,list) or len(mounts) != 1 or not isinstance(mounts[0],dict) or
                any(mounts[0].get(k) != v for k,v in {'Type':'bind','Source':ROOTS[alias],'Destination':'/app/data','RW':True}.items())):
            raise Refused('mount_uncovered')
        value['env'] = initial_env(value['env'])
        return value

    def volume(self):
        template = '{"name":{{json .Name}},"driver":{{json .Driver}},"path":{{json .Mountpoint}},"options":{{if .Options}}true{{else}}false{{end}}}'
        value = json_read(self.run(['volume','inspect','--format',template,VOLUME]))
        if value != {'name':VOLUME,'driver':'local','path':ROOTS['autobid'],'options':False}: raise Refused('volume_uncovered')
        if self.run(['ps','-aq','--no-trunc','--filter','volume='+VOLUME]).strip(): raise Refused('autobid_container_present')
        return value

    def workers(self, container, init):
        lines = self.run(['top',container,'-eo','pid,ppid']).decode('ascii','strict').splitlines()
        if not lines or lines[0].split() != ['PID','PPID']: raise Refused('workers_unconfirmed')
        rows = []
        for line in lines[1:]:
            fields = line.split()
            if len(fields) != 2 or not all(x.isdigit() for x in fields): raise Refused('workers_unconfirmed')
            rows.append(tuple(map(int,fields)))
        if not 1 <= len(rows) <= 64 or len({p for p,_ in rows}) != len(rows) or init not in {p for p,_ in rows}:
            raise Refused('workers_unconfirmed')
        return sorted(rows)


class Proc:
    def __init__(self, files, root='/proc'): self.files, self.root = files, root
    def read(self, pid, name, limit=MAX_READ):
        return self.files.read(self.root+'/'+str(pid)+'/'+name,limit,secure=False)
    @contextlib.contextmanager
    def root_fd(self,pid):
        with self.files.directory(self.root+'/'+str(pid),secure=False) as folder:
            # Explicit kernel /proc/PID/root exception; inner paths stay no-follow.
            fd=os.open('root',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC,dir_fd=folder)
            try: yield fd
            finally: os.close(fd)
    def identity(self,pid):
        raw=self.read(pid,'stat',4096); end=raw.rfind(b')'); fields=raw[end+1:].split()
        if end<0 or raw[:raw.find(b'(')].strip()!=str(pid).encode() or len(fields)<20:
            raise Refused('process_identity_invalid')
        with self.files.directory(self.root+'/'+str(pid)+'/ns',secure=False) as ns:
            a,b=os.stat('pid',dir_fd=ns),os.stat('mnt',dir_fd=ns)
        return (int(fields[19]),int(fields[1]),a.st_dev,a.st_ino,b.st_dev,b.st_ino)
    def cwd(self,pid):
        with self.files.directory(self.root+'/'+str(pid),secure=False) as folder:
            path=os.readlink('cwd',dir_fd=folder)
        if len(path)>4096: raise Refused('cwd_unconfirmed')
        return path
    def mounts(self,pid):
        out={}
        for line in self.read(pid,'mountinfo').splitlines():
            left,sep,right=line.partition(b' - ');fields=left.split();tail=right.split()
            if not sep or len(fields)<6 or len(tail)<3 or not fields[0].isdigit():raise Refused('mount_unconfirmed')
            number=int(fields[0])
            if number in out:raise Refused('mount_unconfirmed')
            out[number]={'memory_backed_hint':tail[0] in (b'tmpfs',b'ramfs'),
                         'readonly_hint':b'ro' in fields[5].split(b',')}
        return out
    def pids(self):
        with self.files.directory(self.root,secure=False) as folder:
            with os.scandir(folder) as rows:
                out=[]
                for row in rows:
                    if row.name.isascii() and row.name.isdigit():
                        out.append(int(row.name))
                        if len(out)>MAX_PIDS: raise Refused('pid_limit')
        return set(out)


def fd_flags(raw):
    rows=re.findall(rb'^flags:\s*([0-7]+)\s*$',raw,re.M)
    mounts=re.findall(rb'^mnt_id:\s*([0-9]+)\s*$',raw,re.M)
    if len(rows)!=1 or len(mounts)!=1: raise Refused('fd_metadata_invalid')
    return int(rows[0],8),int(mounts[0])


def scan_host(proc, covered, owners, content_pids, end, owner_scopes=None, private=None):
    """Two complete host passes, then at most64 newly born PIDs; never a future lock."""
    result={'pids':0,'fds':0,'shared_writable_maps':0,'covered_writable_fds':0,
            'covered_shared_writable_maps':0,'external_writers':0,'target_uncovered_writers':0,
            'exited_pids':0,'deleted_identities':[], 'host_passes':2,
            'unrelated_fd_changes':0,'unrelated_mapping_changes':0,
            'unrelated_process_changes':0,'late_processes_scanned':0}
    deleted={};deleted_refs={};content_deleted_ids=set();seen_processes=set();seen_live=set()
    covered_fds=set();covered_maps=set();all_maps=set();external=set();uncovered=set()
    def in_scope(target, namespace):
        path=target[:-10] if target.endswith(' (deleted)') else target
        if any(path.startswith(directory+'/') for directory in ROOTS.values()):return True
        alias=(owner_scopes or {}).get(namespace)
        return bool(alias and (path.startswith('/app/data/') or (alias=='content' and path.startswith('/tmp/'))))
    def map_rows(raw,before,pid):
        relevant=set()
        for line in raw.splitlines():
            fields=line.split(None,5)
            if len(fields)<5 or re.fullmatch(rb'[r-][w-][x-][sp]',fields[1]) is None:raise Refused('maps_invalid')
            if fields[1][1:2]!=b'w' or fields[1][3:4]!=b's':continue
            if (re.fullmatch(rb'[0-9a-f]+:[0-9a-f]+',fields[3]) is None or not fields[4].isdigit() or
                    re.fullmatch(rb'[0-9a-f]+-[0-9a-f]+',fields[0]) is None):raise Refused('maps_invalid')
            major,minor=(int(x,16) for x in fields[3].split(b':'));inode=int(fields[4])
            identity=(os.makedev(major,minor),inode)
            target=fields[5].decode('utf-8','strict') if len(fields)==6 else ''
            token=(pid,before[0],fields[0],fields[1],fields[2],identity)
            all_maps.add(token)
            if not inode:continue
            matched=identity in covered or in_scope(target,before[2:])
            if matched:
                relevant.add(token);covered_maps.add(token)
                if pid not in owners:external.add(('map',)+token)
            elif pid in owners:uncovered.add(('map',)+token)
        return relevant
    def observe(pid):
        tick(end);seen_live.add(pid)
        if pid==os.getpid():
            result['readonly_observer_pid']=pid
            return
        relevant=False
        try:
            before=proc.identity(pid);seen_processes.add((pid,before[0]))
            if len(seen_processes)>MAX_PIDS:raise Refused('pid_limit')
            mounts=None
            with proc.files.directory(proc.root+'/'+str(pid)+'/fd',secure=False) as fds:
                initial=set(os.listdir(fds))
                if len(initial)>MAX_PID_FDS:raise Refused('fd_limit')
                def inspect_fd(name):
                    nonlocal relevant,mounts
                    tick(end);result['fds']+=1
                    if result['fds']>MAX_FDS or not re.fullmatch('[0-9]{1,10}',name):raise Refused('fd_limit')
                    matched=False
                    try:
                        info=os.stat(name,dir_fd=fds)
                        if not stat.S_ISREG(info.st_mode):return
                        target=os.readlink(name,dir_fd=fds)
                        if len(target)>4096:raise Refused('fd_metadata_invalid')
                        identity=(info.st_dev,info.st_ino)
                        matched=identity in covered or in_scope(target,before[2:])
                        relevant|=matched
                        flags,mount=fd_flags(proc.read(pid,'fdinfo/'+name,4096))
                        access=flags&os.O_ACCMODE
                        if access not in (os.O_RDONLY,os.O_WRONLY,os.O_RDWR):raise Refused('fd_metadata_invalid')
                        writable=access!=os.O_RDONLY;key=(pid,before[0],int(name),identity)
                        if writable and matched:
                            covered_fds.add(key)
                            if pid not in owners:external.add(('fd',)+key)
                        if pid in owners and writable and not matched and info.st_nlink:uncovered.add(('fd',)+key)
                        if pid in owners and info.st_nlink==0:
                            if mounts is None:mounts=proc.mounts(pid)
                            if mount not in mounts:raise Refused('mount_unconfirmed')
                            if identity not in deleted:
                                if len(deleted)>=MAX_DELETED:raise Refused('deleted_limit')
                                deleted_refs[identity]={}
                            row=numbers(info);row.update(mount_id=mount,writable=writable,
                                app='content' if pid in content_pids else 'ad',references=0,
                                heartbeat_path_compatible=bool(re.fullmatch(r'/dev/shm/wgunicorn-[a-z0-9_]{8} \(deleted\)',target)))
                            row.update(mounts[mount])
                            if identity in deleted and deleted[identity]['app']!=row['app']:row['app']='shared'
                            deleted[identity]=row
                            if pid in content_pids:content_deleted_ids.add(identity)
                            deleted_refs[identity][key]={'pid':pid,'fd':int(name),'process_identity':before,
                                'file_identity':stamp(info),'flags':flags,'mount_id':mount}
                            if sum(len(refs) for refs in deleted_refs.values())>MAX_DELETED_REFS:raise Refused('deleted_ref_limit')
                        if pid in owners or matched:
                            if (stamp(os.stat(name,dir_fd=fds))!=stamp(info) or
                                    fd_flags(proc.read(pid,'fdinfo/'+name,4096))!=(flags,mount) or
                                    os.readlink(name,dir_fd=fds)!=target):raise Refused('fd_changed')
                    except (FileNotFoundError,ProcessLookupError):
                        if pid in owners or matched:raise Refused('relevant_file_changed') from None
                        result['unrelated_fd_changes']+=1
                for name in initial:inspect_fd(name)
                after=set(os.listdir(fds))
                if len(after)>MAX_PID_FDS:raise Refused('fd_limit')
                if after!=initial:
                    if pid in owners:raise Refused('fd_set_changed')
                    result['unrelated_fd_changes']+=1
                    # New descriptors are observed now; the complete second
                    # pass also covers births after this per-process window.
                    for name in after-initial:inspect_fd(name)
            maps=proc.read(pid,'maps',MAX_MAPS);first=map_rows(maps,before,pid)
            again=proc.read(pid,'maps',MAX_MAPS);second=map_rows(again,before,pid)
            relevant|=bool(first or second)
            if maps!=again:
                if pid in owners or first!=second:raise Refused('maps_changed')
                result['unrelated_mapping_changes']+=1
            if proc.identity(pid)!=before:
                if pid in owners or relevant:raise Refused('process_changed')
                result['unrelated_process_changes']+=1
        except (FileNotFoundError,ProcessLookupError):
            if pid in owners or relevant:raise Refused('relevant_process_changed') from None
            result['exited_pids']+=1
    for _ in range(2):
        population=proc.pids()
        for pid in sorted(population):observe(pid)
    # A finite tail observes processes born during pass2 without requiring the
    # unrelated host to become motionless. Continued unobserved births refuse.
    tail=proc.pids()-population
    if len(tail)>64:raise Refused('pid_visibility_limit')
    for pid in sorted(tail):observe(pid);result['late_processes_scanned']+=1
    if proc.pids()-seen_live:raise Refused('pid_visibility_incomplete')
    for identity,row in deleted.items():row['references']=len(deleted_refs[identity])
    result.update(pids=len(seen_processes),shared_writable_maps=len(all_maps),covered_writable_fds=len(covered_fds),
        covered_shared_writable_maps=len(covered_maps),external_writers=len(external),target_uncovered_writers=len(uncovered))
    result['deleted_identities']=list(deleted.values());result['deleted_unique_count']=len(deleted)
    content_deleted=[row for identity,row in deleted.items() if identity in content_deleted_ids]
    result['content_deleted_unique_count']=len(content_deleted)
    result['prior_four_zero_pattern_matches']=(len(content_deleted)==4 and all(r['bytes']==0 and r['links']==0 and r['heartbeat_path_compatible'] for r in content_deleted))
    if private is not None:private['deleted_files']={identity:list(refs.values()) for identity,refs in deleted_refs.items()}
    return result


def collect(request,files=None,docker=None,proc=None,end=None,private=None):
    end=end if end is not None else time.monotonic()+TIMEOUT
    files=files or Files(); docker=docker or Docker(end);proc=proc or Proc(files)
    report={'status':'incomplete','error':None,'read_only':True,'stop_safety':'not_determined',
            'runtime_selection':'not_proven','data_sets':[],'candidates':[],'host':None,'routes':None,'checks':{}}
    if private is not None:private.clear()
    try:
        if set(request)!={'ad','content'}: raise Refused('request_refused')
        guards={}; workers={}; identities={};cwd={}
        for alias in ('ad','content'):
            value=request[alias]
            if (not isinstance(value,dict) or set(value)!={'id','pid'} or not isinstance(value['id'],str) or re.fullmatch('[0-9a-f]{64}',value['id']) is None or
                    type(value['pid']) is not int or not 0<value['pid']<=4294967295):raise Refused('request_refused')
            guards[alias]=docker.inspect(alias,value['id'],value['pid'])
            workers[alias]=docker.workers(value['id'],value['pid'])
            for pid,ppid in workers[alias]:
                current=proc.identity(pid)
                if current[1]!=ppid:raise Refused('worker_changed')
                if pid in identities: raise Refused('worker_changed')
                identities[pid]=current
                if proc.cwd(pid)!='/app':raise Refused('cwd_unconfirmed')
            init=identities[value['pid']]
            if any(identities[pid][2:]!=init[2:] for pid,_ in workers[alias]):raise Refused('namespace_changed')
            cwd[alias]='/app'
        volume=docker.volume(); report['checks']['container_mount_volume']=True
        with contextlib.ExitStack() as stack:
            roots={alias:stack.enter_context(proc.root_fd(request[alias]['pid'])) for alias in ('ad','content')}
            bind_identities={alias:files.bind_identity(ROOTS[alias],base) for alias,base in roots.items()}
            for alias,path,digest in SOURCE_PINS:
                body=files.read(path,262144,base=roots[alias])
                if hashlib.sha256(body).hexdigest()!=digest:raise Refused('source_unreviewed')
            report['checks']['reviewed_route_sources']=True
            dot=dotenv(files.read('/app/.env',base=roots['content'],optional=True))
            auto=dotenv(files.read('/root/content-studio-deploy/autobid/.env'))
            report['routes']=resolve_routes(guards['ad']['env'],guards['content']['env'],dot,auto,cwd)
            report['checks']['route_coverage']=True
            covered=set();budget={'files':0}
            for alias,path in ROOTS.items():
                row=scan_tree(files,path,end,identities=covered,budget=budget);row['alias']=alias;report['data_sets'].append(row)
            report['tmp']=scan_tree(files,'/tmp',end,base=roots['content'],identities=covered,budget=budget)
            report['checks']['tree_coverage']=True
            for index,path in enumerate(CANDIDATES,1):
                parent,name=path.rsplit('/',1)
                with files.directory(parent,base=roots['content'],secure=False) as fd:
                    try:s=os.stat(name,dir_fd=fd,follow_symlinks=False)
                    except FileNotFoundError:report['candidates'].append({'alias':index,'status':'absent'});continue
                    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise Refused('candidate_uncovered')
                    row=numbers(s);row.update(alias=index,status='present');report['candidates'].append(row)
            content_pids={pid for pid,_ in workers['content']}
            scopes={identities[pid][2:]:alias for alias,rows in workers.items() for pid,_ in rows}
            report['host']=scan_host(proc,covered,set(identities),content_pids,end,scopes,private)
            report['checks']['host_scan']=True
            for alias,value in request.items():
                if docker.inspect(alias,value['id'],value['pid'])!=guards[alias] or docker.workers(value['id'],value['pid'])!=workers[alias]:
                    raise Refused('container_changed')
            if docker.volume()!=volume or any(proc.identity(pid)!=expected for pid,expected in identities.items()):
                raise Refused('process_changed')
            for row in report['data_sets']:
                with files.directory(ROOTS[row['alias']]) as fd:
                    current=numbers(os.fstat(fd));previous=row['directory_identity']
                    if any(current[key]!=previous[key] for key in ('device','inode','mode','uid','gid')):
                        raise Refused('path_changed')
            if any(files.bind_identity(ROOTS[alias],base)!=expected for alias,expected in bind_identities.items()
                   for base in (roots[alias],)):
                raise Refused('mount_identity_mismatch')
            report['checks']['final_guards']=True
            if private is not None:
                private.update(container_guards=guards,process_identities=identities,owner_scopes=scopes)
            if report['host']['external_writers'] or report['host']['target_uncovered_writers']:
                raise Refused('writers_unresolved')
            report['status']='coverage_complete'
    except Refused as error:report['error']=error.code
    except Deadline:report['error']='time_limit'
    except Exception:report['error']='observation_failed'
    if private is not None and report['status']!='coverage_complete':private.clear()
    return report


def expired(number,frame):raise Deadline()


class SafeParser(argparse.ArgumentParser):
    def error(self,message):raise Refused('request_refused')


def main():
    parser=SafeParser(add_help=False)
    for alias in ('ad','content'):
        parser.add_argument('--'+alias+'-container-id',required=True)
        parser.add_argument('--'+alias+'-init-pid',required=True,type=int)
    try:
        args=parser.parse_args()
        if os.geteuid()!=0:raise Refused('privilege_required')
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,TIMEOUT)
        request={alias:{'id':getattr(args,alias+'_container_id'),'pid':getattr(args,alias+'_init_pid')} for alias in ('ad','content')}
        report=collect(request)
    except Refused as error:
        report={'status':'incomplete','error':error.code,'read_only':True,'stop_safety':'not_determined'}
    except BaseException:
        report={'status':'incomplete','error':'request_or_deadline_refused','read_only':True,'stop_safety':'not_determined'}
    finally:signal.setitimer(signal.ITIMER_REAL,0)
    raw=json.dumps(report,separators=(',',':'))
    if len(raw)>65536:
        report['status']='incomplete'
        raw='{"status":"incomplete","error":"output_limit","read_only":true,"stop_safety":"not_determined"}'
    print(raw)
    return 0 if report['status']=='coverage_complete' and len(raw)<=65536 else 2


if __name__=='__main__':sys.exit(main())
