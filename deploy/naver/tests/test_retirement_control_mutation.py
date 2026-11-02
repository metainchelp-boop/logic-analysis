"""Synthetic Docker, config tree and proof files only; no real CLI/server/key."""
import contextlib
import copy
import datetime
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

BASE=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('retirement_control_mutation',BASE/'retirement_control_mutation.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)
SPEC=importlib.util.spec_from_file_location('control_fixture',Path(__file__).with_name('test_retirement_control_preflight.py'))
f=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(f)
CANARY='PRIVATE_CONFIG_CUSTOMER_CANARY'


class FakeDocker:
    def __init__(self,request):
        self.states={};self.updates=[];self.kills=[];self.names=[]
        for alias,row in request.items():
            self.states[row['id']]={'id':row['id'],'image':m.FIXED_IMAGES[alias],'name':m.FIXED_NAMES[alias],'pid':row['pid'],
                'running':True,'paused':False,'restarting':False,'started_at':'2026-11-02T01:00:00Z','restart':{'Name':'unless-stopped','MaximumRetryCount':0}}
        self.states['b'*64]={'id':'b'*64,'image':'sha256:'+'d'*64,'name':'/logic-analysis','pid':301,'running':True,'paused':False,
            'restarting':False,'started_at':'2026-11-02T01:00:00Z','restart':{'Name':'unless-stopped','MaximumRetryCount':0}}
    def state(self,identifier):return copy.deepcopy(self.states[identifier])
    def inspect(self,alias,selection):return {k:v for k,v in self.state(selection['id']).items() if k!='started_at'}
    def version(self):return {'version':'29.4.0','git_commit':'c'*40,'os':'linux','arch':'amd64'}
    def update_no(self,identifier):self.updates.append(identifier);self.states[identifier]['restart']={'Name':'no','MaximumRetryCount':0}
    def kill(self,identifier):self.kills.append(identifier);self.states[identifier].update(running=False,paused=False,pid=0)
    def running_names(self):return self.names
    def listeners(self):return set()
    def auto_remove(self,identifier):return False


class Mutation(unittest.TestCase):
    def setUp(self):
        self.probe=f.Fixture('test_three_fixed_roles_selected_without_private_content_output');self.probe.setUp();self.addCleanup(self.probe.doCleanups)
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.files=m.Files(str(self.probe.base),os.getuid(),os.getgid(),self.exchange)
        self.request=copy.deepcopy(self.probe.request);self.docker=FakeDocker(self.request);self.calls=[]
        self.control=types.SimpleNamespace(collect=lambda request,docker:f.s.collect(request,files=self.probe.files,docker=docker))
        observed=self.control.collect(self.request,self.docker)
        self.assertEqual(observed['status'],'observed',observed)
        self.policy={'request':self.request,'files':observed['files'],'protected':[{'id':'b'*64,'image':'sha256:'+'d'*64}]}
        self.stack.enter_context(mock.patch.object(m,'PROTECTED',self.policy['protected']))
        self.stack.enter_context(mock.patch.object(m,'POLICY',self.policy))
        self.stack.enter_context(mock.patch.object(m,'OPERATOR_DOCUMENT',None))
        self.mkdir('/assets');self.mkdir('/root');self.directory='/assets'
        operator={'schema':1,'session':m.SESSION,'status':'known_deployments_disabled','actor':'metainchelp-boop',
            'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repository':'metainchelp-boop/metainc-content-studio',
            'other_workflows_unchanged':True,'other_workflows':[{'id':267160662,'path':'.github/workflows/validate.yml','state':'active'}],
            'workflows':[{'id':265254896,'path':'.github/workflows/deploy.yml','before':'active','after':'disabled_manually','active_runs':0},
                         {'id':322623002,'path':'.github/workflows/deploy-autobid.yml','before':'active','after':'disabled_manually','active_runs':0}]}
        self.operator=self.proof('deployment-fence-operator-evidence.json',operator,'OPERATOR_SHA')
    def mkdir(self,path):
        self.probe.local(path).mkdir(parents=True,mode=0o700,exist_ok=True)
    def put(self,path,body):
        target=self.probe.local(path);target.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        target.write_bytes(body);target.chmod(0o600)
    def exchange(self,folder,left,right):
        # macOS-only synthetic adapter; production uses atomic renameat2 exchange.
        saved=left+'.synthetic-swap'
        os.rename(left,saved,src_dir_fd=folder,dst_dir_fd=folder)
        os.rename(right,left,src_dir_fd=folder,dst_dir_fd=folder)
        os.rename(saved,right,src_dir_fd=folder,dst_dir_fd=folder)
    def proof(self,name,value,constant):
        body=m.canonical(value);self.put('/assets/'+name,body)
        self.stack.enter_context(mock.patch.object(m,constant,m.digest(body)));return value
    def runner(self,args,**kwargs):self.calls.append(args);return b'',0
    def freeze(self):
        rows={alias:self.docker.state(row['id']) for alias,row in self.request.items()}
        m.require(all(row['paused'] for row in rows.values()),'not_frozen')
        return rows
    def helper(self):return m.Mutation(self.files,self.docker,self.control,self.freeze,self.runner,self.directory,lambda _:None)
    def fence(self):return self.helper().run('fence',True,'101-1')
    def backup_ready(self):
        self.fence()
        for row in self.request.values():self.docker.states[row['id']]['paused']=True
        self.mkdir(m.TRANSFER.rsplit('/',1)[0])
        self.transfer={'phase':'send','status':'transferred_unverified','session':m.SESSION,'error':None,'ssh_public_key':None,
            'bytes':1000,'sha256':'e'*64,'process_rc':{'archive':0,'gpg':0,'ssh':0},'backup_verified':False,
            'source_bytes':100,'archive_bytes':10240,'object_count':8,'paused':{'ad':'paused','content':'paused'},
            'operator_evidence_sha256':m.OPERATOR_SHA,'run':'900-1'}
        body=m.canonical(self.transfer);self.put(m.TRANSFER,body)
        self.stack.enter_context(mock.patch.object(m,'SEND_SHA',m.digest(body)));self.stack.enter_context(mock.patch.object(m,'SOURCE_RUN','900-1'))
    def stop_ready(self):
        self.backup_ready();self.helper().run('maintenance',True,'102-1')
        proof=dict.fromkeys(('database_count','table_count','row_count','foreign_key_violations','decrypted_fields','content_json_checked',
            'content_json_failed','ad_decrypted_fields','autobid_decrypted_fields','decryption_failures','files_verified','source_bytes',
            'memory_only_files','deleted_objects','recovery_config_objects','recovery_config_absent'),0)
        proof.update(dict.fromkeys(('archive_authenticated','second_pass_identical','pristine_unchanged','sqlite_schema_counts_equal','ad_key_capsule_equal'),True))
        proof.update(dict.fromkeys(('production_sql_baseline_compared','dynamic_references_checked','application_restore_verified'),False))
        proof.update(status='isolated_data_checks_passed',session=m.SESSION,gpg_return_codes=[0,0,0],children_reaped=True,agent_cache_cleared=True,
            restore_sha256='3b4afdfb35db024c0b3203becd487bc9502d48384ecf4218515c266c95b41da7',data_cipher_sha256='e'*64,capsule_cipher_sha256='f'*64,
            source_bytes=100,files_verified=8)
        self.proof('retirement-local-restore-proof.json',proof,'LOCAL_RESTORE_SHA')
        self.stack.enter_context(mock.patch.object(m,'LOCAL_RESTORE_EXPECTED',proof))
        semantics={'schema':'metainc-retirement-kill-v1','daemon_version':'29.4.0','daemon_git_commit':'c'*40,'signal':'KILL',
                   'order':'task_kill_before_resume','source_commit':'c'*40,'source_sha256':'f'*64}
        self.proof('retirement-kill-semantics.json',semantics,'SEMANTICS_SHA')
    def test_auto_remove_adapter_requires_exact_boolean_and_fixed_inspect(self):
        identifier='a'*64
        for raw,expected in ((b'false\n',False),(b'true\n',True)):
            with self.subTest(raw=raw):
                docker=m.Docker('/synthetic-config')
                with mock.patch.object(docker,'run',return_value=raw) as run:
                    self.assertIs(docker.auto_remove(identifier),expected)
                    run.assert_called_once_with('inspect','--format','{{json .HostConfig.AutoRemove}}',identifier,limit=64)
        for raw in (b'0',b'1',b'null',b'"false"',b'[]',b'{}',b'false true',b'NaN'):
            with self.subTest(raw=raw),mock.patch.object(m.Docker,'run',return_value=raw),self.assertRaises(m.Refused):
                m.Docker('/synthetic-config').auto_remove(identifier)
    def test_stop_readiness_refuses_auto_remove_true_and_nonboolean(self):
        self.stop_ready()
        for bad in (True,0,1,None,'false'):
            with self.subTest(value=bad),mock.patch.object(self.docker,'auto_remove',return_value=bad),self.assertRaises(m.Refused):
                self.helper().run('stop',False,'103-1')
            self.assertEqual(self.docker.kills,[])
            self.assertFalse(self.probe.local(m.BASE+'/stop-attempt.json').exists())
    def test_auto_remove_rechecked_for_both_ids_before_first_kill(self):
        self.stop_ready();calls=[]
        def changed(identifier):
            calls.append(identifier);return len(calls)>4
        with mock.patch.object(self.docker,'auto_remove',side_effect=changed),self.assertRaises(m.Refused):
            self.helper().run('stop',True,'103-1')
        expected=[row['id'] for row in self.request.values()]
        self.assertEqual(calls[:4],expected+expected)
        self.assertEqual(len(calls),5);self.assertEqual(self.docker.kills,[])
        self.assertFalse(self.probe.local(m.BASE+'/stop-complete.json').exists())
    def test_fence_does_not_change_or_require_auto_remove_contract(self):
        with mock.patch.object(self.docker,'auto_remove',side_effect=AssertionError):
            self.assertEqual(self.fence()['status'],'completed')
    def test_sticky_tmp_only_exact_private_run_staging_is_readable(self):
        directory='/tmp/metainc-control-mutation-101-1'
        self.mkdir(directory);self.probe.local('/tmp').chmod(0o1777)
        self.put(directory+'/public.py',b'PUBLIC_SOURCE_ONLY')
        with self.assertRaises(m.Refused):self.files.read(directory+'/public.py')
        scoped=m.Files(str(self.probe.base),os.getuid(),os.getgid(),self.exchange,staging=directory)
        self.assertEqual(scoped.read(directory+'/public.py')[0],b'PUBLIC_SOURCE_ONLY')
        self.mkdir('/tmp/metainc-control-mutation-102-1');self.put('/tmp/metainc-control-mutation-102-1/public.py',b'OTHER')
        for path in ('/tmp','/tmp/metainc-control-mutation-102-1'):
            with self.assertRaises(m.Refused),scoped.directory(path):pass
        self.probe.local(directory).chmod(0o755)
        with self.assertRaises(m.Refused):scoped.read(directory+'/public.py')
    @unittest.skipUnless(sys.platform=='linux','Linux actual /tmp sticky directory contract')
    def test_actual_linux_sticky_tmp_staging_with_private_synthetic_file(self):
        directory='/tmp/metainc-control-mutation-'+str(os.getpid())+str(time.time_ns()%10**12)+'-1'
        target=Path(directory);target.mkdir(mode=0o700)
        try:
            public=target/'public.py';public.write_bytes(b'SYNTHETIC_PUBLIC_SOURCE');public.chmod(0o600)
            unscoped=m.Files(uid=os.getuid(),gid=os.getgid())
            with self.assertRaises(m.Refused):unscoped.read(str(public))
            scoped=m.Files(uid=os.getuid(),gid=os.getgid(),staging=directory)
            self.assertEqual(scoped.read(str(public))[0],b'SYNTHETIC_PUBLIC_SOURCE')
            target.chmod(0o755)
            with self.assertRaises(m.Refused):scoped.read(str(public))
        finally:
            public.unlink(missing_ok=True);target.rmdir()
    def test_staging_symlink_and_wrong_run_are_refused(self):
        directory='/tmp/metainc-control-mutation-101-1';self.mkdir(directory);self.probe.local('/tmp').chmod(0o1777)
        scoped=m.Files(str(self.probe.base),os.getuid(),os.getgid(),self.exchange,staging=directory)
        h=self.helper();h.files=scoped
        with self.assertRaises(m.Refused):h.run('fence',False,'102-1')
        self.probe.local(directory).rmdir();self.probe.local(directory).symlink_to(self.probe.local('/assets'))
        with self.assertRaises(m.Refused),scoped.directory(directory):pass
    def test_unpinned_policy_fails_before_any_file_or_docker_access(self):
        h=self.helper();h.policy=None
        with mock.patch.object(h.files,'read',side_effect=AssertionError),mock.patch.object(h.docker,'version',side_effect=AssertionError),self.assertRaises(m.Refused):h.run('fence',True,'101-1')
        self.assertEqual(self.docker.updates,[])
    def test_fence_readiness_does_not_change_policy_or_create_journal(self):
        report=self.helper().run('fence',False,'101-1');self.assertEqual(report['status'],'ready')
        self.assertEqual(self.docker.updates,[]);self.assertFalse(self.probe.local(m.BASE).exists())
    def test_fence_preserves_original_policy_and_daemon_metadata(self):
        report=self.fence();self.assertEqual(report['status'],'completed');self.assertEqual(len(self.docker.updates),2)
        journal=m.decode(self.files.read(m.BASE+'/fence-complete.json',8192,True)[0])
        self.assertEqual(journal['daemon'],self.docker.version())
        stored=self.files.read(m.BASE+'/fence-complete.json',8192,True)[0]
        self.assertEqual(report['fence_journal_sha256'],m.digest(stored))
        self.assertEqual(report['control_policy_sha256'],m.digest(m.canonical(self.policy)))
        self.assertTrue(all(row['restart_policy']['Name']=='unless-stopped' for row in journal['containers'].values()))
        self.assertTrue(all(self.docker.state(row['id'])['restart']['Name']=='no' for row in self.request.values()))
    def test_operator_age_is_required_only_before_fence(self):
        document=copy.deepcopy(self.operator)
        document['checked_at']=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=3)).isoformat()
        self.proof('deployment-fence-operator-evidence.json',document,'OPERATOR_SHA')
        with self.assertRaises(m.Refused):self.helper().operator('fence')
        self.helper().operator('maintenance');self.helper().operator('stop')
        self.assertEqual(self.docker.updates,[])
    def test_second_update_failure_preserves_partial_without_false_complete(self):
        original=self.docker.update_no;count=0
        def fail(identifier):
            nonlocal count
            count+=1
            if count==2:raise m.Refused('docker_failed')
            original(identifier)
        with mock.patch.object(self.docker,'update_no',side_effect=fail),self.assertRaises(m.Refused):self.fence()
        self.assertTrue(self.probe.local(m.BASE+'/fence-original.json').exists())
        self.assertFalse(self.probe.local(m.BASE+'/fence-complete.json').exists())
    def test_attempt_cannot_be_repeated(self):
        self.fence()
        with self.assertRaises(m.Refused):self.helper().run('fence',True,'103-1')
        self.assertEqual(len(self.docker.updates),2)
    def test_operator_disabled_state_and_active_runs_are_mandatory(self):
        for key,value in (('after','active'),('active_runs',True)):
            bad=copy.deepcopy(self.operator);bad['workflows'][0][key]=value
            self.proof('deployment-fence-operator-evidence.json',bad,'OPERATOR_SHA')
            with self.assertRaises(m.Refused):self.helper().run('fence',True,'101-1')
            self.assertEqual(self.docker.updates,[])
    def test_maintenance_requires_send_proof_before_changing_nginx(self):
        self.backup_ready()
        with mock.patch.object(m,'SEND_SHA','0'*64),self.assertRaises(m.Refused):self.helper().run('maintenance',True,'102-1')
        self.assertEqual(self.calls,[])
    def test_maintenance_replaces_only_app_spans_and_keeps_other_bytes(self):
        self.backup_ready();before={r['resolved_path']:self.files.read(r['resolved_path'],262144)[0] for r in self.policy['files']}
        result=self.helper().run('maintenance',True,'102-1');self.assertEqual(result['changed_files'],3)
        for row in self.policy['files']:
            expected,_=m.rewritten(before[row['resolved_path']],row['locations'])
            self.assertEqual(self.files.read(row['resolved_path'],262144)[0],expected)
        self.assertEqual(self.calls,[['/usr/sbin/nginx','-t']]*3+[['/usr/bin/systemctl','reload','nginx']])
        self.assertTrue(all(self.docker.state(v['id'])['paused'] for v in self.request.values()))
    def test_nginx_test_failure_rolls_back_own_changes_and_keeps_apps_paused(self):
        self.backup_ready();before={r['resolved_path']:self.files.read(r['resolved_path'],262144)[0] for r in self.policy['files']}
        h=self.helper();checks=0
        def failed_test(args,**kwargs):
            nonlocal checks
            checks+=1;return b'',2 if checks==3 else 0
        h.runner=failed_test
        with self.assertRaises(m.Refused):h.run('maintenance',True,'102-1')
        for path,body in before.items():self.assertEqual(self.files.read(path,262144)[0],body)
        self.assertTrue(all(self.docker.state(v['id'])['paused'] for v in self.request.values()))
        self.assertFalse(self.probe.local(m.BASE+'/maintenance-complete.json').exists())
    def test_signal_after_swap_is_owned_by_rollback(self):
        self.backup_ready();original=self.files.swap
        def interrupted(*a,**kw):
            row=original(*a,**kw);signal.raise_signal(signal.SIGTERM);return row
        h=self.helper()
        with mock.patch.object(self.files,'swap',side_effect=interrupted),self.assertRaises(m.Refused):h.run('maintenance',True,'102-1')
        for row in self.policy['files']:self.assertEqual(m.digest(self.files.read(row['resolved_path'],262144)[0]),row['sha256'])
    def test_stop_requires_independent_local_proof_and_exact_daemon_semantics(self):
        self.backup_ready()
        with self.assertRaises(m.Refused):self.helper().run('stop',True,'103-1')
        self.assertEqual(self.docker.kills,[])
    def test_stop_kills_only_fixed_apps_and_preserves_all_files_and_protected(self):
        self.stop_ready();before=self.docker.state('b'*64)
        result=self.helper().run('stop',True,'103-1')
        self.assertEqual(result['status'],'completed');self.assertEqual(set(self.docker.kills),{r['id'] for r in self.request.values()})
        self.assertEqual(self.docker.state('b'*64),before);self.assertTrue(self.probe.local(m.BASE+'/stop-complete.json').exists())
        self.assertFalse(result['data_deleted']);self.assertFalse(result['application_restore_verified'])
    def test_replacement_writer_is_observed_without_automatically_killing_it(self):
        self.stop_ready();self.docker.names=[('f'*64,'content-studio')]
        with self.assertRaises(m.Refused):self.helper().run('stop',True,'103-1')
        self.assertNotIn('f'*64,self.docker.kills);self.assertFalse(self.probe.local(m.BASE+'/stop-complete.json').exists())
    def test_protected_change_blocks_fence_before_mutation(self):
        h=self.helper();original=h.protected;count=0
        def changed():
            nonlocal count
            count+=1
            if count>1:self.docker.states['b'*64]['pid']+=1
            return original()
        with mock.patch.object(h,'protected',side_effect=changed),self.assertRaises(m.Refused):h.run('fence',True,'101-1')
        self.assertEqual(self.docker.updates,[])
    def test_wrong_named_config_and_symlink_are_never_mutated(self):
        self.backup_ready();row=self.policy['files'][0];path=self.probe.local(row['resolved_path']);path.rename(path.with_name('saved'))
        path.symlink_to('saved')
        with self.assertRaises(m.Refused):self.helper().run('maintenance',True,'102-1')
        self.assertEqual(self.calls,[])
    def test_exclusive_execution_lock_blocks_a_second_controller(self):
        self.files.initialize()
        with self.files.lock(),self.assertRaises(m.Refused) as error:self.helper().run('fence',True,'101-1')
        self.assertEqual(error.exception.code,'lock_busy');self.assertEqual(self.docker.updates,[])
    def test_swap_race_preserves_concurrent_original_and_refuses_success(self):
        self.backup_ready();original=self.files.exchange;changed=False
        def exchange(folder,left,right):
            nonlocal changed
            if not changed:
                changed=True
                fd=os.open(right,os.O_WRONLY|os.O_TRUNC,dir_fd=folder)
                try:os.write(fd,b'CONCURRENT_SOURCE_CONFIG')
                finally:os.close(fd)
            return original(folder,left,right)
        path=self.policy['files'][0]['resolved_path']
        with mock.patch.object(self.files,'exchange',side_effect=exchange),self.assertRaises(m.Refused):self.helper().run('maintenance',True,'102-1')
        self.assertEqual(self.files.read(path,262144)[0],b'CONCURRENT_SOURCE_CONFIG')
    @unittest.skipUnless(sys.platform=='linux','production syscall is Linux-only')
    def test_linux_atomic_exchange_keeps_both_verified_inodes(self):
        self.backup_ready();self.files.exchanger=None
        self.assertEqual(self.helper().run('maintenance',True,'102-1')['status'],'completed')
    def test_post_reload_failure_restores_disk_and_reloads_original(self):
        self.backup_ready();h=self.helper();original=h.protected;count=0
        def changed():
            nonlocal count
            count+=1
            if len([row for row in self.calls if row==['/usr/bin/systemctl','reload','nginx']])==1:
                raise m.Refused('protected_changed')
            return original()
        with mock.patch.object(h,'protected',side_effect=changed),self.assertRaises(m.Refused):h.run('maintenance',True,'102-1')
        self.assertEqual(len([row for row in self.calls if row==['/usr/bin/systemctl','reload','nginx']]),2)
        for row in self.policy['files']:self.assertEqual(m.digest(self.files.read(row['resolved_path'],262144)[0]),row['sha256'])
    def test_rollback_ignores_repeated_signals_and_attempts_every_file(self):
        self.backup_ready();h=self.helper();original=self.files.rollback;rolled=[];checks=0
        def runner(args,**kwargs):
            nonlocal checks
            checks+=1;return b'',2 if checks==3 else 0
        def rollback(record):
            signal.raise_signal(signal.SIGTERM);signal.raise_signal(signal.SIGHUP)
            rolled.append(record['path']);return original(record)
        h.runner=runner
        with mock.patch.object(self.files,'rollback',side_effect=rollback),self.assertRaises(m.Refused):h.run('maintenance',True,'102-1')
        self.assertEqual(len(rolled),3)
        for row in self.policy['files']:self.assertEqual(m.digest(self.files.read(row['resolved_path'],262144)[0]),row['sha256'])
    def test_exchange_fsync_failure_after_swap_restores_original_inode(self):
        self.backup_ready();original=self.files.exchange;count=0
        def failed(folder,left,right):
            nonlocal count
            count+=1;original(folder,left,right)
            if count==1:raise m.Refused('exchange_failed')
        with mock.patch.object(self.files,'exchange',side_effect=failed),self.assertRaises(m.Refused):self.helper().run('maintenance',True,'102-1')
        for row in self.policy['files']:self.assertEqual(m.digest(self.files.read(row['resolved_path'],262144)[0]),row['sha256'])
        self.assertNotIn(['/usr/bin/systemctl','reload','nginx'],self.calls)
    def test_partial_fence_attempt_already_contains_both_original_policies(self):
        with mock.patch.object(self.docker,'update_no',side_effect=m.Refused('docker_failed')),self.assertRaises(m.Refused):self.fence()
        value=m.decode(self.files.read(m.BASE+'/fence-attempt.json',8192,True)[0])
        self.assertEqual(set(value['original_containers']),{'ad','content'})
        self.assertTrue(all(v['restart_policy']['Name']=='unless-stopped' for v in value['original_containers'].values()))
    def test_raw_configuration_and_secret_canary_never_enter_report(self):
        self.fence();text=json.dumps(self.helper().report)
        self.assertNotIn(f.CANARY,text);self.assertNotIn('root',text);self.assertNotIn('/etc/nginx',text)
    def test_no_unpause_stop_rm_or_host_kill_mutation_path(self):
        source=(BASE/'retirement_control_mutation.py').read_text()
        self.assertNotIn("self.run('stop'",source);self.assertNotIn("self.run('unpause'",source)
        self.assertNotIn('os.unlink(',source);self.assertNotIn("'rm'",source);self.assertNotIn('cgroup.kill',source)


if __name__=='__main__':unittest.main()
