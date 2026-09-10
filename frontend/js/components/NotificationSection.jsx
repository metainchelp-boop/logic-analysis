/* NotificationSection — 알림 설정 */
window.NotificationSection = function NotificationSection() {
    const { useState, useEffect } = React;
    const [settings, setSettings] = useState(null);
    const [loading, setLoading] = useState(true);
    /* 수신 번호는 입력 중에 서버 값으로 덮이면 안 된다 — 따로 들고 있다가 저장할 때만 보낸다. */
    const [phone, setPhone] = useState('');
    const [phoneSaved, setPhoneSaved] = useState(false);
    /* ⚠️ 실패를 말하지 않으면 사람은 「눌렀는데 아무 일도 안 난다」로 겪는다.
       2026-09-10 에 서버가 500 을 돌려주는데 화면이 조용해서, 왜 안 되는지 알 수 없었다. */
    const [phoneErr, setPhoneErr] = useState('');

    useEffect(() => {
        api.get('/notify/settings').then(res => {
            if (res.success) { setSettings(res.data); setPhone(res.data.receiver_phone || ''); }
            setLoading(false);
        }).catch(() => setLoading(false));
    }, []);

    const toggleNotify = async (enabled) => {
        setPhoneErr('');
        const res = await api.put('/notify/settings', { notify_enabled: enabled });
        if (res && res.success) setSettings(res.data);
        else setPhoneErr((res && (res.detail || res.message)) || '설정을 바꾸지 못했습니다.');
    };

    /* 수신 번호 저장 — 수집이 멈췄을 때 문자가 갈 곳이다.
       ⚠️ 이 번호가 비어 있으면 경보는 표·로그에만 남고 아무도 모른다(2026-09-10). */
    const savePhone = async () => {
        setPhoneErr('');
        const res = await api.put('/notify/settings', { receiver_phone: phone.trim() });
        if (res && res.success) {
            setSettings(res.data);
            setPhone((res.data && res.data.receiver_phone) || '');   // 서버가 받은 값으로 되맞춘다
            setPhoneSaved(true);
            setTimeout(() => setPhoneSaved(false), 2500);
        } else {
            /* 서버가 준 사유를 그대로 보여 준다 — 「형식이 틀렸다」와 「서버가 아프다」는 다른 일이다. */
            setPhoneErr((res && (res.detail || res.message)) || '저장하지 못했습니다. 잠시 후 다시 시도해 주세요.');
        }
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

                    {/* 수신 번호 — 일일 리포트와 **수집 멈춤 경보**가 함께 쓴다.
                        ⚠️ 수집 멈춤 경보는 위 토글과 무관하게 이 번호만 보고 보낸다.
                           고장 알림까지 「일일 리포트」 스위치에 묶으면, 요약을 원치 않는 사람은
                           고장도 못 받는다(2026-09-10). */}
                    <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid #e2e8f0' }}>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>문자 받을 번호</div>
                        <div style={{ fontSize: 12, color: '#64748b', margin: '2px 0 8px' }}>
                            순위 수집이 <b>5시간 넘게 멈추면</b> 이 번호로 문자가 갑니다.
                            비워 두면 기록만 남고 아무에게도 알리지 않습니다.
                        </div>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            <input
                                type="tel"
                                value={phone}
                                onChange={e => setPhone(e.target.value)}
                                placeholder="01012345678"
                                style={{ flex: '0 1 220px', padding: '8px 10px', border: '1px solid #cbd5e1',
                                         borderRadius: 6, fontSize: 13 }}
                            />
                            <button className="btn" onClick={savePhone} style={{ padding: '8px 14px' }}>저장</button>
                            {phoneSaved && <span style={{ color: '#16a34a', fontSize: 12, fontWeight: 600 }}>저장됨</span>}
                        </div>
                        {phoneErr && (
                            <div style={{ marginTop: 8, color: '#b91c1c', fontSize: 12, fontWeight: 600 }}>
                                ⚠️ {phoneErr}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
