/* KeywordVolumeSection — 키워드 검색량 (v5) */
window.KeywordVolumeSection = function KeywordVolumeSection({ keyword, data }) {
    if (!data || !data.length) return null;

    const item = data[0];
    const pc = item?.monthlyPcQcCnt || 0;
    const mobile = item?.monthlyMobileQcCnt || 0;
    const total = pc + mobile;
    const pcRatio = total > 0 ? Math.round(pc / total * 100) : 0;
    const mobileRatio = total > 0 ? Math.round(mobile / total * 100) : 0;

    return (
        <div className="section fade-in" id="sec-volume">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' }}>🔍</span>
                    키워드 검색량
                </div>
                <div className="section-line"></div>
                <p className="section-subtitle">네이버 검색광고 API 기준 월간 검색량</p>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                    {/* 왼쪽: 검색량 수치 */}
                    <div style={{
                        background: '#fff', borderRadius: 16, padding: 24,
                        border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
                    }}>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 20 }}>
                            <span style={{ fontSize: 24, fontWeight: 800, color: '#4f46e5' }}>{fmt(total)}</span>
                            <span style={{ fontSize: 14, color: '#64748b' }}>회/월</span>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                            <div style={{ background: '#f0f4ff', borderRadius: 12, padding: 16 }}>
                                <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, marginBottom: 4 }}>💻 PC 검색</div>
                                <div style={{ fontSize: 18, fontWeight: 700, color: '#4f46e5' }}>{fmt(pc)}</div>
                                <div style={{ fontSize: 12, color: '#94a3b8' }}>{pcRatio}%</div>
                            </div>
                            <div style={{ background: '#fffbeb', borderRadius: 12, padding: 16 }}>
                                <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, marginBottom: 4 }}>📱 모바일</div>
                                <div style={{ fontSize: 18, fontWeight: 700, color: '#f59e0b' }}>{fmt(mobile)}</div>
                                <div style={{ fontSize: 12, color: '#94a3b8' }}>{mobileRatio}%</div>
                            </div>
                        </div>
                    </div>

                    {/* 오른쪽: 비율 시각화 */}
                    <div style={{
                        background: '#fff', borderRadius: 16, padding: 24,
                        border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
                    }}>
                        <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 16 }}>검색 기기별 비율</div>

                        {/* 두꺼운 가로 바 */}
                        <div style={{ display: 'flex', height: 48, borderRadius: 12, overflow: 'hidden', marginBottom: 20 }}>
                            <div style={{
                                width: pcRatio + '%', background: 'linear-gradient(135deg, #4f46e5, #818cf8)',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                color: '#fff', fontSize: 13, fontWeight: 700,
                                minWidth: pcRatio > 5 ? 'auto' : '0'
                            }}>
                                {pcRatio > 10 ? 'PC ' + pcRatio + '%' : ''}
                            </div>
                            <div style={{
                                width: mobileRatio + '%', background: 'linear-gradient(135deg, #f59e0b, #fbbf24)',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                color: '#fff', fontSize: 13, fontWeight: 700
                            }}>
                                {mobileRatio > 10 ? '모바일 ' + mobileRatio + '%' : ''}
                            </div>
                        </div>

                        {/* 범례 */}
                        <div style={{ display: 'flex', gap: 20, marginBottom: 16, fontSize: 12, color: '#64748b' }}>
                            <span><span style={{ display: 'inline-block', width: 12, height: 12, background: '#4f46e5', borderRadius: 3, marginRight: 6, verticalAlign: 'middle' }}></span>PC {pcRatio}%</span>
                            <span><span style={{ display: 'inline-block', width: 12, height: 12, background: '#f59e0b', borderRadius: 3, marginRight: 6, verticalAlign: 'middle' }}></span>모바일 {mobileRatio}%</span>
                        </div>

                        {/* 인사이트 박스 */}
                        <div style={{
                            background: '#f0fdf4', borderRadius: 10, padding: '12px 16px',
                            border: '1px solid #bbf7d0', fontSize: 13, color: '#166534', lineHeight: 1.6
                        }}>
                            {mobileRatio >= 70
                                ? '💡 모바일 비중이 ' + mobileRatio + '%로 높습니다. 모바일 최적화 상세페이지가 중요합니다.'
                                : mobileRatio >= 50
                                    ? '💡 모바일과 PC가 균형 잡힌 키워드입니다. 양쪽 모두 최적화가 필요합니다.'
                                    : '💡 PC 비중이 ' + pcRatio + '%로 높습니다. PC 기반 상세페이지 최적화에 집중하세요.'}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
