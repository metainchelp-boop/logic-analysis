window.CompetitionIndexSection = function CompetitionIndexSection(props) {
  if (!props?.data) return null;
  const { compIndex, compLabel, compColor, productCount, searchVolume, avgCtr, interpretation } = props.data;

  if (compIndex === undefined || compIndex === null) return null;

  const maxIdx = 100;
  const barPercent = Math.min(100, (compIndex / maxIdx) * 100);

  return (
    <div className="section fade-in">
      <div className="container">
      <h2 className="section-title">🎯 키워드 경쟁강도 분석</h2>

      <div className="card" style={{ padding: '24px' }}>
        <div className="comp-inner-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
          {/* Left: Competition Index Gauge */}
          <div>
            <p style={{ margin: '0 0 10px', fontSize: '12px', color: '#6b7280', fontWeight: '600' }}>경쟁강도 지수</p>
            <div style={{
              background: '#fff', borderRadius: '10px', padding: '16px',
              border: '1px solid #e5e7eb'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                <span style={{ fontSize: '28px', fontWeight: '800', color: compColor }}>{fmt(compIndex)}</span>
                <span className="gauge-label" style={{
                  background: compColor, color: '#fff',
                  padding: '4px 14px', borderRadius: '999px',
                  fontSize: '11px', fontWeight: '700'
                }}>
                  {compLabel}
                </span>
              </div>
              <div className="progress-bar" style={{ height: '10px' }}>
                <div className="progress-fill" style={{
                  width: barPercent + '%',
                  background: compColor,
                  transition: 'width 0.5s ease'
                }}></div>
              </div>
            </div>
          </div>

          {/* Right: Market Stats */}
          <div>
            <p style={{ margin: '0 0 10px', fontSize: '12px', color: '#6b7280', fontWeight: '600' }}>시장 현황</p>
            <div style={{
              background: '#fff', borderRadius: '10px', padding: '16px',
              border: '1px solid #e5e7eb', fontSize: '13px', lineHeight: '2', color: '#374151'
            }}>
              <p style={{ margin: 0 }}><strong>상품 수:</strong> {fmt(productCount)}개</p>
              <p style={{ margin: 0 }}><strong>검색량:</strong> {fmt(searchVolume)}회/월</p>
              <p style={{ margin: 0 }}><strong>평균 클릭수:</strong> {typeof avgCtr === 'number' ? avgCtr.toFixed(1) : avgCtr}회</p>
            </div>
          </div>
        </div>

        {/* Interpretation */}
        {interpretation && (
          <div style={{
            marginTop: '16px', padding: '12px 16px',
            background: '#fff', borderRadius: '8px',
            borderLeft: '4px solid ' + compColor,
            fontSize: '13px', color: '#374151', lineHeight: '1.6'
          }}>
            {interpretation}
          </div>
        )}
      </div>

      <style>{`
        @media (max-width: 768px) {
          .comp-inner-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
      </div>
    </div>
  );
};
