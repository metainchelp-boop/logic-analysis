/* HtmlDetailAnalysisSection — 상세페이지 HTML 분석 결과 표시 (v5) */
/* SearchBar에서 입력된 HTML → /seo/detail-page API 결과를 시각화 */
window.HtmlDetailAnalysisSection = function HtmlDetailAnalysisSection({ data }) {
    if (!data || !data.scores) return null;

    const getScoreColor = (s) => s >= 70 ? '#10b981' : s >= 40 ? '#f59e0b' : '#ef4444';
    const getScoreLabel = (s) => s >= 70 ? '우수' : s >= 40 ? '보통' : '미흡';
    const priorityLabel = (p) => p === 'high' ? '긴급' : p === 'medium' ? '권장' : '선택';

    const ScoreBar = ({ label, score, icon, weight }) => (
        <div className="scorebar">
            <div className="lbl"><b>{icon} {label}</b><span className="w">{weight}</span></div>
            <div className="track"><i style={{ width: score + '%' }} /></div>
        </div>
    );

    const total = data.scores.total;

    return (
        <div className="section fade-in">
            <div className="container">
                <div className="card" style={{ padding: '20px 22px' }}>
                <h3 className="rt-h3"><span className="rt-hic">🖼️</span>④ 상세페이지 HTML 분석<span className="badge b-est">≈ 추정</span></h3>
                <div className="rt-desc">실제 HTML에서 추출한 데이터 기반 정밀 진단</div>

                {/* v5 2칼럼: 원형 스코어 + 영역별 바 */}
                <div className="grid2" style={{ alignItems: 'center', marginBottom: 16 }}>
                    {/* 왼쪽: 원형 스코어 */}
                    <div style={{
                        textAlign: 'center', display: 'flex', flexDirection: 'column',
                        alignItems: 'center', justifyContent: 'center'
                    }}>
                        <div style={{ fontSize: 14, fontWeight: 600, color: '#64748b', marginBottom: 16 }}>상세페이지 종합 점수</div>
                        <div style={{ position: 'relative', width: 120, height: 120, marginBottom: 12 }}>
                            <ChartCanvas
                                type="doughnut"
                                height={120}
                                data={{ labels: ['점수', '잔여'], datasets: [{ data: [total, Math.max(0, 100 - total)], backgroundColor: [getScoreColor(total), '#f1f5f9'], borderWidth: 0 }] }}
                                options={{ cutout: '78%', plugins: { legend: { display: false }, tooltip: { enabled: false } } }}
                            />
                            <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                                <div style={{ fontSize: 28, fontWeight: 800, color: getScoreColor(total) }}>{total}</div>
                                <div style={{ fontSize: 11, color: '#94a3b8' }}>/ 100</div>
                            </div>
                        </div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: getScoreColor(total) }}>
                            {getScoreLabel(total)}
                        </div>
                    </div>

                    {/* 오른쪽: 영역별 점수 바 */}
                    <div>
                        <ScoreBar label="이미지" score={data.scores.images} icon="🖼️" weight="30%" />
                        <ScoreBar label="텍스트 콘텐츠" score={data.scores.text} icon="📝" weight="20%" />
                        <ScoreBar label="동영상" score={data.scores.video} icon="🎬" weight="15%" />
                        <ScoreBar label="정보 완성도" score={data.scores.info} icon="📋" weight="20%" />
                        <ScoreBar label="신뢰 요소" score={data.scores.trust} icon="🛡️" weight="15%" />
                    </div>
                </div>

                {/* 영역별 점수 레이더 */}
                <div style={{ padding: 24, borderRadius: 16, marginBottom: 16, background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
                    <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>📡 영역별 균형 (레이더)</div>
                    <ChartCanvas
                        type="radar"
                        height={300}
                        data={{
                            labels: ['이미지', '텍스트', '동영상', '정보 완성도', '신뢰 요소'],
                            datasets: [{
                                label: '점수',
                                data: [data.scores.images || 0, data.scores.text || 0, data.scores.video || 0, data.scores.info || 0, data.scores.trust || 0],
                                borderColor: '#4f46e5', backgroundColor: 'rgba(79,70,229,.18)', pointBackgroundColor: '#4f46e5', borderWidth: 2
                            }]
                        }}
                        options={{
                            plugins: { legend: { display: false }, tooltip: { callbacks: { label: function(ctx) { return ctx.label + ' ' + ctx.parsed.r + '점'; } } } },
                            scales: { r: { beginAtZero: true, max: 100, ticks: { display: false }, pointLabels: { font: { size: 11 } } } }
                        }}
                    />
                </div>

                {/* 주요 지표 4칼럼 MetricCard */}
                {data.metrics && (
                    <div className="grid4" style={{ marginTop: 10, marginBottom: 16 }}>
                        {[
                            { label: '상품 이미지', value: data.metrics.total_images + '장', icon: '🖼️', good: data.metrics.total_images >= 10 },
                            { label: '텍스트 길이', value: data.metrics.text_length > 1000 ? (data.metrics.text_length / 1000).toFixed(1) + 'K자' : data.metrics.text_length + '자', icon: '📝', good: data.metrics.text_length >= 500 },
                            { label: '동영상', value: data.metrics.video_count + '개', icon: '🎬', good: data.metrics.video_count > 0 },
                            { label: '페이지 크기', value: data.metrics.html_size_kb + 'KB', icon: '📦', good: data.metrics.html_size_kb >= 50 },
                        ].map((item, i) => (
                            <div key={'dp-metric-'+i} className="kpi">
                                <div className="k">{item.icon} {item.label}</div>
                                <div className="v" style={{ fontSize: 18, color: item.good ? undefined : 'var(--red)' }}>{item.value}</div>
                            </div>
                        ))}
                    </div>
                )}

                {/* 체크리스트 */}
                {data.metrics && (() => {
                    const checkItems = [
                        { label: '배송 정보 (무료배송/당일출고)', checked: data.metrics.has_delivery_info },
                        { label: '교환/반품/환불 정책', checked: data.metrics.has_return_info },
                        { label: '사은품/증정 혜택', checked: data.metrics.has_gift_info },
                        { label: '인증/수상/특허 표시', checked: data.metrics.has_certification },
                        { label: '구매 후기/리뷰 섹션', checked: data.metrics.has_review_section },
                        { label: '스펙/사양 테이블', checked: data.metrics.has_spec_table },
                    ];
                    const half = Math.ceil(checkItems.length / 2);
                    const cols = [checkItems.slice(0, half), checkItems.slice(half)];
                    return (
                        <div className="sub-card">
                            <div className="st">필수 항목 체크리스트</div>
                            <div className="grid2">
                                {cols.map((col, ci) => (
                                    <div key={'dp-check-col-'+ci}>
                                        {col.map((item, i) => (
                                            <div key={'dp-check-'+ci+'-'+i} className="check">
                                                <span className={item.checked ? 'y' : 'n'}>{item.checked ? '✔' : '✘'}</span> {item.label}
                                            </div>
                                        ))}
                                    </div>
                                ))}
                            </div>
                        </div>
                    );
                })()}

                {/* 개선 제안 */}
                {data.suggestions && data.suggestions.length > 0 && (
                    <div className="note est">
                        <b>개선 제안</b>
                        {data.suggestions.map((s, i) => (
                            <span key={'dp-sug-'+i}>
                                {' · '}
                                <span className={'sev ' + (s.priority === 'high' ? 'high' : s.priority === 'medium' ? 'med' : 'low')}>{priorityLabel(s.priority)}</span>
                                {' '}{s.area ? s.area + ' — ' : ''}{s.text}
                            </span>
                        ))}
                    </div>
                )}

                {/* 안내 */}
                <div style={{
                    padding: '12px 16px', background: '#f8fafc', borderRadius: 12,
                    border: '1px solid #e2e8f0', fontSize: 12, color: '#94a3b8', lineHeight: 1.7
                }}>
                    ※ 상세페이지 분석은 검색바에 입력된 HTML을 직접 파싱하여 수행합니다. 네이버의 봇 차단으로 서버측 크롤링이 불가능하여 이 방식을 사용합니다.
                </div>
                </div>
            </div>
        </div>
    );
};
