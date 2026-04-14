/* ProductNameSection — 상품명 키워드 분석 */
window.ProductNameSection = function ProductNameSection({ keyword, shopProducts }) {
    const { useState, useEffect } = React;
    const [names, setNames] = useState('');
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);

    // 검색 결과의 1페이지 상품명 자동 채우기 + 자동 분석
    useEffect(function() {
        if (shopProducts && shopProducts.length > 0) {
            var productNames = shopProducts.map(function(p) { return p.product_name; }).filter(Boolean);
            setNames(productNames.join('\n'));
            // 자동 분석 실행
            if (productNames.length > 0) {
                setLoading(true);
                setResult(null);
                api.post('/product-name/analyze', { product_names: productNames, keyword: keyword || '' })
                    .then(function(res) { if (res.success) setResult(res.data); setLoading(false); })
                    .catch(function() { setLoading(false); });
            }
        }
    }, [shopProducts, keyword]);

    const handleAnalyze = async () => {
        const nameList = names.split('\n').map(n => n.trim()).filter(Boolean);
        if (nameList.length === 0) return;
        setLoading(true);
        try {
            const res = await api.post('/product-name/analyze', { product_names: nameList, keyword: keyword || '' });
            if (res.success) setResult(res.data);
        } catch (e) { alert('분석 실패'); }
        setLoading(false);
    };

    return (
        <div className="section fade-in" id="sec-productname">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: '#fef2f2' }}>📝</span>
                    상품명 키워드 분석
                </div>
                <div className="card" style={{ marginBottom: 16 }}>
                    <div className="form-group">
                        <label className="form-label">상품명 목록 (한 줄에 하나씩)</label>
                        <textarea
                            style={{ width: '100%', height: 100, padding: 12, border: '1.5px solid #e2e8f0', borderRadius: 8, fontFamily: 'inherit', fontSize: 13, resize: 'vertical', outline: 'none' }}
                            placeholder="경쟁 상품명을 한 줄에 하나씩 입력하세요..."
                            value={names} onChange={e => setNames(e.target.value)}
                        />
                    </div>
                    <button className="btn btn-primary" onClick={handleAnalyze} disabled={loading || !names.trim()}>
                        {loading ? '분석 중...' : '상품명 분석'}
                    </button>
                </div>

                {result && (
                    <div className="fade-in">
                        <div className="card-grid card-grid-3" style={{ marginBottom: 16 }}>
                            <div className="card" style={{ textAlign: 'center' }}>
                                <div className="stat-label">분석 상품 수</div>
                                <div className="stat-value">{result.total_analyzed}</div>
                            </div>
                            <div className="card" style={{ textAlign: 'center' }}>
                                <div className="stat-label">평균 상품명 길이</div>
                                <div className="stat-value">{result.avg_name_length}자</div>
                            </div>
                            <div className="card" style={{ textAlign: 'center' }}>
                                <div className="stat-label">키워드 포함률</div>
                                <div className="stat-value">{result.keyword_coverage != null ? `${result.keyword_coverage}%` : '-'}</div>
                            </div>
                        </div>

                        {result.top_keywords?.length > 0 && (
                            <div className="card">
                                <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>📊 자주 사용된 키워드 TOP 15</div>
                                <div className="table-wrap">
                                    <table>
                                        <thead><tr><th>#</th><th>키워드</th><th>등장 횟수</th><th>사용 비율</th></tr></thead>
                                        <tbody>
                                            {result.top_keywords.slice(0, 15).map((k, i) => (
                                                <tr key={k.word}>
                                                    <td style={{ color: '#94a3b8' }}>{i + 1}</td>
                                                    <td style={{ fontWeight: 500 }}>{k.word}</td>
                                                    <td>{k.count}회</td>
                                                    <td>
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                            <div className="progress-bar" style={{ flex: 1, maxWidth: 100 }}>
                                                                <div className="progress-fill" style={{ width: `${Math.min(k.ratio, 100)}%`, background: '#3b82f6' }} />
                                                            </div>
                                                            <span style={{ fontSize: 12 }}>{k.ratio}%</span>
                                                        </div>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};
