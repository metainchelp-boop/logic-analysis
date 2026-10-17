"""Read-only synthetic /me profiling. No Docker, network or production files."""
import ast
import base64
import contextlib
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import sys
import types
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('latency_status', Path(__file__).parents[1]/'tools/naver_preview_collection_status.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def valid_profile():
    phases=['reader','org','scope','context','me','staff_counts','bell']+['aggregate_'+key for key in M.PROFILE_AGGREGATES]
    return dict(state='complete',code=None,last_phase=phases[-1],elapsed_us=100,cpu_us=20,
        phases=[dict(phase=name,wall_us=1,cpu_us=1,completed=True) for name in phases],functions=[],
        aggregates={key:[0]*width for key,(_,width) in M.PROFILE_AGGREGATES.items()},
        cgroup_before={},cgroup_after={},read_only=True,authenticated_request=False,engine_process_shared=False)


class LatencyTest(unittest.TestCase):
    def fixture(self, outcome='complete', owners=(0,)):
        db=sqlite3.connect(':memory:',isolation_level=None)
        self.addCleanup(db.close)
        db.executescript('''
            CREATE TABLE naver_auto_meta(key TEXT,value TEXT);
            CREATE TABLE naver_auto_org(slot TEXT,body TEXT);
            CREATE TABLE naver_auto_performance_job(progress_json TEXT,campaigns_json TEXT);
            CREATE TABLE naver_auto_structure_job(reasons_json TEXT);
            CREATE TABLE naver_auto_inventory_check(status TEXT);
            CREATE TABLE naver_auto_daily_performance(customer_id INT);
            CREATE TABLE naver_auto_link_decision(customer_id INT);
            CREATE TABLE naver_auto_alert_recipient(emp_idx INT);
            INSERT INTO naver_auto_meta VALUES('account_catalog','PRIVATE');
            INSERT INTO naver_auto_org VALUES('current','PRIVATE');
            INSERT INTO naver_auto_performance_job VALUES('PRIVATE','PRIVATE');
            INSERT INTO naver_auto_structure_job VALUES('PRIVATE');
            INSERT INTO naver_auto_inventory_check VALUES('ok');
        ''')
        fixture=json.loads((Path(__file__).with_name('fixtures')/'naver_schema10_11_contract.json').read_text())
        auth=dict(_A=sqlite3)
        exec(fixture['new_observed_unsealed']['authorizer'],auth)
        db.set_authorizer(auth['_authorizer'](auth['PHASE_READ']))
        before=db.total_changes
        reader=types.SimpleNamespace(_conn=db,close=Mock())
        engine=types.ModuleType('naver_engine')
        engine.store=types.SimpleNamespace(open_reader=Mock(return_value=reader))
        chosen=[]
        org=types.SimpleNamespace(top_managers=lambda:frozenset(owners))
        engine.views=types.SimpleNamespace(load_org=lambda r:org,load=lambda *a:object(),
            me=lambda *a:dict(people=[dict(idx=987654321,name='PRIVATE')]),bell=lambda *a:dict(unread=1,private='PRIVATE'))
        namespace={}
        def staff_counts(*args):
            if outcome=='timeout':
                raise namespace['ProfileDeadline']()
            if outcome=='write':
                db.execute("UPDATE naver_auto_meta SET value='PRIVATE_CHANGED'")
            if outcome=='network':
                with socket.socket() as connection:
                    connection.connect(('127.0.0.1',9))
            if outcome=='error':
                raise RuntimeError('PRIVATE /secret/path account=987654321')
            return {987654321:1}
        engine.inventory=types.SimpleNamespace(staff_counts=staff_counts)
        app=types.ModuleType('app')
        auto=types.ModuleType('app.naver_auto')
        def scoped(org,actor):
            chosen.append(actor)
            return types.SimpleNamespace(kind='all',viewer_idx=actor)
        auto.scope=types.SimpleNamespace(scope_of=scoped,ALL='all')
        app.naver_auto=auto
        output=io.StringIO()
        saved_connect=socket.socket.connect
        with patch.dict(sys.modules,{'naver_engine':engine,'app':app,'app.naver_auto':auto}), \
                patch.object(sys,'path',list(sys.path)),patch.dict(os.environ,{}), \
                patch.object(os,'geteuid',return_value=10001),patch('builtins.open',side_effect=FileNotFoundError), \
                patch.object(signal,'setitimer') as timer,contextlib.redirect_stdout(output):
            exec(compile(M.latency_script(),'<synthetic-latency>','exec'),namespace)
        self.assertEqual(timer.call_args_list[0].args,(signal.ITIMER_REAL,25))
        self.assertEqual(timer.call_args_list[-1].args,(signal.ITIMER_REAL,0))
        self.assertIs(socket.socket.connect,saved_connect)
        reader.close.assert_called_once()
        self.assertEqual(chosen,[] if not owners else [0 if 0 in owners else min(owners)])
        engine.store.open_reader.assert_called_once_with('/var/lib/naver-engine/engine.db')
        self.assertEqual(db.total_changes,before)
        for private in ('PRIVATE','987654321','secret/path'):
            self.assertNotIn(private,output.getvalue())
        return json.loads(output.getvalue())['latency_profile']

    def test_actual_reader_authorizer_and_equivalent_me_complete_once(self):
        result=self.fixture()
        self.assertEqual(result['state'],'complete')
        self.assertIsNone(result['code'])
        self.assertEqual(result['aggregates']['performance'],[1,7,7,7,7])
        self.assertEqual(result['aggregates']['catalog'],[7])
        self.assertEqual([p['phase'] for p in result['phases']].count('staff_counts'),1)

    def test_timeout_and_error_are_partial_not_success(self):
        for outcome,code in (('timeout','PROFILE_TIMEOUT'),('error','PROFILE_ERROR'),
                             ('write','PROFILE_ERROR'),('network','PROFILE_ERROR')):
            with self.subTest(outcome=outcome):
                result=self.fixture(outcome)
                self.assertEqual((result['state'],result['code'],result['last_phase']),('partial',code,'staff_counts'))
                self.assertFalse(result['phases'][-1]['completed'])
                self.assertEqual(result['aggregates'],{})

    def test_current_active_top_manager_is_selected_without_exporting_identity(self):
        self.assertEqual(self.fixture(owners=(91,72))['state'],'complete')
        missing=self.fixture(owners=())
        self.assertEqual((missing['state'],missing['code']),('partial','PROFILE_ERROR'))

    def test_workflow_source_bundle_fits_existing_raw_and_compressed_limits(self):
        root=Path(__file__).parents[1]/'tools'
        bundle=dict(package=dict(baseline='a'*64,source_commit=M.WRITER_RELIEF_COMMIT,
            source_tar_gz_sha256='b'*64,latency_profile_only=True),operation='preview-collection-status',function='run',
            source=(root/'naver_preview_collection_status.py').read_text(),
            release_source=(root/'naver_preview_release.py').read_text(),
            host_source=(root/'naver_erp_tunnel_service_install.py').read_text())
        raw=json.dumps(bundle).encode()
        wire='code-gzip-v1:'+base64.b64encode(gzip.compress(raw,mtime=0)).decode()
        self.assertLessEqual(len(raw),196608)
        self.assertLessEqual(len(wire),65536)

    def test_fixed_projection_refuses_unknown_fields_functions_counts_and_success_claims(self):
        valid=valid_profile()
        self.assertEqual(M.latency_projection(valid),valid)
        changes=[lambda v:v.update(raw_error='PRIVATE'),lambda v:v.update(last_phase='PRIVATE'),
            lambda v:v.update(cpu_us=True),lambda v:v.update(read_only=False),
            lambda v:v.update(authenticated_request=True),lambda v:v['aggregates'].update(private=[1]),
            lambda v:v['aggregates'].update(daily=['PRIVATE']),lambda v:v['phases'].clear(),
            lambda v:v['cgroup_before'].update(path='PRIVATE'),lambda v:v.update(code='PROFILE_TIMEOUT'),
            lambda v:v['functions'].append(dict(file='store.py',function='PRIVATE',line=1,calls=1,
                recursive_calls=0,total_us=1,self_us=1)),lambda v:v.update(functions=[{}]*41)]
        for change in changes:
            item=copy.deepcopy(valid);change(item)
            with self.subTest(change=change),self.assertRaises(ValueError):
                M.latency_projection(item)

    def test_profile_mode_is_exclusive_true_only_and_source_pinned(self):
        package=dict(baseline='a'*64,source_commit=M.WRITER_RELIEF_COMMIT,source_tar_gz_sha256='b'*64)
        M.validate_package(dict(package,latency_profile_only=True))
        for extra in (dict(latency_profile_only=False),dict(latency_profile_only=1),
                      dict(latency_profile_only=True,passive_runtime_only=True)):
            with self.assertRaises(ValueError):
                M.validate_package(dict(package,**extra))
        host,release=Mock(),Mock()
        with self.assertRaisesRegex(ValueError,'PROFILE_SOURCE_UNREVIEWED'):
            M.run(dict(package,source_commit='c'*40,latency_profile_only=True),host,release)
        release.command.assert_not_called()

    def test_script_has_no_mutation_or_auth_token_and_only_fixed_reader_path(self):
        source=M.latency_script().decode()
        ast.parse(source)
        self.assertIn("S.open_reader('/var/lib/naver-engine/engine.db')",source)
        self.assertIn('signal.setitimer(signal.ITIMER_REAL,25)',source)
        self.assertIn('set_progress_handler',source)
        for forbidden in ('open_writer','TokenSigner','Authorization','HTTP_AUTHORIZATION','record_',
                          "execute('BEGIN')",'INSERT INTO','UPDATE ','DELETE FROM','executescript'):
            self.assertNotIn(forbidden,source)
        for sql,_ in M.PROFILE_AGGREGATES.values():
            self.assertTrue(sql.startswith('SELECT '))

    def test_cgroup_projection_reads_only_fixed_numeric_fields(self):
        data={'cpu.stat':b'usage_usec 123\nnr_throttled 2\nPRIVATE SECRET\n',
              'cpu.max':b'50000 100000','memory.current':b'1024','memory.max':b'max'}
        def opened(path,mode):
            self.assertTrue(path.startswith('/sys/fs/cgroup/'))
            self.assertEqual(mode,'rb')
            return io.BytesIO(data[path.rsplit('/',1)[1]])
        with patch('builtins.open',side_effect=opened):
            result=M.profile_cgroup()
        self.assertEqual(result,dict(usage_usec=123,nr_throttled=2,cpu_quota_usec=50000,
            cpu_period_usec=100000,memory_current=1024,memory_max=None))


if __name__=='__main__':
    unittest.main()
