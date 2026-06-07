window.CompetitionIndexSection = function CompetitionIndexSection(props) {
  if (!props?.data) return null;
  const { compIndex, compPercent, compLabel, compColor, productCount, searchVolume, avgCtr, interpretation } = props.data;

  if (compPercent === undefined && compIndex === undefined) return null;

  var pct = typeof compPercent === 'number' ? compPercent : Math.min(98, Math.round(Math.log10(compIndex * 10 + 1) / Math.log10(101) * 100));

  return (
    <div className="section fade-in">
      <div className="container">
      <div className="card" style={{ padding: '20px 22px' }}>
        <h3 className="rt-h3"><span className="rt-hic">⚔️</span>키워드 경쟁강도 분석<span className="badge b-ok">✅ 실측</span></h3>
        <div className="rt-desc">상품 수 대비 검색량으로 경쟁 수준을 판단합니다</div>

        {/* 시안 구조: 좌측 반원 게이지 + 우측 밴드·KPI (세로 중앙 정렬) */}
        <div className="grid2" style={{ alignItems: 'center' }}>
          {/* 좌: 반원 게이지 — 점수는 아크 중앙 하단, 등급·경쟁지수는 그래프 바로 아래 중앙 */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ position: 'relative', width: 230, height: 122 }}>
              <ChartCanvas
                type="doughnut"
                height={230}
                style={{ height: 230, width: 230, position: 'absolute', top: 0, left: 0 }}
                data={{
                  labels: ['경쟁', '여유'],
                  datasets: [{ data: [pct, Math.max(0, 100 - pct)], backgroundColor: [compColor, (window.CHART_COLORS || {}).GRID || '#eef2f7'], borderWidth: 0 }]
                }}
                options={{
                  rotation: -90, circumference: 180, cutout: '68%',
                  plugins: { legend: { display: false }, tooltip: { enabled: false } }
                }}
              />
              {/* 점수: 아크 중앙 하단 */}
              <div style={{ position: 'absolute', bottom: 2, left: 0, width: '100%', textAlign: 'center', fontSize: 38, fontWeight: 900, color: compColor, lineHeight: 1 }}>{pct}</div>
            </div>
            {/* 등급 + 경쟁지수: 그래프 바로 아래 중앙 */}
            <div style={{ textAlign: 'center', marginTop: 10 }}>
              <span style={{
                display: 'inline-block', background: compColor, color: '#fff',
                padding: '4px 16px', borderRadius: 999, fontSize: 13, fontWeight: 700
              }}>{compLabel}</span>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>경쟁지수: {fmt(compIndex)}</div>
            </div>
          </div>

          {/* 우: 3구간 밴드 + 핵심 지표 */}
          <div>
            <div className="band"><span className="mk" style={{ left: 'calc(' + pct + '% - 2px)' }}></span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#64748b' }}>
              <span>블루오션</span><span>보통</span><span>레드오션</span>
            </div>
            <div className="grid3" style={{ marginTop: 14 }}>
              <div className="kpi"><div className="k">등록 상품수</div><div className="v" style={{ fontSize: 18 }}>{fmt(productCount)}<small>개</small></div></div>
              <div className="kpi"><div className="k">월간 검색량</div><div className="v" style={{ fontSize: 18 }}>{fmt(searchVolume)}<small>회</small></div></div>
              <div className="kpi"><div className="k">평균 클릭수</div><div className="v" style={{ fontSize: 18 }}>{typeof avgCtr === 'number' ? avgCtr.toFixed(1) : avgCtr}<small>회</small></div></div>
            </div>
          </div>
        </div>

        {/* 전문 코멘트 — 시안 톤(note) */}
        {interpretation && (
          <div className="note">
            <b style={{ color: '#0369a1' }}>📋 시장 분석 코멘트</b><br/>
            {interpretation}
          </div>
        )}
      </div>
      </div>
    </div>
  );
};
