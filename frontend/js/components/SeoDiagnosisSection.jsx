/* SeoDiagnosisSection — SEO 종합 진단 (v5 풀버전) */
window.SeoDiagnosisSection = function SeoDiagnosisSection({ keyword, productUrl: parentProductUrl, competitorData }) {
    const { useState, useEffect, useRef } = React;
    const [productUrl, setProductUrl] = useState('');
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);

    const autoTriggered = useRef(false);

    useEffect(function() {
        if (parentProductUrl) setProductUrl(parentProductUrl);
    }, [parentProductUrl]);

    useEffect(function() {
        autoTriggered.current = false;
        setResult(null);
    }, [keyword, parentProductUrl]);

    useEffect(function() {
        if (keyword && productUrl && !autoTriggered.current && !result && !loading) {
            autoTriggered.current = true;
            handleAnalyze();
        }
    }, [keyword, productUrl]);

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

    /* v5 유틸 */
    const getScoreColor = (s) => s >= 70 ? '#10b981' : s >= 40 ? '#f59e0b' : '#ef4444';
    const getScoreLabel = (s) => s >= 70 ? '양호' : s >= 40 ? '보통' : '개선필요';
    const getScoreGradient = (s) => s >= 70 ? 'linear-gradient(90deg, #34d399, #059669)' : s >= 40 ? 'linear-gradient(90deg, #fbbf24, #d97706)' : 'linear-gradient(90deg, #f87171, #dc2626)';

    /* v5 스코어바 컴포넌트 */
    const ScoreBar = ({ label, score, icon, weight }) => (
        <div style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 15 }}>{icon}</span> {label}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: getScoreColor(score) }}>{score}점</span>
                    <span style={{ fontSize: 11, color: '#94a3b8' }}>{weight}</span>
                </div>
            </div>
            <div style={{ height: 10, borderRadius: 5, background: '#f1f5f9', overflow: 'hidden' }}>
                <div style={{
                    width: score + '%', height: '100%',
                    background: getScoreGradient(score),
                    borderRadius: 5, transition: 'width 0.8s ease'
                }} />
            </div>
        </div>
    );

    return (
        <div className="section fade-in" id="sec-seo">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: '#faf5ff' }}>🏥</span>
                    SEO 종합 진단
                </div>
                <div className="section-line"></div>
                <p className="section-subtitle">10개 평가지표로 상품의 검색 노출 상태를 진단합니다</p>

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
                        {/* v5 2칼럼: 원형 스코어 + 지표 바 */}
                        <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 16, marginBottom: 16 }}>
                            {/* 왼쪽: 원형 스코어 */}
                            <div className="card" style={{
                                textAlign: 'center', display: 'flex', flexDirection: 'column',
                                alignItems: 'center', justifyContent: 'center', padding: 28, borderRadius: 16
                            }}>
                                <div style={{ fontSize: 14, fontWeight: 600, color: '#64748b', marginBottom: 16 }}>SEO 종합 점수</div>
                                <div style={{
                                    width: 120, height: 120, borderRadius: '50%',
                                    background: 'conic-gradient(' + getScoreColor(result.scores.total) + ' ' + (result.scores.total * 3.6) + 'deg, #f1f5f9 0deg)',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12
                                }}>
                                    <div style={{
                                        width: 96, height: 96, borderRadius: '50%', background: '#fff',
                                        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'
                                    }}>
                                        <div style={{ fontSize: 36, fontWeight: 800, color: getScoreColor(result.scores.total) }}>{result.scores.total}</div>
                                        <div style={{ fontSize: 11, color: '#94a3b8' }}>/ 100</div>
                                    </div>
                                </div>
                                <div style={{
                                    fontSize: 14, fontWeight: 700,
                                    color: getScoreColor(result.scores.total)
                                }}>
                                    {getScoreLabel(result.scores.total)}
                                </div>
                                {result.scores.detail?.current_rank && (
                                    <div style={{ marginTop: 8, fontSize: 12, color: '#64748b', lineHeight: 1.6 }}>
                                        현재 순위: <strong>{result.scores.detail.current_rank}위</strong><br />
                                        추정 월 판매: <strong>{(result.scores.detail.est_monthly_sales || 0).toLocaleString()}건</strong>
                                    </div>
                                )}
                            </div>

                            {/* 오른쪽: 지표별 프로그레스바 */}
                            <div className="card" style={{ padding: 24, borderRadius: 16 }}>
                                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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
                        </div>

                        {/* v5 세부 정보 요약 — 4칼럼 메트릭 카드 */}
                        {result.scores.detail && (
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
                                {[
                                    { label: '키워드 포함', value: result.scores.detail.keyword_in_title ? '포함 ✅' : '미포함 ❌', icon: '🔤', color: result.scores.detail.keyword_in_title ? '#10b981' : '#ef4444', bg: result.scores.detail.keyword_in_title ? '#f0fdf4' : '#fef2f2' },
                                    { label: '가격 비율', value: result.scores.detail.price_ratio > 0 ? (result.scores.detail.price_ratio * 100).toFixed(0) + '%' : (result.scores.detail.my_price > 0 ? '비교불가' : '가격없음'), icon: '💲', color: '#4f46e5', bg: '#eef2ff' },
                                    { label: '추정 리뷰', value: (result.scores.detail.est_reviews || 0).toLocaleString() + '개', icon: '💬', color: '#7c3aed', bg: '#f5f3ff' },
                                    { label: '추정 평점', value: result.scores.detail.est_rating ? result.scores.detail.est_rating.toFixed(1) : '-', icon: '⭐', color: '#f59e0b', bg: '#fffbeb' },
                                ].map((item, i) => (
                                    <div key={i} className="card" style={{ textAlign: 'center', padding: '18px 12px', borderRadius: 14, background: item.bg }}>
                                        <div style={{ fontSize: 20, marginBottom: 8 }}>{item.icon}</div>
                                        <div style={{ fontSize: 20, fontWeight: 800, color: item.color }}>{item.value}</div>
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
                        <div style={{
                            marginTop: 12, padding: '12px 16px',
                            background: 'linear-gradient(135deg, #f0f9ff, #e0f2fe)',
                            borderRadius: 10, border: '1px solid #bae6fd',
                            fontSize: 12, color: '#0369a1', lineHeight: 1.7
                        }}>
                            ※ 리뷰 수·평점·판매실적·최신성은 순위 구간별 업계 평균 기반 추정치입니다. 네이버 쇼핑 API 한계로 실제 수치와 차이가 있을 수 있으며, 향후 정밀화 예정입니다.
                        </div>
                    </div>
                )}

            </div>
        </div>
    );
};
