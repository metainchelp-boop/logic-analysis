/* RankTrackingSection — 순위 추적 */
window.RankTrackingSection = function RankTrackingSection({ products, refreshProducts, searchedKeyword, searchedProductUrl, onNavigateToClient, canEdit }) {
    const { useState, useEffect, useRef } = React;
    const [showAddForm, setShowAddForm] = useState(false);
    const [newUrl, setNewUrl] = useState('');
    const [newKeywords, setNewKeywords] = useState('');
    const [adding, setAdding] = useState(false);
    const [refreshing, setRefreshing] = useState({});
    const [expandedProduct, setExpandedProduct] = useState(null);
    const [historyData, setHistoryData] = useState({});
    const lastAutoRegistered = useRef('');
    const productsRef = useRef(products);
    productsRef.current = products;

    // 1회성 순위 조회 결과 (DB 저장 안 함)
    const [tempRankResult, setTempRankResult] = useState(null);
    const [tempRankLoading, setTempRankLoading] = useState(false);
    const lastTempCheckKey = useRef('');

    // 키워드별 노출 분석
    const [exposureResult, setExposureResult] = useState(null);
    const [exposureLoading, setExposureLoading] = useState(false);
    const lastExposureKey = useRef('');

    // 검색 컨텍스트(광고주)가 바뀌면 순위 히스토리 캐시 초기화
    useEffect(function() {
        setHistoryData({});
        setExpandedProduct(null);
        setExposureResult(null);
        lastExposureKey.current = '';
    }, [searchedProductUrl, searchedKeyword]);

    // 검색 시 1회성 순위 조회 (DB 미저장)
    useEffect(function() {
        if (!searchedKeyword || !searchedProductUrl) {
            setTempRankResult(null);
            return;
        }
        var key = searchedProductUrl + '::' + searchedKeyword;
        if (lastTempCheckKey.current === key) return;
        lastTempCheckKey.current = key;

        setTempRankLoading(true);
        setTempRankResult(null);
        api.post('/rank/check', { keyword: searchedKeyword, product_url: searchedProductUrl })
            .then(function(res) {
                if (res && res.success && res.data) {
                    setTempRankResult(res.data);
                } else if (res && !res.success && res.detail) {
                    toast.error(res.detail);
                }
                setTempRankLoading(false);
            })
            .catch(function() {
                setTempRankLoading(false);
            });
    }, [searchedKeyword, searchedProductUrl, canEdit]);

    // 키워드별 노출 분석 (상품명 기반)
    useEffect(function() {
        if (!searchedProductUrl) {
            setExposureResult(null);
            return;
        }
        var key = 'exposure::' + searchedProductUrl;
        if (lastExposureKey.current === key) return;
        lastExposureKey.current = key;

        setExposureLoading(true);
        setExposureResult(null);
        api.post('/rank/keyword-exposure', { product_url: searchedProductUrl })
            .then(function(res) {
                if (res && res.success && res.data) {
                    setExposureResult(res.data);
                }
                setExposureLoading(false);
            })
            .catch(function() {
                setExposureLoading(false);
            });
    }, [searchedProductUrl]);

    // 자동 등록 + 자동 순위체크 제거 — 수동 버튼으로만 실행 (서버 부하 방지)
    // 기존 DB 데이터(스케줄러 수집분)만 표시, 필요시 사용자가 직접 새로고침

    const handleAdd = async () => {
        if (!newUrl || !newKeywords) return;
        setAdding(true);
        try {
            const kws = newKeywords.split(',').map(k => k.trim()).filter(Boolean);
            await api.post('/products/track', { product_url: newUrl, keywords: kws });
            setNewUrl(''); setNewKeywords(''); setShowAddForm(false);
            refreshProducts();
        } catch (e) { toast.error('등록 실패: ' + (e.message || '네트워크 오류')); }
        setAdding(false);
    };

    const handleRefresh = async (productId) => {
        setRefreshing(prev => ({ ...prev, [productId]: true }));
        try {
            await api.post(`/rank/refresh/${productId}`);
            setTimeout(() => {
                refreshProducts();
                setRefreshing(prev => ({ ...prev, [productId]: false }));
            }, 5000);
        } catch (e) {
            toast.error('순위 체크 실패: ' + (e.message || '네트워크 오류'));
            setRefreshing(prev => ({ ...prev, [productId]: false }));
        }
    };

    const handleDelete = async (productId) => {
        if (!confirm('이 상품을 삭제하시겠습니까?')) return;
        try {
            await api.del(`/products/${productId}`);
            refreshProducts();
        } catch (e) {
            toast.error('삭제 실패: ' + (e.message || '네트워크 오류'));
        }
    };

    const loadHistory = async (keywordId) => {
        if (historyData[keywordId]) return;
        try {
            const res = await api.get(`/rank/history/${keywordId}?days=30`);
            if (res.success) setHistoryData(prev => ({ ...prev, [keywordId]: res.data }));
        } catch (e) {
            toast.error('순위 이력 조회 실패');
        }
    };

    // 1회성 순위 결과 블록 카드 렌더링
    var renderTempRankCard = function() {
        if (!searchedProductUrl || !searchedKeyword) return null;

        // 로딩 중
        if (tempRankLoading) {
            return React.createElement('div', { className: 'card fade-in', style: { textAlign: 'center', padding: '24px 16px', color: '#64748b' } },
                React.createElement('div', { style: { fontSize: 14 } }, '순위 조회 중...')
            );
        }

        // 결과 없음
        if (!tempRankResult) return null;

        var d = tempRankResult;
        var pInfo = d.product_info || {};
        var rank = d.rank_position;
        var rankColor = rank && rank > 0
            ? (rank <= 10 ? '#059669' : rank <= 40 ? '#d97706' : '#dc2626')
            : '#94a3b8';
        var rankLabel = rank && rank > 0
            ? (rank <= 10 ? '상위권' : rank <= 40 ? '중위권' : '하위권')
            : '미노출';
        var pageNum = rank && rank > 0 ? Math.ceil(rank / 40) : 0;

        return React.createElement('div', { className: 'fade-in', style: { display: 'flex', flexDirection: 'column', gap: 12 } },
            // 상품 정보 바
            React.createElement('div', { className: 'card', style: { display: 'flex', gap: 12, alignItems: 'center', padding: '12px 16px' } },
                pInfo.image_url && React.createElement('img', { src: pInfo.image_url, alt: '', style: { width: 44, height: 44, borderRadius: 8, objectFit: 'cover', flexShrink: 0 } }),
                React.createElement('div', { style: { minWidth: 0, flex: 1 } },
                    React.createElement('div', { style: { fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
                        pInfo.product_name || '상품 정보'
                    ),
                    React.createElement('div', { style: { fontSize: 11, color: '#64748b' } },
                        (pInfo.store_name || '-') + (pInfo.price > 0 ? '  ·  ' + fmt(pInfo.price) + '원' : '')
                    )
                ),
                React.createElement('span', { style: { background: '#eff6ff', color: '#3b82f6', fontSize: 10, padding: '3px 8px', borderRadius: 6, flexShrink: 0, fontWeight: 500 } }, '실시간 조회')
            ),
            // 핵심 지표 블록 카드 (4열 그리드 — 아래 요약 카드와 동일 레이아웃)
            React.createElement('div', { className: 'card-grid card-grid-4' },
                React.createElement(StatCard, { icon: '🎯', iconColor: 'blue', label: '검색 키워드', value: d.keyword, sub: '분석 대상 키워드' }),
                React.createElement(StatCard, { icon: '📊', iconColor: rank && rank > 0 ? (rank <= 10 ? 'green' : rank <= 40 ? 'amber' : 'red') : 'gray', label: '현재 순위', value: rank && rank > 0 ? rank + '위' : '미노출', sub: rankLabel }),
                React.createElement(StatCard, { icon: '📄', iconColor: 'purple', label: '노출 페이지', value: pageNum > 0 ? pageNum + 'P' : '-', sub: pageNum > 0 ? (pageNum === 1 ? '1페이지 노출' : pageNum + '페이지 노출') : '검색 결과 없음' }),
                React.createElement(StatCard, { icon: '🏆', iconColor: 'amber', label: '상위 경쟁사', value: d.top_competitors ? d.top_competitors.length + '개' : '0개', sub: '상위 노출 상품' })
            ),
            // 경쟁사 블록 카드 (상위 5개를 개별 카드로)
            d.top_competitors && d.top_competitors.length > 0 && React.createElement('div', null,
                React.createElement('div', { style: { fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 8 } }, '상위 경쟁 상품'),
                React.createElement('div', { className: 'card-grid', style: { gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))' } },
                    d.top_competitors.slice(0, 5).map(function(c, i) {
                        return React.createElement('div', { className: 'card', key: i, style: { padding: '12px 14px' } },
                            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 } },
                                React.createElement('span', { style: { fontSize: 11, fontWeight: 700, color: '#fff', background: '#4f46e5', borderRadius: 4, padding: '1px 6px', lineHeight: '1.6' } }, (i + 1) + '위'),
                                React.createElement('span', { style: { fontSize: 11, color: '#64748b' } }, c.store_name || c.mall_name || '-')
                            ),
                            React.createElement('div', { style: { fontSize: 12, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginBottom: 4 } }, c.product_name || c.title || '-'),
                            c.price && React.createElement('div', { style: { fontSize: 12, fontWeight: 600, color: '#0f172a' } }, fmt(c.price) + '원')
                        );
                    })
                )
            ),
            // 안내 문구
            React.createElement('div', { style: { padding: '8px 12px', background: '#f8fafc', borderRadius: 6, fontSize: 11, color: '#94a3b8', lineHeight: '1.5' } },
                '이 결과는 1회성 조회입니다. 지속적인 순위 추적은 관리자에게 상품 등록을 요청하세요.'
            )
        );
    };

    return (
        <div className="section" id="sec-rank">
            <div className="container">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                    <div className="section-title" style={{ marginBottom: 0 }}>
                        <span className="icon" style={{ background: '#eff6ff' }}>📊</span>
                        순위 추적
                    </div>
                    {canEdit !== false && <button className="btn btn-primary btn-sm" onClick={() => setShowAddForm(!showAddForm)}>
                        {showAddForm ? '취소' : '+ 상품 등록'}
                    </button>}
                </div>

                {showAddForm && (
                    <div className="card fade-in" style={{ marginBottom: 16 }}>
                        <div className="form-group">
                            <label className="form-label">상품 URL</label>
                            <input className="form-input" placeholder="https://smartstore.naver.com/스토어명/products/12345" value={newUrl} onChange={e => setNewUrl(e.target.value)} />
                            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>네이버 스마트스토어 상품 페이지 URL을 입력하세요</div>
                        </div>
                        <div className="form-group">
                            <label className="form-label">추적 키워드 (쉼표로 구분)</label>
                            <input className="form-input" placeholder="예: 스마트워치, 블루투스 이어폰" value={newKeywords} onChange={e => setNewKeywords(e.target.value)} />
                            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>여러 키워드는 쉼표(,)로 구분해서 입력하세요 (최대 10개)</div>
                        </div>
                        <button className="btn btn-primary" onClick={handleAdd} disabled={adding || !newUrl.trim() || !newKeywords.trim()}>
                            {adding ? '등록 중...' : '상품 등록'}
                        </button>
                    </div>
                )}

                {/* 실시간 순위 조회 결과 */}
                {renderTempRankCard()}

                {/* 키워드별 노출 분석 */}
                {exposureLoading && (
                    <div className="card fade-in" style={{ textAlign: 'center', padding: '24px 16px', color: '#64748b', marginTop: 16 }}>
                        <div style={{ fontSize: 14 }}>키워드별 노출 순위 분석 중...</div>
                        <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>상품명에서 키워드를 추출하여 각각 순위를 조회하고 있습니다</div>
                    </div>
                )}
                {exposureResult && !exposureLoading && (
                    <div className="fade-in" style={{ marginTop: 16 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                            <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', display: 'flex', alignItems: 'center', gap: 6 }}>
                                <span>🔎</span> 키워드별 노출 순위
                            </div>
                            <div style={{ display: 'flex', gap: 8 }}>
                                <span style={{ padding: '4px 12px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: '#ecfdf5', color: '#10b981' }}>
                                    노출 {exposureResult.exposed_count}개
                                </span>
                                <span style={{ padding: '4px 12px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: '#f1f5f9', color: '#64748b' }}>
                                    전체 {exposureResult.total_keywords}개
                                </span>
                            </div>
                        </div>
                        <div className="card" style={{ padding: 0, overflow: 'hidden', borderRadius: 16 }}>
                            <div style={{ maxHeight: 400, overflowY: 'auto' }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                    <thead>
                                        <tr style={{ background: 'linear-gradient(135deg, #4f46e5, #7c3aed)' }}>
                                            <th style={{ padding: '12px 16px', color: '#fff', fontSize: 12, fontWeight: 600, textAlign: 'center', width: 40 }}>#</th>
                                            <th style={{ padding: '12px 16px', color: '#fff', fontSize: 12, fontWeight: 600, textAlign: 'left' }}>키워드</th>
                                            <th style={{ padding: '12px 16px', color: '#fff', fontSize: 12, fontWeight: 600, textAlign: 'center', width: 80 }}>순위</th>
                                            <th style={{ padding: '12px 16px', color: '#fff', fontSize: 12, fontWeight: 600, textAlign: 'center', width: 70 }}>페이지</th>
                                            <th style={{ padding: '12px 16px', color: '#fff', fontSize: 12, fontWeight: 600, textAlign: 'center', width: 80 }}>상태</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {exposureResult.results.map(function(r, idx) {
                                            var rankColor = r.rank ? (r.rank <= 10 ? '#059669' : r.rank <= 40 ? '#d97706' : '#dc2626') : '#94a3b8';
                                            var statusLabel = r.rank ? (r.rank <= 10 ? '상위권' : r.rank <= 40 ? '1페이지' : '하위권') : '미노출';
                                            var statusBg = r.rank ? (r.rank <= 10 ? '#ecfdf5' : r.rank <= 40 ? '#fffbeb' : '#fef2f2') : '#f8fafc';
                                            return (
                                                <tr key={idx} style={{ borderBottom: '1px solid #e2e8f0', background: idx % 2 === 0 ? '#fff' : '#f8fafc' }}>
                                                    <td style={{ padding: '10px 16px', textAlign: 'center', fontSize: 12, color: '#94a3b8' }}>{idx + 1}</td>
                                                    <td style={{ padding: '10px 16px', fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{r.keyword}</td>
                                                    <td style={{ padding: '10px 16px', textAlign: 'center', fontSize: 14, fontWeight: 700, color: rankColor }}>
                                                        {r.rank ? r.rank + '위' : '-'}
                                                    </td>
                                                    <td style={{ padding: '10px 16px', textAlign: 'center', fontSize: 12, color: '#64748b' }}>
                                                        {r.page ? r.page + 'P' : '-'}
                                                    </td>
                                                    <td style={{ padding: '10px 16px', textAlign: 'center' }}>
                                                        <span style={{ padding: '3px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: statusBg, color: rankColor }}>
                                                            {statusLabel}
                                                        </span>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                        <div style={{ marginTop: 8, fontSize: 11, color: '#94a3b8', lineHeight: 1.6 }}>
                            ※ 상품명에서 추출한 키워드별로 네이버 쇼핑 검색 순위를 조회한 결과입니다. 검색 범위: 상위 300개 상품
                        </div>
                    </div>
                )}

                {/* 등록된 상품 목록 (viewer에게는 숨김 — 1회성 조회만 표시) */}
                {(function() {
                    // viewer는 등록된 상품 목록 표시 안 함
                    if (canEdit === false) {
                        // 1회성 결과도 없고 로딩도 아닌 경우에만 빈 상태 표시
                        if (!tempRankResult && !tempRankLoading && searchedProductUrl) return null;
                        if (!searchedProductUrl) return null;
                        return null;
                    }

                    var filtered = searchedProductUrl
                        ? products.filter(function(p) { return p.product_url === searchedProductUrl; })
                        : products;

                    if (filtered.length === 0) return (
                        <EmptyState icon="📦" text={searchedProductUrl ? "해당 상품의 순위 추적 데이터가 아직 없습니다. 상품이 등록되면 자동으로 표시됩니다." : "추적 중인 상품이 없습니다. 상품을 등록해보세요."} />
                    );

                    /* ===== 특정 업체 분석 결과 → 기존 가로 리스트형 ===== */
                    if (searchedProductUrl) {
                        return (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                                {filtered.map(function(p) {
                                    return React.createElement('div', { className: 'card fade-in', key: p.id },
                                        React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' } },
                                            React.createElement('div', {
                                                style: { display: 'flex', gap: 12, flex: 1, minWidth: 0, cursor: onNavigateToClient ? 'pointer' : 'default' },
                                                onClick: onNavigateToClient ? function() { onNavigateToClient(p.store_name || '', p.product_url || ''); } : undefined,
                                                title: onNavigateToClient ? '클릭하여 업체관리에서 상세 보기' : ''
                                            },
                                                p.image_url && React.createElement('img', { src: p.image_url, alt: '', style: { width: 56, height: 56, borderRadius: 8, objectFit: 'cover', flexShrink: 0 } }),
                                                React.createElement('div', { style: { minWidth: 0 } },
                                                    React.createElement('div', { style: { fontWeight: 600, fontSize: 14, marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: onNavigateToClient ? '#4f46e5' : 'inherit' } },
                                                        p.product_name || '상품',
                                                        onNavigateToClient && React.createElement('span', { style: { fontSize: 11, color: '#818cf8', marginLeft: 6, fontWeight: 400 } }, '→ 업체관리')
                                                    ),
                                                    React.createElement('div', { style: { fontSize: 12, color: '#64748b' } }, p.store_name || '-'),
                                                    p.price > 0 && React.createElement('div', { style: { fontSize: 13, fontWeight: 600, color: '#0f172a', marginTop: 2 } }, fmt(p.price) + '원')
                                                )
                                            ),
                                            canEdit !== false && React.createElement('div', { style: { display: 'flex', gap: 6, flexShrink: 0 } },
                                                React.createElement('button', { className: 'btn btn-secondary btn-sm', onClick: function() { handleRefresh(p.id); }, disabled: refreshing[p.id] },
                                                    refreshing[p.id] ? '체크 중' : '↻ 순위체크'
                                                ),
                                                React.createElement('button', { className: 'btn btn-danger btn-sm', onClick: function() { handleDelete(p.id); } }, '삭제')
                                            )
                                        ),
                                        (p.keywords || []).length > 0 && React.createElement('div', { className: 'table-wrap', style: { marginTop: 14 } },
                                            React.createElement('table', null,
                                                React.createElement('thead', null, React.createElement('tr', null,
                                                    React.createElement('th', null, '키워드'),
                                                    React.createElement('th', null, '현재 순위'),
                                                    React.createElement('th', null, '페이지'),
                                                    React.createElement('th', null, '최근 체크')
                                                )),
                                                React.createElement('tbody', null,
                                                    p.keywords.map(function(k) {
                                                        return React.createElement('tr', { key: k.id, style: { cursor: 'pointer' }, onClick: function() { setExpandedProduct(p.id === expandedProduct ? null : p.id); loadHistory(k.id); } },
                                                            React.createElement('td', { style: { fontWeight: 500 } }, k.keyword),
                                                            React.createElement('td', null,
                                                                k.latest_rank
                                                                    ? React.createElement('span', { style: { fontWeight: 700, color: k.latest_rank <= 10 ? '#059669' : k.latest_rank <= 40 ? '#d97706' : '#dc2626' } }, k.latest_rank + '위')
                                                                    : React.createElement('span', { className: 'badge badge-gray' }, '미노출')
                                                            ),
                                                            React.createElement('td', null, k.latest_rank ? Math.ceil(k.latest_rank / 40) + 'P' : '-'),
                                                            React.createElement('td', { style: { fontSize: 12, color: '#94a3b8' } }, k.last_checked ? new Date(k.last_checked).toLocaleString('ko') : '-')
                                                        );
                                                    })
                                                )
                                            )
                                        )
                                    );
                                })}
                            </div>
                        );
                    }

                    /* ===== 메인 분석 탭 (전체 상품) → 상품별 그룹 카드 2열 ===== */
                    return (
                    <div className="card-grid card-grid-4">
                        {filtered.map(function(p) {
                            var kws = p.keywords || [];
                            return React.createElement('div', {
                                key: p.id,
                                className: 'card fade-in',
                                style: { padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }
                            },
                                /* 상품 헤더 */
                                React.createElement('div', {
                                    style: { display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', background: 'linear-gradient(135deg, #f0f9ff, #eff6ff)', borderBottom: '1px solid #e2e8f0' }
                                },
                                    p.image_url && React.createElement('img', {
                                        src: p.image_url, alt: '',
                                        style: { width: 40, height: 40, borderRadius: 8, objectFit: 'cover', flexShrink: 0 }
                                    }),
                                    React.createElement('div', {
                                        style: { minWidth: 0, flex: 1, cursor: onNavigateToClient ? 'pointer' : 'default' },
                                        onClick: onNavigateToClient ? function() { onNavigateToClient(p.store_name || '', p.product_url || ''); } : undefined,
                                        title: onNavigateToClient ? '클릭하여 업체관리에서 상세 보기' : ''
                                    },
                                        React.createElement('div', {
                                            style: { fontSize: 13, fontWeight: 700, color: onNavigateToClient ? '#4f46e5' : '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
                                        },
                                            p.product_name || '상품',
                                            onNavigateToClient && React.createElement('span', { style: { fontSize: 11, color: '#818cf8', marginLeft: 6, fontWeight: 400 } }, '→ 업체관리')
                                        ),
                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b', marginTop: 1 } },
                                            p.store_name || '-'
                                        )
                                    ),
                                    canEdit !== false && React.createElement('div', { style: { display: 'flex', gap: 4, flexShrink: 0 } },
                                        React.createElement('button', {
                                            className: 'btn btn-secondary btn-sm',
                                            style: { fontSize: 11, padding: '4px 8px', lineHeight: '1.4' },
                                            onClick: function(e) { e.stopPropagation(); handleRefresh(p.id); },
                                            disabled: refreshing[p.id],
                                            title: '순위 체크'
                                        }, refreshing[p.id] ? '체크 중' : '↻ 순위체크'),
                                        React.createElement('button', {
                                            className: 'btn btn-danger btn-sm',
                                            style: { fontSize: 11, padding: '4px 8px', lineHeight: '1.4' },
                                            onClick: function(e) { e.stopPropagation(); handleDelete(p.id); },
                                            title: '상품 삭제'
                                        }, '✕')
                                    )
                                ),
                                /* 키워드 테이블 */
                                kws.length > 0 && React.createElement('div', { style: { overflowX: 'auto', overflowY: kws.length > 5 ? 'auto' : 'visible', maxHeight: kws.length > 5 ? 180 : 'none' } },
                                    React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' } },
                                        React.createElement('colgroup', null,
                                            React.createElement('col', { style: { width: '50%' } }),
                                            React.createElement('col', { style: { width: '30%' } }),
                                            React.createElement('col', { style: { width: '20%' } })
                                        ),
                                        React.createElement('thead', null,
                                            React.createElement('tr', { style: { background: '#fafbfc' } },
                                                React.createElement('th', { style: { fontSize: 10, color: '#94a3b8', fontWeight: 600, textAlign: 'left', padding: '6px 10px 3px', letterSpacing: '0.5px' } }, '키워드'),
                                                React.createElement('th', { style: { fontSize: 10, color: '#94a3b8', fontWeight: 600, textAlign: 'left', padding: '6px 6px 3px', letterSpacing: '0.5px' } }, '순위'),
                                                React.createElement('th', { style: { fontSize: 10, color: '#94a3b8', fontWeight: 600, textAlign: 'left', padding: '6px 6px 3px', letterSpacing: '0.5px' } }, '구분')
                                            )
                                        ),
                                        React.createElement('tbody', null,
                                            kws.map(function(k) {
                                                var rk = k.latest_rank;
                                                var rankColor = rk ? (rk <= 10 ? '#059669' : rk <= 40 ? '#d97706' : '#dc2626') : '#94a3b8';
                                                var rkLabel = rk ? (rk <= 10 ? '상위권' : rk <= 40 ? '중위권' : '하위권') : '미노출';
                                                var badgeBg = rk ? (rk <= 10 ? '#ecfdf5' : rk <= 40 ? '#fffbeb' : '#fef2f2') : '#f1f5f9';
                                                var badgeColor = rk ? (rk <= 10 ? '#059669' : rk <= 40 ? '#d97706' : '#dc2626') : '#94a3b8';
                                                var pg = rk ? Math.ceil(rk / 40) : 0;
                                                return React.createElement('tr', {
                                                    key: k.id,
                                                    style: { cursor: 'pointer', borderTop: '1px solid #f1f5f9' },
                                                    onClick: function() { setExpandedProduct(p.id === expandedProduct ? null : p.id); loadHistory(k.id); }
                                                },
                                                    React.createElement('td', { style: { padding: '6px 10px', fontSize: 12, fontWeight: 600, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, k.keyword),
                                                    React.createElement('td', { style: { padding: '6px 6px', whiteSpace: 'nowrap' } },
                                                        React.createElement('span', { style: { fontSize: 13, fontWeight: 800, letterSpacing: '-0.5px', color: rankColor } }, rk ? rk + '위' : '미노출'),
                                                        pg > 0 && React.createElement('span', { style: { fontSize: 9, padding: '1px 4px', borderRadius: 3, fontWeight: 700, background: '#f1f5f9', color: '#64748b', marginLeft: 4 } }, pg + 'P')
                                                    ),
                                                    React.createElement('td', { style: { padding: '6px 6px', whiteSpace: 'nowrap' } },
                                                        React.createElement('span', { style: { fontSize: 9, padding: '2px 5px', borderRadius: 4, fontWeight: 700, background: badgeBg, color: badgeColor } }, rkLabel)
                                                    )
                                                );
                                            })
                                        )
                                    )
                                ),
                                /* 푸터: 스토어명 + 키워드 개수 */
                                React.createElement('div', {
                                    style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, padding: '6px 14px', background: '#fafbfc', borderTop: '1px solid #f1f5f9' }
                                },
                                    React.createElement('span', { style: { color: '#64748b', fontWeight: 600 } }, p.store_name || '-'),
                                    React.createElement('span', { style: { color: '#94a3b8', fontWeight: 500 } }, '추적 키워드 ' + kws.length + '개')
                                )
                            );
                        })}
                    </div>
                )
                    ; })()}
            </div>
        </div>
    );
};
