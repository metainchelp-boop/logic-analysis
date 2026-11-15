"""nginx-plan / nginx-apply 종단 시험 — 가짜 nginx(-T·-t·-s reload)와 가짜 443(curl --resolve) 대역.

제품 nginx 원문은 공개 저장소에 넣지 않는다. 합성 제품 파일(같은 모양)과 시험 전용 고정 표를 쓴다.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_naver_deploy import C0, C1, FakeHost, make_tar, result_of, source_files  # noqa: E402

STEP = 'reconcile-upload-v1'
PATHS = ['/api/naver-auto/reconcile/settlement/preview', '/api/naver-auto/reconcile/settlement/confirm']
SNIPPET = '/etc/nginx/snippets/naver-relay.conf'
SITE = '/etc/nginx/sites-enabled/dashboard.metainc.co.kr'
OTHER = '/etc/nginx/sites-enabled/logic.metainc.co.kr'
ZONE = '/etc/nginx/conf.d/naver-reconcile-upload-zone.conf'
RELAY = 'http://unix:/run/metainc/naver-relay/relay.sock:'
HTTP_CONF = '# 합성 http include\nlimit_conn_zone $binary_remote_addr zone=naver_reconcile_upload:1m;\n'


def location(path):
    return ('location = %s {\n    proxy_pass http://127.0.0.1:5051;\n    proxy_set_header Host $host;\n'
            '    client_max_body_size 4m;\n    client_body_buffer_size 4m;\n    limit_conn naver_reconcile_upload 1;\n'
            '}\n' % path)


PRODUCT_LOCATIONS = ('# 합성 server include\nlocation ^~ /naver/ {\n    proxy_pass http://127.0.0.1:5051;\n}\n\n'
                     + location(PATHS[0]) + '\n' + location(PATHS[1]) + '\n'
                     'location ^~ /api/naver-auto {\n    proxy_pass http://127.0.0.1:5051;\n    client_max_body_size 64k;\n}\n')
NGINX_CONF = ('user www-data;\nevents {}\nhttp {\n    include /etc/nginx/conf.d/*.conf;\n'
              '    include /etc/nginx/sites-enabled/*;\n}\n')
SITE_BODY = ('server {\n    listen 443 ssl;\n    server_name dashboard.metainc.co.kr;\n'
             '    include /etc/nginx/snippets/naver-relay.conf;\n    location / {\n        proxy_pass http://127.0.0.1:8000;\n'
             '    }\n}\n')
OTHER_BODY = 'server {\n    listen 443 ssl;\n    server_name logic.metainc.co.kr;\n    client_max_body_size 20m;\n}\n'
SNIPPET_BODY = ('access_log off;\nlocation ^~ /naver/ {\n    proxy_pass %s;\n}\n\nlocation ^~ /api/naver-auto {\n'
                '    proxy_pass %s;\n    client_max_body_size 64k;\n}\n' % (RELAY, RELAY))


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class NginxApplyTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='naver-nginx-test-')
        self.host = FakeHost(self.base)
        for path, body in (('/etc/nginx/nginx.conf', NGINX_CONF), (SITE, SITE_BODY), (OTHER, OTHER_BODY),
                           (SNIPPET, SNIPPET_BODY)):
            self.host.file(path, body)
        os.makedirs(self.host.root + '/etc/nginx/conf.d', exist_ok=True)
        subprocess_run(self.host, 'nginx', '-s', 'reload')
        self.tar = os.path.join(self.base, 'nginx-product.tar')
        files = source_files(C1, 21, {'deploy/naver-engine-nginx-http.conf': HTTP_CONF,
                                      'deploy/naver-engine-nginx.conf': PRODUCT_LOCATIONS})
        make_tar(self.tar, files)
        blocks = location(PATHS[0]) + location(PATHS[1])
        self.steps = {STEP: {'product_commit': C1,
                             'http_conf': {'member': 'deploy/naver-engine-nginx-http.conf', 'sha256': sha(HTTP_CONF),
                                           'target': ZONE},
                             'locations': {'member': 'deploy/naver-engine-nginx.conf', 'sha256': sha(PRODUCT_LOCATIONS),
                                           'paths': PATHS, 'blocks_sha256': sha(blocks)},
                             'zone': 'naver_reconcile_upload', 'host': 'dashboard.metainc.co.kr',
                             'big_bytes': 4 * 1024 * 1024, 'small_bytes': 64 * 1024}}
        self.steps_path = os.path.join(self.base, 'nginx-steps.json')
        self.write_steps()
        self.host.clear_calls()

    def tearDown(self):
        shutil.rmtree(self.base)

    def write_steps(self):
        with open(self.steps_path, 'w') as handle:
            json.dump(self.steps, handle)

    def run_mode(self, *args, **env):
        return self.host.run(*args, NAVER_DEPLOY_TEST_NGINX_STEPS=self.steps_path, **env)

    def plan(self):
        done = self.run_mode('nginx-plan', C1, self.tar, STEP)
        self.assertEqual(done.returncode, 0, done.stdout.decode()[-3000:])
        return result_of(done)['plan_sha256']

    def files(self):
        return {p: self.host.read(p) if os.path.exists(self.host.root + p) else None
                for p in ('/etc/nginx/nginx.conf', SITE, OTHER, SNIPPET, ZONE)}

    def test_plan_then_apply_changes_only_pinned_files_and_verifies(self):
        before = self.files()
        plan = self.plan()
        self.assertEqual(self.files(), before, 'plan is read-only')
        done = self.run_mode('nginx-apply', C1, self.tar, STEP, plan)
        self.assertEqual(done.returncode, 0, done.stdout.decode()[-3000:])
        result = result_of(done)
        self.assertEqual(result['status'], 'NGINX_APPLIED')
        self.assertIn('under=401', result['nginx_checks'])
        self.assertIn('above=413', result['nginx_checks'])
        self.assertIn('other=413', result['nginx_checks'])
        after = self.files()
        for path in ('/etc/nginx/nginx.conf', SITE, OTHER):
            self.assertEqual(after[path], before[path], path)
        self.assertEqual(after[ZONE], HTTP_CONF)
        snippet = after[SNIPPET]
        for path in PATHS:
            self.assertIn('location = %s {\n    proxy_pass %s;' % (path, RELAY), snippet)
        self.assertNotIn('127.0.0.1:5051', snippet)
        self.assertTrue(snippet.endswith(SNIPPET_BODY[SNIPPET_BODY.index('location ^~ /api/naver-auto'):]))
        calls = [c for c in self.host.calls() if c[0] == 'nginx']
        self.assertIn(['nginx', '-t'], calls)
        self.assertIn(['nginx', '-s', 'reload'], calls)
        again = self.plan()
        done = self.run_mode('nginx-apply', C1, self.tar, STEP, again)
        self.assertEqual(result_of(done)['status'], 'NGINX_ALREADY_APPLIED')

    def test_plan_mismatch_refuses_without_change(self):
        self.plan()
        before = self.files()
        done = self.run_mode('nginx-apply', C1, self.tar, STEP, '0' * 64)
        self.assertEqual(done.returncode, 10)
        self.assertEqual(self.files(), before)

    def test_config_test_failure_rolls_back(self):
        plan = self.plan()
        before = self.files()
        self.host.set(nginx_t_fail=True)
        done = self.run_mode('nginx-apply', C1, self.tar, STEP, plan)
        self.assertEqual(done.returncode, 4, done.stdout.decode()[-3000:])   # 복원 뒤 -t 도 실패 → 사람 확인
        self.host.set(nginx_t_fail=False)
        self.assertEqual(self.files(), before, 'files restored even when reload cannot run')

    def test_verification_failure_rolls_back_to_previous_config(self):
        plan = self.plan()
        before = self.files()
        self.host.set(nginx_upload_status={PATHS[0]: 502})
        done = self.run_mode('nginx-apply', C1, self.tar, STEP, plan)
        self.assertEqual(done.returncode, 2, done.stdout.decode()[-3000:])
        self.assertEqual(result_of(done)['status'], 'NGINX_ROLLED_BACK')
        self.assertEqual(self.files(), before)

    def test_reload_failure_rolls_back(self):
        plan = self.plan()
        before = self.files()
        self.host.set(nginx_reload_fail=True)
        done = self.run_mode('nginx-apply', C1, self.tar, STEP, plan)
        self.assertEqual(done.returncode, 4)
        self.assertEqual(self.files(), before)

    def test_partial_publish_restores_both_files(self):   # PR368 S1
        plan = self.plan()
        before = self.files()
        tree = self.host.root + SNIPPET + '.naver-deploy.tmp'
        os.makedirs(tree)                                    # zone 은 게시되고 snippet 쓰기만 실패하게
        done = self.run_mode('nginx-apply', C1, self.tar, STEP, plan)
        self.assertEqual(done.returncode, 2, done.stdout.decode()[-3000:])
        self.assertEqual(result_of(done)['status'], 'NGINX_ROLLED_BACK')
        self.assertEqual(self.files(), before)
        self.assertFalse(os.path.exists(self.host.root + ZONE))

    def test_unknown_layout_and_pins_refused(self):
        self.host.file(SNIPPET, SNIPPET_BODY.replace('location ^~ /api/naver-auto', 'location /api/naver-auto'))
        done = self.run_mode('nginx-plan', C1, self.tar, STEP)
        self.assertEqual(done.returncode, 10)
        self.assertIn('NGINX_LAYOUT', done.stdout.decode())
        self.host.file(SNIPPET, SNIPPET_BODY.replace(RELAY, 'http://127.0.0.1:9999'))
        done = self.run_mode('nginx-plan', C1, self.tar, STEP)
        self.assertIn('proxy_pass', done.stdout.decode())
        self.host.file(SNIPPET, SNIPPET_BODY)
        done = self.run_mode('nginx-plan', C0, self.tar, STEP)
        self.assertIn('NGINX_COMMIT_PIN', done.stdout.decode())
        self.steps[STEP]['locations']['blocks_sha256'] = '0' * 64
        self.write_steps()
        done = self.run_mode('nginx-plan', C1, self.tar, STEP)
        self.assertIn('NGINX_PRODUCT', done.stdout.decode())

    def test_other_app_change_during_apply_is_detected(self):
        plan = self.plan()
        before = self.files()
        # 계획 뒤 다른 앱 파일이 바뀌면 계획 해시가 달라져 쓰기 전에 거절된다.
        self.host.file(OTHER, OTHER_BODY + '# changed\n')
        done = self.run_mode('nginx-apply', C1, self.tar, STEP, plan)
        self.assertEqual(done.returncode, 10)
        self.assertEqual(self.files()[SNIPPET], before[SNIPPET])


@unittest.skipUnless(os.environ.get('NAVER_REAL_NGINX_IMAGE') and shutil.which('docker'),
                     '실제 nginx 이미지(고정 digest)와 docker 가 있을 때만(합성 검증 CI 가 켠다)')
class RealNginxDumpTest(unittest.TestCase):
    """실제 nginx 바이너리의 -T 출력 형식(구획 머리 + 원문 + LF 하나)을 배포 스크립트 parser 가 바이트 그대로 되살린다."""

    def test_parser_round_trips_real_nginx_dump(self):
        import subprocess
        base = tempfile.mkdtemp(prefix='naver-real-nginx-')
        try:
            files = {'nginx.conf': ('pid /tmp/nginx.pid;\nerror_log stderr;\nevents {}\nhttp {\n    access_log off;\n'
                                    '    client_body_temp_path /tmp/client_temp;\n    proxy_temp_path /tmp/proxy_temp;\n'
                                    '    fastcgi_temp_path /tmp/fastcgi_temp;\n    uwsgi_temp_path /tmp/uwsgi_temp;\n'
                                    '    scgi_temp_path /tmp/scgi_temp;\n    include /etc/nginx/conf.d/*.conf;\n'
                                    '    include /etc/nginx/snippets/site.conf;\n}\n'),
                     'conf.d/zone.conf': HTTP_CONF,
                     'snippets/site.conf': 'server {\n    listen 8080;\n    server_name dashboard.metainc.co.kr;\n'
                                           '    location = /x { return 200 "ok"; }\n}',   # 끝 LF 없는 파일도
                     'mime.types': 'types {}\n'}
            for name, body in files.items():
                path = os.path.join(base, name)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as handle:
                    handle.write(body)
            done = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '-v', base + ':/etc/nginx:ro',
                                   '--entrypoint', 'nginx', os.environ['NAVER_REAL_NGINX_IMAGE'], '-T'],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=300)
            self.assertEqual(done.returncode, 0, done.stderr.decode()[-2000:])
            with open(os.path.join(os.path.dirname(HERE), 'naver-deploy.sh')) as handle:
                text = handle.read()
            code = text[text.index("PY_HELPER=$(cat <<'PYEOF'\n") + len("PY_HELPER=$(cat <<'PYEOF'\n"):text.index('\nPYEOF\n)')]
            namespace = {'__name__': 'naver_deploy_helper'}
            exec(code, namespace)
            sections = namespace['parse_nginx_dump'](done.stdout.decode())
            for name, body in files.items():
                self.assertEqual(sections['/etc/nginx/' + name], body, name)
        finally:
            shutil.rmtree(base, ignore_errors=True)


def subprocess_run(host, *args):
    import subprocess
    subprocess.run([os.path.join(host.bin, args[0])] + list(args[1:]), check=True)


if __name__ == '__main__':
    unittest.main()
