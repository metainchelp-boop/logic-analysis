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
                {/* 비율 바 */}
                <div style={{ display: 'flex', height: 32, borderRadius: 10, overflow: 'hidden', marginBottom: 12 }}>
                  <div style={{ width: gender.male + '%', background: 'linear-gradient(135deg, #4f46e5, #818cf8)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 13, fontWeight: 700 }}>
                    {gender.male > 10 ? gender.male + '%' : ''}
                  </div>
                  <div style={{ width: gender.female + '%', background: 'linear-gradient(135deg, #ec4899, #f472b6)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 13, fontWeight: 700 }}>
                    {gender.female > 10 ? gender.female + '%' : ''}
                  </div>
                </div>
                {/* 범례 */}
                <div style={{ display: 'flex', gap: 24, justifyContent: 'center', marginBottom: 20 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#475569', fontWeight: 600 }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#4f46e5', display: 'inline-block' }}></span> 남성 {gender.male}%
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#475569', fontWeight: 600 }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#ec4899', display: 'inline-block' }}></span> 여성 {gender.female}%
                  </span>
                </div>
                {/* 수치 카드 */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
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
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {ages.map(function(a, i) {
                    var isPeak = peakAge && a.label === peakAge.label;
                    var widthPct = maxAge > 0 ? Math.max(a.ratio / maxAge * 100, 4) : 4;
                    return (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ width: 48, fontSize: 12, fontWeight: 600, color: '#475569', textAlign: 'right' }}>{a.label}</div>
                        <div style={{ flex: 1, height: 24, background: '#f1f5f9', borderRadius: 8, position: 'relative', overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: widthPct + '%', borderRadius: 8, background: ageGrads[i] || ageGrads[0], display: 'flex', alignItems: 'center', paddingLeft: 10, fontSize: 11, fontWeight: 700, color: '#fff', minWidth: 30 }}>
                            {a.ratio > 8 ? a.ratio + '%' : ''}
                          </div>
                        </div>
                        <div style={{ width: 50, fontSize: 12, fontWeight: isPeak ? 800 : 700, color: isPeak ? '#4f46e5' : '#0f172a', textAlign: 'right' }}>
                          {a.ratio}%{isPeak ? ' 🔥' : ''}
                        </div>
                      </div>
                    );
                  })}
                </div>
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
