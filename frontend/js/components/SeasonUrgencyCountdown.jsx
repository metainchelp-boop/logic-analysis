/* SeasonUrgencyCountdown — 성수기 긴급성 안내 (데이터랩 시즌 데이터에서 파생)
 * 성수기가 식별될 때만 노출. 비수기엔 역효과 없는 톤으로 안내. */
window.SeasonUrgencyCountdown = function SeasonUrgencyCountdown(props) {
  var season = props.season; // datalabData.season
  if (!season || !season.seasons || !season.seasons.length) return null;

  var seasons = season.seasons;
  var peak = null;
  seasons.forEach(function(s) {
    if (!s) return;
    if (s.peakSeason || s.grade === '최성수기') { if (!peak || (s.index || 0) > (peak.index || 0)) peak = s; }
  });
  // 최성수기 라벨이 없으면 지수 최고 시즌을 성수기로 간주
  if (!peak) {
    seasons.forEach(function(s) { if (s && (!peak || (s.index || 0) > (peak.index || 0))) peak = s; });
  }
  if (!peak || !peak.period) return null;

  // "6월 ~ 8월" → 시작월 6
  var mm = String(peak.period).match(/(\d{1,2})\s*월/);
  var startMonth = mm ? parseInt(mm[1], 10) : null;
  if (!startMonth) return null;
  // 끝월(있으면)
  var mm2 = String(peak.period).match(/~\s*(\d{1,2})\s*월/);
  var endMonth = mm2 ? parseInt(mm2[1], 10) : startMonth;

  var now = new Date();
  var curMonth = now.getMonth() + 1; // 1~12

  // 상태 판정
  var inPeak = (startMonth <= endMonth)
    ? (curMonth >= startMonth && curMonth <= endMonth)
    : (curMonth >= startMonth || curMonth <= endMonth); // 겨울처럼 연말~연초 걸침
  var monthsUntil;
  if (inPeak) {
    monthsUntil = 0;
  } else {
    monthsUntil = startMonth - curMonth;
    if (monthsUntil < 0) monthsUntil += 12;
  }

  var box, msg, emoji, col, bg, bd;
  if (inPeak) {
    emoji = '⏰'; col = '#b91c1c'; bg = '#fef2f2'; bd = '#fecaca';
    box = '성수기 진행 중';
    msg = '지금이 ' + peak.name + '(' + peak.period + ') 성수기입니다. 광고·프로모션을 집중할 최적 타이밍입니다.';
  } else if (monthsUntil <= 2) {
    emoji = '🔥'; col = '#c2410c'; bg = '#fff7ed'; bd = '#fed7aa';
    box = '성수기 D-' + monthsUntil + '개월';
    msg = peak.name + ' 성수기(' + peak.period + ')까지 약 ' + monthsUntil + '개월. 지금부터 상품·상세페이지·리뷰를 준비해야 성수기에 상위 노출을 선점합니다.';
  } else {
    emoji = '🗓️'; col = '#475569'; bg = '#f8fafc'; bd = '#e2e8f0';
    box = '다음 성수기까지 ' + monthsUntil + '개월';
    msg = peak.name + ' 성수기(' + peak.period + ')까지 여유가 있습니다. 지금은 비수기 전략(기초 리뷰 확보·콘텐츠 정비)으로 준비하세요.';
  }

  return React.createElement('div', { className: 'section fade-in' },
    React.createElement('div', { className: 'container' },
      React.createElement('div', {
        className: 'card',
        style: { padding: '16px 20px', background: bg, border: '1px solid ' + bd, display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }
      },
        React.createElement('div', { style: { display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 96 } },
          React.createElement('div', { style: { fontSize: 26 } }, emoji),
          React.createElement('div', { style: { fontSize: 13, fontWeight: 800, color: col, textAlign: 'center' } }, box)
        ),
        React.createElement('div', { style: { flex: 1, minWidth: 220 } },
          React.createElement('div', { style: { fontSize: 13.5, fontWeight: 700, color: '#1e293b', marginBottom: 4 } }, '⏱️ 시즌 타이밍 안내'),
          React.createElement('div', { style: { fontSize: 12.5, color: '#475569', lineHeight: 1.6 } }, msg)
        )
      )
    )
  );
};
