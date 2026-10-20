"""Inspection-only continuation proofs; never authority or completion evidence.

Current source validators stay exact. New unfinished checkpoints may cross an
unbroken accepted catalog chain only when their account/matching/policy scope is
unchanged; accepted organization timestamp updates need a sealed semantic epoch.
Old writers or missing proofs break these schema-21 continuation chains.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid

CATALOG_KEY = "inspection-catalog-proof:v1"
CHECKPOINT_PREFIX = "inspection-checkpoint-proof:v1:"
_CATALOG_FIELDS = {"version", "generated_at", "stable_content_at", "content_digest", "content_epoch", "proof_hash"}
_CHECKPOINT_FIELDS = {"version", "role", "binding", "content_digest", "content_epoch", "stable_content_at", "proof_hash"}
_BINDING_FIELDS = ("job_key", "customer_id", "possibility_id", "kind", "cycle_day", "period_start", "period_end",
    "snapshot_at", "catalog_at", "stage_revision", "matching_fingerprint", "generation", "requested_at", "actor",
    "status", "checked_at", "next_try_at", "attempts", "error_code", "progress_hash")
_SCOPE_FIELDS = _BINDING_FIELDS[:14]


def _dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def _hex(value, length=64):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{"+str(length)+"}", value) is not None


def _time(value):
    if not isinstance(value, str):
        raise ValueError("inspection proof time")
    at = datetime.fromisoformat(value)
    if at.utcoffset() is None:
        raise ValueError("inspection proof timezone")
    return at


def decode_proof(raw, limit):
    """Decode an already bounded value; this module never receives a connection."""
    if not isinstance(raw, str) or len(raw.encode()) > limit:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        return None


def _sealed(value, fields):
    return (isinstance(value, dict) and set(value) == fields and type(value["version"]) is int
            and value["version"] == 1 and _hex(value["proof_hash"])
            and value["proof_hash"] == _hash({k: v for k, v in value.items() if k != "proof_hash"}))


def _seal(value):
    return dict(value, proof_hash=_hash(value))


def content_digest(body):
    """All clean catalog fields and ID rows, including types and duplicate claims.

    Sorting makes row order immaterial, but never deduplicates or normalizes IDs.
    The two collection timestamps are the only omitted material.
    """
    from . import erp_read as E
    if not isinstance(body, dict) or set(body) != {"generated_at", "received_at", "total", "complete", "items", "ids"}:
        raise ValueError("inspection catalog shape")
    at = _time(body["generated_at"])
    _time(body["received_at"])
    try:
        clean = E.validate_account_catalog(body, at)
    except E.ErpError:
        raise ValueError("inspection catalog invalid") from None
    material = {k: v for k, v in body.items() if k not in {"generated_at", "received_at"}}
    # Compare canonical bytes, rather than Python equality (True == 1).
    if _dump({k: body[k] for k in clean}) != _dump(clean) or not isinstance(body["ids"], list):
        raise ValueError("inspection catalog types")
    for row in body["ids"]:
        if (not isinstance(row, dict) or set(row) != {"possibility_id", "vendor", "customer_id_raw", "ad_account_no_raw"}
                or type(row["possibility_id"]) is not int or row["possibility_id"] <= 0
                or any(v is not None and (not isinstance(v, str) or len(v) > 200)
                       for k, v in row.items() if k != "possibility_id")):
            raise ValueError("inspection ID shape")
    material = dict(material, items=sorted(material["items"], key=_dump), ids=sorted(material["ids"], key=_dump))
    return _hash(material)


def catalog_proof(proof, body, now):
    try:
        if (not _sealed(proof, _CATALOG_FIELDS) or proof["generated_at"] != body["generated_at"]
                or not _hex(proof["content_digest"]) or not _hex(proof["content_epoch"], 32)
                or not _time(proof["stable_content_at"]) <= _time(proof["generated_at"]) <= now+timedelta(minutes=5)
                or proof["content_digest"] != content_digest(body)):
            return None
        return proof
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return None


def new_catalog_proof(proof, old, body, now):
    """Return the value for the existing accepted-catalog writer transaction."""
    digest = content_digest(body)
    previous = catalog_proof(proof, old, now) if old is not None else None
    unchanged = previous is not None and previous["content_digest"] == digest
    proof = _seal(dict(version=1, generated_at=body["generated_at"], content_digest=digest,
        stable_content_at=previous["stable_content_at"] if unchanged else body["generated_at"],
        content_epoch=previous["content_epoch"] if unchanged else uuid.uuid4().hex))
    return _dump(proof)


def checkpoint_key(job_key):
    return CHECKPOINT_PREFIX+hashlib.sha256(job_key.encode()).hexdigest()


def _binding(row, error_codes):
    material = {k: row[k] for k in _BINDING_FIELDS}
    if (type(material["customer_id"]) is not int
            or material["possibility_id"] is not None and (type(material["possibility_id"]) is not int or material["possibility_id"] <= 0)
            or type(material["attempts"]) is not int
            or not 0 <= material["attempts"] <= 4
            or material["progress_hash"] is not None and not _hex(material["progress_hash"])
            or material["status"] not in {"reading", "partial", "retry", "limited", "reauth_required", "ok"}
            or material["error_code"] is not None and material["error_code"] not in error_codes):
        raise ValueError("inspection checkpoint state")
    return material


def _kst_text(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("inspection scope time")
    return value.astimezone(timezone(timedelta(hours=9))).isoformat(timespec="microseconds")


def _scope_matches(row, job, pid):
    expected = dict(job, possibility_id=pid, snapshot_at=_kst_text(job["snapshot_at"]),
                    requested_at=job.get("requested_at"), actor=job.get("actor"))
    return all(_dump(row[k]) == _dump(expected[k]) for k in _SCOPE_FIELDS if k != "catalog_at")


def last_attempt(row, job, pid, now):
    """Ordering hint only. A stale completed job remains stale and needs fresh GETs."""
    try:
        if row is not None and _scope_matches(row, job, pid):
            checked = _time(row["checked_at"])
            if _time(job["generation"]) <= checked <= now and row["checked_at"] == _kst_text(checked):
                return row["checked_at"]
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return ""


def context(proof, row, now, catalog, error_codes):
    """Closed begin/checkpoint/completion context, including current row state."""
    try:
        if row is None or catalog is None:
            return None
        binding = _binding(row, error_codes)
        if (not _sealed(proof, _CHECKPOINT_FIELDS) or _dump(proof["binding"]) != _dump(binding)
                or proof["role"] not in {"reading", "checkpoint", "complete"}
                or (proof["role"] == "complete") != (row["status"] == "ok")
                or (proof["role"] == "reading") != (row["progress_hash"] is None)
                or proof["role"] == "reading" and row["progress_json"] is not None
                or any(proof[k] != catalog[k] for k in ("content_digest", "content_epoch", "stable_content_at"))
                or not _time(proof["stable_content_at"]) <= _time(row["catalog_at"]) <= _time(catalog["generated_at"])
                or not _time(row["generation"]) <= _time(row["checked_at"]) <= now
                or _time(row["next_try_at"]) < _time(row["checked_at"])):
            return None
        return proof
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return None


def resumable(proof, row, job, pid, now, catalog, error_codes, max_bytes):
    """Does not replace current job authority, retry gates, or progress validation."""
    from . import inspection_reads as R
    try:
        proof = context(proof, row, now, catalog, error_codes)
        if (proof is None or proof["role"] != "checkpoint" or row["status"] not in {"reading", "partial", "retry", "limited"}
                or not _scope_matches(row, job, pid) or not last_attempt(row, job, pid, now)):
            return False
        raw = row["progress_json"]
        if (not isinstance(raw, str) or len(raw.encode()) > max_bytes
                or hashlib.sha256(raw.encode()).hexdigest() != row["progress_hash"]):
            return False
        progress = R.validate_progress(json.loads(raw), job)
        times = [record["checked_at"] for record in progress["entities"].values()]
        times += [record["checked_at"] for group in progress["targets"].values() for record in group.values()]
        times += [record["checked_at"] for record in progress["performance"].values()]
        return not progress["confirmed"] and not any(datetime.fromisoformat(at) > now for at in times)
    except (R.CheckpointInvalid, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return False


def checkpoint_proof(row, progress, catalog, error_codes):
    """Return one bounded key/value: begin, validated progress, or completion."""
    key = checkpoint_key(row["job_key"])
    try:
        if catalog is None or row["catalog_at"] != catalog["generated_at"]:
            raise ValueError("inspection checkpoint unproved")
        role = "complete" if row["status"] == "ok" else "reading" if progress is None else "checkpoint"
        if role == "complete" and (progress is None or not progress["confirmed"] or progress["next_index"] != len(progress["queue"])):
            raise ValueError("inspection completion unproved")
        proof = _seal(dict(version=1, role=role, binding=_binding(row, error_codes), **{k: catalog[k] for k in
            ("content_digest", "content_epoch", "stable_content_at")}))
        if ((role == "reading") != (row["progress_hash"] is None)
                or role == "reading" and row["progress_json"] is not None):
            raise ValueError("inspection context role")
        raw = _dump(proof)
        if len(raw.encode()) > 4096:
            raise ValueError("inspection context size")
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("inspection context proof invalid") from None
    return key, raw


# A continuation bridge is not a current-source or completion proof. Only the
# accepted-catalog writer may advance it; every intervening catalog is checked.
_CONTINUITY_FIELDS = {"version", "checkpoint_hash", "catalog_hash", "scope_hash", "proof_hash"}


def continuity_key(job_key):
    return "inspection-continuity:v1:"+hashlib.sha256(job_key.encode()).hexdigest()


def continuity_proof(checkpoint, catalog, scope_hash):
    if not _sealed(checkpoint, _CHECKPOINT_FIELDS) or checkpoint["role"] not in {"reading", "checkpoint"} or not _hex(scope_hash):
        raise ValueError("inspection continuity anchor")
    return _seal(dict(version=1, checkpoint_hash=_hash(checkpoint), catalog_hash=_hash(catalog), scope_hash=scope_hash))


def continuity_matches(bridge, checkpoint, catalog, scope_hash):
    try:
        return (_sealed(bridge, _CONTINUITY_FIELDS) and _sealed(checkpoint, _CHECKPOINT_FIELDS)
                and checkpoint["role"] in {"reading", "checkpoint"} and _hex(scope_hash)
                and bridge["checkpoint_hash"] == _hash(checkpoint)
                and bridge["catalog_hash"] == _hash(catalog) and bridge["scope_hash"] == scope_hash)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return False


def resumable_continuity(bridge, checkpoint, row, job, pid, now, catalog, scope_hash, error_codes, max_bytes):
    if not continuity_matches(bridge, checkpoint, catalog, scope_hash) or checkpoint["role"] != "checkpoint":
        return False
    # Recheck the sealed original checkpoint and every original progress/scope
    # condition against its own anchor. This view is never returned as current
    # source evidence. begin must still validate the actual current job first.
    anchor = dict(catalog, generated_at=row["catalog_at"], **{key: checkpoint[key] for key in
        ("content_digest", "content_epoch", "stable_content_at")})
    return resumable(checkpoint, row, job, pid, now, anchor, error_codes, max_bytes)


ORG_CONTINUITY_KEY = "inspection-org-continuity:v1"
_ORG_CONTINUITY_FIELDS = {"version", "body_hash", "epoch", "proof_hash"}


def org_continuity_epoch(proof, body):
    """Current accepted body must match the entire writer-sealed snapshot."""
    try:
        if (_sealed(proof, _ORG_CONTINUITY_FIELDS) and _hex(proof["epoch"], 32)
                and proof["body_hash"] == _hash(body)):
            return proof["epoch"]
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        pass
    return None


def new_org_continuity(proof, old, body):
    """Timestamp-only accepted updates preserve an unbroken semantic epoch."""
    epoch = org_continuity_epoch(proof, old) if old is not None else None
    if (epoch is None or _dump({k: v for k, v in old.items() if k != "generated_at"})
            != _dump({k: v for k, v in body.items() if k != "generated_at"})):
        epoch = uuid.uuid4().hex
    return _dump(_seal(dict(version=1, body_hash=_hash(body), epoch=epoch)))
