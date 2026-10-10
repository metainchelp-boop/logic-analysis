import importlib.util
import hashlib
import io
import json
import os
import tempfile
import tarfile
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

    def test_expiry_crossing_kst_midnight_is_rejected_within_three_hour_window(self):
        for now, accepted in ((NOW.replace(hour=23, minute=39, second=59), True),
                              (NOW.replace(hour=23, minute=40), False),
                              ((NOW+timedelta(days=1)).replace(hour=0, minute=0), True)):
            for expiry_timezone in (now.tzinfo, timezone.utc):
                request = {'request_id': 'a'*32, 'hold_id': 1, 'hold_sha256': 'b'*64,
                           'expected_rows': 1437, 'approved_by': 0, 'max_seconds': 300,
                           'expires_at': (now+timedelta(minutes=20)).astimezone(expiry_timezone).isoformat()}
                with self.subTest(now=now.isoformat(), expiry_timezone=expiry_timezone):
                    if accepted:
                        self.assertEqual(M.validate_request(request, now), request)
                    else:
                        with self.assertRaisesRegex(ValueError, '^REQUEST_EXPIRY$'):
                            M.validate_request(request, now)

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
    def scenario(self, failure=None, mode='apply', fixture_setup=None):
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
            source_files={name:b'new fixture compose' for name in
                ('compose.naver-engine.yml','compose.naver-relay.yml','deploy/naver-engine-backup.override.yml')}
            tar_bytes=io.BytesIO()
            with tarfile.open(fileobj=tar_bytes,mode='w:gz') as archive:
                for name,body in source_files.items():
                    member=tarfile.TarInfo(name);member.size=len(body);member.mode=0o644
                    archive.addfile(member,io.BytesIO(body))
            source_body=tar_bytes.getvalue()
            release.validate_payload=lambda *args:(source_body,[
                {'path':str(secret/name),'uid':uid,'gid':gid,'content':'CHANGED' if failure=='secret' else 'PRIVATE_CONFIG_SENTINEL'}
                for name,(uid,gid) in owner_map.items()])
            def source_members(body):
                archive=tarfile.open(fileobj=io.BytesIO(body),mode='r:gz')
                return archive,archive.getmembers()
            release.source_members=source_members
            def extract(source,path):
                path.mkdir();(path/'deploy').mkdir()
                for file in ('compose.naver-engine.yml','compose.naver-relay.yml','deploy/naver-engine-backup.override.yml'):
                    (path/file).write_bytes(b'new fixture compose')
            release.extract_source=extract
            old_files=None
            for source in ((M.OLD_COMMIT,) if mode in ('prepare','retry') else (M.OLD_COMMIT,commit)):
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
            if mode=='retry':
                path=root/'releases'/('naver-'+commit)
                extract(source_body,path)
                for name in ('engine','relay'):
                    body='services:\n  naver-'+name+':\n    image: metainc/naver-'+name+':'+commit+'\n    environment:\n'
                    body+=('      NAVER_ENGINE_BOOTSTRAP_REQUEST: /var/lib/naver-engine/bootstrap-request.json\n'
                           if name=='engine' else '      NAVER_AUTO_WEB: "on"\n')
                    (path/('preview-'+name+'.override.yml')).write_text(body)
                if failure=='source_content': (path/'compose.naver-engine.yml').write_bytes(b'changed')
                if failure=='source_extra': (path/'extra').write_bytes(b'not sealed')
                if failure=='source_missing': (path/'compose.naver-engine.yml').unlink()
                if failure=='override_changed': (path/'preview-engine.override.yml').write_bytes(b'changed')
            now=NOW
            request_data={'request_id':'9'*32,'hold_id':42,'hold_sha256':'8'*64,'expected_rows':1437,
                          'approved_by':0,'expires_at':(now+timedelta(minutes=20)).isoformat(),'max_seconds':300}
            host=Mock();host.baseline.return_value=baseline
            if fixture_setup is not None:
                fixture_setup(root, release)
            with patch.object(M,'REQUEST',request_file),patch.object(M.os,'geteuid',return_value=0), \
                    patch.object(M,'ENVELOPE_KEY',root/'envelope/private.pem'), \
                    patch.object(M,'read_file',side_effect=lambda path,**kwargs:Path(path).read_bytes()), \
                    patch.object(M.pwd,'getpwnam',return_value=types.SimpleNamespace(pw_gid=33)), \
                    patch.object(M,'datetime',wraps=datetime) as clock:
                clock.now.return_value=now.astimezone(timezone.utc)
                try:
                    result=M.prepare(package,host,release,life) if mode in ('prepare','retry') else M.apply({'release':package,'request':request_data},host,release,life)
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

    def test_prepare_check_config_cannot_emit_events_into_live_compose_project(self):
        result,commands,_,_,_=self.scenario(mode='prepare')
        self.assertIs(result['ok'],True)
        check=next(args for args in commands if 'check-config' in args)
        project=check[check.index('--project-name')+1]
        self.assertRegex(project, r'^naver-check-b{40}-[0-9a-f]{32}$')
        self.assertIn('--no-deps',check)
        self.assertIn('--rm',check)
        self.assertEqual(check[-5:],['naver-engine','python','-m','naver_runtime','check-config'])

    def test_interrupted_prepare_reuses_only_exact_sealed_source_without_rewriting_it(self):
        result,commands,writes,restored,state=self.scenario(mode='retry')
        self.assertIsInstance(result,dict,str(result))
        self.assertIs(result['ok'],True)
        self.assertTrue(restored)
        self.assertEqual(state,{'engine':M.OLD_COMMIT,'relay':M.OLD_COMMIT})
        self.assertEqual([path.name for path,_ in writes],['preview-'+'b'*40+'.json'])
        self.assertFalse(any(args[:2] in (['/usr/bin/systemctl','stop'],['/usr/bin/systemctl','start']) for args in commands))

    def test_interrupted_prepare_refuses_missing_extra_or_changed_files_before_build_or_write(self):
        for reason in ('source_content','source_extra','source_missing','override_changed'):
            with self.subTest(reason=reason):
                result,commands,writes,_,_=self.scenario(reason,mode='retry')
                self.assertIsInstance(result,ValueError)
                self.assertTrue(str(result).startswith('SOURCE_'))
                self.assertEqual(writes,[])
                self.assertFalse(any(args[:2]==['docker','build'] or 'check-config' in args for args in commands))

    def test_prepare_rejects_changed_runtime_secret_before_any_new_file_or_build(self):
        result,commands,writes,_,_=self.scenario('secret',mode='prepare')
        self.assertEqual(str(result),'RUNTIME_SECRET_CHANGED')
        self.assertEqual(writes,[])
        self.assertFalse(any(args[:2]==['docker','build'] for args in commands))


class InterruptedTreeTest(unittest.TestCase):
    def test_real_files_require_exact_permissions_no_links_and_accept_empty_sealed_init(self):
        spec=importlib.util.spec_from_file_location('release_tree_fixture',Path(__file__).parents[1]/'tools/naver_preview_release.py')
        release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
        source=io.BytesIO()
        with tarfile.open(fileobj=source,mode='w:gz') as archive:
            for name,body in (('naver_runtime/__init__.py',b''),('naver_runtime/check.py',b'pass\n')):
                member=tarfile.TarInfo(name);member.size=len(body);member.mode=0o644
                archive.addfile(member,io.BytesIO(body))
        actual_read=M.read_file
        actual_dir=release.trusted_dir
        for change in (None,'mode','hardlink','symlink','directory_symlink','directory_writable','extra_dir'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                parent=Path(folder).resolve();destination=parent/'source'
                release.extract_source(source.getvalue(),destination)
                overrides={'engine':'exact-engine','relay':'exact-relay'}
                for name,body in overrides.items():
                    path=destination/('preview-'+name+'.override.yml')
                    path.write_text(body);path.chmod(0o600)
                target=destination/'naver_runtime/check.py'
                if change=='mode': target.chmod(0o600)
                if change=='hardlink': os.link(target,parent/'hardlink')
                if change=='symlink': target.unlink();target.symlink_to(destination/'naver_runtime/__init__.py')
                if change=='directory_symlink':
                    (destination/'naver_runtime').rename(parent/'moved')
                    (destination/'naver_runtime').symlink_to(parent/'moved',target_is_directory=True)
                if change=='directory_writable': (destination/'naver_runtime').chmod(0o777)
                if change=='extra_dir': (destination/'extra').mkdir()
                # Only the test owner's uid/gid differ; actual lstat/open/mode/link checks run.
                with patch.object(M,'read_file',side_effect=lambda path,**kw:actual_read(path,uid=os.getuid(),gid=os.getgid(),**kw)), \
                     patch.object(release,'trusted_dir',side_effect=lambda path,**kw:actual_dir(path,uid=os.getuid(),gid=os.getgid(),**kw)):
                    if change is None:
                        M.verify_interrupted_source(source.getvalue(),destination,overrides,release)
                    else:
                        with self.assertRaises(ValueError):
                            M.verify_interrupted_source(source.getvalue(),destination,overrides,release)

if __name__ == '__main__':
    unittest.main()
