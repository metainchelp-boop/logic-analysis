/* AiFeedbackCard — METAINC AI 피드백 카드 컴포넌트 (자동 실행) */
window.AiFeedbackCard = function AiFeedbackCard(props) {
    var section = props.section;
    var keyword = props.keyword;
    var data = props.data;
    var autoDelay = props.autoDelay || 0;

    var _loading = React.useState(false);
    var loading = _loading[0];
    var setLoading = _loading[1];

    var _feedback = React.useState(null);
    var feedback = _feedback[0];
    var setFeedback = _feedback[1];

    var _error = React.useState('');
    var error = _error[0];
    var setError = _error[1];

    var _lastKeyword = React.useRef('');
    var _timerRef = React.useRef(null);

    if (!keyword || !data) return null;

    var doFetch = function() {
        setLoading(true);
        setError('');
        setFeedback(null);

        fetch('/api/ai/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ section: section, keyword: keyword, data: data })
        }).then(function(r) {
            if (!r.ok) throw new Error('서버 응답 오류 (' + r.status + ')');
            var ct = r.headers.get('content-type') || '';
            if (ct.indexOf('application/json') === -1) throw new Error('서버 응답 오류');
            return r.json();
        }).then(function(res) {
            if (res && res.success && res.data) {
                setFeedback(res.data.feedback);
            } else {
                setError((res && res.error) || 'AI 피드백 생성 실패');
            }
            setLoading(false);
        }).catch(function(e) {
            setError('AI 피드백 요청 실패: ' + (e.message || '네트워크 오류'));
            setLoading(false);
        });
    };

    /* 키워드가 변경되면 자동 실행 (딜레이 적용) — 데이터가 실제로 준비된 경우만 */
    React.useEffect(function() {
        if (!keyword || !data) return;

        /* 키워드가 바뀌었으면 타이머/상태 초기화 */
        if (_lastKeyword.current && _lastKeyword.current !== keyword) {
            if (_timerRef.current) { clearTimeout(_timerRef.current); _timerRef.current = null; }
            _lastKeyword.current = '';
        }

        /* 데이터에 의미 있는 값이 하나라도 있는지 확인 (비동기 로딩 중인 null 데이터 방지) */
        var hasContent = false;
        if (Array.isArray(data)) {
            hasContent = data.length > 0;
        } else if (typeof data === 'object') {
            hasContent = Object.values(data).some(function(v) {
                if (v == null) return false;
                if (Array.isArray(v)) return v.length > 0;
                if (typeof v === 'object') return Object.keys(v).length > 0;
                return true;
            });
        } else {
            hasContent = true;
        }
        if (!hasContent) return;

        if (_lastKeyword.current === keyword) return;
        _lastKeyword.current = keyword;
        setFeedback(null);
        setError('');

        /* 타이머를 ref에 저장 — 부모 재렌더링으로 인한 cleanup에 영향받지 않음 */
        _timerRef.current = setTimeout(function() {
            _timerRef.current = null;
            doFetch();
        }, autoDelay);
    }, [keyword, data]);

    /* 언마운트 시에만 타이머 정리 */
    React.useEffect(function() {
        return function() {
            if (_timerRef.current) clearTimeout(_timerRef.current);
        };
    }, []);

    return React.createElement('div', {
        style: {
            marginTop: 12,
            padding: '14px 18px',
            background: 'linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%)',
            borderRadius: 10,
            border: '1px solid #bae6fd',
            position: 'relative'
        }
    },
        React.createElement('div', {
            style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: feedback ? 10 : 0 }
        },
            React.createElement('div', {
                style: { display: 'flex', alignItems: 'center', gap: 8 }
            },
                React.createElement('span', { style: { fontSize: 16 } }, '🤖'),
                React.createElement('span', {
                    style: { fontSize: 13, fontWeight: 700, color: '#0369a1' }
                }, 'METAINC AI 피드백')
            ),
            !feedback && !loading && React.createElement('button', {
                onClick: doFetch,
                style: {
                    background: 'linear-gradient(135deg, #0ea5e9, #0284c7)',
                    color: '#fff',
                    border: 'none',
                    padding: '6px 16px',
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: 'pointer',
                    transition: 'all 0.2s'
                }
            }, '✨ AI 분석 요청'),
            loading && React.createElement('span', {
                style: { fontSize: 12, color: '#0369a1', fontWeight: 500 }
            }, '⏳ AI 분석 중...'),
            feedback && React.createElement('button', {
                onClick: function() { setFeedback(null); setError(''); },
                style: {
                    background: 'none',
                    border: '1px solid #7dd3fc',
                    color: '#0369a1',
                    padding: '4px 10px',
                    borderRadius: 4,
                    fontSize: 11,
                    cursor: 'pointer'
                }
            }, '다시 분석')
        ),

        error && React.createElement('div', {
            style: { marginTop: 8, padding: '8px 12px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, fontSize: 12, color: '#dc2626' }
        }, error),

        feedback && React.createElement('div', {
            style: { fontSize: 13, lineHeight: 1.8, color: '#1e3a5f', whiteSpace: 'pre-wrap' }
        }, feedback)
    );
};
