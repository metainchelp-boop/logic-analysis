/* SeoDiagnosisSection — SEO 종합 진단 */
window.SeoDiagnosisSection = function SeoDiagnosisSection({ keyword }) {
    const { useState } = React;
    const [productUrl, setProductUrl] = useState('');
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);

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
                        <div className="card-grid card-grid-4" style={{ marginBottom: 16 }}>
                            {[
                                { label: '종합 점수', value: result.scores.total, icon: '📊' },
                                { label: '상품명', value: result.scores.title, icon: '📝' },
                                { label: '가격 경쟁력', value: result.scores.price, icon: '💰' },
                                { label: '순위 점수', value: result.scores.rank, icon: '📈' },
                            ].map((item, i) => (
                                <div className="card" key={i} style={{ textAlign: 'center' }}>
                                    <div style={{ fontSize: 20, marginBottom: 6 }}>{item.icon}</div>
                                    <div className="score-ring" style={{ background: scoreBg(item.value), color: scoreColor(item.value), width: 64, height: 64, fontSize: 18 }}>
                                        {item.value}
                                    </div>
                                    <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b' }}>{item.label}</div>
                                </div>
                            ))}
                        </div>

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
                    </div>
                )}
            </div>
        </div>
    );
};
