/* ClientListSection — 메인 분석 페이지 업체 리스트 (v3.7)
 * 등록된 업체 카드를 가나다순으로 표시하고, 클릭 시 자동 분석 실행
 */
window.ClientListSection = function ClientListSection({ onClientClick }) {
    var useState = React.useState;
    var useEffect = React.useEffect;
    var useCallback = React.useCallback;

    var _s1 = useState([]); var clients = _s1[0]; var setClients = _s1[1];
    var _s2 = useState(true); var loading = _s2[0]; var setLoading = _s2[1];
    var _s3 = useState(''); var query = _s3[0]; var setQuery = _s3[1];

    /* 업체 목록 로드 */
    var loadClients = useCallback(function() {
        setLoading(true);
        api.get('/cd/my-clients').then(function(res) {
            if (res.success) setClients(res.data || []);
            setLoading(false);
        }).catch(function() { setLoading(false); });
    }, []);

    useEffect(function() { loadClients(); }, [loadClients]);

    /* 업체에서 대표 키워드/상품URL 추출 */
    var getClientAnalysisParams = function(client) {
        // 1순위: 최근 분석한 키워드 + URL
        if (client.analyzed_keywords && client.analyzed_keywords.length > 0) {
            var latest = client.analyzed_keywords[0]; // 서버에서 analyzed_date DESC 정렬
            return {
                keyword: latest.keyword,
                productUrl: latest.product_url || '',
                companyName: client.name,
                clientId: client.id,
                lastDate: latest.analyzed_date || ''
            };
        }
        // 2순위: main_keywords에서 첫 키워드
        if (client.main_keywords) {
            var firstKw = String(client.main_keywords).split(',')[0].trim();
            if (firstKw) {
                return {
                    keyword: firstKw,
                    productUrl: client.naver_store_url || '',
                    companyName: client.name,
                    clientId: client.id,
                    lastDate: ''
                };
            }
        }
        return null;
    };

    /* 대표 키워드 텍스트 */
    var getRepresentativeKeyword = function(client) {
        if (client.analyzed_keywords && client.analyzed_keywords.length > 0) {
            return client.analyzed_keywords[0].keyword;
        }
        if (client.main_keywords) {
            return String(client.main_keywords).split(',')[0].trim();
        }
        return '-';
    };

    /* 마지막 분석 일자 텍스트 */
    var getLastAnalyzedText = function(client) {
        if (client.analyzed_keywords && client.analyzed_keywords.length > 0) {
            var d = client.analyzed_keywords[0].analyzed_date;
            return d || '-';
        }
        return '미분석';
    };

    /* 검색 + 가나다 정렬 */
    var filtered = clients
        .filter(function(c) {
            if (!query.trim()) return true;
            var q = query.trim().toLowerCase();
            return (c.name || '').toLowerCase().indexOf(q) !== -1
                || (c.main_keywords || '').toLowerCase().indexOf(q) !== -1;
        })
        .slice()
        .sort(function(a, b) {
            return (a.name || '').localeCompare(b.name || '', 'ko');
        });

    /* 카드 클릭 핸들러 */
    var handleCardClick = function(client) {
        var params = getClientAnalysisParams(client);
        if (!params) {
            alert('이 업체는 분석에 사용할 키워드 정보가 없습니다.\n\n업체관리에서 대표 키워드를 등록하거나 먼저 수동 분석을 한 번 진행해주세요.');
            return;
        }
        if (onClientClick) onClientClick(params);
    };

    /* ==================== 렌더링 ==================== */
    return React.createElement('div', { className: 'section', style: { paddingTop: 24, paddingBottom: 24 } },
        React.createElement('div', { className: 'container' },
            /* 헤더 */
            React.createElement('div', {
                style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 12 }
            },
                React.createElement('div', null,
                    React.createElement('h2', {
                        style: { fontSize: 20, fontWeight: 700, color: '#1e293b', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }
                    }, '🏢 등록 업체 바로 분석', clients.length > 0 && React.createElement('span', { style: { fontSize: 14, fontWeight: 500, color: '#6366f1', marginLeft: 4 } }, '(' + clients.length + '개)')),
                    React.createElement('p', {
                        style: { fontSize: 13, color: '#64748b', margin: '4px 0 0 0' }
                    }, '업체 카드를 클릭하면 마지막 분석 정보로 즉시 재분석됩니다.')
                ),
                React.createElement('input', {
                    type: 'text',
                    placeholder: '업체명/키워드 검색...',
                    value: query,
                    onChange: function(e) { setQuery(e.target.value); },
                    style: {
                        padding: '8px 14px',
                        fontSize: 13,
                        border: '1px solid #e2e8f0',
                        borderRadius: 8,
                        minWidth: 240,
                        outline: 'none'
                    }
                })
            ),

            /* 로딩 */
            loading && React.createElement('div', {
                style: { textAlign: 'center', padding: '40px 20px', color: '#64748b', fontSize: 14 }
            }, '업체 목록 불러오는 중...'),

            /* 빈 상태 */
            !loading && filtered.length === 0 && clients.length === 0 && React.createElement('div', {
                style: {
                    textAlign: 'center',
                    padding: '40px 20px',
                    background: '#f8fafc',
                    borderRadius: 12,
                    border: '1px dashed #cbd5e1'
                }
            },
                React.createElement('div', { style: { fontSize: 40, marginBottom: 8 } }, '📋'),
                React.createElement('div', { style: { fontSize: 14, color: '#475569', fontWeight: 600, marginBottom: 4 } },
                    '등록된 업체가 없습니다'
                ),
                React.createElement('div', { style: { fontSize: 12, color: '#94a3b8' } },
                    '상단에서 직접 키워드를 입력해 분석하거나, 업체관리 탭에서 업체를 먼저 등록해주세요.'
                )
            ),

            /* 검색 결과 없음 */
            !loading && filtered.length === 0 && clients.length > 0 && React.createElement('div', {
                style: { textAlign: 'center', padding: '30px 20px', color: '#94a3b8', fontSize: 13 }
            }, '검색 결과가 없습니다.'),

            /* 업체 카드 그리드 */
            !loading && filtered.length > 0 && React.createElement('div', {
                style: {
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                    gap: 14
                }
            },
                filtered.map(function(client) {
                    var repKeyword = getRepresentativeKeyword(client);
                    var lastDate = getLastAnalyzedText(client);
                    var analyzeCount = (client.analyzed_keywords || []).length;

                    return React.createElement('div', {
                        key: client.id,
                        onClick: function() { handleCardClick(client); },
                        style: {
                            background: '#fff',
                            border: '1px solid #e2e8f0',
                            borderRadius: 12,
                            padding: '16px 18px',
                            cursor: 'pointer',
                            transition: 'all 0.15s ease',
                            boxShadow: '0 1px 2px rgba(0,0,0,0.04)'
                        },
                        onMouseEnter: function(e) {
                            e.currentTarget.style.borderColor = '#6c5ce7';
                            e.currentTarget.style.boxShadow = '0 4px 12px rgba(108,92,231,0.15)';
                            e.currentTarget.style.transform = 'translateY(-2px)';
                        },
                        onMouseLeave: function(e) {
                            e.currentTarget.style.borderColor = '#e2e8f0';
                            e.currentTarget.style.boxShadow = '0 1px 2px rgba(0,0,0,0.04)';
                            e.currentTarget.style.transform = 'translateY(0)';
                        }
                    },
                        /* 업체명 */
                        React.createElement('div', {
                            style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }
                        },
                            React.createElement('div', {
                                style: { fontSize: 15, fontWeight: 700, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }
                            }, client.name || '(이름 없음)'),
                            analyzeCount > 0 && React.createElement('span', {
                                style: {
                                    fontSize: 10,
                                    fontWeight: 600,
                                    color: '#6c5ce7',
                                    background: '#ede9fe',
                                    padding: '2px 8px',
                                    borderRadius: 999,
                                    marginLeft: 8,
                                    whiteSpace: 'nowrap'
                                }
                            }, analyzeCount + '건')
                        ),

                        /* 대표 키워드 */
                        React.createElement('div', {
                            style: { fontSize: 12, color: '#64748b', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }
                        },
                            React.createElement('span', { style: { color: '#94a3b8' } }, '🔑'),
                            React.createElement('span', {
                                style: { fontWeight: 600, color: '#475569', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
                            }, repKeyword)
                        ),

                        /* 마지막 분석 */
                        React.createElement('div', {
                            style: { fontSize: 11, color: '#94a3b8', display: 'flex', alignItems: 'center', gap: 6 }
                        },
                            React.createElement('span', null, '📅'),
                            React.createElement('span', null, '마지막 분석: ' + lastDate)
                        ),

                        /* 클릭 안내 */
                        React.createElement('div', {
                            style: {
                                marginTop: 10,
                                paddingTop: 10,
                                borderTop: '1px dashed #e2e8f0',
                                fontSize: 11,
                                color: '#6c5ce7',
                                fontWeight: 600,
                                textAlign: 'right'
                            }
                        }, '클릭하여 분석 →')
                    );
                })
            )
        )
    );
};
