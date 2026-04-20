window.KeywordTrendSection = function KeywordTrendSection(props) {
  if (!props?.data) return null;
  const { mainKeyword, subKeyword, mainVolume, subVolume, mainDifficulty, subDifficulty, mainDiffColor, subDiffColor } = props.data;

  if (!mainKeyword || !subKeyword || mainVolume === undefined || subVolume === undefined) return null;

  const maxVolume = Math.max(mainVolume, subVolume) || 1;
  const mainBarH = Math.max(8, (mainVolume / maxVolume) * 120);
  const subBarH = Math.max(8, (subVolume / maxVolume) * 120);

  var getDiffBadge = function(color) {
    if (!color) return { bg: '#f1f5f9', text: '#64748b', label: '-' };
    if (color === '#16a34a' || color === '#22c55e') return { bg: '#ecfdf5', text: '#059669', label: '낮음' };
    if (color === '#f59e0b' || color === '#eab308') return { bg: '#fffbeb', text: '#d97706', label: '중간' };
    if (color === '#dc2626' || color === '#ef4444' || color === '#ea580c') return { bg: '#fef2f2', text: '#dc2626', label: '높음' };
    return { bg: '#f1f5f9', text: '#64748b', label: '-' };
  };

  var mainBadge = getDiffBadge(mainDiffColor);
  var subBadge = getDiffBadge(subDiffColor);

  return (
    <div className="section fade-in">
      <div className="container">
      <h2 className="section-title">📈 키워드 검색량 비교 및 진입 난이도</h2>

      <div className="card" style={{ padding: '24px' }}>
        <div className="trend-inner-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
          {/* Left: Volume Comparison Bar Chart */}
          <div>
            <p style={{ margin: '0 0 14px', fontSize: '12px', color: '#6b7280', fontWeight: '600' }}>월간 검색량 비교</p>
            <div style={{
              background: '#f9fafb', borderRadius: '10px', padding: '20px',
              border: '1px solid #e5e7eb'
            }}>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: '24px', height: '140px', marginBottom: '12px', justifyContent: 'center' }}>
                <div style={{ flex: '0 0 40%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <div style={{
                    width: '100%', height: mainBarH + 'px',
                    background: 'linear-gradient(180deg, #4f46e5 0%, #3730a3 100%)',
                    borderRadius: '8px 8px 0 0', transition: 'height 0.5s ease'
                  }}></div>
                  <p style={{ margin: '8px 0 0', fontSize: '13px', fontWeight: '700', color: '#1f2937' }}>{fmt(mainVolume)}</p>
                </div>
                <div style={{ flex: '0 0 40%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <div style={{
                    width: '100%', height: subBarH + 'px',
                    background: 'linear-gradient(180deg, #10b981 0%, #047857 100%)',
                    borderRadius: '8px 8px 0 0', transition: 'height 0.5s ease'
                  }}></div>
                  <p style={{ margin: '8px 0 0', fontSize: '13px', fontWeight: '700', color: '#1f2937' }}>{fmt(subVolume)}</p>
                </div>
              </div>
              <div style={{ fontSize: '11px', color: '#6b7280', display: 'flex', gap: '20px', justifyContent: 'center' }}>
                <span><span style={{ display: 'inline-block', width: '12px', height: '12px', background: '#4f46e5', borderRadius: '3px', marginRight: '6px', verticalAlign: 'middle' }}></span>{mainKeyword}</span>
                <span><span style={{ display: 'inline-block', width: '12px', height: '12px', background: '#10b981', borderRadius: '3px', marginRight: '6px', verticalAlign: 'middle' }}></span>{subKeyword}</span>
              </div>
            </div>
          </div>

          {/* Right: Difficulty */}
          <div>
            <p style={{ margin: '0 0 14px', fontSize: '12px', color: '#6b7280', fontWeight: '600' }}>진입 난이도 분석</p>
            <div style={{
              background: '#f9fafb', borderRadius: '10px', padding: '20px',
              border: '1px solid #e5e7eb'
            }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: '12px', borderBottom: '1px solid #e5e7eb' }}>
                  <span style={{ fontWeight: '600', color: '#374151', fontSize: '14px' }}>{mainKeyword}</span>
                  <span style={{
                    background: mainBadge.bg, color: mainBadge.text,
                    padding: '3px 12px', borderRadius: '6px', fontSize: '11px', fontWeight: '700'
                  }}>{mainBadge.label}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontWeight: '600', color: '#374151', fontSize: '14px' }}>{subKeyword}</span>
                  <span style={{
                    background: subBadge.bg, color: subBadge.text,
                    padding: '3px 12px', borderRadius: '6px', fontSize: '11px', fontWeight: '700'
                  }}>{subBadge.label}</span>
                </div>
              </div>

              <div style={{
                marginTop: '16px', padding: '10px 12px',
                background: '#fff', borderRadius: '6px', border: '1px solid #e5e7eb',
                fontSize: '12px', color: '#6b7280', lineHeight: '1.6'
              }}>
                <strong>난이도 범위:</strong><br/>
                🟢 낮음(0-40) → 🟡 중간(40-60) → 🔴 높음(60-100)
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 반응형은 styles.css에서 처리 */}
      </div>
    </div>
  );
};
