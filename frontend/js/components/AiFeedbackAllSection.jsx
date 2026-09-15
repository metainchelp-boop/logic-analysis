/* AiFeedbackAllSection — METAINC AI 통합 피드백 (1회 호출) */
window.AiFeedbackAllSection = function AiFeedbackAllSection(props) {
    var keyword = props.keyword;
    var analysisData = props.analysisData;
    var volumeData = props.volumeData;
    var relatedData = props.relatedData;
    var advertiserReport = props.advertiserReport;
    var htmlReviewData = props.htmlReviewData;
    var datalabData = props.datalabData;
    /* ⚠️ 선택 props — 안 넘겨주면 undefined 라 아래에서 **종전과 같은 20초 고정 대기**로 떨어진다.
     *    (무회귀: 이 파일을 쓰는 다른 화면이 있어도 동작이 바뀌지 않는다) */
    var datalabLoading = props.datalabLoading;
    var advertiserLoading = props.advertiserLoading;

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
        // R5: AI가 방어자/신규진입을 판단하고 시즌·리뷰격차를 인용하도록 자기상태·리뷰·시즌을 주입
        if (analysisData.reviewAnalysis) sections.review = analysisData.reviewAnalysis;
        if (datalabData && (datalabData.season || datalabData.trend || datalabData.growth)) {
            sections.season = { season: datalabData.season, trend: datalabData.trend, growth: datalabData.growth };
        }
        var _myRank = (advertiserReport && advertiserReport.ranking && advertiserReport.ranking.current_rank != null)
            ? advertiserReport.ranking.current_rank
            : (analysisData.targetProductInfo && analysisData.targetProductInfo.rank != null ? analysisData.targetProductInfo.rank : null);
        var _myReviews = (htmlReviewData && htmlReviewData.reviewCount != null) ? htmlReviewData.reviewCount : null;
        var _top5Reviews = (analysisData.reviewAnalysis && analysisData.reviewAnalysis.reviewCount) ? analysisData.reviewAnalysis.reviewCount.top5 : null;
        sections.mystatus = {
            myRank: _myRank,
            myActualReviews: _myReviews,
            top5AvgReviews: _top5Reviews,
            isDefender: (_myRank != null && _myRank <= 10) || (_myReviews != null && _myReviews >= 100)
        };
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

    /* 키워드가 변경되면 자동 실행.
     *
     * ⚠️ **종전엔 무조건 20초를 기다렸다** — 「모든 분석 완료 대기」라는 이름이었지만
     *    실제로 끝났는지는 안 보고 시계만 봤다. 자료가 3초 만에 다 와도 17초를 흘려보냈고,
     *    영업 자료 한 건마다 그 시간이 그대로 쌓였다(2026-09-15 대표 지시로 개선).
     *
     * ⇒ 이제 **늦게 오는 두 가지(데이터랩·진입 전략)가 끝났는지**를 보고 그 즉시 시작한다.
     *    끝났다 = 로딩 플래그가 꺼졌다(성공이든 실패든 「더 기다릴 것이 없다」는 뜻).
     *
     * ⚠️ 안전장치 둘을 같이 둔다:
     *    ① 플래그를 안 넘겨주는 화면에서는 **종전 그대로 20초**(무회귀)
     *    ② 플래그가 어떤 이유로든 안 꺼지면 20초에 **강제로** 시작(영영 안 도는 것 방지)
     *    ③ 자료가 다 와도 **0.6초는 둔다** — 마지막 setState 가 화면에 반영될 틈
     *      (AI 는 화면 값이 아니라 props 로 읽지만, 같은 틱에 몰린 갱신을 한 번에 태운다) */
    var FALLBACK_MS = 20000;
    var SETTLE_MS = 600;
    var _startedAt = React.useRef(0);

    React.useEffect(function() {
        if (!keyword || !analysisData) return;

        if (_lastKeyword.current && _lastKeyword.current !== keyword) {
            if (_timerRef.current) { clearTimeout(_timerRef.current); _timerRef.current = null; }
            _lastKeyword.current = '';
            _startedAt.current = 0;
            setFeedbacks(null);
            setFullText('');
            setError('');
        }

        if (_lastKeyword.current === keyword) return;
        _lastKeyword.current = keyword;
        _startedAt.current = Date.now();

        _timerRef.current = setTimeout(function() {
            _timerRef.current = null;
            doFetch();
        }, FALLBACK_MS);
    }, [keyword, analysisData]);

    /* 늦게 오는 것들이 끝나면 위 예약을 앞당긴다 — 못 앞당기면 위 20초가 그대로 돈다. */
    React.useEffect(function() {
        if (!keyword || !analysisData) return;
        if (_lastKeyword.current !== keyword) return;
        if (!_timerRef.current) return;                       // 이미 시작했거나 예약이 없다
        if (datalabLoading === undefined && advertiserLoading === undefined) return;  // 옛 호출부 → 20초 유지
        if (datalabLoading || advertiserLoading) return;      // 아직 오는 중

        var waited = Date.now() - (_startedAt.current || Date.now());
        var wait = Math.max(0, SETTLE_MS - waited);
        clearTimeout(_timerRef.current);
        _timerRef.current = setTimeout(function() {
            _timerRef.current = null;
            doFetch();
        }, wait);
    }, [keyword, analysisData, datalabLoading, advertiserLoading, datalabData, advertiserReport]);

    React.useEffect(function() {
        return function() {
            if (_timerRef.current) clearTimeout(_timerRef.current);
        };
    }, []);

    return React.createElement('section', { id: 'sec-ai-feedback', className: 'section' },
        /* 내보내기용 숨김 상태 마커 — ReportCapture가 읽어 미완료 시 로딩 문구 박제를 차단 */
        React.createElement('span', {
            className: 'ai-state',
            style: { display: 'none' },
            'data-state': loading ? 'loading' : (feedbacks ? 'done' : 'idle')
        }),
        React.createElement('div', { className: 'container' },
            React.createElement('div', {
                className: 'card',
                style: { padding: '20px 22px', border: '2px dashed #c7d2fe', background: 'linear-gradient(135deg,#eef2ff,#faf5ff)' }
            },
                /* 헤더 */
                React.createElement('div', {
                    style: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }
                },
                    React.createElement('div', null,
                        React.createElement('h3', { className: 'rt-h3' },
                            React.createElement('span', { className: 'rt-hic' }, '🤖'),
                            'METAINC AI 종합 분석 리포트',
                            React.createElement('span', { className: 'badge b-ai' }, 'AI')
                        ),
                        React.createElement('div', { className: 'rt-desc' },
                            keyword ? '"' + keyword + '" 키워드를 AI가 전체 데이터를 종합해 작성한 분석' : 'AI가 전체 데이터를 종합해 작성한 분석'
                        )
                    ),
                    React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 } },
                        feedbacks && React.createElement('button', {
                            onClick: function() { setExpanded(!expanded); },
                            style: {
                                background: '#f1f5f9',
                                border: '1px solid #e2e8f0',
                                color: '#475569',
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
                        /* no-export: 상태 마커가 실패해도 로딩 문구만은 전달본에서 항상 제거(이중 방어) */
                        loading && React.createElement('span', {
                            className: 'no-export',
                            style: { fontSize: 13, color: '#0ea5e9', fontWeight: 500 }
                        }, '⏳ AI 분석 중... (약 20~30초)')
                    )
                ),

                /* 에러 */
                error && React.createElement('div', {
                    style: { marginTop: 12, padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, fontSize: 13, color: '#b91c1c' }
                }, error),

                /* 피드백 내용 */
                feedbacks && expanded && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16, marginTop: 18 } },
                    sectionConfig.map(function(sec) {
                        var content = feedbacks[sec.key];
                        if (!content) return null;
                        var isSummary = sec.key === 'summary';
                        return React.createElement('div', {
                            key: sec.key,
                            style: {
                                background: isSummary ? '#fffbeb' : '#f8fafc',
                                borderRadius: 12,
                                padding: '16px 20px',
                                border: isSummary ? '1px solid #fde68a' : '1px solid #e2e8f0'
                            }
                        },
                            React.createElement('div', {
                                style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }
                            },
                                React.createElement('span', { style: { fontSize: 16 } }, sec.icon),
                                React.createElement('span', {
                                    style: { fontSize: 14, fontWeight: 700, color: isSummary ? '#b45309' : '#0369a1' }
                                }, sec.label)
                            ),
                            React.createElement('div', {
                                style: { fontSize: 13, lineHeight: 1.75, color: '#334155', whiteSpace: 'pre-wrap' }
                            }, content)
                        );
                    })
                )
            )
        )
    );
};
