window.MarketRevenueSection = function MarketRevenueSection(props) {
  if (!props?.data) return null;
  const { avgPrice, estimatedMonthly, estimatedMonthlyRange, topProducts, conversionRate, calculationMethod, tolerance } = props.data;

  if (!topProducts || topProducts.length === 0) return null;

  var C = window.CHART_COLORS || {};
  var parseWon = function(s) { return parseInt(String(s).replace(/[^0-9]/g, ''), 10) || 0; };
  /* 순위별 예상 월 매출 차트용 데이터 (상위 10위, 만원 단위) */
  var revTop = (topProducts || []).slice(0, 10);
  var revLabels = revTop.map(function(it) { return it.rank + '위'; });
  var revValues = revTop.map(function(it) { return Math.round(parseWon(it.estRevenue) / 10000); });
  var hasRevChart = revValues.some(function(v) { return v > 0; });

  /* ===== 리뷰 실측 앵커 보정 (v6.7) — 판다랭크류와 같은 '실판매 신호' 기반 =====
   * 자사 상품의 실제 누적 리뷰(HTML 수집)로 월판매를 역산(작성률 11.6%·운영 12개월 가정)하고,
   * 그 값을 앵커로 순위 감쇠 곡선(1/rank^0.7)의 절대 수준을 보정해 상위 40개 시장규모를 재계산.
   * 검색량×CTR 모델은 '검색 유입 기여분'이라 실제 시장(재구매·타키워드·광고 유입 포함)보다
   * 크게 작게 나오던 문제 해결. 실리뷰·순위 없으면 이 블록만 생략(기존 표시 그대로 — 무손실). */
  var _rc = Number(props.reviewCount) || 0;
  var _advRank = Number(props.advRank) || 0;
  var _calib = null;
  if (_rc > 0 && _advRank > 0 && topProducts && topProducts.length >= 3) {
    var _realMonthly = _rc / 0.116 / 12; /* 자사 실측 월판매(추정) — SalesEstimation 배너와 동일 가정 */
    var _decay = function(r) { return 1 / Math.pow(Math.max(1, r), 0.7); };
    var _unit = _realMonthly / _decay(_advRank);
    var _sum = 0;
    topProducts.forEach(function(p) {
      var _pr = Number(p.priceNum) || 0;
      if (_pr > 0) _sum += _unit * _decay(p.rank) * _pr;
    });
    if (_sum > 0) {
      _calib = {
        mid: Math.round(_sum),
        lo: Math.round(_sum * 0.7),
        hi: Math.round(_sum * 1.3),
        realMonthly: Math.round(_realMonthly)
      };
    }
  }

  return (
    <div className="section fade-in">
      <div className="container">
      <div className="card" style={{ padding: '20px 22px' }}>
      <h3 className="rt-h3"><span className="rt-hic">💰</span>시장 규모 &amp; 매출 추정<span className="badge b-est">≈ 추정</span>{tolerance ? <span className="badge b-est" style={{ marginLeft: 6 }}>{tolerance}</span> : null}</h3>
      <div className="rt-desc">{_calib ? '리뷰 실측 앵커 보정(주 수치) + 검색 유입 기여분(참고)' : '검색량 × 클릭률 × 전환율 × 평균 단가 기반 추정'}</div>

      {_calib && (
        <div style={{ marginBottom: 12, padding: '14px 18px', background: '#f0fdf4', border: '1px solid #a7f3d0', borderRadius: 12 }}>
          <div style={{ fontSize: 12.5, fontWeight: 800, color: '#047857', marginBottom: 4 }}>🧾 월간 시장 규모 (리뷰 실측 보정 — 주 수치)</div>
          <div style={{ fontSize: 24, fontWeight: 900, color: '#065f46', letterSpacing: '-0.5px' }}>{fmt(_calib.lo)}~{fmt(_calib.hi)}원</div>
          <div style={{ fontSize: 11.5, color: '#64748b', marginTop: 4, lineHeight: 1.6 }}>
            자사 실제 누적 리뷰 {fmt(_rc)}건 → 월판매 ~{fmt(_calib.realMonthly)}건 역산(작성률 11.6%·운영 12개월 가정)을 기준점으로,
            상위 {topProducts.length}개 상품의 순위·판매가에 적용해 재계산한 값입니다. 재구매·타 키워드·광고 유입이 포함된 실제 시장에 가깝습니다.
          </div>
        </div>
      )}

      {/* KPI 3칸: 시안 .grid3 + .kpi 구조 */}
      <div className="grid3">
        <div className="kpi"><div className="k">{_calib ? '검색 유입 기여분 (참고)' : '월간 시장 규모'}</div><div className="v" style={_calib ? { fontSize: 18, color: '#64748b' } : undefined}>{estimatedMonthlyRange || estimatedMonthly || '-'}</div></div>
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
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{item.estMonthlySalesRange || item.estMonthlySales}</td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{item.estRevenueRange || item.estRevenue}</td>
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
