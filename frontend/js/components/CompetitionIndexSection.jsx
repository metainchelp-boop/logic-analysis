window.CompetitionIndexSection = function CompetitionIndexSection(props) {
  if (!props?.data) return null;
  const { compIndex, compPercent, compLabel, compColor, productCount, searchVolume, avgCtr, interpretation } = props.data;

  if (compPercent === undefined && compIndex === undefined) return null;

  // 백분율 값 (신규 데이터면 compPercent 사용, 레거시면 compIndex 기반 계산)
  var pct = typeof compPercent === 'number' ? compPercent : Math.min(98, Math.round(Math.log10(compIndex * 10 + 1) / Math.log10(101) * 100));

  return (
    <div className="section fade-in">
      <div className="container">
      <h2 className="section-title">🎯 키워드 경쟁강도 분석</h2>

      <div className="card" style={{ padding: '24px' }}>
        {/* 상단: 백분율 + 라벨 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
            <span style={{ fontSize: 36, fontWeight: 800, color: compColor }}>{pct}%</span>
            <span style={{
              background: compColor, color: '#fff',
              padding: '5px 16px', borderRadius: 999,
              fontSize: 13, fontWeight: 700
            }}>
              {compLabel}
            </span>
          </div>
          <div style={{ textAlign: 'right', fontSize: 12, color: '#6b7280', lineHeight: 1.8 }}>
            <div>경쟁지수: {fmt(compIndex)}</div>
            <div>(상품수 ÷ 검색량)</div>
          </div>
        </div>

        {/* 가로 막대 차트 — 3구간 */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ position: 'relative', height: 32, borderRadius: 8, overflow: 'hidden', background: '#f1f5f9' }}>
            {/* 3구간 배경 */}
            <div style={{ position: 'absolute', top: 0, left: 0, width: '30%', height: '100%', background: 'linear-gradient(90deg, #d1fae5, #a7f3d0)', borderRight: '2px solid #fff' }} />
            <div style={{ position: 'absolute', top: 0, left: '30%', width: '40%', height: '100%', background: 'linear-gradient(90deg, #fef3c7, #fde68a)', borderRight: '2px solid #fff' }} />
            <div style={{ position: 'absolute', top: 0, left: '70%', width: '30%', height: '100%', background: 'linear-gradient(90deg, #fecaca, #fca5a5)' }} />

            {/* 현재 위치 마커 */}
            <div style={{
              position: 'absolute', top: -2, left: 'calc(' + pct + '% - 14px)',
              width: 28, height: 36, borderRadius: 6,
              background: compColor, border: '3px solid #fff',
              boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'left 0.8s ease'
            }}>
              <span style={{ color: '#fff', fontSize: 10, fontWeight: 800 }}>{pct}</span>
            </div>
          </div>
          {/* 구간 라벨 */}
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 11, color: '#94a3b8' }}>
            <span>0%</span>
            <span style={{ position: 'relative', left: '-5%' }}>블루오션 (30%)</span>
            <span>보통 (70%)</span>
            <span>레드오션 (100%)</span>
          </div>
        </div>

        {/* 시장 현황 카드 3개 */}
        <div className="comp-detail-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
          <div style={{ background: '#f8fafc', borderRadius: 10, padding: '14px 16px', textAlign: 'center', border: '1px solid #e2e8f0' }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>등록 상품수</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#1e293b' }}>{fmt(productCount)}<span style={{ fontSize: 12, fontWeight: 400 }}>개</span></div>
          </div>
          <div style={{ background: '#f8fafc', borderRadius: 10, padding: '14px 16px', textAlign: 'center', border: '1px solid #e2e8f0' }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>월간 검색량</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#1e293b' }}>{fmt(searchVolume)}<span style={{ fontSize: 12, fontWeight: 400 }}>회</span></div>
          </div>
          <div style={{ background: '#f8fafc', borderRadius: 10, padding: '14px 16px', textAlign: 'center', border: '1px solid #e2e8f0' }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>평균 클릭수</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#1e293b' }}>{typeof avgCtr === 'number' ? avgCtr.toFixed(1) : avgCtr}<span style={{ fontSize: 12, fontWeight: 400 }}>회</span></div>
          </div>
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
