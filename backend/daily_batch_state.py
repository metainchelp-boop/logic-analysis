"""08:30 아침 분석의 진행 기록 — 끊기면 남은 키워드만 이어서 하게 한다(2026-11-17 · 대표 「고쳐」).

왜 있나
- 11/3 · 11/4 · 11/15 · 11/16 아침 분석이 시작 20초 안에 1~4건만 하고 멈췄고, 그날 다시 돌지 않았다
  (다른 날은 약 900건). 그날 원래 기록은 서버를 새로 올릴 때 지워져 원인을 확인하지 못했다.
- 추정: 분석을 맡은 서버 일꾼이 멈춰 교체됐고, 새 일꾼은 다음 날 08:30 까지 기다렸다.

이 표가 하는 일
- 아침 분석의 시작 · 진행(키워드마다) · 끝을 날짜별 한 줄로 남긴다 — 다음에 멈추면 「어디서 · 어느 일꾼에서」 멈췄는지 남는다.
- 시작했는데 끝나지 않았고 진행이 3분 넘게 멈춘 날은, 오전(08:35~10:59) 10분마다 보는 점검이 남은 키워드만 이어서 분석한다.
- 오전에 아예 시작하지 못한 날도 같은 점검이 시작한다(서버가 08:30 뒤에 켜진 경우).

⚠️ 11시 이후에는 이어서 하지 않는다 — 약 1시간 걸리는 분석이 업무 시간에 돌면 직원 화면이 느려진다
   (2026-07-27 502 사고로 배치를 새벽 · 이른 아침으로 옮긴 이유). 그날은 표에 「끝나지 않음」으로 남는다.
⚠️ 하루 이어서 하기는 3번까지 — 같은 자리에서 계속 죽는 경우 끝없이 되풀이하지 않게.
⚠️ 이 파일은 표준 라이브러리만 쓴다(배포 시험 환경에서도 돈다).
"""
from datetime import datetime, time as dtime

JOB = "daily_analysis"
STALE_SECONDS = 180            # 진행이 이만큼 멈춰 있으면 「끊김」으로 본다
MAX_RESUMES = 3                # 하루 이어서 하기 최대 횟수
WINDOW_START = dtime(8, 35)    # 이 시각부터
WINDOW_END = dtime(11, 0)      # 이 시각 전까지만 이어서 한다

_FMT = "%Y-%m-%d %H:%M:%S"


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_batch_runs (
            run_date TEXT NOT NULL,
            job TEXT NOT NULL,
            started_at TEXT,
            heartbeat_at TEXT,
            finished_at TEXT,
            total INTEGER DEFAULT 0,
            done INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            skipped INTEGER DEFAULT 0,
            resumes INTEGER DEFAULT 0,
            pid INTEGER,
            last_client_id INTEGER,
            note TEXT DEFAULT '',
            PRIMARY KEY (run_date, job)
        )
    """)
    conn.commit()


def _now_str(now=None):
    return (now or datetime.now()).strftime(_FMT)


def get_run(conn, run_date, job=JOB):
    cur = conn.execute(
        "SELECT run_date, job, started_at, heartbeat_at, finished_at, total, done, failed, skipped,"
        " resumes, pid, last_client_id, note FROM daily_batch_runs WHERE run_date=? AND job=?",
        (run_date, job))
    r = cur.fetchone()
    if r is None:
        return None
    keys = ("run_date", "job", "started_at", "heartbeat_at", "finished_at", "total", "done", "failed",
            "skipped", "resumes", "pid", "last_client_id", "note")
    return dict(zip(keys, tuple(r)))


def mark_start(conn, run_date, pid, resume=False, note="", job=JOB, now=None):
    """시작(또는 이어서 하기) 기록. 이어서 하기면 앞선 진행 수는 두고 횟수만 늘린다."""
    ts = _now_str(now)
    prev = get_run(conn, run_date, job)
    if prev is None:
        conn.execute(
            "INSERT INTO daily_batch_runs (run_date, job, started_at, heartbeat_at, pid, resumes, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_date, job, ts, ts, pid, 0, note))
    elif resume:
        tail = (prev.get("note") or "")
        line = (f"이어서 {int(prev.get('resumes') or 0) + 1}회차 {ts[11:19]} — 직전 진행 {prev.get('done') or 0}건"
                f" · 마지막 갱신 {(prev.get('heartbeat_at') or '?')[11:19]} · 직전 일꾼 {prev.get('pid')}")
        if note:
            line += f" · {note}"
        conn.execute(
            "UPDATE daily_batch_runs SET heartbeat_at=?, finished_at=NULL, pid=?, resumes=resumes+1, note=?"
            " WHERE run_date=? AND job=?",
            (ts, pid, (tail + " | " if tail else "") + line, run_date, job))
    else:
        # 같은 날 정규 시작이 또 온 경우(드묾) — 새로 시작한 것으로 다시 적는다.
        conn.execute(
            "UPDATE daily_batch_runs SET started_at=?, heartbeat_at=?, finished_at=NULL, total=0, done=0,"
            " failed=0, skipped=0, resumes=0, pid=?, last_client_id=NULL, note=? WHERE run_date=? AND job=?",
            (ts, ts, pid, note, run_date, job))
    conn.commit()


def set_total(conn, run_date, total, skipped, job=JOB):
    conn.execute("UPDATE daily_batch_runs SET total=?, skipped=? WHERE run_date=? AND job=?",
                 (int(total), int(skipped), run_date, job))
    conn.commit()


def heartbeat(conn, run_date, client_id, ok, job=JOB, now=None):
    """키워드 하나가 끝날 때마다(성공 · 실패) 진행을 남긴다."""
    col = "done" if ok else "failed"
    conn.execute(
        f"UPDATE daily_batch_runs SET {col}={col}+1, heartbeat_at=?, last_client_id=? WHERE run_date=? AND job=?",
        (_now_str(now), client_id, run_date, job))
    conn.commit()


def mark_finish(conn, run_date, job=JOB, now=None):
    ts = _now_str(now)
    conn.execute("UPDATE daily_batch_runs SET finished_at=?, heartbeat_at=? WHERE run_date=? AND job=?",
                 (ts, ts, run_date, job))
    conn.commit()


def add_note(conn, run_date, text, job=JOB):
    prev = get_run(conn, run_date, job)
    if prev is None:
        return
    tail = prev.get("note") or ""
    conn.execute("UPDATE daily_batch_runs SET note=? WHERE run_date=? AND job=?",
                 ((tail + " | " if tail else "") + text[:300], run_date, job))
    conn.commit()


def decide(row, now, running_here=False):
    """오전 점검이 할 일: None(아무것도 안 함) · 'start'(오늘 시작 안 됨) · 'resume'(끊김) · 'stuck'(이 일꾼에서 붙잡힘).

    - 오전 창(08:35~10:59) 밖이면 아무것도 안 한다.
    - 이 일꾼에서 아직 도는 중이면 새로 돌리지 않는다(진행이 오래 멈췄으면 'stuck' 으로 알리기만).
    - 오늘 기록이 없으면 'start' · 끝났으면 None · 이어서 하기 한도를 넘었으면 None.
    - 진행이 3분 넘게 멈췄으면 'resume'.
    """
    t = now.time()
    if t < WINDOW_START or t >= WINDOW_END:
        return None
    stale = False
    if row is not None and not row.get("finished_at"):
        try:
            hb = datetime.strptime(row.get("heartbeat_at") or row.get("started_at") or "", _FMT)
            stale = (now - hb).total_seconds() > STALE_SECONDS
        except ValueError:
            stale = True
    if running_here:
        return "stuck" if stale else None
    if row is None:
        return "start"
    if row.get("finished_at"):
        return None
    if int(row.get("resumes") or 0) >= MAX_RESUMES:
        return None
    return "resume" if stale else None
