"""Offline delivery gates. No API, secret, filesystem, host or DB access.

Metadata arguments must come from a separately reviewed bounded API collector.
This draft has no collector and refuses production construction while any final
release contract is absent. The registry hash alone never authorizes a source.
"""
import hashlib
import io
import json
import re
import stat
import sys
import types
import zipfile
from native_contract import COUNTS, REQUIRED_STEPS

REPO = 'metainchelp-boop/logic-analysis'
BRANCH = 'codex/naver-claude-reference-ops-20261011'
LINUX_BRANCH = 'codex/naver-market-diagnostic-transition-linux-20261018'
WORKFLOW = '.github/workflows/naver-market-diagnostic-transition.yml'
NATIVE_WORKFLOW = '.github/workflows/naver-product-export-tests.yml'
LINUX_WORKFLOW = '.github/workflows/naver-market-transition-linux.yml'
PAIR = ('fe01f9ef77664899845a10f45b614a61', '89b2fcf8da264c16b3287b58d17735a1')
PAIR_RECEIPT_SHA256 = 'e3ef535c0c404755e3c2f8c69e81b8fc8f11a27228dd64e44e449ddf26b5c088'
CONFIRMS = {'APPLY_MARKET_DIAGNOSTIC_ONCE': 'apply',
            'ROLLBACK_MARKET_DIAGNOSTIC_PAIR': 'rollback'}
MAX_ZIP, MAX_MEMBER = 4*1024*1024, 2*1024*1024
MAX_REGISTRY = 32768
CAPS = {'wire': 102400, 'package': 393216, 'bootstrap': 32768, 'script': 131072}
MODULE_PINS = {'current_guard': '6a9377b6ed3d511e054c1234b0b830314331ddadad3b5887b79a8c36e611e5d8',
 'entrypoint': 'b24302665afb5623b8c466f563b3c50c236dfbbabcebc6a3be3519d77df7c162',
 'host_port': 'f4ed31a5e40db1593358295d30119b95e5ce2d8b3bc3cc97680f94e724562500',
 'journal': '27e2ec8c7b332951151dcb19bd60ec527eb768d1b1711f40069b8dd1ac191333',
 'preflight': '0a48d024d352bb2d32cfa920ee530501001bb889d32219ff8b14dcca0984b7c3',
 'provisioning': '651927b4a93bc68f57dfac3645bd9a2c4fbdf4a0f0ec32beef94389e40a19ad0',
 'publication': 'da60c15bca0dc48c9dda794ade7e87877f5fec13678a908a3f58657bb34be8a1',
 'systemd_boundary': 'a0559bdca3bee319a8bc3d37425a6854185ec06245b69ec494a4513221fe72ac',
 'transition': '89ab4f61004846a90ec75a147b398d5f17eae016a268e375e7c44433143c3a92'}
SOURCE_PINS = {
    'exports_binding': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed',
    'exports_helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737',
    'product_exporter': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59',
    'market_exporter': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8',
    'diagnostic_exporter': '9bb25d4acda4edca44aa71c238a6bf53be7dab5e093bc4f0c69d45c0d0891851',
}
# Exact final source/qualification registration is pending, not inferred from
# previous pins or expected future CI. Root must review changes before filling.
TOOL_PINS = dict(delivery=None, bootstrap=None, strict_receiver=None)
WORKFLOW_PINS = dict(native=None, linux=None)
PORTABLE_CONTRACT = None
LINUX_CHECKS = ('empty_host_gate',
 'exact_public_pins',
 'real_uid_gid',
 'unitpath_control_precedence',
 'persistent_natural_activation',
 'original_failure_bound',
 'compiled_unit_sandbox',
 'apply_source_limit_cell',
 'owned_runtime_masks',
 'paired_rollback',
 'partial_unit_publication_rollback',
 'cached_active_removal_refused',
 'original_files_and_db_preserved',
 'private_ids_not_emitted',
 'completed_invocation_retained',
 'completed_observation_not_export_success',
 'completed_pair_stopped_and_restored')


class Invalid(ValueError):
    pass


def fail(code):
    raise Invalid(code)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        fail('REGISTRY_JSON')


def sha(body):
    return hashlib.sha256(body).hexdigest()


def unique(pairs):
    value = {}
    for k, v in pairs:
        if k in value: fail('CLOSED_JSON')
        value[k] = v
    return value


def strict(body, maximum=MAX_REGISTRY):
    if type(body) is not bytes or not 0 < len(body) <= maximum: fail('CLOSED_SIZE')
    try:
        return json.loads(body, object_pairs_hook=unique,
            parse_constant=lambda _: fail('CLOSED_JSON'))
    except (ValueError, UnicodeError, RecursionError):
        fail('CLOSED_JSON')


def hex_value(value, size=64):
    return type(value) is str and re.fullmatch('[0-9a-f]{'+str(size)+'}', value) is not None and value != '0'*size


def positive(value):
    return type(value) is int and 0 < value < 2**63


def same(actual, expected):
    # Canonical comparison distinguishes JSON bool, int and float spellings.
    return canonical(actual) == canonical(expected)


def request(confirm):
    if type(confirm) is not str or confirm not in CONFIRMS: fail('DISPATCH_CONFIRM')
    return dict(version=1, action=CONFIRMS[confirm], apply_id=PAIR[0], rollback_id=PAIR[1])


def inputs(value):
    if type(value) is not dict or set(value) != {'confirm','native_run_id','linux_run_id','registry_sha256'}:
        fail('DISPATCH_INPUT')
    req = request(value['confirm'])
    for key in ('native_run_id','linux_run_id'):
        item = value[key]
        if type(item) is not str or re.fullmatch('[1-9][0-9]{0,18}',item) is None or not positive(int(item)):
            fail('DISPATCH_INPUT')
    if value['native_run_id'] == value['linux_run_id'] or not hex_value(value['registry_sha256']):
        fail('DISPATCH_INPUT')
    return req


def context(value):
    keys = {'repository','head_sha','ref','event','run_attempt'}
    if type(value) is not dict or set(value) != keys or not hex_value(value['head_sha'],40):
        fail('DISPATCH_CONTEXT')
    want = dict(repository=REPO,head_sha=value['head_sha'],ref='refs/heads/'+BRANCH,
                event='workflow_dispatch',run_attempt=1)
    if not same(value,want): fail('DISPATCH_CONTEXT')


def ref(value):
    keys = {'run_id','head_sha','workflow_id','job_id','artifact_id','artifact_size','artifact_digest'}
    if type(value) is not dict or set(value) != keys: fail('QUALIFICATION_REF')
    for key in ('run_id','workflow_id','job_id','artifact_id','artifact_size'):
        if not positive(value[key]): fail('QUALIFICATION_REF')
    if (not hex_value(value['head_sha'],40) or value['artifact_size'] >= MAX_ZIP
            or type(value['artifact_digest']) is not str
            or re.fullmatch('sha256:[0-9a-f]{64}',value['artifact_digest']) is None):
        fail('QUALIFICATION_REF')


def bind_metadata(expected, run, jobs, artifacts, *, workflow, branch, job_name, artifact_prefix, required_steps):
    """Verify actual API fields in RAM; never choose a latest green candidate."""
    ref(expected)
    want = dict(id=expected['run_id'],head_sha=expected['head_sha'],head_branch=branch,
        workflow_id=expected['workflow_id'],path=workflow,event='push',run_attempt=1,
        status='completed',conclusion='success')
    if type(run) is not dict or not same({k:run.get(k) for k in want},want): fail('QUALIFICATION_RUN')
    repository=run.get('repository')
    if type(repository) is not dict or repository.get('full_name') != REPO: fail('QUALIFICATION_RUN')
    if type(jobs) is not list or len(jobs)!=1 or type(jobs[0]) is not dict: fail('QUALIFICATION_JOB')
    job=jobs[0]; jw=dict(id=expected['job_id'],run_id=expected['run_id'],head_sha=expected['head_sha'],
        name=job_name,run_attempt=1,status='completed',conclusion='success')
    if not same({k:job.get(k) for k in jw},jw): fail('QUALIFICATION_JOB')
    steps=job.get('steps')
    if type(steps) is not list or not steps or len(steps)>64: fail('QUALIFICATION_STEPS')
    if any(type(s) is not dict or s.get('conclusion')!='success' or type(s.get('name')) is not str for s in steps):
        fail('QUALIFICATION_STEPS')
    names=[s['name'] for s in steps]
    if len(names)!=len(set(names)) or any(names.count(n)!=1 for n in required_steps): fail('QUALIFICATION_STEPS')
    if type(artifacts) is not list or len(artifacts)!=1 or type(artifacts[0]) is not dict: fail('QUALIFICATION_ARTIFACT')
    item=artifacts[0]; aw=dict(id=expected['artifact_id'],name=artifact_prefix+str(expected['run_id']),
        expired=False,size_in_bytes=expected['artifact_size'],digest=expected['artifact_digest'])
    if not same({k:item.get(k) for k in aw},aw): fail('QUALIFICATION_ARTIFACT')
    origin=item.get('workflow_run')
    ow=dict(id=expected['run_id'],head_sha=expected['head_sha'],head_branch=branch)
    if type(origin) is not dict or not same({k:origin.get(k) for k in ow},ow): fail('QUALIFICATION_ARTIFACT')
    return dict(run=want,job=jw,artifact=aw)


def unpack(packed, expected, names):
    ref(expected)
    if (type(packed) is not bytes or not 0<len(packed)<MAX_ZIP
            or len(packed)!=expected['artifact_size'] or 'sha256:'+sha(packed)!=expected['artifact_digest']):
        fail('QUALIFICATION_ARCHIVE')
    try:
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            entries=archive.infolist()
            if (len(entries)!=len(names) or {e.filename for e in entries}!=set(names)
                    or any(e.is_dir() or not 0<e.file_size<=MAX_MEMBER
                        or stat.S_IFMT(e.external_attr>>16) not in (0,stat.S_IFREG)
                        or e.flag_bits & 1 for e in entries)
                    or sum(e.file_size for e in entries)>=MAX_ZIP): fail('QUALIFICATION_MEMBERS')
            result={e.filename:archive.read(e) for e in entries}
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError,OSError):
        fail('QUALIFICATION_ARCHIVE')
    source=result['source-sha.txt']
    if len(source)>128 or source.strip()!=expected['head_sha'].encode(): fail('QUALIFICATION_SOURCE')
    return result


def native(expected, run, jobs, artifacts, packed):
    metadata=bind_metadata(expected,run,jobs,artifacts,workflow=NATIVE_WORKFLOW,branch=BRANCH,
        job_name='synthetic-export',artifact_prefix='naver-product-export-tests-',required_steps=REQUIRED_STEPS)
    members=unpack(packed,expected,set(COUNTS)|{'source-sha.txt'})
    if len(COUNTS)!=32 or len(members)!=33 or sum(COUNTS.values())!=1997: fail('NATIVE_CONTRACT')
    summaries={}
    for name,count in COUNTS.items():
        try:text=members[name].decode('utf-8')
        except UnicodeError:fail('NATIVE_SUITE')
        found=list(re.finditer(r'(?m)^Ran ([0-9]+) tests? in [^\r\n]+$',text))
        endings=list(re.finditer(r'(?m)^OK(?: \(skipped=(0)\))?\s*$',text))
        if (len(found)!=1 or len(endings)!=1 or found[0].end()>=endings[0].start()
                or int(found[0][1])!=count or re.search(r'(?m)^(FAILED|ERROR:|FAIL:)',text)):
            fail('NATIVE_SUITE')
        summaries[name]=dict(count=count,sha256=sha(members[name]))
    return dict(metadata=metadata,suites=summaries,total=1997,artifact_sha256=sha(packed))


def linux(expected, run, jobs, artifacts, packed):
    steps=('Checkout exact qualification commit','Qualify only a disposable empty hosted VM',
           'Retain only closed fixture result and source SHA')
    metadata=bind_metadata(expected,run,jobs,artifacts,workflow=LINUX_WORKFLOW,branch=LINUX_BRANCH,
        job_name='empty-linux-systemd',artifact_prefix='market-diagnostic-transition-linux-',required_steps=steps)
    members=unpack(packed,expected,{'source-sha.txt','result.closed.json'})
    value=strict(members['result.closed.json'],8192)
    wanted=dict(schema='diagnostic-empty-linux-vm-qualification-v1',status='passed',
        checks={k:True for k in LINUX_CHECKS},operating_host_access=False,
        production_receipt_verified=False,current_docker_verified=False,operating_SOURCE_LIMIT_cause_verified=False)
    if not same(value,wanted):fail('LINUX_CHECKS')
    return dict(metadata=metadata,result_sha256=sha(members['result.closed.json']),
                artifact_sha256=sha(packed),checks=dict(wanted['checks']))


def verify_sources(modules,sources,tools,workflows):
    for values,pins,maximum in ((modules,MODULE_PINS,32768),(sources,SOURCE_PINS,65536),
                               (tools,TOOL_PINS,32768)):
        if any(not hex_value(p) for p in pins.values()):fail('RELEASE_REGISTRATION_REQUIRED')
        if type(values) is not dict or set(values)!=set(pins):fail('RELEASE_SOURCE_SHAPE')
        for role,pin in pins.items():
            body=values[role]
            if type(body) is not bytes or not 0<len(body)<=maximum or sha(body)!=pin:fail('RELEASE_SOURCE_CHANGED')
    if any(not hex_value(p) for p in WORKFLOW_PINS.values()):fail('RELEASE_REGISTRATION_REQUIRED')
    if type(workflows) is not dict or set(workflows)!={'native','linux','production'}:
        fail('RELEASE_SOURCE_SHAPE')
    for role,body in workflows.items():
        if type(body) is not bytes or not 0<len(body)<=131072:fail('RELEASE_SOURCE_CHANGED')
        if role in WORKFLOW_PINS and sha(body)!=WORKFLOW_PINS[role]:fail('RELEASE_SOURCE_CHANGED')
    # Production workflow pins this runner; the reverse pin would be a cycle.
    # Its digest belongs only in the external reviewed canonical registry and
    # must bind exact checkout/API bytes at the actual dispatch head.
    return dict(modules=dict(MODULE_PINS),sources=dict(SOURCE_PINS),tools=dict(TOOL_PINS),
                workflows={k:sha(v) for k,v in workflows.items()})


def require_final_contract():
    if (PORTABLE_CONTRACT is None or any(not hex_value(p) for p in TOOL_PINS.values())
            or any(not hex_value(p) for p in WORKFLOW_PINS.values())):
        fail('RELEASE_REGISTRATION_REQUIRED')
    # Portable job/member/count and same-byte Linux manifest are not guessed.
    # Their concrete verifier must be reviewed before removing this refusal.
    fail('FINAL_QUALIFICATION_ADAPTER_REQUIRED')


def build_verified(*, confirm, modules, sources, tools, workflows, qualification):
    """Construction skeleton, unreachable before exact final qualification.

    No arbitrary callable/source paths accepted. Updated pinned delivery,
    renderer and receiver execute only after the final gate and full byte check.
    """
    req=request(confirm)
    require_final_contract()
    registration=verify_sources(modules,sources,tools,workflows)
    # Final qualification must bind the portable verifier, native()/linux()
    # results, workflow SHA and Linux source manifest. Not yet implemented.
    if qualification is None:fail('QUALIFICATION_REQUIRED')
    names=('delivery','bootstrap','strict_receiver')
    if any(n in sys.modules for n in names):fail('TOOL_MODULE_COLLISION')
    loaded={}
    try:
        for name in names:
            m=types.ModuleType(name);sys.modules[name]=m;loaded[name]=m
            exec(compile(tools[name],'<pinned-workflow-'+name+'>','exec'),m.__dict__)
        D,B,R=(loaded[n] for n in names)
        release=R.register_release(delivery_source=tools['delivery'],renderer_source=tools['bootstrap'],
            modules=modules,sources=sources)
        wire=D.encode(modules,sources,tools['delivery'],req)
        boot,script=B.render(wire,tools['delivery'],modules)
        measurements={'wire':len(wire.encode()),'package':len(D.canonical(D.decode(wire))),
                      'bootstrap':len(boot.encode()),'script':len(script.encode())}
        if any(not 0<measurements[k]<=cap for k,cap in CAPS.items()):fail('DELIVERY_CAP')
        return dict(script=script,request=req,registration=registration,release=release,
            sizes=measurements,script_sha256=sha(script.encode()),request_sha256=sha(canonical(req)))
    finally:
        for name,m in loaded.items():
            if sys.modules.get(name) is m:del sys.modules[name]


if __name__=='__main__':
    # Intentionally no token read, network fetch, output script or local files.
    raise SystemExit('RELEASE_REGISTRATION_REQUIRED')
