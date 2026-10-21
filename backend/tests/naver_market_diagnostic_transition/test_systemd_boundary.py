"""New boundary tests: fixed command seam and local Python subprocesses only."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import systemd_boundary as S
import transition as T
import test_transition as fixture


def state(unit, **changes):
    value = dict(LoadState='loaded', UnitFileState='static', FragmentPath=T.UNIT_ROOT+'/'+unit,
        DropInPaths='', Job='', Result='success', ExecMainStatus='0',
        ActiveState='inactive', SubState='dead', InvocationID='')
    if unit == T.OLD_TIMER: del value['ExecMainStatus']
    value.update(changes)
    return value


def encode(value, *, kind='service'):
    assert type(kind) is str and kind in ('service', 'timer')
    properties = S.TIMER_PROPERTIES if kind == 'timer' else S.PROPERTIES
    assert set(value) == set(properties)
    return ('\n'.join(k+'='+value[k] for k in properties)+'\n').encode('ascii')


def row(message,unit='fixed-reader.service',invocation='a'*32,**changes):
    value=dict(_SYSTEMD_UNIT=unit,_SYSTEMD_INVOCATION_ID=invocation,MESSAGE=message)
    value.update(changes)
    return json.dumps(value,separators=(',',':'),ensure_ascii=True).encode()


def result(issue='rows',**changes):
    value=dict(status='failed',code='SOURCE_LIMIT',limit_issue=issue)
    value.update(changes)
    return json.dumps(value,separators=(',',':'))


class Commands:
    def __init__(self,plan):
        self.plan=plan;self.calls=[];self.start_error=None;self.start_code=1;self.on_journal=None
        self.snapshots={u:state(u) for u in (T.OLD_COORDINATOR,T.OLD_READER,T.OLD_TIMER,
                                           plan['coordinator'],plan['reader'])}
        self.snapshots[T.OLD_TIMER].update(UnitFileState='enabled',ActiveState='active',SubState='waiting')
        self.unit_path=('UnitPath=/etc/systemd/system.control '+S.MASK_ROOT+' '+T.UNIT_ROOT+
                        ' /run/systemd/system /usr/lib/systemd/system\n').encode()
        self.journal=b''

    def __call__(self,argv,*,limit,timeout):
        self.calls.append((list(argv),limit,timeout))
        if argv==['/usr/bin/systemctl','show','--property=UnitPath']:return 0,self.unit_path
        if argv[:2]==['/usr/bin/systemctl','show']:
            kind = 'timer' if argv[2] == T.OLD_TIMER else 'service'
            properties = S.TIMER_PROPERTIES if kind == 'timer' else S.PROPERTIES
            assert argv[3:]==['--property='+x for x in properties]
            return 0,encode(self.snapshots[argv[2]], kind=kind)
        if argv[0]=='/usr/bin/journalctl':
            if self.on_journal:self.on_journal()
            return 0,self.journal
        if argv==['/usr/bin/systemctl','start',self.plan['coordinator']]:
            if self.start_error:raise self.start_error
            return self.start_code,b''
        if argv==['/usr/bin/systemctl','stop',T.OLD_TIMER]:
            self.snapshots[T.OLD_TIMER].update(ActiveState='inactive',SubState='dead')
        if argv==['/usr/bin/systemctl','start',T.OLD_TIMER]:
            self.snapshots[T.OLD_TIMER].update(ActiveState='active',SubState='elapsed')
        return 0,b''

    def quiesce(self):
        self.snapshots[T.OLD_TIMER].update(ActiveState='inactive',SubState='dead')
        for unit in (T.OLD_COORDINATOR,T.OLD_READER):
            self.snapshots[unit].update(LoadState='masked',UnitFileState='masked-runtime',FragmentPath=S.MASK_ROOT+'/'+unit)


class BoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TransitionTests.setUpClass()
        cls.plan,cls.files,cls.sources=(fixture.TransitionTests.plan,fixture.TransitionTests.files,
                                       fixture.TransitionTests.sources)

    def setUp(self):
        self.command=Commands(self.plan)
        self.system=S.Systemd(self.plan,self.files,sources=self.sources,command=self.command)

    def observation(self,**changes):
        unit=self.plan['reader']
        self.command.snapshots[unit].update(Result='exit-code',ExecMainStatus='1',ActiveState='failed',
                                           SubState='failed',InvocationID='a'*32,**changes)
        self.command.journal=row(result(),unit)

    def test_plan_validation_and_exact_unit_command_shape(self):
        bad=copy.deepcopy(self.plan);bad['controller_start_attempts_max']=True
        with self.assertRaises(T.Invalid):S.Systemd(bad,self.files,sources=self.sources,command=self.command)
        with self.assertRaisesRegex(T.Invalid,'SYSTEMD_UNIT'):self.system.show('other.service')
        self.assertEqual(self.command.calls,[])
        self.system.show(T.OLD_READER)
        self.assertEqual(self.command.calls,[(['/usr/bin/systemctl','show',T.OLD_READER]+
            ['--property='+x for x in S.PROPERTIES],4096,8)])

    def test_snapshot_exact_properties_numeric_status_and_invocation(self):
        raw=encode(state(T.OLD_READER))
        variants=[raw+b'Job=\n',raw.replace(b'Job=\n',b''),raw+b'Unknown=secret\n',b'x'*4097,b'\xff',
                  raw.replace(b'ExecMainStatus=0',b'ExecMainStatus=True'),
                  raw.replace(b'ExecMainStatus=0',b'ExecMainStatus=256'),
                  raw.replace(b'ExecMainStatus=0',b'ExecMainStatus=-1'),
                  raw.replace(b'InvocationID=',b'InvocationID=not-hex')]
        for value in variants:
            with self.subTest(value=value[:20]),self.assertRaises(T.Invalid):S.snapshot(value)
        for invocation in ('','0'*32,'a'*32):
            self.assertEqual(S.snapshot(encode(state(T.OLD_READER,InvocationID=invocation)))['InvocationID'],invocation)

    def test_mask_root_must_precede_etc_in_actual_manager_path(self):
        self.assertEqual(self.system.mask_search_path(),S.MASK_ROOT)
        for raw in (b'UnitPath=/etc/systemd/system /run/systemd/system.control\n',
                    b'UnitPath=/run/systemd/system /etc/systemd/system\n',
                    b'UnitPath=/run/systemd/system.control /etc/systemd/system /etc/systemd/system\n',
                    b'UnitPath=/run/systemd/system.control /etc/systemd/system',
                    b'UnitPath=/run/systemd/system.control relative /etc/systemd/system\n',
                    b'UnitPath=/run/systemd/system.control /etc/systemd/system \\bad\n',b'\xff\n'):
            self.command.unit_path=raw
            with self.assertRaisesRegex(T.Invalid,'SYSTEMD_UNIT_PATH'):self.system.mask_search_path()
        self.assertFalse(any(c[0][1]=='stop' for c in self.command.calls))

    def test_original_preflight_rejects_active_jobs_dropins_masks_and_wrong_fragment(self):
        self.assertTrue(self.system.original_preflight())
        original=copy.deepcopy(self.command.snapshots)
        cases=[(T.OLD_TIMER,dict(UnitFileState='disabled')),(T.OLD_TIMER,dict(Job='42')),
               (T.OLD_TIMER,dict(DropInPaths='/private/dropin')),(T.OLD_READER,dict(Job='42')),
               (T.OLD_READER,dict(ActiveState='active',SubState='running')),
               (T.OLD_COORDINATOR,dict(DropInPaths='/private/dropin')),
               (T.OLD_COORDINATOR,dict(LoadState='masked',FragmentPath='/dev/null')),
               (T.OLD_READER,dict(FragmentPath='/run/systemd/system/x.service'))]
        for unit,changes in cases:
            self.command.snapshots=copy.deepcopy(original);self.command.snapshots[unit].update(changes)
            with self.subTest(unit=unit,changes=changes),self.assertRaises(T.Invalid):self.system.original_preflight()

    def test_masked_and_new_idle_verify_expected_load_state_and_paths(self):
        self.command.quiesce();self.system.masked_idle();self.system.new_idle()
        original=copy.deepcopy(self.command.snapshots)
        for unit,changes,method in [(T.OLD_READER,dict(UnitFileState='masked'),self.system.masked_idle),
                (T.OLD_COORDINATOR,dict(FragmentPath=T.UNIT_ROOT+'/'+T.OLD_COORDINATOR),self.system.masked_idle),
                (T.OLD_READER,dict(Job='8'),self.system.masked_idle),
                (self.plan['reader'],dict(DropInPaths='/dropin'),self.system.new_idle),
                (self.plan['coordinator'],dict(ActiveState='activating',SubState='start'),self.system.new_idle)]:
            self.command.snapshots=copy.deepcopy(original);self.command.snapshots[unit].update(changes)
            with self.assertRaises(T.Invalid):method()

    def test_ambiguous_or_interrupted_start_consumes_memory_attempt(self):
        for error in (T.Invalid('SYSTEMD_COMMAND_AMBIGUOUS'),KeyboardInterrupt('test interruption')):
            command=Commands(self.plan);command.quiesce();command.start_error=error
            system=S.Systemd(self.plan,self.files,sources=self.sources,command=command)
            with self.assertRaises(BaseException):system.start_once()
            count=len(command.calls)
            with self.assertRaisesRegex(T.Invalid,'DIAGNOSTIC_START_REPLAY'):system.start_once()
            self.assertEqual(len(command.calls),count)
            self.assertEqual(sum(c[0]==['/usr/bin/systemctl','start',self.plan['coordinator']] for c in command.calls),1)

    def test_cleanup_idle_checks_both_partial_units_and_accepts_only_idle_missing(self):
        units=[self.plan['coordinator'],self.plan['reader']]
        for missing in (units[:1],units[1:],units):
            for missing_state in ('','not-found'):
                command=Commands(self.plan)
                for unit in missing:
                    command.snapshots[unit].update(LoadState='not-found',UnitFileState=missing_state,
                        FragmentPath='')
                system=S.Systemd(self.plan,self.files,sources=self.sources,command=command)
                system.cleanup_idle()
                self.assertEqual([call[0][2] for call in command.calls],units)
                self.assertTrue(all(call[0][:2]==['/usr/bin/systemctl','show'] for call in command.calls))
        self.system.cleanup_idle()
        self.assertEqual([call[0][2] for call in self.command.calls],units)

    def test_cleanup_idle_refuses_cached_activity_jobs_dropins_and_unowned_fragments(self):
        units=[self.plan['coordinator'],self.plan['reader']]
        missing=dict(LoadState='not-found',UnitFileState='',FragmentPath='')
        variants=[dict(ActiveState='active',SubState='running'),dict(Job='42'),
                  dict(DropInPaths='/unowned/dropin'),dict(FragmentPath='/unowned/unit'),
                  dict(UnitFileState='static'),dict(ActiveState='activating',SubState='start')]
        for unit in units:
            for changes in variants:
                command=Commands(self.plan);command.snapshots[unit].update(missing)
                command.snapshots[unit].update(changes)
                system=S.Systemd(self.plan,self.files,sources=self.sources,command=command)
                with self.subTest(unit=unit,changes=changes),self.assertRaisesRegex(T.Invalid,'DIAGNOSTIC_NOT_IDLE'):
                    system.cleanup_idle()
                self.assertTrue(all(call[0][:2]==['/usr/bin/systemctl','show'] for call in command.calls))
            for changes in (dict(ActiveState='active',SubState='running'),dict(Job='42'),
                    dict(DropInPaths='/unowned/dropin'),dict(FragmentPath='/unowned/unit'),
                    dict(UnitFileState='enabled'),dict(LoadState='masked')):
                command=Commands(self.plan);command.snapshots[unit].update(changes)
                system=S.Systemd(self.plan,self.files,sources=self.sources,command=command)
                with self.assertRaisesRegex(T.Invalid,'DIAGNOSTIC_NOT_IDLE'):system.cleanup_idle()

    def test_existing_invocation_refused_and_exit_one_is_not_retried(self):
        self.command.quiesce();self.command.snapshots[self.plan['reader']]['InvocationID']='a'*32
        with self.assertRaisesRegex(T.Invalid,'DIAGNOSTIC_ALREADY_RAN'):self.system.start_once()
        self.assertFalse(self.system.start_attempted)
        self.command.snapshots[self.plan['reader']]['InvocationID']=''
        self.system.start_once()
        self.assertTrue(self.system.start_attempted)
        with self.assertRaisesRegex(T.Invalid,'DIAGNOSTIC_START_REPLAY'):self.system.start_once()

    def test_exact_source_limit_six_enums_and_historical_two_key(self):
        for issue in T.ISSUES:
            self.assertEqual(S.exact_failure(row(result(issue)),unit='fixed-reader.service',invocation='a'*32),issue)
        historical='{"status":"failed","code":"SOURCE_LIMIT"}'
        self.assertEqual(S.exact_failure(row(historical),unit='fixed-reader.service',invocation='a'*32),'unknown')

    def test_malformed_source_limit_json_never_falls_back_to_reason(self):
        messages=[result(True),result(None),result(1),result('unlisted'),result(extra='private'),
                  result(status=True),result(status='ok'),
                  '{"status":"failed","code":"SOURCE_LIMIT","limit_issue":"rows","limit_issue":"time"}',
                  '{"status":"failed","code":"SOURCE_LIMIT","limit_issue":NaN}',
                  '{"status":"failed","code":"SOURCE_LIMIT","limit_issue":Infinity}',
                  '{"status":"failed","code":"SOURCE_LIMIT",}']
        for message in messages:
            with self.subTest(message=message),self.assertRaises(T.Invalid):
                S.exact_failure(row(message),unit='fixed-reader.service',invocation='a'*32)

    def test_journal_unit_invocation_shape_bounds_and_multiple_results(self):
        good=row(result())
        values=[row(result(),unit='wrong.service'),row(result(),invocation='b'*32),
                row(True),good+b'\n'+good,b'\n'.join(row('prose') for _ in range(33)),b'x'*32769,
                b'{"MESSAGE":"x","MESSAGE":"y"}',row('private\x00message')]
        for raw in values:
            with self.assertRaises(T.Invalid):S.exact_failure(raw,unit='fixed-reader.service',invocation='a'*32)
        with self.assertRaises(T.Invalid):S.exact_failure(good,unit='fixed-reader.service',invocation='0'*32)
        raw=b'\n'.join(row('prose') for _ in range(32))
        self.assertIsNone(S.exact_failure(raw,unit='fixed-reader.service',invocation='a'*32))

    def test_unrelated_prose_and_other_error_json_are_not_source_limit(self):
        raw=b'\n'.join([row('private prose SOURCE_LIMIT'),row('{"status":"failed","code":"SOURCE_READ"}'),
                        row('{"status":"ok","rows":1}')])
        self.assertIsNone(S.exact_failure(raw,unit='fixed-reader.service',invocation='a'*32))

    def test_observe_binds_exact_invocation_and_before_after_all_properties(self):
        self.observation();observed=self.system.observe()
        self.assertEqual(observed['status'],'source_limit');self.assertEqual(observed['limit_issue'],'rows')
        expected=['/usr/bin/journalctl','--output=json','--no-pager','-n','32',
            '_SYSTEMD_UNIT='+self.plan['reader'],'_SYSTEMD_INVOCATION_ID='+'a'*32]
        self.assertIn((expected,32768,8),self.command.calls)
        for change in (dict(InvocationID='b'*32),dict(Job='9'),dict(ExecMainStatus='2'),dict(DropInPaths='/changed')):
            self.command=Commands(self.plan);self.system=S.Systemd(self.plan,self.files,sources=self.sources,command=self.command)
            self.observation();self.command.on_journal=lambda v=change:self.command.snapshots[self.plan['reader']].update(v)
            with self.assertRaisesRegex(T.Invalid,'DIAGNOSTIC_CONTEXT_CHANGED'):self.system.observe()

    def test_unit_success_cannot_certify_bundle_and_missing_reason_stays_unavailable(self):
        self.command.snapshots[self.plan['reader']].update(InvocationID='a'*32)
        observed=self.system.observe()
        self.assertEqual(observed['status'],'diagnostic_unavailable');self.assertIsNone(observed['limit_issue'])
        self.observation();self.command.journal=row('private generic failure',self.plan['reader'])
        observed=self.system.observe()
        self.assertEqual(observed['status'],'diagnostic_unavailable');self.assertIsNone(observed['limit_issue'])
        self.assertNotIn('bundle',observed)

    def test_timer_restore_allows_natural_catchup_without_starting_old_service(self):
        self.command.snapshots[T.OLD_COORDINATOR].update(ActiveState='active',SubState='running',Job='7')
        self.system.timer_restore()
        self.assertEqual([x[0] for x in self.command.calls],[['/usr/bin/systemctl','start',T.OLD_TIMER],
            ['/usr/bin/systemctl','show',T.OLD_TIMER]+['--property='+p for p in S.TIMER_PROPERTIES]])

    def test_fixed_verify_reload_stop_commands_and_return_shape(self):
        self.system.verify_units();self.system.reload();self.system.timer_stop()
        self.assertIn((['/usr/bin/systemd-analyze','verify',T.UNIT_ROOT+'/'+self.plan['coordinator'],
                       T.UNIT_ROOT+'/'+self.plan['reader']],4096,15),self.command.calls)
        for code,body in [(True,b''),(256,b''),(0,'text'),(0,b'x'*4097)]:
            with patch.object(self.system,'command',return_value=(code,body)),self.assertRaises(T.Invalid):
                self.system.reload()


class BoundedProcessTests(unittest.TestCase):
    def command(self,code,root):
        path=Path(root)/'fixture.py';path.write_text(code)
        return [sys.executable,'-I','-B',str(path)]

    def test_real_python_stdout_stderr_exit_and_environment_are_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            argv=self.command('import os,sys\nassert os.environ.get("PRIVATE_PARENT_VALUE") is None\nsys.stderr.write("private stderr")\nsys.stdout.write("fixed")\nsys.exit(7)\n',root)
            with patch.dict(os.environ,{'PRIVATE_PARENT_VALUE':'do-not-inherit'}):
                self.assertEqual(S.bounded(argv,limit=5,timeout=2),(7,b'fixed'))
            argv=self.command('import sys\nsys.stdout.write("x"*9)\n',root)
            with self.assertRaisesRegex(T.Invalid,'SYSTEMD_COMMAND_LIMIT'):S.bounded(argv,limit=8,timeout=2)

    def test_real_python_timeout_is_ambiguous_and_returns_no_partial_output(self):
        with tempfile.TemporaryDirectory() as root:
            argv=self.command('import sys,time\nsys.stdout.write("partial");sys.stdout.flush()\ntime.sleep(10)\n',root)
            with self.assertRaises(T.Invalid) as error:S.bounded(argv,limit=32,timeout=1)
            self.assertEqual(error.exception.args,('SYSTEMD_COMMAND_AMBIGUOUS',))

    def test_invalid_bounds_fail_before_spawning_any_process(self):
        for argv,limit,timeout in [([],1,1),(['ignored'],True,1),(['ignored'],0,1),
                                 (['ignored'],32769,1),(['ignored'],1,True),(['ignored'],1,76)]:
            with patch.object(S.subprocess,'Popen') as spawn,self.assertRaisesRegex(T.Invalid,'SYSTEMD_COMMAND'):
                S.bounded(argv,limit=limit,timeout=timeout)
            spawn.assert_not_called()


if __name__=='__main__':unittest.main()
