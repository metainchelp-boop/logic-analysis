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

    ⚠️ 「못 찾음」을 한 덩어리로 돌려주면 안 된다 — 직원이 할 일이 셋 다 다르다.
       이 저장소가 반복해 데인 지점이다(「없다」와 「지금 안 된다」를 섞지 말 것).
    """
    cid = channel_id_from_url(product_url)
    if not cid:
        return {"nv_mid": "", "keyword": "", "rank": None, "reason": "no-channel-id"}

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

    for r in rows:
        kw = r[0] if not hasattr(r, "keys") else r["keyword"]
        raw = r[1] if not hasattr(r, "keys") else r["products_json"]
        try:
            ps = json.loads(raw or "[]") or []
        except (ValueError, TypeError):
            continue
        for p in ps:
            link = str(p.get("link") or p.get("product_url") or "")
            pid = str(p.get("productId") or "")
            # 지금 순위 매칭 2순위와 **같은 규칙** — 채널 번호가 상품 주소에 들어 있으면 그 상품이다.
            if not link or cid not in link:
                continue
            if not pid:
                continue
            try:
                rank = int(p.get("rank"))
            except (TypeError, ValueError):
                rank = None
            return {"nv_mid": pid, "keyword": kw, "rank": rank, "reason": "ok"}

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
