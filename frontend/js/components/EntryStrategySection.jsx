/* EntryStrategySection — 1페이지 진입 전략 비교 분석 (v5) */
window.EntryStrategySection = function EntryStrategySection(props) {
    var advertiserData = props.advertiserData;   // from /advertiser/analyze
    var strategicData = props.strategicData;      // from App.jsx client-side calc
    var keyword = props.keyword || '';
    var rankCheckResult = props.rankCheckResult;   // from RankTrackingSection (순위 추적 결과 공유)

    if (!advertiserData && !strategicData) return null;

    // 순위 데이터: rankCheckResult(순위 추적)가 있으면 우선 사용, 없으면 advertiser 데이터 사용
    var ranking = (advertiserData && advertiserData.ranking) || {};
    if (rankCheckResult && rankCheckResult.rank_position != null) {
        ranking = Object.assign({}, ranking, {
            current_rank: rankCheckResult.rank_position,
            page_number: rankCheckResult.page_number,
            is_on_page1: rankCheckResult.rank_position <= 40,
        });
    }
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

    // 상위 10개 추출
    var top5Items = compItems.slice(0, 10);

    /* 헬퍼 함수들 */
    var severityColor = function(s) {
        if (s === 'high') return '#ef4444';
        if (s === 'medium') return '#f59e0b';
        if (s === 'low') return '#10b981';
        return '#64748b';
    };
    var severityBg = function(s) {
        if (s === 'high') return '#fef2f2';
        if (s === 'medium') return '#fffbeb';
        if (s === 'low') return '#f0fdf4';
        return '#f8fafc';
    };

    var scoreColor = overallScore >= 70 ? '#10b981' : overallScore >= 40 ? '#f59e0b' : '#ef4444';
    var scoreLabel = overallScore >= 70 ? '양호' : overallScore >= 40 ? '보통' : '개선 필요';

    /* v5 card style */
    var v5Card = { borderRadius: 16, background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' };

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

    /* v5 격차 바 시각화 컴포넌트 */
    var GapBar = function(barProps) {
        var label = barProps.label;
        var myVal = barProps.myVal;
        var compVal = barProps.compVal;
        var unit = barProps.unit || '';
        var reverse = barProps.reverse || false;
        var max = Math.max(myVal, compVal) * 1.2 || 1;
        var myPct = Math.min((myVal / max) * 100, 100);
        var compPct = Math.min((compVal / max) * 100, 100);
        var myBetter = reverse ? myVal <= compVal : myVal >= compVal;

        return React.createElement('div', { style: { marginBottom: 16 } },
            React.createElement('div', { style: { fontSize: 12, fontWeight: 600, color: '#0f172a', marginBottom: 8 } }, label),
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 } },
                React.createElement('span', { style: { fontSize: 11, color: myBetter ? '#10b981' : '#ef4444', fontWeight: 700, width: 55, flexShrink: 0 } }, '내 상품'),
                React.createElement('div', { style: { flex: 1, background: '#f1f5f9', borderRadius: 5, height: 10, position: 'relative', overflow: 'hidden' } },
                    React.createElement('div', { style: { width: myPct + '%', height: '100%', background: myBetter ? 'linear-gradient(90deg, #34d399, #10b981)' : 'linear-gradient(90deg, #f87171, #ef4444)', borderRadius: 5, transition: 'width 0.8s ease' } })
                ),
                React.createElement('span', { style: { fontSize: 12, fontWeight: 700, color: '#0f172a', width: 70, textAlign: 'right', flexShrink: 0 } }, fmt(myVal) + unit)
            ),
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
                React.createElement('span', { style: { fontSize: 11, color: '#64748b', fontWeight: 600, width: 55, flexShrink: 0 } }, '경쟁 평균'),
                React.createElement('div', { style: { flex: 1, background: '#f1f5f9', borderRadius: 5, height: 10, position: 'relative', overflow: 'hidden' } },
                    React.createElement('div', { style: { width: compPct + '%', height: '100%', background: '#94a3b8', borderRadius: 5, transition: 'width 0.8s ease' } })
                ),
                React.createElement('span', { style: { fontSize: 12, fontWeight: 700, color: '#64748b', width: 70, textAlign: 'right', flexShrink: 0 } }, fmt(compVal) + unit)
            )
        );
    };

    return React.createElement('div', { id: 'sec-strategy', className: 'section fade-in' },
        React.createElement('div', { className: 'container' },

            /* === 섹션 헤더 === */
            React.createElement('div', { className: 'section-title' },
                React.createElement('span', { className: 'icon', style: { background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' } }, '🚀'),
                ' 1페이지 진입 전략 비교 분석'
            ),
            React.createElement('div', { className: 'section-line' }),
            React.createElement('p', { className: 'section-subtitle' }, '경쟁사 데이터 기반 1페이지 진입 전략을 제안합니다'),

            /* === 상품 정보 헤더 (광고주 데이터가 있을 때만) === */
            advertiserData && React.createElement('div', { style: {
                background: '#fff', borderRadius: 16, padding: '20px 24px', marginBottom: 24,
                display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'center',
                border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
            } },
                productInfo.image_url && React.createElement('img', {
                    src: productInfo.image_url, alt: '',
                    style: { width: 60, height: 60, borderRadius: 12, objectFit: 'cover', border: '1px solid #e2e8f0' },
                    onError: function(e) { e.target.style.display = 'none'; }
                }),
                React.createElement('div', { style: { flex: 1, minWidth: 200 } },
                    React.createElement('div', { style: { fontWeight: 700, fontSize: 15, color: '#0f172a', marginBottom: 4 } },
                        productInfo.product_name || '상품 정보 로딩 중...'
                    ),
                    React.createElement('div', { style: { fontSize: 13, color: '#64748b' } },
                        productInfo.store_name && React.createElement('span', { style: { marginRight: 12 } }, '판매처: ' + productInfo.store_name),
                        productInfo.price > 0 && React.createElement('span', null, '가격: ' + fmt(productInfo.price) + '원')
                    )
                ),
                React.createElement('div', { style: { display: 'flex', gap: 12, alignItems: 'center' } },
                    /* 순위 배지 */
                    React.createElement('div', { style: { textAlign: 'center', padding: '10px 18px', background: '#f8fafc', borderRadius: 12, minWidth: 80, border: '1px solid #e2e8f0' } },
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 800, color: ranking.current_rank ? '#0f172a' : '#ef4444' } },
                            ranking.current_rank ? ranking.current_rank + '위' : '미노출'
                        ),
                        React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', fontWeight: 600 } }, '현재 순위')
                    ),
                    /* 종합 점수 - conic gradient circle */
                    React.createElement('div', { style: { textAlign: 'center', padding: '10px 18px', background: '#f8fafc', borderRadius: 12, minWidth: 80, border: '1px solid #e2e8f0' } },
                        React.createElement('div', { style: {
                            width: 48, height: 48, borderRadius: '50%', margin: '0 auto 4px',
                            background: 'conic-gradient(' + scoreColor + ' ' + (overallScore * 3.6) + 'deg, #f1f5f9 0deg)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center'
                        } },
                            React.createElement('div', { style: {
                                width: 38, height: 38, borderRadius: '50%', background: '#f8fafc',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                fontSize: 14, fontWeight: 800, color: scoreColor
                            } }, overallScore)
                        ),
                        React.createElement('div', { style: { fontSize: 11, color: scoreColor, fontWeight: 600 } }, scoreLabel)
                    )
                )
            ),

            /* === 1. 경쟁사 상위 10개 비교표 === */
            React.createElement('div', { style: { marginBottom: 28 } },
                React.createElement('h3', { style: { fontSize: 16, fontWeight: 700, color: '#0f172a', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 } },
                    React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, borderRadius: 8, background: 'linear-gradient(135deg, #eef2ff, #dbeafe)', fontSize: 14 } }, '\uD83C\uDFC6'),
                    ' 1. 경쟁사 상위 10개 비교표'
                ),

                /* 시장 요약 v5 MetricCard */
                React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 } },
                    React.createElement('div', { style: Object.assign({}, v5Card, { textAlign: 'center', padding: 24 }) },
                        React.createElement('div', { style: { fontSize: 18, marginBottom: 8 } }, '\uD83D\uDCB0'),
                        React.createElement('div', { style: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 } }, '평균 가격'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 800, color: '#0f172a' } },
                            compStats.avg_price ? fmt(compStats.avg_price) + '원' : avgTop5Price
                        )
                    ),
                    React.createElement('div', { style: Object.assign({}, v5Card, { textAlign: 'center', padding: 24 }) },
                        React.createElement('div', { style: { fontSize: 18, marginBottom: 8 } }, '\uD83D\uDCC8'),
                        React.createElement('div', { style: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 } }, '가격 범위'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 800, color: '#0f172a' } },
                            compStats.min_price ? fmt(compStats.min_price) + '~' + fmt(compStats.max_price) + '원' : priceRange
                        )
                    ),
                    React.createElement('div', { style: Object.assign({}, v5Card, { textAlign: 'center', padding: 24 }) },
                        React.createElement('div', { style: { fontSize: 18, marginBottom: 8 } }, '\uD83D\uDD0D'),
                        React.createElement('div', { style: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 } }, '월간 검색량'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 800, color: '#4f46e5' } }, monthlyVolume + '회')
                    ),
                    React.createElement('div', { style: Object.assign({}, v5Card, { textAlign: 'center', padding: 24 }) },
                        React.createElement('div', { style: { fontSize: 18, marginBottom: 8 } }, '\uD83D\uDD24'),
                        React.createElement('div', { style: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 } }, '키워드 포함률'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 800, color: '#7c3aed' } },
                            compStats.keyword_in_name_ratio ? compStats.keyword_in_name_ratio + '%' : '-'
                        )
                    )
                ),

                /* v5 비교표 — gradient header */
                top5Items.length > 0 ? React.createElement('div', { style: Object.assign({}, v5Card, { overflow: 'hidden' }) },
                    React.createElement('table', { style: { minWidth: 700, width: '100%', borderCollapse: 'collapse' } },
                        React.createElement('thead', null,
                            React.createElement('tr', { style: { background: 'linear-gradient(135deg, #4f46e5, #7c3aed)' } },
                                React.createElement('th', { style: { textAlign: 'center', width: 45, padding: '12px 8px', color: '#fff', fontSize: 12, fontWeight: 600 } }, '순위'),
                                React.createElement('th', { style: { textAlign: 'center', width: 45, padding: '12px 4px', color: '#fff', fontSize: 12, fontWeight: 600 } }, ''),
                                React.createElement('th', { style: { textAlign: 'left', padding: '12px 8px', color: '#fff', fontSize: 12, fontWeight: 600 } }, '상품명'),
                                React.createElement('th', { style: { textAlign: 'left', width: 80, padding: '12px 8px', color: '#fff', fontSize: 12, fontWeight: 600 } }, '판매처'),
                                React.createElement('th', { style: { textAlign: 'right', width: 90, padding: '12px 8px', color: '#fff', fontSize: 12, fontWeight: 600 } }, '가격'),
                                React.createElement('th', { style: { textAlign: 'center', width: 60, padding: '12px 8px', color: '#fff', fontSize: 12, fontWeight: 600 } }, '키워드'),
                                React.createElement('th', { style: { textAlign: 'left', width: 100, padding: '12px 8px', color: '#fff', fontSize: 12, fontWeight: 600 } }, '카테고리')
                            )
                        ),
                        React.createElement('tbody', null,
                            top5Items.map(function(c, idx) {
                                var isMyProduct = ranking.current_rank && c.rank === ranking.current_rank;
                                var rowBg = isMyProduct ? '#eef2ff' : idx % 2 === 0 ? '#fff' : '#f8fafc';
                                return React.createElement('tr', { key: idx, style: { background: rowBg, borderBottom: '1px solid #f1f5f9' } },
                                    React.createElement('td', { style: { textAlign: 'center', fontWeight: 600, padding: '10px 8px', fontSize: 13 } },
                                        c.rank <= 3 ? React.createElement('span', { style: { display: 'inline-block', width: 26, height: 26, lineHeight: '26px', borderRadius: '50%', background: c.rank === 1 ? '#f59e0b' : c.rank === 2 ? '#94a3b8' : '#b45309', color: '#fff', fontSize: 12, fontWeight: 700 } }, c.rank) : c.rank
                                    ),
                                    React.createElement('td', { style: { textAlign: 'center', padding: '8px 4px' } },
                                        c.image_url ? React.createElement('img', { src: c.image_url, alt: '', style: { width: 36, height: 36, objectFit: 'cover', borderRadius: 8 }, onError: function(e) { e.target.style.display = 'none'; } }) : null
                                    ),
                                    React.createElement('td', { style: { maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13, padding: '10px 8px', color: '#0f172a' } },
                                        isMyProduct && React.createElement('span', { style: { color: '#4f46e5', marginRight: 4, fontWeight: 700 } }, '[내 상품]'),
                                        c.product_name
                                    ),
                                    React.createElement('td', { style: { fontSize: 12, color: '#64748b', padding: '10px 8px' } }, c.store_name),
                                    React.createElement('td', { style: { textAlign: 'right', fontWeight: 600, fontSize: 13, padding: '10px 8px', color: '#0f172a' } }, fmt(c.price) + '원'),
                                    React.createElement('td', { style: { textAlign: 'center', padding: '10px 8px' } },
                                        React.createElement('span', { style: { display: 'inline-block', padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700, background: c.has_keyword_in_name ? '#ecfdf5' : '#fef2f2', color: c.has_keyword_in_name ? '#10b981' : '#ef4444' } }, c.has_keyword_in_name ? 'O' : 'X')
                                    ),
                                    React.createElement('td', { style: { fontSize: 11, color: '#64748b', padding: '10px 8px' } }, c.category)
                                );
                            })
                        )
                    )
                ) : (
                    /* strategicData만 있을 때 — 주요 브랜드/판매처 표시 */
                    mainBrands && React.createElement('div', { style: Object.assign({}, v5Card, { padding: 24 }) },
                        React.createElement('h4', { style: { fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 14 } }, '\uD83C\uDFE2 주요 브랜드/판매처'),
                        React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 8 } },
                            mainBrands.split(', ').map(function(brand, idx) {
                                return React.createElement('span', { key: idx, style: { padding: '4px 12px', background: 'linear-gradient(135deg, #eef2ff, #dbeafe)', borderRadius: 999, fontSize: 12, fontWeight: 700, color: '#4f46e5', border: '1px solid #c7d2fe' } }, brand);
                            })
                        )
                    )
                )
            ),

            /* === 2. 내 상품 vs 경쟁사 격차 분석 === */
            gapAnalysis && React.createElement('div', { style: { marginBottom: 28 } },
                React.createElement('h3', { style: { fontSize: 16, fontWeight: 700, color: '#0f172a', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 } },
                    React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, borderRadius: 8, background: 'linear-gradient(135deg, #eef2ff, #dbeafe)', fontSize: 14 } }, '\uD83D\uDCCA'),
                    ' 2. 내 상품 vs 경쟁사 격차 분석'
                ),

                /* 격차 요약 v5 MetricCard */
                React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 } },
                    /* 가격 격차 */
                    React.createElement('div', { style: Object.assign({}, v5Card, { padding: 24, textAlign: 'center' }) },
                        React.createElement('div', { style: { fontSize: 18, marginBottom: 8 } }, '\uD83D\uDCB0'),
                        React.createElement('div', { style: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 } }, '가격 경쟁력'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 800, color: gapAnalysis.priceDiffPct <= 0 ? '#10b981' : gapAnalysis.priceDiffPct <= 10 ? '#f59e0b' : '#ef4444' } },
                            (gapAnalysis.priceDiffPct > 0 ? '+' : '') + gapAnalysis.priceDiffPct + '%'
                        ),
                        React.createElement('div', { style: { fontSize: 12, color: '#64748b', marginTop: 4 } },
                            gapAnalysis.priceDiffPct <= -10 ? '경쟁사 대비 저렴' : gapAnalysis.priceDiffPct <= 0 ? '적정 가격대' : gapAnalysis.priceDiffPct <= 10 ? '소폭 비쌈' : '가격 조정 필요'
                        )
                    ),
                    /* 상위3개 vs 내 가격 */
                    React.createElement('div', { style: Object.assign({}, v5Card, { padding: 24, textAlign: 'center' }) },
                        React.createElement('div', { style: { fontSize: 18, marginBottom: 8 } }, '\uD83E\uDD47'),
                        React.createElement('div', { style: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 } }, 'TOP3 대비 가격'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 800, color: gapAnalysis.priceVsTop3Pct <= 0 ? '#10b981' : '#f59e0b' } },
                            (gapAnalysis.priceVsTop3Pct > 0 ? '+' : '') + gapAnalysis.priceVsTop3Pct + '%'
                        ),
                        React.createElement('div', { style: { fontSize: 12, color: '#64748b', marginTop: 4 } },
                            'TOP3 평균: ' + fmt(gapAnalysis.top3AvgPrice) + '원'
                        )
                    ),
                    /* 키워드 포함 여부 */
                    React.createElement('div', { style: Object.assign({}, v5Card, { padding: 24, textAlign: 'center' }) },
                        React.createElement('div', { style: { fontSize: 18, marginBottom: 8 } }, '\uD83D\uDD24'),
                        React.createElement('div', { style: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 } }, '키워드 포함'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 800, color: gapAnalysis.myHasKeyword ? '#10b981' : '#ef4444' } },
                            gapAnalysis.myHasKeyword ? '포함 \u2705' : '미포함 \u274C'
                        ),
                        React.createElement('div', { style: { fontSize: 12, color: '#64748b', marginTop: 4 } },
                            '경쟁사 포함률: ' + gapAnalysis.compKwRatio + '%'
                        )
                    ),
                    /* 1페이지 진입 여부 */
                    React.createElement('div', { style: Object.assign({}, v5Card, { padding: 24, textAlign: 'center' }) },
                        React.createElement('div', { style: { fontSize: 18, marginBottom: 8 } }, '\uD83D\uDCC4'),
                        React.createElement('div', { style: { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 } }, '1페이지 진입'),
                        React.createElement('div', { style: { fontSize: 18, fontWeight: 800, color: gapAnalysis.isOnPage1 ? '#10b981' : '#ef4444' } },
                            gapAnalysis.isOnPage1 ? '진입 \u2705' : '미진입 \u274C'
                        ),
                        React.createElement('div', { style: { fontSize: 12, color: '#64748b', marginTop: 4 } },
                            gapAnalysis.myRank ? '현재 ' + gapAnalysis.myRank + '위' : '순위권 밖'
                        )
                    )
                ),

                /* 격차 바 차트 */
                React.createElement('div', { style: Object.assign({}, v5Card, { padding: 24 }) },
                    React.createElement('div', { style: { fontWeight: 700, fontSize: 14, marginBottom: 16, color: '#0f172a' } }, '\uD83D\uDCCA 상세 비교'),
                    React.createElement(GapBar, { label: '가격 (원)', myVal: gapAnalysis.myPrice, compVal: gapAnalysis.avgCompPrice, unit: '원', reverse: true }),
                    React.createElement(GapBar, { label: '상품명 길이 (글자)', myVal: gapAnalysis.myNameLength, compVal: gapAnalysis.avgNameLength, unit: '자' }),
                    gapAnalysis.myRank && React.createElement(GapBar, { label: '순위', myVal: gapAnalysis.myRank, compVal: 3, unit: '위', reverse: true })
                )
            ),

            /* === 3. AI 기반 맞춤 진입 전략 제안 === */
            strategies.length > 0 && React.createElement('div', { style: { marginBottom: 20 } },
                React.createElement('h3', { style: { fontSize: 16, fontWeight: 700, color: '#0f172a', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 } },
                    React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, borderRadius: 8, background: 'linear-gradient(135deg, #eef2ff, #dbeafe)', fontSize: 14 } }, '\uD83E\uDD16'),
                    ' 3. AI 기반 맞춤 진입 전략 제안'
                ),

                /* 전략 카드들 — v5 스타일 */
                React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
                    strategies.map(function(s, idx) {
                        var cardBorderColor = severityColor(s.severity === 'info' ? 'medium' : s.severity);
                        var cardBg = severityBg(s.severity === 'info' ? 'medium' : s.severity);
                        var insights = s.insights || [];
                        var actions = s.actions || [];
                        var recs = s.recommendations || [];

                        return React.createElement('div', { key: idx, style: Object.assign({}, v5Card, { overflow: 'hidden' }) },
                            /* 카드 헤더 */
                            React.createElement('div', { style: { background: cardBg, padding: '16px 24px', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', gap: 12 } },
                                React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 36, height: 36, borderRadius: 10, background: '#fff', fontSize: 18, border: '1px solid #e2e8f0' } }, s.icon || ''),
                                React.createElement('span', { style: { fontWeight: 700, fontSize: 15, color: '#0f172a', flex: 1 } }, s.area),
                                React.createElement('span', { style: { padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700, color: '#fff', background: severityColor(s.severity) } },
                                    s.severity === 'high' ? '핵심 개선' : s.severity === 'low' ? '강점 유지' : s.severity === 'info' ? '실행 가이드' : '점검 필요'
                                )
                            ),
                            /* 카드 바디 */
                            React.createElement('div', { style: { padding: '20px 24px' } },
                                /* 분석 인사이트 */
                                insights.length > 0 && React.createElement('div', { style: { marginBottom: actions.length > 0 || recs.length > 0 ? 16 : 0 } },
                                    React.createElement('div', { style: { fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 } }, 'INSIGHT'),
                                    insights.map(function(insight, i) {
                                        return React.createElement('div', { key: i, style: { fontSize: 13, color: '#0f172a', lineHeight: 1.7, padding: '5px 0', display: 'flex', gap: 8 } },
                                            React.createElement('span', { style: { color: severityColor(s.severity), flexShrink: 0, marginTop: 2 } }, '\u25B8'),
                                            React.createElement('span', null, insight)
                                        );
                                    })
                                ),
                                /* 액션 아이템 */
                                actions.length > 0 && React.createElement('div', { style: { background: '#f8fafc', borderRadius: 12, padding: '16px 20px', border: '1px solid #e2e8f0', marginBottom: recs.length > 0 ? 16 : 0 } },
                                    React.createElement('div', { style: { fontSize: 11, fontWeight: 700, color: severityColor(s.severity), textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 } }, 'ACTION PLAN'),
                                    actions.map(function(action, i) {
                                        return React.createElement('div', { key: i, style: { fontSize: 13, color: '#0f172a', lineHeight: 1.7, padding: '6px 0', borderBottom: i < actions.length - 1 ? '1px solid #e2e8f0' : 'none', display: 'flex', gap: 10 } },
                                            React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: 6, background: severityColor(s.severity), color: '#fff', fontSize: 11, fontWeight: 700, flexShrink: 0, marginTop: 1 } }, i + 1),
                                            React.createElement('span', null, action)
                                        );
                                    })
                                ),
                                /* 추천 광고 품목 */
                                recs.length > 0 && React.createElement('div', { style: { background: 'linear-gradient(135deg, #eef2ff, #faf5ff)', borderRadius: 12, padding: '16px 20px', border: '1px solid #c7d2fe' } },
                                    React.createElement('div', { style: { fontSize: 11, fontWeight: 700, color: '#4f46e5', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 } },
                                        React.createElement('span', { style: { fontSize: 13 } }, '\uD83D\uDCE2'),
                                        'RECOMMENDED SERVICE'
                                    ),
                                    recs.map(function(rec, i) {
                                        return React.createElement('div', { key: i, style: { padding: '8px 0', borderBottom: i < recs.length - 1 ? '1px solid #ddd6fe' : 'none', display: 'flex', gap: 10, alignItems: 'flex-start' } },
                                            React.createElement('span', { style: { display: 'inline-flex', alignItems: 'center', padding: '4px 12px', borderRadius: 999, background: '#4f46e5', color: '#fff', fontSize: 12, fontWeight: 700, flexShrink: 0, whiteSpace: 'nowrap', marginTop: 1 } }, rec.name),
                                            React.createElement('span', { style: { fontSize: 12, color: '#64748b', lineHeight: 1.6 } }, rec.reason)
                                        );
                                    })
                                )
                            )
                        );
                    })
                )
            ),

            /* 종합 전략 추천 (strategicData 기반 — advertiserData 없을 때만) */
            !advertiserData && recommendation && React.createElement('div', { style: { background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 16, padding: '20px 24px', borderLeft: '4px solid #10b981', marginBottom: 20 } },
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 } },
                    React.createElement('span', { style: { fontSize: 16 } }, '\uD83D\uDCCC'),
                    React.createElement('span', { style: { fontWeight: 700, fontSize: 14, color: '#065f46' } }, '종합 진입 전략'),
                    React.createElement('span', { style: { padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700, color: '#fff', background: '#10b981', marginLeft: 'auto' } }, '전략')
                ),
                React.createElement('p', { style: { lineHeight: 1.7, color: '#0f172a', fontSize: 13, margin: 0 } }, recommendation)
            ),

            /* 분석 시각 */
            React.createElement('div', { style: { marginTop: 16, padding: '12px 16px', background: '#f8fafc', borderRadius: 12, fontSize: 12, color: '#94a3b8', textAlign: 'center', border: '1px solid #e2e8f0' } },
                '네이버 공식 API 기준 분석 결과이며, 실제 검색 노출 순위와 차이가 있을 수 있습니다.',
                advertiserData && advertiserData.analyzed_at ? ' | 분석 시각: ' + new Date(advertiserData.analyzed_at).toLocaleString('ko-KR') : ''
            ),

            /* 반응형 스타일 */
            React.createElement('style', null, '\n@media (max-width: 768px) {\n  #sec-strategy .card-grid-4 { grid-template-columns: 1fr 1fr !important; }\n}\n')
        )
    );
};
