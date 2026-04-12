window.GoldenKeywordCard = function GoldenKeywordCard(props) {
  if (!props?.data) return null;
  const { name, score, volume, competition, ctr, clicks, reason } = props.data;

  if (!name || score === undefined) return null;

  const scorePercent = Math.min(100, (score / 100) * 100);

  return (
    <div style={{
      background: 'linear-gradient(135deg, #ffd89b 0%, #19547b 100%)',
      borderRadius: '12px',
      padding: '32px',
      color: '#fff',
      boxShadow: '0 8px 32px rgba(255, 215, 0, 0.2)',
      marginBottom: '24px'
    }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <div style={{ fontSize: '14px', fontWeight: '600', opacity: 0.9, marginBottom: '8px' }}>
          👑 GOLDEN KEYWORD
        </div>
        <div style={{ fontSize: '12px', opacity: 0.8, marginBottom: '16px' }}>
          낮은 CPC + 높은 전환율 = 최고 ROAS 키워드
        </div>

        {/* Keyword Name */}
        <div style={{ fontSize: '32px', fontWeight: '700', marginBottom: '12px', wordBreak: 'break-word' }}>
          {name}
        </div>

        {/* Score Badge */}
        <div style={{ display: 'inline-block' }}>
          <div style={{
            backgroundColor: 'rgba(255, 255, 255, 0.2)',
            color: '#fff',
            padding: '6px 12px',
            borderRadius: '20px',
            fontSize: '13px',
            fontWeight: '600',
            border: '1px solid rgba(255, 255, 255, 0.4)'
          }}>
            점수: {score}점
          </div>
        </div>
      </div>

      {/* Stat Cards Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: '16px',
        marginBottom: '24px'
      }}>
        <div style={{
          backgroundColor: 'rgba(255, 255, 255, 0.15)',
          padding: '16px',
          borderRadius: '8px',
          backdropFilter: 'blur(10px)',
          border: '1px solid rgba(255, 255, 255, 0.2)'
        }}>
          <div style={{ fontSize: '11px', opacity: 0.85, marginBottom: '8px' }}>월간 검색량</div>
          <div style={{ fontSize: '18px', fontWeight: '700' }}>{fmt(volume)}회</div>
        </div>

        <div style={{
          backgroundColor: 'rgba(255, 255, 255, 0.15)',
          padding: '16px',
          borderRadius: '8px',
          backdropFilter: 'blur(10px)',
          border: '1px solid rgba(255, 255, 255, 0.2)'
        }}>
          <div style={{ fontSize: '11px', opacity: 0.85, marginBottom: '8px' }}>경쟁강도</div>
          <div style={{ fontSize: '18px', fontWeight: '700' }}>{competition}</div>
        </div>

        <div style={{
          backgroundColor: 'rgba(255, 255, 255, 0.15)',
          padding: '16px',
          borderRadius: '8px',
          backdropFilter: 'blur(10px)',
          border: '1px solid rgba(255, 255, 255, 0.2)'
        }}>
          <div style={{ fontSize: '11px', opacity: 0.85, marginBottom: '8px' }}>평균 클릭수</div>
          <div style={{ fontSize: '18px', fontWeight: '700' }}>{typeof ctr === 'number' ? ctr.toFixed(1) : ctr}회</div>
        </div>

        <div style={{
          backgroundColor: 'rgba(255, 255, 255, 0.15)',
          padding: '16px',
          borderRadius: '8px',
          backdropFilter: 'blur(10px)',
          border: '1px solid rgba(255, 255, 255, 0.2)'
        }}>
          <div style={{ fontSize: '11px', opacity: 0.85, marginBottom: '8px' }}>월간 클릭수</div>
          <div style={{ fontSize: '18px', fontWeight: '700' }}>{fmt(clicks)}회</div>
        </div>
      </div>

      {/* Score Progress Bar */}
      <div style={{ marginBottom: '20px' }}>
        <div style={{
          width: '100%',
          height: '8px',
          backgroundColor: 'rgba(255, 255, 255, 0.2)',
          borderRadius: '4px',
          overflow: 'hidden',
          marginBottom: '8px'
        }}>
          <div style={{
            width: `${scorePercent}%`,
            height: '100%',
            backgroundColor: '#ffd700',
            transition: 'width 0.3s ease'
          }}></div>
        </div>
        <div style={{ fontSize: '11px', opacity: 0.8 }}>
          성능 지수: {Math.round(scorePercent)}%
        </div>
      </div>

      {/* Recommendation Reason */}
      {reason && (
        <div style={{
          backgroundColor: 'rgba(255, 255, 255, 0.1)',
          borderLeft: '4px solid #ffd700',
          padding: '12px',
          borderRadius: '4px',
          fontSize: '12px',
          lineHeight: '1.6',
          opacity: 0.95
        }}>
          <strong style={{ display: 'block', marginBottom: '6px' }}>📌 추천 이유</strong>
          {reason}
        </div>
      )}

      <style>{`
        @media (max-width: 768px) {
          .golden-stats {
            grid-template-columns: repeat(2, 1fr);
          }
        }
      `}</style>
    </div>
  );
};
