/* HtmlDetailAnalysisSection — 상세페이지 HTML 분석 결과 표시 (v4.0.1) */
/* SearchBar에서 입력된 HTML → /seo/detail-page API 결과를 시각화 */
window.HtmlDetailAnalysisSection = function HtmlDetailAnalysisSection({ data }) {
    if (!data || !data.scores) return null;

    const scoreGradient = (s) => s >= 70 ? 'linear-gradient(90deg, #34d399, #059669)' : s >= 40 ? 'linear-gradient(90deg, #fbbf24, #d97706)' : 'linear-gradient(90deg, #f87171, #dc2626)';
    const dpScoreLabel = (s) => s >= 70 ? '우수' : s >= 40 ? '보통' : '미흡';
    const priorityColor = (p) => p === 'high' ? '#dc2626' : p === 'medium' ? '#d97706' : '#6b7280';
    const priorityBg = (p) => p === 'high' ? '#fef2f2' : p === 'medium' ? '#fffbeb' : '#f9fafb';
    const priorityLabel = (p) => p === 'high' ? '긴급' : p === 'medium' ? '권장' : '선택';

    return (
        <div className="section fade-in">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: '#fef3c7' }}>📄</span>
                    상세페이지 품질 진단 (HTML 분석)
                    <span style={{ fontSize: 10, background: '#ecfdf5', color: '#059669', padding: '2px 8px', borderRadius: 10, marginLeft: 8, fontWeight: 700 }}>HTML 기반</span>
                </div>

                {/* 종합 점수 카드 */}
                <div className="card" style={{ textAlign: 'center', marginBottom: 16, padding: '20px', background: scoreBg(data.scores.total) }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>상세페이지 종합 점수</div>
                    <div style={{
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        width: 72, height: 72, borderRadius: '50%',
                        background: '#fff', border: '4px solid ' + scoreColor(data.scores.total),
                        fontSize: 26, fontWeight: 800, color: scoreColor(data.scores.total)
                    }}>
                        {data.scores.total}
                    </div>
                    <div style={{ marginTop: 6, fontSize: 13, fontWeight: 700, color: scoreColor(data.scores.total) }}>
                        {dpScoreLabel(data.scores.total)}
                    </div>
                </div>

                {/* 5대 영역 점수 바 차트 */}
                <div className="card" style={{ marginBottom: 16 }}>
                    <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12, display: 'flex', justifyContent: 'space-between' }}>
                        <span>📊 영역별 점수</span>
                        <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>비중</span>
                    </div>
                    {[
                        { label: '이미지', score: data.scores.images, icon: '🖼️', weight: '30%' },
                        { label: '텍스트 콘텐츠', score: data.scores.text, icon: '📝', weight: '20%' },
                        { label: '동영상', score: data.scores.video, icon: '🎬', weight: '15%' },
                        { label: '정보 완성도', score: data.scores.info, icon: '📋', weight: '20%' },
                        { label: '신뢰 요소', score: data.scores.trust, icon: '🛡️', weight: '15%' },
                    ].map((item, i) => (
                        <div key={'dp-bar-'+i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: i < 4 ? '1px solid #f1f5f9' : 'none' }}>
                            <span style={{ fontSize: 16, width: 24, textAlign: 'center' }}>{item.icon}</span>
                            <span style={{ fontSize: 13, fontWeight: 600, color: '#334155', width: 100, flexShrink: 0 }}>{item.label}</span>
                            <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 6, height: 22, position: 'relative', overflow: 'hidden' }}>
                                <div style={{
                                    width: item.score + '%', height: '100%',
                                    background: scoreGradient(item.score),
                                    borderRadius: 6, transition: 'width 0.8s ease'
                                }} />
                                <span style={{ position: 'absolute', right: 8, top: 2, fontSize: 11, fontWeight: 700, color: '#1e293b' }}>{item.score}점</span>
                            </div>
                            <span style={{ fontSize: 11, color: '#94a3b8', width: 36, textAlign: 'right', flexShrink: 0 }}>{item.weight}</span>
                        </div>
                    ))}
                </div>

                {/* 주요 지표 카드 그리드 */}
                {data.metrics && (
                    <div className="card-grid card-grid-4" style={{ marginBottom: 16 }}>
                        {[
                            { label: '상품 이미지', value: data.metrics.total_images + '장', icon: '🖼️', good: data.metrics.total_images >= 10 },
                            { label: '텍스트 길이', value: data.metrics.text_length > 1000 ? (data.metrics.text_length / 1000).toFixed(1) + 'K자' : data.metrics.text_length + '자', icon: '📝', good: data.metrics.text_length >= 500 },
                            { label: '동영상', value: data.metrics.video_count + '개', icon: '🎬', good: data.metrics.video_count > 0 },
                            { label: '페이지 크기', value: data.metrics.html_size_kb + 'KB', icon: '📦', good: data.metrics.html_size_kb >= 50 },
                        ].map((item, i) => (
                            <div className="card" key={'dp-metric-'+i} style={{ textAlign: 'center', padding: '12px 8px' }}>
                                <div style={{ fontSize: 18, marginBottom: 4 }}>{item.icon}</div>
                                <div style={{ fontSize: 16, fontWeight: 700, color: item.good ? '#059669' : '#dc2626' }}>{item.value}</div>
                                <div style={{ fontSize: 11, color: '#64748b' }}>{item.label}</div>
                            </div>
                        ))}
                    </div>
                )}

                {/* 체크리스트 */}
                {data.metrics && (
                    <div className="card" style={{ marginBottom: 16 }}>
                        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>✅ 필수 항목 체크리스트</div>
                        {[
                            { label: '배송 정보 (무료배송/당일출고)', checked: data.metrics.has_delivery_info },
                            { label: '교환/반품/환불 정책', checked: data.metrics.has_return_info },
                            { label: '사은품/증정 혜택', checked: data.metrics.has_gift_info },
                            { label: '인증/수상/특허 표시', checked: data.metrics.has_certification },
                            { label: '구매 후기/리뷰 섹션', checked: data.metrics.has_review_section },
                            { label: '스펙/사양 테이블', checked: data.metrics.has_spec_table },
                        ].map((item, i) => (
                            <div key={'dp-check-'+i} style={{
                                display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0',
                                borderBottom: i < 5 ? '1px solid #f1f5f9' : 'none'
                            }}>
                                <span style={{
                                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                    width: 22, height: 22, borderRadius: '50%', fontSize: 12,
                                    background: item.checked ? '#ecfdf5' : '#fef2f2',
                                    color: item.checked ? '#059669' : '#dc2626',
                                    border: '1px solid ' + (item.checked ? '#a7f3d0' : '#fecaca')
                                }}>
                                    {item.checked ? '✓' : '✗'}
                                </span>
                                <span style={{ fontSize: 13, color: item.checked ? '#334155' : '#94a3b8', fontWeight: item.checked ? 500 : 400 }}>
                                    {item.label}
                                </span>
                                <span style={{
                                    marginLeft: 'auto', fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
                                    background: item.checked ? '#ecfdf5' : '#fef2f2',
                                    color: item.checked ? '#059669' : '#dc2626'
                                }}>
                                    {item.checked ? '확인됨' : '미확인'}
                                </span>
                            </div>
                        ))}
                    </div>
                )}

                {/* 개선 제안 */}
                {data.suggestions && data.suggestions.length > 0 && (
                    <div className="card" style={{ marginBottom: 16 }}>
                        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>🔧 상세페이지 개선 제안</div>
                        {data.suggestions.map((s, i) => (
                            <div key={'dp-sug-'+i} style={{
                                padding: '12px 14px', marginBottom: i < data.suggestions.length - 1 ? 10 : 0,
                                background: priorityBg(s.priority), borderRadius: 8,
                                border: '1px solid ' + (s.priority === 'high' ? '#fecaca' : s.priority === 'medium' ? '#fed7aa' : '#e5e7eb')
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                    <span style={{
                                        fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
                                        background: priorityColor(s.priority), color: '#fff'
                                    }}>
                                        {priorityLabel(s.priority)}
                                    </span>
                                    <span style={{ fontSize: 13, fontWeight: 600, color: '#334155' }}>{s.area}</span>
                                </div>
                                <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.7 }}>{s.text}</div>
                            </div>
                        ))}
                    </div>
                )}

                {/* 안내 */}
                <div style={{ padding: '10px 14px', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 11, color: '#94a3b8', lineHeight: 1.7 }}>
                    ※ 상세페이지 분석은 검색바에 입력된 HTML을 직접 파싱하여 수행합니다. 네이버의 봇 차단으로 서버측 크롤링이 불가능하여 이 방식을 사용합니다.
                </div>
            </div>
        </div>
    );
};
