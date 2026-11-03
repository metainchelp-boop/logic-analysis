import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('backup_status', Path(__file__).parents[1] / 'backup_status.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
CANARY = 'PRIVATE_SYNTHETIC_CANARY'
NOW = '2026-11-03T02:00:00.123456+00:00'
GOOD = {'backup': {'code': 'OFFSITE_OK', 'last_attempt_at': NOW, 'last_offsite_at': NOW}, 'last_tick': NOW}


def http_response(body, status=200):
    return ('HTTP/1.0 %d OK\r\nContent-Length: %d\r\n\r\n' % (status, len(body))).encode() + body


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nbstat-', dir=Path.home())
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'backup'
        self.root.mkdir(mode=0o700)
        for name in ('local', 'outgoing'):
            (self.root/name).mkdir(mode=0o700)
        self.sock = self.base/'engine.sock'
        self.patches = patch.multiple(B, BACKUP_ROOT=str(self.root), SOCKET_PATH=str(self.sock), ENGINE_UID=os.getuid())
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.commands = []
        self.calls = 0

    def file(self, folder='local', day='20261102T160000Z', extension='zip', data=b'synthetic'):
        p = self.root/folder/('naver-'+day+'-'+'a'*32+'.'+extension)
        p.write_bytes(data);p.chmod(0o600)
        return p

    def server(self, response, delay=0):
        requests=[]
        listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        listener.bind(str(self.sock));os.chmod(self.sock,0o660);listener.listen(1);listener.settimeout(2)
        def work():
            try:
                connection,_=listener.accept()
                with connection:
                    requests.append(connection.recv(4096));time.sleep(delay)
                    try:connection.sendall(response)
                    except OSError:pass
            finally:listener.close()
        thread=threading.Thread(target=work);thread.start()
        self.addCleanup(thread.join,3)
        return requests

    def runner(self, command):
        self.commands.append(command)
        self.assertEqual(command[:2],B.DOCKER)
        ids=['%064x'%n for n in range(1,6)]
        images=['sha256:%064x'%n for n in range(11,16)]
        args=command[2:]
        if args==('ps','-aq','--no-trunc'):data='\n'.join(ids)
        elif args==('ps','-aq','--no-trunc','--filter','label=com.docker.compose.project=naver-engine','--filter','label=com.docker.compose.service=naver-engine'):data=ids[0]
        elif args==('image','ls','-aq','--no-trunc'):data='\n'.join(images)
        elif args[:4]==('inspect','--type=container','--format',B.SNAP_FORMAT):
            self.calls+=1
            data='\n'.join(B.canonical(dict(id=k,image=i,running=True,pid=n+1,restarts=0,started='2026-11-03T00:00:00.123456789Z')) for n,(k,i)in enumerate(zip(ids,images)))
        else:
            self.assertEqual(args[:4],('inspect','--type=container','--format',B.MOUNT_FORMAT))
            mounts=[dict(Type='bind',Source=B.BACKUP_ROOT,Destination='/var/backups/naver-engine',RW=True),dict(Type='bind',Source=str(self.sock.parent),Destination='/run/naver-engine',RW=True)]
            self.assertEqual(args[4:],(ids[0],))
            data=B.canonical(dict(id=ids[0],user='10001:10001',project='naver-engine',service='naver-engine',mounts=mounts))
        return SimpleNamespace(returncode=0,stdout=data.encode(),stderr=CANARY.encode())


class ProjectionTest(unittest.TestCase):
    def test_only_closed_backup_fields_escape(self):
        raw=dict(GOOD, secrets=CANARY)
        actual=B.project_health(json.dumps(raw).encode(),200)
        self.assertEqual(actual['backup'],GOOD['backup'])
        self.assertNotIn(CANARY,B.canonical(actual))
        self.assertEqual(B.project_health(b'{}',200)['reason'],'MISSING')
        self.assertIsNone(B.project_health(b'{}',200)['backup'])
        self.assertEqual(B.project_health(json.dumps(GOOD).encode(),503)['http_status'],503)

    def test_untrusted_raw_types_extra_unknown_and_bad_dates_refused(self):
        bads=[b'[]',b'{}'+b' '*B.MAX_BODY,b'{"backup":{},"backup":{}}',b'not-json']
        for field,value in [('code',CANARY),('code',True),('last_attempt_at',CANARY),('last_offsite_at','2026-99-99T02:00:00Z')]:
            x=copy.deepcopy(GOOD);x['backup'][field]=value;bads.append(json.dumps(x).encode())
        x=copy.deepcopy(GOOD);x['backup']['extra']=CANARY;bads.append(json.dumps(x).encode())
        for raw in bads:
            with self.subTest(raw=raw[:20]),self.assertRaises(B.Refused):B.project_health(raw,200)
        for status in (0,302,404,True):
            with self.assertRaises(B.Refused):B.project_health(json.dumps(GOOD).encode(),status)

    def test_unknown_result_cannot_claim_ok_or_known_counts(self):
        for key in ('health','local','outgoing'):
            value=B.receipt();value[key]['reason']='OK'
            with self.assertRaises(B.Refused):B.validate_report(value)
        value=B.receipt();value['reason']='OK'
        with self.assertRaises(B.Refused):B.validate_report(value)

    def test_http_envelope_total_cap_header_duplicates_and_truncation(self):
        self.assertEqual(B.http_payload(http_response(b'{}')), (b'{}', 200))
        invalid = [http_response(b'{}')[:-1], b'HTTP/1.0 302 Found\r\nContent-Length: 2\r\n\r\n{}',
                   b'HTTP/1.0 200 OK\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}',
                   b'HTTP/1.0 200 OK\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n{}',
                   b'HTTP/1.0 200 OK\r\nX-Ignored: ' + b'a'*B.MAX_BODY + b'\r\nContent-Length: 2\r\n\r\n{}']
        for raw in invalid:
            with self.assertRaises(B.Refused): B.http_payload(raw)

    def test_receipt_refuses_extra_fields_unknown_states_and_successful_missing_data(self):
        for change in ({'extra':CANARY},{'reason':CANARY},{'database_opened':True},{'file_contents_read':True},{'status':'observed'},{'images':True}):
            v=B.receipt();v.update(change)
            with self.assertRaises((B.Refused,TypeError,ValueError)):B.validate_report(v)
        v=B.receipt();v['health']['backup']={'code':CANARY}
        with self.assertRaises(B.Refused):B.validate_report(v)
        v=B.receipt();v['local']['file_count']=0
        with self.assertRaises(B.Refused):B.validate_report(v)


class HealthTest(Fixture):
    def test_real_unix_get_once_has_no_external_network_or_raw_output(self):
        requests=self.server(http_response(json.dumps(dict(GOOD,secret=CANARY)).encode()))
        actual=B.read_health()
        self.assertEqual(actual['status'],'observed');self.assertEqual(len(requests),1)
        self.assertTrue(requests[0].startswith(b'GET /_engine/health HTTP/1.0\r\n'))
        self.assertNotIn(CANARY,B.canonical(actual))

    def test_real_timeout_is_unknown_not_never_or_empty_success(self):
        self.server(http_response(b'{}'),delay=.1)
        with patch.object(B,'HEALTH_SECONDS',.02):actual=B.read_health()
        self.assertEqual(actual['reason'],'TIME_LIMIT');self.assertIsNone(actual['backup'])
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_oversize_body_rejected_with_bounded_result(self):
        self.server(http_response(b' '* (B.MAX_BODY+1)))
        actual=B.read_health();self.assertEqual(actual['reason'],'INVALID')
        self.assertLess(len(B.canonical(actual)),256)

    def test_symlink_socket_refused_before_connect(self):
        self.sock.symlink_to(self.base/'missing')
        with patch.object(B.socket,'socket')as create:
            actual=B.read_health();create.assert_not_called()
        self.assertNotEqual(actual['status'],'observed')


class MetadataTest(Fixture):
    def test_exact_metadata_and_kst_days_without_any_file_content_read(self):
        a=self.file(data=CANARY.encode());b=self.file(day='20261103T160000Z',data=b'abc')
        before={p.name:B.identity(p.stat()) for p in (a,b)}
        original_open=os.open
        def only_directories(path,flags,*args,**kwargs):
            self.assertTrue(flags&os.O_DIRECTORY,'metadata opened regular file')
            return original_open(path,flags,*args,**kwargs)
        with patch.object(B.os,'open',side_effect=only_directories),patch('builtins.open',side_effect=AssertionError('content read')):
            actual=B.summarize_folder('local','zip')
        self.assertEqual((actual['file_count'],actual['logical_bytes']),(2,len(CANARY)+3))
        self.assertEqual(actual['allocated_bytes'],sum(p.stat().st_blocks*512 for p in (a,b)))
        self.assertEqual((actual['oldest_filename_kst_day'],actual['newest_filename_kst_day']),('2026-11-03','2026-11-04'))
        self.assertEqual(before,{p.name:B.identity(p.stat()) for p in (a,b)})
        self.assertNotIn(CANARY,B.canonical(actual));self.assertNotIn('naver-',B.canonical(actual))

    def test_empty_missing_and_incomplete_are_distinct(self):
        empty=B.summarize_folder('local','zip');self.assertEqual(empty['status'],'observed');self.assertEqual(empty['file_count'],0)
        (self.root/'local').rmdir()
        missing=B.summarize_folder('local','zip');self.assertEqual(missing['reason'],'MISSING');self.assertIsNone(missing['file_count'])
        (self.root/'local').mkdir(mode=0o700);(self.root/'local'/'.building-active').mkdir()
        active=B.summarize_folder('local','zip');self.assertEqual(active['reason'],'UNEXPECTED_ENTRY');self.assertIsNone(active['logical_bytes'])

    def test_wrong_extension_link_mode_fifo_and_unknown_name_are_incomplete(self):
        cases=('extension','symlink','hardlink','mode','fifo','name')
        for kind in cases:
            with self.subTest(kind=kind):
                for p in (self.root/'local').iterdir():p.unlink()
                p=self.file()
                if kind=='extension':p.rename(p.with_suffix('.cms'))
                elif kind=='symlink':p.unlink();p.symlink_to(self.base/'other')
                elif kind=='hardlink':os.link(p,self.base/'alias')
                elif kind=='mode':p.chmod(0o644)
                elif kind=='fifo':p.unlink();os.mkfifo(p,0o600)
                elif kind=='name':p.rename(p.with_name(CANARY))
                actual=B.summarize_folder('local','zip')
                self.assertEqual(actual['status'],'incomplete');self.assertIsNone(actual['file_count'])
                self.assertNotIn(CANARY,B.canonical(actual))

    def test_symlink_parent_and_directory_permissions_refused(self):
        (self.root/'local').rmdir();(self.root/'local').symlink_to(self.root/'outgoing',target_is_directory=True)
        self.assertNotEqual(B.summarize_folder('local','zip')['status'],'observed')
        (self.root/'local').unlink();(self.root/'local').mkdir(mode=0o755)
        self.assertEqual(B.summarize_folder('local','zip')['reason'],'PATH_REFUSED')

    def test_entry_and_time_caps(self):
        self.file();self.file(day='20261103T000000Z')
        with patch.object(B,'MAX_ENTRIES',1):
            self.assertEqual(B.summarize_folder('local','zip')['reason'],'ENTRY_LIMIT')
        times=iter([0,11])
        self.assertEqual(B.summarize_folder('local','zip',monotonic=lambda:next(times))['reason'],'TIME_LIMIT')

    def test_file_change_between_passes_refuses_completed_summary(self):
        p=self.file();original=os.stat;calls=0
        def changing(path,*args,**kwargs):
            nonlocal calls
            if path==p.name:
                calls+=1
                if calls==2:p.write_bytes(b'changed')
            return original(path,*args,**kwargs)
        with patch.object(B.os,'stat',side_effect=changing):result=B.summarize_folder('local','zip')
        self.assertEqual(result['reason'],'CHANGED');self.assertIsNone(result['logical_bytes'])


class ExecuteTest(Fixture):
    def test_full_observation_preserves_state_and_fixed_docker_commands(self):
        self.file();self.file('outgoing',extension='cms')
        self.server(http_response(json.dumps(GOOD).encode()))
        result=B.execute(self.runner)
        self.assertEqual(result['status'],'observed',result);self.assertTrue(result['protected_unchanged'])
        self.assertEqual(len(self.commands),8)
        self.assertEqual(result['local']['file_count'],1);self.assertEqual(result['outgoing']['file_count'],1)
        self.assertFalse(any(result[k]for k in ('database_opened','file_contents_read','external_network_used','operating_files_changed')))
        self.assertNotIn(CANARY,B.canonical(result));B.validate_report(result)

    def test_absent_health_keeps_partial_not_success(self):
        result=B.execute(self.runner)
        self.assertEqual(result['status'],'partial');self.assertIsNone(result['health']['backup'])
        self.assertEqual(result['local']['file_count'],0)

    def test_wrong_mount_blocks_health_and_metadata_before_reads(self):
        def wrong(command):
            r=self.runner(command)
            if B.MOUNT_FORMAT in command:r.stdout=r.stdout.replace(str(self.root).encode(),b'/wrong')
            return r
        with patch.object(B,'read_health')as health,patch.object(B,'summarize_folder')as files:
            result=B.execute(wrong);health.assert_not_called();files.assert_not_called()
        self.assertEqual(result['reason'],'MOUNT_REFUSED')

    def test_protected_change_never_reports_completed_observation(self):
        def changed(command):
            r=self.runner(command)
            if self.calls==2 and B.SNAP_FORMAT in command:r.stdout=r.stdout.replace(b'"restarts":0',b'"restarts":1')
            return r
        with patch.object(B,'read_health',return_value=B.project_health(json.dumps(GOOD).encode(),200)):
            result=B.execute(changed)
        self.assertEqual(result['reason'],'PROTECTED_CHANGED');self.assertIs(result['protected_unchanged'],False)

    def test_shared_metadata_deadline_does_not_restart_for_second_folder(self):
        with patch.object(B,'read_health',return_value=B.empty_health('MISSING')),patch.object(B,'summarize_folder',side_effect=B.DeadlineExpired())as scan:
            result=B.execute(self.runner)
        self.assertEqual(scan.call_count,1);self.assertEqual(result['status'],'partial')
        self.assertEqual(result['local']['reason'],'TIME_LIMIT');self.assertEqual(result['outgoing']['reason'],'TIME_LIMIT')

    def test_real_existing_global_flock_and_no_lock_creation(self):
        lockdir=self.base/'lockdir';lockdir.mkdir(mode=0o700)
        lock=lockdir/'lock';lock.write_bytes(b'');lock.chmod(0o600)
        before=B.identity(lock.stat());fstat=os.fstat
        def owner_stat(fd):
            actual=fstat(fd)
            return SimpleNamespace(st_uid=0,st_mode=actual.st_mode,st_nlink=actual.st_nlink)
        with patch.object(B,'LOCK_PATH',str(lock)),patch.object(B.os,'fstat',side_effect=owner_stat):
            with B.deployment_lock():
                with self.assertRaisesRegex(B.Refused,'LOCKED'):
                    with B.deployment_lock():self.fail('nested lock acquired')
        self.assertEqual(before,B.identity(lock.stat()))
        lock.unlink()
        with patch.object(B,'LOCK_PATH',str(lock)),patch.object(B.os,'fstat',side_effect=owner_stat):
            with self.assertRaises(FileNotFoundError):
                with B.deployment_lock():self.fail('created missing lock')
        self.assertFalse(lock.exists())

    def test_cli_input_nonroot_and_exceptions_are_closed_without_values(self):
        for args,uid,reason in [([CANARY],0,'INPUT_REFUSED'),([],123,'NOT_ROOT')]:
            with patch.object(B.os,'geteuid',return_value=uid),patch.object(B,'deployment_lock')as lock,contextlib.redirect_stdout(io.StringIO())as out:
                self.assertEqual(B.main(args),2);lock.assert_not_called()
            actual=json.loads(out.getvalue());self.assertEqual(actual['reason'],reason);self.assertNotIn(CANARY,out.getvalue())
        with patch.object(B,'snapshot',side_effect=RuntimeError(CANARY)):
            actual=B.execute(self.runner)
        self.assertEqual(actual['reason'],'INTERNAL_ERROR');self.assertNotIn(CANARY,B.canonical(actual))


if __name__=='__main__':unittest.main()
