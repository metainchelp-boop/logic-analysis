window.CompetitorTableSection = function CompetitorTableSection(props) {
  if (!props?.data) return null;

  var items = Array.isArray(props.data) ? props.data : (props.data.competitors || []);
  if (items.length === 0) return null;

  var hasScore = items.some(function(item) { return typeof item.seoScore === 'number'; });
  var medalColors = ['#fbbf24', '#94a3b8', '#cd7f32'];

  return (
    <div className="section fade-in">
      <div className="container">
      <div className="section-title">
        <span className="icon" style={{ background: '#eef2ff' }}>🏆</span>
        경쟁사 비교표 (상위 {items.length}개)
      </div>
      <div className="section-line"></div>
      <p className="section-subtitle">상위 노출 상품들의 핵심 지표를 비교합니다</p>

      {hasScore && (
        <div style={{
          marginBottom: 16, padding: '14px 18px',
          background: 'linear-gradient(135deg, #f0f9ff, #e0f2fe)',
          borderRadius: 12, border: '1px solid #bae6fd',
          fontSize: 13, color: '#0369a1', lineHeight: 1.7
        }}>
          💡 종합점수가 높을수록 네이버 쇼핑 노출 순위가 높아지는 경향이 있습니다. 상품명·가격·리뷰·판매실적 등 10개 지표를 가중 합산한 점수입니다.
        </div>
      )}

      <div className="card" style={{ padding: 0, overflow: 'hidden', borderRadius: 16 }}>
        <div style={{ maxHeight: 1200, overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: hasScore ? 900 : 800 }}>
            <thead>
              <tr style={{ background: 'linear-gradient(135deg, #4f46e5, #7c3aed)' }}>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center', width: 50 }}>순위</th>
                {hasScore && <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center', width: 70 }}>종합점수</th>}
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center', width: 50 }}>이미지</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'left' }}>상품명</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'left', width: 90 }}>판매처</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'left', width: 90 }}>브랜드</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'right', width: 100 }}>가격</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'left', width: 100 }}>카테고리</th>
              </tr>
            </thead>
            <tbody>
              {items.map(function(comp, idx) {
                return (
                  <tr key={idx} style={{ borderBottom: '1px solid #e2e8f0', background: idx % 2 === 0 ? '#fff' : '#f8fafc' }}>
                    <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                      {comp.rank <= 3 ? (
                        <span style={{
                          display: 'inline-flex', width: 30, height: 30, borderRadius: '50%',
                          background: medalColors[comp.rank - 1], color: '#fff',
                          alignItems: 'center', justifyContent: 'center',
                          fontSize: 14, fontWeight: 800,
                          boxShadow: '0 2px 6px ' + medalColors[comp.rank - 1] + '66'
                        }}>{comp.rank}</span>
                      ) : (
                        <span style={{ fontSize: 14, fontWeight: 700, color: '#64748b' }}>{comp.rank}</span>
                      )}
                    </td>
                    {hasScore && (
                      <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                        <span style={{
                          display: 'inline-block',
                          padding: '4px 12px',
                          borderRadius: 999,
                          fontSize: 13,
                          fontWeight: 700,
                          color: scoreColor(comp.seoScore),
                          background: scoreBg(comp.seoScore),
                          border: '1px solid ' + scoreColor(comp.seoScore) + '33'
                        }}>
                          {comp.seoScore}
                        </span>
                      </td>
                    )}
                    <td style={{ padding: '8px 16px', textAlign: 'center' }}>
                      {comp.image ? (
                        React.createElement('img', {
                          src: comp.image, alt: '',
                          style: { width: 44, height: 44, objectFit: 'cover', borderRadius: 8 },
                          onError: function(e) { e.target.style.display = 'none'; }
                        })
                      ) : React.createElement('span', { style: { color: '#d1d5db', fontSize: 22 } }, '📦')}
                    </td>
                    <td style={{ padding: '14px 16px', fontWeight: 500, fontSize: 14, color: '#0f172a', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {comp.name}
                    </td>
                    <td style={{ padding: '14px 16px', fontSize: 12, color: '#6b7280' }}>{comp.store}</td>
                    <td style={{ padding: '14px 16px', fontSize: 12, color: '#6b7280' }}>{comp.brand}</td>
                    <td style={{ padding: '14px 16px', textAlign: 'right', fontWeight: 600, fontSize: 14, color: '#0f172a' }}>{comp.price}</td>
                    <td style={{ padding: '14px 16px', fontSize: 12, color: '#6b7280' }}>{comp.category}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      </div>
    </div>
  );
};
