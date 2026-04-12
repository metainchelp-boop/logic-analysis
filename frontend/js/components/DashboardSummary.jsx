/* DashboardSummary — 대시보드 요약 카드 */
window.DashboardSummary = function DashboardSummary({ products, searchResult }) {
    const totalKeywords = products.reduce((sum, p) => sum + (p.keywords?.length || 0), 0);
    const allRanks = products.flatMap(p => (p.keywords || []).map(k => k.latest_rank)).filter(Boolean);
    const avgRank = allRanks.length > 0 ? Math.round(allRanks.reduce((a, b) => a + b, 0) / allRanks.length) : null;

    return (
        <div className="section fade-in">
            <div className="container">
                <div className="card-grid card-grid-4">
                    <StatCard icon="📦" iconColor="blue" label="추적 상품" value={products.length} sub="등록된 상품 수" />
                    <StatCard icon="🔑" iconColor="green" label="추적 키워드" value={totalKeywords} sub="모니터링 중" />
                    <StatCard icon="📈" iconColor="amber" label="평균 순위" value={avgRank ? `${avgRank}위` : '-'} sub={avgRank ? (avgRank <= 20 ? '상위권' : avgRank <= 50 ? '중위권' : '개선 필요') : '데이터 없음'} />
                    <StatCard icon="🔍" iconColor="purple" label="연관 키워드" value={searchResult ? fmt(searchResult.total_found) : '-'} sub={searchResult ? `${searchResult.golden_keywords?.length || 0}개 황금키워드` : '키워드 검색 필요'} />
                </div>
            </div>
        </div>
    );
};
