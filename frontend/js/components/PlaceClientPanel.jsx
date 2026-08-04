/* PlaceClientPanel — 로직 분석(업체관리) 탭 안 플레이스 업체 상세 (통합 뷰, 2026-08-05)
 *
 * 운영자 지시: 「로직 분석」 탭에서 스토어·플레이스 구분 없이 업체를 검색해
 * 분석 자료를 한 곳에서 확인. 플레이스 업체(clients.vertical='place')를 선택하면
 * 스토어 분석 스키마(client_analyses) 대신 플레이스 축(place_rank_history)을 읽는다.
 * 기존 플레이스 조회 API(/api/place/keywords·rank-history)와 PlaceRankChart 재사용 —
 * 플레이스 분석·추적 코드는 손대지 않는 읽기 전용 소비.
 *
 * business_key: 업체 저장 시 product_url 이 map.naver.com/p/entry/place/{id} 형식
 * → 'doc:{id}'. id 가 없으면(구 저장분) 안내만 표시.
 *
 * props: { client }  — clients 행 (vertical='place')
 */
window.PlaceClientPanel = function PlaceClientPanel(props) {
    var useState = React.useState, useEffect = React.useEffect;
    var client = props.client || {};

    /* 지도 URL → business_key */
    var bk = (function() {
        try {
            var m = String(client.naver_store_url || '').match(/entry\/place\/(\d+)/);
            return m ? ('doc:' + m[1]) : '';
        } catch (e) { return ''; }
    })();

    var _k = useState(null); var kws = _k[0], setKws = _k[1];           // [{keyword,rank,state,checked_at}]
    var _sel = useState(''); var selKw = _sel[0], setSelKw = _sel[1];
    var _sr = useState([]); var series = _sr[0], setSeries = _sr[1];
    var _d = useState(30); var days = _d[0], setDays = _d[1];

    useEffect(function() {
        setKws(null); setSelKw(''); setSeries([]);
        if (!bk) { setKws([]); return; }
        api.get('/place/keywords?business=' + encodeURIComponent(bk)).then(function(res) {
            var list = (res && res.success && res.data && res.data.keywords) || [];
            setKws(list);
            if (list.length) setSelKw(list[0].keyword);
        }).catch(function() { setKws([]); });
    }, [bk, client.id]);

    useEffect(function() {
        if (!bk || !selKw) { setSeries([]); return; }
        api.get('/place/rank-history?business=' + encodeURIComponent(bk) +
                '&keyword=' + encodeURIComponent(selKw) + '&days=' + days)
            .then(function(res) {
                setSeries((res && res.success && res.data && res.data.series) || []);
            }).catch(function() { setSeries([]); });
    }, [bk, selKw, days]);

    var goPlaceTab = function(hash) {
        try { window.location.hash = hash; } catch (e) {}
    };

    var chipColor = function(k) {
        if (k.rank != null) return { color: '#16a34a', background: '#f0fdf4', border: '1px solid #bbf7d0' };
        if ((k.state || '') === '미확인') return { color: '#64748b', background: '#f1f5f9', border: '1px solid #e2e8f0' };
        return { color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a' };
    };

    var exposed = (kws || []).filter(function(k) { return k.rank != null; });
    var best = exposed.length ? exposed.slice().sort(function(a, b) { return a.rank - b.rank; })[0] : null;

    return React.createElement('div', null,
        /* KPI */
        kws && kws.length > 0 && React.createElement('div', { style: { display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 } },
            [['추적 키워드', kws.length, ''], ['노출 중', exposed.length, ''],
             ['최고 순위', best ? best.rank + '위' : '—', best ? best.keyword : '']].map(function(t, i) {
                return React.createElement('div', { key: i, style: { background: '#f8fafc', border: '1px solid #eef2f6', borderRadius: 12, padding: '11px 16px', flex: '1 1 130px' } },
                    React.createElement('div', { style: { fontSize: 11, fontWeight: 700, color: '#94a3b8' } }, t[0]),
                    React.createElement('div', { style: { fontSize: 20, fontWeight: 800, color: '#0f172a' } }, t[1]),
                    t[2] && React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, t[2]));
            })),

        /* 키워드 칩 */
        React.createElement('div', { className: 'card', style: { padding: 16, marginBottom: 16 } },
            React.createElement('div', { style: { fontSize: 15, fontWeight: 600, marginBottom: 12 } },
                '📍 플레이스 분석 키워드' + (kws && kws.length ? ' (' + kws.length + '개)' : '')),
            kws === null && React.createElement('div', { style: { color: '#94a3b8', fontSize: 13 } }, '불러오는 중...'),
            kws && kws.length === 0 && React.createElement('div', { style: { color: '#94a3b8', fontSize: 13, lineHeight: 1.7 } },
                bk
                    ? '아직 이 업체의 플레이스 분석 기록이 없습니다. 「📍 플레이스 분석」 탭에서 분석하면 순위가 하루 1점씩 여기에 쌓입니다.'
                    : '이 업체는 플레이스 식별자(지도 링크) 없이 저장돼 순위 이력을 연결할 수 없습니다. 「📍 플레이스 분석」 탭에서 재분석 후 업체 저장을 다시 하면 자동 연결됩니다.'),
            kws && kws.length > 0 && React.createElement('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
                kws.map(function(k, i) {
                    var on = selKw === k.keyword;
                    var base = { padding: '8px 14px', borderRadius: 20, cursor: 'pointer', fontSize: 13, fontWeight: 600, fontFamily: 'inherit' };
                    var st = on
                        ? Object.assign(base, { background: '#1B2A4A', color: '#fff', border: '1px solid #1B2A4A' })
                        : Object.assign(base, chipColor(k));
                    return React.createElement('button', { key: i, onClick: function() { setSelKw(k.keyword); }, style: st },
                        k.keyword,
                        React.createElement('span', { style: { fontSize: 11, opacity: .85, marginLeft: 6, fontWeight: 800 } },
                            k.rank != null ? k.rank + '위' : (k.state || '미노출')));
                }))),

        /* 순위 추이 차트 (기존 PlaceRankChart 재사용 — 기간 토글·📸 이미지 저장 포함) */
        selKw && React.createElement('div', { className: 'card', style: { padding: 16, marginBottom: 16 } },
            React.createElement(window.PlaceRankChart, {
                series: series, keyword: selKw, days: days,
                onDays: function(d) { setDays(d); },
                businessName: client.name || '플레이스 업체',
                placeUrl: client.naver_store_url || ''
            })),

        /* 이동 링크 — 분석·추적 실행처 안내 */
        React.createElement('div', { style: { display: 'flex', gap: 10, flexWrap: 'wrap', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 12, padding: '12px 16px', alignItems: 'center' } },
            React.createElement('span', { style: { fontSize: 13, color: '#1d4ed8', fontWeight: 700 } }, '📍 플레이스 업체'),
            React.createElement('span', { style: { fontSize: 12.5, color: '#475569', flex: 1, minWidth: 200 } },
                '새 분석은 「플레이스 분석」 탭에서, 무인 순위 추적 등록은 「플레이스 추적」 탭에서 합니다. 결과는 이 화면에 모입니다.'),
            React.createElement('button', { onClick: function() { goPlaceTab('place'); }, style: { border: '1px solid #3b82f6', background: '#fff', color: '#1d4ed8', borderRadius: 9, padding: '7px 13px', fontSize: 12.5, fontWeight: 800, cursor: 'pointer' } }, '📍 플레이스 분석 →'),
            React.createElement('button', { onClick: function() { goPlaceTab('placetrack'); }, style: { border: '1px solid #3b82f6', background: '#fff', color: '#1d4ed8', borderRadius: 9, padding: '7px 13px', fontSize: 12.5, fontWeight: 800, cursor: 'pointer' } }, '📊 플레이스 추적 →'))
    );
};
