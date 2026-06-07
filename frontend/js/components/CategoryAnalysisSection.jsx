window.CategoryAnalysisSection = function CategoryAnalysisSection(props) {
  if (!props?.data) return null;
  const { verdict, mainCategory, categories, categoryLevels } = props.data;

  if (!categories || categories.length === 0) return null;

  var gradients = [
    'linear-gradient(90deg, #4f46e5, #7c3aed)',
    'linear-gradient(90deg, #7c3aed, #a78bfa)',
    'linear-gradient(90deg, #a78bfa, #c4b5fd)',
    'linear-gradient(90deg, #c4b5fd, #ddd6fe)',
    'linear-gradient(90deg, #ddd6fe, #ede9fe)'
  ];

  /* 레벨별 분포 차트 렌더링 */
  var renderLevelChart = function(title, items, color) {
    if (!items || items.length === 0) return null;
    return (
      <div style={{ flex: 1, minWidth: 200 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', marginBottom: 12 }}>{title}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {items.map(function(item, idx) {
            return (
              <div key={idx}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, alignItems: 'center' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#334155' }}>{item.name}</span>
                  <span style={{ fontSize: 11, color: '#64748b' }}>
                    <span style={{ fontWeight: 700, color: color, marginRight: 3 }}>{item.count}개</span>
                    ({item.ratio}%)
                  </span>
                </div>
                <div style={{ height: 6, borderRadius: 6, background: '#f1f5f9', overflow: 'hidden' }}>
                  <div style={{
                    width: item.ratio + '%', height: '100%', borderRadius: 6,
                    background: color, opacity: 1 - idx * 0.15,
                    transition: 'width 0.8s ease'
                  }}></div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
        <h3 className="rt-h3"><span className="rt-hic">🗂️</span>카테고리 등록 분석<span className="badge b-ok">✅ 실측</span></h3>
        <div className="rt-desc">상위 상품들의 카테고리 분포를 파악합니다</div>

        {verdict && (
          <div className="note ok">{verdict}</div>
        )}

        {/* 레벨별 분포 (대/중/소) */}
        {categoryLevels && (categoryLevels.large?.length > 0 || categoryLevels.medium?.length > 0 || categoryLevels.small?.length > 0) && (
          <div className="sub-card">
            <div className="st">레벨별 분포 (1페이지 상품)</div>
            {categoryLevels.large && categoryLevels.large.length > 0 && (
              <div>
                {categoryLevels.large.map(function(item, idx) {
                  return (
                    <div key={idx}>
                      <div style={{ fontSize: 12.5, margin: '6px 0' }}><b>대분류</b> {item.name} {item.ratio}%</div>
                      <div className="track"><i style={{ width: item.ratio + '%' }}></i></div>
                    </div>
                  );
                })}
              </div>
            )}
            {categoryLevels.medium && categoryLevels.medium.length > 0 && (
              <div>
                <div style={{ fontSize: 12.5, margin: '10px 0 6px' }}>
                  <b>중분류</b> {categoryLevels.medium.map(function(item, idx) {
                    return item.name + ' ' + item.ratio + '%' + (idx < categoryLevels.medium.length - 1 ? ' · ' : '');
                  }).join('')}
                </div>
                <div className="track"><i style={{ width: categoryLevels.medium[0].ratio + '%' }}></i></div>
              </div>
            )}
            {categoryLevels.small && categoryLevels.small.length > 0 && (
              <div>
                <div style={{ fontSize: 12.5, margin: '10px 0 6px' }}>
                  <b>소분류</b> {categoryLevels.small.map(function(item, idx) {
                    return item.name + ' ' + item.ratio + '%' + (idx < categoryLevels.small.length - 1 ? ' · ' : '');
                  }).join('')}
                </div>
                <div className="track"><i style={{ width: categoryLevels.small[0].ratio + '%' }}></i></div>
              </div>
            )}
          </div>
        )}

        {/* 전체 경로 분포 */}
        <div style={{
          background: '#fff', borderRadius: 16, padding: 24,
          border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
        }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 20 }}>
            카테고리 전체 경로 분포 (상위 상품 기준)
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
    </div>
  );
};
