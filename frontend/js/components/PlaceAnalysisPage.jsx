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
    var _ind = useState('');          var industry = _ind[0], setIndustry = _ind[1];

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
    // ⚠️ 지표 배지는 **서버가 알려주는 실제 출처**(result.metric_source)로 찍는다.
    //    종전엔 이 목록으로 하드코딩해, 값이 없어 기본값(적합도 50·리뷰키워드 55…)이 들어간
    //    지표에도 「측정」이 붙어 캡처 실패가 실측처럼 보였다(2026-08-11 대표 보고서 실사례).
    //    metric_source 를 안 주는 구 서버에서는 이 목록으로 폴백(무회귀).
    var MEASURED = { rank: 1, visitor_review: 1, blog_review: 1, relevance: 1, review_keyword: 1, photo: 1 };
    var SRC_BADGE = { measured: { t: '측정', c: 'meas' }, input: { t: '입력', c: 'inp' }, "default": { t: '미확인', c: 'unk' } };
    var srcOf = function(k) {
        var ms = (result && result.metric_source) || null;
        if (ms && ms[k]) return ms[k];
        return MEASURED[k] ? 'measured' : 'input';
    };
    // 맞춤제안서 #catPlace 와 **같은 13종** — 값이 같아야 같은 상권(소상공인365 소분류)이 잡힌다.
    var INDUSTRY_OPTIONS = ['음식점', '카페·디저트', '베이커리·제과', '분식', '주점·바', '미용·뷰티',
        '네일·에스테틱', '병원·의원', '약국·건강', '헬스·피트니스·필라테스', '학원·교육', '반려동물', '숙박·펜션'];
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
            target_name: businessName.trim(), place_html: html, place: suppPayload(),
            industry: industry   // 동네 상권(소상공인365) 매칭 — 미선택 시 상권 카드만 생략
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
                        // 업종 — 소상공인365 동네 상권(점포당 매출·업소수·벤치마크) 매칭키.
                        // 맞춤제안서와 **같은 13종 목록**을 쓴다(같은 값이어야 같은 상권이 잡힌다).
                        React_.createElement('div', { className: 'field' },
                            React_.createElement('label', null, '업종 ',
                                React_.createElement('span', { style: { color: '#94a3b8', fontWeight: 400 } }, '(선택 — 동네 상권 분석용)')),
                            React_.createElement('select', { className: 'inp' + (industry ? ' filled' : ''), value: industry,
                                onChange: function(e) { setIndustry(e.target.value); } },
                                React_.createElement('option', { value: '' }, '오프라인 업종 선택 (상권분석 가능 업종)'),
                                INDUSTRY_OPTIONS.map(function(o) {
                                    return React_.createElement('option', { key: o, value: o }, o);
                                }))),
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
    // 스토어 보고서와 같은 6섹션 골격(2026-08-11 고도화) — 「대등하게」 지시.
    var TOC_SECTIONS = [
        { id: 'sec-place-score', icon: '📋', label: '종합 요약' },
        { id: 'sec-place-market', icon: '📊', label: '시장·수요 진단' },
        { id: 'sec-place-comp', icon: '⚔️', label: '경쟁 진단' },
        { id: 'sec-place-kw', icon: '📍', label: '내 업체 현황' },
        { id: 'sec-place-opp', icon: '💎', label: '기회 발굴' },
        { id: 'sec-ai-feedback', icon: '🧭', label: '전략·결론' },
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

    // ==================== 표기 유틸 ====================
    // ⚠️ 값이 없으면 **숫자를 만들지 않는다** — 「미확인」으로 비운다(가짜 0 금지).
    var UNK = React_.createElement('span', { className: 'unkv' }, '미확인');
    var manwon = function(won) {
        if (won == null || isNaN(won)) return null;
        return Math.round(Number(won) / 10000).toLocaleString() + '만원';
    };
    var pctStr = function(a, b) {
        if (!a || !b) return null;
        var r = Math.round((a - b) / b * 100);
        return (r >= 0 ? '+' : '') + r + '%';
    };

    // ── 캡처 판독 경고 ──
    // 「점수가 낮은 것」과 「입력이 빈 것」은 완전히 다른 이야기다. 판독이 안 됐으면
    // 점수 위에 그 사실부터 알린다(no-export: 광고주 전달본에는 나가지 않는다).
    var renderCaptureWarn = function() {
        var cap = result.capture || {};
        if (!cap.warning) return null;
        return React_.createElement('div', { className: 'capwarn no-export' },
            React_.createElement('span', { className: 'ci' }, '⚠️'),
            React_.createElement('div', null,
                React_.createElement('b', null, cap.ok ? '내 업체를 찾지 못했습니다' : '검색결과를 읽지 못했습니다'),
                React_.createElement('div', { className: 'cw' }, cap.warning),
                React_.createElement('div', { className: 'cm' },
                    '판독된 업체 ', React_.createElement('b', null, cap.organic || 0), '곳',
                    (result.default_metrics && result.default_metrics.length)
                        ? React_.createElement(React_.Fragment, null, ' · 값이 없어 기본값으로 채운 지표 ',
                            React_.createElement('b', null, result.default_metrics.length), '개')
                        : null)));
    };

    // ── §1 종합 요약 — 광고주가 가장 먼저 보는 네 숫자 ──
    var renderKpis = function() {
        var m = result.market || {};
        var sb = m.sbiz || null;
        var sc = result.scores || {};
        var vol = m.volume;
        var rankTxt = (result.rank_state === '노출' && result.rank) ? (result.rank + '위')
            : (result.rank_state === '미노출' ? '순위 밖' : null);
        var cells = [
            { k: '월 검색량', v: (vol != null ? vol.toLocaleString() + '회' : null),
              s: (m.baseVolume != null && m.baseKeyword)
                    ? ('전체 시장 ‘' + m.baseKeyword + '’ ' + m.baseVolume.toLocaleString() + '회')
                    : ('‘' + (m.keyword || result.keyword || '') + '’ 기준'),
              hint: '검색광고 실측' },
            { k: '현재 노출 순위', v: rankTxt,
              s: (result.rank_state === '미확인' ? '캡처 재시도 필요' : ('‘' + (result.keyword || '') + '’ 오가닉 기준')),
              hint: '광고 제외' },
            { k: '동네 상권 점포당', v: (sb && sb.sales) ? manwon(sb.sales.avgAmt) : null,
              s: (sb && sb.sales && sb.sales.guAvgAmt)
                    ? ('시군구 평균 대비 ' + (pctStr(sb.sales.avgAmt, sb.sales.guAvgAmt) || '-'))
                    : '업종을 고르면 표시됩니다',
              hint: '소상공인365' },
            { k: '종합 경쟁력', v: (sc.total != null ? (sc.total + '/100') : null),
              s: '등급 ' + gradeOf(sc.total || 0), hint: '10지표 가중' }
        ];
        return React_.createElement('div', { className: 'card' },
            React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '🎯'), '한눈에 보기 ',
                React_.createElement('span', { className: 'badge b-ok' }, '✅ 실측')),
            React_.createElement('div', { className: 'rt-desc' },
                (result.business_name || businessName || '이 업체'), ' · ',
                (result.region || region || '지역 미지정'), (industry ? (' · ' + industry) : ''),
                ' 기준으로 모은 네 숫자입니다. 값이 없는 칸은 지어내지 않고 「미확인」으로 둡니다.'),
            React_.createElement('div', { className: 'kpi4' },
                cells.map(function(c, i) {
                    return React_.createElement('div', { key: i, className: 'kpi' + (c.v ? '' : ' empty') },
                        React_.createElement('div', { className: 'kk' }, c.k,
                            React_.createElement('span', { className: 'kh' }, c.hint)),
                        React_.createElement('div', { className: 'kv' }, c.v || UNK),
                        React_.createElement('div', { className: 'ks' }, c.s));
                })));
    };

    var renderSec1 = function() {
        var sc = result.scores || {};
        var labels = result.labels || {};
        var total = sc.total || 0;
        var col = scoreCol(total);
        // 강·약점 도출
        var arr = METRIC_ORDER.map(function(k) { return { k: k, label: labels[k] || k, s: sc[k] || 0 }; });
        var strong = arr.filter(function(x) { return x.s >= 68; }).sort(function(a, b) { return b.s - a.s; }).slice(0, 3).map(function(x) { return x.label; });
        var weak = arr.filter(function(x) { return x.s < 50; }).sort(function(a, b) { return a.s - b.s; }).slice(0, 3).map(function(x) { return x.label; });
        return (
            React_.createElement(React_.Fragment, null,
                React_.createElement(window.SectionDivider, { label: '1. 종합 요약', icon: '📋', color: '#3b82f6', sub: '광고주가 가장 먼저 보는 숫자 · 종합 경쟁력 · 강·약점' }),
                React_.createElement('section', { id: 'sec-place-score', className: 'section' },
                    React_.createElement('div', { className: 'container' },
                renderCaptureWarn(),
                renderKpis(),
                React_.createElement('div', { className: 'card', style: { marginTop: 14 } },
                    React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '🏅'), '플레이스 종합 경쟁력 ',
                        React_.createElement('span', { className: 'badge b-est' }, '≈ 가중')),
                    React_.createElement('div', { className: 'rt-desc' }, '10개 지표를 0~100점으로 채점하고 가중치(합 1.00)로 종합 점수를 산출합니다. 스토어 분석과 동일한 엔진 구조 — 지표·프리셋만 플레이스로 교체. 지표별 상세는 「4. 내 업체 현황」에 있습니다.'),
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
                    (result.default_metrics && result.default_metrics.length)
                        ? React_.createElement('div', { className: 'note est', style: { marginTop: 14 } },
                            React_.createElement('b', null, '참고:'), ' 값이 확인되지 않아 기본값으로 채운 지표가 ',
                            React_.createElement('b', null, result.default_metrics.length), '개 있습니다. 그만큼 종합 점수는 ',
                            React_.createElement('b', null, '참고치'), '입니다 — 「4. 내 업체 현황」에서 「미확인」 표시된 지표를 채우면 실제 점수가 나옵니다.')
                        : null)))
            )
        );
    };

    // ── §2 시장·수요 진단 ──
    var renderTrendChart = function(tr) {
        var ms = (tr && tr.months) || [];
        if (ms.length < 3) return null;
        var W = 620, H = 90, P = 4;
        var vals = ms.map(function(m) { return m.ratio; });
        var mx = Math.max.apply(null, vals), mn = Math.min.apply(null, vals);
        var span = (mx - mn) || 1;
        var pts = ms.map(function(m, i) {
            var x = P + (W - P * 2) * (ms.length > 1 ? i / (ms.length - 1) : 0);
            var y = P + (H - P * 2) * (1 - (m.ratio - mn) / span);
            return Math.round(x) + ',' + Math.round(y);
        }).join(' ');
        return React_.createElement('div', { className: 'trendbox' },
            React_.createElement('svg', { viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none',
                style: { width: '100%', height: 90, display: 'block' } },
                React_.createElement('polyline', { points: pts, fill: 'none', stroke: '#0ea5e9',
                    strokeWidth: 2.5, strokeLinejoin: 'round', strokeLinecap: 'round' })),
            React_.createElement('div', { className: 'tlabels' },
                ms.map(function(m, i) {
                    return React_.createElement('span', { key: i }, (i === 0 || i === ms.length - 1 || i % 3 === 0) ? m.label : '');
                })));
    };

    var renderSec2Market = function() {
        var m = result.market || {};
        var tr = m.trend || null;
        var sb = m.sbiz || null;
        var hasAny = (m.volume != null) || tr || sb;
        return (
            React_.createElement(React_.Fragment, null,
                React_.createElement(window.SectionDivider, { label: '2. 시장·수요 진단', icon: '📊', color: '#0ea5e9', sub: '이 동네에 손님이 얼마나 있나 — 검색 수요 · 계절성 · 상권 규모' }),
                React_.createElement('section', { id: 'sec-place-market', className: 'section' },
                    React_.createElement('div', { className: 'container' },
                !hasAny
                    ? React_.createElement('div', { className: 'card' },
                        React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '📊'), '시장·수요'),
                        React_.createElement('div', { className: 'note est', style: { marginTop: 12 } },
                            '검색량·상권 데이터를 불러오지 못했습니다. ', React_.createElement('b', null, '업종'), '을 선택하고 다시 분석하면 동네 상권이 함께 나옵니다.'))
                    : null,
                // 검색 수요
                (m.volume != null || tr)
                    ? React_.createElement('div', { className: 'card' },
                        React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '🔍'), '검색 수요 ',
                            React_.createElement('span', { className: 'badge b-ok' }, '✅ 실측')),
                        React_.createElement('div', { className: 'rt-desc' },
                            '지역 키워드는 검색량이 원래 작습니다. 그 숫자만으로는 시장 크기를 알 수 없어 ',
                            React_.createElement('b', null, '지역을 뗀 원 키워드'), ' 검색량을 함께 봅니다.'),
                        React_.createElement('div', { className: 'grid3' },
                            React_.createElement('div', { className: 'ratecard p' },
                                React_.createElement('div', { className: 'v' }, m.volume != null ? m.volume.toLocaleString() : '—'),
                                React_.createElement('div', { className: 'k' }, '‘' + (m.keyword || '') + '’ 월 검색량')),
                            React_.createElement('div', { className: 'ratecard g' },
                                React_.createElement('div', { className: 'v' }, m.baseVolume != null ? m.baseVolume.toLocaleString() : '—'),
                                React_.createElement('div', { className: 'k' }, '‘' + (m.baseKeyword || '') + '’ 전체 시장')),
                            React_.createElement('div', { className: 'ratecard' },
                                React_.createElement('div', { className: 'v', style: { fontSize: 20 } }, m.compIdx || '—'),
                                React_.createElement('div', { className: 'k' }, '검색광고 경쟁 정도'))),
                        tr ? React_.createElement('div', { className: 'subcard' },
                                React_.createElement('div', { className: 'h' },
                                    React_.createElement('span', { className: 't' }, '📈 최근 12개월 검색 추이'),
                                    React_.createElement('span', { className: 'badge b-ok', style: { marginLeft: 6 } }, '✅ 데이터랩')),
                                renderTrendChart(tr),
                                React_.createElement('div', { className: 'trendfacts' },
                                    tr.peakMonth ? React_.createElement('span', null, React_.createElement('b', null, '성수기'), ' ', tr.peakMonth) : null,
                                    tr.lowMonth ? React_.createElement('span', null, React_.createElement('b', null, '비수기'), ' ', tr.lowMonth) : null,
                                    tr.peakWeekday ? React_.createElement('span', null, React_.createElement('b', null, '요일 피크'), ' ', tr.peakWeekday + '요일') : null,
                                    (tr.gender && tr.gender.top) ? React_.createElement('span', null, React_.createElement('b', null, '주 이용층'), ' ',
                                        (tr.topAge ? (tr.topAge + ' ') : '') + tr.gender.top) : null,
                                    (tr.yoyRate != null) ? React_.createElement('span', null, React_.createElement('b', null, '전년 동월 대비'), ' ',
                                        (tr.yoyRate >= 0 ? '+' : '') + tr.yoyRate + '%') : null),
                                React_.createElement('div', { className: 'chartfoot' },
                                    '데이터랩 통합검색어 트렌드 · ‘', tr.keyword, '’ 기준(지역을 뗀 업종 키워드 — 지역 키워드는 표본이 작아 계절성이 노이즈가 됩니다). 값은 기간 내 상대 지수입니다.'))
                            : null)
                    : null,
                // 동네 상권
                sb ? React_.createElement('div', { className: 'card', style: { marginTop: 14 } },
                        React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '🏙'), '우리 동네 상권 ',
                            React_.createElement('span', { className: 'badge b-ok' }, '✅ 소상공인365')),
                        React_.createElement('div', { className: 'rt-desc' },
                            (sb.district && sb.district.admiNm ? sb.district.admiNm : (result.region || region)),
                            (sb.industryNm ? (' · ' + sb.industryNm + ' 기준') : ''),
                            (sb.baseYm ? (' · ' + String(sb.baseYm).slice(0, 4) + '.' + String(sb.baseYm).slice(4, 6) + ' 기준') : ''),
                            ' — 이 금액은 ', React_.createElement('b', null, '상권 평균'), '이지 이 업체의 매출이 아닙니다.'),
                        React_.createElement('div', { className: 'grid3' },
                            React_.createElement('div', { className: 'ratecard p' },
                                React_.createElement('div', { className: 'v', style: { fontSize: 22 } }, (sb.sales && manwon(sb.sales.avgAmt)) || '—'),
                                React_.createElement('div', { className: 'k' }, '점포당 월평균')),
                            React_.createElement('div', { className: 'ratecard g' },
                                React_.createElement('div', { className: 'v', style: { fontSize: 22 } },
                                    (sb.sales && sb.sales.guAvgAmt) ? (pctStr(sb.sales.avgAmt, sb.sales.guAvgAmt) || '—') : '—'),
                                React_.createElement('div', { className: 'k' }, '시군구 평균 대비')),
                            React_.createElement('div', { className: 'ratecard' },
                                React_.createElement('div', { className: 'v' }, (sb.shops && sb.shops.count != null) ? sb.shops.count : '—'),
                                React_.createElement('div', { className: 'k' }, '동종 업소 수'))),
                        (sb.major && sb.major.avgAmt)
                            ? React_.createElement('div', { className: 'note ok' },
                                '🏙 이 동네 ', React_.createElement('b', null, sb.major.label || '업종'), ' 전체로 보면 ',
                                React_.createElement('b', null, (sb.major.shopCnt || 0).toLocaleString()), '곳이 영업 중이고, 점포당 월평균은 ',
                                React_.createElement('b', null, manwon(sb.major.avgAmt)), '입니다',
                                sb.major.partial ? ' (일부 세부업종 집계 생략)' : '', '.')
                            : null,
                        React_.createElement('div', { className: 'note est', style: { marginTop: 10 } },
                            React_.createElement('b', null, '시간대·요일 유동인구는 넣지 않습니다'), ' — 공공 API 경로가 막혀 있어(20개 조합 실측 확인) 값을 만들 수 없습니다. 없는 데이터는 비워 둡니다.'))
                    : null)))
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
                React_.createElement(window.SectionDivider, { label: '4. 내 업체 현황', icon: '📍', color: '#059669', sub: '지금 어디에 서 있나 — 노출 순위 · 리뷰 현황 · 최적화 10지표' }),
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
                    React_.createElement(window.PlaceRankChart, { series: chartSeries, keyword: chartKeyword || selectedKw, days: chartDays, businessName: businessName, onDays: onChartDays })),
                renderReviewCard(),
                renderMetricsCard())))
        );
    };

    // ── §4-b 리뷰 현황 (실측 + 상위권 격차) ──
    var renderReviewCard = function() {
        var g = (result.market || {}).reviewGap;
        if (!g || (!g.visitor && !g.blog && !g.saves)) return null;
        var rows = [];
        if (g.visitor) rows.push({ k: '방문자(영수증) 리뷰', d: g.visitor });
        if (g.blog) rows.push({ k: '블로그 리뷰', d: g.blog });
        if (g.saves) rows.push({ k: '저장수(즐겨찾기)', d: g.saves });
        return React_.createElement('div', { className: 'card', style: { marginTop: 14 } },
            React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '💬'), '리뷰 현황 ',
                React_.createElement('span', { className: 'badge b-ok' }, '✅ 실측')),
            React_.createElement('div', { className: 'rt-desc' },
                '캡처에서 읽은 내 업체 값과 ', React_.createElement('b', null, '상위 노출 ' + (g.topCount || 0) + '곳의 중앙값'),
                '을 나란히 둡니다. 상위권 중앙값은 「이 키워드에서 노출되려면 대략 이 정도」의 기준선입니다.'),
            React_.createElement('div', { className: 'twrap' },
                React_.createElement('table', null,
                    React_.createElement('thead', null, React_.createElement('tr', null,
                        React_.createElement('th', null, '지표'),
                        React_.createElement('th', { className: 'n' }, '내 업체'),
                        React_.createElement('th', { className: 'n' }, '상위권 중앙값'),
                        React_.createElement('th', { className: 'n' }, '격차'))),
                    React_.createElement('tbody', null,
                        rows.map(function(r, i) {
                            var gp = r.d.gap;
                            return React_.createElement('tr', { key: i },
                                React_.createElement('td', null, r.k),
                                React_.createElement('td', { className: 'n' }, r.d.mine != null ? fmtN(r.d.mine) : UNK),
                                React_.createElement('td', { className: 'n' }, r.d.topMedian != null ? fmtN(r.d.topMedian) : '—'),
                                React_.createElement('td', { className: 'n', style: { fontWeight: 800, color: (gp == null ? '#94a3b8' : (gp >= 0 ? '#059669' : '#dc2626')) } },
                                    gp == null ? '—' : ((gp >= 0 ? '+' : '') + fmtN(gp))));
                        })))),
            // ⚠️ 광고주 전달본에 들어가는 카드다 — 여기 문구는 「사장님이 읽을 말」이어야 한다.
            //    직원에게 하는 지시(「보완 지표에 입력하세요」)는 no-export 영역에만 둔다.
            React_.createElement('div', { className: 'note est', style: { marginTop: 13 } },
                React_.createElement('b', null, '저장수(즐겨찾기)'), '는 검색결과 화면에 표시되지 않아 자동으로 읽히지 않습니다 — 담당자가 확인한 값이 있을 때만 표기됩니다.'),
            React_.createElement('div', { className: 'note no-export', style: { marginTop: 10 } },
                React_.createElement('b', null, '담당자 안내:'), ' 저장수는 「4. 내 업체 현황」 아래 ',
                React_.createElement('b', null, '담당자 보완 지표'), '에 입력하면 경쟁력 점수에 반영됩니다.'));
    };

    // ── §4-c 최적화 10지표 + 보완 입력 ──
    var renderMetricsCard = function() {
        var sc = result.scores || {};
        var labels = result.labels || {};
        var weights = result.weights || {};
        return React_.createElement('div', { className: 'card', style: { marginTop: 14 } },
            React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '📊'), '플레이스 최적화 10지표 ',
                React_.createElement('span', { className: 'badge b-est' }, '≈ 가중')),
            React_.createElement('div', { className: 'rt-desc' },
                '지표마다 값의 출처를 표시합니다 — ', React_.createElement('b', null, '측정'), '은 캡처에서 읽은 값, ',
                React_.createElement('b', null, '입력'), '은 담당자가 채운 값, ', React_.createElement('b', null, '미확인'),
                '은 값이 없어 기본값이 들어간 자리입니다(그 지표 점수는 참고치).'),
            React_.createElement('div', { className: 'metrics' },
                METRIC_ORDER.map(function(k) {
                    var v = sc[k] || 0;
                    var src = srcOf(k);
                    var bd = SRC_BADGE[src] || SRC_BADGE.input;
                    return React_.createElement('div', { key: k, className: 'scorebar' + (v < 50 ? ' low' : '') + (src === 'default' ? ' unknown' : '') },
                        React_.createElement('div', { className: 'lbl' },
                            React_.createElement('span', { className: 'nm' }, labels[k] || k,
                                React_.createElement('span', { className: 'w' }, (weights[k] != null ? weights[k].toFixed(2) : '')),
                                React_.createElement('span', { className: 'mk ' + bd.c }, bd.t)),
                            React_.createElement('span', { className: 'sc' }, v)),
                        React_.createElement('div', { className: 'track' }, React_.createElement('i', { style: { width: v + '%' } })));
                })),
            renderSuppEditor(),
            // 「재점수화」는 직원 조작 안내라 전달본에서 제외(no-export). 배지 뜻 설명은 위 rt-desc 가 담당.
            React_.createElement('div', { className: 'note no-export', style: { marginTop: 14 } },
                React_.createElement('b', null, '측정 vs 입력:'), ' 순위·리뷰·적합도는 캡처에서 ', React_.createElement('b', null, '자동 측정'),
                ', 저장수·예약·소식·업체정보는 담당자가 ', React_.createElement('b', null, '보완 입력'), '(하이브리드). 보완 지표를 채우고 ',
                React_.createElement('b', null, '재점수화'), '하면 점수에 반영됩니다.'));
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
                React_.createElement(window.SectionDivider, { label: '3. 경쟁 진단', icon: '⚔️', color: '#ef4444', sub: "누구와 싸우고 있나 — '" + (result.keyword || '') + "' 상위 노출 업체 · 상권 경쟁 밀도" }),
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
                        React_.createElement('b', null, '격차 진단 ≈ 추정:'), ' 방문자·블로그 리뷰가 상위권과 벌어질수록 인기도(순위) 병목이 큽니다. 저장수는 캡처로 인식되지 않으므로 「4. 내 업체 현황」의 보완 지표에서 입력해 경쟁력에 반영하세요.')),
                renderDensityCard())))
        );
    };

    // ── §3-b 경쟁 밀도 · 광고 경쟁 ──
    var renderDensityCard = function() {
        var m = result.market || {};
        var sb = m.sbiz || null;
        var shops = (sb && sb.shops && sb.shops.count != null) ? sb.shops.count : null;
        var ad = m.adDepth;
        if (shops == null && !ad) return null;
        return React_.createElement('div', { className: 'card', style: { marginTop: 14 } },
            React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '🏘'), '경쟁 밀도 ',
                React_.createElement('span', { className: 'badge b-ok' }, '✅ 실측')),
            React_.createElement('div', { className: 'rt-desc' },
                '검색결과 안의 경쟁(위 표)과 별개로, ', React_.createElement('b', null, '동네에 같은 업종이 몇 곳인지'), '가 상위 노출 난이도를 좌우합니다.'),
            React_.createElement('div', { className: 'two' },
                shops != null
                    ? React_.createElement('div', { className: 'mini' },
                        React_.createElement('h4', null, '🏘 상권 내 동종 업소'),
                        React_.createElement('div', { style: { fontSize: 26, fontWeight: 900, letterSpacing: '-1px' } }, shops.toLocaleString(), '곳'),
                        React_.createElement('div', { style: { fontSize: 12, color: 'var(--pa-sub)', marginTop: 4 } },
                            (sb.district && sb.district.admiNm ? sb.district.admiNm : (result.region || region)),
                            (sb.industryNm ? (' · ' + sb.industryNm) : ''),
                            (sb.shops && sb.shops.momRate != null) ? (' · 전월 대비 ' + (sb.shops.momRate > 0 ? '+' : '') + sb.shops.momRate + '%') : ''))
                    : null,
                ad
                    ? React_.createElement('div', { className: 'mini' },
                        React_.createElement('h4', null, '📢 검색광고 경쟁'),
                        React_.createElement('div', { style: { fontSize: 26, fontWeight: 900, letterSpacing: '-1px' } }, ad, '개'),
                        React_.createElement('div', { style: { fontSize: 12, color: 'var(--pa-sub)', marginTop: 4 } },
                            '‘', (m.keyword || ''), '’ 월평균 광고 개수', (m.compIdx ? (' · 경쟁 ' + m.compIdx) : '')))
                    : null),
            ad
                ? React_.createElement('div', { className: 'note est', style: { marginTop: 12 } },
                    React_.createElement('b', null, '⚠️ 다른 축입니다:'), ' 이 숫자는 네이버 ',
                    React_.createElement('b', null, '검색광고(파워링크)'), ' 기준이고, 우리가 추적하는 노출 순위는 ',
                    React_.createElement('b', null, '플레이스(지도) 오가닉'), ' 기준입니다. 광고를 많이 하는 키워드라는 뜻이지 플레이스 순위가 그만큼 밀린다는 뜻이 아닙니다.')
                : null);
    };

    // ── §5 기회 발굴 — 연관 키워드 · 지역 황금 키워드 ──
    var renderSec5Opp = function() {
        var m = result.market || {};
        var rel = m.related || [];
        var gold = m.golden || [];
        if (!rel.length && !gold.length) return null;
        return (
            React_.createElement(React_.Fragment, null,
                React_.createElement(window.SectionDivider, { label: '5. 기회 발굴', icon: '💎', color: '#7c3aed', sub: '어디를 파고들면 되나 — 지역 황금 키워드 · 연관 키워드' }),
                React_.createElement('section', { id: 'sec-place-opp', className: 'section' },
                    React_.createElement('div', { className: 'container' },
                gold.length
                    ? React_.createElement('div', { className: 'card' },
                        React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '💎'), '지역 황금 키워드 ',
                            React_.createElement('span', { className: 'badge b-est' }, '≈ 계산')),
                        React_.createElement('div', { className: 'rt-desc' },
                            React_.createElement('b', null, '검색량은 있는데 아직 순위가 없는'), ' 키워드를 먼저 제시합니다. 이미 노출 중인 키워드는 「지킬 것」이라 여기서 뺐습니다. 그대로 ',
                            React_.createElement('b', null, '플레이스 추적'), '에 등록하면 다음 날부터 순위 기록이 쌓입니다.'),
                        React_.createElement('div', { className: 'twrap' },
                            React_.createElement('table', null,
                                React_.createElement('thead', null, React_.createElement('tr', null,
                                    React_.createElement('th', null, '키워드'),
                                    React_.createElement('th', { className: 'n' }, '월 검색량'),
                                    React_.createElement('th', null, '경쟁'),
                                    React_.createElement('th', null, '현재'),
                                    React_.createElement('th', null, '판단'))),
                                React_.createElement('tbody', null,
                                    gold.map(function(r, i) {
                                        return React_.createElement('tr', { key: i },
                                            React_.createElement('td', { style: { fontWeight: 700 } }, r.keyword),
                                            React_.createElement('td', { className: 'n' }, (r.volume || 0).toLocaleString()),
                                            React_.createElement('td', null, r.compIdx || '—'),
                                            React_.createElement('td', null, r.state || '미확인'),
                                            React_.createElement('td', null,
                                                React_.createElement('span', { className: 'ps ' + (r.priority === '우선 공략' ? 'ps-g' : 'ps-n'),
                                                    style: { fontSize: 11, padding: '3px 9px' } }, r.priority)));
                                    })))))
                    : null,
                rel.length
                    ? React_.createElement('div', { className: 'card', style: { marginTop: gold.length ? 14 : 0 } },
                        React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '🔗'), '연관 키워드 ',
                            React_.createElement('span', { className: 'badge b-ok' }, '✅ 실측')),
                        React_.createElement('div', { className: 'rt-desc' },
                            '‘', (m.baseKeyword || ''), '’ 에서 파생된 연관 키워드와, 여기에 지역을 결합한 실제 공략 키워드입니다. 결합 검색량은 상위 5개만 조회합니다(호출 절약).'),
                        React_.createElement('div', { className: 'twrap' },
                            React_.createElement('table', null,
                                React_.createElement('thead', null, React_.createElement('tr', null,
                                    React_.createElement('th', null, '연관 키워드'),
                                    React_.createElement('th', { className: 'n' }, '전체 검색량'),
                                    React_.createElement('th', null, '지역 결합'),
                                    React_.createElement('th', { className: 'n' }, '결합 검색량'),
                                    React_.createElement('th', null, '내 순위'))),
                                React_.createElement('tbody', null,
                                    rel.map(function(r, i) {
                                        return React_.createElement('tr', { key: i },
                                            React_.createElement('td', null, r.keyword),
                                            React_.createElement('td', { className: 'n' }, r.volume != null ? r.volume.toLocaleString() : '—'),
                                            React_.createElement('td', { style: { fontWeight: 700 } }, r.combined),
                                            React_.createElement('td', { className: 'n' }, r.combinedVolume != null ? r.combinedVolume.toLocaleString() : '—'),
                                            React_.createElement('td', null, r.rank ? (r.rank + '위') : (r.state || '미확인')));
                                    })))))
                    : null)))
        );
    };

    // ── §6-a 노출 개선 시뮬레이션 · 90일 로드맵 ──
    var renderImprove = function() {
        var im = result.improve || {};
        var steps = im.steps || [];
        var road = im.roadmap || [];
        if (!steps.length && !road.length) return null;
        var maxT = Math.max.apply(null, steps.map(function(s) { return s.total; }).concat([1]));
        return React_.createElement('div', { className: 'card', style: { marginBottom: 14 } },
            React_.createElement('h3', { className: 'rt-h3' }, React_.createElement('span', { className: 'rt-hic' }, '🚀'), '노출 개선 시뮬레이션 ',
                React_.createElement('span', { className: 'badge b-est' }, '≈ 계산')),
            React_.createElement('div', { className: 'rt-desc' },
                '지금 낮은 지표를 목표선(', (im.target || 75), '점)까지 올리면 종합 경쟁력이 얼마가 되는지 가중치로 역산한 값입니다. ',
                React_.createElement('b', null, '순위 보장이 아니라 관리 목표'), '입니다 — 순위는 경쟁·거리·알고리즘에 따라 변동합니다.'),
            steps.length ? React_.createElement('div', { className: 'simrows' },
                steps.map(function(s, i) {
                    return React_.createElement('div', { key: i, className: 'simrow' + (i === 0 ? ' now' : '') },
                        React_.createElement('div', { className: 'sl' }, s.label),
                        React_.createElement('div', { className: 'sb' },
                            React_.createElement('i', { style: { width: Math.round(s.total / maxT * 100) + '%' } })),
                        React_.createElement('div', { className: 'sv' }, s.total, React_.createElement('small', null, '/100'),
                            s.delta ? React_.createElement('span', { className: 'sd' }, '+' + s.delta) : null),
                        React_.createElement('div', { className: 'sf' }, (s.focus || []).join(' · ')));
                })) : null,
            road.length ? React_.createElement('div', { className: 'subcard' },
                React_.createElement('div', { className: 'h' }, React_.createElement('span', { className: 't' }, '🧭 90일 실행 로드맵')),
                road.map(function(p, i) {
                    return React_.createElement('div', { key: i, className: 'rmrow' },
                        React_.createElement('span', { className: 'ph' }, p.phase),
                        React_.createElement('div', { className: 'it' },
                            (p.items || []).map(function(t, j) {
                                return React_.createElement('div', { key: j }, '· ', t);
                            })));
                })) : null);
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
                React_.createElement(window.SectionDivider, { label: '6. 전략·결론', icon: '🧭', color: '#1e293b', sub: '그래서 무엇부터 — 개선 시뮬레이션 · 90일 로드맵 · AI 종합 진단' }),
                React_.createElement('section', { id: 'sec-ai-feedback', className: 'section' },
                    React_.createElement('span', { className: 'ai-state', style: { display: 'none' },
                        'data-state': aiLoading ? 'loading' : (ai ? 'done' : 'idle') }),
                    React_.createElement('div', { className: 'container' },
                        renderImprove(),
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
                    renderSec1(),        /* 1. 종합 요약 */
                    renderSec2Market(),  /* 2. 시장·수요 진단 */
                    renderSec3(),        /* 3. 경쟁 진단 */
                    renderSec2(),        /* 4. 내 업체 현황 */
                    renderSec5Opp(),     /* 5. 기회 발굴 */
                    renderSec4(),        /* 6. 전략·결론 (개선 계획 + AI) */
                    renderSaveCard(),
                    renderReportSection()))
        )
    );
};
