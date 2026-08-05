/* RelatedKeywordsSection — 연관/황금 키워드 (v6.6: 연관도 우선 정렬 + 상위 30개 기본 표시)
 * '콤부차' 보고서에 쌀·계란 등 대분류 인기 키워드가 상위를 차지하던 문제 개선:
 * ① 분석 키워드를 포함(또는 포함되는) 키워드를 앞으로 → ② 나머지는 검색량순.
 * 기본 30개만 표시(전달본 다이어트), '전체 보기'는 화면 전용(no-export). 데이터 삭제 없음. */
window.RelatedKeywordsSection = function RelatedKeywordsSection({ data, keyword }) {
    const { useState } = React;
    const [tab, setTab] = useState('related');
    const [showAll, setShowAll] = useState(false);
    if (!data) return null;

    const goldenList = data.golden_keywords || [];
    const rawRelated = data.related_keywords || [];

    /* 연관도 우선 정렬 — keyword 미전달 시 기존 순서 그대로(무손실 폴백) */
    var norm = function(v) { return String(v || '').replace(/\s/g, '').toLowerCase(); };
    var base = norm(keyword);
    var isRel = function(k) {
        if (!base) return false;
        var n = norm(k && k.keyword);
        return !!n && (n.indexOf(base) >= 0 || base.indexOf(n) >= 0);
    };
    var relatedList = rawRelated;
    var relCount = 0;
    if (base) {
        var tier1 = [], tier2 = [];
        rawRelated.forEach(function(k) { (isRel(k) ? tier1 : tier2).push(k); });
        var byVol = function(a, b) { return (b.totalVolume || 0) - (a.totalVolume || 0); };
        tier1.sort(byVol); tier2.sort(byVol);
        relatedList = tier1.concat(tier2);
        relCount = tier1.length;
    }
    var SHOW_LIMIT = 30;
    var relatedVisible = (tab === 'related' && !showAll) ? relatedList.slice(0, SHOW_LIMIT) : relatedList;
    /* 상품명 후보: 연관도 상위 5개 (분석 키워드 자체 제외) */
    var nameCandidates = base ? relatedList.filter(function(k) { return isRel(k) && norm(k.keyword) !== base; }).slice(0, 5) : [];

    const displayList = tab === 'golden' ? goldenList : relatedVisible;
    const maxVol = displayList.reduce(function(m, k) { return Math.max(m, k.totalVolume || 0); }, 1);

    /* 경쟁강도 색상 맵 */
    var compColorMap = { '높음': '#ef4444', '보통': '#f59e0b', '낮음': '#10b981' };
    var compBgMap = { '높음': '#fef2f2', '보통': '#fffbeb', '낮음': '#f0fdf4' };

    return (
        <div className="section fade-in" id="sec-related">
            <div className="container">
                <div className="card" style={{ padding: '20px 22px' }}>
                <h3 className="rt-h3"><span className="rt-hic">🔗</span>연관 키워드 분석<span className="badge b-ok">✅ 실측</span><span style={{ fontSize: 12, fontWeight: 400, color: '#64748b', marginLeft: 4 }}>총 {fmt(data.total_found)}개 발견</span></h3>
                <div className="rt-desc">{base ? '연관도(분석 키워드 포함 우선) → 검색량순 정렬 · 기본 상위 ' + SHOW_LIMIT + '개 표시' : '검색량과 경쟁강도를 기반으로 분류합니다'}</div>

                {/* v5 탭 바 */}
                <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                    <button
                        onClick={() => setTab('related')}
                        style={{
                            padding: '10px 20px', borderRadius: 10, border: 'none',
                            background: tab === 'related' ? '#3b82f6' : '#f1f5f9',
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
                    {tab === 'related' && relatedList.length > SHOW_LIMIT && (
                        <button
                            type="button"
                            className="no-export"
                            onClick={() => setShowAll(!showAll)}
                            style={{
                                marginLeft: 'auto', padding: '10px 16px', borderRadius: 10,
                                border: '1px solid #e2e8f0', background: '#fff', color: '#64748b',
                                fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit'
                            }}
                        >
                            {showAll ? '상위 ' + SHOW_LIMIT + '개만 보기' : '전체 ' + fmt(relatedList.length) + '개 보기'}
                        </button>
                    )}
                </div>

                {displayList.length === 0 ? (
                    <EmptyState icon="💎" text={tab === 'golden' ? '황금 키워드가 없습니다 (검색량 100~5,000 + 경쟁 낮음 조건)' : '연관 키워드가 없습니다'} />
                ) : (
                    <div className="card" style={{ padding: 0, overflow: 'hidden', borderRadius: 16 }}>
                      <div style={{ maxHeight: 540, overflowY: 'auto' }}>
                        <table className="rt-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                            <thead>
                                <tr>
                                    <th style={{ textAlign: 'center', width: 40 }}>#</th>
                                    <th style={{ textAlign: 'left' }}>키워드</th>
                                    <th style={{ textAlign: 'left' }}>월간 검색량</th>
                                    <th style={{ textAlign: 'center' }}>PC</th>
                                    <th style={{ textAlign: 'center' }}>모바일</th>
                                    <th style={{ textAlign: 'center' }}>경쟁강도</th>
                                    <th style={{ textAlign: 'left', width: '20%' }}>검색량 비율</th>
                                    {tab === 'golden' && <th style={{ textAlign: 'center' }}>추천</th>}
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
                                            <td style={{ padding: '12px 20px', fontWeight: 700, fontSize: 14, color: '#3b82f6' }}>{fmt(k.totalVolume)}</td>
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
                                                        background: tab === 'golden' ? 'linear-gradient(90deg, #f59e0b, #fbbf24)' : 'linear-gradient(90deg, #3b82f6, #7c3aed)',
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

                {tab === 'related' && nameCandidates.length > 0 && (
                    <div className="sub-card">
                        <div className="st">✏️ 상품명에 넣을 후보 {nameCandidates.length}개</div>
                        <div>
                            {nameCandidates.map(function(k) {
                                return <span key={k.keyword} className="tag2">{k.keyword} · 월 {fmt(k.totalVolume)}</span>;
                            })}
                        </div>
                        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>분석 키워드와 직접 연관된 키워드 중 검색량 상위 — 상품명·태그 반영 후보</div>
                    </div>
                )}
                </div>
            </div>
        </div>
    );
};
