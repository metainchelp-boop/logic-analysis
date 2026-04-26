"""
chat.py — AI 채팅 + 의견함 모듈 v2.0
Claude API 연동, 로직 분석 프로그램 전용 시스템 프롬프트,
DB 데이터 참조형 RAG — 질문에 관련된 분석 데이터를 자동 조회하여 AI 컨텍스트에 주입
#오류/#요청/#의견 태그 자동 감지 → 피드백 테이블 저장
"""
import os
import json
import re
import sqlite3
import logging
import anthropic
from datetime import datetime
from typing import Optional, Dict, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user, require_role, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# ==================== 시스템 프롬프트 ====================
SYSTEM_PROMPT = """당신은 네이버 쇼핑 키워드 분석 분야에서 10년 이상 실무 경험을 쌓은 시니어 마케팅 전문가입니다.
현재 'METAINC 로직 분석 프로그램'의 전담 어드바이저로 활동하고 있습니다.

당신의 말투와 태도:
- 후배 직원에게 편하게 조언하듯 자연스럽고 따뜻하게 말해주세요
- "~하시면 됩니다" 같은 딱딱한 존댓말 대신, "~해보세요", "~하면 좋아요", "제 경험상~" 같은 부드러운 톤을 쓰세요
- 실무 경험에서 우러나온 팁이나 노하우를 자연스럽게 섞어주세요
- 예: "이런 경우는 보통~", "실무에서 자주 보는 패턴인데~", "제가 해보니까~"
- 너무 길게 설명하지 말고, 핵심만 콕콕 짚어주세요
- 이모지는 가끔, 자연스러울 때만 쓰세요
- 불릿포인트나 번호 나열보다는 자연스러운 문장으로 답변하세요

로직 분석 프로그램의 기능 (질문에 답할 때 참고):
- 키워드 분석: 검색량, 경쟁강도, 상품 수, 클릭률 분석
- 순위 추적: 키워드별 네이버 쇼핑 순위 자동 추적 (400위까지)
- 데이터랩: 네이버 쇼핑인사이트 연동 (트렌드, 연령/성별/기기별 분석)
- AI 인사이트: 가격 최적화, 키워드 발굴, 리뷰 감성, 광고 효율, 순위 예측 등 8가지
- 업체 관리: 광고주별 키워드 분석 이력, 보고서 생성
- 사용자 역할: superadmin(전체 관리), manager(담당 업체 관리), viewer(조회 전용, 일 3회)

중요한 답변 원칙:
- 아래에 [참조 데이터]가 제공되면, 반드시 그 실제 데이터를 근거로 답변하세요
- 데이터가 있으면 "우리 시스템 기준으로~", "최근 분석 데이터를 보니까~" 식으로 자연스럽게 인용하세요
- 구체적 수치(검색량, 순위, 경쟁강도 등)를 자연스럽게 언급하면서 인사이트를 덧붙여주세요
- 프로그램 사용법뿐 아니라, 실제 마케팅 실무에서 어떻게 활용하면 효과적인지까지 코멘트해주세요
- 데이터가 없는 질문에는 일반적인 마케팅 노하우로 답변하세요
- 프로그램과 무관한 질문은 부드럽게 로직 분석 관련 이야기로 유도해주세요
- 한국어로 답변하세요

의견/피드백 태그가 포함된 메시지(#오류, #요청, #의견 등)는 프로그램 개선 피드백이니, 공감하면서 "접수했어요, 확인해볼게요" 정도로 자연스럽게 응답하세요.
"""

# ==================== DB 초기화 ====================
def init_chat_db():
    """채팅 이력 + 피드백 테이블 생성"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                content TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                admin_reply TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                resolved_at TEXT
            )
        """)
        conn.commit()
        logger.info("[Chat] DB tables initialized")
    except Exception as e:
        logger.error(f"[Chat] DB init error: {e}")
    finally:
        conn.close()


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ==================== 피드백 태그 감지 ====================
_FEEDBACK_TAGS = {
    "error": ["#오류", "#에러", "#버그", "#error", "#bug"],
    "request": ["#요청", "#기능요청", "#추가요청", "#request"],
    "opinion": ["#의견", "#건의", "#제안", "#개선"],
}


def _detect_feedback(message: str) -> Optional[Dict]:
    """메시지에서 피드백 태그 감지"""
    msg_lower = message.lower()
    for category, tags in _FEEDBACK_TAGS.items():
        for tag in tags:
            if tag in msg_lower:
                return {"category": category, "tag": tag}
    return None


def _save_feedback(user_id: int, username: str, category: str, content: str):
    """피드백을 DB에 저장"""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO chat_feedback (user_id, username, category, content) VALUES (?, ?, ?, ?)",
            (user_id, username, category, content)
        )
        conn.commit()
        logger.info(f"[Chat] 피드백 저장: {username} / {category}")
    except Exception as e:
        logger.error(f"[Chat] 피드백 저장 실패: {e}")
    finally:
        conn.close()


# ==================== 데이터 참조 (RAG) ====================

def _extract_keywords_from_message(message: str) -> List[str]:
    """사용자 메시지에서 잠재적 키워드를 추출"""
    # 따옴표로 감싼 키워드 추출
    quoted = re.findall(r'["\']([^"\']+)["\']', message)
    if quoted:
        return quoted

    # '키워드', '검색어' 뒤의 명사구 추출
    patterns = [
        r'(?:키워드|검색어|상품명?)\s*(?:가|은|는|이|를|을)?\s*["\']?([가-힣a-zA-Z0-9\s]{2,20})["\']?',
        r'["\']([가-힣a-zA-Z0-9\s]{2,20})["\']',
    ]
    for pat in patterns:
        found = re.findall(pat, message)
        if found:
            return [f.strip() for f in found if len(f.strip()) >= 2]

    return []


def _extract_client_names(message: str) -> List[str]:
    """사용자 메시지에서 업체명을 추출"""
    # '업체', '광고주' 뒤의 이름 추출
    patterns = [
        r'(?:업체|광고주|클라이언트|고객사)\s*(?:가|은|는|이|의)?\s*["\']?([가-힣a-zA-Z0-9\s]{2,30})["\']?',
    ]
    for pat in patterns:
        found = re.findall(pat, message)
        if found:
            return [f.strip() for f in found if len(f.strip()) >= 2]
    return []


def _fetch_context_data(message: str) -> str:
    """사용자 메시지를 분석하여 관련 DB 데이터를 조회하고 컨텍스트 문자열 반환"""
    context_parts = []
    conn = _get_conn()

    try:
        # === 1. 키워드 관련 데이터 조회 ===
        keywords = _extract_keywords_from_message(message)
        for kw in keywords[:3]:  # 최대 3개
            # 최근 분석 이력
            rows = conn.execute("""
                SELECT ca.keyword, ca.analysis_json, ca.volume_json, ca.analyzed_date,
                       c.name as client_name
                FROM client_analyses ca
                JOIN clients c ON ca.client_id = c.id
                WHERE ca.keyword LIKE ?
                ORDER BY ca.analyzed_date DESC LIMIT 3
            """, (f"%{kw}%",)).fetchall()

            if rows:
                for r in rows:
                    parts = [f"\n📊 키워드 '{r['keyword']}' 분석 데이터 (업체: {r['client_name']}, 분석일: {r['analyzed_date']}):"]
                    # analysis_json 파싱
                    try:
                        analysis = json.loads(r["analysis_json"]) if r["analysis_json"] else {}
                        if analysis:
                            vol = analysis.get("monthlyPcQcCnt", "-")
                            mob = analysis.get("monthlyMobileQcCnt", "-")
                            comp = analysis.get("compIdx", "-")
                            prod_cnt = analysis.get("totalProductCount", analysis.get("productCount", "-"))
                            parts.append(f"  - PC 검색량: {vol}, 모바일 검색량: {mob}, 경쟁강도: {comp}, 상품 수: {prod_cnt}")
                            # 클릭률 등 추가 데이터
                            pc_ctr = analysis.get("monthlyPcClkCnt", "")
                            mob_ctr = analysis.get("monthlyMobileClkCnt", "")
                            if pc_ctr:
                                parts.append(f"  - PC 클릭수: {pc_ctr}, 모바일 클릭수: {mob_ctr}")
                    except (json.JSONDecodeError, TypeError):
                        pass
                    context_parts.append("\n".join(parts))

            # 순위 이력
            rank_rows = conn.execute("""
                SELECT crh.keyword, crh.rank_position, crh.checked_at, c.name as client_name
                FROM client_rank_history crh
                JOIN clients c ON crh.client_id = c.id
                WHERE crh.keyword LIKE ?
                ORDER BY crh.checked_at DESC LIMIT 5
            """, (f"%{kw}%",)).fetchall()

            if rank_rows:
                rank_info = [f"\n📈 키워드 '{kw}' 최근 순위 추적:"]
                for rr in rank_rows:
                    rank_info.append(f"  - {rr['client_name']}: {rr['rank_position']}위 ({rr['checked_at'][:16]})")
                context_parts.append("\n".join(rank_info))

        # === 2. 업체 관련 데이터 조회 ===
        client_names = _extract_client_names(message)
        for cn in client_names[:2]:  # 최대 2개
            client_row = conn.execute("""
                SELECT id, name, business_name, main_keywords, status
                FROM clients WHERE name LIKE ? OR business_name LIKE ?
                LIMIT 1
            """, (f"%{cn}%", f"%{cn}%")).fetchone()

            if client_row:
                parts = [f"\n🏢 업체 '{client_row['name']}' 정보:"]
                parts.append(f"  - 상호: {client_row['business_name'] or '-'}, 상태: {client_row['status']}")
                if client_row['main_keywords']:
                    parts.append(f"  - 주요 키워드: {client_row['main_keywords']}")

                # 이 업체의 최근 분석 이력
                analyses = conn.execute("""
                    SELECT keyword, analyzed_date FROM client_analyses
                    WHERE client_id = ? ORDER BY analyzed_date DESC LIMIT 5
                """, (client_row['id'],)).fetchall()
                if analyses:
                    kw_list = ", ".join([f"{a['keyword']}({a['analyzed_date']})" for a in analyses])
                    parts.append(f"  - 최근 분석: {kw_list}")

                # 최근 순위
                ranks = conn.execute("""
                    SELECT keyword, rank_position, checked_at
                    FROM client_rank_history
                    WHERE client_id = ? ORDER BY checked_at DESC LIMIT 5
                """, (client_row['id'],)).fetchall()
                if ranks:
                    rank_list = ", ".join([f"{rk['keyword']} {rk['rank_position']}위" for rk in ranks])
                    parts.append(f"  - 최근 순위: {rank_list}")

                context_parts.append("\n".join(parts))

        # === 3. 일반적인 질문이면 전체 현황 요약 제공 ===
        general_triggers = ["현황", "요약", "전체", "몇 개", "총", "업체", "상태", "통계", "어떤 데이터", "분석 현황"]
        if any(t in message for t in general_triggers) and not keywords and not client_names:
            summary = conn.execute("""
                SELECT
                    (SELECT COUNT(*) FROM clients WHERE status = 'active') as active_clients,
                    (SELECT COUNT(DISTINCT keyword) FROM client_analyses) as unique_keywords,
                    (SELECT COUNT(*) FROM client_analyses) as total_analyses,
                    (SELECT COUNT(*) FROM client_rank_history) as total_ranks
            """).fetchone()

            if summary:
                parts = ["\n📋 시스템 현황 요약:"]
                parts.append(f"  - 활성 업체: {summary['active_clients']}개")
                parts.append(f"  - 분석된 고유 키워드: {summary['unique_keywords']}개")
                parts.append(f"  - 총 분석 이력: {summary['total_analyses']}건")
                parts.append(f"  - 순위 추적 기록: {summary['total_ranks']}건")
                context_parts.append("\n".join(parts))

            # 최근 분석된 키워드 TOP 10
            recent = conn.execute("""
                SELECT keyword, COUNT(*) as cnt, MAX(analyzed_date) as last_date
                FROM client_analyses
                GROUP BY keyword ORDER BY last_date DESC LIMIT 10
            """).fetchall()
            if recent:
                parts = ["\n🔥 최근 분석된 키워드 TOP 10:"]
                for i, r in enumerate(recent, 1):
                    parts.append(f"  {i}. {r['keyword']} ({r['cnt']}회 분석, 최근: {r['last_date']})")
                context_parts.append("\n".join(parts))

        # === 4. 경쟁/카테고리 관련 질문 ===
        comp_triggers = ["경쟁", "경쟁사", "경쟁 상품", "순위 비교", "라이벌"]
        if any(t in message for t in comp_triggers) and keywords:
            for kw in keywords[:1]:
                comp_rows = conn.execute("""
                    SELECT cs.rank, cs.product_name, cs.store_name, cs.price,
                           cs.review_count, cs.rating
                    FROM competitor_snapshots cs
                    JOIN tracked_keywords tk ON cs.keyword_id = tk.id
                    WHERE tk.keyword LIKE ?
                    ORDER BY cs.captured_at DESC, cs.rank ASC LIMIT 10
                """, (f"%{kw}%",)).fetchall()

                if comp_rows:
                    parts = [f"\n🏆 '{kw}' 경쟁 상품 TOP 10:"]
                    for cr in comp_rows:
                        price_str = f"{cr['price']:,}원" if cr['price'] else "-"
                        parts.append(f"  {cr['rank']}위. {cr['product_name'][:30]} ({cr['store_name']}) - {price_str}, 리뷰 {cr['review_count'] or 0}개")
                    context_parts.append("\n".join(parts))

    except Exception as e:
        logger.error(f"[Chat] 데이터 조회 오류: {e}")
    finally:
        conn.close()

    if context_parts:
        return "\n\n[참조 데이터 — 로직 분석 프로그램 DB에서 조회된 실제 데이터]\n" + "\n".join(context_parts)
    return ""


# ==================== Claude API 호출 ====================
def _call_claude_sync(messages: list, user_message: str, context_data: str = "") -> str:
    """Claude API 호출 (동기 — anthropic SDK 사용)"""
    if not CLAUDE_API_KEY:
        return "AI 채팅 기능을 사용하려면 관리자가 CLAUDE_API_KEY를 설정해야 합니다. 관리자에게 문의해주세요."

    # 최근 10개 메시지만 컨텍스트로 전송 (비용 절감)
    recent_messages = messages[-10:] if len(messages) > 10 else messages

    api_messages = []
    for m in recent_messages:
        api_messages.append({"role": m["role"], "content": m["content"]})

    # 사용자 메시지에 데이터 컨텍스트를 주입
    enriched_message = user_message
    if context_data:
        enriched_message = f"{user_message}\n\n{context_data}"

    api_messages.append({"role": "user", "content": enriched_message})

    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=api_messages,
        )

        if resp.content:
            return resp.content[0].text
        return "응답을 처리할 수 없습니다."

    except anthropic.APITimeoutError:
        return "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요."
    except anthropic.APIError as e:
        logger.error(f"[Chat] Claude API error: {e}")
        return "AI 응답을 받지 못했습니다. 잠시 후 다시 시도해주세요."
    except Exception as e:
        logger.error(f"[Chat] Claude API exception: {e}")
        return "AI 서비스 연결 오류가 발생했습니다. 잠시 후 다시 시도해주세요."


# ==================== API 엔드포인트 ====================

class ChatRequest(BaseModel):
    message: str


class FeedbackUpdateRequest(BaseModel):
    status: Optional[str] = None
    admin_reply: Optional[str] = None


@router.post("/send")
async def send_message(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    """채팅 메시지 전송 + AI 응답"""
    user_id = current_user["id"]
    username = current_user["username"]
    message = req.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="메시지를 입력해주세요.")

    if len(message) > 2000:
        raise HTTPException(status_code=400, detail="메시지는 2000자 이내로 작성해주세요.")

    conn = _get_conn()
    try:
        # 사용자 메시지 저장
        conn.execute(
            "INSERT INTO chat_messages (user_id, username, role, content) VALUES (?, ?, 'user', ?)",
            (user_id, username, message)
        )
        conn.commit()

        # 피드백 태그 감지
        feedback = _detect_feedback(message)
        feedback_saved = False
        if feedback:
            _save_feedback(user_id, username, feedback["category"], message)
            feedback_saved = True

        # 최근 대화 이력 조회 (이 사용자의 것만)
        rows = conn.execute(
            "SELECT role, content FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT 20",
            (user_id,)
        ).fetchall()
        history = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

        # DB에서 관련 데이터 조회 (RAG)
        context_data = _fetch_context_data(message)
        if context_data:
            logger.info(f"[Chat] RAG 데이터 주입: {len(context_data)}자")

        # Claude API 호출 (데이터 컨텍스트 포함)
        ai_response = _call_claude_sync(history[:-1], message, context_data)

        # 피드백 접수 안내 추가
        if feedback_saved:
            category_labels = {"error": "오류 신고", "request": "기능 요청", "opinion": "의견/건의"}
            label = category_labels.get(feedback["category"], "의견")
            ai_response = f"✅ **{label}**이(가) 정상적으로 접수되었습니다. 관리자가 확인 후 처리할 예정입니다.\n\n---\n\n{ai_response}"

        # AI 응답 저장
        conn.execute(
            "INSERT INTO chat_messages (user_id, username, role, content) VALUES (?, ?, 'assistant', ?)",
            (user_id, username, ai_response)
        )
        conn.commit()

        return {
            "success": True,
            "response": ai_response,
            "feedbackSaved": feedback_saved,
        }

    except Exception as e:
        logger.error(f"[Chat] send error: {e}")
        return {"success": False, "detail": str(e)}
    finally:
        conn.close()


@router.get("/history")
async def get_chat_history(current_user: dict = Depends(get_current_user)):
    """현재 사용자의 채팅 이력 조회 (최근 50건)"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT 50",
            (current_user["id"],)
        ).fetchall()
        messages = [dict(r) for r in reversed(rows)]
        return {"success": True, "data": messages}
    finally:
        conn.close()


@router.get("/feedback")
async def get_feedback_list(
    status: Optional[str] = None,
    current_user: dict = Depends(require_role(UserRole.MANAGER))
):
    """피드백 목록 조회 (manager 이상)"""
    conn = _get_conn()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM chat_feedback WHERE status = ? ORDER BY created_at DESC LIMIT 100",
                (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chat_feedback ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return {"success": True, "data": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.put("/feedback/{feedback_id}")
async def update_feedback(
    feedback_id: int,
    req: FeedbackUpdateRequest,
    current_user: dict = Depends(require_role(UserRole.MANAGER))
):
    """피드백 상태 업데이트 (manager 이상)"""
    conn = _get_conn()
    try:
        updates = []
        params = []
        if req.status:
            updates.append("status = ?")
            params.append(req.status)
            if req.status == "resolved":
                updates.append("resolved_at = datetime('now','localtime')")
        if req.admin_reply is not None:
            updates.append("admin_reply = ?")
            params.append(req.admin_reply)

        if not updates:
            raise HTTPException(status_code=400, detail="변경할 내용이 없습니다.")

        params.append(feedback_id)
        conn.execute(f"UPDATE chat_feedback SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.get("/feedback/stats")
async def get_feedback_stats(current_user: dict = Depends(require_role(UserRole.MANAGER))):
    """피드백 통계 (manager 이상)"""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT
                category,
                status,
                COUNT(*) as cnt
            FROM chat_feedback
            GROUP BY category, status
        """).fetchall()

        stats = {"total": 0, "pending": 0, "resolved": 0, "byCategory": {}}
        for r in rows:
            cat = r["category"]
            st = r["status"]
            cnt = r["cnt"]
            stats["total"] += cnt
            if st == "pending":
                stats["pending"] += cnt
            elif st == "resolved":
                stats["resolved"] += cnt
            if cat not in stats["byCategory"]:
                stats["byCategory"][cat] = 0
            stats["byCategory"][cat] += cnt

        return {"success": True, "data": stats}
    finally:
        conn.close()
