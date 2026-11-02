"""Synthetic-only safety and wire checks; never contact a host or load credentials."""
import base64
import copy
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
A = module('inspection_aggregate')
L = module('inspection_aggregate_local')
OPENSSL = '/opt/homebrew/opt/openssl@3/bin/openssl' if Path('/opt/homebrew/opt/openssl@3/bin/openssl').is_file() else '/usr/bin/openssl'


def binding(cert=b'synthetic certificate'):
    return dict(run_id='123456', run_attempt=1, source=A.SOURCE, workflow_sha='a'*40,
        helper_sha256=hashlib.sha256((HERE/'inspection_aggregate.py').read_bytes()).hexdigest(),
        recipient_sha256=hashlib.sha256(cert).hexdigest(), nonce='b'*64)


def envelope(expected=None):
    return dict(version=1, binding=expected or binding(), observed_at='2026-11-03T00:00:00+00:00',
                stats=dict.fromkeys(A.STAT_KEYS, 0))


class ClosedContract(unittest.TestCase):
    def test_fixed_frame_and_closed_numeric_schema(self):
        value = envelope()
        self.assertEqual(A.validate_envelope(value, value['binding']), value)
        first, second = A.pack(value), A.pack(value)
        self.assertEqual(len(first), 16384)
        self.assertEqual(A.unpack(first), value)
        self.assertNotEqual(first, second)
        for mutation in ('unknown', 'boolean', 'negative', 'string', 'ratio', 'wrong_run', 'wrong_source'):
            bad = copy.deepcopy(value)
            if mutation == 'unknown': bad['stats']['customer_id'] = 1
            elif mutation == 'boolean': bad['stats']['policies_total'] = True
            elif mutation == 'negative': bad['stats']['policies_total'] = -1
            elif mutation == 'string': bad['stats']['policies_total'] = 'private-canary'
            elif mutation == 'ratio': bad['stats']['policies_total'] = 1
            elif mutation == 'wrong_run': bad['binding']['run_id'] = '987654'
            else: bad['binding']['source'] = 'e'*40
            with self.subTest(mutation=mutation), self.assertRaises(A.Refused):
                A.validate_envelope(bad, value['binding'])

    def test_strict_json_and_frame_reject_duplicates_nonfinite_lengths(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.assertRaises(A.Refused): A.decode(raw)
        good = A.pack(envelope())
        for raw in (good[:-1], good+b'x', b'WRONGMAG'+good[8:], A.MAGIC+b'\xff'*4+good[12:]):
            with self.assertRaises(A.Refused): A.unpack(raw)

    def test_log_exactly_one_bounded_canonical_cipher_frame(self):
        line = A.FRAME_PREFIX + base64.b64encode(b'synthetic ciphertext').decode()
        log = ('job\tstep\t2026-11-03T00:00:00Z '+line+'\n').encode()
        self.assertEqual(L.extract_frame(log), b'synthetic ciphertext')
        for bad in (b'', log+log, log.replace(b'=\n', b'===\n'), b'x'*(L.MAX_LOG+1), b'not a frame'):
            with self.subTest(size=len(bad)), self.assertRaises(L.A.Refused): L.extract_frame(bad)

    def test_command_is_bounded_and_errors_do_not_escape(self):
        with self.assertRaises(A.Refused):
            A.command([sys.executable, '-c', 'import os;os.write(1,b"x"*1000000)'], limit=4096)
        with self.assertRaises(A.Refused):
            A.command([sys.executable, '-c', 'import time;time.sleep(5)'], timeout=.05)

    def test_engine_identity_uses_only_closed_metadata_and_refuses_drift(self):
        value = dict(id='1'*64,image=A.IMAGE,pid=123,running=True,paused=False,restarting=False,
            started='2026-11-03T00:00:00Z',restarts=0,user='10001:10001',readonly=True,source=A.SOURCE,schema='21',
            data=[dict(Type='bind',Source=str(A.DATABASE.parent),Destination='/var/lib/naver-engine',RW=True)])
        calls=[]
        def runner(argv, **kwargs):
            calls.append(argv)
            return ('1'*64+'\n').encode() if 'ps' in argv else A.canonical(value)
        with patch.object(A,'command',side_effect=runner): self.assertEqual(A.engine_identity(),value)
        self.assertNotIn('Config.Env',str(calls));self.assertNotIn('exec',str(calls));self.assertNotIn('logs',str(calls))
        for key,replacement in (('source','e'*40),('image','sha256:'+'f'*64),('schema','22'),('restarting',True),('data',[])):
            old=value[key];value[key]=replacement
            with self.subTest(key=key),patch.object(A,'command',side_effect=runner),self.assertRaises(A.Refused): A.engine_identity()
            value[key]=old

    def test_child_is_fixed_image_readonly_without_credentials_or_engine_exec(self):
        argv=A.child_arguments(binding(),Path('/synthetic/helper.py'),Path('/synthetic/recipient.pem'))
        for sequence in (['--pull','never'],['--network','none'],['--user','10001:10001'],
                         ['--cap-drop','ALL'],['--security-opt','no-new-privileges'],
                         ['--pids-limit','32'],['--memory','512m']):
            self.assertIn(sequence,[argv[i:i+2] for i in range(len(argv)-1)])
        self.assertIn('--read-only',argv);self.assertIn(A.IMAGE,argv)
        mounts=[argv[i+1] for i,x in enumerate(argv) if x=='--mount']
        self.assertEqual(len(mounts),3);self.assertTrue(all(x.endswith(',readonly') for x in mounts))
        self.assertNotIn('docker.sock',str(mounts));self.assertNotIn('--env-file',argv);self.assertNotIn('exec',argv)

    def test_host_child_cleanup_and_identity_fences_with_closed_failure(self):
        expected=binding(b'certificate');expected['helper_sha256']=hashlib.sha256(b'helper').hexdigest()
        calls=[]
        def runner(argv,**kwargs):
            calls.append(argv)
            if 'ps' in argv:return b''
            if 'create' in argv:return ('d'*64+'\n').encode()
            if 'start' in argv:return b'NAVER_INSPECTION_REFUSED=source_unavailable\n'
            if 'inspect' in argv:return A.canonical(dict(id='d'*64,name='/naver-inspection-123456-1',image=A.IMAGE,
                binding=hashlib.sha256(A.canonical(expected)).hexdigest()))
            if 'rm' in argv:return ('d'*64+'\n').encode()
            raise AssertionError('unexpected command')
        with patch.object(A.sys,'platform','linux'),patch.object(A.os,'geteuid',return_value=0), \
             patch.object(A,'limits'),patch.object(A.signal,'alarm'),patch.object(A,'verify_release') as manifest, \
             patch.object(A,'deployment_lock',return_value=contextlib.nullcontext()), \
             patch.object(A,'engine_identity',return_value={'fixed':True}) as identity, \
             patch.object(A,'database_identity',return_value=(1,2,3)),patch.object(A,'command',side_effect=runner), \
             patch.object(A,'safe_file',side_effect=lambda p,n:b'certificate' if p.name=='recipient.pem' else b'helper'):
            with self.assertRaisesRegex(A.Refused,'^source_unavailable$'):A.run(expected)
        self.assertEqual(manifest.call_count,2);self.assertEqual(identity.call_count,2)
        self.assertEqual(sum('rm' in call for call in calls),1)
        self.assertEqual(calls[-1][-3:],['rm','--force','d'*64])

    def test_deploy_lock_is_existing_shared_nonblocking_and_never_written(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'lock';path.write_bytes(b'synthetic existing lock');path.chmod(0o600)
            before=path.read_bytes()
            with patch.object(A,'safe_parents'):
                with A.deployment_lock(path,owner=os.geteuid()):
                    with path.open('rb') as other:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with path.open('rb') as other:
                    fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    with self.assertRaisesRegex(A.Refused,'^host_refused$'):
                        with A.deployment_lock(path,owner=os.geteuid()):self.fail('entered busy lock')
                self.assertEqual(path.read_bytes(),before)
                path.unlink()
                with self.assertRaises(FileNotFoundError):
                    with A.deployment_lock(path,owner=os.geteuid()):self.fail('created lock')
                self.assertFalse(path.exists())

    def test_lost_create_receipt_recovers_only_exact_binding_and_image(self):
        expected=binding();calls=[]
        value=dict(id='d'*64,name='/naver-inspection-123456-1',image=A.IMAGE,
                   binding=hashlib.sha256(A.canonical(expected)).hexdigest())
        def runner(argv,**kwargs):
            calls.append(argv)
            if 'ps' in argv:return ('d'*64+'\n').encode()
            if 'inspect' in argv:return A.canonical(value)
            if 'rm' in argv:return b''
            raise AssertionError('unexpected command')
        with patch.object(A,'command',side_effect=runner):A.cleanup_child(['docker'],expected,None)
        self.assertEqual(calls[-1],['docker','rm','--force','d'*64])
        for key,bad in (('image','sha256:'+'e'*64),('binding','e'*64),('name','/foreign'),('id','e'*64)):
            original=value[key];value[key]=bad;calls.clear()
            with self.subTest(key=key),patch.object(A,'command',side_effect=runner),self.assertRaisesRegex(A.Refused,'^cleanup_refused$'):
                A.cleanup_child(['docker'],expected,None)
            self.assertFalse(any('rm' in call for call in calls));value[key]=original

    def test_create_timeout_runs_confined_recovery_and_post_checks(self):
        expected=binding(b'certificate');expected['helper_sha256']=hashlib.sha256(b'helper').hexdigest()
        calls=[]
        def runner(argv,**kwargs):
            calls.append(argv)
            if 'ps' in argv:return b''
            if 'create' in argv:raise A.Refused('deadline')
            raise AssertionError('unexpected command')
        with patch.object(A.sys,'platform','linux'),patch.object(A.os,'geteuid',return_value=0), \
             patch.object(A,'limits'),patch.object(A.signal,'alarm'),patch.object(A,'verify_release') as manifest, \
             patch.object(A,'deployment_lock',return_value=contextlib.nullcontext()), \
             patch.object(A,'engine_identity',return_value={'fixed':True}) as identity, \
             patch.object(A,'database_identity',return_value=(1,2,3)),patch.object(A,'command',side_effect=runner), \
             patch.object(A,'cleanup_child') as cleanup, \
             patch.object(A,'safe_file',side_effect=lambda p,n:b'certificate' if p.name=='recipient.pem' else b'helper'):
            with self.assertRaisesRegex(A.Refused,'^deadline$'):A.run(expected)
        self.assertEqual(manifest.call_count,2);self.assertEqual(identity.call_count,2)
        self.assertEqual(cleanup.call_count,1);self.assertIsNone(cleanup.call_args.args[-1])

    def test_manifest_hash_and_exact_two_generated_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);rows=[]
            for number in range(167):
                name='synthetic-%03d.py'%number;raw=('value=%d\n'%number).encode()
                (root/name).write_bytes(raw);rows.append((name,hashlib.sha256(raw).digest()))
            h=hashlib.sha256()
            for name,digest in rows:h.update(name.encode()+b'\0'+digest)
            expected=h.hexdigest()
            for name in ('preview-engine.override.yml','preview-relay.override.yml'):(root/name).write_bytes(b'public fixture')
            original=A.safe_file
            with patch.object(A,'safe_parents'),patch.object(A,'safe_file',side_effect=lambda p,n:original(p,n,owner=os.geteuid())):
                self.assertEqual(A.verify_release(root,expected),expected)
                (root/'third.override.yml').write_bytes(b'not allowed')
                with self.assertRaises(A.Refused):A.verify_release(root,expected)
                (root/'third.override.yml').unlink();(root/'synthetic-000.py').write_bytes(b'changed')
                with self.assertRaises(A.Refused):A.verify_release(root,expected)

    def test_safe_file_rejects_symlink_hardlink_and_writable_source(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'source';file.write_bytes(b'synthetic')
            self.assertEqual(A.safe_file(file,100,owner=os.geteuid()),b'synthetic')
            link=Path(temp)/'link';link.symlink_to(file)
            with self.assertRaises(OSError):A.safe_file(link,100,owner=os.geteuid())
            link.unlink();os.link(file,link)
            with self.assertRaises(A.Refused):A.safe_file(file,100,owner=os.geteuid())
            link.unlink();file.chmod(0o666)
            with self.assertRaises(A.Refused):A.safe_file(file,100,owner=os.geteuid())

    def test_main_suppresses_python_and_native_private_canaries(self):
        program = '''import importlib.util,os,sys
s=importlib.util.spec_from_file_location('p',sys.argv[1]);a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
sys.argv=['probe']
def bad(binding):
 print('private-canary-python');print('private-canary-stderr',file=sys.stderr)
 os.write(1,b'private-canary-native');os.write(2,b'private-canary-native-error')
 raise RuntimeError('private-canary-exception')
a.run=bad
sys.exit(a.main())
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(HERE/'inspection_aggregate.py')],
            input=A.canonical(binding()), capture_output=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b'NAVER_INSPECTION_REFUSED=internal_refused\n')
        self.assertEqual(result.stderr, b'')

    def test_audit_blocks_network_and_file_writes(self):
        program = '''import importlib.util,sys,socket,tempfile,os
s=importlib.util.spec_from_file_location('p',sys.argv[1]);a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
sys.addaudithook(a.forbid_side_effects)
count=0
for action in (lambda:socket.socket(),lambda:open(sys.argv[2],'w')):
 try:action()
 except a.Refused:count+=1
assert count==2
print('BLOCKED')
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'must-not-exist'
            result = subprocess.run([sys.executable, '-I', '-B', '-c', program,
                str(HERE/'inspection_aggregate.py'), str(path)], capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(path.exists())
            self.assertEqual(result.stdout, b'BLOCKED\n')

    def test_preflight_limits_and_readonly_sql(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'synthetic.db'
            c = sqlite3.connect(path)
            c.executescript('CREATE TABLE naver_auto_meta(key,value);INSERT INTO naver_auto_meta VALUES("schema_version","21");'
                'CREATE TABLE naver_auto_account(a);CREATE TABLE naver_auto_manual_read(a);'
                'CREATE TABLE naver_auto_inspection_job(cycle_day,progress_json);')
            c.commit();c.close()
            read = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
            try:
                A.preflight_rows(read, A.datetime(2026,11,3).date())
                with self.assertRaises(sqlite3.OperationalError):
                    read.execute('INSERT INTO naver_auto_account VALUES(1)')
                read.set_progress_handler(lambda: 1, 1)
                with self.assertRaises(sqlite3.OperationalError):
                    read.execute('WITH RECURSIVE x(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM x WHERE n<1000000) SELECT sum(n) FROM x').fetchone()
            finally: read.close()
            c=sqlite3.connect(path)
            c.executemany('INSERT INTO naver_auto_account VALUES(?)', [(i,) for i in range(A.MAX_POLICIES+1)])
            c.commit()
            with self.assertRaises(A.Refused): A.preflight_rows(c, A.datetime(2026,11,3).date())
            c.close()

    def test_sqlite_feature_guard_preserves_trusted_schema_boundary(self):
        c=sqlite3.connect(':memory:')
        flags={row[0]:row[5] for row in c.execute('PRAGMA function_list')};c.close()
        if all(flags.get(name,0)&0x200000 for name in ('json_extract','json_valid')):
            A.require_sqlite_runtime()
        else:
            with self.assertRaisesRegex(A.Refused,'^sqlite_refused$'):A.require_sqlite_runtime()

    def test_workflow_scope_is_single_sealed_probe(self):
        text = (HERE.parents[1]/'.github/workflows/naver-inspection-aggregate.yml').read_text()
        self.assertIn('unshare --net -- python3 -I -B', text)
        self.assertIn('timeout -k 2s 35s', text)
        self.assertIn('"$REF" = refs/heads/main', text)
        self.assertIn('"$ATTEMPT" = 1', text)
        self.assertNotIn('upload-artifact', text)
        self.assertNotIn('docker exec', text)
        self.assertNotIn('customer_id:', text)
        self.assertNotIn('target_id:', text)
        self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}', text)
        deploy = (HERE.parents[1]/'.github/workflows/deploy.yml').read_text()
        self.assertIn("- '.github/workflows/naver-inspection-aggregate.yml'", deploy)
        checks = (HERE.parents[1]/'.github/workflows/naver-tools-check.yml').read_text()
        self.assertEqual(checks.count("'.github/workflows/naver-inspection-aggregate.yml'"),2)


class CryptoAndLocalReceipt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='synthetic-inspection-crypto-')
        cls.folder = Path(cls.temp.name).resolve();cls.folder.chmod(0o700)
        cls.cert, cls.key = cls.folder/'recipient.pem', cls.folder/'recipient.key'
        old = os.umask(0o077)
        try:
            subprocess.run([OPENSSL, 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-days', '1',
                '-subj', '/CN=synthetic-inspection-test', '-keyout', str(cls.key), '-out', str(cls.cert)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        finally: os.umask(old)
        cls.expected = binding(cls.cert.read_bytes())

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    @staticmethod
    def runner(argv, **kwargs):
        if argv[0] == '/usr/bin/openssl': argv = [OPENSSL, *argv[1:]]
        return A.command(argv, **kwargs)

    def seal(self, value=None):
        return A.encrypt(value or envelope(self.expected), self.cert, self.expected, runner=self.runner)

    def test_cms_aead_roundtrip_fixed_padding_and_cipher_tamper(self):
        line = self.seal()
        cipher = L.extract_frame(line.encode())
        def decrypt(data):
            return self.runner(['/usr/bin/openssl','cms','-decrypt','-binary','-inform','DER',
                '-recip',str(self.cert),'-inkey',str(self.key)],data=data,limit=20480)
        plain = decrypt(cipher)
        self.assertEqual(len(plain), A.FRAME_BYTES)
        self.assertEqual(A.validate_envelope(A.unpack(plain), self.expected), envelope(self.expected))
        changed = bytearray(cipher);changed[-1] ^= 1
        with self.assertRaises(A.Refused): decrypt(bytes(changed))
        varied = envelope(self.expected)
        varied['stats']['daily_generation_age_seconds'] = 123456
        self.assertEqual(len(L.extract_frame(self.seal(varied).encode())), len(cipher))

    def test_encrypt_error_never_returns_plaintext(self):
        def broken(*args, **kwargs): raise RuntimeError('private-canary')
        with self.assertRaisesRegex(A.Refused, '^crypto_refused$'):
            A.encrypt(envelope(self.expected), self.cert, self.expected, runner=broken)
        expected = dict(self.expected, recipient_sha256='0'*64)
        with self.assertRaises(A.Refused): A.encrypt(envelope(expected), self.cert, expected, runner=self.runner)

    def metadata(self):
        return dict(id=123456, run_attempt=1, event='workflow_dispatch', head_branch='main', status='completed',
            conclusion='success', path=L.WORKFLOW, repository={'full_name':L.REPO},
            actor={'login':'metainchelp-boop'}, triggering_actor={'login':'metainchelp-boop'}, head_sha='a'*40)

    def receiver(self, metadata=None, line=None):
        metadata = metadata or self.metadata();line = line or self.seal()
        def runner(argv, **kwargs):
            if argv[0] == 'gh':
                if argv[1] == 'run': return ('job\tstep\t'+line+'\n').encode()
                if '/contents/' in argv[-1]:
                    return A.canonical(dict(encoding='base64', path=L.HELPER,
                        content=base64.b64encode((HERE/'inspection_aggregate.py').read_bytes()).decode()))
                return A.canonical(metadata)
            return self.runner(argv, **kwargs)
        return runner

    def test_private_receipt_binds_exact_run_and_permissions(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as temp:
            directory = Path(temp)/'receipt'
            value = L.receive('123456', 'b'*64, self.cert, self.key, directory, runner=self.receiver())
            self.assertEqual(value, envelope(self.expected))
            self.assertEqual(set(p.name for p in directory.iterdir()), {'run.log','sealed.cms','binding.json','aggregate.json'})
            self.assertTrue(all(stat.S_IMODE(p.stat().st_mode)==0o600 for p in directory.iterdir()))
            with self.assertRaises(FileExistsError):
                L.receive('123456','b'*64,self.cert,self.key,directory,runner=self.receiver())

    def test_replayed_binding_metadata_and_unsafe_key_are_refused(self):
        for field, val in (('run_attempt',2),('head_branch','other'),('conclusion','failure'),('head_sha','bad')):
            bad=self.metadata();bad[field]=val
            with self.subTest(field=field), self.assertRaises(L.A.Refused): L.validate_run(bad,'123456')
        with tempfile.TemporaryDirectory(dir=self.folder) as temp:
            directory=Path(temp)/'wrong-nonce'
            with self.assertRaises(L.A.Refused):
                L.receive('123456','c'*64,self.cert,self.key,directory,runner=self.receiver())
            self.assertFalse((directory/'aggregate.json').exists())
            link=Path(temp)/'linked.key';link.symlink_to(self.key)
            with self.assertRaises(L.A.Refused): L.private_read(link,8192,secret=True)


if __name__ == '__main__': unittest.main()
