"""Exact qualification adapter. CLI may use bounded read-only Actions API.
No deployment or operating call. Script construction follows all three gates.
All dependency/code reads use fixed checkout paths and verified byte buffers.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import types

BASE = "backend/tools/naver_market_diagnostic_transition/"
DEPENDENCY_PINS = {'fixed_actions_api': 'fa5b25f8a64ad98b1bad2f9008003654eef98f03976c7c4992a0be3909f4befc',
 'native_contract': '7c157b45c150f3597e9e126b0d6a2348d9fb90421976c534591426d268f2303a',
 'portable_ci': '476100202174cba63358fee0f15ff3fce42657d80255d7177f99693a4e59fd0c',
 'portable_contract': 'c38c07520c81ef443a0875ac36e8feb26f9b3265499309401655dd40464653cb',
 'workflow_delivery': 'ffe5e94bd54e2beb3c0d6855cc2048a6cef3e7a7070c6c2da8f80888b9c03e81'}
SOURCE_REGISTRY = {'bootstrap': {'bytes': 3974,
               'path': 'backend/tools/naver_market_diagnostic_transition/bootstrap.py',
               'sha256': 'c7031553808146394ccc899a67e8ef76fbae7946ff4a389f874d0c041feb098c'},
 'current_guard': {'bytes': 10836,
                   'path': 'backend/tools/naver_market_diagnostic_transition/current_guard.py',
                   'sha256': '6a9377b6ed3d511e054c1234b0b830314331ddadad3b5887b79a8c36e611e5d8'},
 'delivery': {'bytes': 8446,
              'path': 'backend/tools/naver_market_diagnostic_transition/delivery.py',
              'sha256': '3026d83baa140cd45b0e9361c40a50274fd41bd914885aa46011f904a99b7bcc'},
 'diagnostic_exporter': {'bytes': 19540,
                         'path': 'backend/tools/naver_market_diagnostic_transition/diagnostic_market_export.py',
                         'sha256': '9bb25d4acda4edca44aa71c238a6bf53be7dab5e093bc4f0c69d45c0d0891851'},
 'diagnostic_failure_consumer': {'bytes': 23009,
                                 'path': 'backend/tools/naver_market_diagnostic_transition/diagnostic_failure_consumer.py',
                                 'sha256': '8011a44a6f7965e1dfc9b0c17cfeb766dca0c31107494da1bcfc862d1b8598d8'},
 'diagnostic_product_sibling': {'bytes': 20647,
                                'path': 'backend/tools/naver_market_diagnostic_transition/naver_product_export.py',
                                'sha256': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59'},
 'entrypoint': {'bytes': 4181,
                'path': 'backend/tools/naver_market_diagnostic_transition/entrypoint.py',
                'sha256': 'b24302665afb5623b8c466f563b3c50c236dfbbabcebc6a3be3519d77df7c162'},
 'exports_binding': {'bytes': 10121,
                     'path': 'backend/tools/naver_completion_exports.py',
                     'sha256': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed'},
 'exports_helper': {'bytes': 37216,
                    'path': 'backend/tools/naver_saved_exports.py',
                    'sha256': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737'},
 'host_port': {'bytes': 7744,
               'path': 'backend/tools/naver_market_diagnostic_transition/host_port.py',
               'sha256': 'f4ed31a5e40db1593358295d30119b95e5ce2d8b3bc3cc97680f94e724562500'},
 'journal': {'bytes': 11244,
             'path': 'backend/tools/naver_market_diagnostic_transition/journal.py',
             'sha256': '27e2ec8c7b332951151dcb19bd60ec527eb768d1b1711f40069b8dd1ac191333'},
 'market_exporter': {'bytes': 17992,
                     'path': 'backend/naver_market_export.py',
                     'sha256': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'},
 'preflight': {'bytes': 11165,
               'path': 'backend/tools/naver_market_diagnostic_transition/preflight.py',
               'sha256': '0a48d024d352bb2d32cfa920ee530501001bb889d32219ff8b14dcca0984b7c3'},
 'product_exporter': {'bytes': 20647,
                      'path': 'backend/naver_product_export.py',
                      'sha256': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59'},
 'provisioning': {'bytes': 10009,
                  'path': 'backend/tools/naver_market_diagnostic_transition/provisioning.py',
                  'sha256': '651927b4a93bc68f57dfac3645bd9a2c4fbdf4a0f0ec32beef94389e40a19ad0'},
 'publication': {'bytes': 11483,
                 'path': 'backend/tools/naver_market_diagnostic_transition/publication.py',
                 'sha256': 'da60c15bca0dc48c9dda794ade7e87877f5fec13678a908a3f58657bb34be8a1'},
 'strict_receiver': {'bytes': 13955,
                     'path': 'backend/tools/naver_market_diagnostic_transition/strict_receiver.py',
                     'sha256': '30ed12d72c185df61a69494d7368b1f80030c53a6958ed213b067d99653d29c7'},
 'systemd_boundary': {'bytes': 15655,
                      'path': 'backend/tools/naver_market_diagnostic_transition/systemd_boundary.py',
                      'sha256': 'a0559bdca3bee319a8bc3d37425a6854185ec06245b69ec494a4513221fe72ac'},
 'transition': {'bytes': 16085,
                'path': 'backend/tools/naver_market_diagnostic_transition/transition.py',
                'sha256': '89ab4f61004846a90ec75a147b398d5f17eae016a268e375e7c44433143c3a92'}}
DEPENDENCY_ORDER = ('native_contract','workflow_delivery','portable_contract','portable_ci','fixed_actions_api')
NATIVE_WORKFLOW_SHA256 = 'd6f504478e5141d7861a278013fd26f99a73347f26a829dcbc7568f41fc40289'
PORTABLE_WORKFLOW_SHA256 = 'd6fff09eec44a1174346825e7b922d6ed5d5b68823549f623976a3877bf05a1c'
LINUX_MANIFEST_SHA256 = 'de94b30c23e97e6f8b047e01b6a7d0dd78c0fc93aff1e82efe74c06e8175b96b'
# Registered exact completed 17-check Linux result; future runs are not evidence.
LINUX_QUALIFICATION_SHA256 = '08a199f9eb53bad06223e594f2de794b5b858f021afa5c5d3a5ffc66647db5cf'
MAX_FILE = 131072
MAX_REGISTRY = 32768


class Refused(ValueError):
    pass


def need(value, code):
    if value is not True: raise Refused(code)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    try: return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    except (TypeError,ValueError,RecursionError): raise Refused('CLOSED_JSON') from None


def exact(actual, expected):
    if type(actual) is not type(expected): return False
    if type(expected) is dict:
        return actual.keys()==expected.keys() and all(exact(actual[k],v) for k,v in expected.items())
    if type(expected) is list:
        return len(actual)==len(expected) and all(exact(a,b) for a,b in zip(actual,expected))
    return actual==expected


def digest(value, length=64):
    return type(value) is str and re.fullmatch('[0-9a-f]{'+str(length)+'}',value) is not None and value!='0'*length


def positive(value):
    return type(value) is int and 0<value<2**63


def read_fixed(root, relative, pin=None, maximum=MAX_FILE):
    """One verified buffer; no source re-read between hash and compilation."""
    root=Path(root).absolute(); path=root
    need(type(relative) is str and not Path(relative).is_absolute(),'SOURCE_PATH')
    for part in Path(relative).parts:
        need(part not in ('.','..'),'SOURCE_PATH');path=path/part
        need(not path.is_symlink(),'SOURCE_PATH')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<before.st_size<=maximum,'SOURCE_FILE')
        chunks=[];remaining=maximum+1
        while remaining:
            block=os.read(fd,min(65536,remaining))
            if not block:break
            chunks.append(block);remaining-=len(block)
        body=b''.join(chunks);after=os.fstat(fd);named=path.stat(follow_symlinks=False)
        key=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
        need(key(before)==key(after)==key(named) and len(body)==before.st_size,'SOURCE_CHANGED')
    finally:os.close(fd)
    if pin is not None:need(digest(pin) and sha(body)==pin,'SOURCE_PIN')
    return body


@contextlib.contextmanager
def dependencies(root):
    need(not any(name in sys.modules for name in DEPENDENCY_ORDER),'DEPENDENCY_COLLISION')
    loaded={}
    try:
        # Verify all dependency byte buffers before executing the first.
        buffers={n:read_fixed(root,BASE+'qualification_deps/'+('workflow_delivery_completed.py' if n=='workflow_delivery' else n+'.py'),DEPENDENCY_PINS[n]) for n in DEPENDENCY_ORDER}
        for name in DEPENDENCY_ORDER:
            module=types.ModuleType(name);sys.modules[name]=module;loaded[name]=module
            exec(compile(buffers[name],'<exact-qualification-'+name+'>','exec'),module.__dict__)
        yield loaded
    finally:
        for name,module in loaded.items():
            if sys.modules.get(name) is module:del sys.modules[name]


def ids(value):
    need(type(value) is dict and set(value)=={'native_run_id','portable_run_id','linux_run_id'},'INPUT_IDS')
    result={}
    for key,item in value.items():
        need(type(item) is str and re.fullmatch('[1-9][0-9]{0,18}',item) is not None,'INPUT_IDS')
        number=int(item);need(positive(number),'INPUT_IDS');result[key]=number
    need(len(set(result.values()))==3,'INPUT_IDS')
    return result


def linux_registration(root, G):
    need(digest(LINUX_QUALIFICATION_SHA256),'LINUX_QUALIFICATION_UNREGISTERED')
    source=G.strict(read_fixed(root,BASE+'qualification_deps/linux-source-manifest.closed.json',LINUX_MANIFEST_SHA256),16384)
    registered=G.strict(read_fixed(root,BASE+'qualification_deps/linux-qualified.closed.json',LINUX_QUALIFICATION_SHA256),4096)
    need(type(registered) is dict and set(registered)=={'schema','head_sha','run_id','source_manifest_sha256','strict_result_sha256','full_linux_checks','qualified'},'LINUX_REGISTRATION')
    want=dict(schema='registered-full-linux-v1',head_sha=source['head_sha'],run_id=source['run_id'],
        source_manifest_sha256=LINUX_MANIFEST_SHA256,strict_result_sha256=registered['strict_result_sha256'],
        full_linux_checks=len(G.LINUX_CHECKS),qualified=True)
    need(exact(registered,want) and digest(registered['head_sha'],40)
        and digest(registered['strict_result_sha256']) and positive(registered['run_id']),'LINUX_REGISTRATION')
    need(set(source['runtime'])==set(G.MODULE_PINS),'LINUX_RUNTIME_MANIFEST')
    for role,entry in source['runtime'].items():
        need(exact(entry,SOURCE_REGISTRY[role]),'LINUX_RUNTIME_MANIFEST')
    mapping={'helper':'exports_helper','product':'product_exporter','old_market':'market_exporter','market':'diagnostic_exporter'}
    need(set(source['compiler_sources'])==set(mapping),'LINUX_SOURCE_MANIFEST')
    for role,local in mapping.items():
        entry=source['compiler_sources'][role];target=SOURCE_REGISTRY[local]
        # The Linux fixture names diagnostic_market differently, but pins the same byte buffer.
        expected=dict(target)
        if role=='market':expected['path']=BASE+'naver_market_export_diagnostic.py'
        need(exact(entry,expected),'LINUX_SOURCE_MANIFEST')
    need(source['exports_binding_executed_in_linux'] is False,'LINUX_SOURCE_MANIFEST')
    need(source['workflow']['path']==G.LINUX_WORKFLOW
        and source['workflow']['sha256']=='ac7fb2ef78baf6b62f3f7d1f487839ca719fb80f1c3d6623c837d1b2f5dcf601','LINUX_WORKFLOW')
    return registered,source


def sources(root, G, C):
    need(len(SOURCE_REGISTRY)==19,'SOURCE_REGISTRATION')
    expected={v['path']:{'sha256':v['sha256'],'bytes':v['bytes']} for v in SOURCE_REGISTRY.values()}
    need(exact(expected,C.SOURCE_FILES),'PORTABLE_SOURCE_REGISTRATION')
    values={k:read_fixed(root,v['path'],v['sha256'],v['bytes']) for k,v in SOURCE_REGISTRY.items()}
    for key,value in values.items():need(len(value)==SOURCE_REGISTRY[key]['bytes'],'SOURCE_SIZE')
    modules={k:values[k] for k in G.MODULE_PINS};public={k:values[k] for k in G.SOURCE_PINS}
    need({k:sha(v) for k,v in modules.items()}==G.MODULE_PINS,'MODULE_REGISTRATION')
    need({k:sha(v) for k,v in public.items()}==G.SOURCE_PINS,'PUBLIC_REGISTRATION')
    tools={k:values[k] for k in ('delivery','bootstrap','strict_receiver')}
    workflows={
        'native':read_fixed(root,G.NATIVE_WORKFLOW,NATIVE_WORKFLOW_SHA256),
        'portable':read_fixed(root,C.WORKFLOW,PORTABLE_WORKFLOW_SHA256),
        'production':read_fixed(root,G.WORKFLOW),
    }
    # This digest is an outward registry binding, not a reverse workflow pin.
    self_bytes=read_fixed(root,BASE+'qualification.py')
    receiver_bytes=read_fixed(root,BASE+'result_receiver.py')
    registration=dict(source_files=SOURCE_REGISTRY,dependencies=DEPENDENCY_PINS,
        qualification_sha256=sha(self_bytes),result_receiver_sha256=sha(receiver_bytes),
        workflows={k:sha(v) for k,v in workflows.items()},
        pair=list(G.PAIR),pair_receipt_sha256=G.PAIR_RECEIPT_SHA256)
    return modules,public,tools,registration


def collect_one(api, run_id, head, G, C, kind):
    run=api.run(run_id);jobs=api.jobs(run_id);artifacts=api.artifacts(run_id)
    need(type(jobs) is dict and set(jobs)=={'total_count','jobs'} and type(jobs['total_count']) is int
        and jobs['total_count']==1 and type(jobs['jobs']) is list and len(jobs['jobs'])==1,'QUALIFICATION_JOBS')
    need(type(artifacts) is dict and set(artifacts)=={'total_count','artifacts'} and type(artifacts['total_count']) is int
        and artifacts['total_count']==1 and type(artifacts['artifacts']) is list and len(artifacts['artifacts'])==1,'QUALIFICATION_ARTIFACTS')
    need(type(run) is dict and type(jobs['jobs'][0]) is dict and type(artifacts['artifacts'][0]) is dict,'QUALIFICATION_SHAPE')
    job,item=jobs['jobs'][0],artifacts['artifacts'][0]
    ref=dict(run_id=run_id,head_sha=head,workflow_id=run.get('workflow_id'),job_id=job.get('id'),
        artifact_id=item.get('id'),artifact_size=item.get('size_in_bytes'),artifact_digest=item.get('digest'))
    G.ref(ref)
    # Ref values are recorded from this exact run; never search newest green or an archive URL.
    choices={
        'native':(G.NATIVE_WORKFLOW,G.BRANCH,'synthetic-export','naver-product-export-tests-'+str(run_id)),
        'portable':(C.WORKFLOW,G.BRANCH,C.JOB,C.ARTIFACT),
        'linux':(G.LINUX_WORKFLOW,G.LINUX_BRANCH,'empty-linux-systemd','market-diagnostic-transition-linux-'+str(run_id)),
    }
    need(kind in choices,'QUALIFICATION_KIND');workflow,branch,job_name,artifact_name=choices[kind]
    expected=dict(id=run_id,head_sha=head,head_branch=branch,path=workflow,event='push',run_attempt=1,status='completed',conclusion='success')
    need(exact({k:run.get(k) for k in expected},expected) and type(run.get('repository')) is dict
        and run['repository'].get('full_name')==G.REPO,'QUALIFICATION_RUN')
    expected_job=dict(run_id=run_id,head_sha=head,name=job_name,run_attempt=1,status='completed',conclusion='success')
    need(exact({k:job.get(k) for k in expected_job},expected_job),'QUALIFICATION_JOB')
    need(item.get('name')==artifact_name and item.get('expired') is False and type(item.get('workflow_run')) is dict
        and exact({k:item['workflow_run'].get(k) for k in ('id','head_sha','head_branch')},
            dict(id=run_id,head_sha=head,head_branch=branch)),'QUALIFICATION_ARTIFACT')
    packed=api.artifact_zip(ref['artifact_id'])
    need(type(packed) is bytes and 0<len(packed)<G.MAX_ZIP and len(packed)==ref['artifact_size']
        and 'sha256:'+sha(packed)==ref['artifact_digest'],'QUALIFICATION_ARCHIVE')
    return ref,run,jobs['jobs'],artifacts['artifacts'],packed


def portable(actual,G,P,C):
    ref,run,jobs,artifacts,packed=actual;job,item=jobs[0],artifacts[0]
    expected=dict(id=ref['run_id'],head_sha=ref['head_sha'],head_branch=G.BRANCH,workflow_id=ref['workflow_id'],
        path=C.WORKFLOW,event='push',run_attempt=1,status='completed',conclusion='success')
    need(exact({k:run.get(k) for k in expected},expected),'PORTABLE_RUN')
    need(type(run.get('repository')) is dict and run['repository'].get('full_name')==G.REPO,'PORTABLE_RUN')
    need(type(job.get('run_attempt')) is int and job['run_attempt']==1,'PORTABLE_JOB')
    need(type(item.get('workflow_run')) is dict and item['workflow_run'].get('head_branch')==G.BRANCH,'PORTABLE_ARTIFACT')
    # Explicit raw API -> reviewed exact projection; no implicit dict/string coercion.
    projected_run={k:run[k] for k in ('id','head_sha','head_branch','event','status','conclusion','run_attempt','path')}
    projected_run['repository']=run['repository']['full_name']
    projected_job={k:job.get(k) for k in ('id','run_id','head_sha','name','status','conclusion')}
    raw_steps=job.get('steps');need(type(raw_steps) is list,'PORTABLE_STEPS')
    need(all(type(s) is dict for s in raw_steps),'PORTABLE_STEPS')
    numbers=[s.get('number') for s in raw_steps]
    need(all(type(n) is int and n>0 for n in numbers) and len(set(numbers))==len(numbers)
        and numbers==sorted(numbers),'PORTABLE_STEP_NUMBERS')
    # API post-step numbers may have gaps; preserve validated order, not numeric gaps.
    projected_job['steps']=[dict(number=i,**{k:s.get(k) for k in ('name','status','conclusion')})
        for i,s in enumerate(raw_steps,1)]
    projected_artifact={k:item.get(k) for k in ('id','name','expired','size_in_bytes')}
    projected_artifact['workflow_run']={k:item['workflow_run'].get(k) for k in ('id','head_sha')}
    result=P.verify(projected_run,[projected_job],[projected_artifact],packed,
        head=ref['head_sha'],run_id=ref['run_id'],artifact_id=ref['artifact_id'])
    return dict(ref=ref,artifact_sha256=sha(packed),closed=result)


def _qualify(root, head, run_ids, loaded):
    G=loaded['workflow_delivery'];P=loaded['portable_ci'];C=loaded['portable_contract'];A=loaded['fixed_actions_api']
    need(digest(head,40),'HEAD');numbers=ids(run_ids)
    registered,linux_manifest=linux_registration(root,G)
    need(numbers['linux_run_id']==registered['run_id'],'LINUX_RUN_REGISTRATION')
    modules,public,tools,source_registration=sources(root,G,C)
    native_actual=collect_one(A,numbers['native_run_id'],head,G,C,'native')
    native_result=G.native(*native_actual)
    portable_actual=collect_one(A,numbers['portable_run_id'],head,G,C,'portable')
    portable_result=portable(portable_actual,G,P,C)
    linux_actual=collect_one(A,numbers['linux_run_id'],registered['head_sha'],G,C,'linux')
    linux_result=G.linux(*linux_actual)
    registry=dict(schema='market-diagnostic-qualified-registry-v1',head_sha=head,
        source=source_registration,linux_registration=registered,
        linux_registration_sha256=LINUX_QUALIFICATION_SHA256,
        linux_source_manifest_sha256=LINUX_MANIFEST_SHA256,
        linux_equivalence=dict(runtime=linux_manifest['runtime'],compiler_sources=linux_manifest['compiler_sources'],
            exports_binding_executed_in_linux=False),
        evidence=dict(native=dict(ref=native_actual[0],result=native_result),portable=portable_result,
            linux=dict(ref=linux_actual[0],result=linux_result)))
    body=canonical(registry);need(0<len(body)<=MAX_REGISTRY,'REGISTRY_SIZE')
    return registry,modules,public,tools


def qualification_registry(root, head, run_ids):
    """Controller and workflow use the same live API gates and canonical digest."""
    with dependencies(root) as loaded:
        registry,_,_,_=_qualify(root,head,run_ids,loaded)
        return dict(registry=registry,registry_sha256=sha(canonical(registry)))


def construct(confirm, modules, public, tools, G):
    """Called only after _qualify and exact registry equality; no host execution."""
    req=G.request(confirm);names=('delivery','bootstrap','strict_receiver')
    need(not any(n in sys.modules for n in names),'TOOL_COLLISION');loaded={}
    try:
        for name in names:
            need(sha(tools[name])==SOURCE_REGISTRY[name]['sha256'],'TOOL_PIN')
            m=types.ModuleType(name);sys.modules[name]=m;loaded[name]=m
            exec(compile(tools[name],'<exact-qualified-'+name+'>','exec'),m.__dict__)
        D,B,R=(loaded[n] for n in names)
        release=R.register_release(delivery_source=tools['delivery'],renderer_source=tools['bootstrap'],modules=modules,sources=public)
        wire=D.encode(modules,public,tools['delivery'],req);boot,script=B.render(wire,tools['delivery'],modules)
        sizes=dict(wire=len(wire.encode()),package=len(D.canonical(D.decode(wire))),bootstrap=len(boot.encode()),script=len(script.encode()))
        need(all(type(n) is int and 0<n<=G.CAPS[k] for k,n in sizes.items()),'DELIVERY_CAP')
        return dict(script=script,script_sha256=sha(script.encode()),sizes=sizes,release=release)
    finally:
        for name,module in loaded.items():
            if sys.modules.get(name) is module:del sys.modules[name]


def build(root, value, context):
    need(type(value) is dict and set(value)=={'confirm','native_run_id','portable_run_id','linux_run_id','registry_sha256'},'INPUT_SHAPE')
    need(digest(value['registry_sha256']),'REGISTRY_INPUT')
    with dependencies(root) as loaded:
        G=loaded['workflow_delivery'];G.context(context);G.request(value['confirm'])
        run_ids={k:value[k] for k in ('native_run_id','portable_run_id','linux_run_id')}
        registry,modules,public,tools=_qualify(root,context['head_sha'],run_ids,loaded)
        result_sha=sha(canonical(registry));need(result_sha==value['registry_sha256'],'REGISTRY_MISMATCH')
        result=construct(value['confirm'],modules,public,tools,G)
        return dict(result,registry_sha256=result_sha,request_sha256=sha(canonical(G.request(value['confirm']))),
            gates=dict(NATIVE='PASS',PORTABLE='PASS',LINUX='PASS'))


def output_script(path, script):
    need(type(path) is str and Path(path).is_absolute() and type(script) is str
        and 0<len(script.encode())<=131072 and '\x00' not in script,'WORKFLOW_OUTPUT')
    delimiter='NAVER_DIAGNOSTIC_'+sha(script.encode())
    need(delimiter not in script.splitlines(),'WORKFLOW_OUTPUT')
    fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW)
    try:
        st=os.fstat(fd)
        need(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.geteuid(),'WORKFLOW_OUTPUT')
        body=('script<<'+delimiter+'\n'+script+'\n'+delimiter+'\n').encode();offset=0
        while offset<len(body):
            n=os.write(fd,body[offset:]);need(n>0,'WORKFLOW_OUTPUT');offset+=n
    finally:os.close(fd)


def main():
    need(sys.argv[1:] in (['registry'],['build']),'CLI')
    root=Path(__file__).absolute().parents[3]
    run_ids={k:os.environ.get('DIAG_'+k.upper(),'') for k in ('native_run_id','portable_run_id','linux_run_id')}
    if sys.argv[1]=='registry':
        result=qualification_registry(root,os.environ.get('GITHUB_SHA',''),run_ids)
        print(json.dumps(dict(NATIVE='PASS',PORTABLE='PASS',LINUX='PASS',registry_sha256=result['registry_sha256']),sort_keys=True))
    else:
        need(os.environ.get('GITHUB_ACTIONS')=='true','WORKFLOW_CONTEXT')
        value=dict(run_ids,confirm=os.environ.get('DIAG_CONFIRM',''),registry_sha256=os.environ.get('DIAG_REGISTRY_SHA256',''))
        context=dict(repository=os.environ.get('GITHUB_REPOSITORY',''),head_sha=os.environ.get('GITHUB_SHA',''),
            ref=os.environ.get('GITHUB_REF',''),event=os.environ.get('GITHUB_EVENT_NAME',''),run_attempt=1 if os.environ.get('GITHUB_RUN_ATTEMPT')=='1' else None)
        result=build(root,value,context)
        output_script(os.environ.get('GITHUB_OUTPUT',''),result['script'])
        print('NAVER_MARKET_DIAGNOSTIC_QUALIFICATION_V1='+canonical(dict(result['gates'],
            registry_sha256=result['registry_sha256'],request_sha256=result['request_sha256'])).decode())


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('QUALIFICATION_REFUSED') from None

