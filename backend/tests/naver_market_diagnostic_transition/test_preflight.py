import copy
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import preflight as P
import transition as T

import test_sources as portable_sources


def source_bytes():
    return portable_sources.baseline_sources()


class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = source_bytes()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.root.chmod(0o700)
        (self.root / 'receipts').mkdir(mode=0o700)
        self.binding, self.h = P._modules(self.sources)
        self.plan = self.h.build_plan(**T.PROFILE)
        self.folder = self.root / 'prepared'; self.folder.mkdir(mode=0o700)
        self.scripts = {'naver_product_export.py': self.sources['product_exporter'],
                        'naver_market_export.py': self.sources['market_exporter']}
        self.content = self.h.artifacts(self.plan, self.scripts, self.binding.PINS['scripts'])
        self.content[self.h.INTERPRETER] = b'\x7fELFsynthetic-interpreter'
        self.source = dict(directory_device=1, directory_inode=2, database_device=1, database_inode=3)
        self.runtime = dict(exporter_uid=65534, reader_gid=10001, source_gid=None)
        self.file_identity = dict(device=1, inode=4, size=25, mtime_ns=5, ctime_ns=6,
                                  uid=0, gid=10001, mode=0o550, links=1)
        self.receipt = dict(version=4, operation_id='a'*32, plan=self.plan,
            plan_sha256=T.sha(T.canonical(self.plan)), source_identity=self.source,
            runtime_identity=self.runtime, manifest={k:T.sha(v) for k,v in self.content.items()},
            companion_sha256=T.sha(self.content[self.h.COMPANION]),
            interpreter=dict(source_path='/usr/bin/python3.9',source_identity=self.file_identity,
                             staged_identity=self.file_identity,sha256=T.sha(self.content[self.h.INTERPRETER])))
        self.installed = {str(self.h.INSTALL / self.plan['ops_commit'] / k)
            if k in (*self.h.SCRIPTS,*self.h.COORDINATORS.values(),self.h.INTERPRETER)
            else str(self.h.UNITS / k): v for k,v in self.content.items() if k != self.h.COMPANION}
        self.state = dict(version=1,operation_id=self.receipt['operation_id'],state='installed',
            created_files=sorted(self.installed),
            created_directories=[str(self.h.INSTALL / self.plan['ops_commit'])],
            timers_enabled=True,engine_verified=False,interpreter_identity=self.file_identity,
            sources=dict(product={},market={}))
        self.operating = dict(ok=True,stage='internal_ready',source_commit=T.OPERATING_SOURCE,
            previous_commit='513e52eaee4d1bb722461961639cd588df9080cd',
            operation_id=T.OPERATING_OPERATION,database_policy='preserve-in-place',execution_enabled=False)
        self.operating_path = self.root / 'receipts' / ('preview-start-'+T.OPERATING_SOURCE+'.json')
        self.exports_path = self.root / 'receipts' / ('completion-exports-'+P.EXPORT_SOURCE+'.json')
        self.export_value = dict(source_commit=P.EXPORT_SOURCE,package_sha256=T.sha(T.canonical(P.PACKAGE)),
            pins_sha256=T.sha(T.canonical(self.binding.PINS)),exports=self.receipt)
        self.write(self.operating_path,T.canonical(self.operating))
        self.write(self.exports_path,T.canonical(self.export_value))
        self.calls = []
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        for name,value in [('ROOT',self.root),('OWNER',os.getuid()),('GROUP',os.getgid())]:
            self.stack.enter_context(patch.object(P,name,value))
        self.stack.enter_context(patch.object(P._Release,'ROOT',self.root))
        self.stack.enter_context(patch.object(P,'_modules',return_value=(self.binding,self.h)))
        self.stack.enter_context(patch.object(self.h,'_prepared',side_effect=self.prepared))
        self.stack.enter_context(patch.object(self.h,'_regular',side_effect=self.regular))
        self.stack.enter_context(patch.object(self.h,'_source_identity',side_effect=lambda _:self.source))
        self.stack.enter_context(patch.object(self.h,'_identity',side_effect=lambda _:self.runtime))
        self.stack.enter_context(patch.object(self.h,'_binary',side_effect=self.binary))
        self.verify = self.stack.enter_context(patch.object(self.h,'verify',side_effect=AssertionError('forbidden')))

    def write(self,path,body):
        path.write_bytes(body); path.chmod(0o600)

    def prepared(self,receipt):
        self.calls.append('prepared')
        if not T.same(receipt,self.receipt): raise ValueError('private unexpected receipt')
        return self.plan,self.folder,self.content

    def regular(self,path,**kwargs):
        self.calls.append(('regular',str(path)))
        if path == self.folder/'prepared.json': return self.h._json(self.receipt)
        if path == self.folder/'installed.json': return self.h._json(self.state)
        return self.installed[str(path)]

    def binary(self,path,**kwargs):
        self.calls.append(('binary',str(path)))
        assert kwargs == dict(mode=0o550,group=10001)
        return self.installed[str(path)],self.file_identity

    def collect(self): return P.collect(self.sources)

    def test_original_binding_and_eight_hashes_without_verify_or_commands(self):
        with patch.object(P._Release,'command',side_effect=AssertionError('forbidden')):
            proofs,private=self.collect()
        self.assertEqual(set(proofs),T.PROOF_KEYS)
        for value in proofs.values(): T.digest(value)
        self.assertEqual(proofs['operating_receipt_sha256'],T.sha(self.operating_path.read_bytes()))
        self.assertEqual(proofs['exports_receipt_sha256'],T.sha(self.exports_path.read_bytes()))
        self.assertEqual(proofs['prepared_receipt_sha256'],T.sha(self.h._json(self.receipt)))
        self.assertEqual(proofs['installed_receipt_sha256'],T.sha(self.h._json(self.state)))
        manifest={path:T.sha(body) for path,body in self.installed.items()}
        self.assertEqual(proofs['original_manifest_sha256'],T.sha(T.canonical(manifest)))
        self.assertEqual(proofs['source_identity_sha256'],T.sha(T.canonical(self.source)))
        self.assertEqual(proofs['runtime_identity_sha256'],T.sha(T.canonical(self.runtime)))
        self.assertEqual(private.runtime_uid,65534)
        self.assertEqual(private.plan,self.plan)
        self.assertEqual(private.install_directory,self.h.INSTALL/self.plan['ops_commit'])
        self.assertEqual(private.units_directory,self.h.UNITS)
        self.assertEqual(private.prepared_directory,self.folder)
        self.verify.assert_not_called()
        self.assertEqual(self.calls.count('prepared'),2)

    def test_bad_public_pin_refused_before_modules_or_host_reads(self):
        for key in self.sources:
            wrong=dict(self.sources);wrong[key]+=b'\n'
            with patch.object(P,'_modules') as modules, self.assertRaisesRegex(P.Invalid,'PREFLIGHT_SOURCE'):
                P.collect(wrong)
            modules.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_receipt_duplicate_nan_and_operating_boolean_alias_are_rejected(self):
        original=self.operating_path.read_bytes()
        for raw in (b'{"ok":true,"ok":false}',b'{"ok":NaN}',T.canonical(dict(self.operating,ok=1)),
                    T.canonical(dict(self.operating,execution_enabled=0))):
            self.write(self.operating_path,raw)
            with self.assertRaises(P.Invalid): self.collect()
        self.write(self.operating_path,original)

    def test_original_binding_rejects_wrong_package_and_source(self):
        for key,value in [('package_sha256','0'*64),('source_commit',T.OPERATING_SOURCE),('pins_sha256','0'*64)]:
            self.write(self.exports_path,T.canonical(dict(self.export_value,**{key:value})))
            with self.assertRaisesRegex(P.Invalid,'PREFLIGHT_UNAVAILABLE'): self.collect()

    def test_installed_script_or_interpreter_drift_is_rejected(self):
        for name in ('naver_market_export.py',self.h.INTERPRETER):
            path=str(self.h.INSTALL/self.plan['ops_commit']/name)
            original=self.installed[path];self.installed[path]+=b'X'
            with self.assertRaisesRegex(P.Invalid,'PREFLIGHT_INSTALLED'): self.collect()
            self.installed[path]=original

    def test_source_runtime_and_interpreter_identity_drift_is_rejected(self):
        for method,value in [('_source_identity',dict(self.source,database_inode=99)),
                             ('_identity',dict(self.runtime,exporter_uid=1))]:
            with patch.object(self.h,method,return_value=value),self.assertRaisesRegex(P.Invalid,'PREFLIGHT_IDENTITY'):
                self.collect()
        with patch.object(self.h,'_binary',return_value=(self.content[self.h.INTERPRETER],dict(self.file_identity,inode=99))),self.assertRaisesRegex(P.Invalid,'PREFLIGHT_INSTALLED'):
            self.collect()

    def test_staged_script_cannot_be_self_consistently_rebound(self):
        self.content['naver_market_export.py']+=b'changed'
        with self.assertRaisesRegex(P.Invalid,'PREFLIGHT_PREPARED'): self.collect()

    def test_installed_journal_pair_state_and_inventory_are_closed(self):
        original=copy.deepcopy(self.state)
        for changes in (dict(operation_id='b'*32),dict(state='failed'),dict(timers_enabled=1),
                        dict(created_files=self.state['created_files'][:-1]),
                        dict(created_directories=self.state['created_directories']+['/unexpected']),dict(extra=True)):
            self.state=dict(original,**changes)
            with self.assertRaisesRegex(P.Invalid,'PREFLIGHT_INSTALLED'): self.collect()
        self.state=original

    def test_fixed_receipt_snapshot_rejects_symlink_hardlink_permissions_and_size(self):
        original=self.operating_path.read_bytes()
        self.operating_path.chmod(0o644)
        with self.assertRaisesRegex(P.Invalid,'PREFLIGHT_FILE'): self.collect()
        self.operating_path.chmod(0o600)
        alias=self.root/'alias';os.link(self.operating_path,alias)
        with self.assertRaisesRegex(P.Invalid,'PREFLIGHT_FILE'): self.collect()
        alias.unlink();self.operating_path.unlink();alias.write_bytes(original);alias.chmod(0o600)
        self.operating_path.symlink_to(alias)
        with self.assertRaisesRegex(P.Invalid,'PREFLIGHT_FILE'): self.collect()
        self.operating_path.unlink();self.write(self.operating_path,b'x'*(P.MAX_RECEIPT+1))
        with self.assertRaisesRegex(P.Invalid,'PREFLIGHT_FILE'): self.collect()

    def test_binding_reads_same_captured_receipt_buffer_and_post_metadata_is_checked(self):
        original=self.h._identity
        def changed(plan):
            self.write(self.exports_path,T.canonical(dict(self.export_value,extra='changed')))
            return self.runtime
        with patch.object(self.h,'_identity',side_effect=changed),self.assertRaisesRegex(P.Invalid,'PREFLIGHT_CHANGED'):
            self.collect()
        self.assertIn('prepared',self.calls)

    def test_private_receipt_whitespace_hash_is_raw_and_proofs_have_no_raw_context(self):
        self.write(self.operating_path,json.dumps(self.operating,indent=2).encode())
        proofs,private=self.collect()
        self.assertEqual(proofs['operating_receipt_sha256'],T.sha(self.operating_path.read_bytes()))
        self.assertNotEqual(proofs['operating_receipt_sha256'],T.sha(T.canonical(self.operating)))
        raw=T.canonical(proofs)
        for secret in (b'/root/',b'logic_data.db',b'private',b'sources',b'prepared_receipt":'):
            self.assertNotIn(secret,raw)
        self.assertFalse(hasattr(private,'binding'))

    def test_unknown_lower_error_is_closed_and_command_adapter_refuses(self):
        with patch.object(self.h,'_identity',side_effect=RuntimeError('private source value')):
            with self.assertRaises(P.Invalid) as error: self.collect()
            self.assertEqual(error.exception.args,('PREFLIGHT_UNAVAILABLE',))
        with self.assertRaisesRegex(P.Invalid,'PREFLIGHT_COMMAND_FORBIDDEN'):
            P._Release().command(['systemctl','start','anything'])


if __name__=='__main__':unittest.main()
