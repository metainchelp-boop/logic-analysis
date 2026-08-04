/* TopBar — 상단 카테고리 바 (App.jsx에서 분리)
 * props: { activePage, currentUser, health, onNavigate(page) }
 */
var _navBtnBase = { padding: '7px 16px', borderRadius: 8, cursor: 'pointer', fontSize: 13, transition: 'all 0.2s' };
var _navBtnActive = Object.assign({}, _navBtnBase, { background: '#3b82f6', color: '#fff', border: '1px solid #3b82f6', fontWeight: 700 });
var _navBtnInactive = Object.assign({}, _navBtnBase, { background: '#ffffff', color: '#475569', border: '1px solid #f0d2d2', fontWeight: 500 });
var _navUserStyle = { color: '#475569', fontSize: 13, fontWeight: 600 };
var _topbarContainer = { display:'flex', alignItems:'center', justifyContent:'flex-start', flexWrap:'wrap', minHeight: 48, padding:'8px 24px', gap:10 };
var _versionBadge = { fontSize:11, color:'#94a3b8', background:'#f1f5f9', padding:'2px 8px', borderRadius:10, fontWeight:400 };
var _healthBadge = { background:'#dcfce7', color:'#16a34a', fontSize:11, padding:'2px 8px', borderRadius:10, fontWeight:600 };

function _navBtn(active) { return active ? _navBtnActive : _navBtnInactive; }

window.TopBar = function TopBar(props) {
    var activePage = props.activePage;
    var currentUser = props.currentUser || {};
    var health = props.health;
    var go = props.onNavigate || function(){};

    return React.createElement('div', { className: 'topbar' },
        React.createElement('div', { className: 'container', style: _topbarContainer },
            React.createElement('div', { className: 'logo', style: { cursor:'pointer', display:'flex', alignItems:'center', gap:8 }, onClick: function() { go('home'); } },
                React.createElement('img', { src: '/img/logo_light.png', alt: 'META INC', style: { height:28, width:'auto', display:'block' } }),
                React.createElement('span', { style: _versionBadge }, APP_VERSION),
                (activePage === 'analysis' || activePage === 'home') && health && React.createElement('span', { style: _healthBadge }, '● 정상')
            ),
            React.createElement('div', { className: 'topbar-nav-btns', style: { display:'flex', alignItems:'center', gap:16, flexWrap:'wrap', marginLeft:8 } },
                React.createElement('button', { onClick: function(){ go('home'); }, style: _navBtn(activePage === 'home') }, '🏠 대시보드'),
                // 🔍 SEO 최적화 — 광고 관리팀(manager) + 최고관리자(superadmin) 전용 (타 세션 의도 위치: 대시보드 다음)
                (currentUser.role === 'manager' || currentUser.role === 'superadmin') && React.createElement('button', { onClick: function(){ go('seo'); }, style: _navBtn(activePage === 'seo') }, '🔍 SEO 최적화'),
                React.createElement('button', { onClick: function(){ go('place'); }, style: _navBtn(activePage === 'place') }, '📍 플레이스 분석'),
                React.createElement('button', { onClick: function(){ go('placetrack'); }, style: _navBtn(activePage === 'placetrack') }, '📊 플레이스 추적'),
                React.createElement('button', { onClick: function(){ go('analysis'); }, style: _navBtn(activePage === 'analysis') }, '🛒 스토어 분석'),
                React.createElement('button', { onClick: function(){ go('rank'); }, style: _navBtn(activePage === 'rank') }, '📊 키워드 순위'),
                React.createElement('button', { onClick: function(){ go('management'); }, style: _navBtn(activePage === 'management') }, '📈 로직 분석'),
                React.createElement('button', { onClick: function(){ go('learning'); }, style: _navBtn(activePage === 'learning') }, '🎓 학습센터'),
                React.createElement('button', { onClick: function(){ go('guide'); }, style: _navBtn(activePage === 'guide') }, '📖 설명서'),
                // 👥 직원 탭 제거 — SSO(ERP 연동)로 계정 자동 관리, 로그인 이력/실행 건수는 ⚙️설정 탭으로 통합
                currentUser.role === 'superadmin' && React.createElement('button', { onClick: function(){ go('settings'); }, style: _navBtn(activePage === 'settings') }, '⚙️ 설정')
            ),
            React.createElement('div', { className: 'topbar-user-area', style: { display:'flex', alignItems:'center', gap:8, marginLeft:'auto' } },
                React.createElement('span', { style: _navUserStyle }, currentUser.name || currentUser.username),
                (function(){
                    var _r = currentUser.role;
                    var _label = _r === 'superadmin' ? '최고관리자' : _r === 'admin' ? '관리자' : _r === 'manager' ? '매니저' : '뷰어';
                    var _isAdmin = (_r === 'admin' || _r === 'superadmin');
                    var _bg = _isAdmin ? '#ede9fe' : _r === 'manager' ? '#dbeafe' : '#f1f5f9';
                    var _fg = _isAdmin ? '#6d28d9' : _r === 'manager' ? '#1d4ed8' : '#475569';
                    return React.createElement('span', { title: '내 권한', style: { fontSize:11, fontWeight:800, padding:'2px 9px', borderRadius:999, background:_bg, color:_fg, whiteSpace:'nowrap' } }, _label);
                })()
            )
        )
    );
};
