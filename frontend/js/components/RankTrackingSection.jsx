/* RankTrackingSection — 순위 추적 */
window.RankTrackingSection = function RankTrackingSection({ products, refreshProducts, searchedKeyword, searchedProductUrl, cachedProductName, onNavigateToClient, canEdit, onRankResult }) {
    const { useState, useEffect, useRef } = React;
    const [showAddForm, setShowAddForm] = useState(false);
    const [newUrl, setNewUrl] = useState('');
    const [newKeywords, setNewKeywords] = useState('');
    const [adding, setAdding] = useState(false);
    const [refreshing, setRefreshing] = useState({});
    const [expandedProduct, setExpandedProduct] = useState(null);
    const [expandedKeyword, setExpandedKeyword] = useState(null);
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

    // 검색 컨텍스트(광고주)가 바뀌면 캐시 전체 초기화
    useEffect(function() {
        setHistoryData({});
        setExpandedProduct(null);
        setTempRankResult(null);
        setExposureResult(null);
        lastTempCheckKey.current = '';
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
                    if (onRankResult) onRankResult(res.data);
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
    // cachedProductName이 도착한 후에만 호출 (타이밍 버그 v5.4.16 수정)
    useEffect(function() {
        if (!searchedProductUrl || !searchedKeyword) {
            setExposureResult(null);
            return;
        }
        // cachedProductName이 아직 없으면 대기 (나중에 prop이 채워지면 재실행)
        if (!cachedProductName) return;

        var key = 'exposure::' + searchedProductUrl + '::' + cachedProductName;
        if (lastExposureKey.current === key) return;
        lastExposureKey.current = key;

        setExposureLoading(true);
        setExposureResult(null);
        api.post('/rank/keyword-exposure', { product_url: searchedProductUrl, keyword: searchedKeyword, product_name: cachedProductName })
            .then(function(res) {
                if (res && res.success && res.data) {
                    setExposureResult(res.data);
                } else if (res && !res.success) {
                    toast.warn('키워드 노출 분석: ' + (res.detail || '분석에 실패했습니다'));
                }
                setExposureLoading(false);
            })
            .catch(function() {
                toast.error('키워드 노출 분석 요청 실패');
                setExposureLoading(false);
            });
    }, [searchedProductUrl, searchedKeyword, cachedProductName]);

    // 분석 중인 상품이 추적 등록돼 있으면 30일 순위 추이 차트용 이력을 미리 로드
    useEffect(function() {
        if (!searchedProductUrl || !products) return;
        var tp = products.find(function(p) { return p.product_url === searchedProductUrl; });
        if (!tp) return;
        var kw = (tp.keywords || []).find(function(k) { return k.latest_rank; }) || (tp.keywords || [])[0];
        if (kw && kw.id) loadHistory(kw.id);
    }, [searchedProductUrl, products]);

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

    // 키워드 30일 순위 추이 라인차트 (펼침 행)
    var renderRankHistoryChart = function(keywordId, keywordLabel) {
        var rows = historyData[keywordId];
        if (!rows) {
            return React.createElement('div', { style: { padding: '16px', textAlign: 'center', fontSize: 12, color: '#94a3b8' } }, '순위 이력 불러오는 중...');
        }
        if (rows.length < 2) {
            return React.createElement('div', { style: { padding: '16px', textAlign: 'center', fontSize: 12, color: '#94a3b8' } },
                '30일 추이를 표시하려면 2회 이상의 순위 기록이 필요합니다. (현재 ' + rows.length + '회)');
        }
        var labels = rows.map(function(r) {
            var d = new Date((r.checked_at || '').replace(' ', 'T'));
            return isNaN(d) ? '' : (d.getMonth() + 1) + '/' + d.getDate();
        });
        var data = rows.map(function(r) { return (r.rank_position && r.rank_position > 0) ? r.rank_position : null; });
        var valid = data.filter(function(v) { return v != null; });
        var maxRank = valid.length ? Math.max.apply(null, valid) : 40;
        var C = window.CHART_COLORS || { OK: '#16a34a' };
        return React.createElement('div', { style: { padding: '12px 16px 4px' } },
            React.createElement('div', { style: { fontSize: 12, fontWeight: 700, color: '#0f172a', marginBottom: 8 } },
                '"' + keywordLabel + '" 최근 30일 순위 추이'),
            React.createElement(window.ChartCanvas, {
                type: 'line',
                height: 180,
                data: {
                    labels: labels,
                    datasets: [{
                        label: '순위',
                        data: data,
                        borderColor: C.OK,
                        backgroundColor: 'rgba(22,163,74,.12)',
                        fill: true, tension: 0.35, pointRadius: 2.5, borderWidth: 2.5,
                        spanGaps: true
                    }]
                },
                options: {
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: function(ctx) { return ctx.parsed.y != null ? ctx.parsed.y + '위' : '미노출'; } } }
                    },
                    scales: {
                        y: { reverse: true, suggestedMin: 1, suggestedMax: Math.max(16, maxRank + 2), title: { display: true, text: '순위 (낮을수록 상위 ↑)' }, ticks: { precision: 0 } }
                    }
                }
            }),
            React.createElement('div', { style: { fontSize: 10, color: '#94a3b8', marginTop: 4 } },
                '※ 선이 위로 갈수록 상위 노출. 끊긴 구간은 미노출입니다.')
        );
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
            // 핵심 지표 블록 카드 (3열 그리드 — 아이콘 없음)
            React.createElement('div', { className: 'card-grid card-grid-3' },
                React.createElement('div', { className: 'card', style: { padding: '16px 20px' } },
                    React.createElement('div', { style: { fontSize: 11, color: '#64748b', marginBottom: 6 } }, '검색 키워드'),
                    React.createElement('div', { style: { fontSize: 20, fontWeight: 800, color: '#0f172a' } }, d.keyword),
                    React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginTop: 4 } }, '분석 대상 키워드')
                ),
                React.createElement('div', { className: 'card', style: { padding: '16px 20px' } },
                    React.createElement('div', { style: { fontSize: 11, color: '#64748b', marginBottom: 6 } }, '현재 순위'),
                    React.createElement('div', { style: { fontSize: 20, fontWeight: 800, color: rankColor } }, rank && rank > 0 ? rank + '위' : '미노출'),
                    React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginTop: 4 } }, rankLabel)
                ),
                React.createElement('div', { className: 'card', style: { padding: '16px 20px' } },
                    React.createElement('div', { style: { fontSize: 11, color: '#64748b', marginBottom: 6 } }, '노출 페이지'),
                    React.createElement('div', { style: { fontSize: 20, fontWeight: 800, color: '#0f172a' } }, pageNum > 0 ? pageNum + 'P' : '-'),
                    React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginTop: 4 } }, pageNum > 0 ? (pageNum === 1 ? '1페이지 노출' : pageNum + '페이지 노출') : '검색 결과 없음')
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
                <div className="card" style={{ padding: '20px 22px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                    <div>
                        <h3 className="rt-h3"><span className="rt-hic">📍</span>키워드별 노출 순위<span className="badge b-ok">✅ 실측</span></h3>
                        <div className="rt-desc">상품명에서 추출한 키워드별로 네이버 쇼핑 검색 순위를 조회한 결과 (검색 범위: 상위 300개 상품)</div>
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

                {/* 키워드별 노출 분석 */}
                {exposureLoading && (
                    <div className="card fade-in" style={{ textAlign: 'center', padding: '24px 16px', color: '#64748b', marginTop: 16 }}>
                        <div style={{ fontSize: 14 }}>키워드별 노출 순위 분석 중...</div>
                        <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>상품명에서 키워드를 추출하여 각각 순위를 조회하고 있습니다</div>
                    </div>
                )}
                {exposureResult && !exposureLoading && (function() {
                    var exposed = exposureResult.results.filter(function(r) { return r.rank != null; });
                    var unexposed = exposureResult.results.filter(function(r) { return r.rank == null; });
                    var exposureRate = exposureResult.total_keywords > 0
                        ? Math.round((exposureResult.exposed_count / exposureResult.total_keywords) * 100)
                        : 0;
                    return (
                    <div className="fade-in" style={{ marginTop: 16 }}>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 12 }}>
                            <span className="ps ps-g">노출 {exposureResult.exposed_count}개</span>
                            <span className="ps ps-r">미노출 {unexposed.length}개</span>
                            <span className="ps ps-n">전체 {exposureResult.total_keywords}개</span>
                        </div>

                        {/* 요약 카드 3개 */}
                        <div className="grid3" style={{ marginBottom: 16 }}>
                            <div className="ratecard">
                                <div className="v" style={{ color: 'var(--ok)' }}>{exposureResult.exposed_count}</div>
                                <div className="k">노출 키워드</div>
                            </div>
                            <div className="ratecard">
                                <div className="v" style={{ color: 'var(--red)' }}>{unexposed.length}</div>
                                <div className="k">미노출 키워드</div>
                            </div>
                            <div className="ratecard">
                                <div className="v" style={{ color: 'var(--pur)' }}>{exposureRate}%</div>
                                <div className="k">노출률</div>
                            </div>
                        </div>

                        {/* 2컬럼: 노출 / 미노출 */}
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                            {/* 노출 키워드 */}
                            <div>
                                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                                    <span style={{ color: '#10b981' }}>●</span> 노출 키워드
                                </div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                    {exposed.map(function(r, idx) {
                                        return (
                                            <span key={idx} className={r.rank <= 10 ? 'kwchip' : 'kwchip warn'}>
                                                {r.keyword} <span className="rk">{r.rank}위</span>
                                            </span>
                                        );
                                    })}
                                    {exposed.length === 0 && (
                                        <div style={{ fontSize: 12, color: '#94a3b8' }}>노출된 키워드가 없습니다</div>
                                    )}
                                </div>
                            </div>
                            {/* 미노출 키워드 */}
                            <div>
                                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                                    <span style={{ color: '#ef4444' }}>●</span> 미노출 키워드
                                </div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                    {unexposed.map(function(r, idx) {
                                        return (
                                            <span key={idx} className="kwchip off">{r.keyword}</span>
                                        );
                                    })}
                                    {unexposed.length === 0 && (
                                        <div style={{ fontSize: 12, color: '#94a3b8' }}>모든 키워드에 노출 중입니다</div>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* 30일 순위 추이 차트 (추적 등록된 상품이면 실데이터, 아니면 안내) */}
                        {(function() {
                            var tp = (products || []).find(function(p) { return p.product_url === searchedProductUrl; });
                            var kw = tp && ((tp.keywords || []).find(function(k) { return k.latest_rank; }) || (tp.keywords || [])[0]);
                            var topExposed = exposed.length ? exposed.slice().sort(function(a, b) { return a.rank - b.rank; })[0] : null;
                            var chartTitle = kw ? kw.keyword : (topExposed ? topExposed.keyword : '');
                            return (
                                <div className="sub-card" style={{ marginTop: 16 }}>
                                    <div className="st">📉 {chartTitle ? "'" + chartTitle + "' " : ''}30일 순위 추이 <span className="badge b-est" style={{ marginLeft: 4 }}>신규 차트</span></div>
                                    {kw && kw.id
                                        ? renderRankHistoryChart(kw.id, kw.keyword)
                                        : (
                                            <div style={{ fontSize: 12, color: '#94a3b8', padding: '6px 2px', lineHeight: 1.7 }}>
                                                지속적인 30일 순위 추이는 <b style={{ color: '#475569' }}>관리자에 상품 등록(추적 요청)</b> 후 매일 스냅샷으로 자동 기록됩니다. 등록되면 이 자리에 추이 그래프가 표시됩니다.
                                            </div>
                                        )}
                                </div>
                            );
                        })()}
                    </div>
                    );
                })()}

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
                                                        var isOpen = expandedKeyword === k.id;
                                                        var rowEl = React.createElement('tr', { key: k.id, style: { cursor: 'pointer', background: isOpen ? '#f8fafc' : undefined }, onClick: function() { var next = isOpen ? null : k.id; setExpandedKeyword(next); if (next) loadHistory(k.id); } },
                                                            React.createElement('td', { style: { fontWeight: 500 } },
                                                                React.createElement('span', { style: { color: '#cbd5e1', marginRight: 6, fontSize: 11 } }, isOpen ? '▼' : '▶'),
                                                                k.keyword
                                                            ),
                                                            React.createElement('td', null,
                                                                k.latest_rank
                                                                    ? React.createElement('span', { style: { fontWeight: 700, color: k.latest_rank <= 10 ? '#059669' : k.latest_rank <= 40 ? '#d97706' : '#dc2626' } }, k.latest_rank + '위')
                                                                    : React.createElement('span', { className: 'badge badge-gray' }, '미노출')
                                                            ),
                                                            React.createElement('td', null, k.latest_rank ? Math.ceil(k.latest_rank / 40) + 'P' : '-'),
                                                            React.createElement('td', { style: { fontSize: 12, color: '#94a3b8' } }, k.last_checked ? new Date(k.last_checked).toLocaleString('ko') : '-')
                                                        );
                                                        if (!isOpen) return rowEl;
                                                        var chartRow = React.createElement('tr', { key: k.id + '-chart' },
                                                            React.createElement('td', { colSpan: 4, style: { padding: 0, background: '#f8fafc' } },
                                                                renderRankHistoryChart(k.id, k.keyword)
                                                            )
                                                        );
                                                        return [rowEl, chartRow];
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
                                                var isOpen = expandedKeyword === k.id;
                                                var rowEl = React.createElement('tr', {
                                                    key: k.id,
                                                    style: { cursor: 'pointer', borderTop: '1px solid #f1f5f9', background: isOpen ? '#f8fafc' : undefined },
                                                    onClick: function() { var next = isOpen ? null : k.id; setExpandedKeyword(next); if (next) loadHistory(k.id); }
                                                },
                                                    React.createElement('td', { style: { padding: '6px 10px', fontSize: 12, fontWeight: 600, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
                                                        React.createElement('span', { style: { color: '#cbd5e1', marginRight: 4, fontSize: 9 } }, isOpen ? '▼' : '▶'),
                                                        k.keyword
                                                    ),
                                                    React.createElement('td', { style: { padding: '6px 6px', whiteSpace: 'nowrap' } },
                                                        React.createElement('span', { style: { fontSize: 13, fontWeight: 800, letterSpacing: '-0.5px', color: rankColor } }, rk ? rk + '위' : '미노출'),
                                                        pg > 0 && React.createElement('span', { style: { fontSize: 9, padding: '1px 4px', borderRadius: 3, fontWeight: 700, background: '#f1f5f9', color: '#64748b', marginLeft: 4 } }, pg + 'P')
                                                    ),
                                                    React.createElement('td', { style: { padding: '6px 6px', whiteSpace: 'nowrap' } },
                                                        React.createElement('span', { style: { fontSize: 9, padding: '2px 5px', borderRadius: 4, fontWeight: 700, background: badgeBg, color: badgeColor } }, rkLabel)
                                                    )
                                                );
                                                if (!isOpen) return rowEl;
                                                var chartRow = React.createElement('tr', { key: k.id + '-chart' },
                                                    React.createElement('td', { colSpan: 3, style: { padding: 0, background: '#f8fafc' } },
                                                        renderRankHistoryChart(k.id, k.keyword)
                                                    )
                                                );
                                                return [rowEl, chartRow];
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
        </div>
    );
};
