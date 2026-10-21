"""Synthetic fixture writer in an independently exec'd process; parent DB-open zero."""
from contextlib import contextmanager
import os
from pathlib import Path
import select
import subprocess
import sys
import time

WRITER = r"""
import sqlite3, sys
from pathlib import Path
directory = Path(sys.argv[1])
connection = sqlite3.connect(directory/'logic_data.db', isolation_level=None)
try:
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA wal_autocheckpoint=0')
    connection.executescript('''CREATE TABLE clients(id,naver_store_url,main_keywords,role,vertical);
CREATE TABLE client_keyword_product(client_id,keyword,product_url);
CREATE TABLE client_keyword_mute(client_id,keyword);
CREATE TABLE collector_observations(observation_id,keyword,collected_date,status,kind,reason,
 received_at,payload_hash,products_json,meta_json);
CREATE TABLE collected_serp(keyword,collected_date,total,products_json,meta_json);''')
    sys.stdout.buffer.write(b'READY\n'); sys.stdout.buffer.flush()
    sys.stdin.buffer.read(1)
finally:
    connection.close()
"""


@contextmanager
def independent_writer(directory):
    directory = Path(directory)
    if directory.resolve() != directory or not directory.is_dir() or not directory.name.startswith('naver-probe-fixture-'):
        raise ValueError('FIXTURE_DIRECTORY')
    child = subprocess.Popen([sys.executable, '-I', '-B', '-c', WRITER, str(directory)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={}, close_fds=True)
    try:
        deadline = time.monotonic() + 10
        ready = bytearray()
        while len(ready) < 6:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([child.stdout], [], [], remaining)[0]:
                raise ValueError('FIXTURE_WRITER_TIMEOUT')
            part = os.read(child.stdout.fileno(), 6 - len(ready))
            if not part:
                raise ValueError('FIXTURE_WRITER_NOT_READY')
            ready.extend(part)
        if bytes(ready) != b'READY\n' or child.poll() is not None:
            raise ValueError('FIXTURE_WRITER_NOT_READY')
        yield
        if child.poll() is not None:
            raise ValueError('FIXTURE_WRITER_EXITED_EARLY')
    finally:
        child.stdin.close()
        child.stdout.close()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
