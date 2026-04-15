/* ClientDashboard — 업체별 분석 관리 대시보드 v3.4 (일자별 누적) */
window.ClientDashboard = function ClientDashboard({ currentUser }) {
    const { useState, useEffect, useCallback } = React;

    const [clients, setClients] = useState([]);
    const [selectedClient, setSelectedClient] = useState(null);
    const [analyses, setAnalyses] = useState([]);
    const [rankHistory, setRankHistory] = useState([]);
    const [analysisHistory, setAnalysisHistory] = useState([]);
    const [loading, setLoading] = useState(false);
    const [analyzing, setAnalyzing] = useState(false);
    const [activeKeyword, setActiveKeyword] = useState(null);
    const [activeAnalysis, setActiveAnalysis] = useState(null);
    const [viewMode, setViewMode] = useState('latest');
    const [message, setMessage] = useState('');
    const [searchQuery, setSearchQuery] = useState('');

    /* 업체 목록 로드 */
    var loadClients = useCallback(function() {
        setLoading(true);
        api.get('/cd/my-clients').then(function(res) {
            if (res.success) setClients(res.data || []);
            setLoading(false);
        }).catch(function() { setLoading(false); });
    }, []);

    useEffect(function() { loadClients(); }, [loadClients]);

    /* 업체 삭제 */
    var deleteClient = function(client, e) {
        e.stopPropagation();
        if (!confirm("'" + client.name + "' 업체를 삭제하시겠습니까?\n\n관련된 모든 분석 데이터와 순위 이력이 함께 삭제됩니다.\n이 작업은 되돌릴 수 없습니다.")) return;
        api.del('/cd/' + client.id).then(function(res) {
            if (res.success) {
                if (selectedClient && selectedClient.id === client.id) {
                    setSelectedClient(null);
                    setActiveKeyword(null);
                    setActiveAnalysis(null);
                }
                loadClients();
            } else {
                alert(res.detail || '삭제에 실패했습니다.');
            }
        }).catch(function() { alert('서버 오류가 발생했습니다.'); });
    };

    /* 업체 검색 필터 */
    var filteredClients = clients.filter(function(c) {
        if (!searchQuery.trim()) return true;
        var q = searchQuery.trim().toLowerCase();
        return (c.name || '').toLowerCase().indexOf(q) !== -1
            || (c.main_keywords || '').toLowerCase().indexOf(q) !== -1
            || (c.business_name || '').toLowerCase().indexOf(q) !== -1;
    });

    /* 업체 선택 → 저장된 분석 로드 */
    var selectClient = function(client) {
        setSelectedClient(client);
        setActiveKeyword(null);
        setActiveAnalysis(null);
        setRankHistory([]);
        setAnalysisHistory([]);
        setViewMode('latest');
        loadAnalyses(client.id);
    };

    var loadAnalyses = function(clientId) {
        api.get('/cd/' + clientId + '/analysis').then(function(res) {
            if (res.success) setAnalyses(res.data || []);
        }).catch(function() {});
    };

    /* 키워드별 고유 목록 추출 */
    var getUniqueKeywords = function() {
        var kwMap = {};
        analyses.forEach(function(a) {
            if (!kwMap[a.keyword] || a.analyzed_date > kwMap[a.keyword].analyzed_date) {
                kwMap[a.keyword] = a;
            }
        });
        return Object.values(kwMap);
    };

    /* 키워드 분석 실행 + 저장 */
    var runAnalysis = function(keyword, productUrl) {
        if (!selectedClient || !keyword) return;
        setAnalyzing(true);
        setMessage('');

        Promise.all([
            api.post('/keyword/volume', [keyword]).catch(function() { return null; }),
            api.post('/keywords/related', { keyword: keyword }).catch(function() { return null; }),
            api.post('/products/search', { keyword: keyword, count: 40 }).catch(function() { return null; }),
        ]).then(function(results) {
            var volRes = results[0];
            var relRes = results[1];
            var shopRes = results[2];

            var vol = (volRes && volRes.success && volRes.data && volRes.data[0]) ? volRes.data[0] : null;
            var totalVol = vol ? ((vol.monthlyPcQcCnt || 0) + (vol.monthlyMobileQcCnt || 0)) : 0;
            var prods = (shopRes && shopRes.success && shopRes.data) ? shopRes.data.products || [] : [];
            var rd = (relRes && relRes.success) ? relRes.data : null;
            var productCount = (shopRes && shopRes.success && shopRes.data) ? shopRes.data.total || prods.length : prods.length;

            var analysis = {};

            if (productCount > 0 && totalVol > 0) {
                var compIdx = (productCount / totalVol).toFixed(2);
                analysis.competitionIndex = {
                    compIndex: parseFloat(compIdx),
                    compLabel: compIdx < 0.5 ? '블루오션' : compIdx < 1.0 ? '보통' : '레드오션',
                    compColor: compIdx < 0.5 ? '#16a34a' : compIdx < 1.0 ? '#d97706' : '#dc2626',
                    productCount: productCount, searchVolume: totalVol
                };
            }
            if (prods.length > 0) {
                var prices = prods.map(function(p) { return p.price; }).filter(function(p) { return p > 0; });
                var avgPrice = prices.length > 0 ? Math.round(prices.reduce(function(a, b) { return a + b; }, 0) / prices.length) : 0;
                analysis.marketRevenue = { avgPrice: avgPrice, estimatedMonthly: avgPrice * totalVol };
            }
            if (totalVol > 0) {
                analysis.summaryCards = { totalVolume: totalVol, productCount: productCount, compLevel: analysis.competitionIndex ? analysis.competitionIndex.compLabel : '-' };
            }
            if (vol) {
                analysis.advertiserInfo = { adDepth: vol.plAvgDepth || 0, pcClicks: (vol.monthlyAvePcClkCnt || 0).toFixed(1), mobileClicks: (vol.monthlyAveMobileClkCnt || 0).toFixed(1), compIdx: vol.compIdx || '-' };
            }

            api.post('/cd/analyze', {
                client_id: selectedClient.id,
                keyword: keyword,
                product_url: productUrl || '',
                analysis_data: analysis,
                volume_data: volRes && volRes.success ? volRes.data : {},
                related_data: rd || {},
                shop_products: prods.slice(0, 20),
                advertiser_data: vol || {}
            }).then(function(saveRes) {
                setMessage(saveRes.message || '저장 완료');
                loadAnalyses(selectedClient.id);
                viewKeywordAnalysis(keyword);

                if (productUrl && prods.length > 0) {
                    var found = null;
                    var pid = extractPid(productUrl);
                    for (var i = 0; i < prods.length; i++) {
                        if (prods[i].product_id === pid || (prods[i].product_url && prods[i].product_url.indexOf(pid) !== -1)) {
                            found = { rank: prods[i].rank, page: 1 }; break;
                        }
                    }
                    if (found) {
                        api.post('/cd/rank-save', {
                            client_id: selectedClient.id, keyword: keyword,
                            product_url: productUrl, rank_position: found.rank, page_number: found.page
                        });
                    }
                }
                setAnalyzing(false);
            }).catch(function() { setAnalyzing(false); });
        }).catch(function() { setAnalyzing(false); });
    };

    function extractPid(url) {
        var m = url.match(/products\/(\d+)/);
        return m ? m[1] : url;
    }

    /* 키워드별 분석 보기 (최신 + 히스토리) */
    var viewKeywordAnalysis = function(keyword) {
        setActiveKeyword(keyword);
        setViewMode('latest');

        /* 최신 분석 로드 */
        api.get('/cd/' + selectedClient.id + '/analysis?keyword=' + encodeURIComponent(keyword)).then(function(res) {
            if (res.success && res.data && res.data.length > 0) {
                setActiveAnalysis(res.data[0]);
            }
        });

        /* 일자별 히스토리 로드 */
        api.get('/cd/' + selectedClient.id + '/history?keyword=' + encodeURIComponent(keyword)).then(function(res) {
            if (res.success) setAnalysisHistory(res.data || []);
        });

        /* 순위 이력 로드 */
        api.get('/cd/' + selectedClient.id + '/rank-history?keyword=' + encodeURIComponent(keyword)).then(function(res) {
            if (res.success) setRankHistory(res.data || []);
        });
    };

    /* HTML 보고서 다운로드 — 저장된 HTML 사용 */
    var downloadReport = function(dateStr) {
        if (!selectedClient || !activeKeyword) return;
        var targetDate = dateStr || (activeAnalysis && activeAnalysis.analyzed_date) || '';
        if (!targetDate) { alert('보고서 날짜를 확인할 수 없습니다.'); return; }

        api.get('/cd/' + selectedClient.id + '/report-html?keyword=' + encodeURIComponent(activeKeyword) + '&date=' + targetDate)
            .then(function(res) {
                if (res.success && res.html) {
                    var blob = new Blob([res.html], { type: 'text/html;charset=utf-8' });
                    var a = document.createElement('a');
                    a.href = URL.createObjectURL(blob);
                    a.download = (selectedClient.name || '업체') + '_' + activeKeyword + '_보고서_' + targetDate + '.html';
                    a.click();
                    URL.revokeObjectURL(a.href);
                } else {
                    alert('해당 날짜의 HTML 보고서가 없습니다.\n분석 탭에서 업체 저장 시 보고서가 자동 생성됩니다.');
                }
            }).catch(function() {
                alert('보고서를 불러올 수 없습니다.');
            });
    };

    var exportReport = function() {
        downloadReport(null);
    };

    function _fmt(n) { return n != null ? Number(n).toLocaleString('ko-KR') : '-'; }

    var uniqueKeywords = getUniqueKeywords();

    /* ==================== 렌더링 ==================== */
    return (
        <div style={{ minHeight: 'calc(100vh - 60px)', background: '#f0f2f5' }}>
            <div className="container" style={{ display: 'flex', gap: 20, paddingTop: 20, minHeight: 'calc(100vh - 80px)' }}>
                {/* 좌측: 업체 목록 */}
                <div style={{ width: 280, flexShrink: 0 }}>
                    <div className="card" style={{ padding: 16 }}>
                        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>내 업체 목록 ({clients.length})</div>
                        {clients.length > 3 && (
                            <input className="form-input"
                                placeholder="업체명 / 키워드 검색..."
                                value={searchQuery}
                                onChange={function(e) { setSearchQuery(e.target.value); }}
                                style={{ width: '100%', marginBottom: 10, fontSize: 13, padding: '8px 12px' }}
                            />
                        )}
                        {loading && <div style={{ color: '#64748b', fontSize: 13 }}>로딩 중...</div>}
                        {!loading && clients.length === 0 && (
                            <div style={{ color: '#94a3b8', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
                                등록된 업체가 없습니다.<br />분석 탭에서 업체를 등록해주세요.
                            </div>
                        )}
                        {!loading && clients.length > 0 && filteredClients.length === 0 && (
                            <div style={{ color: '#94a3b8', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
                                검색 결과가 없습니다.
                            </div>
                        )}
                        <div style={{ maxHeight: 'calc(100vh - 220px)', overflowY: 'auto' }}>
                        {filteredClients.map(function(c) {
                            var isActive = selectedClient && selectedClient.id === c.id;
                            return (
                                <div key={c.id} onClick={function() { selectClient(c); }}
                                    style={{
                                        padding: '12px 14px', borderRadius: 8, cursor: 'pointer', marginBottom: 6,
                                        background: isActive ? '#1B2A4A' : '#f8fafc',
                                        color: isActive ? '#fff' : '#1e293b',
                                        border: '1px solid ' + (isActive ? '#1B2A4A' : '#e2e8f0'),
                                        transition: 'all 0.15s'
                                    }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ fontWeight: 600, fontSize: 14 }}>{c.name || c.business_name}</div>
                                            <div style={{ fontSize: 11, opacity: 0.7, marginTop: 2 }}>
                                                {c.unique_keyword_count > 0 ? '키워드 ' + c.unique_keyword_count + '개' : ''}
                                                {c.total_analysis_days > 0 ? ' | ' + c.total_analysis_days + '일 분석' : ''}
                                                {!c.unique_keyword_count && !c.total_analysis_days ? '미분석' : ''}
                                            </div>
                                            {c.main_keywords && (
                                                <div style={{ fontSize: 11, opacity: 0.6, marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.main_keywords}</div>
                                            )}
                                        </div>
                                        <button onClick={function(e) { deleteClient(c, e); }}
                                            title="업체 삭제"
                                            style={{
                                                background: 'none', border: 'none', cursor: 'pointer', padding: '2px 6px',
                                                fontSize: 14, color: isActive ? 'rgba(255,255,255,0.5)' : '#cbd5e1',
                                                flexShrink: 0, lineHeight: 1,
                                            }}
                                            onMouseOver={function(e) { e.target.style.color = '#ef4444'; }}
                                            onMouseOut={function(e) { e.target.style.color = isActive ? 'rgba(255,255,255,0.5)' : '#cbd5e1'; }}
                                        >{'\u2715'}</button>
                                    </div>
                                </div>
                            );
                        })}
                        </div>
                    </div>
                </div>

                {/* 우측: 분석 내용 */}
                <div style={{ flex: 1 }}>
                    {!selectedClient && (
                        <div className="card" style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>
                            <div style={{ fontSize: 48, marginBottom: 12 }}>📊</div>
                            <div style={{ fontSize: 16 }}>좌측에서 업체를 선택하세요</div>
                            <div style={{ fontSize: 13, marginTop: 8 }}>분석 탭에서 키워드 분석 후 업체를 등록하면 여기에 표시됩니다.</div>
                        </div>
                    )}

                    {selectedClient && (
                        <div>
                            {/* 업체 헤더 */}
                            <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <div>
                                        <div style={{ fontSize: 20, fontWeight: 700 }}>{selectedClient.name}</div>
                                        <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
                                            {selectedClient.main_keywords && <span>키워드: {selectedClient.main_keywords}</span>}
                                            {selectedClient.naver_store_url && <span style={{ marginLeft: 12 }}>URL: {selectedClient.naver_store_url.length > 50 ? selectedClient.naver_store_url.slice(0, 50) + '...' : selectedClient.naver_store_url}</span>}
                                        </div>
                                    </div>
                                    <div style={{ fontSize: 12, color: '#94a3b8' }}>
                                        {selectedClient.last_analyzed && '마지막 분석: ' + selectedClient.last_analyzed.slice(0, 10)}
                                    </div>
                                </div>
                            </div>

                            {/* 새 분석 실행 폼 */}
                            <AnalysisForm
                                client={selectedClient}
                                onAnalyze={runAnalysis}
                                analyzing={analyzing}
                                message={message}
                            />

                            {/* 키워드 목록 (pill 버튼) */}
                            {uniqueKeywords.length > 0 && (
                                <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>분석 키워드 ({uniqueKeywords.length}개)</div>
                                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                                        {uniqueKeywords.map(function(a, i) {
                                            var isActive = activeKeyword === a.keyword;
                                            return (
                                                <button key={i} onClick={function() { viewKeywordAnalysis(a.keyword); }}
                                                    style={{
                                                        padding: '8px 16px', borderRadius: 20, cursor: 'pointer', fontSize: 13,
                                                        background: isActive ? '#1B2A4A' : '#f1f5f9',
                                                        color: isActive ? '#fff' : '#475569',
                                                        border: isActive ? '1px solid #1B2A4A' : '1px solid #e2e8f0'
                                                    }}>
                                                    {a.keyword}
                                                    <span style={{ fontSize: 11, opacity: 0.7, marginLeft: 6 }}>{(a.analyzed_date || '').slice(0, 10)}</span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {/* 키워드 선택 시 상세 보기 */}
                            {activeKeyword && (
                                <div>
                                    {/* 보기 모드 전환 */}
                                    <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                                        <button onClick={function() { setViewMode('latest'); }}
                                            style={{
                                                padding: '8px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                                background: viewMode === 'latest' ? '#1B2A4A' : '#fff',
                                                color: viewMode === 'latest' ? '#fff' : '#475569',
                                                border: viewMode === 'latest' ? 'none' : '1px solid #e2e8f0',
                                            }}>최신 분석</button>
                                        <button onClick={function() { setViewMode('history'); }}
                                            style={{
                                                padding: '8px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                                background: viewMode === 'history' ? '#1B2A4A' : '#fff',
                                                color: viewMode === 'history' ? '#fff' : '#475569',
                                                border: viewMode === 'history' ? 'none' : '1px solid #e2e8f0',
                                            }}>일자별 추이 ({analysisHistory.length}일)</button>
                                        {rankHistory.length > 0 && <button onClick={function() { setViewMode('rank'); }}
                                            style={{
                                                padding: '8px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                                background: viewMode === 'rank' ? '#1B2A4A' : '#fff',
                                                color: viewMode === 'rank' ? '#fff' : '#475569',
                                                border: viewMode === 'rank' ? 'none' : '1px solid #e2e8f0',
                                            }}>순위 이력 ({rankHistory.length}건)</button>}
                                        <div style={{ flex: 1 }} />
                                        <button className="btn btn-primary" onClick={exportReport}
                                            style={{ fontSize: 13, padding: '8px 16px' }}>HTML 보고서</button>
                                    </div>

                                    {/* 최신 분석 결과 */}
                                    {viewMode === 'latest' && activeAnalysis && activeAnalysis.analysis_data && (
                                        <AnalysisResultView
                                            keyword={activeKeyword}
                                            data={activeAnalysis.analysis_data}
                                            rankHistory={rankHistory}
                                            onExport={exportReport}
                                            hideHeader={true}
                                        />
                                    )}

                                    {/* 일자별 추이 테이블 */}
                                    {viewMode === 'history' && (
                                        <div className="card" style={{ padding: 20 }}>
                                            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>"{activeKeyword}" 일자별 분석 추이</div>
                                            {analysisHistory.length === 0 ? (
                                                <div style={{ textAlign: 'center', padding: 30, color: '#94a3b8', fontSize: 13 }}>
                                                    아직 누적된 분석 데이터가 없습니다. 매일 분석을 실행하면 여기에 추이가 표시됩니다.
                                                </div>
                                            ) : (
                                                <div className="table-wrap">
                                                    <table>
                                                        <thead>
                                                            <tr>
                                                                <th>날짜</th>
                                                                <th style={{ textAlign: 'right' }}>검색량</th>
                                                                <th style={{ textAlign: 'right' }}>상품 수</th>
                                                                <th>경쟁강도</th>
                                                                <th style={{ textAlign: 'right' }}>경쟁지수</th>
                                                                <th style={{ textAlign: 'right' }}>평균가격</th>
                                                                <th style={{ textAlign: 'right' }}>시장규모</th>
                                                                <th style={{ textAlign: 'center' }}>보고서</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                                            {analysisHistory.map(function(h, i) {
                                                                var prevH = i > 0 ? analysisHistory[i - 1] : null;
                                                                var compIdxDiff = (prevH && h.comp_index != null && prevH.comp_index != null) ? (h.comp_index - prevH.comp_index).toFixed(2) : null;
                                                                return (
                                                                    <tr key={i}>
                                                                        <td style={{ fontWeight: 600 }}>{h.date}</td>
                                                                        <td style={{ textAlign: 'right' }}>{h.search_volume || '-'}</td>
                                                                        <td style={{ textAlign: 'right' }}>{h.product_count || '-'}</td>
                                                                        <td>
                                                                            <span style={{
                                                                                padding: '2px 8px', borderRadius: 10, fontSize: 12, fontWeight: 600,
                                                                                background: h.comp_level === '블루오션' ? '#dcfce7' : h.comp_level === '보통' ? '#fef9c3' : h.comp_level === '레드오션' ? '#fee2e2' : '#f1f5f9',
                                                                                color: h.comp_level === '블루오션' ? '#16a34a' : h.comp_level === '보통' ? '#ca8a04' : h.comp_level === '레드오션' ? '#dc2626' : '#64748b',
                                                                            }}>{h.comp_level || '-'}</span>
                                                                        </td>
                                                                        <td style={{ textAlign: 'right' }}>
                                                                            {h.comp_index != null ? h.comp_index : '-'}
                                                                            {compIdxDiff && compIdxDiff != '0.00' && (
                                                                                <span style={{ fontSize: 11, marginLeft: 4, color: compIdxDiff > 0 ? '#dc2626' : '#16a34a' }}>
                                                                                    {compIdxDiff > 0 ? '+' : ''}{compIdxDiff}
                                                                                </span>
                                                                            )}
                                                                        </td>
                                                                        <td style={{ textAlign: 'right' }}>{h.avg_price || '-'}</td>
                                                                        <td style={{ textAlign: 'right' }}>{h.market_size || '-'}</td>
                                                                        <td style={{ textAlign: 'center' }}>
                                                                            <button onClick={function() { downloadReport(h.date); }}
                                                                                style={{
                                                                                    padding: '4px 10px', borderRadius: 6, fontSize: 11, cursor: 'pointer',
                                                                                    background: '#f0f9ff', color: '#0369a1', border: '1px solid #bae6fd',
                                                                                    fontWeight: 600
                                                                                }}>HTML</button>
                                                                        </td>
                                                                    </tr>
                                                                );
                                                            })}
                                                        </tbody>
                                                    </table>
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {/* 순위 이력 */}
                                    {viewMode === 'rank' && (
                                        <div className="card" style={{ padding: 20 }}>
                                            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>"{activeKeyword}" 순위 추적 이력</div>
                                            <div className="table-wrap">
                                                <table>
                                                    <thead><tr><th>날짜</th><th>순위</th><th>유형</th></tr></thead>
                                                    <tbody>
                                                        {rankHistory.map(function(r, i) {
                                                            var prevR = i > 0 ? rankHistory[i - 1] : null;
                                                            var diff = (prevR && r.rank_position && prevR.rank_position) ? prevR.rank_position - r.rank_position : null;
                                                            return (
                                                                <tr key={i}>
                                                                    <td>{(r.checked_at || '').slice(0, 16)}</td>
                                                                    <td style={{ fontWeight: 700 }}>
                                                                        {r.rank_position ? r.rank_position + '위' : '미노출'}
                                                                        {diff != null && diff !== 0 && (
                                                                            <span style={{ fontSize: 11, marginLeft: 6, color: diff > 0 ? '#16a34a' : '#dc2626' }}>
                                                                                {diff > 0 ? '▲' + diff : '▼' + Math.abs(diff)}
                                                                            </span>
                                                                        )}
                                                                    </td>
                                                                    <td>{r.check_type === 'manual' ? '수동' : '자동'}</td>
                                                                </tr>
                                                            );
                                                        })}
                                                    </tbody>
                                                </table>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

/* ==================== 분석 실행 폼 ==================== */
window.AnalysisForm = function AnalysisForm({ client, onAnalyze, analyzing, message }) {
    const [keyword, setKeyword] = React.useState('');
    const [productUrl, setProductUrl] = React.useState('');

    React.useEffect(function() {
        if (client && client.main_keywords) {
            var first = client.main_keywords.split(',')[0].trim();
            if (first) setKeyword(first);
        }
        if (client && client.naver_store_url) setProductUrl(client.naver_store_url);
    }, [client]);

    return (
        <div className="card" style={{ padding: 16, marginBottom: 16 }}>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>새 분석 실행</div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: 150 }}>
                    <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>키워드</label>
                    <input className="form-input" value={keyword} onChange={function(e) { setKeyword(e.target.value); }}
                        placeholder="분석할 키워드" style={{ width: '100%' }} />
                </div>
                <div style={{ flex: 1.5, minWidth: 200 }}>
                    <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>상품 URL (선택)</label>
                    <input className="form-input" value={productUrl} onChange={function(e) { setProductUrl(e.target.value); }}
                        placeholder="https://smartstore.naver.com/..." style={{ width: '100%' }} />
                </div>
                <button className="btn btn-primary" onClick={function() { onAnalyze(keyword, productUrl); }}
                    disabled={analyzing || !keyword} style={{ whiteSpace: 'nowrap' }}>
                    {analyzing ? '분석 중...' : '분석 실행'}
                </button>
            </div>
            {message && <div style={{ marginTop: 10, fontSize: 13, color: '#16a34a' }}>{message}</div>}
        </div>
    );
};

/* ==================== 분석 결과 뷰 ==================== */
window.AnalysisResultView = function AnalysisResultView({ keyword, data, rankHistory, onExport, hideHeader }) {
    function fmt(n) { return n != null ? Number(n).toLocaleString('ko-KR') : '-'; }

    return (
        <div>
            {/* 요약 카드 */}
            {data.summaryCards && (
                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                    {!hideHeader && (
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                            <div style={{ fontSize: 16, fontWeight: 700 }}>{keyword} 분석 결과</div>
                            {onExport && <button className="btn btn-primary" onClick={onExport} style={{ fontSize: 13, padding: '6px 14px' }}>HTML 보고서</button>}
                        </div>
                    )}
                    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                        <div style={{ flex: 1, minWidth: 120, background: '#f0f9ff', borderRadius: 10, padding: 16, textAlign: 'center' }}>
                            <div style={{ fontSize: 12, color: '#64748b' }}>월간 검색량</div>
                            <div style={{ fontSize: 24, fontWeight: 700, color: '#0f172a' }}>{fmt(data.summaryCards.totalVolume)}</div>
                        </div>
                        <div style={{ flex: 1, minWidth: 120, background: '#f0fdf4', borderRadius: 10, padding: 16, textAlign: 'center' }}>
                            <div style={{ fontSize: 12, color: '#64748b' }}>상품 수</div>
                            <div style={{ fontSize: 24, fontWeight: 700, color: '#0f172a' }}>{fmt(data.summaryCards.productCount)}</div>
                        </div>
                        <div style={{ flex: 1, minWidth: 120, background: '#faf5ff', borderRadius: 10, padding: 16, textAlign: 'center' }}>
                            <div style={{ fontSize: 12, color: '#64748b' }}>경쟁강도</div>
                            <div style={{ fontSize: 24, fontWeight: 700, color: data.competitionIndex ? data.competitionIndex.compColor : '#0f172a' }}>{data.summaryCards.compLevel}</div>
                        </div>
                    </div>
                </div>
            )}

            {/* 경쟁강도 상세 */}
            {data.competitionIndex && (
                <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>경쟁강도 분석</div>
                    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 14 }}>
                        <div><span style={{ color: '#64748b' }}>경쟁지수:</span> <strong style={{ color: data.competitionIndex.compColor }}>{data.competitionIndex.compIndex}</strong></div>
                        <div><span style={{ color: '#64748b' }}>상품 수:</span> <strong>{fmt(data.competitionIndex.productCount)}</strong></div>
                        <div><span style={{ color: '#64748b' }}>검색량:</span> <strong>{fmt(data.competitionIndex.searchVolume)}</strong></div>
                    </div>
                </div>
            )}

            {/* 시장 규모 */}
            {data.marketRevenue && (
                <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>시장 규모</div>
                    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 14 }}>
                        <div><span style={{ color: '#64748b' }}>평균 가격:</span> <strong>{fmt(data.marketRevenue.avgPrice)}원</strong></div>
                        <div><span style={{ color: '#64748b' }}>예상 월 시장:</span> <strong>{fmt(data.marketRevenue.estimatedMonthly)}원</strong></div>
                    </div>
                </div>
            )}

            {/* 광고 경쟁 정보 */}
            {data.advertiserInfo && (
                <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>광고 경쟁 정보</div>
                    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 14 }}>
                        <div><span style={{ color: '#64748b' }}>광고 경쟁강도:</span> <strong>{data.advertiserInfo.compIdx}</strong></div>
                        <div><span style={{ color: '#64748b' }}>노출 깊이:</span> <strong>{data.advertiserInfo.adDepth}</strong></div>
                        <div><span style={{ color: '#64748b' }}>PC 클릭:</span> <strong>{data.advertiserInfo.pcClicks}회</strong></div>
                        <div><span style={{ color: '#64748b' }}>모바일 클릭:</span> <strong>{data.advertiserInfo.mobileClicks}회</strong></div>
                    </div>
                </div>
            )}

            {/* 순위 추적 이력 (hideHeader가 아닌 경우만) */}
            {!hideHeader && rankHistory && rankHistory.length > 0 && (
                <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>순위 추적 이력 ({rankHistory.length}건)</div>
                    <div className="table-wrap">
                        <table>
                            <thead><tr><th>날짜</th><th>순위</th><th>유형</th></tr></thead>
                            <tbody>
                                {rankHistory.map(function(r, i) {
                                    return (
                                        <tr key={i}>
                                            <td>{(r.checked_at || '').slice(0, 16)}</td>
                                            <td style={{ fontWeight: 700 }}>{r.rank_position ? r.rank_position + '위' : '미노출'}</td>
                                            <td>{r.check_type === 'manual' ? '수동' : '자동'}</td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
};
