/* ClientDashboard — 업체별 분석 관리 대시보드 v4.0 (AI 인사이트 탭 추가) */
window.ClientDashboard = function ClientDashboard({ currentUser, onRunAnalysis, initialSearch, canEdit }) {
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
    const [viewMode, setViewMode] = useState('history');
    const [message, setMessage] = useState('');
    const [searchQuery, setSearchQuery] = useState('');
    const [showExportMenu, setShowExportMenu] = useState(false);
    const exportMenuRef = React.useRef(null);
    const [aiInsights, setAiInsights] = useState(null);
    const [aiLoading, setAiLoading] = useState(false);
    const [aiSelectedKeyword, setAiSelectedKeyword] = useState(null);

    // 드롭다운 외부 클릭 시 닫기
    useEffect(function() {
        if (!showExportMenu) return;
        var handleClick = function(e) {
            if (exportMenuRef.current && !exportMenuRef.current.contains(e.target)) {
                setShowExportMenu(false);
            }
        };
        document.addEventListener('mousedown', handleClick);
        return function() { document.removeEventListener('mousedown', handleClick); };
    }, [showExportMenu]);

    /* 업체 목록 로드 */
    var loadClients = useCallback(function() {
        setLoading(true);
        api.get('/cd/my-clients').then(function(res) {
            if (res.success) setClients(res.data || []);
            setLoading(false);
        }).catch(function() { setLoading(false); });
    }, []);

    useEffect(function() { loadClients(); }, [loadClients]);

    /* initialSearch prop으로 순위추적에서 이동 시 해당 업체 자동 선택 */
    useEffect(function() {
        if (!initialSearch || !clients.length) return;
        var searchUrl = (initialSearch.productUrl || '').toLowerCase();
        var searchStore = (initialSearch.storeName || '').toLowerCase();
        if (!searchUrl && !searchStore) return;

        var matched = null;
        for (var i = 0; i < clients.length; i++) {
            var c = clients[i];
            var clientUrl = (c.naver_store_url || '').toLowerCase();
            var clientName = (c.name || '').toLowerCase();
            // URL 매칭 (부분 포함)
            if (searchUrl && clientUrl && (searchUrl.indexOf(clientUrl) !== -1 || clientUrl.indexOf(searchUrl) !== -1)) {
                matched = c; break;
            }
            // 스토어명 매칭
            if (searchStore && clientName && (searchStore.indexOf(clientName) !== -1 || clientName.indexOf(searchStore) !== -1)) {
                matched = c; break;
            }
        }
        if (matched) {
            selectClient(matched);
        } else if (searchStore) {
            setSearchQuery(searchStore);
        }
    }, [initialSearch, clients]);

    /* 업체 삭제 */
    var deleteClient = function(client, e) {
        e.stopPropagation();
        if (canEdit === false) { toast.error('삭제 권한이 없습니다.'); return; }
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

    /* 업체 선택 → 저장된 분석 로드 (경량 summary 모드) */
    var selectClient = function(client) {
        setSelectedClient(client);
        setActiveKeyword(null);
        setActiveAnalysis(null);
        setRankHistory([]);
        setAnalysisHistory([]);
        setAiInsights(null);
        setAiSelectedKeyword(null);
        setViewMode('history');
        loadAnalyses(client.id);
        loadAiInsights(client.id);
    };

    var loadAnalyses = function(clientId) {
        api.get('/cd/' + clientId + '/analysis?summary=true').then(function(res) {
            if (res.success) setAnalyses(res.data || []);
        }).catch(function() {});
    };

    /* AI 인사이트 로드 */
    var loadAiInsights = function(clientId) {
        setAiLoading(true);
        setAiInsights(null);
        api.get('/cd/' + clientId + '/ai-insights').then(function(res) {
            if (res.success) {
                setAiInsights(res.data || res);
                // 키워드별 인사이트가 있으면 첫 번째 키워드 자동 선택
                var kwInsights = (res.data || res).keywordInsights;
                if (kwInsights) {
                    var firstKw = Object.keys(kwInsights)[0];
                    if (firstKw) setAiSelectedKeyword(firstKw);
                }
            }
            setAiLoading(false);
        }).catch(function() { setAiLoading(false); });
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

    /* 키워드별 분석 보기 (히스토리 + 순위 병렬 로드) */
    var viewKeywordAnalysis = function(keyword) {
        if (!selectedClient) return;
        setActiveKeyword(keyword);
        setViewMode('history');

        /* 병렬 로드: 히스토리 + 순위 이력을 동시에 요청 */
        var historyReq = api.get('/cd/' + selectedClient.id + '/history?keyword=' + encodeURIComponent(keyword)).catch(function() { return { success: false }; });
        var rankReq = api.get('/cd/' + selectedClient.id + '/rank-history?keyword=' + encodeURIComponent(keyword)).catch(function() { return { success: false }; });

        Promise.all([historyReq, rankReq]).then(function(results) {
            if (results[0] && results[0].success) setAnalysisHistory(results[0].data || []);
            if (results[1] && results[1].success) setRankHistory(results[1].data || []);
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

    /* ========== 순위 이력 이미지 내보내기 ========== */
    var exportRankImage = function(days) {
        setShowExportMenu(false);
        if (!selectedClient || !activeKeyword || rankHistory.length === 0) return;

        var allData = rankHistory.slice(); // 이미 ASC 정렬 (오래된 날짜부터)

        // 기간 필터 적용
        var data = allData;
        var periodLabel = '전체';
        if (days && days > 0) {
            var cutoff = new Date();
            cutoff.setDate(cutoff.getDate() - days);
            data = allData.filter(function(r) {
                return new Date(r.checked_at) >= cutoff;
            });
            periodLabel = '최근 ' + days + '일';
        }
        if (data.length === 0) {
            toast.warn('선택한 기간에 순위 데이터가 없습니다.');
            return;
        }
        var padding = 40;
        var headerH = 90;
        var tableRowH = 32;
        var tableHeaderH = 36;
        var tableH = tableHeaderH + data.length * tableRowH;
        var chartH = 220;
        var chartGap = 40;
        var totalW = 720;
        var totalH = headerH + tableH + chartGap + chartH + padding * 2 + 30;

        var canvas = document.createElement('canvas');
        var dpr = window.devicePixelRatio || 2;
        canvas.width = totalW * dpr;
        canvas.height = totalH * dpr;
        canvas.style.width = totalW + 'px';
        canvas.style.height = totalH + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        // 배경
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, totalW, totalH);

        // 헤더 영역 — 그라데이션 배경
        var grad = ctx.createLinearGradient(0, 0, totalW, 0);
        grad.addColorStop(0, '#1B2A4A');
        grad.addColorStop(1, '#2d4a7a');
        ctx.fillStyle = grad;
        roundRect(ctx, padding - 10, padding - 10, totalW - padding * 2 + 20, headerH, 12, true, false);

        // 업체명
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 20px "Noto Sans KR", sans-serif';
        ctx.fillText(selectedClient.name || '업체명', padding + 10, padding + 24);

        // 키워드 + URL
        ctx.font = '13px "Noto Sans KR", sans-serif';
        ctx.fillStyle = 'rgba(255,255,255,0.8)';
        var subText = '키워드: ' + activeKeyword;
        if (selectedClient.naver_store_url) {
            var dispUrl = selectedClient.naver_store_url;
            try { var uu = new URL(dispUrl); if (uu.hostname.indexOf('smartstore') !== -1) dispUrl = uu.origin + uu.pathname; } catch(e) {}
            if (dispUrl.length > 55) dispUrl = dispUrl.slice(0, 55) + '...';
            subText += '   |   URL: ' + dispUrl;
        }
        ctx.fillText(subText, padding + 10, padding + 48);

        // 생성일 + 기간
        ctx.font = '11px "Noto Sans KR", sans-serif';
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.fillText('생성일: ' + new Date().toLocaleDateString('ko-KR') + '   |   조회 기간: ' + periodLabel + ' (' + data.length + '건)', padding + 10, padding + 68);

        // 순위 이력 테이블
        var tableY = padding + headerH + 20;
        ctx.font = 'bold 15px "Noto Sans KR", sans-serif';
        ctx.fillStyle = '#1e293b';
        ctx.fillText('"' + activeKeyword + '" 순위 추적 이력 (' + data.length + '건)', padding, tableY);
        tableY += 16;

        var colX = [padding, padding + 250, padding + 430];
        var colW = [250, 180, totalW - padding * 2 - 430];

        // 테이블 헤더
        ctx.fillStyle = '#f1f5f9';
        ctx.fillRect(padding, tableY, totalW - padding * 2, tableHeaderH);
        ctx.fillStyle = '#475569';
        ctx.font = 'bold 12px "Noto Sans KR", sans-serif';
        ctx.fillText('날짜', colX[0] + 12, tableY + 22);
        ctx.fillText('순위', colX[1] + 12, tableY + 22);
        ctx.fillText('유형', colX[2] + 12, tableY + 22);
        tableY += tableHeaderH;

        // 테이블 행
        data.forEach(function(r, i) {
            var rowY = tableY + i * tableRowH;
            if (i % 2 === 0) {
                ctx.fillStyle = '#f8fafc';
                ctx.fillRect(padding, rowY, totalW - padding * 2, tableRowH);
            }
            // 하단 선
            ctx.strokeStyle = '#e2e8f0';
            ctx.lineWidth = 0.5;
            ctx.beginPath();
            ctx.moveTo(padding, rowY + tableRowH);
            ctx.lineTo(totalW - padding, rowY + tableRowH);
            ctx.stroke();

            ctx.font = '12px "Noto Sans KR", sans-serif';
            ctx.fillStyle = '#334155';
            ctx.fillText((r.checked_at || '').slice(0, 16), colX[0] + 12, rowY + 20);

            // 순위 + 변동
            var prevR = i > 0 ? data[i - 1] : null;
            var diff = (prevR && r.rank_position && prevR.rank_position) ? prevR.rank_position - r.rank_position : null;
            ctx.font = 'bold 13px "Noto Sans KR", sans-serif';
            var rankText = r.rank_position ? r.rank_position + '위' : '미노출';
            ctx.fillStyle = r.rank_position ? (r.rank_position <= 10 ? '#059669' : r.rank_position <= 40 ? '#d97706' : '#dc2626') : '#94a3b8';
            ctx.fillText(rankText, colX[1] + 12, rowY + 20);

            if (diff != null && diff !== 0) {
                var diffText = diff > 0 ? '▲' + diff : '▼' + Math.abs(diff);
                var tw = ctx.measureText(rankText).width;
                ctx.font = '11px "Noto Sans KR", sans-serif';
                ctx.fillStyle = diff > 0 ? '#16a34a' : '#dc2626';
                ctx.fillText(diffText, colX[1] + 12 + tw + 8, rowY + 20);
            }

            ctx.font = '12px "Noto Sans KR", sans-serif';
            ctx.fillStyle = '#64748b';
            ctx.fillText(r.check_type === 'manual' ? '수동' : '자동', colX[2] + 12, rowY + 20);
        });

        // ==================== 라인 차트 ====================
        var chartTop = tableY + data.length * tableRowH + chartGap;
        ctx.font = 'bold 15px "Noto Sans KR", sans-serif';
        ctx.fillStyle = '#1e293b';
        ctx.fillText('순위 변동 추이', padding, chartTop);
        chartTop += 20;

        var chartLeft = padding + 40;
        var chartRight = totalW - padding - 20;
        var chartBottom = chartTop + chartH - 30;
        var chartInnerTop = chartTop + 10;

        // 순위 데이터 (유효한 것만)
        var validData = data.filter(function(r) { return r.rank_position != null && r.rank_position > 0; });
        if (validData.length > 1) {
            var ranks = validData.map(function(r) { return r.rank_position; });
            var maxRank = Math.max.apply(null, ranks);
            var minRank = Math.min.apply(null, ranks);
            var rankRange = Math.max(maxRank - minRank, 4);
            var yPad = Math.ceil(rankRange * 0.2);
            var yMin = Math.max(1, minRank - yPad);
            var yMax = maxRank + yPad;

            // Y축 (순위: 위가 1위)
            ctx.strokeStyle = '#e2e8f0';
            ctx.lineWidth = 0.5;
            ctx.font = '10px "Noto Sans KR", sans-serif';
            ctx.fillStyle = '#94a3b8';
            var ySteps = 5;
            for (var yi = 0; yi <= ySteps; yi++) {
                var yVal = Math.round(yMin + (yMax - yMin) * yi / ySteps);
                var yPos = chartInnerTop + (chartBottom - chartInnerTop) * (yi / ySteps);
                ctx.beginPath();
                ctx.moveTo(chartLeft, yPos);
                ctx.lineTo(chartRight, yPos);
                ctx.stroke();
                ctx.textAlign = 'right';
                ctx.fillText(yVal + '위', chartLeft - 6, yPos + 4);
            }
            ctx.textAlign = 'left';

            // X축 라벨
            validData.forEach(function(r, i) {
                var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
                ctx.save();
                ctx.font = '9px "Noto Sans KR", sans-serif';
                ctx.fillStyle = '#94a3b8';
                ctx.translate(xPos, chartBottom + 12);
                ctx.rotate(-0.4);
                ctx.fillText((r.checked_at || '').slice(5, 10), 0, 0);
                ctx.restore();
            });

            // 라인 그리기
            ctx.beginPath();
            ctx.strokeStyle = '#3b82f6';
            ctx.lineWidth = 2.5;
            ctx.lineJoin = 'round';
            validData.forEach(function(r, i) {
                var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
                var yPos = chartInnerTop + (chartBottom - chartInnerTop) * ((r.rank_position - yMin) / (yMax - yMin));
                if (i === 0) ctx.moveTo(xPos, yPos);
                else ctx.lineTo(xPos, yPos);
            });
            ctx.stroke();

            // 그라데이션 영역
            ctx.beginPath();
            validData.forEach(function(r, i) {
                var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
                var yPos = chartInnerTop + (chartBottom - chartInnerTop) * ((r.rank_position - yMin) / (yMax - yMin));
                if (i === 0) ctx.moveTo(xPos, yPos);
                else ctx.lineTo(xPos, yPos);
            });
            var lastX = chartLeft + (chartRight - chartLeft);
            ctx.lineTo(lastX, chartBottom);
            ctx.lineTo(chartLeft, chartBottom);
            ctx.closePath();
            var areaGrad = ctx.createLinearGradient(0, chartInnerTop, 0, chartBottom);
            areaGrad.addColorStop(0, 'rgba(59, 130, 246, 0.15)');
            areaGrad.addColorStop(1, 'rgba(59, 130, 246, 0.02)');
            ctx.fillStyle = areaGrad;
            ctx.fill();

            // 데이터 포인트
            validData.forEach(function(r, i) {
                var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
                var yPos = chartInnerTop + (chartBottom - chartInnerTop) * ((r.rank_position - yMin) / (yMax - yMin));
                ctx.beginPath();
                ctx.arc(xPos, yPos, 4, 0, Math.PI * 2);
                ctx.fillStyle = '#ffffff';
                ctx.fill();
                ctx.strokeStyle = '#3b82f6';
                ctx.lineWidth = 2;
                ctx.stroke();

                // 순위 라벨
                ctx.font = 'bold 10px "Noto Sans KR", sans-serif';
                ctx.fillStyle = '#1e40af';
                ctx.textAlign = 'center';
                ctx.fillText(r.rank_position + '위', xPos, yPos - 10);
            });
            ctx.textAlign = 'left';
        } else {
            ctx.font = '13px "Noto Sans KR", sans-serif';
            ctx.fillStyle = '#94a3b8';
            ctx.fillText('차트를 표시하려면 유효한 순위 데이터가 2건 이상 필요합니다.', chartLeft, chartTop + 60);
        }

        // 워터마크
        ctx.font = '10px "Noto Sans KR", sans-serif';
        ctx.fillStyle = '#cbd5e1';
        ctx.textAlign = 'right';
        ctx.fillText('METAINC 로직분석', totalW - padding, totalH - 12);
        ctx.textAlign = 'left';

        // 다운로드
        canvas.toBlob(function(blob) {
            var a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = (selectedClient.name || '업체') + '_' + activeKeyword + '_순위이력_' + new Date().toISOString().slice(0, 10) + '.png';
            a.click();
            URL.revokeObjectURL(a.href);
        }, 'image/png');
    };

    // Canvas 둥근 사각형 헬퍼
    function roundRect(ctx, x, y, w, h, r, fill, stroke) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
        if (fill) ctx.fill();
        if (stroke) ctx.stroke();
    }

    var uniqueKeywords = getUniqueKeywords();

    /* ==================== 렌더링 ==================== */
    return (
        <div style={{ minHeight: 'calc(100vh - 60px)', background: '#f0f2f5' }}>
            <div className="container cd-layout" style={{ display: 'flex', gap: 20, paddingTop: 20, minHeight: 'calc(100vh - 80px)' }}>
                {/* 좌측: 업체 목록 */}
                <div className="cd-sidebar" style={{ width: 280, flexShrink: 0 }}>
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
                                        {canEdit !== false && <button onClick={function(e) { deleteClient(c, e); }}
                                            title="업체 삭제"
                                            style={{
                                                background: 'none', border: 'none', cursor: 'pointer', padding: '2px 6px',
                                                fontSize: 14, color: isActive ? 'rgba(255,255,255,0.5)' : '#cbd5e1',
                                                flexShrink: 0, lineHeight: 1,
                                            }}
                                            onMouseOver={function(e) { e.target.style.color = '#ef4444'; }}
                                            onMouseOut={function(e) { e.target.style.color = isActive ? 'rgba(255,255,255,0.5)' : '#cbd5e1'; }}
                                        >{'\u2715'}</button>}
                                    </div>
                                </div>
                            );
                        })}
                        </div>
                    </div>
                </div>

                {/* 우측: 분석 내용 */}
                <div className="cd-main" style={{ flex: 1, minWidth: 0 }}>
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
                                            {selectedClient.naver_store_url && <span style={{ marginLeft: 12 }}>URL: {(function() { try { var u = new URL(selectedClient.naver_store_url); if (u.hostname.indexOf('smartstore.naver.com') !== -1) return u.origin + u.pathname; } catch(e) {} return selectedClient.naver_store_url.length > 60 ? selectedClient.naver_store_url.slice(0, 60) + '...' : selectedClient.naver_store_url; })()}</span>}
                                        </div>
                                    </div>
                                    <div style={{ fontSize: 12, color: '#94a3b8' }}>
                                        {selectedClient.last_analyzed && '마지막 분석: ' + selectedClient.last_analyzed.slice(0, 10)}
                                    </div>
                                </div>
                            </div>

                            {/* 새 분석 실행 폼 (viewer는 숨김) */}
                            {canEdit !== false && <AnalysisForm
                                client={selectedClient}
                                onAnalyze={onRunAnalysis ? function(keyword, productUrl) {
                                    /* 분석 탭으로 전환하여 실제 분석 실행 + 자동 저장 */
                                    var params = {
                                        keyword: keyword,
                                        productUrl: productUrl || '',
                                        companyName: selectedClient.name || '',
                                        clientId: selectedClient.id
                                    };
                                    onRunAnalysis(params);
                                } : runAnalysis}
                                analyzing={analyzing}
                                message={message}
                            />}

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

                            {/* 보기 모드 전환 탭 */}
                            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                                <button onClick={function() { setViewMode('history'); }}
                                    style={{
                                        padding: '8px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                        background: viewMode === 'history' ? '#1B2A4A' : '#fff',
                                        color: viewMode === 'history' ? '#fff' : '#475569',
                                        border: viewMode === 'history' ? 'none' : '1px solid #e2e8f0',
                                    }}>{'📊'} 일자별 추이 {activeKeyword ? '(' + analysisHistory.length + '일)' : ''}</button>
                                <button onClick={function() { setViewMode('rank'); }}
                                    style={{
                                        padding: '8px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                        background: viewMode === 'rank' ? '#1B2A4A' : '#fff',
                                        color: viewMode === 'rank' ? '#fff' : '#475569',
                                        border: viewMode === 'rank' ? 'none' : '1px solid #e2e8f0',
                                    }}>{'📈'} 순위 이력 {activeKeyword ? '(' + rankHistory.length + '건)' : ''}</button>
                                <button onClick={function() { setViewMode('insights'); }}
                                    style={{
                                        padding: '8px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                        background: viewMode === 'insights' ? '#7C3AED' : '#fff',
                                        color: viewMode === 'insights' ? '#fff' : '#7C3AED',
                                        border: viewMode === 'insights' ? 'none' : '1px solid #DDD6FE',
                                    }}>{'🤖'} AI 인사이트</button>
                                <div style={{ flex: 1 }} />
                            </div>

                            {/* 키워드 선택 시 상세 보기 (일자별/순위) */}
                            {activeKeyword && (viewMode === 'history' || viewMode === 'rank') && (
                                <div>

                                    {/* 일자별 추이 테이블 */}
                                    {viewMode === 'history' && (
                                        <div className="card" style={{ padding: 20 }}>
                                            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>"{activeKeyword}" 일자별 분석 추이</div>
                                            {analysisHistory.length === 0 ? (
                                                <div style={{ textAlign: 'center', padding: 30, color: '#94a3b8', fontSize: 13 }}>
                                                    아직 누적된 분석 데이터가 없습니다. 매일 분석을 실행하면 여기에 추이가 표시됩니다.
                                                </div>
                                            ) : (
                                                <div className="table-wrap" style={{ overflowX: 'auto' }}>
                                                    <table style={{ minWidth: 750, fontSize: 13, whiteSpace: 'nowrap' }}>
                                                        <thead>
                                                            <tr>
                                                                <th style={{ whiteSpace: 'nowrap' }}>날짜</th>
                                                                <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>검색량</th>
                                                                <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>PC 클릭</th>
                                                                <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>모바일 클릭</th>
                                                                <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>경쟁지수</th>
                                                                <th style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>경쟁수준</th>
                                                                <th style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>광고 경쟁강도</th>
                                                                <th style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>보고서</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                                            {analysisHistory.map(function(h, i) {
                                                                var prevH = i > 0 ? analysisHistory[i - 1] : null;
                                                                var compIdxDiff = (prevH && h.comp_index != null && prevH.comp_index != null) ? (h.comp_index - prevH.comp_index).toFixed(2) : null;
                                                                /* 경쟁수준 퍼센트 색상 */
                                                                var cpVal = h.comp_percent;
                                                                var cpColor = cpVal != null ? (cpVal <= 30 ? '#16a34a' : cpVal <= 70 ? '#ca8a04' : '#dc2626') : '#64748b';
                                                                var cpBg = cpVal != null ? (cpVal <= 30 ? '#dcfce7' : cpVal <= 70 ? '#fef9c3' : '#fee2e2') : '#f1f5f9';
                                                                var cpLabel = cpVal != null ? (cpVal <= 30 ? '블루오션' : cpVal <= 70 ? '보통' : '레드오션') : '-';
                                                                /* 광고 경쟁강도 배지 색상 */
                                                                var adIdx = h.ad_comp_idx || '-';
                                                                var adColor = adIdx === '높음' || adIdx === 'HIGH' ? '#dc2626' : adIdx === '중간' || adIdx === 'MEDIUM' ? '#ca8a04' : adIdx === '낮음' || adIdx === 'LOW' ? '#16a34a' : '#64748b';
                                                                var adBg = adIdx === '높음' || adIdx === 'HIGH' ? '#fee2e2' : adIdx === '중간' || adIdx === 'MEDIUM' ? '#fef9c3' : adIdx === '낮음' || adIdx === 'LOW' ? '#dcfce7' : '#f1f5f9';
                                                                return (
                                                                    <tr key={i}>
                                                                        <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{h.date}</td>
                                                                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{h.search_volume || '-'}</td>
                                                                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{h.pc_clicks || '-'}</td>
                                                                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{h.mobile_clicks || '-'}</td>
                                                                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                                                                            {h.comp_index != null ? h.comp_index : '-'}
                                                                            {compIdxDiff && compIdxDiff != '0.00' && (
                                                                                <span style={{ fontSize: 11, marginLeft: 4, color: compIdxDiff > 0 ? '#dc2626' : '#16a34a' }}>
                                                                                    {compIdxDiff > 0 ? '+' : ''}{compIdxDiff}
                                                                                </span>
                                                                            )}
                                                                        </td>
                                                                        <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                                                                            {cpVal != null ? (
                                                                                <span style={{ padding: '2px 6px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: cpBg, color: cpColor }}>
                                                                                    {cpLabel} {cpVal}%
                                                                                </span>
                                                                            ) : '-'}
                                                                        </td>
                                                                        <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                                                                            <span style={{ padding: '2px 6px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: adBg, color: adColor }}>
                                                                                {adIdx}
                                                                            </span>
                                                                        </td>
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
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                                                <div style={{ fontSize: 16, fontWeight: 700 }}>"{activeKeyword}" 순위 추적 이력</div>
                                                <div ref={exportMenuRef} style={{ position: 'relative' }}>
                                                    <button onClick={function() { setShowExportMenu(!showExportMenu); }}
                                                        style={{
                                                            padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                                                            background: '#f0f9ff', color: '#0369a1', border: '1px solid #bae6fd',
                                                            display: 'flex', alignItems: 'center', gap: 6
                                                        }}>
                                                        {'📸'} 이미지 저장 {'▾'}
                                                    </button>
                                                    {showExportMenu && (
                                                        <div style={{
                                                            position: 'absolute', top: '100%', right: 0, marginTop: 4, zIndex: 100,
                                                            background: '#fff', borderRadius: 10, boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
                                                            border: '1px solid #e2e8f0', minWidth: 160, overflow: 'hidden'
                                                        }}>
                                                            {[
                                                                { label: '최근 7일', days: 7 },
                                                                { label: '최근 30일', days: 30 },
                                                                { label: '최근 60일', days: 60 },
                                                                { label: '전체 기간', days: 0 },
                                                            ].map(function(opt) {
                                                                return React.createElement('button', {
                                                                    key: opt.days,
                                                                    onClick: function() { exportRankImage(opt.days); },
                                                                    style: {
                                                                        display: 'block', width: '100%', padding: '10px 16px',
                                                                        background: 'none', border: 'none', borderBottom: '1px solid #f1f5f9',
                                                                        textAlign: 'left', fontSize: 13, cursor: 'pointer', color: '#334155',
                                                                        fontWeight: 500
                                                                    },
                                                                    onMouseOver: function(e) { e.target.style.background = '#f0f9ff'; },
                                                                    onMouseOut: function(e) { e.target.style.background = 'none'; }
                                                                }, opt.label);
                                                            })}
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                            {rankHistory.length === 0 ? (
                                                <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8', fontSize: 13 }}>
                                                    <div style={{ fontSize: 32, marginBottom: 12 }}>📊</div>
                                                    <div style={{ fontWeight: 600, marginBottom: 6, color: '#64748b' }}>아직 수집된 순위 데이터가 없습니다</div>
                                                    <div>스케줄러가 6시간 간격으로 자동 수집하며, 매일 오전 7시 전체 분석 시에도 함께 수집됩니다.</div>
                                                </div>
                                            ) : (
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
                                            )}
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* ===== 키워드 미선택 + history/rank 모드 안내 ===== */}
                            {!activeKeyword && (viewMode === 'history' || viewMode === 'rank') && (
                                <div className="card" style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>
                                    <div style={{ fontSize: 32, marginBottom: 12 }}>{'👆'}</div>
                                    <div style={{ fontSize: 14, fontWeight: 500 }}>위에서 키워드를 선택하면 {viewMode === 'history' ? '일자별 추이' : '순위 이력'}가 표시됩니다.</div>
                                </div>
                            )}

                            {/* ===== AI 인사이트 탭 ===== */}
                            {viewMode === 'insights' && (
                                <div>
                                    {aiLoading && (
                                        <div className="card" style={{ padding: 40, textAlign: 'center' }}>
                                            <div style={{ fontSize: 32, marginBottom: 12 }}>{'🤖'}</div>
                                            <div style={{ fontSize: 14, color: '#64748b' }}>AI 인사이트를 분석 중입니다...</div>
                                        </div>
                                    )}

                                    {!aiLoading && !aiInsights && (
                                        <div className="card" style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>
                                            <div style={{ fontSize: 32, marginBottom: 12 }}>{'📊'}</div>
                                            <div style={{ fontSize: 14, fontWeight: 500 }}>아직 분석 데이터가 없어 AI 인사이트를 생성할 수 없습니다.</div>
                                            <div style={{ fontSize: 13, marginTop: 8 }}>분석을 실행하면 AI가 자동으로 학습하여 인사이트를 제공합니다.</div>
                                        </div>
                                    )}

                                    {!aiLoading && aiInsights && (
                                        <div>
                                            {/* ⑥ 업체 성과 패턴 */}
                                            {aiInsights.performance && (
                                                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                                                    <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                                                        {'📊'} 업체 성과 패턴
                                                        <span style={{
                                                            fontSize: 11, padding: '2px 8px', borderRadius: 10, fontWeight: 600,
                                                            background: aiInsights.performance.overallTrend === '상승세' ? '#dcfce7' : aiInsights.performance.overallTrend === '하락세' ? '#fee2e2' : '#f1f5f9',
                                                            color: aiInsights.performance.overallTrend === '상승세' ? '#16a34a' : aiInsights.performance.overallTrend === '하락세' ? '#dc2626' : '#64748b'
                                                        }}>{aiInsights.performance.overallTrend}</span>
                                                    </div>
                                                    {/* 성과 요약 카드 */}
                                                    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
                                                        <div style={{ flex: 1, minWidth: 100, background: '#f0fdf4', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                                                            <div style={{ fontSize: 11, color: '#64748b' }}>상승 키워드</div>
                                                            <div style={{ fontSize: 22, fontWeight: 700, color: '#16a34a' }}>{aiInsights.performance.improving}</div>
                                                        </div>
                                                        <div style={{ flex: 1, minWidth: 100, background: '#fee2e2', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                                                            <div style={{ fontSize: 11, color: '#64748b' }}>하락 키워드</div>
                                                            <div style={{ fontSize: 22, fontWeight: 700, color: '#dc2626' }}>{aiInsights.performance.declining}</div>
                                                        </div>
                                                        <div style={{ flex: 1, minWidth: 100, background: '#f1f5f9', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                                                            <div style={{ fontSize: 11, color: '#64748b' }}>유지 키워드</div>
                                                            <div style={{ fontSize: 22, fontWeight: 700, color: '#64748b' }}>{aiInsights.performance.stable}</div>
                                                        </div>
                                                        <div style={{ flex: 1, minWidth: 100, background: '#dbeafe', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                                                            <div style={{ fontSize: 11, color: '#64748b' }}>총 키워드</div>
                                                            <div style={{ fontSize: 22, fontWeight: 700, color: '#1e40af' }}>{aiInsights.performance.totalKeywords}</div>
                                                        </div>
                                                    </div>
                                                    {/* 키워드별 성과 리스트 */}
                                                    {aiInsights.performance.keywordSummaries && aiInsights.performance.keywordSummaries.length > 0 && (
                                                        <div className="table-wrap" style={{ overflowX: 'auto' }}>
                                                            <table style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
                                                                <thead>
                                                                    <tr>
                                                                        <th>키워드</th>
                                                                        <th style={{ textAlign: 'center' }}>추세</th>
                                                                        <th style={{ textAlign: 'right' }}>초기 순위</th>
                                                                        <th style={{ textAlign: 'right' }}>현재 순위</th>
                                                                        <th style={{ textAlign: 'right' }}>변동</th>
                                                                        <th style={{ textAlign: 'right' }}>평균 순위</th>
                                                                        <th style={{ textAlign: 'right' }}>데이터</th>
                                                                    </tr>
                                                                </thead>
                                                                <tbody>
                                                                    {aiInsights.performance.keywordSummaries.map(function(s, i) {
                                                                        var trendColor = s.trend === '상승' ? '#16a34a' : s.trend === '하락' ? '#dc2626' : '#64748b';
                                                                        var trendBg = s.trend === '상승' ? '#dcfce7' : s.trend === '하락' ? '#fee2e2' : '#f1f5f9';
                                                                        return (
                                                                            <tr key={i}>
                                                                                <td style={{ fontWeight: 600 }}>{s.keyword}</td>
                                                                                <td style={{ textAlign: 'center' }}>
                                                                                    <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: trendBg, color: trendColor }}>{s.trend}</span>
                                                                                </td>
                                                                                <td style={{ textAlign: 'right' }}>{s.firstRank}위</td>
                                                                                <td style={{ textAlign: 'right', fontWeight: 700 }}>{s.latestRank}위</td>
                                                                                <td style={{ textAlign: 'right', color: s.change > 0 ? '#16a34a' : s.change < 0 ? '#dc2626' : '#64748b', fontWeight: 600 }}>
                                                                                    {s.change > 0 ? '▲' + s.change : s.change < 0 ? '▼' + Math.abs(s.change) : '-'}
                                                                                </td>
                                                                                <td style={{ textAlign: 'right' }}>{s.avgRank}위</td>
                                                                                <td style={{ textAlign: 'right', color: '#94a3b8' }}>{s.dataPoints}건</td>
                                                                            </tr>
                                                                        );
                                                                    })}
                                                                </tbody>
                                                            </table>
                                                        </div>
                                                    )}
                                                    {/* 성과 조언 */}
                                                    {aiInsights.performance.advice && (
                                                        <div style={{ marginTop: 14, padding: 12, background: '#faf5ff', borderRadius: 8, fontSize: 13, color: '#6b21a8', lineHeight: 1.6 }}>
                                                            {'💡'} {aiInsights.performance.advice}
                                                        </div>
                                                    )}
                                                </div>
                                            )}

                                            {/* ⑦ 경쟁사 이상 감지 */}
                                            {aiInsights.competitorAlerts && aiInsights.competitorAlerts.totalAlerts > 0 && (
                                                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                                                    <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                                                        {'🚨'} 경쟁사 이상 감지
                                                        {aiInsights.competitorAlerts.dangerCount > 0 && (
                                                            <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: '#fee2e2', color: '#dc2626', fontWeight: 600 }}>
                                                                위험 {aiInsights.competitorAlerts.dangerCount}건
                                                            </span>
                                                        )}
                                                        {aiInsights.competitorAlerts.warningCount > 0 && (
                                                            <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: '#fef9c3', color: '#ca8a04', fontWeight: 600 }}>
                                                                주의 {aiInsights.competitorAlerts.warningCount}건
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                        {aiInsights.competitorAlerts.alerts.map(function(alert, i) {
                                                            var severityStyles = {
                                                                danger: { bg: '#fef2f2', border: '#fecaca', color: '#991b1b', icon: '🔴' },
                                                                warning: { bg: '#fffbeb', border: '#fde68a', color: '#92400e', icon: '🟡' },
                                                                success: { bg: '#f0fdf4', border: '#bbf7d0', color: '#166534', icon: '🟢' },
                                                                info: { bg: '#eff6ff', border: '#bfdbfe', color: '#1e40af', icon: '🔵' },
                                                            };
                                                            var st = severityStyles[alert.severity] || severityStyles.info;
                                                            return (
                                                                <div key={i} style={{ padding: '10px 14px', background: st.bg, border: '1px solid ' + st.border, borderRadius: 8, fontSize: 13 }}>
                                                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                                        <div style={{ color: st.color, fontWeight: 600 }}>
                                                                            {st.icon} {alert.message}
                                                                        </div>
                                                                        <span style={{ fontSize: 11, color: '#94a3b8' }}>{(alert.date || '').slice(0, 10)}</span>
                                                                    </div>
                                                                    {alert.detail && (
                                                                        <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>{alert.detail}</div>
                                                                    )}
                                                                </div>
                                                            );
                                                        })}
                                                    </div>
                                                </div>
                                            )}

                                            {/* ② 키워드 발굴 추천 */}
                                            {aiInsights.keywordRecommendations && aiInsights.keywordRecommendations.topRecommended && aiInsights.keywordRecommendations.topRecommended.length > 0 && (
                                                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                                                    <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                                                        {'🔍'} 키워드 발굴 추천
                                                        <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>
                                                            기존 {aiInsights.keywordRecommendations.existingCount}개 키워드에서 {aiInsights.keywordRecommendations.candidateCount}개 후보 발굴
                                                        </span>
                                                    </div>
                                                    <div className="table-wrap" style={{ overflowX: 'auto' }}>
                                                        <table style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
                                                            <thead>
                                                                <tr>
                                                                    <th>추천 키워드</th>
                                                                    <th style={{ textAlign: 'right' }}>월간 검색량</th>
                                                                    <th style={{ textAlign: 'right' }}>연관 등장</th>
                                                                    <th style={{ textAlign: 'right' }}>추천 점수</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody>
                                                                {aiInsights.keywordRecommendations.topRecommended.map(function(kw, i) {
                                                                    return (
                                                                        <tr key={i}>
                                                                            <td style={{ fontWeight: 600 }}>{kw.keyword}</td>
                                                                            <td style={{ textAlign: 'right' }}>{fmt(kw.volume)}</td>
                                                                            <td style={{ textAlign: 'right' }}>{kw.appearances}회</td>
                                                                            <td style={{ textAlign: 'right' }}>
                                                                                <span style={{
                                                                                    padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                                                                                    background: kw.score >= 5 ? '#dcfce7' : kw.score >= 2 ? '#fef9c3' : '#f1f5f9',
                                                                                    color: kw.score >= 5 ? '#16a34a' : kw.score >= 2 ? '#ca8a04' : '#64748b'
                                                                                }}>{kw.score}</span>
                                                                            </td>
                                                                        </tr>
                                                                    );
                                                                })}
                                                            </tbody>
                                                        </table>
                                                    </div>
                                                </div>
                                            )}

                                            {/* ===== 키워드별 인사이트 (①③④⑤⑧) ===== */}
                                            {aiInsights.keywordInsights && Object.keys(aiInsights.keywordInsights).length > 0 && (
                                                <div>
                                                    {/* 키워드 선택 pill */}
                                                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
                                                        {Object.keys(aiInsights.keywordInsights).map(function(kw) {
                                                            var isActive = aiSelectedKeyword === kw;
                                                            return (
                                                                <button key={kw} onClick={function() { setAiSelectedKeyword(kw); }}
                                                                    style={{
                                                                        padding: '6px 14px', borderRadius: 20, cursor: 'pointer', fontSize: 12,
                                                                        background: isActive ? '#7C3AED' : '#f5f3ff',
                                                                        color: isActive ? '#fff' : '#7C3AED',
                                                                        border: isActive ? '1px solid #7C3AED' : '1px solid #DDD6FE'
                                                                    }}>{'🔑'} {kw}</button>
                                                            );
                                                        })}
                                                    </div>

                                                    {/* 선택된 키워드 인사이트 */}
                                                    {aiSelectedKeyword && aiInsights.keywordInsights[aiSelectedKeyword] && (function() {
                                                        var kwData = aiInsights.keywordInsights[aiSelectedKeyword];
                                                        return React.createElement('div', null,
                                                            /* ⑧ 순위 예측 */
                                                            kwData.rankPrediction && React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 16 } },
                                                                React.createElement('div', { style: { fontSize: 16, fontWeight: 700, marginBottom: 16 } }, '🔮 순위 예측 — "' + aiSelectedKeyword + '"'),
                                                                kwData.rankPrediction.ready === false ?
                                                                    React.createElement('div', { style: { textAlign: 'center', padding: 20, color: '#94a3b8', fontSize: 13 } }, kwData.rankPrediction.message) :
                                                                    React.createElement('div', null,
                                                                        React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 } },
                                                                            React.createElement('div', { style: { flex: 1, minWidth: 110, background: '#f1f5f9', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                                React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '현재 순위'),
                                                                                React.createElement('div', { style: { fontSize: 22, fontWeight: 700 } }, kwData.rankPrediction.currentRank + '위')
                                                                            ),
                                                                            React.createElement('div', { style: { flex: 1, minWidth: 110, background: '#dbeafe', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                                React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '7일 후 예측'),
                                                                                React.createElement('div', { style: { fontSize: 22, fontWeight: 700, color: '#1e40af' } }, kwData.rankPrediction.predicted7d + '위')
                                                                            ),
                                                                            React.createElement('div', { style: { flex: 1, minWidth: 110, background: '#ede9fe', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                                React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '14일 후 예측'),
                                                                                React.createElement('div', { style: { fontSize: 22, fontWeight: 700, color: '#6d28d9' } }, kwData.rankPrediction.predicted14d + '위')
                                                                            ),
                                                                            React.createElement('div', { style: { flex: 1, minWidth: 110, background: '#faf5ff', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                                React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '30일 후 예측'),
                                                                                React.createElement('div', { style: { fontSize: 22, fontWeight: 700, color: '#9333ea' } }, kwData.rankPrediction.predicted30d + '위')
                                                                            )
                                                                        ),
                                                                        React.createElement('div', { style: { display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 13, color: '#475569' } },
                                                                            React.createElement('span', null, '추세: ', React.createElement('strong', { style: { color: kwData.rankPrediction.trend === '상승' ? '#16a34a' : kwData.rankPrediction.trend === '하락' ? '#dc2626' : '#64748b' } }, kwData.rankPrediction.trend)),
                                                                            React.createElement('span', null, '신뢰도: ', React.createElement('strong', null, kwData.rankPrediction.confidence, ' (R²=', kwData.rankPrediction.rSquared, ')')),
                                                                            React.createElement('span', null, '데이터: ', React.createElement('strong', null, kwData.rankPrediction.dataPoints, '건'))
                                                                        ),
                                                                        React.createElement('div', { style: { marginTop: 10, padding: 10, background: '#f8fafc', borderRadius: 8, fontSize: 12, color: '#64748b' } }, kwData.rankPrediction.trendDesc)
                                                                    )
                                                            ),

                                                            /* ① 가격 최적화 */
                                                            kwData.priceOptimization && React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 16 } },
                                                                React.createElement('div', { style: { fontSize: 16, fontWeight: 700, marginBottom: 16 } }, '💰 가격 최적화 — "' + aiSelectedKeyword + '"'),
                                                                React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 } },
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 130, background: '#f0fdf4', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '추천 가격대'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700, color: '#16a34a' } }, fmt(kwData.priceOptimization.recommendedRange.low) + ' ~ ' + fmt(kwData.priceOptimization.recommendedRange.high) + '원')
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#eff6ff', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '상위5 평균'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, fmt(kwData.priceOptimization.avgTop5) + '원')
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f1f5f9', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '중위 가격'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, fmt(kwData.priceOptimization.median) + '원')
                                                                    )
                                                                ),
                                                                React.createElement('div', { style: { padding: 12, background: '#faf5ff', borderRadius: 8, fontSize: 13, color: '#6b21a8' } },
                                                                    '💡 전략: ', React.createElement('strong', null, kwData.priceOptimization.strategy), ' — ', kwData.priceOptimization.strategyDesc
                                                                )
                                                            ),

                                                            /* ④ 광고 효율 */
                                                            kwData.adEfficiency && React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 16 } },
                                                                React.createElement('div', { style: { fontSize: 16, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 } },
                                                                    '📣 광고 효율 — "' + aiSelectedKeyword + '"',
                                                                    React.createElement('span', { style: {
                                                                        fontSize: 14, padding: '2px 10px', borderRadius: 10, fontWeight: 700,
                                                                        background: kwData.adEfficiency.grade === 'A' ? '#dcfce7' : kwData.adEfficiency.grade === 'B' ? '#dbeafe' : kwData.adEfficiency.grade === 'C' ? '#fef9c3' : '#fee2e2',
                                                                        color: kwData.adEfficiency.grade === 'A' ? '#16a34a' : kwData.adEfficiency.grade === 'B' ? '#1e40af' : kwData.adEfficiency.grade === 'C' ? '#ca8a04' : '#dc2626'
                                                                    } }, kwData.adEfficiency.grade + '등급')
                                                                ),
                                                                React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 } },
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f8fafc', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '효율 점수'),
                                                                        React.createElement('div', { style: { fontSize: 28, fontWeight: 700, color: kwData.adEfficiency.efficiencyScore >= 70 ? '#16a34a' : kwData.adEfficiency.efficiencyScore >= 40 ? '#ca8a04' : '#dc2626' } }, kwData.adEfficiency.efficiencyScore)
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f8fafc', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '검색량'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, fmt(kwData.adEfficiency.totalVolume))
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f8fafc', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, 'CTR'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, kwData.adEfficiency.ctr + '%')
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f8fafc', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '현재 순위'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, kwData.adEfficiency.currentRank ? kwData.adEfficiency.currentRank + '위' : '미측정')
                                                                    )
                                                                ),
                                                                React.createElement('div', { style: { padding: 12, background: '#faf5ff', borderRadius: 8, fontSize: 13, color: '#6b21a8' } }, '💡 ' + kwData.adEfficiency.advice)
                                                            ),

                                                            /* ⑤ 최적 등록 타이밍 */
                                                            kwData.optimalTiming && React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 16 } },
                                                                React.createElement('div', { style: { fontSize: 16, fontWeight: 700, marginBottom: 16 } }, '⏰ 최적 등록 타이밍 — "' + aiSelectedKeyword + '"'),
                                                                kwData.optimalTiming.ready === false ?
                                                                    React.createElement('div', { style: { textAlign: 'center', padding: 20, color: '#94a3b8', fontSize: 13 } }, kwData.optimalTiming.message) :
                                                                    React.createElement('div', null,
                                                                        /* 요일별 막대 */
                                                                        kwData.optimalTiming.weekdayData && React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'flex-end', height: 120, marginBottom: 16 } },
                                                                            kwData.optimalTiming.weekdayData.map(function(d) {
                                                                                var maxRank = Math.max.apply(null, kwData.optimalTiming.weekdayData.map(function(x) { return x.avgRank; }));
                                                                                var barH = maxRank > 0 ? Math.max(20, (d.avgRank / maxRank) * 100) : 40;
                                                                                return React.createElement('div', { key: d.day, style: { flex: 1, textAlign: 'center' } },
                                                                                    React.createElement('div', { style: { fontSize: 11, fontWeight: 600, marginBottom: 4, color: d.isBest ? '#16a34a' : d.isWorst ? '#dc2626' : '#64748b' } }, d.avgRank + '위'),
                                                                                    React.createElement('div', { style: {
                                                                                        height: barH, borderRadius: '6px 6px 0 0', margin: '0 auto', width: '70%',
                                                                                        background: d.isBest ? '#22c55e' : d.isWorst ? '#ef4444' : '#94a3b8'
                                                                                    } }),
                                                                                    React.createElement('div', { style: { fontSize: 12, fontWeight: 600, marginTop: 6, color: d.isBest ? '#16a34a' : d.isWorst ? '#dc2626' : '#334155' } }, d.day)
                                                                                );
                                                                            })
                                                                        ),
                                                                        React.createElement('div', { style: { padding: 12, background: '#faf5ff', borderRadius: 8, fontSize: 13, color: '#6b21a8' } }, '💡 ' + kwData.optimalTiming.advice)
                                                                    )
                                                            ),

                                                            /* ③ 리뷰 감성 */
                                                            kwData.reviewSentiment && React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 16 } },
                                                                React.createElement('div', { style: { fontSize: 16, fontWeight: 700, marginBottom: 16 } }, '💬 리뷰 감성 분석 — "' + aiSelectedKeyword + '"'),
                                                                kwData.reviewSentiment.alert && React.createElement('div', { style: { marginBottom: 12, padding: 10, borderRadius: 8, fontSize: 13, background: kwData.reviewSentiment.alert.indexOf('급증') !== -1 ? '#fee2e2' : '#dcfce7', color: kwData.reviewSentiment.alert.indexOf('급증') !== -1 ? '#991b1b' : '#166534' } }, '⚠️ ' + kwData.reviewSentiment.alert),
                                                                kwData.reviewSentiment.latest && React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 } },
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#dcfce7', borderRadius: 10, padding: 12, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '긍정'),
                                                                        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: '#16a34a' } }, kwData.reviewSentiment.latest.positiveRate + '%')
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#fee2e2', borderRadius: 10, padding: 12, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '부정'),
                                                                        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: '#dc2626' } }, kwData.reviewSentiment.latest.negativeRate + '%')
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f1f5f9', borderRadius: 10, padding: 12, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '중립'),
                                                                        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: '#64748b' } }, (100 - kwData.reviewSentiment.latest.positiveRate - kwData.reviewSentiment.latest.negativeRate).toFixed(1) + '%')
                                                                    )
                                                                ),
                                                                React.createElement('div', { style: { fontSize: 12, color: '#94a3b8' } }, '분석 데이터: ' + kwData.reviewSentiment.dataPoints + '건')
                                                            )
                                                        );
                                                    })()}
                                                </div>
                                            )}
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
        if (client && client.naver_store_url) {
            // 스마트스토어 URL에서 추적 파라미터 제거
            var url = client.naver_store_url;
            try {
                var u = new URL(url);
                if (u.hostname.indexOf('smartstore.naver.com') !== -1) {
                    url = u.origin + u.pathname;
                }
            } catch(e) {}
            setProductUrl(url);
        }
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
