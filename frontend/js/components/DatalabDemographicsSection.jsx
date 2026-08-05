/* DatalabDemographicsSection — 성별 + 연령대별 검색 비율 (v5) */
window.DatalabDemographicsSection = function DatalabDemographicsSection(props) {
  if (!props?.data) return null;
  var gender = props.data.gender;
  var age = props.data.age;
  if (!gender && !age) return null;

  var ages = age && age.ages ? age.ages : [];
  var maxAge = ages.length > 0 ? Math.max.apply(null, ages.map(function(a) { return a.ratio; })) : 1;
  var peakAge = ages.length > 0 ? ages.reduce(function(a, b) { return a.ratio > b.ratio ? a : b; }) : null;
  /* 유효성 게이트: 전 연령 0%면 "핵심 타겟 60대 남성(0.0%)" 같은 모순 서술 방지 → 데이터 없음 처리 */
  if (peakAge && !(Number(peakAge.ratio) > 0)) { ages = []; peakAge = null; }
  /* 성별 격차 10%p 미만 = 사실상 무차이 → 특정 성별 타겟 단정 금지 */
  var genderGapSmall = gender ? Math.abs((Number(gender.female) || 0) - (Number(gender.male) || 0)) < 10 : false;

  var ageColors = ['#94a3b8', '#818cf8', '#3b82f6', '#7c3aed', '#a78bfa', '#94a3b8'];
  var ageGrads = [
    'linear-gradient(90deg, #94a3b8, #cbd5e1)',
    'linear-gradient(90deg, #818cf8, #a78bfa)',
    'linear-gradient(90deg, #3b82f6, #3b82f6)',
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
    <div className="grid2">
      {/* 성별 비율 */}
      <div className="card">
        <h3 className="rt-h3"><span className="hic">👥</span>검색 인구통계 — 성별 <span className="badge b-dl">📊 데이터랩</span></h3>

        {gender ? (
          <div>
            {/* 성별 도넛 차트 */}
            <div style={{ marginBottom: 14 }}>
              <ChartCanvas
                type="doughnut"
                height={180}
                data={{
                  labels: ['남성', '여성'],
                  datasets: [{ data: [gender.male, gender.female], backgroundColor: ['#3b82f6', '#ec4899'], borderWidth: 0 }]
                }}
                options={{
                  cutout: '62%',
                  plugins: {
                    legend: { position: 'bottom' },
                    tooltip: { callbacks: { label: function(ctx) { return ctx.label + ' ' + ctx.parsed + '%'; } } }
                  }
                }}
              />
            </div>
            <div className="note">
              {genderGapSmall
                ? '여성 ' + gender.female + '% · 남성 ' + gender.male + '% — 성별 차이가 크지 않아 전 성별 공통 소구가 유리합니다.'
                : (gender.male > gender.female
                    ? '남성 ' + gender.male + '% · 여성 ' + gender.female + '% — 남성 타겟 소구.'
                    : '여성 ' + gender.female + '% · 남성 ' + gender.male + '% — 여성 타겟 소구.')}
            </div>
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8', fontSize: 13 }}>데이터 없음</div>
        )}
      </div>

      {/* 연령대별 비율 */}
      <div className="card">
        <h3 className="rt-h3"><span className="hic">👥</span>검색 인구통계 — 연령 <span className="badge b-dl">📊 데이터랩</span></h3>

        {ages.length > 0 ? (
          <div>
            <div style={{ marginBottom: 14 }}>
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
            </div>
            {peakAge && (
              <div className="note">
                핵심 타겟: <b>{targetAge}{genderGapSmall ? '' : ' ' + targetGender}</b>{genderGapSmall || !targetPct ? '' : ' (전체의 약 ' + targetPct + '%)'}{genderGapSmall ? ' — 성별 무관 공통 소구' : ''}.
              </div>
            )}
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8', fontSize: 13 }}>데이터 없음</div>
        )}
      </div>
    </div>
  );
};
