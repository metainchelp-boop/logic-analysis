/* KeywordVolumeSection — 키워드 검색량 */
window.KeywordVolumeSection = function KeywordVolumeSection({ keyword, data }) {
    if (!data || !data.length) return null;

    const item = data[0];
    const pc = item?.monthlyPcQcCnt || 0;
    const mobile = item?.monthlyMobileQcCnt || 0;
    const total = pc + mobile;

    return (
        <div className="section fade-in" id="sec-volume">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: '#ecfdf5' }}>🔍</span>
                    키워드 검색량 — <span style={{ color: '#3b82f6' }}>{keyword}</span>
                </div>
                <div className="card-grid card-grid-3">
                    <div className="card" style={{ textAlign: 'center' }}>
                        <div className="stat-label">월간 총 검색량</div>
                        <div className="stat-value" style={{ color: '#3b82f6' }}>{fmt(total)}</div>
                    </div>
                    <div className="card" style={{ textAlign: 'center' }}>
                        <div className="stat-label">PC 검색량</div>
                        <div className="stat-value">{fmt(pc)}</div>
                        <div className="stat-sub">{total > 0 ? Math.round(pc / total * 100) : 0}%</div>
                    </div>
                    <div className="card" style={{ textAlign: 'center' }}>
                        <div className="stat-label">모바일 검색량</div>
                        <div className="stat-value">{fmt(mobile)}</div>
                        <div className="stat-sub">{total > 0 ? Math.round(mobile / total * 100) : 0}%</div>
                    </div>
                </div>
            </div>
        </div>
    );
};
