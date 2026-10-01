#!/usr/bin/env python3
"""Fixed in-unit network guard. No authentication, payload, DNS or output."""
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
        return error.errno in (errno.EACCES, errno.EPERM)
    return False


if __name__ == "__main__":
    raise SystemExit(0 if check() else 1)
