/* ── 스타일 상수 (렌더 외부, 한 번만 생성) ── */
var _sesSummaryGrid = { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '24px' };
var _sesSummaryCard = { background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '16px', textAlign: 'center' };
var _sesSummaryCardBlue = { background: 'linear-gradient(135deg, #eff6ff, #dbeafe)', border: '1px solid #93c5fd', borderRadius: '12px', padding: '16px', textAlign: 'center' };
var _sesSummaryCardPurple = { background: 'linear-gradient(135deg, #f5f3ff, #ede9fe)', border: '1px solid #c4b5fd', borderRadius: '12px', padding: '16px', textAlign: 'center' };
var _sesSummaryLabel = { fontSize: '11px', color: '#6b7280', marginBottom: '6px' };
var _sesSummaryValue = { fontSize: '20px', fontWeight: '800', color: '#1e293b' };
var _sesCardGrid = { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' };
var _sesCardBase = { borderRadius: '14px', overflow: 'hidden', border: '1px solid #e5e7eb' };
var _sesHeaderBase = { padding: '16px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' };
var _sesHeaderLabel = { fontSize: '14px', fontWeight: '700', color: '#fff' };
var _sesHeaderBadge = { fontSize: '11px', fontWeight: '600', padding: '3px 10px', borderRadius: '20px', background: 'rgba(255,255,255,0.25)', color: '#fff' };
var _sesHeaderGold = { padding: '16px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(135deg, #f59e0b, #d97706)' };
var _sesHeaderPurple = { padding: '16px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(135deg, #6366f1, #4f46e5)' };
var _sesHeaderGray = { padding: '16px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(135deg, #64748b, #475569)' };
var _sesCardBody = { padding: '18px' };
var _sesMetricRow = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid #f1f5f9' };
var _sesMetricRowLast = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0' };
var _sesMetricLabel = { fontSize: '12px', color: '#6b7280', fontWeight: '500' };
var _sesValGold = { fontSize: '15px', fontWeight: '700', color: '#d97706' };
var _sesValPurple = { fontSize: '15px', fontWeight: '700', color: '#4f46e5' };
var _sesValGray = { fontSize: '15px', fontWeight: '700', color: '#475569' };
var _sesTotalRow = { background: '#f8fafc', borderRadius: '10px', padding: '14px 16px', marginTop: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' };
var _sesTotalLabel = { fontSize: '12px', fontWeight: '700', color: '#475569' };
var _sesTotalValGold = { fontSize: '18px', fontWeight: '800', color: '#d97706' };
var _sesTotalValPurple = { fontSize: '18px', fontWeight: '800', color: '#4f46e5' };
var _sesTotalValGray = { fontSize: '18px', fontWeight: '800', color: '#475569' };

window.SalesEstimationSection = function SalesEstimationSection(props) {
  if (!props?.data) return null;
  const { avgPrice, monthlySearches, estimatedCTR, top10Card, page1Card, page2Card } = props.data;

  if (!top10Card || !page1Card || !page2Card) return null;

  return (
    <div className="section fade-in">
      <div className="container">
        <h2 className="section-title">📈 판매량 추정 & 성장 시뮬레이션</h2>

        {/* 상단 요약 카드 */}
        <div style={_sesSummaryGrid}>
          <div style={_sesSummaryCard}>
            <div style={_sesSummaryLabel}>📦 평균 상품 단가</div>
            <div style={_sesSummaryValue}>{avgPrice}</div>
          </div>
          <div style={_sesSummaryCardBlue}>
            <div style={_sesSummaryLabel}>📊 월간 검색량</div>
            <div style={_sesSummaryValue}>{monthlySearches}회</div>
          </div>
          <div style={_sesSummaryCardPurple}>
            <div style={_sesSummaryLabel}>🎯 예상 전환율</div>
            <div style={_sesSummaryValue}>{estimatedCTR}</div>
          </div>
        </div>

        {/* 3칸 카드 그리드 */}
        <div style={_sesCardGrid}>

          {/* 카드 1: TOP 10 */}
          <div style={_sesCardBase}>
            <div style={_sesHeaderGold}>
              <span style={_sesHeaderLabel}>🏆 TOP 10 (1~10위)</span>
              <span style={_sesHeaderBadge}>핵심 구간</span>
            </div>
            <div style={_sesCardBody}>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>1위 예상 판매</span>
                <span style={_sesValGold}>{fmt(top10Card.rank1Sales)}건</span>
              </div>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>5위 예상 판매</span>
                <span style={_sesValGold}>{fmt(top10Card.rank5Sales)}건</span>
              </div>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>10위 예상 판매</span>
                <span style={_sesValGold}>{fmt(top10Card.rank10Sales)}건</span>
              </div>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>1위 예상 매출</span>
                <span style={_sesValGold}>{top10Card.rank1Revenue}</span>
              </div>
              <div style={_sesMetricRowLast}>
                <span style={_sesMetricLabel}>10위 예상 매출</span>
                <span style={_sesValGold}>{top10Card.rank10Revenue}</span>
              </div>
              <div style={_sesTotalRow}>
                <span style={_sesTotalLabel}>TOP10 합산 매출</span>
                <span style={_sesTotalValGold}>{top10Card.totalRevenue}</span>
              </div>
            </div>
          </div>

          {/* 카드 2: 1페이지 (1~40위) */}
          <div style={_sesCardBase}>
            <div style={_sesHeaderPurple}>
              <span style={_sesHeaderLabel}>📄 1페이지 (1~40위)</span>
              <span style={_sesHeaderBadge}>1페이지</span>
            </div>
            <div style={_sesCardBody}>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>평균 판매량</span>
                <span style={_sesValPurple}>{fmt(page1Card.avgSales)}건/월</span>
              </div>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>총 예상 판매</span>
                <span style={_sesValPurple}>{fmt(page1Card.totalSales)}건/월</span>
              </div>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>최고 매출 (1위)</span>
                <span style={_sesValPurple}>{page1Card.maxRevenue}</span>
              </div>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>최저 매출 (40위)</span>
                <span style={_sesValPurple}>{page1Card.minRevenue}</span>
              </div>
              <div style={_sesMetricRowLast}>
                <span style={_sesMetricLabel}>평균 매출</span>
                <span style={_sesValPurple}>{page1Card.avgRevenue}</span>
              </div>
              <div style={_sesTotalRow}>
                <span style={_sesTotalLabel}>1페이지 합산 매출</span>
                <span style={_sesTotalValPurple}>{page1Card.totalRevenue}</span>
              </div>
            </div>
          </div>

          {/* 카드 3: 2페이지 (41~80위) */}
          <div style={_sesCardBase}>
            <div style={_sesHeaderGray}>
              <span style={_sesHeaderLabel}>📄 2페이지 (41~80위)</span>
              <span style={_sesHeaderBadge}>2페이지</span>
            </div>
            <div style={_sesCardBody}>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>평균 판매량</span>
                <span style={_sesValGray}>{fmt(page2Card.avgSales)}건/월</span>
              </div>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>총 예상 판매</span>
                <span style={_sesValGray}>{fmt(page2Card.totalSales)}건/월</span>
              </div>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>최고 매출 (41위)</span>
                <span style={_sesValGray}>{page2Card.maxRevenue}</span>
              </div>
              <div style={_sesMetricRow}>
                <span style={_sesMetricLabel}>최저 매출 (80위)</span>
                <span style={_sesValGray}>{page2Card.minRevenue}</span>
              </div>
              <div style={_sesMetricRowLast}>
                <span style={_sesMetricLabel}>평균 매출</span>
                <span style={_sesValGray}>{page2Card.avgRevenue}</span>
              </div>
              <div style={_sesTotalRow}>
                <span style={_sesTotalLabel}>2페이지 합산 매출</span>
                <span style={_sesTotalValGray}>{page2Card.totalRevenue}</span>
              </div>
            </div>
          </div>

        </div>

        <div className="market-note" style={{ marginTop: '16px' }}>
          ⚠️ 순위별 클릭률(CTR)을 기반으로 추정한 값이며, 실제 판매량은 상품 경쟁력, 리뷰, 가격 등에 따라 달라질 수 있습니다.
        </div>
      </div>
    </div>
  );
};
