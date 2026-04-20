/* TopBar — 상단 헤더 (보라색 그라디언트) */
window.TopBar = function TopBar({ health }) {
    return (
        <header className="top-bar">
            <div className="container top-bar-inner">
                <div className="logo" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <img src="/img/logo_dark.png" alt="META INC" style={{ height: 28, width: 'auto' }} />
                    <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', fontWeight: 400 }}>v3.9</span>
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
