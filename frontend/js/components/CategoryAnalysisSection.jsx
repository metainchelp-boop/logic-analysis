window.CategoryAnalysisSection = function CategoryAnalysisSection(props) {
  if (!props?.data) return null;
  const { verdict, mainCategory, categories } = props.data;

  if (!categories || categories.length === 0) return null;

  var gradients = [
    'linear-gradient(90deg, #4f46e5, #7c3aed)',
    'linear-gradient(90deg, #7c3aed, #a78bfa)',
    'linear-gradient(90deg, #a78bfa, #c4b5fd)',
    'linear-gradient(90deg, #c4b5fd, #ddd6fe)',
    'linear-gradient(90deg, #ddd6fe, #ede9fe)'
  ];

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' }}>📂</span>
          카테고리 등록 분석
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">상위 상품들의 카테고리 분포를 파악합니다</p>

        {verdict && (
          <div style={{
            background: '#fff', borderRadius: 16, padding: 24,
            border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            marginBottom: 20, display: 'flex', alignItems: 'center', gap: 16
          }}>
            <div style={{
              width: 48, height: 48, borderRadius: 14,
              background: 'linear-gradient(135deg, #eef2ff, #dbeafe)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 22, flexShrink: 0
            }}>📋</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 4 }}>{verdict}</div>
              <div style={{ fontSize: 13, color: '#64748b' }}>주요 카테고리: <span style={{ fontWeight: 700, color: '#4f46e5' }}>{mainCategory}</span></div>
            </div>
          </div>
        )}

        <div style={{
          background: '#fff', borderRadius: 16, padding: 24,
          border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
        }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 20 }}>
            카테고리 분포 (상위 40개 상품 기준)
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {categories.map(function(item, idx) {
              var gradient = gradients[Math.min(idx, gradients.length - 1)];
              return (
                <div key={idx}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, fontSize: 13, color: '#0f172a' }}>{item.name}</span>
                    <span style={{ fontSize: 12, color: '#64748b' }}>
                      <span style={{ fontWeight: 700, color: '#4f46e5', marginRight: 4 }}>{item.count}개</span>
                      ({item.ratio}%)
                    </span>
                  </div>
                  <div style={{ height: 10, borderRadius: 10, background: '#f1f5f9', overflow: 'hidden' }}>
                    <div style={{
                      width: item.ratio + '%', height: '100%', borderRadius: 10,
                      background: gradient,
                      transition: 'width 0.8s ease'
                    }}></div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
