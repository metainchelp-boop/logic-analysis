"""네이버 광고 상태의 원문과 표시용 해석. 수집·매칭 실패 또는 자동 조치 판정이 아니다."""
from collections.abc import Mapping
from datetime import datetime

# 네이버 공식 FAQ의 상태이유 표를 확인한 날: 2026-10-02.
# https://github.com/naver/searchad-apidoc/wiki/FAQ
# 이유 코드를 status의 열거값으로 간주하지 않는다. ELIGIBLE 외 상태는 원문으로 남긴다.
_STATUSES = {"ELIGIBLE": "노출 가능한 상태"}
_ENTITY_IDS = {"campaign": "nccCampaignId", "adgroup": "nccAdgroupId", "ad": "nccAdId",
               "keyword": "nccKeywordId", "ad_extension": "nccAdExtensionId",
               "business_channel": "nccBusinessChannelId"}
_REASONS = {
    "ELIGIBLE": "노출 가능한 상태",
    "CAMPAIGN_DELETED": "캠페인 삭제 상태", "CAMPAIGN_PAUSED": "캠페인 사용자 중지",
    "CAMPAIGN_PENDING": "캠페인 노출 시작일 전", "CAMPAIGN_ENDED": "캠페인 노출 종료일 지남",
    "CAMPAIGN_LIMITED_BY_BUDGET": "캠페인 예산 한도 도달",
    "BUSINESS_CHANNEL_PAUSED": "사업채널 중지 상태",
    "BUSINESS_CHANNEL_DISAPPROVED": "사업채널 검수 보류 또는 반려",
    "BUSINESS_CHANNEL_UNDER_REVIEW": "사업채널 검수 등록 상태",
    "BUSINESS_CHANNEL_ABNORMAL_INTERLOCK": "사업채널 외부 연동 이상",
    "PC_BUSINESS_CHANNEL_APPROVED": "PC 사업채널 통과에 따른 일부 노출",
    "PC_BUSINESS_CHANNEL_DISAPPROVED": "PC 사업채널 검수 보류 또는 반려",
    "PC_BUSINESS_CHANNEL_ABNORMAL_INTERLOCK": "PC 사업채널 외부 연동 이상",
    "PC_BUSINESS_CHANNEL_UNDER_REVIEW": "PC 사업채널 검수 등록 상태",
    "MOBILE_BUSINESS_CHANNEL_APPROVED": "모바일 사업채널 통과에 따른 일부 노출",
    "MOBILE_BUSINESS_CHANNEL_DISAPPROVED": "모바일 사업채널 검수 보류 또는 반려",
    "MOBILE_BUSINESS_CHANNEL_ABNORMAL_INTERLOCK": "모바일 사업채널 외부 연동 이상",
    "MOBILE_BUSINESS_CHANNEL_UNDER_REVIEW": "모바일 사업채널 검수 등록 상태",
    "GROUP_DELETED": "광고그룹 삭제 상태", "GROUP_PAUSED": "광고그룹 사용자 중지",
    "GROUP_LIMITED_BY_BUDGET": "광고그룹 예산 한도 도달",
    "GROUP_PAUSED_BY_INVALID_TARGET": "광고그룹 타겟 설정 오류",
    "KEYWORD_DELETED": "키워드 삭제 상태", "KEYWORD_PAUSED": "키워드 사용자 중지",
    "KEYWORD_DISAPPROVED": "키워드 검수 보류", "KEYWORD_DENIED": "키워드 검수 반려",
    "KEYWORD_UNDER_REVIEW": "키워드 검수 등록 상태",
    "AD_DELETED": "소재 삭제 상태", "AD_PAUSED": "소재 사용자 중지",
    "AD_ABNORMAL_INTERLOCK": "소재 외부 연동 이상", "AD_DISAPPROVED": "소재 검수 보류 또는 반려",
    "AD_UNDER_REVIEW": "소재 검수 등록 상태", "AD_EXTENSION_DELETED": "확장소재 삭제 상태",
    "AD_EXTENSION_PAUSED": "확장소재 사용자 중지",
    "AD_EXTENSION_NOT_SCHEDULED": "확장소재 요일 또는 시간 설정에 따른 일시중지",
    "AD_EXTENSION_DISAPPROVED": "확장소재 검수 보류 또는 반려",
    "AD_EXTENSION_UNDER_REVIEW": "확장소재 검수 등록 상태",
    "AD_EXTENSION_PENDING": "확장소재 설정 노출 기간 밖",
    "AD_EXTENSION_ABNORMAL_INTERLOCK": "확장소재 외부 연동 이상",
    "LACK_OF_ACCOUNT_BALANCE": "계정 예산 부족", "REFUND_IN_PROGRESS": "계정 환불 진행 중",
}


def _explain(code, meanings, missing):
    if code is not None and not isinstance(code, str):
        raise ValueError("광고 상태와 사유는 원문 문자열 또는 미제공 값이어야 합니다")
    if code is None or code == "":
        return {"code": code, "meaning": missing, "code_state": "not_provided"}
    meaning = meanings.get(code)
    return {"code": code, "meaning": meaning or "해석 미확인", "code_state": "known" if meaning else "unknown"}


def describe(entity, record, *, checked_at, parents=()):
    """조회한 대상과 상위 응답을 원문 그대로 해석한다. 자동 조치/정상 판정은 하지 않는다.

    parents는 호출자가 관계를 확인한 ``(entity, record, checked_at)`` 묶음이다.
    각 상위 응답의 실제 조회 시각을 받으며 미조회 상위 원인이나 하위 상태를 추정하지 않는다.
    입력을 수정하거나 원천을 조회하지 않고, 상태·사유·대상 번호 외 응답 필드는 내보내지 않는다.
    모르는 계층·번호 누락·문자열 아닌 코드·시간대 없는 시각은 ValueError로 거절한다.
    """
    if not isinstance(entity, str) or entity not in _ENTITY_IDS or not isinstance(record, Mapping):
        raise ValueError("확인 가능한 광고 대상 계층과 응답이 필요합니다")
    identifier = record.get(_ENTITY_IDS[entity])
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("광고 대상 번호가 필요합니다")
    if not isinstance(checked_at, datetime) or checked_at.utcoffset() is None:
        raise ValueError("확인 시각은 시간대가 있는 시각이어야 합니다")
    return {"source": "naver_ad_status", "entity": entity, "entity_id": record[_ENTITY_IDS[entity]],
            "checked_at": checked_at.isoformat(), "status": _explain(record.get("status"), _STATUSES, "상태 미제공"),
            "reason": _explain(record.get("statusReason"), _REASONS, "상세 사유 미제공"),
            "parents": [describe(kind, row, checked_at=at) for kind, row, at in parents]}
