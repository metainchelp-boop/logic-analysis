#!/usr/bin/env python3
"""Download one exact public run log into a private folder and decrypt its frame.

Usage (operator-owned one-use key/certificate must already exist):
  python3 -I -B inspection_aggregate_local.py --run-id RUN --nonce HEX64 \
    --certificate /private/recipient.pem --key /private/recipient.key \
    --directory /private/new-receipt

The public log contains ciphertext. No artifact/relay is used. The key never
leaves this machine. Plaintext is written O_EXCL/0600, never printed. This tool
does not generate a key, dispatch a workflow, contact the host, or modify data.
"""
import argparse
import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import stat
import shutil
import sys

_spec = importlib.util.spec_from_file_location('inspection_aggregate',
    Path(__file__).with_name('inspection_aggregate.py'))
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)
REPO = 'metainchelp-boop/logic-analysis'
WORKFLOW = '.github/workflows/naver-inspection-aggregate.yml'
HELPER = 'deploy/naver/inspection_aggregate.py'
MAX_LOG = 2*1024*1024


def private_read(path, limit, *, secret=False):
    path = Path(path).absolute()
    A.require(path.resolve() == path, 'arguments_refused')
    info = path.lstat()
    A.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1
        and (not secret or not info.st_mode & 0o077), 'arguments_refused')
    if secret:
        parent = path.parent.lstat()
        A.require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.geteuid()
                  and not parent.st_mode & 0o077 and info.st_size <= limit, 'arguments_refused')
        return b''  # Only OpenSSL reads the private-key bytes.
    return A.safe_file(path, limit, owner=os.geteuid())


def create_private(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb', closefd=False) as out:
            out.write(raw)
            out.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def validate_run(value, run_id):
    A.require(type(value) is dict and str(value.get('id')) == run_id)
    A.require(value.get('run_attempt') == 1 and value.get('event') == 'workflow_dispatch'
        and value.get('head_branch') == 'main' and value.get('status') == 'completed'
        and value.get('conclusion') == 'success' and value.get('path') == WORKFLOW)
    A.require(value.get('repository', {}).get('full_name') == REPO)
    for key in ('actor', 'triggering_actor'):
        A.require(value.get(key, {}).get('login') == 'metainchelp-boop')
    A.require(type(value.get('head_sha')) is str and re.fullmatch(r'[0-9a-f]{40}', value['head_sha']))
    return value['head_sha']


def extract_frame(raw):
    A.require(type(raw) is bytes and 0 < len(raw) <= MAX_LOG)
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        raise A.Refused('output_refused') from None
    matches = []
    for line in text.splitlines():
        A.require(len(line) <= 65536)
        match = re.fullmatch(r'(?:[^\r\n]*[ \t])?' + re.escape(A.FRAME_PREFIX)
                            + r'([A-Za-z0-9+/=]{1,43692})', line)
        if match:
            matches.append(match[1])
    A.require(len(matches) == 1)
    try:
        raw = base64.b64decode(matches[0], validate=True)
    except ValueError:
        raise A.Refused('output_refused') from None
    A.require(0 < len(raw) <= A.CIPHER_BYTES and base64.b64encode(raw).decode() == matches[0])
    return raw


def local_command(argv, **kwargs):
    if argv[0] == 'gh':
        executable = shutil.which('gh')
        A.require(executable is not None, 'runtime_refused')
        argv = [executable, *argv[1:]]
    elif argv[0] == '/usr/bin/openssl' and Path('/opt/homebrew/opt/openssl@3/bin/openssl').is_file():
        # macOS system LibreSSL may not implement CMS AuthEnvelopedData/GCM.
        argv = ['/opt/homebrew/opt/openssl@3/bin/openssl', *argv[1:]]
    return A.command(argv, env=None, **kwargs)


def receive(run_id, nonce, certificate, key, directory, runner=local_command):
    A.require(re.fullmatch(r'[1-9][0-9]{0,19}', run_id) and re.fullmatch(r'[0-9a-f]{64}', nonce), 'arguments_refused')
    cert = private_read(certificate, 8192)
    private_read(key, 8192, secret=True)
    directory = Path(directory).absolute()
    A.require(directory.parent.resolve() == directory.parent, 'arguments_refused')
    parent = directory.parent.lstat()
    A.require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.geteuid()
              and not parent.st_mode & 0o077, 'arguments_refused')
    directory.mkdir(mode=0o700)
    # gh inherits only its ordinary local authentication. No secret value is read,
    # printed, added to argv, or sent to a server by this helper.
    gh = ['gh', 'api', 'repos/' + REPO]
    metadata_raw = runner([*gh[:-1], gh[-1] + '/actions/runs/' + run_id], limit=65536, timeout=20)
    metadata = A.decode(metadata_raw)
    head = validate_run(metadata, run_id)
    source_reply = A.decode(runner([*gh[:-1], gh[-1] + '/contents/' + HELPER + '?ref=' + head], limit=131072, timeout=20))
    A.require(type(source_reply) is dict and source_reply.get('encoding') == 'base64'
        and source_reply.get('path') == HELPER and type(source_reply.get('content')) is str)
    helper = base64.b64decode(source_reply['content'].replace('\n', ''), validate=True)
    A.require(0 < len(helper) <= 131072)
    expected = {'run_id': run_id, 'run_attempt': 1, 'source': A.SOURCE, 'workflow_sha': head,
        'helper_sha256': hashlib.sha256(helper).hexdigest(), 'recipient_sha256': hashlib.sha256(cert).hexdigest(), 'nonce': nonce}
    # The completed run is fetched exactly once. Only the encrypted frame is
    # interpreted; the entire bounded log is kept privately for reproducibility.
    log = runner(['gh', 'run', 'view', run_id, '--repo', REPO, '--log'], limit=MAX_LOG, timeout=30)
    create_private(directory / 'run.log', log)
    cipher = extract_frame(log)
    create_private(directory / 'sealed.cms', cipher)
    plain = runner(['/usr/bin/openssl', 'cms', '-decrypt', '-binary', '-inform', 'DER',
        '-recip', str(Path(certificate).absolute()), '-inkey', str(Path(key).absolute())],
        data=cipher, limit=A.FRAME_BYTES + 4096, timeout=10)
    value = A.validate_envelope(A.unpack(plain), expected)
    # Recheck public run identity after download; do not splice another attempt.
    after = A.decode(runner([*gh[:-1], gh[-1] + '/actions/runs/' + run_id], limit=65536, timeout=20))
    A.require(validate_run(after, run_id) == head)
    create_private(directory / 'binding.json', A.canonical(expected) + b'\n')
    create_private(directory / 'aggregate.json', A.canonical(value) + b'\n')
    return value


def main():
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise A.Refused('arguments_refused')
    parser = Parser(description=__doc__)
    for name in ('run-id', 'nonce', 'certificate', 'key', 'directory'):
        parser.add_argument('--' + name, required=True)
    try:
        args = parser.parse_args()
        receive(args.run_id, args.nonce, args.certificate, args.key, args.directory)
        print('NAVER_INSPECTION_LOCAL=VERIFIED')
        return 0
    except BaseException:
        print('NAVER_INSPECTION_LOCAL=REFUSED')
        return 2


if __name__ == '__main__':
    sys.exit(main())
