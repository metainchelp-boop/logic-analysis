FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지 설치
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사 (backend/ 내부를 /app/ 루트로)
COPY backend/ .

# DB 데이터 디렉토리 (볼륨 마운트 대상)
RUN mkdir -p /app/data /app/data/backups

# 환경변수 기본값 — DB는 반드시 볼륨 마운트된 경로에 저장
ENV DB_PATH=/app/data/logic_data.db
ENV TZ=Asia/Seoul
ENV PYTHONUNBUFFERED=1

# 헬스체크 — DB 접근 가능 여부 + 업체 데이터 존재 여부
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "\
import sqlite3, os, sys; \
db=os.getenv('DB_PATH','/app/data/logic_analysis.db'); \
conn=sqlite3.connect(db, timeout=5); \
r=conn.execute('SELECT COUNT(*) FROM clients').fetchone(); \
conn.close(); \
print(f'OK: {r[0]} clients'); \
sys.exit(0) if r[0]>=0 else sys.exit(1)" || exit 1

EXPOSE 5050

# gunicorn (멀티 워커)
# 워커 수는 서버 RAM에 맞춰 3개로 제한한다. 워커 1개당 앱 전체를 메모리에 올리므로,
# RAM 1.9GB 서버에서 6개는 ~1.2GB를 점유해 스왑 thrashing → gunicorn 타임아웃에
# 워커가 끊기고 동일 워커의 다른 요청까지 502로 동반 실패하는 문제가 있었다.
# 3개로 줄이면 메모리 점유가 절반(~0.6GB)으로 떨어져 여유가 확보된다.
CMD ["gunicorn", "main:app", "-w", "3", "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:5050", "--timeout", "120", "--graceful-timeout", "30"]
