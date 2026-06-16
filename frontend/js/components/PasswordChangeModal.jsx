/* PasswordChangeModal — 비밀번호 변경 모달 (App.jsx에서 분리)
 * props: { show: bool, onClose: fn }
 * 자체 상태(현재/새/확인/메시지/로딩)를 관리하고, 열릴 때마다 입력을 초기화한다.
 */
var _pwInputStyle = { width:'100%', padding:'10px', border:'1px solid #D8B4FE', borderRadius:6, boxSizing:'border-box', fontSize:14 };
var _pwLabelStyle = { display:'block', fontSize:12, fontWeight:'bold', color:'#6B21A8', marginBottom:4 };
var _pwModalOverlay = { position:'fixed', top:0, left:0, right:0, bottom:0, background:'rgba(0,0,0,0.5)', display:'flex', justifyContent:'center', alignItems:'center', zIndex:2000 };
var _pwModalBox = { background:'#fff', padding:28, borderRadius:12, width:'90%', maxWidth:380, boxShadow:'0 10px 25px rgba(0,0,0,0.2)' };
var _pwCancelBtn = { background:'#E9D5FF', color:'#6B21A8', border:'none', padding:'10px 20px', borderRadius:6, cursor:'pointer', fontWeight:'bold' };
var _pwSubmitBtn = { background:'#8B5CF6', color:'#fff', border:'none', padding:'10px 20px', borderRadius:6, cursor:'pointer', fontWeight:'bold' };

window.PasswordChangeModal = function PasswordChangeModal(props) {
    var show = props.show;
    var onClose = props.onClose || function(){};
    const { useState, useEffect } = React;

    var _cur = useState(''); var pwCurrent = _cur[0]; var setPwCurrent = _cur[1];
    var _new = useState(''); var pwNew = _new[0]; var setPwNew = _new[1];
    var _conf = useState(''); var pwConfirm = _conf[0]; var setPwConfirm = _conf[1];
    var _msg = useState(''); var pwMsg = _msg[0]; var setPwMsg = _msg[1];
    var _load = useState(false); var pwLoading = _load[0]; var setPwLoading = _load[1];

    // 열릴 때마다 입력 초기화
    useEffect(function() {
        if (show) { setPwCurrent(''); setPwNew(''); setPwConfirm(''); setPwMsg(''); setPwLoading(false); }
    }, [show]);

    if (!show) return null;

    var handleChangePassword = function() {
        if (!pwCurrent || !pwNew) { setPwMsg('현재 비밀번호와 새 비밀번호를 입력하세요.'); return; }
        if (pwNew.length < 6) { setPwMsg('새 비밀번호는 6자 이상이어야 합니다.'); return; }
        if (pwNew !== pwConfirm) { setPwMsg('새 비밀번호가 일치하지 않습니다.'); return; }
        setPwLoading(true); setPwMsg('');
        api.put('/auth/change-password', { current_password: pwCurrent, new_password: pwNew })
        .then(function(res) {
            setPwLoading(false);
            if (res && res.success) {
                setPwMsg('비밀번호가 변경되었습니다!');
                setTimeout(function() { onClose(); }, 1500);
            } else {
                setPwMsg(res.detail || res.message || '비밀번호 변경 실패');
            }
        }).catch(function(e) { setPwLoading(false); setPwMsg(e.message || '네트워크 오류'); });
    };

    return React.createElement('div', { style: _pwModalOverlay, onClick: function(e) { if (e.target === e.currentTarget) onClose(); } },
        React.createElement('div', { className: 'pw-modal-inner', style: _pwModalBox },
            React.createElement('h3', { style: { color:'#6B21A8', marginBottom:16, fontSize:18 } }, '🔒 비밀번호 변경'),
            pwMsg && React.createElement('div', { style: { padding:'8px 12px', borderRadius:6, marginBottom:12, fontSize:13, background: pwMsg.includes('변경되었습니다') ? '#D1FAE5' : '#FEE2E2', color: pwMsg.includes('변경되었습니다') ? '#065F46' : '#991B1B' } }, pwMsg),
            React.createElement('div', { style: { marginBottom:12 } },
                React.createElement('label', { style: _pwLabelStyle }, '현재 비밀번호'),
                React.createElement('input', { type:'password', value:pwCurrent, onChange: function(e){setPwCurrent(e.target.value);}, style: _pwInputStyle, placeholder:'현재 비밀번호 입력' })
            ),
            React.createElement('div', { style: { marginBottom:12 } },
                React.createElement('label', { style: _pwLabelStyle }, '새 비밀번호'),
                React.createElement('input', { type:'password', value:pwNew, onChange: function(e){setPwNew(e.target.value);}, style: _pwInputStyle, placeholder:'6자 이상' })
            ),
            React.createElement('div', { style: { marginBottom:16 } },
                React.createElement('label', { style: _pwLabelStyle }, '새 비밀번호 확인'),
                React.createElement('input', { type:'password', value:pwConfirm, onChange: function(e){setPwConfirm(e.target.value);}, style: _pwInputStyle, placeholder:'새 비밀번호 재입력' })
            ),
            React.createElement('div', { style: { display:'flex', gap:8, justifyContent:'flex-end' } },
                React.createElement('button', { onClick: function(){ onClose(); }, style: _pwCancelBtn }, '취소'),
                React.createElement('button', { onClick: handleChangePassword, disabled: pwLoading, style: Object.assign({}, _pwSubmitBtn, { opacity: pwLoading ? 0.6 : 1 }) }, pwLoading ? '변경 중...' : '변경')
            )
        )
    );
};
