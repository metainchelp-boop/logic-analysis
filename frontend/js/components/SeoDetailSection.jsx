window.SeoDetailSection = function SeoDetailSection(props) {
  if (!props?.data) return null;
  const { relevance, trustworthy, popularity } = props.data;

  if (!relevance || !trustworthy || !popularity) return null;

  const renderScoreCard = (title, gradient, borderColor, scoreData) => {
    return (
      <div style={{
        background: gradient,
        border: `2px solid ${borderColor}`,
        borderRadius: '12px',
        padding: '20px',
        minHeight: '300px',
        display: 'flex',
        flexDirection: 'column'
      }}>
        <div style={{
          fontSize: '24px',
          fontWeight: '700',
          color: '#1f2937',
          marginBottom: '16px',
          textAlign: 'center'
        }}>
          {scoreData.score}점
        </div>

        <div style={{
          fontSize: '12px',
          color: '#666',
          marginBottom: '16px',
          paddingBottom: '12px',
          borderBottom: '1px solid rgba(0, 0, 0, 0.1)'
        }}>
          {title}
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {scoreData.items && scoreData.items.map((item, idx) => (
            <div key={idx} style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '8px',
              fontSize: '13px',
              color: '#333'
            }}>
              <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                minWidth: '20px',
                height: '20px',
                marginTop: '2px',
                fontSize: '14px'
              }}>
                {item.pass ? '✅' : '❌'}
              </span>
              <span style={{ lineHeight: '1.5' }}>{item.label}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="section">
      <h2 className="section-title">🔧 SEO 종합 진단</h2>
      <p style={{ color: '#666', fontSize: '13px', marginBottom: '20px' }}>
        적합도, 신뢰도, 인기도 3가지 관점에서 광고주 상품의 종합 평가
      </p>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: '24px',
        marginTop: '20px'
      }}>
        {renderScoreCard(
          '적합도',
          'linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)',
          '#fcd34d',
          relevance
        )}
        {renderScoreCard(
          '신뢰도',
          'linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%)',
          '#93c5fd',
          trustworthy
        )}
        {renderScoreCard(
          '인기도',
          'linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%)',
          '#f472b6',
          popularity
        )}
      </div>

      <style>{`
        @media (max-width: 1024px) {
          .seo-detail-grid {
            grid-template-columns: repeat(2, 1fr);
          }
        }
        @media (max-width: 768px) {
          .seo-detail-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};
