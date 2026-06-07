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
        ? '모바일 비중이 ' + mobileRatio + '%로 높습니다. 모바일 최적화 상세페이지가 매우 중요합니다.'
        : mobileRatio >= 50
            ? '모바일과 PC가 균형 잡힌 키워드입니다. 양쪽 모두 최적화가 필요합니다.'
            : 'PC 비중이 ' + pcRatio + '%로 높습니다. PC 기반 상세페이지 최적화에 집중하세요.';

    return (
        <div className="section fade-in" id="sec-volume">
            <div className="container">
                <div className="card">
                    <h3 className="rt-h3">
                        <span className="rt-hic">🔍</span>
                        키워드 검색량
                        <span className="badge b-ok">✅ 실측</span>
                    </h3>
                    <div className="rt-desc">네이버 검색광고 API 기준 월간 검색량</div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                        <div className="rt-kpi">
                            <div className="rt-kpi-k">총 검색량</div>
                            <div className="rt-kpi-v">{fmt(total)}<small>회/월</small></div>
                        </div>
                        <div className="rt-kpi">
                            <div className="rt-kpi-k">💻 PC</div>
                            <div className="rt-kpi-v" style={{ color: '#4f46e5' }}>{fmt(pc)}<small>회 ({pcRatio}%)</small></div>
                        </div>
                        <div className="rt-kpi">
                            <div className="rt-kpi-k">📱 모바일</div>
                            <div className="rt-kpi-v" style={{ color: '#ec4899' }}>{fmt(mobile)}<small>회 ({mobileRatio}%)</small></div>
                        </div>
                    </div>

                    {/* 기기별 비율 바 */}
                    <div style={{ display: 'flex', height: 14, borderRadius: 7, overflow: 'hidden', marginTop: 16 }}>
                        <div style={{ width: pcRatio + '%', background: '#4f46e5' }}></div>
                        <div style={{ width: mobileRatio + '%', background: '#ec4899' }}></div>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 12, color: '#64748b', fontWeight: 700 }}>
                        <span><span style={{ display: 'inline-block', width: 9, height: 9, background: '#4f46e5', borderRadius: '50%', marginRight: 5 }}></span>PC {pcRatio}%</span>
                        <span><span style={{ display: 'inline-block', width: 9, height: 9, background: '#ec4899', borderRadius: '50%', marginRight: 5 }}></span>모바일 {mobileRatio}%</span>
                    </div>

                    <div className="note ok">💡 {note}</div>
                </div>
            </div>
        </div>
    );
};
