/* DatalabSeasonSection — 시즌별 수요 예측 (v6) */
window.DatalabSeasonSection = function DatalabSeasonSection(props) {
  if (!props?.data || !props.data.seasons || props.data.seasons.length === 0) return null;
  var d = props.data;
  var seasons = d.seasons;

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
        <h3 className="rt-h3"><span className="rt-hic">🗓️</span>시즌별 수요 예측<span className="badge b-ok">✅ 데이터랩</span></h3>
        <div className="rt-desc">데이터랩 쇼핑인사이트 기반 시즌 분석</div>

        <div className="grid4">
          {seasons.map(function(s, i) {
            var isPeak = s.peakSeason || s.grade === '최성수기';
            return (
              <div key={i} className={isPeak ? 'seasoncard peak' : 'seasoncard'}>
                <div style={{ fontSize: 22 }}>{s.icon}</div>
                <b>{s.name}</b>
                <div className="desc" style={{ margin: '2px 0' }}>{s.period}</div>
                <div style={{ fontWeight: 800 }}>지수 {Math.round(s.index)}{isPeak ? ' 🔥' : ''}</div>
                <div style={{ fontSize: 11, color: isPeak ? '#c2410c' : 'var(--sub)' }}>{s.grade}</div>
              </div>
            );
          })}
        </div>

        {d.insight && (
          <div className="note">
            {d.insight}
          </div>
        )}
        </div>
      </div>
    </div>
  );
};
