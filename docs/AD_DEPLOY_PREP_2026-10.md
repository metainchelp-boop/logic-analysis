# 광고센터 전용 배포 경로 준비 — 2026-10-01

대표 「응 진행해」 승인 범위는 기존 로직분석 서버 관리 연결 안에서 광고센터 전용 배포 경로를 마련하는 것입니다. 기존 SSH 키를 읽어 꺼내거나 다른 저장소에 복사하지 않습니다. 앱 배포·재시작·nginx·운영 env·입찰·수집 스위치 변경은 포함하지 않습니다.

- 최신 main `60864fb`에서 분리한 `codex/ad-deploy-prep-20261001` 가지입니다. S16 로그인 수신부 PR #296와 독립입니다.
- 기존 수동 `debug-rank.yml`에 `ad_prepare=inspect` 작업을 추가합니다. 이 모드에서는 기존 `diagnose` job 전체(데이터 수정·로그·큐 조회 포함)가 건너뛰어집니다.
- 기존 `VPS_HOST`·`VPS_USER`·`VPS_SSH_KEY`를 동일 SSH action 안에서만 사용합니다. action은 기존 v1.0.3의 검증한 SHA에 고정합니다. checkout·설치·키 파일 복사·비밀 설정 신규 등록은 없습니다.
- 실행 대기열은 기존 운영 배포의 `deploy-logic-analysis`를 사용하며 실행 중 작업을 취소하지 않습니다. 작업 전체 5분, 원격 명령 90초, 하위 명령 12초 제한입니다.
- 공개 로그에는 선택한 Docker 메타데이터·폴더 권한·집계 자원만 출력합니다. 환경·키·DB·앱 로그·전체 Docker inspect는 읽지 않습니다.
- GitHub상 작업 성공만으로 준비 완료를 판정하지 않습니다. 실제 출력·경로·원복 경계가 확인되어야 합니다. 운영 환경 확인 결과는 이후 이 문서에 추가합니다.

공식 근거: [기존 workflow의 별도 ref 수동 실행](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow), [최소 권한·입력/비밀값 취급](https://docs.github.com/en/actions/reference/security/secure-use).

기본 가지 병합은 아직 하지 않습니다. 향후 병합 시 이 진단 YAML과 문서는 기존 deploy.yml의 제외 대상이지만 다른 파일이 섞이면 앱 배포가 발생할 수 있으므로 변경 목록을 다시 확인합니다.
