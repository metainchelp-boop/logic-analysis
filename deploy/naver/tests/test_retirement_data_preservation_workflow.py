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
import unittest

BASE = Path(__file__).resolve().parents[3]
WORKFLOW = BASE / '.github/workflows/naver-data-preservation.yml'
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
    value = dict(phase=phase, status='prepared', session='data-snapshot-20261102-v1', error=None,
        ssh_public_key=PUBLIC, bytes=None, sha256=None, process_rc=None, backup_verified=False,
        source_bytes=None, archive_bytes=None, object_count=None,
        paused={'ad':'not_observed','content':'not_observed'}, operator_evidence_sha256=None, run='123-1')
    if phase == 'send':
        value.update(status='transferred_unverified', ssh_public_key=None, bytes=257, sha256='a'*64,
            process_rc={'archive':0,'gpg':0,'ssh':0}, source_bytes=351, archive_bytes=4096, object_count=7,
            paused={'ad':'paused','content':'paused'}, operator_evidence_sha256='c'*64)
    elif phase == 'cleanup':
        value.update(status='transport_key_removed', ssh_public_key=None)
    return value


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text()
        cls.parts = [part for part in re.split(r'(?=^      - )', cls.source, flags=re.M) if part.startswith('      - ')]
        cls.guard = block(cls.parts[0], 'run')
        cls.script = block(next(part for part in cls.parts if 'RETIREMENT_DATA_PRESERVATION=' in part), 'script')
        match = re.search(r"if ! printf '%s' \"\$out\" \| python3 -I -B -c '\n(.*?)\n' \"\$NRD_PHASE\"", cls.script, re.S)
        if not match: raise AssertionError('validator missing')
        cls.validator = match[1]; ast.parse(cls.validator)
        match = re.search(r"out=\$\(timeout -k 5s 2430s python3 -I -B -c '\n(.*?)\n' \"\$helper\"", cls.script, re.S)
        if not match: raise AssertionError('snapshot bootstrap missing')
        cls.bootstrap = match[1]; ast.parse(cls.bootstrap)

    def guard_run(self, **changes):
        env = {'ACTOR':'metainchelp-boop','TRIGGERING_ACTOR':'metainchelp-boop','REF':'refs/heads/main',
               'HOST_FINGERPRINT':'SHA256:'+'x'*43,'NRD_PHASE':'prepare','NRD_OPERATOR':''}
        env.update(changes)
        return subprocess.run(['/bin/bash','--noprofile','--norc','-c',self.guard],env=env,capture_output=True,timeout=3)

    def validate(self, value=None, raw=None, phase=None, rc='0', evidence='c'*64):
        value = receipt() if value is None else value
        if raw is None: raw = json.dumps(value).encode()
        process = subprocess.run([sys.executable,'-I','-B','-c',self.validator, phase or value['phase'],rc,'123-1',evidence],
                                 input=raw,capture_output=True,timeout=3)
        self.assertNotIn(CANARY.encode(),process.stdout+process.stderr)
        self.assertEqual(process.stderr,b'')
        return process

    def test_valid_phases_and_real_synthetic_lifecycle_output(self):
        path = BASE / 'deploy/naver/tests/test_retirement_data_source.py'
        spec = importlib.util.spec_from_file_location('workflow_data_source_fixture', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        fixture = module.SourceFixture('test_lifecycle_keeps_paused_apps_and_only_removes_transport_key')
        try:
            fixture.setUp()
            for phase in ('prepare','send','cleanup','cleanup'):
                result = fixture.source.perform(phase)
                self.assertEqual(self.validate(result).returncode,0)
        finally: fixture.doCleanups()

    def test_actor_triggering_actor_main_phase_and_host_are_guarded(self):
        self.assertEqual(self.guard_run().returncode,0)
        for key in ('ACTOR','TRIGGERING_ACTOR','REF','NRD_PHASE','HOST_FINGERPRINT'):
            result=self.guard_run(**{key:CANARY})
            self.assertNotEqual(result.returncode,0);self.assertNotIn(CANARY.encode(),result.stdout+result.stderr)

    def test_send_requires_only_narrow_hex_operator_evidence(self):
        self.assertEqual(self.guard_run(NRD_PHASE='send',NRD_OPERATOR='c'*64).returncode,0)
        for value in ('', 'c'*63, 'C'*64, 'x;echo '+CANARY, 'a'*64+'\n'):
            self.assertNotEqual(self.guard_run(NRD_PHASE='send',NRD_OPERATOR=value).returncode,0)
        self.assertNotEqual(self.guard_run(NRD_OPERATOR='c'*64).returncode,0)

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
        for phase in ('prepare','cleanup'):
            for key,value in (('source_bytes',1),('operator_evidence_sha256','c'*64),('paused',{'ad':'paused','content':'paused'})):
                data=receipt(phase);data[key]=value;self.assertNotEqual(self.validate(data).returncode,0)

    def test_limits_bool_counts_duplicate_json_and_multiline_are_refused(self):
        for key,value in (('bytes',2300300289),('source_bytes',2147483649),('archive_bytes',2283523073),('object_count',100081),('bytes',True)):
            data=receipt('send');data[key]=value;self.assertNotEqual(self.validate(data).returncode,0)
        for raw in (b'{"x":1,"x":2}',b'{}\n{}\n',b' '*4097,b'{"x":NaN}'):
            self.assertNotEqual(self.validate(raw=raw).returncode,0)

    def test_public_key_requires_exact_wire_no_comment(self):
        for key in (PUBLIC+' comment',PUBLIC[:-1],'ssh-rsa '+PUBLIC.split()[1], 'ssh-ed25519 '+'A'*68):
            data=receipt();data['ssh_public_key']=key;self.assertNotEqual(self.validate(data).returncode,0)

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
        self.assertEqual(files,{'retirement_data_source.py','retirement_data_archive.py','retirement_data_preflight.py',
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
        self.assertIn("      - '.github/workflows/naver-data-preservation.yml'",(BASE/'.github/workflows/deploy.yml').read_text())
        self.assertIn("'.github/workflows/naver-data-preservation.yml'",(BASE/'.github/workflows/naver-tools-check.yml').read_text())
