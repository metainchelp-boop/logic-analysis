/* DatalabTrendSection — 12개월 검색량 트렌드 꺾은선 그래프 (v5) */
window.DatalabTrendSection = function DatalabTrendSection(props) {
  if (!props?.data || !props.data.months || props.data.months.length < 3) return null;
  var d = props.data;
  var months = d.months;

  /* SVG 치수 */
  var W = 680, H = 220, PAD_L = 42, PAD_R = 20, PAD_T = 25, PAD_B = 40;
  var chartW = W - PAD_L - PAD_R;
  var chartH = H - PAD_T - PAD_B;
  var maxR = d.maxRatio || Math.max.apply(null, months.map(function(m){return m.ratio;})) || 100;
  var step = chartW / Math.max(months.length - 1, 1);

  function x(i) { return PAD_L + i * step; }
  function y(v) { return PAD_T + chartH - (v / maxR * chartH); }

  /* 꺾은선 포인트 */
  var points = months.map(function(m, i) { return x(i) + ',' + y(m.ratio); }).join(' ');
  /* 영역 폴리곤 (아래쪽 채움) */
  var area = x(0) + ',' + (PAD_T + chartH) + ' ' + points + ' ' + x(months.length - 1) + ',' + (PAD_T + chartH);

  /* 그리드 라인 (25 단위) */
  var gridLines = [0, 25, 50, 75, 100].filter(function(v) { return v <= maxR; });
  if (maxR > 100) gridLines.push(Math.round(maxR));

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card">
          <h3 className="rt-h3"><span className="rt-hic">📈</span>키워드 검색량 트렌드 (최근 12개월) <span className="badge b-ok">✅ 데이터랩</span></h3>
          {/* KPI 4칸 — 차트 위 */}
          <div className="grid4" style={{ marginBottom: 6 }}>
            <div className="kpi"><div className="k">최고 지수</div><div className="v">{d.maxRatio} <small>{d.maxMonth}</small></div></div>
            <div className="kpi"><div className="k">최저 지수</div><div className="v">{d.minRatio} <small>{d.minMonth}</small></div></div>
            <div className="kpi"><div className="k">평균 지수</div><div className="v">{d.avgRatio}</div></div>
            <div className="kpi"><div className="k">변동폭</div><div className="v">{d.range}<small>p</small></div></div>
          </div>

          {/* Chart.js 꺾은선 그래프 */}
          <div className="chartbox">
            <ChartCanvas
              type="line"
              height={240}
              data={{
                labels: months.map(function(m) { return m.label; }),
                datasets: [{
                  label: '검색 지수',
                  data: months.map(function(m) { return m.ratio; }),
                  borderColor: '#4f46e5',
                  backgroundColor: function(c) {
                    if (!c.chart.ctx) return 'rgba(79,70,229,.12)';
                    return window.chartGrad ? window.chartGrad(c.chart.ctx, 'rgba(79,70,229,.22)', 'rgba(79,70,229,0)', 240) : 'rgba(79,70,229,.12)';
                  },
                  fill: true, tension: 0.4, borderWidth: 2.5,
                  pointRadius: months.map(function(m) { return (m.ratio === d.maxRatio || m.ratio === d.minRatio) ? 6 : 3; }),
                  pointBackgroundColor: months.map(function(m) { return m.ratio === d.maxRatio ? '#4f46e5' : m.ratio === d.minRatio ? '#ef4444' : '#fff'; }),
                  pointBorderColor: months.map(function(m) { return m.ratio === d.minRatio ? '#ef4444' : '#4f46e5'; }),
                  pointBorderWidth: 2
                }]
              }}
              options={{
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, suggestedMax: (d.maxRatio || 100) } }
              }}
            />
          </div>

          <div className="note">{d.trendNote}</div>
        </div>
      </div>
    </div>
  );
};
