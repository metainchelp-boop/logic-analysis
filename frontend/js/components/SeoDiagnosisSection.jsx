/* SeoDiagnosisSection — SEO 종합 진단 (10개 평가지표) + 상세페이지 품질 진단 (HTML 직접 업로드 방식 + 북마클릿) */
window.SeoDiagnosisSection = function SeoDiagnosisSection({ keyword, productUrl: parentProductUrl, competitorData }) {
    const { useState, useEffect, useRef } = React;
    const [productUrl, setProductUrl] = useState('');
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);

    /* ── 상세페이지 진단 상태 (HTML 업로드 방식) ── */
    const [dpHtml, setDpHtml] = useState('');
    const [dpFileName, setDpFileName] = useState('');
    const [dpResult, setDpResult] = useState(null);
    const [dpLoading, setDpLoading] = useState(false);
    const [dpError, setDpError] = useState('');
    const [showPasteModal, setShowPasteModal] = useState(false);
    const [pasteValue, setPasteValue] = useState('');
    const [showHelp, setShowHelp] = useState(false);
    const [dragOver, setDragOver] = useState(false);
    const fileInputRef = useRef(null);

    const autoTriggered = useRef(false);

    useEffect(function() {
        if (parentProductUrl) setProductUrl(parentProductUrl);
    }, [parentProductUrl]);

    useEffect(function() {
        if (keyword && productUrl && !autoTriggered.current && !result && !loading) {
            autoTriggered.current = true;
            handleAnalyze();
        }
    }, [keyword, productUrl]);

    useEffect(function() {
        autoTriggered.current = false;
        setResult(null);
        setDpResult(null);
        setDpError('');
        setDpHtml('');
        setDpFileName('');
    }, [keyword]);

    const handleAnalyze = async () => {
        if (!productUrl || !keyword) return;
        setLoading(true);
        try {
            const res = await api.post('/seo/analyze', { product_url: productUrl, keyword });
            if (res.success) setResult(res.data);
            else alert(res.detail || 'SEO 분석 실패');
        } catch (e) { alert('SEO 분석 실패: ' + e.message); }
        setLoading(false);
    };

    /* ── 파일 처리 (업로드 & 드래그앤드롭 공통) ── */
    const processFile = (file) => {
        if (!file) return;
        setDpError('');
        if (file.size > 10 * 1024 * 1024) {
            setDpError('파일이 너무 큽니다 (최대 10MB).');
            return;
        }
        const name = (file.name || '').toLowerCase();
        if (name && !name.endsWith('.html') && !name.endsWith('.htm') && !name.endsWith('.mhtml') && !name.endsWith('.txt')) {
            if (!confirm('.html/.htm 파일이 아닌 것 같습니다. 계속하시겠습니까?')) return;
        }
        const reader = new FileReader();
        reader.onload = function(ev) {
            setDpHtml(ev.target.result || '');
            setDpFileName(file.name || '(파일)');
        };
        reader.onerror = function() {
            setDpError('파일을 읽는 중 오류가 발생했습니다.');
        };
        reader.readAsText(file, 'UTF-8');
    };

    const handleFileChange = (e) => {
        const file = e.target.files && e.target.files[0];
        processFile(file);
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setDragOver(false);
        const file = e.dataTransfer.files && e.dataTransfer.files[0];
        processFile(file);
    };

    const handleClearHtml = () => {
        setDpHtml('');
        setDpFileName('');
        setDpResult(null);
        setDpError('');
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const handlePasteSubmit = () => {
        if (!pasteValue || pasteValue.length < 100) {
            alert('HTML 내용이 너무 짧습니다 (최소 100자).');
            return;
        }
        setDpHtml(pasteValue);
        setDpFileName('(붙여넣기)');
        setDpError('');
        setShowPasteModal(false);
        setPasteValue('');
    };

    const runDetailAnalysis = async () => {
        if (!dpHtml || dpHtml.length < 100) {
            setDpError('HTML 내용이 비어있거나 너무 짧습니다. 업로드 또는 붙여넣기로 HTML을 입력해주세요.');
            return;
        }
        setDpLoading(true);
        setDpError('');
        try {
            const res = await api.post('/seo/detail-page', { html: dpHtml, product_url: productUrl || '' });
            if (res.success) {
                setDpResult(res.data);
            } else {
                setDpError(res.detail || '상세페이지 분석에 실패했습니다.');
            }
        } catch (e) {
            setDpError('상세페이지 분석 오류: ' + e.message);
        }
        setDpLoading(false);
    };

    /* ── 북마클릿: 스마트스토어 페이지에서 클릭하면 HTML을 클립보드에 복사 ── */
    const bookmarkletCode = "javascript:(function(){try{var h=document.documentElement.outerHTML;navigator.clipboard.writeText(h).then(function(){alert('✅ HTML '+Math.round(h.length/1024)+'KB 복사 완료!\\n\\n로직분석 페이지의 \"📋 HTML 붙여넣기\" 버튼을 눌러 붙여넣으세요.');}).catch(function(e){var t=document.createElement('textarea');t.value=h;document.body.appendChild(t);t.select();document.execCommand('copy');document.body.removeChild(t);alert('✅ HTML '+Math.round(h.length/1024)+'KB 복사 완료! 로직분석에 붙여넣으세요.');});}catch(e){alert('❌ 복사 실패: '+e.message);}})();";

    /* ── 공통 유틸 (scoreColor, scoreBg → utils.js 전역 사용) ── */
    const scoreLabel = (s) => s >= 70 ? '양호' : s >= 40 ? '보통' : '개선필요';
    const scoreGradient = (s) => s >= 70 ? 'linear-gradient(90deg, #34d399, #059669)' : s >= 40 ? 'linear-gradient(90deg, #fbbf24, #d97706)' : 'linear-gradient(90deg, #f87171, #dc2626)';
    const priorityColor = (p) => p === 'high' ? '#dc2626' : p === 'medium' ? '#d97706' : '#6b7280';
    const priorityBg = (p) => p === 'high' ? '#fef2f2' : p === 'medium' ? '#fffbeb' : '#f9fafb';
    const priorityLabel = (p) => p === 'high' ? '긴급' : p === 'medium' ? '권장' : '선택';
    const dpScoreLabel = (s) => s >= 70 ? '우수' : s >= 40 ? '보통' : '미흡';

    const ScoreBar = ({ label, score, icon, weight }) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
            <span style={{ fontSize: 16, width: 24, textAlign: 'center' }}>{icon}</span>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#334155', width: 90, flexShrink: 0 }}>{label}</span>
            <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 6, height: 22, position: 'relative', overflow: 'hidden' }}>
                <div style={{
                    width: score + '%', height: '100%',
                    background: scoreGradient(score),
                    borderRadius: 6, transition: 'width 0.8s ease'
                }} />
                <span style={{ position: 'absolute', right: 8, top: 2, fontSize: 11, fontWeight: 700, color: '#1e293b' }}>{score}점</span>
            </div>
            <span style={{ fontSize: 11, color: '#94a3b8', width: 36, textAlign: 'right', flexShrink: 0 }}>{weight}</span>
        </div>
    );

    const htmlPreviewKB = dpHtml ? (new Blob([dpHtml]).size / 1024).toFixed(1) : 0;

    return (
        <div className="section fade-in" id="sec-seo">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: '#faf5ff' }}>🏥</span>
                    SEO 종합 진단
                </div>

                <div className="card" style={{ marginBottom: 16 }}>
                    <div style={{ display: 'flex', gap: 10 }}>
                        <input className="form-input" placeholder="분석할 상품 URL을 입력하세요" value={productUrl} onChange={e => setProductUrl(e.target.value)} style={{ flex: 1 }} />
                        <button className="btn btn-primary" onClick={handleAnalyze} disabled={loading || !productUrl || !keyword}>
                            {loading ? '분석 중...' : 'SEO 진단'}
                        </button>
                    </div>
                    {keyword && <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>기준 키워드: <strong>{keyword}</strong></div>}
                </div>

                {loading && <LoadingSpinner text="SEO 분석 중..." />}

                {result && !loading && (
                    <div className="fade-in">
                        {/* 종합 점수 대형 카드 */}
                        <div className="card" style={{ textAlign: 'center', marginBottom: 16, padding: '24px 20px', background: scoreBg(result.scores.total) }}>
                            <div style={{ fontSize: 14, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>SEO 종합 점수</div>
                            <div style={{
                                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                width: 80, height: 80, borderRadius: '50%',
                                background: '#fff', border: '4px solid ' + scoreColor(result.scores.total),
                                fontSize: 28, fontWeight: 800, color: scoreColor(result.scores.total)
                            }}>
                                {result.scores.total}
                            </div>
                            <div style={{ marginTop: 8, fontSize: 14, fontWeight: 700, color: scoreColor(result.scores.total) }}>
                                {scoreLabel(result.scores.total)}
                            </div>
                            {result.scores.detail?.current_rank && (
                                <div style={{ marginTop: 4, fontSize: 12, color: '#64748b' }}>
                                    현재 순위: {result.scores.detail.current_rank}위 | 추정 월 판매: {(result.scores.detail.est_monthly_sales || 0).toLocaleString()}건
                                </div>
                            )}
                        </div>

                        {/* 경쟁사 비교표는 container 밖에서 렌더링 (너비 맞춤) */}

                        {/* 10개 지표 상세 바 차트 */}
                        <div className="card" style={{ marginBottom: 16 }}>
                            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span>📊 평가지표 상세</span>
                                <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>비중</span>
                            </div>
                            <ScoreBar label="상품명" score={result.scores.title} icon="📝" weight="15%" />
                            <ScoreBar label="검색 순위" score={result.scores.rank} icon="📈" weight="15%" />
                            <ScoreBar label="가격 경쟁력" score={result.scores.price} icon="💰" weight="12%" />
                            <ScoreBar label="리뷰 수" score={result.scores.review || 0} icon="💬" weight="12%" />
                            <ScoreBar label="판매실적" score={result.scores.sales || 0} icon="🛒" weight="10%" />
                            <ScoreBar label="상품 평점" score={result.scores.rating || 0} icon="⭐" weight="8%" />
                            <ScoreBar label="카테고리" score={result.scores.category || 0} icon="📂" weight="8%" />
                            <ScoreBar label="브랜드" score={result.scores.brand || 0} icon="🏷️" weight="8%" />
                            <ScoreBar label="네이버페이" score={result.scores.naverpay || 0} icon="💳" weight="6%" />
                            <ScoreBar label="최신성" score={result.scores.freshness || 0} icon="🕐" weight="6%" />
                        </div>

                        {/* 세부 정보 요약 */}
                        {result.scores.detail && (
                            <div className="card-grid card-grid-4" style={{ marginBottom: 16 }}>
                                {[
                                    { label: '키워드 포함', value: result.scores.detail.keyword_in_title ? '포함 ✅' : '미포함 ❌', icon: '🔤' },
                                    { label: '가격 비율', value: result.scores.detail.price_ratio > 0 ? (result.scores.detail.price_ratio * 100).toFixed(0) + '%' : (result.scores.detail.my_price > 0 ? '비교불가' : '가격없음'), icon: '💲' },
                                    { label: '추정 리뷰', value: (result.scores.detail.est_reviews || 0).toLocaleString() + '개', icon: '💬' },
                                    { label: '추정 평점', value: result.scores.detail.est_rating ? result.scores.detail.est_rating.toFixed(1) : '-', icon: '⭐' },
                                ].map((item, i) => (
                                    <div className="card" key={i} style={{ textAlign: 'center', padding: '12px 8px' }}>
                                        <div style={{ fontSize: 18, marginBottom: 4 }}>{item.icon}</div>
                                        <div style={{ fontSize: 16, fontWeight: 700, color: '#1e293b' }}>{item.value}</div>
                                        <div style={{ fontSize: 11, color: '#64748b' }}>{item.label}</div>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* 개선 제안 */}
                        {result.suggestions?.length > 0 && (
                            <div className="card">
                                <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10 }}>💡 개선 제안</div>
                                {result.suggestions.map((s, i) => (
                                    <div key={i} style={{ padding: '8px 0', borderBottom: i < result.suggestions.length - 1 ? '1px solid #f1f5f9' : 'none', fontSize: 13, color: '#334155', display: 'flex', gap: 8 }}>
                                        <span style={{ color: '#3b82f6', flexShrink: 0 }}>•</span>{s}
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* 산출 근거 안내 */}
                        <div style={{ marginTop: 12, padding: '10px 14px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 11, color: '#94a3b8', lineHeight: 1.7 }}>
                            ※ 리뷰 수·평점·판매실적·최신성은 순위 구간별 업계 평균 기반 추정치입니다. 네이버 쇼핑 API 한계로 실제 수치와 차이가 있을 수 있으며, 향후 정밀화 예정입니다.
                        </div>
                    </div>
                )}

                {/* ================================================================ */}
                {/* ========== 상세페이지 품질 진단 (HTML 직접 업로드) ========== */}
                {/* ================================================================ */}
                <div style={{ marginTop: 24 }}>
                    {/* 헤더 */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span style={{ fontSize: 20, background: '#fef3c7', borderRadius: 8, padding: '4px 8px' }}>📄</span>
                            <div>
                                <div style={{ fontWeight: 700, fontSize: 15, color: '#1e293b' }}>상세페이지 품질 진단</div>
                                <div style={{ fontSize: 11, color: '#94a3b8' }}>스마트스토어 HTML 직접 분석 (네이버 봇차단 우회)</div>
                            </div>
                        </div>
                        <button
                            className="btn"
                            onClick={() => setShowHelp(!showHelp)}
                            style={{ fontSize: 12, padding: '4px 12px', background: '#e0e7ff', color: '#3730a3', margin: 0 }}
                        >
                            {showHelp ? '도움말 접기' : '❓ 어떻게 쓰나요?'}
                        </button>
                    </div>

                    {/* 🔖 북마클릿 (가장 쉬운 방법) */}
                    <div className="card" style={{ marginBottom: 12, background: '#eff6ff', border: '1px solid #bfdbfe' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                            <span style={{ fontSize: 20 }}>🔖</span>
                            <div style={{ flex: 1 }}>
                                <div style={{ fontSize: 13, fontWeight: 700, color: '#1e40af' }}>★ 가장 쉬운 방법: 북마클릿 사용</div>
                                <div style={{ fontSize: 11, color: '#3730a3' }}>아래 버튼을 북마크바로 <strong>드래그</strong> → 스마트스토어에서 클릭 한 번에 HTML 복사</div>
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                            <a
                                href={bookmarkletCode}
                                onClick={(e) => { e.preventDefault(); alert('이 버튼을 클릭하지 말고, 브라우저 북마크바로 드래그해서 놓으세요!\n\n북마크바가 안 보이면 Chrome에서 ⌘+Shift+B (Mac) / Ctrl+Shift+B (Windows) 로 표시할 수 있습니다.'); }}
                                draggable="true"
                                style={{
                                    display: 'inline-block', padding: '8px 16px',
                                    background: '#1e40af', color: '#fff', fontWeight: 700, fontSize: 13,
                                    borderRadius: 6, textDecoration: 'none', cursor: 'grab',
                                    boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
                                }}
                            >
                                📎 HTML 복사 (북마크바로 드래그)
                            </a>
                            <span style={{ fontSize: 11, color: '#64748b' }}>
                                ← 이 파란 버튼을 위쪽 북마크바에 끌어다 놓으세요
                            </span>
                        </div>
                    </div>

                    {/* 도움말 (토글) */}
                    {showHelp && (
                        <div className="card" style={{ marginBottom: 12, background: '#fefce8', border: '1px solid #fde68a' }}>
                            <div style={{ fontSize: 13, fontWeight: 700, color: '#92400e', marginBottom: 10 }}>
                                📘 HTML 입력 방법 3가지 (편한 것 선택)
                            </div>

                            <div style={{ marginBottom: 12, padding: 10, background: '#fff', borderRadius: 6 }}>
                                <div style={{ fontSize: 12, fontWeight: 700, color: '#1e40af', marginBottom: 6 }}>방법 1: 북마클릿 (추천, 5초)</div>
                                <ol style={{ fontSize: 11, color: '#475569', lineHeight: 1.7, paddingLeft: 18, margin: 0 }}>
                                    <li>위 파란 <strong>"HTML 복사" 버튼을 북마크바로 드래그</strong> (최초 1회만)</li>
                                    <li>스마트스토어 상품 페이지 접속</li>
                                    <li>북마크바에서 방금 추가한 버튼 클릭 → "복사 완료" 알림</li>
                                    <li>이 페이지로 돌아와서 <strong>"📋 HTML 붙여넣기"</strong> 버튼 클릭 → 붙여넣기</li>
                                </ol>
                            </div>

                            <div style={{ marginBottom: 12, padding: 10, background: '#fff', borderRadius: 6 }}>
                                <div style={{ fontSize: 12, fontWeight: 700, color: '#059669', marginBottom: 6 }}>방법 2: 페이지 소스 복사 (⌘+U / Ctrl+U)</div>
                                <ol style={{ fontSize: 11, color: '#475569', lineHeight: 1.7, paddingLeft: 18, margin: 0 }}>
                                    <li>스마트스토어 상품 페이지 접속</li>
                                    <li><kbd style={{ background: '#f1f5f9', padding: '1px 6px', borderRadius: 3, border: '1px solid #cbd5e1', fontSize: 10 }}>⌘ + U</kbd> (Mac) 또는 <kbd style={{ background: '#f1f5f9', padding: '1px 6px', borderRadius: 3, border: '1px solid #cbd5e1', fontSize: 10 }}>Ctrl + U</kbd> (Windows) → 새 탭에 소스 열림</li>
                                    <li><kbd style={{ background: '#f1f5f9', padding: '1px 6px', borderRadius: 3, border: '1px solid #cbd5e1', fontSize: 10 }}>⌘ + A</kbd> → <kbd style={{ background: '#f1f5f9', padding: '1px 6px', borderRadius: 3, border: '1px solid #cbd5e1', fontSize: 10 }}>⌘ + C</kbd> (전체 선택 후 복사)</li>
                                    <li>이 페이지로 돌아와서 <strong>"📋 HTML 붙여넣기"</strong> 클릭</li>
                                </ol>
                            </div>

                            <div style={{ padding: 10, background: '#fff', borderRadius: 6 }}>
                                <div style={{ fontSize: 12, fontWeight: 700, color: '#7c3aed', marginBottom: 6 }}>방법 3: 개발자도구 outerHTML 복사</div>
                                <ol style={{ fontSize: 11, color: '#475569', lineHeight: 1.7, paddingLeft: 18, margin: 0 }}>
                                    <li>스마트스토어 상품 페이지에서 <kbd style={{ background: '#f1f5f9', padding: '1px 6px', borderRadius: 3, border: '1px solid #cbd5e1', fontSize: 10 }}>F12</kbd> 또는 우클릭 → "검사"</li>
                                    <li>Elements 탭 맨 위 <code style={{ background: '#f1f5f9', padding: '1px 4px', borderRadius: 3, fontSize: 11 }}>&lt;html&gt;</code> 우클릭</li>
                                    <li>Copy → <strong>Copy outerHTML</strong> 클릭</li>
                                    <li>이 페이지에서 <strong>"📋 HTML 붙여넣기"</strong> 클릭</li>
                                </ol>
                            </div>
                        </div>
                    )}

                    {/* 드래그앤드롭 영역 */}
                    <div
                        className="card"
                        style={{
                            marginBottom: 16,
                            border: dragOver ? '2px dashed #3b82f6' : '2px dashed #cbd5e1',
                            background: dragOver ? '#eff6ff' : '#f8fafc',
                            transition: 'all 0.2s'
                        }}
                        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                        onDragLeave={() => setDragOver(false)}
                        onDrop={handleDrop}
                    >
                        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                            <input
                                ref={fileInputRef}
                                type="file"
                                accept=".html,.htm,.mhtml,.txt"
                                onChange={handleFileChange}
                                style={{ display: 'none' }}
                                id="dp-html-file-input"
                            />
                            <label htmlFor="dp-html-file-input" className="btn btn-primary" style={{ cursor: 'pointer', margin: 0 }}>
                                📁 HTML 파일 선택
                            </label>
                            <button className="btn btn-secondary" onClick={() => { setPasteValue(''); setShowPasteModal(true); }} style={{ margin: 0 }}>
                                📋 HTML 붙여넣기
                            </button>
                            {dpHtml && (
                                <button className="btn" onClick={handleClearHtml} style={{ margin: 0, background: '#f1f5f9', color: '#475569' }}>
                                    🗑️ 초기화
                                </button>
                            )}
                            <button
                                className="btn btn-primary"
                                onClick={runDetailAnalysis}
                                disabled={dpLoading || !dpHtml}
                                style={{ margin: 0, marginLeft: 'auto' }}
                            >
                                {dpLoading ? '분석 중...' : (dpResult ? '재분석' : '분석 시작')}
                            </button>
                        </div>
                        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 10, textAlign: 'center' }}>
                            💡 HTML 파일을 이 영역으로 <strong>끌어다 놓기</strong>도 가능합니다
                        </div>

                        {/* 업로드 상태 표시 */}
                        {dpHtml && (
                            <div style={{
                                marginTop: 12, padding: '10px 14px', background: '#ecfdf5',
                                borderRadius: 8, border: '1px solid #a7f3d0',
                                display: 'flex', alignItems: 'center', gap: 10, fontSize: 13
                            }}>
                                <span style={{ fontSize: 18 }}>✅</span>
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontWeight: 600, color: '#065f46' }}>{dpFileName || '업로드 완료'}</div>
                                    <div style={{ fontSize: 11, color: '#047857' }}>크기: {htmlPreviewKB} KB ({dpHtml.length.toLocaleString()}자)</div>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* 로딩 */}
                    {dpLoading && (
                        <div className="card" style={{ textAlign: 'center', padding: '32px 20px' }}>
                            <LoadingSpinner text="상세페이지 분석 중..." />
                        </div>
                    )}

                    {/* 에러 */}
                    {dpError && !dpLoading && (
                        <div className="card" style={{ background: '#fef2f2', border: '1px solid #fecaca', padding: '14px 18px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#dc2626', fontSize: 13, fontWeight: 600 }}>
                                <span>⚠️</span> {dpError}
                            </div>
                        </div>
                    )}

                    {/* 결과 표시 */}
                    {dpResult && !dpLoading && (
                        <div className="fade-in">
                            {/* 종합 점수 대형 카드 */}
                            <div className="card" style={{ textAlign: 'center', marginBottom: 16, padding: '20px', background: scoreBg(dpResult.scores.total) }}>
                                <div style={{ fontSize: 13, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>상세페이지 종합 점수</div>
                                <div style={{
                                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                    width: 72, height: 72, borderRadius: '50%',
                                    background: '#fff', border: '4px solid ' + scoreColor(dpResult.scores.total),
                                    fontSize: 26, fontWeight: 800, color: scoreColor(dpResult.scores.total)
                                }}>
                                    {dpResult.scores.total}
                                </div>
                                <div style={{ marginTop: 6, fontSize: 13, fontWeight: 700, color: scoreColor(dpResult.scores.total) }}>
                                    {dpScoreLabel(dpResult.scores.total)}
                                </div>
                            </div>

                            {/* 5대 영역 점수 바 차트 */}
                            <div className="card" style={{ marginBottom: 16 }}>
                                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12, display: 'flex', justifyContent: 'space-between' }}>
                                    <span>📊 영역별 점수</span>
                                    <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>비중</span>
                                </div>
                                {[
                                    { label: '이미지', score: dpResult.scores.images, icon: '🖼️', weight: '30%' },
                                    { label: '텍스트 콘텐츠', score: dpResult.scores.text, icon: '📝', weight: '20%' },
                                    { label: '동영상', score: dpResult.scores.video, icon: '🎬', weight: '15%' },
                                    { label: '정보 완성도', score: dpResult.scores.info, icon: '📋', weight: '20%' },
                                    { label: '신뢰 요소', score: dpResult.scores.trust, icon: '🛡️', weight: '15%' },
                                ].map((item, i) => (
                                    <div key={'dp-bar-'+i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: i < 4 ? '1px solid #f1f5f9' : 'none' }}>
                                        <span style={{ fontSize: 16, width: 24, textAlign: 'center' }}>{item.icon}</span>
                                        <span style={{ fontSize: 13, fontWeight: 600, color: '#334155', width: 100, flexShrink: 0 }}>{item.label}</span>
                                        <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 6, height: 22, position: 'relative', overflow: 'hidden' }}>
                                            <div style={{
                                                width: item.score + '%', height: '100%',
                                                background: scoreGradient(item.score),
                                                borderRadius: 6, transition: 'width 0.8s ease'
                                            }} />
                                            <span style={{ position: 'absolute', right: 8, top: 2, fontSize: 11, fontWeight: 700, color: '#1e293b' }}>{item.score}점</span>
                                        </div>
                                        <span style={{ fontSize: 11, color: '#94a3b8', width: 36, textAlign: 'right', flexShrink: 0 }}>{item.weight}</span>
                                    </div>
                                ))}
                            </div>

                            {/* 주요 지표 카드 그리드 */}
                            <div className="card-grid card-grid-4" style={{ marginBottom: 16 }}>
                                {[
                                    { label: '상품 이미지', value: dpResult.metrics.total_images + '장', icon: '🖼️', good: dpResult.metrics.total_images >= 10 },
                                    { label: '텍스트 길이', value: dpResult.metrics.text_length > 1000 ? (dpResult.metrics.text_length / 1000).toFixed(1) + 'K자' : dpResult.metrics.text_length + '자', icon: '📝', good: dpResult.metrics.text_length >= 500 },
                                    { label: '동영상', value: dpResult.metrics.video_count + '개', icon: '🎬', good: dpResult.metrics.video_count > 0 },
                                    { label: '페이지 크기', value: dpResult.metrics.html_size_kb + 'KB', icon: '📦', good: dpResult.metrics.html_size_kb >= 50 },
                                ].map((item, i) => (
                                    <div className="card" key={'dp-metric-'+i} style={{ textAlign: 'center', padding: '12px 8px' }}>
                                        <div style={{ fontSize: 18, marginBottom: 4 }}>{item.icon}</div>
                                        <div style={{ fontSize: 16, fontWeight: 700, color: item.good ? '#059669' : '#dc2626' }}>{item.value}</div>
                                        <div style={{ fontSize: 11, color: '#64748b' }}>{item.label}</div>
                                    </div>
                                ))}
                            </div>

                            {/* 체크리스트 (불리언 항목) */}
                            <div className="card" style={{ marginBottom: 16 }}>
                                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>✅ 필수 항목 체크리스트</div>
                                {[
                                    { label: '배송 정보 (무료배송/당일출고)', checked: dpResult.metrics.has_delivery_info },
                                    { label: '교환/반품/환불 정책', checked: dpResult.metrics.has_return_info },
                                    { label: '사은품/증정 혜택', checked: dpResult.metrics.has_gift_info },
                                    { label: '인증/수상/특허 표시', checked: dpResult.metrics.has_certification },
                                    { label: '구매 후기/리뷰 섹션', checked: dpResult.metrics.has_review_section },
                                    { label: '스펙/사양 테이블', checked: dpResult.metrics.has_spec_table },
                                ].map((item, i) => (
                                    <div key={'dp-check-'+i} style={{
                                        display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0',
                                        borderBottom: i < 5 ? '1px solid #f1f5f9' : 'none'
                                    }}>
                                        <span style={{
                                            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                            width: 22, height: 22, borderRadius: '50%', fontSize: 12,
                                            background: item.checked ? '#ecfdf5' : '#fef2f2',
                                            color: item.checked ? '#059669' : '#dc2626',
                                            border: '1px solid ' + (item.checked ? '#a7f3d0' : '#fecaca')
                                        }}>
                                            {item.checked ? '✓' : '✗'}
                                        </span>
                                        <span style={{ fontSize: 13, color: item.checked ? '#334155' : '#94a3b8', fontWeight: item.checked ? 500 : 400 }}>
                                            {item.label}
                                        </span>
                                        <span style={{
                                            marginLeft: 'auto', fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
                                            background: item.checked ? '#ecfdf5' : '#fef2f2',
                                            color: item.checked ? '#059669' : '#dc2626'
                                        }}>
                                            {item.checked ? '확인됨' : '미확인'}
                                        </span>
                                    </div>
                                ))}
                            </div>

                            {/* 개선 제안 (우선순위별) */}
                            {dpResult.suggestions && dpResult.suggestions.length > 0 && (
                                <div className="card" style={{ marginBottom: 16 }}>
                                    <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>🔧 상세페이지 개선 제안</div>
                                    {dpResult.suggestions.map((s, i) => (
                                        <div key={'dp-sug-'+i} style={{
                                            padding: '12px 14px', marginBottom: i < dpResult.suggestions.length - 1 ? 10 : 0,
                                            background: priorityBg(s.priority), borderRadius: 8,
                                            border: '1px solid ' + (s.priority === 'high' ? '#fecaca' : s.priority === 'medium' ? '#fed7aa' : '#e5e7eb')
                                        }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                                <span style={{
                                                    fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
                                                    background: priorityColor(s.priority), color: '#fff'
                                                }}>
                                                    {priorityLabel(s.priority)}
                                                </span>
                                                <span style={{ fontSize: 13, fontWeight: 600, color: '#334155' }}>{s.area}</span>
                                            </div>
                                            <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.7 }}>{s.text}</div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {/* 분석 안내 */}
                            <div style={{ padding: '10px 14px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 11, color: '#94a3b8', lineHeight: 1.7 }}>
                                ※ 상세페이지 분석은 사용자가 업로드한 HTML을 직접 파싱하여 수행합니다. 네이버의 봇 차단으로 서버측 크롤링이 불가능하여 이 방식을 사용합니다.
                            </div>
                        </div>
                    )}
                </div>

                {/* ── HTML 붙여넣기 모달 ── */}
                {showPasteModal && (
                    <div style={{
                        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                        background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        zIndex: 9999, padding: 20
                    }} onClick={() => setShowPasteModal(false)}>
                        <div style={{
                            background: '#fff', borderRadius: 12, padding: 24,
                            maxWidth: 800, width: '100%', maxHeight: '80vh', display: 'flex', flexDirection: 'column'
                        }} onClick={(e) => e.stopPropagation()}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                                <div style={{ fontSize: 16, fontWeight: 700 }}>📋 HTML 붙여넣기</div>
                                <button onClick={() => setShowPasteModal(false)} style={{
                                    border: 'none', background: 'transparent', fontSize: 20, cursor: 'pointer', color: '#64748b'
                                }}>✕</button>
                            </div>
                            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>
                                복사한 HTML을 아래 칸에 붙여넣으세요 (⌘+V / Ctrl+V). 최소 100자 이상이어야 합니다.
                            </div>
                            <textarea
                                value={pasteValue}
                                onChange={(e) => setPasteValue(e.target.value)}
                                placeholder="여기에 HTML을 붙여넣으세요..."
                                style={{
                                    flex: 1, minHeight: 300, width: '100%', padding: 12,
                                    border: '1px solid #cbd5e1', borderRadius: 8, fontSize: 12,
                                    fontFamily: 'monospace', resize: 'vertical'
                                }}
                                autoFocus
                            />
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
                                <div style={{ fontSize: 11, color: '#64748b' }}>
                                    {pasteValue ? `${pasteValue.length.toLocaleString()}자 (${(new Blob([pasteValue]).size / 1024).toFixed(1)}KB)` : '비어있음'}
                                </div>
                                <div style={{ display: 'flex', gap: 8 }}>
                                    <button className="btn" onClick={() => setShowPasteModal(false)} style={{ margin: 0, background: '#f1f5f9', color: '#475569' }}>
                                        취소
                                    </button>
                                    <button className="btn btn-primary" onClick={handlePasteSubmit} disabled={!pasteValue || pasteValue.length < 100} style={{ margin: 0 }}>
                                        확인
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

            </div>

            {/* 경쟁사 비교표 — container 밖에서 렌더링하여 다른 섹터와 동일 너비 */}
            {competitorData && React.createElement('div', { id: 'sec-competitor' },
                React.createElement(CompetitorTableSection, { data: competitorData })
            )}
        </div>
    );
};
