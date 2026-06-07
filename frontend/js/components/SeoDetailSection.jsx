window.SeoDetailSection = function SeoDetailSection(props) {
  if (!props?.data) return null;
  const { relevance, trustworthy, popularity } = props.data;

  if (!relevance || !trustworthy || !popularity) return null;

  var categories = [
    { title: '적합도', icon: '🎯', data: relevance, gradient: 'linear-gradient(135deg, #fef3c7, #fde68a)', borderColor: '#fcd34d', color: '#92400e', bg: '#fffbeb' },
    { title: '신뢰도', icon: '🛡️', data: trustworthy, gradient: 'linear-gradient(135deg, #dbeafe, #bfdbfe)', borderColor: '#93c5fd', color: '#1e40af', bg: '#eff6ff' },
    { title: '인기도', icon: '🔥', data: popularity, gradient: 'linear-gradient(135deg, #fce7f3, #fbcfe8)', borderColor: '#f472b6', color: '#9d174d', bg: '#fdf2f8' }
  ];

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
        <h3 className="rt-h3"><span className="rt-hic">🛡️</span>② SEO 적합도 · 신뢰도 · 인기도<span className="badge b-est">≈ 추정</span></h3>
        <div className="rt-desc">적합도, 신뢰도, 인기도 3가지 관점에서 광고주 상품의 종합 평가</div>

        <div className="grid3">
          {categories.map(function(cat, catIdx) {
            return (
              <div key={catIdx} className="sub-card">
                <div className="st">
                  {cat.icon} {cat.title}
                  <span style={{ marginLeft: 'auto', fontWeight: 900 }}>{cat.data.score}</span>
                </div>
                {cat.data.items && cat.data.items.map(function(item, idx) {
                  return (
                    <div key={idx} className="check">
                      {item.pass ? <span className="y">✔</span> : <span className="n">✘</span>}
                      {' '}{item.label}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
        </div>
      </div>
    </div>
  );
};
