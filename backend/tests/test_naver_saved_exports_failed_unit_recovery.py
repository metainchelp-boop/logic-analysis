"""Recover the exact old v3 failed artifact set in a temporary filesystem."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]/'tools'
spec=importlib.util.spec_from_file_location('unit_recovery_under_test',TOOLS/'naver_saved_exports_failed_unit_recovery.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)


class FailedUnitRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_source=subprocess.check_output(['git','show',
            '535a2bf1bd40f479fb913158cae2b7a3d57041a0:backend/tools/naver_saved_exports.py'],cwd=TOOLS.parents[1])

    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();self.h=R.load_helper(self.old_source)
        self.calls=[];self.reloaded=False;self.fail_reload=False;self.active_after=None
        for key,value in {'ROOT_UID':os.getuid(),'READER_GID':os.getgid(),
                'STAGING':self.root/'staging','INSTALL':self.root/'code','UNITS':self.root/'units',
                'OUTPUTS':{kind:self.root/('output-'+kind) for kind in ('product','market')}}.items():
            setattr(self.h,key,value)
        for p in (self.h.STAGING,self.h.INSTALL,self.h.UNITS):p.mkdir(mode=0o700 if p==self.h.STAGING else 0o755)
        (self.root/'receipts').mkdir(mode=0o700)
        self.python=self.root/'python3.10';self.python.write_bytes(b'\x7fELF'+b'synthetic\0'*30);self.python.chmod(0o700)
        for target,key,value in ((R,'ROOT',self.root),(R,'is_root',lambda:True),
                (self.h,'_identity',lambda plan:{'exporter_uid':os.getuid() or 10001,'reader_gid':os.getgid(),'source_gid':None}),
                (self.h,'_source_identity',lambda plan:{'fixed':'synthetic-metadata'}),
                (self.h,'_python_target',lambda plan:self.python)):
            item=patch.object(target,key,value);item.start();self.addCleanup(item.stop)
        scripts={name:(TOOLS.parent/name).read_bytes() for name in self.h.SCRIPTS}
        pins={name:self.h._sha(body) for name,body in scripts.items()}
        self.receipt=self.h.prepare(R.PLAN,scripts=scripts,pins=pins,operation_id=R.FAILED_OPERATION)
        def fail_verify(args):raise RuntimeError('synthetic unit parse failure')
        with self.assertRaises(self.h.ExportInstallInvalid):self.h.install(self.receipt,command=fail_verify)
        self.folder=self.h.STAGING/R.FAILED_OPERATION
        original=self.h._directory
        def synthetic_directory(path,**kwargs):
            # Temp ancestors belong to the OS rather than this fixture's UID.
            # Keep policy checks inside the synthetic root exact.
            if path in self.root.parents:kwargs['owner']=path.lstat().st_uid
            return original(path,**kwargs)
        self.h._directory=synthetic_directory

    def run_fixed(self,args):
        self.calls.append(args)
        if args==['/usr/bin/systemctl','daemon-reload']:
            if self.fail_reload:return types.SimpleNamespace(returncode=1,stdout=b'',stderr=b'private failure')
            self.reloaded=True;return types.SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
        self.assertIn(args[2],R.UNITS)
        active=self.active_after is not None and len(self.calls)>=self.active_after
        value={'LoadState':'not-found' if self.reloaded else 'bad-setting','ActiveState':'active' if active else 'inactive',
               'SubState':'running' if active else 'dead','InvocationID':'','Job':'0','UnitFileState':''}
        return types.SimpleNamespace(returncode=1 if self.reloaded else 0,
            stdout=''.join(k+'='+value[k]+'\n' for k in R.FIELDS).encode(),stderr=b'')

    def recover(self):return R.recover_with_helper(self.h,run=self.run_fixed)

    def test_exact_failed_old_artifacts_removed_without_stop_start_or_source_access(self):
        result=self.recover()
        self.assertEqual(result['expected_exact_files_absent'],9);self.assertIs(result['source_writes'],False)
        self.assertEqual(result['units_started'],0)
        self.assertFalse(list(self.h.UNITS.iterdir()))
        self.assertEqual(json.loads((self.folder/'installed.json').read_text())['state'],'rolled_back')
        self.assertTrue(all(args[1] in ('show','daemon-reload') for args in self.calls))

    def test_changed_helper_bytes_rejected(self):
        with self.assertRaises(ValueError):R.recover(self.old_source+b'\n',run=self.run_fixed)
        self.assertFalse(self.calls)

    def test_active_or_queued_unit_prevents_any_deletion(self):
        self.active_after=1
        with self.assertRaises(ValueError):self.recover()
        self.assertEqual(len(list(self.h.UNITS.iterdir())),6)

    def test_unit_becomes_active_before_first_skip_prevents_deletion(self):
        self.active_after=7
        with self.assertRaises(ValueError):self.recover()
        self.assertEqual(len(list(self.h.UNITS.iterdir())),6)

    def test_successful_prepare_receipt_blocks_recovery(self):
        (self.root/'receipts'/('preview-'+R.TARGET+'.json')).write_text('{}')
        with self.assertRaises(ValueError):self.recover()
        self.assertFalse(self.calls)

    def test_unknown_created_directory_blocks_recovery(self):
        path=self.folder/'installed.json';state=json.loads(path.read_text())
        state['created_directories'].append(str(self.root/'unrelated'));path.write_text(json.dumps(state))
        with self.assertRaises(ValueError):self.recover()
        self.assertFalse(self.calls)

    def test_artifact_drift_blocks_recovery(self):
        path=self.h.UNITS/R.UNITS[0];path.write_bytes(path.read_bytes()+b'# drift\n')
        with self.assertRaises(self.h.ExportInstallInvalid):self.recover()
        self.assertFalse(self.calls)

    def test_reload_failure_resumes_without_recreating_artifacts(self):
        self.fail_reload=True
        with self.assertRaises(Exception):self.recover()
        self.assertFalse(list(self.h.UNITS.iterdir()))
        self.fail_reload=False;result=self.recover()
        self.assertEqual(result['state'],'recovered');self.assertFalse(list(self.h.UNITS.iterdir()))

    def test_duplicate_state_properties_rejected(self):
        original=self.run_fixed
        def duplicate(args):
            result=original(args);result.stdout+=b'Job=0\n';return result
        with self.assertRaises(ValueError):R.recover_with_helper(self.h,run=duplicate)
        self.assertEqual(len(list(self.h.UNITS.iterdir())),6)
