"""업체 목록 5칸 분리 — 어느 칸에 들어가는지 정하는 규칙 한 곳 (2026-08-28 대표 확정).

    ▶ 진행중   추적이 살아 있는 업체 — 기본으로 열리는 칸
    ↩ 환불중   전산 단계가 「환불중」 — 추적은 자동으로 멈춰 있다
    ⏸ 홀딩중   전산 단계가 「홀딩중」 — 재개되면 다음 날 04:00 에 자동 복귀
    🗑 삭제 필요  더 이상 추적할 이유가 없는 등록건 (사유 배지로 갈라 본다)
    🔍 확인 필요  수집이 5회 연속 실패해 포기된 키워드를 가진 업체 — **고칠 것**

⚠️ 「삭제 필요」와 「확인 필요」를 한 칸에 넣지 않는다(대표 확정).
   삭제 필요는 **지울 것**이고 확인 필요는 **키워드 한 글자만 고치면 되살아나는 것**이다.
   섞어 두면 고칠 수 있는 업체를 지우게 되고, 지우는 순간 그 업체의 순위 기록이
   통째로 사라져 되돌릴 수 없다.

⚠️ 「확인 필요」 기준을 「순위가 한 번도 안 잡힌 키워드」로 잡지 않았다(2026-08-28 실측).
   그런 키워드가 260개인데 그중 **251개는 수집분이 멀쩡히 있는 「300위 밖」**이었다.
   검색어는 정상이고 상품이 안 보이는 것뿐이라 지울 것도 고칠 것도 아니다.
   그대로 넣었으면 260건짜리 목록이 돼 아무도 손을 못 대는 화면이 됐다.
   진짜 신호는 **수집 5회 소진**(다섯 번 시도하고 포기) 하나다.

⚠️ 의존성 없음(표준 라이브러리만) — 배포 회귀 게이트가 fastapi 없이 import 한다
   (split_rule.py · tracking_eligibility.py 와 같은 이유).
"""

STAGE_REFUND = "환불중"
STAGE_HOLD = "홀딩중"
STAGE_EXPIRED = "계약 만료"

BUCKET_RUN = "run"        # 진행중
BUCKET_REFUND = "refund"  # 환불중
BUCKET_HOLD = "hold"      # 홀딩중
BUCKET_DELETE = "delete"  # 삭제 필요
BUCKET_CHECK = "check"    # 확인 필요


def _norm(s):
    """단계 이름 비교용 — 띄어쓰기를 지운다.

    ⚠️ 전산 단계명은 「계약 만료」처럼 공백이 섞여 오고, 표기가 흔들린다.
       공백을 그대로 비교하면 그 단계가 조용히 어느 칸에도 안 잡힌다
       (이 저장소에서 반복된 함정 — 담당자 변경·수집 자격 판정에서도 같은 일이 있었다).
    """
    return (s or "").replace(" ", "").strip()


def delete_reasons(row, today):
    """이 업체가 「삭제 필요」인 사유 목록(없으면 빈 목록).

    한 업체가 여러 사유에 걸릴 수 있어 목록으로 돌려준다 — 화면이 배지로 전부 보여준다.
    """
    out = []
    stage = _norm(row.get("contract_stage"))

    if stage == _norm(STAGE_EXPIRED):
        out.append("계약 만료")

    tu = (row.get("track_until") or "").strip()
    if tu and tu < today:
        out.append("기간 지남")

    if (row.get("role") or "advertiser") != "advertiser":
        out.append("광고주 아님")

    # ⚠️ 「전산에 없음」은 단계를 한 번도 못 받은 업체다. 다만 배포 직후에는 전부
    #    그 상태이므로, 동기화를 한 번이라도 돌린 뒤에만(synced=True) 사유로 센다.
    #    안 그러면 배포하자마자 전 업체가 삭제 필요로 뜬다.
    if row.get("_synced") and not stage:
        out.append("전산에 없음")

    return out


def classify(row, today, needs_check=False):
    """이 업체가 들어갈 칸 하나.

    ⚠️ 순서가 규칙이다 — 앞의 것이 이긴다.
       ① 환불중·홀딩중은 「지금 멈춘 상태」라 무엇보다 먼저 알아야 한다.
          기간이 지났더라도 환불 처리 중이면 그건 환불 담당이 볼 일이지 삭제할 일이 아니다.
       ② 삭제 필요가 확인 필요보다 앞선다 — 지울 업체의 키워드를 고칠 이유가 없다.
    """
    stage = _norm(row.get("contract_stage"))
    if stage == _norm(STAGE_REFUND):
        return BUCKET_REFUND
    if stage == _norm(STAGE_HOLD):
        return BUCKET_HOLD
    if delete_reasons(row, today):
        return BUCKET_DELETE
    if needs_check:
        return BUCKET_CHECK
    return BUCKET_RUN
