"""회귀 — 수집기 운영 패널 + 차트 빈 구간(코덱스 1.22.0 「운영 화면」 이식판 · 5차 · 2026-09-22)

지키는 것(소스 배선):
  ① CollectorOpsPanel 이 업체 상세가 아닐 때(!selected) · 뷰어 제외로 붙는다 · GET /collector/v2/daily 를 읽는다 · 5분 주기.
  ② 전체 재개는 관리자 + 「원인을 검토했습니다」 체크 없이는 보내지 않는다 · 중지/재개는 POST /collector/v2/control.
  ③ 못 잰 값은 「미확인」(0 이 아니다) · 첫 조회 전엔 안 그린다 · 미전송 판정 4갈래(보고 없음/확인 불가/세션 바뀜/n건).
  ④ 차트 — 스파크라인 빈 날 끊기(회색) · Chart.js spanGaps:false 두 곳 · rankImage 는 전체 날짜 축 + 빈 구간이면 면적 없음.
  ⑤ 「300위 밖」 표기 유지 — 코덱스의 「순위 미확인」 라벨 교체는 가져오지 않는다(대표 확정 9/22).
  ⑥ 문서 — 운영 런북·실기기 점검표·직원 안내가 저장소에 있다 · 게이트 등록.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE); ROOT = os.path.dirname(BACKEND)
passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


KRP = read("frontend/js/components/KeywordRankPage.jsx"); RTS = read("frontend/js/components/RankTrackingSection.jsx"); IMG = read("frontend/js/rankImage.js")
DEPLOY = read(".github/workflows/deploy.yml")
panel = KRP[KRP.index("function CollectorOpsPanel(props)"):KRP.index("var _krOpsBtn = ")]

print("① 패널 배선")
ok("🔴 업체 상세가 아닐 때 · 뷰어 제외로 붙는다", "!selected && !isViewer && React.createElement(CollectorOpsPanel, { currentUser: currentUser })" in KRP)
ok("🔴 GET /collector/v2/daily 를 읽고 protocol=2 를 확인한다", "api.get('/collector/v2/daily')" in panel and "data.protocol !== 2" in panel)
ok("5분 주기 새로고침 + 언마운트 정리", "setInterval(load, 5 * 60 * 1000)" in panel and "clearInterval(t)" in panel and "alive.current = false" in panel)
ok("첫 조회 전엔 아무것도 안 그린다", "if (!d && !view.error) return null;" in panel)

print("\n② 제어")
ok("🔴 재개는 검토 체크 없이는 보내지 않는다", "if (next === 'READY' && !view.reviewed) return;" in panel)
ok("🔴 제어는 관리자만 · POST /collector/v2/control", "if (!isAdmin) return;" in panel[panel.index("function control(next)"):panel.index("function control(next)") + 200] and "api.post('/collector/v2/control', { state: next, reason: reason })" in panel)
ok("재개 버튼은 체크 전엔 disabled · 중지 버튼은 READY 일 때만", "disabled: !view.reviewed" in panel and "ctlState === 'READY' && React.createElement('button'" in panel)
ok("제어 실패는 자동 재전송하지 않는다고 말한다", "자동 재전송하지 않습니다" in panel)
ok("설정 점검은 관리자만(readiness)", "function check() {\n        if (!isAdmin) return;" in panel and "api.get('/collector/v2/readiness')" in panel)

print("\n③ 「미확인」 · 미전송 판정")
ok("🔴 null/undefined 는 「미확인」으로 그린다(0 아님)", "function _krOpsNum(v) { return (v === null || v === undefined) ? '미확인'" in KRP)
ok("🔴 미전송 4갈래 — 보고 없음 · 확인 불가 · 세션 바뀜 · n건(검토 필요·오래된 보고)", all(t in KRP for t in ("'보고 없음'", "'확인 불가'", "세션 바뀜", "검토 필요", "오래된 보고")))
ok("기계 신호 못 읽음(null)과 0대를 가른다", "machines === null ? React.createElement('p'" in panel and "!machines.length ? React.createElement('p'" in panel)
ok("하단 안내 — 「미확인」은 못 잰 것이지 0 이 아니다", "못 잰 것이지 0 이 아닙니다" in panel)

print("\n④ 차트 빈 구간")
spark = KRP[KRP.index("function _krSparkline(series)"):KRP.index("\n}\n", KRP.index("function _krSparkline(series)"))]
ok("🔴 스파크라인 — 전체 표본 축에 빈 날은 끊고(M/L) 빈 구간이면 회색", "if (c === null) { previous = false; return ''; }" in spark and "var gap = pts.length < samples.length;" in spark and "gap ? '#64748b'" in spark)
ok("🔴 Chart.js spanGaps:false — KeywordRankPage · RankTrackingSection", "spanGaps: false" in KRP and "spanGaps: true" not in KRP and "spanGaps: false" in RTS and "spanGaps: true" not in RTS)
ok("🔴 rankImage — 전체 날짜 축(data) · 빈 날은 선 끊김 · 빈 구간이면 면적 없음", "var xOf = function (i) { return chartLeft + (chartRight - chartLeft) * (i / Math.max(1, data.length - 1)); };" in IMG and "if (!has(r)) { connected = false; return; }" in IMG and "if (validData.length === data.length) {" in IMG)

print("\n⑤ 표기 유지")
ok("🔴 「300위 밖」 표기 그대로 · 코덱스 「순위 미확인」 라벨 미도입", "300위 밖" in KRP and "300위 밖" in RTS and "순위 미확인" not in KRP and "순위 미확인" not in RTS and "순위 미확인" not in IMG)

print("\n⑥ 문서·게이트")
for rel in ("docs/수집기-운영-런북.md", "docs/수집기-실기기-점검표.md", "docs/수집기-운영-패널-직원-안내.html"):
    ok(f"문서 존재 — {rel}", os.path.exists(os.path.join(ROOT, rel)) and os.path.getsize(os.path.join(ROOT, rel)) > 1000)
ok("직원 안내는 외부 의존 없는 단일 HTML(밝은 테마 고정)", (lambda h: "<script src=" not in h and "https://" not in h.replace("https://logic.metainc.co.kr", "") and "prefers-color-scheme" not in h)(read("docs/수집기-운영-패널-직원-안내.html")) if os.path.exists(os.path.join(ROOT, "docs/수집기-운영-패널-직원-안내.html")) else False)
ok("게이트 등록 — test_collector_ops_panel", "backend/tests/test_collector_ops_panel.py" in DEPLOY)

print(f"\n{'✅' if not failed else '❌'} 운영 패널 회귀 — {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
