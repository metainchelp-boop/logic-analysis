/* ChatWidget — 플로팅 AI 채팅 + 의견함 위젯 v2.0 */
window.ChatWidget = function ChatWidget({ currentUser }) {
    const { useState, useEffect, useRef, useCallback } = React;

    const [isOpen, setIsOpen] = useState(false);
    const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'feedback'
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const [unread, setUnread] = useState(0);
    const messagesEndRef = useRef(null);
    const inputRef = useRef(null);

    // 의견함 상태
    const [fbCategory, setFbCategory] = useState('');
    const [fbContent, setFbContent] = useState('');
    const [fbSending, setFbSending] = useState(false);
    const [fbSent, setFbSent] = useState(false);

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
        if (isOpen && activeTab === 'chat' && messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
        if (isOpen && activeTab === 'chat') {
            setUnread(0);
            if (inputRef.current) inputRef.current.focus();
        }
    }, [isOpen, messages.length, activeTab]);

    // 메시지 전송
    var sendMessage = function() {
        var msg = input.trim();
        if (!msg || sending) return;

        setSending(true);
        setInput('');

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

    // 의견함 전송
    var sendFeedback = function() {
        if (!fbCategory || !fbContent.trim() || fbSending) return;
        setFbSending(true);

        // 카테고리 태그를 자동으로 붙여서 기존 백엔드 로직 활용
        var tagMap = { error: '#오류', request: '#요청', opinion: '#의견' };
        var msgWithTag = (tagMap[fbCategory] || '') + ' ' + fbContent.trim();

        api.post('/chat/send', { message: msgWithTag }).then(function(res) {
            setFbSending(false);
            setFbSent(true);
            setFbContent('');
            setFbCategory('');
            setTimeout(function() { setFbSent(false); }, 3000);
        }).catch(function() {
            setFbSending(false);
            toast.error('전송에 실패했습니다.');
        });
    };

    // 마크다운 간이 렌더링
    var renderContent = function(text) {
        if (!text) return '';
        var html = text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/`(.*?)`/g, '<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px;font-size:12px">$1</code>')
            .replace(/\n/g, '<br/>');
        return { __html: html };
    };

    if (!currentUser) return null;

    var categoryOptions = [
        { value: 'error', label: '오류 신고', icon: '🚨', desc: '버그, 에러, 오작동', color: '#dc2626', bg: '#fee2e2' },
        { value: 'request', label: '기능 요청', icon: '💡', desc: '새 기능, 개선 요청', color: '#2563eb', bg: '#dbeafe' },
        { value: 'opinion', label: '의견/건의', icon: '💬', desc: '사용 후기, 제안', color: '#7c3aed', bg: '#ede9fe' },
    ];

    return React.createElement('div', null,
        /* 플로팅 버튼 — 회사 로고 */
        React.createElement('button', {
            onClick: function() { setIsOpen(!isOpen); },
            style: {
                position: 'fixed', bottom: 24, right: 24, zIndex: 10000,
                width: 56, height: 56, borderRadius: '50%',
                background: isOpen ? '#64748b' : '#1B2A4A',
                color: '#fff', border: 'none', cursor: 'pointer',
                boxShadow: '0 4px 20px rgba(27,42,74,0.4)',
                fontSize: 24, display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.2s ease',
                transform: isOpen ? 'scale(0.9)' : 'scale(1)',
                overflow: 'hidden', padding: 0,
            },
            onMouseOver: function(e) { e.currentTarget.style.transform = 'scale(1.1)'; },
            onMouseOut: function(e) { e.currentTarget.style.transform = isOpen ? 'scale(0.9)' : 'scale(1)'; },
        },
            isOpen
                ? '✕'
                : React.createElement('img', {
                    src: 'img/logo_light.png',
                    alt: 'METAINC',
                    style: { width: 32, height: 32, objectFit: 'contain' }
                }),
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

        /* 메인 패널 */
        isOpen && React.createElement('div', {
            style: {
                position: 'fixed', bottom: 90, right: 24, zIndex: 10000,
                width: 380, height: 540, borderRadius: 16,
                background: '#fff', boxShadow: '0 8px 40px rgba(0,0,0,0.18)',
                display: 'flex', flexDirection: 'column', overflow: 'hidden',
                border: '1px solid #e2e8f0',
            }
        },
            /* 헤더 */
            React.createElement('div', {
                style: {
                    padding: '12px 18px', background: '#1B2A4A',
                    color: '#fff', display: 'flex', alignItems: 'center', gap: 10,
                }
            },
                React.createElement('img', {
                    src: 'img/logo_light.png',
                    alt: 'METAINC',
                    style: { width: 28, height: 28, objectFit: 'contain' }
                }),
                React.createElement('div', null,
                    React.createElement('div', { style: { fontSize: 13, fontWeight: 700 } }, 'METAINC 로직 분석 AI'),
                    React.createElement('div', { style: { fontSize: 10, opacity: 0.7 } }, '질문 & 의견함')
                ),
                React.createElement('div', { style: { flex: 1 } }),
                React.createElement('button', {
                    onClick: function() { setIsOpen(false); },
                    style: { background: 'none', border: 'none', color: '#fff', fontSize: 18, cursor: 'pointer', opacity: 0.8 }
                }, '✕')
            ),

            /* 탭 바 */
            React.createElement('div', {
                style: { display: 'flex', borderBottom: '1px solid #e2e8f0', background: '#f8fafc' }
            },
                React.createElement('button', {
                    onClick: function() { setActiveTab('chat'); },
                    style: {
                        flex: 1, padding: '10px 0', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                        background: 'none', border: 'none',
                        color: activeTab === 'chat' ? '#1B2A4A' : '#94a3b8',
                        borderBottom: activeTab === 'chat' ? '2px solid #1B2A4A' : '2px solid transparent',
                    }
                }, '💬 AI 채팅'),
                React.createElement('button', {
                    onClick: function() { setActiveTab('feedback'); },
                    style: {
                        flex: 1, padding: '10px 0', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                        background: 'none', border: 'none',
                        color: activeTab === 'feedback' ? '#1B2A4A' : '#94a3b8',
                        borderBottom: activeTab === 'feedback' ? '2px solid #1B2A4A' : '2px solid transparent',
                    }
                }, '📝 의견함')
            ),

            /* ===== AI 채팅 탭 ===== */
            activeTab === 'chat' && React.createElement(React.Fragment, null,
                /* 메시지 영역 */
                React.createElement('div', {
                    style: { flex: 1, overflowY: 'auto', padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }
                },
                    messages.length === 0 && React.createElement('div', {
                        style: { textAlign: 'center', padding: '40px 20px', color: '#94a3b8' }
                    },
                        React.createElement('img', {
                            src: 'img/logo_dark.png',
                            alt: 'METAINC',
                            style: { width: 48, height: 48, objectFit: 'contain', marginBottom: 12, opacity: 0.6 }
                        }),
                        React.createElement('div', { style: { fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#475569' } }, 'METAINC 로직 분석 AI'),
                        React.createElement('div', { style: { fontSize: 12, lineHeight: 1.6 } },
                            '로직 분석 프로그램 사용법이 궁금하신가요?',
                            React.createElement('br'),
                            '무엇이든 질문해 주세요!'
                        )
                    ),

                    messages.map(function(m, i) {
                        var isUser = m.role === 'user';
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
                                React.createElement('div', { dangerouslySetInnerHTML: renderContent(m.content) }),
                                React.createElement('div', {
                                    style: { fontSize: 10, marginTop: 4, opacity: 0.5, textAlign: isUser ? 'right' : 'left' }
                                }, (m.created_at || '').slice(11, 16))
                            )
                        );
                    }),

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
                        placeholder: '질문을 입력하세요...',
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
                            background: sending || !input.trim() ? '#e2e8f0' : '#1B2A4A',
                            color: '#fff', border: 'none', cursor: sending || !input.trim() ? 'default' : 'pointer',
                            fontSize: 16, display: 'flex', alignItems: 'center', justifyContent: 'center',
                            flexShrink: 0,
                        }
                    }, '➤')
                )
            ),

            /* ===== 의견함 탭 ===== */
            activeTab === 'feedback' && React.createElement('div', {
                style: { flex: 1, overflowY: 'auto', padding: 18, display: 'flex', flexDirection: 'column', gap: 16 }
            },
                /* 완료 메시지 */
                fbSent && React.createElement('div', {
                    style: { padding: '16px 20px', background: '#dcfce7', borderRadius: 12, textAlign: 'center' }
                },
                    React.createElement('div', { style: { fontSize: 28, marginBottom: 8 } }, '✅'),
                    React.createElement('div', { style: { fontSize: 14, fontWeight: 600, color: '#166534' } }, '의견이 접수되었습니다!'),
                    React.createElement('div', { style: { fontSize: 12, color: '#166534', marginTop: 4 } }, '소중한 의견 감사합니다.')
                ),

                /* 안내 */
                !fbSent && React.createElement(React.Fragment, null,
                    React.createElement('div', { style: { fontSize: 13, color: '#475569', lineHeight: 1.6 } },
                        '로직 분석 프로그램에 대한 의견을 남겨주세요.',
                        React.createElement('br'),
                        '오류, 기능 요청, 개선 사항 등 무엇이든 환영합니다!'
                    ),

                    /* 카테고리 선택 */
                    React.createElement('div', null,
                        React.createElement('div', { style: { fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 8 } }, '카테고리 선택'),
                        React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
                            categoryOptions.map(function(cat) {
                                var isSelected = fbCategory === cat.value;
                                return React.createElement('button', {
                                    key: cat.value,
                                    onClick: function() { setFbCategory(cat.value); },
                                    style: {
                                        display: 'flex', alignItems: 'center', gap: 10,
                                        padding: '10px 14px', borderRadius: 10, cursor: 'pointer',
                                        background: isSelected ? cat.bg : '#f8fafc',
                                        border: isSelected ? '2px solid ' + cat.color : '1px solid #e2e8f0',
                                        textAlign: 'left', transition: 'all 0.15s ease',
                                    }
                                },
                                    React.createElement('span', { style: { fontSize: 20 } }, cat.icon),
                                    React.createElement('div', null,
                                        React.createElement('div', { style: { fontSize: 13, fontWeight: 600, color: isSelected ? cat.color : '#334155' } }, cat.label),
                                        React.createElement('div', { style: { fontSize: 11, color: '#94a3b8' } }, cat.desc)
                                    )
                                );
                            })
                        )
                    ),

                    /* 내용 입력 */
                    fbCategory && React.createElement('div', null,
                        React.createElement('div', { style: { fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 8 } }, '내용'),
                        React.createElement('textarea', {
                            value: fbContent,
                            onChange: function(e) { setFbContent(e.target.value); },
                            placeholder: fbCategory === 'error' ? '어떤 오류가 발생했나요? 상황을 자세히 적어주세요...'
                                : fbCategory === 'request' ? '어떤 기능이 있으면 좋겠나요?...'
                                : '의견이나 건의 사항을 자유롭게 적어주세요...',
                            rows: 4,
                            style: {
                                width: '100%', padding: '10px 14px', borderRadius: 10,
                                border: '1px solid #e2e8f0', outline: 'none', resize: 'vertical',
                                fontSize: 13, lineHeight: 1.5, fontFamily: 'inherit',
                                boxSizing: 'border-box',
                            }
                        }),
                        React.createElement('button', {
                            onClick: sendFeedback,
                            disabled: fbSending || !fbContent.trim(),
                            style: {
                                marginTop: 10, width: '100%', padding: '10px 0', borderRadius: 10,
                                background: fbSending || !fbContent.trim() ? '#e2e8f0' : '#1B2A4A',
                                color: fbSending || !fbContent.trim() ? '#94a3b8' : '#fff',
                                border: 'none', fontSize: 13, fontWeight: 600, cursor: fbSending || !fbContent.trim() ? 'default' : 'pointer',
                            }
                        }, fbSending ? '전송 중...' : '의견 보내기')
                    )
                )
            )
        )
    );
};
