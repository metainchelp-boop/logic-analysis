"""Build one bounded, read-only probe for failed prepare 40335961943."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

BASE='0eb8bdb8d5c0bef7562370566c9faab71ee8f2bb'
REF='refs/heads/codex/naver-conversion-incoming-diagnostic-20261026'
FILES={'.github/workflows/naver-conversion-incoming-diagnostic.yml','tools/diagnose_conversion_incoming.py',
       'tools/test_diagnose_conversion_incoming.py','docs/conversion-incoming-diagnostic-20261026.md'}
SCRIPT='''set -eu
/usr/bin/python3 -I -B - <<'PYCODE'
import base64,hashlib,json,os,pathlib,signal,stat,types
signal.alarm(100)
stage='transport';result={'ok':False,'mutations':0,'probe_prepare_run':'40335961943'}
codes={'PATCH_ENCODING','PATCH_SOURCE','PATCH_BUNDLE','PATCH_SCOPE','PATCH_BASELINE','PATCH_PACKAGE','PACKAGE_FIELDS','PACKAGE_SHAPE','PACKAGE_OPERATION','HOST_BASELINE','COMPLETION_TRANSPORT_SOURCE','COMPLETION_TRANSPORT_PROFILE','UNEXPECTED_CONTAINERS','AD_NOT_RUNNING'}
try:
 wire=os.environ['P22_WIRE'];source=os.environ['P22_BOOT']
 if len(source)>32768:raise ValueError('COMPLETION_TRANSPORT_SOURCE')
 raw=base64.b64decode(source,validate=True)
 if hashlib.sha256(raw).hexdigest()!='782703fdc8efad330ecbe7b37378d3d1347caa55e40ca4fa12673ac0001b7cd4':raise ValueError('COMPLETION_TRANSPORT_SOURCE')
 T=types.ModuleType('qualified_transport');exec(raw,T.__dict__)
 if T.TRANSPORT_RAW_SHA256 is not None:raise ValueError('COMPLETION_TRANSPORT_PROFILE')
 T.TRANSPORT_RAW_SHA256=hashlib.sha256(raw).hexdigest();stage='decode';value=T.decode(wire)
 os.environ.clear();os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',LANG='C')
 stage='modules';m=T.modules(value);P=m['patch'];release=m['release'];stage='package'
 P.validate_package(value['package'],release)
 if value['package']['run_id']!='40335961943':raise ValueError('PATCH_PACKAGE')
 result['root_user']=os.geteuid()==0;stage='baseline';actual=m['host'].NativeHost().baseline()
 result.update(baseline_match=actual==P.EXPECTED_BASELINE,actual_baseline_sha256=actual,expected_baseline_sha256=P.EXPECTED_BASELINE)
 stage='paths';paths={}
 for label,path in [('root',release.ROOT),('incoming',release.ROOT/'incoming'),('failed_run',release.ROOT/'incoming'/'40335961943')]:
  try:
   st=path.lstat();paths[label]={'exists':True,'directory':stat.S_ISDIR(st.st_mode),'symlink':stat.S_ISLNK(st.st_mode),'uid':st.st_uid,'gid':st.st_gid,'mode':stat.S_IMODE(st.st_mode)}
  except FileNotFoundError:paths[label]={'exists':False}
 result.update(ok=True,stage='diagnostic_complete',paths=paths)
except Exception as e:
 code=e.args[0] if len(e.args)==1 and isinstance(e.args[0],str) and e.args[0] in codes else 'UNRECOGNIZED'
 result.update(stage=stage,error_code=code,error_kind=type(e).__name__ if type(e).__name__ in {'ValueError','RuntimeError','FileNotFoundError','PermissionError','InstallError'} else 'OtherError')
print('NAVER_CONVERSION_INCOMING_DIAGNOSTIC='+json.dumps(result,sort_keys=True))
PYCODE
'''


def require(condition):
    if not condition:raise ValueError('READONLY_DIAGNOSTIC_BOUNDARY')


def git(*args):
    return subprocess.check_output(['git',*args],text=True,timeout=30).strip()


def context(env,event,head):
    require(env.get('GITHUB_REPOSITORY')=='metainchelp-boop/logic-analysis' and env.get('GITHUB_REF')==REF)
    require(env.get('GITHUB_EVENT_NAME')=='push' and env.get('GITHUB_RUN_ATTEMPT')=='1')
    require(env.get('GITHUB_ACTOR')=='metainchelp-boop' and env.get('GITHUB_SHA')==head and re.fullmatch('[0-9a-f]{40}',head))
    require(event.get('after')==head and event.get('ref')==REF and event.get('forced') is False and event.get('deleted') is False)
    repo=event.get('repository',{})
    require(repo.get('full_name')=='metainchelp-boop/logic-analysis' and repo.get('private') is False)


def build(root):
    os.chdir(root/'release/conversion-20261026')
    scope={};source=Path('bundle.py').read_text()
    require(hashlib.sha256(source.encode()).hexdigest()=='4d9c7e1c4d9fd922106b07c8eae8387126dfcfa1a769b1699d0c8fcabca1d699')
    exec(compile(source.split('P.require_pins();inputs=',1)[0],'qualified_bundle_prefix','exec'),scope)
    T=scope['T'];P=scope['P']
    package={'baseline':P.EXPECTED_BASELINE,'source_commit':P.TARGET_COMMIT,'ciphertext_sha256':'d7ff71b65953fd010b557a7faa4f27ddd565b4421f1a77753172479d34f21feb','source_tar_gz_sha256':'624f51d9e1a0256644bed0fd8e256e590cf57388c7e13f6c8345f331c1a6d81b','run_id':'40335961943','operation':'code-prepare'}
    value=T.bundle('preview-report-progress-prepare',package,Path('backend/tools'));wire=T.encode(value);boot=T.bootstrap(scope['transport_raw'])
    require(T.decode(wire)==value and len(boot)<=32768)
    exports="export P22_WIRE='"+wire+"'; export P22_BOOT='"+boot+"';\n"
    require(len((exports+SCRIPT).encode())<131072)
    os.chdir(root)
    return wire,boot


def main():
    root=Path.cwd();head=git('rev-parse','HEAD')
    context(os.environ,json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()),head)
    require(not git('status','--porcelain','--untracked-files=all'))
    subprocess.run(['git','merge-base','--is-ancestor',BASE,head],check=True,timeout=30)
    require(set(git('diff','--name-status',BASE,head).splitlines())=={'A\t'+p for p in FILES})
    wire,boot=build(root)
    require(git('rev-parse','HEAD')==head and not git('status','--porcelain','--untracked-files=all'))
    for value in [wire,boot]:print('::add-mask::'+value.replace('%','%25'))
    with open(os.environ['GITHUB_ENV'],'a') as stream:stream.write('P22_WIRE='+wire+'\nP22_BOOT='+boot+'\n')


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('READONLY_DIAGNOSTIC_BUILD_REFUSED') from None
