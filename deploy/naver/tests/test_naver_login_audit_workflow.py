"""Manual-only transport guards, using local shell/synthetic output exclusively."""
import fnmatch
from pathlib import Path
import re
import subprocess
import unittest
from test_content_preflight_workflow import block, steps
from test_naver_login_audit_diagnostic import D, CANARY

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / '.github/workflows/naver-login-audit-diagnostic.yml'

class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=PATH.read_text();cls.parts=steps(cls.text);cls.guard=block(cls.parts[0],'run')
    def probe(self, **overrides):
        env=dict(ACTOR='metainchelp-boop',TRIGGERING_ACTOR='metainchelp-boop',REF='refs/heads/main',ATTEMPT='1',HOST_FINGERPRINT='SHA256:'+'a'*43)
        env.update(overrides)
        return subprocess.run(['/bin/bash','-c',self.guard],env=env,capture_output=True,text=True,timeout=3)
    def test_owner_rerun_main_and_host_guards(self):
        self.assertEqual(self.probe().returncode,0)
        for key,value in [('ACTOR',CANARY),('TRIGGERING_ACTOR',CANARY),('REF','refs/tags/main'),('HOST_FINGERPRINT',''),('HOST_FINGERPRINT','SHA256:'+'a'*43+'\n'+CANARY)]:
            result=self.probe(**{key:value});self.assertNotEqual(result.returncode,0);self.assertNotIn(CANARY,result.stdout+result.stderr)
    def test_only_first_attempt_is_accepted(self):
        for value in ('', '0', '2', '01', CANARY):
            result=self.probe(ATTEMPT=value)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn(CANARY,result.stdout+result.stderr)
    def test_only_manual_no_inputs_and_readonly_permission(self):
        header=self.text.split('\npermissions:',1)[0]
        self.assertEqual(re.findall(r'^  ([a-z_]+):',header,re.M),['workflow_dispatch'])
        self.assertNotIn('inputs:',self.text);self.assertIn('contents: read',self.text)
        self.assertIn('group: naver-login-audit-diagnostic\n  cancel-in-progress: false',self.text)
    def test_actions_pinned_and_local_checks_before_network(self):
        tests=next(i for i,p in enumerate(self.parts) if 'unittest discover' in p)
        remote=[i for i,p in enumerate(self.parts) if 'uses: appleboy/' in p]
        self.assertEqual(len(remote),4);self.assertTrue(all(i>tests for i in remote))
        self.assertIn('persist-credentials: false',self.text)
        self.assertTrue(all(re.fullmatch('[0-9a-f]{40}',x) for x in re.findall(r'uses: [^@\s]+@(\S+)',self.text)))
        for i in remote:self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}',self.parts[i])
    def test_public_file_only_uid_normalized_hash_bound_and_no_untrusted_argv(self):
        ship=next(p for p in self.parts if 'mkdir preflight-ship' in p)
        self.assertIn('sudo chown 0:0 preflight-ship/naver_login_audit_diagnostic.py',ship)
        self.assertIn('sudo chmod 644',ship)
        transfer=next(p for p in self.parts if 'uses: appleboy/scp-action@' in p)
        self.assertIn('source: preflight-ship/naver_login_audit_diagnostic.py',transfer)
        self.assertIn('overwrite: false',transfer)
        run=next(p for p in self.parts if 'NAVER_LOGIN_AUDIT_DIAGNOSTIC=%s' in p)
        self.assertIn('timeout -k 5s 70s python3 -I -B "$helper" 2>/dev/null',run)
        self.assertLess(run.index('sha256sum "$helper"'),run.index('timeout -k'))
        self.assertIn('envs: NSP_RUN,NSP_SHA',run)
        self.assertNotRegex(self.text,r'docker\s+(stop|rm|exec|build|run)|rm\s+-rf|rsync|sqlite3|\.env')
    def test_result_validated_before_print_and_bound_to_exit_code(self):
        run=next(p for p in self.parts if 'NAVER_LOGIN_AUDIT_DIAGNOSTIC=%s' in p)
        self.assertLess(run.index('ns["validate_report"](value)'),run.index("printf 'NAVER_LOGIN_AUDIT_DIAGNOSTIC="))
        self.assertIn('sys.stdin.buffer.read(32769)',run)
        self.assertIn('O_NOFOLLOW',run);self.assertIn('st_nlink==1',run)
        self.assertIn('hashlib.sha256(code).hexdigest()==expected',run)
        self.assertIn('rc=="0" and value["status"]=="observed"',run)
        self.assertIn('rc=="2" and value["status"]=="failed"',run)
        self.assertNotIn('"$out" "$helper"',run)
    def test_fixed_private_exclusive_temp_and_narrow_cleanup(self):
        prepare=next(p for p in self.parts if 'id: prepare_remote' in p)
        self.assertIn('umask 077',prepare);self.assertNotIn('mkdir -p',prepare)
        self.assertIn('mkdir "/tmp/metainc-naver-login-audit-$NSP_RUN"',prepare)
        for p in (next(p for p in self.parts if 'NAVER_LOGIN_AUDIT_DIAGNOSTIC=%s' in p),self.parts[-1]):
            self.assertIn('[ ! -L "$incoming" ]',p)
            self.assertIn('0:700',p);self.assertIn('0:1:644',p)
            self.assertIn('rm -f -- "$helper" 2>/dev/null',p);self.assertIn('rmdir -- "$incoming"',p)
        self.assertIn("if: always() && steps.prepare_remote.outcome == 'success'",self.parts[-1])
    def test_shell_blocks_parse(self):
        for part in self.parts:
            for key in ('run','script'):
                if re.search(r'^ +'+key+r': \|$',part,re.M):
                    result=subprocess.run(['/bin/bash','-n'],input=block(part,key),text=True,capture_output=True,timeout=3)
                    self.assertEqual(result.returncode,0,result.stderr)
    def test_deploy_excluded_and_pr_ci_paths_include_all(self):
        deploy=(ROOT/'.github/workflows/deploy.yml').read_text()
        ignored=re.findall(r"^      - '([^']+)'",deploy,re.M)
        for name in ['.github/workflows/naver-login-audit-diagnostic.yml','.github/workflows/deploy.yml','.github/workflows/naver-tools-check.yml','deploy/naver/naver_login_audit_diagnostic.py','deploy/naver/tests/test_naver_login_audit_diagnostic.py','deploy/naver/tests/test_naver_login_audit_workflow.py','deploy/naver/NAVER_LOGIN_AUDIT_DIAGNOSTIC.md']:
            self.assertTrue(any(fnmatch.fnmatchcase(name,p) for p in ignored),name)
        checks=(ROOT/'.github/workflows/naver-tools-check.yml').read_text().split('\n  push:',1)[0]
        self.assertIn("'.github/workflows/naver-login-audit-diagnostic.yml'",checks)
    def test_no_arbitrary_exception_string_in_closed_report(self):
        self.assertNotIn('root_required',D.ERRORS)
        self.assertIn('uid_required',D.ERRORS)
        value=D.empty_report();value['error']=CANARY
        with self.assertRaises(D.Refused):D.validate_report(value)

if __name__=='__main__':unittest.main()
