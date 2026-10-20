"""Explicit report-draft delegations, immutable periods and bounded network-free work.

Provider calls belong to the shared runtime gate. No JWT is persisted here.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import re
import uuid

from . import report_schedule as P

SCHEMA = (
    """CREATE INDEX IF NOT EXISTS naver_auto_report_schedule_snapshot
        ON naver_auto_report_snapshot(possibility_id,period_key,report_id)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_schedule (
        possibility_id INTEGER NOT NULL, account_key TEXT NOT NULL, version INTEGER NOT NULL,
        state TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(possibility_id,account_key))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_schedule_history (
        possibility_id INTEGER NOT NULL, account_key TEXT NOT NULL, version INTEGER NOT NULL,
        payload_json TEXT NOT NULL, PRIMARY KEY(possibility_id,account_key,version))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_schedule_cursor (
        possibility_id INTEGER NOT NULL, account_key TEXT NOT NULL, kind TEXT NOT NULL,
        period_key TEXT NOT NULL, next_check_at TEXT NOT NULL,
        PRIMARY KEY(possibility_id,account_key,kind))""",
    """CREATE INDEX IF NOT EXISTS naver_auto_report_schedule_cursor_due
        ON naver_auto_report_schedule_cursor(next_check_at,possibility_id,account_key,kind)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_schedule_period (
        possibility_id INTEGER NOT NULL, account_key TEXT NOT NULL, period_key TEXT NOT NULL,
        job_id TEXT NOT NULL UNIQUE, PRIMARY KEY(possibility_id,account_key,period_key))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_schedule_job (
        job_id TEXT PRIMARY KEY, version INTEGER NOT NULL, possibility_id INTEGER NOT NULL,
        account_key TEXT NOT NULL, state TEXT NOT NULL, next_check_at TEXT NOT NULL,
        payload_json TEXT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_report_schedule_job_due
        ON naver_auto_report_schedule_job(state,next_check_at,job_id)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS naver_auto_report_schedule_retry_parent
        ON naver_auto_report_schedule_job(json_extract(payload_json,'$.retry_of'))
        WHERE json_extract(payload_json,'$.retry_of') IS NOT NULL""",
    """CREATE INDEX IF NOT EXISTS naver_auto_report_schedule_job_scope
        ON naver_auto_report_schedule_job(possibility_id,account_key,job_id)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_schedule_job_history (
        job_id TEXT NOT NULL, version INTEGER NOT NULL, payload_json TEXT NOT NULL,
        PRIMARY KEY(job_id,version))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_schedule_receipt (
        request_id TEXT PRIMARY KEY, actor INTEGER NOT NULL, narrowed INTEGER NOT NULL,
        possibility_id INTEGER NOT NULL, account_key TEXT NOT NULL, operation TEXT NOT NULL,
        body_hash TEXT NOT NULL, response_json TEXT NOT NULL)""",
)
_ACTIVE = frozenset(('waiting','source_wait','queued','reserved','provider_started','response_received'))
_TERMINAL = frozenset(('draft_saved','failed','unknown','source_changed','cancelled','skipped'))
_RETRY = frozenset(('failed','unknown','source_changed'))
_UUID = re.compile(r'[0-9a-f]{32}\Z')
_KEY = re.compile(r'[0-9a-f]{64}\Z')


def _S():
    from . import store
    return store


def _at(now):
    return _S()._kst_text(now, '보고서 예약 시각')


def _json(value):
    return _S()._json(value)


def _refuse():
    raise _S().StoreRefused('보고서 예약의 최신 판과 현재 권한을 확인해 주세요')


def _identity(pid,key):
    if type(pid)is not int or not 0<pid<2**53 or not isinstance(key,str) or not _KEY.fullmatch(key):_refuse()


def _version(value):
    if type(value)is not int or not 0<=value<2**53:_refuse()


def _diagnostic(code):
    return {'code':code,'http_status':None}


class ReportScheduleStorage:
    def report_schedule(self,pid,key):
        _identity(pid,key)
        row=self._conn.execute('SELECT length(payload_json),substr(payload_json,1,4097) FROM naver_auto_report_schedule WHERE possibility_id=? AND account_key=?',(pid,key)).fetchone()
        if row is None:return {'version':0,'state':'empty','document':P.empty_document(),'actor':None,'narrowed':False,'approved_at':None,'updated_at':None}
        if row[0]>4096:_refuse()
        value=json.loads(row[1]);P.normalize_document(value['document']);_version(value['version'])
        if value['state'] not in ('draft','approved','disabled'):_refuse()
        return value

    def _schedule_save_head(self,c,pid,key,head):
        raw=_json(head)
        c.execute('INSERT INTO naver_auto_report_schedule_history VALUES(?,?,?,?)',(pid,key,head['version'],raw))
        c.execute('INSERT INTO naver_auto_report_schedule VALUES(?,?,?,?,?) ON CONFLICT(possibility_id,account_key) DO UPDATE SET version=excluded.version,state=excluded.state,payload_json=excluded.payload_json',(pid,key,head['version'],head['state'],raw))

    def report_schedule_job(self,job_id):
        if not isinstance(job_id,str) or not _UUID.fullmatch(job_id):_refuse()
        row=self._conn.execute('SELECT length(payload_json),substr(payload_json,1,8193) FROM naver_auto_report_schedule_job WHERE job_id=?',(job_id,)).fetchone()
        if row is None:return None
        if row[0]>8192:_refuse()
        return P.clean_job(json.loads(row[1]))

    def _schedule_save_job(self,c,job):
        job=P.clean_job(job);raw=_json(job)
        c.execute('INSERT INTO naver_auto_report_schedule_job_history VALUES(?,?,?)',(job['job_id'],job['version'],raw))
        c.execute('INSERT INTO naver_auto_report_schedule_job VALUES(?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET version=excluded.version,state=excluded.state,next_check_at=excluded.next_check_at,payload_json=excluded.payload_json',(job['job_id'],job['version'],job['possibility_id'],job['account_key'],job['state'],job['next_check_at'],raw))
        return job

    def _schedule_transition(self,c,job,state,now,*,diagnostic=None,**extra):
        return self._schedule_save_job(c,{**job,'version':job['version']+1,'state':state,'updated_at':_at(now),'diagnostic':diagnostic,**extra})

    def _schedule_current(self,job,now):
        head=self.report_schedule(job['possibility_id'],job['account_key'])
        if head['state']!='approved' or head['version']!=job['delegation_version'] or head['actor']!=job['actor'] or head['narrowed']!=job['narrowed']:_refuse()
        self._learning_actor(job['possibility_id'],job['account_key'],job['actor'],now,narrowed=job['narrowed'])
        return head

    def _schedule_existing_strategy(self,pid,key,period_key):
        return self._conn.execute("SELECT 1 FROM naver_auto_report_snapshot r JOIN naver_auto_meta m ON m.key='report-strategy-head:'||r.report_id||':'||? WHERE r.possibility_id=? AND r.period_key=? LIMIT 1",(key,pid,period_key)).fetchone() is not None

    def _schedule_source(self,job,now,*,existing=False):
        from . import report_views as RV
        self._schedule_current(job,now)
        row=self._conn.execute('SELECT report_id,revision_fingerprint,payload_json FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1',(job['possibility_id'],job['period_key'])).fetchone()
        dirty=self._conn.execute('SELECT pending FROM naver_auto_report_dirty WHERE possibility_id=? AND period_key=?',(job['possibility_id'],job['period_key'])).fetchone()
        strategy_exists=self._schedule_existing_strategy(job['possibility_id'],job['account_key'],job['period_key']) if not existing else False
        selected=RV._account_payload(json.loads(row[2]),job['account_key']) if row else None
        validation={}
        if row and selected is not None:
            states=self.report_refresh_states(row[0]) or {};members=RV._members(json.loads(row[2]));cid=members.get(job['account_key'])
            validation=((states.get('accounts') or {}).get(str(cid)) or {}).get('validation') or {}
        ready=P.readiness(selected,validation,latest=row is not None,dirty=bool(dirty and dirty[0]),strategy_exists=strategy_exists,period_key=job['period_key'],now=now)
        return row,ready

    def _schedule_prepare(self,job,now):
        row,ready=self._schedule_source(job,now)
        if ready['state']!='ready' or row[0]!=job['report_id'] or row[1]!=job['revision_fingerprint']:_refuse()
        prepared=self.prepare_learning_strategy(job['report_id'],job['account_key'],job['revision_fingerprint'],job['actor'],now,job['expected_strategy_version'],narrowed=job['narrowed'])
        if prepared['proof_hash']!=job['proof_hash']:_refuse()
        return prepared

    def report_schedule_receipt(self,pid,key,actor,narrowed,request_id):
        _identity(pid,key)
        if not isinstance(request_id,str) or not _UUID.fullmatch(request_id):_refuse()
        self._learning_actor(pid,key,actor,self._now(),narrowed=narrowed)
        row=self._conn.execute('SELECT actor,narrowed,possibility_id,account_key,response_json FROM naver_auto_report_schedule_receipt WHERE request_id=?',(request_id,)).fetchone()
        if row is None:return None
        if tuple(row[:4])!=(actor,int(narrowed),pid,key):
            from app.naver_auto import scope as SC
            raise SC.ClientNotVisible()
        return P.clean_receipt(json.loads(row[4]))

    def record_report_schedule(self,pid,key,actor,now,*,expected_version=None,request_id,action,document=None,job_id=None,expected_job_version=None,narrowed=False):
        self._need_writer();self._not_future(now,'보고서 예약');_identity(pid,key)
        request={'possibility_id':pid,'account_key':key,'request_id':request_id,'action':action}
        if action=='retry':request.update(job_id=job_id,expected_job_version=expected_job_version)
        else:request['expected_version']=expected_version
        if document is not None:request['document']=document
        try:clean=P.clean_request(request)
        except P.ScheduleInvalid:_refuse()
        digest=hashlib.sha256(_json(clean).encode()).hexdigest()
        with self._tx() as c:
            self._learning_actor(pid,key,actor,now,narrowed=narrowed)
            prior=c.execute('SELECT actor,narrowed,possibility_id,account_key,body_hash,response_json FROM naver_auto_report_schedule_receipt WHERE request_id=?',(request_id,)).fetchone()
            if prior:
                if tuple(prior[:5])!=(actor,int(narrowed),pid,key,digest):_refuse()
                return P.clean_receipt(json.loads(prior[5]))
            head=self.report_schedule(pid,key)
            if action=='retry':
                job=self.report_schedule_job(job_id)
                if not job or (job['possibility_id'],job['account_key'],job['version'])!=(pid,key,expected_job_version) or job['state'] not in _RETRY:_refuse()
                if head['state']!='approved' or c.execute("SELECT 1 FROM naver_auto_report_schedule_job WHERE json_extract(payload_json,'$.retry_of')=? LIMIT 1",(job_id,)).fetchone():_refuse()
                if self._schedule_existing_strategy(pid,key,job['period_key']):_refuse()
                child=self._schedule_new_job(c,pid,key,head,job['period_key'],now,origin='manual_retry',retry=job)
                self._schedule_transition(c,job,job['state'],now,diagnostic=job['diagnostic'])
                receipt={'request_id':request_id,'schedule_version':head['version'],'job_id':child['job_id'],'job_version':child['version']}
            else:
                if head['version']!=expected_version:_refuse()
                if action=='save':doc=P.normalize_document(document)
                else:
                    if head['version']==0 or action=='approve' and head['state']!='draft':_refuse()
                    doc=P.normalize_document(head['document'],approve=action=='approve')
                next_head={'version':head['version']+1,'state':{'save':'draft','approve':'approved','disable':'disabled'}[action],
                    'document':doc,'actor':actor,'narrowed':narrowed,'approved_at':_at(now) if action=='approve' else None,'updated_at':_at(now)}
                self._schedule_save_head(c,pid,key,next_head)
                pending=c.execute("SELECT job_id FROM naver_auto_report_schedule_job WHERE possibility_id=? AND account_key=? AND state IN ('waiting','source_wait','queued','reserved')",(pid,key)).fetchall()
                for item in pending:self._schedule_transition(c,self.report_schedule_job(item[0]),'cancelled',now,diagnostic=_diagnostic('delegation-changed'))
                if action=='approve':
                    for kind in ('weekly','monthly'):
                        if not doc[kind]:continue
                        period=P.first_period(kind,now)
                        prior_cursor=c.execute('SELECT period_key FROM naver_auto_report_schedule_cursor WHERE possibility_id=? AND account_key=? AND kind=?',(pid,key,kind)).fetchone()
                        if prior_cursor and P.period_from_key(prior_cursor[0]).start>period.start:period=P.period_from_key(prior_cursor[0])
                        c.execute('INSERT INTO naver_auto_report_schedule_cursor VALUES(?,?,?,?,?) ON CONFLICT(possibility_id,account_key,kind) DO UPDATE SET period_key=excluded.period_key,next_check_at=excluded.next_check_at',(pid,key,kind,period.key,period.due_at.isoformat()))
                receipt={'request_id':request_id,'schedule_version':next_head['version'],'job_id':None,'job_version':None}
            P.clean_receipt(receipt)
            c.execute('INSERT INTO naver_auto_report_schedule_receipt VALUES(?,?,?,?,?,?,?,?)',(request_id,actor,int(narrowed),pid,key,action,digest,_json(receipt)))
            return receipt

    def _schedule_new_job(self,c,pid,key,head,period_key,now,*,origin='automatic',retry=None):
        at=_at(now);job={'job_id':uuid.uuid4().hex,'version':1,'possibility_id':pid,'account_key':key,'delegation_version':head['version'],'actor':head['actor'],'narrowed':head['narrowed'],'period_key':period_key,'origin':origin,'retry_of':retry['job_id'] if retry else None,'retry_of_version':retry['version'] if retry else None,'state':'waiting','report_id':None,'revision_fingerprint':None,'expected_strategy_version':None,'proof_hash':None,'created_at':at,'updated_at':at,'next_check_at':at,'provider_started_at':None,'response_received_at':None,'result_version':None,'diagnostic':None}
        return self._schedule_save_job(c,job)

    def _schedule_skip_backlog(self,c,job,now):
        if job['origin']!='automatic' or job['state'] not in ('waiting','source_wait','queued'):return False
        head=self.report_schedule(job['possibility_id'],job['account_key'])
        if head['state']!='approved' or head['version']!=job['delegation_version']:return False
        period=P.period_from_key(job['period_key']);latest=P.latest_due(period.kind,head['approved_at'],now,cursor=job['period_key'])
        if latest['period'] is not None and latest['period']['period_key']!=job['period_key']:
            self._schedule_transition(c,job,'skipped',now,diagnostic=_diagnostic('resumed_backlog'));return True
        return False

    def _schedule_ready_job(self,c,job,now):
        try:
            if self._schedule_skip_backlog(c,job,now):return self.report_schedule_job(job['job_id'])
            row,ready=self._schedule_source(job,now)
            if ready['state']=='skip':return self._schedule_transition(c,job,'cancelled',now,diagnostic=_diagnostic('strategy-exists'))
            if ready['state']!='ready':return self._schedule_transition(c,job,'source_wait',now,diagnostic=_diagnostic('source-wait'),next_check_at=_at(now+timedelta(minutes=15)))
            prepared=self.prepare_learning_strategy(row[0],job['account_key'],row[1],job['actor'],now,0,narrowed=job['narrowed'])
            return self._schedule_transition(c,job,'queued',now,report_id=row[0],revision_fingerprint=row[1],expected_strategy_version=0,proof_hash=prepared['proof_hash'])
        except Exception:
            return self._schedule_transition(c,job,'source_changed',now,diagnostic=_diagnostic('context-changed'))

    def report_schedule_work(self,now,limit=10):
        self._need_writer();self._not_future(now,'보고서 예약')
        if type(limit)is not int or not 1<=limit<=10:_refuse()
        at=_at(now);created=0
        with self._tx() as c:
            due=c.execute("""SELECT next_check_at,0 lane,possibility_id,account_key,kind ident FROM naver_auto_report_schedule_cursor c WHERE next_check_at<=? AND EXISTS (SELECT 1 FROM naver_auto_report_schedule d WHERE d.possibility_id=c.possibility_id AND d.account_key=c.account_key AND d.state='approved' AND json_extract(d.payload_json,'$.document.'||c.kind)=1)
                UNION ALL SELECT next_check_at,1 lane,possibility_id,account_key,job_id ident FROM naver_auto_report_schedule_job WHERE state IN ('waiting','source_wait') AND next_check_at<=?
                ORDER BY next_check_at,lane,possibility_id,account_key,ident LIMIT ?""",(at,at,limit)).fetchall()
            for _,lane,pid,key,ident in due:
                if lane==0:
                    head=self.report_schedule(pid,key);cursor=c.execute('SELECT period_key FROM naver_auto_report_schedule_cursor WHERE possibility_id=? AND account_key=? AND kind=?',(pid,key,ident)).fetchone()
                    latest=P.latest_due(ident,head['approved_at'],now,cursor=cursor[0]);next_period=P.period_from_key(latest['next_cursor'])
                    c.execute('UPDATE naver_auto_report_schedule_cursor SET period_key=?,next_check_at=? WHERE possibility_id=? AND account_key=? AND kind=?',(next_period.key,next_period.due_at.isoformat(),pid,key,ident))
                    if latest['skipped_count']:
                        self._set_meta(c,f"report-schedule-backlog:{pid}:{key}:{ident}",_json({'skipped_count':latest['skipped_count'],'reason_codes':latest['reason_codes'],'at':at}))
                    if head['state']!='approved' or not head['document'][ident] or latest['period'] is None:continue
                    period=P.period_from_key(latest['period']['period_key'])
                    if self._conn.execute('SELECT 1 FROM naver_auto_report_schedule_period WHERE possibility_id=? AND account_key=? AND period_key=?',(pid,key,period.key)).fetchone():continue
                    job=self._schedule_new_job(c,pid,key,head,period.key,now);c.execute('INSERT INTO naver_auto_report_schedule_period VALUES(?,?,?,?)',(pid,key,period.key,job['job_id']));created+=1
                else:job=self.report_schedule_job(ident)
                if job and job['state'] in ('waiting','source_wait'):self._schedule_ready_job(c,job,now)
            queued=c.execute("SELECT job_id FROM naver_auto_report_schedule_job WHERE state='queued' ORDER BY next_check_at,job_id LIMIT 10").fetchall();launch=[]
            for row in queued:
                job=self.report_schedule_job(row[0])
                if self._schedule_skip_backlog(c,job,now):continue
                launch=[job];break
            return {'jobs':launch,'considered':len(due),'created':created}

    def report_schedule_reserve(self,job_id,expected_version,now,max_call,monthly,unlimited=False):
        self._need_writer();self._not_future(now,'보고서 예약')
        with self._tx() as c:
            job=self.report_schedule_job(job_id)
            if not job or job['version']!=expected_version or job['state']!='queued':_refuse()
            prepared=self._schedule_prepare(job,now)
            self._reserve_learning_call(c,prepared,job['actor'],now,job_id,max_call,monthly,unlimited=unlimited)
            job=self._schedule_transition(c,job,'reserved',now)
            return {'job':job,'prepared':prepared}

    def report_schedule_reserve_observed(self,job_id,expected_version,now,max_call,monthly,unlimited=False,*,trace_id):
        """The scheduled reservation, state and observation share one commit."""
        self._need_writer();self._not_future(now,'보고서 예약')
        with self._tx() as c:
            job=self.report_schedule_job(job_id)
            if not job or job['version']!=expected_version or job['state']!='queued':_refuse()
            prepared=self._schedule_prepare(job,now)
            self._reserve_learning_call(c,prepared,job['actor'],now,job_id,max_call,monthly,unlimited=unlimited)
            job=self._schedule_transition(c,job,'reserved',now)
            binding=self._begin_provider_observation(c,prepared,job['actor'],now,job_id,trace_id,'scheduled')
        return {'job':job,'prepared':prepared,'binding':binding}

    def report_schedule_started(self,job_id,expected_version,now):
        self._need_writer();self._not_future(now,'보고서 공급자 호출 시도')
        with self._tx() as c:
            job=self.report_schedule_job(job_id)
            if not job or job['version']!=expected_version or job['state']!='reserved':_refuse()
            self._schedule_prepare(job,now)
            return self._schedule_transition(c,job,'provider_started',now,provider_started_at=_at(now))

    def report_schedule_response(self,job_id,expected_version,now):
        self._need_writer();self._not_future(now,'보고서 응답')
        with self._tx() as c:
            job=self.report_schedule_job(job_id)
            if not job or job['version']!=expected_version or job['state']!='provider_started':_refuse()
            return self._schedule_transition(c,job,'response_received',now,response_received_at=_at(now))

    def report_schedule_finish(self,job_id,expected_version,generated,now):
        self._need_writer();self._not_future(now,'보고서 저장')
        with self._tx() as c:
            job=self.report_schedule_job(job_id)
            if not job or job['version']!=expected_version or job['state']!='response_received':_refuse()
            prepared=self._schedule_prepare(job,now)
            strategy=self._record_learning_strategy(c,prepared,generated,job['actor'],now)
            job=self._schedule_transition(c,job,'draft_saved',now,result_version=strategy['version'])
            return {'job':job,'strategy':strategy}

    def report_schedule_fail(self,job_id,expected_version,now,*,state,diagnostic):
        self._need_writer();self._not_future(now,'보고서 예약 상태')
        if state not in ('failed','unknown','source_changed','cancelled'):_refuse()
        with self._tx() as c:
            job=self.report_schedule_job(job_id)
            if not job or job['state'] not in _ACTIVE:return job
            if job['version']!=expected_version:_refuse()
            return self._schedule_transition(c,job,state,now,diagnostic=diagnostic)

    def report_schedule_recover(self,now):
        self._need_writer();self._not_future(now,'보고서 예약 복구')
        with self._tx() as c:
            rows=c.execute("SELECT job_id,state FROM naver_auto_report_schedule_job WHERE state IN ('reserved','provider_started','response_received')").fetchall()
            for jid,state in rows:self._schedule_transition(c,self.report_schedule_job(jid),'failed' if state=='reserved' else 'unknown',now,diagnostic=_diagnostic('worker-unavailable' if state=='reserved' else 'job-interrupted'))
            return {'unknown':sum(state!='reserved' for _,state in rows),'failed':sum(state=='reserved' for _,state in rows)}

    def report_schedule_projection(self,pid,key,actor,now,*,narrowed=False,request_id=None):
        _identity(pid,key);self._learning_actor(pid,key,actor,now,narrowed=narrowed)
        head=self.report_schedule(pid,key);current=True
        if head['state']=='approved':
            try:self._learning_actor(pid,key,head['actor'],now,narrowed=head['narrowed'])
            except Exception:current=False
        out={k:deepcopy(head[k]) for k in ('version','state','document','approved_at','updated_at')}
        out.update(current=current,can_edit=True,can_approve=head['state']=='draft' and any(head['document'].values()),can_disable=head['version']>0 and head['state']!='disabled',hold_reasons=[] if current else [{'code':'context-changed','message':'예약 승인자의 현재 권한을 확인해 주세요.'}])
        jobs=[]
        rows=self._conn.execute('SELECT job_id FROM naver_auto_report_schedule_job WHERE possibility_id=? AND account_key=? ORDER BY rowid DESC LIMIT 100',(pid,key)).fetchall()
        for row in rows:
            job=self.report_schedule_job(row[0]);public=P.public_job(job);public['can_retry']=job['state'] in _RETRY and head['state']=='approved' and not self._conn.execute("SELECT 1 FROM naver_auto_report_schedule_job WHERE json_extract(payload_json,'$.retry_of')=? LIMIT 1",(job['job_id'],)).fetchone() and not self._schedule_existing_strategy(pid,key,job['period_key']);jobs.append(public)
        return {'selection':{'possibility_id':pid,'account_key':key},'schedule':out,'jobs':jobs,
            'recovery_receipt':self.report_schedule_receipt(pid,key,actor,narrowed,request_id) if request_id is not None else None}
