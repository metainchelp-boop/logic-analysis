import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import naver_preview_claude_diagnostics as D


class ClaudeDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=Path(self.folder.name).resolve()/'test.sqlite'
        c=sqlite3.connect(self.path)
        c.executescript('CREATE TABLE naver_auto_meta(key TEXT PRIMARY KEY,value TEXT);'
            'CREATE TABLE naver_auto_access_log(log_id INTEGER PRIMARY KEY,emp_idx INTEGER,action TEXT,result TEXT,at TEXT NOT NULL);'
            'CREATE TABLE naver_auto_account(customer_id INTEGER,ad_account_no INTEGER,present INTEGER);'
            'CREATE TABLE naver_auto_report_snapshot(report_id INTEGER,possibility_id INTEGER,period_key TEXT,revision_fingerprint TEXT,generated_at TEXT,status TEXT,review_status TEXT);')
        c.execute('INSERT INTO naver_auto_account VALUES(?,?,1)',(42,D.TARGET_ACCOUNT))
        c.execute('INSERT INTO naver_auto_report_snapshot VALUES(1,?,?,?,?,?,?)',
            (D.TARGET_PID,D.PERIOD,'a'*64,'2026-10-11T05:00:00+00:00','ready','held'))
        c.commit();c.close()
        self.now=datetime(2026,10,11,6,tzinfo=timezone.utc)

    def tearDown(self):
        self.folder.cleanup()

    def collect(self):
        c=D.connect_reader(self.path)
        try:return D.collect_metadata(c,self.now)
        finally:c.close()

    def add_meta(self,key,value):
        c=sqlite3.connect(self.path);c.execute('INSERT INTO naver_auto_meta VALUES(?,?)',(key,value));c.commit();c.close()

    def add_audit(self,result,at='2026-10-11T16:51:45+09:00',action='learning-ai-generation'):
        c=sqlite3.connect(self.path)
        c.execute('INSERT INTO naver_auto_access_log(emp_idx,action,result,at) VALUES(?,?,?,?)',(987654,action,result,at))
        c.commit();c.close()

    def ready_value(self):
        value,_=self.collect()
        value['synthetic_preflight']=dict(status='not_performed',code='ACTOR_UNAVAILABLE',request_serialized=False,
            request_bytes=0,synthetic_transport_calls=0,learning_cases=0,conversion_complete=None,external_calls=0,draft_mutations=0)
        return value

    def test_no_reservation_no_draft_and_readonly(self):
        before=self.path.read_bytes()
        value,identity=self.collect()
        self.assertEqual(value['reservations']['count'],0)
        self.assertEqual(value['target_strategy']['version'],0)
        self.assertEqual(value['target_strategy']['state'],'empty')
        self.assertEqual(identity[0],1)
        self.assertEqual(before,self.path.read_bytes())

    def test_reservation_not_payment_or_account_attribution(self):
        self.add_meta('learning-call:'+'b'*32,json.dumps(dict(actor=987654,at='2026-10-11T14:30:00+09:00',
            reserved_microusd=31700,proof_hash='SENSITIVE-PROOF-MUST-NOT-LEAVE')))
        self.add_meta('learning-budget:2026-10','31700')
        value,_=self.collect()
        self.assertEqual(value['reservations']['count'],1)
        self.assertEqual(value['reservations']['total_reserved_microusd'],31700)
        self.assertIs(value['reservations']['actual_billed_amount'],False)
        self.assertEqual(value['reservations']['scope'],'instance_total_not_account_attributed')
        text=json.dumps(value)
        for private in ('987654','SENSITIVE-PROOF','b'*32):self.assertNotIn(private,text)

    def test_malformed_reservation_fails_closed_without_raw_output(self):
        self.add_meta('learning-call:'+'b'*32,'private-invalid-json')
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_RESERVATION_METADATA$'):self.collect()

    def test_fixed_window_closed_audit_codes_and_no_private_projection(self):
        for result in ('failed-http-400','failed-timeout','failed-reference-unavailable','failed-unknown','PRIVATE-BODY-API-KEY'):
            self.add_audit(result)
        self.add_audit('failed-tls',at='2026-10-11T16:49:59+09:00')
        self.add_audit('failed-network',at='2026-10-11T16:55:00+09:00')
        self.add_audit('failed-protocol',action='PRIVATE-ACTION')
        value=self.ready_value();D.validate_result(value)
        row=value['audit_window']
        self.assertEqual(row['matched_count'],4);self.assertEqual(row['unrecognized_count'],1)
        self.assertEqual(row['events'][0],dict(at='2026-10-11T07:51:45+00:00',code='http',http_status=400))
        self.assertEqual([x['code'] for x in row['events']],['http','timeout','reference-unavailable','unknown'])
        self.assertEqual(row['scope'],'instance_window_not_account_attributed')
        for private in ('PRIVATE','987654','failed-','emp_idx','log_id'):self.assertNotIn(private,json.dumps(value))

    def test_window_audit_row_limit_is_fail_closed(self):
        for _ in range(33):self.add_audit('failed-timeout')
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_WINDOW_LIMIT$'):self.collect()

    def test_window_reservations_are_aggregate_not_payment_or_target_attributed(self):
        for n,at in enumerate(('2026-10-11T16:49:59+09:00','2026-10-11T16:51:21+09:00','2026-10-11T16:52:00+09:00','2026-10-11T16:55:00+09:00')):
            self.add_meta('learning-call:'+str(n)*32,json.dumps(dict(actor=123456,at=at,reserved_microusd=90536,proof_hash='PRIVATE')))
        value=self.ready_value();D.validate_result(value)
        self.assertEqual(value['reservations']['count'],4)
        self.assertEqual(value['window_reservations'],dict(count=2,total_reserved_microusd=181072,
            first_at='2026-10-11T07:51:21+00:00',last_at='2026-10-11T07:52:00+00:00',
            scope='instance_window_not_account_attributed',actual_billed_amount=False))
        self.assertNotIn('123456',json.dumps(value));self.assertNotIn('PRIVATE',json.dumps(value))

    def test_only_target_claude_draft_history_count_leaves_database(self):
        import hashlib
        prefix='report-strategy-version:1:'+hashlib.sha256(b'42').hexdigest()+':'
        for n,(state,source) in enumerate((('draft','claude'),('approved','claude'),('draft','staff')),1):
            self.add_meta(prefix+f'{n:016d}',json.dumps(dict(version=n,state=state,source=source,document={'private':'PRIVATE-DRAFT'})))
        self.add_meta('report-strategy-version:999:'+hashlib.sha256(b'42').hexdigest()+':0000000000000001',
            json.dumps(dict(version=1,state='draft',source='claude',document={'private':'PRIVATE-OTHER'})))
        value=self.ready_value();D.validate_result(value)
        self.assertEqual(value['target_strategy']['claude_draft_versions'],1)
        self.assertNotIn('PRIVATE',json.dumps(value))

    def test_window_output_rejects_raw_fields_or_invalid_http_status(self):
        self.add_audit('failed-http-400')
        value=self.ready_value();value['audit_window']['events'][0]['body']='PRIVATE'
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_OUTPUT_FIELDS$'):D.validate_result(value)
        value=self.ready_value();value['audit_window']['events'][0]['http_status']=True
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_OUTPUT_SCOPE$'):D.validate_result(value)
        value=self.ready_value();value['audit_window']['events'][0]['at']='2026-10-11T07:55:00+00:00'
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_WINDOW_TIME$'):D.validate_result(value)

    def test_strategy_only_scalar_metadata(self):
        import hashlib
        key='report-strategy-head:1:'+hashlib.sha256(b'42').hexdigest()
        self.add_meta(key,json.dumps(dict(version=1,state='draft',source='claude',
            author={'actor':987654,'at':'2026-10-11T05:45:00+00:00'},document={'diagnosis':'PRIVATE-DRAFT-TEXT'})))
        value,_=self.collect()
        self.assertEqual(value['target_strategy']['version'],1)
        self.assertEqual(value['target_strategy']['source'],'claude')
        self.assertNotIn('PRIVATE-DRAFT',json.dumps(value));self.assertNotIn('987654',json.dumps(value))

    def test_ambiguous_target_refused(self):
        c=sqlite3.connect(self.path);c.execute('INSERT INTO naver_auto_account VALUES(43,?,1)',(D.TARGET_ACCOUNT,));c.commit();c.close()
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_TARGET_ACCOUNT$'):self.collect()

    def test_sqlite_write_attach_and_extension_refused(self):
        c=D.connect_reader(self.path)
        try:
            for query in ("DELETE FROM naver_auto_meta","PRAGMA query_only=OFF","ATTACH DATABASE ':memory:' AS another","SELECT load_extension('private')"):
                with self.subTest(query=query),self.assertRaises(sqlite3.DatabaseError):c.execute(query)
            self.assertEqual(c.total_changes,0)
        finally:c.close()

    def test_exact_package_and_no_credentials_before_rejection(self):
        package=dict(baseline=D.BASELINE,source_commit=D.SOURCE,source_tar_gz_sha256=D.ARCHIVE,
                     target='foodin-weekly-20260928',mode='metadata-and-synthetic-only')
        D.validate_package(package)
        for replacement in ({**package,'mode':'generate'}, {**package,'api_key':'PRIVATE'}, {**package,'source_commit':'a'*40}):
            with patch.object(D.os,'geteuid',side_effect=AssertionError('too early')):
                with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_PACKAGE_PIN$'):D.run(replacement,None,None)

    def test_script_clears_env_forces_stub_and_blocks_network(self):
        body=D.script().decode();compile(body,'<synthetic-diagnostic>','exec')
        for forbidden in ('provider_from_environment(',"get('ANTHROPIC_API_KEY')","get('CLAUDE_API_KEY')",'record_learning_strategy(', 'reserve_learning_call('):
            self.assertNotIn(forbidden,body)
        for required in ('os.environ.clear()','transport=stub','socket.socket.connect=no_network','http.client.HTTPSConnection.request=no_network',"writer=False",'PRAGMA query_only=ON','?mode=ro'):
            self.assertIn(required,body)

    def test_safe_log_projection_emits_fixed_counts(self):
        def capture(identity):
            if identity=='a'*64:
                return b'2026-10-11T07:51:00Z PRIVATE-LOG-TEXT\n'
            return ('2026-10-11T07:51:01Z WARNING naver_relay 관제 엔진 중계 실패: engine-timeout\n'
                    '2026-10-11T07:51:02Z WARNING naver_relay 관제 엔진 중계 실패: PRIVATE\n').encode()
        with patch.object(D,'capture_docker_logs',side_effect=capture):value=D.log_summary('a'*64,'b'*64)
        self.assertEqual(value['relay']['engine_timeout'],1)
        self.assertEqual(value['relay']['events'],[dict(at='2026-10-11T07:51:01+00:00',code='engine_timeout')])
        self.assertEqual(value['relay']['unmatched_entries'],1)
        self.assertEqual(value['engine']['unmatched_entries'],1)
        self.assertNotIn('PRIVATE',json.dumps(value))
        self.assertIs(value['engine']['available'],True)

    def test_log_projection_refuses_out_of_window_and_caps_events(self):
        raw=('2026-10-11T07:49:59Z WARNING naver_relay 관제 엔진 중계 실패: engine-timeout\n').encode()
        with patch.object(D,'capture_docker_logs',return_value=raw):value=D.log_summary('a'*64,'b'*64)
        self.assertEqual(value['relay']['events'],[]);self.assertEqual(value['relay']['unmatched_entries'],1)
        raw=('2026-10-11T07:51:01Z WARNING naver_relay 관제 엔진 중계 실패: engine-timeout\n'*33).encode()
        with patch.object(D,'capture_docker_logs',return_value=raw):value=D.log_summary('a'*64,'b'*64)
        self.assertFalse(value['relay']['available']);self.assertEqual(value['relay']['events'],[])

    def test_runtime_file_must_match_manifest_and_is_not_projected(self):
        import hashlib
        from types import SimpleNamespace
        root=Path(self.folder.name).resolve();path=root/'runtime.env'
        path.write_bytes(b'PRIVATE-FAKE-KEY=synthetic\nUNRELATED=preserve\n')
        release=SimpleNamespace(SECRET_ROOT=root,trusted_private_file=lambda p:None,
            sha=lambda data:hashlib.sha256(data).hexdigest())
        prepared={'files':{str(path):release.sha(path.read_bytes())}}
        before=path.read_bytes();fingerprint=D.runtime_fingerprint(release,prepared)
        self.assertEqual(fingerprint,prepared['files'][str(path)]);self.assertEqual(path.read_bytes(),before)
        path.write_bytes(before+b'CHANGED=1\n')
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_RUNTIME_CHANGED$'):D.runtime_fingerprint(release,prepared)

    def test_postflight_keeps_guards_and_returns_closed_separate_failures(self):
        from types import SimpleNamespace
        receipt=Path(self.folder.name)/'receipt';receipt.write_bytes(b'safe')
        release=SimpleNamespace(sha=lambda data:'a'*64)
        identities={'engine':'e','relay':'r'};before={'engine':{'pid':1},'relay':{'pid':2}}
        args=(SimpleNamespace(baseline=lambda:D.BASELINE),release,identities,before,receipt,'a'*64,{},'b'*64)
        with patch.object(D,'container',side_effect=lambda r,i:before['engine' if i=='e' else 'relay']),patch.object(D,'runtime_fingerprint',return_value='b'*64):
            self.assertEqual(D.postflight(*args),(None,True,True))
        for unit in ('engine','relay'):
            def changed(r,i):return {'pid':999} if i==identities[unit] else before['engine' if i=='e' else 'relay']
            with patch.object(D,'container',side_effect=changed),patch.object(D,'runtime_fingerprint',return_value='b'*64):
                self.assertEqual(D.postflight(*args),('CLAUDE_DIAG_POST_'+unit.upper(),True,True))
        with patch.object(D,'container',side_effect=lambda r,i:before['engine' if i=='e' else 'relay']),patch.object(D,'runtime_fingerprint',side_effect=ValueError('PRIVATE')):
            self.assertEqual(D.postflight(*args),('CLAUDE_DIAG_POST_RUNTIME',True,False))
        args=(SimpleNamespace(baseline=lambda:'different'),*args[1:])
        with patch.object(D,'container',side_effect=lambda r,i:before['engine' if i=='e' else 'relay']),patch.object(D,'runtime_fingerprint',return_value='b'*64):
            self.assertEqual(D.postflight(*args),('CLAUDE_DIAG_POST_LEGACY_BASELINE',False,True))
        self.assertEqual(D.fixed_error(ValueError('PRIVATE API KEY BODY')),'CLAUDE_DIAG_READ_FAILED')
        self.assertEqual(D.fixed_error(ValueError('CLAUDE_DIAG_PRIVATE_KEY_VALUE')),'CLAUDE_DIAG_READ_FAILED')

    def run_fake(self,raw,post_baseline=D.BASELINE):
        import hashlib
        from types import SimpleNamespace
        root=Path(self.folder.name).resolve();secret=root/'secrets';secret.mkdir()
        (secret/'runtime.env').write_bytes(b'PRIVATE-FAKE-KEY=synthetic\n')
        receipt=root/'receipt.json';sha=lambda data:hashlib.sha256(data).hexdigest()
        files={}
        for name in ('engine','relay'):
            for file in (root/('compose.naver-'+name+'.yml'),root/('preview-'+name+'.override.yml')):
                file.write_bytes(b'safe-compose');files[str(file)]=sha(file.read_bytes())
        files[str(secret/'runtime.env')]=sha((secret/'runtime.env').read_bytes())
        images={name:'sha256:'+str(n)*64 for n,name in enumerate(('engine','relay'),1)}
        identities={'engine':'e'*64,'relay':'f'*64}
        snapshots={name:dict(id=identities[name],image=images[name],running=True,restarting=False,pid=1,
            started='safe',restarts=0,user='10001:10001',project='naver-'+name,service='naver-'+name,
            source=D.SOURCE,readonly=True,mounts=[dict(Type='bind',Source='/var/lib/metainc/naver-engine',
            Destination='/var/lib/naver-engine')] if name=='engine' else []) for name in identities}
        prepared=dict(ok=True,source_commit=D.SOURCE,stage='prepared',
            package={'source_tar_gz_sha256':D.ARCHIVE,'baseline':D.BASELINE},files=files,images=images)
        receipt.write_text(json.dumps(prepared))
        def command(args,**kwargs):
            if args[:2]==['docker','exec']:
                self.assertEqual(args[2:6],['-i','--user','10001:10001',identities['engine']]);return raw
            return (identities[args[0]]+'\n').encode()
        release=SimpleNamespace(SECRET_ROOT=secret,sha=sha,trusted_private_file=lambda p:None,
            prepared_paths=lambda source:(root,receipt),unique=dict,compose=lambda p,name:[name],command=command)
        host=SimpleNamespace(baseline=unittest.mock.Mock(side_effect=[D.BASELINE,post_baseline]))
        package=dict(baseline=D.BASELINE,source_commit=D.SOURCE,source_tar_gz_sha256=D.ARCHIVE,
            target='foodin-weekly-20260928',mode='metadata-and-synthetic-only')
        with patch.object(D.os,'geteuid',return_value=0),patch.object(D,'container',side_effect=lambda r,i:snapshots['engine' if i==identities['engine'] else 'relay']),patch.object(D,'log_summary',return_value={}):
            return D.run(package,host,release)

    def test_validated_diagnostics_survive_postflight_baseline_failure(self):
        value=self.ready_value();D.validate_result(value)
        result=self.run_fake(json.dumps(value).encode(),post_baseline='changed')
        self.assertIs(result['ok'],False);self.assertIs(result['postflight_verified'],False)
        self.assertIsNone(result['primary_error'])
        self.assertEqual(result['postflight_error'],'CLAUDE_DIAG_POST_LEGACY_BASELINE')
        self.assertEqual(result['diagnostics'],value)
        self.assertIs(result['runtime_config_unchanged'],True)
        self.assertNotIn('PRIVATE',json.dumps(result))

    def test_primary_error_survives_simultaneous_postflight_failure(self):
        result=self.run_fake(b'{"failure":"CLAUDE_DIAG_SCHEMA"}',post_baseline='changed')
        self.assertIs(result['ok'],False);self.assertIsNone(result['diagnostics'])
        self.assertEqual(result['primary_error'],'CLAUDE_DIAG_SCHEMA')
        self.assertEqual(result['postflight_error'],'CLAUDE_DIAG_POST_LEGACY_BASELINE')
        self.assertIs(result['paid_provider_calls'],None)

    def test_log_capture_refuses_unfixed_identity_before_process(self):
        with patch.object(D.subprocess,'Popen',side_effect=AssertionError('must not run')):
            with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_CONTAINER_ID$'):D.capture_docker_logs('injected')

    def test_log_capture_enforces_memory_bound_and_reaps_synthetic_child(self):
        original=D.subprocess.Popen;children=[]
        def synthetic(args,**kwargs):
            self.assertEqual(args,['docker','logs','--since',D.WINDOW_START,'--until',D.WINDOW_END,'--tail','300','--timestamps','a'*64])
            self.assertEqual(kwargs['env'],{'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C'})
            child=original([sys.executable,'-c',"import os; os.write(1,b'x'*2097152)"],**kwargs)
            children.append(child);return child
        with patch.object(D.subprocess,'Popen',side_effect=synthetic):
            self.assertIsNone(D.capture_docker_logs('a'*64))
        self.assertEqual(len(children),1)
        self.assertIsNotNone(children[0].returncode)

    def test_log_projection_missing_or_oversized_sample_is_unavailable(self):
        for raw in (None,b'x\n'*301):
            with self.subTest(raw_missing=raw is None),patch.object(D,'capture_docker_logs',return_value=raw):
                result=D.log_summary('a'*64,'b'*64)
                self.assertFalse(result['engine']['available']);self.assertFalse(result['relay']['available'])


    def test_output_allowlist_rejects_raw_extra(self):
        value,_=self.collect()
        value['synthetic_preflight']=dict(status='refused',code='PROVIDER_MODEL_UNAVAILABLE',request_serialized=False,
            request_bytes=0,synthetic_transport_calls=0,learning_cases=1,conversion_complete=False,external_calls=0,draft_mutations=0)
        D.validate_result(value)
        value['raw_response']='PRIVATE'
        with self.assertRaisesRegex(ValueError,'^CLAUDE_DIAG_OUTPUT_FIELDS$'):D.validate_result(value)

    def test_missing_model_stops_before_provider_transport(self):
        from types import SimpleNamespace
        prepared=dict(payload={},learning_context={},plan_context={})
        reader=SimpleNamespace(prepare_learning_strategy=lambda *args:prepared)
        class Refused(Exception):pass
        strategy=SimpleNamespace(StrategyRefused=Refused,build_context=lambda *args,**kwargs:{'learning':{'cases':[{}]},'quality':{'conversion':{'complete':False}}})
        engine=SimpleNamespace(marketing_strategy=strategy,store=SimpleNamespace())
        provider=SimpleNamespace(AnthropicProvider=lambda *args,**kwargs:self.fail('provider must not be instantiated'))
        with patch.dict(sys.modules,{'naver_engine':engine,'naver_runtime.claude_provider':provider}):
            value=D.synthetic_preflight(reader,(1,'a'*64,'b'*64,0,5),self.now,None)
        self.assertEqual(value['code'],'PROVIDER_MODEL_UNAVAILABLE')
        self.assertEqual(value['synthetic_transport_calls'],0)

    def test_unavailable_actor_is_not_context_failure(self):
        from types import SimpleNamespace
        engine=SimpleNamespace(marketing_strategy=SimpleNamespace(StrategyRefused=ValueError),store=SimpleNamespace())
        provider=SimpleNamespace(AnthropicProvider=lambda *args,**kwargs:self.fail('provider must not be instantiated'))
        with patch.dict(sys.modules,{'naver_engine':engine,'naver_runtime.claude_provider':provider}):
            value=D.synthetic_preflight(None,(1,'a'*64,'b'*64,0,None),self.now,'model')
        self.assertEqual(value['status'],'not_performed')
        self.assertEqual(value['code'],'ACTOR_UNAVAILABLE')

    def test_actual_workflow_bundle_fits_symmetric_bounded_transport(self):
        import base64
        import gzip
        import re
        import zlib
        root=Path(__file__).resolve().parents[2]
        workflow=(root/'.github/workflows/debug-rank.yml').read_text().split('  claude-diagnostics:',1)[1]
        wire_limits=[int(value) for value in re.findall(r'assert len\(encoded\)<=([0-9]+)',workflow)]
        raw_limits=[int(value) for value in re.findall(r'0<len\(raw\)<=([0-9]+)',workflow)]
        decode_limits=[int(value) for value in re.findall(r'decoder.decompress\(base64.b64decode\(encoded,validate=True\),([0-9]+)\)',workflow)]
        self.assertEqual(wire_limits,[49152,49152])
        self.assertEqual(raw_limits,[131072,131072])
        self.assertEqual(decode_limits,[131073])
        names={'diagnostic':'naver_preview_claude_diagnostics.py','release':'naver_preview_release.py',
               'host':'naver_erp_tunnel_service_install.py'}
        package=dict(baseline=D.BASELINE,source_commit=D.SOURCE,source_tar_gz_sha256=D.ARCHIVE,
                     target='foodin-weekly-20260928',mode='metadata-and-synthetic-only')
        sources={name:(root/'backend/tools'/file).read_text() for name,file in names.items()}
        raw=json.dumps(dict(package=package,sources=sources)).encode()
        wire=base64.b64encode(gzip.compress(raw,mtime=0))
        self.assertLessEqual(len(raw),raw_limits[0])
        self.assertLessEqual(len(wire),wire_limits[0])
        decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
        decoded=decoder.decompress(base64.b64decode(wire,validate=True),decode_limits[0])
        self.assertEqual(decoded,raw)
        self.assertTrue(decoder.eof)
        self.assertFalse(decoder.unused_data or decoder.unconsumed_tail)
        self.assertIn('decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail',workflow)
        decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
        decoder.decompress(gzip.compress(raw,mtime=0)+b'forbidden-trailing',decode_limits[0])
        self.assertTrue(decoder.unused_data)
        decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
        decoded=decoder.decompress(gzip.compress(b'x'*decode_limits[0],mtime=0),decode_limits[0])
        self.assertGreater(len(decoded),raw_limits[0])

    def test_latest_reserve_actor_stays_internal(self):
        c=sqlite3.connect(self.path)
        c.execute("INSERT INTO naver_auto_access_log VALUES(1,987654,'learning-ai-reserve','ok','2026-10-11T16:51:00+09:00')");c.commit();c.close()
        value,identity=self.collect()
        self.assertEqual(identity[-1],987654)
        self.assertNotIn('987654',json.dumps(value))


if __name__=='__main__':unittest.main()
