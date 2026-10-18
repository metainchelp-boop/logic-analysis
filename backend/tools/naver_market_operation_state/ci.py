"""New audit-only CI; local run is never production qualification."""
import ast
import contextlib
import json
import os
from pathlib import Path
import sys
import types
import unittest
import qualification as Q

EVIDENCE='readonly-audit-evidence'

def execute(body,path,name,expected):
 # Only IDs declared in these exact source bytes may enter public CI evidence.
 report=dict(status='failed',phase='load',declared=0,discovered=0,executed=0,
  failures=0,errors=0,skipped=0,expected_failures=0,unexpected_successes=0,
  failed_ids=[],error_ids=[],skipped_ids=[],expected_failure_ids=[],unexpected_success_ids=[])
 module=types.ModuleType(name);module.__file__=str(path);sys.modules[name]=module
 try:
  tree=ast.parse(body)
  allowed={name+'.'+c.name+'.'+f.name for c in tree.body if isinstance(c,ast.ClassDef)
   for f in c.body if isinstance(f,ast.FunctionDef) and f.name.startswith('test_')}
  report['declared']=len(allowed)
  with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):
   exec(compile(body,str(path),'exec'),module.__dict__)
   suite=unittest.defaultTestLoader.loadTestsFromModule(module)
   def flatten(node):
    if isinstance(node,unittest.TestSuite):
     for child in node:yield from flatten(child)
    else:yield node
   tests=list(flatten(suite));ids=[test.id() for test in tests];report['discovered']=len(ids)
   report['phase']='registry'
   Q.need(len(ids)==len(set(ids))==expected and set(ids)==allowed,'AUDIT_TEST_IDS')
   result=unittest.TestResult();report['phase']='execute';suite.run(result)
  report['executed']=result.testsRun
  groups=(('failures','failed_ids',result.failures),('errors','error_ids',result.errors),
   ('skipped','skipped_ids',result.skipped),('expected_failures','expected_failure_ids',result.expectedFailures),
   ('unexpected_successes','unexpected_success_ids',[(t,None) for t in result.unexpectedSuccesses]))
  for count_key,ids_key,items in groups:
   report[count_key]=len(items);public=[]
   for test,_ in items:
    # A subTest parameter string is never public: bind it to its registered parent.
    original=getattr(test,'test_case',test);identifier=original.id()
    Q.need(identifier in allowed,'AUDIT_TEST_IDS');public.append(identifier)
   report[ids_key]=sorted(set(public))
  report['phase']='complete'
  if result.wasSuccessful() and result.testsRun==expected and all(report[k]==0 for k,_,_ in groups):report['status']='passed'
 except BaseException:
  # Import or runner failures disclose only the fixed stage and any closed counts.
  report['status']='failed'
 finally:
  if sys.modules.get(name) is module:del sys.modules[name]
 return report


def write_new(path,body):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
 try:
  # CI-only closed files remain readable by the non-root artifact uploader.
  os.fchmod(fd,0o644)
  offset=0
  while offset<len(body):
   size=os.write(fd,body[offset:]);Q.need(size>0,'CI_OUTPUT');offset+=size
 finally:os.close(fd)


def main():
 Q.need(len(sys.argv)==2 and sys.argv[1] in ('tests','fixture'),'CI_ARGS')
 mode=sys.argv[1];root=Path(__file__).absolute().parents[3]
 Q.need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted'
  and os.environ.get('RUNNER_OS')=='Linux' and os.environ.get('GITHUB_EVENT_NAME')=='push'
  and os.environ.get('GITHUB_REPOSITORY')==Q.REPO and os.environ.get('GITHUB_REF')=='refs/heads/'+Q.BRANCH
  and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','CI_CONTEXT')
 head=os.environ.get('GITHUB_SHA');Q.need(Q.digest(head,40),'CI_SOURCE')
 bodies,source=Q.registration(root);folder=root/EVIDENCE
 if mode=='tests':
  folder.mkdir(mode=0o700)
  counts={};reports={}
  for name,expected in (('test_core.py',Q.CORE_TEST_COUNT),('test_delivery.py',Q.DELIVERY_TEST_COUNT)):
   report=execute(bodies[name],root/Q.BASE/name,'readonly_ci_'+name[:-3],expected)
   reports[name]=report;counts[name]=report['executed']
  if not all(r['status']=='passed' for r in reports.values()):
   failure=dict(schema='readonly-operation-state-qualification-v1',status='failed',phase='tests',
    source_manifest_sha256=Q.sha(Q.canonical(source)),tests=reports,
    operating_host_access=False,production_state_observed=False)
   write_new(folder/'source-sha.txt',(head+'\n').encode('ascii'))
   write_new(folder/'source-manifest.closed.json',Q.canonical(source))
   write_new(folder/'audit.closed.json',Q.canonical(failure))
   raise Q.Refused('AUDIT_TEST_FAILURE')
  value=dict(schema='readonly-operation-state-tests-v1',status='passed',core_tests=counts['test_core.py'],
   delivery_tests=counts['test_delivery.py'],source_manifest_sha256=Q.sha(Q.canonical(source)))
  write_new(folder/'tests.closed.json',Q.canonical(value))
 else:
  Q.need(folder.is_dir() and not folder.is_symlink(),'CI_OUTPUT')
  with Q.dependencies(root) as loaded:
   tests=loaded['workflow_delivery'].strict(Q.read(root,EVIDENCE+'/tests.closed.json',maximum=4096),4096)
  expected=dict(schema='readonly-operation-state-tests-v1',status='passed',core_tests=Q.CORE_TEST_COUNT,
   delivery_tests=Q.DELIVERY_TEST_COUNT,source_manifest_sha256=Q.sha(Q.canonical(source)))
  Q.need(Q.same(tests,expected),'CI_TEST_RECEIPT')
  fixture=Q.module(bodies['linux_fixture.py'],'readonly_linux_fixture')
  fixture.__file__=str(root/Q.BASE/'linux_fixture.py')
  previous=list(sys.argv)
  try:
   sys.argv=[fixture.__file__,'--confirm','github-hosted-empty-operation-state-v1']
   observed=fixture.run()
  finally:sys.argv=previous
  # Preserve the closed failed fixture too; never manufacture success or retry it.
  value=dict(schema='readonly-operation-state-qualification-v1',status='passed' if observed.get('status')=='passed' else 'failed',
   core_tests=Q.CORE_TEST_COUNT,delivery_tests=Q.DELIVERY_TEST_COUNT,source_manifest_sha256=Q.sha(Q.canonical(source)),
   fixture=observed,operating_host_access=False,production_state_observed=False)
  write_new(folder/'source-sha.txt',(head+'\n').encode('ascii'))
  write_new(folder/'source-manifest.closed.json',Q.canonical(source))
  write_new(folder/'audit.closed.json',Q.canonical(value))
  Q.fixture_result(observed)
 print('READONLY_AUDIT_CI_'+mode.upper()+'_PASS')

if __name__=='__main__':
 try:main()
 except BaseException:raise SystemExit('READONLY_AUDIT_CI_REFUSED') from None
