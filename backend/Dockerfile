FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5050
# uvicorn 워커 수는 서버 RAM(1.9GB)에 맞춰 3개로 제한한다.
# 워커 1개당 앱 전체를 메모리에 올리므로, 8개는 ~1.2GB(전체 63%)를 점유해
# 스왑 thrashing → 요청 지연 → 워커 끊김으로 인한 502가 발생했다.
# 3개로 줄이면 메모리 점유가 ~0.5GB로 떨어져 여유가 확보된다.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5050", "--workers", "3"]
