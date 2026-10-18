"""Exact unit-kind schema from new Linux evidence; no systemctl execution."""
import json
import unittest
from unittest.mock import patch
import transition as T
import systemd_boundary as S
import current_guard as G
import test_transition as fixture


def value(unit, *, timer=False, masked=False):
    result = dict(LoadState='masked' if masked else 'loaded',
        UnitFileState='masked-runtime' if masked else ('enabled' if timer else 'static'),
        FragmentPath=(S.MASK_ROOT if masked else T.UNIT_ROOT)+'/'+unit,
        DropInPaths='', Job='', Result='success', ExecMainStatus='0',
        ActiveState='inactive', SubState='dead', InvocationID='')
    if timer: del result['ExecMainStatus']
    return result


def raw(result):
    return ''.join(k+'='+v+'\n' for k,v in result.items()).encode()


class SchemaDelta(unittest.TestCase):
    def test_timer_exact_nine_keys_preserved_without_invented_status(self):
        current=value(T.OLD_TIMER,timer=True)
        for state in ('loaded','not-found','masked'):
            row=dict(current,LoadState=state)
            self.assertEqual(S.snapshot(raw(row),kind='timer'),row)
            self.assertNotIn('ExecMainStatus',S.snapshot(raw(row),kind='timer'))

    def test_timer_missing_other_or_extra_service_key_refused(self):
        current=value(T.OLD_TIMER,timer=True)
        for key in current:
            row=dict(current);del row[key]
            with self.assertRaisesRegex(T.Invalid,'SYSTEMD_SNAPSHOT'):
                S.snapshot(raw(row),kind='timer')
        with self.assertRaisesRegex(T.Invalid,'SYSTEMD_SNAPSHOT'):
            S.snapshot(raw(dict(current,ExecMainStatus='0')),kind='timer')

    def test_service_status_remains_mandatory_and_bounded(self):
        row=value(T.OLD_READER)
        for bad in ('','-1','256','01','true'):
            with self.assertRaisesRegex(T.Invalid,'SYSTEMD_SNAPSHOT'):
                S.snapshot(raw(dict(row,ExecMainStatus=bad)))
        del row['ExecMainStatus']
        with self.assertRaisesRegex(T.Invalid,'SYSTEMD_SNAPSHOT'):S.snapshot(raw(row))

    def test_kind_is_explicit_and_strict_not_inferred_from_response(self):
        for kind in (True,1,None,'Timer','auto'):
            with self.assertRaisesRegex(T.Invalid,'SYSTEMD_SNAPSHOT'):
                S.snapshot(raw(value(T.OLD_READER)),kind=kind)
        with self.assertRaisesRegex(T.Invalid,'SYSTEMD_SNAPSHOT'):
            S.snapshot(raw(value(T.OLD_TIMER,timer=True)))

    def system(self):
        sources=fixture.sources();previous={k:'a'*64 for k in T.PROOF_KEYS}
        plan,files=T.compile_plan(apply_id='a'*32,rollback_id='b'*32,sources=sources,previous=previous)
        self.calls=[]
        def command(argv,**bounds):
            self.calls.append(argv)
            unit=argv[2]
            row=value(unit,timer=unit==T.OLD_TIMER,masked=unit in (T.OLD_READER,T.OLD_COORDINATOR))
            return 0,raw(row)
        return S.Systemd(plan,files,sources=sources,command=command)

    def test_show_only_fixed_old_timer_uses_nine_properties(self):
        system=self.system()
        self.assertNotIn('ExecMainStatus',system.show(T.OLD_TIMER))
        self.assertNotIn('--property=ExecMainStatus',self.calls[-1])
        self.assertIn('ExecMainStatus',system.show(T.OLD_READER))
        self.assertIn('--property=ExecMainStatus',self.calls[-1])

    def test_mask_requires_exact_owned_control_unit_path(self):
        system=self.system();system.masked_idle()
        original=system.show
        for path in ('/dev/null',T.UNIT_ROOT+'/'+T.OLD_READER,S.MASK_ROOT+'/other.service'):
            def show(unit):
                row=original(unit)
                if unit==T.OLD_READER:row['FragmentPath']=path
                return row
            with patch.object(system,'show',side_effect=show):
                with self.assertRaisesRegex(T.Invalid,'ORIGINAL_NOT_MASKED_IDLE'):system.masked_idle()

    def test_current_masked_failure_binds_owned_path_and_existing_invocation(self):
        guard=G.CurrentGuard({k:'a'*64 for k in T.PROOF_KEYS})
        invocation='d'*32
        row=value(T.OLD_READER,masked=True)
        journal=json.dumps(dict(_SYSTEMD_UNIT=T.OLD_READER,_SYSTEMD_INVOCATION_ID=invocation,
            MESSAGE=json.dumps(dict(status='failed',code='SOURCE_LIMIT')))).encode()+b'\n'
        with patch.object(guard,'_reader',return_value=row),patch.object(guard,'_run',return_value=journal):
            self.assertEqual(guard._failure(invocation),invocation)
        for change in (dict(FragmentPath='/dev/null'),dict(FragmentPath=S.MASK_ROOT+'/other.service'),
                       dict(InvocationID='e'*32),dict(DropInPaths='/other'),dict(UnitFileState='masked')):
            with patch.object(guard,'_reader',return_value=dict(row,**change)),patch.object(guard,'_run') as call:
                with self.assertRaises(T.Invalid):guard._failure(invocation)
                call.assert_not_called()


if __name__=='__main__':unittest.main()
