/* METAINC 플레이스 순위 추적기 — 팝업 (v1.0.0) : 상태 표시 + 지금 수집 + ON/OFF */
(function () {
  'use strict';
  var enabledNow = true;

  function $(id) { return document.getElementById(id); }
  function fmtTime(ts) {
    if (!ts) return '-';
    var d = new Date(ts);
    var mm = ('0' + (d.getMonth() + 1)).slice(-2), dd = ('0' + d.getDate()).slice(-2);
    var hh = ('0' + d.getHours()).slice(-2), mi = ('0' + d.getMinutes()).slice(-2);
    return mm + '-' + dd + ' ' + hh + ':' + mi;
  }

  function render(st) {
    if (!st || !st.ok) { $('state').textContent = '연결 안 됨'; return; }
    enabledNow = !!st.enabled;
    $('enabled').textContent = st.enabled ? 'ON' : 'OFF';
    $('enabled').className = 'v ' + (st.enabled ? 'ok' : 'warn');
    $('next').textContent = st.enabled ? fmtTime(st.nextRunAt) : '중지됨';
    $('targets').textContent = st.targets + '건' + (st.syncedAt ? '' : ' (미동기화)');
    $('state').textContent = st.running
      ? ('수집 중 ' + ((st.progress && (st.progress.idx + '/' + st.progress.total)) || ''))
      : (st.pending ? '결과 전달 대기' : '대기');
    var lr = st.lastRun;
    $('last').textContent = !lr ? '-'
      : lr.skipped ? (fmtTime(lr.finishedAt) + ' (' + (lr.skipped === 'no-targets' ? '대상 없음' : '중지됨') + ')')
      : (fmtTime(lr.finishedAt) + ' · 노출 ' + (lr.exposed || 0) + '·미노출 ' + (lr.missing || 0)
         + (lr.unknown ? '·미확인 ' + lr.unknown : '')
         + (lr.depthMax ? ' · 판독 ' + (lr.depthMin && lr.depthMin !== lr.depthMax ? lr.depthMin + '~' : '~') + lr.depthMax + '위' : '')
         + (lr.delivered ? ' ✓기록' : ' (기록 대기)'));
    $('toggle').textContent = st.enabled ? '무인 추적 끄기' : '무인 추적 켜기';
  }

  function refresh() {
    try { chrome.runtime.sendMessage({ type: 'PLACE_STATUS' }, render); } catch (e) {}
  }

  $('run').addEventListener('click', function () {
    $('run').textContent = '수집 시작…';
    try {
      chrome.runtime.sendMessage({ type: 'PLACE_RUN' }, function () {
        setTimeout(refresh, 800);
        setTimeout(function () { $('run').textContent = '지금 전체 수집'; }, 1500);
      });
    } catch (e) {}
  });

  $('toggle').addEventListener('click', function () {
    try {
      chrome.runtime.sendMessage({ type: 'PLACE_TOGGLE', enabled: !enabledNow }, function () { refresh(); });
    } catch (e) {}
  });

  refresh();
  setInterval(refresh, 3000);
})();
