window.SummaryCardsSection = function SummaryCardsSection(props) {
  if (!props?.data) return null;
  const { totalVolume, productCount, goldenCount, compLevel } = props.data;

  var cards = [
    { label: '월간 총 검색량', value: totalVolume + '회', icon: '🔍', colorClass: 'indigo', iconBg: 'blue' },
    { label: '네이버 쇼핑 상품 수', value: productCount + '개', icon: '📦', colorClass: 'purple', iconBg: 'purple' },
    { label: '골든 키워드', value: goldenCount + '개 발견', icon: '💎', colorClass: 'orange', iconBg: 'amber' },
    { label: '경쟁강도', value: compLevel || '-', icon: '⚡', colorClass: '', iconBg: 'green' }
  ];

  return (
    <div className="section fade-in">
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
        gap: '16px'
      }}>
        {cards.map(function(c, i) {
          return (
            <div key={i} className="card" style={{ padding: '20px' }}>
              <div className={'stat-icon ' + c.iconBg}>{c.icon}</div>
              <div className="stat-label">{c.label}</div>
              <div className={'stat-value ' + c.colorClass}>{c.value}</div>
            </div>
          );
        })}
      </div>

      <style>{`
        @media (max-width: 900px) {
          .section > div[style*="grid-template-columns: repeat(4"] {
            grid-template-columns: repeat(2, 1fr) !important;
          }
        }
        @media (max-width: 480px) {
          .section > div[style*="grid-template-columns: repeat(4"] {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
};
