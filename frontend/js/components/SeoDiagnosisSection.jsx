/* SeoDiagnosisSection — SEO 종합 진단 (10개 평가지표) + 상세페이지 품질 진단 */
window.SeoDiagnosisSection = function SeoDiagnosisSection({ keyword, productUrl: parentProductUrl }) {
    const { useState, useEffect, useRef } = React;
    const [productUrl, setProductUrl] = useState('');
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);

    /* ── 상세페이지 진단 상태 ── */
    const [dpResult, setDpResult] = useState(null);
    const [dpLoading, setDpLoading] = useState(false);
    const [dpError, setDpError] = useState('');

    const autoTriggered = useRef(false);
    const dpAutoTriggered = useRef(false);

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
        dpAutoTriggered.current = false;
        setResult(null);
        setDpResult(null);
        setDpError('');
    }, [keyword]);

    /* SEO 분석 완료 후 상세페이지 분석 자동 실행 */
    useEffect(function() {
        if (result && productUrl && !dpAutoTriggered.current && !dpResult && !dpLoading) {
            dpAutoTriggered.current = true;
            runDetailAnalysis();
        }
    }, [result, productUrl]);

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

    const runDetailAnalysis = async () => {
        if (!productUrl) return;
        setDpLoading(true);
        setDpError('');
        try {
            const res = await api.post('/seo/detail-page', { product_url: productUrl });
            if (res.success) {
                setDpResult(res.data);
            } else {
                setDpError(res.detail || '상세페이지 분석에 실패했습니다.');
            }
        } catch (e) {
            setDpError('상세페이지 분석 오류: ' + e.message);
        }
        setDpLoading(false);
    };

    /* ── 공통 유틸 ── */
    const scoreColor = (s) => s >= 70 ? '#059669' : s >= 40 ? '#d97706' : '#dc2626';
    const scoreBg = (s) => s >= 70 ? '#ecfdf5' : s >= 40 ? '#fffbeb' : '#fef2f2';
    const scoreLabel = (s) => s >= 70 ? '양호' : s >= 40 ? '보통' : '개선필요';
    const scoreGradient = (s) => s >= 70 ? 'linear-gradient(90deg, #34d399, #059669)' : s >= 40 ? 'linear-gradient(90deg, #fbbf24, #d97706)' : 'linear-gradient(90deg, #f87171, #dc2626)';
    const priorityColor = (p) => p === 'high' ? '#dc2626' : p === 'medium' ? '#d97706' : '#6b7280';
    const priorityBg = (p) => p === 'high' ? '#fef2f2' : p === 'medium' ? '#fffbeb' : '#f9fafb';
    const priorityLabel = (p) => p === 'high' ? '긴급' : p === 'medium' ? '권장' : '선택';
    const dpScoreLabel = (s) => s >= 70 ? '우수' : s >= 40 ? '보통' : '미흡';

    const ScoreBar = ({ label, score, icon, weight }) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
            <span style={{ fontSize: 16, width: 24, textAlign: 'center' }}>{icon}</span>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#334155', width: 90, flexShrink: 0 }}>{label}</span>
            <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 6, height: 22, position: 'relative', overflow: 'hidden' }}>
                <div style={{
                    width: score + '%', height: '100%',
                    background: scoreGradient(score),
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

                {/* ================================================================ */}
                {/* ========== 상세페이지 품질 진단 (인라인) ========== */}
                {/* ================================================================ */}
                {productUrl && (
                    <div style={{ marginTop: 24 }}>
                        {/* 헤더 */}
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                <span style={{ fontSize: 20, background: '#fef3c7', borderRadius: 8, padding: '4px 8px' }}>📄</span>
                                <div>
                                    <div style={{ fontWeight: 700, fontSize: 15, color: '#1e293b' }}>상세페이지 품질 진단</div>
                                    <div style={{ fontSize: 11, color: '#94a3b8' }}>Bright Data 프록시를 통한 실시간 HTML 분석</div>
                                </div>
                            </div>
                            {!dpLoading && (
                                <button className="btn btn-primary" onClick={runDetailAnalysis} style={{ fontSize: 12, padding: '6px 14px' }}>
                                    {dpResult ? '재분석' : '분석 시작'}
                                </button>
                            )}
                        </div>

                        {/* 로딩 */}
                        {dpLoading && (
                            <div className="card" style={{ textAlign: 'center', padding: '32px 20px' }}>
                                <LoadingSpinner text="상세페이지 HTML 분석 중... (프록시 경유)" />
                            </div>
                        )}

                        {/* 에러 */}
                        {dpError && !dpLoading && (
                            <div className="card" style={{ background: '#fef2f2', border: '1px solid #fecaca', padding: '14px 18px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#dc2626', fontSize: 13, fontWeight: 600 }}>
                                    <span>⚠️</span> {dpError}
                                </div>
                                <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>
                                    스마트스토어 보안 정책으로 일부 페이지는 분석이 제한될 수 있습니다.
                                </div>
                            </div>
                        )}

                        {/* 결과 표시 */}
                        {dpResult && !dpLoading && (
                            <div className="fade-in">
                                {/* 종합 점수 대형 카드 */}
                                <div className="card" style={{ textAlign: 'center', marginBottom: 16, padding: '20px', background: scoreBg(dpResult.scores.total) }}>
                                    <div style={{ fontSize: 13, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>상세페이지 종합 점수</div>
                                    <div style={{
                                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                        width: 72, height: 72, borderRadius: '50%',
                                        background: '#fff', border: '4px solid ' + scoreColor(dpResult.scores.total),
                                        fontSize: 26, fontWeight: 800, color: scoreColor(dpResult.scores.total)
                                    }}>
                                        {dpResult.scores.total}
                                    </div>
                                    <div style={{ marginTop: 6, fontSize: 13, fontWeight: 700, color: scoreColor(dpResult.scores.total) }}>
                                        {dpScoreLabel(dpResult.scores.total)}
                                    </div>
                                </div>

                                {/* 5대 영역 점수 바 차트 */}
                                <div className="card" style={{ marginBottom: 16 }}>
                                    <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12, display: 'flex', justifyContent: 'space-between' }}>
                                        <span>📊 영역별 점수</span>
                                        <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>비중</span>
                                    </div>
                                    {[
                                        { label: '이미지', score: dpResult.scores.images, icon: '🖼️', weight: '30%' },
                                        { label: '텍스트 콘텐츠', score: dpResult.scores.text, icon: '📝', weight: '20%' },
                                        { label: '동영상', score: dpResult.scores.video, icon: '🎬', weight: '15%' },
                                        { label: '정보 완성도', score: dpResult.scores.info, icon: '📋', weight: '20%' },
                                        { label: '신뢰 요소', score: dpResult.scores.trust, icon: '🛡️', weight: '15%' },
                                    ].map((item, i) => (
                                        <div key={'dp-bar-'+i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: i < 4 ? '1px solid #f1f5f9' : 'none' }}>
                                            <span style={{ fontSize: 16, width: 24, textAlign: 'center' }}>{item.icon}</span>
                                            <span style={{ fontSize: 13, fontWeight: 600, color: '#334155', width: 100, flexShrink: 0 }}>{item.label}</span>
                                            <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 6, height: 22, position: 'relative', overflow: 'hidden' }}>
                                                <div style={{
                                                    width: item.score + '%', height: '100%',
                                                    background: scoreGradient(item.score),
                                                    borderRadius: 6, transition: 'width 0.8s ease'
                                                }} />
                                                <span style={{ position: 'absolute', right: 8, top: 2, fontSize: 11, fontWeight: 700, color: '#1e293b' }}>{item.score}점</span>
                                            </div>
                                            <span style={{ fontSize: 11, color: '#94a3b8', width: 36, textAlign: 'right', flexShrink: 0 }}>{item.weight}</span>
                                        </div>
                                    ))}
                                </div>

                                {/* 주요 지표 카드 그리드 */}
                                <div className="card-grid card-grid-4" style={{ marginBottom: 16 }}>
                                    {[
                                        { label: '상품 이미지', value: dpResult.metrics.total_images + '장', icon: '🖼️', good: dpResult.metrics.total_images >= 10 },
                                        { label: '텍스트 길이', value: dpResult.metrics.text_length > 1000 ? (dpResult.metrics.text_length / 1000).toFixed(1) + 'K자' : dpResult.metrics.text_length + '자', icon: '📝', good: dpResult.metrics.text_length >= 500 },
                                        { label: '동영상', value: dpResult.metrics.video_count + '개', icon: '🎬', good: dpResult.metrics.video_count > 0 },
                                        { label: '페이지 크기', value: dpResult.metrics.html_size_kb + 'KB', icon: '📦', good: dpResult.metrics.html_size_kb >= 50 },
                                    ].map((item, i) => (
                                        <div className="card" key={'dp-metric-'+i} style={{ textAlign: 'center', padding: '12px 8px' }}>
                                            <div style={{ fontSize: 18, marginBottom: 4 }}>{item.icon}</div>
                                            <div style={{ fontSize: 16, fontWeight: 700, color: item.good ? '#059669' : '#dc2626' }}>{item.value}</div>
                                            <div style={{ fontSize: 11, color: '#64748b' }}>{item.label}</div>
                                        </div>
                                    ))}
                                </div>

                                {/* 체크리스트 (불리언 항목) */}
                                <div className="card" style={{ marginBottom: 16 }}>
                                    <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>✅ 필수 항목 체크리스트</div>
                                    {[
                                        { label: '배송 정보 (무료배송/당일출고)', checked: dpResult.metrics.has_delivery_info },
                                        { label: '교환/반품/환불 정책', checked: dpResult.metrics.has_return_info },
                                        { label: '사은품/증정 혜택', checked: dpResult.metrics.has_gift_info },
                                        { label: '인증/수상/특허 표시', checked: dpResult.metrics.has_certification },
                                        { label: '구매 후기/리뷰 섹션', checked: dpResult.metrics.has_review_section },
                                        { label: '스펙/사양 테이블', checked: dpResult.metrics.has_spec_table },
                                    ].map((item, i) => (
                                        <div key={'dp-check-'+i} style={{
                                            display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0',
                                            borderBottom: i < 5 ? '1px solid #f1f5f9' : 'none'
                                        }}>
                                            <span style={{
                                                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                                width: 22, height: 22, borderRadius: '50%', fontSize: 12,
                                                background: item.checked ? '#ecfdf5' : '#fef2f2',
                                                color: item.checked ? '#059669' : '#dc2626',
                                                border: '1px solid ' + (item.checked ? '#a7f3d0' : '#fecaca')
                                            }}>
                                                {item.checked ? '✓' : '✗'}
                                            </span>
                                            <span style={{ fontSize: 13, color: item.checked ? '#334155' : '#94a3b8', fontWeight: item.checked ? 500 : 400 }}>
                                                {item.label}
                                            </span>
                                            <span style={{
                                                marginLeft: 'auto', fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
                                                background: item.checked ? '#ecfdf5' : '#fef2f2',
                                                color: item.checked ? '#059669' : '#dc2626'
                                            }}>
                                                {item.checked ? '확인됨' : '미확인'}
                                            </span>
                                        </div>
                                    ))}
                                </div>

                                {/* 개선 제안 (우선순위별) */}
                                {dpResult.suggestions && dpResult.suggestions.length > 0 && (
                                    <div className="card" style={{ marginBottom: 16 }}>
                                        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>🔧 상세페이지 개선 제안</div>
                                        {dpResult.suggestions.map((s, i) => (
                                            <div key={'dp-sug-'+i} style={{
                                                padding: '12px 14px', marginBottom: i < dpResult.suggestions.length - 1 ? 10 : 0,
                                                background: priorityBg(s.priority), borderRadius: 8,
                                                border: '1px solid ' + (s.priority === 'high' ? '#fecaca' : s.priority === 'medium' ? '#fed7aa' : '#e5e7eb')
                                            }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                                    <span style={{
                                                        fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
                                                        background: priorityColor(s.priority), color: '#fff'
                                                    }}>
                                                        {priorityLabel(s.priority)}
                                                    </span>
                                                    <span style={{ fontSize: 13, fontWeight: 600, color: '#334155' }}>{s.area}</span>
                                                </div>
                                                <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.7 }}>{s.text}</div>
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {/* 분석 안내 */}
                                <div style={{ padding: '10px 14px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 11, color: '#94a3b8', lineHeight: 1.7 }}>
                                    ※ 상세페이지 분석은 Bright Data 프록시를 통해 실시간으로 HTML을 가져와 분석합니다. 스마트스토어 보안 정책에 따라 일부 콘텐츠(JS 렌더링 영역)는 감지되지 않을 수 있습니다.
                                </div>
                            </div>
                        )}
                    </div>
                )}

            </div>
        </div>
    );
};
