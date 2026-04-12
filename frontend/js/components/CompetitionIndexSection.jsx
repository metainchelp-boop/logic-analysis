window.CompetitionIndexSection = function CompetitionIndexSection(props) {
  if (!props?.data) return null;
  const { compIndex, compLabel, compColor, productCount, searchVolume, avgCtr, interpretation } = props.data;

  if (compIndex === undefined || compIndex === null) return null;

  const progressPercent = Math.min(100, (compIndex / 100) * 100);

  return (
    <div className="section">
      <h2 className="section-title">🎯 키워드 경쟁강도 분석</h2>

      <div className="competition-content">
        {/* Left column: Competition Index */}
        <div className="competition-left">
          <div style={{ marginBottom: '24px' }}>
            <div style={{ fontSize: '48px', fontWeight: '700', color: compColor, marginBottom: '8px' }}>
              {fmt(compIndex)}
            </div>
            <div style={{ fontSize: '13px', color: '#666', marginBottom: '12px' }}>경쟁강도 지수</div>

            {/* Progress bar */}
            <div style={{
              width: '100%',
              height: '12px',
              backgroundColor: '#f0f0f0',
              borderRadius: '6px',
              overflow: 'hidden',
              marginBottom: '12px'
            }}>
              <div style={{
                width: `${progressPercent}%`,
                height: '100%',
                backgroundColor: compColor,
                transition: 'width 0.3s ease'
              }}></div>
            </div>

            {/* Competition label badge */}
            <div>
              <span className={`badge ${compLabel === '블루오션' ? 'badge-blue' : 'badge-red'}`}>
                {compLabel}
              </span>
            </div>
          </div>
        </div>

        {/* Right column: Market Stats */}
        <div className="competition-right">
          <div className="stat-mini">
            <div className="stat-label">상품 수</div>
            <div className="stat-value">{fmt(productCount)}개</div>
          </div>
          <div className="stat-mini">
            <div className="stat-label">월간 검색량</div>
            <div className="stat-value">{fmt(searchVolume)}회/월</div>
          </div>
          <div className="stat-mini">
            <div className="stat-label">평균 클릭수</div>
            <div className="stat-value">{typeof avgCtr === 'number' ? avgCtr.toFixed(1) : avgCtr}회</div>
          </div>
        </div>
      </div>

      {/* Interpretation */}
      {interpretation && (
        <div style={{
          padding: '16px',
          backgroundColor: '#f8f9fa',
          borderLeft: `4px solid ${compColor}`,
          borderRadius: '4px',
          marginTop: '20px',
          fontSize: '13px',
          color: '#333',
          lineHeight: '1.6'
        }}>
          {interpretation}
        </div>
      )}

      <style>{`
        .competition-content {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 32px;
          margin-top: 20px;
        }
        .competition-left {
          display: flex;
          align-items: flex-start;
        }
        .competition-right {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 16px;
        }
        .stat-mini {
          padding: 12px;
          background: #f8f9fa;
          border-radius: 6px;
          text-align: center;
        }
        .stat-label {
          font-size: 12px;
          color: #999;
          margin-bottom: 6px;
        }
        .stat-value {
          font-size: 18px;
          font-weight: 700;
          color: #333;
        }
        @media (max-width: 768px) {
          .competition-content {
            grid-template-columns: 1fr;
            gap: 20px;
          }
          .competition-right {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};
