/* RankTrackingSection — 순위 추적 */
window.RankTrackingSection = function RankTrackingSection({ products, refreshProducts }) {
    const { useState } = React;
    const [showAddForm, setShowAddForm] = useState(false);
    const [newUrl, setNewUrl] = useState('');
    const [newKeywords, setNewKeywords] = useState('');
    const [adding, setAdding] = useState(false);
    const [refreshing, setRefreshing] = useState({});
    const [expandedProduct, setExpandedProduct] = useState(null);
    const [historyData, setHistoryData] = useState({});

    const handleAdd = async () => {
        if (!newUrl || !newKeywords) return;
        setAdding(true);
        try {
            const kws = newKeywords.split(',').map(k => k.trim()).filter(Boolean);
            await api.post('/products/track', { product_url: newUrl, keywords: kws });
            setNewUrl(''); setNewKeywords(''); setShowAddForm(false);
            refreshProducts();
        } catch (e) { alert('등록 실패: ' + e.message); }
        setAdding(false);
    };

    const handleRefresh = async (productId) => {
        setRefreshing(prev => ({ ...prev, [productId]: true }));
        await api.post(`/rank/refresh/${productId}`);
        setTimeout(() => {
            refreshProducts();
            setRefreshing(prev => ({ ...prev, [productId]: false }));
        }, 5000);
    };

    const handleDelete = async (productId) => {
        if (!confirm('이 상품을 삭제하시겠습니까?')) return;
        await api.del(`/products/${productId}`);
        refreshProducts();
    };

    const loadHistory = async (keywordId) => {
        if (historyData[keywordId]) return;
        const res = await api.get(`/rank/history/${keywordId}?days=30`);
        if (res.success) setHistoryData(prev => ({ ...prev, [keywordId]: res.data }));
    };

    return (
        <div className="section" id="sec-rank">
            <div className="container">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                    <div className="section-title" style={{ marginBottom: 0 }}>
                        <span className="icon" style={{ background: '#eff6ff' }}>📊</span>
                        순위 추적
                    </div>
                    <button className="btn btn-primary btn-sm" onClick={() => setShowAddForm(!showAddForm)}>
                        {showAddForm ? '취소' : '+ 상품 등록'}
                    </button>
                </div>

                {showAddForm && (
                    <div className="card fade-in" style={{ marginBottom: 16 }}>
                        <div className="form-group">
                            <label className="form-label">상품 URL</label>
                            <input className="form-input" placeholder="https://smartstore.naver.com/..." value={newUrl} onChange={e => setNewUrl(e.target.value)} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">추적 키워드 (쉼표로 구분)</label>
                            <input className="form-input" placeholder="스마트워치, 블루투스 이어폰" value={newKeywords} onChange={e => setNewKeywords(e.target.value)} />
                        </div>
                        <button className="btn btn-primary" onClick={handleAdd} disabled={adding}>
                            {adding ? '등록 중...' : '상품 등록'}
                        </button>
                    </div>
                )}

                {products.length === 0 ? (
                    <EmptyState icon="📦" text="추적 중인 상품이 없습니다. 상품을 등록해보세요." />
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                        {products.map(p => (
                            <div className="card fade-in" key={p.id}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
                                    <div style={{ display: 'flex', gap: 14, flex: 1, minWidth: 0 }}>
                                        {p.image_url && <img src={p.image_url} alt="" style={{ width: 56, height: 56, borderRadius: 8, objectFit: 'cover', flexShrink: 0 }} />}
                                        <div style={{ minWidth: 0 }}>
                                            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                {p.product_name || '상품명 로딩 중'}
                                            </div>
                                            <div style={{ fontSize: 12, color: '#64748b' }}>{p.store_name || '-'}</div>
                                            {p.price > 0 && <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', marginTop: 2 }}>{fmt(p.price)}원</div>}
                                        </div>
                                    </div>
                                    <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                                        <button className="btn btn-secondary btn-sm" onClick={() => handleRefresh(p.id)} disabled={refreshing[p.id]}>
                                            {refreshing[p.id] ? '체크 중' : '↻ 순위체크'}
                                        </button>
                                        <button className="btn btn-danger btn-sm" onClick={() => handleDelete(p.id)}>삭제</button>
                                    </div>
                                </div>

                                {(p.keywords || []).length > 0 && (
                                    <div className="table-wrap" style={{ marginTop: 14 }}>
                                        <table>
                                            <thead><tr><th>키워드</th><th>현재 순위</th><th>페이지</th><th>최근 체크</th></tr></thead>
                                            <tbody>
                                                {p.keywords.map(k => (
                                                    <tr key={k.id} style={{ cursor: 'pointer' }} onClick={() => { setExpandedProduct(p.id === expandedProduct ? null : p.id); loadHistory(k.id); }}>
                                                        <td style={{ fontWeight: 500 }}>{k.keyword}</td>
                                                        <td>
                                                            {k.latest_rank ? (
                                                                <span style={{ fontWeight: 700, color: k.latest_rank <= 10 ? '#059669' : k.latest_rank <= 40 ? '#d97706' : '#dc2626' }}>
                                                                    {k.latest_rank}위
                                                                </span>
                                                            ) : <span className="badge badge-gray">미노출</span>}
                                                        </td>
                                                        <td>{k.latest_rank ? `${Math.ceil(k.latest_rank / 40)}P` : '-'}</td>
                                                        <td style={{ fontSize: 12, color: '#94a3b8' }}>{k.last_checked ? new Date(k.last_checked).toLocaleString('ko') : '-'}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};
