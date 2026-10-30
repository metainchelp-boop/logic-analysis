import base64,hashlib,json,os,pathlib,re,sys,types;transport_sha='58bc51e9a26f49a54ca59e4e9f5188f43c963fc9f050c4738e3ac3305aa14fd5';core_sha='0048f014041bf451d26835dffce314a57d699f6046c85000362faedfee175596'
if any(re.fullmatch('[0-9a-f]{64}',value)is None for value in(transport_sha,core_sha)):raise ValueError('REPORT_PROGRESS_PINS_PENDING')
transport_path=pathlib.Path('backend/tools/naver_report_progress_transport.py');core_path=pathlib.Path('backend/tools/naver_report_progress_patch.py')
if transport_path.is_symlink()or not transport_path.is_file()or not 0<transport_path.stat().st_size<=24576:raise ValueError('COMPLETION_TRANSPORT_SOURCE')
transport_raw=transport_path.read_bytes();verified_transport_sha=hashlib.sha256(transport_raw).hexdigest()
if verified_transport_sha!=transport_sha:raise ValueError('COMPLETION_TRANSPORT_SOURCE')
if core_path.is_symlink()or not core_path.is_file()or not 0<core_path.stat().st_size<=160000:raise ValueError('COMPLETION_PATCH_SOURCE')
core_raw=core_path.read_bytes();verified_core_sha=hashlib.sha256(core_raw).hexdigest()
if verified_core_sha!=core_sha:raise ValueError('COMPLETION_PATCH_SOURCE')
T=types.ModuleType('naver_report_progress_transport');T.__file__=str(transport_path)
exec(transport_raw,T.__dict__)
if T.TRANSPORT_RAW_SHA256 is not None or T.SOURCE_SHA256['patch']!=verified_core_sha:raise ValueError('COMPLETION_TRANSPORT_PROFILE')
T.TRANSPORT_RAW_SHA256=verified_transport_sha;T.require_pins()
P=types.ModuleType('naver_report_progress_patch');P.__file__=str(core_path)
exec(core_raw,P.__dict__);P.require_pins()
sys.path.insert(0,'backend/tools');sys.modules[P.__name__]=P
def report_progress_ssh_scripts(workflow):
 lines=workflow.splitlines(keepends=True);starts=[i for i,line in enumerate(lines)if line.rstrip('\r\n')=='  report-progress:']
 if len(starts)!=1:raise ValueError('COMPLETION_SSH_WORKFLOW')
 start=starts[0]+1;end=len(lines)
 for i in range(start,len(lines)):
  if lines[i].startswith('  ')and not lines[i].startswith('   ')and lines[i].strip().endswith(':'):end=i;break
 section=lines[start:end];scripts=[]
 if sum(line.strip().startswith('uses: appleboy/ssh-action@')for line in section)!=2:raise ValueError('COMPLETION_SSH_WORKFLOW')
 for i,line in enumerate(section):
  if line.rstrip('\r\n')!='          script: |':continue
  body=[]
  for item in section[i+1:]:
   if item.startswith('            '):body.append(item[12:])
   elif not item.strip():body.append(item)
   else:break
  if not body:raise ValueError('COMPLETION_SSH_WORKFLOW')
  scripts.append(''.join(body))
 if len(scripts)!=2:raise ValueError('COMPLETION_SSH_WORKFLOW')
 return scripts
def require_report_progress_ssh_pressure(wire,transport,workflow):
 if any(type(value)is not str or not value.isascii()or any(char in value for char in"'\r\n\x00")for value in(wire,transport)):raise ValueError('COMPLETION_SSH_ENV')
 exports="export P22_WIRE='"+wire+"'; export P22_BOOT='"+transport+"';\n";sizes=[len((exports+script).encode('utf-8'))for script in report_progress_ssh_scripts(workflow)]
 if any(size>=131072 for size in sizes):raise ValueError('COMPLETION_SSH_SIZE')
 return sizes
P.require_pins();inputs=json.loads(pathlib.Path(os.environ['GITHUB_EVENT_PATH']).read_text())['inputs'];operation=inputs.pop('ad_prepare');package=json.loads(inputs.pop('ad_expected_baseline'))
assert operation in T.FUNCTIONS and all(v=='off'for v in inputs.values())
if operation=='preview-report-progress-prepare':from naver_completion_download import download;fields=download(package,'preview-payload');fields.update(run_id=os.environ['RUN_ID'],operation='code-prepare');package=fields
package=json.loads(json.dumps(package,sort_keys=True));wire=T.encode(T.bundle(operation,package,pathlib.Path('backend/tools')));transport=T.bootstrap(transport_raw);assert len(transport)<=32768;require_report_progress_ssh_pressure(wire,transport,pathlib.Path('.github/workflows/debug-rank.yml').read_text(encoding='utf-8'));[print('::add-mask::'+x.replace('%','%25'))for x in(wire,transport)]
with open(os.environ['GITHUB_ENV'],'a')as stream:stream.write('P22_WIRE='+wire+'\n');stream.write('P22_BOOT='+transport+'\n')
