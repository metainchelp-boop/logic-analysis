/* ClientDiagnosticsSection — 업체 데이터 점검 (admin/superadmin 전용, 조회 전용) v1.0
 * '진행중(active) 업체 일부 사라짐' 원인 파악용 패널.
 *  - 상태별 업체 수
 *  - 등록자(created_by) 없는 active 업체 (manager에게 안 보여 사라짐처럼 보일 수 있음)
 *  - 최근 paused/terminated로 바뀐 업체 (의도치 않은 상태 변경 의심)
 */
var _cdStatusLabels = { active: '진행중(active)', paused: '일시중지(paused)', terminated: '종료(terminated)' };
var _cdStatusColors = {
    active: { bg: '#dcfce7', color: '#16a34a' },
    paused: { bg: '#fef9c3', color: '#ca8a04' },
    terminated: { bg: '#fee2e2', color: '#dc2626' }
};

window.ClientDiagnosticsSection = function ClientDiagnosticsSection() {
    const { useState, useEffect, useCallback } = React;

    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);

    var load = useCallback(function() {
        setLoading(true);
        api.get('/clients/diagnostics').then(function(res) {
            if (res.success) setData(res.data);
            setLoading(false);
        }).catch(function() { setLoading(false); });
    }, []);

    useEffect(function() { load(); }, [load]);

    var renderTable = function(rows, cols) {
        return React.createElement('div', { style: { overflowX: 'auto' } },
            React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse', fontSize: 12 } },
                React.createElement('thead', null,
                    React.createElement('tr', null,
                        cols.map(function(c) {
                            return React.createElement('th', {
                                key: c.key,
                                style: { textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid #e2e8f0', color: '#64748b', fontWeight: 600, whiteSpace: 'nowrap' }
                            }, c.label);
                        })
                    )
                ),
                React.createElement('tbody', null,
                    rows.map(function(row, i) {
                        return React.createElement('tr', { key: i },
                            cols.map(function(c) {
                                return React.createElement('td', {
                                    key: c.key,
                                    style: { padding: '6px 8px', borderBottom: '1px solid #f1f5f9', color: '#1e293b', whiteSpace: 'nowrap' }
                                }, c.render ? c.render(row[c.key], row) : (row[c.key] == null ? '-' : String(row[c.key])));
                            })
                        );
                    })
                )
            )
        );
    };

    var byStatus = (data && data.byStatus) || {};
    var recentInactive = (data && data.recentInactive) || [];

    return React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 20 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 } },
            React.createElement('div', { style: { fontSize: 18, fontWeight: 700 } }, '🔎 업체 데이터 점검'),
            React.createElement('div', { style: { flex: 1 } }),
            React.createElement('button', {
                onClick: load,
                style: { padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer', background: '#f1f5f9', color: '#334155', border: '1px solid #e2e8f0' }
            }, '↻ 새로고침')
        ),

        React.createElement('div', { style: { fontSize: 12, color: '#64748b', marginBottom: 16, lineHeight: 1.6 } },
            "업체 데이터 점검용입니다. 상태별 업체 수와 최근 일시중지/종료된 업체를 확인할 수 있습니다."
        ),

        loading && React.createElement('div', { style: { textAlign: 'center', padding: 20, color: '#94a3b8' } }, '불러오는 중...'),

        !loading && data && React.createElement(React.Fragment, null,
            /* 서버 디스크 사용량 */
            data.disk && (function() {
                var dk = data.disk;
                var pct = dk.usedPercent || 0;
                var color = pct >= 90 ? { bg: '#fee2e2', bar: '#dc2626', text: '#dc2626' }
                    : pct >= 75 ? { bg: '#fef9c3', bar: '#ca8a04', text: '#ca8a04' }
                    : { bg: '#dcfce7', bar: '#16a34a', text: '#16a34a' };
                return React.createElement('div', { style: { marginBottom: 20 } },
                    React.createElement('div', { style: { fontSize: 13, fontWeight: 700, color: '#334155', margin: '4px 0 8px', display: 'flex', alignItems: 'center', gap: 8 } },
                        '💾 서버 디스크 사용량',
                        React.createElement('span', { style: { fontSize: 12, fontWeight: 700, color: color.text } }, pct + '%'),
                        pct >= 90 && React.createElement('span', { style: { fontSize: 11, color: '#dc2626', fontWeight: 600 } }, '⚠️ 정리 필요')
                    ),
                    /* 사용률 막대 */
                    React.createElement('div', { style: { height: 14, borderRadius: 7, background: '#e2e8f0', overflow: 'hidden', marginBottom: 8 } },
                        React.createElement('div', { style: { width: Math.min(pct, 100) + '%', height: '100%', background: color.bar, transition: 'width 0.3s' } })
                    ),
                    React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 12, color: '#475569' } },
                        React.createElement('span', null, '전체 ' + dk.totalGB + 'GB'),
                        React.createElement('span', null, '사용 ' + dk.usedGB + 'GB'),
                        React.createElement('span', { style: { fontWeight: 600 } }, '여유 ' + dk.freeGB + 'GB'),
                        React.createElement('span', { style: { color: '#94a3b8' } }, '| DB ' + dk.dbSizeGB + 'GB · 백업 ' + dk.backupCount + '개(' + dk.backupTotalGB + 'GB)')
                    )
                );
            })(),

            /* 상태별 업체 수 */
            React.createElement('div', { style: { fontSize: 13, fontWeight: 700, color: '#334155', margin: '4px 0 8px' } }, '상태별 업체 수'),
            React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 } },
                ['active', 'paused', 'terminated'].map(function(st) {
                    var cc = _cdStatusColors[st];
                    return React.createElement('div', { key: st, style: { flex: 1, minWidth: 120, background: cc.bg, borderRadius: 10, padding: 12, textAlign: 'center' } },
                        React.createElement('div', { style: { fontSize: 11, color: cc.color } }, _cdStatusLabels[st]),
                        React.createElement('div', { style: { fontSize: 22, fontWeight: 700, color: cc.color } }, byStatus[st] || 0)
                    );
                })
            ),

            /* (등록자 없는 진행중 업체 항목 제거 — clients.created_by가 NOT NULL이라 항상 0건이라 무의미) */

            /* 최근 paused/terminated */
            React.createElement('div', { style: { fontSize: 13, fontWeight: 700, color: '#334155', margin: '4px 0 8px' } }, '최근 일시중지/종료된 업체 (최대 30건)'),
            recentInactive.length === 0
                ? React.createElement('div', { style: { fontSize: 12, color: '#94a3b8' } }, '없음.')
                : renderTable(recentInactive, [
                    { key: 'id', label: 'ID' },
                    { key: 'name', label: '업체명' },
                    { key: 'status', label: '상태', render: function(v) { return _cdStatusLabels[v] || v; } },
                    { key: 'updated_at', label: '변경일', render: function(v) { return (v || '').slice(0, 16); } }
                ])
        )
    );
};
