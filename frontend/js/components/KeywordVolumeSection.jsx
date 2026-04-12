/* KeywordVolumeSection — 키워드 검색량 */
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
                    <span className="icon" style={{ background: '#ecfdf5' }}>🔍</span>
                    키워드 검색량
                </div>

                <div className="card" style={{ padding: '24px' }}>
                    {/* 키워드명 */}
                    <p style={{ fontSize: '13px', color: '#6b7280', margin: '0 0 4px' }}>검색 키워드</p>
                    <p style={{ fontSize: '18px', fontWeight: '700', color: '#4f46e5', margin: '0 0 20px' }}>{keyword}</p>

                    {/* 총 검색량 */}
                    <div style={{
                        background: 'linear-gradient(135deg, #f0f9ff, #e0f2fe)',
                        borderRadius: '10px', padding: '16px', textAlign: 'center',
                        border: '1px solid #bae6fd', marginBottom: '16px'
                    }}>
                        <div style={{ fontSize: '12px', color: '#64748b', fontWeight: '600', marginBottom: '4px' }}>월간 총 검색량</div>
                        <div style={{ fontSize: '28px', fontWeight: '800', color: '#0369a1' }}>{fmt(total)}<span style={{ fontSize: '14px', fontWeight: '500' }}>회</span></div>
                    </div>

                    {/* PC / 모바일 비교 */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                        <div style={{
                            background: '#f9fafb', borderRadius: '8px', padding: '14px', textAlign: 'center',
                            border: '1px solid #e5e7eb'
                        }}>
                            <div style={{ fontSize: '11px', color: '#6b7280', marginBottom: '4px' }}>💻 PC</div>
                            <div style={{ fontSize: '20px', fontWeight: '700', color: '#1f2937' }}>{fmt(pc)}</div>
                            <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>{pcRatio}%</div>
                        </div>
                        <div style={{
                            background: '#f9fafb', borderRadius: '8px', padding: '14px', textAlign: 'center',
                            border: '1px solid #e5e7eb'
                        }}>
                            <div style={{ fontSize: '11px', color: '#6b7280', marginBottom: '4px' }}>📱 모바일</div>
                            <div style={{ fontSize: '20px', fontWeight: '700', color: '#1f2937' }}>{fmt(mobile)}</div>
                            <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>{mobileRatio}%</div>
                        </div>
                    </div>

                    {/* 비율 바 */}
                    <div style={{ marginTop: '12px' }}>
                        <div style={{ display: 'flex', height: '8px', borderRadius: '999px', overflow: 'hidden' }}>
                            <div style={{ width: pcRatio + '%', background: '#4f46e5', transition: 'width 0.4s' }}></div>
                            <div style={{ width: mobileRatio + '%', background: '#9333ea', transition: 'width 0.4s' }}></div>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', fontSize: '10px', color: '#9ca3af' }}>
                            <span>PC {pcRatio}%</span>
                            <span>모바일 {mobileRatio}%</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
