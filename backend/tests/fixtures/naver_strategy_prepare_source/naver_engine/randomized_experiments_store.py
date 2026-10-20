"""Immutable randomized schedules, actual switch receipts and hourly observations."""
from copy import deepcopy
from datetime import date,datetime,time,timedelta
import json
import re
import uuid
from . import randomized_experiments as R

SCHEMA=(
'''CREATE TABLE IF NOT EXISTS naver_randomized_experiment (
 experiment_id TEXT PRIMARY KEY,possibility_id INTEGER NOT NULL,customer_id INTEGER NOT NULL,account_key TEXT NOT NULL,
 version INTEGER NOT NULL,protocol_version INTEGER NOT NULL,state TEXT NOT NULL,document_json TEXT NOT NULL,binding_json TEXT,
 author INTEGER NOT NULL,approved_by INTEGER,approved_at TEXT,updated_at TEXT NOT NULL,reasons_json TEXT NOT NULL)''',
'CREATE INDEX IF NOT EXISTS naver_randomized_scope ON naver_randomized_experiment(possibility_id,account_key,updated_at)',
'''CREATE TABLE IF NOT EXISTS naver_randomized_history (experiment_id TEXT NOT NULL,version INTEGER NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(experiment_id,version))''',
'''CREATE TABLE IF NOT EXISTS naver_randomized_receipt (request_id TEXT PRIMARY KEY,actor INTEGER NOT NULL,possibility_id INTEGER NOT NULL,account_key TEXT NOT NULL,body_hash TEXT NOT NULL,response_json TEXT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS naver_randomized_block (experiment_id TEXT NOT NULL,block_id TEXT PRIMARY KEY,day TEXT NOT NULL,pair_key TEXT NOT NULL,arm TEXT NOT NULL,state TEXT NOT NULL,schedule_json TEXT NOT NULL,reasons_json TEXT NOT NULL)''',
'CREATE INDEX IF NOT EXISTS naver_randomized_block_due ON naver_randomized_block(state,day,experiment_id)',
'''CREATE TABLE IF NOT EXISTS naver_randomized_command (command_id TEXT PRIMARY KEY,experiment_id TEXT NOT NULL,protocol_version INTEGER NOT NULL,block_id TEXT NOT NULL,step TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(block_id,step))''',
'''CREATE TABLE IF NOT EXISTS naver_randomized_switch (block_id TEXT NOT NULL,step TEXT NOT NULL,receipt_id TEXT NOT NULL,command_id TEXT,at TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(block_id,step))''',
'''CREATE TABLE IF NOT EXISTS naver_randomized_switch_event (receipt_id TEXT PRIMARY KEY,block_id TEXT NOT NULL,step TEXT NOT NULL,command_id TEXT,at TEXT NOT NULL,payload_json TEXT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS naver_randomized_probe (experiment_id TEXT PRIMARY KEY,source_fingerprint TEXT NOT NULL,status TEXT NOT NULL,checked_at TEXT NOT NULL,payload_json TEXT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS naver_randomized_job (job_key TEXT PRIMARY KEY,experiment_id TEXT NOT NULL,block_id TEXT,kind TEXT NOT NULL,day TEXT NOT NULL,status TEXT NOT NULL,checked_at TEXT NOT NULL,next_try_at TEXT NOT NULL,job_json TEXT NOT NULL,progress_json TEXT,error_code TEXT)''',
'CREATE INDEX IF NOT EXISTS naver_randomized_job_due ON naver_randomized_job(status,next_try_at,checked_at)',
'''CREATE TABLE IF NOT EXISTS naver_randomized_observation (block_id TEXT NOT NULL,revision INTEGER NOT NULL,checked_at TEXT NOT NULL,material_hash TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(block_id,revision))''',
'''CREATE TABLE IF NOT EXISTS naver_randomized_result (experiment_id TEXT NOT NULL,revision INTEGER NOT NULL,checked_at TEXT NOT NULL,material_hash TEXT NOT NULL,result_json TEXT NOT NULL,evidence_json TEXT NOT NULL,PRIMARY KEY(experiment_id,revision))''',
'''CREATE TABLE IF NOT EXISTS naver_randomized_scan_cursor (lane TEXT PRIMARY KEY,last_id TEXT NOT NULL,checked_at TEXT NOT NULL)''',
)
JOB_FIELDS=frozenset(('version job_key experiment_id protocol_version block_id kind day possibility_id customer_id account_key stage_revision plan_version source_fingerprint arms requested_at').split())
_UUID=re.compile(r'[0-9a-f]{32}\Z');_KEY=re.compile(r'[0-9a-f]{64}\Z')

def _S():
    from . import store
    return store

def _load(row):
    if row is None:return None
    out=dict(row)
    for key in ('document','binding','reasons'):
        raw=out.pop(key+'_json');out[key]=json.loads(raw) if raw else None
    return out

class RandomizedExperimentsStorage:
    def randomized_scan_heads(self,lane,now,states,limit=100,*,connection=None):
        """Writer-only bounded round robin; stable IDs prevent quiet heads starving others."""
        self._need_writer();self._not_future(now,'실험 순환 점검');now=R.moment(now)
        if lane not in ('advance','refresh') or not isinstance(states,(tuple,list)) or not states or any(s not in ('approved','running','hold','stopping') for s in states) or len(set(states))!=len(states) or type(limit)is not int or not 1<=limit<=100:raise _S().StoreRefused('실험 순환 점검 범위를 확인해 주세요')
        def scan(c):
            prior=c.execute('SELECT last_id FROM naver_randomized_scan_cursor WHERE lane=?',(lane,)).fetchone();last=prior[0] if prior else ''
            base='SELECT * FROM naver_randomized_experiment WHERE state IN ('+','.join('?' for _ in states)+')'
            rows=_S()._rows(c.execute(base+' AND experiment_id>? ORDER BY experiment_id LIMIT ?',(*states,last,limit)))
            if len(rows)<limit and last:
                rows+=_S()._rows(c.execute(base+' AND experiment_id<=? ORDER BY experiment_id LIMIT ?',(*states,last,limit-len(rows))))
            if rows:c.execute('INSERT INTO naver_randomized_scan_cursor VALUES(?,?,?) ON CONFLICT(lane) DO UPDATE SET last_id=excluded.last_id,checked_at=excluded.checked_at',(lane,rows[-1]['experiment_id'],now.isoformat()))
            return [_load(r) for r in rows]
        if connection is not None:return scan(connection)
        with self._tx() as c:return scan(c)

    def _randomized_head(self,eid,pid=None,key=None):
        sql='SELECT * FROM naver_randomized_experiment WHERE experiment_id=?';args=[eid]
        if pid is not None:sql+=' AND possibility_id=? AND account_key=?';args.extend((pid,key))
        return _load(next(iter(_S()._rows(self._conn.execute(sql,args))),None))

    def _randomized_save(self,c,h,now):
        h=deepcopy(h);h['updated_at']=R.moment(now).isoformat()
        keys=tuple(k for k in h if k not in ('document','binding','reasons'))+('document_json','binding_json','reasons_json')
        vals=[h[k] for k in keys[:-3]]+[_S()._json(h[k]) for k in ('document','binding','reasons')]
        c.execute('INSERT INTO naver_randomized_experiment('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+') ON CONFLICT(experiment_id) DO UPDATE SET '+','.join(k+'=excluded.'+k for k in keys if k!='experiment_id'),vals)
        c.execute('INSERT INTO naver_randomized_history VALUES(?,?,?)',(h['experiment_id'],h['version'],_S()._json(h)))

    def randomized_account_claimed(self,customer_id,*,exclude_id=None):
        # Hold retains exclusive ownership until explicit stop; unknown is not off.
        return self._conn.execute("SELECT 1 FROM naver_randomized_experiment WHERE customer_id=? AND state IN ('approved','running','hold','stopping') AND (? IS NULL OR experiment_id<>?) LIMIT 1",(customer_id,exclude_id,exclude_id)).fetchone() is not None

    def randomized_source_scope_current(self,pid,key,actor,now,stage_revision,plan_version):
        """Fresh authority for a formal experiment's GET-only source request."""
        try:
            rows=self._conn.execute("SELECT experiment_id FROM naver_randomized_experiment WHERE possibility_id=? AND account_key=? AND approved_by=? AND state IN ('approved','running') ORDER BY updated_at DESC LIMIT 2",(pid,key,actor)).fetchall()
            if len(rows)!=1:return False
            h=self._randomized_head(rows[0][0]);b=h['binding']
            if b['scope']['stage_revision']!=stage_revision or b['plan_version']!=plan_version:return False
            self._randomized_current(h,now);return True
        except Exception:return False

    def _randomized_current(self,h,now,*,stop=False):
        ctx,own,cid,plan,catalog,obs=self._execution_context(h['possibility_id'],h['account_key'],h['approved_by'] if h['approved_by'] is not None else h['author'],now,stop=stop)
        if cid!=h['customer_id']:R.fail()
        if not stop and h['binding']:
            if catalog.get('status')=='ready':R.current_binding(h['binding'],plan,catalog,now)
            else:
                # A fresh ERP/day generation may precede the morning settings collector.
                # Frozen settings are only GET expectations, never current observations.
                from . import experiments as X
                b=h['binding'];scope=b['scope']
                if not isinstance(obs,dict) or obs.get('status')!='pending' or obs.get('error_code') not in (None,'SOURCE_STALE') or any(obs.get(k)!=scope[k] for k in ('customer_id','possibility_id','stage_revision')):R.fail()
                if plan.get('version')!=b['plan_version'] or X._plan(plan)!=b['plan']:R.fail()
                latest=self._conn.execute('SELECT possibility_id,stage_revision,status,checked_at,progress_json,progress_hash FROM naver_auto_inspection_job WHERE customer_id=? ORDER BY generation DESC,checked_at DESC,rowid DESC LIMIT 1',(cid,)).fetchone()
                if not latest or tuple(latest[:3])!=(scope['possibility_id'],scope['stage_revision'],'ok') or R.moment(latest[3])>R.moment(now) or not latest[4]:R.fail()
                import hashlib
                if hashlib.sha256(latest[4].encode()).hexdigest()!=latest[5]:R.fail()
                progress=json.loads(latest[4])
                if not progress.get('confirmed') or progress.get('next_index')!=len(progress.get('queue',[])):R.fail()
        return ctx,own,cid,plan,catalog,obs

    def _randomized_overlay(self,h):
        b=deepcopy(h['binding'])
        for row in self._conn.execute('SELECT s.payload_json FROM naver_randomized_switch s JOIN naver_randomized_block x ON x.block_id=s.block_id WHERE x.experiment_id=? ORDER BY s.at,s.rowid',(h['experiment_id'],)):
            p=json.loads(row[0]);a=p.get('readback')
            if p.get('state')!='confirmed' or not a:continue
            for entity in b['group_entities']:
                if entity['kind']=='ad' and entity['id']==a.get('nccAdId'):
                    entity['settings']=deepcopy(a)
            for a2 in b['arms'].values():
                if a2['id']==a.get('nccAdId'):
                    a2['settings']=deepcopy(a)
        return b

    def _randomized_queue(self,c,h,kind,day,now,block_id=None):
        key='randomized:'+h['experiment_id']+':'+kind+':'+day
        b=h['binding'];scope=b['scope']
        job=dict(version=1,job_key=key,experiment_id=h['experiment_id'],protocol_version=h['protocol_version'],block_id=block_id,
            kind=kind,day=day,**scope,plan_version=b['plan_version'],source_fingerprint=b['source_fingerprint'],
            arms=deepcopy(b['arms']),requested_at=R.moment(now).isoformat())
        c.execute('INSERT INTO naver_randomized_job VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_key) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,next_try_at=excluded.next_try_at,job_json=excluded.job_json,progress_json=NULL,error_code=NULL',
            (key,h['experiment_id'],block_id,kind,day,'queued',R.moment(now).isoformat(),R.moment(now).isoformat(),_S()._json(job),None,None))
        return job

    def record_randomized_experiment(self,pid,key,actor,now,*,experiment_id,expected_version,request_id,action,document=None,probe_day=None):
        S=_S();self._need_writer();self._not_future(now,'무작위 실험');now=R.moment(now)
        if type(pid)is not int or pid<=0 or not isinstance(key,str) or not _KEY.fullmatch(key) or type(expected_version)is not int or expected_version<0 or not isinstance(request_id,str) or not _UUID.fullmatch(request_id) or experiment_id is not None and (not isinstance(experiment_id,str) or not _UUID.fullmatch(experiment_id)):raise S.StoreRefused('실험 요청 범위를 확인해 주세요')
        if action not in ('save','approve','stop','probe_request') or action!='save' and document is not None or action!='probe_request' and probe_day is not None:raise S.StoreRefused('실험 요청 항목을 확인해 주세요')
        body=R.digest(dict(experiment_id=experiment_id,expected_version=expected_version,action=action,document=document,probe_day=probe_day))
        with self._tx() as c:
            ctx,own,cid,plan,catalog,obs=self._execution_context(pid,key,actor,now,stop=action=='stop')
            old=c.execute('SELECT actor,possibility_id,account_key,body_hash,response_json FROM naver_randomized_receipt WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if tuple(old[:4])!=(actor,pid,key,body):raise S.StoreRefused('다른 요청에 사용된 식별자입니다')
                return json.loads(old[4])
            h=self._randomized_head(experiment_id,pid,key) if experiment_id else None
            if h is None and (experiment_id is not None or expected_version!=0 or action!='save') or h and h['version']!=expected_version:raise S.StoreRefused('현재 실험 판을 다시 확인해 주세요')
            if h and R.moment(h['updated_at'])>now:raise S.StoreRefused('이전 시각으로 실험을 변경할 수 없습니다')
            if action=='save':
                if h and h['state']!='draft':raise S.StoreRefused('승인된 배정 일정은 변경할 수 없습니다')
                try:doc=R.normalize_document(document)
                except ValueError as e:raise S.StoreRefused(str(e)) from None
                h=dict(experiment_id=experiment_id or uuid.uuid4().hex,possibility_id=pid,customer_id=cid,account_key=key,
                    version=(h['version'] if h else 0)+1,protocol_version=(h['protocol_version']+int(h['document']!=doc) if h else 1),
                    state='draft',document=doc,binding=None,author=(h['author'] if h else actor),approved_by=None,approved_at=None,updated_at=now.isoformat(),reasons=[])
            elif action=='stop':
                if not h['binding']:raise S.StoreRefused('승인된 실험의 중단 범위를 확인해 주세요')
                h['binding']['stop_actor']=actor;h['binding']['stopped_early']=now.date()<=R.day(R.period_end(h['document']))
                h.update(version=h['version']+1,state='stopping',reasons=['STOP_PENDING_PLATFORM_CONFIRMATION'])
                c.execute("UPDATE naver_randomized_job SET status='cancelled' WHERE experiment_id=? AND status<>'ok'",(h['experiment_id'],))
                self._randomized_stop_block(c,h,now)
            else:
                if h['state']!='draft':raise S.StoreRefused('저장한 실험 초안에서 진행해 주세요')
                try:b=R.bind_document(h['document'],plan,catalog,now)
                except ValueError as e:raise S.StoreRefused(str(e)) from None
                h['binding']=b
                if action=='probe_request':
                    d=R.day(probe_day)
                    if d>=now.date():raise S.StoreRefused('끝난 날짜의 시간 원천을 확인해 주세요')
                    self._randomized_queue(c,h,'probe',d.isoformat(),now)
                else:
                    from app.naver_auto import scope as SC
                    if plan['approval_requires_lead'] and not SC.can_approve(ctx.org,own,SC.LEVEL_LEAD,h['author'],actor):raise S.StoreRefused('현재 팀장 승인이 필요합니다')
                    if self.randomized_account_claimed(cid,exclude_id=h['experiment_id']):raise S.StoreRefused('같은 광고계정의 다른 무작위 실험을 먼저 중지해 주세요')
                    if c.execute("SELECT 1 FROM naver_auto_execution_resource r LEFT JOIN naver_auto_execution_operation o ON o.command_id=r.resource_id WHERE r.customer_id=? AND ((r.resource_type='mandate' AND r.state='approved') OR r.resource_type='command' AND (r.state IN ('approved','queued','dispatched','unknown','accepted') OR o.status IN ('claimed','dispatched','unknown'))) LIMIT 1",(cid,)).fetchone():raise S.StoreRefused('기존 자동 운영 위임과 미완료 명령을 먼저 정리해 주세요')
                    probe=c.execute('SELECT source_fingerprint,status,payload_json FROM naver_randomized_probe WHERE experiment_id=?',(h['experiment_id'],)).fetchone()
                    if not probe or probe[0]!=b['source_fingerprint'] or probe[1]!='ok' or not json.loads(probe[2]).get('verified'):raise S.StoreRefused('두 소재의 실제 24시간 원천 확인이 먼저 필요합니다')
                    unit=self._execution_unit(pid,key,catalog,obs=obs,now=now)
                    unitid=c.execute("SELECT resource_id FROM naver_auto_execution_resource WHERE possibility_id=? AND account_key=? AND resource_type='unit' ORDER BY updated_at DESC,resource_id DESC LIMIT 1",(pid,key)).fetchone()
                    unithead=self._execution_head(unitid[0]) if unitid else None
                    if not unithead or unithead['state']!='approved' or unit.get('budget_unit') not in ('vat_included_krw','vat_excluded_krw') or unit.get('bid_cap_unit')!='vat_excluded_krw':raise S.StoreRefused('현재 광고계정의 예산·입찰 단위를 먼저 명시 승인해 주세요')
                    spend=self.execution_account_spend(pid,cid,obs,now,period_start=b['plan']['period_start'])
                    if spend.get('status')!='ok' or spend.get('risk_period_start')!=b['plan']['period_start'] or not R.number(spend.get('risk_spend'),0) or not spend.get('source_at') or not timedelta(0)<=now-R.moment(spend['source_at'])<=timedelta(minutes=15):raise S.StoreRefused('현재 승인 계획의 실제 누적 지출을 먼저 조회해 주세요')
                    b['risk_baseline']=dict(risk_spend=spend['risk_spend'],source_at=spend['source_at'],period_start=b['plan']['period_start'])
                    if spend.get('budget_unit')!=unit['budget_unit'] or spend.get('bid_cap_unit')!=unit['bid_cap_unit']:raise S.StoreRefused('실제 지출과 승인한 단위 확인 자료가 다릅니다')
                    b['unit_ref']=dict(id=unithead['resource_id'],version=unithead['version'],checked_at=unithead['binding']['checked_at'],scope=deepcopy(unithead['binding']['scope']),plan_version=unithead['binding']['plan_version'],budget_unit=unit['budget_unit'],bid_cap_unit=unit['bid_cap_unit'])
                    b['schedule']=R.make_schedule(h['document'],experiment_id=h['experiment_id'])
                    b['schedule_fingerprint']=R.digest(b['schedule'])
                    h.update(state='approved',approved_by=actor,approved_at=now.isoformat(),binding=b)
                    for row in b['schedule']:
                        c.execute('INSERT INTO naver_randomized_block VALUES(?,?,?,?,?,?,?,?)',(h['experiment_id'],row['block_id'],row['day'],row['pair_key'],row['arm'],'planned',S._json(row),'[]'))
                h['version']+=1
            self._randomized_save(c,h,now)
            receipt=dict(experiment_id=h['experiment_id'],version=h['version'],protocol_version=h['protocol_version'],request_id=request_id)
            c.execute('INSERT INTO naver_randomized_receipt VALUES(?,?,?,?,?,?)',(request_id,actor,pid,key,body,S._json(receipt)))
            return receipt

    def randomized_recovery_receipt(self,pid,key,actor,request_id,now=None):
        from app.naver_auto import scope as SC
        if not isinstance(request_id,str) or not _UUID.fullmatch(request_id):raise _S().StoreRefused('요청 식별자를 확인해 주세요')
        from . import views as W,automation_views as AV
        ctx=W.load(self,now if now is not None else self._clock());AV.resolve(ctx,self,SC.scope_of(ctx.org,actor),pid,key)
        row=self._conn.execute('SELECT actor,possibility_id,account_key,response_json FROM naver_randomized_receipt WHERE request_id=?',(request_id,)).fetchone()
        if row is None:return None
        if tuple(row[:3])!=(actor,pid,key):raise SC.ClientNotVisible()
        return json.loads(row[3])

    def _randomized_register_command(self,c,ref,block_id,step,command_id,now):
        h=self._randomized_head(ref['id'])
        if not self.randomized_execution_current(ref,None,now,block_id=block_id,step=step):raise _S().StoreRefused('현재 블록 실행 조건이 바뀌었습니다')
        if not isinstance(command_id,str) or not _UUID.fullmatch(command_id):raise _S().StoreRefused('명령 식별자를 확인해 주세요')
        c.execute('INSERT INTO naver_randomized_command VALUES(?,?,?,?,?,?)',(command_id,h['experiment_id'],h['protocol_version'],block_id,step,R.moment(now).isoformat()))
        c.execute('UPDATE naver_randomized_block SET state=? WHERE block_id=?',({'pause_other':'pause_queued','activate_assigned':'activation_queued','stop_control':'stop_control_queued','stop_treatment':'stop_treatment_queued'}[step],block_id))

    def _randomized_command_ref(self,command_id):
        row=self._conn.execute('SELECT experiment_id,protocol_version,block_id,step FROM naver_randomized_command WHERE command_id=?',(command_id,)).fetchone()
        return None if not row else dict(ref=dict(kind='randomized_experiment_stop' if row[3] in ('stop_control','stop_treatment') else 'randomized_experiment',id=row[0],version=row[1]),block_id=row[2],step=row[3])

    def randomized_execution_current(self,ref,command,now,*,block_id=None,step=None):
        try:
            if not isinstance(ref,dict) or set(ref)!={'kind','id','version'} or ref['kind'] not in ('randomized_experiment','randomized_experiment_stop'):return False
            h=self._randomized_head(ref['id'])
            terminal=step in ('stop_control','stop_treatment')
            if command is not None:
                mapped=self._randomized_command_ref(command['command_id'])
                if mapped is None or mapped['ref']!=ref:return False
                block_id,step=mapped['block_id'],mapped['step'];terminal=step in ('stop_control','stop_treatment')
            if ref['kind']!=('randomized_experiment_stop' if terminal else 'randomized_experiment'):return False
            if not h or h['protocol_version']!=ref['version'] or h['state'] not in (('stopping','hold') if terminal else ('approved','running')):return False
            if terminal:
                actor=h['binding'].get('stop_actor',h['approved_by'])
                _,_,cid,_,_,_=self._execution_context(h['possibility_id'],h['account_key'],actor,now,stop=True)
                if cid!=h['customer_id'] or h['document']['end_policy']!='pause_both':return False
            else:self._randomized_current(h,now)
            if command is not None:
                if command['approval_ref']!=ref:return False
            row=self._conn.execute('SELECT state,schedule_json FROM naver_randomized_block WHERE block_id=? AND experiment_id=?',(block_id,h['experiment_id'])).fetchone()
            if row is None or step not in ('pause_other','activate_assigned','stop_control','stop_treatment'):return False
            block=json.loads(row[1]);now=R.moment(now)
            if bool(block.get('terminal',False))!=terminal:return False
            if not terminal and not R.moment(block['start_at'])<=now<R.moment(block['measurement_start_at']):return False
            allowed={'pause_other':('planned','pause_queued'),'activate_assigned':('paused','activation_queued'),
                'stop_control':('stop_planned','stop_control_queued'),'stop_treatment':('stop_control_confirmed','stop_treatment_queued')}
            if row[0] not in allowed[step]:return False
            if command is not None:
                name=step[5:] if terminal else block['arm'] if step=='activate_assigned' else ('control' if block['arm']=='treatment' else 'treatment')
                expected=h['binding']['arms'][name]
                if command['scope']!=h['binding']['scope'] or command['plan_version']!=h['binding']['plan_version'] or command['action']!='set_user_lock' or any(command['target'].get(k)!=expected[k] for k in ('kind','id','parent_id','campaign_id')) or command['target']['settings'].get('customerId')!=h['customer_id'] or command['payload']!={'userLock':step!='activate_assigned'}:return False
            return True
        except Exception:return False

    def randomized_execution_due(self,now,limit=1):
        now=R.moment(now);out=[]
        if type(limit)is not int or not 1<=limit<=24:raise _S().StoreRefused('실험 실행 조회 범위를 확인해 주세요')
        # Pure callbacks never advance a cursor. The writer's head scan already
        # rotates this stable ID anchor, so >100 ineligible heads cannot stay first.
        cursor=self._conn.execute("SELECT last_id FROM naver_randomized_scan_cursor WHERE lane='advance'").fetchone();last=cursor[0] if cursor else ''
        for row in _S()._rows(self._conn.execute("SELECT page.* FROM (SELECT b.*,CASE WHEN e.experiment_id>? THEN 0 ELSE 1 END AS scan_priority FROM naver_randomized_block b JOIN naver_randomized_experiment e ON e.experiment_id=b.experiment_id WHERE e.state IN ('approved','running','hold','stopping') AND b.state IN ('planned','paused','stop_planned','stop_control_confirmed') AND b.day<=? ORDER BY scan_priority,e.experiment_id,b.day,b.block_id LIMIT 100) page ORDER BY CASE WHEN page.state LIKE 'stop_%' THEN 0 ELSE 1 END,page.scan_priority,page.experiment_id,page.day,page.block_id",(last,now.date().isoformat()))):
            h=self._randomized_head(row['experiment_id']);block=json.loads(row['schedule_json'])
            terminal=block.get('terminal',False)
            if not terminal and now>=R.moment(block['measurement_start_at']):continue
            ref=dict(kind='randomized_experiment_stop' if terminal else 'randomized_experiment',id=h['experiment_id'],version=h['protocol_version'])
            step={'planned':'pause_other','paused':'activate_assigned','stop_planned':'stop_control','stop_control_confirmed':'stop_treatment'}[row['state']]
            if self.randomized_execution_current(ref,None,now,block_id=row['block_id'],step=step):
                out.append(dict(experiment_id=h['experiment_id'],version=h['version'],protocol_version=h['protocol_version'],block_id=row['block_id'],day=row['day'],arm=row['arm'],step=step,
                    approval_ref=ref,binding=self._randomized_overlay(h),actor=h['binding'].get('stop_actor',h['approved_by']) if terminal else h['approved_by'],deadline=None if terminal else block['measurement_start_at'],expected_user_lock=step!='activate_assigned'))
                if len(out)>=limit:break
        return out

    def _randomized_stop_block(self,c,h,now):
        bid=R.digest([h['experiment_id'],'terminal_pause'])[:32];at=R.moment(now).isoformat()
        block=dict(block_id=bid,pair_key=R.digest([h['experiment_id'],'terminal_pause']),day=R.moment(now).date().isoformat(),arm='control',start_at=at,measurement_start_at=at,end_at=at,terminal=True)
        c.execute('INSERT OR IGNORE INTO naver_randomized_block VALUES(?,?,?,?,?,?,?,?)',(h['experiment_id'],bid,block['day'],block['pair_key'],'control','stop_planned',_S()._json(block),'[]'))

    def randomized_advance(self,now):
        self._need_writer();now=R.moment(now);changed=0
        with self._tx() as c:
            rows=self.randomized_scan_heads('advance',now,('approved','running','hold','stopping'),connection=c)
            for h in rows:
                end=datetime.combine(R.day(R.period_end(h['document']))+timedelta(days=1),time(),R.KST)
                if h['state'] in ('approved','running') and c.execute("SELECT 1 FROM naver_randomized_block WHERE experiment_id=? AND state='applied' LIMIT 1",(h['experiment_id'],)).fetchone():
                    reason=None
                    try:self._randomized_current(h,now)
                    except Exception:reason='SOURCE_CHANGED'
                    spend=self.randomized_cap_spend(h['experiment_id'],now) if reason is None else None
                    if reason is None and spend is None:reason='SPEND_SOURCE_UNAVAILABLE'
                    elif reason is None and spend>=h['document']['experiment_spend_cap']:reason='BUDGET_STOP'
                    if reason:
                        h['binding']['stopped_early']=now<end;h.update(version=h['version']+1,state='hold',reasons=[reason]);self._randomized_save(c,h,now);changed+=1
                missed=c.execute("SELECT block_id,schedule_json FROM naver_randomized_block WHERE experiment_id=? AND state IN ('planned','pause_queued','paused','activation_queued') AND day<=?",(h['experiment_id'],now.date().isoformat())).fetchall()
                missed=[r for r in missed if now>=R.moment(json.loads(r[1])['measurement_start_at'])]
                if missed and h['state'] in ('approved','running'):
                    for r in missed:c.execute("UPDATE naver_randomized_block SET state='invalid',reasons_json=? WHERE block_id=?",(_S()._json(['MISSED_SWITCH_WINDOW']),r[0]))
                    h.update(version=h['version']+1,state='hold',reasons=['MISSED_SWITCH_WINDOW']);self._randomized_save(c,h,now);changed+=1
                if h['state']=='hold' or now>=end or h['state']=='stopping':
                    self._randomized_stop_block(c,h,now)
                    if h['state'] in ('approved','running'):
                        h.update(version=h['version']+1,state='stopping',reasons=['END_PAUSE_PENDING']);self._randomized_save(c,h,now);changed+=1
                for b in _S()._rows(c.execute("SELECT * FROM naver_randomized_block WHERE experiment_id=? AND state='applied' ORDER BY day",(h['experiment_id'],))):
                    if now.date()>R.day(b['day'])+timedelta(days=h['document']['measurement_lag_days']) and not c.execute("SELECT 1 FROM naver_randomized_job WHERE experiment_id=? AND kind='observation' AND day=?",(h['experiment_id'],b['day'])).fetchone():
                        self._randomized_queue(c,h,'observation',b['day'],now,b['block_id']);changed+=1
        return changed

    def randomized_cap_spend(self,experiment_id,now):
        try:
            h=self._randomized_head(experiment_id);_,_,cid,_,_,obs=self._randomized_current(h,now)
            baseline=h['binding']['risk_baseline'];source=self.execution_account_spend(h['possibility_id'],cid,obs,now,period_start=baseline['period_start'])
            if source.get('status')!='ok' or source.get('risk_period_start')!=baseline['period_start'] or not R.number(source.get('risk_spend'),0) or not source.get('source_at') or not timedelta(0)<=R.moment(now)-R.moment(source['source_at'])<=timedelta(minutes=15):return None
            delta=source['risk_spend']-baseline['risk_spend']
            return delta if R.number(delta,0) else None
        except Exception:return None

    def randomized_observed_spend(self,experiment_id):
        blocks=self._conn.execute("SELECT block_id FROM naver_randomized_block WHERE experiment_id=? AND state='applied'",(experiment_id,)).fetchall()
        if not blocks:return None
        total=0
        for b in blocks:
            row=self._conn.execute('SELECT payload_json FROM naver_randomized_observation WHERE block_id=? ORDER BY revision DESC LIMIT 1',(b[0],)).fetchone()
            if row is None:return None
            values=json.loads(row[0]);total+=sum(values[n]['summary']['salesAmt'] for n in ('control','treatment'))
        return total if R.number(total,0) else None

    def randomized_receipt_work(self,now,limit=100):
        return [r[0] for r in self._conn.execute('SELECT m.command_id FROM naver_randomized_command m LEFT JOIN naver_randomized_switch s ON s.command_id=m.command_id JOIN naver_auto_execution_operation o ON o.command_id=m.command_id WHERE o.status IN (\'confirmed\',\'unknown\',\'rejected\',\'cancelled\',\'stopped\') AND (s.command_id IS NULL OR json_extract(s.payload_json,\'$.journal_state\')<>o.status) ORDER BY m.created_at,m.command_id LIMIT ?',(min(max(limit,1),100),))]

    def randomized_record_switch(self,ref,block_id,step,receipt,now,*,command_id=None):
        """Ingest durable execution/read-only proof; intended settings never qualify."""
        from . import experiments as X
        S=_S();self._need_writer();now=R.moment(now)
        h=self._randomized_head(ref.get('id') if isinstance(ref,dict) else None)
        terminal=step in ('stop_control','stop_treatment')
        if not h or ref!={'kind':'randomized_experiment_stop' if terminal else 'randomized_experiment','id':h['experiment_id'],'version':h['protocol_version']}:raise S.StoreRefused('승인된 실험 판을 확인해 주세요')
        block=next(iter(S._rows(self._conn.execute('SELECT * FROM naver_randomized_block WHERE block_id=? AND experiment_id=?',(block_id,h['experiment_id'])))),None)
        if block is None or step not in ('pause_other','activate_assigned','stop_control','stop_treatment'):raise S.StoreRefused('실제 배정 블록을 확인해 주세요')
        if not isinstance(receipt,dict):raise S.StoreRefused('반영 영수증을 확인해 주세요')
        state=receipt.get('state');journal_state=state;schedule=json.loads(block['schedule_json'])
        if bool(schedule.get('terminal',False))!=terminal or terminal and h['document']['end_policy']!='pause_both':raise S.StoreRefused('승인된 종료 중단 범위를 확인해 주세요')
        if state not in ('confirmed','unknown','rejected','cancelled','stopped'):raise S.StoreRefused('확인되지 않은 실행 결과입니다')
        if command_id is not None:
            mapped=self._randomized_command_ref(command_id)
            if mapped!={'ref':ref,'block_id':block_id,'step':step}:raise S.StoreRefused('다른 실행 영수증입니다')
            op=self._conn.execute('SELECT status,confirmed_at,readback_json FROM naver_auto_execution_operation WHERE command_id=?',(command_id,)).fetchone()
            if not op or op[0]!=state:raise S.StoreRefused('원본 실행 원장의 결과가 다릅니다')
            rb=json.loads(op[2]) if op[2] else None
            if receipt.get('readback')!=rb or receipt.get('confirmed_at')!=op[1]:raise S.StoreRefused('원본 반영 조회가 다릅니다')
            at=R.moment(op[1]) if state=='confirmed' and op[1] else now;origin='execution_journal'
        else:
            if set(receipt)!={'state','origin','checked_at','readback'} or receipt['origin']!='read_only_preflight':raise S.StoreRefused('읽기 전용 조회 영수증을 확인해 주세요')
            rb=receipt['readback'];at=R.moment(receipt['checked_at']);origin='read_only_preflight'
            if now-at>timedelta(seconds=20):raise S.StoreRefused('현재 실제 설정을 다시 조회해 주세요')
        if at>now:raise S.StoreRefused('미래의 반영 조회는 사용할 수 없습니다')
        name=step[5:] if terminal else schedule['arm'] if step=='activate_assigned' else ('control' if schedule['arm']=='treatment' else 'treatment')
        expected=h['binding']['arms'][name];raw=None
        if state=='confirmed':
            try:
                if not isinstance(rb,dict) or set(rb)!={'state','reason_codes','target'} or rb['state']!='confirmed' or rb['reason_codes']!=[]:R.fail()
                arm=X.normalize_arm(rb['target'],h['customer_id'])
                if terminal:
                    if any(arm[k]!=expected[k] for k in ('kind','id','parent_id','campaign_id')):R.fail()
                elif R._material_arm(arm)!=R._material_arm(expected):R.fail()
                raw=arm['settings'];wanted=step!='activate_assigned'
                if raw.get('userLock') is not wanted or raw.get('status')!=('PAUSED' if wanted else 'ELIGIBLE'):R.fail()
            except (TypeError,ValueError,KeyError):
                # The underlying operation remains recorded, but cannot qualify assignment.
                state='unknown';raw=None
        payload=dict(state=state,journal_state=journal_state,origin=origin,checked_at=at.isoformat(),readback=deepcopy(raw))
        rid=R.digest([block_id,step,command_id,payload])
        with self._tx() as c:
            if c.execute('SELECT 1 FROM naver_randomized_switch_event WHERE receipt_id=?',(rid,)).fetchone():return state
            c.execute('INSERT INTO naver_randomized_switch_event VALUES(?,?,?,?,?,?)',(rid,block_id,step,command_id,at.isoformat(),S._json(payload)))
            c.execute('INSERT INTO naver_randomized_switch VALUES(?,?,?,?,?,?) ON CONFLICT(block_id,step) DO UPDATE SET receipt_id=excluded.receipt_id,command_id=excluded.command_id,at=excluded.at,payload_json=excluded.payload_json',(block_id,step,rid,command_id,at.isoformat(),S._json(payload)))
            # Facts survive authority loss, but no epoch/compliance is invented from them.
            current=True
            try:
                if terminal:
                    _,_,cid,_,_,_=self._execution_context(h['possibility_id'],h['account_key'],h['binding'].get('stop_actor',h['approved_by']),now,stop=True)
                    if cid!=h['customer_id']:R.fail()
                else:self._randomized_current(h,now)
            except Exception:current=False
            timely=terminal or R.moment(schedule['start_at'])<=at<R.moment(schedule['measurement_start_at'])
            prior=c.execute('SELECT payload_json FROM naver_randomized_switch WHERE block_id=? AND step=?',(block_id,'pause_other' if not terminal else 'stop_control')).fetchone()
            prerequisite=step in ('pause_other','stop_control') or prior is not None and json.loads(prior[0])['state']=='confirmed'
            if state=='confirmed' and current and timely and prerequisite and (terminal or block['state']!='invalid'):
                newstate={'pause_other':'paused','activate_assigned':'applied','stop_control':'stop_control_confirmed','stop_treatment':'closed'}[step]
                c.execute('UPDATE naver_randomized_block SET state=? WHERE block_id=?',(newstate,block_id))
                h.update(version=h['version']+1,state='stopped' if step=='stop_treatment' else ('running' if not terminal else h['state']))
                if step=='stop_treatment':h['reasons']=['PLATFORM_BOTH_PAUSED_CONFIRMED']
            else:
                if not terminal:c.execute("UPDATE naver_randomized_block SET state='invalid',reasons_json=? WHERE block_id=?",(S._json(['SWITCH_UNCONFIRMED' if timely else 'MISSED_SWITCH_WINDOW']),block_id))
                h.update(version=h['version']+1,state='hold',reasons=['SWITCH_UNCONFIRMED' if current else 'SOURCE_CHANGED'])
                self._randomized_stop_block(c,h,now)
            self._randomized_save(c,h,now)
        return state

    def randomized_work(self,now,limit=24):
        self._need_writer();self._not_future(now,'실험 원천 순환 점검');now=R.moment(now);out=[]
        if type(limit)is not int or not 1<=limit<=24:raise _S().StoreRefused('실험 원천 점검 범위를 확인해 주세요')
        with self._tx() as c:
            prior=c.execute("SELECT last_id FROM naver_randomized_scan_cursor WHERE lane='collection'").fetchone();last=prior[0] if prior else ''
            base="SELECT job_key,job_json FROM naver_randomized_job WHERE status IN ('queued','partial','retry','limited','reauth_required') AND next_try_at<=?"
            rows=c.execute(base+' AND job_key>? ORDER BY job_key LIMIT ?',(now.isoformat(),last,limit)).fetchall()
            if len(rows)<limit and last:rows+=c.execute(base+' AND job_key<=? ORDER BY job_key LIMIT ?',(now.isoformat(),last,limit-len(rows))).fetchall()
            if rows:c.execute("INSERT INTO naver_randomized_scan_cursor VALUES('collection',?,?) ON CONFLICT(lane) DO UPDATE SET last_id=excluded.last_id,checked_at=excluded.checked_at",(rows[-1][0],now.isoformat()))
        for _,raw in rows:
            job=json.loads(raw)
            if self.randomized_account_valid(job,now):out.append(job)
        return out

    def randomized_account_valid(self,job,now):
        try:
            if not isinstance(job,dict) or set(job)!=JOB_FIELDS:return False
            row=self._conn.execute('SELECT job_json,status FROM naver_randomized_job WHERE job_key=?',(job['job_key'],)).fetchone()
            if not row or json.loads(row[0])!=job or row[1]=='cancelled':return False
            h=self._randomized_head(job['experiment_id'])
            if not h or h['protocol_version']!=job['protocol_version'] or h['binding'] is None:return False
            _,_,_,_,_,_=self._randomized_current(h,now)
            b=h['binding']
            if {k:job[k] for k in b['scope']}!=b['scope'] or job['plan_version']!=b['plan_version'] or job['source_fingerprint']!=b['source_fingerprint'] or job['arms']!=b['arms']:return False
            if job['kind']=='probe':return h['state']=='draft'
            block=self._conn.execute('SELECT state,day FROM naver_randomized_block WHERE block_id=? AND experiment_id=?',(job['block_id'],h['experiment_id'])).fetchone()
            return bool(job['kind']=='observation' and block and block[0]=='applied' and block[1]==job['day'] and h['state'] in ('approved','running','stopping','stopped'))
        except Exception:return False

    def randomized_expected_settings(self,job,now):
        if not self.randomized_account_valid(job,now):raise _S().StoreRefused('현재 원천의 범위가 다릅니다')
        return self._randomized_overlay(self._randomized_head(job['experiment_id']))['group_entities']

    def begin_randomized_check(self,job,now):
        self._need_writer()
        if not self.randomized_account_valid(job,now):raise _S().StoreRefused('현재 실험 원천이 다릅니다')
        self._not_future(now,'무작위 실험 원천')

    def randomized_progress(self,job):
        row=self._conn.execute('SELECT progress_json FROM naver_randomized_job WHERE job_key=?',(job['job_key'],)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def record_randomized_progress(self,job,now,source):
        from . import randomized_experiments_reads as RR
        self._need_writer()
        if not self.randomized_account_valid(job,now):raise _S().StoreRefused('현재 실험 원천이 다릅니다')
        RR.validate_progress(source,job,now)
        with self._tx() as c:c.execute('UPDATE naver_randomized_job SET progress_json=?,checked_at=? WHERE job_key=?',(_S()._json(source),R.moment(now).isoformat(),job['job_key']))

    def record_randomized_check(self,job,now,values):
        from . import randomized_experiments_reads as RR
        self._need_writer();now=R.moment(now)
        if not self.randomized_account_valid(job,now):raise _S().StoreRefused('현재 실험 원천이 다릅니다')
        status=values.get('status')
        if status not in ('ok','partial','retry','limited','reauth_required'):raise _S().StoreRefused('원천 상태를 확인해 주세요')
        source=self.randomized_progress(job);payload=RR.validate_progress(source,job,now) if source else None
        if status=='ok' and payload is None:raise _S().StoreRefused('완결된 시간 원천이 없습니다')
        code=values.get('error_code');allowed={'SETTINGS_CHANGED','CHECKPOINT_INVALID','UNEXPECTED','REQUEST_DEADLINE','AUTH_FAILED','RATE_LIMITED','KEY_REJECTED','NETWORK','STATS_SHAPE_UNKNOWN'}
        code=code if code in allowed else None if code is None else 'UNEXPECTED'
        with self._tx() as c:
            c.execute('UPDATE naver_randomized_job SET status=?,checked_at=?,next_try_at=?,error_code=? WHERE job_key=?',(status,now.isoformat(),(now+timedelta(minutes=15 if status not in ('ok','partial') else 0)).isoformat(),code,job['job_key']))
            h=self._randomized_head(job['experiment_id'])
            if job['kind']=='probe':
                proof=R.validate_probe(payload['control'],payload['treatment'],now) if status=='ok' else dict(verified=False,day=job['day'])
                c.execute('INSERT INTO naver_randomized_probe VALUES(?,?,?,?,?) ON CONFLICT(experiment_id) DO UPDATE SET source_fingerprint=excluded.source_fingerprint,status=excluded.status,checked_at=excluded.checked_at,payload_json=excluded.payload_json',(h['experiment_id'],job['source_fingerprint'],status,now.isoformat(),_S()._json(proof)))
            elif status=='ok':
                material=deepcopy(payload)
                for arm in material.values():arm.pop('source_at',None)
                material['qualification']=dict(same_cycle=payload['control']['source_at']==payload['treatment']['source_at'],lag_mature=all(R.moment(a['source_at']).date()>=R.day(job['day'])+timedelta(days=1+h['document']['measurement_lag_days']) for a in payload.values()))
                digest=R.digest(material);last=c.execute('SELECT revision,material_hash FROM naver_randomized_observation WHERE block_id=? ORDER BY revision DESC LIMIT 1',(job['block_id'],)).fetchone()
                if not last or last[1]!=digest:c.execute('INSERT INTO naver_randomized_observation VALUES(?,?,?,?,?)',(job['block_id'],last[0]+1 if last else 1,now.isoformat(),digest,_S()._json(payload)))
                self._randomized_finalize(c,h,now)
            elif code in ('SETTINGS_CHANGED','CHECKPOINT_INVALID'):
                h.update(version=h['version']+1,state='hold',reasons=[code]);self._randomized_save(c,h,now);self._randomized_stop_block(c,h,now)
        return status

    def _randomized_finalize(self,c,h,now):
        from . import randomized_inference as RI
        evidence=self._randomized_evidence(h,now)
        if evidence is None:return
        try:result=RI.assess(R.inference_protocol(h['binding']),evidence,now=now)
        except (ValueError,TypeError,KeyError):return
        material=self._randomized_result_material(h,evidence,result)
        last=c.execute('SELECT revision,material_hash FROM naver_randomized_result WHERE experiment_id=? ORDER BY revision DESC LIMIT 1',(h['experiment_id'],)).fetchone()
        if not last or last[1]!=material:
            c.execute('INSERT INTO naver_randomized_result VALUES(?,?,?,?,?,?)',(h['experiment_id'],last[0]+1 if last else 1,R.moment(now).isoformat(),material,_S()._json(result),_S()._json(evidence)))
        self._learning_capture_event(c,'randomized_experiment',h['experiment_id'],now)

    def _randomized_result_material(self,h,evidence,result):
        sources=[];receipts=[]
        for row in self._conn.execute("SELECT block_id,state FROM naver_randomized_block WHERE experiment_id=? AND state='applied' ORDER BY day",(h['experiment_id'],)):
            obs=self._conn.execute('SELECT material_hash FROM naver_randomized_observation WHERE block_id=? ORDER BY revision DESC LIMIT 1',(row[0],)).fetchone()
            sources.append([row[0],row[1],obs[0] if obs else None])
            for step,command,raw in self._conn.execute('SELECT step,command_id,payload_json FROM naver_randomized_switch WHERE block_id=? ORDER BY step',(row[0],)):
                p=json.loads(raw);settings=deepcopy(p['readback'])
                if settings:settings.pop('editTm',None)
                receipts.append([row[0],step,command,p['state'],settings])
        return R.digest([h['binding']['schedule_fingerprint'],sources,receipts,evidence,result])

    def get_randomized_learning_source(self,experiment_id,now):
        """Qualified saved result only; no mutation, collection or model invocation."""
        from . import randomized_inference as RI
        try:
            h=self._randomized_head(experiment_id)
            if not h or h['state'] not in ('running','stopping','stopped'):return None
            self._randomized_current(h,now)
            evidence=self._randomized_evidence(h,now)
            if evidence is None:return None
            result=RI.assess(R.inference_protocol(h['binding']),evidence,now=now)
            material=self._randomized_result_material(h,evidence,result)
            row=self._conn.execute('SELECT revision,checked_at,material_hash,result_json,evidence_json FROM naver_randomized_result WHERE experiment_id=? ORDER BY revision DESC LIMIT 1',(experiment_id,)).fetchone()
            if not row or row[2]!=material:return None
            saved_result=RI.normalize_result(json.loads(row[3]));saved_evidence=json.loads(row[4])
            # The digest qualifies the saved payload too, not merely a fresh
            # calculation. Canonical JSON also distinguishes booleans from 1/0.
            if _S()._json(saved_result)!=_S()._json(result) or _S()._json(saved_evidence)!=_S()._json(evidence):return None
            if self._randomized_result_material(h,saved_evidence,saved_result)!=row[2]:return None
            totals={name:dict(impressions=0,clicks=0,spend=0) for name in ('control','treatment')};cycles=[]
            for block in self._conn.execute("SELECT block_id,arm FROM naver_randomized_block WHERE experiment_id=? AND state='applied' ORDER BY day",(experiment_id,)):
                obs=self._conn.execute('SELECT payload_json FROM naver_randomized_observation WHERE block_id=? ORDER BY revision DESC LIMIT 1',(block[0],)).fetchone()
                if not obs:return None
                hourly=json.loads(obs[0])[block[1]];cycles.append(hourly['source_at'])
                for hour in hourly['hours']:
                    if hour['hour']<h['document']['washout_hours']:continue
                    for name,field in (('impressions','impCnt'),('clicks','clkCnt'),('spend','salesAmt')):totals[block[1]][name]+=hour[field]
            if not cycles or any(not R.number(v,0) for metrics in totals.values() for v in metrics.values()):return None
            return dict(**h['binding']['scope'],registered_at=h['approved_at'],protocol_version=h['protocol_version'],plan_version=h['binding']['plan_version'],result_revision=row[0],material_fingerprint=row[2],recorded_at=row[1],source_at=min(cycles),period_start=h['document']['period_start'],period_end=R.period_end(h['document']),measurement_lag_days=h['document']['measurement_lag_days'],experiment_spend_cap=h['document']['experiment_spend_cap'],plan_goal=h['binding']['plan']['goal'],minimum_impressions_per_block=h['document']['minimum_impressions_per_block'],washout_hours=h['document']['washout_hours'],result=saved_result,totals=totals,observation_scope=['unobserved_targeting_landing_stability_assumed','sampling_lag_soft_spend_cap','constant_additive_effect_model_unverified'])
        except (ValueError,TypeError,KeyError):return None

    def _randomized_evidence(self,h,now):
        """No selective block deletion. Every registered date and receipt must qualify."""
        from . import randomized_inference as RI
        blocks=_S()._rows(self._conn.execute('SELECT * FROM naver_randomized_block WHERE experiment_id=? ORDER BY day,block_id',(h['experiment_id'],)))
        blocks=[b for b in blocks if not json.loads(b['schedule_json']).get('terminal')]
        expected=2*h['document']['pair_count'];frozen=h['binding'].get('schedule',[])
        assignment=len(blocks)==expected and len(frozen)==expected and h['binding'].get('schedule_fingerprint')==R.digest(frozen)
        compliance=assignment;complete=assignment;stable=True;pairmap={}
        for index,b in enumerate(blocks):
            schedule=json.loads(b['schedule_json']);assignment=assignment and index<len(frozen) and schedule==frozen[index] and b['arm']==schedule['arm'] and b['pair_key']==schedule['pair_key'] and b['day']==(R.day(h['document']['period_start'])+timedelta(days=index)).isoformat() and b['arm'] in ('control','treatment')
            compliance=compliance and b['state']=='applied' and not json.loads(b['reasons_json'])
            receipts={r[0]:json.loads(r[1]) for r in self._conn.execute('SELECT step,payload_json FROM naver_randomized_switch WHERE block_id=?',(b['block_id'],))}
            compliance=compliance and set(receipts)=={'pause_other','activate_assigned'} and all(p['state']=='confirmed' and R.moment(schedule['start_at'])<=R.moment(p['checked_at'])<R.moment(schedule['measurement_start_at']) for p in receipts.values())
            if compliance and R.moment(receipts['pause_other']['checked_at'])>R.moment(receipts['activate_assigned']['checked_at']):compliance=False
            source=self._conn.execute("SELECT status FROM naver_randomized_job WHERE experiment_id=? AND kind='observation' AND day=?",(h['experiment_id'],b['day'])).fetchone()
            last=self._conn.execute('SELECT payload_json FROM naver_randomized_observation WHERE block_id=? ORDER BY revision DESC LIMIT 1',(b['block_id'],)).fetchone()
            if not source or source[0]!='ok' or not last:complete=False;continue
            values=json.loads(last[0]);c,t=(R.normalize_hourly(values[name],now=now) for name in ('control','treatment'))
            mature=all(R.moment(v['source_at']).date()>=R.day(b['day'])+timedelta(days=1+h['document']['measurement_lag_days']) for v in (c,t))
            if c['source_at']!=t['source_at'] or not mature:complete=False
            assigned=values[b['arm']];other=values['control' if b['arm']=='treatment' else 'treatment'];washout=h['document']['washout_hours']
            measured=[r for r in assigned['hours'] if r['hour']>=washout];otherrows=[r for r in other['hours'] if r['hour']>=washout]
            imp=sum(r['impCnt'] for r in measured);clk=sum(r['clkCnt'] for r in measured)
            if imp<h['document']['minimum_impressions_per_block'] or any(r['impCnt'] or r['clkCnt'] or r['salesAmt'] for r in otherrows):complete=False
            pairmap.setdefault(b['pair_key'],[]).append(dict(day=b['day'],arm=b['arm'],imp=imp,clk=clk))
        pairs=[]
        for key,values in sorted(pairmap.items(),key=lambda kv:kv[1][0]['day']):
            if len(values)!=2 or {v['arm'] for v in values}!={'control','treatment'}:assignment=False;continue
            pairs.append(dict(pair_key=key,first=values[0],second=values[1]))
        # Pure validator requires full dates, so do not feed a partially selected subset.
        if len(pairs)!=h['document']['pair_count']:return None
        return dict(assignment_scheme='independent_fair_within_pair',assignment_verified=bool(assignment),compliance_complete=bool(compliance),source_complete=bool(complete),settings_stable=bool(stable),stopped_early=bool(h['binding'].get('stopped_early',False)),pairs=pairs)

    def randomized_projection(self,pid,key,actor,now,*,experiment_id=None,request_id=None):
        from app.naver_auto import scope as SC
        from . import views as W,automation_views as AV,experiments as X,handles as H,approval_documents as D,randomized_inference as RI
        ctx=W.load(self,now);scope=SC.scope_of(ctx.org,actor);company,cid=AV.resolve(ctx,self,scope,pid,key);own=AV.ownership(ctx,company)
        actions=SC.allowed_actions(ctx.org,scope,own);can_edit=SC.ACT_APPROVE in actions and H.stage_key(company['stage']) in D.AUTO_STAGES;can_stop=SC.ACT_STOP in actions
        plan=self.automation_plan(pid,key);observation=self.setup_observation(cid,now);catalog=X.candidate_catalog(observation,possibility_id=pid,customer_id=cid,account_key=key)
        receipt=self.randomized_recovery_receipt(pid,key,actor,request_id,now) if request_id else None
        if receipt:
            if experiment_id and experiment_id!=receipt['experiment_id']:raise _S().StoreRefused('저장된 실험의 범위가 다릅니다')
            experiment_id=receipt['experiment_id']
        heads=_S()._rows(self._conn.execute('SELECT experiment_id,version,protocol_version,state FROM naver_randomized_experiment WHERE possibility_id=? AND account_key=? ORDER BY updated_at DESC,experiment_id LIMIT 100',(pid,key)))
        if experiment_id is not None and not any(r['experiment_id']==experiment_id for r in heads):
            selected=self._randomized_head(experiment_id,pid,key)
            if not selected:raise SC.ClientNotVisible()
        else:selected=self._randomized_head(experiment_id or (heads[0]['experiment_id'] if heads else None),pid,key)
        public=None;approve=False;probe=False
        if selected:
            h=selected;current=False;reasons=list(h['reasons']);binding=None
            try:
                if h['binding']:R.current_binding(h['binding'],plan,catalog,now);current=True
                elif h['state']=='draft':binding=R.bind_document(h['document'],plan,catalog,now);current=True
            except (ValueError,TypeError,KeyError):
                if h['state']!='draft':reasons.append('SOURCE_CHANGED')
            proof=self._conn.execute('SELECT status,checked_at,payload_json,source_fingerprint FROM naver_randomized_probe WHERE experiment_id=?',(h['experiment_id'],)).fetchone()
            source_probe=dict(status=proof[0] if proof else 'unavailable',checked_at=proof[1] if proof else None,day=json.loads(proof[2]).get('day') if proof else None)
            probe=can_edit and h['state']=='draft' and current
            approve=probe and bool(proof and proof[0]=='ok' and proof[3]==(binding or h['binding'])['source_fingerprint'] and json.loads(proof[2]).get('verified'))
            if approve:
                unit=self._execution_unit(pid,key,catalog,obs=observation,now=now)
                unitid=self._conn.execute("SELECT resource_id FROM naver_auto_execution_resource WHERE possibility_id=? AND account_key=? AND resource_type='unit' ORDER BY updated_at DESC,resource_id DESC LIMIT 1",(pid,key)).fetchone()
                unithead=self._execution_head(unitid[0]) if unitid else None
                if not unithead or unithead['state']!='approved' or unit.get('budget_unit') not in ('vat_included_krw','vat_excluded_krw') or unit.get('bid_cap_unit')!='vat_excluded_krw':approve=False;reasons.append('UNIT_APPROVAL_REQUIRED')
                spend=self.execution_account_spend(pid,cid,observation,now,period_start=(binding or h['binding'])['plan']['period_start'])
                if spend.get('status')!='ok' or spend.get('risk_period_start')!=(binding or h['binding'])['plan']['period_start'] or not R.number(spend.get('risk_spend'),0) or not spend.get('source_at') or not timedelta(0)<=R.moment(now)-R.moment(spend['source_at'])<=timedelta(minutes=15):approve=False;reasons.append('SPEND_SOURCE_UNAVAILABLE')
                if self._conn.execute("SELECT 1 FROM naver_auto_execution_resource r LEFT JOIN naver_auto_execution_operation o ON o.command_id=r.resource_id WHERE r.customer_id=? AND ((r.resource_type='mandate' AND r.state='approved') OR r.resource_type='command' AND (r.state IN ('approved','queued','dispatched','unknown','accepted') OR o.status IN ('claimed','dispatched','unknown'))) LIMIT 1",(cid,)).fetchone():approve=False;reasons.append('EXECUTION_PENDING')
            if plan['approval_requires_lead']:approve=approve and SC.can_approve(ctx.org,own,SC.LEVEL_LEAD,h['author'],actor)
            if self.randomized_account_claimed(cid,exclude_id=h['experiment_id']):approve=False;reasons.append('ACCOUNT_CLAIMED')
            if h['state']=='draft' and source_probe['status']!='ok':reasons.append('HOURLY_PROBE_REQUIRED')
            jobs=_S()._rows(self._conn.execute('SELECT kind,status,error_code FROM naver_randomized_job WHERE experiment_id=? ORDER BY checked_at DESC,job_key LIMIT 32',(h['experiment_id'],)))
            status='unavailable' if not jobs else 'ok' if all(j['status']=='ok' for j in jobs) else next((j['status'] for j in jobs if j['status']!='ok'),'unavailable')
            source=self.get_randomized_learning_source(h['experiment_id'],now) if h['state'] in ('running','stopping','stopped') and status=='ok' else None
            result=source['result'] if source is not None else None
            if source is not None:reasons=[c for c in reasons if c!='SOURCE_CHANGED']
            schedule=[]
            for b in _S()._rows(self._conn.execute('SELECT * FROM naver_randomized_block WHERE experiment_id=? ORDER BY day,block_id',(h['experiment_id'],))):
                if json.loads(b['schedule_json']).get('terminal'):continue
                receipts={r[0]:json.loads(r[1]) for r in self._conn.execute('SELECT step,payload_json FROM naver_randomized_switch WHERE block_id=?',(b['block_id'],))}
                schedule.append(dict(block_id=b['block_id'],pair_key=b['pair_key'],day=b['day'],arm=b['arm'],state=b['state'],reason_codes=json.loads(b['reasons_json']),pause_confirmed_at=receipts.get('pause_other',{}).get('checked_at') if receipts.get('pause_other',{}).get('state')=='confirmed' else None,activation_confirmed_at=receipts.get('activate_assigned',{}).get('checked_at') if receipts.get('activate_assigned',{}).get('state')=='confirmed' else None))
            public=dict(id=h['experiment_id'],version=h['version'],protocol_version=h['protocol_version'],state=h['state'],document=deepcopy(h['document']),period_end=R.period_end(h['document']) if h['document']['period_start'] and h['document']['pair_count'] else None,binding_current=current,collection_status=status,source_current=source is not None,source_probe=source_probe,schedule=schedule,result=result,can_approve=approve,can_stop=can_stop and h['binding'] is not None and h['state'] not in ('stopped','draft'),can_probe=probe,hold_reasons=[dict(code=c,message=c) for c in sorted(set(reasons))],limitations=['unobserved_targeting_landing_stability_assumed','sampling_lag_soft_spend_cap','constant_additive_effect_model_unverified'])
        return dict(selection=dict(possibility_id=pid,account_key=key),plan_ref=dict(version=plan['version'],state=plan['state']),capabilities=dict(can_edit=can_edit,can_approve=approve,can_stop=can_stop,can_probe=probe),can_edit=can_edit,can_approve=approve,can_stop=can_stop,can_probe=probe,candidates=deepcopy(catalog.get('items',[])),experiments=[dict(id=r['experiment_id'],version=r['version'],protocol_version=r['protocol_version'],state=r['state']) for r in heads],selected=public,recovery_receipt=receipt)
