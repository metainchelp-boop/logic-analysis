"""엔진 쓰기 연결의 ``-shm`` 잠금 시험 (2026-10-05 운영 엔진 종료 코드 135 · 재시작 5회).

원인: ``open_writer`` 가 연결을 연 뒤 곁 파일(``-wal``·``-shm``)을 ``os.open → os.close`` 했다. POSIX(fcntl) 잠금은 같은
프로세스가 그 파일의 다른 fd 를 하나라도 닫으면 전부 풀리므로, SQLite 가 ``-shm`` 의 DMS 바이트에 건 SHARED 잠금이
사라졌다. 그 뒤 다른 프로세스가 DB 를 열면 자기를 첫 사용자로 여겨 ``-shm`` 을 3바이트로 자르고, ``-shm`` 을 mmap 하던
엔진은 SIGBUS 로 죽었다(이미 있는 WAL DB 를 다시 열 때 — 운영은 늘 이 경우).

- 이미 있는 WAL DB 를 다시 연 쓰기 연결은 ``-shm`` DMS 바이트에 SHARED 잠금을 쥐고 있어야 한다(다른 프로세스에서 F_GETLK).
- 쓰기·읽기를 되풀이하는 엔진 프로세스 옆에서 다른 프로세스가 ``open_reader`` 로 여러 번 읽어도 엔진이 살아 있어야 한다.
"""
from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DMS_OFFSET = 128   # SQLite unix VFS: UNIX_SHM_BASE(120) + SQLITE_SHM_NLOCK(8)

_GETLK = textwrap.dedent("""
    import fcntl, os, struct, sys
    fd = os.open(sys.argv[1], os.O_RDONLY)
    try:
        req = struct.pack('hhqqi', fcntl.F_WRLCK, 0, int(sys.argv[2]), 1, 0)
        kind = struct.unpack('hhqqi', fcntl.fcntl(fd, fcntl.F_GETLK, req))[0]
        print({fcntl.F_UNLCK: 'UNLOCKED', fcntl.F_RDLCK: 'SHARED', fcntl.F_WRLCK: 'EXCLUSIVE'}[kind])
    finally:
        os.close(fd)
""")

_ENGINE = textwrap.dedent("""
    import os, signal, sys, time
    sys.path[:0] = [sys.argv[2], os.path.join(sys.argv[2], 'backend')]
    from naver_engine import store as S
    if sys.argv[3] == 'prepare':            # 운영처럼 -wal·-shm 이 남은 채로 끝난 DB 를 만든다
        st = S.open_writer(sys.argv[1]); st._conn.execute('SELECT 1').fetchone()
        os.kill(os.getpid(), signal.SIGKILL)
    st = S.open_writer(sys.argv[1])
    c = st._conn
    c.set_authorizer(None)                   # 시험 장치 — 부하용 표 하나만
    c.execute('CREATE TABLE IF NOT EXISTS shm_lock_load(id INTEGER PRIMARY KEY, v BLOB)')
    print('READY', flush=True)
    deadline = time.monotonic() + float(sys.argv[4])
    while time.monotonic() < deadline:       # 수집처럼 쓰기와 읽기를 되풀이 — WAL-index 를 계속 쓰고 읽는다
        c.execute('BEGIN IMMEDIATE'); c.execute('INSERT INTO shm_lock_load(v) VALUES (randomblob(2000))'); c.execute('COMMIT')
        c.execute('SELECT COUNT(*) FROM shm_lock_load').fetchone()
    st.close()
    print('DONE', flush=True)
""")

_READER = textwrap.dedent("""
    import os, sys
    sys.path[:0] = [sys.argv[2], os.path.join(sys.argv[2], 'backend')]
    from naver_engine import store as S
    r = S.open_reader(sys.argv[1])
    try:
        r._conn.execute('BEGIN')
        r._conn.execute("SELECT COUNT(*) FROM naver_auto_meta").fetchone()
        r._conn.execute('ROLLBACK')
    finally:
        r.close()
""")


def _run(code, *args, timeout=60):
    return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, timeout=timeout)


class WriterKeepsShmLockTest(unittest.TestCase):
    def setUp(self):
        # 짧은 경로 — 유닉스 소켓·잠금과 무관하지만 다른 시험과 같은 습관
        self.dir = tempfile.TemporaryDirectory(prefix="nvshm")
        os.chmod(self.dir.name, 0o700)
        self.path = os.path.join(self.dir.name, "engine.db")
        prep = _run(_ENGINE, self.path, str(ROOT), "prepare", "0")
        self.assertEqual(prep.returncode, -signal.SIGKILL, prep.stderr[-500:])
        self.assertTrue(os.path.exists(self.path + "-shm"))

    def tearDown(self):
        self.dir.cleanup()

    def _start_engine(self, seconds):
        engine = subprocess.Popen([sys.executable, "-c", _ENGINE, self.path, str(ROOT), "run", str(seconds)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: engine.poll() is None and engine.kill())
        line = engine.stdout.readline().strip()
        self.assertEqual(line, "READY", engine.stderr.read()[-500:] if engine.poll() is not None else line)
        return engine

    def test_reopened_writer_holds_dms_shared_lock(self):
        engine = self._start_engine(10)
        probe = _run(_GETLK, self.path + "-shm", str(DMS_OFFSET))
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), "SHARED",
                         "엔진이 -shm DMS 잠금을 잃었다 — 다른 프로세스가 열면 -shm 을 잘라 엔진이 SIGBUS 로 죽는다")
        engine.kill()
        engine.wait(timeout=10)

    def test_engine_survives_other_process_readers(self):
        engine = self._start_engine(20)
        reads = 0
        for _ in range(15):
            if engine.poll() is not None:
                break
            res = _run(_READER, self.path, str(ROOT))
            self.assertEqual(res.returncode, 0, res.stderr[-500:])
            reads += 1
        time.sleep(0.3)
        rc = engine.poll()
        self.assertIsNone(rc, f"다른 프로세스 읽기 {reads}회 뒤 엔진이 죽었다(returncode={rc} · SIGBUS 는 -7)")
        engine.kill()
        engine.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
