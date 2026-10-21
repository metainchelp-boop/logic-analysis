"""One actual prepare/native ID mismatch; no services or private source reads."""
import ast
import hashlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import test_sources as Sources

# Fixed repository resolver; no workspace search or environment fallback.
OPS=Sources._ROOT
RUNTIME=OPS/'backend/tools/naver_market_diagnostic_transition'
import transition as T
import preflight as B
import entrypoint as Entry

def module(raw,name):
    m=types.ModuleType(name)
    exec(compile(raw,'<pinned-'+name+'>','exec'),m.__dict__)
    return m

_candidate=Sources._read_at(Sources._ROOT,'current_guard')
if hashlib.sha256(_candidate).hexdigest()!='6a9377b6ed3d511e054c1234b0b830314331ddadad3b5887b79a8c36e611e5d8':
    raise ValueError('PREPARED_DELTA_CANDIDATE')
if _candidate.count(b"RUN = '38852615204'")!=1:
    raise ValueError('PREPARED_DELTA_INVERSE')
_baseline=_candidate.replace(b"RUN = '38852615204'",b"RUN = '38850467092'")
if hashlib.sha256(_baseline).hexdigest()!='670f62086a89134f66117541bad5537a21c5c15cd2fcef5478b3792a99d62eb7':
    raise ValueError('PREPARED_DELTA_BASELINE')
BASE=module(_baseline,'baseline_current_guard')
NEW=module(_candidate,'candidate_current_guard')
PREPARE_ID='38852615204'


class PreparedRunDeltaTests(unittest.TestCase):
    def setUp(self):
        producer=OPS/'backend/tools/naver_preview_completion_release.py'
        raw=producer.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'3be9c0360a6f75192455d6b139317319dd111b4e404628505ae62783b37977e2')
        tree=ast.parse(raw);prepare=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prepare')
        assignments=[n for n in ast.walk(prepare) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='receipt' for t in n.targets)]
        self.assertEqual(len(assignments),1)
        receipt=assignments[0].value
        self.assertIsInstance(receipt,ast.Dict)
        package_expr=next(v for k,v in zip(receipt.keys,receipt.values) if isinstance(k,ast.Constant) and k.value=='package')
        # Evaluate only the pinned writer's package dict comprehension, not prepare().
        package=dict(baseline=BASE.BASELINE,source_commit=T.OPERATING_SOURCE,source_tar_gz_sha256=BASE.ARCHIVE,
            ciphertext_sha256=BASE.CIPHER,run_id=PREPARE_ID,operation='code-prepare')
        self.writer_package=eval(compile(ast.Expression(package_expr),'<exact-public-writer-package-only>','eval'),{'__builtins__':{}},{'package':package})
        self.assertEqual(self.writer_package,{k:v for k,v in package.items() if k!='operation'})
        self.prepared=dict(ok=True,stage='prepared',source_commit=T.OPERATING_SOURCE,package=self.writer_package,
            images={'engine':'sha256:'+'a'*64,'relay':'sha256:'+'b'*64})
        self.started=dict(ok=True,stage='internal_ready',source_commit=T.OPERATING_SOURCE,
            previous_commit='513e52eaee4d1bb722461961639cd588df9080cd',operation_id=T.OPERATING_OPERATION,
            database_policy='preserve-in-place',execution_enabled=False)
        self.previous={k:'c'*64 for k in T.PROOF_KEYS}
        self.previous['operating_receipt_sha256']=T.sha(T.canonical(self.started))
        self.snapshot_calls=[]
        def snapshot(path):
            self.snapshot_calls.append(path.name)
            return T.canonical(self.started if path.name.startswith('preview-start-') else self.prepared),('fixture',)
        self.enterContext(mock.patch.object(B,'trusted_dir'))
        self.enterContext(mock.patch.object(B,'snapshot',side_effect=snapshot))
        self.command=mock.Mock(side_effect=AssertionError('No Docker/systemd/journal command permitted'))

    def test_pinned_writer_prepare_id_baseline_red_candidate_green(self):
        self.assertEqual(BASE.RUN,'38850467092');self.assertEqual(NEW.RUN,PREPARE_ID)
        self.assertEqual(self.writer_package['run_id'],PREPARE_ID)
        with self.assertRaisesRegex(T.Invalid,'CURRENT_PREPARED'):BASE.CurrentGuard(self.previous,command=self.command)._receipts()
        hashes,images=NEW.CurrentGuard(self.previous,command=self.command)._receipts()
        self.assertEqual(hashes,(T.sha(T.canonical(self.prepared)),T.sha(T.canonical(self.started))))
        self.assertEqual(images,self.prepared['images']);self.command.assert_not_called()

    def test_other_run_ids_and_type_aliases_rejected_with_all_other_pins_fixed(self):
        for bad in ('38850467092','38852615205',38852615204,True,False,None,'038852615204',38852615204.0):
            with self.subTest(run_id=bad):
                self.prepared['package']['run_id']=bad
                with self.assertRaisesRegex(T.Invalid,'CURRENT_PREPARED'):NEW.CurrentGuard(self.previous,command=self.command)._receipts()
        self.command.assert_not_called()

    def test_writer_top_level_contract_and_every_prepared_guard_remain_exact(self):
        # This assignment/image comprehension is AST-identical to the actual
        # historical 31f29b report-progress writer (evidence.closed.json).
        raw=(OPS/'backend/tools/naver_preview_completion_release.py').read_bytes()
        tree=ast.parse(raw)
        prepare=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prepare')
        assignments={t.id:n.value for n in ast.walk(prepare) if isinstance(n,ast.Assign)
                     for t in n.targets if isinstance(t,ast.Name) and t.id in ('receipt','images')}
        image_expr=assignments['images']
        self.assertEqual(ast.literal_eval(image_expr.generators[0].iter),('engine','relay'))
        receipt=assignments['receipt']
        pairs=[(k,v) for k,v in zip(receipt.keys,receipt.values) if k.value!='files']
        projected=ast.Dict(keys=[k for k,v in pairs],values=[v for k,v in pairs])
        package=dict(self.writer_package,operation='code-prepare')
        writer=eval(compile(ast.fix_missing_locations(ast.Expression(projected)),
                    '<exact-public-writer-nonfile-fields-only>','eval'),{'__builtins__':{}},
                    {'TARGET_COMMIT':T.OPERATING_SOURCE,'package':package,'images':self.prepared['images']})
        self.assertEqual(writer,self.prepared)
        good=T.canonical(writer)
        bad_cases=[[],dict(writer,ok=1),dict(writer,ok=False),dict(writer,stage='internal_ready'),
                   dict(writer,source_commit='0'*40),dict(writer,package=[]),
                   dict(writer,images=[]),dict(writer,images={'engine':'sha256:'+'a'*64}),
                   dict(writer,images=dict(writer['images'],extra='sha256:'+'c'*64))]
        for key in self.writer_package:
            bad_cases.append(dict(writer,package={k:v for k,v in self.writer_package.items() if k!=key}))
            bad_cases.append(dict(writer,package=dict(self.writer_package,**{key:False})))
        for index,value in enumerate(bad_cases):
            with self.subTest(boundary=index):
                self.prepared=value
                with self.assertRaisesRegex(T.Invalid,'CURRENT_PREPARED'):
                    NEW.CurrentGuard(self.previous,command=self.command)._receipts()
        for value in (False,'sha256:'+'A'*64,'a'*64):
            self.prepared=B.decode(good)
            self.prepared['images']['engine']=value
            with self.subTest(image_boundary=type(value).__name__):
                with self.assertRaisesRegex(T.Invalid,'CURRENT_IMAGE'):
                    NEW.CurrentGuard(self.previous,command=self.command)._receipts()
        self.prepared=B.decode(good)
        NEW.CurrentGuard(self.previous,command=self.command)._receipts()
        self.command.assert_not_called()

    def test_writer_receipt_failure_precedes_diagnostic_preparation_and_controller(self):
        self.assertEqual(self.prepared['package']['run_id'],PREPARE_ID)
        systemd=types.SimpleNamespace(original_preflight=mock.Mock(return_value=True))
        with mock.patch.object(Entry.sys,'platform','linux'),mock.patch.object(Entry.os,'geteuid',return_value=0),\
             mock.patch.object(Entry.B,'collect',return_value=(self.previous,types.SimpleNamespace(runtime_uid=65534))),\
             mock.patch.object(Entry.T,'compile_plan',return_value=({},{})),\
             mock.patch.object(Entry.S,'Systemd',return_value=systemd),mock.patch.object(Entry,'G',BASE),\
             mock.patch.object(BASE.S,'bounded',self.command),\
             mock.patch.object(Entry.D,'prepare') as provision,mock.patch.object(Entry.P,'Publication') as publication,\
             mock.patch.object(Entry.J,'Ledger') as ledger,mock.patch.object(Entry.T,'Controller') as controller:
            with self.assertRaisesRegex(T.Invalid,'CURRENT_PREPARED'):
                Entry.run(dict(version=1,action='apply',apply_id='f82dc65cfe3c4de89864916cc0b687fd',rollback_id='f4e00eb5d5574fd787739b158e6e17d3'),sources={},baseline_sources={})
            systemd.original_preflight.assert_called_once()
            for item in (provision,publication,ledger,controller):item.assert_not_called()
        self.command.assert_not_called()


if __name__=='__main__':unittest.main()
