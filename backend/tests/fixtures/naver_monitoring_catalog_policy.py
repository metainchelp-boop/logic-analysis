"""Exact policy functions from product 0a302856c6177c4f53145abaf9ed31b6a39654f3.

Only the dependency namespace is supplied by the synthetic test; no product or network is imported.
"""


def allowed(context, row):
    """기존 verified 범위만: 현재 명시 번호의 자동 짝/이름 불일치, 충돌과 이름 후보는 확인 불가."""
    return block_reason(context, row) is None


def block_reason(context, row):
    """확정과 화면이 같은 첫 거부 사유를 쓴다. 범위 밖 업체의 신원은 반환하지 않는다."""
    ctx, scope = context.ctx, context.scope
    if context.source_state != "accepted":
        return "source-" + context.source_state
    if scope.kind not in (SC.ALL, SC.MINE):
        return "confirmation-not-permitted"
    if row is None:
        return "pair-unavailable"
    if row["state"] != S.PAIR_AUTO and not (row["state"] == S.PAIR_BLOCKED and row["code"] == M.B_NAME_DIFFERENT):
        return (row["code"] if row["state"] == S.PAIR_BLOCKED and row["code"] else
                "explicit-account-required" if row["state"] == S.PAIR_CANDIDATE else "pair-unavailable")
    pid, cid = row["possibility_id"], row["customer_id"]
    if pid not in context.visible_ids:
        return "confirmation-not-permitted"
    own, company, account = ctx.owns.get(pid), context.companies.get(pid), ctx.accounts.get(cid)
    if own is None or SC.ACT_CONFIRM_LINK not in SC.allowed_actions(ctx.org, scope, own):
        return "confirmation-not-permitted"
    if not company:
        return "company-unavailable"
    if not account or account["present"] != 1:
        return "account-unavailable"
    if W.link_holders(ctx, pid, cid) or row.get("claimed_elsewhere"):
        return "account-claimed-elsewhere"
    if any(d.possibility_id == pid and d.customer_id == cid for d in ctx.live_decisions):
        return "pair-already-decided"
    # 계정 신원 확인은 현재 번호·이관·담당으로 결정한다. 계약 종료일과
    # 관리 단계는 수집 주기이며 구형 광고 실행 handle의 자격 조건이 아니다.
    return None
