window.MarketRevenueSection = function MarketRevenueSection(props) {
  if (!props?.data) return null;
  const { avgPrice, estimatedMonthly, topProducts } = props.data;

  if (!topProducts || topProducts.length === 0) return null;

  return (
    <div className="section">
      <h2 className="section-title">📊 대표 키워드 시장 규모 추정 (상위 40개 상품)</h2>

      <div className="summary-cards-grid">
        <StatCard label="평균 상품 단가" value={avgPrice} icon="💳" />
        <StatCard label="월간 예상 시장규모" value={estimatedMonthly} icon="💰" />
      </div>

      <div style={{ marginTop: '32px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '16px', color: '#333' }}>
          🏆 순위별 예상 월 매출
        </h3>
        <div style={{ overflowX: 'auto', backgroundColor: '#fff', borderRadius: '8px', border: '1px solid #e5e5e5' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ backgroundColor: '#f8f9fa', borderBottom: '2px solid #e5e5e5' }}>
                <th style={{ padding: '12px', textAlign: 'center', fontWeight: '600', color: '#333', width: '60px' }}>순위</th>
                <th style={{ padding: '12px', textAlign: 'left', fontWeight: '600', color: '#333' }}>상품명</th>
                <th style={{ padding: '12px', textAlign: 'left', fontWeight: '600', color: '#333', width: '100px' }}>판매처</th>
                <th style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: '#333', width: '120px' }}>가격</th>
                <th style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: '#333', width: '100px' }}>예상 판매</th>
                <th style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: '#333', width: '140px' }}>예상 월 매출</th>
              </tr>
            </thead>
            <tbody>
              {topProducts.slice(0, 20).map(function(item, idx) {
                var medal = item.rank <= 3 ? ['🥇','🥈','🥉'][item.rank - 1] : '';
                return (
                  <tr key={idx} style={{ backgroundColor: idx % 2 === 0 ? '#fff' : '#fafafa', borderBottom: '1px solid #f0f0f0' }}>
                    <td style={{ padding: '12px', textAlign: 'center', color: '#333' }}>
                      {medal && <span style={{ marginRight: '4px' }}>{medal}</span>}{item.rank}
                    </td>
                    <td style={{ padding: '12px', textAlign: 'left', color: '#333', fontWeight: '500', maxWidth: '250px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.name}
                    </td>
                    <td style={{ padding: '12px', textAlign: 'left', color: '#666', fontSize: '12px' }}>{item.store}</td>
                    <td style={{ padding: '12px', textAlign: 'right', color: '#333' }}>{item.price}</td>
                    <td style={{ padding: '12px', textAlign: 'right', color: '#666' }}>{item.estMonthlySales}</td>
                    <td style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: '#1976d2' }}>{item.estRevenue}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ marginTop: '20px', padding: '12px', backgroundColor: '#fff3cd', borderRadius: '4px', fontSize: '12px', color: '#333', lineHeight: '1.5' }}>
        <strong>⚠️ 추정 방법론:</strong> 월간 검색량과 순위를 기반으로 예상 클릭수를 계산하고, 업계 평균 전환율을 적용하여 매출을 추정했습니다.
      </div>

      <style>{`
        .summary-cards-grid {
          display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-top: 20px;
        }
        @media (max-width: 768px) {
          .summary-cards-grid { grid-template-columns: 1fr; }
        }
      `}</style>
    </div>
  );
};
