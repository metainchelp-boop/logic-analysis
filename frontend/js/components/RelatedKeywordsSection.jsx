/* RelatedKeywordsSection — 연관/황금 키워드 (v5) */
window.RelatedKeywordsSection = function RelatedKeywordsSection({ data }) {
    const { useState } = React;
    const [tab, setTab] = useState('related');
    if (!data) return null;

    const goldenList = data.golden_keywords || [];
    const relatedList = data.related_keywords || [];
    const displayList = tab === 'golden' ? goldenList : relatedList;
    const maxVol = displayList.reduce(function(m, k) { return Math.max(m, k.totalVolume || 0); }, 1);

    /* 경쟁강도 색상 맵 */
    var compColorMap = { '높음': '#ef4444', '보통': '#f59e0b', '낮음': '#10b981' };
    var compBgMap = { '높음': '#fef2f2', '보통': '#fffbeb', '낮음': '#f0fdf4' };

    return (
        <div className="section fade-in" id="sec-related">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: '#fef9c3' }}>🔗</span>
                    연관 키워드 분석
                    <span style={{ fontSize: 13, fontWeight: 400, color: '#64748b', marginLeft: 8 }}>
                        총 {fmt(data.total_found)}개 발견
                    </span>
                </div>
                <div className="section-line"></div>
                <p className="section-subtitle">검색량과 경쟁강도를 기반으로 분류합니다</p>

                {/* v5 탭 바 */}
                <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                    <button
                        onClick={() => setTab('related')}
                        style={{
                            padding: '10px 20px', borderRadius: 10, border: 'none',
                            background: tab === 'related' ? '#4f46e5' : '#f1f5f9',
                            color: tab === 'related' ? '#fff' : '#64748b',
                            fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
                            transition: 'all 0.2s'
                        }}
                    >
                        연관 키워드 ({relatedList.length})
                    </button>
                    <button
                        onClick={() => setTab('golden')}
                        style={{
                            padding: '10px 20px', borderRadius: 10, border: 'none',
                            background: tab === 'golden' ? '#f59e0b' : '#f1f5f9',
                            color: tab === 'golden' ? '#fff' : '#64748b',
                            fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
                            transition: 'all 0.2s'
                        }}
                    >
                        💎 황금 키워드 ({goldenList.length})
                    </button>
                </div>

                {displayList.length === 0 ? (
                    <EmptyState icon="💎" text={tab === 'golden' ? '황금 키워드가 없습니다 (검색량 100~5,000 + 경쟁 낮음 조건)' : '연관 키워드가 없습니다'} />
                ) : (
                    <div className="card" style={{ padding: 0, overflow: 'hidden', borderRadius: 16 }}>
                      <div style={{ maxHeight: 540, overflowY: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                            <thead>
                                <tr style={{ background: tab === 'golden' ? 'linear-gradient(135deg, #f59e0b, #d97706)' : 'linear-gradient(135deg, #4f46e5, #7c3aed)' }}>
                                    <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center', width: 40 }}>#</th>
                                    <th style={{ padding: '14px 20px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'left' }}>키워드</th>
                                    <th style={{ padding: '14px 20px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'left' }}>월간 검색량</th>
                                    <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center' }}>PC</th>
                                    <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center' }}>모바일</th>
                                    <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center' }}>경쟁강도</th>
                                    <th style={{ padding: '14px 20px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'left', width: '20%' }}>검색량 비율</th>
                                    {tab === 'golden' && <th style={{ padding: '14px 16px', color: '#fff', fontSize: 13, fontWeight: 600, textAlign: 'center' }}>추천</th>}
                                </tr>
                            </thead>
                            <tbody>
                                {displayList.map((k, i) => {
                                    var volPct = maxVol > 0 ? Math.min(100, Math.round((k.totalVolume || 0) / maxVol * 100)) : 0;
                                    var cLabel = compLabel(k.compIdx);
                                    return (
                                        <tr key={k.keyword} style={{ borderBottom: '1px solid #e2e8f0', background: i % 2 === 0 ? '#fff' : '#f8fafc' }}>
                                            <td style={{ padding: '12px 16px', textAlign: 'center', color: '#94a3b8', fontSize: 13, whiteSpace: 'nowrap', minWidth: 32 }}>{i + 1}</td>
                                            <td style={{ padding: '12px 20px', fontWeight: 600, fontSize: 14, color: '#0f172a' }}>
                                                {k.keyword}
                                                {k.isGolden && <span style={{ display: 'inline-block', marginLeft: 6, padding: '2px 8px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: '#fef3c7', color: '#92400e' }}>황금</span>}
                                            </td>
                                            <td style={{ padding: '12px 20px', fontWeight: 700, fontSize: 14, color: '#4f46e5' }}>{fmt(k.totalVolume)}</td>
                                            <td style={{ padding: '12px 16px', textAlign: 'center', fontSize: 13, color: '#64748b' }}>{fmt(k.monthlyPcQcCnt)}</td>
                                            <td style={{ padding: '12px 16px', textAlign: 'center', fontSize: 13, color: '#64748b' }}>{fmt(k.monthlyMobileQcCnt)}</td>
                                            <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                                                <span style={{
                                                    display: 'inline-block', padding: '4px 12px', borderRadius: 999,
                                                    fontSize: 12, fontWeight: 700,
                                                    background: compBgMap[cLabel] || '#f1f5f9',
                                                    color: compColorMap[cLabel] || '#64748b'
                                                }}>{cLabel}</span>
                                            </td>
                                            <td style={{ padding: '12px 20px' }}>
                                                <div style={{ height: 6, borderRadius: 3, background: '#f1f5f9', overflow: 'hidden' }}>
                                                    <div style={{
                                                        width: volPct + '%', height: '100%', borderRadius: 3,
                                                        background: tab === 'golden' ? 'linear-gradient(90deg, #f59e0b, #fbbf24)' : 'linear-gradient(90deg, #4f46e5, #7c3aed)',
                                                        transition: 'width 0.8s ease'
                                                    }}></div>
                                                </div>
                                            </td>
                                            {tab === 'golden' && (
                                                <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                                                    <span style={{ display: 'inline-block', padding: '4px 12px', borderRadius: 999, fontSize: 11, fontWeight: 700, background: '#f0fdf4', color: '#166534' }}>진입 추천</span>
                                                </td>
                                            )}
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                      </div>
                    </div>
                )}
            </div>
        </div>
    );
};
