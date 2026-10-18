"""Portable candidate runner and offline exact evidence verifier.

CI-only: no network collector, remote execution, deployment or qualification of
the operating host. Raw synthetic stdout stays bounded in RAM and is discarded.
The caller must pin this module and portable_contract at the exact checked head.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import zipfile
import portable_contract as C

MAX_OUTPUT = 2 * 1024 * 1024
MAX_ZIP = 1024 * 1024
MAX_MEMBER = 65536
ARTIFACT_DIRECTORY = 'portable-candidate-evidence'


class Invalid(ValueError):
    pass


def fail(code):
    raise Invalid(code)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError):
        fail('JSON_INVALID')


def sha(body):
    return hashlib.sha256(body).hexdigest()


def same(actual, expected):
    if type(actual) is not type(expected): return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(same(actual[k], v) for k, v in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(same(a, b) for a, b in zip(actual, expected))
    return actual == expected


def unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out: fail('JSON_DUPLICATE')
        out[key] = value
    return out


def strict(body):
    if type(body) is not bytes or not 0 < len(body) <= MAX_MEMBER: fail('JSON_SIZE')
    try:
        return json.loads(body, object_pairs_hook=unique, parse_constant=lambda _: fail('JSON_INVALID'))
    except (ValueError, UnicodeError, RecursionError):
        fail('JSON_INVALID')


def manifest():
    return {'version': 1, 'scope': 'portable_schema_candidate',
        'source_files': C.SOURCE_FILES, 'test_files': C.TEST_FILES,
        'cohorts': {k: {'tests': v['expected_tests'], 'test_ids_sha256': v['test_ids_sha256']}
            for k, v in C.COHORTS.items()}, 'native_unchanged': C.NATIVE_UNCHANGED}


def source_lines():
    return ''.join(v['sha256'] + '  ' + p + '\n' for p, v in sorted(C.SOURCE_FILES.items())).encode()


def verify_sources(root):
    root = Path(root).resolve(strict=True)
    for name, expected in dict(C.SOURCE_FILES, **C.TEST_FILES).items():
        path = root
        for part in Path(name).parts:
            if part in ('.', '..') or Path(name).is_absolute(): fail('SOURCE_PATH')
            path = path / part
            if path.is_symlink(): fail('SOURCE_PATH')
        st = path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size != expected['bytes']:
            fail('SOURCE_CHANGED')
        body = path.read_bytes()
        if len(body) != expected['bytes'] or sha(body) != expected['sha256']: fail('SOURCE_CHANGED')
    return manifest()


def closed_cohort(name):
    if type(name) is not str or name not in C.COHORTS: fail('COHORT')
    value = C.COHORTS[name]
    return {'version': 1, 'scope': 'portable_schema_candidate', 'cohort': name,
        'tests': value['expected_tests'], 'failures': 0, 'errors': 0, 'skipped': 0,
        'exit_code': 0, 'test_ids_sha256': value['test_ids_sha256'],
        'source_manifest_sha256': sha(canonical(manifest()))}


def parse_unittest(name, code, body):
    if type(code) is not int or code != 0 or type(body) is not bytes or len(body) > MAX_OUTPUT:
        fail('COHORT_FAILED')
    try: lines = body.decode('utf-8').splitlines()
    except UnicodeError: fail('COHORT_TEXT')
    expected = closed_cohort(name)
    ids, counts, ok, separators = [], [], 0, 0
    for line in lines:
        if not line: continue
        test = re.fullmatch(r'(test\w*) \(([A-Za-z_][\w.]*)\) \.\.\. ok', line)
        ran = re.fullmatch(r'Ran ([1-9][0-9]*) tests? in [0-9]+\.[0-9]+s', line)
        if test:
            if test[2].rsplit('.', 1)[-1] != test[1]: fail('COHORT_IDS')
            ids.append(test[2])
        elif ran: counts.append(int(ran[1]))
        elif line == 'OK': ok += 1
        elif line == '-' * 70: separators += 1
        else: fail('COHORT_TEXT')
    if (counts != [expected['tests']] or ok != 1 or separators != 1
        or len(ids) != expected['tests'] or len(set(ids)) != len(ids)
        or sha(canonical(sorted(ids))) != expected['test_ids_sha256']): fail('COHORT_IDS')
    return expected


def bounded(argv, *, cwd, env, timeout=180):
    child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    body = bytearray(); deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector(); selector.register(child.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0: fail('COHORT_TIMEOUT')
            for key, _ in selector.select(min(remaining, 0.1)):
                block = os.read(key.fileobj.fileno(), min(65536, MAX_OUTPUT + 1 - len(body)))
                if not block: selector.unregister(key.fileobj)
                else:
                    body.extend(block)
                    if len(body) > MAX_OUTPUT: fail('COHORT_OUTPUT')
        remaining = deadline - time.monotonic()
        if remaining <= 0: fail('COHORT_TIMEOUT')
        try: code = child.wait(timeout=remaining)
        except subprocess.TimeoutExpired: fail('COHORT_TIMEOUT')
        return code, bytes(body)
    finally:
        selector.close()
        if child.poll() is None: os.killpg(child.pid, signal.SIGKILL); child.wait()
        child.stdout.close()


def run_cohort(root, name):
    verify_sources(root)
    if type(name) is not str or name not in C.COHORTS: fail('COHORT')
    cohort = C.COHORTS[name]; root = Path(root).resolve(strict=True)
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONPATH': os.pathsep.join(str(root / p) for p in cohort['pythonpath_entries'])}
    code, body = bounded([sys.executable, '-B', '-m', 'unittest', '-v', *cohort['modules']], cwd=root, env=env)
    return parse_unittest(name, code, body)


def positive(value):
    return type(value) is int and 0 < value < 2**63


def exact_keys(value, keys):
    return type(value) is dict and set(value) == set(keys)


def verify_metadata(run, jobs, artifacts, *, head, run_id, artifact_id):
    if (type(head) is not str or re.fullmatch('[0-9a-f]{40}', head) is None
        or head == '0' * 40 or not positive(run_id) or not positive(artifact_id)): fail('REGISTRATION')
    expected = dict(id=run_id, head_sha=head, head_branch=C.BRANCH, event='push',
        status='completed', conclusion='success', run_attempt=1, path=C.WORKFLOW, repository=C.REPOSITORY)
    if not same(run, expected): fail('RUN_METADATA')
    if type(jobs) is not list or len(jobs) != 1: fail('JOB_METADATA')
    job = jobs[0]
    if not exact_keys(job, ('id','run_id','head_sha','name','status','conclusion','steps')) or not positive(job['id']):
        fail('JOB_METADATA')
    if not same({k: job[k] for k in ('run_id','head_sha','name','status','conclusion')},
        dict(run_id=run_id,head_sha=head,name=C.JOB,status='completed',conclusion='success')): fail('JOB_METADATA')
    steps=job['steps']
    if type(steps) is not list or not len(C.STEP_NAMES) <= len(steps) <= len(C.STEP_NAMES)+len(C.WRAPPER_STEPS):
        fail('JOB_STEPS')
    names=[]
    for i, step in enumerate(steps, 1):
        if not exact_keys(step, ('number','name','status','conclusion')) or type(step['number']) is not int or step['number'] != i:
            fail('JOB_STEPS')
        if (type(step['name']) is not str or step['name'] not in C.STEP_NAMES+C.WRAPPER_STEPS
            or step['status'] != 'completed' or step['conclusion'] != 'success'): fail('JOB_STEPS')
        names.append(step['name'])
    if len(set(names)) != len(names) or tuple(n for n in names if n in C.STEP_NAMES) != C.STEP_NAMES:
        fail('JOB_STEPS')
    if type(artifacts) is not list or len(artifacts) != 1: fail('ARTIFACT_METADATA')
    artifact=artifacts[0]
    if not exact_keys(artifact,('id','name','expired','workflow_run','size_in_bytes')):
        fail('ARTIFACT_METADATA')
    if (not same({k:artifact[k] for k in ('id','name','expired','workflow_run')},
        dict(id=artifact_id,name=C.ARTIFACT,expired=False,workflow_run=dict(id=run_id,head_sha=head)))
        or not positive(artifact['size_in_bytes']) or artifact['size_in_bytes'] > MAX_ZIP): fail('ARTIFACT_METADATA')
    return True


def verify_artifact(body):
    if type(body) is not bytes or not 0 < len(body) <= MAX_ZIP: fail('ARTIFACT_SIZE')
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            infos = archive.infolist()
            if len(infos) != len(C.MEMBERS) or set(i.filename for i in infos) != set(C.MEMBERS): fail('ARTIFACT_MEMBERS')
            values = {}
            for info in infos:
                kind = (info.external_attr >> 16) & 0o170000
                if (info.is_dir() or info.flag_bits & 1 or info.file_size > MAX_MEMBER or info.file_size < 1
                    or kind not in (0, stat.S_IFREG)): fail('ARTIFACT_MEMBER')
                values[info.filename] = archive.read(info)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError): fail('ARTIFACT_ZIP')
    if values['source-sha.txt'] != source_lines() or not same(strict(values['source-manifest.json']), manifest()):
        fail('ARTIFACT_SOURCES')
    for name in C.ORDER:
        if not same(strict(values[name+'.json']), closed_cohort(name)): fail('ARTIFACT_COHORT')
    return {'status':'PASS_PORTABLE_CANDIDATE_ONLY','tests':C.EXPECTED_TESTS,
        'cohorts':len(C.ORDER),'artifact_members':len(C.MEMBERS),'required_steps':len(C.STEP_NAMES),
        'source_files':len(C.SOURCE_FILES),'source_manifest_sha256':sha(canonical(manifest())),
        'native_unchanged':C.NATIVE_UNCHANGED,'linux_qualification':False,'operating_qualification':False}


def verify(run, jobs, artifacts, body, *, head, run_id, artifact_id):
    verify_metadata(run,jobs,artifacts,head=head,run_id=run_id,artifact_id=artifact_id)
    return verify_artifact(body)


def main():
    # Only a fixed repository-relative output directory; no path or command input.
    if len(sys.argv) != 2 or sys.argv[1] not in ('inventory', *C.ORDER): fail('CLI')
    root=Path(__file__).absolute().parents[3]; out=root/ARTIFACT_DIRECTORY
    verify_sources(root)
    if sys.argv[1]=='inventory':
        out.mkdir(mode=0o700,exist_ok=False)
        (out/'source-sha.txt').write_bytes(source_lines())
        (out/'source-manifest.json').write_bytes(canonical(manifest()))
    else:
        if out.is_symlink() or not out.is_dir(): fail('OUTPUT_DIRECTORY')
        result=run_cohort(root,sys.argv[1]); target=out/(sys.argv[1]+'.json')
        with target.open('xb') as stream: stream.write(canonical(result))
    print('PORTABLE_CANDIDATE_STEP_OK')


if __name__=='__main__':
    try: main()
    except Exception: raise SystemExit('PORTABLE_CANDIDATE_REFUSED')
