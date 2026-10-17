"""Exact local product runtime migration; no operating DB, startup or HTTP.

Run with the reviewed product root and its backend on PYTHONPATH, followed by
the OPS backend. The target checkout and the one old store.py object are pinned.
"""
import ast
from contextlib import closing,redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from naver_engine import store as S

spec=importlib.util.spec_from_file_location('completion_runtime21',Path(__file__).parents[1]/'tools/naver_preview_completion_release.py')
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)
TARGET='e7649acfc71c25d7ae9c981a6ba036b77d97897b'
OLD='737a65952f2ddbc05a235cf2b139a4a11f4e7673'
OLD_STORE='a78560f42cd3e4ee774135b3b148f0e518ce59a41f1c9d74ae475769aa643856'


def old_contract(root):
    raw=subprocess.check_output(['git','show',OLD+':naver_engine/store.py'],cwd=root,timeout=30)
    if hashlib.sha256(raw).hexdigest()!=OLD_STORE:raise AssertionError('OLD_STORE_CHANGED')
    tree=ast.parse(raw);schema=[];columns=None;version=None;migrate=None
    for node in tree.body:
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name):
                    if target.id=='_SCHEMA':schema=list(ast.literal_eval(node.value))
                    elif target.id=='_REVISION_COLUMNS':columns=ast.literal_eval(node.value)
                    elif target.id=='SCHEMA_VERSION':version=ast.literal_eval(node.value)
        elif isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id=='_SCHEMA':schema+=list(ast.literal_eval(node.value))
    for node in ast.walk(tree):
        if isinstance(node,ast.FunctionDef) and node.name=='_migrate':migrate=node
    if version!=11 or not schema or columns is None or migrate is None:raise AssertionError('OLD_SCHEMA_CONTRACT')
    return schema,columns,migrate


def initialize(c,contract):
    schema,columns,_=contract
    for sql in schema:c.execute(sql)
    for table,additions in columns.items():
        existing={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
        for column,declaration in additions:
            if column not in existing:c.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+declaration)
    c.execute("INSERT INTO naver_auto_meta VALUES('schema_version','11')")
    for name,ddl in c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
        if name=='naver_auto_meta':continue
        fields=[];values=[]
        for _,column,kind,required,default,primary in c.execute('PRAGMA table_info('+name+')'):
            if default is not None and not primary:continue
            fields.append(column)
            if not required and not primary:values.append(None);continue
            enum=re.search(r'\b'+re.escape(column)+r'\s+IN\s*\(([^)]+)\)',ddl,re.I)
            fixed=re.search(r'\b'+re.escape(column)+r"\s*=\s*'([^']+)'",ddl,re.I)
            quoted=re.findall(r"'([^']+)'",enum.group(1)) if enum else []
            if quoted:value=quoted[0]
            elif fixed:value=fixed.group(1)
            elif kind.upper() in ('INTEGER','INT'):value=1
            elif kind.upper() in ('REAL','NUMERIC'):value=12.5
            elif column.endswith(('json','body','payload','document')):value='{}'
            elif column.endswith(('_at','_on')) or column in ('at','day'):value='2026-10-01T00:00:00+09:00'
            else:value='synthetic'
            values.append(value)
        if name=='naver_auto_alert_recipient':values[fields.index('next_try_at')]='2026-10-01T00:00:00+09:00'
        c.execute('INSERT INTO '+name+'('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',values)
    cases={'approved-plan':{'version':4,'state':'approved'},'separate-account':{'version':2,'state':'draft'},
        'expired':{'stage':'expired'},'holding':{'stage':'holding'},'reviewed-learning':{'state':'reviewed'},
        'approved-report':{'state':'approved','shared':{'version':5}},'zero-null':{'zero':0,'missing':None}}
    for key,value in cases.items():c.execute('INSERT INTO naver_auto_meta VALUES(?,?)',('synthetic:'+key,json.dumps(value,sort_keys=True)))


def rows(c,columns=None):
    columns=columns or {r[0]:[v[1] for v in c.execute('PRAGMA table_info('+r[0]+')')]
        for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")}
    values={}
    for table,names in columns.items():
        query='SELECT '+','.join(names)+' FROM '+table+(" WHERE key<>'schema_version'" if table=='naver_auto_meta' else '')
        values[table]=sorted(json.dumps(list(r),separators=(',',':'),allow_nan=False) for r in c.execute(query))
    return columns,values


class CompletionRuntime21Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(S.__file__).resolve().parents[1]
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=cls.root,timeout=30).decode().strip()
        if head!=TARGET:raise AssertionError('EXACT_TARGET_SOURCE_REQUIRED')
        if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=cls.root,timeout=30):raise AssertionError('TARGET_TRACKED_SOURCE_CHANGED')
        if S.SCHEMA_VERSION!=21 or C.TARGET_SCHEMA!=21:raise AssertionError('TARGET_SCHEMA_REQUIRED')
        cls.contract=old_contract(cls.root)

    def scene(self,mutation=None):
        with tempfile.TemporaryDirectory() as tmp,patch.object(socket.socket,'connect',side_effect=AssertionError('NO_NETWORK')):
            path=Path(tmp)/'synthetic.sqlite';connect=sqlite3.connect
            with closing(connect(path,isolation_level=None)) as c:
                initialize(c,self.contract);columns,before=rows(c);old_shape=C.schema_digest(c)
                with closing(connect(':memory:',isolation_level=None)) as expected:
                    c.backup(expected);st=object.__new__(S.Store);st._conn=expected
                    st._migrate();st._migrate();expected.set_authorizer(None)
                    if mutation:mutation(expected)
                    target_shape=C.schema_digest(expected)
            original=S.Store._migrate
            def migrate(st):
                original(st)
                if mutation:st._conn.set_authorizer(None);mutation(st._conn)
            def local_connect(name,*args,**kwargs):
                self.assertEqual(name,'/var/lib/naver-engine/engine.db')
                connection=connect(path,*args,**kwargs);self.addCleanup(connection.close);return connection
            output=io.StringIO()
            with patch.object(S.Store,'_migrate',migrate),patch.object(sqlite3,'connect',side_effect=local_connect),patch.object(sys,'path',list(sys.path)),redirect_stdout(output):
                try:exec(C.MIGRATION_SCRIPT,{'PINS':{'old':old_shape,'target':target_shape}})
                except SystemExit as error:self.assertEqual(error.code,1)
            receipt=json.loads(output.getvalue())
            with closing(connect(path,isolation_level=None)) as actual:
                self.assertEqual(rows(actual,columns)[1],before)
                if receipt['ok']:
                    found={r[0] for r in actual.execute("SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'naver_randomized_*'")}
                    self.assertEqual(found,C.RANDOMIZED_TABLES);self.assertEqual(len(found),12)
                    self.assertTrue(all(actual.execute('SELECT count(*) FROM '+t).fetchone()==(0,) for t in found))
                    st=object.__new__(S.Store);st._conn=actual
                    scope=dict(vars(S));scope.update(SCHEMA_VERSION=11,_SCHEMA=tuple(self.contract[0]),_REVISION_COLUMNS=self.contract[1])
                    exec(compile(ast.Module(body=[self.contract[2]],type_ignores=[]),'exact-old-store-migration','exec'),scope)
                    with self.assertRaises(S.StoreError):scope['_migrate'](st)
                    actual.set_authorizer(None);self.assertEqual(rows(actual,columns)[1],before)
                    self.assertEqual(actual.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone(),('21',))
            return receipt

    def test_actual_schema11_to21_preserves_every_old_column_row_and_adds_twelve_empty_tables(self):
        receipt=self.scene();self.assertTrue(receipt['ok']);self.assertEqual(receipt['schema'],21)
        self.assertEqual(receipt['old_schema'],11);self.assertTrue(receipt['preserved_rows']);self.assertTrue(receipt['migration_repeatable']);self.assertEqual(receipt['network_calls'],0)
        self.assertGreater(receipt['old_tables'],20);self.assertGreater(receipt['old_rows'],20)
        self.assertEqual(receipt['randomized_tables'],sorted(C.RANDOMIZED_TABLES));self.assertIs(receipt['randomized_tables_empty'],True)

    def test_exact_old_schema_supports_sort_free_stable_rowid_preservation(self):
        with closing(sqlite3.connect(':memory:',isolation_level=None)) as c:
            initialize(c,self.contract)
            tables=c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
            before={};old_columns={}
            for name,ddl in tables:
                self.assertNotRegex(ddl.upper(),r'WITHOUT\s+ROWID')
                columns=[r[1] for r in c.execute('PRAGMA table_info('+name+')')]
                self.assertFalse({'rowid','_rowid_','oid'} & {n.lower() for n in columns})
                old_columns[name]=columns
                query='SELECT rowid,'+','.join(columns)+' FROM '+name
                if name=='naver_auto_meta':query+=" WHERE key<>'schema_version'"
                query+=' ORDER BY rowid'
                plan=c.execute('EXPLAIN QUERY PLAN '+query).fetchall()
                self.assertFalse(any('TEMP B-TREE' in str(row).upper() for row in plan))
                before[name]=c.execute(query).fetchall()
            st=object.__new__(S.Store);st._conn=c;st._migrate();st._migrate();c.set_authorizer(None)
            for name,columns in old_columns.items():
                query='SELECT rowid,'+','.join(columns)+' FROM '+name
                if name=='naver_auto_meta':query+=" WHERE key<>'schema_version'"
                query+=' ORDER BY rowid'
                self.assertEqual(c.execute(query).fetchall(),before[name])

    def test_wrong_randomized_table_set_is_refused_even_with_matching_target_digest(self):
        for mutate in (lambda c:c.execute('DROP TABLE IF EXISTS naver_randomized_switch_event'),
            lambda c:c.execute('CREATE TABLE IF NOT EXISTS naver_randomized_extra(n INTEGER)')):
            with self.subTest(mutate=mutate):self.assertEqual(self.scene(mutate),{'ok':False,'step':'schema_after','code':'DB_TARGET_SCHEMA','error_kind':'ValueError'})

    def test_migration_cannot_create_assignments_or_cursor_rows(self):
        def seed(c):c.execute("INSERT OR IGNORE INTO naver_randomized_scan_cursor VALUES('synthetic','0','2026-10-12T00:00:00+09:00')")
        self.assertEqual(self.scene(seed),{'ok':False,'step':'schema_after','code':'DB_TARGET_SCHEMA','error_kind':'ValueError'})


if __name__=='__main__':unittest.main()
