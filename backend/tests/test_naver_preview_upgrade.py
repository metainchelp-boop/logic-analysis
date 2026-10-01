import importlib.util
import hashlib
import json
import os
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('upgrade', Path(__file__).parents[1]/'tools/naver_preview_upgrade.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
NOW = datetime(2026, 10, 1, 14, tzinfo=timezone(timedelta(hours=9)))


class RequestTest(unittest.TestCase):
    def test_only_exact_same_day_owner_approved_bounded_request_is_accepted(self):
        good = {'request_id': 'a'*32, 'hold_id': 1, 'hold_sha256': 'b'*64, 'expected_rows': 1437,
                'approved_by': 0, 'expires_at': (NOW+timedelta(hours=1)).isoformat(), 'max_seconds': 300}
        self.assertEqual(M.validate_request(good, NOW), good)
        for changes in ({'extra': 1}, {'request_id': '../wrong'}, {'approved_by': 1}, {'approved_by': False},
                        {'hold_id': True}, {'expected_rows': 100001}, {'max_seconds': 601},
                        {'expires_at': NOW.isoformat()}, {'expires_at': (NOW+timedelta(hours=4)).isoformat()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                M.validate_request(dict(good, **changes), NOW)

    def test_invalid_apply_never_calls_host_or_release(self):
        host, release, lifecycle = Mock(), Mock(), Mock()
        with self.assertRaises(ValueError):
            M.apply({'release': {}, 'request': {}, 'extra': True}, host, release, lifecycle)
        self.assertEqual(host.mock_calls, [])
        self.assertEqual(release.mock_calls, [])

    def test_private_file_reader_rejects_symlinks_hardlinks_and_public_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'fixture'
            path.write_bytes(b'fixture');path.chmod(0o600)
            args={'uid':os.getuid(),'gid':os.getgid(),'mode':0o600}
            self.assertEqual(M.read_file(path,**args),b'fixture')
            linked=path.parent/'link';linked.symlink_to(path)
            with self.assertRaises(ValueError):
                M.read_file(linked,**args)
            path.chmod(0o666)
            with self.assertRaises(ValueError):
                M.read_file(path,**args)
            path.chmod(0o600);os.link(path,path.parent/'hardlink')
            with self.assertRaises(ValueError):
                M.read_file(path,**args)

    def test_probe_retries_transient_relay_race_but_not_a_business_write_gate_failure(self):
        release=Mock();attempts=[]
        def read(path,route,method='GET'):
            attempts.append((route,method))
            if route=='/_engine/health':
                return 200,{},b'{"state":"bootstrap_running"}'
            if route=='/naver/':
                if sum(r=='/naver/' for r,_ in attempts)==1:
                    raise OSError('not-yet-listening')
                return 200,{'referrer-policy':'no-referrer','cache-control':'no-store'},b'verificationNotice'
            return (403 if method=='POST' else 401),{},b''
        release.unix_request.side_effect=read
        with patch.object(M.time,'sleep') as sleep:
            M.probe(release)
            self.assertEqual(sleep.call_count,1)
        release.unix_request.side_effect=lambda path,route,method='GET': (
            (200,{},b'{}') if route=='/_engine/health' else
            (200,{'referrer-policy':'no-referrer','cache-control':'no-store'},b'verificationNotice') if route=='/naver/' else
            (200 if method=='POST' else 401,{},b''))
        with patch.object(M.time,'sleep') as sleep,self.assertRaisesRegex(ValueError,'BUSINESS_WRITE_NOT_DENIED'):
            M.probe(release)
        sleep.assert_not_called()


class UpgradeTest(unittest.TestCase):
    def scenario(self, failure=None, mode='apply'):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            root.joinpath('receipts').mkdir()
            root.joinpath('releases').mkdir()
            unit_dir=root/'units';unit_dir.mkdir()
            secret=root/'secrets';secret.mkdir()
            owner_map={'runtime.env':(0,0),'backup-recipient.pem':(10001,10001),
                       'backup-upload-key':(10001,10001),'backup-known-hosts':(10001,10001)}
            for name in owner_map:
                (secret/name).write_bytes(b'PRIVATE_CONFIG_SENTINEL')
            ls=importlib.util.spec_from_file_location('lifecycle_fixture',Path(__file__).parents[1]/'tools/naver_preview_lifecycle.py')
            life=importlib.util.module_from_spec(ls);ls.loader.exec_module(life)
            life.UNIT_DIR=unit_dir;life.TMPFILES=root/'tmpfiles.conf'
            commit='b'*40;baseline='a'*64
            package={'baseline':baseline,'source_commit':commit,'source_tar_gz_sha256':'c'*64,
                     'ciphertext_sha256':'d'*64,'run_id':'123456','operation':'upgrade-prepare'}
            commands=[];writes=[];state={'engine':M.OLD_COMMIT,'relay':M.OLD_COMMIT};triggered=False
            def image(name,source):
                return 'sha256:'+({'engine':'e','relay':'f'}[name] if source==M.OLD_COMMIT else {'engine':'1','relay':'2'}[name])*64
            def compose(path,name):
                return ['docker','compose','--project-name','naver-'+name,'-f',str(path/('compose.naver-'+name+'.yml'))]
            def execute(args,**kwargs):
                nonlocal triggered
                commands.append(args)
                if args[:3]==['docker','image','inspect']:
                    name,source=args[-1].removeprefix('metainc/naver-').split(':')
                    if args[-2]=='{{json .Id}}':
                        return json.dumps(image(name,source)).encode()
                    return json.dumps({'id':image(name,source),'user':'10001:10001','source':'wrong' if failure=='image' else source}).encode()
                if args[:2]==['docker','compose']:
                    name=args[3].removeprefix('naver-')
                    source=Path(args[5]).parent.name.removeprefix('naver-')
                    if 'ps' in args:
                        return (('3' if name=='engine' else '4')*64).encode()
                    if '--force-recreate' in args:
                        if failure=='recreate' and source==commit and name=='relay' and not triggered:
                            triggered=True
                            raise TimeoutError('PRIVATE_ERROR_SENTINEL')
                        if failure=='rollback_recreate' and source==M.OLD_COMMIT and name=='engine':
                            raise RuntimeError('PRIVATE_ERROR_SENTINEL')
                        state[name]=source
                    return b''
                if args[:2]==['docker','inspect']:
                    name='engine' if args[-1]=='3'*64 else 'relay'
                    return json.dumps({'id':args[-1],'image':image(name,state[name]),'running':True,
                       'started':'fixture','restarts':0,'project':'naver-'+name,'service':'naver-'+name}).encode()
                if args[:2]==['/usr/bin/systemctl','show']:
                    return b'enabled' if args[-2]=='UnitFileState' else b'active'
                if args[:2]==['/usr/bin/systemctl','start'] and failure=='start' and not triggered:
                    triggered=True;raise TimeoutError('PRIVATE_ERROR_SENTINEL')
                if args[:2]==['/usr/bin/systemctl','stop'] and failure=='stop' and not triggered:
                    triggered=True;raise TimeoutError('PRIVATE_ERROR_SENTINEL')
                if args[:2]==['openssl','cms']:
                    return b'{}'
                return b''
            def write(path,body,**kwargs):
                writes.append((Path(path),kwargs))
                with Path(path).open('xb') as output:
                    output.write(body)
                Path(path).chmod(kwargs.get('mode',0o600))
            def request(path,route,method='GET'):
                if route=='/_engine/health':
                    return 200,{},b'{"state":"bootstrap_running","last_tick":null}'
                if route=='/naver/':
                    return 200,{'referrer-policy':'no-referrer','cache-control':'no-store'},b'verificationNotice'
                return (200 if failure in ('probe','rollback_recreate') and method=='POST' else 403 if method=='POST' else 401),{},b''
            release=types.SimpleNamespace(ROOT=root,SECRET_ROOT=secret,SECRET_OWNERS=owner_map,
                prepared_paths=lambda source:(root/'releases'/('naver-'+source),root/'receipts'/('preview-'+source+'.json')),
                unique=dict,sha=lambda b:hashlib.sha256(b).hexdigest(),command=execute,compose=compose,
                validate_package=lambda package:None,trusted_dir=lambda *a,**k:None,write_new=write,unix_request=request)
            release.received_ciphertext=lambda *args:b'synthetic-ciphertext'
            release.trusted_private_file=lambda *args:None
            release.validate_payload=lambda *args:(b'synthetic-source',[
                {'path':str(secret/name),'uid':uid,'gid':gid,'content':'CHANGED' if failure=='secret' else 'PRIVATE_CONFIG_SENTINEL'}
                for name,(uid,gid) in owner_map.items()])
            release.source_members=lambda *args:(Mock(),[])
            def extract(source,path):
                path.mkdir();(path/'deploy').mkdir()
                for file in ('compose.naver-engine.yml','compose.naver-relay.yml','deploy/naver-engine-backup.override.yml'):
                    (path/file).write_bytes(b'new fixture compose')
            release.extract_source=extract
            old_files=None
            for source in ((M.OLD_COMMIT,) if mode=='prepare' else (M.OLD_COMMIT,commit)):
                path=root/'releases'/('naver-'+source);path.mkdir();(path/'deploy').mkdir()
                files={str(path/'deploy/naver-engine-backup.override.yml')}
                files.update(str(path/(prefix+name+suffix)) for name in ('engine','relay') for prefix,suffix in
                             (('compose.naver-','.yml'),('preview-','.override.yml')))
                for filename in files:
                    Path(filename).write_bytes(b'fixture-compose')
                files.update(str(secret/name) for name in owner_map)
                meta={'ok':True,'stage':'prepared','source_commit':source,'package':dict(package,source_commit=source),
                      'images':{name:image(name,source) for name in ('engine','relay')},
                      'files':{name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in files}}
                meta['package'].pop('operation')
                if failure=='manifest' and source==commit:
                    meta['files']={}
                (root/'receipts'/('preview-'+source+'.json')).write_text(json.dumps(meta))
                if source==M.OLD_COMMIT:
                    (root/'receipts'/('preview-start-'+source+'.json')).write_text(json.dumps({'ok':True,'stage':'internal_ready','source_commit':source}))
                    old_files=life.unit_files(path,33,release)
                    for filename,body in old_files.items():
                        filename.write_bytes(body)
            if failure=='unit':
                next(p for p in old_files if p!=life.TMPFILES).write_bytes(b'unapproved')
            request_file=root/'bootstrap-request.json'
            if failure=='replay':
                request_file.write_bytes(b'prior-request')
            now=datetime.now(timezone.utc)
            request_data={'request_id':'9'*32,'hold_id':42,'hold_sha256':'8'*64,'expected_rows':1437,
                          'approved_by':0,'expires_at':(now+timedelta(minutes=20)).isoformat(),'max_seconds':300}
            host=Mock();host.baseline.return_value=baseline
            with patch.object(M,'REQUEST',request_file),patch.object(M.os,'geteuid',return_value=0), \
                    patch.object(M,'ENVELOPE_KEY',root/'envelope/private.pem'), \
                    patch.object(M,'read_file',side_effect=lambda path,**kwargs:Path(path).read_bytes()), \
                    patch.object(M.pwd,'getpwnam',return_value=types.SimpleNamespace(pw_gid=33)):
                try:
                    result=M.prepare(package,host,release,life) if mode=='prepare' else M.apply({'release':package,'request':request_data},host,release,life)
                except Exception as error:
                    result=error
            units_restored=all(p.read_bytes()==body for p,body in old_files.items())
            return result,commands,writes,units_restored,state

    def test_apply_targets_only_two_isolated_services_and_preserves_bootstrap_running_health(self):
        result,commands,writes,_,state=self.scenario()
        self.assertIs(result['ok'],True)
        self.assertIs(result['bootstrap_completion_not_asserted'],True)
        self.assertEqual(state,{'engine':'b'*40,'relay':'b'*40})
        stops=[args[-1] for args in commands if args[:2]==['/usr/bin/systemctl','stop']]
        self.assertEqual(stops,['metainc-naver-relay.service','metainc-naver-engine.service'])
        self.assertFalse(any(word in ' '.join(args) for args in commands for word in ('prune','nginx','disable','down','--volumes')))
        provision=next(options for path,options in writes if path.name=='bootstrap-request.json')
        self.assertEqual(provision,{'uid':0,'gid':10001,'mode':0o440})

    def test_preflight_refusals_do_not_stop_or_write(self):
        for reason in ('image','unit','manifest','replay'):
            with self.subTest(reason=reason):
                result,commands,writes,_,_=self.scenario(reason)
                self.assertIsInstance(result,Exception)
                self.assertEqual(writes,[])
                self.assertFalse(any(args[:2]==['/usr/bin/systemctl','stop'] for args in commands))

    def test_partial_recreate_start_and_probe_failure_restore_old_units_and_images(self):
        for reason in ('stop','recreate','start','probe'):
            with self.subTest(reason=reason):
                result,_,_,restored,state=self.scenario(reason)
                self.assertEqual(str(result),'UPGRADE_FAILED_ROLLED_BACK_DB_PRESERVED')
                self.assertTrue(restored)
                self.assertEqual(state,{'engine':M.OLD_COMMIT,'relay':M.OLD_COMMIT})

    def test_failed_old_recreation_must_not_start_that_service_on_new_container(self):
        result,commands,_,_,_=self.scenario('rollback_recreate')
        self.assertEqual(str(result),'UPGRADE_ROLLBACK_FAILED')
        old_attempt=next(i for i,args in enumerate(commands) if '--force-recreate' in args and M.OLD_COMMIT in ' '.join(args))
        self.assertFalse(any(args==['/usr/bin/systemctl','start','metainc-naver-engine.service'] for args in commands[old_attempt+1:]))

    def test_prepare_keeps_secrets_units_and_running_services_unchanged(self):
        result,commands,writes,restored,state=self.scenario(mode='prepare')
        self.assertIs(result['ok'],True)
        self.assertIs(result['services_started'],False)
        self.assertTrue(restored)
        self.assertEqual(state,{'engine':M.OLD_COMMIT,'relay':M.OLD_COMMIT})
        self.assertFalse(any(args[:2] in (['/usr/bin/systemctl','stop'],['/usr/bin/systemctl','start']) for args in commands))
        self.assertFalse(any(path.parent.name in ('units','secrets') for path,_ in writes))

    def test_prepare_rejects_changed_runtime_secret_before_any_new_file_or_build(self):
        result,commands,writes,_,_=self.scenario('secret',mode='prepare')
        self.assertEqual(str(result),'RUNTIME_SECRET_CHANGED')
        self.assertEqual(writes,[])
        self.assertFalse(any(args[:2]==['docker','build'] for args in commands))


if __name__ == '__main__':
    unittest.main()
