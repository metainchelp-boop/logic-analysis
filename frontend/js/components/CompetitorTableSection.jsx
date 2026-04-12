window.CompetitorTableSection = function CompetitorTableSection(props) {
  if (!props?.data) return null;
  const { competitors, totalProducts } = props.data;

  if (!competitors || competitors.length === 0) return null;

  return (
    <div className="section">
      <h2 className="section-title">📋 경쟁사 비교표 (상위 20개)</h2>

      <div style={{
        backgroundColor: '#fff',
        border: '1px solid #e5e7eb',
        borderRadius: '12px',
        padding: '20px',
        marginTop: '20px',
        overflowX: 'auto'
      }}>
        <table style={{
          width: '100%',
          borderCollapse: 'collapse',
          minWidth: '1200px',
          fontSize: '12px'
        }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #e5e7eb', backgroundColor: '#f9fafb' }}>
              <th style={{
                padding: '12px 8px',
                textAlign: 'center',
                fontWeight: '600',
                color: '#666'
              }}>순위</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'left',
                fontWeight: '600',
                color: '#666'
              }}>상품명</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'left',
                fontWeight: '600',
                color: '#666'
              }}>브랜드</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'right',
                fontWeight: '600',
                color: '#666'
              }}>가격</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'center',
                fontWeight: '600',
                color: '#666'
              }}>리뷰수</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'center',
                fontWeight: '600',
                color: '#666'
              }}>평점</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'center',
                fontWeight: '600',
                color: '#666'
              }}>찜수</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'center',
                fontWeight: '600',
                color: '#666'
              }}>판매실적</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'center',
                fontWeight: '600',
                color: '#666'
              }}>판매처수</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'center',
                fontWeight: '600',
                color: '#666'
              }}>배송</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'center',
                fontWeight: '600',
                color: '#666'
              }}>최신성</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'center',
                fontWeight: '600',
                color: '#666'
              }}>네이버페이</th>
              <th style={{
                padding: '12px 8px',
                textAlign: 'center',
                fontWeight: '600',
                color: '#666'
              }}>종합점수</th>
            </tr>
          </thead>
          <tbody>
            {competitors.map((comp, idx) => (
              <tr
                key={idx}
                style={{
                  borderBottom: '1px solid #e5e7eb',
                  backgroundColor: comp.isAdvertiser ? '#dbeafe' : 'transparent'
                }}
              >
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  color: '#333',
                  fontWeight: comp.isAdvertiser ? '600' : '400'
                }}>
                  {comp.rank}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'left',
                  color: '#333',
                  fontWeight: comp.isAdvertiser ? '600' : '400',
                  maxWidth: '180px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap'
                }}>
                  {comp.name}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'left',
                  color: '#666',
                  fontSize: '11px',
                  maxWidth: '100px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap'
                }}>
                  {comp.brand}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'right',
                  color: '#333',
                  fontWeight: '500'
                }}>
                  {fmt(comp.price)}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  color: '#333'
                }}>
                  {fmt(comp.reviews)}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  color: '#333'
                }}>
                  {comp.rating?.toFixed(2) || '-'}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  color: '#333'
                }}>
                  {fmt(comp.wishes)}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  color: '#333',
                  fontSize: '11px'
                }}>
                  {comp.sales || '-'}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  color: '#333'
                }}>
                  {comp.sellers || '-'}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  color: '#333',
                  fontSize: '11px'
                }}>
                  {comp.shipping || '-'}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  color: '#333',
                  fontSize: '11px'
                }}>
                  {comp.freshness || '-'}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  color: '#333',
                  fontSize: '11px'
                }}>
                  {comp.naverPay ? '✓' : '✗'}
                </td>
                <td style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  color: '#1f2937',
                  fontWeight: '600',
                  backgroundColor: comp.isAdvertiser ? 'rgba(219, 234, 254, 0.5)' : 'transparent'
                }}>
                  {comp.totalScore?.toFixed(1) || '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer Note */}
      {totalProducts !== undefined && (
        <div style={{
          marginTop: '16px',
          fontSize: '12px',
          color: '#666',
          textAlign: 'center',
          paddingTop: '12px',
          borderTop: '1px solid #e5e7eb'
        }}>
          상위 20개 / 전체 <strong>{fmt(totalProducts)}</strong>개
        </div>
      )}

      <style>{`
        @media (max-width: 1200px) {
          table {
            font-size: 11px;
          }
          td, th {
            padding: 10px 6px !important;
          }
        }
      `}</style>
    </div>
  );
};
