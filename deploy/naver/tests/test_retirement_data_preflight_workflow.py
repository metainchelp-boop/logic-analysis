"""Exercise real local Bash guards and output-validator code; no SSH or app data."""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

BASE=Path(__file__).resolve().parents[3]
WORKFLOW=BASE/'.github/workflows/naver-data-preflight.yml'
CANARY='PRIVATE_ENV_CUSTOMER_VALUE_CANARY'


def steps(source):
    return [p for p in re.split(r'(?=^      - )',source,flags=re.M) if p.startswith('      - ')]


def block(source,key):
    m=re.search(r'^( +)'+re.escape(key)+r': \|\n',source,re.M)
    if m is None:raise AssertionError('literal block absent')
    indent=len(m[1]);out=[]
    for line in source[m.end():].splitlines():
        if line.strip() and len(line)-len(line.lstrip())<=indent:break
        out.append(line)
    return textwrap.dedent('\n'.join(out))+'\n'


def complete():
    metadata={'device':1,'inode':2,'mode':0o700,'uid':0,'gid':0,'links':2,'bytes':4096}
    tree={'files':1,'directories':0,'bytes':11,'blocks_bytes':4096,'directory_identity':metadata}
    return {'status':'coverage_complete','error':None,'read_only':True,'stop_safety':'not_determined',
        'runtime_selection':'not_proven','data_sets':[dict(tree,alias=alias) for alias in ('ad','content','autobid')],
        'tmp':copy.deepcopy(tree),'candidates':[{'alias':n,'status':'absent'} for n in range(1,33)],
        'routes':{'configured_routes':11,'fallback_routes':6,'coverage':'configured_and_all_known_fallbacks_covered','runtime_selection':'not_proven'},
        'checks':dict.fromkeys(('container_mount_volume','reviewed_route_sources','route_coverage','tree_coverage','host_scan','final_guards'),True),
        'host':dict.fromkeys(('pids','fds','shared_writable_maps','covered_writable_fds','covered_shared_writable_maps','external_writers',
                             'target_uncovered_writers','exited_pids','deleted_unique_count','content_deleted_unique_count',
                             'unrelated_fd_changes','unrelated_mapping_changes','unrelated_process_changes','late_processes_scanned'),0)|
                {'deleted_identities':[],'prior_four_zero_pattern_matches':False,'host_passes':2}}


class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=WORKFLOW.read_text();cls.parts=steps(cls.source);cls.guard=block(cls.parts[0],'run')
        cls.execute=next(p for p in cls.parts if 'NAVER_RETIREMENT_DATA_PREFLIGHT=' in p)
        cls.script=block(cls.execute,'script')
        match=re.search(r"python3 -I -B -c '\n(.*?)\n' \"\$rc\"",cls.script,re.S)
        if match is None:raise AssertionError('validator absent')
        cls.validator=match[1];ast.parse(cls.validator)

    def guard_run(self,**override):
        env={'ACTOR':'metainchelp-boop','TRIGGERING_ACTOR':'metainchelp-boop','REF':'refs/heads/main',
             'AD_ID':'a'*64,'CONTENT_ID':'c'*64,'AD_PID':'101','CONTENT_PID':'201','HOST_FINGERPRINT':'SHA256:'+'x'*43}
        env.update(override)
        return subprocess.run(['/bin/bash','--noprofile','--norc','-c',self.guard],env=env,capture_output=True,text=True,timeout=3)
    def rejected(self,**override):
        p=self.guard_run(**override);self.assertNotEqual(p.returncode,0);self.assertNotIn(CANARY,p.stdout+p.stderr);self.assertEqual(p.stderr,'')
    def validation(self,data=None,raw=None,rc='0'):
        if raw is None:raw=json.dumps(complete() if data is None else data).encode()
        p=subprocess.run([sys.executable,'-I','-B','-c',self.validator,rc],input=raw,capture_output=True,timeout=3)
        self.assertNotIn(CANARY.encode(),p.stdout+p.stderr)
        self.assertEqual(p.stderr,b'')
        return p
    def test_real_synthetic_helper_receipt_passes_exact_workflow_validator(self):
        spec=importlib.util.spec_from_file_location('data_preflight_fixture',BASE/'deploy/naver/tests/test_retirement_data_preflight.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        fixture=module.Fixture('test_complete_fixture_reports_finite_coverage_without_stop_claim')
        try:
            fixture.setUp();data=fixture.collect()
            self.assertEqual(data['status'],'coverage_complete',data)
            process=self.validation(data)
            self.assertEqual(process.returncode,0,process.stdout)
            self.assertTrue(process.stdout.startswith(b'NAVER_RETIREMENT_DATA_PREFLIGHT='))
        finally:fixture.doCleanups()
    def test_only_tooling_change_is_ci_covered_and_does_not_redeploy_app(self):
        deploy=(BASE/'.github/workflows/deploy.yml').read_text()
        ci=(BASE/'.github/workflows/naver-tools-check.yml').read_text()
        self.assertIn("      - '.github/workflows/naver-data-preflight.yml'",deploy.split('  workflow_dispatch:',1)[0])
        self.assertIn("'.github/workflows/naver-data-preflight.yml'",ci.split('  push:',1)[0])
    def test_owner_main_targets_and_required_host_pass(self):
        p=self.guard_run();self.assertEqual(p.returncode,0);self.assertEqual(p.stdout+p.stderr,'')
    def test_actor_triggering_actor_and_ref_each_fail(self):
        for key in ('ACTOR','TRIGGERING_ACTOR','REF'):
            with self.subTest(key=key):self.rejected(**{key:CANARY})
    def test_both_id_formats_duplicate_and_injection_fail(self):
        for key in ('AD_ID','CONTENT_ID'):
            for value in ('','a'*63,'A'*64,'a'*64+'\n'+CANARY,'../'+CANARY):self.rejected(**{key:value})
        self.rejected(CONTENT_ID='a'*64)
    def test_both_pid_formats_range_duplicate_and_injection_fail(self):
        for key in ('AD_PID','CONTENT_PID'):
            for value in ('0','-1','01','4294967296','1;echo '+CANARY,'201\n'+CANARY):self.rejected(**{key:value})
        self.rejected(CONTENT_PID='101');self.assertEqual(self.guard_run(AD_PID='4294967295').returncode,0)
    def test_host_fingerprint_is_required_not_optional(self):
        for value in ('',CANARY,'SHA256:'+'x'*42,'SHA256:'+'x'*43+'\n'+CANARY):self.rejected(HOST_FINGERPRINT=value)
    def test_manual_readonly_separate_concurrency_guard_before_network(self):
        header=self.source.split('\npermissions:',1)[0]
        self.assertEqual(re.findall(r'^  ([a-z_]+):',header,re.M),['workflow_dispatch'])
        self.assertIn('contents: read',self.source);self.assertNotIn('contents: write',self.source)
        self.assertIn('group: naver-retirement-data-preflight\n  cancel-in-progress: false',self.source)
        self.assertIn('persist-credentials: false',self.source)
        self.assertTrue(all(re.fullmatch('[0-9a-f]{40}',v) for v in re.findall(r'uses: [^@\s]+@(\S+)',self.source)))
        tests=next(i for i,p in enumerate(self.parts) if 'unittest discover' in p)
        self.assertTrue(all(i>tests>0 for i,p in enumerate(self.parts) if 'uses: appleboy/' in p))
        self.assertIn("-p 'test_retirement_data*.py'",self.parts[tests])
    def test_all_four_remote_steps_pin_same_host_and_have_bounds(self):
        remote=[p for p in self.parts if 'uses: appleboy/' in p];self.assertEqual(len(remote),4)
        for p in remote:
            self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}',p)
            self.assertRegex(p,r'command_timeout: (30|45|110)s')
        self.assertNotIn('allenvs:',self.source);self.assertNotIn('debug: true',self.source)
    def test_public_ship_permissions_work_before_uid1000_transport(self):
        ship=next(p for p in self.parts if 'mkdir data-preflight-ship' in p)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'deploy/naver').mkdir(parents=True)
            (path/'deploy/naver/retirement_data_preflight.py').write_text('PUBLIC_TEST_SOURCE')
            (path/'bin').mkdir();stub=path/'bin/sha256sum'
            stub.write_text('#!/bin/sh\nprintf "%064d  public\\n" 0\n');stub.chmod(0o755)
            p=subprocess.run(['/bin/bash','--noprofile','--norc','-c',block(ship,'run')],cwd=tmp,
                env={'PATH':str(path/'bin')+os.pathsep+os.defpath,'GITHUB_ENV':str(path/'env'),
                     'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'},capture_output=True,timeout=3)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(stat.S_IMODE((path/'data-preflight-ship').stat().st_mode),0o755)
            self.assertEqual(stat.S_IMODE((path/'data-preflight-ship/retirement_data_preflight.py').stat().st_mode),0o644)
    def test_remote_one_file_normalization_exclusive_namespace_and_timeout(self):
        prep=next(p for p in self.parts if 'id: prepare_remote' in p)
        self.assertIn('mkdir "/tmp/metainc-data-preflight-$NRD_RUN"',prep);self.assertNotIn('mkdir -p',prep)
        self.assertIn('[ ! -L /tmp ]',prep);self.assertIn('umask 077',prep)
        for token in ('[ ! -L "$incoming" ]','[ ! -L "$helper" ]',"0:700",'chown 0:0 -- "$helper"',
                      'chmod 600 "$helper"','0:600:1','timeout -k 5s 80s python3 -I -B "$helper"',
                      '2>/dev/null) || rc=$?','case "$rc" in 0|2)', 'sys.stdin.buffer.read(65537)'):
            self.assertIn(token,self.script)
        self.assertLess(self.script.index('chmod 600'),self.script.index('sha256sum "$helper"'))
        self.assertLess(self.script.index('sha256sum "$helper"'),self.script.index('out=$('))
        transfer=next(p for p in self.parts if 'uses: appleboy/scp-action@' in p)
        self.assertIn('source: data-preflight-ship/retirement_data_preflight.py',transfer)
        self.assertIn('overwrite: false',transfer);self.assertIn('strip_components: 1',transfer)
        self.assertNotRegex(self.source,r'docker\s+(stop|rm|exec|run|pause)|rm\s+-rf|rsync|sqlite3|upload-artifact')
    def test_cleanup_is_always_scoped_hash_nlink_nofollow_and_empty_directory_only(self):
        cleanup=self.parts[-1]
        self.assertIn("if: always() && steps.prepare_remote.outcome == 'success'",cleanup)
        for token in ('[ ! -L "$incoming" ]','0:700','[ ! -L "$helper" ]',"stat -c '%h'",'sha256sum "$helper"',
                      'rm -f -- "$helper" 2>/dev/null','rmdir -- "$incoming" 2>/dev/null'):
            self.assertIn(token,cleanup)
        self.assertNotIn('rm -r',cleanup)
    def test_all_shell_blocks_parse_and_embedded_validator_compiles(self):
        for p in self.parts:
            for key in ('run','script'):
                if re.search(r'^ +'+key+r': \|$',p,re.M):
                    checked=subprocess.run(['/bin/bash','-n'],input=block(p,key),capture_output=True,text=True,timeout=3)
                    self.assertEqual(checked.returncode,0,checked.stderr)
    def test_full_success_has_only_prefix_and_exact_json(self):
        p=self.validation();self.assertEqual(p.returncode,0)
        prefix=b'NAVER_RETIREMENT_DATA_PREFLIGHT=';self.assertTrue(p.stdout.startswith(prefix))
        self.assertEqual(json.loads(p.stdout[len(prefix):]),complete());self.assertNotIn(b'root',p.stdout)
    def test_failed_partial_and_minimal_public_metadata_are_allowed_only_with_rc2(self):
        data={'status':'incomplete','error':'source_unreviewed','read_only':True,'stop_safety':'not_determined'}
        self.assertEqual(self.validation(data,rc='2').returncode,0)
        self.assertNotEqual(self.validation(data).returncode,0)
        data=complete();data.update(status='incomplete',error='writers_unresolved');data['host']['external_writers']=1
        self.assertEqual(self.validation(data,rc='2').returncode,0)
    def test_extra_keys_unknown_errors_private_strings_and_boolean_counts_refused(self):
        variants=[]
        d=complete();d[CANARY]=CANARY;variants.append(d)
        d=complete();d['host']['fds']=True;variants.append(d)
        d=complete();d['data_sets'][0]['alias']=CANARY;variants.append(d)
        d=complete();d.update(status='incomplete',error='unknown_private_lowercase');variants.append(d)
        d=complete();d['checks']['unapproved']=True;variants.append(d)
        d=complete();d['routes']['coverage']=CANARY;variants.append(d)
        d=complete();d['host']['external_writers']=1;variants.append(d)
        d=complete();d['candidates'][0]={'alias':1,'status':CANARY};variants.append(d)
        for data in variants:self.assertNotEqual(self.validation(data).returncode,0)
    def test_bounds_multiline_duplicate_nan_masked_keys_and_incomplete_success_refused(self):
        for raw in (b'x'*65537,b'{}\n{}',b'{"status":1,"status":2}',b'NaN',
                    json.dumps(complete()).replace('data_sets','***_sets').encode()):
            self.assertNotEqual(self.validation(raw=raw).returncode,0)
        for key in ('tmp','host','routes','data_sets','candidates'):
            value=complete()
            if key=='tmp':del value[key]
            elif key in ('host','routes'):value[key]=None
            else:value[key]=[]
            self.assertNotEqual(self.validation(value).returncode,0)
    def test_deleted_metadata_schema_numeric_reference_bounds_and_no_raw_pid(self):
        value=complete();row={'device':1,'inode':2,'mode':0o600,'uid':0,'gid':0,'links':0,'bytes':0,
            'mount_id':1,'writable':True,'app':'content','references':2,'heartbeat_path_compatible':True,
            'memory_backed_hint':True,'readonly_hint':False}
        value['host'].update(deleted_identities=[row],deleted_unique_count=1,content_deleted_unique_count=1)
        self.assertEqual(self.validation(value).returncode,0)
        for name,item in (('pid',123),('references',257),('app',CANARY),('memory_backed_hint',1)):
            bad=copy.deepcopy(value);bad['host']['deleted_identities'][0][name]=item
            self.assertNotEqual(self.validation(bad).returncode,0)
    def test_every_literal_helper_failure_is_covered_by_fixed_output_allowlist(self):
        tree=ast.parse((BASE/'deploy/naver/retirement_data_preflight.py').read_text())
        failures={node.args[0].value for node in ast.walk(tree) if isinstance(node,ast.Call) and
                  isinstance(node.func,ast.Name) and node.func.id=='Refused' and node.args and isinstance(node.args[0],ast.Constant)}
        failures|={'observation_failed','time_limit','request_or_deadline_refused','output_limit'}
        parsed=ast.parse(self.validator)
        allowed=next(ast.literal_eval(node.value) for node in ast.walk(parsed) if isinstance(node,ast.Assign) and
                     any(isinstance(t,ast.Name) and t.id=='errors' for t in node.targets))
        self.assertLessEqual(failures,allowed)


if __name__=='__main__':unittest.main()
