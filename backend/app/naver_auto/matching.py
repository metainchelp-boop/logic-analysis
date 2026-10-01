"""짝 규칙 — ① 전산 광고주(가망) ↔ 네이버 광고계정 (설계 v1.8 S3 · 반박 H4 · Q5 · J3 · L12).

순수 함수 — 네트워크·저장·시계를 모른다. 엔진(S7·S8)이 ① 에서 읽은 가망·자격 행과,
읽기 관문이 **전부 받았을 때만** 만드는 대행 연결 목록(``ChildAccounts.accounts``)을 넣는다.

짝은 세 가지뿐이다.
- **확인한 짝**(``confirmed``) — 사람이 「이 계정 맞음」을 눌렀다. 가장 우선한다.
- **자동 짝**(``auto``) — ①의 명시적 광고 계정 ID를 대행 목록에서 고객 번호로 찾거나 기존 고객 번호와 대조한다.
  바로 점검하되 「계정 확인 전」 · 늘 「확인 필요 예」(판정 verdict 가 한다 · 반박 H4).
- **이름 후보**(``Candidate``) — 이름이 비슷할 뿐. **사람이 확인할 때까지 그 계정에 들어가지 않는다**(J3).
  확인 화면의 미리보기도 사람이 그 줄을 누를 때만 읽는다(Q2).

자동 짝이 되려면 다음을 **모두** 통과해야 한다(하나라도 어긋나면 ``Blocked`` · 사람 몫).
1. ① 매체의 연동 종류가 ``NAVER_SEARCHAD`` 인 행만(매체 이름은 대표가 자유롭게 적어 믿지 않는다).
2. 번호는 **숫자만** — 띄어쓰기·하이픈만 허용하고 지운다 · 4~8자리 · 0 으로 시작하지 않음.
   (실측 2026-09-28: 고객 번호 1,784곳 모두 4~7자리 · 0 으로 시작 0 · 광고계정 번호도 4~7자리라
   **자릿수로는 두 번호를 가를 수 없다** → 아래 3 이 막는다.)
3. 기존 고객 번호 칸은 **고객 번호 한 공간과만** 맞는다 — 광고계정 번호(``adAccountNo``)와만 맞으면 「광고계정 번호를 적은 듯」,
   두 공간 모두에 있으면(서로 다른 계정) 「어느 번호인지 모름」.
   별도 광고 계정 ID 칸은 번호 종류가 명시되어 그 공간에서만 찾는다. 같은 행의 두 번호가 다르면 보류한다.
4. 같은 번호를 ① 의 다른 가망도 적었으면 모두 멈춘다(사람이 가른다 — 스토어·플레이스 두 가망이 한 업체일 수도 있다).
5. 그 계정을 사람이 다른 가망의 짝으로 이미 확인했으면 멈춘다 · 사람이 「아님」이라 한 조합은 다시 올리지 않는다.
6. **이름이 어긋나지 않는다** — ① 상호와 네이버 계정 이름을 ① 과 같은 규칙(``looseName``)으로 정리해
   「같음 · 한쪽이 다른 쪽을 품음 · 모름(너무 짧음)」이면 통과. 「다름」이면 멈춘다.
   계정 이름이 **다른 가망의 상호와 같으면**(이 가망과는 같지 않고) 멈춘다.

이름 정리는 ① ``ProspectMatchKeys.normalizeName`` · ``looseName`` 과 같은 규칙이다 — ① 자바 코드를 그대로 돌린 정답표
(``tests/fixtures/prospect_match_keys_vectors.json`` · 68개)와 한 글자까지 같은지 시험이 고정한다(서버와 같은 파이썬 3.12 ·
자바 21 — 둘 다 유니코드 15). 길이는 자바처럼 UTF-16 단위로 센다(한자 확장 글자 하나 = 2).
⚠️ **알려진 차이** — 그리스 대문자 시그마(Σ)가 숫자 뒤 끝에 올 때 자바는 ς · 파이썬은 σ(「끝 글자」 판정 방식이 다름 ·
시험 ``test_known_difference_final_sigma`` 가 고정). 짝 규칙은 양쪽 이름을 같은 파이썬 함수로 정리해 비교하므로 짝 결과에는
영향이 없다 — ① 의 정리 키를 그대로 받아 비교하는 일이 생기면 이 차이를 먼저 막는다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .verdict import LINK_AUTO, LINK_CONFIRMED

VENDOR_NAVER = "NAVER_SEARCHAD"          # ① ad_platform.integration_vendor 값(BLOCK 205)
DIGITS_MIN, DIGITS_MAX = 4, 8            # 실측 4~7자리 + 한 자리 여유
AUTO_CONTAIN_MIN = 2                     # 자동 짝: 번호가 이미 맞았으니 「품음」은 2글자부터
CANDIDATE_CONTAIN_MIN = 3                # 이름 후보: 번호 근거가 없으니 3글자부터
CANDIDATE_MAX = 5                        # 가망 하나에 보여 줄 이름 후보 최대 수

REL_SAME, REL_CONTAINS, REL_DIFFERENT, REL_UNKNOWN = "same", "contains", "different", "unknown"

# 막힌 까닭(화면 S11 이 한국어 문구로 바꾼다 — 여기서는 코드만)
B_FORMAT = "customer-id-format"          # 숫자·띄어쓰기·하이픈 말고 다른 글자
B_LENGTH = "customer-id-length"          # 자릿수 밖 · 0 으로 시작
B_NOT_LINKED = "not-linked"              # 대행 연결 목록에 없음(광고주가 대행 연결을 안 했다)
B_AD_ACCOUNT_NO = "ad-account-number"    # 고객 번호가 아니라 광고계정 번호와만 맞음
B_AMBIGUOUS_SPACE = "ambiguous-space"    # 한 계정의 고객 번호이자 다른 계정의 광고계정 번호
B_CLAIMED_BY_SEVERAL = "claimed-by-several"  # ① 의 여러 가망이 같은 번호를 적음
B_CONFIRMED_ELSEWHERE = "confirmed-elsewhere"  # 사람이 그 계정을 다른 가망의 짝으로 확인함
B_REJECTED = "rejected-by-human"         # 사람이 이 조합은 아니라고 함
B_NAME_DIFFERENT = "name-different"      # 번호는 맞는데 이름이 다름
B_NAME_ELSEWHERE = "name-points-elsewhere"  # 계정 이름이 다른 가망의 상호와 같음
B_AD_FORMAT = "ad-account-id-format"      # 명시한 광고 계정 ID가 양의 ASCII 정수가 아님
B_AD_NOT_LINKED = "ad-account-not-linked"  # 명시한 광고 계정 ID가 대행 연결 목록에 없음
B_IDENTIFIER_CONFLICT = "account-identifiers-conflict"  # 같은 행의 두 번호가 서로 다른 계정

DECISION_CONFIRMED, DECISION_REJECTED = "confirmed", "rejected"

_LEGAL = re.compile(r"\(주\)|\(유\)|주식회사|유한회사|유한책임회사")   # ① looseName 과 같은 목록·같은 순서
_EDGE = " \t\r\n\u00a0\u3000"
_SEP = frozenset(" \u00a0\u3000-\u2010\u2011\u2012\u2013\u2014\u2212\uff0d")
_ASCII_DIGITS = frozenset("0123456789")


class IncompleteAccounts(ValueError):
    """대행 연결 목록을 전부 받았다는 표시 없이 짝을 맞추려 함(반박 H1 — 일부만 받은 목록으로 짝을 지우면 안 된다)."""


class BadInput(ValueError):
    """입력 모양이 틀림. 문구에 번호·이름을 싣지 않는다."""


# ── 이름 정리 — ① ProspectMatchKeys 와 같은 규칙 ─────────────────────────────

def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _letters_digits_lower(s: str) -> str:
    # 자바 [^\p{L}\p{N}] 제거 = 유니코드 분류가 L*·N* 인 글자만 남김 → toLowerCase(Locale.ROOT)
    return "".join(ch for ch in s if unicodedata.category(ch)[0] in "LN").lower()


def normalize_name(raw) -> Optional[str]:
    """① ``ProspectMatchKeys.normalizeName`` — NFC · 글자·숫자만 · 소문자 · 2 미만이면 None."""
    if not isinstance(raw, str):
        return None
    key = _letters_digits_lower(unicodedata.normalize("NFC", raw))
    return key if _utf16_len(key) >= 2 else None


def loose_name(raw) -> Optional[str]:
    """① ``ProspectMatchKeys.looseName`` — NFKC · 법인 표기 제거 · 글자·숫자만 · 소문자 · 2 미만이면 None."""
    if not isinstance(raw, str):
        return None
    s = _LEGAL.sub("", unicodedata.normalize("NFKC", raw))
    key = _letters_digits_lower(s)
    return key if _utf16_len(key) >= 2 else None


def name_relation(a, b, contain_min: int = AUTO_CONTAIN_MIN) -> str:
    """두 이름의 관계 — same · contains · different · unknown(어느 한쪽이 너무 짧거나 없음)."""
    ka, kb = loose_name(a), loose_name(b)
    if ka is None or kb is None:
        return REL_UNKNOWN
    if ka == kb:
        return REL_SAME
    short, long_ = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if len(short) >= contain_min and short in long_:
        return REL_CONTAINS
    return REL_DIFFERENT


# ── 번호 정리 ──────────────────────────────────────────────────────────

def parse_customer_id(raw) -> Tuple[Optional[int], Optional[str]]:
    """① 에 적힌 고객 번호 원문 → (번호, None) 또는 (None, 막힌 까닭 · 빈칸이면 None)."""
    if raw is None or isinstance(raw, bool):
        return None, (None if raw is None else B_FORMAT)
    if isinstance(raw, int):
        s = str(raw)
    elif isinstance(raw, str):
        s = raw
    else:
        return None, B_FORMAT
    s = s.strip(_EDGE)
    if not s:
        return None, None
    digits = []
    for ch in s:
        if ch in _ASCII_DIGITS:
            digits.append(ch)
        elif ch in _SEP:
            continue
        else:
            return None, B_FORMAT
    if not digits:
        return None, B_FORMAT
    d = "".join(digits)
    if d[0] == "0" or not (DIGITS_MIN <= len(d) <= DIGITS_MAX):
        return None, B_LENGTH
    return int(d), None


# ── 입력 · 결과 ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ErpProspect:
    """관리 대상 가망 하나(① 7단계 안 — 엔진 S5 가 거른 것만)."""
    possibility_id: int
    name: Optional[str] = field(default=None, repr=False)


@dataclass(frozen=True)
class ErpCredential:
    """① 광고주 관리 「광고 API 연동 정보」 한 행(업체 × 매체)."""
    possibility_id: int
    vendor: Optional[str]
    customer_id_raw: Optional[str] = field(default=None, repr=False)
    ad_account_no_raw: Optional[str] = field(default=None, repr=False, kw_only=True)


@dataclass(frozen=True)
class HumanDecision:
    """짝 확인 화면에서 사람이 내린 판단."""
    possibility_id: int
    customer_id: int = field(repr=False)
    decision: str = DECISION_CONFIRMED


@dataclass(frozen=True)
class Pair:
    """점검해도 되는 짝(확인한 짝 · 자동 짝)."""
    possibility_id: int
    customer_id: int = field(repr=False)
    link: str = LINK_AUTO
    name_relation: str = REL_UNKNOWN


@dataclass(frozen=True)
class Blocked:
    """① 에 번호가 적혀 있는데 자동 짝이 되지 못함 — 짝 확인 화면에 까닭과 함께 올린다."""
    possibility_id: int
    reason: str
    customer_id: Optional[int] = field(default=None, repr=False)


@dataclass(frozen=True)
class Candidate:
    """이름만 비슷한 계정 — 사람이 확인할 때까지 들어가지 않는다."""
    possibility_id: int
    customer_id: int = field(repr=False)
    relation: str = REL_SAME
    same_name_accounts: int = 1          # 같은 정리 이름을 가진 계정 수(2 이상 = 여럿 중 하나)
    claimed_elsewhere: bool = False      # 다른 가망이 ① 에 이 번호를 적었거나 사람이 다른 가망 짝으로 확인함(관리 대상 밖 포함)


@dataclass(frozen=True)
class PairingResult:
    pairs: Tuple[Pair, ...]
    blocked: Tuple[Blocked, ...]
    candidates: Tuple[Candidate, ...]
    confirmed_missing: Tuple[Tuple[int, int], ...]   # 확인한 짝인데 오늘 연결 목록에 없음(무효화 2일 규칙은 S8)
    ignored_rows: int                                # 관리 대상 밖 가망의 행 · 네이버가 아닌 행 · 번호 빈칸

    def __repr__(self) -> str:   # 번호·이름이 로그에 새지 않게 — 개수만
        return (f"PairingResult(pairs={len(self.pairs)}, blocked={len(self.blocked)}, "
                f"candidates={len(self.candidates)}, confirmed_missing={len(self.confirmed_missing)}, "
                f"ignored={self.ignored_rows})")

    def checkable(self) -> Dict[int, Tuple[Tuple[int, str], ...]]:
        """가망 번호 → ((고객 번호, 짝 종류), …) — 점검 손잡이를 발급해도 되는 것만."""
        out: Dict[int, List[Tuple[int, str]]] = {}
        for p in self.pairs:
            out.setdefault(p.possibility_id, []).append((p.customer_id, p.link))
        return {k: tuple(v) for k, v in out.items()}


def _pid(v) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise BadInput("가망 번호는 양의 정수")
    return v


def _cid(v) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise BadInput("고객 번호는 양의 정수")
    return v


def _cid_like(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise BadInput(f"{what}는 양의 정수")
    return v


# ── 짝 맞추기 ──────────────────────────────────────────────────────────

def match(prospects: Sequence[ErpProspect], credentials: Iterable[ErpCredential],
          accounts: Mapping[int, Mapping], decisions: Iterable[HumanDecision] = (),
          *, accounts_complete: bool, previous_ad_accounts: Optional[Mapping[int, int]] = None) -> PairingResult:
    """한 번에 전부 맞춘다. ``accounts`` = 읽기 관문의 ``ChildAccounts.accounts``(고객 번호 → 남길 칸).

    ``accounts_complete=True`` 는 관문이 **모든 관리계정의 모든 쪽을 받았을 때만** 넘긴다(반박 H1).
    ``previous_ad_accounts`` 는 현재 목록에서 빠진 계정의 옛 대응이며 이관 빠짐 표시에만 쓴다.
    """
    if accounts_complete is not True:
        raise IncompleteAccounts("대행 연결 목록을 전부 받았을 때만 짝을 맞춘다")

    # 가망
    names: Dict[int, Optional[str]] = {}
    for p in prospects:
        if not isinstance(p, ErpProspect):
            raise BadInput("가망 모양이 아님")
        pid = _pid(p.possibility_id)
        if pid in names:
            raise BadInput("같은 가망 번호가 두 번")
        if p.name is not None and not isinstance(p.name, str):
            raise BadInput("상호 모양이 아님")   # 모름으로 바꾸면 이름 검사가 조용히 풀린다(실패는 닫힌 쪽으로)
        names[pid] = p.name
    loose_of_prospect = {pid: loose_name(n) for pid, n in names.items()}
    prospects_by_loose: Dict[str, set] = {}
    for pid, k in loose_of_prospect.items():
        if k is not None:
            prospects_by_loose.setdefault(k, set()).add(pid)

    # 네이버 계정
    acc_name: Dict[int, Optional[str]] = {}
    ad_no_owner: Dict[int, int] = {}
    for cid, row in accounts.items():
        cid = _cid(cid)
        if not isinstance(row, Mapping):
            raise BadInput("계정 칸 모양이 아님")
        rc = row.get("customerId", cid)
        if rc != cid:
            raise BadInput("계정 열쇠와 칸의 고객 번호가 다름")
        # 광고계정 번호가 비면 「고객 번호 한 공간과만」 검사가 조용히 약해진다 — 실측 1,784곳 모두 있음 · 없으면 회차 실패
        no = _cid_like(row.get("adAccountNo"), "광고계정 번호")
        # 이름 칸이 빠지거나(네이버가 칸 이름을 바꿈) 글자가 아니면 이름 검사가 통째로 풀린다 — 모름으로 바꾸지 않고 실패
        if "adAccountName" not in row:
            raise BadInput("계정 이름 칸 없음")
        nm = row["adAccountName"]
        if nm is not None and not isinstance(nm, str):
            raise BadInput("계정 이름 모양이 아님")
        acc_name[cid] = nm
        if no in ad_no_owner and ad_no_owner[no] != cid:
            raise BadInput("광고계정 번호가 두 계정에 겹침")
        ad_no_owner[no] = cid
    cids = set(acc_name)

    # 사람의 판단
    confirmed: Dict[int, set] = {}          # 가망 → 확인한 고객 번호들
    confirmed_owner: Dict[int, set] = {}    # 고객 번호 → 확인한 가망들
    rejected = set()
    for d in decisions:
        if not isinstance(d, HumanDecision):
            raise BadInput("판단 모양이 아님")
        pid, cid = _pid(d.possibility_id), _cid(d.customer_id)
        if d.decision == DECISION_CONFIRMED:
            confirmed.setdefault(pid, set()).add(cid)
            confirmed_owner.setdefault(cid, set()).add(pid)
        elif d.decision == DECISION_REJECTED:
            rejected.add((pid, cid))
        else:
            raise BadInput("모르는 판단")
    if any((pid, cid) in rejected for pid, cs in confirmed.items() for cid in cs):
        raise BadInput("같은 짝을 확인과 아님으로 동시에")
    # 한 계정을 여러 가망의 짝으로 확인한 채로 들어오면 두 가망이 같은 계정을 점검한다 — 저장소가 가장 늦은 확인 하나만
    # 살려 넘긴다(엔진 S8). 여기까지 여럿이 오면 앞 단계가 고장 난 것이니 짝을 맞추지 않는다(실패는 닫힌 쪽으로).
    if any(len(ps) > 1 for ps in confirmed_owner.values()):
        raise BadInput("한 계정을 여러 가망의 짝으로 확인")

    pairs: List[Pair] = []
    blocked: List[Blocked] = []
    missing: List[Tuple[int, int]] = []
    paired: Dict[int, set] = {}              # 가망 → 짝 고객 번호
    paired_cids = set()

    # 1) 확인한 짝 — 관리 대상 가망만(끝난 지 14일 넘은 가망은 S5 가 넣지 않는다 · 들어가지 않는다)
    for pid in sorted(confirmed):
        if pid not in names:
            continue
        for cid in sorted(confirmed[pid]):
            if cid in cids:
                pairs.append(Pair(pid, cid, LINK_CONFIRMED, name_relation(names[pid], acc_name[cid])))
                paired.setdefault(pid, set()).add(cid)
                paired_cids.add(cid)
            else:
                missing.append((pid, cid))

    # 2) ① 에 적힌 고객 번호 — 자동 짝 후보 모으기
    ignored = 0
    claims: List[Tuple[int, int, bool]] = [] # (가망, 고객 번호, 명시적 광고 계정 번호에서 찾음)
    seen = set()
    all_claims = set()                       # 관리 대상 밖·보류 행의 주장도 지우지 않는다
    held_claims = set()
    for c in credentials:
        if not isinstance(c, ErpCredential):
            raise BadInput("자격 행 모양이 아님")
        pid = _pid(c.possibility_id)
        if c.vendor != VENDOR_NAVER:
            ignored += 1
            continue
        explicit = c.ad_account_no_raw is not None and c.ad_account_no_raw != ""
        cid, why = parse_customer_id(c.customer_id_raw)
        if cid is not None:
            # 구 입력칸에서 번호 종류가 모호하면 양쪽 계정을 모두 보호한다.
            if cid in cids:
                all_claims.add((pid, cid))
            if not explicit and cid in ad_no_owner:
                all_claims.add((pid, ad_no_owner[cid]))
        if explicit:
            raw = c.ad_account_no_raw
            ad_no = int(raw) if isinstance(raw, str) and re.fullmatch(r"[1-9][0-9]{0,14}", raw) else None
            target = ad_no_owner.get(ad_no)
            if target is not None:
                all_claims.add((pid, target))
            if ad_no is None:
                why = B_AD_FORMAT
            elif target is None:
                why = B_AD_NOT_LINKED
            elif why is not None or (cid is not None and cid != target):
                why = B_IDENTIFIER_CONFLICT
            if why is not None:
                held_claims.update((pid, v) for v in (cid, target) if v in cids)
                previous = None
                if why == B_AD_NOT_LINKED and previous_ad_accounts is not None:
                    previous = previous_ad_accounts.get(ad_no)
                if previous is not None:
                    previous = _cid(previous)
                    if previous in cids:
                        previous = None  # 현재 다른 번호로 존재하는 계정은 이탈로 오인하지 않는다
                    elif cid is not None and cid != previous:
                        why, previous = B_IDENTIFIER_CONFLICT, None
                    else:
                        why = B_REJECTED if (pid, previous) in rejected else B_NOT_LINKED
                if pid in names:
                    blocked.append(Blocked(pid, why, previous))
                else:
                    ignored += 1
                continue
            cid = target
        if pid not in names:
            ignored += 1                     # 관리 대상 밖 — 짝은 안 만들지만 충돌 판정에는 센다
            continue
        if cid is None:
            if why is None:
                ignored += 1
            else:
                blocked.append(Blocked(pid, why))
            continue
        if (pid, cid, explicit) not in seen:
            seen.add((pid, cid, explicit))
            claims.append((pid, cid, explicit))
    # 적힌 번호가 어느 계정을 가리키나 — 고객 번호면 그 계정, 광고계정 번호면 그 번호의 주인 계정.
    # 두 가망이 같은 계정을 서로 다른 번호 공간으로 적어도 한 계정을 두고 다투는 것으로 본다.
    claimers: Dict[int, set] = {}
    for pid, cid in all_claims:
        claimers.setdefault(cid, set()).add(pid)

    for pid, cid, explicit in claims:
        if cid in paired.get(pid, ()):
            continue                          # 이미 사람이 확인한 짝
        if (pid, cid) in held_claims:
            continue                          # 같은 행의 상충 값을 다른 중복 행으로 우회하지 않는다
        if (pid, cid) in rejected:
            blocked.append(Blocked(pid, B_REJECTED, cid))
            continue
        in_cid, in_no = cid in cids, cid in ad_no_owner
        if not in_cid:
            blocked.append(Blocked(pid, B_AD_ACCOUNT_NO if in_no else B_NOT_LINKED, cid))
            continue
        if not explicit and in_no and ad_no_owner[cid] != cid:
            blocked.append(Blocked(pid, B_AMBIGUOUS_SPACE, cid))
            continue
        if len(claimers.get(cid, ())) > 1:
            blocked.append(Blocked(pid, B_CLAIMED_BY_SEVERAL, cid))
            continue
        if confirmed_owner.get(cid, set()) - {pid}:
            blocked.append(Blocked(pid, B_CONFIRMED_ELSEWHERE, cid))
            continue
        rel = name_relation(names[pid], acc_name[cid], AUTO_CONTAIN_MIN)
        if rel == REL_DIFFERENT:
            blocked.append(Blocked(pid, B_NAME_DIFFERENT, cid))
            continue
        ak = loose_name(acc_name[cid])
        if rel != REL_SAME and ak is not None and prospects_by_loose.get(ak, set()) - {pid}:
            blocked.append(Blocked(pid, B_NAME_ELSEWHERE, cid))
            continue
        pairs.append(Pair(pid, cid, LINK_AUTO, rel))
        paired.setdefault(pid, set()).add(cid)
        paired_cids.add(cid)

    # 3) 이름 후보 — 짝이 하나도 없는 관리 대상 가망만(L12) · 이미 짝이 된 계정은 빼고 · 사람이 아니라 한 조합은 빼고
    acc_loose = {cid: loose_name(n) for cid, n in acc_name.items()}
    by_loose: Dict[str, List[int]] = {}
    for cid, k in acc_loose.items():
        if k is not None:
            by_loose.setdefault(k, []).append(cid)
    free = sorted(cid for cid in cids if cid not in paired_cids and acc_loose[cid] is not None)
    candidates: List[Candidate] = []
    for pid in sorted(names):
        if paired.get(pid):
            continue
        pk = loose_of_prospect[pid]
        if pk is None:
            continue
        found: List[Candidate] = []
        for cid in free:
            if (pid, cid) in rejected:
                continue
            ak = acc_loose[cid]
            if ak == pk:
                rel = REL_SAME
            else:
                short, long_ = (pk, ak) if len(pk) <= len(ak) else (ak, pk)
                if len(short) >= CANDIDATE_CONTAIN_MIN and short in long_:
                    rel = REL_CONTAINS
                else:
                    continue
            elsewhere = bool((confirmed_owner.get(cid, set()) | claimers.get(cid, set())) - {pid})
            found.append(Candidate(pid, cid, rel, len(by_loose[ak]), elsewhere))
        found.sort(key=lambda x: (x.relation != REL_SAME, x.customer_id))
        candidates.extend(found[:CANDIDATE_MAX])

    return PairingResult(tuple(pairs), tuple(blocked), tuple(candidates), tuple(missing), ignored)
