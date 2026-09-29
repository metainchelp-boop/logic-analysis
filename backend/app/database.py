"""DB 연결 — Sprint 1은 SQLite(파일 1개, 설치 불필요). 운영 단계에서 PostgreSQL로 교체 가능(코드 동일)."""
import contextlib
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


@contextlib.contextmanager
def init_lock():
    """시작 준비(표 만들기 · 컬럼 더하기 · 데모 씨앗)를 워커 하나씩 — gunicorn 워커 넷이 동시에 떠서 같은 표를 만들다
    「이미 있음」으로 한 워커가 죽으면 gunicorn 이 전부 내린다(S0 검토 실측). 잠금 파일은 DB 옆."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover — 윈도우(운영 아님)
        yield
        return
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(Path(DB_PATH).parent / ".init.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)
