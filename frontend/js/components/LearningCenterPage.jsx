/* LearningCenterPage — 학습센터 (v1.0)
 * 업체관리(광고주)의 데이터를 기반으로, 각 광고주별 AI 자기학습 인사이트
 * (가격최적화·키워드발굴·리뷰감성·광고효율·등록타이밍·성과패턴·경쟁사이상·순위예측)를
 * 한 곳에서 운영/조회한다. 인사이트 렌더링은 공용 컴포넌트 AiInsightsView를 재사용.
 */
window.LearningCenterPage = function LearningCenterPage({ currentUser }) {
    const { useState, useEffect, useCallback } = React;

    const [clients, setClients] = useState([]);
    const [loading, setLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedClient, setSelectedClient] = useState(null);
    const [aiInsights, setAiInsights] = useState(null);
    const [aiLoading, setAiLoading] = useState(false);
    const [aiSelectedKeyword, setAiSelectedKeyword] = useState(null);

    /* 광고주(업체) 목록 로드 — 업체관리와 동일한 소스 */
    var loadClients = useCallback(function() {
        setLoading(true);
        api.get('/cd/my-clients').then(function(res) {
            if (res.success) setClients(res.data || []);
            setLoading(false);
        }).catch(function() { setLoading(false); });
    }, []);

    useEffect(function() { loadClients(); }, [loadClients]);

    /* 광고주 선택 → AI 자기학습 인사이트 로드 (업체관리 AI 인사이트 탭과 동일 엔드포인트) */
    var selectClient = function(client) {
        setSelectedClient(client);
        setAiInsights(null);
        setAiSelectedKeyword(null);
        setAiLoading(true);
        api.get('/cd/' + client.id + '/ai-insights').then(function(res) {
            if (res.success) {
                var data = res.data || res;
                setAiInsights(data);
                var kwInsights = data.keywordInsights;
                if (kwInsights) {
                    var firstKw = Object.keys(kwInsights)[0];
                    if (firstKw) setAiSelectedKeyword(firstKw);
                }
            }
            setAiLoading(false);
        }).catch(function() { setAiLoading(false); });
    };

    var filteredClients = clients.filter(function(c) {
        if (!searchQuery.trim()) return true;
        var q = searchQuery.trim().toLowerCase();
        return (c.name || '').toLowerCase().indexOf(q) !== -1
            || (c.main_keywords || '').toLowerCase().indexOf(q) !== -1
            || (c.business_name || '').toLowerCase().indexOf(q) !== -1;
    });

    /* ==================== 광고주 사이드바 아이템 ==================== */
    var renderClientItem = function(c) {
        var isActive = selectedClient && selectedClient.id === c.id;
        return React.createElement('button', {
            key: c.id,
            onClick: function() { selectClient(c); window.scrollTo({ top: 0, behavior: 'smooth' }); },
            style: {
                display: 'block', width: '100%', padding: '11px 16px', border: 'none', cursor: 'pointer',
                textAlign: 'left', background: isActive ? '#f0f0ff' : 'transparent',
                borderLeft: isActive ? '3px solid #7C3AED' : '3px solid transparent',
                transition: 'all 0.15s',
            }
        },
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 } },
                React.createElement('span', { style: { fontSize: 13, fontWeight: isActive ? 700 : 500, color: isActive ? '#6d28d9' : '#334155', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, c.name || c.business_name),
                (currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin') && c.manager_name)
                    ? React.createElement('span', { style: { flexShrink: 0, fontSize: 10, fontWeight: 600, padding: '1px 7px', borderRadius: 8, background: '#ede9fe', color: '#6d28d9' } }, c.manager_name)
                    : null
            ),
            c.main_keywords && React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, c.main_keywords)
        );
    };

    /* ==================== 우측 콘텐츠 ==================== */
    var renderRight = function() {
        if (!selectedClient) {
            return React.createElement('div', { className: 'card', style: { padding: 48, textAlign: 'center', color: '#94a3b8' } },
                React.createElement('div', { style: { fontSize: 34, marginBottom: 12 } }, '🎓'),
                React.createElement('div', { style: { fontSize: 15, fontWeight: 600, color: '#64748b' } }, '좌측에서 광고주를 선택하세요'),
                React.createElement('div', { style: { fontSize: 13, marginTop: 8, lineHeight: 1.7 } }, '선택한 광고주의 누적 분석 데이터를 바탕으로 AI가 학습한 인사이트(성과 패턴·경쟁사 감지·가격/광고/순위 예측 등)를 보여줍니다.')
            );
        }
        return React.createElement('div', null,
            /* 선택된 광고주 헤더 */
            React.createElement('div', { className: 'card', style: { padding: '16px 20px', marginBottom: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 } },
                React.createElement('div', null,
                    React.createElement('div', { style: { fontSize: 17, fontWeight: 700, color: '#1e293b' } }, selectedClient.name),
                    selectedClient.main_keywords && React.createElement('div', { style: { fontSize: 12, color: '#94a3b8', marginTop: 3 } }, '주요 키워드: ' + selectedClient.main_keywords)
                ),
                selectedClient.naver_store_url && React.createElement('a', { href: selectedClient.naver_store_url, target: '_blank', rel: 'noopener noreferrer', style: { fontSize: 12, color: '#7C3AED', textDecoration: 'none', fontWeight: 600 } }, '스토어 바로가기 →')
            ),
            /* 공용 AI 인사이트 렌더러 */
            React.createElement(window.AiInsightsView, {
                aiLoading: aiLoading,
                aiInsights: aiInsights,
                aiSelectedKeyword: aiSelectedKeyword,
                setAiSelectedKeyword: setAiSelectedKeyword
            })
        );
    };

    return React.createElement('div', { className: 'container', style: { paddingTop: 24, paddingBottom: 40 } },
        /* 헤더 */
        React.createElement('div', { style: { background: 'linear-gradient(135deg, #7C3AED, #a78bfa)', borderRadius: 16, padding: '28px 32px', marginBottom: 24, color: '#fff' } },
            React.createElement('h1', { style: { fontSize: 24, fontWeight: 700, marginBottom: 6 } }, '🎓 학습센터'),
            React.createElement('p', { style: { fontSize: 14, opacity: 0.92, lineHeight: 1.6 } }, '광고주(업체)별 누적 분석 데이터를 기반으로 AI가 자기학습한 인사이트를 한 곳에서 운영합니다. 광고주를 선택하면 성과 패턴, 경쟁사 이상 감지, 가격·광고·등록 타이밍, 순위 예측을 확인할 수 있습니다.')
        ),

        /* 좌우 레이아웃 */
        React.createElement('div', { className: 'cd-layout', style: { display: 'flex', gap: 20, alignItems: 'flex-start' } },
            /* 좌측: 광고주 목록 */
            React.createElement('div', { className: 'cd-sidebar', style: { width: 260, minWidth: 260, background: '#fff', borderRadius: 14, boxShadow: '0 1px 4px rgba(0,0,0,0.06)', position: 'sticky', top: 80, overflow: 'hidden' } },
                React.createElement('div', { style: { padding: '14px 14px 10px' } },
                    React.createElement('div', { style: { fontSize: 13, fontWeight: 700, color: '#334155', marginBottom: 10 } }, '광고주 목록' + (clients.length ? ' (' + clients.length + ')' : '')),
                    React.createElement('input', {
                        className: 'form-input', value: searchQuery,
                        onChange: function(e) { setSearchQuery(e.target.value); },
                        placeholder: '광고주·키워드 검색',
                        style: { width: '100%', fontSize: 13, padding: '7px 10px' }
                    })
                ),
                React.createElement('div', { style: { maxHeight: '70vh', overflowY: 'auto', borderTop: '1px solid #f1f5f9' } },
                    loading ? React.createElement('div', { style: { padding: 24, textAlign: 'center', fontSize: 13, color: '#94a3b8' } }, '불러오는 중...')
                    : filteredClients.length === 0 ? React.createElement('div', { style: { padding: 24, textAlign: 'center', fontSize: 13, color: '#94a3b8' } }, clients.length === 0 ? '등록된 광고주가 없습니다.' : '검색 결과가 없습니다.')
                    : filteredClients.map(renderClientItem)
                )
            ),

            /* 우측: 인사이트 */
            React.createElement('div', { style: { flex: 1, minWidth: 0 } }, renderRight())
        )
    );
};
