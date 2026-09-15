/* 영업 자료 동시 생성 — 보고서와 제안서를 한 번에 (2026-09-15 대표 확정)
 *
 * 왜 있나 — 영업사원이 대상 1명당 보고서 5분 + 제안서 3분을 따로 기다렸다.
 * 두 자료는 서로의 결과를 쓰지 않고 **같은 서버에 같은 것을 각자** 물어볼 뿐이라,
 * 한 번 받아 둘이 나눠 쓰면 제안서 쪽 기다림이 통째로 사라진다.
 *
 * ⚠️ 이 파일은 **켜져 있을 때만** 동작한다(주소에 both=1 이 있을 때).
 *    평소 분석 화면은 이 파일이 있으나 없으나 똑같이 돈다 — 무회귀.
 *
 * ⚠️ 전역 하나만 내놓는다(window.SalesOneShot) — importScripts 가 아니라 번들 연결이라
 *    같은 전역을 여러 파일이 선언하면 통째로 죽는다(collector-extension 선례).
 */
(function () {
  'use strict';

  var LOG = '[영업자료]';

  function params() {
    try { return new URLSearchParams(window.location.search); } catch (e) { return null; }
  }

  /** 지금 「동시 생성」으로 열린 창인가 */
  function isActive() {
    var p = params();
    return !!(p && p.get('both') === '1');
  }

  /** 전산이 넘겨준 맥락 — 어느 기록에 「내려받았다」를 돌려줄지가 핵심이다. */
  function context() {
    var p = params();
    if (!p) return {};
    return {
      genLogIdx: p.get('genlog') || '',      // 전산 proposal_gen_log.idx
      erpBase: p.get('erp') || '',           // 전산 **API** 주소 — 기록을 돌려줄 곳
      propBase: p.get('prop') || '',         // 전산 **화면** 주소 — 제안서(/proposal/)가 있는 곳
                                             // ⚠️ 둘은 다른 호스트다. 섞으면 빈 탭이 열린다.
      name: p.get('name') || '',
      storeUrl: p.get('storeUrl') || ''
    };
  }

  /* ── 진행 표시 ─────────────────────────────────────────────────────────── */
  var STEPS = [
    { id: 'data', label: '검색량 · 연관어 · 상품 목록 받기' },
    { id: 'ai', label: 'AI 진단 작성' },
    { id: 'report', label: '보고서 만들기' },
    { id: 'proposal', label: '제안서 만들기' }
  ];

  var _box = null;

  function ensureBox() {
    if (_box && document.body.contains(_box)) return _box;
    var box = document.createElement('div');
    box.id = 'sales-oneshot';
    box.setAttribute('role', 'status');
    box.setAttribute('aria-live', 'polite');
    box.style.cssText = [
      'position:fixed', 'right:18px', 'bottom:18px', 'z-index:99999',
      'width:320px', 'max-width:calc(100vw - 36px)',
      'background:#fff', 'border:1px solid #bfdbfe', 'border-radius:12px',
      'box-shadow:0 10px 30px rgba(15,23,42,.16)', 'padding:14px 16px',
      'font-family:"Malgun Gothic","맑은 고딕",-apple-system,sans-serif',
      'font-size:13.5px', 'color:#0f172a', 'line-height:1.6'
    ].join(';');
    var html = '<div style="font-weight:700;margin-bottom:8px;color:#1d4ed8">⚡ 영업 자료 만드는 중</div>';
    STEPS.forEach(function (s) {
      html += '<div data-step="' + s.id + '" style="display:flex;gap:8px;align-items:center;padding:3px 0;color:#64748b">' +
              '<span data-ic style="flex:0 0 18px;height:18px;border-radius:50%;background:#e2e8f0;color:#94a3b8;' +
              'font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center">·</span>' +
              '<span data-lb style="flex:1">' + s.label + '</span></div>';
    });
    html += '<div data-note style="margin-top:9px;font-size:12.5px;color:#64748b"></div>';
    box.innerHTML = html;
    document.body.appendChild(box);
    _box = box;
    return box;
  }

  function mark(stepId, state, note) {
    var box = ensureBox();
    var row = box.querySelector('[data-step="' + stepId + '"]');
    if (row) {
      var ic = row.querySelector('[data-ic]');
      if (state === 'run') {
        ic.style.background = '#3b82f6'; ic.style.color = '#fff'; ic.textContent = '●';
        row.style.color = '#0f172a';
      } else if (state === 'done') {
        ic.style.background = '#16a34a'; ic.style.color = '#fff'; ic.textContent = '✓';
        row.style.color = '#0f172a';
      } else if (state === 'fail') {
        ic.style.background = '#dc2626'; ic.style.color = '#fff'; ic.textContent = '!';
        row.style.color = '#991b1b';
      }
    }
    if (note != null) {
      var n = box.querySelector('[data-note]');
      if (n) n.textContent = note;
    }
  }

  function finish(ok, note) {
    var box = ensureBox();
    var head = box.firstChild;
    if (head) {
      head.textContent = ok ? '✅ 영업 자료를 내려받았습니다' : '⚠️ 영업 자료 생성이 끝나지 않았습니다';
      head.style.color = ok ? '#15803d' : '#b45309';
    }
    var n = box.querySelector('[data-note]');
    if (n) n.textContent = note || '';
    if (ok) setTimeout(function () { try { box.remove(); } catch (e) {} }, 12000);
  }

  /* ── 파일 내려받기 ─────────────────────────────────────────────────────── */
  /** ⚠️ 두 파일을 같은 순간에 내려받으면 브라우저가 「여러 파일 허용?」을 묻는다.
   *     그래서 부르는 쪽이 간격을 두고 순차로 부른다. */
  function download(html, filename) {
    var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { try { URL.revokeObjectURL(a.href); } catch (e) {} }, 4000);
  }

  /* ── 전산에 「실제로 내려받았다」를 돌려준다 ───────────────────────────── */
  /** ⚠️ 이게 이 기능의 핵심 중 하나다. 전산 기록은 지금까지 **버튼 누른 시각**만 남겨
   *     탭만 열고 닫아도 「생성했다」로 보였다. 파일이 실제로 나간 뒤에만 부른다.
   *  ⚠️ 실패해도 **자료 생성은 성공이다** — 조용히 넘기고 사람에게는 알리되 막지 않는다. */
  function reportDownloaded(ctx) {
    if (!ctx.genLogIdx || !ctx.erpBase) return Promise.resolve(false);
    var url = ctx.erpBase.replace(/\/+$/, '') +
              '/api/my-prospective/sales-material-log/' + encodeURIComponent(ctx.genLogIdx) + '/downloaded';
    var headers = { 'Content-Type': 'application/json' };
    try {
      var t = localStorage.getItem('token');
      if (t) headers['Authorization'] = t;
    } catch (e) {}
    return fetch(url, { method: 'PATCH', headers: headers })
      .then(function (r) { return r.ok; })
      .catch(function () { return false; });
  }

  window.SalesOneShot = {
    isActive: isActive,
    context: context,
    mark: mark,
    finish: finish,
    download: download,
    reportDownloaded: reportDownloaded,
    ensureBox: ensureBox,
    STEPS: STEPS,
    LOG: LOG
  };
})();
