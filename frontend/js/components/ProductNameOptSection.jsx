window.ProductNameOptSection = function ProductNameOptSection(props) {
  if (!props?.data) return null;
  const { currentName, issues, suggestedName, marketerComment } = props.data;

  if (!currentName) return null;

  const cardBase = {
    background: '#fff',
    borderRadius: 16,
    padding: 24,
    border: '1px solid #e2e8f0',
    boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
    marginBottom: 20
  };

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' }}>✏️</span>
          상품명 SEO 최적화
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">키워드 배치와 가독성을 개선합니다</p>

        {/* Current Product Name */}
        <div style={cardBase}>
          <div style={{
            fontSize: 11,
            fontWeight: 600,
            color: '#94a3b8',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            marginBottom: 10
          }}>
            현재 상품명
          </div>
          <div style={{
            background: '#f8fafc',
            border: '1px solid #e2e8f0',
            borderRadius: 12,
            padding: '14px 16px',
            fontSize: 15,
            color: '#0f172a',
            wordBreak: 'break-word',
            lineHeight: 1.6
          }}>
            {currentName}
          </div>
        </div>

        {/* Issues Checklist */}
        {issues && issues.length > 0 && (
          <div style={cardBase}>
            <div style={{
              fontSize: 11,
              fontWeight: 600,
              color: '#94a3b8',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              marginBottom: 14
            }}>
              개선 항목 체크리스트
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {issues.map((item, idx) => (
                <div key={idx} style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 12,
                  padding: '12px 14px',
                  background: item.pass ? '#f0fdf4' : '#fef2f2',
                  borderRadius: 12,
                  border: item.pass ? '1px solid #bbf7d0' : '1px solid #fecaca'
                }}>
                  <span style={{
                    fontSize: 18,
                    lineHeight: '20px',
                    flexShrink: 0
                  }}>
                    {item.pass ? '✅' : '❌'}
                  </span>
                  <span style={{
                    fontSize: 13,
                    color: '#0f172a',
                    lineHeight: 1.5
                  }}>{item.text}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Suggested Product Name */}
        {suggestedName && (
          <div style={{
            ...cardBase,
            background: 'linear-gradient(135deg, #f0fdf4, #ecfdf5)',
            border: '1px solid #bbf7d0'
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 12
            }}>
              <span style={{
                padding: '4px 12px',
                borderRadius: 999,
                fontSize: 12,
                fontWeight: 700,
                background: '#10b981',
                color: '#fff'
              }}>추천</span>
              <span style={{
                fontSize: 11,
                fontWeight: 600,
                color: '#10b981',
                textTransform: 'uppercase',
                letterSpacing: '0.05em'
              }}>제안 상품명</span>
            </div>
            <div style={{
              background: '#fff',
              border: '1px solid #bbf7d0',
              borderRadius: 12,
              padding: '14px 16px',
              fontSize: 15,
              color: '#0f172a',
              wordBreak: 'break-word',
              lineHeight: 1.6,
              fontWeight: 600
            }}>
              {suggestedName}
            </div>
          </div>
        )}

        {/* Marketer Comment */}
        {marketerComment && (
          <div style={{
            ...cardBase,
            background: 'linear-gradient(135deg, #eef2ff, #e0f2fe)',
            border: '1px solid #bfdbfe',
            marginBottom: 0
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 12
            }}>
              <span style={{
                padding: '4px 12px',
                borderRadius: 999,
                fontSize: 12,
                fontWeight: 700,
                background: '#4f46e5',
                color: '#fff'
              }}>AI</span>
              <span style={{
                fontSize: 11,
                fontWeight: 600,
                color: '#4f46e5',
                textTransform: 'uppercase',
                letterSpacing: '0.05em'
              }}>마케터 코멘트</span>
            </div>
            <div style={{
              fontSize: 13,
              color: '#0f172a',
              lineHeight: 1.7
            }}>
              {marketerComment}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
