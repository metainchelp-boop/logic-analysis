/* METAINC 플레이스 순위 추적기 — 팝업 v1.1.0
 * 쇼핑 순위 수집기(v1.9.2) 팝업과 같은 구성(2026-08-28 대표 지시):
 * 오늘 진척(진행 막대·남은 것) + 결과 색 구분 + 진행 중 키워드 + 로그 창.
 * ⚠️ 수집 동작은 여기서 아무것도 바꾸지 않는다 — 러너 상태를 읽어 보여주기만 한다. */
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
  function isToday(ts) {
    if (!ts) return false;
    var a = new Date(ts), b = new Date();
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }
  function bar(done, total) {
    var pct = total ? Math.min(100, Math.round(done / total * 100)) : 0;
    return { pct: pct, html: '<div class="bar"><i style="width:' + pct + '%"></i></div>' };
  }

  function render(st) {
    if (!st || !st.ok) { $('stat').innerHTML = '확장이 응답하지 않습니다 — 새로고침(↻) 해 주세요'; return; }
    enabledNow = !!st.enabled;

    var head = '상태: ' + (st.running
        ? '<span class="b ok">수집 중</span>'
        : (st.pending ? '<span class="b wr">서버 기록 대기</span>' : '<span class="b">대기</span>'))
      + ' · 무인 추적 ' + (st.enabled ? '<span class="b ok">ON</span>' : '<span class="b wr">OFF</span>');

    var body = '';
    var lr = st.lastRun;
    if (st.running && st.progressDetail) {
      /* 수집이 도는 중 — 실시간 진척(쇼핑의 「오늘 진척」 자리) */
      var d = st.progressDetail;
      var b1 = bar(d.doneTargets, d.totalTargets);
      body += '<div class="sec"><b>오늘 수집</b> <span class="b ok">' + d.doneTargets + '</span> / '
        + d.totalTargets + '건 <span class="b">' + b1.pct + '%</span>' + b1.html
        + '<span class="dim">노출 ' + d.exposed + ' · 미노출 ' + d.missing
        + (d.unknown ? ' · <span class="wr">미확인 ' + d.unknown + '</span>' : '')
        + ' · 남은 것 ' + Math.max(0, d.totalTargets - d.doneTargets) + '건</span></div>';
      if (d.currentKeyword) body += '<div class="sec">진행 중: <b>' + d.currentKeyword + '</b></div>';
    } else if (lr && !lr.skipped && isToday(lr.finishedAt)) {
      /* 오늘 수집이 끝난 상태 — 하루 1회라 완료 요약이 곧 오늘 진척 */
      var total = lr.results || 0;
      var b2 = bar(total, total);
      body += '<div class="sec"><b>오늘 수집</b> <span class="b ok">' + total + '</span> / ' + total
        + '건 <span class="b">100%</span>' + b2.html
        + '<span class="dim">노출 <span class="ok b">' + (lr.exposed || 0) + '</span>'
        + ' · 미노출 ' + (lr.missing || 0)
        + (lr.unknown ? ' · <span class="wr">미확인 ' + lr.unknown + '</span>' : '')
        + (lr.depthMax ? ' · 판독 ' + (lr.depthMin && lr.depthMin !== lr.depthMax ? lr.depthMin + '~' : '~') + lr.depthMax + '위' : '')
        + ' · ' + (lr.delivered ? '✓ 서버 기록 완료' : '<span class="wr">서버 기록 대기</span>') + '</span></div>';
    } else {
      /* 오늘 아직 안 돌았다 — 대상 수와 다음 시각을 보여준다 */
      body += '<div class="sec"><b>오늘 수집</b> <span class="b">0</span> / ' + (st.targets || 0) + '건'
        + bar(0, 1).html
        + '<span class="dim">아직 오늘 수집 전'
        + (lr && lr.skipped ? ' — 마지막: ' + (lr.skipped === 'no-targets' ? '대상 없음' : '무인 추적 꺼짐') : '')
        + '</span></div>';
    }

    body += '<div class="sec dim">추적 대상 <b>' + (st.targets || 0) + '건</b>'
      + (st.syncedAt ? '' : ' <span class="wr">(미동기화)</span>')
      + ' · 다음 자동 수집 <b>' + (st.enabled ? fmtTime(st.nextRunAt) : '중지됨') + '</b>'
      + (lr && lr.finishedAt && !st.running ? '<br>마지막 완료: ' + fmtTime(lr.finishedAt) : '')
      + '</div>';

    $('stat').innerHTML = head + '<br>' + body;
    $('toggle').textContent = st.enabled ? '무인 추적 끄기' : '무인 추적 켜기';
  }

  function refresh() {
    try { chrome.runtime.sendMessage({ type: 'PLACE_STATUS' }, render); } catch (e) {}
    /* 로그는 러너가 storage 에 쌓는다(쇼핑 수집기와 같은 방식) — 직접 읽는다 */
    try {
      chrome.storage.local.get(['place_logs'], function (r) {
        $('logs').textContent = ((r && r.place_logs) || ['아직 기록 없음 — 첫 수집부터 여기에 남습니다']).join('\n');
      });
    } catch (e) {}
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
  $('refresh').addEventListener('click', refresh);
  $('toggle').addEventListener('click', function () {
    try {
      chrome.runtime.sendMessage({ type: 'PLACE_TOGGLE', enabled: !enabledNow }, function () { refresh(); });
    } catch (e) {}
  });

  refresh();
  setInterval(refresh, 3000);
})();

/* 버전은 manifest 에서 읽는다 — 팝업에 숫자를 박아두면 교체해도 옛 버전으로 보여
   '안 바뀌었다'는 오판을 부른다(2026-08-12 실사고). */
try {
  var _v = chrome.runtime.getManifest().version;
  var _e = document.getElementById('ver');
  if (_e) _e.textContent = 'v' + _v + ' · 무인 추적 · 매일 06:30';
} catch (e) {}
