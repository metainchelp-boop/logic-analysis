/* RelatedKeywordsSection — 연관/황금 키워드 */
window.RelatedKeywordsSection = function RelatedKeywordsSection({ data }) {
    const { useState } = React;
    const [tab, setTab] = useState('golden');
    if (!data) return null;

    const goldenList = data.golden_keywords || [];
    const relatedList = data.related_keywords || [];
    const displayList = tab === 'golden' ? goldenList : relatedList;

    return (
        <div className="section fade-in" id="sec-related">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: '#fef9c3' }}>💎</span>
                    연관 키워드 분석
                    <span style={{ fontSize: 13, fontWeight: 400, color: '#64748b', marginLeft: 8 }}>
                        총 {fmt(data.total_found)}개 발견
                    </span>
                </div>

                <div className="tab-bar">
                    <button className={`tab-btn ${tab === 'golden' ? 'active' : ''}`} onClick={() => setTab('golden')}>
                        황금 키워드 ({goldenList.length})
                    </button>
                    <button className={`tab-btn ${tab === 'related' ? 'active' : ''}`} onClick={() => setTab('related')}>
                        연관 키워드 ({relatedList.length})
                    </button>
                </div>

                {displayList.length === 0 ? (
                    <EmptyState icon="💎" text={tab === 'golden' ? '황금 키워드가 없습니다 (검색량 100~5,000 + 경쟁 낮음 조건)' : '연관 키워드가 없습니다'} />
                ) : (
                    <div className="table-wrap">
                        <table>
                            <thead>
                                <tr>
                                    <th style={{ width: 40 }}>#</th>
                                    <th>키워드</th>
                                    <th>월간 검색량</th>
                                    <th>PC</th>
                                    <th>모바일</th>
                                    <th>경쟁강도</th>
                                    {tab === 'golden' && <th>추천</th>}
                                </tr>
                            </thead>
                            <tbody>
                                {displayList.map((k, i) => (
                                    <tr key={k.keyword}>
                                        <td style={{ color: '#94a3b8' }}>{i + 1}</td>
                                        <td style={{ fontWeight: 500 }}>
                                            {k.keyword}
                                            {k.isGolden && <span className="badge badge-gold" style={{ marginLeft: 6 }}>황금</span>}
                                        </td>
                                        <td style={{ fontWeight: 600 }}>{fmt(k.totalVolume)}</td>
                                        <td>{fmt(k.monthlyPcQcCnt)}</td>
                                        <td>{fmt(k.monthlyMobileQcCnt)}</td>
                                        <td><span className={`badge ${compClass(k.compIdx)}`}>{compLabel(k.compIdx)}</span></td>
                                        {tab === 'golden' && <td><span className="badge badge-green">진입 추천</span></td>}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
};
