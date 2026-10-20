"""Independent platform-purchase evidence; no order/customer data or advertising writes."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import re

from . import management as P

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS naver_auto_funnel_job (
        job_key TEXT PRIMARY KEY,customer_id INTEGER NOT NULL,possibility_id INTEGER NOT NULL,
        kind TEXT NOT NULL,cycle_day TEXT NOT NULL,period_start TEXT NOT NULL,period_end TEXT NOT NULL,
        snapshot_at TEXT NOT NULL,catalog_at TEXT NOT NULL,stage_revision TEXT NOT NULL,
        matching_fingerprint TEXT NOT NULL,generation TEXT NOT NULL,primary_checked_at TEXT NOT NULL,
        requested_at TEXT,actor INTEGER,status TEXT NOT NULL,checked_at TEXT NOT NULL,
        next_try_at TEXT NOT NULL,attempts INTEGER NOT NULL,error_code TEXT,progress_json TEXT,progress_hash TEXT)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_funnel_due
        ON naver_auto_funnel_job(customer_id,possibility_id,period_start,period_end,generation,checked_at)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_funnel_daily (
        customer_id INTEGER NOT NULL,day TEXT NOT NULL,possibility_id INTEGER NOT NULL,
        stage_revision TEXT NOT NULL,matching_fingerprint TEXT NOT NULL,campaign_fingerprint TEXT NOT NULL,
        source_generation TEXT NOT NULL,source_revision INTEGER NOT NULL,job_key TEXT NOT NULL,
        basic_complete INTEGER NOT NULL,count_complete INTEGER NOT NULL,value_complete INTEGER NOT NULL,
        imp INTEGER,clk INTEGER,spend REAL,purchase_count INTEGER,purchase_value REAL,
        checked_at TEXT NOT NULL,source_at TEXT NOT NULL,PRIMARY KEY(customer_id,day))""",
    """CREATE INDEX IF NOT EXISTS naver_auto_funnel_scope
        ON naver_auto_funnel_daily(possibility_id,day,customer_id)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_funnel_history (
        history_id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL,day TEXT NOT NULL,
        possibility_id INTEGER NOT NULL,recorded_at TEXT NOT NULL,payload_json TEXT NOT NULL)""",
)
JOB_FIELDS = ("job_key", "customer_id", "possibility_id", "kind", "cycle_day", "period_start", "period_end",
    "snapshot_at", "catalog_at", "stage_revision", "matching_fingerprint", "generation", "primary_checked_at")
_MAX_BYTES = 4 * 1024 * 1024
_SAFE_CODES = frozenset({"KEY_REJECTED", "RATE", "SERVER", "BAD_REQUEST", "NOT_FOUND", "NETWORK", "BAD_RESPONSE",
    "MISMATCH", "OTHER", "CHECKPOINT_PENDING", "CHECKPOINT_INVALID", "SETTINGS_CHANGED", "CAMPAIGNS_CHANGED",
    "REQUEST_BUDGET", "REQUEST_DEADLINE", "REQUEST_CALL_CAP", "SOURCE_AGGREGATING", "STATS_INCOMPLETE",
    "STATS_SHAPE", "STATS_SHAPE_UNKNOWN", "STATS_NUMERIC_INVALID", "STATS_ROW_ID_INVALID", "STATS_DATE_INVALID",
    "STATS_PERIOD_OPEN", "STATS_METRIC_MISSING", "STATS_METRIC_INVALID", "STATS_DATE_INCOMPLETE",
    "STATS_CYCLE_INVALID", "STATS_CYCLE_FUTURE", "STATS_CAMPAIGNS_INVALID", "UNEXPECTED", "RETRY_EXHAUSTED"})


def _storage():
    from . import store
    return store


def _digest(value):
    return hashlib.sha256(_storage()._json(value).encode()).hexdigest()


def _job(row):
    result = {key: row[key] for key in JOB_FIELDS}
    result["snapshot_at"] = datetime.fromisoformat(result["snapshot_at"])
    if row["kind"] in ("manual", "manual_period"):
        result.update(requested_at=row["requested_at"], actor=row["actor"])
    return result


def _same(row, job):
    S = _storage()
    return row is not None and all(row[key] == (S._kst_text(job[key], "원천 시각") if key == "snapshot_at" else job[key])
                                   for key in JOB_FIELDS)


def _candidates(cursor):
    """Advance through bounded pages; waiting/invalid accounts cannot pin the first page forever."""
    columns = tuple(item[0] for item in cursor.description)
    while True:
        page = cursor.fetchmany(128)
        if not page:
            return
        for row in page:
            yield dict(zip(columns,row))


class FunnelStorage:
    def funnel_work(self, now, limit=24):
        S = _storage()
        if type(limit) is not int or not 1 <= limit <= 24:
            raise S.StoreRefused("구매 성과 후보 한도를 확인해 주세요")
        at = S._kst_text(now, "현재")
        if now.astimezone(S.KST).time().replace(tzinfo=None) < P.COLLECTION_START:
            return []
        self.synchronize_management(now)
        snapshot, catalog = self.inventory_snapshot(now), self.account_catalog()
        if snapshot is None or catalog is None:
            return []
        primary = _candidates(self._conn.execute("""SELECT * FROM (SELECT p.*,m.requested_at,m.actor,COALESCE(f.checked_at,'') AS funnel_checked_at,
            ROW_NUMBER() OVER(PARTITION BY p.customer_id ORDER BY p.generation DESC,COALESCE(f.checked_at,''),p.checked_at DESC,p.job_key) AS customer_rank
            FROM naver_auto_performance_job p LEFT JOIN naver_auto_funnel_job f
            ON f.job_key='funnel:'||p.job_key
            LEFT JOIN naver_auto_manual_read m ON m.customer_id=p.customer_id AND m.requested_at=p.generation
            WHERE p.status='ok' AND p.possibility_id IS NOT NULL AND p.cycle_day>=?
            AND (f.job_key IS NULL OR f.status!='ok' OR f.primary_checked_at!=p.checked_at
                 OR f.stage_revision!=p.stage_revision OR f.possibility_id!=p.possibility_id
                 OR f.matching_fingerprint!=p.matching_fingerprint)
            AND NOT EXISTS(SELECT 1 FROM naver_auto_funnel_job covered WHERE covered.customer_id=p.customer_id
                AND covered.possibility_id=p.possibility_id AND covered.stage_revision=p.stage_revision
                AND covered.matching_fingerprint=p.matching_fingerprint AND covered.status='ok'
                AND covered.generation>=p.generation AND covered.primary_checked_at>=p.checked_at
                AND covered.period_start<=p.period_start AND covered.period_end>=p.period_end)
            ) WHERE customer_rank=1 ORDER BY funnel_checked_at,checked_at DESC,job_key""", ((now.date()-timedelta(days=8)).isoformat(),)))
        # This source never leaves the single Writer callback. Public execution
        # and save gates still read fresh authority and exact primary rows.
        selection_source = None
        def valid(job):
            nonlocal selection_source
            methods = (self.funnel_account_valid, self._funnel_account_valid,
                       self.performance_account_valid, self._performance_account_valid,
                       self._performance_selection_source, self.inventory_account_valid)
            expected = (*_FUNNEL_SELECTION_DEFAULTS, *S._PERFORMANCE_SELECTION_DEFAULTS)
            if type(self) is not S.Store or any(getattr(method, "__func__", None) is not original
                   for method, original in zip(methods, expected)):
                return self.funnel_account_valid(job, now)
            if selection_source is None:
                from . import management_store as MS
                try:
                    policies = MS.snapshot(self, now)
                    requests = {row["customer_id"]: row for row in S._rows(
                        self._conn.execute("SELECT * FROM naver_auto_manual_read"))}
                    selection_source = self._performance_selection_source(now, policies, requests)
                except (S.StoreRefused, AttributeError, KeyError, TypeError, ValueError, OverflowError):
                    return self.funnel_account_valid(job, now)
            return self._funnel_account_valid(job, now, selection_source)
        selected, customers = [], set()
        for row in primary:
            cid = row["customer_id"]
            if cid in customers:
                continue
            job = _job({**row, "job_key": "funnel:"+row["job_key"], "primary_checked_at": row["checked_at"],
                        "snapshot_at": S._kst_text(snapshot, "계정 원천"), "catalog_at": catalog["generated_at"]})
            old_rows = S._rows(self._conn.execute("SELECT * FROM naver_auto_funnel_job WHERE job_key=?", (job["job_key"],)))
            old = old_rows[0] if old_rows and _same(old_rows[0], job) else None
            if old and not self._collection_retry_ready(old, at):
                continue
            if not self._collection_account_ready(cid, at) or not valid(job):
                continue
            selected.append(job); customers.add(cid)
            if len(selected) == limit:
                break
        return selected

    def funnel_account_valid(self, job, now):
        # Every HTTP/start/progress/commit boundary reads current sources.
        return self._funnel_account_valid(job, now)

    def _funnel_account_valid(self, job, now, source=None):
        S = _storage()
        try:
            expected = set(JOB_FIELDS) | ({"requested_at", "actor"} if job.get("kind") in ("manual", "manual_period") else set())
            if not isinstance(job, dict) or set(job) != expected or type(job["possibility_id"]) is not int \
                    or job["possibility_id"] <= 0 or not job["job_key"].startswith("funnel:"):
                return False
            plain = {key: value for key, value in job.items() if key not in ("possibility_id", "primary_checked_at")}
            plain["job_key"] = job["job_key"][7:]
            if not (self.performance_account_valid(plain, now) if source is None else
                    self._performance_account_valid(plain, now, source)):
                return False
            primary = S._rows(self._conn.execute("SELECT * FROM naver_auto_performance_job WHERE job_key=?", (plain["job_key"],)))
            if not primary:
                return False
            row = primary[0]
            if row["status"] != "ok" or row["checked_at"] != job["primary_checked_at"] \
                    or row["possibility_id"] != job["possibility_id"]:
                return False
            if any(row[key] != job[key] for key in ("customer_id", "stage_revision", "matching_fingerprint", "generation",
                                                    "period_start", "period_end", "kind", "cycle_day")):
                return False
            state = (self.management_states() if source is None else source.states).get(job["customer_id"])
            if not state or state["possibility_id"] != job["possibility_id"]:
                return False
            # A fully covering newer primary supersedes this job. Partially overlapping
            # periods may fill their other days; daily projection and commit preserve newer rows.
            newer = self._conn.execute("""SELECT 1 FROM naver_auto_performance_job WHERE customer_id=?
                AND possibility_id=? AND period_start<=? AND period_end>=?
                AND (generation>? OR (generation=? AND checked_at>?)) LIMIT 1""",
                (job["customer_id"], job["possibility_id"], job["period_start"], job["period_end"], job["generation"],job["generation"],job["primary_checked_at"])).fetchone()
            pending = self._conn.execute("""SELECT requested_at FROM naver_auto_manual_read WHERE customer_id=?
                AND possibility_id=? AND consumed_at IS NULL AND requested_at>? LIMIT 1""",
                (job["customer_id"],job["possibility_id"],job["generation"])).fetchone()
            return newer is None and pending is None
        except (S.StoreRefused, AttributeError, KeyError, TypeError, ValueError, OverflowError):
            return False

    def _funnel_dirty(self, connection, job, at):
        S = _storage()
        for raw in connection.execute("""SELECT DISTINCT period_key FROM naver_auto_report_snapshot
            WHERE possibility_id=?""", (job["possibility_id"],)):
            period = S._report_period(raw[0])
            if job["period_start"] <= str(period.end) and job["period_end"] >= str(period.start):
                S._report_mark_dirty(connection, job["possibility_id"], period.key, at)

    def begin_funnel_check(self, job, now):
        S = _storage()
        self._need_writer(); self._not_future(now, "구매 성과 시작")
        if not self.funnel_account_valid(job, now) or not self._collection_account_ready(job["customer_id"], S._kst_text(now,"현재")):
            raise S.StoreRefused("구매 성과 귀속·권한·재시도 상태가 변경되었습니다")
        at = S._kst_text(now, "구매 성과 시작")
        with self._tx() as connection:
            rows = S._rows(connection.execute("SELECT * FROM naver_auto_funnel_job WHERE job_key=?", (job["job_key"],)))
            old = rows[0] if rows else None
            same = _same(old, job)
            if same and not self._collection_retry_ready(old, at):
                raise S.StoreRefused("구매 성과를 다시 읽을 시각이 아닙니다")
            columns = (*JOB_FIELDS,"requested_at","actor","status","checked_at","next_try_at","attempts","error_code","progress_json","progress_hash")
            values = [S._kst_text(job[key],"원천 시각") if key == "snapshot_at" else job[key] for key in JOB_FIELDS]
            values += [job.get("requested_at"),job.get("actor"),"reading",at,S._kst_text(now+timedelta(minutes=2),"재시도 시각"),
                       old["attempts"] if same else 0,old["error_code"] if same else None,
                       old["progress_json"] if same else None,old["progress_hash"] if same else None]
            connection.execute("INSERT INTO naver_auto_funnel_job ("+",".join(columns)+") VALUES ("+",".join("?" for _ in columns)+
                ") ON CONFLICT(job_key) DO UPDATE SET "+",".join(key+"=excluded."+key for key in columns if key != "job_key"), values)
            self._funnel_dirty(connection,job,at)

    def funnel_progress(self, job):
        from . import funnel_reads as FR
        S = _storage()
        rows = S._rows(self._conn.execute("SELECT * FROM naver_auto_funnel_job WHERE job_key=?", (job["job_key"],)))
        row = rows[0] if rows else None
        if row is None or row["progress_json"] is None:
            return None
        if not _same(row, job) or len(row["progress_json"].encode()) > _MAX_BYTES \
                or hashlib.sha256(row["progress_json"].encode()).hexdigest() != row["progress_hash"]:
            raise FR.CheckpointInvalid("구매 성과 재개 자료 지문이 다릅니다")
        try:
            value = json.loads(row["progress_json"])
            FR.validate_progress(value,job)
            return value
        except (ValueError,TypeError):
            raise FR.CheckpointInvalid("구매 성과 재개 자료 모양이 다릅니다") from None

    def record_funnel_progress(self, job, now, progress):
        from . import funnel_reads as FR
        S = _storage()
        self._need_writer();self._not_future(now,"구매 성과 기록")
        if not self.funnel_account_valid(job,now):
            raise S.StoreRefused("구매 성과 귀속 또는 세대가 변경되었습니다")
        FR.validate_progress(progress,job,now)
        if any(datetime.fromisoformat(value)>now for value in progress["cycles"]):
            raise S.StoreRefused("미래 구매 원천은 저장하지 않습니다")
        body=S._json(progress)
        if len(body.encode())>_MAX_BYTES:
            raise S.StoreRefused("구매 성과 저장 크기를 확인해 주세요")
        with self._tx() as connection:
            row=connection.execute("SELECT status FROM naver_auto_funnel_job WHERE job_key=?",(job["job_key"],)).fetchone()
            if row is None or row[0]!="reading":
                raise S.StoreRefused("시작하지 않은 구매 성과입니다")
            old=self.funnel_progress(job)
            if old is not None and progress["next_index"]<old["next_index"]:
                if progress["next_index"]!=0 or progress["cycles"] or progress["campaign_fingerprint"]==old["campaign_fingerprint"]:
                    raise S.StoreRefused("구매 성과 재개 위치가 되돌아갔습니다")
            connection.execute("UPDATE naver_auto_funnel_job SET progress_json=?,progress_hash=?,attempts=CASE WHEN ? THEN 0 ELSE attempts END WHERE job_key=?",
                (body,hashlib.sha256(body.encode()).hexdigest(),int(old is not None and progress["next_index"]>old["next_index"]),job["job_key"]))

    def record_funnel_check(self, job, now, values):
        from . import funnel_reads as FR
        S=_storage()
        self._need_writer();self._not_future(now,"구매 성과 확인")
        if not self.funnel_account_valid(job,now) or not isinstance(values,dict):
            raise S.StoreRefused("구매 성과 귀속 또는 세대가 변경되었습니다")
        status=values.get("status");code=values.get("error_code")
        if status not in ("ok","partial","retry","limited","reauth_required","source_wait","superseded") \
                or code is not None and code not in _SAFE_CODES:
            raise S.StoreRefused("구매 성과 결과 상태를 확인해 주세요")
        at=S._kst_text(now,"구매 성과 확인");given=[]
        if status=="ok":
            progress=self.funnel_progress(job)
            if progress is None or progress["next_index"]!=len(progress["campaigns"]):
                raise S.StoreRefused("완결된 구매 원천이 아닙니다")
            expected=FR.validate_progress(progress,job,now)
            rows=values.get("daily_rows")
            if not isinstance(rows,list) or len(rows)!=len(expected) or values.get("campaign_fingerprint")!=progress["campaign_fingerprint"]:
                raise S.StoreRefused("구매 성과 날짜 또는 캠페인 원천이 다릅니다")
            seen=set();end=date.fromisoformat(job["period_end"])
            cycles=[S._performance_time(value,end,now) for value in progress["cycles"]]
            for row in rows:
                if not isinstance(row,dict) or row.get("customer_id")!=job["customer_id"] or type(row.get("customer_id")) is not int \
                        or row.get("day") not in expected or row["day"] in seen:
                    raise S.StoreRefused("구매 성과 계정 또는 날짜가 다릅니다")
                seen.add(row["day"]);origin=expected[row["day"]]
                for src,dst in zip(FR.FIELDS,("imp","clk","spend","purchase_count","purchase_value")):
                    if row.get(dst)!=origin[src] or (row.get(dst) is not None and type(row.get(dst)) not in (int,float)):
                        raise S.StoreRefused("구매 성과 수치가 원천과 다릅니다")
                if any(row.get(key) is not origin[key] for key in ("basic_complete","count_complete","value_complete")):
                    raise S.StoreRefused("구매 성과 완결 증거가 다릅니다")
                checked=S._performance_time(row.get("checked_at"),end,now);source=S._performance_time(row.get("source_at"),end,now)
                if source!=(min(cycles) if cycles else checked) or checked<(max(cycles) if cycles else source):
                    raise S.StoreRefused("구매 성과 원천 시각이 다릅니다")
                given.append({**row,"checked_at":S._kst_text(checked,"확인 시각"),"source_at":S._kst_text(source,"원천 시각")})
        with self._tx() as connection:
            oldrows=S._rows(connection.execute("SELECT * FROM naver_auto_funnel_job WHERE job_key=?",(job["job_key"],)))
            old=oldrows[0] if oldrows else None
            if not _same(old,job) or old["status"]!="reading":
                raise S.StoreRefused("시작하지 않은 구매 성과입니다")
            attempts=old["attempts"]+int(status=="retry" and code not in ("REQUEST_DEADLINE","REQUEST_CALL_CAP"))
            if status=="retry" and attempts>=4:status="limited"
            delay=(2,5,15,30)[max(0,min(4,attempts)-1)] if status=="retry" else 60 if status=="limited" else 15 if status=="source_wait" else 0
            if code in ("REQUEST_DEADLINE","REQUEST_CALL_CAP") and status=="retry":delay=0
            connection.execute("UPDATE naver_auto_funnel_job SET status=?,checked_at=?,next_try_at=?,attempts=?,error_code=? WHERE job_key=?",
                (status,at,S._kst_text(now+timedelta(minutes=delay),"재시도 시각"),attempts,code,job["job_key"]))
            for row in given:
                if not self._performance_history_valid(job["customer_id"],job["possibility_id"],date.fromisoformat(row["day"]),date.fromisoformat(row["day"])):
                    continue
                prior=S._rows(connection.execute("SELECT * FROM naver_auto_funnel_daily WHERE customer_id=? AND day=?",(job["customer_id"],row["day"])))
                before=prior[0] if prior else None
                if before and (before["possibility_id"]!=job["possibility_id"] or before["source_generation"]>job["generation"] or before["source_at"]>row["source_at"]):
                    continue
                if before and before["source_generation"]==job["generation"]:
                    prior_binding=connection.execute("SELECT primary_checked_at FROM naver_auto_funnel_job WHERE job_key=?",(before["job_key"],)).fetchone()
                    if prior_binding and prior_binding[0]>job["primary_checked_at"]:
                        continue
                body={key:row[key] for key in ("customer_id","day","basic_complete","count_complete","value_complete","imp","clk","spend","purchase_count","purchase_value","checked_at","source_at")}
                body.update(possibility_id=job["possibility_id"],stage_revision=job["stage_revision"],matching_fingerprint=job["matching_fingerprint"],
                    campaign_fingerprint=values["campaign_fingerprint"],source_generation=job["generation"],job_key=job["job_key"])
                changed=before is None or any(before[key]!=value for key,value in body.items() if key not in ("checked_at","source_at","job_key","source_generation"))
                body["source_revision"]=(before["source_revision"]+int(changed)) if before else 1
                if before and changed:
                    connection.execute("INSERT INTO naver_auto_funnel_history(customer_id,day,possibility_id,recorded_at,payload_json) VALUES(?,?,?,?,?)",
                        (job["customer_id"],row["day"],job["possibility_id"],at,S._json(before)))
                columns=tuple(body)
                connection.execute("INSERT INTO naver_auto_funnel_daily ("+",".join(columns)+") VALUES ("+",".join("?" for _ in columns)+
                    ") ON CONFLICT(customer_id,day) DO UPDATE SET "+",".join(key+"=excluded."+key for key in columns if key not in ("customer_id","day")),tuple(body.values()))
            self._funnel_dirty(connection,job,at)
        return status

    def funnel_daily(self, possibility_id, customers, start, end, *, authority=None):
        """Bounded saved source plus latest-family state. No collection or mutation on GET."""
        S=_storage();ids=tuple(sorted(set(customers)))
        if not ids:return None
        rows=[];jobs=[];manual=[];primary=[];states={}
        for offset in range(0,len(ids),400):
            chunk=ids[offset:offset+400];marks=",".join("?" for _ in chunk);args=(possibility_id,*chunk,str(start),str(end))
            rows.extend(S._rows(self._conn.execute("SELECT * FROM naver_auto_funnel_daily WHERE possibility_id=? AND customer_id IN ("+marks+") AND day BETWEEN ? AND ?",args)))
            jobs.extend(S._rows(self._conn.execute("SELECT * FROM naver_auto_funnel_job WHERE possibility_id=? AND customer_id IN ("+marks+") AND period_end>=? AND period_start<=?",args)))
            manual.extend(S._rows(self._conn.execute("SELECT * FROM naver_auto_manual_read WHERE possibility_id=? AND customer_id IN ("+marks+") AND consumed_at IS NULL",(possibility_id,*chunk))))
            primary.extend(S._rows(self._conn.execute("SELECT job_key,customer_id,possibility_id,period_start,period_end,status,checked_at,generation FROM naver_auto_performance_job WHERE possibility_id=? AND customer_id IN ("+marks+") AND period_end>=? AND period_start<=?",args)))
            states.update({row["customer_id"]:row for row in S._rows(self._conn.execute(
                "SELECT customer_id,possibility_id,stage_revision,stage_key FROM naver_auto_management_state WHERE customer_id IN ("+marks+")",chunk))})
        if not rows and not jobs:return None
        by_day={(r["customer_id"],r["day"]):r for r in rows}
        output=[]
        for cid in ids:
            for i in range((end-start).days+1):
                day=str(start+timedelta(days=i));saved=by_day.get((cid,day));current=states.get(cid)
                relevant=[j for j in jobs if j["customer_id"]==cid and j["period_start"]<=day<=j["period_end"]]
                latest=max(relevant,key=lambda j:(j["generation"],j["checked_at"],j["job_key"]),default=None)
                status="ok" if saved else "unavailable"
                if latest and (saved is None or latest["generation"]>=saved["source_generation"]):
                    status="ok" if latest["status"]=="ok" else "partial" if latest["status"]=="partial" else "pending" if latest["status"] in ("reading","source_wait") else "failed"
                    if status=="ok" and saved and (latest["stage_revision"]!=saved["stage_revision"] or latest["matching_fingerprint"]!=saved["matching_fingerprint"]):status="unavailable"
                pjobs=[j for j in primary if j["customer_id"]==cid and j["period_start"]<=day<=j["period_end"]]
                pnew=max(pjobs,key=lambda j:(j["generation"],j["checked_at"],j["status"]!="ok"),default=None)
                if pnew and saved and pnew["generation"]>=saved["source_generation"] and pnew["status"]!="ok":
                    status="pending" if pnew["status"] in ("reading","partial","source_wait") else "failed"
                ownjob=next((j for j in jobs if saved and j["job_key"]==saved["job_key"]),None)
                pown=next((j for j in pjobs if ownjob and j["job_key"]==ownjob["job_key"][7:]),None)
                if saved and (ownjob is None or pown is None or ownjob["primary_checked_at"]!=pown["checked_at"]):
                    status="pending"
                if saved and pnew and (pnew["generation"]>saved["source_generation"] or
                        pnew["generation"]==saved["source_generation"] and ownjob and pnew["checked_at"]>ownjob["primary_checked_at"]):
                    status="pending"
                if not current or current["possibility_id"]!=possibility_id or saved and saved["stage_revision"]!=current["stage_revision"]:
                    status="unavailable"
                if any(j["customer_id"]==cid and (not j.get("period_start") or j["period_start"]<=day<=j["period_end"]) for j in manual):status="pending"
                if authority is not None and (cid not in authority["accounts"] or authority["pairs"].get(cid)!=possibility_id
                        or not current or authority["stages"].get(possibility_id)!=current["stage_key"]):
                    status="unavailable"
                row=dict(saved) if saved else {"customer_id":cid,"day":day,"basic_complete":False,"count_complete":False,"value_complete":False,
                    "imp":None,"clk":None,"spend":None,"purchase_count":None,"purchase_value":None,"checked_at":latest["checked_at"] if latest else None,
                    "source_at":None,"source_generation":latest["generation"] if latest else None,"source_revision":0,"campaign_fingerprint":None}
                row["status"]=status
                for key in ("imp","clk","purchase_count"):
                    value=row[key]
                    if type(value) is float and value.is_integer():row[key]=int(value)
                for key in ("basic_complete","count_complete","value_complete"):row[key]=row[key] is True or row[key]==1
                output.append(row)
        return output

    def attach_funnel_snapshot(self, possibility_id, report, now):
        from . import funnel_evidence as FE, reporting as R
        period=R.period(report["period"]["kind"],date.fromisoformat(report["period"]["start"]))
        rows=self.funnel_daily(possibility_id,report["_expected_customers"],period.start,period.end)
        if rows is None:return report
        targets=[report,*report.get("_account_reports",{}).values()]
        for target in targets:
            saved=FE.snapshot(period,target["_expected_customers"],rows,now)
            target["details"]["funnel"]=R.public_payload(saved)
            target["_funnel_manifest"]=[{key:row.get(key) for key in ("customer_id","day","source_revision","source_generation","checked_at","source_at","campaign_fingerprint","status")}
                for row in rows if row["customer_id"] in target["_expected_customers"]]
            target["_funnel_fingerprint"]=saved["_fingerprint"]
            target["revision_fingerprint"]=_digest([target["revision_fingerprint"],target["_funnel_fingerprint"]])
        return report

    def funnel_strategy_source(self, possibility_id, payload, now, *, authority=None):
        from . import funnel_evidence as FE, reporting as R
        S=_storage()
        period=R.period(payload["period"]["kind"],date.fromisoformat(payload["period"]["start"]))
        saved=payload.get("details",{}).get("funnel")
        if saved is not None:
            if authority is None:
                from . import views as W, automation_views as AV
                from app.naver_auto import scope as SC
                try:
                    ctx=W.load(self,now)
                    companies,pairs=AV.context(ctx,self,SC.scope_of(ctx.org,0))
                    authority={"accounts":ctx.accounts,"pairs":pairs,
                        "stages":{pid:"".join((company["stage"] or "").split()) for pid,company in companies.items()}}
                except (S.StoreRefused,ValueError,TypeError,AttributeError,KeyError):
                    authority={"accounts":{},"pairs":{},"stages":{}}
        rows=self.funnel_daily(possibility_id,payload.get("_expected_customers",()),period.start,period.end,authority=authority)
        fresh=FE.snapshot(period,payload.get("_expected_customers",()),rows,now) if rows is not None else None
        fingerprint = fresh["_fingerprint"] if fresh is not None else _digest(None)
        return {"context":FE.model_context(saved) if saved is not None else None,"fingerprint":fingerprint,
                "current":payload.get("_funnel_fingerprint",_digest(None))==fingerprint}

# Keep class/instance overrides on the original public validation path.
_FUNNEL_SELECTION_DEFAULTS = (FunnelStorage.funnel_account_valid,
                              FunnelStorage._funnel_account_valid)
