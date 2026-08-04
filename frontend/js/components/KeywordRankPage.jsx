/* KeywordRankPage — 📊 키워드 순위 탭 (2026-08-04 탭 분리 1차)
 *
 * 구조(시안 v2 확정): 랜딩 = 광고주 업체 목록(업체별 롤업 KPI·검색·주의 배지,
 * 행 클릭 → 상세) / 상세 = 그 업체의 키워드 보드(순위+전일 Δ·7일 스파크라인·
 * 상태 칩·검색량·페이지). 하단에 기존 RankTrackingSection 을 그대로 마운트해
 * 상품 등록·수동 재확인·1회성 조회 등 기존 기능을 무손실 이전한다.
 * 스토어 분석 → 이 탭 이동 시 sessionStorage 'logic_rank_ctx' 로 검색 컨텍스트를
 * 넘겨받아 노출 확인(1회성 조회)이 이어진다.
 *
 * props: { currentUser, onNavigateToClient(storeName, productUrl) }
 */

/* ---------- 정적 스타일 (렌더 밖) ---------- */
var _krWrap = { maxWidth: 1200, margin: '0 auto', padding: '24px 16px 48px' };
var _krCard = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14, padding: '18px 20px', marginBottom: 16 };
var _krKpiGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10, marginBottom: 16 };
var _krKpi = { background: '#f8fafc', border: '1px solid #eef2f6', borderRadius: 12, padding: '13px 16px' };
var _krKpiK = { fontSize: 11.5, fontWeight: 700, color: '#94a3b8', letterSpacing: '.03em' };
var _krKpiV = { fontSize: 22, fontWeight: 800, letterSpacing: '-.02em', marginTop: 2, color: '#0f172a', fontVariantNumeric: 'tabular-nums' };
var _krKpiS = { fontSize: 11.5, marginTop: 1, color: '#94a3b8', fontVariantNumeric: 'tabular-nums' };
var _krTh = { textAlign: 'left', padding: '9px 12px', fontSize: 11.5, fontWeight: 700, color: '#94a3b8', letterSpacing: '.02em', borderBottom: '1px solid #e2e8f0', whiteSpace: 'nowrap' };
var _krTd = { padding: '11px 12px', fontSize: 13, color: '#334155', borderBottom: '1px solid #f1f5f9', verticalAlign: 'middle' };

function _krChip(kind) {
    var base = { display: 'inline-block', fontSize: 11.5, fontWeight: 800, borderRadius: 999, padding: '3px 10px', whiteSpace: 'nowrap' };
    if (kind === 'ok') return Object.assign({}, base, { color: '#16a34a', background: '#f0fdf4' });
    if (kind === 'warn') return Object.assign({}, base, { color: '#b45309', background: '#fffbeb' });
    return Object.assign({}, base, { color: '#64748b', background: '#f2f4f6' });
}
function _krDelta(delta) {
    var base = { display: 'inline-block', fontSize: 11.5, fontWeight: 800, borderRadius: 999, padding: '2px 8px', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' };
    if (delta > 0) return { style: Object.assign({}, base, { color: '#dc2626', background: '#fef2f2' }), label: '▲ ' + delta };
    if (delta < 0) return { style: Object.assign({}, base, { color: '#2563eb', background: '#eff6ff' }), label: '▼ ' + (-delta) };
    return { style: Object.assign({}, base, { color: '#64748b', background: '#f2f4f6' }), label: delta === 0 ? '—' : 'NEW' };
}

/* 7일 스파크라인 — 순위는 낮을수록 좋음(위쪽) */
function _krSparkline(series) {
    var pts = (series || []).filter(function(p) { return p.rank !== null && p.rank !== undefined; });
    if (pts.length < 2) return React.createElement('span', { style: { fontSize: 11, color: '#cbd5e1' } }, '—');
    var w = 84, h = 26, pad = 3;
    var ranks = pts.map(function(p) { return p.rank; });
    var mn = Math.min.apply(null, ranks), mx = Math.max.apply(null, ranks);
    var span = (mx - mn) || 1;
    var coords = pts.map(function(p, i) {
        var x = pad + (w - pad * 2) * (i / (pts.length - 1));
        var y = pad + (h - pad * 2) * ((p.rank - mn) / span); // 순위↑(숫자↓) = 위
        return x.toFixed(1) + ',' + y.toFixed(1);
    });
    var last = coords[coords.length - 1].split(',');
    var improving = ranks[ranks.length - 1] <= ranks[0];
    var color = improving ? '#16a34a' : '#dc2626';
    return React.createElement('svg', { width: w, height: h, style: { display: 'block' } },
        React.createElement('polyline', { points: coords.join(' '), fill: 'none', stroke: color, strokeWidth: 1.6, strokeLinejoin: 'round', strokeLinecap: 'round' }),
        React.createElement('circle', { cx: last[0], cy: last[1], r: 2.4, fill: color })
    );
}

window.KeywordRankPage = function KeywordRankPage(props) {
    var useState = React.useState, useEffect = React.useEffect, useCallback = React.useCallback;
    var currentUser = props.currentUser || {};
    var onNavigateToClient = props.onNavigateToClient;
    var isViewer = currentUser.role === 'viewer';

    var _ov = useState(null); var overview = _ov[0], setOverview = _ov[1];
    var _ovL = useState(true); var ovLoading = _ovL[0], setOvLoading = _ovL[1];
    var _sel = useState(null); var selected = _sel[0], setSelected = _sel[1]; // {id, name}
    var _bd = useState(null); var board = _bd[0], setBoard = _bd[1];
    var _bdL = useState(false); var bdLoading = _bdL[0], setBdLoading = _bdL[1];
    var _q = useState(''); var query = _q[0], setQuery = _q[1];
    var _flt = useState('all'); var filter = _flt[0], setFilter = _flt[1]; // all|attention|up|down

    /* 하단 RankTrackingSection 용 — 추적 상품은 이 페이지가 자체 로드 */
    var _pr = useState([]); var products = _pr[0], setProducts = _pr[1];
    var loadProducts = useCallback(function() {
        api.get('/products').then(function(res) {
            if (res && res.success) setProducts(res.data || []);
        }).catch(function() {});
    }, []);

    /* 스토어 분석 → 탭 이동 핸드오프 (1회 소비) */
    var _ctx = useState(function() {
        try {
            var raw = sessionStorage.getItem('logic_rank_ctx');
            if (raw) { sessionStorage.removeItem('logic_rank_ctx'); return JSON.parse(raw); }
        } catch (e) {}
        return null;
    });
    var rankCtx = _ctx[0];

    /* 하단 추적 상품 관리(전체 업체 도구) — 업체 목록에서만, 기본 접힘.
       스토어 분석에서 컨텍스트를 들고 넘어온 경우엔 노출 확인이 이어지도록 자동 펼침 */
    var _tk = useState(!!_ctx[0]); var trackingOpen = _tk[0], setTrackingOpen = _tk[1];

    /* 키워드별 📸 이미지 저장 — 기간 메뉴(열린 키워드)와 진행 상태 */
    var _im = useState(null); var imgMenuKw = _im[0], setImgMenuKw = _im[1];
    var _ims = useState(''); var imgSavingKw = _ims[0], setImgSavingKw = _ims[1];
    var saveRankImage = function(client, keyword, days) {
        setImgMenuKw(null);
        setImgSavingKw(keyword);
        api.get('/cd/' + client.id + '/rank-history?keyword=' + encodeURIComponent(keyword))
            .then(function(res) {
                var rows = (res && res.success && res.data) || [];
                if (!rows.length) { try { toast.warn('저장할 순위 이력이 없습니다.'); } catch (e) {} return; }
                window.exportRankHistoryImage({
                    rows: rows,
                    storeName: client.name || '업체',
                    keyword: keyword,
                    storeUrl: client.store_url || '',
                    days: days
                });
            })
            .catch(function() { try { toast.error('순위 이력을 불러오지 못했습니다.'); } catch (e) {} })
            .finally(function() { setImgSavingKw(''); });
    };

    var loadOverview = useCallback(function() {
        setOvLoading(true);
        api.get('/cd/rank-overview').then(function(res) {
            if (res && res.success) setOverview(res);
            else if (res && res.detail) toast.error(res.detail);
        }).catch(function() {
            try { toast.error('업체 순위 현황을 불러오지 못했습니다.'); } catch (e) {}
        }).finally(function() { setOvLoading(false); });
    }, []);

    useEffect(function() { loadOverview(); loadProducts(); }, [loadOverview, loadProducts]);

    var openDetail = function(c) {
        setSelected({ id: c.id, name: c.name });
        setBoard(null);
        setBdLoading(true);
        api.get('/cd/' + c.id + '/rank-board').then(function(res) {
            if (res && res.success) setBoard(res);
            else toast.error((res && res.detail) || '키워드 보드를 불러오지 못했습니다.');
        }).catch(function() {
            try { toast.error('키워드 보드를 불러오지 못했습니다.'); } catch (e) {}
        }).finally(function() { setBdLoading(false); });
        try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) {}
    };
    var backToList = function() { setSelected(null); setBoard(null); };

    /* ---------- 업체 목록 (랜딩) ---------- */
    function renderList() {
        var totals = (overview && overview.totals) || {};
        var rows = (overview && overview.data) || [];
        var q = query.trim().toLowerCase();
        var shown = rows.filter(function(c) {
            if (q && c.name.toLowerCase().indexOf(q) === -1) return false;
            if (filter === 'attention') return c.keywords > 0 && c.exposed === 0;
            if (filter === 'up') return c.up > 0;
            if (filter === 'down') return c.down > 0;
            return true;
        });
        var fchip = function(key, label) {
            var on = filter === key;
            return React.createElement('button', {
                key: key, onClick: function() { setFilter(on ? 'all' : key); },
                style: { border: '1px solid ' + (on ? '#3b82f6' : '#e2e8f0'), background: on ? '#eff6ff' : '#fff', color: on ? '#1d4ed8' : '#475569', borderRadius: 999, padding: '5px 13px', fontSize: 12, fontWeight: 700, cursor: 'pointer' }
            }, label);
        };
        return React.createElement(React.Fragment, null,
            React.createElement('div', { style: _krKpiGrid },
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, isViewer ? '영업 대상 업체' : '광고주 업체'),
                    React.createElement('div', { style: _krKpiV }, totals.clients != null ? totals.clients : '—'),
                    React.createElement('div', { style: _krKpiS }, '추적 키워드 ' + (totals.keywords != null ? totals.keywords : '—'))),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '노출 중 업체'),
                    React.createElement('div', { style: _krKpiV }, totals.exposed_clients != null ? totals.exposed_clients : '—'),
                    React.createElement('div', { style: _krKpiS }, '300위 내 키워드 보유')),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '상승 키워드'),
                    React.createElement('div', { style: Object.assign({}, _krKpiV, { color: '#dc2626' }) }, '▲ ' + (totals.up_total != null ? totals.up_total : '—')),
                    React.createElement('div', { style: _krKpiS }, '전일 대비 순위 상승')),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '하락 키워드'),
                    React.createElement('div', { style: Object.assign({}, _krKpiV, { color: '#2563eb' }) }, '▼ ' + (totals.down_total != null ? totals.down_total : '—')),
                    React.createElement('div', { style: _krKpiS }, '전일 대비 순위 하락')),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '주의 필요'),
                    React.createElement('div', { style: Object.assign({}, _krKpiV, { color: (totals.attention || 0) > 0 ? '#b45309' : '#0f172a' }) }, totals.attention != null ? totals.attention : '—'),
                    React.createElement('div', { style: _krKpiS }, '추적 중인데 노출 0'))
            ),
            React.createElement('div', { style: _krCard },
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 12 } },
                    React.createElement('input', {
                        value: query, onChange: function(e) { setQuery(e.target.value); },
                        placeholder: '🔍 업체명 검색',
                        style: { flex: '1 1 200px', maxWidth: 300, padding: '8px 13px', border: '1px solid #e2e8f0', borderRadius: 10, fontSize: 13, outline: 'none' }
                    }),
                    fchip('attention', '⚠️ 주의 필요'), fchip('up', '▲ 상승 보유'), fchip('down', '▼ 하락 보유'),
                    React.createElement('span', { style: { marginLeft: 'auto', fontSize: 12, color: '#94a3b8' } }, shown.length + '개 업체')
                ),
                ovLoading ? React.createElement('div', { style: { padding: '40px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 } }, '불러오는 중...') :
                shown.length === 0 ? React.createElement('div', { style: { padding: '40px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 } },
                    rows.length === 0 ? '등록된 업체가 없습니다. 업체관리 탭에서 업체를 등록하고 키워드 추적을 시작하세요.' : '조건에 맞는 업체가 없습니다.') :
                React.createElement('div', { style: { overflowX: 'auto' } },
                    React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
                        React.createElement('thead', null, React.createElement('tr', null,
                            React.createElement('th', { style: _krTh }, '업체'),
                            React.createElement('th', { style: _krTh }, '상태'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, '키워드'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, '노출'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, 'TOP10'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, '▲ / ▼'),
                            React.createElement('th', { style: _krTh }, '대표 키워드'),
                            React.createElement('th', { style: _krTh }, '최근 확인')
                        )),
                        React.createElement('tbody', null, shown.map(function(c) {
                            var attention = c.keywords > 0 && c.exposed === 0;
                            var chip = c.keywords === 0
                                ? React.createElement('span', { style: _krChip('mute') }, '추적 없음')
                                : attention
                                    ? React.createElement('span', { style: _krChip('warn') }, '노출 0')
                                    : React.createElement('span', { style: _krChip('ok') }, '노출 ' + c.exposed + '/' + c.keywords);
                            return React.createElement('tr', {
                                key: c.id, onClick: function() { openDetail(c); },
                                style: { cursor: 'pointer', background: attention ? '#fffbeb' : 'transparent' },
                                onMouseEnter: function(e) { e.currentTarget.style.background = '#f8fafc'; },
                                onMouseLeave: function(e) { e.currentTarget.style.background = attention ? '#fffbeb' : 'transparent'; }
                            },
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontWeight: 700, color: '#0f172a', whiteSpace: 'nowrap' }) }, c.name),
                                React.createElement('td', { style: _krTd }, chip),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }) }, c.keywords),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }) }, c.exposed),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }) }, c.top10),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }) },
                                    React.createElement('span', { style: { color: '#dc2626', fontWeight: 700 } }, '▲' + c.up),
                                    React.createElement('span', { style: { color: '#cbd5e1', margin: '0 4px' } }, '/'),
                                    React.createElement('span', { style: { color: '#2563eb', fontWeight: 700 } }, '▼' + c.down)),
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontSize: 12, color: '#64748b' }) },
                                    (c.top_keywords || []).map(function(t) { return t.keyword + ' ' + t.rank + '위'; }).join(' · ') || '—'),
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontSize: 12, color: '#94a3b8', whiteSpace: 'nowrap' }) }, c.last_checked || '—')
                            );
                        }))
                    )
                )
            )
        );
    }

    /* ---------- 업체 상세 (키워드 보드) ---------- */
    function renderDetail() {
        var kpis = (board && board.kpis) || {};
        var rows = (board && board.board) || [];
        var client = (board && board.client) || selected;
        return React.createElement(React.Fragment, null,
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14, flexWrap: 'wrap' } },
                React.createElement('button', {
                    onClick: backToList,
                    style: { border: '1px solid #e2e8f0', background: '#fff', color: '#475569', borderRadius: 10, padding: '7px 14px', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }
                }, '← 업체 목록'),
                React.createElement('h2', { style: { margin: 0, fontSize: 19, fontWeight: 800, color: '#0f172a' } }, '🏢 ' + (client.name || '')),
                client.store_url && React.createElement('a', {
                    href: client.store_url, target: '_blank', rel: 'noopener noreferrer',
                    style: { fontSize: 12, color: '#3b82f6', fontWeight: 600, textDecoration: 'none' }
                }, '스토어 열기 ↗'),
                onNavigateToClient && React.createElement('button', {
                    onClick: function() { onNavigateToClient(client.name, client.store_url || ''); },
                    style: { marginLeft: 'auto', border: '1px solid #bfdbfe', background: '#eff6ff', color: '#1d4ed8', borderRadius: 10, padding: '7px 14px', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }
                }, '📈 업체관리에서 보기')
            ),
            React.createElement('div', { style: _krKpiGrid },
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '추적 키워드'),
                    React.createElement('div', { style: _krKpiV }, kpis.keywords != null ? kpis.keywords : '—')),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '노출 중'),
                    React.createElement('div', { style: _krKpiV }, kpis.exposed != null ? kpis.exposed : '—'),
                    React.createElement('div', { style: _krKpiS }, '300위 내')),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, 'TOP 10'),
                    React.createElement('div', { style: _krKpiV }, kpis.top10 != null ? kpis.top10 : '—')),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '상승 / 하락'),
                    React.createElement('div', { style: _krKpiV },
                        React.createElement('span', { style: { color: '#dc2626' } }, '▲' + (kpis.up != null ? kpis.up : '—')),
                        React.createElement('span', { style: { color: '#cbd5e1', margin: '0 5px', fontSize: 16 } }, '/'),
                        React.createElement('span', { style: { color: '#2563eb' } }, '▼' + (kpis.down != null ? kpis.down : '—'))),
                    React.createElement('div', { style: _krKpiS }, '전일 대비'))
            ),
            React.createElement('div', { style: _krCard },
                bdLoading ? React.createElement('div', { style: { padding: '40px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 } }, '불러오는 중...') :
                rows.length === 0 ? React.createElement('div', { style: { padding: '40px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 } },
                    '최근 8일 순위 기록이 없습니다. 아래 「상품 순위 추적」에서 상품·키워드를 등록하면 매일 아침 자동 기록됩니다.') :
                React.createElement('div', { style: { overflowX: 'auto' } },
                    React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
                        React.createElement('thead', null, React.createElement('tr', null,
                            React.createElement('th', { style: _krTh }, '키워드'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, '현재 순위'),
                            React.createElement('th', { style: _krTh }, '전일 대비'),
                            React.createElement('th', { style: _krTh }, '최근 7일'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, '월 검색량'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, '페이지'),
                            React.createElement('th', { style: _krTh }, '확인 시각'),
                            React.createElement('th', { style: _krTh }, '이미지')
                        )),
                        React.createElement('tbody', null, rows.map(function(b) {
                            var d = _krDelta(b.delta === null || b.delta === undefined ? (b.prev_rank == null && b.rank != null ? undefined : 0) : b.delta);
                            var exposed = b.rank !== null && b.rank !== undefined;
                            return React.createElement('tr', { key: b.keyword },
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontWeight: 700, color: '#0f172a' }) }, b.keyword),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right' }) },
                                    exposed
                                        ? React.createElement('span', { style: { fontSize: 16, fontWeight: 800, color: b.rank <= 10 ? '#16a34a' : '#0f172a', fontVariantNumeric: 'tabular-nums' } }, b.rank + '위')
                                        : React.createElement('span', { style: _krChip('mute') }, '미노출')),
                                React.createElement('td', { style: _krTd },
                                    exposed && (b.delta !== null && b.delta !== undefined)
                                        ? React.createElement('span', { style: d.style }, d.label)
                                        : React.createElement('span', { style: { fontSize: 11.5, color: '#cbd5e1' } }, '—')),
                                React.createElement('td', { style: _krTd }, _krSparkline(b.series)),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }) }, b.volume || '—'),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }) }, exposed && b.page ? b.page + 'p' : '—'),
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontSize: 12, color: '#94a3b8', whiteSpace: 'nowrap' }) },
                                    b.last_checked ? String(b.last_checked).slice(0, 16).replace('T', ' ') : '—'),
                                React.createElement('td', { style: Object.assign({}, _krTd, { whiteSpace: 'nowrap', position: 'relative' }) },
                                    React.createElement('button', {
                                        disabled: imgSavingKw === b.keyword,
                                        onClick: function(e) { e.stopPropagation(); setImgMenuKw(imgMenuKw === b.keyword ? null : b.keyword); },
                                        title: '순위 이력 이미지(PNG) 저장 — 광고주 보고용',
                                        style: { fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 14, cursor: 'pointer', border: '1px solid #16a34a', background: '#f0fdf4', color: '#16a34a' }
                                    }, imgSavingKw === b.keyword ? '저장 중...' : '📸 이미지 저장 ▾'),
                                    imgMenuKw === b.keyword && React.createElement('div', {
                                        style: { position: 'absolute', top: '100%', right: 8, zIndex: 30, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, boxShadow: '0 8px 20px rgba(15,23,42,.12)', padding: 4, display: 'flex', flexDirection: 'column', minWidth: 110 }
                                    }, [[7, '최근 7일'], [30, '최근 30일'], [0, '전체(90일)']].map(function(opt) {
                                        return React.createElement('button', {
                                            key: opt[0],
                                            onClick: function(e) { e.stopPropagation(); saveRankImage(client, b.keyword, opt[0]); },
                                            style: { border: 'none', background: 'transparent', textAlign: 'left', padding: '7px 12px', fontSize: 12.5, fontWeight: 600, color: '#334155', cursor: 'pointer', borderRadius: 7 },
                                            onMouseEnter: function(e) { e.currentTarget.style.background = '#f1f5f9'; },
                                            onMouseLeave: function(e) { e.currentTarget.style.background = 'transparent'; }
                                        }, opt[1]);
                                    })))
                            );
                        }))
                    )
                )
            )
        );
    }

    return React.createElement('div', { style: _krWrap },
        React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 16, flexWrap: 'wrap' } },
            React.createElement('h1', { style: { margin: 0, fontSize: 21, fontWeight: 800, color: '#0f172a', letterSpacing: '-.02em' } }, '📊 키워드 순위'),
            React.createElement('span', { style: { fontSize: 12.5, color: '#94a3b8' } },
                selected ? '업체 상세 — 키워드별 추적 현황' : (isViewer ? '내 영업 대상 업체별 순위 추적 현황' : '광고주 업체별 순위 추적 현황') + ' · 매일 아침 자동 기록')),
        selected ? renderDetail() : renderList(),

        /* ---------- 추적 상품 관리(전체 업체 도구) — 업체 목록에서만, 기본 접힘 ----------
           업체 상세는 그 업체 데이터만 보이도록 여기서 제외한다(운영자 지시 2026-08-04). */
        !selected && React.createElement('div', { style: { marginTop: 28 } },
            React.createElement('button', {
                onClick: function() { setTrackingOpen(!trackingOpen); },
                style: { width: '100%', textAlign: 'left', border: '1px solid #e2e8f0', background: '#fff', color: '#334155', borderRadius: 12, padding: '13px 18px', fontSize: 13.5, fontWeight: 700, cursor: 'pointer' }
            },
                (trackingOpen ? '▴ ' : '▾ ') + '🛠 추적 상품 관리 — 상품·키워드 등록/삭제 · 수동 재확인 · 노출 분석 (전체 업체)',
                !trackingOpen && React.createElement('span', { style: { fontSize: 12, fontWeight: 500, color: '#94a3b8', marginLeft: 8 } }, '펼쳐서 관리')
            ),
            trackingOpen && React.createElement('div', { style: { marginTop: 12 } },
                React.createElement(window.SectionErrorBoundary, { name: '순위 추적' },
                    React.createElement(window.RankTrackingSection, {
                        products: products,
                        refreshProducts: loadProducts,
                        searchedKeyword: (rankCtx && rankCtx.searchedKeyword) || '',
                        searchedProductUrl: (rankCtx && rankCtx.searchedProductUrl) || '',
                        cachedProductName: (rankCtx && rankCtx.cachedProductName) || '',
                        relatedKeywords: (rankCtx && rankCtx.relatedKeywords) || null,
                        onNavigateToClient: onNavigateToClient,
                        canEdit: currentUser.role !== 'viewer',
                        onRankResult: null
                    })
                )
            )
        )
    );
};
