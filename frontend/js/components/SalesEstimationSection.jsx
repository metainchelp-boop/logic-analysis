window.SalesEstimationSection = function SalesEstimationSection(props) {
  if (!props?.data) return null;
  const { avgPrice, monthlySearches, estimatedCTR, simulations } = props.data;

  if (!simulations || simulations.length === 0) return null;

  return (
    <div className="section">
      <h2 className="section-title">📈 판매량 추정 & 성장 시뮬레이션</h2>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginTop: '20px', marginBottom: '32px' }}>
        <div style={{ backgroundColor: '#dbeafe', border: '2px solid #93c5fd', borderRadius: '12px', padding: '16px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', fontWeight: '600', color: '#666', marginBottom: '8px' }}>📦 평균 상품 단가</div>
          <div style={{ fontSize: '24px', fontWeight: '700', color: '#1f2937' }}>{avgPrice}</div>
        </div>
        <div style={{ backgroundColor: '#fef3c7', border: '2px solid #fcd34d', borderRadius: '12px', padding: '16px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', fontWeight: '600', color: '#666', marginBottom: '8px' }}>📊 월간 검색량</div>
          <div style={{ fontSize: '24px', fontWeight: '700', color: '#1f2937' }}>{monthlySearches}회</div>
        </div>
        <div style={{ backgroundColor: '#fce7f3', border: '2px solid #f472b6', borderRadius: '12px', padding: '16px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', fontWeight: '600', color: '#666', marginBottom: '8px' }}>🎯 예상 전환율</div>
          <div style={{ fontSize: '24px', fontWeight: '700', color: '#1f2937' }}>{estimatedCTR}</div>
        </div>
      </div>

      <div style={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '12px', padding: '20px', overflowX: 'auto' }}>
        <div style={{ fontSize: '13px', fontWeight: '600', color: '#1f2937', marginBottom: '16px' }}>
          순위별 판매 추정 시뮬레이션
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
              <th style={{ padding: '12px 8px', textAlign: 'center', fontWeight: '600', color: '#666' }}>목표 순위</th>
              <th style={{ padding: '12px 8px', textAlign: 'right', fontWeight: '600', color: '#666' }}>예상 월 판매량</th>
              <th style={{ padding: '12px 8px', textAlign: 'right', fontWeight: '600', color: '#666' }}>예상 월 매출</th>
            </tr>
          </thead>
          <tbody>
            {simulations.map(function(row, idx) {
              return (
                <tr key={idx} style={{ borderBottom: '1px solid #e5e7eb', backgroundColor: idx === 0 ? '#f0f7ff' : 'transparent' }}>
                  <td style={{ padding: '12px 8px', textAlign: 'center', fontWeight: '600', color: '#333' }}>{row.rank}위</td>
                  <td style={{ padding: '12px 8px', textAlign: 'right', color: '#333' }}>{fmt(row.estSales)}건</td>
                  <td style={{ padding: '12px 8px', textAlign: 'right', fontWeight: '600', color: '#1976d2' }}>{row.revenue}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: '16px', padding: '12px', backgroundColor: '#fff3cd', borderRadius: '4px', fontSize: '12px', color: '#333', lineHeight: '1.5' }}>
        <strong>⚠️ 참고:</strong> 순위별 클릭률(CTR)을 기반으로 추정한 값이며, 실제 판매량은 상품 경쟁력, 리뷰, 가격 등에 따라 달라질 수 있습니다.
      </div>
    </div>
  );
};
