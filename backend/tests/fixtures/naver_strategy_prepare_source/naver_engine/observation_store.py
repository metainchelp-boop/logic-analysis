"""Small immutable provider observations. No network, prompt or credential storage."""
from datetime import date, datetime, timedelta
import hashlib
import json
import re

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS naver_auto_provider_binding (
        trace_id TEXT PRIMARY KEY,job_id TEXT NOT NULL UNIQUE,actor INTEGER NOT NULL,
        possibility_id INTEGER NOT NULL,account_key TEXT NOT NULL,report_id INTEGER NOT NULL,
        origin TEXT NOT NULL,created_at TEXT NOT NULL,reserved_microusd INTEGER NOT NULL,
        proof_hash TEXT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_provider_binding_scope
        ON naver_auto_provider_binding(actor,possibility_id,account_key,created_at)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_provider_trace (
        trace_id TEXT NOT NULL,revision INTEGER NOT NULL,recorded_at TEXT NOT NULL,
        material_hash TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(trace_id,revision))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_provider_trace_head (
        trace_id TEXT PRIMARY KEY,revision INTEGER NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_provider_reservation_scope
        ON naver_auto_meta(json_extract(value,'$.actor'),json_extract(value,'$.possibility_id'),
            json_extract(value,'$.account_key'),json_extract(value,'$.at'))
        WHERE key LIKE 'learning-call:%'""",
)
ORIGINS = frozenset({'manual_sync','manual_async','scheduled'})
WINDOW = 100
PUBLIC_LIMIT = 20
VALIDATION_LIMIT = 1024

def _S():
    from . import store
    return store

def _uuid(value):return isinstance(value,str) and re.fullmatch(r'[0-9a-f]{32}',value) is not None
def _dump(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))
def _refuse():raise _S().StoreRefused('운영 관측의 결속 또는 형식을 확인해 주세요')


def _inspection_day(value):
    if not isinstance(value,str) or len(value)!=10 or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value) is None:
        return None
    try:
        date.fromisoformat(value)
        return value
    except ValueError:
        return None


def _inspection_at(value,now=None):
    # Inspection writers use canonical KST timestamps. Never echo arbitrary metadata.
    if not isinstance(value,str) or not 25<=len(value)<=32 or re.fullmatch(
            r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?\+09:00',value) is None:
        return None
    try:
        at=datetime.fromisoformat(value)
        return value if now is None or at<=now else None
    except (TypeError,ValueError):
        return None


def _inspection_stored_job(row,now):
    """Closed historical cursor facts; no current-source validation or authority."""
    from . import inspection_reads as R, inspection_store as I, observation_views as V
    out={'version':1,'scope':'stored_only','current_source_not_proven':True,
         'cycle_kind':row['kind'] if row['kind'] in ('daily','weekly','manual') else None,
         'cycle_day':_inspection_day(row['cycle_day']),
         'generation':_inspection_at(row['generation'],now),
         'next_try_at':_inspection_at(row['next_try_at']),
         'attempts':V.public_number(row['attempts']),
         'checkpoint_state':'missing' if row['progress_missing'] else 'invalid','checkpoint':None}
    if row['progress_missing']:
        return out
    try:
        checked=_inspection_at(row['checked_at'],now)
        start,end=_inspection_day(row['period_start']),_inspection_day(row['period_end'])
        if (any(out[name] is None for name in ('cycle_kind','cycle_day','generation','next_try_at'))
                or checked is None or start is None or end is None
                or not start<=end<out['cycle_day']
                or datetime.fromisoformat(out['generation']).date().isoformat()!=out['cycle_day']
                or not datetime.fromisoformat(out['generation'])<=datetime.fromisoformat(checked)<=datetime.fromisoformat(out['next_try_at'])):
            return out
        raw,digest=row['progress_json'],row['progress_hash']
        if (not isinstance(raw,str) or len(raw.encode('utf8'))>R.MAX_BYTES
                or not isinstance(digest,str) or re.fullmatch(r'[0-9a-f]{64}',digest) is None
                or hashlib.sha256(raw.encode('utf8')).hexdigest()!=digest):
            return out
        progress=R.validate_progress(json.loads(raw),row)
        if any(datetime.fromisoformat(at)>now for at in I._observed_times(progress)):
            return out
        index,queue=progress['next_index'],progress['queue']
        out.update(checkpoint_state='validated',checkpoint={'next_index':index,'queue_len':len(queue),
            'current_task_kind':queue[index]['kind'] if index<len(queue) else None,'confirmed':progress['confirmed']})
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError):
        pass  # Corrupt optional diagnostics cannot change collection or report state.
    return out


class ObservationStorage:
    def begin_provider_observation(self,prepared,actor,now,job_id,trace_id,origin):
        """Bind only an already reserved server call; this grants no call authority."""
        self._need_writer();self._not_future(now,'운영 관측')
        if not _uuid(job_id) or not _uuid(trace_id) or origin not in ORIGINS or type(actor)is not int or actor<0 or not isinstance(prepared,dict):_refuse()
        with self._tx() as c:
            self._begin_provider_observation(c,prepared,actor,now,job_id,trace_id,origin)
        return {'bound':True}

    def _begin_provider_observation(self,c,prepared,actor,now,job_id,trace_id,origin):
        # The caller owns the single transaction, including the reservation.
        self._need_writer();self._not_future(now,'운영 관측')
        if not _uuid(job_id) or not _uuid(trace_id) or origin not in ORIGINS or type(actor)is not int or actor<0 or not isinstance(prepared,dict):_refuse()
        row=c.execute('SELECT value FROM naver_auto_meta WHERE key=?',('learning-call:'+job_id,)).fetchone()
        if row is None:_refuse()
        reservation=json.loads(row[0])
        report_id,key=prepared.get('report_id'),prepared.get('account_key')
        if type(report_id)is not int or report_id<=0 or not isinstance(key,str) or not re.fullmatch(r'[0-9a-f]{64}',key):_refuse()
        report=c.execute('SELECT possibility_id FROM naver_auto_report_snapshot WHERE report_id=?',(report_id,)).fetchone()
        if (report is None or reservation.get('actor')!=actor or reservation.get('proof_hash')!=prepared.get('proof_hash')
                or reservation.get('report_id')!=report_id or reservation.get('account_key')!=key
                or reservation.get('possibility_id')!=report[0]):_refuse()
        if origin=='scheduled':
            job=self.report_schedule_job(job_id)
            if not job or (job['actor'],job['report_id'],job['account_key'])!=(actor,report_id,key):_refuse()
        elif origin=='manual_async':
            job=self.learning_strategy_job(job_id=job_id)
            if not job or (job['actor'],job['report_id'],job['account_key'])!=(actor,report_id,key):_refuse()
        elif self.report_schedule_job(job_id) is not None or self.learning_strategy_job(job_id=job_id) is not None:_refuse()
        values=(trace_id,job_id,actor,report[0],key,report_id,origin,reservation['at'],reservation['reserved_microusd'],prepared['proof_hash'])
        prior=c.execute('SELECT * FROM naver_auto_provider_binding WHERE trace_id=? OR job_id=?',(trace_id,job_id)).fetchall()
        if prior:
            if len(prior)!=1 or tuple(prior[0])!=values:_refuse()
        else:c.execute('INSERT INTO naver_auto_provider_binding VALUES(?,?,?,?,?,?,?,?,?,?)',values)
        return {'bound':True}

    def record_provider_observation(self,trace_id,snapshot,now):
        """A prior immutable binding preserves late outcomes after authority changes."""
        from naver_runtime import provider_observability as P
        self._need_writer();self._not_future(now,'운영 관측')
        try:clean=P.normalize_snapshot(snapshot)
        except Exception:_refuse()
        if not _uuid(trace_id) or clean['trace_id']!=trace_id:_refuse()
        for event in clean['events']:
            if datetime.fromisoformat(event['at'])>now+timedelta(minutes=5):_refuse()
        raw=_dump(clean)
        if len(raw.encode('utf8'))>32768:_refuse()
        digest=hashlib.sha256(raw.encode()).hexdigest()
        with self._tx() as c:
            if not c.execute('SELECT 1 FROM naver_auto_provider_binding WHERE trace_id=?',(trace_id,)).fetchone():_refuse()
            prior=c.execute('SELECT h.revision,t.material_hash,t.payload_json FROM naver_auto_provider_trace_head h JOIN naver_auto_provider_trace t ON t.trace_id=h.trace_id AND t.revision=h.revision WHERE h.trace_id=?',(trace_id,)).fetchone()
            if prior and prior[1]==digest:return {'recorded':True,'revision':prior[0]}
            if prior:
                old=json.loads(prior[2])
                if (clean['events'][:len(old['events'])]!=old['events'] or len(clean['events'])==len(old['events'])
                        or not any(event['phase']=='usage_parsed' for event in clean['events'][len(old['events']):])
                        and (clean['usage']!=old['usage'] or clean['estimate']!=old['estimate'])):_refuse()
            revision=(prior[0] if prior else 0)+1
            if revision>8:_refuse()
            c.execute('INSERT INTO naver_auto_provider_trace VALUES(?,?,?,?,?)',(trace_id,revision,now.isoformat(),digest,raw))
            c.execute('INSERT INTO naver_auto_provider_trace_head VALUES(?,?) ON CONFLICT(trace_id) DO UPDATE SET revision=excluded.revision',(trace_id,revision))
        return {'recorded':True,'revision':revision}

    def record_provider_validation(self,trace_id,summary,now):
        """Immutable closed failure facts, separate from the unchanged trace ABI."""
        from naver_runtime import provider_observability as P
        from . import strategy_validation as V
        self._need_writer();self._not_future(now,'운영 관측')
        try:clean=V.normalize(summary)
        except Exception:_refuse()
        if not _uuid(trace_id):_refuse()
        raw=_dump(clean)
        if len(raw.encode('utf8'))>VALIDATION_LIMIT:_refuse()
        with self._tx() as c:
            row=c.execute('''SELECT t.payload_json FROM naver_auto_provider_binding b
                JOIN naver_auto_provider_trace_head h ON h.trace_id=b.trace_id
                JOIN naver_auto_provider_trace t ON t.trace_id=h.trace_id AND t.revision=h.revision
                WHERE b.trace_id=? AND length(CAST(t.payload_json AS BLOB))<=32768''',(trace_id,)).fetchone()
            try:trace=P.normalize_snapshot(json.loads(row[0])) if row else None
            except Exception:_refuse()
            if (trace is None or trace['trace_id']!=trace_id
                    or not any(event['phase']=='failure' and event['diagnostic']==P.diagnostic(V.ERROR_CODES[clean['rule']]) for event in trace['events'])
                    or any(event['phase'] in {'document_validated','draft_saved'} for event in trace['events'])):_refuse()
            key='provider-validation:'+trace_id
            prior=c.execute('SELECT value FROM naver_auto_meta WHERE key=?',(key,)).fetchone()
            if prior:
                if prior[0]!=raw:_refuse()
            else:c.execute('INSERT INTO naver_auto_meta VALUES(?,?)',(key,raw))
        return {'recorded':True}

    def learning_strategy_validation(self, job):
        """Optional compiler facts for the exact persisted failed job; read only."""
        from naver_runtime import learning_jobs as J, provider_observability as P
        from . import strategy_validation as V
        try:
            job = J.clean(job)
            if job['state'] != 'failed' or job['diagnostic'] != {'code':'document-invalid','http_status':None}:
                return None
            identity = J.PREFIX+J.identity(job['actor'], job['narrowed'], job['report_id'],
                job['account_key'], job['revision_fingerprint'], job['expected_version'])
            row = self._conn.execute('''SELECT j.value,b.trace_id,b.created_at,b.reserved_microusd,
                b.possibility_id,q.value,r.revision_fingerprint,t.payload_json,t.material_hash,v.value
                FROM naver_auto_provider_binding b
                JOIN naver_auto_meta j ON j.key=?
                JOIN naver_auto_meta q ON q.key='learning-call:'||b.job_id
                JOIN naver_auto_report_snapshot r ON r.report_id=b.report_id AND r.possibility_id=b.possibility_id
                JOIN naver_auto_provider_trace_head h ON h.trace_id=b.trace_id
                JOIN naver_auto_provider_trace t ON t.trace_id=h.trace_id AND t.revision=h.revision
                JOIN naver_auto_meta v ON v.key='provider-validation:'||b.trace_id
                WHERE b.job_id=? AND b.actor=? AND b.report_id=? AND b.account_key=? AND b.proof_hash=?
                    AND b.origin='manual_async' AND length(CAST(j.value AS BLOB))<=4096
                    AND length(CAST(q.value AS BLOB))<=4096 AND length(CAST(t.payload_json AS BLOB))<=32768
                    AND length(CAST(v.value AS BLOB))<=1024''', (identity,job['job_id'],job['actor'],
                    job['report_id'],job['account_key'],job['proof_hash'])).fetchone()
            if row is None or J.clean(json.loads(row[0])) != job or row[6] != job['revision_fingerprint']:
                return None
            reservation = json.loads(row[5])
            expected = {'actor':job['actor'], 'at':row[2], 'reserved_microusd':row[3],
                'proof_hash':job['proof_hash'], 'report_id':job['report_id'], 'account_key':job['account_key'],
                'possibility_id':row[4]}
            if (type(reservation) is not dict or reservation != expected
                    or type(row[3]) is not int or not 0 < row[3] <= 10**12
                    or type(row[4]) is not int or row[4] <= 0
                    or any(type(reservation[key]) is not int for key in ('actor','reserved_microusd','report_id','possibility_id'))
                    or not datetime.fromisoformat(job['created_at']) <= datetime.fromisoformat(row[2]) <= datetime.fromisoformat(job['updated_at'])):
                return None
            trace = P.normalize_snapshot(json.loads(row[7]))
            summary = V.normalize(json.loads(row[9]))
            if (not V.proposal_pair(summary) or trace['trace_id'] != row[1]
                    or hashlib.sha256(row[7].encode()).hexdigest() != row[8]
                    or any(event['phase'] in {'document_validated','draft_saved'} for event in trace['events'])
                    or not any(event['phase']=='failure' and event['diagnostic']==P.diagnostic('DOCUMENT_INVALID')
                        and datetime.fromisoformat(row[2]) <= datetime.fromisoformat(event['at']) <= datetime.fromisoformat(job['updated_at'])
                        for event in trace['events'])):
                return None
            return summary
        except Exception:
            return None  # Missing/corrupt optional observations cannot change job state.

    def operations_observations(self,pid,key,cid,actor,now):
        """Selected account aggregates only; callers must resolve current permissions."""
        from . import observation_views as V
        args=(actor,pid,key)
        reservations=self._conn.execute("""SELECT substr(key,15),json_extract(value,'$.reserved_microusd'),json_extract(value,'$.at')
            FROM naver_auto_meta WHERE key LIKE 'learning-call:%' AND json_extract(value,'$.actor')=?
            AND json_extract(value,'$.possibility_id')=? AND json_extract(value,'$.account_key')=?
            ORDER BY json_extract(value,'$.at') DESC,key DESC LIMIT ?""",(*args,WINDOW+1)).fetchall()
        rows=self._conn.execute('''SELECT b.job_id,b.origin,b.created_at,b.reserved_microusd,
            CASE WHEN length(CAST(t.payload_json AS BLOB))<=32768 THEN t.payload_json ELSE NULL END,r.period_key,
            CASE WHEN length(CAST(v.value AS BLOB))<=1024 THEN v.value ELSE NULL END
            FROM naver_auto_provider_binding b LEFT JOIN naver_auto_provider_trace_head h ON h.trace_id=b.trace_id
            LEFT JOIN naver_auto_provider_trace t ON t.trace_id=h.trace_id AND t.revision=h.revision
            LEFT JOIN naver_auto_meta v ON v.key='provider-validation:'||b.trace_id
            JOIN naver_auto_report_snapshot r ON r.report_id=b.report_id
            WHERE b.actor=? AND b.possibility_id=? AND b.account_key=? ORDER BY b.created_at DESC,b.job_id DESC LIMIT ?''',(*args,WINDOW)).fetchall()
        legacy=self._conn.execute("SELECT EXISTS(SELECT 1 FROM naver_auto_meta WHERE key LIKE 'learning-call:%' AND json_extract(value,'$.actor')=? AND json_extract(value,'$.possibility_id') IS NULL)",(actor,)).fetchone()[0]
        provider=V.provider_projection(reservations,rows,legacy=bool(legacy))
        allowed_states={'empty','draft','approved','stopped','cancelled','waiting','source_wait','queued','reserved','provider_started','response_received','draft_saved','failed','unknown','source_changed','skipped','pending','reading','partial','ok','stale','unavailable','dispatched','accepted','rejected','confirmed','mismatch','planned','ready','observed','hold','superseded'}
        def counts(sql,params):
            result={}
            for state,count in self._conn.execute(sql,params):
                state=state if state in allowed_states else 'unclassified'
                result[state]=V.public_number(result.get(state,0)+count)
            return result
        queues={
            'reports':counts('SELECT state,count(*) FROM naver_auto_report_schedule_job WHERE possibility_id=? AND account_key=? GROUP BY state',(pid,key)),
            'experiments':counts('SELECT state,count(*) FROM naver_auto_experiment WHERE possibility_id=? AND account_key=? GROUP BY state',(pid,key)),
            'experiment_collection':counts('SELECT j.status,count(*) FROM naver_auto_experiment_job j JOIN naver_auto_experiment x ON x.experiment_id=j.experiment_id WHERE x.possibility_id=? AND x.account_key=? GROUP BY j.status',(pid,key)),
            'execution':counts('SELECT state,count(*) FROM naver_auto_execution_resource WHERE possibility_id=? AND account_key=? GROUP BY state',(pid,key)),
            'execution_outcomes':counts('SELECT o.status,count(*) FROM naver_auto_execution_operation o JOIN naver_auto_execution_resource r ON r.resource_id=o.command_id WHERE r.possibility_id=? AND r.account_key=? GROUP BY o.status',(pid,key)),
            'learning_capture':self.learning_source_pending(pid,key),
        }
        prefix=f'{pid}:{hashlib.sha256(key.encode()).hexdigest()}:'
        def storage(prefix):
            row=self._conn.execute('SELECT count(*),coalesce(sum(length(CAST(value AS BLOB))),0) FROM naver_auto_meta WHERE key>=? AND key<?',(prefix,prefix+'\uffff')).fetchone()
            return row[0],row[1]
        assets,head_bytes=storage('learning-head:'+prefix);versions,version_bytes=storage('learning-version:'+prefix)
        source=self._conn.execute('SELECT count(*),coalesce(sum(length(CAST(payload_json AS BLOB))),0) FROM naver_auto_learning_source WHERE possibility_id=? AND account_key=?',(pid,key)).fetchone()
        annotations=self._conn.execute('SELECT count(*),coalesce(sum(length(CAST(document_json AS BLOB))),0) FROM naver_auto_learning_annotation WHERE possibility_id=? AND account_key=?',(pid,key)).fetchone()
        learning={'stored_assets':assets,'stored_versions':versions,'source_versions':source[0],'annotation_versions':annotations[0],
            'stored_json_bytes':head_bytes+version_bytes+source[1]+annotations[1],
            'display_limit':100,'search_limit':500,'cross_candidate_limit':1000,'selection_limit':5,
            'display_truncated':assets>100,'search_truncated':assets>500,'storage_limit':None}
        collection={}
        collection_states=_S().ACCOUNT_STATUSES | {'reading','blocked','retry','source_wait','limited','reauth_required','superseded','failed','stale','unavailable'}
        for name,table in (('performance','naver_auto_performance_job'),('inspection','naver_auto_inspection_job'),('funnel','naver_auto_funnel_job')):
            stored=None
            binding=None
            if name=='inspection':
                with self.read_snapshot():
                    from .inspection_reads import MAX_BYTES
                    row=self._conn.execute('''SELECT status,checked_at,error_code,kind,cycle_day,generation,next_try_at,
                        attempts,customer_id,period_start,period_end,progress_hash,
                        CASE WHEN typeof(progress_json)='text' AND length(CAST(progress_json AS BLOB))<=?
                            THEN progress_json ELSE NULL END AS progress_json,
                        progress_json IS NULL AS progress_missing,
                    CASE WHEN typeof(job_key)='text' AND length(CAST(job_key AS BLOB))<=500 THEN job_key ELSE NULL END AS job_key
                        FROM naver_auto_inspection_job WHERE possibility_id=? AND customer_id=?
                        ORDER BY checked_at DESC,rowid DESC LIMIT 1''',(MAX_BYTES,pid,cid)).fetchone()
                    if row is not None:
                        stored=_inspection_stored_job(dict(zip(('status','checked_at','error_code','kind','cycle_day',
                            'generation','next_try_at','attempts','customer_id','period_start','period_end',
                            'progress_hash','progress_json','progress_missing'),row[:14])),now)
                        binding=self.inspection_binding_diagnostic(cid,now,possibility_id=pid,latest_job_key=row[14])
            else:
                row=self._conn.execute('SELECT status,checked_at,error_code FROM '+table+' WHERE possibility_id=? AND customer_id=? ORDER BY checked_at DESC LIMIT 1',(pid,cid)).fetchone()
            diagnostics={'KEY_REJECTED','RATE','SERVER','BAD_REQUEST','NOT_FOUND','NETWORK','BAD_RESPONSE','MISMATCH','OTHER','CHECKPOINT_PENDING','CHECKPOINT_INVALID','SETTINGS_CHANGED','SOURCE_AGGREGATING','CAMPAIGNS_CHANGED','RECHECK_COVERED','REQUEST_BUDGET','REQUEST_DEADLINE','REQUEST_CALL_CAP','STATS_INCOMPLETE','STATS_SHAPE','STATS_SHAPE_UNKNOWN','STATS_NUMERIC_INVALID','STATS_ROW_ID_INVALID','STATS_DATE_INVALID','STATS_PERIOD_OPEN','STATS_METRIC_MISSING','STATS_METRIC_INVALID','STATS_DATE_INCOMPLETE','STATS_CYCLE_INVALID','STATS_CYCLE_FUTURE','STATS_CAMPAIGNS_INVALID','UNEXPECTED','RETRY_EXHAUSTED'}
            collection[name]=None if row is None else {'status':row[0] if row[0] in collection_states else 'unclassified','checked_at':_inspection_at(row[1],now) if name=='inspection' else row[1],
                'diagnostic':row[2] if row[2] in diagnostics else 'UNCLASSIFIED' if row[2] is not None else None}
            if stored is not None:
                collection[name]['stored_job']=stored
            if binding is not None and collection[name] is not None:
                collection[name]['current_binding']=binding
        days=self._conn.execute('SELECT count(*),coalesce(sum(basic_complete),0),coalesce(sum(conversion_complete),0),max(checked_at) FROM naver_auto_daily_performance WHERE possibility_id=? AND customer_id=?',(pid,cid)).fetchone()
        collection['saved_daily_rows']={'total':days[0],'basic_complete':days[1],'general_conversion_complete':days[2],'last_checked_at':days[3]}
        return {'version':1,'selection':{'possibility_id':pid,'account_key':key},'provider':provider,'queues':queues,'learning':learning,'collection':collection}
