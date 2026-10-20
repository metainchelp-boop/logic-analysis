"""Closed campaign-detail evidence; missing fields never mean nonshared.

This module grants no authority. Store supplies a current sealed observation and
execution rechecks that binding; the original campaign-list settings stay intact.
"""
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json

from . import inspection_fields as F

MAX_AGE = timedelta(minutes=15)
DETAIL_KEYS = frozenset(('settings checked_at verified_at error_code').split())
PROOF_KEYS = frozenset(('version origin scope root_fingerprint campaigns details checked_at').split())
SCOPE_KEYS = frozenset(('possibility_id customer_id account_key stage_revision generation').split())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def moment(value):
    if not isinstance(value,str): raise ValueError('관측 시각이 없습니다')
    at=datetime.fromisoformat(value)
    if at.utcoffset() is None: raise ValueError('관측 시각에는 시간대가 필요합니다')
    return at


def state(raw):
    result='unknown' if 'sharedBudgetId' not in raw else 'none' if raw['sharedBudgetId'] is None else 'shared'
    if raw.get('sharedBudgetLock') is True or type(raw.get('sharedDailyBudget')) in (int,float) and raw['sharedDailyBudget']>0:
        result='shared'
    return result


def detail_valid(value,root,cid,*,complete=False):
    if not isinstance(value,dict) or set(value)!=DETAIL_KEYS: raise ValueError('단건 관측 항목이 다릅니다')
    checked=moment(value['checked_at']); verified=None if value['verified_at'] is None else moment(value['verified_at'])
    if verified is not None and verified<checked or complete and verified is None: raise ValueError('단건 관측이 미완결입니다')
    raw=value['settings']
    if raw is None:
        if value['error_code']!='NOT_FOUND': raise ValueError('단건 읽기 실패 근거가 다릅니다')
    elif (value['error_code'] is not None or F.sanitize_record('campaign',raw,cid)!=raw
            or any(k not in raw or raw[k]!=v for k,v in root.items())):
        raise ValueError('단건 관측의 계정·캠페인·목록 설정이 다릅니다')
    return value


def validate(proof,now,*,scope=None,campaigns=None):
    if not isinstance(now,datetime) or now.utcoffset() is None: raise ValueError('확인 시각이 다릅니다')
    if not isinstance(proof,dict) or set(proof)!=PROOF_KEYS or type(proof['version']) is not int or proof['version']!=1 or proof['origin']!='campaign-detail-get':
        raise ValueError('단건 예산 원천 형식이 다릅니다')
    bound=proof['scope']
    if not isinstance(bound,dict) or set(bound)!=SCOPE_KEYS or any(type(bound[k]) is not int or bound[k]<=0 for k in ('possibility_id','customer_id')):
        raise ValueError('단건 예산 소속이 다릅니다')
    if (bound['account_key']!=hashlib.sha256(str(bound['customer_id']).encode('ascii')).hexdigest()
            or not isinstance(bound['stage_revision'],str) or not bound['stage_revision'] or len(bound['stage_revision'])>200):
        raise ValueError('단건 예산 관리 원천이 다릅니다')
    generation=moment(bound['generation']); checked=moment(proof['checked_at'])
    if generation>checked or not timedelta(0)<=now-checked<=MAX_AGE: raise ValueError('단건 예산 원천이 오래되었거나 미래입니다')
    if scope is not None and any(bound.get(k)!=v for k,v in scope.items()): raise ValueError('단건 예산 소속이 바뀌었습니다')
    roots=proof['campaigns']
    if not isinstance(roots,list) or not 1<=len(roots)<=F.MAX_ROWS or roots!=sorted(roots,key=lambda r:r['nccCampaignId']):
        raise ValueError('단건 예산 캠페인 목록이 다릅니다')
    if campaigns is not None and roots!=campaigns: raise ValueError('단건 예산 캠페인 원천이 바뀌었습니다')
    ids=set()
    for raw in roots:
        if F.sanitize_record('campaign',raw,bound['customer_id'])!=raw or raw['nccCampaignId'] in ids: raise ValueError('단건 예산 캠페인 식별이 다릅니다')
        ids.add(raw['nccCampaignId'])
    if proof['root_fingerprint']!=fingerprint(roots): raise ValueError('단건 예산 캠페인 지문이 다릅니다')
    details=proof['details']; expected={r['nccCampaignId'] for r in roots if state(r)=='unknown'}
    if not isinstance(details,dict) or set(details)!=expected: raise ValueError('단건 예산 관측 범위가 미완결입니다')
    for raw in roots:
        identifier=raw['nccCampaignId']
        if identifier not in details: continue
        detail=detail_valid(details[identifier],raw,bound['customer_id'],complete=True)
        if (any(not generation<=moment(detail[k])<=checked for k in ('checked_at','verified_at'))
                or not timedelta(0)<=now-moment(detail['verified_at'])<=MAX_AGE):
            raise ValueError('단건 예산 관측 시각이 다릅니다')
    return proof


def make(observation,details,now):
    if (not isinstance(observation,Mapping) or type(observation.get('version')) is not int or observation.get('version')!=1
            or observation.get('status')!='ok' or observation.get('complete') is not True
            or observation.get('stale') is not False): return None
    try:
        cid=observation['customer_id']
        scope={k:observation[k] for k in SCOPE_KEYS if k!='account_key'}
        scope['account_key']=hashlib.sha256(str(cid).encode('ascii')).hexdigest()
        roots=deepcopy(observation['campaigns'])
        proof=dict(version=1,origin='campaign-detail-get',scope=scope,root_fingerprint=fingerprint(roots),
            campaigns=roots,details=deepcopy(details),checked_at=observation['checked_at'])
        return validate(proof,now)
    except (KeyError,ValueError,TypeError,OverflowError): return None


def from_observation(observation,now):
    if not isinstance(observation,Mapping): return None
    try:
        proof=observation.get('campaign_budget_proof')
        if make(observation,proof['details'],now)!=proof: return None
        return validate(proof,now)
    except (KeyError,ValueError,TypeError,OverflowError): return None


def resolved(raw,proof,now):
    result=state(raw)
    if result!='unknown' or proof is None: return result
    try:
        validate(proof,now)
        row=proof['details'][raw['nccCampaignId']]
        if raw not in proof['campaigns'] or row['settings'] is None: return 'unknown'
        return state(row['settings'])
    except (KeyError,ValueError,TypeError,OverflowError): return 'unknown'
