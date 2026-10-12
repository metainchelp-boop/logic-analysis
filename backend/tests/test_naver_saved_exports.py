"""Synthetic filesystem/SQLite CLI only; no system units, remote host or APIs."""
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'naver_saved_exports.py'
SPEC = importlib.util.spec_from_file_location('saved_exports_under_test', SOURCE)
M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)


class SavedExportInstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root / 'saved-source'; self.source.mkdir()
        self.database = self.source / 'logic_data.db'
        conn = sqlite3.connect(self.database)
        conn.executescript('''
            CREATE TABLE clients(id INTEGER PRIMARY KEY,naver_store_url TEXT,main_keywords TEXT,role TEXT,vertical TEXT);
            CREATE TABLE client_analyses(id INTEGER PRIMARY KEY,client_id INTEGER,product_url TEXT,updated_at TEXT,analysis_json TEXT,advertiser_json TEXT);
            CREATE TABLE client_keyword_product(client_id INTEGER,keyword TEXT,product_url TEXT);
            CREATE TABLE client_keyword_mute(client_id INTEGER,keyword TEXT);
            CREATE TABLE collector_observations(observation_id TEXT,keyword TEXT,collected_date TEXT,status TEXT,kind TEXT,reason TEXT,payload_hash TEXT,products_json TEXT,meta_json TEXT,received_at TEXT);
            CREATE TABLE collected_serp(keyword TEXT,collected_date TEXT,total INTEGER,products_json TEXT,meta_json TEXT);
        '''); conn.commit(); conn.close()
        self.uid = os.getuid() or 10001; self.gid = os.getgid()
        self.staging = self.root / 'staging'; self.staging.mkdir(mode=0o700)
        self.install = self.root / 'installed-code'; self.install.mkdir(mode=0o755)
        self.units = self.root / 'units'; self.units.mkdir(mode=0o755)
        self.outputs = {kind: self.root / ('export-' + kind) for kind in M.KINDS}
        for name, value in {'STAGING':self.staging,'INSTALL':self.install,'UNITS':self.units,
                            'OUTPUTS':self.outputs,'ROOT_UID':os.getuid(),'READER_GID':self.gid}.items():
            item=patch.object(M,name,value);item.start();self.addCleanup(item.stop)
        item=patch.object(M.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=self.uid));item.start();self.addCleanup(item.stop)
        item=patch.object(M.grp,'getgrgid',return_value=SimpleNamespace(gr_gid=self.gid));item.start();self.addCleanup(item.stop)
        self.plan = M.build_plan(ops_commit='a'*40,source_directory=str(self.source),database_name='logic_data.db',
            exporter_user='synthetic-exporter',source_group=None,python_executable='/usr/bin/python3')
        self.scripts = {name:(SOURCE.parents[1]/name).read_bytes() for name in M.SCRIPTS}
        self.pins = {name:hashlib.sha256(body).hexdigest() for name,body in self.scripts.items()}
        self.calls = []

    def prepare(self):
        return M.prepare(self.plan,scripts=self.scripts,pins=self.pins,operation_id='b'*32)

    def command(self,args):
        self.calls.append(list(args))
        if args[:2]==['systemctl','start']:
            kind = 'product' if 'product' in args[2] else 'market'
            target=self.outputs[kind]/'bundle.json'
            # Actual standalone CLI against synthetic SQLite. The fake systemctl
            # does not claim to exercise a real mount namespace or service user.
            result=subprocess.run([sys.executable,'-I','-B',str(self.install/self.plan['ops_commit']/('naver_'+kind+'_export.py')),
                '--database',str(self.database),'--output',str(target)],capture_output=True,check=True)
            self.assertEqual(json.loads(result.stdout)['status'],'ok')
            os.chown(target,self.uid,self.gid)
        if args[:2]==['systemctl','show']:
            return b'Result=success\nExecMainStatus=0\n'
        return b''

    def test_closed_plan_refuses_path_injection_broad_source_and_root(self):
        for key,value in [('source_directory','/root'),('source_directory','/tmp/a%h'),
                          ('source_directory',str(self.outputs['product'])),('database_name','../secret.db'),
                          ('exporter_user','root'),('source_group','root'),('python_executable','/tmp/python')]:
            with self.subTest(key=key,value=value),self.assertRaises(M.ExportInstallInvalid):
                M.build_plan(**{**self.plan,key:value})

    def test_pins_fail_before_host_source_access(self):
        with patch.object(M,'_source_identity',side_effect=AssertionError('Must not read host')) as source:
            with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_PIN'):
                M.prepare(self.plan,scripts=self.scripts,pins={**self.pins,M.SCRIPTS[0]:'0'*64},operation_id='b'*32)
            source.assert_not_called()

    def test_companion_and_units_bind_only_dedicated_directories_readonly(self):
        items=M.artifacts(self.plan,self.scripts,self.pins)
        self.assertEqual(len(items),7)
        engine=json.loads(items[M.COMPANION])['services']['naver-engine']
        self.assertEqual(set(engine),{'environment','volumes'});self.assertEqual(len(engine['volumes']),2)
        for row in engine['volumes']:
            self.assertIs(row['read_only'],True);self.assertIs(row['bind']['create_host_path'],False)
            self.assertNotIn(str(self.source),row['source'])
        for kind in M.KINDS:
            unit=items[f'naver-{kind}-export.service'].decode()
            self.assertIn('ProtectHome=tmpfs\n',unit)
            self.assertIn(f'BindReadOnlyPaths={self.source}:/run/naver-saved-source:norbind\n',unit)
            self.assertIn('os.statvfs',unit);self.assertIn('os.ST_RDONLY',unit)
            self.assertNotIn('immutable=1',unit);self.assertNotIn('EnvironmentFile=',unit)
            self.assertIn('PrivateNetwork=true\n',unit);self.assertIn('CapabilityBoundingSet=\n',unit)

    def test_prepare_is_non_operational_and_source_change_blocks_install(self):
        receipt=self.prepare();self.assertEqual(self.calls,[]);self.assertEqual(list(self.units.iterdir()),[])
        old=self.database.with_suffix('.old');self.database.rename(old);self.database.write_bytes(old.read_bytes())
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_SOURCE_CHANGED'):
            M.install(receipt,command=self.command)
        self.assertEqual(self.calls,[])

    def test_actual_synthetic_cli_export_verify_then_rollback_preserves_source_and_bundles(self):
        before=(self.database.read_bytes(),self.database.stat().st_mtime_ns)
        receipt=self.prepare();result=M.install(receipt,command=self.command)
        self.assertEqual(result['state'],'installed');self.assertIs(result['engine_verified'],False)
        self.assertEqual(before,(self.database.read_bytes(),self.database.stat().st_mtime_ns))
        start=[i for i,args in enumerate(self.calls) if args[:2]==['systemctl','start']]
        enable=[i for i,args in enumerate(self.calls) if args[:2]==['systemctl','enable']]
        self.assertEqual(len(start),2);self.assertEqual(len(enable),2);self.assertLess(max(start),min(enable))
        summary=M.verify(receipt,command=self.command);self.assertEqual(summary['sources']['product']['products'],0)
        output=json.dumps(summary);self.assertNotIn(str(self.database),output);self.assertNotIn('synthetic-exporter',output)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_ALREADY_ATTEMPTED'):
            M.install(receipt,command=self.command)
        done=M.rollback(receipt,command=self.command);self.assertEqual(done['state'],'rolled_back')
        self.assertEqual(list(self.units.iterdir()),[])
        self.assertTrue(all((path/'bundle.json').exists() for path in self.outputs.values()))
        self.assertEqual(before,(self.database.read_bytes(),self.database.stat().st_mtime_ns))

    def test_live_wal_pair_is_read_and_later_commits_visible_without_source_repair(self):
        writer=sqlite3.connect(self.database);self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL');writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO clients VALUES(1,'https://smartstore.naver.com/Synthetic/products/1','','advertiser','store')");writer.commit()
        self.assertTrue(Path(str(self.database)+'-wal').exists());self.assertTrue(Path(str(self.database)+'-shm').exists())
        receipt=self.prepare();M.install(receipt,command=self.command)
        first=json.loads((self.outputs['product']/'bundle.json').read_bytes());self.assertEqual(len(first['stores']),1)
        writer.execute("INSERT INTO clients VALUES(2,'https://smartstore.naver.com/Second/products/2','','advertiser','store')");writer.commit()
        stable={str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in (self.database,Path(str(self.database)+'-wal'))}
        self.command(['systemctl','start','naver-product-export.service'])
        second=json.loads((self.outputs['product']/'bundle.json').read_bytes());self.assertEqual(len(second['stores']),2)
        self.assertEqual(stable,{str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in (self.database,Path(str(self.database)+'-wal'))})

    def test_partial_failure_before_units_can_be_rolled_back_without_unknown_unit_calls(self):
        receipt=self.prepare();real=M._write_new
        def fail_script(path,*args):
            if path.parent.parent==self.install:raise OSError('synthetic')
            return real(path,*args)
        with patch.object(M,'_write_new',side_effect=fail_script):
            with self.assertRaises(OSError):M.install(receipt,command=self.command)
        self.assertEqual(M.rollback(receipt,command=self.command)['state'],'rolled_back')
        self.assertEqual(self.calls,[])

    def test_failed_one_shot_never_enables_timer_and_rollback_stops_only_own_units(self):
        receipt=self.prepare()
        def failed(args):
            self.calls.append(args)
            if args[:2]==['systemctl','start']:raise RuntimeError('private synthetic details')
            return b''
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_COMMAND_FAILED'):
            M.install(receipt,command=failed)
        self.assertFalse(any(args[:2]==['systemctl','enable'] for args in self.calls))
        M.rollback(receipt,command=self.command);self.assertEqual(list(self.units.iterdir()),[])

    def test_drift_and_symlink_block_verification_and_rollback_before_any_commands(self):
        receipt=self.prepare();M.install(receipt,command=self.command)
        path=self.units/'naver-product-export.service';path.write_bytes(b'foreign unit\n')
        self.calls.clear()
        with self.assertRaises(M.ExportInstallInvalid):M.verify(receipt,command=self.command)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_ROLLBACK_DRIFT'):M.validate_rollback(receipt)
        with self.assertRaisesRegex(M.ExportInstallInvalid,'EXPORT_ROLLBACK_DRIFT'):M.rollback(receipt,command=self.command)
        self.assertEqual(self.calls,[])

    def test_validate_rollback_is_readonly_and_does_not_require_source_inode(self):
        receipt=self.prepare();M.install(receipt,command=self.command)
        self.calls.clear()
        files=list(self.units.iterdir())+list((self.install/self.plan['ops_commit']).iterdir())
        before={str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in files}
        self.database.rename(self.source/'old.db')
        self.database.write_bytes(b'changed source inode must not block rollback preflight')
        self.assertIsNone(M.validate_rollback(receipt))
        self.assertEqual(self.calls,[])
        self.assertEqual(before,{str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in files})

    def test_stale_or_malformed_bundle_is_not_successful_verification(self):
        receipt=self.prepare();M.install(receipt,command=self.command)
        path=self.outputs['product']/'bundle.json';value=json.loads(path.read_text())
        value['exported_at']=(datetime.now(timezone.utc)-timedelta(hours=31)).isoformat();path.write_text(json.dumps(value))
        with self.assertRaises(M.ExportInstallInvalid):M.verify(receipt,command=self.command)
        path.unlink();path.symlink_to(self.database)
        with self.assertRaises(M.ExportInstallInvalid):M.verify(receipt,command=self.command)

    def test_restrictive_umask_and_paired_rollback_allow_exact_new_operation(self):
        previous=os.umask(0o077)
        try:
            receipt=self.prepare();M.install(receipt,command=self.command)
            M.rollback(receipt,command=self.command)
            second=M.prepare(self.plan,scripts=self.scripts,pins=self.pins,operation_id='c'*32)
            result=M.install(second,command=self.command)
        finally:os.umask(previous)
        self.assertEqual(result['state'],'installed')
        self.assertEqual((self.install/self.plan['ops_commit']).stat().st_mode&0o777,0o755)
        self.assertTrue(all((self.units/f'naver-{kind}-export.service').stat().st_mode&0o777==0o644 for kind in M.KINDS))

    def test_partial_unit_creation_failure_does_not_stop_nonexistent_unit(self):
        receipt=self.prepare();real=M._write_new
        def fail_unit(path,*args):
            if path.parent==self.units:raise OSError('synthetic unit write failure')
            return real(path,*args)
        with patch.object(M,'_write_new',side_effect=fail_unit):
            with self.assertRaises(OSError):M.install(receipt,command=self.command)
        M.rollback(receipt,command=self.command)
        self.assertFalse(any(args[0]=='systemctl' and args[1] in ('stop','disable') for args in self.calls))


if __name__=='__main__':unittest.main()
