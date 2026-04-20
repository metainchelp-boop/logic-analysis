/* UserGuidePage — 내부 직원용 사용자 가이드북 (v3.9 Enhanced) */
window.UserGuidePage = function UserGuidePage({ currentUser }) {
    const { useState } = React;
    const [activeSection, setActiveSection] = useState('overview');

    var sections = [
        { id: 'overview', icon: '\uD83D\uDCCB', label: '프로그램 개요' },
        { id: 'cost', icon: '\uD83D\uDCB0', label: '비용 안내' },
        { id: 'quickstart', icon: '\uD83D\uDE80', label: '빠른 시작 가이드' },
        { id: 'login', icon: '\uD83D\uDD10', label: '로그인 & 권한' },
        { id: 'analysis', icon: '\uD83D\uDCCA', label: '분석 탭 사용법' },
        { id: 'data', icon: '\uD83D\uDCC8', label: '데이터 해석 방법' },
        { id: 'management', icon: '\uD83C\uDFE2', label: '업체관리 사용법' },
        { id: 'rank', icon: '\uD83C\uDFC6', label: '순위 추적 해석' },
        { id: 'report', icon: '\uD83D\uDCC4', label: '보고서 활용' },
        { id: 'advanced', icon: '\u2699\uFE0F', label: '고급 활용법' },
        { id: 'tips', icon: '\uD83D\uDCA1', label: '실전 활용 팁' },
        { id: 'faq', icon: '\u2753', label: '자주 묻는 질문' },
    ];

    var cardStyle = { background: '#fff', borderRadius: 14, padding: '28px 32px', marginBottom: 20, boxShadow: '0 1px 4px rgba(0,0,0,0.06)' };
    var h2Style = { fontSize: 20, fontWeight: 700, color: '#1e293b', marginBottom: 18, display: 'flex', alignItems: 'center', gap: 8 };
    var h3Style = { fontSize: 16, fontWeight: 700, color: '#334155', marginTop: 24, marginBottom: 10 };
    var h4Style = { fontSize: 14, fontWeight: 700, color: '#475569', marginTop: 18, marginBottom: 8 };
    var pStyle = { fontSize: 14, color: '#475569', lineHeight: 1.8, marginBottom: 12 };
    var tipBoxStyle = { background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 10, padding: '14px 18px', marginBottom: 14, fontSize: 13, color: '#1e40af', lineHeight: 1.7 };
    var warnBoxStyle = { background: '#fef3c7', border: '1px solid #fde68a', borderRadius: 10, padding: '14px 18px', marginBottom: 14, fontSize: 13, color: '#92400e', lineHeight: 1.7 };
    var costBoxStyle = { background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10, padding: '14px 18px', marginBottom: 14, fontSize: 13, color: '#991b1b', lineHeight: 1.7 };
    var successBoxStyle = { background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: '14px 18px', marginBottom: 14, fontSize: 13, color: '#166534', lineHeight: 1.7 };
    var tableStyle = { width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 16 };
    var thStyle = { background: '#f1f5f9', padding: '10px 14px', textAlign: 'left', fontWeight: 600, color: '#475569', borderBottom: '2px solid #e2e8f0' };
    var tdStyle = { padding: '10px 14px', borderBottom: '1px solid #f1f5f9', color: '#334155' };
    var tdCenterStyle = { padding: '10px 14px', borderBottom: '1px solid #f1f5f9', color: '#334155', textAlign: 'center' };
    var tdRightStyle = { padding: '10px 14px', borderBottom: '1px solid #f1f5f9', color: '#334155', textAlign: 'right', fontWeight: 600 };
    var badgeStyle = function(bg, color) { return { display: 'inline-block', padding: '2px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: bg, color: color, marginRight: 4 }; };
    var stepNumStyle = { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 24, height: 24, borderRadius: '50%', background: '#6C5CE7', color: '#fff', fontSize: 12, fontWeight: 700, marginRight: 8, flexShrink: 0 };
    var stepRowStyle = { display: 'flex', alignItems: 'flex-start', marginBottom: 14 };
    var dividerStyle = { border: 'none', borderTop: '1px solid #e2e8f0', margin: '24px 0' };

    var renderContent = function() {
        switch (activeSection) {

        /* ==================== 프로그램 개요 ==================== */
        case 'overview':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\uD83D\uDCCB \uD504\uB85C\uADF8\uB7A8 \uAC1C\uC694'),
                    React.createElement('p', { style: pStyle },
                        '\uB85C\uC9C1 \uBD84\uC11D\uC740 \uB124\uC774\uBC84 \uC1FC\uD551 \uD0A4\uC6CC\uB4DC\uC758 \uC2DC\uC7A5 \uACBD\uC7C1 \uD604\uD669\uC744 AI \uAE30\uBC18\uC73C\uB85C \uBD84\uC11D\uD558\uACE0, \uB4F1\uB85D\uB41C \uC5C5\uCCB4\uC758 \uC0C1\uD488 \uC21C\uC704\uB97C \uC790\uB3D9 \uCD94\uC801\uD558\uB294 \uB0B4\uBD80 \uC5C5\uBB34 \uB3C4\uAD6C\uC785\uB2C8\uB2E4. \uB9E4\uC77C \uC0C8\uBCBD 5\uC2DC\uC5D0 \uC804\uCCB4 \uC5C5\uCCB4\uC758 \uD0A4\uC6CC\uB4DC\uB97C \uC790\uB3D9 \uBD84\uC11D\uD558\uC5EC \uC77C\uC790\uBCC4 \uCD94\uC774\uB97C \uB204\uC801 \uAD00\uB9AC\uD569\uB2C8\uB2E4.'
                    ),
                    React.createElement('p', { style: pStyle },
                        '\uBD84\uC11D \uACB0\uACFC\uB294 11\uAC00\uC9C0 \uC139\uC158(\uACBD\uC7C1\uAC15\uB3C4, \uC2DC\uC7A5\uADDC\uBAA8, \uACE8\uB4E0\uD0A4\uC6CC\uB4DC, \uAD11\uACE0\uBD84\uC11D, \uACBD\uC7C1\uC0AC \uBE44\uAD50 \uB4F1)\uC73C\uB85C \uAD6C\uC131\uB418\uBA70, \uAC01 \uC139\uC158\uC5D0 Claude AI\uAC00 \uB9DE\uCDA4\uD615 \uD53C\uB4DC\uBC31\uC744 \uC81C\uACF5\uD569\uB2C8\uB2E4. HTML \uBCF4\uACE0\uC11C\uB85C \uB2E4\uC6B4\uB85C\uB4DC\uD558\uC5EC \uACE0\uAC1D \uBBF8\uD305\uC774\uB098 \uB0B4\uBD80 \uBCF4\uACE0\uC5D0 \uD65C\uC6A9\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC8FC\uC694 \uAE30\uB2A5'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uAE30\uB2A5'),
                                React.createElement('th', { style: thStyle }, '\uC124\uBA85'),
                                React.createElement('th', { style: thStyle }, '\uC704\uCE58')
                            )
                        ),
                        React.createElement('tbody', null,
                            [
                                ['\uD0A4\uC6CC\uB4DC \uBD84\uC11D', '\uAC80\uC0C9\uB7C9, \uACBD\uC7C1\uAC15\uB3C4, \uC2DC\uC7A5\uADDC\uBAA8, \uACE8\uB4E0\uD0A4\uC6CC\uB4DC \uB4F1 11\uAC00\uC9C0 + AI \uD53C\uB4DC\uBC31', '\uBD84\uC11D \uD0ED'],
                                ['\uC5C5\uCCB4\uAD00\uB9AC', '\uC5C5\uCCB4\uBCC4 \uD0A4\uC6CC\uB4DC \uBD84\uC11D \uB204\uC801, \uC77C\uC790\uBCC4 \uCD94\uC774, \uC21C\uC704 \uC774\uB825', '\uC5C5\uCCB4\uAD00\uB9AC \uD0ED'],
                                ['\uC790\uB3D9 \uBD84\uC11D', '\uB9E4\uC77C 05:00 \uC804\uCCB4 \uC5C5\uCCB4 \uD0A4\uC6CC\uB4DC \uC790\uB3D9 \uBD84\uC11D + HTML \uBCF4\uACE0\uC11C', '\uC790\uB3D9 (\uC2A4\uCF00\uC904\uB7EC)'],
                                ['\uC21C\uC704 \uCD94\uC801', '\uB4F1\uB85D \uC0C1\uD488\uC758 \uD0A4\uC6CC\uB4DC\uBCC4 \uB124\uC774\uBC84 \uC1FC\uD551 \uC21C\uC704 \uC790\uB3D9 \uAE30\uB85D', '\uC5C5\uCCB4\uAD00\uB9AC > \uC21C\uC704 \uC774\uB825'],
                                ['HTML \uBCF4\uACE0\uC11C', '\uBD84\uC11D \uACB0\uACFC\uB97C \uAE54\uB054\uD55C HTML \uBB38\uC11C\uB85C \uB2E4\uC6B4\uB85C\uB4DC', '\uBD84\uC11D \uD0ED \uD558\uB2E8 / \uC5C5\uCCB4\uAD00\uB9AC'],
                                ['AI \uD53C\uB4DC\uBC31', 'Claude AI\uAC00 \uAC01 \uBD84\uC11D \uC139\uC158\uC5D0 \uB9DE\uCDA4\uD615 \uC804\uB7B5 \uC81C\uC548', '\uBD84\uC11D \uACB0\uACFC \uB0B4 \uAC01 \uC139\uC158'],
                            ].map(function(row, i) {
                                return React.createElement('tr', { key: i },
                                    React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600, whiteSpace: 'nowrap' }) }, row[0]),
                                    React.createElement('td', { style: tdStyle }, row[1]),
                                    React.createElement('td', { style: Object.assign({}, tdStyle, { whiteSpace: 'nowrap' }) }, row[2])
                                );
                            })
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC2DC\uC2A4\uD15C \uAD6C\uC131\uB3C4'),
                    React.createElement('div', { style: tipBoxStyle },
                        '\uD504\uB860\uD2B8\uC5D4\uB4DC: React \uAE30\uBC18 SPA (Single Page Application)\n\uBC31\uC5D4\uB4DC: FastAPI (Python) + SQLite \uB370\uC774\uD130\uBCA0\uC774\uC2A4\n\uC678\uBD80 API: \uB124\uC774\uBC84 \uAC80\uC0C9\uAD11\uACE0 API + \uB124\uC774\uBC84 \uC1FC\uD551 \uB370\uC774\uD130\uC218\uC9D1(Bright Data)\nAI \uC5D4\uC9C4: Claude API (Anthropic) \u2014 \uBD84\uC11D \uACB0\uACFC \uD53C\uB4DC\uBC31 \uC0DD\uC131\n\uC11C\uBC84: Docker \uCEE8\uD14C\uC774\uB108 \uAE30\uBC18 VPS \uBC30\uD3EC'
                    )
                ),

                /* 운영 시간표 */
                React.createElement('div', { style: cardStyle },
                    React.createElement('h3', { style: Object.assign({}, h3Style, { marginTop: 0 }) }, '\uC6B4\uC601 \uC2DC\uAC04\uD45C'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uC2DC\uAC04'),
                                React.createElement('th', { style: thStyle }, '\uC791\uC5C5'),
                                React.createElement('th', { style: thStyle }, '\uBE44\uC6A9 \uBC1C\uC0DD')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC624\uC804 07:00'),
                                React.createElement('td', { style: tdStyle }, '\uC790\uB3D9 \uBD84\uC11D \uC2A4\uCF00\uC904\uB7EC \uC2E4\uD589 (\uC804\uCCB4 \uC5C5\uCCB4 \uD0A4\uC6CC\uB4DC \uBD84\uC11D + \uC21C\uC704 \uCCB4\uD06C)'),
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#dcfce7', '#16a34a') }, 'API\uBE44\uC6A9\uB9CC (AI \uBBF8\uD638\uCD9C)'))
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC5C5\uBB34 \uC2DC\uAC04'),
                                React.createElement('td', { style: tdStyle }, '\uC9C1\uC6D0 \uC218\uB3D9 \uBD84\uC11D (\uBD84\uC11D \uD0ED \uB610\uB294 \uC5C5\uCCB4\uAD00\uB9AC\uC5D0\uC11C \uC2E4\uD589)'),
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#fee2e2', '#dc2626') }, 'API + AI \uBE44\uC6A9 \uBC1C\uC0DD'))
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC218\uC2DC'),
                                React.createElement('td', { style: tdStyle }, '\uC21C\uC704 \uC774\uB825 \uC870\uD68C, \uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC, \uB370\uC774\uD130 \uD655\uC778'),
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#dcfce7', '#16a34a') }, '\uBB34\uB8CC (\uC800\uC7A5\uB41C \uB370\uC774\uD130 \uC870\uD68C)'))
                            )
                        )
                    )
                )
            );

        /* ==================== 비용 안내 ==================== */
        case 'cost':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\uD83D\uDCB0 \uBD84\uC11D \uBE44\uC6A9 \uC548\uB0B4'),
                    React.createElement('p', { style: pStyle },
                        '\uBD84\uC11D\uC744 \uC2E4\uD589\uD560 \uB54C\uB9C8\uB2E4 \uC678\uBD80 API \uD638\uCD9C \uBE44\uC6A9\uC774 \uBC1C\uC0DD\uD569\uB2C8\uB2E4. \uBD88\uD544\uC694\uD55C \uBD84\uC11D\uC744 \uC904\uC774\uACE0, \uD6A8\uC728\uC801\uC73C\uB85C \uC0AC\uC6A9\uD574\uC57C \uD68C\uC0AC \uBE44\uC6A9\uC744 \uC808\uAC10\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'
                    ),
                    React.createElement('div', { style: costBoxStyle },
                        '\u26A0\uFE0F \uC911\uC694: \uBD84\uC11D \uBC84\uD2BC\uC744 \uB204\uB97C \uB54C\uB9C8\uB2E4 \uC2E4\uC81C \uBE44\uC6A9\uC774 \uBC1C\uC0DD\uD569\uB2C8\uB2E4. \uD14C\uC2A4\uD2B8 \uBAA9\uC801\uC758 \uBB34\uC758\uBBF8\uD55C \uBC18\uBCF5 \uBD84\uC11D\uC740 \uC790\uC81C\uD574\uC8FC\uC138\uC694.'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uBE44\uC6A9 \uBC1C\uC0DD \uAD6C\uC870'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uD56D\uBAA9'),
                                React.createElement('th', { style: thStyle }, '\uC124\uBA85'),
                                React.createElement('th', { style: Object.assign({}, thStyle, { textAlign: 'right' }) }, '\uBE44\uC6A9')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, 'Claude AI \uD53C\uB4DC\uBC31'),
                                React.createElement('td', { style: tdStyle }, '\uBD84\uC11D \uACB0\uACFC 9\uAC1C \uC139\uC158\uC5D0 AI\uAC00 \uB9DE\uCDA4\uD615 \uC804\uB7B5 \uC81C\uC548'),
                                React.createElement('td', { style: tdRightStyle }, '1\uD68C \uD638\uCD9C\uB2F9 $0.012 (\uC57D 17\uC6D0)')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, 'Bright Data \uB370\uC774\uD130 \uC218\uC9D1'),
                                React.createElement('td', { style: tdStyle }, '\uB124\uC774\uBC84 \uC1FC\uD551 \uC0C1\uC704 \uC0C1\uD488 \uB370\uC774\uD130 \uD06C\uB864\uB9C1'),
                                React.createElement('td', { style: tdRightStyle }, '\uBD84\uC11D 1\uAC74\uB2F9 \uD3EC\uD568')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uB124\uC774\uBC84 \uAC80\uC0C9\uAD11\uACE0 API'),
                                React.createElement('td', { style: tdStyle }, '\uAC80\uC0C9\uB7C9, \uD074\uB9AD\uC218, \uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4 \uC870\uD68C'),
                                React.createElement('td', { style: tdRightStyle }, '\uBB34\uB8CC (API \uD0A4 \uAE30\uBC18)')
                            )
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, '\uBD84\uC11D 1\uAC74\uB2F9 \uBE44\uC6A9'),
                    React.createElement('div', { style: Object.assign({}, cardStyle, { background: '#fafafa', padding: '20px 24px', boxShadow: 'none', border: '1px solid #e2e8f0' }) },
                        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 } },
                            React.createElement('div', { style: { textAlign: 'center', flex: 1, minWidth: 120 } },
                                React.createElement('div', { style: { fontSize: 12, color: '#94a3b8', marginBottom: 4 } }, 'AI \uD53C\uB4DC\uBC31 9\uC139\uC158'),
                                React.createElement('div', { style: { fontSize: 24, fontWeight: 700, color: '#dc2626' } }, '$0.11'),
                                React.createElement('div', { style: { fontSize: 11, color: '#94a3b8' } }, '\uC57D 155\uC6D0')
                            ),
                            React.createElement('div', { style: { fontSize: 20, color: '#cbd5e1' } }, '+'),
                            React.createElement('div', { style: { textAlign: 'center', flex: 1, minWidth: 120 } },
                                React.createElement('div', { style: { fontSize: 12, color: '#94a3b8', marginBottom: 4 } }, '\uB370\uC774\uD130 \uC218\uC9D1 + API'),
                                React.createElement('div', { style: { fontSize: 24, fontWeight: 700, color: '#f59e0b' } }, '$0.03~'),
                                React.createElement('div', { style: { fontSize: 11, color: '#94a3b8' } }, '\uC57D 40\uC6D0~')
                            ),
                            React.createElement('div', { style: { fontSize: 20, color: '#cbd5e1' } }, '='),
                            React.createElement('div', { style: { textAlign: 'center', flex: 1, minWidth: 120 } },
                                React.createElement('div', { style: { fontSize: 12, color: '#94a3b8', marginBottom: 4 } }, '\uBD84\uC11D 1\uAC74 \uCD1D\uBE44\uC6A9'),
                                React.createElement('div', { style: { fontSize: 24, fontWeight: 700, color: '#1e293b' } }, '\uC57D 200\uC6D0'),
                                React.createElement('div', { style: { fontSize: 11, color: '#94a3b8' } }, '\uD0A4\uC6CC\uB4DC 1\uAC1C \uAE30\uC900')
                            )
                        )
                    )
                ),

                /* 월간 비용 시뮬레이션 */
                React.createElement('div', { style: cardStyle },
                    React.createElement('h3', { style: Object.assign({}, h3Style, { marginTop: 0 }) }, '\uD300 \uADDC\uBAA8\uBCC4 \uC6D4\uAC04 \uBE44\uC6A9 \uC2DC\uBBAC\uB808\uC774\uC158'),
                    React.createElement('p', { style: pStyle }, '\uC544\uB798\uB294 AI \uD53C\uB4DC\uBC31 \uBE44\uC6A9\uB9CC \uAE30\uC900\uC73C\uB85C \uC0B0\uCD9C\uD55C \uC608\uC0C1 \uC6D4\uAC04 \uBE44\uC6A9\uC785\uB2C8\uB2E4.'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uC2DC\uB098\uB9AC\uC624'),
                                React.createElement('th', { style: Object.assign({}, thStyle, { textAlign: 'center' }) }, '\uC9C1\uC6D0 \uC218'),
                                React.createElement('th', { style: Object.assign({}, thStyle, { textAlign: 'center' }) }, '\uC77C \uBD84\uC11D \uD69F\uC218'),
                                React.createElement('th', { style: Object.assign({}, thStyle, { textAlign: 'center' }) }, '\uC6D4 \uCD1D \uBD84\uC11D'),
                                React.createElement('th', { style: Object.assign({}, thStyle, { textAlign: 'right' }) }, '\uC608\uC0C1 \uC6D4 \uBE44\uC6A9')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC18C\uADDC\uBAA8'),
                                React.createElement('td', { style: tdCenterStyle }, '3\uBA85'),
                                React.createElement('td', { style: tdCenterStyle }, '\uC778\uB2F9 5\uAC74'),
                                React.createElement('td', { style: tdCenterStyle }, '450\uAC74'),
                                React.createElement('td', { style: Object.assign({}, tdRightStyle, { color: '#16a34a' }) }, '\uC57D 7.2\uB9CC\uC6D0')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC911\uADDC\uBAA8'),
                                React.createElement('td', { style: tdCenterStyle }, '5\uBA85'),
                                React.createElement('td', { style: tdCenterStyle }, '\uC778\uB2F9 10\uAC74'),
                                React.createElement('td', { style: tdCenterStyle }, '1,500\uAC74'),
                                React.createElement('td', { style: Object.assign({}, tdRightStyle, { color: '#f59e0b' }) }, '\uC57D 23.5\uB9CC\uC6D0')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uB300\uADDC\uBAA8'),
                                React.createElement('td', { style: tdCenterStyle }, '10\uBA85'),
                                React.createElement('td', { style: tdCenterStyle }, '\uC778\uB2F9 15\uAC74'),
                                React.createElement('td', { style: tdCenterStyle }, '4,500\uAC74'),
                                React.createElement('td', { style: Object.assign({}, tdRightStyle, { color: '#dc2626' }) }, '\uC57D 71\uB9CC\uC6D0')
                            )
                        )
                    ),
                    React.createElement('div', { style: warnBoxStyle },
                        '\u26A0\uFE0F \uC704 \uAE08\uC561\uC740 AI \uD53C\uB4DC\uBC31 \uBE44\uC6A9\uB9CC \uAE30\uC900\uC785\uB2C8\uB2E4. Bright Data \uB370\uC774\uD130 \uC218\uC9D1 \uBE44\uC6A9\uC774 \uCD94\uAC00\uB85C \uBC1C\uC0DD\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.\n\uBD84\uC11D \uD69F\uC218 = \uD0A4\uC6CC\uB4DC 1\uAC1C\uB2F9 1\uAC74\uC73C\uB85C \uACC4\uC0B0\uD569\uB2C8\uB2E4.'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC0C8\uBCBD \uC790\uB3D9 \uBD84\uC11D\uC740 \uBB34\uB8CC\uC785\uB2C8\uB2E4'),
                    React.createElement('div', { style: successBoxStyle },
                        '\u2705 \uC624\uC804 07:00 \uC790\uB3D9 \uBD84\uC11D \uC2A4\uCF00\uC904\uB7EC\uB294 AI \uD53C\uB4DC\uBC31\uC744 \uD638\uCD9C\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.\n\u2705 \uC608\uC2DC: 50\uAC1C \uC5C5\uCCB4 \u00D7 \uD0A4\uC6CC\uB4DC 3\uAC1C = \uD558\uB8E8 150\uAC74 \uC790\uB3D9 \uBD84\uC11D \u2192 AI \uBE44\uC6A9 0\uC6D0\n\u2705 \uAE30\uBCF8 \uB370\uC774\uD130(\uAC80\uC0C9\uB7C9, \uACBD\uC7C1\uC9C0\uC218, \uC21C\uC704 \uB4F1)\uB294 \uBB34\uB8CC\uB85C \uC218\uC9D1\uB429\uB2C8\uB2E4.\n\u2139\uFE0F AI \uD53C\uB4DC\uBC31\uC774 \uD544\uC694\uD55C \uACBD\uC6B0 \uC5C5\uBB34 \uC2DC\uAC04\uC5D0 \uC218\uB3D9\uC73C\uB85C \uBD84\uC11D\uC744 \uC2E4\uD589\uD574\uC8FC\uC138\uC694.'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uBE44\uC6A9 \uC808\uAC10 \uC694\uB839'),
                    React.createElement('div', { style: tipBoxStyle },
                        '\uD83D\uDCA1 \uAC19\uC740 \uD0A4\uC6CC\uB4DC\uB97C \uD558\uB8E8\uC5D0 \uC5EC\uB7EC \uBC88 \uBD84\uC11D\uD558\uC9C0 \uB9C8\uC138\uC694. \uC2DC\uC7A5 \uB370\uC774\uD130\uB294 \uC77C\uB2E8\uC704\uB85C \uBCC0\uD569\uB2C8\uB2E4.\n\uD83D\uDCA1 \uC0C8\uBCBD \uC790\uB3D9 \uBD84\uC11D\uC73C\uB85C \uCDA9\uBD84\uD55C \uACBD\uC6B0, \uC218\uB3D9 \uBD84\uC11D \uC5C6\uC774 \uC800\uC7A5\uB41C \uB370\uC774\uD130\uB9CC \uD655\uC778\uD558\uC138\uC694.\n\uD83D\uDCA1 \uD14C\uC2A4\uD2B8 \uBAA9\uC801\uC758 \uBC18\uBCF5 \uBD84\uC11D\uC740 \uBE44\uC6A9\uB9CC \uBC1C\uC0DD\uD558\uACE0 \uC758\uBBF8 \uC5C6\uB294 \uACB0\uACFC\uAC00 \uB098\uC635\uB2C8\uB2E4.\n\uD83D\uDCA1 \uC5C5\uCCB4\uAD00\uB9AC\uC5D0\uC11C \uC77C\uC790\uBCC4 \uCD94\uC774\uB97C \uD655\uC778\uD558\uB294 \uAC83\uC740 \uBB34\uB8CC\uC785\uB2C8\uB2E4 (\uC774\uBBF8 \uC800\uC7A5\uB41C \uB370\uC774\uD130 \uC870\uD68C).'
                    )
                )
            );

        /* ==================== 빠른 시작 가이드 ==================== */
        case 'quickstart':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\uD83D\uDE80 \uBE60\uB978 \uC2DC\uC791 \uAC00\uC774\uB4DC'),
                    React.createElement('p', { style: pStyle }, '\uCC98\uC74C \uC0AC\uC6A9\uD558\uC2DC\uB294 \uBD84\uC744 \uC704\uD55C 5\uBD84 \uD575\uC2EC \uAC00\uC774\uB4DC\uC785\uB2C8\uB2E4. \uC544\uB798 \uC21C\uC11C\uB300\uB85C \uB530\uB77C\uD558\uC138\uC694.'),

                    React.createElement('div', { style: stepRowStyle },
                        React.createElement('span', { style: stepNumStyle }, '1'),
                        React.createElement('div', null,
                            React.createElement('div', { style: { fontWeight: 600, fontSize: 14, color: '#1e293b', marginBottom: 4 } }, '\uB85C\uADF8\uC778'),
                            React.createElement('p', { style: Object.assign({}, pStyle, { marginBottom: 0 }) }, '\uAD00\uB9AC\uC790\uAC00 \uBC1C\uAE09\uD55C \uACC4\uC815(ID/\uBE44\uBC00\uBC88\uD638)\uC73C\uB85C \uB85C\uADF8\uC778\uD569\uB2C8\uB2E4. \uCD5C\uCD08 \uB85C\uADF8\uC778 \uD6C4 \uBC18\uB4DC\uC2DC \uBE44\uBC00\uBC88\uD638\uB97C \uBCC0\uACBD\uD574\uC8FC\uC138\uC694.')
                        )
                    ),
                    React.createElement('div', { style: stepRowStyle },
                        React.createElement('span', { style: stepNumStyle }, '2'),
                        React.createElement('div', null,
                            React.createElement('div', { style: { fontWeight: 600, fontSize: 14, color: '#1e293b', marginBottom: 4 } }, '\uBD84\uC11D \uD0ED\uC5D0\uC11C \uD0A4\uC6CC\uB4DC \uBD84\uC11D'),
                            React.createElement('p', { style: Object.assign({}, pStyle, { marginBottom: 0 }) }, '\uBD84\uC11D \uD0ED\uC73C\uB85C \uC774\uB3D9 \u2192 \uD0A4\uC6CC\uB4DC \uC785\uB825 (ex: "\uBB34\uC120\uC774\uC5B4\uD3F0") \u2192 \uBD84\uC11D \uBC84\uD2BC \uD074\uB9AD. \uACB0\uACFC\uAC00 \uC57D 5~10\uCD08 \uD6C4 11\uAC00\uC9C0 \uC139\uC158\uC73C\uB85C \uD45C\uC2DC\uB429\uB2C8\uB2E4.')
                        )
                    ),
                    React.createElement('div', { style: stepRowStyle },
                        React.createElement('span', { style: stepNumStyle }, '3'),
                        React.createElement('div', null,
                            React.createElement('div', { style: { fontWeight: 600, fontSize: 14, color: '#1e293b', marginBottom: 4 } }, 'AI \uD53C\uB4DC\uBC31 \uD655\uC778'),
                            React.createElement('p', { style: Object.assign({}, pStyle, { marginBottom: 0 }) }, '\uAC01 \uBD84\uC11D \uC139\uC158 \uD558\uB2E8\uC5D0 Claude AI\uC758 \uB9DE\uCDA4\uD615 \uC804\uB7B5 \uC81C\uC548\uC774 \uD45C\uC2DC\uB429\uB2C8\uB2E4. \uC2DC\uC7A5 \uD604\uD669\uC5D0 \uB300\uD55C \uD575\uC2EC \uC778\uC0AC\uC774\uD2B8\uB97C \uD655\uC778\uD558\uC138\uC694.')
                        )
                    ),
                    React.createElement('div', { style: stepRowStyle },
                        React.createElement('span', { style: stepNumStyle }, '4'),
                        React.createElement('div', null,
                            React.createElement('div', { style: { fontWeight: 600, fontSize: 14, color: '#1e293b', marginBottom: 4 } }, '\uC5C5\uCCB4 \uB4F1\uB85D & \uCD94\uC801'),
                            React.createElement('p', { style: Object.assign({}, pStyle, { marginBottom: 0 }) }, '\uBD84\uC11D \uACB0\uACFC\uAC00 \uB9C8\uC74C\uC5D0 \uB4E4\uBA74 "\uC5C5\uCCB4\uC5D0 \uC800\uC7A5" \uBC84\uD2BC\uC744 \uB20C\uB7EC \uC5C5\uCCB4\uAD00\uB9AC\uC5D0 \uB4F1\uB85D\uD558\uC138\uC694. \uC774\uD6C4 \uC77C\uC790\uBCC4 \uCD94\uC774\uC640 \uC21C\uC704 \uBCC0\uD654\uB97C \uC790\uB3D9 \uCD94\uC801\uD569\uB2C8\uB2E4.')
                        )
                    ),
                    React.createElement('div', { style: stepRowStyle },
                        React.createElement('span', { style: stepNumStyle }, '5'),
                        React.createElement('div', null,
                            React.createElement('div', { style: { fontWeight: 600, fontSize: 14, color: '#1e293b', marginBottom: 4 } }, '\uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC'),
                            React.createElement('p', { style: Object.assign({}, pStyle, { marginBottom: 0 }) }, '\uBD84\uC11D \uACB0\uACFC \uD558\uB2E8 "HTML \uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC" \uBC84\uD2BC\uC73C\uB85C \uBCF4\uACE0\uC11C\uB97C \uC800\uC7A5\uD558\uC138\uC694. \uACE0\uAC1D \uBBF8\uD305\uC774\uB098 \uB0B4\uBD80 \uBCF4\uACE0\uC5D0 \uD65C\uC6A9\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.')
                        )
                    ),

                    React.createElement('hr', { style: dividerStyle }),
                    React.createElement('div', { style: successBoxStyle },
                        '\u2705 \uCD95\uD558\uD569\uB2C8\uB2E4! \uC704 5\uB2E8\uACC4\uB9CC \uC54C\uBA74 \uAE30\uBCF8\uC801\uC778 \uC0AC\uC6A9\uC774 \uAC00\uB2A5\uD569\uB2C8\uB2E4.\n\uB354 \uC790\uC138\uD55C \uC0AC\uC6A9\uBC95\uC740 \uC88C\uCE21 \uBA54\uB274\uC758 \uAC01 \uD56D\uBAA9\uC744 \uCC38\uACE0\uD574\uC8FC\uC138\uC694.'
                    )
                )
            );

        /* ==================== 로그인 & 권한 ==================== */
        case 'login':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\uD83D\uDD10 \uB85C\uADF8\uC778 & \uAD8C\uD55C \uCCB4\uACC4'),
                    React.createElement('p', { style: pStyle }, '\uB85C\uADF8\uC778 \uD6C4 \uBD80\uC5EC\uB41C \uC5ED\uD560(Role)\uC5D0 \uB530\uB77C \uC811\uADFC \uAC00\uB2A5\uD55C \uAE30\uB2A5\uC774 \uB2E4\uB985\uB2C8\uB2E4.'),

                    React.createElement('h3', { style: h3Style }, '\uC5ED\uD560\uBCC4 \uAD8C\uD55C \uBE44\uAD50'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uC5ED\uD560'),
                                React.createElement('th', { style: thStyle }, '\uBD84\uC11D'),
                                React.createElement('th', { style: thStyle }, '\uC5C5\uCCB4\uAD00\uB9AC'),
                                React.createElement('th', { style: thStyle }, '\uC5C5\uCCB4 \uB4F1\uB85D/\uC0AD\uC81C'),
                                React.createElement('th', { style: thStyle }, '\uC9C1\uC6D0 \uAD00\uB9AC'),
                                React.createElement('th', { style: thStyle }, '\uC54C\uB9BC \uC124\uC815')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#fee2e2', '#dc2626') }, 'Admin')),
                                React.createElement('td', { style: tdCenterStyle }, '\u2705'), React.createElement('td', { style: tdCenterStyle }, '\u2705'),
                                React.createElement('td', { style: tdCenterStyle }, '\u2705'), React.createElement('td', { style: tdCenterStyle }, '\u2705'),
                                React.createElement('td', { style: tdCenterStyle }, '\u2705')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#dbeafe', '#1d4ed8') }, 'Manager')),
                                React.createElement('td', { style: tdCenterStyle }, '\u2705'), React.createElement('td', { style: tdCenterStyle }, '\u2705'),
                                React.createElement('td', { style: tdCenterStyle }, '\u2705 (\uBCF8\uC778 \uB4F1\uB85D\uBD84)'), React.createElement('td', { style: tdCenterStyle }, '\u274C'),
                                React.createElement('td', { style: tdCenterStyle }, '\u274C')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#f1f5f9', '#64748b') }, 'Viewer')),
                                React.createElement('td', { style: tdCenterStyle }, '\u2705 (\uC77C 3\uD68C)'), React.createElement('td', { style: tdCenterStyle }, '\u2705 (\uC804\uCCB4 \uC5C5\uCCB4 \uC870\uD68C)'),
                                React.createElement('td', { style: tdCenterStyle }, '\u274C'), React.createElement('td', { style: tdCenterStyle }, '\u274C'),
                                React.createElement('td', { style: tdCenterStyle }, '\u274C')
                            )
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, '\uBE44\uBC00\uBC88\uD638 \uBCC0\uACBD'),
                    React.createElement('p', { style: pStyle }, '\uC0C1\uB2E8 \uD0ED\uBC14 \uC6B0\uCE21\uC758 "\uBE44\uBC00\uBC88\uD638 \uBCC0\uACBD" \uBC84\uD2BC\uC744 \uD074\uB9AD\uD558\uBA74 \uD604\uC7AC \uBE44\uBC00\uBC88\uD638\uC640 \uC0C8 \uBE44\uBC00\uBC88\uD638\uB97C \uC785\uB825\uD558\uB294 \uD31D\uC5C5\uC774 \uB098\uD0C0\uB0A9\uB2C8\uB2E4.'),
                    React.createElement('div', { style: warnBoxStyle }, '\u26A0\uFE0F \uCD5C\uCD08 \uB85C\uADF8\uC778 \uD6C4 \uBC18\uB4DC\uC2DC \uBE44\uBC00\uBC88\uD638\uB97C \uBCC0\uACBD\uD574\uC8FC\uC138\uC694. \uCD08\uAE30 \uBE44\uBC00\uBC88\uD638\uB294 \uBCF4\uC548\uC5D0 \uCDE8\uC57D\uD569\uB2C8\uB2E4.'),

                    React.createElement('h3', { style: h3Style }, '\uB85C\uADF8\uC778 \uC774\uB825'),
                    React.createElement('p', { style: pStyle }, '\uAD00\uB9AC\uC790\uB294 \uC9C1\uC6D0 \uAD00\uB9AC \uD0ED\uC5D0\uC11C \uAC01 \uACC4\uC815\uC758 \uB85C\uADF8\uC778 \uC774\uB825(\uC2DC\uAC04, IP \uC8FC\uC18C)\uC744 \uD655\uC778\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4. \uBE44\uC815\uC0C1\uC801\uC778 \uC811\uADFC\uC774 \uAC10\uC9C0\uB418\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C \uBB38\uC758\uD558\uC138\uC694.'),
                    React.createElement('div', { style: tipBoxStyle }, '\uD83D\uDCA1 Viewer \uACC4\uC815\uC740 \uD558\uB8E8 3\uD68C \uBD84\uC11D \uC81C\uD55C\uC774 \uC788\uC2B5\uB2C8\uB2E4. \uC81C\uD55C \uCD08\uACFC \uC2DC \uB2E4\uC74C \uB0A0 \uC790\uC815\uC5D0 \uCD08\uAE30\uD654\uB429\uB2C8\uB2E4. \uBD84\uC11D \uD69F\uC218\uAC00 \uBD80\uC871\uD558\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C Manager \uC5ED\uD560 \uC2B9\uACA9\uC744 \uC694\uCCAD\uD558\uC138\uC694.')
                )
            );

        /* ==================== 분석 탭 사용법 ==================== */
        case 'analysis':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\uD83D\uDCCA \uBD84\uC11D \uD0ED \uC0AC\uC6A9\uBC95'),

                    React.createElement('h3', { style: h3Style }, '1\uB2E8\uACC4: \uD0A4\uC6CC\uB4DC \uC785\uB825'),
                    React.createElement('p', { style: pStyle }, '\uC0C1\uB2E8 \uAC80\uC0C9\uCC3D\uC5D0 \uBD84\uC11D\uD558\uB824\uB294 \uD0A4\uC6CC\uB4DC\uB97C \uC785\uB825\uD569\uB2C8\uB2E4. \uC608: "\uAC74\uAC15\uC74C\uB8CC", "\uB538\uAE30", "\uBB34\uC120\uC774\uC5B4\uD3F0".'),
                    React.createElement('div', { style: tipBoxStyle },
                        '\uD83D\uDCA1 \uD0A4\uC6CC\uB4DC \uC785\uB825 \uD301:\n\u2022 \uB108\uBB34 \uB113\uC740 \uD0A4\uC6CC\uB4DC(\uC608: "\uC637") \uBCF4\uB2E4 \uAD6C\uCCB4\uC801\uC778 \uD0A4\uC6CC\uB4DC(\uC608: "\uC5EC\uC131 \uACE8\uD504\uC6E8\uC5B4")\uAC00 \uB354 \uC720\uC6A9\uD569\uB2C8\uB2E4.\n\u2022 \uC0C1\uD488 URL(\uC120\uD0DD)\uC744 \uD568\uAED8 \uC785\uB825\uD558\uBA74 \uD574\uB2F9 \uC0C1\uD488\uC758 \uC21C\uC704\uC640 \uACBD\uC7C1\uC0AC \uBE44\uAD50 \uBD84\uC11D\uC774 \uCD94\uAC00\uB429\uB2C8\uB2E4.\n\u2022 \uD0A4\uC6CC\uB4DC\uB294 \uC18C\uBE44\uC790\uAC00 \uC2E4\uC81C\uB85C \uAC80\uC0C9\uD560 \uBC95\uD55C \uB2E8\uC5B4\uB85C \uC785\uB825\uD558\uC138\uC694.'
                    ),

                    React.createElement('h3', { style: h3Style }, '2\uB2E8\uACC4: \uBD84\uC11D \uACB0\uACFC \uD655\uC778'),
                    React.createElement('p', { style: pStyle }, '\uBD84\uC11D\uC740 \uC57D 5~10\uCD08 \uC18C\uC694\uB429\uB2C8\uB2E4. \uC644\uB8CC\uB418\uBA74 \uC544\uB798 11\uAC00\uC9C0 \uC139\uC158\uC774 \uC21C\uC11C\uB300\uB85C \uD45C\uC2DC\uB429\uB2C8\uB2E4:'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: Object.assign({}, thStyle, { width: 30 }) }, '#'),
                                React.createElement('th', { style: thStyle }, '\uC139\uC158'),
                                React.createElement('th', { style: thStyle }, '\uD655\uC778 \uD3EC\uC778\uD2B8'),
                                React.createElement('th', { style: thStyle }, 'AI \uD53C\uB4DC\uBC31')
                            )
                        ),
                        React.createElement('tbody', null,
                            [
                                ['1', '\uC885\uD569 \uC694\uC57D \uCE74\uB4DC', '\uAC80\uC0C9\uB7C9, \uC0C1\uD488 \uC218, \uACBD\uC7C1\uAC15\uB3C4, \uACE8\uB4E0\uD0A4\uC6CC\uB4DC \uC218', '\u2705'],
                                ['2', '\uACBD\uC7C1\uAC15\uB3C4 \uBD84\uC11D', '\uBE14\uB8E8\uC624\uC158/\uBCF4\uD1B5/\uB808\uB4DC\uC624\uC158 \uD310\uC815 \uBC0F \uACBD\uC7C1\uC9C0\uC218', '\u2705'],
                                ['3', '\uC2DC\uC7A5 \uADDC\uBAA8 \uCD94\uC815', '\uD3C9\uADE0\uAC00\uACA9, \uC608\uC0C1 \uC6D4 \uC2DC\uC7A5\uADDC\uBAA8, \uC804\uD658\uC728 \uAE30\uBC18', '\u2705'],
                                ['4', '\uD0A4\uC6CC\uB4DC \uD2B8\uB80C\uB4DC', '\uBA54\uC778 vs \uC11C\uBE0C \uD0A4\uC6CC\uB4DC \uBE44\uAD50', '\u2705'],
                                ['5', '\uACE8\uB4E0 \uD0A4\uC6CC\uB4DC', '\uAC80\uC0C9\uB7C9 100~5,000 + \uACBD\uC7C1 \uB0AE\uC74C \uCD94\uCC9C', '\u2705'],
                                ['6', '\uAD11\uACE0 \uACBD\uC7C1 \uC815\uBCF4', '\uAD11\uACE0 \uC785\uCC30 \uACBD\uC7C1\uAC15\uB3C4, PC/\uBAA8\uBC14\uC77C \uD074\uB9AD\uC218', '\u2705'],
                                ['7', '\uCE74\uD14C\uACE0\uB9AC \uBD84\uC11D', '\uC0C1\uC704 \uC0C1\uD488\uB4E4\uC758 \uCE74\uD14C\uACE0\uB9AC \uBD84\uD3EC', '\u2705'],
                                ['8', '\uC5F0\uAD00 \uD0A4\uC6CC\uB4DC \uD0DC\uADF8', '\uACE8\uB4E0\uD0A4\uC6CC\uB4DC \uD3EC\uD568 \uC5F0\uAD00 \uD0A4\uC6CC\uB4DC \uBAA9\uB85D', '\u2014'],
                                ['9', '\uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C', '\uC0C1\uC704 20\uAC1C \uC0C1\uD488\uC758 \uAC00\uACA9/\uBE0C\uB79C\uB4DC/\uCE74\uD14C\uACE0\uB9AC', '\u2705'],
                                ['10', '\uD310\uB9E4\uB7C9 \uCD94\uC815', '\uC21C\uC704\uBCC4 \uC608\uC0C1 \uD310\uB9E4\uB7C9\uACFC \uB9E4\uCD9C \uC2DC\uBBAC\uB808\uC774\uC158', '\u2705'],
                                ['11', '1\uD398\uC774\uC9C0 \uC9C4\uC785 \uC804\uB7B5', '\uC0C1\uC704 5\uC704 \uD3C9\uADE0\uAC00, \uAC00\uACA9 \uBC94\uC704, \uC804\uB7B5 \uC81C\uC548', '\u2705'],
                            ].map(function(row, i) {
                                return React.createElement('tr', { key: i },
                                    React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, row[0]),
                                    React.createElement('td', { style: tdStyle }, row[1]),
                                    React.createElement('td', { style: tdStyle }, row[2]),
                                    React.createElement('td', { style: tdCenterStyle }, row[3])
                                );
                            })
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, '3\uB2E8\uACC4: \uACB0\uACFC \uD65C\uC6A9'),
                    React.createElement('p', { style: pStyle }, '\uBD84\uC11D \uACB0\uACFC \uD558\uB2E8\uC5D0\uC11C \uB2E4\uC74C \uC791\uC5C5\uC744 \uC120\uD0DD\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4:'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uBC84\uD2BC'),
                                React.createElement('th', { style: thStyle }, '\uAE30\uB2A5'),
                                React.createElement('th', { style: thStyle }, '\uC5B8\uC81C \uC0AC\uC6A9')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC5C5\uCCB4\uC5D0 \uC800\uC7A5'),
                                React.createElement('td', { style: tdStyle }, '\uBD84\uC11D \uACB0\uACFC\uB97C \uC5C5\uCCB4\uAD00\uB9AC\uC5D0 \uB4F1\uB85D'),
                                React.createElement('td', { style: tdStyle }, '\uC9C0\uC18D\uC801\uC73C\uB85C \uCD94\uC801\uD560 \uD0A4\uC6CC\uB4DC\uC77C \uB54C')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, 'HTML \uBCF4\uACE0\uC11C'),
                                React.createElement('td', { style: tdStyle }, '\uBD84\uC11D \uACB0\uACFC\uB97C HTML \uD30C\uC77C\uB85C \uB2E4\uC6B4\uB85C\uB4DC'),
                                React.createElement('td', { style: tdStyle }, '\uACE0\uAC1D \uBBF8\uD305, \uB0B4\uBD80 \uBCF4\uACE0, \uAE30\uB85D \uBCF4\uAD00')
                            )
                        )
                    ),

                    React.createElement('div', { style: warnBoxStyle }, '\u26A0\uFE0F \uBD84\uC11D \uC2E4\uD589 \uC2DC \uBE48 \uD398\uC774\uC9C0\uAC00 \uB098\uD0C0\uB098\uBA74 Ctrl+Shift+R(\uAC15\uB825 \uC0C8\uB85C\uACE0\uCE68)\uC744 \uC2DC\uB3C4\uD574\uC8FC\uC138\uC694. \uBB38\uC81C\uAC00 \uC9C0\uC18D\uB418\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C \uBB38\uC758\uD558\uC138\uC694.')
                )
            );

        /* ==================== 데이터 해석 방법 ==================== */
        case 'data':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\uD83D\uDCC8 \uB370\uC774\uD130 \uD574\uC11D \uBC29\uBC95'),

                    React.createElement('h3', { style: h3Style }, '\uACBD\uC7C1\uC9C0\uC218 (Competition Index)'),
                    React.createElement('p', { style: pStyle }, '\uACBD\uC7C1\uC9C0\uC218 = \uB124\uC774\uBC84 \uC1FC\uD551 \uC804\uCCB4 \uC0C1\uD488 \uC218 \u00F7 \uC6D4\uAC04 \uAC80\uC0C9\uB7C9. \uC218\uC694 \uB300\uBE44 \uACF5\uAE09\uC758 \uBE44\uC728\uC744 \uB098\uD0C0\uB0C5\uB2C8\uB2E4.'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uACBD\uC7C1\uC9C0\uC218'),
                                React.createElement('th', { style: thStyle }, '\uACBD\uC7C1\uC218\uC900'),
                                React.createElement('th', { style: thStyle }, '\uC758\uBBF8'),
                                React.createElement('th', { style: thStyle }, '\uC804\uB7B5')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, '0.5 \uBBF8\uB9CC'),
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#dcfce7', '#16a34a') }, '\uBE14\uB8E8\uC624\uC158')),
                                React.createElement('td', { style: tdStyle }, '\uC218\uC694 > \uACF5\uAE09, \uC9C4\uC785 \uC720\uB9AC'),
                                React.createElement('td', { style: tdStyle }, '\uBE60\uB978 \uC9C4\uC785 \uCD94\uCC9C')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, '0.5 ~ 1.0'),
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#fef9c3', '#ca8a04') }, '\uBCF4\uD1B5')),
                                React.createElement('td', { style: tdStyle }, '\uC218\uC694 \u2248 \uACF5\uAE09, \uACBD\uC7C1 \uC801\uB2F9'),
                                React.createElement('td', { style: tdStyle }, '\uCC28\uBCC4\uD654 \uC804\uB7B5 \uD544\uC694')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, '1.0 \uC774\uC0C1'),
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#fee2e2', '#dc2626') }, '\uB808\uB4DC\uC624\uC158')),
                                React.createElement('td', { style: tdStyle }, '\uACF5\uAE09 > \uC218\uC694, \uACBD\uC7C1 \uCE58\uC5F4'),
                                React.createElement('td', { style: tdStyle }, '\uB871\uD14C\uC77C \uD0A4\uC6CC\uB4DC \uACF5\uB7B5')
                            )
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, '\uACBD\uC7C1\uC218\uC900 \uD37C\uC13C\uD2B8'),
                    React.createElement('p', { style: pStyle }, '\uACBD\uC7C1\uC9C0\uC218\uB97C 0~100% \uC2A4\uCF00\uC77C\uB85C \uBCC0\uD658\uD55C \uAC12\uC785\uB2C8\uB2E4. 30% \uC774\uD558\uBA74 \uBE14\uB8E8\uC624\uC158, 30~70%\uBA74 \uBCF4\uD1B5, 70% \uC774\uC0C1\uC774\uBA74 \uB808\uB4DC\uC624\uC158\uC73C\uB85C \uD310\uC815\uD569\uB2C8\uB2E4.'),

                    React.createElement('h3', { style: h3Style }, '\uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4'),
                    React.createElement('p', { style: pStyle }, '\uB124\uC774\uBC84 \uAC80\uC0C9\uAD11\uACE0 API\uC5D0\uC11C \uC81C\uACF5\uD558\uB294 \uAD11\uACE0 \uC785\uCC30 \uACBD\uC7C1 \uC218\uC900\uC785\uB2C8\uB2E4.'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uB4F1\uAE09'),
                                React.createElement('th', { style: thStyle }, '\uC758\uBBF8'),
                                React.createElement('th', { style: thStyle }, '\uC2DC\uC0AC\uC810')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#dcfce7', '#16a34a') }, '\uB0AE\uC74C')),
                                React.createElement('td', { style: tdStyle }, '\uAD11\uACE0 \uC785\uCC30 \uACBD\uC7C1\uC774 \uC801\uC74C'),
                                React.createElement('td', { style: tdStyle }, '\uB0AE\uC740 \uAD11\uACE0\uBE44\uB85C \uC0C1\uC704 \uB178\uCD9C \uAC00\uB2A5')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#fef9c3', '#ca8a04') }, '\uC911\uAC04')),
                                React.createElement('td', { style: tdStyle }, '\uC801\uB2F9\uD55C \uC218\uC900\uC758 \uAD11\uACE0 \uACBD\uC7C1'),
                                React.createElement('td', { style: tdStyle }, '\uD0C0\uAC9F\uD305\uACFC \uC785\uCC30 \uC804\uB7B5 \uD544\uC694')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, React.createElement('span', { style: badgeStyle('#fee2e2', '#dc2626') }, '\uB192\uC74C')),
                                React.createElement('td', { style: tdStyle }, '\uAD11\uACE0 \uC785\uCC30 \uACBD\uC7C1\uC774 \uCE58\uC5F4'),
                                React.createElement('td', { style: tdStyle }, '\uB192\uC740 \uAD11\uACE0\uBE44 \uC608\uC0C1, SEO \uBCD1\uD589 \uAD8C\uC7A5')
                            )
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, 'PC / \uBAA8\uBC14\uC77C \uD074\uB9AD\uC218'),
                    React.createElement('p', { style: pStyle }, '\uC6D4 \uD3C9\uADE0 PC \uBC0F \uBAA8\uBC14\uC77C \uD074\uB9AD\uC218\uC785\uB2C8\uB2E4. \uD074\uB9AD\uC218\uAC00 \uB192\uC744\uC218\uB85D \uAD6C\uB9E4 \uC758\uD5A5\uC774 \uB192\uC740 \uD0A4\uC6CC\uB4DC\uC785\uB2C8\uB2E4. \uBAA8\uBC14\uC77C \uD074\uB9AD\uC774 PC\uBCF4\uB2E4 5\uBC30 \uC774\uC0C1 \uB192\uC73C\uBA74 \uBAA8\uBC14\uC77C \uCD5C\uC801\uD654\uAC00 \uD2B9\uD788 \uC911\uC694\uD569\uB2C8\uB2E4.'),

                    React.createElement('h3', { style: h3Style }, '\uC2DC\uC7A5\uADDC\uBAA8'),
                    React.createElement('p', { style: pStyle }, '\uC0C1\uC704 20\uAC1C \uC0C1\uD488\uC758 \uC608\uC0C1 \uC6D4 \uB9E4\uCD9C \uD569\uACC4\uC785\uB2C8\uB2E4. \uAC80\uC0C9\uB7C9 \u00D7 \uC21C\uC704\uBCC4 CTR \u00D7 \uC804\uD658\uC728(3.5%) \u00D7 \uC0C1\uD488 \uAC00\uACA9\uC73C\uB85C \uCD94\uC815\uD569\uB2C8\uB2E4. \uC2E4\uC81C \uB9E4\uCD9C\uACFC\uB294 \uCC28\uC774\uAC00 \uC788\uC73C\uBBF4\uB85C \uC0C1\uB300\uC801 \uBE44\uAD50 \uC9C0\uD45C\uB85C \uD65C\uC6A9\uD558\uC138\uC694.'),

                    React.createElement('h3', { style: h3Style }, '\uACE8\uB4E0 \uD0A4\uC6CC\uB4DC \uD310\uC815 \uAE30\uC900'),
                    React.createElement('p', { style: pStyle }, '\uC544\uB798 \uC870\uAC74\uC744 \uBAA8\uB450 \uB9CC\uC871\uD558\uB294 \uD0A4\uC6CC\uB4DC\uAC00 \uACE8\uB4E0 \uD0A4\uC6CC\uB4DC\uB85C \uBD84\uB958\uB429\uB2C8\uB2E4:'),
                    React.createElement('div', { style: tipBoxStyle },
                        '\u2022 \uC6D4\uAC04 \uAC80\uC0C9\uB7C9 100 ~ 5,000\uD68C\n\u2022 \uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4: \uB0AE\uC74C\n\u2022 \uC2A4\uD1A0\uC5B4\uBA85\uC774 \uC544\uB2CC \uC2E4\uC81C \uC0C1\uD488 \uD0A4\uC6CC\uB4DC\n\u2022 \uC6D0\uB798 \uAC80\uC0C9 \uD0A4\uC6CC\uB4DC\uC640 \uC5F0\uAD00\uC131\uC774 \uC788\uC74C'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uB370\uC774\uD130 \uD574\uC11D \uC2DC \uC8FC\uC758\uC0AC\uD56D'),
                    React.createElement('div', { style: warnBoxStyle },
                        '\u26A0\uFE0F \uBAA8\uB4E0 \uC218\uCE58\uB294 \uCD94\uC815\uCE58\uC785\uB2C8\uB2E4. \uC808\uB300\uC801\uC778 \uC218\uCE58\uBCF4\uB2E4 \uD0A4\uC6CC\uB4DC \uAC04 \uC0C1\uB300 \uBE44\uAD50\uC5D0 \uD65C\uC6A9\uD558\uC138\uC694.\n\u26A0\uFE0F \uAC80\uC0C9\uB7C9\uACFC \uD074\uB9AD\uC218\uB294 \uC6D4\uAC04 \uD3C9\uADE0\uCE58\uC774\uBBC0\uB85C \uC2DC\uC990 \uBCC0\uB3D9\uC774 \uD06C\uB2C8 \uCC38\uACE0\uD574\uC8FC\uC138\uC694.\n\u26A0\uFE0F AI \uD53C\uB4DC\uBC31\uC740 \uCC38\uACE0\uC6A9\uC774\uBA70 \uCD5C\uC885 \uC758\uC0AC\uACB0\uC815\uC740 \uC2DC\uC7A5 \uC0C1\uD669\uACFC \uACBD\uD5D8\uC744 \uBC14\uD0D5\uC73C\uB85C \uD310\uB2E8\uD558\uC138\uC694.'
                    )
                )
            );

        /* ==================== 업체관리 사용법 ==================== */
        case 'management':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\uD83C\uDFE2 \uC5C5\uCCB4\uAD00\uB9AC \uC0AC\uC6A9\uBC95'),

                    React.createElement('h3', { style: h3Style }, '\uC5C5\uCCB4 \uB4F1\uB85D \uBC29\uBC95'),
                    React.createElement('p', { style: pStyle }, '\uC5C5\uCCB4\uB97C \uB4F1\uB85D\uD558\uB294 \uBC29\uBC95\uC740 2\uAC00\uC9C0\uC785\uB2C8\uB2E4:'),
                    React.createElement('div', { style: tipBoxStyle },
                        '\uBC29\uBC95 1\uFE0F\u20E3  \uD648 \uD0ED\uC5D0\uC11C \uC5C5\uCCB4 \uCE74\uB4DC \uD074\uB9AD \u2192 \uBD84\uC11D \uC2E4\uD589 \u2192 \uC790\uB3D9 \uC800\uC7A5\n\uBC29\uBC95 2\uFE0F\u20E3  \uBD84\uC11D \uD0ED\uC5D0\uC11C \uD0A4\uC6CC\uB4DC \uBD84\uC11D \uD6C4 \uD558\uB2E8 "\uC5C5\uCCB4\uC5D0 \uC800\uC7A5" \uD074\uB9AD'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC5C5\uCCB4 \uC0C1\uC138 \uD654\uBA74 \uAD6C\uC131'),
                    React.createElement('p', { style: pStyle }, '\uC5C5\uCCB4\uB97C \uC120\uD0DD\uD558\uBA74 \uB4F1\uB85D\uB41C \uD0A4\uC6CC\uB4DC \uBAA9\uB85D\uC774 \uD45C\uC2DC\uB429\uB2C8\uB2E4. \uD0A4\uC6CC\uB4DC\uB97C \uD074\uB9AD\uD558\uBA74 \uB450 \uAC00\uC9C0 \uBDF0\uB97C \uC804\uD658\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4:'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uBDF0'),
                                React.createElement('th', { style: thStyle }, '\uB0B4\uC6A9'),
                                React.createElement('th', { style: thStyle }, '\uD65C\uC6A9')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC77C\uC790\uBCC4 \uCD94\uC774'),
                                React.createElement('td', { style: tdStyle }, '\uB0A0\uC9DC\uBCC4 \uAC80\uC0C9\uB7C9, \uD074\uB9AD\uC218, \uACBD\uC7C1\uC9C0\uC218, \uC2DC\uC7A5\uADDC\uBAA8 \uBCC0\uD654'),
                                React.createElement('td', { style: tdStyle }, '\uC2DC\uC7A5 \uD2B8\uB80C\uB4DC \uD30C\uC545, \uACBD\uC7C1 \uBCC0\uD654 \uBAA8\uB2C8\uD130\uB9C1')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC21C\uC704 \uC774\uB825'),
                                React.createElement('td', { style: tdStyle }, '\uC0C1\uD488\uC758 \uD0A4\uC6CC\uB4DC\uBCC4 \uB124\uC774\uBC84 \uC1FC\uD551 \uC21C\uC704 \uBCC0\uD654'),
                                React.createElement('td', { style: tdStyle }, 'SEO \uD6A8\uACFC \uD655\uC778, \uC21C\uC704 \uC0C1\uC2B9/\uD558\uB77D \uCD94\uC801')
                            )
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC77C\uC790\uBCC4 \uCD94\uC774 \uD14C\uC774\uBE14 \uD56D\uBAA9 \uC124\uBA85'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uD56D\uBAA9'),
                                React.createElement('th', { style: thStyle }, '\uC124\uBA85'),
                                React.createElement('th', { style: thStyle }, '\uD65C\uC6A9 \uD3EC\uC778\uD2B8')
                            )
                        ),
                        React.createElement('tbody', null,
                            [
                                ['\uAC80\uC0C9\uB7C9', '\uD574\uB2F9 \uD0A4\uC6CC\uB4DC\uC758 \uC6D4\uAC04 PC + \uBAA8\uBC14\uC77C \uAC80\uC0C9 \uD69F\uC218', '\uAC80\uC0C9\uB7C9 \uCD94\uC774\uB85C \uC2DC\uC990 \uD310\uB2E8'],
                                ['PC \uD074\uB9AD', '\uC6D4 \uD3C9\uADE0 PC \uAD11\uACE0 \uD074\uB9AD\uC218', '\uAD11\uACE0 \uD6A8\uACFC \uD310\uB2E8'],
                                ['\uBAA8\uBC14\uC77C \uD074\uB9AD', '\uC6D4 \uD3C9\uADE0 \uBAA8\uBC14\uC77C \uAD11\uACE0 \uD074\uB9AD\uC218', '\uBAA8\uBC14\uC77C \uBE44\uC911 \uD310\uB2E8'],
                                ['\uACBD\uC7C1\uC9C0\uC218', '\uC0C1\uD488 \uC218 \u00F7 \uAC80\uC0C9\uB7C9 (\uB0AE\uC744\uC218\uB85D \uC720\uB9AC)', '\uACBD\uC7C1 \uBCC0\uD654 \uCD94\uC801'],
                                ['\uACBD\uC7C1\uC218\uC900', '\uACBD\uC7C1\uC9C0\uC218\uB97C \uBC31\uBD84\uC728\uB85C \uBCC0\uD658', '\uBE68\uAC04\uC0C9\uC774\uBA74 \uACBD\uACE0'],
                                ['\uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4', '\uB124\uC774\uBC84 \uAC80\uC0C9\uAD11\uACE0 \uC785\uCC30 \uACBD\uC7C1 \uC218\uC900', '\uAD11\uACE0\uBE44 \uC608\uCE21'],
                                ['\uC2DC\uC7A5\uADDC\uBAA8', '\uC0C1\uC704 20\uAC1C \uC0C1\uD488 \uAE30\uC900 \uC608\uC0C1 \uC6D4 \uB9E4\uCD9C \uD569\uACC4', '\uC2DC\uC7A5 \uAC00\uCE58 \uD310\uB2E8'],
                                ['\uBCF4\uACE0\uC11C', 'HTML \uD615\uC2DD\uC758 \uC0C1\uC138 \uBD84\uC11D \uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC', '\uACE0\uAC1D \uC81C\uCD9C\uC6A9'],
                            ].map(function(row, i) {
                                return React.createElement('tr', { key: i },
                                    React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600, whiteSpace: 'nowrap' }) }, row[0]),
                                    React.createElement('td', { style: tdStyle }, row[1]),
                                    React.createElement('td', { style: Object.assign({}, tdStyle, { fontSize: 12, color: '#64748b' }) }, row[2])
                                );
                            })
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC5C5\uCCB4 \uC0AD\uC81C \uC2DC \uC8FC\uC758\uC0AC\uD56D'),
                    React.createElement('div', { style: warnBoxStyle },
                        '\u26A0\uFE0F \uC5C5\uCCB4\uB97C \uC0AD\uC81C\uD558\uBA74 \uD574\uB2F9 \uC5C5\uCCB4\uC758 \uBAA8\uB4E0 \uD0A4\uC6CC\uB4DC, \uBD84\uC11D \uC774\uB825, \uC21C\uC704 \uAE30\uB85D\uC774 \uD568\uAED8 \uC601\uAD6C \uC0AD\uC81C\uB429\uB2C8\uB2E4.\n\uC0AD\uC81C \uC804 \uBC18\uB4DC\uC2DC \uD544\uC694\uD55C \uBCF4\uACE0\uC11C\uB97C \uBBF8\uB9AC \uB2E4\uC6B4\uB85C\uB4DC\uD574\uB450\uC138\uC694.\nManager \uACC4\uC815\uC740 \uBCF8\uC778\uC774 \uB4F1\uB85D\uD55C \uC5C5\uCCB4\uB9CC \uC0AD\uC81C\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC790\uB3D9 \uBD84\uC11D \uC2A4\uCF00\uC904'),
                    React.createElement('div', { style: successBoxStyle },
                        '\u23F0 \uB9E4\uC77C \uC624\uC804 07:00 \u2014 \uB4F1\uB85D\uB41C \uBAA8\uB4E0 \uC5C5\uCCB4\uC758 \uD0A4\uC6CC\uB4DC\uB97C \uC790\uB3D9 \uBD84\uC11D\uD558\uACE0 HTML \uBCF4\uACE0\uC11C\uB97C \uC0DD\uC131\uD569\uB2C8\uB2E4.\n\u23F0 \uC21C\uC704 \uCCB4\uD06C\uB294 \uC790\uB3D9 \uBD84\uC11D \uC2DC \uD568\uAED8 \uC218\uD589\uB418\uBA70, \uD558\uB8E8 1\uD68C\uB9CC \uAE30\uB85D\uB429\uB2C8\uB2E4.\n\u2705 \uC790\uB3D9 \uBD84\uC11D\uC740 AI \uD53C\uB4DC\uBC31\uC744 \uD638\uCD9C\uD558\uC9C0 \uC54A\uC544 \uCD94\uAC00 \uBE44\uC6A9\uC774 \uBC1C\uC0DD\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.'
                    )
                )
            );

        /* ==================== 순위 추적 해석 ==================== */
        case 'rank':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\uD83C\uDFC6 \uC21C\uC704 \uCD94\uC801 \uD574\uC11D'),
                    React.createElement('p', { style: pStyle }, '\uC21C\uC704 \uC774\uB825\uC740 \uC5C5\uCCB4\uAD00\uB9AC\uC5D0\uC11C \uD0A4\uC6CC\uB4DC\uB97C \uC120\uD0DD\uD55C \uD6C4 "\uC21C\uC704 \uC774\uB825" \uD0ED\uC5D0\uC11C \uD655\uC778\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'),

                    React.createElement('h3', { style: h3Style }, '\uC21C\uC704 \uB370\uC774\uD130 \uC77D\uAE30'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uD56D\uBAA9'),
                                React.createElement('th', { style: thStyle }, '\uC124\uBA85')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC21C\uC704'),
                                React.createElement('td', { style: tdStyle }, '\uB124\uC774\uBC84 \uC1FC\uD551 \uAC80\uC0C9 \uACB0\uACFC\uC5D0\uC11C\uC758 \uC704\uCE58 (1\uC704 = \uCD5C\uC0C1\uB2E8)')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uBCC0\uB3D9'),
                                React.createElement('td', { style: tdStyle }, '\uC774\uC804 \uB300\uBE44 \uC21C\uC704 \uBCC0\uD654 (\uCD08\uB85D\uC0C9 \u25B2 = \uC0C1\uC2B9, \uBE68\uAC04\uC0C9 \u25BC = \uD558\uB77D)')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC720\uD615'),
                                React.createElement('td', { style: tdStyle }, '\uC790\uB3D9 = \uC2A4\uCF00\uC904\uB7EC \uC790\uB3D9 \uCCB4\uD06C, \uC218\uB3D9 = \uC0AC\uC6A9\uC790\uAC00 \uC9C1\uC811 \uC2E4\uD589')
                            )
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC21C\uC704 \uD574\uC11D \uAC00\uC774\uB4DC'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uC21C\uC704'),
                                React.createElement('th', { style: thStyle }, '\uB178\uCD9C \uC704\uCE58'),
                                React.createElement('th', { style: thStyle }, '\uC608\uC0C1 CTR'),
                                React.createElement('th', { style: thStyle }, '\uC758\uBBF8'),
                                React.createElement('th', { style: thStyle }, '\uAD8C\uC7A5 \uC561\uC158')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, '1~5\uC704'), React.createElement('td', { style: tdStyle }, '1\uD398\uC774\uC9C0 \uC0C1\uB2E8'),
                                React.createElement('td', { style: tdStyle }, '3~8%'), React.createElement('td', { style: tdStyle }, '\uCD5C\uC6B0\uC218 \u2014 \uB192\uC740 \uD2B8\uB798\uD53D'),
                                React.createElement('td', { style: tdStyle }, '\uD604 \uC0C1\uD0DC \uC720\uC9C0, \uB9AC\uBDF0 \uAD00\uB9AC')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, '6~20\uC704'), React.createElement('td', { style: tdStyle }, '1\uD398\uC774\uC9C0'),
                                React.createElement('td', { style: tdStyle }, '0.8~1.5%'), React.createElement('td', { style: tdStyle }, '\uC591\uD638 \u2014 \uC548\uC815\uC801 \uB178\uCD9C'),
                                React.createElement('td', { style: tdStyle }, '\uC0C1\uC704 5\uC704 \uC9C4\uC785 \uC704\uD574 \uAC00\uACA9/\uC0C1\uC138\uD398\uC774\uC9C0 \uAC1C\uC120')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, '21~40\uC704'), React.createElement('td', { style: tdStyle }, '2\uD398\uC774\uC9C0'),
                                React.createElement('td', { style: tdStyle }, '0.3%'), React.createElement('td', { style: tdStyle }, '\uAC1C\uC120 \uD544\uC694'),
                                React.createElement('td', { style: tdStyle }, '\uB9AC\uBDF0/\uAC00\uACA9/\uC0C1\uD488\uBA85 \uCD5C\uC801\uD654')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: tdStyle }, '\uC21C\uC704 \uC5C6\uC74C'), React.createElement('td', { style: tdStyle }, '2\uD398\uC774\uC9C0 \uC774\uD6C4'),
                                React.createElement('td', { style: tdStyle }, '< 0.1%'), React.createElement('td', { style: tdStyle }, '\uB178\uCD9C \uBBF8\uBBF8'),
                                React.createElement('td', { style: tdStyle }, '\uC0C1\uD488\uBA85/\uCE74\uD14C\uACE0\uB9AC \uC7AC\uAC80\uD1A0, \uACE8\uB4E0\uD0A4\uC6CC\uB4DC \uACF5\uB7B5')
                            )
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC21C\uC704 \uBCC0\uB3D9 \uD328\uD134\uBCC4 \uB300\uC751'),
                    React.createElement('div', { style: tipBoxStyle },
                        '\u25B2 3\uC77C \uC5F0\uC18D \uC0C1\uC2B9: \uD604\uC7AC \uC804\uB7B5\uC774 \uD6A8\uACFC\uC801, \uD604 \uC0C1\uD0DC \uC720\uC9C0\n\u25BC 3\uC77C \uC5F0\uC18D \uD558\uB77D: \uACBD\uC7C1\uC0AC \uBD84\uC11D \uD544\uC694, \uAC00\uACA9/\uB9AC\uBDF0/\uC0C1\uC138\uD398\uC774\uC9C0 \uC810\uAC80\n\u2194 \uD070 \uB4F1\uB77D\uC774 \uBC18\uBCF5: \uD0A4\uC6CC\uB4DC \uACBD\uC7C1\uC774 \uCE58\uC5F4\uD55C \uC0C1\uD0DC, \uBCF4\uC870 \uD0A4\uC6CC\uB4DC \uBD84\uC0B0 \uD544\uC694\n\u2014 \uC21C\uC704 \uBCC0\uB3D9 \uC5C6\uC74C: \uC548\uC815\uC801\uC774\uC9C0\uB9CC \uC131\uC7A5 \uC5EC\uC9C0 \uD655\uC778 \uD544\uC694'
                    ),

                    React.createElement('div', { style: warnBoxStyle }, '\u26A0\uFE0F \uC21C\uC704\uB294 \uB124\uC774\uBC84 \uC1FC\uD551 API(\uC720\uC0AC\uB3C4\uC21C) \uAE30\uC900\uC774\uBA70, \uC2E4\uC81C \uBE0C\uB77C\uC6B0\uC800 \uAC80\uC0C9 \uACB0\uACFC(\uAD00\uB828\uB3C4\uC21C)\uC640 \uCC28\uC774\uAC00 \uC788\uC744 \uC218 \uC788\uC2B5\uB2C8\uB2E4. \uCC38\uACE0 \uC9C0\uD45C\uB85C \uD65C\uC6A9\uD574\uC8FC\uC138\uC694.')
                )
            );

        /* ==================== 보고서 활용 ==================== */
        case 'report':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\uD83D\uDCC4 \uBCF4\uACE0\uC11C \uD65C\uC6A9'),

                    React.createElement('h3', { style: h3Style }, 'HTML \uBCF4\uACE0\uC11C\uB780?'),
                    React.createElement('p', { style: pStyle }, '\uBD84\uC11D \uACB0\uACFC\uB97C \uD558\uB098\uC758 HTML \uD30C\uC77C\uB85C \uC815\uB9AC\uD55C \uBB38\uC11C\uC785\uB2C8\uB2E4. \uBE0C\uB77C\uC6B0\uC800\uC5D0\uC11C \uC5F4\uC5B4 \uBC14\uB85C \uD655\uC778\uD558\uAC70\uB098 \uC778\uC1C4(PDF \uBCC0\uD658)\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'),

                    React.createElement('h3', { style: h3Style }, '\uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC \uBC29\uBC95'),
                    React.createElement('div', { style: tipBoxStyle },
                        '\uBC29\uBC95 1\uFE0F\u20E3  \uBD84\uC11D \uD0ED \u2014 \uBD84\uC11D \uC644\uB8CC \uD6C4 \uD398\uC774\uC9C0 \uCD5C\uD558\uB2E8 "HTML \uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC" \uBC84\uD2BC\n\uBC29\uBC95 2\uFE0F\u20E3  \uC5C5\uCCB4\uAD00\uB9AC \uD0ED \u2014 \uC77C\uC790\uBCC4 \uCD94\uC774 \uD14C\uC774\uBE14\uC758 "HTML" \uBC84\uD2BC (\uB0A0\uC9DC\uBCC4 \uBCF4\uACE0\uC11C)'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uBCF4\uACE0\uC11C \uD3EC\uD568 \uB0B4\uC6A9'),
                    React.createElement('p', { style: pStyle }, '\uBCF4\uACE0\uC11C\uC5D0\uB294 \uC885\uD569 \uC694\uC57D, \uACBD\uC7C1\uAC15\uB3C4 \uBD84\uC11D, \uC2DC\uC7A5 \uADDC\uBAA8 \uCD94\uC815, \uAD11\uACE0 \uACBD\uC7C1 \uC815\uBCF4, \uACE8\uB4E0 \uD0A4\uC6CC\uB4DC, \uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C, \uD310\uB9E4\uB7C9 \uCD94\uC815, \uC9C4\uC785 \uC804\uB7B5, \uCE74\uD14C\uACE0\uB9AC \uBD84\uC11D, \uD0A4\uC6CC\uB4DC \uD0DC\uADF8, AI \uD53C\uB4DC\uBC31\uC774 \uD3EC\uD568\uB429\uB2C8\uB2E4.'),

                    React.createElement('h3', { style: h3Style }, '\uD65C\uC6A9 \uC0AC\uB840'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uC0C1\uD669'),
                                React.createElement('th', { style: thStyle }, '\uD65C\uC6A9 \uBC29\uBC95'),
                                React.createElement('th', { style: thStyle }, '\uD575\uC2EC \uC139\uC158')
                            )
                        ),
                        React.createElement('tbody', null,
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uACE0\uAC1D \uBBF8\uD305'),
                                React.createElement('td', { style: tdStyle }, '\uBCF4\uACE0\uC11C\uB97C \uC778\uC1C4\uD558\uAC70\uB098 \uD654\uBA74 \uACF5\uC720\uD558\uC5EC \uC2DC\uC7A5 \uD604\uD669 \uC124\uBA85'),
                                React.createElement('td', { style: tdStyle }, '\uC885\uD569\uC694\uC57D, \uACBD\uC7C1\uAC15\uB3C4, \uC9C4\uC785\uC804\uB7B5')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uB0B4\uBD80 \uBCF4\uACE0'),
                                React.createElement('td', { style: tdStyle }, '\uC77C\uC790\uBCC4 \uBCF4\uACE0\uC11C\uB97C \uBE44\uAD50\uD558\uC5EC \uC2DC\uC7A5 \uBCC0\uD654 \uCD94\uC774 \uBCF4\uACE0'),
                                React.createElement('td', { style: tdStyle }, '\uC2DC\uC7A5\uADDC\uBAA8, \uD2B8\uB80C\uB4DC, \uD310\uB9E4\uB7C9')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uC804\uB7B5 \uC218\uB9BD'),
                                React.createElement('td', { style: tdStyle }, '\uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C\uC640 \uC9C4\uC785 \uC804\uB7B5\uC744 \uAE30\uBC18\uC73C\uB85C \uAC00\uACA9/\uB9C8\uCF00\uD305 \uC804\uB7B5 \uC218\uB9BD'),
                                React.createElement('td', { style: tdStyle }, '\uACBD\uC7C1\uC0AC\uBE44\uAD50, AI\uD53C\uB4DC\uBC31')
                            ),
                            React.createElement('tr', null,
                                React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, '\uD0A4\uC6CC\uB4DC \uBC1C\uAD74'),
                                React.createElement('td', { style: tdStyle }, '\uACE8\uB4E0 \uD0A4\uC6CC\uB4DC \uBAA9\uB85D\uC744 \uD65C\uC6A9\uD558\uC5EC \uC0C8\uB85C\uC6B4 \uD0A4\uC6CC\uB4DC \uAD11\uACE0 \uC804\uB7B5 \uC218\uB9BD'),
                                React.createElement('td', { style: tdStyle }, '\uACE8\uB4E0\uD0A4\uC6CC\uB4DC, \uC5F0\uAD00\uD0A4\uC6CC\uB4DC')
                            )
                        )
                    ),

                    React.createElement('div', { style: tipBoxStyle }, '\uD83D\uDCA1 \uBCF4\uACE0\uC11C\uB97C PDF\uB85C \uBCC0\uD658\uD558\uB824\uBA74 \uBE0C\uB77C\uC6B0\uC800\uC5D0\uC11C HTML \uD30C\uC77C\uC744 \uC5F4\uACE0 Ctrl+P(\uC778\uC1C4) \u2192 "PDF\uB85C \uC800\uC7A5"\uC744 \uC120\uD0DD\uD558\uC138\uC694.')
                )
            );

        /* ==================== 고급 활용법 ==================== */
        case 'advanced':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\u2699\uFE0F \uACE0\uAE09 \uD65C\uC6A9\uBC95'),
                    React.createElement('p', { style: pStyle }, '\uAE30\uBCF8 \uAE30\uB2A5\uC5D0 \uC775\uC219\uD574\uC9C4 \uBD84\uC744 \uC704\uD55C \uACE0\uAE09 \uD65C\uC6A9 \uD301\uC785\uB2C8\uB2E4.'),

                    React.createElement('h3', { style: h3Style }, '\uACBD\uC7C1\uC0AC \uBE44\uAD50 \uBD84\uC11D \uD65C\uC6A9'),
                    React.createElement('p', { style: pStyle }, '\uBD84\uC11D \uC2DC \uC0C1\uD488 URL\uC744 \uD568\uAED8 \uC785\uB825\uD558\uBA74 \uD574\uB2F9 \uC0C1\uD488\uC758 \uC21C\uC704\uC640 \uACBD\uC7C1\uC0AC \uB300\uBE44 \uC704\uCE58\uB97C \uD655\uC778\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'),
                    React.createElement('div', { style: tipBoxStyle },
                        '\uD83D\uDCA1 \uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C\uC5D0\uC11C \uD655\uC778\uD560 \uAC83:\n\u2022 \uC0C1\uC704 5\uAC1C \uC0C1\uD488\uC758 \uD3C9\uADE0 \uAC00\uACA9 vs \uB0B4 \uC0C1\uD488 \uAC00\uACA9\n\u2022 \uC0C1\uC704 \uC0C1\uD488\uB4E4\uC758 \uB9AC\uBDF0 \uC218 \u2014 \uB9AC\uBDF0 50\uAC1C \uBBF8\uB9CC\uC774\uBA74 \uCD94\uACA9 \uAC00\uB2A5\n\u2022 \uBE0C\uB79C\uB4DC \uC0C1\uD488 \uBE44\uC728 \u2014 \uBE0C\uB79C\uB4DC \uBE44\uC728\uC774 \uB0AE\uC73C\uBA74 \uC18C\uADDC\uBAA8 \uC140\uB7EC\uC5D0\uAC8C \uAE30\uD68C\n\u2022 \uCE74\uD14C\uACE0\uB9AC \uBD84\uD3EC \u2014 \uC0C1\uC704 \uC0C1\uD488\uC774 \uC5B4\uB5A4 \uCE74\uD14C\uACE0\uB9AC\uC5D0 \uB4F1\uB85D\uB418\uC5B4 \uC788\uB294\uC9C0 \uD655\uC778'
                    ),

                    React.createElement('h3', { style: h3Style }, 'AI \uD53C\uB4DC\uBC31 \uC81C\uB300\uB85C \uD65C\uC6A9\uD558\uAE30'),
                    React.createElement('p', { style: pStyle }, '\uAC01 \uBD84\uC11D \uC139\uC158\uC758 AI \uD53C\uB4DC\uBC31\uC740 \uD574\uB2F9 \uB370\uC774\uD130\uB97C \uBC14\uD0D5\uC73C\uB85C \uC0DD\uC131\uB41C \uB9DE\uCDA4\uD615 \uC804\uB7B5 \uC81C\uC548\uC785\uB2C8\uB2E4.'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, 'AI \uD53C\uB4DC\uBC31 \uC704\uCE58'),
                                React.createElement('th', { style: thStyle }, '\uD65C\uC6A9 \uBC29\uBC95')
                            )
                        ),
                        React.createElement('tbody', null,
                            [
                                ['\uACBD\uC7C1\uAC15\uB3C4 \uD53C\uB4DC\uBC31', '\uC2DC\uC7A5 \uC9C4\uC785 \uC5EC\uBD80 \uD310\uB2E8\uC758 \uADFC\uAC70\uB85C \uD65C\uC6A9'],
                                ['\uC2DC\uC7A5\uADDC\uBAA8 \uD53C\uB4DC\uBC31', '\uB9E4\uCD9C \uAE30\uB300\uCE58 \uC124\uC815\uC758 \uCC38\uACE0\uC790\uB8CC'],
                                ['\uACE8\uB4E0\uD0A4\uC6CC\uB4DC \uD53C\uB4DC\uBC31', '\uAD11\uACE0 \uD0A4\uC6CC\uB4DC \uC120\uC815 \uC2DC \uC6B0\uC120\uC21C\uC704 \uCC38\uACE0'],
                                ['\uACBD\uC7C1\uC0AC\uBE44\uAD50 \uD53C\uB4DC\uBC31', '\uACE0\uAC1D \uC81C\uC548\uC11C\uC5D0 \uACBD\uC7C1 \uD604\uD669 \uC124\uBA85 \uC2DC \uD65C\uC6A9'],
                                ['\uC9C4\uC785\uC804\uB7B5 \uD53C\uB4DC\uBC31', '\uAD6C\uCCB4\uC801\uC778 \uAC00\uACA9/\uD3EC\uC9C0\uC154\uB2DD \uC804\uB7B5\uC758 \uCD9C\uBC1C\uC810'],
                            ].map(function(row, i) {
                                return React.createElement('tr', { key: i },
                                    React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, row[0]),
                                    React.createElement('td', { style: tdStyle }, row[1])
                                );
                            })
                        )
                    ),

                    React.createElement('h3', { style: h3Style }, '\uBCF5\uC218 \uD0A4\uC6CC\uB4DC \uAD50\uCC28 \uBD84\uC11D'),
                    React.createElement('p', { style: pStyle }, '\uAC19\uC740 \uC0C1\uD488\uC5D0 \uB300\uD574 \uC5EC\uB7EC \uD0A4\uC6CC\uB4DC\uB97C \uBD84\uC11D\uD558\uBA74 \uC5B4\uB5A4 \uD0A4\uC6CC\uB4DC\uAC00 \uAC00\uC7A5 \uD6A8\uACFC\uC801\uC778\uC9C0 \uBE44\uAD50\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'),
                    React.createElement('div', { style: tipBoxStyle },
                        '\uD83D\uDCA1 \uC608\uC2DC: "\uBB34\uC120\uC774\uC5B4\uD3F0" vs "\uBE14\uB8E8\uD22C\uC2A4 \uC774\uC5B4\uD3F0" vs "TWS \uC774\uC5B4\uD3F0"\n\u2192 \uAC01\uAC01 \uBD84\uC11D\uD558\uC5EC \uACBD\uC7C1\uC9C0\uC218, \uAC80\uC0C9\uB7C9, \uC2DC\uC7A5\uADDC\uBAA8\uB97C \uBE44\uAD50\uD558\uBA74\n\u2192 \uAC00\uC7A5 \uD6A8\uC728\uC801\uC778 \uD0A4\uC6CC\uB4DC\uB97C \uCC3E\uC744 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC77C\uC790\uBCC4 \uCD94\uC774\uB85C \uC2DC\uC7A5 \uBCC0\uD654 \uAC10\uC9C0'),
                    React.createElement('p', { style: pStyle }, '\uC5C5\uCCB4\uAD00\uB9AC\uC758 \uC77C\uC790\uBCC4 \uCD94\uC774 \uB370\uC774\uD130\uB97C \uC8FC\uAE30\uC801\uC73C\uB85C \uD655\uC778\uD558\uBA74 \uC2DC\uC7A5 \uBCC0\uD654\uB97C \uC870\uAE30\uC5D0 \uAC10\uC9C0\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'),
                    React.createElement('table', { style: tableStyle },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', { style: thStyle }, '\uBCC0\uD654 \uC2E0\uD638'),
                                React.createElement('th', { style: thStyle }, '\uC758\uBBF8'),
                                React.createElement('th', { style: thStyle }, '\uB300\uC751')
                            )
                        ),
                        React.createElement('tbody', null,
                            [
                                ['\uACBD\uC7C1\uC9C0\uC218 3\uC77C \uC5F0\uC18D \uC0C1\uC2B9', '\uC2E0\uADDC \uC140\uB7EC \uC9C4\uC785 \uC2E0\uD638', '\uCC28\uBCC4\uD654 \uAC15\uD654, \uAD11\uACE0 \uC804\uB7B5 \uC870\uC815'],
                                ['\uAC80\uC0C9\uB7C9 \uAE09\uC99D', '\uC2DC\uC990/\uD2B8\uB80C\uB4DC \uD0A4\uC6CC\uB4DC', '\uBE60\uB978 \uC7AC\uACE0 \uD655\uBCF4, \uAD11\uACE0 \uAC15\uD654'],
                                ['\uAD11\uACE0 \uACBD\uC7C1 "\uB0AE\uC74C\u2192\uB192\uC74C"', '\uAD11\uACE0 \uB2E8\uAC00 \uC0C1\uC2B9 \uC608\uC0C1', '\uC608\uC0B0 \uC870\uC815, SEO \uBCD1\uD589 \uAC15\uD654'],
                                ['\uC2DC\uC7A5\uADDC\uBAA8 \uAC10\uC18C', '\uC218\uC694 \uAC10\uC18C \uB610\uB294 \uAC00\uACA9 \uD558\uB77D', '\uB300\uCCB4 \uD0A4\uC6CC\uB4DC \uBC1C\uAD74, \uD3EC\uD2B8\uD3F4\uB9AC\uC624 \uB2E4\uBCC0\uD654'],
                            ].map(function(row, i) {
                                return React.createElement('tr', { key: i },
                                    React.createElement('td', { style: Object.assign({}, tdStyle, { fontWeight: 600 }) }, row[0]),
                                    React.createElement('td', { style: tdStyle }, row[1]),
                                    React.createElement('td', { style: tdStyle }, row[2])
                                );
                            })
                        )
                    )
                )
            );

        /* ==================== 실전 활용 팁 ==================== */
        case 'tips':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\uD83D\uDCA1 \uC2E4\uC804 \uD65C\uC6A9 \uD301'),

                    React.createElement('h3', { style: h3Style }, '\uC2E0\uADDC \uC0C1\uD488 \uC9C4\uC785 \uD310\uB2E8 \uCCB4\uD06C\uB9AC\uC2A4\uD2B8'),
                    React.createElement('div', { style: tipBoxStyle },
                        '1. \uD0A4\uC6CC\uB4DC \uBD84\uC11D\uC5D0\uC11C \uACBD\uC7C1\uC9C0\uC218 0.5 \uBBF8\uB9CC(\uBE14\uB8E8\uC624\uC158) \uD655\uC778\n2. \uACE8\uB4E0 \uD0A4\uC6CC\uB4DC\uAC00 3\uAC1C \uC774\uC0C1 \uC788\uB294\uC9C0 \uD655\uC778\n3. \uC2DC\uC7A5\uADDC\uBAA8\uAC00 \uCD5C\uC18C 100\uB9CC\uC6D0 \uC774\uC0C1\uC778\uC9C0 \uD655\uC778\n4. \uC0C1\uC704 5\uC704 \uD3C9\uADE0\uAC00\uACA9\uACFC \uB0B4 \uC0C1\uD488 \uAC00\uACA9 \uBE44\uAD50\n5. AI \uC9C4\uC785 \uC804\uB7B5 \uD53C\uB4DC\uBC31 \uD655\uC778\n\u2192 \uC704 \uC870\uAC74\uC744 \uBAA8\uB450 \uB9CC\uC871\uD558\uBA74 \uC9C4\uC785 \uC801\uAE30!'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uAE30\uC874 \uC0C1\uD488 \uAC1C\uC120'),
                    React.createElement('div', { style: tipBoxStyle },
                        '1. \uC5C5\uCCB4\uAD00\uB9AC\uC5D0\uC11C \uC21C\uC704 \uC774\uB825 \uCD94\uC801 \u2192 \uC21C\uC704 \uD558\uB77D \uD0A4\uC6CC\uB4DC \uC2DD\uBCC4\n2. \uD574\uB2F9 \uD0A4\uC6CC\uB4DC\uB85C \uC7AC\uBD84\uC11D \u2192 \uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C\uC5D0\uC11C \uC0C1\uC704 \uC0C1\uD488 \uD655\uC778\n3. \uC0C1\uC704 \uC0C1\uD488 \uB300\uBE44 \uAC00\uACA9/\uB9AC\uBDF0/\uC0C1\uC138\uD398\uC774\uC9C0 \uBE44\uAD50\n4. AI \uD53C\uB4DC\uBC31\uC758 \uAC1C\uC120 \uC81C\uC548 \uD655\uC778\n\u2192 \uBD80\uC871\uD55C \uBD80\uBD84\uC744 \uBCF4\uAC15\uD558\uBA74 \uC21C\uC704 \uD68C\uBCF5 \uAC00\uB2A5'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC77C\uC790\uBCC4 \uCD94\uC774 \uBAA8\uB2C8\uD130\uB9C1'),
                    React.createElement('div', { style: tipBoxStyle },
                        '\u2022 \uACBD\uC7C1\uC9C0\uC218\uAC00 3\uC77C \uC5F0\uC18D \uC0C1\uC2B9 \u2192 \uC2E0\uADDC \uC140\uB7EC \uC9C4\uC785 \uC2E0\uD638, \uCC28\uBCC4\uD654 \uAC15\uD654 \uD544\uC694\n\u2022 \uAC80\uC0C9\uB7C9\uC774 \uAE09\uC99D \u2192 \uC2DC\uC988/\uD2B8\uB80C\uB4DC \uD0A4\uC6CC\uB4DC, \uBE60\uB978 \uC7AC\uACE0 \uD655\uBCF4 \uAC80\uD1A0\n\u2022 \uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4 "\uB0AE\uC74C\u2192\uB192\uC74C" \uC804\uD658 \u2192 \uAD11\uACE0 \uB2E8\uAC00 \uC0C1\uC2B9 \uC608\uC0C1, \uC608\uC0B0 \uC870\uC815 \uD544\uC694'
                    ),

                    React.createElement('h3', { style: h3Style }, '\uC790\uC8FC \uD558\uB294 \uC2E4\uC218'),
                    React.createElement('div', { style: warnBoxStyle },
                        '\u274C \uACBD\uC7C1\uC9C0\uC218\uB9CC \uBCF4\uACE0 \uC9C4\uC785 \uACB0\uC815 \u2192 \uC2DC\uC7A5\uADDC\uBAA8\uAC00 \uB108\uBB34 \uC791\uC73C\uBA74 \uB9E4\uCD9C\uC774 \uB098\uC624\uC9C0 \uC54A\uC74C\n\u274C \uC21C\uC704\uB9CC \uCD94\uC801\uD558\uACE0 \uC7AC\uBD84\uC11D \uC548 \uD568 \u2192 \uC2DC\uC7A5 \uBCC0\uD654\uB97C \uB193\uCE60 \uC218 \uC788\uC74C\n\u274C \uD558\uB098\uC758 \uD0A4\uC6CC\uB4DC\uC5D0\uB9CC \uC758\uC874 \u2192 \uBC18\uB4DC\uC2DC \uC5F0\uAD00/\uACE8\uB4E0 \uD0A4\uC6CC\uB4DC\uB3C4 \uD568\uAED8 \uB4F1\uB85D\n\u274C \uBCF4\uACE0\uC11C\uB97C \uC800\uC7A5\uD558\uC9C0 \uC54A\uC74C \u2192 \uC77C\uC790\uBCC4 HTML \uBCF4\uACE0\uC11C\uB85C \uBCC0\uD654 \uCD94\uC774 \uAE30\uB85D \uD544\uC218\n\u274C \uAC19\uC740 \uD0A4\uC6CC\uB4DC \uBC18\uBCF5 \uBD84\uC11D \u2192 \uBE44\uC6A9\uB9CC \uBC1C\uC0DD, \uD558\uB8E8 1\uD68C\uBA74 \uCDA9\uBD84'
                    )
                )
            );

        /* ==================== 자주 묻는 질문 ==================== */
        case 'faq':
            return React.createElement('div', null,
                React.createElement('div', { style: cardStyle },
                    React.createElement('h2', { style: h2Style }, '\u2753 \uC790\uC8FC \uBB3B\uB294 \uC9C8\uBB38'),

                    [
                        { q: '\uBD84\uC11D \uACB0\uACFC\uAC00 \uC5B4\uC81C\uC640 \uAC19\uC740\uB370 \uB2E4\uC2DC \uBD84\uC11D\uD574\uC57C \uD558\uB098\uC694?', a: '\uC2DC\uC7A5 \uB370\uC774\uD130\uB294 \uC77C\uB2E8\uC704\uB85C \uBCC0\uD569\uB2C8\uB2E4. \uAC19\uC740 \uB0A0 \uBC18\uBCF5 \uBD84\uC11D\uC740 \uBE44\uC6A9\uB9CC \uBC1C\uC0DD\uD569\uB2C8\uB2E4. \uC5C5\uCCB4\uAD00\uB9AC\uC758 \uC800\uC7A5\uB41C \uB370\uC774\uD130\uB97C \uD655\uC778\uD558\uC138\uC694.' },
                        { q: '\uC0C8\uBCBD \uC790\uB3D9 \uBD84\uC11D\uACFC \uC218\uB3D9 \uBD84\uC11D\uC758 \uCC28\uC774\uB294?', a: '\uC790\uB3D9 \uBD84\uC11D\uC740 \uAE30\uBCF8 \uB370\uC774\uD130(\uAC80\uC0C9\uB7C9, \uACBD\uC7C1\uC9C0\uC218 \uB4F1)\uB9CC \uC218\uC9D1\uD558\uBA70 AI \uD53C\uB4DC\uBC31\uC744 \uD638\uCD9C\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4(= \uBB34\uB8CC). \uC218\uB3D9 \uBD84\uC11D\uC740 AI \uD53C\uB4DC\uBC31\uC774 \uD3EC\uD568\uB418\uC5B4 \uBE44\uC6A9\uC774 \uBC1C\uC0DD\uD569\uB2C8\uB2E4.' },
                        { q: 'Viewer \uACC4\uC815\uC758 \uBD84\uC11D \uC81C\uD55C\uC740 \uC5B8\uC81C \uCD08\uAE30\uD654\uB418\uB098\uC694?', a: '\uB9E4\uC77C \uC790\uC815(00:00)\uC5D0 \uCD08\uAE30\uD654\uB429\uB2C8\uB2E4. \uBD84\uC11D \uD69F\uC218\uAC00 \uBD80\uC871\uD558\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C Manager \uC5ED\uD560 \uC2B9\uACA9\uC744 \uC694\uCCAD\uD558\uC138\uC694.' },
                        { q: '\uBCF4\uACE0\uC11C\uB97C PDF\uB85C \uBC1B\uC744 \uC218 \uC788\uB098\uC694?', a: 'HTML \uBCF4\uACE0\uC11C\uB97C \uBE0C\uB77C\uC6B0\uC800\uC5D0\uC11C \uC5F4\uACE0 Ctrl+P \u2192 "PDF\uB85C \uC800\uC7A5"\uC744 \uC120\uD0DD\uD558\uBA74 PDF\uB85C \uBCC0\uD658\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.' },
                        { q: '\uC5C5\uCCB4\uB97C \uC0AD\uC81C\uD558\uBA74 \uB370\uC774\uD130\uB3C4 \uC0AC\uB77C\uC9C0\uB098\uC694?', a: '\uB124, \uC5C5\uCCB4 \uC0AD\uC81C \uC2DC \uD574\uB2F9 \uC5C5\uCCB4\uC758 \uBAA8\uB4E0 \uD0A4\uC6CC\uB4DC, \uBD84\uC11D \uC774\uB825, \uC21C\uC704 \uAE30\uB85D\uC774 \uC601\uAD6C \uC0AD\uC81C\uB429\uB2C8\uB2E4. \uC0AD\uC81C \uC804 \uBCF4\uACE0\uC11C\uB97C \uBBF8\uB9AC \uB2E4\uC6B4\uB85C\uB4DC\uD574\uB450\uC138\uC694.' },
                        { q: '\uBD84\uC11D \uC2DC \uBE48 \uD398\uC774\uC9C0\uAC00 \uB098\uC640\uC694.', a: 'Ctrl+Shift+R(\uAC15\uB825 \uC0C8\uB85C\uACE0\uCE68)\uC744 \uC2DC\uB3C4\uD574\uC8FC\uC138\uC694. \uBB38\uC81C\uAC00 \uC9C0\uC18D\uB418\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C \uBB38\uC758\uD558\uC138\uC694.' },
                        { q: 'AI \uD53C\uB4DC\uBC31\uC774 \uD56D\uC0C1 \uC815\uD655\uD55C\uAC00\uC694?', a: 'AI \uD53C\uB4DC\uBC31\uC740 \uB370\uC774\uD130 \uAE30\uBC18\uC758 \uCC38\uACE0\uC6A9 \uC81C\uC548\uC785\uB2C8\uB2E4. \uCD5C\uC885 \uD310\uB2E8\uC740 \uC2DC\uC7A5 \uC0C1\uD669\uACFC \uACBD\uD5D8\uC744 \uBC14\uD0D5\uC73C\uB85C \uD558\uC138\uC694.' },
                    ].map(function(item, i) {
                        return React.createElement('div', { key: i, style: { marginBottom: 16 } },
                            React.createElement('h4', { style: h4Style }, 'Q. ' + item.q),
                            React.createElement('p', { style: Object.assign({}, pStyle, { paddingLeft: 16, borderLeft: '3px solid #e2e8f0' }) }, 'A. ' + item.a)
                        );
                    }),

                    React.createElement('hr', { style: dividerStyle }),
                    React.createElement('div', { style: tipBoxStyle },
                        '\uD83D\uDCA1 \uC704\uC5D0 \uC5C6\uB294 \uC9C8\uBB38\uC740 \uAD00\uB9AC\uC790\uC5D0\uAC8C \uBB38\uC758\uD574\uC8FC\uC138\uC694.'
                    )
                )
            );

        default:
            return null;
        }
    };

    /* ==================== 메인 레이아웃 ==================== */
    return React.createElement('div', { className: 'container', style: { paddingTop: 24, paddingBottom: 40 } },
        /* 헤더 */
        React.createElement('div', { style: { background: 'linear-gradient(135deg, #6C5CE7, #a29bfe)', borderRadius: 16, padding: '32px 36px', marginBottom: 24, color: '#fff' } },
            React.createElement('h1', { style: { fontSize: 24, fontWeight: 700, marginBottom: 6 } }, '\uD83D\uDCD6 \uC0AC\uC6A9\uC790 \uAC00\uC774\uB4DC\uBD81'),
            React.createElement('p', { style: { fontSize: 14, opacity: 0.85 } }, '\uB85C\uC9C1 \uBD84\uC11D \uD504\uB85C\uADF8\uB7A8 \uB0B4\uBD80 \uC9C1\uC6D0\uC6A9 \uC0AC\uC6A9 \uC548\uB0B4\uC11C \u2014 \uC0AC\uC6A9 \uBC29\uBC95, \uB370\uC774\uD130 \uD574\uC11D, \uBE44\uC6A9 \uC548\uB0B4, \uD65C\uC6A9 \uD301')
        ),

        /* 좌우 레이아웃 */
        React.createElement('div', { className: 'cd-layout', style: { display: 'flex', gap: 20, alignItems: 'flex-start' } },
            /* 좌측 메뉴 */
            React.createElement('div', { className: 'cd-sidebar', style: { width: 200, minWidth: 200, background: '#fff', borderRadius: 14, padding: '12px 0', boxShadow: '0 1px 4px rgba(0,0,0,0.06)', position: 'sticky', top: 80 } },
                sections.map(function(s) {
                    var isActive = activeSection === s.id;
                    return React.createElement('button', {
                        key: s.id,
                        onClick: function() { setActiveSection(s.id); window.scrollTo({ top: 0, behavior: 'smooth' }); },
                        style: {
                            display: 'block', width: '100%', padding: '10px 18px', border: 'none', cursor: 'pointer',
                            textAlign: 'left', fontSize: 13, fontWeight: isActive ? 700 : 400,
                            background: isActive ? '#f0f0ff' : 'transparent',
                            color: isActive ? '#6C5CE7' : '#475569',
                            borderLeft: isActive ? '3px solid #6C5CE7' : '3px solid transparent',
                            transition: 'all 0.15s',
                        }
                    }, s.icon + ' ' + s.label);
                })
            ),

            /* 우측 콘텐츠 */
            React.createElement('div', { style: { flex: 1, minWidth: 0 } },
                renderContent()
            )
        )
    );
};
