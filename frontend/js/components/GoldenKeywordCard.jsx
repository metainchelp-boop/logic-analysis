window.GoldenKeywordCard = function GoldenKeywordCard(props) {
  if (!props?.data) return null;

  // 단일 객체 또는 배열 모두 처리
  const items = Array.isArray(props.data) ? props.data : [props.data];

  if (!items.length) return null;

  return (
    <div className="card">
      <h3 className="rt-h3"><span className="rt-hic">👑</span>골든 키워드 <span className="badge b-ok">✅ 실측</span></h3>
      <div className="grid2">
        {items.map(function(item, idx) {
          if (!item || !item.name || item.score === undefined) return null;
          const { name, score, volume, competition, ctr, clicks, reason } = item;
          const scorePercent = Math.min(100, (score / 100) * 100);
          return (
            <div key={idx} className="sub-card">
              <div className="st">
                👑 {name}
                <span style={{ marginLeft: 'auto', color: 'var(--est)', fontWeight: 900 }}>점수 {score}</span>
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
