/* DatalabWeekdaySection — 요일별 검색 패턴 (v5) */
window.DatalabWeekdaySection = function DatalabWeekdaySection(props) {
  if (!props?.data || !props.data.days || props.data.days.length === 0) return null;
  var d = props.data;
  var days = d.days;

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: 24 }}>
          <h3 className="rt-h3"><span className="rt-hic">📅</span>요일별 검색 패턴<span className="badge b-ok">✅ 데이터랩</span></h3>
          <div className="rt-desc">최근 4주 기준 요일별 검색 트렌드</div>
          <ChartCanvas
            type="bar"
            height={200}
            data={{
              labels: days.map(function(day) { return day.label + (day.label === d.peakDay ? ' 🔥' : ''); }),
              datasets: [{
                label: '검색 지수',
                data: days.map(function(day) { return Math.round(day.normalized); }),
                backgroundColor: days.map(function(day) {
                  return day.label === d.peakDay ? '#ec4899' : day.label === d.lowDay ? '#94a3b8' : (day.normalized >= 85 ? '#7c3aed' : '#4f46e5');
                }),
                borderRadius: 6
              }]
            }}
            options={{
              plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: function(ctx) { return '지수 ' + ctx.parsed.y; } } }
              },
              scales: { y: { beginAtZero: true } }
            }}
          />

          <div style={{ display: 'flex', justifyContent: 'center', gap: 24, marginTop: 16, paddingTop: 12, borderTop: '1px solid #f1f5f9' }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>📈 최고: <strong style={{ color: '#ec4899' }}>{d.peakDay}요일</strong> (지수 {Math.round(d.peakIndex)})</span>
            <span style={{ fontSize: 12, color: '#64748b' }}>📉 최저: <strong style={{ color: '#64748b' }}>{d.lowDay}요일</strong> (지수 {Math.round(d.lowIndex)})</span>
          </div>
        </div>
      </div>
    </div>
  );
};
