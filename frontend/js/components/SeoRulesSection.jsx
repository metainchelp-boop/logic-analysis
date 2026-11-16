/* SeoRulesSection — 설정 탭: 사내 SEO 규칙 편집 (최고관리자 전용)
 * GET /api/seo/rules, PUT /api/seo/rules
 * 여기서 저장한 기준이 SEO 최적화 탭의 AI 생성에 즉시 반영됨(재배포 불필요).
 */
window.SeoRulesSection = function SeoRulesSection() {
    const { useState, useEffect, useRef } = React;
    const [text, setText] = useState('');
    const [orig, setOrig] = useState('');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [metadata, setMetadata] = useState(null);
    const [error, setError] = useState('');
    const busy = useRef(false);

    useEffect(function() {
        var alive = true;
        api.get('/seo/rules').then(function(res) {
            if (!alive) return;
            if (res && res.success && res.data) {
                setText(res.data.rules_text || '');
                setOrig(res.data.rules_text || '');
                setMetadata(res.data);
            } else setError('사내 기준을 불러오지 못했습니다. 기존 기준이 없는 것으로 판정하지 않습니다.');
            setLoading(false);
        }).catch(function(){ if (alive) { setError('사내 기준 조회에 실패했습니다. 새로고침 후 다시 확인하세요.'); setLoading(false); } });
        return function() { alive = false; };
    }, []);

    const save = async function() {
        if (busy.current) return;
        if (!text.trim()) { if (window.toast) toast.warn('규칙 내용을 입력하세요'); return; }
        busy.current = true; setSaving(true);
        try {
            var res = await api.put('/seo/rules', { rules_text: text });
            if (res && res.success) {
                var updated = res.data || {};
                setText(updated.rules_text || text); setOrig(updated.rules_text || text);
                setMetadata(function(prev){ return Object.assign({}, prev, updated); });
                if (window.toast && toast.success) toast.success('SEO 규칙이 저장되었습니다 — 생성에 즉시 반영됩니다');
            } else if (window.toast) {
                toast.warn((res && res.detail) || '저장에 실패했습니다.');
            }
        } catch (e) {
            if (window.toast) toast.warn('저장 요청에 실패했습니다.');
        }
        busy.current = false; setSaving(false);
    };

    const activate = async function() {
        if (busy.current || text !== orig || !metadata || metadata.is_recommended_active) return;
        if (!window.confirm('기존 사내 기준 원문을 이력에 보관하고 개정 기준을 활성화하시겠습니까? 이후 생성부터 적용되며, 스마트스토어 실제 상품은 변경하지 않습니다.')) return;
        busy.current = true; setSaving(true);
        try {
            var res = await api.post('/seo/rules/activate-recommended', {});
            if (res && res.success && res.data) {
                setText(res.data.rules_text || ''); setOrig(res.data.rules_text || ''); setMetadata(res.data);
                if (window.toast && toast.success) toast.success('개정 기준을 활성화했습니다. 기존 기준은 이력에 보관됩니다.');
            } else if (window.toast && toast.warn) toast.warn(res && typeof res.detail === 'string' ? res.detail : '기준 전환에 실패했습니다.');
        } catch (e) { if (window.toast && toast.warn) toast.warn('기준 전환 요청에 실패했습니다.'); }
        busy.current = false; setSaving(false);
    };

    var dirty = text !== orig;

    return (
        <div className="card" style={{ padding: '20px 22px', marginBottom: 16, borderRadius: 16 }}>
            <h3 className="rt-h3"><span className="rt-hic">📋</span>SEO 사내 규칙</h3>
            <div className="rt-desc">여기서 저장한 기준이 <b>이후 SEO 추천 생성</b>에 적용됩니다. 실제 상품 변경이나 이전 승인본 변경은 수행하지 않습니다.</div>
            {metadata && <div style={{ fontSize: 12, color: '#64748b', margin: '10px 0' }}>{metadata.is_recommended_active ? '개정 기준 사용' : '구 기준 사용 · 개정본 미적용'} · {metadata.version || '버전 미확인'}</div>}
            {error && <div role="alert" style={{ fontSize: 13, color: '#b91c1c', marginTop: 12 }}>{error}</div>}

            {loading
                ? <div style={{ color: '#94a3b8', fontSize: 13, padding: '12px 0' }}>불러오는 중...</div>
                : !error ? <div>
                    {metadata && metadata.recommended_rules_text && <details style={{ margin: '10px 0 14px' }}>
                        <summary style={{ cursor: 'pointer', fontSize: 13 }}>개정 기준 확인 · {metadata.recommended_version}</summary>
                        <pre style={{ whiteSpace: 'pre-wrap', font: 'inherit', fontSize: 12, lineHeight: 1.6, maxHeight: 260, overflow: 'auto' }}>{metadata.recommended_rules_text}</pre>
                        <div style={{ fontSize: 12, color: '#64748b' }}>공식 정책·관측·가설을 구분하며 네 항목을 직원 검수합니다. 기존 기준은 전환 시 이력에 보관합니다.</div>
                    </details>}
                    {metadata && !metadata.is_recommended_active && <div style={{ marginBottom: 12 }}>
                        <button className="btn" onClick={activate} disabled={saving || dirty || !metadata.recommended_rules_text}>개정 기준 활성화</button>
                        {dirty && <span style={{ marginLeft: 8, fontSize: 12, color: '#64748b' }}>작성 중인 기준을 먼저 저장한 뒤 전환하세요.</span>}
                    </div>}
                    <textarea value={text} onChange={function(e){ setText(e.target.value); }}
                        aria-label="사내 SEO 규칙" disabled={saving}
                        spellCheck={false}
                        style={{ width: '100%', minHeight: 360, padding: 14, border: '1px solid #e2e8f0', borderRadius: 10, fontSize: 13, lineHeight: 1.6, fontFamily: 'inherit', resize: 'vertical', whiteSpace: 'pre' }} />
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
                        <button className="btn btn-primary" onClick={save} disabled={saving || !dirty}>
                            {saving ? '저장 중...' : '저장'}
                        </button>
                        {dirty && <span style={{ fontSize: 12, color: '#f59e0b', fontWeight: 600 }}>● 저장되지 않은 변경사항</span>}
                        <span style={{ fontSize: 11, color: '#94a3b8', marginLeft: 'auto' }}>{text.length.toLocaleString()}자</span>
                    </div>
                </div> : null
            }
        </div>
    );
};
