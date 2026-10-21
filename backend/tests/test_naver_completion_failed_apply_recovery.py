"""Offline recovery of one synthetic old DB; no host commands/network/secrets."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from contextlib import closing
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]/'tools'
spec=importlib.util.spec_from_file_location('failed_apply_recovery_test',TOOLS/'naver_completion_failed_apply_recovery.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)


class FailedApplyRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();self.data=self.root/'data';self.data.mkdir(mode=0o750)
        self.db=self.data/'engine.db'
        with closing(sqlite3.connect(self.db)) as conn:
            with conn:
                conn.execute('CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT)')
                conn.execute("INSERT INTO naver_auto_meta VALUES('schema_version','11')")
        self.db.chmod(0o600)
        self.receipts=self.root/'receipts';self.receipts.mkdir(mode=0o700)
        self.units=self.root/'units';self.units.mkdir(mode=0o755)
        self.tmpfiles=self.root/'tmpfiles';self.tmpfiles.mkdir(mode=0o755)
        self.unit_names=('metainc-naver-engine.service','metainc-naver-relay.service')
        self.old_path=self.root/('naver-'+R.OLD_COMMIT);self.old_path.mkdir()
        self.files={self.units/name:('old '+name).encode() for name in self.unit_names}
        self.tmp=self.tmpfiles/'preview.conf';self.files[self.tmp]=b'old tmpfiles'
        for path,body in self.files.items():path.write_bytes(body);path.chmod(0o644)
        self.package={'operation_id':R.FAILED_OPERATION,'release':{'baseline':'a'*64,'operation':'code-prepare'}}
        self.old={'source_commit':R.OLD_COMMIT,'package':{'baseline':'a'*64,'source_tar_gz_sha256':'b'*64},
            'images':{'engine':'sha256:'+'c'*64,'relay':'sha256:'+'d'*64}}
        backup={'source_commit':R.OLD_COMMIT,'target_commit':R.TARGET_COMMIT,'images':self.old['images'],
            'units':{str(p):v.decode() for p,v in self.files.items() if p!=self.tmp}}
        self.backup=self.receipts/('code-upgrade-'+R.FAILED_OPERATION+'.json')
        self.backup.write_bytes(R._json(backup));self.backup.chmod(0o600)
        self.calls=[];self.running=False;self.bad_image=False;self.fail_start=False;self.fail_verify=False
        self.schema_calls=0;self.mutate_before_start=False;self.container_checks=0
        def trusted(path,**kw):
            self.assertTrue(path.is_dir());self.assertFalse(path.is_symlink())
            if 'mode' in kw:self.assertEqual(path.stat().st_mode&0o777,kw['mode'])
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('duplicate')
                result[key]=value
            return result
        def write_new(path,body):
            with path.open('xb') as f:f.write(body)
            path.chmod(0o600)
        self.release=types.SimpleNamespace(ROOT=self.root,trusted_dir=trusted,unique=unique,
            command=self.command,compose=lambda path,name:['docker','compose',name],write_new=write_new)
        def read_file(path,**kw):
            self.assertNotEqual(path,self.db,'whole DB read is forbidden')
            return path.read_bytes()
        self.upgrade=types.SimpleNamespace(read_file=read_file,manifest=lambda *a,**k:(self.old_path,self.old))
        self.life=types.SimpleNamespace(UNIT_DIR=self.units,TMPFILES=self.tmp,UNITS=self.unit_names,
            TUNNEL='metainc-naver-erp-tunnel.service',unit_files=lambda *a:self.files.copy(),
            _state=lambda release,unit,field:'enabled' if field=='UnitFileState' else 'active')
        def stopped(*args):
            if self.running:raise ValueError('writer running')
        def verify(*args):
            if self.fail_verify:raise RuntimeError('PRIVATE raw host details')
            self.assertTrue(self.running)
        self.C=types.SimpleNamespace(OLD_COMMIT=R.OLD_COMMIT,TARGET_COMMIT=R.TARGET_COMMIT,
            OLD_SCHEMA=11,TARGET_SCHEMA=21,DATA=self.data,OLD_SOURCE_SHA256='b'*64,
            require_pins=lambda:None,validate_package=lambda package,release:package,
            stopped_writer=stopped,bootstrap_state=lambda *a:{'fixed':'synthetic'},
            database_contract=self.contract,verify_running=verify,
            container_runtime_flags=lambda *a:{'execution_enabled':False})
        self.host=types.SimpleNamespace(baseline=lambda:'a'*64)
        changes=((R,'DATA',self.data),(R,'DB_UID',os.getuid()),(R,'DB_GID',os.getgid()),
            (R,'PACKAGE_SHA256',hashlib.sha256(R._json(self.package)).hexdigest()),
            (R.os,'geteuid',lambda:0),(R.pwd,'getpwnam',lambda name:types.SimpleNamespace(pw_gid=33)))
        for obj,key,value in changes:
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)

    def contract(self,conn,source):
        self.schema_calls+=1;self.assertEqual(source,R.OLD_COMMIT)
        self.assertEqual(conn.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone(),('11',))
        # This is the real controller schema query, including its LIKE function.
        conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()

    def command(self,args,**kwargs):
        self.calls.append(args)
        if args[:2]==['/usr/bin/systemctl','start']:
            if self.fail_start:raise RuntimeError('PRIVATE socket/path details')
            self.running=True;return b''
        if args[:2]==['/usr/bin/systemctl','stop']:
            self.running=False;return b''
        if args[:2]==['docker','compose']:
            self.container_checks+=1
            if self.mutate_before_start and self.container_checks==3:
                self.db.touch()
            return (('1' if args[2]=='engine' else '2')*64+'\n').encode()
        if args[:2]==['docker','inspect']:
            name='engine' if args[-1]=='1'*64 else 'relay'
            return R._json({'id':args[-1],'image':'sha256:'+'f'*64 if self.bad_image else self.old['images'][name],
                'running':False,'restarting':False,'pid':0,'source':R.OLD_COMMIT,
                'project':'naver-'+name,'service':'naver-'+name})
        raise AssertionError('not an allowlisted synthetic command')

    def recover(self):return R.recover(self.package,self.host,self.release,self.life,self.upgrade,self.C)
    def no_start(self):self.assertFalse(any(c[:2]==['/usr/bin/systemctl','start'] for c in self.calls))

    def test_exact_pre_migration_recovery_no_database_source_unit_or_image_writes(self):
        before=self.db.read_bytes();units={p:p.read_bytes() for p in self.files}
        result=self.recover();self.assertIs(result['ok'],True);self.assertEqual(result['database_schema'],11)
        for key in ('database_writes','source_writes','database_restored','migration_performed','new_apply_performed','execution_enabled'):
            self.assertIs(result[key],False)
        self.assertEqual(before,self.db.read_bytes());self.assertEqual(units,{p:p.read_bytes() for p in self.files})
        self.assertEqual([c[2] for c in self.calls if c[:2]==['/usr/bin/systemctl','start']],list(self.unit_names))
        self.assertEqual(list(self.data.iterdir()),[self.db])

    def test_large_sparse_database_is_metadata_bounded_not_read_into_memory(self):
        with self.db.open('r+b') as f:f.truncate(1024**3+4096)
        self.assertTrue(self.recover()['ok']);self.assertEqual(self.schema_calls,1)

    def test_wrong_package_and_nonroot_are_rejected_before_host_or_file_access(self):
        self.package['operation_id']='0'*32
        self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_PACKAGE');self.assertFalse(self.calls)
        self.package['operation_id']=R.FAILED_OPERATION
        with patch.object(R.os,'geteuid',return_value=1000):
            self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_ROOT')
        self.assertFalse(self.calls)

    def test_any_target_started_or_snapshot_artifact_blocks_restart(self):
        for name in ('preview-start-'+R.TARGET_COMMIT+'.json',
            'completion-snapshot-'+R.FAILED_OPERATION+'.json',
            'completion-db-'+R.FAILED_OPERATION+'.sqlite',
            'completion-db-'+R.FAILED_OPERATION+'.verify.sqlite'):
            p=self.receipts/name;p.write_bytes(b'x')
            self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_EVIDENCE_EXISTS');self.no_start();p.unlink()

    def test_changed_backup_unit_or_container_rejected(self):
        original=self.backup.read_bytes();self.backup.write_text('{}')
        self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_BACKUP');self.no_start()
        self.backup.write_bytes(original)
        unit=next(iter(self.files));unit.write_bytes(b'changed')
        self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_UNIT_CHANGED');self.no_start()
        unit.write_bytes(self.files[unit]);self.bad_image=True
        self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_CONTAINER');self.no_start()

    def test_all_sidecar_types_including_dangling_symlink_block_immutable_open(self):
        for p in R._sidecars():
            p.symlink_to(self.root/'missing')
            self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_DB_SIDECAR')
            self.assertEqual(self.schema_calls,0);self.no_start();p.unlink()

    def test_database_mode_hardlink_and_symlink_are_not_repaired(self):
        self.db.chmod(0o644);self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_DB_POLICY');self.no_start()
        self.db.chmod(0o600);other=self.root/'other';os.link(self.db,other)
        self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_DB_POLICY');self.no_start();other.unlink()
        self.db.rename(other);self.db.symlink_to(other)
        self.assertEqual(self.recover()['ok'],False);self.no_start()

    def test_schema_mismatch_and_authorizer_write_attempt_block_start(self):
        with closing(sqlite3.connect(self.db)) as conn:
            with conn:conn.execute("UPDATE naver_auto_meta SET value='21'")
        self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_DB_SCHEMA');self.no_start()

    def test_real_controller_schema_contract_and_like_function_are_supported(self):
        spec=importlib.util.spec_from_file_location('actual_recovery_controller',TOOLS/'naver_preview_completion_release.py')
        controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller)
        with closing(sqlite3.connect(self.db)) as conn:digest=controller.schema_digest(conn)
        with patch.object(controller,'SCHEMA_SHA256',{'old':digest,'target':'0'*64}):
            proof=R._database_schema(self.release,controller)
            self.assertEqual(proof[6],self.db.stat().st_size)
        def forbidden_function(conn,source):conn.execute('SELECT random()').fetchone()
        with self.assertRaisesRegex(ValueError,'RECOVERY_DB_SCHEMA'):
            R._database_schema(self.release,types.SimpleNamespace(database_contract=forbidden_function))
        self.C.database_contract=lambda conn,source:conn.execute('CREATE TABLE unsafe(x)')
        self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_DB_SCHEMA');self.no_start()

    def test_database_changed_after_schema_validation_blocks_start(self):
        self.mutate_before_start=True
        self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_DB_CHANGED');self.no_start()

    def test_start_or_health_failure_stops_both_old_services_and_exposes_no_raw_error(self):
        for startfail in (True,False):
            self.fail_start=startfail;self.fail_verify=not startfail
            result=self.recover();self.assertFalse(result['ok']);self.assertNotIn('PRIVATE',json.dumps(result))
            self.assertEqual([c[2] for c in self.calls if c[:2]==['/usr/bin/systemctl','stop']],list(reversed(self.unit_names)))
            self.assertFalse(self.running)
            intent=self.receipts/('completion-failed-apply-recovery-'+R.FAILED_OPERATION+'.json');intent.unlink()
            self.calls.clear()

    def test_ambiguous_restart_cannot_automatically_be_repeated(self):
        self.fail_start=True;self.assertFalse(self.recover()['ok']);self.calls.clear();self.fail_start=False
        self.assertEqual(self.recover()['failed_error_code'],'RECOVERY_ALREADY_ATTEMPTED');self.no_start()

    def test_success_receipt_recheck_never_opens_immutable_database_while_live(self):
        self.assertTrue(self.recover()['ok']);self.calls.clear()
        with patch.object(R,'_database_schema',side_effect=AssertionError('live immutable forbidden')):
            self.assertTrue(self.recover()['ok'])
        self.no_start();self.assertEqual(self.schema_calls,1)


if __name__=='__main__':unittest.main()
