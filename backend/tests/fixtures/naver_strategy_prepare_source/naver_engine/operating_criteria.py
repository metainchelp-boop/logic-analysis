"""개별 관리 계정의 운영 기준. 순수 검증·관측 비교만 하며 광고를 실행하지 않는다."""
from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import math
import re

KST = timezone(timedelta(hours=9))
BASE_FIELDS = frozenset({'goal','target_value','daily_spend_cap','absolute_bid_cap','experiment_days','loss_cap','notes'})
LIMIT_FIELDS = frozenset({'single_increase_percent','single_decrease_percent','rolling_day_increase_percent',
                         'rolling_day_decrease_percent','weekly_increase_requires_approval_percent'})
EXTRA_FIELDS = frozenset({'schema_version','monthly_spend_cap','conversion_definition','value_basis','period_start','period_end',
                         'measurement_lag_days','minimum_clicks','minimum_conversions','change_limits'})
V2_FIELDS = BASE_FIELDS | EXTRA_FIELDS
CONVERSION_DEFINITIONS = frozenset({'platform','purchase','lead'})
VALUE_BASES = frozenset({'platform_conversion_value','paid_order_revenue','gross_profit'})
_METRICS = frozenset({'impressions','clicks','spend','conversions','conversion_value'})


class CriteriaInvalid(ValueError):
    pass


def _refuse():
    raise CriteriaInvalid('개별 계정 운영 기준의 항목·단위·기간을 확인해 주세요')


def _number(value, low=0, high=10**15, integer=False):
    return type(value) in ((int,) if integer else (int,float)) and low <= value <= high and math.isfinite(value)


def _day(value):
    if not isinstance(value,str) or re.fullmatch(r'\d{4}-\d{2}-\d{2}',value) is None:
        _refuse()
    try:
        return date.fromisoformat(value)
    except ValueError:
        _refuse()


def _moment(value):
    try:
        at = datetime.fromisoformat(value) if isinstance(value,str) else value
        return at.astimezone(KST) if isinstance(at,datetime) and at.utcoffset() is not None else None
    except (ValueError,TypeError,OverflowError):
        return None


def empty_extra():
    return {**{key:None for key in EXTRA_FIELDS},'schema_version':2,'change_limits':dict.fromkeys(sorted(LIMIT_FIELDS))}


def _months(start,end,daily,monthly):
    result=[]
    cursor=start.replace(day=1)
    while cursor <= end:
        final=date(cursor.year,cursor.month,monthrange(cursor.year,cursor.month)[1])
        active=(min(end,final)-max(start,cursor)).days+1
        result.append({'month':cursor.strftime('%Y-%m'),'active_days':active,'capacity':min(monthly,daily*active)})
        if cursor.month == 12:
            if cursor.year == 9999: break
            cursor=date(cursor.year+1,1,1)
        else:
            cursor=date(cursor.year,cursor.month+1,1)
    return result


def normalize_extra(plan,approve=False):
    """v2 추가 필드만 반환. base 값은 기존 plan_document가 검증한다."""
    if not isinstance(plan,dict) or set(plan) not in (V2_FIELDS,V2_FIELDS-{'notes'}) or type(plan.get('schema_version')) is not int or plan['schema_version'] != 2:
        _refuse()
    out={key:deepcopy(plan[key]) for key in EXTRA_FIELDS}
    for key,options in (('conversion_definition',CONVERSION_DEFINITIONS),('value_basis',VALUE_BASES)):
        if out[key] is not None and (not isinstance(out[key],str) or out[key] not in options): _refuse()
    if out['monthly_spend_cap'] is not None and not _number(out['monthly_spend_cap'],low=1e-12,high=10**12): _refuse()
    for key,low,high in (('measurement_lag_days',0,30),('minimum_clicks',1,10**9),('minimum_conversions',1,10**9)):
        if out[key] is not None and not _number(out[key],low,high,integer=True): _refuse()
    dates={key:None if out[key] is None else _day(out[key]) for key in ('period_start','period_end')}
    start,end=dates.values()
    if start and end and not 1 <= (end-start).days+1 <= 366: _refuse()
    limits=out['change_limits']
    if not isinstance(limits,dict) or set(limits) != LIMIT_FIELDS: _refuse()
    for key,value in limits.items():
        if value is not None and not _number(value,0,100 if 'decrease' in key else 1000): _refuse()
    if approve:
        required={'monthly_spend_cap','period_start','period_end','measurement_lag_days','minimum_clicks'}
        if plan.get('goal') in ('cpa','roas'): required |= {'conversion_definition','minimum_conversions'}
        if plan.get('goal') == 'roas': required.add('value_basis')
        if any(out[key] is None for key in required) or any(value is None for value in limits.values()): _refuse()
        if any(not _number(plan.get(key),1e-12,10**12) for key in ('target_value','daily_spend_cap','absolute_bid_cap','loss_cap')) \
                or not _number(plan.get('experiment_days'),2,30,integer=True): _refuse()
        days=(end-start).days+1
        if plan['experiment_days'] > days or plan['absolute_bid_cap'] > plan['daily_spend_cap']: _refuse()
        capacity=sum(row['capacity'] for row in _months(start,end,plan['daily_spend_cap'],out['monthly_spend_cap']))
        if plan['loss_cap'] > min(plan['daily_spend_cap']*plan['experiment_days'],capacity): _refuse()
    return out


def _reason(code,message):
    return {'code':code,'message':message}


def _performance(value,now):
    keys={'period_start','period_end','source_at','basic_complete','conversion_complete','conversion_definition','value_basis','minimum_source_lag_days','fields'}
    try:
        if not isinstance(value,dict) or set(value) != keys: return None
        start,end=_day(value['period_start']),_day(value['period_end'])
        source=_moment(value['source_at'])
        if not 1 <= (end-start).days+1 <= 366 or end >= now.date() or source is None or source > now or source.date() <= end: return None
        if type(value['basic_complete']) is not bool or type(value['conversion_complete']) is not bool: return None
        if value['minimum_source_lag_days'] is not None and not _number(value['minimum_source_lag_days'],0,366,integer=True): return None
        boundary=datetime.combine(end,time.min,tzinfo=KST)+timedelta(days=1)
        if value['minimum_source_lag_days'] is not None and value['minimum_source_lag_days'] > (source-boundary).days: return None
        if value['conversion_definition'] not in CONVERSION_DEFINITIONS or value['value_basis'] not in VALUE_BASES: return None
        if not isinstance(value['fields'],dict) or set(value['fields']) != _METRICS: return None
        if any(v is not None and not _number(v) for v in value['fields'].values()): return None
        if value['basic_complete'] and any(value['fields'][key] is None for key in ('impressions','clicks','spend')): return None
        if value['conversion_complete'] and (not value['basic_complete'] or any(v is None for v in value['fields'].values())): return None
        return deepcopy(value)
    except (CriteriaInvalid,TypeError,ValueError,OverflowError):
        return None


def assess(plan_view,now,performance=None):
    now=_moment(now)
    if now is None: _refuse()
    doc=plan_view.get('plan',plan_view.get('document',{})) if isinstance(plan_view,dict) else {}
    state=plan_view.get('state') if isinstance(plan_view,dict) else None
    approved=state=='approved' and _number(plan_view.get('version'),1,2**53-1,integer=True)
    out={'version':1,'state':'hold','criteria_complete':False,'approval_current':approved,
         'execution_enabled':False,'as_of':now.isoformat(),'reasons':[],
         'budget':{'scope':'individual_managed_account','daily_cap':None,'monthly_cap':None,'months':[],'remaining':None},
         'metric':{'goal':None,'value':None,'target':None,'status':'hold'},'limits':dict.fromkeys(sorted(LIMIT_FIELDS))}
    def hold(code,message):out['reasons'].append(_reason(code,message))
    if not isinstance(doc,dict) or doc.get('schema_version') != 2:
        out['state']='needs_criteria';hold('CRITERIA_MISSING','기존 계획은 보존되며 새 계정별 운영 기준은 미정입니다.');return out
    try:
        extra=normalize_extra(doc)
    except CriteriaInvalid:
        hold('CRITERIA_INVALID','운영 기준의 항목·단위·기간을 다시 확인하세요.');return out
    out['limits']=extra['change_limits']
    out['budget'].update(daily_cap=doc.get('daily_spend_cap') if _number(doc.get('daily_spend_cap'),1e-12,10**12) else None,monthly_cap=extra['monthly_spend_cap'])
    goal=doc.get('goal');out['metric'].update(goal=goal if goal in ('impressions','clicks','cpa','roas') else None,target=doc.get('target_value') if _number(doc.get('target_value'),1e-12,10**12) else None)
    try:
        if goal not in ('impressions','clicks','cpa','roas'): _refuse()
        normalize_extra(doc,approve=True)
        out['criteria_complete']=True
    except CriteriaInvalid:
        hold('CRITERIA_INCOMPLETE','목표·예산·기간·측정 대기·최소 표본·변경 한도의 필수 기준을 확인하세요.')
    if extra['period_start'] and extra['period_end'] and _number(doc.get('daily_spend_cap'),1e-12,10**12) and extra['monthly_spend_cap'] is not None:
        out['budget']['months']=_months(_day(extra['period_start']),_day(extra['period_end']),doc['daily_spend_cap'],extra['monthly_spend_cap'])
    if not approved: hold('PLAN_UNAPPROVED','현재 기준을 포함한 계획은 아직 승인되지 않았습니다.')
    if extra['period_start'] and extra['period_end'] and not _day(extra['period_start']) <= now.date() <= _day(extra['period_end']):
        hold('OUTSIDE_OPERATION_WINDOW','계획한 운영 기간 밖입니다.')
    observed=_performance(performance,now)
    if observed is None:
        hold('PERFORMANCE_UNCONFIRMED','동일 계정·기간의 완결된 성과와 원천 시각을 확인하지 못했습니다.')
    elif out['criteria_complete']:
        start,end=_day(observed['period_start']),_day(observed['period_end'])
        fields=observed['fields']
        if start < _day(extra['period_start']) or end > _day(extra['period_end']):
            hold('PERFORMANCE_OUTSIDE_WINDOW','성과 집계 기간과 승인 운영 기간이 일치하지 않습니다.')
        if not observed['basic_complete']: hold('BASIC_INCOMPLETE','노출·클릭·광고비 집계가 부분 또는 미확인입니다.')
        if fields['clicks'] is None or fields['clicks'] < extra['minimum_clicks']:
            hold('INSUFFICIENT_CLICKS','담당자가 정한 최소 클릭 표본을 충족하지 못했습니다.')
        if goal in ('cpa','roas'):
            if not observed['conversion_complete']: hold('CONVERSION_INCOMPLETE','전환과 광고비의 동일 범위 집계가 미완결입니다.')
            if observed['conversion_definition'] != extra['conversion_definition']:
                hold('CONVERSION_DEFINITION_MISMATCH','플랫폼 일반 전환을 구매·리드 성과로 바꾸어 평가하지 않습니다.')
            if goal == 'roas' and observed['value_basis'] != extra['value_basis']:
                hold('VALUE_BASIS_MISMATCH','전환가치·결제 매출·이익의 기준이 다릅니다.')
            if fields['conversions'] is None or fields['conversions'] < extra['minimum_conversions']:
                hold('INSUFFICIENT_CONVERSIONS','담당자가 정한 최소 전환 표본을 충족하지 못했습니다.')
            # 원천 통계 시각이 담당자가 지정한 대기 기간을 지났는지 확인. 태그 정상 증거는 아님.
            if observed['minimum_source_lag_days'] is None or observed['minimum_source_lag_days'] < extra['measurement_lag_days']: hold('MEASUREMENT_WAIT','담당자가 정한 전환 대기 기간이 원천 통계에 아직 반영되지 않았습니다.')
            if (fields['conversions'] if goal=='cpa' else fields['spend']) == 0:
                hold('ZERO_DENOMINATOR','분모가 0이므로 목표 효율과 비교하지 않습니다.')
        elif (end-start).days+1 != doc['experiment_days']:
            hold('EVALUATION_PERIOD_MISMATCH','횟수 목표와 성과 집계의 기간이 다릅니다.')
        if not out['reasons']:
            value=(fields['spend']/fields['conversions'] if goal=='cpa' else fields['conversion_value']/fields['spend']*100 if goal=='roas' else fields[goal])
            if _number(value):
                out['metric'].update(value=value,status='at_target' if (value<=doc['target_value'] if goal=='cpa' else value>=doc['target_value']) else 'below_target')
                out['state']='reviewable'
    return out


def performance_from_observation(observation):
    """캠페인 합계만 사용. 그룹·키워드·소재를 더해 중복 집계하지 않는다."""
    try:
        if (not isinstance(observation,dict) or observation.get('status')!='ok' or observation.get('complete') is not True
                or observation.get('stale') is not False): return None
        campaigns=observation['campaigns']; entities=observation['entities']; metrics=observation['performance']
        if not isinstance(campaigns,list) or not 1 <= len(campaigns) <= 10000 or not isinstance(entities,dict) or not isinstance(metrics,dict): return None
        mapping={'impressions':'impCnt','clicks':'clkCnt','spend':'salesAmt','conversions':'ccnt','conversion_value':'convAmt'}
        rows=[];seen=set()
        for campaign in campaigns:
            identifier=campaign['nccCampaignId'];key='campaign:'+identifier
            if identifier in seen or key not in entities or entities[key]['entity']!='campaign': return None
            seen.add(identifier);row=metrics[key]
            if row['period_start']!=observation['period_start'] or row['period_end']!=observation['period_end'] or row.get('missing') is not False: return None
            if not isinstance(row['fields'],dict) or any(row['fields'].get(name) is not None and not _number(row['fields'][name]) for name in mapping.values()): return None
            rows.append(row)
        fields={key:sum(row['fields'][name] for row in rows) if all(row['fields'].get(name) is not None for row in rows) else None for key,name in mapping.items()}
        if any(value is not None and not _number(value) for value in fields.values()): return None
        sources=[_moment(row.get('source_at')) for row in rows]
        source=max(sources).isoformat() if all(at is not None for at in sources) else None
        boundary=datetime.combine(_day(observation['period_end']),time.min,tzinfo=KST)+timedelta(days=1)
        lag=min((at-boundary).days for at in sources) if all(at is not None and at>=boundary for at in sources) else None
        return {'period_start':observation['period_start'],'period_end':observation['period_end'],'source_at':source,
                'basic_complete':all(fields[key] is not None for key in ('impressions','clicks','spend')),
                'conversion_complete':all(row.get('complete') is True for row in rows) and all(v is not None for v in fields.values()),
                'conversion_definition':'platform','value_basis':'platform_conversion_value','minimum_source_lag_days':lag,'fields':fields}
    except (KeyError,TypeError,ValueError,OverflowError):
        return None


def performance_from_report(payload):
    from . import report_enrichment as E
    try:
        result=E.enrich(payload); metrics={row['key']:row for row in result['metrics']}
        period=payload['period'];source=payload.get('_source_manifest',[])
        start,end=_day(period['start']),_day(period['end'])
        days=(end-start).days+1
        if not 1 <= days <= 366 or payload.get('coverage',{}).get('accounts') != 1 \
                or not isinstance(source,list) or len(source) != days: return None
        if any(not isinstance(row,dict) or type(row.get('customer_id')) is not int or row['customer_id'] <= 0 for row in source): return None
        owners={row['customer_id'] for row in source}
        if len(owners) != 1 or {row.get('day') for row in source} != {str(start+timedelta(days=i)) for i in range(days)}: return None
        if '_expected_customers' in payload and payload['_expected_customers'] != list(owners): return None
        moments=[_moment(row.get('source_at')) for row in source]
        source_at=max(moments).isoformat() if moments and all(at is not None for at in moments) else None
        elapsed=[]
        for row,at in zip(source,moments):
            boundary=datetime.combine(_day(row['day']),time.min,tzinfo=KST)+timedelta(days=1)
            if at is None or at<boundary: break
            elapsed.append((at-boundary).days)
        lag=min(elapsed) if elapsed and len(elapsed)==len(source) else None
        fields={key:metrics[key]['current'] for key in _METRICS}
        return {'period_start':period['start'],'period_end':period['end'],'source_at':source_at,
                'basic_complete':result['quality']['basic']['complete'] is True,
                'conversion_complete':result['quality']['paired']['complete'] is True,
                'conversion_definition':'platform','value_basis':'platform_conversion_value','minimum_source_lag_days':lag,'fields':fields}
    except (KeyError,TypeError,ValueError,OverflowError):
        return None


def assessment_from_report(plan_view,payload):
    """현재시각을 발명하지 않고 저장 보고서의 작성시점에 한해서 비교한다."""
    at=_moment(payload.get('generated_at')) if isinstance(payload,dict) else None
    if at is None: return None
    out=assess(plan_view,at,performance_from_report(payload));out['assessment_source']='saved_report'
    return out
