#!/usr/bin/env bash
# 제품 커밋에서 관제(engine·relay) 배포에 필요한 파일만 tar 로 묶는다.
# 범위는 옛 실행기(naver_preview_release.py EXACT/PREFIXES, safe_source_path)와 같다:
# tests·캐시·키·env 파일은 넣지 않는다. 서버의 naver-deploy.sh 가 같은 범위로 다시 검사한다.
#
# 사용: make-source-archive.sh <제품 저장소 폴더> <커밋 40자리> <출력 tar>
# 출력: tar 의 sha256 (표준출력 한 줄)
set -euo pipefail

repo=$1
commit=$2
out=$3
case "$out" in
  /*) ;;
  *) out="$PWD/$out" ;;
esac
if ! printf '%s' "$commit" | grep -Eq '^[0-9a-f]{40}$'; then
  echo 'commit 은 40자리 소문자 16진수여야 합니다' >&2
  exit 1
fi
if [ "$(git -C "$repo" rev-parse "$commit^{commit}")" != "$commit" ]; then
  echo "저장소에 커밋 $commit 이 없습니다" >&2
  exit 1
fi

# archive-paths-begin
git -C "$repo" archive --format=tar -o "$out" "$commit" -- \
  .dockerignore \
  Dockerfile.naver-engine \
  Dockerfile.naver-engine.dockerignore \
  Dockerfile.naver-relay \
  Dockerfile.naver-relay.dockerignore \
  compose.naver-engine.yml \
  compose.naver-relay.yml \
  backend/app/__init__.py \
  backend/app/naver_entry.py \
  backend/app/naver_relay.py \
  backend/app/routers/naver.py \
  backend/app/routers/__init__.py \
  backend/requirements.txt \
  naver_engine \
  naver_runtime \
  backend/app/naver_auto \
  backend/naver_page \
  deploy \
  ':(exclude,glob)**/tests/**' \
  ':(exclude,glob)**/__pycache__/**' \
  ':(exclude,glob)**/*.pyc' \
  ':(exclude,glob)**/*.env' \
  ':(exclude,glob)**/*.env.*' \
  ':(exclude,glob)**/*.pem' \
  ':(exclude,glob)**/*.key' \
  ':(exclude,glob)**/store 2.py'
# archive-paths-end

if command -v sha256sum >/dev/null; then
  sha256sum "$out" | cut -d' ' -f1
else
  shasum -a 256 "$out" | cut -d' ' -f1
fi
