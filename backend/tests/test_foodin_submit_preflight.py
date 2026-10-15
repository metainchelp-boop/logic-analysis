"""Fixed submit preparation contract; no operating DB or provider access."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import unittest
TOOLS=Path(__file__).parents[1]/'tools'
def load(name):
    spec=importlib.util.spec_from_file_location(name,TOOLS/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
GOOD = {'schema_version': 21, 'projection_model': 'foodin-submit-preflight-v1', 'target_identifier_namespace': 'ad_account_no', 'scope': 'current_preparation_only', 'past_POST_cause_not_proven': True, 'checks': {'authority_passed': True, 'report_latest': True, 'report_revision_matches': True, 'report_dirty': False, 'strategy_version_matches': True, 'active_job_exists': False, 'funnel_current': True, 'setup_model_source_passed': True, 'prepare_passed': True}, 'strategy_version': 0, 'failure_checkpoint': 'none', 'failure_kind': 'none', 'limits': {'stored_snapshot_only': True, 'source_guards_unchanged': True, 'reservation_not_called': True, 'provider_not_called': True, 'job_creation_not_called': True, 'ads_unchanged': True}, 'mutations': 0}
class SubmitPreflightTests(unittest.TestCase):
    def test_fixed_scope_no_dynamic_actor_sql_or_report_input(self):
        d=load('naver_setup_stale_diagnostics');t=load('naver_setup_stale_diagnostics_transport')
        self.assertEqual((d._PREFLIGHT_REPORT_ID,d._PREFLIGHT_REPORT_REVISION,d._PREFLIGHT_STRATEGY_VERSION,d._PREFLIGHT_ACTOR,d._PREFLIGHT_NARROWED,d._PREFLIGHT_TARGET),(14055,6,0,0,False,('foodin',51952,1030001)))
        for key,value in (('actor',1),('report_id',14056),('sql','SELECT'),('narrowed',True)):
            with self.subTest(key=key),self.assertRaises(ValueError):t.validate_package(dict(t.PACKAGE,**{key:value}))
        text=d.submit_preflight_script().decode();ast.parse(text)
        self.assertEqual(text.count('result=collect_submit_preflight(reader,datetime.now(KST),deadline,modules)'),1)
        for literal in ('os.geteuid()!=10001','socket.socket.connect=socket.socket.connect_ex=no_network',"connection.execute('BEGIN')",'connection.total_changes!=0','time.monotonic()+20'):
            self.assertIn(literal,text)
        self.assertEqual(len(d.CODE_PINS),115)
    def test_closed_result_rejects_raw_extra_wrong_types_and_success_overclaim(self):
        d=load('naver_setup_stale_diagnostics');self.assertEqual(d.validate_submit_preflight_result(copy.deepcopy(GOOD)),GOOD)
        mutations=[lambda x:x.update(raw='RAW_CANARY'),lambda x:x['checks'].update(raw='RAW_CANARY'),lambda x:x.update(failure_checkpoint=[]),lambda x:x.update(failure_kind='RAW_CANARY'),lambda x:x.update(strategy_version=True),lambda x:x['checks'].update(report_latest=False),lambda x:x['checks'].update(report_dirty=True),lambda x:x['checks'].update(authority_passed=False),lambda x:x['limits'].update(provider_not_called=False),lambda x:x.update(projection_model='dc168-setup-stale-v1')]
        for mutate in mutations:
            bad=copy.deepcopy(GOOD);mutate(bad)
            with self.subTest(value=bad),self.assertRaises(ValueError):d.validate_submit_preflight_result(bad)
    def test_controller_inverse_and_actual_packet_keep_guards_and_codec_bounds(self):
        d=load('naver_setup_stale_diagnostics');t=load('naver_setup_stale_diagnostics_transport')
        tree=ast.parse((TOOLS/'naver_setup_stale_diagnostics.py').read_text());old=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run');new=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_submit_preflight')
        new.name='run'
        for node in ast.walk(new):
            if isinstance(node,ast.Name) and node.id=='submit_preflight_script':node.id='script'
            if isinstance(node,ast.Name) and node.id=='validate_submit_preflight_result':node.id='validate_result'
        self.assertEqual(ast.dump(new),ast.dump(old))
        value=t.bundle(dict(t.PACKAGE),TOOLS);wire=t.encode(value);self.assertEqual(t.decode(wire),value)
        self.assertEqual((t.MAX_JSON,t.MAX_WIRE,t.MAX_SOURCE,t.MAX_RESULT,t.MAX_TRANSPORT_BASE64),(196608,65536,98304,20480,32768))
        for bad in (wire[:-5],wire+'AAAA',wire+'A'*t.MAX_WIRE):
            with self.subTest(size=len(bad)),self.assertRaises(ValueError):t.decode(bad)
        changed=copy.deepcopy(value);changed['sources']['diagnostic']+='\n# altered'
        with self.assertRaises(ValueError):t.encode(changed)
if __name__=='__main__':unittest.main()
