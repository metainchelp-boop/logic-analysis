/* SeoOptimizerPage — 관리팀 SEO 검수 보조. 승인본 기록/복사만 수행하며
 * 네이버 실제 상품 변경이나 추가 수집은 호출하지 않는다. */
window.SeoOptimizerPage = function SeoOptimizerPage(props) {
    const { useState, useEffect, useRef } = React;
    const [mode, setMode] = useState('generate');
    const [clients, setClients] = useState([]);
    const [clientId, setClientId] = useState('');
    const [clientName, setClientName] = useState('');
    const [clientError, setClientError] = useState('');
    const [products, setProducts] = useState([]);
    const [productKey, setProductKey] = useState('');
    const [productsLoading, setProductsLoading] = useState(false);
    const [productsError, setProductsError] = useState('');
    const [savedList, setSavedList] = useState([]);
    const [savedLoading, setSavedLoading] = useState(false);
    const [savedError, setSavedError] = useState('');
    const [rules, setRules] = useState(null);
    const [rulesError, setRulesError] = useState('');
    const [showRules, setShowRules] = useState(false);
    const [diagKeyword, setDiagKeyword] = useState('');
    const [activeKeyword, setActiveKeyword] = useState('');
    const [genKeyword, setGenKeyword] = useState('');
    const [productUrl, setProductUrl] = useState('');
    const [brand, setBrand] = useState('');
    const [category, setCategory] = useState('');
    const [features, setFeatures] = useState('');
    const emptyCurrent = function() { return { product_name: null, tags: null, page_title: null, meta_description: null }; };
    const [currentValues, setCurrentValues] = useState(emptyCurrent);
    const [genLoading, setGenLoading] = useState(false);
    const [genError, setGenError] = useState('');
    const [genResult, setGenResult] = useState(null);
    const [decisions, setDecisions] = useState({});
    const [edits, setEdits] = useState({});
    const [reviewed, setReviewed] = useState(false);
    const [saving, setSaving] = useState(false);
    const [savedApproval, setSavedApproval] = useState(null);
    const generationEpoch = useRef(0);
    const companyEpoch = useRef(0);
    const savedEpoch = useRef(0);
    const clientRef = useRef('');
    const saveBusy = useRef(false);
    var allowed = !!(props.currentUser && ['manager', 'superadmin'].indexOf(props.currentUser.role) !== -1);
    var fields = [
        { key: 'product_name', label: '상품명' }, { key: 'tags', label: '판매자 태그' },
        { key: 'page_title', label: '페이지 타이틀' }, { key: 'meta_description', label: '메타 디스크립션' }
    ];
    var decisionLabels = { adopt: '채택', edit: '수정', hold: '보류 · 현재값 유지' };
    var card = { padding: '18px 20px', marginBottom: 14, borderRadius: 12 };
    var muted = { fontSize: 12, color: '#64748b', lineHeight: 1.6 };
    var row = { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' };
    var grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 12 };
    var warn = function(message) { if (window.toast && toast.warn) toast.warn(message); };
    var success = function(message) { if (window.toast && toast.success) toast.success(message); };
    var errorText = function(res, fallback) { return res && typeof res.detail === 'string' ? res.detail : fallback; };
    var valueText = function(value) { return value == null ? '미확인' : Array.isArray(value) ? value.join(', ') : String(value); };
    var tagsFromText = function(text) { return text.trim() ? text.split(/[,\n]/).map(function(t){ return t.trim(); }).filter(Boolean) : null; };

    /* 입력 이벤트에서 즉시 세대를 올려 React 렌더 전 도착한 응답도 폐기한다. */
    const invalidate = function() {
        generationEpoch.current++;
        setGenResult(null); setGenLoading(false); setGenError('');
        setReviewed(false); setSavedApproval(null);
    };
    useEffect(function() {
        if (!allowed) return;
        var alive = true;
        api.get('/cd/registered-clients').then(function(res) {
            if (!alive) return;
            if (res && res.success && Array.isArray(res.data)) setClients(res.data);
            else setClientError('업체 목록을 불러오지 못했습니다. 새로고침 후 다시 확인하세요.');
        }).catch(function(){ if (alive) setClientError('업체 목록 조회에 실패했습니다.'); });
        api.get('/seo/rules').then(function(res) {
            if (!alive) return;
            if (res && res.success && res.data) setRules(res.data);
            else setRulesError('사내 기준을 불러오지 못했습니다.');
        }).catch(function(){ if (alive) setRulesError('사내 기준 조회에 실패했습니다.'); });
        return function() { alive = false; generationEpoch.current++; companyEpoch.current++; savedEpoch.current++; };
    }, [allowed]);

    const loadSaved = function(cid) {
        var request = ++savedEpoch.current;
        setSavedList([]); setSavedError(''); setSavedLoading(!!cid);
        if (!cid) return;
        api.get('/seo/client/' + cid + '/saved').then(function(res) {
            if (request !== savedEpoch.current || clientRef.current !== cid) return;
            if (res && res.success && Array.isArray(res.data)) setSavedList(res.data);
            else setSavedError('저장 이력을 불러오지 못했습니다. 이력이 없는 것으로 판정하지 않습니다.');
        }).catch(function() {
            if (request === savedEpoch.current && clientRef.current === cid) setSavedError('저장 이력 조회에 실패했습니다.');
        }).finally(function() { if (request === savedEpoch.current) setSavedLoading(false); });
    };
    const loadProducts = function(cid) {
        var request = ++companyEpoch.current;
        setProducts([]); setProductsError(''); setProductsLoading(!!cid);
        if (!cid) return;
        api.get('/seo/client/' + cid + '/products').then(function(res) {
            if (request !== companyEpoch.current || clientRef.current !== cid) return;
            if (res && res.success && Array.isArray(res.data)) setProducts(res.data);
            else setProductsError('연결 상품을 불러오지 못했습니다. 연결 상품 없음과 다릅니다. 다시 조회하세요.');
        }).catch(function() {
            if (request === companyEpoch.current && clientRef.current === cid) setProductsError('연결 상품 조회에 실패했습니다. 다시 조회하세요.');
        }).finally(function() { if (request === companyEpoch.current) setProductsLoading(false); });
    };
    const clearFacts = function() {
        setProductUrl(''); setBrand(''); setCategory(''); setFeatures(''); setCurrentValues(emptyCurrent());
    };
    const handleSelectClient = function(cid) {
        invalidate(); clientRef.current = cid; setClientId(cid); setProductKey(''); clearFacts();
        var picked = clients.filter(function(c){ return String(c.id) === cid; })[0];
        var kw = picked && picked.main_keywords ? String(picked.main_keywords).split(',')[0].trim() : '';
        setClientName(picked ? picked.name : ''); setGenKeyword(kw); setDiagKeyword(kw); setActiveKeyword('');
        loadSaved(cid); loadProducts(cid);
    };
    const handleSelectProduct = function(key) {
        invalidate(); setProductKey(key); clearFacts();
        var picked = products.filter(function(p){ return p.product_key === key; })[0];
        if (!picked) return;
        setProductUrl(picked.product_url || ''); setGenKeyword(picked.keyword || '');
        setDiagKeyword(picked.keyword || ''); setActiveKeyword('');
        setBrand(picked.brand || ''); setCategory(picked.category || '');
        setFeatures(Array.isArray(picked.features) ? picked.features.join(', ') : picked.features || '');
        setCurrentValues(Object.assign(emptyCurrent(), picked.current_values || { product_name: picked.product_name || null }));
    };
    const changeFact = function(setter, value) { invalidate(); setter(value); };
    const changeCurrent = function(key, value) {
        invalidate(); setCurrentValues(function(prev) {
            var next = Object.assign({}, prev); next[key] = key === 'tags' ? tagsFromText(value) : value || null; return next;
        });
    };
    const handleGenerate = async function() {
        var kw = genKeyword.trim();
        if (!kw || genLoading) return;
        var request = ++generationEpoch.current;
        setGenLoading(true); setGenResult(null); setGenError(''); setReviewed(false); setSavedApproval(null);
        var body = { keyword: kw, brand: brand, category: category, features: features, product_url: productUrl, current_values: currentValues };
        if (clientId) body.client_id = Number(clientId);
        try {
            var res = await api.post('/seo/generate', body);
            if (request !== generationEpoch.current) return;
            if (!res || !res.success) { setGenError(errorText(res, 'SEO 생성에 실패했습니다.')); return; }
            var result = res.data;
            if (!result || !result.generation_id || !result.recommendation || !Array.isArray(result.recommendation.tags) ||
                !['product_name', 'page_title', 'meta_description'].every(function(key){ return typeof result.recommendation[key] === 'string'; })) {
                setGenError('생성 응답에 검수용 네 항목이 없습니다. 다시 생성하거나 관리자에게 문의하세요.'); return;
            }
            setGenResult(result);
            setDecisions({ product_name: 'hold', tags: 'hold', page_title: 'hold', meta_description: 'hold' });
            setEdits(Object.assign({}, result.recommendation, { tags: result.recommendation.tags.join(', ') }));
        } catch (e) {
            if (request === generationEpoch.current) setGenError('SEO 생성 요청에 실패했습니다. 잠시 후 다시 시도하세요.');
        } finally { if (request === generationEpoch.current) setGenLoading(false); }
    };
    const approvedValues = function() {
        var values = {};
        fields.forEach(function(field) {
            var key = field.key;
            if (decisions[key] === 'adopt') values[key] = genResult.recommendation[key];
            else if (decisions[key] === 'edit') {
                if (key === 'tags') {
                    var tags = (tagsFromText(edits[key] || '') || []).map(function(tag){ return tag.replace(/^#+/, ''); });
                    values[key] = tags.filter(function(tag, index){ return tags.indexOf(tag) === index; });
                } else values[key] = (edits[key] || '').trim();
            }
            else values[key] = genResult.current_values && genResult.current_values[key] != null ? genResult.current_values[key] : null;
        });
        return values;
    };
    const changeReview = function(setter, key, value) {
        setter(function(prev){ var next = Object.assign({}, prev); next[key] = value; return next; });
        setReviewed(false); setSavedApproval(null);
    };
    const saveToClient = async function() {
        if (saveBusy.current || !genResult || !reviewed || !clientId || savedApproval) return;
        saveBusy.current = true; setSaving(true);
        var request = generationEpoch.current;
        var cid = clientId;
        var values = approvedValues();
        try {
            var res = await api.post('/seo/save-to-client', {
                client_id: Number(cid), keyword: genResult.keyword,
                product_name: values.product_name || '', tags: values.tags || [], category: genResult.category || '',
                rationale: genResult.rationale || [], source: 'generate', generation_id: genResult.generation_id,
                reviewed: true, approved_values: values, decisions: decisions, product_url: genResult.product_url || ''
            });
            if (request !== generationEpoch.current || clientRef.current !== cid) return;
            if (res && res.success) {
                setSavedApproval(values); success('승인본을 전산에 저장했습니다. 스마트스토어 실제 상품은 변경하지 않았습니다.'); loadSaved(cid);
            } else warn(errorText(res, '승인본 저장에 실패했습니다.'));
        } catch (e) {
            if (request === generationEpoch.current) warn('승인본 저장 요청에 실패했습니다.');
        } finally { saveBusy.current = false; setSaving(false); }
    };
    const copy = async function(values) {
        var text = fields.map(function(field){ return field.label + ': ' + valueText(values[field.key]); }).join('\n');
        try { await navigator.clipboard.writeText(text); success('승인본을 복사했습니다. 스마트스토어에서 직원이 직접 반영하세요.'); }
        catch (e) { warn('복사에 실패했습니다. 브라우저의 클립보드 권한을 확인하세요.'); }
    };
    const exportCsv = function() {
        if (!genResult) return;
        var evidence = genResult.evidence || {};
        var values = savedApproval || approvedValues();
        var rows = [['항목', '현재값', '추천안', '검토값', '변경 이유', '검토 상태', '자료 날짜', '기준 버전']];
        rows.push(['업체', clientName, '키워드', genResult.keyword, '상품 URL', genResult.product_url || '', '승인 상태', savedApproval ? '승인본 저장됨 · 외부 미반영' : '검수 중 · 미승인']);
        fields.forEach(function(field) {
            rows.push([field.label, valueText((genResult.current_values || {})[field.key]), valueText(genResult.recommendation[field.key]), valueText(values[field.key]),
                ((genResult.field_reasons || {})[field.key] || []).join(' / '), decisionLabels[decisions[field.key]], evidence.collected_date || '미확인', genResult.rules_version || '미확인']);
        });
        rows.push(['자료 상태', evidence.label || '미확인', '광고 제외', evidence.ads_verified ? '확인' : '미확인']);
        var csv = rows.map(function(r) { return r.map(function(value) {
            var text = String(value == null ? '' : value);
            if (/^[\s\u0000-\u001f]*[=+@-]/.test(text)) text = "'" + text;
            return '"' + text.replace(/"/g, '""') + '"';
        }).join(','); }).join('\r\n');
        var url = URL.createObjectURL(new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' }));
        var anchor = document.createElement('a'); anchor.href = url;
        anchor.download = (clientName ? clientName + '_' : '') + 'SEO_' + genResult.keyword + '.csv'; anchor.click();
        setTimeout(function(){ URL.revokeObjectURL(url); }, 1000);
    };
    var evidence = genResult && genResult.evidence || {};
    if (!allowed) return <div role="alert">SEO 최적화는 관리팀·최고관리자 전용입니다.</div>;
    return (
        <div style={{ maxWidth: 1080, margin: '0 auto', padding: '24px 16px' }}>
            <h2 style={{ fontSize: 22, margin: '0 0 6px' }}>🔍 SEO 최적화 <span style={{ fontSize: 11, color: '#1d4ed8' }}>관리팀 전용</span></h2>
            <p style={muted}>상품 사실과 저장 자료를 바탕으로 네 항목을 검수합니다. 저장·복사는 전산 기록이며 스마트스토어 실제 상품을 변경하지 않습니다.</p>
            <div className="card" style={card}>
                <div style={row}>
                    <label htmlFor="seo-client" style={{ fontSize: 13, fontWeight: 700 }}>업체 선택</label>
                    <select id="seo-client" className="form-input" value={clientId} onChange={function(e){ handleSelectClient(e.target.value); }} style={{ minWidth: 230, maxWidth: 360 }}>
                        <option value="">— 업체 미선택 (일반 추천) —</option>
                        {clients.map(function(c){ return <option key={c.id} value={c.id}>{c.name}</option>; })}
                    </select>
                    <button className="btn" style={{ marginLeft: 'auto' }} onClick={function(){ setShowRules(!showRules); }}>📋 사내 SEO 기준 {showRules ? '닫기' : '보기'}</button>
                    <span style={muted}>{rules ? (rules.is_recommended_active ? '개정 기준 사용' : '구 기준 사용 · 개정본 미적용') + ' · ' + (rules.version || '버전 미확인') : rulesError || '기준 조회 중'}</span>
                </div>
                {clientError && <p role="alert" style={muted}>{clientError}</p>}
                {showRules && <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, maxHeight: 260, overflow: 'auto', lineHeight: 1.6 }}>{rules ? rules.rules_text : rulesError || '불러오는 중...'}</pre>}
            </div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
                <button className={mode === 'generate' ? 'btn btn-primary' : 'btn'} onClick={function(){ setMode('generate'); }}>✨ SEO 생성</button>
                <button className={mode === 'diagnose' ? 'btn btn-primary' : 'btn'} onClick={function(){ setMode('diagnose'); }}>🩺 SEO 진단·점검</button>
            </div>
            {mode === 'generate' && <div>
                <div className="card" style={card}>
                    {clientId && <div style={{ marginBottom: 12 }}>
                        <label htmlFor="seo-product" style={muted}>연결 상품</label>
                        <select id="seo-product" className="form-input" value={productKey} disabled={productsLoading} onChange={function(e){ handleSelectProduct(e.target.value); }}>
                            <option value="">{productsLoading ? '연결 상품 조회 중...' : '— 상품 선택 또는 사실정보 직접 입력 —'}</option>
                            {products.map(function(p){ return <option key={p.product_key} value={p.product_key}>{p.product_name || p.product_key} · {p.keyword}</option>; })}
                        </select>
                        {productsError ? <p role="alert" style={muted}>{productsError} <button className="btn" onClick={function(){ loadProducts(clientId); }}>연결 상품 다시 조회</button></p> : !productsLoading && products.length === 0 ? <p style={muted}>연결 상품이 없습니다. 아래 사실정보를 직접 입력할 수 있습니다.</p> : null}
                    </div>}
                    <label htmlFor="seo-keyword" style={muted}>대표 키워드</label>
                    <input id="seo-keyword" className="form-input" placeholder="예: 생멸치" value={genKeyword} onChange={function(e){ changeFact(setGenKeyword, e.target.value); }} onKeyDown={function(e){ if (e.key === 'Enter') handleGenerate(); }} />
                    <details style={{ margin: '12px 0' }}>
                        <summary style={{ cursor: 'pointer', fontSize: 13, color: '#334155' }}>상품 사실·현재값 확인 및 보완</summary>
                        <p style={muted}>연결 자료에 없는 값은 미확인입니다. 실제 상품에서 확인한 값만 입력하세요. URL 입력만으로 외부 수집하지 않습니다.</p>
                        <div style={grid}>
                            <div><label htmlFor="seo-url" style={muted}>상품 URL</label><input id="seo-url" className="form-input" value={productUrl} onChange={function(e){ changeFact(setProductUrl, e.target.value); }} /></div>
                            <div><label htmlFor="seo-brand" style={muted}>브랜드</label><input id="seo-brand" className="form-input" value={brand} onChange={function(e){ changeFact(setBrand, e.target.value); }} /></div>
                            <div><label htmlFor="seo-category" style={muted}>카테고리</label><input id="seo-category" className="form-input" value={category} onChange={function(e){ changeFact(setCategory, e.target.value); }} /></div>
                            <div><label htmlFor="seo-features" style={muted}>확인된 특징·속성</label><input id="seo-features" className="form-input" value={features} onChange={function(e){ changeFact(setFeatures, e.target.value); }} /></div>
                            {fields.map(function(field){ return <div key={field.key}><label htmlFor={'seo-current-' + field.key} style={muted}>현재 {field.label}</label><input id={'seo-current-' + field.key} className="form-input" placeholder="미확인" value={currentValues[field.key] == null ? '' : valueText(currentValues[field.key])} onChange={function(e){ changeCurrent(field.key, e.target.value); }} /></div>; })}
                        </div>
                    </details>
                    <button className="btn btn-primary" onClick={handleGenerate} disabled={genLoading || !genKeyword.trim()}>{genLoading ? 'AI 생성 중...' : '검수 추천 생성'}</button>
                    <p style={muted}>입력한 사실이 적으면 일반 추천에 한정됩니다. 순위·매출 상승을 보장하지 않습니다.</p>
                    {genError && <p role="alert" style={{ color: '#b91c1c', fontSize: 13 }}>{genError}</p>}
                </div>
                {genLoading && React.createElement(window.LoadingSpinner, { text: '저장 자료 기반 추천 생성 중...' })}
                {genResult && <div data-testid="seo-review">
                    <div className="card" style={card}>
                        <div style={row}><b style={{ fontSize: 14 }}>저장 자료 근거: {evidence.label || '자료 상태 미확인'}</b><span style={muted}>기준 버전 {genResult.rules_version || '미확인'}</span></div>
                        <p style={muted}>자료 날짜: {evidence.collected_date || '미확인'} · 정확한 관측 시각: {evidence.observed_at || '미확인'} · 검색 화면: {evidence.surface || '미확인'} · 광고 제외: {evidence.ads_verified ? '확인' : '미확인'}</p>
                        <p style={muted}>경쟁상품의 실제 태그·타이틀·메타 설정값은 이 자료로 확인하지 못했습니다. 공통어 빈도는 순위 상승의 인과관계가 아닙니다.</p>
                        <details><summary style={{ cursor: 'pointer', fontSize: 12 }}>확보 상품·공통어·한계 보기</summary>
                            <ul style={muted}>{(evidence.products || []).map(function(p, i){ return <li key={i} style={{ overflowWrap: 'anywhere', marginBottom: 6 }}>{p.rank == null ? '순위 미확인' : p.rank + '위'} · {p.product_name || p.title || '상품명 미확인'} · ID: {p.product_id || '미확인'} · {p.mall_name || '판매처 미확인'} · {p.category || '카테고리 미확인'} · 가격: {p.price == null ? '미확인' : p.price} · {p.product_url || p.url || 'URL 미확인'}</li>; })}</ul>
                            <p style={muted}>공통어: {(evidence.common_terms || []).map(function(term){ return typeof term === 'string' ? term : term.term + ' (' + term.count + '/' + (term.total || (evidence.products || []).length) + '개 상품)'; }).join(', ') || '없음/미확인'}</p>
                            {(evidence.notes || []).map(function(note, i){ return <p key={i} style={muted}>{note}</p>; })}
                        </details>
                    </div>
                    {fields.map(function(field) { var key = field.key; return <div key={key} className="card" style={card}>
                        <div style={row}><b style={{ fontSize: 14 }}>{field.label}</b><select aria-label={field.label + ' 검토 결정'} className="form-input" style={{ marginLeft: 'auto', width: 190 }} value={decisions[key]} disabled={saving || !!savedApproval} onChange={function(e){ changeReview(setDecisions, key, e.target.value); }}><option value="hold">보류 · 현재값 유지</option><option value="adopt">채택</option><option value="edit">수정</option></select></div>
                        <div style={Object.assign({}, grid, { marginTop: 10 })}>
                            <div><div style={muted}>현재값</div><div style={{ fontSize: 13, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{valueText((genResult.current_values || {})[key])}</div></div>
                            <div><div style={muted}>추천안</div><div style={{ fontSize: 13, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{valueText(genResult.recommendation[key])}</div></div>
                        </div>
                        <p style={muted}>변경 이유: {((genResult.field_reasons || {})[key] || []).join(' / ') || '제공되지 않음'}</p>
                        {decisions[key] === 'edit' && <textarea aria-label={field.label + ' 수정값'} className="form-input" rows={key === 'meta_description' ? 3 : 2} value={edits[key] || ''} disabled={saving || !!savedApproval} onChange={function(e){ changeReview(setEdits, key, e.target.value); }} />}
                        {decisions[key] === 'hold' && <div style={muted}>현재값을 유지합니다. 미확인 값은 미확인으로 보존합니다.</div>}
                    </div>; })}
                    {genResult.product_names && genResult.product_names.length > 1 && <details style={{ marginBottom: 12 }}><summary style={muted}>다른 상품명 후보</summary><ul style={muted}>{genResult.product_names.slice(1).map(function(name, i){ return <li key={i}>{name} <button className="btn" disabled={saving || !!savedApproval} onClick={function(){ changeReview(setDecisions, 'product_name', 'edit'); changeReview(setEdits, 'product_name', name); }}>이 상품명 선택</button></li>; })}</ul></details>}
                    {genResult.category && <p style={muted}>카테고리 참고안: {genResult.category} · 실제 상품 분류를 확인하세요.</p>}
                    <div className="card" style={card}>
                        <label style={{ fontSize: 13, lineHeight: 1.6 }}><input type="checkbox" checked={reviewed} disabled={saving || !!savedApproval} onChange={function(e){ setReviewed(e.target.checked); }} /> 실제 상품 사실과 네 항목의 채택·수정·보류 결정을 검토했습니다.</label>
                        <div style={Object.assign({}, row, { marginTop: 12 })}>
                            <button className="btn btn-primary" disabled={!clientId || !reviewed || saving || !!savedApproval} onClick={saveToClient}>{saving ? '저장 중...' : savedApproval ? '승인본 저장됨' : '승인본 저장'}</button>
                            <button className="btn" disabled={!savedApproval} onClick={function(){ copy(savedApproval); }}>승인본 복사</button>
                            <button className="btn" onClick={exportCsv}>검수 결과 CSV</button>
                        </div>
                        {!clientId && <p style={muted}>업체 미선택 일반 추천입니다. 업체별 승인 기록은 업체를 선택한 뒤 다시 생성하여 저장하세요.</p>}
                        <p role="status" style={muted}>{savedApproval ? '승인본은 전산에 저장되었습니다. 스마트스토어 실제 상품은 변경하지 않았습니다. 직원이 직접 반영해야 합니다.' : '승인 확인 전에는 승인본으로 저장하거나 복사하지 않습니다. 보류 항목은 현재값을 유지합니다.'}</p>
                    </div>
                </div>}
                {clientId && <div className="card" style={card}>
                    <div style={row}><b style={{ fontSize: 14 }}>🗂️ {clientName} · 저장된 SEO 작업 ({savedList.length})</b><button className="btn" disabled={savedLoading} onClick={function(){ loadSaved(clientId); }}>이력 새로고침</button></div>
                    {savedLoading ? <p style={muted}>저장 이력 조회 중...</p> : savedError ? <p role="alert" style={muted}>{savedError}</p> : savedList.length === 0 ? <p style={muted}>저장된 SEO 작업이 없습니다.</p> : null}
                    {savedList.map(function(it) { var review = it.review; return <div key={it.id} style={{ padding: '12px 0', borderBottom: '1px solid #e2e8f0' }}>
                        <div style={row}><b style={{ fontSize: 13 }}>{review ? valueText(review.approved_values.product_name) : it.product_name || '(상품명 없음)'}</b><span style={muted}>키워드: {it.keyword} · {(it.created_at || '').slice(0, 10)} · {it.created_by}</span></div>
                        {review ? <details><summary style={muted}>승인 기록 · {review.rules_version} · {review.reviewed_by} · {review.reviewed_at}</summary>
                            {fields.map(function(field){ return <p key={field.key} style={muted}>{field.label}: {valueText(review.approved_values[field.key])} · {decisionLabels[review.decisions[field.key]] || '미확인'}</p>; })}
                            {review.original && <details><summary style={muted}>저장 당시 추천 원본·근거</summary>
                                <p style={muted}>입력 브랜드: {(review.original.input_facts || {}).brand || '미확인'} · 입력 카테고리: {(review.original.input_facts || {}).category || '미확인'} · 확인한 속성: {(review.original.input_facts || {}).features || '미확인'}</p>
                                {fields.map(function(field){ var original = review.original; return <p key={field.key} style={muted}>{field.label} · 당시 현재값: {valueText((original.current_values || {})[field.key])} → 추천안: {valueText((original.recommendation || {})[field.key])} · 변경 이유: {((original.field_reasons || {})[field.key] || []).join(' / ') || '미확인'}</p>; })}
                                <p style={muted}>자료 상태: {(review.original.evidence || {}).label || '미확인'} · 자료 날짜: {(review.original.evidence || {}).collected_date || '미확인'} · 관측 시각: {(review.original.evidence || {}).observed_at || '미확인'} · 광고 제외: {(review.original.evidence || {}).ads_verified ? '확인' : '미확인'}</p>
                            </details>}
                            <p style={muted}>{review.product_url || '상품 URL 미확인'} · 외부 반영 여부는 확인하지 않았습니다.</p><button className="btn" onClick={function(){ copy(review.approved_values); }}>저장된 승인본 복사</button>
                        </details> : <div style={muted}>이전 형식 기록 · 검수 상태 미확인{Array.isArray(it.tags) && it.tags.length > 0 ? ' · ' + it.tags.join(', ') : ''}</div>}
                    </div>; })}
                </div>}
            </div>}
            {mode === 'diagnose' && <div>
                <div className="card" style={card}>
                    <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 10 }}>① 기준 키워드 입력</div>
                    <div style={{ display: 'flex', gap: 10 }}>
                        <input aria-label="진단 기준 키워드" className="form-input" placeholder="진단 기준 키워드 (예: 생멸치, 무선이어폰)" value={diagKeyword} onChange={function(e){ setDiagKeyword(e.target.value); }} onKeyDown={function(e){ if (e.key === 'Enter') setActiveKeyword(diagKeyword.trim()); }} style={{ flex: 1 }} />
                        <button className="btn btn-primary" disabled={!diagKeyword.trim()} onClick={function(){ setActiveKeyword(diagKeyword.trim()); }}>키워드 적용</button>
                    </div>
                    <p style={muted}>{clientName ? '업체 ' + clientName + '의 키워드가 입력되었습니다. ' : ''}키워드를 적용한 뒤, 아래에서 진단할 상품 URL을 입력하면 10개 지표로 SEO 상태를 진단합니다.</p>
                </div>
                {activeKeyword ? React.createElement(window.SeoDiagnosisSection, { keyword: activeKeyword }) : <div className="card" style={card}>기준 키워드를 먼저 적용해주세요.</div>}
            </div>}
        </div>
    );
};
