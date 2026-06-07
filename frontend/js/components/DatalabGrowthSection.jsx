/* DatalabGrowthSection — 전년 동기 대비 성장률 (v5) */
window.DatalabGrowthSection = function DatalabGrowthSection(props) {
  if (!props?.data || !props.data.periods || props.data.periods.length === 0) return null;
  var periods = props.data.periods;

  var colors = [
    { main: '#22c55e', grad: 'linear-gradient(90deg, #22c55e, #4ade80)', bg: '#f0fdf4' },
    { main: '#4f46e5', grad: 'linear-gradient(90deg, #4f46e5, #818cf8)', bg: '#eef2ff' },
    { main: '#f59e0b', grad: 'linear-gradient(90deg, #f59e0b, #fbbf24)', bg: '#fffbeb' },
  ];

  /* 전체 성장 판단 */
  var avg3m = periods.length > 1 ? periods[1] : periods[0];
  var growthLabel = avg3m.growth > 10 ? '빠른 성장세' : avg3m.growth > 0 ? '완만한 성장세' : avg3m.growth > -10 ? '보합세' : '하락세';

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
        <h3 className="rt-h3"><span className="rt-hic">🚀</span>전년 동기 대비 성장률<span className="badge b-ok">✅ 데이터랩</span></h3>
        <div className="rt-desc">데이터랩 쇼핑인사이트 기반 전년 대비 검색 트렌드 변화</div>

        {/* 기간별 성장률 비교 막대 차트 */}
        <div className="card" style={{ padding: '20px 24px', marginBottom: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 14 }}>기간별 성장률 비교</div>
          <ChartCanvas
            type="bar"
            height={200}
            data={{
              labels: periods.map(function(p) { return '직전 ' + p.label + ' 대비'; }),
              datasets: [{
                label: '성장률(%)',
                data: periods.map(function(p) { return p.growth; }),
                backgroundColor: periods.map(function(p) { return p.growth >= 0 ? '#22c55e' : '#ef4444'; }),
                borderRadius: 6
              }]
            }}
            options={{
              plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: function(ctx) { return (ctx.parsed.y >= 0 ? '+' : '') + ctx.parsed.y + '%'; } } }
              },
              scales: { y: { ticks: { callback: function(v) { return (v > 0 ? '+' : '') + v + '%'; } } } }
            }}
          />
        </div>

        <div className="card-grid card-grid-3">
          {periods.map(function(p, i) {
            var c = colors[i] || colors[0];
            var isRecommended = i === 1;
            var isPositive = p.growth >= 0;
            var barWidth = Math.min(Math.abs(p.growth) + 50, 100);

            return (
              <div key={i} className="card" style={{ padding: 24, textAlign: 'center', position: 'relative', border: isRecommended ? '2px solid #4f46e5' : undefined }}>
                {isRecommended && (
                  <div style={{ position: 'absolute', top: -1, right: 16, background: '#4f46e5', color: '#fff', fontSize: 10, fontWeight: 700, padding: '2px 10px', borderRadius: '0 0 6px 6px' }}>추천 기준</div>
                )}
                <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 12 }}>
                  직전 {p.label} 대비
                </div>
                <div style={{ fontSize: 32, fontWeight: 800, color: isPositive ? c.main : '#ef4444', marginBottom: 4 }}>
                  {isPositive ? '+' : ''}{p.growth}%
                </div>
                <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
                  {isPositive ? '검색량 증가 추세' : '검색량 감소 추세'}
                </div>
                <div style={{ height: 6, background: '#e2e8f0', borderRadius: 3, overflow: 'hidden', marginBottom: 10 }}>
                  <div style={{ height: '100%', width: barWidth + '%', borderRadius: 3, background: isPositive ? c.grad : 'linear-gradient(90deg, #ef4444, #f87171)' }}></div>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#94a3b8' }}>
                  <span>전년: {p.previousAvg}</span>
                  <span>올해: {p.currentAvg}</span>
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ marginTop: 16, padding: '12px 16px', background: '#f0fdf4', borderRadius: 10, border: '1px solid #a7f3d0', fontSize: 12, color: '#065f46', lineHeight: 1.7 }}>
          📈 <strong>성장 분석:</strong> 전년 대비 3개월 평균 기준 {avg3m.growth > 0 ? '+' : ''}{avg3m.growth}%로 <strong>{growthLabel}</strong>입니다.
          {avg3m.growth > 0 && ' 단기(1개월) 성장률이 장기 평균보다 ' + (periods[0].growth > avg3m.growth ? '높아 현재 상승 모멘텀이 강합니다.' : '낮아 안정적 성장 구간입니다.')}
        </div>
        </div>
      </div>
    </div>
  );
};
