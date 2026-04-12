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

  return (
    <div className="section fade-in">
      <h2 className="section-title">📋 경쟁사 비교표 (상위 {items.length}개)</h2>

      <div className="table-wrap" style={{ maxHeight: '600px', overflowY: 'auto' }}>
        <table style={{ minWidth: '800px' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'center', width: '50px' }}>순위</th>
              <th style={{ textAlign: 'center', width: '50px' }}>이미지</th>
              <th style={{ textAlign: 'left' }}>상품명</th>
              <th style={{ textAlign: 'left', width: '90px' }}>판매처</th>
              <th style={{ textAlign: 'left', width: '90px' }}>브랜드</th>
              <th style={{ textAlign: 'right', width: '100px' }}>가격</th>
              <th style={{ textAlign: 'left', width: '120px' }}>카테고리</th>
            </tr>
          </thead>
          <tbody>
            {items.map(function(comp, idx) {
              return (
                <tr key={idx} className={comp.rank <= 3 ? 'rank-highlight' : ''}>
                  <td style={{ textAlign: 'center', fontWeight: '600' }}>{getRankBadge(comp.rank)}</td>
                  <td style={{ textAlign: 'center', padding: '8px' }}>
                    {comp.image ? (
                      React.createElement('img', {
                        src: comp.image, alt: '',
                        style: { width: '40px', height: '40px', objectFit: 'cover', borderRadius: '6px' },
                        onError: function(e) { e.target.style.display = 'none'; }
                      })
                    ) : React.createElement('span', { style: { color: '#d1d5db', fontSize: '18px' } }, '📦')}
                  </td>
                  <td style={{ fontWeight: '500', maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
  );
};
