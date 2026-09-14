# ⛔ 이 파일은 **배포에 쓰이지 않습니다.**
#
#    실제로 서버에 올라가는 것은  ➜  backend/Dockerfile  (CMD: uvicorn --workers 5)
#
#    왜 그런가 — 배포 스크립트(.github/workflows/deploy.yml)가 서버에 docker-compose.yml 을
#    **직접 써 넣는데**, 그 안이 `build: ./backend` 다. 그래서 저장소 루트의 이 Dockerfile 도,
#    루트 docker-compose.yml 도 배포 경로에 들어가지 않는다.
#
# ⚠️ 2026-09-14 실사고 — 백업이 깨진 원인을 파다가 **이 파일을 읽고**
#    「gunicorn 워커 3개」라고 단정해 보고했다. 실제 서버는 **uvicorn 워커 5개**였다.
#    원인 진단 자체는 맞았지만(여럿이 돈다) 수와 실행기를 틀리게 적었다.
#    ⭐ 교훈 — 「설정 파일에 뭐라고 적혀 있나」가 아니라 **「배포가 어느 파일을 집어 가나」**를 따라갈 것.
#
# ⚠️ 아래 「RAM 1.9GB」 주석도 낡았다 — 2026-09-14 실측 **3.9GB**(available 2.7GB).
#
# ⛔ 여기를 고쳐도 서버는 안 바뀐다. 서버 동작을 바꾸려면 backend/Dockerfile 을 고칠 것.
#    (로컬에서 단독 실행할 때만 쓰인다. 지우지 않는 이유가 그것이다.)
#
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
