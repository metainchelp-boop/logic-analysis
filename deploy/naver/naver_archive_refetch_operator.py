"""Pinned Mac operator for a separate, fixed historical-cipher refetch lease.

Only public code and evidence JSON are read. SSH alone opens the administrator
key; this module checks that key's metadata before and after the operation.
"""
import argparse
import ast
import base64
import contextlib
import hashlib
import os
from pathlib import Path
import stat
import sys
import types

LEGACY_OPERATOR_SHA256 = 'dba48d67355f076befd18379aa788858ec4777398dcc08bdfcc2b56b7484b2e8'
LEGACY_CONTROLLER_SHA256 = 'f058ae0585643b461fcaf5cdba7c43a48cebbfff9b43e15f7726231a0c92bebc'
RECEIVER_SHA256 = '67fc72b96b0224f4525545ec51a4faa4ebdc86925a185c2eae371da1e5c0ffe1'
KNOWN_HOSTS_SHA256 = '263a7fd1c7fe50257fec9223c4cb2015d4e4ff575c0f8c7d362225c589204675'
TRANSFER_PINS = {
    'naver_archive_common.py': '127000d66a91804fc2cd39665df5b2324e255e4a47554e404c20d9284885f55d',
    'naver_archive_transport.py': '6a9dae8548d66a2d903dcfe76abd328853cb820fd9c092cdf0a703e3e964aafe',
    'cold_backup_archive.py': 'd6f696eeb724c8f592c137a1d26e8fd69c6f0c22f2ea6efb95f4a0bf16f04550',
    'backup_bundle.py': '978b83c27b01f77caaa8d499a08bbc1b510841795b73c7ff09c34c37961ce1b5',
}
MAX_EVIDENCE = 256 * 1024
MAX_RECEIPT = 16384
INSTALL_EXCHANGE_SECONDS = 600
REVOKE_EXCHANGE_SECONDS = 90
PUBLIC_LIMIT = 131072
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
ERRORS = frozenset(('bundle_refused', 'path_refused', 'path_changed', 'input_refused',
    'evidence_refused', 'receipt_refused', 'output_exists', 'remote_unknown',
    'deadline_exceeded', 'output_limit', 'operation_failed', 'file_refused'))


class Refused(Exception):
    pass


def need(condition, code='input_refused'):
    if not condition:
        raise Refused(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _bootstrap_read(path, expected, limit=PUBLIC_LIMIT):
    """Load the first trusted module without relying on any unverified module."""
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts and path.name not in ('', '.', '..'), 'path_refused')
    with contextlib.ExitStack() as stack:
        parent = os.open('/', FLAGS)
        stack.callback(os.close, parent)
        chain = []
        for name in path.parts[1:-1]:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            need(stat.S_ISDIR(before.st_mode) and before.st_uid in (0, os.getuid())
                 and not before.st_mode & 0o022, 'path_refused')
            child = os.open(name, FLAGS, dir_fd=parent)
            stack.callback(os.close, child)
            same = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid)
            need(same(before) == same(os.fstat(child)), 'path_changed')
            chain.append((parent, name, child, same(before)))
            parent = child
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        need(stat.S_ISREG(before.st_mode) and before.st_uid in (0, os.getuid())
             and not before.st_mode & 0o022 and before.st_nlink == 1
             and 0 < before.st_size <= limit, 'bundle_refused')
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        stack.callback(os.close, fd)
        need(_identity(before) == _identity(os.fstat(fd)), 'path_changed')
        raw = bytearray()
        while True:
            data = os.read(fd, min(8192, limit + 1 - len(raw)))
            if not data:
                break
            raw.extend(data)
            need(len(raw) <= limit, 'bundle_refused')
        need(_identity(before) == _identity(os.fstat(fd)) ==
             _identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)), 'path_changed')
        for folder, name, opened, original in chain:
            need(same(os.stat(name, dir_fd=folder, follow_symlinks=False)) == original == same(os.fstat(opened)),
                 'path_changed')
        need(digest(raw) == expected, 'bundle_refused')
        return bytes(raw)


def _module(raw, name, path):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def _legacy(directory):
    raw = _bootstrap_read(directory / 'naver_archive_receiver_operator.py', LEGACY_OPERATOR_SHA256)
    return _module(raw, '_pinned_refetch_legacy_operator', directory / 'naver_archive_receiver_operator.py')


def load_bundle(directory=None, files=None):
    """Return pinned public modules for the operator and the separate Mac client.

    `legacy_operator` is a module. `legacy_controller` and `receiver` are namespace
    dictionaries. No private evidence, network, controller entrypoint or key is
    accessed by this function.
    """
    directory = Path(directory) if directory is not None else Path(__file__).absolute().parent
    legacy = _legacy(directory)
    files = files or legacy.LocalFiles()
    control = files.read(directory / 'naver_archive_receiver_control.py', PUBLIC_LIMIT)
    server = files.read(directory / 'naver_archive_refetch_receiver.py', PUBLIC_LIMIT)
    known = directory / 'preservation/server-b-known-hosts'
    need(digest(control) == LEGACY_CONTROLLER_SHA256 and digest(server) == RECEIVER_SHA256
         and digest(files.read(known, 1024)) == KNOWN_HOSTS_SHA256, 'bundle_refused')
    need(legacy.CONTROLLER_SHA256 == LEGACY_CONTROLLER_SHA256
         and legacy.KNOWN_HOSTS_SHA256 == KNOWN_HOSTS_SHA256, 'bundle_refused')
    ns = {'__name__': '_pinned_refetch_legacy_controller'}
    exec(compile(control, '<pinned-public-legacy-controller>', 'exec'), ns)
    receiver = {'__name__': '_pinned_refetch_receiver', 'L': ns,
                'LEGACY_SOURCE': control, 'MODULE_SOURCE': server}
    exec(compile(server, '<pinned-public-refetch-receiver>', 'exec'), receiver)
    for name in ('validate_request', 'validate_result', 'validate_config', 'main_control'):
        need(callable(receiver.get(name)), 'bundle_refused')
    return dict(legacy_operator=legacy, legacy_controller=ns, receiver=receiver,
                legacy_raw=control, receiver_raw=server, known_hosts=known)


def _module_with_loader(raw, name, path, loader_name, loader):
    """Replace only the pinned source's dependency loader, never load .pyc files.

    The rest of the exact-hash source AST is unchanged. Both removed loader names
    are fixed by this module; no caller-provided code or path enters the AST.
    """
    tree = ast.parse(raw, filename=str(path))
    found = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == loader_name]
    need(len(found) == 1 and isinstance(found[0], ast.FunctionDef), 'bundle_refused')
    tree.body.remove(found[0])
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__dict__[loader_name] = loader
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    return module


def _transfer_modules(directory, files):
    raw = {name: files.read(directory / name, PUBLIC_LIMIT) for name in TRANSFER_PINS}
    need(all(digest(raw[name]) == expected for name, expected in TRANSFER_PINS.items()), 'bundle_refused')
    # Compile every dependency from the already-verified bytes. Python -B stops
    # cache writes, not cache reads; the original path-based loaders must never
    # execute here, even when a timestamp-valid but different .pyc exists.
    cold = _module(raw['cold_backup_archive.py'], '_pinned_refetch_cold', directory / 'cold_backup_archive.py')
    cache = {'cold_backup_archive': cold}
    def sibling(name):
        need(name in ('cold_backup_archive', 'backup_bundle'), 'bundle_refused')
        if name not in cache:
            cache[name] = _module_with_loader(raw['backup_bundle.py'], '_pinned_refetch_backup_bundle',
                directory / 'backup_bundle.py', 'load_cold', lambda: cold)
        return cache[name]
    common = _module_with_loader(raw['naver_archive_common.py'], '_pinned_refetch_common',
        directory / 'naver_archive_common.py', 'sibling', sibling)
    transport = _module(raw['naver_archive_transport.py'], '_pinned_refetch_transport', directory / 'naver_archive_transport.py')
    return common, transport


def _evidence(path, sha, files, validator, limit):
    need(type(sha) is str and len(sha) == 64 and all(x in '0123456789abcdef' for x in sha), 'evidence_refused')
    raw = files.read(path, limit, private=True)
    need(digest(raw) == sha, 'evidence_refused')
    try:
        value = validator['strict_json'](raw)
        need(validator['canonical'](value) == raw, 'evidence_refused')
    except Exception:
        raise Refused('evidence_refused') from None
    return raw, value


def read_transfer_inputs(plan_path, plan_sha, sent_path, sent_sha, files=None, directory=None):
    directory = Path(directory) if directory is not None else Path(__file__).absolute().parent
    if files is None:
        files = _legacy(directory).LocalFiles()
    common, transport = _transfer_modules(directory, files)
    validators = {'strict_json': common.strict_json, 'canonical': common.canonical}
    _, plan = _evidence(plan_path, plan_sha, files, validators, MAX_EVIDENCE)
    _, sent = _evidence(sent_path, sent_sha, files, validators, MAX_RECEIPT)
    try:
        common.validate_plan(plan)
        transport.validate_sent(sent)
    except Exception:
        raise Refused('evidence_refused') from None
    need(sent['plan_sha256'] == plan_sha, 'evidence_refused')
    return plan, sent


def _install_request(args, bundle, files, directory):
    ns = bundle['legacy_controller']
    _, sent = read_transfer_inputs(args.plan, args.plan_sha256, args.sent, args.sent_sha256,
                                  files=files, directory=directory)
    proofs = {}
    for name, path, sha, limit in (
            ('plan', args.plan, args.plan_sha256, MAX_EVIDENCE),
            ('sent', args.sent, args.sent_sha256, MAX_RECEIPT),
            ('install', args.old_install, args.old_install_sha256, MAX_RECEIPT),
            ('revoke', args.old_revoke, args.old_revoke_sha256, MAX_RECEIPT)):
        raw, value = _evidence(path, sha, files, ns, limit)
        proofs[name] = (raw, value, sha)
    installed, revoked = proofs['install'][1], proofs['revoke'][1]
    try:
        ns['validate_result'](installed)
        ns['validate_result'](revoked)
        need(installed['action'] == 'install' and installed['status'] == 'installed'
             and installed['primary_unchanged'] is True and installed['secondary_published'], 'evidence_refused')
        need(revoked['action'] == 'revoke' and revoked['status'] in ('revoked', 'already_absent')
             and revoked['primary_unchanged'] is True, 'evidence_refused')
        need(revoked == dict(installed, action='revoke', status=revoked['status']), 'evidence_refused')
        parts = files.read(args.fetch_public_key, 1024).decode('ascii').strip().split()
        need(len(parts) in (2, 3), 'input_refused')
        key = ns['public_key'](' '.join(parts[:2]))
        ns['ipv4'](args.fetch_ip)
        need(digest(key.encode('ascii')) == installed['fetch_key_sha256'], 'evidence_refused')
    except Refused:
        raise
    except Exception:
        raise Refused('evidence_refused') from None
    request = dict(action='install', fetch_public_key=key, fetch_ip=args.fetch_ip,
                   cipher_bytes=sent['bytes'], cipher_sha256=sent['sha256'])
    for name, (raw, _, sha) in proofs.items():
        request[name + '_b64'] = base64.b64encode(raw).decode('ascii')
        request[name + '_sha256'] = sha
    return request


def bootstrap(bundle):
    """Only two pinned public Python programs are executable on the remote side."""
    return ("import sys\nLEGACY_SOURCE=" + repr(bundle['legacy_raw']) +
            "\nMODULE_SOURCE=" + repr(bundle['receiver_raw']) +
            "\nL={'__name__':'pinned_refetch_legacy'}\n" +
            "exec(compile(LEGACY_SOURCE,'<pinned-public-legacy>','exec'),L)\n" +
            "R={'__name__':'pinned_refetch_control','L':L,'LEGACY_SOURCE':LEGACY_SOURCE,'MODULE_SOURCE':MODULE_SOURCE}\n" +
            "exec(compile(MODULE_SOURCE,'<pinned-public-refetch>','exec'),R)\n" +
            "sys.exit(R['main_control']())\n").encode('utf-8')


def run(args, files=None, remote=None, directory=None):
    directory = Path(directory) if directory is not None else Path(__file__).absolute().parent
    bundle = load_bundle(directory, files)
    legacy, receiver = bundle['legacy_operator'], bundle['receiver']
    files = files or legacy.LocalFiles()
    remote = remote or legacy.exchange
    admin_identity = files.read(args.admin_key, 32768, private=True, metadata_only=True)
    if args.action == 'install':
        request = _install_request(args, bundle, files, directory)
    elif args.action == 'revoke':
        _, installed = _evidence(args.installed, args.receipt_sha256, files,
                                 bundle['legacy_controller'], MAX_RECEIPT)
        receiver['validate_result'](installed)
        request = dict(action='revoke', installed=installed)
    else:
        raise Refused('input_refused')
    receiver['validate_request'](request)
    with files.output(args.output) as save:
        timeout = INSTALL_EXCHANGE_SECONDS if args.action == 'install' else REVOKE_EXCHANGE_SECONDS
        rc, result = remote(legacy.ssh_command(args.admin_key, bundle['known_hosts'], bootstrap(bundle)),
                            request, timeout=timeout)
        receiver['validate_result'](result)
        need(result['action'] == args.action, 'receipt_refused')
        need((rc == 0) == (result['status'] in ('installed', 'revoked', 'already_absent')), 'receipt_refused')
        # The new server's validator binds its result's config and every posted
        # metadata/hash. Additional request/result binding is checked below.
        bind_result(result, request, receiver)
        receipt_sha = save(result)
        need(files.read(args.admin_key, 32768, private=True, metadata_only=True) == admin_identity, 'path_changed')
    return dict(status=result['status'], error=result['error'], receipt_sha256=receipt_sha,
                primary_unchanged=result['primary_unchanged'])


def bind_result(result, request, receiver):
    """Bind a valid server report to this exact request, including partial writes."""
    config = result['config']
    if request['action'] == 'install':
        if config is not None:
            receiver['validate_config'](config)
            need(config['bindings'] == {name + '_sha256': request[name + '_sha256']
                 for name in ('plan', 'sent', 'install', 'revoke')}, 'receipt_refused')
            need(config['cipher']['bytes'] == request['cipher_bytes']
                 and config['cipher']['sha256'] == request['cipher_sha256']
                 and config['fetch_ip'] == request['fetch_ip']
                 and config['fetch_key_sha256'] == digest(request['fetch_public_key'].encode('ascii'))
                 and config['module_sha256'] == RECEIVER_SHA256
                 and config['legacy_sha256'] == LEGACY_CONTROLLER_SHA256, 'receipt_refused')
        else:
            need(result['status'] == 'failed' and not result['secondary_published'], 'receipt_refused')
        import json
        old = json.loads(base64.b64decode(request['install_b64'], validate=True))
        if result['primary_unchanged'] is True:
            need(result['primary'] == old['primary'], 'receipt_refused')
    else:
        installed = request['installed']
        if result['config'] is not None:
            for name in ('config', 'config_sha256', 'secondary', 'secondary_published', 'pending',
                         'tool_directory', 'receiver', 'legacy', 'config_file'):
                need(result[name] == installed[name], 'receipt_refused')
        if result['primary_unchanged'] is True:
            need(result['primary'] == installed['primary'], 'receipt_refused')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused('input_refused')


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        commands = parser.add_subparsers(dest='action', required=True)
        for action in ('install', 'revoke'):
            command = commands.add_parser(action)
            command.add_argument('--admin-key', type=Path, required=True)
            command.add_argument('--output', type=Path, required=True)
            if action == 'install':
                for name in ('plan', 'sent', 'old-install', 'old-revoke'):
                    command.add_argument('--' + name, type=Path, required=True)
                    command.add_argument('--' + name + '-sha256', required=True)
                command.add_argument('--fetch-public-key', type=Path, required=True)
                command.add_argument('--fetch-ip', required=True)
            else:
                command.add_argument('--installed', type=Path, required=True)
                command.add_argument('--receipt-sha256', required=True)
        result = run(parser.parse_args(argv))
    except Exception as error:
        code = str(error) if str(error) in ERRORS else 'operation_failed'
        result = dict(status='HOLD', error=code, retry_authorized=False)
    import json
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['status'] in ('installed', 'revoked', 'already_absent') else 2


if __name__ == '__main__':
    raise SystemExit(main())
