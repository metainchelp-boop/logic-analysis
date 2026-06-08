window.ReviewAnalysisSection = function ReviewAnalysisSection(props) {
  if (!props?.data) return null;
  const { reviewCount, rating, wishCount, strategy } = props.data;

  if (!reviewCount || !rating || !wishCount) return null;

  // HTML에서 추출된 실제 리뷰 데이터 (있으면 내 상품 값으로 사용)
  const html = props.htmlReviewData || null;
  const hasHtmlData = html && (html.reviewCount != null || html.rating != null || html.wishCount != null);

  var fmt = function(n) { return n != null ? Number(n).toLocaleString('ko-KR') : '-'; };
  var num = function(v) { return (v == null || isNaN(Number(v))) ? 0 : Number(v); };

  var mineReview = (hasHtmlData && html && html.reviewCount != null) ? html.reviewCount : reviewCount.adv;
  var top5Review = reviewCount.top5;

  // 시안 톤 노트: '부족 지적 → 해결방안' 논리 (광고주 보고서, 실데이터 기반)
  var noteText;
  if (top5Review && mineReview < top5Review) {
    noteText = '리뷰 ' + fmt(mineReview) + '건(상위5 평균 ' + fmt(top5Review) + '건 대비 부족) — 구매 전환의 가장 큰 병목. 체험단으로 단기 확보 필요.';
  } else if (reviewCount.avg && mineReview < reviewCount.avg) {
    noteText = '리뷰 ' + fmt(mineReview) + '건(경쟁 평균 ' + fmt(reviewCount.avg) + '건 대비 부족) — 구매 전환의 핵심 지표. 체험단으로 단기 확보 필요.';
  } else {
    noteText = '리뷰 ' + fmt(mineReview) + '건 — 경쟁 대비 양호. 평점·재구매 관리로 전환율을 끌어올리세요.';
  }

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
        <h3 className="rt-h3"><span className="rt-hic">⭐</span>리뷰 &amp; 찜 분석<span className="badge b-ok">✅ 실측</span></h3>
        <div className="rt-desc">광고주 상품 vs 경쟁 평균 vs 상위 5개 비교</div>

        {/* 리뷰·평점·찜 비교 그룹 막대 차트 (시안 구성) */}
        {(function() {
          var C = window.CHART_COLORS || {};
          var mineRating = (hasHtmlData && html && html.rating != null) ? html.rating : rating.adv;
          var mineWish = (hasHtmlData && html && html.wishCount != null) ? html.wishCount : wishCount.adv;
          var mine = [num(mineReview), num(mineRating) * 100, num(mineWish)];
          var avg = [num(reviewCount.avg), num(rating.avg) * 100, num(wishCount.avg)];
          var top5 = [num(reviewCount.top5), num(rating.top5) * 100, num(wishCount.top5)];
          var anyVal = mine.concat(avg, top5).some(function(v) { return v > 0; });
          if (!anyVal) return null;
          var fmtTip = function(ctx) {
            var raw = ctx.parsed.y;
            var label = ctx.dataset.label + ': ';
            if (ctx.dataIndex === 1) return label + (raw / 100).toFixed(1) + '점';
            return label + (window.chartComma ? window.chartComma(raw) : raw);
          };
          return (
            <div className="chartbox">
              <ChartCanvas
                type="bar"
                height={280}
                data={{
                  labels: ['리뷰 수', '평점(×100)', '찜 수'],
                  datasets: [
                    { label: '내 상품', data: mine, backgroundColor: '#ec4899', borderRadius: 5 },
                    { label: '경쟁 평균', data: avg, backgroundColor: '#94a3b8', borderRadius: 5 },
                    { label: '상위 5', data: top5, backgroundColor: C.IND || '#4f46e5', borderRadius: 5 }
                  ]
                }}
                options={{
                  maintainAspectRatio: false,
                  plugins: {
                    legend: { position: 'bottom' },
                    tooltip: { callbacks: { label: fmtTip } }
                  },
                  scales: { y: { type: 'logarithmic', ticks: { callback: function(v) { return window.chartComma ? window.chartComma(v) : v; } } } }
                }}
              />
            </div>
          );
        })()}

        {/* 노트 (시안 톤) */}
        {noteText && <div className="note">{noteText}</div>}
        </div>
      </div>
    </div>
  );
};
