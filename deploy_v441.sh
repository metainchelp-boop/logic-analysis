#!/bin/bash
# v4.4.1 배포 스크립트
# 사용법: VPS에서 실행
#   cd /root/logic-analysis-deploy && bash deploy_v441.sh
set -e

DEPLOY_DIR="/root/logic-analysis-deploy"
REPO_DIR="/root/logic-analysis"
DB_PATH="$DEPLOY_DIR/data/logic_data.db"
BACKUP_DIR="$DEPLOY_DIR/data/backups"
CONTAINER="logic-analysis"

echo "========================================"
echo "  v4.4.1 배포: 리뷰 텍스트 분석 + 찜 수 API"
echo "========================================"

# 1) DB 백업
echo ""
echo "[1/5] DB 백업..."
mkdir -p "$BACKUP_DIR"
if [ -f "$DB_PATH" ]; then
    BACKUP_FILE="$BACKUP_DIR/pre_v441_$(date +%Y%m%d_%H%M%S).db"
    cp "$DB_PATH" "$BACKUP_FILE"
    CLIENT_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM clients;" 2>/dev/null || echo "?")
    echo "  ✅ 백업 완료: $BACKUP_FILE (업체 ${CLIENT_COUNT}건)"
else
    echo "  ⚠️ DB 파일 없음, 백업 건너뜀"
fi

# 2) GitHub에서 최신 코드 pull
echo ""
echo "[2/5] 코드 업데이트 (git pull)..."
cd "$DEPLOY_DIR"
git pull origin main 2>/dev/null && echo "  ✅ git pull 완료" || echo "  ℹ️ git pull 실패 — 수동 모드"

# 3) 프론트엔드 배포 (nginx 서빙 디렉토리)
echo ""
echo "[3/5] 프론트엔드 배포..."
# 새 파일 복사
cp "$DEPLOY_DIR/frontend/js/components/ReviewTextAnalysisSection.jsx" "$DEPLOY_DIR/frontend/js/components/" 2>/dev/null || true
echo "  ✅ 프론트엔드 파일 배포 완료"
echo "  - ReviewTextAnalysisSection.jsx (신규)"
echo "  - App.jsx, index.html, utils.js (수정)"

# 4) 백엔드 배포 (Docker 컨테이너에 복사)
echo ""
echo "[4/5] 백엔드 배포 (Docker cp)..."
if docker ps --format '{{.Names}}' | grep -q "$CONTAINER"; then
    docker cp "$DEPLOY_DIR/backend/naver_crawler.py" "$CONTAINER:/app/naver_crawler.py"
    echo "  ✅ naver_crawler.py → 컨테이너 복사 완료"

    # 컨테이너 재시작 (새 코드 적용)
    docker restart "$CONTAINER"
    echo "  ✅ 컨테이너 재시작 완료"
else
    echo "  ⚠️ 컨테이너 '$CONTAINER' 미실행 — docker compose up 실행"
    cd "$DEPLOY_DIR"
    docker compose up -d --build 2>/dev/null || docker-compose up -d --build
fi

# 5) 헬스체크
echo ""
echo "[5/5] 헬스체크..."
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

# 배포 후 확인
if [ -f "$DB_PATH" ]; then
    POST_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM clients;" 2>/dev/null || echo "?")
    echo ""
    echo "  📊 배포 후 업체 수: ${POST_COUNT}건"
fi

echo ""
echo "========================================"
echo "  v4.4.1 배포 완료!"
echo "  - 리뷰 텍스트 분석 (HTML 입력 시)"
echo "  - 찜 수 API 조회 (상품 URL 입력 시)"
echo "========================================"
