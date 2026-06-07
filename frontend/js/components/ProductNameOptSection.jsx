window.ProductNameOptSection = function ProductNameOptSection(props) {
  if (!props?.data) return null;
  const { currentName, issues, suggestedName, marketerComment } = props.data;

  if (!currentName) return null;

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
          <h3 className="rt-h3"><span className="rt-hic">✏️</span>상품명 SEO 최적화 <span className="badge b-ai">AI</span></h3>

          {/* Current Product Name */}
          <div style={{ fontSize: 13, marginBottom: 8 }}>
            <span style={{ color: 'var(--sub)' }}>현재</span><br />
            <b>{currentName}</b>
          </div>

          {/* Issues Checklist */}
          {issues && issues.map((item, idx) => (
            <div key={idx} className="check">
              <span className={item.pass ? 'y' : 'n'}>{item.pass ? '✔' : '✘'}</span>
              {' '}{item.text}
            </div>
          ))}

          {/* Suggested Name + Marketer Comment */}
          {suggestedName && (
            <div className="note" style={{ borderLeftColor: '#ec4899' }}>
              <b>✏️ 제안</b><br />
              <b>{suggestedName}</b>
              {marketerComment && <><br />{marketerComment}</>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
