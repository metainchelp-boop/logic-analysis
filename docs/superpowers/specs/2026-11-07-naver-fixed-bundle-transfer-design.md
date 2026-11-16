# 고정 이중 보관본의 NAVER 원격 이전

## 문제와 선택

PR364의 source는 cold 프로필 8개와 중단된 일일 백업 보존본만 처리한다.
기존 `backup_bundle.py`가 만든
`54fc-and-20261021-regular-snapshot-gzip6-v1`도 같은 cold 부모에 있으므로
현재 plan은 `unknown_cold_directory`로 쓰기 없이 중단한다.
이 이름은 일반 cold 프로필과 달리 deployment와 snapshot 하위 폴더를 가진다.
이름만 허용하거나 unknown 검사 자체를 제거해서는 검증할 수 없다.

원래 이전 요청 범위에 이 고정 완료 형식을 포함한다. 별도 회차로 남기거나
명시적으로 제외하는 방법도 도구 변경이 필요하고 이전 범위를 줄이므로 선택하지 않는다.
임시 파일, 임의 폴더, 다른 날짜의 bundle은 계속 거부한다.

## 형식과 검증

전송 plan의 기존 group/row 구조, 세션과 암호화 framing은 유지한다.
고정 이름을 공유하는 `bundle`, `bundle-deployment`, `bundle-snapshot` 세 그룹이
함께 존재하거나 모두 없어야 한다. 그룹별 파일 수는 각각 1, 3, 2개다.

- bundle: `archive-manifest.json`
- deployment: `archive-manifest.json`, `source-manifest.json`, `engine.db.gz`
- snapshot: `archive-manifest.json`, `snapshot.sqlite.gz`

복구 경로는 닫힌 매핑으로 `bundle/<고정 이름>/` 아래 원래 두 하위 폴더를
재구성한다. 사용자 제공 상대 경로나 경로 정규화에 의존하지 않는다.
source는 실제 세 디렉터리와 모든 파일의 descriptor, identity, 이름 집합을
고정한다. 경로 변경, symlink, hardlink, 추가 파일, pending marker는 거부한다.
기존 cold 부모의 이름 집합도 재확인한다.

기존 `backup_bundle.py`의 읽기 전용 순수 형식 검증 함수를 재사용한다.
그 파일은 공개 도구 설치 목록에 추가하며 producer/apply 함수는 호출하지 않는다.
루트 plan SHA, 자식 manifest SHA, codec, 원본 및 gzip 크기·SHA, protected claim,
deployment source-manifest를 상호 대조한다. 두 gzip 모두 끝까지 해제하여 원본
크기와 SHA를 확인하고 trailing bytes/불완전 stream을 거부한다.
이 검증은 snapshot의 바이트 보존을 증명하며 DB 논리 무결성을 주장하지 않는다.

## 정리와 실패

회수 암호문의 인증 복호화와 격리 복구 영수증, source 재검증을 기존과 같이
요구한다. cleanup은 모든 그룹 payload를 먼저 제거한 뒤 일반·자식 JSON을
제거하고, bundle 루트 manifest는 마지막에 제거한다. 디렉터리는 남긴다.
실패 영수증만으로 원본이나 부분 산출물을 재시도·삭제하지 않는다.
운영 DB, 서비스, 일일 백업 상태는 이 변경에 포함하지 않는다.

## 설치와 실행

새 source/common과 추가 backup_bundle helper는 최종 커밋 SHA로 고정한 별도
도구 폴더에 설치한다. 기존 PR364 도구 폴더를 부분 교체하지 않는다.
receiver/controller/operator/transport 및 B 설치 영수증은 그대로 유지한다.
새 source의 plan과 Mac 검증기는 같은 최종 버전을 사용한다.
이미 실행된 B install을 다시 실행하거나 만료를 연장하지 않는다.
송신 전에 남은 인증 유효시간과 실제 처리 시간을 대조한다.
만료 전 완료를 보장하지 못하면 현재 상태를 보존하고 다음 절차를 별도 검토한다.

## 검증

합성 파일로 기존 unknown-directory 실패를 재현하고 고정 완료 bundle의
plan, stream, 무쓰기 검증, 중첩 격리 복구, 증거 결속 cleanup을 시험한다.
부분 세 그룹, 추가 파일, pending, symlink/hardlink, 경로 교체, manifest 변조,
상위/하위 불일치, gzip 손상·후행 바이트 및 cleanup 중단을 거부해야 한다.
기존 cold/interrupted 회귀와 전체 Linux CI를 최종 SHA에서 실행한다.
독립 코드 검토와 비밀정보 검사를 거친 PR을 VPS 담당 Claude에게 전달한다.
