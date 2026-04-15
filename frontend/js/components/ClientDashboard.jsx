/* ClientDashboard — 업체별 분석 관리 대시보드 */
window.ClientDashboard = function ClientDashboard({ onBack }) {
    const { useState, useEffect, useCallback } = React;

    const [clients, setClients] = useState([]);
    const [selectedClient, setSelectedClient] = useState(null);
    const [analyses, setAnalyses] = useState([]);
    const [rankHistory, setRankHistory] = useState([]);
    const [loading, setLoading] = useState(false);
    const [analyzing, setAnalyzing] = useState(false);
    const [activeKeyword, setActiveKeyword] = useState(null);
    const [activeAnalysis, setActiveAnalysis] = useState(null);
    const [message, setMessage] = useState('');

    /* 업체 목록 로드 */
    var loadClients = useCallback(function() {
        setLoading(true);
        api.get('/cd/my-clients').then(function(res) {
            if (res.success) setClients(res.data);
            setLoading(false);
        }).catch(function() { setLoading(false); });
    }, []);

    useEffect(function() { loadClients(); }, [loadClients]);

    /* 업체 선택 → 저장된 분석 로드 */
    var selectClient = function(client) {
        setSelectedClient(client);
        setActiveKeyword(null);
        setActiveAnalysis(null);
        setRankHistory([]);
        loadAnalyses(client.id);
    };

    var loadAnalyses = function(clientId) {
        api.get('/cd/' + clientId + '/analysis').then(function(res) {
            if (res.success) setAnalyses(res.data);
        }).catch(function() {});
    };

    /* 키워드 분석 실행 + 저장 */
    var runAnalysis = function(keyword, productUrl) {
        if (!selectedClient || !keyword) return;
        setAnalyzing(true);
        setMessage('');

        /* 기존 API로 데이터 수집 (병렬) */
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

            /* 분석 데이터 계산 (App.jsx 동일 로직) */
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

            /* 서버에 저장 */
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
                setActiveKeyword(keyword);
                setActiveAnalysis({ analysis_data: analysis, volume_data: volRes && volRes.success ? volRes.data : {}, related_data: rd || {} });

                /* 순위도 체크하여 저장 */
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

    /* 저장된 분석 보기 */
    var viewSavedAnalysis = function(a) {
        setActiveKeyword(a.keyword);
        setActiveAnalysis(a);
        /* 순위 이력 로드 */
        api.get('/cd/' + selectedClient.id + '/rank-history?keyword=' + encodeURIComponent(a.keyword)).then(function(res) {
            if (res.success) setRankHistory(res.data);
        });
    };

    /* HTML 보고서 생성 */
    var exportReport = function() {
        if (!activeAnalysis || !activeAnalysis.analysis_data) return;
        var ad = activeAnalysis.analysis_data;
        var dateStr = new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
        var title = (selectedClient.name || '') + ' 분석 보고서';

        var body = '<div class="rpt-section"><h2>📊 ' + activeKeyword + ' 키워드 분석</h2>';
        if (ad.summaryCards) {
            body += '<div class="rpt-cards">';
            body += '<div class="rpt-card"><div class="rpt-card-label">월간 검색량</div><div class="rpt-card-value">' + fmt(ad.summaryCards.totalVolume) + '</div></div>';
            body += '<div class="rpt-card"><div class="rpt-card-label">상품 수</div><div class="rpt-card-value">' + fmt(ad.summaryCards.productCount) + '</div></div>';
            body += '<div class="rpt-card"><div class="rpt-card-label">경쟁강도</div><div class="rpt-card-value">' + (ad.summaryCards.compLevel || '-') + '</div></div>';
            body += '</div>';
        }
        if (ad.competitionIndex) {
            body += '<div class="rpt-item"><strong>경쟁강도 지수:</strong> ' + ad.competitionIndex.compIndex + ' (' + ad.competitionIndex.compLabel + ')</div>';
        }
        if (ad.marketRevenue) {
            body += '<div class="rpt-item"><strong>평균 상품 가격:</strong> ' + fmt(ad.marketRevenue.avgPrice) + '원</div>';
            body += '<div class="rpt-item"><strong>예상 월 시장 규모:</strong> ' + fmt(ad.marketRevenue.estimatedMonthly) + '원</div>';
        }
        if (ad.advertiserInfo) {
            body += '<div class="rpt-item"><strong>광고 경쟁강도:</strong> ' + (ad.advertiserInfo.compIdx || '-') + '</div>';
            body += '<div class="rpt-item"><strong>광고 노출 깊이:</strong> ' + ad.advertiserInfo.adDepth + '</div>';
        }
        body += '</div>';

        /* 순위 이력 테이블 */
        if (rankHistory.length > 0) {
            body += '<div class="rpt-section"><h2>📈 순위 추적 이력</h2><table class="rpt-table"><thead><tr><th>날짜</th><th>순위</th></tr></thead><tbody>';
            rankHistory.forEach(function(r) {
                body += '<tr><td>' + (r.checked_at || '').slice(0, 10) + '</td><td>' + (r.rank_position || '-') + '위</td></tr>';
            });
            body += '</tbody></table></div>';
        }

        var html = '<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            + '<title>' + title + '</title><style>'
            + 'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f8fafc;color:#1e293b;margin:0}'
            + '.rpt-header{background:linear-gradient(135deg,#6C5CE7,#a29bfe);color:#fff;padding:40px 20px;text-align:center}'
            + '.rpt-header h1{font-size:24px;margin:0 0 8px} .rpt-header p{font-size:14px;opacity:.85}'
            + '.rpt-body{max-width:900px;margin:0 auto;padding:30px 20px}'
            + '.rpt-section{background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}'
            + '.rpt-section h2{font-size:18px;margin:0 0 16px;color:#1e293b}'
            + '.rpt-cards{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap}'
            + '.rpt-card{flex:1;min-width:120px;background:#f0f9ff;border-radius:8px;padding:16px;text-align:center}'
            + '.rpt-card-label{font-size:12px;color:#64748b;margin-bottom:4px}'
            + '.rpt-card-value{font-size:22px;font-weight:700;color:#0f172a}'
            + '.rpt-item{padding:8px 0;border-bottom:1px solid #f1f5f9;font-size:14px}'
            + '.rpt-table{width:100%;border-collapse:collapse;font-size:14px}'
            + '.rpt-table th,.rpt-table td{padding:10px 12px;border-bottom:1px solid #e2e8f0;text-align:left}'
            + '.rpt-table th{background:#f8fafc;font-weight:600}'
            + '.rpt-footer{text-align:center;padding:30px;color:#94a3b8;font-size:12px}'
            + '</style></head><body>'
            + '<div class="rpt-header"><h1>' + title + '</h1><p>' + dateStr + ' | \uba54\ud0c0\uc544\uc774\uc564\uc528 \ub85c\uc9c1 \ubd84\uc11d</p></div>'
            + '<div class="rpt-body">' + body + '</div>'
            + '<div class="rpt-footer">\u00A9 2026 \uba54\ud0c0\uc544\uc774\uc564\uc528 — \ub85c\uc9c1 \ubd84\uc11d \uc2dc\uc2a4\ud15c</div>'
            + '</body></html>';

        var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = (selectedClient.name || '업체') + '_' + activeKeyword + '_보고서_' + new Date().toISOString().slice(0, 10) + '.html';
        a.click();
        URL.revokeObjectURL(a.href);
    };

    function fmt(n) { return n != null ? Number(n).toLocaleString('ko-KR') : '-'; }

    /* ==================== 렌더링 ==================== */
    return (
        <div style={{ minHeight: 'calc(100vh - 60px)', background: '#f0f2f5' }}>
            <div className="container" style={{ display: 'flex', gap: 20, paddingTop: 20, minHeight: 'calc(100vh - 80px)' }}>
                {/* 좌측: 업체 목록 */}
                <div style={{ width: 300, flexShrink: 0 }}>
                    <div className="card" style={{ padding: 16 }}>
                        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>📋 내 업체 목록</div>
                        {loading && <div style={{ color: '#64748b', fontSize: 13 }}>로딩 중...</div>}
                        {!loading && clients.length === 0 && (
                            <div style={{ color: '#94a3b8', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
                                등록된 업체가 없습니다.<br />메인 분석 페이지에서 업체를 먼저 등록해주세요.
                            </div>
                        )}
                        {clients.map(function(c) {
                            var isActive = selectedClient && selectedClient.id === c.id;
                            return (
                                <div key={c.id} onClick={function() { selectClient(c); }}
                                    style={{
                                        padding: '12px 14px', borderRadius: 8, cursor: 'pointer', marginBottom: 6,
                                        background: isActive ? '#6C5CE7' : '#f8fafc',
                                        color: isActive ? '#fff' : '#1e293b',
                                        border: '1px solid ' + (isActive ? '#6C5CE7' : '#e2e8f0'),
                                        transition: 'all 0.15s'
                                    }}>
                                    <div style={{ fontWeight: 600, fontSize: 14 }}>{c.name || c.business_name}</div>
                                    <div style={{ fontSize: 11, opacity: 0.7, marginTop: 2 }}>
                                        {c.analysis_count > 0 ? '분석 ' + c.analysis_count + '건' : '미분석'}
                                        {c.last_analyzed ? ' · ' + c.last_analyzed.slice(0, 10) : ''}
                                    </div>
                                    {c.main_keywords && (
                                        <div style={{ fontSize: 11, opacity: 0.6, marginTop: 4 }}>🔑 {c.main_keywords}</div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* 우측: 분석 내용 */}
                <div style={{ flex: 1 }}>
                    {!selectedClient && (
                        <div className="card" style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>
                            <div style={{ fontSize: 48, marginBottom: 12 }}>📊</div>
                            <div style={{ fontSize: 16 }}>좌측에서 업체를 선택하세요</div>
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
                                            {selectedClient.naver_store_url && <span>🏪 {selectedClient.naver_store_url}</span>}
                                            {selectedClient.contact_name && <span style={{ marginLeft: 12 }}>👤 {selectedClient.contact_name}</span>}
                                        </div>
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

                            {/* 저장된 분석 키워드 목록 */}
                            {analyses.length > 0 && (
                                <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>📁 저장된 분석 ({analyses.length}건)</div>
                                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                                        {analyses.map(function(a, i) {
                                            var isActive = activeKeyword === a.keyword;
                                            return (
                                                <button key={i} onClick={function() { viewSavedAnalysis(a); }}
                                                    style={{
                                                        padding: '8px 16px', borderRadius: 20, cursor: 'pointer', fontSize: 13,
                                                        background: isActive ? '#6C5CE7' : '#f1f5f9',
                                                        color: isActive ? '#fff' : '#475569',
                                                        border: isActive ? '1px solid #6C5CE7' : '1px solid #e2e8f0'
                                                    }}>
                                                    {a.keyword}
                                                    <span style={{ fontSize: 11, opacity: 0.7, marginLeft: 6 }}>{(a.updated_at || '').slice(0, 10)}</span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {/* 분석 결과 표시 */}
                            {activeAnalysis && activeAnalysis.analysis_data && (
                                <AnalysisResultView
                                    keyword={activeKeyword}
                                    data={activeAnalysis.analysis_data}
                                    rankHistory={rankHistory}
                                    onExport={exportReport}
                                />
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
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>🔍 새 분석 실행</div>
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
                    {analyzing ? '분석 중...' : '🔍 분석 실행'}
                </button>
            </div>
            {message && <div style={{ marginTop: 10, fontSize: 13, color: '#16a34a' }}>✅ {message}</div>}
        </div>
    );
};

/* ==================== 분석 결과 뷰 ==================== */
window.AnalysisResultView = function AnalysisResultView({ keyword, data, rankHistory, onExport }) {
    function fmt(n) { return n != null ? Number(n).toLocaleString('ko-KR') : '-'; }

    return (
        <div>
            {/* 요약 카드 */}
            {data.summaryCards && (
                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                        <div style={{ fontSize: 16, fontWeight: 700 }}>📊 {keyword} 분석 결과</div>
                        <button className="btn btn-primary" onClick={onExport} style={{ fontSize: 13, padding: '6px 14px' }}>📄 HTML 보고서</button>
                    </div>
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
                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>⚔️ 경쟁강도 분석</div>
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
                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>💰 시장 규모</div>
                    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 14 }}>
                        <div><span style={{ color: '#64748b' }}>평균 가격:</span> <strong>{fmt(data.marketRevenue.avgPrice)}원</strong></div>
                        <div><span style={{ color: '#64748b' }}>예상 월 시장:</span> <strong>{fmt(data.marketRevenue.estimatedMonthly)}원</strong></div>
                    </div>
                </div>
            )}

            {/* 광고 경쟁 정보 */}
            {data.advertiserInfo && (
                <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>📢 광고 경쟁 정보</div>
                    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 14 }}>
                        <div><span style={{ color: '#64748b' }}>광고 경쟁강도:</span> <strong>{data.advertiserInfo.compIdx}</strong></div>
                        <div><span style={{ color: '#64748b' }}>노출 깊이:</span> <strong>{data.advertiserInfo.adDepth}</strong></div>
                        <div><span style={{ color: '#64748b' }}>PC 클릭:</span> <strong>{data.advertiserInfo.pcClicks}회</strong></div>
                        <div><span style={{ color: '#64748b' }}>모바일 클릭:</span> <strong>{data.advertiserInfo.mobileClicks}회</strong></div>
                    </div>
                </div>
            )}

            {/* 순위 추적 이력 */}
            {rankHistory && rankHistory.length > 0 && (
                <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>📈 순위 추적 이력 ({rankHistory.length}건)</div>
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
