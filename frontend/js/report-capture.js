/* report-capture.js — 보고서 내보내기 공용 캡처 빌더 (v6.6)
 *
 * ReportSection(수동 HTML 내보내기)과 App(업체 자동저장·저장 보고서 다운로드)이
 * 서로 다른 캡처 함수를 쓰면서 제거 목록이 어긋나 직원용 UI("업체에 저장하시겠습니까",
 * 보고서 내보내기 폼, 추적 안내, 빈 목차 띠, 앱 푸터)가 광고주 전달본에 박제되던 문제를
 * 단일 빌더로 원천 차단한다. 두 경로 모두 이 파일 하나만 수정하면 함께 반영된다.
 *
 * 무손실 원칙: 화면 DOM은 절대 건드리지 않고(clone만 조작), 빌드 실패 시 ''를
 * 반환해 호출부가 기존 실패 처리(알림)로 안전하게 빠지게 한다. */
(function () {
  'use strict';

  /* 전달본에서 제거할 직원용/화면 전용 요소 — 두 캡처 경로 공통(단일 출처) */
  var REMOVE_SELECTORS = [
    '#sec-report',        /* 보고서 내보내기 폼 */
    '#sec-notify',        /* 알림 설정 */
    '#sec-save-client',   /* 업체 등록/저장 */
    '.anchor-nav-wrap',   /* 모바일 목차 껍데기(버튼 제거 후 빈 띠로 남던 유령 요소) */
    '.anchor-nav',
    '.topbar',
    '.footer',            /* 앱 푸터(버전 문자열) — 전달본은 report-footer 하나만 사용 */
    '.no-export'
  ];

  /* 목차 카드용 디바이더 색 (1~6장 순서 — SectionDivider 호출 색과 동일) */
  var DIVIDER_COLORS = ['#4f46e5', '#0ea5e9', '#ef4444', '#059669', '#7c3aed', '#1e293b'];

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  /* AI 종합 분석 진행 상태 — AiFeedbackAllSection이 심는 숨김 마커(.ai-state) 판독
   * 'done'=완료 / 'loading'=진행 중 / 'idle'=미시작·오류 / 'none'=섹션 없음 */
  function aiState() {
    try {
      var el = document.querySelector('#sec-ai-feedback .ai-state');
      if (el) return el.getAttribute('data-state') || 'idle';
      return document.getElementById('sec-ai-feedback') ? 'idle' : 'none';
    } catch (e) { return 'none'; }
  }

  /* 차트 canvas → 이미지 치환 + 래퍼 높이 해제(겹침 방지) — 기존 두 경로의 검증된 로직 그대로 */
  function canvasToImages(srcRoot, clone) {
    try {
      var oc = srcRoot.querySelectorAll('canvas');
      var cc = clone.querySelectorAll('canvas');
      for (var i = 0; i < cc.length; i++) {
        var du = '';
        try {
          var ch = (window.Chart && window.Chart.getChart) ? window.Chart.getChart(oc[i]) : null;
          if (ch) du = ch.toBase64Image('image/png', 1);
        } catch (e1) {}
        if (!du && oc[i] && oc[i].toDataURL) { try { du = oc[i].toDataURL('image/png'); } catch (e2) {} }
        if (!du) continue;
        var img = document.createElement('img');
        img.src = du;
        img.style.cssText = 'width:100%;height:auto;display:block;margin-bottom:14px;';
        if (cc[i].parentNode) cc[i].parentNode.replaceChild(img, cc[i]);
        var wrap = img.parentNode; /* ChartCanvas가 만든 position:relative;height 고정 래퍼 */
        if (wrap && wrap.style) { wrap.style.height = 'auto'; wrap.style.minHeight = '0'; wrap.style.position = 'static'; }
        var box = (img.closest && img.closest('.chartbox')) || wrap;
        if (box && box.style) { box.style.height = 'auto'; box.style.minHeight = '0'; box.style.overflow = 'visible'; box.style.marginBottom = '18px'; }
      }
    } catch (eC) {}
  }

  /* AI 섹션 미완료 시 → 로딩 문구 박제 대신 '별도 전달' 안내 카드로 대체 */
  function replaceUnfinishedAi(clone) {
    try {
      if (aiState() === 'done') return;
      var aiSec = clone.querySelector('#sec-ai-feedback');
      if (!aiSec || !aiSec.parentNode) return;
      var note = document.createElement('div');
      note.className = 'section';
      var inner = document.createElement('div');
      inner.className = 'container';
      var card = document.createElement('div');
      card.className = 'card';
      card.style.cssText = 'padding:18px 22px;background:#f5f3ff;border:1px solid #ddd6fe;font-size:13px;color:#4c1d95;line-height:1.7;';
      card.textContent = '🤖 METAINC AI 종합 분석 리포트는 분석 완료 후 담당자가 별도로 전달드립니다.';
      inner.appendChild(card); note.appendChild(inner);
      aiSec.parentNode.replaceChild(note, aiSec);
    } catch (eA) {}
  }

  /* 실제 렌더된 섹션 디바이더 기준 정적 목차 카드 생성 (표지 아래 삽입)
   * 화면의 좌측 목차(report-toc)는 캡처 범위 밖이라 전달본에서 사라지던 문제 보완 */
  function insertToc(clone) {
    try {
      var divs = clone.querySelectorAll('.report-divider');
      if (divs.length < 2) return; /* 구분 1개 이하면 목차 무의미 */
      var toc = document.createElement('div');
      toc.className = 'section';
      var cont = document.createElement('div');
      cont.className = 'container';
      var card = document.createElement('div');
      card.className = 'card';
      card.style.cssText = 'padding:16px 22px;';
      var title = document.createElement('div');
      title.style.cssText = 'font-size:13px;font-weight:800;color:#0f172a;margin-bottom:10px;';
      title.textContent = '📑 목차';
      card.appendChild(title);
      var grid = document.createElement('div');
      grid.className = 'rpt-grid';
      grid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;';
      for (var i = 0; i < divs.length; i++) {
        var d = divs[i];
        var id = 'rpt-part-' + (i + 1);
        d.id = id;
        /* SectionDivider 구조: .report-divider > div > [아이콘, div > [라벨, 부제]] */
        var label = '', sub = '';
        try {
          var txtBox = d.children[0] && d.children[0].children[1];
          if (txtBox) {
            label = (txtBox.children[0] && txtBox.children[0].textContent || '').trim();
            sub = (txtBox.children[1] && txtBox.children[1].textContent || '').trim();
          }
        } catch (eL) {}
        if (!label) label = (d.textContent || '').trim().slice(0, 30);
        var a = document.createElement('a');
        a.href = '#' + id;
        a.style.cssText = 'display:flex;align-items:baseline;gap:8px;text-decoration:none;color:#334155;font-size:12.5px;font-weight:700;line-height:1.5;';
        var dot = document.createElement('span');
        dot.style.cssText = 'width:8px;height:8px;border-radius:3px;flex:none;align-self:center;background:' + (DIVIDER_COLORS[i] || '#4f46e5') + ';';
        a.appendChild(dot);
        var tx = document.createElement('span');
        tx.textContent = label;
        a.appendChild(tx);
        if (sub) {
          var sb = document.createElement('span');
          sb.style.cssText = 'font-size:10.5px;color:#94a3b8;font-weight:500;';
          sb.textContent = sub;
          a.appendChild(sb);
        }
        grid.appendChild(a);
      }
      card.appendChild(grid);
      cont.appendChild(card); toc.appendChild(cont);
      /* 표지(.report-cover) 바로 다음, 없으면 맨 앞 */
      var cover = clone.querySelector('.report-cover');
      if (cover && cover.parentNode === clone && cover.nextSibling) clone.insertBefore(toc, cover.nextSibling);
      else if (cover && cover.parentNode) cover.parentNode.insertBefore(toc, cover.nextSibling);
      else clone.insertBefore(toc, clone.firstChild);
    } catch (eT) {}
  }

  /* 직원용/인터랙티브 요소 제거 + 입력값 평문화 + 반응형 클래스 부여 + 원격 이미지 안전화 */
  function cleanup(clone) {
    REMOVE_SELECTORS.forEach(function (sel) {
      try { clone.querySelectorAll(sel).forEach(function (el) { el.remove(); }); } catch (e) {}
    });
    clone.querySelectorAll('button, .btn').forEach(function (b) { b.remove(); });
    clone.querySelectorAll('input, select, textarea').forEach(function (inp) {
      var span = document.createElement('span');
      span.textContent = inp.value || '';
      span.style.fontWeight = '600';
      if (inp.parentNode) inp.parentNode.replaceChild(span, inp);
    });
    /* 인라인 grid/flex → 모바일 1열 전환용 훅 클래스 */
    clone.querySelectorAll('[style*="grid-template-columns"]').forEach(function (el) { el.classList.add('rpt-grid'); });
    clone.querySelectorAll('[style*="display: flex"], [style*="display:flex"]').forEach(function (el) { el.classList.add('rpt-flex'); });
    /* 원격 이미지(경쟁사 썸네일 등) — CDN 만료·오프라인 열람 시 깨진 아이콘 대신 자동 숨김 */
    clone.querySelectorAll('img').forEach(function (im) {
      var src = im.getAttribute('src') || '';
      if (/^https?:/i.test(src)) im.setAttribute('onerror', "this.style.display='none'");
    });
  }

  function collectCss() {
    var cssText = '';
    try {
      var sheets = document.styleSheets;
      for (var i = 0; i < sheets.length; i++) {
        try {
          var rules = sheets[i].cssRules || sheets[i].rules;
          for (var j = 0; j < rules.length; j++) cssText += rules[j].cssText + '\n';
        } catch (e) { /* cross-origin 무시 */ }
      }
    } catch (e2) {}
    /* 전달본 자체 반응형 보정 — rpt-grid/rpt-flex는 전달본에서만 쓰는 훅이므로 여기서 정의 보장 */
    cssText += '\n@media (max-width: 640px) {\n'
      + '  .rpt-grid { grid-template-columns: 1fr !important; }\n'
      + '  .rpt-flex { flex-wrap: wrap !important; }\n'
      + '}\n';
    return cssText;
  }

  /* 전체 빌드 — opts: { title(필수, 헤더 제목), managerName(선택, 담당자명) }
   * 성공 시 완성 HTML 문자열, 실패 시 '' */
  function buildHtml(opts) {
    try {
      opts = opts || {};
      var srcMain = document.querySelector('.report-main')
        || (document.getElementById('root') && document.getElementById('root').children[0]);
      if (!srcMain) return '';
      var clone = srcMain.cloneNode(true);

      canvasToImages(srcMain, clone);
      replaceUnfinishedAi(clone);
      cleanup(clone);
      insertToc(clone);

      var cssText = collectCss();
      var dateStr = new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
      var headerText = esc(opts.title || '로직 분석 보고서');
      var manager = esc(opts.managerName || '');
      var metaLine = esc(dateStr) + ' · 메타아이앤씨 로직분석' + (manager ? ' · 담당 ' + manager : '');
      var contact = (manager ? '담당 ' + manager + ' · ' : '') + '고객센터 02-2082-2005 · 메타아이앤씨';

      return '<!DOCTYPE html>\n<html lang="ko">\n<head>\n'
        + '<meta charset="UTF-8">\n'
        + '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        + '<title>' + headerText + ' - ' + esc(dateStr) + '</title>\n'
        + '<style>\n'
        + '* { margin: 0; padding: 0; box-sizing: border-box; }\n'
        + 'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", sans-serif; background: #f8fafc; color: #1e293b; }\n'
        /* 표지: 본문 인디고 토큰과 동일 계열(#4f46e5→#7c3aed)로 단일 브랜드색 통일 (구 보라 #6C5CE7 폐기) */
        + '.report-header { background: linear-gradient(135deg, #4f46e5, #7c3aed); color: #fff; padding: 38px 20px 34px; text-align: center; }\n'
        + '.report-header .rh-eyebrow { font-size: 11px; font-weight: 700; letter-spacing: 0.18em; opacity: 0.8; margin-bottom: 8px; }\n'
        + '.report-header h1 { font-size: 24px; margin-bottom: 8px; letter-spacing: -0.3px; }\n'
        + '.report-header p { font-size: 13.5px; opacity: 0.88; }\n'
        + '.report-cta { max-width: 1200px; margin: 28px auto 0; padding: 0 20px; }\n'
        + '.report-cta .in { background: #1e293b; color: #e2e8f0; border-radius: 16px; padding: 22px 26px; }\n'
        + '.report-cta .t { font-size: 16px; font-weight: 800; color: #fff; margin-bottom: 6px; }\n'
        + '.report-cta .d { font-size: 12.5px; color: #cbd5e1; line-height: 1.7; }\n'
        + '.report-cta .c { display: inline-block; margin-top: 12px; background: #4f46e5; color: #fff; font-size: 13px; font-weight: 800; border-radius: 10px; padding: 9px 18px; }\n'
        + '.report-footer { text-align: center; padding: 26px 16px 30px; color: #94a3b8; font-size: 12px; border-top: 1px solid #e2e8f0; margin-top: 32px; line-height: 1.8; }\n'
        + '.report-footer .rf-main { font-size: 13px; font-weight: 700; color: #475569; }\n'
        + cssText
        + '\n@media print { .report-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }\n'
        + '</style>\n</head>\n<body>\n'
        + '<div class="report-header">\n'
        + '  <div class="rh-eyebrow">METAINC · 로직분석</div>\n'
        + '  <h1>' + headerText + '</h1>\n'
        + '  <p>' + metaLine + '</p>\n'
        + '</div>\n'
        + '<div class="report-content" style="max-width:1200px; margin:0 auto; padding:20px;">\n'
        + clone.outerHTML + '\n'
        + '</div>\n'
        + '<div class="report-cta"><div class="in">\n'
        + '  <div class="t">다음 단계를 함께 진행해요</div>\n'
        + '  <div class="d">본 보고서의 실행 로드맵(즉시 → 1주 → 1개월)을 담당자와 확정하세요. 궁금하신 점은 언제든 문의 가능합니다.</div>\n'
        + '  <span class="c">' + esc(contact) + '</span>\n'
        + '</div></div>\n'
        + '<div class="report-footer">\n'
        + '  <div class="rf-main">' + esc(contact) + '</div>\n'
        + '  <div>본 보고서의 수치는 네이버 공식 API 기준이며, 시장 상황에 따라 변동될 수 있습니다. © 2026 메타아이앤씨</div>\n'
        + '</div>\n'
        + '</body>\n</html>';
    } catch (e) {
      try { console.error('[ReportCapture] build 실패:', e); } catch (e2) {}
      return '';
    }
  }

  window.ReportCapture = { buildHtml: buildHtml, aiState: aiState, REMOVE_SELECTORS: REMOVE_SELECTORS };
})();
