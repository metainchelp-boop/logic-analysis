"""One exact failed pre-start install recovery; never touch DBs or start units."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import types

OLD_HELPER_SHA256 = '2b47884242c1b1e7b67074383f070a79bbdd4f88471c0448a92116cf9b34c7a8'
FAILED_OPERATION = '90bde9d376f05f4ae24c99e0cccdea5e'
TARGET = 'e7649acfc71c25d7ae9c981a6ba036b77d97897b'
PLAN = {'ops_commit':'19586caf7fe5579e7da70d4a2d4205c3ed603996',
        'source_directory':'/root/logic-analysis-deploy/data', 'database_name':'logic_data.db',
        'exporter_user':'nobody', 'source_group':None, 'python_executable':'/usr/bin/python3'}
FIELDS = ('LoadState','ActiveState','SubState','InvocationID','Job','UnitFileState')
UNITS = tuple('naver-'+kind+'-export'+tail for kind in ('product','market')
              for tail in ('.service','-reader.service','.timer'))
ROOT = Path('/srv/metainc/ad-deploy-staging')
STAGE = 'input'
ISSUES = frozenset(('policy unit_fields unit_load unit_active unit_invocation unit_job unit_enabled unit_status daemon_reload helper_refused').split())
STAGES = frozenset(('input receipt_preflight artifact_preflight unit_state_preflight rollback_unit_state rollback daemon_reload postflight').split())


def is_root():
    return os.geteuid()==0


def refuse(issue='policy'):
    raise ValueError(issue if issue in ISSUES else 'policy')


def failure_report(error):
    issue=error.args[0] if type(error) is ValueError and error.args and type(error.args[0]) is str and error.args[0] in ISSUES else 'helper_refused'
    stage=STAGE if type(STAGE) is str and STAGE in STAGES else 'input'
    return {'version':1,'state':'refused','stage':stage,'issue':issue}


def load_helper(source):
    if type(source) is not bytes or hashlib.sha256(source).hexdigest()!=OLD_HELPER_SHA256:
        refuse()
    module=types.ModuleType('exact_failed_saved_exports_helper')
    exec(source,module.__dict__)
    return module


def run_fixed(args):
    if args!=['/usr/bin/systemctl','daemon-reload'] and args not in [
            ['/usr/bin/systemctl','show',unit,*['--property='+key for key in FIELDS]] for unit in UNITS]:
        refuse()
    result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,timeout=8,
                          env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C'})
    if (type(result.stdout) is not bytes or type(result.stderr) is not bytes or
            len(result.stdout)>8192 or len(result.stderr)>8192 or result.returncode not in (0,1)):
        refuse()
    return result


def unit_state(unit,run):
    result=run(['/usr/bin/systemctl','show',unit,*['--property='+key for key in FIELDS]])
    if result.returncode not in (0,1):refuse()
    try:
        lines=result.stdout.decode('ascii').splitlines()
        pairs=[line.split('=',1) for line in lines]
        if any(len(pair)!=2 for pair in pairs) or len(pairs)!=len(FIELDS):refuse('unit_fields')
        value=dict(pairs)
        if set(value)!=set(FIELDS) or len(value)!=len(pairs):refuse('unit_fields')
    except (UnicodeError,TypeError,ValueError):
        refuse()
    if value['LoadState'] not in ('loaded','not-found','bad-setting','error'):refuse('unit_load')
    if value['ActiveState']!='inactive' or value['SubState']!='dead':refuse('unit_active')
    if value['InvocationID'] not in ('','0'*32):refuse('unit_invocation')
    if value['Job']!='0':refuse('unit_job')
    if value['UnitFileState'] not in ('','disabled','static','bad','not-found'):refuse('unit_enabled')
    if result.returncode==1 and value['LoadState']!='not-found':refuse('unit_status')
    return value


def inactive_units(run,*,removed=False):
    values=[unit_state(unit,run) for unit in UNITS]
    if removed and any(value['LoadState']!='not-found' for value in values):refuse()
    return values


def recover_with_helper(helper,*,run=run_fixed):
    global STAGE
    STAGE='receipt_preflight'
    if not is_root():refuse()
    # A successful completion prepare publishes this receipt. Recovery must
    # never dismantle a successfully prepared/applied companion.
    completion=ROOT/'receipts'/('completion-exports-'+TARGET+'.json')
    prepared_release=ROOT/'receipts'/('preview-'+TARGET+'.json')
    helper._directory(ROOT,mode=0o700)
    helper._directory(ROOT/'receipts',mode=0o700)
    for path in (completion,prepared_release):
        if path.exists() or path.is_symlink():refuse()
    folder=helper.STAGING/FAILED_OPERATION
    helper._directory(helper.STAGING,mode=0o700)
    helper._directory(folder,mode=0o700)
    receipt=json.loads(helper._regular(folder/'prepared.json',mode=0o600))
    if (receipt.get('version')!=3 or receipt.get('operation_id')!=FAILED_OPERATION or receipt.get('plan')!=PLAN):
        refuse()
    STAGE='artifact_preflight'
    plan,actual_folder,state=helper._rollback_state(receipt)
    expected=[str(helper.INSTALL/PLAN['ops_commit']/name) for name in (*helper.SCRIPTS,helper.INTERPRETER)]
    expected.extend(str(helper.UNITS/unit) for unit in UNITS)
    allowed_directories={str(helper.INSTALL/PLAN['ops_commit']),*[str(path) for path in helper.OUTPUTS.values()]}
    if (actual_folder!=folder or plan!=PLAN or state.get('version')!=1 or state.get('state') not in ('failed','rolled_back') or
            state.get('timers_enabled') is not False or state.get('engine_verified') is not False or
            type(state.get('created_directories')) is not list or
            len(state['created_directories'])!=len(set(state['created_directories'])) or
            not set(state['created_directories'])<=allowed_directories or
            str(helper.INSTALL/PLAN['ops_commit']) not in state['created_directories'] or
            sorted(state.get('created_files',[]))!=sorted(expected)):
        refuse()
    for leaf in (helper.UNITS,helper.INSTALL):
        for parent in (leaf,*leaf.parents):helper._directory(parent)
    script_dir=helper.INSTALL/PLAN['ops_commit']
    if script_dir.exists() or script_dir.is_symlink():helper._directory(script_dir,mode=0o755)
    for name in expected:
        if not Path(name).exists() and not Path(name).is_symlink():continue
        info=Path(name).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:refuse()
    STAGE='unit_state_preflight';inactive_units(run)
    # The malformed units never started or gained timers. Recheck all six on
    # every skip; do not reinterpret a failed stop as proof of inactivity.
    def command(args):
        global STAGE
        allowed=[['systemctl','disable','--now','naver-'+kind+'-export.timer'] for kind in ('product','market')]
        allowed.extend(['systemctl','stop',unit] for unit in UNITS if unit.endswith('.service'))
        if args in allowed:
            STAGE='rollback_unit_state'
            inactive_units(run)
            helper._rollback_state(receipt)
            return b''
        if args==['systemctl','daemon-reload']:
            STAGE='daemon_reload'
            checked=run(['/usr/bin/systemctl','daemon-reload'])
            if checked.returncode!=0:refuse('daemon_reload')
            return b''
        refuse()
    STAGE='rollback';helper.rollback(receipt,command=command)
    STAGE='postflight';inactive_units(run,removed=True)
    if any(Path(name).exists() or Path(name).is_symlink() for name in expected):refuse()
    return {'version':1,'state':'recovered','failed_prepare_run':38195967572,
            'expected_exact_files_absent':len(expected),'units_started':0,
            'source_writes':False,'database_writes':False,'export_bundles_preserved':True}


def recover(source,*,run=run_fixed):
    return recover_with_helper(load_helper(source),run=run)
