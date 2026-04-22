#!/bin/bash
# logic-analysis 배포 스크립트 v4.4.0
# 사용법: VPS에서 실행
#   cd /root/logic-analysis-deploy && bash deploy.sh
#
# 이 스크립트는:
# 1. 현재 DB를 백업 (업체/광고주 데이터 보호)
# 2. 최신 코드를 GitHub에서 pull
# 3. Docker 이미지를 빌드하고 컨테이너를 재시작
# 4. 헬스체크로 정상 동작을 확인

set -e

DEPLOY_DIR="/root/logic-analysis-deploy"
DB_PATH="$DEPLOY_DIR/data/logic_data.db"
BACKUP_DIR="$DEPLOY_DIR/data/backups"
FRONTEND_DEPLOY="$DEPLOY_DIR/frontend"

echo "========================================"
echo "  logic-analysis 배포 시작"
echo "========================================"

# 1) DB 백업 (가장 먼저!)
echo ""
echo "[1/5] DB 백업 중..."
mkdir -p "$BACKUP_DIR"
if [ -f "$DB_PATH" ]; then
    BACKUP_FILE="$BACKUP_DIR/pre_deploy_$(date +%Y%m%d_%H%M%S).db"
    cp "$DB_PATH" "$BACKUP_FILE"
    CLIENT_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM clients;" 2>/dev/null || echo "?")
    echo "  ✅ 백업 완료: $BACKUP_FILE (업체 ${CLIENT_COUNT}건)"
else
    echo "  ⚠️ DB 파일 없음, 백업 건너뜀"
fi

# 2) 코드 업데이트 (GitHub pull 또는 로컬 복사)
echo ""
echo "[2/5] 코드 업데이트 중..."
if [ -d "$DEPLOY_DIR/.git" ]; then
    cd "$DEPLOY_DIR"
    git pull origin main 2>/dev/null || echo "  ℹ️ git pull 실패 — 수동 배포 모드"
fi

# 3) 프론트엔드 배포
echo ""
echo "[3/5] 프론트엔드 배포 중..."
if [ -d "$DEPLOY_DIR/frontend" ]; then
    echo "  ✅ 프론트엔드 디렉토리 확인 완료"
else
    echo "  ⚠️ 프론트엔드 디렉토리 없음"
fi

# 4) Docker 빌드 + 재시작
echo ""
echo "[4/5] Docker 빌드 및 재시작 중..."
cd "$DEPLOY_DIR"

# docker-compose 사용 (표준 방식)
if [ -f "docker-compose.yml" ]; then
    docker compose down 2>/dev/null || docker-compose down 2>/dev/null || true
    docker compose up -d --build 2>/dev/null || docker-compose up -d --build
    echo "  ✅ Docker Compose로 배포 완료"
else
    # fallback: 수동 docker run
    echo "  ℹ️ docker-compose.yml 없음 — 수동 docker run 사용"
    docker stop logic-analysis 2>/dev/null || true
    docker rm logic-analysis 2>/dev/null || true
    docker build -t logic-analysis:latest .
    docker run -d \
        --name logic-analysis \
        --restart unless-stopped \
        --env-file "$DEPLOY_DIR/.env" \
        -e TZ=Asia/Seoul \
        -e DB_PATH=/app/data/logic_data.db \
        -v "$DEPLOY_DIR/data:/app/data" \
        -p 127.0.0.1:5050:5050 \
        --log-driver json-file \
        --log-opt max-size=10m \
        --log-opt max-file=3 \
        logic-analysis:latest
    echo "  ✅ 수동 Docker 배포 완료"
fi

# 5) 헬스체크
echo ""
echo "[5/5] 헬스체크 중..."
sleep 5
for i in 1 2 3 4 5; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5050/api/health 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "  ✅ API 정상 (HTTP $HTTP_CODE)"
        break
    else
        echo "  ⏳ 대기 중... ($i/5, HTTP $HTTP_CODE)"
        sleep 3
    fi
done

# 배포 후 DB 확인
if [ -f "$DB_PATH" ]; then
    POST_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM clients;" 2>/dev/null || echo "?")
    echo ""
    echo "  📊 배포 후 업체 수: ${POST_COUNT}건"
    if [ "$POST_COUNT" = "0" ]; then
        echo "  ❌ 경고: 업체 데이터가 0건입니다! 볼륨 마운트를 확인하세요!"
    fi
fi

echo ""
echo "========================================"
echo "  배포 완료!"
echo "========================================"
