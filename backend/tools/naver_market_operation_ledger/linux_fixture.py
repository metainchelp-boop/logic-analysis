"""Isolated hosted Linux/root qualification; synthetic /run FS only, no services."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
from unittest import mock

CORE_SHA256 = 'd7fedc6bae4abe13cf7a53636ea288de6f33598337fe48b5183616af924a6f8f'
TEST_SHA256 = '2dae805c7c5c176ad36cda55b7646b0791703214616711260dc9dd0f33bf492f'
CONFIRM = 'github-hosted-empty-operation-ledger-v1'
CHECKS = ('root_ancestor_and_restored', 'readonly_syscalls_unchanged',
          'shared_lock_writer_exclusion', 'missing_and_bad_lock_refused',
          'lock_replacement_refused', 'directory_replacement_refused',
          'pending_hardlink_contract', 'run_once_after_rollback',
          'malformed_chain_refused', 'deadline_budget_and_fd_cleanup')


def require(value):
    if value is not True: raise RuntimeError('fixture_refused')


def source(path, digest):
    info=path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 32768)
    raw=path.read_bytes()
    require(type(digest) is str and len(digest)==64 and hashlib.sha256(raw).hexdigest()==digest)
    return raw


def load_test():
    here=Path(__file__).resolve().parent
    core=source(here/'core.py',CORE_SHA256)
    tests=source(here/'test_core.py',TEST_SHA256)
    module=types.ModuleType('_ledger_linux_tests'); module.__file__=str(here/'test_core.py')
    exec(compile(tests,str(here/'test_core.py'),'exec'),module.__dict__)
    def load_core():
        value=types.ModuleType('_ledger_linux_core'); value.__file__=str(here/'core.py')
        exec(compile(core,str(here/'core.py'),'exec'),value.__dict__)
        return value
    module.load_core=load_core
    return module


@contextmanager
def fixture(tests):
    with tempfile.TemporaryDirectory(prefix='naver-ledger-qualification-',dir='/run') as base:
        os.chmod(base,0o700)
        value=tests.Fixture(base,strict_root=True)
        try: yield value
        finally: value.close()


def run():
    checks=dict.fromkeys(CHECKS,False)
    result=dict(version=1,status='failed',stage='host_gate',core_sha256=CORE_SHA256,
                test_sha256=TEST_SHA256,checks=checks,operating_observed=False,
                systemd_called=False,database_opened=False)
    try:
        require(sys.argv[1:]==['--confirm',CONFIRM])
        require(sys.platform=='linux' and os.geteuid()==0 and os.getegid()==0)
        require(os.environ.get('GITHUB_ACTIONS')=='true')
        require(os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted')
        require(os.environ.get('RUNNER_OS')=='Linux')
        tests=load_test()
        result['stage']=CHECKS[0]
        with fixture(tests) as f:
            value=f.observe()
            require(value['status']=='observed' and value['rollback_done'] is True)
            require(f.root.stat().st_uid==0 and f.root.stat().st_gid==0)
            require(f.C._ancestor.__module__=='_ledger_linux_core')
        checks[CHECKS[0]]=True

        result['stage']=CHECKS[1]
        with fixture(tests) as f:
            before=f.inventory(); original=os.open
            def opening(path,flags,*args,**kwargs):
                require(flags & os.O_ACCMODE == os.O_RDONLY)
                require(not bool(flags & (os.O_CREAT|os.O_TRUNC|os.O_APPEND)))
                return original(path,flags,*args,**kwargs)
            with tests.ExitStack() as stack:
                stack.enter_context(mock.patch.object(os,'open',side_effect=opening))
                for name in ('write','fsync','mkdir','unlink','rename','link','chmod','fchmod'):
                    stack.enter_context(mock.patch.object(os,name,side_effect=RuntimeError('write_forbidden')))
                require(f.observe()['status']=='observed')
            require(f.inventory()==before)
        checks[CHECKS[1]]=True

        result['stage']=CHECKS[2]
        with fixture(tests) as f, tests.flock_peers(f.root/'transition.lock') as check:
            original=f.C._project
            def locked(*args):
                check(); return original(*args)
            with mock.patch.object(f.C,'_project',side_effect=locked): require(f.observe()['status']=='observed')
        checks[CHECKS[2]]=True

        result['stage']=CHECKS[3]
        with fixture(tests) as f:
            path=f.root/'transition.lock'; path.unlink()
            require(f.observe()['refusal']=='lock_missing')
            f.write(path,b'x'); require(f.observe()['refusal']=='lock_invalid')
            path.unlink(); path.symlink_to(f.folder/'plan.json')
            require(f.observe()['refusal']=='lock_invalid')
        checks[CHECKS[3]]=True

        result['stage']=CHECKS[4]
        with fixture(tests) as f:
            original=fcntl.flock
            def replacement(fd,flags):
                path=f.root/'transition.lock'; path.unlink(); f.write(path,b'')
                return original(fd,flags)
            with mock.patch.object(fcntl,'flock',side_effect=replacement):
                require(f.observe()['refusal']=='context_changed')
        checks[CHECKS[4]]=True

        result['stage']=CHECKS[5]
        with fixture(tests) as f:
            original=f.C._project
            def replacement(*args):
                value=original(*args)
                old=f.root/f.C.APPLY
                old.rename(f.root/'retained-old-folder'); old.mkdir(mode=0o700)
                return value
            with mock.patch.object(f.C,'_project',side_effect=replacement):
                require(f.observe()['refusal']=='context_changed')
        checks[CHECKS[5]]=True

        result['stage']=CHECKS[6]
        with fixture(tests) as f:
            peer=f.folder/('.pending-'+'a'*32)
            os.link(f.folder/'000002.json',peer)
            require(f.observe()['status']=='observed')
            peer.rename(f.root/'wrong-peer')
            require(f.observe()['refusal']=='ledger_rejected')
        checks[CHECKS[6]]=True

        result['stage']=CHECKS[7]
        with fixture(tests) as f:
            for step,state in [('run_once','intent'),('run_once','done'),('observe','intent'),('observe','done')]:
                f.history(f.apply_prefix(step,state,restored=True)); value=f.observe()
                require(value['status']=='observed' and value['rollback_done'] is True)
                require(value['last_apply_step']==step and value['last_apply_step_state']==state)
                require(value['run_once_intent'] is True)
        checks[CHECKS[7]]=True

        result['stage']=CHECKS[8]
        with fixture(tests) as f:
            path=f.folder/'000002.json'; raw=path.read_bytes()
            f.write(path,raw.replace(b'timer_stop',b'timer_bad_'))
            require(f.observe()['refusal']=='ledger_rejected')
        checks[CHECKS[8]]=True

        result['stage']=CHECKS[9]
        with fixture(tests) as f:
            before=set(os.listdir('/proc/self/fd'))
            with mock.patch.object(f.C,'MAX_READ',32768): require(f.observe()['refusal']=='read_budget')
            with mock.patch.object(f.C,'SECONDS',0.02),mock.patch.object(f.C,'_read',side_effect=lambda *a:time.sleep(0.1)):
                require(f.observe()['refusal']=='deadline')
            require(signal.getitimer(signal.ITIMER_REAL)==(0.0,0.0))
            require(set(os.listdir('/proc/self/fd'))==before)
            original_close=os.close; injected=[]
            def closing(fd):
                is_directory=stat.S_ISDIR(os.fstat(fd).st_mode)
                original_close(fd)
                if is_directory and not injected:
                    injected.append(True); signal.raise_signal(signal.SIGALRM)
            with mock.patch.object(os,'close',side_effect=closing):
                require(f.observe()['refusal']=='deadline')
            require(injected==[True] and set(os.listdir('/proc/self/fd'))==before)
            original_open=os.open; injected=[]
            def opening(path,*args,**kwargs):
                fd=original_open(path,*args,**kwargs)
                if str(path).endswith('plan.json') and not injected:
                    injected.append(True); signal.raise_signal(signal.SIGALRM)
                return fd
            with mock.patch.object(os,'open',side_effect=opening):
                require(f.observe()['refusal']=='deadline')
            require(injected==[True] and set(os.listdir('/proc/self/fd'))==before)
        checks[CHECKS[9]]=True
        result.update(status='passed',stage='complete')
    except Exception:
        pass
    return result


if __name__=='__main__':
    result=run()
    print(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False))
    raise SystemExit(0 if result['status']=='passed' else 1)
