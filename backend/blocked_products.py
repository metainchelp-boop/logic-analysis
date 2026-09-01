"""「추적 안 됨」 정리함 — 어떤 상품이 왜 안 재지는지 모으고, 그 자리에서 처분한다.

## 배경 (신고 #248 후속 · 2026-09-01 대표 확정)

9/1 배포로 직원 화면에 「⚠ 추적 안 됨」 배지가 보이기 시작했다. 이 모듈은 그것들을
한 화면에 모아 처분하는 정리함의 서버 쪽 몫이다. 실측(9/1): 계약 끝난 업체에만 이어진
상품 66개(키워드 144짝) · 주인 없어 자동 비활성 41개(68짝).

## 두 무리 — 처분이 정반대라 한 목록으로 섞지 않는다

  stuck   활성인데 **자격 없는 업체에만** 이어진 상품 — 계약 만료·환불·홀딩 등.
          계약이 살아나면 04:00 동기화가 자격을 되살려 **자동 재개**되므로 기본은
          「그대로 두기」다. 다시 볼 일 없는 것만 내린다(shelve).
  shelved 내려간 상품(disabled_at) — 01:20 잡이 주인 없어 내린 것 + 사람이 내린 것.
          업체를 이어 주면 그 자리에서 되살아난다. **하드 삭제는 없다**
          (대표 확정 「내리기로 통일」 — 실수해도 되돌릴 수 있어야 한다).

⚠️ 「연결 없음 + 활성」 상품은 여기 안 나온다 — 규칙상 **수집되고 있는** 상품이고
   (방금 등록분 보호), 화면 하단 도구가 이미 그 목록을 보여준다. 여기 넣으면
   「추적 안 됨」이라는 이름이 거짓말이 된다.

## 왜 파일을 따로 뒀나 (split_rule·keyword_mute·kst_backfill 과 같은 이유)

배포 게이트 환경에는 fastapi 가 없어 main.py 를 임포트할 수 없다.
판정·처분이 거기 있으면 검사할 방법이 없다. 여기는 표준 라이브러리만 쓴다.
"""
import logging

logger = logging.getLogger(__name__)


def _stage_of(row) -> str:
    """사람이 읽는 자격 탈락 사유 — 전산 단계명이 있으면 그대로(단계명이 곧 계약)."""
    stage = (row["contract_stage"] or "").strip() if "contract_stage" in row.keys() else ""
    if stage:
        return stage
    if not row["auto_analysis"]:
        return "자동 분석 꺼짐"
    if not row["track_enabled"]:
        return "추적 꺼짐"
    if (row["track_until"] or "").strip():
        return "추적 기간 만료"
    return "자격 없음"


def list_blocked(conn) -> dict:
    """정리함 목록. {"stuck": [...], "shelved": [...]} — 전부 읽기 전용.

    ⚠️ 자격 판정은 tracking_eligibility 한 곳만 쓴다. 여기서 조건을 다시 쓰면
       수집·기록·화면이 서로 다른 답을 하게 된다 — 이번에 고치는 문제 그 자체다.
    """
    from tracking_eligibility import eligible_client_ids, ensure_disabled_column
    ensure_disabled_column(conn)
    ok_clients = set(eligible_client_ids(conn))

    stuck, shelved = [], []
    rows = conn.execute("""
        SELECT p.id, p.product_name, p.product_url, p.store_name,
               COALESCE(p.disabled_at,'') AS disabled_at
          FROM tracked_products p""").fetchall()
    kw_map = {}
    for r in conn.execute("SELECT product_id, keyword FROM tracked_keywords"):
        k = (r[1] or "").strip()
        if k:
            kw_map.setdefault(r[0], []).append(k)
    link_map = {}
    for r in conn.execute("""
        SELECT l.tracked_product_id, l.client_id, c.name,
               COALESCE(c.contract_stage,'') AS contract_stage,
               COALESCE(c.auto_analysis,1)   AS auto_analysis,
               COALESCE(c.track_enabled,1)   AS track_enabled,
               CASE WHEN COALESCE(c.track_until,'') <> ''
                     AND date(c.track_until) < date('now','localtime')
                    THEN c.track_until ELSE '' END AS track_until
          FROM rank_link l JOIN clients c ON c.id = l.client_id"""):
        link_map.setdefault(r["tracked_product_id"], []).append(r)

    for p in rows:
        links = link_map.get(p["id"], [])
        item = {
            "id": p["id"],
            "name": p["product_name"] or "",
            "store": p["store_name"] or "",
            "url": p["product_url"] or "",
            "keywords": sorted(kw_map.get(p["id"], [])),
            "clients": [{"id": l["client_id"], "name": l["name"],
                         "eligible": l["client_id"] in ok_clients,
                         "stage": "" if l["client_id"] in ok_clients else _stage_of(l)}
                        for l in links],
        }
        if p["disabled_at"]:
            item["disabled_at"] = p["disabled_at"][:10]
            shelved.append(item)
        elif links and all(l["client_id"] not in ok_clients for l in links):
            stuck.append(item)

    stuck.sort(key=lambda x: x["name"])
    shelved.sort(key=lambda x: (x.get("disabled_at", ""), x["name"]))
    return {"stuck": stuck, "shelved": shelved,
            "stuck_keywords": len({k for i in stuck for k in i["keywords"]}),
            "shelved_keywords": len({k for i in shelved for k in i["keywords"]})}


def shelve(conn, product_id: int) -> bool:
    """상품을 내린다 — 지우지 않는다. 수집·기록에서 빠지고 shelved 무리로 옮겨 간다.

    ⚠️ KST 를 명시한다 — 표 기본값에 기대면 8/31 reports 와 같은 UTC 병이 또 생긴다.
    """
    cur = conn.execute(
        "UPDATE tracked_products SET disabled_at = datetime('now','localtime')"
        " WHERE id = ? AND COALESCE(disabled_at,'') = ''", (product_id,))
    return cur.rowcount > 0


def revive(conn, product_id: int) -> dict:
    """내려간 상품을 되살린다. 자격 있는 업체에 이어져 있어야만 살린다.

    ⚠️ 자격 없는 업체뿐인데 살리면 stuck 무리로 자리만 옮겨 간다 — 그건 처분이 아니라
       문제를 옆 칸으로 미는 것이다. 그 경우 살리지 않고 「업체 연결부터」를 안내한다.
    """
    from tracking_eligibility import eligible_client_ids
    ok = set(eligible_client_ids(conn))
    linked = [r[0] for r in conn.execute(
        "SELECT client_id FROM rank_link WHERE tracked_product_id = ?", (product_id,))]
    if not any(c in ok for c in linked):
        return {"ok": False,
                "reason": ("이어진 업체가 없습니다 — 업체를 먼저 연결해 주세요" if not linked
                           else "이어진 업체가 전부 자격이 없습니다(계약 만료 등) — 자격 있는 업체로 연결해 주세요")}
    cur = conn.execute(
        "UPDATE tracked_products SET disabled_at = ''"
        " WHERE id = ? AND COALESCE(disabled_at,'') <> ''", (product_id,))
    return {"ok": cur.rowcount > 0,
            "reason": "" if cur.rowcount > 0 else "이미 활성 상태입니다"}
