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

    const metricCardStyle = {
        background: '#fff',
        borderRadius: 16,
        padding: 24,
        border: '1px solid #e2e8f0',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        textAlign: 'center'
    };

    return (
        <div className="section fade-in" id="sec-productname">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' }}>📝</span>
                    상품명 키워드 분석
                </div>
                <div className="section-line"></div>
                <p className="section-subtitle">경쟁 상품명의 키워드 구성을 분석합니다</p>

                {/* Textarea Input Card */}
                <div className="no-export" style={{
                    background: '#fff',
                    borderRadius: 16,
                    padding: 24,
                    border: '1px solid #e2e8f0',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                    marginBottom: 20
                }}>
                    <div style={{ marginBottom: 12 }}>
                        <label style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                            상품명 목록 (한 줄에 하나씩)
                        </label>
                    </div>
                    <textarea
                        style={{
                            width: '100%',
                            height: 100,
                            padding: 12,
                            border: '1.5px solid #e2e8f0',
                            borderRadius: 12,
                            fontFamily: 'inherit',
                            fontSize: 13,
                            resize: 'vertical',
                            outline: 'none',
                            background: '#f8fafc',
                            color: '#0f172a',
                            boxSizing: 'border-box'
                        }}
                        placeholder="경쟁 상품명을 한 줄에 하나씩 입력하세요..."
                        value={names} onChange={e => setNames(e.target.value)}
                    />
                    <div style={{ marginTop: 12 }}>
                        <button className="btn btn-primary" onClick={handleAnalyze} disabled={loading || !names.trim()}
                            style={{ borderRadius: 12, padding: '10px 24px', fontWeight: 700 }}>
                            {loading ? '분석 중...' : '상품명 분석'}
                        </button>
                    </div>
                </div>

                {result && (
                    <div className="fade-in">
                        {/* Metric Cards - 3 column grid */}
                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(3, 1fr)',
                            gap: 16,
                            marginBottom: 20
                        }}>
                            <div style={metricCardStyle}>
                                <div style={{ fontSize: 18, marginBottom: 8 }}>📦</div>
                                <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>분석 상품 수</div>
                                <div style={{ fontSize: 18, fontWeight: 800, color: '#0f172a' }}>{result.total_analyzed}</div>
                                <div style={{ fontSize: 12, color: '#64748b' }}>개</div>
                            </div>
                            <div style={metricCardStyle}>
                                <div style={{ fontSize: 18, marginBottom: 8 }}>📏</div>
                                <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>평균 상품명 길이</div>
                                <div style={{ fontSize: 18, fontWeight: 800, color: '#0f172a' }}>{result.avg_name_length}</div>
                                <div style={{ fontSize: 12, color: '#64748b' }}>자</div>
                            </div>
                            <div style={metricCardStyle}>
                                <div style={{ fontSize: 18, marginBottom: 8 }}>🎯</div>
                                <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>키워드 포함률</div>
                                <div style={{ fontSize: 18, fontWeight: 800, color: '#0f172a' }}>{result.keyword_coverage != null ? result.keyword_coverage : '-'}</div>
                                <div style={{ fontSize: 12, color: '#64748b' }}>%</div>
                            </div>
                        </div>

                        {/* Keyword Frequency Table */}
                        {result.top_keywords?.length > 0 && (
                            <div style={{
                                background: '#fff',
                                borderRadius: 16,
                                padding: 24,
                                border: '1px solid #e2e8f0',
                                boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
                            }}>
                                <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 16 }}>📊 자주 사용된 키워드 TOP 15</div>
                                <div className="table-wrap">
                                    <table>
                                        <thead>
                                            <tr style={{ background: 'linear-gradient(135deg, #4f46e5, #7c3aed)' }}>
                                                <th style={{ color: '#fff', fontWeight: 600, fontSize: 12 }}>#</th>
                                                <th style={{ color: '#fff', fontWeight: 600, fontSize: 12 }}>키워드</th>
                                                <th style={{ color: '#fff', fontWeight: 600, fontSize: 12 }}>등장 횟수</th>
                                                <th style={{ color: '#fff', fontWeight: 600, fontSize: 12 }}>사용 비율</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {result.top_keywords.slice(0, 15).map((k, i) => (
                                                <tr key={k.word} style={{ background: i % 2 === 0 ? '#fff' : '#f8fafc' }}>
                                                    <td>
                                                        <span style={{
                                                            display: 'inline-flex',
                                                            alignItems: 'center',
                                                            justifyContent: 'center',
                                                            width: 26,
                                                            height: 26,
                                                            background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                                                            color: '#fff',
                                                            borderRadius: '50%',
                                                            fontSize: 11,
                                                            fontWeight: 700
                                                        }}>{i + 1}</span>
                                                    </td>
                                                    <td style={{ fontWeight: 600, color: '#0f172a' }}>{k.word}</td>
                                                    <td style={{ color: '#0f172a' }}>{k.count}회</td>
                                                    <td>
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                            <div style={{
                                                                flex: 1,
                                                                maxWidth: 120,
                                                                height: 8,
                                                                borderRadius: 8,
                                                                background: '#f1f5f9',
                                                                overflow: 'hidden'
                                                            }}>
                                                                <div style={{
                                                                    width: Math.min(k.ratio, 100) + '%',
                                                                    height: '100%',
                                                                    borderRadius: 8,
                                                                    background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                                                                    transition: 'width 0.3s ease'
                                                                }} />
                                                            </div>
                                                            <span style={{ fontSize: 12, color: '#64748b', minWidth: 36 }}>{k.ratio}%</span>
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
