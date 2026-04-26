/* ChatWidget — 플로팅 AI 채팅 위젯 v1.0 */
window.ChatWidget = function ChatWidget({ currentUser }) {
    const { useState, useEffect, useRef, useCallback } = React;

    const [isOpen, setIsOpen] = useState(false);
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const [unread, setUnread] = useState(0);
    const messagesEndRef = useRef(null);
    const inputRef = useRef(null);

    // 채팅 이력 로드
    var loadHistory = useCallback(function() {
        api.get('/chat/history').then(function(res) {
            if (res.success && res.data) {
                setMessages(res.data);
            }
        }).catch(function() {});
    }, []);

    useEffect(function() {
        if (currentUser) loadHistory();
    }, [currentUser, loadHistory]);

    // 채팅 열 때 스크롤
    useEffect(function() {
        if (isOpen && messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
        if (isOpen) {
            setUnread(0);
            if (inputRef.current) inputRef.current.focus();
        }
    }, [isOpen, messages.length]);

    // 메시지 전송
    var sendMessage = function() {
        var msg = input.trim();
        if (!msg || sending) return;

        setSending(true);
        setInput('');

        // 즉시 사용자 메시지 표시
        var userMsg = { role: 'user', content: msg, created_at: new Date().toISOString().slice(0, 19).replace('T', ' ') };
        setMessages(function(prev) { return prev.concat([userMsg]); });

        api.post('/chat/send', { message: msg }).then(function(res) {
            if (res.success) {
                var aiMsg = { role: 'assistant', content: res.response, created_at: new Date().toISOString().slice(0, 19).replace('T', ' ') };
                setMessages(function(prev) { return prev.concat([aiMsg]); });
                if (!isOpen) setUnread(function(n) { return n + 1; });
            } else {
                var errMsg = { role: 'assistant', content: res.detail || '오류가 발생했습니다.', created_at: new Date().toISOString().slice(0, 19).replace('T', ' ') };
                setMessages(function(prev) { return prev.concat([errMsg]); });
            }
            setSending(false);
        }).catch(function() {
            var errMsg = { role: 'assistant', content: '네트워크 오류가 발생했습니다.', created_at: new Date().toISOString().slice(0, 19).replace('T', ' ') };
            setMessages(function(prev) { return prev.concat([errMsg]); });
            setSending(false);
        });
    };

    var handleKeyDown = function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    // 태그 감지 표시
    var detectTags = function(text) {
        var tags = [];
        if (/#오류|#에러|#버그|#error|#bug/i.test(text)) tags.push({ label: '오류 신고', color: '#dc2626', bg: '#fee2e2' });
        if (/#요청|#기능요청|#추가요청|#request/i.test(text)) tags.push({ label: '기능 요청', color: '#2563eb', bg: '#dbeafe' });
        if (/#의견|#건의|#제안|#개선/i.test(text)) tags.push({ label: '의견', color: '#7c3aed', bg: '#ede9fe' });
        return tags;
    };

    // 마크다운 간이 렌더링 (볼드, 코드)
    var renderContent = function(text) {
        if (!text) return '';
        // **bold** → <strong>
        var html = text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/`(.*?)`/g, '<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px;font-size:12px">$1</code>')
            .replace(/\n/g, '<br/>');
        return { __html: html };
    };

    if (!currentUser) return null;

    return React.createElement('div', null,
        /* 플로팅 버튼 */
        React.createElement('button', {
            onClick: function() { setIsOpen(!isOpen); },
            style: {
                position: 'fixed', bottom: 24, right: 24, zIndex: 10000,
                width: 56, height: 56, borderRadius: '50%',
                background: 'linear-gradient(135deg, #7C3AED, #2563EB)',
                color: '#fff', border: 'none', cursor: 'pointer',
                boxShadow: '0 4px 20px rgba(124,58,237,0.4)',
                fontSize: 24, display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'transform 0.2s ease',
                transform: isOpen ? 'rotate(0deg) scale(0.9)' : 'rotate(0deg) scale(1)',
            },
            onMouseOver: function(e) { e.currentTarget.style.transform = 'scale(1.1)'; },
            onMouseOut: function(e) { e.currentTarget.style.transform = isOpen ? 'scale(0.9)' : 'scale(1)'; },
        },
            isOpen ? '✕' : '🤖',
            /* 읽지 않은 메시지 뱃지 */
            !isOpen && unread > 0 && React.createElement('span', {
                style: {
                    position: 'absolute', top: -4, right: -4,
                    width: 20, height: 20, borderRadius: '50%',
                    background: '#ef4444', color: '#fff', fontSize: 11, fontWeight: 700,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                }
            }, unread)
        ),

        /* 채팅 패널 */
        isOpen && React.createElement('div', {
            style: {
                position: 'fixed', bottom: 90, right: 24, zIndex: 10000,
                width: 380, height: 520, borderRadius: 16,
                background: '#fff', boxShadow: '0 8px 40px rgba(0,0,0,0.18)',
                display: 'flex', flexDirection: 'column', overflow: 'hidden',
                border: '1px solid #e2e8f0',
            }
        },
            /* 헤더 */
            React.createElement('div', {
                style: {
                    padding: '14px 18px', background: 'linear-gradient(135deg, #7C3AED, #2563EB)',
                    color: '#fff', display: 'flex', alignItems: 'center', gap: 10,
                }
            },
                React.createElement('span', { style: { fontSize: 20 } }, '🤖'),
                React.createElement('div', null,
                    React.createElement('div', { style: { fontSize: 14, fontWeight: 700 } }, 'AI 도우미'),
                    React.createElement('div', { style: { fontSize: 11, opacity: 0.8 } }, '로직 분석 프로그램 사용법 & 의견함')
                ),
                React.createElement('div', { style: { flex: 1 } }),
                React.createElement('button', {
                    onClick: function() { setIsOpen(false); },
                    style: { background: 'none', border: 'none', color: '#fff', fontSize: 18, cursor: 'pointer', opacity: 0.8 }
                }, '✕')
            ),

            /* 태그 안내 바 */
            React.createElement('div', {
                style: { padding: '8px 14px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0', fontSize: 11, color: '#64748b', display: 'flex', gap: 6, flexWrap: 'wrap' }
            },
                React.createElement('span', { style: { padding: '2px 6px', borderRadius: 8, background: '#fee2e2', color: '#dc2626', fontWeight: 600 } }, '#오류'),
                React.createElement('span', { style: { padding: '2px 6px', borderRadius: 8, background: '#dbeafe', color: '#2563eb', fontWeight: 600 } }, '#요청'),
                React.createElement('span', { style: { padding: '2px 6px', borderRadius: 8, background: '#ede9fe', color: '#7c3aed', fontWeight: 600 } }, '#의견'),
                React.createElement('span', null, '태그로 의견을 남길 수 있어요')
            ),

            /* 메시지 영역 */
            React.createElement('div', {
                style: { flex: 1, overflowY: 'auto', padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }
            },
                messages.length === 0 && React.createElement('div', {
                    style: { textAlign: 'center', padding: '40px 20px', color: '#94a3b8' }
                },
                    React.createElement('div', { style: { fontSize: 40, marginBottom: 12 } }, '🤖'),
                    React.createElement('div', { style: { fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#475569' } }, '안녕하세요! AI 도우미입니다'),
                    React.createElement('div', { style: { fontSize: 12, lineHeight: 1.6 } },
                        '로직 분석 프로그램 사용법이 궁금하신가요?',
                        React.createElement('br'),
                        '오류 신고나 기능 요청도 여기서 할 수 있어요!'
                    )
                ),

                messages.map(function(m, i) {
                    var isUser = m.role === 'user';
                    var tags = isUser ? detectTags(m.content) : [];
                    return React.createElement('div', {
                        key: i,
                        style: { display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start' }
                    },
                        React.createElement('div', {
                            style: {
                                maxWidth: '80%', padding: '10px 14px', borderRadius: 12,
                                background: isUser ? '#1B2A4A' : '#f1f5f9',
                                color: isUser ? '#fff' : '#1e293b',
                                fontSize: 13, lineHeight: 1.6,
                                borderBottomRightRadius: isUser ? 4 : 12,
                                borderBottomLeftRadius: isUser ? 12 : 4,
                            }
                        },
                            /* 태그 뱃지 */
                            tags.length > 0 && React.createElement('div', { style: { marginBottom: 6, display: 'flex', gap: 4 } },
                                tags.map(function(t, ti) {
                                    return React.createElement('span', {
                                        key: ti,
                                        style: { padding: '1px 6px', borderRadius: 6, fontSize: 10, fontWeight: 600, background: t.bg, color: t.color }
                                    }, t.label);
                                })
                            ),
                            /* 메시지 본문 */
                            React.createElement('div', { dangerouslySetInnerHTML: renderContent(m.content) }),
                            /* 시간 */
                            React.createElement('div', {
                                style: { fontSize: 10, marginTop: 4, opacity: 0.5, textAlign: isUser ? 'right' : 'left' }
                            }, (m.created_at || '').slice(11, 16))
                        )
                    );
                }),

                /* 전송 중 인디케이터 */
                sending && React.createElement('div', { style: { display: 'flex', justifyContent: 'flex-start' } },
                    React.createElement('div', {
                        style: { padding: '10px 14px', borderRadius: 12, background: '#f1f5f9', fontSize: 13, color: '#94a3b8', borderBottomLeftRadius: 4 }
                    }, '✨ AI가 답변을 작성 중입니다...')
                ),

                React.createElement('div', { ref: messagesEndRef })
            ),

            /* 입력 영역 */
            React.createElement('div', {
                style: { padding: '10px 14px', borderTop: '1px solid #e2e8f0', background: '#fff', display: 'flex', gap: 8, alignItems: 'flex-end' }
            },
                React.createElement('textarea', {
                    ref: inputRef,
                    value: input,
                    onChange: function(e) { setInput(e.target.value); },
                    onKeyDown: handleKeyDown,
                    placeholder: '질문이나 의견을 입력하세요...',
                    rows: 1,
                    style: {
                        flex: 1, padding: '8px 12px', borderRadius: 10,
                        border: '1px solid #e2e8f0', outline: 'none', resize: 'none',
                        fontSize: 13, lineHeight: 1.5, fontFamily: 'inherit',
                        maxHeight: 80, overflowY: 'auto',
                    }
                }),
                React.createElement('button', {
                    onClick: sendMessage,
                    disabled: sending || !input.trim(),
                    style: {
                        width: 36, height: 36, borderRadius: '50%',
                        background: sending || !input.trim() ? '#e2e8f0' : 'linear-gradient(135deg, #7C3AED, #2563EB)',
                        color: '#fff', border: 'none', cursor: sending || !input.trim() ? 'default' : 'pointer',
                        fontSize: 16, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0,
                    }
                }, '➤')
            )
        )
    );
};
