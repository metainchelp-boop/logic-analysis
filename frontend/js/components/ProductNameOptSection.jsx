window.ProductNameOptSection = function ProductNameOptSection(props) {
  if (!props?.data) return null;
  const { currentName, issues, suggestedName, marketerComment } = props.data;

  if (!currentName) return null;

  return (
    <div className="section">
      <h2 className="section-title">✏️ 상품명 SEO 최적화</h2>

      {/* Current Product Name */}
      <div style={{ marginBottom: '20px' }}>
        <div style={{
          fontSize: '12px',
          fontWeight: '600',
          color: '#666',
          marginBottom: '8px'
        }}>
          현재 상품명
        </div>
        <div style={{
          backgroundColor: '#f3f4f6',
          border: '1px solid #d1d5db',
          borderRadius: '8px',
          padding: '14px 16px',
          fontSize: '15px',
          color: '#333',
          wordBreak: 'break-word',
          lineHeight: '1.6'
        }}>
          {currentName}
        </div>
      </div>

      {/* Issues List */}
      {issues && issues.length > 0 && (
        <div style={{ marginBottom: '20px' }}>
          <div style={{
            fontSize: '12px',
            fontWeight: '600',
            color: '#dc2626',
            marginBottom: '8px'
          }}>
            개선 필요 항목
          </div>
          <div style={{
            backgroundColor: '#fee2e2',
            border: '2px solid #fca5a5',
            borderLeft: '6px solid #dc2626',
            borderRadius: '8px',
            padding: '14px 16px'
          }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {issues.map((item, idx) => (
                <div key={idx} style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '10px',
                  fontSize: '13px',
                  color: '#333'
                }}>
                  <span style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minWidth: '20px',
                    height: '20px',
                    marginTop: '1px',
                    fontSize: '16px',
                    flexShrink: 0
                  }}>
                    {item.pass ? '✅' : '⚠️'}
                  </span>
                  <span>{item.text}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Suggested Product Name */}
      {suggestedName && (
        <div style={{ marginBottom: '20px' }}>
          <div style={{
            fontSize: '12px',
            fontWeight: '600',
            color: '#16a34a',
            marginBottom: '8px'
          }}>
            제안 상품명
          </div>
          <div style={{
            backgroundColor: '#dcfce7',
            border: '2px solid #86efac',
            borderLeft: '6px solid #16a34a',
            borderRadius: '8px',
            padding: '14px 16px',
            fontSize: '15px',
            color: '#333',
            wordBreak: 'break-word',
            lineHeight: '1.6',
            fontWeight: '500'
          }}>
            {suggestedName}
          </div>
        </div>
      )}

      {/* Marketer Comment */}
      {marketerComment && (
        <div>
          <div style={{
            fontSize: '12px',
            fontWeight: '600',
            color: '#0284c7',
            marginBottom: '8px'
          }}>
            마케터 코멘트
          </div>
          <div style={{
            backgroundColor: '#e0f2fe',
            border: '2px solid #7dd3fc',
            borderLeft: '6px solid #0284c7',
            borderRadius: '8px',
            padding: '14px 16px',
            fontSize: '13px',
            color: '#333',
            lineHeight: '1.6'
          }}>
            {marketerComment}
          </div>
        </div>
      )}

      <style>{`
        .product-name-section {
          margin-top: 20px;
        }
      `}</style>
    </div>
  );
};
