# 남은 고정 이미지 네 개의 암호화 보존

## 범위와 선택

- 기존 대표 지시의 원본 복구 자료 보존을 이어간다. 앱 볼륨·DB 접근, 컨테이너 실행·중지, 설정 변경·이미지 삭제는 없다. 원격 실행은 root 담당이며 이 구현 단계는 합성 검사만 한다.
- 기존 광고센터 source/receiver/validator와 종료된 `ad-image-20261102-v1`은 그대로 보존한다. 해당 파일의 전역 상수를 치환하거나 기존 세션을 재사용하지 않는다.
- 기존 파일을 함께 수정하는 방식은 현재 고정된 검증기 해시에 영향을 준다. 이미지마다 구현을 복제하는 방식은 보안 수정이 갈라진다. 검토된 전송/수신/OCI 코드를 각각 한 번만 새 공통 구현으로 가져오고 frozen `ImageProfile`을 명시 인자로 전달한다.

## 고정 계약

- 프로필은 `autobid-web`, `autobid-engine`, `autobid-watchdog`, `content-studio` 네 개뿐이다. 공개 모듈에 전체 이미지 ID·관측 Size·고유 session/forced command·한도를 고정한다. 임의 태그·경로·수신자·호스트·한도 입력은 없다.
- source CLI는 `phase profile`, receiver/validator는 `profile` 한 인자다. 수동 workflow는 한 프로필의 `prepare/send/cleanup`만 실행하며 같은 concurrency 그룹에서 순차 처리한다. source도 고정 공유 flock으로 네 프로필의 동시 실행을 거부한다.
- 각 프로필은 별도 source 0700 session·0600 운송 키·독립 영수증을 갖는다. 서버 B namespace와 `image.gpg.pending`/`image.gpg.partial`도 프로필에 결속된다. 실패·완료 뒤 send 재시도와 session 재준비는 거부한다. B 제한 인증 폐기 뒤 cleanup은 해당 운송 키 두 파일만 삭제하며 영수증·암호문·원본은 남긴다.
- `-I`에서도 고정 sibling 프로필 파일만 no-follow FD로 연다. regular·owner·nlink1·쓰기 권한·32KiB 상한과 전후 identity를 검사하고, 내장 SHA256과 일치한 동일 bytes만 compile/exec한다. workflow는 공개 helper/profile/수신 공개키/호스트키 네 파일을 별도로 해시 검사한다.

## 자원 확인과 큰 이미지의 제한된 허용

- AutoBid 세 이미지는 관측 Size 약84MB와 정확히 일치해야 하며 image256MiB·cipher/archive512MiB를 유지한다. 콘텐츠는 관측1,381,032,080B, image1.5GiB·cipher/archive2GiB·gzip expanded2GiB다. raw/expanded 예산은 별개다.
- prepare/send 직전에 제한된 Docker info/version, 정확한 ID/Size, systemd MainPID와 dockerd 시작 시점, bounded daemon 환경의 TMPDIR/DOCKER_TMPDIR 허용 여부를 검사한다. 환경 원문 읽기가 전혀 없다고 주장하지 않는다. 값 원문은 출력·저장하지 않는다.
- 안전 영수증 `resources`는 버전 숫자 3개·release/suffixed enum·driver/backend/data/tmp enum·고정3경로의 device/f_bavail 바이트만 포함한다. `/var/lib/docker`, `/var/lib/docker/tmp`, `/tmp`를 no-follow FD로 확인하고 Docker data/tmp의 같은 device와 각3GiB 가용량을 요구한다.
- 공개 출력 키/alias는 `docker_data`를 사용한다. Actions가 SSH 사용자 시크릿 `root` 문자열을 마스킹하더라도 JSON 필드명과 영수증 계약이 변하지 않게 한다. daemon 환경 검사 전 core dump도 비활성화한다.
- 콘텐츠는 고정 client/server `29.4.0` release, driver `overlayfs`, driver-type `io.containerd.snapshotter.v1` 조합만 허용한다. 준비 단계의 첫 검사는 session/키 생성 전에 수행하고 실제 준비와 send 직전에 다시 검사한다. 버전·suffix·backend·이미지 ID/Size·temp 경로·여유 공간이 달라지면 중단한다. flag만 바꾸거나 CLI·환경으로 우회할 수 없다.
- 읽기 전용 현장 조회 `41393347518`에서 해당 containerd backend와 가용3,359,207,424B를, `41393681258`에서 서버29.4.0을 확인했다. client 버전과 실제 전송 직전 가용량은 새 prepare/send가 다시 확인하므로 이 과거 수치를 실행 허가로 대신하지 않는다.
- 공식 Moby `docker-v29.4.0`의 고정 commit `daa0cb7f23594cdbcce5002e370027d3fd36ffd7`에서 [containerd ExportImage](https://github.com/moby/moby/blob/daa0cb7f23594cdbcce5002e370027d3fd36ffd7/daemon/containerd/image_exporter.go)는 기존 content에 lease를 걸고 [Client.Export](https://github.com/moby/moby/blob/daa0cb7f23594cdbcce5002e370027d3fd36ffd7/vendor/github.com/containerd/containerd/v2/client/export.go)로 writer를 전달한다. [archive exporter](https://github.com/moby/moby/blob/daa0cb7f23594cdbcce5002e370027d3fd36ffd7/vendor/github.com/containerd/containerd/v2/core/images/archive/exporter.go)는 tar writer와 content ReaderAt/CopyTo를 연결한다. [CLI29.4.0 save](https://github.com/docker/cli/blob/v29.4.0/cli/command/image/save.go)는 `-o` 없이 API 응답을 stdout에 복사한다. 검토한 이 경로에서는 전체 tar의 임시 파일 사본을 만들지 않는다.
- 따라서 콘텐츠의 전체 tar 임시 사본 예산은0B, metadata/운영 여유는1GiB, 실제 최소 여유는 `max(3GiB, 0B + 1GiB) = 3GiB`다. lease·daemon metadata 쓰기까지0이라는 뜻은 아니며 다른 exporter·버전으로 일반화하지 않는다. 별도 실측된 세 경로 모두 이 여유를 충족해야 하고 runtime이 검토 조합과 다르면 `large_image_not_reviewed`다.

## 결과와 검증

- source 출력은 기존10필드에 `resources`만 더한다. 준비/전송 성공은 resources 필수, cleanup은 null, 실패는 확인된 수치만 남긴다. 전송은 docker/gpg/ssh 종료0·암호문 길이/해시·엄격한 receiver 영수증이 모두 일치해도 `transferred_unverified`, `backup_verified=false`다.
- OCI 검증은 profile의 고정 digest에서 descriptor chain·config·정렬된 layers·diff_ids를 연결한다. 구조 검증과 실제 앱 복구 성공은 구분한다.
- 합성 검사는 기존 전송 실패/종료/EOF/부분쓰기/권한 회귀에 profile 혼선, 공유 잠금, resource canary, 콘텐츠의 정확한 버전/backend 허용·변형 거부·세 경로 용량·send 재검사, 동일 FD 모듈 해시·symlink/hardlink/FIFO/교체를 추가한다. 기존 광고센터 세 파일 변경 없음도 확인한다. 실제 source/B 및 비밀 복구 키 실행은 별도 운영 증거다.
