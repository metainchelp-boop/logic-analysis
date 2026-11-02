# 로그인 감사 오류의 제한된 읽기 전용 관찰

승인된 NAVER 보호 기능 회귀 조사입니다. `naver-login-audit-diagnostic.yml`은 대표 계정의 main 수동 실행만 허용하며, 제품 배포를 유발하지 않습니다. 조회 대상은 검토한 관제 엔진·중계 컨테이너의 고정 ID·이미지·소스입니다. 정확한 시작 시각·PID·재시작 횟수·실행 상태와 엔진 DB bind 경로를 전후 대조하고 달라지면 관찰 결과를 내보내지 않습니다.

DB 본문, SQLite 연결, 환경값, 앱 HTTP, 수집, 재시작·중지는 사용하지 않습니다. DB 디렉터리는 descriptor 기반 no-follow 탐색과 부모 identity 대조, 고정 DB/WAL/SHM 3개는 lstat만 수행합니다. 파일 종류·숫자 메타데이터·statvfs 여유 공간은 실제 쓰기 성공의 증거가 아닙니다. leaf가 심볼릭 링크여도 그 링크의 메타데이터만 관찰합니다.

Docker logs는 컨테이너별 최근 한 시간·마지막 300줄 표본, stdout/stderr 합계 1MiB로 제한합니다. 두 파이프를 동시에 비우며 원문은 메모리 안에서만 처리합니다. 검토한 형식 전체가 일치할 때만 고정 오류 분류·고정 종류·건수·시각을 내보냅니다. 모르는 예외명은 `unrecognized`, 나머지는 무시 건수뿐입니다. `StoreBusy`만으로 queue full/closed/wait timeout을 구분할 수 없으며 `StoreError`만으로 SQLite의 lock/disk 원인을 구분할 수 없습니다. queue 상태는 항상 `not_observed`입니다. 표본에 없다고 과거 오류가 없었다고 결론 내리지 않습니다.

실행당 명령은 8초, helper 전체 60초, workflow 외부 70초 후 종료 유예 5초입니다. 신호가 child 생성 도중 도착해도 등록한 다음 죽이고 회수하며, 회수가 불확실하면 실패로 처리합니다. 공개 stdout은 닫힌 13필드 JSON 한 줄이고 workflow가 해시로 고정한 같은 helper의 검증기로 다시 검증한 뒤 접두사와 함께 공개합니다. 원문 stderr와 예외 문자열은 출력하지 않습니다.

`read_only`는 서비스·DB 변경이 없다는 뜻입니다. 프로세스 core limit/umask와 빈 임시 Docker CLI 설정 폴더, 전송용 공개 helper 폴더는 실행 환경이며 종료 후 좁게 정리합니다. 사용자 설정·키·context는 불러오지 않습니다.

검증 순서: 합성 파일·가짜 Docker/log·로컬 자식 프로세스의 경계 시험 → 독립 검토 → 정확한 PR HEAD 전체 도구 CI → main의 동일 tree 확인 → 수동 진단 1회 → 닫힌 출력과 실행 HEAD/actor/attempt 확인. 실제 진단 전까지 운영 원인은 확인되지 않은 상태입니다.
