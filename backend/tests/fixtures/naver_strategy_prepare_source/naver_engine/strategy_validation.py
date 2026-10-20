"""Closed validation facts; no response text, references, IDs or metric values.

These optional facts are stored beside the unchanged v1 provider trace. Older
readers can ignore them without losing the trace, its usage or its cost estimate.
"""

FIELDS = frozenset((
    "document", "diagnosis", "direction", "shared_comment", "ab_comment",
    "competitive_response", "competitive_response.hypothesis", "competitive_response.basis",
    "funnel_comment", "funnel_comment.hypothesis", "funnel_comment.basis",
    "appeal_points", "appeal_points.title", "appeal_points.message", "appeal_points.basis",
    "weekly_plan.action", "weekly_plan.reason", "weekly_plan.criterion",
    "monthly_plan.action", "monthly_plan.reason", "monthly_plan.criterion",
))
RULES = frozenset((
    "document-shape", "text-shape", "market-reference-location", "funnel-reference-location",
    "exploratory-claim", "randomized-claim", "numeric-reference-required", "reference-unavailable", "setup-historical-cause",
    "funnel-shape", "funnel-hypothesis", "funnel-basis",
    "competition-shape", "competition-hypothesis", "competition-basis",
    "fixed-boundary", "product-unlinked", "appeal-hypothesis", "appeal-basis",
))
FLAGS = frozenset(("product_connected", "market_connected", "funnel_present",
    "exploratory_learning", "randomized_learning"))
KEYS = frozenset(("version", "field", "rule")) | FLAGS
APPEAL_REASONS = frozenset(("TITLE", "PREFIX", "SUFFIX", "LEXEME"))
NUMERIC_REASONS = frozenset(("BRACES", "LITERAL_NUMERAL", "PERCENT_CURRENCY", "KOREAN_QUANTITY", "REFERENCE_UNIT"))
NUMERIC_FIELDS = FIELDS - {"document", "appeal_points"}
ERROR_CODES = {rule: ("DOCUMENT_INVALID" if rule in ("document-shape", "text-shape") else
    "NUMERIC_CITATION_REQUIRED" if rule == "numeric-reference-required" else
    "REFERENCE_UNAVAILABLE" if rule == "reference-unavailable" else "UNCONNECTED_EVIDENCE") for rule in RULES}
_SPECIFIC_FIELDS = {
    "document-shape": {"document"}, "fixed-boundary": {"competitive_response", "funnel_comment", "ab_comment"},
    "funnel-shape": {"funnel_comment"}, "funnel-hypothesis": {"funnel_comment.hypothesis"}, "funnel-basis": {"funnel_comment.basis"},
    "competition-shape": {"competitive_response"}, "competition-hypothesis": {"competitive_response.hypothesis"},
    "competition-basis": {"competitive_response.basis"}, "product-unlinked": {"appeal_points"},
    "appeal-hypothesis": {"appeal_points.message"}, "appeal-basis": {"appeal_points.basis"},
}


TEXT_POOL_REASONS = frozenset(('POOL_JSON', 'POOL_DOCUMENT', 'POOL_TYPE', 'POOL_SIZE',
    'POOL_TEXT_TYPE', 'POOL_INDEX_TYPE', 'POOL_INDEX_RANGE', 'POOL_UNUSED'))


PROPOSAL_REASONS = {
    **{reason: frozenset(('document',)) for reason in TEXT_POOL_REASONS},
    "KEYS": frozenset(("document", "weekly_plan", "monthly_plan", "competitive_response", "funnel_comment", "appeal_points")),
    "TYPE": frozenset(("document", "diagnosis", "direction", "shared_comment", "weekly_plan", "monthly_plan",
        "weekly_plan.action", "weekly_plan.reason", "weekly_plan.criterion", "monthly_plan.action", "monthly_plan.reason", "monthly_plan.criterion",
        "competitive_response", "funnel_comment", "competitive_response.hypothesis", "funnel_comment.hypothesis",
        "appeal_points", "appeal_points.title", "appeal_points.message", "appeal_points.basis")),
    "ROWS": frozenset(("weekly_plan", "monthly_plan", "appeal_points")),
    "BASIS_ID": frozenset(("appeal_points.basis",)),
    **{reason: frozenset(("competitive_response.hypothesis", "funnel_comment.hypothesis", "appeal_points.message"))
       for reason in ("EMPTY", "LENGTH", "PREFIX", "SUFFIX")},
}


def proposal_pair(value):
    """Only compiler-owned shape facts may use the two plan containers."""
    return (type(value) is dict and value.get("rule") == "document-shape"
        and type(value.get("reason")) is str and value["reason"] in PROPOSAL_REASONS
        and type(value.get("field")) is str and value["field"] in PROPOSAL_REASONS[value["reason"]])


def normalize(value):
    proposal = proposal_pair(value)
    if (type(value) is not dict or set(value) not in (KEYS, KEYS | {"reason"}) or type(value["version"]) is not int
            or value["version"] != 1 or type(value["field"]) is not str or (value["field"] not in FIELDS and not proposal)
            or type(value["rule"]) is not str or value["rule"] not in RULES
            or any(type(value[key]) is not bool for key in FLAGS)
            or (value["field"] not in _SPECIFIC_FIELDS.get(value["rule"], FIELDS) and not proposal)
            or ("reason" in value and (type(value["reason"]) is not str or not (
                (value["field"] == "appeal_points.message" and value["rule"] == "appeal-hypothesis" and
                    value["reason"] in APPEAL_REASONS) or
                (value["field"] in NUMERIC_FIELDS and value["rule"] == "numeric-reference-required" and
                    value["reason"] in NUMERIC_REASONS) or proposal)))):
        raise ValueError("VALIDATION_SUMMARY_INVALID")
    return dict(value)


def failure(error):
    """Never expose arbitrary exception attributes or stringify an error."""
    try:
        return normalize(getattr(error, "validation", None))
    except Exception:
        return None
