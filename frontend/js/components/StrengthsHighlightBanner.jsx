/* StrengthsHighlightBanner — 리포트 상단 '자사 강점 요약' 배너
 * 기존 분석 데이터에서 강점만 파생(신규 데이터 없음). 강점이 1개 이상일 때만 노출. */
window.StrengthsHighlightBanner = function StrengthsHighlightBanner(props) {
  var reviewAnalysis = props.reviewAnalysis;
  var htmlReviewData = props.htmlReviewData;
  var marketRevenue = props.marketRevenue;
  var advertiserReport = props.advertiserReport;
  var datalabGrowth = props.datalabGrowth;

  var parseWon = function(s) { return parseInt(String(s == null ? '' : s).replace(/[^0-9]/g, ''), 10) || 0; };

  var strengths = [];

  /* 1) 리뷰 경쟁력 — 실측 자사 리뷰수 vs 경쟁 평균 */
  var rc = reviewAnalysis && reviewAnalysis.reviewCount;
  var myReviews = (htmlReviewData && htmlReviewData.reviewCount != null)
    ? htmlReviewData.reviewCount
    : (rc && rc.adv != null ? rc.adv : null);
  var avgReviews = rc && rc.avg != null ? rc.avg : null;
  if (myReviews != null && avgReviews != null && avgReviews > 0 && myReviews >= avgReviews) {
    var revMult = (myReviews / avgReviews);
    strengths.push({
      icon: '⭐', title: '리뷰 경쟁력',
      desc: '경쟁 평균 ' + fmt(avgReviews) + '건 대비 ' + fmt(myReviews) + '건 보유'
        + (revMult >= 1.2 ? ' (' + revMult.toFixed(1) + '배)' : ''),
      color: '#16a34a', bg: '#f0fdf4', border: '#bbf7d0'
    });
  }

  /* 2) 가격 경쟁력 — 자사 판매가 vs 1페이지 경쟁 평균가 */
  var myPrice = advertiserReport && advertiserReport.product_info ? (advertiserReport.product_info.price || 0) : 0;
  if (!myPrice && marketRevenue) myPrice = parseWon(marketRevenue.avgPrice);
  var compAvg = (advertiserReport && advertiserReport.competitor_comparison && advertiserReport.competitor_comparison.stats)
    ? (advertiserReport.competitor_comparison.stats.avg_price || 0) : 0;
  if (myPrice > 0 && compAvg > 0 && myPrice <= compAvg) {
    var cheaperPct = Math.round((compAvg - myPrice) / compAvg * 100);
    strengths.push({
      icon: '💰', title: '가격 경쟁력',
      desc: cheaperPct > 0 ? ('경쟁 평균 대비 ' + cheaperPct + '% 저렴') : '경쟁 평균 수준의 적정가',
      color: '#0ea5e9', bg: '#f0f9ff', border: '#bae6fd'
    });
  }

  /* 3) 상위 노출 — 현재 순위 10위 이내 */
  var rank = (advertiserReport && advertiserReport.ranking) ? advertiserReport.ranking.current_rank : null;
  if (rank != null && rank > 0 && rank <= 10) {
    strengths.push({
      icon: '🎯', title: '상위 노출 방어',
      desc: '현재 ' + rank + '위 — 이미 상위권 진입',
      color: '#7c3aed', bg: '#faf5ff', border: '#e9d5ff'
    });
  }

  /* 4) 검색 성장세 — 데이터랩 성장률(신뢰 가능한 값 중 최고) */
  if (datalabGrowth && datalabGrowth.periods && datalabGrowth.periods.length) {
    var best = null;
    datalabGrowth.periods.forEach(function(p) {
      if (p && p.reliable !== false && typeof p.growth === 'number' && p.growth > 0) {
        if (!best || p.growth > best.growth) best = p;
      }
    });
    if (best) {
      strengths.push({
        icon: '🔥', title: '검색 성장세',
        desc: '직전 ' + (best.label || '기간') + ' 대비 +' + best.growth + '%',
        color: '#ea580c', bg: '#fff7ed', border: '#fed7aa'
      });
    }
  }

  if (strengths.length === 0) return null;

  return React.createElement('div', { className: 'section fade-in' },
    React.createElement('div', { className: 'container' },
      React.createElement('div', {
        className: 'card',
        style: { padding: '18px 20px', background: 'linear-gradient(135deg,#eff6ff,#f5f3ff)', border: '1px solid #dbeafe' }
      },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 } },
          React.createElement('span', { style: { fontSize: 18 } }, '💪'),
          React.createElement('span', { style: { fontSize: 15, fontWeight: 800, color: '#1e293b' } }, '한눈에 보는 자사 강점'),
          React.createElement('span', { style: { fontSize: 11, color: '#94a3b8' } }, '· 아래 상세 지표에서 근거 확인')
        ),
        React.createElement('div', {
          style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }
        },
          strengths.map(function(s, i) {
            return React.createElement('div', {
              key: i,
              style: { background: s.bg, border: '1px solid ' + s.border, borderRadius: 12, padding: '12px 14px' }
            },
              React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 } },
                React.createElement('span', { style: { fontSize: 15 } }, s.icon),
                React.createElement('span', { style: { fontSize: 13, fontWeight: 700, color: s.color } }, s.title)
              ),
              React.createElement('div', { style: { fontSize: 12, color: '#475569', lineHeight: 1.5 } }, s.desc)
            );
          })
        )
      )
    )
  );
};
