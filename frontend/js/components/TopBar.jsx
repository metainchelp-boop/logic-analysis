/* TopBar — 상단 헤더 */
window.TopBar = function TopBar({ health }) {
    return (
        <header className="top-bar">
            <div className="container top-bar-inner">
                <div className="logo">
                    <span className="logo-dot" />
                    로직 분석
                    <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400, marginLeft: 2 }}>v2.1</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span className={`status-chip ${health ? '' : 'offline'}`}>
                        {health ? '● 정상 운영' : '○ 연결 확인 중'}
                    </span>
                </div>
            </div>
        </header>
    );
};
