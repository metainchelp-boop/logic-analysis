/* DatalabCategoryKeywordsSection — 카테고리 인기 키워드 TOP (v5) */
window.DatalabCategoryKeywordsSection = function DatalabCategoryKeywordsSection(props) {
  if (!props?.data) return null;
  var popular = props.data.popular || [];
  var rising = props.data.rising || [];
  if (popular.length === 0 && rising.length === 0) return null;

  var medalColors = ['#fbbf24', '#94a3b8', '#cd7f32'];

  function renderKwRow(kw, idx, type) {
    var isTop3 = idx < 3;
    var isRising = type === 'rising';
    var growthAbs = Math.abs(kw.growth);
    var isPositive = kw.growth >= 0;

    var rowBg = isTop3 && idx === 0
      ? (isRising ? 'linear-gradient(135deg, #dcfce7, #f0fdf4)' : 'linear-gradient(135deg, #fef9c3, #fffbeb)')
      : '#f8fafc';
    var rowBorder = isTop3 && idx === 0 && isRising ? '1px solid #a7f3d0' : '1px solid #f1f5f9';

    return (
      <div key={idx} style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
        background: rowBg, borderRadius: 10, border: rowBorder
      }}>
        <span style={{
          width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, fontWeight: 800, color: '#fff', flexShrink: 0,
          background: isRising ? '#22c55e' : (isTop3 ? medalColors[idx] : '#64748b')
        }}>{idx + 1}</span>
        <span style={{ flex: 1, fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{kw.keyword}</span>
        <span style={{
          padding: '4px 10px', borderRadius: 999, fontSize: 12, fontWeight: 700,
          background: isPositive ? (growthAbs > 50 ? '#22c55e' : growthAbs > 10 ? '#dcfce7' : '#fef3c7') : '#fee2e2',
          color: isPositive ? (growthAbs > 50 ? '#fff' : '#16a34a') : '#dc2626'
        }}>
          {isPositive ? '▲' : '▼'} {growthAbs}%
        </span>
        <span style={{ fontSize: 12, color: '#64748b', width: 70, textAlign: 'right' }}>{fmt(kw.volume)}</span>
      </div>
    );
  }

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #fef3c7, #fde68a)' }}>🏷️</span>
          카테고리 인기 키워드 TOP
          <span style={{ marginLeft: 8, padding: '3px 10px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: '#10b981', color: '#fff' }}>DATALAB</span>
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">분석 상품의 카테고리에서 최근 가장 많이 검색되는 키워드</p>

        <div className="card-grid card-grid-2">
          {/* 인기 키워드 순위 */}
          <div className="card" style={{ padding: 20 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>🔥</span> 인기 키워드 순위
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 340, overflowY: 'auto' }}>
              {popular.map(function(kw, i) { return renderKwRow(kw, i, 'popular'); })}
            </div>
            {popular.length > 5 && (
              <div style={{ textAlign: 'center', marginTop: 10, fontSize: 11, color: '#94a3b8' }}>스크롤하여 더 보기 ↓</div>
            )}
          </div>

          {/* 급상승 키워드 */}
          <div className="card" style={{ padding: 20 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>🚀</span> 급상승 키워드
            </div>
            {rising.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {rising.map(function(kw, i) { return renderKwRow(kw, i, 'rising'); })}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8', fontSize: 13 }}>급상승 키워드 없음</div>
            )}
            <div style={{ textAlign: 'center', marginTop: 10, fontSize: 11, color: '#94a3b8' }}>전월 대비 성장률 기준</div>
          </div>
        </div>

        <div style={{ marginTop: 16, padding: '12px 16px', background: '#fffbeb', borderRadius: 10, border: '1px solid #fde68a', fontSize: 12, color: '#92400e', lineHeight: 1.7 }}>
          💡 <strong>활용 팁:</strong> 인기 키워드를 상품명이나 태그에 포함하면 노출 확률이 높아집니다. 급상승 키워드는 시즌 트렌드를 반영하므로 빠른 대응이 유리합니다.
        </div>
      </div>
    </div>
  );
};
