/* SeoRulesSection — 설정 탭: 사내 SEO 규칙 편집 (최고관리자 전용)
 * GET /api/seo/rules, PUT /api/seo/rules
 * 여기서 저장한 기준이 SEO 최적화 탭의 AI 생성에 즉시 반영됨(재배포 불필요).
 */
window.SeoRulesSection = function SeoRulesSection() {
    const { useState, useEffect } = React;
    const [text, setText] = useState('');
    const [orig, setOrig] = useState('');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    useEffect(function() {
        api.get('/seo/rules').then(function(res) {
            if (res && res.success && res.data) {
                setText(res.data.rules_text || '');
                setOrig(res.data.rules_text || '');
            }
            setLoading(false);
        }).catch(function(){ setLoading(false); });
    }, []);

    const save = async function() {
        if (!text.trim()) { if (window.toast) toast.warn('규칙 내용을 입력하세요'); return; }
        setSaving(true);
        try {
            var res = await api.put('/seo/rules', { rules_text: text });
            if (res && res.success) {
                setOrig(res.data.rules_text || text);
                if (window.toast && toast.success) toast.success('SEO 규칙이 저장되었습니다 — 생성에 즉시 반영됩니다');
            } else if (window.toast) {
                toast.warn((res && res.detail) || '저장에 실패했습니다.');
            }
        } catch (e) {
            if (window.toast) toast.warn('저장 요청에 실패했습니다.');
        }
        setSaving(false);
    };

    var dirty = text !== orig;

    return (
        <div className="card" style={{ padding: '20px 22px', marginBottom: 16, borderRadius: 16 }}>
            <h3 className="rt-h3"><span className="rt-hic">📋</span>SEO 사내 규칙</h3>
            <div className="rt-desc">여기서 정한 기준이 <b>SEO 최적화 탭의 AI 생성</b>에 즉시 적용됩니다. (상품명 공식·필수요소·금지어·태그/카테고리 기준 등)</div>

            {loading
                ? <div style={{ color: '#94a3b8', fontSize: 13, padding: '12px 0' }}>불러오는 중...</div>
                : <div>
                    <textarea value={text} onChange={function(e){ setText(e.target.value); }}
                        spellCheck={false}
                        style={{ width: '100%', minHeight: 360, padding: 14, border: '1px solid #e2e8f0', borderRadius: 10, fontSize: 13, lineHeight: 1.6, fontFamily: 'inherit', resize: 'vertical', whiteSpace: 'pre' }} />
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
                        <button className="btn btn-primary" onClick={save} disabled={saving || !dirty}>
                            {saving ? '저장 중...' : '저장'}
                        </button>
                        {dirty && <span style={{ fontSize: 12, color: '#f59e0b', fontWeight: 600 }}>● 저장되지 않은 변경사항</span>}
                        <span style={{ fontSize: 11, color: '#94a3b8', marginLeft: 'auto' }}>{text.length.toLocaleString()}자</span>
                    </div>
                </div>
            }
        </div>
    );
};
