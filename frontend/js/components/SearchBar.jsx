/* SearchBar — 통합 검색바 (업체명 + 키워드 + 상품 URL + HTML 붙여넣기 + 북마클릿) */
window.SearchBar = function SearchBar({ onSearch, loading, initialValues }) {
    const { useState, useEffect, useRef } = React;
    const [keyword, setKeyword] = useState('');
    const [companyName, setCompanyName] = useState('');
    const [productUrl, setProductUrl] = useState('');
    const [htmlInput, setHtmlInput] = useState('');
    const [htmlExpanded, setHtmlExpanded] = useState(false);

    /* 북마클릿: 스마트스토어에서 클릭하면 HTML을 클립보드에 복사 */
    const bookmarkletCode = "javascript:(function(){try{var h=document.documentElement.outerHTML;navigator.clipboard.writeText(h).then(function(){alert('\\u2705 HTML '+Math.round(h.length/1024)+'KB \\ubcf5\\uc0ac \\uc644\\ub8cc!\\n\\n\\ub85c\\uc9c1\\ubd84\\uc11d \\ud398\\uc774\\uc9c0\\uc758 HTML \\ubd99\\uc5ec\\ub123\\uae30 \\uce78\\uc5d0 \\ubd99\\uc5ec\\ub123\\uc73c\\uc138\\uc694.');}).catch(function(e){var t=document.createElement('textarea');t.value=h;document.body.appendChild(t);t.select();document.execCommand('copy');document.body.removeChild(t);alert('\\u2705 HTML '+Math.round(h.length/1024)+'KB \\ubcf5\\uc0ac \\uc644\\ub8cc! \\ub85c\\uc9c1\\ubd84\\uc11d\\uc5d0 \\ubd99\\uc5ec\\ub123\\uc73c\\uc138\\uc694.');});}catch(e){alert('\\u274c \\ubcf5\\uc0ac \\uc2e4\\ud328: '+e.message);}})();";

    /* 외부에서 초기값 전달 시 입력 필드 업데이트 (업체 카드 클릭 시 사용) */
    useEffect(function() {
        if (initialValues && typeof initialValues === 'object') {
            if (typeof initialValues.keyword === 'string') setKeyword(initialValues.keyword);
            if (typeof initialValues.companyName === 'string') setCompanyName(initialValues.companyName);
            if (typeof initialValues.productUrl === 'string') setProductUrl(initialValues.productUrl);
        }
    }, [initialValues]);

    const handleSubmit = (e) => {
        e.preventDefault();
        if (keyword.trim()) onSearch(keyword.trim(), productUrl.trim(), companyName.trim(), htmlInput.trim() || null);
    };

    const htmlSizeKB = htmlInput ? (new Blob([htmlInput]).size / 1024).toFixed(1) : 0;

    return (
        <div className="search-section">
            <div className="container">
                <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {/* 1행: 업체명 + 키워드 + 상품URL */}
                    <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr 1fr', gap: '10px', alignItems: 'end' }}>
                        <div>
                            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4, letterSpacing: '0.02em' }}>업체명</label>
                            <input
                                className="search-input"
                                type="text"
                                placeholder="보고서 표지용"
                                value={companyName}
                                onChange={e => setCompanyName(e.target.value)}
                                style={{ width: '100%', fontSize: 13 }}
                            />
                        </div>
                        <div>
                            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4, letterSpacing: '0.02em' }}>키워드</label>
                            <input
                                className="search-input"
                                type="text"
                                placeholder="분석할 키워드 (예: 무선 이어폰)"
                                value={keyword}
                                onChange={e => setKeyword(e.target.value)}
                                style={{ width: '100%' }}
                            />
                        </div>
                        <div>
                            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4, letterSpacing: '0.02em' }}>상품 URL (선택)</label>
                            <input
                                className="search-input"
                                type="url"
                                placeholder="광고주 상품 URL"
                                value={productUrl}
                                onChange={e => setProductUrl(e.target.value)}
                                style={{ width: '100%', fontSize: 12 }}
                            />
                        </div>
                    </div>

                    {/* 2행: HTML 붙여넣기 + 북마클릿 + 분석 버튼 */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '10px', alignItems: 'end' }}>
                        <div>
                            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4, letterSpacing: '0.02em' }}>
                                HTML 붙여넣기
                                <span style={{ display: 'inline-block', background: '#ecfdf5', color: '#059669', fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 10, marginLeft: 6, verticalAlign: 'middle' }}>NEW</span>
                                <span style={{ fontSize: 10, color: '#94a3b8', fontWeight: 400, marginLeft: 6 }}>상세페이지 HTML → 실제 리뷰수/평점/찜수 추출</span>
                            </label>
                            <div style={{ position: 'relative' }}>
                                <textarea
                                    placeholder="상세페이지 HTML 소스를 붙여넣으세요 (선택사항) — Ctrl+U로 소스보기 후 전체 복사"
                                    value={htmlInput}
                                    onChange={e => setHtmlInput(e.target.value)}
                                    style={{
                                        width: '100%', height: htmlExpanded ? 120 : 44,
                                        padding: '10px 14px',
                                        border: '2px solid ' + (htmlInput ? '#a7f3d0' : '#e5e7eb'),
                                        borderRadius: 10, fontSize: 12, fontFamily: 'inherit',
                                        outline: 'none', background: htmlInput ? '#f0fdf4' : '#f9fafb',
                                        resize: 'none', transition: 'all 0.2s',
                                        overflow: htmlExpanded ? 'auto' : 'hidden'
                                    }}
                                    onFocus={() => setHtmlExpanded(true)}
                                    onBlur={() => { if (!htmlInput) setHtmlExpanded(false); }}
                                />
                                {htmlInput && (
                                    <div style={{
                                        position: 'absolute', top: 8, right: 8,
                                        display: 'flex', alignItems: 'center', gap: 8
                                    }}>
                                        <span style={{ fontSize: 10, color: '#059669', fontWeight: 600, background: '#ecfdf5', padding: '2px 8px', borderRadius: 10 }}>
                                            {htmlSizeKB} KB
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() => { setHtmlInput(''); setHtmlExpanded(false); }}
                                            style={{ border: 'none', background: '#fef2f2', color: '#dc2626', fontSize: 11, padding: '2px 8px', borderRadius: 10, cursor: 'pointer', fontWeight: 600 }}
                                        >
                                            초기화
                                        </button>
                                    </div>
                                )}
                            </div>
                        </div>
                        <button className="btn-search" type="submit" disabled={loading || !keyword.trim()} style={{ height: 44, marginBottom: 0 }}>
                            {loading ? <><span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} /> 분석 중...</> : productUrl.trim() ? '상품 분석' : '키워드 분석'}
                        </button>
                    </div>

                    {/* 3행: 북마클릿 안내 (HTML 필드 바로 아래) */}
                    <div style={{
                        display: 'flex', alignItems: 'center', gap: 12,
                        padding: '8px 14px', background: '#eff6ff', borderRadius: 10,
                        border: '1px solid #bfdbfe'
                    }}>
                        <span style={{ fontSize: 16 }}>🔖</span>
                        <div style={{ flex: 1 }}>
                            <span style={{ fontSize: 12, fontWeight: 700, color: '#1e40af' }}>★ 가장 쉬운 방법: 북마클릿 사용</span>
                            <span style={{ fontSize: 11, color: '#3730a3', marginLeft: 8 }}>아래 버튼을 북마크바로 <strong>드래그</strong> → 스마트스토어에서 클릭 한 번에 HTML 복사</span>
                        </div>
                        <a
                            href={bookmarkletCode}
                            onClick={(e) => { e.preventDefault(); alert('이 버튼을 클릭하지 말고, 브라우저 북마크바로 드래그해서 놓으세요!\n\n북마크바가 안 보이면 Chrome에서 ⌘+Shift+B (Mac) / Ctrl+Shift+B (Windows) 로 표시할 수 있습니다.'); }}
                            draggable="true"
                            style={{
                                display: 'inline-block', padding: '6px 14px',
                                background: '#1e40af', color: '#fff', fontWeight: 700, fontSize: 12,
                                borderRadius: 6, textDecoration: 'none', cursor: 'grab',
                                boxShadow: '0 2px 4px rgba(0,0,0,0.1)', whiteSpace: 'nowrap', flexShrink: 0
                            }}
                        >
                            📎 HTML 복사 (북마크바로 드래그)
                        </a>
                        <span style={{ fontSize: 10, color: '#64748b', flexShrink: 0 }}>← 이 파란 버튼을 위쪽 북마크바에 끌어다 놓으세요</span>
                    </div>
                </form>
            </div>
        </div>
    );
};
