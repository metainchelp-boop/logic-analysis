window.KeywordTrendSection = function KeywordTrendSection(props) {
  if (!props?.data) return null;
  const { mainKeyword, subKeyword, mainVolume, subVolume, mainDifficulty, subDifficulty, mainDiffColor, subDiffColor } = props.data;

  if (!mainKeyword || !subKeyword || mainVolume === undefined || subVolume === undefined) return null;

  const maxVolume = Math.max(mainVolume, subVolume) || 1;
  const mainPercent = (mainVolume / maxVolume) * 100;
  const subPercent = (subVolume / maxVolume) * 100;

  const getDifficultyLabel = (difficulty) => {
    if (difficulty <= 20) return '매우 낮음';
    if (difficulty <= 40) return '낮음';
    if (difficulty <= 60) return '중간';
    if (difficulty <= 80) return '높음';
    return '매우 높음';
  };

  return (
    <div className="section">
      <h2 className="section-title">📈 키워드 검색량 비교 및 진입 난이도</h2>

      <div className="keyword-trend-content">
        {/* Left: Volume Comparison */}
        <div className="keyword-trend-left">
          <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '20px', color: '#333' }}>
            검색량 비교
          </h3>

          <div style={{ marginBottom: '28px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontSize: '13px', fontWeight: '500', color: '#333' }}>{mainKeyword}</span>
              <span style={{ fontSize: '13px', fontWeight: '600', color: '#1976d2' }}>{fmt(mainVolume)}</span>
            </div>
            <div style={{
              width: '100%',
              height: '24px',
              backgroundColor: '#e3f2fd',
              borderRadius: '4px',
              overflow: 'hidden'
            }}>
              <div style={{
                width: `${mainPercent}%`,
                height: '100%',
                backgroundColor: '#1976d2',
                transition: 'width 0.3s ease',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                paddingRight: '8px',
                color: '#fff',
                fontSize: '11px',
                fontWeight: '600'
              }}>
                {Math.round(mainPercent)}%
              </div>
            </div>
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontSize: '13px', fontWeight: '500', color: '#333' }}>{subKeyword}</span>
              <span style={{ fontSize: '13px', fontWeight: '600', color: '#8b5cf6' }}>{fmt(subVolume)}</span>
            </div>
            <div style={{
              width: '100%',
              height: '24px',
              backgroundColor: '#f3e5f5',
              borderRadius: '4px',
              overflow: 'hidden'
            }}>
              <div style={{
                width: `${subPercent}%`,
                height: '100%',
                backgroundColor: '#8b5cf6',
                transition: 'width 0.3s ease',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                paddingRight: '8px',
                color: '#fff',
                fontSize: '11px',
                fontWeight: '600'
              }}>
                {Math.round(subPercent)}%
              </div>
            </div>
          </div>
        </div>

        {/* Right: Difficulty Analysis */}
        <div className="keyword-trend-right">
          <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '20px', color: '#333' }}>
            진입 난이도
          </h3>

          <div style={{ marginBottom: '24px' }}>
            <div style={{ marginBottom: '12px' }}>
              <div style={{ fontSize: '13px', fontWeight: '500', color: '#333', marginBottom: '8px' }}>
                {mainKeyword}
              </div>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <div style={{
                  flex: 1,
                  height: '20px',
                  backgroundColor: '#f0f0f0',
                  borderRadius: '4px',
                  overflow: 'hidden'
                }}>
                  <div style={{
                    width: `${mainDifficulty}%`,
                    height: '100%',
                    backgroundColor: mainDiffColor,
                    transition: 'width 0.3s ease'
                  }}></div>
                </div>
                <span className={`badge ${mainDiffColor === '#dc2626' ? 'badge-red' : mainDiffColor === '#ea580c' ? 'badge-orange' : mainDiffColor === '#f59e0b' ? 'badge-yellow' : 'badge-green'}`}
                  style={{ whiteSpace: 'nowrap', fontSize: '11px' }}>
                  {getDifficultyLabel(mainDifficulty)}
                </span>
              </div>
            </div>

            <div>
              <div style={{ fontSize: '13px', fontWeight: '500', color: '#333', marginBottom: '8px' }}>
                {subKeyword}
              </div>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <div style={{
                  flex: 1,
                  height: '20px',
                  backgroundColor: '#f0f0f0',
                  borderRadius: '4px',
                  overflow: 'hidden'
                }}>
                  <div style={{
                    width: `${subDifficulty}%`,
                    height: '100%',
                    backgroundColor: subDiffColor,
                    transition: 'width 0.3s ease'
                  }}></div>
                </div>
                <span className={`badge ${subDiffColor === '#dc2626' ? 'badge-red' : subDiffColor === '#ea580c' ? 'badge-orange' : subDiffColor === '#f59e0b' ? 'badge-yellow' : 'badge-green'}`}
                  style={{ whiteSpace: 'nowrap', fontSize: '11px' }}>
                  {getDifficultyLabel(subDifficulty)}
                </span>
              </div>
            </div>
          </div>

          <div style={{
            padding: '12px',
            backgroundColor: '#f8f9fa',
            borderRadius: '4px',
            fontSize: '12px',
            color: '#666',
            lineHeight: '1.5'
          }}>
            <strong>난이도 범위:</strong>
            <div style={{ marginTop: '6px' }}>
              🟢 낮음(0-40) → 🟡 중간(40-60) → 🔴 높음(60-100)
            </div>
          </div>
        </div>
      </div>

      <style>{`
        .keyword-trend-content {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 32px;
          margin-top: 20px;
        }
        @media (max-width: 768px) {
          .keyword-trend-content {
            grid-template-columns: 1fr;
            gap: 24px;
          }
        }
      `}</style>
    </div>
  );
};
