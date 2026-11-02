#!/usr/bin/env python3
"""Observe one fixed candidate's metadata. Never open or read the candidate."""
import contextlib
import datetime
import errno
import json
import os
import signal
import stat
import sys

PARENTS = ('root', 'content-studio-deploy', 'autobid')
LEAF = '.env'
ALIAS = 'autobid-env-candidate'
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_REPORT_BYTES = 4096
TIME_BUDGET = 5


class ObservationError(Exception):
    def __init__(self, code):
        self.code = code


class DeadlineExpired(BaseException):
    """A deadline bypasses ordinary per-file error handling."""


def directory_identity(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode,
            metadata.st_uid, metadata.st_gid, metadata.st_nlink)


def file_metadata(metadata):
    return {'device': metadata.st_dev, 'inode': metadata.st_ino,
            'mode': stat.S_IMODE(metadata.st_mode), 'uid': metadata.st_uid,
            'gid': metadata.st_gid, 'links': metadata.st_nlink,
            'size_bytes': metadata.st_size, 'mtime_ns': metadata.st_mtime_ns,
            'ctime_ns': metadata.st_ctime_ns}


def result():
    return {'schema_version': 1, 'read_only': True, 'status': 'incomplete',
            'collected_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'error': None, 'candidate': {'alias': ALIAS, 'exists': None, 'kind': 'unknown'},
            'original_key_available': 'unknown', 'stop_safety': 'not_determined'}


def failure(error):
    if isinstance(error, ObservationError):
        return error.code
    if isinstance(error, PermissionError):
        return 'permission_denied'
    if isinstance(error, FileNotFoundError):
        return 'changed_during_query'
    if isinstance(error, OSError) and error.errno in (errno.ELOOP, errno.ENOTDIR):
        return 'symlink_or_non_directory_refused'
    return 'metadata_failed'


def optional_stat(parent, name):
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def validate_chain(root_fd, root_identity, chain):
    if directory_identity(os.fstat(root_fd)) != root_identity:
        raise ObservationError('changed_during_query')
    for parent, name, child, identity in chain:
        # Revalidate the pathname edge as well as the pinned descriptor.
        linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (directory_identity(linked) != identity or
                directory_identity(os.fstat(child)) != identity):
            raise ObservationError('changed_during_query')


def observe(root_fd):
    """root_fd is opened at / by collect; synthetic tests use their own root fd."""
    report = result()
    try:
        root_stat = os.fstat(root_fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ObservationError('root_type_refused')
        root_identity = directory_identity(root_stat)
        chain, parent = [], root_fd
        with contextlib.ExitStack() as stack:
            for name in PARENTS:
                before = optional_stat(parent, name)
                if before is None:
                    validate_chain(root_fd, root_identity, chain)
                    if optional_stat(parent, name) is not None:
                        raise ObservationError('changed_during_query')
                    validate_chain(root_fd, root_identity, chain)
                    report.update(status='complete', error='parent_absent')
                    report['candidate'].update(exists=False, kind='absent')
                    return report
                if stat.S_ISLNK(before.st_mode):
                    raise ObservationError('parent_symlink_refused')
                if not stat.S_ISDIR(before.st_mode):
                    raise ObservationError('parent_type_refused')
                child = os.open(name, DIRECTORY_FLAGS, dir_fd=parent)
                stack.callback(os.close, child)
                identity = directory_identity(before)
                if directory_identity(os.fstat(child)) != identity:
                    raise ObservationError('changed_during_query')
                chain.append((parent, name, child, identity))
                parent = child

            before = optional_stat(parent, LEAF)
            validate_chain(root_fd, root_identity, chain)
            after = optional_stat(parent, LEAF)
            if (before is None) != (after is None):
                raise ObservationError('changed_during_query')
            if before is None:
                validate_chain(root_fd, root_identity, chain)
                report.update(status='complete', error='target_absent')
                report['candidate'].update(exists=False, kind='absent')
                return report
            if stat.S_ISLNK(before.st_mode) or stat.S_ISLNK(after.st_mode):
                raise ObservationError('target_symlink_refused')
            if not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(after.st_mode):
                raise ObservationError('target_type_refused')
            if file_metadata(before) != file_metadata(after):
                raise ObservationError('changed_during_query')
            # A final chain check catches replacement during the leaf recheck.
            validate_chain(root_fd, root_identity, chain)
            report['candidate'].update(exists=True, kind='regular_file', **file_metadata(after))
            report['status'] = 'complete'
    except Exception as error:
        report = result()
        report['error'] = failure(error)
    return report


def collect():
    root_fd = None
    try:
        before = os.stat('/', follow_symlinks=False)
        root_fd = os.open('/', DIRECTORY_FLAGS)
        identity = directory_identity(before)
        if directory_identity(os.fstat(root_fd)) != identity:
            raise ObservationError('changed_during_query')
        report = observe(root_fd)
        if directory_identity(os.stat('/', follow_symlinks=False)) != identity:
            raise ObservationError('changed_during_query')
        return report
    except Exception as error:
        report = result()
        report['error'] = failure(error)
        return report
    finally:
        if root_fd is not None:
            os.close(root_fd)


def deadline(signum, frame):
    raise DeadlineExpired()


def main():
    report = result()
    if len(sys.argv) != 1:
        report['error'] = 'arguments_not_allowed'
    elif os.geteuid() != 0:
        report['error'] = 'root_required'
    else:
        previous = signal.signal(signal.SIGALRM, deadline)
        signal.alarm(TIME_BUDGET)
        try:
            report = collect()
        except DeadlineExpired:
            report['error'] = 'deadline_exceeded'
        except Exception:
            report['error'] = 'metadata_failed'
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    payload = json.dumps(report, separators=(',', ':'), ensure_ascii=True)
    if len(payload.encode('utf-8')) > MAX_REPORT_BYTES:
        report = result()
        report['error'] = 'report_limit_exceeded'
        payload = json.dumps(report, separators=(',', ':'))
    print(payload)
    return 0 if report['status'] == 'complete' else 2


if __name__ == '__main__':
    sys.exit(main())
