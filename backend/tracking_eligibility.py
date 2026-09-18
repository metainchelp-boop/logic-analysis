"""순위 추적 자격 판정 — 전산 전체에서 **여기 한 곳만** 쓴다.

⚠️ 이 파일이 생긴 이유(2026-08-28 실측):
   같은 「추적 대상」을 세 곳이 각자 다른 기준으로 골라내고 있었다.

     · 수집(collector)      6조건 — 활성·광고주·스토어·자동분석·추적ON·추적기간
     · 기록(08:00 배치)     4조건 — 활성·광고주·스토어·자동분석  ← 추적ON·기간 없음
     · 추적 상품(홈탭)      필터 0 — get_all_tracked_products() 가 전량 반환

   그래서 **계약이 끝난 업체 65곳의 순위가 매일 계속 기록되고 있었다**.
   수집은 안 하는데 기록은 하니, 대표께서 「종료일이 적혀 있는데 왜 살아 있냐」고
   물으신 현상이 여기서 나왔다.

⚠️ 의존성 없음(표준 라이브러리만) — 배포 회귀 게이트가 fastapi 없이 import 한다.
   collector.py 는 fastapi 를 import 하므로 게이트에서 못 읽는다(split_rule.py 와 같은 이유).

재개 규칙: 전산①에서 업무 단계를 「진행중」으로 되돌리면 다음 날 04:00 계약 동기화가
   auto_analysis·track_until 을 되돌려 놓는다 → 여기서 자동으로 다시 자격이 생긴다.
   로직분석에서 사람이 따로 켤 필요가 없다(대표 확정 2026-08-28).
"""

# 자격 = 활성 · 광고주(영업대상·경쟁사 제외) · 스토어축 · 자동분석 ON
#        · 추적 켜짐 · 추적 기간이 남아 있음
ELIGIBLE_WHERE = (
    "status='active' "
    "AND COALESCE(role,'advertiser')='advertiser' "
    "AND COALESCE(vertical,'store')='store' "
    "AND COALESCE(auto_analysis,1)=1 "
    "AND COALESCE(track_enabled,1)=1 "
    "AND (track_until IS NULL OR track_until='' "
    "     OR date(track_until) >= date('now','localtime'))"
)


def eligible_clients_sql(columns: str = "id") -> str:
    """자격 있는 업체를 고르는 SELECT 문. columns 로 필요한 칸만 가져간다."""
    return f"SELECT {columns} FROM clients WHERE {ELIGIBLE_WHERE}"


def eligible_client_ids(conn) -> list:
    """자격 있는 업체 id 목록. 조회가 실패하면 빈 목록(=아무것도 안 함)."""
    try:
        return [r[0] for r in conn.execute(eligible_clients_sql("id")).fetchall()]
    except Exception:
        return []


# ── 추적 상품(홈탭) 자격 ──────────────────────────────────────────────
#
# 규칙(2026-08-28 대표 확정 「주인 없는 것들은 전부 없애는 게 낫겠어」):
#   · 자격 업체에 이어진 상품            → 잰다
#   · 자격 없는 업체에만 이어진 상품      → 안 잰다 (계약이 끝났다)
#   · 아무 업체에도 안 이어진 상품        → **비활성 처리한 것만** 뺀다
#
# ⚠️ 마지막 줄이 중요하다. 「연결 없음」을 그 자리에서 곧바로 제외해 버리면,
#    직원이 방금 손으로 등록해 아직 연결이 안 맺어진 상품까지 죽는다.
#    그래서 '연결 없음'은 01:20 정리 잡이 하루 지켜본 뒤 비활성으로 내리고,
#    여기서는 비활성 표시가 붙은 것만 뺀다. 되돌리려면 그 표시만 지우면 된다.

def eligible_tracked_product_ids(conn) -> set:
    """순위를 재야 할 추적 상품 id 집합."""
    try:
        rows = conn.execute(
            "SELECT p.id FROM tracked_products p "
            " WHERE COALESCE(p.disabled_at,'') = '' "
            "   AND ( p.id IN (SELECT tracked_product_id FROM rank_link "
            f"                  WHERE client_id IN ({eligible_clients_sql('id')})) "
            "      OR p.id NOT IN (SELECT tracked_product_id FROM rank_link) )"
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        # 판정에 실패하면 '전부 잰다'로 폴백한다 — 조회 하나가 실패했다고
        # 순위 추적이 통째로 멈추는 쪽이 훨씬 나쁘다.
        return None


def ensure_disabled_column(conn) -> None:
    """tracked_products.disabled_at 보장(멱등). 이미 있으면 아무 일도 안 한다."""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tracked_products)").fetchall()}
        if "disabled_at" not in cols:
            conn.execute("ALTER TABLE tracked_products ADD COLUMN disabled_at TEXT DEFAULT ''")
            conn.commit()
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────
#  「nvMid 없으면 추적 대상이 아니다」 — 대표 지시 2026-09-18
# ──────────────────────────────────────────────────────────────────────────
#
# 대표 지시 원문: 「미드값을 안 넣으면 추적 안 할거야. 무조건 미드값이 있어야만
# 추적 대상이 되도록 하고 싶어.」
#
# ⛔ **기본은 꺼 둔다(False).** 지금 등록된 444개가 **전부 비어 있어서**(실측 0/444)
#    그대로 켜면 **다음 회차부터 순위 기록이 0** 이 된다. 광고주 보고서와
#    ① portal-summary 가 동시에 빈다 — 되돌리기 어려운 종류의 사고다.
#
# 켜는 순서(이 순서를 지키지 않으면 위 사고가 난다):
#   ① 기동 백필이 돌아 채울 수 있는 것을 다 채운다(`nvmid.backfill_from_collected`)
#   ② 남은 명단을 직원이 처리한다
#   ③ 그때 이 값을 True 로 바꾸는 PR 하나 + 배포
#
# ⚠️ env `NVMID_REQUIRED` 로도 켤 수 있다(서버에서 즉시 되돌리기 위한 문).
NVMID_REQUIRED_DEFAULT = False


def nvmid_required() -> bool:
    """지금 「nvMid 없으면 추적 안 함」이 켜져 있는가."""
    import os
    v = (os.getenv("NVMID_REQUIRED") or "").strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    return NVMID_REQUIRED_DEFAULT
