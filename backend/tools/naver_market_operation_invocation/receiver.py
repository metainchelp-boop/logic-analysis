"""Pinned read-only dispatch receiver. Raw job logs stay bounded in RAM."""
from datetime import datetime,timedelta
import re
import qualification as Q

MAX_LOG=524288
RESULT_MARKER=b'NAVER_MARKET_OPERATION_INVOCATION_V1='


def stamp(value):
 Q.need(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,7})?Z',value) is not None,'RESULT_TIME')
 try:return datetime.fromisoformat(value[:-1]+'+00:00')
 except ValueError:raise Q.Refused('RESULT_TIME') from None


def marker(raw,literal,step,D):
 Q.need(type(raw) is bytes and 0<len(raw)<=MAX_LOG,'RESULT_LOG_SIZE')
 start,end=stamp(step.get('started_at')),stamp(step.get('completed_at'))
 Q.need(start<=end,'RESULT_TIME');end+=timedelta(seconds=1)
 Q.need(literal in (RESULT_MARKER,Q.BUILD_MARKER.encode()),'RESULT_MARKER')
 found=[]
 pattern=rb'(\S+Z)\s+(?:out: )?'+re.escape(literal)+rb'(.*)'
 family=rb'^(?:\S+\s+)?(?:out: )?(NAVER_MARKET_OPERATION_INVOCATION_.*)'
 known=(RESULT_MARKER,Q.BUILD_MARKER.encode())
 for line in raw.splitlines():
  match=re.fullmatch(pattern,line)
  # Unknown family versions cannot hide beside a valid result. The other known
  # literal belongs to its own step and is checked by the other marker() call.
  family_match=re.search(family,line)
  if family_match:
   payload=family_match[1]
   Q.need(any(payload.startswith(k) for k in known),'RESULT_MARKER')
   if payload.startswith(literal):Q.need(match is not None,'RESULT_MARKER')
  if match is not None:
   try:at=stamp(match[1].decode('ascii'))
   except UnicodeError:raise Q.Refused('RESULT_TIME') from None
   Q.need(start<=at<end,'RESULT_TIME')
   found.append(D.strict(match[2]))
 Q.need(len(found)==1,'RESULT_MARKER_COUNT')
 return found[0]


def fixed_input(root,registry):
 bodies,source=Q.registration(root)
 Q.need(type(registry) is dict and set(registry)=={'schema','head_sha','pair','source','evidence'}
  and registry['schema']=='readonly-operation-invocation-qualified-v1' and Q.digest(registry['head_sha'],40)
  and registry['pair']==list(Q.PAIR) and Q.same(registry['source'],source),'REGISTRY')
 evidence=registry['evidence'];Q.need(type(evidence) is dict and set(evidence)=={'native','audit'},'REGISTRY')
 for kind in ('native','audit'):
  ref=evidence[kind]['ref'];Q.need(Q.positive(ref['run_id']) and Q.positive(ref['workflow_id']) and ref['head_sha']==registry['head_sha'],'REGISTRY')
 Q.need(evidence['native']['ref']['run_id']!=evidence['audit']['ref']['run_id'],'REGISTRY')
 D=Q.module(bodies['delivery.py'],'readonly_delivery')
 built=D.render(bodies['core.py'],Q.SOURCE_PINS['core.py'])
 return dict(schema='readonly-operation-invocation-fixed-input-v1',confirm=Q.CONFIRM,pair=list(Q.PAIR),
  registry_sha256=Q.sha(Q.canonical(registry)),head_sha=registry['head_sha'],
  native_run_id=evidence['native']['ref']['run_id'],audit_run_id=evidence['audit']['ref']['run_id'],
  workflow_id=evidence['audit']['ref']['workflow_id'],source=source,
  script_sha256=built['script_sha256'],sizes=built['sizes'])


def receive(root,registry,fixed,run_id):
 expected=fixed_input(root,registry);Q.need(Q.same(fixed,expected),'FIXED_INPUT')
 Q.need(Q.positive(run_id) and run_id not in (fixed['native_run_id'],fixed['audit_run_id']),'RESULT_RUN_ID')
 bodies,_=Q.registration(root);D=Q.module(bodies['delivery.py'],'readonly_delivery')
 core=D.load_core(bodies['core.py'],Q.SOURCE_PINS['core.py'])
 with Q.dependencies(root) as loaded:
  A,G,N=loaded['fixed_actions_api'],loaded['workflow_delivery'],loaded['native_contract']
  # Metadata freshness only; prior exact artifact gates are bound by build marker.
  native=Q.run_bound(A.run(fixed['native_run_id']),fixed['native_run_id'],fixed['head_sha'],Q.NATIVE_WORKFLOW,'push',registry['evidence']['native']['ref']['workflow_id'])
  native_jobs=A.jobs(fixed['native_run_id'])
  Q.need(type(native_jobs) is dict and set(native_jobs)=={'total_count','jobs'} and type(native_jobs['total_count']) is int and native_jobs['total_count']==1 and type(native_jobs['jobs']) is list and len(native_jobs['jobs'])==1,'NATIVE_JOB')
  job=native_jobs['jobs'][0];ref=registry['evidence']['native']['ref']
  want=dict(id=ref['job_id'],run_id=fixed['native_run_id'],head_sha=fixed['head_sha'],name='synthetic-export',run_attempt=1,status='completed',conclusion='success')
  Q.need(type(job) is dict and Q.same({k:job.get(k) for k in want},want),'NATIVE_JOB')
  rows=job.get('steps');Q.need(type(rows) is list and 0<len(rows)<=64 and all(type(s) is dict and s.get('conclusion')=='success' and s.get('status')=='completed' and Q.positive(s.get('number')) and type(s.get('name')) is str for s in rows),'NATIVE_STEPS')
  names=[s['name'] for s in rows];numbers=[s['number'] for s in rows]
  Q.need(len(names)==len(set(names)) and len(numbers)==len(set(numbers)) and numbers==sorted(numbers) and all(names.count(n)==1 for n in N.REQUIRED_STEPS),'NATIVE_STEPS')
  Q.run_bound(A.run(fixed['audit_run_id']),fixed['audit_run_id'],fixed['head_sha'],Q.WORKFLOW,'push',fixed['workflow_id'])
  run=Q.run_bound(A.run(run_id),run_id,fixed['head_sha'],Q.WORKFLOW,'workflow_dispatch',fixed['workflow_id'])
  job=Q.selected_job(A.jobs(run_id),run_id,fixed['head_sha'],'workflow_dispatch')
  selected=Q.steps(job,Q.DISPATCH_STEPS,docker=True)
  raw=A.job_log(job['id'])
  build=marker(raw,Q.BUILD_MARKER.encode(),selected[Q.DISPATCH_STEPS[2]],D)
  wanted=dict(native='PASS',audit='PASS',registry_sha256=fixed['registry_sha256'],core_sha256=Q.SOURCE_PINS['core.py'],script_sha256=fixed['script_sha256'])
  Q.need(Q.same(build,wanted),'BUILD_BINDING')
  value=D.result(marker(raw,RESULT_MARKER,selected[Q.DISPATCH_STEPS[3]],D),core)
 return dict(schema='readonly-operation-invocation-received-v1',head_sha=fixed['head_sha'],workflow_run_id=run_id,
  workflow_id=fixed['workflow_id'],native_run_id=fixed['native_run_id'],audit_run_id=fixed['audit_run_id'],
  pair=list(Q.PAIR),target=Q.TARGET_PROVENANCE,registry_sha256=fixed['registry_sha256'],source=fixed['source'],
  result=value,original_export_success_verified=False,cleanup_executed=False,
  operating_stage_inferred=False,product_deployed=False,ads_written=False)

if __name__=='__main__':raise SystemExit('PINNED_READONLY_RECEIVER_REQUIRED')
