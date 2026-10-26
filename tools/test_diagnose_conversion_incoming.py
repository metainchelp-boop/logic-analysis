import ast
from pathlib import Path
import unittest
import diagnose_conversion_incoming as diagnostic


class ReadonlyProbe(unittest.TestCase):
    def test_probe_has_no_mutating_controller_calls(self):
        source=diagnostic.SCRIPT.split("<<'PYCODE'\n",1)[1].rsplit('PYCODE',1)[0]
        tree=ast.parse(source)
        calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        self.assertFalse(calls & {'execute','prepare','apply','rollback','trusted_dir','mkdir','chmod','chown','open','write_bytes','write_text','unlink','remove','rmdir'})
        self.assertIn('baseline',calls);self.assertIn('run',calls)
        self.assertIn("stage='components'",source)
        self.assertIn("hexdigest()!=actual",source)

    def test_foreign_context_and_retry_refused(self):
        head='a'*40;env=dict(GITHUB_REPOSITORY='metainchelp-boop/logic-analysis',GITHUB_REF=diagnostic.REF,GITHUB_EVENT_NAME='push',GITHUB_RUN_ATTEMPT='1',GITHUB_ACTOR='metainchelp-boop',GITHUB_SHA=head)
        event=dict(after=head,ref=diagnostic.REF,forced=False,deleted=False,repository=dict(full_name=env['GITHUB_REPOSITORY'],private=False))
        diagnostic.context(env,event,head)
        for key,value in [('GITHUB_RUN_ATTEMPT','2'),('GITHUB_REF','refs/heads/main'),('GITHUB_ACTOR','foreign'),('GITHUB_SHA','b'*40),('GITHUB_EVENT_NAME','pull_request')]:
            with self.subTest(key=key),self.assertRaises(ValueError):diagnostic.context(dict(env,**{key:value}),event,head)

    def test_workflow_runs_exact_probe(self):
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/naver-conversion-incoming-diagnostic.yml').read_text()
        script=workflow.split('          script: |\n',1)[1]
        self.assertEqual(script,''.join('            '+line if line.strip() else line for line in diagnostic.SCRIPT.splitlines(True)))
        self.assertEqual(workflow.count('uses: appleboy/ssh-action@029f5b4aeeeb58fdfe1410a5d17f967dacf36262'),1)
        self.assertNotIn('scp-action',workflow)


if __name__=='__main__':unittest.main()
