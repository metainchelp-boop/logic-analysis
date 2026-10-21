"""Synthetic dashboard profiling: no live database, Docker, identity or money output."""
import ast
import contextlib
import copy
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

SPEC = importlib.util.spec_from_file_location('dashboard_status', Path(__file__).parents[1]/'tools/naver_preview_collection_status.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def valid_profile():
    phases=['reader','org','scope','context','dashboard']
    return dict(state='complete',code=None,last_phase='dashboard',elapsed_us=100,cpu_us=20,
        phases=[dict(phase=name,wall_us=1,cpu_us=1,completed=True) for name in phases],functions=[],
        aggregates={},cgroup_before={},cgroup_after={},read_only=True,
        authenticated_request=False,engine_process_shared=False)


class DashboardProfileTest(unittest.TestCase):
    def fixture(self, outcome='complete', owners=(0,), scope_kind='all'):
        db=sqlite3.connect(':memory:',isolation_level=None)
        self.addCleanup(db.close)
        db.execute('CREATE TABLE private_rows(customer_id INT,spend INT)')
        db.execute('INSERT INTO private_rows VALUES(987654321,123456789)')
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
        ctx=object()
        engine.views=types.SimpleNamespace(load_org=Mock(return_value=org),load=Mock(return_value=ctx),
            me=Mock(side_effect=AssertionError('/me must not be measured')),
            bell=Mock(side_effect=AssertionError('bell must not be measured')))
        engine.inventory=types.SimpleNamespace(staff_counts=Mock(side_effect=AssertionError('counts must not be measured')))
        namespace={}
        def board(*args,**kwargs):
            if outcome=='timeout':
                raise namespace['ProfileDeadline']()
            if outcome=='write':
                db.execute('UPDATE private_rows SET spend=0')
            if outcome=='network':
                with socket.socket() as connection:
                    connection.connect(('127.0.0.1',9))
            if outcome=='error':
                raise RuntimeError('PRIVATE /secret/path account=987654321 spend=123456789')
            return dict(customer_id=987654321,spend=123456789,private='PRIVATE')
        engine.dashboard=types.SimpleNamespace(board=Mock(side_effect=board))
        app=types.ModuleType('app')
        auto=types.ModuleType('app.naver_auto')
        def scoped(org,actor):
            chosen.append(actor)
            return types.SimpleNamespace(kind=scope_kind,viewer_idx=actor)
        auto.scope=types.SimpleNamespace(scope_of=scoped,ALL='all')
        app.naver_auto=auto
        output=io.StringIO()
        saved_connect,saved_connect_ex=socket.socket.connect,socket.socket.connect_ex
        with patch.dict(sys.modules,{'naver_engine':engine,'app':app,'app.naver_auto':auto}), \
                patch.object(sys,'path',list(sys.path)),patch.dict(os.environ,{}), \
                patch.object(os,'geteuid',return_value=10001),patch('builtins.open',side_effect=FileNotFoundError), \
                patch.object(signal,'setitimer') as timer,contextlib.redirect_stdout(output):
            exec(compile(M.dashboard_script(),'<synthetic-dashboard>','exec'),namespace)
        self.assertEqual(timer.call_args_list[0].args,(signal.ITIMER_REAL,25))
        self.assertEqual(timer.call_args_list[-1].args,(signal.ITIMER_REAL,0))
        self.assertIs(socket.socket.connect,saved_connect)
        self.assertIs(socket.socket.connect_ex,saved_connect_ex)
        reader.close.assert_called_once()
        self.assertEqual(chosen,[] if not owners else [0 if 0 in owners else min(owners)])
        engine.store.open_reader.assert_called_once_with('/var/lib/naver-engine/engine.db')
        self.assertEqual(db.total_changes,before)
        if owners and scope_kind=='all':
            engine.dashboard.board.assert_called_once_with(ctx,reader,unittest.mock.ANY,selection='all')
        else:
            engine.dashboard.board.assert_not_called()
        engine.views.me.assert_not_called()
        engine.views.bell.assert_not_called()
        engine.inventory.staff_counts.assert_not_called()
        for private in ('PRIVATE','987654321','123456789','secret/path'):
            self.assertNotIn(private,output.getvalue())
        return json.loads(output.getvalue())['dashboard_profile']

    def test_exact_dashboard_board_uses_current_all_scope_without_output(self):
        result=self.fixture()
        self.assertEqual(result['state'],'complete')
        self.assertIsNone(result['code'])
        self.assertEqual(result['aggregates'],{})
        self.assertEqual([p['phase'] for p in result['phases']],['reader','org','scope','context','dashboard'])

    def test_timeout_error_write_and_network_are_partial(self):
        for outcome,code in (('timeout','PROFILE_TIMEOUT'),('error','PROFILE_ERROR'),
                             ('write','PROFILE_ERROR'),('network','PROFILE_ERROR')):
            with self.subTest(outcome=outcome):
                result=self.fixture(outcome)
                self.assertEqual((result['state'],result['code'],result['last_phase']),('partial',code,'dashboard'))
                self.assertFalse(result['phases'][-1]['completed'])

    def test_current_top_manager_scope_is_required_and_identity_not_exported(self):
        self.assertEqual(self.fixture(owners=(91,72))['state'],'complete')
        for kwargs in (dict(owners=()),dict(scope_kind='none')):
            result=self.fixture(**kwargs)
            self.assertEqual((result['state'],result['code']),('partial','PROFILE_ERROR'))

    def test_explicit_mode_is_exclusive_true_only_and_exact_source_pinned(self):
        package=dict(baseline='a'*64,source_commit=M.LATENCY_FIX_COMMIT,source_tar_gz_sha256='b'*64)
        M.validate_package(dict(package,dashboard_profile_only=True))
        for extra in (dict(dashboard_profile_only=False),dict(dashboard_profile_only=1),
                      dict(dashboard_profile_only=True,passive_runtime_only=True),
                      dict(dashboard_profile_only=True,latency_profile_only=True)):
            with self.assertRaises(ValueError):
                M.validate_package(dict(package,**extra))
        for commit in (M.WRITER_RELIEF_COMMIT,'c'*40):
            host,release=Mock(),Mock()
            with self.assertRaisesRegex(ValueError,'PROFILE_SOURCE_UNREVIEWED'):
                M.run(dict(package,source_commit=commit,dashboard_profile_only=True),host,release)
            host.baseline.assert_not_called()
            release.command.assert_not_called()

    def test_fixed_projection_rejects_customer_money_and_other_profile(self):
        valid=valid_profile()
        self.assertEqual(M.latency_projection(valid,dashboard=True),valid)
        changes=[lambda v:v.update(customer_id=987654321),lambda v:v.update(spend=123456789),
            lambda v:v.update(last_phase='staff_counts'),lambda v:v.update(engine_process_shared=True),
            lambda v:v['aggregates'].update(daily=[1]),lambda v:v['phases'].pop(),
            lambda v:v['functions'].append(dict(file='dashboard.py',function='PRIVATE',line=1,
                calls=1,recursive_calls=0,total_us=1,self_us=1))]
        for change in changes:
            item=copy.deepcopy(valid);change(item)
            with self.subTest(change=change),self.assertRaises(ValueError):
                M.latency_projection(item,dashboard=True)
        with self.assertRaises(ValueError):
            M.latency_projection(valid)

    def test_script_uses_existing_bounded_read_only_path_and_only_fixed_functions(self):
        source=M.dashboard_script().decode()
        ast.parse(source)
        self.assertIn("S.open_reader('/var/lib/naver-engine/engine.db')",source)
        self.assertIn('signal.setitimer(signal.ITIMER_REAL,25)',source)
        self.assertIn('set_progress_handler',source)
        self.assertIn("DASH.board(ctx,reader,scope,selection='all')",source)
        for forbidden in ('open_writer','TokenSigner','Authorization','HTTP_AUTHORIZATION','record_',
                          "execute('BEGIN')",'INSERT INTO','UPDATE ','DELETE FROM','executescript'):
            self.assertNotIn(forbidden,source)
        item=valid_profile()
        item['functions']=[dict(file='dashboard.py',function='board',line=1,
            calls=1,recursive_calls=0,total_us=1,self_us=1)]
        self.assertEqual(M.latency_projection(item,dashboard=True),item)


if __name__=='__main__':
    unittest.main()
