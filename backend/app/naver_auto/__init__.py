"""네이버 광고 자동운영(/naver/) — 보는 범위 판정 모듈.

설계: docs/superpowers/specs/2026-09-27-naver-ai-autopilot-design.md (v1.5 착수 순서 · v1.4 개인화).

1차(지금)는 **판정만** 한다.
- ``org_snapshot`` — ① 전산 ``GET /api/ad-sync/org-snapshot`` 응답을 읽고 검사한다(전부 받거나 전부 버린다).
- ``scope`` — 누가 어떤 광고주를 보고, 알림을 받고, 승인하고, 멈출 수 있는지 판정하는 **한 곳**.

규칙:
- 순수 함수만 둔다. 저장(DB)·네트워크·웹 프레임워크를 모른다.
- ③ 광고센터의 역할·팀·담당 칸(users.role · team_id · owner_id)을 읽지 않는다. 사람은 ① 직원 번호(idx)로만 안다.
- ``main.py`` 에 연결하지 않았다 — 지금 서비스 동작은 하나도 바뀌지 않는다.
  2차(엔진)와 3차(/naver/ 화면 API)가 이 모듈을 그대로 import 한다.
"""
