"""Fixed read-only diagnostic fixtures: actual SQLite, synthetic Docker only."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]/'tools'
spec=importlib.util.spec_from_file_location('migration_inspect_test',TOOLS/'naver_completion_migration_inspect.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


def unique(pairs):
    out={}
    for k,v in pairs:
        if k in out:raise ValueError('duplicate')
        out[k]=v
    return out


class MigrationInspectTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();self.receipts=self.root/'receipts';self.receipts.mkdir(mode=0o700)
        self.data=self.root/'data';self.data.mkdir(mode=0o750)
        self.quarantine=self.data/('.completion-failed-db-'+M.OPERATION);self.quarantine.mkdir(mode=0o700)
        self.snapshot=self.receipts/('completion-db-'+M.OPERATION+'.sqlite')
        with closing(sqlite3.connect(self.snapshot)) as c:
            with c:
                c.execute('CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT)')
                c.execute("INSERT INTO naver_auto_meta VALUES('schema_version','11')")
                c.execute("INSERT INTO naver_auto_meta VALUES('learning-call:PRIVATE-KEY','{}')")
                c.execute('CREATE TABLE synthetic_records(id INTEGER,payload TEXT,zero INTEGER,missing TEXT)')
                c.execute("INSERT INTO synthetic_records VALUES(1,'PRIVATE-ROW',0,NULL)")
            self.schema_hash=hashlib.sha256(json.dumps([(k,n,t,re.sub(r'\s+',' ',s or '').strip())
                for k,n,t,s in c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")],separators=(',',':')).encode()).hexdigest()
        self.snapshot.chmod(0o600)
        self.receipt=self.receipts/('completion-snapshot-'+M.OPERATION+'.json')
        self.update_receipt()
        (self.quarantine/'engine.db').write_bytes(b'PRIVATE quarantine content must never be read')
        (self.quarantine/'engine.db').chmod(0o600)
        self.calls=[];self.created=False;self.removed=False;self.raw_result=None
        self.exit_code=0;self.oom=False;self.foreign=False;self.cleanup_failure=False
        self.invalid_config=None;self.timeout=False;self.started=False;self.create_timeout=False
        self.project=None
        self.image='sha256:'+'a'*64;self.container_id='b'*64
        def trusted(path,**kw):
            self.assertTrue(path.is_dir());self.assertFalse(path.is_symlink())
            if 'mode' in kw:self.assertEqual(path.stat().st_mode&0o777,kw['mode'])
        self.release=types.SimpleNamespace(ROOT=self.root,trusted_dir=trusted,unique=unique,command=self.command)
        self.C=types.SimpleNamespace(OLD_COMMIT=M.OLD,TARGET_COMMIT=M.TARGET,OLD_SCHEMA=11,TARGET_SCHEMA=21,
            SCHEMA_SHA256={'old':self.schema_hash},require_pins=lambda:None)
        self.upgrade=types.SimpleNamespace(manifest=lambda release,target:
            (self.root/('naver-'+M.TARGET),{'source_commit':M.TARGET,'images':{'engine':self.image,'relay':'sha256:'+'c'*64}}))
        for obj,key,value in ((M,'DATA',self.data),(M,'ROOT_UID',os.getuid()),(M,'ROOT_GID',os.getgid()),(M.os,'geteuid',lambda:0)):
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)

    def update_receipt(self):
        value={'source_commit':M.OLD,'target_commit':M.TARGET,'operation_id':M.OPERATION,
            'database_sha256':hashlib.sha256(self.snapshot.read_bytes()).hexdigest(),'schema':11,'snapshot_restore_verified':True}
        self.receipt.write_text(json.dumps(value));self.receipt.chmod(0o600)

    def script_result(self,script=None):
        script=(script or M._script(self.C)).replace('file:/inspection/snapshot.sqlite?',self.snapshot.as_uri()+'?')
        p=subprocess.run([sys.executable,'-I','-B','-c',script],capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr[:100]);self.assertEqual(p.stderr,b'')
        return p.stdout

    def command(self,args,**kwargs):
        self.calls.append(args)
        if args[:2]==['docker','ps']:
            return (self.container_id+'\n').encode() if self.created and not self.removed else b''
        if args[:2]==['docker','create']:
            self.created=True;self.create_args=args;self.name=args[args.index('--name')+1];self.script=args[-1]
            if self.create_timeout:raise TimeoutError('PRIVATE process timeout details')
            return (self.container_id+'\n').encode()
        if args[:2]==['docker','inspect']:
            if '.State.ExitCode' in args[3]:return json.dumps({'exit_code':self.exit_code,'oom_killed':self.oom,'running':False}).encode()
            row={'image':self.image,'user':'0:0','operation':M.OPERATION,'source':M.TARGET,'image_source':M.TARGET,
                'project':self.project,'entrypoint':['python'],'cmd':['-I','-B','-c',self.script],
                'readonly':True,'network':'none','memory':M.MEMORY,'swap':M.MEMORY,'pids':64,'cpu':1000000000,
                'caps':['ALL'],'security':['no-new-privileges'],'tmpfs':{'/tmp':'rw,noexec,nosuid,nodev,size='+str(M.TMP)+',mode=1777'},
                'name':'/'+self.name,'mounts':[{'Type':'bind','Source':str(self.snapshot),'Destination':'/inspection/snapshot.sqlite','RW':False,'Propagation':'rprivate'}]}
            if self.invalid_config:row[self.invalid_config]=False if self.invalid_config=='readonly' else 'PRIVATE-foreign'
            if self.foreign:row['source']='0'*40
            return json.dumps(row).encode()
        if args[:2]==['docker','start']:self.started=True;return b''
        if args[:2]==['docker','wait']:
            if self.timeout:raise TimeoutError('PRIVATE wait details')
            return str(self.exit_code).encode()
        if args[:2]==['docker','logs']:return self.raw_result if self.raw_result is not None else self.script_result(self.script)
        if args[:2]==['docker','rm']:
            if self.cleanup_failure:raise RuntimeError('PRIVATE cleanup details')
            self.removed=True;return b''
        raise AssertionError('unallowlisted synthetic Docker command')

    def inspect(self):return M.inspect_host(self.C,self.release,self.upgrade)

    def test_exact_snapshot_and_rows_privately_verified_under_strict_sandbox(self):
        before=self.snapshot.read_bytes();q=(self.quarantine/'engine.db').read_bytes()
        result=self.inspect();self.assertTrue(result['ok']);self.assertTrue(result['row_check']['row_hash_completed'])
        self.assertFalse(result['row_check']['invalid_learning_call_json']);self.assertTrue(self.removed)
        self.assertEqual(result['process'],{'exit_code':0,'oom_killed':False})
        self.assertEqual(self.snapshot.read_bytes(),before);self.assertEqual((self.quarantine/'engine.db').read_bytes(),q)
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn(self.schema_hash,json.dumps(result))
        self.assertEqual(result['sandbox']['memory_bytes'],768*1024**2);self.assertEqual(result['sandbox']['tmpfs_bytes'],64*1024**2)
        self.assertEqual(self.create_args.count('--mount'),1);self.assertIn('readonly',self.create_args[self.create_args.index('--mount')+1])
        for key in ('database_writes','source_writes','service_changes'):self.assertIs(result[key],False)

    def test_invalid_learning_call_json_is_boolean_only_and_does_not_block_hash(self):
        with closing(sqlite3.connect(self.snapshot)) as c:
            with c:c.execute("UPDATE naver_auto_meta SET value='PRIVATE-invalid-json' WHERE key LIKE 'learning-call:%'")
        self.update_receipt();result=self.inspect()
        self.assertTrue(result['row_check']['invalid_learning_call_json']);self.assertTrue(result['row_check']['row_hash_completed'])
        self.assertNotIn('PRIVATE',json.dumps(result))

    def test_actual_blob_json_serialization_failure_is_closed_and_prior_bool_survives(self):
        with closing(sqlite3.connect(self.snapshot)) as c:
            with c:c.execute('UPDATE synthetic_records SET payload=?',(sqlite3.Binary(b'PRIVATE-BLOB'),))
        self.update_receipt();result=self.inspect();self.assertTrue(result['ok'])
        self.assertEqual(result['row_check']['phase'],'rows_before');self.assertEqual(result['row_check']['error_kind'],'TypeError')
        self.assertFalse(result['row_check']['row_hash_completed']);self.assertIs(result['row_check']['invalid_learning_call_json'],False)
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertTrue(self.removed)

    def test_receipt_scope_duplicate_hash_and_schema_tampering_prevents_docker(self):
        original=self.receipt.read_text()
        for field,value in (('operation_id','0'*32),('schema',True),('target_commit',M.OLD),('database_sha256','f'*64)):
            obj=json.loads(original);obj[field]=value;self.receipt.write_text(json.dumps(obj))
            self.assertFalse(self.inspect()['ok']);self.assertFalse(self.calls)
        self.receipt.write_text(original[:-1]+',"schema":11}')
        self.assertFalse(self.inspect()['ok']);self.assertFalse(self.calls)

    def test_snapshot_hardlink_mode_and_sidecar_are_rejected_without_repairs(self):
        self.snapshot.chmod(0o644);self.assertFalse(self.inspect()['ok']);self.assertFalse(self.calls)
        self.snapshot.chmod(0o600);link=self.root/'other';os.link(self.snapshot,link)
        self.assertFalse(self.inspect()['ok']);self.assertFalse(self.calls);link.unlink()
        side=Path(str(self.snapshot)+'-wal');side.symlink_to(self.root/'missing')
        self.assertEqual(self.inspect()['code'],'INSPECT_SIDECAR');self.assertFalse(self.calls)

    def test_symlink_snapshot_and_nonroot_are_rejected(self):
        other=self.root/'other';self.snapshot.rename(other);self.snapshot.symlink_to(other)
        self.assertFalse(self.inspect()['ok']);self.assertFalse(self.calls)
        with patch.object(M.os,'geteuid',return_value=10001):self.assertEqual(self.inspect()['code'],'INSPECT_ROOT')

    def test_no_quarantine_or_operating_database_body_reads(self):
        real_open=os.open
        def safe_open(path,*args,**kwargs):
            self.assertNotIn(self.quarantine,Path(path).parents);self.assertNotEqual(Path(path),self.data/'engine.db')
            return real_open(path,*args,**kwargs)
        with patch.object(M.os,'open',side_effect=safe_open):self.assertTrue(self.inspect()['ok'])

    def test_image_inherited_source_is_required_and_foreign_container_never_removed(self):
        self.foreign=True;result=self.inspect();self.assertFalse(result['ok']);self.assertEqual(result['code'],'INSPECT_CLEANUP')
        self.assertFalse(self.started);self.assertFalse(self.removed)

    def test_missing_compose_label_empty_string_is_not_a_foreign_project(self):
        self.project='';self.assertTrue(self.inspect()['ok'])
        self.created=False;self.removed=False;self.project='naver-engine';self.started=False
        self.assertFalse(self.inspect()['ok']);self.assertFalse(self.started);self.assertFalse(self.removed)

    def test_bad_sandbox_is_not_started_or_blindly_removed(self):
        self.invalid_config='readonly';result=self.inspect();self.assertFalse(result['ok'])
        self.assertFalse(self.started);self.assertFalse(self.removed)

    def test_oom_no_json_is_reported_as_actual_process_metadata(self):
        self.exit_code=137;self.oom=True;self.raw_result=b''
        result=self.inspect();self.assertTrue(result['ok']);self.assertIsNone(result['row_check'])
        self.assertEqual(result['process'],{'exit_code':137,'oom_killed':True});self.assertTrue(self.removed)

    def test_timeout_and_late_created_container_are_cleaned_without_raw_errors(self):
        self.timeout=True;result=self.inspect();self.assertFalse(result['ok']);self.assertTrue(self.removed)
        self.assertEqual(result['stage'],'container_wait');self.assertNotIn('PRIVATE',json.dumps(result))
        self.created=False;self.removed=False;self.timeout=False;self.create_timeout=True
        result=self.inspect();self.assertFalse(result['ok']);self.assertTrue(self.removed)

    def test_output_raw_fields_unknown_sqlite_and_contradictions_are_rejected(self):
        base={'ok':False,'phase':'rows_before','error_kind':'OperationalError','sqlite_primary':'SQLITE_FULL',
            'invalid_learning_call_json':True,'row_hash_completed':False}
        self.assertEqual(M._result(json.dumps(base).encode(),self.release),base)
        for extra in ({'raw':'PRIVATE'}, {'sqlite_primary':'PRIVATE'}, {'row_hash_completed':True}):
            with self.assertRaises(ValueError):M._result(json.dumps(dict(base,**extra)).encode(),self.release)

    def test_child_authorizer_and_immutable_mode_forbid_database_mutations(self):
        before=self.snapshot.read_bytes()
        script=M._script(self.C).replace("phase='json_valid'", "phase='json_valid'\n c.execute('DELETE FROM synthetic_records')")
        value=json.loads(self.script_result(script));self.assertFalse(value['ok']);self.assertEqual(value['sqlite_primary'],'SQLITE_AUTH')
        self.assertEqual(before,self.snapshot.read_bytes())


if __name__=='__main__':unittest.main()
