/* AiFeedbackCard — METAINC AI 피드백 카드 컴포넌트 */
window.AiFeedbackCard = function AiFeedbackCard(props) {
    var useState = React.useState;
    var section = props.section;     // 섹션 ID (volume, competition 등)
    var keyword = props.keyword;     // 분석 키워드
    var data = props.data;           // 해당 섹션 분석 데이터

    var _loading = useState(false);
    var loading = _loading[0];
    var setLoading = _loading[1];

    var _feedback = useState(null);
    var feedback = _feedback[0];
    var setFeedback = _feedback[1];

    var _error = useState('');
    var error = _error[0];
    var setError = _error[1];

    var fetchFeedback = function() {
        if (loading || !keyword || !data) return;
        setLoading(true);
        setError('');
        setFeedback(null);

        fetch('/api/ai/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ section: section, keyword: keyword, data: data })
        }).then(function(r) {
            if (!r.ok) throw new Error('서버 응답 오류 (' + r.status + '). 잠시 후 다시 시도해주세요.');
            var ct = r.headers.get('content-type') || '';
            if (ct.indexOf('application/json') === -1) throw new Error('서버가 일시적으로 응답할 수 없습니다. 잠시 후 다시 시도해주세요.');
            return r.json();
        }).then(function(res) {
            if (res && res.success && res.data) {
                setFeedback(res.data.feedback);
            } else {
                setError((res && res.error) || 'METAINC AI 피드백 생성에 실패했습니다.');
            }
            setLoading(false);
        }).catch(function(e) {
            setError('METAINC AI 피드백 요청 실패: ' + (e.message || '네트워크 오류'));
            setLoading(false);
        });
    };

    if (!keyword || !data) return null;

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
                onClick: fetchFeedback,
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
