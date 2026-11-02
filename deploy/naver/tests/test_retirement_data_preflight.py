"""Synthetic filesystem/proc/Docker only. No live Docker, key, database, or SSH."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

PATH=Path(__file__).resolve().parents[1]/'retirement_data_preflight.py'
SPEC=importlib.util.spec_from_file_location('retirement_data_preflight',PATH)
s=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(s)
CANARY='PRIVATE_CUSTOMER_ENV_FILENAME_CANARY'


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.files=s.Files(str(self.root),os.getuid())
        self.end=time.monotonic()+10
        self.request={'ad':{'id':'a'*64,'pid':101},'content':{'id':'c'*64,'pid':201}}
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        # Synthetic /proc PIDs are unrelated to the real test runner PID.
        # In Linux CI the runner itself can legitimately be PID101 or201.
        self.stack.enter_context(mock.patch.object(s.os,'getpid',return_value=4294967295))
        native_readlink=os.readlink
        def virtual_fd_target(path,*args,**kwargs):
            value=native_readlink(path,*args,**kwargs)
            # FD symlinks must point at real fixture files for stat(), but their
            # target strings emulate the process namespace, not host tempfile.
            if (isinstance(path,str) and path.isdecimal() and kwargs.get('dir_fd') is not None and
                    isinstance(value,str) and value.startswith(str(self.root)+'/')):
                return value[len(str(self.root)):]
            return value
        self.stack.enter_context(mock.patch.object(s.os,'readlink',side_effect=virtual_fd_target))
        pins=[]
        for alias,entry in self.request.items():
            pid=entry['pid'];base=self.root/('containers/'+alias)
            self.mkdir('/containers/'+alias+'/app/data');self.mkdir('/containers/'+alias+'/tmp',0o1777)
            self.write('/containers/'+alias+'/app/safe_db_route.py',b'PUBLIC_REVIEWED_ROUTE_SOURCE')
            pins.append((alias,'/app/safe_db_route.py',hashlib.sha256(b'PUBLIC_REVIEWED_ROUTE_SOURCE').hexdigest()))
            self.mkdir('/proc/'+str(pid)+'/fd');self.mkdir('/proc/'+str(pid)+'/fdinfo');self.mkdir('/proc/'+str(pid)+'/ns')
            self.write('/proc/'+str(pid)+'/ns/pid',b'');self.write('/proc/'+str(pid)+'/ns/mnt',b'')
            fields=[b'S',b'1']+[b'0']*17+[str(pid+1000).encode()]
            self.write('/proc/'+str(pid)+'/stat',str(pid).encode()+b' (synthetic) '+b' '.join(fields))
            self.write('/proc/'+str(pid)+'/maps',b'')
            self.write('/proc/'+str(pid)+'/mountinfo',b'1 0 0:1 / /dev/shm rw - tmpfs tmpfs rw\n')
            os.symlink(base,self.local('/proc/'+str(pid)+'/root'))
            os.symlink('/app',self.local('/proc/'+str(pid)+'/cwd'))
        self.stack.enter_context(mock.patch.object(s,'SOURCE_PINS',tuple(pins)))
        for path in s.ROOTS.values():self.mkdir(path)
        self.write(s.ROOTS['ad']+'/app.db',CANARY.encode())
        self.write(s.ROOTS['content']+'/auth.db',b'SYNTHETIC_DB_NOT_OPENED')
        self.write(s.ROOTS['autobid']+'/autobid.db',b'SYNTHETIC_WAL_DATABASE')
        self.write('/containers/content/tmp/studio_copy_library.db',b'SYNTHETIC_INTERNAL_DATABASE')
        self.write('/containers/content/app/.env',('SECRET='+CANARY+'\nSTUDIO_AUTH_DB=/app/data/auth.db\n').encode())
        self.write('/root/content-studio-deploy/autobid/.env',('AUTOBID_ENC_KEY='+CANARY+'\nAUTOBID_DATABASE_URL=sqlite:////srv/autobid/data/autobid.db\n').encode())
        self.env={'ad':['DB_PATH=/app/data/app.db'],'content':[]}
        self.docker=s.Docker(self.end,self.run_docker);self.proc=s.Proc(self.files)
        self.stack.enter_context(mock.patch.object(self.files,'bind_identity',side_effect=self.fake_bind))
        self.commands=[]

    def local(self,path):return self.root/path.lstrip('/')
    def mkdir(self,path,mode=0o700):
        self.local(path).mkdir(parents=True,exist_ok=True)
        self.local(path).chmod(mode)
    def write(self,path,body):
        self.local(path).parent.mkdir(parents=True,exist_ok=True)
        self.local(path).write_bytes(body);self.local(path).chmod(0o600)
    def fake_bind(self,path,base):
        # Synthetic mount adapter: macOS fixtures cannot create Linux bind mounts.
        self.assertIn(path,(s.ROOTS['ad'],s.ROOTS['content']))
        self.assertTrue(stat.S_ISDIR(os.fstat(base).st_mode))
        return s.numbers(self.local(path).stat())
    def run_docker(self,args):
        self.commands.append(args)
        if args[0]=='inspect':
            alias='ad' if args[-1]=='a'*64 else 'content';v=self.request[alias]
            return json.dumps({'id':v['id'],'image':s.IMAGES[alias],'name':s.NAMES[alias],
                'pid':v['pid'],'running':True,'workdir':'/app','env':self.env[alias],
                'mounts':[{'Type':'bind','Source':s.ROOTS[alias],'Destination':'/app/data','RW':True}]}).encode()
        if args[0]=='top':return b'PID PPID\n'+(b'101 1\n' if args[1]=='a'*64 else b'201 1\n')
        if args[:2]==['volume','inspect']:
            return json.dumps({'name':s.VOLUME,'driver':'local','path':s.ROOTS['autobid'],'options':False}).encode()
        if args[0]=='ps':return b''
        raise AssertionError('Unexpected synthetic command')
    def collect(self):return s.collect(self.request,self.files,self.docker,self.proc,self.end)
    def assert_safe(self,result):
        raw=json.dumps(result)
        for bad in (CANARY,'app.db','auth.db','/root/','/app/','sqlite:','PUBLIC_REVIEWED'):
            self.assertNotIn(bad,raw)
        self.assertEqual(result['stop_safety'],'not_determined')
        self.assertEqual(result['runtime_selection'],'not_proven')
        self.assertNotIn('root',raw)
    def covered(self):
        return {(p.stat().st_dev,p.stat().st_ino) for path in s.ROOTS.values() for p in self.local(path).iterdir()}
    def fd(self,pid,number,path,flags=2):
        os.symlink(self.local(path),self.local('/proc/'+str(pid)+'/fd/'+str(number)))
        self.write('/proc/'+str(pid)+'/fdinfo/'+str(number),('flags:\t'+oct(flags)[2:]+'\nmnt_id:\t1\n').encode())
    def map(self,pid,path,perms='rw-s'):
        info=self.local(path).stat();dev=f'{os.major(info.st_dev):x}:{os.minor(info.st_dev):x}'
        self.write('/proc/'+str(pid)+'/maps',('1000-2000 '+perms+' 00000000 '+dev+' '+str(info.st_ino)+' '+CANARY+'\n').encode())

    def test_complete_fixture_reports_finite_coverage_without_stop_claim(self):
        result=self.collect();self.assertEqual(result['status'],'coverage_complete',result)
        self.assertEqual(set(result['checks']),{'container_mount_volume','reviewed_route_sources','route_coverage','tree_coverage','host_scan','final_guards'})
        self.assertEqual(result['routes']['fallback_routes'],6);self.assertEqual(len(result['candidates']),32)
        self.assert_safe(result)
        self.assertTrue(all(command[0] in ('inspect','top','volume','ps') for command in self.commands))
    def test_real_observer_pid_collision_cannot_hide_synthetic_app_writer(self):
        for real_pid in (101,201):
            with self.subTest(real_pid=real_pid),mock.patch.object(s.os,'getpid',return_value=real_pid):
                fixture=Fixture('test_target_uncovered_writer_and_map_prevent_complete_coverage')
                try:
                    fixture.setUp()
                    fixture.write('/outside/'+CANARY,b'opaque');fixture.fd(201,3,'/outside/'+CANARY)
                    self.assertNotIn(s.os.getpid(),(101,201))
                    result=fixture.collect()
                    self.assertEqual(result['error'],'writers_unresolved',result)
                finally:fixture.doCleanups()
    def test_linux_tmp_fixture_prefix_is_not_a_content_container_tmp_path(self):
        original=tempfile.TemporaryDirectory
        # Reproduce Linux tempfile spelling on macOS as well: the kernel FD
        # target is /tmp/<fixture>/outside, not the container's own /tmp file.
        with mock.patch.object(tempfile,'TemporaryDirectory',side_effect=lambda:original(dir='/tmp')):
            fixture=Fixture('test_target_uncovered_writer_and_map_prevent_complete_coverage')
            try:
                fixture.setUp();self.assertTrue(str(fixture.root).startswith('/tmp/'))
                fixture.write('/outside/'+CANARY,b'opaque');fixture.fd(201,3,'/outside/'+CANARY)
                result=fixture.collect()
                self.assertEqual(result['error'],'writers_unresolved',result)
                self.assertEqual(result['host']['target_uncovered_writers'],1)
                self.assertEqual(result['host']['covered_writable_fds'],0)
            finally:fixture.doCleanups()
    def test_source_pin_mismatch_is_separate_failure_without_body(self):
        self.write('/containers/content/app/safe_db_route.py',CANARY.encode())
        result=self.collect();self.assertEqual(result['error'],'source_unreviewed');self.assert_safe(result)
    def test_unknown_database_route_fails_without_leaking_value(self):
        self.env['ad']=['DB_PATH=/elsewhere/'+CANARY]
        result=self.collect();self.assertEqual(result['error'],'database_path_uncovered');self.assert_safe(result)
    def test_content_tmp_override_is_covered_without_selecting_runtime_database(self):
        self.env['content']=['STUDIO_AUTH_DB=/tmp/auth.db']
        result=self.collect();self.assertEqual(result['status'],'coverage_complete',result);self.assert_safe(result)
    def test_container_mismatch_mount_extra_and_volume_options_fail(self):
        for mutation,want in ((lambda v:v.update(image='sha256:'+'0'*64),'container_changed'),
                              (lambda v:v['mounts'].append(dict(v['mounts'][0])),'mount_uncovered')):
            def changed(args):
                value=self.run_docker(args)
                if args[0]=='inspect':
                    data=json.loads(value);mutation(data);return json.dumps(data).encode()
                return value
            with self.subTest(want=want):
                result=s.collect(self.request,self.files,s.Docker(self.end,changed),self.proc,self.end)
                self.assertEqual(result['error'],want);self.assert_safe(result)
    def test_final_guard_rechecks_container_identity(self):
        count=0
        def changed(args):
            nonlocal count
            raw=self.run_docker(args)
            if args[0]=='inspect':
                count+=1
                if count>2:
                    value=json.loads(raw);value['pid']+=1;return json.dumps(value).encode()
            return raw
        result=s.collect(self.request,self.files,s.Docker(self.end,changed),self.proc,self.end)
        self.assertEqual(result['error'],'container_changed');self.assert_safe(result)
    def test_bind_inode_mismatch_blocks_path_only_mount_assumptions(self):
        with mock.patch.object(self.files,'bind_identity',side_effect=s.Refused('mount_identity_mismatch')):
            result=self.collect()
        self.assertEqual(result['error'],'mount_identity_mismatch');self.assert_safe(result)
        with self.files.directory('/containers/ad') as base,self.assertRaises(s.Refused):
            s.Files.bind_identity(self.files,s.ROOTS['ad'],base)
    def test_autobid_consumer_and_nonlocal_volume_are_refused(self):
        for scenario in ('consumer','options','driver'):
            def changed(args):
                raw=self.run_docker(args)
                if args[0]=='ps' and scenario=='consumer':return b'e'*64
                if args[:2]==['volume','inspect'] and scenario!='consumer':
                    value=json.loads(raw);value[scenario]=True if scenario=='options' else 'nfs';return json.dumps(value).encode()
                return raw
            result=s.collect(self.request,self.files,s.Docker(self.end,changed),self.proc,self.end)
            self.assertEqual(result['status'],'incomplete');self.assert_safe(result)
    def test_symlink_hardlink_and_special_entries_never_silently_omit(self):
        folder=self.local(s.ROOTS['ad']);target=folder/'app.db'
        for kind in ('symlink','hardlink','fifo'):
            extra=folder/CANARY
            if kind=='symlink':extra.symlink_to(target)
            elif kind=='hardlink':os.link(target,extra)
            else:os.mkfifo(extra)
            with self.subTest(kind=kind),self.assertRaises(s.Refused):s.scan_tree(self.files,s.ROOTS['ad'],self.end)
            extra.unlink()
    def test_root_parent_symlink_and_permission_change_are_refused(self):
        self.local('/root/ad-dashboard-deploy').rename(self.local('/root/original'))
        self.local('/root/ad-dashboard-deploy').symlink_to(self.local('/root/original'))
        with self.assertRaises(s.Refused):s.scan_tree(self.files,s.ROOTS['ad'],self.end)
    def test_tree_count_depth_and_nested_mount_limits(self):
        with mock.patch.object(s,'MAX_FILES',0),self.assertRaises(s.Refused):s.scan_tree(self.files,s.ROOTS['ad'],self.end)
        self.mkdir(s.ROOTS['ad']+'/nested')
        with mock.patch.object(s,'MAX_DEPTH',0),self.assertRaises(s.Refused):s.scan_tree(self.files,s.ROOTS['ad'],self.end)
        initial=True
        def mount(fd):
            nonlocal initial
            if initial:initial=False;return 1
            return 2
        with mock.patch.object(self.files,'mount_id',side_effect=mount),self.assertRaises(s.Refused):s.scan_tree(self.files,s.ROOTS['ad'],self.end)
    def test_tree_reads_metadata_not_database_bodies(self):
        original=os.open
        paths=[]
        def opened(path,flags,*args,**kw):
            paths.append((str(path),flags));return original(path,flags,*args,**kw)
        with mock.patch.object(os,'open',side_effect=opened):s.scan_tree(self.files,s.ROOTS['ad'],self.end)
        self.assertTrue(all(flags&os.O_DIRECTORY for _,flags in paths))
    def test_host_fd_writer_in_owner_and_external_are_distinguished(self):
        self.fd(101,3,s.ROOTS['ad']+'/app.db')
        result=s.scan_host(self.proc,self.covered(),{101,201},{201},self.end)
        self.assertEqual(result['covered_writable_fds'],1);self.assertEqual(result['external_writers'],0)
        result=s.scan_host(self.proc,self.covered(),{201},{201},self.end)
        self.assertEqual(result['external_writers'],1)
    def test_deleted_external_writer_is_detected_even_when_inode_absent_from_tree(self):
        self.fd(101,3,s.ROOTS['ad']+'/app.db')
        original=os.readlink
        def link(name,*args,**kwargs):
            return s.ROOTS['ad']+'/'+CANARY+' (deleted)' if name=='3' else original(name,*args,**kwargs)
        with mock.patch.object(os,'readlink',side_effect=link):
            result=s.scan_host(self.proc,set(),{201},{201},self.end)
        self.assertEqual(result['external_writers'],1)
        self.assertNotIn(CANARY,json.dumps(result))
    def test_four_zero_deleted_content_identities_are_fresh_metadata_not_excluded_writers(self):
        inodes=set()
        for number in range(3,7):
            path='/zero/'+str(number);self.write(path,b'');self.fd(201,number,path)
            inodes.add(self.local(path).stat().st_ino)
        original_stat,original_link=os.stat,os.readlink
        def observed(path,*args,**kwargs):
            value=original_stat(path,*args,**kwargs)
            if value.st_ino in inodes:
                result={name:getattr(value,name) for name in dir(value) if name.startswith('st_')}
                result['st_nlink']=0
                return types.SimpleNamespace(**result)
            return value
        def link(name,*args,**kwargs):
            if name in ('3','4','5','6'):return '/dev/shm/wgunicorn-abcd000'+name+' (deleted)'
            return original_link(name,*args,**kwargs)
        private={}
        with mock.patch.object(os,'stat',side_effect=observed),mock.patch.object(os,'readlink',side_effect=link):
            result=s.scan_host(self.proc,self.covered(),{101,201},{201},self.end,private=private)
        self.assertEqual(result['content_deleted_unique_count'],4)
        self.assertTrue(result['prior_four_zero_pattern_matches'])
        self.assertEqual(len(result['deleted_identities']),4)
        self.assertTrue(all(row['links']==0 and row['bytes']==0 for row in result['deleted_identities']))
        self.assertTrue(all(row['memory_backed_hint'] for row in result['deleted_identities']))
        self.assertEqual(sum(len(refs) for refs in private['deleted_files'].values()),4)
        self.assertTrue(all(ref['pid']==201 for refs in private['deleted_files'].values() for ref in refs))
        self.assertNotIn('"pid"',json.dumps(result))
    def test_failed_collection_clears_private_reuse_seam(self):
        private={'old':CANARY}
        result=s.collect(self.request,self.files,self.docker,self.proc,self.end,private)
        self.assertEqual(result['status'],'coverage_complete',result)
        self.assertIn('container_guards',private)
        self.env['ad']=['DB_PATH=/outside/'+CANARY]
        result=s.collect(self.request,self.files,self.docker,self.proc,self.end,private)
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(private,{})
    def test_shared_writable_map_is_detected_without_an_open_fd(self):
        self.map(101,s.ROOTS['autobid']+'/autobid.db')
        result=s.scan_host(self.proc,self.covered(),{201},{201},self.end)
        self.assertEqual(result['covered_shared_writable_maps'],1);self.assertEqual(result['external_writers'],1)
        self.map(101,s.ROOTS['autobid']+'/autobid.db','rw-p')
        self.assertEqual(s.scan_host(self.proc,self.covered(),set(),set(),self.end)['external_writers'],0)
    def test_target_uncovered_writer_and_map_prevent_complete_coverage(self):
        self.write('/outside/'+CANARY,b'opaque')
        self.fd(201,3,'/outside/'+CANARY)
        result=self.collect();self.assertEqual(result['error'],'writers_unresolved');self.assert_safe(result)
    def test_fd_metadata_race_and_bounds_fail_closed(self):
        self.fd(101,3,s.ROOTS['ad']+'/app.db')
        self.write('/proc/101/fdinfo/3',b'flags: 2\nflags: 2\nmnt_id: 1\n')
        with self.assertRaises(s.Refused):s.scan_host(self.proc,self.covered(),set(),set(),self.end)
        with mock.patch.object(s,'MAX_PIDS',1),self.assertRaises(s.Refused):self.proc.pids()
        with mock.patch.object(s,'MAX_PID_FDS',0),self.assertRaises(s.Refused):s.scan_host(self.proc,self.covered(),set(),set(),self.end)
    def test_relevant_process_start_namespace_changes_are_refused(self):
        original=self.proc.identity;counts={}
        def changed(pid):
            value=original(pid);counts[pid]=counts.get(pid,0)+1
            return ((value[0]+1,)+value[1:]) if counts[pid]>1 else value
        with mock.patch.object(self.proc,'identity',side_effect=changed),self.assertRaises(s.Refused):
            s.scan_host(self.proc,self.covered(),{101,201},{201},self.end)
    def test_maps_change_and_fd_flags_change_are_incomplete(self):
        original=self.proc.read;counts={}
        def changed(pid,name,limit=s.MAX_READ):
            raw=original(pid,name,limit);key=(pid,name);counts[key]=counts.get(key,0)+1
            if name=='maps' and counts[key]>1:return raw+b'changed'
            return raw
        with mock.patch.object(self.proc,'read',side_effect=changed),self.assertRaises(s.Refused):
            s.scan_host(self.proc,self.covered(),set(),set(),self.end)
        self.fd(101,3,s.ROOTS['ad']+'/app.db');counts.clear()
        def changed_flags(pid,name,limit=s.MAX_READ):
            raw=original(pid,name,limit);key=(pid,name);counts[key]=counts.get(key,0)+1
            return raw.replace(b'flags:\t2',b'flags:\t0') if name=='fdinfo/3' and counts[key]>1 else raw
        with mock.patch.object(self.proc,'read',side_effect=changed_flags),self.assertRaises(s.Refused):
            s.scan_host(self.proc,self.covered(),set(),set(),self.end)
    def test_unrelated_valid_mapping_and_process_churn_are_counted(self):
        original=self.proc.read;counts={}
        def changed(pid,name,limit=s.MAX_READ):
            raw=original(pid,name,limit)
            if name=='maps':
                counts[pid]=counts.get(pid,0)+1
                return b'1000-2000 rw-p 00000000 00:00 0 [anonymous]\n' if counts[pid]%2 else raw
            return raw
        with mock.patch.object(self.proc,'read',side_effect=changed):
            result=s.scan_host(self.proc,set(),set(),set(),self.end)
        self.assertEqual(result['unrelated_mapping_changes'],4)
        original_id=self.proc.identity;counts={}
        def identities(pid):
            value=original_id(pid);counts[pid]=counts.get(pid,0)+1
            return (value[0]+counts[pid],)+value[1:]
        with mock.patch.object(self.proc,'identity',side_effect=identities):
            result=s.scan_host(self.proc,set(),set(),set(),self.end)
        self.assertEqual(result['unrelated_process_changes'],4)
    def test_late_pid_is_observed_and_continued_unseen_births_refuse(self):
        # A newly visible existing synthetic PID is scanned in the finite tail.
        populations=[{101},{101},{101,201},{101,201}]
        with mock.patch.object(self.proc,'pids',side_effect=populations):
            result=s.scan_host(self.proc,set(),{101},{201},self.end)
        self.assertEqual(result['late_processes_scanned'],1)
        self.assertEqual(result['pids'],2)
        with mock.patch.object(self.proc,'pids',side_effect=[{101},{101},{101,201},{101,201,301}]):
            with self.assertRaisesRegex(s.Refused,'pid_visibility_incomplete'):
                s.scan_host(self.proc,set(),{101},{201},self.end)
        with mock.patch.object(self.proc,'pids',side_effect=[{101},{101},set(range(1000,1065))]):
            with self.assertRaisesRegex(s.Refused,'pid_visibility_limit'):
                s.scan_host(self.proc,set(),{101},{201},self.end)
    def test_unrelated_fdset_churn_is_observed_without_requiring_host_stillness(self):
        self.write('/outside/opaque',b'synthetic');self.fd(101,3,'/outside/opaque')
        original=os.listdir;counts={}
        def listing(fd):
            rows=original(fd)
            if '3' in rows:
                counts[fd]=counts.get(fd,0)+1
                return [] if counts[fd]%2 else rows
            return rows
        with mock.patch.object(os,'listdir',side_effect=listing):
            result=s.scan_host(self.proc,set(),{201},{201},self.end)
        self.assertGreater(result['unrelated_fd_changes'],0)
        self.assertEqual(result['external_writers'],0)
        with mock.patch.object(os,'listdir',side_effect=listing),self.assertRaises(s.Refused):
            s.scan_host(self.proc,set(),{101,201},{201},self.end)
    def test_new_fd_in_unrelated_process_is_scanned_for_relevant_writer(self):
        self.fd(101,3,s.ROOTS['ad']+'/app.db')
        original=os.listdir;count=0
        def listing(fd):
            nonlocal count
            rows=original(fd)
            if '3' in rows:
                count+=1
                return [] if count==1 else rows
            return rows
        with mock.patch.object(os,'listdir',side_effect=listing):
            result=s.scan_host(self.proc,self.covered(),{201},{201},self.end)
        self.assertEqual(result['external_writers'],1)
        self.assertGreater(result['unrelated_fd_changes'],0)
    def test_permission_or_proc_read_failure_never_means_no_writer(self):
        with mock.patch.object(self.proc,'read',side_effect=PermissionError(CANARY)):
            result=self.collect();self.assertEqual(result['status'],'incomplete');self.assert_safe(result)
    def test_deadline_and_bad_request_have_fixed_safe_errors(self):
        result=s.collect(self.request,self.files,self.docker,self.proc,time.monotonic()-1)
        self.assertEqual(result['status'],'incomplete');self.assert_safe(result)
        request={'ad':{'id':CANARY,'pid':101},'content':self.request['content']}
        result=s.collect(request,self.files,self.docker,self.proc,self.end)
        self.assertEqual(result['error'],'request_refused');self.assert_safe(result)


class Routes(unittest.TestCase):
    def test_only_exact_observed_host_parent_has_501_50_755_exception(self):
        good=types.SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=501,st_gid=50)
        self.assertTrue(s.directory_allowed(good,'/root/ad-dashboard-deploy',0,True))
        for path in ('/root/ad-dashboard-deploy/data','/root/content-studio-deploy','/root/other'):
            self.assertFalse(s.directory_allowed(good,path,0,True))
        self.assertFalse(s.directory_allowed(good,'/root/ad-dashboard-deploy',0,False))
        for key,value in (('st_gid',20),('st_uid',1000),('st_mode',stat.S_IFDIR|0o775)):
            changed=types.SimpleNamespace(**dict(vars(good),**{key:value}))
            self.assertFalse(s.directory_allowed(changed,'/root/ad-dashboard-deploy',0,True))
    def test_dotenv_selects_only_route_keys_and_environment_has_precedence(self):
        raw=('SECRET='+CANARY+'\nexport STUDIO_AUTH_DB="/app/data/auth.db"\n').encode()
        self.assertEqual(s.dotenv(raw),{'STUDIO_AUTH_DB':'/app/data/auth.db'})
        self.assertEqual(s.resolve_routes({'DB_PATH':'/app/data/app.db'},{'STUDIO_AUTH_DB':'/tmp/auth.db'},
            {'STUDIO_AUTH_DB':'/uncovered/ignored'}, {'AUTOBID_DATABASE_URL':'sqlite:////srv/autobid/data/autobid.db'},
            {'ad':'/app','content':'/app'})['configured_routes'],11)
    def test_interpolation_duplicate_complex_quote_and_non_sqlite_fail(self):
        for raw in (b'STUDIO_AUTH_DB=${PRIVATE}/app.db',b'STUDIO_AUTH_DB=a\nSTUDIO_AUTH_DB=b',
                    b'STUDIO_AUTH_DB="unterminated',b'STUDIO_AUTH_DB=a # comment'):
            with self.subTest(raw=raw),self.assertRaises(s.Refused):s.dotenv(raw)
        for url in ('mysql://'+CANARY,'sqlite:///relative.db','sqlite:////outside/app.db'):
            with self.assertRaises(s.Refused):s.resolve_routes({'DB_PATH':'/app/data/a'}, {}, {},
                {'AUTOBID_DATABASE_URL':url},{'ad':'/app','content':'/app'})
    def test_initial_env_duplicate_unknown_or_nonstring_rows_fail(self):
        for rows in (['DB_PATH=a','DB_PATH=b'],['SECRET='+CANARY],[True]):
            with self.assertRaises(s.Refused):s.initial_env(rows)
    def test_relative_path_needs_exact_cwd_and_rejects_dot_segments(self):
        self.assertEqual(s.covered_path('data/app.db','/app','/app/data'),'/app/data/app.db')
        for path in ('../data/app.db','./data/app.db','data/../x','data/'+CANARY+'\n'):
            with self.assertRaises(s.Refused):s.covered_path(path,'/app','/app/data')
    def test_json_duplicates_nan_and_unsafe_parser_arguments_are_rejected_without_text(self):
        for raw in (b'{"x":1,"x":2}',b'NaN'):
            with self.assertRaises(s.Refused):s.json_read(raw)
        output=io.StringIO()
        with mock.patch.object(sys,'argv',['preflight',CANARY]),contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            self.assertEqual(s.main(),2)
        self.assertNotIn(CANARY,output.getvalue())


if __name__=='__main__':unittest.main()
