window.MarketRevenueSection = function MarketRevenueSection(props) {
  if (!props?.data) return null;
  const { avgPrice, estimatedMonthly, topProducts, conversionRate, calculationMethod } = props.data;

  if (!topProducts || topProducts.length === 0) return null;

  /* v5 상단 메트릭 카드 데이터 */
  var summaryCards = [
    { icon: '💰', label: '월간 시장 규모', value: estimatedMonthly || '-', color: '#4f46e5', gradBg: 'linear-gradient(135deg, #eef2ff, #dbeafe)' },
    { icon: '🏷️', label: '평균 판매가', value: avgPrice || '-', color: '#7c3aed', gradBg: 'linear-gradient(135deg, #f5f3ff, #ede9fe)' },
    { icon: '🎯', label: '적용 전환율', value: conversionRate || '3.5%', color: '#f59e0b', gradBg: 'linear-gradient(135deg, #fffbeb, #fef3c7)' }
  ];

  return (
    <div className="section fade-in">
      <div className="container">
      <div className="section-title">
        <span className="icon" style={{ background: '#fef3c7' }}>💰</span>
        시장 규모 & 매출 추정
      </div>
      <div className="section-line"></div>
      <p className="section-subtitle">검색량 × 클릭률 × 전환율 × 평균 단가 기반 추정</p>

      {/* v5 3칼럼 메트릭 카드 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 24 }}>
        {summaryCards.map(function(c, i) {
          return (
            <div key={i} className="card" style={{
              textAlign: 'center', padding: '28px 20px', borderRadius: 16
            }}>
              <div style={{
                width: 48, height: 48, borderRadius: 14,
                background: c.gradBg,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 22, margin: '0 auto 12px'
              }}>{c.icon}</div>
              <div style={{
                fontSize: 11, fontWeight: 600, color: '#94a3b8',
                textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8
              }}>{c.label}</div>
              <div style={{
                fontSize: 32, fontWeight: 800, color: c.color, lineHeight: 1.2
              }}>{c.value}</div>
            </div>
          );
        })}
      </div>

      {/* v5 순위별 매출 테이블 — 그라데이션 헤더 */}
      <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span>🏆</span> 순위별 예상 월 매출
      </div>
      <div className="card" style={{ padding: 0, overflow: 'hidden', borderRadius: 16 }}>
        <div style={{ maxHeight: 1200, overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'linear-gradient(135deg, #4f46e5, #7c3aed)' }}>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center', width: 50 }}>순위</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'left' }}>상품명</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'left', width: 90 }}>판매처</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'right', width: 90 }}>가격</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center', width: 60 }}>CTR</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'right', width: 90 }}>예상 판매</th>
                <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'right', width: 120 }}>예상 월 매출</th>
              </tr>
            </thead>
            <tbody>
              {topProducts.map(function(item, idx) {
                var medalColors = ['#fbbf24', '#94a3b8', '#cd7f32'];
                return (
                  <tr key={idx} style={{ borderBottom: '1px solid #e2e8f0', background: idx % 2 === 0 ? '#fff' : '#f8fafc' }}>
                    <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                      {item.rank <= 3 ? (
                        <span style={{
                          display: 'inline-flex', width: 28, height: 28, borderRadius: '50%',
                          background: medalColors[item.rank - 1], color: '#fff',
                          alignItems: 'center', justifyContent: 'center',
                          fontSize: 13, fontWeight: 800
                        }}>{item.rank}</span>
                      ) : (
                        <span style={{ fontSize: 14, fontWeight: 700, color: '#64748b' }}>{item.rank}</span>
                      )}
                    </td>
                    <td style={{ padding: '14px 16px', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 500, fontSize: 14, color: '#0f172a' }}>
                      {item.name}
                    </td>
                    <td style={{ padding: '14px 16px', fontSize: 12, color: '#6b7280' }}>{item.store}</td>
                    <td style={{ padding: '14px 16px', textAlign: 'right', fontSize: 14, color: '#0f172a' }}>{item.price}</td>
                    <td style={{ padding: '14px 16px', textAlign: 'center', fontSize: 12, color: '#4f46e5', fontWeight: 600 }}>{item.ctr}</td>
                    <td style={{ padding: '14px 16px', textAlign: 'right', color: '#6b7280', fontSize: 14 }}>{item.estMonthlySales}</td>
                    <td style={{ padding: '14px 16px', textAlign: 'right', fontWeight: 700, color: '#4f46e5', fontSize: 14 }}>{item.estRevenue}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{
        marginTop: 16, padding: '12px 16px',
        background: 'linear-gradient(135deg, #f0f9ff, #e0f2fe)',
        borderRadius: 10, border: '1px solid #bae6fd',
        fontSize: 12, color: '#0369a1', lineHeight: 1.7
      }}>
        ※ 산출 근거: 월간 검색량 × 순위별 CTR(클릭률) × 전환율({conversionRate || '3.5%'})로 계산된 추정치입니다. 순위별 CTR은 업계 평균 벤치마크(1위 8%, 5위 3%, 10위 1.5%, 20위 0.8%)를 적용했습니다. 실제 매출은 리뷰 수, 가격, 광고, 시즌 등에 따라 달라질 수 있으며, 참고 지표로 활용해 주세요.
      </div>
      </div>
    </div>
  );
};
