/* ManagerReassignSection — 담당자 재배정 / 퇴사자 업체 일괄 이관 (설정 탭, 관리자 전용) */
window.ManagerReassignSection = function ManagerReassignSection() {
    const { useState, useEffect, useCallback } = React;
    const [fromList, setFromList] = useState([]);   // 보유 업체 있는 담당자(원본)
    const [toList, setToList] = useState([]);       // 배정 가능한 담당자(대상)
    const [fromId, setFromId] = useState('');
    const [toId, setToId] = useState('');
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState('');

    const load = useCallback(function() {
        api.get('/clients/manager-counts').then(function(res) { if (res && res.success) setFromList(res.data || []); }).catch(function(){});
        api.get('/clients/assignable-managers').then(function(res) { if (res && res.success) setToList(res.data || []); }).catch(function(){});
    }, []);
    useEffect(function() { load(); }, [load]);

    var doReassign = function() {
        var f = parseInt(fromId, 10), t = parseInt(toId, 10);
        if (!f || !t) { setMsg('원본 담당자와 이관 대상을 모두 선택하세요.'); return; }
        if (f === t) { setMsg('같은 담당자로는 이관할 수 없습니다.'); return; }
        var fromName = (fromList.find(function(x){ return x.id === f; }) || {}).name || '';
        var toName = (toList.find(function(x){ return x.id === t; }) || {}).name || '';
        if (!confirm("'" + fromName + "' 담당 업체를 전부 '" + toName + "'(으)로 이관할까요?")) return;
        setBusy(true); setMsg('');
        api.post('/clients/reassign-bulk', { from_user_id: f, to_user_id: t }).then(function(res) {
            setBusy(false);
            if (res && res.success) {
                setMsg('✅ ' + res.moved + '개 업체를 ' + (res.to_name || toName) + '(으)로 이관했습니다.');
                setFromId(''); setToId('');
                load();
            } else {
                setMsg('이관 실패: ' + ((res && res.detail) || '오류'));
            }
        }).catch(function(e) { setBusy(false); setMsg('이관 실패: ' + (e.message || '네트워크 오류')); });
    };

    var selStyle = { fontSize: 13, padding: '8px 10px', borderRadius: 8, border: '1px solid #e2e8f0', minWidth: 220, background: '#fff' };

    return React.createElement('div', { style: { background: '#fff', borderRadius: 16, padding: '22px 24px', boxShadow: '0 1px 3px rgba(0,0,0,0.06)', marginBottom: 20 } },
        React.createElement('div', { style: { fontSize: 16, fontWeight: 800, color: '#0f172a', marginBottom: 4 } }, '👥 담당자 재배정 · 퇴사자 업체 이관'),
        React.createElement('div', { style: { fontSize: 12, color: '#94a3b8', marginBottom: 16 } }, '원본 담당자의 모든 진행중 업체를 다른 담당자에게 한 번에 이관합니다. (퇴사·비활성 계정도 원본으로 선택 가능)'),
        React.createElement('div', { style: { display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' } },
            React.createElement('select', { value: fromId, onChange: function(e){ setFromId(e.target.value); }, style: selStyle },
                React.createElement('option', { value: '' }, '원본 담당자 선택...'),
                fromList.map(function(m) {
                    return React.createElement('option', { key: m.id, value: m.id },
                        m.name + ' (' + m.count + '개)' + (m.is_active ? '' : ' · 퇴사'));
                })
            ),
            React.createElement('span', { style: { color: '#94a3b8', fontWeight: 700 } }, '→'),
            React.createElement('select', { value: toId, onChange: function(e){ setToId(e.target.value); }, style: selStyle },
                React.createElement('option', { value: '' }, '이관 대상 선택...'),
                toList.map(function(m) {
                    return React.createElement('option', { key: m.id, value: m.id }, m.name + (m.role !== 'manager' ? ' (' + m.role + ')' : ''));
                })
            ),
            React.createElement('button', { onClick: doReassign, disabled: busy,
                style: { fontSize: 13, fontWeight: 700, padding: '8px 18px', borderRadius: 8, cursor: busy ? 'default' : 'pointer', border: 'none', background: '#4f46e5', color: '#fff', opacity: busy ? 0.6 : 1 } },
                busy ? '이관 중…' : '이관 실행')
        ),
        msg && React.createElement('div', { style: { marginTop: 14, fontSize: 13, fontWeight: 600, color: msg.indexOf('✅') === 0 ? '#16a34a' : '#dc2626' } }, msg)
    );
};
