"""Bounded current setup facts for future plans; no IO, execution or authority.

The caller must obtain setup_observation under current account/ERP/actor scope.
Business labels and the full source fingerprint remain server-only. Selection is
explicit and deterministic before the provider; it never truncates wire facts.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import math
import re

from . import setup_checks as SETUP

MAX_CONTEXT_BYTES = 2200
MAX_EXTENSION_BYTES = 3200  # design budget, provider's existing 32768-byte cap remains absolute
MAX_ROWS = 8
COLUMNS = ('index', 'kind', 'campaign', 'group', 'status', 'budget_mode', 'shared',
           'daily_budget', 'bid', 'impressions', 'clicks', 'spend', 'conversions',
           'conversion_value', 'ctr', 'cpc', 'metric_state')
METRIC_FIELDS = ('impressions', 'clicks', 'spend', 'conversions', 'conversion_value', 'ctr', 'cpc')
SUMMARY_FIELDS = ('source_status', 'period_relation', 'coverage', 'checks', 'campaign_count', 'adgroup_count',
                  'keyword_count', 'ad_count', 'attention_count', 'unknown_count')
ENTITY_FIELDS = ('target', 'status', 'targeting', 'daily_budget', 'bid') + METRIC_FIELDS
KINDS = ('campaign', 'adgroup', 'keyword', 'ad')
CHECKS = ('attention', 'unknown', 'verified', 'not_applicable')
TARGETS = ('SD', 'RL', 'AG', 'negative_keywords')
CHECK_KEYS = ('structure', 'inspection', 'suspension', 'delivery', 'campaign_budget', 'campaign_period',
              'time_targeting', 'region_targeting', 'age_targeting', 'negative_keywords', 'creative_copy',
              'goal', 'budget_plan', 'setup_completeness')
_STATE_CODES = {'attention': 'a', 'unknown': 'u', 'verified': 'v', 'not_applicable': 'n'}
_FIELDS = {'version', 'state', 'reason', 'next_plan_only', 'historical_cause_allowed', 'period_relation',
           'source', 'counts', 'checks', 'check_states', 'targets', 'selected_targets', 'coverage', 'columns', 'rows'}
_OBS_FIELDS = {'version', 'customer_id', 'possibility_id', 'stage_revision', 'status', 'checked_at',
               'error_code', 'complete', 'stale', 'generation', 'period_start', 'period_end',
               'campaigns', 'entities', 'targets', 'performance', 'history'}
_LABELS = {'campaign': '캠페인', 'adgroup': '광고그룹', 'keyword': '키워드', 'ad': '소재'}
_STATUS = {'eligible': '노출 가능 상태', 'paused': '중지 상태', 'deleted': '삭제 상태', 'unknown': '상태 미확인'}


class EvidenceInvalid(ValueError):
    pass


class EvidenceUnavailable(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def _bad():
    raise EvidenceInvalid('SETUP_EVIDENCE_INVALID')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10**15


def _integer(value, maximum=10000):
    return type(value) is int and 0 <= value <= maximum


def _day(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError):
        return False


def _moment(value):
    try:
        at = datetime.fromisoformat(value) if isinstance(value, str) else None
        return at if at is not None and at.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _empty(reason):
    return dict(version=1, state='unavailable', reason=reason, next_plan_only=True,
        historical_cause_allowed=False, period_relation='unknown',
        source=dict(checked_at=None, period_start=None, period_end=None),
        counts=dict.fromkeys(KINDS), checks=dict.fromkeys(CHECKS),
        check_states=dict(columns=list(CHECK_KEYS), row=['u']*14), targets={},
        selected_targets=dict(values_included=False, groups=[]),
        coverage=dict(total=None, selected=0, truncated=False), columns=list(COLUMNS), rows=[])


def normalize_context(value):
    try:
        if (not isinstance(value, dict) or set(value) != _FIELDS or type(value['version']) is not int
                or value['version'] != 1 or value['next_plan_only'] is not True
                or value['historical_cause_allowed'] is not False
                or value['state'] not in ('current', 'unavailable')
                or value['reason'] not in ('ok', 'missing', 'stale', 'incomplete')
                or value['period_relation'] not in ('same', 'different', 'unknown')
                or value['columns'] != list(COLUMNS) or not isinstance(value['rows'], list)
                or len(value['rows']) > MAX_ROWS or len(canonical(value).encode()) > MAX_CONTEXT_BYTES):
            _bad()
        source, counts, checks, coverage = (value[k] for k in ('source', 'counts', 'checks', 'coverage'))
        if (not isinstance(source, dict) or set(source) != {'checked_at', 'period_start', 'period_end'}
                or not isinstance(counts, dict) or set(counts) != set(KINDS)
                or not isinstance(checks, dict) or set(checks) != set(CHECKS)
                or not isinstance(coverage, dict) or set(coverage) != {'total', 'selected', 'truncated'}
                or type(coverage['truncated']) is not bool or coverage['selected'] != len(value['rows'])
                or not _integer(coverage['selected'], MAX_ROWS)):
            _bad()
        if value['state'] == 'unavailable':
            if value != _empty(value['reason']) or value['reason'] == 'ok':
                _bad()
            return deepcopy(value)
        if (value['reason'] != 'ok' or value['period_relation'] == 'unknown' or _moment(source['checked_at']) is None
                or not all(_day(source[k]) for k in ('period_start', 'period_end'))
                or source['period_start'] > source['period_end'] or any(not _integer(v) for v in counts.values())
                or any(not _integer(v, 14) for v in checks.values()) or sum(checks.values()) != 14
                or coverage['total'] != sum(counts.values()) or coverage['selected'] > coverage['total']
                or coverage['truncated'] != (coverage['selected'] < coverage['total'])
                or not isinstance(value['targets'], dict) or set(value['targets']) != set(TARGETS)):
            _bad()
        state_table = value['check_states']
        if (not isinstance(state_table, dict) or set(state_table) != {'columns', 'row'} or state_table['columns'] != list(CHECK_KEYS)
                or not isinstance(state_table['row'], list) or len(state_table['row']) != 14
                or any(code not in _STATE_CODES.values() for code in state_table['row'])
                or any(state_table['row'].count(code) != checks[key] for key, code in _STATE_CODES.items())):
            _bad()
        for record in value['targets'].values():
            if (not isinstance(record, list) or len(record) != 4 or any(not _integer(v) for v in record)
                    or sum(record[:3]) != counts['adgroup'] or record[3] > record[0]):
                _bad()
        selected = value['selected_targets']
        if (not isinstance(selected, dict) or set(selected) != {'values_included', 'groups'}
                or selected['values_included'] is not False or not isinstance(selected['groups'], list)
                or len(selected['groups']) > 2):
            _bad()
        expected_groups = sorted({row[3] for row in value['rows'] if isinstance(row, list) and len(row) == len(COLUMNS)
                                  and row[1] != 'campaign' and row[3] is not None})
        if [r[0] for r in selected['groups'] if isinstance(r, list) and len(r) == 5] != expected_groups:
            _bad()
        for record in selected['groups']:
            if (not isinstance(record, list) or len(record) != 5 or not _integer(record[0]) or record[0] < 1
                    or any(not isinstance(v, list) or len(v) != 2 or v[0] not in ('o', 's', 'u')
                           or (v[0] == 'u' and v[1] is not None) or (v[0] != 'u' and not _integer(v[1]))
                           or (v[0] == 's' and v[1] != 0) for v in record[1:])):
                _bad()
        for index, values in enumerate(value['rows'], 1):
            if not isinstance(values, list) or len(values) != len(COLUMNS):
                _bad()
            row = dict(zip(COLUMNS, values))
            if (type(row['index']) is not int or row['index'] != index or row['kind'] not in KINDS
                    or row['status'] not in _STATUS or row['budget_mode'] not in ('finite', 'unlimited', 'unknown')
                    or row['shared'] not in ('none', 'shared', 'unknown')
                    or not _integer(row['campaign']) or not 1 <= row['campaign'] <= counts['campaign']
                    or (row['kind'] == 'campaign' and row['group'] is not None)
                    or (row['kind'] != 'campaign' and (not _integer(row['group']) or not 1 <= row['group'] <= counts['adgroup']))
                    or row['metric_state'] not in ('ready', 'basic_only', 'other_period', 'unavailable')
                    or any(row[k] is not None and not _number(row[k]) for k in ('daily_budget', 'bid') + METRIC_FIELDS)
                    or any(row[k] is not None and type(row[k]) is not int for k in ('impressions', 'clicks'))
                    or (row['daily_budget'] is not None and row['budget_mode'] != 'finite')):
                _bad()
            if (value['period_relation'] != 'same' or row['metric_state'] in ('other_period', 'unavailable')) and any(
                    row[k] is not None for k in METRIC_FIELDS):
                _bad()
            if ((row['metric_state'] == 'basic_only' and any(row[k] is not None for k in ('conversions', 'conversion_value')))
                    or (row['metric_state'] in ('ready', 'basic_only') and any(row[k] is None for k in ('impressions', 'clicks', 'spend')))
                    or (row['metric_state'] == 'ready' and any(row[k] is None for k in ('conversions', 'conversion_value')))
                    or (value['period_relation'] == 'same' and row['metric_state'] == 'other_period')
                    or (value['period_relation'] == 'different' and row['metric_state'] != 'other_period')):
                _bad()
        return deepcopy(value)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as error:
        if isinstance(error, EvidenceInvalid):
            raise
        _bad()


def _label(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 80 or re.search(
            r'[<>\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]|https?://|www\.', value, re.I)
            or any(0xd800 <= ord(c) <= 0xdfff for c in value)):
        return None
    return value.strip()


def normalize_labels(labels, context):
    context = normalize_context(context)
    if labels is None:
        return {}
    if (not isinstance(labels, dict) or not set(labels) <= {str(row[0]) for row in context['rows']}
            or any(not isinstance(v, str) or len(v) > 200 or not v.strip() or re.search(
                r'[<>\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]|https?://|www\.', v, re.I)
                or any(0xd800 <= ord(c) <= 0xdfff for c in v) for v in labels.values())):
        _bad()
    return deepcopy(labels)


def _metrics(raw, report, relation, now, checked):
    out = dict.fromkeys(METRIC_FIELDS)
    if relation != 'same':
        return out, 'other_period'
    item = SETUP._metric_detail(raw, now, checked)
    period = report['period']
    if (item is None or item['missing'] or item['period_start'] != period['start'] or item['period_end'] != period['end']
            or any(not _number(item['fields'].get(k)) for k in ('impCnt', 'clkCnt', 'salesAmt'))):
        return out, 'unavailable'
    fields = item['fields']
    out.update(impressions=fields['impCnt'], clicks=fields['clkCnt'], spend=fields['salesAmt'])
    for field, numerator, denominator, scale in (('ctr', 'clicks', 'impressions', 100), ('cpc', 'spend', 'clicks', 1)):
        if out[denominator] != 0:
            ratio = float(Decimal(str(out[numerator])) / Decimal(str(out[denominator])) * scale)
            out[field] = ratio if _number(ratio) else None
    conversion = item['complete'] and report.get('coverage', {}).get('conversion_complete') is True
    if conversion:
        out.update(conversions=fields['ccnt'], conversion_value=fields['convAmt'])
    return out, 'ready' if conversion else 'basic_only'


def _semantic_available(observation, report_payload, now):
    """Hash-only available source content, including incomplete observations.

    It grants no model visibility or currentness. Only refresh timestamps are
    omitted; malformed available containers/rows are not converted to empties.
    """
    if observation is None:
        return dict(campaigns=[], entities=[], target_settings={}, used_metrics=None)
    campaigns, entities, targets, performance = (observation[k] for k in ('campaigns','entities','targets','performance'))
    if (not isinstance(campaigns,list) or len(campaigns)>10000 or any(not isinstance(r,dict) for r in campaigns)
            or not isinstance(entities,dict) or len(entities)>10000 or not isinstance(targets,dict)
            or len(targets)>10000 or not isinstance(performance,dict) or len(performance)>10000):
        _bad()
    content=[]
    for key,row in entities.items():
        if (not isinstance(key,str) or not isinstance(row,dict)
                or set(row)!={'entity','id','parent_id','campaign_id','settings','checked_at'}
                or row['entity'] not in KINDS or not isinstance(row['id'],str)
                or key!=row['entity']+':'+row['id'] or not isinstance(row['settings'],dict)
                or not isinstance(row['campaign_id'],str)
                or (row['parent_id'] is not None and not isinstance(row['parent_id'],str))
                or _moment(row['checked_at']) is None or _moment(row['checked_at']) > now):
            _bad()
        content.append({k:row[k] for k in ('entity','id','parent_id','campaign_id','settings')})
    target_content={}
    for group,values in targets.items():
        if not isinstance(group,str) or 'adgroup:'+group not in entities or not isinstance(values,dict) or set(values)-set(TARGETS):
            _bad()
        target_content[group]={}
        for kind,row in values.items():
            if (not isinstance(row,dict) or set(row)!={'state','records','checked_at'}
                    or row['state'] not in ('observed','unsupported') or _moment(row['checked_at']) is None or _moment(row['checked_at']) > now
                    or not isinstance(row['records'],list) or len(row['records'])>10000
                    or any(not isinstance(r,dict) for r in row['records'])
                    or (row['state']=='unsupported' and row['records'])):
                _bad()
            target_content[group][kind]={k:row[k] for k in ('state','records')}
    metric_content={}
    report_period=report_payload.get('period',{})
    same=(all(_day(observation.get(k)) for k in ('period_start','period_end')) and
          (observation['period_start'],observation['period_end'])==(report_period.get('start'),report_period.get('end')))
    for key,row in performance.items():
        if (key not in entities or not isinstance(row,dict)
                or set(row)!={'period_start','period_end','checked_at','source_at','fields','complete','missing'}
                or not all(_day(row[k]) for k in ('period_start','period_end')) or row['period_start']>row['period_end']
                or _moment(row['checked_at']) is None or _moment(row['checked_at']) > now
                or (row['source_at'] is not None and (_moment(row['source_at']) is None or _moment(row['source_at']) > _moment(row['checked_at'])))
                or type(row['complete']) is not bool or type(row['missing']) is not bool
                or not isinstance(row['fields'],dict) or set(row['fields'])-{'impCnt','clkCnt','salesAmt','ccnt','convAmt'}
                or any(value is not None and not _number(value) for value in row['fields'].values())):
            _bad()
        if same and (row['period_start'],row['period_end'])==(observation['period_start'],observation['period_end']):
            metric_content[key]={k:row[k] for k in ('period_start','period_end','fields','complete','missing')}
    return dict(campaigns=campaigns,entities=sorted(content,key=canonical),target_settings=target_content,
                used_metrics=metric_content if same else None)


def _model_source(observation, report_payload, now):
    """Current validated source only; caller must bind PID/account/actor first."""
    if not isinstance(now, datetime) or now.utcoffset() is None or not isinstance(report_payload, dict):
        _bad()
    if observation is None:
        context, labels = _empty('missing'), {}
    else:
        if (not isinstance(observation, dict) or set(observation) != _OBS_FIELDS
                or type(observation['complete']) is not bool or type(observation['stale']) is not bool
                or (observation['checked_at'] is not None and (_moment(observation['checked_at']) is None
                    or _moment(observation['checked_at']) > now))):
            _bad()
        expected = report_payload.get('_expected_customers')
        if (not isinstance(expected, list) or len(expected) != 1 or type(expected[0]) not in (int, str)
                or str(expected[0]) != str(observation['customer_id']) or type(observation['customer_id']) is not int
                or observation['customer_id'] <= 0):
            _bad()
        if observation['stale'] is True:
            context, labels = _empty('stale'), {}
        elif observation['complete'] is not True or observation['status'] != 'ok':
            context, labels = _empty('incomplete'), {}
        else:
            checked = _moment(observation['checked_at'])
            if checked is None or checked > now:
                _bad()
            projected = SETUP.project_setup(now=now, observation=observation)
            if projected['source']['observation']['usable'] is not True:
                _bad()
            entities = observation['entities']
            counts = {k: sum(row['entity'] == k for row in entities.values()) for k in KINDS}
            period = report_payload.get('period', {})
            if not (all(_day(period.get(k)) for k in ('start', 'end')) and
                    all(_day(observation[k]) for k in ('period_start', 'period_end'))):
                _bad()
            relation = 'same' if (period['start'], period['end']) == (observation['period_start'], observation['period_end']) else 'different'
            context = dict(version=1, state='current', reason='ok', next_plan_only=True,
                historical_cause_allowed=False, period_relation=relation,
                source={k: observation[k] for k in ('checked_at', 'period_start', 'period_end')},
                counts=counts, checks=projected['counts'], check_states=dict(columns=list(CHECK_KEYS),
                    row=[_STATE_CODES[next(item['state'] for item in projected['items'] if item['key'] == key)] for key in CHECK_KEYS]), targets={},
                selected_targets=dict(values_included=False, groups=[]),
                coverage=dict(total=len(entities), selected=0, truncated=bool(entities)), columns=list(COLUMNS), rows=[])
            groups = sorted((r for r in entities.values() if r['entity'] == 'adgroup'), key=lambda r: r['id'])
            all_targets = SETUP._target_details(observation, entities, projected['source']['observation'], now)
            for target in TARGETS:
                records = [r for (group_id, kind), r in all_targets.items() if kind == target]
                observed = sum(r['state'] == 'observed' for r in records)
                unsupported = sum(r['state'] == 'unsupported' for r in records)
                # Bounded UI target rows cannot prove omitted target states.
                context['targets'][target] = [observed, unsupported, len(groups)-len(records),
                    sum(r['state'] == 'observed' and r['record_total'] > 0 for r in records)]
            campaigns = sorted((r for r in entities.values() if r['entity'] == 'campaign'), key=lambda r: r['id'])
            camp_index = {r['id']: i for i, r in enumerate(campaigns, 1)}
            group_index = {r['id']: i for i, r in enumerate(groups, 1)}
            others = [r for r in entities.values() if r['entity'] != 'campaign']
            def rank(row):
                raw = row['settings']
                attention = raw.get('delFlag') is True or raw.get('userLock') is True or raw.get('status') == 'PAUSED'
                metrics, _ = _metrics(observation['performance'].get(row['entity']+':'+row['id']), report_payload, relation, now, checked)
                return (not attention, -(metrics['spend'] or 0), row['entity'], row['id'])
            details = sorted(others, key=rank)[:2]
            parent_ids = {row['campaign_id'] for row in details}
            parents = [row for row in campaigns if row['id'] in parent_ids]
            candidates = details + parents + [row for row in campaigns[:6] if row['id'] not in parent_ids]
            candidates = candidates[:MAX_ROWS]
            labels = {}
            for entity in candidates:
                raw, kind = entity['settings'], entity['entity']
                metrics, metric_state = _metrics(observation['performance'].get(kind+':'+entity['id']), report_payload, relation, now, checked)
                status = 'deleted' if raw.get('delFlag') is True else 'paused' if raw.get('userLock') is True or raw.get('status') == 'PAUSED' else 'eligible' if raw.get('status') == 'ELIGIBLE' else 'unknown'
                amount, bid = raw.get('dailyBudget'), raw.get('bidAmt')
                mode = 'finite' if raw.get('useDailyBudget') is True else 'unlimited' if raw.get('useDailyBudget') is False else 'unknown'
                record = dict(index=len(context['rows'])+1, kind=kind, campaign=camp_index.get(entity['campaign_id'] if kind != 'campaign' else entity['id']),
                    group=None if kind == 'campaign' else group_index.get(entity['parent_id'] if kind in ('ad', 'keyword') else entity['id']), status=status,
                    budget_mode=mode, shared=SETUP._shared_budget_state(raw), daily_budget=amount if mode == 'finite' and _number(amount) else None,
                    bid=bid if _number(bid) else None, **metrics, metric_state=metric_state)
                previous_targets = deepcopy(context['selected_targets']['groups'])
                if kind != 'campaign' and record['group'] not in [r[0] for r in previous_targets]:
                    group_id = entity['id'] if kind == 'adgroup' else entity['parent_id']
                    states = []
                    for target in TARGETS:
                        detail = all_targets.get((group_id, target))
                        states.append(['u', None] if detail is None else
                                      ['o' if detail['state'] == 'observed' else 's', detail['record_total']])
                    context['selected_targets']['groups'].append([record['group']] + states)
                    context['selected_targets']['groups'].sort(key=lambda row: row[0])
                context['rows'].append([record[k] for k in COLUMNS])
                context['coverage'].update(selected=len(context['rows']), truncated=len(context['rows']) < len(entities))
                if len(canonical(context).encode()) > MAX_CONTEXT_BYTES:
                    context['rows'].pop()
                    context['selected_targets']['groups'] = previous_targets
                    context['coverage'].update(selected=len(context['rows']), truncated=len(context['rows']) < len(entities))
                    break
                name = _label(raw.get('name')) if kind in ('campaign', 'adgroup') else None
                if kind != 'campaign':
                    campaign_name = _label(entities.get('campaign:'+str(entity['campaign_id']), {}).get('settings', {}).get('name'))
                    if kind in ('ad', 'keyword'):
                        parent_name = _label(entities.get('adgroup:'+str(entity['parent_id']), {}).get('settings', {}).get('name'))
                        name = (parent_name+' / ' if parent_name else '')+_LABELS[kind]+' '+str(record['index'])
                    if name is not None and campaign_name:
                        name = campaign_name+' / '+name
                labels[str(record['index'])] = (_LABELS[kind]+' · '+name) if name else _LABELS[kind]+' '+str(record['index'])
    context = normalize_context(context)
    labels = normalize_labels(labels, context)
    try:
        raw = canonical({'observation': observation, 'context': context, 'labels': labels})
        if len(raw.encode()) > 9*1024*1024:
            _bad()
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()
    except (ValueError, TypeError, OverflowError, RecursionError):
        _bad()
    # Current source authority is revalidated separately. Refresh timestamps do
    # not change settings semantics; archival source dates are retained above.
    semantics = {'binding': {k: observation.get(k) for k in ('customer_id', 'possibility_id', 'stage_revision')} if observation else None,
        'state': context['state'], 'reason': context['reason'], 'counts': context['counts'], 'checks': context['checks'],
        'check_states': context['check_states'], 'targets': context['targets'], 'labels': labels,
        **_semantic_available(observation, report_payload, now)}
    try:
        semantic_fingerprint = hashlib.sha256(canonical(semantics).encode()).hexdigest()
    except (ValueError, TypeError, OverflowError, RecursionError):
        _bad()
    return dict(context=context, fingerprint=fingerprint, labels=labels,
                semantic_fingerprint=semantic_fingerprint)


def model_source(observation, report_payload, now):
    """Return only the closed evidence contract; malformed nested source fails closed."""
    try:
        return _model_source(observation, report_payload, now)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        _bad()


def display(context, index, field, labels=None):
    context = normalize_context(context)
    if type(index) is not int or not 0 <= index <= MAX_ROWS:
        raise EvidenceUnavailable()
    if index == 0:
        if field not in SUMMARY_FIELDS:
            raise EvidenceUnavailable()
        if field == 'source_status':
            return ('현재 상세 설정 관측 '+context['source']['checked_at']+' · 다음 계획 참고용') if context['state'] == 'current' else '현재 상세 설정 자료 미확인 · '+context['reason']
        if field == 'period_relation':
            return '상세 설정은 다음 계획 참고용이며 과거 성과의 원인 근거가 아닙니다' + (' · 보고기간과 관측기간 다름' if context['period_relation'] == 'different' else '')
        if field == 'coverage':
            return '선택 상세 '+str(context['coverage']['selected'])+'개 / 전체 관측 '+str(context['coverage']['total'])+'개' if context['state'] == 'current' else '상세 관측 범위 미확인'
        if field == 'checks':
            if context['state'] != 'current':
                raise EvidenceUnavailable()
            names = {'structure': '구조', 'inspection': '심사', 'suspension': '중지·삭제', 'delivery': '노출제한',
                'campaign_budget': '캠페인 한도', 'campaign_period': '캠페인 기간', 'time_targeting': '요일·시간',
                'region_targeting': '지역', 'age_targeting': '연령', 'negative_keywords': '제외 검색어',
                'creative_copy': '소재 자산', 'goal': '계획 목표', 'budget_plan': '계획 예산', 'setup_completeness': '전체 설정'}
            states = {'a': '확인 필요', 'u': '미확인', 'v': '관측', 'n': '유형상 미적용'}
            return ' · '.join(names[key]+': '+states[code] for key, code in zip(CHECK_KEYS, context['check_states']['row']))
        value = context['checks'].get(field[:-6]) if field in ('attention_count', 'unknown_count') else context['counts'].get(field[:-6])
        if value is None:
            raise EvidenceUnavailable()
        return field.replace('_count', '')+' 관측 '+f'{value:,}'+'개'
    if field not in ENTITY_FIELDS or index > len(context['rows']):
        raise EvidenceUnavailable()
    row = dict(zip(COLUMNS, context['rows'][index-1]))
    if field == 'target':
        return normalize_labels(labels, context).get(str(index), _LABELS[row['kind']]+' '+str(index))
    if field == 'status':
        return '관측 '+_STATUS[row['status']]
    if field == 'targeting':
        group = next((r for r in context['selected_targets']['groups'] if r[0] == row['group']), None)
        if row['kind'] == 'campaign' or group is None:
            raise EvidenceUnavailable()
        names = ('요일·시간', '지역', '연령', '제외 검색어')
        def state(pair):
            return '미확인' if pair[0] == 'u' else '유형상 미지원' if pair[0] == 's' else '명시 설정 '+str(pair[1])+'건 관측'
        return ' · '.join(name+': '+state(pair) for name, pair in zip(names, group[1:]))+' · 실제 타겟값·제외어 문구는 모델에 미전달 · 제외어 관측은 KEYWORD_PLUS_RESTRICT 범위이며 전체 제외 설정이 아님'

    value = row[field]
    if value is None:
        raise EvidenceUnavailable()
    number = f'{value:,.6f}'.rstrip('0').rstrip('.') if isinstance(value, float) else f'{value:,}'
    units = '%' if field == 'ctr' else '원' if field in ('daily_budget', 'bid', 'spend', 'conversion_value', 'cpc') else '회'
    names = {'daily_budget': '관측 대상 일한도', 'bid': '관측 입찰가', 'impressions': '대상 노출', 'clicks': '대상 클릭',
             'spend': '대상 광고비', 'conversions': '대상 일반 전환', 'conversion_value': '대상 플랫폼 전환가치', 'ctr': '대상 CTR', 'cpc': '대상 CPC'}
    suffix = ' · 승인 계정 예산·부가세·공유예산 확정 아님' if field == 'daily_budget' else ''
    return names[field]+' '+number+units+suffix


def source_boundary(context):
    """Deterministic input disclosure, separately labelled from AI assessment."""
    context = normalize_context(context)
    if context['state'] != 'current':
        return '상세 설정 입력 범위: 현재 자료 '+{'missing':'없음','stale':'이전 회차','incomplete':'미완결'}[context['reason']]+' · 상세 설정·대상별 성과 판단 보류.'
    source, coverage = context['source'], context['coverage']
    relation = '보고기간과 같은 관측기간' if context['period_relation'] == 'same' else '보고기간과 다른 관측기간 · 대상별 과거 성과 미전달'
    checks = context['checks']
    return ('상세 설정 입력 범위: 확인 '+source['checked_at']+' · 원천기간 '+source['period_start']+'~'+source['period_end']+
        ' · '+relation+' · 전체 '+str(coverage['total'])+'개 중 '+str(coverage['selected'])+'개 선택'+
        ('(일부 선택)' if coverage['truncated'] else '')+' · 설정 점검 14항목: 확인 필요 '+str(checks['attention'])+
        ', 자료 미확인 '+str(checks['unknown'])+', 관측 '+str(checks['verified'])+', 유형상 미적용 '+str(checks['not_applicable'])+
        ' · 전체 설정 정상 확인을 뜻하지 않음 · 선택 그룹별 타겟 상태·건수만 전달, 실제 요일·시간·지역·연령값·제외어 문구 미전달.'+
        ' 제외어 관측은 KEYWORD_PLUS_RESTRICT 범위이며 EXP_SEARCH 등 전체 제외 설정이 아님. 현재 설정은 다음 계획 참고용이며 과거 성과 원인·A/B 승자 근거가 아님. 관측 일한도는 승인 계정 상한·부가세·공유예산 확정이 아님.')
