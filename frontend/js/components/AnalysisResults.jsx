/* AnalysisResults — 메인 분석결과 렌더 (App.jsx에서 분리)
 * report-shell(좌측 목차 + 본문 전 섹션). App의 상태/핸들러를 props로 받음. */

/* 키워드 적합도 판정(/api/keywords/fit)에 보내는 묶음 — 화면이 이미 받아 둔 자료만 쓴다(네이버 호출 없음).
   연관어·검색어가 없으면 null(판정 없음). ⚠️ 여기 넣는 칸이 곧 「판정을 다시 받을 조건」이다 —
   화면은 이 묶음을 문자열로 만든 **본문 그대로**를 열쇠로 쓴다(해시로 줄이지 않는다 · 아래 훅). */
window.buildKeywordFitPayload = function(src) {
    src = src || {};
    if (!src.relatedData || !src.keyword) return null;
    var adv = src.advertiserReport || {};
    var tp = (src.analysisData && src.analysisData.targetProductInfo) || null;
    var hd = src.htmlDetail || null;
    return {
        keyword: src.keyword,
        name: src.companyName || '',
        productName: (adv.product_info && adv.product_info.product_name) || (tp && tp.product_name) || '',
        related: src.relatedData,
        advertiser: { product_info: adv.product_info || null,
                      competitor_comparison: { items: (((adv.competitor_comparison || {}).items) || []).slice(0, 80).map(function(it) { return { store_name: it.store_name, brand: it.brand }; }) } },
        analysis: { targetProductInfo: tp },
        htmlDetail: hd ? { reviewData: hd.reviewData ? { category: hd.reviewData.category, category1: hd.reviewData.category1 } : null,
                           sellerTags: hd.sellerTags || [], storeInfo: hd.storeInfo || null } : null,
        shopProducts: (src.shopProducts || []).slice(0, 80).map(function(p) { return { store_name: p.store_name || p.mallName, brand: p.brand }; })
    };
};
window.AnalysisResults = function AnalysisResults(props) {
    var advertiserLoading = props.advertiserLoading;
    var advertiserReport = props.advertiserReport;
    var analysisData = props.analysisData;
    var companyName = props.companyName;
    var currentUser = props.currentUser;
    var datalabData = props.datalabData;
    var datalabLoading = props.datalabLoading;
    var auditStatus = props.auditStatus;
    var handleNavigateToClient = props.handleNavigateToClient;
    var htmlDetailResult = props.htmlDetailResult;
    var htmlReviewData = props.htmlReviewData;
    var lastHtmlRef = props.lastHtmlRef;
    var loadProducts = props.loadProducts;
    var products = props.products;
    var rankCheckResult = props.rankCheckResult;
    var relatedData = props.relatedData;
    var scrollTo = props.scrollTo;
    var searchLoading = props.searchLoading;
    var searchedKeyword = props.searchedKeyword;
    var searchedProductUrl = props.searchedProductUrl;
    var sections = props.sections;
    var setRankCheckResult = props.setRankCheckResult;
    var shopProducts = props.shopProducts;
    var volumeData = props.volumeData;

    /* 광고주/스토어명 자동 채우기 (2026-07-27 수정)
       주의: 백엔드 store_name 은 쇼핑API 매칭·상품페이지 방문이 모두 실패하면
       'URL 슬러그'가 그대로 담긴다. 슬러그가 이메일 아이디인 업체가 있어 표지에
       'chajju2009' 처럼 찍히는 신고가 있었다(윤채은 07-27). 따라서 슬러그와 같은 값은
       '이름 미확보'로 보고, 상세 HTML에서 뽑은 실제 상호명(storeInfo)을 우선 사용한다.
       ※ 슬러그는 순위 매칭 키로 계속 쓰이므로 여기서는 '표시용'만 판단한다. */
    var _urlSlug = (function() {
        try { var m = (searchedProductUrl || '').match(/smartstore\.naver\.com\/([^\/?#]+)/); return m ? decodeURIComponent(m[1]) : ''; }
        catch (e) { return ''; }
    })();
    var _isSlug = function(v) {
        return !!v && !!_urlSlug && String(v).trim().toLowerCase() === _urlSlug.trim().toLowerCase();
    };
    var _realStoreName = (function() {
        var cands = [
            (htmlDetailResult && htmlDetailResult.storeInfo && htmlDetailResult.storeInfo.name),
            (advertiserReport && advertiserReport.product_info && advertiserReport.product_info.store_name),
            (analysisData && analysisData.targetProductInfo && analysisData.targetProductInfo.store_name),
            (analysisData && analysisData.htmlDetail && analysisData.htmlDetail.storeInfo && analysisData.htmlDetail.storeInfo.name)
        ];
        for (var i = 0; i < cands.length; i++) {
            var v = cands[i] && String(cands[i]).trim();
            if (v && !_isSlug(v)) return v;   // 슬러그와 같은 값은 이름으로 인정하지 않음
        }
        return '';
    })();
    /* 실제 이름을 못 구하면 최후에만 슬러그(빈 표지보다는 낫다) */
    var _storeName = _realStoreName || _urlSlug || '';
    var _displayCompany = companyName || _storeName;

    /* 키워드 적합도 판정(2026-11-16 · 초콜릿 판매자 제안서 사고) — 파베초콜릿 보고서·제안서에 '빼빼로'가 공략 키워드로 나갔다.
       이 화면이 이미 받아 둔 자료(연관어·상품명·카테고리·판매자 태그·1페이지 타사)를 서버에 보내
       「이 상품을 찾는 말인가」를 판정받는다(네이버 호출 없음 · 규칙은 서버 keyword_fit 한 곳 · 제안서와 같은 판정).
       ⚠️ 실패하면 조용히 종전 화면 그대로(판정 없음). 토스트를 띄우지 않으려고 api 대신 fetch 를 쓴다.
       ⚠️ 이 컴포넌트에는 early return 이 없다 — 훅을 더할 때도 return 앞에 둘 것(App.jsx #310 사고).
       ⚠️ 판정을 다시 받을지는 **서버에 보내는 본문 문자열 그대로**로 정한다(2026-11-21 고침 · 11-22 보강).
          종전엔 판매자 태그·연관어의 「개수」만 봐서, 개수가 같은 채 내용이 바뀌면(#다크초콜릿 → #밀크초콜릿 ·
          저장 보고서를 불러와 상태를 갈아 끼울 때) 옛 판정이 그대로 남았다.
          ⛔ 본문을 해시로 줄여 열쇠로 쓰지 말 것 — 길이가 같고 해시가 겹치는 다른 본문('Ab…' ↔ 'BA…')에서
             다시 묻지 않아 옛 판정이 남는다(교차검증 재현). 문자열 비교는 정확하고 충분히 싸다.
          받은 판정은 그때 보낸 본문과 함께 들고 있다가 **지금 본문과 정확히 같을 때만** 쓴다 — 다른 자료의 판정을 잠깐이라도 쓰지 않는다. */
    var _fitSt = React.useState(null);
    var _fitHd = htmlDetailResult || (analysisData && analysisData.htmlDetail) || null;
    var _fitBody = React.useMemo(function() {
        var payload = window.buildKeywordFitPayload({
            keyword: searchedKeyword, companyName: companyName, relatedData: relatedData, advertiserReport: advertiserReport,
            analysisData: analysisData, htmlDetail: _fitHd, shopProducts: shopProducts });
        return payload ? JSON.stringify({ payload: payload }) : '';
    }, [searchedKeyword, companyName, relatedData, advertiserReport, analysisData, _fitHd, shopProducts]);
    var keywordFit = (_fitSt[0] && _fitSt[0].body === _fitBody) ? _fitSt[0].data : null;
    React.useEffect(function() {
        var setFit = _fitSt[1];
        if (!_fitBody) { setFit(null); return; }
        var alive = true, body = _fitBody;
        var t = setTimeout(function() {
            try {
                fetch(API_BASE + '/keywords/fit', { method: 'POST', headers: _authHeaders({ 'Content-Type': 'application/json' }), body: body })
                    .then(function(r) { return r.ok ? r.json() : null; })
                    .then(function(j) { if (alive) setFit(j && j.success ? { body: body, data: j.data } : null); })
                    .catch(function() { if (alive) setFit(null); });
            } catch (e) { setFit(null); }
        }, 500);
        return function() { alive = false; clearTimeout(t); };
    }, [_fitBody]);

    /* 골든 키워드 카드 — 판정에서 빠진 말이면 통과한 황금 키워드로 바꾸고, 없으면 0건 안내를 띄운다. */
    var _nz = function(v) { return String(v || '').replace(/\s/g, '').toLowerCase(); };
    var _fitGolden = React.useMemo(function() {
        var g = analysisData ? analysisData.goldenKeyword : null;
        if (!keywordFit) return g;
        var passed = {};
        (keywordFit.passed || []).forEach(function(k) { passed[_nz(k)] = 1; });
        if (g && passed[_nz(g.name)]) return g;
        var list = ((relatedData && relatedData.golden_keywords) || []).filter(function(gk) { return !gk.isStoreName && passed[_nz(gk.keyword)]; });
        return list.length && window.buildGoldenKeywordInfo ? window.buildGoldenKeywordInfo(list[0], searchedKeyword) : null;
    }, [analysisData, keywordFit, relatedData, searchedKeyword]);
    /* AI 종합 분석에 넘기는 골든 키워드도 같은 것으로(판정 전에 이미 시작했으면 종전 값 — 키워드당 한 번만 부른다) */
    var _fitAnalysis = React.useMemo(function() {
        if (!analysisData || !keywordFit || _fitGolden === analysisData.goldenKeyword) return analysisData;
        return Object.assign({}, analysisData, { goldenKeyword: _fitGolden });
    }, [analysisData, keywordFit, _fitGolden]);

    /* ===== 쇼핑 1페이지 자료가 없을 때(쇼핑 순위 수집 쉼 · 2026-11-05~) — 대표 결정 「보고서 문구 — ①ⓐ ②ⓐ ③ⓐ」 =====
       ① 광고주 전달본: 빈 칸·빈 장은 빼고 맨 위에 한 줄(.export-only)  ② 점수는 「계산 불가」
       ③ 직원 화면: 이유까지 적은 안내 띠와 장마다 「이번 분석에서 빠진 칸」 한 줄(.no-export).
       자료가 있으면 아래 갈래는 전부 꺼져 지금 화면과 똑같다. */
    var marketMissing = !!(analysisData && analysisData.marketMissing);
    var relatedLookupFailed = !!(relatedData && relatedData.lookup_ok === false);
    var volumeMissing = !(volumeData && volumeData.length > 0);
    var _staffNote = function(text) {
        return React.createElement('div', { className: 'section no-export' },
            React.createElement('div', { className: 'container' },
                React.createElement('div', { style: { background: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: 10, padding: '9px 14px', fontSize: 12.5, color: '#64748b', lineHeight: 1.6 } }, text)
            )
        );
    };
    var _missingLine = function(names) {
        return _staffNote(React.createElement(React.Fragment, null,
            React.createElement('b', { style: { color: '#475569' } }, '이번 분석에서 빠진 칸: '),
            names.join(' · '),
            ' — 쇼핑 시장 자료 없음'));
    };

    return (
                React.createElement('div', { className: 'report-shell' },
                  /* 좌측 고정 목차 (와이드 화면 전용) — 분석 결과(섹션 2개 이상)가 있을 때만 표시 */
                  (sections.length > 1) && React.createElement('nav', { className: 'report-toc' },
                    React.createElement('div', { className: 'report-toc-title' }, '목차'),
                    sections.map(function(s) {
                      return React.createElement('a', { key: s.id, className: 'report-toc-link', onClick: function() { scrollTo(s.id); } },
                        React.createElement('span', { className: 'report-toc-n' }, s.icon),
                        s.label
                      );
                    }),
                    React.createElement('div', { className: 'report-toc-legend' },
                      React.createElement('div', null, React.createElement('b', { className: 'badge b-ok' }, '✅ 실측'), ' 네이버 실제값'),
                      React.createElement('div', null, React.createElement('b', { className: 'badge b-dl' }, '📊 데이터랩'), ' 쇼핑인사이트 통계'),
                      React.createElement('div', null, React.createElement('b', { className: 'badge b-est' }, '≈ 추정'), ' 계산·근거기반'),
                      React.createElement('div', null, React.createElement('b', { className: 'badge b-ai' }, 'AI'), ' AI 생성')
                    )
                  ),
                  /* 본문 시작 (이후 모든 섹션이 report-main의 자식) */
                  React.createElement('div', { className: 'report-main' },
                    /* 보고서 표지(광고주 정보) 카드 */
                    analysisData && React.createElement('div', { className: 'report-cover' },
                        React.createElement('div', { className: 'report-cover-head' },
                            React.createElement('span', { className: 'rc-ic' }, '📋'),
                            React.createElement('span', { className: 'rc-title' }, '로직 분석 보고서')
                        ),
                        React.createElement('div', { className: 'rc-grid' },
                            React.createElement('div', { className: 'rc-field' },
                                React.createElement('div', { className: 'rc-k' }, '광고주 / 스토어'),
                                React.createElement('div', { className: 'rc-v' }, _displayCompany || '-')
                            ),
                            React.createElement('div', { className: 'rc-field' },
                                React.createElement('div', { className: 'rc-k' }, '분석 키워드'),
                                React.createElement('div', { className: 'rc-v' }, searchedKeyword || '-')
                            ),
                            React.createElement('div', { className: 'rc-field' },
                                React.createElement('div', { className: 'rc-k' }, '상품 URL'),
                                React.createElement('div', { className: 'rc-v rc-url', title: searchedProductUrl || '' }, searchedProductUrl || '-')
                            ),
                            React.createElement('div', { className: 'rc-field' },
                                React.createElement('div', { className: 'rc-k' }, '분석일'),
                                React.createElement('div', { className: 'rc-v' }, new Date().toLocaleDateString('ko'))
                            )
                        )
                    ),
                    /* 배지 범례 — report-main 내부에 두어 전달본(내보내기)에도 포함되게 함
                     * (좌측 목차의 범례는 캡처 범위 밖이라 전달본에서 소실되던 문제 보완) */
                    analysisData && React.createElement('div', { className: 'report-legend' },
                        React.createElement('b', { className: 'badge b-ok' }, '✅ 실측'), ' 네이버 실제값',
                        React.createElement('span', { className: 'rl-sep' }, '·'),
                        React.createElement('b', { className: 'badge b-dl' }, '📊 데이터랩'), ' 쇼핑인사이트 통계',
                        React.createElement('span', { className: 'rl-sep' }, '·'),
                        React.createElement('b', { className: 'badge b-est' }, '≈ 추정'), ' 계산·근거 기반',
                        React.createElement('span', { className: 'rl-sep' }, '·'),
                        React.createElement('b', { className: 'badge b-ai' }, 'AI'), ' AI 생성'
                    ),
                    /* 모바일용 가로 목차 */
                    React.createElement('div', { className: 'anchor-nav-wrap' },
                        React.createElement('div', { className: 'container' },
                            React.createElement('div', { className: 'anchor-nav' },
                                sections.map(function(s) {
                                    return React.createElement('button', { key: s.id, className: 'anchor-btn', onClick: function() { scrollTo(s.id); } },
                                        React.createElement('span', { className: 'anchor-icon' }, s.icon),
                                        s.label
                                    );
                                })
                            )
                        )
                    ),
    
                /* 1페이지 진입 전략 비교 분석 (통합) — 로딩 */
                advertiserLoading && !advertiserReport && React.createElement('div', { id: 'sec-strategy', className: 'section' },
                    React.createElement('div', { className: 'container' },
                        React.createElement(LoadingSpinner, { text: '1페이지 진입 전략 분석 중... 약 10~15초 소요됩니다' })
                    )
                ),
    
                /* 대시보드 요약 — 분석 전 메인 화면에서만 표시, 특정 업체 분석 시 숨김 */
                !searchedProductUrl && React.createElement(DashboardSummary, { products: products, searchResult: relatedData }),
    
                /* [검수] 데이터 검수 상태 배너 — 항목별 실데이터 확보 현황(✓ 확보 · ↻ 재조회 중 · ✗ 실패) */
                auditStatus && auditStatus.items && auditStatus.items.length > 0 && React.createElement('div', { className: 'section fade-in no-export' },
                    React.createElement('div', { className: 'container' },
                        React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 14px', fontSize: 12.5 } },
                            React.createElement('b', { style: { color: '#334155' } },
                                auditStatus.phase === 'auditing' ? '🔍 데이터 검수 중…' : '🔍 데이터 검수'),
                            auditStatus.items.map(function(it, i) {
                                /* off = 「성공 · 빈 목록」(쇼핑 수집 쉼) — 실패가 아니라 회색 「—」 */
                                var color = it.st === 'ok' ? '#059669' : (it.st === 'retry' ? '#d97706' : ((it.st === 'wait' || it.st === 'off') ? '#94a3b8' : '#dc2626'));
                                var mark = it.st === 'ok' ? '✓' : (it.st === 'retry' ? '↻' : (it.st === 'wait' ? '…' : (it.st === 'off' ? '—' : '✗')));
                                return React.createElement('span', { key: i, style: { color: color, whiteSpace: 'nowrap', fontWeight: 600 } }, mark + ' ' + it.name + (it.st === 'off' ? ' · 수집 쉬는 중' : ''));
                            })
                        )
                    )
                ),

                /* [DATALAB] 로딩 인디케이터 */
                analysisData && !datalabData && datalabLoading && React.createElement('div', { className: 'section fade-in', style: { textAlign: 'center', padding: '24px 0' } },
                    React.createElement('div', { className: 'container' },
                        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, color: '#64748b', fontSize: 13 } },
                            React.createElement('div', { className: 'spinner-small' }),
                            '데이터랩 쇼핑인사이트 분석 중...'
                        )
                    )
                ),
    
                /* (검색 전 안내 제거 — 공간 낭비 없이 추적상품/순위 목록이 바로 보이도록) */
    
                /* 검색 로딩 */
                searchLoading && React.createElement('div', { className: 'section' },
                    React.createElement('div', { className: 'container' },
                        React.createElement('div', { style: { textAlign:'center', padding:'40px 20px' } },
                            React.createElement('span', { className:'spinner', style:{ width:32, height:32, borderWidth:3, marginBottom:16, display:'inline-block' } }),
                            React.createElement('div', { style: { fontSize:15, fontWeight:600, color:'#3b82f6', marginBottom:6 } }, '"' + searchedKeyword + '" 분석 중...'),
                            React.createElement('div', { style: { fontSize:13, color:'#94a3b8' } }, '검색량·경쟁강도·시장규모를 종합 분석하고 있습니다. 약 5~10초 소요됩니다.')
                        )
                    )
                ),
    
                /* ==================== 보고서 6단계 흐름 (v6.0 — 광고주 발송용 재배치) ==================== */
    
                /* [자료 없음] 직원 화면 안내 띠 — 결정 ③ⓐ 이유까지 */
                marketMissing && React.createElement('div', { className: 'section fade-in no-export' },
                    React.createElement('div', { className: 'container' },
                        React.createElement('div', { style: { background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 10, padding: '11px 15px', fontSize: 13, color: '#334155', lineHeight: 1.65 } },
                            React.createElement('b', null, '🛒 쇼핑 시장 자료 없음'),
                            ' — 쇼핑 순위 수집을 쉬는 동안(2026-11-05~) 경쟁 상품·가격·카테고리·순위 칸은 비어 있습니다. 검색량·연관 키워드·데이터랩·광고 경쟁 칸은 이 일과 상관없습니다. ',
                            React.createElement('b', null, '고장이 아닙니다.')
                        )
                    )
                ),

                /* [자료 없음] 광고주 전달본 맨 위 한 줄 — 결정 ①ⓐ (화면에서는 숨김 · 내보내기에서만 보임) */
                marketMissing && React.createElement('div', { className: 'section export-only', style: { display: 'none' } },
                    React.createElement('div', { className: 'container' },
                        React.createElement('div', { style: { background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '11px 15px', fontSize: 13, color: '#334155', lineHeight: 1.65 } },
                            '이번 보고서는 검색 수요 · 키워드 · 광고 경쟁 자료를 중심으로 작성했습니다. 경쟁 상품 · 가격 비교는 이번 보고서에 담지 않았습니다.'
                        )
                    )
                ),

                /* ========== 1. 종합 요약 ========== */
                analysisData && React.createElement(window.SectionDivider, { label: '1. 종합 요약', icon: '📋', color: '#3b82f6', sub: '광고주가 가장 먼저 보는 핵심 지표' }),
    
                analysisData && analysisData.summaryCards && React.createElement(window.SectionErrorBoundary, { name: '종합 요약' },
                    React.createElement('div', { id: 'sec-summary' },
                        React.createElement(SummaryCardsSection, {
                            data: analysisData.summaryCards,
                            marketMissing: marketMissing,
                            /* 히어로 요약용 — 전부 기존 데이터 재사용(없으면 히어로만 생략) */
                            keyword: searchedKeyword,
                            advertiserReport: advertiserReport,
                            rankCheckResult: rankCheckResult,
                            htmlReviewData: htmlReviewData
                        })
                    )
                ),

                /* 자사 강점 요약 배너 (강점 1개 이상일 때만 노출) */
                analysisData && React.createElement(window.SectionErrorBoundary, { name: '강점 요약' },
                    React.createElement(window.StrengthsHighlightBanner, {
                        reviewAnalysis: analysisData.reviewAnalysis,
                        htmlReviewData: htmlReviewData,
                        marketRevenue: analysisData.marketRevenue,
                        advertiserReport: advertiserReport,
                        datalabGrowth: datalabData && datalabData.growth
                    })
                ),
    
                /* ========== 2. 시장 · 수요 진단 ========== */
                analysisData && React.createElement(window.SectionDivider, { label: '2. 시장 · 수요 진단', icon: '📊', color: '#0ea5e9', sub: marketMissing ? '검색량 · 트렌드 · 시즌 · 인구 · 요일 · 성장' : '검색량 · 트렌드 · 시즌 · 인구 · 요일 · 성장 · 시장규모' }),
                marketMissing && _missingLine(['시장 규모 & 매출 추정']),
    
                /* 키워드 검색량 */
                volumeData && React.createElement(window.SectionErrorBoundary, { name: '키워드 검색량' },
                    React.createElement(KeywordVolumeSection, { keyword: searchedKeyword, data: volumeData })
                ),
    
                /* [DATALAB] 일일 한도 소진 안내 — 서버 quotaNotice 수신 시에만 노출 */
                datalabData && datalabData.quotaNotice && React.createElement('div', {
                    className: 'section fade-in',
                    style: { background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 10,
                             padding: '10px 14px', color: '#92400e', fontSize: 13, lineHeight: 1.6 }
                }, '⏳ ' + datalabData.quotaNotice),

                /* [DATALAB] 업종을 못 읽어 「생활/건강」 기준으로 센 경우 — 직원 화면에만 그 사실을 적는다 */
                datalabData && datalabData.categoryDefaulted && _staffNote('📊 업종을 읽지 못해 데이터랩 성별·연령·트렌드·요일은 「생활/건강」 기준으로 셌습니다. 다른 업종이면 숫자가 다를 수 있습니다.'),

                /* [DATALAB] 12개월 검색량 트렌드 (꺾은선) */
                datalabData && datalabData.trend && React.createElement(window.SectionErrorBoundary, { name: '검색량 트렌드' },
                    React.createElement(window.DatalabTrendSection, { data: datalabData.trend })
                ),
    
                /* [DATALAB] 시즌별 수요 예측 */
                datalabData && datalabData.season && React.createElement(window.SectionErrorBoundary, { name: '시즌별 수요' },
                    React.createElement(window.DatalabSeasonSection, { data: datalabData.season })
                ),

                /* 성수기 긴급성 안내 (성수기 식별 시) */
                datalabData && datalabData.season && React.createElement(window.SectionErrorBoundary, { name: '시즌 긴급성' },
                    React.createElement(window.SeasonUrgencyCountdown, { season: datalabData.season })
                ),
    
                /* [DATALAB] 성별 + 연령대별 검색 비율 */
                datalabData && (datalabData.gender || datalabData.age) && React.createElement(window.SectionErrorBoundary, { name: '검색 인구통계' },
                    React.createElement(window.DatalabDemographicsSection, { data: datalabData })
                ),
    
                /* [DATALAB] 요일별 검색 패턴 */
                datalabData && datalabData.weekday && React.createElement(window.SectionErrorBoundary, { name: '요일별 패턴' },
                    React.createElement(window.DatalabWeekdaySection, { data: datalabData.weekday })
                ),
    
                /* [DATALAB] 전년 동기 대비 성장률 */
                datalabData && datalabData.growth && React.createElement(window.SectionErrorBoundary, { name: '전년 성장률' },
                    React.createElement(window.DatalabGrowthSection, { data: datalabData.growth })
                ),
    
                /* [DATALAB] 카테고리 인기 키워드 TOP */
                datalabData && datalabData.categoryKeywords && React.createElement(window.SectionErrorBoundary, { name: '카테고리 인기 키워드' },
                    React.createElement(window.DatalabCategoryKeywordsSection, { data: datalabData.categoryKeywords })
                ),
    
                /* 시장 규모 & 매출 추정 */
                analysisData && analysisData.marketRevenue && React.createElement(window.SectionErrorBoundary, { name: '시장 규모' },
                    React.createElement('div', { id: 'sec-market' },
                        React.createElement(MarketRevenueSection, { advRank: (rankCheckResult && rankCheckResult.rank_position != null) ? rankCheckResult.rank_position : ((advertiserReport && advertiserReport.ranking) ? advertiserReport.ranking.current_rank : null), data: analysisData.marketRevenue, reviewCount: (htmlReviewData && htmlReviewData.reviewCount) || (analysisData.reviewAnalysis && analysisData.reviewAnalysis.reviewCount ? analysisData.reviewAnalysis.reviewCount.adv : null), productPrice: analysisData.marketRevenue ? parseInt((analysisData.marketRevenue.avgPrice || '0').replace(/[^0-9]/g, '')) : 0 })
                    )
                ),
    
                /* ========== 3. 경쟁 진단 ========== */
                analysisData && React.createElement(window.SectionDivider, { label: '3. 경쟁 진단', icon: '⚔️', color: '#ef4444', sub: marketMissing ? '광고경쟁 · 예상 CPC' : '경쟁강도 · 광고경쟁 · 경쟁사 · 카테고리' }),
                marketMissing && _missingLine(['경쟁강도', '경쟁사 비교표', '카테고리 등록 분석']),
    
                /* 키워드 경쟁강도 */
                analysisData && analysisData.competitionIndex && React.createElement(window.SectionErrorBoundary, { name: '경쟁강도' },
                    React.createElement('div', { id: 'sec-competition' },
                        React.createElement(CompetitionIndexSection, { data: analysisData.competitionIndex })
                    )
                ),
    
                /* 광고 경쟁 정보 */
                analysisData && analysisData.advertiserInfo && React.createElement(window.SectionErrorBoundary, { name: '광고 경쟁 정보' },
                    React.createElement(AdvertiserInfoCard, { data: analysisData.advertiserInfo })
                ),

                /* 예상 CPC · 권장 입찰가 (추정) */
                /* ⚠️ 종전 조건 `volumeData.length &&` 는 빈 배열이면 숫자 0 을 돌려 화면·전달본에 「0」 한 글자가 찍혔다(2026-11-16 고침) */
                analysisData && !volumeMissing && React.createElement(window.SectionErrorBoundary, { name: '예상 CPC' },
                    React.createElement(window.CpcBidEstimateSection, { volumeData: volumeData, keyword: searchedKeyword })
                ),
                analysisData && volumeMissing && _staffNote('⚔️ 검색량을 불러오지 못해 예상 CPC를 계산하지 못했습니다. 잠시 뒤 다시 분석하세요.'),
    
                /* 경쟁사 비교표 (상위 80개) */
                analysisData && analysisData.competitorTable && React.createElement(window.SectionErrorBoundary, { name: '경쟁사 비교표' },
                    React.createElement(window.CompetitorTableSection, { data: analysisData.competitorTable })
                ),

                /* 경쟁사 상위 10개 비교 · 격차 분석 — 3장(경쟁 진단)으로 재배치.
                 * 같은 컴포넌트를 part로 분할 렌더: 여기선 경쟁 비교/격차만, 전략 제안은 6장에 유지 */
                (advertiserReport || (analysisData && analysisData.strategicAnalysis)) && !advertiserLoading && React.createElement(window.SectionErrorBoundary, { name: '경쟁 격차 분석' },
                    React.createElement(EntryStrategySection, {
                        advertiserData: advertiserReport,
                        strategicData: analysisData && analysisData.strategicAnalysis,
                        keyword: searchedKeyword,
                        rankCheckResult: rankCheckResult,
                        part: 'competition'
                    })
                ),
    
                /* 카테고리 등록 분석 */
                analysisData && analysisData.categoryAnalysis && React.createElement(window.SectionErrorBoundary, { name: '카테고리 분석' },
                    React.createElement(CategoryAnalysisSection, { data: analysisData.categoryAnalysis })
                ),
    
                /* ========== 4. 내 상품 현황 ========== */
                analysisData && React.createElement(window.SectionDivider, { label: '4. 내 상품 현황', icon: '🛒', color: '#059669', sub: marketMissing ? '노출순위 · SEO 진단 · 상세페이지 분석' : '노출순위 · 판매추정 · 리뷰 · SEO 4종' }),
                marketMissing && _missingLine(['판매량 추정', '순위 상승 시 예상 성과', '리뷰 & 찜 분석', 'SEO 상세', '상세페이지 품질 진단']),
    
                /* 키워드별 노출 순위 — analysisOnly 모드(노출 분석·1회성 조회만, 보고서 구성 요소).
                   추적 상품 목록·등록 관리만 📊 키워드 순위 탭으로 분리(2026-08-04, 직원 신고로
                   노출 분석 블록은 복구 — 탭 분리 대상은 '추적 현황 열람'이지 분석 결과가 아님). */
                React.createElement(window.SectionErrorBoundary, { name: '순위 추적' },
                    React.createElement(RankTrackingSection, { analysisOnly: true, onOpenRankTab: props.onOpenRankTab, products: products, refreshProducts: loadProducts, searchedKeyword: searchedKeyword, searchedProductUrl: searchedProductUrl, cachedProductName: (advertiserReport && advertiserReport.product_info && advertiserReport.product_info.product_name) ? advertiserReport.product_info.product_name : ((advertiserReport && advertiserReport.product_name) ? advertiserReport.product_name : (analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo.product_name : null)), relatedKeywords: (relatedData ? (relatedData.golden_keywords || []).concat(relatedData.related_keywords || []).map(function(k) { return typeof k === 'string' ? k : (k && k.keyword) || ''; }).filter(Boolean) : []), onNavigateToClient: handleNavigateToClient, canEdit: currentUser.role !== 'viewer', onRankResult: setRankCheckResult })
                ),

                /* 분석 상품 순위추적 원클릭 등록 */
                searchedProductUrl && React.createElement(window.SectionErrorBoundary, { name: '추적 등록' },
                    React.createElement(window.TrackRegisterButton, { searchedProductUrl: searchedProductUrl, searchedKeyword: searchedKeyword, products: products, refreshProducts: loadProducts, canEdit: currentUser.role !== 'viewer', storeNameHint: _realStoreName })
                ),
    
                /* 판매량 추정 */
                analysisData && analysisData.salesEstimation && React.createElement(window.SectionErrorBoundary, { name: '판매량 추정' },
                    React.createElement('div', { id: 'sec-sales' },
                        React.createElement(SalesEstimationSection, { productUrl: searchedProductUrl, data: analysisData.salesEstimation, reviewCount: (htmlReviewData && htmlReviewData.reviewCount) || (analysisData.reviewAnalysis && analysisData.reviewAnalysis.reviewCount ? analysisData.reviewAnalysis.reviewCount.adv : null), productPrice: analysisData.marketRevenue ? parseInt((analysisData.marketRevenue.avgPrice || '0').replace(/[^0-9]/g, '')) : 0 })
                    )
                ),

                /* 순위 상승 시 예상 성과(ROI 델타) */
                analysisData && analysisData.salesEstimation && React.createElement(window.SectionErrorBoundary, { name: 'ROI 시뮬레이션' },
                    React.createElement(window.RankDeltaROISimulation, {
                        salesEstimation: analysisData.salesEstimation,
                        currentRank: (rankCheckResult && rankCheckResult.rank_position != null)
                            ? rankCheckResult.rank_position
                            : ((advertiserReport && advertiserReport.ranking) ? advertiserReport.ranking.current_rank : null)
                    })
                ),
    
                /* 리뷰 & 찜 분석 */
                analysisData && analysisData.reviewAnalysis && React.createElement(window.SectionErrorBoundary, { name: '리뷰 분석' },
                    React.createElement(window.ReviewAnalysisSection, { data: analysisData.reviewAnalysis, htmlReviewData: htmlReviewData })
                ),
    
                /* 리뷰 텍스트 분석 */
                htmlReviewData && htmlReviewData.reviews && htmlReviewData.reviews.length > 0 && React.createElement(window.SectionErrorBoundary, { name: '리뷰 텍스트 분석' },
                    React.createElement(window.ReviewTextAnalysisSection, {
                        data: htmlReviewData.reviewTextAnalysis,
                        reviews: htmlReviewData.reviews,
                        totalReviewCount: htmlReviewData.reviewCount
                    })
                ),
    
                /* SEO 종합 진단 */
                searchedProductUrl && React.createElement(window.SectionErrorBoundary, { name: 'SEO 진단' },
                    React.createElement(SeoDiagnosisSection, {
                        keyword: searchedKeyword,
                        productUrl: searchedProductUrl,
                        competitorData: analysisData && analysisData.competitorTable,
                        cachedRank: analysisData && analysisData.seoDetail ? (analysisData.seoDetail.popularity.items[0].pass !== undefined ? (function() {
                            var rankText = analysisData.seoDetail.popularity.items[0].label;
                            var m = rankText.match(/(\d+)위/);
                            return m ? parseInt(m[1]) : null;
                        })() : null) : null,
                        cachedProductName: (advertiserReport && advertiserReport.product_info && advertiserReport.product_info.product_name) ? advertiserReport.product_info.product_name : ((advertiserReport && advertiserReport.product_name) ? advertiserReport.product_name : (analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo.product_name : null)),
                        cachedTotalVolume: volumeData && volumeData[0] ? ((volumeData[0].monthlyPcQcCnt || 0) + (volumeData[0].monthlyMobileQcCnt || 0)) : null,
                        cachedProductInfo: analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo : null,
                        shopProducts: shopProducts,
                        htmlReviewData: htmlReviewData
                    })
                ),
    
                /* SEO 상세 분석 (적합도/신뢰도/인기도) */
                analysisData && analysisData.seoDetail && React.createElement(window.SectionErrorBoundary, { name: 'SEO 상세' },
                    React.createElement(window.SeoDetailSection, { data: analysisData.seoDetail })
                ),
    
                /* 상세페이지 품질 진단 */
                analysisData && analysisData.detailPageQuality && React.createElement(window.SectionErrorBoundary, { name: '상세페이지 품질' },
                    React.createElement(window.DetailPageQualitySection, { data: analysisData.detailPageQuality })
                ),
    
                /* 상세페이지 HTML 분석 */
                htmlDetailResult && React.createElement(window.SectionErrorBoundary, { name: '상세페이지 HTML 분석' },
                    React.createElement(window.HtmlDetailAnalysisSection, { data: htmlDetailResult })
                ),
    
                /* ========== 5. 기회 발굴 ========== */
                analysisData && React.createElement(window.SectionDivider, { label: '5. 기회 발굴', icon: '💎', color: '#7c3aed', sub: marketMissing ? '연관키워드 · 골든키워드' : '연관키워드 · 골든키워드 · 상품명 최적화' }),
                marketMissing && _missingLine(['상품명 키워드 분석', '상품명 SEO 최적화 제안']),
    
                /* 연관 키워드 — 검색광고 조회 실패면 「총 0개 ✅ 실측」 대신 직원 화면에 실패를 적는다(전달본에서는 뺀다) */
                relatedData && relatedLookupFailed && _staffNote('🔗 연관 키워드 · 불러오지 못함 — 네이버 검색광고 조회가 실패했습니다. 「연관 키워드가 없다」는 뜻이 아닙니다. 잠시 뒤 다시 분석하세요.'),
                relatedData && !relatedLookupFailed && React.createElement(window.SectionErrorBoundary, { name: '연관 키워드' },
                    React.createElement(RelatedKeywordsSection, { data: relatedData, keyword: searchedKeyword, fit: keywordFit })
                ),
    
                /* 골든 키워드 (0건이어도 대안 안내를 렌더) */
                analysisData && React.createElement(window.SectionErrorBoundary, { name: '골든 키워드' },
                    React.createElement('div', { id: 'sec-golden' },
                        React.createElement(GoldenKeywordCard, { data: _fitGolden, lookupFailed: relatedLookupFailed })
                    )
                ),
    
                /* 상품명 키워드 분석 (키워드&태그 통합) */
                searchedProductUrl && React.createElement(window.SectionErrorBoundary, { name: '상품명 분석' },
                    /* 경쟁 상품명이 없으면 이 칸은 비어 있다 — 직원이 손으로 붙여 넣어 쓸 수 있게 화면에는 두고, 전달본에서는 뺀다 */
                    React.createElement('div', { className: marketMissing ? 'no-export' : undefined },
                        React.createElement(ProductNameSection, { keyword: searchedKeyword, shopProducts: shopProducts })
                    )
                ),
    
                /* 상품명 SEO 최적화 제안 */
                analysisData && analysisData.productNameOpt && React.createElement(window.SectionErrorBoundary, { name: '상품명 최적화' },
                    React.createElement(window.ProductNameOptSection, { data: analysisData.productNameOpt })
                ),
    
                /* ========== 6. 전략 · 결론 ========== */
                analysisData && React.createElement(window.SectionDivider, { label: '6. 전략 · 결론', icon: '🧭', color: '#1e293b', sub: '진입전략 · AI 종합 · 보고서 내보내기' }),
    
                /* 17. 1페이지 진입 전략 (경쟁 비교표·격차는 3장으로 이동 — part 분할) */
                (advertiserReport || (analysisData && analysisData.strategicAnalysis)) && !advertiserLoading && React.createElement(window.SectionErrorBoundary, { name: '진입 전략' },
                    React.createElement(EntryStrategySection, {
                        advertiserData: advertiserReport,
                        strategicData: analysisData && analysisData.strategicAnalysis,
                        keyword: searchedKeyword,
                        rankCheckResult: rankCheckResult,
                        part: 'strategy'
                    })
                ),
    
                /* 19. AI 종합 분석 리포트 */
                analysisData && React.createElement(window.SectionErrorBoundary, { name: 'AI 종합 분석' },
                    React.createElement(AiFeedbackAllSection, {
                        productUrl: searchedProductUrl,
                        keyword: searchedKeyword,
                        analysisData: _fitAnalysis,
                        volumeData: volumeData,
                        relatedData: relatedData,
                        advertiserReport: advertiserReport,
                        htmlReviewData: htmlReviewData,
                        datalabData: datalabData,
                        /* 늦게 오는 두 가지가 끝났는지 — AI 호출을 20초 기다리지 않고 그 즉시 시작하려고 넘긴다 */
                        datalabLoading: datalabLoading,
                        advertiserLoading: advertiserLoading
                    })
                ),
    
                /* 20. 업체 등록/저장 — 관리팀은 업체+경쟁사, 영업사원(viewer)은 경쟁사 저장만 */
                analysisData && React.createElement(window.SectionErrorBoundary, { name: '업체 저장' },
                    React.createElement(SaveToClientSection, {
                        keyword: searchedKeyword,
                        productUrl: searchedProductUrl,
                        analysisData: analysisData,
                        volumeData: volumeData,
                        relatedData: relatedData,
                        shopProducts: shopProducts,
                        advertiserReport: advertiserReport,
                        detailHtml: lastHtmlRef.current,
                        htmlDetailResult: htmlDetailResult,
                        competitorContext: props.competitorContext,
                        onCompetitorSaved: props.onCompetitorSaved,
                        isViewer: currentUser.role === 'viewer',
                        defaultName: _displayCompany,
                    })
                ),
    
                /* 21. 보고서 출력 */
                searchedProductUrl && React.createElement(window.SectionErrorBoundary, { name: '보고서' },
                    React.createElement(ReportSection, { keyword: searchedKeyword, companyName: companyName, managerName: currentUser && currentUser.name, onMakeProposal: props.onMakeProposal })
                ),
    
                /* 알림 설정 (admin/superadmin만) */
                (currentUser.role === 'admin' || currentUser.role === 'superadmin') && React.createElement(window.SectionErrorBoundary, { name: '알림 설정' },
                    React.createElement(NotificationSection, null)
                ),
    
                /* 푸터 */
                React.createElement(window.Footer, null)
                  ) /* report-main 닫기 */
                ) /* report-shell 닫기 */
    );
};
