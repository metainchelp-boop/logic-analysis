"""Synthetic CPU-only controller tests; Docker/HTTP/database access is prohibited."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared


class ResourceTrialTest(unittest.TestCase):
    def setUp(self):
        self.module = shared.load('naver_preview_resource_trial')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.path = self.folder/'releases'/('naver-'+'7985925dcc4ed9d75c28ae43a456964cdc78c63f')
        self.path.mkdir(parents=True)
        (self.folder/'receipts').mkdir()
        self.pin = dict(source_commit=self.path.name[6:],
            source_tar_gz_sha256='47632d4d3403c24dd4988b80c1a0ada25cc155fc6048a7f2413fb72d84ea73ff',
            baseline='5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76')
        self.package = dict(release=self.pin,operation_id='9'*32,action='apply')
        self.cid, self.rid = 'd'*64, 'f'*64
        self.image, self.rimage = 'sha256:'+'e'*64, 'sha256:'+'a'*64
        files = {}
        for name in ('compose.naver-engine.yml','preview-engine.override.yml',
                     'deploy/naver-engine-backup.override.yml','compose.naver-relay.yml','preview-relay.override.yml'):
            file = self.path/name
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(b'approved '+name.encode())
            file.chmod(0o600 if name.startswith('preview-') else 0o644)
            files[str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
        store = self.path/'naver_engine/store.py'
        store.parent.mkdir()
        store.write_bytes(b'SCHEMA_VERSION = 11\n')
        store.chmod(0o644)
        self.store_digest = hashlib.sha256(store.read_bytes()).hexdigest()
        self.receipt = self.folder/'receipts'/('preview-'+self.pin['source_commit']+'.json')
        self.prepared = dict(ok=True,stage='prepared',source_commit=self.pin['source_commit'],
            package=self.pin,images=dict(engine=self.image,relay=self.rimage),files=files)
        self.receipt.write_text(json.dumps(self.prepared))
        self.receipt.chmod(0o600)
        self.start = self.receipt.with_name('preview-start-'+self.pin['source_commit']+'.json')
        self.start.write_text(json.dumps(dict(ok=True,stage='internal_ready',source_commit=self.pin['source_commit'])))
        self.start.chmod(0o600)
        self.state = dict(id=self.cid,image=self.image,running=True,user='10001:10001',
            project='naver-engine',service='naver-engine',source=self.pin['source_commit'],
            started='2026-10-09T02:03:00.311514514Z',restarts=0,oom_killed=False,
            readonly=True,data=[dict(Type='bind',Destination='/var/lib/naver-engine',
                Source='/var/lib/metainc/naver-engine',RW=True)],
            limits=dict(nano_cpus=500000000,cpu_period=0,cpu_quota=0,cpu_shares=0,
                cpu_realtime_period=0,cpu_realtime_runtime=0,cpuset_cpus='',cpuset_mems='',
                memory=536870912,memory_swap=1073741824,memory_reservation=0,
                memory_swappiness=None,oom_kill_disable=False,pids_limit=64))
        self.relay = dict(id=self.rid,image=self.rimage,running=True,user='10001:10001',
            project='naver-relay',service='naver-relay',source=self.pin['source_commit'],
            started='2026-10-09T02:03:02.000000000Z',restarts=0,readonly=True)
        self.calls = []
        self.release = Mock()
        self.release.ROOT = self.folder
        self.release.prepared_paths.return_value = self.path,self.receipt
        self.release.sha.side_effect = lambda body: hashlib.sha256(body).hexdigest()
        self.release.unique.side_effect = dict
        self.release.compose.side_effect = lambda path,name:['docker','compose','--project-name','naver-'+name]
        self.release.write_new.side_effect = self.write_new
        self.release.command.side_effect = self.command
        self.host = Mock()
        self.host.baseline.return_value = self.pin['baseline']
        self.stack.enter_context(patch.object(self.module.os,'geteuid',return_value=0))
        self.stack.enter_context(patch.object(self.module,'STORE_SHA256',self.store_digest))
        # The real trust predicate is checked separately; this fixture runs on a
        # non-root Mac as well as root-owned, offline Linux temporary files.
        real = Path.lstat
        def fixture_stat(path):
            info = real(path)
            return SimpleNamespace(st_mode=info.st_mode,st_uid=0,st_gid=0,
                st_nlink=info.st_nlink,st_size=info.st_size,st_dev=info.st_dev,st_ino=info.st_ino)
        self.stack.enter_context(patch.object(Path,'lstat',fixture_stat))
        fstat = os.fstat
        def fixture_fdstat(fd):
            info=fstat(fd)
            return SimpleNamespace(st_mode=info.st_mode,st_uid=0,st_gid=0,
                st_nlink=info.st_nlink,st_dev=info.st_dev,st_ino=info.st_ino)
        self.stack.enter_context(patch.object(self.module.os,'fstat',fixture_fdstat))

    def write_new(self,path,body,**kwargs):
        with path.open('xb') as stream: stream.write(body)
        path.chmod(0o600)

    def command(self,args,**kwargs):
        self.calls.append((list(args),kwargs))
        if args[0]=='/usr/bin/systemctl': return b'active\n'
        if args[1:3] == ['image','inspect']:
            engine = args[-1].startswith('metainc/naver-engine:')
            return json.dumps(dict(id=self.image if engine else self.rimage,
                user='10001:10001',source=self.pin['source_commit'])).encode()
        if args[1] == 'compose':
            return (self.cid if args[3]=='naver-engine' else self.rid).encode()
        if args[1] == 'inspect':
            return json.dumps(self.state if args[-1]==self.cid else self.relay).encode()
        if args[1] == 'update':
            self.assertEqual(args,['docker','update','--cpus',args[3],self.cid])
            self.assertIn(args[3],('1.0','0.5'))
            self.state['limits']['nano_cpus'] = 1000000000 if args[3]=='1.0' else 500000000
            return self.cid.encode()
        self.fail('Unexpected host command: '+str(args))

    def test_apply_changes_only_engine_cpu_and_returns_safe_receipt(self):
        before = json.loads(json.dumps(self.state))
        result = self.module.run(self.package,self.host,self.release)
        self.assertTrue(result['ok'])
        self.assertEqual(result['before_nano_cpus'],500000000)
        self.assertEqual(result['after_nano_cpus'],1000000000)
        self.assertEqual(result['memory_limit_bytes'],536870912)
        self.assertFalse(result['database_opened'])
        self.assertFalse(result['services_restarted'])
        self.assertEqual(len([a for a,k in self.calls if a[1]=='update']),1)
        before['limits']['nano_cpus'] = 1000000000
        self.assertEqual(self.state,before)
        self.assertNotIn(self.cid,json.dumps(result))
        self.assertNotIn(self.image,json.dumps(result))

    def test_same_operation_rollback_restores_cpu_without_restart_and_is_idempotent(self):
        self.module.run(self.package,self.host,self.release)
        rollback=dict(self.package,action='rollback')
        result=self.module.run(rollback,self.host,self.release)
        self.assertTrue(result['ok'])
        self.assertEqual(result['after_nano_cpus'],500000000)
        self.assertEqual(self.state['limits']['nano_cpus'],500000000)
        repeated=self.module.run(rollback,self.host,self.release)
        self.assertTrue(repeated['already_rolled_back'])
        self.assertEqual(repeated['cpu_updates_this_run'],0)
        self.assertEqual([a[3] for a,k in self.calls if a[1]=='update'],['1.0','0.5'])

    def test_request_cannot_select_source_container_or_resource_values_before_host(self):
        for change in ({'source_commit':'0'*40},{'source_tar_gz_sha256':'0'*64},{'baseline':'0'*64}):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'RESOURCE_SOURCE'):
                self.module.run(dict(self.package,release=dict(self.pin,**change)),self.host,self.release)
        for change in ({'container_id':self.cid},{'cpus':1.5},{'memory':1073741824},
                       {'action':'inspect'},{'operation_id':'../escape'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.module.run(dict(self.package,**change),self.host,self.release)
        self.assertEqual(self.host.mock_calls,[])
        self.assertEqual(self.release.mock_calls,[])

    def test_limits_drift_source_changes_and_wrong_container_refuse_before_update(self):
        cases=(('memory',1073741824),('nano_cpus',1000000000),('nano_cpus',True),('cpu_quota',50000))
        for key,value in cases:
            old=self.state['limits'][key]
            self.state['limits'][key]=value
            with self.subTest(key=key,value=value),self.assertRaisesRegex(ValueError,'RESOURCE_LIMITS'):
                self.module.run(self.package,self.host,self.release)
            self.state['limits'][key]=old
        for key,value in (('id','0'*64),('image','sha256:'+'0'*64),('source','0'*40),('running',False),('readonly',False)):
            old=self.state[key];self.state[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'RESOURCE_CONTAINER_CHANGED'):
                self.module.run(self.package,self.host,self.release)
            self.state[key]=old
        (self.path/'naver_engine/store.py').write_bytes(b'changed Store')
        with self.assertRaisesRegex(ValueError,'RESOURCE_STORE_CHANGED'):
            self.module.run(self.package,self.host,self.release)
        self.assertFalse(any(a[1]=='update' for a,k in self.calls))

    def test_apply_is_once_and_rollback_requires_same_operation_and_unchanged_runtime(self):
        self.module.run(self.package,self.host,self.release)
        with self.assertRaisesRegex(ValueError,'RESOURCE_ALREADY_ATTEMPTED'):
            self.module.run(self.package,self.host,self.release)
        with self.assertRaisesRegex(ValueError,'RESOURCE_RECEIPT_MISSING'):
            self.module.run(dict(self.package,action='rollback',operation_id='8'*32),self.host,self.release)
        self.state['limits']['memory_swap']+=1
        with self.assertRaisesRegex(ValueError,'RESOURCE_RECEIPT_CHANGED'):
            self.module.run(dict(self.package,action='rollback'),self.host,self.release)
        self.assertEqual(len([a for a,k in self.calls if a[1]=='update']),1)

    def test_timeout_after_update_keeps_intent_and_explicit_rollback_can_restore(self):
        real=self.command
        def timeout(args,**kwargs):
            value=real(args,**kwargs)
            if args[1]=='update': raise TimeoutError('PRIVATE_ERROR')
            return value
        self.release.command.side_effect=timeout
        with self.assertRaises(TimeoutError): self.module.run(self.package,self.host,self.release)
        self.assertTrue(self.module.failure_report(TimeoutError('PRIVATE_ERROR'))['cpu_update_attempted'])
        self.release.command.side_effect=real
        result=self.module.run(dict(self.package,action='rollback'),self.host,self.release)
        self.assertTrue(result['ok'])
        self.assertEqual(self.state['limits']['nano_cpus'],500000000)
        self.assertNotIn('PRIVATE',json.dumps(self.module.failure_report(TimeoutError('PRIVATE_ERROR'))))

    def test_old_operation_cannot_restore_a_new_trial_even_after_external_cpu_restore(self):
        self.module.run(self.package,self.host,self.release)
        self.state['limits']['nano_cpus']=500000000
        with self.assertRaisesRegex(ValueError,'RESOURCE_BUSY'):
            self.module.run(dict(self.package,operation_id='8'*32),self.host,self.release)
        self.assertEqual(len([a for a,k in self.calls if a[1]=='update']),1)

    def test_unready_receipt_wrong_archive_symlink_or_untrusted_mode_cannot_update(self):
        old=self.prepared.copy()
        for change in ({'ok':False},{'source_commit':'0'*40},
                       {'package':dict(self.pin,source_tar_gz_sha256='0'*64)}):
            self.receipt.write_text(json.dumps(dict(old,**change)))
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'RESOURCE_SOURCE_NOT_READY'):
                self.module.run(self.package,self.host,self.release)
        self.receipt.write_text(json.dumps(old))
        file=self.path/'compose.naver-engine.yml'
        file.chmod(0o666)
        with self.assertRaisesRegex(ValueError,'RESOURCE_FILE_POLICY'):
            self.module.run(self.package,self.host,self.release)
        file.chmod(0o644)
        original=file.read_bytes()
        file.unlink();file.symlink_to(self.path/'compose.naver-relay.yml')
        with self.assertRaisesRegex(ValueError,'RESOURCE_FILE_POLICY'):
            self.module.run(self.package,self.host,self.release)
        self.assertFalse(any(a[1]=='update' for a,k in self.calls))

    def test_exclusive_lock_and_inactive_service_refuse_without_update(self):
        with patch.object(self.module.fcntl,'flock',side_effect=BlockingIOError):
            with self.assertRaisesRegex(ValueError,'RESOURCE_BUSY'):
                self.module.run(self.package,self.host,self.release)
        real=self.command
        self.release.command.side_effect=lambda args,**kwargs: b'inactive\n' if args[0]=='/usr/bin/systemctl' else real(args,**kwargs)
        with self.assertRaisesRegex(ValueError,'RESOURCE_DEPENDENCY'):
            self.module.run(self.package,self.host,self.release)
        self.assertFalse(any(a[1]=='update' for a,k in self.calls))

    def test_postflight_restart_or_existing_app_drift_cannot_report_success(self):
        real=self.command
        def restart(args,**kwargs):
            value=real(args,**kwargs)
            if args[1]=='update': self.state['restarts']=1
            return value
        self.release.command.side_effect=restart
        with self.assertRaisesRegex(ValueError,'RESOURCE_CONTAINER_CHANGED'):
            self.module.run(self.package,self.host,self.release)
        self.state['restarts']=0
        self.release.command.side_effect=real
        self.host.baseline.return_value='0'*64
        with self.assertRaisesRegex(ValueError,'RESOURCE_HOST_BASELINE'):
            self.module.run(dict(self.package,action='rollback'),self.host,self.release)
        self.host.baseline.return_value=self.pin['baseline']
        self.assertTrue(self.module.run(dict(self.package,action='rollback'),self.host,self.release)['ok'])

    def test_rollbacks_do_not_echo_changed_completion_receipt_or_wrong_lease(self):
        self.module.run(self.package,self.host,self.release)
        active=self.folder/'receipts'/'preview-resource-trial.active.json'
        saved=active.read_bytes()
        lease=json.loads(saved);lease['operation_id']='8'*32
        active.write_text(json.dumps(lease))
        with self.assertRaisesRegex(ValueError,'RESOURCE_RECEIPT_CHANGED'):
            self.module.run(dict(self.package,action='rollback'),self.host,self.release)
        active.write_bytes(saved)
        self.module.run(dict(self.package,action='rollback'),self.host,self.release)
        done=self.folder/'receipts'/('resource-trial-'+'9'*32+'.rollback.json')
        value=json.loads(done.read_bytes());value['PRIVATE']='PRIVATE_CREDENTIAL'
        done.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'RESOURCE_RECEIPT_CHANGED'):
            self.module.run(dict(self.package,action='rollback'),self.host,self.release)

    def test_command_budget_and_controller_never_open_database_http_or_other_service(self):
        self.module.run(self.package,self.host,self.release)
        self.assertEqual(len([a for a,k in self.calls if a[1]=='update']),1)
        self.assertLessEqual(len(self.calls),24)
        for args,kwargs in self.calls:
            self.assertEqual(kwargs,{'timeout':10})
            self.assertNotIn('exec',args)
            self.assertNotIn('restart',args)
            self.assertNotIn('stop',args)
            self.assertNotIn('--memory',args)
        with patch.object(self.module.os,'geteuid',return_value=501):
            with self.assertRaisesRegex(ValueError,'RESOURCE_ROOT'):
                self.module.run(dict(self.package,operation_id='8'*32),self.host,self.release)

    def test_idempotent_completion_has_exact_fields_types_source_limits_and_fresh_postflight(self):
        self.module.run(self.package,self.host,self.release)
        rollback=dict(self.package,action='rollback')
        self.module.run(rollback,self.host,self.release)
        path=self.folder/'receipts'/('resource-trial-'+'9'*32+'.rollback.json')
        original=json.loads(path.read_bytes())
        missing=dict(original);missing.pop('source_archive_sha256')
        changes=[missing,dict(original,source_commit='0'*40),dict(original,ok=False),
            dict(original,action='apply'),dict(original,memory_limit_bytes=1073741824),
            dict(original,engine_identity_sha256='0'*64),dict(original,cpu_updates_this_run=True),
            dict(original,source_files_changed=True),dict(original,PRIVATE='PRIVATE_CREDENTIAL')]
        for value in changes:
            path.write_text(json.dumps(value))
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'RESOURCE_RECEIPT_CHANGED'):
                self.module.run(rollback,self.host,self.release)
        path.write_text(json.dumps(original))
        self.host.baseline.side_effect=[self.pin['baseline'],'0'*64]
        with self.assertRaisesRegex(ValueError,'RESOURCE_POST_STATE'):
            self.module.run(rollback,self.host,self.release)
        self.assertEqual(len([a for a,k in self.calls if a[1]=='update']),2)


if __name__=='__main__': unittest.main()
