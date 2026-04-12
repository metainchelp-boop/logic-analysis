window.KeywordTagSection = function KeywordTagSection(props) {
  if (!props?.data) return null;
  const { topKeywords, totalFound } = props.data;

  if (!topKeywords || topKeywords.length === 0) return null;

  return (
    <div className="section">
      <h2 className="section-title">🔍 키워드 & 태그 분석</h2>

      <div className="keyword-tag-content">
        <div className="keyword-column">
          <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '16px', color: '#1976d2' }}>
            💬 상품명 주요 키워드 TOP {Math.min(topKeywords.length, 15)}
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {topKeywords.map(function(kw, idx) {
              return (
                <div key={idx} style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '8px 12px',
                  backgroundColor: kw.isGolden ? '#fef3c7' : '#f8f9fa',
                  borderRadius: '6px',
                  border: kw.isGolden ? '1px solid #fcd34d' : '1px solid #e5e5e5'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      width: '24px', height: '24px',
                      backgroundColor: kw.isGolden ? '#f59e0b' : '#1976d2',
                      color: '#fff', borderRadius: '50%', fontSize: '11px', fontWeight: '600'
                    }}>{idx + 1}</span>
                    <span style={{ fontSize: '13px', fontWeight: '500', color: '#333' }}>
                      {kw.keyword}
                      {kw.isGolden && <span style={{ marginLeft: '6px', fontSize: '11px', color: '#f59e0b' }}>👑</span>}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '12px', color: '#666' }}>
                    <span>검색량: {kw.volume}</span>
                    <span className={'badge ' + (kw.comp === '낮음' ? 'badge-blue' : 'badge-red')} style={{ fontSize: '10px', padding: '2px 6px' }}>
                      {kw.comp}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="tag-column">
          <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '16px', color: '#8b5cf6' }}>
            📊 키워드 통계
          </h3>
          <div style={{ padding: '20px', backgroundColor: '#f8f9fa', borderRadius: '8px' }}>
            <div style={{ marginBottom: '20px' }}>
              <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>총 발견 키워드</div>
              <div style={{ fontSize: '32px', fontWeight: '700', color: '#8b5cf6' }}>{fmt(totalFound)}개</div>
            </div>
            <div style={{ marginBottom: '20px' }}>
              <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>골든 키워드</div>
              <div style={{ fontSize: '24px', fontWeight: '700', color: '#f59e0b' }}>
                {topKeywords.filter(function(k) { return k.isGolden; }).length}개
              </div>
            </div>
            <div>
              <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>경쟁 낮은 키워드</div>
              <div style={{ fontSize: '24px', fontWeight: '700', color: '#16a34a' }}>
                {topKeywords.filter(function(k) { return k.comp === '낮음'; }).length}개
              </div>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        .keyword-tag-content { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; margin-top: 20px; }
        .keyword-column, .tag-column { min-height: 200px; }
        @media (max-width: 768px) { .keyword-tag-content { grid-template-columns: 1fr; gap: 24px; } }
      `}</style>
    </div>
  );
};
