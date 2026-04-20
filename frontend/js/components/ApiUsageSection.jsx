/* ApiUsageSection — API 사용량 및 비용 대시보드 (superadmin 전용, v3.9.13) */
window.ApiUsageSection = function ApiUsageSection() {
    var useState = React.useState;
    var useEffect = React.useEffect;

    var _s = useState(null); var data = _s[0]; var setData = _s[1];
    var _l = useState(true); var loading = _l[0]; var setLoading = _l[1];
    var _t = useState('overview'); var tab = _t[0]; var setTab = _t[1];
    var _p = useState('month'); var period = _p[0]; var setPeriod = _p[1];
    var _h = useState(null); var hovered = _h[0]; var setHovered = _h[1];

    var _e = useState(''); var errMsg = _e[0]; var setErrMsg = _e[1];

    useEffect(function() {
        api.get('/admin/api-usage').then(function(res) {
            if (res.success) {
                setData(res.data);
            } else {
                setErrMsg(res.error || res.detail || 'API 데이터 로드 실패');
                // 빈 데이터로 초기화하여 UI는 표시
                setData({ today: { calls: 0, cost_krw: 0, input_tokens: 0, output_tokens: 0 }, month: { calls: 0, cost_krw: 0, input_tokens: 0, output_tokens: 0 }, avg_cost: 0, daily_avg_cost: 0, daily: [], clients: [], logs: [] });
            }
            setLoading(false);
        }).catch(function(e) {
            setErrMsg('네트워크 오류: ' + (e.message || ''));
            setData({ today: { calls: 0, cost_krw: 0, input_tokens: 0, output_tokens: 0 }, month: { calls: 0, cost_krw: 0, input_tokens: 0, output_tokens: 0 }, avg_cost: 0, daily_avg_cost: 0, daily: [], clients: [], logs: [] });
            setLoading(false);
        });
    }, []);

    if (loading) return React.createElement('div', { className: 'section', id: 'sec-api-usage' },
        React.createElement('div', { className: 'container' },
            React.createElement('div', { style: { textAlign: 'center', padding: '40px 0', color: '#94a3b8' } }, '로딩 중...')
        )
    );
    if (!data) return null;

    var daily = data.daily || [];
    var clients = data.clients || [];
    var logs = data.logs || [];
    var today = data.today || {};
    var month = data.month || {};
    var avgCost = data.avg_cost || 0;
    var dailyAvg = data.daily_avg_cost || 0;

    // 기간별 일별 데이터
    var chartData = period === 'week' ? daily.slice(-7) : daily;
    var maxCost = Math.max.apply(null, chartData.map(function(d) { return d.cost_krw; }).concat([1]));

    var tabs = [
        { key: 'overview', label: '비용 요약' },
        { key: 'clients', label: '업체별 분석' },
        { key: 'logs', label: '호출 로그' },
    ];

    var summaryCards = [
        { label: '오늘 비용', value: fmt(today.cost_krw || 0) + '원', sub: (today.calls || 0) + '회 호출', icon: '📊', color: '#6366f1', bg: '#eef2ff' },
        { label: '이번 달 누적', value: fmt(month.cost_krw || 0) + '원', sub: (month.calls || 0) + '회 호출', icon: '📅', color: '#8b5cf6', bg: '#f5f3ff' },
        { label: '1회 평균 비용', value: avgCost + '원', sub: 'Claude Sonnet 4', icon: '⚡', color: '#0ea5e9', bg: '#f0f9ff' },
        { label: '일 평균 비용', value: fmt(dailyAvg) + '원', sub: '일 평균 ' + (month.calls ? Math.round(month.calls / 30) : 0) + '회', icon: '📈', color: '#10b981', bg: '#ecfdf5' },
    ];

    var totalClientCost = clients.reduce(function(s, c) { return s + c.cost_krw; }, 0) || 1;
    var totalInputTokens = month.input_tokens || 0;
    var totalOutputTokens = month.output_tokens || 0;
    var totalTokenCost = totalInputTokens * 3 + totalOutputTokens * 15;
    var inputPct = totalTokenCost > 0 ? Math.round((totalInputTokens * 3) / totalTokenCost * 100) : 25;
    var outputPct = 100 - inputPct;

    return React.createElement('div', { className: 'section', id: 'sec-api-usage' },
        React.createElement('div', { className: 'container' },
            /* 헤더 */
            React.createElement('div', { className: 'section-title' },
                React.createElement('span', { className: 'icon', style: { background: '#eef2ff' } }, '💰'),
                'API 사용량 및 비용'
            ),
            React.createElement('p', { style: { fontSize: 13, color: '#94a3b8', margin: '-8px 0 16px 0' } },
                'Claude AI API 호출 내역과 비용을 실시간으로 확인합니다.'
            ),

            errMsg && React.createElement('div', {
                style: { padding: '12px 16px', background: '#fffbeb', borderRadius: 8, border: '1px solid #fde68a', fontSize: 13, color: '#92400e', marginBottom: 16 }
            }, '아직 분석 데이터가 없습니다. 키워드 분석을 실행하면 비용이 자동으로 기록됩니다.'),

            /* 요약 카드 4개 */
            React.createElement('div', {
                style: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }
            },
                summaryCards.map(function(c, i) {
                    return React.createElement('div', {
                        key: i, className: 'card',
                        style: { background: 'linear-gradient(135deg, ' + c.bg + ', #fff)', borderLeft: '3px solid ' + c.color, padding: 16 }
                    },
                        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 } },
                            React.createElement('span', { style: { fontSize: 16 } }, c.icon),
                            React.createElement('span', { style: { fontSize: 12, color: '#64748b', fontWeight: 500 } }, c.label)
                        ),
                        React.createElement('div', { style: { fontSize: 20, fontWeight: 700, color: '#1e293b', marginBottom: 2 } }, c.value),
                        React.createElement('div', { style: { fontSize: 11, color: '#94a3b8' } }, c.sub)
                    );
                })
            ),

            /* 탭 전환 */
            React.createElement('div', {
                style: { display: 'flex', gap: 4, marginBottom: 16, background: '#f1f5f9', borderRadius: 10, padding: 4 }
            },
                tabs.map(function(t) {
                    var active = tab === t.key;
                    return React.createElement('button', {
                        key: t.key, onClick: function() { setTab(t.key); },
                        style: {
                            flex: 1, padding: '8px 16px', border: 'none', cursor: 'pointer',
                            borderRadius: 8, fontSize: 13, fontWeight: 600,
                            background: active ? '#fff' : 'transparent',
                            color: active ? '#4f46e5' : '#64748b',
                            boxShadow: active ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                            transition: 'all 0.2s',
                        }
                    }, t.label);
                })
            ),

            /* ========== 비용 요약 탭 ========== */
            tab === 'overview' && React.createElement('div', null,
                /* 일별 차트 */
                React.createElement('div', { className: 'card', style: { marginBottom: 16 } },
                    React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } },
                        React.createElement('div', { style: { fontWeight: 600, fontSize: 15, color: '#1e293b' } }, '일별 비용 추이'),
                        React.createElement('div', { style: { display: 'flex', gap: 4, background: '#f8fafc', borderRadius: 8, padding: 2 } },
                            ['7일', '30일'].map(function(p) {
                                var active = (period === 'week' && p === '7일') || (period === 'month' && p === '30일');
                                return React.createElement('button', {
                                    key: p,
                                    onClick: function() { setPeriod(p === '7일' ? 'week' : 'month'); },
                                    style: {
                                        padding: '4px 12px', border: 'none', borderRadius: 6,
                                        fontSize: 12, cursor: 'pointer', fontWeight: 500,
                                        background: active ? '#6366f1' : 'transparent',
                                        color: active ? '#fff' : '#64748b',
                                    }
                                }, p);
                            })
                        )
                    ),
                    /* 바 차트 */
                    React.createElement('div', {
                        style: { display: 'flex', alignItems: 'flex-end', gap: 3, height: 160, padding: '0 4px' }
                    },
                        chartData.map(function(d, i) {
                            var h = Math.max((d.cost_krw / maxCost) * 140, 2);
                            var isHov = hovered === i;
                            return React.createElement('div', {
                                key: i,
                                style: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%', cursor: 'pointer', position: 'relative' },
                                onMouseEnter: function() { setHovered(i); },
                                onMouseLeave: function() { setHovered(null); },
                            },
                                isHov && React.createElement('div', {
                                    style: {
                                        position: 'absolute', bottom: h + 8,
                                        background: '#1e293b', color: '#fff', padding: '4px 8px',
                                        borderRadius: 6, fontSize: 11, whiteSpace: 'nowrap',
                                        zIndex: 10, boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
                                    }
                                }, d.day.slice(5) + ' | ' + d.calls + '회 | ' + fmt(d.cost_krw) + '원'),
                                React.createElement('div', {
                                    style: {
                                        width: '100%', height: h, borderRadius: '3px 3px 0 0',
                                        background: isHov ? 'linear-gradient(180deg, #6366f1, #4f46e5)' :
                                            (i >= chartData.length - 5 ? 'linear-gradient(180deg, #818cf8, #6366f1)' : 'linear-gradient(180deg, #c7d2fe, #a5b4fc)'),
                                        transition: 'all 0.2s',
                                    }
                                })
                            );
                        })
                    ),
                    chartData.length > 0 && React.createElement('div', {
                        style: { display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#94a3b8', marginTop: 6, padding: '0 4px' }
                    },
                        React.createElement('span', null, chartData[0].day.slice(5)),
                        React.createElement('span', null, period === 'week' ? '최근 7일' : '최근 30일'),
                        React.createElement('span', null, chartData[chartData.length - 1].day.slice(5))
                    )
                ),

                /* 비용 구성 분석 */
                React.createElement('div', { className: 'card' },
                    React.createElement('div', { style: { fontWeight: 600, fontSize: 15, color: '#1e293b', marginBottom: 16 } }, '비용 구성 분석'),
                    React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 } },
                        /* 입력 토큰 */
                        React.createElement('div', { style: { background: '#f8fafc', borderRadius: 10, padding: 16 } },
                            React.createElement('div', { style: { fontSize: 12, color: '#64748b', marginBottom: 8, fontWeight: 500 } }, '입력 토큰 (Input)'),
                            React.createElement('div', { style: { fontSize: 13, color: '#1e293b', marginBottom: 4 } }, '이번 달: ' + fmt(totalInputTokens) + ' 토큰'),
                            React.createElement('div', { style: { fontSize: 12, color: '#94a3b8' } }, '단가: $3 / 1M 토큰'),
                            React.createElement('div', { style: { marginTop: 8, height: 6, background: '#e2e8f0', borderRadius: 3, overflow: 'hidden' } },
                                React.createElement('div', { style: { width: inputPct + '%', height: '100%', background: 'linear-gradient(90deg, #818cf8, #6366f1)', borderRadius: 3 } })
                            ),
                            React.createElement('div', { style: { fontSize: 11, color: '#6366f1', marginTop: 4, fontWeight: 600 } }, '전체 비용의 약 ' + inputPct + '%')
                        ),
                        /* 출력 토큰 */
                        React.createElement('div', { style: { background: '#f8fafc', borderRadius: 10, padding: 16 } },
                            React.createElement('div', { style: { fontSize: 12, color: '#64748b', marginBottom: 8, fontWeight: 500 } }, '출력 토큰 (Output)'),
                            React.createElement('div', { style: { fontSize: 13, color: '#1e293b', marginBottom: 4 } }, '이번 달: ' + fmt(totalOutputTokens) + ' 토큰'),
                            React.createElement('div', { style: { fontSize: 12, color: '#94a3b8' } }, '단가: $15 / 1M 토큰'),
                            React.createElement('div', { style: { marginTop: 8, height: 6, background: '#e2e8f0', borderRadius: 3, overflow: 'hidden' } },
                                React.createElement('div', { style: { width: outputPct + '%', height: '100%', background: 'linear-gradient(90deg, #a78bfa, #8b5cf6)', borderRadius: 3 } })
                            ),
                            React.createElement('div', { style: { fontSize: 11, color: '#8b5cf6', marginTop: 4, fontWeight: 600 } }, '전체 비용의 약 ' + outputPct + '%')
                        )
                    )
                )
            ),

            /* ========== 업체별 분석 탭 ========== */
            tab === 'clients' && React.createElement('div', { className: 'card' },
                React.createElement('div', { style: { fontWeight: 600, fontSize: 15, color: '#1e293b', marginBottom: 16 } }, '업체별 API 사용 비용'),
                clients.length === 0
                    ? React.createElement('div', { style: { textAlign: 'center', padding: '40px 0', color: '#94a3b8', fontSize: 13 } }, '아직 업체별 사용 데이터가 없습니다.')
                    : React.createElement('div', { style: { overflowX: 'auto' } },
                        React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse', fontSize: 13 } },
                            React.createElement('thead', null,
                                React.createElement('tr', { style: { borderBottom: '2px solid #e2e8f0' } },
                                    ['업체명', '키워드 수', '분석 횟수', '이번 달 비용', '비중'].map(function(h) {
                                        return React.createElement('th', {
                                            key: h,
                                            style: { padding: '10px 12px', textAlign: h === '업체명' ? 'left' : 'center', color: '#64748b', fontWeight: 600, fontSize: 12 }
                                        }, h);
                                    })
                                )
                            ),
                            React.createElement('tbody', null,
                                clients.map(function(c, i) {
                                    var pct = Math.round(c.cost_krw / totalClientCost * 100);
                                    return React.createElement('tr', { key: i, style: { borderBottom: '1px solid #f1f5f9', background: i % 2 === 0 ? '#fafbfc' : '#fff' } },
                                        React.createElement('td', { style: { padding: 12, fontWeight: 600, color: '#1e293b' } }, c.client_name),
                                        React.createElement('td', { style: { padding: 12, textAlign: 'center', color: '#64748b' } }, c.keyword_count + '개'),
                                        React.createElement('td', { style: { padding: 12, textAlign: 'center', color: '#64748b' } }, c.calls + '회'),
                                        React.createElement('td', { style: { padding: 12, textAlign: 'center', fontWeight: 700, color: '#4f46e5' } }, fmt(c.cost_krw) + '원'),
                                        React.createElement('td', { style: { padding: 12, textAlign: 'center' } },
                                            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center' } },
                                                React.createElement('div', { style: { width: 60, height: 6, background: '#e2e8f0', borderRadius: 3, overflow: 'hidden' } },
                                                    React.createElement('div', { style: { width: pct + '%', height: '100%', background: '#6366f1', borderRadius: 3 } })
                                                ),
                                                React.createElement('span', { style: { fontSize: 11, color: '#64748b', minWidth: 30 } }, pct + '%')
                                            )
                                        )
                                    );
                                }),
                                /* 합계 행 */
                                React.createElement('tr', { style: { borderTop: '2px solid #e2e8f0', background: '#f8fafc' } },
                                    React.createElement('td', { style: { padding: 12, fontWeight: 700, color: '#1e293b' } }, '합계'),
                                    React.createElement('td', { style: { padding: 12, textAlign: 'center', fontWeight: 600, color: '#64748b' } },
                                        clients.reduce(function(s, c) { return s + c.keyword_count; }, 0) + '개'),
                                    React.createElement('td', { style: { padding: 12, textAlign: 'center', fontWeight: 600, color: '#64748b' } },
                                        clients.reduce(function(s, c) { return s + c.calls; }, 0) + '회'),
                                    React.createElement('td', { style: { padding: 12, textAlign: 'center', fontWeight: 700, color: '#4f46e5', fontSize: 14 } },
                                        fmt(totalClientCost) + '원'),
                                    React.createElement('td', { style: { padding: 12, textAlign: 'center', fontWeight: 600, color: '#64748b', fontSize: 11 } }, '100%')
                                )
                            )
                        )
                    ),
                React.createElement('div', {
                    style: { marginTop: 16, padding: '12px 16px', background: '#fffbeb', borderRadius: 8, border: '1px solid #fde68a', fontSize: 12, color: '#92400e' }
                }, '자동 분석 (매일 07:00)과 수동 분석 비용이 합산됩니다. 키워드가 많은 업체일수록 비용이 높아집니다.')
            ),

            /* ========== 호출 로그 탭 ========== */
            tab === 'logs' && React.createElement('div', { className: 'card' },
                React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } },
                    React.createElement('div', { style: { fontWeight: 600, fontSize: 15, color: '#1e293b' } }, '최근 API 호출 내역'),
                    React.createElement('div', {
                        style: { padding: '4px 12px', background: '#f0f9ff', borderRadius: 6, fontSize: 12, color: '#0369a1', fontWeight: 500 }
                    }, '오늘 ' + (today.calls || 0) + '건')
                ),
                logs.length === 0
                    ? React.createElement('div', { style: { textAlign: 'center', padding: '40px 0', color: '#94a3b8', fontSize: 13 } }, '아직 호출 내역이 없습니다.')
                    : React.createElement('div', { style: { overflowX: 'auto' } },
                        React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse', fontSize: 12, minWidth: 700 } },
                            React.createElement('thead', null,
                                React.createElement('tr', { style: { borderBottom: '2px solid #e2e8f0' } },
                                    ['#', '시간', '키워드', '업체', '유형', '입력', '출력', '비용', '상태'].map(function(h) {
                                        return React.createElement('th', {
                                            key: h,
                                            style: { padding: '8px 10px', textAlign: (h === '키워드' || h === '업체') ? 'left' : 'center', color: '#64748b', fontWeight: 600, fontSize: 11, whiteSpace: 'nowrap' }
                                        }, h);
                                    })
                                )
                            ),
                            React.createElement('tbody', null,
                                logs.map(function(log, i) {
                                    var timeStr = log.called_at ? log.called_at.slice(11, 16) : '';
                                    var typeLabel = log.call_type === 'auto' ? '자동 분석' : '수동 분석';
                                    return React.createElement('tr', {
                                        key: i,
                                        style: { borderBottom: '1px solid #f1f5f9', background: log.status === 'error' ? '#fef2f2' : (i % 2 === 0 ? '#fafbfc' : '#fff') }
                                    },
                                        React.createElement('td', { style: { padding: '8px 10px', textAlign: 'center', color: '#94a3b8', fontSize: 11 } }, log.id),
                                        React.createElement('td', { style: { padding: '8px 10px', textAlign: 'center', fontFamily: 'monospace', color: '#475569' } }, timeStr),
                                        React.createElement('td', { style: { padding: '8px 10px', fontWeight: 500, color: '#1e293b' } }, log.keyword || '-'),
                                        React.createElement('td', { style: { padding: '8px 10px', color: log.client_name ? '#64748b' : '#cbd5e1' } }, log.client_name || '키워드 분석'),
                                        React.createElement('td', { style: { padding: '8px 10px', textAlign: 'center' } },
                                            React.createElement('span', {
                                                style: {
                                                    padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 500,
                                                    background: log.call_type === 'auto' ? '#dbeafe' : '#f0fdf4',
                                                    color: log.call_type === 'auto' ? '#1d4ed8' : '#15803d',
                                                }
                                            }, typeLabel)
                                        ),
                                        React.createElement('td', { style: { padding: '8px 10px', textAlign: 'center', color: '#64748b', fontFamily: 'monospace', fontSize: 11 } }, fmt(log.input_tokens)),
                                        React.createElement('td', { style: { padding: '8px 10px', textAlign: 'center', color: '#64748b', fontFamily: 'monospace', fontSize: 11 } }, fmt(log.output_tokens)),
                                        React.createElement('td', { style: { padding: '8px 10px', textAlign: 'center', fontWeight: 600, color: '#4f46e5', fontSize: 12 } }, log.cost_krw + '원'),
                                        React.createElement('td', { style: { padding: '8px 10px', textAlign: 'center' } },
                                            React.createElement('span', {
                                                style: { display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: log.status === 'success' ? '#22c55e' : '#ef4444' }
                                            })
                                        )
                                    );
                                })
                            )
                        )
                    )
            )
        )
    );
};
