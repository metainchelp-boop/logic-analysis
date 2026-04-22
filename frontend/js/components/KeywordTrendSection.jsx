/* KeywordTrendSection — 키워드 검색량 비교 및 진입 난이도 (v5) */
window.KeywordTrendSection = function KeywordTrendSection(props) {
  if (!props?.data) return null;
  const { mainKeyword, subKeyword, mainVolume, subVolume, mainDifficulty, subDifficulty, mainDiffColor, subDiffColor, monthlyTrend } = props.data;

  if (!mainKeyword || !subKeyword || mainVolume === undefined || subVolume === undefined) return null;

  var v5Card = { borderRadius: 16, background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' };

  const maxVolume = Math.max(mainVolume, subVolume) || 1;
  const mainBarH = Math.max(12, (mainVolume / maxVolume) * 140);
  const subBarH = Math.max(12, (subVolume / maxVolume) * 140);

  var getDiffBadge = function(color) {
    if (!color) return { bg: '#f1f5f9', text: '#64748b', label: '-' };
    if (color === '#16a34a' || color === '#22c55e') return { bg: '#ecfdf5', text: '#10b981', label: '낮음' };
    if (color === '#f59e0b' || color === '#eab308') return { bg: '#fffbeb', text: '#f59e0b', label: '중간' };
    if (color === '#dc2626' || color === '#ef4444' || color === '#ea580c') return { bg: '#fef2f2', text: '#ef4444', label: '높음' };
    return { bg: '#f1f5f9', text: '#64748b', label: '-' };
  };

  var mainBadge = getDiffBadge(mainDiffColor);
  var subBadge = getDiffBadge(subDiffColor);

  var totalVol = mainVolume + subVolume;
  var mainPct = totalVol > 0 ? Math.round(mainVolume / totalVol * 100) : 50;
  var subPct = totalVol > 0 ? Math.round(subVolume / totalVol * 100) : 50;

  /* 12개월 트렌드 SVG 미니차트 */
  var renderTrendChart = function() {
    if (!monthlyTrend || !Array.isArray(monthlyTrend) || monthlyTrend.length < 2) return null;

    var values = monthlyTrend.map(function(item) { return typeof item === 'object' ? (item.value || item.volume || item.count || 0) : item; });
    var labels = monthlyTrend.map(function(item, idx) { return typeof item === 'object' ? (item.label || item.month || (idx + 1) + '월') : (idx + 1) + '월'; });
    var max = Math.max.apply(null, values) || 1;
    var min = Math.min.apply(null, values);
    var svgW = 520, svgH = 120, padX = 10, padY = 10;
    var usableW = svgW - padX * 2, usableH = svgH - padY * 2;

    var points = values.map(function(v, i) {
      var x = padX + (i / (values.length - 1)) * usableW;
      var y = padY + usableH - ((v - min) / (max - min || 1)) * usableH;
      return x + ',' + y;
    });

    var lastVal = values[values.length - 1];
    var prevVal = values[values.length - 2];
    var change = prevVal > 0 ? Math.round((lastVal - prevVal) / prevVal * 100) : 0;
    var changeColor = change >= 0 ? '#10b981' : '#ef4444';

    return React.createElement('div', { style: { ...v5Card, padding: 24, marginBottom: 16 } },
      React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } },
        React.createElement('div', { style: { fontSize: 14, fontWeight: 700, color: '#0f172a' } }, '12개월 검색량 추이'),
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12 } },
          React.createElement('span', { style: { fontSize: 11, color: '#94a3b8' } }, '이번 달'),
          React.createElement('span', { style: { fontSize: 18, fontWeight: 800, color: '#4f46e5' } }, fmt(lastVal)),
          React.createElement('span', { style: { padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700, background: change >= 0 ? '#ecfdf5' : '#fef2f2', color: changeColor } },
            (change >= 0 ? '+' : '') + change + '%'
          )
        )
      ),
      React.createElement('svg', { viewBox: '0 0 ' + svgW + ' ' + svgH, style: { width: '100%', height: 120 } },
        /* area fill */
        React.createElement('polygon', {
          points: padX + ',' + (padY + usableH) + ' ' + points.join(' ') + ' ' + (padX + usableW) + ',' + (padY + usableH),
          fill: 'url(#trendGrad)', opacity: 0.3
        }),
        React.createElement('defs', null,
          React.createElement('linearGradient', { id: 'trendGrad', x1: '0', y1: '0', x2: '0', y2: '1' },
            React.createElement('stop', { offset: '0%', stopColor: '#4f46e5', stopOpacity: 0.4 }),
            React.createElement('stop', { offset: '100%', stopColor: '#4f46e5', stopOpacity: 0.02 })
          )
        ),
        /* line */
        React.createElement('polyline', {
          points: points.join(' '),
          fill: 'none', stroke: '#4f46e5', strokeWidth: 2.5, strokeLinecap: 'round', strokeLinejoin: 'round'
        }),
        /* dots */
        values.map(function(v, i) {
          var x = padX + (i / (values.length - 1)) * usableW;
          var y = padY + usableH - ((v - min) / (max - min || 1)) * usableH;
          return React.createElement('circle', { key: i, cx: x, cy: y, r: 3, fill: '#4f46e5', stroke: '#fff', strokeWidth: 1.5 });
        })
      ),
      /* month labels */
      React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 10, color: '#94a3b8' } },
        labels.map(function(l, i) { return React.createElement('span', { key: i }, l); })
      )
    );
  };

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' }}>📈</span>
          키워드 검색량 비교 및 진입 난이도
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">대표 키워드와 서브 키워드의 검색량·난이도를 비교합니다</p>

        {/* 12개월 트렌드 차트 (데이터가 있을 때만) */}
        {renderTrendChart()}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {/* Left: Volume Comparison */}
          <div style={{ ...v5Card, padding: 24 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 16 }}>월간 검색량 비교</div>
            <div style={{
              background: '#f8fafc', borderRadius: 12, padding: 24,
              border: '1px solid #e2e8f0'
            }}>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 32, height: 160, marginBottom: 16, justifyContent: 'center' }}>
                <div style={{ flex: '0 0 35%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 800, color: '#4f46e5', marginBottom: 8 }}>{fmt(mainVolume)}</div>
                  <div style={{
                    width: '100%', height: mainBarH + 'px',
                    background: 'linear-gradient(180deg, #4f46e5 0%, #818cf8 100%)',
                    borderRadius: '10px 10px 4px 4px', transition: 'height 0.6s ease',
                    boxShadow: '0 4px 12px rgba(79,70,229,0.2)'
                  }}></div>
                </div>
                <div style={{ flex: '0 0 35%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 800, color: '#10b981', marginBottom: 8 }}>{fmt(subVolume)}</div>
                  <div style={{
                    width: '100%', height: subBarH + 'px',
                    background: 'linear-gradient(180deg, #10b981 0%, #6ee7b7 100%)',
                    borderRadius: '10px 10px 4px 4px', transition: 'height 0.6s ease',
                    boxShadow: '0 4px 12px rgba(16,185,129,0.2)'
                  }}></div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 24, justifyContent: 'center', fontSize: 12, color: '#64748b' }}>
                <span><span style={{ display: 'inline-block', width: 12, height: 12, background: '#4f46e5', borderRadius: 3, marginRight: 6, verticalAlign: 'middle' }}></span>{mainKeyword} ({mainPct}%)</span>
                <span><span style={{ display: 'inline-block', width: 12, height: 12, background: '#10b981', borderRadius: 3, marginRight: 6, verticalAlign: 'middle' }}></span>{subKeyword} ({subPct}%)</span>
              </div>
            </div>

            {/* 비율 바 */}
            <div style={{ marginTop: 16 }}>
              <div style={{ display: 'flex', height: 36, borderRadius: 10, overflow: 'hidden' }}>
                <div style={{
                  width: mainPct + '%', background: 'linear-gradient(135deg, #4f46e5, #818cf8)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: '#fff', fontSize: 12, fontWeight: 700,
                  minWidth: mainPct > 10 ? 'auto' : '0'
                }}>
                  {mainPct > 15 ? mainPct + '%' : ''}
                </div>
                <div style={{
                  width: subPct + '%', background: 'linear-gradient(135deg, #10b981, #6ee7b7)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: '#fff', fontSize: 12, fontWeight: 700
                }}>
                  {subPct > 15 ? subPct + '%' : ''}
                </div>
              </div>
            </div>
          </div>

          {/* Right: Difficulty */}
          <div style={{ ...v5Card, padding: 24 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 16 }}>진입 난이도 분석</div>
            <div style={{
              background: '#f8fafc', borderRadius: 12, padding: 20,
              border: '1px solid #e2e8f0'
            }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {/* Main keyword difficulty */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: 16, background: '#fff', borderRadius: 12,
                  border: '1px solid #e2e8f0'
                }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{mainKeyword}</div>
                    <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>대표 키워드</div>
                  </div>
                  <span style={{
                    background: mainBadge.bg, color: mainBadge.text,
                    padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700
                  }}>{mainBadge.label}</span>
                </div>
                {/* Sub keyword difficulty */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: 16, background: '#fff', borderRadius: 12,
                  border: '1px solid #e2e8f0'
                }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{subKeyword}</div>
                    <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>서브 키워드</div>
                  </div>
                  <span style={{
                    background: subBadge.bg, color: subBadge.text,
                    padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700
                  }}>{subBadge.label}</span>
                </div>
              </div>

              {/* 난이도 기준 안내 */}
              <div style={{
                marginTop: 16, padding: '12px 14px',
                background: '#fff', borderRadius: 10, border: '1px solid #e2e8f0',
                fontSize: 12, color: '#64748b', lineHeight: 1.7
              }}>
                <strong>난이도 기준:</strong> 🟢 낮음(0-40) → 🟡 중간(40-60) → 🔴 높음(60-100)
              </div>
            </div>

            {/* 인사이트 박스 */}
            <div style={{
              marginTop: 16, padding: '14px 18px',
              background: '#f0fdf4', borderRadius: 12,
              border: '1px solid #bbf7d0', fontSize: 13, color: '#166534', lineHeight: 1.6
            }}>
              {mainVolume > subVolume
                ? '💡 대표 키워드 "' + mainKeyword + '"의 검색량이 ' + (mainVolume > subVolume * 2 ? '크게 ' : '') + '더 높습니다. ' + (mainBadge.label === '높음' ? '경쟁이 치열하므로 서브 키워드 병행 전략을 추천합니다.' : '메인 키워드 중심 전략이 유효합니다.')
                : '💡 서브 키워드 "' + subKeyword + '"의 검색량이 더 높습니다. 서브 키워드 기반 진입을 먼저 고려해보세요.'
              }
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
