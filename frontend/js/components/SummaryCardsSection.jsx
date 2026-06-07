/* SummaryCardsSection — 종합 요약 (시안: 한 카드 + ✅배지 KPI 4칸) */
window.SummaryCardsSection = function SummaryCardsSection(props) {
  if (!props?.data) return null;
  const { totalVolume, productCount, goldenCount, compLevel, note } = props.data;
  var n = function(v) { return (typeof fmt === 'function') ? fmt(v) : v; };

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card">
          <h3 className="rt-h3"><span className="rt-hic">🎯</span>종합 요약</h3>
          <div className="grid4">
            <div className="kpi"><div className="k">월간 검색량 <span className="badge b-ok">✅</span></div><div className="v">{n(totalVolume)}<small>회/월</small></div></div>
            <div className="kpi"><div className="k">등록 상품수 <span className="badge b-ok">✅</span></div><div className="v">{n(productCount)}<small>개</small></div></div>
            <div className="kpi"><div className="k">골든 키워드 <span className="badge b-ok">✅</span></div><div className="v">{goldenCount}<small>개 발견</small></div></div>
            <div className="kpi"><div className="k">경쟁강도 <span className="badge b-ok">✅</span></div><div className="v" style={{ fontSize: '22px' }}>{compLevel || '-'}</div></div>
          </div>
          {note && <div className="note">💡 {note}</div>}
        </div>
      </div>
    </div>
  );
};
