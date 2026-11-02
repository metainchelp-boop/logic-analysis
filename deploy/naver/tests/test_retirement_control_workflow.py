"""Real Bash guard/strict JSON validator, synthetic facts; no SSH/config secrets."""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import unittest

BASE=Path(__file__).resolve().parents[3]
PATH=BASE/'.github/workflows/naver-data-control-preflight.yml'
CANARY='PRIVATE_CUSTOMER_CONFIG_VALUE'


def parts(source):return [p for p in re.split(r'(?=^      - )',source,flags=re.M) if p.startswith('      - ')]


def block(source,key):
    match=re.search(r'^( +)'+re.escape(key)+r': \|\n',source,re.M)
    if match is None:raise AssertionError('literal block missing')
    indent=len(match[1]);lines=[]
    for line in source[match.end():].splitlines():
        if line.strip() and len(line)-len(line.lstrip())<=indent:break
        lines.append(line)
    return textwrap.dedent('\n'.join(lines))+'\n'


def fixture_data():
    spec=importlib.util.spec_from_file_location('synthetic_control',BASE/'deploy/naver/tests/test_retirement_control_preflight.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    fixture=module.Fixture('test_three_fixed_roles_selected_without_private_content_output')
    try:
        fixture.setUp();result=fixture.collect()
        if result['status']!='observed':raise AssertionError('synthetic collection failed')
        # The filesystem adapter uses the Mac test user's UID. The production
        # helper requires UID0; normalize only that explicit fixture difference.
        for row in result['files']:row['metadata']['uid']=0
        return result
    finally:fixture.doCleanups()


class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=PATH.read_text();cls.parts=parts(cls.source);cls.guard=block(cls.parts[0],'run')
        cls.remote=next(p for p in cls.parts if 'NAVER_RETIREMENT_CONTROL_PREFLIGHT=' in p)
        cls.script=block(cls.remote,'script')
        match=re.search(r"python3 -I -B -c '\n(.*?)\n' \"\$rc\"",cls.script,re.S)
        if match is None:raise AssertionError('strict validator missing')
        cls.validator=match[1];ast.parse(cls.validator);cls.good=fixture_data()
    def guard_run(self,**values):
        env={'ACTOR':'metainchelp-boop','TRIGGERING_ACTOR':'metainchelp-boop','REF':'refs/heads/main',
             'AD_ID':'a'*64,'CONTENT_ID':'c'*64,'AD_PID':'101','CONTENT_PID':'201','HOST_FINGERPRINT':'SHA256:'+'x'*43}
        env.update(values)
        return subprocess.run(['/bin/bash','--noprofile','--norc','-c',self.guard],env=env,capture_output=True,timeout=3)
    def validate(self,value=None,raw=None,rc='0'):
        if raw is None:raw=json.dumps(self.good if value is None else value).encode()
        result=subprocess.run([sys.executable,'-I','-B','-c',self.validator,rc],input=raw,capture_output=True,timeout=3)
        self.assertEqual(result.stderr,b'');self.assertNotIn(CANARY.encode(),result.stdout)
        return result
    def test_owner_main_and_four_input_formats_precede_network(self):
        self.assertEqual(self.guard_run().returncode,0)
        for key in ('ACTOR','TRIGGERING_ACTOR','REF','AD_ID','CONTENT_ID','AD_PID','CONTENT_PID','HOST_FINGERPRINT'):
            process=self.guard_run(**{key:CANARY});self.assertNotEqual(process.returncode,0);self.assertNotIn(CANARY.encode(),process.stdout+process.stderr)
        for values in ({'AD_ID':'A'*64},{'CONTENT_ID':'a'*64},{'AD_PID':'0'},{'AD_PID':'01'},
                       {'AD_PID':'4294967296'},{'CONTENT_PID':'101'},{'CONTENT_PID':'201;'+CANARY}):
            self.assertNotEqual(self.guard_run(**values).returncode,0)
    def test_manual_only_pins_actor_host_actions_and_no_write_permissions(self):
        self.assertEqual(re.findall(r'^  ([a-z_]+):',self.source.split('\npermissions:',1)[0],re.M),['workflow_dispatch'])
        self.assertIn('contents: read',self.source);self.assertNotIn('contents: write',self.source)
        self.assertIn('group: naver-retirement-control-preflight\n  cancel-in-progress: false',self.source)
        self.assertIn('persist-credentials: false',self.source)
        self.assertTrue(all(re.fullmatch('[0-9a-f]{40}',s) for s in re.findall(r'uses: [^@\s]+@(\S+)',self.source)))
        remotes=[p for p in self.parts if 'uses: appleboy/' in p];self.assertEqual(len(remotes),4)
        for part in remotes:self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}',part)
        tests=next(i for i,p in enumerate(self.parts) if 'unittest discover' in p)
        self.assertTrue(all(i>tests for i,p in enumerate(self.parts) if 'uses: appleboy/' in p))
        self.assertIn("-p 'test_retirement_control*.py'",self.parts[tests])
    def test_public755_644_staging_remote700_600_sha_and_narrow_cleanup(self):
        self.assertIn('chmod 755 control-preflight-ship',self.source)
        self.assertIn('chmod 644 control-preflight-ship/retirement_control_preflight.py',self.source)
        self.assertIn('chown 0:0 -- "$helper"',self.source);self.assertIn('chmod 600 "$helper"',self.source)
        self.assertIn('0:600:1',self.source);self.assertIn('"$NRC_SHA"',self.script)
        self.assertIn('timeout -k 5s 80s python3 -I -B "$helper"',self.script)
        cleanup=self.parts[-1];self.assertIn("if: always() && steps.prepare_remote.outcome == 'success'",cleanup)
        self.assertIn('rm -f -- "$helper"',cleanup);self.assertIn('rmdir -- "$incoming"',cleanup)
        self.assertNotIn('rm -rf',self.source);self.assertNotIn('upload-artifact',self.source)
    def test_every_run_and_remote_shell_parses_and_validator_compiles(self):
        for part in self.parts:
            for key in ('run','script'):
                if re.search(r'^ +'+key+r': \|',part,re.M):
                    result=subprocess.run(['/bin/bash','-n'],input=block(part,key),text=True,capture_output=True,timeout=3)
                    self.assertEqual(result.returncode,0,result.stderr)
        ast.parse(self.validator)
    def test_actual_synthetic_helper_receipt_passes_closed_output_contract(self):
        process=self.validate();self.assertEqual(process.returncode,0)
        self.assertTrue(process.stdout.startswith(b'NAVER_RETIREMENT_CONTROL_PREFLIGHT='))
        self.assertNotIn(b'root',process.stdout)
    def test_unknown_keys_values_bools_and_unverified_claims_refused(self):
        mutations=[lambda x:x.update(extra=CANARY),lambda x:x.update(loaded_config_verified=True),
                   lambda x:x['files'][0]['metadata'].update(uid=True),lambda x:x['files'][0].update(resolved_path='/tmp/evil'),
                   lambda x:x['files'][0]['locations'][0].update(path='/unknown'),
                   lambda x:x['containers'][0].update(restart_policy='unknown'),lambda x:x['containers'][0].update(pid=True),
                   lambda x:x['files'][0].update(aliases=['ad','ad'])]
        for mutate in mutations:
            value=copy.deepcopy(self.good);mutate(value);self.assertNotEqual(self.validate(value).returncode,0)
    def test_bounds_hash_masked_keys_duplicate_json_nan_and_multiline_refused(self):
        for raw in (b'x'*65537,b'{}\n{}',b'{"status":0,"status":1}',b'NaN',b'{"root":1}'):
            self.assertNotEqual(self.validate(raw=raw).returncode,0)
        for mutate in (lambda x:x['files'][0].update(sha256='g'*64),
                       lambda x:x['files'][0]['locations'][0].update(end=999999),
                       lambda x:x['files'][0]['metadata'].update(bytes=262145),
                       lambda x:x['files'][0].update(protected_locations=[])):
            value=copy.deepcopy(self.good);mutate(value);self.assertNotEqual(self.validate(value).returncode,0)
    def test_failure_rc_and_closed_reason_enum(self):
        minimal={'status':'incomplete','error':'time_limit','read_only':True,'changes_applied':False}
        self.assertEqual(self.validate(minimal,rc='2').returncode,0)
        self.assertNotEqual(self.validate(minimal,rc='0').returncode,0)
        minimal['error']=CANARY;self.assertNotEqual(self.validate(minimal,rc='2').returncode,0)
        self.assertNotEqual(self.validate(rc='2').returncode,0)
    def test_all_literal_helper_failures_have_allowlisted_public_reasons(self):
        helper=ast.parse((BASE/'deploy/naver/retirement_control_preflight.py').read_text());errors=set()
        for node in ast.walk(helper):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
                index=1 if node.func.id=='check' else 0 if node.func.id=='Refused' else None
                if index is not None and len(node.args)>index and isinstance(node.args[index],ast.Constant):errors.add(node.args[index].value)
        assignment=next(n for n in ast.walk(ast.parse(self.validator)) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='errors' for t in n.targets))
        self.assertLessEqual(errors,ast.literal_eval(assignment.value))


if __name__=='__main__':unittest.main()
