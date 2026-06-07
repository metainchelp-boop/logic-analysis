/* SummaryCardsSection — 종합 요약 (v6.1 미리보기 디자인: 한 카드 + ✅배지 KPI) */
window.SummaryCardsSection = function SummaryCardsSection(props) {
  if (!props?.data) return null;
  const { totalVolume, productCount, goldenCount, compLevel } = props.data;

  var kpis = [
    { label: '월간 검색량', value: totalVolume, unit: '회/월', badge: 'b-ok', badgeText: '✅ 실측' },
    { label: '등록 상품수', value: productCount, unit: '개', badge: 'b-ok', badgeText: '✅ 실측' },
    { label: '골든 키워드', value: goldenCount + '개', unit: '발견', badge: 'b-est', badgeText: '≈ 추정' },
    { label: '경쟁강도', value: compLevel || '-', unit: '', badge: 'b-est', badgeText: '≈ 추정' }
  ];

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card">
          <h3 className="rt-h3">
            <span className="rt-hic">🎯</span>
            종합 요약
          </h3>
          <div className="rt-desc">핵심 지표를 한눈에 확인하세요</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
            {kpis.map(function(c, i) {
              return (
                <div key={i} className="rt-kpi">
                  <div className="rt-kpi-k">
                    {c.label}
                    <span className={'badge ' + c.badge} style={{ marginLeft: 6 }}>{c.badgeText}</span>
                  </div>
                  <div className="rt-kpi-v">
                    {c.value}{c.unit && <small>{c.unit}</small>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
