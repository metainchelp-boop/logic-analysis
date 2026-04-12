/* App — 메인 앱 컴포넌트 */
window.App = function App() {
    const { useState, useEffect, useCallback } = React;
    const [health, setHealth] = useState(false);
    const [products, setProducts] = useState([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [searchedKeyword, setSearchedKeyword] = useState('');

    // 검색 결과
    const [volumeData, setVolumeData] = useState(null);
    const [relatedData, setRelatedData] = useState(null);

    // 종합 분석 결과 (SEO 분석 시 함께 로드)
    const [analysisData, setAnalysisData] = useState(null);

    // 헬스체크
    useEffect(() => {
        api.get('/health').then(res => setHealth(res.status === 'ok')).catch(() => setHealth(false));
    }, []);

    // 상품 목록 로드
    const loadProducts = useCallback(() => {
        api.get('/products').then(res => {
            if (res.success) setProducts(res.data);
        }).catch(() => {});
    }, []);

    useEffect(() => { loadProducts(); }, [loadProducts]);

    // 통합 검색
    const handleSearch = async (keyword) => {
        setSearchLoading(true);
        setSearchedKeyword(keyword);
        setVolumeData(null);
        setRelatedData(null);
        setAnalysisData(null);

        try {
            // 병렬로 검색량 + 연관키워드 호출
            const [volRes, relRes] = await Promise.all([
                api.post('/keyword/volume', [keyword]).catch(() => null),
                api.post('/keywords/related', { keyword }).catch(() => null),
            ]);

            if (volRes?.success) setVolumeData(volRes.data);
            if (relRes?.success) setRelatedData(relRes.data);

            // 연관 키워드 데이터에서 경쟁강도/골든키워드 등 추출
            if (relRes?.success && relRes.data) {
                const rd = relRes.data;
                const vol = volRes?.success && volRes.data?.[0] ? volRes.data[0] : null;
                const totalVol = vol ? (vol.monthlyPcQcCnt || 0) + (vol.monthlyMobileQcCnt || 0) : 0;
                const productCount = rd.total_products || rd.product_count || 0;

                // 경쟁강도 계산
                const compIndex = productCount > 0 && totalVol > 0
                    ? (productCount / totalVol).toFixed(2)
                    : null;
                const compLevel = compIndex !== null
                    ? (compIndex < 0.5 ? '블루오션 (진입 적기)' : compIndex < 1.0 ? '보통 (경쟁 중간)' : '레드오션 (경쟁 치열)')
                    : null;
                const compColor = compIndex !== null
                    ? (compIndex < 0.5 ? '#16a34a' : compIndex < 1.0 ? '#d97706' : '#dc2626')
                    : '#94a3b8';

                // 골든 키워드 찾기
                const goldenKws = rd.golden_keywords || [];
                const bestGolden = goldenKws.length > 0 ? goldenKws[0] : null;

                setAnalysisData({
                    competitionIndex: compIndex !== null ? {
                        compIndex: compIndex,
                        compLabel: compLevel,
                        compColor: compColor,
                        productCount: fmt(productCount) + '개',
                        searchVolume: fmt(totalVol) + '회/월',
                        avgCtr: vol ? ((vol.monthlyPcQcCnt || 0) / Math.max(totalVol, 1) * 100).toFixed(2) + '%' : '-',
                        interpretation: compIndex < 0.5
                            ? '시장에 상품이 부족한 상태입니다. 지금이 시장 진입의 최고 기회입니다.'
                            : compIndex < 1.0
                            ? '경쟁이 적당한 시장입니다. 차별화 전략으로 진입이 가능합니다.'
                            : '경쟁이 치열한 시장입니다. 명확한 차별화 포인트가 필요합니다.',
                    } : null,
                    goldenKeyword: bestGolden ? {
                        name: bestGolden.keyword,
                        score: bestGolden.score || (bestGolden.totalVolume ? Math.round(bestGolden.totalVolume / 100) : 0),
                        volume: fmt(bestGolden.totalVolume),
                        competition: compLabel(bestGolden.compIdx),
                        ctr: bestGolden.ctr ? bestGolden.ctr + '%' : '-',
                        clicks: fmt(bestGolden.monthlyClicks || Math.round((bestGolden.totalVolume || 0) * 0.05)),
                        reason: bestGolden.reason || '검색량 ' + fmt(bestGolden.totalVolume) + '회로 틈새 수요가 확실합니다. 경쟁강도가 낮아 진입하기 좋은 키워드입니다.',
                    } : null,
                    keywordTrend: totalVol > 0 ? {
                        mainKeyword: keyword,
                        subKeyword: rd.related_keywords?.[0]?.keyword || keyword,
                        mainVolume: totalVol,
                        subVolume: rd.related_keywords?.[0]?.totalVolume || 0,
                        mainDifficulty: compIndex < 0.5 ? '쉬움' : compIndex < 1.0 ? '보통' : '어려움',
                        subDifficulty: '보통',
                        mainDiffColor: compColor,
                        subDiffColor: '#d97706',
                    } : null,
                });
            }
        } catch (e) {
            console.error('검색 오류:', e);
        }
        setSearchLoading(false);
    };

    // 앵커 네비게이션
    const hasAnalysis = !!analysisData;
    const sections = [
        { id: 'sec-rank', label: '순위 추적' },
        { id: 'sec-volume', label: '검색량', show: !!volumeData },
        { id: 'sec-competition', label: '경쟁강도', show: !!analysisData?.competitionIndex },
        { id: 'sec-related', label: '연관 키워드', show: !!relatedData },
        { id: 'sec-trend', label: '키워드 트렌드', show: !!analysisData?.keywordTrend },
        { id: 'sec-golden', label: '골든키워드', show: !!analysisData?.goldenKeyword },
        { id: 'sec-seo', label: 'SEO 진단' },
        { id: 'sec-productname', label: '상품명 분석' },
        { id: 'sec-report', label: '보고서' },
        { id: 'sec-notify', label: '알림' },
    ].filter(s => s.show !== false);

    const scrollTo = (id) => {
        document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    return (
        <div>
            <TopBar health={health} />
            <SearchBar onSearch={handleSearch} loading={searchLoading} />

            {/* 앵커 네비 */}
            <div style={{ background: '#fff', borderBottom: '1px solid #e8ecf1', padding: '10px 0', position: 'sticky', top: 64, zIndex: 40 }}>
                <div className="container">
                    <div className="anchor-nav">
                        {sections.map(s => (
                            <button key={s.id} className="anchor-btn" onClick={() => scrollTo(s.id)}>{s.label}</button>
                        ))}
                    </div>
                </div>
            </div>

            {/* 대시보드 요약 */}
            <DashboardSummary products={products} searchResult={relatedData} />

            {/* 검색 로딩 */}
            {searchLoading && (
                <div className="section">
                    <div className="container">
                        <LoadingSpinner text={`"${searchedKeyword}" 분석 중... 약 5~10초 소요됩니다`} />
                    </div>
                </div>
            )}

            {/* 순위 추적 */}
            <RankTrackingSection products={products} refreshProducts={loadProducts} />

            {/* 키워드 검색량 */}
            {volumeData && <KeywordVolumeSection keyword={searchedKeyword} data={volumeData} />}

            {/* 키워드 경쟁강도 분석 */}
            {analysisData?.competitionIndex && (
                <div id="sec-competition">
                    <CompetitionIndexSection data={analysisData.competitionIndex} />
                </div>
            )}

            {/* 연관/황금 키워드 */}
            {relatedData && <RelatedKeywordsSection data={relatedData} />}

            {/* 키워드 검색량 비교 및 진입 난이도 */}
            {analysisData?.keywordTrend && (
                <div id="sec-trend">
                    <KeywordTrendSection data={analysisData.keywordTrend} />
                </div>
            )}

            {/* GOLDEN KEYWORD */}
            {analysisData?.goldenKeyword && (
                <div id="sec-golden">
                    <GoldenKeywordCard data={analysisData.goldenKeyword} />
                </div>
            )}

            {/* SEO 진단 */}
            <SeoDiagnosisSection keyword={searchedKeyword} />

            {/* 상품명 분석 */}
            <ProductNameSection keyword={searchedKeyword} />

            {/* 보고서 */}
            <ReportSection />

            {/* 알림 설정 */}
            <NotificationSection />

            {/* 푸터 */}
            <footer className="footer">
                <div className="container">
                    © 2026 메타인크 — 로직 분석 v2.1 | 네이버 쇼핑 키워드 분석 & 순위 추적
                </div>
            </footer>
        </div>
    );
};

// 앱 렌더링
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
