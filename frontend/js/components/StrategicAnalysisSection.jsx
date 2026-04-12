window.StrategicAnalysisSection = function StrategicAnalysisSection(props) {
  if (!props?.data) return null;
  const { avgTop5Price, priceRange, monthlyVolume, mainBrands, recommendation } = props.data;

  if (!recommendation) return null;

  return (
    <div className="section fade-in">
      <h2 className="section-title">🎯 1페이지 진입 전략 비교 분석</h2>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '24px' }}>
        {/* Price Analysis Card */}
        <div className="score-card" style={{ borderLeftColor: '#4f46e5' }}>
          <h4 style={{ fontSize: '14px', fontWeight: '700', color: '#1f2937', marginBottom: '16px' }}>💰 가격 분석 (상위 5개)</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
            {[
              { label: '평균 가격', value: avgTop5Price },
              { label: '가격 범위', value: priceRange },
              { label: '월간 검색량', value: monthlyVolume + '회' }
            ].map(function(item, idx) {
              return (
                <div key={idx} style={{
                  display: 'flex', justifyContent: 'space-between',
                  padding: '10px 0',
                  borderBottom: idx < 2 ? '1px solid #f1f5f9' : 'none'
                }}>
                  <span style={{ fontSize: '13px', color: '#6b7280' }}>{item.label}</span>
                  <span style={{ fontSize: '13px', fontWeight: '700', color: '#1f2937' }}>{item.value}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Brand Analysis Card */}
        <div className="score-card" style={{ borderLeftColor: '#7c3aed' }}>
          <h4 style={{ fontSize: '14px', fontWeight: '700', color: '#1f2937', marginBottom: '16px' }}>🏢 주요 브랜드/판매처</h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {mainBrands.split(', ').map(function(brand, idx) {
              return (
                <span key={idx} style={{
                  padding: '6px 14px',
                  background: 'linear-gradient(135deg, #ede9fe, #e0e7ff)',
                  borderRadius: '999px', fontSize: '12px', fontWeight: '600',
                  color: '#4f46e5', border: '1px solid #c7d2fe'
                }}>{brand}</span>
              );
            })}
          </div>
        </div>
      </div>

      {/* Recommendation */}
      <div className="rec-card success">
        <div className="rec-top">
          <h4 style={{ color: '#065f46' }}>📌 진입 전략 추천</h4>
          <span className="type-badge success">전략</span>
        </div>
        <p style={{ lineHeight: '1.7', color: '#374151' }}>{recommendation}</p>
      </div>

      <style>{`
        @media (max-width: 768px) {
          .section > div[style*="1fr 1fr"] { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
};
