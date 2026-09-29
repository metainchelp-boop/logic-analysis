"""앱 진입점 — API(/api) + 정적 화면(/) 서빙."""
import logging
import os
import pathlib
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from . import cors_policy, seed
from .routers import auth, clients, insights, erp, naver

Base.metadata.create_all(bind=engine)

# 가벼운 마이그레이션 — 기존 테이블에 새 컬럼 추가(이미 있으면 무시)
from sqlalchemy import text as _text  # noqa: E402

with engine.connect() as _conn:
    for _ddl in (
        "ALTER TABLE clients ADD COLUMN delete_requested_by INTEGER",
        "ALTER TABLE clients ADD COLUMN delete_requested_at TEXT",
        "ALTER TABLE clients ADD COLUMN contract_end TEXT",
        "ALTER TABLE clients ADD COLUMN biz_reg_name TEXT",
        "ALTER TABLE clients ADD COLUMN erp_possibility_id INTEGER",
        "ALTER TABLE clients ADD COLUMN sales_manager TEXT",
        "ALTER TABLE clients ADD COLUMN db_grade TEXT",
        # 성능: 광고주×채널 최신 스냅샷 조회(스펜딩·월별 집계 핫패스) 복합 인덱스
        "CREATE INDEX IF NOT EXISTS ix_chmetric_client_channel_id "
        "ON channel_metrics(client_id, channel, id)",
    ):
        try:
            _conn.execute(_text(_ddl))
            _conn.commit()
        except Exception:
            pass  # 컬럼 이미 존재

app = FastAPI(title="메타 광고주 통합 대시보드 API")
# 다른 사이트 화면의 호출(CORS) — 기본은 아무 곳에도 열지 않는다(S0 · 예전엔 모든 사이트 *).
# 꼭 열어야 하면 CORS_ALLOW_ORIGINS 에 정확한 주소만(cors_policy 설명) · 로그인 토큰은 머리로만 싣으므로 쿠키 허용 없음.
_cors_origins, _cors_dropped = cors_policy.allowed_origins(os.environ.get("CORS_ALLOW_ORIGINS"))
if _cors_dropped:
    logging.getLogger("app.main").warning("CORS_ALLOW_ORIGINS — 모양이 틀려 버린 값 %d개(* · 경로 포함 등)", _cors_dropped)
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )

app.include_router(auth.router, prefix="/api")
app.include_router(clients.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(erp.router, prefix="/api")
# 네이버 관제(/naver/ · /api/naver-auto) — 스위치 NAVER_AUTO_WEB=on 일 때만 · 꺼지면 라우트가 맞지 않아 없는 주소와 같은 답(GET·HEAD 404 · 그 밖 405).
# 정적 마운트(맨 끝)보다 먼저 받아야 한다(설계 M6) — 이 줄을 app.mount 아래로 옮기지 말 것.
app.include_router(naver.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ad-dashboard", "sprint": 1}


seed.run()

# 정기 자동수집 스케줄러(매일 06:00 KST, 워커 1개만)
from . import collector  # noqa: E402

collector.start_scheduler()

# 프론트(가벼운 화면) 서빙 — API 라우트보다 뒤에 mount
_static = pathlib.Path(__file__).resolve().parent.parent / "static"


# 광고주 자가 키 입력 공개 페이지 (/connect/<token>) — 정적 mount보다 먼저 등록
from fastapi.responses import FileResponse  # noqa: E402


@app.get("/connect/{token}")
def connect_page(token: str):
    return FileResponse(str(_static / "connect.html"))


# 앱 셸(index.html)은 캐시 금지 — 배포 후 그냥 새로고침(F5)만 해도 최신 화면이 뜨게.
# (모든 화면 코드가 index.html 안에 인라인이므로 이 파일만 no-store면 충분)
_NOCACHE = {"Cache-Control": "no-store, must-revalidate"}


@app.get("/")
@app.get("/index.html")
def index_page():
    return FileResponse(str(_static / "index.html"), headers=_NOCACHE)


app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
