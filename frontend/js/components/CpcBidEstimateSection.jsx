/* CpcBidEstimateSection — 키워드 예상 CPC·권장 입찰가 (추정)
 * 네이버는 실제 CPC를 제공하지 않으므로, 경쟁지수(실값)+클릭량(실값) 기반의
 * 투명한 추정 밴드로 제시. 절대값이 아니라 '기준선'임을 강하게 고지. */
window.CpcBidEstimateSection = function CpcBidEstimateSection(props) {
  var vol = (props.volumeData && props.volumeData.length) ? props.volumeData[0] : null;
  var keyword = props.keyword || '';
  if (!vol) return null;

  var comp = (vol.compIdx || '').trim();
  // 경쟁지수 → 업종 일반 CPC 밴드(원). 네이버 미제공 → 휴리스틱.
  var bandMap = {
    '높음': { base: 900, low: 700, high: 1200 },
    '중간': { base: 500, low: 350, high: 700 },
    '낮음': { base: 300, low: 200, high: 450 }
  };
  var band = bandMap[comp] || bandMap['중간'];

  var clicks = Math.round((Number(vol.monthlyAvePcClkCnt) || 0) + (Number(vol.monthlyAveMobileClkCnt) || 0));
  var volTotal = (Number(vol.monthlyPcQcCnt) || 0) + (Number(vol.monthlyMobileQcCnt) || 0);
  // 예상 월 광고비(중간 입찰가 × 예상 유입 클릭의 일부). 보수적으로 클릭의 30% 확보 가정.
  var assumedClicks = Math.max(Math.round(clicks * 0.3), 0);
  var estSpendMid = assumedClicks * band.base;

  var won = function(v) { return fmt(Math.round(v)) + '원'; };

  var Kpi = function(k, v, sub, color) {
    return React.createElement('div', { className: 'kpi' },
      React.createElement('div', { className: 'k' }, k),
      React.createElement('div', { className: 'v', style: { fontSize: 18, color: color || undefined } }, v),
      sub ? React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginTop: 2 } }, sub) : null
    );
  };

  return React.createElement('div', { className: 'section fade-in' },
    React.createElement('div', { className: 'container' },
      React.createElement('div', { className: 'card', style: { padding: '20px 22px' } },
        React.createElement('h3', { className: 'rt-h3' },
          React.createElement('span', { className: 'rt-hic' }, '💸'),
          '예상 CPC · 권장 입찰가',
          React.createElement('span', { className: 'badge b-est' }, '≈ 추정')
        ),
        React.createElement('div', { className: 'rt-desc' },
          (keyword ? '"' + keyword + '" ' : '') + '경쟁지수 "' + (comp || '중간') + '" · 월 검색량 ' + fmt(volTotal) + '회 기준 추정'
        ),

        React.createElement('div', { className: 'grid4', style: { marginTop: 10 } },
          Kpi('예상 CPC(중간)', won(band.base), '클릭당 예상 단가', '#0f172a'),
          Kpi('권장 입찰가 범위', fmt(band.low) + '~' + fmt(band.high) + '원', '저가~상위노출가'),
          Kpi('예상 월 클릭', fmt(clicks) + '회', '네이버 실측 평균클릭'),
          Kpi('예상 월 광고비', '~' + won(estSpendMid), '클릭 30% 확보 가정', '#4f46e5')
        ),

        React.createElement('div', {
          style: { marginTop: 14, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }
        },
          React.createElement('table', { className: 'rt-table', style: { margin: 0 } },
            React.createElement('thead', null,
              React.createElement('tr', null,
                React.createElement('th', null, '전략'),
                React.createElement('th', { style: { textAlign: 'right' } }, '입찰가(추정)'),
                React.createElement('th', null, '기대 효과')
              )
            ),
            React.createElement('tbody', null,
              React.createElement('tr', null,
                React.createElement('td', null, '저가 진입'),
                React.createElement('td', { style: { textAlign: 'right' } }, won(band.low)),
                React.createElement('td', null, '노출 제한적·광고비 절약 (SEO 병행 권장)')
              ),
              React.createElement('tr', null,
                React.createElement('td', null, '표준'),
                React.createElement('td', { style: { textAlign: 'right', fontWeight: 700 } }, won(band.base)),
                React.createElement('td', null, '평균적 노출 확보')
              ),
              React.createElement('tr', null,
                React.createElement('td', null, '상위 노출'),
                React.createElement('td', { style: { textAlign: 'right' } }, won(band.high)),
                React.createElement('td', null, '상단 노출 경쟁 우위 (광고비 부담↑)')
              )
            )
          )
        ),

        React.createElement('div', {
          style: { marginTop: 12, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 10, fontSize: 11.5, color: '#92400e', lineHeight: 1.6 }
        }, '※ 네이버는 키워드별 실제 CPC를 제공하지 않습니다. 위 값은 경쟁지수·클릭량 기반 <b>업종 일반 추정 밴드</b>로, 실제 입찰 단가는 광고 시스템의 실시간 경쟁·품질지수에 따라 달라집니다. 집행 전 네이버 검색광고 관리시스템에서 실제 예상 입찰가를 확인하세요.')
      )
    )
  );
};
