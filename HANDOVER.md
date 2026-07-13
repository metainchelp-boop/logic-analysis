# 광고 센터(metainc-ad-dashboard) 개발 인수인계

> 이 문서 하나로 새 섹션에서 바로 이어서 작업할 수 있게 정리. (작성 2026-06-13)
> 운영 URL: **https://dashboard.metainc.co.kr** · 전산 GNB 명칭 "광고 센터"
> 함께 볼 파일: `ERP_CONTRACT_SYNC_API.md`(계약 연동 명세), `DEPLOY.md`(있으면)

---

## 0. 지금 당장 — 진행 중인 작업 (가장 먼저 볼 것)

**ERP(전산) 계약 동기화 — A 단계 배포 대기 중**
- 전산(`metainc-web-backend`)에 계약 조회 API를 만들어 **master에 푸시 완료**(커밋 `c66bfc9`). GitHub Actions가 `bootWar` 빌드 → 성공 시 ROOT.war 업로드. **빌드 실패 시 업로드 안 됨 = 운영 안전.**
- **대표가 할 일(대기 중)**: ① Actions 초록 확인 → ② 전산 톰캣 `setenv.sh` 맨 아래 append(덮어쓰기 금지):
  `export AD_SYNC_API_KEY='aa1ea559b3e9d64a6dba38c2158dab769e2a26ed955621c9'` → ③ **톰캣 재시작**(대표가 직접).
- **재시작 후 이어서 할 일(클로드)**:
  1. 전산 엔드포인트 검증: `curl -H "X-Api-Key: aa1ea559...b769e2a26ed955621c9" "http://api.metainc.co.kr/api/ad-sync/contracts"` → 200·JSON이면 성공, 404면 빌드 실패(수정·재푸시).
  2. 광고센터 VPS `.env`에 추가(append): `ERP_SYNC_URL=http://api.metainc.co.kr/api/ad-sync/contracts`, `ERP_SYNC_API_KEY=aa1ea559b3e9d64a6dba38c2158dab769e2a26ed955621c9` → `docker compose up -d`.
  3. 동기화 실행(`POST /api/admin/sync-contracts`, admin) → **전산 진행중 계약이 광고센터 광고주 계약기간으로 들어오는지** 검증.
- **광고센터 수신부(B)는 이미 구축·배포 완료** (아래 10번 참고).

**생성한 인증키**: `AD_SYNC_API_KEY = aa1ea559b3e9d64a6dba38c2158dab769e2a26ed955621c9` (전산·광고센터 양쪽 동일값).

---

## 1. 프로젝트 개요

마케터 전용 **"광고주 통합 대시보드 + AI 리포트/인사이트"** 웹앱. 광고주 1명 또는 전체를 멀티채널 데이터 한 화면 + AI 요약·피드백·캠페인 설계·예측. 단일 조직, 직원 100명+, 3계층(직원→팀→광고주), 4단계 RBAC.
- **1차 본질**: 데이터 통합 대시보드 + AI 리포트(읽기·요약 중심). 자동입찰(쓰기)은 S5 후속.
- 로드맵 문서(권위): `~/Library/Mobile Documents/com~apple~CloudDocs/옵시디언 METAINC/METAINC/결과물/Claude/Projects/AI 광고 운영 프로그램/광고자동화플랫폼_로드맵.md` + `상세기획_화면·데이터·리포트.md`.

---

## 2. 위치 / 스택 / 실행

- **repo**: `~/Documents/GitHub/metainc-ad-dashboard` — **⚠️ 자체 git repo 아님**(홈 repo `/Users/sinyosub`에 속함). GitHub Actions 미작동 → **배포는 rsync+ssh 수동**(3번 참고). 홈 repo 위험: 절대 `/Users/sinyosub`에서 `git add -A` 금지.
- **스택**: FastAPI + SQLite(운영 볼륨 `/root/ad-dashboard-deploy/data/`) + 경량 프론트(단일 `backend/static/index.html`에 전 화면 인라인 JS, React 미사용). Fernet 채널키 암호화. Docker.
- **로컬 실행**: `bash run.sh` → http://localhost:8000.
- **구조**: `backend/app/`(main.py, routers/, adapters/, models.py, schemas.py, deps.py, security.py, database.py, collector.py + analytics.py, ai_insights.py, erp_sync.py, report_ai.py, campaign_ai.py) + `backend/static/`(index.html, connect.html, logo.png, naver-categories.js).

---

## 3. 배포 (★ 가장 중요 — 운영 반영 방법)

운영 VPS: **`root@1.234.20.80`** (키 기반 SSH·비번 불필요. 단 운영 VPS SSH는 classifier가 대표 명시 승인 요구). 컨테이너 `ad-api`(127.0.0.1:5051), 배포폴더 `/root/ad-dashboard-deploy`, nginx `/etc/nginx/sites-available/ad.metainc.co.kr`(certbot HTTPS).

**표준 배포 절차 (★ 반드시 `run_in_background: true` 한 ssh 세션으로 묶기 — 중간 포그라운드 명령이 배포를 죽임):**
```bash
SRC=~/Documents/GitHub/metainc-ad-dashboard/backend
rsync -avz --exclude '__pycache__' -e "ssh -o ConnectTimeout=20" "$SRC/app/" root@1.234.20.80:/root/ad-dashboard-deploy/backend/app/
rsync -avz -e "ssh -o ConnectTimeout=20" "$SRC/static/index.html" root@1.234.20.80:/root/ad-dashboard-deploy/backend/static/index.html
ssh root@1.234.20.80 'bash -s' <<'EOF'
cd /root/ad-dashboard-deploy
docker cp backend/static/index.html ad-api:/app/static/index.html   # 정적 즉시 반영
docker compose up -d --build
sleep 9; curl -s http://127.0.0.1:5051/api/health
curl -s -k -o /dev/null -w "ext %{http_code}\n" https://dashboard.metainc.co.kr/
EOF
```
- **데이터/`.env`는 deploy 루트에 있어 rsync가 안 건드림**(backend/app·static만 동기화).
- **라이브 미반영 디버그**: 컨테이너만 보지 말고 **서버 `/root/ad-dashboard-deploy/backend/static/index.html` 부터 grep** — 거기 0이면 rsync 자체가 안 간 것.
- **index.html은 no-cache**(main.py가 Cache-Control no-store) → 배포 후 직원은 **F5만** 하면 최신.
- **검증 패턴**: 백엔드=`python3 -m py_compile`, 프론트 JS=`node -e "new Function(<script>)"`, 화면=standalone 하니스 만들어 `manual-preview`(4178) preview 도구로 렌더 확인, 풀스택=FastAPI TestClient(`export DB_PATH=$(mktemp)`).

---

## 4. 기능 인벤토리 (좌측 메뉴 = `.group` 4구분 + 설정)

**대시보드**: 담당자 메인보드(home) · 광고주 대시보드(dashboard, 합산·관리현황) · 광고주 진행현황(status, 상태필터+계약컬럼) · 매체별 진행현황(channel) · 💰 스펜딩 소진현황(spending, 금액·월별소진)
**작업보드**: 광고주 등록 관리(register) · 광고주 매체 엑셀 등록(upload) · 🤖 AI 캠페인 설계(campaign)
**보고서**: AI 리포트, 보고서(report) · 🚀 AI 인사이트(insights, 8카드+NL비서)
**기록 관리**[admin전용·nav-admin]: 팀, 전체 현황(team) · 🧠 학습 센터(learn, 시뮬레이터+수집현황)
**설정**(settings): 내 계정·비밀번호변경·알림 / (admin)회사공용키·직원권한

전 메뉴 **실데이터 작동**. 유일 '준비중'=설정 카카오알림 라벨(미구현).

---

## 5. 백엔드 구조 (주요 엔드포인트)

- **auth**(routers/auth.py): `/auth/login`·`/auth/me`·`/auth/sso`(전산 토큰 검증 자동가입)·`/auth/change-password`.
- **clients**(routers/clients.py, 대형): 광고주 CRUD, 채널키 암호화저장, `/channels/{ch}/test`·`/upload`·`/manual`, 리포트(`/clients/{id}/reports`), 캠페인 제안(`/clients/{id}/campaign-proposals`·`/campaign-proposals/{pid}/apply`), `/team/overview`(+by_channel)·`/team/spend-by-month`, `/alerts`·`/clients/{id}/dossier`·`/clients/{id}/activity`, `/learning/stats`·`/learning/collection-status`, `/admin/collect`·`/admin/system-keys`·`/admin/users`·`/admin/users/{id}/role`, 삭제워크플로(request/confirm/reject-delete·restore), connect-link(공개키입력).
- **insights**(routers/insights.py): `/insights/{id}/forecast·budget-advice·keyword-advice·peer-compare·text-insights·synergy·proposal-success/{pid}·autopilot(+simulate)·report-schedule` + `POST /insights/assistant`. 토대=`analytics.py`(순수통계)·`ai_insights.py`(Claude).
- **erp**(routers/erp.py): `POST /erp/contract-webhook`(전산 푸시 수신·X-Webhook-Secret) + `POST /admin/sync-contracts`(admin 수동조회). 로직=`erp_sync.py`.
- **collector.py**: 매일 06:00 KST 자동수집(fcntl 파일잠금 1워커) + `run_due_reports()`(정기리포트) 호출.
- **모델**(models.py): User·Team·Client·ChannelCredential·ChannelMetric·Report·CampaignProposal·ClientSetting·ConnectLink·ActivityLog. Client에 계약필드(contract_start/end·biz_reg_name·erp_possibility_id·sales_manager·db_grade) — main.py가 ALTER TABLE 경량 마이그레이션.

---

## 6. 프론트엔드 구조 (단일 index.html, 주의점)

- **해시 라우팅(SPA)**: `setRoute(r)`=렌더러가 자기 `#해시` 기록(같은값 skip→루프방지), `route()`=해시 파싱→렌더러 dispatch(`dashboard/{id}`·`register/{id}` 딥링크), hashchange 리스너(`_suppressHash`로 자기변경 무시). **새로고침 시 현재화면 유지·뒤로가기 작동**. 새 화면 추가 시: nav 링크 + section + route() map + 렌더러에 `activateScreen(id,navKey)` 또는 `setRoute()`.
- **★CSS 스코프 함정**: `.kpi-grid`·`.section-title`·`.card`·`.cards`는 `#s-dashboard` 스코프(renderReport도 사용) → **다른 화면(#s-spending 등)에서 쓰면 무효**. 새 화면은 **자체 CSS키트 재사용**하거나 **인라인 스타일**로 작성. (#s-channel/#s-team/#s-settings는 자체 키트 있음.)
- **라이트 테마 토큰**: `--panel/--panel2/--line/--line2/--text/--sub/--muted/--blue/--green/--amber/--red/--meta(#6c5ce7 AI강조)`. 채널색=`chMeta(key)`(CHANNELS 배열, color/abbr/tcolor).
- **권한 표시**: `applyRole()`이 `.nav-admin` 숨김(admin만), `isEditor()`(viewer 아니면 true), `ME.role`.
- **카테고리**: `naver-categories.js`(window.NAVER_CATS, 네이버쇼핑 대>중>소 전체트리, 제안서와 동일). 학습센터 시뮬레이터가 대>중>소 3단 드롭다운으로 사용.

---

## 7. 권한(RBAC) / SSO

- 4단계: **admin**(대표,전체) / **lead**(팀장,팀) / **staff**(광고관리팀 담당자,본인 광고주 쓰기) / **viewer**(그외 전직원,읽기전용). `visible_clients`가 서버에서 범위 강제(staff=본인 owner_id).
- **SSO**: 전산 `?sso=<토큰>` → `/api/auth/sso`가 전산 my-profile(`http://api.metainc.co.kr/api/employee-management/my-profile`)로 검증→자동가입(email=`erp:<로그인ID>`). 매핑: 대표/최고→admin, 팀명'광고관리'(공백제거)→staff, 그외→viewer. admin 강등 안함.
- 유일 실관리자=**metainchelp@gmail.com**(수동로그인 병행, 비번 미저장). 데모계정 전부 삭제됨.

---

## 8. 채널(매체) 11종 + 자격증명 대기

검색광고(searchad,라이브)·커머스(commerce,키미발급)·메타체험단(라이브,자사DB)·유튜브·메타광고·카카오모먼트·쿠팡애즈·네이버GFA·당근·토스애즈·모비온. 정규화패턴 `adapters/_common.py`(ads_result), 공용렌더러 `renderAds`.
- **★수집 대기 자격증명(나중에 한번에)**: YOUTUBE_API_KEY(구글콘솔 무료)·메타 access_token(+앱심사)·카카오 비즈OAuth토큰·쿠팡 키3종(+광고API권한+리포트경로 env COUPANG_ADS_PATH)·GFA(+파트너승인+스펙 env GFA_API_BASE). 키 없으면 graceful 한글에러, 다른 채널 정상.
- 메타체험단 토큰값 로컬 `메타크루/work/.mc_cal_token`, 서버 `.env` `MC_AD_API_TOKEN`. ANTHROPIC_API_KEY 설정완료(AI리포트·인사이트·캠페인설계 가동).

---

## 9. AI 기능 (이미 가동)

- **AI 리포트**(report_ai.py): 광고주+기간→연동 전채널 _gather_perf 수집→Claude 4단계 피드백(진단·개선·방향·전략).
- **AI 캠페인 설계**(campaign_ai.py): 실데이터로 채널믹스·검색광고 캠페인/키워드/입찰가 설계. **진행할 매체 선택**(체크박스). 실제적용=검색광고 write(`naver_searchad.apply_plan`), **전부 userLock=True(일시중지) 생성**·admin만·confirm필수·예산한도. ⚠️첫 실제적용은 검색광고 connected 광고주+비즈채널 필요(테스트계정·소액으로 대표와 1회 검증 — 아직 안함).
- **AI 인사이트 10종**(insights.py): 예측·해지위험·예산재배분·키워드추천·동종비교·텍스트분석·시너지·성공확률·NL비서·오토파일럿(드라이런만)·정기리포트예약. ★오토파일럿은 실집행 안함(시뮬레이션). 예측·상관은 수집이력 쌓일수록 정확.
- **학습센터**: 상단 시뮬레이터(비전·가정데이터, 네이버 대>중>소 카테고리) + 하단 실제 수집현황 대시보드(`/learning/collection-status`).

---

## 10. ERP(전산) 계약 동기화 — A/B 상세

**목적**: 전산 가망 "진행중"+계약 등록 시 계약기간(계약일·종료일)을 광고센터 광고주에 자동 반영. **매칭키=상호명(=광고주명)**.
- **명세**: `ERP_CONTRACT_SYNC_API.md`(repo 루트).
- **B(광고센터 수신부) — 구축·배포 완료**: Client 계약필드 + `erp_sync.py`(STAGE_MAP 진행중→active·사후관리→archived 등, upsert_company 상호명/possibility_id 매칭, pull_sync) + `routers/erp.py`(webhook·admin sync). 단계 자동변경은 `ERP_SYNC_STATUS=1` 옵션(기본 꺼짐, 계약기간만 항상 반영). TestClient 검증 완료.
- **A(전산 제공부) — 푸시 완료·배포대기**: `metainc-web-backend`에 `AdSyncController`+`AdSyncService`+`AdSyncDto`+`ProspectiveCompanyRepository.findByWorkStageName` 추가(커밋 `c66bfc9` master). 인증=X-Api-Key(env `AD_SYNC_API_KEY`). `@Auth` 없음→로그인불요, `anyRequest().permitAll()` 경로. 전산 엔티티: `ProspectiveCompany`(name=상호명·workStage·manageEmp·storeLink·isAdCenterRegistered) + `CompanyProduct`(contractDate·contractEndDate·contractPrice·round·product). **⚠️ 로컬 gradle은 Lombok/QueryDSL 애너테이션 처리가 안 됨**(전 프로젝트 게터 못찾음·환경문제) → 로컬 컴파일 검증 불가, **CI(Actions)가 검증**(빌드실패=무배포).
- **다음 단계**: 0번 참고(대표 톰캣 재시작 후 검증·연결·테스트).

---

## 11. 잔여 과제 / 대기 항목

1. **ERP 계약 동기화 마무리**(0번) — 대표 톰캣 재시작 대기.
2. **자격증명 수집**(8번) — 유튜브키·메타·카카오·쿠팡·GFA. 키 들어오면 서버 `.env` 추가→재시작이면 즉시 켜짐.
3. **AI 캠페인 실제적용 첫 테스트** — 검색광고 connected 광고주+비즈채널로 테스트계정·소액 1회(대표와 함께).
4. **정기 리포트 발송 채널** — 현재 자동'생성·보관'만, 광고주 발송(이메일/카톡) 미연결.
5. **API 없는 3채널(당근·토스·모비온)** — 엑셀 업로드만(자동수집 불가).
6. 데모 광고주 client_id=4 "🧪 테스트광고주" 추후 삭제 예정.

---

## 12. 작업 규칙 / 주의 (대표 선호·운영 안전)

- **대표는 비전공**: 질문 많이·쉬운 설명·화면(스샷/프리뷰)으로 확인. 이미지 못 봄 → **시안은 실행가능 HTML로 크롬에서** 확인.
- **비중대 건은 승인 없이 직접 진행, 중대 건만 보고**. 각 작업 검증 후 "N번 완료, 체크하세요" 식 보고.
- **배포는 run_in_background로** + 완료 알림 시점에만 보고(대표 진행표시 안 보여 불안해함).
- **운영 전산(metainc-web)은 중대**: 조사→계획→대표 OK 후 수정. ★`setenv.sh` 절대 덮어쓰지 말 것(JASYPT 키)·append만. 톰캣 재시작은 **항상 대표에게 요청**(대표가 직접). master push=자동배포. **`git add -A` 금지**(자기 파일만 명시 커밋 — 동시 작업 세션과 섞임 방지).
- **운영 VPS SSH**·**홈 repo git**는 classifier 승인 필요.

---

## 13. 관련 시스템 / 메모리 포인터

- **전산 ERP**: `metainc-web-backend`(Spring, org.metainc.systems, master 푸시 자동배포·톰캣 재시작 대표) + `metainc-web-frontend`(전산 GNB "광고 센터" 탭, Header.tsx, master push→vite build→cafe24). 전산 URL=http://metainc.co.kr/login. → 메모리 [[metainc-web-erp-setup]], [[metainc-proposal-generator]].
- **메타체험단**: `meta-chehumdan.com`, 읽기전용 API `/www/mc_ad_api.php`. → [[metacrew-platform]].
- **로직분석**: `logic.metainc.co.kr`(별개, 네이버쇼핑 분석). → [[logic-analysis-project]].
- **메모리 원본**: `ai-ad-dashboard-project.md`(이 프로젝트 전체 이력) — 새 세션은 이 메모리 + 본 HANDOVER.md를 함께 참고.
- **배포 인프라**: VPS 1.234.20.80(logic 5050·studio 5060·ad-api 5051 독립), DNS=Cafe24(계정 yoosub92), 디스크 ~82%(prune 주의).
