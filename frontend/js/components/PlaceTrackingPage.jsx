/* PlaceTrackingPage — 📍 지도 순위 추적 탭 (플레이스 무인 순위 추적)
 *
 * 2026-08-11 대표 지시로 **쇼핑 순위 추적(KeywordRankPage)과 같은 골격**으로 재구현:
 * 랜딩 = 업체 목록(KPI 밴드·검색·필터 칩·행 클릭 → 상세) / 상세 = 그 업체의 키워드
 * 보드(현재 순위·전일 Δ·7일 스파크라인·행 펼침 추이 차트·📸 이미지 저장).
 * 스타일 상수(_kr*)·칩·스파크라인은 KeywordRankPage.jsx 의 것을 그대로 쓴다
 * (번들 순서상 먼저 로드 — 한 소스 = 두 화면이 항상 같은 모양).
 *
 * 다른 것은 「추적하는 대상」뿐이다:
 *  - 수집은 「플레이스 순위 추적기」 확장(추적 PC)이 매일 아침 무인 수행 → /api/place/ingest
 *  - 이 화면은 확장에 추적 목록을 동기화(METAINC_PLACE_TARGETS)하고 즉시 수집(METAINC_PLACE_RUN) 요청
 *  - 등록 키워드는 지역 자동 합성(placeCombineKeyword — 서버와 1:1 규칙, 미리보기 제공)
 *  - 사용 범주 = 쇼핑 순위 추적과 동일(2026-08-04 대표 확정): viewer 는 열람만.
 */
window.PlaceTrackingPage = function PlaceTrackingPage(props) {
    var useState = React.useState, useEffect = React.useEffect;

    var currentUser = props.currentUser;
    var isViewer = !!(currentUser && currentUser.role === 'viewer');

    // ── 목록 상태 ──
    var _t = useState([]);        var targets = _t[0], setTargets = _t[1];
    var _ld = useState(true);     var loading = _ld[0], setLoading = _ld[1];
    var _q = useState('');        var query = _q[0], setQuery = _q[1];
    var _flt = useState('all');   var filter = _flt[0], setFilter = _flt[1];      // all|attention|up|down
    var _sel = useState(null);    var selected = _sel[0], setSelected = _sel[1];  // {name, region, place_id}
    var _bs = useState('rank');   var boardSort = _bs[0], setBoardSort = _bs[1];  // rank|delta|name

    // ── 신규 업체 등록 폼 (랜딩) ──
    var _n = useState('');        var bizName = _n[0], setBizName = _n[1];
    var _r = useState('');        var region = _r[0], setRegion = _r[1];
    var _ki = useState('');       var kwInput = _ki[0], setKwInput = _ki[1];
    var _ks = useState([]);       var kws = _ks[0], setKws = _ks[1];
    var _sv = useState(false);    var saving = _sv[0], setSaving = _sv[1];
    var _pid = useState('');      var placeIdInput = _pid[0], setPlaceIdInput = _pid[1];
    var _ro = useState(false);    var regOpen = _ro[0], setRegOpen = _ro[1];      // 등록 카드 접기(기본 접힘 — 목록이 먼저)

    // ── 상세: 키워드 추가 등록 ──
    var _dki = useState('');      var dKwInput = _dki[0], setDKwInput = _dki[1];
    var _dkb = useState(false);   var dKwBusy = _dkb[0], setDKwBusy = _dkb[1];
    var _dkm = useState(null);    var dKwMsg = _dkm[0], setDKwMsg = _dkm[1];      // {ok, text}

    // ── 확장 연동 상태 ──
    var _ex = useState(false);    var extReady = _ex[0], setExtReady = _ex[1];

    // ── 키워드 행 펼침(순위 추이 차트) — 쇼핑 순위 추적과 동일 패턴 ──
    var _open = useState(null);   var expandedKw = _open[0], setExpandedKw = _open[1];   // 'bk||keyword'
    var _kd = useState({});       var kwDays = _kd[0], setKwDays = _kd[1];               // { key: 7|30|0 }
    var _hc = useState({});       var histCache = _hc[0], setHistCache = _hc[1];         // { key: series(90일) }

    // ==================== 플레이스 ID 추출 ====================
    // 네이버 지도/플레이스 주소의 **알려진 자리**에서만 숫자 ID 를 뽑는다.
    // ⚠️ 종전의 「아무 7자리+ 숫자」 폴백은 제거(2026-08-11) — 주소·문구에 섞인 날짜가
    //    ID 로 삼켜져 등록 시각(YYYYMMDDHHMM)이 플레이스 ID 로 저장된 실사고(흑해·금정산성).
    //    잘못된 ID 는 러너의 정확 매칭을 영영 빗나가게 하고, self-heal 은 빈 값만 채워
    //    스스로 낫지 않는다. 서버도 같은 형식 검증으로 이중 방어한다.
    function _looksLikeTimestampId(s) {
        if (!/^\d{12}$/.test(s)) return false;
        var y = +s.slice(0, 4), mo = +s.slice(4, 6), d = +s.slice(6, 8), h = +s.slice(8, 10), mi = +s.slice(10, 12);
        return y >= 2020 && y <= 2035 && mo >= 1 && mo <= 12 && d >= 1 && d <= 31 && h <= 23 && mi <= 59;
    }
    function extractPlaceId(v) {
        v = String(v || '').trim();
        if (!v) return '';
        if (/^\d{5,}$/.test(v)) return _looksLikeTimestampId(v) ? '' : v;   // 숫자 단독(타임스탬프 모양은 거절)
        var m = v.match(/(?:place|restaurant|cafe|hairshop|hospital|accommodation|attraction)\/(\d{5,})/);
        if (m) return m[1];
        m = v.match(/[?&](?:pinId|placeId|id)=(\d{5,})/);                    // 지도 URL 쿼리 형태
        return m ? m[1] : '';
    }

    // ==================== 확장 브리지 ====================
    // 러너 동기화는 항상 서버 전체 활성 목록(?active=1 — 러너 전용 격리 예외)으로 push:
    // 화면 목록은 본인 것만(개인화)이지만, 무인 수집은 전 직원 등록분을 커버해야 하기 때문.
    function pushTargetsToExt() {
        api.get('/place/track-targets?active=1').then(function (res) {
            if (!(res && res.success)) return;
            var actives = ((res.data && res.data.targets) || []).map(function (t) {
                return { id: t.id, business_name: t.business_name, region: t.region,
                         place_id: t.place_id || '', keyword: t.keyword };
            });
            window.postMessage({ type: 'METAINC_PLACE_TARGETS', payload: { targets: actives } }, window.location.origin);
        }).catch(function () {});
    }

    useEffect(function () {
        var onMsg = function (ev) {
            if (ev.source !== window || !ev.data) return;
            if (ev.data.type === 'METAINC_PLACE_EXT_READY') {
                setExtReady(true);
                pushTargetsToExt();          // 연동 확인 즉시 목록 동기화
            }
        };
        window.addEventListener('message', onMsg);
        try { window.postMessage({ type: 'METAINC_PLACE_PING' }, window.location.origin); } catch (e) {}
        return function () { window.removeEventListener('message', onMsg); };
    }, []);

    function requestRunNow() {
        try { window.postMessage({ type: 'METAINC_PLACE_RUN' }, window.location.origin); } catch (e) {}
        if (extReady) toast.success('⟳ 이 컴퓨터의 추적기에 수집을 요청했습니다 — 키워드당 30~50초, 완료되면 자동 기록됩니다.');
        else toast.warn('이 브라우저에 「플레이스 순위 추적기」 확장이 없습니다 — 추적 PC에서는 매일 아침 자동 수집됩니다.');
    }

    // ==================== 데이터 ====================
    function load() {
        setLoading(true);
        api.get('/place/track-targets').then(function (res) {
            setLoading(false);
            if (res && res.success) {
                setTargets((res.data && res.data.targets) || []);
                pushTargetsToExt();
            }
        }).catch(function () { setLoading(false); });
    }
    useEffect(function () { load(); }, []);

    // ==================== 업체 그룹(랜딩 행 단위) ====================
    function buildGroups() {
        var groups = [], idx = {};
        targets.forEach(function (t) {
            var gk = (t.business_name || '') + '|' + (t.region || '');
            if (idx[gk] === undefined) {
                idx[gk] = groups.length;
                groups.push({ key: gk, name: t.business_name, region: t.region, place_id: t.place_id || '', items: [] });
            }
            var g = groups[idx[gk]];
            if (!g.place_id && t.place_id) g.place_id = t.place_id;
            g.items.push(t);
        });
        groups.forEach(function (g) {
            var s = { keywords: g.items.length, exposed: 0, top10: 0, up: 0, down: 0, pending: 0, best: null, last: '' };
            var tops = [];
            g.items.forEach(function (t) {
                if (!t.last) { s.pending++; return; }
                if (t.last.checked_at && t.last.checked_at > s.last) s.last = t.last.checked_at;
                if (t.last.state === '노출' && t.last.rank != null) {
                    s.exposed++;
                    if (t.last.rank <= 10) s.top10++;
                    if (s.best === null || t.last.rank < s.best) s.best = t.last.rank;
                    tops.push({ keyword: t.keyword, rank: t.last.rank });
                }
                if (t.delta != null && t.delta > 0) s.up++;
                if (t.delta != null && t.delta < 0) s.down++;
            });
            tops.sort(function (a, b) { return a.rank - b.rank; });
            s.top_keywords = tops.slice(0, 2);
            g.sum = s;
        });
        return groups;
    }
    var groups = buildGroups();
    function groupOf(sel) {
        if (!sel) return null;
        for (var i = 0; i < groups.length; i++) if (groups[i].key === sel.key) return groups[i];
        return null;
    }

    // ==================== 등록(신규 업체) ====================
    // ⚠️ 합성 규칙은 utils.js `placeCombineKeyword` 하나만 쓴다(서버 규칙과 1:1).
    function combinedPreview(kw) { return placeCombineKeyword(region, kw); }
    function addKw() {
        var v = (kwInput || '').trim().replace(/,$/, '');
        if (!v) return;
        if (kws.length >= 10) { toast.warn('키워드는 업체당 최대 10개입니다.'); return; }
        if (kws.indexOf(v) >= 0) { setKwInput(''); return; }
        setKws(kws.concat([v]));
        setKwInput('');
    }
    function onKwKey(e) {
        if (e.nativeEvent && e.nativeEvent.isComposing) return;   // 한글 IME 중복 방지
        if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addKw(); }
    }
    function submit() {
        if (saving) return;
        var name = (bizName || '').trim(), reg = (region || '').trim();
        var pending = (kwInput || '').trim();
        var list = pending && kws.indexOf(pending) < 0 && kws.length < 10 ? kws.concat([pending]) : kws;
        if (!name) { toast.warn('업체명을 입력해주세요.'); return; }
        if (!reg) { toast.warn('지역을 입력해주세요. (예: 성수동 — 순위 재현에 필요)'); return; }
        if (!list.length) { toast.warn('추적 키워드를 1개 이상 입력해주세요.'); return; }
        var pid = '';
        if ((placeIdInput || '').trim()) {
            pid = extractPlaceId(placeIdInput);
            if (!pid) { toast.warn('플레이스 링크/ID를 인식하지 못했습니다 — 네이버 지도 업체 페이지 주소나 숫자 ID를 붙여넣어주세요. (비워두면 업체명으로 찾습니다)'); return; }
        }
        setSaving(true);
        api.post('/place/track-targets', { business_name: name, region: reg, keywords: list, place_id: pid })
            .then(function (res) {
                setSaving(false);
                if (res && res.success) {
                    toast.success('✅ 추적 등록: ' + name + ' · 키워드 ' + ((res.data && res.data.added) || 0) + '개 — 다음 자동 수집부터 기록됩니다.');
                    setBizName(''); setRegion(''); setKws([]); setKwInput(''); setPlaceIdInput('');
                    load();
                } else {
                    toast.error((res && res.error) || '등록에 실패했습니다.');
                }
            }).catch(function () { setSaving(false); });
    }

    // ==================== 상세: 키워드 추가 등록 ====================
    function submitDetailKeyword(g) {
        var kw = (dKwInput || '').trim();
        if (!kw || dKwBusy || !g) return;
        setDKwBusy(true); setDKwMsg(null);
        api.post('/place/track-targets', { business_name: g.name, region: g.region, keywords: [kw], place_id: g.place_id || '' })
            .then(function (res) {
                setDKwBusy(false);
                if (res && res.success) {
                    var added = (res.data && res.data.added) || 0;
                    var saved = (res.data && res.data.keywords && res.data.keywords[0]) || kw;
                    setDKwMsg({ ok: true, text: added ? ('「' + saved + '」 등록되었습니다 — 다음 자동 수집부터 기록됩니다.') : ('「' + saved + '」 — 이미 추적 중인 키워드입니다.') });
                    if (added) { setDKwInput(''); load(); }
                } else {
                    setDKwMsg({ ok: false, text: (res && res.error) || '등록하지 못했습니다.' });
                }
            }).catch(function () { setDKwBusy(false); setDKwMsg({ ok: false, text: '등록하지 못했습니다.' }); });
    }

    // ==================== 행 액션 ====================
    function toggleActive(t) {
        api.patch('/place/track-targets/' + t.id, { active: !t.active }).then(function (res) {
            if (res && res.success) load();
        });
    }
    function removeTarget(t) {
        if (!window.confirm('「' + t.business_name + ' · ' + t.keyword + '」 추적을 삭제할까요?\n(그동안 쌓인 순위 이력은 보존됩니다 — 재등록하면 이어집니다)')) return;
        api.del('/place/track-targets/' + t.id).then(function (res) {
            if (res && res.success) { toast.success('삭제했습니다.'); load(); }
        });
    }

    // ==================== 펼침 패널(순위 추이) — 쇼핑 순위 추적 renderKwPanel 미러 ====================
    function keyOf(t) { return (t.business_key || '') + '||' + t.keyword; }
    function loadKwHistory(t) {
        var key = keyOf(t);
        if (histCache[key]) return;
        api.get('/place/rank-history?business=' + encodeURIComponent(t.business_key || '')
            + '&keyword=' + encodeURIComponent(t.keyword) + '&days=90')
            .then(function (res) {
                var rows = (res && res.success && res.data && res.data.series) || [];
                setHistCache(function (prev) { var n = Object.assign({}, prev); n[key] = rows; return n; });
            })
            .catch(function () {
                setHistCache(function (prev) { var n = Object.assign({}, prev); n[key] = []; return n; });
                try { toast.error('순위 이력을 불러오지 못했습니다.'); } catch (e) {}
            });
    }
    function toggleKw(t) {
        var key = keyOf(t);
        if (expandedKw === key) { setExpandedKw(null); return; }
        setExpandedKw(key);
        loadKwHistory(t);
    }
    var _kwPeriodLabel = { 7: '최근 7일', 30: '최근 30일', 0: '전체(90일)' };
    function _kwFilterRows(rows, days) {
        if (!days) return rows;
        var cutoff = new Date(); cutoff.setDate(cutoff.getDate() - days);
        var cs = cutoff.toISOString().slice(0, 10);
        return rows.filter(function (r) { return String(r.date || '') >= cs; });
    }
    function saveKwImage(g, t, rows, days) {
        try {
            if (!rows || !rows.length) { try { toast.warn('저장할 순위 데이터가 없습니다.'); } catch (e) {} return; }
            // 쇼핑 순위 추적과 같은 공용 빌더 — 플레이스는 「상태」 컬럼·미노출 「–」 표기(additive 옵션)
            window.exportRankHistoryImage({
                rows: rows.map(function (p) {
                    return { checked_at: p.date || '', rank_position: (p.rank == null ? null : p.rank),
                             type_label: p.state || '미확인', rank_null_label: '–' };
                }),
                storeName: (g && g.name) || t.business_name || '플레이스 업체',
                keyword: t.keyword,
                storeUrl: (g && g.place_id) ? ('https://map.naver.com/p/entry/place/' + g.place_id) : '',
                days: days,
                typeHeader: '상태'
            });
        } catch (e) { try { toast.error('이미지 저장 실패'); } catch (e2) {} }
    }
    function renderKwPanel(g, t) {
        var key = keyOf(t);
        var days = kwDays[key] != null ? kwDays[key] : 7;   // 기본 = 최근 7일
        var all = histCache[key];
        var rows = all ? _kwFilterRows(all, days) : null;
        var setPeriod = function (d) {
            setKwDays(function (prev) { var n = Object.assign({}, prev); n[key] = d; return n; });
        };
        var header = React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 } },
            [7, 30, 0].map(function (d) {
                var on = days === d;
                return React.createElement('button', {
                    key: d, onClick: function (e) { e.stopPropagation(); setPeriod(d); },
                    style: { fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 14, cursor: 'pointer',
                             border: '1px solid ' + (on ? '#3b82f6' : '#e2e8f0'), background: on ? '#3b82f6' : '#fff', color: on ? '#fff' : '#475569' }
                }, _kwPeriodLabel[d]);
            }),
            React.createElement('button', {
                onClick: function (e) { e.stopPropagation(); saveKwImage(g, t, all || [], days); },
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
            var labels = rows.map(function (r) {
                var d = String(r.date || '').split('-');
                return d.length === 3 ? (parseInt(d[1], 10) + '/' + parseInt(d[2], 10)) : (r.date || '');
            });
            var data = rows.map(function (r) { return (r.rank != null && r.rank > 0) ? r.rank : null; });
            var valid = data.filter(function (v) { return v != null; });
            var maxRank = valid.length ? Math.max.apply(null, valid) : 16;
            bodyEl = React.createElement(React.Fragment, null,
                React.createElement('div', { style: { fontSize: 12, fontWeight: 700, color: '#0f172a', marginBottom: 8 } },
                    '"' + t.keyword + '" ' + _kwPeriodLabel[days] + ' 순위 추이'),
                React.createElement(window.ChartCanvas, {
                    canvasId: 'ptrank-' + t.id,
                    type: 'line',
                    height: 180,
                    data: {
                        labels: labels,
                        datasets: [{
                            label: '순위', data: data,
                            borderColor: '#16a34a', backgroundColor: 'rgba(22,163,74,.12)',
                            /* 플레이스는 미노출 날이 의미 있는 정보라 선을 끊는다(spanGaps:false) */
                            fill: true, tension: 0.35, pointRadius: 2.5, borderWidth: 2.5, spanGaps: false
                        }]
                    },
                    options: {
                        plugins: {
                            legend: { display: false },
                            tooltip: { callbacks: { label: function (ctx) { return ctx.parsed.y != null ? ctx.parsed.y + '위' : '미노출/미확인'; } } }
                        },
                        scales: {
                            y: { reverse: true, suggestedMin: 1, suggestedMax: Math.max(16, maxRank + 2), title: { display: true, text: '순위 (낮을수록 상위 ↑)' }, ticks: { precision: 0 } }
                        }
                    }
                })
            );
        }
        return React.createElement('tr', { key: keyOf(t) + '::panel' },
            React.createElement('td', { colSpan: 8, style: { padding: '14px 18px 10px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0' } },
                header, bodyEl));
    }

    // ==================== 공통 셀 ====================
    function fmtChecked(s) { return s ? String(s).slice(0, 16).replace('T', ' ') : '—'; }
    function rankCellOf(t) {
        var exposed = !!(t.last && t.last.state === '노출' && t.last.rank != null);
        if (exposed) {
            return React.createElement('span', { style: { fontSize: 16, fontWeight: 800, color: t.last.rank <= 10 ? '#16a34a' : '#0f172a', fontVariantNumeric: 'tabular-nums' } }, t.last.rank + '위');
        }
        if (!t.last) {
            return React.createElement('span', { style: _krChip('info'), title: '등록됨 — 첫 자동 수집(매일 아침)을 기다리는 중' }, '⏳ 기록 대기');
        }
        if (t.last.state === '미노출') {
            return React.createElement('span', null,
                React.createElement('span', { style: _krChip('mute') }, '미노출'),
                (t.unexposed_days || 0) >= 2 && React.createElement('span', { style: Object.assign({}, _krChip('warn'), { marginLeft: 4 }), title: '연속 미노출 일수' }, t.unexposed_days + '일째'));
        }
        return React.createElement('span', { style: _krChip('mute') }, '미확인');
    }

    // ==================== 등록 카드(랜딩 · 관리팀만) ====================
    var kwChipEls = kws.map(function (k, i) {
        return React.createElement('span', {
            key: k,
            style: { display: 'inline-flex', alignItems: 'center', gap: 4, margin: '2px 4px 2px 0', fontSize: 12, fontWeight: 700,
                     background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe', borderRadius: 999, padding: '3px 10px', cursor: 'pointer' },
            title: '추적 키워드: ' + combinedPreview(k) + ' (클릭 시 제거)',
            onClick: function () { setKws(kws.filter(function (_, j) { return j !== i; })); }
        }, combinedPreview(k) + ' ✕');
    });
    var _regLabel = { display: 'block', fontSize: 11.5, fontWeight: 700, color: '#64748b', marginBottom: 4 };
    var _regInput = { width: '100%', boxSizing: 'border-box', border: '1px solid #e2e8f0', borderRadius: 9, padding: '8px 10px', fontSize: 13, outline: 'none' };
    function renderRegisterCard() {
        if (isViewer) return null;
        var pidExtracted = extractPlaceId(placeIdInput);
        return React.createElement('div', { style: _krCard },
            React.createElement('button', {
                onClick: function () { setRegOpen(!regOpen); },
                style: { width: '100%', textAlign: 'left', border: 'none', background: 'none', color: '#334155', padding: 0, fontSize: 13.5, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' }
            },
                (regOpen ? '▴ ' : '▾ ') + '➕ 추적 대상 등록 — 새 업체·키워드 추가',
                !regOpen && React.createElement('span', { style: { fontSize: 12, fontWeight: 500, color: '#94a3b8', marginLeft: 8 } }, '펼쳐서 등록')
            ),
            regOpen && React.createElement('div', { style: { marginTop: 12 } },
                React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(160px,1.2fr) minmax(120px,0.9fr) minmax(220px,2fr) auto', gap: 10, alignItems: 'end' } },
                    React.createElement('div', null,
                        React.createElement('label', { style: _regLabel }, '업체명 *'),
                        React.createElement('input', { type: 'text', value: bizName, placeholder: '예: 성수동 감성카페',
                            onChange: function (e) { setBizName(e.target.value); }, style: _regInput })),
                    React.createElement('div', null,
                        React.createElement('label', { style: _regLabel }, '지역 *'),
                        React.createElement('input', { type: 'text', value: region, placeholder: '예: 성수동',
                            onChange: function (e) { setRegion(e.target.value); }, style: _regInput })),
                    React.createElement('div', null,
                        React.createElement('label', { style: _regLabel }, '추적 키워드 (Enter로 추가 · 최대 10)'),
                        React.createElement('div', { style: { border: '1px solid #e2e8f0', borderRadius: 9, padding: '4px 8px', background: '#fbfcfe', display: 'flex', flexWrap: 'wrap', alignItems: 'center', minHeight: 36 } },
                            kwChipEls,
                            React.createElement('input', { type: 'text', value: kwInput, placeholder: kws.length ? '' : '예: 카페, 브런치',
                                onChange: function (e) { setKwInput(e.target.value); },
                                onKeyDown: onKwKey,
                                style: { flex: 1, minWidth: 90, border: 0, outline: 'none', background: 'transparent', fontSize: 13, padding: '4px 2px' } }))),
                    React.createElement('button', {
                        onClick: submit, disabled: saving,
                        style: { border: 'none', background: saving ? '#93c5fd' : '#3b82f6', color: '#fff', borderRadius: 9, padding: '9px 18px', fontSize: 13, fontWeight: 700, cursor: saving ? 'default' : 'pointer' }
                    }, saving ? '등록 중…' : '등록')),
                React.createElement('div', { style: { marginTop: 10 } },
                    React.createElement('label', { style: _regLabel }, '플레이스 링크 또는 ID (선택 — 넣으면 이름 대신 ID로 정확 매칭)'),
                    React.createElement('input', { type: 'text', value: placeIdInput,
                        placeholder: '예: https://m.place.naver.com/restaurant/1234567890 · 네이버 지도 업체 페이지 주소를 그대로 붙여넣으세요',
                        onChange: function (e) { setPlaceIdInput(e.target.value); }, style: _regInput }),
                    (placeIdInput || '').trim()
                        ? React.createElement('div', { style: { fontSize: 11.5, marginTop: 4, fontWeight: 700,
                            color: pidExtracted ? '#059669' : '#b45309' } },
                            pidExtracted
                                ? '✓ 인식된 플레이스 ID: ' + pidExtracted
                                : '⚠ ID를 인식하지 못했습니다 — 네이버 지도 업체 페이지 주소 또는 숫자 ID만 인식합니다. 이 칸을 비우면 업체명으로 찾습니다.')
                        : null),
                React.createElement('div', { style: { marginTop: 10, fontSize: 12, color: '#64748b', background: '#f8fafc', border: '1px solid #eef2f6', borderRadius: 9, padding: '8px 12px' } },
                    'ℹ️ 키워드는 자동으로 「지역 + 키워드」로 저장됩니다(칩 미리보기 = 실제 저장 형태). 키워드에 동네가 이미 있으면 지역을 붙이지 않습니다. 플레이스 ID를 비워두면 업체명으로 찾고, 첫 노출 때 ID가 자동 저장됩니다.'))
        );
    }

    // ==================== 랜딩(업체 목록) — 쇼핑 순위 추적 renderList 미러 ====================
    function renderList() {
        var q = query.trim().toLowerCase();
        var totals = { biz: groups.length, keywords: targets.length, exposedBiz: 0, up: 0, down: 0, attention: 0 };
        groups.forEach(function (g) {
            if (g.sum.exposed > 0) totals.exposedBiz++;
            totals.up += g.sum.up; totals.down += g.sum.down;
            if (g.sum.keywords > 0 && g.sum.exposed === 0 && g.sum.pending < g.sum.keywords) totals.attention++;
        });
        var shown = groups.filter(function (g) {
            if (q && String(g.name || '').toLowerCase().indexOf(q) === -1) return false;
            if (filter === 'attention') return g.sum.keywords > 0 && g.sum.exposed === 0 && g.sum.pending < g.sum.keywords;
            if (filter === 'up') return g.sum.up > 0;
            if (filter === 'down') return g.sum.down > 0;
            return true;
        });
        var fchip = function (key, label) {
            var on = filter === key;
            return React.createElement('button', {
                key: key, onClick: function () { setFilter(on ? 'all' : key); },
                style: { border: '1px solid ' + (on ? '#3b82f6' : '#e2e8f0'), background: on ? '#eff6ff' : '#fff', color: on ? '#1d4ed8' : '#475569', borderRadius: 999, padding: '5px 13px', fontSize: 12, fontWeight: 700, cursor: 'pointer' }
            }, label);
        };
        return React.createElement(React.Fragment, null,
            React.createElement('div', { style: _krKpiGrid },
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '추적 업체'),
                    React.createElement('div', { style: _krKpiV }, totals.biz),
                    React.createElement('div', { style: _krKpiS }, '추적 키워드 ' + totals.keywords)),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '노출 중 업체'),
                    React.createElement('div', { style: _krKpiV }, totals.exposedBiz),
                    React.createElement('div', { style: _krKpiS }, '지도 검색 노출 키워드 보유')),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '상승 키워드'),
                    React.createElement('div', { style: Object.assign({}, _krKpiV, { color: '#dc2626' }) }, '▲ ' + totals.up),
                    React.createElement('div', { style: _krKpiS }, '전일 대비 순위 상승')),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '하락 키워드'),
                    React.createElement('div', { style: Object.assign({}, _krKpiV, { color: '#2563eb' }) }, '▼ ' + totals.down),
                    React.createElement('div', { style: _krKpiS }, '전일 대비 순위 하락')),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '주의 필요'),
                    React.createElement('div', { style: Object.assign({}, _krKpiV, { color: totals.attention > 0 ? '#b45309' : '#0f172a' }) }, totals.attention),
                    React.createElement('div', { style: _krKpiS }, '추적 중인데 노출 0'))
            ),
            renderRegisterCard(),
            React.createElement('div', { style: _krCard },
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 12 } },
                    React.createElement('input', {
                        value: query, onChange: function (e) { setQuery(e.target.value); },
                        placeholder: '🔍 업체명 검색',
                        style: { flex: '1 1 200px', maxWidth: 300, padding: '8px 13px', border: '1px solid #e2e8f0', borderRadius: 10, fontSize: 13, outline: 'none' }
                    }),
                    fchip('attention', '⚠️ 주의 필요'), fchip('up', '▲ 상승 보유'), fchip('down', '▼ 하락 보유'),
                    React.createElement('span', { style: { marginLeft: 'auto', fontSize: 12, color: '#94a3b8' } }, shown.length + '개 업체')
                ),
                loading ? React.createElement('div', { style: { padding: '40px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 } }, '불러오는 중...') :
                shown.length === 0 ? React.createElement('div', { style: { padding: '40px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 } },
                    groups.length === 0
                        ? (isViewer ? '등록된 추적 대상이 없습니다. 추적이 필요한 업체는 관리팀에 요청해주세요.'
                                    : '아직 추적 대상이 없습니다. 위 「➕ 추적 대상 등록」에서 업체와 키워드를 등록하면 다음 자동 수집(매일 아침)부터 순위가 기록됩니다.')
                        : '조건에 맞는 업체가 없습니다.') :
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
                        React.createElement('tbody', null, shown.map(function (g) {
                            var s = g.sum;
                            var attention = s.keywords > 0 && s.exposed === 0 && s.pending < s.keywords;
                            var chip = s.pending === s.keywords
                                ? React.createElement('span', { style: _krChip('info') }, '⏳ 기록 대기')
                                : attention
                                    ? React.createElement('span', { style: _krChip('warn') }, '노출 0')
                                    : React.createElement('span', { style: _krChip('ok') }, '노출 ' + s.exposed + '/' + s.keywords);
                            return React.createElement('tr', {
                                key: g.key, onClick: function () { setSelected({ key: g.key, name: g.name, region: g.region, place_id: g.place_id }); setDKwInput(''); setDKwMsg(null); setExpandedKw(null); try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) {} },
                                style: { cursor: 'pointer', background: attention ? '#fffbeb' : 'transparent' },
                                onMouseEnter: function (e) { e.currentTarget.style.background = '#f8fafc'; },
                                onMouseLeave: function (e) { e.currentTarget.style.background = attention ? '#fffbeb' : 'transparent'; }
                            },
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontWeight: 700, color: '#0f172a', whiteSpace: 'nowrap' }) }, '📍 ' + (g.name || ''),
                                    React.createElement('span', { style: { fontWeight: 500, color: '#94a3b8', fontSize: 12, marginLeft: 6 } }, g.region || '')),
                                React.createElement('td', { style: _krTd }, chip),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }) }, s.keywords),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }) }, s.exposed),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }) }, s.top10),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }) },
                                    React.createElement('span', { style: { color: '#dc2626', fontWeight: 700 } }, '▲' + s.up),
                                    React.createElement('span', { style: { color: '#cbd5e1', margin: '0 4px' } }, '/'),
                                    React.createElement('span', { style: { color: '#2563eb', fontWeight: 700 } }, '▼' + s.down)),
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontSize: 12, color: '#64748b' }) },
                                    (s.top_keywords || []).map(function (t) { return t.keyword + ' ' + t.rank + '위'; }).join(' · ') || '—'),
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontSize: 12, color: '#94a3b8', whiteSpace: 'nowrap' }) }, s.last ? fmtChecked(s.last) : '—')
                            );
                        }))
                    )
                )
            ),
            React.createElement('div', { style: { fontSize: 12, color: '#64748b', background: '#f8fafc', border: '1px solid #eef2f6', borderRadius: 10, padding: '9px 13px' } },
                '✅ 수집은 「플레이스 순위 추적기」 확장이 설치된 추적 PC(24시간 크롬)가 매일 아침 자동으로 수행합니다. ',
                '확장이 없는 PC에서도 등록만 해두면 됩니다 — 추적 PC가 수집 직전 최신 등록 목록을 자동으로 받아 갑니다. ',
                '순위 기준은 광고를 제외한 지도(플레이스) 오가닉 순위이며, 수동 「📍 플레이스 분석」 기록과 같은 이력에 이어집니다.')
        );
    }

    // ==================== 상세(키워드 보드) — 쇼핑 순위 추적 renderDetail 미러 ====================
    function renderDetail() {
        var g = groupOf(selected);
        var items = (g && g.items) ? g.items.slice() : [];
        items.sort(function (a, b) {
            if (boardSort === 'delta') return Math.abs((b.delta == null ? 0 : b.delta)) - Math.abs((a.delta == null ? 0 : a.delta));
            if (boardSort === 'name') return String(a.keyword).localeCompare(String(b.keyword), 'ko');
            var ar = (a.last && a.last.rank != null) ? a.last.rank : null;
            var br = (b.last && b.last.rank != null) ? b.last.rank : null;
            return (ar == null) - (br == null) || (ar || 0) - (br || 0);
        });
        var s = (g && g.sum) || { keywords: 0, exposed: 0, top10: 0, up: 0, down: 0 };
        return React.createElement(React.Fragment, null,
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14, flexWrap: 'wrap' } },
                React.createElement('button', {
                    onClick: function () { setSelected(null); setExpandedKw(null); setDKwInput(''); setDKwMsg(null); },
                    style: { border: '1px solid #e2e8f0', background: '#fff', color: '#475569', borderRadius: 10, padding: '7px 14px', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }
                }, '← 업체 목록'),
                React.createElement('h2', { style: { margin: 0, fontSize: 19, fontWeight: 800, color: '#0f172a' } }, '📍 ' + ((selected && selected.name) || '')),
                React.createElement('span', { style: { fontSize: 12.5, color: '#94a3b8', fontWeight: 600 } }, (selected && selected.region) || ''),
                (selected && selected.place_id) && React.createElement('a', {
                    href: 'https://map.naver.com/p/entry/place/' + selected.place_id, target: '_blank', rel: 'noopener noreferrer',
                    style: { fontSize: 12, color: '#3b82f6', fontWeight: 600, textDecoration: 'none' }
                }, '지도 열기 ↗')
            ),
            React.createElement('div', { style: _krKpiGrid },
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '추적 키워드'),
                    React.createElement('div', { style: _krKpiV }, s.keywords)),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '노출 중'),
                    React.createElement('div', { style: _krKpiV }, s.exposed),
                    React.createElement('div', { style: _krKpiS }, '지도 검색 노출')),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, 'TOP 10'),
                    React.createElement('div', { style: _krKpiV }, s.top10)),
                React.createElement('div', { style: _krKpi },
                    React.createElement('div', { style: _krKpiK }, '상승 / 하락'),
                    React.createElement('div', { style: _krKpiV },
                        React.createElement('span', { style: { color: '#dc2626' } }, '▲' + s.up),
                        React.createElement('span', { style: { color: '#cbd5e1', margin: '0 5px', fontSize: 16 } }, '/'),
                        React.createElement('span', { style: { color: '#2563eb' } }, '▼' + s.down)),
                    React.createElement('div', { style: _krKpiS }, '전일 대비'))
            ),
            React.createElement('div', { style: _krCard },
                /* 추적 키워드 추가 등록 — 쇼핑 순위 추적 상세와 동일 배치(관리팀만) */
                !isViewer && React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10, padding: '10px 12px', background: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: 10 } },
                    React.createElement('span', { style: { fontSize: 12.5, fontWeight: 700, color: '#475569' } }, '＋ 추적 키워드 등록'),
                    React.createElement('input', {
                        value: dKwInput, disabled: dKwBusy,
                        onChange: function (e) { setDKwInput(e.target.value); },
                        onKeyDown: function (e) { if (e.key === 'Enter' && !e.nativeEvent.isComposing) submitDetailKeyword(g); },
                        placeholder: '예: 칼국수 (Enter)',
                        style: { flex: '1 1 180px', maxWidth: 260, padding: '7px 12px', border: '1px solid #e2e8f0', borderRadius: 9, fontSize: 13, outline: 'none' }
                    }),
                    React.createElement('button', {
                        onClick: function () { submitDetailKeyword(g); }, disabled: dKwBusy || !dKwInput.trim(),
                        style: { border: 'none', background: (dKwBusy || !dKwInput.trim()) ? '#93c5fd' : '#3b82f6', color: '#fff', borderRadius: 9, padding: '7px 16px', fontSize: 12.5, fontWeight: 700, cursor: (dKwBusy || !dKwInput.trim()) ? 'default' : 'pointer' }
                    }, dKwBusy ? '등록 중…' : '등록'),
                    dKwInput.trim() && React.createElement('span', { style: { fontSize: 11.5, color: '#1d4ed8', fontWeight: 600, flexBasis: '100%' } },
                        '🔍 이렇게 저장됩니다: ' + placeCombineKeyword((selected && selected.region) || '', dKwInput.trim())),
                    dKwMsg && React.createElement('span', { style: { fontSize: 12, fontWeight: 600, color: dKwMsg.ok ? '#16a34a' : '#dc2626', flexBasis: '100%' } }, dKwMsg.text)
                ),
                React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 } },
                    React.createElement('select', {
                        value: boardSort, onChange: function (e) { setBoardSort(e.target.value); },
                        style: { border: '1px solid #e2e8f0', borderRadius: 9, padding: '7px 11px', fontSize: 12.5, fontWeight: 600, color: '#475569', background: '#fff' }
                    },
                        React.createElement('option', { value: 'rank' }, '정렬: 순위순'),
                        React.createElement('option', { value: 'delta' }, '변동 큰 순'),
                        React.createElement('option', { value: 'name' }, '가나다순')),
                    React.createElement('span', { style: { fontSize: 12, color: '#94a3b8', marginLeft: 'auto' } }, '추이·전일 대비는 매일 아침 자동 수집 기준')
                ),
                items.length === 0 ? React.createElement('div', { style: { padding: '40px 0', textAlign: 'center', color: '#94a3b8', fontSize: 13 } },
                    '추적 키워드가 없습니다.' + (isViewer ? '' : ' 위 「＋ 추적 키워드 등록」에 키워드를 넣으면 다음 자동 수집부터 기록됩니다.')) :
                React.createElement('div', { style: { overflowX: 'auto' } },
                    React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
                        React.createElement('thead', null, React.createElement('tr', null,
                            React.createElement('th', { style: _krTh }, '키워드'),
                            React.createElement('th', { style: Object.assign({}, _krTh, { textAlign: 'right' }) }, '현재 순위'),
                            React.createElement('th', { style: _krTh }, '전일 대비'),
                            React.createElement('th', { style: _krTh }, '최근 7일'),
                            React.createElement('th', { style: _krTh }, '상태'),
                            React.createElement('th', { style: _krTh }, '확인 시각'),
                            React.createElement('th', { style: _krTh }, '이미지'),
                            React.createElement('th', { style: _krTh }, isViewer ? '' : '관리')
                        )),
                        React.createElement('tbody', null, items.map(function (t) {
                            var open = expandedKw === keyOf(t);
                            var exposed = !!(t.last && t.last.state === '노출' && t.last.rank != null);
                            var d = _krDelta(t.delta == null ? ((t.last && t.last.rank != null) ? undefined : 0) : t.delta);
                            var stChip = !t.last
                                ? React.createElement('span', { style: _krChip('info') }, '대기')
                                : t.last.state === '노출'
                                    ? React.createElement('span', { style: _krChip('ok') }, '노출')
                                    : t.last.state === '미노출'
                                        ? React.createElement('span', { style: _krChip('warn') }, '미노출')
                                        : React.createElement('span', { style: _krChip('mute') }, '미확인');
                            var mainRow = React.createElement('tr', {
                                key: keyOf(t),
                                onClick: function () { toggleKw(t); },
                                style: { cursor: 'pointer', background: open ? '#f8fafc' : 'transparent', opacity: t.active ? 1 : 0.45 },
                                onMouseEnter: function (e) { e.currentTarget.style.background = '#f8fafc'; },
                                onMouseLeave: function (e) { e.currentTarget.style.background = open ? '#f8fafc' : 'transparent'; }
                            },
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontWeight: 700, color: '#0f172a' }) },
                                    React.createElement('span', { style: { color: '#94a3b8', fontSize: 10, marginRight: 7 } }, open ? '▼' : '▶'),
                                    t.keyword,
                                    !t.active && React.createElement('span', { style: Object.assign({}, _krChip('mute'), { marginLeft: 6 }) }, '⏸ 일시중지')),
                                React.createElement('td', { style: Object.assign({}, _krTd, { textAlign: 'right' }) }, rankCellOf(t)),
                                React.createElement('td', { style: _krTd },
                                    exposed && t.delta != null
                                        ? React.createElement('span', { style: d.style }, d.label)
                                        : React.createElement('span', { style: { fontSize: 11.5, color: '#cbd5e1' } }, '—')),
                                React.createElement('td', { style: _krTd }, _krSparkline(t.series)),
                                React.createElement('td', { style: _krTd }, stChip),
                                React.createElement('td', { style: Object.assign({}, _krTd, { fontSize: 12, color: '#94a3b8', whiteSpace: 'nowrap' }) },
                                    t.last ? fmtChecked(t.last.checked_at) : '—'),
                                React.createElement('td', { style: Object.assign({}, _krTd, { whiteSpace: 'nowrap' }) },
                                    React.createElement('button', {
                                        onClick: function (e) { e.stopPropagation(); if (!open) toggleKw(t); else setExpandedKw(null); },
                                        title: '순위 추이 그래프 + 이미지(PNG) 저장',
                                        style: { fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 14, cursor: 'pointer', border: '1px solid #16a34a', background: '#f0fdf4', color: '#16a34a' }
                                    }, open ? '▴ 접기' : '📸 그래프·저장')),
                                React.createElement('td', { style: Object.assign({}, _krTd, { whiteSpace: 'nowrap' }) },
                                    isViewer ? null : React.createElement(React.Fragment, null,
                                        React.createElement('button', {
                                            onClick: function (e) { e.stopPropagation(); toggleActive(t); },
                                            title: t.active ? '일시중지 — 자동 수집에서 제외' : '재개',
                                            style: { fontSize: 11, fontWeight: 700, padding: '3px 9px', borderRadius: 14, cursor: 'pointer', border: '1px solid #e2e8f0', background: '#fff', color: '#475569', marginRight: 4 }
                                        }, t.active ? '⏸' : '▶'),
                                        React.createElement('button', {
                                            onClick: function (e) { e.stopPropagation(); removeTarget(t); },
                                            title: '추적 삭제(이력은 보존)',
                                            style: { fontSize: 11, fontWeight: 700, padding: '3px 9px', borderRadius: 14, cursor: 'pointer', border: '1px solid #fecaca', background: '#fff', color: '#dc2626' }
                                        }, '✕')))
                            );
                            return open
                                ? React.createElement(React.Fragment, { key: keyOf(t) + '::grp' }, mainRow, renderKwPanel(g, t))
                                : mainRow;
                        }))
                    )
                )
            )
        );
    }

    // ==================== 최종 렌더 — 쇼핑 순위 추적과 같은 페이지 골격 ====================
    return React.createElement('div', { style: _krWrap },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, flexWrap: 'wrap' } },
            React.createElement('h1', { style: { margin: 0, fontSize: 21, fontWeight: 800, color: '#0f172a', letterSpacing: '-.02em' } }, '📍 지도 순위 추적'),
            React.createElement('span', { style: { fontSize: 12.5, color: '#94a3b8' } },
                selected ? '업체 상세 — 키워드별 추적 현황' : '업체별 지도(플레이스) 순위 추적 현황 · 매일 아침 자동 수집'),
            React.createElement('span', { style: { marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
                isViewer
                    ? React.createElement('span', {
                        style: { fontSize: 11.5, fontWeight: 700, borderRadius: 999, padding: '3px 10px',
                                 background: '#f1f5f9', border: '1px solid #e2e8f0', color: '#64748b' }
                    }, '👁 열람 전용 (등록·관리는 관리팀)')
                    : React.createElement(React.Fragment, null,
                        React.createElement('span', {
                            style: { fontSize: 11.5, fontWeight: 700, borderRadius: 999, padding: '3px 10px',
                                     background: extReady ? '#dcfce7' : '#f1f5f9',
                                     border: '1px solid ' + (extReady ? '#bbf7d0' : '#e2e8f0'),
                                     color: extReady ? '#059669' : '#94a3b8' }
                        }, extReady ? '🧩 이 브라우저 추적기 연동됨' : '🧩 이 브라우저엔 추적기 없음'),
                        React.createElement('button', {
                            onClick: requestRunNow,
                            style: { border: 'none', background: '#3b82f6', color: '#fff', borderRadius: 9, padding: '7px 14px', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }
                        }, '⟳ 지금 수집')))),
        selected ? renderDetail() : renderList()
    );
};
