FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5050
# uvicorn 워커 수는 서버 RAM(1.9GB)과 동시처리 사이에서 5개로 맞춘다.
# 8개는 ~1.2GB(전체 63%)를 점유해 스왑 thrashing → 502를 유발했고,
# 3개는 메모리는 안정(~0.5GB)이나 무거운 분석(네이버 크롤링)이 동시에
# 들어오면 워커를 모두 점유해 가벼운 요청까지 502가 났다.
# 5개면 메모리 ~0.8GB로 여유를 유지하면서 동시처리 여력을 확보한다.
# (함께: naver_crawler의 429 빠른 실패로 워커 점유 시간도 대폭 단축)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5050", "--workers", "5"]
