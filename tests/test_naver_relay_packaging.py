"""관제 전용 중계 패키징 계약. 비밀값·운영 Docker daemon을 사용하지 않는다."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NaverRelayPackagingTest(unittest.TestCase):
    def test_image_copies_only_standalone_entry_relay_router_and_page(self):
        source = (ROOT / 'Dockerfile.naver-relay').read_text()
        self.assertEqual(re.findall(r'^COPY (.+)$', source, re.M), [
            'backend/requirements.txt /tmp/source-requirements.txt',
            'backend/app/__init__.py ./app/__init__.py',
            'backend/app/naver_entry.py ./app/naver_entry.py',
            'backend/app/naver_relay.py ./app/naver_relay.py',
            'backend/app/routers/__init__.py ./app/routers/__init__.py',
            'backend/app/routers/naver.py ./app/routers/naver.py',
            'backend/naver_page/ ./naver_page/',
        ])
        for required in ('FROM python:3.12-slim-trixie', 'USER 10001:10001',
                         'app.naver_entry:app', '--no-access-log', '--no-proxy-headers', '--no-server-header'):
            self.assertIn(required, source)
        self.assertNotRegex(source, r'(?m)^EXPOSE\s|app\.main|gunicorn|sqlalchemy')

    def test_compose_has_no_network_secret_or_database_mount(self):
        source = (ROOT / 'compose.naver-relay.yml').read_text()
        active = '\n'.join(line for line in source.splitlines() if not line.lstrip().startswith('#'))
        for required in ('name: naver-relay', 'network_mode: none', 'read_only: true',
                         'user: "10001:10001"', 'cap_drop: [ALL]', 'no-new-privileges:true',
                         'mem_limit: 256m', 'NAVER_AUTO_WEB: ${NAVER_AUTO_WEB:-off}',
                         'NAVER_AUTO_ENGINE: unix:/run/naver-engine/engine.sock'):
            self.assertIn(required, active)
        self.assertNotRegex(active, r'(?m)^\s+(?:ports|expose|env_file|networks|container_name):|/app/data|\.db|SSO_|TOKEN|KEY')
        self.assertEqual(active.count('create_host_path: false'), 2)
        self.assertRegex(active, r'target: /run/naver-engine\n\s+read_only: true')
        self.assertIn('source: ${NAVER_RELAY_SOCKET_DIR:-/run/metainc/naver-relay}', active)
        self.assertIn('target: /run/naver-relay', active)

    def test_context_is_allowlisted_and_no_existing_app_is_copied(self):
        rules = [line for line in (ROOT / 'Dockerfile.naver-relay.dockerignore').read_text().splitlines()
                 if line and not line.startswith('#')]
        self.assertEqual(rules[0], '**')
        for required in ('**/*.db*', '**/.env*', '**/*.pem', '**/*.key*'):
            self.assertIn(required, rules)
        for forbidden in ('!backend/**', '!backend/app/**', '!backend/app/main.py', '!backend/static/**'):
            self.assertNotIn(forbidden, rules)

    def test_rendered_compose_preserves_isolation(self):
        executable = shutil.which('docker-compose')
        if not executable:
            self.skipTest('Compose CLI 없음 — 원문 검사는 별도 수행')
        result = subprocess.run([executable, '-f', 'compose.naver-relay.yml', 'config', '--format', 'json'],
                                cwd=ROOT, env={'PATH': os.environ.get('PATH', ''), 'COMPOSE_DISABLE_ENV_FILE': '1'},
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(set(data['services']), {'naver-relay'})
        service = data['services']['naver-relay']
        self.assertEqual(service['network_mode'], 'none')
        self.assertEqual(service['user'], '10001:10001')
        self.assertTrue(service['read_only'])
        self.assertEqual(int(service['mem_limit']), 256 * 1024 * 1024)
        self.assertEqual(service['environment'], {'NAVER_AUTO_WEB': 'off',
                         'NAVER_AUTO_ENGINE': 'unix:/run/naver-engine/engine.sock', 'TZ': 'Asia/Seoul'})
        self.assertFalse(service.get('ports'))
        self.assertEqual(len(service['volumes']), 2)
        self.assertTrue(next(v for v in service['volumes'] if v['target'] == '/run/naver-engine')['read_only'])
        self.assertTrue(all(v['bind']['create_host_path'] is False for v in service['volumes']))


if __name__ == '__main__':
    unittest.main()
