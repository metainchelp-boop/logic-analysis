window.AdvertiserInfoCard = function AdvertiserInfoCard(props) {
  if (!props?.data) return null;
  const { adDepth, pcClicks, mobileClicks, compIdx } = props.data;

  var items = [
    { label: '광고 노출 깊이', value: adDepth || 0, bg: 'linear-gradient(135deg, #f0f9ff, #e0f2fe)', border: '#bae6fd', color: '#0369a1' },
    { label: 'PC 평균 클릭수', value: pcClicks + '회', bg: 'linear-gradient(135deg, #f0fdf4, #dcfce7)', border: '#bbf7d0', color: '#15803d' },
    { label: '모바일 평균 클릭수', value: mobileClicks + '회', bg: 'linear-gradient(135deg, #fff7ed, #ffedd5)', border: '#fed7aa', color: '#c2410c' },
    { label: '광고 경쟁강도', value: compIdx || '-', bg: 'linear-gradient(135deg, #faf5ff, #f3e8ff)', border: '#e9d5ff', color: '#7e22ce' }
  ];

  return (
    <div className="section fade-in">
      <h2 className="section-title">📢 광고 경쟁 정보</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px' }}>
        {items.map(function(item, idx) {
          return (
            <div key={idx} style={{
              background: item.bg, borderRadius: '12px', padding: '20px',
              textAlign: 'center', border: '1px solid ' + item.border,
              transition: 'transform 0.2s'
            }}
            onMouseOver={function(e) { e.currentTarget.style.transform = 'translateY(-2px)'; }}
            onMouseOut={function(e) { e.currentTarget.style.transform = 'translateY(0)'; }}
            >
              <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '8px', fontWeight: '600' }}>{item.label}</div>
              <div style={{ fontSize: '24px', fontWeight: '800', color: item.color }}>{item.value}</div>
            </div>
          );
        })}
      </div>

      <style>{`
        @media (max-width: 480px) {
          .section > div[style*="repeat(2"] {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
};
