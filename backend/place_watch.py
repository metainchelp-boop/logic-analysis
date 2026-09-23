"""플레이스(지도) 무인 순위 추적이 멈춘 것을 **서버가 스스로 알아챈다** (대표 지시 2026-09-23).

⚠️ 이 파일이 생긴 이유 — **추적이 이틀 통째로 빠졌는데 아무도 몰랐다.**
   2026-09-23 오프라인 점검에서 지난 14일 중 **9/15·9/17 두 날 추적기 기록이 0** 이었다
   (활성 19곳 중 0곳). 쇼핑 쪽에는 멈춤 감시(`collect_watch.py`)가 있지만 그것은
   `collected_serp` 만 본다 — 플레이스는 한 줄도 안 본다. 추적기 팝업의 「오늘 수집」은
   그 PC 앞에서 열어 봐야 보인다.

   ⇒ 매시간 「오늘 활성 대상 중 몇 곳을 실제로 쟀나」를 센다.

⚠️ **요청이 아니라 기록으로 잰다** — `collect_watch` 와 같은 원칙(2026-09-10 교훈).
   추적 대상 목록 조회(`/api/place/track-targets`)는 수집을 안 해도 온다.
   실제로 남은 순위 기록(`place_rank_history`)만 본다.

⚠️ **「잰 것」은 노출·미노출만이다.** 「미확인」은 추적기가 화면을 못 읽은 것이라
   「우리가 안 봤다」는 뜻이다(`save_place_rank` 와 같은 규칙).

⚠️ **표만으로는 「추적기가 왔나」를 못 가른다** — 직원이 플레이스 분석을 돌려도 같은 표에
   출처 칸 없이 쌓인다. 그래서 `/api/place/ingest` 도착을 따로 적는다(`note_ingest`).
   ⚠️ 이 도착 기록은 **배포 뒤부터만** 있다. 기록이 한 줄도 없으면 「추적기 안 옴(0)」이 아니라
      「아직 못 쟀다(None)」로 돌려준다 — **실패와 0 은 다른 값이다**(9/18 대표 지시).

⚠️ 의존성 없음(표준 라이브러리만) — 배포 회귀 게이트가 fastapi 없이 import 한다.
⚠️ **어떤 실패도 밖으로 내보내지 않는다** — 감시가 추적 기록을 막으면 본말전도다.
⚠️ 문자는 보내지 않는다 — 수집 경보와 같은 결정(2026-09-10 대표 「문자 안 받을게」).
   판정은 표와 로그에 남고, 화면은 `/api/collector/health` 의 `place` 로 읽는다.
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")


def _int_env(name: str, default: int) -> int:
    """환경변수로 조절하되, 값이 이상하면 기본값으로 돌아간다."""
    try:
        v = int(str(os.getenv(name, "")).strip())
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


# 몇 시부터 「오늘 못 쟀다」로 판정하나.
# ⚠️ 추적기는 매일 **06:30** 한 번 돈다(`extension-place/place-runner.js` RUN_HOUR=6 · RUN_MIN=30).
#    19곳 기준 약 15분이면 끝난다(실측 9/23 06:48). 09시 전에는 「아직 도는 중」일 수 있어
#    못 쟀어도 경보가 아니라 `pending` 이다.
CHECK_FROM_HOUR = _int_env("PLACE_WATCH_FROM_HOUR", 9)
# 며칠 연속 못 잰 대상을 「계속 빠지는 곳」으로 세나.
# ⚠️ 9/16~9/21 에 한 대상이 엿새를 빠졌는데 매일 18/19 라 「거의 다 됐다」로 보였다.
#    하루 빠짐은 흔하다(네이버 일시 오류) — 사흘이면 사람이 볼 일이다.
STALE_DAYS = _int_env("PLACE_WATCH_STALE_DAYS", 3)
# 화면·진단이 보는 지난 며칠 줄.
HISTORY_DAYS = 14
# 감시 기록 보관(일). 하루 13줄 + 도착 1줄 — 작다. 무한히 쌓이지만 않게.
KEEP_DAYS = 90

STATE_OK = "ok"             # 활성 대상 전부 오늘 쟀다
STATE_PARTIAL = "partial"   # 일부만 쟀다
STATE_MISSED = "missed"     # 한 곳도 못 쟀다(판정 시각 이후)
STATE_PENDING = "pending"   # 판정 시각 전이라 아직 판단하지 않는다
STATE_NONE = "none"         # 활성 대상이 없다 — 잴 것이 없다
STATE_UNKNOWN = "unknown"   # 조회 실패 — 0 으로 찍지 않는다

MEASURED_STATES = ("노출", "미노출")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _norm(s) -> str:
    """업체명·지역 정규화 — **`place_crawler._norm` 과 같은 규칙**(공백 제거 + 소문자).
    ⚠️ 규칙이 갈라지면 키가 안 맞아 멀쩡한 추적을 「못 쟀다」로 센다 — 시험이 두 함수를 대조한다."""
    return re.sub(r"\s+", "", str(s or "")).lower()


def target_keys(place_id, business_name, region) -> list:
    """추적 대상 한 줄이 기록될 수 있는 업체 키 전부.

    ingest 는 `doc:{장소번호}`(장소번호가 있으면) 또는 `nm:{이름}|{지역}` 으로 쓴다
    (`main._place_registry_business_key`). 직원 분석은 장소번호를 못 찾으면 `nm:` 으로 쓴다.
    ⚠️ **둘 다 본다** — 장소번호가 뒤늦게 채워진(self-heal) 대상은 그날 기록이 `nm:` 일 수 있다.
    """
    keys = []
    pid = str(place_id or "").strip()
    if pid:
        keys.append(f"doc:{pid}")
    nm = _norm(business_name)
    if nm:
        keys.append(f"nm:{nm}|{_norm(region)}")
    return keys


def ensure_table(conn) -> None:
    """멱등. 진행 중인 트랜잭션 안에서는 commit 하지 않는다(collect_watch 와 같은 이유)."""
    try:
        in_tx = conn.in_transaction
        conn.execute("""
            CREATE TABLE IF NOT EXISTS place_watch(
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                checked_at  TEXT NOT NULL,
                state       TEXT NOT NULL,      -- ok / partial / missed / pending / none / unknown
                active      INTEGER,
                measured    INTEGER,
                unconfirmed INTEGER,
                missing     INTEGER,
                stale       INTEGER,
                arrivals    INTEGER,            -- 오늘 추적기 도착 횟수(도착 기록 전이면 NULL)
                notice      TEXT DEFAULT ''     -- 이번 판정이 새로 알린 것(missed/partial/recovered)
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_place_watch_at ON place_watch(checked_at)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS place_ingest_seen(
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                items       INTEGER DEFAULT 0,
                saved       INTEGER DEFAULT 0,
                skipped     INTEGER DEFAULT 0
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_place_ingest_seen_at ON place_ingest_seen(received_at)")
        if not in_tx:
            conn.commit()
    except Exception:
        pass


def note_ingest(items: int, saved: int, skipped: int, conn=None) -> bool:
    """추적기 결과가 서버에 **도착했다**는 사실만 적는다(`/api/place/ingest` 끝에서 부른다).

    ⚠️ 어떤 실패도 밖으로 내보내지 않는다 — 이 한 줄 때문에 순위 기록 응답이 깨지면 안 된다.
    ⚠️ 업체명·키워드는 적지 않는다 — 건수만.
    """
    own = conn is None
    try:
        if own:
            conn = _conn()
        ensure_table(conn)
        conn.execute(
            "INSERT INTO place_ingest_seen(received_at, items, saved, skipped) VALUES(?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             int(items or 0), int(saved or 0), int(skipped or 0)))
        if own:
            conn.commit()
        return True
    except Exception:
        return False
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _active_targets(conn) -> list:
    rows = conn.execute(
        "SELECT id, business_name, region, place_id, keyword, created_at "
        "  FROM place_track_target WHERE active = 1").fetchall()
    out = []
    for r in rows:
        kw = str(r["keyword"] or "").strip()
        if not kw:
            continue
        out.append({"id": r["id"], "keyword": kw,
                    "keys": target_keys(r["place_id"], r["business_name"], r["region"]),
                    "created": str(r["created_at"] or "")[:10]})
    return out


def _day_marks(conn, start: str, end_excl: str) -> dict:
    """[start, end_excl) 기간 기록을 {날짜: {"measured": set, "seen": set}} 으로.
    원소는 (업체키, 키워드) 쌍."""
    rows = conn.execute(
        "SELECT business_key, keyword, rank_position, rank_state, checked_at "
        "  FROM place_rank_history WHERE checked_at >= ? AND checked_at < ?",
        (start, end_excl)).fetchall()
    days = {}
    for r in rows:
        d = str(r["checked_at"] or "")[:10]
        pair = (str(r["business_key"] or ""), str(r["keyword"] or "").strip())
        slot = days.setdefault(d, {"measured": set(), "seen": set()})
        slot["seen"].add(pair)
        if r["rank_position"] is not None or str(r["rank_state"] or "").strip() in MEASURED_STATES:
            slot["measured"].add(pair)
    return days


def _hit(target: dict, pairs: set) -> bool:
    return any((k, target["keyword"]) in pairs for k in target["keys"])


def _tracker_today(conn, today: str, tomorrow: str) -> Optional[dict]:
    """오늘 추적기 도착. 도착 기록이 **한 줄도 없으면 None**(= 아직 못 잼 · 0 이 아니다)."""
    try:
        first = conn.execute("SELECT MIN(received_at) m FROM place_ingest_seen").fetchone()
        since = first["m"] if first else None
        if not since:
            return None
        r = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(items),0) items, COALESCE(SUM(saved),0) saved, "
            "       MAX(received_at) last FROM place_ingest_seen "
            " WHERE received_at >= ? AND received_at < ?", (today, tomorrow)).fetchone()
        return {"arrivals": int(r["n"] or 0), "items": int(r["items"] or 0),
                "saved": int(r["saved"] or 0), "last_at": r["last"], "since": since}
    except Exception:
        return None


def evaluate(conn, now: Optional[datetime] = None) -> dict:
    """지금 상태를 판정한다. DB 를 고치지 않는다(읽기 전용).

    ⚠️ 조회가 실패하면 `unknown` — 「0곳 쟀다」로 바꿔 적지 않는다.
    """
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    out = {"date": today, "state": STATE_UNKNOWN, "active": None, "measured": None,
           "unconfirmed": None, "missing": None, "stale": None, "stale_ids": [],
           "tracker": None, "check_from_hour": CHECK_FROM_HOUR, "stale_days": STALE_DAYS}
    try:
        ensure_table(conn)
        targets = _active_targets(conn)
        out["active"] = len(targets)
        out["tracker"] = _tracker_today(conn, today, tomorrow)
        if not targets:
            out.update(measured=0, unconfirmed=0, missing=0, stale=0, state=STATE_NONE)
            return out
        win_start = (now - timedelta(days=STALE_DAYS - 1)).strftime("%Y-%m-%d")
        marks = _day_marks(conn, win_start, tomorrow)
        t_marks = marks.get(today, {"measured": set(), "seen": set()})
        measured = unconfirmed = missing = 0
        for t in targets:
            if _hit(t, t_marks["measured"]):
                measured += 1
            elif _hit(t, t_marks["seen"]):
                unconfirmed += 1
            else:
                missing += 1
        # 며칠째 못 잰 곳 — 그 기간 안에 새로 등록된 대상은 뺀다(아직 잴 기회가 없었다).
        window_measured = set()
        for d in marks.values():
            window_measured |= d["measured"]
        stale_ids = [t["id"] for t in targets
                     if (t["created"] and t["created"] < win_start)
                     and not _hit(t, window_measured)]
        out.update(measured=measured, unconfirmed=unconfirmed, missing=missing,
                   stale=len(stale_ids), stale_ids=stale_ids)
        if measured >= len(targets):
            out["state"] = STATE_OK
        elif now.hour < CHECK_FROM_HOUR:
            out["state"] = STATE_PENDING
        elif measured == 0:
            out["state"] = STATE_MISSED
        else:
            out["state"] = STATE_PARTIAL
        return out
    except Exception:
        out["state"] = STATE_UNKNOWN
        return out


def history(conn, now: Optional[datetime] = None, days: int = HISTORY_DAYS) -> Optional[list]:
    """지난 며칠의 날짜별 「활성 대상 중 잰 곳」. 조회 실패는 None(빈 목록과 다르다).

    ⚠️ **지금의 활성 목록**으로 잰다 — 그 사이 꺼진 대상은 안 보이고, 그날 이후 등록된 대상은
       그날 분모에서 뺀다(등록 전 날을 「못 쟀다」로 세지 않게).
    """
    now = now or datetime.now()
    try:
        targets = _active_targets(conn)
        start = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        marks = _day_marks(conn, start, tomorrow)
        out = []
        for i in range(days - 1, -1, -1):
            d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            pool = [t for t in targets if not t["created"] or t["created"] <= d]
            m = marks.get(d, {"measured": set()})["measured"]
            out.append({"date": d, "active": len(pool),
                        "measured": sum(1 for t in pool if _hit(t, m))})
        return out
    except Exception:
        return None


def _message(ev: dict) -> str:
    """화면이 그대로 띄울 한 문장. 업체명·키워드는 넣지 않는다(건수만)."""
    st = ev.get("state")
    act, meas = ev.get("active") or 0, ev.get("measured") or 0
    tr = ev.get("tracker")
    if st == STATE_MISSED:
        if tr is not None and tr.get("arrivals", 0) > 0:
            return (f"지도 순위 추적기는 오늘 돌았지만 {act}곳 모두 순위를 읽지 못했습니다"
                    f"(미확인 {ev.get('unconfirmed') or 0}). 네이버 지도 화면이 바뀌었을 수 있습니다.")
        return (f"오늘 지도 순위가 한 곳도 기록되지 않았습니다(활성 {act}곳). "
                "추적 PC의 전원·크롬·로직분석 로그인을 확인해 주세요.")
    if st == STATE_PARTIAL:
        msg = (f"오늘 지도 순위 {act}곳 중 {act - meas}곳을 재지 못했습니다"
               f"(미확인 {ev.get('unconfirmed') or 0} · 기록 없음 {ev.get('missing') or 0}).")
        if ev.get("stale"):
            msg += f" 그중 {ev['stale']}곳은 {STALE_DAYS}일째 못 잽니다."
        return msg
    return ""


def decide_notice(prev, ev: dict) -> Optional[str]:
    """이번 판정이 **새로** 알릴 것. 없으면 None.

    ① 오늘 처음 못 쟀다(또는 상태가 바뀌었다) : missed / partial
    ② 같은 날 못 쟀다가 다 쟀다             : recovered
    그 밖(계속 같은 상태·pending·none·unknown)은 알리지 않는다 — 로그 도배 방지(9/9 교훈:
    같은 경고가 하루 13줄 쌓여 원인 줄을 밀어냈다).
    """
    st = ev.get("state")
    prev_state = prev["state"] if prev else None
    prev_day = str(prev["checked_at"])[:10] if prev else None
    same_day = prev_day == ev.get("date")
    if st in (STATE_MISSED, STATE_PARTIAL):
        return None if (same_day and prev_state == st) else st
    if st == STATE_OK and same_day and prev_state in (STATE_MISSED, STATE_PARTIAL):
        return "recovered"
    return None


def _last_row(conn):
    try:
        return conn.execute("SELECT * FROM place_watch ORDER BY id DESC LIMIT 1").fetchone()
    except Exception:
        return None


def _prune(conn, now: datetime) -> None:
    cut = (now - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    try:
        conn.execute("DELETE FROM place_watch WHERE checked_at < ?", (cut,))
        conn.execute("DELETE FROM place_ingest_seen WHERE received_at < ?", (cut,))
    except Exception:
        pass


def run_check(conn=None, now: Optional[datetime] = None) -> dict:
    """매시간 부르는 본체. 판정을 표에 남기고 돌려준다.

    ⚠️ 연결을 남이 쥐고 있으면 커밋은 그쪽 몫이다(collect_watch 와 같은 규칙 —
       `in_transaction` 으로 판단하면 INSERT 직후 항상 True 라 커밋이 건너뛰어진다).
    """
    own = conn is None
    now = now or datetime.now()
    ev = {"state": STATE_UNKNOWN, "notice": None}
    try:
        if own:
            conn = _conn()
        ensure_table(conn)
        ev = evaluate(conn, now=now)
        prev = _last_row(conn)
        notice = decide_notice(prev, ev)
        ev["notice"] = notice
        ev["message"] = _message(ev)
        tr = ev.get("tracker")
        conn.execute(
            "INSERT INTO place_watch(checked_at, state, active, measured, unconfirmed, "
            "                        missing, stale, arrivals, notice) VALUES(?,?,?,?,?,?,?,?,?)",
            (now.strftime("%Y-%m-%d %H:%M:%S"), ev["state"], ev.get("active"), ev.get("measured"),
             ev.get("unconfirmed"), ev.get("missing"), ev.get("stale"),
             (tr or {}).get("arrivals") if tr is not None else None, notice or ""))
        _prune(conn, now)
        if own:
            conn.commit()
        return ev
    except Exception:
        return ev
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def summary(conn=None, now: Optional[datetime] = None) -> dict:
    """화면·진단이 읽는 요약. 조회 실패는 빈 dict(= 「못 쟀다」 · 화면은 아무것도 안 그린다).

    ⚠️ 매번 새로 센다(마지막 점검 줄을 읽지 않는다) — 점검 사이에 추적기가 늦게 와도
       화면이 한 시간 동안 옛 경보를 띄우지 않게.
    """
    own = conn is None
    now = now or datetime.now()
    try:
        if own:
            conn = _conn()
        ev = evaluate(conn, now=now)
        if ev.get("state") == STATE_UNKNOWN:
            return {}
        ev["message"] = _message(ev)
        ev["days"] = history(conn, now=now)
        r = _last_row(conn)
        ev["last_check"] = r["checked_at"] if r else None
        return ev
    except Exception:
        return {}
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass
