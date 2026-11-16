# 퇴역 이미지 CLI 호환성과 제한된 실패 진단

## 승인된 범위

Parent 누락 시에도 읽기 검사를 수행하고, 다음 실패를 명령 단계와 고정 분류로 구분한다. 기존 이미지 대상·소켓·명령 allowlist·자원 상한·읽기 전용·UNKNOWN·삭제 비승인 경계는 유지한다. 소유자 간 합의에 따라 수정 PR과 정확 커밋 CI까지 준비하며 운영 실행과 병합은 이 변경에 포함하지 않는다.

## 선택

1. 채택: `{{json (index . "Parent")}}`로 누락을 null, 빈 문자열을 빈 문자열로 유지한다. 기존 정규화와 불완전 부모 관계 표현을 재사용한다.
2. API 버전 강제 하향은 다른 metadata 동작을 바꾸므로 사용하지 않는다.
3. 누락을 빈 문자열로 치환하면 미확인을 확인된 빈값과 섞으므로 사용하지 않는다.

## 출력 계약

scope는 고정 대상 범위 식별자 `naver-retired-image-inspect-v1`을 유지하고 JSON schema_version을 2로 올린다. 최상위 diagnostic은 정상/변경/명령 외 실패에 null이다. 명령 호출에서 거절될 때만 아래 닫힌 object를 제공한다.

- snapshot: 1 또는 2.
- command_index: 두 관찰 전체의 호출 순서 1..304.
- stage: INFO, IMAGE_LIST, CONTAINER_LIST, IMAGE_INSPECT, CONTAINER_INSPECT, ANCESTOR_FILTER.
- code: PARENT_KEY_MISSING, TEMPLATE_ERROR, DAEMON_UNAVAILABLE, OBJECT_NOT_FOUND, COMMAND_NONZERO, OS_NOT_FOUND, OS_PERMISSION, OS_OTHER, COMMAND_TIMEOUT, OUTPUT_LIMIT, INVALID_METADATA.
- exit_code: 실제 비정상 자식 종료값(-64..255, 0 제외) 또는 미확인 null. OS/시간/출력/형식 거절은 null. 명시된 Docker 오류 분류는 실제 종료값 필수.

stderr는 기존 stdout+stderr 합산 상한 안에서 메모리에만 두고 고정 코드로 분류한다. raw error, 경로, 명령 문자열, 태그, 환경 등은 출력하지 않는다. 분류는 오류 문구의 관측 지표이며 최초 원인 확정이나 복구 성공을 의미하지 않는다. schema 검증기는 같은 전송 helper에서 읽으므로 생산자와 검증기를 함께 갱신한다. 잘못된 진단 object는 INTERNAL_ERROR/null로 닫는다.

## 검증과 완료 기준

- 실제 Docker CLI를 fresh private Unix mock daemon에 고정하여 Parent 포함/생략/유효한 값, 구형 템플릿 실패 대조, null 처리 및 metadata 안정성을 검사한다. 실제 Docker daemon은 접속하지 않는다.
- 기존 FakeDocker 시험은 유지하고, 실패 단계·종료코드·고정 분류·비밀 canary 누출·닫힌 schema 변조를 추가 검사한다.
- CI와 운영 workflow의 사전 합성 검사에서 CLI 부재로 회귀 검사를 건너뛰지 못하게 한다.
- 관련 검사, 전체 도구 CI, 비밀정보 검사, 원격 SHA 확인 후 PR을 인계한다. COMPLETE_STABLE 운영 결과는 실제 수동 실행 뒤에만 판단한다.
