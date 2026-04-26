"""
chat.py — AI 채팅 + 의견함 모듈
Claude API 연동, 로직 분석 프로그램 전용 시스템 프롬프트,
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
현재 '로직 분석 프로그램'의 전담 어드바이저로 활동하고 있습니다.

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

답변 원칙:
- 프로그램 사용법뿐 아니라, 실제 마케팅 실무에서 어떻게 활용하면 효과적인지까지 코멘트해주세요
- 데이터 해석 시 단순 수치 설명이 아니라, "이 수치가 의미하는 건~" 식으로 인사이트를 덧붙여주세요
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


# ==================== Claude API 호출 ====================
def _call_claude_sync(messages: list, user_message: str) -> str:
    """Claude API 호출 (동기 — anthropic SDK 사용)"""
    if not CLAUDE_API_KEY:
        return "AI 채팅 기능을 사용하려면 관리자가 CLAUDE_API_KEY를 설정해야 합니다. 관리자에게 문의해주세요."

    # 최근 10개 메시지만 컨텍스트로 전송 (비용 절감)
    recent_messages = messages[-10:] if len(messages) > 10 else messages

    api_messages = []
    for m in recent_messages:
        api_messages.append({"role": m["role"], "content": m["content"]})
    api_messages.append({"role": "user", "content": user_message})

    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
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

        # Claude API 호출
        ai_response = _call_claude_sync(history[:-1], message)

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
