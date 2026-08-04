/* RankDeltaROISimulation — 현재 순위 → 1위 도달 시 예상 성과 증분
 * salesEstimation의 순위별 추정값(실데이터)에서 파생. 값을 지어내지 않음. */
window.RankDeltaROISimulation = function RankDeltaROISimulation(props) {
  var se = props.salesEstimation;
  var currentRank = props.currentRank; // null = 미노출
  if (!se || !se.top10Card) return null;

  var top10 = se.top10Card;
  var n = function(v) { return Number(v) || 0; };

  var s1 = n(top10.rank1Sales), s5 = n(top10.rank5Sales), s10 = n(top10.rank10Sales);
  if (s1 <= 0) return null; // 1위 추정치가 없으면 델타 계산 불가

  // 순위 → 예상 월 판매(건) : 1/5/10위 앵커로 선형보간, 10위 밖은 감쇠
  var salesForRank = function(r) {
    if (r == null) return 0;          // 미노출 → 0 기준(전량 업사이드)
    if (r <= 1) return s1;
    if (r <= 5) return s1 + (s5 - s1) * (r - 1) / 4;
    if (r <= 10) return s5 + (s10 - s5) * (r - 5) / 5;
    // 10위 밖: 10위 값에서 순위가 낮아질수록 감쇠(최저 10%)
    return Math.max(s10 * Math.pow(0.92, r - 10), s10 * 0.1);
  };

  var isRanked = currentRank != null && currentRank > 0;
  var curSales = Math.round(salesForRank(isRanked ? currentRank : null));
  var tgtSales = Math.round(s1);
  var deltaSales = Math.max(tgtSales - curSales, 0);

  // 이미 1위면 방어 메시지
  var alreadyTop = isRanked && currentRank === 1;

  var curLabel = isRanked ? (currentRank + '위') : '미노출';
  var pct = curSales > 0 ? Math.round(deltaSales / curSales * 100) : null;

  var Col = function(title, value, sub, color) {
    return React.createElement('div', {
      style: { flex: 1, minWidth: 130, textAlign: 'center', padding: '14px 12px', background: '#f8fafc', borderRadius: 12, border: '1px solid #e2e8f0' }
    },
      React.createElement('div', { style: { fontSize: 11, fontWeight: 600, color: '#94a3b8', marginBottom: 6 } }, title),
      React.createElement('div', { style: { fontSize: 22, fontWeight: 800, color: color || '#0f172a' } }, value),
      sub ? React.createElement('div', { style: { fontSize: 11, color: '#64748b', marginTop: 4 } }, sub) : null
    );
  };

  return React.createElement('div', { className: 'section fade-in' },
    React.createElement('div', { className: 'container' },
      React.createElement('div', { className: 'card', style: { padding: '20px 22px' } },
        React.createElement('h3', { className: 'rt-h3' },
          React.createElement('span', { className: 'rt-hic' }, '📈'),
          '순위 상승 시 예상 성과',
          React.createElement('span', { className: 'badge b-est' }, '≈ 추정')
        ),
        React.createElement('div', { className: 'rt-desc' },
          alreadyTop
            ? '이미 1위입니다 — 방어 관점의 참고 지표입니다.'
            : '현재 순위 대비 1위 도달 시 예상되는 월 판매 증분(순위별 추정 판매량 기반)'
        ),

        alreadyTop
          ? React.createElement('div', {
              style: { marginTop: 12, padding: '14px 16px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, fontSize: 13, color: '#065f46', lineHeight: 1.6 }
            }, '🎉 현재 1위입니다. 예상 월 판매 ~' + fmt(tgtSales) + '건 수준을 유지하려면 리뷰·가격·상세페이지 방어에 집중하세요.')
          : React.createElement('div', null,
              React.createElement('div', { style: { display: 'flex', gap: 12, marginTop: 12, flexWrap: 'wrap', alignItems: 'stretch' } },
                Col('현재 (' + curLabel + ')', isRanked ? ('~' + fmt(curSales) + '건') : '0건', '예상 월 판매', '#64748b'),
                Col('목표 (1위)', '~' + fmt(tgtSales) + '건', '예상 월 판매', '#3b82f6'),
                Col('증분 (Δ)', '+' + fmt(deltaSales) + '건', pct != null ? ('현재 대비 +' + pct + '%') : '1위 도달 시 순증', '#16a34a')
              ),
              React.createElement('div', {
                style: { marginTop: 12, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 10, fontSize: 11.5, color: '#92400e', lineHeight: 1.6 }
              }, '※ 순위별 클릭률(CTR) 기반 추정치입니다. 실제 성과는 상품 경쟁력·리뷰·가격·시즌에 따라 달라지며, 순위 상승을 보장하지 않습니다.')
            )
      )
    )
  );
};
