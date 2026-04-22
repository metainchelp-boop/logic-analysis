/* DatalabSeasonSection — 시즌별 수요 예측 (v5) */
window.DatalabSeasonSection = function DatalabSeasonSection(props) {
  if (!props?.data || !props.data.seasons || props.data.seasons.length === 0) return null;
  var d = props.data;
  var seasons = d.seasons;

  var seasonBgs = {
    '봄': 'linear-gradient(135deg, #fef3c7, #fff)',
    '여름': 'linear-gradient(135deg, #dcfce7, #fff)',
    '가을': 'linear-gradient(135deg, #fee2e2, #fff)',
    '겨울': 'linear-gradient(135deg, #dbeafe, #fff)',
  };

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #fef3c7, #fde68a)' }}>🌤️</span>
          시즌별 수요 예측
          <span style={{ marginLeft: 8, padding: '3px 10px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: '#10b981', color: '#fff' }}>DATALAB</span>
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">데이터랩 쇼핑인사이트 기반 시즌 분석</p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {seasons.map(function(s, i) {
            return (
              <div key={i} className="card" style={{ padding: '20px 16px', textAlign: 'center', background: seasonBgs[s.name] || '#fff' }}>
                <div style={{ fontSize: 28, marginBottom: 8 }}>{s.icon}</div>
                <div style={{ fontSize: 13, fontWeight: 700, color: s.gradeColor || '#475569', marginBottom: 4 }}>{s.name} 시즌</div>
                <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 12 }}>{s.period}</div>
                <div style={{ fontSize: 28, fontWeight: 800, color: s.gradeColor || '#475569' }}>{Math.round(s.index)}</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>수요 지수</div>
                <div style={{ marginTop: 8, padding: '4px 12px', background: s.gradeBg || '#f1f5f9', borderRadius: 999, display: 'inline-block', fontSize: 11, fontWeight: 700, color: s.gradeColor || '#475569' }}>
                  {s.grade}{s.grade === '최성수기' ? ' 🔥' : ''}
                </div>
              </div>
            );
          })}
        </div>

        {d.insight && (
          <div style={{ marginTop: 16, padding: '12px 16px', background: '#fffbeb', borderRadius: 10, border: '1px solid #fde68a', fontSize: 12, color: '#92400e', lineHeight: 1.7 }}>
            💡 <strong>인사이트:</strong> {d.insight}
          </div>
        )}
      </div>
    </div>
  );
};
