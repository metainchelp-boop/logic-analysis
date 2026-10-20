"""Explicit daily randomized CTR protocols. No implicit traffic randomization."""
from copy import deepcopy
from datetime import date,datetime,time,timedelta
from decimal import Decimal
import hashlib
import json
import math
import re
import secrets
from zoneinfo import ZoneInfo

KST=ZoneInfo('Asia/Seoul')
METHOD='randomized_paired_ctr_constant_shift_v1'
FIELDS=frozenset(('schema_version method control_key treatment_key single_variable hypothesis period_start pair_count washout_hours measurement_lag_days superiority_margin_pp equivalence_margin_pp minimum_impressions_per_block experiment_spend_cap max_changes_24h end_policy unobserved_settings_fixed assumptions').split())
ASSUMPTIONS=frozenset(('constant_additive_effect','no_interference','no_carryover'))
METRICS=frozenset(('impCnt','clkCnt','salesAmt'))
MAX=2**53-1
class RandomizedInvalid(ValueError):pass

def fail(message='무작위 블록 실험의 기간·단위·실제 원천을 확인해 주세요'):
    raise RandomizedInvalid(message)

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def moment(value):
    if isinstance(value,str):
        try:value=datetime.fromisoformat(value)
        except ValueError:fail()
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:fail()
    return value.astimezone(KST)

def day(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):fail()
    try:return date.fromisoformat(value)
    except ValueError:fail()

def number(value,low,high=MAX,*,integer=False):
    return type(value) in ((int,) if integer else (int,float)) and math.isfinite(value) and low<=value<=high

def empty_document():
    return {**{k:None for k in FIELDS},'schema_version':1,'method':METHOD,'single_variable':'','hypothesis':'',
        'unobserved_settings_fixed':False,'assumptions':{k:False for k in sorted(ASSUMPTIONS)}}

def normalize_document(value,*,approve=False):
    if not isinstance(value,dict) or set(value)!=FIELDS:fail()
    out=deepcopy(value)
    if type(out['schema_version'])is not int or out['schema_version']!=1 or out['method']!=METHOD:fail()
    if out['end_policy'] is not None and out['end_policy']!='pause_both':fail()
    if type(out['unobserved_settings_fixed']) is not bool:fail()
    for k in ('control_key','treatment_key'):
        if out[k] is not None and (not isinstance(out[k],str) or not re.fullmatch(r'[0-9a-f]{64}',out[k])):fail()
    for k,cap in (('single_variable',160),('hypothesis',1000)):
        if not isinstance(out[k],str) or len(out[k])>cap or any(ord(c)<32 and c not in '\n\t' for c in out[k]):fail()
    if out['period_start'] is not None:day(out['period_start'])
    for k,lo,hi,integer in (('pair_count',2,15,True),('washout_hours',1,23,True),('measurement_lag_days',0,30,True),
            ('superiority_margin_pp',0,100,False),('equivalence_margin_pp',1e-12,100,False),
            ('minimum_impressions_per_block',1,MAX,True),('experiment_spend_cap',1e-12,10**12,False),('max_changes_24h',1,100,True)):
        if out[k] is not None and not number(out[k],lo,hi,integer=integer):fail()
    a=out['assumptions']
    if not isinstance(a,dict) or set(a)!=ASSUMPTIONS or any(type(v)is not bool for v in a.values()):fail()
    if approve and (any(out[k] is None or out[k]=='' for k in FIELDS-{'assumptions'}) or not all(a.values()) or not out['unobserved_settings_fixed']
            or out['control_key']==out['treatment_key']):fail('대상·기간·pp 기준과 조건부 모형의 가정을 모두 명시해 주세요')
    if out['equivalence_margin_pp'] is not None and out['superiority_margin_pp'] is not None and out['equivalence_margin_pp']>out['superiority_margin_pp']:fail('등가 한계는 우세 한계보다 클 수 없습니다')
    return out

def period_end(doc):return (day(doc['period_start'])+timedelta(days=2*doc['pair_count']-1)).isoformat()

def make_schedule(document,*,experiment_id,coins=None):
    doc=normalize_document(document,approve=True)
    if not isinstance(experiment_id,str) or not re.fullmatch(r'[0-9a-f]{32}',experiment_id):fail()
    if coins is None:coins=[bool(secrets.randbits(1)) for _ in range(doc['pair_count'])]
    if not isinstance(coins,(list,tuple)) or len(coins)!=doc['pair_count'] or any(type(v)is not bool for v in coins):fail()
    out=[]
    for n in range(2*doc['pair_count']):
        d=day(doc['period_start'])+timedelta(days=n);start=datetime.combine(d,time(),KST)
        treatment=coins[n//2] if n%2==0 else not coins[n//2]
        out.append(dict(block_id=digest([experiment_id,'block',n])[:32],pair_key=digest([experiment_id,'pair',n//2]),
            day=d.isoformat(),arm='treatment' if treatment else 'control',start_at=start.isoformat(),
            measurement_start_at=(start+timedelta(hours=doc['washout_hours'])).isoformat(),
            end_at=(start+timedelta(days=1)).isoformat()))
    return out

def _material_arm(arm):
    out=deepcopy(arm)
    if out['kind']=='ad':
        for k in ('userLock','status','editTm'):out['settings'].pop(k,None)
    return out

def bind_document(document,plan_view,catalog,now,*,registered_at=None):
    from . import experiments as X
    doc=normalize_document(document,approve=True);now=moment(now);plan=X._plan(plan_view)
    if not isinstance(catalog,dict) or catalog.get('status')!='ready':fail('완결된 현재 설정 관측이 필요합니다')
    scope={k:v for k,v in catalog['scope'].items() if k!='generation'}
    arms={name:deepcopy(catalog['_arms'].get(doc[name+'_key'])) for name in ('control','treatment')}
    if any(not a or a['kind']!='ad' or a['settings'].get('type')!='TEXT_45' for a in arms.values()):fail('같은 그룹의 TEXT_45 두 소재를 선택해 주세요')
    first=arms['control']
    if arms['treatment']['id']==first['id'] or any((a['parent_id'],a['campaign_id'])!=(first['parent_id'],first['campaign_id']) for a in arms.values()):fail()
    entities=[deepcopy(a) for a in catalog['_arms'].values() if a['id']==first['campaign_id'] or
        a['kind']=='adgroup' and a['id']==first['parent_id'] or a['kind'] in ('ad','keyword') and a['parent_id']==first['parent_id']]
    ads=[a for a in entities if a['kind']=='ad'];parents={k:next((a for a in entities if a['kind']==k),None) for k in ('campaign','adgroup')}
    if len(ads)!=2 or {a['id'] for a in ads}!={a['id'] for a in arms.values()} or not all(parents.values()) or len([a for a in entities if a['kind']=='keyword'])>50:fail('전체 그룹에 정확한 두 소재와 부모 원천이 필요합니다')
    if moment(catalog['scope']['generation'])>now:fail()
    start,end=day(doc['period_start']),day(period_end(doc));registration=moment(registered_at) if registered_at else now
    if registration>now or registration>=datetime.combine(start,time(),KST):fail('시작 전 사전 승인이 필요합니다')
    if start<day(plan['period_start']) or end>day(plan['period_end']) or 2*doc['pair_count']>plan['experiment_days']:fail('승인된 운영 기간과 실험 기간 상한을 확인해 주세요')
    if doc['measurement_lag_days']!=plan['measurement_lag_days'] or doc['experiment_spend_cap']>plan['loss_cap']:fail()
    material=sorted((_material_arm(a) for a in entities),key=lambda a:(a['kind'],a['id']))
    return dict(version=1,document=doc,scope=scope,plan_version=plan_view['version'],plan=plan,arms=arms,parents=parents,
        group_entities=entities,source_fingerprint=digest([scope,material]),registered_at=registration.isoformat())

def current_binding(binding,plan_view,catalog,now):
    doc=deepcopy(binding['document'])
    # Own userLock changes alter public opaque keys; identity is frozen server-side.
    for name,arm in binding['arms'].items():
        matches=[k for k,a in catalog.get('_arms',{}).items() if a['kind']==arm['kind'] and a['id']==arm['id']]
        if len(matches)!=1:fail()
        doc[name+'_key']=matches[0]
    fresh=bind_document(doc,plan_view,catalog,now,registered_at=binding['registered_at'])
    if fresh['scope']!=binding['scope'] or fresh['plan_version']!=binding['plan_version'] or fresh['plan']!=binding['plan'] or fresh['source_fingerprint']!=binding['source_fingerprint']:fail('승인 후 운영 기준 또는 그룹 설정이 변경되었습니다')
    return True

def inference_protocol(binding):
    d=binding['document']
    return dict(version=1,method=METHOD,registered_at=binding['registered_at'],period_start=d['period_start'],period_end=period_end(d),
        pair_count=d['pair_count'],measurement_lag_days=d['measurement_lag_days'],superiority_margin_pp=d['superiority_margin_pp'],
        equivalence_margin_pp=d['equivalence_margin_pp'],assumptions=deepcopy(d['assumptions']))

def normalize_hourly(value,*,now=None):
    expected={'customer_id','entity_id','day','source_at','hours','summary'}
    if not isinstance(value,dict) or set(value)!=expected or not number(value['customer_id'],1,MAX,integer=True) or not isinstance(value['entity_id'],str) or not value['entity_id'].startswith('nad-'):fail()
    d=day(value['day']);source=moment(value['source_at'])
    if source.date()<=d or now is not None and source>moment(now):fail('시간 통계의 집계 시점을 확인해 주세요')
    hours=value['hours'];summary=value['summary']
    if not isinstance(hours,list) or len(hours)!=24 or {r.get('hour') for r in hours if isinstance(r,dict)}!=set(range(24)):fail('24시간 원천이 완결되지 않았습니다')
    def fields(row):
        if set(row)!=METRICS or not number(row['impCnt'],0,MAX,integer=True) or not number(row['clkCnt'],0,row['impCnt'],integer=True) or not number(row['salesAmt'],0,10**15):fail()
    if not isinstance(summary,dict):fail()
    fields(summary)
    for row in hours:
        if not isinstance(row,dict) or set(row)!=METRICS|{'hour'} or type(row['hour'])is not int:fail()
        fields({k:row[k] for k in METRICS})
    if any(sum(Decimal(str(r[k])) for r in hours)!=Decimal(str(summary[k])) for k in METRICS):fail('시간 합계와 요약 통계가 다릅니다')
    return {**deepcopy(value),'source_at':source.isoformat(),'hours':sorted(deepcopy(hours),key=lambda r:r['hour'])}

def validate_probe(control,treatment,now):
    c,t=(normalize_hourly(v,now=now) for v in (control,treatment))
    if c['customer_id']!=t['customer_id'] or c['entity_id']==t['entity_id'] or c['day']!=t['day'] or c['source_at']!=t['source_at']:fail('두 소재의 동일 집계 시점·날짜 원천이 필요합니다')
    return dict(version=1,verified=True,day=c['day'],source_at=c['source_at'],checked_at=moment(now).isoformat(),
        customer_id=c['customer_id'],entity_ids=sorted((c['entity_id'],t['entity_id'])))
