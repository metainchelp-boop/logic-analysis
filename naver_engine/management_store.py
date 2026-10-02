"""저장된 이관·전산·매칭 자료를 실관리 수집 정책으로 변환한다. 쓰기는 하지 않는다."""
from types import SimpleNamespace

from app.naver_auto import org_snapshot as O, scope as SC

from . import management as P


def snapshot(store, now, *, stage_states=None) -> dict:
    """계정별 현재 판정. 네이버 호출·상태 갱신 없이 저장소의 공개 조회만 쓴다."""
    # inventory는 store를 참조하므로 저장소가 이 어댑터를 부른 뒤에 불러온다.
    from . import inventory as I

    accounts = {row["customer_id"]: row for row in store.accounts()}
    catalog, catalog_state = I.catalog_status(store, now)
    snapshot_at = store.inventory_snapshot(now)
    org = _organization(store)
    org_current = org is not None and O.allows_raising(O.org_freshness(org.generated_dt, now))
    current = catalog_state == "accepted" and snapshot_at is not None and org_current
    states = store.management_states() if stage_states is None else stage_states
    pairs, companies = {}, {}
    if current:
        companies = {row["possibility_id"]: row for row in catalog["items"]}
        result, _ = I._matching(SimpleNamespace(accounts=accounts, live_decisions=store.current_decisions()), catalog)
        pairs = {pair.customer_id: pair for pair in result.pairs}
    rows = {}
    for cid, account in accounts.items():
        pair = pairs.get(cid)
        company = companies.get(pair.possibility_id) if pair else None
        pid = company["possibility_id"] if company else None
        stage = company["stage"] if company and company["stage_known"] and not company["stage_hidden"] else None
        stage_key = "".join(stage.split()) if stage else None
        previous = states.get(cid, {})
        same_stage = previous.get("possibility_id") == pid and previous.get("stage_key") == stage_key
        revision = previous.get("stage_revision") if same_stage else None
        revision = revision or (f"pending:{pid}:{stage_key}" if pid is not None else None)
        excluded = previous.get("excluded_revision") if same_stage else None
        included = previous.get("included_revision") if same_stage else None
        decision = P.classify(stage=stage, stage_revision=revision, matched=company is not None,
                              authority_valid=account["present"] == 1, source_current=current,
                              excluded_revision=excluded, included_revision=included)
        rows[cid] = {"decision": decision, "possibility_id": pid, "stage": stage, "stage_key": stage_key,
                     "stage_revision": revision, "excluded_revision": excluded, "matched": company is not None,
                     "included_revision": included,
                     "snapshot_at": snapshot_at, "source_current": current, "catalog_status": catalog_state}
    return rows


def require_action(store, now, viewer_idx, customer_id, *, possibility_id=None, allow_unmatched=False) -> dict:
    """본인 담당의 관제 분류/수동 수집만 허용한다. 전산·광고 수정 권한은 아니다."""
    if type(allow_unmatched) is not bool:
        raise ValueError("미매칭 수동 조회 여부는 참/거짓이어야 합니다")
    if type(customer_id) is not int or customer_id <= 0:
        raise SC.ClientNotVisible()
    org = _organization(store)
    if org is None:
        raise SC.ClientNotVisible()
    scope = SC.scope_of(org, viewer_idx)
    row = snapshot(store, now).get(customer_id)
    if row is None:
        raise SC.ClientNotVisible()
    pid = row["possibility_id"]
    if possibility_id is not None and (type(possibility_id) is not int or possibility_id != pid):
        raise SC.ClientNotVisible()
    if pid is None:
        if scope.kind != SC.ALL or not allow_unmatched:
            raise SC.ClientNotVisible()
    else:
        own = SC.ownership_for_client(org, pid, pid, SC.MATCH_PID)
        SC.require_client(org, scope, {pid: own}, pid, SC.ACT_CONFIRM_LINK)
    if row["decision"].cadence == "blocked":
        raise SC.ActionNotAllowed()
    return row


def _organization(store):
    stored = store.org_current()
    if stored is None:
        return None
    try:
        return O.parse_org_snapshot(stored["body"])
    except O.SnapshotFormatError:
        return None
