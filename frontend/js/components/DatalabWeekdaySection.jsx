/* DatalabWeekdaySection — 요일별 검색 패턴 (v5) */
window.DatalabWeekdaySection = function DatalabWeekdaySection(props) {
  if (!props?.data || !props.data.days || props.data.days.length === 0) return null;
  var d = props.data;
  var days = d.days;

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #ede9fe, #ddd6fe)' }}>📅</span>
          요일별 검색 패턴
          <span style={{ marginLeft: 8, padding: '3px 10px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: '#10b981', color: '#fff' }}>DATALAB</span>
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">최근 4주 기준 요일별 검색 트렌드</p>

        <div className="card" style={{ padding: 24 }}>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 160, paddingTop: 20 }}>
            {days.map(function(day, i) {
              var isPeak = day.label === d.peakDay;
              var isLow = day.label === d.lowDay;
              var barH = Math.max(day.normalized, 8);
              var barBg = isPeak
                ? 'linear-gradient(180deg, #f472b6, #ec4899)'
                : isLow
                  ? 'linear-gradient(180deg, #94a3b8, #64748b)'
                  : (day.normalized >= 85
                    ? 'linear-gradient(180deg, #a78bfa, #7c3aed)'
                    : 'linear-gradient(180deg, #818cf8, #4f46e5)');

              return (
                <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, height: '100%', justifyContent: 'flex-end' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: isPeak ? '#ec4899' : isLow ? '#64748b' : '#4f46e5' }}>
                    {Math.round(day.normalized)}
                  </div>
                  <div style={{ width: '100%', height: barH + '%', borderRadius: '8px 8px 4px 4px', background: barBg, minHeight: 8 }}></div>
                  <div style={{ fontSize: 12, fontWeight: isPeak || isLow ? 700 : 600, color: isPeak ? '#ec4899' : isLow ? '#64748b' : '#64748b' }}>
                    {day.label}{isPeak ? ' 🔥' : ''}
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ display: 'flex', justifyContent: 'center', gap: 24, marginTop: 16, paddingTop: 12, borderTop: '1px solid #f1f5f9' }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>📈 최고: <strong style={{ color: '#ec4899' }}>{d.peakDay}요일</strong> (지수 {Math.round(d.peakIndex)})</span>
            <span style={{ fontSize: 12, color: '#64748b' }}>📉 최저: <strong style={{ color: '#64748b' }}>{d.lowDay}요일</strong> (지수 {Math.round(d.lowIndex)})</span>
          </div>
        </div>
      </div>
    </div>
  );
};
