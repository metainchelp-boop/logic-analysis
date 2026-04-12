/* NotificationSection — 알림 설정 */
window.NotificationSection = function NotificationSection() {
    const { useState, useEffect } = React;
    const [settings, setSettings] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        api.get('/notify/settings').then(res => {
            if (res.success) setSettings(res.data);
            setLoading(false);
        }).catch(() => setLoading(false));
    }, []);

    const toggleNotify = async (enabled) => {
        const res = await api.put('/notify/settings', { notify_enabled: enabled });
        if (res.success) setSettings(res.data);
    };

    if (loading) return null;
    if (!settings) return null;

    return (
        <div className="section" id="sec-notify">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: '#fffbeb' }}>🔔</span>
                    알림 설정
                </div>
                <div className="card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                            <div style={{ fontWeight: 600, fontSize: 14 }}>일일 리포트 알림</div>
                            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                                {settings.report_time || '09:00'}에 순위 변동 리포트를 발송합니다
                            </div>
                        </div>
                        <label className="toggle">
                            <input type="checkbox" checked={settings.notify_enabled || false} onChange={e => toggleNotify(e.target.checked)} />
                            <span className="toggle-track" />
                        </label>
                    </div>
                    {!settings.solapi_configured && (
                        <div className="alert alert-info" style={{ marginTop: 12, marginBottom: 0 }}>
                            솔라피 API가 설정되지 않았습니다. 알림을 사용하려면 환경변수를 설정하세요.
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
