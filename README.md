# 메타 광고주 통합 대시보드

마케터 전용 — 광고주 1명 기준으로 네이버·체험단·유튜브·카카오·당근 데이터를 모아 요약·리포트하는 웹 프로그램.
상세 기획·로드맵: 옵시디언 `결과물/Claude/Projects/AI 광고 운영 프로그램/`.

## 현재: Sprint 1 (로그인 + 광고주 등록·관리)

- ✅ 로그인 (JWT) + 3단계 권한(담당자/팀장/대표)
- ✅ 광고주 등록·조회·수정·삭제 (진짜 DB 저장)
- ✅ 채널별 API 키 입력 + **암호화 저장**(Fernet)
- ⬜ 다음 스프린트: 네이버 커머스/검색광고 실데이터 수집 → 통합 대시보드 → AI 리포트

## 실행 방법 (로컬)

터미널에서:

```bash
bash run.sh
```

→ 브라우저에서 **http://localhost:8000** 접속.

### 데모 로그인 계정
| 역할 | 이메일 | 비밀번호 |
|---|---|---|
| 담당자 | kim@metainc.co.kr | kim1234 |
| 팀장 | lead@metainc.co.kr | lead1234 |
| 대표 | admin@metainc.co.kr | admin1234 |

## 기술 스택
- 백엔드: FastAPI + SQLAlchemy + SQLite(개발) → PostgreSQL(운영 전환 예정)
- 인증: JWT + 서버측 RBAC / 키 암호화: Fernet
- 프론트: Sprint 1은 경량 화면(서버 서빙) → 팀 배포 단계에서 React로 승격

## 폴더
```
backend/
  app/            FastAPI 앱 (models, schemas, routers, security)
  static/         프론트 화면 (index.html, app.js, styles.css)
  requirements.txt
run.sh            로컬 실행
```
