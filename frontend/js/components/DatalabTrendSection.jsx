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
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #dbeafe, #bfdbfe)' }}>📈</span>
          키워드 검색량 트렌드
          <span style={{ marginLeft: 8, padding: '3px 10px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: '#10b981', color: '#fff' }}>DATALAB</span>
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">최근 12개월 검색량 추이 — 데이터랩 쇼핑인사이트 기준</p>

        <div className="card" style={{ padding: 24 }}>
          {/* 상단 요약 카드 */}
          <div className="card-grid card-grid-4" style={{ marginBottom: 20 }}>
            <div style={{ background: '#f0f4ff', borderRadius: 10, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: '#64748b', fontWeight: 600 }}>최고 지수</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: '#4f46e5' }}>{d.maxRatio}</div>
              <div style={{ fontSize: 10, color: '#94a3b8' }}>{d.maxMonth}</div>
            </div>
            <div style={{ background: '#fef2f2', borderRadius: 10, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: '#64748b', fontWeight: 600 }}>최저 지수</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: '#ef4444' }}>{d.minRatio}</div>
              <div style={{ fontSize: 10, color: '#94a3b8' }}>{d.minMonth}</div>
            </div>
            <div style={{ background: '#f0fdf4', borderRadius: 10, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: '#64748b', fontWeight: 600 }}>평균 지수</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: '#22c55e' }}>{d.avgRatio}</div>
              <div style={{ fontSize: 10, color: '#94a3b8' }}>12개월</div>
            </div>
            <div style={{ background: '#fffbeb', borderRadius: 10, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: '#64748b', fontWeight: 600 }}>변동폭</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: '#f59e0b' }}>{d.range}p</div>
              <div style={{ fontSize: 10, color: '#94a3b8' }}>최고-최저</div>
            </div>
          </div>

          {/* Chart.js 꺾은선 그래프 */}
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

          <div style={{ marginTop: 12, padding: '10px 16px', background: 'linear-gradient(135deg, #f0f9ff, #e0f2fe)', borderRadius: 10, border: '1px solid #bae6fd', fontSize: 12, color: '#0369a1', lineHeight: 1.7 }}>
            📊 <strong>트렌드 요약:</strong> 검색량이 {d.maxMonth}에 최고({d.maxRatio}), {d.minMonth}에 최저({d.minRatio})를 기록합니다. 평균 지수는 {d.avgRatio}이며 변동폭은 {d.range}p입니다.
          </div>
        </div>
      </div>
    </div>
  );
};
