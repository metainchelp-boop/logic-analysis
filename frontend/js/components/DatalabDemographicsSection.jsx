/* DatalabDemographicsSection — 성별 + 연령대별 검색 비율 (v5) */
window.DatalabDemographicsSection = function DatalabDemographicsSection(props) {
  if (!props?.data) return null;
  var gender = props.data.gender;
  var age = props.data.age;
  if (!gender && !age) return null;

  var ages = age && age.ages ? age.ages : [];
  var maxAge = ages.length > 0 ? Math.max.apply(null, ages.map(function(a) { return a.ratio; })) : 1;
  var peakAge = ages.length > 0 ? ages.reduce(function(a, b) { return a.ratio > b.ratio ? a : b; }) : null;

  var ageColors = ['#94a3b8', '#818cf8', '#4f46e5', '#7c3aed', '#a78bfa', '#94a3b8'];
  var ageGrads = [
    'linear-gradient(90deg, #94a3b8, #cbd5e1)',
    'linear-gradient(90deg, #818cf8, #a78bfa)',
    'linear-gradient(90deg, #4f46e5, #6366f1)',
    'linear-gradient(90deg, #7c3aed, #8b5cf6)',
    'linear-gradient(90deg, #a78bfa, #c4b5fd)',
    'linear-gradient(90deg, #94a3b8, #cbd5e1)',
  ];

  /* 핵심 타겟 계산 */
  var targetGender = gender ? (gender.female > gender.male ? '여성' : '남성') : '';
  var targetAge = peakAge ? peakAge.label : '';
  var targetPct = (gender && peakAge) ? (gender.female > gender.male
    ? (peakAge.ratio * gender.female / 100).toFixed(1)
    : (peakAge.ratio * gender.male / 100).toFixed(1)) : '';

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #fce7f3, #fbcfe8)' }}>👥</span>
          검색 인구통계
          <span style={{ marginLeft: 8, padding: '3px 10px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: '#10b981', color: '#fff' }}>DATALAB</span>
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">데이터랩 쇼핑인사이트 기반 성별·연령대 검색 비율</p>

        <div className="card-grid card-grid-2">
          {/* 성별 비율 */}
          <div className="card" style={{ padding: 24 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>⚤</span> 성별 검색 비율
            </div>

            {gender ? (
              <div>
                {/* 성별 도넛 차트 */}
                <ChartCanvas
                  type="doughnut"
                  height={180}
                  data={{
                    labels: ['남성', '여성'],
                    datasets: [{ data: [gender.male, gender.female], backgroundColor: ['#4f46e5', '#ec4899'], borderWidth: 0 }]
                  }}
                  options={{
                    cutout: '62%',
                    plugins: {
                      legend: { position: 'bottom' },
                      tooltip: { callbacks: { label: function(ctx) { return ctx.label + ' ' + ctx.parsed + '%'; } } }
                    }
                  }}
                />
                {/* 수치 카드 */}
                <div className="card-grid card-grid-2" style={{ gap: 10 }}>
                  <div style={{ background: '#eef2ff', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, marginBottom: 4 }}>🧑 남성</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: '#4f46e5' }}>{gender.male}%</div>
                  </div>
                  <div style={{ background: '#fdf2f8', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, marginBottom: 4 }}>👩 여성</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: '#ec4899' }}>{gender.female}%</div>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8', fontSize: 13 }}>데이터 없음</div>
            )}
          </div>

          {/* 연령대별 비율 */}
          <div className="card" style={{ padding: 24 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>📊</span> 연령대별 검색 비율
            </div>

            {ages.length > 0 ? (
              <div>
                <ChartCanvas
                  type="bar"
                  height={200}
                  data={{
                    labels: ages.map(function(a) { return a.label + (peakAge && a.label === peakAge.label ? ' 🔥' : ''); }),
                    datasets: [{
                      label: '검색 비율',
                      data: ages.map(function(a) { return a.ratio; }),
                      backgroundColor: ages.map(function(a) { return (peakAge && a.label === peakAge.label) ? '#7c3aed' : '#c7d2fe'; }),
                      borderRadius: 6
                    }]
                  }}
                  options={{
                    plugins: {
                      legend: { display: false },
                      tooltip: { callbacks: { label: function(ctx) { return ctx.parsed.y + '%'; } } }
                    },
                    scales: { y: { beginAtZero: true, ticks: { callback: function(v) { return v + '%'; } } } }
                  }}
                />
                {peakAge && (
                  <div style={{ marginTop: 14, padding: '10px 14px', background: '#f0f4ff', borderRadius: 8, fontSize: 11, color: '#4f46e5', fontWeight: 600 }}>
                    🎯 핵심 타겟: {targetAge} {targetGender} (전체의 약 {targetPct}%)
                  </div>
                )}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8', fontSize: 13 }}>데이터 없음</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
