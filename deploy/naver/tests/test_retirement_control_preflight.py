"""Synthetic configs/files/Docker only; no network, real key, or nginx calls."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

PATH=Path(__file__).resolve().parents[1]/'retirement_control_preflight.py'
SPEC=importlib.util.spec_from_file_location('retirement_control_preflight',PATH)
s=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(s)
CANARY='PRIVATE_CUSTOMER_CONFIG_VALUE'
AD=('server { listen 443 ssl; server_name ad.metainc.co.kr dashboard.metainc.co.kr; '
    'ssl_certificate_key /PRIVATE_TLS_PATH; location / { proxy_pass http://127.0.0.1:5051; } '+
    ' '.join('location '+modifier+' '+path+' { proxy_pass http://unix:'+s.RELAY+':; }'
             for modifier,path in (('=','/naver'),('^~','/naver/'),('=','/api/naver-auto'),('^~','/api/naver-auto/')))+
    ' # '+CANARY+'\n}')
LOGIC=('server { listen 443 ssl; server_name logic.metainc.co.kr; '
       'location /studio/ { proxy_pass http://127.0.0.1:5060/; } location = /studio { return 301 /studio/; } '
       'location /autobid/ { proxy_pass http://127.0.0.1:5070; } location = /autobid { proxy_pass http://127.0.0.1:5070; } '
       'location /private-customer { proxy_pass http://127.0.0.1:5050; } }')
STUDIO='server { listen 80; server_name studio.metainc.co.kr; location / { proxy_pass http://127.0.0.1:5060; } }'


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.files=s.Files(str(self.base),os.getuid())
        for directory in (s.ENABLED,s.AVAILABLE):self.local(directory).mkdir(parents=True,mode=0o700)
        self.write('ad.metainc.co.kr',AD);self.write('logic-analysis',LOGIC);self.write('content-host.conf',STUDIO)
        self.request={'ad':{'id':'a'*64,'pid':101},'content':{'id':'c'*64,'pid':201}}
        self.docker=mock.Mock();self.docker.inspect.side_effect=self.inspect
    def local(self,path):return self.base/path.lstrip('/')
    def write(self,name,body):
        path=self.local(s.AVAILABLE+'/'+name);path.write_bytes(body.encode() if isinstance(body,str) else body);path.chmod(0o600)
        link=self.local(s.ENABLED+'/'+name)
        if not link.exists():link.symlink_to('../sites-available/'+name)
    def inspect(self,alias,selection):
        return {'id':selection['id'],'image':s.IMAGES[alias],'name':s.NAMES[alias],'pid':selection['pid'],
                'running':True,'paused':False,'restarting':False,'restart':{'Name':'unless-stopped','MaximumRetryCount':0}}
    def collect(self,private=None):return s.collect(self.request,self.files,self.docker,private)
    def safe(self,result):
        raw=json.dumps(result)
        for word in (CANARY,'PRIVATE_TLS_PATH','private-customer','root') :self.assertNotIn(word,raw)
        self.assertTrue(result['read_only']);self.assertFalse(result['changes_applied'])
    def test_three_fixed_roles_selected_without_private_content_output(self):
        private={};report=self.collect(private);self.assertEqual(report['status'],'observed',report);self.safe(report)
        self.assertEqual(len(report['files']),3);self.assertEqual(set(private['preimages']),{'ad','logic','studio'})
        self.assertEqual([r['restart_policy'] for r in report['containers']],['unless-stopped']*2)
        self.assertIn(CANARY.encode(),private['preimages']['ad']['body'])
        self.assertEqual(len(report['files'][0]['protected_locations']),4)
    def test_exact_byte_spans_and_digest_preserve_every_other_byte(self):
        info=s.selectors(LOGIC.encode(),'logic');self.assertEqual(len(info['locations']),4)
        source=LOGIC.encode();outside=b'';cursor=0
        for row in info['locations']:
            self.assertTrue(source[row['start']:row['end']].startswith(b'location '))
            self.assertEqual(hashlib.sha256(source[row['start']:row['end']]).hexdigest(),row['sha256'])
            outside+=source[cursor:row['start']];cursor=row['end']
        outside+=source[cursor:]
        self.assertIn(b'/private-customer',outside)
        self.assertEqual(hashlib.sha256(outside).hexdigest(),info['protected_bytes_sha256'])
    def test_quoted_braces_comments_and_semicolons_do_not_change_spans(self):
        raw=LOGIC.replace('listen 443 ssl;','listen 443 ssl; add_header X-Test "{;#}"; # }\n')
        self.assertEqual(len(s.selectors(raw.encode(),'logic')['locations']),4)
    def test_multiple_studio_sources_are_refused_and_clear_private(self):
        self.write('second.conf',STUDIO);private={'old':CANARY};result=self.collect(private)
        self.assertEqual(result['error'],'studio_source_ambiguous');self.assertEqual(private,{});self.safe(result)
    def test_combined_logic_and_studio_file_groups_spans_without_double_mutation(self):
        self.local(s.ENABLED+'/content-host.conf').unlink()
        self.write('logic-analysis',LOGIC+'\n'+STUDIO)
        result=self.collect();self.assertEqual(result['status'],'observed',result)
        combined=next(r for r in result['files'] if r['aliases']==['logic','studio'])
        self.assertEqual(len(combined['locations']),5);self.assertEqual(len(result['files']),2)
    def test_symlink_escape_chain_and_regular_hardlink_refused(self):
        link=self.local(s.ENABLED+'/content-host.conf');link.unlink();link.symlink_to('/tmp/'+CANARY)
        self.assertEqual(self.collect()['error'],'symlink_refused')
        link.unlink();link.symlink_to('../sites-available/other.conf')
        self.local(s.AVAILABLE+'/other.conf').symlink_to('content-host.conf')
        self.assertEqual(self.collect()['error'],'file_refused')
        self.local(s.AVAILABLE+'/other.conf').unlink();os.link(self.local(s.AVAILABLE+'/content-host.conf'),self.local(s.AVAILABLE+'/other.conf'))
        self.assertEqual(self.collect()['error'],'file_refused')
    def test_directory_symlink_and_mutable_file_permissions_refused(self):
        self.local(s.AVAILABLE+'/content-host.conf').chmod(0o666)
        self.assertEqual(self.collect()['error'],'file_refused')
        self.local(s.AVAILABLE+'/content-host.conf').chmod(0o600)
        actual=self.local(s.AVAILABLE);actual.rename(self.local('/etc/nginx/saved'))
        actual.symlink_to('saved')
        self.assertEqual(self.collect()['error'],'directory_refused')
    def test_candidate_count_file_and_total_bounds(self):
        with mock.patch.object(s,'MAX_FILES',2):self.assertEqual(self.collect()['error'],'candidate_limit')
        with mock.patch.object(s,'MAX_FILE',10):self.assertEqual(self.collect()['error'],'file_refused')
        with mock.patch.object(s,'MAX_TOTAL',10):self.assertEqual(self.collect()['error'],'candidate_total_limit')
    def test_regular_enabled_file_is_supported_without_following_any_link(self):
        link=self.local(s.ENABLED+'/content-host.conf');link.unlink();link.write_text(STUDIO);link.chmod(0o600)
        self.assertEqual(self.collect()['status'],'observed')
    def test_config_and_candidate_set_change_are_refused(self):
        original=self.files.read;calls={}
        def changed(name):
            calls[name]=calls.get(name,0)+1;row=original(name)
            if calls[name]>1:row['body']+=b'changed'
            return row
        with mock.patch.object(self.files,'read',side_effect=changed):self.assertEqual(self.collect()['error'],'configuration_changed')
        original_names=self.files.names();calls=iter([original_names,original_names+('unexpected',)])
        with mock.patch.object(self.files,'names',side_effect=lambda:next(calls)):
            self.assertEqual(self.collect()['error'],'candidate_set_changed')
    def test_nginx_ambiguous_missing_and_unknown_route_fail_closed(self):
        for body,want in ((STUDIO.replace('5060','9999'),'app_location_unresolved'),
                          (STUDIO.replace('studio.metainc.co.kr','unknown.invalid'),'studio_source_ambiguous'),
                          (STUDIO+' {','nginx_syntax_unsupported')):
            self.write('content-host.conf',body);result=self.collect();self.assertEqual(result['error'],want,result);self.safe(result)
    def test_protected_relay_route_and_related_redirect_must_be_exact(self):
        self.write('ad.metainc.co.kr',AD.replace('/run/metainc/naver-relay/relay.sock','/wrong.sock'))
        self.assertEqual(self.collect()['error'],'relay_location_unresolved')
        self.write('ad.metainc.co.kr',AD);self.write('logic-analysis',LOGIC.replace('return 301 /studio/','return 301 https://unknown.invalid'))
        self.assertEqual(self.collect()['error'],'app_location_unresolved')
    def test_unchosen_config_identity_is_rechecked_for_studio_discovery_races(self):
        self.write('unrelated.conf','server { listen 81; server_name other.invalid; }')
        original=self.files.verify
        def changed(row):
            if row['enabled_path'].endswith('/unrelated.conf'):
                self.local(row['resolved_path']).write_text(STUDIO)
            return original(row)
        with mock.patch.object(self.files,'verify',side_effect=changed):
            result=self.collect();self.assertEqual(result['error'],'configuration_changed');self.safe(result)
    def test_shared_unknown_domain_and_multiple_matching_servers_are_refused(self):
        for body,want in ((AD.replace('dashboard.metainc.co.kr;','dashboard.metainc.co.kr unrelated.invalid;'),'vhost_names_unresolved'),
                          (AD+'\n'+AD,'vhost_ambiguous')):
            self.write('ad.metainc.co.kr',body)
            self.assertEqual(self.collect()['error'],want)
    def test_relay_socket_prefix_uri_and_exact_forms(self):
        for suffix in ('-evil:',':/unexpected-uri'):
            self.write('ad.metainc.co.kr',AD.replace(s.RELAY+':',s.RELAY+suffix))
            self.assertEqual(self.collect()['error'],'relay_location_unresolved')
        self.write('ad.metainc.co.kr',AD.replace(s.RELAY+':',s.RELAY))
        self.assertEqual(self.collect()['status'],'observed')
    def test_docker_metadata_output_deadline_and_stderr_are_bounded(self):
        original=s.subprocess.Popen
        for program,deadline,want in (("print('x'*16385)",2,'command_limit'),
                                      ('import time; time.sleep(20)',.1,'time_limit'),
                                      ("import sys; sys.stderr.write('"+CANARY+"'); sys.exit(2)",2,'container_inspect_failed')):
            children=[]
            def spawn(args,**kwargs):
                self.assertEqual(kwargs['stderr'],s.subprocess.DEVNULL)
                child=original([sys.executable,'-I','-B','-c',program],**kwargs);children.append(child);return child
            with mock.patch.object(s.subprocess,'Popen',side_effect=spawn),self.assertRaises(s.Refused) as error:
                s.Docker(time.monotonic()+deadline).inspect('ad',self.request['ad'])
            self.assertEqual(error.exception.code,want)
            self.assertTrue(all(child.poll() is not None and child.stdout.closed for child in children))
    def test_docker_socket_config_and_environment_cannot_follow_parent_context(self):
        original=s.subprocess.Popen;seen=[]
        def spawn(args,**kwargs):
            self.assertEqual(args[:4],['/usr/bin/docker','--host','unix:///var/run/docker.sock','--config'])
            config=args[4];self.assertEqual(stat.S_IMODE(os.stat(config).st_mode),0o700)
            self.assertEqual(os.listdir(config),[])
            self.assertEqual(kwargs['env'],{'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','HOME':config})
            self.assertNotIn(CANARY,str(args)+str(kwargs['env']));seen.append(config)
            return original([sys.executable,'-I','-B','-c','print("{}")'],**kwargs)
        with mock.patch.dict(os.environ,{'DOCKER_HOST':'tcp://'+CANARY,'DOCKER_CONTEXT':CANARY,'DOCKER_CONFIG':'/'+CANARY}),mock.patch.object(s.subprocess,'Popen',side_effect=spawn):
            self.assertEqual(s.Docker(time.monotonic()+2).inspect('ad',self.request['ad']),{})
        self.assertTrue(seen);self.assertTrue(all(not os.path.exists(config) for config in seen))
    def test_uncertain_child_teardown_fails_closed_and_closes_pipe(self):
        child=mock.Mock();child.pid=999999;child.stdout=mock.Mock();child.poll.return_value=None
        child.wait.side_effect=s.subprocess.TimeoutExpired('synthetic',5)
        with mock.patch.object(s.subprocess,'Popen',return_value=child),mock.patch.object(s.io_selectors,'DefaultSelector',side_effect=s.Refused('time_limit')),mock.patch.object(s.os,'killpg') as kill:
            with self.assertRaises(s.Refused) as error:s.Docker(time.monotonic()+2).inspect('ad',self.request['ad'])
        self.assertEqual(error.exception.code,'child_teardown_failed');kill.assert_called_once_with(999999,s.signal.SIGKILL)
        child.wait.assert_called_with(timeout=5);child.stdout.close.assert_called_once()
    def test_container_id_image_pid_restart_type_and_final_change_refused(self):
        for key,value in (('image','sha256:'+'0'*64),('pid',True),('restarting',True),('paused',1),('restart',{'Name':'unknown','MaximumRetryCount':0})):
            def changed(alias,selection):
                row=self.inspect(alias,selection);row[key]=value;return row
            self.docker.inspect.side_effect=changed
            result=self.collect();self.assertEqual(result['status'],'incomplete');self.safe(result)
        count=0
        def changed(alias,selection):
            nonlocal count
            count+=1;row=self.inspect(alias,selection)
            if count>2:row['restart']['Name']='no'
            return row
        self.docker.inspect.side_effect=changed
        self.assertEqual(self.collect()['error'],'container_changed')
    def test_no_app_env_nginx_command_or_mutation_api(self):
        text=PATH.read_text()
        for token in ('docker pause','docker stop','nginx -T','nginx -t','reload','docker update','Config.Env','os.unlink','os.rename'):
            self.assertNotIn(token,text)
        self.assertEqual(self.collect()['status'],'observed');self.assertEqual(self.docker.inspect.call_count,4)
    def test_safe_cli_error_does_not_echo_untrusted_argument(self):
        output=io.StringIO()
        with mock.patch.object(sys,'argv',['helper',CANARY]),mock.patch.object(os,'geteuid',return_value=0),contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            self.assertEqual(s.main(),2)
        self.assertNotIn(CANARY,output.getvalue())


if __name__=='__main__':unittest.main()
