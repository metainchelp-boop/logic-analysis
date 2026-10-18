"""Inspect fixed systemd property-schema differences on an empty hosted VM.

No exporter, DB, journal, network or prior whole fixture is executed. Only two
new fixed disposable units are owned. Raw property values stay in RAM. Existing
production snapshot() remains unchanged and is called for classification only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import types

CONFIRM = 'github-hosted-empty-snapshot-schema-only-v1'
GATE_PIN = '1a7048dd55d808f583e25f2b4f73f7f7503c5d898555acd4cbef7c06258c8356'
TRANSITION_PIN = 'acd5636795506381c89ac0aa8657c7ea1b4f6a26985f50b0297fba62c7d5591a'
SYSTEMD_PIN = '2dc4e18e855a504cac6acd5c1df2be9ac30436a6d8755a7a10205661b304283c'
FIELDS = ('LoadState', 'UnitFileState', 'FragmentPath', 'DropInPaths', 'Job',
          'Result', 'ExecMainStatus', 'ActiveState', 'SubState', 'InvocationID')
CASES = ('service_absent', 'timer_absent', 'service_loaded_idle', 'timer_loaded_idle',
         'timer_active_waiting', 'service_finished', 'service_masked', 'timer_masked')
SERVICE = 'naver-diagnostic-snapshot-fixture.service'
TIMER = 'naver-diagnostic-snapshot-fixture.timer'
ROOT = Path('/etc/systemd/system')
MASK_ROOT = Path('/run/systemd/system.control')
SERVICE_BODY = b'[Unit]\nDescription=Disposable property-schema fixture\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\nNoNewPrivileges=yes\nPrivateNetwork=yes\n'
TIMER_BODY = ('[Unit]\nDescription=Disposable timer-schema fixture\n[Timer]\n'
    'OnActiveSec=1h\nUnit=' + SERVICE + '\n').encode()


class Refused(Exception):
    pass


def require(value):
    if value is not True: raise Refused()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def pinned(path, digest):
    info = path.lstat()
    require(path.resolve() == path and stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    require(0 < info.st_size <= 262144)
    body = path.read_bytes()
    require(hashlib.sha256(body).hexdigest() == digest)
    return body


def dependencies():
    parent = Path(__file__).resolve().parent
    require(parent.name == 'naver_market_diagnostic_transition')
    paths = (('gate', parent/'linux_root_fixture.py', GATE_PIN),
             ('transition', parent/'transition.py', TRANSITION_PIN),
             ('systemd_boundary', parent/'systemd_boundary.py', SYSTEMD_PIN))
    bodies = [(name, pinned(path, pin)) for name,path,pin in paths]
    modules = {}
    for name, body in bodies:
        require(name not in sys.modules)
        module = types.ModuleType(name)
        module.__file__ = '<pinned-snapshot-schema-' + name + '>'
        sys.modules[name] = module
        exec(compile(body, module.__file__, 'exec'), module.__dict__)
        modules[name] = module
    return modules['gate'], modules['transition'], modules['systemd_boundary']


def project(raw, S):
    """Names come only from FIELDS or a fixed unknown-property marker."""
    result = dict(format_ok=False, missing=[], extra=[], empty=[], invalid=[], duplicate=[],
                  snapshot_accepted=False, rejection='unclassified')
    try:
        S.snapshot(raw)
    except BaseException as error:
        code = error.args[0] if len(error.args) == 1 and type(error.args[0]) is str else None
        result['rejection'] = code if code in ('SYSTEMD_SNAPSHOT', 'SYSTEMD_JSON', 'OPERATION') else 'unclassified'
    else:
        result['snapshot_accepted'] = True; result['rejection'] = None
    if type(raw) is not bytes or len(raw) > 4096:
        return result
    try: lines = raw.decode('ascii').splitlines()
    except UnicodeError: return result
    pairs = [line.split('=', 1) for line in lines]
    if any(len(pair) != 2 for pair in pairs): return result
    fields, duplicates = {}, set()
    for name,value in pairs:
        if name in fields: duplicates.add(name)
        fields[name] = value
    known = set(FIELDS)
    result['format_ok'] = True
    result['missing'] = sorted(known-set(fields))
    result['extra'] = ['other_property'] if set(fields)-known else []
    result['empty'] = sorted(k for k in known & set(fields) if fields[k] == '')
    result['duplicate'] = sorted(k for k in duplicates if k in known)
    if duplicates-known: result['duplicate'].append('other_property')
    invalid = {k if k in known else 'other_property' for k,v in fields.items()
               if any(ord(c) < 32 for c in v)}
    if 'ExecMainStatus' in fields:
        v=fields['ExecMainStatus']
        if re.fullmatch('0|[1-9][0-9]{0,2}', v) is None or int(v)>255:
            invalid.add('ExecMainStatus')
    if 'InvocationID' in fields:
        v=fields['InvocationID']
        if v not in ('','0'*32) and re.fullmatch('[0-9a-f]{32}',v) is None:
            invalid.add('InvocationID')
    result['invalid'] = sorted(invalid)
    return result


def private_fields(raw):
    try:
        if type(raw) is not bytes or len(raw)>4096: return {}
        pairs=[line.split('=',1) for line in raw.decode('ascii').splitlines()]
        if any(len(pair)!=2 for pair in pairs): return {}
        fields=dict(pairs)
        if len(fields)!=len(pairs) or set(fields)-set(FIELDS): return {}
        return fields
    except (ValueError,UnicodeError): return {}


def masked_expectations(raw, previous=None):
    fields=private_fields(raw)
    result={name:fields.get(name)==expected for name,expected in (
        ('LoadState','masked'),('FragmentPath','/dev/null'),('UnitFileState','masked-runtime'))}
    if previous is not None:
        before=private_fields(previous).get('InvocationID')
        usable=type(before) is str and before!='0'*32 and re.fullmatch('[0-9a-f]{32}',before) is not None
        result['finished_invocation_nonzero']=usable
        result['invocation_matches_finished_or_cleared']=usable and fields.get('InvocationID') in ('','0'*32,before)
    return result


def identity(path):
    s = path.lstat()
    return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_nlink]


def write_unit(path, body, owned):
    fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o644)
    owned[path]=identity(path)
    try:
        os.fchmod(fd,0o644);os.fchown(fd,0,0)
        owned[path]=identity(path)
        view=memoryview(body)
        while view:
            n=os.write(fd,view);require(n>0);view=view[n:]
        os.fsync(fd)
    finally: os.close(fd)
    owned[path]=identity(path)


def run(confirm):
    stage='host_gate'; observations={}; private={}; owned={}; mask_created=False; S=None
    cleaned=True; failure=False
    try:
        require(confirm==CONFIRM)
        gate,T,S=dependencies()
        # Only the original fixture's pre-mutation guard is reused, never run().
        gate.gate(gate.CONFIRM)
        require(tuple(S.PROPERTIES)==FIELDS)
        for directory in (ROOT,Path('/run/systemd/system'),MASK_ROOT,
                          Path('/usr/lib/systemd/system'),Path('/lib/systemd/system')):
            for name in (SERVICE,TIMER):
                for suffix in ('','.d'):
                    p=directory/(name+suffix)
                    require(not p.exists() and not p.is_symlink())
        def command(argv):
            code,raw=S.bounded(argv,limit=4096,timeout=8)
            require(type(code) is int and code==0)
            return raw
        def action(verb,*units):
            require(verb in ('daemon-reload','start','stop'))
            require(all(unit in (SERVICE,TIMER) for unit in units))
            command(['/usr/bin/systemctl',verb,*units])
        def capture(case,unit):
            require(case in CASES and case not in observations and unit in (SERVICE,TIMER))
            code,raw=S.bounded(['/usr/bin/systemctl','show',unit]+
                ['--property='+p for p in FIELDS],limit=4096,timeout=8)
            observations[case]=dict(command_success=type(code) is int and code==0, **project(raw,S))
            private[case]=raw
            if case in ('service_masked','timer_masked'):
                observations[case]['exact_expected']=masked_expectations(raw,
                    private.get('service_finished') if case=='service_masked' else None)
        stage='absent'
        for name in (SERVICE,TIMER):
            require(command(['/usr/bin/systemctl','show',name,'--property=LoadState'])==b'LoadState=not-found\n')
        capture('service_absent',SERVICE);capture('timer_absent',TIMER)
        stage='create_units'
        for name,body in ((SERVICE,SERVICE_BODY),(TIMER,TIMER_BODY)):
            write_unit(ROOT/name,body,owned)
        action('daemon-reload')
        capture('service_loaded_idle',SERVICE);capture('timer_loaded_idle',TIMER)
        stage='timer_waiting'
        action('start',TIMER)
        capture('timer_active_waiting',TIMER)
        stage='service_finished'
        action('start',SERVICE)  # /usr/bin/true once; no source or database access.
        capture('service_finished',SERVICE)
        stage='runtime_masks'
        action('stop',TIMER,SERVICE)
        # Reuse actual manager UnitPath syntax; do not alter parser/unit-kind contracts.
        raw=command(['/usr/bin/systemctl','show','--property=UnitPath'])
        text=raw.decode('ascii')
        require(text.startswith('UnitPath=') and text.count('\n')==1)
        paths=text.removeprefix('UnitPath=').rstrip('\n').split(' ')
        require(str(MASK_ROOT) in paths and str(ROOT) in paths and
                paths.index(str(MASK_ROOT))<paths.index(str(ROOT)))
        if not MASK_ROOT.exists():
            MASK_ROOT.mkdir(mode=0o755);mask_created=True
        require(MASK_ROOT.resolve()==MASK_ROOT)
        s=MASK_ROOT.lstat()
        require(stat.S_ISDIR(s.st_mode) and s.st_uid==0 and s.st_gid==0 and not s.st_mode&0o022)
        for name in (SERVICE,TIMER):
            p=MASK_ROOT/name;p.symlink_to('/dev/null');owned[p]=identity(p)
        action('daemon-reload')
        capture('service_masked',SERVICE);capture('timer_masked',TIMER)
        require(set(observations)==set(CASES))
    except BaseException:
        failure=True
    finally:
        if owned and S is not None:
            try:
                # The only stopped/removed objects are newly owned fixture units.
                code,_=S.bounded(['/usr/bin/systemctl','stop',TIMER,SERVICE],limit=4096,timeout=8)
                require(type(code) is int and code==0)
                for path,pin in owned.items(): require(identity(path)==pin)
                for path in owned: path.unlink()
                code,_=S.bounded(['/usr/bin/systemctl','daemon-reload'],limit=4096,timeout=8)
                require(type(code) is int and code==0)
                if mask_created: MASK_ROOT.rmdir()
            except BaseException:
                cleaned=False;failure=True
    return dict(schema='systemd-fixed-property-schema-observation-v1',
        status='failed' if failure else 'observed', failed_stage=stage if failure else None,
        cases=observations, cleanup_verified=cleaned, original_snapshot_changed=False,
        operating_host_access=False, database_or_exporter_executed=False,
        whole_fixture_reexecuted=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--confirm',required=True,choices=[CONFIRM])
    args=parser.parse_args();result=run(args.confirm)
    sys.stdout.buffer.write(canonical(result)+b'\n')
    raise SystemExit(0 if result['status']=='observed' else 1)
