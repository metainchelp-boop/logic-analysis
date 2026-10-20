"""저장판 근거의 전략 초안. 저장·승인·광고 실행은 호출자의 별도 책임이다.

규칙 초안은 네트워크를 쓰지 않는다. 제공자 호출은 명시적으로 전달된 경우에만
수행하며, 모델의 숫자는 알려진 지표 참조로만 받아 서버에서 표시한다.
"""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import math
import re

from . import report_enrichment as E, reporting as R, strategy_validation as SV, setup_strategy_evidence as SE


DOCUMENT_FIELDS = frozenset({"diagnosis", "direction", "appeal_points", "competitive_response",
    "weekly_plan", "monthly_plan", "funnel_comment", "ab_comment", "shared_comment"})
METRIC_FIELDS = ("current", "previous", "absolute", "percent")
COMPETITIVE_COMMENT = "상품·시장·경쟁 자료가 미연결 상태입니다. 경쟁 우위나 고객 특성을 확정하지 않고 출처가 있는 자료 연결 후 소구를 제안합니다."
PRODUCT_COMPETITIVE_COMMENT = "시장·경쟁 자료는 미연결 상태입니다. 경쟁 우위나 고객 특성을 확정하지 않고 비교 자료 연결 후 대응을 검토합니다."
FUNNEL_COMMENT = "현재 근거는 노출·클릭·일반 광고 전환입니다. 장바구니·구매·재구매와 고객 전체 여정은 미연결이며, 합산 수치로 특정 소재나 랜딩을 원인으로 확정하지 않습니다."
AB_COMMENT = "현재 자료는 계정×일 관찰 비교입니다. 실험군·배분·표본·전환 지연·외부 변경이 검증되지 않아 통제된 A/B 결과나 승자로 판정하지 않습니다."
_PROMOTED_EXPLORATORY = re.compile(r"확정\s*(?:승자|무승부|동등)[^.!?\n]{0,20}(?:나왔|확인됐|판정했|결정됐|입니다)|통계적(?:으로)?\s*유의|"
    r"(?:승자|무승부|동등성|인과\s*(?:개선|효과))[^.!?\n]{0,35}(?:입증됐|입증된|입증합니다|검증됐|검증된|확정됐|확정된|확정합니다)|"
    r"(?:자동\s*(?:입찰|광고|예산)|광고\s*집행)[^.!?\n]{0,20}(?:실행했|반영했|확대했|변경했|완료했)")
_PROMOTED_RANDOMIZED = re.compile(r"(?:타겟|타기팅|랜딩)[^.!?\n]{0,30}(?:모든|전체|전수)[^.!?\n]{0,20}(?:검증했|확인했|검증됐|확인됐)|"
    r"(?:무가정|가정\s*없이|가정이\s*검증)[^.!?\n]{0,30}(?:승자|동등|인과|검증)|"
    r"현재\s*(?:계정|업체|광고주)[^.!?\n]{0,40}(?:승자|동등성)[^.!?\n]{0,20}(?:나왔|입니다|판정했|확인했)")
_STATUS = frozenset({"ready", "no_previous", "scope_changed", "insufficient_data", "zero_denominator"})
_VALUE_STATUS = frozenset({"ready", "partial", "zero_denominator", "unavailable", "legacy_unavailable"})
_REF = re.compile(r"\{\{metric:([a-z_]+)\.(current|previous|absolute|percent)\}\}")
_CASE_REF = re.compile(r"\{\{case:([1-5])\.([a-z_]+(?:\.[a-z_]+)?)\}\}")
_PLAN_LIMIT_FIELDS = ("single_increase_percent", "single_decrease_percent", "rolling_day_increase_percent",
                      "rolling_day_decrease_percent", "weekly_increase_requires_approval_percent")
PLAN_NUMERIC_FIELDS = ("target_value", "daily_spend_cap", "absolute_bid_cap", "experiment_days", "loss_cap",
                       "monthly_spend_cap", "measurement_lag_days", "minimum_clicks", "minimum_conversions") + _PLAN_LIMIT_FIELDS
_PLAN_REF = re.compile(r"\{\{plan:(" + "|".join(PLAN_NUMERIC_FIELDS) + r")\}\}")
PRODUCT_FIELDS = ("name", "category", "price", "review_count", "rating", "delivery_info", "return_info",
                  "gift_info", "certification", "review_section", "spec_table", "source_status")
_PRODUCT_REF = re.compile(r"\{\{product:([1-3])\.(" + "|".join(PRODUCT_FIELDS) + r")\}\}")
MARKET_FIELDS = ("keyword", "source_status", "observed_at", "recorded_at", "sample_count", "price_count",
                 "price_min", "price_median", "price_max")
_MARKET_REF = re.compile(r"\{\{market:(1)\.(" + "|".join(MARKET_FIELDS) + r")\}\}")
FUNNEL_FIELDS = ("source_status", "coverage", "count_coverage", "value_coverage", "purchase_count", "purchase_value",
                 "purchase_cvr", "purchase_cpa", "purchase_roas")
_FUNNEL_REF = re.compile(r"\{\{funnel:(" + "|".join(FUNNEL_FIELDS) + r")\}\}")
SETUP_SUMMARY_FIELDS = SE.SUMMARY_FIELDS
SETUP_ENTITY_FIELDS = SE.ENTITY_FIELDS
SETUP_FIELDS = SETUP_SUMMARY_FIELDS + SETUP_ENTITY_FIELDS
_SETUP_REF = re.compile(r"\{\{setup:([0-8])\.(" + "|".join(SETUP_FIELDS) + r")\}\}")
_SETUP_PAST_CAUSE = re.compile(
    r"때문에|덕분에|인해|원인(?:으로\s*)?(?:입니다|확정됐|입증됐|증명됐)|"
    r"원인(?:으로\s*)?(?:판단|해석|설명)(?:됩|했|합|됐)|"
    r"(?:성과|전환|효율)[^.!?\n]{0,24}(?:향상|개선|증가)[^.!?\n]{0,12}기여했|"
    r"(?:성과|전환|효율)[^.!?\n]{0,12}(?:개선했|증가시켰|하락시켰|높였)")

FUNNEL_CAVEAT = "별도 플랫폼 구매 전환은 실제 결제 주문·장바구니·환불·재구매·이익과 별도입니다. 반복 클릭·구매 이벤트의 비율은 고객별 순차 여정이나 이탈률이 아니며 태그 정상·최종 귀속을 보증하지 않습니다."
_UNSUPPORTED_FUNNEL = re.compile(r"고객\s*(?:이탈|여정|경로|성향|특성)|이탈률|단계별\s*이탈|순차|누수|"
    r"(?:태그|측정|추적)[^.!?\n]{0,40}(?:정상|정확하|정확한|모든\s*구매|누락\s*없[이음는])|"
    r"(?:구매\s*전환|최종\s*귀속)[^.!?\n]{0,30}(?:최종\s*확정|확정된|확정됐)|"
    r"고객[^.!?\n]{0,20}동선|구매\s*고객|재구매\s*고객|유일\s*고객|고유\s*고객|"
    r"(?:장바구니|실제\s*주문|결제|환불|재구매|순이익|마진)[^.!?\n]{0,40}(?:확인됐|확인된|발생|증가|감소|많|적|보장|없는|없음|없습니다)|"
    r"일반\s*전환[^.!?\n]{0,40}구매(?:로|임|입니다|\s*증거)")
MARKET_CAVEAT = "경쟁 자료는 저장 검색 표본이며 다음 계획 검토에만 사용합니다. 수집 시각과 검색·상품 비교 조건이 독립 확인되지 않아 현재 시장·광고 경쟁·성과 원인을 확정하지 않습니다."
MARKET_UNAVAILABLE_COMMENT = "시장·경쟁 자료가 미연결 상태입니다. 업계 추세·경쟁 광고·경쟁 성과를 확인할 수 없어 대응 판단을 보류하고 비교 자료 연결 후 다음 계획을 검토합니다."
_UNSUPPORTED_COMPETITION = re.compile(r"최저가|최고가|가장\s*저렴|경쟁\s*우위|가격\s*우위|차익|점유율|"
    r"시장\s*전체|업계\s*전체|산업\s*전체|경쟁\s*사?\s*광고비|경쟁\s*예산|경쟁\s*사?\s*매출|"
    r"원인|인과|입증|증명|확실[한히]|보장|수요\s*증가|수요\s*감소|때문|덕분|인해|영향으로|우월|앞[서섬]|"
    r"보다\s*(?:더\s*)?(?:저렴|싸|낮|우수|높|빠르)|"
    r"경쟁\s*(?:사|업체|상품|제품|스토어|브랜드)[^.!?\n]{0,60}(?:느[리림]|빠르|낮|높|좋|나쁘|부족|많|적|강|약|비싸|저렴|우수|열등|없|있|합니다|입니다)|"
    r"인기|잘\s*팔|고객(?:이|들이)?\s*몰|판매\s*호조|주문\s*폭주|"
    r"(?:판매(?:가|량)?|주문(?:수|량)?|매출|유입)[^.!?\n]{0,20}(?:급증|증가|감소|상승|하락|늘|줄|오르|올[랐라]|떨어|많|적|폭증)|"
    r"업계\s*(?:추세|동향|현황)|시장\s*(?:수요|추세|성장|축소)")
PRODUCT_CAVEAT = "상품 자료는 저장 관측이며 원본 수집 시각이 미확인입니다. 현재 가격·혜택·서비스와 실제 구매 동기를 확정하지 않고 담당자가 재확인해야 합니다."
APPEAL_TITLES = ("가격 정보 제시", "리뷰 정보 설명", "배송 안내 이해", "반품 안내 이해", "선물 안내 이해",
                 "인증 정보 확인", "상품 정보 구성")
_APPEAL_SUFFIXES = ("효과를 비교 검증합니다.", "여부를 비교 검증합니다.")
_UNSUPPORTED_APPEAL = re.compile(r"최저가|최고가|최고의|가장\s*저렴|업계\s*최[고저]|유일한|무료\s*배송|"
    r"치료|완치|예방|효능|보장|확실[한히]|입증된|인증\s*받[은았]|증명된")
_LABELS = {key: (label, unit) for key, label, unit, _ in E.METRICS}
_METRIC_TIMES = {"current": "현재", "previous": "직전", "absolute": "차이", "percent": "상대 증감률"}
_DUPLICATE_METRIC_PREFIX = re.compile(r"(?<![가-힣A-Za-z0-9_])(?P<label>" +
    "|".join(re.escape(label) for label in sorted({row[0] for row in _LABELS.values()}, key=len, reverse=True)) +
    r")(?:\s+(?P<time>현재|직전|차이|상대 증감률))?(?:은|는|이|가|을|를|:)?\s*"
    r"(?P<reference>\{\{metric:(?P<key>[a-z_]+)\.(?P<field>current|previous|absolute|percent)\}\})")
_QUANTITY_UNITS = r"퍼센트포인트|퍼센트|개월|시간|주일|원|배|건|회|개|명|번|일|주|달|월|년|분|초"
_NATIVE_ONES = r"한|두|세|네|다섯|여섯|일곱|여덟|아홉"
_KOREAN_QUANTITY = re.compile(r"(?<![가-힣A-Za-z0-9_])(?P<number>[일이삼사오육칠팔구십백천만억]+|"
    r"(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)(?:" + _NATIVE_ONES + r")?|" + _NATIVE_ONES +
    r")\s*(?P<unit>" + _QUANTITY_UNITS + r")")
_IDIOMATIC_PERIOD = re.compile(r"(?<![가-힣A-Za-z0-9_])(?:하루|이틀|사흘|나흘|닷새|엿새|이레|여드레|아흐레|열흘|일주일)")
# 닫힌 명사 문법의 해당 토큰만 제외한다. 뒤의 다른 수량은 계속 검사한다.
_NOUN_QUANTITY_CONTEXTS = (
    re.compile(r"(?<![가-힣A-Za-z0-9_])(?P<quantity>오일)(?=\s+(?:상품|제품)(?=$|[\s.,!?은는이가을를의]))"),
    re.compile(r"(?<![가-힣A-Za-z0-9_])(?:팀|조직)의\s+(?P<quantity>일원)으로(?=$|[\s.,!?])"),
)
_UNIT_AT_START = re.compile(r"(?:" + _QUANTITY_UNITS + r")")
_UNIT_BEFORE_REFERENCE = re.compile(r"(?<![가-힣A-Za-z0-9_])(?:" + _QUANTITY_UNITS + r")\s*$")
# 단위 뒤 조사·서술형을 확인한다. 한글이면 모두 제외하면 '일원입니다'도 통과한다.
_QUANTITY_SUFFIX_TOKENS = frozenset(("이었습니다|이었다면|이었다|이라면|이라도|이라고|이라서|이므로|이지만|이기에|"
    "입니다|였습니다|이며|이고|이면|이나|이다|인|라서|여서|짜리|뿐|나|"
    "으로|에서|부터|까지|보다|마다|동안|정도|이상|이하|이내|내|미만|초과|"
    "은|는|이|가|을|를|의|에|로|와|과|도|만|씩|당|간|째|대").split("|"))
_QUANTITY_SUFFIX_BY_FIRST = {first: tuple(token for token in _QUANTITY_SUFFIX_TOKENS if token[0] == first)
    for first in {token[0] for token in _QUANTITY_SUFFIX_TOKENS}}
_QUANTITY_WORD = re.compile(r"[가-힣A-Za-z0-9_]+")
_UNIT_NOUN_PREFIXES = ("원인", "원가", "회사", "배경", "개발", "개선", "개인")
TEXT_LIMITS = {"diagnosis": 1800, "direction": 1400, "competitive_response": 500,
               "funnel_comment": 600, "ab_comment": 600, "shared_comment": 3000}
PLAN_LIMITS = {"action": 300, "reason": 500, "criterion": 500}
PROMPT_VERSION = "marketing-strategy-v2"
LEARNING_PROMPT_VERSION = "marketing-strategy-learning-v3"
PRODUCT_PROMPT_VERSION = "marketing-strategy-product-v1"
MARKET_PROMPT_VERSION = "marketing-strategy-market-v1"
FUNNEL_PROMPT_VERSION = "marketing-strategy-funnel-v1"
LEARNING_METADATA = {
    "industry": frozenset({"food", "pet", "home", "beauty", "fashion", "local_service", "b2b", "other"}),
    "goal": frozenset({"impressions", "clicks", "cpa", "roas", "ctr", "cvr"}),
    "ad_type": frozenset({"powerlink", "shopping", "brand", "place", "display", "other"}),
    "budget_band": frozenset({"under_300k", "300k_1m", "1m_3m", "over_3m"}),
}
_LEARNING_METRICS = frozenset({"impressions", "clicks", "spend", "conversions", "conversion_value"})
_OUTCOME_LABELS = {"observation": "관찰 자료", "unknown": "측정 근거 미확인", "winner": "검수된 실험 우세",
    "inconclusive": "판정 유보", "invalid": "실험 조건 부적합"}


def _learning_error():
    raise StrategyRefused("LEARNING_CONTEXT_INVALID")


def _learning_number(value, *, signed=False):
    try:
        return _number(value, signed=signed)
    except StrategyRefused:
        _learning_error()


def _learning_bool(value):
    if type(value) is not bool:
        _learning_error()
    return value


def _learning_period(evidence):
    try:
        start, end = (date.fromisoformat(evidence[key]) for key in ("period_start", "period_end"))
        days = (end-start).days+1
        if not 1 <= days <= 367:
            _learning_error()
        return days
    except (KeyError, TypeError, ValueError):
        _learning_error()


def _learning_metrics(evidence, *, conversions_usable):
    if not isinstance(evidence, dict) or not _LEARNING_METRICS <= set(evidence):
        _learning_error()
    values = {key: _learning_number(evidence[key]) for key in sorted(_LEARNING_METRICS)}
    if any(values[key] is not None and type(values[key]) is not int for key in ("impressions", "clicks")):
        _learning_error()
    if values["clicks"] is not None and values["impressions"] is not None and values["clicks"] > values["impressions"]:
        _learning_error()
    if not conversions_usable:
        values.update(conversions=None, conversion_value=None)
    return values


def _learning_compact_performance(value):
    from . import learning_assets as LA
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _LEARNING_METRICS | {"days", "measurement_complete", "lag_mature", "conversion_definition", "value_basis"}:
        _learning_error()
    if type(value["days"]) is not int or not 1 <= value["days"] <= 367:
        _learning_error()
    complete, mature = _learning_bool(value["measurement_complete"]), _learning_bool(value["lag_mature"])
    if (not isinstance(value["conversion_definition"], str) or value["conversion_definition"] not in LA.AUTO_CONVERSION_DEFINITIONS or
            not isinstance(value["value_basis"], str) or value["value_basis"] not in LA.AUTO_VALUE_BASES):
        _learning_error()
    metrics = _learning_metrics(value, conversions_usable=complete and mature and value["conversion_definition"] != "unknown")
    if complete and any(value[key] is None for key in _LEARNING_METRICS):
        _learning_error()
    return {**metrics, "days": value["days"], "measurement_complete": complete, "lag_mature": mature,
        "conversion_definition": value["conversion_definition"], "value_basis": value["value_basis"]}


def _learning_auto_facts(value, kind):
    from . import learning_assets as LA
    from . import observational_inference as OI
    from . import randomized_inference as RI
    try:
        if kind == "experiment":
            required = LA._EXPERIMENT_FACTS - {"source_status", "recorded_at", "source_at"}
            exploratory = isinstance(value, dict) and value.get("method") == OI.METHOD
            randomized = isinstance(value, dict) and value.get("method") == RI.METHOD
            if exploratory:
                required = required | {"exploratory_diagnostic"}
            if randomized:
                required = required | LA._RANDOMIZED_FACTS
            LA._fields(value, required)
            out = deepcopy(value)
            LA._enum(value["method"], {"two_proportion_fixed_horizon_95_80_v1", "observational_only_v1", OI.METHOD, RI.METHOD}, nullable=True)
            if randomized:
                result = RI.normalize_result(value["randomized_result"])
                if (value["observation_scope"] != list(LA.RANDOMIZED_SCOPE) or value["value_basis"] != "unknown"
                        or any(value[key] is not None for key in ("declared_control_sample", "declared_treatment_sample",
                            "control_daily_cap", "treatment_daily_cap", "baseline"))):
                    _learning_error()
                LA._integer(value["washout_hours"], minimum=1, maximum=23)
                LA._integer(value["minimum_impressions_per_block"], minimum=1, maximum=LA.MAX_VERSION)
                # Full exact-tail fractions and all fixed qualifiers remain in the
                # immutable asset. The model receives bounded anonymous conclusions
                # and intervals; references repeat the model/source limitations.
                out["randomized_result"] = {key: deepcopy(result[key]) for key in (
                    "evidence_grade", "decision", "winner", "randomized", "causal_claim", "assumptions_verified",
                    "effect_pp", "interval95_pp", "interval90_pp", "superiority_margin_pp", "equivalence_margin_pp",
                    "pair_count", "assignment_count", "reason_codes")}
            if exploratory:
                diagnostic = (None if value["exploratory_diagnostic"] is None
                    else OI.normalize_decision(value["exploratory_diagnostic"]))
                # The complete ledger stays in the learning asset. The model gets
                # closed anonymous diagnostic facts, never daily rows or identities.
                out["exploratory_diagnostic"] = (None if diagnostic is None else {key: diagnostic[key] for key in (
                    "evidence_grade", "decision", "recommended_arm", "causal_claim", "formal_equivalence",
                    "calibration_verified", "effect_percent", "margin_percent", "band", "paired_days",
                    "complete_week_blocks", "remainder_days", "reason_codes")})
            for key in ("declared_control_sample", "declared_treatment_sample"):
                if value[key] is not None:
                    LA._integer(value[key], minimum=1, maximum=10**9)
            if value["measurement_lag_days"] is not None:
                LA._integer(value["measurement_lag_days"], maximum=30)
            for key in ("experiment_spend_cap", "control_daily_cap", "treatment_daily_cap"):
                if value[key] is not None:
                    LA._number(value[key], minimum=1e-12, maximum=10**12)
            LA._enum(value["metric_role"], {"primary", "proxy"})
            LA._enum(value["plan_goal"], LA.METADATA_ENUMS["goal"])
            LA._enum(value["value_basis"], LA.AUTO_VALUE_BASES)
            if value["baseline"] is not None:
                LA._fields(value["baseline"], {"control", "treatment"})
                out["baseline"] = {key: _learning_compact_performance(value["baseline"][key]) for key in ("control", "treatment")}
            return out
        LA._fields(value, {"desired", "profile", "baseline", "followup"})
        return {"desired": LA._settings(value["desired"]), "profile": LA.auto_source_profile(value["profile"]),
            "baseline": _learning_compact_performance(value["baseline"]), "followup": _learning_compact_performance(value["followup"])}
    except (LA.S.StoreRefused, OI.DiagnosticInvalid, RI.InferenceInvalid, TypeError, ValueError):
        _learning_error()


def _learning_context(value):
    """서버가 권한 확인 후 검색한 검수 사례만 받는다. ID·자유 문안은 모델에 보내지 않는다."""
    from . import learning_assets as LA
    if (not isinstance(value, dict) or set(value) != {"version", "cases"} or type(value["version"]) is not int
            or value["version"] != 1 or not isinstance(value["cases"], list) or len(value["cases"]) > 5):
        _learning_error()
    cases, references, identities = [], [], set()
    for index, item in enumerate(value["cases"], 1):
        base_fields = {"asset_id", "version", "kind", "metadata", "evidence", "assessment"}
        auto_fields = {"source_summary", "lesson_codes", "confounder_codes"}
        if (not isinstance(item, dict) or set(item) not in (base_fields, base_fields | auto_fields)
                or not isinstance(item["asset_id"], str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", item["asset_id"])
                or type(item["version"]) is not int or not 1 <= item["version"] <= 2**53-1
                or item["asset_id"] in identities or item["kind"] not in {"performance", "setting_change", "experiment"}):
            _learning_error()
        identities.add(item["asset_id"])
        metadata = item["metadata"]
        if not isinstance(metadata, dict) or set(metadata) != set(LEARNING_METADATA):
            _learning_error()
        for key, allowed in LEARNING_METADATA.items():
            if metadata[key] is not None and (not isinstance(metadata[key], str) or metadata[key] not in allowed):
                _learning_error()
        evidence, assessment = item["evidence"], item["assessment"]
        if not isinstance(evidence, dict) or not isinstance(assessment, dict):
            _learning_error()
        outcome = assessment.get("outcome")
        if outcome not in _OUTCOME_LABELS:
            _learning_error()
        reasons = assessment.get("reason_codes")
        if (not isinstance(reasons, list) or len(reasons) > 16 or any(not isinstance(code, str)
                or code not in LA.REASON_CODES for code in reasons)):
            _learning_error()
        case = {"index": index, "kind": item["kind"], "metadata": deepcopy(metadata),
            "assessment": {"outcome": outcome, "reason_codes": list(reasons), "causal_claim": False}}
        automatic = "source_summary" in item
        if automatic:
            try:
                summary = LA.normalize_source_summary(item["source_summary"])
                lessons = LA._codes(item["lesson_codes"], LA.LESSON_CODES)
                confounders = LA._codes(item["confounder_codes"], LA.CONFOUNDER_CODES)
            except (ValueError, TypeError, LA.S.StoreRefused):
                _learning_error()
            if (item["kind"] != {"experiment_observation": "experiment", "execution_result": "setting_change"}[summary["kind"]]
                    or outcome != "observation" or assessment.get("causal_claim") is not False or assessment.get("winner") is not None
                    or assessment.get("confidence_interval") is not None):
                _learning_error()
            case.update(source_summary=summary, lesson_codes=lessons, confounder_codes=confounders)
        if item["kind"] in {"performance", "experiment"}:
            complete = _learning_bool(evidence.get("measurement_complete"))
            mature = _learning_bool(evidence.get("lag_mature"))
            definition = evidence.get("conversion_definition")
            if definition not in (LA.AUTO_CONVERSION_DEFINITIONS if automatic else LA.CONVERSION_DEFINITIONS):
                _learning_error()
            clean = {"days": _learning_period(evidence), "measurement_complete": complete, "lag_mature": mature,
                "conversion_definition": definition}
            usable = complete and mature and definition != "unknown"
            if item["kind"] == "performance":
                if outcome != "observation" or assessment.get("causal_claim") is not False:
                    _learning_error()
                clean.update(_learning_metrics(evidence, conversions_usable=usable))
            else:
                for key in ("randomized", "one_variable", "allocation_valid", "independent_units"):
                    clean[key] = _learning_bool(evidence.get(key))
                if evidence.get("goal") not in LEARNING_METADATA["goal"] or evidence.get("status") not in {"planned", "running", "completed", "stopped"}:
                    _learning_error()
                clean.update(goal=evidence["goal"], status=evidence["status"],
                    min_sample_per_arm=_learning_number(evidence.get("min_sample_per_arm")),
                    mde_percent=_learning_number(evidence.get("mde_percent")))
                if ((clean["min_sample_per_arm"] is None and not automatic) or
                        (clean["min_sample_per_arm"] is not None and (type(clean["min_sample_per_arm"]) is not int or clean["min_sample_per_arm"] < 1)) or
                        (clean["mde_percent"] is None and not automatic) or
                        (clean["mde_percent"] is not None and not 0 < clean["mde_percent"] <= 100)):
                    _learning_error()
                clean.update(baseline_rate=_learning_number(evidence.get("baseline_rate")),
                    control_share=_learning_number(evidence.get("control_share")))
                if (clean["control_share"] is None and not automatic) or (clean["control_share"] is not None and not 0.1 <= clean["control_share"] <= 0.9):
                    _learning_error()
                if clean["baseline_rate"] is not None and not 0 < clean["baseline_rate"] < 1:
                    _learning_error()
                registered = evidence.get("preregistered_at")
                clean["preregistered"] = False
                if registered is not None:
                    try:
                        registered_at = datetime.fromisoformat(registered)
                        clean["preregistered"] = (registered_at.utcoffset() is not None and
                            registered_at.astimezone(R.KST).date() < date.fromisoformat(evidence["period_start"]))
                    except (TypeError, ValueError):
                        _learning_error()
                for arm in ("control", "treatment"):
                    clean[arm] = _learning_metrics(evidence.get(arm), conversions_usable=usable)
                if automatic and any(clean[key] for key in ("randomized", "independent_units", "allocation_valid")):
                    _learning_error()
                winner = assessment.get("winner")
                if winner not in (None, "control", "treatment"):
                    _learning_error()
                qualified = (complete and mature and clean["randomized"] and clean["one_variable"]
                    and clean["allocation_valid"] and clean["independent_units"] and clean["status"] == "completed" and clean["preregistered"])
                if winner is not None and (outcome != "winner" or not qualified):
                    _learning_error()
                if assessment.get("causal_claim") is True and (winner is None or not qualified):
                    _learning_error()
                if type(assessment.get("causal_claim")) is not bool:
                    _learning_error()
                case["assessment"].update(winner=winner, causal_claim=assessment["causal_claim"])
                interval = assessment.get("confidence_interval")
                if interval is not None:
                    if not isinstance(interval, dict) or set(interval) != {"low", "high", "confidence"} or interval["confidence"] != 0.95:
                        _learning_error()
                    low, high = (_learning_number(interval[key], signed=True) for key in ("low", "high"))
                    if low is None or high is None or not -1 <= low <= high <= 1:
                        _learning_error()
                    case["assessment"]["confidence_interval"] = {"low": low, "high": high, "confidence": 0.95}
                if winner is not None:
                    denominator = "impressions" if clean["goal"] == "ctr" else "clicks" if clean["goal"] == "cvr" else None
                    required = assessment.get("required_sample_per_arm")
                    numerator = "clicks" if clean["goal"] == "ctr" else "conversions"
                    if (denominator is None or type(required) is not int or required > clean["min_sample_per_arm"]
                            or any(clean[arm][denominator] is None or clean[arm][denominator] < clean["min_sample_per_arm"] for arm in ("control", "treatment"))
                            or any(type(clean[arm][numerator]) is not int or type(clean[arm][denominator]) is not int or
                                not 0 <= clean[arm][numerator] <= clean[arm][denominator] for arm in ("control", "treatment"))
                            or interval is None or (winner == "treatment" and interval["low"] <= 0)
                            or (winner == "control" and interval["high"] >= 0)):
                        _learning_error()
        else:
            if assessment.get("causal_claim") is not False or outcome != "observation":
                _learning_error()
            changed = evidence.get("changed_variable")
            if not isinstance(changed, str) or not re.fullmatch(r"[a-z_]{1,64}", changed):
                _learning_error()
            allowed_settings = {"goal", "target_value", "daily_spend_cap", "absolute_bid_cap", "experiment_days", "loss_cap", "bid", "daily_budget", "enabled"}
            allowed_execution = LA._EXECUTION_STATES if automatic else {"planned", "observed", "applied"}
            if changed not in allowed_settings | {"multiple"} or evidence.get("execution") not in allowed_execution:
                _learning_error()
            clean = {"changed_variable": changed, "execution": evidence["execution"]}
            for side in ("before", "after"):
                settings = evidence.get(side)
                if automatic and side == "after" and settings is None:
                    clean[side] = None
                    continue
                if not isinstance(settings, dict) or not set(settings) <= allowed_settings:
                    _learning_error()
                clean[side] = {}
                for key, setting in settings.items():
                    if key == "goal":
                        if setting is not None and setting not in LEARNING_METADATA["goal"]:
                            _learning_error()
                        clean[side][key] = setting
                    else:
                        clean[side][key] = _learning_bool(setting) if key == "enabled" and setting is not None else _learning_number(setting)
            if automatic:
                status = case["source_summary"]["status"]
                expected = {"confirmed": "applied", "accepted": "dispatched", "approved": "planned", "queued": "planned"}.get(status, status)
                if clean["execution"] != expected or (status == "confirmed") != (clean["after"] is not None):
                    _learning_error()
        if automatic:
            clean["source_facts"] = _learning_auto_facts(evidence.get("source_facts"), item["kind"])
            if clean["source_facts"].get("method") == "randomized_paired_ctr_constant_shift_v1":
                facts = clean["source_facts"]
                if (clean["goal"] != "ctr" or clean["conversion_definition"] != "unknown" or any(
                        clean[key] is not None for key in ("min_sample_per_arm", "baseline_rate", "mde_percent", "control_share"))
                        or any(evidence[arm][key] is not None for arm in ("control", "treatment") for key in ("conversions", "conversion_value"))
                        or clean["days"] != 2*facts["randomized_result"]["pair_count"]
                        or facts["randomized_result"]["decision"] != "hold" and (not complete or not mature
                            or not clean["preregistered"] or clean["status"] != "completed" or summary["status"] != "ok")):
                    _learning_error()
            if item["kind"] == "setting_change" and clean["after"] is None and clean["source_facts"]["followup"] is not None:
                _learning_error()
        case["evidence"] = clean
        cases.append(case)
        references.append({"asset_id": item["asset_id"], "version": item["version"]})
    return {"version": 1, "cases": cases}, references


def _plan_context(value):
    fields = {"goal", "target_value", "daily_spend_cap", "absolute_bid_cap", "experiment_days", "loss_cap"}
    if (not isinstance(value, dict) or set(value) != {"version", "state", "document"}
            or type(value["version"]) is not int or not 0 <= value["version"] <= 2**53-1
            or value["state"] not in {"empty", "draft", "approved"}
            or not isinstance(value["document"], dict)):
        raise StrategyRefused("PLAN_CONTEXT_INVALID")
    plan = value["document"]
    extra = {}
    if set(plan) != fields:
        from . import operating_criteria as OC
        if set(plan) != OC.V2_FIELDS - {"notes"}:
            raise StrategyRefused("PLAN_CONTEXT_INVALID")
        try:
            extra = OC.normalize_extra(plan, approve=value["state"] == "approved")
        except OC.CriteriaInvalid:
            raise StrategyRefused("PLAN_CONTEXT_INVALID") from None
    if plan["goal"] is not None and plan["goal"] not in {"impressions", "clicks", "cpa", "roas"}:
        raise StrategyRefused("PLAN_CONTEXT_INVALID")
    clean = {"state": value["state"], "goal": plan["goal"]}
    for key in fields - {"goal"}:
        try:
            clean[key] = _number(plan[key])
        except StrategyRefused:
            raise StrategyRefused("PLAN_CONTEXT_INVALID") from None
        if clean[key] is not None and not 0 < clean[key] <= 10**12:
            raise StrategyRefused("PLAN_CONTEXT_INVALID")
    days = clean["experiment_days"]
    if days is not None and (type(days) is not int or not 2 <= days <= 30):
        raise StrategyRefused("PLAN_CONTEXT_INVALID")
    if value["state"] == "approved" and (value["version"] < 1 or any(clean[key] is None for key in fields)
            or clean["loss_cap"] > clean["daily_spend_cap"] * days):
        raise StrategyRefused("PLAN_CONTEXT_INVALID")
    if (value["state"] == "empty" and (value["version"] != 0 or any(clean[key] is not None for key in fields))
            or value["state"] != "empty" and value["version"] < 1):
        raise StrategyRefused("PLAN_CONTEXT_INVALID")
    clean.update(extra)
    return clean, {"version": value["version"], "state": value["state"]}


class StrategyRefused(ValueError):
    """외부 응답·키·계정 정보 대신 고정 분류만 반환한다."""
    def __init__(self, code, *, rule=None, field=None):
        self.code = code
        self.rule, self.field = rule, field
        super().__init__(code)


def _number(value, *, signed=False):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not (-E.MAX_NUMBER if signed else 0) <= value <= E.MAX_NUMBER:
        raise StrategyRefused("CONTEXT_INVALID")
    return value


def build_context(payload, *, learning_context=None, plan_context=None, product_context=None, market_context=None,
                  funnel_context=None, setup_context=None):
    """수치판을 순수 재계산한 뒤 allowlist만 복사한다. 권한·판 확인은 호출자가 한다."""
    try:
        saved = payload["period"]
        if saved["kind"] not in ("weekly", "monthly") or type(saved["days"]) is not int or not 1 <= saved["days"] <= 31:
            raise StrategyRefused("CONTEXT_INVALID")
        enriched = E.enrich(payload)
        metrics = []
        for item in enriched["metrics"]:
            if item["key"] not in _LABELS or item["status"] not in _STATUS or item["value_status"] not in _VALUE_STATUS:
                raise StrategyRefused("CONTEXT_INVALID")
            scope = item["scope"]
            metrics.append({"key": item["key"], "label": _LABELS[item["key"]][0], "unit": _LABELS[item["key"]][1],
                **{field: _number(item[field], signed=field in ("absolute", "percent")) for field in METRIC_FIELDS},
                "status": item["status"], "value_status": item["value_status"],
                "percentage_points": item["percentage_points"] is True,
                "scope": {"account_days": _number(scope["account_days"]),
                          "expected_account_days": _number(scope["expected_account_days"]),
                          "complete": scope["complete"] is True}})
        quality = enriched["quality"]
        public_quality = {key: _number(quality[key]) for key in ("expected_account_days", "missing_account_days", "missing_count")}
        for family in ("basic", "conversion", "paired"):
            public_quality[family] = {"complete": quality[family]["complete"] is True,
                "count": _number(quality[family]["count"]), "percent": _number(quality[family]["percent"])}
        comparison = payload.get("details", {}).get("comparison") or {}
        prior_days = comparison.get("period", {}).get("days")
        if prior_days is not None and (type(prior_days) is not int or not 1 <= prior_days <= 31):
            raise StrategyRefused("CONTEXT_INVALID")
        feedback = enriched["feedback"]
        result = {"version": 1, "period": {"kind": saved["kind"], "days": saved["days"], "previous_days": prior_days},
            "metrics": metrics, "quality": public_quality,
            "feedback": {kind: [{"metric_keys": [key for key in row["metric_keys"] if key in _LABELS]}
                                    for row in feedback[kind]] for kind in ("facts", "hypotheses", "actions")},
            "connected": {"product": False, "market": False, "purchase_definition": False, "experiment": False}}
        if learning_context is not None:
            result["learning"], _ = _learning_context(learning_context)
        if plan_context is not None:
            result["operating_plan"], _ = _plan_context(plan_context)
            if result["operating_plan"].get("schema_version") == 2:
                from . import operating_criteria as OC
                result["operating_assessment"] = OC.assessment_from_report(
                    {"version": plan_context["version"], "state": plan_context["state"],
                     "plan": plan_context["document"]}, payload)
        if product_context is not None:
            from . import product_evidence as PE
            result["product"] = PE.normalize_context(product_context)
            result["connected"]["product"] = result["product"]["state"] == "stored_observations"
        if market_context is not None:
            from . import market_evidence as ME
            result["market"] = ME.normalize_context(market_context)
            result["connected"]["market"] = result["market"]["state"] == "stored_search_sample"
        if funnel_context is not None:
            from . import funnel_evidence as FE
            result["funnel"] = FE.normalize_context(funnel_context)
            if result["funnel"]["coverage"]["expected_account_days"] != public_quality["expected_account_days"]:
                raise StrategyRefused("CONTEXT_INVALID")
        if setup_context is not None:
            try:
                result["setup"] = SE.normalize_context(setup_context)
            except SE.EvidenceInvalid:
                raise StrategyRefused("SETUP_CONTEXT_INVALID") from None
        return result
    except StrategyRefused:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise StrategyRefused("CONTEXT_INVALID") from None


def _display(context, key, field):
    item = next((row for row in context["metrics"] if row["key"] == key), None)
    if (item is None or field not in METRIC_FIELDS or item[field] is None or
            (field != "current" and item["status"] != "ready")):
        raise StrategyRefused("REFERENCE_UNAVAILABLE")
    value = item[field]
    text = format(value, ",.2f").rstrip("0").rstrip(".") if type(value) is float else format(value, ",")
    unit = "%" if field == "percent" else "%p" if field == "absolute" and item["percentage_points"] else (
        "%" if item["unit"] == "percent" else "원" if item["unit"] == "money" else "")
    label = {"current": "현재", "previous": "직전", "absolute": "차이", "percent": "상대 증감률"}[field]
    partial = " · 일부 완결 자료 기준" if field == "current" and item["value_status"] == "partial" else ""
    return f"{item['label']} {label} {text}{unit}{partial}"


def _display_case(context, index, field):
    cases = context.get("learning", {}).get("cases", [])
    if not 1 <= index <= len(cases):
        raise StrategyRefused("REFERENCE_UNAVAILABLE")
    case = cases[index-1]
    if field == "outcome":
        return f"검수된 과거 사례 {index}: " + _OUTCOME_LABELS[case["assessment"]["outcome"]]
    if field == "reason":
        return "과거 사례의 측정·표본·실험 조건을 현재 계정에 적용하기 전에 다시 확인합니다"
    if field == "source_status":
        summary = case.get("source_summary")
        if summary is None:
            raise StrategyRefused("REFERENCE_UNAVAILABLE")
        labels = {"ok": "관측 숫자 응답", "partial": "부분 관측", "pending": "관측 대기", "failed": "관측 실패",
            "stale": "오래된 관측", "unavailable": "원천 미확인", "superseded": "원천 판 교체",
            "planned": "계획", "approved": "계획 승인", "queued": "실행 대기", "dispatched": "송신 기록·반영 미확인",
            "accepted": "송신 응답 수락·반영 미확인", "unknown": "실행 결과 미확인", "rejected": "실행 거절",
            "cancelled": "실행 취소", "stopped": "운영 중단", "confirmed": "정확한 재조회로 세팅 반영 확인·성과 효과 미확인"}
        return f"검수된 과거 사례 {index}의 원천 상태: " + labels[summary["status"]]
    path = field.split(".")
    evidence = case["evidence"]
    source_facts = evidence.get("source_facts", {})
    if len(path) == 2 and path[0] == "diagnostic":
        diagnostic = source_facts.get("exploratory_diagnostic")
        if not isinstance(diagnostic, dict):
            raise StrategyRefused("REFERENCE_UNAVAILABLE")
        prefix = f"검수된 과거 사례 {index}의 탐색적·비교정 관측 "
        if path[1] == "status":
            labels = {"hold": "판단 보류", "inconclusive": "방향 불명확",
                "conditional_preference": "조건부 관측 추천·정식 승자 아님",
                "within_material_margin": "사전 관측 기준 안의 차이·동등성 입증 아님"}
            return prefix + labels[diagnostic["decision"]]
        values = {"effect_percent": diagnostic["effect_percent"], "margin_percent": diagnostic["margin_percent"],
            "paired_days": diagnostic["paired_days"],
            "lower_percent": (diagnostic["band"] or {}).get("lower_percent"),
            "upper_percent": (diagnostic["band"] or {}).get("upper_percent")}
        labels = {"effect_percent": "목표 기준 상대 차이", "margin_percent": "사전 상대 차이 기준",
            "paired_days": "양군 일별 관측 기간", "lower_percent": "진단 밴드 하한·신뢰구간 아님",
            "upper_percent": "진단 밴드 상한·신뢰구간 아님"}
        value = values.get(path[1])
        if type(value) not in (int, float):
            raise StrategyRefused("REFERENCE_UNAVAILABLE")
        number = format(value, ",.2f").rstrip("0").rstrip(".") if type(value) is float else format(value, ",")
        return prefix + labels[path[1]] + " " + number + ("일" if path[1] == "paired_days" else "%")
    if len(path) == 2 and path[0] == "randomized":
        result = source_facts.get("randomized_result")
        if not isinstance(result, dict):
            raise StrategyRefused("REFERENCE_UNAVAILABLE")
        prefix = f"검수된 과거 사례 {index}의 시간 블록 CTR·상수 가산효과 모형조건부 결과·가정 미검증: "
        if path[1] == "status":
            labels = {"hold": "판단 보류", "inconclusive": "승자·등가 판단 불충분",
                "winner": ("실험군" if result["winner"] == "treatment" else "대조군") + " 모형조건부 우세",
                "equivalent": "사전 퍼센트포인트 범위의 모형조건부 등가·단순 비유의 아님"}
            return prefix + labels[result["decision"]]
        if path[1] == "scope":
            return prefix + "상수 가산효과·간섭과 이월효과 없음은 미검증 가정이며, 사용자·노출 무작위 배정이나 타겟·랜딩 전수 검증을 뜻하지 않습니다"
        fields = {"effect_pp": (result["effect_pp"], "실험군−대조군 동일 가중 일자 블록 CTR 차이", "%p"),
            "superiority_margin_pp": (result["superiority_margin_pp"], "사전 우세 기준", "%p"),
            "equivalence_margin_pp": (result["equivalence_margin_pp"], "사전 등가 범위", "%p"),
            "pair_count": (result["pair_count"], "대응 일자 블록 쌍", "쌍"),
            "minimum_impressions_per_block": (source_facts["minimum_impressions_per_block"], "사전 블록별 최소 노출", "회"),
            "washout_hours": (source_facts["washout_hours"], "각 블록 시작 후 사전 제외 시간", "시간"),
            "lower_ninety_five_pp": (result["interval95_pp"]["lower_pp"], "가정하 조건부 95% 구간 하한", "%p"),
            "upper_ninety_five_pp": (result["interval95_pp"]["upper_pp"], "가정하 조건부 95% 구간 상한", "%p"),
            "lower_ninety_pp": (result["interval90_pp"]["lower_pp"], "가정하 조건부 90% 구간 하한", "%p"),
            "upper_ninety_pp": (result["interval90_pp"]["upper_pp"], "가정하 조건부 90% 구간 상한", "%p")}
        value, label, unit = fields.get(path[1], (None, "", ""))
        if type(value) not in (int, float):
            raise StrategyRefused("REFERENCE_UNAVAILABLE")
        number = format(value, ",.2f").rstrip("0").rstrip(".") if type(value) is float else format(value, ",")
        return prefix + label + " " + number + unit
    source_numbers = {"declared_control_sample", "declared_treatment_sample", "measurement_lag_days",
        "experiment_spend_cap", "control_daily_cap", "treatment_daily_cap"}
    if len(path) == 1 and path[0] in _LEARNING_METRICS | {"days", "min_sample_per_arm", "mde_percent"}:
        value = evidence.get(path[0])
    elif len(path) == 1 and path[0] in source_numbers:
        value = source_facts.get(path[0])
    elif len(path) == 2 and path[0] in {"control", "treatment"} and path[1] in _LEARNING_METRICS:
        value = (evidence.get(path[0]) or {}).get(path[1])
    elif len(path) == 2 and path[0] in {"before", "after", "desired"} and path[1] in {
            "target_value", "daily_spend_cap", "absolute_bid_cap", "experiment_days", "loss_cap", "bid", "daily_budget"}:
        value = ((source_facts if path[0] == "desired" else evidence).get(path[0]) or {}).get(path[1])
    elif len(path) == 2 and path[0] in {"baseline", "followup"} and path[1] in _LEARNING_METRICS | {"days"}:
        value = (source_facts.get(path[0]) or {}).get(path[1])
    else:
        raise StrategyRefused("REFERENCE_UNAVAILABLE")
    if type(value) not in (int, float):
        raise StrategyRefused("REFERENCE_UNAVAILABLE")
    number = format(value, ",.2f").rstrip("0").rstrip(".") if type(value) is float else format(value, ",")
    unit = "원" if path[-1] in {"spend", "conversion_value", "daily_spend_cap", "absolute_bid_cap", "loss_cap", "bid", "daily_budget", "experiment_spend_cap", "control_daily_cap", "treatment_daily_cap"} else "%" if path[-1] == "mde_percent" else "일" if path[-1] in {"days", "experiment_days", "measurement_lag_days"} else ""
    label = {"impressions": "노출", "clicks": "클릭", "spend": "광고비", "conversions": "광고 전환",
        "conversion_value": "플랫폼 전환금액", "days": "관측 기간", "min_sample_per_arm": "군별 계획 표본",
        "mde_percent": "계획 최소 차이", "target_value": "목표값", "daily_spend_cap": "일 예산 한도",
        "absolute_bid_cap": "절대 입찰 한도", "experiment_days": "계획 기간", "loss_cap": "손실 한도",
        "bid": "입찰값", "daily_budget": "일 예산", "declared_control_sample": "대조군 사전 계획 표본",
        "declared_treatment_sample": "실험군 사전 계획 표본", "measurement_lag_days": "계획 측정 대기",
        "experiment_spend_cap": "실험 광고비 위험 한도", "control_daily_cap": "대조군 일 예산 한도", "treatment_daily_cap": "실험군 일 예산 한도"}[path[-1]]
    scope = {"control": "대조군 ", "treatment": "실험군 ", "before": "변경 전 ", "after": "재조회 확인 변경 후 " if "source_summary" in case else "변경 후 ",
        "desired": "의도한 변경 ", "baseline": "이전 관측 ", "followup": "이후 관측 "}.get(path[0], "")
    return f"검수된 과거 사례 {index}의 {scope}{label} {number}{unit}"


def plan_numeric_values(plan):
    """검증된 계획의 고정 수치 키만 펼친다. 임의 nested 경로·문자열·날짜는 참조하지 않는다."""
    if not isinstance(plan, dict):
        return {}
    values = {key: plan.get(key) for key in PLAN_NUMERIC_FIELDS if key not in _PLAN_LIMIT_FIELDS}
    limits = plan.get("change_limits")
    if isinstance(limits, dict):
        values.update({key: limits.get(key) for key in _PLAN_LIMIT_FIELDS})
    return values


def _display_plan(context, field):
    plan = context.get("operating_plan", {})
    value = plan_numeric_values(plan).get(field)
    if field not in PLAN_NUMERIC_FIELDS or type(value) not in (int, float) or not 0 <= value <= 10**12:
        raise StrategyRefused("REFERENCE_UNAVAILABLE")
    label = {"target_value": "목표값", "daily_spend_cap": "일 예산 한도", "absolute_bid_cap": "절대 입찰 한도",
        "experiment_days": "계획 기간", "loss_cap": "손실 한도", "monthly_spend_cap": "개별 계정 월 예산 상한",
        "measurement_lag_days": "전환 측정 대기 기간", "minimum_clicks": "최소 클릭 표본", "minimum_conversions": "최소 전환 표본",
        "single_increase_percent": "단일 인상 한도", "single_decrease_percent": "단일 인하 한도",
        "rolling_day_increase_percent": "누적 일간 인상 한도", "rolling_day_decrease_percent": "누적 일간 인하 한도",
        "weekly_increase_requires_approval_percent": "주간 인상 재승인 기준"}[field]
    if plan.get("schema_version") == 2 and field == "loss_cap":
        label = "실험 광고 지출 위험 상한"
    number = format(value, ",.2f").rstrip("0").rstrip(".") if type(value) is float else format(value, ",")
    unit = ("%" if field in _PLAN_LIMIT_FIELDS else "일" if field in ("experiment_days", "measurement_lag_days") else
        "회" if field == "minimum_clicks" else "건" if field == "minimum_conversions" else
        "%" if field == "target_value" and plan.get("goal") == "roas" else
        "원" if field != "target_value" or plan.get("goal") == "cpa" else
        "회" if plan.get("schema_version") == 2 and plan.get("goal") in ("impressions", "clicks") else "")
    return ("승인 계획의 " if plan.get("state") == "approved" else "미승인 초안의 ") + label + " " + number + unit


def _display_product(context, index, field):
    from . import product_evidence as PE
    try:
        return PE.display(context.get("product"), index, field)
    except PE.EvidenceInvalid:
        raise StrategyRefused("REFERENCE_UNAVAILABLE") from None


def _display_market(context, index, field):
    from . import market_evidence as ME
    try:
        return ME.display(context.get("market"), index, field)
    except ME.EvidenceInvalid:
        raise StrategyRefused("REFERENCE_UNAVAILABLE") from None


def _display_funnel(context, field):
    from . import funnel_evidence as FE
    try:
        return FE.display(context.get("funnel"), field)
    except FE.EvidenceInvalid:
        raise StrategyRefused("REFERENCE_UNAVAILABLE") from None


def _display_setup(context, index, field):
    try:
        return SE.display(context["setup"], index, field, context.get("_setup_labels"))
    except (KeyError, SE.EvidenceInvalid, SE.EvidenceUnavailable):
        raise StrategyRefused("REFERENCE_UNAVAILABLE") from None


def _setup_render_context(context, labels):
    if labels is None:
        return context
    try:
        return {**context, "_setup_labels": SE.normalize_labels(labels, context["setup"])}
    except (KeyError, SE.EvidenceInvalid):
        raise StrategyRefused("SETUP_CONTEXT_INVALID") from None


def _with_learning_provenance(result, context, learning_context, plan_context, product_context=None, market_context=None,
                              funnel_context=None, setup_context=None):
    if (learning_context is None and plan_context is None and product_context is None and market_context is None
            and funnel_context is None and setup_context is None):
        return result
    references = _learning_context(learning_context)[1] if learning_context is not None else []
    plan_ref = _plan_context(plan_context)[1] if plan_context is not None else None
    canonical = json.dumps({"context": context, "learning_refs": references, "plan_ref": plan_ref},
        sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    result.update(prompt_version=FUNNEL_PROMPT_VERSION if funnel_context is not None else MARKET_PROMPT_VERSION if market_context is not None else
        PRODUCT_PROMPT_VERSION if product_context is not None else LEARNING_PROMPT_VERSION,
        learning_refs=references,
        context_fingerprint=hashlib.sha256(canonical).hexdigest())
    if plan_ref is not None:
        result["plan_ref"] = plan_ref
    if learning_context is not None or plan_context is not None:
        result["caveats"].append("학습 사례는 검수한 과거 기록입니다. 유사 조건의 재검증 없이 현재 성과·매출·인과 효과를 보장하지 않습니다.")
    if product_context is not None:
        result["caveats"].append(PRODUCT_CAVEAT if context["connected"]["product"] else
            "상품 자료가 가용하지 않아 구체 소구점 생성을 보류합니다. 현재 상품 상태나 고객의 구매 동기를 추정하지 않습니다.")
    if market_context is not None:
        result["caveats"].append(MARKET_CAVEAT if context["connected"]["market"] else MARKET_UNAVAILABLE_COMMENT)
    if funnel_context is not None:
        result["caveats"].append(FUNNEL_CAVEAT)
    if setup_context is not None:
        result["setup_context_fingerprint"] = hashlib.sha256(SE.canonical(context["setup"]).encode()).hexdigest()
        result["caveats"].append(SE.source_boundary(context["setup"]))
    return result


def _product_appeals(context):
    """저장 사실을 근거로 담당자가 비교할 행동 가설만 선택한다."""
    if not context["connected"]["product"]:
        return []
    # 원문 상품명을 제안에 복사하거나 저장된 안내의 존재를 현재 혜택으로 바꾸지 않는다.
    options = (("price", "가격 정보 제시", "가격 정보의 제시 위치를 바꾼 소재와 랜딩의 반응"),
        ("review_count", "리뷰 정보 설명", "리뷰 정보의 설명 방식을 바꾼 소재와 랜딩의 반응"),
        ("rating", "리뷰 정보 설명", "저장 평점 자료의 범위를 명확하게 설명하는 방식의 반응"),
        ("review_section", "리뷰 정보 설명", "리뷰 안내의 위치를 바꾼 랜딩의 반응"),
        ("delivery_info", "배송 안내 이해", "배송 안내를 랜딩 상단에서 설명하는 방식의 반응"),
        ("return_info", "반품 안내 이해", "반품 안내를 이해하기 쉽게 배치하는 방식의 반응"),
        ("gift_info", "선물 안내 이해", "선물 안내의 설명 방식을 바꾼 소재의 반응"),
        ("certification", "인증 정보 확인", "인증 관련 안내의 확인 위치를 명확히 설명하는 방식의 반응"),
        ("spec_table", "상품 정보 구성", "상품 정보의 순서와 설명 구성을 바꾼 랜딩의 반응"),
        ("category", "상품 정보 구성", "상품 분류와 사용 상황을 설명하는 소재의 반응"),
        ("name", "상품 정보 구성", "상품 정보를 간결하게 설명하는 소재의 반응"))
    appeals = []
    for product in context["product"]["products"]:
        index = product["index"]
        for field, title, hypothesis in options:
            try:
                _display_product(context, index, field)
            except StrategyRefused:
                continue
            appeals.append({"title": title, "message": "검증 가설: "+hypothesis+" 효과를 비교 검증합니다.",
                "basis": "{{product:"+str(index)+"."+field+"}} · {{product:"+str(index)+".source_status}}"})
            break
    return appeals


def competitive_comment(context=None):
    """상품 관측과 시장·경쟁 근거의 연결 상태를 서로 바꾸지 않는다."""
    if context is not None and "market" in context:
        return MARKET_UNAVAILABLE_COMMENT
    return (PRODUCT_COMPETITIVE_COMMENT if context is not None and
        context.get("connected", {}).get("product") is True else COMPETITIVE_COMMENT)


def _market_competition(context):
    if not context.get("connected", {}).get("market"):
        return competitive_comment(context)
    fields = ["keyword", "source_status", "sample_count", "price_count"]
    prices = context["market"]["cohorts"][0]["price_count"] > 0
    if prices:
        fields.append("price_median")
    hypothesis = ("표본의 가격대와 상품 구성·규격·배송 조건을 따로 대조한 뒤 설명 방식을 바꾼 랜딩의 반응" if prices else
        "상품 구성·규격·배송 조건을 추가 확인한 뒤 선택에 필요한 안내를 정리한 랜딩의 반응")
    return {"hypothesis": "검증 가설: "+hypothesis+" 효과를 비교 검증합니다.",
        "basis": " · ".join("{{market:1."+field+"}}" for field in fields)}


def _funnel_diagnosis(context):
    """저장판 수치·완결 상태만 해석한다. 임계값·원인·고객별 단계를 추정하지 않는다."""
    metrics = {row["key"]: row for row in context["metrics"]}
    if not context["quality"]["basic"]["complete"]:
        diagnosis = "기본 지표가 미완결이므로 전체 유입 평가와 기간 비교를 보류합니다."
    elif metrics["impressions"]["current"] == 0:
        diagnosis = "기본 원천의 노출 응답값이 0이므로 송출 조건과 수집 범위를 먼저 대조합니다."
    elif metrics["clicks"]["current"] == 0:
        diagnosis = "노출은 기록됐지만 클릭 응답값이 0이므로 검색 의도와 소재 안내를 점검할 대상으로 봅니다."
    elif not context["quality"]["paired"]["complete"]:
        diagnosis = "클릭 자료는 집계됐지만 일반 전환 공동 근거가 미완결이므로 전환 평가를 보류합니다."
    elif metrics["conversions"]["current"] == 0:
        diagnosis = "클릭과 일반 광고 전환의 공동 완결 범위에서 전환 응답값이 0이며, 측정 정상이나 구매 부재를 뜻하지 않습니다."
    else:
        changes = [("클릭률", metrics["ctr"]), ("일반 전환율", metrics["cvr"])]
        descriptions = [label+("이 상승" if row["absolute"] > 0 else "이 하락") for label,row in changes
            if row["status"] == "ready" and row["absolute"] not in (None, 0)]
        diagnosis = ("같은 계정 범위의 직전 기간 대비 "+" · ".join(descriptions)+"했지만 원인과 구매 효과는 확정하지 않습니다."
            if descriptions else "노출·클릭·일반 광고 전환은 같은 저장판의 관측이며 구매 여정이나 소재 효과의 증거와 구분합니다.")
    source = context["funnel"]
    if source["metric_status"]["purchase_count"] == "unavailable":
        diagnosis += " 별도 구매 전환수 원천이 미확인입니다."
    elif source["metric_status"]["purchase_count"] == "partial":
        diagnosis += " 별도 구매 전환수는 일부 확인 범위이며 전체 구매 성과로 확대하지 않습니다."
    elif source["metrics"]["purchase_count"] == 0:
        diagnosis += " 별도 구매 전환수의 응답값 0도 태그 정상이나 실제 주문 부재를 보증하지 않습니다."
    else:
        diagnosis += " 플랫폼 구매 이벤트가 집계돼도 실제 결제 주문·이익은 미연결입니다."
    return diagnosis


def funnel_comment(context=None):
    if context is None or "funnel" not in context:
        return FUNNEL_COMMENT
    fields = ["source_status", "coverage"]
    for field in ("purchase_count", "purchase_value", "purchase_cvr", "purchase_cpa", "purchase_roas"):
        try:
            _display_funnel(context, field)
            fields.append(field)
        except StrategyRefused:
            pass
    refs = ["{{funnel:"+field+"}}" for field in fields]
    metrics = {row["key"]: row for row in context["metrics"]}
    for key in ("impressions", "clicks", "conversions"):
        if metrics[key]["current"] is not None:
            refs.append("{{metric:"+key+".current}}")
    for key in ("ctr", "cvr"):
        if metrics[key]["status"] == "ready" and metrics[key]["absolute"] not in (None, 0):
            refs.append("{{metric:"+key+".absolute}}")
    if not context["quality"]["basic"]["complete"]:
        hypothesis = "같은 기간의 원천과 보고서 범위를 대조한 뒤 상품 설명을 정리한 소재의 반응"
    elif metrics["clicks"]["current"] == 0:
        hypothesis = "검색 의도와 상품 설명을 맞춘 소재 표현을 검토하는 반응"
    elif (not context["quality"]["paired"]["complete"] or
            context["funnel"]["metric_status"]["purchase_count"] == "unavailable"):
        hypothesis = "전환 정의와 추적 기록을 대조한 뒤 랜딩 안내의 설명 방식을 바꾸는 반응"
    elif (metrics["ctr"]["status"] == metrics["cvr"]["status"] == "ready" and
            metrics["ctr"]["absolute"] > 0 and metrics["cvr"]["absolute"] < 0):
        hypothesis = "소재에서 약속한 정보와 랜딩 상단의 상품 구성·배송 안내를 일치시키는 반응"
    else:
        hypothesis = "상품 구성·규격·배송 안내의 제시 순서를 바꾼 소재와 랜딩의 반응"
    return {"hypothesis": "검증 가설: "+hypothesis+" 효과를 비교 검증합니다.", "basis": " · ".join(refs)}


def _baseline(context):
    usable = [row["key"] for row in context["metrics"] if row["key"] in ("spend", "clicks", "conversions") and row["current"] is not None]
    observation = " · ".join("{{metric:"+key+".current}}" for key in usable) or "확인 가능한 성과 수치가 없습니다"
    incomplete = not all(context["quality"][family]["complete"] for family in ("basic", "conversion", "paired"))
    diagnosis = observation+". "+("자료가 미완결이므로 전체 성과 평가와 기간 비교를 보류합니다." if incomplete else
        "확인한 계정×일 범위의 관측값이며 원인이나 구매 효율 개선의 증거와는 구분합니다.")
    statuses = {row["status"] for row in context["metrics"]}
    if "scope_changed" in statuses:
        diagnosis += " 포함 계정 범위가 바뀌어 직전 기간 증감을 보류합니다."
    elif statuses == {"no_previous"}:
        diagnosis += " 직전 기간 저장판이 없어 증감을 판정하지 않습니다."
    else:
        changes = [row["key"] for row in context["metrics"] if row["key"] in ("clicks", "conversions", "cvr", "cpa")
                   and row["status"] == "ready" and row["absolute"] != 0]
        if changes:
            diagnosis += " 직전 기간 차이: "+" · ".join("{{metric:"+key+".absolute}}" for key in changes)+"."
    if context["period"]["previous_days"] not in (None, context["period"]["days"]):
        diagnosis += " 기간 길이가 달라 합계와 완결 자료의 일평균을 함께 확인합니다."
    direction = "전환 정의와 합의한 목표를 먼저 확인하고 유입·소재·랜딩 근거를 연결합니다. 상품 사실이 연결되기 전에는 구체 소구나 예산 확대를 확정하지 않습니다."
    if context.get("learning", {}).get("cases"):
        direction += " 검수된 과거 사례는 적용 조건을 재확인할 계획 근거로 사용하며, 과거 실험 결과를 현재 계정의 성과로 확정하지 않습니다."
    if context.get("operating_plan", {}).get("daily_spend_cap") is not None:
        direction += " {{plan:daily_spend_cap}}를 확인하고 적용 조건과 검수할 목표를 구체화합니다."
    if context.get("operating_plan", {}).get("schema_version") == 2:
        plan = context["operating_plan"]
        caps = [field for field in ("monthly_spend_cap", "loss_cap") if plan.get(field) is not None]
        if caps:
            direction += " "+" · ".join("{{plan:"+field+"}}" for field in caps)+"의 범위에서 검토합니다."
        assessment = context.get("operating_assessment")
        direction += " 목표 대조는 저장 보고서 작성 시점에 한정하며 현재 운영 상태와 구분합니다."
        if not assessment or assessment.get("state") != "reviewable":
            direction += " 기준이나 성과 근거가 충족되지 않아 목표 달성 판단을 보류합니다."
        else:
            direction += " 저장 시점의 목표 대조 결과를 다음 계획의 검토 자료로 사용하며 실행이나 실험 승자를 확정하지 않습니다."
    weekly = [
        {"action": "전환 정의와 자료 완결 상태 확인", "reason": "일반 광고 전환과 구매 완료를 구분하고 미확인 자료를 점검합니다.", "criterion": "같은 계정·기간의 기본·전환 공동 완결과 목표 근거 확인"},
        {"action": "상품·검색 의도·소재·랜딩 자료 연결", "reason": "계정 합산 성과만으로 소구 효과나 특정 소재의 원인을 판단할 수 없습니다.", "criterion": "상품 사실·출처·조회 시각과 동일 기간의 세부 성과 확인"},
        {"action": "비교할 가설과 실험 계획 검토", "reason": "관찰 비교와 통제된 실험을 분리합니다.", "criterion": "주지표·실험 단위·배분·표본·전환 지연·최대 기간·중단 조건을 계획에 기록"}]
    monthly = [
        {"action": "기간별 성과와 운영 이력 대조", "reason": "기간 길이·계정 범위·외부 변경의 영향을 확인합니다.", "criterion": "동일 범위의 완결 자료와 합계·일평균을 함께 비교"},
        {"action": "소구·경쟁 대응 계획 검토", "reason": "상품과 공개 경쟁 자료가 연결된 뒤 선택 이유를 검증합니다.", "criterion": "비교 가능한 상품 조건·출처와 승인할 구체안 확보"},
        {"action": "결과에 따라 유지·보완·다음 실험 구분", "reason": "표본이 부족하거나 비교 조건이 다르면 승자를 선정하지 않습니다.", "criterion": "성숙한 전환·주지표·악화 방지 기준 충족 여부를 검수하고 별도 운영 승인"}]
    appeals = _product_appeals(context)
    if appeals:
        direction += " 저장 상품 관측을 바탕으로 소재·랜딩 제안을 검증 가설로 검토하며 현재 상품 상태와 효과를 확정하지 않습니다."
    return {"diagnosis": diagnosis, "direction": direction, "appeal_points": appeals,
        "competitive_response": _market_competition(context), "weekly_plan": weekly, "monthly_plan": monthly,
        "funnel_comment": funnel_comment(context), "ab_comment": AB_COMMENT,
        "shared_comment": diagnosis+" "+direction+" 상품·시장 근거 연결과 계획 검토 후 다음 방향을 정하겠습니다."}


def _render(value, context, references):
    if isinstance(value, str):
        def replace(match):
            key, field = match.groups()
            text = _display(context, key, field)
            reference = {"metric_key": key, "field": field}
            if reference not in references:
                references.append(reference)
            return text
        def replace_case(match):
            index, field = match.groups()
            text = _display_case(context, int(index), field)
            reference = {"case_index": int(index), "field": field}
            if reference not in references:
                references.append(reference)
            return text
        def replace_plan(match):
            field = match[1]
            reference = {"plan_field": field}
            if reference not in references:
                references.append(reference)
            return _display_plan(context, field)
        def replace_product(match):
            index, field = int(match[1]), match[2]
            text = _display_product(context, index, field)
            reference = {"product_index": index, "field": field}
            if reference not in references:
                references.append(reference)
            return text
        def replace_market(match):
            index, field = int(match[1]), match[2]
            text = _display_market(context, index, field)
            reference = {"market_index": index, "field": field}
            if reference not in references:
                references.append(reference)
            return text
        def replace_funnel(match):
            field = match[1]
            text = _display_funnel(context, field)
            reference = {"funnel_field": field}
            if reference not in references:
                references.append(reference)
            return text
        def replace_setup(match):
            index, field = int(match[1]), match[2]
            text = _display_setup(context, index, field)
            reference = {"setup_index": index, "field": field}
            if reference not in references:
                references.append(reference)
            return text
        return _SETUP_REF.sub(replace_setup, _FUNNEL_REF.sub(replace_funnel, _MARKET_REF.sub(replace_market, _PRODUCT_REF.sub(replace_product,
            _PLAN_REF.sub(replace_plan, _CASE_REF.sub(replace_case, _REF.sub(replace, value)))))))
    if isinstance(value, list):
        return [_render(item, context, references) for item in value]
    if set(value) == {"hypothesis", "basis"}:
        return _render(value["basis"], context, references)+"\n"+_render(value["hypothesis"], context, references)
    return {key: (_funnel_diagnosis(context)+"\n"+_render(item, context, references) if key == "funnel_comment"
        and isinstance(item, dict) and "funnel" in context else _render(item, context, references)) for key, item in value.items()}


def rule_based(payload, *, learning_context=None, plan_context=None, product_context=None, market_context=None,
               funnel_context=None, setup_context=None, setup_labels=None):
    """AI가 아닌 결정적 기본 초안. 데이터 조회·저장·외부 호출은 없다."""
    context = build_context(payload, learning_context=learning_context, plan_context=plan_context,
        product_context=product_context, market_context=market_context, funnel_context=funnel_context, setup_context=setup_context)
    render_context = _setup_render_context(context, setup_labels)
    references = []
    result = {"source": "rule_based", "model": None, "prompt_version": PROMPT_VERSION,
        "document": _normalize_generated(_render(_baseline(context), render_context, references), context),
        "references": references, "caveats": ["규칙 기반 초안이며 AI 생성 결과가 아닙니다.",
        "광고 전환가치는 플랫폼 전환금액이며 실제 주문·결제 매출과 별도입니다.",
        "문안 승인은 광고 변경 승인이 아닙니다. 실행은 별도 승인·한도·권한 검증이 필요합니다."]}
    return _with_learning_provenance(result, context, learning_context, plan_context, product_context, market_context, funnel_context, setup_context)


def document_template(*, context=None):
    """제공자에게 주는 닫힌 문서 예시. 미연결 항목의 경계 문구는 고정한다."""
    plan = [{"action": "자료와 계획 검토", "reason": "검증된 근거를 먼저 연결합니다.",
             "criterion": "목표·자료 완결·비교 조건을 확인한 뒤 별도 운영 승인"}]
    return {"diagnosis": "저장판의 확인 자료와 완결 상태를 먼저 검토합니다.",
        "direction": "원인 가설을 검증할 근거와 목표를 연결한 뒤 다음 계획을 검토합니다.",
        "appeal_points": [], "competitive_response": _market_competition(context) if context is not None else COMPETITIVE_COMMENT,
        "weekly_plan": deepcopy(plan), "monthly_plan": deepcopy(plan),
        "funnel_comment": funnel_comment(context), "ab_comment": AB_COMMENT,
        "shared_comment": "확인 자료를 바탕으로 진단과 다음 계획을 검토하겠습니다."}


def _quantity_ending(tail):
    word_match = _QUANTITY_WORD.match(tail)
    if word_match is None:
        return True
    word = word_match[0]
    # '이내'는 '이'+'내'로도 분해된다. 겹치는 선택지의 반복 정규식은 실패 시
    # 지수적으로 되돌아가므로, 같은 도달 위치를 한 번만 처리하는 전진 검사로 보존한다.
    reachable = bytearray(len(word)+1)
    reachable[0] = 1
    for index, char in enumerate(word):
        if reachable[index]:
            for token in _QUANTITY_SUFFIX_BY_FIRST.get(char, ()):
                if word.startswith(token, index):
                    reachable[index+len(token)] = 1
    return bool(reachable[-1])


def _has_korean_quantity(prose):
    """닫힌 수량 문법만 검사한다. '이 회의' 같은 중의어는 정상 명사 요구를 우선한다."""
    noun_spans = {match.span("quantity") for pattern in _NOUN_QUANTITY_CONTEXTS for match in pattern.finditer(prose)}
    for match in _KOREAN_QUANTITY.finditer(prose):
        if match.span() in noun_spans:
            continue
        if match[0] in ("이번", "이달"):
            continue
        unit_word = prose[match.start("unit"):]
        if unit_word.startswith(_UNIT_NOUN_PREFIXES) or (
                match["number"] == "이" and unit_word.startswith("회의")):
            continue
        if _quantity_ending(prose[match.end():]):
            return True
    return any(_quantity_ending(prose[match.end():]) for match in _IDIOMATIC_PERIOD.finditer(prose))


def _has_reference_unit(value):
    """서버 참조는 이미 단위를 포함한다. 바로 앞뒤의 별도 수량 단위를 받지 않는다."""
    for pattern in (_REF, _CASE_REF, _PLAN_REF, _PRODUCT_REF, _MARKET_REF, _FUNNEL_REF, _SETUP_REF):
        for match in pattern.finditer(value):
            if _UNIT_BEFORE_REFERENCE.search(value[:match.start()]):
                return True
            following = value[match.end():].lstrip()
            if pattern is _MARKET_REF and following.startswith("점") and _quantity_ending(following[1:]):
                return True
            if following.startswith(_UNIT_NOUN_PREFIXES + ("회의",)):
                continue
            unit = _UNIT_AT_START.match(following)
            if unit and _quantity_ending(following[unit.end():]):
                return True
    return False


def _normalize_metric_prefixes(value):
    def replace(match):
        label = _LABELS.get(match["key"], (None, None))[0]
        if match["label"] != label or match["time"] not in (None, _METRIC_TIMES[match["field"]]):
            return match[0]
        return match["reference"]
    return _DUPLICATE_METRIC_PREFIX.sub(replace, value)


def _text(value, limit, context, *, require_refs=True, allow_market=False, allow_funnel=False):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit or any(
            (ord(char) < 32 and char != "\n") or 0x7f <= ord(char) <= 0x9f or 0xd800 <= ord(char) <= 0xdfff or
            char in "<>" or 0x202a <= ord(char) <= 0x202e or 0x2066 <= ord(char) <= 0x2069 for char in value)):
        raise StrategyRefused("DOCUMENT_INVALID", rule="text-shape")
    if require_refs:
        if _MARKET_REF.search(value) and not allow_market:
            raise StrategyRefused("UNCONNECTED_EVIDENCE", rule="market-reference-location")
        if _FUNNEL_REF.search(value) and not allow_funnel:
            raise StrategyRefused("UNCONNECTED_EVIDENCE", rule="funnel-reference-location")
        for match in _REF.finditer(value):
            _display(context, *match.groups())
        for match in _CASE_REF.finditer(value):
            _display_case(context, int(match[1]), match[2])
        for match in _PLAN_REF.finditer(value):
            _display_plan(context, match[1])
        for match in _PRODUCT_REF.finditer(value):
            _display_product(context, int(match[1]), match[2])
        for match in _MARKET_REF.finditer(value):
            _display_market(context, int(match[1]), match[2])
        for match in _FUNNEL_REF.finditer(value):
            _display_funnel(context, match[1])
        for match in _SETUP_REF.finditer(value):
            _display_setup(context, int(match[1]), match[2])
        prose = _SETUP_REF.sub("", _FUNNEL_REF.sub("", _MARKET_REF.sub("", _PRODUCT_REF.sub("", _PLAN_REF.sub("", _CASE_REF.sub("", _REF.sub("", value)))))))
        if _SETUP_REF.search(value) and _SETUP_PAST_CAUSE.search(prose):
            raise StrategyRefused("UNCONNECTED_EVIDENCE", rule="setup-historical-cause")
        exploratory = any(case.get("evidence", {}).get("source_facts", {}).get("exploratory_diagnostic") is not None
            for case in (context or {}).get("learning", {}).get("cases", []))
        if exploratory and _PROMOTED_EXPLORATORY.search(prose):
            raise StrategyRefused("UNCONNECTED_EVIDENCE", rule="exploratory-claim")
        randomized = any(case.get("evidence", {}).get("source_facts", {}).get("randomized_result") is not None
            for case in (context or {}).get("learning", {}).get("cases", []))
        if randomized and (_PROMOTED_EXPLORATORY.search(prose) or _PROMOTED_RANDOMIZED.search(prose)):
            raise StrategyRefused("UNCONNECTED_EVIDENCE", rule="randomized-claim")
        if ("{" in prose or "}" in prose or any(char.isnumeric() for char in prose) or
                any(char in prose for char in "%％₩") or _has_korean_quantity(prose) or _has_reference_unit(value)):
            error = StrategyRefused("NUMERIC_CITATION_REQUIRED", rule="numeric-reference-required")
            # Preserve the original OR and first-failure order; retain no text.
            error.validation_reason = ("BRACES" if "{" in prose or "}" in prose else
                "LITERAL_NUMERAL" if any(char.isnumeric() for char in prose) else
                "PERCENT_CURRENCY" if any(char in prose for char in "%％₩") else
                "KOREAN_QUANTITY" if _has_korean_quantity(prose) else "REFERENCE_UNIT")
            raise error
        value = _normalize_metric_prefixes(value)
    return value.strip()


def _field_text(value, limit, context, field, **kwargs):
    try:
        return _text(value, limit, context, **kwargs)
    except StrategyRefused as error:
        error.field = field
        raise


def normalize_document(document, *, competitive_limit=500, funnel_limit=600):
    """직원 편집용 형태·길이·일반 텍스트 검증. 숫자와 수동 근거 입력을 허용한다."""
    if not isinstance(document, dict) or set(document) != DOCUMENT_FIELDS:
        raise StrategyRefused("DOCUMENT_INVALID")
    if competitive_limit not in (500, 1000) or funnel_limit not in (600, 1000):
        raise StrategyRefused("DOCUMENT_INVALID")
    clean = {key: _field_text(document[key], competitive_limit if key == "competitive_response" else
        funnel_limit if key == "funnel_comment" else limit,
        None, key, require_refs=False) for key, limit in TEXT_LIMITS.items()}
    appeals = document["appeal_points"]
    if not isinstance(appeals, list) or len(appeals) > 3:
        raise StrategyRefused("DOCUMENT_INVALID")
    clean["appeal_points"] = []
    for row in appeals:
        limits = {"title": 100, "message": 300, "basis": 500}
        if not isinstance(row, dict) or set(row) != set(limits):
            raise StrategyRefused("DOCUMENT_INVALID")
        clean["appeal_points"].append({key: _field_text(row[key], limit, None, "appeal_points."+key, require_refs=False) for key, limit in limits.items()})
    for period in ("weekly_plan", "monthly_plan"):
        plans = document[period]
        if not isinstance(plans, list) or not 1 <= len(plans) <= 6:
            raise StrategyRefused("DOCUMENT_INVALID")
        clean[period] = []
        for row in plans:
            if not isinstance(row, dict) or set(row) != set(PLAN_LIMITS):
                raise StrategyRefused("DOCUMENT_INVALID")
            clean[period].append({key: _field_text(row[key], limit, None, period+"."+key, require_refs=False) for key, limit in PLAN_LIMITS.items()})
    return clean


def _normalize_generated(document, context):
    return normalize_document(document, competitive_limit=1000 if context.get("connected", {}).get("market") else 500,
        funnel_limit=1000 if "funnel" in context else 600)


def _validate_funnel(value, context):
    if not isinstance(value, dict) or set(value) != {"hypothesis", "basis"}:
        raise StrategyRefused("UNCONNECTED_EVIDENCE", field="funnel_comment", rule="funnel-shape")
    hypothesis = _field_text(value["hypothesis"], 300, context, "funnel_comment.hypothesis")
    basis = _field_text(value["basis"], 700, context, "funnel_comment.basis", allow_funnel=True)
    refs = sorted(list(_FUNNEL_REF.finditer(basis))+list(_REF.finditer(basis)), key=lambda ref:ref.start())
    fields = {ref[1] for ref in _FUNNEL_REF.finditer(basis)}
    required = {"source_status", "coverage"} | {field for field in ("purchase_count", "purchase_value")
        if context["funnel"]["metrics"][field] is not None}
    current = {row["key"] for row in context["metrics"] if row["key"] in ("impressions", "clicks", "conversions")
        and row["current"] is not None}
    if (not hypothesis.startswith("검증 가설: ") or not hypothesis.endswith(_APPEAL_SUFFIXES) or "{{" in hypothesis
            or _UNSUPPORTED_APPEAL.search(hypothesis) or _UNSUPPORTED_COMPETITION.search(hypothesis)
            or _UNSUPPORTED_FUNNEL.search(hypothesis)):
        raise StrategyRefused("UNCONNECTED_EVIDENCE", field="funnel_comment.hypothesis", rule="funnel-hypothesis")
    if (not required <= fields
            or (current and not any(ref[1] in current and ref[2] == "current" for ref in _REF.finditer(basis)))
            or len(refs) != len({ref[0] for ref in refs}) or basis != " · ".join(ref[0] for ref in refs)):
        raise StrategyRefused("UNCONNECTED_EVIDENCE", field="funnel_comment.basis", rule="funnel-basis")
    return {"hypothesis":hypothesis,"basis":basis}


def _validate_competition(value, context):
    if not isinstance(value, dict) or set(value) != {"hypothesis", "basis"}:
        raise StrategyRefused("UNCONNECTED_EVIDENCE", field="competitive_response", rule="competition-shape")
    hypothesis = _field_text(value["hypothesis"], 300, context, "competitive_response.hypothesis")
    basis = _field_text(value["basis"], 600, context, "competitive_response.basis", allow_market=True)
    refs = sorted(list(_MARKET_REF.finditer(basis))+list(_PRODUCT_REF.finditer(basis)), key=lambda ref: ref.start())
    fields = {ref[2] for ref in _MARKET_REF.finditer(basis)}
    price_fields = {"price_min", "price_median", "price_max"}
    products = list(_PRODUCT_REF.finditer(basis))
    if (not hypothesis.startswith("검증 가설: ") or not hypothesis.endswith(_APPEAL_SUFFIXES)
            or "{{" in hypothesis
            or _UNSUPPORTED_APPEAL.search(hypothesis) or _UNSUPPORTED_COMPETITION.search(hypothesis)):
        raise StrategyRefused("UNCONNECTED_EVIDENCE", field="competitive_response.hypothesis", rule="competition-hypothesis")
    if (not {"keyword", "source_status", "sample_count", "price_count"} <= fields
            or (context["market"]["cohorts"][0]["price_count"] > 0 and not fields & price_fields)
            or len(refs) != len({ref[0] for ref in refs}) or basis != " · ".join(ref[0] for ref in refs)
            or any(not any(other[1] == ref[1] and other[2] == "source_status" for other in products) for ref in products)):
        raise StrategyRefused("UNCONNECTED_EVIDENCE", field="competitive_response.basis", rule="competition-basis")
    return {"hypothesis": hypothesis, "basis": basis}


def _validate_template_body(document, context):
    market_ready = context.get("connected", {}).get("market") is True
    competition = None
    funnel = None
    if "funnel" in context:
        if not isinstance(document, dict) or "funnel_comment" not in document:
            raise StrategyRefused("DOCUMENT_INVALID")
        funnel = _validate_funnel(document["funnel_comment"], context)
        document = {**document, "funnel_comment": FUNNEL_COMMENT}
    if market_ready:
        if not isinstance(document, dict) or "competitive_response" not in document:
            raise StrategyRefused("DOCUMENT_INVALID")
        competition = _validate_competition(document["competitive_response"], context)
        document = {**document, "competitive_response": MARKET_UNAVAILABLE_COMMENT}
    clean = normalize_document(document)
    for key, limit in TEXT_LIMITS.items():
        clean[key] = _field_text(clean[key], limit, context, key)
    # 과거 검수 사례와 현재 계획은 현재 보고서의 상품·경쟁·구매·실험 증거가 아니다.
    # 모델이 현재 관찰을 실행한 실험이나 구매 여정으로 바꾸면 그대로 거절한다.
    for key, expected in (("competitive_response", competitive_comment(context)),
            ("funnel_comment", FUNNEL_COMMENT), ("ab_comment", AB_COMMENT)):
        if clean[key] != expected:
            raise StrategyRefused("UNCONNECTED_EVIDENCE", field=key, rule="fixed-boundary")
    if competition is not None:
        clean["competitive_response"] = competition
    if funnel is not None:
        clean["funnel_comment"] = funnel
    for row in clean["appeal_points"]:
        if not context.get("connected", {}).get("product"):
            raise StrategyRefused("UNCONNECTED_EVIDENCE", field="appeal_points", rule="product-unlinked")
        for key, limit in {"title": 100, "message": 300, "basis": 500}.items():
            row[key] = _field_text(row[key], limit, context, "appeal_points."+key)
        refs = list(_PRODUCT_REF.finditer(row["basis"]))
        if (row["title"] not in APPEAL_TITLES or not row["message"].startswith("검증 가설: ") or
                not row["message"].endswith(_APPEAL_SUFFIXES) or _UNSUPPORTED_APPEAL.search(row["message"])):
            error = StrategyRefused("UNCONNECTED_EVIDENCE", field="appeal_points.message", rule="appeal-hypothesis")
            # The original OR and its first-failure order stay authoritative.
            # Retain a finite predicate name, never the title or matched text.
            error.validation_reason = ("TITLE" if row["title"] not in APPEAL_TITLES else
                "PREFIX" if not row["message"].startswith("검증 가설: ") else
                "SUFFIX" if not row["message"].endswith(_APPEAL_SUFFIXES) else "LEXEME")
            raise error
        if (len(refs) < 2 or len({ref[1] for ref in refs}) != 1 or
                not any(ref[2] == "source_status" for ref in refs) or
                not any(ref[2] != "source_status" for ref in refs) or
                row["basis"] != " · ".join(ref[0] for ref in refs)):
            raise StrategyRefused("UNCONNECTED_EVIDENCE", field="appeal_points.basis", rule="appeal-basis")
    for period in ("weekly_plan", "monthly_plan"):
        for row in clean[period]:
            for key, limit in PLAN_LIMITS.items():
                row[key] = _field_text(row[key], limit, context, period+"."+key)
    return clean


def _validate_template(document, context):
    try:
        return _validate_template_body(document, context)
    except StrategyRefused as error:
        # Add only finite diagnostic facts. Accepted/rejected documents and
        # legacy exception codes are unchanged; no candidate text is retained.
        try:
            fallback = {"DOCUMENT_INVALID": "document-shape", "REFERENCE_UNAVAILABLE": "reference-unavailable",
                "NUMERIC_CITATION_REQUIRED": "numeric-reference-required"}
            rule = error.rule or fallback.get(error.code)
            field = error.field or "document"
            cases = context.get("learning", {}).get("cases", [])
            summary = {"version": 1, "field": field, "rule": rule,
                "product_connected": context.get("connected", {}).get("product") is True,
                "market_connected": context.get("connected", {}).get("market") is True,
                "funnel_present": "funnel" in context,
                "exploratory_learning": any(case.get("evidence", {}).get("source_facts", {}).get("exploratory_diagnostic") is not None for case in cases),
                "randomized_learning": any(case.get("evidence", {}).get("source_facts", {}).get("randomized_result") is not None for case in cases)}
            if hasattr(error, "validation_reason"):
                summary["reason"] = error.validation_reason
            clean = SV.normalize(summary)
            if error.code == SV.ERROR_CODES[clean["rule"]]:
                error.validation = clean
        except Exception:
            pass  # Unknown diagnostic remains unknown; it cannot weaken validation.
        raise


def validate_document(document, context):
    """모델의 닫힌 참조 문서를 검증하고 근거 수치를 치환한 일반 텍스트를 반환한다."""
    return _normalize_generated(_render(_validate_template(document, context), context, []), context)


def generate(payload, *, provider=None, learning_context=None, plan_context=None, product_context=None, market_context=None,
             funnel_context=None, setup_context=None, setup_labels=None):
    """명시된 provider만 호출한다. 실패 시 기존 승인본을 대체할 결과를 만들지 않는다."""
    if provider is None:
        return rule_based(payload, learning_context=learning_context, plan_context=plan_context,
            product_context=product_context, market_context=market_context, funnel_context=funnel_context,
            setup_context=setup_context, setup_labels=setup_labels)
    context = build_context(payload, learning_context=learning_context, plan_context=plan_context,
        product_context=product_context, market_context=market_context, funnel_context=funnel_context, setup_context=setup_context)
    render_context = _setup_render_context(context, setup_labels)
    try:
        candidate = provider(deepcopy(context))
    except StrategyRefused:
        raise
    except Exception:
        raise StrategyRefused("PROVIDER_UNAVAILABLE") from None
    clean = _validate_template(candidate, context)
    references = []
    result = {"source": "claude", "model": getattr(provider, "model", None), "prompt_version": PROMPT_VERSION,
        "document": _normalize_generated(_render(clean, render_context, references), context), "references": references,
        "caveats": ["AI 전략 초안이며 담당자 검토·문안 승인이 필요합니다.",
        "광고 전환가치는 플랫폼 전환금액이며 실제 주문·결제 매출과 별도입니다.",
        "문안 승인은 광고 변경 승인이 아닙니다. 실행은 별도 승인·한도·권한 검증이 필요합니다."]}
    return _with_learning_provenance(result, context, learning_context, plan_context, product_context, market_context, funnel_context, setup_context)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def constant(value):
        raise ValueError()
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise StrategyRefused("PROVIDER_RESPONSE_INVALID") from None
