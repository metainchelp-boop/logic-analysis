"""네이버 응답에서 **남길 칸만** 적은 목록 (설계 v1.8 · 반박 H10).

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

# 통계 지표 — 명세에 있는 이름만 요청할 수 있다. 합계(SummaryStatMap)에는 구매 지표가 없다.
STAT_FIELDS_SUMMARY = frozenset({
    "impCnt", "clkCnt", "salesAmt", "ccnt", "viewCnt", "cpc", "ctr", "avgRnk", "drtCrto",
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
