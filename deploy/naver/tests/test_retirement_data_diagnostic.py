"""Synthetic snapshot stages and real shell/output guards; no server/data/key."""
import ast
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import types
import unittest
from unittest import mock
BASE=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('data_diagnostic',BASE/'deploy/naver/retirement_data_diagnostic.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
spec=importlib.util.spec_from_file_location('workflow_parts',Path(__file__).with_name('test_retirement_control_workflow.py'))
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
CANARY='PRIVATE_CONFIG_CANARY'

class Fake:
    def __init__(self,*a,**kw):
        self.stack=contextlib.ExitStack();self.bases={};self.deleted=[];self.calls=[];self.mapping_pins=[]
        self.proc=types.SimpleNamespace(root_fd=lambda _:contextlib.nullcontext(17))
        self.files=types.SimpleNamespace(directory=lambda *a,**kw:contextlib.nullcontext(18))
    def frozen(self):self.calls.append('frozen');return {'GUARD':True}
    def observe(self):self.calls.append('coverage');return {},{}
    def inventory(self):self.calls.append('inventory');return [{'kind':'file','private':CANARY}]
    def pin_deleted(self):self.calls.append('deleted');self.deleted=[{'private':CANARY}]
    def pin_mappings_and_check_io(self):self.calls.append('mapping')
    def configuration(self):self.calls.append('configuration');return [{'body':CANARY}],['absent'],{}
    def write(self,*a):raise AssertionError('no archive write')

class Diagnostic(unittest.TestCase):
    def setUp(self):
        self.snapshot=Fake();self.archive=types.SimpleNamespace(Snapshot=mock.Mock(return_value=self.snapshot),DATA_SCOPES=('ad','content','autobid','content_tmp'),ROOTS={'ad':'/data/ad','content':'/data/content','autobid':'/data/autobid'})
        self.source=types.SimpleNamespace(RESTART_EVIDENCE={'sha256':'a'*64})
    def run_diag(self):return m.diagnose(self.archive,object(),self.source,object(),end=123)
    def test_all_prewrite_stages_are_visited_without_sink_or_private_output(self):
        result=self.run_diag();self.assertEqual(result['status'],'diagnosed');self.assertEqual(result['stage'],'complete');self.assertTrue(result['cleanup_confirmed'])
        self.assertEqual(self.snapshot.calls,['frozen','coverage','frozen','inventory','deleted','mapping','configuration','frozen'])
        self.assertEqual(result['entry_count'],1);self.assertEqual(result['deleted_count'],1);self.assertEqual(result['configuration_count'],1)
        self.assertNotIn(CANARY,json.dumps(result));self.assertNotIn('root',json.dumps(result));self.assertFalse(result['archive_written']);self.assertFalse(result['state_changed'])
    def test_each_actual_stage_reports_only_allowlisted_failure_code(self):
        for method,stage in [('frozen','frozen_initial'),('observe','coverage'),('inventory','inventory'),('pin_deleted','deleted'),('pin_mappings_and_check_io','mapping'),('configuration','configuration')]:
            with self.subTest(stage=stage),mock.patch.object(self.snapshot,method,side_effect=m.Refused('configuration_changed')):
                result=self.run_diag();self.assertEqual((result['status'],result['stage'],result['error']),('blocked',stage,'configuration_changed'));self.assertTrue(result['cleanup_confirmed'])
    def test_repeated_freeze_is_not_skipped(self):
        with mock.patch.object(self.snapshot,'frozen',side_effect=[{'GUARD':True},{'GUARD':False}]):
            r=self.run_diag();self.assertEqual((r['stage'],r['error']),('frozen_repeat','freeze_changed'))
    def test_final_freeze_is_checked_after_configuration(self):
        with mock.patch.object(self.snapshot,'frozen',side_effect=[{'GUARD':True},{'GUARD':True},{'GUARD':False}]):
            r=self.run_diag();self.assertEqual((r['stage'],r['error']),('frozen_final','freeze_changed'))
    def test_pinned_base_failure_is_distinct(self):
        with mock.patch.object(self.snapshot.files,'directory',side_effect=m.Refused('unsafe_directory')):
            r=self.run_diag();self.assertEqual((r['stage'],r['error']),('pin_base','unsafe_directory'))
    def test_unknown_error_text_never_leaks(self):
        with mock.patch.object(self.snapshot,'inventory',side_effect=RuntimeError(CANARY)):
            r=self.run_diag();self.assertEqual(r['error'],'operation_failed');self.assertNotIn(CANARY,json.dumps(r))
    def test_arbitrary_error_code_is_not_echoed(self):
        with mock.patch.object(self.snapshot,'inventory',side_effect=m.Refused(CANARY)):
            self.assertEqual(self.run_diag()['error'],'operation_failed')
    def test_cleanup_failure_cannot_claim_success(self):
        with mock.patch.object(self.snapshot.stack,'close',side_effect=RuntimeError(CANARY)):
            r=self.run_diag();self.assertEqual(r['status'],'blocked');self.assertEqual(r['error'],'cleanup_unconfirmed');self.assertFalse(r['cleanup_confirmed'])
    def test_interruption_is_bounded_and_closes_snapshot(self):
        with mock.patch.object(self.snapshot,'configuration',side_effect=m.Refused('interrupted')),mock.patch.object(self.snapshot.stack,'close',wraps=self.snapshot.stack.close) as close:
            self.assertEqual(self.run_diag()['error'],'interrupted');close.assert_called_once()
    def test_outer_temporary_directory_cleanup_failure_is_not_confirmed(self):
        folder=mock.MagicMock();folder.__enter__.return_value='/synthetic-config';folder.__exit__.side_effect=RuntimeError(CANARY)
        modules={'retirement_data_preflight.py':types.SimpleNamespace(Docker=lambda *a,**kw:None),'retirement_data_archive.py':None,'retirement_data_source.py':None}
        out=io.StringIO()
        with mock.patch.object(m.os,'geteuid',return_value=0),mock.patch.object(m.os,'umask'),mock.patch.object(m.sys,'platform','linux'),mock.patch.object(m.sys,'argv',['diagnostic','123-1']),mock.patch.object(m,'load_modules',return_value=modules),mock.patch.object(m.tempfile,'TemporaryDirectory',return_value=folder),mock.patch.object(m,'diagnose',return_value={'status':'diagnosed'}),mock.patch.object(m.signal,'signal'),mock.patch.object(m.signal,'setitimer'),mock.patch.object(m.resource,'setrlimit'),contextlib.redirect_stdout(out):
            self.assertEqual(m.main(),2)
        result=json.loads(out.getvalue());self.assertFalse(result['cleanup_confirmed']);self.assertEqual(result['error'],'operation_failed');self.assertNotIn(CANARY,out.getvalue())
    def test_assets_wrong_path_or_run_fail_before_any_open(self):
        for path,run in [('/tmp/other','123-1'),('/tmp/metainc-data-diagnostic-123-1','124-1'),('/tmp/metainc-data-diagnostic-01-1','01-1')]:
            with mock.patch.object(m.os,'open',side_effect=AssertionError('no open')),self.assertRaises(m.Refused):m.load_modules(path,run)
    def test_pins_match_exact_reviewed_public_sources(self):
        import hashlib
        for name,pin in m.PINS.items():self.assertEqual(hashlib.sha256((BASE/'deploy/naver'/name).read_bytes()).hexdigest(),pin)
    def test_helper_has_no_archive_or_mutation_or_sqlite_call(self):
        tree=ast.parse((BASE/'deploy/naver/retirement_data_diagnostic.py').read_text())
        forbidden={'write','archive_snapshot','send','perform','pause','unpause','kill','connect','execute','load'}
        calls=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertFalse(forbidden.intersection(calls));self.assertNotIn('subprocess',calls)

class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=(BASE/'.github/workflows/naver-data-diagnostic.yml').read_text();cls.parts=f.parts(cls.text);cls.guard=f.block(cls.parts[0],'run')
        cls.remote=f.block(next(p for p in cls.parts if 'RETIREMENT_DATA_DIAGNOSTIC=' in p),'script')
        cls.validator=re.search(r"if ! printf .*?python3 -I -B -c '\n(.*?)\n' \"\$rc\"",cls.remote,re.S)[1];ast.parse(cls.validator)
        cls.good=m.diagnose(types.SimpleNamespace(Snapshot=lambda *a,**kw:Fake(),DATA_SCOPES=(),ROOTS={}),None,types.SimpleNamespace(RESTART_EVIDENCE={}),None)
    def validate(self,value=None,raw=None,rc='0'):
        r=subprocess.run([sys.executable,'-I','-B','-c',self.validator,rc],input=json.dumps(self.good if value is None else value).encode() if raw is None else raw,capture_output=True,timeout=3);self.assertEqual(r.stderr,b'');return r
    def test_every_shell_and_embedded_python_compiles(self):
        for part in self.parts:
            for key in ('run','script'):
                if re.search(r'^ +'+key+r': \|',part,re.M):
                    shell=f.block(part,key);p=subprocess.run(['/bin/bash','-n'],input=shell.encode(),capture_output=True,timeout=3);self.assertEqual(p.returncode,0,p.stderr)
                    for code in re.findall(r"python3? -I -B -c '\n(.*?)\n'",shell,re.S):ast.parse(code)
                    for code in re.findall(r"<<'PYCODE'\n(.*?)\nPYCODE",shell,re.S):ast.parse(code)
    def test_manual_owner_main_first_attempt_host_guards(self):
        env={'ACTOR':'metainchelp-boop','TRIGGERING_ACTOR':'metainchelp-boop','REF':'refs/heads/main','ATTEMPT':'1','HOST_FINGERPRINT':'SHA256:'+'a'*43}
        self.assertEqual(subprocess.run(['/bin/bash','-c',self.guard],env=env,capture_output=True,timeout=3).returncode,0)
        for key in env:
            bad=dict(env);bad[key]=CANARY;p=subprocess.run(['/bin/bash','-c',self.guard],env=bad,capture_output=True,timeout=3);self.assertNotEqual(p.returncode,0);self.assertNotIn(CANARY.encode(),p.stdout+p.stderr)
        self.assertIn('workflow_dispatch: {}',self.text);self.assertNotIn('contents: write',self.text)
        source=(BASE/'.github/workflows/naver-data-preservation.yml').read_text()
        self.assertEqual(re.search(r'^  group: (.+)$',self.text,re.M)[1],re.search(r'^  group: (.+)$',source,re.M)[1])
    def test_good_and_specific_stage_failure_pass_closed_validator(self):
        self.assertEqual(self.validate().returncode,0)
        v=copy.deepcopy(self.good);v.update(status='blocked',stage='frozen_initial',error='cgroup_unconfirmed');self.assertEqual(self.validate(v,rc='2').returncode,0)
    def test_duplicate_unknown_keys_and_raw_text_are_refused(self):
        for raw in (b'{"a":1,"a":2}',b'NaN',b'{}\n{}',CANARY.encode(),b'x'*8193):self.assertNotEqual(self.validate(raw=raw).returncode,0)
        v=copy.deepcopy(self.good);v['private']=CANARY;p=self.validate(v);self.assertNotEqual(p.returncode,0);self.assertNotIn(CANARY.encode(),p.stdout)
    def test_numeric_bool_and_mutation_claims_are_refused(self):
        for key,bad in [('file_count',True),('entry_count',100001),('deleted_count',65),('configuration_count',17),('archive_written',True),('state_changed',True),('cleanup_confirmed',False)]:
            v=copy.deepcopy(self.good);v[key]=bad;self.assertNotEqual(self.validate(v).returncode,0)
    def test_bounded_pinned_snapshot_and_public_only_cleanup(self):
        self.assertIn('timeout -k 10s 300s',self.text);self.assertIn('exec(compile(source,path,"exec")',self.text)
        self.assertIn('os.O_NOFOLLOW',self.text);self.assertIn('os.fchown(fd,0,0);os.fchmod(fd,0o600)',self.text)
        self.assertIn('overwrite: false',self.text);self.assertNotIn('upload-artifact',self.text);self.assertNotIn('rm -rf',self.text)
        for p in self.parts:
            if 'uses: appleboy/' in p:self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}',p)
        cleanup=self.parts[-1];self.assertIn('if: always()',cleanup);self.assertNotIn('transfer-receipt',cleanup);self.assertNotIn('data.gpg',cleanup)

if __name__=='__main__':unittest.main()
