"""Closed advertising mandates and commands. Pure; no database, network, or credentials.

This evaluates an explicitly approved operating rule, never an A/B causal winner.
Platform cost is VAT-inclusive; unverified budget units do not become spend proof.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

from . import experiments as X, operating_criteria as OC, inspection_fields as IF

MANDATE_FIELDS = frozenset(('schema_version plan_version operation_start operation_end target_keys allowed_actions rule '
    'evaluation_interval_minutes evaluation_window_days bid_increase_percent bid_decrease_percent minimum_bid '
    'cooldown_minutes max_changes_per_target_24h max_changes_per_account_24h stop notes').split())
STOP_FIELDS = frozenset(('spend_cap performance_threshold consecutive_periods source_max_age_minutes '
    'pause_on_period_end pause_on_source_stale').split())
ACTIONS = frozenset(('create_campaign create_adgroup create_keyword create_text_ad update_bid update_daily_budget set_user_lock').split())
RULES = frozenset(('observe_only_v1', 'target_efficiency_step_v1'))
SCOPE_FIELDS = frozenset(('possibility_id customer_id account_key stage_revision').split())
BINDING_FIELDS = frozenset(('schema_version document scope plan_version plan targets parents').split())
COMMAND_FIELDS = frozenset(('schema_version command_id approval_ref scope plan_version target_key config_epoch action target parent payload channel_fingerprints activation_snapshot evaluation_key created_at').split())
EVIDENCE_FIELDS = frozenset(('status customer_id target_key config_epoch period_start period_end source_at '
    'configuration_verified fields conversion_definition value_basis minimum_source_lag_days').split())
SPEND_FIELDS = frozenset(('status customer_id source_at day month daily_spend monthly_spend risk_spend risk_period_start budget_unit bid_cap_unit campaigns').split())
LEDGER_FIELDS = frozenset(('command_id customer_id target_key target_identity action status at before after').split())
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_UUID = re.compile(r'[0-9a-f]{32}\Z')
_PENDING = frozenset(('reserved', 'dispatched', 'unknown'))
MAX_TARGETS = 100


class ExecutionInvalid(ValueError):
    pass


def _bad(message='실행 위임·명령의 항목과 원천을 확인해 주세요'):
    raise ExecutionInvalid(message)


def _number(value, low=0, high=10**12, integer=False):
    return type(value) in ((int,) if integer else (int, float)) and low <= value <= high and math.isfinite(value)


def _text(value, maximum, *, empty=False):
    if (not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip())
            or re.search(r'[<>\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]', value)
            or any(0xD800 <= ord(c) <= 0xDFFF for c in value)):
        _bad()
    return value


def _day(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value) is None:
        _bad()
    try:
        return date.fromisoformat(value)
    except ValueError:
        _bad()


def parse_moment(value):
    result = X.moment(value)
    if result is None:
        _bad()
    return result


def fingerprint(value):
    try:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError, OverflowError, UnicodeError):
        _bad()


def empty_mandate():
    return {name: 1 if name == 'schema_version' else '' if name == 'notes' else
            dict.fromkeys(sorted(STOP_FIELDS)) if name == 'stop' else [] if name in ('target_keys', 'allowed_actions') else None
            for name in sorted(MANDATE_FIELDS)}


def normalize_mandate(value, *, approve=False):
    if not isinstance(value, dict) or set(value) != MANDATE_FIELDS or type(value['schema_version']) is not int or value['schema_version'] != 1:
        _bad()
    out = deepcopy(value)
    if out['rule'] is not None and (not isinstance(out['rule'], str) or out['rule'] not in RULES):
        _bad()
    for name, permitted, maximum in (('target_keys', None, MAX_TARGETS), ('allowed_actions', {'bid', 'pause'}, 2)):
        rows = out[name]
        if not isinstance(rows, list) or len(rows) > maximum or any(not isinstance(row, str) for row in rows) or len(set(rows)) != len(rows):
            _bad()
        if any(not isinstance(row, str) or (_HEX.fullmatch(row) is None if permitted is None else row not in permitted) for row in rows):
            _bad()
    for name in ('operation_start', 'operation_end'):
        if out[name] is not None:
            _day(out[name])
    if out['operation_start'] and out['operation_end'] and not 1 <= (_day(out['operation_end'])-_day(out['operation_start'])).days+1 <= 366:
        _bad()
    ranges = {'plan_version': (1, 2**53-1, True), 'evaluation_interval_minutes': (1, 43200, True),
        'evaluation_window_days': (1, 30, True), 'bid_increase_percent': (0, 1000, False),
        'bid_decrease_percent': (0, 100, False), 'minimum_bid': (70, 100000, True),
        'cooldown_minutes': (1, 525600, True), 'max_changes_per_target_24h': (1, 1000, True),
        'max_changes_per_account_24h': (1, 10000, True)}
    for name, bounds in ranges.items():
        if out[name] is not None and not _number(out[name], *bounds[:2], integer=bounds[2]):
            _bad()
    stop = out['stop']
    if not isinstance(stop, dict) or set(stop) != STOP_FIELDS:
        _bad()
    for name, bounds in {'spend_cap': (1e-12, 10**12, False), 'performance_threshold': (0, 1000, False),
            'consecutive_periods': (1, 100, True), 'source_max_age_minutes': (1, 43200, True)}.items():
        if stop[name] is not None and not _number(stop[name], *bounds[:2], integer=bounds[2]):
            _bad()
    for name in ('pause_on_period_end', 'pause_on_source_stale'):
        if stop[name] is not None and type(stop[name]) is not bool:
            _bad()
    _text(out['notes'], 1000, empty=True)
    if approve:
        required = MANDATE_FIELDS-{'schema_version', 'notes', 'stop'}
        if any(out[name] is None or out[name] == [] for name in required) or any(v is None for v in stop.values()):
            _bad('대상·기간·평가·변경·중단 기준을 명시한 뒤 승인해 주세요')
        if out['max_changes_per_account_24h'] < out['max_changes_per_target_24h']:
            _bad()
        if out['rule'] == 'target_efficiency_step_v1' and 'bid' not in out['allowed_actions']:
            _bad()
        if (stop['pause_on_period_end'] or stop['pause_on_source_stale']) and 'pause' not in out['allowed_actions']:
            _bad()
    return out


def _scope(value):
    if not isinstance(value, dict) or set(value) != SCOPE_FIELDS:
        _bad()
    if any(not _number(value[name], 1, 2**53-1, integer=True) for name in ('possibility_id', 'customer_id')):
        _bad()
    if (not isinstance(value['account_key'], str) or not _HEX.fullmatch(value['account_key'])
            or not isinstance(value['stage_revision'], str) or not 1 <= len(value['stage_revision']) <= 160):
        _bad()
    return deepcopy(value)


def _plan(view):
    try:
        return X._plan(view)
    except (ValueError, TypeError, KeyError, OverflowError):
        _bad('현재 승인된 업체별 v2 운영 기준이 필요합니다')


def bind_mandate(document, plan_view, catalog, now, *, approve=False):
    now, doc, plan = parse_moment(now), normalize_mandate(document, approve=approve), _plan(plan_view)
    if (not isinstance(catalog, dict) or catalog.get('status') != 'ready' or not isinstance(catalog.get('_arms'), dict)
            or not isinstance(catalog.get('scope'), dict)):
        _bad('현재 대상·설정 원천이 필요합니다')
    scope = _scope({key: catalog['scope'].get(key) for key in SCOPE_FIELDS})
    if parse_moment(catalog['scope'].get('generation')) > now or doc['plan_version'] is not None and doc['plan_version'] != plan_view['version']:
        _bad('현재 운영계획 판과 위임 계획을 대조해 주세요')
    for name, bound in (('operation_start', plan['period_start']), ('operation_end', plan['period_end'])):
        if doc[name] is not None and (doc[name] < bound if name.endswith('start') else doc[name] > bound):
            _bad('승인한 운영 기간을 벗어났습니다')
    for name, limit in (('bid_increase_percent', 'single_increase_percent'), ('bid_decrease_percent', 'single_decrease_percent')):
        if doc[name] is not None and doc[name] > plan['change_limits'][limit]:
            _bad('승인한 한 번 변경 한도를 넘었습니다')
    if doc['minimum_bid'] is not None and doc['minimum_bid'] > plan['absolute_bid_cap']:
        _bad()
    if doc['stop']['spend_cap'] is not None and doc['stop']['spend_cap'] > plan['loss_cap']:
        _bad('승인한 광고 지출 위험 한도를 넘었습니다')
    if doc['rule'] == 'target_efficiency_step_v1' and plan['goal'] not in ('cpa', 'roas'):
        _bad('현재 효율 규칙은 CPA·ROAS 목표에만 적용합니다')
    threshold = doc['stop']['performance_threshold']
    if threshold is not None and ((plan['goal'] == 'cpa' and threshold < 1) or (plan['goal'] == 'roas' and not 0 <= threshold <= 1)):
        _bad('중단 기준의 목표 대비 배수·비율을 확인해 주세요')
    targets, parents = {}, {}
    for key in doc['target_keys']:
        try:
            target = X.normalize_arm(catalog['_arms'][key], scope['customer_id'])
        except (KeyError, ValueError, TypeError):
            _bad('현재 목록에서 실행 대상을 다시 선택해 주세요')
        if 'bid' in doc['allowed_actions'] and target['kind'] not in ('adgroup', 'keyword'):
            _bad('자동 입찰 대상은 광고그룹·키워드만 지원합니다')
        targets[key] = target
        if target['kind'] != 'campaign':
            kind = 'campaign' if target['kind'] == 'adgroup' else 'adgroup'
            matches = [a for a in catalog['_arms'].values() if a['kind'] == kind and a['id'] == target['parent_id']]
            if len(matches) != 1:
                _bad('부모 대상 원천을 확인해 주세요')
            parents[key] = X.normalize_arm(matches[0], scope['customer_id'])
    # Parent/child targeting would double-count a mandate's risk and changes.
    identifiers = {target['id'] for target in targets.values()}
    if any(target['parent_id'] in identifiers or (target['campaign_id'] in identifiers and target['kind'] != 'campaign') for target in targets.values()):
        _bad('부모와 자식을 겹쳐 위임할 수 없습니다')
    return dict(schema_version=1, document=doc, scope=scope, plan_version=plan_view['version'], plan=plan, targets=targets, parents=parents)


def validate_binding(value):
    if not isinstance(value, dict) or set(value) != BINDING_FIELDS or type(value['schema_version']) is not int or value['schema_version'] != 1:
        _bad()
    doc = normalize_mandate(value['document'], approve=True)
    scope = _scope(value['scope'])
    plan = _plan({'state': 'approved', 'version': value['plan_version'], 'plan': value['plan']})
    if doc['plan_version'] != value['plan_version'] or not isinstance(value['targets'], dict) or set(value['targets']) != set(doc['target_keys']):
        _bad()
    for target in value['targets'].values():
        try:
            X.normalize_arm(target, scope['customer_id'])
        except (ValueError, TypeError):
            _bad()
    if not isinstance(value['parents'], dict) or set(value['parents']) != {k for k, a in value['targets'].items() if a['kind'] != 'campaign'}:
        _bad()
    # Reuse the same complete semantic validation; persisted JSON is not trusted.
    catalog = dict(status='ready', scope=dict(scope, generation='2000-01-01T00:00:00+09:00'),
        _arms={**value['targets'], **{'parent:'+a['kind']+':'+a['id']: a for a in value['parents'].values()}})
    rebuilt = bind_mandate(doc, {'state': 'approved', 'version': value['plan_version'], 'plan': plan}, catalog,
        '2000-01-01T00:00:00+09:00', approve=True)
    if rebuilt != value:
        _bad()
    return deepcopy(value)


def _epoch(binding, key, epochs=None):
    if key not in binding['targets']:
        _bad()
    row = (epochs or {}).get(key)
    if row is None:
        return dict(epoch=0, target=deepcopy(binding['targets'][key]), applied_at=None)
    if not isinstance(row, dict) or set(row) != {'epoch', 'target', 'applied_at'} or not _number(row['epoch'], 0, 2**53-1, integer=True):
        _bad()
    try:
        target = X.normalize_arm(row['target'], binding['scope']['customer_id'])
    except (ValueError, TypeError):
        _bad()
    if any(target[name] != binding['targets'][key][name] for name in ('kind', 'id', 'parent_id', 'campaign_id')):
        _bad()
    if row['applied_at'] is not None:
        parse_moment(row['applied_at'])
    return deepcopy(row)


def current_mandate(binding, plan_view, catalog, now, *, epochs=None):
    bound, now = validate_binding(binding), parse_moment(now)
    if _plan(plan_view) != bound['plan'] or plan_view['version'] != bound['plan_version']:
        _bad('승인한 운영계획이 바뀌었습니다')
    if not isinstance(catalog, dict) or catalog.get('status') != 'ready' or not isinstance(catalog.get('scope'), dict):
        _bad('현재 설정 원천을 확인하지 못했습니다')
    if _scope({key: catalog['scope'].get(key) for key in SCOPE_FIELDS}) != bound['scope'] or parse_moment(catalog['scope'].get('generation')) > now:
        _bad('현재 업체·계정·계약 단계가 바뀌었습니다')
    actual = catalog.get('_arms', {})
    for key in bound['targets']:
        expected = _epoch(bound, key, epochs)['target']
        matches = [target for target in actual.values() if isinstance(target, dict) and target.get('kind') == expected['kind'] and target.get('id') == expected['id']]
        if len(matches) != 1 or matches[0] != expected:
            _bad('승인 또는 반영 확인한 대상 설정과 현재 설정이 다릅니다')
        parent = bound['parents'].get(key)
        if parent is not None and sum(a == parent for a in actual.values()) != 1:
            _bad('승인한 부모 대상 설정과 현재 설정이 다릅니다')
    return True


def _ledger(value, customer_id, now, *, exclude_command_id=None):
    if not isinstance(value, list) or len(value) > 10000:
        _bad('변경 원장을 확인하지 못했습니다')
    out, seen = [], set()
    for row in value:
        if (not isinstance(row, dict) or set(row) != LEDGER_FIELDS or not isinstance(row['command_id'], str)
                or not _UUID.fullmatch(row['command_id']) or row['command_id'] in seen or row['customer_id'] != customer_id
                or not isinstance(row['target_key'], str) or not _HEX.fullmatch(row['target_key'])
                or not isinstance(row['target_identity'], str) or not _HEX.fullmatch(row['target_identity'])
                or not isinstance(row['action'], str) or row['action'] not in ACTIONS
                or not isinstance(row['status'], str) or row['status'] not in _PENDING | {'confirmed', 'rejected'}):
            _bad('변경 원장의 범위와 상태를 확인해 주세요')
        at = parse_moment(row['at'])
        if at > now:
            _bad()
        for name in ('before', 'after'):
            if row[name] is not None and type(row[name]) is not bool and not _number(row[name]):
                _bad()
        seen.add(row['command_id'])
        if row['command_id'] != exclude_command_id:
            out.append((row, at))
    return out


def _spend(value, binding, now):
    if not isinstance(value, dict) or set(value) != SPEND_FIELDS or value['status'] != 'ok' or value['customer_id'] != binding['scope']['customer_id']:
        return None
    try:
        source = parse_moment(value['source_at'])
        if not timedelta(0) <= now-source <= timedelta(minutes=binding['document']['stop']['source_max_age_minutes']):
            return None
        if value['day'] != now.date().isoformat() or value['month'] != now.strftime('%Y-%m'):
            return None
        if value['risk_period_start'] != binding['plan']['period_start']:return None
        if any(not _number(value[name]) for name in ('daily_spend', 'monthly_spend', 'risk_spend')):
            return None
        if value['budget_unit'] not in ('vat_included_krw', 'vat_excluded_krw', 'unknown') or not isinstance(value['campaigns'], list) or len(value['campaigns']) > 10000:
            return None
        return deepcopy(value)
    except (ValueError, TypeError, OverflowError):
        return None


def _result(state, reasons, **values):
    return dict(state=state, reason_codes=list(dict.fromkeys(reasons)), **values)


def assess_operation(binding, target_key, evidence, account_spend, ledger, now, *, epochs=None, consecutive_periods=0):
    bound, now = validate_binding(binding), parse_moment(now)
    doc, plan, ep = bound['document'], bound['plan'], _epoch(bound, target_key, epochs)
    empty = dict(evaluation_key=None, action=None, desired=None, metric=None, at_target=None, deteriorated=None)
    try:
        history = _ledger(ledger, bound['scope']['customer_id'], now)
    except ExecutionInvalid:
        return _result('hold', ['LEDGER_UNAVAILABLE'], **empty)
    if any(row['status'] in _PENDING for row, at in history):
        return _result('hold', ['ACCOUNT_OUTCOME_PENDING'], **empty)
    if now.date() < _day(doc['operation_start']):
        return _result('hold', ['NOT_STARTED'], **empty)
    stop_reason = None
    if now.date() > _day(doc['operation_end']):
        if doc['stop']['pause_on_period_end']:
            stop_reason = 'OPERATION_ENDED'
        else:
            return _result('hold', ['OPERATION_ENDED'], **empty)
    spending = _spend(account_spend, bound, now)
    if spending and spending['risk_spend'] >= doc['stop']['spend_cap']:
        stop_reason = 'RISK_SPEND_AT_CAP'
    if spending and (spending['daily_spend'] >= plan['daily_spend_cap'] or spending['monthly_spend'] >= plan['monthly_spend_cap']):
        stop_reason = 'ACCOUNT_SPEND_AT_CAP'
    if stop_reason:
        return _pause_decision(bound, target_key, ep, now, stop_reason)
    if (not isinstance(evidence, dict) or set(evidence) != EVIDENCE_FIELDS or evidence['status'] != 'ok'
            or evidence['customer_id'] != bound['scope']['customer_id'] or evidence['target_key'] != target_key
            or type(evidence['config_epoch']) is not int or evidence['config_epoch'] != ep['epoch']
            or evidence['configuration_verified'] is not True):
        return _result('hold', ['ENTITY_EVIDENCE_UNAVAILABLE'], **empty)
    try:
        source, start, end = parse_moment(evidence['source_at']), _day(evidence['period_start']), _day(evidence['period_end'])
        if not timedelta(0) <= now-source <= timedelta(minutes=doc['stop']['source_max_age_minutes']):
            if doc['stop']['pause_on_source_stale']:
                return _pause_decision(bound, target_key, ep, now, 'SOURCE_STALE')
            return _result('hold', ['SOURCE_STALE'], **empty)
        if (end >= now.date() or (end-start).days+1 != doc['evaluation_window_days'] or start < _day(doc['operation_start'])
                or end > _day(doc['operation_end'])):
            return _result('hold', ['EVALUATION_WINDOW_INVALID'], **empty)
        if ep['applied_at'] and start <= parse_moment(ep['applied_at']).date():
            return _result('hold', ['POST_CHANGE_WINDOW_NOT_MATURE'], **empty)
        boundary = datetime.combine(end+timedelta(days=1), time(), OC.KST)
        if source < boundary or source-boundary < timedelta(days=plan['measurement_lag_days']):
            return _result('hold', ['MEASUREMENT_WAIT'], **empty)
        if not _number(evidence['minimum_source_lag_days'], plan['measurement_lag_days'], 366, integer=True):
            return _result('hold', ['MEASUREMENT_WAIT'], **empty)
        fields = evidence['fields']
        if not isinstance(fields, dict) or set(fields) != set(X.FIELDS) or any(v is not None and not _number(v, high=9e15,integer=k in ('impCnt','clkCnt')) for k,v in fields.items()):
            return _result('hold', ['METRICS_INVALID'], **empty)
    except (ValueError, TypeError, OverflowError):
        return _result('hold', ['ENTITY_EVIDENCE_UNAVAILABLE'], **empty)
    evaluation = fingerprint([bound['scope'], target_key, evidence['period_start'], evidence['period_end']])
    empty['evaluation_key'] = evaluation
    if doc['rule'] == 'observe_only_v1':
        return _result('noop', ['OBSERVE_ONLY'], **empty)
    needed = ('clkCnt', 'salesAmt', 'ccnt') + (('convAmt',) if plan['goal'] == 'roas' else ())
    if any(fields[name] is None for name in needed):
        return _result('hold', ['METRICS_PARTIAL'], **empty)
    # Existing OC.performance_from_observation/report uses literal 'platform'
    # specifically for ccnt/convAmt. It is the only legacy alias, never free text.
    general = {'platform', 'platform_all_conversions'}
    if (not isinstance(evidence['conversion_definition'],str) or evidence['conversion_definition'] not in general
            or plan['conversion_definition'] not in general or (plan['goal'] == 'roas' and evidence['value_basis'] != plan['value_basis'])):
        return _result('hold', ['METRIC_DEFINITION_MISMATCH'], **empty)
    if fields['clkCnt'] < plan['minimum_clicks'] or fields['ccnt'] < plan['minimum_conversions']:
        return _result('hold', ['SAMPLE_BELOW_PLAN'], **empty)
    denominator = fields['ccnt'] if plan['goal'] == 'cpa' else fields['salesAmt']
    if denominator == 0:
        return _result('hold', ['ZERO_DENOMINATOR'], **empty)
    metric = fields['salesAmt']/denominator if plan['goal'] == 'cpa' else fields['convAmt']/denominator*100
    if not math.isfinite(metric):
        return _result('hold', ['METRIC_OUT_OF_RANGE'], **empty)
    threshold = doc['stop']['performance_threshold']
    deteriorated = metric > plan['target_value']*threshold if plan['goal'] == 'cpa' else metric < plan['target_value']*threshold
    empty.update(metric=metric, deteriorated=deteriorated)
    if not _number(consecutive_periods, 0, 100000, integer=True):
        return _result('hold', ['STOP_HISTORY_UNAVAILABLE'], **empty)
    if deteriorated and consecutive_periods+1 >= doc['stop']['consecutive_periods']:
        return dict(_pause_decision(bound, target_key, ep, now, 'PERFORMANCE_STOP', evaluation=evaluation), metric=metric, at_target=False, deteriorated=True)
    at_target = metric <= plan['target_value'] if plan['goal'] == 'cpa' else metric >= plan['target_value']
    empty['at_target'] = at_target
    step = doc['bid_increase_percent'] if at_target else doc['bid_decrease_percent']
    if step == 0:
        return _result('noop', ['DIRECTION_DISABLED'], **empty)
    target = ep['target']
    settings = target['settings']
    group = target if target['kind'] == 'adgroup' else bound['parents'].get(target_key)
    if target['kind'] not in ('adgroup', 'keyword') or not _manual_group(group):
        return _result('hold', ['NATIVE_AUTOMATION_UNSUPPORTED'], **empty)
    if target['kind'] == 'keyword' and settings.get('useGroupBidAmt') is not False:
        return _result('hold', ['INHERITED_BID_UNSUPPORTED'], **empty)
    current = settings.get('bidAmt')
    if not _number(current, 70, 100000, integer=True):
        return _result('hold', ['BID_UNAVAILABLE'], **empty)
    desired = Decimal(current)*(Decimal(1)+(Decimal(str(step))/100 if at_target else -Decimal(str(step))/100))
    if desired != desired.to_integral_value():
        return _result('hold', ['NONINTEGER_BID'], **empty)
    decision = dict(action='update_bid', desired={'bidAmt': int(desired)}, evaluation_key=evaluation)
    if target['kind'] == 'keyword':
        decision['desired']['useGroupBidAmt'] = False
    return _result('queue', ['TARGET_MET' if at_target else 'TARGET_NOT_MET'], **decision, metric=metric, at_target=at_target, deteriorated=deteriorated)


def _pause_decision(binding, key, epoch, now, reason, *, evaluation=None):
    if 'pause' not in binding['document']['allowed_actions']:
        return _result('hold', [reason, 'PAUSE_NOT_DELEGATED'], evaluation_key=evaluation, action=None, desired=None)
    if epoch['target']['settings'].get('userLock') is True:
        return _result('noop', [reason, 'ALREADY_PAUSED'], evaluation_key=evaluation, action=None, desired=None)
    if epoch['target']['settings'].get('userLock') is not False:
        return _result('hold', [reason, 'LOCK_STATE_UNAVAILABLE'], evaluation_key=evaluation, action=None, desired=None)
    return _result('queue', [reason], evaluation_key=evaluation or fingerprint([binding['scope'], key, now.date().isoformat(), reason]), action='set_user_lock', desired={'userLock': True})


def _manual_group(group):
    if not isinstance(group, dict) or group.get('kind') != 'adgroup':
        return False
    s = group.get('settings', {})
    return (s.get('adgroupType') == 'WEB_SITE' and s.get('systemBiddingType') == 'NONE'
        and s.get('aiAdsOptIn') is False and s.get('useExpSearch') is False
        and s.get('pcNetworkBidWeight') == 100 and s.get('mobileNetworkBidWeight') == 100
        and type(s.get('pcNetworkBidWeight')) in (int, float) and type(s.get('mobileNetworkBidWeight')) in (int, float)
        and s.get('useCntsNetworkBidAmt') is False and s.get('useCntsNetworkBidWeight') is False)


MANIFEST_FIELDS = frozenset(('action target_key parent_key payload').split())
PAYLOAD_FIELDS = {
    'create_campaign': frozenset(('name daily_budget delivery_method period_start period_end').split()),
    'create_adgroup': frozenset(('name bid daily_budget pc_channel_key mobile_channel_key use_exp_search ai_ads_opt_in '
        'system_bidding_type ad_rolling_type pc_network_bid_weight mobile_network_bid_weight contents_network_bid use_contents_network_bid').split()),
    'create_keyword': frozenset(('keyword bid').split()),
    'create_text_ad': frozenset(('headline description pc_final mobile_final').split()),
    'update_bid': frozenset(('bid',)), 'update_daily_budget': frozenset(('daily_budget',)),
    'set_user_lock': frozenset(('user_lock',)),
}


def empty_manifest():
    return dict(action=None, target_key=None, parent_key=None, payload={})


def _url(value):
    _text(value, 1024)
    try:
        p = urlsplit(value)
        if (p.scheme not in ('http', 'https') or not p.hostname or p.username is not None or p.password is not None
                or p.fragment or any(c.isspace() for c in value) or '\\' in value or p.port not in (None, 80, 443)):
            _bad('HTTP·HTTPS 최종 URL 형식을 확인해 주세요')
        p.hostname.encode('idna')
    except (ValueError, UnicodeError):
        _bad('HTTP·HTTPS 최종 URL 형식을 확인해 주세요')
    return value


def _creative(value, low, high):
    _text(value, high)
    if not low <= len(value) <= high or re.fullmatch(r'[가-힣ㄱ-ㅎㅏ-ㅣA-Za-z0-9 ~!#$%&():;?=+\-/.,\"\']+', value) is None:
        _bad('TEXT_45 문구 길이·문자 범위를 확인해 주세요. 동적 키워드 문법은 지원하지 않습니다')
    return value


def normalize_manifest(value, *, approve=False):
    if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
        _bad()
    out = deepcopy(value)
    action = out['action']
    if action is None:
        if approve or out != empty_manifest(): _bad()
        return out
    if not isinstance(action, str) or action not in ACTIONS or not isinstance(out['payload'], dict) or set(out['payload']) != PAYLOAD_FIELDS[action]:
        _bad()
    for key in ('target_key', 'parent_key'):
        if out[key] is not None and (not isinstance(out[key], str) or not _HEX.fullmatch(out[key])): _bad()
    creation = action.startswith('create_')
    if creation and out['target_key'] is not None or not creation and out['parent_key'] is not None:
        _bad()
    if approve and ((not creation and out['target_key'] is None) or (creation and action != 'create_campaign' and out['parent_key'] is None)):
        _bad('현재 목록에서 대상·부모를 선택해 주세요')
    if action == 'create_campaign' and out['parent_key'] is not None: _bad()
    p = out['payload']
    for name, v in p.items():
        if v is None:
            if approve: _bad('명령의 모든 설정값을 명시해 주세요')
            continue
        if name in ('bid', 'contents_network_bid') and not _number(v, 70, 100000, integer=True): _bad()
        elif name == 'daily_budget' and (not _number(v, 70, 10**9, integer=True) or v % 10): _bad('일예산은 명시한 10원 단위 금액으로 입력해 주세요')
        elif name in ('pc_network_bid_weight', 'mobile_network_bid_weight') and (type(v) is not int or v != 100):
            _bad('첫 실행 범위는 명시한 PC·모바일 가중치 100%만 지원합니다')
        elif name in ('user_lock', 'use_exp_search', 'ai_ads_opt_in', 'use_contents_network_bid') and type(v) is not bool: _bad()
        elif name in ('use_exp_search', 'ai_ads_opt_in', 'use_contents_network_bid') and v is not False:
            _bad('확장검색·네이버 자체 자동입찰은 첫 실행 범위에 포함하지 않습니다')
        elif name == 'system_bidding_type' and v != 'NONE': _bad()
        elif name == 'ad_rolling_type' and v not in ('ROUND_ROBIN', 'PERFORMANCE'): _bad()
        elif name == 'delivery_method' and v not in ('STANDARD', 'ACCELERATED'): _bad()
        elif name in ('pc_channel_key', 'mobile_channel_key') and (not isinstance(v, str) or not _HEX.fullmatch(v)): _bad()
        elif name in ('period_start', 'period_end'): _day(v)
        elif name in ('pc_final', 'mobile_final'): _url(v)
        elif name == 'headline': _creative(v, 1, 15)
        elif name == 'description': _creative(v, 20, 45)
        elif name in ('name', 'keyword'): _text(v, 100 if name == 'name' else 25)
    if p.get('period_start') and p.get('period_end') and p['period_start'] > p['period_end']: _bad()
    return out


def _approval(value):
    if (not isinstance(value, dict) or set(value) != {'kind', 'id', 'version'} or value['kind'] not in ('mandate', 'one_shot', 'randomized_experiment', 'randomized_experiment_stop')
            or not isinstance(value['id'], str) or not _UUID.fullmatch(value['id']) or not _number(value['version'], 1, 2**53-1, integer=True)):
        _bad()
    return deepcopy(value)


def _command_common(scope, plan_version, target_key, epoch, action, target, parent, payload, now, command_id, approval_ref, evaluation=None,channel_fingerprints=None,activation_snapshot=None):
    if not isinstance(command_id, str) or not _UUID.fullmatch(command_id): _bad()
    return validate_command(dict(schema_version=1, command_id=command_id, approval_ref=_approval(approval_ref), scope=_scope(scope),
        plan_version=plan_version, target_key=target_key, config_epoch=epoch, action=action, target=target, parent=parent,
        payload=payload,channel_fingerprints=channel_fingerprints or {},activation_snapshot=activation_snapshot or [], evaluation_key=evaluation, created_at=parse_moment(now).isoformat()))


def build_command(binding, target_key, decision, now, *, command_id, approval_ref, epochs=None):
    b = validate_binding(binding)
    if not isinstance(decision, dict) or decision.get('state') != 'queue' or decision.get('action') not in ('update_bid', 'set_user_lock'):
        _bad()
    if decision['action'] == 'update_bid' and 'bid' not in b['document']['allowed_actions'] or decision['action'] == 'set_user_lock' and ('pause' not in b['document']['allowed_actions'] or decision.get('desired') != {'userLock': True}): _bad()
    ep = _epoch(b, target_key, epochs)
    return _command_common(b['scope'], b['plan_version'], target_key, ep['epoch'], decision['action'], ep['target'],
        b['parents'].get(target_key), deepcopy(decision['desired']), now, command_id, approval_ref, decision['evaluation_key'])


def bind_one_shot(manifest, plan_view, catalog, now, *, command_id, approval_ref, channels=None):
    m, now, plan = normalize_manifest(manifest, approve=True), parse_moment(now), _plan(plan_view)
    if not isinstance(catalog, dict) or catalog.get('status') != 'ready' or not isinstance(catalog.get('_arms'), dict): _bad()
    scope = _scope({k: catalog['scope'].get(k) for k in SCOPE_FIELDS})
    if parse_moment(catalog['scope']['generation']) > now: _bad()
    action, p = m['action'], m['payload']
    channel_fingerprints={}
    def arm(key):
        try: return X.normalize_arm(catalog['_arms'][key], scope['customer_id'])
        except (KeyError, ValueError, TypeError): _bad('현재 실행 대상을 다시 선택해 주세요')
    target = arm(m['target_key']) if m['target_key'] else None
    parent = arm(m['parent_key']) if m['parent_key'] else None
    if target and target['kind'] != 'campaign':
        candidates = [a for a in catalog['_arms'].values() if a['id'] == target['parent_id']]
        if len(candidates) != 1: _bad()
        parent = X.normalize_arm(candidates[0], scope['customer_id'])
    if action == 'create_campaign':
        if p['period_start'] < plan['period_start'] or p['period_end'] > plan['period_end']: _bad('운영계획 기간을 벗어났습니다')
        payload = dict(customerId=scope['customer_id'], name=p['name'], campaignTp='WEB_SITE', dailyBudget=p['daily_budget'],
            useDailyBudget=True, userLock=True, deliveryMethod=p['delivery_method'], usePeriod=True,
            periodStartDt=_api_day(p['period_start']), periodEndDt=_api_day(p['period_end']), trackingMode='TRACKING_DISABLED')
    elif action == 'create_adgroup':
        if parent['kind'] != 'campaign' or parent['settings'].get('campaignTp') != 'WEB_SITE' or parent['settings'].get('userLock') is not True: _bad('잠금 확인된 WEB_SITE 캠페인이 필요합니다')
        ids = []
        for field in ('pc_channel_key', 'mobile_channel_key'):
            ch = (channels or {}).get(p[field])
            if (not isinstance(ch, dict) or ch.get('customer_id') != scope['customer_id'] or ch.get('type') != 'SITE'
                    or ch.get('status') != 'ELIGIBLE' or not IF.valid_id(ch.get('id'))):
                _bad('현재 계정의 사용 가능한 SITE 채널을 먼저 확인해 주세요')
            if ch.get('source_at') is None or not timedelta(0) <= now-parse_moment(ch['source_at']) <= timedelta(minutes=30): _bad('SITE 채널 자료를 갱신해 주세요')
            ids.append(ch['id'])
            channel_fingerprints[ch['id']]=fingerprint(_url(ch.get('channel_key')))
        payload = dict(customerId=scope['customer_id'], nccCampaignId=parent['id'], name=p['name'], adgroupType='WEB_SITE',
            pcChannelId=ids[0], mobileChannelId=ids[1], bidAmt=p['bid'], dailyBudget=p['daily_budget'], useDailyBudget=True,
            userLock=True, useExpSearch=False, aiAdsOptIn=False, systemBiddingType='NONE', adRollingType=p['ad_rolling_type'],
            pcNetworkBidWeight=100, mobileNetworkBidWeight=100, useCntsNetworkBidAmt=False, useCntsNetworkBidWeight=False,
            contentsNetworkBidAmt=p['contents_network_bid'])
    elif action in ('create_keyword', 'create_text_ad'):
        if not _manual_group(parent) or parent['settings'].get('userLock') is not True: _bad('잠금·수동입찰 설정이 확인된 WEB_SITE 광고그룹이 필요합니다')
        if action == 'create_keyword': payload = dict(keyword=p['keyword'], bidAmt=p['bid'], useGroupBidAmt=False, userLock=True)
        else: payload = dict(type='TEXT_45', nccAdgroupId=parent['id'], ad=dict(headline=p['headline'], description=p['description'], pc={'final': p['pc_final']}, mobile={'final': p['mobile_final']}))
    elif action == 'update_bid':
        if target['kind'] not in ('adgroup', 'keyword') or not _manual_group(target if target['kind'] == 'adgroup' else parent): _bad('현재 수동 입찰 원천을 확인해 주세요')
        if target['kind'] == 'keyword' and target['settings'].get('useGroupBidAmt') is not False: _bad('그룹 입찰 상속은 자동 해제하지 않습니다')
        payload = {'bidAmt': p['bid']}
        if target['kind'] == 'keyword': payload['useGroupBidAmt'] = False
    elif action == 'update_daily_budget':
        if target['kind'] not in ('campaign', 'adgroup'): _bad()
        if target['settings'].get('useDailyBudget') is not True or not _number(target['settings'].get('dailyBudget'), 70, 10**9, integer=True): _bad('현재 유한 일예산을 확인해 주세요')
        payload = dict(dailyBudget=p['daily_budget'], useDailyBudget=True)
    else: payload = {'userLock': p['user_lock']}
    # A new entity's opaque key binds the exact approved manifest; it is not a platform ID.
    key = m['target_key'] or fingerprint(['new-entity', scope, m, command_id])
    descendants=_activation_descendants(target,catalog['_arms'].values()) if action=='set_user_lock' and p['user_lock'] is False and target['kind'] in ('campaign','adgroup') else []
    return _command_common(scope, plan_view['version'], key, 0, action, target, parent, payload, now, command_id, approval_ref,channel_fingerprints=channel_fingerprints,activation_snapshot=descendants)


def _api_day(value):
    return datetime.combine(_day(value), time(), OC.KST).astimezone(X.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def validate_command(value):
    if not isinstance(value, dict) or set(value) != COMMAND_FIELDS or type(value['schema_version']) is not int or value['schema_version'] != 1: _bad()
    _scope(value['scope']); _approval(value['approval_ref']); parse_moment(value['created_at'])
    if (not isinstance(value['command_id'], str) or not _UUID.fullmatch(value['command_id']) or not isinstance(value['target_key'], str)
            or not _HEX.fullmatch(value['target_key']) or not _number(value['plan_version'], 1, 2**53-1, integer=True)
            or not _number(value['config_epoch'], 0, 2**53-1, integer=True) or not isinstance(value['action'], str) or value['action'] not in ACTIONS): _bad()
    if value['evaluation_key'] is not None and (not isinstance(value['evaluation_key'], str) or not _HEX.fullmatch(value['evaluation_key'])): _bad()
    target, parent, action, p, cid = value['target'], value['parent'], value['action'], value['payload'], value['scope']['customer_id']
    for a in (target, parent):
        if a is not None:
            try: X.normalize_arm(a, cid)
            except (ValueError, TypeError): _bad()
    if not isinstance(p, dict): _bad()
    snapshot=value['activation_snapshot']
    if not isinstance(snapshot,list) or len(snapshot)>101:_bad()
    for arm in snapshot:
        try:X.normalize_arm(arm,cid)
        except (ValueError,TypeError):_bad()
    activation=action=='set_user_lock' and p.get('userLock') is False and target and target['kind'] in ('campaign','adgroup')
    formal = value['approval_ref']['kind'] == 'randomized_experiment'
    terminal = value['approval_ref']['kind'] == 'randomized_experiment_stop'
    if terminal:
        if (action!='set_user_lock' or p!={'userLock':True} or not target or target['kind']!='ad'
                or not parent or parent['kind']!='adgroup' or target['parent_id']!=parent['id']
                or target['campaign_id']!=parent['campaign_id'] or snapshot):_bad()
    elif formal:
        if action != 'set_user_lock' or not target or target['kind'] != 'ad': _bad()
        _randomized_snapshot(value)
    elif activation:
        if _activation_descendants(target,snapshot)!=snapshot:_bad()
    elif snapshot:_bad()
    fps=value['channel_fingerprints']
    if (not isinstance(fps,dict) or any(not IF.valid_id(k) or not isinstance(v,str) or not _HEX.fullmatch(v) for k,v in fps.items())
            or action!='create_adgroup' and fps):_bad()
    if action.startswith('create_'):
        if target is not None: _bad()
        if action == 'create_campaign':
            keys = {'customerId','name','campaignTp','dailyBudget','useDailyBudget','userLock','deliveryMethod','usePeriod','periodStartDt','periodEndDt','trackingMode'}
            if set(p) != keys or parent is not None or p['campaignTp'] != 'WEB_SITE' or p['customerId'] != cid or p['usePeriod'] is not True or p['trackingMode'] != 'TRACKING_DISABLED' or p['deliveryMethod'] not in ('STANDARD','ACCELERATED'): _bad()
            _text(p['name'],100)
            start, end = parse_moment(p['periodStartDt']), parse_moment(p['periodEndDt'])
            if start.time() != time() or end.time() != time() or start > end: _bad()
        elif action == 'create_adgroup':
            keys = {'customerId','nccCampaignId','name','adgroupType','pcChannelId','mobileChannelId','bidAmt','dailyBudget','useDailyBudget','userLock','useExpSearch','aiAdsOptIn','systemBiddingType','adRollingType','pcNetworkBidWeight','mobileNetworkBidWeight','useCntsNetworkBidAmt','useCntsNetworkBidWeight','contentsNetworkBidAmt'}
            if (set(p) != keys or parent is None or parent['kind'] != 'campaign' or parent['settings'].get('campaignTp') != 'WEB_SITE'
                    or p['nccCampaignId'] != parent['id'] or p['customerId'] != cid or p['adgroupType'] != 'WEB_SITE'
                    or any(p[k] is not False for k in ('useExpSearch','aiAdsOptIn','useCntsNetworkBidAmt','useCntsNetworkBidWeight'))
                    or p['systemBiddingType'] != 'NONE' or p['adRollingType'] not in ('ROUND_ROBIN','PERFORMANCE')
                    or any(type(p[k]) is not int or p[k] != 100 for k in ('pcNetworkBidWeight','mobileNetworkBidWeight'))
                    or any(not IF.valid_id(p[k]) for k in ('pcChannelId','mobileChannelId'))): _bad()
            if set(fps)!={p['pcChannelId'],p['mobileChannelId']}:_bad()
            _text(p['name'],100)
            if not _number(p['contentsNetworkBidAmt'],70,100000,integer=True): _bad()
        elif action == 'create_keyword':
            if set(p) != {'keyword','bidAmt','useGroupBidAmt','userLock'} or p['useGroupBidAmt'] is not False or not _manual_group(parent): _bad()
            _text(p['keyword'],25)
        else:
            if set(p) != {'type','nccAdgroupId','ad'} or p['type'] != 'TEXT_45' or not _manual_group(parent) or p['nccAdgroupId'] != parent['id']: _bad()
            ad = p['ad']
            if not isinstance(ad,dict) or set(ad) != {'headline','description','pc','mobile'}: _bad()
            _creative(ad['headline'],1,15); _creative(ad['description'],20,45)
            for kind in ('pc','mobile'):
                if not isinstance(ad[kind],dict) or set(ad[kind]) != {'final'}: _bad()
                _url(ad[kind]['final'])
        if action != 'create_text_ad' and p.get('userLock') is not True: _bad()
        if action in ('create_campaign','create_adgroup') and (p['useDailyBudget'] is not True or not _number(p['dailyBudget'],70,10**9,integer=True) or p['dailyBudget']%10): _bad()
        if action != 'create_campaign' and parent['settings'].get('userLock') is not True: _bad()
        if action in ('create_adgroup','create_keyword') and not _number(p['bidAmt'],70,100000,integer=True): _bad()
    else:
        if target is None: _bad()
        if target['kind']!='campaign' and parent is None:_bad()
        if (target['kind']=='campaign' and target['settings'].get('campaignTp')!='WEB_SITE'
                or target['kind']=='adgroup' and target['settings'].get('adgroupType')!='WEB_SITE'
                or target['kind'] in ('keyword','ad') and parent['settings'].get('adgroupType')!='WEB_SITE'
                or target['kind']=='ad' and target['settings'].get('type')!='TEXT_45'):_bad('현재 실행은 WEB_SITE·TEXT_45 범위만 지원합니다')
        if target['kind'] == 'campaign' and parent is not None or target['kind'] != 'campaign' and (parent is None or parent['id'] != target['parent_id']): _bad()
        if action == 'update_bid':
            expected = {'bidAmt','useGroupBidAmt'} if target['kind'] == 'keyword' else {'bidAmt'}
            if target['kind'] not in ('adgroup','keyword') or set(p) != expected or not _number(p['bidAmt'],70,100000,integer=True): _bad()
            if not _manual_group(target if target['kind'] == 'adgroup' else parent) or target['kind'] == 'keyword' and (p['useGroupBidAmt'] is not False or target['settings'].get('useGroupBidAmt') is not False): _bad()
        elif action == 'update_daily_budget':
            if target['kind'] not in ('campaign','adgroup') or set(p) != {'dailyBudget','useDailyBudget'} or p['useDailyBudget'] is not True or target['settings'].get('useDailyBudget') is not True or not _number(p['dailyBudget'],70,10**9,integer=True) or p['dailyBudget']%10: _bad()
        elif set(p) != {'userLock'} or type(p['userLock']) is not bool or type(target['settings'].get('userLock')) is not bool: _bad()
    return deepcopy(value)


def public_manifest(command):
    c = validate_command(command)
    return dict(command_id=c['command_id'], approval_ref=c['approval_ref'], action=c['action'], target_key=c['target_key'],
        config_epoch=c['config_epoch'], plan_version=c['plan_version'], evaluation_key=c['evaluation_key'], created_at=c['created_at'],
        summary='별도 승인한 단일 변경' if c['approval_ref']['kind'] == 'one_shot' else '승인한 위임 범위의 주기 변경')


def target_identity(command, *, target=None):
    c = validate_command(command)
    t = target if target is not None else c['target']
    return fingerprint(['execution-target-v1', c['scope'], t['kind'], t['id']]) if t is not None else fingerprint(['unresolved-create', c['scope'], c['command_id']])


def _activation_descendants(target,arms):
    allarms=list(arms)
    groups=[a for a in allarms if a['kind']=='adgroup' and a['campaign_id']==target['id']] if target['kind']=='campaign' else [target]
    if len(groups)!=1 or not _manual_group(groups[0]):_bad('활성화는 수동 입찰 광고그룹 1개를 전수 확인한 범위만 지원합니다')
    g=groups[0]
    if type(g['settings'].get('userLock')) is not bool:_bad('그룹의 현재 잠금 상태를 확인해 주세요')
    children=[a for a in allarms if a['kind'] in ('keyword','ad') and a['parent_id']==g['id']]
    if any(sum(a['kind']==k for a in children)>50 for k in ('keyword','ad')):_bad('활성화 자식 목록은 종류별 50개 이하 전수 확인이 필요합니다')
    for a in children:
        s=a['settings']
        if type(s.get('userLock')) is not bool:_bad('자식의 현재 잠금 상태를 확인해 주세요')
        if a['kind']=='keyword' and (type(s.get('useGroupBidAmt')) is not bool or s['useGroupBidAmt'] is False and not _number(s.get('bidAmt'),70,100000,integer=True)):_bad('키워드의 실제 입찰 상속·금액을 확인해 주세요')
        if a['kind']=='ad' and (s.get('type')!='TEXT_45' or s.get('adAttr') not in (None,{})):_bad('활성화는 TEXT_45의 확인된 입찰 범위만 지원합니다')
    result=([g] if target['kind']=='campaign' else [])+children
    if len({(a['kind'],a['id']) for a in result})!=len(result):_bad()
    return sorted(deepcopy(result),key=lambda a:(a['kind'],a['id']))


def _randomized_snapshot(command):
    """Only two exact TEXT_45 ads and their complete manual parent scope."""
    target, snapshot = command['target'], command['activation_snapshot']
    if not isinstance(target, dict) or target.get('kind') != 'ad': _bad()
    groups = [a for a in snapshot if a['kind'] == 'adgroup']
    campaigns = [a for a in snapshot if a['kind'] == 'campaign']
    ads = [a for a in snapshot if a['kind'] == 'ad']
    keywords = [a for a in snapshot if a['kind'] == 'keyword']
    if (len(groups) != 1 or len(campaigns) != 1 or len(ads) != 2 or not 1 <= len(keywords) <= 50
            or len(snapshot) != 4+len(keywords) or not _manual_group(groups[0])
            or groups[0] != command['parent'] or campaigns[0]['id'] != groups[0]['campaign_id']
            or target not in ads or len({(a['kind'], a['id']) for a in snapshot}) != len(snapshot)
            or snapshot != sorted(snapshot, key=lambda a:(a['kind'], a['id']))): _bad()
    for a in campaigns+groups:
        if a['settings'].get('userLock') is not False or a['settings'].get('status') != 'ELIGIBLE': _bad('실험 부모의 노출 상태를 확인해 주세요')
    for a in ads+keywords:
        if a['parent_id'] != groups[0]['id'] or a['campaign_id'] != campaigns[0]['id']: _bad()
        if a['kind'] == 'ad' and (a['settings'].get('type') != 'TEXT_45' or a['settings'].get('adAttr') not in (None, {})): _bad()
        if type(a['settings'].get('userLock')) is not bool: _bad()
    if command['payload'].get('userLock') is False:
        other = next(a for a in ads if a != target)
        if other['settings']['userLock'] is not True or other['settings'].get('status') != 'PAUSED': _bad('다른 소재의 중단 반영을 먼저 확인해야 합니다')
    return snapshot


def current_command(command,catalog,now):
    c=validate_command(command);now=parse_moment(now)
    if not isinstance(catalog,dict) or catalog.get('status')!='ready' or _scope({k:catalog['scope'].get(k) for k in SCOPE_FIELDS})!=c['scope'] or parse_moment(catalog['scope']['generation'])>now:_bad()
    for key in ('target','parent'):
        expected=c[key]
        if expected is not None and sum(a==expected for a in catalog['_arms'].values())!=1:_bad('승인한 대상·부모 설정이 바뀌었습니다')
    if c['action']=='set_user_lock' and c['payload']['userLock'] is False and c['target']['kind'] in ('campaign','adgroup'):
        if _activation_descendants(c['target'],catalog['_arms'].values())!=c['activation_snapshot']:_bad('활성화할 자식 설정·목록이 바뀌었습니다')
    return True


def _spend_for_limits(value, command, plan, doc, now):
    if not isinstance(value, dict) or set(value) != SPEND_FIELDS or value.get('status') != 'ok' or value.get('customer_id') != command['scope']['customer_id']: return None
    try:
        age = doc['stop']['source_max_age_minutes'] if doc else 30
        if not timedelta(0) <= now-parse_moment(value['source_at']) <= timedelta(minutes=age) or value['day'] != now.date().isoformat() or value['month'] != now.strftime('%Y-%m') or value['risk_period_start']!=plan['period_start']: return None
        if any(not _number(value[k]) for k in ('daily_spend','monthly_spend','risk_spend')): return None
        # Platform salesAmt is VAT inclusive. A confirmed unit is supplied by the
        # separately approved operator evidence, never inferred from an amount.
        # Official FAQ747 establishes the fixed 10% VAT protocol. Unknown stays hold.
        if value['budget_unit'] not in ('vat_included_krw','vat_excluded_krw') or value['bid_cap_unit'] != 'vat_excluded_krw': return None
        if not isinstance(value['campaigns'], list) or not value['campaigns'] or len(value['campaigns']) > 10000: return None
        ids = set()
        for row in value['campaigns']:
            if not isinstance(row,dict) or set(row) != {'id','daily_budget','use_daily_budget','shared_budget'} or not IF.valid_id(row['id'],'campaign') or row['id'] in ids: return None
            ids.add(row['id'])
            if row['use_daily_budget'] is not True or row['shared_budget'] is not False or not _number(row['daily_budget'],70,10**9,integer=True): return None
        factor=_budget_factor(value)
        if sum(Decimal(r['daily_budget'])*factor for r in value['campaigns']) > Decimal(str(plan['daily_spend_cap'])): return None
        return value
    except (ValueError, TypeError, OverflowError): return None


def _budget_factor(spend):
    return Decimal('1.1') if spend['budget_unit']=='vat_excluded_krw' else Decimal(1)


def assess_limits(command, binding, ledger, account_spend, now, *, exclude_command_id=None):
    c, now = validate_command(command), parse_moment(now)
    if not isinstance(binding, dict) or not isinstance(binding.get('plan'), dict): _bad()
    doc = None
    if binding.get('document') is not None:
        b = validate_binding(binding); plan = b['plan']; doc = b['document']
        if c['scope'] != b['scope'] or c['plan_version'] != b['plan_version']: _bad()
        if c['approval_ref']['kind'] != 'mandate': _bad()
    else:
        plan = _plan({'state':'approved','version':c['plan_version'],'plan':binding['plan']})
        if c['approval_ref']['kind'] not in ('one_shot','randomized_experiment','randomized_experiment_stop'): _bad()
        if c['approval_ref']['kind']=='randomized_experiment': _randomized_snapshot(c)
    reasons = []
    try: history = _ledger(ledger, c['scope']['customer_id'], now, exclude_command_id=exclude_command_id)
    except ExecutionInvalid: return dict(allowed=False, reason_codes=['LEDGER_UNAVAILABLE'])
    if any(row['status'] in _PENDING for row, _ in history): reasons.append('ACCOUNT_OUTCOME_PENDING')
    is_pause = c['action'] == 'set_user_lock' and c['payload']['userLock'] is True
    if not is_pause and not _day(plan['period_start']) <= now.date() <= _day(plan['period_end']): reasons.append('PLAN_PERIOD_ENDED')
    if doc and not is_pause and not _day(doc['operation_start']) <= now.date() <= _day(doc['operation_end']): reasons.append('OPERATION_ENDED')
    identity = target_identity(c)
    own = [(r,t) for r,t in history if r['target_identity'] == identity and r['status'] != 'rejected']
    dayrows = [(r,t) for r,t in history if now-t < timedelta(hours=24) and r['status'] != 'rejected']
    ownday = [(r,t) for r,t in own if now-t < timedelta(hours=24)]
    if doc:
        # 명시 위임한 중단은 확정된 직전 입찰의 쿨다운·횟수 때문에 늦추지 않는다.
        # unknown/dispatched의 계정 잠금은 위에서 그대로 유지한다.
        if not is_pause:
            if len(dayrows) >= doc['max_changes_per_account_24h']: reasons.append('ACCOUNT_CHANGE_COUNT')
            if len(ownday) >= doc['max_changes_per_target_24h']: reasons.append('TARGET_CHANGE_COUNT')
            if own and now-max(t for _,t in own) < timedelta(minutes=doc['cooldown_minutes']): reasons.append('COOLDOWN')
        if c['action'] == 'update_bid' and 'bid' not in doc['allowed_actions'] or is_pause and 'pause' not in doc['allowed_actions']: reasons.append('ACTION_NOT_DELEGATED')
        if c['action'] not in ('update_bid','set_user_lock') or c['action'] == 'set_user_lock' and not is_pause: reasons.append('ACTION_NOT_DELEGATED')
    s = c['target']['settings'] if c['target'] else {}
    upward = False
    if c['action'] == 'update_bid':
        before, after = s.get('bidAmt'), c['payload']['bidAmt']
        if not _number(before,70,100000,integer=True): reasons.append('BID_UNAVAILABLE')
        else:
            upward = after > before
            if after == before: reasons.append('NO_CHANGE')
            if after > plan['absolute_bid_cap']: reasons.append('ABSOLUTE_BID_CAP')
            if doc and after < doc['minimum_bid']: reasons.append('MINIMUM_BID')
            group = c['target'] if c['target']['kind'] == 'adgroup' else c['parent']
            if not _manual_group(group): reasons.append('NATIVE_OR_WEIGHT_UNVERIFIED')
            direction = 'increase' if upward else 'decrease'
            single = abs(Decimal(after)-Decimal(before))/Decimal(before)*100
            if single > Decimal(str(plan['change_limits']['single_'+direction+'_percent'])): reasons.append('SINGLE_CHANGE_LIMIT')
            if doc and single > Decimal(str(doc['bid_'+direction+'_percent'])): reasons.append('MANDATE_STEP_LIMIT')
            # Gross directional movement anchored at the first pre-change bid in the window.
            changes = sorted([(r,t) for r,t in ownday if r['action'] == 'update_bid'], key=lambda row:row[1])
            if any(not _number(r['before'],70,100000,integer=True) or not _number(r['after'],70,100000,integer=True) for r,t in changes):
                reasons.append('BID_LEDGER_UNAVAILABLE')
            else:
                anchor = changes[0][0]['before'] if changes else before
                gross = sum((max(0,r['after']-r['before']) if upward else max(0,r['before']-r['after'])) for r,t in changes)
                gross += abs(after-before)
                if Decimal(gross)/Decimal(anchor)*100 > Decimal(str(plan['change_limits']['rolling_day_'+direction+'_percent'])): reasons.append('DAILY_DIRECTION_LIMIT')
            if upward and c['approval_ref']['kind'] == 'mandate':
                week = sorted([(r,t) for r,t in own if now-t < timedelta(days=7) and r['action'] == 'update_bid'],key=lambda row:row[1])
                if any(not _number(r['before'],70,100000,integer=True) or not _number(r['after'],70,100000,integer=True) for r,t in week): reasons.append('BID_LEDGER_UNAVAILABLE')
                else:
                    anchor = week[0][0]['before'] if week else before
                    gross = sum(max(0,r['after']-r['before']) for r,t in week)+max(0,after-before)
                    if Decimal(gross)/Decimal(anchor)*100 > Decimal(str(plan['change_limits']['weekly_increase_requires_approval_percent'])): reasons.append('WEEKLY_REAPPROVAL')
    elif c['action'] == 'update_daily_budget':
        before, after = s.get('dailyBudget'), c['payload']['dailyBudget']
        if not _number(before,70,10**9,integer=True): reasons.append('BUDGET_UNAVAILABLE')
        else:
            upward = after > before
            if after == before: reasons.append('NO_CHANGE')
            direction = 'increase' if upward else 'decrease'
            if Decimal(abs(after-before))/Decimal(before)*100 > Decimal(str(plan['change_limits']['single_'+direction+'_percent'])): reasons.append('SINGLE_CHANGE_LIMIT')
            if after > plan['daily_spend_cap']: reasons.append('DAILY_BUDGET_CAP')
            changes=sorted([(r,t) for r,t in ownday if r['action']=='update_daily_budget'],key=lambda row:row[1])
            if any(not _number(r['before'],70,10**9,integer=True) or not _number(r['after'],70,10**9,integer=True) for r,t in changes):reasons.append('BUDGET_LEDGER_UNAVAILABLE')
            else:
                anchor=changes[0][0]['before'] if changes else before
                gross=sum(max(0,r['after']-r['before']) if upward else max(0,r['before']-r['after']) for r,t in changes)+abs(after-before)
                if Decimal(gross)/Decimal(anchor)*100>Decimal(str(plan['change_limits']['rolling_day_'+direction+'_percent'])):reasons.append('DAILY_DIRECTION_LIMIT')
    elif c['action'] == 'set_user_lock':
        upward = c['payload']['userLock'] is False
        if s.get('userLock') == c['payload']['userLock']: reasons.append('NO_CHANGE')
        if upward:
            group=c['target'] if c['target']['kind']=='adgroup' else c['parent']
            groups=[a for a in c['activation_snapshot'] if a['kind']=='adgroup'] if c['target']['kind']=='campaign' else [group]
            if len(groups)!=1 or not _manual_group(groups[0]):reasons.append('NATIVE_OR_WEIGHT_UNVERIFIED')
            else:
                g=groups[0]
                bids=[g['settings'].get('bidAmt')]+[a['settings'].get('bidAmt') for a in c['activation_snapshot'] if a['kind']=='keyword' and a['settings'].get('useGroupBidAmt') is False]
                if c['target']['kind']=='keyword' and type(s.get('useGroupBidAmt')) is not bool:reasons.append('INHERITED_BID_UNSUPPORTED')
                if c['target']['kind']=='keyword' and s.get('useGroupBidAmt') is False:bids.append(s.get('bidAmt'))
                if any(not _number(v,70,100000,integer=True) or v>plan['absolute_bid_cap'] for v in bids):reasons.append('ABSOLUTE_BID_CAP')
    else:
        # Creation is locked and does not authorize activation or native defaults.
        if c['payload'].get('bidAmt',0) > plan['absolute_bid_cap']: reasons.append('ABSOLUTE_BID_CAP')
        if c['payload'].get('dailyBudget',0) > plan['daily_spend_cap']: reasons.append('DAILY_BUDGET_CAP')
    if upward:
        spend = _spend_for_limits(account_spend,c,plan,doc,now)
        if spend is None: reasons.append('ACCOUNT_SPEND_OR_UNIT_UNVERIFIED')
        elif spend['daily_spend'] >= plan['daily_spend_cap'] or spend['monthly_spend'] >= plan['monthly_spend_cap'] or spend['risk_spend'] >= (doc['stop']['spend_cap'] if doc else plan['loss_cap']): reasons.append('ACCOUNT_SPEND_AT_CAP')
        elif c['action']=='update_daily_budget':
            factor=_budget_factor(spend);after=c['payload']['dailyBudget']
            if Decimal(after)*factor>Decimal(str(plan['daily_spend_cap'])):reasons.append('DAILY_BUDGET_CAP')
            if c['target']['kind']=='campaign':
                rows=[r for r in spend['campaigns'] if r['id']==c['target']['id']]
                if len(rows)!=1 or rows[0]['daily_budget']!=c['target']['settings'].get('dailyBudget'):reasons.append('CAPACITY_SOURCE_CHANGED')
                elif sum(Decimal(after if r['id']==c['target']['id'] else r['daily_budget'])*factor for r in spend['campaigns'])>Decimal(str(plan['daily_spend_cap'])):reasons.append('ACCOUNT_DAILY_CAPACITY')
            elif (c['parent']['settings'].get('useDailyBudget') is not True or not _number(c['parent']['settings'].get('dailyBudget'),70,10**9,integer=True)
                    or after>c['parent']['settings']['dailyBudget']):reasons.append('PARENT_BUDGET_CAPACITY')
    return dict(allowed=not reasons, reason_codes=list(dict.fromkeys(reasons)))


def _row_arm(row, kind, cid, parent=None, campaign=None):
    if not isinstance(row,dict): _bad()
    try:
        settings = IF.sanitize_record(kind,row,cid,parent)
        return X.normalize_arm(dict(kind=kind,id=settings[IF.IDS[kind]],parent_id=parent,
            campaign_id=settings[IF.IDS[kind]] if kind == 'campaign' else (parent if kind == 'adgroup' else campaign),settings=settings),cid)
    except (ValueError, TypeError, KeyError): _bad('재조회한 대상의 소유·부모를 확인하지 못했습니다')


def verify_preflight(command, preflight):
    c = validate_command(command)
    if c['approval_ref']['kind']=='randomized_experiment_stop':
        if not isinstance(preflight,dict) or set(preflight)!={'target','parent','channels'} or preflight['channels']!=[]:_bad()
        group=_row_arm(preflight['parent'],'adgroup',c['scope']['customer_id'],c['parent']['parent_id'],c['parent']['campaign_id'])
        ad=_row_arm(preflight['target'],'ad',c['scope']['customer_id'],group['id'],group['campaign_id'])
        if group['id']!=c['parent']['id'] or group['parent_id']!=c['parent']['parent_id'] or ad['id']!=c['target']['id'] or type(ad['settings'].get('userLock'))is not bool:_bad('승인된 중단 대상의 현재 계정·부모·ID를 확인해 주세요')
        return True
    formal = c['approval_ref']['kind'] == 'randomized_experiment'
    if formal:
        if not isinstance(preflight, dict) or set(preflight) != {'target','parent','channels','randomized_scope'} or preflight['channels'] != []: _bad()
        proof = preflight['randomized_scope']
        if not isinstance(proof, dict) or set(proof) != {'campaign','adgroup','ads','keywords'} or not isinstance(proof['ads'],list) or len(proof['ads']) != 2 or not isinstance(proof['keywords'],list) or not 1 <= len(proof['keywords']) <= 50: _bad()
        group, campaign = c['parent'], next(a for a in c['activation_snapshot'] if a['kind']=='campaign')
        rows = [_row_arm(proof['campaign'],'campaign',c['scope']['customer_id']),
            _row_arm(proof['adgroup'],'adgroup',c['scope']['customer_id'],campaign['id'])]
        for kind, key in (('ad','ads'),('keyword','keywords')):
            rows += [_row_arm(r,kind,c['scope']['customer_id'],group['id'],campaign['id']) for r in proof[key]]
        if sorted(rows,key=lambda a:(a['kind'],a['id'])) != _randomized_snapshot(c): _bad('실험 그룹·소재·키워드 전수 원천이 변경되었습니다')
        if preflight['parent'] != proof['adgroup'] or preflight['target'] not in proof['ads']: _bad()
        if _row_arm(preflight['target'],'ad',c['scope']['customer_id'],group['id'],campaign['id']) != c['target']: _bad()
        return True
    if not isinstance(preflight,dict) or set(preflight) not in ({'target','parent','channels'},{'target','parent','channels','activation'}) or not isinstance(preflight['channels'],list): _bad()
    for key in ('target','parent'):
        expected = c[key]
        if expected is None:
            if preflight[key] is not None: _bad()
        elif _row_arm(preflight[key],expected['kind'],c['scope']['customer_id'],expected['parent_id'],expected['campaign_id']) != expected:
            _bad('송신 전 설정이 승인된 설정과 달라졌습니다')
    if c['action'].startswith('create_') and c['parent'] and preflight['parent'].get('userLock') is not True: _bad('부모 잠금을 먼저 확인해 주세요')
    if c['action'] == 'create_adgroup':
        for key in ('pcChannelId','mobileChannelId'):
            rows = [r for r in preflight['channels'] if isinstance(r,dict) and r.get('nccBusinessChannelId') == c['payload'][key]]
            if len(rows) != 1 or rows[0].get('customerId') != c['scope']['customer_id'] or rows[0].get('channelTp') != 'SITE' or rows[0].get('status') != 'ELIGIBLE' or fingerprint(_url(rows[0].get('channelKey')))!=c['channel_fingerprints'][c['payload'][key]]: _bad('현재 SITE 채널을 다시 확인해 주세요')
    activation=c['action']=='set_user_lock' and c['payload']['userLock'] is False and c['target']['kind'] in ('campaign','adgroup')
    proof=preflight.get('activation',{})
    if activation:
        if not isinstance(proof,dict) or set(proof)!={'adgroups','keywords','ads'}:_bad('활성화 자식의 전수 조회가 필요합니다')
        groups=proof['adgroups'] if c['target']['kind']=='campaign' else [preflight['target']]
        if not isinstance(groups,list) or len(groups)!=1:_bad()
        group=_row_arm(groups[0],'adgroup',c['scope']['customer_id'],c['target']['id'] if c['target']['kind']=='campaign' else c['target']['parent_id'])
        rows=[group] if c['target']['kind']=='campaign' else []
        for kind,key in (('keyword','keywords'),('ad','ads')):
            if not isinstance(proof[key],list) or len(proof[key])>50:_bad()
            rows += [_row_arm(r,kind,c['scope']['customer_id'],group['id'],group['campaign_id']) for r in proof[key]]
        if _activation_descendants(c['target'],rows)!=c['activation_snapshot']:_bad('활성화 자식 설정·목록이 승인과 다릅니다')
    elif proof:_bad()
    return True


def verify_readback(command, row):
    c = validate_command(command)
    if row is None: return _result('unknown',['READBACK_UNAVAILABLE'],target=None)
    creation = c['action'].startswith('create_')
    kind = {'create_campaign':'campaign','create_adgroup':'adgroup','create_keyword':'keyword','create_text_ad':'ad'}.get(c['action'],c['target']['kind'] if c['target'] else None)
    parent = c['parent']['id'] if c['parent'] else None
    campaign = c['parent']['campaign_id'] if c['parent'] else None
    try:
        actual = _row_arm(row,kind,c['scope']['customer_id'],parent,campaign)
        if not creation and actual['id'] != c['target']['id']: _bad()
        desired = c['payload']
        if creation:
            checks = {k:v for k,v in desired.items() if k not in ('pcChannelId','mobileChannelId','trackingMode','ad')}
            if any(row.get(k) != v for k,v in checks.items()): _bad()
            if c['action'] == 'create_adgroup' and any(row.get(k) != desired[k] for k in ('pcChannelId','mobileChannelId')): _bad()
            if c['action'] == 'create_text_ad' and row.get('ad') != desired['ad']: _bad()
        else:
            if any(row.get(k) != v or type(row.get(k)) is not type(v) for k,v in desired.items()): _bad()
            if c['approval_ref']['kind'] in ('randomized_experiment','randomized_experiment_stop') and row.get('status') != ('PAUSED' if desired['userLock'] else 'ELIGIBLE'):
                _bad('실험 소재의 실제 노출 상태 반영을 확인하지 못했습니다')
            # Preserve every approved current setting except mutable API timestamps/status.
            ignorable = {'editTm','regTm','status','statusReason','inspectStatus','budgetLock','sharedBudgetLock'}
            for k,v in c['target']['settings'].items():
                if c['approval_ref']['kind']!='randomized_experiment_stop' and k not in desired and k not in ignorable and actual['settings'].get(k) != v: _bad()
        return _result('confirmed',[],target=actual)
    except (ExecutionInvalid,ValueError,TypeError,KeyError):
        return _result('mismatch',['READBACK_MISMATCH'],target=None)
