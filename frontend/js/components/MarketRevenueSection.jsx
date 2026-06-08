window.MarketRevenueSection = function MarketRevenueSection(props) {
  if (!props?.data) return null;
  const { avgPrice, estimatedMonthly, topProducts, conversionRate, calculationMethod } = props.data;

  if (!topProducts || topProducts.length === 0) return null;

  var C = window.CHART_COLORS || {};
  var parseWon = function(s) { return parseInt(String(s).replace(/[^0-9]/g, ''), 10) || 0; };
  /* 순위별 예상 월 매출 차트용 데이터 (상위 10위, 만원 단위) */
  var revTop = (topProducts || []).slice(0, 10);
  var revLabels = revTop.map(function(it) { return it.rank + '위'; });
  var revValues = revTop.map(function(it) { return Math.round(parseWon(it.estRevenue) / 10000); });
  var hasRevChart = revValues.some(function(v) { return v > 0; });

  return (
    <div className="section fade-in">
      <div className="container">
      <div className="card" style={{ padding: '20px 22px' }}>
      <h3 className="rt-h3"><span className="rt-hic">💰</span>시장 규모 &amp; 매출 추정<span className="badge b-est">≈ 추정</span></h3>
      <div className="rt-desc">검색량 × 클릭률 × 전환율 × 평균 단가 기반 추정</div>

      {/* KPI 3칸: 시안 .grid3 + .kpi 구조 */}
      <div className="grid3">
        <div className="kpi"><div className="k">월간 시장 규모</div><div className="v">{estimatedMonthly || '-'}</div></div>
        <div className="kpi"><div className="k">평균 판매가</div><div className="v">{avgPrice || '-'}</div></div>
        <div className="kpi"><div className="k">적용 전환율</div><div className="v">{conversionRate || '3.0%'}</div></div>
      </div>

      {/* 순위별 예상 월 매출 막대 차트 */}
      {hasRevChart && (
        <div className="chartbox" style={{ marginTop: 14 }}>
          <ChartCanvas
            type="bar"
            height={240}
            data={{
              labels: revLabels,
              datasets: [{
                label: '예상 월 매출(만원)',
                data: revValues,
                backgroundColor: function(ctx) { return ctx.dataIndex < 3 ? C.IND : C.SOFT; },
                borderRadius: 6
              }]
            }}
            options={{
              plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: function(ctx) { return (window.chartComma ? window.chartComma(ctx.parsed.y) : ctx.parsed.y) + '만원'; } } }
              },
              scales: { y: { beginAtZero: true, ticks: { callback: function(v) { return (window.chartComma ? window.chartComma(v) : v) + '만'; } } } }
            }}
          />
        </div>
      )}

      {/* 순위별 매출 표: 10개 높이까지만 보이고 나머지는 스크롤(헤더 고정) */}
      <div className="rt-scroll">
      <table className="rt-table" style={{ marginTop: 0 }}>
        <thead>
          <tr>
            <th>순위</th>
            <th>상품명</th>
            <th style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>CTR</th>
            <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>예상 판매</th>
            <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>예상 월 매출</th>
          </tr>
        </thead>
        <tbody>
          {topProducts.map(function(item, idx) {
            var isMyProduct = item.isMyProduct || false;
            return (
              <tr key={idx} style={isMyProduct ? { background: '#fff7ed' } : {}}>
                <td>{item.rank}</td>
                <td style={{ fontWeight: isMyProduct ? 700 : 400, wordBreak: 'keep-all' }}>{item.name}{isMyProduct ? ' 👈' : ''}</td>
                <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>{item.ctr}</td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{item.estMonthlySales}</td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{item.estRevenue}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>

      <div className="note est">≈ 검색량×순위별 클릭률×전환율 기반 <b>시장 규모 추정</b>(개별 실판매 아님). 보완 후 리뷰증가 기반으로 정밀화.</div>
      </div>
      </div>
    </div>
  );
};
