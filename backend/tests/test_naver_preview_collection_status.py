"""Synthetic SQLite collection projection; never connects to Docker or a server."""
import importlib.util
import ast
import hashlib
import json
import os
import sqlite3
import tempfile
import types
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('collection_status', Path(__file__).parents[1]/'tools/naver_preview_collection_status.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class CollectionTest(unittest.TestCase):
    def test_compose_version_diagnostics_never_export_freeform(self):
        release = Mock()
        for raw, want in ((b'2.39.4\n', '2.39.4'), (b'v2.39.4-desktop.2\n', '2.39.4-desktop.2'),
                          (b'2.39.4-SECRET', None), (b'SECRET', None), (b'x'*129, None)):
            release.command.return_value = raw
            self.assertEqual(M.compose_version(release), want)
        release.command.assert_called_with(['docker','compose','version','--short'], timeout=3)

    def test_optional_lifecycle_diagnostics_are_fixed_services_enums_and_bounded(self):
        release = Mock()
        responses = [b'ActiveState=active\nSubState=running\nResult=success\nNRestarts=0\n',
                     b'ActiveState=SECRET\nSubState=SECRET\nResult=SECRET\nNRestarts=SECRET\n',
                     RuntimeError('SECRET_FAILURE'), b'x'*4097]
        release.command.side_effect = responses
        out = M.lifecycle_status(release)
        self.assertEqual(set(out), {'docker','tunnel','engine','relay'})
        self.assertEqual(out['docker'], dict(available=True,active='active',substate='running',result='success',restarts=0))
        self.assertEqual(out['tunnel']['active'], 'UNRECOGNIZED')
        self.assertIsNone(out['tunnel']['restarts'])
        self.assertFalse(out['engine']['available'])
        self.assertFalse(out['relay']['available'])
        self.assertNotIn('SECRET', json.dumps(out))
        expected = ('docker.service','metainc-naver-erp-tunnel.service','metainc-naver-engine.service','metainc-naver-relay.service')
        for call, unit in zip(release.command.call_args_list, expected):
            self.assertEqual(call.args[0], ['/usr/bin/systemctl','show',unit,'--property=ActiveState,SubState,Result,NRestarts'])
            self.assertEqual(call.kwargs, {'timeout':3})

    def test_run_checks_approved_identity_and_reprojects_engine_output(self):
        package = dict(baseline='a'*64, source_commit='b'*40, source_tar_gz_sha256='c'*64)
        cid, image = 'd'*64, 'sha256:'+'e'*64
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            files = {}
            for name in ('compose.naver-engine.yml', 'preview-engine.override.yml', 'deploy/naver-engine-backup.override.yml'):
                path = root/name; path.parent.mkdir(exist_ok=True); path.write_bytes(b'fixture')
                files[str(path)] = hashlib.sha256(b'fixture').hexdigest()
            receipt = root/('preview-'+package['source_commit']+'.json')
            receipt.write_text(json.dumps(dict(ok=True, stage='prepared', source_commit=package['source_commit'],
                package=package, images={'engine':image}, files=files)))
            receipt.with_name('preview-start-'+package['source_commit']+'.json').write_text(json.dumps(
                dict(ok=True, stage='internal_ready', source_commit=package['source_commit'])))
            values = dict(today='2026-10-01', prospects={'total':0,'stages':{}},
                pairing={'available':False,'statuses':{},'unmatched_prospects':None}, latest_run=None,
                today_checks={'statuses':{},'reasons':{}}, bootstrap=M.bootstrap_empty('no_request'))
            for failure in (None, 'image', 'mount', 'rootfs', 'output', 'restart'):
                calls, inspections = [], []
                host, release = Mock(), Mock()
                host.baseline.return_value = package['baseline']
                release.prepared_paths.return_value = root, receipt
                release.sha.side_effect = lambda body: hashlib.sha256(body).hexdigest()
                release.unique.side_effect = dict
                release.compose.return_value = ['docker','compose','--project-name','naver-engine']
                def command(args, **kwargs):
                    calls.append(args)
                    if args[0] == '/usr/bin/systemctl':
                        return b'ActiveState=active\nSubState=running\nResult=success\nNRestarts=0\n'
                    if args[:3] == ['docker','compose','version']:
                        return b'2.39.4\n'
                    if args[1:3] == ['image','inspect']:
                        return json.dumps(dict(id=image,user='10001:10001',source='wrong' if failure=='image' else package['source_commit'])).encode()
                    if args[1] == 'compose':
                        return cid.encode()
                    if args[1] == 'inspect':
                        inspections.append(1)
                        return json.dumps(dict(id=cid,image=image,running=True,user='10001:10001',project='naver-engine',
                            service='naver-engine',started='2026-10-01T13:00:00+09:00',oom_killed=False,restarts=int(failure=='restart' and len(inspections)>1),
                            readonly=failure!='rootfs',data=[dict(Type='bind',Destination='/var/lib/naver-engine',
                            Source='/legacy' if failure=='mount' else '/var/lib/metainc/naver-engine')])).encode()
                    if args[1] == 'exec':
                        ast.parse(kwargs['data'])
                        self.assertEqual(args, ['docker','exec','-i','--user','10001:10001',cid,'python','-I','-B','-'])
                        return json.dumps(dict(values, secret='SECRET') if failure=='output' else values).encode()
                    self.fail('unexpected command')
                release.command.side_effect = command
                with self.subTest(failure=failure), patch.object(M.os, 'geteuid', return_value=0):
                    if failure:
                        with self.assertRaises(ValueError):
                            M.run(package, host, release)
                    else:
                        result = M.run(package, host, release)
                        self.assertEqual(result['collection'], values)
                        self.assertEqual(result['mutations'], 0)
                        self.assertEqual(result['lifecycle']['engine']['active'], 'active')
                        self.assertEqual(result['compose_version'], '2.39.4')
                        self.assertEqual(result['engine_state'], {'started_at':'2026-10-01T13:00:00+09:00', 'oom_killed':False})
                if failure in ('image','mount','rootfs'):
                    self.assertFalse(any(args[1]=='exec' for args in calls))

    def test_fixed_request_receipt_reader_refuses_links_modes_and_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            request, directory = root/'request.json', root/'bootstrap'
            request.write_text(json.dumps(dict(request_id='a'*32, hold_id=9, hold_sha256='b'*64,
                expected_rows=3, approved_by=0, expires_at='2026-10-01T15:00:00+09:00', max_seconds=60)))
            request.chmod(0o440)
            args = dict(request_uid=os.getuid(), runtime_uid=os.getuid(), gid=os.getgid())
            self.assertEqual(M.read_bootstrap(request, directory, **args)['state'], 'not_started')
            directory.mkdir(mode=0o700)
            started = directory/('bootstrap-'+'a'*32+'.json')
            body = dict(status='started', phase='preflight', request_id='a'*32, hold_id=9,
                        expected_rows=3, approved_by=0, started_at='2026-10-01T13:00:00+09:00')
            started.write_text(json.dumps(body)); started.chmod(0o600)
            self.assertEqual(M.read_bootstrap(request, directory, **args)['state'], 'started_without_result')
            started.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'BOOTSTRAP_FILE'):
                M.read_bootstrap(request, directory, **args)
            started.chmod(0o600)
            started.write_text(json.dumps(dict(body, hold_id=10)))
            with self.assertRaisesRegex(ValueError, 'BOOTSTRAP_IDENTITY'):
                M.read_bootstrap(request, directory, **args)
            link = root/'link.json'; link.symlink_to(request)
            with self.assertRaisesRegex(ValueError, 'BOOTSTRAP_PATH'):
                M.read_bootstrap(link, directory, **args)

    def test_package_cannot_select_another_database_or_receipt(self):
        package = dict(baseline='a'*64, source_commit='b'*40, source_tar_gz_sha256='c'*64)
        host, release = Mock(), Mock()
        for extra in ({'database':'/legacy'}, {'request_id':'d'*32}, {'source_commit':'../bad'}):
            with self.assertRaises(ValueError):
                M.run(dict(package, **extra), host, release)
        release.command.assert_not_called()

    def test_memory_script_and_bootstrap_projection_never_echo_receipt_identity(self):
        module = types.ModuleType('memory_collection')
        exec(compile(SPEC.loader.get_source('collection_status'), '<approved>', 'exec'), module.__dict__)
        ast.parse(module.script())
        started = dict(status='started', phase='preflight', request_id='a'*32, hold_id=9,
                       expected_rows=3, approved_by=0, started_at='2026-10-01T13:00:00+09:00')
        out = module.project_bootstrap(started, None)
        self.assertEqual(out['state'], 'started_without_result')
        self.assertNotIn('request_id', out)
        result = dict(started, status='partial', phase='finished', collection_outcome='done',
                      collection_counts={'ok':2,'account_error':1,'SECRET_CUSTOMER':987654321},
                      codes=['ACCOUNT_ERROR','SECRET_ERROR'], error_code='SECRET_FAILURE',
                      finished_at='2026-10-01T13:01:00+09:00')
        out = module.project_bootstrap(started, result)
        self.assertEqual(out['state'], 'partial')
        self.assertEqual(out['collection_counts'], {'ok':2,'account_error':1})
        self.assertEqual(out['error_code'], 'UNRECOGNIZED')
        self.assertNotIn('SECRET', json.dumps(out))
        self.assertNotIn('987654321', json.dumps(out))

    def test_counts_do_not_export_source_rows_or_freeform_codes(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('''
          CREATE TABLE naver_auto_prospect(possibility_id, name, stage_key, present);
          CREATE TABLE naver_auto_pairing_run(pairing_id, outcome);
          CREATE TABLE naver_auto_pairing_row(pairing_id, possibility_id, state);
          CREATE TABLE naver_auto_check_run(run_id,run_date,status,started_at,finished_at,accounts_total,accounts_ok,error_kind);
          CREATE TABLE naver_auto_account_day(day,status,rules_not_run);
          INSERT INTO naver_auto_prospect VALUES(987654321,'SECRET_NAME','진행중',1),(987654322,'SECRET_NAME','SECRET_STAGE',1);
          INSERT INTO naver_auto_pairing_run VALUES(1,'accepted');
          INSERT INTO naver_auto_pairing_row VALUES(1,987654321,'candidate');
          INSERT INTO naver_auto_check_run VALUES(1,'2026-10-01','failed','2026-10-01T13:00:00+09:00','2026-10-01T13:01:00+09:00',1,0,'SECRET_ERROR');
          INSERT INTO naver_auto_account_day VALUES('2026-10-01','partial','[["bizmoney","stats-unread"],["other","stats-unread"],["x","SECRET_REASON"]]');
        ''')
        db.set_authorizer(lambda action,*args: sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION) else sqlite3.SQLITE_DENY)
        out = M.collect(types.SimpleNamespace(_conn=db), '2026-10-01')
        self.assertEqual(out['prospects']['total'], 2)
        self.assertEqual(out['prospects']['stages']['UNRECOGNIZED'], 1)
        self.assertEqual(out['pairing']['unmatched_prospects'], 1)
        self.assertEqual(out['today_checks']['reasons'], {'stats-unread':1,'UNRECOGNIZED':1})
        self.assertEqual(out['latest_run']['codes'], ['UNRECOGNIZED'])
        self.assertNotIn('SECRET', json.dumps(out))
        self.assertNotIn('987654321', json.dumps(out))


if __name__ == '__main__':
    unittest.main()
