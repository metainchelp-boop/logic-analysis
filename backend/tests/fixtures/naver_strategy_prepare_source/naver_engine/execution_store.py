"""Advertiser-approved execution ledger. Network operations never run in a DB transaction."""
from copy import deepcopy
from datetime import date, timedelta
import json
import math
import re
import uuid
from .experiments import moment

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_resource (
        resource_id TEXT PRIMARY KEY,resource_type TEXT NOT NULL,possibility_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,account_key TEXT NOT NULL,version INTEGER NOT NULL,state TEXT NOT NULL,
        document_json TEXT NOT NULL,binding_json TEXT,command_json TEXT,author INTEGER NOT NULL,
        approved_by INTEGER,approved_at TEXT,updated_at TEXT NOT NULL,next_evaluation_at TEXT,
        reasons_json TEXT NOT NULL DEFAULT '[]')""",
    "CREATE INDEX IF NOT EXISTS naver_auto_execution_scope ON naver_auto_execution_resource(possibility_id,account_key,resource_type,updated_at)",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_history (
        resource_id TEXT NOT NULL,version INTEGER NOT NULL,payload_json TEXT NOT NULL,
        PRIMARY KEY(resource_id,version))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_receipt (
        request_id TEXT PRIMARY KEY,actor INTEGER NOT NULL,possibility_id INTEGER NOT NULL,
        account_key TEXT NOT NULL,body_hash TEXT NOT NULL,response_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_operation (
        command_id TEXT PRIMARY KEY,status TEXT NOT NULL,lease_token TEXT,lease_until TEXT,
        dispatched_at TEXT,confirmed_at TEXT,next_try_at TEXT NOT NULL,
        outcome_json TEXT,readback_json TEXT,error_code TEXT,reconcile_actor INTEGER)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_event (
        event_id INTEGER PRIMARY KEY,resource_id TEXT NOT NULL,at TEXT NOT NULL,
        code TEXT NOT NULL,payload_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_evaluation (
        mandate_id TEXT NOT NULL,evaluation_key TEXT NOT NULL,target_key TEXT NOT NULL,
        evaluated_at TEXT NOT NULL,decision_json TEXT NOT NULL,command_id TEXT,
        PRIMARY KEY(mandate_id,evaluation_key))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_epoch (
        mandate_id TEXT NOT NULL,target_key TEXT NOT NULL,epoch INTEGER NOT NULL,
        target_json TEXT NOT NULL,applied_at TEXT NOT NULL,command_id TEXT NOT NULL,
        PRIMARY KEY(mandate_id,target_key))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_reservation (
        command_id TEXT PRIMARY KEY,customer_id INTEGER NOT NULL,target_key TEXT,
        action TEXT NOT NULL,status TEXT NOT NULL,at TEXT NOT NULL,before_json TEXT,after_json TEXT,target_identity TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_attempt (
        command_id TEXT NOT NULL,lease_token TEXT NOT NULL,command_hash TEXT NOT NULL,
        dispatched_at TEXT NOT NULL,outcome_json TEXT,PRIMARY KEY(command_id,lease_token))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_spend (
        possibility_id INTEGER NOT NULL,account_key TEXT NOT NULL,customer_id INTEGER NOT NULL,
        stage_revision TEXT NOT NULL,plan_version INTEGER NOT NULL,period_start TEXT NOT NULL,
        status TEXT NOT NULL,checked_at TEXT NOT NULL,payload_json TEXT NOT NULL,
        PRIMARY KEY(possibility_id,account_key,period_start))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_evidence (
        mandate_id TEXT NOT NULL,target_key TEXT NOT NULL,config_epoch INTEGER NOT NULL,
        period_start TEXT NOT NULL,period_end TEXT NOT NULL,status TEXT NOT NULL,checked_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,PRIMARY KEY(mandate_id,target_key,config_epoch,period_start,period_end))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_execution_channels (
        customer_id INTEGER NOT NULL,possibility_id INTEGER NOT NULL,account_key TEXT NOT NULL,stage_revision TEXT NOT NULL,
        status TEXT NOT NULL,checked_at TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(possibility_id,account_key))""",
)
_UUID = re.compile(r"[0-9a-f]{32}\Z")
_KEY = re.compile(r"[0-9a-f]{64}\Z")
_TERMINAL = frozenset({'confirmed','rejected','cancelled','stopped'})


def _S():
    from . import store
    return store


def _E():
    from . import execution_commands
    return execution_commands


def _decode(row):
    if row is None:return None
    out=dict(row)
    for name in ('document','binding','command','reasons'):
        raw=out.pop(name+'_json');out[name]=json.loads(raw) if raw else None
    return out


def _reason(code):
    messages={'APPROVAL_REQUIRED':'개별 실행 승인이 필요합니다.', 'OPERATOR_DISABLED':'운영자 쓰기 설정이 꺼져 있습니다.',
        'SOURCE_CHANGED':'현재 권한·운영 기준·대상 설정을 다시 확인해야 합니다.',
        'UNKNOWN':'송신 결과가 불명확합니다. 자동 재송신하지 않고 정확한 대상만 재조회합니다.',
        'UNIT_UNVERIFIED':'계정 지출과 광고 예산의 부가세·단위 정합이 확인되지 않았습니다.',
        'STOPPED':'자체 실행 큐를 중지했습니다. 플랫폼 광고 중단 여부는 별도 반영 확인이 필요합니다.'}
    return {'code':code,'message':messages.get(code,'실행 조건을 확인해야 합니다.'),'next_action':'현재 원천과 개별 승인 범위를 확인해 주세요.'}


class ExecutionStorage:
    def _execution_head(self,rid,pid=None,key=None):
        if not rid:return None
        sql='SELECT * FROM naver_auto_execution_resource WHERE resource_id=?';args=[rid]
        if pid is not None:sql+=' AND possibility_id=? AND account_key=?';args.extend((pid,key))
        return _decode(next(iter(_S()._rows(self._conn.execute(sql,args))),None))

    def _execution_context(self,pid,key,actor,now,*,stop=False):
        from app.naver_auto import scope as SC
        from . import views as W, automation_views as AV, experiments as X, handles as H, approval_documents as D
        ctx=W.load(self,now);scope=SC.scope_of(ctx.org,actor)
        company,cid=AV.resolve(ctx,self,scope,pid,key);own=AV.ownership(ctx,company)
        SC.require_client(ctx.org,scope,{pid:own},pid,SC.ACT_STOP if stop else SC.ACT_APPROVE)
        if not stop and H.stage_key(company['stage']) not in D.AUTO_STAGES:raise _S().StoreRefused('현재 계약 단계에서는 실행 계획을 승인할 수 없습니다')
        plan=self.automation_plan(pid,key);obs=self.setup_observation(cid,now)
        catalog=X.candidate_catalog(obs,possibility_id=pid,customer_id=cid,account_key=key)
        return ctx,own,cid,plan,catalog,obs

    def _execution_save_head(self,c,head,at,code):
        S=_S();h=deepcopy(head);h['updated_at']=at
        names=tuple(k for k in h if k not in ('document','binding','command','reasons'))+('document_json','binding_json','command_json','reasons_json')
        values=[h[k] for k in names[:-4]]+[S._json(h.get(k)) for k in ('document','binding','command','reasons')]
        c.execute('INSERT INTO naver_auto_execution_resource('+','.join(names)+') VALUES('+','.join('?' for _ in names)+') ON CONFLICT(resource_id) DO UPDATE SET '+','.join(k+'=excluded.'+k for k in names if k!='resource_id'),values)
        c.execute('INSERT INTO naver_auto_execution_history VALUES(?,?,?)',(h['resource_id'],h['version'],S._json(h)))
        c.execute('INSERT INTO naver_auto_execution_event(resource_id,at,code,payload_json) VALUES(?,?,?,?)',(h['resource_id'],at,code,S._json({'version':h['version'],'state':h['state']})))
        if h['resource_type']=='command':self._learning_capture_event(c,'execution_result',h['resource_id'],moment(at))
        return h

    def execution_recovery_receipt(self,pid,key,actor,request_id):
        from app.naver_auto import scope as SC
        S=_S()
        if not isinstance(request_id,str) or not _UUID.fullmatch(request_id):raise S.StoreRefused('실행 요청 식별자를 확인해 주세요')
        row=self._conn.execute('SELECT actor,possibility_id,account_key,length(response_json),substr(response_json,1,1025) FROM naver_auto_execution_receipt WHERE request_id=?',(request_id,)).fetchone()
        if row is None:return None
        if tuple(row[:3])!=(actor,pid,key):raise SC.ClientNotVisible()
        try:
            out=json.loads(row[4]);head=self._execution_head(out['resource_id'],pid,key)
            if row[3]>1024 or set(out)!={'resource_id','resource_type','version','request_id'} or out['request_id']!=request_id or not _UUID.fullmatch(out['resource_id']) or out['resource_type'] not in ('mandate','command','channels','spend','unit') or type(out['version']) is not int or not 1<=out['version']<2**53 or not head or head['version']<out['version']:raise ValueError()
            return out
        except (ValueError,TypeError,KeyError):raise S.StoreRefused('실행 저장 결과를 다시 확인해 주세요') from None

    def _execution_epochs(self,mid):
        return {r[0]:{'epoch':r[1],'target':json.loads(r[2]),'applied_at':r[3]} for r in self._conn.execute('SELECT target_key,epoch,target_json,applied_at FROM naver_auto_execution_epoch WHERE mandate_id=?',(mid,))}

    def _execution_ledger(self,cid):
        return [dict(command_id=r[0],customer_id=r[1],target_key=r[2],action=r[3],status=r[4],at=r[5],before=json.loads(r[6]) if r[6] else None,after=json.loads(r[7]) if r[7] else None,target_identity=r[8]) for r in self._conn.execute('SELECT command_id,customer_id,target_key,action,status,at,before_json,after_json,target_identity FROM naver_auto_execution_reservation WHERE customer_id=? ORDER BY at,command_id',(cid,))]

    def execution_account_spend(self,pid,cid,obs,now,period_start=None):
        """Calendar totals are source-qualified; VAT/capacity is never invented from a checkbox."""
        E=_E();day=now.astimezone(_S().KST).date();start=day.replace(day=1)
        from . import report_views as RV
        plan=self.automation_plan(pid,RV.account_key(cid))
        expected_start=plan['plan'].get('period_start')
        if period_start is not None and period_start!=expected_start:raise _S().StoreRefused('누적 지출은 승인 운영계획 시작일부터 확인해야 합니다')
        period_start=expected_start
        row=self._conn.execute('SELECT stage_revision,plan_version,period_start,status,checked_at,payload_json FROM naver_auto_execution_spend WHERE possibility_id=? AND account_key=? AND customer_id=? AND period_start=?',(pid,RV.account_key(cid),cid,period_start)).fetchone()
        if row and row[0]==(obs or {}).get('stage_revision') and row[1]==plan['version'] and row[2]==period_start and row[3]=='ok' and timedelta(0)<=now-moment(row[4])<=timedelta(minutes=15):
            cached=json.loads(row[5])
            if isinstance(cached,dict) and set(cached)=={'version','spend','campaign_budget_proof'}:
                from . import shared_budget_evidence as B
                current=B.from_observation(obs,now)
                cached=cached['spend'] if type(cached['version']) is int and cached['version']==1 and current is not None and cached['campaign_budget_proof']==current else None
            if isinstance(cached,dict) and cached.get('day')==day.isoformat() and cached.get('risk_period_start')==expected_start:
                unit=self._execution_unit(pid,RV.account_key(cid),catalog=None,obs=obs,now=now)
                cached.update(budget_unit=unit.get('budget_unit','unknown'),bid_cap_unit=unit.get('bid_cap_unit','unknown'))
                return cached
        rows=self.daily_performance([cid],start,day,possibility_id=pid)
        byday={r['day']:r for r in rows};expected={(start+timedelta(days=n)).isoformat() for n in range((day-start).days+1)}
        good=set(byday)==expected and all(r['basic_complete'] and type(r['spend']) in (int,float) and math.isfinite(r['spend']) and r['spend']>=0 and r.get('source_at') and moment(r['source_at'])<=moment(r['checked_at'])<=now for r in rows)
        campaigns=[]
        if obs and obs.get('status')=='ok' and obs.get('complete') and not obs.get('stale'):
            from . import experiments as X
            catalog=X.candidate_catalog(obs,possibility_id=pid,customer_id=cid,account_key=RV.account_key(cid))
            campaigns=[{'id':a['id'],'daily_budget':a['settings'].get('dailyBudget'),'use_daily_budget':a['settings'].get('useDailyBudget'),'shared_budget':a['settings'].get('sharedBudgetId')} for a in catalog.get('_arms',{}).values() if a['kind']=='campaign']
        return {'status':'unavailable','customer_id':cid,'source_at':min((r['source_at'] for r in rows),default=None) if good else None,
            'day':day.isoformat(),'month':day.strftime('%Y-%m'),'daily_spend':byday[day.isoformat()]['spend'] if good else None,
            'monthly_spend':sum(r['spend'] for r in rows) if good else None,'risk_spend':None,'risk_period_start':period_start,'budget_unit':'unknown','bid_cap_unit':'unknown','campaigns':campaigns}

    def _execution_channels_map(self,pid,cid,catalog,now):
        row=self._conn.execute('SELECT possibility_id,stage_revision,status,checked_at,payload_json FROM naver_auto_execution_channels WHERE customer_id=? AND possibility_id=? AND account_key=?',(cid,pid,(catalog.get('scope') or {}).get('account_key'))).fetchone()
        if not row or row[0]!=pid or row[1]!=(catalog.get('scope') or {}).get('stage_revision') or row[2]!='ok' or not timedelta(0)<=now-moment(row[3])<=timedelta(minutes=15):return {}
        return json.loads(row[4])

    def record_execution(self,pid,key,actor,now,*,resource_type,resource_id,expected_version,request_id,action,document=None):
        from . import approval_documents as D
        from app.naver_auto import scope as SC
        S=_S();E=_E();self._need_writer();self._not_future(now,'실행 승인');D.version(expected_version);S._pos_int(pid,'업체')
        if not isinstance(key,str) or not _KEY.fullmatch(key) or not isinstance(request_id,str) or not _UUID.fullmatch(request_id) or resource_type not in ('mandate','command','channels','spend','unit') or action not in ('save','approve','stop','cancel','reconcile_request','channels_request','spend_request','restore_draft') or resource_id is not None and (not isinstance(resource_id,str) or not _UUID.fullmatch(resource_id)) or action!='save' and document is not None:raise S.StoreRefused('실행 요청 범위를 확인해 주세요')
        body={'resource_type':resource_type,'resource_id':resource_id,'expected_version':expected_version,'action':action,'document':document}
        try:body_hash=E.fingerprint(body)
        except (ValueError,TypeError):raise S.StoreRefused('실행 자료 형식을 확인해 주세요') from None
        at=S._kst_text(now,'실행 승인');stopping=action in ('stop','cancel','reconcile_request')
        with self._tx() as c:
            ctx,own,cid,plan,catalog,obs=self._execution_context(pid,key,actor,now,stop=stopping)
            replay=c.execute('SELECT actor,possibility_id,account_key,body_hash,response_json FROM naver_auto_execution_receipt WHERE request_id=?',(request_id,)).fetchone()
            if replay:
                if tuple(replay[:4])!=(actor,pid,key,body_hash):raise S.StoreRefused('다른 실행 요청에 사용된 식별자입니다')
                return json.loads(replay[4])
            old=self._execution_head(resource_id,pid,key) if resource_id else None
            if old and (old['resource_type']!=resource_type or old['version']!=expected_version or old['updated_at']>at) or expected_version==D.MAX_VERSION:raise S.StoreRefused('실행 계획이 변경되었습니다. 다시 불러와 주세요')
            if not old and (resource_id is not None or expected_version!=0 or action not in ('save','channels_request','spend_request')):raise S.StoreRefused('현재 실행 계획을 다시 불러와 주세요')
            if resource_type=='spend' and action!='spend_request' or resource_type!='spend' and action=='spend_request' or resource_type=='channels' and action!='channels_request' or resource_type!='channels' and action=='channels_request' or resource_type=='mandate' and action not in ('save','approve','stop') or resource_type=='unit' and action not in ('save','approve') or resource_type=='command' and action not in ('save','approve','cancel','reconcile_request','restore_draft'):raise S.StoreRefused('실행 동작과 문서 범위가 맞지 않습니다')
            if resource_type=='command' and action in ('save','restore_draft') and c.execute("SELECT 1 FROM naver_auto_execution_resource r JOIN naver_auto_execution_operation o ON r.resource_id=o.command_id WHERE r.customer_id=? AND o.status IN ('dispatched','unknown') LIMIT 1",(cid,)).fetchone():raise S.StoreRefused('송신 결과를 먼저 재확인해 주세요')
            if old and action=='save' and old.get('binding'):raise S.StoreRefused('반영 영수증 기반 복구 초안은 편집할 수 없습니다. 새 일반 초안을 만들어 주세요')
            if old and action=='save' and old['state']!='draft':raise S.StoreRefused('승인한 실행 문서는 변경할 수 없습니다. 새 초안을 만들어 주세요')
            rid=resource_id or uuid.uuid4().hex
            head=deepcopy(old) if old else dict(resource_id=rid,resource_type=resource_type,possibility_id=pid,customer_id=cid,account_key=key,version=0,state='draft',document={},binding=None,command=None,author=actor,approved_by=None,approved_at=None,updated_at=at,next_evaluation_at=None,reasons=[])
            if action in ('save','approve'):
                if plan.get('state')!='approved' or plan.get('plan',{}).get('schema_version')!=2:raise S.StoreRefused('현재 승인된 업체별 운영 기준이 필요합니다')
                if action=='approve' and resource_type in ('mandate','command') and self.randomized_account_claimed(cid):
                    raise S.StoreRefused('이 계정은 승인된 무작위 실험에서 사용 중입니다. 실험 중단과 반영 결과를 먼저 확인해 주세요')
                try:
                    if resource_type=='unit':
                        doc=deepcopy(document if action=='save' else head['document'])
                        if not isinstance(doc,dict) or set(doc)!={'budget_unit','bid_cap_unit','source_note'} or any(doc[k] not in (None,'vat_included_krw','vat_excluded_krw') for k in ('budget_unit','bid_cap_unit')) or not isinstance(doc['source_note'],str) or len(doc['source_note'])>500 or any(ord(ch)<32 for ch in doc['source_note']):raise ValueError('단위 확인 자료를 확인해 주세요')
                        if action=='approve' and (any(doc[k] is None for k in ('budget_unit','bid_cap_unit')) or not doc['source_note'].strip()):raise ValueError('단위와 확인 자료 설명이 필요합니다')
                        if catalog.get('status')!='ready':raise ValueError('현재 캠페인 설정을 확인해 주세요')
                        binding={'scope':{k:catalog['scope'][k] for k in ('possibility_id','customer_id','account_key','stage_revision')},'settings_fingerprint':self._execution_campaign_fingerprint(obs),'plan_version':plan['version'],'actor':actor,'checked_at':at};command=None
                    elif resource_type=='mandate':
                        doc=E.normalize_mandate(document if action=='save' else head['document'],approve=action=='approve')
                        binding=E.bind_mandate(doc,plan,catalog,now,approve=action=='approve');command=None
                    else:
                        doc=E.normalize_manifest(document if action=='save' else head['document'])
                        binding=deepcopy(head.get('binding'))
                        if binding:self._execution_restore_current(binding,catalog)
                        command=E.bind_one_shot(doc,plan,catalog,now,command_id=rid,approval_ref={'kind':'one_shot','id':rid,'version':expected_version+1},channels=self._execution_channels_map(pid,cid,catalog,now)) if action=='approve' else None
                except (ValueError,TypeError,KeyError) as exc:raise S.StoreRefused(str(exc)) from None
                if action=='approve':
                    if old['state']!='draft':raise S.StoreRefused('저장한 실행 초안을 먼저 확인해 주세요')
                    if plan.get('approval_requires_lead') and not SC.can_approve(ctx.org,own,SC.LEVEL_LEAD,head['author'],actor):raise S.StoreRefused('운영 상한을 높이는 계획은 팀장 승인이 필요합니다')
                    if resource_type=='command':
                        limits=E.assess_limits(command,{'plan':plan['plan'],'document':None},self._execution_ledger(cid),self.execution_account_spend(pid,cid,obs,now),now)
                        if not limits['allowed']:raise S.StoreRefused('개별 실행의 지출·변경 한도를 확인해 주세요')
                        self._execution_reserve(c,command,at)
                    if resource_type=='mandate':
                        for prior in _S()._rows(c.execute("SELECT * FROM naver_auto_execution_resource WHERE possibility_id=? AND account_key=? AND resource_type='mandate' AND state='approved' AND resource_id!=?",(pid,key,rid))):
                            prior=_decode(prior);prior.update(version=prior['version']+1,state='stopped',reasons=['STOPPED']);self._execution_save_head(c,prior,at,'SUPERSEDED');self._execution_stop_children(c,prior['resource_id'],at)
                    head.update(state='approved',approved_by=actor,approved_at=at,next_evaluation_at=at if resource_type=='mandate' else None)
                else:head.update(state='draft',author=actor,approved_by=None,approved_at=None)
                head.update(document=doc,binding=binding,command=command,reasons=[])
            elif action in ('channels_request','spend_request'):
                if old:raise S.StoreRefused('새 채널 조회 요청을 만들어 주세요')
                if catalog.get('status')!='ready':raise S.StoreRefused('최신 계정 설정을 먼저 확인해 주세요')
                head.update(state='queued',document={'stage_revision':catalog['scope']['stage_revision'],**({'plan_version':plan['version'],'period_start':plan['plan']['period_start']} if action=='spend_request' else {})})
            elif action=='stop':
                if head['state']!='approved':raise S.StoreRefused('현재 승인된 실행 위임을 확인해 주세요')
                head.update(state='stopped',reasons=['STOPPED'])
                self._execution_stop_children(c,rid,at)
            elif action=='restore_draft':
                doc,binding=self._execution_restore_manifest(head,catalog)
                rid=uuid.uuid4().hex;head=dict(resource_id=rid,resource_type='command',possibility_id=pid,customer_id=cid,account_key=key,version=0,state='draft',document=doc,binding=binding,command=None,author=actor,approved_by=None,approved_at=None,updated_at=at,next_evaluation_at=None,reasons=[])
            elif action=='cancel':
                op=c.execute('SELECT status FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
                if not op or op[0] not in ('queued','claimed','dispatched','unknown'):raise S.StoreRefused('현재 실행 큐를 확인해 주세요')
                if op[0] in ('queued','claimed'):
                    c.execute("UPDATE naver_auto_execution_operation SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE command_id=?",(rid,));c.execute("UPDATE naver_auto_execution_reservation SET status='rejected' WHERE command_id=?",(rid,));head.update(state='cancelled',reasons=['STOPPED'])
                else:head.update(reasons=['STOPPED','UNKNOWN'])
            else:
                op=c.execute('SELECT status FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
                if not op or op[0] not in ('dispatched','unknown'):raise S.StoreRefused('송신 결과 재확인이 필요한 명령을 선택해 주세요')
                c.execute('UPDATE naver_auto_execution_operation SET next_try_at=?,reconcile_actor=? WHERE command_id=?',(at,actor,rid))
            head['version']=1 if action=='restore_draft' else expected_version+1;self._execution_save_head(c,head,at,action.upper())
            out={'resource_id':rid,'resource_type':resource_type,'version':head['version'],'request_id':request_id}
            c.execute('INSERT INTO naver_auto_execution_receipt VALUES(?,?,?,?,?,?)',(request_id,actor,pid,key,body_hash,S._json(out)))
            return out

    def _execution_stop_children(self,c,rid,at):
        for child in _S()._rows(c.execute("SELECT * FROM naver_auto_execution_resource WHERE resource_type='command' AND json_extract(command_json,'$.approval_ref.id')=?",(rid,))):
            op=c.execute('SELECT status FROM naver_auto_execution_operation WHERE command_id=?',(child['resource_id'],)).fetchone()
            if op and op[0] in ('queued','claimed'):
                c.execute("UPDATE naver_auto_execution_operation SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE command_id=?",(child['resource_id'],))
                c.execute("UPDATE naver_auto_execution_reservation SET status='rejected' WHERE command_id=?",(child['resource_id'],))
                ch=_decode(child);ch.update(version=ch['version']+1,state='cancelled',reasons=['STOPPED']);self._execution_save_head(c,ch,at,'MANDATE_STOP')

    def _execution_restore_current(self,proof,catalog):
        if not isinstance(proof,dict) or set(proof)!={'recovery_source','command_hash','recorded_after'}:raise _S().StoreRefused('복구 원본을 확인해 주세요')
        ref=proof['recovery_source'];original=self._execution_head(ref['resource_id'])
        if not original or original['state']!='confirmed' or original['version']!=ref['version'] or _E().fingerprint(original['command'])!=proof['command_hash'] or catalog.get('status')!='ready' or original['command']['scope']!={k:(catalog.get('scope') or {}).get(k) for k in original['command']['scope']}:raise _S().StoreRefused('현재 복구 원본과 계정 귀속을 확인해 주세요')
        after=proof['recorded_after']
        if sum(a==after for a in catalog.get('_arms',{}).values())!=1:raise _S().StoreRefused('현재 설정이 원본 반영 결과와 다릅니다. 복구를 자동 추정하지 않습니다')
        op=self._conn.execute('SELECT readback_json FROM naver_auto_execution_operation WHERE command_id=?',(original['resource_id'],)).fetchone()
        if not op or not op[0] or json.loads(op[0]).get('target')!=after:raise _S().StoreRefused('확인된 반영 영수증이 필요합니다')
        return original

    def _execution_restore_manifest(self,original,catalog):
        cmd=original.get('command')
        if original['state']!='confirmed' or not cmd or cmd['action'] not in ('update_bid','update_daily_budget','set_user_lock'):raise _S().StoreRefused('반영이 확인된 설정 변경만 복구 초안을 만들 수 있습니다. 생성 명령의 삭제 복구는 지원하지 않습니다')
        row=self._conn.execute('SELECT readback_json FROM naver_auto_execution_operation WHERE command_id=?',(original['resource_id'],)).fetchone()
        result=json.loads(row[0]) if row and row[0] else {}
        proof={'recovery_source':{'resource_id':original['resource_id'],'version':original['version']},'command_hash':_E().fingerprint(cmd),'recorded_after':result.get('target')}
        self._execution_restore_current(proof,catalog)
        key=next(k for k,a in catalog['_arms'].items() if a==result['target'])
        field,public={'update_bid':('bidAmt','bid'),'update_daily_budget':('dailyBudget','daily_budget'),'set_user_lock':('userLock','user_lock')}[cmd['action']]
        doc={'action':cmd['action'],'target_key':key,'parent_key':None,'payload':{public:cmd['target']['settings'].get(field)}}
        return _E().normalize_manifest(doc,approve=True),proof

    def _execution_reserve(self,c,command,at,evidence=None):
        S=_S();target=command.get('target');action=command['action'];payload=command['payload'];before=after=None
        plan=self.automation_plan(command['scope']['possibility_id'],command['scope']['account_key'])['plan']
        c.execute('INSERT OR IGNORE INTO naver_auto_meta(key,value) VALUES(?,?)',('learning-auto-plan:'+command['command_id'],S._json(plan)))
        self._learning_freeze_baseline(c,command['command_id'],evidence)
        if target:
            field='bidAmt' if action=='update_bid' else 'dailyBudget' if action=='update_daily_budget' else 'userLock'
            before=target['settings'].get(field);after=payload.get(field)
        c.execute('INSERT INTO naver_auto_execution_operation(command_id,status,next_try_at) VALUES(?,?,?)',(command['command_id'],'queued',at))
        c.execute('INSERT INTO naver_auto_execution_reservation VALUES(?,?,?,?,?,?,?,?,?)',(command['command_id'],command['scope']['customer_id'],command.get('target_key'),action,'reserved',at,S._json(before),S._json(after),_E().target_identity(command)))

    def _execution_binding_current(self,head,now):
        formal=head.get('command') and head['command']['approval_ref']['kind'] in ('randomized_experiment','randomized_experiment_stop')
        if formal:
            mapped=self._randomized_command_ref(head['resource_id'])
            terminal=bool(mapped and mapped['step'] in ('stop_control','stop_treatment'))
            E=_E();ctx,own,cid,plan,catalog,obs=self._execution_context(head['possibility_id'],head['account_key'],head['approved_by'],now,stop=terminal)
            if not self.randomized_execution_current(head['command']['approval_ref'],head['command'],now):raise _S().StoreRefused('현재 실험 배정·권한·전환 기한을 확인해 주세요')
            if terminal:
                bound=self._randomized_head(mapped['ref']['id'])['binding']
                plan={'state':'approved','version':bound['plan_version'],'plan':bound['plan']}
            return plan,catalog,obs,{}
        E=_E();ctx,own,cid,plan,catalog,obs=self._execution_context(head['possibility_id'],head['account_key'],head['approved_by'],now)
        epochs={}
        if self.randomized_account_claimed(cid):raise _S().StoreRefused('승인된 실험과 다른 자동 운영을 병행할 수 없습니다')
        if head['resource_type']=='mandate':
            epochs=self._execution_epochs(head['resource_id']);E.current_mandate(head['binding'],plan,catalog,now,epochs=epochs)
        else:
            command=head['command'];ref=command['approval_ref']
            if ref['kind']=='mandate':
                mandate=self._execution_head(ref['id'],head['possibility_id'],head['account_key'])
                if not mandate or mandate['state']!='approved' or mandate['version']!=ref['version']:raise _S().StoreRefused('실행 위임이 중지되거나 변경되었습니다')
                epochs=self._execution_epochs(ref['id']);E.current_mandate(mandate['binding'],plan,catalog,now,epochs=epochs)
            elif head['state'] not in ('approved','claimed','dispatched','unknown'):raise _S().StoreRefused('현재 승인된 개별 실행이 아닙니다')
            if plan['state']!='approved' or plan['version']!=command['plan_version']:raise _S().StoreRefused('승인 운영 기준이 변경되었습니다')
            if command['scope']!={k:(catalog.get('scope') or {}).get(k) for k in command['scope']}:raise _S().StoreRefused('실행 계정 귀속이 변경되었습니다')
            if command.get('target'):
                expected=command['target'];current=next((a for a in catalog.get('_arms',{}).values() if a['kind']==expected['kind'] and a['id']==expected['id']),None)
                if current!=expected:raise _S().StoreRefused('실행 대상 설정이 변경되었습니다')
            if command.get('parent') and command['parent'] not in catalog.get('_arms',{}).values():raise _S().StoreRefused('생성할 부모 설정이 변경되었습니다')
            E.current_command(command,catalog,now)
            if head.get('binding'):self._execution_restore_current(head['binding'],catalog)
        return plan,catalog,obs,epochs

    def execution_evaluate(self,now,limit=1):
        S=_S();E=_E();self._need_writer();self._not_future(now,'실행 평가');S._pos_int(limit,'평가 상한')
        if limit>10:raise S.StoreRefused('실행 평가 상한을 확인해 주세요')
        at=S._kst_text(now,'실행 평가');heads=_S()._rows(self._conn.execute("SELECT resource_id FROM naver_auto_execution_resource WHERE resource_type='mandate' AND state='approved' AND next_evaluation_at<=? ORDER BY next_evaluation_at,resource_id LIMIT ?",(at,limit)))
        out={'evaluated':0,'queued':0,'held':0}
        for row in heads:
            with self._tx() as c:
                head=self._execution_head(row['resource_id']);binding=head['binding'];out['evaluated']+=1
                interval=head['document']['evaluation_interval_minutes'];c.execute('UPDATE naver_auto_execution_resource SET next_evaluation_at=? WHERE resource_id=?',((now+timedelta(minutes=interval)).isoformat(),head['resource_id']))
                try:plan,catalog,obs,epochs=self._execution_binding_current(head,now)
                except Exception:
                    c.execute('UPDATE naver_auto_execution_resource SET reasons_json=? WHERE resource_id=?',(S._json(['SOURCE_CHANGED']),head['resource_id']));out['held']+=1;continue
                ledger=self._execution_ledger(head['customer_id']);spend=self.execution_account_spend(head['possibility_id'],head['customer_id'],obs,now,plan['plan']['period_start'])
                if spend['status']!='ok':self._execution_queue_source(c,head,'spend',{'stage_revision':binding['scope']['stage_revision'],'plan_version':binding['plan_version'],'period_start':plan['plan']['period_start']},at)
                for target_key,arm in binding['targets'].items():
                    current=epochs.get(target_key,{}).get('target',arm);perf=(obs or {}).get('performance',{}).get(current['kind']+':'+current['id'])
                    evidence=dict(status='ok' if perf and perf['complete'] and not perf['missing'] else 'unavailable',customer_id=head['customer_id'],target_key=target_key,config_epoch=epochs.get(target_key,{}).get('epoch',0),period_start=perf.get('period_start') if perf else None,period_end=perf.get('period_end') if perf else None,source_at=perf.get('source_at') if perf else None,configuration_verified=bool(perf and catalog.get('status')=='ready'),fields=deepcopy(perf['fields']) if perf else dict.fromkeys(('impCnt','clkCnt','salesAmt','ccnt','convAmt')),conversion_definition='platform_all_conversions',value_basis='platform_conversion_value',minimum_source_lag_days=max(-1,(moment(perf['source_at'])-moment(perf['period_end']+'T00:00:00+09:00')-timedelta(days=1)).days) if perf and perf.get('source_at') else None)
                    window_end=now.astimezone(S.KST).date()-timedelta(days=1+plan['plan']['measurement_lag_days']);window_start=window_end-timedelta(days=head['document']['evaluation_window_days']-1)
                    cached=self._conn.execute('SELECT status,checked_at,payload_json FROM naver_auto_execution_evidence WHERE mandate_id=? AND target_key=? AND config_epoch=? AND period_start=? AND period_end=?',(head['resource_id'],target_key,epochs.get(target_key,{}).get('epoch',0),window_start.isoformat(),window_end.isoformat())).fetchone()
                    if cached and cached[0]!='ok':evidence.update(status='unavailable',fields=dict.fromkeys(evidence['fields']))
                    if cached and cached[0]=='ok' and timedelta(0)<=now-moment(cached[1])<=timedelta(minutes=head['document']['stop']['source_max_age_minutes']):evidence=json.loads(cached[2])
                    elif evidence['period_start']!=window_start.isoformat() or evidence['period_end']!=window_end.isoformat() or evidence['status']!='ok':
                        evidence.update(status='unavailable',fields=dict.fromkeys(evidence['fields']))
                        if window_start>=date.fromisoformat(head['document']['operation_start']):self._execution_queue_source(c,head,'evidence',{'mandate_id':head['resource_id'],'target_key':target_key,'config_epoch':epochs.get(target_key,{}).get('epoch',0),'period_start':window_start.isoformat(),'period_end':window_end.isoformat()},at)
                    if evidence['status']=='ok' and epochs.get(target_key,{}).get('epoch',0)>0:
                        self._learning_attach_followup(c,head['resource_id'],target_key,epochs[target_key]['epoch'],evidence,now)
                    decision=E.assess_operation(binding,target_key,evidence,spend,ledger,now,epochs=epochs)
                    ek=decision.get('evaluation_key')
                    if not ek:
                        c.execute('UPDATE naver_auto_execution_resource SET reasons_json=? WHERE resource_id=?',(S._json(decision.get('reason_codes',[])),head['resource_id']))
                        out['held']+=int(decision['state']=='hold');continue
                    previous=c.execute('SELECT decision_json,command_id FROM naver_auto_execution_evaluation WHERE mandate_id=? AND evaluation_key=?',(head['resource_id'],ek)).fetchone()
                    if previous and (previous[1] is not None or json.loads(previous[0]).get('state')!='hold'):continue
                    prior=c.execute('SELECT decision_json FROM naver_auto_execution_evaluation WHERE mandate_id=? AND target_key=? AND evaluation_key!=? ORDER BY evaluated_at DESC,rowid DESC LIMIT 100',(head['resource_id'],target_key,ek)).fetchall();consecutive=0
                    for historical in prior:
                        flag=json.loads(historical[0]).get('deteriorated')
                        if flag is None:continue
                        if flag is not True:break
                        consecutive+=1
                    if consecutive:decision=E.assess_operation(binding,target_key,evidence,spend,ledger,now,epochs=epochs,consecutive_periods=consecutive)
                    command=None;rid=None
                    if decision['state']=='queue':
                        rid=uuid.uuid4().hex;command=E.build_command(binding,target_key,decision,now,command_id=rid,approval_ref={'kind':'mandate','id':head['resource_id'],'version':head['version']},epochs=epochs)
                        limits=E.assess_limits(command,binding,ledger,spend,now)
                        if not limits['allowed']:
                            decision={**decision,'state':'hold','reason_codes':limits['reason_codes']};command=None;rid=None
                            c.execute('UPDATE naver_auto_execution_resource SET reasons_json=? WHERE resource_id=?',(S._json(limits['reason_codes']),head['resource_id']))
                            out['held']+=1
                            c.execute('INSERT INTO naver_auto_execution_evaluation VALUES(?,?,?,?,?,NULL) ON CONFLICT(mandate_id,evaluation_key) DO UPDATE SET evaluated_at=excluded.evaluated_at,decision_json=excluded.decision_json',(head['resource_id'],ek,target_key,at,S._json(decision)))
                            continue
                    c.execute('INSERT INTO naver_auto_execution_evaluation VALUES(?,?,?,?,?,?) ON CONFLICT(mandate_id,evaluation_key) DO UPDATE SET evaluated_at=excluded.evaluated_at,decision_json=excluded.decision_json,command_id=excluded.command_id',(head['resource_id'],ek,target_key,at,S._json(decision),rid))
                    if command:
                        ch=dict(resource_id=rid,resource_type='command',possibility_id=head['possibility_id'],customer_id=head['customer_id'],account_key=head['account_key'],version=1,state='approved',document={'action':command['action'],'target_key':target_key,'parent_key':None,'payload':{'bid':command['payload']['bidAmt']} if command['action']=='update_bid' else {'user_lock':command['payload']['userLock']}},binding=None,command=command,author=head['author'],approved_by=head['approved_by'],approved_at=head['approved_at'],updated_at=at,next_evaluation_at=None,reasons=[])
                        self._execution_save_head(c,ch,at,'RULE_QUEUED');self._execution_reserve(c,command,at,evidence=evidence);self._learning_capture_event(c,'execution_result',rid,now);ledger=self._execution_ledger(head['customer_id']);out['queued']+=1
                    elif decision['state']=='hold':out['held']+=1
                    c.execute('UPDATE naver_auto_execution_resource SET reasons_json=? WHERE resource_id=?',(S._json(decision.get('reason_codes',[])),head['resource_id']))
        return out

    def execution_work(self,now,limit=1):
        at=_S()._kst_text(now,'실행 작업')
        if type(limit)is not int or not 1<=limit<=3:raise _S().StoreRefused('실행 작업 상한을 확인해 주세요')
        rows=_S()._rows(self._conn.execute("SELECT r.resource_id,r.resource_type,o.status,o.lease_until FROM naver_auto_execution_resource r LEFT JOIN naver_auto_execution_operation o ON r.resource_id=o.command_id WHERE (r.resource_type IN ('channels','spend','evidence') AND r.state='queued') OR (r.resource_type='command' AND o.next_try_at<=? AND (o.status IN ('queued','dispatched','unknown') OR (o.status='claimed' AND o.lease_until<=?))) ORDER BY CASE WHEN o.status IN ('dispatched','unknown') THEN 0 WHEN r.resource_type IN ('channels','spend','evidence') THEN 1 ELSE 2 END,r.updated_at,r.resource_id LIMIT ?",(at,at,limit)))
        return [{'resource_id':r['resource_id'],'resource_type':r['resource_type'],'mode':r['resource_type'] if r['resource_type'] in ('channels','spend','evidence') else 'reconcile' if r['status'] in ('dispatched','unknown') else 'dispatch'} for r in rows]

    def execution_claim(self,rid,now,lease_seconds=30):
        S=_S();self._need_writer();self._not_future(now,'실행 claim');at=S._kst_text(now,'실행 claim')
        if not isinstance(rid,str) or not _UUID.fullmatch(rid) or type(lease_seconds)is not int or not 1<=lease_seconds<=60:raise S.StoreRefused('실행 claim 범위를 확인해 주세요')
        with self._tx() as c:
            head=self._execution_head(rid);op=c.execute('SELECT status,lease_until,next_try_at FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
            if not head or not op or op[2]>at or op[0] not in ('queued','claimed','dispatched','unknown') or op[0]=='claimed' and op[1]>at:return None
            if op[0] in ('dispatched','unknown') and op[1] and op[1]>at:return None
            token=uuid.uuid4().hex;mode='reconcile' if op[0] in ('dispatched','unknown') else 'dispatch'
            if mode=='dispatch':
                try:self._execution_binding_current(head,now)
                except Exception:self._execution_reject(c,head,at,'SOURCE_CHANGED');return None
            else:
                try:self._execution_context(head['possibility_id'],head['account_key'],self._execution_reconcile_actor(rid,head),now,stop=True)
                except Exception:return None
            c.execute('UPDATE naver_auto_execution_operation SET status=?,lease_token=?,lease_until=? WHERE command_id=?',('claimed' if mode=='dispatch' else op[0],token,(now+timedelta(seconds=lease_seconds)).isoformat(),rid))
            return {'lease_token':token,'command':deepcopy(head['command']),'mode':mode}

    def _execution_reject(self,c,head,at,reason):
        c.execute("UPDATE naver_auto_execution_operation SET status='rejected',lease_token=NULL,lease_until=NULL,error_code=? WHERE command_id=?",(reason,head['resource_id']))
        c.execute("UPDATE naver_auto_execution_reservation SET status='rejected' WHERE command_id=?",(head['resource_id'],))
        head.update(version=head['version']+1,state='rejected',reasons=[reason]);self._execution_save_head(c,head,at,'REJECTED')

    def execution_mark_dispatched(self,rid,token,now,preflight=None):
        S=_S();E=_E();self._need_writer();self._not_future(now,'실행 송신');at=S._kst_text(now,'실행 송신')
        with self._tx() as c:
            head=self._execution_head(rid);op=c.execute('SELECT status,lease_token,lease_until FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
            if not op or op[0]!='claimed' or op[1]!=token or op[2]<=at:raise S.StoreRefused('현재 실행 lease를 확인해 주세요')
            try:
                plan,catalog,obs,epochs=self._execution_binding_current(head,now)
                if preflight is None:raise S.StoreRefused('송신 직전 대상 재조회가 필요합니다')
                E.verify_preflight(head['command'],preflight)
                ref=head['command']['approval_ref'];mandate=self._execution_head(ref['id']) if ref['kind']=='mandate' else None
                binding=mandate['binding'] if mandate else {'plan':plan['plan'],'document':None}
                mapped=self._randomized_command_ref(rid) if ref['kind'] in ('randomized_experiment','randomized_experiment_stop') else None
                terminal=bool(mapped and mapped['step'] in ('stop_control','stop_treatment'))
                spend=None if terminal else self.randomized_execution_spend(ref['id'],now) if mapped else self.execution_account_spend(head['possibility_id'],head['customer_id'],obs,now,plan['plan']['period_start'])
                limits=E.assess_limits(head['command'],binding,self._execution_ledger(head['customer_id']),spend,now,exclude_command_id=rid)
                reasons=[r for r in limits['reason_codes'] if not(terminal and r=='NO_CHANGE')]
                if reasons:raise S.StoreRefused('송신 직전 실행 한도가 바뀌었습니다')
                if mapped and not self.randomized_execution_limits(head['command'],now):
                    raise S.StoreRefused('실험 광고비·변경 횟수 한도를 확인해 주세요')
            except Exception:
                self._execution_reject(c,head,at,'SOURCE_CHANGED');return None
            c.execute('INSERT INTO naver_auto_execution_attempt VALUES(?,?,?,?,NULL)',(rid,token,E.fingerprint(head['command']),at))
            c.execute("UPDATE naver_auto_execution_operation SET status='dispatched',dispatched_at=? WHERE command_id=?",(at,rid))
            c.execute("UPDATE naver_auto_execution_reservation SET status='dispatched' WHERE command_id=?",(rid,))
            head.update(version=head['version']+1,state='dispatched');self._execution_save_head(c,head,at,'DISPATCHED')
            return deepcopy(head['command'])

    def execution_record_result(self,rid,token,outcome,now):
        S=_S();self._need_writer();self._not_future(now,'실행 결과');at=S._kst_text(now,'실행 결과')
        if not isinstance(outcome,dict) or outcome.get('state') not in ('accepted','unknown','rejected'):raise S.StoreRefused('실행 결과 형식을 확인해 주세요')
        with self._tx() as c:
            head=self._execution_head(rid);op=c.execute('SELECT status,lease_token FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
            attempt=c.execute('SELECT command_hash,outcome_json FROM naver_auto_execution_attempt WHERE command_id=? AND lease_token=?',(rid,token)).fetchone()
            if not head or not op or not attempt or attempt[0]!=_E().fingerprint(head['command']):raise S.StoreRefused('현재 송신 결과의 lease를 확인해 주세요')
            if attempt[1] is not None:return op[0]
            state='dispatched' if outcome['state']=='accepted' else outcome['state']
            # Provider bodies are never persisted; adapter returns only typed safe outcome.
            code=outcome.get('error_code')
            if code not in (None,'PLATFORM_REJECTED','OUTCOME_UNKNOWN','RESULT_ID_UNKNOWN','PREFLIGHT_OR_APPROVAL_BLOCKED','UNEXPECTED','NETWORK'):code='UNEXPECTED'
            safe={'state':outcome['state'],'result_id':outcome.get('result_id'),'error_code':code}
            if safe['result_id'] is not None and not isinstance(safe['result_id'],str):raise S.StoreRefused('실행 응답 식별자를 확인해 주세요')
            c.execute('UPDATE naver_auto_execution_attempt SET outcome_json=? WHERE command_id=? AND lease_token=?',(S._json(safe),rid,token))
            if op[0]=='confirmed':return 'confirmed'
            if op[1]!=token and op[1] is not None:
                c.execute('UPDATE naver_auto_execution_operation SET outcome_json=? WHERE command_id=?',(S._json(safe),rid))
                return op[0]
            c.execute('UPDATE naver_auto_execution_operation SET status=?,outcome_json=?,next_try_at=?,lease_token=NULL,lease_until=NULL,error_code=? WHERE command_id=?',(state,S._json(safe),(now+timedelta(seconds=1 if state=='dispatched' else 60)).isoformat(),safe['error_code'],rid))
            c.execute('UPDATE naver_auto_execution_reservation SET status=? WHERE command_id=?',('rejected' if state=='rejected' else 'unknown' if state=='unknown' else 'dispatched',rid))
            head.update(version=head['version']+1,state=state,reasons=['UNKNOWN'] if state=='unknown' else []);self._execution_save_head(c,head,at,'RESULT_'+state.upper())
            return state

    def execution_reconcile_data(self,rid,token,now):
        head=self._execution_head(rid);op=self._conn.execute('SELECT status,lease_token,lease_until,outcome_json FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
        at=_S()._kst_text(now,'실행 재조회')
        if not head or not op or op[0] not in ('dispatched','unknown') or op[1]!=token or op[2]<=at:raise _S().StoreRefused('현재 재조회 lease를 확인해 주세요')
        return {'command':deepcopy(head['command']),'outcome':json.loads(op[3]) if op[3] else None}

    def execution_record_readback(self,rid,token,row,now):
        S=_S();E=_E();self._need_writer();self._not_future(now,'실행 반영 확인');at=S._kst_text(now,'실행 반영 확인')
        with self._tx() as c:
            head=self._execution_head(rid);op=c.execute('SELECT status,lease_token,lease_until FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
            if not head or not op or op[0] not in ('dispatched','unknown') or op[1]!=token or op[2]<=at:raise S.StoreRefused('현재 반영 확인 lease를 확인해 주세요')
            command=head['command']
            if command['action'].startswith('create_'):
                outcome=c.execute('SELECT outcome_json FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
                result_id=(json.loads(outcome[0]) if outcome and outcome[0] else {}).get('result_id')
                from . import inspection_fields as IF
                kind={'create_campaign':'campaign','create_adgroup':'adgroup','create_keyword':'keyword','create_text_ad':'ad'}[command['action']]
                if not result_id or not isinstance(row,dict) or row.get(IF.IDS[kind])!=result_id:row=None
            result=E.verify_readback(command,row);state='confirmed' if result['state']=='confirmed' else 'unknown'
            c.execute('UPDATE naver_auto_execution_operation SET status=?,confirmed_at=?,readback_json=?,lease_token=NULL,lease_until=NULL,next_try_at=? WHERE command_id=?',(state,at if state=='confirmed' else None,S._json(result),(now+timedelta(minutes=15)).isoformat(),rid))
            c.execute('UPDATE naver_auto_execution_reservation SET status=? WHERE command_id=?',(state,rid))
            current=False
            if state=='confirmed':
                try:self._execution_post_current(head,result['target'],now);current=True
                except Exception:pass
            if state=='confirmed' and command['action'].startswith('create_'):
                c.execute('UPDATE naver_auto_execution_reservation SET target_identity=? WHERE command_id=?',(E.target_identity(command,target=result['target']),rid))
            if state=='confirmed' and current and head['command']['approval_ref']['kind']=='mandate':
                cmd=head['command'];mid=cmd['approval_ref']['id'];tk=cmd['target_key'];epoch=cmd['config_epoch']+1
                c.execute('INSERT INTO naver_auto_execution_epoch VALUES(?,?,?,?,?,?) ON CONFLICT(mandate_id,target_key) DO UPDATE SET epoch=excluded.epoch,target_json=excluded.target_json,applied_at=excluded.applied_at,command_id=excluded.command_id',(mid,tk,epoch,S._json(result['target']),at,rid))
            head.update(version=head['version']+1,state=state,reasons=[] if state=='confirmed' else ['UNKNOWN']);self._execution_save_head(c,head,at,'READBACK_'+state.upper())
            return state

    def execution_channel_work(self,rid,now):
        head=self._execution_head(rid)
        if not head or head['resource_type'] not in ('channels','spend') or head['state']!='queued':return None
        _,_,cid,plan,catalog,obs=self._execution_context(head['possibility_id'],head['account_key'],head['author'],now)
        if head['document']['stage_revision']!=(catalog.get('scope') or {}).get('stage_revision'):
            # A formal experiment may start before the new day's settings collector.
            # This only authorizes its GET-only spend read; fresh ERP/plan checks remain mandatory.
            if head['resource_type']!='spend' or not self.randomized_source_scope_current(
                head['possibility_id'],head['account_key'],head['author'],now,
                head['document']['stage_revision'],head['document']['plan_version']):return None
        if head['resource_type']=='spend' and (plan['state']!='approved' or head['document']['plan_version']!=plan['version'] or head['document']['period_start']!=plan['plan']['period_start']):return None
        out={'resource_id':rid,'possibility_id':head['possibility_id'],'account_key':head['account_key'],'customer_id':cid,'stage_revision':head['document']['stage_revision'],**({'plan_version':head['document']['plan_version'],'period_start':head['document']['period_start']} if head['resource_type']=='spend' else {})}
        if head['resource_type']=='spend':
            from . import shared_budget_evidence as B
            proof=B.from_observation(obs,now)
            if proof is not None and all(proof['scope'][k]==out[k] for k in ('possibility_id','customer_id','account_key','stage_revision')):
                out['campaign_budget_proof']=proof
        return out

    def execution_record_channels(self,rid,records,now):
        S=_S();E=_E();self._need_writer();self._not_future(now,'채널 조회');at=S._kst_text(now,'채널 조회')
        with self._tx() as c:
            work=self.execution_channel_work(rid,now)
            if not work:return False
            if records is not None and (not isinstance(records,list) or len(records)>100):raise S.StoreRefused('채널 조회 범위를 확인해 주세요')
            mapping={}
            for r in records or []:
                if not isinstance(r,dict) or set(r)-{'nccBusinessChannelId','customerId','name','channelTp','channelKey','status'} or r.get('customerId')!=work['customer_id'] or r.get('channelTp')!='SITE' or not isinstance(r.get('nccBusinessChannelId'),str) or not re.fullmatch(r'bsn-[A-Za-z0-9_-]{1,96}',r['nccBusinessChannelId']) or not isinstance(r.get('channelKey'),str):raise S.StoreRefused('현재 계정의 사이트 채널인지 확인해 주세요')
                key=E.fingerprint({'scope':{k:work[k] for k in ('possibility_id','account_key','customer_id','stage_revision')},'id':r['nccBusinessChannelId'],'type':'SITE','status':r.get('status'),'url_hash':E.fingerprint(r['channelKey'])})
                if key in mapping:raise S.StoreRefused('채널 조회가 중복되었습니다')
                mapping[key]={'id':r['nccBusinessChannelId'],'customer_id':work['customer_id'],'type':'SITE','status':r.get('status'),'channel_key':r['channelKey'],'source_at':at}
            status='ok' if records is not None else 'failed'
            c.execute('INSERT INTO naver_auto_execution_channels VALUES(?,?,?,?,?,?,?) ON CONFLICT(possibility_id,account_key) DO UPDATE SET customer_id=excluded.customer_id,stage_revision=excluded.stage_revision,status=excluded.status,checked_at=excluded.checked_at,payload_json=excluded.payload_json',(work['customer_id'],work['possibility_id'],work['account_key'],work['stage_revision'],status,at,S._json(mapping)))
            head=self._execution_head(rid);head.update(version=head['version']+1,state='confirmed' if status=='ok' else 'rejected');self._execution_save_head(c,head,at,'CHANNELS_'+status.upper());return True

    def execution_projection(self,pid,key,cid,now,plan,catalog,*,resource_id=None,can_edit=False,can_approve=False,can_stop=False,operator_enabled=False):
        rows=_S()._rows(self._conn.execute('SELECT resource_id FROM naver_auto_execution_resource WHERE possibility_id=? AND account_key=? AND customer_id=? ORDER BY updated_at DESC,resource_id DESC LIMIT 100',(pid,key,cid)))
        heads=[self._execution_head(r['resource_id']) for r in rows]
        for kind in ('mandate','unit','channels','spend'):
            row=self._conn.execute('SELECT resource_id FROM naver_auto_execution_resource WHERE possibility_id=? AND account_key=? AND customer_id=? AND resource_type=? ORDER BY updated_at DESC,resource_id DESC LIMIT 1',(pid,key,cid,kind)).fetchone()
            if row and not any(h['resource_id']==row[0] for h in heads):heads.append(self._execution_head(row[0]))
        pending=self._conn.execute("SELECT EXISTS(SELECT 1 FROM naver_auto_execution_reservation WHERE customer_id=? AND status IN ('reserved','dispatched','unknown')),EXISTS(SELECT 1 FROM naver_auto_execution_operation o JOIN naver_auto_execution_resource r ON r.resource_id=o.command_id WHERE r.customer_id=? AND o.status='unknown')",(cid,cid)).fetchone()
        mandate=next((h for h in heads if h['resource_type']=='mandate'),None)
        chosen=self._execution_head(resource_id,pid,key) if resource_id else next((h for h in heads if h['resource_type']=='command'),None)
        if resource_id and not chosen:raise _S().StoreRefused('현재 실행 문서를 다시 불러와 주세요')
        if chosen and chosen['resource_type']=='mandate':mandate=chosen
        def public(h,detail=False):
            cmd=h.get('command')
            if detail and h['resource_type']=='command' and cmd is None:
                try:cmd=_E().bind_one_shot(h['document'],plan,catalog,now,command_id=h['resource_id'],approval_ref={'kind':'one_shot','id':h['resource_id'],'version':h['version']+1},channels=self._execution_channels_map(pid,cid,catalog,now))
                except (ValueError,TypeError,KeyError):pass
            labels={r['key']:r['label'] for r in catalog.get('items',[])}
            out={'id':h['resource_id'],'version':h['version'],'state':h['state'],'created_at':h['updated_at'],'approved_at':h['approved_at'],'hold_reasons':[_reason(x) for x in h.get('reasons',[])],'can_cancel':can_stop and h['state'] in ('approved','claimed','dispatched','unknown'),'can_reconcile':can_stop and h['state'] in ('dispatched','unknown')}
            if h['resource_type']=='mandate':
                current=False
                if h['binding'] and h['state']=='approved':
                    try:current=_E().current_mandate(h['binding'],plan,catalog,now,epochs=self._execution_epochs(h['resource_id'])) is True
                    except (ValueError,TypeError,KeyError):pass
                approvable=can_approve and h['state']=='draft'
                if approvable:
                    try:_E().bind_mandate(h['document'],plan,catalog,now,approve=True)
                    except (ValueError,TypeError,KeyError):approvable=False
                out.update(document=deepcopy(h['document']),current=current,can_stop=can_stop and h['state']=='approved',can_approve=approvable)
            else:
                op=self._conn.execute('SELECT dispatched_at,confirmed_at FROM naver_auto_execution_operation WHERE command_id=?',(h['resource_id'],)).fetchone()
                doc=h['document'];out.update(action=doc.get('action'),target_label=labels.get(doc.get('target_key'),'선택 대상'),parent_label=labels.get(doc.get('parent_key'),'선택 부모'),dispatched_at=op[0] if op else None,confirmed_at=op[1] if op else None,can_approve=can_approve and h['state']=='draft')
                restorable=False
                if can_edit and h['state']=='confirmed' and not self._conn.execute("SELECT 1 FROM naver_auto_execution_resource r JOIN naver_auto_execution_operation o ON r.resource_id=o.command_id WHERE r.customer_id=? AND o.status IN ('dispatched','unknown') LIMIT 1",(cid,)).fetchone():
                    try:self._execution_restore_manifest(h,catalog);restorable=True
                    except (ValueError,TypeError,KeyError,_S().StoreRefused):pass
                out.update(can_restore=restorable,restore_ref=deepcopy((h.get('binding') or {}).get('recovery_source')))
                if detail:
                    out['document']=deepcopy(doc);changes=[]
                    if cmd and cmd.get('target') and cmd['action'] in ('update_bid','update_daily_budget','set_user_lock'):
                        field='bidAmt' if cmd['action']=='update_bid' else 'dailyBudget' if cmd['action']=='update_daily_budget' else 'userLock'
                        changes=[{'field':field,'before':cmd['target']['settings'].get(field),'after':cmd['payload'].get(field)}]
                    out['preview']={'target_label':out['target_label'],'parent_label':out['parent_label'],'changes':changes}
            return out
        selected=public(chosen,True) if chosen and chosen['resource_type']=='command' else None
        channels=self._execution_channels_map(pid,cid,catalog,now);row=self._conn.execute('SELECT status,checked_at FROM naver_auto_execution_channels WHERE customer_id=? AND possibility_id=? AND account_key=?',(cid,pid,key)).fetchone()
        unithead=next((h for h in heads if h['resource_type']=='unit'),None)
        unit=self._execution_unit(pid,key,catalog,obs=None,now=now)
        unitpublic={'id':unithead['resource_id'],'version':unithead['version'],'state':unithead['state'],'document':unithead['document'],'current':bool(unit),'kind':'operator_verified','checked_at':unithead['approved_at'],'can_approve':can_approve and unithead['state']=='draft'} if unithead else None
        spendrow=self._conn.execute('SELECT status,checked_at,period_start,payload_json,stage_revision,plan_version FROM naver_auto_execution_spend WHERE possibility_id=? AND account_key=? ORDER BY checked_at DESC LIMIT 1',(pid,key)).fetchone()
        spendpublic={'status':'unavailable','checked_at':spendrow[1] if spendrow else None,'period_start':spendrow[2] if spendrow else None,'source_at':None,'daily_spend':None,'monthly_spend':None,'risk_spend':None,'current_day_final':False,'request':next(({'id':h['resource_id'],'version':h['version'],'state':h['state']} for h in ([chosen] if chosen and chosen['resource_type']=='spend' else heads) if h['resource_type']=='spend'),None)}
        if spendrow and spendrow[0]=='ok' and spendrow[4]==(catalog.get('scope') or {}).get('stage_revision') and spendrow[5]==plan['version'] and spendrow[2]==plan['plan'].get('period_start') and catalog.get('status')=='ready' and timedelta(0)<=now-moment(spendrow[1])<=timedelta(minutes=15):
            source=json.loads(spendrow[3]);spendpublic.update(status='observed',**{k:source.get(k) for k in ('source_at','daily_spend','monthly_spend','risk_spend')})
        entity_sources=[]
        if mandate:
            for tk in mandate['document'].get('target_keys',[]):
                source=self._conn.execute('SELECT config_epoch,period_start,period_end,status,checked_at,payload_json FROM naver_auto_execution_evidence WHERE mandate_id=? AND target_key=? ORDER BY checked_at DESC,rowid DESC LIMIT 1',(mandate['resource_id'],tk)).fetchone()
                req=next((h for h in heads if h['resource_type']=='evidence' and h['document'].get('mandate_id')==mandate['resource_id'] and h['document'].get('target_key')==tk),None)
                qualified=False
                if source and source[3]=='ok' and mandate['state']=='approved' and source[0]==self._execution_epochs(mandate['resource_id']).get(tk,{}).get('epoch',0):
                    try:qualified=_E().current_mandate(mandate['binding'],plan,catalog,now,epochs=self._execution_epochs(mandate['resource_id'])) is True and timedelta(0)<=now-moment(source[4])<=timedelta(minutes=mandate['document']['stop']['source_max_age_minutes'])
                    except (ValueError,TypeError,KeyError):pass
                evidence=json.loads(source[5]) if qualified and source[5] else None
                entity_sources.append({'target_key':tk,'status':source[3] if source and (qualified or source[3]!='ok') else 'unavailable','period_start':source[1] if source else None,'period_end':source[2] if source else None,'source_at':evidence.get('source_at') if evidence else None,'config_epoch':source[0] if source else 0,'request':{'id':req['resource_id'],'version':req['version'],'state':req['state']} if req else None})
        return {'account_outcome_pending':bool(pending[0]),'unknown_pending':bool(pending[1]),'entity_sources':entity_sources,'unit':unitpublic,'spend':spendpublic,'selection':{'possibility_id':pid,'account_key':key},'operator_enabled':operator_enabled,'execution_enabled':False,'capabilities':{'can_edit':can_edit,'can_approve':can_approve,'can_stop':can_stop},'mandate':public(mandate,True) if mandate else None,'commands':[public(h) for h in heads if h['resource_type']=='command'],'selected_command':selected,'candidates':deepcopy(catalog.get('items',[])),'plan_ref':{'version':plan['version'],'state':plan['state']},'channels':{'status':row[0] if row and channels else 'unavailable','checked_at':row[1] if row else None,'request':next(({'id':h['resource_id'],'version':h['version'],'state':h['state']} for h in ([chosen] if chosen and chosen['resource_type']=='channels' else heads) if h['resource_type']=='channels'),None),'items':[{'key':k,'label':'사이트 채널 '+str(n+1),'type':'SITE','status':v['status']} for n,(k,v) in enumerate(channels.items())]},'source':{'status':catalog.get('status'),'period_start':catalog.get('period_start'),'period_end':catalog.get('period_end')}}


    def execution_lease_valid(self,rid,token,now,phase='dispatch'):
        """Read-only fresh guard, invoked immediately before each closed adapter request."""
        try:
            at=_S()._kst_text(now,'실행 lease');head=self._execution_head(rid)
            op=self._conn.execute('SELECT status,lease_token,lease_until FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
            statuses=('claimed',) if phase=='preflight' else ('dispatched',) if phase=='dispatch' else ('dispatched','unknown')
            if not head or not op or op[0] not in statuses or op[1]!=token or not op[2] or op[2]<=at:return False
            if phase=='reconcile':self._execution_context(head['possibility_id'],head['account_key'],self._execution_reconcile_actor(rid,head),now,stop=True)
            else:self._execution_binding_current(head,now)
            return True
        except Exception:return False

    def execution_release_claim(self,rid,token,now,reason='SOURCE_CHANGED'):
        self._need_writer();at=_S()._kst_text(now,'실행 차단')
        if reason not in ('SOURCE_CHANGED','PREFLIGHT_FAILED','ADAPTER_UNAVAILABLE'):reason='SOURCE_CHANGED'
        with self._tx() as c:
            op=c.execute('SELECT status,lease_token FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
            if op and op[0]=='claimed' and op[1]==token:self._execution_reject(c,self._execution_head(rid),at,reason);return True
        return False


    def _execution_reconcile_actor(self,rid,head):
        row=self._conn.execute('SELECT reconcile_actor FROM naver_auto_execution_operation WHERE command_id=?',(rid,)).fetchone()
        return row[0] if row and row[0] is not None else head['approved_by']

    def _execution_post_current(self,head,after,now):
        E=_E();_,_,_,plan,catalog,_=self._execution_context(head['possibility_id'],head['account_key'],head['approved_by'],now)
        command=head['command'];ref=command['approval_ref']
        if plan['state']!='approved' or plan['version']!=command['plan_version']:raise _S().StoreRefused('운영 기준 변경')
        if ref['kind']!='mandate':return True
        mandate=self._execution_head(ref['id'],head['possibility_id'],head['account_key'])
        if not mandate or mandate['state']!='approved' or mandate['version']!=ref['version']:raise _S().StoreRefused('위임 변경')
        epochs=self._execution_epochs(ref['id'])
        if epochs.get(command['target_key'],{}).get('epoch',0)!=command['config_epoch']:raise _S().StoreRefused('반영 판 변경')
        try:return E.current_mandate(mandate['binding'],plan,catalog,now,epochs=epochs)
        except (ValueError,TypeError):
            epochs[command['target_key']]={'epoch':command['config_epoch']+1,'target':after,'applied_at':now.isoformat()}
            return E.current_mandate(mandate['binding'],plan,catalog,now,epochs=epochs)

    def execution_record_spend(self,rid,payload,now,*,campaign_budget_proof=None):
        S=_S();self._need_writer();self._not_future(now,'지출 조회');at=S._kst_text(now,'지출 조회')
        with self._tx() as c:
            work=self.execution_channel_work(rid,now)
            if not work or 'period_start' not in work:return False
            fields={'status','customer_id','source_at','day','month','daily_spend','monthly_spend','risk_spend','risk_period_start','budget_unit','bid_cap_unit','campaigns'}
            if payload is not None:
                if not isinstance(payload,dict) or set(payload)!=fields or payload['status']!='ok' or payload['customer_id']!=work['customer_id'] or payload['day']!=now.astimezone(S.KST).date().isoformat() or payload['month']!=now.astimezone(S.KST).strftime('%Y-%m') or payload['risk_period_start']!=work['period_start'] or any(payload[k]!='unknown' for k in ('budget_unit','bid_cap_unit')) or not timedelta(0)<=now-moment(payload['source_at'])<=timedelta(minutes=15) or any(type(payload[k]) not in (int,float) or not math.isfinite(payload[k]) or payload[k]<0 for k in ('daily_spend','monthly_spend','risk_spend')) or not isinstance(payload['campaigns'],list) or len(payload['campaigns'])>100:raise S.StoreRefused('지출 원천의 범위와 시각을 확인해 주세요')
            stored=payload
            if payload is not None and campaign_budget_proof!=work.get('campaign_budget_proof'):
                raise S.StoreRefused('지출 조회에 봉인된 단건 예산 원천이 바뀌었습니다')
            if payload is not None and campaign_budget_proof is not None:
                from . import shared_budget_evidence as B
                proof=campaign_budget_proof
                B.validate(proof,now,scope={k:work[k] for k in ('possibility_id','customer_id','account_key','stage_revision')})
                expected=[dict(id=r['nccCampaignId'],daily_budget=r.get('dailyBudget'),use_daily_budget=r.get('useDailyBudget'),
                    shared_budget=False if B.resolved(r,proof,now)=='none' else None) for r in proof['campaigns']]
                if payload['campaigns']!=expected:raise S.StoreRefused('지출과 단건 예산 원천이 다릅니다')
                stored={'version':1,'spend':payload,'campaign_budget_proof':proof}
            status='ok' if payload is not None else 'failed'
            c.execute('INSERT INTO naver_auto_execution_spend VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(possibility_id,account_key,period_start) DO UPDATE SET customer_id=excluded.customer_id,stage_revision=excluded.stage_revision,plan_version=excluded.plan_version,period_start=excluded.period_start,status=excluded.status,checked_at=excluded.checked_at,payload_json=excluded.payload_json',(work['possibility_id'],work['account_key'],work['customer_id'],work['stage_revision'],work['plan_version'],work['period_start'],status,at,S._json(stored)))
            head=self._execution_head(rid);head.update(version=head['version']+1,state='confirmed' if status=='ok' else 'rejected');self._execution_save_head(c,head,at,'SPEND_'+status.upper());return True


    @staticmethod
    def _execution_campaign_fingerprint(obs):
        return _E().fingerprint(sorted([r['settings'] for r in (obs or {}).get('entities',{}).values() if r.get('entity')=='campaign'],key=lambda r:r.get('nccCampaignId','')))

    def _execution_unit(self,pid,key,catalog=None,*,obs=None,now):
        rows=_S()._rows(self._conn.execute("SELECT * FROM naver_auto_execution_resource WHERE possibility_id=? AND account_key=? AND resource_type='unit' ORDER BY updated_at DESC,resource_id DESC LIMIT 1",(pid,key)))
        if not rows:return {}
        h=_decode(rows[0]);b=h.get('binding')
        if h['state']!='approved' or not b:return {}
        if obs is None and catalog is not None:
            obs={'status':'ok' if catalog.get('status')=='ready' else 'unavailable','stale':catalog.get('status')!='ready','stage_revision':(catalog.get('scope') or {}).get('stage_revision'),'entities':{k:{'entity':v['kind'],'settings':v['settings']} for k,v in catalog.get('_arms',{}).items()}}
        if obs is None:obs=self.setup_observation(h['customer_id'],now)
        scope={k:((catalog or {}).get('scope') or {}).get(k) for k in ('possibility_id','customer_id','account_key','stage_revision')} if catalog else {'possibility_id':pid,'customer_id':h['customer_id'],'account_key':key,'stage_revision':(obs or {}).get('stage_revision')}
        if not obs or obs.get('status')!='ok' or obs.get('stale') or b['scope']!=scope or b['settings_fingerprint']!=self._execution_campaign_fingerprint(obs) or not timedelta(0)<=now-moment(b['checked_at'])<=timedelta(days=30):return {}
        if self.automation_plan(pid,key)['version']!=b['plan_version']:return {}
        return {'kind':'operator_verified','budget_unit':h['document']['budget_unit'],'bid_cap_unit':h['document']['bid_cap_unit'],'actor':b['actor'],'checked_at':b['checked_at']}

    def _execution_queue_source(self,c,head,kind,document,at):
        raw=_S()._json(document)
        if c.execute('SELECT 1 FROM naver_auto_execution_resource WHERE possibility_id=? AND account_key=? AND resource_type=? AND state=? AND document_json=?',(head['possibility_id'],head['account_key'],kind,'queued',raw)).fetchone():return
        rid=uuid.uuid4().hex
        if kind=='evidence':
            c.execute('INSERT INTO naver_auto_execution_evidence VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(mandate_id,target_key,config_epoch,period_start,period_end) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,payload_json=excluded.payload_json',(document['mandate_id'],document['target_key'],document['config_epoch'],document['period_start'],document['period_end'],'pending',at,'null'))
        elif kind=='spend':
            c.execute('INSERT INTO naver_auto_execution_spend VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(possibility_id,account_key,period_start) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,payload_json=excluded.payload_json',(head['possibility_id'],head['account_key'],head['customer_id'],document['stage_revision'],document['plan_version'],document['period_start'],'pending',at,'null'))
        queued=dict(resource_id=rid,resource_type=kind,possibility_id=head['possibility_id'],customer_id=head['customer_id'],account_key=head['account_key'],version=1,state='queued',document=document,binding=None,command=None,author=head['approved_by'],approved_by=None,approved_at=None,updated_at=at,next_evaluation_at=None,reasons=[])
        self._execution_save_head(c,queued,at,'SOURCE_QUEUED')

    def execution_evidence_work(self,rid,now):
        head=self._execution_head(rid)
        if not head or head['resource_type']!='evidence' or head['state']!='queued':return None
        doc=head['document'];mandate=self._execution_head(doc['mandate_id'],head['possibility_id'],head['account_key'])
        if not mandate or mandate['state']!='approved':return None
        try:_,_,_,epochs=self._execution_binding_current(mandate,now)
        except Exception:return None
        if doc['config_epoch']!=epochs.get(doc['target_key'],{}).get('epoch',0):return None
        return {'binding':mandate['binding'],'target_key':doc['target_key'],'epochs':epochs,'period_start':doc['period_start'],'period_end':doc['period_end']}

    def execution_record_evidence(self,rid,evidence,now):
        S=_S();E=_E();self._need_writer();at=S._kst_text(now,'대상 기간 조회')
        with self._tx() as c:
            work=self.execution_evidence_work(rid,now)
            if work is None:return False
            head=self._execution_head(rid);doc=head['document']
            if evidence is not None:
                if not isinstance(evidence,dict) or set(evidence)!=E.EVIDENCE_FIELDS or evidence['status']!='ok' or evidence['customer_id']!=head['customer_id'] or evidence['target_key']!=doc['target_key'] or evidence['config_epoch']!=doc['config_epoch'] or evidence['period_start']!=doc['period_start'] or evidence['period_end']!=doc['period_end'] or evidence['configuration_verified'] is not True or not timedelta(0)<=now-moment(evidence['source_at'])<=timedelta(minutes=work['binding']['document']['stop']['source_max_age_minutes']):raise S.StoreRefused('대상 성과 원천의 기간과 설정을 확인해 주세요')
            status='ok' if evidence is not None else 'failed'
            c.execute('INSERT INTO naver_auto_execution_evidence VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(mandate_id,target_key,config_epoch,period_start,period_end) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,payload_json=excluded.payload_json',(doc['mandate_id'],doc['target_key'],doc['config_epoch'],doc['period_start'],doc['period_end'],status,at,S._json(evidence)))
            head.update(version=head['version']+1,state='confirmed' if status=='ok' else 'rejected');self._execution_save_head(c,head,at,'EVIDENCE_'+status.upper())
            if status=='ok':
                c.execute('UPDATE naver_auto_execution_resource SET next_evaluation_at=? WHERE resource_id=?',(at,doc['mandate_id']))
            self._learning_attach_followup(c,doc['mandate_id'],doc['target_key'],doc['config_epoch'],evidence,now)
            return True


    def execution_source_abandon(self,rid,now):
        self._need_writer();at=_S()._kst_text(now,'원천 조회 차단')
        with self._tx() as c:
            head=self._execution_head(rid)
            if not head or head['resource_type'] not in ('channels','spend','evidence') or head['state']!='queued':return False
            head.update(version=head['version']+1,state='rejected',reasons=['SOURCE_CHANGED']);self._execution_save_head(c,head,at,'SOURCE_ABANDONED');return True
