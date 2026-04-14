/* AdvertiserReportSection — 광고주 맞춤 분석 리포트 (순위 현황 + 경쟁사 비교 + 진입 전략) */
window.AdvertiserReportSection = function AdvertiserReportSection(props) {
    if (!props || !props.data) return null;
    var data = props.data;
    var ranking = data.ranking || {};
    var productInfo = data.product_info || {};
    var comparison = data.competitor_comparison || {};
    var compItems = comparison.items || [];
    var compStats = comparison.stats || {};
    var strategy = data.entry_strategy || {};
    var strategies = strategy.strategies || [];
    var overallScore = strategy.overall_score || 0;

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
    var severityLabel = function(s) {
        if (s === 'high') return '개선 필요';
        if (s === 'medium') return '보통';
        if (s === 'low') return '양호';
        return '참고';
    };

    var scoreColor = overallScore >= 70 ? '#16a34a' : overallScore >= 40 ? '#d97706' : '#dc2626';
    var scoreLabel = overallScore >= 70 ? '양호' : overallScore >= 40 ? '보통' : '개선 필요';

    return (
        <div id="sec-advertiser" className="section fade-in" style={{ borderTop: '3px solid #3b82f6' }}>
            <div className="container">

                {/* 헤더 */}
                <h2 className="section-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '22px' }}>📊</span> 광고주 맞춤 분석 리포트
                </h2>
                <div style={{ background: '#eff6ff', borderRadius: '10px', padding: '16px 20px', marginBottom: '24px', display: 'flex', flexWrap: 'wrap', gap: '20px', alignItems: 'center' }}>
                    {productInfo.image_url && (
                        <img src={productInfo.image_url} alt="" style={{ width: '56px', height: '56px', borderRadius: '8px', objectFit: 'cover' }}
                             onError={function(e){ e.target.style.display='none'; }} />
                    )}
                    <div style={{ flex: 1, minWidth: '200px' }}>
                        <div style={{ fontWeight: '700', fontSize: '15px', color: '#1e3a5f', marginBottom: '4px' }}>
                            {productInfo.product_name || '상품 정보 로딩 중...'}
                        </div>
                        <div style={{ fontSize: '13px', color: '#4b5563' }}>
                            {productInfo.store_name && <span style={{ marginRight: '12px' }}>판매처: {productInfo.store_name}</span>}
                            {productInfo.price > 0 && <span>가격: {fmt(productInfo.price)}원</span>}
                        </div>
                    </div>
                    <div style={{ textAlign: 'center', padding: '8px 20px', background: '#fff', borderRadius: '10px', minWidth: '100px' }}>
                        <div style={{ fontSize: '28px', fontWeight: '800', color: scoreColor }}>{overallScore}점</div>
                        <div style={{ fontSize: '12px', color: scoreColor, fontWeight: '600' }}>{scoreLabel}</div>
                    </div>
                </div>

                {/* ===== 1. 순위 현황 ===== */}
                <div style={{ marginBottom: '32px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: '700', color: '#1f2937', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span>🏆</span> 1. 순위 현황
                    </h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
                        <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '10px', padding: '20px', textAlign: 'center' }}>
                            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '8px' }}>현재 순위</div>
                            <div style={{ fontSize: '32px', fontWeight: '800', color: ranking.current_rank ? '#1f2937' : '#dc2626' }}>
                                {ranking.current_rank ? ranking.current_rank + '위' : '미노출'}
                            </div>
                        </div>
                        <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '10px', padding: '20px', textAlign: 'center' }}>
                            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '8px' }}>페이지</div>
                            <div style={{ fontSize: '32px', fontWeight: '800', color: '#1f2937' }}>
                                {ranking.page_number ? ranking.page_number + 'P' : '-'}
                            </div>
                        </div>
                        <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '10px', padding: '20px', textAlign: 'center' }}>
                            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '8px' }}>1페이지 진입</div>
                            <div style={{ fontSize: '32px', fontWeight: '800', color: ranking.is_on_page1 ? '#16a34a' : '#dc2626' }}>
                                {ranking.is_on_page1 ? 'O' : 'X'}
                            </div>
                        </div>
                    </div>
                    {!ranking.current_rank && (
                        <div style={{ marginTop: '12px', padding: '12px 16px', background: '#fef2f2', borderRadius: '8px', fontSize: '13px', color: '#991b1b' }}>
                            해당 키워드 검색 결과 상위 400위 내에서 상품이 발견되지 않았습니다. 상품명 최적화와 키워드 전략이 시급합니다.
                        </div>
                    )}
                </div>

                {/* ===== 2. 경쟁사 비교 분석 ===== */}
                <div style={{ marginBottom: '32px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: '700', color: '#1f2937', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span>📋</span> 2. 경쟁사 비교 분석 (상위 {compItems.length}개 상품)
                    </h3>

                    {/* 통계 요약 */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px', marginBottom: '16px' }}>
                        <div style={{ background: '#f9fafb', borderRadius: '8px', padding: '14px', textAlign: 'center' }}>
                            <div style={{ fontSize: '11px', color: '#6b7280' }}>평균 가격</div>
                            <div style={{ fontSize: '18px', fontWeight: '700', color: '#1f2937' }}>{fmt(compStats.avg_price)}원</div>
                        </div>
                        <div style={{ background: '#f9fafb', borderRadius: '8px', padding: '14px', textAlign: 'center' }}>
                            <div style={{ fontSize: '11px', color: '#6b7280' }}>가격 범위</div>
                            <div style={{ fontSize: '14px', fontWeight: '600', color: '#1f2937' }}>{fmt(compStats.min_price)}~{fmt(compStats.max_price)}원</div>
                        </div>
                        <div style={{ background: '#f9fafb', borderRadius: '8px', padding: '14px', textAlign: 'center' }}>
                            <div style={{ fontSize: '11px', color: '#6b7280' }}>평균 상품명 길이</div>
                            <div style={{ fontSize: '18px', fontWeight: '700', color: '#1f2937' }}>{compStats.avg_name_length}자</div>
                        </div>
                        <div style={{ background: '#f9fafb', borderRadius: '8px', padding: '14px', textAlign: 'center' }}>
                            <div style={{ fontSize: '11px', color: '#6b7280' }}>키워드 포함률</div>
                            <div style={{ fontSize: '18px', fontWeight: '700', color: '#1f2937' }}>{compStats.keyword_in_name_ratio}%</div>
                        </div>
                    </div>

                    {/* 비교표 */}
                    <div className="table-wrap" style={{ maxHeight: '400px', overflowY: 'auto' }}>
                        <table style={{ minWidth: '750px' }}>
                            <thead>
                                <tr>
                                    <th style={{ textAlign: 'center', width: '45px' }}>순위</th>
                                    <th style={{ textAlign: 'center', width: '45px' }}></th>
                                    <th style={{ textAlign: 'left' }}>상품명</th>
                                    <th style={{ textAlign: 'left', width: '80px' }}>판매처</th>
                                    <th style={{ textAlign: 'right', width: '90px' }}>가격</th>
                                    <th style={{ textAlign: 'center', width: '60px' }}>키워드</th>
                                    <th style={{ textAlign: 'left', width: '100px' }}>카테고리</th>
                                </tr>
                            </thead>
                            <tbody>
                                {compItems.map(function(c, idx) {
                                    var isMyProduct = ranking.current_rank && c.rank === ranking.current_rank;
                                    return (
                                        <tr key={idx} style={ isMyProduct ? { background: '#eff6ff', fontWeight: '600' } : {} }>
                                            <td style={{ textAlign: 'center', fontWeight: '600' }}>
                                                {c.rank <= 3 ? (
                                                    <span style={{ display: 'inline-block', width: '24px', height: '24px', lineHeight: '24px', borderRadius: '50%', background: c.rank === 1 ? '#f59e0b' : c.rank === 2 ? '#9ca3af' : '#b45309', color: '#fff', fontSize: '12px', fontWeight: '700' }}>{c.rank}</span>
                                                ) : c.rank}
                                            </td>
                                            <td style={{ textAlign: 'center', padding: '6px' }}>
                                                {c.image_url ? (
                                                    <img src={c.image_url} alt="" style={{ width: '36px', height: '36px', objectFit: 'cover', borderRadius: '6px' }}
                                                         onError={function(e){ e.target.style.display='none'; }} />
                                                ) : null}
                                            </td>
                                            <td style={{ maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '13px' }}>
                                                {isMyProduct && <span style={{ color: '#3b82f6', marginRight: '4px' }}>[내 상품]</span>}
                                                {c.product_name}
                                            </td>
                                            <td style={{ fontSize: '12px', color: '#6b7280' }}>{c.store_name}</td>
                                            <td style={{ textAlign: 'right', fontWeight: '600', fontSize: '13px' }}>{fmt(c.price)}원</td>
                                            <td style={{ textAlign: 'center' }}>
                                                <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: '10px', fontSize: '11px', fontWeight: '600',
                                                    background: c.has_keyword_in_name ? '#dcfce7' : '#fef2f2',
                                                    color: c.has_keyword_in_name ? '#166534' : '#991b1b' }}>
                                                    {c.has_keyword_in_name ? 'O' : 'X'}
                                                </span>
                                            </td>
                                            <td style={{ fontSize: '11px', color: '#6b7280' }}>{c.category}</td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* ===== 3. 1페이지 진입 전략 ===== */}
                <div>
                    <h3 style={{ fontSize: '16px', fontWeight: '700', color: '#1f2937', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span>🎯</span> 3. 1페이지 진입 전략
                    </h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        {strategies.map(function(s, idx) {
                            return (
                                <div key={idx} style={{ background: severityBg(s.severity), border: '1px solid ' + severityColor(s.severity) + '22', borderRadius: '10px', padding: '16px 20px', borderLeft: '4px solid ' + severityColor(s.severity) }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                        <span style={{ fontWeight: '700', fontSize: '14px', color: '#1f2937' }}>{s.area}</span>
                                        <span style={{ padding: '2px 10px', borderRadius: '10px', fontSize: '11px', fontWeight: '700', color: '#fff', background: severityColor(s.severity) }}>
                                            {s.status}
                                        </span>
                                    </div>
                                    <div style={{ display: 'flex', gap: '20px', fontSize: '13px', color: '#4b5563', marginBottom: '6px' }}>
                                        <span>현재: <strong>{s.current}</strong></span>
                                        <span>목표: <strong>{s.target}</strong></span>
                                    </div>
                                    <div style={{ fontSize: '13px', color: '#6b7280', lineHeight: '1.5' }}>{s.detail}</div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                <div style={{ marginTop: '20px', padding: '12px 16px', background: '#f9fafb', borderRadius: '8px', fontSize: '12px', color: '#9ca3af', textAlign: 'center' }}>
                    네이버 공식 API 기준 분석 결과이며, 실제 검색 노출 순위와 차이가 있을 수 있습니다. | 분석 시각: {data.analyzed_at ? new Date(data.analyzed_at).toLocaleString('ko-KR') : '-'}
                </div>
            </div>
        </div>
    );
};
