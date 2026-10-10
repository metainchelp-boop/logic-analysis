"""Retrieve anonymous experience only from the caller's current authorized accounts.

This module does not grant access. The caller supplies freshly resolved pairs.
Names, comments, source IDs and author data never enter the model context.
"""
from copy import deepcopy
import hashlib

from . import learning_assets as L, store as S

MAX_ALLOWED_PAIRS = 2000
MAX_CANDIDATES = 1000
BATCH_SIZE = 50
MATCH_FIELDS = ("industry", "goal", "ad_type")


def _pairs(allowed_pairs, target_pid, target_key):
    if not isinstance(allowed_pairs, (list, tuple, set, frozenset)) or len(allowed_pairs) > MAX_ALLOWED_PAIRS:
        raise S.StoreRefused("학습 사례의 현재 열람 범위를 확인해 주세요")
    allowed = set()
    for pair in allowed_pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise S.StoreRefused("학습 사례의 현재 열람 범위를 확인해 주세요")
        L._identity(pair[0], pair[1])
        allowed.add((pair[0], pair[1]))
    L._identity(target_pid, target_key)
    if (target_pid, target_key) not in allowed:
        raise S.StoreRefused("학습 사례의 현재 열람 범위를 확인해 주세요")
    return sorted(allowed)


def _safe(record):
    identity, document = record["identity"], record["document"]
    source = {**identity, "asset_id": record["asset_id"], "version": record["version"]}
    # Different advertisers may use the same local asset ID. This opaque ID is
    # only local provenance; STR replaces it with an ordinal before any API call.
    opaque = hashlib.sha256((str(identity["possibility_id"]) + ":" + identity["account_key"] + ":" + record["asset_id"]).encode()).hexdigest()
    case = {"asset_id": opaque, "version": record["version"], "kind": document["kind"],
        "metadata": deepcopy(document["metadata"]), "evidence": deepcopy(document["evidence"]),
        "assessment": deepcopy(record["assessment"])}
    return case, source


def retrieve_scoped(connection, allowed_pairs, target_pid, target_key, metadata=None):
    """Return at most five vetted cases and separate, private source references.

    Cross-account reuse requires explicitly known, equal industry/goal/ad type.
    Budget similarity ranks matches; no unknown field is guessed. Retrieval is
    bounded and reports truncation rather than claiming a complete corpus scan.
    """
    allowed = _pairs(allowed_pairs, target_pid, target_key)
    repository = S.learning_asset_storage(connection)
    target = (target_pid, target_key)
    own_window = L.list_assets(repository, *target, limit=L.MAX_ASSETS)
    own = [item for item in own_window if item["state"] == "reviewed"]
    own.sort(key=lambda item: (item["reviewed_at"], item["asset_id"]), reverse=True)
    wanted = L.metadata_document(metadata) if metadata is not None else (
        deepcopy(own[0]["document"]["metadata"]) if own else {key: None for key in L.METADATA_ENUMS})
    cross_enabled = all(wanted[key] is not None for key in MATCH_FIELDS)
    own_matches = [item for item in own if not any(wanted[key] is not None and
        item["document"]["metadata"][key] is not None and wanted[key] != item["document"]["metadata"][key] for key in wanted)]
    cross, scanned, truncated, scanned_accounts = [], 0, len(own_window) == L.MAX_ASSETS, 1
    others = [pair for pair in allowed if pair != target]
    if cross_enabled:
        for offset in range(0, len(others), BATCH_SIZE):
            batch = others[offset:offset+BATCH_SIZE]
            remaining = MAX_CANDIDATES - scanned
            records = repository.reviewed_candidates(batch, limit=remaining+1)
            scanned_accounts += len(batch)
            if len(records) > remaining:
                truncated = True
                records = records[:remaining]
            for item in records:
                scanned += 1
                if item["state"] != "reviewed":
                    continue
                known = item["document"]["metadata"]
                if all(known[key] == wanted[key] for key in MATCH_FIELDS):
                    cross.append(item)
            if scanned >= MAX_CANDIDATES:
                truncated = truncated or offset + len(batch) < len(others)
                break
    def rank(item):
        known = item["document"]["metadata"]
        return (sum(wanted[key] is not None and known[key] == wanted[key] for key in wanted),
                item["reviewed_at"], item["asset_id"], item["identity"]["possibility_id"])
    own_matches.sort(key=rank, reverse=True)
    cross.sort(key=rank, reverse=True)
    # Reserve space for both current-account experience and authorized agency
    # experience, including invalid/stopped/inconclusive reviewed lessons.
    chosen = own_matches[:3] + cross[:2]
    chosen += (own_matches[3:] + cross[2:])[:5-len(chosen)]
    cases, refs = [], []
    for item in chosen:
        case, ref = _safe(item)
        cases.append(case)
        refs.append(ref)
    return {"context": {"version": 1, "cases": cases}, "refs": refs,
        "coverage": {"scope": "authorized", "allowed_accounts": len(allowed), "scanned_accounts": scanned_accounts,
            "candidates": len(own) + scanned, "matched": len(own_matches) + len(cross), "selected": len(chosen),
            "cross_enabled": cross_enabled, "cross_selected": sum((ref["possibility_id"], ref["account_key"]) != target for ref in refs),
            "candidate_limit": MAX_CANDIDATES, "truncated": truncated}}
