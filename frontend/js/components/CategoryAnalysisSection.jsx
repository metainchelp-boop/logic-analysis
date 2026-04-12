window.CategoryAnalysisSection = function CategoryAnalysisSection(props) {
  if (!props?.data) return null;
  const { verdict, mainCategory, categories } = props.data;

  if (!categories || categories.length === 0) return null;

  var barColors = ['#4f46e5', '#7c3aed', '#a78bfa', '#c4b5fd', '#ddd6fe'];

  return (
    <div className="section fade-in">
      <h2 className="section-title">📂 카테고리 등록 분석</h2>

      {verdict && (
        <div className="rec-card info" style={{ marginBottom: '20px' }}>
          <div className="rec-top">
            <h4>📋 {verdict}</h4>
          </div>
          <p style={{ margin: 0 }}>주요 카테고리: <strong>{mainCategory}</strong></p>
        </div>
      )}

      <div className="card" style={{ padding: '24px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: '700', color: '#1f2937', marginBottom: '20px' }}>
          카테고리 분포 (상위 40개 상품 기준)
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {categories.map(function(item, idx) {
            var color = barColors[Math.min(idx, barColors.length - 1)];
            return (
              <div key={idx}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '13px' }}>
                  <span style={{ fontWeight: '600', color: '#374151' }}>{item.name}</span>
                  <span style={{ color: '#6b7280', fontWeight: '500' }}>{item.count}개 ({item.ratio}%)</span>
                </div>
                <div className="progress-bar" style={{ height: '10px' }}>
                  <div className="progress-fill" style={{
                    width: item.ratio + '%',
                    background: color
                  }}></div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
