window.CompetitorTableSection = function CompetitorTableSection(props) {
  if (!props?.data) return null;

  /* data can be an array directly or { competitors: [...] } */
  var items = Array.isArray(props.data) ? props.data : (props.data.competitors || []);
  if (items.length === 0) return null;

  return (
    <div className="section">
      <h2 className="section-title">📋 경쟁사 비교표 (상위 {items.length}개)</h2>

      <div style={{
        backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '12px',
        padding: '20px', marginTop: '20px', overflowX: 'auto'
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '800px', fontSize: '12px' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #e5e7eb', backgroundColor: '#f9fafb' }}>
              <th style={{ padding: '12px 8px', textAlign: 'center', fontWeight: '600', color: '#666' }}>순위</th>
              <th style={{ padding: '12px 8px', textAlign: 'center', fontWeight: '600', color: '#666', width: '60px' }}>이미지</th>
              <th style={{ padding: '12px 8px', textAlign: 'left', fontWeight: '600', color: '#666' }}>상품명</th>
              <th style={{ padding: '12px 8px', textAlign: 'left', fontWeight: '600', color: '#666' }}>판매처</th>
              <th style={{ padding: '12px 8px', textAlign: 'left', fontWeight: '600', color: '#666' }}>브랜드</th>
              <th style={{ padding: '12px 8px', textAlign: 'right', fontWeight: '600', color: '#666' }}>가격</th>
              <th style={{ padding: '12px 8px', textAlign: 'left', fontWeight: '600', color: '#666' }}>카테고리</th>
            </tr>
          </thead>
          <tbody>
            {items.map(function(comp, idx) {
              return (
                <tr key={idx} style={{ borderBottom: '1px solid #e5e7eb', backgroundColor: idx % 2 === 0 ? '#fff' : '#fafafa' }}>
                  <td style={{ padding: '12px 8px', textAlign: 'center', color: '#333', fontWeight: '600' }}>
                    {comp.rank}
                  </td>
                  <td style={{ padding: '8px', textAlign: 'center' }}>
                    {comp.image ? (
                      <img src={comp.image} alt="" style={{ width: '40px', height: '40px', objectFit: 'cover', borderRadius: '4px' }}
                        onError={function(e) { e.target.style.display='none'; }} />
                    ) : <span style={{ color: '#ccc' }}>📦</span>}
                  </td>
                  <td style={{ padding: '12px 8px', textAlign: 'left', color: '#333', fontWeight: '500', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {comp.name}
                  </td>
                  <td style={{ padding: '12px 8px', textAlign: 'left', color: '#666', fontSize: '11px' }}>{comp.store}</td>
                  <td style={{ padding: '12px 8px', textAlign: 'left', color: '#666', fontSize: '11px' }}>{comp.brand}</td>
                  <td style={{ padding: '12px 8px', textAlign: 'right', color: '#333', fontWeight: '500' }}>{comp.price}</td>
                  <td style={{ padding: '12px 8px', textAlign: 'left', color: '#666', fontSize: '11px' }}>{comp.category}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
