"""
FastAPI Report Generation Module for 로직분석
Generates shareable HTML reports from keyword analysis data
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from auth import get_current_user, require_role


# Configuration
DB_PATH = os.getenv("DB_PATH", "logic_analysis.db")
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)


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
    conn.row_factory = sqlite3.Row
    return conn


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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
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

    conn.commit()
    conn.close()


def generate_report_hash() -> str:
    """Generate unique report hash for public sharing"""
    return hashlib.md5(f"{uuid.uuid4()}{datetime.now()}".encode()).hexdigest()[:16]


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
            rank = product.get("rank", idx)
            title = product.get("title", "제품명 없음")
            price = product.get("price", "가격 정보 없음")
            merchant = product.get("merchant", "판매처 미확인")
            sales = product.get("sales", 0)
            rating = product.get("rating", 0.0)

            # Format price
            try:
                if isinstance(price, str):
                    price_text = price
                else:
                    price_text = f"₩{int(price):,}"
            except:
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
            <div class="footer-brand">로직분석 by 메타인크</div>
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


@router.on_event("startup")
async def startup():
    """Initialize database on startup"""
    init_reports_db()


@router.post("/generate")
async def generate_report(
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
            # Optionally fetch client name from database
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM clients WHERE id = ?", (request.client_id,))
            result = cursor.fetchone()
            if result:
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
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO reports (
                client_id, title, keyword, product_url, report_data,
                report_hash, html_filename, status, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
async def list_reports(
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

        # Build query
        where_clauses = ["created_by = ?"]
        params = [current_user["id"]]

        if client_id:
            where_clauses.append("client_id = ?")
            params.append(client_id)

        if search:
            where_clauses.append("(keyword LIKE ? OR title LIKE ?)")
            search_term = f"%{search}%"
            params.extend([search_term, search_term])

        where_clause = " AND ".join(where_clauses)

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


@router.get("/{report_id}")
async def get_report(
    report_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Get report metadata by ID"""
    try:
        conn = get_db()
        cursor = conn.cursor()

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
async def view_public_report(report_hash: str):
    """
    Public report view (NO AUTHENTICATION REQUIRED)
    Returns HTML content and increments view count
    """
    try:
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

        # Read HTML file
        html_path = REPORTS_DIR / report["html_filename"]

        if not html_path.exists():
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
async def delete_report(
    report_id: int,
    current_user: dict = Depends(get_current_user),
    role: str = Depends(lambda: require_role(["admin", "manager"]))
):
    """
    Delete a report (admin/manager only)
    Removes both database record and HTML file
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Get report
        cursor.execute("""
            SELECT id, html_filename FROM reports WHERE id = ?
        """, (report_id,))

        report = cursor.fetchone()

        if not report:
            raise HTTPException(
                status_code=404,
                detail={"success": False, "message": "보고서를 찾을 수 없습니다."}
            )

        # Delete HTML file
        html_path = REPORTS_DIR / report["html_filename"]
        if html_path.exists():
            html_path.unlink()

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


# Mount static files for serving HTML reports
def mount_reports_static(app):
    """
    Call this function in your main FastAPI app to mount the reports static files
    Example in main.py:
        from backend_reports import mount_reports_static
        mount_reports_static(app)
    """
    app.mount("/api/reports/static", StaticFiles(directory="reports"), name="reports")
