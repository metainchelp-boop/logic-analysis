#!/bin/bash
# ===== v4.3.0 배포 스크립트 — v5 디자인 100% 적용 =====
# 실행: bash deploy_v430.sh
# VPS: 1.234.20.80 (SSH 포트 22)

set -e

VPS="root@1.234.20.80"
DEPLOY_DIR="/root/logic-analysis-deploy/frontend"
REPO_DIR="/root/logic-analysis/frontend"
LOCAL_FRONTEND="frontend"

echo "===== v4.3.0 배포 시작 ====="
echo ""

# 1) VPS에 현재 버전 백업
echo "[1/4] VPS 현재 버전 백업..."
ssh $VPS "cp -r $DEPLOY_DIR ${DEPLOY_DIR}_backup_$(date +%Y%m%d_%H%M%S)" || {
  echo "⚠️  백업 실패 — 계속 진행하시겠습니까? (Ctrl+C로 중단)"
  read -p "Enter to continue..."
}

# 2) 수정된 파일 목록
FILES=(
  "index.html"
  "css/styles.css"
  "js/utils.js"
  "js/components/App.jsx"
  "js/components/AdvertiserInfoCard.jsx"
  "js/components/KeywordVolumeSection.jsx"
  "js/components/MarketRevenueSection.jsx"
  "js/components/RelatedKeywordsSection.jsx"
  "js/components/CategoryAnalysisSection.jsx"
  "js/components/KeywordTagSection.jsx"
  "js/components/ProductNameSection.jsx"
  "js/components/ProductNameOptSection.jsx"
  "js/components/ReviewAnalysisSection.jsx"
  "js/components/HtmlDetailAnalysisSection.jsx"
  "js/components/SalesEstimationSection.jsx"
  "js/components/KeywordTrendSection.jsx"
  "js/components/EntryStrategySection.jsx"
)

# 3) deploy 디렉토리에 파일 전송
echo "[2/4] deploy 디렉토리에 파일 전송 (${#FILES[@]}개)..."
for f in "${FILES[@]}"; do
  echo "  → $f"
  scp "$LOCAL_FRONTEND/$f" "$VPS:$DEPLOY_DIR/$f"
done

# 4) repo 디렉토리에도 동기화
echo "[3/4] repo 디렉토리 동기화..."
for f in "${FILES[@]}"; do
  scp "$LOCAL_FRONTEND/$f" "$VPS:$REPO_DIR/$f"
done

# 5) 배포 완료 확인
echo "[4/4] 배포 완료 확인..."
ssh $VPS "head -4 $DEPLOY_DIR/js/utils.js | grep APP_VERSION"

echo ""
echo "===== v4.3.0 배포 완료! ====="
echo "확인: http://1.234.20.80 또는 https://metainc.co.kr"
echo ""
echo "롤백 방법: ssh $VPS 'cp -r ${DEPLOY_DIR}_backup_* $DEPLOY_DIR'"
