"""DB 연결 — Sprint 1은 SQLite(파일 1개, 설치 불필요). 운영 단계에서 PostgreSQL로 교체 가능(코드 동일)."""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 서버 배포 시 DB_PATH 환경변수로 영구 보관 위치 지정(도커 볼륨). 로컬은 기본값.
DB_PATH = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "app.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
