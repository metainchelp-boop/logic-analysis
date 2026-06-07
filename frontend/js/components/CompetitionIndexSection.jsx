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
          {/* 좌: 원형 도넛 게이지 — 가운데에 경쟁지수 숫자 */}
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
            <div style={{ position: 'relative', width: 172, height: 172 }}>
              <ChartCanvas
                type="doughnut"
                height={172}
                style={{ height: 172, width: 172 }}
                data={{
                  labels: ['경쟁', '여유'],
                  datasets: [{ data: [pct, Math.max(0, 100 - pct)], backgroundColor: [compColor, (window.CHART_COLORS || {}).GRID || '#eef2f7'], borderWidth: 0 }]
                }}
                options={{
                  cutout: '70%',
                  plugins: { legend: { display: false }, tooltip: { enabled: false } }
                }}
              />
              {/* 중앙 오버레이: 경쟁지수 숫자 + 라벨 */}
              <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 900, color: compColor, lineHeight: 1.1 }}>{fmt(compIndex)}</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>경쟁지수</div>
                <div style={{ fontSize: 11, fontWeight: 700, color: compColor, marginTop: 2 }}>{compLabel}</div>
              </div>
            </div>
          </div>

          {/* 우: 3구간 밴드 + 핵심 지표 */}
          <div>
            <div className="band"><span className="mk" style={{ left: 'calc(' + pct + '% - 2px)' }}></span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#64748b' }}>
              <span>블루오션</span><span>보통</span><span>레드오션</span>
            </div>
            <div className="grid3" style={{ marginTop: 14 }}>
              <div className="kpi"><div className="k">등록 상품수</div><div className="v" style={{ fontSize: 18 }}>{fmt(productCount)}</div></div>
              <div className="kpi"><div className="k">월간 검색량</div><div className="v" style={{ fontSize: 18 }}>{fmt(searchVolume)}</div></div>
              <div className="kpi"><div className="k">평균 클릭수</div><div className="v" style={{ fontSize: 18 }}>{fmt(avgCtr)}</div></div>
            </div>
          </div>
        </div>

        {/* 코멘트 — 시안 톤(note): 경쟁지수(레벨) + 해석 */}
        <div className="note">경쟁지수 {fmt(compIndex)}({compLabel}){interpretation ? '. ' + interpretation : '.'}</div>
      </div>
      </div>
    </div>
  );
};
