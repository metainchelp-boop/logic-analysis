"""Explicit, separately reviewed rollback after a successful code-only apply.

Only the separately reviewed operating49 -> final74, operating74 -> reader
correction, reader -> progress-observation and observation -> loading-read transitions
can roll back here.
Request inputs cannot grant another release.
"""
import json
import os
import pwd
import re


REVIEWED_ROLLBACKS = frozenset({(
    '49c42d645b90732071d0c61b8f9aaf7660e8b765',
    '74b79ce6381178abf9b74fff43b0fcb03c5aa60b',
    '69b9f79ab243eac6d3d32fe67ce267b96bdd923323997fd2661934bc6a5459d4',
    '7136119034645500fa31cd1afb85d72b70264144ab62d0181ada6e06ec0484cf',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
    frozenset({'backend/app/naver_auto/matching.py', 'naver_engine/inventory.py',
        'naver_engine/naver_read.py', 'naver_runtime/scheduler.py',
        'naver_engine/management_store.py', 'naver_runtime/writer.py', 'naver_engine/web.py'}),

), (
    '74b79ce6381178abf9b74fff43b0fcb03c5aa60b',
    '383c8511964c13e24e884a4cee561fc9bee64102',
    '7136119034645500fa31cd1afb85d72b70264144ab62d0181ada6e06ec0484cf',
    'a55b8a3a4b87e69b936778298ef95be41241ebdbd322fe5fa467883543b2229e',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
    frozenset({'naver_engine/web.py', 'naver_runtime/scheduler.py'}),
), (
    '383c8511964c13e24e884a4cee561fc9bee64102',
    '96f10f05b0e92651e04b2076999fa6c6ace7291e',
    'a55b8a3a4b87e69b936778298ef95be41241ebdbd322fe5fa467883543b2229e',
    'a58f46db0367b9b03deb6f141b080b10bbe1d51c7ce91b3265497e9b9c20856f',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
    frozenset({'naver_engine/web.py', 'naver_runtime/scheduler.py', 'naver_runtime/runtime_status.py'}),
), (
    '96f10f05b0e92651e04b2076999fa6c6ace7291e',
    '7985925dcc4ed9d75c28ae43a456964cdc78c63f',
    'a58f46db0367b9b03deb6f141b080b10bbe1d51c7ce91b3265497e9b9c20856f',
    '47632d4d3403c24dd4988b80c1a0ada25cc155fc6048a7f2413fb72d84ea73ff',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
    frozenset({'backend/naver_page/app.js', 'naver_engine/views.py', 'naver_engine/web.py'}),
)})
# Reviewed V9 rollback tuple and exact resource decision.
REVIEWED_RESOURCE_LIMITS_V9 = True
REVIEWED_ROLLBACK_V9 = (
    '7985925dcc4ed9d75c28ae43a456964cdc78c63f', 'bd08fd07281ae5448bffb3de3d7c405887bfecd9',
    '47632d4d3403c24dd4988b80c1a0ada25cc155fc6048a7f2413fb72d84ea73ff', '6b1618ab9dd47eca6030d1092bdbce1d451d30ce8fdf103e448a96f3ac9da3f1',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862', 'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
    frozenset({'naver_engine/inventory.py', 'naver_engine/management_store.py'}) |
        (frozenset({'compose.naver-engine.yml'}) if REVIEWED_RESOURCE_LIMITS_V9 is True else frozenset()),
)
if (type(REVIEWED_ROLLBACK_V9[1]) is str and re.fullmatch('[0-9a-f]{40}', REVIEWED_ROLLBACK_V9[1])
        and type(REVIEWED_ROLLBACK_V9[3]) is str and re.fullmatch('[0-9a-f]{64}', REVIEWED_ROLLBACK_V9[3])
        and type(REVIEWED_RESOURCE_LIMITS_V9) is bool):
    REVIEWED_ROLLBACKS |= frozenset({REVIEWED_ROLLBACK_V9})

# Reviewed V10 reverse transition: exact source/archive; Store and compose unchanged.
REVIEWED_ROLLBACK_V10 = (
    'bd08fd07281ae5448bffb3de3d7c405887bfecd9', '3fa096d3d383123fdd3469c5dc68404171a6f076', '6b1618ab9dd47eca6030d1092bdbce1d451d30ce8fdf103e448a96f3ac9da3f1', '1a528165dae3f2e896d98e950f1b92369f997af2ce4e2d823febb7b18c86a6de',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862', 'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76', frozenset({'naver_engine/web.py'}),
)
if (type(REVIEWED_ROLLBACK_V10[1]) is str and re.fullmatch('[0-9a-f]{40}', REVIEWED_ROLLBACK_V10[1])
        and type(REVIEWED_ROLLBACK_V10[3]) is str and re.fullmatch('[0-9a-f]{64}', REVIEWED_ROLLBACK_V10[3])):
    REVIEWED_ROLLBACKS |= frozenset({REVIEWED_ROLLBACK_V10})

# V11 reverse tuple is not admitted until every target/archive/Store pin is exact.
REVIEWED_ROLLBACK_V11 = (
    '3fa096d3d383123fdd3469c5dc68404171a6f076', '9bfcace1c6ba2a49807c5ec8feb69fde11de73bf', '1a528165dae3f2e896d98e950f1b92369f997af2ce4e2d823febb7b18c86a6de', '1acf8f5d9f54d075655ed263026a77745b75548bbee8fd66a2286aeee404628e',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862', 'de9d1fe5886055d07261bc41687666cfe5f800fe582a02057910026ef564ca53', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
    frozenset({'naver_engine/store.py', 'naver_engine/inventory.py', 'naver_engine/dashboard.py', 'naver_engine/web.py'}),
)
if (type(REVIEWED_ROLLBACK_V11[1]) is str and re.fullmatch('[0-9a-f]{40}', REVIEWED_ROLLBACK_V11[1])
        and all(type(REVIEWED_ROLLBACK_V11[index]) is str
            and re.fullmatch('[0-9a-f]{64}', REVIEWED_ROLLBACK_V11[index]) for index in (3, 4, 5))):
    REVIEWED_ROLLBACKS |= frozenset({REVIEWED_ROLLBACK_V11})

STAGE = 'input'
OPERATION = 'none'


def transition(code):
    return (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256,
            code.TARGET_SOURCE_SHA256, code.STORE_SHA256.get('old'),
            code.STORE_SHA256.get('target'), code.EXPECTED_BASELINE,
            frozenset(code.CODE_PATHS))


def require_review(policy, code):
    policy.require_review(code)
    if (transition(code) not in REVIEWED_ROLLBACKS
            or (code.STORE_SHA256.get('old') != code.STORE_SHA256.get('target')
                and transition(code) != REVIEWED_ROLLBACK_V11)):
        raise ValueError('CODE_ROLLBACK_NOT_REVIEWED')


def validate_package(package, release, policy, code):
    require_review(policy, code)
    if not isinstance(package, dict) or set(package) != {'release', 'apply_operation_id', 'operation_id'}:
        raise ValueError('CODE_ROLLBACK_FIELDS')
    original, identity = package['apply_operation_id'], package['operation_id']
    if (not isinstance(original, str) or not re.fullmatch('[0-9a-f]{32}', original)
            or not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity)
            or original == identity):
        raise ValueError('CODE_ROLLBACK_OPERATION_ID')
    return code.validate_package(package['release'], release)


def run(package, host, release, lifecycle, upgrade, policy, code):
    global STAGE, OPERATION
    STAGE, OPERATION = 'rollback_preflight', 'package'
    prepared = validate_package(package, release, policy, code)
    original, identity = package['apply_operation_id'], package['operation_id']
    if os.geteuid() != 0 or host.baseline() != prepared['baseline']:
        raise ValueError('HOST_BASELINE')
    old_path, old_receipt = upgrade.manifest(release, code.OLD_COMMIT, started=True)
    path, receipt = upgrade.manifest(release, code.TARGET_COMMIT, prepared, started=True)
    for value, digest in ((old_receipt, code.OLD_SOURCE_SHA256),
                          (receipt, code.TARGET_SOURCE_SHA256)):
        if (value['package'].get('baseline') != prepared['baseline']
                or value['package'].get('source_tar_gz_sha256') != digest):
            raise ValueError('CODE_ROLLBACK_SOURCE')
    code.compatible_source(old_path, path, upgrade)
    files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    old_files = lifecycle.unit_files(old_path, pwd.getpwnam('www-data').pw_gid, release)
    if files[lifecycle.TMPFILES] != old_files[lifecycle.TMPFILES]:
        raise ValueError('TMPFILES_CHANGED')
    for parent in (lifecycle.UNIT_DIR, lifecycle.TMPFILES.parent, release.ROOT / 'receipts'):
        release.trusted_dir(parent)
    for filename, body in files.items():
        if upgrade.read_file(filename, mode=0o644, maximum=32768) != body:
            raise ValueError('CODE_ROLLBACK_UNIT')
    if lifecycle._state(release, 'docker.service', 'ActiveState') != 'active':
        raise ValueError('DEPENDENCY_NOT_ACTIVE')
    policy.verify_running(path, receipt, release, lifecycle, upgrade, code)
    saved_path = release.ROOT / 'receipts' / ('code-upgrade-' + original + '.json')
    started_path = release.ROOT / 'receipts' / ('preview-start-' + code.TARGET_COMMIT + '.json')
    read = lambda filename: upgrade.read_file(filename, mode=0o600, maximum=32768)
    saved_raw, started_raw = read(saved_path), read(started_path)
    saved = json.loads(saved_raw, object_pairs_hook=release.unique)
    started = json.loads(started_raw, object_pairs_hook=release.unique)
    expected_saved = dict(source_commit=code.OLD_COMMIT, target_commit=code.TARGET_COMMIT,
        database_policy='preserve-in-place', images=old_receipt['images'],
        units={str(p): b.decode() for p, b in old_files.items() if p != lifecycle.TMPFILES})
    if saved != expected_saved:
        raise ValueError('CODE_ROLLBACK_RECOVERY')
    if (started.get('ok') is not True or started.get('stage') != 'internal_ready'
            or started.get('source_commit') != code.TARGET_COMMIT
            or started.get('previous_commit') != code.OLD_COMMIT
            or started.get('operation_id') != original
            or started.get('database_policy') != 'preserve-in-place'
            or started.get('database_opened_by_controller') is not False
            or started.get('source_warmup_performed') is not False):
        raise ValueError('CODE_ROLLBACK_STARTED')
    bootstrap = code.bootstrap_state(release, upgrade)
    attempt = release.ROOT / 'receipts' / ('code-post-rollback-' + identity + '.json')
    result_path = attempt.with_name('code-post-rollback-' + identity + '.result.json')
    if any(os.path.lexists(p) for p in (attempt, result_path)):
        raise ValueError('CODE_ROLLBACK_ALREADY_ATTEMPTED')
    # A new operation receipt, never replacement of either historical start receipt.
    release.write_new(attempt, json.dumps(dict(source_commit=code.TARGET_COMMIT,
        target_commit=code.OLD_COMMIT, apply_operation_id=original,
        operation_id=identity, database_policy='preserve-in-place'), sort_keys=True).encode())

    def unchanged():
        require_review(policy, code)
        if (host.baseline() != prepared['baseline']
                or code.bootstrap_state(release, upgrade) != bootstrap
                or read(saved_path) != saved_raw or read(started_path) != started_raw):
            raise ValueError('CODE_ROLLBACK_STATE')
        if (upgrade.manifest(release, code.OLD_COMMIT, started=True) != (old_path, old_receipt)
                or upgrade.manifest(release, code.TARGET_COMMIT, prepared, started=True) != (path, receipt)):
            raise ValueError('CODE_ROLLBACK_SOURCE')
        code.compatible_source(old_path, path, upgrade)

    try:
        STAGE = 'rollback_stop'
        for unit in reversed(lifecycle.UNITS):
            OPERATION = 'stop_' + unit
            release.command(['/usr/bin/systemctl', 'stop', unit], timeout=90)
            code.stopped_writer(release, lifecycle, path,
                {code.TARGET_COMMIT: receipt['images']}, unit)
        OPERATION = 'unchanged'
        unchanged()
        STAGE = 'rollback_restore'
        # manifest verifies retained image IDs; no image build/pull, DB open or warmup.
        for name in ('engine', 'relay'):
            OPERATION = 'recreate_' + name
            release.command(release.compose(old_path, name) +
                ['up', '--no-start', '--no-build', '--force-recreate'], timeout=90)
        for unit in reversed(lifecycle.UNITS):
            OPERATION = 'replace_' + unit
            filename = lifecycle.UNIT_DIR / unit
            upgrade.replace_unit(filename, files[filename], old_files[filename], identity, release)
        OPERATION = 'daemon_reload'
        release.command(['/usr/bin/systemctl', 'daemon-reload'])
        unchanged()
        STAGE = 'rollback_start'
        for unit in lifecycle.UNITS:
            OPERATION = 'start_' + unit
            release.command(['/usr/bin/systemctl', 'start', unit], timeout=90)
        STAGE, OPERATION = 'rollback_verify', 'verify_running'
        policy.verify_running(old_path, old_receipt, release, lifecycle, upgrade, code)
        for filename, body in old_files.items():
            if upgrade.read_file(filename, mode=0o644, maximum=32768) != body:
                raise ValueError('CODE_ROLLBACK_UNIT')
        unchanged()
        result = dict(ok=True, stage='internal_ready', operation='code-only-rollback',
            source_commit=code.OLD_COMMIT, previous_commit=code.TARGET_COMMIT,
            operation_id=identity, apply_operation_id=original,
            database_policy='preserve-in-place', database_opened_by_controller=False,
            source_warmup_performed=False, nginx_changed=False)
        release.write_new(result_path, json.dumps(result, sort_keys=True).encode())
        return result
    except Exception as error:
        # A failed post-success rollback is not permission to run either unverified writer.
        failed_stage, failed_operation = STAGE, OPERATION
        STAGE, OPERATION = 'rollback_failed_stop', 'stop_isolated'
        stop_verified = True
        for unit in reversed(lifecycle.UNITS):
            try:
                release.command(['/usr/bin/systemctl', 'stop', unit], timeout=90)
            except Exception:
                stop_verified = False
        for unit in lifecycle.UNITS:
            try:
                code.stopped_writer(release, lifecycle, path,
                    {code.OLD_COMMIT: old_receipt['images'],
                     code.TARGET_COMMIT: receipt['images']}, unit)
            except Exception:
                stop_verified = False
        refused = RuntimeError('CODE_POST_ROLLBACK_FAILED')
        kind = type(error).__name__
        refused.failure_details = dict(failed_stage=failed_stage,
            failed_operation=failed_operation,
            failed_error_kind=kind if kind in code.FAILURE_KINDS else 'UNRECOGNIZED',
            isolated_stop_verified=stop_verified)
        raise refused from None


def failure_report(error, code):
    stages = {'input', 'rollback_preflight', 'rollback_stop', 'rollback_restore',
              'rollback_start', 'rollback_verify', 'rollback_failed_stop'}
    labels = {'CODE_ROLLBACK_NOT_REVIEWED', 'CODE_ROLLBACK_FIELDS',
              'CODE_ROLLBACK_OPERATION_ID', 'CODE_ROLLBACK_SOURCE',
              'CODE_ROLLBACK_UNIT', 'CODE_ROLLBACK_RECOVERY', 'CODE_ROLLBACK_STARTED',
              'CODE_ROLLBACK_ALREADY_ATTEMPTED', 'CODE_ROLLBACK_STATE',
              'CODE_POST_ROLLBACK_FAILED', 'CODE_ONLY_RELEASE_NOT_REVIEWED'}
    kind = type(error).__name__
    result = dict(stage=STAGE if STAGE in stages else 'preflight',
        error_kind=kind if kind in code.FAILURE_KINDS else 'OtherError',
        error_code=error.args[0] if type(error) in (ValueError, RuntimeError)
            and len(error.args) == 1 and error.args[0] in labels | code.FAILURE_CODES
            else 'UNRECOGNIZED')
    details = getattr(error, 'failure_details', {})
    if type(details) is dict and type(details.get('isolated_stop_verified')) is bool:
        result['isolated_stop_verified'] = details['isolated_stop_verified']
    return result
