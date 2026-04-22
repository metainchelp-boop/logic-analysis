/* SalesEstimationSection — 판매량 추정 & 성장 시뮬레이션 (v5) */
window.SalesEstimationSection = function SalesEstimationSection(props) {
  if (!props?.data) return null;
  const { avgPrice, monthlySearches, estimatedCTR, top10Card, page1Card, page2Card } = props.data;

  if (!top10Card || !page1Card || !page2Card) return null;

  /* v5 카드 스타일 */
  var v5Card = { borderRadius: 16, background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' };
  var v5MetricRow = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid #f1f5f9' };
  var v5MetricRowLast = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0' };
  var v5MetricLabel = { fontSize: 12, color: '#64748b', fontWeight: 500 };
  var v5TotalRow = { background: '#f8fafc', borderRadius: 10, padding: '14px 16px', marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' };
  var v5TotalLabel = { fontSize: 12, fontWeight: 700, color: '#64748b' };

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' }}>💵</span>
          판매량 추정 &amp; 성장 시뮬레이션
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">순위별 예상 판매량과 매출 성장 시나리오</p>

        {/* v5 상단 요약 MetricCard 3칼럼 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 24 }}>
          <div style={{ ...v5Card, textAlign: 'center', padding: 24 }}>
            <div style={{ fontSize: 18, marginBottom: 8 }}>📦</div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 }}>평균 상품 단가</div>
            <div style={{ fontSize: 24, fontWeight: 800, color: '#0f172a' }}>{avgPrice}</div>
          </div>
          <div style={{ ...v5Card, textAlign: 'center', padding: 24 }}>
            <div style={{ fontSize: 18, marginBottom: 8 }}>📊</div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 }}>월간 검색량</div>
            <div style={{ fontSize: 24, fontWeight: 800, color: '#4f46e5' }}>{monthlySearches}<span style={{ fontSize: 12, color: '#64748b' }}>회</span></div>
          </div>
          <div style={{ ...v5Card, textAlign: 'center', padding: 24 }}>
            <div style={{ fontSize: 18, marginBottom: 8 }}>🎯</div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 }}>예상 전환율</div>
            <div style={{ fontSize: 24, fontWeight: 800, color: '#7c3aed' }}>{estimatedCTR}</div>
          </div>
        </div>

        {/* v5 3칸 시나리오 카드 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>

          {/* TOP 10 */}
          <div style={{ ...v5Card, overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(135deg, #f59e0b, #d97706)' }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>🏆 TOP 10 (1~10위)</span>
              <span style={{ padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700, background: 'rgba(255,255,255,0.25)', color: '#fff' }}>핵심 구간</span>
            </div>
            <div style={{ padding: 20 }}>
              <div style={v5MetricRow}><span style={v5MetricLabel}>1위 예상 판매</span><span style={{ fontSize: 13, fontWeight: 700, color: '#d97706' }}>{fmt(top10Card.rank1Sales)}건</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>5위 예상 판매</span><span style={{ fontSize: 13, fontWeight: 700, color: '#d97706' }}>{fmt(top10Card.rank5Sales)}건</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>10위 예상 판매</span><span style={{ fontSize: 13, fontWeight: 700, color: '#d97706' }}>{fmt(top10Card.rank10Sales)}건</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>1위 예상 매출</span><span style={{ fontSize: 13, fontWeight: 700, color: '#d97706' }}>{top10Card.rank1Revenue}</span></div>
              <div style={v5MetricRowLast}><span style={v5MetricLabel}>10위 예상 매출</span><span style={{ fontSize: 13, fontWeight: 700, color: '#d97706' }}>{top10Card.rank10Revenue}</span></div>
              <div style={v5TotalRow}>
                <span style={v5TotalLabel}>TOP10 합산 매출</span>
                <span style={{ fontSize: 15, fontWeight: 800, color: '#d97706' }}>{top10Card.totalRevenue}</span>
              </div>
            </div>
          </div>

          {/* 1페이지 */}
          <div style={{ ...v5Card, overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(135deg, #4f46e5, #7c3aed)' }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>📄 1페이지 (1~40위)</span>
              <span style={{ padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700, background: 'rgba(255,255,255,0.25)', color: '#fff' }}>1페이지</span>
            </div>
            <div style={{ padding: 20 }}>
              <div style={v5MetricRow}><span style={v5MetricLabel}>평균 판매량</span><span style={{ fontSize: 13, fontWeight: 700, color: '#4f46e5' }}>{fmt(page1Card.avgSales)}건/월</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>총 예상 판매</span><span style={{ fontSize: 13, fontWeight: 700, color: '#4f46e5' }}>{fmt(page1Card.totalSales)}건/월</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>최고 매출 (1위)</span><span style={{ fontSize: 13, fontWeight: 700, color: '#4f46e5' }}>{page1Card.maxRevenue}</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>최저 매출 (40위)</span><span style={{ fontSize: 13, fontWeight: 700, color: '#4f46e5' }}>{page1Card.minRevenue}</span></div>
              <div style={v5MetricRowLast}><span style={v5MetricLabel}>평균 매출</span><span style={{ fontSize: 13, fontWeight: 700, color: '#4f46e5' }}>{page1Card.avgRevenue}</span></div>
              <div style={v5TotalRow}>
                <span style={v5TotalLabel}>1페이지 합산 매출</span>
                <span style={{ fontSize: 15, fontWeight: 800, color: '#4f46e5' }}>{page1Card.totalRevenue}</span>
              </div>
            </div>
          </div>

          {/* 2페이지 */}
          <div style={{ ...v5Card, overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(135deg, #64748b, #475569)' }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>📄 2페이지 (41~80위)</span>
              <span style={{ padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700, background: 'rgba(255,255,255,0.25)', color: '#fff' }}>2페이지</span>
            </div>
            <div style={{ padding: 20 }}>
              <div style={v5MetricRow}><span style={v5MetricLabel}>평균 판매량</span><span style={{ fontSize: 13, fontWeight: 700, color: '#475569' }}>{fmt(page2Card.avgSales)}건/월</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>총 예상 판매</span><span style={{ fontSize: 13, fontWeight: 700, color: '#475569' }}>{fmt(page2Card.totalSales)}건/월</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>최고 매출 (41위)</span><span style={{ fontSize: 13, fontWeight: 700, color: '#475569' }}>{page2Card.maxRevenue}</span></div>
              <div style={v5MetricRow}><span style={v5MetricLabel}>최저 매출 (80위)</span><span style={{ fontSize: 13, fontWeight: 700, color: '#475569' }}>{page2Card.minRevenue}</span></div>
              <div style={v5MetricRowLast}><span style={v5MetricLabel}>평균 매출</span><span style={{ fontSize: 13, fontWeight: 700, color: '#475569' }}>{page2Card.avgRevenue}</span></div>
              <div style={v5TotalRow}>
                <span style={v5TotalLabel}>2페이지 합산 매출</span>
                <span style={{ fontSize: 15, fontWeight: 800, color: '#475569' }}>{page2Card.totalRevenue}</span>
              </div>
            </div>
          </div>

        </div>

        <div style={{
          marginTop: 16, padding: '12px 16px', background: '#f8fafc', borderRadius: 12,
          border: '1px solid #e2e8f0', fontSize: 12, color: '#94a3b8', lineHeight: 1.7, textAlign: 'center'
        }}>
          ⚠️ 순위별 클릭률(CTR)을 기반으로 추정한 값이며, 실제 판매량은 상품 경쟁력, 리뷰, 가격 등에 따라 달라질 수 있습니다.
        </div>

        {/* 리뷰 기반 매출 추정 */}
        {props.reviewCount != null && props.reviewCount > 0 && props.productPrice > 0 && (function() {
          var rc = props.reviewCount;
          var price = props.productPrice;
          var reviewRates = [
            { label: '보수적 (5%)', rate: 0.05 },
            { label: '평균 (3%)', rate: 0.03 },
            { label: '적극적 (2%)', rate: 0.02 },
          ];
          var periods = [
            { label: '3개월', months: 3 },
            { label: '6개월', months: 6 },
            { label: '12개월', months: 12 },
          ];

          return (
            <div style={{ marginTop: 32 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 18 }}>📝</span>
                <span style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>리뷰 기반 매출 추정</span>
                <span style={{ padding: '3px 10px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: '#ecfdf5', color: '#10b981' }}>NEW</span>
              </div>
              <p style={{ fontSize: 12, color: '#64748b', marginBottom: 16, lineHeight: 1.6 }}>
                실제 리뷰 수({fmt(rc)}개)를 기반으로 판매량을 역산합니다. 리뷰 작성률에 따라 추정치가 달라집니다.
              </p>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
                {reviewRates.map(function(rr) {
                  var totalSales = Math.round(rc / rr.rate);
                  return (
                    <div key={rr.label} style={{ ...v5Card, overflow: 'hidden' }}>
                      <div style={{ padding: '14px 20px', background: rr.rate === 0.03 ? 'linear-gradient(135deg, #10b981, #059669)' : '#f8fafc', borderBottom: rr.rate === 0.03 ? 'none' : '1px solid #e2e8f0' }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: rr.rate === 0.03 ? '#fff' : '#475569' }}>
                          {rr.label}
                          {rr.rate === 0.03 && <span style={{ marginLeft: 8, padding: '2px 8px', borderRadius: 999, fontSize: 10, background: 'rgba(255,255,255,0.25)', color: '#fff' }}>추천</span>}
                        </div>
                        <div style={{ fontSize: 11, color: rr.rate === 0.03 ? 'rgba(255,255,255,0.8)' : '#94a3b8', marginTop: 2 }}>
                          구매 {Math.round(1/rr.rate)}명 중 1명이 리뷰 작성
                        </div>
                      </div>
                      <div style={{ padding: '16px 20px' }}>
                        <div style={{ ...v5MetricRow }}>
                          <span style={v5MetricLabel}>추정 총 판매량</span>
                          <span style={{ fontSize: 13, fontWeight: 700, color: '#10b981' }}>{fmt(totalSales)}건</span>
                        </div>
                        <div style={{ ...v5MetricRow }}>
                          <span style={v5MetricLabel}>추정 총 매출</span>
                          <span style={{ fontSize: 13, fontWeight: 700, color: '#10b981' }}>{fmt(totalSales * price)}원</span>
                        </div>
                        {periods.map(function(p, pidx) {
                          var monthlySales = Math.round(totalSales / p.months);
                          var monthlyRev = monthlySales * price;
                          return (
                            <div key={p.months} style={pidx === periods.length - 1 ? v5MetricRowLast : v5MetricRow}>
                              <span style={v5MetricLabel}>{p.label} 기준 월 매출</span>
                              <span style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>{fmt(monthlyRev)}원</span>
                            </div>
                          );
                        })}
                        <div style={v5TotalRow}>
                          <span style={v5TotalLabel}>월 평균 판매 (6개월)</span>
                          <span style={{ fontSize: 15, fontWeight: 800, color: '#10b981' }}>{fmt(Math.round(totalSales / 6))}건</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div style={{
                marginTop: 16, padding: '12px 16px', background: '#ecfdf5', borderRadius: 12,
                border: '1px solid #a7f3d0', fontSize: 12, color: '#065f46', lineHeight: 1.7, textAlign: 'center'
              }}>
                📊 리뷰 기반 추정은 실제 구매 데이터(리뷰)에서 역산하므로 CTR 기반보다 현실에 가깝습니다. 단, 상품 판매 기간에 따라 월 매출은 달라질 수 있습니다.
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
};
