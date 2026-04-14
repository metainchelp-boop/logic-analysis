window.GoldenKeywordCard = function GoldenKeywordCard(props) {
  if (!props?.data) return null;
  const { name, score, volume, competition, ctr, clicks, reason } = props.data;

  if (!name || score === undefined) return null;

  const scorePercent = Math.min(100, (score / 100) * 100);

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="golden-card" style={{ marginBottom: '16px' }}>
          {/* Header */}
          <div style={{ marginBottom: '20px', position: 'relative', zIndex: 1 }}>
            <span className="golden-badge">👑 GOLDEN KEYWORD</span>
            <p style={{ fontSize: '12px', color: '#92400e', marginTop: '10px', marginBottom: '16px' }}>
              낮은 CPC + 높은 전환율 = 최고 ROAS 키워드
            </p>
            <div style={{ fontSize: '28px', fontWeight: '800', color: '#78350f', marginBottom: '8px', wordBreak: 'break-word' }}>
              {name}
            </div>
            <span className="badge badge-gold" style={{ fontSize: '13px', padding: '5px 14px' }}>
              점수: {score}점
            </span>
          </div>

          {/* Stat Cards */}
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px',
            marginBottom: '20px', position: 'relative', zIndex: 1
          }}>
            {[
              { label: '월간 검색량', val: fmt(volume) + '회', color: '#b45309' },
              { label: '경쟁강도', val: competition, color: '#b45309' },
              { label: '평균 클릭수', val: (typeof ctr === 'number' ? ctr.toFixed(1) : ctr) + '회', color: '#b45309' },
              { label: '월간 클릭수', val: fmt(clicks) + '회', color: '#b45309' }
            ].map(function(s, i) {
              return (
                <div key={i} style={{
                  background: 'rgba(255,255,255,0.7)', padding: '14px',
                  borderRadius: '10px', border: '1px solid rgba(251,191,36,0.4)',
                  textAlign: 'center'
                }}>
                  <div style={{ fontSize: '11px', color: '#92400e', marginBottom: '6px', fontWeight: '600' }}>{s.label}</div>
                  <div style={{ fontSize: '18px', fontWeight: '700', color: s.color }}>{s.val}</div>
                </div>
              );
            })}
          </div>

          {/* Score Progress */}
          <div style={{ marginBottom: '16px', position: 'relative', zIndex: 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '12px', color: '#92400e' }}>
              <span>성능 지수</span>
              <span style={{ fontWeight: '700' }}>{Math.round(scorePercent)}%</span>
            </div>
            <div style={{ height: '8px', background: 'rgba(251,191,36,0.3)', borderRadius: '999px', overflow: 'hidden' }}>
              <div style={{
                width: scorePercent + '%', height: '100%',
                background: 'linear-gradient(90deg, #f59e0b, #d97706)',
                borderRadius: '999px', transition: 'width 0.5s ease'
              }}></div>
            </div>
          </div>

          {/* Reason */}
          {reason && (
            <div style={{
              background: 'rgba(255,255,255,0.6)', borderLeft: '4px solid #d97706',
              padding: '12px 16px', borderRadius: '8px',
              fontSize: '13px', color: '#78350f', lineHeight: '1.6',
              position: 'relative', zIndex: 1
            }}>
              <strong style={{ display: 'block', marginBottom: '4px' }}>📌 추천 이유</strong>
              {reason}
            </div>
          )}

          <style>{`
            @media (max-width: 768px) {
              .golden-card > div:nth-child(2) { grid-template-columns: repeat(2, 1fr) !important; }
            }
            @media (max-width: 480px) {
              .golden-card > div:nth-child(2) { grid-template-columns: 1fr !important; }
            }
          `}</style>
        </div>
      </div>
    </div>
  );
};
