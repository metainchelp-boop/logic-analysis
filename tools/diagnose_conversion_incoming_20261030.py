"""Build one minimal, read-only Incoming probe for failed prepare 41023987057."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

BASE = '7121379777590e9ff8b09b49bb2ba18924844d1d'
BRANCH = 'claude/naver-conversion-incoming-diagnostic-20261030'
REF = 'refs/heads/' + BRANCH
WORKFLOW = '.github/workflows/naver-conversion-incoming-diagnostic-20261030.yml'
FILES = {WORKFLOW, 'tools/diagnose_conversion_incoming_20261030.py',
         'tools/test_diagnose_conversion_incoming_20261030.py', 'docs/conversion-incoming-diagnostic-20261030.md'}
NS = 'release/conversion-20261026'
PINS = {  # unchanged BASE payload, checked on the exact bytes that are executed or sent
    'bundle.py': '546c7cb729428add49a79fcac72eeb05fb652ff67dbdd236ce0f947bf0d602c9',
    'backend/tools/naver_report_progress_transport.py': '58bc51e9a26f49a54ca59e4e9f5188f43c963fc9f050c4738e3ac3305aa14fd5',
    'backend/tools/naver_report_progress_patch.py': '0048f014041bf451d26835dffce314a57d699f6046c85000362faedfee175596',
    'backend/tools/naver_preview_completion_release.py': '3be9c0360a6f75192455d6b139317319dd111b4e404628505ae62783b37977e2',
}
FAILED_RUN = '41023987057'
SOURCE_COMMIT = 'abceeb737548ada081072df95279d19981b561f7'
SOURCE_SHA256 = '50681cb0a30db4f421d8555d859b8a050ca5e07e6f5b6f5662ca527c036ef703'
CIPHERTEXT_SHA256 = '53b9fd97ccf1baf5923af959fd8b7e315df04c51b4440ce12de91a029ad32027'
CURRENT_BASELINE = '1a107fb029873d44ccfc09b1001c5d85b3dd5e871c008adeadb516e12b72e3cd'
HISTORICAL_BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
MAX_SCRIPT = 2200
MAX_SSH = 131072
SCRIPT = '''set -eu
/usr/bin/python3 -I -B - <<'PYCODE'
import base64,hashlib,json,os,signal,types
signal.alarm(100)
s='transport';r={}
try:
 w=os.environ['P22_WIRE'];b=os.environ['P22_BOOT']
 if len(b)>32768:raise ValueError('COMPLETION_TRANSPORT_SOURCE')
 raw=base64.b64decode(b,validate=True)
 if hashlib.sha256(raw).hexdigest()!='58bc51e9a26f49a54ca59e4e9f5188f43c963fc9f050c4738e3ac3305aa14fd5':raise ValueError('COMPLETION_TRANSPORT_SOURCE')
 T=types.ModuleType('qualified_transport');exec(raw,T.__dict__)
 if T.TRANSPORT_RAW_SHA256 is not None:raise ValueError('COMPLETION_TRANSPORT_PROFILE')
 T.TRANSPORT_RAW_SHA256=hashlib.sha256(raw).hexdigest();s='decode';v=T.decode(w)
 os.environ.clear();os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',LANG='C')
 s='modules';m=T.modules(v);P=m['patch'];s='package';k=v['package']
 if v['operation']!='preview-report-progress-prepare' or k['run_id']!='41023987057' or k['ciphertext_sha256']!='53b9fd97ccf1baf5923af959fd8b7e315df04c51b4440ce12de91a029ad32027':raise ValueError('PATCH_PACKAGE')
 P.validate_package(k,m['release'])
 r['root_user']=os.geteuid()==0;s='baseline';a=m['host'].NativeHost().baseline();c=P.CURRENT_BASELINE
 r.update(actual_baseline_sha256=a,current_expected_sha256=c,equal=a==c);s='complete'
except Exception as e:
 x=e.args[0] if len(e.args)==1 and type(e.args[0]) is str else ''
 r['error_code']=x if x in {'PATCH_ENCODING','PATCH_SOURCE','PATCH_BUNDLE','PATCH_SCOPE','PATCH_BASELINE','PATCH_PACKAGE','PATCH_NOT_PINNED','DETAIL_AI_PINS_PENDING','PACKAGE_FIELDS','PACKAGE_SHAPE','PACKAGE_OPERATION','COMPLETION_TRANSPORT_SOURCE','COMPLETION_TRANSPORT_PROFILE','UNEXPECTED_CONTAINERS','AD_NOT_RUNNING'} else 'UNRECOGNIZED'
r['stage']=s
print('NAVER_CONVERSION_INCOMING_DIAGNOSTIC='+json.dumps(r,sort_keys=True))
PYCODE
'''


def require(condition):
    if condition is not True:
        raise ValueError('READONLY_DIAGNOSTIC_BOUNDARY')


def git(*args):
    return subprocess.check_output(['git', *args], text=True, timeout=30).strip()


def context(env, event, head):
    require(env.get('GITHUB_REPOSITORY') == 'metainchelp-boop/logic-analysis' and env.get('GITHUB_REF') == REF)
    require(env.get('GITHUB_EVENT_NAME') == 'push' and env.get('GITHUB_RUN_ATTEMPT') == '1')
    require(env.get('GITHUB_ACTOR') == 'metainchelp-boop' and env.get('GITHUB_SHA') == head
            and re.fullmatch('[0-9a-f]{40}', head) is not None)
    require(event.get('after') == head and event.get('ref') == REF and event.get('forced') is False and event.get('deleted') is False)
    repo = event.get('repository', {})
    require(repo.get('full_name') == 'metainchelp-boop/logic-analysis' and repo.get('private') is False)


def source_boundary(head):
    """Exact BASE plus the four added diagnostic files; nothing in BASE changes."""
    require(not git('status', '--porcelain', '--untracked-files=all'))
    require(subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, head], timeout=30).returncode == 0)
    require(set(git('diff', '--name-status', BASE, head).splitlines()) == {'A\t' + p for p in FILES})


def pinned(root, name):
    raw = (root / NS / name).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == PINS[name])
    return raw


def package():
    return {'baseline': CURRENT_BASELINE, 'source_commit': SOURCE_COMMIT, 'ciphertext_sha256': CIPHERTEXT_SHA256,
            'source_tar_gz_sha256': SOURCE_SHA256, 'run_id': FAILED_RUN, 'operation': 'code-prepare'}


def build(root):
    """Rebuild the failed prepare's request offline from the pinned release; no URL, no ciphertext."""
    for name in PINS:
        pinned(root, name)
    folder = root / NS
    previous = Path.cwd()
    os.chdir(folder)
    try:
        source = pinned(root, 'bundle.py').decode()
        marker = 'P.require_pins();inputs='
        require(source.count(marker) == 1)
        prefix = source.split(marker, 1)[0]
        scope = {}
        exec(compile(prefix, 'qualified_bundle_prefix', 'exec'), scope)
        T, P = scope['T'], scope['P']
        require((P.CURRENT_BASELINE, P.EXPECTED_BASELINE, P.TARGET_COMMIT, P.TARGET_SOURCE_SHA256, P.BASE_CONTROLLER_SHA256)
                == (CURRENT_BASELINE, HISTORICAL_BASELINE, SOURCE_COMMIT, SOURCE_SHA256, PINS['backend/tools/naver_preview_completion_release.py']))
        value = T.bundle('preview-report-progress-prepare', json.loads(json.dumps(package(), sort_keys=True)), Path('backend/tools'))
        wire = T.encode(value); boot = T.bootstrap(scope['transport_raw'])
        require(T.decode(wire) == value and len(boot) <= T.MAX_BOOTSTRAP_B64 and len(wire) <= T.MAX_WIRE)
    finally:
        os.chdir(previous)
    require(len(SCRIPT.encode()) <= MAX_SCRIPT and ssh_size(wire, boot) < MAX_SSH)
    return wire, boot


def ssh_size(wire, boot):
    return len(("export P22_WIRE='" + wire + "'; export P22_BOOT='" + boot + "';\n" + SCRIPT).encode())


def main():
    root = Path.cwd(); head = git('rev-parse', 'HEAD')
    context(os.environ, json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()), head)
    source_boundary(head)
    wire, boot = build(root)
    require(git('rev-parse', 'HEAD') == head and not git('status', '--porcelain', '--untracked-files=all'))
    for value in (wire, boot):
        print('::add-mask::' + value.replace('%', '%25'))
    with open(os.environ['GITHUB_ENV'], 'a') as stream:
        stream.write('P22_WIRE=' + wire + '\nP22_BOOT=' + boot + '\n')
    print(json.dumps({'readonly_probe': 'built', 'script_bytes': len(SCRIPT.encode()), 'wire_bytes': len(wire),
                      'bootstrap_bytes': len(boot), 'ssh_bytes': ssh_size(wire, boot), 'server_calls': 0}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('READONLY_DIAGNOSTIC_BUILD_REFUSED') from None
