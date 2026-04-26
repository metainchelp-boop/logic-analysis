/* FeedbackManagement — 피드백 관리 (manager/superadmin용) v1.1 (리팩토링) */

// 상수를 컴포넌트 외부로 추출 (매 렌더링마다 재생성 방지)
var _fbCategoryLabels = { error: '오류 신고', request: '기능 요청', opinion: '의견/건의', general: '일반' };
var _fbCategoryColors = {
    error: { bg: '#fee2e2', color: '#dc2626' },
    request: { bg: '#dbeafe', color: '#2563eb' },
    opinion: { bg: '#ede9fe', color: '#7c3aed' },
    general: { bg: '#f1f5f9', color: '#64748b' }
};
var _fbStatusLabels = { pending: '대기', resolved: '처리완료', in_progress: '처리중' };
var _fbStatusColors = {
    pending: { bg: '#fef9c3', color: '#ca8a04' },
    resolved: { bg: '#dcfce7', color: '#16a34a' },
    in_progress: { bg: '#dbeafe', color: '#2563eb' }
};
var _fbFilterOptions = ['all', 'pending', 'resolved'];

window.FeedbackManagement = function FeedbackManagement() {
    const { useState, useEffect, useCallback } = React;

    const [feedbacks, setFeedbacks] = useState([]);
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(false);
    const [filter, setFilter] = useState('all');
    const [replyingId, setReplyingId] = useState(null);
    const [replyText, setReplyText] = useState('');

    var loadFeedbacks = useCallback(function() {
        setLoading(true);
        var url = filter === 'all' ? '/chat/feedback' : '/chat/feedback?status=' + filter;
        api.get(url).then(function(res) {
            if (res.success) setFeedbacks(res.data || []);
            setLoading(false);
        }).catch(function() { setLoading(false); });
    }, [filter]);

    var loadStats = useCallback(function() {
        api.get('/chat/feedback/stats').then(function(res) {
            if (res.success) setStats(res.data);
        }).catch(function() {});
    }, []);

    useEffect(function() { loadFeedbacks(); loadStats(); }, [loadFeedbacks, loadStats]);

    var updateFeedback = useCallback(function(id, status, reply) {
        var body = {};
        if (status) body.status = status;
        if (reply !== undefined) body.admin_reply = reply;
        api.put('/chat/feedback/' + id, body).then(function(res) {
            if (res.success) {
                toast.success('피드백이 업데이트되었습니다.');
                loadFeedbacks();
                loadStats();
                setReplyingId(null);
                setReplyText('');
            }
        }).catch(function() {});
    }, [loadFeedbacks, loadStats]);

    var categoryLabels = _fbCategoryLabels;
    var categoryColors = _fbCategoryColors;
    var statusLabels = _fbStatusLabels;
    var statusColors = _fbStatusColors;

    return React.createElement('div', { className: 'card', style: { padding: 20, marginBottom: 20 } },
        React.createElement('div', { style: { fontSize: 18, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 } },
            '💬 피드백 관리',
            stats && React.createElement('span', { style: { fontSize: 12, padding: '2px 8px', borderRadius: 10, background: '#fee2e2', color: '#dc2626', fontWeight: 600 } },
                '대기 ' + stats.pending + '건'
            )
        ),

        /* 통계 요약 */
        stats && React.createElement('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 } },
            React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#f8fafc', borderRadius: 10, padding: 12, textAlign: 'center' } },
                React.createElement('div', { style: { fontSize: 11, color: '#64748b' } }, '전체'),
                React.createElement('div', { style: { fontSize: 20, fontWeight: 700 } }, stats.total)
            ),
            React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#fef9c3', borderRadius: 10, padding: 12, textAlign: 'center' } },
                React.createElement('div', { style: { fontSize: 11, color: '#ca8a04' } }, '대기'),
                React.createElement('div', { style: { fontSize: 20, fontWeight: 700, color: '#ca8a04' } }, stats.pending)
            ),
            React.createElement('div', { style: { flex: 1, minWidth: 100, background: '#dcfce7', borderRadius: 10, padding: 12, textAlign: 'center' } },
                React.createElement('div', { style: { fontSize: 11, color: '#16a34a' } }, '완료'),
                React.createElement('div', { style: { fontSize: 20, fontWeight: 700, color: '#16a34a' } }, stats.resolved)
            ),
            stats.byCategory && Object.keys(stats.byCategory).map(function(cat) {
                var cc = categoryColors[cat] || categoryColors.general;
                return React.createElement('div', { key: cat, style: { flex: 1, minWidth: 100, background: cc.bg, borderRadius: 10, padding: 12, textAlign: 'center' } },
                    React.createElement('div', { style: { fontSize: 11, color: cc.color } }, categoryLabels[cat] || cat),
                    React.createElement('div', { style: { fontSize: 20, fontWeight: 700, color: cc.color } }, stats.byCategory[cat])
                );
            })
        ),

        /* 필터 */
        React.createElement('div', { style: { display: 'flex', gap: 8, marginBottom: 16 } },
            _fbFilterOptions.map(function(f) {
                var label = f === 'all' ? '전체' : statusLabels[f] || f;
                return React.createElement('button', {
                    key: f,
                    onClick: function() { setFilter(f); },
                    style: {
                        padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                        background: filter === f ? '#1B2A4A' : '#f1f5f9',
                        color: filter === f ? '#fff' : '#64748b',
                        border: 'none'
                    }
                }, label);
            })
        ),

        /* 피드백 리스트 */
        loading && React.createElement('div', { style: { textAlign: 'center', padding: 20, color: '#94a3b8' } }, '로딩 중...'),

        !loading && feedbacks.length === 0 && React.createElement('div', { style: { textAlign: 'center', padding: 30, color: '#94a3b8', fontSize: 13 } },
            '아직 접수된 피드백이 없습니다.'
        ),

        !loading && feedbacks.map(function(fb) {
            var cc = categoryColors[fb.category] || categoryColors.general;
            var sc = statusColors[fb.status] || statusColors.pending;
            return React.createElement('div', {
                key: fb.id,
                style: { padding: '14px 16px', marginBottom: 8, borderRadius: 10, border: '1px solid #e2e8f0', background: '#fff' }
            },
                /* 상단: 카테고리/상태/날짜 */
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 } },
                    React.createElement('span', { style: { padding: '2px 8px', borderRadius: 8, fontSize: 11, fontWeight: 600, background: cc.bg, color: cc.color } },
                        categoryLabels[fb.category] || fb.category
                    ),
                    React.createElement('span', { style: { padding: '2px 8px', borderRadius: 8, fontSize: 11, fontWeight: 600, background: sc.bg, color: sc.color } },
                        statusLabels[fb.status] || fb.status
                    ),
                    React.createElement('span', { style: { fontSize: 12, color: '#94a3b8' } }, fb.username),
                    React.createElement('div', { style: { flex: 1 } }),
                    React.createElement('span', { style: { fontSize: 11, color: '#94a3b8' } }, (fb.created_at || '').slice(0, 16))
                ),
                /* 내용 */
                React.createElement('div', { style: { fontSize: 13, color: '#1e293b', lineHeight: 1.6, marginBottom: 8 } }, fb.content),
                /* 관리자 답변 */
                fb.admin_reply && React.createElement('div', { style: { padding: 10, background: '#f0fdf4', borderRadius: 8, fontSize: 12, color: '#166534', marginBottom: 8 } },
                    '💬 관리자 답변: ' + fb.admin_reply
                ),
                /* 액션 버튼 */
                React.createElement('div', { style: { display: 'flex', gap: 8 } },
                    fb.status !== 'resolved' && React.createElement('button', {
                        onClick: function() { updateFeedback(fb.id, 'resolved'); },
                        style: { padding: '4px 10px', borderRadius: 6, fontSize: 11, cursor: 'pointer', background: '#dcfce7', color: '#16a34a', border: '1px solid #bbf7d0', fontWeight: 600 }
                    }, '✓ 처리완료'),
                    React.createElement('button', {
                        onClick: function() { setReplyingId(replyingId === fb.id ? null : fb.id); setReplyText(fb.admin_reply || ''); },
                        style: { padding: '4px 10px', borderRadius: 6, fontSize: 11, cursor: 'pointer', background: '#dbeafe', color: '#2563eb', border: '1px solid #bfdbfe', fontWeight: 600 }
                    }, '💬 답변')
                ),
                /* 답변 입력 */
                replyingId === fb.id && React.createElement('div', { style: { marginTop: 8, display: 'flex', gap: 8 } },
                    React.createElement('input', {
                        value: replyText,
                        onChange: function(e) { setReplyText(e.target.value); },
                        placeholder: '답변을 입력하세요...',
                        style: { flex: 1, padding: '6px 10px', borderRadius: 6, border: '1px solid #e2e8f0', fontSize: 12, outline: 'none' }
                    }),
                    React.createElement('button', {
                        onClick: function() { updateFeedback(fb.id, null, replyText); },
                        style: { padding: '6px 12px', borderRadius: 6, fontSize: 11, cursor: 'pointer', background: '#1B2A4A', color: '#fff', border: 'none', fontWeight: 600 }
                    }, '저장')
                )
            );
        })
    );
};
