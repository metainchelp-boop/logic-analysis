import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_cold_backup_archive_workflow import blocks
from test_backup_status import B, CANARY

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT/'.github/workflows/naver-backup-status.yml'


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=WORKFLOW.read_text();cls.blocks=blocks(cls.text);cls.guard=cls.blocks[0]
        cls.invoke=next(s for s in cls.blocks if 'out=$(python3' in s)
        cls.validator=cls.invoke.split("python3 -I -B -c '\n",1)[1].split("\n' \"$helper\"",1)[0]

    def gate(self,**changes):
        env=dict(PATH=os.environ.get('PATH',''),ACTOR='metainchelp-boop',TRIGGERING_ACTOR='metainchelp-boop',REF='refs/heads/main',ATTEMPT='1',HOST_FINGERPRINT='SHA256:'+'a'*43)
        env.update(changes)
        return subprocess.run(['/bin/bash','-c',self.guard],env=env,capture_output=True,timeout=3)

    def test_no_inputs_owner_main_host_first_attempt_and_same_global_concurrency(self):
        self.assertEqual(self.gate().returncode,0)
        for key,values in dict(ACTOR=[CANARY],TRIGGERING_ACTOR=[CANARY],REF=['refs/heads/other'],ATTEMPT=['2'],HOST_FINGERPRINT=['','SHA256:'+'a'*42,CANARY]).items():
            for v in values:
                result=self.gate(**{key:v});self.assertNotEqual(result.returncode,0);self.assertNotIn(CANARY.encode(),result.stdout+result.stderr)
        header=self.text.split('\npermissions:',1)[0]
        self.assertEqual(re.findall(r'^  ([a-z_]+):',header,re.M),['workflow_dispatch'])
        self.assertNotIn('inputs:',self.text)
        self.assertIn('contents: read',self.text);self.assertNotIn('contents: write',self.text)
        self.assertIn('group: deploy-logic-analysis\n  cancel-in-progress: false',self.text)

    def test_single_hash_bound_public_helper_and_no_data_transport(self):
        self.assertEqual(re.findall(r'^          source: (.+)$',self.text,re.M),['backup-status-ship/backup_status.py'])
        self.assertIn('persist-credentials: false',self.text);self.assertIn('overwrite: false',self.text)
        self.assertNotRegex(self.text,r'upload-artifact|docker\s+(run|exec|stop|rm|prune)|rsync|sqlite3|\.env')
        self.assertLess(self.text.index('unittest discover'),self.text.index('uses: appleboy/'))
        execute=self.invoke.index('out=$(python3')
        for part in ('[ ! -L "$incoming" ]','[ ! -L "$helper" ]','0:700','0:1:644','"$(sha256sum "$helper" | cut -d\' \' -f1)" = "$NBS_SHA"'):
            self.assertLess(self.invoke.index(part),execute)
        self.assertIn('out=$(python3 -I -B "$helper" 2>/dev/null)',self.invoke)
        self.assertIn('command_timeout: 5m',self.text)
        self.assertEqual(self.text.count('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}'),4)
        for action in re.findall(r'uses: ([^\n]+)',self.text):self.assertRegex(action,r'@[0-9a-f]{40}\Z')

    def validate_output(self,raw,rc='2',good_hash=True,same_file=True):
        with tempfile.TemporaryDirectory()as directory:
            p=Path(directory)/'helper.py';p.write_bytes((ROOT/'deploy/naver/backup_status.py').read_bytes())
            digest=hashlib.sha256(p.read_bytes()).hexdigest()if good_hash else '0'*64
            fstat=os.fstat;calls=0
            def normalized(fd):
                nonlocal calls
                calls+=1;s=fstat(fd);v={k:getattr(s,k)for k in ('st_mode','st_nlink','st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')}
                if not same_file and calls>1:v['st_mtime_ns']+=1
                return SimpleNamespace(st_uid=0,**v)
            with patch.object(sys,'argv',['-c',str(p),digest,rc]),patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(raw))),patch.object(os,'fstat',side_effect=normalized),contextlib.redirect_stdout(io.StringIO())as out:
                try:exec(compile(self.validator,'workflow-validator','exec'),{});accepted=True
                except Exception:accepted=False
            self.assertEqual(out.getvalue(),'');return accepted

    def test_actual_closed_validator_hash_identity_exit_status_and_raw_canary(self):
        v=B.receipt();raw=json.dumps(v).encode()
        self.assertTrue(self.validate_output(raw));self.assertFalse(self.validate_output(raw,'0'))
        self.assertFalse(self.validate_output(raw,good_hash=False));self.assertFalse(self.validate_output(raw,same_file=False))
        for raw in (CANARY.encode(),b'',json.dumps(dict(v,extra=CANARY)).encode(),json.dumps(v).encode()+b'\n',b' '*32769):
            self.assertFalse(self.validate_output(raw))
        self.assertLess(self.invoke.index('ns["validate_report"](value)'),self.invoke.index("printf 'NAVER_BACKUP_STATUS_RESULT="))
        self.assertEqual(self.invoke.count("printf 'NAVER_BACKUP_STATUS_RESULT="),1)

    def test_versioned_metadata_validator_preserves_unknown_archive_and_rejects_leaks(self):
        with tempfile.TemporaryDirectory(prefix='nbmeta-',dir=Path.home()) as directory:
            root=Path(directory);root.chmod(0o700)
            (root/'local').mkdir(mode=0o700)
            building=root/'local'/'.building-abc123__';building.mkdir(mode=0o700)
            (building/'snapshot.sqlite').write_bytes(CANARY.encode())
            with patch.multiple(B,BACKUP_ROOT=str(root),ENGINE_UID=os.getuid()):
                local=B.summarize_folder('local','zip')
            self.assertEqual(local['reason'],'UNEXPECTED_ENTRY')
            self.assertIsNone(local['logical_bytes'])
            self.assertEqual(local['metadata']['status'],'observed')
            v=B.receipt();v['local']=local
            raw=json.dumps(v).encode()
            self.assertLess(len(raw),32768);self.assertNotIn(CANARY.encode(),raw)
            self.assertTrue(self.validate_output(raw))
            self.assertEqual(v['version'],2);self.assertEqual(v['scope'],'naver-backup-status-v2')
            v['version']=1
            self.assertFalse(self.validate_output(json.dumps(v).encode()))
            v['version']=2;v['local']['metadata']['raw_name']=CANARY
            self.assertFalse(self.validate_output(json.dumps(v).encode()))
        self.assertIn("-p 'test_backup_*.py'",self.text)

    def test_cleanup_only_temporary_helper_and_empty_directory(self):
        clean=self.blocks[-1]
        self.assertNotIn('/var/backups',self.text);self.assertNotRegex(self.text,r'rm\s+-rf')
        self.assertIn('rm -f -- "$helper"',clean);self.assertIn('rmdir -- "$incoming"',clean)
        self.assertIn('0:700',clean);self.assertIn('0:1:644',clean)
        self.assertIn("if: always() && steps.prepare_remote.outcome == 'success'",self.text)

    def test_each_shell_block_parses_and_change_does_not_trigger_app_deployment(self):
        self.assertEqual(len(self.blocks),5)
        for script in self.blocks:
            result=subprocess.run(['/bin/bash','-n'],input=script,text=True,capture_output=True,timeout=3)
            self.assertEqual(result.returncode,0,result.stderr)
        deploy=(ROOT/'.github/workflows/deploy.yml').read_text().split('workflow_dispatch:',1)[0]
        self.assertIn("      - '.github/workflows/naver-backup-status.yml'",deploy)
        checks=(ROOT/'.github/workflows/naver-tools-check.yml').read_text()
        self.assertIn("'.github/workflows/naver-backup-status.yml'",checks.split('  push:',1)[0])


if __name__=='__main__':unittest.main()
