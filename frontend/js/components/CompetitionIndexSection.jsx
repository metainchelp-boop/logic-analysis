window.CompetitionIndexSection = function CompetitionIndexSection(props) {
  if (!props?.data) return null;
  const { compIndex, compPercent, compLabel, compColor, productCount, searchVolume, avgCtr, interpretation } = props.data;

  if (compPercent === undefined && compIndex === undefined) return null;

  var pct = typeof compPercent === 'number' ? compPercent : Math.min(98, Math.round(Math.log10(compIndex * 10 + 1) / Math.log10(101) * 100));

  /* 지표 카드 색상 매핑 */
  var metricCards = [
    { label: '등록 상품수', value: fmt(productCount), unit: '개', bg: '#fef2f2', color: '#dc2626' },
    { label: '월간 검색량', value: fmt(searchVolume), unit: '회', bg: '#eff6ff', color: '#2563eb' },
    { label: '평균 클릭수', value: typeof avgCtr === 'number' ? avgCtr.toFixed(1) : avgCtr, unit: '회', bg: '#f0fdf4', color: '#16a34a' }
  ];

  return (
    <div className="section fade-in">
      <div className="container">
      <div className="section-title">
        <span className="icon" style={{ background: '#fef2f2' }}>⚔️</span>
        키워드 경쟁강도 분석
      </div>
      <div className="section-line"></div>
      <p className="section-subtitle">상품 수 대비 검색량으로 경쟁 수준을 판단합니다</p>

      <div className="card" style={{ padding: '24px', borderRadius: '16px' }}>
        {/* 상단: 도넛차트 + 라벨 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            {/* conic-gradient 도넛 */}
            <div style={{
              width: 80, height: 80, borderRadius: '50%',
              background: 'conic-gradient(' + compColor + ' ' + (pct * 3.6) + 'deg, #f1f5f9 0deg)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0
            }}>
              <div style={{
                width: 60, height: 60, borderRadius: '50%', background: '#fff',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 18, fontWeight: 800, color: compColor
              }}>
                {pct}
              </div>
            </div>
            <div>
              <span style={{
                display: 'inline-block', background: compColor, color: '#fff',
                padding: '5px 16px', borderRadius: 999, fontSize: 14, fontWeight: 700
              }}>
                {compLabel}
              </span>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>경쟁지수: {fmt(compIndex)}</div>
            </div>
          </div>
        </div>

        {/* 3구간 바 */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ position: 'relative', height: 36, borderRadius: 18, overflow: 'hidden' }}>
            <div style={{ position: 'absolute', top: 0, left: 0, width: '30%', height: '100%', background: 'linear-gradient(90deg, #d1fae5, #a7f3d0)' }} />
            <div style={{ position: 'absolute', top: 0, left: '30%', width: '40%', height: '100%', background: 'linear-gradient(90deg, #fef3c7, #fde68a)' }} />
            <div style={{ position: 'absolute', top: 0, left: '70%', width: '30%', height: '100%', background: 'linear-gradient(90deg, #fecaca, #fca5a5)' }} />
            <div style={{
              position: 'absolute', top: 2, left: 'calc(' + pct + '% - 16px)',
              width: 32, height: 32, borderRadius: 16,
              background: compColor, border: '3px solid #fff',
              boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', fontSize: 11, fontWeight: 800,
              transition: 'left 0.8s ease'
            }}>
              {pct}
            </div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 11, color: '#94a3b8' }}>
            <span style={{ color: '#10b981' }}>블루오션</span>
            <span style={{ color: '#f59e0b' }}>보통</span>
            <span style={{ color: '#ef4444' }}>레드오션</span>
          </div>
        </div>

        {/* 핵심 지표 — 컬러 배경 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
          {metricCards.map(function(m, i) {
            return (
              <div key={i} style={{ background: m.bg, borderRadius: 12, padding: 16, textAlign: 'center' }}>
                <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, marginBottom: 6 }}>{m.label}</div>
                <div style={{ fontSize: 18, fontWeight: 800, color: m.color }}>
                  {m.value}<span style={{ fontSize: 12, fontWeight: 400 }}>{m.unit}</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* 전문 코멘트 */}
        {interpretation && (
          <div style={{
            padding: '14px 18px',
            background: 'linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%)',
            borderRadius: 10, border: '1px solid #bae6fd',
            borderLeft: '4px solid ' + compColor,
            fontSize: 13, color: '#1e3a5f', lineHeight: 1.8
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
              <span style={{ fontSize: 14 }}>📋</span>
              <span style={{ fontWeight: 700, fontSize: 13, color: '#0369a1' }}>시장 분석 코멘트</span>
            </div>
            {interpretation}
          </div>
        )}
      </div>
      </div>
    </div>
  );
};
