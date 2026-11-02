"""Execute local guard and closed output validator with synthetic JSON only."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

BASE=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('control_workflow_parts',Path(__file__).with_name('test_retirement_control_workflow.py'))
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
PATH=BASE/'.github/workflows/naver-control-mutation.yml'

class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=PATH.read_text();cls.parts=f.parts(cls.source);cls.guard=f.block(cls.parts[0],'run')
        cls.script=f.block(next(p for p in cls.parts if 'RETIREMENT_CONTROL_MUTATION=' in p),'script')
        cls.validator=re.search(r"if ! printf .*?python3 -I -B -c '\n(.*?)\n' \"\$NCM_RUN\"",cls.script,re.S)[1]
        ast.parse(cls.validator)
        cls.good={'status':'completed','error':None,'phase':'fence','execute':True,'session':'data-snapshot-20261102-v1','run':'101-1',
                  'changed_containers':2,'changed_files':0,'protected_count':3,'daemon':{'version':'29.4.0','git_commit':'a'*40,'os':'linux','arch':'amd64'},
                  'local_restore_verified':False,'application_restore_verified':False,'data_deleted':False,
                  'fence_journal_sha256':'b'*64,'control_policy_sha256':'c'*64}
    def validate(self,value=None,raw=None,rc='0',mode='execute',phase='fence'):
        result=subprocess.run([sys.executable,'-I','-B','-c',self.validator,'101-1',phase,mode,rc],
            input=json.dumps(self.good if value is None else value).encode() if raw is None else raw,capture_output=True,timeout=3)
        self.assertEqual(result.stderr,b'');return result
    def test_owner_main_first_attempt_and_safe_inputs_guard(self):
        env={'ACTOR':'metainchelp-boop','TRIGGERING_ACTOR':'metainchelp-boop','REF':'refs/heads/main','ATTEMPT':'1',
             'PHASE':'fence','EXECUTE':'false','HOST_FINGERPRINT':'SHA256:'+'a'*43}
        self.assertEqual(subprocess.run(['/bin/bash','-c',self.guard],env=env,capture_output=True,timeout=3).returncode,0)
        for key in env:
            with self.subTest(key=key):
                changed=dict(env);changed[key]='UNTRUSTED_CANARY'
                p=subprocess.run(['/bin/bash','-c',self.guard],env=changed,capture_output=True,timeout=3)
                self.assertNotEqual(p.returncode,0);self.assertNotIn(b'UNTRUSTED_CANARY',p.stdout+p.stderr)
    def test_manual_only_readonly_pinned_actions_and_serialized_session(self):
        self.assertEqual(re.findall(r'^  ([a-z_]+):',self.source.split('\npermissions:',1)[0],re.M),['workflow_dispatch'])
        self.assertIn('contents: read',self.source);self.assertNotIn('contents: write',self.source)
        self.assertIn('cancel-in-progress: false',self.source)
        self.assertTrue(all(re.fullmatch('[0-9a-f]{40}',pin) for pin in re.findall(r'uses: [^@\s]+@(\S+)',self.source)))
        for part in self.parts:
            if 'uses: appleboy/' in part:self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}',part)
        self.assertNotIn('rm -rf',self.source);self.assertNotIn('upload-artifact',self.source)
    def test_shell_blocks_and_all_embedded_python_compile(self):
        for part in self.parts:
            for key in ('run','script'):
                if re.search(r'^ +'+key+r': \|',part,re.M):
                    shell=f.block(part,key)
                    p=subprocess.run(['/bin/bash','-n'],input=shell.encode(),capture_output=True,timeout=3)
                    self.assertEqual(p.returncode,0,p.stderr.decode())
                    for code in re.findall(r"python3? -I -B -c '\n(.*?)\n'",shell,re.S):ast.parse(code)
                    for code in re.findall(r"<<'PY'\n(.*?)\nPY",shell,re.S):ast.parse(code)
    def test_success_roundtrip_and_fence_digest_required(self):
        self.assertEqual(self.validate().returncode,0)
        for key in ('fence_journal_sha256','control_policy_sha256'):
            for bad in (None,'x'*64,True):
                v=copy.deepcopy(self.good);v[key]=bad;self.assertNotEqual(self.validate(v).returncode,0)
    def test_closed_schema_duplicate_nonfinite_multiline_and_oversize(self):
        for raw in (b'{"status":1,"status":2}',b'{}\n{}',b'NaN',b'x'*8193):
            self.assertNotEqual(self.validate(raw=raw).returncode,0)
        v=copy.deepcopy(self.good);v['unexpected']='PRIVATE_CANARY';p=self.validate(v);self.assertNotEqual(p.returncode,0);self.assertNotIn(b'PRIVATE_CANARY',p.stdout)
    def test_exact_numeric_bool_daemon_and_status_contract(self):
        for key,bad in (('changed_containers',True),('changed_files',4),('protected_count',4),('data_deleted',True),('application_restore_verified',True),('execute',1),('status','ready')):
            v=copy.deepcopy(self.good);v[key]=bad;self.assertNotEqual(self.validate(v).returncode,0)
        v=copy.deepcopy(self.good);v['daemon']['git_commit']='PRIVATE_CANARY';self.assertNotEqual(self.validate(v).returncode,0)
    def test_blocked_reason_closed_and_nonfence_digest_null(self):
        v=copy.deepcopy(self.good);v.update(status='blocked',error='policy_not_pinned',fence_journal_sha256=None,control_policy_sha256=None)
        self.assertEqual(self.validate(v,rc='2').returncode,0)
        v['error']='arbitrary_private_error';self.assertNotEqual(self.validate(v,rc='2').returncode,0)
        v=copy.deepcopy(self.good);v.update(phase='maintenance',fence_journal_sha256=None,control_policy_sha256=None)
        self.assertEqual(self.validate(v,phase='maintenance').returncode,0)
        v['control_policy_sha256']='c'*64;self.assertNotEqual(self.validate(v,phase='maintenance').returncode,0)
    def test_readiness_never_claims_changes_and_stop_requires_local_restore(self):
        v=copy.deepcopy(self.good);v.update(status='ready',execute=False,changed_containers=0,fence_journal_sha256=None,control_policy_sha256=None)
        self.assertEqual(self.validate(v,mode='check').returncode,0)
        v['changed_files']=1;self.assertNotEqual(self.validate(v,mode='check').returncode,0)
        v=copy.deepcopy(self.good);v.update(phase='stop',fence_journal_sha256=None,control_policy_sha256=None)
        self.assertNotEqual(self.validate(v,phase='stop').returncode,0)
    def test_remote_snapshot_and_narrow_cleanup_boundaries(self):
        self.assertIn('exec(compile(source,path,"exec")',self.source)
        self.assertIn('os.O_NOFOLLOW',self.source);self.assertIn('os.fchown(fd,0,0);os.fchmod(fd,0o600)',self.source)
        self.assertIn('ship.mkdir(mode=0o755)',self.source);self.assertIn('path.chmod(0o644)',self.source)
        self.assertIn('overwrite: false',self.source)
        self.assertIn('if: always() && steps.prepare_remote.outcome',self.parts[-1])
        self.assertNotIn('fence-complete.json',self.parts[-1]);self.assertIn('os.rmdir',self.parts[-1])
    def test_stop_proof_requires_exact_nonplaceholder_pin_before_staging(self):
        self.assertIn("expected=='0'*64",self.source);self.assertIn('hashlib.sha256(body).hexdigest()!=expected',self.source)
        self.assertIn("if phase!='fence':names+=",self.source)
        self.assertIn('len(raw)>65536',self.source)

if __name__=='__main__':unittest.main()
