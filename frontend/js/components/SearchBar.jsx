/* SearchBar — 통합 검색바 (업체명 + 키워드 + 상품 URL 상시 노출) */
window.SearchBar = function SearchBar({ onSearch, loading, initialValues }) {
    const { useState, useEffect } = React;
    const [keyword, setKeyword] = useState('');
    const [companyName, setCompanyName] = useState('');
    const [productUrl, setProductUrl] = useState('');

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
        if (keyword.trim()) onSearch(keyword.trim(), productUrl.trim(), companyName.trim());
    };

    return (
        <div className="search-section">
            <div className="container">
                <form onSubmit={handleSubmit} className="search-wrapper" style={{ flexDirection: 'column', gap: '10px' }}>
                    {/* 업체명 + 키워드 입력 행 */}
                    <div className="search-mobile-row" style={{ display: 'flex', gap: '8px', width: '100%' }}>
                        <div className="search-field-group" style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: '200px' }}>
                            <span style={{ fontSize: '13px', color: '#94a3b8', whiteSpace: 'nowrap', fontWeight: '500', width: '60px', flexShrink: 0 }}>업체명</span>
                            <input
                                className="search-input"
                                type="text"
                                placeholder="업체명 (보고서 표지용)"
                                value={companyName}
                                onChange={e => setCompanyName(e.target.value)}
                                style={{ minWidth: '120px', maxWidth: '200px', fontSize: '13px' }}
                            />
                        </div>
                        <div className="search-field-group" style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 1 }}>
                            <span style={{ fontSize: '13px', color: '#94a3b8', whiteSpace: 'nowrap', fontWeight: '500', width: '60px', flexShrink: 0 }}>키워드</span>
                            <input
                                className="search-input"
                                type="text"
                                placeholder="분석할 키워드 (예: 스마트워치, 가습기)"
                                value={keyword}
                                onChange={e => setKeyword(e.target.value)}
                                style={{ flex: 1 }}
                            />
                        </div>
                    </div>
                    {/* 상품 URL + 버튼 행 */}
                    <div className="search-mobile-row" style={{ display: 'flex', gap: '8px', width: '100%' }}>
                        <div className="search-field-group" style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 1 }}>
                            <span style={{ fontSize: '13px', color: '#94a3b8', whiteSpace: 'nowrap', fontWeight: '500', width: '60px', flexShrink: 0 }}>상품URL</span>
                            <input
                                className="search-input"
                                type="url"
                                placeholder="광고주 상품 URL (선택사항)"
                                value={productUrl}
                                onChange={e => setProductUrl(e.target.value)}
                                style={{ flex: 1, fontSize: '13px' }}
                            />
                        </div>
                        <button className="btn-search" type="submit" disabled={loading || !keyword.trim()}>
                            {loading ? <><span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} /> 분석 중...</> : productUrl.trim() ? '상품 분석' : '키워드 분석'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};
