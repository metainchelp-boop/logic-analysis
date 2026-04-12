window.StrategicAnalysisSection = function StrategicAnalysisSection(props) {
  if (!props?.data) return null;
  const { avgTop5Price, priceRange, monthlyVolume, mainBrands, recommendation } = props.data;

  if (!recommendation) return null;

  return (
    <div className="section">
      <h2 className="section-title">🎯 1페이지 진입 전략 비교 분석</h2>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px', marginTop: '20px' }}>
        <div style={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '12px', padding: '20px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: '600', color: '#333', marginBottom: '16px' }}>💰 가격 분석 (상위 5개)</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
              <span style={{ fontSize: '13px', color: '#666' }}>평균 가격</span>
              <span style={{ fontSize: '13px', fontWeight: '600', color: '#333' }}>{avgTop5Price}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
              <span style={{ fontSize: '13px', color: '#666' }}>가격 범위</span>
              <span style={{ fontSize: '13px', fontWeight: '600', color: '#333' }}>{priceRange}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0' }}>
              <span style={{ fontSize: '13px', color: '#666' }}>월간 검색량</span>
              <span style={{ fontSize: '13px', fontWeight: '600', color: '#333' }}>{monthlyVolume}회</span>
            </div>
          </div>
        </div>

        <div style={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '12px', padding: '20px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: '600', color: '#333', marginBottom: '16px' }}>🏢 주요 브랜드/판매처</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {mainBrands.split(', ').map(function(brand, idx) {
              return (
                <span key={idx} style={{
                  padding: '6px 12px', backgroundColor: '#f0f7ff', borderRadius: '20px',
                  fontSize: '12px', color: '#1976d2', border: '1px solid #b3d9ff'
                }}>{brand}</span>
              );
            })}
          </div>
        </div>
      </div>

      <div style={{
        marginTop: '24px', backgroundColor: '#f0fdf4', border: '2px solid #86efac',
        borderLeft: '6px solid #16a34a', borderRadius: '8px', padding: '16px',
        fontSize: '13px', color: '#333', lineHeight: '1.7'
      }}>
        <strong style={{ display: 'block', marginBottom: '8px', color: '#16a34a', fontSize: '14px' }}>
          📌 진입 전략 추천
        </strong>
        {recommendation}
      </div>
    </div>
  );
};
