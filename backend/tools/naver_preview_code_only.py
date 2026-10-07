"""Gated, schema-compatible code replacement without controller DB access.

The explicit workflow modes accept only the separate reviewed source/archive/store
transitions sealed below. Their file scopes are not interchangeable.
"""
import json
import os
import pwd
import re

# Reviewed 6198be3 -> e4f64e1 transition. Never derive this approval from request input.
# Tuple: old/new commit, old/new archive SHA256, old/new store SHA256, host baseline.
REVIEWED_TRANSITION = (
    '6198be366344a82923e10ba5e323877026d82f48',
    'e4f64e165ebdf81d4127218d5c91ff6904e75958',
    'b9071a746aa1879d518849bb5a76a8d2259a5d77853e28298fcd26fc7ea0d90e',
    '716d849b68d72cb03489bc16da1cee3d9a0f31cb16612287b407fe244dea84c6',
    '5fa2618f3d74bdfaa10581f6ac759d605544ab0e0e8178eef89f68d8e6840c94',
    '5fa2618f3d74bdfaa10581f6ac759d605544ab0e0e8178eef89f68d8e6840c94',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)
REVIEWED_TRANSITION_V3 = (
    'e4f64e165ebdf81d4127218d5c91ff6904e75958',
    '953c2ccdb1d74a4fd339de013a1bbbbc5f50e3b6',
    '716d849b68d72cb03489bc16da1cee3d9a0f31cb16612287b407fe244dea84c6',
    '461be6b6ae6d09d74108f9f96a5e2bcf68feffdd2728c43f1b5e460be743ac80',
    '5fa2618f3d74bdfaa10581f6ac759d605544ab0e0e8178eef89f68d8e6840c94',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)


def code_module_name(source_commit):
    if type(source_commit) is str and source_commit == REVIEWED_TRANSITION[1]:
        return 'naver_preview_code_upgrade'
    if type(source_commit) is str and source_commit == REVIEWED_TRANSITION_V3[1]:
        return 'naver_preview_code_upgrade_v3'
    raise ValueError('CODE_ONLY_RELEASE_NOT_REVIEWED')


def require_review(code):
    transition = (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256,
                  code.TARGET_SOURCE_SHA256, code.STORE_SHA256.get('old'),
                  code.STORE_SHA256.get('target'), code.EXPECTED_BASELINE)
    expected_paths = ({'naver_engine/catalog_links.py', 'naver_engine/dashboard.py', 'naver_engine/inventory.py'}
        if transition == REVIEWED_TRANSITION else
        {'naver_engine/inventory.py', 'naver_engine/store.py', 'naver_engine/naver_read.py', 'naver_engine/morning.py'}
        if transition == REVIEWED_TRANSITION_V3 else None)
    if expected_paths is None or code.CODE_PATHS != expected_paths or code.TEST_PATHS != frozenset():
        raise ValueError('CODE_ONLY_RELEASE_NOT_REVIEWED')


def prepare(package, host, release, lifecycle, upgrade, code):
    code.STAGE, code.OPERATION = 'code_prepare_preflight', 'package'
    require_review(code)
    result = code.prepare(package, host, release, lifecycle, upgrade)
    return dict(result, database_policy='preserve-in-place', database_opened_by_controller=False)


def apply(package, host, release, lifecycle, upgrade, code):
    code.STAGE, code.OPERATION = 'code_apply_preflight', 'package'
    require_review(code)
    if not isinstance(package, dict) or set(package) != {'release', 'operation_id'}:
        raise ValueError('CODE_APPLY_FIELDS')
    identity = package['operation_id']
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
        raise ValueError('CODE_OPERATION_ID')
    prepared = code.validate_package(package['release'], release)
    code.OPERATION = 'current_state'
    old_path, old_receipt, old_files, _, bootstrap = code.current_state(prepared, host, release, lifecycle, upgrade)
    code.OPERATION = 'target_manifest'
    path, receipt = upgrade.manifest(release, code.TARGET_COMMIT, prepared)
    code.OPERATION = 'compatible_source'
    code.compatible_source(old_path, path, upgrade)
    code.OPERATION = 'unit_manifest'
    new_files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    if new_files[lifecycle.TMPFILES] != old_files[lifecycle.TMPFILES]:
        raise ValueError('TMPFILES_CHANGED')
    started = release.ROOT/'receipts'/('preview-start-'+code.TARGET_COMMIT+'.json')
    recovery = release.ROOT/'receipts'/('code-upgrade-'+identity+'.json')
    if any(os.path.lexists(p) for p in (started, recovery)):
        raise ValueError('CODE_ALREADY_ATTEMPTED')
    code.OPERATION = 'write_recovery_receipt'
    release.write_new(recovery, json.dumps({
        'source_commit':code.OLD_COMMIT, 'target_commit':code.TARGET_COMMIT,
        'database_policy':'preserve-in-place', 'images':old_receipt['images'],
        'units':{str(p):b.decode() for p,b in old_files.items() if p != lifecycle.TMPFILES}},
        sort_keys=True).encode())
    replaced = []

    def unchanged_state():
        require_review(code)
        if host.baseline() != prepared['baseline'] or code.bootstrap_state(release, upgrade) != bootstrap:
            raise ValueError('CODE_POST_STATE')

    def name(unit):
        return 'engine' if unit == lifecycle.UNITS[0] else 'relay'

    try:
        code.STAGE = 'code_stop_isolated'
        for unit in reversed(lifecycle.UNITS):
            code.OPERATION = 'stop_'+name(unit)
            release.command(['/usr/bin/systemctl', 'stop', unit], timeout=90)
            code.OPERATION = 'stop_check_'+name(unit)
            code.stopped_writer(release, lifecycle, old_path, {code.OLD_COMMIT:old_receipt['images']}, unit)
        code.OPERATION = 'bootstrap_check'
        unchanged_state()
        code.STAGE = 'code_recreate'
        for service in ('engine', 'relay'):
            code.OPERATION = 'recreate_'+service
            release.command(release.compose(path, service)+['up', '--no-start', '--no-build', '--force-recreate'], timeout=90)
        code.STAGE = 'code_replace_units'
        for unit in lifecycle.UNITS:
            code.OPERATION = 'replace_unit_'+name(unit)
            target = lifecycle.UNIT_DIR/unit
            replaced.append(target)
            upgrade.replace_unit(target, old_files[target], new_files[target], identity, release)
        code.OPERATION = 'daemon_reload'
        release.command(['/usr/bin/systemctl', 'daemon-reload'])
        code.STAGE = 'code_start'
        for unit in lifecycle.UNITS:
            code.OPERATION = 'start_'+name(unit)
            release.command(['/usr/bin/systemctl', 'start', unit], timeout=90)
        code.STAGE, code.OPERATION = 'code_verify', 'verify_running'
        verify_running(path, receipt, release, lifecycle, upgrade, code)
        code.OPERATION = 'post_state'
        unchanged_state()
        result = dict(ok=True, stage='internal_ready', source_commit=code.TARGET_COMMIT,
                      previous_commit=code.OLD_COMMIT, operation_id=identity, nginx_changed=False,
                      legacy_containers_unchanged=True, bootstrap_unchanged=True,
                      unauthenticated_read_status=401, business_post_status=403,
                      database_policy='preserve-in-place', database_opened_by_controller=False,
                      database_snapshot_verified=False, source_warmup_performed=False,
                      rollback_requires_matching_database=False, collection_completion_verified=False)
        code.OPERATION = 'write_started_receipt'
        release.write_new(started, json.dumps(result, sort_keys=True).encode())
        return result
    except Exception as error:
        details = code._capture_failure(error)
        code.STAGE = 'code_rollback'
        failed = False

        def attempt(function, *args, **kwargs):
            nonlocal failed
            try:
                function(*args, **kwargs)
                return True
            except Exception as rollback_error:
                if 'rollback_stage' not in details:
                    details.update(code._capture_failure(rollback_error, 'rollback'))
                failed = True
                return False

        def restore_unit(target):
            if upgrade.read_file(target, mode=0o644, maximum=32768) != old_files[target]:
                upgrade.replace_unit(target, new_files[target], old_files[target], identity+'-rollback', release)

        for unit in reversed(lifecycle.UNITS):
            code.OPERATION = 'stop_'+name(unit)
            attempt(release.command, ['/usr/bin/systemctl', 'stop', unit], timeout=90)
        for unit in lifecycle.UNITS:
            code.OPERATION = 'stop_check_'+name(unit)
            attempt(code.stopped_writer, release, lifecycle, old_path,
                    {code.OLD_COMMIT:old_receipt['images'], code.TARGET_COMMIT:receipt['images']}, unit)
        if not failed:
            code.OPERATION = 'rollback_state'
            attempt(unchanged_state)
        if not failed:
            code.OPERATION = 'compatible_source'
            attempt(code.compatible_source, old_path, path, upgrade)
        if not failed:
            code.OPERATION = 'old_manifest'
            attempt(upgrade.manifest, release, code.OLD_COMMIT, started=True)
        if not failed:
            for target in reversed(replaced):
                code.OPERATION = 'restore_unit_'+name(target.name)
                if not attempt(restore_unit, target):
                    break
        if not failed:
            for service in ('engine', 'relay'):
                code.OPERATION = 'recreate_'+service
                if not attempt(release.command, release.compose(old_path, service)+
                               ['up', '--no-start', '--no-build', '--force-recreate'], timeout=90):
                    break
        if not failed:
            code.OPERATION = 'daemon_reload'
            attempt(release.command, ['/usr/bin/systemctl', 'daemon-reload'])
        if not failed:
            for unit in lifecycle.UNITS:
                code.OPERATION = 'start_'+name(unit)
                if not attempt(release.command, ['/usr/bin/systemctl', 'start', unit], timeout=90):
                    break
            if not failed:
                code.OPERATION = 'verify_running'
                attempt(verify_running, old_path, old_receipt, release, lifecycle, upgrade, code)
        code.OPERATION = 'rollback_state'
        attempt(unchanged_state)
        if failed:
            for unit in reversed(lifecycle.UNITS):
                code.OPERATION = 'stop_'+name(unit)
                attempt(release.command, ['/usr/bin/systemctl', 'stop', unit], timeout=90)
        refused = RuntimeError('CODE_ROLLBACK_FAILED' if failed else 'CODE_ONLY_FAILED_ROLLED_BACK')
        refused.failure_details = details
        raise refused from None


def verify_running(path, receipt, release, lifecycle, upgrade, code):
    # No direct DB reader, docker exec, warmup, or integrity assertion here.
    source = receipt.get('source_commit')
    if source not in (code.OLD_COMMIT, code.TARGET_COMMIT) or path.name != 'naver-'+source:
        raise ValueError('CODE_PROBE_SOURCE')
    code.probe(release, source, upgrade)
    lifecycle._snapshot(release, path, receipt['images'])
    for unit in (lifecycle.TUNNEL, *lifecycle.UNITS):
        if lifecycle._state(release, unit, 'ActiveState') != 'active':
            raise ValueError('CODE_SERVICE_NOT_ACTIVE')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release, unit, 'UnitFileState') != 'enabled':
            raise ValueError('CODE_SERVICE_NOT_ENABLED')


def failure_report(error, code):
    result = code.failure_report(error)
    if type(error) in (ValueError, RuntimeError) and error.args in (
            ('CODE_ONLY_RELEASE_NOT_REVIEWED',), ('CODE_ONLY_FAILED_ROLLED_BACK',)):
        result['error_code'] = error.args[0]
    return result
