#!/usr/bin/env python3
"""Retrieve the same complete ciphertext once; preserve the previous partial."""
import argparse
import contextlib
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
import types

OPERATOR_SHA256 = 'b835456557f63cadad3625f4149c9c0379cdf4b63f60f1177ab1d958137eaf30'
LEGACY_OPERATOR_SHA256 = 'dba48d67355f076befd18379aa788858ec4777398dcc08bdfcc2b56b7484b2e8'
TRANSPORT_SHA256 = '6a9dae8548d66a2d903dcfe76abd328853cb820fd9c092cdf0a703e3e964aafe'
LEASE_ID = 'naver-archives-refetch-20261107-v1'
OUTPUT_NAME = 'archives-refetch-20261107-v1.gpg'
PRESERVED_NAME = 'archives.gpg.partial'
CLIENT_TIMEOUT = 16200
HEX = re.compile(r'[0-9a-f]{64}\Z')
ERRORS = frozenset(('asset_refused', 'input_refused', 'receipt_refused', 'lease_refused',
    'start_window_expired', 'preserved_partial_changed', 'output_exists',
    'deadline_exceeded', 'fetch_failed', 'interrupted', 'operation_failed'))


class Refused(Exception):
    pass


def need(value, code):
    if not value:
        raise Refused(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bootstrap_read(path, expected):
    """Read the first pinned local helper without following any path symlink."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    with contextlib.ExitStack() as stack:
        fd = os.open('/', flags)
        stack.callback(os.close, fd)
        chain = []
        for name in path.parts[1:-1]:
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            need(stat.S_ISDIR(before.st_mode) and before.st_uid in (0, os.getuid())
                 and not before.st_mode & 0o022, 'asset_refused')
            child = os.open(name, flags, dir_fd=fd)
            stack.callback(os.close, child)
            identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid)
            need(identity(before) == identity(os.fstat(child)), 'asset_refused')
            chain.append((fd, name, child, identity(before)))
            fd = child
        before = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        need(stat.S_ISREG(before.st_mode) and before.st_uid in (0, os.getuid())
             and not before.st_mode & 0o022 and before.st_nlink == 1
             and 0 < before.st_size <= 262144, 'asset_refused')
        source = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        stack.callback(os.close, source)
        stamp = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid,
                           s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        need(stamp(os.fstat(source)) == stamp(before), 'asset_refused')
        raw = bytearray()
        while len(raw) <= 262144:
            part = os.read(source, 65536)
            if not part:
                break
            raw.extend(part)
        need(stamp(before) == stamp(os.fstat(source))
             == stamp(os.stat(path.name, dir_fd=fd, follow_symlinks=False)), 'asset_refused')
        for parent, name, child, expected_dir in chain:
            need(identity(os.fstat(child)) == expected_dir
                 == identity(os.stat(name, dir_fd=parent, follow_symlinks=False)), 'asset_refused')
        need(digest(raw) == expected, 'asset_refused')
        return bytes(raw)


def module(raw, path, name):
    value = types.ModuleType(name)
    value.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), value.__dict__)
    return value


def dependencies(directory=None):
    directory = Path(directory or Path(__file__).absolute().parent)
    old_path = directory / 'naver_archive_receiver_operator.py'
    old = module(bootstrap_read(old_path, LEGACY_OPERATOR_SHA256), old_path, 'refetch_legacy_operator')
    files = old.LocalFiles()
    op_path = directory / 'naver_archive_refetch_operator.py'
    raw = files.read(op_path, 262144)
    need(digest(raw) == OPERATOR_SHA256, 'asset_refused')
    op = module(raw, op_path, 'refetch_operator')
    bundle = op.load_bundle(directory=directory, files=files)
    transport_path = directory / 'naver_archive_transport.py'
    raw = files.read(transport_path, 131072)
    need(digest(raw) == TRANSPORT_SHA256, 'asset_refused')
    transport = module(raw, transport_path, 'refetch_transport')
    return op, bundle, transport, files, directory


def timestamp(value):
    try:
        return datetime.datetime.strptime(value, '%Y%m%d%H%M%SZ').replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except (ValueError, TypeError):
        raise Refused('lease_refused') from None


def remaining(end, monotonic):
    value = end - monotonic()
    need(value > 0, 'deadline_exceeded')
    return value


def check_window(config, now):
    need(timestamp(config['issued_at']) <= now <= timestamp(config['start_before']),
         'start_window_expired')
    need(now + CLIENT_TIMEOUT < timestamp(config['expires_at']), 'lease_refused')


def hash_fd(fd, expected_size, end, monotonic):
    os.lseek(fd, 0, os.SEEK_SET)
    hashed, count = hashlib.sha256(), 0
    while True:
        remaining(end, monotonic)
        block = os.read(fd, min(1024 * 1024, expected_size + 1 - count))
        if not block:
            break
        hashed.update(block)
        count += len(block)
        need(count <= expected_size, 'preserved_partial_changed')
    need(count == expected_size, 'preserved_partial_changed')
    return hashed.hexdigest()


def run(args, *, loaded=None, stream=None, now=time.time, monotonic=time.monotonic):
    end = monotonic() + CLIENT_TIMEOUT
    op, bundle, transport, files, directory = loaded or dependencies()
    server = bundle['receiver']
    need(server['LEASE_ID'] == LEASE_ID and server['CLIENT_TIMEOUT'] == CLIENT_TIMEOUT, 'asset_refused')
    plan, sent = op.read_transfer_inputs(args.plan, args.plan_sha256, args.sent_receipt,
                                        args.receipt_sha256, files=files, directory=directory)
    need(type(args.install_sha256) is str and HEX.fullmatch(args.install_sha256), 'receipt_refused')
    raw = files.read(Path(args.installed), 16384, private=True)
    need(digest(raw) == args.install_sha256, 'receipt_refused')
    installed = bundle['legacy_operator'].strict_json(raw)
    server['validate_result'](installed)
    need(installed['status'] == 'installed' and installed['primary_unchanged'] is True
         and installed['secondary_published'] is True, 'lease_refused')
    config = installed['config']
    need(config['bindings']['plan_sha256'] == args.plan_sha256
         and config['bindings']['sent_sha256'] == args.receipt_sha256
         and config['cipher']['bytes'] == sent['bytes']
         and config['cipher']['sha256'] == sent['sha256'], 'receipt_refused')
    check_window(config, now())
    public = files.read(Path(args.fetch_public_key), 1024).decode('ascii').strip().split()
    need(len(public) in (2, 3), 'input_refused')
    public = ' '.join(public[:2])
    bundle['legacy_controller']['public_key'](public)
    need(digest(public.encode('ascii')) == config['fetch_key_sha256'], 'receipt_refused')
    key_identity = files.read(Path(args.transport_key), 32768, private=True, metadata_only=True)
    preserved, output, result_path = map(Path, (args.preserved_partial, args.output, args.output_receipt))
    need(preserved.name == PRESERVED_NAME and output.name == OUTPUT_NAME
         and preserved.parent == output.parent == result_path.parent
         and len({preserved.name, output.name, output.name + '.partial', result_path.name}) == 4,
         'input_refused')
    need(HEX.fullmatch(args.preserved_sha256) is not None, 'input_refused')
    # LocalFiles forbids symlink ancestors and requires the actual user's 0700 folder.
    with files.parent(output) as (parent, name):
        info = os.fstat(parent)
        need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, 'input_refused')
        for candidate in (name, name + '.partial'):
            try:
                os.stat(candidate, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise Refused('output_exists')
    local = transport.Files()
    result = dict(status='failed', error='operation_failed', lease_id=LEASE_ID,
                  session=sent['session'], install_sha256=args.install_sha256,
                  plan_sha256=args.plan_sha256, sent_sha256=args.receipt_sha256,
                  preserved_sha256=args.preserved_sha256, preserved_unchanged=False,
                  bytes=None, sha256=None)
    with files.output(result_path) as save:
        try:
            with local.opened(str(preserved), 0o600) as preserved_fd:
                before = os.fstat(preserved_fd)
                need(0 < before.st_size < sent['bytes'], 'input_refused')
                baseline = transport.identity(before)
                need(hash_fd(preserved_fd, before.st_size, end, monotonic) == args.preserved_sha256,
                     'preserved_partial_changed')
                try:
                    check_window(config, now())
                    ssh = bundle['legacy_operator'].ssh_command(
                        Path(args.transport_key), bundle['known_hosts'], b'pass')
                    ssh[-1] = server['FETCH_COMMAND']
                    answer = (stream or transport.stream_fetch)(
                        ssh, sent, str(output), local, timeout=remaining(end, monotonic))
                    need(answer == dict(status='fetched_unverified', session=sent['session'],
                                        plan_sha256=args.plan_sha256, bytes=sent['bytes'],
                                        sha256=sent['sha256']), 'fetch_failed')
                    result.update(status='fetched_unverified', error=None,
                                  bytes=answer['bytes'], sha256=answer['sha256'])
                except BaseException as error:
                    code = getattr(error, 'code', str(error))
                    result.update(status='failed', error=code if code in ERRORS else 'fetch_failed')
                need(transport.identity(os.fstat(preserved_fd)) == baseline
                     == transport.identity(os.stat(preserved, follow_symlinks=False)),
                     'preserved_partial_changed')
                need(hash_fd(preserved_fd, before.st_size, end, monotonic) == args.preserved_sha256,
                     'preserved_partial_changed')
                need(transport.identity(os.fstat(preserved_fd)) == baseline
                     == transport.identity(os.stat(preserved, follow_symlinks=False)),
                     'preserved_partial_changed')
            # Context-manager path rechecks must finish before a success receipt.
            need(files.read(Path(args.transport_key), 32768, private=True,
                            metadata_only=True) == key_identity, 'input_refused')
            result['preserved_unchanged'] = True
        except BaseException as error:
            code = getattr(error, 'code', str(error))
            result.update(status='failed', error=code if code in ERRORS else 'operation_failed')
        result['result_sha256'] = save(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'plan-sha256', 'sent-receipt', 'receipt-sha256', 'installed',
                 'install-sha256', 'fetch-public-key', 'transport-key', 'preserved-partial',
                 'preserved-sha256', 'output', 'output-receipt'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    def stopped(*_):
        raise Refused('interrupted')
    def expired(*_):
        raise Refused('deadline_exceeded')
    previous = {number: signal.signal(number, stopped)
                for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    previous[signal.SIGALRM] = signal.signal(signal.SIGALRM, expired)
    os.umask(0o077)
    signal.alarm(math.ceil(CLIENT_TIMEOUT))
    try:
        result = run(args)
    except BaseException as error:
        code = getattr(error, 'code', str(error))
        result = dict(status='failed', error=code if code in ERRORS else 'operation_failed',
                      lease_id=LEASE_ID, retry_authorized=False)
    finally:
        signal.alarm(0)
        for number, handler in previous.items():
            signal.signal(number, handler)
    print(json.dumps(result, sort_keys=True, separators=(',', ':')), flush=True)
    return 0 if result['status'] == 'fetched_unverified' else 2


if __name__ == '__main__':
    sys.exit(main())
