/* PlaceAnalysisPage — 로직분석 「플레이스 분석」 화면 (오프라인·지역 업종)
 *
 * 스토어 분석과 동일 엔진 구조를 쓰되, 플레이스 프리셋으로:
 *  - 입력: 업체명·지역·추적 키워드(최대 10개, 분석 대상 1개 선택)·플레이스 검색결과 캡처(HTML)
 *  - 분석: POST /api/seo/analyze { vertical:'place', ... } → 로컬 10지표 점수·순위(3-state)·경쟁사
 *  - 보완 지표(저장수·예약·소식·정보)는 결과 화면에서 인라인 입력 → 재점수화(하이브리드)
 *  - 순위 추적: 캡처마다 순위가 하루 1점 누적 → 역Y축 선형 차트(§2)
 *  - AI 진단: POST /api/ai/feedback-all { vertical:'place', sections:{...} }
 *
 * 확정 시안(2026-07-23 v2) 구조·팔레트를 그대로 이식. 스타일은 css/place.css(.place-analysis 스코프).
 */
window.PlaceAnalysisPage = function PlaceAnalysisPage(props) {
    var React_ = React, useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
    var currentUser = props.currentUser || {};

    // ── 입력 상태 ──
    var _b = useState('');            var businessName = _b[0], setBusinessName = _b[1];
    var _r = useState('');            var region = _r[0], setRegion = _r[1];
    var _kws = useState([]);          var keywords = _kws[0], setKeywords = _kws[1];
    var _kin = useState('');          var kwInput = _kin[0], setKwInput = _kin[1];
    var _sel = useState('');          var selectedKw = _sel[0], setSelectedKw = _sel[1];
    var _html = useState('');         var placeHtml = _html[0], setPlaceHtml = _html[1];

    // 담당자 보완 지표
    var _supp = useState({ saves: '', photos: '', news_days: '', info_complete: '',
        has_booking: false, has_talk: false, has_order: false, rep_keyword: false });
    var supp = _supp[0], setSupp = _supp[1];

    // ── 결과 상태 ──
    var _load = useState(false);      var loading = _load[0], setLoading = _load[1];
    var _res = useState(null);        var result = _res[0], setResult = _res[1];
    var _al = useState(false);        var aiLoading = _al[0], setAiLoading = _al[1];
    var _ai = useState(null);         var ai = _ai[0], setAi = _ai[1];
    var _ax = useState(true);         var aiExpanded = _ax[0], setAiExpanded = _ax[1];
    var _cs = useState([]);           var chartSeries = _cs[0], setChartSeries = _cs[1];
    var _cd = useState(30);           var chartDays = _cd[0], setChartDays = _cd[1];
    var _ck = useState('');           var chartKeyword = _ck[0], setChartKeyword = _ck[1];
    var _kc = useState([]);           var kwChips = _kc[0], setKwChips = _kc[1];

    var lastHtmlRef = useRef('');
    var aiTimerRef = useRef(null);

    // ── 업체 저장 (스토어 SaveToClientSection 과 동일 규칙 — /cd/quick-register 재사용) ──
    var _sb = useState(false);        var saveBusy = _sb[0], setSaveBusy = _sb[1];
    var _sm = useState(null);         var saveMsg = _sm[0], setSaveMsg = _sm[1];

    // ── 보고서 내보내기 (스토어 ReportSection 과 동일 사용법 — ReportCapture 공용 빌더 재사용) ──
    var _eb = useState(false);        var exportBusy = _eb[0], setExportBusy = _eb[1];
    var _ec = useState('');           var exportCompany = _ec[0], setExportCompany = _ec[1];
    useEffect(function() { if (businessName) setExportCompany(businessName); }, [businessName]);

    // ==================== 유틸 ====================
    var METRIC_ORDER = ['rank', 'relevance', 'visitor_review', 'blog_review', 'save',
        'photo', 'booking', 'review_keyword', 'activity', 'info'];
    var MEASURED = { rank: 1, visitor_review: 1, blog_review: 1, relevance: 1, review_keyword: 1, photo: 1 };
    var scoreCol = function(s) { return (window.scoreColor ? window.scoreColor(s) : (s >= 70 ? '#059669' : s >= 40 ? '#d97706' : '#dc2626')); };
    var gradeOf = function(t) {
        if (t >= 90) return 'A+'; if (t >= 83) return 'A'; if (t >= 77) return 'A-';
        if (t >= 71) return 'B+'; if (t >= 65) return 'B'; if (t >= 59) return 'B-';
        if (t >= 52) return 'C+'; if (t >= 45) return 'C'; if (t >= 38) return 'C-';
        if (t >= 30) return 'D'; return 'F';
    };
    var fmtN = function(n) { return (window.fmt ? window.fmt(n) : (n == null ? '-' : String(n))); };

    var suppPayload = function() {
        var p = {};
        if (supp.saves !== '') p.saves = Number(supp.saves) || 0;
        if (supp.photos !== '') p.photos = Number(supp.photos) || 0;
        if (supp.news_days !== '') p.news_days = Number(supp.news_days);
        if (supp.info_complete !== '') p.info_complete = Math.max(0, Math.min(100, Number(supp.info_complete) || 0));
        p.has_booking = !!supp.has_booking; p.has_talk = !!supp.has_talk; p.has_order = !!supp.has_order;
        p.rep_keyword = !!supp.rep_keyword;
        return p;
    };

    // ==================== 키워드 관리 ====================
    var addKeyword = function(raw) {
        var t = (raw || '').trim();
        if (!t) return;
        if (keywords.indexOf(t) !== -1) { setKwInput(''); return; }
        if (keywords.length >= 10) { try { toast.warn('추적 키워드는 최대 10개입니다.'); } catch(e){} return; }
        var next = keywords.concat([t]);
        setKeywords(next);
        if (!selectedKw) setSelectedKw(t);
        setKwInput('');
    };
    var removeKeyword = function(kw) {
        var next = keywords.filter(function(k) { return k !== kw; });
        setKeywords(next);
        if (selectedKw === kw) setSelectedKw(next[0] || '');
    };

    // ==================== 분석 실행 ====================
    var runAnalyze = function(opts) {
        opts = opts || {};
        var kw = selectedKw || keywords[0] || '';
        var html = opts.reuseHtml ? (lastHtmlRef.current || placeHtml) : placeHtml;
        if (!businessName.trim()) { try { toast.warn('업체명을 입력해주세요.'); } catch(e){} return; }
        if (!kw) { try { toast.warn('추적 키워드를 1개 이상 추가하고, 분석할 키워드를 선택하세요.'); } catch(e){} return; }
        if ((html || '').trim().length < 100) { try { toast.warn('플레이스 검색결과 HTML을 붙여넣어주세요. (북마클릿으로 캡처)'); } catch(e){} return; }

        setLoading(true);
        lastHtmlRef.current = html;
        var body = {
            // ⚠️ product_url 은 SeoAnalysisRequest 의 **필수 필드**다(쇼핑 경로용).
            //    플레이스는 상품 URL 이 없어 안 보냈는데, 그러면 요청이 서버 검증에서
            //    422 로 튕기고 화면엔 「[object Object]」만 떴다(2026-08-05 대표 신고).
            //    플레이스 분기는 product_url 을 읽지 않으므로 빈 문자열로 형식만 맞춘다.
            product_url: '',
            vertical: 'place', keyword: kw, region: region.trim(),
            target_name: businessName.trim(), place_html: html, place: suppPayload()
        };
        api.post('/seo/analyze', body).then(function(res) {
            setLoading(false);
            if (res && res.success && res.data) {
                setResult(res.data);
                setChartKeyword(kw);
                loadHistory(res.data.business_key, kw, chartDays);
                loadKeywords(res.data.business_key);
                if (!opts.silent) {
                    try { window.scrollTo({ top: 260, behavior: 'smooth' }); } catch(e){}
                    fetchAi(res.data);
                }
            } else {
                try { toast.error((res && res.detail) || '플레이스 분석에 실패했습니다.'); } catch(e){}
            }
        }).catch(function() { setLoading(false); });
    };

    // ==================== 순위 이력·키워드 ====================
    var loadHistory = function(bk, kw, days) {
        if (!bk || !kw) { setChartSeries([]); return; }
        api.get('/place/rank-history?business=' + encodeURIComponent(bk) + '&keyword=' + encodeURIComponent(kw) + '&days=' + (days || 30))
            .then(function(res) { if (res && res.success && res.data) setChartSeries(res.data.series || []); })
            .catch(function() {});
    };
    var loadKeywords = function(bk) {
        if (!bk) return;
        api.get('/place/keywords?business=' + encodeURIComponent(bk))
            .then(function(res) { if (res && res.success && res.data) setKwChips(res.data.keywords || []); })
            .catch(function() {});
    };
    var onChartDays = function(d) {
        setChartDays(d);
        if (result) loadHistory(result.business_key, chartKeyword || selectedKw, d);
    };

    // ==================== AI 진단 ====================
    var fetchAi = function(data) {
        if (!data) return;
        if (aiTimerRef.current) { clearTimeout(aiTimerRef.current); aiTimerRef.current = null; }
        setAiLoading(true); setAi(null);
        var sc = data.scores || {};
        var comp = (data.competitors || []).slice(0, 5);
        var sections = {
            rank: { keyword: data.keyword, region: data.region, rank_state: data.rank_state, rank: data.rank, page: data.page },
            review: { visitor_review_score: sc.visitor_review, blog_review_score: sc.blog_review, review_keyword_score: sc.review_keyword },
            competition: { my_rank: data.rank, competitors: comp },
            opportunity: { scores: sc, suggestions: data.suggestions || [] },
            strategy: { total: sc.total, scores: sc, weights: data.weights }
        };
        api.post('/ai/feedback-all', {
            vertical: 'place', keyword: data.keyword, sections: sections,
            client_name: (businessName || ''), call_type: 'place'
        }).then(function(res) {
            setAiLoading(false);
            if (res && res.success && res.data) setAi(res.data.feedbacks || {});
        }).catch(function() { setAiLoading(false); });
    };

    // 보완 지표 변경 시 즉시 저장은 안 하고, [재점수화] 버튼으로 반영(불필요한 재호출 방지)
    var rescore = function() { runAnalyze({ reuseHtml: true, silent: true }); };

    var resetCapture = function() { setPlaceHtml(''); };

    // ==================== 렌더 헬퍼 ====================
    var htmlKB = placeHtml ? (new Blob([placeHtml]).size / 1024).toFixed(0) : 0;
    var organicHint = (function() {
        if (!placeHtml) return '';
        var m = (placeHtml.match(/data-nmb_res-doc-id=/g) || []).length;
        return m ? ('오가닉 ' + m + '곳 인식') : '';
    })();

    var bookmarklet = "javascript:(function(){try{var h=document.documentElement.outerHTML;navigator.clipboard.writeText(h).then(function(){alert('\\u2705 \\ud50c\\ub808\\uc774\\uc2a4 HTML '+Math.round(h.length/1024)+'KB \\ubcf5\\uc0ac \\uc644\\ub8cc! \\ub85c\\uc9c1\\ubd84\\uc11d \\uce78\\uc5d0 \\ubd99\\uc5ec\\ub123\\uc73c\\uc138\\uc694.');}).catch(function(){var t=document.createElement('textarea');t.value=h;document.body.appendChild(t);t.select();document.execCommand('copy');document.body.removeChild(t);alert('\\u2705 HTML \\ubcf5\\uc0ac \\uc644\\ub8cc!');});}catch(e){alert('\\u274c \\ubcf5\\uc0ac \\uc2e4\\ud328: '+e.message);}})();";

    // ── 입력 섹션 ──
    var renderInput = function() {
        return (
            React_.createElement('div', { className: 'search-section' },
                React_.createElement('div', { className: 'ss-head' },
                    React_.createElement('div', { className: 'ic' }, '📍'),
                    React_.createElement('div', null,
                        React_.createElement('h3', null, '플레이스 분석 실행'),
                        React_.createElement('div', { className: 'sub' }, '오프라인·지역 업종 — 상품 HTML 대신 ', React_.createElement('b', null, '플레이스 검색결과'), '를 캡처해 분석합니다'))),
                React_.createElement('div', { className: 'frm' },
                    // 1행: 업체명 + 키워드
                    React_.createElement('div', { className: 'grid-in' },
                        React_.createElement('div', { className: 'field' },
                            React_.createElement('label', null, '업체명 ', React_.createElement('span', { className: 'req' }, '*')),
                            React_.createElement('input', { className: 'inp' + (businessName ? ' filled' : ''), value: businessName,
                                onChange: function(e) { setBusinessName(e.target.value); }, placeholder: '예: 성수 감성커피' })),
                        React_.createElement('div', { className: 'field' },
                            React_.createElement('label', null, '추적 키워드 ', React_.createElement('span', { className: 'req' }, '*'),
                                ' ', React_.createElement('span', { style: { color: '#94a3b8', fontWeight: 400 } }, '(최대 10개 · 칩 클릭=분석 대상 선택)')),
                            React_.createElement('div', { className: 'kwbox' },
                                keywords.map(function(kw) {
                                    return React_.createElement('span', { key: kw, className: 'kwtag' + (kw === selectedKw ? ' sel' : ''),
                                        onClick: function() { setSelectedKw(kw); }, title: '클릭 = 이 키워드를 분석 대상으로' },
                                        kw, React_.createElement('span', { className: 'x', onClick: function(e) { e.stopPropagation(); removeKeyword(kw); } }, '×'));
                                }),
                                React_.createElement('input', { className: 'kwin', value: kwInput, placeholder: keywords.length ? '키워드 추가…' : '예: 성수동 카페 (Enter)',
                                    onChange: function(e) { setKwInput(e.target.value); },
                                    onKeyDown: function(e) { if (e.key === 'Enter') { e.preventDefault(); addKeyword(kwInput); } } })))),
                    // 2행: 지역 + 캡처
                    React_.createElement('div', { className: 'grid-in' },
                        React_.createElement('div', { className: 'field' },
                            React_.createElement('label', null, '지역 ',
                                React_.createElement('span', { style: { color: '#94a3b8', fontWeight: 400 } }, '(동 이름 — 맞춤제안서와 같게)')),
                            React_.createElement('input', { className: 'inp' + (region ? ' filled' : ''), value: region,
                                onChange: function(e) { setRegion(e.target.value); }, placeholder: '예: 성수동' })),
                        React_.createElement('div', { className: 'field' },
                            React_.createElement('label', null, '플레이스 검색결과 캡처 ', React_.createElement('span', { className: 'req' }, '*'),
                                ' ', React_.createElement('span', { style: { color: '#94a3b8', fontWeight: 400 } }, '(선택한 키워드의 검색결과)')),
                            placeHtml
                                ? React_.createElement('div', { className: 'capbox' },
                                    React_.createElement('span', { className: 'big' }, '✓ 검색결과 HTML 붙여넣음'),
                                    React_.createElement('span', { className: 'kb' }, htmlKB + ' KB' + (organicHint ? (' · ' + organicHint) : '')),
                                    React_.createElement('button', { type: 'button', className: 're', onClick: resetCapture }, '↻ 초기화'))
                                : React_.createElement('textarea', { className: 'inp', style: { minHeight: 44 }, value: placeHtml,
                                    onChange: function(e) { setPlaceHtml(e.target.value); },
                                    placeholder: '네이버 플레이스 검색결과 페이지 HTML을 붙여넣으세요 (북마클릿 사용)' }))),
                    // 북마클릿
                    React_.createElement('div', { className: 'bmk' },
                        React_.createElement('span', { style: { fontSize: 16 } }, '🔖'),
                        React_.createElement('div', { style: { flex: 1, minWidth: 220 } },
                            React_.createElement('b', null, '북마클릿(가장 쉬움)'), ' — 오른쪽 파란 버튼을 브라우저 북마크바로 ',
                            React_.createElement('b', null, '드래그'), '해 두면, 네이버 플레이스 ', React_.createElement('b', null, '검색결과 페이지에서 클릭 한 번'), '으로 HTML이 복사됩니다 → 위 칸에 붙여넣기'),
                        React_.createElement('a', { className: 'drag', href: bookmarklet, draggable: 'true',
                            onClick: function(e) { e.preventDefault(); try { toast.info('클릭하지 말고 브라우저 북마크바로 드래그해서 놓으세요. (북마크바: Ctrl+Shift+B)'); } catch(er){} } },
                            '📎 플레이스 캡처 (북마크바로 드래그)')),
                    // 실행
                    React_.createElement('div', { className: 'runrow' },
                        React_.createElement('button', { className: 'btn btn-primary', disabled: loading, onClick: function() { runAnalyze(); } },
                            loading ? React_.createElement(React_.Fragment, null, React_.createElement('span', { className: 'spin' }), ' 분석 중…') : '📍 분석 실행'),
                        React_.createElement('span', { className: 'hint' }, '담당자 보완 지표(저장수·예약·소식 등)는 결과 화면에서 바로 입력·저장')))
            )
        );
    };

    // ── 커버 · 목차 · 범례 — 스토어(AnalysisResults)와 동일한 보고서 골격 ──
    // 대표 지시(2026-08-11): 「쇼핑 분석과 디자인·배치·사용법을 동일하게」. 표지(.report-cover)·
    // 배지 범례(.report-legend)·모바일 목차(.anchor-nav)·좌측 목차(.report-toc)를 스토어 마크업
    // 그대로 쓴다(report-theme.css 공용) — 내용(업체명·지역 축)만 플레이스.
    var TOC_SECTIONS = [
        { id: 'sec-place-score', icon: '🎯', label: '종합 경쟁력' },
        { id: 'sec-place-kw', icon: '📍', label: '키워드 노출 순위' },
        { id: 'sec-place-comp', icon: '⚔️', label: '경쟁 비교' },
        { id: 'sec-ai-feedback', icon: '🤖', label: 'AI 진단·처방' },
        { id: 'sec-save-client', icon: '💾', label: '업체 저장' },
        { id: 'sec-report', icon: '📄', label: '보고서 내보내기' }
    ];
    var scrollToSec = function(id) {
        try { var el = document.getElementById(id); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch(e) {}
    };
    var renderCover = function() {
        return (
            React_.createElement(React_.Fragment, null,
                React_.createElement('div', { className: 'report-cover' },
                    React_.createElement('div', { className: 'report-cover-head' },
                        React_.createElement('span', { className: 'rc-ic' }, '📋'),
                        React_.createElement('span', { className: 'rc-title' }, '플레이스 분석 보고서')),
                    React_.createElement('div', { className: 'rc-grid' },
                        React_.createElement('div', { className: 'rc-field' },
                            React_.createElement('div', { className: 'rc-k' }, '광고주 / 업체'),
                            React_.createElement('div', { className: 'rc-v' }, result.business_name || businessName || '-')),
                        React_.createElement('div', { className: 'rc-field' },
                            React_.createElement('div', { className: 'rc-k' }, '분석 키워드'),
                            React_.createElement('div', { className: 'rc-v' }, result.keyword || selectedKw || '-')),
                        React_.createElement('div', { className: 'rc-field' },
                            React_.createElement('div', { className: 'rc-k' }, '지역'),
                            React_.createElement('div', { className: 'rc-v' }, (result.region || region || '미지정') + (result.category ? (' · ' + result.category) : ''))),
                        React_.createElement('div', { className: 'rc-field' },
                            React_.createElement('div', { className: 'rc-k' }, '분석일'),
                            React_.createElement('div', { className: 'rc-v' }, (result.analyzed_at || '').slice(0, 10) || new Date().toLocaleDateString('ko'))))),
                React_.createElement('div', { className: 'report-legend' },
                    React_.createElement('b', { className: 'badge b-ok' }, '✅ 실측'), ' 캡처 검색결과 실제값',
                    React_.createElement('span', { className: 'rl-sep' }, '·'),
                    React_.createElement('b', { className: 'badge b-est' }, '≈ 추정'), ' 계산·근거 기반',
                    React_.createElement('span', { className: 'rl-sep' }, '·'),
                    React_.createElement('b', { className: 'badge b-ai' }, 'AI'), ' AI 생성'),
                React_.createElement('div', { className: 'anchor-nav-wrap' },
                    React_.createElement('div', { className: 'container' },
                        React_.createElement('div', { className: 'anchor-nav' },
                            TOC_SECTIONS.map(function(s) {
                                return React_.createElement('button', { key: s.id, className: 'anchor-btn', onClick: function() { scrollToSec(s.id); } },
                                    React_.createElement('span', { className: 'anchor-icon' }, s.icon), s.label);
                            })))))
        );
    };

    // ── §1 종합 경쟁력 ──
    var renderSec1 = function() {
        var sc = result.scores || {};
        var labels = result.labels || {};
        var weights = result.weights || {};
        var total = sc.total || 0;
        var col = scoreCol(total);
        // 강·약점 도출
        var arr = METRIC_ORDER.map(function(k) { return { k: k, label: labels[k] || k, s: sc[k] || 0 }; });
        var strong = arr.filter(function(x) { return x.s >= 68; }).sort(function(a, b) { return b.s - a.s; }).slice(0, 3).map(function(x) { return x.label; });
        var weak = arr.filter(function(x) { return x.s < 50; }).sort(function(a, b) { return a.s - b.s; }).slice(0, 3).map(function(x) { return x.label; });
        return (
            React_.createElement(React_.Fragment, null,
                React_.createElement(window.SectionDivider, { label: '1. 종합 경쟁력', icon: '🎯', color: '#3b82f6', sub: '플레이스 로컬 10지표 가중 점수 · 강·약점' }),
                React_.createElement('section', { id: 'sec-place-score', className: 'section' },
                    React_.createElement('div', { className: 'container' },
                React_.createElement('div', { className: 'card' },
                    React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '🎯'), '플레이스 종합 경쟁력 ',
                        React_.createElement('span', { className: 'badge b-est' }, '≈ 가중')),
                    React_.createElement('div', { className: 'rt-desc' }, '10개 지표를 0~100점으로 채점하고 가중치(합 1.00)로 종합 점수를 산출합니다. 스토어 분석과 동일한 엔진 구조 — 지표·프리셋만 플레이스로 교체.'),
                    React_.createElement('div', { className: 'scorewrap' },
                        React_.createElement('div', { className: 'ring', style: { background: 'conic-gradient(' + col + ' ' + (total * 3.6) + 'deg, var(--pa-track) 0)' } },
                            React_.createElement('div', { className: 'inr' },
                                React_.createElement('div', { className: 'n' }, total, React_.createElement('small', null, '/100')),
                                React_.createElement('div', { className: 'g', style: { color: col } }, '등급 ' + gradeOf(total)))),
                        React_.createElement('div', { className: 'str' },
                            React_.createElement('div', { className: 'row good' }, React_.createElement('span', { className: 'ic' }, '↑'),
                                React_.createElement('div', null, React_.createElement('b', null, '강점'), ' — ', strong.length ? strong.join(' · ') : '지표 보강 필요')),
                            React_.createElement('div', { className: 'row bad' }, React_.createElement('span', { className: 'ic' }, '↓'),
                                React_.createElement('div', null, React_.createElement('b', null, '개선 우선'), ' — ', weak.length ? (weak.join(' · ') + ' 가 상위권 대비 부족(주황 막대)') : '전반적으로 양호')),
                            React_.createElement('div', { className: 'row mid' }, React_.createElement('span', { className: 'ic' }, '→'),
                                React_.createElement('div', null, React_.createElement('b', null, '기회'), ' — 저장·블로그 등 인기도 지표를 보강하면 대표키워드 방어 + 중위 키워드 상승 여지가 큽니다.')))),
                    // 10 지표 막대
                    React_.createElement('div', { className: 'metrics' },
                        METRIC_ORDER.map(function(k) {
                            var v = sc[k] || 0;
                            var low = v < 50;
                            return React_.createElement('div', { key: k, className: 'scorebar' + (low ? ' low' : '') },
                                React_.createElement('div', { className: 'lbl' },
                                    React_.createElement('span', { className: 'nm' }, labels[k] || k,
                                        React_.createElement('span', { className: 'w' }, (weights[k] != null ? weights[k].toFixed(2) : '')),
                                        React_.createElement('span', { className: 'mk ' + (MEASURED[k] ? 'meas' : 'inp') }, MEASURED[k] ? '측정' : '보완')),
                                    React_.createElement('span', { className: 'sc' }, v)),
                                React_.createElement('div', { className: 'track' }, React_.createElement('i', { style: { width: v + '%' } })));
                        })),
                    // 보완 지표 편집
                    renderSuppEditor(),
                    React_.createElement('div', { className: 'note', style: { marginTop: 14 } },
                        React_.createElement('b', null, '측정 vs 보완:'), ' 순위·리뷰·적합도·사진은 캡처에서 ', React_.createElement('b', null, '자동 측정'),
                        ', 저장수·예약·소식·업체정보는 담당자가 ', React_.createElement('b', null, '보완 입력'), '(하이브리드). 보완 지표를 채우고 ', React_.createElement('b', null, '재점수화'), '하면 점수에 반영됩니다.'))))
            )
        );
    };

    var chkBtn = function(key, label) {
        return React_.createElement('button', { type: 'button', className: 'chkb' + (supp[key] ? ' on' : ''),
            onClick: function() { var n = Object.assign({}, supp); n[key] = !n[key]; setSupp(n); } },
            (supp[key] ? '✓ ' : '') + label);
    };
    var suppNum = function(key, label, ph) {
        return React_.createElement('div', { className: 'suppf' },
            React_.createElement('label', null, label),
            React_.createElement('input', { className: 'si', type: 'number', min: 0, value: supp[key], placeholder: ph || '',
                onChange: function(e) { var n = Object.assign({}, supp); n[key] = e.target.value; setSupp(n); } }));
    };
    var renderSuppEditor = function() {
        // no-export: 담당자 입력 도구 — 광고주 전달본(보고서 내보내기)에서 자동 제거
        return (
            React_.createElement('div', { className: 'suppcard no-export' },
                React_.createElement('h4', null, '✍️ 담당자 보완 지표'),
                React_.createElement('div', { className: 'sd' }, '캡처로 측정되지 않는 지표를 입력하세요. 방문자·블로그 리뷰는 캡처에서 자동 인식되며, 값을 직접 넣으면 그 값이 우선됩니다.'),
                React_.createElement('div', { className: 'suppgrid' },
                    suppNum('saves', '저장수(즐겨찾기)', '예: 1020'),
                    suppNum('photos', '사진 수', '예: 96'),
                    suppNum('news_days', '소식 최근 게시(일 전)', '예: 18'),
                    suppNum('info_complete', '업체정보 완성도(0~100)', '예: 80')),
                React_.createElement('div', { className: 'chk', style: { marginTop: 12 } },
                    chkBtn('has_booking', '예약'), chkBtn('has_talk', '톡톡'), chkBtn('has_order', '주문'), chkBtn('rep_keyword', '대표키워드 등록')),
                React_.createElement('div', { className: 'supprow' },
                    React_.createElement('button', { className: 'btn btn-primary btn-sm', disabled: loading, onClick: rescore },
                        loading ? React_.createElement(React_.Fragment, null, React_.createElement('span', { className: 'spin' }), ' 반영 중…') : '↻ 보완 지표 반영(재점수화)'),
                    React_.createElement('span', { className: 'hint', style: { fontSize: 11.5, color: '#94a3b8' } }, '입력값은 다음 분석에도 유지됩니다.')))
        );
    };

    // ── §2 키워드 노출 순위 ──
    var chipClass = function(c) {
        if (c.state === '미확인' || (c.state !== '노출' && c.rank == null && c.state !== '미노출')) return 'unk';
        if (c.state === '미노출' || c.rank == null) return 'off';
        if (c.rank <= 10) return '';
        if (c.rank <= 30) return 'warn';
        return 'off';
    };
    var renderSec2 = function() {
        // 입력 키워드 + 서버 추적 키워드 병합
        var map = {}; (kwChips || []).forEach(function(c) { map[c.keyword] = c; });
        var union = [];
        keywords.forEach(function(k) { if (union.indexOf(k) === -1) union.push(k); });
        (kwChips || []).forEach(function(c) { if (union.indexOf(c.keyword) === -1) union.push(c.keyword); });
        var chips = union.map(function(k) { return map[k] || { keyword: k, rank: null, state: '미확인' }; });
        var exposed = chips.filter(function(c) { return c.state === '노출'; });
        var notExp = chips.filter(function(c) { return c.state === '미노출'; });
        var unk = chips.filter(function(c) { return c.state === '미확인'; });
        var rate = chips.length ? Math.round(exposed.length / chips.length * 100) : 0;
        return (
            React_.createElement(React_.Fragment, null,
                React_.createElement(window.SectionDivider, { label: '2. 키워드 노출 순위', icon: '📍', color: '#059669', sub: '지역+키워드 기준 노출/미노출/미확인 · 일자별 추적' }),
                React_.createElement('section', { id: 'sec-place-kw', className: 'section' },
                    React_.createElement('div', { className: 'container' },
                React_.createElement('div', { className: 'card' },
                    React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '📍'), '키워드별 노출 순위 ',
                        React_.createElement('span', { className: 'badge b-ok' }, '✅ 실측')),
                    React_.createElement('div', { className: 'rt-desc' }, '캡처한 검색결과에서 내 업체의 오가닉 순위를 키워드별로 찾습니다. ', React_.createElement('b', null, '미확인'), ' = 아직 캡처·분석하지 않은 키워드(실제 미노출과 구분).'),
                    React_.createElement('div', { className: 'pills' },
                        React_.createElement('span', { className: 'ps ps-g' }, '노출 ' + exposed.length + '개'),
                        React_.createElement('span', { className: 'ps ps-r' }, '미노출 ' + notExp.length + '개'),
                        React_.createElement('span', { className: 'ps ps-n' }, '미확인 ' + unk.length + '개')),
                    React_.createElement('div', { className: 'grid3' },
                        React_.createElement('div', { className: 'ratecard g' }, React_.createElement('div', { className: 'v' }, exposed.length), React_.createElement('div', { className: 'k' }, '노출 키워드')),
                        React_.createElement('div', { className: 'ratecard r' }, React_.createElement('div', { className: 'v' }, notExp.length), React_.createElement('div', { className: 'k' }, '미노출')),
                        React_.createElement('div', { className: 'ratecard p' }, React_.createElement('div', { className: 'v' }, rate + '%'), React_.createElement('div', { className: 'k' }, '노출률'))),
                    React_.createElement('div', { className: 'kwgrid' },
                        chips.map(function(c) {
                            var cls = chipClass(c);
                            var rk = (c.state === '미확인') ? '?' : (c.rank != null ? (c.rank + '위') : '밖');
                            return React_.createElement('span', { key: c.keyword, className: 'kwchip ' + cls + (c.keyword === chartKeyword ? ' cur' : ''),
                                onClick: function() { setChartKeyword(c.keyword); loadHistory(result.business_key, c.keyword, chartDays); },
                                title: '클릭 = 이 키워드 순위 추이 보기', style: { cursor: 'pointer' } },
                                React_.createElement('span', { className: 'rk' }, rk), c.keyword + (c.state === '미확인' ? ' · 미확인' : ''));
                        })),
                    React_.createElement(window.PlaceRankChart, { series: chartSeries, keyword: chartKeyword || selectedKw, days: chartDays, businessName: businessName, onDays: onChartDays }))))
            )
        );
    };

    // ── 업체 저장 카드 (스토어와 동일 규칙: viewer=영업 대상 30일 유예 / 관리팀=광고주 영구) ──
    var saveToClient = function (role) {
        if (saveBusy) return;
        var name = (businessName || '').trim();
        var kw = (selectedKw || keywords[0] || '').trim();
        if (!name) { try { toast.warn('업체명이 없습니다.'); } catch (e) {} return; }
        if (!kw) { try { toast.warn('키워드가 없습니다.'); } catch (e) {} return; }
        // 매칭된 플레이스 doc-id → 지도 링크.
        // ⚠️ 종전엔 `result.rank_info.matched` 를 읽었는데 **응답에 rank_info 키 자체가 없어**
        //    지도 링크가 늘 빈 값이었다(저장한 영업 대상을 다시 열면 빈 패널). 2026-08-05 수정.
        //    서버가 내려주는 place_id 를 쓰고, 없으면 business_key 의 `doc:` 접두에서 뽑는다.
        var pid = '';
        try {
            pid = String((result && result.place_id) || '');
            if (!pid) {
                var bk = String((result && result.business_key) || '');
                if (bk.indexOf('doc:') === 0) pid = bk.slice(4);
            }
        } catch (e) {}
        setSaveBusy(true); setSaveMsg(null);
        api.post('/cd/quick-register', {
            name: name, keyword: kw,
            product_url: pid ? ('https://map.naver.com/p/entry/place/' + pid) : '',
            vertical: 'place', role: role
        }).then(function (res) {
            setSaveBusy(false);
            if (res && res.success) setSaveMsg({ ok: true, text: res.message || '저장되었습니다.' });
            else setSaveMsg({ ok: false, text: (res && (typeof res.detail === 'string' ? res.detail : res.error)) || '저장에 실패했습니다.' });
        }).catch(function () { setSaveBusy(false); setSaveMsg({ ok: false, text: '저장 중 오류가 발생했습니다.' }); });
    };
    var renderSaveCard = function () {
        var isViewer = (currentUser.role === 'viewer');
        var canAdv = (currentUser.role === 'manager' || currentUser.role === 'superadmin');
        // #sec-save-client — ReportCapture 가 이 id 로 내보내기에서 제거(직원 전용 도구 = 전달본 미포함)
        return React_.createElement('section', { id: 'sec-save-client', className: 'section' },
            React_.createElement('div', { className: 'container' },
                React_.createElement('div', { className: 'card', style: { marginTop: 14 } },
            React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '💾'), '업체 저장 ',
                React_.createElement('span', { className: 'badge b-ok' }, '스토어와 동일 규칙')),
            React_.createElement('div', { className: 'rt-desc' },
                isViewer
                    ? '이 업체를 내 영업 대상으로 저장합니다 — 본인만 열람 · 30일 후 자동 삭제(재저장 시 연장). 스토어 분석과 동일합니다.'
                    : '이 업체를 광고주로 등록(영구)하거나 영업 대상으로 저장합니다 — 광고주 대시보드 목록·권한이 스토어와 동일한 파이프라인입니다.'),
            React_.createElement('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' } },
                canAdv && React_.createElement('button', { className: 'btn btn-primary', disabled: saveBusy,
                    onClick: function () { saveToClient('advertiser'); } }, saveBusy ? '저장 중…' : '⭐ 광고주로 등록 (영구)'),
                React_.createElement('button', { className: canAdv ? 'btn btn-secondary' : 'btn btn-primary', disabled: saveBusy,
                    onClick: function () { saveToClient('prospect'); } }, saveBusy ? '저장 중…' : '🎯 영업 대상으로 저장' + (isViewer ? ' (30일)' : ''))),
            saveMsg && React_.createElement('div', { className: 'note ' + (saveMsg.ok ? 'ok' : 'est'), style: { marginTop: 10 } },
                (saveMsg.ok ? '✅ ' : '⚠️ ') + saveMsg.text))));
    };

    // ── 보고서 내보내기 — 스토어 ReportSection 의 HTML 경로와 동일(공용 ReportCapture 빌더 재사용).
    //    JSON/CSV 는 스토어 추적상품(/report/export) 전용 데이터라 플레이스엔 해당 없음 — HTML 단일.
    var handleHtmlExport = function() {
        /* AI 종합 분석이 진행 중이면 완료 대기를 먼저 권유 (강행 시 해당 섹션은 '별도 전달' 안내로 대체) */
        try {
            if (window.ReportCapture && window.ReportCapture.aiState() === 'loading') {
                var goNow = window.confirm('🤖 AI 종합 분석이 아직 진행 중입니다 (약 20~30초).\n완료 후 내보내면 AI 분석이 보고서에 포함됩니다.\n\n지금 바로 내보내시겠습니까?\n(AI 섹션은 "완료 후 별도 전달" 안내로 대체됩니다)');
                if (!goNow) return;
            }
        } catch(eG) {}
        setExportBusy(true);
        try {
            var nm = (exportCompany || businessName || '').trim();
            var headerText = nm ? nm + ' 플레이스 분석 보고서' : '플레이스 분석 보고서';
            var fullHtml = window.ReportCapture
                ? window.ReportCapture.buildHtml({ title: headerText, managerName: currentUser && currentUser.name })
                : '';
            if (!fullHtml) { throw new Error('캡처 대상(.report-main)을 찾지 못했습니다'); }
            var blob = new Blob([fullHtml], { type: 'text/html;charset=utf-8' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = (nm || '플레이스분석') + '_보고서_' + new Date().toISOString().slice(0, 10) + '.html';
            a.click();
            URL.revokeObjectURL(url);
            alert('HTML 보고서가 다운로드되었습니다.');
        } catch(e) {
            alert('HTML 보고서 생성 실패: ' + e.message);
        }
        setExportBusy(false);
    };
    var renderReportSection = function() {
        return React_.createElement('div', { className: 'section fade-in', id: 'sec-report' },
            React_.createElement('div', { className: 'container' },
                React_.createElement('div', { className: 'section-title' },
                    React_.createElement('span', { className: 'icon', style: { background: '#eff6ff' } }, '📄'),
                    '보고서 내보내기'),
                React_.createElement('div', { className: 'section-line' }),
                React_.createElement('p', { className: 'section-subtitle' }, '분석 결과를 광고주 전달용 HTML 보고서로 다운로드합니다'),
                React_.createElement('div', { className: 'card' },
                    React_.createElement('div', { style: { display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' } },
                        React_.createElement('div', { className: 'form-group', style: { marginBottom: 0 } },
                            React_.createElement('label', { className: 'form-label' }, '업체명 (선택)'),
                            React_.createElement('input', { className: 'form-input', style: { width: 160 }, placeholder: '업체명 입력',
                                value: exportCompany, onChange: function(e) { setExportCompany(e.target.value); } })),
                        React_.createElement('button', { className: 'btn btn-primary', onClick: handleHtmlExport, disabled: exportBusy },
                            exportBusy ? '생성 중...' : '📄 HTML 보고서 다운로드')),
                    React_.createElement('div', { style: { marginTop: 12, padding: '10px 14px', background: '#f0f9ff', borderRadius: 8, fontSize: 13, color: '#0369a1' } },
                        '💡 현재 페이지에 표시된 분석 결과를 그대로 HTML 파일로 내보냅니다. 직원 전용 도구(보완 지표 입력·업체 저장·이 카드)는 전달본에서 자동 제외됩니다.'))));
    };

    // ── §3 경쟁 비교 ──
    var renderSec3 = function() {
        var comps = (result.competitors || []).slice(0, 5);
        // 내 업체 행(순위만 확정 — 방문자/블로그 리뷰는 응답에 미포함이라 표시 생략)
        var myRow = { name: (result.business_name || businessName || '내 업체'), rank: result.rank,
            visitor_reviews: null, blog_reviews: null, me: true };
        var rows = comps.map(function(c) { return { name: c.name, rank: c.rank, visitor_reviews: c.visitor_reviews, blog_reviews: c.blog_reviews, me: false }; });
        rows.push(myRow);
        rows.sort(function(a, b) { return (a.rank || 999) - (b.rank || 999); });
        var maxV = Math.max.apply(null, rows.map(function(r) { return r.visitor_reviews || 0; }).concat([1]));
        var rkClass = function(r) { return r == null ? '' : r <= 5 ? 'rk-hi' : r <= 15 ? 'rk-mid' : 'rk-lo'; };
        return (
            React_.createElement(React_.Fragment, null,
                React_.createElement(window.SectionDivider, { label: '3. 경쟁 비교', icon: '⚔️', color: '#ef4444', sub: "'" + (result.keyword || '') + "' 상위 노출 업체 대비 지표" }),
                React_.createElement('section', { id: 'sec-place-comp', className: 'section' },
                    React_.createElement('div', { className: 'container' },
                React_.createElement('div', { className: 'card' },
                    React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '⚔️'), '상위 노출 경쟁사 비교 ',
                        React_.createElement('span', { className: 'badge b-ok' }, '✅ 실측')),
                    React_.createElement('div', { className: 'rt-desc' }, '캡처 검색결과의 상위 오가닉 업체를 내 업체와 정면 비교합니다. 방문자·블로그 리뷰는 캡처에서 인식된 값입니다.'),
                    comps.length === 0
                        ? React_.createElement('div', { className: 'empty' }, '캡처에서 경쟁사 지표를 인식하지 못했습니다. 검색결과 HTML을 다시 캡처해 보세요.')
                        : React_.createElement('div', { className: 'twrap' },
                            React_.createElement('table', null,
                                React_.createElement('thead', null, React_.createElement('tr', null,
                                    React_.createElement('th', null, '순위'), React_.createElement('th', null, '업체'),
                                    React_.createElement('th', { className: 'n' }, '방문자 리뷰'), React_.createElement('th', { className: 'n' }, '블로그 리뷰'),
                                    React_.createElement('th', { style: { width: 160 } }, '방문자 리뷰 격차'))),
                                React_.createElement('tbody', null,
                                    rows.map(function(r, i) {
                                        var pct = maxV ? Math.round((r.visitor_reviews || 0) / maxV * 100) : 0;
                                        return React_.createElement('tr', { key: i, className: r.me ? 'me' : '' },
                                            React_.createElement('td', { className: 'rkcell ' + rkClass(r.rank) }, r.rank != null ? (r.rank + '위') : '미노출'),
                                            React_.createElement('td', null, r.name || '-', r.me ? React_.createElement('span', { className: 'metag' }, '내 업체') : null),
                                            React_.createElement('td', { className: 'n' }, fmtN(r.visitor_reviews)),
                                            React_.createElement('td', { className: 'n' }, fmtN(r.blog_reviews)),
                                            React_.createElement('td', null, React_.createElement('div', { className: 'gap' },
                                                React_.createElement('div', { className: 'gapbar' }, React_.createElement('i', { className: 'me-f', style: { width: pct + '%' } })))));
                                    })))),
                    React_.createElement('div', { className: 'note est', style: { marginTop: 13 } },
                        React_.createElement('b', null, '격차 진단 ≈ 추정:'), ' 방문자·블로그 리뷰가 상위권과 벌어질수록 인기도(순위) 병목이 큽니다. 저장수는 캡처로 인식되지 않으므로 §1 보완 지표에서 입력해 경쟁력에 반영하세요.'))))
            )
        );
    };

    // ── §4 AI 진단 ──
    // AI 서술 정돈 렌더 — 모델이 마크다운(###·**·표 구분선)을 섞어 보내도 기호가 화면에
    // 그대로 노출되지 않게 다듬는다(2026-08-11 직원 신고: 「AI 진단 처방에 ### 으로 나온다」).
    // 프롬프트에서도 금지하지만(원천), 규칙을 어긴 응답과 이미 생성된 텍스트까지 여기서 방어한다.
    // 스토어 AI 리포트와 같은 「기호 없는 산문」 기준: 제목 줄은 굵게, 불릿은 · 로, 강조 기호는 제거.
    var _aiInline = function(s) {
        return String(s || '')
            .replace(/\*\*\*([^*]+)\*\*\*/g, '$1')  // ***강조*** 를 먼저 — ** 규칙만 있으면 *강조* 별 1쌍이 잔류(검증에서 확인)
            .replace(/\*\*([^*]+)\*\*/g, '$1')      // **강조** → 강조 (단일별 *X* 는 산식(10,000*2)·원문일 수 있어 손대지 않음)
            .replace(/`([^`]+)`/g, '$1');           // `코드` → 코드
    };
    var renderAiText = function(txt) {
        var out = [];
        String(txt || '').split('\n').forEach(function(line, i) {
            // ###제목(공백 없음)도 소제목으로 인식. 단 #{1} 무공백(#해시태그)은 헤딩 아님 — 해시태그 원문 보존.
            var mHead = line.match(/^\s*(?:#{1,6}\s+|#{2,6})(.*)$/);
            if (mHead) {   // ### 소제목 → 굵은 줄(기호 제거)
                var ht = _aiInline(mHead[1]).trim();
                if (ht) out.push(React_.createElement('div', { key: 'h' + i, style: { fontWeight: 800, color: 'var(--pa-ink)', marginTop: out.length ? 4 : 0 } }, ht));
                return;
            }
            if (/^\s*[-*_]{3,}\s*$/.test(line)) return;          // --- 구분선 줄 제거
            var mBullet = line.match(/^(\s*)[-*•]\s+(.*)$/);      // - 불릿 → · (·aiblock 이 pre-wrap 이라 \n 유지)
            out.push((mBullet ? mBullet[1] + '· ' + _aiInline(mBullet[2]) : _aiInline(line)) + '\n');
        });
        return out;
    };
    var PLACE_AI_SECTIONS = [
        { key: 'summary', label: '종합 진단', icon: '🧭' },
        { key: 'rank', label: '노출 순위', icon: '📍' },
        { key: 'review', label: '리뷰 진단', icon: '💬' },
        { key: 'competition', label: '경쟁 비교', icon: '⚔️' },
        { key: 'opportunity', label: '기회 발굴', icon: '🌱' },
        { key: 'strategy', label: '전략·결론', icon: '🚀' }
    ];
    var renderSec4 = function() {
        var suggestions = result.suggestions || [];
        // 스토어 AiFeedbackAllSection 과 동일한 마크업·팔레트(대시 카드·그라데이션 버튼·접기/펼치기).
        // #sec-ai-feedback + 숨김 .ai-state 마커는 ReportCapture(보고서 내보내기)가 읽는 계약 —
        // AI 미완료 상태에서 내보내면 로딩 문구 대신 「완료 후 별도 전달」 안내로 치환된다.
        return (
            React_.createElement(React_.Fragment, null,
                React_.createElement(window.SectionDivider, { label: '4. AI 진단·처방', icon: '🤖', color: '#7c3aed', sub: '무엇을·왜·얼마나 하면 몇 위가 되는가' }),
                React_.createElement('section', { id: 'sec-ai-feedback', className: 'section' },
                    React_.createElement('span', { className: 'ai-state', style: { display: 'none' },
                        'data-state': aiLoading ? 'loading' : (ai ? 'done' : 'idle') }),
                    React_.createElement('div', { className: 'container' },
                        React_.createElement('div', { className: 'card',
                            style: { padding: '20px 22px', border: '2px dashed #c7d2fe', background: 'linear-gradient(135deg,#eef2ff,#faf5ff)' } },
                            // 헤더 — 스토어와 동일 배치(제목·설명 좌 / 접기·분석 버튼 우)
                            React_.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 } },
                                React_.createElement('div', null,
                                    React_.createElement('h3', { className: 'rt-h3' },
                                        React_.createElement('span', { className: 'rt-hic' }, '🤖'),
                                        'METAINC AI 종합 분석 리포트',
                                        React_.createElement('span', { className: 'badge b-ai' }, 'AI')),
                                    React_.createElement('div', { className: 'rt-desc' },
                                        '"' + (result.keyword || selectedKw || '') + '" 플레이스 상위노출 로직(적합도·인기도·거리)을 AI가 종합해 작성한 진단')),
                                React_.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 } },
                                    ai && React_.createElement('button', {
                                        onClick: function() { setAiExpanded(!aiExpanded); },
                                        style: { background: '#f1f5f9', border: '1px solid #e2e8f0', color: '#475569',
                                            padding: '6px 14px', borderRadius: 8, fontSize: 12, cursor: 'pointer' }
                                    }, aiExpanded ? '접기' : '펼치기'),
                                    !aiLoading && React_.createElement('button', {
                                        onClick: function() { fetchAi(result); },
                                        style: { background: 'linear-gradient(135deg, #38bdf8, #0ea5e9)', color: '#fff', border: 'none',
                                            padding: '8px 20px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                            boxShadow: '0 4px 12px rgba(14, 165, 233, 0.4)' }
                                    }, ai ? '다시 분석' : '✨ AI 종합 분석'),
                                    /* no-export: 상태 마커가 실패해도 로딩 문구만은 전달본에서 항상 제거(이중 방어) */
                                    aiLoading && React_.createElement('span', {
                                        className: 'no-export',
                                        style: { fontSize: 13, color: '#0ea5e9', fontWeight: 500 }
                                    }, '⏳ AI 분석 중... (약 20~30초)'))),
                            // 규칙 기반 처방(즉시) — 플레이스 전용 콘텐츠(스토어와 다른 부분은 내용뿐)
                            React_.createElement('div', { style: { margin: '14px 0 4px', fontSize: 13, fontWeight: 800, color: '#0f172a' } }, '개선 처방 (우선순위)'),
                            React_.createElement('div', null,
                                suggestions.map(function(s, i) {
                                    return React_.createElement('div', { key: i, className: 'rx' },
                                        React_.createElement('span', { className: 'no' }, i + 1),
                                        React_.createElement('div', { className: 'tx' }, s));
                                })),
                            // AI 서술 — 스토어와 동일한 블록 카드(요약=앰버)
                            ai && aiExpanded && React_.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16, marginTop: 18 } },
                                PLACE_AI_SECTIONS.filter(function(s) { return ai[s.key]; }).map(function(s) {
                                    var isSummary = s.key === 'summary';
                                    return React_.createElement('div', { key: s.key,
                                        style: { background: isSummary ? '#fffbeb' : '#f8fafc', borderRadius: 12,
                                            padding: '16px 20px', border: isSummary ? '1px solid #fde68a' : '1px solid #e2e8f0' } },
                                        React_.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 } },
                                            React_.createElement('span', { style: { fontSize: 16 } }, s.icon),
                                            React_.createElement('span', { style: { fontSize: 14, fontWeight: 700, color: isSummary ? '#b45309' : '#0369a1' } }, s.label)),
                                        React_.createElement('div', { style: { fontSize: 13, lineHeight: 1.75, color: '#334155', whiteSpace: 'pre-wrap' } },
                                            renderAiText(ai[s.key])));
                                })),
                            !ai && !aiLoading && React_.createElement('div', { className: 'note', style: { marginTop: 10 } },
                                'AI 종합 진단은 분석 실행 후 자동 생성됩니다. 「✨ AI 종합 분석」으로 다시 생성할 수 있습니다.'),
                            React_.createElement('div', { className: 'note', style: { marginTop: 13 } },
                                React_.createElement('b', null, '관리 목표(보장 아님):'), ' 순위는 경쟁·거리·알고리즘에 따라 변동하므로 관리기준으로 표기합니다. 저장·블로그·소식 등 인기도 지표를 꾸준히 보강하는 것이 상위 방어의 핵심입니다.'))))
            )
        );
    };

    // ==================== 최종 렌더 ====================
    // 스토어(AnalysisResults)와 동일한 보고서 골격: report-shell(좌측 목차) + report-main(본문).
    // ⚠️ place-analysis 클래스는 report-main 「자기 자신」에도 붙인다 — ReportCapture 가 report-main
    //    만 복제해 내보내므로, 조상에만 있으면 전달본에서 .place-analysis 스코프 CSS 가 전부 죽는다.
    return (
        React_.createElement('div', { className: 'place-analysis' },
            React_.createElement('div', { className: 'pa-wrap' },
                renderInput(),
                !result && React_.createElement('div', { className: 'card', style: { textAlign: 'center', color: '#94a3b8', padding: '34px 20px' } },
                    React_.createElement('div', { style: { fontSize: 30, marginBottom: 8 } }, '📍'),
                    React_.createElement('div', { style: { fontSize: 14, fontWeight: 700, color: '#64748b' } }, '업체명·키워드·플레이스 검색결과 캡처를 입력하고 「분석 실행」을 눌러주세요.'),
                    React_.createElement('div', { style: { fontSize: 12, marginTop: 6 } }, '오프라인·지역 업종(카페·식당·병원·미용 등)의 플레이스 상위노출 경쟁력을 진단합니다.'))),
            result && React_.createElement('div', { className: 'report-shell' },
                /* 좌측 고정 목차 (와이드 화면 전용) — 스토어와 동일 마크업 */
                React_.createElement('nav', { className: 'report-toc' },
                    React_.createElement('div', { className: 'report-toc-title' }, '목차'),
                    TOC_SECTIONS.map(function(s) {
                        return React_.createElement('a', { key: s.id, className: 'report-toc-link', onClick: function() { scrollToSec(s.id); } },
                            React_.createElement('span', { className: 'report-toc-n' }, s.icon),
                            s.label);
                    }),
                    React_.createElement('div', { className: 'report-toc-legend' },
                        React_.createElement('div', null, React_.createElement('b', { className: 'badge b-ok' }, '✅ 실측'), ' 캡처 검색결과 실제값'),
                        React_.createElement('div', null, React_.createElement('b', { className: 'badge b-est' }, '≈ 추정'), ' 계산·근거기반'),
                        React_.createElement('div', null, React_.createElement('b', { className: 'badge b-ai' }, 'AI'), ' AI 생성'))),
                /* 본문 — 이후 모든 섹션이 report-main 의 자식(내보내기 캡처 범위) */
                React_.createElement('div', { className: 'report-main place-analysis' },
                    renderCover(),
                    renderSec1(),
                    renderSec2(),
                    renderSec3(),
                    renderSec4(),
                    renderSaveCard(),
                    renderReportSection()))
        )
    );
};
