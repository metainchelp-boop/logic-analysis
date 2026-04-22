window.AdvertiserInfoCard = function AdvertiserInfoCard(props) {
  if (!props?.data) return null;
  const { adDepth, pcClicks, mobileClicks, compIdx } = props.data;

  var items = [
    { icon: '📊', label: '광고 노출 깊이', value: adDepth || 0, unit: '', color: '#4f46e5' },
    { icon: '💻', label: 'PC 평균 클릭수', value: pcClicks, unit: '회', color: '#7c3aed' },
    { icon: '📱', label: '모바일 평균 클릭수', value: mobileClicks, unit: '회', color: '#f59e0b' },
    { icon: '⚔️', label: '광고 경쟁강도', value: compIdx || '-', unit: '', color: '#10b981' }
  ];

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' }}>📢</span>
          광고 경쟁 정보
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">네이버 광고 입찰 현황을 분석합니다</p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
          {items.map(function(item, idx) {
            return (
              <div key={idx} style={{
                background: '#fff', borderRadius: 16, padding: 24,
                border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                textAlign: 'center'
              }}>
                <div style={{ fontSize: 24, marginBottom: 8 }}>{item.icon}</div>
                <div style={{
                  fontSize: 11, fontWeight: 600, color: '#94a3b8',
                  textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8
                }}>{item.label}</div>
                <div style={{ fontSize: 28, fontWeight: 800, color: item.color }}>{item.value}</div>
                {item.unit && <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>{item.unit}</div>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
