FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Seoul

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/

RUN mkdir -p /app/data
EXPOSE 5051

# gunicorn + uvicorn 워커 (logic-analysis와 동일 패턴)
CMD ["gunicorn", "app.main:app", \
     "-w", "4", "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:5051", "--timeout", "120", "--graceful-timeout", "30"]
