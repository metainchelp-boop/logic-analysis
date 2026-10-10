"""New-only systemd attachment to approved, already-running preview containers.

install(package, host, release) receives the already-loaded trusted release module;
no imports from the workspace, environment values or credential output are used.
"""
import json
import os
from pathlib import Path
import pwd
import re
import time

UNIT_DIR = Path('/etc/systemd/system')
UNITS = ('metainc-naver-engine.service', 'metainc-naver-relay.service')
TUNNEL = 'metainc-naver-erp-tunnel.service'
TMPFILES = Path('/etc/tmpfiles.d/metainc-naver-preview.conf')
STAGE = 'input'
CREATED = []


def unit_files(release_path, nginx_gid, release):
    if type(nginx_gid) is not int or not 0 < nginx_gid < 2**31:
        raise ValueError('NGINX_GROUP')
    files = {TMPFILES: ('d /run/metainc 0755 root root -\n'
             'd /run/metainc/naver-engine 0750 10001 10001 -\n'
             f'd /run/metainc/naver-relay 0750 10001 {nginx_gid} -\n').encode()}
    for number, name in enumerate(('engine', 'relay')):
        dependency = TUNNEL if name == 'engine' else UNITS[0]
        command = ['/usr/bin/docker', *release.compose(release_path, name)[1:]]
        start = ' '.join(command + ['up', '--no-build', '--no-recreate', '--abort-on-container-exit',
                                   '--exit-code-from', 'naver-'+name, 'naver-'+name])
        stop = ' '.join(command + ['stop', '--timeout', '45', 'naver-'+name])
        files[UNIT_DIR/UNITS[number]] = ('[Unit]\nDescription=Naver isolated '+name+' supervisor\n'
            'Requires=docker.service '+dependency+'\nAfter=docker.service '+dependency+
            '\nAfter=systemd-tmpfiles-setup.service\nStartLimitIntervalSec=0\n\n'
            '[Service]\nType=exec\nUser=root\nGroup=root\nUMask=0077\n'
            'Environment=PATH=/usr/sbin:/usr/bin:/sbin:/bin\n'
            'ExecStartPre=/usr/bin/systemd-tmpfiles --create '+str(TMPFILES)+'\n'
            'ExecStart='+start+'\nExecStop='+stop+'\nRestart=always\nRestartSec=10s\n'
            'TimeoutStopSec=70s\nStandardOutput=null\nStandardError=null\n\n'
            '[Install]\nWantedBy=multi-user.target\n').encode()
    return files


def _state(release, unit, field):
    return release.command(['/usr/bin/systemctl', 'show', unit, '-p', field, '--value']).decode().strip()


def _snapshot(release, path, images):
    rows = {}
    fields = {'id': '.Id', 'image': '.Image', 'running': '.State.Running',
              'started': '.State.StartedAt', 'restarts': '.RestartCount',
              'project': '(index .Config.Labels "com.docker.compose.project")',
              'service': '(index .Config.Labels "com.docker.compose.service")'}
    fmt = '{'+','.join(json.dumps(key)+':{{json '+value+'}}' for key, value in fields.items())+'}'
    for name in ('engine', 'relay'):
        identity = release.command(release.compose(path, name)+['ps', '--all', '--quiet']).decode().strip()
        if not re.fullmatch('[0-9a-f]{64}', identity):
            raise ValueError('PREVIEW_CONTAINER_ID')
        row = json.loads(release.command(['docker', 'inspect', '--format', fmt, identity]))
        if (row.get('id') != identity or row.get('image') != images[name] or row.get('running') is not True
                or row.get('restarts') != 0 or not row.get('started')
                or row.get('project') != 'naver-'+name or row.get('service') != 'naver-'+name):
            raise ValueError('PREVIEW_CONTAINER_STATE')
        rows[name] = row
    return rows


def install(package, host, release):
    global STAGE
    STAGE = 'preflight'
    release.validate_package(package)
    if package['operation'] != 'start' or os.geteuid() != 0 or host.baseline() != package['baseline']:
        raise ValueError('HOST_BASELINE')
    path, receipt_path = release.prepared_paths(package['source_commit'])
    receipt = json.loads(receipt_path.read_text(), object_pairs_hook=release.unique)
    started_path = receipt_path.with_name('preview-start-'+package['source_commit']+'.json')
    release.trusted_private_file(started_path)
    started = json.loads(started_path.read_text(), object_pairs_hook=release.unique)
    if (receipt.get('ok') is not True or receipt.get('stage') != 'prepared'
            or receipt.get('package') != {k: v for k, v in package.items() if k != 'operation'}
            or started.get('ok') is not True or started.get('stage') != 'internal_ready'
            or started.get('source_commit') != package['source_commit']):
        raise ValueError('SOURCE_NOT_READY')
    expected = {str(path/'deploy/naver-engine-backup.override.yml')}
    expected.update(str(path/(prefix+name+suffix)) for name in ('engine', 'relay')
                    for prefix, suffix in (('compose.naver-', '.yml'), ('preview-', '.override.yml')))
    expected.update(str(release.SECRET_ROOT/name) for name in release.SECRET_OWNERS)
    if set(receipt['files']) != expected or set(receipt['images']) != {'engine', 'relay'}:
        raise ValueError('PREPARED_MANIFEST')
    for filename, digest in receipt['files'].items():
        if release.sha(Path(filename).read_bytes()) != digest:
            raise ValueError('PREPARED_FILE_CHANGED')
    for name in ('engine', 'relay'):
        image = json.loads(release.command(['docker', 'image', 'inspect', '--format', '{{json .Id}}',
                                           'metainc/naver-'+name+':'+package['source_commit']]))
        if image != receipt['images'][name]:
            raise ValueError('PREPARED_IMAGE_CHANGED')
    before = _snapshot(release, path, receipt['images'])
    if any(_state(release, unit, 'ActiveState') != 'active' for unit in ('docker.service', TUNNEL)):
        raise ValueError('DEPENDENCY_NOT_ACTIVE')
    prior = _state(release, TUNNEL, 'UnitFileState')
    if prior not in ('enabled', 'disabled'):
        raise ValueError('TUNNEL_ENABLE_STATE')
    files = unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    for parent in (UNIT_DIR, TMPFILES.parent):
        release.trusted_dir(parent)
    if (any(os.path.lexists(filename) for filename in files)
            or any(os.path.lexists(UNIT_DIR/'multi-user.target.wants'/unit) for unit in UNITS)
            or any(_state(release, unit, 'LoadState') != 'not-found' for unit in UNITS)):
        raise ValueError('PREEXISTING_LIFECYCLE')
    attempted, tunnel_changed = [], False
    try:
        STAGE = 'new_files'
        for filename, body in files.items():
            CREATED.append(str(filename))
            release.write_new(filename, body, mode=0o644)
        STAGE = 'enable_and_attach'
        release.command(['/usr/bin/systemctl', 'daemon-reload'])
        tunnel_changed = prior == 'disabled'
        release.command(['/usr/bin/systemctl', 'enable', TUNNEL, *UNITS])
        for unit in UNITS:
            attempted.append(unit)
            release.command(['/usr/bin/systemctl', 'start', unit], timeout=90)
        STAGE = 'verify'
        for _ in range(3):
            time.sleep(1)
            for unit in (TUNNEL, *UNITS):
                if _state(release, unit, 'ActiveState') != 'active' or _state(release, unit, 'UnitFileState') != 'enabled':
                    raise ValueError('LIFECYCLE_NOT_ACTIVE')
            if host.baseline() != package['baseline'] or _snapshot(release, path, receipt['images']) != before:
                raise ValueError('CONTAINER_BASELINE_CHANGED')
        return {'ok': True, 'services_active_enabled': True, 'new_containers_restarted': False,
                'legacy_containers_unchanged': True, 'source_commit': package['source_commit']}
    except Exception:
        failures = []
        for args in ([['/usr/bin/systemctl', 'stop', unit] for unit in reversed(attempted)]
                     + [['/usr/bin/systemctl', 'disable', unit] for unit in UNITS]
                     + ([['/usr/bin/systemctl', 'disable', TUNNEL]] if tunnel_changed else [])):
            try:
                release.command(args, timeout=90)
            except Exception:
                failures.append(True)
        if failures:
            raise RuntimeError('LIFECYCLE_ROLLBACK_FAILED') from None
        raise
