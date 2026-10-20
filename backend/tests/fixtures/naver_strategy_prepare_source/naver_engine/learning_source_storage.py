"""Immutable automatic evidence and separately reviewed, actor-scoped annotations.

Network-free. Capture failures preserve the enclosing collection/execution receipt.
"""
from copy import deepcopy
from datetime import date, timedelta
import json
import re
import uuid
from .experiments import moment

SCHEMA=(
    """CREATE TABLE IF NOT EXISTS naver_auto_learning_source (
        possibility_id INTEGER NOT NULL,account_key TEXT NOT NULL,asset_id TEXT NOT NULL,
        revision INTEGER NOT NULL,kind TEXT NOT NULL,source_id TEXT NOT NULL,material_fingerprint TEXT NOT NULL,
        captured_at TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(possibility_id,account_key,asset_id,revision))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_learning_annotation (
        possibility_id INTEGER NOT NULL,account_key TEXT NOT NULL,asset_id TEXT NOT NULL,version INTEGER NOT NULL,
        source_fingerprint TEXT NOT NULL,state TEXT NOT NULL,document_json TEXT NOT NULL,
        actor INTEGER NOT NULL,at TEXT NOT NULL,PRIMARY KEY(possibility_id,account_key,asset_id,version))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_learning_source_receipt (
        request_id TEXT PRIMARY KEY,actor INTEGER NOT NULL,possibility_id INTEGER NOT NULL,
        account_key TEXT NOT NULL,asset_id TEXT NOT NULL,body_hash TEXT NOT NULL,response_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_learning_source_pending (
        kind TEXT NOT NULL,source_id TEXT NOT NULL,attempts INTEGER NOT NULL,next_try_at TEXT NOT NULL,
        error_code TEXT NOT NULL,PRIMARY KEY(kind,source_id))""",
)
_AUTO=re.compile(r'auto-(?:exp|exec)-[0-9a-f]{32}\Z')
_UUID=re.compile(r'[0-9a-f]{32}\Z')

def _S():
    from . import store
    return store

def _LA():
    from . import learning_assets
    return learning_assets

def _hash(value):return _S().hashlib.sha256(_S()._json(value).encode()).hexdigest()

def _perf(source, *, now=None, lag_days=None):
    if not isinstance(source,dict):return None
    fields=source.get('fields') or {}
    start,end=source.get('period_start'),source.get('period_end')
    if not start or not end:return None
    return {'period_start':start,'period_end':end,'source_at':source.get('source_at'),
        'measurement_complete':source.get('status')=='ok' and source.get('configuration_verified') is True and all(fields.get(k) is not None for k in ('impCnt','clkCnt','salesAmt','ccnt','convAmt')),
        'lag_mature':type(lag_days)is int and lag_days>=0 and now is not None and source.get('source_at') is not None and moment(source['source_at']).date()>date.fromisoformat(end)+timedelta(days=lag_days) and now.date()>date.fromisoformat(end)+timedelta(days=lag_days),
        'conversion_definition':'platform' if source.get('conversion_definition') in ('platform','platform_all_conversions') else 'unknown',
        'value_basis':source.get('value_basis') or 'unknown',**{k:fields.get(v) for k,v in {'impressions':'impCnt','clicks':'clkCnt','spend':'salesAmt','conversions':'ccnt','conversion_value':'convAmt'}.items()}}

def _settings(arm):
    if not arm:return {}
    source=arm.get('settings') or {}
    result={k:source.get(v) for k,v in {'bid':'bidAmt','daily_budget':'dailyBudget'}.items() if source.get(v) is not None}
    if type(source.get('userLock'))is bool:result['enabled']=not source['userLock']
    return result

def _desired(manifest):
    payload=manifest.get('payload') or {}
    out={k:payload[k] for k in ('bid','daily_budget') if payload.get(k) is not None}
    if type(payload.get('user_lock'))is bool:out['enabled']=not payload['user_lock']
    return out

def _material(value):
    """Freshness polls do not amend immutable facts or withdraw a human review."""
    out=deepcopy(value)
    facts=out.get('evidence',{}).get('source_facts',{})
    facts.pop('recorded_at',None);facts.pop('source_at',None)
    for field in ('baseline','followup'):
        perf=facts.get(field)
        if isinstance(perf,dict):
            if 'control' in perf:
                for arm in perf.values():
                    if isinstance(arm,dict):arm.pop('source_at',None)
            else:perf.pop('source_at',None)
    return out

_RANDOMIZED_SOURCE_FIELDS=frozenset(('possibility_id account_key customer_id stage_revision protocol_version plan_version '
    'result_revision material_fingerprint recorded_at source_at period_start period_end measurement_lag_days '
    'experiment_spend_cap plan_goal minimum_impressions_per_block washout_hours result totals observation_scope registered_at').split())

def _randomized_parts(value,now):
    """Closed saved-result adapter. The formal store owns actual source authority.

    No dates, IDs, schedule rows or receipts are exposed by anonymous_evidence.
    A second material digest prevents an unrefreshed derivative from reviving a
    reviewed case when metrics/qualification change before capture retries finish.
    """
    LA=_LA();S=_S()
    from . import randomized_inference as RI
    LA._fields(value,_RANDOMIZED_SOURCE_FIELDS)
    LA._identity(value['possibility_id'],value['account_key'])
    for key in ('customer_id','protocol_version','plan_version','result_revision'):
        LA._integer(value[key],minimum=1,maximum=LA.MAX_VERSION)
    for key in ('stage_revision','material_fingerprint'):
        if not isinstance(value[key],str) or not re.fullmatch(r'[0-9a-f]{64}',value[key]):raise S.StoreRefused('조건부 결과 원천 판을 확인해 주세요')
    if value['source_at'] is None or not moment(value['source_at'])<=moment(value['recorded_at'])<=moment(now):raise S.StoreRefused('조건부 결과의 원천 시각을 확인해 주세요')
    start,end=LA._day(value['period_start']),LA._day(value['period_end'])
    if start>end:raise S.StoreRefused('조건부 결과의 관측 기간을 확인해 주세요')
    result=RI.normalize_result(value['result']);LA._fields(value['totals'],{'control','treatment'})
    controls={}
    for name in ('control','treatment'):
        raw=value['totals'][name];LA._fields(raw,{'impressions','clicks','spend'})
        controls[name]={'impressions':LA._integer(raw['impressions']),'clicks':LA._integer(raw['clicks']),
            'spend':LA._number(raw['spend']),'conversions':None,'conversion_value':None}
        if controls[name]['clicks']>controls[name]['impressions']:raise S.StoreRefused('CTR 관측 원천을 확인해 주세요')
    # Failed coverage is useful negative evidence, never a falsely complete case.
    incomplete={'SOURCE_INCOMPLETE','REQUIRED_METRIC_UNAVAILABLE','ZERO_IMPRESSIONS','INVALID_CTR_COUNTS',
        'PAIR_COUNT_MISMATCH','BLOCK_CALENDAR_MISMATCH','PAIR_ARMS_INVALID'}
    complete=not incomplete.intersection(result['reason_codes'])
    mature=complete and 'LAG_NOT_MATURE' not in result['reason_codes']
    evidence={'period_start':start,'period_end':end,'status':'stopped' if 'STOPPED_EARLY' in result['reason_codes'] else 'completed',
        'goal':'ctr','min_sample_per_arm':None,'baseline_rate':None,'mde_percent':None,'control_share':None,
        'preregistered_at':value['registered_at'],'randomized':False,'independent_units':False,'one_variable':True,
        'measurement_complete':complete,'lag_mature':mature,'allocation_valid':False,'conversion_definition':'unknown',**controls,
        'source_facts':{'source_status':'ok' if complete else 'partial','recorded_at':value['recorded_at'],'source_at':value['source_at'],
            'method':RI.METHOD,'declared_control_sample':None,'declared_treatment_sample':None,
            'measurement_lag_days':value['measurement_lag_days'],'experiment_spend_cap':value['experiment_spend_cap'],
            'control_daily_cap':None,'treatment_daily_cap':None,'metric_role':'primary' if value['plan_goal']=='ctr' else 'proxy',
            'plan_goal':value['plan_goal'],'value_basis':'unknown','baseline':None,'randomized_result':result,
            'observation_scope':deepcopy(value['observation_scope']),'washout_hours':value['washout_hours'],
            'minimum_impressions_per_block':value['minimum_impressions_per_block']}}
    material={k:deepcopy(v) for k,v in value.items() if k not in ('recorded_at','source_at')}
    origin={'source_kind':'randomized_experiment','customer_id':value['customer_id'],'stage_revision':value['stage_revision'],
        'result_revision':value['result_revision'],'result_fingerprint':value['material_fingerprint'],
        'source_content_fingerprint':_hash(material),'profile':{'conversion_definition':'unknown','value_basis':'unknown'}}
    return evidence,origin

class LearningSourceStorage:
    def _learning_source_row(self,pid,key,asset_id):
        row=self._conn.execute('SELECT revision,kind,source_id,material_fingerprint,captured_at,payload_json FROM naver_auto_learning_source WHERE possibility_id=? AND account_key=? AND asset_id=? ORDER BY revision DESC LIMIT 1',(pid,key,asset_id)).fetchone()
        return None if row is None else {'revision':row[0],'kind':row[1],'source_id':row[2],'fingerprint':row[3],'captured_at':row[4],'payload':json.loads(row[5])}

    def _learning_annotation(self,pid,key,asset_id):
        row=self._conn.execute('SELECT version,source_fingerprint,state,document_json,actor,at FROM naver_auto_learning_annotation WHERE possibility_id=? AND account_key=? AND asset_id=? ORDER BY version DESC LIMIT 1',(pid,key,asset_id)).fetchone()
        return None if row is None else dict(version=row[0],source_fingerprint=row[1],state=row[2],document=json.loads(row[3]),actor=row[4],at=row[5])

    def _learning_freeze_baseline(self,c,command_id,evidence):
        key='learning-auto-baseline:'+command_id
        if evidence is not None and _perf(evidence,now=moment(evidence['source_at']),lag_days=evidence.get('minimum_source_lag_days')) is not None:
            c.execute('INSERT OR IGNORE INTO naver_auto_meta(key,value) VALUES(?,?)',(key,_S()._json(_perf(evidence,now=moment(evidence['source_at']),lag_days=evidence.get('minimum_source_lag_days')))))

    def _learning_capture_event(self,c,kind,source_id,now,*,retry=False):
        """A failed derivative must not erase a known execution or collection result."""
        at=_S()._kst_text(now,'자동 학습 기록')
        c.execute('SAVEPOINT learning_source_capture')
        try:
            self._learning_capture_source(c,kind,source_id,now)
            c.execute("UPDATE naver_auto_learning_source_pending SET attempts=-1,error_code='CAPTURED' WHERE kind=? AND source_id=?",(kind,source_id))
            c.execute('RELEASE SAVEPOINT learning_source_capture');return True
        except Exception:
            c.execute('ROLLBACK TO SAVEPOINT learning_source_capture');c.execute('RELEASE SAVEPOINT learning_source_capture')
            try:
                if retry:
                    c.execute("INSERT INTO naver_auto_learning_source_pending VALUES(?,?,0,?,'CAPTURE_UNAVAILABLE') ON CONFLICT(kind,source_id) DO UPDATE SET next_try_at=excluded.next_try_at,error_code=excluded.error_code",(kind,source_id,at))
                else:
                    c.execute("INSERT INTO naver_auto_learning_source_pending VALUES(?,?,0,?,'CAPTURE_UNAVAILABLE') ON CONFLICT(kind,source_id) DO UPDATE SET attempts=0,next_try_at=excluded.next_try_at,error_code=excluded.error_code",(kind,source_id,at))
            except Exception:
                # The upstream operation receipt is authoritative even if its derivative table fails.
                pass
            return False

    def refresh_learning_sources(self,now,limit=10):
        self._need_writer();self._not_future(now,'학습 재기록')
        if type(limit)is not int or not 1<=limit<=10:raise _S().StoreRefused('학습 재기록 상한을 확인해 주세요')
        at=_S()._kst_text(now,'학습 재기록');rows=self._conn.execute('SELECT kind,source_id,attempts FROM naver_auto_learning_source_pending WHERE next_try_at<=? AND attempts>=0 AND attempts<5 ORDER BY next_try_at,source_id LIMIT ?',(at,limit)).fetchall();out={'captured':0,'pending':0}
        for kind,sid,attempts in rows:
            with self._tx() as c:
                if self._learning_capture_event(c,kind,sid,now,retry=True):out['captured']+=1
                else:
                    c.execute('UPDATE naver_auto_learning_source_pending SET attempts=?,next_try_at=? WHERE kind=? AND source_id=?',(attempts+1,(now+timedelta(minutes=min(60,2**attempts))).isoformat(),kind,sid));out['pending']+=1
        return out

    def _learning_cached_followup(self,command,confirmed_at,now):
        if not command or command['approval_ref']['kind']!='mandate' or not confirmed_at:return None,None,False
        mid,tk,epoch=command['approval_ref']['id'],command['target_key'],command['config_epoch']+1
        row=self._conn.execute("SELECT period_start,period_end,status,checked_at,payload_json FROM naver_auto_execution_evidence WHERE mandate_id=? AND target_key=? AND config_epoch=? AND period_start>? ORDER BY period_end DESC,checked_at DESC LIMIT 1",(mid,tk,epoch,moment(confirmed_at).date().isoformat())).fetchone()
        if row is None:return None,None,False
        perf=None
        if row[2]=='ok':
            raw=json.loads(row[4]);candidate=_perf(raw,now=moment(row[3]),lag_days=raw.get('minimum_source_lag_days'))
            if candidate and candidate['measurement_complete'] and candidate['lag_mature']:perf=candidate
        ref=None if perf is None else {'mandate_id':mid,'target_key':tk,'config_epoch':epoch,'period_start':row[0],'period_end':row[1],'fingerprint':_hash({k:v for k,v in perf.items() if k!='source_at'})}
        return perf,ref,True

    def _learning_capture_source(self,c,kind,sid,now):
        LA=_LA();S=_S();at=S._kst_text(now,'자동 학습 기록')
        if kind=='execution_result':
            h=self._execution_head(sid)
            if not h or h['resource_type']!='command':return
            pid,key=h['possibility_id'],h['account_key'];asset_id='auto-exec-'+sid;command=h['command'];manifest=h['document']
            if manifest.get('action') not in LA.AUTO_ACTIONS:return
            plan=(self._execution_head(command['approval_ref']['id']) or {}).get('binding',{}).get('plan') if command and command['approval_ref']['kind']=='mandate' else self.automation_plan(pid,key)['plan']
            frozen=c.execute('SELECT value FROM naver_auto_meta WHERE key=?',('learning-auto-plan:'+sid,)).fetchone()
            plan=json.loads(frozen[0]) if frozen else plan or {};pv=command['plan_version'] if command else self.automation_plan(pid,key)['version']
            op=c.execute('SELECT dispatched_at,confirmed_at,outcome_json,readback_json FROM naver_auto_execution_operation WHERE command_id=?',(sid,)).fetchone()
            readback=json.loads(op[3]) if op and op[3] else {};confirmed=h['state']=='confirmed' and readback.get('state')=='confirmed';source_status='confirmed' if confirmed else 'planned' if h['state']=='draft' else h['state']
            if source_status=='dispatched' and op and op[2] and json.loads(op[2]).get('state')=='accepted':source_status='accepted'
            baseline=c.execute('SELECT value FROM naver_auto_meta WHERE key=?',('learning-auto-baseline:'+sid,)).fetchone();followup=c.execute('SELECT value FROM naver_auto_meta WHERE key=?',('learning-auto-followup:'+sid,)).fetchone()
            baseline_value=json.loads(baseline[0]) if baseline else None;followup_value=json.loads(followup[0]) if followup else None
            cached_followup,followup_ref,has_cached_followup=self._learning_cached_followup(command,op[1] if confirmed else None,now)
            if has_cached_followup:followup_value=cached_followup
            measured=followup_value or baseline_value
            profile={k:measured[k] for k in ('conversion_definition','value_basis')} if measured else {'conversion_definition':'unknown','value_basis':'unknown'}
            before=_settings(command['target']) if command else {};after=_settings(readback.get('target')) if confirmed else None
            changed={k for k in set(before)|set(after or {}) if before.get(k)!=(after or {}).get(k)}
            evidence={'execution':'applied' if confirmed else 'planned' if source_status in ('planned','approved','queued') else 'dispatched' if source_status=='accepted' else source_status,'changed_variable':next(iter(changed)) if len(changed)==1 else 'multiple','before':before,'after':after,'observed_at':op[1] if confirmed else None,
                'source_facts':{'source_status':source_status,'recorded_at':max(h['updated_at'],followup_value['source_at']) if followup_value else h['updated_at'],'source_at':op[1] if confirmed else None,'decided_at':command['created_at'] if command else None,'dispatched_at':op[0] if op else None,'confirmed_at':op[1] if confirmed else None,'action':manifest.get('action'),'desired':_desired(manifest),'profile':profile,'baseline':baseline_value,'followup':followup_value}}
            title='자동 운영 원장';protocol_version=None;origin={'customer_id':h['customer_id'],'stage_revision':(command or {}).get('scope',{}).get('stage_revision'),'event_version':h['version'],'profile':profile,'document':manifest,'followup_ref':followup_ref}
            document_kind='setting_change'
        elif kind=='randomized_experiment':
            raw=self.get_randomized_learning_source(sid,now)
            if raw is None:raise S.StoreRefused('현재 조건부 결과 원천을 다시 확인해 주세요')
            evidence,origin=_randomized_parts(raw,now)
            pid,key=raw['possibility_id'],raw['account_key'];asset_id='auto-exp-'+sid
            protocol_version,pv=raw['protocol_version'],raw['plan_version']
            title='과거 무작위 시간 블록 CTR 조건부 결과';document_kind='experiment'
            # Keep the existing automatic experiment kind/namespace and never
            # overwrite a distinct legacy experiment that happens to share an ID.
            existing=self._learning_source_row(pid,key,asset_id)
            if existing and existing['payload']['origin'].get('source_kind')!='randomized_experiment':raise S.StoreRefused('다른 실험 원천에 사용한 자산 식별자입니다')
            kind='experiment_observation'
        elif kind=='experiment_observation':
            scoped=c.execute('SELECT possibility_id,account_key FROM naver_auto_experiment WHERE experiment_id=?',(sid,)).fetchone()
            h=self._experiment_head(sid,scoped[0],scoped[1]) if scoped else None
            if not h:return
            pid,key=h['possibility_id'],h['account_key'];asset_id='auto-exp-'+sid;protocol_version=h['protocol_version'];binding=h['binding']
            row=c.execute('SELECT revision,status,checked_at,material_hash,payload_json FROM naver_auto_experiment_observation WHERE experiment_id=? AND protocol_version=? ORDER BY revision DESC LIMIT 1',(sid,protocol_version)).fetchone()
            if not row or not binding:return
            snapshot=json.loads(row[4]) if row[4] else None;doc=h['document'];criteria=binding['criteria'];pv=binding['plan_version'];profile={'conversion_definition':'platform_all_conversions','value_basis':'platform_conversion_value'}
            exploratory=doc.get('method')=='exploratory_paired_day_hac_v1'
            if exploratory:
                latest=c.execute('SELECT status FROM naver_auto_experiment_job WHERE experiment_id=? ORDER BY checked_at DESC,rowid DESC LIMIT 1',(sid,)).fetchone()
                # A saved daily-progress poll has no new outcome. In particular,
                # capture retries must not turn a source_wait into a fresh case.
                if latest and latest[0]=='source_wait':return
                if not latest or latest[0] not in ('ok','partial') or latest[0]!=row[1]:snapshot=None
            def arm_perf(name):
                arm=(snapshot or {}).get('arms',{}).get(name)
                return _perf({'status':(snapshot or {}).get('status'),'configuration_verified':(snapshot or {}).get('configuration_verified'),'fields':arm['fields'],'period_start':doc['period_start'],'period_end':doc['period_end'],'source_at':arm['source_at'],'minimum_source_lag_days':doc['measurement_lag_days'],'conversion_definition':'platform_all_conversions','value_basis':'platform_conversion_value'},now=now,lag_days=doc['measurement_lag_days']) if arm else None
            metric_names=('impressions','clicks','spend','conversions','conversion_value')
            base={}
            for name in ('control','treatment'):
                b=binding['baseline'].get(name);base[name]=_perf({'status':'ok' if b and b.get('complete') and not b.get('missing') else 'partial','configuration_verified':True,'fields':b.get('fields',{}) if b else {},'period_start':b.get('period_start') if b else None,'period_end':b.get('period_end') if b else None,'source_at':b.get('source_at') if b else None,'minimum_source_lag_days':None,'conversion_definition':'platform_all_conversions','value_basis':'platform_conversion_value'},now=now,lag_days=doc['measurement_lag_days'])
            controls={n:{k:(arm_perf(n) or {}).get(k) for k in metric_names} for n in ('control','treatment')}
            evidence={'period_start':doc['period_start'],'period_end':doc['period_end'],'status':'completed' if row[1]=='ok' else 'running','goal':doc['goal'],'min_sample_per_arm':doc['declared_control_sample'] if doc['declared_control_sample']==doc['declared_treatment_sample'] else None,'baseline_rate':None,'mde_percent':doc['mde_percent'],'control_share':doc['sample_share'],'preregistered_at':h['approved_at'] if doc['method']=='two_proportion_fixed_horizon_95_80_v1' or exploratory else None,'randomized':False,'independent_units':False,'one_variable':bool(doc['single_variable']),'measurement_complete':bool(snapshot and snapshot['status']=='ok'),'lag_mature':all((arm_perf(name) or {}).get('lag_mature',False) for name in ('control','treatment')),'allocation_valid':False,'conversion_definition':profile['conversion_definition'],**controls,
                'source_facts':{'source_status':row[1] if row[1] in ('ok','partial','pending','failed','stale','unavailable','superseded') else 'failed','recorded_at':row[2],'source_at':min((a['source_at'] for a in (snapshot or {}).get('arms',{}).values() if a and a.get('source_at')),default=None),'method':doc['method'],'declared_control_sample':doc['declared_control_sample'],'declared_treatment_sample':doc['declared_treatment_sample'],'measurement_lag_days':doc['measurement_lag_days'],'experiment_spend_cap':doc['experiment_spend_cap'],'control_daily_cap':doc['control_daily_cap'],'treatment_daily_cap':doc['treatment_daily_cap'],'metric_role':criteria.get('metric_role'),'plan_goal':criteria.get('plan_goal'),'value_basis':'platform_conversion_value','baseline':base}}
            if exploratory:
                from . import experiments as X
                assessment=X.assess(binding,snapshot,now,approved_at=h['approved_at'],current_plan=self.automation_plan(pid,key),
                    current_source_fingerprint=binding['source_fingerprint'])
                evidence['source_facts']['exploratory_diagnostic']=deepcopy(assessment['observational_decision'])
            title='자동 실험 관측';origin={'customer_id':h['customer_id'],'stage_revision':h['stage_revision'],'observation_revision':row[0],'observation_hash':row[3],'profile':profile,'document':doc};document_kind='experiment'
        else:raise S.StoreRefused('자동 학습 원천 종류를 확인해 주세요')
        material=_hash(_material({'kind':kind,'id':sid,'protocol_version':protocol_version,'plan_version':pv,'evidence':evidence,'origin':origin}))
        old=self._learning_source_row(pid,key,asset_id)
        if old and ('randomized_experiment' in (origin.get('source_kind'),old['payload']['origin'].get('source_kind'))
                and origin.get('source_kind')!=old['payload']['origin'].get('source_kind')):
            raise S.StoreRefused('다른 실험 원천에 사용한 자산 식별자입니다')
        if old and old['fingerprint']==material:return
        revision=old['revision']+1 if old else 1
        source={'kind':kind,'id':sid,'revision':revision,'protocol_version':protocol_version,'plan_version':pv,'material_fingerprint':material}
        document=LA.auto_document(document_kind,title=title,evidence=evidence,source=source)
        c.execute('INSERT INTO naver_auto_learning_source VALUES(?,?,?,?,?,?,?,?,?)',(pid,key,asset_id,revision,kind,sid,material,at,S._json({'origin':origin,'source':source,'document':document})))
        repository=S.LearningAssetStorage(c);current=repository.get_asset(pid,key,asset_id)
        repository.record(pid,key,None,at,current['version'] if current else 0,asset_id,document,action='save')

    def _learning_source_current(self,pid,key,source,now,allowed_pairs,cache=None):
        if (pid,key) not in set(allowed_pairs):return False
        origin=source['payload']['origin'];ref=source['payload']['source']
        if origin.get('source_kind')=='randomized_experiment':
            try:
                raw=self.get_randomized_learning_source(source['source_id'],now)
                if raw is None or (raw['possibility_id'],raw['account_key'])!=(pid,key):return False
                _,current=_randomized_parts(raw,now)
                return (current==origin and raw['protocol_version']==ref['protocol_version'] and raw['plan_version']==ref['plan_version'])
            except (ValueError,TypeError,KeyError,_S().StoreRefused):return False
        if source['kind']=='execution_result':
            head=self._execution_head(source['source_id'],pid,key)
            if not head or head['customer_id']!=origin['customer_id'] or head['version']!=origin['event_version']:return False
            if origin.get('followup_ref'):
                followup=origin['followup_ref'];row=self._conn.execute('SELECT status,checked_at,payload_json FROM naver_auto_execution_evidence WHERE mandate_id=? AND target_key=? AND config_epoch=? AND period_start=? AND period_end=?',(followup['mandate_id'],followup['target_key'],followup['config_epoch'],followup['period_start'],followup['period_end'])).fetchone()
                if not row or row[0]!='ok':return False
                raw=json.loads(row[2]);perf=_perf(raw,now=moment(row[1]),lag_days=raw.get('minimum_source_lag_days'))
                if not perf or _hash({k:v for k,v in perf.items() if k!='source_at'})!=followup['fingerprint']:return False
            return True
        head=self._experiment_head(source['source_id'],pid,key)
        if not head or head['state']!='approved' or head['protocol_version']!=ref['protocol_version']:return False
        latest=self._conn.execute('SELECT status FROM naver_auto_experiment_job WHERE experiment_id=? ORDER BY checked_at DESC,rowid DESC LIMIT 1',(source['source_id'],)).fetchone()
        row=self._conn.execute('SELECT revision,material_hash,status FROM naver_auto_experiment_observation WHERE experiment_id=? AND protocol_version=? ORDER BY revision DESC LIMIT 1',(source['source_id'],ref['protocol_version'])).fetchone()
        if not latest or latest[0] not in ('ok','partial') or not row or row[0]!=origin['observation_revision'] or row[1]!=origin['observation_hash'] or row[2]!=latest[0]:return False
        if head['document'].get('method')=='exploratory_paired_day_hac_v1':
            from . import experiments_reads as ER, experiments_store as ES
            try:
                # A current budget-partial checkpoint cannot revive a previous
                # partial result, even though both have the same status label.
                job=self._conn.execute('SELECT job_json FROM naver_auto_experiment_job WHERE experiment_id=? ORDER BY checked_at DESC,rowid DESC LIMIT 1',(source['source_id'],)).fetchone()
                job=json.loads(job[0])
                current=ER.validate_progress(self.experiments_progress(job),job,now=now)
                saved=self._conn.execute('SELECT payload_json FROM naver_auto_experiment_observation WHERE experiment_id=? AND protocol_version=? AND revision=?',(source['source_id'],ref['protocol_version'],row[0])).fetchone()
                saved=json.loads(saved[0]) if saved and saved[0] else None
                if current is None or ES.observation_material(current,job=job,now=now)!=ES.observation_material(saved,job=job,now=now):return False
            except (ValueError,TypeError,KeyError,OverflowError,RecursionError):return False
        from . import experiments as X
        cache={} if cache is None else cache;pair=(pid,key)
        if pair not in cache:
            obs=self.setup_observation(head['customer_id'],now)
            cache[pair]=(self.automation_plan(pid,key),X.candidate_catalog(obs,possibility_id=pid,customer_id=head['customer_id'],account_key=key))
        try:return X.current_binding(head['binding'],cache[pair][0],cache[pair][1],now) is True
        except (ValueError,TypeError,KeyError):return False

    def learning_source_eligibility(self,record,now,allowed_pairs,cache=None):
        ref=record.get('document',{}).get('source_refs',{}).get('auto_source')
        if ref is None:return None
        identity=record['identity'];pid,key=identity['possibility_id'],identity['account_key'];source=self._learning_source_row(pid,key,record['asset_id']);annotation=self._learning_annotation(pid,key,record['asset_id'])
        if not source or not annotation or annotation['state']!='reviewed' or annotation['source_fingerprint']!=source['fingerprint'] or source['payload']['source']!=ref or record['state']!='reviewed' or not self._learning_source_current(pid,key,source,now,allowed_pairs,cache):return None
        doc=annotation['document']
        return {'annotation_version':annotation['version'],'source_fingerprint':source['fingerprint'],'metadata':deepcopy(doc['metadata']),'profile':deepcopy(source['payload']['origin']['profile']),'source_summary':_LA().source_summary(record['document']),'lesson_codes':list(doc['lesson_codes']),'confounder_codes':list(doc['confounder_codes'])}

    def learning_source_reference_current(self,ref,now,allowed_pairs,cache=None):
        record=_S().LearningAssetStorage(self._conn).get_asset(ref['possibility_id'],ref['account_key'],ref['asset_id'])
        if not record or record['version']!=ref['version'] or record['state']!='reviewed':return False
        if 'auto_source' not in record['document']['source_refs']:return True
        eligible=self.learning_source_eligibility(record,now,allowed_pairs,cache)
        return bool(eligible and eligible['annotation_version']==ref.get('annotation_version') and eligible['source_fingerprint']==ref.get('source_fingerprint'))

    def learning_source_item(self,item,now,allowed_pairs,*,can_edit=False):
        if 'auto_source' not in item['document'].get('source_refs',{}):return item
        out=deepcopy(item);pid,key=item['identity']['possibility_id'],item['identity']['account_key'];source=self._learning_source_row(pid,key,item['asset_id']);annotation=self._learning_annotation(pid,key,item['asset_id']);current=bool(source and self._learning_source_current(pid,key,source,now,allowed_pairs))
        doc=annotation['document'] if annotation else {'metadata':dict.fromkeys(_LA().METADATA_ENUMS),'lesson_codes':[],'confounder_codes':[],'private_comment':''}
        reviewed=bool(annotation and annotation['state']=='reviewed' and current and annotation['source_fingerprint']==source['fingerprint'] and item['state']=='reviewed')
        out['source_annotation']={'version':annotation['version'] if annotation else 0,'state':annotation['state'] if annotation else 'empty','document':deepcopy(doc),'source_revision':source['revision'] if source else 0,'source_fingerprint':source['fingerprint'] if source else None,'current':current,'hold_reasons':[] if reviewed else [{'code':'SOURCE_CHANGED' if not current else 'REVIEW_REQUIRED','message':'현재 원천과 주석 검수를 확인해 주세요.'}],'can_edit':can_edit and current,'can_review':can_edit and current and bool(annotation and annotation['state']=='draft' and annotation['source_fingerprint']==source['fingerprint'] and doc['lesson_codes'] and all(v is not None for v in doc['metadata'].values())),'can_reject':can_edit and bool(annotation and annotation['state'] in ('draft','reviewed'))}
        out['source_summary']=_LA().source_summary(item['document']);return out

    def learning_source_receipt(self,pid,key,asset_id,actor,request_id):
        if not isinstance(request_id,str) or not _UUID.fullmatch(request_id):raise _S().StoreRefused('학습 요청 식별자를 확인해 주세요')
        row=self._conn.execute('SELECT actor,possibility_id,account_key,asset_id,length(response_json),substr(response_json,1,1025) FROM naver_auto_learning_source_receipt WHERE request_id=?',(request_id,)).fetchone()
        if row is None:return None
        if tuple(row[:4])!=(actor,pid,key,asset_id):
            from app.naver_auto import scope as SC
            raise SC.ClientNotVisible()
        try:
            out=json.loads(row[5]);item=_S().LearningAssetStorage(self._conn).get_asset(pid,key,asset_id);ann=self._learning_annotation(pid,key,asset_id)
            if row[4]>1024 or set(out)!={'asset_id','source_version','annotation_version','request_id'} or out['asset_id']!=asset_id or out['request_id']!=request_id or any(type(out[k])is not int or not 1<=out[k]<2**53 for k in ('source_version','annotation_version')) or not item or item['version']<out['source_version'] or not ann or ann['version']<out['annotation_version']:raise ValueError()
            return out
        except (ValueError,TypeError,KeyError):raise _S().StoreRefused('학습 검수 영수증을 다시 확인해 주세요') from None

    def learning_source_projection(self,pid,key,asset_id,now,allowed_pairs,*,can_edit=False):
        if not isinstance(asset_id,str) or not _AUTO.fullmatch(asset_id):raise _S().StoreRefused('자동 학습 자산을 확인해 주세요')
        item=_S().LearningAssetStorage(self._conn).get_asset(pid,key,asset_id)
        if not item or 'auto_source' not in item['document']['source_refs']:
            from app.naver_auto import scope as SC
            raise SC.ClientNotVisible()
        return self.learning_source_item(item,now,allowed_pairs,can_edit=can_edit)

    def learning_source_pending(self,pid,key):
        rows=self._conn.execute("""SELECT p.attempts,p.error_code FROM naver_auto_learning_source_pending p
            LEFT JOIN naver_auto_execution_resource e ON p.kind='execution_result' AND e.resource_id=p.source_id
            LEFT JOIN naver_auto_experiment x ON p.kind='experiment_observation' AND x.experiment_id=p.source_id
            WHERE (e.possibility_id=? AND e.account_key=?) OR (x.possibility_id=? AND x.account_key=?)""",(pid,key,pid,key)).fetchall()
        if self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='naver_randomized_experiment'").fetchone():
            rows+=self._conn.execute("SELECT p.attempts,p.error_code FROM naver_auto_learning_source_pending p JOIN naver_randomized_experiment r ON p.kind='randomized_experiment' AND p.source_id=r.experiment_id WHERE r.possibility_id=? AND r.account_key=?",(pid,key)).fetchall()
        return {'pending':sum(0<=r[0]<5 for r in rows),'exhausted':sum(r[0]>=5 for r in rows),
            'reason_codes':['CAPTURE_RETRY_EXHAUSTED'] if any(r[0]>=5 for r in rows) else ['CAPTURE_UNAVAILABLE'] if any(r[0]>=0 for r in rows) else []}

    def record_learning_source_annotation(self,pid,key,asset_id,actor,now,*,expected_source_version,expected_annotation_version,request_id,action,document=None):
        S=_S();LA=_LA();self._need_writer();self._not_future(now,'학습 원천 검수')
        if not isinstance(asset_id,str) or not _AUTO.fullmatch(asset_id) or not isinstance(request_id,str) or not _UUID.fullmatch(request_id) or action not in ('save','review','reject') or any(type(v)is not int or not 0<=v<2**53 for v in (expected_source_version,expected_annotation_version)) or action!='save' and document is not None:raise S.StoreRefused('학습 원천 검수 범위를 확인해 주세요')
        clean=LA.annotation_document(document) if action=='save' else None;body_hash=_hash({'asset_id':asset_id,'source_version':expected_source_version,'annotation_version':expected_annotation_version,'action':action,'document':clean});at=S._kst_text(now,'학습 원천 검수')
        with self._tx() as c:
            ctx,scope=self._learning_actor(pid,key,actor,now)
            from . import automation_views as AV,report_views as RV,approval_documents as D,handles as H
            companies,pairs=AV.context(ctx,self,scope);allowed=[(p,RV.account_key(cid)) for cid,p in pairs.items() if p in companies and cid in ctx.accounts and H.stage_key(companies[p]['stage']) in D.EDIT_STAGES]
            receipt=c.execute('SELECT actor,possibility_id,account_key,asset_id,body_hash,response_json FROM naver_auto_learning_source_receipt WHERE request_id=?',(request_id,)).fetchone()
            if receipt:
                if tuple(receipt[:5])!=(actor,pid,key,asset_id,body_hash):raise S.StoreRefused('다른 학습 요청에 사용한 식별자입니다')
                return json.loads(receipt[5])
            repository=S.LearningAssetStorage(c);item=repository.get_asset(pid,key,asset_id);source=self._learning_source_row(pid,key,asset_id);old=self._learning_annotation(pid,key,asset_id)
            if not item or not source or item['version']!=expected_source_version or (old['version'] if old else 0)!=expected_annotation_version:raise S.StoreRefused('원천 또는 주석 판이 변경되었습니다. 다시 확인해 주세요')
            if action in ('save','review') and not self._learning_source_current(pid,key,source,now,allowed):raise S.StoreRefused('현재 원천이 변경되어 검수할 수 없습니다')
            if action!='save':
                if old is None or action=='review' and old['state']!='draft' or action=='reject' and old['state'] not in ('draft','reviewed'):raise S.StoreRefused('검수할 주석 초안을 먼저 저장해 주세요')
                clean=old['document']
            if action=='review' and (old['source_fingerprint']!=source['fingerprint'] or not clean['lesson_codes'] or any(v is None for v in clean['metadata'].values())):raise S.StoreRefused('현재 원천과 분류·교훈을 확인해 주세요')
            if action=='save':saved=repository.record(pid,key,None,at,item['version'],asset_id,item['document'],action='save')
            else:
                if item['state']!='draft':item=repository.record(pid,key,None,at,item['version'],asset_id,item['document'],action='save')
                saved=repository.record(pid,key,actor,at,item['version'],asset_id,action=action)
            version=expected_annotation_version+1;state={'save':'draft','review':'reviewed','reject':'rejected'}[action]
            c.execute('INSERT INTO naver_auto_learning_annotation VALUES(?,?,?,?,?,?,?,?,?)',(pid,key,asset_id,version,source['fingerprint'],state,S._json(clean),actor,at))
            out={'asset_id':asset_id,'source_version':saved['version'],'annotation_version':version,'request_id':request_id}
            c.execute('INSERT INTO naver_auto_learning_source_receipt VALUES(?,?,?,?,?,?,?)',(request_id,actor,pid,key,asset_id,body_hash,S._json(out)));return out

    def _learning_attach_followup(self,c,mandate_id,target_key,epoch,evidence,now):
        c.execute('SAVEPOINT learning_followup_capture')
        try:
            self._learning_attach_followup_inner(c,mandate_id,target_key,epoch,evidence,now)
            c.execute('RELEASE SAVEPOINT learning_followup_capture')
        except Exception:
            c.execute('ROLLBACK TO SAVEPOINT learning_followup_capture');c.execute('RELEASE SAVEPOINT learning_followup_capture')
            # Replaying the derivative from this frozen evidence is network-free.
            row=c.execute("SELECT r.resource_id FROM naver_auto_execution_resource r WHERE r.state='confirmed' AND json_extract(r.command_json,'$.approval_ref.id')=? AND json_extract(r.command_json,'$.target_key')=? AND json_extract(r.command_json,'$.config_epoch')=? ORDER BY r.updated_at DESC LIMIT 1",(mandate_id,target_key,epoch-1)).fetchone()
            if row:
                try:c.execute("INSERT INTO naver_auto_learning_source_pending VALUES('execution_result',?,0,?,'CAPTURE_UNAVAILABLE') ON CONFLICT(kind,source_id) DO UPDATE SET attempts=0,next_try_at=excluded.next_try_at,error_code=excluded.error_code",(row[0],_S()._kst_text(now,'학습 후속 기록')))
                except Exception:pass

    def _learning_attach_followup_inner(self,c,mandate_id,target_key,epoch,evidence,now):
        perf=_perf(evidence,now=now,lag_days=evidence.get('minimum_source_lag_days')) if evidence else None
        if evidence is not None and (not perf or not perf['measurement_complete'] or not perf['lag_mature']):return
        row=c.execute("SELECT r.resource_id,o.confirmed_at FROM naver_auto_execution_resource r JOIN naver_auto_execution_operation o ON o.command_id=r.resource_id WHERE r.state='confirmed' AND json_extract(r.command_json,'$.approval_ref.id')=? AND json_extract(r.command_json,'$.target_key')=? AND json_extract(r.command_json,'$.config_epoch')=? ORDER BY o.confirmed_at DESC LIMIT 1",(mandate_id,target_key,epoch-1)).fetchone()
        if not row or perf and perf['period_start']<=moment(row[1]).date().isoformat():return
        if perf:c.execute('INSERT INTO naver_auto_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('learning-auto-followup:'+row[0],_S()._json(perf)))
        self._learning_capture_event(c,'execution_result',row[0],now)
