/* SummaryCardsSection — 종합 요약 (v6.6: 경영자 히어로 요약 + KPI 4칸)
 * 히어로: 6장에 묻혀 있던 종합 진입 점수·현재 순위를 문서 최상단으로 승격.
 *   결론 1문장 + 점수 게이지 + 추천 액션 Top3(섹션 앵커). 데이터가 없으면
 *   히어로만 조용히 생략되고 기존 KPI 카드 레이아웃이 그대로 유지된다(무손실).
 * KPI: 결측값('-'·0)은 초록 ✅ 대신 중립 '집계 없음' 배지로 강등 — 가짜 검증 인상 방지. */
window.SummaryCardsSection = function SummaryCardsSection(props) {
  if (!props?.data) return null;
  const { totalVolume, productCount, goldenCount, compLevel, note } = props.data;
  // ★ totalVolume/productCount 는 App.jsx에서 이미 fmt() 적용된 문자열 → 그대로 출력(이중 포맷 NaN 방지)

  /* ===== 히어로 데이터 파생 (전부 기존 분석 데이터 재사용 — 신규 호출 없음) ===== */
  var adv = props.advertiserReport || null;
  var strategy = (adv && adv.entry_strategy) || {};
  var score = Number(strategy.overall_score) || 0;
  var ranking = (adv && adv.ranking) || {};
  var rank = (props.rankCheckResult && props.rankCheckResult.rank_position != null)
    ? props.rankCheckResult.rank_position
    : (ranking.current_rank != null ? ranking.current_rank : null);
  var onPage1 = rank != null && rank > 0 && rank <= 40;
  var rating = (props.htmlReviewData && props.htmlReviewData.rating != null) ? props.htmlReviewData.rating : null;
  var kw = props.keyword || '';

  var scoreColor = score >= 70 ? '#34d399' : score >= 40 ? '#fbbf24' : '#f87171';
  var scoreLabel = score >= 70 ? '양호' : score >= 40 ? '보통' : '개선 필요';

  /* 결론 1문장 — 규칙 기반(실데이터만 인용) */
  var conclusion = '';
  if (rank != null && rank > 0) {
    conclusion = '현재 ' + fmt(rank) + '위' + (onPage1 ? ' (1페이지 진입)' : '');
    if (rating != null && Number(rating) >= 4.5) conclusion += ' · 리뷰 평점 ' + rating + ' 강점';
    conclusion += '. ';
  }
  if (score >= 70) conclusion += '기반이 탄탄해 상위 노출 여력이 충분합니다.';
  else if (score >= 40) conclusion += '핵심 항목 보완 시 순위 상승 여지가 있습니다.';
  else if (score > 0) conclusion += '아래 추천 액션부터 순서대로 개선이 필요합니다.';
  else if (rank != null) conclusion += '아래 보고서에서 항목별 상세 진단을 확인하세요.';

  /* 추천 액션 Top3 — 진입 전략의 심각도 순 상위 3개 (섹션 앵커로 연결) */
  var sevRank = { high: 0, medium: 1, low: 2 };
  var actions = (strategy.strategies || [])
    .filter(function(s) { return s && s.area; })
    .slice()
    .sort(function(a, b) { return (sevRank[a.severity] != null ? sevRank[a.severity] : 1) - (sevRank[b.severity] != null ? sevRank[b.severity] : 1); })
    .slice(0, 3);

  var showHero = score > 0 || (rank != null && rank > 0);

  /* KPI 결측 판정 — '-'·빈값·0(콤마 포맷 문자열 '0' 포함)은 중립 처리 */
  var isMissing = function(v) {
    if (v == null) return true;
    var s = String(v).trim();
    return s === '' || s === '-' || s === '0';
  };
  var Kpi = function(label, value, unit, opts) {
    opts = opts || {};
    var missing = opts.forceMissing != null ? opts.forceMissing : isMissing(value);
    return (
      <div className="kpi">
        <div className="k">{label} {missing
          ? <span className="badge b-n">집계 없음</span>
          : <span className="badge b-ok">✅</span>}</div>
        <div className="v" style={{ color: missing ? '#94a3b8' : undefined, fontSize: opts.fontSize }}>
          {missing ? '—' : value}
          {!missing && unit ? <small>{unit}</small> : null}
        </div>
      </div>
    );
  };

  return (
    <div className="section fade-in">
      <div className="container">
        {/* ===== 경영자 히어로 요약 (점수·순위 있을 때만 — 없으면 기존 화면 그대로) ===== */}
        {showHero && (
          <div className="card" style={{
            background: 'linear-gradient(135deg, #3b82f6, #7c3aed)', border: 'none',
            color: '#fff', padding: '22px 26px', marginBottom: 14
          }}>
            <div className="rpt-flex" style={{ display: 'flex', gap: 20, alignItems: 'center', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 220 }}>
                <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: '0.14em', opacity: 0.8, marginBottom: 6 }}>핵심 결론</div>
                <div style={{ fontSize: 18, fontWeight: 800, lineHeight: 1.5, letterSpacing: '-0.2px' }}>
                  {kw ? '"' + kw + '" — ' : ''}{conclusion}
                </div>
                {actions.length > 0 && (
                  <div style={{ marginTop: 12, background: 'rgba(255,255,255,0.12)', borderRadius: 12, padding: '10px 14px' }}>
                    <div style={{ fontSize: 11, fontWeight: 800, opacity: 0.85, marginBottom: 4 }}>지금 하면 좋은 것 Top {actions.length}</div>
                    {actions.map(function(s, i) {
                      return (
                        <div key={i} style={{ fontSize: 12.5, fontWeight: 600, padding: '2px 0', display: 'flex', gap: 8 }}>
                          <span style={{ opacity: 0.75 }}>{i + 1}.</span>
                          <a href="#sec-strategy" style={{ color: '#fff', textDecoration: 'none' }}>
                            {s.area}
                            <span style={{ opacity: 0.65, fontWeight: 500, marginLeft: 6, fontSize: 11 }}>
                              {s.severity === 'high' ? '긴급' : s.severity === 'low' ? '선택' : '권장'} → 진입 전략
                            </span>
                          </a>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
              {score > 0 && (
                <div style={{ textAlign: 'center', flexShrink: 0 }}>
                  <div style={{
                    width: 84, height: 84, borderRadius: '50%', margin: '0 auto',
                    background: 'conic-gradient(' + scoreColor + ' ' + (score * 3.6) + 'deg, rgba(255,255,255,0.22) 0deg)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center'
                  }}>
                    <div style={{
                      width: 64, height: 64, borderRadius: '50%', background: '#5b50e8',
                      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'
                    }}>
                      <span style={{ fontSize: 22, fontWeight: 900, lineHeight: 1 }}>{score}</span>
                      <span style={{ fontSize: 10, opacity: 0.8 }}>/100</span>
                    </div>
                  </div>
                  <div style={{
                    marginTop: 8, display: 'inline-block', fontSize: 11, fontWeight: 800,
                    background: 'rgba(255,255,255,0.18)', borderRadius: 999, padding: '3px 12px'
                  }}>종합 진입 점수 · {scoreLabel}</div>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="card">
          <h3 className="rt-h3"><span className="rt-hic">🎯</span>종합 요약</h3>
          <div className="grid4">
            {Kpi('월간 검색량', totalVolume, '회/월')}
            {Kpi('등록 상품수', productCount, '개')}
            <div className="kpi"><div className="k">골든 키워드 <span className="badge b-ok">✅</span></div><div className="v" style={{ color: (Number(goldenCount) === 0 ? '#f59e0b' : undefined) }}>{goldenCount}<small>{Number(goldenCount) === 0 ? '개 — 롱테일 권장' : '개 발견'}</small></div></div>
            {Kpi('경쟁강도', compLevel, '', { fontSize: '22px' })}
          </div>
          {note && <div className="note">💡 {note}</div>}
        </div>
      </div>
    </div>
  );
};
