window.MarketRevenueSection = function MarketRevenueSection(props) {
  if (!props?.data) return null;
  const { avgPrice, estimatedMonthly, topProducts, conversionRate, calculationMethod } = props.data;

  if (!topProducts || topProducts.length === 0) return null;

  var getRankBadge = function(rank) {
    if (rank === 1) return React.createElement('span', { className: 'rank-badge gold' }, '1');
    if (rank === 2) return React.createElement('span', { className: 'rank-badge silver' }, '2');
    if (rank === 3) return React.createElement('span', { className: 'rank-badge bronze' }, '3');
    return rank;
  };

  return (
    <div className="section fade-in">
      <div className="container">
      <h2 className="section-title">📊 대표 키워드 시장 규모 추정 (상위 20개 상품)</h2>

      {/* Summary Cards */}
      <div className="market-summary-grid">
        <div className="market-summary-card">
          <p className="ms-label">💳 평균 상품 단가</p>
          <p className="ms-value">{avgPrice}</p>
          <p className="ms-sub">상위 40개 평균</p>
        </div>
        <div className="market-summary-card green">
          <p className="ms-label">💰 월간 예상 시장규모</p>
          <p className="ms-value">{estimatedMonthly}</p>
          <p className="ms-sub">상위 20개 상품 추정 매출 합산</p>
        </div>
      </div>

      {/* Rank Revenue Table */}
      <h3 style={{ fontSize: '15px', fontWeight: '700', color: '#1e293b', marginBottom: '12px' }}>🏆 순위별 예상 월 매출</h3>
      <div className="table-wrap" style={{ maxHeight: '520px', overflowY: 'auto', border: '1px solid #e5e7eb', borderRadius: '12px' }}>
        <table>
          <thead>
            <tr>
              <th style={{ textAlign: 'center', width: '50px' }}>순위</th>
              <th style={{ textAlign: 'left' }}>상품명</th>
              <th style={{ textAlign: 'left', width: '90px' }}>판매처</th>
              <th style={{ textAlign: 'right', width: '90px' }}>가격</th>
              <th style={{ textAlign: 'center', width: '60px' }}>CTR</th>
              <th style={{ textAlign: 'right', width: '90px' }}>예상 판매</th>
              <th style={{ textAlign: 'right', width: '120px' }}>예상 월 매출</th>
            </tr>
          </thead>
          <tbody>
            {topProducts.slice(0, 20).map(function(item, idx) {
              return (
                <tr key={idx} className={item.rank <= 3 ? 'rank-highlight' : ''}>
                  <td style={{ textAlign: 'center' }}>{getRankBadge(item.rank)}</td>
                  <td style={{ maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: '500' }}>
                    {item.name}
                  </td>
                  <td style={{ fontSize: '12px', color: '#6b7280' }}>{item.store}</td>
                  <td style={{ textAlign: 'right' }}>{item.price}</td>
                  <td style={{ textAlign: 'center', fontSize: '12px', color: '#6366f1', fontWeight: '600' }}>{item.ctr}</td>
                  <td style={{ textAlign: 'right', color: '#6b7280' }}>{item.estMonthlySales}</td>
                  <td style={{ textAlign: 'right', fontWeight: '700', color: '#4f46e5' }}>{item.estRevenue}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="market-note">
        ※ 산출 근거: 월간 검색량 × 순위별 CTR(클릭률) × 전환율({conversionRate || '3.5%'})로 계산된 추정치입니다. 순위별 CTR은 업계 평균 벤치마크(1위 8%, 5위 3%, 10위 1.5%, 20위 0.8%)를 적용했습니다. 실제 매출은 리뷰 수, 가격, 광고, 시즌 등에 따라 달라질 수 있으며, 참고 지표로 활용해 주세요.
      </div>
      </div>
    </div>
  );
};
