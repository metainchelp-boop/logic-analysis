/* RankCheckCard — 스토어 분석 안 「키워드별 노출 순위」 콤팩트 연동 카드 (탭 분리 1차)
 *
 * 상세 추적 UI(RankTrackingSection)는 📊 키워드 순위 탭으로 이전했고, 여기서는
 * ① 검색 컨텍스트의 1회성 순위 조회(/rank/check)를 기존과 동일하게 수행해
 *    onRankResult 로 올린다 — 진입 전략·시장 매출 섹션이 이 값을 계속 소비(무회귀).
 * ② 결과를 한 줄로 보여주고, 「키워드 순위 탭」으로 컨텍스트를 넘겨 이동한다
 *    (sessionStorage 'logic_rank_ctx' — KeywordRankPage 가 1회 소비).
 *
 * props: { searchedKeyword, searchedProductUrl, cachedProductName, relatedKeywords,
 *          onRankResult, onOpenRankTab }
 */
window.RankCheckCard = function RankCheckCard(props) {
    var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
    var searchedKeyword = props.searchedKeyword;
    var searchedProductUrl = props.searchedProductUrl;
    var onRankResult = props.onRankResult;
    var onOpenRankTab = props.onOpenRankTab;

    var _r = useState(null); var result = _r[0], setResult = _r[1];
    var _l = useState(false); var loading = _l[0], setLoading = _l[1];
    var lastKey = useRef('');

    /* 1회성 순위 조회 (DB 미저장) — RankTrackingSection 에 있던 로직 그대로 */
    useEffect(function() {
        if (!searchedKeyword || !searchedProductUrl) { setResult(null); return; }
        var key = searchedProductUrl + '::' + searchedKeyword;
        if (lastKey.current === key) return;
        lastKey.current = key;
        setLoading(true);
        setResult(null);
        api.post('/rank/check', { keyword: searchedKeyword, product_url: searchedProductUrl })
            .then(function(res) {
                if (res && res.success && res.data) {
                    setResult(res.data);
                    if (onRankResult) onRankResult(res.data);
                } else if (res && !res.success && res.detail) {
                    toast.error(res.detail);
                }
            })
            .catch(function() {})
            .finally(function() { setLoading(false); });
    }, [searchedKeyword, searchedProductUrl]);

    var openTab = function() {
        try {
            sessionStorage.setItem('logic_rank_ctx', JSON.stringify({
                searchedKeyword: searchedKeyword || '',
                searchedProductUrl: searchedProductUrl || '',
                cachedProductName: props.cachedProductName || '',
                relatedKeywords: props.relatedKeywords || []
            }));
        } catch (e) {}
        if (onOpenRankTab) onOpenRankTab();
    };

    var statusEl;
    if (loading) {
        statusEl = React.createElement('span', { style: { fontSize: 13, color: '#64748b' } }, '🔄 현재 순위 조회 중...');
    } else if (result && result.rank_position != null) {
        statusEl = React.createElement('span', { style: { fontSize: 14, fontWeight: 800, color: result.rank_position <= 10 ? '#16a34a' : '#0f172a' } },
            '현재 ' + result.rank_position + '위',
            result.page_number ? React.createElement('span', { style: { fontSize: 12, fontWeight: 600, color: '#94a3b8', marginLeft: 6 } }, result.page_number + '페이지') : null);
    } else if (result) {
        statusEl = React.createElement('span', { style: { fontSize: 13, fontWeight: 700, color: '#b45309' } }, '300위 내 미노출');
    } else if (searchedKeyword && searchedProductUrl) {
        statusEl = React.createElement('span', { style: { fontSize: 13, color: '#94a3b8' } }, '—');
    } else {
        statusEl = React.createElement('span', { style: { fontSize: 13, color: '#94a3b8' } }, '상품 URL 로 분석하면 현재 순위가 표시됩니다');
    }

    return React.createElement('div', { id: 'sec-rank', style: { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14, padding: '16px 20px', marginBottom: 16 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
            React.createElement('div', { style: { fontSize: 15, fontWeight: 800, color: '#0f172a' } }, '📊 키워드별 노출 순위'),
            searchedKeyword && React.createElement('span', { style: { fontSize: 12.5, color: '#475569', background: '#f1f5f9', borderRadius: 999, padding: '3px 10px', fontWeight: 600 } }, searchedKeyword),
            statusEl,
            React.createElement('button', {
                onClick: openTab,
                style: { marginLeft: 'auto', border: '1px solid #bfdbfe', background: '#eff6ff', color: '#1d4ed8', borderRadius: 10, padding: '7px 14px', fontSize: 12.5, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' }
            }, '📊 키워드 순위 탭에서 상세 보기 →')
        ),
        React.createElement('div', { style: { fontSize: 12, color: '#94a3b8', marginTop: 8 } },
            '업체별 순위 추적 현황·키워드별 노출 분석·상품 추적 등록은 상단 「📊 키워드 순위」 탭으로 이동했습니다.')
    );
};
