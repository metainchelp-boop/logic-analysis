window.SalesEstimationSection = function SalesEstimationSection(props) {
  if (!props?.data) return null;
  const { avgPrice, monthlySearches, estimatedCTR, simulations } = props.data;

  if (!simulations || simulations.length === 0) return null;

  return (
    <div className="section fade-in">
      <h2 className="section-title">📈 판매량 추정 & 성장 시뮬레이션</h2>

      {/* Summary Cards */}
      <div className="market-summary-grid" style={{ marginBottom: '24px' }}>
        <div className="market-summary-card">
          <p className="ms-label">📦 평균 상품 단가</p>
          <p className="ms-value">{avgPrice}</p>
        </div>
        <div className="market-summary-card orange">
          <p className="ms-label">📊 월간 검색량</p>
          <p className="ms-value">{monthlySearches}회</p>
        </div>
        <div className="market-summary-card purple">
          <p className="ms-label">🎯 예상 전환율</p>
          <p className="ms-value">{estimatedCTR}</p>
        </div>
      </div>

      {/* Simulation Table */}
      <div className="table-wrap">
        <div style={{ padding: '16px 20px 8px', fontSize: '14px', fontWeight: '700', color: '#1f2937' }}>
          순위별 판매 추정 시뮬레이션
        </div>
        <table>
          <thead>
            <tr>
              <th style={{ textAlign: 'center', width: '100px' }}>목표 순위</th>
              <th style={{ textAlign: 'right' }}>예상 월 판매량</th>
              <th style={{ textAlign: 'right' }}>예상 월 매출</th>
            </tr>
          </thead>
          <tbody>
            {simulations.map(function(row, idx) {
              return (
                <tr key={idx} className={idx === 0 ? 'rank-highlight' : ''}>
                  <td style={{ textAlign: 'center', fontWeight: '700' }}>{row.rank}위</td>
                  <td style={{ textAlign: 'right' }}>{fmt(row.estSales)}건</td>
                  <td style={{ textAlign: 'right', fontWeight: '700', color: '#4f46e5' }}>{row.revenue}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="market-note" style={{ marginTop: '12px' }}>
        ⚠️ 순위별 클릭률(CTR)을 기반으로 추정한 값이며, 실제 판매량은 상품 경쟁력, 리뷰, 가격 등에 따라 달라질 수 있습니다.
      </div>
    </div>
  );
};
