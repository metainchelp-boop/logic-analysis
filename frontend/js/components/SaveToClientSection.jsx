/* SaveToClientSection — 분석 결과를 업체로 저장하는 섹션 */
window.SaveToClientSection = function SaveToClientSection({
    keyword, productUrl, analysisData, volumeData, relatedData, shopProducts, advertiserReport, detailHtml, htmlDetailResult,
    competitorContext, onCompetitorSaved, allowCompetitorOnly
}) {
    var _React = React;
    var useState = _React.useState;
    var useEffect = _React.useEffect;
    var useCallback = _React.useCallback;

    var _s = useState(false); var showModal = _s[0]; var setShowModal = _s[1];
    var _s2 = useState([]); var existingClients = _s2[0]; var setExistingClients = _s2[1];
    var _s3 = useState('new'); var saveMode = _s3[0]; var setSaveMode = _s3[1];
    var _s4 = useState(''); var clientName = _s4[0]; var setClientName = _s4[1];
    var _s5 = useState(null); var selectedClientId = _s5[0]; var setSelectedClientId = _s5[1];
    var _s6 = useState(false); var saving = _s6[0]; var setSaving = _s6[1];
    var _s7 = useState(''); var message = _s7[0]; var setMessage = _s7[1];
    var _s8 = useState(false); var success = _s8[0]; var setSuccess = _s8[1];
    var _s9 = useState(''); var clientSearch = _s9[0]; var setClientSearch = _s9[1];  // 기존 업체 검색어
    /* 경쟁사 저장(영업사원/확장 흐름) — 연결할 광고주 드롭다운 선택 */
    var _sa = useState(null); var compAdvId = _sa[0]; var setCompAdvId = _sa[1];

    /* 영업사원(viewer)은 경쟁사 저장만 가능 → 모달 열리면 경쟁사 모드로 고정 */
    var _forceComp = !!allowCompetitorOnly;

    /* 기존 업체(광고주) 목록 로드 — 기존 업체 추가/경쟁사 연결 드롭다운 공용 */
    var loadClients = useCallback(function() {
        api.get('/cd/registered-clients').then(function(res) {
            if (res.success) setExistingClients(res.data || []);
        }).catch(function() {});
    }, []);

    useEffect(function() {
        if (showModal) {
            loadClients();
            if (_forceComp) setSaveMode('competitor');
        }
    }, [showModal, loadClients, _forceComp]);

    if (!keyword || !analysisData) return null;

    /* DOM 캡처 — 공용 빌더(ReportCapture) 사용 (v6.7 통일)
     * 수동 내보내기·자동저장과 동일한 제거 규칙·인디고 표지·PC 축소판 viewport 적용.
     * 구버전(자체 클론 로직)은 보라 표지·no-export 미제거로 전달본 불일치가 있었음. */
    var captureReportHtml = function() {
        try {
            if (!window.ReportCapture) return '';
            return window.ReportCapture.buildHtml({ title: keyword + ' 키워드 분석 보고서' });
        } catch(e) {
            console.error('DOM capture failed:', e);
            return '';
        }
    };

    var handleSave = function() {
        setSaving(true);
        setMessage('');

        /* DOM 캡처로 HTML 보고서 생성 */
        var reportHtml = captureReportHtml();

        var payload = {
            keyword: keyword,
            product_url: productUrl || '',
            analysis_data: (htmlDetailResult ? Object.assign({}, analysisData, { htmlDetail: trimHtmlDetail(htmlDetailResult) }) : analysisData),
            volume_data: volumeData || {},
            related_data: relatedData || {},
            shop_products: (shopProducts || []).slice(0, 20),
            advertiser_data: advertiserReport || {},
            report_html: reportHtml,
            detail_html: detailHtml || '',
        };

        // 경쟁사 저장 대상 광고주: 업체관리 진입(competitorContext) 우선, 아니면 경쟁사 탭 드롭다운 선택
        var compOf = (competitorContext && competitorContext.competitor_of)
            || ((saveMode === 'competitor' || _forceComp) ? compAdvId : null);
        var isCompMode = !!compOf;
        if (saveMode === 'new' || isCompMode) {
            if (!clientName.trim()) {
                setMessage(isCompMode ? '경쟁사명을 입력해주세요.' : '업체명을 입력해주세요.');
                setSaving(false);
                return;
            }
            if (isCompMode && !compOf) {
                setMessage('연결할 광고주를 선택해주세요.');
                setSaving(false);
                return;
            }
            payload.name = clientName.trim();
            // 경쟁사 저장: 광고주에 연결된 경쟁사로 (광고주 리스트/자동추적엔 안 섞임)
            if (isCompMode) {
                payload.role = 'competitor';
                payload.competitor_of = compOf;
            }
            api.post('/cd/quick-register', payload).then(function(res) {
                if (res.success) {
                    setSuccess(true);
                    setMessage(res.message);
                    if (isCompMode && onCompetitorSaved) { try { onCompetitorSaved(); } catch(e) {} }
                } else {
                    var errMsg = typeof res.detail === 'string' ? res.detail : '저장에 실패했습니다.';
                    setMessage(errMsg);
                }
                setSaving(false);
            }).catch(function(e) {
                setMessage('서버 오류가 발생했습니다.');
                setSaving(false);
            });
        } else {
            if (!selectedClientId) {
                setMessage('업체를 선택해주세요.');
                setSaving(false);
                return;
            }
            payload.client_id = selectedClientId;
            api.post('/cd/analyze', payload).then(function(res) {
                if (res.success) {
                    setSuccess(true);
                    setMessage(res.message);
                } else {
                    var errMsg = typeof res.detail === 'string' ? res.detail : '저장에 실패했습니다.';
                    setMessage(errMsg);
                }
                setSaving(false);
            }).catch(function(e) {
                setMessage('서버 오류가 발생했습니다.');
                setSaving(false);
            });
        }
    };

    var closeModal = function() {
        setShowModal(false);
        setMessage('');
        setSuccess(false);
        setClientName('');
        setSelectedClientId(null);
        setSaveMode('new');
    };

    return React.createElement('div', { id: 'sec-save-client', className: 'section', style: { paddingBottom: 20 } },
        React.createElement('div', { className: 'container' },
            React.createElement('div', {
                className: 'card',
                style: {
                    padding: '24px 28px',
                    background: 'linear-gradient(135deg, #6C5CE7 0%, #a29bfe 100%)',
                    color: '#fff',
                    textAlign: 'center',
                    borderRadius: 14,
                }
            },
                React.createElement('div', { style: { fontSize: 18, fontWeight: 700, marginBottom: 8 } },
                    _forceComp
                        ? '"' + keyword + '" 분석 결과를 경쟁사로 저장하시겠습니까?'
                        : '"' + keyword + '" 분석 결과를 업체에 저장하시겠습니까?'
                ),
                React.createElement('div', { style: { fontSize: 13, opacity: 0.85, marginBottom: 16 } },
                    _forceComp
                        ? '광고주를 선택해 그 광고주의 경쟁사로 저장합니다. (영업사원 등록분은 30일 후 자동 삭제)'
                        : '업체로 저장하면 업체관리 탭에서 일자별 분석 데이터가 누적됩니다.'
                ),
                React.createElement('button', {
                    onClick: function() { setShowModal(true); },
                    style: {
                        background: '#fff', color: '#6C5CE7', border: 'none',
                        padding: '12px 32px', borderRadius: 10, fontSize: 15, fontWeight: 700,
                        cursor: 'pointer', boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
                    }
                }, _forceComp ? '⚔️ 경쟁사로 저장' : '업체 등록 / 저장')
            )
        ),

        /* 모달 */
        showModal && React.createElement('div', {
            style: {
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                background: 'rgba(0,0,0,0.5)', zIndex: 9999,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
            },
            onClick: function(e) { if (e.target === e.currentTarget) closeModal(); }
        },
            React.createElement('div', {
                className: 'responsive-modal',
                style: {
                    background: '#fff', borderRadius: 16, padding: 28, width: 420,
                    maxWidth: '92vw', boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
                }
            },
                /* 헤더 */
                React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 } },
                    React.createElement('div', { style: { fontSize: 18, fontWeight: 700, color: '#1e293b' } }, '업체 등록 / 분석 저장'),
                    React.createElement('button', {
                        onClick: closeModal,
                        style: { background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#94a3b8' }
                    }, '\u2715')
                ),

                /* 분석 키워드 표시 */
                React.createElement('div', {
                    style: { background: '#f8fafc', borderRadius: 10, padding: '12px 16px', marginBottom: 16, fontSize: 13, color: '#475569' }
                },
                    React.createElement('span', { style: { fontWeight: 600 } }, '키워드: '),
                    keyword,
                    productUrl && React.createElement('span', null, ' | URL: ' + (productUrl.length > 40 ? productUrl.slice(0, 40) + '...' : productUrl))
                ),

                /* 성공 메시지 */
                success ? React.createElement('div', null,
                    React.createElement('div', {
                        style: { background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10,
                            padding: '20px', textAlign: 'center', marginBottom: 16 }
                    },
                        React.createElement('div', { style: { fontSize: 32, marginBottom: 8 } }, '\u2705'),
                        React.createElement('div', { style: { fontSize: 15, fontWeight: 600, color: '#16a34a' } }, message)
                    ),
                    React.createElement('button', {
                        onClick: closeModal,
                        style: {
                            width: '100%', padding: '12px', borderRadius: 10, border: 'none',
                            background: '#6C5CE7', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer'
                        }
                    }, '확인')
                )

                /* 입력 폼 */
                : React.createElement('div', null,
                    /* 탭: 새 업체 / 기존 업체 / 경쟁사 (viewer는 경쟁사만) */
                    React.createElement('div', { style: { display: 'flex', gap: 8, marginBottom: 16 } },
                        !_forceComp && React.createElement('button', {
                            onClick: function() { setSaveMode('new'); },
                            style: {
                                flex: 1, padding: '10px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                background: saveMode === 'new' ? '#6C5CE7' : '#f1f5f9',
                                color: saveMode === 'new' ? '#fff' : '#64748b',
                                border: saveMode === 'new' ? '1px solid #6C5CE7' : '1px solid #e2e8f0',
                            }
                        }, '새 업체 등록'),
                        !_forceComp && React.createElement('button', {
                            onClick: function() { setSaveMode('existing'); },
                            style: {
                                flex: 1, padding: '10px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                background: saveMode === 'existing' ? '#6C5CE7' : '#f1f5f9',
                                color: saveMode === 'existing' ? '#fff' : '#64748b',
                                border: saveMode === 'existing' ? '1px solid #6C5CE7' : '1px solid #e2e8f0',
                            }
                        }, '기존 업체에 추가 (' + existingClients.length + ')'),
                        React.createElement('button', {
                            onClick: function() { setSaveMode('competitor'); },
                            style: {
                                flex: 1, padding: '10px', borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: 'pointer',
                                background: saveMode === 'competitor' ? '#c2410c' : '#fff7ed',
                                color: saveMode === 'competitor' ? '#fff' : '#c2410c',
                                border: '1px solid ' + (saveMode === 'competitor' ? '#c2410c' : '#fed7aa'),
                            }
                        }, '⚔️ 경쟁사로 저장')
                    ),

                    /* 경쟁사 저장: 연결할 광고주 선택 + 경쟁사명 */
                    saveMode === 'competitor' && React.createElement('div', { style: { marginBottom: 16 } },
                        React.createElement('label', { style: { fontSize: 13, color: '#475569', fontWeight: 600, display: 'block', marginBottom: 6 } }, '연결할 광고주'),
                        React.createElement('select', {
                            className: 'form-input', value: compAdvId || '',
                            onChange: function(e) { setCompAdvId(e.target.value ? Number(e.target.value) : null); },
                            style: { width: '100%', marginBottom: 12 }
                        },
                            [React.createElement('option', { key: '_', value: '' }, '— 광고주 선택 —')].concat(
                                existingClients.map(function(c) { return React.createElement('option', { key: c.id, value: c.id }, c.name); })
                            )
                        ),
                        React.createElement('label', { style: { fontSize: 13, color: '#475569', fontWeight: 600, display: 'block', marginBottom: 6 } }, '경쟁사명'),
                        React.createElement('input', {
                            className: 'form-input', value: clientName,
                            onChange: function(e) { setClientName(e.target.value); },
                            placeholder: '경쟁사명을 입력하세요',
                            style: { width: '100%', marginBottom: 8 }, autoFocus: true
                        }),
                        _forceComp && React.createElement('div', { style: { fontSize: 11.5, color: '#c2410c', background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: 8, padding: '8px 12px' } },
                            '⏳ 영업사원이 등록한 경쟁사는 30일 후 자동 삭제됩니다. (관리팀에 정식 등록이 필요하면 담당자에게 요청)')
                    ),

                    /* 새 업체 입력 */
                    saveMode === 'new' && React.createElement('div', null,
                        React.createElement('label', { style: { fontSize: 13, color: '#475569', fontWeight: 600, display: 'block', marginBottom: 6 } }, '업체명'),
                        React.createElement('input', {
                            className: 'form-input',
                            value: clientName,
                            onChange: function(e) { setClientName(e.target.value); },
                            placeholder: '업체명을 입력하세요',
                            style: { width: '100%', marginBottom: 4 },
                            autoFocus: true,
                        }),
                        React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginBottom: 16 } },
                            '같은 이름의 업체가 있으면 해당 업체에 분석이 추가됩니다.'
                        )
                    ),

                    /* 기존 업체 선택 */
                    saveMode === 'existing' && React.createElement('div', { style: { marginBottom: 16 } },
                        existingClients.length === 0
                            ? React.createElement('div', { style: { textAlign: 'center', padding: 20, color: '#94a3b8', fontSize: 13 } },
                                '등록된 업체가 없습니다. 새 업체를 등록해주세요.')
                            : (function() {
                                var q = clientSearch.trim().toLowerCase();
                                var filtered = q
                                    ? existingClients.filter(function(c) {
                                        return ((c.name || '').toLowerCase().indexOf(q) !== -1)
                                            || ((c.main_keywords || '').toLowerCase().indexOf(q) !== -1);
                                    })
                                    : existingClients;
                                return React.createElement(React.Fragment, null,
                                    /* 업체명 검색 (업체 多 → 빠르게 찾기) */
                                    React.createElement('input', {
                                        type: 'text', value: clientSearch,
                                        onChange: function(e) { setClientSearch(e.target.value); },
                                        placeholder: '🔍 업체명 검색...',
                                        style: {
                                            width: '100%', boxSizing: 'border-box', padding: '10px 12px',
                                            borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, marginBottom: 8,
                                        }
                                    }),
                                    filtered.length === 0
                                        ? React.createElement('div', { style: { textAlign: 'center', padding: 16, color: '#94a3b8', fontSize: 13 } },
                                            "'" + clientSearch + "' 검색 결과가 없습니다.")
                                        : React.createElement('div', { style: { maxHeight: 200, overflowY: 'auto' } },
                                            filtered.map(function(c) {
                                                var isSelected = selectedClientId === c.id;
                                                return React.createElement('div', {
                                                    key: c.id,
                                                    onClick: function() { setSelectedClientId(c.id); },
                                                    style: {
                                                        padding: '10px 14px', borderRadius: 8, cursor: 'pointer', marginBottom: 4,
                                                        background: isSelected ? '#6C5CE7' : '#f8fafc',
                                                        color: isSelected ? '#fff' : '#1e293b',
                                                        border: '1px solid ' + (isSelected ? '#6C5CE7' : '#e2e8f0'),
                                                    }
                                                },
                                                    React.createElement('div', { style: { fontWeight: 600, fontSize: 14 } }, c.name),
                                                    c.main_keywords && React.createElement('div', { style: { fontSize: 11, opacity: 0.7, marginTop: 2 } }, c.main_keywords)
                                                );
                                            })
                                        )
                                );
                            })()
                    ),

                    /* 오류 메시지 */
                    message && !success && React.createElement('div', {
                        style: { color: '#dc2626', fontSize: 13, marginBottom: 12, padding: '8px 12px', background: '#fef2f2', borderRadius: 8 }
                    }, message),

                    /* 저장 버튼 */
                    React.createElement('button', {
                        onClick: handleSave,
                        disabled: saving,
                        style: {
                            width: '100%', padding: '12px', borderRadius: 10, border: 'none',
                            background: saving ? '#94a3b8' : '#6C5CE7', color: '#fff',
                            fontSize: 14, fontWeight: 600, cursor: saving ? 'default' : 'pointer',
                        }
                    }, saving ? '저장 중...' : '분석 결과 저장')
                )
            )
        )
    );
};
