window.CategoryAnalysisSection = function CategoryAnalysisSection(props) {
  if (!props?.data) return null;
  const { verdictStatus, verdictIcon, verdictTitle, verdictDesc, verdictBg, verdictBorder, advCategories, compCategories, distribution } = props.data;

  if (!advCategories || !compCategories) return null;

  return (
    <div className="section">
      <h2 className="section-title">📂 카테고리 등록 분석</h2>

      {/* Verdict Banner */}
      {verdictStatus && (
        <div style={{
          backgroundColor: verdictBg,
          borderLeft: `4px solid ${verdictBorder}`,
          padding: '16px',
          borderRadius: '6px',
          marginTop: '16px',
          marginBottom: '24px'
        }}>
          <div style={{ fontSize: '16px', fontWeight: '600', color: '#333', marginBottom: '4px' }}>
            {verdictIcon} {verdictTitle}
          </div>
          <div style={{ fontSize: '13px', color: '#555', lineHeight: '1.5' }}>
            {verdictDesc}
          </div>
        </div>
      )}

      {/* Two-Column Categories */}
      <div className="category-columns">
        {/* Advertiser Categories */}
        <div className="category-column">
          <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '16px', color: '#1976d2', display: 'flex', alignItems: 'center', gap: '6px' }}>
            🏢 광고주 등록 카테고리
          </h3>
          <div style={{ backgroundColor: '#f0f7ff', borderRadius: '6px', padding: '12px' }}>
            {advCategories.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {advCategories.map((cat, idx) => (
                  <div key={idx} style={{
                    padding: '8px 12px',
                    backgroundColor: '#fff',
                    borderRadius: '4px',
                    fontSize: '13px',
                    color: '#333',
                    border: '1px solid #b3d9ff',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    <span style={{ color: '#1976d2', fontWeight: '600' }}>
                      {cat.level === 1 ? '▸' : cat.level === 2 ? '▪' : '◦'}
                    </span>
                    <span>{cat.name}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: '16px', textAlign: 'center', color: '#999', fontSize: '12px' }}>
                등록된 카테고리 없음
              </div>
            )}
          </div>
        </div>

        {/* Competitor Categories */}
        <div className="category-column">
          <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '16px', color: '#d97706', display: 'flex', alignItems: 'center', gap: '6px' }}>
            🏆 1페이지 경쟁사 TOP 카테고리
          </h3>
          <div style={{ backgroundColor: '#fffbeb', borderRadius: '6px', padding: '12px' }}>
            {compCategories.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {compCategories.map((cat, idx) => (
                  <div key={idx} style={{
                    padding: '8px 12px',
                    backgroundColor: '#fff',
                    borderRadius: '4px',
                    fontSize: '13px',
                    color: '#333',
                    border: '1px solid #fcd34d',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    <span style={{ color: '#d97706', fontWeight: '600' }}>
                      {cat.level === 1 ? '▸' : cat.level === 2 ? '▪' : '◦'}
                    </span>
                    <span>{cat.name}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: '16px', textAlign: 'center', color: '#999', fontSize: '12px' }}>
                분석 데이터 없음
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Distribution Section */}
      {distribution && distribution.length > 0 && (
        <div style={{ marginTop: '28px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '16px', color: '#333' }}>
            카테고리 분포 (1페이지 상위 40개)
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {distribution.map((item, idx) => (
              <div key={idx}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '12px' }}>
                  <span style={{ fontWeight: '500', color: '#333' }}>
                    {item.isAdvertiser && '🔴 '}{item.category}
                  </span>
                  <span style={{ color: '#666' }}>
                    {item.count}개 ({item.percent}%)
                  </span>
                </div>
                <div style={{
                  width: '100%',
                  height: '12px',
                  backgroundColor: '#e5e5e5',
                  borderRadius: '6px',
                  overflow: 'hidden'
                }}>
                  <div style={{
                    width: `${item.percent}%`,
                    height: '100%',
                    backgroundColor: item.isAdvertiser ? '#ef4444' : '#3b82f6',
                    transition: 'width 0.3s ease'
                  }}></div>
                </div>
              </div>
            ))}
          </div>

          <div style={{
            marginTop: '16px',
            padding: '12px',
            backgroundColor: '#f8f9fa',
            borderRadius: '4px',
            fontSize: '12px',
            color: '#666'
          }}>
            <span style={{ color: '#ef4444', fontWeight: '600', marginRight: '8px' }}>🔴 광고주</span>
            <span style={{ color: '#3b82f6', fontWeight: '600' }}>🔵 일반</span>
          </div>
        </div>
      )}

      <style>{`
        .category-columns {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 24px;
          margin-top: 20px;
        }
        .category-column {
          min-height: 280px;
        }
        @media (max-width: 768px) {
          .category-columns {
            grid-template-columns: 1fr;
            gap: 20px;
          }
        }
      `}</style>
    </div>
  );
};
