"""Verify the private qualification and the exact public release before SSH."""
import ast
import hashlib
import types
import json
import os
from pathlib import Path
import re
import subprocess
import sys

BASE = '35f2f5b7d3c3feefbc6bd6eaf838f63ebbbcbfbd'
PRIVATE_BASE = '7b8eecf673d5d9db0c79b8a705414d07a87b1aed'
PRIVATE_REPO = 'metainchelp-boop/metainc-ad-dashboard'
PRIVATE_REF = 'refs/heads/codex/naver-conversion-baseline-transition-20261026'
REPO = 'metainchelp-boop/logic-analysis'
RELEASE = 'codex/naver-conversion-existing-executor-20261026'
IMPL = 'codex/naver-conversion-baseline-executor-20261026'
NS = 'release/conversion-20261026'
WORKFLOW = '.github/workflows/debug-rank.yml'
ROOT = Path(__file__).resolve().parents[1]
COMMANDS = (
    "PYTHONPATH=backend/tools:backend/tests python3 -m unittest discover -s backend/tests -p 'test_naver_preview_*.py' -q",
    'PYTHONPATH=backend/tools:backend/tests python3 -m unittest test_report_progress_patch test_report_progress_transport test_report_progress_epoch test_naver_completion_download test_naver_saved_exports test_naver_saved_exports_inspect test_naver_completion_export_diagnostics test_naver_completion_failed_apply_recovery -q',
)
CHECKOUT = '11d5960a326750d5838078e36cf38b85af677262'
PYTHON = 'a26af69be951a213d495a4c3e4e4022e16d87065'


def need(ok, label):
    if ok is not True:
        raise ValueError(label)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    out = {}
    for key, value in pairs:
        need(key not in out, 'DUPLICATE_JSON')
        out[key] = value
    return out


def read(root, name, cap=1024 * 1024):
    path = root / name
    need(path.resolve() == path and path.is_file() and not path.is_symlink(), 'FILE_PATH')
    need(0 < path.stat().st_size <= cap, 'FILE_SIZE')
    return path.read_bytes()


def git(root, *args):
    result = subprocess.run(['git', *args], cwd=root, stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=30)
    need(result.returncode == 0, 'GIT')
    return result.stdout


def expected_workflow(original):
    """Only declared scheduling/path changes; original SSH and ownership code."""
    old = "    if: github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/codex/naver-proof-release-20261020' && "
    new = ("    needs: checks\n    if: github.repository == '" + REPO +
           "' && github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/" + RELEASE +
           "' && github.run_attempt == 1 && ")
    need(original.count(old) == 1, 'ORIGINAL_JOB_GUARD')
    job = original.replace(old, new)
    job = job.replace('    steps:\n', f'    defaults:\n      run:\n        working-directory: {NS}\n    steps:\n', 1)
    start = job.index('      - name: Bundle\n')
    end = job.index('      - name: Incoming\n', start)
    job = job[:start] + f'''      - uses: actions/setup-python@{PYTHON}
        with:
          python-version: '3.12'
      - name: Verify exact qualified release before building wire
        working-directory: .
        run: python3 -I -B tools/check_conversion_executor.py --deploy
      - name: Bundle
        env:
          RUN_ID: ${{{{github.run_id}}}}
          PYTHONDONTWRITEBYTECODE: '1'
        run: python3 -I -B bundle.py
''' + job[end:]
    need(job.count('          source: preview-payload/runtime-secrets.cms\n') == 1, 'TRANSFER_SOURCE')
    job = job.replace('          source: preview-payload/runtime-secrets.cms\n',
                      f'          source: {NS}/preview-payload/runtime-secrets.cms\n')
    need(job.count('          strip_components: 1\n') == 1, 'TRANSFER_STRIP')
    job = job.replace('          strip_components: 1\n', '          strip_components: 3\n')
    return f'''name: Conversion diagnostic through existing VPS connection

on:
  push:
    branches: [{IMPL}, {RELEASE}]
  pull_request:
    branches: [{RELEASE}]
  workflow_dispatch:
    inputs:
      ad_prepare:
        type: choice
        required: true
        default: 'off'
        options: ['off', preview-report-progress-prepare, preview-report-progress-apply, preview-report-progress-rollback]
      ad_expected_baseline:
        type: string
        required: true
        default: '{{}}'

permissions:
  contents: read

jobs:
  checks:
    if: github.repository == '{REPO}'
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@{CHECKOUT}
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@{PYTHON}
        with:
          python-version: '3.12'
      - name: Check new public qualification boundary
        run: python3 -I -B -m unittest discover -s tools -p test_conversion_executor.py -q
      - name: Verify qualified files and exact workflow
        run: python3 -I -B tools/check_conversion_executor.py
''' + job


def qualification(receipt, policy):
    need(receipt['schema'] == 'private-conversion-bundle-qualification-v1', 'RECEIPT_SCHEMA')
    for key, value in {'repository': PRIVATE_REPO, 'ref': PRIVATE_REF, 'base': PRIVATE_BASE,
                       'workflow': '.github/workflows/naver-conversion-bundle-private.yml',
                       'status': 'pass', 'base_files': 796, 'private_fixtures': 6,
                       'qualification_scope': 'baseline_transition_bundle_checks_private_only'}.items():
        need(receipt[key] == value and type(receipt[key]) is type(value), 'RECEIPT_IDENTITY')
    need(receipt['private'] is True and receipt['deployment_ready'] is False, 'RECEIPT_SCOPE')
    need(type(receipt['attempt']) is int and receipt['attempt'] == 1, 'RECEIPT_ATTEMPT')
    need(receipt['server_calls'] == receipt['secret_values_read'] == 0, 'RECEIPT_NO_SERVER')
    for key in ('head', 'tree', 'run_id'):
        need(receipt[key] == policy['private_' + key], 'PRIVATE_RUN_BINDING')
    need(policy['run_conclusion'] == policy['job_conclusion'] == 'success', 'PRIVATE_SUCCESS')
    need(policy['spec_review'] == policy['standards_review'] == 'pass', 'PRIVATE_REVIEWS')
    need(len(receipt['checks']) == 2, 'CHECK_COUNT')
    for index, row in enumerate(receipt['checks']):
        skipped = 2 if index == 0 else 0
        need(row['command_sha256'] == sha(COMMANDS[index].encode()), 'CHECK_COMMAND')
        need(all(type(row[k]) is int for k in ('tests', 'passed', 'skipped', 'skipped_cases', 'errors', 'failures')), 'CHECK_TYPES')
        need(row['tests'] > skipped and row['passed'] == row['tests'] - skipped, 'CHECK_COUNTS')
        need(row['skipped'] == skipped and row['errors'] == row['failures'] == 0, 'CHECK_RESULT')
        need(row['skipped_cases'] == (3 if index == 0 else 0), 'CHECK_SKIP_CASES')
        replays = ['test_naver_preview_verify_database_repro.VerifyDatabaseReplay.' + name for name in (
            'test_actual_old_and_new_store_with_closed_report_fixture',
            'test_actual_new_store_with_live_wal_writer_and_report_transaction')]
        need(row['expected_skipped_replays'] == (replays if skipped else []), 'CHECK_SKIP_IDENTITY')
    transition = receipt['transition']
    expected_transition = {'base': '7ec30317b1f91ffb65fa97ac6e2711a114b03247', 'manifest_sha256': 'b4843960260e570cf0222770e49b6b8ee87ac3bd4fce607e77bb8fbad6449d21', 'tests': 7, 'passed': 7, 'failures': 0, 'errors': 0, 'skipped': 0, 'command_sha256': sha(b'PYTHONPATH=backend/tools:backend/tests python3 -m unittest test_conversion_baseline_transition -q'), 'historical_baseline': '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76', 'current_baseline': '1a107fb029873d44ccfc09b1001c5d85b3dd5e871c008adeadb516e12b72e3cd'}
    need(set(transition) == set(expected_transition), 'TRANSITION_FIELDS')
    need(all(type(transition[k]) is type(v) and transition[k] == v for k, v in expected_transition.items()), 'TRANSITION_PROOF')
    need(len(receipt['public_files']) == 12, 'PUBLIC_TOOL_COUNT')


def deploy_context(env, event):
    need(env.get('GITHUB_REPOSITORY') == REPO and env.get('GITHUB_REF') == 'refs/heads/' + RELEASE, 'RELEASE_IDENTITY')
    need(env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and env.get('GITHUB_RUN_ATTEMPT') == '1', 'EVENT_ATTEMPT')
    need(re.fullmatch('[0-9a-f]{40}', env.get('GITHUB_SHA', '')) is not None, 'HEAD_FORMAT')
    need(re.fullmatch('[0-9]{6,20}', env.get('GITHUB_RUN_ID', '')) is not None, 'RUN_FORMAT')
    need(event.get('repository', {}).get('full_name') == REPO, 'EVENT_REPO')
    inputs = event.get('inputs', {})
    need(inputs.get('ad_prepare') in {'preview-report-progress-' + x for x in ('prepare', 'apply', 'rollback')}, 'OPERATION')
    need(type(inputs.get('ad_expected_baseline')) is str, 'PACKAGE')
    need(all(value == 'off' for name, value in inputs.items() if name not in ('ad_prepare', 'ad_expected_baseline')), 'OTHER_INPUTS')


APPLY_ID = 'd43ebab98f5941f08146490e48e71aab'
ROLLBACK_ID = 'cb95f18a925e4637a8c5c7ac7b4583d0'


def operation_packages(env, event):
    inputs = event['inputs']
    operation = inputs['ad_prepare']
    package = json.loads(inputs['ad_expected_baseline'], object_pairs_hook=unique)
    need(type(package) is dict, 'PRESSURE_PACKAGE')
    if operation == 'preview-report-progress-prepare':
        need(set(package) == {'baseline', 'source_commit', 'source_tar_gz_sha256', 'ciphertext_sha256', 'download_url', 'artifact_sha256'}, 'PREPARE_FIELDS')
        release = {k: package[k] for k in ('baseline', 'source_commit', 'source_tar_gz_sha256', 'ciphertext_sha256')}
        release.update(operation='code-prepare', run_id=env['GITHUB_RUN_ID'])
    else:
        expected = {'release', 'operation_id'} | ({'apply_operation_id'} if operation == 'preview-report-progress-rollback' else set())
        need(set(package) == expected, 'OPERATION_FIELDS')
        need(package['operation_id'] == (ROLLBACK_ID if operation.endswith('rollback') else APPLY_ID), 'RESERVED_OPERATION')
        if operation.endswith('rollback'):need(package['apply_operation_id'] == APPLY_ID, 'RESERVED_APPLY')
        release = package['release']
    need(type(release) is dict and set(release) == {'operation', 'baseline', 'source_commit', 'source_tar_gz_sha256', 'ciphertext_sha256', 'run_id'}, 'RELEASE_FIELDS')
    need(type(release['run_id']) is str and re.fullmatch('[0-9]{6,20}', release['run_id']) is not None, 'PREPARE_RUN_ID')
    return [('prepare', release), ('apply', {'release': release, 'operation_id': APPLY_ID}),
            ('rollback', {'release': release, 'apply_operation_id': APPLY_ID, 'operation_id': ROLLBACK_ID})]


def pressure(root, env, event):
    # verify() and deploy_context() must pass before this function is called.
    folder = root / NS
    def module(name):
        path = folder / 'backend/tools' / (name + '.py')
        raw = read(root, path.relative_to(root).as_posix())
        value = types.ModuleType(name); value.__file__ = str(path)
        exec(compile(raw, str(path), 'exec'), value.__dict__)
        return value, raw
    transport, raw = module('naver_report_progress_transport')
    patch, _ = module('naver_report_progress_patch')
    transport.TRANSPORT_RAW_SHA256 = sha(raw)
    transport.require_pins(); patch.require_pins()
    bootstrap = transport.bootstrap(raw)
    helpers = [n for n in ast.parse(read(root, NS + '/bundle.py')).body if isinstance(n, ast.FunctionDef)]
    need({n.name for n in helpers} == {'report_progress_ssh_scripts', 'require_report_progress_ssh_pressure'}, 'PRESSURE_HELPERS')
    namespace = {}; exec(compile(ast.Module(body=helpers, type_ignores=[]), 'qualified-pressure', 'exec'), namespace)
    previous = sys.modules.get('naver_report_progress_patch')
    sys.modules['naver_report_progress_patch'] = patch
    try:
        rows = []
        packages = operation_packages(env, event)
        for operation, package in packages:
            package = json.loads(json.dumps(package, sort_keys=True))
            value = transport.bundle('preview-report-progress-' + operation, package, folder / 'backend/tools')
            if operation == 'prepare':
                modules = transport.modules(value)
                modules['patch'].validate_package(package, modules['release'])
            wire = transport.encode(value)
            need(transport.decode(wire) == value, 'PRESSURE_ROUNDTRIP')
            sizes = namespace['require_report_progress_ssh_pressure'](wire, bootstrap, read(root, NS + '/' + WORKFLOW).decode())
            rows.append({'operation': operation, 'json_bytes': len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()),
                         'wire_bytes': len(wire), 'bootstrap_bytes': len(bootstrap), 'ssh_bytes': sizes})
        return {'prepare_run_id': packages[0][1]['run_id'], 'rows': rows, 'server_calls': 0, 'cipher_downloads': 0}
    finally:
        if previous is None:sys.modules.pop('naver_report_progress_patch', None)
        else:sys.modules['naver_report_progress_patch'] = previous


def verify(root):
    policy = json.loads(read(root, NS + '/release-policy.json', 16384), object_pairs_hook=unique)
    raw = read(root, NS + '/qualification.json', 16384)
    need(sha(raw) == policy['receipt_sha256'], 'QUALIFICATION_HASH')
    receipt = json.loads(raw, object_pairs_hook=unique)
    qualification(receipt, policy)
    manifest = json.loads(read(root, NS + '/public-files.json', 16384), object_pairs_hook=unique)
    additions = {NS + '/' + name for name in receipt['public_files']} | {
        NS + '/bundle.py', NS + '/' + WORKFLOW, NS + '/qualification.json',
        NS + '/release-policy.json', NS + '/public-files.json', NS + '/README.md',
        'tools/check_conversion_executor.py', 'tools/test_conversion_executor.py'}
    expected = additions | {WORKFLOW}
    need(set(manifest) == expected - {NS + '/public-files.json'}, 'MANIFEST_PATH_SET')
    for name, row in manifest.items():
        body = read(root, name)
        need(set(row) == {'bytes', 'sha256'} and len(body) == row['bytes'] and sha(body) == row['sha256'], 'FILE_DIGEST')
    for name, row in receipt['public_files'].items():
        need(name.startswith('backend/') and name.endswith('.py') and '/fixtures/' not in name, 'PUBLIC_TOOL_PATH')
        need(manifest[NS + '/' + name] == row, 'QUALIFIED_TOOL_DIGEST')
    original = read(root, NS + '/' + WORKFLOW)
    need(sha(original) == receipt['report_progress_job_sha256'], 'ORIGINAL_JOB')
    need(sha(read(root, NS + '/bundle.py')) == receipt['bundle_python_sha256'], 'ORIGINAL_BUNDLE')
    need(read(root, WORKFLOW).decode() == expected_workflow(original.decode()), 'WORKFLOW_DELTA')
    changes = git(root, 'diff', '--name-status', BASE, 'HEAD').decode().splitlines()
    need(set(changes) == {'A\t' + name for name in additions} | {'M\t' + WORKFLOW}, 'RELEASE_CHANGE_SET')
    need(git(root, 'status', '--porcelain', '--untracked-files=no') == b'', 'DIRTY_SOURCE')
    need(git(root, 'ls-files', '--others', '-z') == b'', 'UNTRACKED_SOURCE')
    return receipt


if __name__ == '__main__':
    try:
        receipt = verify(ROOT)
        if sys.argv[1:] == ['--deploy']:
            event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes(), object_pairs_hook=unique)
            deploy_context(os.environ, event)
            need(git(ROOT, 'rev-parse', 'HEAD').decode().strip() == os.environ['GITHUB_SHA'], 'EXECUTION_HEAD')
            print(json.dumps({'actual_operation_pressure': pressure(ROOT, os.environ, event)}))
        else:
            need(sys.argv[1:] == [], 'ARGUMENTS')
        print(json.dumps({'public_boundary': 'PASS', 'private_run': receipt['run_id'], 'server_calls': 0}))
    except Exception:
        print('CONVERSION_EXECUTOR_REFUSED', file=sys.stderr)
        sys.exit(1)
