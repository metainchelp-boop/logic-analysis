#!/usr/bin/env python3
"""Read-only pre-write snapshot diagnosis. No archive sink or send/unpause API."""
import contextlib
import hashlib
import json
import os
import re
import resource
import signal
import stat
import sys
import tempfile
import time
import types

SESSION='data-snapshot-20261102-v1'
REQUEST={'ad':{'id':'6f37ec7da0dea75b4630fd177ff0f51ae0087e6b310d68df5a6e6803c015890f','pid':1679637},'content':{'id':'740ea62adf12d41571a1297ea4bb623ca62177f1c4def4d2c290f7b5ee07c9b5','pid':1669091}}
PINS={'retirement_data_preflight.py':'562582ebf91b82c84f6a728bd2fd2afd9a7cc59d8346deb40b110c20578fec8c','retirement_data_archive.py':'034e27f27aec4b0bd183ac23570816b7a9841808621693f3a1224cf5ae12b642','retirement_data_source.py':'47916b99bbbd9312a4d971efbe83f278f2c013984b2fa89b62c9104b34aed693'}
STAGES=('dependencies','frozen_initial','coverage','frozen_repeat','pin_base','inventory','deleted','mapping','configuration','frozen_final','complete')
# Filled from the reviewed public modules at development time; never exception text.
ERRORS=('archive_failed', 'archive_incomplete', 'archive_size_limit', 'archive_timeout', 'arguments_refused', 'asset_invalid', 'assets_refused', 'async_io_uncovered', 'attempt_exists', 'attempt_not_terminal', 'autobid_container_present', 'candidate_uncovered', 'cgroup_tasks_changed', 'cgroup_unconfirmed', 'cipher_limit', 'cleanup_unconfirmed', 'command_failed', 'command_limit', 'configuration_changed', 'configuration_limit', 'configuration_missing', 'configuration_unconfirmed', 'container_changed', 'content_changed', 'controls_changed', 'coverage_incomplete', 'cwd_unconfirmed', 'daemon_unverified', 'data_size_limit', 'database_driver_or_path_uncovered', 'database_path_uncovered', 'db_config_ambiguous', 'deadline_exceeded', 'deleted_changed', 'deleted_limit', 'deleted_ref_limit', 'deleted_uncovered', 'dependency_failed', 'depth_limit', 'direct_io_uncovered', 'directory_changed', 'encrypted_pipe_failed', 'encrypted_pipe_required', 'entry_limit', 'fd_changed', 'fd_limit', 'fd_metadata_invalid', 'fd_set_changed', 'file_changed', 'file_count_limit', 'file_exists', 'file_too_large', 'filesystem_boundary', 'final_guard_changed', 'freeze_changed', 'hardlink_unresolved', 'internal_failure', 'interrupted', 'invalid_metadata', 'invalid_phase', 'link_or_special_uncovered', 'lock_busy', 'manifest_size_limit', 'mapping_changed', 'mapping_unpinned', 'maps_changed', 'maps_invalid', 'module_refused', 'mount_identity_mismatch', 'mount_unconfirmed', 'mount_uncovered', 'name_uncovered', 'namespace_changed', 'nested_cgroup_uncovered', 'not_frozen', 'not_prepared', 'operation_failed', 'operator_evidence_refused', 'path_changed', 'path_uncovered', 'pause_failed', 'pid_limit', 'pid_visibility_incomplete', 'pid_visibility_limit', 'pipe_failed', 'pipeline_failed', 'policy_unresolved', 'preflight_contract_refused', 'privilege_or_platform_refused', 'privilege_required', 'process_changed', 'process_identity_invalid', 'public_key_invalid', 'read_limit', 'receipt_invalid', 'recipient_invalid', 'regular_file_uncovered', 'relevant_file_changed', 'relevant_process_changed', 'request_refused', 'restart_evidence_unconfirmed', 'session_closed', 'session_exists', 'source_unreviewed', 'space_insufficient', 'thread_set_unconfirmed', 'time_limit', 'tree_changed', 'unsafe_directory', 'unsafe_file', 'unsafe_path', 'volume_uncovered', 'worker_changed', 'workers_unconfirmed', 'writers_unresolved')
class Refused(Exception):
    def __init__(self,code):self.code=code

def stamp(v):return v.st_dev,v.st_ino,v.st_mode,v.st_uid,v.st_gid,v.st_nlink,v.st_size,v.st_mtime_ns,v.st_ctime_ns

def load_modules(directory,run):
    if re.fullmatch('[1-9][0-9]{0,19}-1',run) is None or directory!='/tmp/metainc-data-diagnostic-'+run:raise Refused('assets_refused')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    with contextlib.ExitStack() as stack:
        top=os.open('/tmp',flags);stack.callback(os.close,top)
        info=os.fstat(top)
        if info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=0o1777:raise Refused('assets_refused')
        leaf=directory.rsplit('/',1)[1];folder=os.open(leaf,flags,dir_fd=top);stack.callback(os.close,folder);before=os.fstat(folder)
        if before.st_uid!=0 or before.st_gid!=0 or stat.S_IMODE(before.st_mode)!=0o700:raise Refused('assets_refused')
        out={}
        for name,pin in PINS.items():
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=folder);stack.callback(os.close,fd)
            initial=os.fstat(fd)
            if not stat.S_ISREG(initial.st_mode) or initial.st_uid!=0 or initial.st_gid!=0 or initial.st_nlink!=1 or stat.S_IMODE(initial.st_mode)!=0o600 or not 0<initial.st_size<=262144:raise Refused('assets_refused')
            body=bytearray()
            while True:
                block=os.read(fd,65536)
                if not block:break
                body.extend(block)
                if len(body)>262144:raise Refused('assets_refused')
            if stamp(os.fstat(fd))!=stamp(initial) or stamp(os.stat(name,dir_fd=folder,follow_symlinks=False))!=stamp(initial) or hashlib.sha256(body).hexdigest()!=pin:raise Refused('assets_refused')
            module=types.ModuleType('_diagnostic_'+pin);module.__file__=directory+'/'+name
            exec(compile(bytes(body),module.__file__,'exec'),module.__dict__);out[name]=module
        linked=os.stat(leaf,dir_fd=top,follow_symlinks=False)
        if stamp(linked)[:5]!=stamp(before)[:5] or stamp(os.fstat(folder))[:5]!=stamp(before)[:5]:raise Refused('assets_refused')
        return out

def diagnose(archive,preflight,source,docker,*,end=None):
    report={'schema':'metainc-data-diagnostic-v1','session':SESSION,'status':'blocked','stage':'dependencies','error':None,'read_only':True,'archive_written':False,'state_changed':False,'cleanup_confirmed':False,'entry_count':0,'file_count':0,'deleted_count':0,'configuration_count':0,'configuration_absent_count':0}
    snapshot=None;child_cleanup_uncertain=False
    def stage(name,call):report['stage']=name;return call()
    try:
        snapshot=archive.Snapshot(preflight,REQUEST,docker=docker,end=end,restart_evidence=source.RESTART_EVIDENCE)
        snapshot.guard=stage('frozen_initial',snapshot.frozen)
        snapshot.report,snapshot.private=stage('coverage',snapshot.observe)
        if stage('frozen_repeat',snapshot.frozen)!=snapshot.guard:raise Refused('freeze_changed')
        def bases():
            snapshot.bases['content_tmp']=snapshot.stack.enter_context(snapshot.proc.root_fd(REQUEST['content']['pid']))
            for scope in archive.DATA_SCOPES:
                snapshot.stack.enter_context(snapshot.files.directory('/tmp' if scope=='content_tmp' else archive.ROOTS[scope],snapshot.bases.get(scope),secure=scope!='content_tmp'))
        stage('pin_base',bases)
        snapshot.entries=stage('inventory',snapshot.inventory)
        report.update(entry_count=len(snapshot.entries),file_count=sum(row['kind']=='file' for row in snapshot.entries))
        stage('deleted',snapshot.pin_deleted);report['deleted_count']=len(snapshot.deleted)
        stage('mapping',snapshot.pin_mappings_and_check_io)
        snapshot.recovery,snapshot.recovery_absent,snapshot.config_parent_guards=stage('configuration',snapshot.configuration)
        report.update(configuration_count=len(snapshot.recovery),configuration_absent_count=len(snapshot.recovery_absent))
        if stage('frozen_final',snapshot.frozen)!=snapshot.guard:raise Refused('freeze_changed')
        report.update(status='diagnosed',stage='complete')
    except BaseException as error:
        reason=getattr(error,'code',None)
        child_cleanup_uncertain=reason=='attempt_not_terminal'
        report['error']=reason if isinstance(reason,str) and reason in ERRORS else 'operation_failed'
    finally:
        signals=(signal.SIGINT,signal.SIGTERM,signal.SIGHUP,signal.SIGALRM)
        mask=signal.pthread_sigmask(signal.SIG_BLOCK,signals);old={}
        try:
            for number in signals:old[number]=signal.signal(number,signal.SIG_IGN)
        finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
        try:
            if snapshot is not None:snapshot.stack.close()
            report['cleanup_confirmed']=not child_cleanup_uncertain
        except BaseException:
            report.update(status='blocked',error='cleanup_unconfirmed')
        finally:
            mask=signal.pthread_sigmask(signal.SIG_BLOCK,signals)
            try:
                for number,handler in old.items():signal.signal(number,handler)
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
    return report

def main():
    report=None
    try:
        if os.geteuid()!=0 or sys.platform!='linux' or len(sys.argv)!=2:raise Refused('arguments_refused')
        resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
        for number in (signal.SIGINT,signal.SIGHUP,signal.SIGTERM,signal.SIGALRM):signal.signal(number,lambda *_:(_ for _ in ()).throw(Refused('interrupted')))
        signal.setitimer(signal.ITIMER_REAL,240)
        modules=load_modules(os.path.dirname(os.path.abspath(__file__)),sys.argv[1])
        preflight,archive,source=(modules['retirement_data_'+name+'.py'] for name in ('preflight','archive','source'))
        end=time.monotonic()+220
        with tempfile.TemporaryDirectory(prefix='metainc-data-diag-docker-',dir='/tmp') as config:
            def run(args):
                return source.command(['/usr/bin/docker','--host','unix:///var/run/docker.sock','--config',config,*args],limit=131072,timeout=min(20,max(.01,end-time.monotonic())))
            report=diagnose(archive,preflight,source,preflight.Docker(end,runner=run),end=end)
    except BaseException as error:
        code=getattr(error,'code',None)
        report={'schema':'metainc-data-diagnostic-v1','session':SESSION,'status':'blocked','stage':'dependencies','error':code if code in ERRORS else 'operation_failed','read_only':True,'archive_written':False,'state_changed':False,'cleanup_confirmed':False,'entry_count':0,'file_count':0,'deleted_count':0,'configuration_count':0,'configuration_absent_count':0}
    finally:signal.setitimer(signal.ITIMER_REAL,0)
    print(json.dumps(report,sort_keys=True,separators=(',',':')));return 0 if report['status']=='diagnosed' else 2
if __name__=='__main__':sys.exit(main())
