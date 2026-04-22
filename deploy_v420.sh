#!/bin/bash
# UI v5.0 풀버전 배포 스크립트 (v4.1.0 → v4.2.0)
# 사용법: cd /Users/sinyosub/Documents/GitHub/logic-analysis && bash deploy_v420.sh

VPS="root@1.234.20.80"
DEPLOY="/root/logic-analysis-deploy/frontend"

echo "=== v4.2.0 UI v5 풀버전 배포 시작 ==="

# CSS + HTML + JS
echo "[1/4] 코어 파일 전송..."
scp frontend/css/styles.css ${VPS}:${DEPLOY}/css/styles.css
scp frontend/index.html ${VPS}:${DEPLOY}/index.html
scp frontend/js/utils.js ${VPS}:${DEPLOY}/js/utils.js

# 컴포넌트 20개
echo "[2/4] 컴포넌트 전송..."
COMPONENTS=(
  App.jsx
  SummaryCardsSection.jsx
  KeywordVolumeSection.jsx
  MarketRevenueSection.jsx
  CompetitionIndexSection.jsx
  KeywordTrendSection.jsx
  RelatedKeywordsSection.jsx
  CompetitorTableSection.jsx
  SalesEstimationSection.jsx
  SeoDiagnosisSection.jsx
  SeoDetailSection.jsx
  HtmlDetailAnalysisSection.jsx
  ReviewAnalysisSection.jsx
  ProductNameSection.jsx
  ProductNameOptSection.jsx
  KeywordTagSection.jsx
  CategoryAnalysisSection.jsx
  DetailPageQualitySection.jsx
  EntryStrategySection.jsx
  ReportSection.jsx
  AdvertiserInfoCard.jsx
)

for f in "${COMPONENTS[@]}"; do
  scp "frontend/js/components/${f}" "${VPS}:${DEPLOY}/js/components/${f}"
done

# repo 동기화
echo "[3/4] repo 디렉토리 동기화..."
ssh ${VPS} "cp -r ${DEPLOY}/css /root/logic-analysis/frontend/ && cp -r ${DEPLOY}/js /root/logic-analysis/frontend/ && cp ${DEPLOY}/index.html /root/logic-analysis/frontend/"

# 확인
echo "[4/4] 버전 확인..."
ssh ${VPS} "grep APP_VERSION ${DEPLOY}/js/utils.js"

echo "=== v4.2.0 배포 완료! 브라우저에서 Ctrl+Shift+R로 확인하세요 ==="
