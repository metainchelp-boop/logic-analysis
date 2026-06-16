/* App — 메인 앱 컴포넌트 (v3 에이전시) */
/* APP_VERSION은 utils.js에서 전역 선언 */

/* ==================== 정적 스타일 (렌더 밖 — 매번 재생성 방지) ==================== */
var _navBtnBase = { padding: '6px 14px', borderRadius: 8, cursor: 'pointer', fontSize: 13, transition: 'all 0.2s' };
var _navBtnActive = Object.assign({}, _navBtnBase, { background: 'rgba(59,130,246,0.9)', color: '#fff', border: 'none', fontWeight: 600 });
var _navBtnInactive = Object.assign({}, _navBtnBase, { background: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.75)', border: '1px solid rgba(255,255,255,0.12)', fontWeight: 400 });
var _navUserStyle = { color: 'rgba(255,255,255,0.7)', fontSize: 13 };
var _navLogoutStyle = { background: 'rgba(239,68,68,0.15)', color: '#fca5a5', border: '1px solid rgba(239,68,68,0.2)', padding: '6px 14px', borderRadius: 8, cursor: 'pointer', fontSize: 13 };
var _topbarContainer = { display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', minHeight: 48, padding:'8px 24px', gap:6 };
var _versionBadge = { fontSize:11, color:'rgba(255,255,255,0.4)', background:'rgba(255,255,255,0.06)', padding:'2px 8px', borderRadius:10, fontWeight:400 };
var _healthBadge = { background:'rgba(16,185,129,0.2)', color:'#34d399', fontSize:11, padding:'2px 8px', borderRadius:10, fontWeight:400 };

window.App = function App() {
    const { useState, useEffect, useCallback } = React;

    /* ==================== 인증 상태 ==================== */
    const [currentUser, setCurrentUser] = useState(null);
    const [authToken, setAuthToken] = useState(null);
    const [authChecking, setAuthChecking] = useState(true);
    // URL hash에서 현재 페이지 복원 (새로고침 시 탭 유지)
    var _getPageFromHash = function() {
        var hash = window.location.hash.replace('#', '');
        var validPages = ['home', 'analysis', 'management', 'guide', 'settings'];
        return validPages.indexOf(hash) !== -1 ? hash : 'home';
    };
    const [currentPage, setCurrentPage] = useState(_getPageFromHash);

    /* ==================== 기존 상태 (hooks는 반드시 조건문 전에) ==================== */
    const [health, setHealth] = useState(false);
    const [products, setProducts] = useState([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [searchedKeyword, setSearchedKeyword] = useState('');
    const [volumeData, setVolumeData] = useState(null);
    const [relatedData, setRelatedData] = useState(null);
    const [analysisData, setAnalysisData] = useState(null);
    const [shopProducts, setShopProducts] = useState(null);
    const [advertiserReport, setAdvertiserReport] = useState(null);
    const [advertiserLoading, setAdvertiserLoading] = useState(false);
    const [htmlReviewData, setHtmlReviewData] = useState(null);
    const [htmlDetailResult, setHtmlDetailResult] = useState(null);
    const [searchedProductUrl, setSearchedProductUrl] = useState('');
    const [companyName, setCompanyName] = useState('');
    const [datalabData, setDatalabData] = useState(null);
    const [datalabLoading, setDatalabLoading] = useState(false);
    const [rankCheckResult, setRankCheckResult] = useState(null); // 순위 추적 → 진입 전략 공유용
    const searchIdRef = React.useRef(0); // 비동기 요청 경합 방지용
    const lastHtmlRef = React.useRef(''); // #1: 마지막 분석에 쓰인 상세 HTML (업체 저장/재사용용)

    /* 업체 카드 클릭으로 시작된 분석 추적 (자동 저장용) */
    const [currentClientId, setCurrentClientId] = useState(null);
    const [searchBarInitial, setSearchBarInitial] = useState(null);
    const [autoSaveStatus, setAutoSaveStatus] = useState(''); // '', 'saving', 'saved', 'error'

    /* 순위 추적 → 업체관리 이동 시 자동 검색용 */
    const [managementInitialSearch, setManagementInitialSearch] = useState(null);


    var saveAuth = function(user, token) {
        setCurrentUser(user); setAuthToken(token);
        try { sessionStorage.setItem('logic_token', token); sessionStorage.setItem('logic_user', JSON.stringify(user)); } catch(e) {}
    };
    var clearAuth = function() {
        setCurrentUser(null); setAuthToken(null); setCurrentPage('analysis');
        try { sessionStorage.removeItem('logic_token'); sessionStorage.removeItem('logic_user'); } catch(e) {}
    };

    useEffect(function() {
        try {
            // 0) 전산(ERP) SSO 자동 로그인: URL ?sso=<토큰> 있으면 우선 처리
            var _ssoTok = '';
            try { _ssoTok = new URLSearchParams(window.location.search).get('sso') || ''; } catch(e) {}
            if (_ssoTok) {
                var _cleanUrl = function() {
                    try {
                        var u = new URL(window.location.href);
                        u.searchParams.delete('sso');
                        window.history.replaceState({}, document.title, u.pathname + u.search + u.hash);
                    } catch(e) {}
                };
                fetch('/api/auth/sso', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: _ssoTok }) })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        _cleanUrl();
                        if (data && data.success && data.token && data.user) {
                            saveAuth(data.user, data.token);
                        }
                        setAuthChecking(false);
                    }).catch(function() { _cleanUrl(); setAuthChecking(false); });
                return; // SSO 처리로 분기 — 아래 세션복원 스킵
            }
            // 기존 세션 복원
            var savedToken = sessionStorage.getItem('logic_token');
            if (savedToken) {
                fetch('/api/auth/me', { headers: { 'Authorization': 'Bearer ' + savedToken } })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data && data.id) { setCurrentUser(data); setAuthToken(savedToken); }
                        else if (data && data.success && data.user) { setCurrentUser(data.user); setAuthToken(savedToken); }
                        setAuthChecking(false);
                    }).catch(function() { setAuthChecking(false); });
            } else { setAuthChecking(false); }
        } catch(e) { setAuthChecking(false); }
    }, []);

    // URL hash ↔ currentPage 동기화
    useEffect(function() {
        if (currentPage) {
            window.location.hash = currentPage;
        }
    }, [currentPage]);

    useEffect(function() {
        var onHashChange = function() {
            var page = _getPageFromHash();
            setCurrentPage(page);
        };
        window.addEventListener('hashchange', onHashChange);
        return function() { window.removeEventListener('hashchange', onHashChange); };
    }, []);

    // 헬스체크
    useEffect(function() {
        if (currentUser) {
            api.get('/health').then(function(res) { setHealth(res.status === 'ok'); }).catch(function() { setHealth(false); });
        }
    }, [currentUser]);

    // 상품 목록 로드
    var loadProducts = useCallback(function() {
        api.get('/products').then(function(res) {
            if (res.success) setProducts(res.data);
        }).catch(function() {});
    }, []);

    useEffect(function() { if (currentUser) loadProducts(); }, [loadProducts, currentUser]);

    /* 업체 연동 자동 저장 — Rules of Hooks에 따라 early return 이전에 선언.
       실제 저장 조건은 effect 내부에서 가드 (로그인 전에는 currentClientId가 null이라 no-op). */
    useEffect(function() {
        if (!currentClientId) return;
        if (!analysisData) return;
        if (searchLoading) return;
        if (currentUser && currentUser.role === 'viewer') return; // 뷰어는 자동저장 금지
        if (autoSaveStatus === 'saving' || autoSaveStatus === 'saved') return;

        setAutoSaveStatus('saving');
        var savedClientId = currentClientId;
        var savedKeyword = searchedKeyword;
        var savedUrl = searchedProductUrl;
        var mounted = true;
        var nestedTimers = [];
        var timer = setTimeout(function() {
            if (!mounted) return;
            var reportHtml = (typeof captureAutoReportHtml === 'function') ? captureAutoReportHtml(savedKeyword) : '';
            api.post('/cd/analyze', {
                client_id: savedClientId,
                keyword: savedKeyword,
                product_url: savedUrl || '',
                analysis_data: (htmlDetailResult ? Object.assign({}, analysisData, { htmlDetail: trimHtmlDetail(htmlDetailResult) }) : analysisData),
                volume_data: volumeData || {},
                related_data: relatedData || {},
                shop_products: (shopProducts || []).slice(0, 20),
                advertiser_data: advertiserReport || {},
                report_html: reportHtml,
                detail_html: lastHtmlRef.current || '',
            }).then(function(res) {
                if (!mounted) return;
                if (res && res.success) {
                    setAutoSaveStatus('saved');
                    nestedTimers.push(setTimeout(function() { if (mounted) setAutoSaveStatus(''); }, 4000));
                } else {
                    setAutoSaveStatus('error');
                    nestedTimers.push(setTimeout(function() { if (mounted) setAutoSaveStatus(''); }, 5000));
                }
            }).catch(function() {
                if (!mounted) return;
                setAutoSaveStatus('error');
                nestedTimers.push(setTimeout(function() { if (mounted) setAutoSaveStatus(''); }, 5000));
            });
        }, 25000);

        return function() { mounted = false; clearTimeout(timer); nestedTimers.forEach(function(t) { clearTimeout(t); }); };
    }, [analysisData, currentClientId, searchLoading, autoSaveStatus]);

    if (authChecking) return React.createElement('div', { style: { display:'flex', flexDirection:'column', justifyContent:'center', alignItems:'center', height:'100vh', background:'linear-gradient(135deg,#6C5CE7,#a29bfe)', gap:16 } },
        React.createElement('img', { src: '/img/logo_dark.png', alt: 'META INC', style: { height:40, width:'auto', marginBottom:8 } }),
        React.createElement('span', { className:'spinner', style:{ width:28, height:28, borderWidth:3, borderColor:'rgba(255,255,255,0.3)', borderTopColor:'#fff' } }),
        React.createElement('div', { style: { color:'#fff', fontSize:14, fontWeight:500, opacity:0.8 } }, '시스템 연결 중...'));
    if (!currentUser) return React.createElement(window.LoginPage, { onLogin: saveAuth });

    // 수동 검색 (SearchBar 제출): 업체 자동연동 해제
    var handleManualSearch = function(keyword, productUrl, inputCompanyName, htmlInput) {
        setCurrentClientId(null);
        setAutoSaveStatus('');
        handleSearch(keyword, productUrl, inputCompanyName, htmlInput);
    };

    // 상품 URL 정리 — 불필요한 추적 파라미터 제거
    var cleanProductUrl = function(url) {
        if (!url) return '';
        try {
            var u = new URL(url);
            // smartstore URL이면 path만 유지 (NaPm, nl-query 등 제거)
            if (u.hostname.indexOf('smartstore.naver.com') !== -1) {
                return u.origin + u.pathname;
            }
            // 그 외 URL은 NaPm, nl-query 파라미터만 제거
            u.searchParams.delete('NaPm');
            u.searchParams.delete('nl-query');
            return u.toString();
        } catch(e) { return url; }
    };

    // 통합 검색 (htmlInput: 검색바에서 입력된 HTML — 상세페이지 분석 + 리뷰 추출에 사용)
    var handleSearch = function(keyword, productUrl, inputCompanyName, htmlInput) {
        // Viewer 일일 분석 횟수 체크 (백엔드 연동)
        if (currentUser && currentUser.role === 'viewer') {
            api.get('/cd/usage/check').then(function(usageRes) {
                if (usageRes && usageRes.success && usageRes.data && !usageRes.data.can_query) {
                    toast.error('일일 분석 제한(3회)을 초과했습니다. 내일 자정에 초기화됩니다.');
                    return;
                }
                // 제한 내 → 카운트 증가 후 실제 분석 실행
                api.post('/cd/usage/increment').then(function() {
                    _doSearch(keyword, productUrl, inputCompanyName, htmlInput);
                }).catch(function() {
                    _doSearch(keyword, productUrl, inputCompanyName, htmlInput);
                });
            }).catch(function() {
                _doSearch(keyword, productUrl, inputCompanyName, htmlInput);
            });
            return;
        }
        // 관리자/매니저도 수동 분석 카운팅
        api.post('/cd/usage/increment').catch(function() {});
        _doSearch(keyword, productUrl, inputCompanyName, htmlInput);
    };

    var _doSearch = function(keyword, productUrl, inputCompanyName, htmlInput) {
        lastHtmlRef.current = htmlInput || '';  // #1: 저장/재사용용 상세 HTML 보관
        if (inputCompanyName !== undefined) setCompanyName(inputCompanyName);
        var cleanedUrl = cleanProductUrl(productUrl);
        // URL을 안 넣어도 됨: 붙여넣은 HTML에서 상품 URL 자동 추출 → 순위/광고주 분석 정상 동작
        if (!cleanedUrl && htmlInput && typeof extractProductUrlFromHtml === 'function') {
            var _autoUrl = extractProductUrlFromHtml(htmlInput);
            if (_autoUrl) {
                cleanedUrl = cleanProductUrl(_autoUrl);
                try { toast.info('HTML에서 상품 URL을 자동 인식했습니다.'); } catch(e) {}
            }
        }
        var currentSearchId = ++searchIdRef.current; // 새 검색마다 ID 증가
        setSearchLoading(true);
        setSearchedKeyword(keyword);
        setSearchedProductUrl(cleanedUrl);
        setVolumeData(null);
        setRelatedData(null);
        setAnalysisData(null);
        setShopProducts(null);
        setAdvertiserReport(null);
        setAdvertiserLoading(false);
        setHtmlReviewData(null);
        setHtmlDetailResult(null);
        setDatalabData(null);
        setDatalabLoading(false);
        setRankCheckResult(null);

        // 검색바에서 HTML이 입력되었으면 상세페이지 분석 + 리뷰 데이터 추출 (비동기)
        if (htmlInput && htmlInput.length >= 100) {
            api.post('/seo/detail-page', { html: htmlInput, product_url: productUrl || '' })
                .then(function(res) {
                    if (searchIdRef.current !== currentSearchId) return; // 이미 다른 검색 시작됨
                    if (res && res.success && res.data) {
                        setHtmlDetailResult(res.data);
                        if (res.data.reviewData) {
                            setHtmlReviewData(res.data.reviewData);
                        }
                        toast.success('상세페이지 HTML 분석 완료');
                    } else if (res && !res.success) {
                        toast.error('상세페이지 분석 실패: ' + (res.detail || '서버 오류'));
                    }
                })
                .catch(function(e) {
                    if (searchIdRef.current !== currentSearchId) return;
                    console.warn('HTML 상세페이지 분석 실패:', e.message);
                    toast.error('상세페이지 분석 요청 실패 — ' + (e.message || '네트워크 오류'));
                });
        }

        // 광고주 상품 URL이 있으면 광고주 분석 API 호출
        if (productUrl) {
            setAdvertiserLoading(true);
            api.post('/advertiser/analyze', { keyword: keyword, product_url: productUrl })
                .then(function(res) {
                    if (searchIdRef.current !== currentSearchId) return;
                    if (res && res.success) setAdvertiserReport(res.data);
                    setAdvertiserLoading(false);
                })
                .catch(function() {
                    if (searchIdRef.current !== currentSearchId) return;
                    setAdvertiserLoading(false);
                });
        }

        // 병렬로 3개 API 호출
        Promise.all([
            api.post('/keyword/volume', [keyword]).catch(function() { return null; }),
            api.post('/keywords/related', { keyword: keyword }).catch(function() { return null; }),
            api.post('/products/search', { keyword: keyword, count: 80 }).catch(function() { return null; }),
        ]).then(function(results) {
            if (searchIdRef.current !== currentSearchId) return; // 이미 다른 검색 시작됨

            var volRes = results[0];
            var relRes = results[1];
            var shopRes = results[2];

            // 모든 API 실패 시 사용자에게 알림
            if ((!volRes || !volRes.success) && (!relRes || !relRes.success) && (!shopRes || !shopRes.success)) {
                toast.error('키워드 분석 데이터를 가져오지 못했습니다. 네트워크를 확인해주세요.');
            }

            if (volRes && volRes.success) setVolumeData(volRes.data);
            if (relRes && relRes.success) setRelatedData(relRes.data);

            var prods = (shopRes && shopRes.success && shopRes.data) ? shopRes.data.products : [];
            var totalShopProducts = (shopRes && shopRes.success && shopRes.data) ? shopRes.data.total : 0;
            if (prods.length > 0) setShopProducts(prods);

            // 검색량 데이터 추출
            var vol = (volRes && volRes.success && volRes.data && volRes.data[0]) ? volRes.data[0] : null;
            var totalVol = vol ? ((vol.monthlyPcQcCnt || 0) + (vol.monthlyMobileQcCnt || 0)) : 0;
            var productCount = totalShopProducts || prods.length;

            // 연관 키워드 데이터
            var rd = (relRes && relRes.success && relRes.data) ? relRes.data : null;

            // ==================== 분석 데이터 계산 ====================
            var analysis = {};

            // 1. 경쟁강도 계산 (백분율 변환)
            if (productCount > 0 && totalVol > 0) {
                var rawIdx = productCount / totalVol;
                // 백분율 변환: rawIdx 0→0%, 0.5→30%, 1.0→50%, 2.0→70%, 5.0→90%, 10+→98%
                // 로그 스케일로 자연스럽게 매핑
                var compPercent = Math.min(98, Math.round(Math.log10(rawIdx * 10 + 1) / Math.log10(101) * 100));
                compPercent = Math.max(2, compPercent);

                var compLevel, compColor;
                if (compPercent <= 30) {
                    compLevel = '블루오션';
                    compColor = '#059669';
                } else if (compPercent <= 70) {
                    compLevel = '보통';
                    compColor = '#d97706';
                } else {
                    compLevel = '레드오션';
                    compColor = '#dc2626';
                }

                // 전문 코멘트 2~3줄 (실제 데이터 기반)
                var avgCtrVal = vol ? (vol.monthlyAvePcClkCnt || 0) + (vol.monthlyAveMobileClkCnt || 0) : 0;
                var compComment = '';
                if (compPercent <= 30) {
                    compComment = '월간 검색량 ' + fmt(totalVol) + '회 대비 등록 상품 ' + fmt(productCount) + '개로, 공급이 수요를 따라가지 못하는 시장입니다. ';
                    compComment += '신규 진입 시 상위 노출 가능성이 높으며, 상품 등록만으로도 검색 트래픽을 확보할 수 있는 최적의 타이밍입니다.';
                    if (avgCtrVal > 0) compComment += ' 평균 클릭수 ' + avgCtrVal.toFixed(1) + '회로 구매 의향이 높은 키워드입니다.';
                } else if (compPercent <= 70) {
                    compComment = '월간 검색량 ' + fmt(totalVol) + '회에 상품 ' + fmt(productCount) + '개가 경쟁 중인 시장입니다. ';
                    compComment += '진입은 가능하지만, 가격 경쟁력·리뷰 확보·상품명 최적화 등 차별화 전략이 필요합니다. ';
                    compComment += '상위 10위 이내 진입을 목표로 SEO 최적화에 집중하세요.';
                } else {
                    compComment = '월간 검색량 ' + fmt(totalVol) + '회 대비 상품 ' + fmt(productCount) + '개로, 공급 과잉 상태의 치열한 시장입니다. ';
                    compComment += '기존 상위 셀러들이 리뷰·판매 실적을 선점하고 있어, 동일 키워드로의 진입은 높은 광고비를 수반합니다. ';
                    compComment += '세부 키워드(롱테일) 전략이나 틈새 카테고리를 공략하는 것을 권장합니다.';
                }

                analysis.competitionIndex = {
                    compIndex: parseFloat(rawIdx.toFixed(2)),
                    compPercent: compPercent,
                    compLabel: compLevel,
                    compColor: compColor,
                    productCount: productCount,
                    searchVolume: totalVol,
                    avgCtr: avgCtrVal,
                    interpretation: compComment,
                };
            }

            // 2. 시장 규모 추정 (CTR × 전환율 기반)
            if (prods.length > 0) {
                var prices = prods.map(function(p) { return p.price; }).filter(function(p) { return p > 0; });
                var avgPrice = prices.length > 0 ? Math.round(prices.reduce(function(a, b) { return a + b; }, 0) / prices.length) : 0;

                var conversionRate = 0.035; // 전환율 3.5%

                var topProductsList = prods.slice(0, 40).map(function(p) {
                    var ctr = getCTR(p.rank);
                    var estSales = Math.max(1, Math.round(totalVol * ctr * conversionRate));
                    return {
                        rank: p.rank,
                        name: p.product_name,
                        store: p.store_name,
                        price: p.price,
                        priceStr: fmt(p.price) + '원',
                        ctr: ctr,
                        estMonthlySales: estSales,
                        estMonthlySalesStr: fmt(estSales) + '건',
                        estRevenue: p.price * estSales,
                        estRevenueStr: fmt(p.price * estSales) + '원',
                    };
                });

                // 전체 시장 규모 = 상위 40개 상품 추정 매출 합산
                var totalMarketRevenue = topProductsList.slice(0, 40).reduce(function(sum, p) {
                    return sum + p.estRevenue;
                }, 0);

                analysis.marketRevenue = {
                    avgPrice: fmt(avgPrice) + '원',
                    estimatedMonthly: fmt(totalMarketRevenue) + '원',
                    conversionRate: '3.5%',
                    calculationMethod: 'CTR × 전환율',
                    topProducts: topProductsList.map(function(p) {
                        return {
                            rank: p.rank,
                            name: p.name,
                            store: p.store,
                            price: p.priceStr,
                            ctr: (p.ctr * 100).toFixed(1) + '%',
                            estMonthlySales: p.estMonthlySalesStr,
                            estRevenue: p.estRevenueStr,
                        };
                    }),
                };
            }

            // 3. 키워드 트렌드
            if (totalVol > 0 && rd && rd.related_keywords && rd.related_keywords.length > 0) {
                var subKw = rd.related_keywords[0];
                analysis.keywordTrend = {
                    mainKeyword: keyword,
                    subKeyword: subKw.keyword,
                    mainVolume: totalVol,
                    subVolume: subKw.totalVolume || 0,
                    mainDifficulty: (function() { var ci = analysis.competitionIndex; return ci && ci.compIndex < 0.5 ? '쉬움' : ci && ci.compIndex < 1.0 ? '보통' : '어려움'; })(),
                    subDifficulty: subKw.compIdx === '낮음' || subKw.compIdx === 'LOW' ? '쉬움' : subKw.compIdx === '높음' || subKw.compIdx === 'HIGH' ? '어려움' : '보통',
                    mainDiffColor: analysis.competitionIndex ? analysis.competitionIndex.compColor : '#94a3b8',
                    subDiffColor: subKw.compIdx === '낮음' || subKw.compIdx === 'LOW' ? '#16a34a' : subKw.compIdx === '높음' || subKw.compIdx === 'HIGH' ? '#dc2626' : '#d97706',
                };
            }

            // 4. 골든 키워드 (스토어명 필터링 적용)
            if (rd && rd.golden_keywords && rd.golden_keywords.length > 0) {
                // 스토어명이 아닌 키워드만 필터 (백엔드에서 이미 필터하지만 이중 안전장치)
                var filteredGolden = rd.golden_keywords.filter(function(gk) {
                    return !gk.isStoreName;
                });
                var gk = filteredGolden.length > 0 ? filteredGolden[0] : rd.golden_keywords[0];

                var gkVolume = gk.totalVolume || 0;
                var gkClicks = gk.monthlyAvePcClkCnt ? (gk.monthlyAvePcClkCnt + gk.monthlyAveMobileClkCnt) : 0;
                var gkClickRate = gkVolume > 0 ? ((gkClicks / gkVolume) * 100).toFixed(1) : 0;

                // 디테일한 추천 이유 생성
                var gkReason = '"' + gk.keyword + '"은(는) 월간 검색량 ' + fmt(gkVolume) + '회로 안정적인 수요가 존재합니다. ';
                if (gkClicks > 0) {
                    gkReason += '평균 클릭수 ' + gkClicks.toFixed(1) + '회(클릭률 ' + gkClickRate + '%)로 구매 의도가 높은 키워드입니다. ';
                }
                gkReason += '경쟁강도 "' + compLabel(gk.compIdx) + '" 수준이라 상위 노출 진입 비용이 낮습니다. ';
                gkReason += '메인 키워드 "' + keyword + '"의 세부 키워드로 상품명에 함께 포함시키면 추가 유입을 확보할 수 있습니다.';

                analysis.goldenKeyword = {
                    name: gk.keyword,
                    score: gk.score || (gkVolume ? Math.round(gkVolume / 100) : 0),
                    volume: gkVolume,
                    competition: compLabel(gk.compIdx),
                    ctr: gkClicks,
                    clicks: Math.round(gkVolume * 0.05),
                    reason: gkReason,
                };
            }

            // 5. 광고주 상품 정보
            if (vol) {
                analysis.advertiserInfo = {
                    adDepth: vol.plAvgDepth || 0,
                    pcClicks: (vol.monthlyAvePcClkCnt || 0).toFixed(1),
                    mobileClicks: (vol.monthlyAveMobileClkCnt || 0).toFixed(1),
                    compIdx: vol.compIdx || '-',
                };
            }

            // 6. 종합 요약 카드
            analysis.summaryCards = {
                totalVolume: fmt(totalVol),
                productCount: fmt(productCount),
                goldenCount: rd ? (rd.golden_keywords || []).length : 0,
                compLevel: analysis.competitionIndex ? analysis.competitionIndex.compLabel : '-',
            };

            // 7. 카테고리 분석 (대>중>소 계층 경로)
            if (prods.length > 0) {
                var fullpathMap = {};
                var cat1Map = {};
                var cat2Map = {};
                var cat3Map = {};
                prods.forEach(function(p) {
                    var c1 = p.category1 || '';
                    var c2 = p.category2 || '';
                    var c3 = p.category3 || '';
                    var parts = [c1, c2, c3].filter(function(x) { return x; });
                    var fullPath = parts.length > 0 ? parts.join(' > ') : '기타';
                    fullpathMap[fullPath] = (fullpathMap[fullPath] || 0) + 1;
                    if (c1) cat1Map[c1] = (cat1Map[c1] || 0) + 1;
                    if (c2) cat2Map[c2] = (cat2Map[c2] || 0) + 1;
                    if (c3) cat3Map[c3] = (cat3Map[c3] || 0) + 1;
                });
                var total = prods.length;
                var categories = Object.keys(fullpathMap).map(function(k) {
                    return { name: k, count: fullpathMap[k], ratio: Math.round(fullpathMap[k] / total * 100) };
                }).sort(function(a, b) { return b.count - a.count; });
                var makeLevelList = function(map) {
                    return Object.keys(map).map(function(k) {
                        return { name: k, count: map[k], ratio: Math.round(map[k] / total * 100) };
                    }).sort(function(a, b) { return b.count - a.count; }).slice(0, 5);
                };
                var topCat = categories[0] || { name: '-', ratio: 0 };
                analysis.categoryAnalysis = {
                    verdict: topCat.name + ' 카테고리에 ' + topCat.ratio + '% 등록',
                    mainCategory: topCat.name,
                    categories: categories.slice(0, 8),
                    categoryLevels: {
                        large: makeLevelList(cat1Map),
                        medium: makeLevelList(cat2Map),
                        small: makeLevelList(cat3Map),
                    },
                };
            }

            // 8. 키워드 & 태그 분석
            if (rd) {
                var allKws = (rd.golden_keywords || []).concat(rd.related_keywords || []);
                analysis.keywordTags = {
                    topKeywords: allKws.slice(0, 15).map(function(k) {
                        return { keyword: k.keyword, volume: k.totalVolume || 0, comp: compLabel(k.compIdx), isGolden: k.isGolden };
                    }),
                    totalFound: rd.total_found || allKws.length,
                };
            }

            // 9. 경쟁사 비교표 (종합점수 포함)
            if (prods.length > 0) {
                // 상위 20개 평균가격 (가격 경쟁력 계산용)
                var compPrices = prods.slice(0, 20).map(function(p) { return p.price; }).filter(function(p) { return p > 0; });
                var avgCompPrice = compPrices.length > 0 ? compPrices.reduce(function(a, b) { return a + b; }, 0) / compPrices.length : 0;
                // 최다 카테고리 (카테고리 적합도 계산용)
                var catCounts = {};
                prods.slice(0, 80).forEach(function(p) {
                    var cat = p.category2 || p.category1 || '';
                    if (cat) catCounts[cat] = (catCounts[cat] || 0) + 1;
                });
                var topCat = '';
                var topCatCount = 0;
                Object.keys(catCounts).forEach(function(k) { if (catCounts[k] > topCatCount) { topCat = k; topCatCount = catCounts[k]; } });

                analysis.competitorTable = prods.slice(0, 80).map(function(p) {
                    // --- 종합점수 계산 (백엔드 SEO 로직과 동일 가중치) ---
                    // 1. 상품명 (15%) — 키워드 포함 여부
                    var kwInTitle = keyword.toLowerCase().split(' ').some(function(w) { return p.product_name.toLowerCase().indexOf(w) >= 0; });
                    var nameLen = p.product_name.length;
                    var titleSc = (kwInTitle ? 40 : 0) + (nameLen >= 20 && nameLen <= 50 ? 30 : nameLen >= 10 ? 20 : 10) + 20;

                    // 2. 가격 경쟁력 (12%)
                    var priceSc = 50;
                    if (p.price > 0 && avgCompPrice > 0) {
                        var pr = p.price / avgCompPrice;
                        priceSc = pr <= 0.85 ? 100 : pr <= 1.0 ? 80 : pr <= 1.15 ? 60 : pr <= 1.3 ? 40 : 20;
                    }

                    // 3. 순위 (15%)
                    var rankSc = p.rank <= 10 ? 100 : p.rank <= 20 ? 80 : p.rank <= 40 ? 60 : 40;

                    // 4. 리뷰 추정 (12%)
                    var reviewSc = p.rank <= 5 ? 95 : p.rank <= 10 ? 80 : p.rank <= 20 ? 60 : 40;

                    // 5. 평점 추정 (8%)
                    var ratingSc = p.rank <= 10 ? 90 : p.rank <= 20 ? 75 : p.rank <= 40 ? 60 : 45;

                    // 6. 판매실적 추정 (10%)
                    var salesSc = p.rank <= 5 ? 95 : p.rank <= 10 ? 80 : p.rank <= 20 ? 60 : 40;

                    // 7. 카테고리 적합도 (8%)
                    var pCat = p.category2 || p.category1 || '';
                    var catSc = pCat === topCat ? 100 : pCat ? 60 : 20;

                    // 8. 브랜드 (8%)
                    var brandSc = (p.brand ? 40 : 0) + (p.store_name ? 30 : 0) + (p.product_url && p.product_url.indexOf('smartstore.naver.com') >= 0 ? 30 : 0);
                    brandSc = Math.min(brandSc, 100);

                    // 9. 네이버페이 (6%)
                    var npSc = p.product_url && p.product_url.indexOf('smartstore.naver.com') >= 0 ? 100 : 50;

                    // 10. 최신성 (6%)
                    var freshSc = p.rank <= 20 ? 80 : p.rank <= 40 ? 60 : 40;

                    var totalSc = Math.round(
                        titleSc * 0.15 + priceSc * 0.12 + rankSc * 0.15 +
                        reviewSc * 0.12 + ratingSc * 0.08 + salesSc * 0.10 +
                        catSc * 0.08 + brandSc * 0.08 + npSc * 0.06 + freshSc * 0.06
                    );

                    return {
                        rank: p.rank,
                        name: p.product_name,
                        store: p.store_name,
                        price: fmt(p.price) + '원',
                        brand: p.brand || '-',
                        category: p.category2 || p.category1 || '-',
                        image: p.image_url,
                        seoScore: totalSc,
                    };
                });
            }

            // 10. 판매량 추정 카드형 (TOP10 / 1페이지 / 2페이지) — CTR_TABLE 전역 사용
            if (prods.length > 0 && totalVol > 0) {
                var top10p = prods.slice(0, 10);
                var avgP = Math.round(top10p.reduce(function(s, p) { return s + p.price; }, 0) / top10p.length);
                var cv = 0.035;
                // 80위 전체 한번에 계산
                var allRanks = [];
                for (var ci = 0; ci < 80; ci++) {
                    var sales = Math.round(totalVol * CTR_TABLE[ci] * cv);
                    allRanks.push({ sales: sales, revenue: sales * avgP });
                }
                // TOP 10 집계
                var top10Rev = 0;
                for (var ci = 0; ci < 10; ci++) top10Rev += allRanks[ci].revenue;
                // 1페이지 (1~40) 집계
                var p1Sales = 0, p1Total = 0;
                for (var ci = 0; ci < 40; ci++) { p1Sales += allRanks[ci].sales; p1Total += allRanks[ci].revenue; }
                // 2페이지 (41~80) 집계
                var p2Sales = 0, p2Total = 0;
                for (var ci = 40; ci < 80; ci++) { p2Sales += allRanks[ci].sales; p2Total += allRanks[ci].revenue; }

                analysis.salesEstimation = {
                    avgPrice: fmt(avgP) + '원',
                    monthlySearches: fmt(totalVol),
                    estimatedCTR: 'CTR × 3.5%',
                    top10Card: {
                        rank1Sales: allRanks[0].sales, rank5Sales: allRanks[4].sales, rank10Sales: allRanks[9].sales,
                        rank1Revenue: fmt(allRanks[0].revenue) + '원', rank10Revenue: fmt(allRanks[9].revenue) + '원',
                        totalRevenue: fmt(top10Rev) + '원'
                    },
                    page1Card: {
                        avgSales: Math.round(p1Sales / 40), totalSales: p1Sales,
                        maxRevenue: fmt(allRanks[0].revenue) + '원', minRevenue: fmt(allRanks[39].revenue) + '원',
                        avgRevenue: fmt(Math.round(p1Total / 40)) + '원', totalRevenue: fmt(p1Total) + '원'
                    },
                    page2Card: {
                        avgSales: Math.round(p2Sales / 40), totalSales: p2Sales,
                        maxRevenue: fmt(allRanks[40].revenue) + '원', minRevenue: fmt(allRanks[79].revenue) + '원',
                        avgRevenue: fmt(Math.round(p2Total / 40)) + '원', totalRevenue: fmt(p2Total) + '원'
                    }
                };
            }

            // 11. 1페이지 진입 전략 비교
            if (prods.length >= 10 && totalVol > 0) {
                var topItems = prods.slice(0, 10);
                var topPrices = topItems.map(function(p) { return p.price; });
                var avgTopPrice = Math.round(topPrices.reduce(function(s, v) { return s + v; }, 0) / topPrices.length);
                var minPrice = Math.min.apply(null, topPrices);
                var maxPrice = Math.max.apply(null, topPrices);
                var ci = analysis.competitionIndex;
                analysis.strategicAnalysis = {
                    avgTop5Price: fmt(avgTopPrice) + '원',
                    priceRange: fmt(minPrice) + '원 ~ ' + fmt(maxPrice) + '원',
                    monthlyVolume: fmt(totalVol),
                    mainBrands: (function() {
                        var brands = {};
                        topItems.forEach(function(p) { var b = p.brand || p.store_name; brands[b] = (brands[b] || 0) + 1; });
                        return Object.keys(brands).slice(0, 5).join(', ');
                    })(),
                    recommendation: ci && ci.compIndex < 0.5
                        ? '현재 시장은 블루오션입니다. 빠른 진입을 추천합니다.'
                        : ci && ci.compIndex < 1.0
                        ? '경쟁이 적당합니다. 가격/리뷰 전략에 집중하세요.'
                        : '경쟁이 치열합니다. 차별화된 상세페이지와 리뷰 확보가 핵심입니다.',
                };
            }

            // URL에서 스토어명 추출 (매칭 검증용 — 섹션 12, 13에서 공통 사용)
            var _storeMatch = cleanedUrl ? cleanedUrl.match(/smartstore\.naver\.com\/([^\/]+)/) : null;
            var _targetStoreName = _storeMatch ? _storeMatch[1].toLowerCase() : '';
            // 안전한 advProd 매칭 헬퍼 (스토어 URL 슬러그 교차 검증)
            var _findAdvProd = function(prodList) {
                if (!cleanedUrl) return null;
                // 1차: 전체 URL 포함 매칭 (가장 정확)
                var found = prodList.find(function(p) { return p.product_url && p.product_url.indexOf(cleanedUrl) >= 0; });
                if (found) return found;
                // 2차: 채널상품ID(URL의 /products/ID)로 매칭
                var pidMatch = cleanedUrl.match(/\/products\/(\d+)/);
                if (pidMatch) {
                    var pid = pidMatch[1];
                    // 2-a: product_id 필드 직접 비교
                    found = prodList.find(function(p) { return p.product_id && String(p.product_id) === pid; });
                    if (found) return found;
                    // 2-b: product_url에 PID 포함 (네이버 API link = /main/products/채널ID)
                    found = prodList.find(function(p) {
                        return p.product_url && p.product_url.indexOf(pid) >= 0;
                    });
                    if (found) return found;
                }
                // 3차: 스토어명으로 매칭 (URL/PID 매칭 실패 시 — store_name 또는 URL 슬러그)
                if (_targetStoreName) {
                    found = prodList.find(function(p) {
                        // store_name 필드 직접 비교
                        if ((p.store_name || '').toLowerCase() === _targetStoreName) return true;
                        // product_url에서 스토어 슬러그 추출하여 비교
                        var pSlugMatch = (p.product_url || '').match(/smartstore\.naver\.com\/([^\/\?]+)/);
                        if (pSlugMatch && pSlugMatch[1].toLowerCase() === _targetStoreName) return true;
                        return false;
                    });
                }
                return found || null;
            };

            // 12. 리뷰 분석 (상위 상품 기반 추정)
            if (prods.length >= 5) {
                var top5 = prods.slice(0, 5);
                var top20 = prods.slice(0, 20);
                var allProds = prods.slice(0, 80);

                // 리뷰 수 추정 (순위 기반 로그 감소 모델)
                var estReviews = function(rank) { return Math.max(1, Math.round(2000 / Math.pow(rank, 0.7))); };
                var advReview = cleanedUrl ? (function() {
                    var advProd = _findAdvProd(prods);
                    return advProd ? estReviews(advProd.rank) : estReviews(40);
                })() : estReviews(40);
                var avgReview = Math.round(top20.reduce(function(s, p) { return s + estReviews(p.rank); }, 0) / top20.length);
                var top5Review = Math.round(top5.reduce(function(s, p) { return s + estReviews(p.rank); }, 0) / top5.length);

                // 평점 추정 (상위 4.5~4.9, 하위 4.0~4.5)
                var estRating = function(rank) { return Math.round((4.9 - (rank - 1) * 0.012) * 10) / 10; };
                var advRating = cleanedUrl ? (function() {
                    var advProd = _findAdvProd(prods);
                    return advProd ? estRating(advProd.rank) : estRating(40);
                })() : estRating(40);
                var avgRating = Math.round(top20.reduce(function(s, p) { return s + estRating(p.rank); }, 0) / top20.length * 10) / 10;
                var top5Rating = Math.round(top5.reduce(function(s, p) { return s + estRating(p.rank); }, 0) / top5.length * 10) / 10;

                // 찜 수 추정
                var estWish = function(rank) { return Math.max(5, Math.round(500 / Math.pow(rank, 0.6))); };
                var advWish = cleanedUrl ? (function() {
                    var advProd = _findAdvProd(prods);
                    return advProd ? estWish(advProd.rank) : estWish(40);
                })() : estWish(40);
                var avgWish = Math.round(top20.reduce(function(s, p) { return s + estWish(p.rank); }, 0) / top20.length);
                var top5Wish = Math.round(top5.reduce(function(s, p) { return s + estWish(p.rank); }, 0) / top5.length);

                var reviewGap = avgReview > 0 ? Math.round(((advReview - avgReview) / avgReview) * 100) : 0;
                var ratingGap = avgRating > 0 ? Math.round(((advRating - avgRating) / avgRating) * 100) : 0;
                var wishGap = avgWish > 0 ? Math.round(((advWish - avgWish) / avgWish) * 100) : 0;

                analysis.reviewAnalysis = {
                    reviewCount: { adv: advReview, avg: avgReview, top5: top5Review, gapColor: reviewGap >= 0 ? '#16a34a' : '#dc2626', gapLabel: (reviewGap >= 0 ? '+' : '') + reviewGap + '%' },
                    rating: { adv: advRating.toFixed(1), avg: avgRating.toFixed(1), top5: top5Rating.toFixed(1), gapColor: ratingGap >= 0 ? '#16a34a' : '#dc2626', gapLabel: (ratingGap >= 0 ? '+' : '') + ratingGap + '%' },
                    wishCount: { adv: advWish, avg: avgWish, top5: top5Wish, gapColor: wishGap >= 0 ? '#16a34a' : '#dc2626', gapLabel: (wishGap >= 0 ? '+' : '') + wishGap + '%' },
                    reviewGapPercent: reviewGap,
                    ratingGapPercent: ratingGap,
                    wishGapPercent: wishGap,
                    strategy: reviewGap < 0
                        ? '리뷰 수가 경쟁 평균보다 부족합니다. 체험단/구매 후기 이벤트를 통해 리뷰를 확보하세요.'
                        : '리뷰 수가 경쟁 평균 이상입니다. 평점 관리에 집중하세요.'
                };
            }

            // 13. SEO 상세 분석 (상품URL 있을 때)
            if (prods.length > 0) {
                // 공통 헬퍼로 안전하게 매칭
                var advProd = _findAdvProd(prods);
                // advProd가 없으면 (광고주 상품 매칭 실패) prods[0]을 사용하지 않음
                var targetProd = advProd;
                if (targetProd) {
                    var kwWords = keyword.toLowerCase().split(/\s+/);
                    var titleLower = targetProd.product_name.toLowerCase();
                    // 공백 무시 매칭도 인정: 네이버는 띄어쓰기와 무관하게 키워드를 매칭하므로
                    // '브로멜라인효소'(붙임)와 '브로멜라인 효소'(띄움)를 동일하게 취급한다.
                    var titleNoSpace = titleLower.replace(/\s+/g, '');
                    var kwNoSpace = keyword.toLowerCase().replace(/\s+/g, '');
                    var kwInTitle = kwWords.every(function(w) { return titleLower.indexOf(w) >= 0; })
                        || (kwNoSpace.length > 0 && titleNoSpace.indexOf(kwNoSpace) >= 0);
                    var titleLen = targetProd.product_name.length;
                    var isSmartStore = targetProd.product_url && targetProd.product_url.indexOf('smartstore.naver.com') >= 0;
                    var hasBrand = !!targetProd.brand;
                    var hasCategory = !!(targetProd.category2 || targetProd.category1);
                    var myRank = targetProd.rank || null;
                    var myRankLabel = myRank ? myRank + '위' : '미노출';

                    var relScore = (kwInTitle ? 40 : 0) + (titleLen >= 20 && titleLen <= 50 ? 30 : titleLen >= 10 ? 15 : 5) + (hasCategory ? 30 : 10);
                    var trustScore = (isSmartStore ? 35 : 15) + (hasBrand ? 30 : 10) + (myRank && myRank <= 20 ? 35 : myRank && myRank <= 40 ? 20 : 10);
                    var popScore = (myRank && myRank <= 5 ? 40 : myRank && myRank <= 10 ? 30 : myRank && myRank <= 20 ? 20 : 10)
                        + (myRank && myRank <= 10 ? 30 : myRank && myRank <= 20 ? 20 : 10)
                        + (myRank && myRank <= 10 ? 30 : myRank && myRank <= 30 ? 20 : 10);

                    analysis.seoDetail = {
                        relevance: {
                            score: relScore,
                            items: [
                                { pass: kwInTitle, label: '키워드 "' + keyword + '"이(가) 상품명에 포함됨' },
                                { pass: titleLen >= 20 && titleLen <= 50, label: '상품명 길이 적절 (' + titleLen + '자)' },
                                { pass: hasCategory, label: '카테고리 정보 존재: ' + (targetProd.category2 || targetProd.category1 || '없음') },
                                { pass: kwWords.length > 1 && kwInTitle, label: '복합 키워드 완전 포함' }
                            ]
                        },
                        trustworthy: {
                            score: trustScore,
                            items: [
                                { pass: isSmartStore, label: '네이버 스마트스토어 입점' },
                                { pass: hasBrand, label: '브랜드 등록: ' + (targetProd.brand || '미등록') },
                                { pass: myRank && myRank <= 20, label: myRank ? '상위 노출 달성 (현재 ' + myRankLabel + ')' : '검색 결과 내 미노출' },
                                { pass: isSmartStore, label: '네이버페이 결제 지원' }
                            ]
                        },
                        popularity: {
                            score: popScore,
                            items: [
                                { pass: myRank && myRank <= 10, label: myRank ? '검색 결과 ' + myRankLabel + (myRank <= 10 ? ' (상위 10위 이내)' : '') : '검색 결과 내 미노출' },
                                { pass: myRank && myRank <= 20, label: '추정 리뷰 수 경쟁력 있음' },
                                { pass: myRank && myRank <= 10, label: '추정 판매량 상위권' },
                                { pass: myRank && myRank <= 30, label: '찜 수 평균 이상 추정' }
                            ]
                        }
                    };

                    // 14. 상세페이지 품질 진단
                    var dpScores = [
                        { label: '상품명 최적화', score: kwInTitle ? (titleLen >= 20 && titleLen <= 50 ? 95 : 70) : 30, maxScore: 100, color: '#6366f1' },
                        { label: '가격 경쟁력', score: (function() { var avgP = prods.slice(0, 20).reduce(function(s, p) { return s + p.price; }, 0) / 20; return targetProd.price <= avgP ? 85 : targetProd.price <= avgP * 1.2 ? 60 : 35; })(), maxScore: 100, color: '#22c55e' },
                        { label: '브랜드/스토어 신뢰도', score: (hasBrand ? 40 : 0) + (isSmartStore ? 40 : 20) + 10, maxScore: 100, color: '#f59e0b' },
                        { label: '카테고리 적합도', score: hasCategory ? 80 : 30, maxScore: 100, color: '#06b6d4' },
                        { label: '검색 노출 순위', score: myRank ? (myRank <= 5 ? 95 : myRank <= 10 ? 80 : myRank <= 20 ? 60 : myRank <= 40 ? 40 : 20) : 10, maxScore: 100, color: '#ec4899' }
                    ];
                    var dpTotal = Math.round(dpScores.reduce(function(s, b) { return s + b.score; }, 0) / dpScores.length);
                    var dpGrade = dpTotal >= 80 ? 'A등급' : dpTotal >= 60 ? 'B등급' : dpTotal >= 40 ? 'C등급' : 'D등급';
                    var dpGradeColor = dpTotal >= 80 ? '#dcfce7' : dpTotal >= 60 ? '#dbeafe' : dpTotal >= 40 ? '#fef3c7' : '#fee2e2';

                    analysis.detailPageQuality = {
                        totalScore: dpTotal,
                        grade: dpGrade,
                        gradeColor: dpGradeColor,
                        scoreBars: dpScores,
                        checklist: [
                            { category: '상품명', items: [
                                { pass: kwInTitle, text: '메인 키워드 포함' },
                                { pass: titleLen >= 20, text: '상품명 20자 이상' },
                                { pass: titleLen <= 50, text: '상품명 50자 이하 (과도하지 않음)' }
                            ]},
                            { category: '가격/혜택', items: [
                                { pass: targetProd.price > 0, text: '정상 가격 등록' },
                                { pass: isSmartStore, text: '네이버페이 지원' }
                            ]},
                            { category: '신뢰도', items: [
                                { pass: hasBrand, text: '브랜드 등록 완료' },
                                { pass: isSmartStore, text: '스마트스토어 입점' },
                                { pass: hasCategory, text: '정확한 카테고리 설정' }
                            ]}
                        ],
                        comment: dpTotal >= 80 ? '상세페이지 품질이 우수합니다. 현재 전략을 유지하세요.' : dpTotal >= 60 ? '전반적으로 양호하나 일부 개선이 필요합니다.' : '상세페이지 개선이 시급합니다. 상품명과 가격 경쟁력을 우선 확인하세요.'
                    };

                    // 15. 상품명 SEO 최적화 제안
                    var nameIssues = [];
                    nameIssues.push({ pass: kwInTitle, text: kwInTitle ? '메인 키워드 "' + keyword + '" 포함됨' : '메인 키워드 "' + keyword + '" 미포함 — 상품명에 추가 필요' });
                    nameIssues.push({ pass: titleLen >= 20 && titleLen <= 50, text: titleLen < 20 ? '상품명이 너무 짧음 (' + titleLen + '자) — 20자 이상 권장' : titleLen > 50 ? '상품명이 너무 김 (' + titleLen + '자) — 50자 이하 권장' : '상품명 길이 적절 (' + titleLen + '자)' });

                    var hasSpecialChars = /[★☆♥♡●○■□▶◀※@#$%^&*]/.test(targetProd.product_name);
                    nameIssues.push({ pass: !hasSpecialChars, text: hasSpecialChars ? '특수문자/이모지 포함 — SEO에 불리할 수 있음' : '불필요한 특수문자 없음' });

                    var hasDuplicateWords = (function() {
                        var words = targetProd.product_name.split(/\s+/);
                        var seen = {};
                        return words.some(function(w) { if (seen[w]) return true; seen[w] = true; return false; });
                    })();
                    nameIssues.push({ pass: !hasDuplicateWords, text: hasDuplicateWords ? '중복 단어 존재 — 제거 권장' : '중복 단어 없음' });

                    // 추천 상품명 생성
                    var suggested = targetProd.product_name;
                    if (!kwInTitle) {
                        suggested = keyword + ' ' + targetProd.product_name;
                        // 중복 단어 토큰 제거 (키워드와 기존 상품명에 같은 단어가 겹치면 한 번만 유지)
                        var _seenWord = {};
                        suggested = suggested.split(/\s+/).filter(function(w) {
                            if (!w) return false;
                            var lw = w.toLowerCase();
                            if (_seenWord[lw]) return false;
                            _seenWord[lw] = true;
                            return true;
                        }).join(' ');
                        if (suggested.length > 50) suggested = suggested.substring(0, 50).trim();
                    }

                    analysis.productNameOpt = {
                        currentName: targetProd.product_name,
                        issues: nameIssues,
                        suggestedName: suggested !== targetProd.product_name ? suggested : null,
                        marketerComment: kwInTitle
                            ? '상품명에 메인 키워드가 포함되어 있어 기본적인 SEO는 충족합니다. 연관 키워드를 추가하면 노출이 더 개선될 수 있습니다.'
                            : '상품명에 메인 키워드 "' + keyword + '"가 없습니다. 상품명 앞부분에 키워드를 배치하면 검색 노출이 크게 개선됩니다.'
                    };
                }
            }

            // SEO 진단용 targetProd 정보 저장 (get_product_info API 호출 제거용)
            if (targetProd) {
                analysis.targetProductInfo = {
                    product_name: targetProd.product_name,
                    price: targetProd.price,
                    brand: targetProd.brand || '',
                    store_name: targetProd.store_name || '',
                    category1: targetProd.category1 || '',
                    category2: targetProd.category2 || '',
                    image_url: targetProd.image_url || ''
                };
            } else if (_targetStoreName && prods.length > 0) {
                // URL/PID/스토어 3단계 매칭 모두 실패해도 스토어 정보는 전달
                // → 백엔드에서 cached_competitors 스토어명 매칭으로 get_product_info 호출 방지
                var _sameStoreProd = prods.find(function(p) {
                    return (p.store_name || '').toLowerCase() === _targetStoreName ||
                           ((p.product_url || '').match(/smartstore\.naver\.com\/([^\/\?]+)/) || [])[1] === _targetStoreName;
                });
                analysis.targetProductInfo = {
                    product_name: _sameStoreProd ? _sameStoreProd.product_name : '',
                    price: _sameStoreProd ? _sameStoreProd.price : 0,
                    brand: _sameStoreProd ? (_sameStoreProd.brand || '') : '',
                    store_name: _sameStoreProd ? (_sameStoreProd.store_name || _targetStoreName) : _targetStoreName,
                    category1: _sameStoreProd ? (_sameStoreProd.category1 || '') : '',
                    category2: _sameStoreProd ? (_sameStoreProd.category2 || '') : '',
                    image_url: _sameStoreProd ? (_sameStoreProd.image_url || '') : ''
                };
            }

            setAnalysisData(Object.keys(analysis).length > 0 ? analysis : null);
            setSearchLoading(false);

            /* 데이터랩 쇼핑인사이트 비동기 호출 (분석 완료 후) */
            (function() {
                var cat1 = '';
                if (analysis.categoryAnalysis && analysis.categoryAnalysis.categoryLevels && analysis.categoryAnalysis.categoryLevels.large && analysis.categoryAnalysis.categoryLevels.large.length > 0) {
                    cat1 = analysis.categoryAnalysis.categoryLevels.large[0].name || '';
                }
                var relKws = [];
                if (analysis.keywordTags && analysis.keywordTags.topKeywords) {
                    relKws = analysis.keywordTags.topKeywords.map(function(k) { return { keyword: k.keyword, totalVolume: parseInt(String(k.volume || '0').replace(/,/g, '')) }; });
                }
                setDatalabLoading(true);
                api.post('/datalab/analyze', { keyword: keyword, category1: cat1, related_keywords: relKws })
                    .then(function(dlRes) {
                        if (searchIdRef.current !== currentSearchId) return;
                        if (dlRes && dlRes.success && dlRes.data) {
                            setDatalabData(dlRes.data);
                        }
                    }).catch(function(e) {
                        console.warn('데이터랩 조회 실패 (무시):', e);
                    }).finally(function() {
                        setDatalabLoading(false);
                    });
            })();

        }).catch(function(e) {
            if (searchIdRef.current !== currentSearchId) return;
            console.error('검색 오류:', e);
            toast.error('분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
            setSearchLoading(false);
        });
    };

    /* ==================== 순위 추적 → 업체관리 이동 ==================== */
    var handleNavigateToClient = function(storeName, productUrl) {
        setManagementInitialSearch({ storeName: storeName || '', productUrl: productUrl || '' });
        setCurrentPage('management');
        try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch(e) {}
    };

    /* ==================== 업체 카드 클릭 → 자동 분석 ==================== */
    var handleClientClick = function(params) {
        if (!params) return;
        setCurrentClientId(params.clientId);
        setSearchBarInitial({
            keyword: params.keyword || '',
            productUrl: params.productUrl || '',
            companyName: params.companyName || ''
        });
        setAutoSaveStatus('');
        setCurrentPage('analysis');
        try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch(e) {}
        // #1: 업체에 저장된 상세 HTML이 있으면 자동 주입 → 리뷰 텍스트/상세 분석 자동 표시
        handleSearch(params.keyword, params.productUrl || '', params.companyName || '', params.detailHtml || null);
    };

    /* DOM 캡처 — 자동 저장용 HTML 보고서 생성 (SaveToClientSection과 동일 로직) */
    /* (본 함수는 hook이 아니라 일반 함수이므로 early return 이후 위치에 있어도 됨) */
    var captureAutoReportHtml = function(kw) {
        try {
            var captured = [];
            // 화면의 실제 보고서 본문(.report-main)을 통째로 캡처 → 화면과 동일
            var srcRoot = document.querySelector('.report-main')
                || (document.getElementById('root') && document.getElementById('root').children[0]);
            if (srcRoot) {
                var cloneRoot = srcRoot.cloneNode(true);
                // 차트(canvas) → 이미지 변환 (정적 HTML에서도 보이도록)
                try {
                    var _oc = srcRoot.querySelectorAll('canvas');
                    var _cc = cloneRoot.querySelectorAll('canvas');
                    for (var _i = 0; _i < _cc.length; _i++) {
                        var _du = '';
                        var _o = _oc[_i];
                        var _ch = (window.Chart && window.Chart.getChart && _o) ? window.Chart.getChart(_o) : null;
                        if (_ch) { try { _du = _ch.toBase64Image('image/png', 1); } catch(e) {} }
                        if (!_du && _o && _o.toDataURL) { try { _du = _o.toDataURL('image/png'); } catch(e) {} }
                        if (!_du) continue;
                        var _img = document.createElement('img');
                        _img.src = _du; _img.style.cssText = 'width:100%;height:auto;display:block;margin-bottom:14px;';
                        if (_cc[_i].parentNode) _cc[_i].parentNode.replaceChild(_img, _cc[_i]);
                        // 겹침방지(핵심): 이미지 직속 부모(차트 래퍼 height:NNNpx 고정) + .chartbox 모두 높이 해제
                        var _wrap2 = _img.parentNode;
                        if (_wrap2 && _wrap2.style) { _wrap2.style.height = 'auto'; _wrap2.style.minHeight = '0'; _wrap2.style.position = 'static'; }
                        var _box2 = (_img.closest && _img.closest('.chartbox')) || _wrap2;
                        if (_box2 && _box2.style) { _box2.style.height = 'auto'; _box2.style.minHeight = '0'; _box2.style.overflow = 'visible'; _box2.style.marginBottom = '18px'; }
                    }
                } catch(e) {}
                captured.push(cloneRoot);
            }
            captured.forEach(function(node) {
                // 내보내기 제외 영역 제거 (보고서/알림/업체저장/네비/버튼/입력)
                ['#sec-report', '#sec-notify', '#sec-save-client', '.anchor-nav', '.topbar', '.no-export'].forEach(function(sel) {
                    node.querySelectorAll(sel).forEach(function(el) { el.remove(); });
                });
                node.querySelectorAll('button, .btn').forEach(function(b) { b.remove(); });
                node.querySelectorAll('input, select, textarea').forEach(function(inp) {
                    var span = document.createElement('span');
                    span.textContent = inp.value || '';
                    span.style.fontWeight = '600';
                    if (inp.parentNode) inp.parentNode.replaceChild(span, inp);
                });
            });
            var cssText = '';
            try {
                var sheets = document.styleSheets;
                for (var i = 0; i < sheets.length; i++) {
                    try {
                        var rules = sheets[i].cssRules || sheets[i].rules;
                        for (var j = 0; j < rules.length; j++) { cssText += rules[j].cssText + '\n'; }
                    } catch(e) {}
                }
            } catch(e) {}
            var bodyHtml = '';
            captured.forEach(function(node) { bodyHtml += node.outerHTML + '\n'; });
            var dateStr = new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
            // XSS 방지: HTML 특수문자 이스케이프
            var _esc = function(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; };
            var headerText = _esc(kw || '키워드') + ' 분석 보고서';
            return '<!DOCTYPE html>\n<html lang="ko">\n<head>\n'
                + '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                + '<title>' + headerText + ' - ' + dateStr + '</title>\n<style>\n'
                + '* { margin: 0; padding: 0; box-sizing: border-box; }\n'
                + 'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #1e293b; }\n'
                + '.report-header { background: linear-gradient(135deg, #6C5CE7, #a29bfe); color: #fff; padding: 40px 20px; text-align: center; }\n'
                + '.report-header h1 { font-size: 24px; margin-bottom: 8px; }\n'
                + '.report-header p { font-size: 14px; opacity: 0.85; }\n'
                + '.report-footer { text-align: center; padding: 30px; color: #94a3b8; font-size: 12px; border-top: 1px solid #e2e8f0; margin-top: 40px; }\n'
                + cssText
                + '\n</style>\n</head>\n<body>\n'
                + '<div class="report-header">\n<h1>' + headerText + '</h1>\n'
                + '<p>' + dateStr + ' | 메타아이앤씨 로직 분석 시스템</p>\n</div>\n'
                + '<div style="max-width:1200px; margin:0 auto; padding:20px;">\n' + bodyHtml + '</div>\n'
                + '<div class="report-footer">\n<p>© 2026 메타아이앤씨 — 로직 분석 시스템 | 자동 저장된 보고서</p>\n</div>\n'
                + '</body>\n</html>';
        } catch(e) {
            console.error('자동 DOM capture 실패:', e);
            return '';
        }
    };

    /* 저장된 분석 데이터를 실제 분석 화면으로 재렌더 → 화면과 동일하게 HTML 다운로드 (옵션 A) */
    var downloadSavedReport = function(saved) {
        if (!saved) { toast.error('보고서 데이터가 없습니다.'); return; }
        var kw = saved.keyword || '';
        // 1) 저장 데이터를 화면 상태에 주입 → 분석 화면(React 컴포넌트)으로 그대로 렌더
        setCurrentClientId(saved.client_id || null);
        setCompanyName(saved.companyName || saved.client_name || '');
        setSearchedKeyword(kw);
        setSearchedProductUrl(saved.product_url || '');
        setAnalysisData(saved.analysis_data || null);
        setVolumeData(saved.volume_data || null);
        setRelatedData(saved.related_data || null);
        setShopProducts(saved.shop_products || []);
        setAdvertiserReport(saved.advertiser_data || null);
        // Phase2: 저장된 상세분석(analysis_data.htmlDetail) 주입 → 상세HTML분석·리뷰텍스트 렌더
        var _hd = saved.analysis_data && saved.analysis_data.htmlDetail;
        setHtmlDetailResult(_hd || null);
        setHtmlReviewData(_hd && _hd.reviewData ? _hd.reviewData : null);
        setCurrentPage('analysis');
        try { window.scrollTo({ top: 0 }); } catch(e) {}
        toast.info('보고서를 화면에 불러오는 중… 잠시 후 자동 다운로드됩니다.');
        // 2) 차트가 그려질 시간을 준 뒤 화면 그대로 캡처 → 다운로드
        setTimeout(function() {
            try {
                var htmlStr = captureAutoReportHtml(kw);
                if (!htmlStr) { toast.error('보고서 생성에 실패했습니다.'); return; }
                var blob = new Blob([htmlStr], { type: 'text/html;charset=utf-8' });
                var a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = (saved.companyName || saved.client_name || '업체') + '_' + kw + '_보고서_' + (saved.analyzed_date || '') + '.html';
                document.body.appendChild(a); a.click(); a.remove();
                URL.revokeObjectURL(a.href);
                toast.success('보고서를 다운로드했습니다. (화면과 동일)');
            } catch(e) {
                toast.error('보고서 다운로드 실패: ' + (e && e.message ? e.message : ''));
            }
        }, 3000);
    };

    // 앵커 네비게이션 (페이지 렌더링 순서와 동일하게 정렬)
    var sections = [
        { id: 'sec-rank', label: '순위 추적', icon: '📍' },
        { id: 'sec-summary', label: '종합요약', icon: '📊', show: !!(analysisData && analysisData.summaryCards) },
        { id: 'sec-volume', label: '검색량', icon: '🔍', show: !!volumeData },
        { id: 'sec-market', label: '시장규모', icon: '💰', show: !!(analysisData && analysisData.marketRevenue) },
        { id: 'sec-sales', label: '판매추정', icon: '💵', show: !!(analysisData && analysisData.salesEstimation) },
        { id: 'sec-competition', label: '경쟁강도', icon: '⚔️', show: !!(analysisData && analysisData.competitionIndex) },
        { id: 'sec-related', label: '연관키워드', icon: '🔗', show: !!relatedData },
        { id: 'sec-golden', label: '골든키워드', icon: '🌟', show: !!(analysisData && analysisData.goldenKeyword) },
        { id: 'sec-competitor', label: '경쟁사', icon: '🏆', show: !!(analysisData && analysisData.competitorTable) },
        { id: 'sec-seo', label: 'SEO 진단', icon: '🎯', show: !!searchedProductUrl },
        { id: 'sec-productname', label: '상품명', icon: '✏️', show: !!searchedProductUrl },
        { id: 'sec-strategy', label: '진입전략', icon: '🚀', show: !!(advertiserReport || advertiserLoading || (analysisData && analysisData.strategicAnalysis)) },
        { id: 'sec-report', label: '보고서', icon: '📄', show: !!searchedProductUrl },
    ].filter(function(s) { return s.show !== false; });

    var scrollTo = function(id) {
        var el = document.getElementById(id);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    /* ==================== Topbar 스타일 (정적 객체는 컴포넌트 밖에 선언) ==================== */
    var navBtn = function(active) { return active ? _navBtnActive : _navBtnInactive; };


    var renderTopbar = function(activePage) {
        return React.createElement('div', { className: 'topbar' },
            React.createElement('div', { className: 'container', style: _topbarContainer },
                React.createElement('div', { className: 'logo', style: { cursor:'pointer', display:'flex', alignItems:'center', gap:8 }, onClick: function() { setCurrentPage('home'); } },
                    React.createElement('img', { src: '/img/logo_dark.png', alt: 'META INC', style: { height:28, width:'auto', display:'block' } }),
                    React.createElement('span', { style: _versionBadge }, APP_VERSION),
                    (activePage === 'analysis' || activePage === 'home') && health && React.createElement('span', { style: _healthBadge }, '● 정상')
                ),
                React.createElement('div', { className: 'topbar-nav-btns', style: { display:'flex', alignItems:'center', gap:6, flexWrap:'wrap' } },
                    React.createElement('button', { onClick: function(){setCurrentPage('home');}, style: navBtn(activePage === 'home') }, '🏠 대시보드'),
                    React.createElement('button', { onClick: function(){setCurrentPage('analysis');}, style: navBtn(activePage === 'analysis') }, '📊 스토어 분석'),
                    React.createElement('button', { onClick: function(){setCurrentPage('management');}, style: navBtn(activePage === 'management') }, '🏢 진행중 업체'),
                    React.createElement('button', { onClick: function(){setCurrentPage('guide');}, style: navBtn(activePage === 'guide') }, '📖 설명서'),
                    // 👥 직원 탭 제거 — SSO(ERP 연동)로 계정 자동 관리, 로그인 이력/실행 건수는 ⚙️설정 탭으로 통합
                    currentUser.role === 'superadmin' && React.createElement('button', { onClick: function(){setCurrentPage('settings');}, style: navBtn(activePage === 'settings') }, '⚙️ 설정')
                ),
                React.createElement('div', { className: 'topbar-user-area', style: { display:'flex', alignItems:'center', gap:8 } },
                    React.createElement('span', { style: _navUserStyle }, currentUser.name || currentUser.username),
                    (function(){
                        var _r = currentUser.role;
                        var _label = _r === 'superadmin' ? '최고관리자' : _r === 'admin' ? '관리자' : _r === 'manager' ? '매니저' : '뷰어';
                        var _isAdmin = (_r === 'admin' || _r === 'superadmin');
                        var _bg = _isAdmin ? '#ede9fe' : _r === 'manager' ? '#dbeafe' : '#f1f5f9';
                        var _fg = _isAdmin ? '#6d28d9' : _r === 'manager' ? '#1d4ed8' : '#475569';
                        return React.createElement('span', { title: '내 권한', style: { fontSize:11, fontWeight:800, padding:'2px 9px', borderRadius:999, background:_bg, color:_fg, whiteSpace:'nowrap' } }, _label);
                    })()
                )
            )
        );
    };

    /* ==================== 홈에서 검색 시 분석 탭으로 전환하는 핸들러 ==================== */
    var handleHomeSearch = function(keyword, productUrl, inputCompanyName, htmlInput) {
        setCurrentClientId(null);
        setAutoSaveStatus('');
        setCurrentPage('analysis');
        handleSearch(keyword, productUrl, inputCompanyName, htmlInput);
    };

    /* ==================== 페이지별 콘텐츠 렌더링 ==================== */

    /* 홈 탭 — 업체 리스트 + 검색 */
    if (currentPage === 'home') return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            renderTopbar('home'),
            React.createElement(SearchBar, { onSearch: handleHomeSearch, loading: searchLoading, initialValues: searchBarInitial }),

            /* 업체 연동 자동저장 상태 배너 */
            currentClientId && autoSaveStatus && React.createElement('div', {
                style: {
                    background: autoSaveStatus === 'saved' ? '#dcfce7' : autoSaveStatus === 'error' ? '#fee2e2' : '#e0e7ff',
                    color: autoSaveStatus === 'saved' ? '#166534' : autoSaveStatus === 'error' ? '#991b1b' : '#3730a3',
                    padding: '10px 0', fontSize: 13, fontWeight: 600, textAlign: 'center',
                    borderBottom: '1px solid rgba(0,0,0,0.05)'
                }
            },
                autoSaveStatus === 'saving' ? '🔄 분석 완료 후 업체관리에 자동 저장됩니다...' :
                autoSaveStatus === 'saved' ? '✅ 업체관리 탭에 분석 기록이 자동 저장되었습니다' :
                autoSaveStatus === 'error' ? '⚠️ 자동 저장에 실패했습니다. 분석 완료 후 하단 "업체 등록/저장" 버튼을 이용해주세요' : ''
            ),

            /* 등록 업체 리스트 */
            React.createElement(window.ClientListSection, {
                onClientClick: handleClientClick,
                onNavigateToClient: handleNavigateToClient
            }),

            /* 푸터 */
            React.createElement('footer', { className: 'footer' },
                React.createElement('div', { className: 'container' },
                    '© 2026 메타아이앤씨 — 로직 분석 ' + APP_VERSION + ' | 네이버 쇼핑 키워드 분석 & 순위 추적'
                )
            )
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
    );

    if (currentPage === 'management') return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            renderTopbar('management'),
            React.createElement(window.ClientDashboard, {
                currentUser: currentUser,
                onRunAnalysis: handleClientClick,
                onDownloadReport: downloadSavedReport,
                initialSearch: managementInitialSearch,
                canEdit: currentUser.role !== 'viewer'
            })
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
    );

    if (currentPage === 'guide') return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            renderTopbar('guide'),
            React.createElement(window.UserGuidePage, { currentUser: currentUser })
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
    );

    if (currentPage === 'users' && (currentUser.role === 'admin' || currentUser.role === 'superadmin')) return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            renderTopbar('users'),
            React.createElement(window.UserManagementPage, { currentUser: currentUser, token: authToken })
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
    );

    if (currentPage === 'settings' && currentUser.role === 'superadmin') return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            renderTopbar('settings'),
            React.createElement('div', { style: { maxWidth: 1000, margin: '0 auto', padding: '24px 16px' } },
                React.createElement(window.AnalysisStatsSection, null),
                React.createElement(ApiUsageSection, null),
                React.createElement(NotificationSection, null),
                React.createElement(window.ClientDiagnosticsSection, null),
                React.createElement(window.FeedbackManagement, null)
            )
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
    );

    /* ==================== 메인 분석 페이지 ==================== */
    return (
        React.createElement(React.Fragment, null,
        React.createElement('div', { className: 'analysis-page' },
            /* 네비게이션 바 */
            renderTopbar('analysis'),
            React.createElement(SearchBar, { onSearch: handleManualSearch, loading: searchLoading, initialValues: searchBarInitial }),

            /* 업체 연동 자동저장 상태 배너 */
            currentClientId && autoSaveStatus && React.createElement('div', {
                style: {
                    background: autoSaveStatus === 'saved' ? '#dcfce7' : autoSaveStatus === 'error' ? '#fee2e2' : '#e0e7ff',
                    color: autoSaveStatus === 'saved' ? '#166534' : autoSaveStatus === 'error' ? '#991b1b' : '#3730a3',
                    padding: '10px 0', fontSize: 13, fontWeight: 600, textAlign: 'center',
                    borderBottom: '1px solid rgba(0,0,0,0.05)'
                }
            },
                autoSaveStatus === 'saving' ? '🔄 분석 완료 후 업체관리에 자동 저장됩니다... (약 25초 대기)' :
                autoSaveStatus === 'saved' ? '✅ 업체관리 탭에 분석 기록이 자동 저장되었습니다' :
                autoSaveStatus === 'error' ? '⚠️ 자동 저장에 실패했습니다. 하단의 "업체 등록/저장" 버튼을 이용해주세요' : ''
            ),

            /* ==================== 보고서 레이아웃: 좌측 목차 + 본문 ==================== */
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
                            React.createElement('div', { className: 'rc-v' }, companyName || '-')
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

            /* [DATALAB] 로딩 인디케이터 */
            analysisData && !datalabData && datalabLoading && React.createElement('div', { className: 'section fade-in', style: { textAlign: 'center', padding: '24px 0' } },
                React.createElement('div', { className: 'container' },
                    React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, color: '#64748b', fontSize: 13 } },
                        React.createElement('div', { className: 'spinner-small' }),
                        '데이터랩 쇼핑인사이트 분석 중...'
                    )
                )
            ),

            /* 검색 전 안내 (아무 데이터도 없을 때) */
            !searchLoading && !analysisData && !volumeData && !searchedKeyword && React.createElement('div', { className: 'section' },
                React.createElement('div', { className: 'container' },
                    React.createElement('div', { style: { textAlign:'center', padding:'60px 20px', color:'#94a3b8' } },
                        React.createElement('img', { src: '/img/logo_light.png', alt: 'META INC', style: { height:40, width:'auto', marginBottom:16, opacity:0.45 } }),
                        React.createElement('div', { style: { fontSize:16, fontWeight:600, color:'#64748b', marginBottom:8 } }, '키워드를 입력하고 분석을 시작하세요'),
                        React.createElement('div', { style: { fontSize:13, color:'#94a3b8', lineHeight:1.6 } }, '상단 검색바에 키워드를 입력하면 검색량, 경쟁강도, 시장규모 등을 분석합니다.')
                    )
                )
            ),

            /* 검색 로딩 */
            searchLoading && React.createElement('div', { className: 'section' },
                React.createElement('div', { className: 'container' },
                    React.createElement('div', { style: { textAlign:'center', padding:'40px 20px' } },
                        React.createElement('span', { className:'spinner', style:{ width:32, height:32, borderWidth:3, marginBottom:16, display:'inline-block' } }),
                        React.createElement('div', { style: { fontSize:15, fontWeight:600, color:'#4f46e5', marginBottom:6 } }, '"' + searchedKeyword + '" 분석 중...'),
                        React.createElement('div', { style: { fontSize:13, color:'#94a3b8' } }, '검색량·경쟁강도·시장규모를 종합 분석하고 있습니다. 약 5~10초 소요됩니다.')
                    )
                )
            ),

            /* ==================== 보고서 6단계 흐름 (v6.0 — 광고주 발송용 재배치) ==================== */

            /* ========== 1. 종합 요약 ========== */
            analysisData && React.createElement(window.SectionDivider, { label: '1. 종합 요약', icon: '📋', color: '#4f46e5', sub: '광고주가 가장 먼저 보는 핵심 지표' }),

            analysisData && analysisData.summaryCards && React.createElement(window.SectionErrorBoundary, { name: '종합 요약' },
                React.createElement('div', { id: 'sec-summary' },
                    React.createElement(SummaryCardsSection, { data: analysisData.summaryCards })
                )
            ),

            /* ========== 2. 시장 · 수요 진단 ========== */
            analysisData && React.createElement(window.SectionDivider, { label: '2. 시장 · 수요 진단', icon: '📊', color: '#0ea5e9', sub: '검색량 · 트렌드 · 시즌 · 인구 · 요일 · 성장 · 시장규모' }),

            /* 키워드 검색량 */
            volumeData && React.createElement(window.SectionErrorBoundary, { name: '키워드 검색량' },
                React.createElement(KeywordVolumeSection, { keyword: searchedKeyword, data: volumeData })
            ),

            /* [DATALAB] 12개월 검색량 트렌드 (꺾은선) */
            datalabData && datalabData.trend && React.createElement(window.SectionErrorBoundary, { name: '검색량 트렌드' },
                React.createElement(window.DatalabTrendSection, { data: datalabData.trend })
            ),

            /* [DATALAB] 시즌별 수요 예측 */
            datalabData && datalabData.season && React.createElement(window.SectionErrorBoundary, { name: '시즌별 수요' },
                React.createElement(window.DatalabSeasonSection, { data: datalabData.season })
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
                    React.createElement(MarketRevenueSection, { data: analysisData.marketRevenue, reviewCount: (htmlReviewData && htmlReviewData.reviewCount) || (analysisData.reviewAnalysis && analysisData.reviewAnalysis.reviewCount ? analysisData.reviewAnalysis.reviewCount.adv : null), productPrice: analysisData.marketRevenue ? parseInt((analysisData.marketRevenue.avgPrice || '0').replace(/[^0-9]/g, '')) : 0 })
                )
            ),

            /* ========== 3. 경쟁 진단 ========== */
            analysisData && React.createElement(window.SectionDivider, { label: '3. 경쟁 진단', icon: '⚔️', color: '#ef4444', sub: '경쟁강도 · 광고경쟁 · 경쟁사 · 카테고리' }),

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

            /* 경쟁사 비교표 (상위 80개) */
            analysisData && analysisData.competitorTable && React.createElement(window.SectionErrorBoundary, { name: '경쟁사 비교표' },
                React.createElement(window.CompetitorTableSection, { data: analysisData.competitorTable })
            ),

            /* 카테고리 등록 분석 */
            analysisData && analysisData.categoryAnalysis && React.createElement(window.SectionErrorBoundary, { name: '카테고리 분석' },
                React.createElement(CategoryAnalysisSection, { data: analysisData.categoryAnalysis })
            ),

            /* ========== 4. 내 상품 현황 ========== */
            analysisData && React.createElement(window.SectionDivider, { label: '4. 내 상품 현황', icon: '🛒', color: '#059669', sub: '노출순위 · 판매추정 · 리뷰 · SEO 4종' }),

            /* 키워드별 노출 순위 */
            React.createElement(window.SectionErrorBoundary, { name: '순위 추적' },
                React.createElement(RankTrackingSection, { products: products, refreshProducts: loadProducts, searchedKeyword: searchedKeyword, searchedProductUrl: searchedProductUrl, cachedProductName: advertiserReport && advertiserReport.product_name ? advertiserReport.product_name : (analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo.product_name : null), relatedKeywords: (relatedData ? (relatedData.golden_keywords || []).concat(relatedData.related_keywords || []).map(function(k) { return typeof k === 'string' ? k : (k && k.keyword) || ''; }).filter(Boolean) : []), onNavigateToClient: handleNavigateToClient, canEdit: currentUser.role !== 'viewer', onRankResult: setRankCheckResult })
            ),

            /* 판매량 추정 */
            analysisData && analysisData.salesEstimation && React.createElement(window.SectionErrorBoundary, { name: '판매량 추정' },
                React.createElement('div', { id: 'sec-sales' },
                    React.createElement(SalesEstimationSection, { data: analysisData.salesEstimation, reviewCount: (htmlReviewData && htmlReviewData.reviewCount) || (analysisData.reviewAnalysis && analysisData.reviewAnalysis.reviewCount ? analysisData.reviewAnalysis.reviewCount.adv : null), productPrice: analysisData.marketRevenue ? parseInt((analysisData.marketRevenue.avgPrice || '0').replace(/[^0-9]/g, '')) : 0 })
                )
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
                    cachedProductName: advertiserReport && advertiserReport.product_name ? advertiserReport.product_name : (analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo.product_name : null),
                    cachedTotalVolume: volumeData && volumeData[0] ? ((volumeData[0].monthlyPcQcCnt || 0) + (volumeData[0].monthlyMobileQcCnt || 0)) : null,
                    cachedProductInfo: analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo : null,
                    shopProducts: shopProducts
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
            analysisData && React.createElement(window.SectionDivider, { label: '5. 기회 발굴', icon: '💎', color: '#7c3aed', sub: '연관키워드 · 골든키워드 · 상품명 최적화' }),

            /* 연관 키워드 */
            relatedData && React.createElement(window.SectionErrorBoundary, { name: '연관 키워드' },
                React.createElement(RelatedKeywordsSection, { data: relatedData })
            ),

            /* 골든 키워드 */
            analysisData && analysisData.goldenKeyword && React.createElement(window.SectionErrorBoundary, { name: '골든 키워드' },
                React.createElement('div', { id: 'sec-golden' },
                    React.createElement(GoldenKeywordCard, { data: analysisData.goldenKeyword })
                )
            ),

            /* 상품명 키워드 분석 (키워드&태그 통합) */
            searchedProductUrl && React.createElement(window.SectionErrorBoundary, { name: '상품명 분석' },
                React.createElement(ProductNameSection, { keyword: searchedKeyword, shopProducts: shopProducts })
            ),

            /* 상품명 SEO 최적화 제안 */
            analysisData && analysisData.productNameOpt && React.createElement(window.SectionErrorBoundary, { name: '상품명 최적화' },
                React.createElement(window.ProductNameOptSection, { data: analysisData.productNameOpt })
            ),

            /* ========== 6. 전략 · 결론 ========== */
            analysisData && React.createElement(window.SectionDivider, { label: '6. 전략 · 결론', icon: '🧭', color: '#1e293b', sub: '진입전략 · AI 종합 · 보고서 내보내기' }),

            /* 17. 1페이지 진입 전략 비교 분석 */
            (advertiserReport || (analysisData && analysisData.strategicAnalysis)) && !advertiserLoading && React.createElement(window.SectionErrorBoundary, { name: '진입 전략' },
                React.createElement(EntryStrategySection, {
                    advertiserData: advertiserReport,
                    strategicData: analysisData && analysisData.strategicAnalysis,
                    keyword: searchedKeyword,
                    rankCheckResult: rankCheckResult
                })
            ),

            /* 19. AI 종합 분석 리포트 */
            analysisData && React.createElement(window.SectionErrorBoundary, { name: 'AI 종합 분석' },
                React.createElement(AiFeedbackAllSection, {
                    keyword: searchedKeyword,
                    analysisData: analysisData,
                    volumeData: volumeData,
                    relatedData: relatedData,
                    advertiserReport: advertiserReport
                })
            ),

            /* 20. 업체 등록/저장 (viewer는 숨김) */
            analysisData && currentUser.role !== 'viewer' && React.createElement(window.SectionErrorBoundary, { name: '업체 저장' },
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
                })
            ),

            /* 21. 보고서 출력 */
            searchedProductUrl && React.createElement(window.SectionErrorBoundary, { name: '보고서' },
                React.createElement(ReportSection, { keyword: searchedKeyword, companyName: companyName })
            ),

            /* 알림 설정 (admin/superadmin만) */
            (currentUser.role === 'admin' || currentUser.role === 'superadmin') && React.createElement(window.SectionErrorBoundary, { name: '알림 설정' },
                React.createElement(NotificationSection, null)
            ),

            /* 푸터 */
            React.createElement('footer', { className: 'footer' },
                React.createElement('div', { className: 'container' },
                    '© 2026 메타아이앤씨 — 로직 분석 ' + APP_VERSION + ' | 네이버 쇼핑 키워드 분석 & 순위 추적'
                )
            )
              ) /* report-main 닫기 */
            ) /* report-shell 닫기 */
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
        )
    );
};

// 앱 렌더링 (ErrorBoundary로 감싸서 빈 화면 방지)
var root = ReactDOM.createRoot(document.getElementById('root'));
root.render(React.createElement(window.ErrorBoundary, null, React.createElement(App, null)));
