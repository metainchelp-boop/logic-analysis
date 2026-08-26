"""주간 로직 분석 보고서 — 자동 생성 + 보관정책.

배경 (2026-08-20, ① 메타 전산 요청 · 대표 승인)
    광고주 공유 링크에 주간 보고서를 누적해 보여주기 위해, 활성 광고주마다
    주 1건씩 reports 표에 등록한다.

⭐ 새로 분석을 돌리지 않는다.
    08:30 자동분석이 이미 매일 `generate_html_report()` 로 HTML 을 구워
    `client_analyses.report_html` 에 넣고 있다(실측: 전 행 100% 채워짐).
    주간 잡은 그 주에 쌓인 것 중 하나를 골라 reports 에 '등록'만 한다.
    ⇒ 네이버 호출 0회. 수집 커버리지가 빠듯한 상황이라 이 점이 중요하다.

⚠️ is_auto 는 이 기능과 반드시 같은 배포에 있어야 한다(reports.init 주석 참조).

⚠️ 보관정책이 함께 있는 이유 — reports 는 DB 행과 디스크 HTML 파일을 함께 만드는데
   지우는 규칙이 어디에도 없었다. 주 566건 × 평균 18KB ≈ 주 10MB 가 무한히 쌓인다.
   이 서버는 2026-08 초 「지우는 규칙 없이 쌓이던 백업」으로 디스크 87% 경보가 났던
   곳이라, 같은 구조를 하나 더 만들지 않기 위해 생성과 정리를 한 잡에 묶는다.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

# 업체당 보관할 자동 보고서 주차 수. 대표 승인 2026-08-20.
# ⚠️ 「개수」가 아니라 「개수 × 크기」로 관리할 것 — 평균 18KB × 566업체 × 12주 ≈ 120MB 에서 평형.
#    보고서가 커지거나 업체가 늘면 이 상수의 뜻이 달라진다(2026-08-05 백업 증식 교훈).
#
# ⚠️⚠️ 이 값을 바꾸면 ①(메타 전산)에 사전 통지할 것 — 계약이다(2026-08-20 상호 합의, PR #492).
#    ①은 광고주 화면에서 이 기간(84일)을 그대로 따라가 오래된 줄을 숨긴다(`withinRetention`).
#    - 우리가 기간을 **줄이면**: ①이 아직 보여 주는 줄이 우리 쪽에서 먼저 사라져 광고주가 눌렀을 때 404.
#    - 우리가 기간을 **늘리면**: ①이 계속 숨겨 늘린 보람이 없다.
#    어느 쪽이든 ①이 같은 값으로 맞춰야 화면과 실제가 일치한다.
AUTO_REPORT_KEEP_WEEKS = int(os.getenv("AUTO_REPORT_KEEP_WEEKS", "12"))

# 한 회차에 만들 수 있는 최대 건수 — 폭주 안전장치(정상값은 600 안팎).
MAX_PER_RUN = int(os.getenv("AUTO_REPORT_MAX_PER_RUN", "2000"))


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _volume_of(volume_json):
    """검색량 JSON 에서 총 검색량 하나를 뽑는다. 못 읽으면 0(정렬에서 뒤로)."""
    try:
        d = json.loads(volume_json or "{}")
    except Exception:
        return 0
    if not isinstance(d, dict):
        return 0
    for key in ("total", "totalVolume", "monthlyTotal"):
        v = d.get(key)
        if isinstance(v, (int, float)):
            return int(v)
    pc, mo = d.get("pc"), d.get("mobile")
    if isinstance(pc, (int, float)) or isinstance(mo, (int, float)):
        return int(pc or 0) + int(mo or 0)
    return 0


def run_weekly_reports():
    """매주 월요일 — 활성 광고주마다 지난 7일 분석분으로 보고서 1건 등록."""
    from reports import REPORTS_DIR, generate_report_hash

    started = datetime.now()
    logger.info(f"📄 주간 보고서 생성 시작 ({started.strftime('%m-%d %H:%M')})")

    made = skipped_dup = skipped_nomat = errors = 0
    conn = _conn()
    try:
        # 대상 = 08:30 분석 잡과 같은 자격(직원이 자동 분석을 꺼 둔 업체는 보고서도 안 나간다)
        clients = conn.execute(
            "SELECT id, name FROM clients "
            " WHERE status='active' AND COALESCE(role,'advertiser')='advertiser' "
            "   AND COALESCE(vertical,'store')='store' "
            "   AND COALESCE(auto_analysis,1)=1"
        ).fetchall()
        logger.info(f"   대상 업체 {len(clients)}곳")

        for c in clients:
            if made >= MAX_PER_RUN:
                logger.warning(f"   ⚠️ 한 회차 상한 {MAX_PER_RUN}건 도달 — 나머지는 다음 회차")
                break
            try:
                # 1) 이번 주에 이미 자동 보고서가 있으면 건너뛴다(재실행해도 같은 결과)
                dup = conn.execute(
                    "SELECT 1 FROM reports "
                    " WHERE client_id=? AND COALESCE(is_auto,0)=1 "
                    "   AND date(created_at) >= date('now','localtime','-6 day') LIMIT 1",
                    (c["id"],)
                ).fetchone()
                if dup:
                    skipped_dup += 1
                    continue

                # 2) 재료 — 지난 7일치, (키워드별 최신 1건)
                rows = conn.execute(
                    "SELECT keyword, product_url, report_html, volume_json, analyzed_date "
                    "  FROM client_analyses "
                    " WHERE client_id=? AND analyzed_date >= date('now','localtime','-6 day') "
                    " ORDER BY analyzed_date DESC",
                    (c["id"],)
                ).fetchall()
                if not rows:
                    skipped_nomat += 1
                    continue

                latest = {}
                for r in rows:
                    kw = (r["keyword"] or "").strip()
                    if kw and kw not in latest:
                        latest[kw] = r
                # 보고서 본문이 실제로 있는 것만 후보(빈 보고서를 광고주에게 내보내지 않는다)
                cands = [r for r in latest.values() if (r["report_html"] or "").strip()]
                if not cands:
                    skipped_nomat += 1
                    continue

                # 3) 대표 키워드 = 검색량이 가장 큰 것 (동률이면 최신)
                cands.sort(key=lambda r: (_volume_of(r["volume_json"]), r["analyzed_date"] or ""),
                           reverse=True)
                head = cands[0]
                keywords = [
                    {"keyword": (r["keyword"] or "").strip(),
                     "volume": _volume_of(r["volume_json"]),
                     "analyzedDate": r["analyzed_date"]}
                    for r in cands
                ]

                # 4) 파일 + 행
                report_hash = generate_report_hash()
                html_filename = f"{report_hash}.html"
                html_path = Path(REPORTS_DIR) / html_filename
                html_path.write_text(head["report_html"], encoding="utf-8")

                title = f"{c['name']} 주간 로직 분석"
                report_data = json.dumps({
                    "generatedBy": "weekly-auto",
                    "weekOf": started.strftime("%Y-%m-%d"),
                    "headKeyword": (head["keyword"] or "").strip(),
                    "keywords": keywords,
                }, ensure_ascii=False)

                try:
                    conn.execute(
                        # ⚠️ created_at 을 명시한다 — 표 기본값이 옛 정의(UTC)라
                        #    2026-08-24 첫 배치가 09:40 KST 에 돌고도 00:40 로 기록됐다.
                        "INSERT INTO reports (client_id, title, keyword, product_url, report_data,"
                        " report_hash, html_filename, status, created_by, is_auto, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,1,datetime('now','localtime'))",
                        (c["id"], title, (head["keyword"] or "").strip(),
                         head["product_url"] or "", report_data, report_hash,
                         html_filename, "generated", 0)
                    )
                    conn.commit()
                except Exception:
                    # DB 실패 시 고아 HTML 제거 (수동 생성 경로와 같은 규칙)
                    html_path.unlink(missing_ok=True)
                    raise
                made += 1

            except Exception as e:
                errors += 1
                logger.error(f"   ❌ 업체 {c['id']} 보고서 실패: {e}")
                continue
    except Exception as e:
        logger.error(f"❌ 주간 보고서 생성 실패: {e}")
    finally:
        conn.close()

    logger.info(
        f"✅ 주간 보고서 완료: 생성 {made}건 · 이미있음 {skipped_dup} · 재료없음 {skipped_nomat} · 실패 {errors}"
    )

    # 생성 직후 정리 — 같은 잡에 묶어 「만들기만 하고 안 지우는」 상태가 생기지 않게 한다.
    try:
        run_weekly_report_retention()
    except Exception as e:
        logger.error(f"❌ 주간 보고서 보관정책 실패: {e}")

    return {"made": made, "skipped_dup": skipped_dup,
            "skipped_no_material": skipped_nomat, "errors": errors}


def run_weekly_report_retention(dry_run: bool = False):
    """업체당 자동 보고서 최근 N주분만 남기고 정리 (DB 행 + HTML 파일).

    ⚠️ 수동 보고서(is_auto=0)는 절대 건드리지 않는다 — 영업 자산이다.
    """
    from reports import resolve_report_file

    conn = _conn()
    removed = files = 0
    try:
        # 업체별로 최신 N건만 남긴다(주 1건이므로 N건 = N주분).
        rows = conn.execute(
            "SELECT id, client_id, report_hash, html_filename FROM reports "
            " WHERE COALESCE(is_auto,0)=1 "
            " ORDER BY client_id, created_at DESC"
        ).fetchall()

        seen = {}
        doomed = []
        for r in rows:
            n = seen.get(r["client_id"], 0) + 1
            seen[r["client_id"]] = n
            if n > AUTO_REPORT_KEEP_WEEKS:
                doomed.append(r)

        if dry_run:
            logger.info(f"[보관정책·미리보기] 삭제 대상 {len(doomed)}건 (보관 {AUTO_REPORT_KEEP_WEEKS}주)")
            return {"would_delete": len(doomed), "keep_weeks": AUTO_REPORT_KEEP_WEEKS}

        for r in doomed:
            try:
                p = resolve_report_file(r["html_filename"])
                if p is not None:
                    p.unlink(missing_ok=True)
                    files += 1
                conn.execute("DELETE FROM reports WHERE id=?", (r["id"],))
                removed += 1
            except Exception as e:
                logger.error(f"   보관정책 개별 실패 (id={r['id']}): {e}")
                continue
        conn.commit()
    finally:
        conn.close()

    if removed:
        logger.info(f"🧹 주간 보고서 정리: {removed}건 삭제 (파일 {files}개, 보관 {AUTO_REPORT_KEEP_WEEKS}주)")
    return {"deleted": removed, "files": files, "keep_weeks": AUTO_REPORT_KEEP_WEEKS}
