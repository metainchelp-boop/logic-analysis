# 빈 timestamp 검색 메타데이터 수정 — 승인된 범위

## 근거와 설계

사용자는 2026-10-02 설명한 우선순위 1번(빈 `timestamp=`를 잘못 거절하는 규칙)을 먼저 개선하도록 승인했다. 기준은 `e696e51`, 확장 1.28.5이다.

- 같은 시간대 1.28.5 판독 실패 진단 17건 중 16건은 주소상 2페이지이며, 유일한 미허용 항목이 빈 `timestamp=`였다. 클릭 수신은 17건 모두 기록됐다. 이것은 정상 상품 응답이나 순위 정확성 전체를 입증하지 않는다.
- 실제 캡처/판독 함수를 사용한 격리 재현에서 동일한 합성 상품 데이터는 해당 항목이 없으면 통과하고 있으면 거절됐다.
- 접근은 관측된 단일 빈 문자열만 허용하는 최소 수정이다. 알 수 없는 항목 전체 허용이나 검증 삭제는 하지 않는다.
- 응답 캡처, 페이지 판독, 페이지 링크의 현재/목적지 검색 조건 검사에 같은 규칙을 적용한다. 클릭 좌표·입력 횟수·수집 속도·휴식·차단 보호·서버 계약은 변경하지 않는다.
- `timestamp`의 중복, 빈 문자열 이외의 값, 배열/비문자 값, 다른 필터·검색어·페이지, 오래된 응답과 접근 제한은 계속 거절한다.

## 검증 및 전달 계획

1. 실제 캡처에서 판독으로 연결하는 실패 시험을 추가해 RED를 확인한다.
2. 최소 수정으로 GREEN을 확인하고 현재/목적지 링크 검사도 동일하게 맞춘다.
3. 변형·중복·오래된 응답·제한 응답과 기존 회귀 시험을 실행한다.
4. 모든 외부 요청을 차단/로컬 응답하는 Chrome fixture로 1→2페이지 및 기존 서버 검증/메모리 DB 저장을 확인한다.
5. 1.28.6-rc1 후보 ZIP과 교체·복귀 안내를 다운로드 폴더에 제공한다. 서버 배포나 노트북 설치는 수행하지 않는다.

새 공용 인터페이스나 범용 검증 모듈은 추가하지 않는다. 페이지 세계에 주입되는 기존 함수의 독립성을 유지하며 동일 규칙을 시험으로 묶는다. Windows 실기기, 실 네이버 응답, 실제 서버 수신은 후보 교체 뒤 별도 확인한다.

## 구현 및 검증 결과

- 후보: `1.28.6-rc1` (`manifest.version=1.28.6`). 런타임 변경은 background.js의 판독/두 클릭 경로 검색 조건과 net_tap.js의 요청/응답 검색 조건뿐이다.
- 첫 캡처→판독 시험은 수정 전 `UNVERIFIED_PAGE`로 실패하고 최소 수정 후 통과했다. 별도 현재/목적지 페이지 링크 시험도 수정 전 실패, 수정 후 통과했다.
- 확장 Node 회귀: 21개 파일, Node 집계 72개 시험 통과, 실패 0. 내부 레거시 assertion 수와 다른 집계다.
- 격리 Chrome 수집→순위 봉투→서버 검증→메모리 SQLite 저장: 19개 시나리오 통과. 빈 timestamp의 tap/router/HTTP418/숫자 필터와 실제 링크 혼합 4개를 추가했다. 정상 합성 목록은 클릭 한 번으로 1~80위, 두 번째 장 첫 상품 41위·sourcePage=2를 기록했다. 제한 응답은 첫 40개만 부분 보존했다.
- 기존 Chrome 클릭 안정성/대상 안전: 21개 시험(안정성 19개, 대상 안전 2개) 통과. 클릭 좌표 알고리즘은 수정하지 않았다.
- 별도 읽기 전용 계약 검토: 기존 서버의 timestamp URL 재검증 없음. backend observation 56/56, rank_guard 19/19, v2_wire 48/48 및 extension observation_envelope 24/24 통과. 서버 파일 수정 없음.
- 독립 검토에서 4개 검색 조건 검사의 단일 빈 값/중복 거절 일치를 확인했다. 추가 인코딩·타입·신선도 검사 85회 통과. 이번 변경의 새 결함은 발견하지 못했다.
- 변경 JS 구문 및 `git diff --check` 통과. manifest의 권한·호스트·주입 설정은 기준판과 동일하고 버전 두 필드만 바뀌었다.

## 교체와 현장 합격 기준

1. 우선 2번 한 대만 적용한다. 팝업에서 일시정지하고 재개 표시를 확인한 뒤 확장 카드 새로고침으로 기존 실행을 끊는다. 일시정지 표시만으로 진행 중 작업이 즉시 취소되는 버그까지 고친 것은 아니다.
2. 기존 등록 폴더를 별도로 복사해 보관한다. ZIP 루트 8개 파일을 같은 등록 폴더에 덮어쓰고 `chrome://extensions`의 해당 확장 카드 새로고침을 누른다. 확장 삭제·새 ID 등록·쿠키/저장소 삭제는 하지 않는다.
3. 확장 1.28.6을 확인한다. 예전 net_tap이 남지 않도록 수집기 전용 쇼핑 작업 탭만 닫는다. 일반 업무 탭은 닫지 않는다.
4. 접근 제한·캡차·차단 휴식이 없고 기존 대기가 허용할 때 재개한다. 강제 수집·반복 새로고침은 하지 않는다.
5. 새 관측의 버전/시작 시각과 pagesRead>=2, 실제 상품·순위·서버 저장을 함께 대조한다. 주소만 2페이지이거나 running=true만으로 합격 처리하지 않는다. 추적 대상을 첫 페이지에서 모두 찾은 정상 조기 종료는 제외한다.

복귀는 일시정지 후 같은 폴더에 보관한 구버전 파일을 복원하고 확장 카드를 새로고침한다. 복귀해도 이 검증 결함은 다시 생기므로 강제 수집하지 않는다.

이번 후보에 화면 밖 `NO_PAGER`의 추가 수정, 오류 탭 자동 복구, 반복 실패 후 재시도 간격 변경, 일시정지 즉시 취소, 80개 보기 지원은 포함하지 않았다. 실제 네이버·Windows·운영 HTTP 저장·장시간 안정성·오전 10시 완료는 검증 전이다.

## 전달 파일과 재검증

- `/Users/sinyosub/Downloads/collector-extension-1.28.6-rc1.zip`
- `/Users/sinyosub/Downloads/collector-extension-1.28.6-rc1-교체안내.md`
- ZIP 루트 런타임 8개만 포함. 압축 무결성, 파일 집합, 각 파일의 검증 소스와 바이트 일치, manifest 1.28.6을 확인했다. 고객 데이터·운영 DB·토큰·시험 파일은 포함하지 않았다.
- ZIP SHA-256: `4a2fcf98de4839e0495ec58534ae32fd10287fe49849bda721266b1d44dd0667`

```sh
TZ=Asia/Seoul node --test collector-extension/tests/*.test.js
NODE_PATH=/Users/sinyosub/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules COLLECTOR_TEST_CHANNEL=chrome PYTHONDONTWRITEBYTECODE=1 node collector-extension/tests/pagination_browser.test.cjs
NODE_PATH=/Users/sinyosub/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules COLLECTOR_TEST_CHANNEL=chrome node --test collector-extension/tests/pager_target_browser.test.cjs collector-extension/tests/click_stability_browser.test.cjs
```

기존 로컬 Chrome/Playwright로 시험했다. 설치·다운로드·실사이트 요청은 수행하지 않았다.
