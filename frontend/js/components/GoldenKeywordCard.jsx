window.GoldenKeywordCard = function GoldenKeywordCard(props) {
  // 단일 객체 또는 배열 모두 처리 (data가 없어도 0건 안내를 렌더)
  var raw = props ? props.data : null;
  var items = Array.isArray(raw) ? raw : (raw ? [raw] : []);
  var valid = items.filter(function(item) { return item && item.name && item.score !== undefined; });

  // 0건: 숨기지 않고 대안을 안내 (빈 표/‘없음’이 부정적으로 보이는 문제 개선)
  if (valid.length === 0) {
    return (
      <div className="card">
        <h3 className="rt-h3"><span className="rt-hic">👑</span>골든 키워드 <span className="badge b-ok">✅ 실측</span></h3>
        <div style={{ padding: '22px 20px', textAlign: 'center', background: '#f8fafc', borderRadius: 12, border: '1px dashed #e2e8f0' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#475569', marginBottom: 6 }}>지금은 저경쟁 골든 키워드가 발견되지 않았습니다</div>
          <div style={{ fontSize: 12, color: '#94a3b8', lineHeight: 1.7 }}>
            골든 키워드는 <b>검색량은 있으면서 경쟁강도가 낮은</b> 키워드입니다. 대표키워드 주변에는 없지만,
            아래 <b>연관 키워드</b>의 롱테일(2~3어절 조합)이나 <b>세부 상품 속성 키워드</b>로 진입하면
            낮은 비용으로 상위 노출을 노릴 수 있습니다.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="card golden-card">
      <h3 className="rt-h3"><span className="rt-hic">👑</span>골든 키워드 <span className="badge b-ok">✅ 실측</span></h3>
      <div style={{ fontSize: 11.5, color: '#92400e', margin: '2px 0 10px' }}>
        대표 골든 키워드 기준 — 전체 후보는 연관 키워드의 「황금 키워드」 탭 참조.
        브랜드(상표)형 키워드는 상품명에 직접 쓰지 말고 광고 참고용으로만 활용하세요.
      </div>
      <div className="grid2">
        {valid.map(function(item, idx) {
          const { name, score, volume, competition, ctr, clicks, reason } = item;
          const scorePercent = Math.min(100, (score / 100) * 100);
          return (
            <div key={idx} className="sub-card">
              <div className="st">
                👑 {name}
                <span style={{ marginLeft: 'auto', color: 'var(--est)', fontWeight: 900 }}>점수 {score}/100</span>
              </div>
              <div className="grid2" style={{ gap: '8px', margin: '8px 0' }}>
                <div style={{ fontSize: '12px' }}><span style={{ color: 'var(--sub)' }}>월 검색량</span> <b>{fmt(volume)}</b></div>
                <div style={{ fontSize: '12px' }}><span style={{ color: 'var(--sub)' }}>경쟁강도</span> <b>{competition}</b></div>
                <div style={{ fontSize: '12px' }}><span style={{ color: 'var(--sub)' }}>평균 클릭</span> <b>{typeof ctr === 'number' ? ctr.toFixed(1) : ctr}</b></div>
                <div style={{ fontSize: '12px' }}><span style={{ color: 'var(--sub)' }}>월 클릭수</span> <b>{fmt(clicks)}</b></div>
              </div>
              <div className="track"><i style={{ width: Math.round(scorePercent) + '%' }}></i></div>
              {reason && (
                <div style={{ fontSize: '11.5px', color: 'var(--sub)', marginTop: '6px' }}>{reason}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
