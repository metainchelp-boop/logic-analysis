window.SeoDetailSection = function SeoDetailSection(props) {
  if (!props?.data) return null;
  const { relevance, trustworthy, popularity } = props.data;

  if (!relevance || !trustworthy || !popularity) return null;

  var categories = [
    { title: '적합도', icon: '🎯', data: relevance, gradient: 'linear-gradient(135deg, #fef3c7, #fde68a)', borderColor: '#fcd34d', color: '#92400e', bg: '#fffbeb' },
    { title: '신뢰도', icon: '🛡️', data: trustworthy, gradient: 'linear-gradient(135deg, #dbeafe, #bfdbfe)', borderColor: '#93c5fd', color: '#1e40af', bg: '#eff6ff' },
    { title: '인기도', icon: '🔥', data: popularity, gradient: 'linear-gradient(135deg, #fce7f3, #fbcfe8)', borderColor: '#f472b6', color: '#9d174d', bg: '#fdf2f8' }
  ];

  var getScoreColor = function(s) { return s >= 70 ? '#10b981' : s >= 40 ? '#f59e0b' : '#ef4444'; };

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: '#f0fdf4' }}>🔧</span>
          SEO 종합 진단
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">적합도, 신뢰도, 인기도 3가지 관점에서 광고주 상품의 종합 평가</p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20, marginTop: 20 }}>
          {categories.map(function(cat, catIdx) {
            return (
              <div key={catIdx} className="card" style={{
                padding: 0, overflow: 'hidden', borderRadius: 16,
                border: '2px solid ' + cat.borderColor
              }}>
                {/* 카드 헤더 */}
                <div style={{
                  background: cat.gradient, padding: '18px 20px',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 18 }}>{cat.icon}</span>
                    <span style={{ fontSize: 14, fontWeight: 700, color: cat.color }}>{cat.title}</span>
                  </div>
                  <div style={{
                    width: 48, height: 48, borderRadius: '50%',
                    background: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 18, fontWeight: 800, color: getScoreColor(cat.data.score),
                    boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                  }}>
                    {cat.data.score}
                  </div>
                </div>

                {/* 체크리스트 */}
                <div style={{ padding: '16px 20px' }}>
                  {cat.data.items && cat.data.items.map(function(item, idx) {
                    return (
                      <div key={idx} style={{
                        display: 'flex', alignItems: 'flex-start', gap: 10,
                        padding: '10px 0',
                        borderBottom: idx < cat.data.items.length - 1 ? '1px solid #f1f5f9' : 'none',
                        fontSize: 13, color: '#334155', lineHeight: 1.6
                      }}>
                        <span style={{
                          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                          width: 22, height: 22, borderRadius: 6, flexShrink: 0, marginTop: 1,
                          background: item.pass ? '#f0fdf4' : '#fef2f2',
                          fontSize: 13
                        }}>
                          {item.pass ? '✅' : '❌'}
                        </span>
                        <span>{item.label}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
