"""앱 진입점 — API(/api) + 정적 화면(/) 서빙."""
import pathlib
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from . import seed
from .routers import auth, clients, insights, erp

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(clients.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(erp.router, prefix="/api")


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
