/* App — 메인 앱 컴포넌트 (v3 에이전시) */
window.App = function App() {
    const { useState, useEffect, useCallback } = React;

    /* ==================== 인증 상태 ==================== */
    const [currentUser, setCurrentUser] = useState(null);
    const [authToken, setAuthToken] = useState(null);
    const [authChecking, setAuthChecking] = useState(true);
    const [currentPage, setCurrentPage] = useState('analysis');

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
    const [searchedProductUrl, setSearchedProductUrl] = useState('');
    const [companyName, setCompanyName] = useState('');

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

    if (authChecking) return React.createElement('div', { style: { display:'flex', justifyContent:'center', alignItems:'center', height:'100vh', background:'linear-gradient(135deg,#6C5CE7,#a29bfe)' } },
        React.createElement('div', { style: { color:'#fff', fontSize:18 } }, '로딩 중...'));
    if (!currentUser) return React.createElement(window.LoginPage, { onLogin: saveAuth });

    // 통합 검색
    var handleSearch = function(keyword, productUrl, inputCompanyName) {
        if (inputCompanyName !== undefined) setCompanyName(inputCompanyName);
        setSearchLoading(true);
        setSearchedKeyword(keyword);
        setSearchedProductUrl(productUrl || '');
        setVolumeData(null);
        setRelatedData(null);
        setAnalysisData(null);
        setShopProducts(null);
        setAdvertiserReport(null);

        // 광고주 상품 URL이 있으면 광고주 분석 API 호출
        if (productUrl) {
            setAdvertiserLoading(true);
            api.post('/advertiser/analyze', { keyword: keyword, product_url: productUrl })
                .then(function(res) {
                    if (res && res.success) setAdvertiserReport(res.data);
                    setAdvertiserLoading(false);
                })
                .catch(function() { setAdvertiserLoading(false); });
        }

        // 병렬로 3개 API 호출
        Promise.all([
            api.post('/keyword/volume', [keyword]).catch(function() { return null; }),
            api.post('/keywords/related', { keyword: keyword }).catch(function() { return null; }),
            api.post('/products/search', { keyword: keyword, count: 40 }).catch(function() { return null; }),
        ]).then(function(results) {
            var volRes = results[0];
            var relRes = results[1];
            var shopRes = results[2];

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

                // 순위별 CTR (업계 벤치마크)
                var getCTR = function(rank) {
                    if (rank === 1) return 0.08;
                    if (rank === 2) return 0.06;
                    if (rank === 3) return 0.05;
                    if (rank === 4) return 0.04;
                    if (rank === 5) return 0.03;
                    if (rank <= 10) return 0.015;
                    if (rank <= 20) return 0.008;
                    if (rank <= 40) return 0.003;
                    return 0.001;
                };
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

                // 전체 시장 규모 = 상위 20개 상품 추정 매출 합산
                var totalMarketRevenue = topProductsList.slice(0, 20).reduce(function(sum, p) {
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
                    mainDifficulty: (analysis.competitionIndex && analysis.competitionIndex.compIndex < 0.5) ? '쉬움' : (analysis.competitionIndex && analysis.competitionIndex.compIndex < 1.0) ? '보통' : '어려움',
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

            // 7. 카테고리 분석
            if (prods.length > 0) {
                var catMap = {};
                prods.forEach(function(p) {
                    var cat = p.category2 || p.category1 || '기타';
                    catMap[cat] = (catMap[cat] || 0) + 1;
                });
                var categories = Object.keys(catMap).map(function(k) {
                    return { name: k, count: catMap[k], ratio: Math.round(catMap[k] / prods.length * 100) };
                }).sort(function(a, b) { return b.count - a.count; });
                var topCat = categories[0] || { name: '-', ratio: 0 };
                analysis.categoryAnalysis = {
                    verdict: topCat.name + ' 카테고리에 ' + topCat.ratio + '% 등록',
                    mainCategory: topCat.name,
                    categories: categories.slice(0, 8),
                };
            }

            // 8. 키워드 & 태그 분석
            if (rd) {
                var allKws = (rd.golden_keywords || []).concat(rd.related_keywords || []);
                analysis.keywordTags = {
                    topKeywords: allKws.slice(0, 15).map(function(k) {
                        return { keyword: k.keyword, volume: fmt(k.totalVolume), comp: compLabel(k.compIdx), isGolden: k.isGolden };
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
                prods.slice(0, 20).forEach(function(p) {
                    var cat = p.category2 || p.category1 || '';
                    if (cat) catCounts[cat] = (catCounts[cat] || 0) + 1;
                });
                var topCat = '';
                var topCatCount = 0;
                Object.keys(catCounts).forEach(function(k) { if (catCounts[k] > topCatCount) { topCat = k; topCatCount = catCounts[k]; } });

                analysis.competitorTable = prods.slice(0, 20).map(function(p) {
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

            // 10. 판매량 추정 & 성장 시뮬레이션 (CTR × 전환율 3.5% 통일)
            if (prods.length > 0 && totalVol > 0) {
                var top10 = prods.slice(0, 10);
                var avgP = Math.round(top10.reduce(function(s, p) { return s + p.price; }, 0) / top10.length);
                var cv = 0.035; // 전환율 3.5%
                analysis.salesEstimation = {
                    avgPrice: fmt(avgP) + '원',
                    monthlySearches: fmt(totalVol),
                    estimatedCTR: 'CTR × 3.5%',
                    simulations: [
                        { rank: 1, estSales: Math.round(totalVol * 0.08 * cv), revenue: fmt(Math.round(totalVol * 0.08 * cv * avgP)) + '원' },
                        { rank: 5, estSales: Math.round(totalVol * 0.03 * cv), revenue: fmt(Math.round(totalVol * 0.03 * cv * avgP)) + '원' },
                        { rank: 10, estSales: Math.round(totalVol * 0.015 * cv), revenue: fmt(Math.round(totalVol * 0.015 * cv * avgP)) + '원' },
                        { rank: 20, estSales: Math.round(totalVol * 0.008 * cv), revenue: fmt(Math.round(totalVol * 0.008 * cv * avgP)) + '원' },
                    ],
                };
            }

            // 11. 1페이지 진입 전략 비교
            if (prods.length >= 10 && totalVol > 0) {
                var top5 = prods.slice(0, 5);
                var avgTop5Price = Math.round(top5.reduce(function(s, p) { return s + p.price; }, 0) / 5);
                analysis.strategicAnalysis = {
                    avgTop5Price: fmt(avgTop5Price) + '원',
                    priceRange: fmt(Math.min.apply(null, top5.map(function(p) { return p.price; }))) + '원 ~ ' + fmt(Math.max.apply(null, top5.map(function(p) { return p.price; }))) + '원',
                    monthlyVolume: fmt(totalVol),
                    mainBrands: (function() {
                        var brands = {};
                        top5.forEach(function(p) { var b = p.brand || p.store_name; brands[b] = (brands[b] || 0) + 1; });
                        return Object.keys(brands).slice(0, 5).join(', ');
                    })(),
                    recommendation: analysis.competitionIndex && analysis.competitionIndex.compIndex < 0.5
                        ? '현재 시장은 블루오션입니다. 빠른 진입을 추천합니다.'
                        : analysis.competitionIndex && analysis.competitionIndex.compIndex < 1.0
                        ? '경쟁이 적당합니다. 가격/리뷰 전략에 집중하세요.'
                        : '경쟁이 치열합니다. 차별화된 상세페이지와 리뷰 확보가 핵심입니다.',
                };
            }

            setAnalysisData(Object.keys(analysis).length > 0 ? analysis : null);
            setSearchLoading(false);
        }).catch(function(e) {
            console.error('검색 오류:', e);
            setSearchLoading(false);
        });
    };

    // 앵커 네비게이션
    var sections = [
        { id: 'sec-strategy', label: '진입전략', show: !!(advertiserReport || advertiserLoading || (analysisData && analysisData.strategicAnalysis)) },
        { id: 'sec-rank', label: '순위 추적' },
        { id: 'sec-volume', label: '검색량', show: !!volumeData },
        { id: 'sec-competition', label: '경쟁강도', show: !!(analysisData && analysisData.competitionIndex) },
        { id: 'sec-market', label: '시장규모', show: !!(analysisData && analysisData.marketRevenue) },
        { id: 'sec-related', label: '연관 키워드', show: !!relatedData },
        { id: 'sec-trend', label: '트렌드', show: !!(analysisData && analysisData.keywordTrend) },
        { id: 'sec-golden', label: '골든키워드', show: !!(analysisData && analysisData.goldenKeyword) },
        { id: 'sec-competitor', label: '경쟁사', show: !!(analysisData && analysisData.competitorTable) },
        { id: 'sec-sales', label: '판매추정', show: !!(analysisData && analysisData.salesEstimation) },
        { id: 'sec-seo', label: 'SEO 진단' },
        { id: 'sec-productname', label: '상품명 분석' },
        { id: 'sec-report', label: '보고서' },
        { id: 'sec-notify', label: '알림' },
    ].filter(function(s) { return s.show !== false; });

    var scrollTo = function(id) {
        var el = document.getElementById(id);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    /* ==================== Topbar 공통 스타일 ==================== */
    var navBtn = function(active) {
        return { background: active ? 'rgba(59,130,246,0.9)' : 'rgba(255,255,255,0.08)', color: active ? '#fff' : 'rgba(255,255,255,0.75)', border: active ? 'none' : '1px solid rgba(255,255,255,0.12)', padding: '6px 14px', borderRadius: 8, cursor: 'pointer', fontSize: 13, fontWeight: active ? 600 : 400, transition: 'all 0.2s' };
    };
    var navUserStyle = { color: 'rgba(255,255,255,0.7)', fontSize: 13 };
    var navLogoutStyle = { background: 'rgba(239,68,68,0.15)', color: '#fca5a5', border: '1px solid rgba(239,68,68,0.2)', padding: '6px 14px', borderRadius: 8, cursor: 'pointer', fontSize: 13 };

    var renderTopbar = function(activePage) {
        return React.createElement('div', { className: 'topbar' },
            React.createElement('div', { className: 'container', style: { display:'flex', alignItems:'center', justifyContent:'space-between', height: 56 } },
                React.createElement('div', { style: { display:'flex', alignItems:'center', gap:14 } },
                    React.createElement('span', { style: { fontSize:18, fontWeight:700, color:'#fff', cursor:'pointer', letterSpacing:'-0.02em' }, onClick: function() { setCurrentPage('analysis'); } }, '🔍 로직 분석'),
                    React.createElement('span', { style: { fontSize:11, color:'rgba(255,255,255,0.4)', background:'rgba(255,255,255,0.06)', padding:'2px 8px', borderRadius:10 } }, 'v3.0'),
                    activePage === 'analysis' && health && React.createElement('span', { style: { background:'rgba(16,185,129,0.2)', color:'#34d399', fontSize:11, padding:'2px 8px', borderRadius:10 } }, '● 정상'),
                    React.createElement('button', { onClick: function(){setCurrentPage('analysis');}, style: navBtn(activePage === 'analysis') }, '📊 분석'),
                    React.createElement('button', { onClick: function(){setCurrentPage('management');}, style: navBtn(activePage === 'management') }, '🏢 업체관리'),
                    (currentUser.role === 'admin' || currentUser.role === 'superadmin') && React.createElement('button', { onClick: function(){setCurrentPage('users');}, style: navBtn(activePage === 'users') }, '👥 직원')
                ),
                React.createElement('div', { style: { display:'flex', alignItems:'center', gap:12 } },
                    React.createElement('span', { style: navUserStyle }, currentUser.name || currentUser.username),
                    React.createElement('button', { onClick: clearAuth, style: navLogoutStyle }, '로그아웃')
                )
            )
        );
    };

    /* ==================== 페이지별 콘텐츠 렌더링 ==================== */
    if (currentPage === 'management') return React.createElement('div', null,
        renderTopbar('management'),
        React.createElement(window.ClientDashboard, { currentUser: currentUser, token: authToken })
    );

    if (currentPage === 'users' && (currentUser.role === 'admin' || currentUser.role === 'superadmin')) return React.createElement('div', null,
        renderTopbar('users'),
        React.createElement(window.UserManagementPage, { currentUser: currentUser, token: authToken })
    );

    /* ==================== 메인 분석 페이지 ==================== */
    return (
        React.createElement('div', null,
            /* 네비게이션 바 */
            renderTopbar('analysis'),
            React.createElement(SearchBar, { onSearch: handleSearch, loading: searchLoading }),

            /* 앵커 네비 */
            React.createElement('div', { style: { background: '#fff', borderBottom: '1px solid #e8ecf1', padding: '10px 0' } },
                React.createElement('div', { className: 'container' },
                    React.createElement('div', { className: 'anchor-nav' },
                        sections.map(function(s) {
                            return React.createElement('button', { key: s.id, className: 'anchor-btn', onClick: function() { scrollTo(s.id); } }, s.label);
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

            /* 순위 추적 */
            React.createElement(RankTrackingSection, { products: products, refreshProducts: loadProducts, searchedKeyword: searchedKeyword, searchedProductUrl: searchedProductUrl }),

            /* 종합 요약 카드 */
            analysisData && analysisData.summaryCards && React.createElement('div', { id: 'sec-summary' },
                React.createElement(SummaryCardsSection, { data: analysisData.summaryCards })
            ),

            /* 대시보드 요약 */
            React.createElement(DashboardSummary, { products: products, searchResult: relatedData }),

            /* 검색 로딩 */
            searchLoading && React.createElement('div', { className: 'section' },
                React.createElement('div', { className: 'container' },
                    React.createElement(LoadingSpinner, { text: '"' + searchedKeyword + '" 분석 중... 약 5~10초 소요됩니다' })
                )
            ),

            /* 광고주 정보 */
            analysisData && analysisData.advertiserInfo && React.createElement(AdvertiserInfoCard, { data: analysisData.advertiserInfo }),

            /* 키워드 검색량 */
            volumeData && React.createElement('div', null,
                React.createElement(KeywordVolumeSection, { keyword: searchedKeyword, data: volumeData }),
                React.createElement('div', { className: 'container' },
                    React.createElement(AiFeedbackCard, { section: 'volume', keyword: searchedKeyword, data: volumeData, autoDelay: 3000 })
                )
            ),

            /* 시장 규모 추정 */
            analysisData && analysisData.marketRevenue && React.createElement('div', { id: 'sec-market' },
                React.createElement(MarketRevenueSection, { data: analysisData.marketRevenue }),
                React.createElement('div', { className: 'container' },
                    React.createElement(AiFeedbackCard, { section: 'market', keyword: searchedKeyword, data: analysisData.marketRevenue, autoDelay: 5000 })
                )
            ),

            /* 경쟁강도 분석 */
            analysisData && analysisData.competitionIndex && React.createElement('div', { id: 'sec-competition' },
                React.createElement(CompetitionIndexSection, { data: analysisData.competitionIndex }),
                React.createElement('div', { className: 'container' },
                    React.createElement(AiFeedbackCard, { section: 'competition', keyword: searchedKeyword, data: analysisData.competitionIndex, autoDelay: 7000 })
                )
            ),

            /* 연관 키워드 */
            relatedData && React.createElement('div', null,
                React.createElement(RelatedKeywordsSection, { data: relatedData }),
                React.createElement('div', { className: 'container' },
                    React.createElement(AiFeedbackCard, { section: 'related', keyword: searchedKeyword, data: relatedData, autoDelay: 9000 })
                )
            ),

            /* 키워드 트렌드 */
            analysisData && analysisData.keywordTrend && React.createElement('div', { id: 'sec-trend' },
                React.createElement(KeywordTrendSection, { data: analysisData.keywordTrend }),
                React.createElement('div', { className: 'container' },
                    React.createElement(AiFeedbackCard, { section: 'trend', keyword: searchedKeyword, data: analysisData.keywordTrend, autoDelay: 11000 })
                )
            ),

            /* 골든 키워드 */
            analysisData && analysisData.goldenKeyword && React.createElement('div', { id: 'sec-golden' },
                React.createElement(GoldenKeywordCard, { data: analysisData.goldenKeyword }),
                React.createElement('div', { className: 'container' },
                    React.createElement(AiFeedbackCard, { section: 'golden', keyword: searchedKeyword, data: analysisData.goldenKeyword, autoDelay: 13000 })
                )
            ),

            /* SEO 진단 */
            React.createElement('div', null,
                React.createElement(SeoDiagnosisSection, { keyword: searchedKeyword, productUrl: searchedProductUrl })
            ),

            /* 경쟁사 비교표 */
            analysisData && analysisData.competitorTable && React.createElement('div', { id: 'sec-competitor' },
                React.createElement(CompetitorTableSection, { data: analysisData.competitorTable }),
                React.createElement('div', { className: 'container' },
                    React.createElement(AiFeedbackCard, { section: 'competitor', keyword: searchedKeyword, data: analysisData.competitorTable, autoDelay: 15000 })
                )
            ),

            /* 판매량 추정 */
            analysisData && analysisData.salesEstimation && React.createElement('div', { id: 'sec-sales' },
                React.createElement(SalesEstimationSection, { data: analysisData.salesEstimation }),
                React.createElement('div', { className: 'container' },
                    React.createElement(AiFeedbackCard, { section: 'sales', keyword: searchedKeyword, data: analysisData.salesEstimation, autoDelay: 17000 })
                )
            ),

            /* 상품명 분석 */
            React.createElement(ProductNameSection, { keyword: searchedKeyword, shopProducts: shopProducts }),

            /* 카테고리 분석 */
            analysisData && analysisData.categoryAnalysis && React.createElement(CategoryAnalysisSection, { data: analysisData.categoryAnalysis }),

            /* 키워드 & 태그 분석 */
            analysisData && analysisData.keywordTags && React.createElement(KeywordTagSection, { data: analysisData.keywordTags }),

            /* 1페이지 진입 전략 비교 분석 (통합) */
            (advertiserReport || (analysisData && analysisData.strategicAnalysis)) && !advertiserLoading && React.createElement('div', null,
                React.createElement(EntryStrategySection, {
                    advertiserData: advertiserReport,
                    strategicData: analysisData && analysisData.strategicAnalysis,
                    keyword: searchedKeyword
                }),
                React.createElement('div', { className: 'container' },
                    React.createElement(AiFeedbackCard, {
                        section: 'strategy',
                        keyword: searchedKeyword,
                        data: { advertiserReport: advertiserReport, strategicAnalysis: analysisData && analysisData.strategicAnalysis },
                        autoDelay: 20000
                    })
                )
            ),

            /* 업체 등록/저장 */
            analysisData && React.createElement(SaveToClientSection, {
                keyword: searchedKeyword,
                productUrl: searchedProductUrl,
                analysisData: analysisData,
                volumeData: volumeData,
                relatedData: relatedData,
                shopProducts: shopProducts,
                advertiserReport: advertiserReport,
            }),

            /* 보고서 */
            React.createElement(ReportSection, { keyword: searchedKeyword, companyName: companyName }),

            /* 알림 설정 */
            React.createElement(NotificationSection, null),

            /* 푸터 */
            React.createElement('footer', { className: 'footer' },
                React.createElement('div', { className: 'container' },
                    '© 2026 메타아이앤씨 — 로직 분석 v3.6 | 네이버 쇼핑 키워드 분석 & 순위 추적'
                )
            )
        )
    );
};

// 앱 렌더링
var root = ReactDOM.createRoot(document.getElementById('root'));
root.render(React.createElement(App, null));
