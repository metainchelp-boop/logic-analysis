"""저장된 이관·전산·매칭 자료를 실관리 수집 정책으로 변환한다. 쓰기는 하지 않는다."""
from types import SimpleNamespace
from threading import Lock
import sys

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
        result = _matched(store, accounts, store.current_decisions(), catalog, I.automatic_evidence(store))
        pairs = {pair.customer_id: pair for pair in result.pairs}
    rows = {}
    for cid, account in accounts.items():
        pair = pairs.get(cid)
        company = companies.get(pair.possibility_id) if pair else None
        stage = company["stage"] if company and company["stage_known"] and not company["stage_hidden"] else None
        stage_key = "".join(stage.split()) if stage else None
        # 현재 이관 계정은 회사 귀속이 보류되어도 주간 원천 수집을 한다.
        # 숨김/미확인 업체의 번호 매칭을 직원 접근이나 ERP 귀속으로 승격하지 않는다.
        # 기존 연결 결정은 조회만 하며 이 분류 전환으로 지우지 않는다.
        pid = company["possibility_id"] if company and stage_key else None
        previous = states.get(cid, {})
        same_stage = previous.get("possibility_id") == pid and previous.get("stage_key") == stage_key
        revision = previous.get("stage_revision") if same_stage else None
        revision = revision or (f"pending:{pid}:{stage_key}" if pid is not None else None)
        excluded = previous.get("excluded_revision") if same_stage else None
        included = previous.get("included_revision") if same_stage else None
        decision = P.classify(stage=stage, stage_revision=revision, matched=pid is not None,
                              authority_valid=account["present"] == 1, source_current=current,
                              excluded_revision=excluded, included_revision=included)
        rows[cid] = {"decision": decision, "possibility_id": pid, "stage": stage, "stage_key": stage_key,
                     "stage_revision": revision, "excluded_revision": excluded, "matched": pid is not None,
                     "included_revision": included,
                     "_auto_identity": ((pair.possibility_id, pair.auto_identity_fingerprint)
                                        if pair and pair.auto_identity_fingerprint else None),
                     "snapshot_at": snapshot_at, "source_current": current, "catalog_status": catalog_state}
    return rows


# ── 짝 맞추기 기억 (NV-S00 · 쓰기 줄 막힘 해소 2차) ──
# 관리 판정(snapshot)은 수집 후보(performance_work · structure_work)와 보고서 여는 조각이 회차마다 부르고, 동기화
# (synchronize_management)는 한 번에 두 번 부른다. 그때마다 전산 업체 목록(약 3.7만 줄) × 계정 이름 짝 맞추기를 처음부터 다시
# 해서 쓰기 줄 항목 CPU 의 6할이 여기였다(0.5코어 · 화면 부하에서 한 항목이 15초를 넘겨 로그인 감사가 「저장 바쁨」).
# 짝 맞추기는 넘겨받은 값만 보는 계산이다(시각·임의값·저장소 쓰기 없음 — 결과는 바꿀 수 없는 튜플). 그래서 **그 계산이 실제로
# 읽는 칸만** 같은 차례로 뽑아 글(repr — 1·1.0·참이 서로 다른 글)로 만든 열쇠가 지난번과 글자까지 같을 때만 지난 결과를 다시 쓴다.
#   · 열쇠 = 계정(현재 계정만 · 광고 계정 번호 · 이름) · 사람 판단(가망 · 계정 · 판단) · 번호 행 4칸 · 업체 2칸 · 자동 근거.
#     하나라도 다르면(목록 갱신 · 판단 · 동기화가 방금 쓴 근거 · 계정 동기화) 다시 계산한다 — 무효화 시점을 따로 두지 않는다.
#   · 완료한 순수 결과 한 개만 이 프로세스의 읽기/쓰기 저장소가 공유한다. 새 요청도 원천·권한·업무 단계는 다시 판정한다.
#     열쇠 조회/게시만 잠그고 계산은 잠금 밖에서 한다. 다른 입력의 계산이 늦게 끝나도 다음 호출은 열쇠를 다시 견준다.
#   · 계산 함수가 바뀌었으면(시험이 바꿔 끼움) 지난 결과를 쓰지 않는다. 열쇠를 못 만들면 기억 없이 원래대로 계산한다
#     (오류도 원래 자리·원래 종류로 난다). 계산이 오류로 끝나면 기억하지 않는다.
# 열쇠 만들기는 약 0.02초(짝 맞추기의 1/15 · 3.7만 줄 기준) — 결과는 원래 계산과 같은 객체 모양 · 같은 값이다.
# 저장소·거래·요청 객체는 기억하지 않는다. 열쇠 원문은 로그나 파일로 내보내지 않는다.

_MATCH_MEMO_LOCK = Lock()
_MATCH_MEMO = None

# 부재 포함 매칭은 현재 계정 매칭과 입력/자동 근거가 다르므로 별도 결과 하나만 보관한다.
# 문자열 자체의 실제 Python 크기만 제한한다. 결과를 포함한 전체 heap 상한을 뜻하지 않는다.
_ABSENT_MATCH_KEY_BYTES = 4 * 1024 * 1024
_ABSENT_MATCH_MEMO = None


def _matched(store, accounts, decisions, catalog, evidence):
    """``I._matching(…)[0]`` 과 같은 결과. 같은 입력이 이어지면 지난 계산을 다시 쓴다(위 설명)."""
    return matching_result(store, accounts, decisions, catalog, evidence)[0]


def matching_result(store, accounts, decisions, catalog, evidence, *, candidate_counts=None):
    """현재 계정의 순수 매칭만 공유한다. 권한·단계·원천 신선도 판정은 호출자가 매번 한다."""
    global _MATCH_MEMO
    from . import inventory as I   # snapshot 과 같은 까닭(inventory 가 store 를 참조)으로 부를 때 불러온다
    functions = (I._matching, I.M.match, I.M.loose_name)
    try:
        key = repr(([(cid, a["ad_account_no"], a["account_name"]) for cid, a in accounts.items() if a["present"] == 1],
                    [(d.possibility_id, d.customer_id, d.decision) for d in decisions],
                    [(r["possibility_id"], r["vendor"], r["customer_id_raw"], r["ad_account_no_raw"]) for r in catalog["ids"]],
                    [(r["possibility_id"], r["company_name"]) for r in catalog["items"]],
                    None if evidence is None else list(evidence.items())))
    except Exception:  # noqa: BLE001 — 열쇠를 못 만들면 기억 없이(원래 계산이 같은 입력으로 원래 오류를 낸다)
        key = None
    with _MATCH_MEMO_LOCK:
        memo = _MATCH_MEMO if key is not None else None
    if memo is not None and memo[0] == key and all(a is b for a, b in zip(memo[1], functions)):
        if candidate_counts is not None:
            candidate_counts.update(memo[4])
        return memo[2], set(memo[3])
    counts = {}
    result, possible = I._matching(SimpleNamespace(accounts=accounts, live_decisions=decisions), catalog,
                                   auto_evidence=evidence, candidate_counts=counts)
    if key is not None:
        # 목록이 집합/사전을 바꿔도 다른 요청의 관리 판정·후보 수가 오염되지 않는다.
        completed = (key, functions, result, frozenset(possible), tuple(counts.items()))
        with _MATCH_MEMO_LOCK:
            _MATCH_MEMO = completed
    if candidate_counts is not None:
        candidate_counts.update(counts)
    return result, possible


def absent_matching_result(accounts, decisions, catalog):
    """현재·부재 계정의 순수 매칭만 재사용. 담당·단계·부재 기간은 호출자가 매번 판정한다."""
    global _ABSENT_MATCH_MEMO
    from . import inventory as I
    functions = (I._matching, I.M.match, I.M.loose_name)
    try:
        # include_absent=True도 present 칸을 읽으므로 누락/형 변경을 정상 답으로 덮지 않는다.
        key = repr(([(cid, a["present"], a["ad_account_no"], a["account_name"]) for cid, a in accounts.items()],
                    [(d.possibility_id, d.customer_id, d.decision) for d in decisions],
                    [(r["possibility_id"], r["vendor"], r["customer_id_raw"], r["ad_account_no_raw"])
                     for r in catalog["ids"]],
                    [(r["possibility_id"], r["company_name"]) for r in catalog["items"]]))
        if sys.getsizeof(key) > _ABSENT_MATCH_KEY_BYTES:
            key = None
    except Exception:  # noqa: BLE001 — 오류는 원래 계산의 원래 자리에서 발생해야 한다.
        key = None
    with _MATCH_MEMO_LOCK:
        memo = _ABSENT_MATCH_MEMO if key is not None else None
    if memo is not None and memo[0] == key and all(a is b for a, b in zip(memo[1], functions)):
        return memo[2], set(memo[3])
    # 기존 _lost_rows와 똑같이 auto_evidence 없이 계산한다. 현재 매칭의 근거를 넘기지 않는다.
    result, possible = I._matching(SimpleNamespace(accounts=accounts, live_decisions=decisions), catalog,
                                   include_absent=True)
    if key is not None:
        completed = (key, functions, result, frozenset(possible))
        with _MATCH_MEMO_LOCK:
            _ABSENT_MATCH_MEMO = completed
    return result, possible


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
