"""Read-only completed-dispatch adapter. Logs stay bounded in RAM.
Exact legacy timestamp/out marker grammar feeds the unchanged strict receiver.
This module has no SSH/service/DB operation and never writes raw job output.
"""
import contextlib
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import types
import qualification as Q

BUILD_MARKER=b'NAVER_MARKET_DIAGNOSTIC_QUALIFICATION_V1='
RESULT_MARKER=b'NAVER_MARKET_DIAGNOSTIC_TRANSITION_V1='
MAX_LOG=524288
BUILD_WRAPPER='Build appleboy/ssh-action@029f5b4aeeeb58fdfe1410a5d17f967dacf36262'
STEPS=('Checkout exact source','Python 3.12','Validate exact qualifications and build fixed script','Execute one fixed diagnostic action')


def stamp(text):
    Q.need(type(text) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,7})?Z',text) is not None,'RESULT_TIMESTAMP')
    try:return datetime.fromisoformat(text[:-1]+'+00:00')
    except ValueError:raise Q.Refused('RESULT_TIMESTAMP') from None


def marker(raw, literal, step, G):
    Q.need(type(raw) is bytes and 0<len(raw)<=MAX_LOG,'RESULT_LOG_SIZE')
    start,end=stamp(step.get('started_at')),stamp(step.get('completed_at'))
    Q.need(start<=end,'RESULT_STEP_TIME')
    # API completion timestamps have second precision. The inclusive API second
    # is allowed, not an arbitrary time window. Exact source emits each marker once.
    end=end+timedelta(seconds=1)
    pattern=rb'(\S+Z)\s+(?:out: )?'+re.escape(literal)+rb'(.*)'
    found=[]
    for line in raw.splitlines():
        match=re.fullmatch(pattern,line)
        if match:
            at=stamp(match[1].decode('ascii'));Q.need(start<=at<end,'RESULT_STEP_TIME')
            body=match[2];Q.need(0<len(body)<=4096,'RESULT_LINE_SIZE')
            value=G.strict(body,4096);Q.need(G.canonical(value)==body,'RESULT_CANONICAL');found.append(body)
    Q.need(len(found)==1,'RESULT_SINGLE_MARKER')
    return literal+found[0]+b'\n'


@contextlib.contextmanager
def receiver_modules(tools):
    names=('delivery','strict_receiver');Q.need(not any(n in sys.modules for n in names),'RESULT_MODULE_COLLISION');loaded={}
    try:
        for name in names:
            Q.need(Q.sha(tools[name])==Q.SOURCE_REGISTRY[name]['sha256'],'RESULT_SOURCE')
            module=types.ModuleType(name);sys.modules[name]=module;loaded[name]=module
            exec(compile(tools[name],'<fixed-result-'+name+'>','exec'),module.__dict__)
        yield loaded['strict_receiver']
    finally:
        for name,module in loaded.items():
            if sys.modules.get(name) is module:del sys.modules[name]


def expected(registry, workflow_id, G, *, run_id=None):
    ref=registry['evidence']['native']['ref'];Q.need(Q.positive(workflow_id),'RESULT_WORKFLOW_ID')
    result=dict(repository=G.REPO,ops_head=registry['head_sha'],native_run_id=ref['run_id'],native_attempt=1,
        native_workflow_id=ref['workflow_id'],native_workflow_path=G.NATIVE_WORKFLOW,native_event='push',
        workflow_id=workflow_id,workflow_path=G.WORKFLOW)
    if run_id is not None:
        Q.need(Q.positive(run_id) and run_id not in [registry['evidence'][k]['ref']['run_id'] for k in ('native','portable','linux')],'RESULT_RUN_ID')
        result.update(workflow_run_id=run_id,workflow_attempt=1)
    return result


def fixed_input(root, registry, confirm, workflow_id):
    """Caller retains this closed receipt before dispatch; no run is invented."""
    with Q.dependencies(root) as loaded:
        G,C=loaded['workflow_delivery'],loaded['portable_contract'];req=G.request(confirm)
        modules,public,tools,source=Q.sources(root,G,C)
        Q.need(Q.exact(source,registry['source']),'RESULT_SOURCE_REGISTRY')
        with receiver_modules(tools) as R:
            release=R.register_release(delivery_source=tools['delivery'],renderer_source=tools['bootstrap'],modules=modules,sources=public)
            receipt=R.fixed_input_receipt(registration=release,expected_request=req,expected=expected(registry,workflow_id,G))
        return dict(schema='fixed-qualified-dispatch-input-v1',registry_sha256=Q.sha(Q.canonical(registry)),
            confirm=confirm,request_sha256=Q.sha(Q.canonical(req)),receipt=receipt)


def receive(root, registry, fixed, dispatch_run_id):
    """Use exact API run/jobs and one bounded job log; never latest-success search."""
    with Q.dependencies(root) as loaded:
        G,C,A=loaded['workflow_delivery'],loaded['portable_contract'],loaded['fixed_actions_api']
        Q.need(type(fixed) is dict and set(fixed)=={'schema','registry_sha256','confirm','request_sha256','receipt'}
            and fixed['schema']=='fixed-qualified-dispatch-input-v1'
            and fixed['registry_sha256']==Q.sha(Q.canonical(registry)),'RESULT_FIXED_INPUT')
        req=G.request(fixed['confirm']);Q.need(fixed['request_sha256']==Q.sha(Q.canonical(req)),'RESULT_FIXED_INPUT')
        modules,public,tools,source=Q.sources(root,G,C);Q.need(Q.exact(source,registry['source']),'RESULT_SOURCE_REGISTRY')
        workflow_id=fixed['receipt']['inputs']['workflow_id'];exp=expected(registry,workflow_id,G,run_id=dispatch_run_id)
        run=A.run(dispatch_run_id);jobs=A.jobs(dispatch_run_id)
        wanted=dict(id=dispatch_run_id,head_sha=registry['head_sha'],head_branch=G.BRANCH,workflow_id=workflow_id,
            path=G.WORKFLOW,event='workflow_dispatch',run_attempt=1,status='completed',conclusion='success')
        Q.need(type(run) is dict and Q.exact({k:run.get(k) for k in wanted},wanted)
            and type(run.get('repository')) is dict and run['repository'].get('full_name')==G.REPO,'RESULT_RUN')
        Q.need(type(jobs) is dict and set(jobs)=={'total_count','jobs'} and type(jobs['total_count']) is int
            and jobs['total_count']==1 and type(jobs['jobs']) is list and len(jobs['jobs'])==1,'RESULT_JOBS')
        job=jobs['jobs'][0];wanted_job=dict(run_id=dispatch_run_id,head_sha=registry['head_sha'],run_attempt=1,
            name='qualified-one-shot',status='completed',conclusion='success')
        Q.need(type(job) is dict and Q.exact({k:job.get(k) for k in wanted_job},wanted_job) and Q.positive(job.get('id')),'RESULT_JOB')
        steps=job.get('steps');Q.need(type(steps) is list and len(steps)<=12,'RESULT_STEPS');selected={};numbers=[];build_seen=False
        for step in steps:
            Q.need(type(step) is dict and Q.positive(step.get('number')) and step.get('status')=='completed'
                and step.get('conclusion')=='success' and type(step.get('name')) is str,'RESULT_STEPS')
            numbers.append(step['number'])
            if step['name'] in STEPS:
                Q.need(step['name'] not in selected,'RESULT_STEPS');selected[step['name']]=step
            elif step['name']==BUILD_WRAPPER:
                Q.need(not build_seen and not selected,'RESULT_STEPS');build_seen=True
            else:Q.need(step['name'] in ('Set up job','Post Python 3.12','Post Checkout exact source','Complete job'),'RESULT_STEPS')
        Q.need(len(numbers)==len(set(numbers)) and numbers==sorted(numbers) and tuple(selected)==STEPS,'RESULT_STEPS')
        native=A.run(exp['native_run_id']);observed=[]
        for item in (native,run):
            Q.need(type(item) is dict and type(item.get('repository')) is dict,'RESULT_METADATA')
            projected={k:item.get(k) for k in ('id','run_attempt','head_sha','workflow_id','path','event','status','conclusion')}
            projected['repository']=item['repository'].get('full_name');observed.append(projected)
        with receiver_modules(tools) as R:
            release=R.register_release(delivery_source=tools['delivery'],renderer_source=tools['bootstrap'],modules=modules,sources=public)
            R.bind_execution(registration=release,expected_request=req,expected=exp,input_receipt=fixed['receipt'],
                observed_native=observed[0],observed_workflow=observed[1])
            raw=A.job_log(job['id'])
            build_line=marker(raw,BUILD_MARKER,selected[STEPS[2]],G)
            build_value=G.strict(build_line[len(BUILD_MARKER):],4096)
            Q.need(Q.exact(build_value,dict(NATIVE='PASS',PORTABLE='PASS',LINUX='PASS',
                registry_sha256=fixed['registry_sha256'],request_sha256=fixed['request_sha256'])),'RESULT_BUILD_BINDING')
            result_line=marker(raw,RESULT_MARKER,selected[STEPS[3]],G)
            return R.receive(result_line,registration=release,expected_request=req,expected=exp,input_receipt=fixed['receipt'],
                observed_native=observed[0],observed_workflow=observed[1])


def main():
    Q.need(sys.argv[1:]==['receive'],'RESULT_CLI')
    root=Path(__file__).absolute().parents[3]
    # Only bounded public controller receipts enter stdin. No logs or credentials.
    raw=sys.stdin.buffer.read(49153);Q.need(0<len(raw)<=49152,'RESULT_INPUT_SIZE')
    with Q.dependencies(root) as loaded:value=loaded['workflow_delivery'].strict(raw,49152)
    Q.need(type(value) is dict and set(value)=={'registry','fixed_input','dispatch_run_id'},'RESULT_INPUT')
    result=receive(root,value['registry'],value['fixed_input'],value['dispatch_run_id'])
    print(Q.canonical(result).decode())


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('RESULT_RECEIVER_REFUSED') from None
