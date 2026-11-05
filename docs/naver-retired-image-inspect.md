# 퇴역 이미지 참조 확인 설계·운영 절차

## 목적과 범위

광고센터·콘텐츠 스튜디오·자동입찰의 보존 대상으로 확정된 이미지 5개에 대해,
삭제 계획 전에 현재 Docker 참조를 읽는다. 기존 앱 inventory는 앱 분류 밖 컨테이너를
제외하고 태그를 저장소 이름으로 축약하므로 전체 참조 확인에 재사용하지 않는다.
기존 삭제 도구의 대상 확대 대신 독립된 읽기 전용 helper를 사용한다.

`deploy/naver/retired_image_inspect.py`는 사용자 인자 없이 고정 이미지 ID만 판정한다.
앱·DB·파일 내용·환경변수·명령·마운트·컨테이너 이름을 출력하지 않는다.
이미지 태그와 RepoDigest, 서버 식별값은 개수 또는 SHA256으로만 내보낸다.
이미지·컨테이너·볼륨 삭제, prune, 서비스 제어, 백업 전송은 구현하지 않는다.

## 고정 대상

| 이름 | 이미지 SHA256 |
|---|---|
| ad-api | 959001525d45612e0c5cc1045291c7b6caefa768c14d37cc1070c26584cb8922 |
| content-studio | b52374a33084ea20386af2380478a38cff92eebdbeff97c616ad7d80a112a0dc |
| autobid-web | 075e4cd227777d7ea5347c27c0842067bc963cead5c6b6cc60b71897105140ec |
| autobid-engine | 3b86b60dd010faba75e910bdac4d8acc1678a3eabf1f54463fe5a64bf1cc0f6d |
| autobid-watchdog | 935ce49a4c3981eda46e1ae39c76daf831fd90107410d1823ea133f7b86cffad |

위 ID는 11월 2일 복구 사본 보존·회수·복호화·레이어 검증 기록의 대상이다.
이 검사로 서버 B의 현재 보존 사본 존재나 복원 가능성을 다시 검증하지 않는다.

## 관찰 방식과 판정

1. 고정 로컬 Docker 소켓에서 전체 이미지와 실행·정지 컨테이너를 조회한다.
   컨테이너가 사용한 실제 image ID는 inspect 값으로 확인한다.
2. 각 고정 대상에 직접 참조, Docker ancestor 필터 참조, Parent 연결,
   레이어 접두사·동일 목록·공유 관계를 구분한다.
3. 같은 전체 조회를 다시 수행하고 정규화한 fingerprint를 비교한다.
   목록 순서 차이는 허용하지만 태그·상태·관계·서버 변경은 성공 처리하지 않는다.
4. 명령 실패, 시간·출력·항목 상한 초과, 잘못된 ID, 누락·모순된 결과는
   `INCOMPLETE`와 후보별 `UNKNOWN`으로 처리한다. 두 관찰이 다르면 `CHANGED`다.

| 후보 상태 | 의미 |
|---|---|
| `ABSENT_IN_ACTIVE_STORE` | 완전하고 안정된 두 관찰의 활성 저장소 목록에 없음 |
| `REFERENCES_OBSERVED` | 컨테이너 참조, 명시된 부모 연결, 레이어 접두사·동일 목록 중 하나가 발견됨 |
| `NO_REFERENCES_OBSERVED` | 이번 검사에서 참조가 발견되지 않음 |
| `UNKNOWN` | 오류·누락·변경으로 판정 불가 |

`COMPLETE_STABLE`은 두 번의 관찰이 일치했다는 의미다. 원자적인 스냅샷이나
관찰 이후 불변을 보장하지 않는다. 다른 Docker 저장소로 전환해 숨겨진 이미지는
검사하지 않는다. Parent는 이전 빌더 전용 정보여서 빈값이나 누락이 자식 부재를
증명하지 않는다. 레이어 접두사나 동일 목록은 보수적으로 참조 발견에 포함하지만,
실제 빌드 계보의 확정 증거는 아니다. 공유 레이어만 있는 경우는 보조 수치로 표시한다.
부모 정보가 일부 빠져도 이미 확인된 부모·자식 연결은 보존하며, 연결 수는
관찰된 수로 해석한다. 레이어 관계 역시 빌드 계보 전체를 증명하지 않는다.

모든 결과에서 `delete_authorized=false`, `backup_currently_verified=false`,
`reclaimable_bytes=null`, 정상 관찰의 `parent_relation_complete=false`를 유지한다.
이미지 Size는 공유 레이어를 포함하므로 합계나 실제 확보량을 제시하지 않는다.
정지 컨테이너의 참조도 참조 발견이며 컨테이너 삭제를 자동으로 포함하지 않는다.

## 수동 실행 경계

GitHub Actions의 **퇴역 이미지 참조 읽기 전용 확인**은 수동 실행만 지원한다.
대표 계정, main, 최초 실행 시도, 저장된 SSH 호스트 지문을 검사하고 공유 배포
동시 실행 그룹에서 대기한다. 합성 검사를 통과한 공개 helper 한 파일만
관리자 전용 임시 폴더로 전송하고 SHA256을 대조한다.

출력은 같은 파일의 닫힌 스키마 검사기를 다시 해시 확인해 검사한 뒤에만 공개한다.
종료 코드 0은 `COMPLETE_STABLE`, 2는 `INCOMPLETE` 또는 `CHANGED`다.
정리 대상은 이번 실행의 임시 helper와 빈 임시 폴더뿐이다.
업무 데이터 변경은 없지만 실행 과정에 임시 코드 전송·삭제가 있으므로
운영 실행은 별도로 승인받은 차례에 수행한다. 이 PR의 업로드는 실행 승인이 아니다.

후속 삭제는 현재 백업 증거, 정확한 태그·다른 참조 검토, 삭제 직전 재확인,
대상별 비강제 삭제 계획을 별도로 확정해야 한다. 이 helper는 삭제 계획을 실행하지 않는다.

## 검사와 근거

로컬 합성 검사:

```sh
python3 -I -B -m unittest discover -s deploy/naver/tests -p 'test_retired_image_*.py' -v
```

서버·실제 Docker를 사용하지 않는 fixture로 중지 컨테이너 참조, 누락·변경,
잘린 ID, 태그·오류 원문 누출, 자원 상한, 고정 읽기 명령과 workflow 경계를 검사한다.
실제 Linux Docker 운영 조회와 현재 후보 참조는 별도 실행 증거가 필요하다.

- [Docker container ls: 전체 상태와 ancestor 필터](https://docs.docker.com/reference/cli/docker/container/ls/)
- [Docker image ls: 전체 이미지·중복 태그·Size 의미](https://docs.docker.com/reference/cli/docker/image/ls/)
- [Docker API 이력: Parent 필드의 제한](https://docs.docker.com/reference/api/engine/version-history/)
- [Docker 활성 이미지 저장소 전환의 범위](https://docs.docker.com/engine/storage/containerd/)
