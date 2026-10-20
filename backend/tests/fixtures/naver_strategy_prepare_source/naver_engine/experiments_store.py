"""Scoped immutable experiment protocols and bounded observational reads. No advertising writes."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import re
import uuid

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS naver_auto_experiment (
        experiment_id TEXT PRIMARY KEY,possibility_id INTEGER NOT NULL,customer_id INTEGER NOT NULL,
        account_key TEXT NOT NULL,stage_revision TEXT NOT NULL,version INTEGER NOT NULL,
        protocol_version INTEGER NOT NULL,state TEXT NOT NULL,document_json TEXT NOT NULL,
        binding_json TEXT,author INTEGER NOT NULL,approved_by INTEGER,approved_at TEXT,
        requested_at TEXT,request_id TEXT,updated_at TEXT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_experiment_scope ON naver_auto_experiment(possibility_id,account_key,updated_at)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_experiment_history (
        experiment_id TEXT NOT NULL,version INTEGER NOT NULL,payload_json TEXT NOT NULL,
        PRIMARY KEY(experiment_id,version))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_experiment_receipt (
        request_id TEXT PRIMARY KEY,actor INTEGER NOT NULL,possibility_id INTEGER NOT NULL,
        account_key TEXT NOT NULL,body_hash TEXT NOT NULL,response_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_experiment_job (
        job_key TEXT PRIMARY KEY,experiment_id TEXT NOT NULL,customer_id INTEGER NOT NULL,
        job_json TEXT NOT NULL,status TEXT NOT NULL,checked_at TEXT NOT NULL,next_try_at TEXT NOT NULL,
        attempts INTEGER NOT NULL,error_code TEXT,progress_json TEXT,progress_hash TEXT)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_experiment_due ON naver_auto_experiment_job(status,next_try_at,checked_at)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_experiment_observation (
        experiment_id TEXT NOT NULL,protocol_version INTEGER NOT NULL,revision INTEGER NOT NULL,
        job_key TEXT NOT NULL,generation TEXT NOT NULL,status TEXT NOT NULL,checked_at TEXT NOT NULL,
        material_hash TEXT NOT NULL,payload_json TEXT,
        PRIMARY KEY(experiment_id,protocol_version,revision))""",
)
JOB_FIELDS = frozenset({"job_key","experiment_id","protocol_version","possibility_id","customer_id","stage_revision",
    "account_key","generation","period_start","period_end","plan_version","source_fingerprint","arms"})
JOB_V2_FIELDS = JOB_FIELDS | {"version","method","approved_at","measurement_lag_days","parents"}
EXPLORATORY_METHOD = "exploratory_paired_day_hac_v1"
_MAX_BYTES = 1024 * 1024


def _S():
    from . import store
    return store


def _digest(value):
    return hashlib.sha256(_S()._json(value).encode()).hexdigest()


def _decode(row):
    if row is None:
        return None
    out = dict(row)
    out["document"] = json.loads(out.pop("document_json"))
    raw = out.pop("binding_json")
    out["binding"] = json.loads(raw) if raw else None
    return out


def _rows(cursor):
    return _S()._rows(cursor)


def _same_binding(a,b):
    def material(value):
        out=deepcopy(value)
        if out:
            for row in out.get("baseline",{}).values():
                if row:
                    row.pop("source_at",None);row.pop("checked_at",None)
        return out
    return material(a)==material(b)


def _reason(code, message, action="최신 운영 기준과 설정을 확인한 뒤 다시 승인해 주세요."):
    return {"code":code,"message":message,"next_action":action}


def observation_material(snapshot,*,job=None,now=None):
    """Observation refresh times are metadata; dated facts and stability are facts."""
    facts=deepcopy(snapshot)
    if facts:
        facts.pop("checked_at",None)
        for arm in facts["arms"].values():
            if arm:arm.pop("source_at",None);arm.pop("checked_at",None)
        if facts.get("version")==2:
            from . import experiments as X
            # Ignore healthy polling times without ignoring a qualification
            # change. Different source cycles cannot be paired, and a source
            # that has not passed the declared lag is not a mature refresh.
            rows=[row for day in snapshot["daily"] for row in (day["control"],day["treatment"])]
            rows.extend(snapshot["arms"].values())
            end=date.fromisoformat(snapshot["period_end"])
            lag=(job or {}).get("measurement_lag_days",0)
            cycles=[X.moment(row["source_at"]) if row and row.get("source_at") is not None else None for row in rows]
            checked=[X.moment(row["checked_at"]) if row and row.get("checked_at") is not None else None for row in rows]
            available=bool(rows) and all(cycle is not None for cycle in cycles)
            facts["_source_qualification"]={
                "source_available":available,
                "same_cycle":available and len(set(cycles))==1,
                "after_horizon":available and all(cycle.date()>end for cycle in cycles),
                "lag_source_mature":available and all(cycle.date()>end+timedelta(days=lag) for cycle in cycles),
                "lag_clock_mature":now is None or X.moment(now).date()>end+timedelta(days=lag),
                "checked_current":available and all(at is not None and cycle<=at and (now is None or at<=X.moment(now)) for cycle,at in zip(cycles,checked)),
            }
            for day in facts["daily"]:
                for name in ("control","treatment"):
                    if day[name]:day[name].pop("source_at",None);day[name].pop("checked_at",None)
            facts["stability"].pop("first_checked_at",None)
            facts["stability"].pop("last_checked_at",None)
    return facts


def _observed_stability(job,progress):
    """Only validated observed dates are counted; never fill past or future dates."""
    start,end=date.fromisoformat(job["period_start"]),date.fromisoformat(job["period_end"])
    expected=[(start+timedelta(days=n)).isoformat() for n in range((end-start).days+1)]
    ledger=progress["settings_ledger"]
    observed=[day for day in expected if day in ledger]
    return {"qualifier":"observed_stability","expected_days":expected,"observed_days":observed,
        "missing_days":[day for day in expected if day not in ledger],"drift":progress["drift"],
        "coverage_complete":len(observed)==len(expected) and not progress["drift"],
        "first_checked_at":min((ledger[day]["first_checked_at"] for day in observed),default=None),
        "last_checked_at":max((ledger[day]["last_checked_at"] for day in observed),default=None),
        "limitations":["intraday_changes_unobserved","unobserved_fields_unknown"]}


class ExperimentsStorage:
    def _experiment_head(self, experiment_id, pid, key):
        return _decode(next(iter(_rows(self._conn.execute("SELECT * FROM naver_auto_experiment WHERE experiment_id=? AND possibility_id=? AND account_key=?",
            (experiment_id,pid,key)))),None))

    def experiment_recovery_receipt(self,pid,key,actor,request_id):
        """Read one scoped actor receipt; absence does not prove an uncommitted POST."""
        from app.naver_auto import scope as SC
        S=_S()
        if not isinstance(request_id,str) or not re.fullmatch(r"[0-9a-f]{32}",request_id):
            raise S.StoreRefused("실험 요청 식별자를 확인해 주세요")
        row=self._conn.execute("SELECT actor,possibility_id,account_key,length(response_json),substr(response_json,1,1025) FROM naver_auto_experiment_receipt WHERE request_id=?",(request_id,)).fetchone()
        if row is None:return None
        if tuple(row[:3])!=(actor,pid,key):raise SC.ClientNotVisible()
        try:
            if row[3]>1024:raise ValueError()
            receipt=json.loads(row[4])
            if (not isinstance(receipt,dict) or set(receipt)!={"experiment_id","version","protocol_version","request_id"}
                    or receipt["request_id"]!=request_id
                    or not isinstance(receipt["experiment_id"],str) or not re.fullmatch(r"[0-9a-f]{32}",receipt["experiment_id"])
                    or any(type(receipt[k])is not int or not 1<=receipt[k]<=2**53-1 for k in ("version","protocol_version"))):
                raise ValueError()
            head=self._conn.execute("SELECT version FROM naver_auto_experiment WHERE experiment_id=? AND possibility_id=? AND account_key=?",(receipt["experiment_id"],pid,key)).fetchone()
            if head is None or head[0]<receipt["version"]:raise ValueError()
            return receipt
        except (ValueError,TypeError,KeyError,RecursionError):
            raise S.StoreRefused("실험 저장 결과를 다시 확인해 주세요") from None

    def _experiment_context(self, pid, key, actor, now):
        from app.naver_auto import scope as SC
        from . import automation_views as AV, views as W, experiments as X, handles as H, approval_documents as D
        ctx=W.load(self,now);scope=SC.scope_of(ctx.org,actor)
        company,cid=AV.resolve(ctx,self,scope,pid,key)
        own=AV.ownership(ctx,company)
        SC.require_client(ctx.org,scope,{pid:own},pid,SC.ACT_APPROVE)
        stage=H.stage_key(company["stage"])
        if stage not in D.AUTO_STAGES:
            raise _S().StoreRefused("현재 계약 단계에서는 실험 승인·수집을 진행할 수 없습니다")
        plan=self.automation_plan(pid,key)
        observation=self.setup_observation(cid,now)
        catalog=X.candidate_catalog(observation,possibility_id=pid,customer_id=cid,account_key=key)
        return ctx,own,cid,plan,catalog,observation

    def record_experiment(self,pid,key,actor,now,*,experiment_id,expected_version,request_id,action,protocol=None):
        from . import experiments as X, approval_documents as D
        from app.naver_auto import scope as SC
        S=_S();self._need_writer();self._not_future(now,"실험 작성")
        S._pos_int(pid,"업체");D.version(expected_version)
        if not isinstance(key,str) or not re.fullmatch(r"[0-9a-f]{64}",key) or not isinstance(request_id,str) or not re.fullmatch(r"[0-9a-f]{32}",request_id) \
                or action not in ("save","approve","collect_request") or (action!="save" and protocol is not None) \
                or (experiment_id is not None and (not isinstance(experiment_id,str) or not re.fullmatch(r"[0-9a-f]{32}",experiment_id))):
            raise S.StoreRefused("실험 요청 범위를 확인해 주세요")
        body={"experiment_id":experiment_id,"expected_version":expected_version,"action":action,"protocol":protocol}
        try:body_hash=_digest(body)
        except (ValueError,TypeError,OverflowError):raise S.StoreRefused("실험 수치와 자료 형식을 확인해 주세요") from None
        at=S._kst_text(now,"실험 작성")
        with self._tx() as c:
            ctx,own,cid,plan,catalog,observation=self._experiment_context(pid,key,actor,now)
            receipt=c.execute("SELECT actor,possibility_id,account_key,body_hash,response_json FROM naver_auto_experiment_receipt WHERE request_id=?",(request_id,)).fetchone()
            if receipt:
                if tuple(receipt[:4])!=(actor,pid,key,body_hash):
                    raise S.StoreRefused("다른 실험 요청에 사용된 식별자입니다")
                return json.loads(receipt[4])
            current=self._experiment_head(experiment_id,pid,key) if experiment_id else None
            if current is None and (experiment_id is not None or expected_version!=0 or action!="save"):
                raise S.StoreRefused("현재 실험을 다시 불러와 주세요")
            if current and current["updated_at"]>at:
                raise S.StoreRefused("실험 작성 시각이 최신 판보다 이전입니다")
            if current and current["version"]!=expected_version or expected_version==D.MAX_VERSION:
                raise S.StoreRefused("실험이 변경되었습니다. 다시 불러와 주세요")
            if plan["state"]!="approved" or plan["plan"].get("schema_version")!=2:
                raise S.StoreRefused("현재 승인된 업체별 운영 기준이 필요합니다")
            try:
                doc=X.normalize_protocol(protocol) if action=="save" else current["document"]
            except (ValueError,TypeError):
                raise S.StoreRefused("실험 계획의 항목과 수치를 확인해 주세요") from None
            prior_approval=c.execute("SELECT payload_json FROM naver_auto_experiment_history WHERE experiment_id=? AND json_extract(payload_json,'$.approved_at') IS NOT NULL ORDER BY version LIMIT 1",(experiment_id,)).fetchall() if current else []
            started=any((h:=json.loads(row[0])).get("approved_at") and h["document"].get("period_start") \
                and now.astimezone(S.KST).date()>=date.fromisoformat(h["document"]["period_start"]) for row in prior_approval)
            if action=="save" and started:
                raise S.StoreRefused("시작한 실험 계획은 변경할 수 없습니다. 새 실험을 만들어 주세요")
            try:
                if action=="collect_request":
                    X.current_binding(current["binding"],plan,catalog,now)
                    binding=deepcopy(current["binding"])
                else:
                    binding=X.bind_protocol(doc,plan,catalog,now,approve=action=="approve")
            except (ValueError,TypeError) as exc:
                raise S.StoreRefused(str(exc)) from None
            if action in ("approve","collect_request") and catalog.get("status")!="ready":
                raise S.StoreRefused("현재 완결된 설정 관측을 먼저 확인해 주세요")
            if action=="approve":
                if current["state"]!="draft":raise S.StoreRefused("저장한 실험 초안을 먼저 확인해 주세요")
                if plan["approval_requires_lead"] and not SC.can_approve(ctx.org,own,SC.LEVEL_LEAD,current["author"],actor):
                    raise S.StoreRefused("운영 상한을 높이는 계획은 팀장 승인이 필요합니다")
            if action=="collect_request":
                if current["state"]!="approved" or not _same_binding(current["binding"],binding):
                    raise S.StoreRefused("승인 이후 계획 또는 설정이 변경되었습니다. 다시 저장·승인해 주세요")
                if now.astimezone(S.KST).date()<=date.fromisoformat(doc["period_end"])+timedelta(days=doc["measurement_lag_days"]):
                    raise S.StoreRefused("관측 기간과 전환 지연이 끝난 뒤 수집을 요청해 주세요")
                active=c.execute("SELECT status,job_json FROM naver_auto_experiment_job WHERE experiment_id=? ORDER BY checked_at DESC,rowid DESC LIMIT 1",(experiment_id,)).fetchone()
                completed_partial=False
                if active and active[0]=="partial" and doc.get("method")==EXPLORATORY_METHOD:
                    from . import experiments_reads as ER
                    try:
                        previous_job=json.loads(active[1])
                        completed_partial=ER.validate_progress(self.experiments_progress(previous_job),previous_job,now=now) is not None
                    except (ValueError,TypeError,KeyError):pass
                if active and active[0] in ("queued","reading","partial","retry","source_wait") and not completed_partial:
                    raise S.StoreRefused("현재 실험 수집 요청을 먼저 완료해 주세요")
            exploratory=doc.get("method")==EXPLORATORY_METHOD
            eid=experiment_id or uuid.uuid4().hex
            pv=(current["protocol_version"]+int(current["document"]!=doc)) if current else 1
            head={"experiment_id":eid,"possibility_id":pid,"customer_id":cid,"account_key":key,
                "stage_revision":(observation or {}).get("stage_revision") or "unavailable","version":expected_version+1,
                "protocol_version":pv,"state":"draft" if action=="save" else "approved","document":doc,"binding":binding,
                "author":actor if action=="save" else current["author"],
                "approved_by":actor if action=="approve" else current.get("approved_by") if action=="collect_request" else None,
                "approved_at":at if action=="approve" else current.get("approved_at") if action=="collect_request" else None,
                "requested_at":(at if action=="approve" else current.get("requested_at")) if exploratory and action!="save" else at if action=="collect_request" else None,
                "request_id":request_id,"updated_at":at}
            columns=tuple(k for k in head if k not in ("document","binding"))+("document_json","binding_json")
            values=[head[k] for k in columns[:-2]]+[S._json(doc),S._json(binding)]
            c.execute("INSERT INTO naver_auto_experiment ("+",".join(columns)+") VALUES("+",".join("?" for _ in columns)+") ON CONFLICT(experiment_id) DO UPDATE SET "+",".join(k+"=excluded."+k for k in columns if k!="experiment_id"),values)
            c.execute("INSERT INTO naver_auto_experiment_history VALUES(?,?,?)",(eid,head["version"],S._json(head)))
            if exploratory and action=="collect_request":
                # Revisit the original approved observation job, retaining every
                # actually observed day. A new job cannot recreate a missed day.
                prior=c.execute("SELECT job_key,job_json FROM naver_auto_experiment_job WHERE experiment_id=? ORDER BY rowid DESC LIMIT 1",(eid,)).fetchone()
                if not prior:
                    raise S.StoreRefused("승인한 일별 관측 예약을 다시 확인해 주세요")
                previous=json.loads(prior[1])
                if set(previous)!=JOB_V2_FIELDS or previous["approved_at"]!=head["approved_at"] or previous["protocol_version"]!=pv:
                    raise S.StoreRefused("현재 승인판의 일별 관측 예약이 아닙니다")
                c.execute("UPDATE naver_auto_experiment_job SET status='queued',checked_at=?,next_try_at=?,attempts=0,error_code=NULL WHERE job_key=?",(at,at,prior[0]))
            elif action=="collect_request" or exploratory and action=="approve":
                job={"job_key":"experiment:"+eid+":"+request_id,"experiment_id":eid,"protocol_version":pv,
                    "possibility_id":pid,"customer_id":cid,"stage_revision":head["stage_revision"],"account_key":key,
                    "generation":at,"period_start":doc["period_start"],"period_end":doc["period_end"],
                    "plan_version":binding["plan_version"],"source_fingerprint":binding["source_fingerprint"],"arms":binding["arms"]}
                if exploratory:
                    job.update(version=2,method=EXPLORATORY_METHOD,approved_at=at,
                        measurement_lag_days=doc["measurement_lag_days"],parents=deepcopy(binding["parents"]))
                c.execute("INSERT INTO naver_auto_experiment_job(job_key,experiment_id,customer_id,job_json,status,checked_at,next_try_at,attempts) VALUES(?,?,?,?,?,?,?,0)",
                    (job["job_key"],eid,cid,S._json(job),"queued",at,at))
            response={"experiment_id":eid,"version":head["version"],"protocol_version":pv,"request_id":request_id}
            c.execute("INSERT INTO naver_auto_experiment_receipt VALUES(?,?,?,?,?,?)",(request_id,actor,pid,key,body_hash,S._json(response)))
            return response

    def experiments_projection(self,pid,key,cid,now,plan,catalog,*,experiment_id=None,can_edit=False,can_approve=False):
        from . import experiments as X
        S=_S()
        heads=_rows(self._conn.execute("SELECT experiment_id,version,protocol_version,state FROM naver_auto_experiment WHERE possibility_id=? AND account_key=? AND customer_id=? ORDER BY updated_at DESC,experiment_id LIMIT 100",(pid,key,cid)))
        eid=experiment_id or (heads[0]["experiment_id"] if heads else None)
        head=self._experiment_head(eid,pid,key) if eid else None
        if experiment_id and head is None:raise S.StoreRefused("현재 실험을 다시 불러와 주세요")
        selected=None
        if head:
            jobs=_rows(self._conn.execute("SELECT job_key,status,checked_at,error_code,job_json,length(progress_json) AS progress_size,substr(progress_json,1,1048577) AS progress_json,progress_hash FROM naver_auto_experiment_job WHERE experiment_id=? ORDER BY checked_at DESC,rowid DESC LIMIT 1",(eid,)))
            rows=_rows(self._conn.execute("SELECT revision,status,checked_at,payload_json FROM naver_auto_experiment_observation WHERE experiment_id=? AND protocol_version=? ORDER BY revision DESC LIMIT 1",(eid,head["protocol_version"])))
            row=rows[0] if rows else None;latest=jobs[0] if jobs else None
            snapshot=json.loads(row["payload_json"]) if row and row["payload_json"] and latest and latest["status"] in ("ok","partial") and row["status"]==latest["status"] else None
            binding=head["binding"];reasons=[];result=None;planning=None;current=False;observed_stability=None
            if binding:
                try:
                    current=X.current_binding(binding,plan,catalog,now) is True
                except (ValueError,TypeError,KeyError):
                    current=False
                if not current or head["state"]!="approved":snapshot=None
                if head["document"].get("method")==EXPLORATORY_METHOD and latest:
                    from . import experiments_reads as ER
                    try:
                        if not latest["progress_json"]:
                            snapshot=None
                        else:
                            if latest["progress_size"]>_MAX_BYTES or len(latest["progress_json"].encode())>_MAX_BYTES or hashlib.sha256(latest["progress_json"].encode()).hexdigest()!=latest["progress_hash"]:
                                raise ValueError()
                            job=json.loads(latest["job_json"]);progress=json.loads(latest["progress_json"])
                            latest_snapshot=ER.validate_progress(progress,job,now=now)
                            if current and head["state"]=="approved":observed_stability=_observed_stability(job,progress)
                            # A final partial source and a budget checkpoint share
                            # a status name. Only a completed current round can
                            # qualify an older immutable partial observation.
                            if latest_snapshot is None or observation_material(latest_snapshot,job=job,now=now)!=observation_material(snapshot,job=job,now=now):snapshot=None
                    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
                        snapshot=None
                        reasons.append(_reason("SOURCE_INVALID","일별 설정 관측 기록을 다시 확인해야 합니다."))
                try:
                    planning=X.planning(binding,now)
                    result=X.assess(binding,snapshot,now,approved_at=head["approved_at"],current_plan=plan,
                        current_source_fingerprint=binding["source_fingerprint"] if current else "unavailable")
                except (ValueError,TypeError,KeyError):
                    reasons.append(_reason("SOURCE_INVALID","승인 자료를 현재 설정과 다시 대조해야 합니다."))
            if head["state"]!="approved":reasons.append(_reason("APPROVAL_REQUIRED","실험 초안을 아직 승인하지 않았습니다."))
            if latest and latest["status"]!="ok":reasons.append(_reason("COLLECTION_"+latest["status"].upper(),"최신 수집이 완료되지 않아 이전 결과를 현재 비교에 사용하지 않습니다.","최신 수집 상태와 재시도 시각을 확인해 주세요."))
            can_approve=can_approve and head["state"]=="draft"
            if can_approve:
                try:X.bind_protocol(head["document"],plan,catalog,now,approve=True)
                except (ValueError,TypeError,KeyError):can_approve=False
            can_collect=can_edit and current and head["state"]=="approved" and bool(head["document"].get("period_end"))
            if can_collect:
                can_collect=now.astimezone(S.KST).date()>date.fromisoformat(head["document"]["period_end"])+timedelta(days=head["document"]["measurement_lag_days"])
                if not can_collect:reasons.append(_reason("PERIOD_NOT_MATURE","관측 기간과 전환 지연이 아직 끝나지 않았습니다.","기간과 측정 대기가 끝난 뒤 수집을 요청해 주세요."))
            if latest and latest["status"]in("queued","reading","partial","retry","source_wait"):
                if not (head["document"].get("method")==EXPLORATORY_METHOD and latest["status"]=="partial" and snapshot is not None):can_collect=False
            if not current:reasons.append(_reason("SOURCE_CHANGED","현재 운영 기준 또는 설정이 승인한 판과 다릅니다."))
            if not current or head["state"]!="approved":snapshot=None
            selected={"id":eid,"version":head["version"],"protocol_version":head["protocol_version"],"state":head["state"],
                "protocol":deepcopy(head["document"]),"planning":planning,"result":result,"observations":snapshot,
                "hold_reasons":reasons,"approved_at":head["approved_at"],"requested_at":head["requested_at"],
                "request_id":head["request_id"],"author":head["author"],"approved_by":head["approved_by"],
                "observation_revision":row["revision"] if row else 0,"collection_status":latest["status"] if latest else "unavailable",
                "last_checked_at":latest["checked_at"] if latest else None,
                "criteria":{k:binding["criteria"].get(k) for k in ("conversion_definition","value_basis","plan_goal","metric_role")} if binding else None}
            if head["document"].get("method")==EXPLORATORY_METHOD:
                selected["observed_stability"]=observed_stability
        return {"selection":{"possibility_id":pid,"account_key":key},"plan_ref":{"version":plan["version"],"state":plan["state"],**{k:plan.get("plan",{}).get(k) for k in ("goal","conversion_definition","value_basis")}},
            "source":{"status":catalog.get("status"),"period_start":catalog.get("period_start"),"period_end":catalog.get("period_end"),
                "checked_at":None,"generation":None,"coverage":len(catalog.get("items",[]))},
            "candidates":deepcopy(catalog.get("items",[])),"experiments":[{"id":r.pop("experiment_id"),**r} for r in heads],"selected":selected,
            "can_edit":can_edit,"can_approve":can_approve and bool(head),"can_collect":can_collect if head else False,
            "execution_enabled":False,"limitations":["관측 비교이며 무작위 배정 증거가 없습니다.","승인은 광고 집행을 시작하지 않습니다."]}

    def experiments_work(self,now,limit=24):
        S=_S()
        if type(limit)is not int or not 1<=limit<=24:raise S.StoreRefused("실험 후보 한도를 확인해 주세요")
        at=S._kst_text(now,"현재");out=[];seen=set()
        cursor=self._conn.execute("SELECT * FROM naver_auto_experiment_job WHERE status IN ('queued','reading','retry','partial','source_wait','limited') AND next_try_at<=? ORDER BY checked_at,job_key",(at,))
        for rows in iter(lambda:cursor.fetchmany(64),[]):
            for raw in rows:
                row=dict(zip((d[0] for d in cursor.description),raw));cid=row["customer_id"]
                if cid in seen or not self._collection_account_ready(cid,at):continue
                if row["status"]!="queued" and not self._collection_retry_ready(row,at):continue
                job=json.loads(row["job_json"])
                if not self.experiments_account_valid(job,now):continue
                seen.add(cid);out.append(job)
                if len(out)==limit:return out
        return out

    def experiments_account_valid(self,job,now):
        from . import experiments as X
        S=_S()
        try:
            exploratory=isinstance(job,dict) and job.get("version")==2 and job.get("method")==EXPLORATORY_METHOD
            if not isinstance(job,dict) or set(job)!=(JOB_V2_FIELDS if exploratory else JOB_FIELDS):return False
            head=self._experiment_head(job["experiment_id"],job["possibility_id"],job["account_key"])
            if not head or head["state"]!="approved" or head["protocol_version"]!=job["protocol_version"] or head["requested_at"]!=job["generation"]:return False
            if exploratory:
                latest=self._conn.execute("SELECT job_key,job_json FROM naver_auto_experiment_job WHERE experiment_id=? ORDER BY rowid DESC LIMIT 1",(job["experiment_id"],)).fetchone()
                if (not latest or latest[0]!=job["job_key"] or json.loads(latest[1])!=job
                        or head["document"].get("method")!=EXPLORATORY_METHOD or head["binding"].get("version")!=2
                        or head["approved_at"]!=job["approved_at"] or job["approved_at"]!=job["generation"]
                        or head["document"]["measurement_lag_days"]!=job["measurement_lag_days"]
                        or head["binding"]["parents"]!=job["parents"]):return False
            elif head["request_id"]!=job["job_key"].split(":")[-1]:return False
            _,_,cid,plan,catalog,observation=self._experiment_context(job["possibility_id"],job["account_key"],head["approved_by"],now)
            if cid!=job["customer_id"] or (observation or {}).get("stage_revision")!=job["stage_revision"]:return False
            X.current_binding(head["binding"],plan,catalog,now)
            binding=head["binding"]
            return all(binding[k]==job[k] for k in ("plan_version","source_fingerprint","arms"))
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError,S.StoreRefused):return False

    def begin_experiments_check(self,job,now):
        S=_S();self._need_writer();self._not_future(now,"실험 수집 시작")
        if not self.experiments_account_valid(job,now) or not self._collection_account_ready(job["customer_id"],S._kst_text(now,"현재")):
            raise S.StoreRefused("현재 실험 승인·설정·권한이 변경되었습니다")
        with self._tx() as c:
            row=c.execute("SELECT status,next_try_at FROM naver_auto_experiment_job WHERE job_key=?",(job["job_key"],)).fetchone()
            if not row or row[1]>S._kst_text(now,"현재") or row[0]in("ok","superseded","reauth_required"):raise S.StoreRefused("현재 실험 수집을 시작할 수 없습니다")
            c.execute("UPDATE naver_auto_experiment_job SET status='reading',checked_at=?,next_try_at=? WHERE job_key=?",(S._kst_text(now,"현재"),S._kst_text(now+timedelta(minutes=2),"재시도"),job["job_key"]))

    def experiments_progress(self,job):
        from . import experiments_reads as ER
        row=self._conn.execute("SELECT progress_json,progress_hash,job_json FROM naver_auto_experiment_job WHERE job_key=?",(job["job_key"],)).fetchone()
        if not row or row[0]is None:return None
        if len(row[0].encode())>_MAX_BYTES or hashlib.sha256(row[0].encode()).hexdigest()!=row[1] or json.loads(row[2])!=job:
            raise ER.CheckpointInvalid("실험 재개 자료 지문이 다릅니다")
        try:
            value=json.loads(row[0]);ER.validate_progress(value,job);return value
        except (ValueError,TypeError):raise ER.CheckpointInvalid("실험 재개 자료를 확인해 주세요") from None

    def record_experiments_progress(self,job,now,progress):
        from . import experiments_reads as ER
        S=_S();self._need_writer();self._not_future(now,"실험 재개 저장")
        if not self.experiments_account_valid(job,now):raise S.StoreRefused("실험의 현재 승인이 변경되었습니다")
        ER.validate_progress(progress,job,now=now);body=S._json(progress)
        if len(body.encode())>_MAX_BYTES:raise S.StoreRefused("실험 재개 자료가 너무 큽니다")
        with self._tx() as c:
            row=c.execute("SELECT status FROM naver_auto_experiment_job WHERE job_key=?",(job["job_key"],)).fetchone()
            if not row or row[0]!="reading":raise S.StoreRefused("시작하지 않은 실험 수집입니다")
            c.execute("UPDATE naver_auto_experiment_job SET progress_json=?,progress_hash=? WHERE job_key=?",(body,hashlib.sha256(body.encode()).hexdigest(),job["job_key"]))

    def record_experiments_check(self,job,now,values):
        from . import experiments_reads as ER
        from .funnel_store import _SAFE_CODES
        S=_S();self._need_writer();self._not_future(now,"실험 수집 확인")
        if not self.experiments_account_valid(job,now) or not isinstance(values,dict):raise S.StoreRefused("실험 승인·원천이 변경되었습니다")
        status=values.get("status");code=values.get("error_code")
        if status not in ("ok","partial","retry","limited","reauth_required","source_wait","superseded") or code is not None and code not in _SAFE_CODES:
            raise S.StoreRefused("실험 수집 상태를 확인해 주세요")
        snapshot=None
        if status=="ok" or values.get("snapshot") is not None:
            progress=self.experiments_progress(job)
            snapshot=ER.validate_progress(progress,job,now=now)
            if snapshot is None or snapshot!=values.get("snapshot") or snapshot["status"]!=status:
                raise S.StoreRefused("실험 관측은 완료된 재개 원천과 같아야 합니다")
        next_check=None
        if values.get("next_check_at") is not None:
            from . import experiments as X
            try:
                next_check=X.moment(values["next_check_at"])
                if job.get("version")!=2 or job.get("method")!=EXPLORATORY_METHOD or status!="source_wait" or not now<next_check<=now+timedelta(days=1):
                    raise ValueError()
                # A wait is permitted only with a validated checkpoint. Missing
                # progress must not postpone an unauthenticated observation.
                ER.validate_progress(self.experiments_progress(job),job,now=now)
            except (ValueError,TypeError,KeyError,OverflowError):
                raise S.StoreRefused("다음 일별 관측 시각과 재개 자료를 확인해 주세요") from None
        at=S._kst_text(now,"실험 수집 확인")
        with self._tx() as c:
            row=c.execute("SELECT status,attempts FROM naver_auto_experiment_job WHERE job_key=?",(job["job_key"],)).fetchone()
            if not row or row[0]!="reading":raise S.StoreRefused("시작하지 않은 실험 관측입니다")
            attempts=row[1]+int(status=="retry" and code not in ("REQUEST_DEADLINE","REQUEST_CALL_CAP"))
            if status=="retry" and attempts>=4:status="limited"
            delay=(2,5,15,30)[max(0,min(4,attempts)-1)] if status=="retry" else 60 if status=="limited" else 15 if status=="source_wait" else 0
            if status=="partial" and snapshot is not None:
                # All configuration reads finished. Missing/lagged metrics need
                # source refresh time; a budget checkpoint still resumes immediately.
                delay=15
            if code in ("REQUEST_DEADLINE","REQUEST_CALL_CAP"):delay=0
            c.execute("UPDATE naver_auto_experiment_job SET status=?,error_code=?,attempts=?,checked_at=?,next_try_at=? WHERE job_key=?",(status,code,attempts,at,S._kst_text(next_check or now+timedelta(minutes=delay),"재시도"),job["job_key"]))
            if job.get("version")==2 and status in ("source_wait","partial") and snapshot is None:
                # The actual daily ledger is already durable in the job. A
                # waiting poll is neither a result revision nor a learning case.
                return status
            facts=observation_material(snapshot,job=job,now=now)
            material={"status":status,"source_fingerprint":job["source_fingerprint"],"payload":facts}
            old=c.execute("SELECT revision,material_hash FROM naver_auto_experiment_observation WHERE experiment_id=? AND protocol_version=? ORDER BY revision DESC LIMIT 1",(job["experiment_id"],job["protocol_version"])).fetchone()
            fingerprint=_digest(material)
            if old is None or fingerprint!=old[1]:
                c.execute("INSERT INTO naver_auto_experiment_observation VALUES(?,?,?,?,?,?,?,?,?)",(job["experiment_id"],job["protocol_version"],old[0]+1 if old else 1,job["job_key"],job["generation"],status,at,fingerprint,S._json(snapshot) if snapshot is not None else None))
                self._learning_capture_event(c,"experiment_observation",job["experiment_id"],now)
        return status
