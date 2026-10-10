#!/usr/bin/env python3
"""Candidate only: parent must verify BPF attachment, controls and ingress."""
import errno
import socket


def check():
    try:
        with socket.create_connection(("1.234.23.117", 22), timeout=3):
            pass
    except OSError:
        return False
    try:
        with socket.create_connection(("127.0.0.1", 22), timeout=3):
            pass
    except OSError as error:
        # TCP cgroup-SKB drops may surface as timeout, not an immediate errno.
        # This permits the parent verification stage; it does NOT prove policy.
        return error.errno in (errno.EACCES, errno.EPERM) or isinstance(error, TimeoutError)
    return False


if __name__ == "__main__":
    raise SystemExit(0 if check() else 1)
