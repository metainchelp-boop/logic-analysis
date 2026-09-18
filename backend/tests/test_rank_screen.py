"""회귀 — 순위 추적 화면(#rank = KeywordRankPage) 펼치기 개편 (대표 지시 2026-09-18)

지키는 것:
  ① rank-board 응답이 며칠째용 tracking_started 와 키워드별 has_nvmid 를 준다.
  ② 화면(KeywordRankPage)이 랜딩에서 **펼치기**(페이지 이동 없음)를 한다.
  ③ 「300위 밖」·「nvMid 없음」을 배지로 표기한다.

⚠️ 게이트 환경엔 fastapi 가 없어 import 로 못 돌린다 → 소스로 배선을 확인한다.
   ⚠️ 이름만 찾으면 주석·설명문에 걸린다 — **조회문·호출 모양**으로 판정한다
      (이 저장소가 반복해 데인 지점: 문구 vs 동작).
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)

passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


print("① BE — rank-board 가 며칠째·nvMid 를 준다")
cd = read("backend/client_dashboard.py")
# rank-board 함수 본문만 잘라 본다(다른 엔드포인트의 같은 이름에 안 속게)
i = cd.index("def rank_board(")
body = cd[i:cd.index("\n@router", i) if "\n@router" in cd[i:] else len(cd)]
ok("🔴 응답에 tracking_started 를 넣는다",
   re.search(r'"tracking_started":\s*tracking_started', body) is not None)
ok("🔴 tracking_started 를 MIN(checked_at) 로 실제 조회한다",
   re.search(r"SELECT MIN\(checked_at\) FROM client_rank_history", body) is not None)
ok("🔴 board 행마다 has_nvmid 를 붙인다",
   re.search(r'b\["has_nvmid"\]\s*=', body) is not None)
ok("nvMid 있는 상품을 실제로 조회한다(COALESCE(nv_mid,'') <> '')",
   "COALESCE(nv_mid,'') <> ''" in body)
ok("판정 실패 시 죽지 않는다(tracking_started None 폴백)",
   "tracking_started = None" in body)
# 시안 정합(2026-09-18) — 펼침 카드가 nvMid 값을 그대로 보여주므로 값도 내려준다
ok("🔴 board 행에 nvMid 값을 붙인다(불리언만이 아니라)",
   re.search(r'b\["nvmid"\]\s*=', body) is not None)
# 며칠째를 접힌 줄에도 보이게 — rank_overview 가 tracking_started 를 준다
ok("🔴 rank_overview 가 업체별 tracking_started 를 준다",
   re.search(r'"tracking_started":\s*_first_map\.get', cd) is not None)
ok("첫 기록일을 MIN(checked_at) 로 업체별 조회한다",
   re.search(r"SELECT client_id, MIN\(checked_at\)[\s\S]{0,200}GROUP BY client_id", cd) is not None)

print("\n② FE — KeywordRankPage 펼치기(페이지 이동 없음)")
fe = read("frontend/js/components/KeywordRankPage.jsx")
ok("🔴 랜딩 행 클릭이 toggleExpand 를 부른다(openDetail 즉시 이동 아님)",
   re.search(r"onClick:\s*function\(\)\s*\{\s*toggleExpand\(c\);\s*\}", fe) is not None)
ok("toggleExpand 가 정의돼 있다", "var toggleExpand = function" in fe)
ok("🔴 펼침은 rank-board 를 지연 호출한다",
   re.search(r"toggleExpand[\s\S]{0,400}/cd/'\s*\+\s*c\.id\s*\+\s*'/rank-board", fe) is not None)
ok("펼침 패널(_expandPanel)을 그린다", "_expandPanel(c)" in fe and "var _expandPanel" in fe)
ok("🔴 「상세 보기」 버튼이 openDetail 로 넘어간다(별도 단계)",
   re.search(r"openDetail\(c\);[\s\S]{0,400}상세 보기", fe) is not None)
ok("며칠째를 첫 기록일로 센다", "var _daysSince" in fe and "tracking_started" in fe)

print("\n③ FE — 300위 밖 · nvMid 없음 표기")
ok("🔴 300위 밖을 글자로 표기한다", "300위 밖" in fe)
ok("🔴 nvMid 없음을 글자로 표기한다", "nvMid 없음" in fe)
ok("첫 수집 대기 상태가 있다", "첫 수집 대기" in fe)
ok("상태 배지 함수(_kwStateChip)가 has_nvmid 를 본다",
   "var _kwStateChip" in fe and "b.has_nvmid === false" in fe)

print("\n④ FE — 시안 정합(며칠째 칸 · 카드형 펼침 2026-09-18)")
ok("🔴 접힌 줄에 「추적」 칸(며칠째)이 있다",
   re.search(r"React\.createElement\('th',[^)]*\},\s*'추적'\)", fe) is not None)
ok("🔴 행이 _daysBadge(c.tracking_started) 를 그린다",
   "_daysBadge(c.tracking_started)" in fe and "var _daysBadge" in fe)
ok("🔴 펼침이 키워드 카드(_kwCard)를 그린다", "var _kwCard" in fe and "brd.map(_kwCard)" in fe)
ok("🔴 카드가 스파크라인을 그린다", re.search(r"var _kwCard[\s\S]{0,1500}_krSparkline\(b\.series\)", fe) is not None)
ok("🔴 카드가 nvMid 값을 보여준다(있으면 값·없으면 없음)",
   re.search(r"var _kwCard[\s\S]{0,2000}nvMid[\s\S]{0,40}b\.nvmid", fe) is not None)
ok("카드가 최고/최저를 series 에서 계산한다", "최고 ' + best" in fe and "최저 ' + worst" in fe)

print(f"\n{'✅' if not failed else '🔴'} 통과 {passed} · 실패 {failed}")
sys.exit(1 if failed else 0)
