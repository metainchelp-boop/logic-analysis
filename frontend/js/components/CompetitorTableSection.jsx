window.CompetitorTableSection = function CompetitorTableSection(props) {
  if (!props?.data) return null;

  var items = Array.isArray(props.data) ? props.data : (props.data.competitors || []);
  if (items.length === 0) return null;

  var getRankBadge = function(rank) {
    if (rank <= 3) {
      var cls = rank === 1 ? 'gold' : rank === 2 ? 'silver' : 'bronze';
      return React.createElement('span', { className: 'rank-badge ' + cls }, rank);
    }
    return rank;
  };

  var scoreColor = function(s) {
    return s >= 70 ? '#059669' : s >= 40 ? '#d97706' : '#dc2626';
  };
  var scoreBg = function(s) {
    return s >= 70 ? '#ecfdf5' : s >= 40 ? '#fffbeb' : '#fef2f2';
  };

  // 종합점수 존재 여부 확인
  var hasScore = items.some(function(item) { return typeof item.seoScore === 'number'; });

  return (
    <div className="section fade-in">
      <div className="container">
      <h2 className="section-title">📋 경쟁사 비교표 (상위 {items.length}개)</h2>

      {hasScore && (
        <div style={{ marginBottom: 12, padding: '10px 14px', background: 'linear-gradient(135deg, #f0f9ff, #e0f2fe)', borderRadius: 8, border: '1px solid #bae6fd', fontSize: 12, color: '#0369a1', lineHeight: 1.6 }}>
          💡 종합점수가 높을수록 네이버 쇼핑 노출 순위가 높아지는 경향이 있습니다. 상품명·가격·리뷰·판매실적 등 10개 지표를 가중 합산한 점수입니다.
        </div>
      )}

      <div className="table-wrap" style={{ maxHeight: '600px', overflowY: 'auto' }}>
        <table style={{ minWidth: hasScore ? '900px' : '800px' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'center', width: '50px' }}>순위</th>
              {hasScore && <th style={{ textAlign: 'center', width: '70px' }}>종합점수</th>}
              <th style={{ textAlign: 'center', width: '50px' }}>이미지</th>
              <th style={{ textAlign: 'left' }}>상품명</th>
              <th style={{ textAlign: 'left', width: '90px' }}>판매처</th>
              <th style={{ textAlign: 'left', width: '90px' }}>브랜드</th>
              <th style={{ textAlign: 'right', width: '100px' }}>가격</th>
              <th style={{ textAlign: 'left', width: '100px' }}>카테고리</th>
            </tr>
          </thead>
          <tbody>
            {items.map(function(comp, idx) {
              return (
                <tr key={idx} className={comp.rank <= 3 ? 'rank-highlight' : ''}>
                  <td style={{ textAlign: 'center', fontWeight: '600' }}>{getRankBadge(comp.rank)}</td>
                  {hasScore && (
                    <td style={{ textAlign: 'center' }}>
                      <span style={{
                        display: 'inline-block',
                        padding: '3px 10px',
                        borderRadius: 12,
                        fontSize: 12,
                        fontWeight: 700,
                        color: scoreColor(comp.seoScore),
                        background: scoreBg(comp.seoScore),
                        border: '1px solid ' + scoreColor(comp.seoScore) + '33',
                        minWidth: 36
                      }}>
                        {comp.seoScore}
                      </span>
                    </td>
                  )}
                  <td style={{ textAlign: 'center', padding: '8px' }}>
                    {comp.image ? (
                      React.createElement('img', {
                        src: comp.image, alt: '',
                        style: { width: '40px', height: '40px', objectFit: 'cover', borderRadius: '6px' },
                        onError: function(e) { e.target.style.display = 'none'; }
                      })
                    ) : React.createElement('span', { style: { color: '#d1d5db', fontSize: '18px' } }, '📦')}
                  </td>
                  <td style={{ fontWeight: '500', maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {comp.name}
                  </td>
                  <td style={{ fontSize: '12px', color: '#6b7280' }}>{comp.store}</td>
                  <td style={{ fontSize: '12px', color: '#6b7280' }}>{comp.brand}</td>
                  <td style={{ textAlign: 'right', fontWeight: '600', color: '#1f2937' }}>{comp.price}</td>
                  <td style={{ fontSize: '12px', color: '#6b7280' }}>{comp.category}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      </div>
    </div>
  );
};
