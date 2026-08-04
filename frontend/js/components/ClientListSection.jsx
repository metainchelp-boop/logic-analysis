/* ClientListSection — 메인 분석 페이지 업체 리스트 (v3.7)
 * 등록된 업체 카드를 가나다순으로 표시하고, 클릭 시 자동 분석 실행
 */
window.ClientListSection = function ClientListSection({ currentUser, onClientClick, onNavigateToClient }) {
    var useState = React.useState;
    var useEffect = React.useEffect;
    var useCallback = React.useCallback;

    var _s1 = useState([]); var clients = _s1[0]; var setClients = _s1[1];
    var _s2 = useState(true); var loading = _s2[0]; var setLoading = _s2[1];
    var _s3 = useState(function() {
        /* 셸 전역 검색(Ctrl+K) 핸드오프 — 1회 소비 */
        try {
            var g = sessionStorage.getItem('logic_global_q');
            if (g) { sessionStorage.removeItem('logic_global_q'); return g; }
        } catch (e) {}
        return '';
    }); var query = _s3[0]; var setQuery = _s3[1];
    var _s4 = useState(null); var mgrFilter = _s4[0]; var setMgrFilter = _s4[1]; // 담당자 탭 필터(null=전체)

    // 상위 계정(관리자)만 담당자(등록 직원) 정보를 노출 (매니저는 본인 것만 보므로 불필요)
    var isAdmin = !!(currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin'));

    var _s5 = useState([]); var managers = _s5[0]; var setManagers = _s5[1];     // 배정 가능한 담당자
    var _s6 = useState(null); var editMgrId = _s6[0]; var setEditMgrId = _s6[1]; // 담당자 변경 중인 업체 id

    /* 2차 확산(2026-08-05): 업체별 순위 롤업(rank-overview) — 카드에 대표 키워드
       순위·변동·미니 추이 표시용. 실패해도 카드 기본 표시는 그대로(가산). */
    var _s7 = useState({}); var rankOv = _s7[0]; var setRankOv = _s7[1];         // { clientId: overviewItem }
    var _s8 = useState(false); var attnOnly = _s8[0]; var setAttnOnly = _s8[1];  // ⚠️ 주의만 보기

    useEffect(function() {
        api.get('/cd/rank-overview').then(function(res) {
            if (res && res.success && res.data) {
                var m = {};
                res.data.forEach(function(it) { m[it.id] = it; });
                setRankOv(m);
            }
        }).catch(function() {});
    }, []);

    /* 카드 미니 스파크라인 — 대표 키워드 8일 추이 (낮은 순위 = 위) */
    var miniSpark = function(series) {
        var pts = (series || []).filter(function(p) { return p.rank != null; });
        if (pts.length < 2) return null;
        var w = 200, h = 22, pad = 2;
        var rs = pts.map(function(p) { return p.rank; });
        var mn = Math.min.apply(null, rs), mx = Math.max.apply(null, rs);
        var span = (mx - mn) || 1;
        var coords = pts.map(function(p, i) {
            return (pad + (w - pad * 2) * (i / (pts.length - 1))).toFixed(1) + ',' +
                   (pad + (h - pad * 2) * ((p.rank - mn) / span)).toFixed(1);
        });
        var improving = rs[rs.length - 1] <= rs[0];
        return React.createElement('svg', { width: '100%', height: h, viewBox: '0 0 ' + w + ' ' + h, preserveAspectRatio: 'none', style: { display: 'block', margin: '4px 0 2px' } },
            React.createElement('polyline', { points: coords.join(' '), fill: 'none', stroke: improving ? '#16a34a' : '#dc2626', strokeWidth: 1.8, strokeLinejoin: 'round', strokeLinecap: 'round' }));
    };

    useEffect(function() {
        if (!isAdmin) return;
        api.get('/clients/assignable-managers').then(function(res) {
            if (res && res.success) setManagers(res.data || []);
        }).catch(function() {});
    }, [isAdmin]);

    // 담당자(created_by) 변경
    var changeManager = function(clientId, managerId) {
        var mid = parseInt(managerId, 10);
        if (!mid) { setEditMgrId(null); return; }
        api.put('/clients/' + clientId + '/manager', { manager_id: mid }).then(function(res) {
            if (res && res.success) {
                setClients(function(prev) {
                    return prev.map(function(c) { return c.id === clientId ? Object.assign({}, c, { created_by: mid, manager_name: res.manager_name }) : c; });
                });
                try { toast.success('담당자를 변경했습니다.'); } catch(e) {}
            }
            setEditMgrId(null);
        }).catch(function() { setEditMgrId(null); });
    };

    /* 업체 목록 로드 */
    var loadClients = useCallback(function() {
        setLoading(true);
        api.get('/cd/my-clients').then(function(res) {
            if (res.success) setClients(res.data || []);
            setLoading(false);
        }).catch(function() { setLoading(false); });
    }, []);

    useEffect(function() { loadClients(); }, [loadClients]);

    /* 셸 전역 검색 이벤트 — 대시보드에 이미 있을 때도 검색어 반영 */
    useEffect(function() {
        var onSearch = function(ev) {
            if (ev && typeof ev.detail === 'string') {
                setQuery(ev.detail);
                try { sessionStorage.removeItem('logic_global_q'); } catch (e) {}
            }
        };
        window.addEventListener('logic-global-search', onSearch);
        return function() { window.removeEventListener('logic-global-search', onSearch); };
    }, []);

    /* 업체에서 대표 키워드/상품URL 추출 */
    var getClientAnalysisParams = function(client) {
        // 1순위: 최근 분석한 키워드 + URL
        if (client.analyzed_keywords && client.analyzed_keywords.length > 0) {
            var latest = client.analyzed_keywords[0]; // 서버에서 analyzed_date DESC 정렬
            return {
                keyword: latest.keyword,
                productUrl: latest.product_url || '',
                companyName: client.name,
                clientId: client.id,
                lastDate: latest.analyzed_date || ''
            };
        }
        // 2순위: main_keywords에서 첫 키워드
        if (client.main_keywords) {
            var firstKw = String(client.main_keywords).split(',')[0].trim();
            if (firstKw) {
                return {
                    keyword: firstKw,
                    productUrl: client.naver_store_url || '',
                    companyName: client.name,
                    clientId: client.id,
                    lastDate: ''
                };
            }
        }
        return null;
    };

    /* 대표 키워드 텍스트 */
    var getRepresentativeKeyword = function(client) {
        if (client.analyzed_keywords && client.analyzed_keywords.length > 0) {
            return client.analyzed_keywords[0].keyword;
        }
        if (client.main_keywords) {
            return String(client.main_keywords).split(',')[0].trim();
        }
        return '-';
    };

    /* 마지막 분석 일자 텍스트 */
    var getLastAnalyzedText = function(client) {
        if (client.analyzed_keywords && client.analyzed_keywords.length > 0) {
            var d = client.analyzed_keywords[0].analyzed_date;
            return d || '-';
        }
        return '미분석';
    };

    /* ⚠️ 주의 판정 — 추적 키워드는 있는데 노출 0 (rank-overview 기준) */
    var isAttention = function(c) {
        var ov = rankOv[c.id];
        return !!(ov && ov.keywords > 0 && ov.exposed === 0);
    };

    /* 검색 + 가나다 정렬 */
    var filtered = clients
        .filter(function(c) {
            // 담당자 탭 필터 (null = 전체)
            if (mgrFilter && (c.manager_name || '(미지정)') !== mgrFilter) return false;
            if (attnOnly && !isAttention(c)) return false;
            if (!query.trim()) return true;
            var q = query.trim().toLowerCase();
            return (c.name || '').toLowerCase().indexOf(q) !== -1
                || (c.main_keywords || '').toLowerCase().indexOf(q) !== -1;
        })
        .slice()
        .sort(function(a, b) {
            return (a.name || '').localeCompare(b.name || '', 'ko');
        });

    /* 업체 상세 보기 핸들러 — 진행중 업체 탭 상세 화면으로 이동 */
    var handleViewClient = function(client) {
        if (onNavigateToClient) {
            onNavigateToClient(client.name || '', client.naver_store_url || '');
        }
    };

    /* ==================== 렌더링 ==================== */
    return React.createElement('div', { className: 'section', style: { paddingTop: 24, paddingBottom: 24 } },
        React.createElement('div', { className: 'container' },
            /* 헤더 */
            React.createElement('div', {
                style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 12 }
            },
                React.createElement('div', null,
                    React.createElement('h2', {
                        style: { fontSize: 20, fontWeight: 700, color: '#1e293b', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }
                    }, '🏢 등록 업체', clients.length > 0 && React.createElement('span', { style: { fontSize: 14, fontWeight: 500, color: '#3b82f6', marginLeft: 4 } }, '(' + clients.length + '개)')),
                    React.createElement('p', {
                        style: { fontSize: 13, color: '#64748b', margin: '4px 0 0 0' }
                    }, '업체 상세 보기를 클릭하면 분석 이력과 순위를 확인할 수 있습니다.')
                ),
                React.createElement('input', {
                    type: 'text',
                    placeholder: '업체명/키워드 검색...',
                    value: query,
                    onChange: function(e) { setQuery(e.target.value); },
                    style: {
                        padding: '8px 14px',
                        fontSize: 13,
                        border: '1px solid #e2e8f0',
                        borderRadius: 8,
                        minWidth: 240,
                        outline: 'none'
                    }
                })
            ),

            /* 2차 확산: KPI 스트립 — 업체·오늘 분석·상승 키워드·주의(클릭 필터) */
            !loading && clients.length > 0 && (function() {
                var today = new Date().toISOString().slice(0, 10);
                var analyzedToday = clients.filter(function(c) {
                    return c.analyzed_keywords && c.analyzed_keywords[0] && String(c.analyzed_keywords[0].analyzed_date || '').slice(0, 10) === today;
                }).length;
                var upTotal = 0, attn = 0, hasOv = false;
                clients.forEach(function(c) {
                    var ov = rankOv[c.id];
                    if (ov) { hasOv = true; upTotal += (ov.up || 0); if (isAttention(c)) attn++; }
                });
                var kpi = function(k, v, sub, subColor, onClick, active) {
                    return React.createElement('div', {
                        onClick: onClick || null,
                        style: { background: active ? '#fffbeb' : '#f8fafc', border: '1px solid ' + (active ? '#f59e0b' : '#eef2f6'), borderRadius: 12, padding: '11px 15px', cursor: onClick ? 'pointer' : 'default', flex: '1 1 150px', minWidth: 140 }
                    },
                        React.createElement('div', { style: { fontSize: 11, fontWeight: 700, color: '#94a3b8', letterSpacing: '.03em' } }, k),
                        React.createElement('div', { style: { fontSize: 20, fontWeight: 800, color: '#0f172a', marginTop: 1 } }, v),
                        sub && React.createElement('div', { style: { fontSize: 11, color: subColor || '#94a3b8' } }, sub)
                    );
                };
                return React.createElement('div', { style: { display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 } },
                    kpi('내 업체', clients.length, null),
                    kpi('오늘 자동 분석', analyzedToday, '보고서 생성됨'),
                    hasOv && kpi('상승 키워드', '▲ ' + upTotal, '전일 대비', '#16a34a'),
                    hasOv && kpi('주의 필요', attn, attnOnly ? '필터 적용 중 — 클릭 해제' : '노출 0 — 클릭 시 필터', '#b45309',
                        function() { setAttnOnly(!attnOnly); }, attnOnly)
                );
            })(),

            /* 담당자별 구분 탭 (상위 계정 전용) — 클릭 시 해당 담당자 업체만 모아보기 */
            isAdmin && !loading && clients.length > 0 && (function() {
                var counts = {};
                clients.forEach(function(c) { var m = c.manager_name || '(미지정)'; counts[m] = (counts[m] || 0) + 1; });
                var names = Object.keys(counts).sort(function(a, b) { return counts[b] - counts[a]; });
                var mkTab = function(label, val, count) {
                    var on = mgrFilter === val;
                    return React.createElement('button', { key: label, onClick: function() { setMgrFilter(val); },
                        style: { fontSize: 12, fontWeight: 700, padding: '6px 12px', borderRadius: 999, cursor: 'pointer', whiteSpace: 'nowrap',
                                 border: '1px solid ' + (on ? '#6d28d9' : '#e9d5ff'), background: on ? '#6d28d9' : '#faf5ff', color: on ? '#fff' : '#6d28d9' } },
                        label + (count != null ? ' ' + count : ''));
                };
                return React.createElement('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 16, paddingBottom: 14, borderBottom: '1px dashed #e2e8f0' } },
                    React.createElement('span', { style: { fontSize: 12, color: '#94a3b8', fontWeight: 700, marginRight: 2 } }, '담당자별 보기'),
                    mkTab('전체', null, clients.length),
                    names.map(function(m) { return mkTab('👤 ' + m, m, counts[m]); })
                );
            })(),

            /* 로딩 */
            loading && React.createElement('div', {
                style: { textAlign: 'center', padding: '40px 20px', color: '#64748b', fontSize: 14 }
            }, '업체 목록 불러오는 중...'),

            /* 빈 상태 */
            !loading && filtered.length === 0 && clients.length === 0 && React.createElement('div', {
                style: {
                    textAlign: 'center',
                    padding: '40px 20px',
                    background: '#f8fafc',
                    borderRadius: 12,
                    border: '1px dashed #cbd5e1'
                }
            },
                React.createElement('div', { style: { fontSize: 40, marginBottom: 8 } }, '📋'),
                React.createElement('div', { style: { fontSize: 14, color: '#475569', fontWeight: 600, marginBottom: 4 } },
                    '등록된 업체가 없습니다'
                ),
                React.createElement('div', { style: { fontSize: 12, color: '#94a3b8' } },
                    '상단에서 직접 키워드를 입력해 분석하거나, 업체관리 탭에서 업체를 먼저 등록해주세요.'
                )
            ),

            /* 검색 결과 없음 */
            !loading && filtered.length === 0 && clients.length > 0 && React.createElement('div', {
                style: { textAlign: 'center', padding: '30px 20px', color: '#94a3b8', fontSize: 13 }
            }, '검색 결과가 없습니다.'),

            /* 업체 카드 그리드 */
            !loading && filtered.length > 0 && React.createElement('div', {
                style: {
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
                    gap: 14
                }
            },
                filtered.map(function(client) {
                    var lastDate = getLastAnalyzedText(client);
                    var ov = rankOv[client.id];
                    var attn = isAttention(client);
                    var repKw = ov && ov.top_keywords && ov.top_keywords[0];
                    var repDelta = null;
                    if (ov && ov.rep_series && ov.rep_series.length >= 2) {
                        var _rs = ov.rep_series;
                        if (_rs[_rs.length - 1].rank != null && _rs[_rs.length - 2].rank != null) {
                            repDelta = _rs[_rs.length - 2].rank - _rs[_rs.length - 1].rank; // 양수=상승
                        }
                    }

                    return React.createElement('div', {
                        key: client.id,
                        style: {
                            background: '#fff',
                            border: '1px solid ' + (attn ? '#f59e0b' : '#e2e8f0'),
                            borderRadius: 12,
                            padding: '16px 18px',
                            transition: 'all 0.15s ease',
                            boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'space-between'
                        },
                        onMouseEnter: function(e) {
                            e.currentTarget.style.borderColor = '#3b82f6';
                            e.currentTarget.style.boxShadow = '0 4px 12px rgba(108,92,231,0.15)';
                            e.currentTarget.style.transform = 'translateY(-2px)';
                        },
                        onMouseLeave: function(e) {
                            e.currentTarget.style.borderColor = attn ? '#f59e0b' : '#e2e8f0';
                            e.currentTarget.style.boxShadow = '0 1px 2px rgba(0,0,0,0.04)';
                            e.currentTarget.style.transform = 'translateY(0)';
                        }
                    },
                        /* 업체명 + 대표 키워드 순위(2차 확산) + 마지막 분석 */
                        React.createElement('div', null,
                            React.createElement('div', {
                                style: { fontSize: 15, fontWeight: 700, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginBottom: 6 }
                            },
                                client.vertical === 'place' && React.createElement('span', { title: '플레이스 업체', style: { marginRight: 4 } }, '📍'),
                                client.name || '(이름 없음)'),

                            /* 대표 키워드 현재 순위 + 변동 + 미니 추이 */
                            ov && React.createElement('div', { style: { marginBottom: 7 } },
                                repKw
                                    ? React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 6 } },
                                        React.createElement('span', { style: { fontSize: 12, color: '#475569', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, repKw.keyword),
                                        React.createElement('span', { style: { fontSize: 16, fontWeight: 800, color: repKw.rank <= 10 ? '#16a34a' : '#0f172a' } }, repKw.rank + '위'),
                                        repDelta != null && repDelta !== 0 && React.createElement('span', {
                                            style: { fontSize: 11, fontWeight: 800, borderRadius: 6, padding: '1px 6px',
                                                     color: repDelta > 0 ? '#dc2626' : '#2563eb', background: repDelta > 0 ? '#fef2f2' : '#eff6ff' }
                                        }, (repDelta > 0 ? '▲' : '▼') + Math.abs(repDelta)))
                                    : (ov.keywords > 0
                                        ? React.createElement('div', { style: { fontSize: 12, fontWeight: 700, color: '#b45309' } }, '⚠️ 추적 ' + ov.keywords + '개 전부 미노출')
                                        : null),
                                miniSpark(ov.rep_series),
                                ov.keywords > 0 && React.createElement('div', { style: { fontSize: 11, color: '#94a3b8' } },
                                    '키워드 ' + ov.keywords + ' · 노출 ' + ov.exposed + (ov.top10 ? ' · TOP10 ' + ov.top10 : ''))
                            ),

                            React.createElement('div', {
                                style: { fontSize: 11, color: '#dc2626', marginBottom: isAdmin ? 4 : 12 }
                            }, '마지막 분석: ' + lastDate),
                            isAdmin && React.createElement('div', {
                                style: { fontSize: 11, color: '#6d28d9', fontWeight: 700, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }
                            },
                                editMgrId === client.id
                                    ? React.createElement('select', {
                                        defaultValue: client.created_by || '',
                                        onClick: function(e){ e.stopPropagation(); },
                                        onChange: function(e){ e.stopPropagation(); changeManager(client.id, e.target.value); },
                                        style: { fontSize: 11, padding: '3px 6px', borderRadius: 6, border: '1px solid #ddd6fe', maxWidth: '100%' }
                                    },
                                        React.createElement('option', { value: '' }, '담당자 선택...'),
                                        managers.map(function(m){ return React.createElement('option', { key: m.id, value: m.id }, m.name + (m.role !== 'manager' ? ' (' + m.role + ')' : '')); })
                                    )
                                    : React.createElement(React.Fragment, null,
                                        React.createElement('span', null, '👤 담당자: ' + (client.manager_name || '-')),
                                        React.createElement('button', { onClick: function(e){ e.stopPropagation(); setEditMgrId(client.id); },
                                            style: { fontSize: 10, fontWeight: 700, color: '#6d28d9', background: '#ede9fe', border: 'none', borderRadius: 6, padding: '2px 7px', cursor: 'pointer' } }, '변경')
                                    )
                            )
                        ),

                        /* 업체 상세 보기 버튼 */
                        React.createElement('button', {
                            onClick: function() { handleViewClient(client); },
                            style: {
                                display: 'block',
                                width: '100%',
                                textAlign: 'center',
                                background: '#3b82f6',
                                color: '#fff',
                                border: 'none',
                                padding: '8px 0',
                                borderRadius: 8,
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: 'pointer'
                            }
                        }, '업체 상세 보기 →'),

                        /* 자동 추적 켜기/끄기 (호출 다이어트) — 계약만료·환불·홀딩 등 관리 중단 업체는
                           일일 자동분석·순위추적에서 제외. 기록·조회는 유지. viewer는 조회만 */
                        currentUser && currentUser.role !== 'viewer' && React.createElement('button', {
                            onClick: function(e) {
                                e.stopPropagation();
                                var next = (client.auto_analysis === 0) ? 1 : 0;
                                var label = next === 0 ? '끄기' : '켜기';
                                if (!window.confirm('"' + (client.name || '') + '" 자동 추적을 ' + label + ' 할까요?' + (next === 0 ? '\n(계약만료·환불·홀딩 등 관리 중단 업체 권장 — 기록·조회는 그대로 유지됩니다)' : ''))) return;
                                api.put('/clients/' + client.id, { auto_analysis: next }).then(function(res) {
                                    if (res && (res.success === undefined || res.success)) {
                                        try { toast.success('자동 추적 ' + label + ' 완료: ' + (client.name || '')); } catch (e2) {}
                                        loadClients();
                                    } else {
                                        try { toast.error('변경 실패: ' + ((res && res.detail) || '오류')); } catch (e2) {}
                                    }
                                }).catch(function(err) {
                                    try { toast.error('변경 실패: ' + (err.message || '네트워크 오류')); } catch (e2) {}
                                });
                            },
                            style: {
                                display: 'block',
                                width: '100%',
                                textAlign: 'center',
                                marginTop: 6,
                                background: client.auto_analysis === 0 ? '#fef3c7' : '#f1f5f9',
                                color: client.auto_analysis === 0 ? '#92400e' : '#475569',
                                border: '1px solid ' + (client.auto_analysis === 0 ? '#fcd34d' : '#e2e8f0'),
                                padding: '6px 0',
                                borderRadius: 8,
                                fontSize: 11.5,
                                fontWeight: 700,
                                cursor: 'pointer'
                            }
                        }, client.auto_analysis === 0 ? '⏸ 자동 추적 꺼짐 — 켜기' : '▶ 자동 추적 중 — 끄기'),

                        /* 중지 상태 배지(viewer 포함 전원에게 보임) */
                        client.auto_analysis === 0 && (!currentUser || currentUser.role === 'viewer') && React.createElement('div', {
                            style: { marginTop: 6, textAlign: 'center', fontSize: 11, fontWeight: 700, color: '#92400e' }
                        }, '⏸ 자동 추적 중지됨')
                    );
                })
            )
        )
    );
};
