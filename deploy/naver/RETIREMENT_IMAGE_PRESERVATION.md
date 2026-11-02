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
