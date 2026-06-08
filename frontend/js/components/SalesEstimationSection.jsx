/* SalesEstimationSection — 판매량 추정 & 성장 시뮬레이션 (v5) */
window.SalesEstimationSection = function SalesEstimationSection(props) {
  if (!props?.data) return null;
  const { avgPrice, monthlySearches, estimatedCTR, top10Card, page1Card, page2Card } = props.data;

  if (!top10Card || !page1Card || !page2Card) return null;

  var C = window.CHART_COLORS || {};
  /* 순위별 예상 월 판매량 차트 데이터 */
  var salesBars = [
    { label: '1위', val: Number(top10Card.rank1Sales) || 0 },
    { label: '5위', val: Number(top10Card.rank5Sales) || 0 },
    { label: '10위', val: Number(top10Card.rank10Sales) || 0 }
  ];
  var hasSalesChart = salesBars.some(function(b) { return b.val > 0; });

  /* v5 카드 스타일 */
  var v5Card = { borderRadius: 16, background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' };
  var v5MetricRow = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid #f1f5f9' };
  var v5MetricRowLast = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0' };
  var v5MetricLabel = { fontSize: 12, color: '#64748b', fontWeight: 500 };
  var v5TotalRow = { background: '#f8fafc', borderRadius: 10, padding: '14px 16px', marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' };
  var v5TotalLabel = { fontSize: 12, fontWeight: 700, color: '#64748b' };

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
        <h3 className="rt-h3"><span className="rt-hic">📦</span>판매량 추정 &amp; 성장 시뮬레이션<span className="badge b-est">≈ 추정</span></h3>
        <div className="rt-desc">순위별 예상 판매량과 매출 성장 시나리오</div>

        {/* KPI 3칸 */}
        <div className="grid3" style={{ marginBottom: 16 }}>
          <div className="kpi"><div className="k">평균 상품 단가</div><div className="v">{avgPrice}</div></div>
          <div className="kpi"><div className="k">월간 검색량</div><div className="v">{monthlySearches}</div></div>
          <div className="kpi"><div className="k">예상 전환율</div><div className="v">{estimatedCTR}</div></div>
        </div>

        {/* ★ 리뷰 기반 추정(더 정확) — 실제 리뷰수 기반이라 CTR 추정보다 오차가 작음 */}
        {props.reviewCount != null && props.reviewCount > 0 && (function() {
          var rc = props.reviewCount;
          var rate = 0.116; // 식품 평균 리뷰 작성률
          var cumSales = Math.round(rc / rate);
          var monthly = Math.round(cumSales / 12); // 운영 12개월 가정
          return (
            <div className="note ok" style={{ marginTop: 0, marginBottom: 20 }}>
              <b>🧾 리뷰 기반 추정 (더 정확)</b> — 실제 누적 리뷰 <b>{fmt(rc)}건</b> 기반.
              추정 누적 판매 <b>~{fmt(cumSales)}건</b>, 월 환산 <b>~{fmt(monthly)}건</b>
              <span style={{ color: '#64748b' }}> (작성률 11.6% · 운영 12개월 가정). 아래 순위 기반 시나리오는 참고용입니다.</span>
            </div>
          );
        })()}

        {/* 순위별 예상 월 판매량 막대 차트 */}
        {hasSalesChart && (
          <div className="chartbox" style={{ marginBottom: 20 }}>
            <ChartCanvas
              type="bar"
              height={220}
              data={{
                labels: salesBars.map(function(b) { return b.label; }),
                datasets: [{
                  label: '예상 월 판매(건)',
                  data: salesBars.map(function(b) { return b.val; }),
                  backgroundColor: [C.OK || '#16a34a', C.IND || '#4f46e5', '#cbd5e1'],
                  borderRadius: 6
                }]
              }}
              options={{
                plugins: {
                  legend: { display: false },
                  tooltip: { callbacks: { label: function(ctx) { return (window.chartComma ? window.chartComma(ctx.parsed.y) : ctx.parsed.y) + '건/월'; } } }
                },
                scales: { y: { beginAtZero: true, ticks: { callback: function(v) { return window.chartComma ? window.chartComma(v) : v; } } } }
              }}
            />
          </div>
        )}

        {/* v5 3칸 시나리오 카드 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>

          {/* TOP 10 */}
          <div style={{ ...v5Card, overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(135deg, #f59e0b, #d97706)' }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>🏆 TOP 10 (1~10위)</span>
              <span style={{ padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700, background: 'rgba(255,255,255,0.25)', color: '#fff' }}>핵심 구간</span>
            </div>
            <div style={{ padding: 20 }}>
              <div style={v5MetricRow}><span style={v5MetricLabel}>1위 예상 판매</span><span style={{ fontSize: 13, fontWeight: 700, color: '#d97706' }}>{fmt(top10Card.rank1Sales)}건</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>5위 예상 판매</span><span style={{ fontSize: 13, fontWeight: 700, color: '#d97706' }}>{fmt(top10Card.rank5Sales)}건</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>10위 예상 판매</span><span style={{ fontSize: 13, fontWeight: 700, color: '#d97706' }}>{fmt(top10Card.rank10Sales)}건</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>1위 예상 매출</span><span style={{ fontSize: 13, fontWeight: 700, color: '#d97706' }}>{top10Card.rank1Revenue}</span></div>
              <div style={v5MetricRowLast}><span style={v5MetricLabel}>10위 예상 매출</span><span style={{ fontSize: 13, fontWeight: 700, color: '#d97706' }}>{top10Card.rank10Revenue}</span></div>
              <div style={v5TotalRow}>
                <span style={v5TotalLabel}>TOP10 합산 매출</span>
                <span style={{ fontSize: 15, fontWeight: 800, color: '#d97706' }}>{top10Card.totalRevenue}</span>
              </div>
            </div>
          </div>

          {/* 1페이지 */}
          <div style={{ ...v5Card, overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(135deg, #4f46e5, #7c3aed)' }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>📄 1페이지 (1~40위)</span>
              <span style={{ padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700, background: 'rgba(255,255,255,0.25)', color: '#fff' }}>1페이지</span>
            </div>
            <div style={{ padding: 20 }}>
              <div style={v5MetricRow}><span style={v5MetricLabel}>평균 판매량</span><span style={{ fontSize: 13, fontWeight: 700, color: '#4f46e5' }}>{fmt(page1Card.avgSales)}건/월</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>총 예상 판매</span><span style={{ fontSize: 13, fontWeight: 700, color: '#4f46e5' }}>{fmt(page1Card.totalSales)}건/월</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>최고 매출 (1위)</span><span style={{ fontSize: 13, fontWeight: 700, color: '#4f46e5' }}>{page1Card.maxRevenue}</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>최저 매출 (40위)</span><span style={{ fontSize: 13, fontWeight: 700, color: '#4f46e5' }}>{page1Card.minRevenue}</span></div>
              <div style={v5MetricRowLast}><span style={v5MetricLabel}>평균 매출</span><span style={{ fontSize: 13, fontWeight: 700, color: '#4f46e5' }}>{page1Card.avgRevenue}</span></div>
              <div style={v5TotalRow}>
                <span style={v5TotalLabel}>1페이지 합산 매출</span>
                <span style={{ fontSize: 15, fontWeight: 800, color: '#4f46e5' }}>{page1Card.totalRevenue}</span>
              </div>
            </div>
          </div>

          {/* 2페이지 */}
          <div style={{ ...v5Card, overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(135deg, #64748b, #475569)' }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>📄 2페이지 (41~80위)</span>
              <span style={{ padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700, background: 'rgba(255,255,255,0.25)', color: '#fff' }}>2페이지</span>
            </div>
            <div style={{ padding: 20 }}>
              <div style={v5MetricRow}><span style={v5MetricLabel}>평균 판매량</span><span style={{ fontSize: 13, fontWeight: 700, color: '#475569' }}>{fmt(page2Card.avgSales)}건/월</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>총 예상 판매</span><span style={{ fontSize: 13, fontWeight: 700, color: '#475569' }}>{fmt(page2Card.totalSales)}건/월</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>최고 매출 (41위)</span><span style={{ fontSize: 13, fontWeight: 700, color: '#475569' }}>{page2Card.maxRevenue}</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>최저 매출 (80위)</span><span style={{ fontSize: 13, fontWeight: 700, color: '#475569' }}>{page2Card.minRevenue}</span></div>
              <div style={v5MetricRowLast}><span style={v5MetricLabel}>평균 매출</span><span style={{ fontSize: 13, fontWeight: 700, color: '#475569' }}>{page2Card.avgRevenue}</span></div>
              <div style={v5TotalRow}>
                <span style={v5TotalLabel}>2페이지 합산 매출</span>
                <span style={{ fontSize: 15, fontWeight: 800, color: '#475569' }}>{page2Card.totalRevenue}</span>
              </div>
            </div>
          </div>

        </div>

        <div className="note est">
          ⚠️ 순위별 클릭률(CTR)을 기반으로 추정한 값이며, 실제 판매량은 상품 경쟁력, 리뷰, 가격 등에 따라 달라질 수 있습니다.
        </div>

        {/* 리뷰 증가 기반 추정 sub-card */}
        {props.reviewCount != null && props.reviewCount > 0 && props.productPrice > 0 && (function() {
          var rc = props.reviewCount;
          var price = props.productPrice;
          var reviewRates = [
            { label: '보수(작성률 5%)', rate: 0.05 },
            { label: '평균(11.6%)',      rate: 0.116 },
            { label: '적극(이벤트)',      rate: 0.20 },
          ];
          var periods = [3, 6, 12];

          return (
            <div className="sub-card">
              <div className="st">🧾 리뷰 증가 기반 추정 (작성률 식품 11.6%)</div>
              <table className="rt-table">
                <thead>
                  <tr>
                    <th>가정</th>
                    {periods.map(function(m) { return <th key={m} style={{ textAlign: 'right' }}>{m}개월</th>; })}
                  </tr>
                </thead>
                <tbody>
                  {reviewRates.map(function(rr) {
                    var totalSales = Math.round(rc / rr.rate);
                    return (
                      <tr key={rr.label}>
                        <td>{rr.label}</td>
                        {periods.map(function(m) {
                          return <td key={m} style={{ textAlign: 'right' }}>~{fmt(Math.round(totalSales / 12 * m))}건</td>;
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          );
        })()}
        </div>
      </div>
    </div>
  );
};
