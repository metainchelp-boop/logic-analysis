# 계정별 보고서 구현 계획

승인 근거: 같은 날짜의 account-reports-pdf-design 및 대표의 시안 승인.
writing-plans 스킬은 현재 설치 목록에 없어 이 문서로 구현·검증 순서를 관리한다.
운영 데이터·배포·발송·AI 호출은 변경하지 않는다.

## 순서와 소유 경계

1. 집계: reporting/store의 v2 스냅샷에 계정별·합산·일별·전기간 비교를 고정한다. 원천 귀속, 누락, 정정, 옛 판 보존을 단위시험한다.
2. 조회: 현재 실관리·담당 범위를 먼저 적용한 계정 목록/검색/기간/페이지와 상세 읽기 API를 추가한다. 없는 자료와 범위 밖 자료는 같은 거절로 처리한다.
3. 화면: 승인 시안의 목록→상세→계정/합산→PDF 흐름, 전체폭·모바일, 오래된 비동기 응답과 권한 변경 방어를 연결한다.
4. PDF: 고정된 로컬 라이브러리·한글 폰트로 브라우저에서 같은 판을 출력한다. 다운로드 전 권한을 다시 확인한다. 외부 변환 서비스·인쇄창 대체·가짜 PDF는 사용하지 않는다.
5. 통합: 회귀시험, 실제 브라우저 흐름, PDF 한글 추출·숫자·페이지 나눔과 패키지 경계를 확인한다. 검증한 변경만 커밋한다.

## 조회 계약

- GET /reports/accounts: selection, kind(weekly/monthly), anchor(기간 안 날짜), q, page, possibility_id(선택).
- 응답: rows, total, page, page_size, next_page, period, selection, unlinked_companies, schedule.
- 행: possibility_id, company_name, account_key(불투명 키), ad_account_no(검증된 번호), account_name, owner, workflow, period, status, report_id, revision_no, generated_at, details_status.
- GET /reports/detail: report_id, account_key(계정 키 또는 company). 기존 보고서 메타데이터 + scope + 선택 범위 payload를 반환한다.
- payload의 totals/ratios/coverage는 기존 의미 유지. format_version=2, details에 daily/comparison/briefing 등을 고정하고 내부 고객 ID·원천 지문은 공개하지 않는다.
- 이전 /reports, /reports/history는 회귀 호환한다. 새 GET 경로에서 재수집·재생성·업무 쓰기를 하지 않는다.

## 검수 기준

- 누락은 —/미확인, 실제 확인된 0만 0. 비율은 합산 분자/분모로 계산한다.
- 비교는 동일 범위·완결 자료만. 비율의 차이는 %p, 분모 0은 산출 불가.
- 보고서 없는 실관리 계정을 숨기지 않는다. 전산 미연결 업체는 이관 현황 안내로 구분한다.
- 업무 기록이 없으면 없다고 표시한다. 실제 하지 않은 관리 작업이나 원인 분석을 만들어내지 않는다.
- PDF 생성 직전 같은 report_id/account_key를 재확인하고 현재 화면 판과 다르면 다운로드하지 않는다.
- 화면·PDF 데이터에 비밀정보, 내부 메모, 직원 진단 원문, 잔액을 넣지 않는다.
- 권한·빠른 검색·기간/페이지 전환·목록 복귀·320px 가로 넘침·한글 긴 이름·부분 집계·폰트 실패를 검증한다.

## 승인 범위

이번 완료는 로컬 구현 및 검증이다. 운영 배포, 현재 직원 PC 검증, 광고주 발송 완료로 표현하지 않는다.
