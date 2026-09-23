"""nvMid — 네이버 쇼핑 상품 고유번호 (2026-09-18 대표 확정)

왜 생겼나
  추적 상품 443개 중 441개가 `product_id` 를 갖고 있는데, 그 값이 최근 14일 수집분의
  상품 ID **279,845개 중 하나도 안 맞았다**(진단 #301 실측). 우연이 아니라 체계가 다르다 —
  우리가 저장한 건 **스마트스토어 채널 상품번호**이고 수집분에 실린 건 **nvMid** 다.

  그래서 순위 매칭 1순위(nvMid 완전일치)는 **항상 빗나가고**, 2순위(채널 ID 가 상품 주소에
  들어 있나)가 혼자 떠받치고 있었다. 실측 — 목표 807건 중 **1순위 0건 · 2순위 462건 ·
  못 찾음 345건(43%)**.

  ⚠️ **43% 가 진짜 문제다.** 못 찾은 것이 「진짜 순위 밖」인지 「번호가 안 맞아 매칭 실패」인지
     지금은 못 가른다. 둘 다 화면·광고주 보고서에 「순위 없음(300위 밖)」으로 나간다.
     nvMid 를 받으면 그 둘이 갈린다 — 이것이 이 칸의 가장 큰 값어치이고, 속도는 그 다음이다.

대표 확정 (2026-09-18)
  ① 기존 443개는 **A안** — 지금 그대로 추적하고, 「자동 찾기」로 하나씩 채운다.
  ② 깊이 **300위**(8페이지). 실측상 찾은 목표 462건 중 301위 밖 **0건** = 잃는 것 0.
  ③ **새 등록은 nvMid 필수** — 없으면 등록이 안 된다(서버가 400 으로 차단).

⚠️ 표준 라이브러리만 쓴다 — 배포 게이트 환경에 fastapi·requests 가 없다
   (collect_cap·split_rule·tracking_eligibility 와 같은 이유).
⚠️ 이 파일은 **네이버에 요청하지 않는다.** 자동 찾기도 우리가 이미 모아 둔 수집분에서만 본다.
"""
import json
import re
import sqlite3

# nvMid 는 네이버가 매기는 숫자다. 자릿수는 상품마다 다르지만 실측상 8~20 자리 안에 든다.
# ⚠️ 상한을 두는 이유 = 사람이 주소를 통째로 붙여넣는 실수를 여기서 잡기 위함이다.
MIN_LEN = 8
MAX_LEN = 20


def normalize(v) -> str:
    """사람이 넣은 값을 숫자만 남긴 문자열로. 주소를 붙여넣었으면 nvMid 파라미터를 뽑는다."""
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    # 주소를 통째로 붙여넣은 경우 — nvMid=... 를 먼저 본다.
    m = re.search(r"[?&]nvMid=(\d+)", s)
    if m:
        return m.group(1)
    # 그 밖에는 숫자만 남긴다(공백·쉼표·따옴표 제거).
    return re.sub(r"\D", "", s)


def is_valid(v) -> bool:
    """등록을 허용할 수 있는 모양인가. 값 자체가 실재하는지는 lookup 이 따로 본다."""
    s = normalize(v)
    return s.isdigit() and MIN_LEN <= len(s) <= MAX_LEN


def channel_id_from_url(url: str) -> str:
    """상품 주소에서 채널 상품번호(스마트스토어 `/products/…`·카탈로그 `/catalog/…`)를 뽑는다.

    ⚠️ 이건 **nvMid 가 아니다.** 자동 찾기가 수집분에서 그 상품을 알아보는 데만 쓴다
       (수집분의 `link` 안에 이 번호가 들어 있다 — 지금 2순위 매칭이 쓰는 그 규칙).
    """
    if not url:
        return ""
    s = str(url)
    m = re.search(r"[?&]nvMid=(\d+)", s)
    if m:
        return m.group(1)
    m = re.search(r"/products/(\d+)", s)
    if m:
        return m.group(1)
    m = re.search(r"/catalog/(\d+)", s)
    if m:
        return m.group(1)
    return ""


def ensure_column(conn) -> None:
    """`tracked_products.nv_mid` 보장(멱등). 이미 있으면 아무 일도 안 한다.

    ⚠️ `tracking_eligibility.ensure_disabled_column` 과 같은 방식이다 —
       DDL 을 따로 돌리지 않고 쓰는 자리에서 한 번 확인한다(배포 순서에 안 묶인다).
    """
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tracked_products)").fetchall()}
        if "nv_mid" not in cols:
            conn.execute("ALTER TABLE tracked_products ADD COLUMN nv_mid TEXT DEFAULT ''")
            conn.commit()
    except Exception:
        pass


def existing_for(conn, product_url: str, user_id) -> str:
    """이 등록 요청이 **고칠 행**(같은 주소·같은 직원)에 이미 저장된 nvMid. 없거나 모양이 틀리면 "".

    신고 #275 (2026-09-23) — 9/18 확정 ③은 「**새로** 등록하는 것만 막는다」였는데, 등록 경로는
    nvMid 없는 요청을 **전부** 막고 있었다. 그래서 이미 등록한 상품에 키워드만 더하는 요청
    (분석 화면 「＋ 이 키워드도 추적 추가」)도 400 이었다 — 9/22 7건 · 9/23 3건, 성공 0건.

    ⚠️ 찾는 기준은 `database.add_tracked_product` 가 **고칠 행을 찾는 기준과 똑같이** 둔다
       (`product_url` 글자 그대로 + `user_id`). 기준이 다르면 A 행의 nvMid 를 들고 B 행을
       새로 만드는 일이 생긴다 — 그건 「새 등록」인데 필수 검사를 건너뛰는 셈이다.
    ⚠️ 저장된 값도 `is_valid` 로 다시 본다 — 비었거나 모양이 틀린 옛 값을 빌려 쓰지 않는다.
    ⚠️ 조회가 실패하면 "" — 그러면 호출처는 **종전대로 거절**한다(여기서는 fail-closed 가 맞다:
       빈 nvMid 로 새 상품이 들어가는 것이 이 규칙이 막으려던 바로 그 일이다).
    """
    url = product_url if isinstance(product_url, str) else ""
    if not url:
        return ""
    try:
        row = conn.execute(
            "SELECT nv_mid FROM tracked_products WHERE product_url = ? AND user_id = ?",
            (url, user_id)).fetchone()
    except Exception:
        return ""
    if not row:
        return ""
    v = normalize(row[0])
    return v if is_valid(v) else ""


# ──────────────────────────────────────────────────────────────────────────
#  자동 찾기 — 이미 모아 둔 수집분에서 nvMid 를 되찾는다 (네이버 요청 0건)
# ──────────────────────────────────────────────────────────────────────────

LOOKUP_DAYS = 14   # 수집 원문 보관정책과 같다(2026-08-30 배포).


def lookup_from_collected(conn, product_url: str, keywords=None, days: int = LOOKUP_DAYS) -> dict:
    """상품 주소로 최근 수집분을 뒤져 nvMid 를 찾는다.

    반환 — {"nv_mid": str, "keyword": str, "rank": int|None, "reason": str}
      nv_mid 가 빈 문자열이면 못 찾은 것이고, **reason 이 왜인지 말한다**:
        - "no-channel-id"   주소에서 상품번호를 못 뽑았다(주소 형식이 다르다)
        - "not-collected"   그 키워드를 우리가 아직 안 모았다
        - "not-in-serp"     모으긴 했는데 그 안에 이 상품이 없다(= 진짜로 순위 밖일 수 있다)
        - "ambiguous-match" 같은 상품 주소에 서로 다른 nvMid 가 관측됐다(자동으로 넣지 않는다 · 사람 확인)

    ⚠️ 「못 찾음」을 한 덩어리로 돌려주면 안 된다 — 직원이 할 일이 셋 다 다르다.
       이 저장소가 반복해 데인 지점이다(「없다」와 「지금 안 된다」를 섞지 말 것).

    코덱스 1.22.0 이식(2026-09-22 3차) — 매칭을 두 단계로:
      ① **정확 식별**(product_identity.naver_product_identity — 호스트·스토어·상품번호 튜플 일치)
      ② ①이 0건이면 종전 규칙(채널 번호가 주소 안에 있으면 그 상품 — 2순위 폴백 · B5 측정 전까지 유지)
      후보의 nvMid 가 둘 이상 다르면 ambiguous-match(코덱스 채택). 순위는 양의 정수만 순위로 본다.
    ⚠️ 코덱스가 「오늘의 검증된 관측만」으로 좁힌 것은 **가져오지 않았다** — 14일 창을 좁히면
       not-collected 가 늘어 배치 채우기(nvmid_backfill)가 못 채운다. 창은 종전 그대로.
    """
    cid = channel_id_from_url(product_url)
    if not cid:
        return {"nv_mid": "", "keyword": "", "rank": None, "reason": "no-channel-id"}
    try:
        from product_identity import naver_product_identity, canonical_product_id
        identity = naver_product_identity(product_url)
    except Exception:
        identity, canonical_product_id = None, (lambda v: str(v) if v else None)

    kws = [str(k).strip() for k in (keywords or []) if str(k or "").strip()]
    try:
        if kws:
            ph = ",".join("?" * len(kws))
            rows = conn.execute(
                "SELECT keyword, products_json FROM collected_serp "
                f" WHERE keyword IN ({ph}) "
                "   AND collected_date >= date('now','localtime',?) "
                " ORDER BY collected_date DESC",
                kws + [f"-{int(days)} day"]).fetchall()
        else:
            rows = conn.execute(
                "SELECT keyword, products_json FROM collected_serp "
                " WHERE collected_date >= date('now','localtime',?) "
                " ORDER BY collected_date DESC LIMIT 400",
                (f"-{int(days)} day",)).fetchall()
    except sqlite3.Error:
        return {"nv_mid": "", "keyword": "", "rank": None, "reason": "not-collected"}

    if not rows:
        return {"nv_mid": "", "keyword": "", "rank": None, "reason": "not-collected"}

    exact, loose = {}, {}   # nv_mid → 가장 좋은(작은 순위) 관측
    def _put(bucket, pid, kw, rank):
        cur = bucket.get(pid)
        if cur is None or (rank is not None and (cur["rank"] is None or rank < cur["rank"])):
            bucket[pid] = {"nv_mid": pid, "keyword": kw, "rank": rank, "reason": "ok"}

    for r in rows:
        kw = r[0] if not hasattr(r, "keys") else r["keyword"]
        raw = r[1] if not hasattr(r, "keys") else r["products_json"]
        try:
            ps = json.loads(raw or "[]") or []
        except (ValueError, TypeError):
            continue
        for p in ps:
            if not isinstance(p, dict):
                continue
            link = str(p.get("link") or p.get("product_url") or "")
            pid = canonical_product_id(p.get("nvMid") or p.get("productId")) or ""
            if not link or not pid:
                continue
            rank = p.get("rank")
            rank = rank if (type(rank) is int and rank > 0) else None   # 양의 정수만 순위(코덱스)
            if identity is not None and naver_product_identity(link) == identity:
                if identity[0] == "nvMid" and identity[1] != pid:
                    continue   # 카탈로그 주소의 nvMid 와 수집 ID 가 다르면 자동 등록하지 않는다
                _put(exact, pid, kw, rank)
            elif cid in link:
                # 종전 2순위 규칙(채널 번호가 주소 안에) — 정확 식별이 0건일 때만 쓴다
                _put(loose, pid, kw, rank)

    found = exact or loose
    if len(found) > 1:
        return {"nv_mid": "", "keyword": "", "rank": None, "reason": "ambiguous-match"}
    if found:
        return next(iter(found.values()))
    return {"nv_mid": "", "keyword": "", "rank": None, "reason": "not-in-serp"}


# ──────────────────────────────────────────────────────────────────────────
#  조기 종료 — 키워드마다 「찾아야 할 nvMid 목록」
# ──────────────────────────────────────────────────────────────────────────

def targets_for_keywords(conn, keywords) -> dict:
    """{키워드: [nvMid, …]} — 확장이 「다 찾으면 멈출」 근거.

    ⚠️ nv_mid 가 **빈 상품은 넣지 않는다.** 없는 것을 목표로 두면 영원히 못 찾아
       조기 종료가 통째로 죽는다(A안이라 당분간 빈 상품이 많다).
    ⚠️ 목표가 하나도 없는 키워드는 **키를 아예 안 만든다** — 확장은 키가 없으면
       종전대로 끝까지 긁는다(무회귀).
    ⚠️ 축B(업체 대표 키워드)는 목표 상품이 특정되지 않으므로 여기 안 들어간다.
       그 키워드는 지금처럼 깊이까지 간다.
    """
    kws = [str(k).strip() for k in (keywords or []) if str(k or "").strip()]
    if not kws:
        return {}
    out = {}
    try:
        ensure_column(conn)
        ph = ",".join("?" * len(kws))
        rows = conn.execute(
            "SELECT k.keyword AS kw, p.nv_mid AS nv "
            "  FROM tracked_keywords k JOIN tracked_products p ON p.id = k.product_id "
            f" WHERE k.keyword IN ({ph}) "
            "   AND p.nv_mid IS NOT NULL AND TRIM(p.nv_mid) <> ''", kws).fetchall()
    except sqlite3.Error:
        return {}          # 조회가 깨지면 목표 없이 간다 = 종전 동작(무회귀)
    for r in rows:
        kw = r[0] if not hasattr(r, "keys") else r["kw"]
        nv = normalize(r[1] if not hasattr(r, "keys") else r["nv"])
        if not nv:
            continue
        lst = out.setdefault(kw, [])
        if nv not in lst:
            lst.append(nv)
    return out

# ──────────────────────────────────────────────────────────────────────────
#  일괄 자동 채우기 — 444개를 서버가 스스로 메운다 (2026-09-18)
# ──────────────────────────────────────────────────────────────────────────
#
# 왜 필요한가 — 대표 지시가 A안(새 등록만 필수)에서 **「nvMid 없으면 추적 안 함」**
# 으로 바뀌었다. 그런데 지금 등록된 444개는 **전부 비어 있다**(실측 0/444).
# 그대로 켜면 **내일부터 순위 기록이 0** 이 된다 — 되돌리기 어려운 종류의 사고다.
#
# ⇒ 순서를 바꾼다: ① 서버가 채울 수 있는 것을 전부 채우고 ② 남은 것 명단을 내고
#    ③ 그 다음에 「없으면 추적 안 함」을 켠다.
#
# ⚠️ **네이버에 요청하지 않는다.** 이미 모아 둔 수집분에서만 찾는다(자동 찾기와 같은 함수).
# ⚠️ **이미 채워진 값은 절대 안 덮는다** — 사람이 확인해 넣은 값이 기계 추정보다 낫다.

NVMID_BACKFILL_MARKER = ".nvmid_backfilled"


def backfill_from_collected(conn, limit: int = 0) -> dict:
    """nv_mid 가 빈 추적 상품을 수집분에서 찾아 채운다.

    반환 — {"scanned": n, "filled": n, "by_reason": {...}}

    ⚠️ 상품의 **자기 키워드로만** 찾는다. 아무 키워드나 뒤지면 같은 채널번호를 쓰는
       다른 상품을 잘못 집을 수 있다(자동 찾기 화면과 같은 규칙을 그대로 쓴다).
    ⚠️ 한 건이 실패해도 전체가 멈추지 않는다 — 실패 사유를 세어서 돌려준다.
    """
    out = {"scanned": 0, "filled": 0, "by_reason": {}}
    try:
        ensure_column(conn)
        rows = conn.execute(
            "SELECT id, product_url FROM tracked_products "
            " WHERE (nv_mid IS NULL OR TRIM(nv_mid) = '') "
            "   AND product_url IS NOT NULL AND TRIM(product_url) <> '' "
            " ORDER BY id").fetchall()
    except sqlite3.Error:
        return out
    if limit and limit > 0:
        rows = rows[:limit]

    for r in rows:
        pid = r[0] if not hasattr(r, "keys") else r["id"]
        url = r[1] if not hasattr(r, "keys") else r["product_url"]
        out["scanned"] += 1
        try:
            kws = [x[0] for x in conn.execute(
                "SELECT keyword FROM tracked_keywords WHERE product_id = ?", (pid,)).fetchall()]
        except sqlite3.Error:
            kws = []
        got = lookup_from_collected(conn, url, kws)
        reason = got.get("reason") or "?"
        out["by_reason"][reason] = out["by_reason"].get(reason, 0) + 1
        nv = normalize(got.get("nv_mid"))
        if not nv or not is_valid(nv):
            continue
        try:
            # ⚠️ 조건에 빈 값 검사를 다시 건다 — 조회와 쓰기 사이에 사람이 넣었을 수 있다.
            conn.execute(
                "UPDATE tracked_products SET nv_mid = ? "
                " WHERE id = ? AND (nv_mid IS NULL OR TRIM(nv_mid) = '')", (nv, pid))
            out["filled"] += 1
        except sqlite3.Error:
            continue
    try:
        conn.commit()
    except sqlite3.Error:
        pass
    return out


def missing_rows(conn, limit: int = 500) -> list:
    """아직 nv_mid 가 없는 추적 상품 — 직원에게 줄 명단의 재료.

    ⚠️ 업체명·상품명은 여기서 붙이지 않는다(호출처가 필요하면 붙인다) — 이 모듈은
       저장소 공개 로그에 그대로 찍히는 진단에서도 쓰인다.
    """
    try:
        ensure_column(conn)
        return [dict(zip(("id", "product_url", "keywords"), (r[0], r[1], r[2] or "")))
                for r in conn.execute(
                    "SELECT p.id, p.product_url, "
                    "       (SELECT GROUP_CONCAT(k.keyword, ',') FROM tracked_keywords k "
                    "         WHERE k.product_id = p.id) AS kws "
                    "  FROM tracked_products p "
                    " WHERE (p.nv_mid IS NULL OR TRIM(p.nv_mid) = '') "
                    " ORDER BY p.id LIMIT ?", (int(limit),)).fetchall()]
    except sqlite3.Error:
        return []
