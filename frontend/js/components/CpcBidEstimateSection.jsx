/* CpcBidEstimateSection — 키워드 예상 CPC·권장 입찰가 (추정)
 * 네이버는 실제 CPC를 제공하지 않으므로, 경쟁지수(실값)+클릭량(실값) 기반의
 * 투명한 추정 밴드로 제시. 절대값이 아니라 '기준선'임을 강하게 고지.
 *
 * + 파워링크 순위별 입찰가 (건의 2026-07-22, 이예은 — 시안 v1 확정):
 *   네이버 검색광고 공식 '입찰가 추정' API로 1~5위 평균 노출 입찰가(PC/모바일) 표를 추가.
 *   데이터 미수신/실패 시 신규 표만 조용히 빠지고 기존 화면과 100% 동일(자동 폴백).
 *   보고서는 화면 DOM을 그대로 복제하므로 이 표가 보고서에도 자동 포함된다. */
window.CpcBidEstimateSection = function CpcBidEstimateSection(props) {
  var keyword = props.keyword || '';

  /* 파워링크 공식 입찰가 — hooks는 조기 return 이전에 선언(Rules of Hooks) */
  var _bs = React.useState(null); var bidData = _bs[0]; var setBidData = _bs[1];
  React.useEffect(function() {
    setBidData(null);
    if (!keyword) return;
    var alive = true;
    var call = function(canRetry) {
      api.post('/keyword/bid-estimate', { keyword: keyword }).then(function(res) {
        if (!alive) return;
        var d = (res && res.success && res.data) || null;
        if (d && ((d.pc || []).length > 0 || (d.mobile || []).length > 0)) {
          setBidData(d);
        } else if (canRetry) {
          setTimeout(function() { if (alive) call(false); }, 3000); // 순간 실패 1회 재조회(검수 철학)
        }
      }).catch(function() {
        if (alive && canRetry) setTimeout(function() { if (alive) call(false); }, 3000);
      });
    };
    call(true);
    return function() { alive = false; };
  }, [keyword]);

  var vol = (props.volumeData && props.volumeData.length) ? props.volumeData[0] : null;
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

  /* 파워링크 순위별 입찰가 표 (공식 데이터 있을 때만 — 시안 A) */
  var bidTable = null;
  if (bidData) {
    var byPos = {};
    (bidData.pc || []).forEach(function(r) { byPos[r.position] = byPos[r.position] || {}; byPos[r.position].pc = r.bid; });
    (bidData.mobile || []).forEach(function(r) { byPos[r.position] = byPos[r.position] || {}; byPos[r.position].mo = r.bid; });
    var positions = [1, 2, 3, 4, 5].filter(function(p) { return byPos[p]; });
    var cellR = function(v, bold) {
      return React.createElement('td', { style: { textAlign: 'right', fontWeight: bold ? 800 : undefined } }, v != null ? won(v) : '—');
    };
    var rows = positions.map(function(p) {
      return React.createElement('tr', { key: p },
        React.createElement('td', null, p === 1 ? React.createElement('b', null, '1위') : (p + '위')),
        cellR(byPos[p].pc, p === 1),
        cellR(byPos[p].mo, p === 1)
      );
    });
    var mb = bidData.minBid || {};
    if (mb.pc != null || mb.mobile != null) {
      rows.push(React.createElement('tr', { key: 'min', style: { background: '#f8fafc' } },
        React.createElement('td', { style: { color: '#64748b' } }, '최소 노출가'),
        React.createElement('td', { style: { textAlign: 'right', color: '#64748b' } }, mb.pc != null ? won(mb.pc) : '—'),
        React.createElement('td', { style: { textAlign: 'right', color: '#64748b' } }, mb.mobile != null ? won(mb.mobile) : '—')
      ));
    }
    if (rows.length > 0) {
      bidTable = React.createElement('div', {
        style: { marginTop: 14, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }
      },
        React.createElement('div', { style: { padding: '10px 14px 0', fontSize: 13, fontWeight: 800, color: '#0f172a' } },
          '🎯 파워링크 순위별 입찰가 ',
          React.createElement('span', { className: 'badge b-ok' }, '네이버 공식 추정')
        ),
        React.createElement('div', { style: { padding: '2px 14px 8px', fontSize: 11.5, color: '#64748b' } },
          '네이버 검색광고 API의 순위별 평균 노출 입찰가 — 광고시스템 콘솔의 \'예상 입찰가\'와 같은 소스'),
        React.createElement('table', { className: 'rt-table', style: { margin: 0 } },
          React.createElement('thead', null,
            React.createElement('tr', null,
              React.createElement('th', { style: { width: 90 } }, '노출 순위'),
              React.createElement('th', { style: { textAlign: 'right' } }, 'PC 입찰가'),
              React.createElement('th', { style: { textAlign: 'right' } }, '모바일 입찰가')
            )
          ),
          React.createElement('tbody', null, rows)
        )
      );
    }
  }

  return React.createElement('div', { className: 'section fade-in' },
    React.createElement('div', { className: 'container' },
      React.createElement('div', { className: 'card', style: { padding: '20px 22px' } },
        React.createElement('h3', { className: 'rt-h3' },
          React.createElement('span', { className: 'rt-hic' }, '💸'),
          '예상 CPC · 권장 입찰가',
          React.createElement('span', { className: 'badge b-est' }, '≈ 추정'),
          bidTable ? React.createElement('span', { className: 'badge b-ok' }, '✅ 파워링크 공식 추정 포함') : null
        ),
        React.createElement('div', { className: 'rt-desc' },
          (keyword ? '"' + keyword + '" ' : '') + '경쟁지수 "' + (comp || '중간') + '" · 월 검색량 ' + fmt(volTotal) + '회 기준 추정'
          + (bidTable ? ' + 네이버 검색광고 공식 입찰가 추정' : '')
        ),

        React.createElement('div', { className: 'grid4', style: { marginTop: 10 } },
          Kpi('예상 CPC(중간)', won(band.base), '클릭당 예상 단가', '#0f172a'),
          Kpi('권장 입찰가 범위', fmt(band.low) + '~' + fmt(band.high) + '원', '저가~상위노출가'),
          Kpi('예상 월 클릭', fmt(clicks) + '회', '네이버 실측 평균클릭'),
          Kpi('예상 월 광고비', '~' + won(estSpendMid), '클릭 30% 확보 가정', '#4f46e5')
        ),

        bidTable,

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
        }, bidTable
          ? '※ 순위별 입찰가는 네이버 검색광고의 공식 추정치(최근 실제 입찰·노출 데이터 기반)입니다. 단 실시간 낙찰가는 아니며, 품질지수·순간 경쟁에 따라 실제 지불 단가는 달라질 수 있습니다. 위 전략 밴드는 기존 경쟁지수 기반 참고 추정입니다.'
          : '※ 네이버는 키워드별 실제 CPC를 제공하지 않습니다. 위 값은 경쟁지수·클릭량 기반 업종 일반 추정 밴드로, 실제 입찰 단가는 광고 시스템의 실시간 경쟁·품질지수에 따라 달라집니다. 집행 전 네이버 검색광고 관리시스템에서 실제 예상 입찰가를 확인하세요.')
      )
    )
  );
};
