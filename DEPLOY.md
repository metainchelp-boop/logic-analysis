# 배포 가이드 — ad.metainc.co.kr

광고 앱을 회사 VPS(로직분석이 도는 그 서버)에 **서브도메인**으로 올리는 방법.
구조: `ad.metainc.co.kr` → nginx 역프록시 → Docker(`ad-api`, 포트 5051). logic-analysis와 동일 패턴.

---

## 📋 대표님(또는 권한 가진 분)이 준비할 것

1. **DNS A 레코드 추가** — `ad.metainc.co.kr` → (VPS 서버 IP). 도메인 관리 콘솔에서.
2. **GitHub 저장소** — 이 폴더를 회사 GitHub에 올리기 (private 권장).
3. **GitHub Secrets** (저장소 Settings → Secrets) — logic-analysis와 같은 값 재사용:
   - `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`
   - `AD_JWT_SECRET` (아무 긴 무작위 문자열 — 토큰 서명용)

→ 이 3가지만 되면, 코드 push 시 **자동 배포**됩니다.

---

## 🚀 배포 절차

### 1. 자동 배포 (GitHub Actions, 권장)
`main` 브랜치에 push → `.github/workflows/deploy.yml`이:
파일을 VPS로 복사 → `docker compose up -d --build` → 헬스체크.

### 2. nginx 설정 (서버에서 1회)
```bash
# VPS에서
sudo cp deploy/nginx-ad.metainc.co.kr.conf /etc/nginx/sites-available/ad.metainc.co.kr
sudo ln -s /etc/nginx/sites-available/ad.metainc.co.kr /etc/nginx/sites-enabled/
sudo nginx -t && sudo nginx -s reload
sudo certbot --nginx -d ad.metainc.co.kr      # HTTPS 인증서 자동
```

### 3. 첫 배포 후: 광고팀 계정 만들기
```bash
# VPS에서, ad-api 컨테이너 안:
docker compose exec ad-api python create_user.py 대표@metainc.co.kr 대표 admin '강한비밀번호'
docker compose exec ad-api python create_user.py ad1@metainc.co.kr 박광고 staff '강한비밀번호'
# 역할: admin(대표) / lead(팀장) / staff(광고팀) / viewer(읽기전용)
```
> 데모 계정(kim/admin/viewer 등)은 첫 실행 시 자동 생성되니, 운영에선 **비밀번호를 바꾸거나 삭제**하세요.

---

## 🔁 수동 배포 (Actions 없이, 1회용)
```bash
# 로컬에서 VPS로 복사 후
scp -r . <VPS_USER>@<VPS_HOST>:/root/ad-dashboard-deploy
ssh <VPS_USER>@<VPS_HOST> "cd /root/ad-dashboard-deploy && JWT_SECRET=xxx docker compose up -d --build"
```

---

## ✅ 확인
- `https://ad.metainc.co.kr` 접속 → 로그인 화면
- 전산 "광고 관리" 탭(→ `docs/전산-통합/INTEGRATION.md`) 추가 후 전산에서 바로 열림

## 디스크 관리 (logic-analysis와 공유 서버)
이미지가 쌓이면: `docker system prune -af` (가끔).
