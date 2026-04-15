/* EntryStrategySection — 1페이지 진입 전략 비교 분석 (통합) */
window.EntryStrategySection = function EntryStrategySection(props) {
    var advertiserData = props.advertiserData;   // from /advertiser/analyze
    var strategicData = props.strategicData;      // from App.jsx client-side calc
    var keyword = props.keyword || '';

    if (!advertiserData && !strategicData) return null;

    var ranking = (advertiserData && advertiserData.ranking) || {};
    var productInfo = (advertiserData && advertiserData.product_info) || {};
    var comparison = (advertiserData && advertiserData.competitor_comparison) || {};
    var compItems = comparison.items || [];
    var compStats = comparison.stats || {};
    var strategy = (advertiserData && advertiserData.entry_strategy) || {};
    var strategies = strategy.strategies || [];
    var overallScore = strategy.overall_score || 0;

    // strategicData fallback
    var stData = strategicData || {};
    var avgTop5Price = stData.avgTop5Price || '-';
    var priceRange = stData.priceRange || '-';
    var monthlyVolume = stData.monthlyVolume || '-';
    var mainBrands = stData.mainBrands || '';
    var recommendation = stData.recommendation || '';

    // 상위 5개만 추출
    var top5Items = compItems.slice(0, 5);

    /* 헬퍼 함수들 */
    var severityColor = function(s) {
        if (s === 'high') return '#dc2626';
        if (s === 'medium') return '#d97706';
        if (s === 'low') return '#16a34a';
        return '#6b7280';
    };
    var severityBg = function(s) {
        if (s === 'high') return '#fef2f2';
        if (s === 'medium') return '#fffbeb';
        if (s === 'low') return '#f0fdf4';
        return '#f9fafb';
    };

    var scoreColor = overallScore >= 70 ? '#16a34a' : overallScore >= 40 ? '#d97706' : '#dc2626';
    var scoreLabel = overallScore >= 70 ? '양호' : overallScore >= 40 ? '보통' : '개선 필요';

    /* 격차 분석 데이터 계산 */
    var gapAnalysis = null;
    if (advertiserData && productInfo.price > 0 && compItems.length >= 3) {
        var myPrice = productInfo.price;
        var myRank = ranking.current_rank || null;
        var avgCompPrice = compStats.avg_price || 0;
        var top3Avg = compItems.slice(0, 3).reduce(function(s, c) { return s + c.price; }, 0) / Math.min(3, compItems.length);
        var priceDiffPct = avgCompPrice > 0 ? Math.round((myPrice - avgCompPrice) / avgCompPrice * 100) : 0;
        var priceVsTop3Pct = top3Avg > 0 ? Math.round((myPrice - top3Avg) / top3Avg * 100) : 0;

        var kwInNameCount = compItems.filter(function(c) { return c.has_keyword_in_name; }).length;
        var kwInNameRatio = compItems.length > 0 ? Math.round(kwInNameCount / compItems.length * 100) : 0;
        var myHasKw = productInfo.product_name && keyword && productInfo.product_name.toLowerCase().indexOf(keyword.toLowerCase()) >= 0;

        gapAnalysis = {
            myPrice: myPrice,
            myRank: myRank,
            avgCompPrice: avgCompPrice,
            top3AvgPrice: Math.round(top3Avg),
            priceDiffPct: priceDiffPct,
            priceVsTop3Pct: priceVsTop3Pct,
            compKwRatio: kwInNameRatio,
            myHasKeyword: myHasKw,
            avgNameLength: compStats.avg_name_length || 0,
            myNameLength: productInfo.product_name ? productInfo.product_name.length : 0,
            isOnPage1: ranking.is_on_page1 || false,
        };
    }

    /* 격차 바 시각화 컴포넌트 */
    var GapBar = function(barProps) {
        var label = barProps.label;
        var myVal = barProps.myVal;
        var compVal = barProps.compVal;
        var unit = barProps.unit || '';
        var reverse = barProps.reverse || false; // true면 낮을수록 좋음
        var max = Math.max(myVal, compVal) * 1.2 || 1;
        var myPct = Math.min((myVal / max) * 100, 100);
        var compPct = Math.min((compVal / max) * 100, 100);
        var myBetter = reverse ? myVal <= compVal : myVal >= compVal;

        return React.createElement('div', { style: { marginBottom: 14 } },
            React.createElement('div', { style: { fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 6 } }, label),
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 } },
                React.createElement('span', { style: { fontSize: 11, color: myBetter ? '#059669' : '#dc2626', fontWeight: 700, width: 50, flexShrink: 0 } }, '내 상품'),
                React.createElement('div', { style: { flex: 1, background: '#f1f5f9', borderRadius: 4, height: 18, position: 'relative', overflow: 'hidden' } },
                    React.createElement('div', { style: { width: myPct + '%', height: '100%', background: myBetter ? '#34d399' : '#f87171', borderRadius: 4, transition: 'width 0.8s ease' } }),
                    React.createElement('span', { style: { position: 'absolute', right: 6, top: 1, fontSize: 10, fontWeight: 700, color: '#1e293b' } }, fmt(myVal) + unit)
                )
            ),
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
                React.createElement('span', { style: { fontSize: 11, color: '#64748b', fontWeight: 600, width: 50, flexShrink: 0 } }, '경쟁 평균'),
                React.createElement('div', { style: { flex: 1, background: '#f1f5f9', borderRadius: 4, height: 18, position: 'relative', overflow: 'hidden' } },
                    React.createElement('div', { style: { width: compPct + '%', height: '100%', background: '#94a3b8', borderRadius: 4, transition: 'width 0.8s ease' } }),
                    React.createElement('span', { style: { position: 'absolute', right: 6, top: 1, fontSize: 10, fontWeight: 700, color: '#1e293b' } }, fmt(compVal) + unit)
                )
            )
        );
    };

    return React.createElement('div', { id: 'sec-strategy', className: 'section fade-in' },
        React.createElement('div', { className: 'container' },

            /* === 섹션 헤더 === */
            React.createElement('h2', { className: 'section-title', style: { display: 'flex', alignItems: 'center', gap: 8 } },
                React.createElement('span', { style: { fontSize: 22 } }, '\uD83C\uDFAF'),
                ' 1페이지 진입 전략 비교 분석'
            ),

            /* === 상품 정보 헤더 (광고주 데이터가 있을 때만) === */
            advertiserData && React.createElement('div', { style: { background: '#eff6ff', borderRadius: 10, padding: '16px 20px', marginBottom: 24, display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'center' } },
                productInfo.image_url && React.createElement('img', {
                    src: productInfo.image_url, alt: '',
                    style: { width: 56, height: 56, borderRadius: 8, objectFit: 'cover' },
                    onError: function(e) { e.target.style.display = 'none'; }
                }),
                React.createElement('div', { style: { flex: 1, minWidth: 200 } },
                    React.createElement('div', { style: { fontWeight: 700, fontSize: 15, color: '#1e3a5f', marginBottom: 4 } },
                        productInfo.product_name || '상품 정보 로딩 중...'
                    ),
                    React.createElement('div', { style: { fontSize: 13, color: '#4b5563' } },
                        productInfo.store_name && React.createElement('span', { style: { marginRight: 12 } }, '판매처: ' + productInfo.store_name),
                        productInfo.price > 0 && React.createElement('span', null, '가격: ' + fmt(productInfo.price) + '원')
                    )
                ),
                React.createElement('div', { style: { display: 'flex', gap: 12, alignItems: 'center' } },
                    /* 순위 배지 */
                    React.createElement('div', { style: { textAlign: 'center', padding: '8px 16px', background: '#fff', borderRadius: 10, minWidth: 80 } },
                        React.createElement('div', { style: { fontSize: 24, fontWeight: 800, color: ranking.current_rank ? '#1f2937' : '#dc2626' } },
                            ranking.current_rank ? ranking.current_rank + '위' : '미노출'
                        ),
                        React.createElement('div', { style: { fontSize: 11, color: '#6b7280' } }, '현재 순위')
                    ),
                    /* 종합 점수 배지 */
                    React.createElement('div', { style: { textAlign: 'center', padding: '8px 16px', background: '#fff', borderRadius: 10, minWidth: 80 } },
                        React.createElement('div', { style: { fontSize: 24, fontWeight: 800, color: scoreColor } }, overallScore + '점'),
                        React.createElement('div', { style: { fontSize: 11, color: scoreColor, fontWeight: 600 } }, scoreLabel)
                    )
                )
            ),

            /* === 1. 경쟁사 상위 5개 비교표 === */
            React.createElement('div', { style: { marginBottom: 28 } },
                React.createElement('h3', { style: { fontSize: 16, fontWeight: 700, color: '#1f2937', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6 } },
                    React.createElement('span', null, '\uD83C\uDFC6'), ' 1. 경쟁사 상위 5개 비교표'
                ),

                /* 시장 요약 카드 */
                React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginBottom: 16 } },
                    React.createElement('div', { className: 'card', style: { textAlign: 'center', padding: '14px 10px' } },
                        React.createElement('div', { style: { fontSize: 11, color: '#6b7280', marginBottom: 4 } }, '평균 가격'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: '#1f2937' } },
                            compStats.avg_price ? fmt(compStats.avg_price) + '원' : avgTop5Price
                        )
                    ),
                    React.createElement('div', { className: 'card', style: { textAlign: 'center', padding: '14px 10px' } },
                        React.createElement('div', { style: { fontSize: 11, color: '#6b7280', marginBottom: 4 } }, '가격 범위'),
                        React.createElement('div', { style: { fontSize: 14, fontWeight: 600, color: '#1f2937' } },
                            compStats.min_price ? fmt(compStats.min_price) + '~' + fmt(compStats.max_price) + '원' : priceRange
                        )
                    ),
                    React.createElement('div', { className: 'card', style: { textAlign: 'center', padding: '14px 10px' } },
                        React.createElement('div', { style: { fontSize: 11, color: '#6b7280', marginBottom: 4 } }, '월간 검색량'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: '#1f2937' } }, monthlyVolume + '회')
                    ),
                    React.createElement('div', { className: 'card', style: { textAlign: 'center', padding: '14px 10px' } },
                        React.createElement('div', { style: { fontSize: 11, color: '#6b7280', marginBottom: 4 } }, '키워드 포함률'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: '#1f2937' } },
                            compStats.keyword_in_name_ratio ? compStats.keyword_in_name_ratio + '%' : '-'
                        )
                    )
                ),

                /* 비교표 */
                top5Items.length > 0 ? React.createElement('div', { className: 'table-wrap' },
                    React.createElement('table', { style: { minWidth: 700 } },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: { textAlign: 'center', width: 45 } }, '순위'),
                                React.createElement('th', { style: { textAlign: 'center', width: 45 } }, ''),
                                React.createElement('th', { style: { textAlign: 'left' } }, '상품명'),
                                React.createElement('th', { style: { textAlign: 'left', width: 80 } }, '판매처'),
                                React.createElement('th', { style: { textAlign: 'right', width: 90 } }, '가격'),
                                React.createElement('th', { style: { textAlign: 'center', width: 60 } }, '키워드'),
                                React.createElement('th', { style: { textAlign: 'left', width: 100 } }, '카테고리')
                            )
                        ),
                        React.createElement('tbody', null,
                            top5Items.map(function(c, idx) {
                                var isMyProduct = ranking.current_rank && c.rank === ranking.current_rank;
                                return React.createElement('tr', { key: idx, style: isMyProduct ? { background: '#eff6ff', fontWeight: 600 } : {} },
                                    React.createElement('td', { style: { textAlign: 'center', fontWeight: 600 } },
                                        c.rank <= 3 ? React.createElement('span', { style: { display: 'inline-block', width: 24, height: 24, lineHeight: '24px', borderRadius: '50%', background: c.rank === 1 ? '#f59e0b' : c.rank === 2 ? '#9ca3af' : '#b45309', color: '#fff', fontSize: 12, fontWeight: 700 } }, c.rank) : c.rank
                                    ),
                                    React.createElement('td', { style: { textAlign: 'center', padding: '6px' } },
                                        c.image_url ? React.createElement('img', { src: c.image_url, alt: '', style: { width: 36, height: 36, objectFit: 'cover', borderRadius: 6 }, onError: function(e) { e.target.style.display = 'none'; } }) : null
                                    ),
                                    React.createElement('td', { style: { maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 } },
                                        isMyProduct && React.createElement('span', { style: { color: '#3b82f6', marginRight: 4 } }, '[내 상품]'),
                                        c.product_name
                                    ),
                                    React.createElement('td', { style: { fontSize: 12, color: '#6b7280' } }, c.store_name),
                                    React.createElement('td', { style: { textAlign: 'right', fontWeight: 600, fontSize: 13 } }, fmt(c.price) + '원'),
                                    React.createElement('td', { style: { textAlign: 'center' } },
                                        React.createElement('span', { style: { display: 'inline-block', padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: c.has_keyword_in_name ? '#dcfce7' : '#fef2f2', color: c.has_keyword_in_name ? '#166534' : '#991b1b' } }, c.has_keyword_in_name ? 'O' : 'X')
                                    ),
                                    React.createElement('td', { style: { fontSize: 11, color: '#6b7280' } }, c.category)
                                );
                            })
                        )
                    )
                ) : (
                    /* strategicData만 있을 때 — 주요 브랜드/판매처 표시 */
                    mainBrands && React.createElement('div', { className: 'card', style: { padding: 20 } },
                        React.createElement('h4', { style: { fontSize: 14, fontWeight: 700, color: '#1f2937', marginBottom: 14 } }, '\uD83C\uDFE2 주요 브랜드/판매처'),
                        React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 8 } },
                            mainBrands.split(', ').map(function(brand, idx) {
                                return React.createElement('span', { key: idx, style: { padding: '6px 14px', background: 'linear-gradient(135deg, #ede9fe, #e0e7ff)', borderRadius: 999, fontSize: 12, fontWeight: 600, color: '#4f46e5', border: '1px solid #c7d2fe' } }, brand);
                            })
                        )
                    )
                )
            ),

            /* === 2. 내 상품 vs 경쟁사 격차 분석 === */
            gapAnalysis && React.createElement('div', { style: { marginBottom: 28 } },
                React.createElement('h3', { style: { fontSize: 16, fontWeight: 700, color: '#1f2937', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6 } },
                    React.createElement('span', null, '\uD83D\uDCCA'), ' 2. 내 상품 vs 경쟁사 격차 분석'
                ),

                /* 격차 요약 카드 */
                React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 20 } },
                    /* 가격 격차 */
                    React.createElement('div', { className: 'card', style: { padding: '16px 18px', borderLeft: '4px solid ' + (gapAnalysis.priceDiffPct <= 0 ? '#16a34a' : gapAnalysis.priceDiffPct <= 10 ? '#d97706' : '#dc2626') } },
                        React.createElement('div', { style: { fontSize: 11, color: '#6b7280', marginBottom: 6 } }, '\uD83D\uDCB0 가격 경쟁력'),
                        React.createElement('div', { style: { fontSize: 22, fontWeight: 800, color: gapAnalysis.priceDiffPct <= 0 ? '#16a34a' : gapAnalysis.priceDiffPct <= 10 ? '#d97706' : '#dc2626' } },
                            (gapAnalysis.priceDiffPct > 0 ? '+' : '') + gapAnalysis.priceDiffPct + '%'
                        ),
                        React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginTop: 4 } },
                            gapAnalysis.priceDiffPct <= -10 ? '경쟁사 대비 저렴' : gapAnalysis.priceDiffPct <= 0 ? '적정 가격대' : gapAnalysis.priceDiffPct <= 10 ? '소폭 비쌈' : '가격 조정 필요'
                        )
                    ),
                    /* 상위3개 vs 내 가격 */
                    React.createElement('div', { className: 'card', style: { padding: '16px 18px', borderLeft: '4px solid ' + (gapAnalysis.priceVsTop3Pct <= 0 ? '#16a34a' : '#d97706') } },
                        React.createElement('div', { style: { fontSize: 11, color: '#6b7280', marginBottom: 6 } }, '\uD83E\uDD47 TOP3 대비 가격'),
                        React.createElement('div', { style: { fontSize: 22, fontWeight: 800, color: gapAnalysis.priceVsTop3Pct <= 0 ? '#16a34a' : '#d97706' } },
                            (gapAnalysis.priceVsTop3Pct > 0 ? '+' : '') + gapAnalysis.priceVsTop3Pct + '%'
                        ),
                        React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginTop: 4 } },
                            'TOP3 평균: ' + fmt(gapAnalysis.top3AvgPrice) + '원'
                        )
                    ),
                    /* 키워드 포함 여부 */
                    React.createElement('div', { className: 'card', style: { padding: '16px 18px', borderLeft: '4px solid ' + (gapAnalysis.myHasKeyword ? '#16a34a' : '#dc2626') } },
                        React.createElement('div', { style: { fontSize: 11, color: '#6b7280', marginBottom: 6 } }, '\uD83D\uDD24 키워드 포함'),
                        React.createElement('div', { style: { fontSize: 22, fontWeight: 800, color: gapAnalysis.myHasKeyword ? '#16a34a' : '#dc2626' } },
                            gapAnalysis.myHasKeyword ? '포함 \u2705' : '미포함 \u274C'
                        ),
                        React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginTop: 4 } },
                            '경쟁사 포함률: ' + gapAnalysis.compKwRatio + '%'
                        )
                    ),
                    /* 1페이지 진입 여부 */
                    React.createElement('div', { className: 'card', style: { padding: '16px 18px', borderLeft: '4px solid ' + (gapAnalysis.isOnPage1 ? '#16a34a' : '#dc2626') } },
                        React.createElement('div', { style: { fontSize: 11, color: '#6b7280', marginBottom: 6 } }, '\uD83D\uDCC4 1페이지 진입'),
                        React.createElement('div', { style: { fontSize: 22, fontWeight: 800, color: gapAnalysis.isOnPage1 ? '#16a34a' : '#dc2626' } },
                            gapAnalysis.isOnPage1 ? '진입 \u2705' : '미진입 \u274C'
                        ),
                        React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginTop: 4 } },
                            gapAnalysis.myRank ? '현재 ' + gapAnalysis.myRank + '위' : '순위권 밖'
                        )
                    )
                ),

                /* 격차 바 차트 */
                React.createElement('div', { className: 'card', style: { padding: 20 } },
                    React.createElement('div', { style: { fontWeight: 700, fontSize: 14, marginBottom: 16, color: '#334155' } }, '\uD83D\uDCCA 상세 비교'),
                    React.createElement(GapBar, { label: '가격 (원)', myVal: gapAnalysis.myPrice, compVal: gapAnalysis.avgCompPrice, unit: '원', reverse: true }),
                    React.createElement(GapBar, { label: '상품명 길이 (글자)', myVal: gapAnalysis.myNameLength, compVal: gapAnalysis.avgNameLength, unit: '자' }),
                    gapAnalysis.myRank && React.createElement(GapBar, { label: '순위', myVal: gapAnalysis.myRank, compVal: 3, unit: '위', reverse: true })
                )
            ),

            /* === 3. AI 기반 맞춤 진입 전략 제안 === */
            strategies.length > 0 && React.createElement('div', { style: { marginBottom: 20 } },
                React.createElement('h3', { style: { fontSize: 16, fontWeight: 700, color: '#1f2937', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6 } },
                    React.createElement('span', null, '\uD83E\uDD16'), ' 3. AI 기반 맞춤 진입 전략 제안'
                ),

                /* 전략 카드들 — 컨설팅 리포트 스타일 */
                React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
                    strategies.map(function(s, idx) {
                        var cardBorderColor = s.severity === 'high' ? '#dc2626' : s.severity === 'low' ? '#16a34a' : s.severity === 'info' ? '#3b82f6' : '#d97706';
                        var cardBg = s.severity === 'high' ? '#fef2f2' : s.severity === 'low' ? '#f0fdf4' : s.severity === 'info' ? '#eff6ff' : '#fffbeb';
                        var iconBg = s.severity === 'high' ? '#fee2e2' : s.severity === 'low' ? '#dcfce7' : s.severity === 'info' ? '#dbeafe' : '#fef3c7';
                        var insights = s.insights || [];
                        var actions = s.actions || [];
                        var recs = s.recommendations || [];

                        return React.createElement('div', { key: idx, style: { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' } },
                            /* 카드 헤더 */
                            React.createElement('div', { style: { background: cardBg, padding: '14px 20px', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', gap: 10 } },
                                React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 32, height: 32, borderRadius: 8, background: iconBg, fontSize: 16 } }, s.icon || ''),
                                React.createElement('span', { style: { fontWeight: 700, fontSize: 15, color: '#1f2937', flex: 1 } }, s.area),
                                React.createElement('span', { style: { padding: '3px 12px', borderRadius: 20, fontSize: 11, fontWeight: 700, color: '#fff', background: cardBorderColor } },
                                    s.severity === 'high' ? '핵심 개선' : s.severity === 'low' ? '강점 유지' : s.severity === 'info' ? '실행 가이드' : '점검 필요'
                                )
                            ),
                            /* 카드 바디 */
                            React.createElement('div', { style: { padding: '16px 20px' } },
                                /* 분석 인사이트 */
                                insights.length > 0 && React.createElement('div', { style: { marginBottom: actions.length > 0 || recs.length > 0 ? 14 : 0 } },
                                    React.createElement('div', { style: { fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 } }, 'INSIGHT'),
                                    insights.map(function(insight, i) {
                                        return React.createElement('div', { key: i, style: { fontSize: 13, color: '#374151', lineHeight: 1.7, padding: '4px 0', display: 'flex', gap: 8 } },
                                            React.createElement('span', { style: { color: cardBorderColor, flexShrink: 0, marginTop: 2 } }, '\u25B8'),
                                            React.createElement('span', null, insight)
                                        );
                                    })
                                ),
                                /* 액션 아이템 */
                                actions.length > 0 && React.createElement('div', { style: { background: '#f8fafc', borderRadius: 8, padding: '12px 16px', border: '1px solid #e2e8f0', marginBottom: recs.length > 0 ? 14 : 0 } },
                                    React.createElement('div', { style: { fontSize: 11, fontWeight: 700, color: cardBorderColor, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 } }, 'ACTION PLAN'),
                                    actions.map(function(action, i) {
                                        return React.createElement('div', { key: i, style: { fontSize: 13, color: '#1e293b', lineHeight: 1.7, padding: '5px 0', borderBottom: i < actions.length - 1 ? '1px solid #e2e8f0' : 'none', display: 'flex', gap: 8 } },
                                            React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 18, height: 18, borderRadius: 4, background: cardBorderColor, color: '#fff', fontSize: 10, fontWeight: 700, flexShrink: 0, marginTop: 2 } }, i + 1),
                                            React.createElement('span', null, action)
                                        );
                                    })
                                ),
                                /* 추천 광고 품목 */
                                recs.length > 0 && React.createElement('div', { style: { background: 'linear-gradient(135deg, #eef2ff, #faf5ff)', borderRadius: 8, padding: '12px 16px', border: '1px solid #c7d2fe' } },
                                    React.createElement('div', { style: { fontSize: 11, fontWeight: 700, color: '#6366f1', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 } },
                                        React.createElement('span', { style: { fontSize: 13 } }, '\uD83D\uDCE2'),
                                        'RECOMMENDED SERVICE'
                                    ),
                                    recs.map(function(rec, i) {
                                        return React.createElement('div', { key: i, style: { padding: '8px 0', borderBottom: i < recs.length - 1 ? '1px solid #ddd6fe' : 'none', display: 'flex', gap: 10, alignItems: 'flex-start' } },
                                            React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', padding: '3px 10px', borderRadius: 20, background: '#6366f1', color: '#fff', fontSize: 11, fontWeight: 700, flexShrink: 0, whiteSpace: 'nowrap', marginTop: 1 } }, rec.name),
                                            React.createElement('span', { style: { fontSize: 12, color: '#4b5563', lineHeight: 1.6 } }, rec.reason)
                                        );
                                    })
                                )
                            )
                        );
                    })
                )
            ),

            /* 종합 전략 추천 (strategicData 기반 — advertiserData 없을 때만) */
            !advertiserData && recommendation && React.createElement('div', { style: { background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: '18px 22px', borderLeft: '4px solid #16a34a', marginBottom: 20 } },
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 } },
                    React.createElement('span', { style: { fontSize: 16 } }, '\uD83D\uDCCC'),
                    React.createElement('span', { style: { fontWeight: 700, fontSize: 14, color: '#065f46' } }, '종합 진입 전략'),
                    React.createElement('span', { style: { padding: '2px 10px', borderRadius: 10, fontSize: 10, fontWeight: 700, color: '#fff', background: '#16a34a', marginLeft: 'auto' } }, '전략')
                ),
                React.createElement('p', { style: { lineHeight: 1.7, color: '#374151', fontSize: 13, margin: 0 } }, recommendation)
            ),

            /* 분석 시각 */
            React.createElement('div', { style: { marginTop: 16, padding: '10px 16px', background: '#f9fafb', borderRadius: 8, fontSize: 12, color: '#9ca3af', textAlign: 'center' } },
                '네이버 공식 API 기준 분석 결과이며, 실제 검색 노출 순위와 차이가 있을 수 있습니다.',
                advertiserData && advertiserData.analyzed_at ? ' | 분석 시각: ' + new Date(advertiserData.analyzed_at).toLocaleString('ko-KR') : ''
            ),

            /* 반응형 스타일 */
            React.createElement('style', null, '\n@media (max-width: 768px) {\n  #sec-strategy .card-grid-4 { grid-template-columns: 1fr 1fr !important; }\n}\n')
        )
    );
};
