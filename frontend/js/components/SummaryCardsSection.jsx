window.SummaryCardsSection = function SummaryCardsSection(props) {
  if (!props?.data) return null;
  const { totalVolume, productCount, goldenCount, compLevel } = props.data;

  var cards = [
    { label: '월간 검색량', value: totalVolume, unit: '회/월', icon: '🔍', color: '#4f46e5', gradBg: 'linear-gradient(135deg, #eef2ff, #dbeafe)' },
    { label: '등록 상품수', value: productCount, unit: '개', icon: '📦', color: '#7c3aed', gradBg: 'linear-gradient(135deg, #f5f3ff, #ede9fe)' },
    { label: '골든 키워드', value: goldenCount + '개', unit: '발견', icon: '💎', color: '#f59e0b', gradBg: 'linear-gradient(135deg, #fffbeb, #fef3c7)' },
    { label: '경쟁강도', value: compLevel || '-', unit: '', icon: '⚡', color: '#ef4444', gradBg: 'linear-gradient(135deg, #fef2f2, #fee2e2)' }
  ];

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: '#eef2ff' }}>📊</span>
          종합 요약
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">핵심 지표를 한눈에 확인하세요</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
          {cards.map(function(c, i) {
            return (
              <div key={i} className="card" style={{
                padding: '24px 20px', textAlign: 'center',
                borderRadius: '16px', transition: 'all 0.2s ease'
              }}>
                <div style={{
                  width: 48, height: 48, borderRadius: 14,
                  background: c.gradBg,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 22, margin: '0 auto 12px'
                }}>{c.icon}</div>
                <div style={{
                  fontSize: 11, fontWeight: 600, color: '#94a3b8',
                  textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8
                }}>{c.label}</div>
                <div style={{
                  fontSize: 28, fontWeight: 800, color: c.color, lineHeight: 1.2
                }}>{c.value}</div>
                {c.unit && <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>{c.unit}</div>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
