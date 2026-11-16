# 광고센터 실행 이미지 1개 암호화 보존

이미지는 원래 앱의 설정이나 비밀을 포함할 수 있다. 이 절차는 이미지 전체를 승인된 공개키로 암호화하여 별도 백업 서버로 보존하며, 앱 데이터베이스·volume·컨테이너 상태는 변경하지 않는다. 기존 자동입찰 키와 DB 일치, 데이터의 일관 사본, 앱 철거는 별도 단계다.

고정 대상·원본 측 경계는 [명세](../../docs/superpowers/specs/2026-11-02-retirement-image-preservation-source-design.md), 서버 B 수신 계약은 [수신기 안내](RETIREMENT_CIPHER_RECEIVER.md)에 있다. 수동 workflow는 `naver-image-preservation.yml`이다. 대표 계정이 검사를 통과한 `main`에서만 실행한다.

## 실행 순서

1. 현장 inventory로 고정 image ID와 보존 목적지를 다시 대조한다. `prepare`는 source 여유 공간·도구·공개 수신자·호스트 신뢰를 확인하고 전용 SSH 운송 키를 만든다. 결과의 공개키만 서버 B의 제한 인증에 사용한다. 복구 비밀키는 source나 B로 보내지 않는다.
2. B에 검사한 receiver와 root 전용 namespace를 준비한다. SSH 공개키는 확인한 source IP, `restrict`, 가까운 만료 시각, 고정 receiver 명령으로 제한한다. 기존 인증 파일이나 ScaleForce 수신기를 덮어쓰지 않는다. 별도 인증 파일을 사용한다면 현재 `sshd -T`가 그 경로를 허용하고 파일이 존재하지 않음을 확인한 뒤 exclusive 생성한다. SSH 설정 변경·재시작은 필요하지 않다.
3. `send`를 한 번 실행한다. source의 Docker/GPG/SSH 종료 코드가 모두0이고 B의 암호문 바이트 수·SHA-256이 같아야 전송 성공이다. `received_unverified`와 `transferred_unverified`는 복구 완료가 아니다. 실패 사본이나 동일 session을 자동 덮어쓰기·재사용하지 않는다.
4. 완료된 시도의 B 임시 인증을 정확한 공개키·파일 내용 대조 후 철회한다. 이어 `cleanup`으로 source의 전용 SSH private/public 키를 제거한다. 암호문과 안전한 영수증은 보존한다. 정리 성공을 복구 성공으로 해석하지 않는다.
5. B의 암호문을 Mac의 관리자 전용 폴더로 실제 회수한다. 복호화 전 수신 영수증과 전체 크기·SHA-256을 대조한다. 대화나 GitHub artifact로 전달하지 않는다.
6. 보안 입력창에서 복구 키 잠금을 풀고 GPG 복호화 stdout을 `retirement_image_verify.py`의 stdin에 직접 연결한다. 평문 tar를 파일·터미널·보고서에 쓰지 않는다. 부모 실행기는 **GPG와 검증기의 종료 코드가 모두0**인지 확인해야 한다. 검증기는 외부 tar의 한 image manifest, config SHA, 모든 참조 layer의 diff ID, 전체 EOF와 제한을 검사한다. Docker load/run과 앱 모듈 import는 하지 않는다.
7. 성공하면 별도 검증 영수증에 암호문 크기·해시, 정확한 image ID, GPG/검증기 종료 코드와 시각을 기록한다. `archive_structure_verified`는 실행 이미지 구조·내용 일치 검증이며 DB 복구나 실제 서비스 복원 검증이 아니다. 원본 image/앱/data는 이 절차로 삭제하지 않는다.

## 검증 경계

공개 asset 두 파일은 복구 공개키와 서버 B의 공개 호스트 키다. 원본 앱의 설정·키·이미지 본문이나 복구 비밀키는 저장소에 포함하지 않는다. 공개 stdout은 고정 상태·숫자·암호문 해시·공개 SSH 키만 허용한다. daemon 임시 경로 판정을 위한 제한된 환경 조회는 원문을 출력하거나 보관하지 않는다.

`docker save`의 pipe 사용은 daemon 내부 임시파일이 없다는 보장이 아니다. 원본 helper는 작은 고정 image와 충분한 공간만 허용한다. 참고: [Moby의 image save 임시 디렉터리](https://github.com/moby/moby/blob/v27.5.1/image/tarexport/save.go#L195), [daemon의 임시 경로 설정](https://github.com/moby/moby/blob/v27.5.1/daemon/daemon.go#L1351).

합성 시험은 실제 서버 접근·전송·암호문 회수·복호화의 증거가 아니다. 각 실행 결과를 별도로 보존한다. 키·비밀번호·DB 행·환경 원문·고객 파일명은 결과 기록에 남기지 않는다.

## Docker·containerd 이미지 식별 검증

기존 Docker 형식은 고정 image ID와 config 원문 SHA-256을 대조한다. containerd 저장소에서는 inspect의 image ID가 manifest/index의 target digest일 수 있다. 이때 검증기는 고정 target blob의 실제 SHA-256에서 시작해 각 descriptor의 원문 해시·크기·형식을 확인하고, 단일 runtime manifest의 config와 순서 있는 layer 목록을 `manifest.json`의 동일 경로·순서에 연결한다. 임의 config를 허용하는 fallback은 없다. [Moby inspect 구현](https://github.com/moby/moby/blob/v28.5.2/daemon/containerd/image_inspect.go), [containerd export 구현](https://github.com/containerd/containerd/blob/v2.1.4/core/images/archive/exporter.go).

OCI layer의 descriptor digest는 보관된 원문 바이트의 해시이며 config의 `rootfs.diff_ids`는 압축 해제된 tar 바이트의 순서별 해시다. 검증기는 비압축 tar와 단일 gzip stream을 지원하고 gzip의 CRC·trailer·EOF까지 확인한다. 이어 붙인 gzip, 뒤에 붙인 데이터, zstd 등 미지원 형식은 성공 처리하지 않는다. [OCI descriptor](https://github.com/opencontainers/image-spec/blob/v1.1.1/descriptor.md), [Layer DiffID](https://github.com/opencontainers/image-spec/blob/v1.1.1/config.md#layer-diffid).

index는 runtime 경로 하나만 허용한다. BuildKit의 명시적 attestation annotation과 `unknown/unknown` platform을 함께 가진 descriptor는 제외하며, 해당 attestation의 존재·복구는 검증하지 않는다. runtime 플랫폼이 둘 이상이거나 runtime blob이 빠지면 거부한다. 따라서 성공은 고정 target에 연결된 단일 runtime 이미지의 구조 검증이고 전체 다중 플랫폼·attestation 보존의 증거는 아니다. 미지원 형식으로 인한 실패도 암호문 손상을 뜻하지 않는다. [BuildKit attestation descriptor](https://github.com/moby/buildkit/blob/v0.20.2/docs/attestations/attestation-storage.md#attestation-manifest-descriptor).

입력과 gzip 확장량은 각각512MiB, outer tar 항목은4096개, 보관하는 metadata 후보는256개·각2MiB·합계16MiB, JSON 깊이는32, index 깊이는8, 전체 실행은600초로 제한한다. CLI는 core dump를 끄며 평문을 추출하거나 디스크에 쓰지 않는다. 일반 구조 오류에서도 입력을 EOF까지 소비하지만 크기·시간 제한에서는 중단한다. 최종 성공에는 부모 실행기가 확인한 **GPG 종료 코드0과 검증기 종료 코드0**이 모두 필요하다. 이 변경의 합성 시험과 실제 암호문 복호화 검증은 별도 증거다.


## 콘텐츠 이미지의 압축 해제 검증 예산

남은 이미지 공통 profile에서 콘텐츠 이미지의 gzip 해제 누적 작업량만 8GiB로 제한합니다. 기존 이미지 식별자, 세션, 전송·암호문·외부 tar 2GiB 한도, 1800초 검증 제한과 나머지 세 이미지의 512MiB 해제 한도는 그대로입니다. 평문은 64KiB 이하 chunk로 해시하며 파일로 추출하지 않습니다. 8GiB는 메모리 할당량이나 확인된 실제 해제 크기가 아니라 유한한 검증 작업량 상한입니다.

Docker 29.4.0의 containerd `ImageInspect.Size`는 [packed resource descriptor 크기 합계](https://github.com/moby/moby/blob/daa0cb7f23594cdbcce5002e370027d3fd36ffd7/daemon/containerd/image_inspect.go#L174)입니다. gzip 해제 뒤 계층 tar의 총 길이와 같지 않습니다. 그래서 약 1.38GB의 inspect Size를 근거로 해제 한도까지 2GiB로 둔 기존 설정은 정상 크기의 압축본도 거부할 수 있었습니다. `expanded_size_limit` 뒤에는 EOF까지 drain하므로 결과의 `archive_bytes`는 해제 크기나 실패 위치를 뜻하지 않습니다.

기존 암호문과 과거 영수증은 보존합니다. 새로운 검증은 과거 전송 profile의 SHA와 새 검증 코드/profile의 SHA를 구분하고, 같은 암호문 FD의 전체 길이·SHA를 다시 결속해야 합니다. 완료된 전송 세션을 다시 준비하거나 송신하지 않습니다. 새 한도로도 크기·시간·식별·descriptor·diff_id 검증이 실패하면 성공으로 처리하지 않습니다.
