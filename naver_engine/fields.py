"""네이버 응답 · ① 조직 스냅숏에서 **남길 칸만** 적은 목록 (설계 v1.8 · 반박 H10 · S7).

지울 칸을 적는 방식이 아니다 — 네이버가 새 칸(개인정보일 수도 있다)을 더해도 여기 없으면 저절로 빠진다.
빠지는 칸 예: 하위 계정의 ``ownerNaverId``(계정책임자 네이버 아이디) · 관리계정의 ``naverId`` ·
캠페인의 추적 주소(``trackingUrl``) · 비즈채널의 사업자 정보(``businessInfo``).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

# 하위 광고계정(ChildAdAccount)
CHILD_ACCOUNT = ("customerId", "adAccountNo", "adAccountName", "accountRole")

# 관리계정(ManagerAccount) — 안쪽 managerAccount 에서 꺼내 한 층으로 편다
MANAGER_ACCOUNT_TOP = ("managerAccountNo",)
MANAGER_ACCOUNT_DETAIL = ("name", "childAdAccountCount", "deleted", "disabled")

# 캠페인(Campaign)
CAMPAIGN = (
    "nccCampaignId", "customerId", "name", "campaignTp", "status", "statusReason", "userLock",
    "dailyBudget", "useDailyBudget", "usePeriod", "periodStartDt", "periodEndDt", "deliveryMethod",
    "sharedBudgetId", "sharedDailyBudget", "sharedBudgetLock", "editTm", "delFlag",
)

# 비즈머니(Bizmoney) — customerId 는 대조에만 쓰고 남긴다
BIZMONEY = ("customerId", "bizmoney", "budgetLock", "refundLock")

# 비즈채널(BusinessChannel) — 짝 확인 미리보기에서만(저장하지 않음)
CHANNEL = ("nccBusinessChannelId", "customerId", "name", "channelTp", "channelKey", "status")

# ① 전산 조직 스냅숏(``GET /api/ad-sync/org-snapshot``) — 엔진 저장소가 수락본을 남길 칸(설계 v1.8 S7 · M12).
# ① 계약 §9 에 적힌 칸 그대로다. 전화·주민번호·급여·로그인 아이디는 ① 가 보내지 않고, 보내더라도 여기 없으면 남지 않는다.
ORG_TEAM = ("idx", "name", "level", "parent_idx", "is_system")
ORG_EMPLOYEE = ("idx", "name", "team_idx", "is_manager", "is_top_manager", "status", "is_deleted", "is_management",
                "is_sales", "naver_sales_view")
ORG_SALES_CONTRACT = ("possibility_id", "seller_emp_idx")
ORG_OWNER = ("possibility_id", "manage_emp_idx", "sub_manage_emp_idx", "prev_manage_owner_idx", "sales_emp_idx",
             "owner_source")

# 통계 지표 — 명세의 **요청** 이름(``fields`` 쿼리 목록)만 요청할 수 있다(응답 칸 이름 ``drtCrto`` 가 아니라 요청 이름 ``crto``).
# 합계 응답(SummaryStatMap)에는 구매 지표가 없어 합계로는 요청하지 않는다. 받은 값이 비면 0 이 아니라 모름이다.
STAT_FIELDS_SUMMARY = frozenset({
    "impCnt", "clkCnt", "salesAmt", "ccnt", "viewCnt", "cpc", "ctr", "avgRnk", "crto", "convAmt", "ror", "cpConv",
})
STAT_FIELDS_DAILY = STAT_FIELDS_SUMMARY | frozenset({"purchaseCcnt", "purchaseConvAmt", "purchaseRor"})
STAT_FIELDS = STAT_FIELDS_DAILY


def keep(record: Mapping[str, Any], allowed: Iterable[str]) -> dict:
    """목록에 있는 칸만 새 사전으로 옮긴다(원본은 건드리지 않는다)."""
    return {k: record[k] for k in allowed if k in record}


def keep_manager(record: Mapping[str, Any]) -> dict:
    out = keep(record, MANAGER_ACCOUNT_TOP)
    detail = record.get("managerAccount")
    if isinstance(detail, Mapping):
        out.update(keep(detail, MANAGER_ACCOUNT_DETAIL))
    return out
