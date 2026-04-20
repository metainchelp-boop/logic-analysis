/* AiFeedbackAllSection — METAINC AI 통합 피드백 (1회 호출) */
window.AiFeedbackAllSection = function AiFeedbackAllSection(props) {
    var keyword = props.keyword;
    var analysisData = props.analysisData;
    var volumeData = props.volumeData;
    var relatedData = props.relatedData;
    var advertiserReport = props.advertiserReport;

    var _loading = React.useState(false);
    var loading = _loading[0];
    var setLoading = _loading[1];

    var _feedbacks = React.useState(null);
    var feedbacks = _feedbacks[0];
    var setFeedbacks = _feedbacks[1];

    var _fullText = React.useState('');
    var fullText = _fullText[0];
    var setFullText = _fullText[1];

    var _error = React.useState('');
    var error = _error[0];
    var setError = _error[1];

    var _lastKeyword = React.useRef('');
    var _timerRef = React.useRef(null);

    var _expanded = React.useState(true);
    var expanded = _expanded[0];
    var setExpanded = _expanded[1];

    if (!keyword || !analysisData) return null;

    var sectionConfig = [
        { key: 'volume', label: '검색량 분석', icon: '🔍' },
        { key: 'market', label: '시장 규모', icon: '💰' },
        { key: 'competition', label: '경쟁강도', icon: '⚔️' },
        { key: 'related', label: '연관 키워드', icon: '🔗' },
        { key: 'trend', label: '키워드 트렌드', icon: '📈' },
        { key: 'golden', label: '골든 키워드', icon: '🏆' },
        { key: 'competitor', label: '경쟁사 비교', icon: '🏪' },
        { key: 'sales', label: '판매량 추정', icon: '📊' },
        { key: 'strategy', label: '진입 전략', icon: '🎯' },
        { key: 'summary', label: 'METAINC 종합 인사이트', icon: '💡' },
    ];

    var buildSections = function() {
        var sections = {};
        if (volumeData) sections.volume = volumeData;
        if (analysisData.marketRevenue) sections.market = analysisData.marketRevenue;
        if (analysisData.competitionIndex) sections.competition = analysisData.competitionIndex;
        if (relatedData) sections.related = relatedData;
        if (analysisData.keywordTrend) sections.trend = analysisData.keywordTrend;
        if (analysisData.goldenKeyword) sections.golden = analysisData.goldenKeyword;
        if (analysisData.competitorTable) sections.competitor = analysisData.competitorTable;
        if (analysisData.salesEstimation) sections.sales = analysisData.salesEstimation;
        if (advertiserReport || (analysisData && analysisData.strategicAnalysis)) {
            sections.strategy = { advertiserReport: advertiserReport, strategicAnalysis: analysisData.strategicAnalysis };
        }
        return sections;
    };

    var doFetch = function() {
        var sections = buildSections();
        if (Object.keys(sections).length === 0) {
            setError('분석 데이터가 아직 준비되지 않았습니다.');
            return;
        }

        setLoading(true);
        setError('');
        setFeedbacks(null);
        setFullText('');

        api.post('/ai/feedback-all', { keyword: keyword, sections: sections })
        .then(function(res) {
            if (res && res.success && res.data) {
                setFeedbacks(res.data.feedbacks);
                setFullText(res.data.full_text || '');
            } else {
                setError((res && res.error) || 'AI 피드백 생성 실패');
            }
            setLoading(false);
        }).catch(function(e) {
            setError('AI 피드백 요청 실패: ' + (e.message || '네트워크 오류'));
            setLoading(false);
        });
    };

    /* 키워드가 변경되면 자동 실행 (20초 딜레이 — 모든 분석 완료 대기) */
    React.useEffect(function() {
        if (!keyword || !analysisData) return;

        if (_lastKeyword.current && _lastKeyword.current !== keyword) {
            if (_timerRef.current) { clearTimeout(_timerRef.current); _timerRef.current = null; }
            _lastKeyword.current = '';
            setFeedbacks(null);
            setFullText('');
            setError('');
        }

        if (_lastKeyword.current === keyword) return;
        _lastKeyword.current = keyword;

        _timerRef.current = setTimeout(function() {
            _timerRef.current = null;
            doFetch();
        }, 20000);
    }, [keyword, analysisData]);

    React.useEffect(function() {
        return function() {
            if (_timerRef.current) clearTimeout(_timerRef.current);
        };
    }, []);

    return React.createElement('section', { id: 'sec-ai-feedback', className: 'section' },
        React.createElement('div', { className: 'container' },
            React.createElement('div', {
                style: {
                    background: 'linear-gradient(135deg, #0c4a6e 0%, #075985 50%, #0369a1 100%)',
                    borderRadius: 16,
                    padding: '24px 28px',
                    color: '#fff',
                    boxShadow: '0 8px 32px rgba(3, 105, 161, 0.3)'
                }
            },
                /* 헤더 */
                React.createElement('div', {
                    style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: feedbacks ? 20 : 0 }
                },
                    React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12 } },
                        React.createElement('span', { style: { fontSize: 28 } }, '🤖'),
                        React.createElement('div', null,
                            React.createElement('div', { style: { fontSize: 18, fontWeight: 700 } }, 'METAINC AI 종합 분석 리포트'),
                            React.createElement('div', { style: { fontSize: 12, opacity: 0.7, marginTop: 2 } },
                                keyword ? '"' + keyword + '" 키워드 분석 결과' : ''
                            )
                        )
                    ),
                    React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
                        feedbacks && React.createElement('button', {
                            onClick: function() { setExpanded(!expanded); },
                            style: {
                                background: 'rgba(255,255,255,0.15)',
                                border: '1px solid rgba(255,255,255,0.3)',
                                color: '#fff',
                                padding: '6px 14px',
                                borderRadius: 8,
                                fontSize: 12,
                                cursor: 'pointer'
                            }
                        }, expanded ? '접기' : '펼치기'),
                        !loading && React.createElement('button', {
                            onClick: doFetch,
                            style: {
                                background: 'linear-gradient(135deg, #38bdf8, #0ea5e9)',
                                color: '#fff',
                                border: 'none',
                                padding: '8px 20px',
                                borderRadius: 8,
                                fontSize: 13,
                                fontWeight: 600,
                                cursor: 'pointer',
                                boxShadow: '0 4px 12px rgba(14, 165, 233, 0.4)'
                            }
                        }, feedbacks ? '다시 분석' : '✨ AI 종합 분석'),
                        loading && React.createElement('span', {
                            style: { fontSize: 13, color: '#bae6fd', fontWeight: 500 }
                        }, '⏳ AI 분석 중... (약 20~30초)')
                    )
                ),

                /* 에러 */
                error && React.createElement('div', {
                    style: { marginTop: 12, padding: '10px 14px', background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, fontSize: 13, color: '#fecaca' }
                }, error),

                /* 피드백 내용 */
                feedbacks && expanded && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
                    sectionConfig.map(function(sec) {
                        var content = feedbacks[sec.key];
                        if (!content) return null;
                        var isSummary = sec.key === 'summary';
                        return React.createElement('div', {
                            key: sec.key,
                            style: {
                                background: isSummary ? 'rgba(251, 191, 36, 0.12)' : 'rgba(255,255,255,0.08)',
                                borderRadius: 12,
                                padding: '16px 20px',
                                border: isSummary ? '1px solid rgba(251, 191, 36, 0.3)' : '1px solid rgba(255,255,255,0.1)'
                            }
                        },
                            React.createElement('div', {
                                style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }
                            },
                                React.createElement('span', { style: { fontSize: 16 } }, sec.icon),
                                React.createElement('span', {
                                    style: { fontSize: 14, fontWeight: 700, color: isSummary ? '#fbbf24' : '#bae6fd' }
                                }, sec.label)
                            ),
                            React.createElement('div', {
                                style: { fontSize: 13, lineHeight: 1.85, color: '#e0f2fe', whiteSpace: 'pre-wrap' }
                            }, content)
                        );
                    })
                )
            )
        )
    );
};
