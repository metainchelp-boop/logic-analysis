"""현재 대행 권한·전산 귀속·수집 세대로 묶인 설정 관측. 광고를 변경하지 않는다."""
from datetime import date, datetime, timedelta
import hashlib
import json

from . import management as P
from . import inspection_catalog as IC


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS naver_auto_inspection_job (
        job_key TEXT PRIMARY KEY,customer_id INTEGER NOT NULL,possibility_id INTEGER,
        kind TEXT NOT NULL,cycle_day TEXT NOT NULL,period_start TEXT NOT NULL,period_end TEXT NOT NULL,
        snapshot_at TEXT NOT NULL,catalog_at TEXT NOT NULL,stage_revision TEXT NOT NULL,
        matching_fingerprint TEXT NOT NULL,generation TEXT NOT NULL,requested_at TEXT,actor INTEGER,
        status TEXT NOT NULL,checked_at TEXT NOT NULL,next_try_at TEXT NOT NULL,attempts INTEGER NOT NULL,
        error_code TEXT,progress_json TEXT,progress_hash TEXT)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_inspection_customer
        ON naver_auto_inspection_job(customer_id,generation,checked_at)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_setting_observation (
        history_id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL,possibility_id INTEGER,
        stage_revision TEXT NOT NULL,entity TEXT NOT NULL,entity_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,generation TEXT NOT NULL,cycle_day TEXT NOT NULL,
        body_json TEXT NOT NULL,body_hash TEXT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_setting_scope
        ON naver_auto_setting_observation(customer_id,possibility_id,stage_revision,entity,entity_id,history_id)""",
)
_JOB_FIELDS = ("job_key", "customer_id", "kind", "cycle_day", "period_start", "period_end", "snapshot_at",
               "catalog_at", "stage_revision", "matching_fingerprint", "generation")
_MAX_BYTES = 8 * 1024 * 1024
_INSPECTION_BINDING_COLUMNS = ",".join(IC._BINDING_FIELDS)
_ERROR_CODES = frozenset({"KEY_REJECTED", "RATE", "SERVER", "BAD_REQUEST", "NOT_FOUND", "NETWORK", "BAD_RESPONSE",
    "MISMATCH", "OTHER", "CHECKPOINT_PENDING", "CHECKPOINT_INVALID", "SETTINGS_CHANGED", "REQUEST_BUDGET",
    "REQUEST_DEADLINE", "REQUEST_CALL_CAP", "STATS_INCOMPLETE", "STATS_SHAPE", "STATS_SHAPE_UNKNOWN",
    "STATS_NUMERIC_INVALID", "STATS_ROW_ID_INVALID", "STATS_DATE_INVALID", "STATS_PERIOD_OPEN", "STATS_METRIC_MISSING",
    "STATS_METRIC_INVALID", "STATS_DATE_INCOMPLETE", "STATS_CYCLE_INVALID", "STATS_CYCLE_FUTURE",
    "STATS_CAMPAIGNS_INVALID", "UNEXPECTED", "RETRY_EXHAUSTED"})


def _storage():
    from . import store
    return store


def _digest(body):
    return hashlib.sha256(body.encode()).hexdigest()


def _binding(row, job, possibility_id):
    return row and row["stage_revision"] == job["stage_revision"] and row["possibility_id"] == possibility_id \
        and row["generation"] == job["generation"] and row["catalog_at"] == job["catalog_at"] \
        and row["matching_fingerprint"] == job["matching_fingerprint"] \
        and row["snapshot_at"] == _storage()._kst_text(job["snapshot_at"], "계정 원천")


def _job(row):
    out = {key: row[key] for key in _JOB_FIELDS}
    out["snapshot_at"] = datetime.fromisoformat(out["snapshot_at"])
    if row["kind"] == "manual":
        out.update(requested_at=row["requested_at"], actor=row["actor"])
    return out


def _observed_times(progress):
    times = [row["checked_at"] for row in progress["entities"].values()]
    times += [row["checked_at"] for group in progress["targets"].values() for row in group.values()]
    times += [row["checked_at"] for row in progress["performance"].values()]
    for row in progress.get("campaign_budget_details", {}).values():
        times.append(row["checked_at"])
        if row["verified_at"] is not None:
            times.append(row["verified_at"])
    return times


def _history_body(raw, cid, pid, revision, now):
    """이력도 닫힌 필드만 다시 읽는다. 과거 관측은 현재 설정의 증거가 아니다."""
    from . import inspection_fields as F
    keys = {"possibility_id", "customer_id", "stage_revision", "entity", "id", "parent_id", "campaign_id",
            "observed_at", "generation", "cycle_day", "execution", "change_kind", "before", "after"}
    try:
        body = json.loads(raw)
        if (not isinstance(body, dict) or set(body) != keys or body["customer_id"] != cid
                or body["possibility_id"] != pid or body["stage_revision"] != revision
                or body["execution"] != "observed" or body["change_kind"] not in ("initial", "changed", "removed")):
            return None
        for name in ("observed_at", "generation"):
            at = datetime.fromisoformat(body[name])
            if at.utcoffset() is None or at > now:
                return None
        cycle = date.fromisoformat(body["cycle_day"])
        if datetime.fromisoformat(body["observed_at"]).date() < cycle:
            return None
        entity = body["entity"]
        if entity in F.IDS:
            if not F.valid_id(body["id"], entity) or not F.valid_id(body["campaign_id"], "campaign"):
                return None
            if entity == "campaign" and (body["parent_id"] is not None or body["campaign_id"] != body["id"]):
                return None
            for value in (body["before"], body["after"]):
                parent = value.get(F.PARENTS[entity]) if entity in F.PARENTS and isinstance(value, dict) else None
                if value is not None and (F.sanitize_record(entity, value, cid, parent) != value
                                          or value[F.IDS[entity]] != body["id"]):
                    return None
            if body["after"] is not None and entity in F.PARENTS and body["after"][F.PARENTS[entity]] != body["parent_id"]:
                return None
        elif entity in ("target:SD", "target:RL", "target:AG", "target:negative_keywords"):
            kind = entity[7:]
            if not F.valid_id(body["id"], "adgroup") or body["parent_id"] != body["id"] \
                    or not F.valid_id(body["campaign_id"], "campaign"):
                return None
            for value in (body["before"], body["after"]):
                if value is None:
                    continue
                if not isinstance(value, dict) or set(value) != {"state", "records"} or value["state"] not in ("observed", "unsupported"):
                    return None
                if value["state"] == "unsupported":
                    if value["records"] != []:
                        return None
                elif (F.sanitize_negative(value["records"], cid, body["id"]) if kind == "negative_keywords" else
                      F.sanitize_criteria(value["records"], cid, body["id"], kind)) != value["records"]:
                    return None
        else:
            return None
        before, after = body["before"], body["after"]
        if before == after or (body["change_kind"] == "initial" and (before is not None or after is None)) \
                or (body["change_kind"] == "removed" and (before is None or after is not None)) \
                or (body["change_kind"] == "changed" and (before is None or after is None)):
            return None
        return body
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _inspection_order_attempt(row, job, possibility_id, now):
    """Same-account/cycle ordering only; never authority or checkpoint evidence.

    Source refreshes still invalidate current observations and continuation. They
    must not erase the ordering history of an otherwise identical work item.
    """
    try:
        expected = dict(job, possibility_id=possibility_id,
                        requested_at=job.get("requested_at"), actor=job.get("actor"))
        if row is not None and all(IC._dump(row[key]) == IC._dump(expected[key])
                for key in IC._SCOPE_FIELDS if key not in {"snapshot_at", "catalog_at", "matching_fingerprint"}):
            checked = IC._time(row["checked_at"])
            if IC._time(job["generation"]) <= checked <= now and row["checked_at"] == IC._kst_text(checked):
                return row["checked_at"]
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return ""


def _observe_selection(observe, event, customer_id=None, *, customers=()):
    """Diagnostic sink only; failures never alter the selector's decisions."""
    try:
        if observe is not None:
            observe(event, job=None if customer_id is None else {"customer_id": customer_id},
                    customers=customers)
    except Exception:
        pass


class InspectionStorage:
    def _inspection_read_proof(self, c, key, limit):
        row = c.execute("SELECT CASE WHEN length(CAST(value AS BLOB))<=? THEN value END FROM naver_auto_meta WHERE key=?",
                        (limit, key)).fetchone()
        return IC.decode_proof(row[0], limit) if row is not None else None

    def _inspection_catalog_proof(self, now, c=None):
        """One read per selection; HTTP and writer boundaries read again."""
        from . import inventory as I
        S = _storage()
        c = self._conn if c is None else c
        try:
            body, state = I.catalog_status(self, now)
            if state != "accepted":
                return None
            proof = self._inspection_read_proof(c, IC.CATALOG_KEY, 2048)
            return IC.catalog_proof(proof, body, now)
        except (S.StoreError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
            return None

    def _inspection_context(self, c, row, now, catalog):
        try:
            if row is None or catalog is None:
                return None
            proof = self._inspection_read_proof(c, IC.checkpoint_key(row["job_key"]), 4096)
            return IC.context(proof, row, now, catalog, _ERROR_CODES)
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
            return None

    def _inspection_resumable(self, c, row, job, pid, now, catalog, continuity_cache=None):
        try:
            if row is None or catalog is None:
                return False
            proof = self._inspection_read_proof(c, IC.checkpoint_key(row["job_key"]), 4096)
            if IC.resumable(proof, row, job, pid, now, catalog, _ERROR_CODES, _MAX_BYTES):
                return True
            bridge = self._inspection_read_proof(c, IC.continuity_key(row["job_key"]), 4096)
            if bridge is None:
                return False
            if continuity_cache is None:
                scope = self._inspection_continuity_scopes(c, self.account_catalog(), now, {row["customer_id"]})
            else:
                if "scopes" not in continuity_cache:
                    continuity_cache["scopes"] = self._inspection_continuity_scopes(c, self.account_catalog(), now,
                        set(self.management_states()))
                scope = continuity_cache["scopes"]
            return IC.resumable_continuity(bridge, proof, row, job, pid, now, catalog,
                scope.get(row["customer_id"]), _ERROR_CODES, _MAX_BYTES)
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
            return False

    def _record_inspection_context(self, c, row, progress, now, catalog=None, *, initialize=False):
        catalog = self._inspection_catalog_proof(now, c) if catalog is None else catalog
        try:
            key, raw = IC.checkpoint_proof(row, progress, catalog, _ERROR_CODES)
            bridge, scope_hash = None, None
            if initialize:
                if progress is None:
                    organization = self.org_current()
                    if organization is not None and IC.org_continuity_epoch(
                            self._inspection_read_proof(c, IC.ORG_CONTINUITY_KEY, 4096), organization["body"]) is None:
                        self._record_inspection_org_continuity(c, organization["body"])
                scope_hash = self._inspection_continuity_scopes(c, self.account_catalog(), now,
                    {row["customer_id"]}).get(row["customer_id"])
                if progress is not None:
                    prior = self._inspection_read_proof(c, IC.checkpoint_key(row["job_key"]), 4096)
                    carried = self._inspection_read_proof(c, IC.continuity_key(row["job_key"]), 4096)
                    if not IC.continuity_matches(carried, prior, catalog, scope_hash):
                        scope_hash = None
            elif progress is not None and not progress["confirmed"]:
                prior = self._inspection_read_proof(c, IC.checkpoint_key(row["job_key"]), 4096)
                carried = self._inspection_read_proof(c, IC.continuity_key(row["job_key"]), 4096)
                scope_hash = carried.get("scope_hash") if isinstance(carried, dict) else None
                if (not IC.continuity_matches(carried, prior, catalog, scope_hash)
                        or any(IC._dump(prior["binding"][name]) != IC._dump(row[name]) for name in IC._SCOPE_FIELDS)):
                    scope_hash = None
            if scope_hash is not None and (progress is None or not progress["confirmed"]):
                bridge = IC.continuity_proof(json.loads(raw), catalog, scope_hash)
            self._set_meta(c, IC.continuity_key(row["job_key"]), IC._dump(bridge))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise _storage().StoreRefused("설정 관측 내용 증명의 형식을 확인하지 못했습니다") from None
        self._set_meta(c, key, raw)

    def _clear_inspection_context(self, c, job_key):
        # The runtime authorizer forbids DELETE; a null value revokes the proof.
        c.execute("UPDATE naver_auto_meta SET value='null' WHERE key=?", (IC.checkpoint_key(job_key),))

    def _inspection_continuity_scopes(self, c, catalog, now, customers):
        """Bounded hashes only; actual matching sees the full current catalog.

        Account snapshot, organization semantic epoch, global human decisions,
        target-related raw ID claims and policy events remain exact. Full catalog
        matching still sees every company and ID row before target scopes form.
        """
        from dataclasses import asdict
        from . import inventory as I, management_store as MS, sync as Y
        from app.naver_auto import org_snapshot as O
        S = _storage()
        try:
            snapshot = self.inventory_snapshot(now)
            organization, sync = self.org_current(), self.last_sync(S.SYNC_ORG)
            if (catalog is None or snapshot is None or organization is None or sync is None
                    or sync["outcome"] != S.SYNC_ACCEPTED
                    or not O.allows_raising(Y.org_freshness(self, now))):
                return {}
            accounts = {row["customer_id"]: row for row in self.accounts()}
            states = self.management_states()
            matches = MS.matching_result(self, accounts, self.current_decisions(), catalog,
                I.automatic_evidence(self))[0]
            pairs = {pair.customer_id: pair for pair in matches.pairs}
            companies = {row["possibility_id"]: row for row in catalog["items"]}
            org_epoch = IC.org_continuity_epoch(self._inspection_read_proof(c, IC.ORG_CONTINUITY_KEY, 4096),
                organization["body"])
            if org_epoch is None:
                return {}
            common = dict(snapshot=S._kst_text(snapshot, "계정 원천"), org_epoch=org_epoch,
                matching=self.decision_fingerprint())
            # Preserve raw rows (including duplicates) owned by the target company
            # or claiming its customer/ad-account ID. A confirmed Pair alone does
            # not expose every competing claim, so it is not the only scope proof.
            claims_by_pid, claims_by_customer = {}, {}
            ad_owners = {str(row["ad_account_no"]): cid for cid, row in accounts.items() if row["present"] == 1}
            for index, claim in enumerate(catalog["ids"]):
                claims_by_pid.setdefault(claim["possibility_id"], set()).add(index)
                if claim["vendor"] != I.M.VENDOR_NAVER:
                    continue
                claimed, _ = I.M.parse_customer_id(claim["customer_id_raw"])
                targets = {claimed} if claimed in accounts else set()
                explicit = claim["ad_account_no_raw"] not in (None, "")
                by_number = ad_owners.get(claim["ad_account_no_raw"] if explicit else str(claimed))
                if by_number is not None:
                    targets.add(by_number)
                for target in targets:
                    claims_by_customer.setdefault(target, set()).add(index)
            common_hash = IC._hash(common)
            result = {}
            for cid in customers:
                pair, state, account = pairs.get(cid), states.get(cid), accounts.get(cid)
                if not pair or not state or not account or account["present"] != 1 or pair.possibility_id != state["possibility_id"]:
                    continue
                company = companies.get(pair.possibility_id)
                if company is None or not company["stage_known"] or company["stage_hidden"]:
                    continue
                event = c.execute("SELECT MAX(event_id) FROM naver_auto_management_event WHERE customer_id=?", (cid,)).fetchone()[0]
                indices = claims_by_pid.get(pair.possibility_id, set()) | claims_by_customer.get(cid, set())
                claims = sorted((catalog["ids"][index] for index in indices), key=IC._dump)
                result[cid] = IC._hash(dict(common_hash=common_hash, account=account, company=company,
                    pair=asdict(pair), policy=state, policy_event=event, claims=IC._hash(claims)))
            return result
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError, S.StoreRefused):
            return {}

    def _advance_inspection_continuity(self, c, old, accepted, previous, current, now):
        """Same transaction as accepted catalog; never change job/progress/current proof."""
        S = _storage()
        prior = IC.catalog_proof(previous, old, now) if old is not None else None
        if prior is None:
            return  # Chain reset cannot grant an old checkpoint a new bridge.
        rows = S._rows(c.execute("SELECT job_key,customer_id FROM naver_auto_inspection_job WHERE status IN ('reading','partial','retry','limited') AND cycle_day>=?",
            ((now.astimezone(S.KST).date()-timedelta(days=8)).isoformat(),)))
        customers = {row["customer_id"] for row in rows}
        if not customers:
            return
        before = self._inspection_continuity_scopes(c, old, now, customers)
        after = self._inspection_continuity_scopes(c, accepted, now, customers)
        for row in rows:
            key = IC.continuity_key(row["job_key"])
            checkpoint = self._inspection_read_proof(c, IC.checkpoint_key(row["job_key"]), 4096)
            bridge = self._inspection_read_proof(c, key, 4096)
            cid = row["customer_id"]
            if (cid in before and before.get(cid) == after.get(cid)
                    and isinstance(checkpoint, dict) and checkpoint.get("role") == "checkpoint"
                    and IC.continuity_matches(bridge, checkpoint, prior, before[cid])):
                self._set_meta(c, key, IC._dump(IC.continuity_proof(checkpoint, current, after[cid])))
            else:
                self._set_meta(c, key, 'null')

    def _record_inspection_org_continuity(self, c, accepted):
        """Called only inside the existing accepted organization transaction."""
        S = _storage()
        try:
            current, sync = self.org_current(), self.last_sync(S.SYNC_ORG)
            old = current["body"] if current is not None and sync is not None and sync["outcome"] == S.SYNC_ACCEPTED else None
        except S.StoreError:
            old = None
        previous = self._inspection_read_proof(c, IC.ORG_CONTINUITY_KEY, 4096)
        self._set_meta(c, IC.ORG_CONTINUITY_KEY, IC.new_org_continuity(previous, old, accepted))

    def _inspection_manual_job(self, request, row, snapshot, catalog_at, fingerprint, now, source=None):
        S = _storage()
        if request is None or request.get("request_kind") == "manual_period":
            return None
        cycle = datetime.fromisoformat(request["requested_at"]).astimezone(S.KST).date()
        # 지난 수동 요청을 오늘 자동 관측보다 새 현재 자료로 되살리지 않는다.
        if cycle != now.astimezone(S.KST).date():
            return None
        end = date.fromisoformat(request["period_end"]) if request.get("period_end") else cycle-timedelta(days=1)
        start = date.fromisoformat(request["period_start"]) if request.get("period_start") else (
            end if row["decision"].cadence == "daily" else end-timedelta(days=6))
        job = self._performance_job(request["customer_id"], "manual", cycle, start, end, row, snapshot,
                                    catalog_at, matching_fingerprint=fingerprint)
        job["job_key"] = "inspection:"+job["job_key"]+":"+request["requested_at"]
        job.update(requested_at=request["requested_at"], actor=request["actor"], generation=request["requested_at"])
        return job if self._inspection_account_valid(job, now, source) else None

    def inspection_work(self, now, limit=24, *, observe=None):
        S = _storage()
        if type(limit) is not int or not 1 <= limit <= 24:
            raise S.StoreRefused("설정 관측 후보는 1~24개입니다")
        S._kst_text(now, "현재")
        if now.astimezone(S.KST).time().replace(tzinfo=None) < P.COLLECTION_START:
            return []
        policies = self.synchronize_management(now)
        requests = {r["customer_id"]: r for r in S._rows(self._conn.execute("SELECT * FROM naver_auto_manual_read"))}
        source = self._performance_selection_source(now, policies, requests)
        snapshot, catalog = source.snapshot, source.catalog
        if snapshot is None or catalog is None:
            return []
        day, at, fingerprint = now.astimezone(S.KST).date(), S._kst_text(now, "현재"), source.fingerprint
        prior = {r["job_key"]: r for r in S._rows(self._conn.execute(
            "SELECT * FROM naver_auto_inspection_job WHERE cycle_day>=?", ((day-timedelta(days=8)).isoformat(),)))}
        catalog_proof = self._inspection_catalog_proof(now)
        candidates, continuity_cache = [], {}
        if observe is not None:
            _observe_selection(observe, "selection_started", customers=tuple(policies))
        for cid, row in policies.items():
            cadence = row["decision"].cadence
            if cadence == "blocked":
                _observe_selection(observe, "selection_policy_blocked", cid)
                continue
            manual = self._inspection_manual_job(requests.get(cid), row, snapshot, catalog["generated_at"], fingerprint, now, source)
            period = P.period_for(cadence, day)
            automatic = self._performance_job(cid, cadence, period.cycle_day, period.since, period.until, row, snapshot,
                                               catalog["generated_at"], matching_fingerprint=fingerprint)
            automatic["job_key"] = "inspection:"+automatic["job_key"]
            # 오늘의 명시적 재확인 세대가 있으면 오래된 자동 회차로 우회하지 않는다.
            job = manual or automatic
            old = prior.get(job["job_key"])
            attempted_at = _inspection_order_attempt(old, job, row["possibility_id"], now)
            started = (old is not None and old["stage_revision"] == job["stage_revision"]
                       and old["possibility_id"] == row["possibility_id"] and old["generation"] == job["generation"])
            bound = _binding(old, job, row["possibility_id"]) and IC._scope_matches(old, job, row["possibility_id"])
            if bound and old["status"] == "ok" and self._inspection_context(self._conn, old, now, catalog_proof) is None:
                bound = False
            if not bound and not self._inspection_resumable(self._conn, old, job, row["possibility_id"], now, catalog_proof, continuity_cache):
                old = None
            if old and not self._collection_retry_ready(old, at):
                _observe_selection(observe, "selection_retry_wait", cid)
                continue
            if job["kind"] == "weekly" and not P.is_due(row["decision"], day,
                    started_cycle=period.cycle_day if started else None):
                _observe_selection(observe, "selection_weekly_not_due", cid)
                continue
            if not self._collection_account_ready(cid, at):
                _observe_selection(observe, "selection_account_wait", cid)
                continue
            if not self._inspection_account_valid(job, now, source):
                _observe_selection(observe, "selection_account_scope_invalid", cid)
                continue
            candidates.append((-1 if manual else 0 if cadence == "daily" else 1,
                               attempted_at, cid, job))
        selected, manual_selected = [], False
        has_daily = any(entry[0] == 0 for entry in candidates)
        ordered = sorted(candidates, key=lambda entry: entry[:3])
        for position, (priority, _, _, job) in enumerate(ordered):
            if priority == -1 and has_daily and manual_selected:
                _observe_selection(observe, "selection_manual_quota", job["customer_id"])
                continue
            selected.append(job)
            manual_selected |= priority == -1
            if len(selected) == limit:
                if observe is not None:
                    for _, _, cid, _ in ordered[position + 1:]:
                        _observe_selection(observe, "selection_behind_window", cid)
                break
        return selected

    def inspection_account_valid(self, job, now):
        # HTTP 전·후와 저장 시에는 항상 새 원천으로 확인한다.
        if not self._inspection_account_valid(job, now):
            return False
        S = _storage()
        rows = S._rows(self._conn.execute("SELECT "+_INSPECTION_BINDING_COLUMNS+",CASE WHEN progress_json IS NULL THEN NULL ELSE 1 END AS progress_json FROM naver_auto_inspection_job WHERE job_key=?", (job["job_key"],)))
        if not rows:
            return True  # authority query before begin; the collector begins before issuing a handle.
        row = rows[0]
        state = self.management_states().get(job["customer_id"])
        if not state or not _binding(row, job, state["possibility_id"]) or not IC._scope_matches(row, job, state["possibility_id"]):
            return False
        return self._inspection_context(self._conn, row, now, self._inspection_catalog_proof(now)) is not None

    def _inspection_account_valid(self, job, now, source=None):
        S = _storage()
        if (not isinstance(job, dict) or not isinstance(job.get("job_key"), str)
                or not job["job_key"].startswith("inspection:") or job.get("kind") not in ("daily", "weekly", "manual")):
            return False
        try:
            cycle = date.fromisoformat(job["cycle_day"])
            if job["kind"] == "manual":
                if cycle != now.astimezone(S.KST).date():
                    return False
            elif cycle != P.period_for(job["kind"], now).cycle_day:
                return False
            plain = dict(job, job_key=job["job_key"][11:])
            if not (self.performance_account_valid(plain, now) if source is None else
                    self._performance_account_valid(plain, now, source)):
                return False
            if job["kind"] != "manual":
                # 수동 재확인 요청보다 이전 자동 작업의 늦은 응답을 받지 않는다.
                if source is None:
                    requests = S._rows(self._conn.execute("SELECT requested_at,possibility_id,request_kind,actor FROM naver_auto_manual_read WHERE customer_id=?",
                                                         (job["customer_id"],)))
                    request = requests[0] if requests else None
                else:
                    request = source.manual_requests.get(job["customer_id"])
                state = (self.management_states() if source is None else source.states).get(job["customer_id"])
                if request and request["request_kind"] != "manual_period" and state and request["possibility_id"] == state["possibility_id"] \
                        and datetime.fromisoformat(request["requested_at"]).astimezone(S.KST).date() == now.astimezone(S.KST).date() \
                        and request["requested_at"] > job["generation"]:
                    from . import management_store as MS
                    from app.naver_auto import scope as SC
                    try:
                        if source is None:
                            MS.require_action(self, now, request["actor"], job["customer_id"],
                                              possibility_id=state["possibility_id"], allow_unmatched=True)
                        else:
                            source.require_action(request["actor"], job["customer_id"], possibility_id=state["possibility_id"])
                    except (S.StoreRefused, SC.ClientNotVisible, SC.ActionNotAllowed):
                        pass
                    else:
                        return False
            return True
        except (S.StoreRefused, KeyError, TypeError, ValueError, OverflowError):
            return False

    def begin_inspection_check(self, job, now):
        S = _storage()
        self._need_writer()
        self._not_future(now, "설정 관측 시작")
        if not self._inspection_account_valid(job, now):
            raise S.StoreRefused("설정 관측 권한 또는 회차가 바뀌었습니다")
        at = S._kst_text(now, "설정 관측 시작")
        if not self._collection_account_ready(job["customer_id"], at):
            raise S.StoreRefused("계정의 인증 또는 통신 재시도 대기 중입니다")
        pid = self.management_states()[job["customer_id"]]["possibility_id"]
        with self._tx() as c:
            rows = S._rows(c.execute("SELECT * FROM naver_auto_inspection_job WHERE job_key=?", (job["job_key"],)))
            old = rows[0] if rows else None
            same = _binding(old, job, pid) and IC._scope_matches(old, job, pid)
            catalog_proof = self._inspection_catalog_proof(now, c)
            if catalog_proof is None:
                raise S.StoreRefused("설정 관측 전산 내용 증명을 확인하지 못했습니다")
            continued = self._inspection_resumable(c, old, job, pid, now, catalog_proof)
            # Exact authority binding still enforces retry state. It is not a
            # semantic proof for a checkpoint, even when timestamps coincide.
            # An unproved old success is a fresh-read candidate, not current evidence.
            bound = same and (old["status"] != "ok" or self._inspection_context(c, old, now, catalog_proof) is not None) or continued
            if bound and not self._collection_retry_ready(old, at):
                raise S.StoreRefused("설정 관측을 다시 수집할 시각이 아닙니다")
            columns = (*_JOB_FIELDS, "possibility_id", "requested_at", "actor", "status", "checked_at", "next_try_at",
                       "attempts", "error_code", "progress_json", "progress_hash")
            values = [S._kst_text(job[key], "계정 원천") if key == "snapshot_at" else job[key] for key in _JOB_FIELDS]
            values += [pid, job.get("requested_at"), job.get("actor"), "reading", at,
                       S._kst_text(now+timedelta(minutes=2), "설정 관측 대기"), old["attempts"] if bound else 0,
                       old["error_code"] if bound else None, old["progress_json"] if continued else None,
                       old["progress_hash"] if continued else None]
            c.execute("INSERT INTO naver_auto_inspection_job ("+",".join(columns)+") VALUES ("+",".join("?" for _ in columns)+
                      ") ON CONFLICT(job_key) DO UPDATE SET "+",".join(key+"=excluded."+key for key in columns if key != "job_key"), values)
            self._record_inspection_context(c, dict(zip(columns, values)),
                                            json.loads(old["progress_json"]) if continued else None, now, catalog_proof, initialize=True)

    def inspection_progress(self, job):
        from . import inspection_reads as R
        row = self._conn.execute("SELECT progress_json,progress_hash,stage_revision,generation FROM naver_auto_inspection_job WHERE job_key=?",
                                 (job["job_key"],)).fetchone()
        if row is None or row[0] is None:
            return None
        if row[2] != job["stage_revision"] or row[3] != job["generation"]:
            raise R.CheckpointInvalid("설정 관측 귀속 또는 세대가 다릅니다")
        if not isinstance(row[0], str) or len(row[0].encode()) > _MAX_BYTES or _digest(row[0]) != row[1]:
            raise R.CheckpointInvalid("설정 관측 지문 또는 크기가 다릅니다")
        try:
            source = json.loads(row[0])
        except (TypeError, ValueError):
            raise R.CheckpointInvalid("설정 관측 모양을 확인하지 못했습니다") from None
        return R.validate_progress(source, job)

    def record_inspection_progress(self, job, now, progress):
        from . import inspection_reads as R
        S = _storage()
        self._need_writer()
        self._not_future(now, "설정 관측 시각")
        if not self.inspection_account_valid(job, now):
            raise S.StoreRefused("설정 관측 권한 또는 회차가 바뀌었습니다")
        R.validate_progress(progress, job)
        if any(datetime.fromisoformat(at) > now for at in _observed_times(progress)):
            raise S.StoreRefused("미래 설정 관측은 저장하지 않습니다")
        body = S._json(progress)
        if len(body.encode()) > _MAX_BYTES:
            raise S.StoreRefused("설정 관측 저장 한도를 넘었습니다")
        with self._tx() as c:
            rows = S._rows(c.execute("SELECT * FROM naver_auto_inspection_job WHERE job_key=? AND status='reading'",
                                    (job["job_key"],)))
            if not rows:
                raise S.StoreRefused("시작하지 않은 설정 관측입니다")
            catalog_proof = self._inspection_catalog_proof(now, c)
            if self._inspection_context(c, rows[0], now, catalog_proof) is None:
                raise S.StoreRefused("설정 관측 전산 내용 증명이 바뀌었습니다")
            old = self.inspection_progress(job)
            if old is not None and progress["next_index"] < old["next_index"]:
                initial = (progress["next_index"] == 0 and not progress["confirmed"] and not progress["targets"]
                    and not progress["performance"] and len(progress["entities"]) == len(progress["campaigns"])
                    and all(row["entity"] == "campaign" for row in progress["entities"].values())
                    and progress["queue"] == R._initial(progress["campaigns"], job, now,
                        detail_reads=progress["version"] == 2)["queue"]
                    and all(datetime.fromisoformat(row["checked_at"]) >= max(
                        (datetime.fromisoformat(at) for at in _observed_times(old)), default=now)
                        for row in progress["entities"].values()))
                if not initial:
                    raise S.StoreRefused("설정 관측 재개 위치가 되돌아갔습니다")
            advanced = old is not None and progress["next_index"] > old["next_index"]
            c.execute("""UPDATE naver_auto_inspection_job SET progress_json=?,progress_hash=?,
                attempts=CASE WHEN ? THEN 0 ELSE attempts END WHERE job_key=?""",
                      (body, _digest(body), int(advanced), job["job_key"]))
            saved = S._rows(c.execute("SELECT * FROM naver_auto_inspection_job WHERE job_key=?", (job["job_key"],)))[0]
            self._record_inspection_context(c, saved, progress, now, catalog_proof)

    def _inspection_history(self, c, job, pid, progress, at):
        S = _storage()
        current = {}
        for row in progress["entities"].values():
            current[(row["entity"], row["id"])] = (row["parent_id"], row["campaign_id"], row["settings"])
        for group, targets in progress["targets"].items():
            campaign = progress["entities"]["adgroup:"+group]["campaign_id"]
            for kind, row in targets.items():
                current[("target:"+kind, group)] = (group, campaign, {"state": row["state"], "records": row["records"]})
        old_rows = S._rows(c.execute("""SELECT r.* FROM naver_auto_setting_observation r
            WHERE customer_id=? AND possibility_id IS ? AND stage_revision=? AND history_id=(
                SELECT MAX(p.history_id) FROM naver_auto_setting_observation p WHERE p.customer_id=r.customer_id
                AND p.possibility_id IS r.possibility_id AND p.stage_revision=r.stage_revision
                AND p.entity=r.entity AND p.entity_id=r.entity_id)""", (job["customer_id"], pid, job["stage_revision"])))
        prior = {}
        for row in old_rows:
            if not isinstance(row["body_json"], str) or len(row["body_json"].encode()) > _MAX_BYTES \
                    or _digest(row["body_json"]) != row["body_hash"]:
                raise S.StoreRefused("설정 관측 이력 지문이 다릅니다")
            body = _history_body(row["body_json"], job["customer_id"], pid, job["stage_revision"], datetime.fromisoformat(at))
            if body is None or body["entity"] != row["entity"] or body["id"] != row["entity_id"]:
                raise S.StoreRefused("설정 관측 이력 모양이 다릅니다")
            prior[(row["entity"], row["entity_id"])] = body
        for key in sorted(set(prior) | set(current)):
            before = prior.get(key, {}).get("after")
            after = current.get(key, (None, None, None))[2]
            if before == after:
                continue
            parent, campaign, _ = current.get(key, (prior[key]["parent_id"], prior[key]["campaign_id"], None)) if key in prior \
                else current[key]
            body = dict(possibility_id=pid, customer_id=job["customer_id"], stage_revision=job["stage_revision"],
                        entity=key[0], id=key[1], parent_id=parent, campaign_id=campaign, observed_at=at,
                        generation=job["generation"], cycle_day=job["cycle_day"], execution="observed",
                        change_kind="removed" if after is None else "initial" if before is None else "changed",
                        before=before, after=after)
            encoded = S._json(body)
            c.execute("""INSERT INTO naver_auto_setting_observation
                (customer_id,possibility_id,stage_revision,entity,entity_id,observed_at,generation,cycle_day,body_json,body_hash)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (job["customer_id"], pid, job["stage_revision"], *key, at,
                job["generation"], job["cycle_day"], encoded, _digest(encoded)))

    def record_inspection_check(self, job, now, values):
        from . import inspection_reads as R
        S = _storage()
        self._need_writer()
        self._not_future(now, "설정 관측 확인")
        if not isinstance(values, dict):
            raise S.StoreRefused("설정 관측 상태가 올바르지 않습니다")
        status, code = values.get("status"), values.get("error_code")
        expired = values.get("_final_confirmation_expired", False)
        if (type(expired) is not bool or expired and
                (status not in ("partial", "retry") or code != "REQUEST_DEADLINE")):
            raise S.StoreRefused("설정 관측 최종 확인 중단 상태가 올바르지 않습니다")
        if status not in ("ok", "partial", "retry", "limited", "reauth_required") or (code is not None and
                (not isinstance(code, str) or code not in _ERROR_CODES)):
            raise S.StoreRefused("설정 관측 상태가 올바르지 않습니다")
        invalid_checkpoint = status == "limited" and code == "CHECKPOINT_INVALID"
        if not self.inspection_account_valid(job, now) and not (
                invalid_checkpoint and self._inspection_account_valid(job, now)):
            raise S.StoreRefused("설정 관측 권한 또는 회차가 바뀌었습니다")
        try:
            progress = self.inspection_progress(job)
        except R.CheckpointInvalid:
            if status != "limited" or code != "CHECKPOINT_INVALID":
                raise S.StoreRefused("손상 설정 관측을 완료로 저장하지 않습니다") from None
            progress = None
        if status == "ok" and (progress is None or progress["next_index"] != len(progress["queue"]) or not progress["confirmed"]):
            raise S.StoreRefused("미완결 설정 관측입니다")
        at = S._kst_text(now, "설정 관측 확인")
        pid = self.management_states()[job["customer_id"]]["possibility_id"]
        with self._tx() as c:
            rows = S._rows(c.execute("SELECT * FROM naver_auto_inspection_job WHERE job_key=? AND status='reading'",
                                    (job["job_key"],)))
            if not rows:
                raise S.StoreRefused("시작하지 않은 설정 관측입니다")
            row = rows[0]
            catalog_proof = self._inspection_catalog_proof(now, c)
            if catalog_proof is None or invalid_checkpoint and (
                    not _binding(row, job, pid) or not IC._scope_matches(row, job, pid)):
                raise S.StoreRefused("설정 관측 권한 또는 회차가 바뀌었습니다")
            if self._inspection_context(c, row, now, catalog_proof) is None and not invalid_checkpoint:
                raise S.StoreRefused("설정 관측 전산 내용 증명이 바뀌었습니다")
            if expired:
                # The final fresh root was read in this attempt, but the outer
                # deadline refused completion. Keep only unfinished evidence;
                # the next bounded attempt must read the final root again.
                progress = self.inspection_progress(job)
                if (progress is None or not progress["confirmed"]
                        or progress["next_index"] != len(progress["queue"])
                        or any(datetime.fromisoformat(at) > now for at in _observed_times(progress))):
                    raise S.StoreRefused("설정 관측 최종 확인 재개 근거가 올바르지 않습니다")
                progress = dict(progress, confirmed=False)
                body = S._json(progress)
                if len(body.encode()) > _MAX_BYTES:
                    raise S.StoreRefused("설정 관측 저장 한도를 넘었습니다")
                c.execute("UPDATE naver_auto_inspection_job SET progress_json=?,progress_hash=? WHERE job_key=?",
                          (body, _digest(body), job["job_key"]))
            # This is the bounded retry stage, not a lifetime failure counter.
            # Hourly limited resumes must still fit the checkpoint's four stages.
            attempts = min(4, row["attempts"]+int(status == "retry" and code not in ("REQUEST_DEADLINE", "REQUEST_CALL_CAP")))
            if attempts >= 4 and status == "retry":
                status = "limited"
            delay = (2, 5, 15, 30)[max(0, min(attempts, 4)-1)] if status == "retry" else 0
            if status == "retry" and code in ("REQUEST_DEADLINE", "REQUEST_CALL_CAP"):
                delay = 0
            if status == "limited" and code in ("SERVER", "NETWORK", "RATE", "REQUEST_DEADLINE", "REQUEST_CALL_CAP", "REQUEST_BUDGET"):
                delay = 60
            if status == "ok":
                self._inspection_history(c, job, pid, progress, at)
            c.execute("""UPDATE naver_auto_inspection_job SET status=?,checked_at=?,next_try_at=?,attempts=?,error_code=?
                WHERE job_key=?""", (status, at, S._kst_text(now+timedelta(minutes=delay), "설정 관측 대기"), attempts, code, job["job_key"]))
            saved = S._rows(c.execute("SELECT * FROM naver_auto_inspection_job WHERE job_key=?", (job["job_key"],)))[0]
            if invalid_checkpoint:
                self._clear_inspection_context(c, job["job_key"])
            else:
                self._record_inspection_context(c, saved, progress, now, catalog_proof)
        return status

    def _inspection_observation_valid(self, row, now):
        """Read-only completion continuity; never authorizes collector writes.

        A freshly accepted identical catalog does not invalidate already sealed
        completed evidence. All current account/org/matching/stage/manual gates
        still run against the latest catalog; partial and unproved rows retain
        the ordinary exact-source rule.
        """
        job = _job(row)
        if self.inspection_account_valid(job, now):
            return True
        if row['status'] != 'ok':
            return False
        catalog = self._inspection_catalog_proof(now)
        proof = self._inspection_context(self._conn, row, now, catalog)
        if proof is None or proof['role'] != 'complete':
            return False
        current_job = dict(job, catalog_at=catalog['generated_at'])
        if not self._inspection_account_valid(current_job, now):
            return False
        state = self.management_states().get(job['customer_id'])
        return bool(state and _binding(row, job, state['possibility_id'])
                    and IC._scope_matches(row, current_job, state['possibility_id']))

    def inspection_checkpoint_summary(self, customer_id, now, observation):
        """Four saved progress fields for the same current observation; never writes."""
        from . import inspection_reads as R
        S = _storage()
        cid = S._customer_id(customer_id, "계정")
        S._kst_text(now, "현재")
        try:
            if (not isinstance(observation, dict) or type(observation.get("customer_id")) is not int
                    or observation["customer_id"] != cid or observation.get("stale") is not False
                    or observation.get("status") not in ("reading", "partial", "retry", "limited", "reauth_required", "ok")
                    or not isinstance(observation.get("generation"), str)
                    or not isinstance(observation.get("checked_at"), str)):
                return None
            rows = S._rows(self._conn.execute("""SELECT * FROM naver_auto_inspection_job
                WHERE customer_id=? AND possibility_id IS ? AND stage_revision=? AND generation=?
                AND checked_at=? AND status=? LIMIT 2""", (cid, observation.get("possibility_id"),
                    observation.get("stage_revision"), observation["generation"], observation["checked_at"],
                    observation["status"])))
            if len(rows) != 1 or not self._inspection_observation_valid(rows[0], now):
                return None
            row = rows[0]
            raw = row["progress_json"]
            if not isinstance(raw, str) or len(raw.encode()) > _MAX_BYTES or _digest(raw) != row["progress_hash"]:
                return None
            # Parse the matched row itself. A second SELECT could mix newer
            # progress with this observation's older status and checked_at.
            progress = R.validate_progress(json.loads(raw), _job(row))
            if (datetime.fromisoformat(row["generation"]) > now
                    or datetime.fromisoformat(row["checked_at"]) > now
                    or any(datetime.fromisoformat(at) > now for at in _observed_times(progress))):
                return None
            index, queue = progress["next_index"], progress["queue"]
            return dict(next_index=index, queue_len=len(queue),
                        current_task_kind=queue[index]["kind"] if index < len(queue) else None,
                        confirmed=progress["confirmed"])
        except (R.CheckpointInvalid, S.StoreRefused, KeyError, TypeError, ValueError, OverflowError, RecursionError):
            return None

    def setup_observation(self, customer_id, now):
        """Current observation contract; optional diagnostics never enter this result."""
        return self._setup_observation_read(customer_id, now)

    def _setup_observation_read(self, customer_id, now, *, _diagnostic=None):
        """현재 관측만 반환하는 읽기. 이전 성공을 새 실패·수동 대기 자료로 빌리지 않는다."""
        from . import management_store as MS, inspection_reads as R
        S = _storage()
        cid = S._customer_id(customer_id, "계정")
        S._kst_text(now, "현재")
        if _diagnostic is not None:
            _diagnostic.update(source_rejection_branch="none", policy=None, manual=None, requests=[], row=None)
        exists = self._conn.execute("SELECT 1 FROM naver_auto_inspection_job WHERE customer_id=? LIMIT 1", (cid,)).fetchone()
        requests = S._rows(self._conn.execute("SELECT * FROM naver_auto_manual_read WHERE customer_id=?", (cid,)))
        if _diagnostic is not None:
            _diagnostic["requests"] = requests
        if exists is None and not requests:
            return None
        policy = MS.snapshot(self, now).get(cid)
        if _diagnostic is not None:
            _diagnostic["policy"] = policy
        active = policy is not None and policy["decision"].cadence != "blocked"
        pid, revision = (policy["possibility_id"], policy["stage_revision"]) if policy else (None, None)
        manual = None
        if active and requests:
            catalog, snapshot = self.account_catalog(), self.inventory_snapshot(now)
            if catalog and snapshot is not None:
                manual = self._inspection_manual_job(requests[0], policy, snapshot, catalog["generated_at"], self.decision_fingerprint(), now)
        if _diagnostic is not None:
            _diagnostic["manual"] = manual
        if exists is None and manual is None:
            return None
        out = dict(version=1, customer_id=cid, possibility_id=pid, stage_revision=revision, status="pending",
                   checked_at=None, error_code=None, complete=False, stale=True, generation=None,
                   period_start=None, period_end=None, campaigns=[], entities={}, targets={}, performance={}, history=[])
        if not active:
            if _diagnostic is not None:
                _diagnostic["source_rejection_branch"] = "policy_blocked"
            out["error_code"] = "SOURCE_STALE"
            return out
        cadence = policy["decision"].cadence
        cycle = str(P.period_for(cadence, now).cycle_day)
        projection = "*" if _diagnostic is None else (_INSPECTION_BINDING_COLUMNS+",CASE WHEN progress_json IS NULL THEN NULL WHEN typeof(progress_json)='text' AND length(CAST(progress_json AS BLOB))<=8388608 THEN progress_json ELSE '!' END AS progress_json")
        scope_rows = S._rows(self._conn.execute("SELECT "+projection+""" FROM naver_auto_inspection_job WHERE customer_id=?
            AND possibility_id IS ? AND stage_revision=? AND ((kind=? AND cycle_day=?) OR (kind='manual' AND generation=?))
            ORDER BY generation DESC,checked_at DESC,rowid DESC LIMIT 1""",
            (cid, pid, revision, cadence, cycle, manual["generation"] if manual else None)))
        row = scope_rows[0] if scope_rows else None
        if _diagnostic is not None:
            _diagnostic["row"] = row
        history = [] if _diagnostic is not None else S._rows(self._conn.execute("""SELECT history_id,body_json,body_hash FROM naver_auto_setting_observation
            WHERE customer_id=? AND possibility_id IS ? AND stage_revision=? ORDER BY history_id DESC LIMIT 200""", (cid, pid, revision)))
        for item in history:
            if not isinstance(item["body_json"], str) or len(item["body_json"].encode()) > _MAX_BYTES \
                    or _digest(item["body_json"]) != item["body_hash"]:
                continue
            body = _history_body(item["body_json"], cid, pid, revision, now)
            if body is not None:
                out["history"].append(dict(body, history_id=item["history_id"]))
        if manual is not None and (row is None or row["generation"] < manual["generation"]):
            out.update(generation=manual["generation"], period_start=manual["period_start"], period_end=manual["period_end"],
                       error_code="MANUAL_PENDING", stale=False)
            return out
        if row is None:
            return out
        current = row["cycle_day"] == str(P.period_for(policy["decision"].cadence, now).cycle_day)
        if row["kind"] == "manual":
            current = row["cycle_day"] == str(now.astimezone(S.KST).date()) and manual is not None and row["generation"] == manual["generation"]
        if not current:
            return out
        # 목록/전산/직원 권한의 최신 세대가 바뀐 동안 과거 성공을 현재 관측으로 표시하지 않는다.
        if not self._inspection_observation_valid(row, now):
            if _diagnostic is not None:
                _diagnostic["source_rejection_branch"] = "observation_invalid"
            out["error_code"] = "SOURCE_STALE"
            return out
        out.update(status=row["status"], checked_at=row["checked_at"], error_code=row["error_code"], stale=False,
                   generation=row["generation"], period_start=row["period_start"], period_end=row["period_end"])
        if _diagnostic is not None:
            return out
        if datetime.fromisoformat(row["checked_at"]) > now:
            out.update(status="pending", error_code="CHECKPOINT_INVALID", stale=True, checked_at=None)
            return out
        if row["status"] != "ok":
            return out
        try:
            progress = self.inspection_progress(_job(row))
            if progress is None or not progress["confirmed"] or progress["next_index"] != len(progress["queue"]) \
                    or any(datetime.fromisoformat(at) > now for at in _observed_times(progress)) \
                    or datetime.fromisoformat(row["generation"]) > now:
                raise R.CheckpointInvalid("미완결 설정 관측입니다")
        except (R.CheckpointInvalid, TypeError, ValueError):
            out.update(status="limited", error_code="CHECKPOINT_INVALID")
            return out
        out.update(complete=True, campaigns=progress["campaigns"], entities=progress["entities"],
                   targets=progress["targets"], performance=progress["performance"])
        if progress["version"] == 2:
            from . import shared_budget_evidence as B
            proof = B.make(out, progress["campaign_budget_details"], now)
            if proof is not None:
                out["campaign_budget_proof"] = proof
        return out

    def inspection_binding_diagnostic(self, customer_id, now, *, possibility_id, latest_job_key=None):
        """One read snapshot; candidate-only facts, never scheduler/authority/completion proof."""
        from . import inventory as I, management_store as MS
        S = _storage()
        out = dict(version=1, scope="local_candidate_only", current_source_not_proven=True,
                   evaluated_at=None, source_rejection_branch="unknown", job_match="unknown",
                   binding_current=None, continuation_valid=None, retry_ready=None,
                   account_ready=None, local_exclusion="unknown")
        try:
            cid = S._customer_id(customer_id, "계정")
            out["evaluated_at"] = S._kst_text(now, "현재")
            if type(possibility_id) is not int or possibility_id <= 0:
                return out
            with self.read_snapshot():
                capture = {}
                self._setup_observation_read(cid, now, _diagnostic=capture)
                out["source_rejection_branch"] = capture["source_rejection_branch"]
                policy = capture["policy"]
                if policy is None:
                    policy = MS.snapshot(self, now).get(cid)
                if policy is None:
                    return dict(out, job_match="no_candidate", local_exclusion="policy_blocked") if capture["source_rejection_branch"] == "policy_blocked" else out
                if policy["decision"].cadence == "blocked" and policy["possibility_id"] in (None, possibility_id):
                    return dict(out, job_match="no_candidate", local_exclusion="policy_blocked")
                if policy["possibility_id"] != possibility_id:
                    return dict(out, source_rejection_branch="unknown")
                states = self.management_states()
                state = states.get(cid)
                if (state is None or any(state.get(key) != policy.get(key)
                        for key in ("possibility_id", "stage_key", "stage_revision"))):
                    return dict(out, local_exclusion="management_sync_pending")
                if now.astimezone(S.KST).time().replace(tzinfo=None) < P.COLLECTION_START:
                    return dict(out, job_match="no_candidate", local_exclusion="before_start")
                snapshot = self.inventory_snapshot(now)
                catalog, catalog_state = I.catalog_status(self, now, header_only=True)
                if snapshot is None or catalog_state != "accepted":
                    return dict(out, job_match="no_candidate", local_exclusion="source_unavailable")
                period = P.period_for(policy["decision"].cadence, now)
                manual = capture["manual"]
                job = manual or self._performance_job(cid, policy["decision"].cadence,
                    period.cycle_day, period.since, period.until, policy, snapshot,
                    catalog["generated_at"], matching_fingerprint=self.decision_fingerprint())
                if manual is None:
                    job["job_key"] = "inspection:"+job["job_key"]
                rows = S._rows(self._conn.execute("SELECT "+_INSPECTION_BINDING_COLUMNS+
                    ",CASE WHEN progress_json IS NULL THEN NULL WHEN typeof(progress_json)='text' AND length(CAST(progress_json AS BLOB))<=8388608 THEN progress_json ELSE '!' END AS progress_json FROM naver_auto_inspection_job WHERE job_key=? AND customer_id=? LIMIT 2", (job["job_key"], cid)))
                if len(rows) > 1:
                    return dict(out, source_rejection_branch="unknown")
                old = rows[0] if rows else None
                if old is not None:
                    IC._binding(old, _ERROR_CODES)
                    for key in ("generation", "checked_at", "snapshot_at", "catalog_at"):
                        at = datetime.fromisoformat(old[key])
                        if at.utcoffset() is None or at > now:
                            return dict(out, source_rejection_branch="unknown")
                    retry_at = datetime.fromisoformat(old["next_try_at"])
                    if retry_at.utcoffset() is None or retry_at < datetime.fromisoformat(old["checked_at"]):
                        return dict(out, source_rejection_branch="unknown")
                if latest_job_key is not None and (type(latest_job_key) is not str or not latest_job_key.startswith("inspection:") or len(latest_job_key) > 500):
                    return dict(out, source_rejection_branch="unknown")
                out["job_match"] = ("candidate_not_stored" if old is None else "unknown" if latest_job_key is None else
                    "same" if latest_job_key == job["job_key"] else "different")
                catalog_proof = self._inspection_catalog_proof(now)
                started = old is not None and old["stage_revision"] == job["stage_revision"] \
                    and old["possibility_id"] == possibility_id and old["generation"] == job["generation"]
                bound = bool(_binding(old, job, possibility_id) and IC._scope_matches(old, job, possibility_id))
                if bound and old["status"] == "ok" and self._inspection_context(self._conn, old, now, catalog_proof) is None:
                    bound = False
                continued = self._inspection_resumable(self._conn, old, job, possibility_id, now, catalog_proof)
                retained = old if bound or continued else None
                retry = self._collection_retry_ready(retained, S._kst_text(now, "현재"))
                ready = self._collection_account_ready(cid, S._kst_text(now, "현재"))
                out.update(binding_current=bound, continuation_valid=continued, retry_ready=bool(retry), account_ready=bool(ready))
                if not retry:
                    out["local_exclusion"] = "retry_wait"
                elif job["kind"] == "weekly" and not P.is_due(policy["decision"], now,
                        started_cycle=period.cycle_day if started else None):
                    out["local_exclusion"] = "weekly_not_due"
                elif not ready:
                    out["local_exclusion"] = "account_wait"
                elif not self._inspection_account_valid(job, now):
                    out["local_exclusion"] = "account_scope_invalid"
                else:
                    out["local_exclusion"] = "ready_bound" if bound else "ready_continuation" if continued else "ready_fresh_read"
                return out
        except (S.StoreError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
            return dict(version=1, scope="local_candidate_only", current_source_not_proven=True,
                        evaluated_at=out["evaluated_at"], source_rejection_branch="unknown", job_match="unknown",
                        binding_current=None, continuation_valid=None, retry_ready=None,
                        account_ready=None, local_exclusion="unknown")
