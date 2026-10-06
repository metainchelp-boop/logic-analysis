# 관제 직원 접속 오류(NV-S00) 수정판 운영 배포 — 2026-10-06 저녁

## 승인과 범위

대표 신고(10/6 오후): 「직원들이 네이버 관제에 접속이 계속 안 된다 · 내 최고 관리자 계정은 된다」 → 원인 확정·수정·검증 뒤 대표 「배포하자」(10/6 20:0x KST).
제품 `a981b35e298aa58a52b30e266792bd0f36506c5d`(관제 화면 개편판)에서 `25dc24d8760a06b2321d4fbde481769c3ce32c34`로 전용 관제 engine/relay만 교체한다.

- 원인: 보고서 회차(`generate_reports`, 약 60초마다)가 쓰기 줄(Writer 하나)을 한 항목으로 10~20초 넘게 쥐었다. 판 표(4,683행)에
  (업체·기간) 색인이 없어 업체·기간마다 표를 다시 훑었고, 엔진 CPU 한도 0.5에서 더 길어졌다. 그 뒤에 선 로그인 감사 쓰기가 15초(`Writer.call(wait=15)`)를
  넘겨 `StoreBusy` → `_audit` 가 `audit-unavailable`(503) → 화면 NV-S00. 운영 기록(읽기 전용) 10/6 10:27~15:05 KST `열람·쓰기 기록 실패: StoreBusy` 10건,
  다른 오류 줄 0. 대표 계정과 직원의 차이는 들어간 때가 회차와 겹쳤는지의 차이로 본다(추정 — 사람별 기록은 내보내지 않는다).
- 바뀐 것(코드 5파일): `naver_engine/store.py`(보고서 회차를 업체 한 곳씩 쓰기 줄 항목으로 · 판 지도·판 사실 기억 · 최신 판 한 번 묶어 고르기 — 파이썬만) ·
  `naver_engine/management_store.py`(수집 후보·관리 판정이 같은 입력이면 짝 맞추기 재사용 · 지난 작업 계정별로만 훑기) · `naver_runtime/scheduler.py`(보고서 단계를
  조각 회차로 부름 · 조각 상한 64) · `naver_engine/web.py`(저장소 바쁨 503 에 기록 한 줄 「화면 API 저장소 바쁨: StoreBusy」 — 나머지 기록 줄은 a981b35 와 글자 그대로) ·
  `backend/naver_page/app.js`(진입 실패를 NV-S09 감사 · S10 저장소 · S11 내부 · S12 중계 · S13 JSON 아님으로 나눔 · 응답 번호 표시 · NV-S00 은 정말 모르는 답에만).
- 바꾸지 않은 것: schema 11 · SQL·표 구조·색인(배포 장치가 `SCHEMA_VERSION`·`_SCHEMA`·`_REVISION_COLUMNS`·`_migrate` 를 AST 로 대조) · 수집 회차·네이버 읽기
  (`naver_runtime/__main__.py`·`morning.py`·`naver_read.py`·`sync.py`·`links.py` 바뀐 줄 0) · 보는 범위·로그인(PKCE)·보안 머리글 · 쓰기 허용 목록 · nginx · 다른 앱.

## 제품·포장·제어 근거

- 제품 Linux CI 37451346647(광고센터 `codex/naver-account-first-20261002` @ `7257e65` · 봉인 고정 소스 25dc24d): 성공.
- 동등성·경합 검증(로컬): 수정 전후 보고서·판정 결과 같음(SAME) · 운영 크기 합성 저장소에서 쓰기 줄 막힘(StoreBusy) 0.
- 봉인 37452908086: source tar `05e114a9bf055ed8d1b0888afe41daa6fc77e2bc30241018a31da20284d3df28`(제어 고정값·로컬 git archive 계산과 일치 · 103파일 · 시험 폴더 없음),
  cipher `296ce258c319d85b1521d4135727cfb513061ef00fc0f46eb90ccdfa53a259e5` 1,721,346 bytes · artifact 11407380910 `750e7848083618a163572d1af475851e21fa91f1971da513ca8ab21b2c389e68`(1,722,376 bytes).
- 제어 `0b9c559`(이 갈래 앞으로 감기 `054d8cf..0b9c559` · 강제 없음): 전환 고정값(OLD a981b35 seal `1b1179f1…` / TARGET 25dc24d · store 옛 `cead3be3…` / 새 `6ba88658…`) ·
  CODE_PATHS 5개(실제 두 묶음 대조: 103파일 같은 목록 · 5개만 바뀜 · 권한 변화 없음) · 탐침: `/links/revoke` 가 양쪽 모두 401(a981b35 가 이미 엶) → OWNER_ACTION_ROUTES 로 옮기고
  TARGET_ACTION_ROUTES 는 비움. ⚠️ 옛 나눔(대상만 401 · 옛 판 403)을 그대로 두면 적용 실패 뒤 되돌린 a981b35 를 `CODE_ROUTE_STATUS` 로 거절해 engine·relay 가 멈춘 채 남는다 —
  옛 판 쪽 401 을 글자로 적은 시험으로 고정. 수집 상태 진단이 25dc24d 를 받고 새 기록 줄을 `web_store_busy` 로 센다(template_release 25dc24d).
  preview 시험 298항(uid 65534) 통과 · 일부러 고장 5종(옛 나눔 · 닫힌 거두기 · 옛 커밋 · 감시 목록 · 저장소 바쁨 틀) 모두 잡힘 · 준비 묶음 132,010 / 180,000(와이어 45,812 / 65,536).

## 배포와 운영 검증

- 사전 비접속 상태 37453065608(19:56 KST · a981b35): DB 열기0 · 엔진 08:33 기동 뒤 재시작0 · `audit_write_failed` StoreBusy 10건(10:27~15:05 KST) · 중계 engine-timeout 1건(13:10).
- 준비 37454733417(20:11~20:13 KST): `prepared` · services_started=false · nginx 불변 · bootstrap 불변.
- 적용 37455042395(20:14~20:15 KST): 서버 작업 약 40초 · 성공 `internal_ready`, 작업 ID `26b3d5bae2df4727920b88de6cac468e`.
  DB 일관사본 무결성 확인 · schema11 · 비로그인401/업무403 · nginx/기존컨테이너/bootstrap 불변 · 원천 수락(계정 1,789 · 카탈로그 36,981 · 관리 인원 15 · 조직 자료 최신).
- 사후 비접속 37455203562(20:16 KST): 새 엔진 20:15:00 KST 기동 · 재시작0 · OOM 없음 · 최근 종료 기록은 교체 때의 계획된 정지(130)뿐 · 135 없음 · 새 컨테이너 기록 줄 0.
- 사후 실제 읽기 37455350625(20:17 KST): 읽기 전용 · mutations0 · 엔진 기동 시각 그대로·재시작0 · 짝 확정 304 · 후보 131 · 일일 점검 276 ok · 주간 보고서 284업체판 ·
  로그인 기록(24시간) ok 6 · 새 컨테이너 기록 줄 0. 최근 회차 1건(20:16:24~20:16:54) `RUN_ABORT`(10곳 중 3곳) — 회차·네이버 읽기 코드는 이번 판에서 바뀐 줄 0 → 이 배포와 무관(뒤 회차로 재확인).
- 밖에서 확인(로그인 없이): 화면 3파일(index.html 27,379 · app.js 205,797 · app.css 41,028 bytes)이 25dc24d 원본과 바이트 일치 ·
  `/links/revoke`·`/issues/1/ack`·`/bell/read-all`·`/settings/thresholds` 401 · `/links/reject`·`/links/preview` 403 · `/dashboard`·`/me` 401.
- 위 수치는 교체가 끝났고 엔진이 살아 있음을 뜻한다. 직원 PC 실접속(로그인 기록 ok)은 다음 근무 시간 기록으로 확인한다.

## 남은 것

- 다음 근무일 아침: 직원 로그인이 `ok` 로 남는지 · `audit_write_failed` 0 · `web_store_busy` 0(있으면 갈래·시각) · 엔진 재시작0 · 135 없음.
- 봉인 묶음(artifact 11407380910)은 10/7 19:54 KST 에 만료 — 이미 쓰였다.
- 서버 빈 공간 6.13GB → 5.57GB(교체 때 DB 사본·새 이미지). 옛 사본 정리 규칙은 별도.
