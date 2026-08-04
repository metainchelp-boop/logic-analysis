/* AppShellBar — B+A 대개편 셸 (2026-08-05, 대표 확정)
 *
 * 상단 TopBar 를 대체하는 「좌측 사이드바 + 상단 바」. TopBar 와 동일한 props
 * 계약({ activePage, currentUser, health, onNavigate })이라 페이지 블록들은
 * 마운트 치환만으로 이전된다(라우팅·권한 게이트 불변).
 *  - 사이드바: 쇼핑/플레이스/통합 그룹 · 상승 키워드 뱃지(rank-overview totals)
 *    · 접기(수동 토글 localStorage + 좁은 화면 자동) — position:fixed,
 *    본문은 body padding 으로 밀어낸다(페이지 내부 레이아웃 무수정).
 *  - 상단 바: 크럼 · 전역 검색(Ctrl+K, Enter → 대시보드 검색 핸드오프) · 사용자.
 *  - 첫 진입 1회 안내(「메뉴가 왼쪽으로 이동했어요」, localStorage).
 */

var _AS_W = 206, _AS_WC = 60, _AS_TOP = 50;
var _AS_GROUPS = function(cu) {
    var role = (cu && cu.role) || '';
    return [
        { label: null, items: [ { page: 'home', icon: '🏠', name: '대시보드' } ] },
        { label: '쇼핑', items: [
            (role === 'manager' || role === 'superadmin') && { page: 'seo', icon: '🔍', name: 'SEO 최적화' },
            { page: 'analysis', icon: '🛒', name: '스토어 분석' },
            { page: 'rank', icon: '📊', name: '키워드 순위', badge: 'up' }
        ].filter(Boolean) },
        { label: '플레이스', items: [
            { page: 'place', icon: '📍', name: '플레이스 분석' },
            { page: 'placetrack', icon: '📊', name: '플레이스 추적' }
        ] },
        { label: '통합', items: [
            { page: 'management', icon: '📈', name: '로직 분석 (업체)' },
            { page: 'learning', icon: '🎓', name: '학습센터' },
            { page: 'guide', icon: '📖', name: '설명서' }
        ] },
        role === 'superadmin' ? { label: '관리', items: [ { page: 'settings', icon: '⚙️', name: '설정' } ] } : null
    ].filter(Boolean);
};
var _AS_CRUMB = {
    home: '홈 / 대시보드', seo: '쇼핑 / SEO 최적화', analysis: '쇼핑 / 스토어 분석', rank: '쇼핑 / 키워드 순위',
    place: '플레이스 / 플레이스 분석', placetrack: '플레이스 / 플레이스 추적',
    management: '통합 / 로직 분석 (업체)', learning: '통합 / 학습센터', guide: '통합 / 설명서',
    settings: '관리 / 설정', users: '관리 / 직원'
};

window.AppShellBar = function AppShellBar(props) {
    var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
    var activePage = props.activePage;
    var currentUser = props.currentUser || {};
    var health = props.health;
    var go = props.onNavigate || function() {};

    var _c = useState(function() {
        try {
            var saved = localStorage.getItem('logic_nav_collapsed');
            if (saved != null) return saved === '1';
        } catch (e) {}
        return (typeof window !== 'undefined' && window.innerWidth < 1080);
    });
    var collapsed = _c[0], setCollapsed = _c[1];
    var _up = useState(null); var upTotal = _up[0], setUpTotal = _up[1];
    var _q = useState(''); var q = _q[0], setQ = _q[1];
    var _in = useState(function() {
        try { return !localStorage.getItem('logic_nav_intro_v7'); } catch (e) { return false; }
    });
    var showIntro = _in[0], setShowIntro = _in[1];
    var searchRef = useRef(null);

    /* 본문 밀어내기 — 페이지 내부 컨테이너 무수정으로 셸 폭 반영 */
    useEffect(function() {
        var w = collapsed ? _AS_WC : _AS_W;
        document.body.style.paddingLeft = w + 'px';
        document.body.style.paddingTop = _AS_TOP + 'px';
        return function() { document.body.style.paddingLeft = ''; document.body.style.paddingTop = ''; };
    }, [collapsed]);

    /* 좁은 화면 자동 접힘(수동 설정 없을 때만) */
    useEffect(function() {
        var onR = function() {
            try { if (localStorage.getItem('logic_nav_collapsed') != null) return; } catch (e) {}
            setCollapsed(window.innerWidth < 1080);
        };
        window.addEventListener('resize', onR);
        return function() { window.removeEventListener('resize', onR); };
    }, []);

    /* 상승 키워드 뱃지 — 실패 무해 */
    useEffect(function() {
        api.get('/cd/rank-overview').then(function(res) {
            if (res && res.success && res.totals) setUpTotal(res.totals.up_total || 0);
        }).catch(function() {});
    }, []);

    /* Ctrl+K → 검색 포커스 */
    useEffect(function() {
        var onKey = function(e) {
            if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
                e.preventDefault();
                if (searchRef.current) searchRef.current.focus();
            }
        };
        window.addEventListener('keydown', onKey);
        return function() { window.removeEventListener('keydown', onKey); };
    }, []);

    var toggle = function() {
        var next = !collapsed;
        setCollapsed(next);
        try { localStorage.setItem('logic_nav_collapsed', next ? '1' : '0'); } catch (e) {}
    };
    var submitSearch = function() {
        var v = q.trim();
        if (!v) return;
        try { sessionStorage.setItem('logic_global_q', v); } catch (e) {}
        /* 이미 대시보드에 있어도 반영되게 이벤트 병행(리스트가 리스닝) */
        try { window.dispatchEvent(new CustomEvent('logic-global-search', { detail: v })); } catch (e) {}
        setQ('');
        go('home');
    };
    var dismissIntro = function() {
        setShowIntro(false);
        try { localStorage.setItem('logic_nav_intro_v7', '1'); } catch (e) {}
    };

    var W = collapsed ? _AS_WC : _AS_W;
    var _r = currentUser.role;
    var roleLabel = _r === 'superadmin' ? '최고관리자' : _r === 'admin' ? '관리자' : _r === 'manager' ? '매니저' : '뷰어';
    var roleBg = (_r === 'admin' || _r === 'superadmin') ? '#ede9fe' : _r === 'manager' ? '#dbeafe' : '#f1f5f9';
    var roleFg = (_r === 'admin' || _r === 'superadmin') ? '#6d28d9' : _r === 'manager' ? '#1d4ed8' : '#475569';

    var navBtn = function(item) {
        var on = activePage === item.page;
        return React.createElement('button', {
            key: item.page,
            onClick: function() { go(item.page); },
            title: collapsed ? item.name : undefined,
            style: {
                display: 'flex', alignItems: 'center', gap: 9, width: '100%',
                border: 'none', background: on ? '#1d2a44' : 'none', color: on ? '#fff' : '#aeb8c8',
                fontFamily: 'inherit', fontSize: 13, fontWeight: on ? 800 : 600, textAlign: 'left',
                borderRadius: 9, padding: collapsed ? '9px 0' : '8px 11px', cursor: 'pointer',
                justifyContent: collapsed ? 'center' : 'flex-start', whiteSpace: 'nowrap'
            },
            onMouseEnter: function(e) { if (!on) { e.currentTarget.style.background = '#18202f'; e.currentTarget.style.color = '#e2e8f0'; } },
            onMouseLeave: function(e) { if (!on) { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = '#aeb8c8'; } }
        },
            React.createElement('span', { style: { fontSize: 14, flex: 'none' } }, item.icon),
            !collapsed && React.createElement('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis' } }, item.name),
            !collapsed && item.badge === 'up' && upTotal > 0 && React.createElement('span', {
                style: { marginLeft: 'auto', fontSize: 10, fontWeight: 800, background: '#324467', color: '#cfe0ff', borderRadius: 999, padding: '1px 7px' }
            }, '▲' + upTotal)
        );
    };

    return React.createElement(React.Fragment, null,
        /* ── 좌측 사이드바 ── */
        React.createElement('nav', {
            'aria-label': '주요 메뉴',
            style: { position: 'fixed', top: 0, left: 0, bottom: 0, width: W, zIndex: 1000,
                     background: '#101623', display: 'flex', flexDirection: 'column',
                     padding: collapsed ? '14px 8px 12px' : '16px 12px 14px', gap: 2, overflowY: 'auto', overflowX: 'hidden',
                     transition: 'width .15s ease' }
        },
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', padding: collapsed ? '2px 0 12px' : '4px 10px 14px', justifyContent: collapsed ? 'center' : 'flex-start' } },
                collapsed
                    ? React.createElement('span', { style: { fontWeight: 900, color: '#6ea8ff', fontSize: 14 } }, 'M')
                    : React.createElement('span', { style: { fontWeight: 900, color: '#fff', fontSize: 14.5, whiteSpace: 'nowrap' } }, 'META ',
                        React.createElement('em', { style: { color: '#6ea8ff', fontStyle: 'normal' } }, '로직분석'))
            ),
            _AS_GROUPS(currentUser).map(function(g, gi) {
                return React.createElement(React.Fragment, { key: gi },
                    g.label && !collapsed && React.createElement('div', {
                        style: { fontSize: 10, fontWeight: 800, letterSpacing: '.12em', color: '#5b6880', padding: '13px 11px 5px' }
                    }, g.label),
                    g.label && collapsed && React.createElement('div', { style: { height: 1, background: '#1c2534', margin: '9px 4px' } }),
                    g.items.map(navBtn)
                );
            }),
            React.createElement('div', { style: { marginTop: 'auto', paddingTop: 10, borderTop: '1px solid #1c2534' } },
                React.createElement('button', {
                    onClick: toggle, title: collapsed ? '메뉴 펼치기' : '메뉴 접기',
                    style: { width: '100%', border: 'none', background: 'none', color: '#5b6880', fontSize: 12, fontWeight: 700,
                             cursor: 'pointer', padding: '6px 0', fontFamily: 'inherit', textAlign: 'center' }
                }, collapsed ? '»' : '« 접기'),
                !collapsed && React.createElement('div', { style: { fontSize: 11, color: '#5b6880', padding: '4px 11px 0', whiteSpace: 'nowrap' } },
                    (typeof APP_VERSION !== 'undefined' ? APP_VERSION : ''),
                    health && React.createElement('span', { style: { color: '#4ade80', marginLeft: 6, fontWeight: 700 } }, '● 정상'))
            )
        ),

        /* ── 상단 바 ── */
        React.createElement('div', {
            style: { position: 'fixed', top: 0, left: W, right: 0, height: _AS_TOP, zIndex: 999,
                     background: '#fff', borderBottom: '1px solid #e9ecf0',
                     display: 'flex', alignItems: 'center', gap: 10, padding: '0 18px', transition: 'left .15s ease' }
        },
            React.createElement('span', { style: { fontSize: 13, fontWeight: 700, color: '#4e5968', whiteSpace: 'nowrap' } },
                _AS_CRUMB[activePage] || ''),
            showIntro && React.createElement('span', {
                style: { fontSize: 11.5, fontWeight: 700, color: '#1d4ed8', background: '#eff4ff', border: '1px solid #bfdbfe',
                         borderRadius: 999, padding: '3px 10px', whiteSpace: 'nowrap', cursor: 'pointer' },
                onClick: dismissIntro, title: '닫기'
            }, '💡 메뉴가 왼쪽으로 이동했어요 ✕'),
            React.createElement('input', {
                ref: searchRef, value: q,
                onChange: function(e) { setQ(e.target.value); },
                onKeyDown: function(e) { if (e.key === 'Enter' && !e.nativeEvent.isComposing) submitSearch(); },
                placeholder: '🔍 업체·키워드 검색 (Ctrl+K)',
                style: { marginLeft: 'auto', border: '1px solid #e5e8ec', borderRadius: 9, padding: '6px 12px',
                         fontSize: 12.5, background: '#f7f8fa', minWidth: 150, maxWidth: 260, flex: '0 1 260px', outline: 'none' }
            }),
            React.createElement('span', { style: { fontSize: 12.5, fontWeight: 700, color: '#4e5968', whiteSpace: 'nowrap' } },
                currentUser.name || currentUser.username),
            React.createElement('span', { style: { fontSize: 10.5, fontWeight: 800, color: roleFg, background: roleBg, borderRadius: 999, padding: '2px 8px', whiteSpace: 'nowrap' } },
                roleLabel)
        )
    );
};
