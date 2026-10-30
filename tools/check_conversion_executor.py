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
PRIVATE_REF = 'refs/heads/claude/naver-conversion-pool-first-executor-20261030'
# Exact private qualification identity for the c44a -> abceeb7 pool-first release.
PRIVATE_HEAD = 'ee04b7fb7f863081e5f0712e07b24792b2631578'
PRIVATE_TREE = 'dc4f52da6da54620d6b4f93ec7753e868a0a3b43'
PRIVATE_RUN_ID = '41017595072'
QUALIFICATION_SCOPE = 'pool_first_bundle_checks_private_only'
REPORT_PROGRESS_JOB_SHA256 = '3951c27ffbd5b9c365df7731290abb90f372be82fbfcb1cd6ca86c1fb8829cc6'
BUNDLE_PYTHON_SHA256 = '546c7cb729428add49a79fcac72eeb05fb652ff67dbdd236ce0f947bf0d602c9'
PUBLIC_FILES = {"backend/naver_market_export.py": {"bytes": 17992, "sha256": "d491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8"}, "backend/naver_product_export.py": {"bytes": 20647, "sha256": "42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59"}, "backend/tools/naver_completion_download.py": {"bytes": 3548, "sha256": "cc5f87d78f05cac5ad1ceebf99c79505edd4604fd65007403e752d06c0e05c5e"}, "backend/tools/naver_completion_exports.py": {"bytes": 10121, "sha256": "1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed"}, "backend/tools/naver_erp_tunnel_service_install.py": {"bytes": 30508, "sha256": "236cdd596bae2f8d5e0dfea5822bdd7216c44addac2bbb643306dfbff00fdd3a"}, "backend/tools/naver_preview_completion_release.py": {"bytes": 130559, "sha256": "3be9c0360a6f75192455d6b139317319dd111b4e404628505ae62783b37977e2"}, "backend/tools/naver_preview_lifecycle.py": {"bytes": 8083, "sha256": "4f5f85c197b5efe2c323b2c784814eb1bd177dd60d44b8c7ead943b0af98abc4"}, "backend/tools/naver_preview_release.py": {"bytes": 23235, "sha256": "7288d51eba4e2c0320d196b8da2ee14f852b87f33304c221878c218cd1dacb84"}, "backend/tools/naver_preview_upgrade.py": {"bytes": 19571, "sha256": "6aa60100ba8ae39c07be4016498a4c79076c540707bee6a44e651c8de8e62c28"}, "backend/tools/naver_report_progress_patch.py": {"bytes": 123343, "sha256": "0048f014041bf451d26835dffce314a57d699f6046c85000362faedfee175596"}, "backend/tools/naver_report_progress_transport.py": {"bytes": 19812, "sha256": "58bc51e9a26f49a54ca59e4e9f5188f43c963fc9f050c4738e3ac3305aa14fd5"}, "backend/tools/naver_saved_exports.py": {"bytes": 37216, "sha256": "062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737"}}
POOL_FIRST = {
    'base': '49275594f9c9344afd403b32f129756194423e1b',
    'manifest_sha256': 'fbd61469ff15fd5d067257e08792ac9d4e5b53e24eb5bd53f4ad5401f4ab2f2d',
    'tests': 20, 'passed': 20, 'failures': 0, 'errors': 0, 'skipped': 0,
    'command_sha256': hashlib.sha256(b'PYTHONPATH=backend/tools:backend/tests python3 -m unittest test_conversion_pool_first_transition test_report_progress_store_history -q').hexdigest(),
    'old_commit': 'c44a66393340314796851f4dd524dad523bd5415',
    'target_commit': 'abceeb737548ada081072df95279d19981b561f7',
    'private_fixtures_added': 2,
    'reserved_apply_operation_id': '01330a7419d0494d8bfb74ec1fcb7e28',
    'reserved_rollback_operation_id': 'ba912f5af5d34a6985d9415013f90486',
}
# The two added private fixtures (pinned by the layer-2 manifest above) must be the exact
# old/new schema rows the qualified controller deploys.
POOL_FIRST_FIXTURES = {
    'fixtures/c44a66393340314796851f4dd524dad523bd5415/naver_runtime/report_output_schema.py': (420, 10231, '3b978c85f92233fb5d4afdfce2c6b761b431db5f6c41de4b1e781829b793ee2a'),
    'fixtures/abceeb737548ada081072df95279d19981b561f7/naver_runtime/report_output_schema.py': (420, 10448, '109b76c3ec0af340491842657a0902dd1aa05112dde089499b2bbfc4981a56fd'),
}
POLICY_FIELDS = frozenset({'job_conclusion', 'private_artifact_id', 'private_artifact_sha256', 'private_fixture_bodies_exported',
                           'private_head', 'private_job_id', 'private_run_id', 'private_tree', 'receipt_sha256', 'run_conclusion',
                           'schema', 'secret_values_copied', 'spec_review', 'standards_review', 'trust_boundary'})
RECEIPT_FIELDS = frozenset({'schema', 'repository', 'private', 'ref', 'head', 'base', 'tree', 'run_id', 'attempt', 'status',
                            'workflow', 'base_manifest_sha256', 'base_files', 'private_fixtures', 'report_progress_job_sha256',
                            'bundle_python_sha256', 'transition', 'pool_first', 'checks', 'public_files', 'server_calls',
                            'secret_values_read', 'qualification_scope', 'deployment_ready'})
REPO = 'metainchelp-boop/logic-analysis'
RELEASE = 'codex/naver-conversion-existing-executor-20261026'
IMPL = 'claude/naver-conversion-pool-first-executor-20261030'
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
    need(type(receipt) is dict and set(receipt) == RECEIPT_FIELDS, 'RECEIPT_FIELDS')
    need(receipt['schema'] == 'private-conversion-bundle-qualification-v1', 'RECEIPT_SCHEMA')
    for key, value in {'repository': PRIVATE_REPO, 'ref': PRIVATE_REF, 'base': PRIVATE_BASE,
                       'workflow': '.github/workflows/naver-conversion-bundle-private.yml',
                       'status': 'pass', 'base_files': 796, 'private_fixtures': 6,
                       'base_manifest_sha256': 'ff1703526eca736923839c250bcebde1f9e20a8a305f4f7eb3341746583510c9',
                       'head': PRIVATE_HEAD, 'tree': PRIVATE_TREE, 'run_id': PRIVATE_RUN_ID,
                       'report_progress_job_sha256': REPORT_PROGRESS_JOB_SHA256,
                       'bundle_python_sha256': BUNDLE_PYTHON_SHA256,
                       'qualification_scope': QUALIFICATION_SCOPE}.items():
        need(receipt[key] == value and type(receipt[key]) is type(value), 'RECEIPT_IDENTITY')
    need(receipt['private'] is True and receipt['deployment_ready'] is False, 'RECEIPT_SCOPE')
    need(type(receipt['attempt']) is int and receipt['attempt'] == 1, 'RECEIPT_ATTEMPT')
    need(receipt['server_calls'] == receipt['secret_values_read'] == 0, 'RECEIPT_NO_SERVER')
    for key in ('head', 'tree', 'run_id'):
        need(receipt[key] == policy['private_' + key], 'PRIVATE_RUN_BINDING')
    need(type(policy) is dict and set(policy) == POLICY_FIELDS and policy['schema'] == 'conversion-existing-executor-release-policy-v1', 'POLICY_FIELDS')
    need(policy['trust_boundary'] == 'owner_reviewed_exact_public_release_commit'
         and policy['private_fixture_bodies_exported'] == 0 and policy['secret_values_copied'] == 0, 'POLICY_SCOPE')
    need(type(policy['private_job_id']) is int and type(policy['private_artifact_id']) is int
         and re.fullmatch('[0-9a-f]{64}', policy['private_artifact_sha256']) is not None, 'POLICY_ARTIFACT')
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
    need(receipt['public_files'] == PUBLIC_FILES, 'PUBLIC_TOOL_DIGESTS')
    pool_first = receipt['pool_first']
    need(type(pool_first) is dict and set(pool_first) == set(POOL_FIRST), 'POOL_FIRST_FIELDS')
    need(all(type(pool_first[k]) is type(v) and pool_first[k] == v for k, v in POOL_FIRST.items()), 'POOL_FIRST_PROOF')


def pinned_bytes(root, name, row):
    """Read a release file once and accept only its exact pinned size and digest.

    Callers compile/exec or parse only the returned bytes; the file is never read again."""
    need(type(row) is dict and set(row) == {'bytes', 'sha256'}, 'PINNED_ROW')
    raw = read(root, name)
    need(len(raw) == row['bytes'] and sha(raw) == row['sha256'], 'PINNED_DIGEST')
    return raw


def pinned_module(root, tool):
    """Execute a qualified release tool only after its bytes match PUBLIC_FILES."""
    relative = 'backend/tools/' + tool + '.py'
    raw = pinned_bytes(root, NS + '/' + relative, PUBLIC_FILES[relative])
    path = root / NS / relative
    value = types.ModuleType(tool); value.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), value.__dict__)
    return value, raw


def pool_first_identity(root):
    """The qualified controller deploys exactly the privately tested fixture rows and IDs."""
    patch, _ = pinned_module(root, 'naver_report_progress_patch')
    patch.require_pins()
    old, new = POOL_FIRST_FIXTURES.values()
    need((patch.OLD_COMMIT, patch.TARGET_COMMIT) == (POOL_FIRST['old_commit'], POOL_FIRST['target_commit']), 'POOL_FIRST_COMMITS')
    need(patch.TARGET_DELTA == {'naver_runtime/report_output_schema.py': new}, 'POOL_FIRST_TARGET_FIXTURE')
    need(patch.U2_D['naver_runtime/report_output_schema.py'] == old and 'naver_runtime/report_output_schema.py' not in patch.U3_D
         and 'naver_runtime/report_output_schema.py' not in patch.C44_D, 'POOL_FIRST_OLD_FIXTURE')
    need(all(name.split('/')[1] in (POOL_FIRST['old_commit'], POOL_FIRST['target_commit']) for name in POOL_FIRST_FIXTURES), 'POOL_FIRST_FIXTURE_PATHS')
    need((APPLY_ID, ROLLBACK_ID) == (POOL_FIRST['reserved_apply_operation_id'], POOL_FIRST['reserved_rollback_operation_id']), 'RESERVED_IDENTITY')


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


APPLY_ID = '01330a7419d0494d8bfb74ec1fcb7e28'
ROLLBACK_ID = 'ba912f5af5d34a6985d9415013f90486'


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
    # Every release file used here is read once and digest-checked before parse/compile/exec.
    folder = root / NS
    transport, raw = pinned_module(root, 'naver_report_progress_transport')
    patch, _ = pinned_module(root, 'naver_report_progress_patch')
    transport.TRANSPORT_RAW_SHA256 = sha(raw)
    transport.require_pins(); patch.require_pins()
    bootstrap = transport.bootstrap(raw)
    bundle_raw = read(root, NS + '/bundle.py')
    need(sha(bundle_raw) == BUNDLE_PYTHON_SHA256, 'PINNED_DIGEST')
    job_raw = read(root, NS + '/' + WORKFLOW)
    need(sha(job_raw) == REPORT_PROGRESS_JOB_SHA256, 'PINNED_DIGEST')
    job = job_raw.decode()
    helpers = [n for n in ast.parse(bundle_raw).body if isinstance(n, ast.FunctionDef)]
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
            sizes = namespace['require_report_progress_ssh_pressure'](wire, bootstrap, job)
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
    # Only now, with every digest, the workflow delta, the change set and a clean tree verified,
    # execute the controller (re-checked against its pin on the single read it executes).
    pool_first_identity(root)
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
