window.MarketRevenueSection = function MarketRevenueSection(props) {
  if (!props?.data) return null;
  const { searchVolume, totalOrders, totalRevenue, avgPrice, rankRevenue } = props.data;

  if (!rankRevenue || rankRevenue.length === 0) return null;

  const getMedalBadge = (rank) => {
    if (rank === 1) return { emoji: '🥇', text: '1위', color: '#ffd700' };
    if (rank === 2) return { emoji: '🥈', text: '2위', color: '#c0c0c0' };
    if (rank === 3) return { emoji: '🥉', text: '3위', color: '#cd7f32' };
    return null;
  };

  return (
    <div className="section">
      <h2 className="section-title">📊 대표 키워드 시장 규모 추정 (상위 40개 상품)</h2>

      {/* Summary Cards */}
      <div className="summary-cards-grid">
        <StatCard
          label="월간 검색량"
          value={fmt(searchVolume)}
          icon="📈"
        />
        <StatCard
          label="총 예상 주문량"
          value={fmt(totalOrders)}
          icon="📦"
        />
        <StatCard
          label="총 예상 매출"
          value={`${fmt(Math.round(totalRevenue))}원`}
          icon="💰"
        />
        <StatCard
          label="평균 상품 단가"
          value={`${fmt(Math.round(avgPrice))}원`}
          icon="💳"
        />
      </div>

      {/* Table Section */}
      <div style={{ marginTop: '32px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '16px', color: '#333' }}>
          🏆 순위별 예상 월 매출
        </h3>

        <div style={{
          overflowX: 'auto',
          backgroundColor: '#fff',
          borderRadius: '8px',
          border: '1px solid #e5e5e5'
        }}>
          <table style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: '13px'
          }}>
            <thead>
              <tr style={{ backgroundColor: '#f8f9fa', borderBottom: '2px solid #e5e5e5' }}>
                <th style={{ padding: '12px', textAlign: 'center', fontWeight: '600', color: '#333', width: '60px' }}>순위</th>
                <th style={{ padding: '12px', textAlign: 'left', fontWeight: '600', color: '#333' }}>상품명</th>
                <th style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: '#333', width: '120px' }}>상품가격</th>
                <th style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: '#333', width: '100px' }}>예상 클릭수</th>
                <th style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: '#333', width: '100px' }}>예상 주문량</th>
                <th style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: '#333', width: '140px' }}>예상 월 매출</th>
              </tr>
            </thead>
            <tbody>
              {rankRevenue.map((item, idx) => {
                const medal = getMedalBadge(item.rank);
                const isAdvertiser = item.isAdvertiser;
                const rowBg = isAdvertiser ? '#f0f7ff' : idx % 2 === 0 ? '#fff' : '#fafafa';
                const rowBorder = isAdvertiser ? '1px solid #b3d9ff' : '1px solid #f0f0f0';

                return (
                  <tr key={idx} style={{
                    backgroundColor: rowBg,
                    borderBottom: rowBorder
                  }}>
                    <td style={{ padding: '12px', textAlign: 'center', color: '#333' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                        {medal && (
                          <span title={medal.text} style={{ fontSize: '16px' }}>{medal.emoji}</span>
                        )}
                        <span>{item.rank}</span>
                      </div>
                    </td>
                    <td style={{ padding: '12px', textAlign: 'left', color: '#333', fontWeight: '500' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span>{item.name}</span>
                        {isAdvertiser && (
                          <span className="badge badge-blue" style={{ fontSize: '11px', padding: '2px 6px' }}>
                            광고주
                          </span>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: '12px', textAlign: 'right', color: '#333' }}>
                      {fmt(Math.round(item.price))}원
                    </td>
                    <td style={{ padding: '12px', textAlign: 'right', color: '#666' }}>
                      {fmt(Math.round(item.clicks))}
                    </td>
                    <td style={{ padding: '12px', textAlign: 'right', color: '#666' }}>
                      {fmt(Math.round(item.orders))}개
                    </td>
                    <td style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: '#1976d2' }}>
                      {fmt(Math.round(item.revenue))}원
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Footer note */}
      <div style={{
        marginTop: '20px',
        padding: '12px',
        backgroundColor: '#fff3cd',
        borderRadius: '4px',
        fontSize: '12px',
        color: '#333',
        lineHeight: '1.5'
      }}>
        <strong>⚠️ 추정 방법론:</strong> 월간 검색량과 검색결과 내 순위를 기반으로 예상 클릭수를 계산하고, 업계 평균 전환율(CTR)을 적용하여 주문량과 매출을 추정했습니다. 실제 수치와 상이할 수 있습니다.
      </div>

      <style>{`
        .summary-cards-grid {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 16px;
          margin-top: 20px;
        }
        @media (max-width: 1024px) {
          .summary-cards-grid {
            grid-template-columns: repeat(2, 1fr);
          }
        }
        @media (max-width: 768px) {
          .summary-cards-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};
