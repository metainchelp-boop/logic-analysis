"""Synthetic journal bytes and stat only; never execute systemd or read a source DB."""
import builtins
import json
import hashlib
from pathlib import Path
import socket
import sqlite3
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.tools import naver_saved_exports_failure_inspect as I

NOW = 1791767400000000


def row(message, *, stamp=NOW-1000000, invocation='a'*32, kind='product', **extra):
    return json.dumps({'__REALTIME_TIMESTAMP': str(stamp), '_SYSTEMD_INVOCATION_ID': invocation,
        '_SYSTEMD_UNIT': I.UNITS[kind], 'MESSAGE': message, **extra}).encode()


class SavedExportsFailureInspectTests(unittest.TestCase):
    def test_latest_invocation_only_preserves_time_and_known_role_error(self):
        raw=b'\n'.join([row('PermissionError: private SECRET',stamp=NOW-10000000),
            row('Traceback /opt/metainc/naver-saved-exports/'+'1'*40+'/naver_product_export.py',invocation='b'*32,stamp=NOW-2000000),
            row("PermissionError: [Errno 13] Permission denied: '/var/lib/metainc/naver-product-source/bundle.json'",invocation='b'*32)])
        result=I._project(raw,'product',NOW)
        self.assertEqual(result,{'kind':'product','status':'observed','first_timestamp_us':NOW-2000000,
            'last_timestamp_us':NOW-1000000,'events':[
                {'timestamp_us':NOW-2000000,'path_roles':['code'],'error_labels':[]},
                {'timestamp_us':NOW-1000000,'path_roles':['product_output'],
                 'error_labels':['permission_error','permission_denied']}]})
        self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn('a'*32,json.dumps(result))
        self.assertNotIn('bundle.json',json.dumps(result));self.assertNotIn('/var',json.dumps(result))

    def test_latest_success_does_not_reuse_older_failure_or_other_unit(self):
        raw=b'\n'.join([row('Permission denied',stamp=NOW-3000000),
            row('ordinary completion',invocation='b'*32,stamp=NOW-2000000),
            row('PermissionError',kind='market')])
        result=I._project(raw,'product',NOW)
        self.assertEqual(result['events'],[]);self.assertEqual(result['last_timestamp_us'],NOW-2000000)

    def test_fixed_error_labels_and_exact_paths_without_prefix_or_traversal_guessing(self):
        text="/usr/bin/python3: can't open file '/opt/metainc/naver-saved-exports/a.py': Permission denied"
        self.assertEqual(I._labels(text),(['code'],['permission_denied','python_cannot_open']))
        self.assertEqual(I._labels("statvfs('/run/naver-saved-source') EXPORT_FAILED"),
            (['source_alias'],['statvfs','export_failed']))
        for value in ('/opt/metainc/naver-saved-exports-evil/x','/opt/metainc/naver-saved-exports/../private',
                      'https://private/run/naver-saved-source/x','/root/private/data.db'):
            self.assertEqual(I._labels(value),([],[]))
        self.assertEqual(I._labels('Failed at step NAMESPACE: read-only file system unable to open database file'),
            ([],['namespace','readonly','sqlite_open']))

    def test_exact_closed_exporter_failure_codes_without_raw_json_or_unknown_promotion(self):
        self.assertEqual(set(I.EXPORTER_FAILURE_LABELS),{'SOURCE_READ','SOURCE_PATH','SOURCE_LIMIT',
            'SOURCE_JSON','SOURCE_STATE','OUTPUT_WRITE','OUTPUT_PATH','EXPORT_INVALID','EXPORT_LIMIT','EXPORT_FAILED'})
        for code,label in I.EXPORTER_FAILURE_LABELS.items():
            with self.subTest(code=code):
                message=json.dumps({'status':'failed','code':code})
                self.assertEqual(I._labels(message),([],[label]))
                result=I._project(row(message),'product',NOW)
                self.assertEqual(result['events'][0]['error_labels'],[label])
                self.assertNotIn(code,json.dumps(result))
        for message in ('SOURCE_READ','Traceback: SOURCE_READ',
                '{"status":"failed","code":"SOURCE_READ","private":"SECRET"}',
                '{"status":"failed","code":"SOURCE_READ","code":"OUTPUT_WRITE"}',
                '{"status":"ok","code":"SOURCE_READ"}',
                '{"status":"failed","code":"SOURCE_READ_SECRET"}',
                '{"status":"failed","code":["SOURCE_READ"]}'):
            with self.subTest(message=message):
                self.assertEqual(I._labels(message),([],[]))

    def test_coordinator_codes_require_exact_closed_two_key_json_without_raw_promotion(self):
        self.assertEqual(I.COORDINATION_FAILURE_LABELS,{
            'COORDINATION_SOURCE_OPEN':'coordination_source_open',
            'COORDINATION_READER_FAILED':'coordination_reader_failed',
            'COORDINATION_TIMEOUT':'coordination_timeout',
            'COORDINATION_INVALID':'coordination_invalid',
            'COORDINATION_READER_STOP_FAILED':'coordination_reader_stop_failed'})
        for code,label in I.COORDINATION_FAILURE_LABELS.items():
            message=json.dumps({'status':'failed','code':code})
            with self.subTest(code=code):
                self.assertEqual(I._labels(message),([],[label]))
                result=I._project(row(message),'product',NOW)
                self.assertEqual(result['events'][0]['error_labels'],[label])
                self.assertNotIn(code,json.dumps(result))
            for value in ({'status':'ok','code':code},{'status':False,'code':code},
                {'status':'failed','code':code,'private':'SECRET'},
                {'status':'failed','code':code,'source_issue':'sqlite_open'},
                {'status':'failed','code':code+'_PRIVATE'}):
                self.assertEqual(I._labels(json.dumps(value)),([],[]))
            for value in (code,'Traceback '+code,
                '{"status":"failed","code":"'+code+'","code":"'+code+'"}'):
                self.assertEqual(I._labels(value),([],[]))

    def test_fixed_four_journals_keep_coordinator_and_reader_invocations_separate(self):
        self.assertEqual(I.UNITS,{'product':'naver-product-export.service','market':'naver-market-export.service',
            'product_reader':'naver-product-export-reader.service','market_reader':'naver-market-export-reader.service'})
        raw=b'\n'.join([
            row('{"status":"failed","code":"COORDINATION_READER_FAILED"}',kind='product'),
            row('{"status":"failed","code":"SOURCE_READ","source_issue":"sqlite_open"}',kind='product_reader'),
            row('PermissionError SECRET',kind='market_reader'),
            row('private unrelated failure',_SYSTEMD_UNIT='unrelated-private.service')])
        coordinator=I._project(raw,'product',NOW)
        reader=I._project(raw,'product_reader',NOW)
        self.assertEqual(coordinator['events'][0]['error_labels'],['coordination_reader_failed'])
        self.assertEqual(reader['events'][0]['error_labels'],['export_source_read','sqlite_open'])
        for result in (coordinator,reader):
            self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn('private',json.dumps(result))
            self.assertNotIn('MESSAGE',json.dumps(result));self.assertNotIn('.service',json.dumps(result))
        self.assertEqual(I._project(row('PermissionError',kind='product'),'product_reader',NOW)['status'],'no_invocation')

    def test_python_import_fatal_stdlib_and_loader_hints_are_closed_and_private(self):
        samples=(
            ("ModuleNotFoundError: No module named 'private_module_SECRET'",['python_module_missing']),
            ("ImportError: cannot import name 'SECRET' from '/root/private.py'",['python_import_error']),
            ('Fatal Python error: init_fs_encoding: failed to get the Python codec of the filesystem encoding',
                ['python_fatal','python_stdlib_init']),
            ('Could not find platform independent libraries <private_PREFIX>', ['python_stdlib_init']),
            ('Could not find platform dependent libraries <private_EXEC_PREFIX>', ['python_stdlib_init']),
            ('/opt/metainc/naver-saved-exports/'+'1'*40+'/python-export: error while loading shared libraries: '
                'private_LIBRARY: cannot open shared object file', ['dynamic_loader']),
            ('python-export: symbol lookup error: private_LIBRARY: undefined symbol: SECRET', ['dynamic_loader']),
            ('python-export: cannot execute binary file: Exec format error', ['binary_format']))
        for message,labels in samples:
            with self.subTest(labels=labels):
                result=I._project(row(message),'product',NOW)
                self.assertEqual(result['events'][0]['error_labels'],labels)
                output=json.dumps(result)
                for private in ('SECRET','/root','private_LIBRARY','private_PREFIX','MESSAGE','python-export'):
                    self.assertNotIn(private,output)
        self.assertEqual(I._labels("/opt/metainc/naver-saved-exports/a/python-export: can't open file 'private'"),
            (['code'],['python_cannot_open']))

    def test_latest_closed_exporter_code_does_not_reuse_old_permission_failure(self):
        raw=b'\n'.join([row('Permission denied',stamp=NOW-3000000),
            row('{"status":"failed","code":"SOURCE_READ"}',invocation='b'*32,stamp=NOW-1000000)])
        result=I._project(raw,'product',NOW)
        self.assertEqual(result['events'],[{'timestamp_us':NOW-1000000,'path_roles':[],
            'error_labels':['export_source_read']}])

    def test_expanded_closed_label_projection_remains_below_workflow_output_bound(self):
        message=' '.join(["PermissionError permission denied python-export: can't open file statvfs",
            'Failed at step NAMESPACE EXPORT_FAILED read-only file system unable to open database file',
            'No such file or directory failed at step NETWORK failed at step GROUP failed at step USER',
            'failed at step STDOUT failed at step EXEC failed at step CHDIR failed at step CAPABILITIES',
            'failed at step SECCOMP failed at step APPARMOR failed to create cgroup',
            'ModuleNotFoundError ImportError Fatal Python error: init_fs_encoding:',
            'error while loading shared libraries Exec format error',
            *(path+'/private' for _,path in I.PATH_ROLES)])
        raw=b'\n'.join(row(message,stamp=NOW-1000000-index) for index in range(32))
        result=I._project(raw,'product',NOW)
        self.assertEqual(len(result['events']),32)
        self.assertLess(len(json.dumps(result).encode()),32768)

    def test_all_four_maximal_closed_journals_fit_full_output_budget_and_keep_latest_events(self):
        message=' '.join(["PermissionError permission denied python-export: can't open file statvfs",
            'Failed at step NAMESPACE EXPORT_FAILED read-only file system unable to open database file',
            'No such file or directory failed at step NETWORK failed at step GROUP failed at step USER',
            'failed at step STDOUT failed at step EXEC failed at step CHDIR failed at step CAPABILITIES',
            'failed at step SECCOMP failed at step APPARMOR failed to create cgroup',
            'ModuleNotFoundError ImportError Fatal Python error: init_fs_encoding:',
            'error while loading shared libraries Exec format error SECRET',
            *(path+'/private' for _,path in I.PATH_ROLES)])
        def journal(kind, *, deadline):
            return b'\n'.join(row(message,kind=kind,stamp=NOW-1000000-index) for index in range(32)),None
        info=SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0,st_gid=0)
        with patch.object(I,'_journal',side_effect=journal),patch.object(I.time,'time_ns',return_value=NOW*1000),\
            patch.object(I.os,'lstat',return_value=info),patch.object(I.os,'stat',return_value=info),\
            patch.object(I.os.path,'realpath',side_effect=lambda path:path):
            result=I.inspect_host()
        output=json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)
        self.assertEqual(set(result),{'version','diagnostic_only','journals','paths','source_writes',
            'service_changes','network_calls','runtime_executables','source_files'})
        self.assertLessEqual(len(output.encode()),32768)
        self.assertEqual(len(result['journals']),4);self.assertEqual(len(result['paths']),14)
        for value in result['journals']:
            self.assertEqual(set(value),{'kind','status','first_timestamp_us','last_timestamp_us','events'})
            self.assertEqual(value['status'],'limited')
            self.assertLessEqual(len(json.dumps(value,sort_keys=True,separators=(',',':')).encode()),4096)
            self.assertEqual(value['first_timestamp_us'],NOW-1000031)
            self.assertEqual(value['last_timestamp_us'],NOW-1000000)
            self.assertGreater(len(value['events']),0);self.assertLess(len(value['events']),32)
            self.assertEqual(value['events'][-1]['timestamp_us'],NOW-1000000)
            self.assertEqual([event['timestamp_us'] for event in value['events']],
                list(range(NOW-1000000-len(value['events'])+1,NOW-1000000+1)))
        for private in ('SECRET','private','MESSAGE','/opt','/run','_SYSTEMD_INVOCATION_ID'):
            self.assertNotIn(private,output)

    def test_small_journal_is_preserved_and_limiting_never_mutates_invocation_projection(self):
        value=I._project(row('{"status":"failed","code":"COORDINATION_READER_FAILED"}'),'product',NOW)
        before=json.dumps(value,sort_keys=True)
        self.assertIs(I._limit_journal(value),value)
        self.assertEqual(json.dumps(value,sort_keys=True),before)
        large=I._project(b'\n'.join(row('PermissionError',stamp=NOW-1000000-index) for index in range(32)),'product',NOW)
        before=json.dumps(large,sort_keys=True)
        with patch.object(I,'MAX_JOURNAL_OUTPUT',512):limited=I._limit_journal(large)
        self.assertEqual(limited['status'],'limited')
        self.assertEqual(json.dumps(large,sort_keys=True),before)
        self.assertEqual(limited['first_timestamp_us'],large['first_timestamp_us'])
        self.assertEqual(limited['last_timestamp_us'],large['last_timestamp_us'])
        self.assertEqual(limited['events'][-1],large['events'][-1])

    def test_invalid_timestamp_id_message_and_duplicate_keys_never_fall_back(self):
        bad=[]
        for value in (True,1.0,'1e15','01791767400000000','-1',0,I.MAX_TIMESTAMP_US+1):
            bad.append(row('Permission denied',__REALTIME_TIMESTAMP=value))
        for value in (None,'B'*32,'a'*31,[],{}):
            bad.append(row('Permission denied',_SYSTEMD_INVOCATION_ID=value))
        bad.extend([row('x',MESSAGE=[]),b'{"MESSAGE":"first","MESSAGE":"second"}',b'NaN'])
        for value in bad:
            with self.subTest(value=value[:35]):
                result=I._project(row('old PermissionError',stamp=NOW-2000000)+b'\n'+value,'product',NOW)
                self.assertEqual(result['status'],'invalid');self.assertEqual(result['events'],[])

    def test_equal_latest_time_is_ambiguous_and_old_or_future_rows_not_used(self):
        result=I._project(row('PermissionError')+b'\n'+row('Permission denied',invocation='b'*32),'product',NOW)
        self.assertEqual(result['status'],'invalid')
        for stamp in (NOW-906000000,NOW+6000000):
            self.assertEqual(I._project(row('PermissionError',stamp=stamp),'product',NOW)['status'],'no_invocation')

    def test_json_count_line_and_total_bytes_are_bounded(self):
        for raw in (b'\n'.join([row('x')]*33),row('x'*I.MAX_LINE)):
            self.assertEqual(I._project(raw,'product',NOW)['status'],'limited')
        self.assertEqual(I._project(b'x'*(I.MAX_RAW+1),'product',NOW)['status'],'invalid')

    def test_inspection_has_only_fixed_stat_and_journal_calls_no_bodies_or_env(self):
        seen=[]
        def metadata(path):
            seen.append(path)
            return SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0,st_gid=0)
        with patch.object(I,'_python_metadata',return_value=[]) as runtime,patch.object(I,'_source_metadata',return_value=[]) as source,\
             patch.object(I,'_journal',return_value=(row('Permission denied'),None)) as command,\
             patch.object(I.time,'time_ns',return_value=NOW*1000),patch.object(I.time,'monotonic',return_value=100),\
             patch.object(I.os,'lstat',side_effect=metadata),\
             patch.object(builtins,'open',side_effect=AssertionError('body')),\
             patch.object(I.os,'open',side_effect=AssertionError('body')),\
             patch.object(I.os,'getenv',side_effect=AssertionError('environment')),\
             patch.object(sqlite3,'connect',side_effect=AssertionError('database')),\
             patch.object(socket,'socket',side_effect=AssertionError('network')):
            result=I.inspect_host()
        self.assertEqual(seen,[path for _,path in I.METADATA_PATHS])
        self.assertEqual([call.args for call in command.call_args_list],
            [('product',),('market',),('product_reader',),('market_reader',)])
        self.assertEqual([call.kwargs for call in command.call_args_list],[{'deadline':108}]*4)
        self.assertEqual(len(result['paths']),14)
        self.assertEqual([value['kind'] for value in result['journals']],list(I.UNITS))
        self.assertEqual(I.METADATA_PATHS[-2:],(
            ('product_reader_service','/etc/systemd/system/naver-product-export-reader.service'),
            ('market_reader_service','/etc/systemd/system/naver-market-export-reader.service')))
        self.assertFalse(result['source_writes']);self.assertFalse(result['service_changes'])
        self.assertEqual(result['network_calls'],0)
        self.assertNotIn('MESSAGE',json.dumps(result));self.assertNotIn('Invocation',json.dumps(result))

    def test_fixed_source_directory_db_wal_shm_lstat_only_closed_metadata(self):
        seen=[]
        def metadata(path):
            seen.append(path)
            if path.endswith('-wal'):raise FileNotFoundError('PRIVATE missing WAL')
            directory=path in ('/root','/root/logic-analysis-deploy',I.SOURCE_PATHS[0][1])
            return SimpleNamespace(st_mode=(stat.S_IFDIR if directory else stat.S_IFREG)|0o640,
                st_uid=1234,st_gid=10001)
        with patch.object(I.os,'lstat',side_effect=metadata),\
             patch.object(I.os,'stat',side_effect=AssertionError('follow')),\
             patch.object(I.os.path,'realpath',side_effect=AssertionError('resolve')),\
             patch.object(builtins,'open',side_effect=AssertionError('body')),\
             patch.object(I.os,'open',side_effect=AssertionError('body')),\
             patch.object(I.os,'getenv',side_effect=AssertionError('env')),\
             patch.object(sqlite3,'connect',side_effect=AssertionError('DB')),\
             patch.object(socket,'socket',side_effect=AssertionError('network')):
            result=I._source_metadata()
        self.assertEqual(seen,['/root','/root/logic-analysis-deploy',*(p for _,p in I.SOURCE_PATHS)])
        self.assertEqual([value['role'] for value in result],['source_directory','source_database','source_wal','source_shm'])
        self.assertTrue(all(set(value)=={'role','exists','kind','mode','uid','gid'} for value in result))
        self.assertEqual(result[1],{'role':'source_database','exists':True,'kind':'regular','mode':'0640','uid':1234,'gid':10001})
        self.assertEqual(result[2],{'role':'source_wal','exists':False,'kind':'missing','mode':None,'uid':None,'gid':None})
        self.assertNotIn('/root',json.dumps(result));self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertNotIn('logic_data',json.dumps(result))

    def test_source_symlink_or_unavailable_ancestor_never_follows_descendants(self):
        for bad in ('/root','/root/logic-analysis-deploy',I.SOURCE_PATHS[0][1]):
            for failure in ('symlink','missing','permission'):
                seen=[]
                def metadata(path):
                    seen.append(path)
                    if path==bad:
                        if failure=='missing':raise FileNotFoundError('PRIVATE')
                        if failure=='permission':raise PermissionError('PRIVATE')
                        return SimpleNamespace(st_mode=stat.S_IFLNK|0o777,st_uid=0,st_gid=0)
                    return SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0,st_gid=0)
                with self.subTest(bad=bad,failure=failure),patch.object(I.os,'lstat',side_effect=metadata):
                    result=I._source_metadata()
                    self.assertTrue(all(item['kind']=='blocked' for item in result[1:]))
                    self.assertFalse(any(path in seen for _,path in I.SOURCE_PATHS[1:]))
                    self.assertNotIn('PRIVATE',json.dumps(result))

    def test_source_database_symlink_is_reported_without_dereferencing(self):
        def metadata(path):
            mode=stat.S_IFLNK|0o777 if path==I.SOURCE_PATHS[1][1] else stat.S_IFDIR|0o755
            return SimpleNamespace(st_mode=mode,st_uid=0,st_gid=0)
        with patch.object(I.os,'lstat',side_effect=metadata),\
             patch.object(I.os,'stat',side_effect=AssertionError('follow')),\
             patch.object(I.os.path,'realpath',side_effect=AssertionError('resolve')):
            result=I._source_metadata()
        self.assertEqual(result[1]['kind'],'symlink')
        self.assertEqual(result[1]['mode'],'0777')

    def test_fixed_interpreter_targets_only_expose_scope_and_mode(self):
        def target(path):return '/root/private/runtime/bin/python' if path=='/usr/bin/python3' else path
        with patch.object(I.os,'lstat',return_value=SimpleNamespace(st_mode=stat.S_IFLNK|0o777,st_uid=0,st_gid=0)) as ls,\
             patch.object(I.os.path,'realpath',side_effect=target),\
             patch.object(I.os,'stat',return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o755,st_uid=0,st_gid=0)),\
             patch.object(builtins,'open',side_effect=AssertionError('no bodies')):
            rows=I._python_metadata()
        self.assertEqual([c.args[0] for c in ls.call_args_list],['/usr/bin/python3','/usr/bin/python3.10','/usr/bin/python3.11','/usr/bin/python3.12'])
        self.assertEqual(rows[0]['resolved_scope'],'private_home');self.assertEqual(rows[1]['resolved_scope'],'system')
        self.assertTrue(all(r['regular'] and r['mode']=='0755' for r in rows))
        self.assertNotIn('private/runtime',json.dumps(rows));self.assertNotIn('/root',json.dumps(rows))

    def test_missing_interpreters_expose_no_error_text(self):
        with patch.object(I.os,'lstat',side_effect=PermissionError('private error')):
            rows=I._python_metadata()
        self.assertTrue(all(not r['exists'] and r['resolved_scope']=='unknown' for r in rows))
        self.assertNotIn('private error',json.dumps(rows))

    def test_missing_unit_and_symlink_ancestor_are_labels_without_following_children(self):
        seen=[]
        def metadata(path):
            seen.append(path)
            if path=='/opt':return SimpleNamespace(st_mode=stat.S_IFLNK|0o777,st_uid=0,st_gid=0)
            if path.endswith('.service'):raise FileNotFoundError()
            return SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0,st_gid=0)
        with patch.object(I,'_journal',return_value=(b'',None)),patch.object(I.os,'lstat',side_effect=metadata):
            result=I.inspect_host()
        self.assertNotIn('/opt/metainc',seen)
        values={value['role']:value for value in result['paths']}
        self.assertEqual(values['code_directory']['kind'],'blocked')
        self.assertEqual(values['product_service']['kind'],'missing')
        self.assertFalse(values['product_service']['exists'])

    def test_journal_pipe_is_fixed_bounded_and_never_reads_stderr(self):
        process=Mock();process.stdout.fileno.return_value=7;process.wait.return_value=0;process.poll.return_value=0
        selector=Mock();selector.select.return_value=[object()]
        raw=row('Permission denied')
        with patch.object(I.subprocess,'Popen',return_value=process) as start,\
             patch.object(I.selectors,'DefaultSelector',return_value=selector),\
             patch.object(I.os,'read',side_effect=[raw,b'']):
            self.assertEqual(I._journal('product'),(raw,None))
        self.assertEqual(start.call_args.args[0],['/usr/bin/journalctl','--output=json','--no-pager',
            '-n','32','-u','naver-product-export.service','--since','-15min'])
        self.assertEqual(start.call_args.kwargs['env'],{'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','LC_ALL':'C'})
        self.assertEqual(start.call_args.kwargs['stderr'],I.subprocess.DEVNULL)
        selector.close.assert_called_once();process.stdout.close.assert_called_once();process.kill.assert_not_called()

    def test_reader_journal_commands_are_fixed_and_foreign_units_cannot_start_processes(self):
        self.assertEqual((I.TIMEOUT,I.MAX_RECORDS,I.MAX_RAW,I.MAX_LINE),(8,32,256*1024,32768))
        for kind in ('product_reader','market_reader'):
            process=Mock();process.stdout.fileno.return_value=7;process.wait.return_value=0;process.poll.return_value=0
            selector=Mock();selector.select.return_value=[object()]
            raw=row('{"status":"failed","code":"SOURCE_READ"}',kind=kind)
            with self.subTest(kind=kind),patch.object(I.subprocess,'Popen',return_value=process) as start,\
                patch.object(I.selectors,'DefaultSelector',return_value=selector),\
                patch.object(I.os,'read',side_effect=[raw,b'']):
                self.assertEqual(I._journal(kind),(raw,None))
                self.assertEqual(start.call_args.args[0],['/usr/bin/journalctl','--output=json','--no-pager',
                    '-n','32','-u',I.UNITS[kind],'--since','-15min'])
                self.assertEqual(start.call_args.kwargs['stderr'],I.subprocess.DEVNULL)
        for kind in ('private.service','product_reader.service','product\nmarket','',None,[],{}):
            with self.subTest(kind=kind),patch.object(I.subprocess,'Popen') as start,\
                patch.object(I.selectors,'DefaultSelector') as selector:
                self.assertEqual(I._journal(kind),(None,'unavailable'))
                start.assert_not_called();selector.assert_not_called()

    def test_expired_or_invalid_shared_deadline_starts_no_journal_process(self):
        for deadline in (99,100,True,'108',[],float('inf'),float('nan')):
            with self.subTest(deadline=deadline),patch.object(I.time,'monotonic',return_value=100),\
                patch.object(I.subprocess,'Popen') as start,patch.object(I.selectors,'DefaultSelector') as selector:
                self.assertEqual(I._journal('product_reader',deadline=deadline),(None,'unavailable'))
                start.assert_not_called();selector.assert_not_called()

    def test_failure_inspection_workflow_pins_current_source_twice_and_preserves_result_bound(self):
        root=Path(__file__).resolve().parents[2]
        source=root.joinpath('backend/tools/naver_saved_exports_failure_inspect.py').read_bytes()
        section=root.joinpath('.github/workflows/debug-rank.yml').read_text().split('  completion-export-failure-inspect:',1)[1].split('\n  completion-release:',1)[0]
        self.assertEqual(section.count(hashlib.sha256(source).hexdigest()),2)
        self.assertIn('if len(raw.encode())>32768:',section)
        self.assertIn("assert len(encoded)<=32768",section)
        self.assertLessEqual(len(__import__('base64').b64encode(source)),32768)

    def test_pipe_overflow_and_timeout_kill_child_without_returning_raw_data(self):
        for overflow in (True,False):
            process=Mock();process.stdout.fileno.return_value=7;process.poll.return_value=None
            selector=Mock();selector.select.return_value=[object()] if overflow else []
            with patch.object(I.subprocess,'Popen',return_value=process),\
                 patch.object(I.selectors,'DefaultSelector',return_value=selector),\
                 patch.object(I.os,'read',return_value=b'x'*(I.MAX_RAW+1)):
                result=I._journal('market')
            self.assertEqual(result,(None,'limited' if overflow else 'unavailable'))
            process.kill.assert_called_once();selector.close.assert_called_once()

    def test_closed_sqlite_issue_accepts_only_exact_source_read_shape(self):
        for issue, label in I.SQLITE_SOURCE_LABELS.items():
            raw=json.dumps({'status':'failed','code':'SOURCE_READ','source_issue':issue})
            roles,labels=I._labels(raw)
            self.assertEqual(roles,[])
            self.assertEqual(labels,['export_source_read',label])
        for value in (
            {'status':'failed','code':'SOURCE_READ','source_issue':'private message'},
            {'status':'ok','code':'SOURCE_READ','source_issue':'schema'},
            {'status':'failed','code':'OUTPUT_WRITE','source_issue':'schema'},
            {'status':'failed','code':'SOURCE_READ','source_issue':'schema','sql':'private'},
            {'status':'failed','code':'SOURCE_READ','source_issue':['schema']},
        ):
            self.assertEqual(I._labels(json.dumps(value)),([],[]))
        self.assertEqual(I._labels('{"status":"failed","code":"SOURCE_READ","source_issue":"schema","source_issue":"locked"}'),([],[]))

    def test_cli_refuses_arguments_without_executing_diagnostics(self):
        with patch.object(I.sys,'argv',['inspect','--unit','private']),patch.object(I,'inspect_host') as inspect,\
             patch.object(builtins,'print') as output:
            self.assertEqual(I.main(),2)
        inspect.assert_not_called()
        self.assertEqual(json.loads(output.call_args.args[0]),{'version':1,'error':'ARGUMENTS_NOT_SUPPORTED'})


if __name__=='__main__':unittest.main()
