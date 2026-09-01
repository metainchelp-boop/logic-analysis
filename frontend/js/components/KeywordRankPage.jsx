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
/* 페이지 폭·정렬 = 앱 표준(styles.css `.container` = max-width 1920 · margin 0 · 좌우 24px).
   ⚠️ `margin:'0 auto'`(가운데 고정)로 되돌리지 말 것 — 스토어 분석(.container)·보고서(.report-shell)가
   전부 왼쪽 정렬 전체 폭이라 이 화면만 가운데면 넓은 모니터에서 혼자 좁은 칸이 된다(2026-08-11 대표 지적).
   지도 순위 추적(PlaceTrackingPage)도 이 상수를 그대로 쓰므로 여기만 고치면 두 화면이 함께 맞는다. */
var _krWrap = { maxWidth: 1920, margin: 0, padding: '24px 24px 48px' };
var _krCard = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14, padding: '18px 20px', marginBottom: 16 };
var _krKpiGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10, marginBottom: 16 };
var _krKpi = { background: '#f8fafc', border: '1px solid #eef2f6', borderRadius: 12, padding: '13px 16px' };
var _krKpiK = { fontSize: 11.5, fontWeight: 700, color: '#94a3b8', letterSpacing: '.03em' };
var _krKpiV = { fontSize: 22, fontWeight: 800, letterSpacing: '-.02em', marginTop: 2, color: '#0f172a', fontVariantNumeric: 'tabular-nums' };
var _krKpiS = { fontSize: 11.5, marginTop: 1, color: '#94a3b8', fontVariantNumeric: 'tabular-nums' };
var _krTh = { textAlign: 'left', padding: '9px 12px', fontSize: 11.5, fontWeight: 700, color: '#94a3b8', letterSpacing: '.02em', borderBottom: '1px solid #e2e8f0', whiteSpace: 'nowrap' };
/* ＋ 추적 상품 등록 카드 (2026-08-28 대표 확정) — 제목 바로 아래 항상 펼쳐 둔다.
   ⚠️ 접이식으로 되돌리지 말 것. 종전엔 페이지 맨 아래 접힌 「추적 상품 관리」 안에 있어
      스크롤 → 펼치기 → 버튼, 세 단계를 거쳐야 입력칸이 나왔다(대표 지적). */
var _krRegBox = { border: '1.5px solid #3b82f6', background: '#eff6ff', borderRadius: 12, padding: '15px 16px', marginBottom: 18 };
var _krRegRow = { display: 'grid', gridTemplateColumns: 'minmax(150px,1fr) minmax(220px,1.6fr) minmax(160px,1.3fr) auto', gap: 9, alignItems: 'end' };
var _krRegLbl = { display: 'block', fontSize: 11.5, color: '#334155', fontWeight: 700, marginBottom: 4 };
var _krRegInp = { width: '100%', border: '1px solid #cbd5e1', borderRadius: 8, padding: '8px 10px', fontSize: 12.5, fontFamily: 'inherit', background: '#fff', color: '#0f172a' };
var _krTd = { padding: '11px 12px', fontSize: 13, color: '#334155', borderBottom: '1px solid #f1f5f9', verticalAlign: 'middle' };

function _krChip(kind) {
    var base = { display: 'inline-block', fontSize: 11.5, fontWeight: 800, borderRadius: 999, padding: '3px 10px', whiteSpace: 'nowrap' };
    if (kind === 'ok') return Object.assign({}, base, { color: '#16a34a', background: '#f0fdf4' });
    if (kind === 'warn') return Object.assign({}, base, { color: '#b45309', background: '#fffbeb' });
    if (kind === 'info') return Object.assign({}, base, { color: '#1d4ed8', background: '#eff6ff' });
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
    var _bs = useState('rank'); var boardSort = _bs[0], setBoardSort = _bs[1];   // rank|delta|volume|name (2차 확산)
    var _bd2 = useState(7); var boardDays = _bd2[0], setBoardDays = _bd2[1];     // 추이 기간 7|30
    var _kwi = useState(''); var kwInput = _kwi[0], setKwInput = _kwi[1];       // 추적 키워드 추가 입력
    // 키워드별 상품 지정 (2026-08-21 이예은 신고) — 업체당 상품 하나 전제 해소
    var _kpE = useState(null); var kpEdit = _kpE[0], setKpEdit = _kpE[1];        // 편집 중 키워드
    var _kpV = useState(''); var kpVal = _kpV[0], setKpVal = _kpV[1];
    var _kpB = useState(false); var kpBusy = _kpB[0], setKpBusy = _kpB[1];
    var _kwb = useState(false); var kwBusy = _kwb[0], setKwBusy = _kwb[1];
    var _kwm = useState(null); var kwMsg = _kwm[0], setKwMsg = _kwm[1];          // {ok, text}
    var selectedRef = React.useRef(null);   // 늦은 응답 가드용 — 현재 보고 있는 업체

    /* 하단 RankTrackingSection 용 — 추적 상품은 이 페이지가 자체 로드 */
    var _pr = useState([]); var products = _pr[0], setProducts = _pr[1];
    var loadProducts = useCallback(function() {
        api.get('/products').then(function(res) {
            if (res && res.success) setProducts(res.data || []);
        }).catch(function() {});
    }, []);

    /* 화면 통합(2026-08-29 대표 확정) — 업체에 이어진 상품 id 목록.
       하단 「전체 도구」는 미연결 상품만 보여준다: 이어진 상품은 업체 상세가 이미
       보여주므로 두 곳에 나오면 같은 것을 두 번 관리하게 된다(이번 통합의 이유). */
    var _lk = useState(null); var linkedIds = _lk[0], setLinkedIds = _lk[1];   // null=아직 모름
    useEffect(function() {
        api.get('/cd/rank-links').then(function(res) {
            if (res && res.success) setLinkedIds(res.linked_product_ids || []);
        }).catch(function() {});   // 실패 시 null 유지 → 종전대로 전부 노출(조용한 소실 방지)
    }, []);
    var unlinkedProducts = React.useMemo(function() {
        if (!linkedIds) return products;
        var s = {}; linkedIds.forEach(function(i) { s[i] = 1; });
        return products.filter(function(p) { return !s[p.id]; });
    }, [products, linkedIds]);
    var linkedHiddenCount = linkedIds ? (products.length - unlinkedProducts.length) : 0;

    /* ＋ 추적 상품 등록 (상단 고정 카드) — 2026-08-28
       ⚠️ 업체는 **필수**다. 목록에서 고른 것만 저장한다 — 손으로 친 글자를 그대로 받으면
          오타·유사 상호가 들어가 지금과 똑같이 주인을 못 찾는다(대표 확정). */
    var _rgQ = useState(''); var regQuery = _rgQ[0], setRegQuery = _rgQ[1];      // 업체 검색어
    var _rgO = useState([]); var regOpts = _rgO[0], setRegOpts = _rgO[1];        // 검색 결과
    var _rgC = useState(null); var regClient = _rgC[0], setRegClient = _rgC[1];  // 고른 업체 {id,name}
    var _rgU = useState(''); var regUrl = _rgU[0], setRegUrl = _rgU[1];
    var _rgK = useState(''); var regKw = _rgK[0], setRegKw = _rgK[1];
    var _rgB = useState(false); var regBusy = _rgB[0], setRegBusy = _rgB[1];
    var _rgM = useState(null); var regMsg = _rgM[0], setRegMsg = _rgM[1];        // {ok, text}

    /* 업체 검색 — 이미 있는 피커 경로를 그대로 쓴다(신규 서버 작업 0).
       입력이 멈추고 250ms 뒤 한 번만 부른다(글자마다 부르면 서버를 두드린다). */
    React.useEffect(function() {
        var q = (regQuery || '').trim();
        if (regClient || !q) { setRegOpts([]); return; }
        var t = setTimeout(function() {
            api.get('/cd/clients-lookup?q=' + encodeURIComponent(q))
               .then(function(res) { setRegOpts((res && res.success && res.data) ? res.data : []); })
               .catch(function() { setRegOpts([]); });
        }, 250);
        return function() { clearTimeout(t); };
    }, [regQuery, regClient]);

    var regReady = !!(regClient && regUrl.trim() && regKw.trim()) && !regBusy;
    var submitRegister = function() {
        if (!regReady) return;
        setRegBusy(true); setRegMsg(null);
        var kws = regKw.split(',').map(function(k) { return k.trim(); }).filter(Boolean);
        api.post('/products/track', {
            product_url: regUrl.trim(),
            keywords: kws,
            client_id: regClient.id
        }).then(function(res) {
            if (res && res.success === false) throw new Error(res.detail || '등록 실패');
            setRegUrl(''); setRegKw('');
            /* ⚠️ 「등록됨」과 「업체에 이어짐」은 다른 일이다. 서버는 등록을 성립시키고
               연결 결과를 link 로 따로 돌려준다 — 이어지지 않았으면 그렇게 말해야 한다.
               성공했다고만 알리면 주인 없는 상품이 또 조용히 생긴다. */
            var lk = (res && res.data && res.data.link) || null;
            setRegMsg(lk && lk.linked === false
                ? { ok: false, text: '상품은 등록됐지만 「' + regClient.name + '」에 잇지 못했습니다'
                                     + (lk.reason ? ' — ' + lk.reason : '') + '. 아래 「추적 상품 관리」에서 확인해 주세요.' }
                : { ok: true, text: '「' + regClient.name + '」에 등록했습니다 · 키워드 ' + kws.length + '개 · 첫 순위는 잠시 뒤 표시됩니다' });
            loadProducts();
        }).catch(function(e) {
            setRegMsg({ ok: false, text: '등록하지 못했습니다 — ' + ((e && e.message) || '네트워크 오류') });
        }).then(function() { setRegBusy(false); });
    };

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

    /* 키워드 펼침 패널 — 순위 추이 차트(이미지 저장과 동일 데이터) + 기간 선택 + 📸 저장 */
    var _ex = useState(null); var expandedKw = _ex[0], setExpandedKw = _ex[1];
    var _kd = useState({}); var kwDays = _kd[0], setKwDays = _kd[1];           // { keyword: 7|30|0 }
    var _hc = useState({}); var histCache = _hc[0], setHistCache = _hc[1];    // { keyword: rows(90일) }
    var loadKwHistory = function(client, keyword) {
        if (histCache[keyword]) return;
        api.get('/cd/' + client.id + '/rank-history?keyword=' + encodeURIComponent(keyword) + '&days=90')
            .then(function(res) {
                var rows = (res && res.success && res.data) || [];
                setHistCache(function(prev) { var n = Object.assign({}, prev); n[keyword] = rows; return n; });
            })
            .catch(function() {
                setHistCache(function(prev) { var n = Object.assign({}, prev); n[keyword] = []; return n; });
                try { toast.error('순위 이력을 불러오지 못했습니다.'); } catch (e) {}
            });
    };
    var toggleKw = function(client, keyword) {
        if (expandedKw === keyword) { setExpandedKw(null); return; }
        setExpandedKw(keyword);
        loadKwHistory(client, keyword);
    };
    var _kwPeriodLabel = { 7: '최근 7일', 30: '최근 30일', 0: '전체(90일)' };
    var _kwFilterRows = function(rows, days) {
        if (!days) return rows;
        var cutoff = new Date(); cutoff.setDate(cutoff.getDate() - days);
        return rows.filter(function(r) { return new Date((r.checked_at || '').replace(' ', 'T')) >= cutoff; });
    };

    function renderKwPanel(client, b) {
        var days = kwDays[b.keyword] != null ? kwDays[b.keyword] : 7;   // 기본 = 최근 7일
        var all = histCache[b.keyword];
        var rows = all ? _kwFilterRows(all, days) : null;
        var setPeriod = function(d) {
            setKwDays(function(prev) { var n = Object.assign({}, prev); n[b.keyword] = d; return n; });
        };
        var header = React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 } },
            [7, 30, 0].map(function(d) {
                var on = days === d;
                return React.createElement('button', {
                    key: d, onClick: function(e) { e.stopPropagation(); setPeriod(d); },
                    style: { fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 14, cursor: 'pointer',
                             border: '1px solid ' + (on ? '#3b82f6' : '#e2e8f0'), background: on ? '#3b82f6' : '#fff', color: on ? '#fff' : '#475569' }
                }, _kwPeriodLabel[d]);
            }),
            React.createElement('button', {
                onClick: function(e) {
                    e.stopPropagation();
                    window.exportRankHistoryImage({
                        rows: all || [],
                        storeName: client.name || '업체',
                        keyword: b.keyword,
                        storeUrl: client.store_url || '',
                        days: days
                    });
                },
                style: { marginLeft: 'auto', fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 14, cursor: 'pointer', border: '1px solid #16a34a', background: '#f0fdf4', color: '#16a34a' }
            }, '📸 이미지 저장')
        );
        var bodyEl;
        if (!rows) {
            bodyEl = React.createElement('div', { style: { padding: 8, textAlign: 'center', fontSize: 12, color: '#94a3b8' } }, '순위 이력 불러오는 중...');
        } else if (rows.length < 2) {
            bodyEl = React.createElement('div', { style: { padding: 8, textAlign: 'center', fontSize: 12, color: '#94a3b8' } },
                _kwPeriodLabel[days] + ' 추이는 2회 이상의 순위 기록이 필요합니다. (현재 ' + rows.length + '회)');
        } else {
            var labels = rows.map(function(r) {
                var d = new Date((r.checked_at || '').replace(' ', 'T'));
                return isNaN(d) ? '' : (d.getMonth() + 1) + '/' + d.getDate();
            });
            var data = rows.map(function(r) { return (r.rank_position && r.rank_position > 0) ? r.rank_position : null; });
            var valid = data.filter(function(v) { return v != null; });
            var maxRank = valid.length ? Math.max.apply(null, valid) : 40;
            bodyEl = React.createElement(React.Fragment, null,
                React.createElement('div', { style: { fontSize: 12, fontWeight: 700, color: '#0f172a', marginBottom: 8 } },
                    '"' + b.keyword + '" ' + _kwPeriodLabel[days] + ' 순위 추이'),
                React.createElement(window.ChartCanvas, {
                    canvasId: 'cdrank-' + client.id + '-' + encodeURIComponent(b.keyword),
                    type: 'line',
                    height: 180,
                    data: {
                        labels: labels,
                        datasets: [{
                            label: '순위', data: data,
                            borderColor: '#16a34a', backgroundColor: 'rgba(22,163,74,.12)',
                            fill: true, tension: 0.35, pointRadius: 2.5, borderWidth: 2.5, spanGaps: true
                        }]
                    },
                    options: {
                        plugins: {
                            legend: { display: false },
                            tooltip: { callbacks: { label: function(ctx) { return ctx.parsed.y != null ? ctx.parsed.y + '위' : '300위 밖'; } } }
                        },
                        scales: {
                            y: { reverse: true, suggestedMin: 1, suggestedMax: Math.max(16, maxRank + 2), title: { display: true, text: '순위 (낮을수록 상위 ↑)' }, ticks: { precision: 0 } }
                        }
                    }
                })
            );
        }
        /* 이 키워드로 추적할 상품 — 업체당 상품이 하나뿐이던 것을 키워드마다 지정 가능하게
           (2026-08-21 이예은 신고). 지정이 없으면 업체 대표 상품을 쓴다. */
        var editing = kpEdit === b.keyword;
        var pUrl = b.product_url || '';
        var prodRow = React.createElement('div', {
            style: { display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
                     padding: '9px 11px', marginBottom: 11, borderRadius: 9,
                     background: b.product_assigned ? '#eff6ff' : '#fff',
                     border: '1px solid ' + (b.product_assigned ? '#bfdbfe' : '#e2e8f0') }
        },
            React.createElement('span', { style: { fontSize: 11.5, fontWeight: 800, color: '#475569', whiteSpace: 'nowrap' } },
                '🛒 이 키워드로 추적할 상품'),
            editing
                ? React.createElement(React.Fragment, null,
                    React.createElement('input', {
                        value: kpVal, disabled: kpBusy, autoFocus: true,
                        onChange: function(e) { setKpVal(e.target.value); },
                        placeholder: 'https://smartstore.naver.com/…/products/000000',
                        style: { flex: '1 1 320px', minWidth: 200, border: '1px solid #cbd5e1', borderRadius: 7,
                                 padding: '5px 9px', fontSize: 12 }
                    }),
                    React.createElement('button', {
                        onClick: function() { saveKeywordProduct(client.id, b.keyword, kpVal.trim()); },
                        disabled: kpBusy,
                        style: { border: 'none', background: kpBusy ? '#93c5fd' : '#3b82f6', color: '#fff',
                                 borderRadius: 7, padding: '5px 13px', fontSize: 12, fontWeight: 700,
                                 cursor: kpBusy ? 'default' : 'pointer' }
                    }, kpBusy ? '저장 중…' : '저장'),
                    React.createElement('button', {
                        onClick: function() { setKpEdit(null); setKpVal(''); }, disabled: kpBusy,
                        style: { border: '1px solid #e2e8f0', background: '#fff', color: '#64748b',
                                 borderRadius: 7, padding: '5px 11px', fontSize: 12, cursor: 'pointer' }
                    }, '취소'),
                    b.product_assigned && React.createElement('button', {
                        onClick: function() { saveKeywordProduct(client.id, b.keyword, ''); }, disabled: kpBusy,
                        title: '지정을 해제하면 업체 대표 상품으로 되돌아갑니다',
                        style: { border: '1px solid #fecaca', background: '#fef2f2', color: '#b91c1c',
                                 borderRadius: 7, padding: '5px 11px', fontSize: 12, cursor: 'pointer' }
                    }, '지정 해제'))
                : React.createElement(React.Fragment, null,
                    React.createElement('span', { style: { flex: '1 1 260px', minWidth: 160, fontSize: 11.5,
                                                           color: pUrl ? '#334155' : '#94a3b8',
                                                           wordBreak: 'break-all' } },
                        pUrl || '상품 주소가 없습니다',
                        !b.product_assigned && pUrl && React.createElement('span', {
                            style: { marginLeft: 6, fontSize: 10.5, color: '#94a3b8' }
                        }, '(업체 대표 상품)')),
                    React.createElement('button', {
                        onClick: function() { setKpEdit(b.keyword); setKpVal(b.product_assigned ? pUrl : ''); },
                        style: { border: '1px solid #cbd5e1', background: '#fff', color: '#334155',
                                 borderRadius: 7, padding: '4px 11px', fontSize: 11.5, fontWeight: 700, cursor: 'pointer' }
                    }, b.product_assigned ? '변경' : '이 키워드만 다른 상품으로')),
            React.createElement('div', { style: { flexBasis: '100%', fontSize: 11, color: '#94a3b8' } },
                '지정하면 내일 아침 자동 분석부터 그 상품으로 순위를 잽니다. 지정이 없으면 업체 대표 상품을 씁니다.')
        );

        return React.createElement('tr', { key: b.keyword + '::panel' },
            React.createElement('td', { colSpan: 8, style: { padding: '14px 18px 10px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0' } },
                prodRow, header, bodyEl));
    }

    /* ── 「추적 안 됨」 정리함 (신고 #248 후속 · 2026-09-01 대표 확정) ──
       진입은 이 화면의 배너 하나뿐. 파괴 동작은 전부 「내리기」 계열(하드 삭제 없음).
       빨간 배너는 stuck(계약 끝난 업체의 상품)만 센다 — 내려간 상품은 문제가 아니라
       보관 상태라, stuck 이 0이면 회색 한 줄로만 남는다. */
    var _tr = useState(null); var tray = _tr[0], setTray = _tr[1];
    var _tro = useState(false); var trayOpen = _tro[0], setTrayOpen = _tro[1];
    var _trt = useState('stuck'); var trayTab = _trt[0], setTrayTab = _trt[1];
    var _trb = useState(0); var trayBusy = _trb[0], setTrayBusy = _trb[1];   // 처리 중인 상품 id
    var _trl = useState(null); var linkFor = _trl[0], setLinkFor = _trl[1]; // 연결 입력이 열린 상품 id
    var _trq = useState(''); var linkQ = _trq[0], setLinkQ = _trq[1];
    var _trOpt = useState([]); var linkOpts = _trOpt[0], setLinkOpts = _trOpt[1];

    var loadTray = useCallback(function() {
        if (isViewer) return;                       // 영업사원 화면에는 광고주 상품 정리함이 없다
        api.get('/products/blocked').then(function(res) {
            if (res && res.success) setTray(res);
        }).catch(function() {});
    }, [isViewer]);

    React.useEffect(function() {
        var q = (linkQ || '').trim();
        if (!linkFor || !q) { setLinkOpts([]); return; }
        var t = setTimeout(function() {
            api.get('/cd/clients-lookup?q=' + encodeURIComponent(q))
               .then(function(res) { setLinkOpts((res && res.success && res.data) ? res.data : []); })
               .catch(function() { setLinkOpts([]); });
        }, 250);
        return function() { clearTimeout(t); };
    }, [linkQ, linkFor]);

    var trayAct = function(pid, path, body, okMsg) {
        setTrayBusy(pid);
        api.post('/products/' + pid + path, body || {}).then(function(res) {
            if (res && res.success === false) throw new Error(res.detail || '실패');
            try { toast.success((res && res.message) || okMsg); } catch (e) {}
            setLinkFor(null); setLinkQ('');
            loadTray(); loadProducts();
        }).catch(function(e) {
            try { toast.error((e && e.message) || '처리하지 못했습니다'); } catch (x) {}
        }).finally(function() { setTrayBusy(0); });
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

    useEffect(function() { loadOverview(); loadProducts(); loadTray(); }, [loadOverview, loadProducts, loadTray]);

    var loadBoard = function(id, days) {
        setBoard(null);
        setBdLoading(true);
        api.get('/cd/' + id + '/rank-board?days=' + (days || boardDays)).then(function(res) {
            if (res && res.success) setBoard(res);
            else toast.error((res && res.detail) || '키워드 보드를 불러오지 못했습니다.');
        }).catch(function() {
            try { toast.error('키워드 보드를 불러오지 못했습니다.'); } catch (e) {}
        }).finally(function() { setBdLoading(false); });
    };
    var submitKeyword = function() {
        var kw = kwInput.trim();
        if (!kw || kwBusy || !selected) return;
        var cid = selected.id;   // 요청 시점 업체 고정
        setKwBusy(true); setKwMsg(null);
        var stillHere = function() { return selectedRef.current && selectedRef.current.id === cid; };
        api.post('/cd/' + cid + '/track-keyword', { keyword: kw }).then(function(res) {
            // 업체를 이동한 뒤 도착한 늦은 응답이 다른 업체의 보드·메시지를 덮지 않게 가드
            if (!stillHere()) return;
            if (res && res.success) {
                setKwMsg({ ok: true, text: res.already ? '「' + kw + '」 — 이미 추적 중인 키워드입니다.' : '「' + kw + '」 ' + (res.message || '등록되었습니다.') });
                if (!res.already) { setKwInput(''); loadBoard(cid, boardDays); }
            } else {
                setKwMsg({ ok: false, text: (res && res.detail) || '등록하지 못했습니다.' });
            }
        }).catch(function(err) {
            if (!stillHere()) return;
            setKwMsg({ ok: false, text: (err && err.message) || '등록하지 못했습니다.' });
        }).finally(function() { setKwBusy(false); });
    };
    /* 그만 재기(양방향) — 지우지 않고 억제한다. 업체·이어진 상품 양쪽에서 함께 빠지고,
       순위 기록은 보존돼 같은 키워드를 다시 등록하면 이전 기록 그대로 복귀한다. */
    var untrackKeyword = function(client, b) {
        if (kwBusy) return;
        if (!confirm('「' + b.keyword + '」 그만 재기\n\n'
                + '· 이 업체와 이어진 추적 상품 양쪽에서 함께 빠집니다.\n'
                + '· 순위 기록은 보존됩니다 — 같은 키워드를 다시 등록하면 이전 기록 그대로 복귀합니다.')) return;
        var cid = client.id;
        setKwBusy(true);
        api.post('/cd/' + cid + '/untrack-keyword', { keyword: b.keyword }).then(function(res) {
            if (res && res.success) {
                try { toast.success('「' + b.keyword + '」 ' + (res.message || '그만 잽니다.')); } catch (e) {}
                loadBoard(cid, boardDays); loadProducts();
            } else {
                try { toast.error((res && res.detail) || '처리하지 못했습니다.'); } catch (e) {}
            }
        }).catch(function(err) {
            try { toast.error((err && err.message) || '처리하지 못했습니다.'); } catch (e) {}
        }).finally(function() { setKwBusy(false); });
    };

    /* 업체 상세의 추적 상품 관리 — 하단 전체 도구와 같은 서버 경로를 그대로 쓴다 */
    var _dpB = useState(false); var prodBusy = _dpB[0], setProdBusy = _dpB[1];
    var deleteDetailProduct = function(client, p) {
        if (prodBusy) return;
        if (!confirm('「' + (p.name || '이 상품') + '」 추적 상품을 삭제할까요?\n\n'
                + '· 이 상품의 키워드 등록과 순위 이력이 함께 삭제됩니다.\n'
                + '· 업체 쪽 순위 기록(로직 분석 화면)은 그대로 남습니다.')) return;
        setProdBusy(true);
        api.del('/products/' + p.id).then(function() {
            try { toast.success('상품 추적을 삭제했습니다.'); } catch (e) {}
            loadBoard(client.id, boardDays); loadProducts();
        }).catch(function(err) {
            try { toast.error('삭제 실패: ' + ((err && err.message) || '네트워크 오류')); } catch (e) {}
        }).finally(function() { setProdBusy(false); });
    };
    var refreshDetailProduct = function(client, p) {
        if (prodBusy) return;
        setProdBusy(true);
        api.post('/rank/refresh/' + p.id).then(function() {
            try { toast.success('「' + (p.name || '상품') + '」 순위 재확인을 시작했습니다 — 잠시 뒤 새로고침해 확인하세요.'); } catch (e) {}
        }).catch(function(err) {
            try { toast.error('재확인 실패: ' + ((err && err.message) || '네트워크 오류')); } catch (e) {}
        }).finally(function() { setProdBusy(false); });
    };

    var saveKeywordProduct = function(cid, kw, url) {
        if (kpBusy) return;
        setKpBusy(true);
        api.put('/cd/' + cid + '/keyword-product', { keyword: kw, product_url: url }).then(function(res) {
            if (res && res.success) {
                try { toast.success(res.message || '저장되었습니다.'); } catch (e) {}
                setKpEdit(null); setKpVal('');
                loadBoard(cid, boardDays);
            } else {
                try { toast.error((res && res.detail) || '저장하지 못했습니다.'); } catch (e) {}
            }
        }).catch(function(err) {
            try { toast.error((err && err.message) || '저장하지 못했습니다.'); } catch (e) {}
        }).finally(function() { setKpBusy(false); });
    };

    var openDetail = function(c) {
        selectedRef.current = { id: c.id, name: c.name };
        setSelected({ id: c.id, name: c.name });
        setKwInput(''); setKwMsg(null);
        loadBoard(c.id, boardDays);
        try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) {}
    };
    var changeBoardDays = function(d) {
        if (d === boardDays) return;
        setBoardDays(d);
        if (selected) loadBoard(selected.id, d);
    };
    var backToList = function() { selectedRef.current = null; setSelected(null); setBoard(null); setKwInput(''); setKwMsg(null); };

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
        /* 2차 확산: 정렬 — 서버 기본(노출 순위순) 위에 클라이언트 재정렬 */
        var _volNum = function(v) { var n = parseInt(String(v || '').replace(/[^0-9]/g, ''), 10); return isNaN(n) ? -1 : n; };
        rows = rows.slice().sort(function(a, b) {
            if (boardSort === 'delta') return Math.abs(b.delta || 0) - Math.abs(a.delta || 0);
            if (boardSort === 'volume') return _volNum(b.volume) - _volNum(a.volume);
            if (boardSort === 'name') return String(a.keyword).localeCompare(String(b.keyword), 'ko');
            return (a.rank == null) - (b.rank == null) || (a.rank || 0) - (b.rank || 0);
        });
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
            /* 이 업체에 이어진 추적 상품 — 화면 통합(2026-08-29): 상품 관리가 하단 전체
               도구에 떨어져 있어 「업체 따로 상품 따로」 관리 미스가 나던 것을 한 화면으로. */
            (board && board.products && board.products.length > 0) && React.createElement('div', {
                style: { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14, padding: '13px 16px', marginBottom: 14 }
            },
                React.createElement('div', { style: { fontSize: 13, fontWeight: 800, color: '#334155', marginBottom: 9 } },
                    '🛍 이 업체의 추적 상품 ' + board.products.length + '개',
                    React.createElement('span', { style: { fontSize: 11.5, fontWeight: 500, color: '#94a3b8', marginLeft: 8 } },
                        '아래 키워드 표와 같은 기록입니다 — 상품을 지우면 그 상품의 키워드·이력만 빠집니다')),
                board.products.map(function(p) {
                    return React.createElement('div', {
                        key: p.id,
                        style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '7px 0', borderTop: '1px solid #f1f5f9' }
                    },
                        React.createElement('span', { style: { fontSize: 12.5, fontWeight: 700, color: '#0f172a', maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
                            p.name || '(상품명 없음)'),
                        p.disabled && React.createElement('span', {
                            style: { fontSize: 10.5, fontWeight: 800, padding: '1px 8px', borderRadius: 999, background: '#f1f5f9', color: '#64748b' },
                            title: '키워드가 0개가 되어 수집을 쉬는 상품 — 키워드를 다시 등록하면 깨어납니다'
                        }, '휴면'),
                        React.createElement('span', { style: { fontSize: 11.5, color: '#64748b' } },
                            '키워드 ' + ((p.keywords || []).length) + '개' + ((p.keywords || []).length ? ' · ' + p.keywords.join(', ') : '')),
                        p.url && React.createElement('a', {
                            href: p.url, target: '_blank', rel: 'noopener noreferrer',
                            style: { fontSize: 11.5, color: '#3b82f6', fontWeight: 600, textDecoration: 'none' }
                        }, '상품 열기 ↗'),
                        canEditHere && React.createElement('span', { style: { marginLeft: 'auto', display: 'inline-flex', gap: 6 } },
                            React.createElement('button', {
                                onClick: function() { refreshDetailProduct(client, p); }, disabled: prodBusy,
                                style: { border: '1px solid #bfdbfe', background: '#eff6ff', color: '#1d4ed8', borderRadius: 8, padding: '4px 10px', fontSize: 11.5, fontWeight: 700, cursor: prodBusy ? 'default' : 'pointer' }
                            }, '↻ 재확인'),
                            React.createElement('button', {
                                onClick: function() { deleteDetailProduct(client, p); }, disabled: prodBusy,
                                style: { border: '1px solid #fecaca', background: '#fef2f2', color: '#dc2626', borderRadius: 8, padding: '4px 10px', fontSize: 11.5, fontWeight: 700, cursor: prodBusy ? 'default' : 'pointer' }
                            }, '🗑 상품 삭제'))
                    );
                })
            ),
            React.createElement('div', { style: _krCard },
                /* 추적 키워드 추가 등록 (2026-08-11 직원 기능 요청) — 서버가 권한·중복·
                   영업대상 여부를 최종 판정하므로 입력은 항상 노출, 결과 메시지로 안내 */
                React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10, padding: '10px 12px', background: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: 10 } },
                    React.createElement('span', { style: { fontSize: 12.5, fontWeight: 700, color: '#475569' } }, '＋ 추적 키워드 등록'),
                    React.createElement('input', {
                        value: kwInput, disabled: kwBusy,
                        onChange: function(e) { setKwInput(e.target.value); },
                        onKeyDown: function(e) { if (e.key === 'Enter' && !e.nativeEvent.isComposing) submitKeyword(); },
                        placeholder: '예: 수제쿠키 (Enter)',
                        style: { flex: '1 1 180px', maxWidth: 260, padding: '7px 12px', border: '1px solid #e2e8f0', borderRadius: 9, fontSize: 13, outline: 'none' }
                    }),
                    React.createElement('button', {
                        onClick: submitKeyword, disabled: kwBusy || !kwInput.trim(),
                        style: { border: 'none', background: (kwBusy || !kwInput.trim()) ? '#93c5fd' : '#3b82f6', color: '#fff', borderRadius: 9, padding: '7px 16px', fontSize: 12.5, fontWeight: 700, cursor: (kwBusy || !kwInput.trim()) ? 'default' : 'pointer' }
                    }, kwBusy ? '등록 중…' : '등록'),
                    kwMsg && React.createElement('span', { style: { fontSize: 12, fontWeight: 600, color: kwMsg.ok ? '#16a34a' : '#dc2626', flexBasis: '100%' } }, kwMsg.text)
                ),
                /* 2차 확산: 정렬 · 추이 기간 컨트롤 */
                React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 } },
                    React.createElement('select', {
                        value: boardSort, onChange: function(e) { setBoardSort(e.target.value); },
                        style: { border: '1px solid #e2e8f0', borderRadius: 9, padding: '7px 11px', fontSize: 12.5, fontWeight: 600, color: '#475569', background: '#fff' }
                    },
                        React.createElement('option', { value: 'rank' }, '정렬: 순위순'),
                        React.createElement('option', { value: 'delta' }, '변동 큰 순'),
                        React.createElement('option', { value: 'volume' }, '검색량 많은 순'),
                        React.createElement('option', { value: 'name' }, '가나다순')),
                    React.createElement('span', { style: { display: 'inline-flex', border: '1px solid #e2e8f0', borderRadius: 9, overflow: 'hidden' } },
                        [7, 30].map(function(d) {
                            var on = boardDays === d;
                            return React.createElement('button', {
                                key: d, onClick: function() { changeBoardDays(d); },
                                style: { border: 'none', padding: '7px 13px', fontSize: 12.5, fontWeight: 700, cursor: 'pointer',
                                         background: on ? '#3b82f6' : '#fff', color: on ? '#fff' : '#475569' }
                            }, d + '일');
                        })),
                    React.createElement('span', { style: { fontSize: 12, color: '#94a3b8', marginLeft: 'auto' } }, '추이·전일 대비는 매일 08:00 기록 기준')
                ),
                bdLoading ? React.createElement('div', { style: { padding: '40px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 } }, '불러오는 중...') :
                rows.length === 0 ? React.createElement('div', { style: { padding: '40px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 } },
                    '아직 순위 기록이 없습니다. 위 「＋ 추적 키워드 등록」에 키워드를 넣으면 수 분 안에 첫 순위가 기록됩니다.') :
                React.createElement('div', { style: { overflowX: 'auto' } },
                    React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
                        React.createElement('thead', null, React.createElement('tr', null,
                            React.createElement('th', { style: _krTh }, '키워드'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, '현재 순위'),
                            React.createElement('th', { style: _krTh }, '전일 대비'),
                            React.createElement('th', { style: _krTh }, '최근 ' + boardDays + '일'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, '월 검색량'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, '페이지'),
                            React.createElement('th', { style: _krTh }, '확인 시각'),
                            React.createElement('th', { style: _krTh }, '이미지')
                        )),
                        React.createElement('tbody', null, rows.map(function(b) {
                            var d = _krDelta(b.delta === null || b.delta === undefined ? (b.prev_rank == null && b.rank != null ? undefined : 0) : b.delta);
                            var exposed = b.rank !== null && b.rank !== undefined;
                            var open = expandedKw === b.keyword;
                            var mainRow = React.createElement('tr', {
                                key: b.keyword,
                                onClick: function() { toggleKw(client, b.keyword); },
                                style: { cursor: 'pointer', background: open ? '#f8fafc' : 'transparent' },
                                onMouseEnter: function(e) { e.currentTarget.style.background = '#f8fafc'; },
                                onMouseLeave: function(e) { e.currentTarget.style.background = open ? '#f8fafc' : 'transparent'; }
                            },
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontWeight: 700, color: '#0f172a' }) },
                                    React.createElement('span', { style: { color: '#94a3b8', fontSize: 10, marginRight: 7 } }, open ? '▼' : '▶'),
                                    b.keyword,
                                    /* 이 키워드만 다른 상품으로 추적 중이면 표시 — 안 보이면 업체 대표 상품이다 */
                                    b.product_assigned && React.createElement('span', {
                                        style: { marginLeft: 7, fontSize: 10.5, fontWeight: 800, padding: '1px 7px', borderRadius: 999,
                                                 background: '#eff6ff', color: '#1d4ed8', verticalAlign: 'middle' },
                                        title: '이 키워드는 지정한 상품으로 추적합니다'
                                    }, '개별 상품'),
                                    /* 출처 — 어디서 등록돼 재는지. 그만 재기 때 무엇이 빠지는지 알려면 필요하다 */
                                    b.source_label && React.createElement('span', {
                                        style: { marginLeft: 7, fontSize: 10.5, fontWeight: 700, padding: '1px 7px', borderRadius: 999,
                                                 background: b.source === 'product' ? '#f5f3ff' : '#f8fafc',
                                                 color: b.source === 'product' ? '#7c3aed' : '#64748b',
                                                 border: '1px solid ' + (b.source === 'product' ? '#ddd6fe' : '#e2e8f0'),
                                                 verticalAlign: 'middle', maxWidth: 180, overflow: 'hidden',
                                                 textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block' },
                                        title: '등록 출처 — ' + b.source_label
                                    }, b.source_label)),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right' }) },
                                    exposed
                                        ? React.createElement('span', { style: { fontSize: 16, fontWeight: 800, color: b.rank <= 10 ? '#16a34a' : '#0f172a', fontVariantNumeric: 'tabular-nums' } }, b.rank + '위')
                                        : b.pending
                                        // 「기록 대기」를 두 종류로 가른다(신고 #248) —
                                        // 기다리면 풀리는 것과, 사람이 손대기 전엔 영영 안 풀리는 것.
                                        // ⚠️ 종전엔 둘 다 같은 배지에 「보통 수 분」이라고 적혀 있었다.
                                        //    추가 등록 키워드는 오후 슬롯이라 실제로는 최대 하루다.
                                        ? (b.pending_reason === 'blocked'
                                            ? React.createElement('span', {
                                                style: Object.assign({}, _krChip('warn'), { background: '#fef2f2', color: '#b91c1c', border: '1px solid #fecaca' }),
                                                title: b.pending_hint || '지금은 기록되지 않습니다'
                                              }, '⚠ 추적 안 됨')
                                            : React.createElement('span', {
                                                style: _krChip('info'),
                                                title: '등록됐고 아직 그 키워드의 수집 시간대가 안 왔습니다 — ' + (b.pending_hint || '오늘 안에 수집')
                                              }, '⏳ ' + (b.pending_hint || '수집 대기')))
                                        : React.createElement('span', null,
                                            React.createElement('span', { style: _krChip('mute') }, '미노출'),
                                            (b.unexposed_days || 0) >= 2 && React.createElement('span', { style: Object.assign({}, _krChip('warn'), { marginLeft: 4 }), title: '연속 미노출 일수' }, b.unexposed_days + '일째'))),
                                React.createElement('td', { style: _krTd },
                                    exposed && (b.delta !== null && b.delta !== undefined)
                                        ? React.createElement('span', { style: d.style }, d.label)
                                        : React.createElement('span', { style: { fontSize: 11.5, color: '#cbd5e1' } }, '—')),
                                React.createElement('td', { style: _krTd }, _krSparkline(b.series)),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }) }, b.volume || '—'),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }) }, exposed && b.page ? b.page + 'p' : '—'),
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontSize: 12, color: '#94a3b8', whiteSpace: 'nowrap' }) },
                                    b.last_checked ? String(b.last_checked).slice(0, 16).replace('T', ' ') : '—'),
                                React.createElement('td', { style: Object.assign({}, _krTd, { whiteSpace: 'nowrap' }) },
                                    React.createElement('button', {
                                        onClick: function(e) { e.stopPropagation(); if (!open) toggleKw(client, b.keyword); else setExpandedKw(null); },
                                        title: '순위 추이 그래프 + 이미지(PNG) 저장',
                                        style: { fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 14, cursor: 'pointer', border: '1px solid #16a34a', background: '#f0fdf4', color: '#16a34a' }
                                    }, open ? '▴ 접기' : '📸 그래프·저장'),
                                    /* 그만 재기 ✕ — 오타·안 쓰는 키워드 정리(2026-08-29 직원 신고).
                                       지우는 게 아니라 억제 — 재등록 한 번이면 기록 그대로 복귀 */
                                    canEditHere && React.createElement('button', {
                                        onClick: function(e) { e.stopPropagation(); untrackKeyword(client, b); },
                                        title: '그만 재기 — 업체·이어진 상품 양쪽에서 함께 빠집니다(기록 보존 · 재등록 시 복귀)',
                                        style: { marginLeft: 6, fontSize: 11, fontWeight: 800, padding: '3px 9px', borderRadius: 14, cursor: 'pointer', border: '1px solid #fca5a5', background: '#fef2f2', color: '#dc2626' }
                                    }, '✕'))
                            );
                            return open
                                ? React.createElement(React.Fragment, { key: b.keyword + '::grp' }, mainRow, renderKwPanel(client, b))
                                : mainRow;
                        }))
                    )
                )
            )
        );
    }

    var canEditHere = currentUser && currentUser.role !== 'viewer';

    return React.createElement('div', { style: _krWrap },
        React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 16, flexWrap: 'wrap' } },
            React.createElement('h1', { style: { margin: 0, fontSize: 21, fontWeight: 800, color: '#0f172a', letterSpacing: '-.02em' } }, '📊 쇼핑 순위 추적'),
            React.createElement('span', { style: { fontSize: 12.5, color: '#94a3b8' } },
                selected ? '업체 상세 — 키워드별 추적 현황' : (isViewer ? '내 영업 대상 업체별 순위 추적 현황' : '광고주 업체별 순위 추적 현황') + ' · 매일 아침 자동 기록')),
        /* ---------- ⚠ 추적 안 됨 정리함 (신고 #248 후속) ---------- */
        !selected && canEditHere && tray && (function() {
            var stuck = tray.stuck || [], shelved = tray.shelved || [];
            if (!stuck.length && !shelved.length) return null;   // 0건이면 아무것도 안 보인다
            var red = stuck.length > 0;
            var banner = React.createElement('div', {
                style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: trayOpen ? 0 : 18,
                         padding: red ? '11px 16px' : '7px 14px', borderRadius: trayOpen ? '10px 10px 0 0' : 10,
                         background: red ? '#fef2f2' : '#f8fafc',
                         border: '1px solid ' + (red ? '#fecaca' : '#e2e8f0'),
                         borderBottom: trayOpen ? 'none' : undefined, fontSize: 13.5 }
            },
                React.createElement('span', { style: { fontSize: red ? 16 : 14 } }, red ? '⚠' : '🗄'),
                React.createElement('span', { style: { flex: 1, color: red ? '#b91c1c' : '#64748b' } },
                    red
                        ? React.createElement('span', null, React.createElement('b', null, '추적 안 되는 키워드 ' + tray.stuck_keywords + '개'),
                            ' — 계약이 끝난 업체의 상품 ' + stuck.length + '개에 걸려 있습니다.')
                        : '내려간 상품 ' + shelved.length + '개 — 업체를 이으면 되살릴 수 있습니다.'),
                React.createElement('button', {
                    onClick: function() { setTrayOpen(!trayOpen); if (!trayOpen) setTrayTab(red ? 'stuck' : 'shelved'); },
                    style: { border: 0, borderRadius: 7, padding: '6px 13px', fontSize: 12.5, fontWeight: 700, cursor: 'pointer',
                             background: red ? '#3b82f6' : '#fff', color: red ? '#fff' : '#475569',
                             boxShadow: red ? 'none' : 'inset 0 0 0 1px #cbd5e1' }
                }, trayOpen ? '닫기' : '정리함 열기'));

            if (!trayOpen) return banner;

            var tabBtn = function(key, label, n) {
                var on = trayTab === key;
                return React.createElement('button', {
                    key: key, onClick: function() { setTrayTab(key); },
                    style: { border: 0, background: 'none', padding: '9px 13px', fontSize: 13, fontWeight: 700, cursor: 'pointer',
                             color: on ? '#1d4ed8' : '#64748b', borderBottom: '2px solid ' + (on ? '#3b82f6' : 'transparent') }
                }, label + ' ' + n);
            };
            var stageChip = function(c) {
                return React.createElement('span', {
                    key: c.id,
                    style: { fontSize: 11, padding: '1px 8px', borderRadius: 99, marginLeft: 5, whiteSpace: 'nowrap',
                             background: c.eligible ? '#f0fdf4' : '#fef2f2',
                             color: c.eligible ? '#15803d' : '#b91c1c',
                             border: '1px solid ' + (c.eligible ? '#bbf7d0' : '#fecaca') }
                }, c.name + (c.stage ? ' · ' + c.stage : ''));
            };
            var rowBase = { display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px',
                            borderBottom: '1px solid #f1f5f9', fontSize: 13, flexWrap: 'wrap' };
            var actBtn = function(label, primary, onClick, disabled) {
                return React.createElement('button', {
                    onClick: onClick, disabled: !!disabled,
                    style: { border: 0, borderRadius: 6, padding: '5px 11px', fontSize: 12, fontWeight: 700,
                             cursor: disabled ? 'default' : 'pointer', opacity: disabled ? .5 : 1,
                             background: primary ? '#3b82f6' : '#fff', color: primary ? '#fff' : '#475569',
                             boxShadow: primary ? 'none' : 'inset 0 0 0 1px #cbd5e1' }
                }, label);
            };

            var body;
            if (trayTab === 'stuck') {
                body = [React.createElement('div', { key: 'n', style: { margin: '10px 14px 4px', padding: '8px 12px', borderRadius: 7, fontSize: 12.5, background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#166534' } },
                    '계약이 다시 살아나면 다음 날 새벽부터 자동 재개됩니다 — 지우지 않아도 됩니다. 다시 볼 일 없는 것만 내려 주세요(되돌릴 수 있습니다).')]
                    .concat(stuck.map(function(pd) {
                        return React.createElement('div', { key: pd.id, style: rowBase },
                            React.createElement('span', { style: { fontWeight: 600, flex: '1 1 240px', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, title: pd.name }, pd.name || '(이름 없음)'),
                            React.createElement('span', { style: { flex: '1 1 200px' } }, pd.clients.map(stageChip)),
                            React.createElement('span', { style: { color: '#94a3b8', fontSize: 12 }, title: pd.keywords.join(', ') }, '키워드 ' + pd.keywords.length),
                            actBtn(trayBusy === pd.id ? '내리는 중…' : '🗄 내리기', false,
                                function() { trayAct(pd.id, '/shelve', null, '내렸습니다'); }, trayBusy === pd.id));
                    }));
            } else {
                body = [React.createElement('div', { key: 'n', style: { margin: '10px 14px 4px', padding: '8px 12px', borderRadius: 7, fontSize: 12.5, background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e' } },
                    '내려간 상품입니다(주인 없어 자동으로 내려간 것 + 직접 내린 것). 업체를 이으면 그 자리에서 되살아나 다음 수집부터 다시 잽니다.')]
                    .concat(shelved.map(function(pd) {
                        var canRevive = pd.clients.some(function(c) { return c.eligible; });
                        var open = linkFor === pd.id;
                        return React.createElement('div', { key: pd.id, style: rowBase },
                            React.createElement('span', { style: { fontWeight: 600, flex: '1 1 240px', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, title: pd.name }, pd.name || '(이름 없음)'),
                            React.createElement('span', { style: { flex: '1 1 160px', color: '#94a3b8', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, title: pd.keywords.join(', ') }, pd.keywords.join(' · ') || '—'),
                            React.createElement('span', { style: { color: '#94a3b8', fontSize: 11.5, whiteSpace: 'nowrap' } }, '내린 날 ' + (pd.disabled_at || '—')),
                            pd.clients.length > 0 && React.createElement('span', null, pd.clients.map(stageChip)),
                            canRevive && actBtn(trayBusy === pd.id ? '…' : '↩ 되살리기', true,
                                function() { trayAct(pd.id, '/revive', null, '되살렸습니다'); }, trayBusy === pd.id),
                            actBtn(open ? '연결 취소' : '업체 연결', !canRevive,
                                function() { setLinkFor(open ? null : pd.id); setLinkQ(''); setLinkOpts([]); }),
                            open && React.createElement('div', { style: { flexBasis: '100%', display: 'flex', gap: 8, alignItems: 'center', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 7, padding: '8px 10px', position: 'relative' } },
                                React.createElement('input', {
                                    value: linkQ, autoFocus: true,
                                    onChange: function(e) { setLinkQ(e.target.value); },
                                    placeholder: '업체명 검색 — 목록에서 고른 것만 연결됩니다',
                                    style: { flex: 1, border: '1px solid #cbd5e1', borderRadius: 6, padding: '6px 10px', font: 'inherit', fontSize: 12.5 }
                                }),
                                linkOpts.length > 0 && React.createElement('div', { style: { position: 'absolute', top: '100%', left: 10, right: 10, zIndex: 20, background: '#fff', border: '1px solid #cbd5e1', borderRadius: 7, boxShadow: '0 8px 20px rgba(15,23,42,.12)', maxHeight: 180, overflowY: 'auto' } },
                                    linkOpts.slice(0, 8).map(function(c) {
                                        return React.createElement('button', {
                                            key: c.id,
                                            onClick: function() { trayAct(pd.id, '/relink', { client_id: c.id }, '연결했습니다'); },
                                            style: { display: 'block', width: '100%', textAlign: 'left', border: 0, background: 'none', padding: '7px 11px', fontSize: 12.5, cursor: 'pointer' }
                                        }, c.name);
                                    }))));
                    }));
            }

            return React.createElement('div', { style: { marginBottom: 18 } },
                banner,
                React.createElement('div', { style: { border: '1px solid ' + (red ? '#fecaca' : '#e2e8f0'), borderTop: 'none', borderRadius: '0 0 10px 10px', background: '#fff' } },
                    React.createElement('div', { style: { display: 'flex', gap: 2, borderBottom: '1px solid #f1f5f9', padding: '0 8px' } },
                        tabBtn('stuck', '계약 끝난 업체의 상품', stuck.length),
                        tabBtn('shelved', '🗄 내려간 상품(보관)', shelved.length)),
                    body,
                    React.createElement('div', { style: { padding: '8px 14px 10px', fontSize: 11.5, color: '#94a3b8' } },
                        '하드 삭제는 없습니다 — 전부 내리기·되살리기로 오갑니다(대표 확정 2026-09-01).')));
        })(),

        /* ---------- ＋ 추적 상품 등록 (항상 펼침) ----------
           업체 목록 화면에서만 — 업체 상세는 그 업체 것만 보이게 두는 기존 규칙 그대로. */
        !selected && canEditHere && React.createElement('div', { style: _krRegBox },
            React.createElement('div', { style: { fontSize: 13.5, fontWeight: 800, color: '#2563eb', marginBottom: 11 } }, '＋ 추적 상품 등록'),
            React.createElement('div', { style: _krRegRow },
                /* 업체 — 고른 것만 저장된다 */
                React.createElement('div', { style: { position: 'relative' } },
                    React.createElement('label', { style: _krRegLbl }, '업체 ', React.createElement('span', { style: { color: '#ef4444' } }, '*')),
                    regClient
                        ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, background: '#fff', border: '1px solid #3b82f6', borderRadius: 99, padding: '5px 8px 5px 11px', fontSize: 12.5, fontWeight: 800, color: '#2563eb' } },
                            React.createElement('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, regClient.name),
                            React.createElement('button', {
                                onClick: function() { setRegClient(null); setRegQuery(''); },
                                title: '업체 다시 고르기',
                                style: { border: 0, background: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '0 2px', fontWeight: 400 }
                            }, '✕'))
                        : React.createElement('input', {
                            style: _krRegInp, value: regQuery, placeholder: '업체명 검색', autoComplete: 'off',
                            onChange: function(e) { setRegQuery(e.target.value); }
                        }),
                    !regClient && regOpts.length > 0 && React.createElement('div', {
                        style: { position: 'absolute', zIndex: 20, left: 0, right: 0, top: 'calc(100% + 4px)', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, boxShadow: '0 8px 20px rgba(15,23,42,.12)', maxHeight: 190, overflow: 'auto' }
                    }, regOpts.map(function(c) {
                        return React.createElement('button', {
                            key: c.id,
                            onClick: function() { setRegClient(c); setRegOpts([]); },
                            style: { display: 'block', width: '100%', textAlign: 'left', border: 0, background: 'none', padding: '7px 11px', fontSize: 12.5, cursor: 'pointer', fontFamily: 'inherit', color: '#0f172a' }
                        }, c.name);
                    }))
                ),
                React.createElement('div', null,
                    React.createElement('label', { style: _krRegLbl }, '상품 URL ', React.createElement('span', { style: { color: '#ef4444' } }, '*')),
                    React.createElement('input', {
                        style: _krRegInp, value: regUrl, placeholder: 'https://smartstore.naver.com/…/products/12345',
                        onChange: function(e) { setRegUrl(e.target.value); }
                    })),
                React.createElement('div', null,
                    React.createElement('label', { style: _krRegLbl }, '추적 키워드 ', React.createElement('span', { style: { color: '#ef4444' } }, '*')),
                    React.createElement('input', {
                        style: _krRegInp, value: regKw, placeholder: '고구마, 꿀고구마',
                        onChange: function(e) { setRegKw(e.target.value); },
                        onKeyDown: function(e) { if (e.key === 'Enter') submitRegister(); }
                    })),
                React.createElement('button', {
                    onClick: submitRegister, disabled: !regReady,
                    style: { border: 0, background: regReady ? '#3b82f6' : '#cbd5e1', color: '#fff', borderRadius: 8, padding: '9px 16px', fontSize: 12.5, fontWeight: 700, cursor: regReady ? 'pointer' : 'not-allowed', whiteSpace: 'nowrap', fontFamily: 'inherit' }
                }, regBusy ? '등록 중…' : '등록')
            ),
            React.createElement('div', { style: { fontSize: 11, marginTop: 7, color: regMsg ? (regMsg.ok ? '#047857' : '#b91c1c') : '#64748b' } },
                regMsg ? regMsg.text
                       : (regClient
                            ? '「' + regClient.name + '」 것으로 등록됩니다 — 그 업체 계약이 끝나면 추적도 함께 멈춥니다.'
                            : '업체는 목록에서 골라야 합니다. 여러 키워드는 쉼표(,)로 구분하세요.'))
        ),

        selected ? renderDetail() : renderList(),

        /* ---------- 추적 상품 관리(전체 업체 도구) — 업체 목록에서만, 기본 접힘 ----------
           업체 상세는 그 업체 데이터만 보이도록 여기서 제외한다(운영자 지시 2026-08-04). */
        !selected && React.createElement('div', { style: { marginTop: 28 } },
            React.createElement('button', {
                onClick: function() { setTrackingOpen(!trackingOpen); },
                style: { width: '100%', textAlign: 'left', border: '1px solid #e2e8f0', background: '#fff', color: '#334155', borderRadius: 12, padding: '13px 18px', fontSize: 13.5, fontWeight: 700, cursor: 'pointer' }
            },
                (trackingOpen ? '▴ ' : '▾ ') + '🛠 전체 도구 — 업체에 안 이어진 상품 · 1회성 노출 조회',
                !trackingOpen && React.createElement('span', { style: { fontSize: 12, fontWeight: 500, color: '#94a3b8', marginLeft: 8 } },
                    linkedHiddenCount > 0
                        ? '업체에 이어진 상품 ' + linkedHiddenCount + '개는 각 업체 상세에서 관리합니다'
                        : '펼쳐서 관리')
            ),
            trackingOpen && React.createElement('div', { style: { marginTop: 12 } },
                linkedHiddenCount > 0 && React.createElement('div', {
                    style: { fontSize: 12, color: '#64748b', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '8px 12px', marginBottom: 10 }
                }, 'ℹ️ 업체에 이어진 상품 ' + linkedHiddenCount + '개는 여기 안 보입니다 — 위 업체 목록에서 그 업체를 열면 상품·키워드를 한 화면에서 관리합니다(같은 것을 두 곳에서 만지지 않게).'),
                React.createElement(window.SectionErrorBoundary, { name: '순위 추적' },
                    React.createElement(window.RankTrackingSection, {
                        products: unlinkedProducts,
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
