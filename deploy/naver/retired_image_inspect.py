"""Bounded, metadata-only observation of five preserved Docker image identities.

This is an observation of the active Docker image store, not a removal plan.
Neither Parent nor layer similarity proves complete image ancestry.
"""
import hashlib
import json
import os
import re
import selectors
import subprocess
import sys
import time

SCOPE = 'naver-retired-image-inspect-v1'
DOCKER = ('/usr/bin/docker', '--host=unix:///var/run/docker.sock')
ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent',
       'DOCKER_CONFIG': '/nonexistent/metainc-retired-image-inspect', 'LC_ALL': 'C'}
CANDIDATES = (
    ('ad-api', 'sha256:959001525d45612e0c5cc1045291c7b6caefa768c14d37cc1070c26584cb8922'),
    ('content-studio', 'sha256:b52374a33084ea20386af2380478a38cff92eebdbeff97c616ad7d80a112a0dc'),
    ('autobid-web', 'sha256:075e4cd227777d7ea5347c27c0842067bc963cead5c6b6cc60b71897105140ec'),
    ('autobid-engine', 'sha256:3b86b60dd010faba75e910bdac4d8acc1678a3eabf1f54463fe5a64bf1cc0f6d'),
    ('autobid-watchdog', 'sha256:935ce49a4c3981eda46e1ae39c76daf831fd90107410d1823ea133f7b86cffad'),
)
MAX_IMAGES = 512
MAX_CONTAINERS = 4096
MAX_REFS = 256
MAX_LAYERS = 512
MAX_SIZE = 1 << 50
MAX_COMMAND_BYTES = 1 << 20
MAX_TOTAL_BYTES = 8 << 20
MAX_REPORT_BYTES = 32768
COMMAND_SECONDS = 10
TOTAL_SECONDS = 120
BATCH_SIZE = 32
HEX = re.compile(r'[0-9a-f]{64}\Z')
IMAGE_ID = re.compile(r'sha256:[0-9a-f]{64}\Z')
STATES = frozenset(('created', 'running', 'paused', 'restarting', 'removing', 'exited', 'dead'))
REASONS = frozenset(('OK', 'INPUT_REFUSED', 'NOT_ROOT', 'UNSUPPORTED_PLATFORM',
                     'COMMAND_FAILED', 'COMMAND_TIMEOUT', 'OUTPUT_LIMIT', 'ITEM_LIMIT',
                     'INVALID_METADATA', 'IDENTITY_MISMATCH', 'MISSING_CONTAINER_IMAGE',
                     'REFERENCE_MISMATCH', 'INVENTORY_CHANGED', 'INTERNAL_ERROR'))
INFO_FORMAT = ('{"id":{{json .ID}},"driver":{{json .Driver}},'
               '"driver_status":{{json .DriverStatus}},"root":{{json .DockerRootDir}},'
               '"server_version":{{json .ServerVersion}}}')
IMAGE_FORMAT = ('{"id":{{json .Id}},"size":{{json .Size}},"tags":{{json .RepoTags}},'
                '"digests":{{json .RepoDigests}},"parent":{{json .Parent}},'
                '"rootfs":{{json .RootFS}}}')
CONTAINER_FORMAT = ('{"id":{{json .Id}},"image":{{json .Image}},'
                    '"state":{{json .State.Status}}}')
IMAGE_LIST = ('image', 'ls', '--all', '--quiet', '--no-trunc')
CONTAINER_LIST = ('container', 'ls', '--all', '--quiet', '--no-trunc')


class Refused(Exception):
    """Only fixed reason codes are allowed to leave the collector."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refused('INVALID_METADATA')
            result[key] = value
        return result

    def no_float(value):
        raise Refused('INVALID_METADATA')

    def integer(value):
        if len(value) > 20:
            raise Refused('INVALID_METADATA')
        return int(value)

    if type(raw) not in (bytes, str) or len(raw) > MAX_COMMAND_BYTES:
        raise Refused('OUTPUT_LIMIT')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=no_float,
                          parse_float=no_float, parse_int=integer)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise Refused('INVALID_METADATA') from None


def keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise Refused('INVALID_METADATA')


def number(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise Refused('INVALID_METADATA')
    return value


def identifier(value, image=False):
    if type(value) is not str or not (IMAGE_ID if image else HEX).fullmatch(value):
        raise Refused('INVALID_METADATA')
    return value


def private_text(value, maximum=512):
    # Values stay in memory for comparison and hashing; never emit them directly.
    if type(value) is not str or not 1 <= len(value) <= maximum or not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise Refused('INVALID_METADATA')
    return value


def command_allowed(command):
    if type(command) is not tuple or command[:len(DOCKER)] != DOCKER:
        return False
    args = command[len(DOCKER):]
    if args in (('info', '--format', INFO_FORMAT), IMAGE_LIST, CONTAINER_LIST):
        return True
    if args[:len(CONTAINER_LIST)] == CONTAINER_LIST and len(args) == len(CONTAINER_LIST) + 2:
        return args[-2] == '--filter' and args[-1] in {'ancestor=' + value for _, value in CANDIDATES}
    for kind, template in (('image', IMAGE_FORMAT), ('container', CONTAINER_FORMAT)):
        prefix = (kind, 'inspect', '--format', template)
        if args[:4] == prefix and 1 <= len(args[4:]) <= BATCH_SIZE:
            pattern = IMAGE_ID if kind == 'image' else HEX
            return all(type(value) is str and pattern.fullmatch(value) for value in args[4:])
    return False


class Runner:
    """Drain both pipes with one combined byte cap and a wall-clock deadline."""
    def __init__(self):
        self.deadline = time.monotonic() + TOTAL_SECONDS
        self.total_bytes = 0

    def __call__(self, command):
        if not command_allowed(command):
            raise Refused('INPUT_REFUSED')
        until = min(self.deadline, time.monotonic() + COMMAND_SECONDS)
        if until <= time.monotonic():
            raise Refused('COMMAND_TIMEOUT')
        process = None
        selector = selectors.DefaultSelector()
        output = bytearray()
        command_bytes = 0
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=ENV, cwd='/', close_fds=True)
            for pipe in (process.stdout, process.stderr):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ)
            while selector.get_map():
                left = until - time.monotonic()
                if left <= 0:
                    raise Refused('COMMAND_TIMEOUT')
                for key, _ in selector.select(min(left, 0.2)):
                    block = os.read(key.fileobj.fileno(), 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    command_bytes += len(block)
                    self.total_bytes += len(block)
                    if command_bytes > MAX_COMMAND_BYTES or self.total_bytes > MAX_TOTAL_BYTES:
                        raise Refused('OUTPUT_LIMIT')
                    if key.fileobj is process.stdout:
                        output.extend(block)
            remaining = until - time.monotonic()
            if remaining <= 0:
                raise Refused('COMMAND_TIMEOUT')
            try:
                result = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise Refused('COMMAND_TIMEOUT') from None
            if result != 0:
                raise Refused('COMMAND_FAILED')
            return bytes(output)
        except OSError:
            raise Refused('COMMAND_FAILED') from None
        finally:
            selector.close()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait()
                process.stdout.close()
                process.stderr.close()


class Session:
    def __init__(self, runner):
        self.runner = runner
        self.deadline = time.monotonic() + TOTAL_SECONDS
        self.total_bytes = 0

    def read(self, args):
        command = DOCKER + args
        if not command_allowed(command):
            raise Refused('INPUT_REFUSED')
        if time.monotonic() >= self.deadline:
            raise Refused('COMMAND_TIMEOUT')
        raw = self.runner(command)
        if time.monotonic() >= self.deadline:
            raise Refused('COMMAND_TIMEOUT')
        if type(raw) is not bytes:
            raise Refused('INVALID_METADATA')
        self.total_bytes += len(raw)
        if len(raw) > MAX_COMMAND_BYTES or self.total_bytes > MAX_TOTAL_BYTES:
            raise Refused('OUTPUT_LIMIT')
        return raw

    def ids(self, args, image=False):
        raw = self.read(args)
        try:
            lines = raw.decode('ascii').splitlines()
        except UnicodeError:
            raise Refused('INVALID_METADATA') from None
        maximum = MAX_IMAGES if image else MAX_CONTAINERS
        # Docker image ls can repeat an ID for several tags. Bound lines as well
        # as unique IDs; container IDs may never be duplicated.
        if len(lines) > maximum * (MAX_REFS if image else 1):
            raise Refused('ITEM_LIMIT')
        values = [identifier(line, image) for line in lines]
        if not image and len(values) != len(set(values)):
            raise Refused('INVALID_METADATA')
        values = sorted(set(values))
        if len(values) > maximum:
            raise Refused('ITEM_LIMIT')
        return values

    def inspect(self, ids, image=False):
        result = {}
        kind, template = ('image', IMAGE_FORMAT) if image else ('container', CONTAINER_FORMAT)
        for offset in range(0, len(ids), BATCH_SIZE):
            batch = ids[offset:offset + BATCH_SIZE]
            raw = self.read((kind, 'inspect', '--format', template) + tuple(batch))
            lines = raw.splitlines()
            if len(lines) != len(batch):
                raise Refused('IDENTITY_MISMATCH')
            for line in lines:
                value = normalize_image(strict_json(line)) if image else normalize_container(strict_json(line))
                if value['id'] not in batch or value['id'] in result:
                    raise Refused('IDENTITY_MISMATCH')
                result[value['id']] = value
        if set(result) != set(ids):
            raise Refused('IDENTITY_MISMATCH')
        return result


def normalize_info(value):
    keys(value, ('id', 'driver', 'driver_status', 'root', 'server_version'))
    for name in ('id', 'driver', 'root', 'server_version'):
        private_text(value[name])
    rows = value['driver_status']
    if type(rows) is not list or len(rows) > 64:
        raise Refused('INVALID_METADATA')
    normalized = []
    for row in rows:
        if type(row) is not list or len(row) != 2:
            raise Refused('INVALID_METADATA')
        normalized.append([private_text(cell, 2048) for cell in row])
    return dict(value, driver_status=sorted(normalized))


def normalize_refs(value):
    if value is None:
        return []
    if type(value) is not list or len(value) > MAX_REFS:
        raise Refused('ITEM_LIMIT' if type(value) is list else 'INVALID_METADATA')
    values = [private_text(item) for item in value]
    if len(values) != len(set(values)):
        raise Refused('INVALID_METADATA')
    return sorted(values)


def normalize_image(value):
    keys(value, ('id', 'size', 'tags', 'digests', 'parent', 'rootfs'))
    identifier(value['id'], True)
    number(value['size'], MAX_SIZE)
    parent = value['parent']
    if parent is not None and parent != '':
        identifier(parent, True)
        if parent == value['id']:
            raise Refused('INVALID_METADATA')
    rootfs = value['rootfs']
    keys(rootfs, ('Type', 'Layers'))
    if rootfs['Type'] != 'layers' or type(rootfs['Layers']) is not list:
        raise Refused('INVALID_METADATA')
    if len(rootfs['Layers']) > MAX_LAYERS:
        raise Refused('ITEM_LIMIT')
    layers = [identifier(layer, True) for layer in rootfs['Layers']]
    return dict(id=value['id'], size=value['size'], tags=normalize_refs(value['tags']),
                digests=normalize_refs(value['digests']), parent=parent, layers=layers)


def normalize_container(value):
    keys(value, ('id', 'image', 'state'))
    identifier(value['id'])
    identifier(value['image'], True)
    if type(value['state']) is not str or value['state'] not in STATES:
        raise Refused('INVALID_METADATA')
    return value


def snapshot(session):
    info = normalize_info(strict_json(session.read(('info', '--format', INFO_FORMAT))))
    image_ids = session.ids(IMAGE_LIST, True)
    container_ids = session.ids(CONTAINER_LIST)
    images = session.inspect(image_ids, True)
    containers = session.inspect(container_ids)
    if any(value['image'] not in images for value in containers.values()):
        raise Refused('MISSING_CONTAINER_IMAGE')
    ancestors = {}
    for _, image in CANDIDATES:
        if image not in images:
            continue
        values = session.ids(CONTAINER_LIST + ('--filter', 'ancestor=' + image))
        direct = {key for key, value in containers.items() if value['image'] == image}
        if not set(values) <= set(containers) or not direct <= set(values):
            raise Refused('REFERENCE_MISMATCH')
        ancestors[image] = values
    return dict(info=info, images=images, containers=containers, ancestors=ancestors)


def empty_report(reason='INTERNAL_ERROR', changed=False):
    return dict(schema_version=1, scope=SCOPE,
                status='CHANGED' if changed else 'INCOMPLETE', reason=reason,
                delete_authorized=False, reclaimable_bytes=None, backup_currently_verified=False,
                docker=None, candidates=[dict(name=name, image_id=image, status='UNKNOWN',
                                             image=None, references=None) for name, image in CANDIDATES])


def project(value):
    info, images, containers = value['info'], value['images'], value['containers']
    output = empty_report('OK')
    output['status'] = 'COMPLETE_STABLE'
    output['docker'] = dict(server_identity_sha256=digest([info['id'], info['root']]),
                            driver_sha256=digest([info['driver'], info['driver_status']]),
                            server_version_sha256=digest(info['server_version']),
                            inventory_fingerprint_sha256=digest(value), container_count=len(containers),
                            image_count=len(images), inventory_scope='ACTIVE_DOCKER_IMAGE_STORE_ONLY',
                            parent_relation_complete=False)
    parents_available = all(item['parent'] is not None for item in images.values())
    for candidate in output['candidates']:
        image_id = candidate['image_id']
        if image_id not in images:
            candidate['status'] = 'ABSENT_IN_ACTIVE_STORE'
            continue
        item = images[image_id]
        layers = item['layers']
        others = [v for key, v in images.items() if key != image_id]
        candidate['image'] = dict(size_bytes=item['size'], tag_count=len(item['tags']),
                                 tags_sha256=digest(item['tags']), digest_count=len(item['digests']),
                                 digests_sha256=digest(item['digests']), parent_present=None if item['parent'] is None else bool(item['parent']),
                                 layer_count=len(layers))
        observed_children = sum(v['parent'] == image_id for v in others)
        refs = dict(direct_container_count=sum(v['image'] == image_id for v in containers.values()),
                    ancestor_container_count=len(value['ancestors'][image_id]),
                    # Preserve a known positive even when another legacy Parent
                    # field is absent. A positive is an observed lower bound.
                    parent_child_image_count=observed_children if observed_children or parents_available else None,
                    layer_prefix_image_count=sum(bool(layers) and len(v['layers']) > len(layers) and v['layers'][:len(layers)] == layers for v in others),
                    equal_layers_image_count=sum(v['layers'] == layers for v in others),
                    shared_layers_image_count=sum(bool(set(layers).intersection(v['layers'])) for v in others))
        candidate['references'] = refs
        candidate['status'] = 'REFERENCES_OBSERVED' if any(refs[key] for key in (
            'direct_container_count', 'ancestor_container_count', 'parent_child_image_count',
            'layer_prefix_image_count', 'equal_layers_image_count')) else 'NO_REFERENCES_OBSERVED'
    return output


def collect_report(runner=None):
    try:
        session = Session(Runner() if runner is None else runner)
        before = snapshot(session)
        after = snapshot(session)
        result = empty_report('INVENTORY_CHANGED', True) if before != after else project(before)
        return validate_report(result)
    except Refused as error:
        reason = str(error)
        if reason not in REASONS - {'OK', 'INVENTORY_CHANGED'}:
            reason = 'INTERNAL_ERROR'
        return empty_report(reason)
    except Exception:
        return empty_report('INTERNAL_ERROR')


def validate_report(value):
    keys(value, ('schema_version', 'scope', 'status', 'reason', 'delete_authorized',
                 'reclaimable_bytes', 'backup_currently_verified', 'docker', 'candidates'))
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['scope'] != SCOPE:
        raise Refused('INVALID_METADATA')
    if value['delete_authorized'] is not False or value['reclaimable_bytes'] is not None or value['backup_currently_verified'] is not False:
        raise Refused('INVALID_METADATA')
    status, reason = value['status'], value['reason']
    if type(status) is not str or type(reason) is not str or reason not in REASONS:
        raise Refused('INVALID_METADATA')
    if (status == 'COMPLETE_STABLE' and reason != 'OK') or (status == 'CHANGED' and reason != 'INVENTORY_CHANGED') or (status == 'INCOMPLETE' and reason in ('OK', 'INVENTORY_CHANGED')) or status not in ('COMPLETE_STABLE', 'INCOMPLETE', 'CHANGED'):
        raise Refused('INVALID_METADATA')
    complete = status == 'COMPLETE_STABLE'
    docker = value['docker']
    if complete:
        keys(docker, ('server_identity_sha256', 'driver_sha256', 'server_version_sha256',
                      'inventory_fingerprint_sha256', 'container_count', 'image_count',
                      'inventory_scope', 'parent_relation_complete'))
        for key in ('server_identity_sha256', 'driver_sha256', 'server_version_sha256', 'inventory_fingerprint_sha256'):
            identifier(docker[key])
        number(docker['container_count'], MAX_CONTAINERS)
        number(docker['image_count'], MAX_IMAGES)
        if docker['inventory_scope'] != 'ACTIVE_DOCKER_IMAGE_STORE_ONLY' or docker['parent_relation_complete'] is not False:
            raise Refused('INVALID_METADATA')
    elif docker is not None:
        raise Refused('INVALID_METADATA')
    candidates = value['candidates']
    if type(candidates) is not list or len(candidates) != len(CANDIDATES):
        raise Refused('INVALID_METADATA')
    present = 0
    direct_total = 0
    for candidate, (name, image_id) in zip(candidates, CANDIDATES):
        keys(candidate, ('name', 'image_id', 'status', 'image', 'references'))
        if candidate['name'] != name or candidate['image_id'] != image_id:
            raise Refused('INVALID_METADATA')
        state = candidate['status']
        if not complete:
            if state != 'UNKNOWN' or candidate['image'] is not None or candidate['references'] is not None:
                raise Refused('INVALID_METADATA')
            continue
        if state == 'ABSENT_IN_ACTIVE_STORE':
            if candidate['image'] is not None or candidate['references'] is not None:
                raise Refused('INVALID_METADATA')
            continue
        if state not in ('REFERENCES_OBSERVED', 'NO_REFERENCES_OBSERVED'):
            raise Refused('INVALID_METADATA')
        present += 1
        item, refs = candidate['image'], candidate['references']
        keys(item, ('size_bytes', 'tag_count', 'tags_sha256', 'digest_count', 'digests_sha256', 'parent_present', 'layer_count'))
        number(item['size_bytes'], MAX_SIZE)
        number(item['tag_count'], MAX_REFS)
        number(item['digest_count'], MAX_REFS)
        number(item['layer_count'], MAX_LAYERS)
        identifier(item['tags_sha256'])
        identifier(item['digests_sha256'])
        if item['parent_present'] is not None and type(item['parent_present']) is not bool:
            raise Refused('INVALID_METADATA')
        for count, fingerprint in (('tag_count', 'tags_sha256'), ('digest_count', 'digests_sha256')):
            if item[count] == 0 and item[fingerprint] != digest([]):
                raise Refused('INVALID_METADATA')
        keys(refs, ('direct_container_count', 'ancestor_container_count', 'parent_child_image_count',
                    'layer_prefix_image_count', 'equal_layers_image_count', 'shared_layers_image_count'))
        for key in ('direct_container_count', 'ancestor_container_count'):
            number(refs[key], docker['container_count'])
        if refs['direct_container_count'] > refs['ancestor_container_count']:
            raise Refused('INVALID_METADATA')
        direct_total += refs['direct_container_count']
        for key in ('parent_child_image_count', 'layer_prefix_image_count', 'equal_layers_image_count', 'shared_layers_image_count'):
            if key == 'parent_child_image_count' and refs[key] is None:
                continue
            number(refs[key], max(0, docker['image_count'] - 1))
        if item['layer_count']:
            if refs['layer_prefix_image_count'] + refs['equal_layers_image_count'] > refs['shared_layers_image_count']:
                raise Refused('INVALID_METADATA')
        elif refs['layer_prefix_image_count'] or refs['shared_layers_image_count']:
            raise Refused('INVALID_METADATA')
        observed = any(refs[key] for key in ('direct_container_count', 'ancestor_container_count',
                       'parent_child_image_count', 'layer_prefix_image_count', 'equal_layers_image_count'))
        if (state == 'REFERENCES_OBSERVED') != bool(observed):
            raise Refused('INVALID_METADATA')
    if complete and present > docker['image_count']:
        raise Refused('INVALID_METADATA')
    if complete and direct_total > docker['container_count']:
        raise Refused('INVALID_METADATA')
    if len(canonical(value).encode('utf-8')) + 1 > MAX_REPORT_BYTES:
        raise Refused('OUTPUT_LIMIT')
    return value


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args:
        result = empty_report('INPUT_REFUSED')
    elif sys.platform != 'linux':
        result = empty_report('UNSUPPORTED_PLATFORM')
    elif os.geteuid() != 0:
        result = empty_report('NOT_ROOT')
    else:
        result = collect_report()
    try:
        validate_report(result)
    except Exception:
        result = empty_report()
    print(canonical(result))
    return 0 if result['status'] == 'COMPLETE_STABLE' else 2


if __name__ == '__main__':
    sys.exit(main())
