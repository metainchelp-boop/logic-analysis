window.KeywordTagSection = function KeywordTagSection(props) {
  if (!props?.data) return null;
  const { topKeywords, topTags, maxTagCount } = props.data;

  if ((!topKeywords || topKeywords.length === 0) && (!topTags || topTags.length === 0)) {
    return null;
  }

  const keywordMax = topKeywords && topKeywords.length > 0 ? Math.max(...topKeywords.map(k => k.count)) : 1;
  const tagMax = maxTagCount || (topTags && topTags.length > 0 ? Math.max(...topTags.map(t => t.count)) : 1);

  return (
    <div className="section">
      <h2 className="section-title">🔍 키워드 & 태그 분석</h2>

      <div className="keyword-tag-content">
        {/* Left: Top Keywords */}
        {topKeywords && topKeywords.length > 0 && (
          <div className="keyword-column">
            <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '16px', color: '#1976d2', display: 'flex', alignItems: 'center', gap: '6px' }}>
              💬 상품명 주요 키워드 TOP 5
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {topKeywords.map((kw, idx) => {
                const percent = (kw.count / keywordMax) * 100;
                return (
                  <div key={idx}>
                    <div style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      marginBottom: '6px'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          width: '24px',
                          height: '24px',
                          backgroundColor: '#1976d2',
                          color: '#fff',
                          borderRadius: '50%',
                          fontSize: '12px',
                          fontWeight: '600'
                        }}>
                          {idx + 1}
                        </span>
                        <span style={{ fontSize: '13px', fontWeight: '500', color: '#333' }}>
                          {kw.word}
                        </span>
                      </div>
                      <span style={{ fontSize: '12px', color: '#999' }}>
                        {fmt(kw.count)} ({kw.percent}%)
                      </span>
                    </div>
                    <div style={{
                      width: '100%',
                      height: '16px',
                      backgroundColor: '#e3f2fd',
                      borderRadius: '4px',
                      overflow: 'hidden'
                    }}>
                      <div style={{
                        width: `${percent}%`,
                        height: '100%',
                        backgroundColor: '#1976d2',
                        transition: 'width 0.3s ease'
                      }}></div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Right: Top Tags */}
        {topTags && topTags.length > 0 && (
          <div className="tag-column">
            <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '16px', color: '#8b5cf6', display: 'flex', alignItems: 'center', gap: '6px' }}>
              🏷️ 네이버 쇼핑 연관 키워드 TOP 10
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {topTags.map((tag, idx) => {
                const percent = (tag.count / tagMax) * 100;
                return (
                  <div key={idx}>
                    <div style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      marginBottom: '6px'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          width: '24px',
                          height: '24px',
                          backgroundColor: '#8b5cf6',
                          color: '#fff',
                          borderRadius: '50%',
                          fontSize: '12px',
                          fontWeight: '600'
                        }}>
                          {idx + 1}
                        </span>
                        <span style={{ fontSize: '13px', fontWeight: '500', color: '#333' }}>
                          {tag.tag}
                        </span>
                      </div>
                      <span style={{ fontSize: '12px', color: '#999' }}>
                        {fmt(tag.count)}
                      </span>
                    </div>
                    <div style={{
                      width: '100%',
                      height: '16px',
                      backgroundColor: '#f3e5f5',
                      borderRadius: '4px',
                      overflow: 'hidden'
                    }}>
                      <div style={{
                        width: `${percent}%`,
                        height: '100%',
                        backgroundColor: '#8b5cf6',
                        transition: 'width 0.3s ease'
                      }}></div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <style>{`
        .keyword-tag-content {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 32px;
          margin-top: 20px;
        }
        .keyword-column,
        .tag-column {
          min-height: 200px;
        }
        @media (max-width: 768px) {
          .keyword-tag-content {
            grid-template-columns: 1fr;
            gap: 24px;
          }
        }
      `}</style>
    </div>
  );
};
