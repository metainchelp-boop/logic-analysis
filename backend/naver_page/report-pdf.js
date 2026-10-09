/* Local-only, advertiser-facing PDF. The caller revalidates the exact report revision and permission. */
(function (root) {
  'use strict';
  const BASE = '/naver/vendor/report-pdf/';
  const INTEGRITY = {
    'pdf-lib-1.17.1.min.js': 'sha256-D5pcrQeUHwgmWGyU4InYm5GMRuXBfPLVo8b2ZuO8aU8=',
    'fontkit-1.1.1.umd.min.js': 'sha256-2N9WG5+6mOJPLlEw5AlIgJKBu7xVogxBI1nxoKXrNaY=',
    'sha256-1.0.0.min.js': 'sha256-oFDXlOFwaZvRpp0zkI0JQsaJAcuINHAWBktgskDwBn4='
  };
  const FONT_SHA = '76f45ef4a6bcff344c837c95a7dcc26e017e38b5846d5ae0cdcb5b86be2e2d31';
  const PACKED_FONT_SHA = '72d1bf88a642ede8ff7da422031106fc697ea4c79b1cfd2994bffc57df4dab07';
  const WIDTH = 595.28, HEIGHT = 841.89, MARGIN = 42;
  let loading, fontBytes;

  function fail(code) { throw new Error(code); }
  function loadScript(file, name) {
    if (root[name]) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = BASE + file;
      script.integrity = INTEGRITY[file];
      script.referrerPolicy = 'no-referrer';
      const timer = setTimeout(() => { script.remove(); reject(new Error('REPORT_PDF_ASSET')); }, 15000);
      script.onload = () => { clearTimeout(timer); root[name] ? resolve() : reject(new Error('REPORT_PDF_ASSET')); };
      script.onerror = () => { clearTimeout(timer); script.remove(); reject(new Error('REPORT_PDF_ASSET')); };
      document.head.appendChild(script);
    });
  }
  async function digest(bytes) {
    if (root.crypto && root.crypto.subtle) {
      const hash = await root.crypto.subtle.digest('SHA-256', bytes);
      return Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('');
    }
    // The existing application also supports HTTP, where SubtleCrypto is not exposed.
    await loadScript('sha256-1.0.0.min.js', 'sha256');
    if (typeof root.sha256 !== 'function') fail('REPORT_PDF_FONT');
    return root.sha256(bytes);
  }
  async function dependencies() {
    if (!loading) loading = Promise.all([
      loadScript('pdf-lib-1.17.1.min.js', 'PDFLib'), loadScript('fontkit-1.1.1.umd.min.js', 'fontkit')
    ]).catch(error => { loading = null; throw error; });
    await loading;
    if (!fontBytes) {
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch(BASE + 'NanumGothic-Regular.ttf.gz', {
          credentials: 'omit', cache: 'force-cache', redirect: 'error', referrerPolicy: 'no-referrer', signal: controller.signal
        });
        if (!response.ok) fail('REPORT_PDF_FONT');
        const packed = new Uint8Array(await response.arrayBuffer());
        if (packed.length !== 697020 || await digest(packed) !== PACKED_FONT_SHA || typeof DecompressionStream !== 'function') fail('REPORT_PDF_FONT');
        const reader = new Blob([packed]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();
        const bytes = new Uint8Array(2054744); let offset = 0;
        try {
          for (;;) {
            const part = await reader.read();
            if (part.done) break;
            if (offset + part.value.length > bytes.length) fail('REPORT_PDF_FONT');
            bytes.set(part.value, offset); offset += part.value.length;
          }
        } finally { await reader.cancel(); }
        if (offset !== bytes.length || await digest(bytes) !== FONT_SHA) fail('REPORT_PDF_FONT');
        fontBytes = bytes;
      } finally { clearTimeout(timer); }
    }
    return fontBytes;
  }
  function text(value, limit = 240) {
    if (typeof value !== 'string' || value.length > limit) fail('REPORT_PDF_DATA');
    return value.normalize('NFC').replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, ' ').trim();
  }
  function day(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) ||
        new Date(value).toISOString().slice(0, 10) !== value) fail('REPORT_PDF_DATA');
    return value;
  }
  function pinned(report) {
    if (!report || !report.payload || !report.scope || !Number.isSafeInteger(report.report_id) || report.report_id < 1 ||
        !Number.isSafeInteger(report.revision_no) || report.revision_no < 1) fail('REPORT_PDF_DATA');
    const p = report.payload;
    if (!p.period || !['weekly', 'monthly'].includes(p.period.kind) ||
        !['account', 'company'].includes(report.scope.kind) || !['ready', 'partial', 'collecting'].includes(p.status)) fail('REPORT_PDF_DATA');
    day(p.period.start); day(p.period.end);
    if (p.period.start > p.period.end || Date.parse(p.period.end) - Date.parse(p.period.start) > 30 * 86400000 || typeof report.generated_at !== 'string' ||
        !Number.isFinite(Date.parse(report.generated_at))) fail('REPORT_PDF_DATA');
    return {report, p, company: text(report.company_name), kind: p.period.kind === 'weekly' ? '주간' : '월간'};
  }
  const METRICS = [
    ['spend', '광고비', '원'], ['impressions', '노출', '회'], ['clicks', '클릭', '회'],
    ['ctr', '클릭률', '%'], ['cpc', '클릭당 비용', '원'], ['conversions', '전환', '건'],
    ['conversion_value', '광고 전환가치', '원'], ['cvr', '전환율', '%'],
    ['cpa', '전환당 비용', '원'], ['roas', 'ROAS', '%']
  ];
  function numeric(value) {
    if (value == null) return null;
    if (typeof value !== 'number' || !Number.isFinite(value) || Math.abs(value) > Number.MAX_SAFE_INTEGER) fail('REPORT_PDF_DATA');
    return value;
  }
  function amount(value, unit = '', signed = false) {
    const n = numeric(value);
    if (n === null) return '미확인';
    const displayed = unit === '원' ? Math.trunc(n) : Number(n.toFixed(2));
    return (signed && n > 0 ? '+' : '') + displayed.toLocaleString('ko-KR', {
      maximumFractionDigits: unit === '원' ? 0 : 2
    }) + unit;
  }
  function metric(payload, key) {
    const value = numeric((payload.totals && payload.totals[key]) ?? (payload.ratios && payload.ratios[key]));
    if (value !== null && value < 0) fail('REPORT_PDF_DATA');
    return value;
  }
  function comparisonState(value) {
    return {ready: '비교 가능', partial: '일부 항목 비교 가능', scope_changed: '비교 범위 변경',
      insufficient_data: '비교 자료 부족', zero_denominator: '산출 불가'}[value] || '비교 자료 부족';
  }
  function change(value) {
    if (!value || !['ready', 'zero_denominator'].includes(value.status)) return comparisonState(value && value.status);
    if (value.unit === 'percentage_points') return value.absolute == null ? '산출 불가' : amount(value.absolute, '%p', true);
    if (!['currency', 'count'].includes(value.unit)) fail('REPORT_PDF_DATA');
    const absolute = amount(value.absolute, value.unit === 'currency' ? '원' : '', true);
    return absolute + ' / ' + (value.status === 'zero_denominator' || value.percent == null ? '증감률 산출 불가' : amount(value.percent, '%', true));
  }
  function unitName(unit) { return unit === 'money' ? '원' : unit === 'percent' ? '%' : ''; }
  function enrichedAmount(value, unit, signed = false) { return value == null ? '—' : amount(value, unitName(unit), signed); }
  function scopeDescription(scope = {}) {
    return (scope.family === 'paired' ? '공동 ' : '') + amount(scope.account_days) + '/' + amount(scope.expected_account_days) +
      ' 계정×일 · ' + (scope.complete === true ? '완결' : '확인분·미확인');
  }
  function approvedShared(report) {
    const a = report.annotations || {}, s = a.shared, m = s && s.metadata;
    return a.state === 'approved' && s && s.state === 'approved' && s.version === a.version && m &&
      m.report_id === report.report_id && m.account_key === report.scope.account_key && m.revision_fingerprint === report.revision_fingerprint ? s : null;
  }
  async function build(report) {
    report = structuredClone(report); // Freeze the selected revision before asynchronous asset loading.
    const view = pinned(report), bytes = await dependencies();
    const doc = await root.PDFLib.PDFDocument.create();
    doc.registerFontkit(root.fontkit);
    // This font's composite Korean outlines are corrupted by fontkit 1.1.1 subsetting.
    // Embed the pinned full font: searchable mappings alone do not prove visible glyphs.
    const font = await doc.embedFont(bytes, {subset: false});
    doc.setTitle(view.company + ' ' + view.kind + ' 광고 성과 보고서');
    doc.setProducer('네이버 관제 - 로컬 보고서');
    doc.setCreationDate(new Date(report.generated_at)); doc.setModificationDate(new Date(report.generated_at));
    const {p} = view, coverage = p.coverage || {}, detail = p.details || {}, enrichment = detail.enrichment || {}, shared = approvedShared(report);
    const enriched = Array.isArray(enrichment.metrics) ? enrichment.metrics : null;
    if (enriched && enriched.length > 17) fail('REPORT_PDF_DATA');
    const ink = root.PDFLib.rgb(0.13, 0.19, 0.27), muted = root.PDFLib.rgb(0.36, 0.42, 0.48);
    const accent = root.PDFLib.rgb(0.04, 0.40, 0.43), pale = root.PDFLib.rgb(0.94, 0.96, 0.97);
    const supported = new Set(font.getCharacterSet());
    let page, y, replaced = false;
    function printable(value) {
      return Array.from(value, ch => {
        if (supported.has(ch.codePointAt(0))) return ch;
        replaced = true; return '?';
      }).join('');
    }
    function lines(value, width, size) {
      const out = []; let line = '';
      for (const ch of printable(value)) {
        if (line && font.widthOfTextAtSize(line + ch, size) > width) { out.push(line.trimEnd()); line = ''; }
        line += ch;
      }
      out.push(line.trimEnd()); return out;
    }
    function newPage() {
      if (doc.getPageCount() >= 80) fail('REPORT_PDF_SIZE');
      page = doc.addPage([WIDTH, HEIGHT]); y = HEIGHT - 60;
      page.drawText(view.kind + ' 광고 성과 보고서 | ' + report.revision_no + '판', {
        x: MARGIN, y: HEIGHT - 30, font, size: 8, color: muted
      });
    }
    function ensure(height) { if (y - height < 62) newPage(); }
    function paragraph(value, size = 10, color = ink, gap = 8) {
      for (const line of lines(value, WIDTH - 2 * MARGIN, size)) {
        ensure(size * 1.6); page.drawText(line, {x: MARGIN, y, font, size, color}); y -= size * 1.6;
      }
      y -= gap;
    }
    function heading(value) { ensure(42); y -= 6; paragraph(value, 13, accent, 7); }
    function row(values, widths, header = false) {
      const wrapped = values.map((v, i) => lines(v, widths[i] - 14, 9));
      const height = Math.max(...wrapped.map(v => v.length)) * 14 + 14;
      let x = MARGIN;
      if (header) page.drawRectangle({x, y: y - height + 8, width: WIDTH - 2 * MARGIN, height, color: pale});
      wrapped.forEach((parts, i) => {
        parts.forEach((part, j) => page.drawText(part, {x: x + 7, y: y - j * 14, size: 9, font, color: header ? accent : ink}));
        x += widths[i];
      });
      y -= height;
      page.drawLine({start: {x: MARGIN, y: y + 8}, end: {x: WIDTH - MARGIN, y: y + 8}, thickness: 0.4, color: pale});
    }
    function table(headers, rows, widths) {
      ensure(64); row(headers, widths, true);
      for (const values of rows) {
        const height = Math.max(...values.map((v, i) => lines(v, widths[i] - 14, 9).length)) * 14 + 14;
        if (y - height < 62) { newPage(); row(headers, widths, true); }
        row(values, widths);
      }
      y -= 12;
    }
    newPage();
    paragraph(view.company, 21, ink, 7);
    paragraph(view.kind + ' 광고 성과 보고서', 16, accent, 10);
    paragraph(p.period.start + ' ~ ' + p.period.end + ' | ' + report.revision_no + '판', 11);
    const owner = typeof report.owner === 'string' ? report.owner : report.owner && report.owner.name;
    paragraph('담당자: ' + (owner == null ? '미보관' : text(owner)) + ' | 생성 시각: ' + text(report.generated_at, 60), 9, muted);
    const scope = report.scope;
    if (scope.kind === 'account') {
      paragraph('집계 범위: 이 광고 계정 | ' + text(scope.account_name || '계정명 미보관') + ' | ' + text(scope.ad_account_no || '번호 미보관', 40), 10);
    } else {
      if (!Array.isArray(scope.accounts) || scope.accounts.length > 500) fail('REPORT_PDF_DATA');
      paragraph('집계 범위: 업체 전체 합산 | 포함 계정 ' + scope.accounts.length + '개', 10);
    }
    const partial = p.status !== 'ready' || coverage.basic_complete !== true || coverage.conversion_complete !== true;
    if (partial) {
      paragraph(p.status === 'collecting' ? '수집 중 - 확정 보고서가 아닙니다.' : '부분 집계 - 확인된 자료만 포함합니다.', 12, accent);
      if (coverage.basic_complete !== true) paragraph('기본 성과 부분 집계: 광고비·노출·클릭에 누락 자료가 있습니다.', 9);
      if (coverage.conversion_complete !== true) paragraph('전환 성과 부분 집계: 전환·광고 전환가치·전환율·전환당 비용·ROAS는 미확인 또는 일부 자료입니다.', 9);
    } else paragraph('생성 완료 - 해당 판의 집계 범위 기준', 10, accent);
    paragraph('기본 성과 ' + amount(coverage.basic_complete_account_days) + ' / ' + amount(coverage.expected_account_days) +
      ' 계정일 | 전환 성과 ' + amount(coverage.conversion_complete_account_days) + ' / ' + amount(coverage.expected_account_days) + ' 계정일', 9, muted);
    if (enrichment.quality) {
      heading('자료 완결 범위');
      const q = enrichment.quality;
      table(['자료', '완결 계정×일', '완결률'], [['basic', '기본 자료'], ['conversion', '전환 자료'], ['paired', '효율 계산 공동 범위']].map(([key, label]) => {
        const block = q[key] || {};
        return [label, amount(block.count) + '/' + amount(q.expected_account_days), enrichedAmount(block.percent, 'percent') + ' · ' + (block.complete === true ? '완결' : '미완결·미확인')];
      }), [170, 170, 171.28]);
    }
    if (Array.isArray(enrichment.period_caveats)) enrichment.period_caveats.slice(0, 20).forEach(item => paragraph(text(item, 1000), 9, muted));
    if (coverage.newest_collected_at) paragraph('자료 기준시각: ' + text(coverage.newest_collected_at, 60), 9, muted);
    if (detail.status === 'legacy_unavailable' || p.format_version !== 2) paragraph('옛 판 상세 미보관 - 현재 자료로 보충하지 않았습니다.', 10, accent);
    if (detail.status === 'reconstructed') paragraph('상세 재구성 - 원천을 확인하여 생성한 새 판입니다.', 10, accent);
    heading('핵심 성과');
    if (enriched) table(['지표', '현재 수치', '계산 범위'], enriched.map(item =>
      [text(item.label, 80), enrichedAmount(item.current, item.unit), scopeDescription(item.scope)]), [145, 145, 221.28]);
    else table(['항목', '해당 판 수치', '항목', '해당 판 수치'],
      Array.from({length: 5}, (_, i) => [METRICS[i], METRICS[i + 5]].flatMap(([key, label, unit]) =>
        [label, amount(metric(p, key), unit)])), [110, 146, 125, 130.28]);
    if (metric(p, 'conversions') === null) paragraph('전환 미확인 - 광고 전환가치나 ROAS를 0으로 간주하지 않습니다.', 9, muted);
    paragraph('전환은 광고 플랫폼의 이벤트 수이며 주문·구매자 수와 다를 수 있습니다. 광고 전환가치는 실제 주문·결제 매출과 별도입니다.', 9, muted);
    paragraph('금액은 화면과 같이 원 미만을 버림 표시하며 계산 원본은 해당 판에 보존됩니다. 비율은 서버에 고정된 합산 기준 수치입니다.', 8, muted);
    heading('성과 요약');
    const briefing = detail.briefing || [];
    if (!Array.isArray(briefing) || briefing.length > 12) fail('REPORT_PDF_DATA');
    if (!briefing.length) paragraph('해당 판의 요약 미보관', 10, muted);
    briefing.forEach(item => paragraph(text(item, 1000), 10));
    newPage(); heading('직전 기간 비교');
    const comparison = detail.comparison || {};
    if (comparison.period) paragraph(day(comparison.period.start) + ' ~ ' + day(comparison.period.end), 10);
    paragraph(comparisonState(comparison.status) + ' | 기본 성과: ' + comparisonState(comparison.basic_status) +
      ' | 전환 성과: ' + comparisonState(comparison.conversion_status), 9, accent);
    if (enriched) table(['지표', '이전', '절대 변화', '상대 변화', '차이(%p)', '비교 범위'], enriched.map(item => {
      const comparable = ['ready', 'zero_denominator'].includes(item.status);
      return [text(item.label, 80), enrichedAmount(item.previous, item.unit), comparable && !item.percentage_points ? enrichedAmount(item.absolute, item.unit, true) : '—',
        comparable ? enrichedAmount(item.percent, 'percent', true) : '—', comparable && item.percentage_points && item.absolute != null ? amount(item.absolute, '%p', true) : '—',
        item.comparison_reason ? text(item.comparison_reason, 200) : scopeDescription(item.scope)];
    }), [84, 73, 73, 73, 70, 138.28]);
    else table(['항목', '직전 기간', '증감'], METRICS.map(([key, label, unit]) =>
      [label, amount(metric(comparison, key), unit), change(comparison.changes && comparison.changes[key])]), [140, 145, 226.28]);
    paragraph('직전 주·월의 비교이며 같은 기간의 정정 전후 차이가 아닙니다. 비율의 차이는 %p로 표시합니다.', 8, muted);
    heading('수치 근거와 확인할 내용');
    paragraph('관측 사실, 원인 가설, 예정 행동을 구분합니다. 원인 가설과 권장 행동은 완료된 업무가 아닙니다.', 9, muted);
    const feedback = enrichment.feedback || {};
    for (const [key, label] of [['facts', '관측 사실'], ['hypotheses', '원인 가설 · 추가 확인'], ['actions', '권장 행동']]) {
      paragraph(label, 11, accent);
      const items = feedback[key] || [];
      if (!Array.isArray(items) || items.length > 20) fail('REPORT_PDF_DATA');
      if (!items.length) paragraph('이 판에 저장된 내용이 없습니다.', 9, muted);
      items.forEach(item => {
        paragraph(text(item.text || '', 2000), 10);
        if (key === 'facts' && item.evidence && item.evidence.scope) {
          const e = item.evidence;
          paragraph('근거 범위: ' + text(e.scope, 200) + ' · ' + amount(e.account_days) + '/' + amount(e.expected_account_days) + ' 계정×일', 8, muted);
        }
        if (Array.isArray(item.metric_keys) && item.metric_keys.length) paragraph('근거 지표: ' + item.metric_keys.map(key => {
          const metric = enriched && enriched.find(row => row.key === key); return metric ? text(metric.label, 80) : '';
        }).filter(Boolean).join(' · '), 8, muted);
        if (key === 'hypotheses') {
          if (item.alternative) paragraph('다른 가능성: ' + text(item.alternative, 1000), 9, muted);
          if (item.required_evidence) paragraph('필요 근거: ' + text(Array.isArray(item.required_evidence) ? item.required_evidence.join(' · ') : item.required_evidence, 1500), 9, muted);
          if (item.verification) paragraph('확인 방법: ' + text(item.verification, 1000), 9, muted);
        }
        if (key === 'actions') {
          if (item.reason) paragraph('이유: ' + text(item.reason, 1000), 9, muted);
          paragraph('담당 ' + (item.owner == null ? '미정' : text(item.owner, 120)) + ' · 기한 ' + (item.due_date ? day(item.due_date) : '미정') + ' · ' +
            '우선순위 ' + ({high:'높음',medium:'보통',low:'낮음'}[item.priority] || '미정') + ' · ' + (item.approval_status === 'approved' ? '승인됨' : '검토 필요') + ' · ' + (item.status === 'completed' ? '완료' : '예정·미완료'), 9, muted);
        }
      });
    }
    heading('승인된 공유 문안 / 다음 계획');
    if (shared) {
      paragraph('공유 문안 ' + shared.version + '판 · 승인 시각 ' + text(shared.approved_at, 60), 9, muted);
      paragraph(text(shared.shared_comment || '공유 코멘트가 없습니다.', 2000), 10);
      paragraph('다음 관리 계획', 11, accent); paragraph(text(shared.next_plan || '확정된 다음 계획이 없습니다.', 1000), 10);
      paragraph('계획 기한: ' + (shared.plan_due ? day(shared.plan_due) : '미정') + ' · 계획 기록은 업무 완료를 뜻하지 않습니다.', 9, muted);
    } else paragraph('현재 수치판·문안판에 승인된 공유 문안이 없습니다. 공유 문안 미확정 상태입니다.', 10, muted);
    heading('승인된 목표 대비');
    const targets = shared && shared.targets || {};
    paragraph(targets.source ? '목표 출처: ' + text(targets.source, 500) : '목표 출처가 저장되지 않아 판정을 보류합니다. 임의 목표를 설정하지 않습니다.', 9, muted);
    table(['지표', '현재', '목표', '판정'], [['spend_per_day', '일평균 광고비', 'money'], ['cpa', 'CPA', 'money'], ['roas', 'ROAS', 'percent']].map(([key, label, unit]) => {
      const item = enriched && enriched.find(row => row.key === key) || {}, target = numeric(targets[key]);
      const ready = target != null && !!targets.source && item.scope && item.scope.complete === true && item.current != null;
      const verdict = target == null ? '목표 미설정' : !ready ? '자료·목표 출처 미확인 · 판정 보류' : key === 'roas' ? (item.current >= target ? '목표 이상' : '목표 미달') : (item.current <= target ? '목표 이내' : '목표 초과');
      return [label, enrichedAmount(item.current, unit), enrichedAmount(target, unit), verdict];
    }), [125, 110, 110, 166.28]);
    const daily = detail.daily || [];
    if (!Array.isArray(daily) || daily.length > 31) fail('REPORT_PDF_DATA');
    newPage(); heading('일별 추이');
    paragraph('누락·부분 집계 날짜는 선을 연결하지 않습니다. 표에는 확인된 부분합 또는 미확인을 표시하며 0으로 대체하지 않습니다.', 9, muted);
    if (!daily.length) paragraph('해당 판의 일별 상세 미보관', 10, muted);
    const seenDays = new Set();
    for (const item of daily) {
      if (!item || !day(item.day) ||
          item.day < p.period.start || item.day > p.period.end || seenDays.has(item.day)) fail('REPORT_PDF_DATA');
      seenDays.add(item.day);
    }
    const sortedDays = [...daily].sort((a, b) => a.day.localeCompare(b.day));
    for (const [key, label, unit] of [...METRICS.slice(0, 3), ['conversions', '전환수', '건'], ['roas', 'ROAS', '%']]) {
      if (!daily.length) break;
      ensure(112); paragraph(label, 10, accent, 1);
      const points = sortedDays.map(item => {
        const cov = item.coverage || {}, conversion = key === 'conversions' || key === 'roas';
        const complete = conversion ? cov.conversion_complete === true && (key !== 'roas' || cov.basic_complete === true) : cov.basic_complete === true;
        return complete ? metric(item, key) : null;
      });
      const max = Math.max(1, ...points.filter(n => n !== null)), plotTop = y, plotBottom = y - 48;
      const plotX = i => MARGIN + 8 + (Date.parse(sortedDays[i].day) - Date.parse(p.period.start)) /
        Math.max(86400000, Date.parse(p.period.end) - Date.parse(p.period.start)) * (WIDTH - 2 * MARGIN - 16);
      page.drawLine({start: {x: MARGIN, y: plotBottom}, end: {x: WIDTH - MARGIN, y: plotBottom}, thickness: 0.5, color: muted});
      points.forEach((n, i) => {
        if (n === null) return;
        if (n < 0) fail('REPORT_PDF_DATA');
        const x = plotX(i), py = plotBottom + n / max * 42;
        page.drawCircle({x, y: py, size: 2, color: accent});
        if (i && points[i - 1] !== null && Date.parse(sortedDays[i].day) - Date.parse(sortedDays[i - 1].day) === 86400000) {
          page.drawLine({start: {x: plotX(i - 1),
            y: plotBottom + points[i - 1] / max * 42}, end: {x, y: py}, thickness: 1, color: accent});
        }
      });
      y = plotTop - 66;
      const known = points.filter(n => n !== null);
      paragraph(p.period.start + ' ~ ' + p.period.end + ' | 최대 ' + amount(known.length ? Math.max(...known) : null, unit), 8, muted, 5);
    }
    if (daily.length) {
      heading('일별 수치표');
      table(['실적일', '광고비', '노출', '클릭', '전환', '전환가치', 'ROAS', '범위'], sortedDays.map(item => {
        const cov = item.coverage || {};
        return [item.day, amount(metric(item, 'spend'), '원'), amount(metric(item, 'impressions')),
          amount(metric(item, 'clicks')), amount(metric(item, 'conversions')), amount(metric(item, 'conversion_value'), '원'), amount(metric(item, 'roas'), '%'),
          (cov.basic_complete === true ? '기본 완결' : '기본 확인분') + ' · ' + (cov.conversion_complete === true ? '전환 완결' : '전환 확인분·미확인')];
      }), [73, 69, 60, 45, 43, 75, 57, 89.28]);
    }
    if (scope.kind === 'company') {
      heading('업체 합산에 포함된 광고 계정');
      table(['광고 계정 ID', '광고 계정 이름'], scope.accounts.map(account =>
        [text(account.ad_account_no || '미보관', 40), text(account.account_name || '미보관')]), [150, 361.28]);
      if (Array.isArray(scope.contributions)) {
        if (scope.contributions.length > 500) fail('REPORT_PDF_DATA');
        heading('계정별 기여');
        paragraph('동일 보고서 판에 포함된 계정입니다. 효율은 공동 합계로 계산하며 계정 비율의 단순평균이 아닙니다. 미완결 기여 비중은 —로 표시합니다.', 9, muted);
        table(['계정', '광고비', '비중', '전환', '전환 비중', '전환가치', 'ROAS', 'CPA'], scope.contributions.map(account => {
          function current(key) { const item = (account.metrics || []).find(row => row.key === key); return item && item.current; }
          const shares = account.shares || {};
          return [text(account.account_name || '미보관', 240) + ' · ' + text(account.ad_account_no || '미보관', 40),
            enrichedAmount(current('spend'), 'money'), enrichedAmount(shares.spend, 'percent'), enrichedAmount(current('conversions'), 'number'), enrichedAmount(shares.conversions, 'percent'),
            enrichedAmount(current('conversion_value'), 'money'), enrichedAmount(current('roas'), 'percent'), enrichedAmount(current('cpa'), 'money')];
        }), [100, 70, 45, 40, 60, 75, 56, 65.28]);
      }
    }
    if (replaced) paragraph('지원되지 않는 일부 특수문자는 ?로 표시했습니다.', 8, muted);
    const pages = doc.getPages();
    pages.forEach((sheet, i) => {
      sheet.drawText('네이버 관제 | ' + report.revision_no + '판 | ' + (partial ? '부분 집계' : '해당 판 기준'), {x: MARGIN, y: 32, size: 8, font, color: muted});
      const label = (i + 1) + ' / ' + pages.length;
      sheet.drawText(label, {x: WIDTH - MARGIN - font.widthOfTextAtSize(label, 8), y: 32, size: 8, font, color: muted});
    });
    const output = await doc.save();
    if (output.length > 8 * 1024 * 1024) fail('REPORT_PDF_SIZE');
    return output;
  }
  function filename(report) {
    const view = pinned(report);
    const safe = value => text(value).replace(/[\\/:*?"<>|]/g, '_').replace(/^[.\s]+|[.\s]+$/g, '').slice(0, 60) || '보고서';
    const account = report.scope.kind === 'company' ? '전체합산' : safe(report.scope.ad_account_no || '미보관');
    return safe(view.company) + '_' + account + '_' + view.kind + '_' + view.p.period.start + '_' +
      view.p.period.end + '_v' + report.revision_no + '.pdf';
  }
  async function download(report, options) {
    const current = () => {
      try { return !!options && typeof options.isCurrent === 'function' && options.isCurrent() === true; }
      catch (_) { return false; }
    };
    if (!current()) fail('REPORT_PDF_STALE');
    const snapshot = structuredClone(report), bytes = await build(snapshot), name = filename(snapshot);
    if (!current()) fail('REPORT_PDF_STALE');
    const url = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'})), link = document.createElement('a');
    try {
      link.href = url; link.download = name; link.rel = 'noopener';
      document.body.appendChild(link); link.click();
    } catch (error) { URL.revokeObjectURL(url); throw error; }
    finally { link.remove(); }
    const revoke = URL.revokeObjectURL.bind(URL), timer = setTimeout(() => revoke(url), 30000);
    if (timer && typeof timer.unref === 'function') timer.unref();
    return {filename: name, bytes: bytes.length};
  }
  const api = Object.freeze({build, download});
  root.NaverReportPDF = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window === 'undefined' ? globalThis : window);
