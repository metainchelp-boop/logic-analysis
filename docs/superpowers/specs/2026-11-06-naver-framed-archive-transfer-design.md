# NAVER 보관본 이전의 완료 경계와 B 설치 설계

## 승인된 범위

PR362 이후 검토에서 확인한 세 경계와 새 B 설치·철회 도구를 구현한다.
source/GPG 실패를 정상 수신 EOF와 구분하고, Mac partial 이름 교체를 감지하며,
원본 정리 중단 시 manifest를 남긴다. 기존 앱 정지나 종료한 세션은 재사용하지
않는다. 이 변경은 소스 구현이며 서버 설치·키 생성·전송·삭제 실행과 구분한다.

## 불변 조건

- 동일한 고정 cold 8프로필 및 interrupted 3파일만 포함한다. wire plan의
  canonical bytes, 원본 해시, 복구 영수증 binding은 유지한다.
- 암호문은 길이 프레임으로 보내고 source/GPG exit0와 두 stderr EOF 뒤에만
  END를 보낸다. B는 END 총길이/SHA/후행 EOF 확인 전 final을 게시하지 않는다.
- transport/receiver는 함께 갱신한다. 구버전 raw ciphertext는 거부한다.
- fetch의 final link 뒤 partial unlink 직전에 fd·두 이름의 identity와 nlink2를
  대조한다. payload 전부를 JSON manifest보다 먼저 정리한다.
- 송신·회수 성공은 삭제 허가가 아니다. 인증 복호화·전체 바이트 대조·승인된
  plan/receipt 원문 SHA가 필요하다. 실패 시 자동 정리·재시도는 없다.

## 새 B 제어 경계

고정 세션 `naver-archives-20261106-v1`에 대해 controller는 install/revoke만
수행한다. 새 Ed25519 공개키 두 개, 서로 확인한 현재 IPv4 두 개, 고정 receiver
SHA만 입력한다. 180분 만료, restrict/from, 고정 강제 명령을 사용한다.
두 키가 허용받는 original command는 이 세션의 receive/fetch뿐이다.

Linux root에서 기존 primary 인증 파일을 보존하고 secondary 부재와 현재
두 IP의 sshd effective 조건을 확인한다. root 소유·비쓰기 상위 경로,
0700 leaf, 0600 파일, 새 경로, B 여유15GiB를 요구한다. pending을 배타
작성한 뒤 renameat2 NOREPLACE로 secondary를 게시하고 fsync한다.
철회는 설치 receipt의 정확 metadata·hash 및 실제 두 인증 줄을 대조한
secondary 한 파일만 삭제한다. 기존 primary, 서비스, sshd 설정, 도구와
보존 데이터를 변경·삭제하지 않는다.

Mac operator는 controller/receiver/known-hosts 공개 파일 SHA를 고정하고
기존 관리자 인증 파일의 metadata만 검사한다. private key 본문은 SSH만
사용하며 새 운송 private key를 전달하지 않는다. 요청은 stdin JSON,
응답은 제한된 closed schema이다. 결과는 새 private 파일에 배타 보존한다.
설치 결과의 IP/keyhash, 철회 결과의 원래 설치 증거를 대조한다.

## 실패와 남는 경계

정상 END 게시 이후 ACK나 sent.json만 유실되는 분산 작업의 모호성은 남는다.
원격 설치도 응답 유실 뒤 성공했을 수 있다. 부분 파일과 실패 영수증은
조사 근거로 보존하고 실제 상태를 대조한다. null은 부재 증명이 아니다.
동일 UID의 비협조적 수정에 대한 원자적 compare-and-unlink는 보장하지
않으므로 같은 파일을 다른 운영자가 수정하지 않는 작업 창을 사용한다.

이 PR에는 VPS 자동 배포 workflow, 작은 plan/receipt의 관리자 채널 교환,
실제 키 가용성·pinentry·서버 상태 검증이 포함되지 않는다. 운영 절차는
`docs/naver-archive-offsite.md`와 별도 비공개 인수인계에 기록한다.

## 검증

실제 임시 GPG 암호문과 Python subprocess를 사용한 로컬 파이프 시험,
모든 절단 위치·프레임 경계·upstream 실패·stderr EOF 대기·경로 교체,
controller의 파일/권한/sshd/게시 실패/정확 철회, operator의 pin·응답결속·
상한·시간초과를 합성 검증한다. 실제 회사 키나 서버는 시험에 쓰지 않는다.
Linux 전용 renameat2는 Linux CI에서 실제 임시 파일로 시험한다.
