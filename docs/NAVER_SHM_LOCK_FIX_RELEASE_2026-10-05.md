# 관제 엔진 -shm 잠금 수정판 운영 배포 — 2026-10-05

## 승인과 범위

대표 「네이버 관제 배포해」 승인. 제품 `a38c53775c112cdf5db420f979093d6bee9e5376`에서
`c21f5f05f610abf89df0c24e85c00b1bec23d01c`로 전용 관제 engine/relay만 교체한다.
변경은 엔진 저장소 한 곳(`naver_engine/store.py`의 쓰기 연결 뒤 곁 파일 점검)과 그 시험 1개뿐이다.
schema11·수집 정책·화면·계약 원본·광고 설정·다른 앱은 바꾸지 않는다.

## 원인

`open_writer`가 SQLite 연결과 WAL 설정 뒤 곁 파일(`-wal`·`-shm`)을 `os.open`→`os.close`로 점검했다.
POSIX 잠금은 같은 프로세스가 그 파일의 다른 fd를 닫으면 풀리므로 엔진이 `-shm` 공유 메모리 잠금을 잃었다.
그 뒤 다른 프로세스가 같은 DB를 열면(읽기 전용이어도) 자신을 첫 사용자로 보고 `-shm`을 잘라,
그 파일을 쓰던 엔진이 SIGBUS(종료 135)로 끝났다. 10/4~10/5 재시작 5회가 DB를 직접 연 진단과 겹쳤다.
수정판은 연결 뒤에는 파일을 열지 않고 `lstat`·`chmod`로만 점검한다.

## 제품·포장·제어 근거

- 제품 Linux CI 37312547562(c21f5f0)·37318381104(봉인 고정값 a39f281): 성공.
- 봉인 37318788721: source tar `e23f84b0ba2799861746168d1d8f3dc4915b419977dbbc7b5afac13cf31ea898`
  (로컬 git archive 재계산과 일치), cipher `2c61aeb9f48b6c35fba5e797c24f0921083ce383581f980f692581eca32b443a`
  2,087,738 bytes, artifact 11348433440 `5808a5e5166aca66fe3d9b23957481e066c5b1d0df48c6d5f15503cf240f7a57`.
- 제어 `43f97b6`·`3da68e9`: 전환 고정값(OLD a38c537 / TARGET c21f5f0, store 272e8993… / 31be2c8e…,
  CODE_PATHS = store.py, TEST_PATHS = test_store_shm_lock.py — 실제 아카이브 차이와 정확히 일치).
  되돌리기에서 옛 판 DB 확인을 기동 전(쓰기 정지 확인 뒤)으로 옮기고, 옛 판 기동 뒤에는 HTTP·서비스 상태만 본다.
  status·data-audit·link-audit은 a38c537이면 호스트 접근 전에 `LIVE_READER_SUSPENDED`로 거절한다.
  preview 시험 287항(uid 65534) 통과, prepare 원문 130,492/131,072 bytes.
- 독립 반대 검토 2건: 차단 결함 없음, 고정값 정합, 사보타주 8종 모두 시험이 잡음.

## 배포와 운영 검증

- 사전 비접속 상태 37320583219(22:55 KST): a38c537, 엔진 14:40 KST 이후 재시작0, DB 열기0, 기존앱 기준 불변.
- 준비 37320753420: 22:58 KST `prepared`, services_started=false, nginx/bootstrap 불변.
- 적용 37321082045: 22:59~23:00 KST 성공 `internal_ready`, 작업 ID `39edf5c211532d63b7b0a8eba3970db9`.
  schema11·DB 일관사본 무결성 확인·비로그인401/업무403·nginx/기존컨테이너/bootstrap 불변·원천 수락.
- 사후 비접속 37321340880: 새 엔진 23:00:34 KST 기동, 재시작0(적용 단계의 호스트 DB 확인 뒤에도).
- 사후 실제 읽기 37321468844(23:02 KST): 엔진 컨테이너 안 별도 프로세스가 운영 DB를 열어 읽음, mutations0,
  읽은 뒤 엔진 기동 시각 그대로·재시작0. 수정 전 판에서는 같은 종류의 읽기가 엔진을 끝냈다.
- 위 수치는 엔진이 살아 있음과 잠금 결함 해소를 뜻하며, 전체 수집 완료나 모든 직원 화면 검증을 뜻하지 않는다.
