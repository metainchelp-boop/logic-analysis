window.KeywordTagSection = function KeywordTagSection(props) {
  if (!props?.data) return null;
  const { topKeywords, totalFound } = props.data;

  if (!topKeywords || topKeywords.length === 0) return null;

  var goldenCount = topKeywords.filter(function(k) { return k.isGolden; }).length;
  var lowCompCount = topKeywords.filter(function(k) { return k.comp === '낮음'; }).length;

  return (
    <div className="section fade-in">
      <div className="container">
      <h2 className="section-title">🔍 키워드 & 태그 분석</h2>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: '24px' }}>
        {/* Left: Keyword List */}
        <div className="card" style={{ padding: '24px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: '700', color: '#4f46e5', marginBottom: '16px' }}>
            💬 상품명 주요 키워드 TOP {Math.min(topKeywords.length, 15)}
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {topKeywords.map(function(kw, idx) {
              return (
                <div key={idx} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '10px 14px',
                  background: kw.isGolden ? 'linear-gradient(135deg, #fefce8, #fef9c3)' : '#f9fafb',
                  borderRadius: '8px',
                  border: kw.isGolden ? '1px solid #fbbf24' : '1px solid #e5e7eb',
                  transition: 'transform 0.15s'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      width: '26px', height: '26px',
                      background: kw.isGolden ? 'linear-gradient(135deg, #f59e0b, #d97706)' : 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                      color: '#fff', borderRadius: '50%', fontSize: '11px', fontWeight: '700'
                    }}>{idx + 1}</span>
                    <span style={{ fontSize: '13px', fontWeight: '600', color: '#1f2937' }}>
                      {kw.keyword}
                      {kw.isGolden && <span style={{ marginLeft: '6px' }}>👑</span>}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '12px', color: '#6b7280' }}>
                    <span>검색량: {kw.volume}</span>
                    <span className={'badge ' + (kw.comp === '낮음' ? 'badge-green' : kw.comp === '높음' ? 'badge-red' : 'badge-amber')}
                      style={{ fontSize: '10px', padding: '2px 8px' }}>
                      {kw.comp}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Stats Panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="score-card" style={{ borderLeftColor: '#7c3aed' }}>
            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '6px', fontWeight: '600' }}>총 발견 키워드</div>
            <div className="big-num" style={{ color: '#7c3aed' }}>{fmt(totalFound)}개</div>
          </div>
          <div className="score-card" style={{ borderLeftColor: '#d97706' }}>
            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '6px', fontWeight: '600' }}>골든 키워드</div>
            <div className="big-num" style={{ color: '#d97706' }}>{goldenCount}개</div>
          </div>
          <div className="score-card" style={{ borderLeftColor: '#059669' }}>
            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '6px', fontWeight: '600' }}>경쟁 낮은 키워드</div>
            <div className="big-num" style={{ color: '#059669' }}>{lowCompCount}개</div>
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 768px) {
          .section > div[style*="1fr 320px"] {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
      </div>
    </div>
  );
};
