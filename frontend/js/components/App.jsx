/* App — 메인 앱 컴포넌트 */
window.App = function App() {
    const { useState, useEffect, useCallback } = React;
    const [health, setHealth] = useState(false);
    const [products, setProducts] = useState([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [searchedKeyword, setSearchedKeyword] = useState('');

    // 검색 결과
    const [volumeData, setVolumeData] = useState(null);
    const [relatedData, setRelatedData] = useState(null);

    // 종합 분석 결과
    const [analysisData, setAnalysisData] = useState(null);

    // 상품 검색 결과 (상위 40개)
    const [shopProducts, setShopProducts] = useState(null);

    // 헬스체크
    useEffect(function() {
        api.get('/health').then(function(res) { setHealth(res.status === 'ok'); }).catch(function() { setHealth(false); });
    }, []);

    // 상품 목록 로드
    var loadProducts = useCallback(function() {
        api.get('/products').then(function(res) {
            if (res.success) setProducts(res.data);
        }).catch(function() {});
    }, []);

    useEffect(function() { loadProducts(); }, [loadProducts]);

    // 통합 검색
    var handleSearch = function(keyword) {
        setSearchLoading(true);
        setSearchedKeyword(keyword);
        setVolumeData(null);
        setRelatedData(null);
        setAnalysisData(null);
        setShopProducts(null);

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

            // 1. 경쟁강도 계산
            if (productCount > 0 && totalVol > 0) {
                var compIdx = (productCount / totalVol).toFixed(2);
                var compLevel = compIdx < 0.5 ? '블루오션 (진입 적기)' : compIdx < 1.0 ? '보통 (경쟁 중간)' : '레드오션 (경쟁 치열)';
                var compColor = compIdx < 0.5 ? '#16a34a' : compIdx < 1.0 ? '#d97706' : '#dc2626';
                analysis.competitionIndex = {
                    compIndex: compIdx,
                    compLabel: compLevel,
                    compColor: compColor,
                    productCount: fmt(productCount) + '개',
                    searchVolume: fmt(totalVol) + '회/월',
                    avgCtr: vol ? ((vol.monthlyAvePcClkCnt || 0) + (vol.monthlyAveMobileClkCnt || 0)).toFixed(1) + '회' : '-',
                    interpretation: compIdx < 0.5
                        ? '시장에 상품이 부족한 상태입니다. 지금이 시장 진입의 최고 기회입니다.'
                        : compIdx < 1.0
                        ? '경쟁이 적당한 시장입니다. 차별화 전략으로 진입이 가능합니다.'
                        : '경쟁이 치열한 시장입니다. 명확한 차별화 포인트가 필요합니다.',
                };
            }

            // 2. 시장 규모 추정
            if (prods.length > 0) {
                var prices = prods.map(function(p) { return p.price; }).filter(function(p) { return p > 0; });
                var avgPrice = prices.length > 0 ? Math.round(prices.reduce(function(a, b) { return a + b; }, 0) / prices.length) : 0;
                var estimatedMarketSize = avgPrice * totalVol;
                analysis.marketRevenue = {
                    avgPrice: fmt(avgPrice) + '원',
                    estimatedMonthly: fmt(estimatedMarketSize) + '원',
                    topProducts: prods.slice(0, 40).map(function(p) {
                        var estSales = Math.max(1, Math.round(totalVol / Math.pow(p.rank, 0.8) * 0.1));
                        return {
                            rank: p.rank,
                            name: p.product_name,
                            store: p.store_name,
                            price: fmt(p.price) + '원',
                            estMonthlySales: fmt(estSales) + '건',
                            estRevenue: fmt(p.price * estSales) + '원',
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

            // 4. 골든 키워드
            if (rd && rd.golden_keywords && rd.golden_keywords.length > 0) {
                var gk = rd.golden_keywords[0];
                analysis.goldenKeyword = {
                    name: gk.keyword,
                    score: gk.score || (gk.totalVolume ? Math.round(gk.totalVolume / 100) : 0),
                    volume: fmt(gk.totalVolume),
                    competition: compLabel(gk.compIdx),
                    ctr: gk.monthlyAvePcClkCnt ? (gk.monthlyAvePcClkCnt + gk.monthlyAveMobileClkCnt).toFixed(1) + '회' : '-',
                    clicks: fmt(Math.round((gk.totalVolume || 0) * 0.05)),
                    reason: '검색량 ' + fmt(gk.totalVolume) + '회로 틈새 수요가 확실합니다. 경쟁강도가 낮아 진입하기 좋은 키워드입니다.',
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

            // 9. 경쟁사 비교표
            if (prods.length > 0) {
                analysis.competitorTable = prods.slice(0, 20).map(function(p) {
                    return {
                        rank: p.rank,
                        name: p.product_name,
                        store: p.store_name,
                        price: fmt(p.price) + '원',
                        brand: p.brand || '-',
                        category: p.category2 || p.category1 || '-',
                        image: p.image_url,
                    };
                });
            }

            // 10. 판매량 추정 & 성장 시뮬레이션
            if (prods.length > 0 && totalVol > 0) {
                var top10 = prods.slice(0, 10);
                var avgP = Math.round(top10.reduce(function(s, p) { return s + p.price; }, 0) / top10.length);
                analysis.salesEstimation = {
                    avgPrice: fmt(avgP) + '원',
                    monthlySearches: fmt(totalVol),
                    estimatedCTR: '2~5%',
                    simulations: [
                        { rank: 1, estSales: Math.round(totalVol * 0.08), revenue: fmt(Math.round(totalVol * 0.08 * avgP)) + '원' },
                        { rank: 5, estSales: Math.round(totalVol * 0.03), revenue: fmt(Math.round(totalVol * 0.03 * avgP)) + '원' },
                        { rank: 10, estSales: Math.round(totalVol * 0.015), revenue: fmt(Math.round(totalVol * 0.015 * avgP)) + '원' },
                        { rank: 20, estSales: Math.round(totalVol * 0.008), revenue: fmt(Math.round(totalVol * 0.008 * avgP)) + '원' },
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
        { id: 'sec-rank', label: '순위 추적' },
        { id: 'sec-volume', label: '검색량', show: !!volumeData },
        { id: 'sec-competition', label: '경쟁강도', show: !!(analysisData && analysisData.competitionIndex) },
        { id: 'sec-market', label: '시장규모', show: !!(analysisData && analysisData.marketRevenue) },
        { id: 'sec-related', label: '연관 키워드', show: !!relatedData },
        { id: 'sec-trend', label: '트렌드', show: !!(analysisData && analysisData.keywordTrend) },
        { id: 'sec-golden', label: '골든키워드', show: !!(analysisData && analysisData.goldenKeyword) },
        { id: 'sec-competitor', label: '경쟁사', show: !!(analysisData && analysisData.competitorTable) },
        { id: 'sec-sales', label: '판매추정', show: !!(analysisData && analysisData.salesEstimation) },
        { id: 'sec-strategy', label: '진입전략', show: !!(analysisData && analysisData.strategicAnalysis) },
        { id: 'sec-seo', label: 'SEO 진단' },
        { id: 'sec-productname', label: '상품명 분석' },
        { id: 'sec-report', label: '보고서' },
        { id: 'sec-notify', label: '알림' },
    ].filter(function(s) { return s.show !== false; });

    var scrollTo = function(id) {
        var el = document.getElementById(id);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    return (
        React.createElement('div', null,
            React.createElement(TopBar, { health: health }),
            React.createElement(SearchBar, { onSearch: handleSearch, loading: searchLoading }),

            /* 앵커 네비 */
            React.createElement('div', { style: { background: '#fff', borderBottom: '1px solid #e8ecf1', padding: '10px 0', position: 'sticky', top: 64, zIndex: 40 } },
                React.createElement('div', { className: 'container' },
                    React.createElement('div', { className: 'anchor-nav' },
                        sections.map(function(s) {
                            return React.createElement('button', { key: s.id, className: 'anchor-btn', onClick: function() { scrollTo(s.id); } }, s.label);
                        })
                    )
                )
            ),

            /* 종합 요약 카드 (검색 후 표시) */
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

            /* 순위 추적 */
            React.createElement(RankTrackingSection, { products: products, refreshProducts: loadProducts }),

            /* 키워드 검색량 */
            volumeData && React.createElement(KeywordVolumeSection, { keyword: searchedKeyword, data: volumeData }),

            /* 경쟁강도 분석 */
            analysisData && analysisData.competitionIndex && React.createElement('div', { id: 'sec-competition' },
                React.createElement(CompetitionIndexSection, { data: analysisData.competitionIndex })
            ),

            /* 시장 규모 추정 */
            analysisData && analysisData.marketRevenue && React.createElement('div', { id: 'sec-market' },
                React.createElement(MarketRevenueSection, { data: analysisData.marketRevenue })
            ),

            /* 연관 키워드 */
            relatedData && React.createElement(RelatedKeywordsSection, { data: relatedData }),

            /* 키워드 트렌드 */
            analysisData && analysisData.keywordTrend && React.createElement('div', { id: 'sec-trend' },
                React.createElement(KeywordTrendSection, { data: analysisData.keywordTrend })
            ),

            /* 골든 키워드 */
            analysisData && analysisData.goldenKeyword && React.createElement('div', { id: 'sec-golden' },
                React.createElement(GoldenKeywordCard, { data: analysisData.goldenKeyword })
            ),

            /* 광고주 정보 */
            analysisData && analysisData.advertiserInfo && React.createElement(AdvertiserInfoCard, { data: analysisData.advertiserInfo }),

            /* 카테고리 분석 */
            analysisData && analysisData.categoryAnalysis && React.createElement(CategoryAnalysisSection, { data: analysisData.categoryAnalysis }),

            /* 키워드 & 태그 분석 */
            analysisData && analysisData.keywordTags && React.createElement(KeywordTagSection, { data: analysisData.keywordTags }),

            /* 경쟁사 비교표 */
            analysisData && analysisData.competitorTable && React.createElement('div', { id: 'sec-competitor' },
                React.createElement(CompetitorTableSection, { data: analysisData.competitorTable })
            ),

            /* 판매량 추정 */
            analysisData && analysisData.salesEstimation && React.createElement('div', { id: 'sec-sales' },
                React.createElement(SalesEstimationSection, { data: analysisData.salesEstimation })
            ),

            /* 진입 전략 */
            analysisData && analysisData.strategicAnalysis && React.createElement('div', { id: 'sec-strategy' },
                React.createElement(StrategicAnalysisSection, { data: analysisData.strategicAnalysis })
            ),

            /* SEO 진단 */
            React.createElement(SeoDiagnosisSection, { keyword: searchedKeyword }),

            /* 상품명 분석 */
            React.createElement(ProductNameSection, { keyword: searchedKeyword }),

            /* 보고서 */
            React.createElement(ReportSection, null),

            /* 알림 설정 */
            React.createElement(NotificationSection, null),

            /* 푸터 */
            React.createElement('footer', { className: 'footer' },
                React.createElement('div', { className: 'container' },
                    '© 2026 메타인크 — 로직 분석 v2.1 | 네이버 쇼핑 키워드 분석 & 순위 추적'
                )
            )
        )
    );
};

// 앱 렌더링
var root = ReactDOM.createRoot(document.getElementById('root'));
root.render(React.createElement(App, null));
