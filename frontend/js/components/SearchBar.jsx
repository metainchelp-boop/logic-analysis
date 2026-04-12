/* SearchBar — 통합 검색바 */
window.SearchBar = function SearchBar({ onSearch, loading }) {
    const { useState } = React;
    const [keyword, setKeyword] = useState('');
    const handleSubmit = (e) => {
        e.preventDefault();
        if (keyword.trim()) onSearch(keyword.trim());
    };
    return (
        <div className="search-section">
            <div className="container">
                <form onSubmit={handleSubmit} className="search-wrapper">
                    <input
                        className="search-input"
                        type="text"
                        placeholder="분석할 키워드를 입력하세요 (예: 스마트워치, 가습기, 텀블러)"
                        value={keyword}
                        onChange={e => setKeyword(e.target.value)}
                    />
                    <button className="btn-search" type="submit" disabled={loading || !keyword.trim()}>
                        {loading ? <><span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} /> 분석 중</> : '키워드 분석'}
                    </button>
                </form>
            </div>
        </div>
    );
};
