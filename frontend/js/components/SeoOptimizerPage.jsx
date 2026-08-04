/* SeoOptimizerPage — 네이버 쇼핑 SEO 최적화 (관리팀 전용 상단 탭)
 * 우리 업무 방식 반영:
 *  - 업체(고객) 연동: 업체 선택 → 키워드/URL 자동입력 → 결과를 업체 기록으로 저장(담당자 이어받기)
 *  - 사내 SEO 규칙: 설정 탭에서 편집한 기준을 AI 생성에 적용 + 화면에 '적용 기준' 표시
 *  - 결과물 산출/공유: 생성 결과를 CSV로 내보내기
 * props: { currentUser }
 */
window.SeoOptimizerPage = function SeoOptimizerPage(props) {
    const { useState, useEffect } = React;
    const [mode, setMode] = useState('generate'); // 'generate' | 'diagnose'

    /* ---------- 업체 연동 ---------- */
    const [clients, setClients] = useState([]);
    const [clientId, setClientId] = useState('');
    const [clientName, setClientName] = useState('');
    const [savedList, setSavedList] = useState([]);

    /* ---------- 사내 규칙(읽기 표시) ---------- */
    const [rules, setRules] = useState('');
    const [showRules, setShowRules] = useState(false);

    /* ---------- 진단 ---------- */
    const [diagKeyword, setDiagKeyword] = useState('');
    const [activeKeyword, setActiveKeyword] = useState('');

    /* ---------- 생성 ---------- */
    const [genKeyword, setGenKeyword] = useState('');
    const [brand, setBrand] = useState('');
    const [category, setCategory] = useState('');
    const [features, setFeatures] = useState('');
    const [genLoading, setGenLoading] = useState(false);
    const [genResult, setGenResult] = useState(null);

    /* 업체 목록 + 사내 규칙 로드 */
    useEffect(function() {
        api.get('/cd/registered-clients').then(function(res) {
            if (res && res.success) setClients(res.data || []);
        }).catch(function(){});
        api.get('/seo/rules').then(function(res) {
            if (res && res.success && res.data) setRules(res.data.rules_text || '');
        }).catch(function(){});
    }, []);

    /* 업체별 저장 이력 로드 */
    const loadSaved = function(cid) {
        if (!cid) { setSavedList([]); return; }
        api.get('/seo/client/' + cid + '/saved').then(function(res) {
            if (res && res.success) setSavedList(res.data || []);
        }).catch(function(){});
    };

    /* 업체 선택 → 키워드/URL 자동입력 + 이력 로드 */
    const handleSelectClient = function(cid) {
        setClientId(cid);
        if (!cid) { setClientName(''); setSavedList([]); return; }
        var picked = clients.filter(function(c){ return String(c.id) === String(cid); })[0];
        setClientName(picked ? picked.name : '');
        // 대표 키워드 자동입력 (첫 키워드)
        var kw = picked && picked.main_keywords ? String(picked.main_keywords).split(',')[0].trim() : '';
        if (kw) { setGenKeyword(kw); setDiagKeyword(kw); }
        loadSaved(cid);
    };

    /* ---------- 유틸 ---------- */
    const copy = function(text) {
        try {
            navigator.clipboard.writeText(text);
            if (window.toast && toast.success) toast.success('복사되었습니다');
        } catch (e) {
            if (window.toast && toast.warn) toast.warn('복사에 실패했습니다');
        }
    };

    const handleGenerate = async function() {
        var kw = (genKeyword || '').trim();
        if (!kw) { if (window.toast) toast.warn('키워드를 입력하세요'); return; }
        setGenLoading(true);
        setGenResult(null);
        try {
            var body = { keyword: kw, brand: brand || '', category: category || '', features: features || '' };
            if (clientId) body.client_id = Number(clientId);
            var res = await api.post('/seo/generate', body);
            if (res && res.success) setGenResult(res.data);
            else if (window.toast) toast.warn((res && res.detail) || 'SEO 생성에 실패했습니다.');
        } catch (e) {
            if (window.toast) toast.warn('SEO 생성 요청 실패 — 잠시 후 다시 시도해주세요.');
        }
        setGenLoading(false);
    };

    /* 업체에 저장 (선택한 상품명 기준) */
    const saveToClient = async function(productName) {
        if (!clientId) { if (window.toast) toast.warn('먼저 업체를 선택하세요'); return; }
        if (!genResult) return;
        try {
            var res = await api.post('/seo/save-to-client', {
                client_id: Number(clientId),
                keyword: genResult.keyword,
                product_name: productName || (genResult.product_names[0] || ''),
                tags: genResult.tags || [],
                category: genResult.category || '',
                rationale: genResult.rationale || [],
                source: 'generate'
            });
            if (res && res.success) {
                if (window.toast && toast.success) toast.success('업체 기록에 저장되었습니다');
                loadSaved(clientId);
            } else if (window.toast) {
                toast.warn((res && res.detail) || '저장에 실패했습니다.');
            }
        } catch (e) {
            if (window.toast) toast.warn('저장 요청에 실패했습니다.');
        }
    };

    /* 결과물 내보내기 (CSV) */
    const exportCsv = function() {
        if (!genResult) return;
        var rows = [['항목', '내용']];
        if (clientName) rows.push(['업체', clientName]);
        rows.push(['대표 키워드', genResult.keyword]);
        (genResult.product_names || []).forEach(function(nm, i) { rows.push(['추천 상품명 ' + (i + 1), nm]); });
        rows.push(['추천 태그', (genResult.tags || []).join(', ')]);
        rows.push(['추천 카테고리', genResult.category || '']);
        (genResult.rationale || []).forEach(function(r, i) { rows.push(['적용 근거 ' + (i + 1), r]); });
        var csv = rows.map(function(r) {
            return r.map(function(cell) {
                var s = String(cell == null ? '' : cell).replace(/"/g, '""');
                return '"' + s + '"';
            }).join(',');
        }).join('\r\n');
        // 엑셀 한글 깨짐 방지 BOM
        var blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        var fn = (clientName ? clientName + '_' : '') + 'SEO_' + (genResult.keyword || '') + '.csv';
        a.download = fn;
        a.click();
        if (window.toast && toast.success) toast.success('CSV로 내보냈습니다');
    };

    /* ---------- 스타일 ---------- */
    var tabBtn = function(active) {
        return {
            padding: '10px 20px', borderRadius: 10, cursor: 'pointer', fontSize: 14, fontWeight: 700,
            border: active ? '1px solid #3b82f6' : '1px solid #e2e8f0',
            background: active ? '#3b82f6' : '#fff', color: active ? '#fff' : '#475569', transition: 'all .15s'
        };
    };
    var chip = {
        display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px', margin: '4px 6px 4px 0',
        background: '#eef2ff', color: '#3730a3', borderRadius: 999, fontSize: 13, fontWeight: 600,
        cursor: 'pointer', border: '1px solid #c7d2fe'
    };

    return (
        <div style={{ maxWidth: 1080, margin: '0 auto', padding: '24px 16px' }}>
            <div style={{ marginBottom: 18 }}>
                <h2 style={{ fontSize: 22, fontWeight: 900, margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: 8 }}>
                    🔍 SEO 최적화
                    <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 9px', borderRadius: 999, background: '#dbeafe', color: '#1d4ed8' }}>관리팀 전용</span>
                </h2>
                <div style={{ color: '#64748b', fontSize: 13 }}>업체를 선택해 사내 SEO 기준으로 진단·생성하고, 결과를 업체 기록에 저장·공유합니다.</div>
            </div>

            {/* 업체 선택 + 사내 기준 */}
            <div className="card" style={{ padding: '16px 20px', marginBottom: 16, borderRadius: 16 }}>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                    <label style={{ fontSize: 13, fontWeight: 700, color: '#334155' }}>🏢 업체 선택</label>
                    <select className="form-input" value={clientId} onChange={function(e){ handleSelectClient(e.target.value); }} style={{ minWidth: 240, maxWidth: 360 }}>
                        <option value="">— 업체를 선택하세요 (선택) —</option>
                        {clients.map(function(c) {
                            return <option key={c.id} value={c.id}>{c.name}</option>;
                        })}
                    </select>
                    {clientName && <span style={{ fontSize: 12, color: '#0f766e', fontWeight: 600 }}>선택됨: {clientName} · 대표키워드 자동입력</span>}
                    <button className="btn" style={{ marginLeft: 'auto', padding: '6px 12px', fontSize: 12 }} onClick={function(){ setShowRules(!showRules); }}>
                        📋 사내 SEO 기준 {showRules ? '닫기' : '보기'}
                    </button>
                </div>
                {showRules && (
                    <pre style={{ marginTop: 12, padding: 14, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, fontSize: 12, color: '#334155', whiteSpace: 'pre-wrap', lineHeight: 1.6, maxHeight: 320, overflow: 'auto' }}>
                        {rules || '사내 SEO 기준이 아직 설정되지 않았습니다. (설정 탭 → SEO 규칙)'}
                    </pre>
                )}
            </div>

            {/* 모드 전환 */}
            <div style={{ display: 'flex', gap: 10, marginBottom: 18 }}>
                <button style={tabBtn(mode === 'generate')} onClick={function(){ setMode('generate'); }}>✨ SEO 생성</button>
                <button style={tabBtn(mode === 'diagnose')} onClick={function(){ setMode('diagnose'); }}>🩺 SEO 진단·점검</button>
            </div>

            {/* ===== 생성 모드 ===== */}
            {mode === 'generate' && (
                <div className="fade-in">
                    <div className="card" style={{ padding: '18px 20px', marginBottom: 16, borderRadius: 16 }}>
                        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>상품 정보 입력</div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                            <div>
                                <label style={{ fontSize: 12, color: '#64748b', fontWeight: 600 }}>대표 키워드 <span style={{ color: '#ef4444' }}>*</span></label>
                                <input className="form-input" placeholder="예: 생멸치 1kg" value={genKeyword}
                                    onChange={function(e){ setGenKeyword(e.target.value); }}
                                    onKeyDown={function(e){ if (e.key === 'Enter') handleGenerate(); }} />
                            </div>
                            <div>
                                <label style={{ fontSize: 12, color: '#64748b', fontWeight: 600 }}>브랜드 (선택)</label>
                                <input className="form-input" placeholder="예: 바다드림" value={brand}
                                    onChange={function(e){ setBrand(e.target.value); }} />
                            </div>
                            <div>
                                <label style={{ fontSize: 12, color: '#64748b', fontWeight: 600 }}>희망 카테고리 (선택)</label>
                                <input className="form-input" placeholder="예: 식품 > 수산물 > 건어물" value={category}
                                    onChange={function(e){ setCategory(e.target.value); }} />
                            </div>
                            <div>
                                <label style={{ fontSize: 12, color: '#64748b', fontWeight: 600 }}>제품 특징/속성 (선택)</label>
                                <input className="form-input" placeholder="예: 국내산, 무염, 대용량" value={features}
                                    onChange={function(e){ setFeatures(e.target.value); }} />
                            </div>
                        </div>
                        <button className="btn btn-primary" onClick={handleGenerate} disabled={genLoading || !genKeyword.trim()}>
                            {genLoading ? 'AI 생성 중...' : '✨ SEO 생성'}
                        </button>
                        <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 8 }}>
                            사내 SEO 기준 + 네이버 상위 노출 상품을 반영해 AI가 상품명·태그·카테고리를 제안합니다.
                        </div>
                    </div>

                    {genLoading && React.createElement(window.LoadingSpinner, { text: '네이버 데이터 분석 + AI 생성 중...' })}

                    {genResult && !genLoading && (
                        <div className="fade-in">
                            {/* 액션 바 */}
                            <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                                <button className="btn" onClick={exportCsv}>📤 결과 내보내기 (CSV)</button>
                                {clientId
                                    ? <button className="btn btn-primary" onClick={function(){ saveToClient(genResult.product_names[0]); }}>💾 {clientName}에 저장 (1순위)</button>
                                    : <span style={{ fontSize: 12, color: '#94a3b8', alignSelf: 'center' }}>※ 업체를 선택하면 결과를 업체 기록에 저장할 수 있습니다</span>}
                            </div>

                            {/* 상품명 후보 */}
                            <div className="card" style={{ padding: '18px 20px', marginBottom: 14, borderRadius: 16 }}>
                                <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                                    ✏️ 추천 상품명 <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 999, background: '#fce7f3', color: '#9d174d' }}>AI</span>
                                </div>
                                {genResult.product_names.map(function(nm, i) {
                                    return (
                                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: i < genResult.product_names.length - 1 ? '1px solid #f1f5f9' : 'none' }}>
                                            <span style={{ width: 22, height: 22, flexShrink: 0, borderRadius: 6, background: '#ec4899', color: '#fff', fontSize: 11, fontWeight: 800, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>{i + 1}</span>
                                            <b style={{ flex: 1, fontSize: 14, lineHeight: 1.5 }}>{nm}</b>
                                            <span style={{ fontSize: 11, color: '#94a3b8' }}>{nm.length}자</span>
                                            <button className="btn" style={{ padding: '4px 10px', fontSize: 12 }} onClick={function(){ copy(nm); }}>복사</button>
                                            {clientId && <button className="btn" style={{ padding: '4px 10px', fontSize: 12 }} onClick={function(){ saveToClient(nm); }}>이 안 저장</button>}
                                        </div>
                                    );
                                })}
                            </div>

                            {/* 추천 태그 */}
                            {genResult.tags && genResult.tags.length > 0 && (
                                <div className="card" style={{ padding: '18px 20px', marginBottom: 14, borderRadius: 16 }}>
                                    <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                                        🏷️ 추천 태그 ({genResult.tags.length})
                                        <button className="btn" style={{ marginLeft: 'auto', padding: '4px 10px', fontSize: 12 }}
                                            onClick={function(){ copy(genResult.tags.join(', ')); }}>전체 복사</button>
                                    </div>
                                    <div>
                                        {genResult.tags.map(function(tg, i) {
                                            return <span key={i} style={chip} onClick={function(){ copy(tg); }}>#{tg}</span>;
                                        })}
                                    </div>
                                </div>
                            )}

                            {/* 추천 카테고리 */}
                            {genResult.category && (
                                <div className="card" style={{ padding: '18px 20px', marginBottom: 14, borderRadius: 16 }}>
                                    <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 8 }}>📂 추천 카테고리</div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                        <b style={{ fontSize: 14, color: '#0f766e' }}>{genResult.category}</b>
                                        <button className="btn" style={{ padding: '4px 10px', fontSize: 12 }} onClick={function(){ copy(genResult.category); }}>복사</button>
                                    </div>
                                </div>
                            )}

                            {/* 근거 */}
                            {genResult.rationale && genResult.rationale.length > 0 && (
                                <div className="card" style={{ padding: '18px 20px', marginBottom: 14, borderRadius: 16 }}>
                                    <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 12 }}>💡 적용 근거 (사내 기준 반영)</div>
                                    {genResult.rationale.map(function(r, i) {
                                        return (
                                            <div key={i} style={{ padding: '8px 0', borderBottom: i < genResult.rationale.length - 1 ? '1px solid #f1f5f9' : 'none', fontSize: 13, color: '#334155', display: 'flex', gap: 10, lineHeight: 1.7 }}>
                                                <span style={{ color: '#10b981', fontWeight: 800, flexShrink: 0 }}>✔</span>{r}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}

                            <div className="note est" style={{ fontSize: 12 }}>
                                ※ AI가 네이버 상위 노출 상품 {(genResult.context && genResult.context.sampled_titles) || 0}건 + 사내 SEO 기준을 반영해 생성한 제안입니다. 등록 전 실제 상품 정보와 맞는지 검토 후 사용하세요.
                            </div>
                        </div>
                    )}

                    {/* 업체 저장 이력 */}
                    {clientId && savedList.length > 0 && (
                        <div className="card" style={{ padding: '18px 20px', marginTop: 8, borderRadius: 16 }}>
                            <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 12 }}>🗂️ {clientName} · 저장된 SEO 작업 ({savedList.length})</div>
                            {savedList.map(function(it) {
                                return (
                                    <div key={it.id} style={{ padding: '10px 0', borderBottom: '1px solid #f1f5f9' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                            <b style={{ fontSize: 13 }}>{it.product_name || '(상품명 없음)'}</b>
                                            <span style={{ fontSize: 11, color: '#94a3b8' }}>키워드: {it.keyword}</span>
                                            <span style={{ fontSize: 11, color: '#cbd5e1', marginLeft: 'auto' }}>{(it.created_at || '').slice(0, 10)} · {it.created_by}</span>
                                        </div>
                                        {it.tags && it.tags.length > 0 && <div style={{ fontSize: 12, color: '#3b82f6', marginTop: 4 }}>{it.tags.map(function(t){ return '#' + t; }).join(' ')}</div>}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}

            {/* ===== 진단 모드 ===== */}
            {mode === 'diagnose' && (
                <div className="fade-in">
                    <div className="card" style={{ padding: '18px 20px', marginBottom: 8, borderRadius: 16 }}>
                        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 10 }}>① 기준 키워드 입력</div>
                        <div style={{ display: 'flex', gap: 10 }}>
                            <input className="form-input" placeholder="진단 기준 키워드 (예: 생멸치, 무선이어폰)"
                                value={diagKeyword}
                                onChange={function(e){ setDiagKeyword(e.target.value); }}
                                onKeyDown={function(e){ if (e.key === 'Enter') setActiveKeyword(diagKeyword.trim()); }}
                                style={{ flex: 1 }} />
                            <button className="btn btn-primary" disabled={!diagKeyword.trim()}
                                onClick={function(){ setActiveKeyword(diagKeyword.trim()); }}>키워드 적용</button>
                        </div>
                        <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>
                            {clientName ? <span>업체 <b>{clientName}</b>의 대표 키워드가 입력되었습니다. </span> : null}
                            키워드를 적용한 뒤, 아래에서 진단할 상품 URL을 입력하면 10개 지표로 SEO 상태를 진단합니다.
                        </div>
                    </div>

                    {activeKeyword
                        ? React.createElement(window.SeoDiagnosisSection, { keyword: activeKeyword })
                        : <div className="card" style={{ padding: '28px 20px', textAlign: 'center', color: '#94a3b8', borderRadius: 16 }}>
                            기준 키워드를 먼저 적용해주세요.
                          </div>
                    }
                </div>
            )}
        </div>
    );
};
