/* KeywordVolumeSection — 키워드 검색량 (v6.1 미리보기 디자인) */
window.KeywordVolumeSection = function KeywordVolumeSection({ keyword, data }) {
    if (!data || !data.length) return null;

    const item = data[0];
    const pc = item?.monthlyPcQcCnt || 0;
    const mobile = item?.monthlyMobileQcCnt || 0;
    const total = pc + mobile;
    const pcRatio = total > 0 ? Math.round(pc / total * 100) : 0;
    const mobileRatio = total > 0 ? Math.round(mobile / total * 100) : 0;

    var note = mobileRatio >= 70
        ? '모바일 비중 ' + mobileRatio + '% — 모바일 최적화 상세페이지가 매우 중요합니다.'
        : mobileRatio >= 50
            ? '모바일과 PC가 균형 잡힌 키워드입니다. 양쪽 모두 최적화가 필요합니다.'
            : 'PC 비중 ' + pcRatio + '% — PC 기반 상세페이지 최적화에 집중하세요.';

    return (
        <div className="section fade-in" id="sec-volume">
            <div className="container">
                <div className="card">
                    <h3 className="rt-h3">
                        <span className="hic">🔍</span>
                        키워드 검색량
                        <span className="badge b-ok">✅ 실측</span>
                    </h3>

                    <div className="grid3">
                        <div className="kpi"><div className="k">총 검색량</div><div className="v">{fmt(total)}<small>회/월</small></div></div>
                        <div className="kpi"><div className="k">PC</div><div className="v">{fmt(pc)}<small>회 ({pcRatio}%)</small></div></div>
                        <div className="kpi"><div className="k">모바일</div><div className="v">{fmt(mobile)}<small>회 ({mobileRatio}%)</small></div></div>
                    </div>

                    {/* 기기별 비율 트랙바 */}
                    <div className="track" style={{ height: 14, marginTop: 14, display: 'flex' }}>
                        <i style={{ width: pcRatio + '%', background: '#6366f1' }}></i>
                        <i style={{ width: mobileRatio + '%', background: '#ec4899' }}></i>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--sub)', marginTop: 5 }}>
                        <span>● PC {pcRatio}%</span>
                        <span>모바일 {mobileRatio}% ●</span>
                    </div>

                    <div className="note">{note}</div>
                </div>
            </div>
        </div>
    );
};
