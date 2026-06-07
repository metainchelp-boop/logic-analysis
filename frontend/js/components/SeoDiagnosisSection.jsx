/* SeoDiagnosisSection — SEO 종합 진단 (v5 풀버전) */
window.SeoDiagnosisSection = function SeoDiagnosisSection({ keyword, productUrl: parentProductUrl, competitorData, cachedRank, cachedProductName, cachedTotalVolume, cachedProductInfo, shopProducts }) {
    const { useState, useEffect, useRef } = React;
    const [productUrl, setProductUrl] = useState('');
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);

    const autoTriggered = useRef(false);
    // shopProducts ref — React 17 Promise 내 setState 비배치 문제 방지
    // useEffect 실행 시점에 shopProducts prop이 아직 null일 수 있으므로 ref로 최신값 보장
    const shopProductsRef = useRef(shopProducts);
    shopProductsRef.current = shopProducts;

    useEffect(function() {
        if (parentProductUrl) setProductUrl(parentProductUrl);
    }, [parentProductUrl]);

    useEffect(function() {
        autoTriggered.current = false;
        setResult(null);
    }, [keyword, parentProductUrl]);

    // 자동 실행: 메인 분석 데이터 + shopProducts 모두 도착한 후 실행
    // shopProducts를 deps에 포함하여 데이터 도착 후 재시도 보장
    useEffect(function() {
        if (keyword && productUrl && !autoTriggered.current && !result && !loading
            && (cachedRank || cachedProductName || cachedTotalVolume || cachedProductInfo)
            && shopProducts && shopProducts.length > 0) {
            autoTriggered.current = true;
            handleAnalyze();
        }
    }, [keyword, productUrl, cachedRank, cachedProductName, cachedTotalVolume, cachedProductInfo, shopProducts]);

    const handleAnalyze = async () => {
        if (!productUrl || !keyword) return;
        setLoading(true);
        try {
            var seoBody = { product_url: productUrl, keyword: keyword };
            // 메인 분석 데이터 재활용 → 네이버 API 중복 호출 방지
            if (cachedRank != null) seoBody.cached_rank = cachedRank;
            if (cachedProductName) seoBody.cached_product_name = cachedProductName;
            if (cachedTotalVolume != null) seoBody.cached_total_volume = cachedTotalVolume;
            if (cachedProductInfo) seoBody.cached_product_info = cachedProductInfo;
            // shopProducts에서 competitor 정보 추출 (ref로 최신값 읽기)
            var currentShopProducts = shopProductsRef.current;
            if (currentShopProducts && currentShopProducts.length > 0) {
                seoBody.cached_competitors = currentShopProducts.slice(0, 80).map(function(p) {
                    return { product_id: p.product_id || '', product_name: p.product_name, price: p.price, store_name: p.store_name, brand: p.brand, category1: p.category1, category2: p.category2, product_url: p.product_url };
                });
            }
            const res = await api.post('/seo/analyze', seoBody);
            if (res.success) setResult(res.data);
            else toast.warn(res.detail || 'SEO 분석 데이터 일부를 가져오지 못했습니다.');
        } catch (e) { toast.warn('SEO 분석 요청 실패 — 잠시 후 다시 시도해주세요.'); }
        setLoading(false);
    };

    /* v5 유틸 */
    const getScoreColor = (s) => s >= 70 ? '#10b981' : s >= 40 ? '#f59e0b' : '#ef4444';
    const getScoreLabel = (s) => s >= 70 ? '양호' : s >= 40 ? '보통' : '개선필요';

    return (
        <div className="section fade-in" id="sec-seo">
            <div className="container">
                <div className="card" style={{ padding: '20px 22px' }}>
                <h3 className="rt-h3"><span className="rt-hic">🔧</span>① SEO 종합 진단<span className="badge b-est">≈ 추정</span></h3>
                <div className="rt-desc">10개 평가지표로 상품의 검색 노출 상태를 진단합니다</div>

                <div className="card" style={{ marginBottom: 16, borderRadius: 16 }}>
                    <div style={{ display: 'flex', gap: 10 }}>
                        <input className="form-input" placeholder="분석할 상품 URL을 입력하세요" value={productUrl} onChange={e => setProductUrl(e.target.value)} style={{ flex: 1 }} />
                        <button className="btn btn-primary" onClick={handleAnalyze} disabled={loading || !productUrl || !keyword}>
                            {loading ? '분석 중...' : 'SEO 진단'}
                        </button>
                    </div>
                    {keyword && <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>기준 키워드: <strong>{keyword}</strong></div>}
                </div>

                {loading && <LoadingSpinner text="SEO 분석 중..." />}

                {result && !loading && (
                    <div className="fade-in">
                        {/* 시안 .grid2: 좌측 레이더 + 우측 종합점수/지표바 */}
                        <div className="grid2" style={{ alignItems: 'center', marginBottom: 16 }}>
                            {/* 왼쪽: 10개 지표 레이더 차트 (기존 ChartCanvas 보존) */}
                            <div className="chartbox sm">
                                <ChartCanvas
                                    type="radar"
                                    height={320}
                                    data={{
                                        labels: ['상품명', '검색순위', '가격', '리뷰', '판매', '평점', '카테고리', '브랜드', '네이버페이', '최신성'],
                                        datasets: [{
                                            label: 'SEO 점수',
                                            data: [
                                                result.scores.title || 0, result.scores.rank || 0, result.scores.price || 0,
                                                result.scores.review || 0, result.scores.sales || 0, result.scores.rating || 0,
                                                result.scores.category || 0, result.scores.brand || 0, result.scores.naverpay || 0,
                                                result.scores.freshness || 0
                                            ],
                                            borderColor: '#4f46e5',
                                            backgroundColor: 'rgba(79,70,229,.18)',
                                            pointBackgroundColor: '#4f46e5',
                                            borderWidth: 2
                                        }]
                                    }}
                                    options={{
                                        plugins: { legend: { display: false }, tooltip: { callbacks: { label: function(ctx) { return ctx.label + ' ' + ctx.parsed.r + '점'; } } } },
                                        scales: { r: { beginAtZero: true, max: 100, ticks: { display: false }, pointLabels: { font: { size: 11 } } } }
                                    }}
                                />
                            </div>

                            {/* 오른쪽: 종합점수 + 지표별 스코어바 */}
                            <div>
                                <div style={{ textAlign: 'center', marginBottom: 8 }}>
                                    <span style={{ fontSize: 34, fontWeight: 900, color: getScoreColor(result.scores.total) }}>{result.scores.total}</span>
                                    <span style={{ color: 'var(--rt-sub)' }}>/100 · {getScoreLabel(result.scores.total)}</span>
                                </div>
                                <div className="scorebar"><div className="lbl"><b>상품명</b><span className="w">15%</span></div><div className="track"><i style={{ width: (result.scores.title || 0) + '%' }}></i></div></div>
                                <div className="scorebar"><div className="lbl"><b>검색순위</b><span className="w">15%</span></div><div className="track"><i style={{ width: (result.scores.rank || 0) + '%' }}></i></div></div>
                                <div className="scorebar"><div className="lbl"><b>가격</b><span className="w">12%</span></div><div className="track"><i style={{ width: (result.scores.price || 0) + '%' }}></i></div></div>
                                <div className="scorebar"><div className="lbl"><b>리뷰</b><span className="w">12%</span></div><div className="track"><i style={{ width: (result.scores.review || 0) + '%' }}></i></div></div>
                                <div className="scorebar"><div className="lbl"><b>판매실적</b><span className="w">10%</span></div><div className="track"><i style={{ width: (result.scores.sales || 0) + '%' }}></i></div></div>
                                <div className="scorebar"><div className="lbl"><b>평점</b><span className="w">8%</span></div><div className="track"><i style={{ width: (result.scores.rating || 0) + '%' }}></i></div></div>
                                <div className="scorebar"><div className="lbl"><b>카테고리</b><span className="w">8%</span></div><div className="track"><i style={{ width: (result.scores.category || 0) + '%' }}></i></div></div>
                                <div className="scorebar"><div className="lbl"><b>브랜드</b><span className="w">8%</span></div><div className="track"><i style={{ width: (result.scores.brand || 0) + '%' }}></i></div></div>
                                <div className="scorebar"><div className="lbl"><b>네이버페이</b><span className="w">6%</span></div><div className="track"><i style={{ width: (result.scores.naverpay || 0) + '%' }}></i></div></div>
                                <div className="scorebar"><div className="lbl"><b>최신성</b><span className="w">6%</span></div><div className="track"><i style={{ width: (result.scores.freshness || 0) + '%' }}></i></div></div>
                                {result.scores.detail?.current_rank && (
                                    <div style={{ marginTop: 8, fontSize: 12, color: 'var(--rt-sub)', lineHeight: 1.6, textAlign: 'center' }}>
                                        현재 순위: <strong>{result.scores.detail.current_rank}위</strong> · 추정 월 판매: <strong>{(result.scores.detail.est_monthly_sales || 0).toLocaleString()}건</strong>
                                    </div>
                                )}
                            </div>
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--rt-sub)', marginTop: 6 }}>10개 지표: 상품명·검색순위·가격·리뷰·판매실적·평점·카테고리·브랜드·네이버페이·최신성 (레이더 차트)</div>

                        {/* v5 세부 정보 요약 — 4칼럼 메트릭 카드 */}
                        {result.scores.detail && (
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
                                {[
                                    { label: '키워드 포함', value: result.scores.detail.keyword_in_title ? '포함 ✅' : '미포함 ❌', icon: '🔤', color: result.scores.detail.keyword_in_title ? '#10b981' : '#ef4444', bg: result.scores.detail.keyword_in_title ? '#f0fdf4' : '#fef2f2' },
                                    { label: '가격 비율', value: result.scores.detail.price_ratio > 0 ? (result.scores.detail.price_ratio * 100).toFixed(0) + '%' : (result.scores.detail.my_price > 0 ? '비교불가' : '가격없음'), icon: '💲', color: '#4f46e5', bg: '#eef2ff' },
                                    { label: result.scores.detail.review_source === 'api' ? '실제 리뷰' : '추정 리뷰', value: (result.scores.detail.est_reviews || 0).toLocaleString() + '개', icon: '💬', color: '#7c3aed', bg: '#f5f3ff' },
                                    { label: result.scores.detail.review_source === 'api' ? '실제 평점' : '추정 평점', value: result.scores.detail.est_rating ? result.scores.detail.est_rating.toFixed(1) : '-', icon: '⭐', color: '#f59e0b', bg: '#fffbeb' },
                                ].map((item, i) => (
                                    <div key={i} className="card" style={{ textAlign: 'center', padding: '18px 12px', borderRadius: 14, background: item.bg }}>
                                        <div style={{ fontSize: 18, marginBottom: 8 }}>{item.icon}</div>
                                        <div style={{ fontSize: 14, fontWeight: 800, color: item.color }}>{item.value}</div>
                                        <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>{item.label}</div>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* v5 개선 제안 */}
                        {result.suggestions?.length > 0 && (
                            <div className="card" style={{ borderRadius: 16 }}>
                                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
                                    <span>💡</span> 개선 제안
                                </div>
                                {result.suggestions.map((s, i) => (
                                    <div key={i} style={{
                                        padding: '10px 0', borderBottom: i < result.suggestions.length - 1 ? '1px solid #f1f5f9' : 'none',
                                        fontSize: 13, color: '#334155', display: 'flex', gap: 10, lineHeight: 1.7
                                    }}>
                                        <span style={{
                                            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                            width: 22, height: 22, borderRadius: 6,
                                            background: '#4f46e5', color: '#fff', fontSize: 11, fontWeight: 700,
                                            flexShrink: 0, marginTop: 2
                                        }}>{i + 1}</span>
                                        {s}
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* 산출 근거 */}
                        <div className="note est">
                            ※ 리뷰 수·평점·판매실적·최신성은 순위 구간별 업계 평균 기반 추정치입니다. 네이버 쇼핑 API 한계로 실제 수치와 차이가 있을 수 있으며, 향후 정밀화 예정입니다.
                        </div>
                    </div>
                )}

                </div>
            </div>
        </div>
    );
};
