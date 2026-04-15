/* SeoDiagnosisSection — SEO 종합 진단 (10개 평가지표) */
window.SeoDiagnosisSection = function SeoDiagnosisSection({ keyword, productUrl: parentProductUrl }) {
    const { useState, useEffect } = React;
    const [productUrl, setProductUrl] = useState('');
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);

    const autoTriggered = React.useRef(false);

    useEffect(function() {
        if (parentProductUrl) setProductUrl(parentProductUrl);
    }, [parentProductUrl]);

    useEffect(function() {
        if (keyword && productUrl && !autoTriggered.current && !result && !loading) {
            autoTriggered.current = true;
            handleAnalyze();
        }
    }, [keyword, productUrl]);

    useEffect(function() {
        autoTriggered.current = false;
        setResult(null);
    }, [keyword]);

    const handleAnalyze = async () => {
        if (!productUrl || !keyword) return;
        setLoading(true);
        try {
            const res = await api.post('/seo/analyze', { product_url: productUrl, keyword });
            if (res.success) setResult(res.data);
            else alert(res.detail || 'SEO 분석 실패');
        } catch (e) { alert('SEO 분석 실패: ' + e.message); }
        setLoading(false);
    };

    const scoreColor = (s) => s >= 70 ? '#059669' : s >= 40 ? '#d97706' : '#dc2626';
    const scoreBg = (s) => s >= 70 ? '#ecfdf5' : s >= 40 ? '#fffbeb' : '#fef2f2';
    const scoreLabel = (s) => s >= 70 ? '양호' : s >= 40 ? '보통' : '개선필요';

    const ScoreBar = ({ label, score, icon, weight }) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
            <span style={{ fontSize: 16, width: 24, textAlign: 'center' }}>{icon}</span>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#334155', width: 90, flexShrink: 0 }}>{label}</span>
            <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 6, height: 22, position: 'relative', overflow: 'hidden' }}>
                <div style={{
                    width: score + '%', height: '100%',
                    background: score >= 70 ? 'linear-gradient(90deg, #34d399, #059669)' : score >= 40 ? 'linear-gradient(90deg, #fbbf24, #d97706)' : 'linear-gradient(90deg, #f87171, #dc2626)',
                    borderRadius: 6, transition: 'width 0.8s ease'
                }} />
                <span style={{ position: 'absolute', right: 8, top: 2, fontSize: 11, fontWeight: 700, color: '#1e293b' }}>{score}점</span>
            </div>
            <span style={{ fontSize: 11, color: '#94a3b8', width: 36, textAlign: 'right', flexShrink: 0 }}>{weight}</span>
        </div>
    );

    return (
        <div className="section fade-in" id="sec-seo">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: '#faf5ff' }}>🏥</span>
                    SEO 종합 진단
                </div>

                <div className="card" style={{ marginBottom: 16 }}>
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
                        {/* 종합 점수 대형 카드 */}
                        <div className="card" style={{ textAlign: 'center', marginBottom: 16, padding: '24px 20px', background: scoreBg(result.scores.total) }}>
                            <div style={{ fontSize: 14, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>SEO 종합 점수</div>
                            <div style={{
                                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                width: 80, height: 80, borderRadius: '50%',
                                background: '#fff', border: '4px solid ' + scoreColor(result.scores.total),
                                fontSize: 28, fontWeight: 800, color: scoreColor(result.scores.total)
                            }}>
                                {result.scores.total}
                            </div>
                            <div style={{ marginTop: 8, fontSize: 14, fontWeight: 700, color: scoreColor(result.scores.total) }}>
                                {scoreLabel(result.scores.total)}
                            </div>
                            {result.scores.detail?.current_rank && (
                                <div style={{ marginTop: 4, fontSize: 12, color: '#64748b' }}>
                                    현재 순위: {result.scores.detail.current_rank}위 | 추정 월 판매: {(result.scores.detail.est_monthly_sales || 0).toLocaleString()}건
                                </div>
                            )}
                        </div>

                        {/* 10개 지표 상세 바 차트 */}
                        <div className="card" style={{ marginBottom: 16 }}>
                            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span>📊 평가지표 상세</span>
                                <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>비중</span>
                            </div>
                            <ScoreBar label="상품명" score={result.scores.title} icon="📝" weight="15%" />
                            <ScoreBar label="검색 순위" score={result.scores.rank} icon="📈" weight="15%" />
                            <ScoreBar label="가격 경쟁력" score={result.scores.price} icon="💰" weight="12%" />
                            <ScoreBar label="리뷰 수" score={result.scores.review || 0} icon="💬" weight="12%" />
                            <ScoreBar label="판매실적" score={result.scores.sales || 0} icon="🛒" weight="10%" />
                            <ScoreBar label="상품 평점" score={result.scores.rating || 0} icon="⭐" weight="8%" />
                            <ScoreBar label="카테고리" score={result.scores.category || 0} icon="📂" weight="8%" />
                            <ScoreBar label="브랜드" score={result.scores.brand || 0} icon="🏷️" weight="8%" />
                            <ScoreBar label="네이버페이" score={result.scores.naverpay || 0} icon="💳" weight="6%" />
                            <ScoreBar label="최신성" score={result.scores.freshness || 0} icon="🕐" weight="6%" />
                        </div>

                        {/* 세부 정보 요약 */}
                        {result.scores.detail && (
                            <div className="card-grid card-grid-4" style={{ marginBottom: 16 }}>
                                {[
                                    { label: '키워드 포함', value: result.scores.detail.keyword_in_title ? '포함 ✅' : '미포함 ❌', icon: '🔤' },
                                    { label: '가격 비율', value: result.scores.detail.price_ratio > 0 ? (result.scores.detail.price_ratio * 100).toFixed(0) + '%' : (result.scores.detail.my_price > 0 ? '비교불가' : '가격없음'), icon: '💲' },
                                    { label: '추정 리뷰', value: (result.scores.detail.est_reviews || 0).toLocaleString() + '개', icon: '💬' },
                                    { label: '추정 평점', value: result.scores.detail.est_rating ? result.scores.detail.est_rating.toFixed(1) : '-', icon: '⭐' },
                                ].map((item, i) => (
                                    <div className="card" key={i} style={{ textAlign: 'center', padding: '12px 8px' }}>
                                        <div style={{ fontSize: 18, marginBottom: 4 }}>{item.icon}</div>
                                        <div style={{ fontSize: 16, fontWeight: 700, color: '#1e293b' }}>{item.value}</div>
                                        <div style={{ fontSize: 11, color: '#64748b' }}>{item.label}</div>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* 개선 제안 */}
                        {result.suggestions?.length > 0 && (
                            <div className="card">
                                <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10 }}>💡 개선 제안</div>
                                {result.suggestions.map((s, i) => (
                                    <div key={i} style={{ padding: '8px 0', borderBottom: i < result.suggestions.length - 1 ? '1px solid #f1f5f9' : 'none', fontSize: 13, color: '#334155', display: 'flex', gap: 8 }}>
                                        <span style={{ color: '#3b82f6', flexShrink: 0 }}>•</span>{s}
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* 산출 근거 안내 */}
                        <div style={{ marginTop: 12, padding: '10px 14px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 11, color: '#94a3b8', lineHeight: 1.7 }}>
                            ※ 리뷰 수·평점·판매실적·최신성은 순위 구간별 업계 평균 기반 추정치입니다. 네이버 쇼핑 API 한계로 실제 수치와 차이가 있을 수 있으며, 향후 정밀화 예정입니다.
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
