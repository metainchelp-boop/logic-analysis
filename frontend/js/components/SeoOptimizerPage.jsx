/* SeoOptimizerPage — 네이버 쇼핑 SEO 최적화 (관리팀 전용 상단 탭)
 * 1) 진단: 상품 URL + 키워드 → 기존 /seo/analyze 엔진 재활용 (SeoDiagnosisSection)
 * 2) 생성: 키워드(+브랜드/카테고리/특징) → /seo/generate (Claude) → 상품명·태그·카테고리 제안
 * props: { currentUser }
 */
window.SeoOptimizerPage = function SeoOptimizerPage(props) {
    const { useState } = React;
    const [mode, setMode] = useState('diagnose'); // 'diagnose' | 'generate'

    /* ---------- 진단 ---------- */
    const [diagKeyword, setDiagKeyword] = useState('');
    const [activeKeyword, setActiveKeyword] = useState(''); // SeoDiagnosisSection로 전달되는 확정 키워드

    /* ---------- 생성 ---------- */
    const [genKeyword, setGenKeyword] = useState('');
    const [brand, setBrand] = useState('');
    const [category, setCategory] = useState('');
    const [features, setFeatures] = useState('');
    const [genLoading, setGenLoading] = useState(false);
    const [genResult, setGenResult] = useState(null);

    const copy = function(text) {
        try {
            navigator.clipboard.writeText(text);
            if (window.toast && toast.success) toast.success('복사되었습니다');
            else if (window.toast && toast.info) toast.info('복사되었습니다');
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
            var res = await api.post('/seo/generate', {
                keyword: kw, brand: brand || '', category: category || '', features: features || ''
            });
            if (res && res.success) setGenResult(res.data);
            else if (window.toast) toast.warn((res && res.detail) || 'SEO 생성에 실패했습니다.');
        } catch (e) {
            if (window.toast) toast.warn('SEO 생성 요청 실패 — 잠시 후 다시 시도해주세요.');
        }
        setGenLoading(false);
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
                <div style={{ color: '#64748b', fontSize: 13 }}>네이버 쇼핑 검색 노출에 맞춰 상품 SEO를 진단하고, AI로 최적화된 상품명·태그·카테고리를 생성합니다.</div>
            </div>

            {/* 모드 전환 */}
            <div style={{ display: 'flex', gap: 10, marginBottom: 18 }}>
                <button style={tabBtn(mode === 'diagnose')} onClick={function(){ setMode('diagnose'); }}>🩺 SEO 진단·점검</button>
                <button style={tabBtn(mode === 'generate')} onClick={function(){ setMode('generate'); }}>✨ SEO 생성</button>
            </div>

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
                                <input className="form-input" placeholder="예: 메타인크" value={brand}
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
                            네이버 상위 노출 상품을 참고해 AI가 최적화된 상품명·태그·카테고리를 제안합니다.
                        </div>
                    </div>

                    {genLoading && React.createElement(window.LoadingSpinner, { text: '네이버 데이터 분석 + AI 생성 중...' })}

                    {genResult && !genLoading && (
                        <div className="fade-in">
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
                                    <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 12 }}>💡 적용 근거</div>
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
                                ※ AI가 네이버 상위 노출 상품 {(genResult.context && genResult.context.sampled_titles) || 0}건을 참고해 생성한 제안입니다. 등록 전 실제 상품 정보와 맞는지 검토 후 사용하세요.
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};
