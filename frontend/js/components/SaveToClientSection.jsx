/* SaveToClientSection — 분석 결과를 업체로 저장하는 섹션 */
window.SaveToClientSection = function SaveToClientSection({
    keyword, productUrl, analysisData, volumeData, relatedData, shopProducts, advertiserReport
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

    /* 기존 업체 목록 로드 */
    var loadClients = useCallback(function() {
        api.get('/cd/registered-clients').then(function(res) {
            if (res.success) setExistingClients(res.data || []);
        }).catch(function() {});
    }, []);

    useEffect(function() {
        if (showModal) loadClients();
    }, [showModal, loadClients]);

    if (!keyword || !analysisData) return null;

    /* DOM 캡처 — ReportSection과 동일한 로직으로 분석 화면 HTML 생성 */
    var captureReportHtml = function() {
        try {
            var captured = [];
            var rootEl = document.getElementById('root');
            if (rootEl && rootEl.children[0]) {
                var appDiv = rootEl.children[0];
                var children = Array.from(appDiv.children);
                children.forEach(function(child) {
                    if (child.classList.contains('topbar')) return;
                    if (child.querySelector && child.querySelector('.anchor-nav')) return;
                    var style = child.getAttribute('style') || '';
                    if (style.indexOf('sticky') !== -1 && style.indexOf('top') !== -1 && child.querySelector && child.querySelector('.anchor-btn')) return;
                    if (child.id === 'sec-report') return;
                    if (child.id === 'sec-notify') return;
                    if (child.id === 'sec-save-client') return;
                    if (child.querySelector && child.querySelector('#sec-report')) return;
                    if (child.querySelector && child.querySelector('#sec-notify')) return;
                    if (child.querySelector && child.querySelector('#sec-save-client')) return;
                    if (child.tagName === 'FOOTER') return;
                    if (!child.innerHTML || child.innerHTML.trim() === '') return;
                    if (child.querySelector && child.querySelector('.loading-spinner')) return;
                    captured.push(child.cloneNode(true));
                });
            }
            if (captured.length === 0) {
                var allSections = document.querySelectorAll('.section');
                allSections.forEach(function(s) {
                    if (s.id === 'sec-report' || s.id === 'sec-notify' || s.id === 'sec-save-client') return;
                    captured.push(s.cloneNode(true));
                });
            }
            captured.forEach(function(node) {
                var btns = node.querySelectorAll('button, .btn');
                btns.forEach(function(b) { b.remove(); });
                var inputs = node.querySelectorAll('input, select, textarea');
                inputs.forEach(function(inp) {
                    var span = document.createElement('span');
                    span.textContent = inp.value || '';
                    span.style.fontWeight = '600';
                    inp.parentNode.replaceChild(span, inp);
                });
            });
            var cssText = '';
            try {
                var sheets = document.styleSheets;
                for (var i = 0; i < sheets.length; i++) {
                    try {
                        var rules = sheets[i].cssRules || sheets[i].rules;
                        for (var j = 0; j < rules.length; j++) { cssText += rules[j].cssText + '\n'; }
                    } catch(e) {}
                }
            } catch(e) {}
            var bodyHtml = '';
            captured.forEach(function(node) { bodyHtml += node.outerHTML + '\n'; });
            var dateStr = new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
            var headerText = keyword + ' 키워드 분석 보고서';
            return '<!DOCTYPE html>\n<html lang="ko">\n<head>\n'
                + '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                + '<title>' + headerText + ' - ' + dateStr + '</title>\n<style>\n'
                + '* { margin: 0; padding: 0; box-sizing: border-box; }\n'
                + 'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #1e293b; }\n'
                + '.report-header { background: linear-gradient(135deg, #6C5CE7, #a29bfe); color: #fff; padding: 40px 20px; text-align: center; }\n'
                + '.report-header h1 { font-size: 24px; margin-bottom: 8px; }\n'
                + '.report-header p { font-size: 14px; opacity: 0.85; }\n'
                + '.report-footer { text-align: center; padding: 30px; color: #94a3b8; font-size: 12px; border-top: 1px solid #e2e8f0; margin-top: 40px; }\n'
                + cssText
                + '\n@media print { .report-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }\n'
                + '</style>\n</head>\n<body>\n'
                + '<div class="report-header">\n<h1>' + headerText + '</h1>\n'
                + '<p>' + dateStr + ' | \uba54\ud0c0\uc544\uc774\uc564\uc528 \ub85c\uc9c1 \ubd84\uc11d \uc2dc\uc2a4\ud15c</p>\n</div>\n'
                + '<div style="max-width:1200px; margin:0 auto; padding:20px;">\n' + bodyHtml + '</div>\n'
                + '<div class="report-footer">\n<p>\u00A9 2026 \uba54\ud0c0\uc544\uc774\uc564\uc528 \u2014 \ub85c\uc9c1 \ubd84\uc11d \uc2dc\uc2a4\ud15c | \ubcf8 \ubcf4\uace0\uc11c\ub294 \uc790\ub3d9 \uc0dd\uc131\ub418\uc5c8\uc2b5\ub2c8\ub2e4.</p>\n</div>\n'
                + '</body>\n</html>';
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
            analysis_data: analysisData,
            volume_data: volumeData || {},
            related_data: relatedData || {},
            shop_products: (shopProducts || []).slice(0, 20),
            advertiser_data: advertiserReport || {},
            report_html: reportHtml,
        };

        if (saveMode === 'new') {
            if (!clientName.trim()) {
                setMessage('업체명을 입력해주세요.');
                setSaving(false);
                return;
            }
            payload.name = clientName.trim();
            api.post('/cd/quick-register', payload).then(function(res) {
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
                    '"' + keyword + '" 분석 결과를 업체에 저장하시겠습니까?'
                ),
                React.createElement('div', { style: { fontSize: 13, opacity: 0.85, marginBottom: 16 } },
                    '업체로 저장하면 업체관리 탭에서 일자별 분석 데이터가 누적됩니다.'
                ),
                React.createElement('button', {
                    onClick: function() { setShowModal(true); },
                    style: {
                        background: '#fff', color: '#6C5CE7', border: 'none',
                        padding: '12px 32px', borderRadius: 10, fontSize: 15, fontWeight: 700,
                        cursor: 'pointer', boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
                    }
                }, '업체 등록 / 저장')
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
                style: {
                    background: '#fff', borderRadius: 16, padding: 28, width: 420,
                    maxWidth: '90vw', boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
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
                    /* 탭: 새 업체 / 기존 업체 */
                    React.createElement('div', { style: { display: 'flex', gap: 8, marginBottom: 16 } },
                        React.createElement('button', {
                            onClick: function() { setSaveMode('new'); },
                            style: {
                                flex: 1, padding: '10px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                background: saveMode === 'new' ? '#6C5CE7' : '#f1f5f9',
                                color: saveMode === 'new' ? '#fff' : '#64748b',
                                border: saveMode === 'new' ? '1px solid #6C5CE7' : '1px solid #e2e8f0',
                            }
                        }, '새 업체 등록'),
                        React.createElement('button', {
                            onClick: function() { setSaveMode('existing'); },
                            style: {
                                flex: 1, padding: '10px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                                background: saveMode === 'existing' ? '#6C5CE7' : '#f1f5f9',
                                color: saveMode === 'existing' ? '#fff' : '#64748b',
                                border: saveMode === 'existing' ? '1px solid #6C5CE7' : '1px solid #e2e8f0',
                            }
                        }, '기존 업체에 추가 (' + existingClients.length + ')')
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
                            : React.createElement('div', { style: { maxHeight: 200, overflowY: 'auto' } },
                                existingClients.map(function(c) {
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
