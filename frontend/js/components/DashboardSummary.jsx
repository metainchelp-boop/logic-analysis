/* DashboardSummary — 대시보드 요약 카드 (v2) */
window.DashboardSummary = function DashboardSummary({ products, searchResult }) {
    var useState = React.useState;
    var useEffect = React.useEffect;

    var _s1 = useState(0); var analysisCount = _s1[0]; var setAnalysisCount = _s1[1];
    var _s2 = useState(0); var reportCount = _s2[0]; var setReportCount = _s2[1];

    useEffect(function() {
        api.get('/cd/today-stats').then(function(res) {
            if (res && res.success && res.data) {
                setAnalysisCount(res.data.analysis_count || 0);
                setReportCount(res.data.report_count || 0);
            }
        }).catch(function() {});
    }, []);

    var totalKeywords = products.reduce(function(sum, p) { return sum + ((p.keywords && p.keywords.length) || 0); }, 0);

    return React.createElement('div', { className: 'section fade-in' },
        React.createElement('div', { className: 'container' },
            React.createElement('div', { className: 'card-grid card-grid-4' },
                React.createElement(StatCard, { label: '추적 상품', value: products.length, sub: '등록된 상품 수' }),
                React.createElement(StatCard, { label: '추적 키워드', value: totalKeywords, sub: '모니터링 중' }),
                React.createElement(StatCard, { label: '당일 분석', value: analysisCount, sub: '수동 분석 횟수' }),
                React.createElement(StatCard, { label: '보고서 출력', value: reportCount, sub: '당일 출력 건수' })
            )
        )
    );
};
