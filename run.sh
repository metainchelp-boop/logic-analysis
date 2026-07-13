#!/bin/bash
# 메타 광고주 통합 대시보드 — 로컬 실행 스크립트
set -e
cd "$(dirname "$0")/backend"

if [ ! -d ".venv" ]; then
  echo "▶ 최초 1회: 가상환경 생성 중…"
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "▶ 필요한 부품 설치 중… (처음만 시간이 걸립니다)"
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo ""
echo "============================================================"
echo "  ✅ 서버 시작!  브라우저에서 아래 주소를 여세요:"
echo "      http://localhost:8000"
echo "  데모 로그인:  kim@metainc.co.kr / kim1234"
echo "  (종료하려면 이 창에서 Ctrl + C)"
echo "============================================================"
echo ""
uvicorn app.main:app --reload --port 8000
