"""Execute local guard/validator snippets and synthetic source receipts; never SSH."""
import ast
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import tempfile
import stat
import unittest

BASE = Path(__file__).resolve().parents[3]
WORKFLOW = BASE / '.github/workflows/naver-data-continuation.yml'
CANARY = 'PRIVATE_ENV_CONTENT_CANARY'
PUBLIC = 'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + b'x'*32).decode()


def block(source, key):
    match = re.search(r'^( +)' + re.escape(key) + r': \|\n', source, re.M)
    if not match: raise AssertionError('literal block missing')
    indent = len(match[1]); rows = []
    for line in source[match.end():].splitlines():
        if line.strip() and len(line) - len(line.lstrip()) <= indent: break
        rows.append(line)
    return textwrap.dedent('\n'.join(rows)) + '\n'


def receipt(phase='prepare'):
    value = dict(phase=phase, status='prepared', session='data-snapshot-continuation-20261102-v1', error=None,
        ssh_public_key=PUBLIC, bytes=None, sha256=None, process_rc=None, backup_verified=False,
        source_bytes=None, archive_bytes=None, object_count=None,
        paused={'ad':'paused','content':'paused'}, operator_evidence_sha256='c'*64, run='123-1')
    if phase == 'send':
        value.update(status='transferred_unverified', ssh_public_key=None, bytes=257, sha256='a'*64,
            process_rc={'archive':0,'gpg':0,'ssh':0}, source_bytes=351, archive_bytes=4096, object_count=7,
            paused={'ad':'paused','content':'paused'}, operator_evidence_sha256='c'*64)
    elif phase == 'cleanup':
        value.update(status='transport_key_removed', ssh_public_key=None,
            paused={'ad':'not_observed','content':'not_observed'},operator_evidence_sha256=None)
    return value


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text()
        cls.parts = [part for part in re.split(r'(?=^      - )', cls.source, flags=re.M) if part.startswith('      - ')]
        cls.guard = block(cls.parts[0], 'run')
        cls.script = block(next(part for part in cls.parts if 'RETIREMENT_DATA_CONTINUATION=' in part), 'script')
        match = re.search(r"if ! printf '%s' \"\$out\" \| python3 -I -B -c '\n(.*?)\n' \"\$NRD_PHASE\"", cls.script, re.S)
        if not match: raise AssertionError('validator missing')
        cls.validator = match[1]; ast.parse(cls.validator)
        match = re.search(r"out=\$\(timeout -k 5s 2430s python3 -I -B -c '\n(.*?)\n' \"\$helper\"", cls.script, re.S)
        if not match: raise AssertionError('snapshot bootstrap missing')
        cls.bootstrap = match[1]; ast.parse(cls.bootstrap)

    def guard_run(self, **changes):
        env = {'ACTOR':'metainchelp-boop','TRIGGERING_ACTOR':'metainchelp-boop','REF':'refs/heads/main',
               'HOST_FINGERPRINT':'SHA256:'+'x'*43,'NRD_PHASE':'prepare','NRD_OPERATOR':'c'*64}
        env.update(changes)
        return subprocess.run(['/bin/bash','--noprofile','--norc','-c',self.guard],env=env,capture_output=True,timeout=3)

    def validate(self, value=None, raw=None, phase=None, rc='0', evidence=None):
        value = receipt() if value is None else value
        if raw is None: raw = json.dumps(value).encode()
        if evidence is None: evidence = '' if (phase or value['phase']) == 'cleanup' else 'c'*64
        process = subprocess.run([sys.executable,'-I','-B','-c',self.validator, phase or value['phase'],rc,'123-1',evidence],
                                 input=raw,capture_output=True,timeout=3)
        self.assertNotIn(CANARY.encode(),process.stdout+process.stderr)
        self.assertEqual(process.stderr,b'')
        return process

    def test_valid_closed_phase_receipts(self):
        for phase in ('prepare','send','cleanup'):
            self.assertEqual(self.validate(receipt(phase)).returncode,0)

    def test_actual_synthetic_source_lifecycle_matches_transport_schema(self):
        path=BASE/'deploy/naver/tests/test_retirement_data_continuation.py'
        spec=importlib.util.spec_from_file_location('workflow_continuation_fixture',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        fixture=module.SourceFixture('test_lifecycle_keeps_paused_apps_and_only_removes_transport_key')
        try:
            fixture.setUp()
            for phase in ('prepare','send','cleanup','cleanup'):
                result=fixture.check(phase)
                self.assertEqual(self.validate(result).returncode,0)
        finally:fixture.doCleanups()

    def test_actor_triggering_actor_main_phase_and_host_are_guarded(self):
        self.assertEqual(self.guard_run().returncode,0)
        for key in ('ACTOR','TRIGGERING_ACTOR','REF','NRD_PHASE','HOST_FINGERPRINT'):
            result=self.guard_run(**{key:CANARY})
            self.assertNotEqual(result.returncode,0);self.assertNotIn(CANARY.encode(),result.stdout+result.stderr)

    def test_prepare_and_send_require_operator_evidence_before_any_remote_step(self):
        for phase in ('prepare','send'):
            self.assertEqual(self.guard_run(NRD_PHASE=phase,NRD_OPERATOR='c'*64).returncode,0)
            for value in ('', 'c'*63, 'C'*64, 'x;echo '+CANARY, 'a'*64+'\n'):
                result = self.guard_run(NRD_PHASE=phase,NRD_OPERATOR=value)
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn(CANARY.encode(),result.stdout+result.stderr)
        self.assertEqual(self.guard_run(NRD_PHASE='cleanup',NRD_OPERATOR='').returncode,0)
        self.assertNotEqual(self.guard_run(NRD_PHASE='cleanup',NRD_OPERATOR='c'*64).returncode,0)
        self.assertLess(self.source.index('OPERATOR_EVIDENCE_REQUIRED'),self.source.index('uses: appleboy/'))

    def test_success_cannot_claim_backup_verified_or_extra_private_fields(self):
        for key,value in (('backup_verified',True),('secret',CANARY),('session',CANARY),('run','124-1')):
            data=receipt();data[key]=value;self.assertNotEqual(self.validate(data).returncode,0)

    def test_exact_fifteen_fields_and_errors_enum_are_required(self):
        for key in receipt():
            data=receipt();data.pop(key);self.assertNotEqual(self.validate(data,phase='prepare').returncode,0)
        data=receipt();data.update(status='failed',error=CANARY)
        self.assertNotEqual(self.validate(data,rc='2').returncode,0)
        data['error']='policy_unresolved';self.assertEqual(self.validate(data,rc='2').returncode,0)
        self.assertNotEqual(self.validate(data,rc='0').returncode,0)

    def test_success_crossfields_require_counts_all_rc_zero_and_current_evidence(self):
        for key,value in (('bytes',0),('archive_bytes',100),('object_count',None),('process_rc',{'archive':0,'gpg':1,'ssh':0}),
                          ('paused',{'ad':'paused','content':'pause_requested'}),('operator_evidence_sha256','d'*64),('ssh_public_key',PUBLIC)):
            data=receipt('send');data[key]=value;self.assertNotEqual(self.validate(data).returncode,0)
        for key,value in (('source_bytes',1),('operator_evidence_sha256',None),
                          ('operator_evidence_sha256','d'*64),('paused',{'ad':'paused','content':'not_observed'}),
                          ('paused',{'ad':'not_observed','content':'not_observed'}),('ssh_public_key',None)):
            data=receipt('prepare');data[key]=value;self.assertNotEqual(self.validate(data).returncode,0)
        for key,value in (('source_bytes',1),('operator_evidence_sha256','c'*64),('paused',{'ad':'paused','content':'paused'})):
            data=receipt('cleanup');data[key]=value;self.assertNotEqual(self.validate(data).returncode,0)

    def test_limits_bool_counts_duplicate_json_and_multiline_are_refused(self):
        for key,value in (('bytes',2300300289),('source_bytes',2147483649),('archive_bytes',2283523073),('object_count',100081),('bytes',True)):
            data=receipt('send');data[key]=value;self.assertNotEqual(self.validate(data).returncode,0)
        for raw in (b'{"x":1,"x":2}',b'{}\n{}\n',b' '*4097,b'{"x":NaN}'):
            self.assertNotEqual(self.validate(raw=raw).returncode,0)

    def test_public_key_requires_exact_wire_no_comment(self):
        for key in (PUBLIC+' comment',PUBLIC[:-1],'ssh-rsa '+PUBLIC.split()[1], 'ssh-ed25519 '+'A'*68):
            data=receipt();data['ssh_public_key']=key;self.assertNotEqual(self.validate(data).returncode,0)

    def test_failure_may_report_unstarted_children_without_claiming_transfer(self):
        data=receipt('send')
        data.update(status='failed',error='pipeline_failed',process_rc={'archive':None,'gpg':2,'ssh':None})
        self.assertEqual(self.validate(data,rc='2').returncode,0)
        data['status']='transferred_unverified';data['error']=None
        self.assertNotEqual(self.validate(data).returncode,0)
        data.update(status='failed',error='pipeline_failed')
        for value in (True,256,-256,'0',CANARY):
            data['process_rc']['archive']=value
            self.assertNotEqual(self.validate(data,rc='2').returncode,0)
        data['process_rc']={'gpg':0,'ssh':0}
        self.assertNotEqual(self.validate(data,rc='2').returncode,0)

    def test_source_failure_allowlist_matches_workflow_without_running_source(self):
        source=ast.parse((BASE/'deploy/naver/retirement_data_continuation.py').read_text())
        values={}
        for node in source.body:
            if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='frozenset':
                for target in node.targets:
                    if isinstance(target,ast.Name) and target.id in {'ERRORS','PRODUCER_CODES','PRODUCER_COMMAND_CODES'}:
                        values[target.id]=set(ast.literal_eval(node.value.args[0]))
        producer_union=[node.value for node in source.body if isinstance(node,ast.Assign)
                        and isinstance(node.value,ast.BinOp) and any(isinstance(target,ast.Name)
                        and target.id=='PRODUCER_CODES' for target in node.targets)]
        self.assertEqual(len(producer_union),1)
        self.assertEqual(ast.dump(producer_union[0]),ast.dump(ast.parse('PRODUCER_CODES | PRODUCER_COMMAND_CODES',mode='eval').body))
        expected=values['ERRORS']|{'producer_'+code for code in values['PRODUCER_CODES']|values['PRODUCER_COMMAND_CODES']}
        found=[node for node in ast.walk(ast.parse(self.validator)) if isinstance(node,ast.Assign)
               and any(isinstance(target,ast.Name) and target.id=='errors' for target in node.targets)]
        self.assertEqual(len(found),1)
        self.assertEqual(set(ast.literal_eval(found[0].value)),expected)
        for label in ('old_attempt_refused','old_transport_not_closed','producer_not_frozen','producer_command_failed','producer_interrupted'):
            data=receipt();data.update(status='failed',error=label)
            self.assertEqual(self.validate(data,rc='2').returncode,0)

    def test_all_shell_literals_parse_and_no_expression_inside_remote_scripts(self):
        for part in self.parts:
            for key in ('run','script'):
                if re.search(r'^ +'+key+r': \|',part,re.M):
                    body=block(part,key)
                    result=subprocess.run(['/bin/bash','-n'],input=body.encode(),capture_output=True,timeout=3)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertNotIn('${{',body)

    def test_only_fixed_public_six_files_are_shipped_and_cleanup_is_narrow(self):
        source=next(part for part in self.parts if 'uses: appleboy/scp-action' in part)
        line=re.search(r'^          source: (.+)$',source,re.M)[1]
        files={name.split('/')[-1] for name in line.split(',')}
        self.assertEqual(files,{'retirement_data_continuation.py','retirement_data_archive.py','retirement_data_preflight.py',
                               'retirement_control_preflight.py','recovery-public.asc','server-b-known-hosts'})
        cleanup=block(self.parts[-1],'script')
        self.assertNotIn('rm -rf',cleanup);self.assertNotIn('source-transport-key',cleanup)
        self.assertIn('rmdir -- "$incoming"',cleanup)
        self.assertNotIn('GITHUB_TOKEN',self.source)

    def test_source_snapshot_has_no_follow_same_fd_hash_then_compile(self):
        for token in ('O_NOFOLLOW','st_nlink!=1','st_uid!=0','0o600','os.read(fd','os.fstat(fd)',
                      'hashlib.sha256(body).hexdigest()!=digest','exec(compile(bytes(body)'):
            self.assertIn(token,self.bootstrap)
        self.assertNotIn('importlib',self.bootstrap)

    def test_manual_main_only_concurrency_hostpins_and_no_product_deployment(self):
        top=self.source.split('permissions:',1)[0]
        self.assertIn('workflow_dispatch:',top);self.assertNotIn('  push:',top);self.assertNotIn('  schedule:',top)
        self.assertIn('cancel-in-progress: false',self.source)
        self.assertIn('2430s',self.source);self.assertIn('command_timeout: 42m',self.source)
        for part in self.parts:
            if 'uses: appleboy/' in part:self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}',part)
        actions=re.findall(r'uses: (\S+)',self.source)
        self.assertTrue(actions)
        for action in actions:self.assertRegex(action,r'^[A-Za-z0-9_/-]+@[0-9a-f]{40}$')
        self.assertIn('group: naver-data-preservation',self.source)
        self.assertNotIn('docker pause',self.source)
        self.assertNotIn('docker unpause',self.source)
        self.assertNotIn('docker stop',self.source)

    def test_public_staging_is_readable_by_distinct_scp_uid_without_host_chown(self):
        stage=block(next(part for part in self.parts if 'mkdir preservation-ship' in part),'run')
        with tempfile.TemporaryDirectory(prefix='continuation-public-stage-') as temporary:
            root=Path(temporary)
            folder=root/'deploy/naver';(folder/'preservation').mkdir(parents=True)
            names=('retirement_data_continuation.py','retirement_data_archive.py',
                   'retirement_data_preflight.py','retirement_control_preflight.py')
            for name in names:(folder/name).write_text('# Public synthetic helper\n')
            for name in ('recovery-public.asc','server-b-known-hosts'):
                (folder/'preservation'/name).write_text('PUBLIC_SYNTHETIC_ASSET\n')
            env=dict(os.environ,GITHUB_ENV=str(root/'environment'),GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1')
            result=subprocess.run(['/bin/bash','--noprofile','--norc','-c',stage],cwd=root,env=env,capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            incoming=root/'preservation-ship'
            self.assertEqual(stat.S_IMODE(incoming.stat().st_mode),0o755)
            for path in incoming.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o644)
                self.assertEqual(path.stat().st_uid,os.getuid())

    def test_remote_assets_are_normalized_only_after_regular_unlinked_private_parent_checks(self):
        script=self.script
        parent=script.index('''[ "$(stat -c '%u:%a' "$incoming")" = 0:700 ]''')
        regular=script.index('[ -f "$asset" ]')
        no_link=script.index('[ ! -L "$asset" ]')
        nlink=script.index('''[ "$(stat -c '%h' "$asset")" = 1 ]''')
        chown=script.index('chown 0:0 -- "$asset"')
        private=script.index('chmod 600 "$asset"')
        self.assertLess(parent,regular);self.assertLess(regular,no_link)
        self.assertLess(no_link,nlink);self.assertLess(nlink,chown);self.assertLess(chown,private)

    def test_prior_transport_receipts_and_missing_prepare_evidence_are_refused(self):
        for phase in ('prepare','send'):
            data=receipt(phase);data['session']='data-snapshot-20261102-v1'
            self.assertNotEqual(self.validate(data).returncode,0)
            self.assertNotEqual(self.validate(receipt(phase),evidence='').returncode,0)
        for public_flag in (True,None,'true',0):
            data=receipt();data['paused']['ad']=public_flag
            self.assertNotEqual(self.validate(data).returncode,0)
        data=receipt();data.update(status='failed',error='controls_changed')
        data['paused']['ad']='pause_requested'
        self.assertNotEqual(self.validate(data,rc='2').returncode,0)
