"""Only new invocation-bound market observation boundaries; no host access."""
import importlib.util
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

CORE = Path(__file__).resolve().with_name('inspect_export_binding.py')
if not CORE.is_file():
    CORE = Path(__file__).resolve().parents[1]/'tools/naver_export_binding_readonly.py'
SPEC = importlib.util.spec_from_file_location('market_observation_draft', CORE)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
INV = '1'*32
READER_INV = '2'*32


def snapshot(inv=INV, result='exit-code', status='1', active='failed', sub='failed'):
    return ('Result='+result+'\nExecMainStatus='+status+'\nActiveState='+active+
            '\nSubState='+sub+'\nInvocationID='+inv+'\n').encode()


def journal(role='market', inv=INV, message=None):
    if message is None:
        message = json.dumps({'status':'failed','code':'COORDINATION_READER_FAILED'})
    return json.dumps({'_SYSTEMD_UNIT':D.UNITS[role], '_SYSTEMD_INVOCATION_ID':inv,
                       'MESSAGE':message},separators=(',', ':')).encode()+b'\n'


class ExportInstallInvalid(ValueError):
    pass


def original_observation(component='market_result', fail=True, code='EXPORT_RUN_NOT_VERIFIED'):
    helper = types.SimpleNamespace(ExportInstallInvalid=ExportInstallInvalid)
    release = D.ReadOnlyRelease()
    class Binding:
        def __init__(self, *args):
            self.receipt = {}
            self.command = release.command
        def load(self, package, *, verify):
            assert verify is False
        def operation(self, callback):
            return callback()
    def verify(receipt, *, command):
        if fail:
            release.unit_results['market'] = False
            raise ExportInstallInvalid(code)
    helper.verify = verify
    sources = {key:b'public fixture' for key in D.SOURCE_PINS}
    with patch.object(D, '_failure_component', return_value=component):
        return D._observe(types.SimpleNamespace(Binding=Binding),helper,sources,release,lambda:True)


class MarketInvocationTests(unittest.TestCase):
    def test_original_failure_remains_false_and_extra_observation_requires_exact_branch(self):
        with patch.object(D, '_market_failure_observation', return_value={'closed':'fixture'}) as extra:
            result = original_observation()
            self.assertEqual((result['ok'],result['phase'],result['error_code'],result['error_component']),
                             (False,'verify','EXPORT_RUN_NOT_VERIFIED','market_result'))
            self.assertEqual(result['market_failure'], {'closed':'fixture'})
            extra.assert_called_once_with()
        for kwargs in ({'fail':False},{'component':'product_result'},{'code':'EXPORT_FILE_POLICY'}):
            with self.subTest(kwargs=kwargs), patch.object(D, '_market_failure_observation') as extra:
                result=original_observation(**kwargs)
                self.assertIsNone(result['market_failure'])
                extra.assert_not_called()

    def test_both_fixed_invocations_are_bound_independently_without_pairing_claim(self):
        replies=[(snapshot(),None),(journal(),None),(snapshot(),None),
            (snapshot(READER_INV),None),
            (journal('market_reader',READER_INV,json.dumps({'status':'failed','code':'SOURCE_READ','source_issue':'locked'})),None),
            (snapshot(READER_INV),None)]
        with patch.object(D,'_market_command',side_effect=replies) as command:
            value=D._market_failure_observation()
        self.assertEqual(len(command.call_args_list),6)
        self.assertEqual(value['reader_pairing'],'not_proven')
        self.assertEqual(value['market']['error_labels'],['coordination_reader_failed'])
        self.assertEqual(value['market_reader']['error_labels'],['export_source_read','sqlite_locked'])
        for role in D.MARKET_ROLES:
            self.assertTrue(value[role]['same_invocation'])
        args=[call.args[0] for call in command.call_args_list]
        self.assertEqual(args[1][-2:],['_SYSTEMD_UNIT='+D.UNITS['market'],'_SYSTEMD_INVOCATION_ID='+INV])
        self.assertEqual(args[4][-2:],['_SYSTEMD_UNIT='+D.UNITS['market_reader'],'_SYSTEMD_INVOCATION_ID='+READER_INV])
        self.assertNotIn('--since',repr(args))
        self.assertNotIn(INV,json.dumps(value)); self.assertNotIn(READER_INV,json.dumps(value))

    def test_invocation_or_state_change_discards_journal_labels(self):
        for after in (snapshot('3'*32),snapshot(active='activating'),snapshot(status='2')):
            with self.subTest(after=after),patch.object(D,'_market_command',side_effect=[(snapshot(),None),(journal(),None),(after,None)]):
                value=D._market_unit('market')
                self.assertEqual((value['status'],value['journal_status']),('context_changed','context_changed'))
                self.assertFalse(value['same_invocation']);self.assertEqual(value['error_labels'],[])

    def test_no_invocation_or_now_success_has_no_journal_request(self):
        for raw,expected in ((snapshot(''),'no_invocation'),(snapshot('0'*32),'no_invocation'),
            (snapshot(result='success',status='0'),'context_changed')):
            with self.subTest(expected=expected),patch.object(D,'_market_command',return_value=(raw,None)) as command:
                self.assertEqual(D._market_unit('market')['status'],expected)
                self.assertEqual(command.call_count,1)

    def test_unit_properties_are_strict_bounded_and_unknown_text_does_not_escape(self):
        for raw in (snapshot(status='256'),snapshot(status='-1'),snapshot(status='01'),snapshot()+b'Result=success\n',
                    snapshot(inv='RAW_SECRET_MARKER'),snapshot()+b'Extra=RAW_SECRET_MARKER\n'):
            with self.subTest(raw=raw),self.assertRaises((ValueError,UnicodeError)):
                D._market_snapshot(raw)
        raw=snapshot(result='RAW_SECRET_MARKER',active='UNLISTED',sub='UNLISTED')
        with patch.object(D,'_market_command',side_effect=[(raw,None),(journal(message='unclassified'),None),(raw,None)]):
            value=D._market_unit('market')
        self.assertEqual((value['unit_result'],value['active_state'],value['sub_state']),('unknown','unknown','unknown'))
        self.assertNotIn('RAW_SECRET_MARKER',json.dumps(value))

    def test_journal_requires_exact_unit_invocation_and_strict_json(self):
        cases=[journal('market_reader'),journal(inv='4'*32),b'not JSON\n',
            b'{"_SYSTEMD_UNIT":"a","_SYSTEMD_UNIT":"b"}\n',
            journal(message='NUL\x00RAW_SECRET_MARKER')]
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual(D._market_journal(raw,'market',INV),('invalid',0,[]))
        self.assertEqual(D._market_journal(journal()*33,'market',INV),('limited',0,[]))
        self.assertEqual(D._market_journal(b'x'*32769,'market',INV),('limited',0,[]))
        self.assertEqual(D._market_journal(b'','market',INV),('empty',0,[]))

    def test_closed_json_promotion_rejects_extra_duplicate_and_unknown_fields(self):
        valid={'status':'failed','code':'SOURCE_READ','source_issue':'schema'}
        self.assertEqual(D._market_labels(json.dumps(valid)),['export_source_read','sqlite_schema'])
        for text in (json.dumps(dict(valid,raw='RAW_SECRET_MARKER')),
                     '{"status":"failed","code":"SOURCE_READ","code":"SOURCE_READ","source_issue":"schema"}',
                     json.dumps(dict(valid,source_issue='RAW_SECRET_MARKER')),
                     json.dumps({'status':'failed','code':'RAW_SECRET_MARKER'})):
            self.assertEqual(D._market_labels(text),[])
        self.assertIn('permission_denied',D._market_labels('permission denied /private/RAW_SECRET_MARKER'))

    def test_mutating_arbitrary_or_unbound_commands_refuse_before_popen(self):
        bad=[['/usr/bin/systemctl','restart',D.UNITS['market']],
            ['/usr/bin/journalctl','--output=json','--no-pager','-n','32','_SYSTEMD_UNIT='+D.UNITS['market'],'_SYSTEMD_INVOCATION_ID='+'0'*32],
            ['/usr/bin/journalctl','--output=json','--no-pager','-n','32','_SYSTEMD_UNIT=foreign.service','_SYSTEMD_INVOCATION_ID='+INV],
            ['/bin/sh','-c','anything']]
        with patch.object(D.subprocess,'Popen') as popen:
            for args in bad:
                with self.subTest(args=args),self.assertRaisesRegex(ValueError,'DIAGNOSTIC_COMMAND'):
                    D._market_command(args)
            popen.assert_not_called()

    def test_bounded_pipe_kills_overflow_without_returning_journal_text(self):
        process=Mock();process.stdout.fileno.return_value=123;process.poll.return_value=None;process.wait.return_value=0
        selector=Mock();selector.select.return_value=[True]
        args=['/usr/bin/journalctl','--output=json','--no-pager','-n','32','_SYSTEMD_UNIT='+D.UNITS['market'],'_SYSTEMD_INVOCATION_ID='+INV]
        with patch.object(D.subprocess,'Popen',return_value=process) as popen,patch.object(D.selectors,'DefaultSelector',return_value=selector),patch.object(D.os,'read',side_effect=[b'x'*4096]*8+[b'x']):
            self.assertEqual(D._market_command(args),(None,'limited'))
        process.kill.assert_called_once();process.stdout.close.assert_called_once()
        self.assertEqual(popen.call_args.kwargs['stdin'],D.subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs['stderr'],D.subprocess.DEVNULL)
        self.assertNotIn('shell',popen.call_args.kwargs)

    def test_timeout_and_observer_exception_keep_closed_unavailable_result(self):
        process=Mock();process.stdout.fileno.return_value=123;process.poll.return_value=None;process.wait.return_value=0
        selector=Mock();selector.select.return_value=[]
        args=['/usr/bin/systemctl','show',D.UNITS['market']]+['--property='+name for name in D.UNIT_PROPERTIES]
        with patch.object(D.subprocess,'Popen',return_value=process),patch.object(D.selectors,'DefaultSelector',return_value=selector):
            self.assertEqual(D._market_command(args),(None,'unavailable'))
        with patch.object(D,'_market_unit',side_effect=RuntimeError('RAW_SECRET_MARKER')):
            extra=D._market_failure_observation()
        self.assertEqual(extra['market']['status'],'unavailable')
        self.assertNotIn('RAW_SECRET_MARKER',json.dumps(extra))

    def test_full_projection_cannot_emit_identifier_unknown_label_or_boolean_number(self):
        with patch.object(D,'_market_unit',return_value=D._market_empty()):
            value=D._market_failure_observation()
        D._validate_market_failure(value)
        for field,bad in (('exit_status',True),('exit_status',256),('journal_records',33),
                          ('error_labels',['RAW_SECRET_MARKER']),('unit_result','RAW_SECRET_MARKER')):
            copy=json.loads(json.dumps(value));copy['market'][field]=bad
            with self.subTest(field=field),self.assertRaises(ValueError):D._validate_market_failure(copy)
        copy=json.loads(json.dumps(value));copy['market']['invocation']=INV
        with self.assertRaises(ValueError):D._validate_market_failure(copy)

    def test_maximum_allowlisted_labels_keep_existing_4096_byte_result_cap(self):
        labels=sorted({x for x,_ in D.ERROR_PATTERNS}|set(D.EXPORTER_FAILURE_LABELS.values())|
                      set(D.SQLITE_SOURCE_LABELS.values())|set(D.COORDINATION_FAILURE_LABELS.values()))
        row=D._market_empty();row.update(status='observed',unit_result='exit-code',exit_status=255,
            active_state='failed',sub_state='failed',invocation_present=True,same_invocation=True,
            journal_status='observed',journal_records=32,error_labels=labels)
        with patch.object(D,'_market_unit',return_value=row):
            result=original_observation()
        raw=D.closed_json(result)
        self.assertLessEqual(len(raw.encode()),4096)
        self.assertFalse(json.loads(raw)['ok'])


if __name__=='__main__':unittest.main()
