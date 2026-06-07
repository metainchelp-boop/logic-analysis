#!/bin/bash
# v5.0 배포 스크립트 — 보고서 6단계 재배치 + AI 모델 교체(claude-sonnet-4-6)
# 사용법: VPS에서 실행
#   cd /root/logic-analysis-deploy && git pull origin main && bash deploy_v50.sh
set -e

DEPLOY_DIR="/root/logic-analysis-deploy"
DB_PATH="$DEPLOY_DIR/data/logic_data.db"
BACKUP_DIR="$DEPLOY_DIR/data/backups"
CONTAINER="logic-analysis"

echo "========================================"
echo "  v5.0 배포: 보고서 6단계 재배치 + 모델 교체"
echo "========================================"

# 1) DB 백업
echo ""
echo "[1/5] DB 백업..."
mkdir -p "$BACKUP_DIR"
if [ -f "$DB_PATH" ]; then
    BACKUP_FILE="$BACKUP_DIR/pre_v50_$(date +%Y%m%d_%H%M%S).db"
    cp "$DB_PATH" "$BACKUP_FILE"
    echo "  ✅ 백업 완료: $BACKUP_FILE"
else
    echo "  ⚠️ DB 파일 없음, 백업 건너뜀"
fi

# 2) 최신 코드 pull (프론트엔드는 이 디렉터리를 nginx가 서빙 → git pull로 자동 반영)
echo ""
echo "[2/5] 코드 업데이트 (git pull)..."
cd "$DEPLOY_DIR"
git pull origin main && echo "  ✅ git pull 완료" || echo "  ⚠️ git pull 실패 — 확인 필요"

# 3) 프론트엔드: index.html App.jsx 버전 6.0.0 → 브라우저 캐시 자동 무효화
echo ""
echo "[3/5] 프론트엔드 — git pull로 반영됨 (App.jsx 재배치, index.html v6.0.0 캐시버스트)"

# 4) 백엔드 배포 (변경된 chat.py, main.py 컨테이너에 복사 후 재시작)
echo ""
echo "[4/5] 백엔드 배포 (Docker cp + restart)..."
if docker ps --format '{{.Names}}' | grep -q "$CONTAINER"; then
    docker cp "$DEPLOY_DIR/backend/chat.py" "$CONTAINER:/app/chat.py"
    docker cp "$DEPLOY_DIR/backend/main.py" "$CONTAINER:/app/main.py"
    echo "  ✅ chat.py, main.py → 컨테이너 복사 완료 (AI 모델 claude-sonnet-4-6)"
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

echo ""
echo "========================================"
echo "  v5.0 배포 완료!"
echo "  - 보고서 6단계 흐름 재배치"
echo "  - 상품명/키워드태그 통합"
echo "  - AI 모델 claude-sonnet-4-6 (6/15 폐기 대비)"
echo "  → 브라우저 새로고침(Ctrl+Shift+R) 후 확인"
echo "========================================"
