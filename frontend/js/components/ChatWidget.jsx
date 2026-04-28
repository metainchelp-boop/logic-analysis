/* ChatWidget — 플로팅 AI 채팅 + 의견함 위젯 v2.2 (이미지 첨부 지원) */

// 타임스탬프 헬퍼 (컴포넌트 외부 — 매 렌더링마다 재생성 방지)
var _chatNow = function() { return new Date().toISOString().slice(0, 19).replace('T', ' '); };

// 의견함 카테고리 옵션 (상수)
var _categoryOptions = [
    { value: 'error', label: '오류 신고', icon: '🚨', desc: '버그, 에러, 오작동', color: '#dc2626', bg: '#fee2e2' },
    { value: 'request', label: '기능 요청', icon: '💡', desc: '새 기능, 개선 요청', color: '#2563eb', bg: '#dbeafe' },
    { value: 'opinion', label: '의견/건의', icon: '💬', desc: '사용 후기, 제안', color: '#7c3aed', bg: '#ede9fe' },
];
var _fbTagMap = { error: '#오류', request: '#요청', opinion: '#의견' };

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
    const fileInputRef = useRef(null);

    // 이미지 첨부 상태
    const [imagePreview, setImagePreview] = useState(null);   // 미리보기 data URL
    const [imageB64, setImageB64] = useState(null);           // base64 데이터 (서버 전송용)
    const [imageType, setImageType] = useState(null);         // MIME 타입

    // 의견함 상태
    const [fbCategory, setFbCategory] = useState('');
    const [fbContent, setFbContent] = useState('');
    const [fbSending, setFbSending] = useState(false);
    const [fbSent, setFbSent] = useState(false);

    // 내 피드백 이력
    const [myFeedback, setMyFeedback] = useState([]);
    const [fbHistoryLoaded, setFbHistoryLoaded] = useState(false);

    // isOpen을 ref로도 추적 (useCallback 내부에서 최신값 참조)
    const isOpenRef = useRef(isOpen);
    useEffect(function() { isOpenRef.current = isOpen; }, [isOpen]);

    // 채팅 이력 로드
    var loadHistory = useCallback(function() {
        api.get('/chat/history').then(function(res) {
            if (res.success && res.data) {
                setMessages(res.data);
            }
        }).catch(function() {});
    }, []);

    // 내 피드백 이력 로드
    var loadMyFeedback = useCallback(function() {
        api.get('/chat/my-feedback').then(function(res) {
            if (res.success && res.data) {
                setMyFeedback(res.data);
                setFbHistoryLoaded(true);
            }
        }).catch(function() {});
    }, []);

    useEffect(function() {
        if (currentUser) loadHistory();
    }, [currentUser, loadHistory]);

    // 의견함 탭 열 때 피드백 이력 로드
    useEffect(function() {
        if (isOpen && activeTab === 'feedback' && currentUser) loadMyFeedback();
    }, [isOpen, activeTab, currentUser, loadMyFeedback]);

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

    // 이미지 파일 선택 핸들러
    var handleImageSelect = useCallback(function(e) {
        var file = e.target.files && e.target.files[0];
        if (!file) return;

        // 타입 검증
        var allowed = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
        if (allowed.indexOf(file.type) < 0) {
            toast.error('PNG, JPG, GIF, WebP 이미지만 첨부 가능합니다.');
            e.target.value = '';
            return;
        }
        // 크기 검증 (5MB)
        if (file.size > 5 * 1024 * 1024) {
            toast.error('이미지 크기는 5MB 이하만 가능합니다.');
            e.target.value = '';
            return;
        }

        var reader = new FileReader();
        reader.onload = function(ev) {
            setImagePreview(ev.target.result);
            // data:image/png;base64,xxxxx → base64 부분만 추출
            var b64 = ev.target.result.split(',')[1];
            setImageB64(b64);
            setImageType(file.type);
        };
        reader.readAsDataURL(file);
        e.target.value = ''; // 같은 파일 재선택 허용
    }, []);

    var clearImage = useCallback(function() {
        setImagePreview(null);
        setImageB64(null);
        setImageType(null);
    }, []);

    // 메시지 전송 (useCallback으로 안정적 참조)
    var sendMessage = useCallback(function() {
        var msg = input.trim();
        if ((!msg && !imageB64) || sending) return;

        setSending(true);
        setInput('');

        var userMsg = { role: 'user', content: msg || '(이미지)', created_at: _chatNow(), image_url: imagePreview };
        setMessages(function(prev) { return prev.concat([userMsg]); });

        var payload = { message: msg || '이 이미지를 분석해주세요.' };
        if (imageB64) {
            payload.image = imageB64;
            payload.image_type = imageType;
        }
        clearImage();

        api.post('/chat/send', payload).then(function(res) {
            var aiMsg = {
                role: 'assistant',
                content: res.success ? res.response : (res.detail || '오류가 발생했습니다.'),
                created_at: _chatNow()
            };
            setMessages(function(prev) { return prev.concat([aiMsg]); });
            if (!isOpenRef.current) setUnread(function(n) { return n + 1; });
            setSending(false);
        }).catch(function() {
            setMessages(function(prev) { return prev.concat([{ role: 'assistant', content: '네트워크 오류가 발생했습니다.', created_at: _chatNow() }]); });
            setSending(false);
        });
    }, [input, sending, imageB64, imageType, imagePreview, clearImage]);

    var handleKeyDown = useCallback(function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }, [sendMessage]);

    // 의견함 전송
    var sendFeedback = useCallback(function() {
        if (!fbCategory || !fbContent.trim() || fbSending) return;
        setFbSending(true);

        var msgWithTag = (_fbTagMap[fbCategory] || '') + ' ' + fbContent.trim();

        api.post('/chat/send', { message: msgWithTag }).then(function(res) {
            setFbSending(false);
            setFbSent(true);
            setFbContent('');
            setFbCategory('');
            loadMyFeedback(); // 이력 새로고침
            setTimeout(function() { setFbSent(false); }, 3000);
        }).catch(function() {
            setFbSending(false);
            toast.error('전송에 실패했습니다.');
        });
    }, [fbCategory, fbContent, fbSending]);

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

    var categoryOptions = _categoryOptions;

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
                                /* 이미지 표시 */
                                m.image_url && React.createElement('img', {
                                    src: m.image_url,
                                    alt: '첨부 이미지',
                                    style: {
                                        maxWidth: '100%', maxHeight: 200, borderRadius: 8,
                                        marginBottom: m.content && m.content !== '(이미지)' ? 8 : 0,
                                        cursor: 'pointer', display: 'block',
                                    },
                                    onClick: function() { window.open(m.image_url, '_blank'); }
                                }),
                                /* 텍스트 (이미지만 보낸 경우 '(이미지)' 표시 제외) */
                                (m.content && m.content !== '(이미지)') && React.createElement('div', { dangerouslySetInnerHTML: renderContent(m.content) }),
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

                /* 이미지 미리보기 */
                imagePreview && React.createElement('div', {
                    style: {
                        padding: '8px 14px', borderTop: '1px solid #e2e8f0', background: '#f8fafc',
                        display: 'flex', alignItems: 'center', gap: 8,
                    }
                },
                    React.createElement('img', {
                        src: imagePreview,
                        alt: '미리보기',
                        style: { width: 48, height: 48, objectFit: 'cover', borderRadius: 8, border: '1px solid #e2e8f0' }
                    }),
                    React.createElement('span', { style: { fontSize: 12, color: '#64748b', flex: 1 } }, '이미지 첨부됨'),
                    React.createElement('button', {
                        onClick: clearImage,
                        style: {
                            background: '#fee2e2', color: '#dc2626', border: 'none', borderRadius: 6,
                            padding: '4px 8px', fontSize: 11, cursor: 'pointer', fontWeight: 600,
                        }
                    }, '삭제')
                ),

                /* 입력 영역 */
                React.createElement('div', {
                    style: { padding: '10px 14px', borderTop: imagePreview ? 'none' : '1px solid #e2e8f0', background: '#fff', display: 'flex', gap: 8, alignItems: 'flex-end' }
                },
                    /* 숨겨진 파일 입력 */
                    React.createElement('input', {
                        ref: fileInputRef,
                        type: 'file',
                        accept: 'image/png,image/jpeg,image/gif,image/webp',
                        style: { display: 'none' },
                        onChange: handleImageSelect,
                    }),
                    /* 이미지 첨부 버튼 */
                    React.createElement('button', {
                        onClick: function() { if (fileInputRef.current) fileInputRef.current.click(); },
                        disabled: sending,
                        title: '이미지 첨부 (5MB 이하)',
                        style: {
                            width: 36, height: 36, borderRadius: '50%',
                            background: imagePreview ? '#dbeafe' : '#f1f5f9',
                            color: imagePreview ? '#2563eb' : '#64748b',
                            border: 'none', cursor: sending ? 'default' : 'pointer',
                            fontSize: 18, display: 'flex', alignItems: 'center', justifyContent: 'center',
                            flexShrink: 0, transition: 'all 0.15s ease',
                        }
                    }, '📷'),
                    React.createElement('textarea', {
                        ref: inputRef,
                        value: input,
                        onChange: function(e) { setInput(e.target.value); },
                        onKeyDown: handleKeyDown,
                        placeholder: imagePreview ? '이미지에 대해 질문하세요...' : '질문을 입력하세요...',
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
                        disabled: sending || (!input.trim() && !imageB64),
                        style: {
                            width: 36, height: 36, borderRadius: '50%',
                            background: sending || (!input.trim() && !imageB64) ? '#e2e8f0' : '#1B2A4A',
                            color: '#fff', border: 'none', cursor: sending || (!input.trim() && !imageB64) ? 'default' : 'pointer',
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
                    ),

                    /* ===== 내 의견 이력 ===== */
                    React.createElement('div', {
                        style: { marginTop: 8, borderTop: '1px solid #e2e8f0', paddingTop: 16 }
                    },
                        React.createElement('div', {
                            style: { fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }
                        }, '📋 내 의견 이력'),

                        myFeedback.length === 0 && fbHistoryLoaded && React.createElement('div', {
                            style: { fontSize: 12, color: '#94a3b8', textAlign: 'center', padding: '12px 0' }
                        }, '아직 등록한 의견이 없습니다.'),

                        myFeedback.map(function(fb) {
                            var _catInfo = { error: { icon: '🚨', label: '오류', color: '#dc2626', bg: '#fee2e2' }, request: { icon: '💡', label: '요청', color: '#2563eb', bg: '#dbeafe' }, opinion: { icon: '💬', label: '의견', color: '#7c3aed', bg: '#ede9fe' } };
                            var catInfo = _catInfo[fb.category] || _catInfo.opinion;
                            var _statusMap = { pending: { label: '접수됨', color: '#f59e0b', bg: '#fffbeb' }, in_progress: { label: '처리중', color: '#3b82f6', bg: '#dbeafe' }, resolved: { label: '완료', color: '#10b981', bg: '#dcfce7' } };
                            var statusInfo = _statusMap[fb.status] || _statusMap.pending;

                            return React.createElement('div', {
                                key: fb.id,
                                style: {
                                    padding: '10px 12px', borderRadius: 10,
                                    background: '#f8fafc', border: '1px solid #e2e8f0',
                                    marginBottom: 8, fontSize: 12,
                                }
                            },
                                /* 헤더: 카테고리 + 상태 + 날짜 */
                                React.createElement('div', {
                                    style: { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }
                                },
                                    React.createElement('span', {
                                        style: { padding: '2px 6px', borderRadius: 4, fontSize: 10, fontWeight: 600, color: catInfo.color, background: catInfo.bg }
                                    }, catInfo.icon + ' ' + catInfo.label),
                                    React.createElement('span', {
                                        style: { padding: '2px 6px', borderRadius: 4, fontSize: 10, fontWeight: 600, color: statusInfo.color, background: statusInfo.bg }
                                    }, statusInfo.label),
                                    React.createElement('span', { style: { flex: 1 } }),
                                    React.createElement('span', { style: { fontSize: 10, color: '#94a3b8' } }, (fb.created_at || '').slice(0, 16))
                                ),
                                /* 내용 (태그 제거) */
                                React.createElement('div', {
                                    style: { color: '#334155', lineHeight: 1.5, wordBreak: 'break-word' }
                                }, (fb.content || '').replace(/^#\S+\s*/, '')),
                                /* 관리자 답변 */
                                fb.admin_reply && React.createElement('div', {
                                    style: {
                                        marginTop: 8, padding: '8px 10px', borderRadius: 8,
                                        background: '#eff6ff', border: '1px solid #bfdbfe',
                                        fontSize: 11, color: '#1e40af', lineHeight: 1.5,
                                    }
                                },
                                    React.createElement('div', { style: { fontWeight: 600, marginBottom: 2, fontSize: 10 } }, '💼 관리자 답변'),
                                    fb.admin_reply
                                ),
                                /* 완료 시간 */
                                fb.resolved_at && React.createElement('div', {
                                    style: { marginTop: 4, fontSize: 10, color: '#10b981' }
                                }, '✅ 처리 완료: ' + fb.resolved_at.slice(0, 16))
                            );
                        })
                    )
                )
            )
        )
    );
};
