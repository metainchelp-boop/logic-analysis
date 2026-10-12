"""Closed synthetic exporter failure diagnostics; no systemd, host or data IO."""
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import naver_completion_exports as E

class CompletionExportDiagnosticTests(unittest.TestCase):
    def test_every_generated_command_has_closed_stage(self):
        units=['/etc/systemd/system/naver-'+kind+'-export.'+suffix for kind in ('market','product') for suffix in ('service','timer')]
        self.assertEqual(E.command_stage(['systemd-analyze','verify',*units]),'unit_verify')
        self.assertEqual(E.command_stage(['systemctl','daemon-reload']),'daemon_reload')
        for kind in ('product','market'):
            service='naver-'+kind+'-export.service';timer='naver-'+kind+'-export.timer'
            for action,tail,stage in [('start',[service],'start'),('enable',['--now',timer],'enable'),
                ('show',[service,'--property=Result','--property=ExecMainStatus'],'show'),
                ('is-enabled',[timer],'enabled'),('is-active',[timer],'active'),
                ('disable',['--now',timer],'disable'),('stop',[service],'stop')]:
                self.assertEqual(E.command_stage(['systemctl',action,*tail]),kind+'_'+stage)
        for args in (None,(),['systemctl','start','foreign.service'],['journalctl'],['systemd-analyze','verify','/private/secret']):
            self.assertEqual(E.command_stage(args),'unknown')

    def test_unknown_commands_never_probe_or_expose_errors(self):
        with patch.object(E.subprocess,'run') as run:
            result=E.command_diagnostic(['private','secret'],RuntimeError('secret token'))
        run.assert_not_called();self.assertEqual(result,{'export_command_stage':'unknown','export_command_issue':'unknown'})

    def test_unit_verify_only_repeats_readonly_exact_command(self):
        args=['systemd-analyze','verify',*['/etc/systemd/system/naver-'+kind+'-export.'+suffix for kind in ('market','product') for suffix in ('service','timer')]]
        fake=SimpleNamespace(stdout=b'private token',stderr=b'failed to parse private /path',returncode=1)
        with patch.object(E.subprocess,'run',return_value=fake) as run:
            result=E.command_diagnostic(args,RuntimeError('private'))
        self.assertEqual(run.call_args.args[0],args);self.assertEqual(run.call_args.kwargs['timeout'],8)
        self.assertEqual(result,{'export_command_stage':'unit_verify','export_command_issue':'unit_syntax','export_command_status':1})
        self.assertNotIn('private',json.dumps(result))

    def test_failed_start_reads_only_fixed_journal_and_never_restarts(self):
        with patch.object(E.subprocess,'run',side_effect=[SimpleNamespace(stdout=b'a'*32+b'\n',stderr=b'',returncode=0),SimpleNamespace(stdout=b'Failed at step NAMESPACE: private',stderr=b'',returncode=0)]) as run:
            result=E.command_diagnostic(['systemctl','start','naver-product-export.service'],RuntimeError('private'))
        self.assertEqual(run.call_args_list[0].args[0],['systemctl','show','naver-product-export.service','--property=InvocationID','--value'])
        self.assertEqual(run.call_args.args[0],['journalctl','--no-pager','--output=cat','-n','32','-u','naver-product-export.service','_SYSTEMD_INVOCATION_ID='+'a'*32])
        self.assertEqual(result,{'export_command_stage':'product_start','export_command_issue':'namespace'})

    def test_invalid_or_missing_invocation_never_reads_old_journal(self):
        for body in (b'',b'private invalid identifier',b'a'*31,b'a'*33):
            with patch.object(E.subprocess,'run',return_value=SimpleNamespace(stdout=body,returncode=0)) as run:
                result=E.command_diagnostic(['systemctl','start','naver-product-export.service'],RuntimeError('private'))
            self.assertEqual(run.call_count,1);self.assertEqual(result['export_command_issue'],'command_failed')

    def test_diagnostic_failure_and_invalid_status_stay_closed(self):
        args=['systemctl','start','naver-market-export.service']
        with patch.object(E.subprocess,'run',side_effect=RuntimeError('private')):
            self.assertEqual(E.command_diagnostic(args,RuntimeError('private'))['export_command_issue'],'command_failed')
        with patch.object(E.subprocess,'run') as run:
            self.assertEqual(E.command_diagnostic(args,subprocess.TimeoutExpired('private',45))['export_command_issue'],'command_timeout')
        run.assert_not_called()

    def test_masked_helper_exception_preserves_closed_command_failure(self):
        binding=object.__new__(E.Binding);binding._command_failure=None
        def command(args):raise RuntimeError('private details')
        binding.r=SimpleNamespace(command=command)
        def helper():
            try:binding.command(['systemctl','daemon-reload'])
            except Exception:raise ValueError('EXPORT_COMMAND_FAILED')
        with self.assertRaisesRegex(ValueError,'EXPORT_COMMAND_FAILED') as caught:
            binding.operation(helper)
        self.assertEqual(caught.exception.failure_details,{'export_command_stage':'daemon_reload','export_command_issue':'command_failed'})
        self.assertNotIn('private',json.dumps(caught.exception.failure_details))

if __name__=='__main__':unittest.main()
