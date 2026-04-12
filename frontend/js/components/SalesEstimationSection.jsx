window.SalesEstimationSection = function SalesEstimationSection(props) {
  if (!props?.data) return null;
  const {
    monthlySales,
    monthlyRevenue,
    top5Ratio,
    simulation,
    reviewBasedSales,
    reviewConsistency,
    commentary
  } = props.data;

  if (!monthlySales && !monthlyRevenue && !top5Ratio) return null;

  const renderMetricCard = (label, emoji, value, unit, bgColor, borderColor) => (
    <div style={{
      backgroundColor: bgColor,
      border: `2px solid ${borderColor}`,
      borderRadius: '12px',
      padding: '16px',
      minHeight: '120px',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center'
    }}>
      <div style={{
        fontSize: '12px',
        fontWeight: '600',
        color: '#666',
        marginBottom: '8px',
        display: 'flex',
        alignItems: 'center',
        gap: '6px'
      }}>
        <span>{emoji}</span>
        <span>{label}</span>
      </div>
      <div style={{
        fontSize: '28px',
        fontWeight: '700',
        color: '#1f2937',
        lineHeight: '1.2'
      }}>
        {fmt(value)}{unit && <span style={{ fontSize: '16px', marginLeft: '4px' }}>{unit}</span>}
      </div>
    </div>
  );

  return (
    <div className="section">
      <h2 className="section-title">📈 판매량 추정 & 성장 시뮬레이션</h2>

      {/* Metric Cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: '20px',
        marginTop: '20px',
        marginBottom: '32px'
      }}>
        {monthlySales !== undefined && renderMetricCard(
          '월 예상 판매량',
          '📦',
          monthlySales,
          '개',
          '#dbeafe',
          '#93c5fd'
        )}
        {monthlyRevenue !== undefined && renderMetricCard(
          '월 예상 매출',
          '💰',
          monthlyRevenue,
          '원',
          '#fef3c7',
          '#fcd34d'
        )}
        {top5Ratio !== undefined && renderMetricCard(
          'TOP5 대비',
          '📊',
          top5Ratio,
          '%',
          '#fce7f3',
          '#f472b6'
        )}
      </div>

      {/* Simulation Table */}
      {simulation && simulation.length > 0 && (
        <div style={{
          backgroundColor: '#fff',
          border: '1px solid #e5e7eb',
          borderRadius: '12px',
          padding: '20px',
          marginBottom: '20px',
          overflowX: 'auto'
        }}>
          <div style={{
            fontSize: '13px',
            fontWeight: '600',
            color: '#1f2937',
            marginBottom: '16px'
          }}>
            순위별 판매 추정 시뮬레이션
          </div>
          <table style={{
            width: '100%',
            borderCollapse: 'collapse',
            minWidth: '600px'
          }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
                <th style={{
                  padding: '12px 8px',
                  textAlign: 'left',
                  fontSize: '12px',
                  fontWeight: '600',
                  color: '#666'
                }}>순위</th>
                <th style={{
                  padding: '12px 8px',
                  textAlign: 'left',
                  fontSize: '12px',
                  fontWeight: '600',
                  color: '#666'
                }}>예상 월 판매량</th>
                <th style={{
                  padding: '12px 8px',
                  textAlign: 'left',
                  fontSize: '12px',
                  fontWeight: '600',
                  color: '#666'
                }}>예상 월 매출</th>
                <th style={{
                  padding: '12px 8px',
                  textAlign: 'right',
                  fontSize: '12px',
                  fontWeight: '600',
                  color: '#666'
                }}>현재 대비</th>
              </tr>
            </thead>
            <tbody>
              {simulation.map((row, idx) => (
                <tr
                  key={idx}
                  style={{
                    borderBottom: '1px solid #e5e7eb',
                    backgroundColor: row.isCurrent ? '#dbeafe' : 'transparent'
                  }}
                >
                  <td style={{
                    padding: '12px 8px',
                    fontSize: '12px',
                    color: '#333',
                    fontWeight: row.isCurrent ? '600' : '400'
                  }}>
                    {row.rank}위
                  </td>
                  <td style={{
                    padding: '12px 8px',
                    fontSize: '12px',
                    color: '#333',
                    fontWeight: row.isCurrent ? '600' : '400'
                  }}>
                    {fmt(row.sales)}개
                  </td>
                  <td style={{
                    padding: '12px 8px',
                    fontSize: '12px',
                    color: '#333',
                    fontWeight: row.isCurrent ? '600' : '400'
                  }}>
                    {fmt(row.revenue)}원
                  </td>
                  <td style={{
                    padding: '12px 8px',
                    textAlign: 'right',
                    fontSize: '12px',
                    fontWeight: '600',
                    color: row.vsCurrentColor === 'green' ? '#16a34a' : row.vsCurrentColor === 'red' ? '#dc2626' : '#666'
                  }}>
                    {row.vsCurrentLabel}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Review-Based Estimation */}
      {reviewBasedSales && (
        <div style={{
          backgroundColor: '#f0fdf4',
          border: '2px solid #86efac',
          borderLeft: '6px solid #16a34a',
          borderRadius: '8px',
          padding: '14px 16px',
          marginBottom: '20px',
          fontSize: '13px',
          color: '#333',
          lineHeight: '1.6'
        }}>
          <strong style={{ display: 'block', marginBottom: '4px', color: '#16a34a' }}>📝 리뷰 기반 판매량 추정</strong>
          <div style={{ marginBottom: '4px' }}>{reviewBasedSales}</div>
          {reviewConsistency && (
            <div style={{ fontSize: '12px', color: '#666', marginTop: '6px' }}>
              <strong>일관성:</strong> {reviewConsistency}
            </div>
          )}
        </div>
      )}

      {/* Commentary */}
      {commentary && (
        <div style={{
          background: 'linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)',
          border: '2px solid #fcd34d',
          borderRadius: '8px',
          padding: '14px 16px',
          fontSize: '13px',
          color: '#333',
          lineHeight: '1.6'
        }}>
          <strong style={{ display: 'block', marginBottom: '6px', color: '#b45309' }}>💡 성장 전략 코멘트</strong>
          {commentary}
        </div>
      )}

      <style>{`
        @media (max-width: 1024px) {
          .sales-metric-grid {
            grid-template-columns: repeat(2, 1fr);
          }
        }
        @media (max-width: 768px) {
          .sales-metric-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};
