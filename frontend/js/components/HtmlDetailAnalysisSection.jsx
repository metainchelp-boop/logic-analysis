/* HtmlDetailAnalysisSection — 상세페이지 HTML 분석 결과 표시 (v5) */
/* SearchBar에서 입력된 HTML → /seo/detail-page API 결과를 시각화 */
window.HtmlDetailAnalysisSection = function HtmlDetailAnalysisSection({ data }) {
    if (!data || !data.scores) return null;

    const getScoreColor = (s) => s >= 70 ? '#10b981' : s >= 40 ? '#f59e0b' : '#ef4444';
    const getScoreLabel = (s) => s >= 70 ? '우수' : s >= 40 ? '보통' : '미흡';
    const priorityLabel = (p) => p === 'high' ? '긴급' : p === 'medium' ? '권장' : '선택';

    const ScoreBar = ({ label, score, weight }) => (
        <div className="scorebar">
            <div className="lbl"><b>{label}</b><span className="w">{weight}</span></div>
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
                <div className="grid2" style={{ alignItems: 'center' }}>
                    {/* 왼쪽: 도넛 차트 (고정 크기로 가두기 → 오버플로우 방지 + 중앙 점수) */}
                    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', padding: '6px 0' }}>
                        <div style={{ position: 'relative', width: 180, height: 180 }}>
                            <ChartCanvas
                                type="doughnut"
                                height={180}
                                style={{ height: 180, width: 180 }}
                                data={{ labels: ['점수', '잔여'], datasets: [{ data: [total, Math.max(0, 100 - total)], backgroundColor: [getScoreColor(total), '#f1f5f9'], borderWidth: 0 }] }}
                                options={{ maintainAspectRatio: false, cutout: '78%', plugins: { legend: { display: false }, tooltip: { enabled: false } } }}
                            />
                            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
                                <div style={{ fontSize: 30, fontWeight: 900, color: getScoreColor(total), lineHeight: 1.1 }}>{total}</div>
                                <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>/100 · {getScoreLabel(total)}</div>
                            </div>
                        </div>
                    </div>

                    {/* 오른쪽: 영역별 점수 바 */}
                    <div>
                        <ScoreBar label="이미지" score={data.scores.images} weight="30%" />
                        <ScoreBar label="텍스트" score={data.scores.text} weight="20%" />
                        <ScoreBar label="동영상" score={data.scores.video} weight="15%" />
                        <ScoreBar label="정보 완성도" score={data.scores.info} weight="20%" />
                        <ScoreBar label="신뢰 요소" score={data.scores.trust} weight="15%" />
                    </div>
                </div>

                {/* 주요 지표 4칼럼 MetricCard */}
                {data.metrics && (
                    <div className="grid4" style={{ marginTop: 10 }}>
                        {[
                            { label: '상품 이미지', num: data.metrics.total_images, unit: '장', good: data.metrics.total_images >= 10 },
                            { label: '텍스트 길이', num: data.metrics.text_length > 1000 ? (data.metrics.text_length / 1000).toFixed(1) + 'K' : data.metrics.text_length, unit: '자', good: data.metrics.text_length >= 500 },
                            { label: '동영상', num: data.metrics.video_count, unit: '개', good: data.metrics.video_count > 0 },
                            { label: '페이지 크기', num: data.metrics.html_size_kb, unit: 'KB', good: data.metrics.html_size_kb >= 50 },
                        ].map((item, i) => (
                            <div key={'dp-metric-'+i} className="kpi">
                                <div className="k">{item.label}</div>
                                <div className="v" style={{ color: item.good ? undefined : 'var(--red)' }}>{item.num}<small>{item.unit}</small></div>
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

                </div>
            </div>
        </div>
    );
};
