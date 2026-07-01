/* analysis.jsx — 분석 실행 로직(_doSearch)을 App.jsx에서 분리
 * window.createDoSearch(deps) → _doSearch 함수 반환. deps로 App의 setter/ref/값 주입. */
window.createDoSearch = function(deps) {
    var cleanProductUrl = deps.cleanProductUrl;
    var lastHtmlRef = deps.lastHtmlRef;
    var products = deps.products;
    var searchIdRef = deps.searchIdRef;
    var setAdvertiserLoading = deps.setAdvertiserLoading;
    var setAdvertiserReport = deps.setAdvertiserReport;
    var setAnalysisData = deps.setAnalysisData;
    var setCompanyName = deps.setCompanyName;
    var setDatalabData = deps.setDatalabData;
    var setDatalabLoading = deps.setDatalabLoading;
    var setHtmlDetailResult = deps.setHtmlDetailResult;
    var setHtmlReviewData = deps.setHtmlReviewData;
    var setRankCheckResult = deps.setRankCheckResult;
    var setRelatedData = deps.setRelatedData;
    var setSearchLoading = deps.setSearchLoading;
    var setSearchedKeyword = deps.setSearchedKeyword;
    var setSearchedProductUrl = deps.setSearchedProductUrl;
    var setShopProducts = deps.setShopProducts;
    var setVolumeData = deps.setVolumeData;

    return function _doSearch(keyword, productUrl, inputCompanyName, htmlInput) {
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
            api.post('/seo/detail-page', { html: htmlInput, product_url: cleanedUrl || '' })
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
        // cleanedUrl 사용: 추적 파라미터 제거 + HTML만 붙여넣은 경우 HTML에서 자동추출된 URL 포함
        // (기존엔 raw productUrl이라 HTML만 붙여넣으면 광고주(진입전략) 분석이 통째로 누락됐음)
        if (cleanedUrl) {
            setAdvertiserLoading(true);
            api.post('/advertiser/analyze', { keyword: keyword, product_url: cleanedUrl })
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

                // 전환율 밴드(저/중/고) — 매출/판매량은 단일값이 아니라 '범위'로 추정 (±EST_TOLERANCE)
                var EST_TOLERANCE = 0.30; // 허용오차 밴드 ±30%
                var cvMid = 0.035;        // 기준 전환율 3.5%
                var cvLo = cvMid * (1 - EST_TOLERANCE); // 0.0245
                var cvHi = cvMid * (1 + EST_TOLERANCE); // 0.0455

                var topProductsList = prods.slice(0, 40).map(function(p) {
                    var ctr = getCTR(p.rank);
                    var estSales = Math.max(1, Math.round(totalVol * ctr * cvMid));
                    var estSalesLo = Math.max(1, Math.round(totalVol * ctr * cvLo));
                    var estSalesHi = Math.max(1, Math.round(totalVol * ctr * cvHi));
                    return {
                        rank: p.rank,
                        name: p.product_name,
                        store: p.store_name,
                        price: p.price,
                        priceStr: fmt(p.price) + '원',
                        ctr: ctr,
                        estMonthlySales: estSales,
                        estMonthlySalesStr: fmt(estSales) + '건',
                        estMonthlySalesRange: fmt(estSalesLo) + '~' + fmt(estSalesHi) + '건',
                        estRevenue: p.price * estSales,
                        estRevenueStr: fmt(p.price * estSales) + '원',
                        estRevenueRange: fmt(p.price * estSalesLo) + '~' + fmt(p.price * estSalesHi) + '원',
                    };
                });

                // 전체 시장 규모 = 상위 40개 상품 추정 매출 합산 (전환율별로 동일 방식 합산)
                var _marketTotal = function(cv) {
                    return prods.slice(0, 40).reduce(function(sum, p) {
                        var estSales = Math.max(1, Math.round(totalVol * getCTR(p.rank) * cv));
                        return sum + p.price * estSales;
                    }, 0);
                };
                var totalMarketRevenue = _marketTotal(cvMid);
                var marketLo = _marketTotal(cvLo);
                var marketHi = _marketTotal(cvHi);

                // '2.5%~4.6% (기준 3.5%, ±30%)' 형태의 전환율 가정 라벨 (백엔드 conv_band_label과 동일)
                var convBandLabel = (cvLo * 100).toFixed(1) + '%~' + (cvHi * 100).toFixed(1) + '% (기준 ' + (cvMid * 100).toFixed(1) + '%, ±' + Math.round(EST_TOLERANCE * 100) + '%)';

                analysis.marketRevenue = {
                    avgPrice: fmt(avgPrice) + '원',
                    estimatedMonthly: fmt(totalMarketRevenue) + '원',
                    estimatedMonthlyRange: fmt(marketLo) + '~' + fmt(marketHi) + '원',
                    conversionRate: convBandLabel,
                    calculationMethod: 'CTR × 전환율(밴드)',
                    tolerance: '±' + Math.round(EST_TOLERANCE * 100) + '%',
                    topProducts: topProductsList.map(function(p) {
                        return {
                            rank: p.rank,
                            name: p.name,
                            store: p.store,
                            price: p.priceStr,
                            ctr: (p.ctr * 100).toFixed(1) + '%',
                            estMonthlySales: p.estMonthlySalesStr,
                            estMonthlySalesRange: p.estMonthlySalesRange,
                            estRevenue: p.estRevenueStr,
                            estRevenueRange: p.estRevenueRange,
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
                // 전환율 밴드(저/중/고) — 판매량/매출은 단일값이 아니라 '범위'로 추정 (±EST_TOLERANCE)
                var SE_TOLERANCE = 0.30; // 허용오차 밴드 ±30%
                var cv = 0.035;                       // 기준 전환율 3.5%
                var cvLoSE = cv * (1 - SE_TOLERANCE);  // 0.0245
                var cvHiSE = cv * (1 + SE_TOLERANCE);  // 0.0455
                // '2.5%~4.6% (기준 3.5%, ±30%)' 형태의 전환율 가정 라벨 (백엔드 conv_band_label과 동일)
                var seBandLabel = (cvLoSE * 100).toFixed(1) + '%~' + (cvHiSE * 100).toFixed(1) + '% (기준 ' + (cv * 100).toFixed(1) + '%, ±' + Math.round(SE_TOLERANCE * 100) + '%)';
                // 80위 전체 한번에 계산
                var allRanks = [];
                for (var ci = 0; ci < 80; ci++) {
                    var sales = Math.round(totalVol * CTR_TABLE[ci] * cv);
                    var salesLo = Math.round(totalVol * CTR_TABLE[ci] * cvLoSE);
                    var salesHi = Math.round(totalVol * CTR_TABLE[ci] * cvHiSE);
                    allRanks.push({
                        sales: sales, revenue: sales * avgP,
                        salesLo: salesLo, salesHi: salesHi,
                        revenueLo: salesLo * avgP, revenueHi: salesHi * avgP,
                    });
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

                // 순위별 시뮬레이션 행 (±밴드 범위 포함) — 백엔드 salesEstimation.simulations와 동일 구조
                var _simRanks = [1, 5, 10, 15, 20, 25, 30, 35, 40];
                var simulations = _simRanks.map(function(rank) {
                    var r = allRanks[rank - 1];
                    return {
                        rank: rank,
                        estSales: r.sales,
                        estSalesRange: fmt(r.salesLo) + '~' + fmt(r.salesHi),
                        revenue: fmt(r.revenue) + '원',
                        revenueRange: fmt(r.revenueLo) + '~' + fmt(r.revenueHi) + '원',
                    };
                });

                analysis.salesEstimation = {
                    avgPrice: fmt(avgP) + '원',
                    monthlySearches: fmt(totalVol),
                    estimatedCTR: 'CTR × 전환율 ' + seBandLabel,
                    tolerance: '±' + Math.round(SE_TOLERANCE * 100) + '%',
                    simulations: simulations,
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
};
