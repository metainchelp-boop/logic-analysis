/* AnalysisResults — 메인 분석결과 렌더 (App.jsx에서 분리)
 * report-shell(좌측 목차 + 본문 전 섹션). App의 상태/핸들러를 props로 받음. */
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
                auditStatus && auditStatus.items && auditStatus.items.length > 0 && React.createElement('div', { className: 'section fade-in' },
                    React.createElement('div', { className: 'container' },
                        React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 14px', fontSize: 12.5 } },
                            React.createElement('b', { style: { color: '#334155' } },
                                auditStatus.phase === 'auditing' ? '🔍 데이터 검수 중…' : '🔍 데이터 검수'),
                            auditStatus.items.map(function(it, i) {
                                var color = it.st === 'ok' ? '#059669' : (it.st === 'retry' ? '#d97706' : (it.st === 'wait' ? '#94a3b8' : '#dc2626'));
                                var mark = it.st === 'ok' ? '✓' : (it.st === 'retry' ? '↻' : (it.st === 'wait' ? '…' : '✗'));
                                return React.createElement('span', { key: i, style: { color: color, whiteSpace: 'nowrap', fontWeight: 600 } }, mark + ' ' + it.name);
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
                        React.createElement(SummaryCardsSection, {
                            data: analysisData.summaryCards,
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

                /* 예상 CPC · 권장 입찰가 (추정) */
                analysisData && volumeData && volumeData.length && React.createElement(window.SectionErrorBoundary, { name: '예상 CPC' },
                    React.createElement(window.CpcBidEstimateSection, { volumeData: volumeData, keyword: searchedKeyword })
                ),
    
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
                analysisData && React.createElement(window.SectionDivider, { label: '4. 내 상품 현황', icon: '🛒', color: '#059669', sub: '노출순위 · 판매추정 · 리뷰 · SEO 4종' }),
    
                /* 키워드별 노출 순위 */
                React.createElement(window.SectionErrorBoundary, { name: '순위 추적' },
                    React.createElement(RankTrackingSection, { products: products, refreshProducts: loadProducts, searchedKeyword: searchedKeyword, searchedProductUrl: searchedProductUrl, cachedProductName: advertiserReport && advertiserReport.product_name ? advertiserReport.product_name : (analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo.product_name : null), relatedKeywords: (relatedData ? (relatedData.golden_keywords || []).concat(relatedData.related_keywords || []).map(function(k) { return typeof k === 'string' ? k : (k && k.keyword) || ''; }).filter(Boolean) : []), onNavigateToClient: handleNavigateToClient, canEdit: currentUser.role !== 'viewer', onRankResult: setRankCheckResult })
                ),

                /* 분석 상품 순위추적 원클릭 등록 */
                searchedProductUrl && React.createElement(window.SectionErrorBoundary, { name: '추적 등록' },
                    React.createElement(window.TrackRegisterButton, { searchedProductUrl: searchedProductUrl, searchedKeyword: searchedKeyword, products: products, refreshProducts: loadProducts, canEdit: currentUser.role !== 'viewer' })
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
                        cachedProductName: advertiserReport && advertiserReport.product_name ? advertiserReport.product_name : (analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo.product_name : null),
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
                analysisData && React.createElement(window.SectionDivider, { label: '5. 기회 발굴', icon: '💎', color: '#7c3aed', sub: '연관키워드 · 골든키워드 · 상품명 최적화' }),
    
                /* 연관 키워드 */
                relatedData && React.createElement(window.SectionErrorBoundary, { name: '연관 키워드' },
                    React.createElement(RelatedKeywordsSection, { data: relatedData, keyword: searchedKeyword })
                ),
    
                /* 골든 키워드 (0건이어도 대안 안내를 렌더) */
                analysisData && React.createElement(window.SectionErrorBoundary, { name: '골든 키워드' },
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
                        keyword: searchedKeyword,
                        analysisData: analysisData,
                        volumeData: volumeData,
                        relatedData: relatedData,
                        advertiserReport: advertiserReport,
                        htmlReviewData: htmlReviewData,
                        datalabData: datalabData
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
                        competitorContext: props.competitorContext,
                        onCompetitorSaved: props.onCompetitorSaved,
                    })
                ),
    
                /* 21. 보고서 출력 */
                searchedProductUrl && React.createElement(window.SectionErrorBoundary, { name: '보고서' },
                    React.createElement(ReportSection, { keyword: searchedKeyword, companyName: companyName, managerName: currentUser && currentUser.name })
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
