/* HtmlDetailAnalysisSection — 상세페이지 HTML 분석 결과 표시 (v5) */
/* SearchBar에서 입력된 HTML → /seo/detail-page API 결과를 시각화 */
window.HtmlDetailAnalysisSection = function HtmlDetailAnalysisSection({ data }) {
    if (!data || !data.scores) return null;

    const getScoreColor = (s) => s >= 70 ? '#10b981' : s >= 40 ? '#f59e0b' : '#ef4444';
    const getScoreLabel = (s) => s >= 70 ? '우수' : s >= 40 ? '보통' : '미흡';
    const getScoreGradient = (s) => s >= 70 ? 'linear-gradient(90deg, #34d399, #059669)' : s >= 40 ? 'linear-gradient(90deg, #fbbf24, #d97706)' : 'linear-gradient(90deg, #f87171, #dc2626)';
    const priorityColor = (p) => p === 'high' ? '#ef4444' : p === 'medium' ? '#f59e0b' : '#64748b';
    const priorityBg = (p) => p === 'high' ? '#fef2f2' : p === 'medium' ? '#fffbeb' : '#f8fafc';
    const priorityLabel = (p) => p === 'high' ? '긴급' : p === 'medium' ? '권장' : '선택';

    const ScoreBar = ({ label, score, icon, weight }) => (
        <div style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 15 }}>{icon}</span> {label}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: getScoreColor(score) }}>{score}점</span>
                    <span style={{ fontSize: 11, color: '#94a3b8' }}>{weight}</span>
                </div>
            </div>
            <div style={{ height: 10, borderRadius: 5, background: '#f1f5f9', overflow: 'hidden' }}>
                <div style={{
                    width: score + '%', height: '100%',
                    background: getScoreGradient(score),
                    borderRadius: 5, transition: 'width 0.8s ease'
                }} />
            </div>
        </div>
    );

    const total = data.scores.total;

    return (
        <div className="section fade-in">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' }}>📄</span>
                    상세페이지 품질 진단 (HTML 분석)
                    <span style={{ fontSize: 10, background: '#ecfdf5', color: '#10b981', padding: '4px 12px', borderRadius: 999, marginLeft: 8, fontWeight: 700 }}>HTML 기반</span>
                </div>
                <div className="section-line"></div>
                <p className="section-subtitle">실제 HTML에서 추출한 데이터 기반 정밀 진단</p>

                {/* v5 2칼럼: 원형 스코어 + 영역별 바 */}
                <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 16, marginBottom: 16 }}>
                    {/* 왼쪽: 원형 스코어 */}
                    <div style={{
                        textAlign: 'center', display: 'flex', flexDirection: 'column',
                        alignItems: 'center', justifyContent: 'center', padding: 28, borderRadius: 16,
                        background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
                    }}>
                        <div style={{ fontSize: 14, fontWeight: 600, color: '#64748b', marginBottom: 16 }}>상세페이지 종합 점수</div>
                        <div style={{
                            width: 120, height: 120, borderRadius: '50%',
                            background: 'conic-gradient(' + getScoreColor(total) + ' ' + (total * 3.6) + 'deg, #f1f5f9 0deg)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12
                        }}>
                            <div style={{
                                width: 96, height: 96, borderRadius: '50%', background: '#fff',
                                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'
                            }}>
                                <div style={{ fontSize: 28, fontWeight: 800, color: getScoreColor(total) }}>{total}</div>
                                <div style={{ fontSize: 11, color: '#94a3b8' }}>/ 100</div>
                            </div>
                        </div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: getScoreColor(total) }}>
                            {getScoreLabel(total)}
                        </div>
                    </div>

                    {/* 오른쪽: 영역별 점수 바 */}
                    <div style={{
                        padding: 24, borderRadius: 16,
                        background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
                    }}>
                        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>📊 영역별 점수</span>
                            <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>비중</span>
                        </div>
                        <ScoreBar label="이미지" score={data.scores.images} icon="🖼️" weight="30%" />
                        <ScoreBar label="텍스트 콘텐츠" score={data.scores.text} icon="📝" weight="20%" />
                        <ScoreBar label="동영상" score={data.scores.video} icon="🎬" weight="15%" />
                        <ScoreBar label="정보 완성도" score={data.scores.info} icon="📋" weight="20%" />
                        <ScoreBar label="신뢰 요소" score={data.scores.trust} icon="🛡️" weight="15%" />
                    </div>
                </div>

                {/* 주요 지표 4칼럼 MetricCard */}
                {data.metrics && (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
                        {[
                            { label: '상품 이미지', value: data.metrics.total_images + '장', icon: '🖼️', good: data.metrics.total_images >= 10 },
                            { label: '텍스트 길이', value: data.metrics.text_length > 1000 ? (data.metrics.text_length / 1000).toFixed(1) + 'K자' : data.metrics.text_length + '자', icon: '📝', good: data.metrics.text_length >= 500 },
                            { label: '동영상', value: data.metrics.video_count + '개', icon: '🎬', good: data.metrics.video_count > 0 },
                            { label: '페이지 크기', value: data.metrics.html_size_kb + 'KB', icon: '📦', good: data.metrics.html_size_kb >= 50 },
                        ].map((item, i) => (
                            <div key={'dp-metric-'+i} style={{
                                textAlign: 'center', padding: 24, borderRadius: 16,
                                background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
                            }}>
                                <div style={{ fontSize: 18, marginBottom: 8 }}>{item.icon}</div>
                                <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 6 }}>{item.label}</div>
                                <div style={{ fontSize: 24, fontWeight: 800, color: item.good ? '#10b981' : '#ef4444' }}>{item.value}</div>
                            </div>
                        ))}
                    </div>
                )}

                {/* 체크리스트 */}
                {data.metrics && (
                    <div style={{
                        padding: 24, borderRadius: 16, marginBottom: 16,
                        background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
                    }}>
                        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 16 }}>✅ 필수 항목 체크리스트</div>
                        {[
                            { label: '배송 정보 (무료배송/당일출고)', checked: data.metrics.has_delivery_info },
                            { label: '교환/반품/환불 정책', checked: data.metrics.has_return_info },
                            { label: '사은품/증정 혜택', checked: data.metrics.has_gift_info },
                            { label: '인증/수상/특허 표시', checked: data.metrics.has_certification },
                            { label: '구매 후기/리뷰 섹션', checked: data.metrics.has_review_section },
                            { label: '스펙/사양 테이블', checked: data.metrics.has_spec_table },
                        ].map((item, i) => (
                            <div key={'dp-check-'+i} style={{
                                display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0',
                                borderBottom: i < 5 ? '1px solid #f1f5f9' : 'none'
                            }}>
                                <span style={{
                                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                    width: 24, height: 24, borderRadius: '50%', fontSize: 12,
                                    background: item.checked ? '#ecfdf5' : '#fef2f2',
                                    color: item.checked ? '#10b981' : '#ef4444',
                                    border: '1px solid ' + (item.checked ? '#a7f3d0' : '#fecaca')
                                }}>
                                    {item.checked ? '✓' : '✗'}
                                </span>
                                <span style={{ fontSize: 13, color: item.checked ? '#0f172a' : '#94a3b8', fontWeight: item.checked ? 500 : 400, flex: 1 }}>
                                    {item.label}
                                </span>
                                <span style={{
                                    padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700,
                                    background: item.checked ? '#ecfdf5' : '#fef2f2',
                                    color: item.checked ? '#10b981' : '#ef4444'
                                }}>
                                    {item.checked ? '확인됨' : '미확인'}
                                </span>
                            </div>
                        ))}
                    </div>
                )}

                {/* 개선 제안 */}
                {data.suggestions && data.suggestions.length > 0 && (
                    <div style={{
                        padding: 24, borderRadius: 16, marginBottom: 16,
                        background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
                    }}>
                        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 16 }}>🔧 상세페이지 개선 제안</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                            {data.suggestions.map((s, i) => (
                                <div key={'dp-sug-'+i} style={{
                                    padding: '16px 20px', background: priorityBg(s.priority), borderRadius: 12,
                                    border: '1px solid #e2e8f0', display: 'flex', gap: 14, alignItems: 'flex-start'
                                }}>
                                    <span style={{
                                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                        width: 28, height: 28, borderRadius: 8, background: priorityColor(s.priority),
                                        color: '#fff', fontSize: 13, fontWeight: 800, flexShrink: 0
                                    }}>
                                        {i + 1}
                                    </span>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                            <span style={{
                                                padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700,
                                                background: priorityColor(s.priority), color: '#fff'
                                            }}>
                                                {priorityLabel(s.priority)}
                                            </span>
                                            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{s.area}</span>
                                        </div>
                                        <div style={{ fontSize: 13, color: '#64748b', lineHeight: 1.7 }}>{s.text}</div>
                                    </div>
                                </div>
                            ))}
                        </div>
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
    );
};
