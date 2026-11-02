"""Execute workflow trust/asset/cleanup boundaries with synthetic local files only."""
import base64
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

from test_content_preflight_workflow import block, steps

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/naver-images-preservation.yml'
CANARY = 'PRIVATE_SYNTHETIC_VALUE_CANARY'
ASSETS = ('retirement_images_source.py', 'retirement_image_profiles.py', 'recovery-public.asc', 'server-b-known-hosts')
PYTHON = shutil.which('python3')
PUBLIC_KEY = 'ssh-ed25519 ' + base64.b64encode(
    b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + b'x' * 32).decode('ascii')


class ImagesPreservationWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text()
        cls.parts = steps(cls.source)
        cls.guard = block(cls.parts[0], 'run')
        cls.invoke = block(next(p for p in cls.parts if 'out=$(timeout' in p), 'script')
        cls.cleanup = block(cls.parts[-1], 'script')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.incoming = self.base / 'incoming'
        self.incoming.mkdir(mode=0o700)
        self.fakebin = self.base / 'bin'
        self.fakebin.mkdir()
        self.env = dict(PATH=str(self.fakebin) + os.pathsep + os.environ.get('PATH', ''),
                        ACTOR='metainchelp-boop', TRIGGERING_ACTOR='metainchelp-boop',
                        REF='refs/heads/main', HOST_FINGERPRINT='SHA256:' + 'c' * 43,
                        NRI_RUN='1234-1', NRI_PHASE='prepare', NRI_PROFILE='autobid-web',
                        TEST_INCOMING=str(self.incoming), TEST_UID='0',
                        TEST_CHOWN_LOG=str(self.base / 'chown-log'))
        self.program('id', "import os\nprint(os.environ['TEST_UID'])\n")
        self.program('stat', """import os, stat, sys
s = os.lstat(sys.argv[-1])
fields = {'%u': os.environ['TEST_UID'], '%g': '0', '%a': format(stat.S_IMODE(s.st_mode), 'o'), '%h': str(s.st_nlink)}
print(':'.join(fields[p] for p in sys.argv[2].split(':')))
""")
        self.program('chown', """import os, pathlib, sys
if sys.argv[1] != '0:0' or len(sys.argv) != 3:
    raise SystemExit(1)
with open(os.environ['TEST_CHOWN_LOG'], 'a') as out:
    out.write(pathlib.Path(sys.argv[2]).name + '\\n')
""")
        self.program('sha256sum', "import hashlib, pathlib, sys\np = pathlib.Path(sys.argv[1])\nprint(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p))\n")
        self.program('timeout', "import os, sys\nos.execvp(sys.argv[4], sys.argv[4:])\n")
        self.set_report(self.report())
        for name in ASSETS[1:]:
            path = self.incoming / name
            path.write_text('SYNTHETIC_PUBLIC_ASSET\n')
            path.chmod(0o600)
        self.hash_assets()

    def program(self, name, code):
        path = self.fakebin / name
        path.write_text('#!' + PYTHON + '\n' + code)
        path.chmod(0o700)

    def set_helper(self, code):
        path = self.incoming / ASSETS[0]
        path.write_text(code)
        path.chmod(0o600)

    def resources(self):
        return dict(client_version=[28, 5, 1], server_version=[28, 5, 1],
                    client_variant='release', server_variant='release', driver='overlayfs',
                    storage_backend='containerd_snapshotter', docker_data='var_lib_docker',
                    docker_tmpdir='unset', tmpdir='unset', required_free_bytes=3221225472,
                    large_export_gate='not_required', filesystems=[
                        dict(alias=name, status='ok', device=1, available_bytes=4000000000)
                        for name in ('docker_data', 'docker_tmp', 'tmp')])

    def report(self):
        return dict(phase='prepare', status='prepared', session='autobid-web-image-20261102-v1',
                    error=None, ssh_public_key=PUBLIC_KEY, image_size_bytes=84303740,
                    bytes=None, sha256=None, process_rc=None, backup_verified=False, resources=self.resources())

    def set_report(self, payload, rc=0):
        self.set_helper('import sys\nprint(' + repr(json.dumps(payload)) + ')\nsys.exit(' + str(rc) + ')\n')

    def hash_assets(self):
        for name, field in zip(ASSETS, ('NRI_HELPER_SHA', 'NRI_PROFILE_SHA', 'NRI_PUBLIC_SHA', 'NRI_HOSTS_SHA')):
            self.env[field] = hashlib.sha256((self.incoming / name).read_bytes()).hexdigest()

    def run_shell(self, script, **values):
        script = script.replace('"/tmp/metainc-images-preservation-$NRI_RUN"', '"$TEST_INCOMING"')
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', script],
                              env=dict(self.env, **values), capture_output=True,
                              text=True, timeout=5)

    def assert_refused(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(CANARY, result.stdout + result.stderr)

    def test_owner_main_pin_and_each_phase_pass(self):
        for phase in ('prepare', 'send', 'cleanup'):
            result = self.run_shell(self.guard, NRI_PHASE=phase)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, '')

    def test_initial_and_rerun_actor_each_fail_closed(self):
        for field in ('ACTOR', 'TRIGGERING_ACTOR'):
            for value in ('', CANARY, 'metainchelp-boop\n' + CANARY):
                self.assert_refused(self.run_shell(self.guard, **{field: value}))

    def test_non_main_malformed_pin_and_unlisted_phase_are_refused(self):
        for field, values in {
            'REF': ('', 'refs/tags/main', 'refs/heads/main\n' + CANARY),
            'HOST_FINGERPRINT': ('', CANARY, 'SHA256:' + 'c' * 42, 'SHA256:' + 'c' * 43 + '\n' + CANARY),
            'NRI_PHASE': ('', 'delete', 'send\n' + CANARY, 'send;echo ' + CANARY),
        }.items():
            for value in values:
                self.assert_refused(self.run_shell(self.guard, **{field: value}))

    def test_only_manual_phase_choice_and_serial_non_cancelling_group(self):
        header = self.source.split('\npermissions:', 1)[0]
        self.assertEqual(re.findall(r'^  ([a-z_]+):', header, re.MULTILINE), ['workflow_dispatch'])
        self.assertEqual(re.findall(r'^      ([a-z_]+):', header, re.MULTILINE), ['phase', 'profile'])
        self.assertIn('type: choice', header)
        self.assertIn('options: [prepare, send, cleanup]', header)
        self.assertIn('contents: read', self.source)
        self.assertNotIn('contents: write', self.source)
        self.assertIn('group: naver-images-preservation\n  cancel-in-progress: false', self.source)
        self.assertNotIn('group: deploy-logic-analysis', self.source)

    def test_preservation_tests_before_transport_and_pinned_actions(self):
        checked = next(i for i, p in enumerate(self.parts) if "unittest discover -s deploy/naver/tests -p 'test_retirement_*.py' -v" in p)
        remote = [i for i, p in enumerate(self.parts) if 'uses: appleboy/' in p]
        self.assertEqual(len(remote), 4)
        self.assertTrue(all(i > checked > 0 for i in remote))
        self.assertIn('persist-credentials: false', self.source)
        for version in re.findall(r'uses: [^@\s]+@(\S+)', self.source):
            self.assertRegex(version, r'^[0-9a-f]{40}$')
        for i in remote:
            self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}', self.parts[i])
        self.assertNotIn('allenvs:', self.source)
        self.assertNotIn('debug: true', self.source)

    def test_transfer_contains_exactly_three_public_assets(self):
        part = next(p for p in self.parts if 'uses: appleboy/scp-action@' in p)
        source = re.search(r'^          source: (.+)$', part, re.MULTILINE)[1]
        self.assertEqual(source.split(','), ['images-preservation-ship/' + name for name in ASSETS])
        self.assertIn('strip_components: 1', part)
        self.assertIn('overwrite: false', part)
        ship = next(p for p in self.parts if 'mkdir -m 755 images-preservation-ship' in p)
        self.assertIn('chmod 644', ship)
        self.assertNotIn('chown', ship)
        self.assertNotIn('sudo', ship)
        self.assertLess(self.invoke.index('chown 0:0'), self.invoke.index('sha256sum "$helper"'))
        self.assertNotRegex(self.source, r'docker\s+(stop|rm|exec|build|run)|rm\s+-rf|rsync|sqlite3|/root/|\.env')
        self.assertNotIn('upload-artifact', self.source)

    def test_public_staging_is_readable_to_the_scp_container_other_uid(self):
        # drone-scp runs as UID 1000, which can differ from runner UID 1001.
        # Verify actual POSIX other-read/search bits, with no root or sudo access.
        self.program('sudo', 'raise SystemExit(1)\n')
        target = self.base / 'deploy/naver'
        (target / 'preservation').mkdir(parents=True)
        for name in ASSETS:
            source = target / name if name.endswith('.py') else target / 'preservation' / name
            source.write_text('SYNTHETIC_PUBLIC_ASSET\n')
        ship = block(next(p for p in self.parts if 'mkdir -m 755 images-preservation-ship' in p), 'run')
        env_file = self.base / 'github-env'
        result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', ship],
                                env=dict(self.env, GITHUB_ENV=str(env_file),
                                         GITHUB_RUN_ID='1234', GITHUB_RUN_ATTEMPT='1'),
                                cwd=self.base, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, '')
        values = dict(line.split('=', 1) for line in env_file.read_text().splitlines())
        expected = hashlib.sha256(b'SYNTHETIC_PUBLIC_ASSET\n').hexdigest()
        for field in ('NRI_HELPER_SHA', 'NRI_PROFILE_SHA', 'NRI_PUBLIC_SHA', 'NRI_HOSTS_SHA'):
            self.assertEqual(values[field], expected)
        self.assertEqual(values['NRI_RUN'], '1234-1')
        folder = self.base / 'images-preservation-ship'
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o755)
        self.assertTrue(folder.stat().st_mode & stat.S_IXOTH)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(ASSETS))
        for name in ASSETS:
            info = (folder / name).stat()
            self.assertEqual((info.st_uid, stat.S_IMODE(info.st_mode)), (os.getuid(), 0o644))
            self.assertTrue(info.st_mode & stat.S_IROTH)
        self.assertFalse((self.base / 'chown-log').exists())

    def test_remote_normalizes_public_assets_before_hash_and_execution(self):
        for name in ASSETS:
            (self.incoming / name).chmod(0o644)
        result = self.run_shell(self.invoke)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / 'chown-log').read_text().splitlines(), list(ASSETS))
        for name in ASSETS:
            self.assertEqual(stat.S_IMODE((self.incoming / name).stat().st_mode), 0o600)

    def test_matching_assets_execute_exact_phase_with_metadata_output(self):
        result = self.run_shell(self.invoke)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        prefix, payload = result.stdout.strip().split('=', 1)
        self.assertEqual(prefix, 'RETIREMENT_IMAGES')
        self.assertEqual(json.loads(payload)['phase'], 'prepare')

    def test_each_tampered_asset_prevents_helper_execution(self):
        self.set_helper('print(' + repr(CANARY) + ')\n')
        self.hash_assets()
        for name in ASSETS:
            with self.subTest(asset=name):
                path = self.incoming / name
                before = path.read_bytes()
                path.write_bytes(before + b'# tampered\n')
                self.assert_refused(self.run_shell(self.invoke))
                path.write_bytes(before)

    def test_untrusted_run_digest_phase_owner_and_hardlink_prevent_execution(self):
        self.set_helper('print(' + repr(CANARY) + ')\n')
        self.hash_assets()
        for field, value in (('NRI_RUN', '1234-1\n' + CANARY), ('NRI_HELPER_SHA', 'f' * 64 + '\n'),
                             ('NRI_PHASE', CANARY), ('TEST_UID', '1000')):
            self.assert_refused(self.run_shell(self.invoke, **{field: value}))
        os.link(self.incoming / ASSETS[1], self.base / 'extra-public-link')
        self.assert_refused(self.run_shell(self.invoke))
        self.assert_refused(self.run_shell(self.cleanup))
        self.assertTrue((self.incoming / ASSETS[1]).exists())
        self.assertTrue((self.base / 'extra-public-link').exists())

    def test_linked_asset_is_rejected(self):
        target = self.base / 'outside-public'
        target.write_text(CANARY)
        path = self.incoming / ASSETS[1]
        path.unlink()
        path.symlink_to(target)
        self.assert_refused(self.run_shell(self.invoke))
        self.assert_refused(self.run_shell(self.cleanup))
        self.assertEqual(target.read_text(), CANARY)

    def test_failed_helper_stdout_and_stderr_are_not_published(self):
        self.set_helper("import sys\nprint(" + repr(CANARY) + ")\nprint(" + repr(CANARY) + ", file=sys.stderr)\nsys.exit(1)\n")
        self.hash_assets()
        self.assert_refused(self.run_shell(self.invoke))

    def test_success_exit_does_not_publish_unvalidated_output(self):
        for output in (CANARY, CANARY + '\n{}', json.dumps({'unexpected': CANARY}), 'x' * 4097):
            self.set_helper('print(' + repr(output) + ')\n')
            self.hash_assets()
            result = self.run_shell(self.invoke)
            self.assert_refused(result)
            self.assertIn('RETIREMENT_IMAGES_OUTPUT_REFUSED', result.stdout)

    def test_output_shape_and_value_types_fail_closed(self):
        for key, value in (('session', CANARY), ('phase', 'send'), ('status', CANARY),
                           ('error', CANARY), ('ssh_public_key', CANARY), ('bytes', CANARY),
                           ('sha256', CANARY), ('image_size_bytes', True),
                           ('process_rc', {'gpg': CANARY}), ('backup_verified', True)):
            payload = self.report()
            payload[key] = value
            self.set_report(payload)
            self.hash_assets()
            self.assert_refused(self.run_shell(self.invoke))

    def test_failure_report_is_public_metadata_and_keeps_failure_exit(self):
        payload = self.report()
        payload.update(status='failed', error='source_refused')
        self.set_report(payload, rc=2)
        self.hash_assets()
        result = self.run_shell(self.invoke)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout.split('=', 1)[1]), payload)
        self.assertEqual(result.stderr, '')

    def test_valid_send_and_cleanup_reports_match_the_fixed_phase(self):
        payload = self.report()
        payload.update(phase='send', status='transferred_unverified', ssh_public_key=None,
                       bytes=1024, sha256='a' * 64, process_rc={'docker': 0, 'gpg': 0, 'ssh': 0})
        for status in ('transferred_unverified', 'transport_key_removed', 'already_closed'):
            if status != 'transferred_unverified':
                payload.update(phase='cleanup', status=status, image_size_bytes=None,
                               bytes=None, sha256=None, process_rc=None, resources=None)
            self.set_report(payload)
            self.hash_assets()
            result = self.run_shell(self.invoke, NRI_PHASE=payload['phase'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.split('=', 1)[1]), payload)

    def test_success_cannot_omit_required_fields_or_claim_failed_processes(self):
        prepared = self.report()
        sent = dict(prepared, phase='send', status='transferred_unverified',
                    ssh_public_key=None, bytes=512, sha256='a' * 64,
                    process_rc={'docker': 0, 'gpg': 0, 'ssh': 0})
        cleaned = dict(prepared, phase='cleanup', status='transport_key_removed',
                       ssh_public_key=None, image_size_bytes=None, resources=None)
        cases = [(prepared, 'ssh_public_key', None), (prepared, 'image_size_bytes', 0),
                 (prepared, 'image_size_bytes', 268435457), (prepared, 'error', 'source_refused'),
                 (prepared, 'bytes', 1), (sent, 'bytes', 0), (sent, 'bytes', 536870913),
                 (sent, 'sha256', None), (sent, 'process_rc', None),
                 (sent, 'process_rc', {'gpg': 2, 'ssh': 0}),
                 (sent, 'process_rc', {'gpg': 0, 'ssh': 0}),
                 (sent, 'ssh_public_key', PUBLIC_KEY), (cleaned, 'image_size_bytes', 351)]
        for base, field, value in cases:
            with self.subTest(phase=base['phase'], field=field, value=value):
                payload = dict(base, **{field: value})
                self.set_report(payload)
                self.hash_assets()
                self.assert_refused(self.run_shell(self.invoke, NRI_PHASE=payload['phase']))

    def test_duplicate_json_keys_and_failed_status_without_error_are_refused(self):
        raw = json.dumps(self.report())[:-1] + ', "error": null}'
        self.set_helper('print(' + repr(raw) + ')\n')
        self.hash_assets()
        self.assert_refused(self.run_shell(self.invoke))
        self.set_report(dict(self.report(), status='failed'), rc=2)
        self.hash_assets()
        self.assert_refused(self.run_shell(self.invoke))

    def test_outer_deadline_exceeds_bounded_source_and_precedes_ssh_timeout(self):
        self.assertIn('timeout -k 5s "$outer_timeout" python3 -I -B', self.invoke)
        self.assertIn('outer_timeout=930s', self.invoke)
        self.assertIn('outer_timeout=1830s', self.invoke)
        self.assertIn('command_timeout: 32m', self.source)
        self.assertIn('timeout-minutes: 45', self.source)

    def test_cleanup_only_removes_public_assets_and_empty_directory(self):
        # SCP can fail before remote ownership/mode normalization.
        for name in ASSETS:
            (self.incoming / name).chmod(0o644)
        result = self.run_shell(self.cleanup)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.incoming.exists())
        cleanup_step = self.parts[-1]
        self.assertIn("if: always() && steps.prepare_remote.outcome == 'success'", cleanup_step)
        self.assertNotIn('"$helper"', cleanup_step)
        self.assertNotIn('images-preservation-20261102-v1', cleanup_step)
        self.assertNotIn('rm -r', cleanup_step)

    def test_cleanup_unknown_entry_is_preserved_and_reported_incomplete(self):
        unexpected = self.incoming / 'unrelated'
        unexpected.write_text(CANARY)
        result = self.run_shell(self.cleanup)
        self.assert_refused(result)
        self.assertIn('RETIREMENT_IMAGES_CLEANUP_INCOMPLETE', result.stdout)
        self.assertEqual(unexpected.read_text(), CANARY)

    def test_helper_temporary_directory_must_be_exclusive_private_and_owned(self):
        prepare = next(p for p in self.parts if 'id: prepare_remote' in p)
        self.assertIn('umask 077', prepare)
        self.assertIn('[ ! -L /tmp ]', prepare)
        self.assertIn('mkdir "/tmp/metainc-images-preservation-$NRI_RUN"', prepare)
        self.assertNotIn('mkdir -p', prepare)
        self.incoming.chmod(0o755)
        self.assert_refused(self.run_shell(self.invoke))
        self.assert_refused(self.run_shell(self.cleanup))

    def test_every_embedded_shell_block_parses(self):
        for part in self.parts:
            for key in ('run', 'script'):
                if re.search(r'^ +' + key + r': \|$', part, re.MULTILINE):
                    result = subprocess.run(['/bin/bash', '-n'], input=block(part, key),
                                            text=True, capture_output=True, timeout=3)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_preservation_changes_never_trigger_app_deploy_and_ci_covers_workflow(self):
        deploy = (ROOT / '.github/workflows/deploy.yml').read_text()
        ignored = re.findall(r"^      - '([^']+)'", deploy, re.MULTILINE)
        paths = ['.github/workflows/deploy.yml', '.github/workflows/naver-tools-check.yml',
                 '.github/workflows/naver-images-preservation.yml',
                 'deploy/naver/retirement_images_source.py', 'deploy/naver/retirement_key_capsule_receiver.py',
                 'deploy/naver/preservation/recovery-public.asc',
                 'deploy/naver/preservation/server-b-known-hosts',
                 'deploy/naver/tests/test_retirement_key_capsule_workflow.py']
        for path in paths:
            self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in ignored), path)
        checks = (ROOT / '.github/workflows/naver-tools-check.yml').read_text().split('\n  push:', 1)[0]
        self.assertIn("'.github/workflows/naver-images-preservation.yml'", checks)
        self.assertIn("'deploy/naver/**'", checks)

    def test_only_four_profiles_are_accepted_and_forwarded_without_interpolation(self):
        for name in ('autobid-web', 'autobid-engine', 'autobid-watchdog', 'content-studio'):
            self.assertEqual(self.run_shell(self.guard, NRI_PROFILE=name).returncode, 0)
        for name in ('', 'ad-image', 'unknown', 'autobid-web;echo ' + CANARY, 'autobid-web\n' + CANARY):
            self.assert_refused(self.run_shell(self.guard, NRI_PROFILE=name))
            self.assert_refused(self.run_shell(self.invoke, NRI_PROFILE=name))
        self.set_helper('import sys\nassert sys.argv[1:] == ["prepare", "autobid-web"]\nprint(' + repr(json.dumps(self.report())) + ')\n')
        self.hash_assets()
        self.assertEqual(self.run_shell(self.invoke).returncode, 0)

    def test_profile_session_size_and_resources_are_bound_to_selected_image(self):
        for name, size in (('autobid-web', 84303740), ('autobid-engine', 84303743), ('autobid-watchdog', 84303745)):
            payload = dict(self.report(), session=name + '-image-20261102-v1', image_size_bytes=size)
            self.set_report(payload)
            self.hash_assets()
            self.assertEqual(self.run_shell(self.invoke, NRI_PROFILE=name).returncode, 0)
            other = 'autobid-engine' if name == 'autobid-web' else 'autobid-web'
            self.assert_refused(self.run_shell(self.invoke, NRI_PROFILE=other))
        for field, value in (('resources', None), ('resources', {'path': CANARY})):
            self.set_report(dict(self.report(), **{field: value}))
            self.hash_assets()
            self.assert_refused(self.run_shell(self.invoke))
        for field, value in (('client_version', [28, True, 1]), ('driver', CANARY),
                             ('required_free_bytes', True), ('large_export_gate', 'reviewed'),
                             ('driver', 'unknown'), ('storage_backend', 'graphdriver'), ('tmpdir', 'unknown')):
            payload = self.report()
            payload['resources'][field] = value
            self.set_report(payload)
            self.hash_assets()
            self.assert_refused(self.run_shell(self.invoke))

    def test_content_resource_receipt_cannot_enable_export(self):
        payload = dict(self.report(), session='content-studio-image-20261102-v1', image_size_bytes=1381032080)
        payload['resources']['large_export_gate'] = 'reviewed'
        self.set_report(payload)
        self.hash_assets()
        self.assert_refused(self.run_shell(self.invoke, NRI_PROFILE='content-studio'))
        payload.update(status='failed', error='large_image_not_reviewed', ssh_public_key=None)
        payload['resources']['large_export_gate'] = 'unreviewed'
        self.set_report(payload, rc=2)
        self.hash_assets()
        result = self.run_shell(self.invoke, NRI_PROFILE='content-studio')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout.split('=', 1)[1]), payload)

    def test_content_success_requires_exact_reviewed_exporter_versions(self):
        payload = dict(self.report(), session='content-studio-image-20261102-v1', image_size_bytes=1381032080)
        payload['resources'].update(client_version=[29, 4, 0], server_version=[29, 4, 0], large_export_gate='reviewed')
        self.set_report(payload)
        self.hash_assets()
        self.assertEqual(self.run_shell(self.invoke, NRI_PROFILE='content-studio').returncode, 0)
        for key, value in (('client_version', [29, 4, 1]), ('server_variant', 'suffixed'),
                           ('driver', 'overlay2'), ('large_export_gate', 'unreviewed')):
            candidate = json.loads(json.dumps(payload))
            candidate['resources'][key] = value
            self.set_report(candidate)
            self.hash_assets()
            self.assert_refused(self.run_shell(self.invoke, NRI_PROFILE='content-studio'))

    def test_closed_ad_assets_remain_exactly_frozen(self):
        expected = {
            'deploy/naver/retirement_preserve_source.py': '3c7ef9d9d344447fafffe967d8218f3e00de06ba6e74858ccae67f41e034d792',
            'deploy/naver/retirement_cipher_receiver.py': 'eaa4b96c9ab807d615bf4958fa35fff4c8d35bbc91044e09dbc1ed2bd9bae5de',
            'deploy/naver/retirement_image_verify.py': 'a9d52a9788fae8431e8d9d0b7b0385f1c650c906c392138c1b3f4f66631214eb',
            '.github/workflows/naver-image-preservation.yml': 'f9b574a2cbbfc3fde2ea74bb3d9eab49ee37695615577053f748173f71af4bca',
        }
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
