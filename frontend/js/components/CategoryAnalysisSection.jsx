window.CategoryAnalysisSection = function CategoryAnalysisSection(props) {
  if (!props?.data) return null;
  const { verdict, mainCategory, categories } = props.data;

  if (!categories || categories.length === 0) return null;

  return (
    <div className="section">
      <h2 className="section-title">📂 카테고리 등록 분석</h2>

      {verdict && (
        <div style={{
          backgroundColor: '#f0f7ff',
          borderLeft: '4px solid #1976d2',
          padding: '16px',
          borderRadius: '6px',
          marginTop: '16px',
          marginBottom: '24px'
        }}>
          <div style={{ fontSize: '15px', fontWeight: '600', color: '#333', marginBottom: '4px' }}>
            📋 {verdict}
          </div>
          <div style={{ fontSize: '13px', color: '#555' }}>
            주요 카테고리: <strong>{mainCategory}</strong>
          </div>
        </div>
      )}

      <div style={{ marginTop: '20px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '16px', color: '#333' }}>
          카테고리 분포 (상위 40개 상품 기준)
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {categories.map(function(item, idx) {
            return (
              <div key={idx}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '12px' }}>
                  <span style={{ fontWeight: '500', color: '#333' }}>{item.name}</span>
                  <span style={{ color: '#666' }}>{item.count}개 ({item.ratio}%)</span>
                </div>
                <div style={{ width: '100%', height: '12px', backgroundColor: '#e5e5e5', borderRadius: '6px', overflow: 'hidden' }}>
                  <div style={{
                    width: item.ratio + '%',
                    height: '100%',
                    backgroundColor: idx === 0 ? '#1976d2' : idx === 1 ? '#42a5f5' : '#90caf9',
                    transition: 'width 0.3s ease'
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
