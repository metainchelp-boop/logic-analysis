"""
FastAPI Report Generation Module for 로직분석
Generates shareable HTML reports from keyword analysis data
"""

import sqlite3
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import hashlib
import uuid
import html as html_module


# ===== 인메모리 레이트 리밋 (공개 보고서 조회용) =====
_view_tracker = defaultdict(list)

def _check_view_rate(ip: str, limit: int = 30, window_sec: int = 60) -> bool:
    """IP 기준 분당 최대 limit회 허용. 초과 시 False 반환."""
    now = datetime.now()
    cutoff = now - timedelta(seconds=window_sec)
    _view_tracker[ip] = [t for t in _view_tracker[ip] if t > cutoff]
    if len(_view_tracker[ip]) >= limit:
        return False
    _view_tracker[ip].append(now)
    # 오래된 IP 엔트리 정리 (메모리 누적 방지)
    if len(_view_tracker) > 1000:
        stale_ips = [k for k, v in _view_tracker.items() if not v or v[-1] < cutoff]
        for k in stale_ips:
            del _view_tracker[k]
    return True

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from auth import get_current_user, require_role


# Configuration
logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")

# 보고서 HTML 저장 위치.
# ⚠️ 종전 값은 상대경로 Path("reports") = 컨테이너 안 /app/reports 였는데,
#    docker-compose 가 마운트하는 볼륨은 ./data:/app/data 하나뿐이다.
#    즉 배포로 컨테이너가 새로 만들어질 때마다 HTML 파일이 통째로 사라지고,
#    reports 행(DB=/app/data)만 남아 /view/{hash} 가 404「보고서 파일을 찾을 수
#    없습니다」로 죽는다. reports 표가 0건이라 여태 아무도 못 겪었을 뿐이다.
#    → 마운트된 데이터 볼륨 아래로 옮긴다(주간 자동 보고서는 이 위에서 산다).
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", str(Path(DB_PATH).parent / "reports")))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# 옛 위치. 읽기에만 쓴다(구버전이 남긴 파일이 있으면 계속 열리도록).
LEGACY_REPORTS_DIR = Path("reports")


def resolve_report_file(html_filename: str) -> Optional[Path]:
    """보고서 HTML 실제 경로 — 새 위치 우선, 없으면 옛 위치."""
    if not html_filename:
        return None
    for base in (REPORTS_DIR, LEGACY_REPORTS_DIR):
        try:
            cand = base / html_filename
            if cand.exists():
                return cand
        except Exception:
            continue
    return None


# Pydantic Models
class ReportGenerateRequest(BaseModel):
    keyword: str
    product_url: Optional[str] = ""
    client_id: Optional[int] = None
    title: Optional[str] = None
    data: Optional[Dict[str, Any]] = None  # Analysis data from frontend


class ReportListQuery(BaseModel):
    page: int = 1
    per_page: int = 20
    client_id: Optional[int] = None
    search: Optional[str] = None


class ReportResponse(BaseModel):
    id: int
    title: str
    keyword: str
    product_url: str
    status: str
    views: int
    report_hash: str
    created_at: str
    created_by: int


class ErrorResponse(BaseModel):
    success: bool = False
    message: str


# Database Functions
def get_db():
    """Get database connection with WAL mode and Row factory"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # 쓰기 잠금 시 즉시 실패 대신 최대 30초 대기
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_reports_created_at_to_kst(conn, cursor):
    """기존 행의 created_at(UTC) 을 KST 로 1회 보정.

    ⚠️ `datetime(created_at, 'localtime')` 을 쓴다 — 「+9시간」을 박지 않는다.
       서버 시간대가 바뀌어도 규칙이 따라가고, 서머타임 같은 예외도 OS 가 판단한다.
    ⚠️ 1회성 마커(_app_migrations)로 보호 — 두 번 돌면 9시간이 두 번 더해진다.
    ⚠️ 이 시점의 모든 행은 옛 UTC 기본값으로 들어간 것이다(신규 INSERT 는 이미 KST 명시).
    """
    FLAG = "reports_created_at_kst_2026_08_26"
    try:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS _app_migrations "
            "(key TEXT PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now','localtime')))")
        if cursor.execute("SELECT 1 FROM _app_migrations WHERE key=?", (FLAG,)).fetchone():
            return
        n = cursor.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        if n:
            cursor.execute("UPDATE reports SET created_at = datetime(created_at, 'localtime')")
            logger.info(f"[reports] created_at UTC→KST 보정 {n}행 (1회성)")
        cursor.execute("INSERT OR REPLACE INTO _app_migrations(key) VALUES(?)", (FLAG,))
        conn.commit()
    except Exception as e:
        # 보정 실패가 부팅을 막지 않는다 — 시각 표시만 어긋난 채 서비스는 정상 동작한다
        logger.warning(f"[reports] created_at 보정 건너뜀: {e}")


def init_reports_db():
    """Initialize reports table with indexes"""
    conn = get_db()
    cursor = conn.cursor()

    # Create reports table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            title TEXT NOT NULL,
            keyword TEXT NOT NULL,
            product_url TEXT DEFAULT '',
            report_data TEXT NOT NULL,
            report_hash TEXT UNIQUE NOT NULL,
            html_filename TEXT DEFAULT '',
            status TEXT DEFAULT 'generated',
            views INTEGER DEFAULT 0,
            created_by INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (client_id) REFERENCES clients(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)

    # Create indexes for better query performance
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_client_id
        ON reports(client_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_created_by
        ON reports(created_by)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_keyword
        ON reports(keyword)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_report_hash
        ON reports(report_hash)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_status
        ON reports(status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_created_at
        ON reports(created_at)
    """)

    # ⚠️ created_at 은 **KST 로 저장**한다 — 표 기본값에 기대지 않고 INSERT 에서 명시한다.
    #    이 표는 옛 정의(`DEFAULT CURRENT_TIMESTAMP` = UTC)로 이미 만들어져 있어,
    #    아래 CREATE TABLE 의 `datetime('now','localtime')` 은 **한 번도 적용된 적이 없다**
    #    (`CREATE TABLE IF NOT EXISTS` 는 기존 표를 고치지 않는다).
    #    2026-08-24 첫 주간 배치가 09:40 KST 에 돌았는데 00:40 로 기록된 것이 그 결과다.
    #    ⇒ SQLite 는 컬럼 기본값을 바꿀 수 없으므로(표 재생성 필요) **INSERT 에서 명시**하는 쪽을 택했다.
    #       표를 다시 만드는 것보다 안전하고, 새 서버에서는 CREATE 정의가 그대로 맞다.
    #    ⚠️ 앞으로 reports 에 INSERT 를 추가하는 곳은 반드시 created_at 을 함께 넣을 것.
    _migrate_reports_created_at_to_kst(conn, cursor)

    # 마이그레이션: is_auto — 주간 자동 생성분과 영업용 수동 보고서를 가른다.
    # ⚠️ 자동 생성 기능과 반드시 같은 배포에 있어야 한다(①메타 전산 요청·2026-08-20).
    #    표시 없이 자동 생성만 먼저 켜면 첫 회차 수백 건이 표시 없이 들어가고,
    #    나중에 컬럼을 붙이면 DEFAULT 0 때문에 그 행들이 전부 '수동'으로 둔갑한다.
    #    되돌릴 근거가 남지 않으므로 나눠서 배포하지 않는다.
    try:
        cursor.execute("SELECT is_auto FROM reports LIMIT 1")
    except Exception:
        cursor.execute("ALTER TABLE reports ADD COLUMN is_auto INTEGER NOT NULL DEFAULT 0")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_is_auto
        ON reports(is_auto, client_id, created_at)
    """)

    conn.commit()
    conn.close()


def generate_report_hash() -> str:
    """Generate unique report hash for public sharing"""
    return hashlib.sha256(f"{uuid.uuid4()}{datetime.now()}".encode()).hexdigest()[:32]


def format_korean_number(num: int) -> str:
    """Format number with Korean-style separators (e.g., 70,500)"""
    if num is None:
        return "0"
    return f"{num:,}".replace(",", ",")


def generate_report_html(
    report_data: Dict[str, Any],
    keyword: str,
    product_url: str = "",
    client_name: str = "클라이언트"
) -> str:
    """
    Generate beautiful, professional HTML report with inline CSS

    Args:
        report_data: Analysis data containing keyword metrics and competitor info
        keyword: Search keyword
        product_url: Product URL (optional)
        client_name: Client name for header

    Returns:
        Complete HTML document as string
    """

    # XSS 방지 — 사용자 입력값 이스케이프
    keyword = html_module.escape(keyword)
    product_url = html_module.escape(product_url)
    client_name = html_module.escape(client_name)

    # Extract data from report_data, with sensible defaults
    monthly_search = report_data.get("monthly_search_volume", 0)
    pc_ratio = report_data.get("pc_ratio", 50)
    mobile_ratio = report_data.get("mobile_ratio", 50)
    competition_score = report_data.get("competition_score", 50)
    competition_level = report_data.get("competition_level", "중간")
    top_products = report_data.get("top_products", [])
    current_rank = report_data.get("current_rank", "-")
    current_price = report_data.get("current_price", "-")

    # Generate timestamp
    now = datetime.now()
    report_date = now.strftime("%Y년 %m월 %d일")
    report_time = now.strftime("%H:%M")

    # Build top products table
    products_html = ""
    if top_products:
        for idx, product in enumerate(top_products[:20], 1):
            # 외부(네이버) 데이터는 타입이 불안정 → 강제 변환(미변환 시 리포트 생성 500)
            try:
                rank = int(product.get("rank", idx))
            except (ValueError, TypeError):
                rank = idx
            try:
                rating = float(product.get("rating", 0.0) or 0)
            except (ValueError, TypeError):
                rating = 0.0
            # XSS 방지: 상품명/판매처는 리포트 HTML에 그대로 삽입되므로 이스케이프
            title = html_module.escape(str(product.get("title", "제품명 없음")))
            price = product.get("price", "가격 정보 없음")
            merchant = html_module.escape(str(product.get("merchant", "판매처 미확인")))
            sales = product.get("sales", 0)

            # Format price
            try:
                if isinstance(price, str):
                    price_text = price
                else:
                    price_text = f"₩{int(price):,}"
            except (ValueError, TypeError):
                price_text = price

            # Determine rank color
            if rank <= 3:
                rank_color = "#FF6B6B"
            elif rank <= 10:
                rank_color = "#FF9F43"
            else:
                rank_color = "#95A5A6"

            products_html += f"""
            <tr>
                <td style="text-align: center; font-weight: bold; color: {rank_color};">{rank}</td>
                <td>{title}</td>
                <td style="text-align: right;">{price_text}</td>
                <td style="text-align: center;">{merchant}</td>
                <td style="text-align: center;">
                    <span style="background: #F0E68C; padding: 4px 8px; border-radius: 4px; font-size: 12px;">
                        ★ {rating:.1f}
                    </span>
                </td>
            </tr>
            """
    else:
        products_html = '<tr><td colspan="5" style="text-align: center; color: #999;">분석 데이터가 없습니다.</td></tr>'

    # Build competition analysis
    competition_color = "#FF6B6B" if competition_score > 70 else "#FF9F43" if competition_score > 40 else "#51CF66"

    # Build strategy tips
    strategy_tips = """
    <div style="background: #F8F9FA; border-left: 4px solid #7C3AED; padding: 16px; margin-bottom: 16px; border-radius: 4px;">
        <h4 style="margin: 0 0 12px 0; color: #2C3E50;">📊 1페이지 진입 전략</h4>
        <ul style="margin: 0; padding-left: 20px; color: #555;">
            <li style="margin-bottom: 8px;"><strong>상품명 최적화:</strong> 검색 키워드를 포함한 명확한 상품명 작성</li>
            <li style="margin-bottom: 8px;"><strong>가격 경쟁력:</strong> 상위 순위 제품의 가격대를 분석하여 적정 가격 책정</li>
            <li style="margin-bottom: 8px;"><strong>리뷰 관리:</strong> 고객 만족도를 높이고 정기적인 후기 수집</li>
            <li style="margin-bottom: 8px;"><strong>판매량 증대:</strong> 프로모션과 광고를 통해 초기 판매량 확보</li>
            <li><strong>키워드 광고:</strong> 상위 3위 진입 시까지 검색광고 활용</li>
        </ul>
    </div>
    """

    # Complete HTML document with inline CSS
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{keyword} - 로직분석 보고서</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', sans-serif;
            line-height: 1.6;
            color: #2C3E50;
            background: #F5F7FA;
        }}

        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        }}

        /* Header */
        .header {{
            background: linear-gradient(135deg, #7C3AED 0%, #A78BFA 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
            position: relative;
            overflow: hidden;
        }}

        .header::before {{
            content: '';
            position: absolute;
            top: 0;
            right: 0;
            width: 200px;
            height: 200px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 50%;
            transform: translate(50%, -50%);
        }}

        .header-content {{
            position: relative;
            z-index: 1;
        }}

        .logo {{
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 16px;
            text-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        }}

        .logo::before {{
            content: '📊 ';
        }}

        .report-title {{
            font-size: 32px;
            font-weight: 700;
            margin: 12px 0;
            word-break: break-word;
        }}

        .report-keyword {{
            font-size: 18px;
            opacity: 0.95;
            margin-bottom: 8px;
        }}

        .report-meta {{
            font-size: 13px;
            opacity: 0.85;
            margin-top: 12px;
        }}

        /* Content */
        .content {{
            padding: 40px 30px;
        }}

        .section {{
            margin-bottom: 40px;
        }}

        .section-title {{
            font-size: 20px;
            font-weight: 700;
            color: #2C3E50;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 3px solid #7C3AED;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        /* Metrics Grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .metric-card {{
            background: linear-gradient(135deg, #F5F7FA 0%, #EEF2FF 100%);
            border: 1px solid #E5E7EB;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            transition: transform 0.3s ease;
        }}

        .metric-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 4px 12px rgba(124, 58, 237, 0.1);
        }}

        .metric-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            margin-bottom: 8px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }}

        .metric-value {{
            font-size: 28px;
            font-weight: 700;
            color: #7C3AED;
            margin-bottom: 4px;
        }}

        .metric-unit {{
            font-size: 12px;
            color: #999;
        }}

        /* Chart Simulation */
        .chart-container {{
            background: #F8F9FA;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }}

        .ratio-bar {{
            display: flex;
            height: 40px;
            border-radius: 4px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}

        .ratio-segment {{
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 600;
            color: white;
        }}

        .pc-ratio {{
            background: linear-gradient(90deg, #7C3AED 0%, #A78BFA 100%);
        }}

        .mobile-ratio {{
            background: linear-gradient(90deg, #F59E0B 0%, #FBBF24 100%);
        }}

        .ratio-label {{
            margin-top: 12px;
            font-size: 13px;
            color: #666;
            display: flex;
            justify-content: space-between;
        }}

        /* Score Badge */
        .score-badge {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 80px;
            height: 80px;
            border-radius: 50%;
            font-size: 32px;
            font-weight: 700;
            color: white;
            margin: 0 auto 16px;
        }}

        .score-high {{
            background: linear-gradient(135deg, #FF6B6B 0%, #FF8E72 100%);
        }}

        .score-medium {{
            background: linear-gradient(135deg, #FF9F43 0%, #FFA502 100%);
        }}

        .score-low {{
            background: linear-gradient(135deg, #51CF66 0%, #69DB7C 100%);
        }}

        /* Table */
        .table-container {{
            overflow-x: auto;
            margin-bottom: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
        }}

        th {{
            background: linear-gradient(135deg, #7C3AED 0%, #A78BFA 100%);
            color: white;
            padding: 14px 12px;
            text-align: left;
            font-weight: 600;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        td {{
            padding: 14px 12px;
            border-bottom: 1px solid #E5E7EB;
            font-size: 13px;
        }}

        tr:nth-child(even) {{
            background: #F9FAFB;
        }}

        tr:hover {{
            background: #F3E8FF;
        }}

        /* Footer */
        .footer {{
            background: linear-gradient(135deg, #2C3E50 0%, #34495E 100%);
            color: white;
            padding: 30px;
            text-align: center;
            font-size: 12px;
            border-top: 4px solid #7C3AED;
        }}

        .footer-brand {{
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 8px;
        }}

        .footer-text {{
            opacity: 0.85;
            margin-bottom: 4px;
        }}

        /* Print Styles */
        @media print {{
            body {{
                background: white;
            }}

            .container {{
                box-shadow: none;
                max-width: 100%;
            }}

            .header {{
                page-break-after: avoid;
            }}

            .section {{
                page-break-inside: avoid;
            }}

            .metric-card {{
                box-shadow: none;
                border: 1px solid #DDD;
            }}

            table {{
                page-break-inside: avoid;
            }}
        }}

        /* Responsive */
        @media (max-width: 768px) {{
            .header {{
                padding: 30px 20px;
            }}

            .report-title {{
                font-size: 24px;
            }}

            .content {{
                padding: 24px 16px;
            }}

            .metrics-grid {{
                grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
                gap: 12px;
            }}

            .metric-card {{
                padding: 16px;
            }}

            .metric-value {{
                font-size: 22px;
            }}

            .section-title {{
                font-size: 18px;
            }}

            table {{
                font-size: 12px;
            }}

            th, td {{
                padding: 10px 8px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div class="header-content">
                <div class="logo">로직분석</div>
                <h1 class="report-title">{keyword}</h1>
                <p class="report-keyword">네이버 쇼핑 키워드 분석 보고서</p>
                <p class="report-meta">
                    {client_name} | {report_date} {report_time}
                </p>
            </div>
        </div>

        <!-- Content -->
        <div class="content">
            <!-- Section 1: 키워드 검색량 -->
            <div class="section">
                <h2 class="section-title">📈 키워드 검색량</h2>

                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-label">월간 검색량</div>
                        <div class="metric-value">{format_korean_number(monthly_search)}</div>
                        <div class="metric-unit">회/월</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">PC 검색</div>
                        <div class="metric-value">{pc_ratio}%</div>
                        <div class="metric-unit">검색 비율</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">모바일 검색</div>
                        <div class="metric-value">{mobile_ratio}%</div>
                        <div class="metric-unit">검색 비율</div>
                    </div>
                </div>

                <div class="chart-container">
                    <p style="margin-bottom: 12px; font-weight: 600; color: #2C3E50;">검색 기기별 비율</p>
                    <div class="ratio-bar">
                        <div class="ratio-segment pc-ratio" style="width: {pc_ratio}%;">PC {pc_ratio}%</div>
                        <div class="ratio-segment mobile-ratio" style="width: {mobile_ratio}%;">모바일 {mobile_ratio}%</div>
                    </div>
                    <div class="ratio-label">
                        <span>PC 중심</span>
                        <span>모바일 중심</span>
                    </div>
                </div>
            </div>

            <!-- Section 2: 경쟁강도 분석 -->
            <div class="section">
                <h2 class="section-title">⚔️ 경쟁강도 분석</h2>

                <div style="text-align: center; margin-bottom: 20px;">
                    <div class="score-badge score-{'high' if competition_score > 70 else 'medium' if competition_score > 40 else 'low'}">
                        {competition_score}
                    </div>
                    <p style="font-size: 18px; font-weight: 600; color: #2C3E50;">{competition_level} 경쟁</p>
                </div>

                <div style="background: #F8F9FA; border-radius: 8px; padding: 20px;">
                    <p style="color: #666; line-height: 1.8;">
                        <strong>경쟁강도:</strong> 이 키워드의 경쟁강도는 <strong style="color: {competition_color};">{competition_level}</strong> 수준입니다.
                        경쟁강도가 낮을수록 신규 판매자 진입이 유리하며, 높을수록 브랜드 가치와 고객 만족도가 중요합니다.
                    </p>
                </div>
            </div>

            <!-- Section 3: 순위 현황 -->
            <div class="section">
                <h2 class="section-title">🏆 순위 현황</h2>

                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-label">현재 순위</div>
                        <div class="metric-value">{current_rank}</div>
                        <div class="metric-unit">위</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">상품 가격</div>
                        <div class="metric-value" style="font-size: 20px;">{current_price}</div>
                        <div class="metric-unit">원</div>
                    </div>
                </div>

                {f'<p style="color: #666; background: #F8F9FA; padding: 16px; border-radius: 8px;">상품 URL: <code style="background: white; padding: 4px 8px; border-radius: 4px; font-family: monospace;">{product_url}</code></p>' if product_url else '<p style="color: #999; background: #F8F9FA; padding: 16px; border-radius: 8px; text-align: center;">상품 URL 정보가 제공되지 않았습니다.</p>'}
            </div>

            <!-- Section 4: 경쟁사 비교 분석 -->
            <div class="section">
                <h2 class="section-title">🔍 경쟁사 비교 분석</h2>

                <p style="color: #666; margin-bottom: 16px; font-size: 13px;">
                    상위 20개 제품의 순위, 가격, 판매처, 별점 정보를 통해 경쟁 상황을 파악하세요.
                </p>

                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th style="width: 50px;">순위</th>
                                <th>제품명</th>
                                <th style="width: 120px;">가격</th>
                                <th style="width: 100px;">판매처</th>
                                <th style="width: 80px;">평점</th>
                            </tr>
                        </thead>
                        <tbody>
                            {products_html}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Section 5: 1페이지 진입 전략 -->
            <div class="section">
                <h2 class="section-title">🎯 1페이지 진입 전략</h2>

                {strategy_tips}
            </div>
        </div>

        <!-- Footer -->
        <div class="footer">
            <div class="footer-brand">로직분석 by 메타아이앤씨</div>
            <div class="footer-text">네이버 쇼핑 키워드 분석 및 순위 추적 솔루션</div>
            <div class="footer-text" style="font-size: 11px; opacity: 0.75; margin-top: 12px;">
                이 보고서는 AI 기반 분석으로 생성되었습니다. 정확한 정보는 네이버 쇼핑 검색 결과를 참고하세요.
            </div>
        </div>
    </div>
</body>
</html>"""

    return html


# Create APIRouter
router = APIRouter(prefix="/api/reports", tags=["reports"])


# on_event("startup") 제거 — main.py lifespan에서 init_reports_db() 호출됨


@router.post("/generate")
def generate_report(
    request: ReportGenerateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Generate a new report from analysis data

    Required fields:
    - keyword: Search keyword
    - data: Analysis data dict containing search volume, competition, products, etc.

    Optional fields:
    - product_url: URL of product to analyze
    - client_id: Client ID for tracking
    - title: Report title (defaults to keyword)
    """
    try:
        # Validate required fields
        if not request.keyword or not request.keyword.strip():
            raise HTTPException(
                status_code=400,
                detail={"success": False, "message": "키워드를 입력해주세요."}
            )

        if not request.data:
            raise HTTPException(
                status_code=400,
                detail={
                    "success": False,
                    "message": "분석 데이터(data)가 필요합니다. 프론트엔드에서 분석 결과를 전송해주세요."
                }
            )

        # Generate report hash for public URL
        report_hash = generate_report_hash()

        # Generate HTML content
        title = request.title or request.keyword
        client_name = "클라이언트"

        if request.client_id:
            # 업체 소유권 검증 + 이름 조회
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT name, created_by FROM clients WHERE id = ?", (request.client_id,))
            result = cursor.fetchone()
            if result:
                _is_adm = current_user.get("role") in ("admin", "superadmin")
                if not _is_adm and result["created_by"] != current_user["id"]:
                    conn.close()
                    raise HTTPException(status_code=403, detail={"success": False, "message": "해당 업체에 대한 접근 권한이 없습니다."})
                client_name = result["name"]
            conn.close()

        html_content = generate_report_html(
            report_data=request.data,
            keyword=request.keyword,
            product_url=request.product_url or "",
            client_name=client_name
        )

        # Save HTML file
        html_filename = f"{report_hash}.html"
        html_path = REPORTS_DIR / html_filename

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Save to database
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reports (
                    client_id, title, keyword, product_url, report_data,
                    report_hash, html_filename, status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
            """, (
                request.client_id,
                title,
                request.keyword,
                request.product_url or "",
                json.dumps(request.data, ensure_ascii=False),
                report_hash,
                html_filename,
                "generated",
                current_user["id"]
            ))
            conn.commit()
            report_id = cursor.lastrowid
        except Exception as db_err:
            # DB 실패 시 고아 HTML 파일 제거
            if html_path.exists():
                html_path.unlink(missing_ok=True)
            raise db_err
        finally:
            conn.close()

        return {
            "success": True,
            "message": "보고서가 성공적으로 생성되었습니다.",
            "report": {
                "id": report_id,
                "title": title,
                "keyword": request.keyword,
                "report_hash": report_hash,
                "url": f"/api/reports/view/{report_hash}"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": f"보고서 생성 중 오류가 발생했습니다: {str(e)}"}
        )


@router.get("")
def list_reports(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    client_id: Optional[int] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    List reports with pagination and filtering

    Query parameters:
    - page: Page number (default: 1)
    - per_page: Items per page (default: 20, max: 100)
    - client_id: Filter by client ID
    - search: Search keyword or title
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Build query (관리자는 전체 열람, 일반 유저는 본인 것만)
        _is_adm = current_user.get("role") in ("admin", "superadmin")
        where_clauses = []
        params = []
        if not _is_adm:
            where_clauses.append("created_by = ?")
            params.append(current_user["id"])

        if client_id:
            where_clauses.append("client_id = ?")
            params.append(client_id)

        if search:
            where_clauses.append("(keyword LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')")
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            search_term = f"%{escaped}%"
            params.extend([search_term, search_term])

        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Get total count
        cursor.execute(f"SELECT COUNT(*) as count FROM reports WHERE {where_clause}", params)
        total = cursor.fetchone()["count"]

        # Get reports with pagination
        offset = (page - 1) * per_page
        cursor.execute(f"""
            SELECT id, client_id, title, keyword, product_url, status, views, report_hash, created_at
            FROM reports
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, params + [per_page, offset])

        reports = [dict(row) for row in cursor.fetchall()]
        conn.close()

        total_pages = (total + per_page - 1) // per_page

        return {
            "success": True,
            "reports": reports,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": f"보고서 목록 조회 중 오류가 발생했습니다: {str(e)}"}
        )


# ==================== 전산①(ERP) 소비 경로 ====================
# ⚠️ 계약: 아래 응답 필드 이름·의미는 ① 메타 전산이 광고주 공유 대시보드에서 소비한다.
#    (2026-08-20 합의) 바꾸려면 ①에 사전 통지. 읽기 전용이며 ①은 여기에 쓰지 않는다.
# ⚠️ 라우트 순서 주의 — 반드시 @router.get("/{report_id}") 보다 위에 있어야 한다.
#    아래에 두면 "for-erp" 가 report_id(int) 로 해석돼 422 로 막힌다.

@router.get("/for-erp")
def list_reports_for_erp(
    client_ids: Optional[str] = Query(None, description="쉼표 구분 업체 id. 생략 시 전체"),
    since: Optional[str] = Query(None, description="YYYY-MM-DD. 이 날짜 이후 생성분만"),
    auto_only: bool = Query(True, description="자동 생성분만(전산은 항상 true)"),
    limit: int = Query(2000, ge=1, le=10000),
    current_user: dict = Depends(get_current_user),
):
    """전산①이 주 1회 훑어가는 보고서 목록. 본문 HTML 은 주지 않는다
    (광고주는 기존 공개 주소 /api/reports/view/{hash} 로 연다).

    ⚠️ 권한: 이 경로만 전 업체를 열어 준다. 서비스 계정을 admin 으로 올리지 않는 이유는
    그러면 보고서 삭제·업체 관리까지 함께 열리기 때문이다(최소 권한).
    읽기 전용이고 auto_only 기본값이 True 라 영업용 수동 보고서는 기본적으로 안 나간다.
    """
    try:
        where = ["1=1"]
        params: List[Any] = []

        if auto_only:
            where.append("COALESCE(r.is_auto,0) = 1")

        if client_ids:
            ids = [int(x) for x in str(client_ids).split(",") if str(x).strip().isdigit()]
            if not ids:
                return {"success": True, "reports": []}
            where.append(f"r.client_id IN ({','.join('?' * len(ids))})")
            params.extend(ids)

        if since:
            # 형식이 어긋나면 조용히 무시하지 않고 400 — 전산이 빈 목록을 정상으로 오해하지 않도록.
            try:
                datetime.strptime(since, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail={"success": False, "message": "since 는 YYYY-MM-DD 형식이어야 합니다."},
                )
            where.append("date(r.created_at) >= date(?)")
            params.append(since)

        conn = get_db()
        try:
            rows = conn.execute(
                f"""SELECT r.client_id, r.title, r.keyword, r.report_hash, r.created_at,
                           COALESCE(r.is_auto,0) AS is_auto, r.report_data
                      FROM reports r
                     WHERE {' AND '.join(where)}
                     ORDER BY r.created_at DESC
                     LIMIT ?""",
                (*params, limit),
            ).fetchall()
        finally:
            conn.close()

        base = os.getenv("PUBLIC_BASE_URL", "https://logic.metainc.co.kr").rstrip("/")
        out = []
        for r in rows:
            # keywordCount — 업체당 1건으로 굽느라 어차피 세는 값이라 함께 실어 준다.
            kw_count = None
            try:
                d = json.loads(r["report_data"] or "{}")
                kws = d.get("keywords")
                if isinstance(kws, list):
                    kw_count = len(kws)
            except Exception:
                kw_count = None
            out.append({
                "clientId": r["client_id"],
                "reportHash": r["report_hash"],
                "title": r["title"],
                "keyword": r["keyword"],
                "keywordCount": kw_count,
                "auto": bool(r["is_auto"]),
                "createdAt": r["created_at"],
                "viewUrl": f"{base}/api/reports/view/{r['report_hash']}",
            })
        return {"success": True, "reports": out}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[for-erp] {e}")
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": "보고서 목록 조회 중 오류가 발생했습니다."},
        )


@router.get("/{report_id}")
def get_report(
    report_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Get report metadata by ID"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        _is_adm = current_user.get("role") in ("admin", "superadmin")
        if _is_adm:
            cursor.execute("""
                SELECT id, client_id, title, keyword, product_url, status, views,
                       report_hash, created_at, created_by
                FROM reports
                WHERE id = ?
            """, (report_id,))
        else:
            cursor.execute("""
                SELECT id, client_id, title, keyword, product_url, status, views,
                       report_hash, created_at, created_by
                FROM reports
                WHERE id = ? AND created_by = ?
            """, (report_id, current_user["id"]))

        report = cursor.fetchone()
        conn.close()

        if not report:
            raise HTTPException(
                status_code=404,
                detail={"success": False, "message": "보고서를 찾을 수 없습니다."}
            )

        return {
            "success": True,
            "report": dict(report)
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": f"보고서 조회 중 오류가 발생했습니다: {str(e)}"}
        )


@router.get("/view/{report_hash}")
def view_public_report(report_hash: str, request: Request):
    """
    Public report view (레이트 리밋 적용, 분당 30회 제한)
    Returns HTML content and increments view count
    """
    try:
        # 레이트 리밋 체크
        client_ip = request.client.host if request.client else "unknown"
        if not _check_view_rate(client_ip):
            raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
        conn = get_db()
        cursor = conn.cursor()

        # Get report
        cursor.execute("""
            SELECT id, html_filename, status FROM reports WHERE report_hash = ?
        """, (report_hash,))

        report = cursor.fetchone()

        if not report:
            raise HTTPException(
                status_code=404,
                detail="보고서를 찾을 수 없습니다."
            )

        # Increment view count
        cursor.execute("""
            UPDATE reports SET views = views + 1 WHERE id = ?
        """, (report["id"],))
        conn.commit()
        conn.close()

        # Read HTML file (새 위치 → 옛 위치 순으로 찾는다)
        html_path = resolve_report_file(report["html_filename"])

        if html_path is None:
            raise HTTPException(
                status_code=404,
                detail="보고서 파일을 찾을 수 없습니다."
            )

        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        return HTMLResponse(content=html_content)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"보고서 조회 중 오류가 발생했습니다: {str(e)}"
        )


@router.delete("/{report_id}")
def delete_report(
    report_id: int,
    current_user: dict = Depends(require_role(["admin", "manager"]))
):
    """
    Delete a report (admin/manager only)
    Removes both database record and HTML file
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Get report + 소유권 확인
        cursor.execute("""
            SELECT id, html_filename, created_by FROM reports WHERE id = ?
        """, (report_id,))

        report = cursor.fetchone()

        if not report:
            raise HTTPException(
                status_code=404,
                detail={"success": False, "message": "보고서를 찾을 수 없습니다."}
            )

        # 관리자가 아니면 본인 보고서만 삭제 가능
        _is_adm = current_user.get("role") in ("admin", "superadmin")
        if not _is_adm and report["created_by"] != current_user["id"]:
            raise HTTPException(
                status_code=403,
                detail={"success": False, "message": "다른 직원의 보고서는 삭제할 수 없습니다."}
            )

        # Delete HTML file (옛 위치에 남은 파일도 함께 지운다)
        html_path = resolve_report_file(report["html_filename"])
        if html_path is not None:
            html_path.unlink(missing_ok=True)

        # Delete from database
        cursor.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": "보고서가 삭제되었습니다."
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": f"보고서 삭제 중 오류가 발생했습니다: {str(e)}"}
        )

