/* App — 메인 앱 컴포넌트 (v3 에이전시) */
/* APP_VERSION은 utils.js에서 전역 선언 */

/* ==================== 정적 스타일 (렌더 밖 — 매번 재생성 방지) ==================== */

window.App = function App() {
    const { useState, useEffect, useCallback } = React;

    /* ==================== 인증 상태 ==================== */
    const [currentUser, setCurrentUser] = useState(null);
    const [authToken, setAuthToken] = useState(null);
    const [authChecking, setAuthChecking] = useState(true);
    // URL hash에서 현재 페이지 복원 (새로고침 시 탭 유지)
    var _getPageFromHash = function() {
        var hash = window.location.hash.replace('#', '');
        var validPages = ['home', 'place', 'analysis', 'management', 'learning', 'guide', 'settings'];
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
    const [auditStatus, setAuditStatus] = useState(null);   // 🔍 데이터 검수 상태
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
            // 기존 세션 복원 (SSO 실패 시 폴백으로도 사용 — 오래된 sso 토큰이 유효 세션을 밀어내지 않게)
            var _restoreSession = function() {
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
            };
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
                            setAuthChecking(false);
                        } else {
                            _restoreSession(); // SSO 토큰 만료·검증 실패 → 기존 세션이 있으면 그대로 유지
                        }
                    }).catch(function() { _cleanUrl(); _restoreSession(); });
                return; // SSO 처리로 분기
            }
            _restoreSession();
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

    /* 🧩 크롬 확장 브리지 — 확장이 수집한 상품 HTML 수신 → 검색바 자동 주입·분석 자동 시작.
       확장 미설치·미사용 시 이 리스너는 아무 일도 하지 않음(기존 흐름 무영향). */
    const currentUserRef = React.useRef(null);
    currentUserRef.current = currentUser;
    const extSearchRef = React.useRef(null);   // handleHomeSearch 최신본 (정의 이후 갱신)
    const lastCaptureRef = React.useRef(0);    // 같은 수집물 중복 처리 방지
    useEffect(function() {
        var onExtMsg = function(ev) {
            if (ev.source !== window || !ev.data || ev.data.type !== 'METAINC_EXT_CAPTURE') return;
            if (!currentUserRef.current) return;                 // 로그인 전 — 확장이 30초간 재시도
            var p = ev.data.payload || {};
            var html = String(p.html || '');
            if (html.length < 1000) return;                      // 비정상 수집물 무시
            var capId = Number(p.captured_at) || 0;
            if (capId && capId === lastCaptureRef.current) return;
            lastCaptureRef.current = capId || Date.now();
            window.postMessage({ type: 'METAINC_EXT_ACK' }, window.location.origin);
            try { toast.success('🧩 확장 수신: 상품 HTML ' + Math.round(html.length / 1024) + 'KB'); } catch (e) {}
            var kw = String(p.keyword || '').trim();
            if (kw && extSearchRef.current) {
                extSearchRef.current(kw, String(p.product_url || ''), html);   // 분석 자동 시작
            } else {
                setSearchBarInitial({ keyword: kw, companyName: String(p.product_name || ''), html: html, productUrl: String(p.product_url || '') });
                setCurrentPage('home');
                try { toast.info('키워드 입력 후 분석 실행을 눌러주세요.'); } catch (e) {}
            }
        };
        window.addEventListener('message', onExtMsg);
        return function() { window.removeEventListener('message', onExtMsg); };
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
                    toast.error('일일 분석 제한(15회)을 초과했습니다. 내일 자정에 초기화됩니다.');
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

    var _doSearch = window.createDoSearch({
        cleanProductUrl: cleanProductUrl,
        lastHtmlRef: lastHtmlRef,
        products: products,
        searchIdRef: searchIdRef,
        setAdvertiserLoading: setAdvertiserLoading,
        setAdvertiserReport: setAdvertiserReport,
        setAnalysisData: setAnalysisData,
        setCompanyName: setCompanyName,
        setDatalabData: setDatalabData,
        setDatalabLoading: setDatalabLoading,
        setAuditStatus: setAuditStatus,
        setHtmlDetailResult: setHtmlDetailResult,
        setHtmlReviewData: setHtmlReviewData,
        setRankCheckResult: setRankCheckResult,
        setRelatedData: setRelatedData,
        setSearchLoading: setSearchLoading,
        setSearchedKeyword: setSearchedKeyword,
        setSearchedProductUrl: setSearchedProductUrl,
        setShopProducts: setShopProducts,
        setVolumeData: setVolumeData
    });

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

    /* DOM 캡처 — 자동 저장/저장 보고서 다운로드용 HTML 생성
     * 공용 빌더(ReportCapture) 사용: 수동 내보내기(ReportSection)와 완전히 동일한 제거 규칙·표지·푸터 적용 */
    var captureAutoReportHtml = function(kw) {
        try {
            if (!window.ReportCapture) return '';
            return window.ReportCapture.buildHtml({
                title: (kw || '키워드') + ' 분석 보고서',
                managerName: currentUser && currentUser.name
            });
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



    /* ==================== 홈에서 검색 시 분석 탭으로 전환하는 핸들러 ==================== */
    var handleHomeSearch = function(keyword, productUrl, inputCompanyName, htmlInput) {
        setCurrentClientId(null);
        setAutoSaveStatus('');
        setCurrentPage('analysis');
        handleSearch(keyword, productUrl, inputCompanyName, htmlInput);
    };
    // 크롬 확장 브리지에서 자동 분석 시작에 사용(최신 클로저 유지)
    extSearchRef.current = function(kw, url, html) { handleHomeSearch(kw, url, undefined, html); };

    /* ==================== 페이지별 콘텐츠 렌더링 ==================== */

    /* 홈 탭 — 업체 리스트 + 검색 */
    if (currentPage === 'home') return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            React.createElement(window.TopBar, { activePage: 'home', currentUser: currentUser, health: health, onNavigate: setCurrentPage }),
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
                currentUser: currentUser,
                onClientClick: handleClientClick,
                onNavigateToClient: handleNavigateToClient
            }),

            /* 푸터 */
            React.createElement(window.Footer, null)
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
    );

    if (currentPage === 'management') return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            React.createElement(window.TopBar, { activePage: 'management', currentUser: currentUser, health: health, onNavigate: setCurrentPage }),
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

    /* 플레이스 분석 탭 — 오프라인·지역 업종(자체완결 페이지, 스토어 분석 흐름과 독립) */
    if (currentPage === 'place') return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            React.createElement(window.TopBar, { activePage: 'place', currentUser: currentUser, health: health, onNavigate: setCurrentPage }),
            React.createElement(window.PlaceAnalysisPage, { currentUser: currentUser })
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
    );

    if (currentPage === 'learning') return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            React.createElement(window.TopBar, { activePage: 'learning', currentUser: currentUser, health: health, onNavigate: setCurrentPage }),
            React.createElement(window.LearningCenterPage, { currentUser: currentUser })
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
    );

    if (currentPage === 'guide') return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            React.createElement(window.TopBar, { activePage: 'guide', currentUser: currentUser, health: health, onNavigate: setCurrentPage }),
            React.createElement(window.UserGuidePage, { currentUser: currentUser })
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
    );

    if (currentPage === 'users' && (currentUser.role === 'admin' || currentUser.role === 'superadmin')) return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            React.createElement(window.TopBar, { activePage: 'users', currentUser: currentUser, health: health, onNavigate: setCurrentPage }),
            React.createElement(window.UserManagementPage, { currentUser: currentUser, token: authToken })
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
    );

    if (currentPage === 'settings' && currentUser.role === 'superadmin') return React.createElement(React.Fragment, null,
        React.createElement('div', null,
            React.createElement(window.TopBar, { activePage: 'settings', currentUser: currentUser, health: health, onNavigate: setCurrentPage }),
            React.createElement('div', { style: { maxWidth: 1000, margin: '0 auto', padding: '24px 16px' } },
                React.createElement(window.AnalysisStatsSection, null),
                React.createElement(ApiUsageSection, null),
                React.createElement(NotificationSection, null),
                React.createElement(window.ManagerReassignSection, null),
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
            React.createElement(window.TopBar, { activePage: 'analysis', currentUser: currentUser, health: health, onNavigate: setCurrentPage }),
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
            React.createElement(window.AnalysisResults, {
                advertiserLoading: advertiserLoading,
                advertiserReport: advertiserReport,
                analysisData: analysisData,
                companyName: companyName,
                currentUser: currentUser,
                datalabData: datalabData,
                datalabLoading: datalabLoading,
                auditStatus: auditStatus,
                handleNavigateToClient: handleNavigateToClient,
                htmlDetailResult: htmlDetailResult,
                htmlReviewData: htmlReviewData,
                lastHtmlRef: lastHtmlRef,
                loadProducts: loadProducts,
                products: products,
                rankCheckResult: rankCheckResult,
                relatedData: relatedData,
                scrollTo: scrollTo,
                searchLoading: searchLoading,
                searchedKeyword: searchedKeyword,
                searchedProductUrl: searchedProductUrl,
                sections: sections,
                setRankCheckResult: setRankCheckResult,
                shopProducts: shopProducts,
                volumeData: volumeData
            })
        ),
        React.createElement(window.ChatWidget, { currentUser: currentUser })
        )
    );
};

// 앱 렌더링 (ErrorBoundary로 감싸서 빈 화면 방지)
var root = ReactDOM.createRoot(document.getElementById('root'));
root.render(React.createElement(window.ErrorBoundary, null, React.createElement(App, null)));
