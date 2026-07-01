/* SummaryCardsSection — 종합 요약 (시안: 한 카드 + ✅배지 KPI 4칸) */
window.SummaryCardsSection = function SummaryCardsSection(props) {
  if (!props?.data) return null;
  const { totalVolume, productCount, goldenCount, compLevel, note } = props.data;
  // ★ totalVolume/productCount 는 App.jsx에서 이미 fmt() 적용된 문자열 → 그대로 출력(이중 포맷 NaN 방지)

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card">
          <h3 className="rt-h3"><span className="rt-hic">🎯</span>종합 요약</h3>
          <div className="grid4">
            <div className="kpi"><div className="k">월간 검색량 <span className="badge b-ok">✅</span></div><div className="v">{totalVolume}<small>회/월</small></div></div>
            <div className="kpi"><div className="k">등록 상품수 <span className="badge b-ok">✅</span></div><div className="v">{productCount}<small>개</small></div></div>
            <div className="kpi"><div className="k">골든 키워드 <span className="badge b-ok">✅</span></div><div className="v" style={{ color: (Number(goldenCount) === 0 ? '#f59e0b' : undefined) }}>{goldenCount}<small>{Number(goldenCount) === 0 ? '개 — 롱테일 권장' : '개 발견'}</small></div></div>
            <div className="kpi"><div className="k">경쟁강도 <span className="badge b-ok">✅</span></div><div className="v" style={{ fontSize: '22px' }}>{compLevel || '-'}</div></div>
          </div>
          {note && <div className="note">💡 {note}</div>}
        </div>
      </div>
    </div>
  );
};
