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

    // viewer 전용: 1회성 순위 조회 결과 (DB 저장 안 함)
    const [tempRankResult, setTempRankResult] = useState(null);
    const [tempRankLoading, setTempRankLoading] = useState(false);
    const lastTempCheckKey = useRef('');

    // 검색 컨텍스트(광고주)가 바뀌면 순위 히스토리 캐시 초기화
    useEffect(function() {
        setHistoryData({});
        setExpandedProduct(null);
    }, [searchedProductUrl, searchedKeyword]);

    // viewer 전용: 검색 시 1회성 순위 조회 (DB 미저장)
    useEffect(function() {
        if (canEdit !== false) return; // viewer만 해당
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

    // 검색 시 상품 URL이 있으면 자동 등록 + 자동 순위체크 (뷰어는 제외)
    useEffect(function() {
        if (canEdit === false) return; // 뷰어는 자동 등록/순위체크 금지
        if (!searchedKeyword || !searchedProductUrl) return;
        var key = searchedProductUrl + '::' + searchedKeyword;
        if (lastAutoRegistered.current === key) return;
        lastAutoRegistered.current = key;

        // 이미 등록된 상품인지 확인 (ref로 최신 products 참조)
        var existingProduct = productsRef.current.find(function(p) {
            return p.product_url === searchedProductUrl;
        });

        if (existingProduct) {
            // 이미 등록됨 → 바로 순위체크 실행
            setRefreshing(function(prev) { var n = {}; for (var k in prev) n[k] = prev[k]; n[existingProduct.id] = true; return n; });
            api.post('/rank/refresh/' + existingProduct.id)
                .then(function() {
                    setTimeout(function() {
                        refreshProducts();
                        setRefreshing(function(prev) { var n = {}; for (var k in prev) n[k] = prev[k]; n[existingProduct.id] = false; return n; });
                    }, 5000);
                })
                .catch(function() {
                    setRefreshing(function(prev) { var n = {}; for (var k in prev) n[k] = prev[k]; n[existingProduct.id] = false; return n; });
                });
            return;
        }

        // 신규 등록 → 등록 후 products 재조회 → 순위체크
        api.post('/products/track', { product_url: searchedProductUrl, keywords: [searchedKeyword] })
            .then(function() {
                // 등록 완료 후 1초 대기 → products 재조회하여 ID 확보
                setTimeout(function() {
                    api.get('/products').then(function(prodRes) {
                        var prodList = (prodRes && prodRes.success && prodRes.data) ? prodRes.data : [];
                        var newProduct = prodList.find(function(p) { return p.product_url === searchedProductUrl; });
                        refreshProducts();
                        if (newProduct) {
                            setRefreshing(function(prev) { var n = {}; for (var k in prev) n[k] = prev[k]; n[newProduct.id] = true; return n; });
                            api.post('/rank/refresh/' + newProduct.id)
                                .then(function() {
                                    setTimeout(function() {
                                        refreshProducts();
                                        setRefreshing(function(prev) { var n = {}; for (var k in prev) n[k] = prev[k]; n[newProduct.id] = false; return n; });
                                    }, 5000);
                                })
                                .catch(function() {
                                    setRefreshing(function(prev) { var n = {}; for (var k in prev) n[k] = prev[k]; n[newProduct.id] = false; return n; });
                                });
                        }
                    }).catch(function() { refreshProducts(); });
                }, 1000);
            })
            .catch(function() {});
    }, [searchedKeyword, searchedProductUrl, canEdit]);

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

    // viewer 전용 1회성 순위 결과 블록 카드 렌더링
    var renderTempRankCard = function() {
        if (canEdit !== false) return null; // viewer만 해당
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
                React.createElement('span', { style: { background: '#eff6ff', color: '#3b82f6', fontSize: 10, padding: '3px 8px', borderRadius: 6, flexShrink: 0, fontWeight: 500 } }, '1회성 조회')
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

                {/* viewer 1회성 순위 조회 결과 */}
                {renderTempRankCard()}

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

                    // 모든 상품의 키워드를 평탄하게 펼침
                    var allKeywords = [];
                    filtered.forEach(function(p) {
                        (p.keywords || []).forEach(function(k) {
                            allKeywords.push({ keyword: k, product: p });
                        });
                    });

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

                    /* ===== 메인 분석 탭 (전체 상품) → 카드 4열 그리드 ===== */
                    return (
                    <div className="card-grid card-grid-4">
                        {allKeywords.map(function(item) {
                            var k = item.keyword;
                            var p = item.product;
                            var rk = k.latest_rank;
                            var rkLabel = rk ? (rk <= 10 ? '상위권' : rk <= 40 ? '중위권' : '하위권') : '미노출';
                            var pg = rk ? Math.ceil(rk / 40) : 0;
                            var badgeBg = rk ? (rk <= 10 ? '#ecfdf5' : rk <= 40 ? '#fffbeb' : '#fef2f2') : '#f1f5f9';
                            var badgeColor = rk ? (rk <= 10 ? '#059669' : rk <= 40 ? '#d97706' : '#dc2626') : '#94a3b8';
                            var rankColor = rk ? (rk <= 10 ? '#059669' : rk <= 40 ? '#d97706' : '#dc2626') : '#94a3b8';
                            return React.createElement('div', {
                                key: k.id,
                                className: 'card fade-in',
                                style: { padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }
                            },
                                React.createElement('div', {
                                    style: { height: 42, background: 'linear-gradient(135deg, #f0f9ff, #eff6ff)', display: 'flex', alignItems: 'center', padding: '0 12px', gap: 10, borderBottom: '1px solid #e2e8f0', cursor: onNavigateToClient ? 'pointer' : 'default' },
                                    onClick: onNavigateToClient ? function(e) { e.stopPropagation(); onNavigateToClient(p.store_name || '', p.product_url || ''); } : undefined,
                                    title: onNavigateToClient ? '클릭하여 업체관리에서 상세 보기' : ''
                                },
                                    p.image_url && React.createElement('img', { src: p.image_url, alt: '', style: { width: 32, height: 32, borderRadius: 6, objectFit: 'cover', flexShrink: 0 } }),
                                    React.createElement('span', { style: { fontSize: 12, color: onNavigateToClient ? '#4f46e5' : '#475569', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, fontWeight: 600 } }, p.product_name || '상품'),
                                    onNavigateToClient && React.createElement('span', { style: { fontSize: 11, color: '#818cf8', flexShrink: 0, fontWeight: 600 } }, '→')
                                ),
                                React.createElement('div', {
                                    style: { padding: '10px 14px', flex: 1, cursor: 'pointer' },
                                    onClick: function() { setExpandedProduct(p.id === expandedProduct ? null : p.id); loadHistory(k.id); }
                                },
                                    React.createElement('div', { style: { fontSize: 14, fontWeight: 700, marginBottom: 4 } }, k.keyword),
                                    React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 6 } },
                                        React.createElement('span', { style: { fontSize: 24, fontWeight: 800, letterSpacing: '-1px', color: rankColor } }, rk ? rk + '위' : '미노출'),
                                        pg > 0 && React.createElement('span', { style: { fontSize: 12, color: '#475569', fontWeight: 600 } }, pg + '페이지')
                                    )
                                ),
                                React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 14px', background: '#f8fafc', borderTop: '1px solid #f1f5f9' } },
                                    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
                                        React.createElement('span', { style: { fontSize: 10, padding: '2px 7px', borderRadius: 4, fontWeight: 700, background: badgeBg, color: badgeColor } }, rkLabel),
                                        React.createElement('span', { style: { fontSize: 11, color: '#64748b', fontWeight: 500 } }, p.store_name || '-')
                                    ),
                                    canEdit !== false && React.createElement('div', { style: { display: 'flex', gap: 4 } },
                                        React.createElement('button', {
                                            className: 'btn btn-secondary btn-sm',
                                            style: { fontSize: 10, padding: '2px 6px', lineHeight: '1.4' },
                                            onClick: function(e) { e.stopPropagation(); handleRefresh(p.id); },
                                            disabled: refreshing[p.id],
                                            title: '순위 체크'
                                        }, refreshing[p.id] ? '...' : '↻'),
                                        React.createElement('button', {
                                            className: 'btn btn-danger btn-sm',
                                            style: { fontSize: 10, padding: '2px 6px', lineHeight: '1.4' },
                                            onClick: function(e) { e.stopPropagation(); handleDelete(p.id); },
                                            title: '상품 삭제'
                                        }, '✕')
                                    )
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
