/* AiInsightsView — 광고주(업체) 누적 데이터 기반 AI 자기학습 인사이트 렌더러
 * ClientDashboard의 "AI 인사이트" 탭과 학습센터(LearningCenterPage)에서 공용으로 사용. */
window.AiInsightsView = function AiInsightsView({ aiLoading, aiInsights, aiSelectedKeyword, setAiSelectedKeyword }) {
    function fmt(n) { return n != null ? Number(n).toLocaleString("ko-KR") : "-"; }
    return (
                                <div>
                                    {aiLoading && (
                                        <div className="card" style={{ padding: 40, textAlign: 'center' }}>
                                            <div style={{ fontSize: 32, marginBottom: 12 }}>{'🤖'}</div>
                                            <div style={{ fontSize: 14, color: '#64748b' }}>AI 인사이트를 분석 중입니다...</div>
                                        </div>
                                    )}

                                    {!aiLoading && !aiInsights && (
                                        <div className="card" style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>
                                            <div style={{ fontSize: 32, marginBottom: 12 }}>{'📊'}</div>
                                            <div style={{ fontSize: 14, fontWeight: 500 }}>아직 분석 데이터가 없어 AI 인사이트를 생성할 수 없습니다.</div>
                                            <div style={{ fontSize: 13, marginTop: 8 }}>분석을 실행하면 AI가 자동으로 학습하여 인사이트를 제공합니다.</div>
                                        </div>
                                    )}

                                    {!aiLoading && aiInsights && (
                                        <div>
                                            {/* ⑥ 업체 성과 패턴 */}
                                            {aiInsights.performance && (
                                                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                                                    <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                                                        {'📊'} 업체 성과 패턴
                                                        <span style={{
                                                            fontSize: 11, padding: '2px 8px', borderRadius: 10, fontWeight: 600,
                                                            background: aiInsights.performance.overallTrend === '상승세' ? '#dcfce7' : aiInsights.performance.overallTrend === '하락세' ? '#fee2e2' : '#f1f5f9',
                                                            color: aiInsights.performance.overallTrend === '상승세' ? '#16a34a' : aiInsights.performance.overallTrend === '하락세' ? '#dc2626' : '#64748b'
                                                        }}>{aiInsights.performance.overallTrend}</span>
                                                    </div>
                                                    {/* 성과 요약 카드 */}
                                                    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
                                                        <div style={{ flex: 1, minWidth: 100, background: '#f0fdf4', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                                                            <div style={{ fontSize: 11, color: '#64748b' }}>상승 키워드</div>
                                                            <div style={{ fontSize: 22, fontWeight: 700, color: '#16a34a' }}>{aiInsights.performance.improving}</div>
                                                        </div>
                                                        <div style={{ flex: 1, minWidth: 100, background: '#fee2e2', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                                                            <div style={{ fontSize: 11, color: '#64748b' }}>하락 키워드</div>
                                                            <div style={{ fontSize: 22, fontWeight: 700, color: '#dc2626' }}>{aiInsights.performance.declining}</div>
                                                        </div>
                                                        <div style={{ flex: 1, minWidth: 100, background: '#f1f5f9', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                                                            <div style={{ fontSize: 11, color: '#64748b' }}>유지 키워드</div>
                                                            <div style={{ fontSize: 22, fontWeight: 700, color: '#64748b' }}>{aiInsights.performance.stable}</div>
                                                        </div>
                                                        <div style={{ flex: 1, minWidth: 100, background: '#dbeafe', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                                                            <div style={{ fontSize: 11, color: '#64748b' }}>총 키워드</div>
                                                            <div style={{ fontSize: 22, fontWeight: 700, color: '#1e40af' }}>{aiInsights.performance.totalKeywords}</div>
                                                        </div>
                                                    </div>
                                                    {/* 키워드별 성과 리스트 */}
                                                    {aiInsights.performance.keywordSummaries && aiInsights.performance.keywordSummaries.length > 0 && (
                                                        <div className="table-wrap" style={{ overflowX: 'auto' }}>
                                                            <table style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
                                                                <thead>
                                                                    <tr>
                                                                        <th>키워드</th>
                                                                        <th style={{ textAlign: 'center' }}>추세</th>
                                                                        <th style={{ textAlign: 'right' }}>초기 순위</th>
                                                                        <th style={{ textAlign: 'right' }}>현재 순위</th>
                                                                        <th style={{ textAlign: 'right' }}>변동</th>
                                                                        <th style={{ textAlign: 'right' }}>평균 순위</th>
                                                                        <th style={{ textAlign: 'right' }}>데이터</th>
                                                                    </tr>
                                                                </thead>
                                                                <tbody>
                                                                    {aiInsights.performance.keywordSummaries.map(function(s, i) {
                                                                        var trendColor = s.trend === '상승' ? '#16a34a' : s.trend === '하락' ? '#dc2626' : '#64748b';
                                                                        var trendBg = s.trend === '상승' ? '#dcfce7' : s.trend === '하락' ? '#fee2e2' : '#f1f5f9';
                                                                        return (
                                                                            <tr key={i}>
                                                                                <td style={{ fontWeight: 600 }}>{s.keyword}</td>
                                                                                <td style={{ textAlign: 'center' }}>
                                                                                    <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: trendBg, color: trendColor }}>{s.trend}</span>
                                                                                </td>
                                                                                <td style={{ textAlign: 'right' }}>{s.firstRank}위</td>
                                                                                <td style={{ textAlign: 'right', fontWeight: 700 }}>{s.latestRank}위</td>
                                                                                <td style={{ textAlign: 'right', color: s.change > 0 ? '#16a34a' : s.change < 0 ? '#dc2626' : '#64748b', fontWeight: 600 }}>
                                                                                    {s.change > 0 ? '▲' + s.change : s.change < 0 ? '▼' + Math.abs(s.change) : '-'}
                                                                                </td>
                                                                                <td style={{ textAlign: 'right' }}>{s.avgRank}위</td>
                                                                                <td style={{ textAlign: 'right', color: '#94a3b8' }}>{s.dataPoints}건</td>
                                                                            </tr>
                                                                        );
                                                                    })}
                                                                </tbody>
                                                            </table>
                                                        </div>
                                                    )}
                                                    {/* 성과 조언 */}
                                                    {aiInsights.performance.advice && (
                                                        <div style={{ marginTop: 14, padding: 12, background: '#faf5ff', borderRadius: 8, fontSize: 13, color: '#6b21a8', lineHeight: 1.6 }}>
                                                            {'💡'} {aiInsights.performance.advice}
                                                        </div>
                                                    )}
                                                </div>
                                            )}

                                            {/* ⑦ 경쟁사 이상 감지 */}
                                            {aiInsights.competitorAlerts && aiInsights.competitorAlerts.totalAlerts > 0 && (
                                                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                                                    <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                                                        {'🚨'} 경쟁사 이상 감지
                                                        {aiInsights.competitorAlerts.dangerCount > 0 && (
                                                            <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: '#fee2e2', color: '#dc2626', fontWeight: 600 }}>
                                                                위험 {aiInsights.competitorAlerts.dangerCount}건
                                                            </span>
                                                        )}
                                                        {aiInsights.competitorAlerts.warningCount > 0 && (
                                                            <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: '#fef9c3', color: '#ca8a04', fontWeight: 600 }}>
                                                                주의 {aiInsights.competitorAlerts.warningCount}건
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                        {aiInsights.competitorAlerts.alerts.map(function(alert, i) {
                                                            var severityStyles = {
                                                                danger: { bg: '#fef2f2', border: '#fecaca', color: '#991b1b', icon: '🔴' },
                                                                warning: { bg: '#fffbeb', border: '#fde68a', color: '#92400e', icon: '🟡' },
                                                                success: { bg: '#f0fdf4', border: '#bbf7d0', color: '#166534', icon: '🟢' },
                                                                info: { bg: '#eff6ff', border: '#bfdbfe', color: '#1e40af', icon: '🔵' },
                                                            };
                                                            var st = severityStyles[alert.severity] || severityStyles.info;
                                                            return (
                                                                <div key={i} style={{ padding: '10px 14px', background: st.bg, border: '1px solid ' + st.border, borderRadius: 8, fontSize: 13 }}>
                                                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                                        <div style={{ color: st.color, fontWeight: 600 }}>
                                                                            {st.icon} {alert.message}
                                                                        </div>
                                                                        <span style={{ fontSize: 11, color: '#94a3b8' }}>{(alert.date || '').slice(0, 10)}</span>
                                                                    </div>
                                                                    {alert.detail && (
                                                                        <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>{alert.detail}</div>
                                                                    )}
                                                                </div>
                                                            );
                                                        })}
                                                    </div>
                                                </div>
                                            )}

                                            {/* ② 키워드 발굴 추천 */}
                                            {aiInsights.keywordRecommendations && aiInsights.keywordRecommendations.topRecommended && aiInsights.keywordRecommendations.topRecommended.length > 0 && (
                                                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                                                    <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                                                        {'🔍'} 키워드 발굴 추천
                                                        <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>
                                                            기존 {aiInsights.keywordRecommendations.existingCount}개 키워드에서 {aiInsights.keywordRecommendations.candidateCount}개 후보 발굴
                                                        </span>
                                                    </div>
                                                    <div className="table-wrap" style={{ overflowX: 'auto' }}>
                                                        <table style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
                                                            <thead>
                                                                <tr>
                                                                    <th>추천 키워드</th>
                                                                    <th style={{ textAlign: 'right' }}>월간 검색량</th>
                                                                    <th style={{ textAlign: 'right' }}>연관 등장</th>
                                                                    <th style={{ textAlign: 'right' }}>추천 점수</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody>
                                                                {aiInsights.keywordRecommendations.topRecommended.map(function(kw, i) {
                                                                    return (
                                                                        <tr key={i}>
                                                                            <td style={{ fontWeight: 600 }}>{kw.keyword}</td>
                                                                            <td style={{ textAlign: 'right' }}>{fmt(kw.volume)}</td>
                                                                            <td style={{ textAlign: 'right' }}>{kw.appearances}회</td>
                                                                            <td style={{ textAlign: 'right' }}>
                                                                                <span style={{
                                                                                    padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                                                                                    background: kw.score >= 5 ? '#dcfce7' : kw.score >= 2 ? '#fef9c3' : '#f1f5f9',
                                                                                    color: kw.score >= 5 ? '#16a34a' : kw.score >= 2 ? '#ca8a04' : '#64748b'
                                                                                }}>{kw.score}</span>
                                                                            </td>
                                                                        </tr>
                                                                    );
                                                                })}
                                                            </tbody>
                                                        </table>
                                                    </div>
                                                </div>
                                            )}

                                            {/* ===== 키워드별 인사이트 (①③④⑤⑧) ===== */}
                                            {aiInsights.keywordInsights && Object.keys(aiInsights.keywordInsights).length > 0 && (
                                                <div>
                                                    {/* 키워드 선택 pill */}
                                                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
                                                        {Object.keys(aiInsights.keywordInsights).map(function(kw) {
                                                            var isActive = aiSelectedKeyword === kw;
                                                            return (
                                                                <button key={kw} onClick={function() { setAiSelectedKeyword(kw); }}
                                                                    style={{
                                                                        padding: '6px 14px', borderRadius: 20, cursor: 'pointer', fontSize: 12,
                                                                        background: isActive ? '#7C3AED' : '#f5f3ff',
                                                                        color: isActive ? '#fff' : '#7C3AED',
                                                                        border: isActive ? '1px solid #7C3AED' : '1px solid #DDD6FE'
                                                                    }}>{'🔑'} {kw}</button>
                                                            );
                                                        })}
                                                    </div>

                                                    {/* 선택된 키워드 인사이트 */}
                                                    {aiSelectedKeyword && aiInsights.keywordInsights[aiSelectedKeyword] && (function() {
                                                        var kwData = aiInsights.keywordInsights[aiSelectedKeyword];
                                                        return React.createElement('div', null,
                                                            /* ⑧ 순위 예측 */
                                                            kwData.rankPrediction && React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 16 } },
                                                                React.createElement('div', { style: { fontSize: 16, fontWeight: 700, marginBottom: 16 } }, '🔮 순위 예측 — "' + aiSelectedKeyword + '"'),
                                                                kwData.rankPrediction.ready === false ?
                                                                    React.createElement('div', { style: { textAlign: 'center', padding: 20, color: '#94a3b8', fontSize: 13 } }, kwData.rankPrediction.message) :
                                                                    React.createElement('div', null,
                                                                        React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 } },
                                                                            React.createElement('div', { style: { flex: 1, minWidth: 110, background: '#f1f5f9', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                                React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '현재 순위'),
                                                                                React.createElement('div', { style: { fontSize: 22, fontWeight: 700 } }, kwData.rankPrediction.currentRank + '위')
                                                                            ),
                                                                            React.createElement('div', { style: { flex: 1, minWidth: 110, background: '#dbeafe', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                                React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '7일 후 예측'),
                                                                                React.createElement('div', { style: { fontSize: 22, fontWeight: 700, color: '#1e40af' } }, kwData.rankPrediction.predicted7d + '위')
                                                                            ),
                                                                            React.createElement('div', { style: { flex: 1, minWidth: 110, background: '#ede9fe', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                                React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '14일 후 예측'),
                                                                                React.createElement('div', { style: { fontSize: 22, fontWeight: 700, color: '#6d28d9' } }, kwData.rankPrediction.predicted14d + '위')
                                                                            ),
                                                                            React.createElement('div', { style: { flex: 1, minWidth: 110, background: '#faf5ff', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                                React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '30일 후 예측'),
                                                                                React.createElement('div', { style: { fontSize: 22, fontWeight: 700, color: '#9333ea' } }, kwData.rankPrediction.predicted30d + '위')
                                                                            )
                                                                        ),
                                                                        React.createElement('div', { style: { display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 13, color: '#475569' } },
                                                                            React.createElement('span', null, '추세: ', React.createElement('strong', { style: { color: kwData.rankPrediction.trend === '상승' ? '#16a34a' : kwData.rankPrediction.trend === '하락' ? '#dc2626' : '#64748b' } }, kwData.rankPrediction.trend)),
                                                                            React.createElement('span', null, '신뢰도: ', React.createElement('strong', null, kwData.rankPrediction.confidence, ' (R²=', kwData.rankPrediction.rSquared, ')')),
                                                                            React.createElement('span', null, '데이터: ', React.createElement('strong', null, kwData.rankPrediction.dataPoints, '건'))
                                                                        ),
                                                                        React.createElement('div', { style: { marginTop: 10, padding: 10, background: '#f8fafc', borderRadius: 8, fontSize: 12, color: '#64748b' } }, kwData.rankPrediction.trendDesc)
                                                                    )
                                                            ),

                                                            /* ① 가격 최적화 */
                                                            kwData.priceOptimization && React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 16 } },
                                                                React.createElement('div', { style: { fontSize: 16, fontWeight: 700, marginBottom: 16 } }, '💰 가격 최적화 — "' + aiSelectedKeyword + '"'),
                                                                React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 } },
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 130, background: '#f0fdf4', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '추천 가격대'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700, color: '#16a34a' } }, fmt(kwData.priceOptimization.recommendedRange.low) + ' ~ ' + fmt(kwData.priceOptimization.recommendedRange.high) + '원')
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#eff6ff', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '상위5 평균'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, fmt(kwData.priceOptimization.avgTop5) + '원')
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f1f5f9', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '중위 가격'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, fmt(kwData.priceOptimization.median) + '원')
                                                                    )
                                                                ),
                                                                React.createElement('div', { style: { padding: 12, background: '#faf5ff', borderRadius: 8, fontSize: 13, color: '#6b21a8' } },
                                                                    '💡 전략: ', React.createElement('strong', null, kwData.priceOptimization.strategy), ' — ', kwData.priceOptimization.strategyDesc
                                                                )
                                                            ),

                                                            /* ④ 광고 효율 */
                                                            kwData.adEfficiency && React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 16 } },
                                                                React.createElement('div', { style: { fontSize: 16, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 } },
                                                                    '📣 광고 효율 — "' + aiSelectedKeyword + '"',
                                                                    React.createElement('span', { style: {
                                                                        fontSize: 14, padding: '2px 10px', borderRadius: 10, fontWeight: 700,
                                                                        background: kwData.adEfficiency.grade === 'A' ? '#dcfce7' : kwData.adEfficiency.grade === 'B' ? '#dbeafe' : kwData.adEfficiency.grade === 'C' ? '#fef9c3' : '#fee2e2',
                                                                        color: kwData.adEfficiency.grade === 'A' ? '#16a34a' : kwData.adEfficiency.grade === 'B' ? '#1e40af' : kwData.adEfficiency.grade === 'C' ? '#ca8a04' : '#dc2626'
                                                                    } }, kwData.adEfficiency.grade + '등급')
                                                                ),
                                                                React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 } },
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f8fafc', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '효율 점수'),
                                                                        React.createElement('div', { style: { fontSize: 28, fontWeight: 700, color: kwData.adEfficiency.efficiencyScore >= 70 ? '#16a34a' : kwData.adEfficiency.efficiencyScore >= 40 ? '#ca8a04' : '#dc2626' } }, kwData.adEfficiency.efficiencyScore)
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f8fafc', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '검색량'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, fmt(kwData.adEfficiency.totalVolume))
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f8fafc', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, 'CTR'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, kwData.adEfficiency.ctr + '%')
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f8fafc', borderRadius: 10, padding: 14, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '현재 순위'),
                                                                        React.createElement('div', { style: { fontSize: 16, fontWeight: 700 } }, kwData.adEfficiency.currentRank ? kwData.adEfficiency.currentRank + '위' : '미측정')
                                                                    )
                                                                ),
                                                                React.createElement('div', { style: { padding: 12, background: '#faf5ff', borderRadius: 8, fontSize: 13, color: '#6b21a8' } }, '💡 ' + kwData.adEfficiency.advice)
                                                            ),

                                                            /* ⑤ 최적 등록 타이밍 */
                                                            kwData.optimalTiming && React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 16 } },
                                                                React.createElement('div', { style: { fontSize: 16, fontWeight: 700, marginBottom: 16 } }, '⏰ 최적 등록 타이밍 — "' + aiSelectedKeyword + '"'),
                                                                kwData.optimalTiming.ready === false ?
                                                                    React.createElement('div', { style: { textAlign: 'center', padding: 20, color: '#94a3b8', fontSize: 13 } }, kwData.optimalTiming.message) :
                                                                    React.createElement('div', null,
                                                                        /* 요일별 막대 */
                                                                        kwData.optimalTiming.weekdayData && React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'flex-end', height: 120, marginBottom: 16 } },
                                                                            kwData.optimalTiming.weekdayData.map(function(d) {
                                                                                var maxRank = Math.max.apply(null, kwData.optimalTiming.weekdayData.map(function(x) { return x.avgRank; }));
                                                                                var barH = maxRank > 0 ? Math.max(20, (d.avgRank / maxRank) * 100) : 40;
                                                                                return React.createElement('div', { key: d.day, style: { flex: 1, textAlign: 'center' } },
                                                                                    React.createElement('div', { style: { fontSize: 11, fontWeight: 600, marginBottom: 4, color: d.isBest ? '#16a34a' : d.isWorst ? '#dc2626' : '#64748b' } }, d.avgRank + '위'),
                                                                                    React.createElement('div', { style: {
                                                                                        height: barH, borderRadius: '6px 6px 0 0', margin: '0 auto', width: '70%',
                                                                                        background: d.isBest ? '#22c55e' : d.isWorst ? '#ef4444' : '#94a3b8'
                                                                                    } }),
                                                                                    React.createElement('div', { style: { fontSize: 12, fontWeight: 600, marginTop: 6, color: d.isBest ? '#16a34a' : d.isWorst ? '#dc2626' : '#334155' } }, d.day)
                                                                                );
                                                                            })
                                                                        ),
                                                                        React.createElement('div', { style: { padding: 12, background: '#faf5ff', borderRadius: 8, fontSize: 13, color: '#6b21a8' } }, '💡 ' + kwData.optimalTiming.advice)
                                                                    )
                                                            ),

                                                            /* ③ 리뷰 감성 */
                                                            kwData.reviewSentiment && React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 16 } },
                                                                React.createElement('div', { style: { fontSize: 16, fontWeight: 700, marginBottom: 16 } }, '💬 리뷰 감성 분석 — "' + aiSelectedKeyword + '"'),
                                                                kwData.reviewSentiment.alert && React.createElement('div', { style: { marginBottom: 12, padding: 10, borderRadius: 8, fontSize: 13, background: kwData.reviewSentiment.alert.indexOf('급증') !== -1 ? '#fee2e2' : '#dcfce7', color: kwData.reviewSentiment.alert.indexOf('급증') !== -1 ? '#991b1b' : '#166534' } }, '⚠️ ' + kwData.reviewSentiment.alert),
                                                                kwData.reviewSentiment.latest && React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 } },
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#dcfce7', borderRadius: 10, padding: 12, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '긍정'),
                                                                        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: '#16a34a' } }, kwData.reviewSentiment.latest.positiveRate + '%')
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#fee2e2', borderRadius: 10, padding: 12, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '부정'),
                                                                        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: '#dc2626' } }, kwData.reviewSentiment.latest.negativeRate + '%')
                                                                    ),
                                                                    React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f1f5f9', borderRadius: 10, padding: 12, textAlign: 'center' } },
                                                                        React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '중립'),
                                                                        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: '#64748b' } }, (100 - kwData.reviewSentiment.latest.positiveRate - kwData.reviewSentiment.latest.negativeRate).toFixed(1) + '%')
                                                                    )
                                                                ),
                                                                React.createElement('div', { style: { fontSize: 12, color: '#94a3b8' } }, '분석 데이터: ' + kwData.reviewSentiment.dataPoints + '건')
                                                            )
                                                        );
                                                    })()}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
    );
};
