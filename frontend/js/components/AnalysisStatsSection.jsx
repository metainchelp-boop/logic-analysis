/* AnalysisStatsSection — 로직 분석 실행 건수 통계 (설정 탭, 최고관리자 전용) v1.0
 *  - 요약 카드: 총 실행 / 이번 달 / 오늘
 *  - 직원별 표: 이름·역할 + 오늘/이번 달/누적 실행 건수
 *  데이터: daily_usage.query_count (분석 실행마다 +1, 모든 역할 카운트)
 */
var _asRoleLabels = { superadmin: '최고관리자', admin: '관리자', manager: '매니저', viewer: '뷰어' };
var _asRoleColors = {
    superadmin: { bg: '#ede9fe', color: '#6d28d9' },
    admin: { bg: '#dbeafe', color: '#2563eb' },
    manager: { bg: '#dcfce7', color: '#16a34a' },
    viewer: { bg: '#f1f5f9', color: '#64748b' }
};

window.AnalysisStatsSection = function AnalysisStatsSection() {
    const { useState, useEffect, useCallback } = React;
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);

    var load = useCallback(function() {
        setLoading(true);
        api.get('/auth/analysis-stats').then(function(res) {
            if (res && res.success) setData(res);
            setLoading(false);
        }).catch(function() { setLoading(false); });
    }, []);

    useEffect(function() { load(); }, [load]);

    var card = function(label, value, color, bg) {
        return React.createElement('div', {
            key: label,
            style: { flex: 1, minWidth: 140, padding: '16px 18px', background: bg, borderRadius: 12, border: '1px solid ' + color + '22' }
        },
            React.createElement('div', { style: { fontSize: 28, fontWeight: 800, color: color, lineHeight: 1.1 } }, fmt(value)),
            React.createElement('div', { style: { fontSize: 12, color: '#64748b', marginTop: 4, fontWeight: 600 } }, label)
        );
    };

    var th = function(label, align) {
        return React.createElement('th', {
            key: label,
            style: { textAlign: align || 'left', padding: '8px 10px', borderBottom: '2px solid #e2e8f0', color: '#64748b', fontWeight: 700, whiteSpace: 'nowrap', fontSize: 12 }
        }, label);
    };

    var numCell = function(v, strong) {
        return React.createElement('td', {
            style: { textAlign: 'right', padding: '8px 10px', borderBottom: '1px solid #f1f5f9', fontWeight: strong ? 700 : 500, color: v > 0 ? '#0f172a' : '#cbd5e1', fontVariantNumeric: 'tabular-nums' }
        }, fmt(v) + '건');
    };

    return React.createElement('div', { style: { background: '#fff', borderRadius: 16, padding: '22px 24px', boxShadow: '0 1px 3px rgba(0,0,0,0.06)', marginBottom: 20 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 } },
            React.createElement('div', null,
                React.createElement('h3', { style: { margin: 0, fontSize: 16, fontWeight: 800, color: '#0f172a' } }, '📊 로직 분석 실행 건수'),
                React.createElement('div', { style: { fontSize: 12, color: '#94a3b8', marginTop: 2 } }, '분석 실행마다 집계 (모든 직원 포함)')
            ),
            React.createElement('button', {
                onClick: load, disabled: loading,
                style: { border: '1px solid #e2e8f0', background: '#f8fafc', color: '#475569', fontSize: 12, fontWeight: 600, padding: '6px 12px', borderRadius: 8, cursor: loading ? 'default' : 'pointer' }
            }, loading ? '불러오는 중…' : '↻ 새로고침')
        ),

        (!data && loading) && React.createElement('div', { style: { padding: 24, textAlign: 'center', color: '#94a3b8', fontSize: 13 } }, '불러오는 중…'),
        (!data && !loading) && React.createElement('div', { style: { padding: 24, textAlign: 'center', color: '#94a3b8', fontSize: 13 } }, '데이터를 불러오지 못했습니다.'),

        data && React.createElement(React.Fragment, null,
            // 요약 카드
            React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 } },
                card('총 누적 실행', data.total, '#6d28d9', '#f5f3ff'),
                card('이번 달', data.this_month, '#2563eb', '#eff6ff'),
                card('오늘', data.today, '#16a34a', '#f0fdf4')
            ),
            // 직원별 표
            React.createElement('div', { style: { fontSize: 13, fontWeight: 700, color: '#334155', marginBottom: 8 } }, '직원별 실행 건수'),
            React.createElement('div', { style: { overflowX: 'auto' } },
                React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse', fontSize: 13 } },
                    React.createElement('thead', null,
                        React.createElement('tr', null,
                            th('직원'), th('권한'), th('오늘', 'right'), th('이번 달', 'right'), th('누적', 'right')
                        )
                    ),
                    React.createElement('tbody', null,
                        (data.per_user || []).map(function(u) {
                            var rc = _asRoleColors[u.role] || _asRoleColors.viewer;
                            return React.createElement('tr', { key: u.user_id },
                                React.createElement('td', { style: { padding: '8px 10px', borderBottom: '1px solid #f1f5f9', fontWeight: 600, color: '#0f172a' } }, u.name),
                                React.createElement('td', { style: { padding: '8px 10px', borderBottom: '1px solid #f1f5f9' } },
                                    React.createElement('span', { style: { fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 10, background: rc.bg, color: rc.color } }, _asRoleLabels[u.role] || u.role)
                                ),
                                numCell(u.today),
                                numCell(u.month),
                                numCell(u.total, true)
                            );
                        }),
                        (!data.per_user || data.per_user.length === 0) && React.createElement('tr', null,
                            React.createElement('td', { colSpan: 5, style: { padding: 18, textAlign: 'center', color: '#94a3b8' } }, '실행 기록이 없습니다.')
                        )
                    )
                )
            )
        )
    );
};
