/* PlaceTrackingPage — 로직분석 「플레이스 추적」 전용 탭 (무인 순위 추적, v1)
 *
 * 확정 시안(2026-08-04 v2, Artifact 790e1710) 기준:
 *  - 추적 대상 등록: 업체명·지역·키워드(최대 10, 지역 자동 합성 — 맞춤제안서와 동일 규칙)
 *  - 추적 현황: 노출/미노출/미확인 필, (업체×키워드) 표, 행 클릭 → 순위 추이(PlaceRankChart 재사용)
 *  - 수집은 「플레이스 순위 추적기」 확장(별개 설치)이 매일 06:30 무인 수행 → /api/place/ingest 기록
 *  - 이 화면은 확장에 추적 목록을 동기화(METAINC_PLACE_TARGETS)하고 즉시 수집(METAINC_PLACE_RUN)을 요청
 *
 * 스파이크 실측(2026-08-04): 키워드에 지역이 포함되면 오가닉 순위는 검색 위치와 무관하게 재현
 *  → 등록 시 지역 합성이 재현성의 핵심(좌표 고정 불필요).
 * 스타일: css/place.css(.place-analysis 스코프) 재사용. */
window.PlaceTrackingPage = function PlaceTrackingPage(props) {
    var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;

    // ── 목록 상태 ──
    var _t = useState([]);        var targets = _t[0], setTargets = _t[1];
    var _ld = useState(false);    var loading = _ld[0], setLoading = _ld[1];

    // ── 등록 폼 ──
    var _n = useState('');        var bizName = _n[0], setBizName = _n[1];
    var _r = useState('');        var region = _r[0], setRegion = _r[1];
    var _ki = useState('');       var kwInput = _ki[0], setKwInput = _ki[1];
    var _ks = useState([]);       var kws = _ks[0], setKws = _ks[1];
    var _sv = useState(false);    var saving = _sv[0], setSaving = _sv[1];

    // ── 확장 연동 상태 ──
    var _ex = useState(false);    var extReady = _ex[0], setExtReady = _ex[1];

    // ── 행 펼침 차트 ──
    var _open = useState('');     var openKey = _open[0], setOpenKey = _open[1];   // 'bk||keyword'
    var _cs = useState([]);       var chartSeries = _cs[0], setChartSeries = _cs[1];
    var _cd = useState(30);       var chartDays = _cd[0], setChartDays = _cd[1];

    var targetsRef = useRef([]);
    targetsRef.current = targets;

    // ==================== 확장 브리지 ====================
    function pushTargetsToExt(list) {
        try {
            var actives = (list || targetsRef.current).filter(function (t) { return t.active; })
                .map(function (t) {
                    return { id: t.id, business_name: t.business_name, region: t.region,
                             place_id: t.place_id || '', keyword: t.keyword };
                });
            window.postMessage({ type: 'METAINC_PLACE_TARGETS', payload: { targets: actives } }, window.location.origin);
        } catch (e) {}
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
        else toast.warn('이 브라우저에 「플레이스 순위 추적기」 확장이 없습니다 — 추적 PC(맥북)에서는 매일 06:30 자동 수집됩니다.');
    }

    // ==================== 데이터 ====================
    function load() {
        setLoading(true);
        api.get('/place/track-targets').then(function (res) {
            setLoading(false);
            if (res && res.success) {
                var list = (res.data && res.data.targets) || [];
                setTargets(list);
                pushTargetsToExt(list);
            }
        }).catch(function () { setLoading(false); });
    }
    useEffect(function () { load(); }, []);

    // ==================== 등록 폼 ====================
    function combinedPreview(kw) {
        var reg = (region || '').trim();
        if (!reg) return kw;
        var norm = function (s) { return String(s).toLowerCase().replace(/\s+/g, ''); };
        return norm(kw).indexOf(norm(reg)) >= 0 ? kw : (reg + ' ' + kw);
    }
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
        setSaving(true);
        api.post('/place/track-targets', { business_name: name, region: reg, keywords: list })
            .then(function (res) {
                setSaving(false);
                if (res && res.success) {
                    toast.success('✅ 추적 등록: ' + name + ' · 키워드 ' + ((res.data && res.data.added) || 0) + '개 — 다음 자동 수집부터 기록됩니다.');
                    setBizName(''); setRegion(''); setKws([]); setKwInput('');
                    load();
                } else {
                    toast.error((res && res.error) || '등록에 실패했습니다.');
                }
            }).catch(function () { setSaving(false); });
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
    function toggleChart(t) {
        var key = (t.business_key || '') + '||' + t.keyword;
        if (openKey === key) { setOpenKey(''); return; }
        setOpenKey(key);
        loadSeries(t, chartDays);
    }
    function loadSeries(t, days) {
        if (!t.business_key) { setChartSeries([]); return; }
        api.get('/place/rank-history?business=' + encodeURIComponent(t.business_key)
            + '&keyword=' + encodeURIComponent(t.keyword) + '&days=' + days)
            .then(function (res) {
                if (res && res.success) setChartSeries((res.data && res.data.series) || []);
            });
    }

    // ==================== 렌더 ====================
    var pills = { exposed: 0, missing: 0, unknown: 0, none: 0 };
    targets.forEach(function (t) {
        if (!t.last) pills.none++;
        else if (t.last.state === '노출') pills.exposed++;
        else if (t.last.state === '미노출') pills.missing++;
        else pills.unknown++;
    });

    // 업체 그룹(연속 표시용): business_key 기준 첫 행에만 업체명 표시
    var seenBiz = {};

    function rankCell(t) {
        if (!t.last || t.last.rank == null) {
            return React.createElement('span', { style: { color: '#94a3b8', fontWeight: 800 } },
                t.last && t.last.state === '미노출' ? '–' : '?');
        }
        var r = t.last.rank;
        var col = r <= 10 ? '#059669' : (r <= 30 ? '#d97706' : '#dc2626');
        return React.createElement('span', null,
            React.createElement('span', { style: { fontFamily: 'SF Mono,JetBrains Mono,monospace', fontWeight: 800, fontSize: 15, color: col } }, r),
            React.createElement('span', { style: { color: '#94a3b8', fontSize: 11 } }, '위'));
    }
    function stateChip(t) {
        var st = t.last ? t.last.state : null;
        var cls = st === '노출' ? 'kwchip' : (st === '미노출' ? 'kwchip off' : 'kwchip unk');
        var label = st || '이력 없음';
        return React.createElement('span', { className: cls, style: { cursor: 'default' } }, label);
    }
    function fmtDate(s) {
        if (!s) return '-';
        return String(s).slice(5, 10).replace('-', '.');
    }

    var rows = [];
    targets.forEach(function (t) {
        var bizKey = (t.business_name || '') + '|' + (t.region || '');
        var first = !seenBiz[bizKey];
        seenBiz[bizKey] = 1;
        var key = (t.business_key || '') + '||' + t.keyword;
        rows.push(React.createElement('tr', {
            key: 'r' + t.id,
            onClick: function () { toggleChart(t); },
            style: { cursor: 'pointer', opacity: t.active ? 1 : 0.45 }
        },
            React.createElement('td', null, first
                ? React.createElement('span', null,
                    React.createElement('b', null, t.business_name),
                    React.createElement('span', { style: { display: 'block', color: '#94a3b8', fontSize: 11.5 } },
                        (t.region || '') + (t.place_id ? ' · ID ' + t.place_id : '')))
                : React.createElement('span', { style: { color: '#cbd5e1' } }, '〃')),
            React.createElement('td', { style: { fontFamily: 'SF Mono,JetBrains Mono,monospace', fontSize: 12.5, color: '#334155' } }, t.keyword),
            React.createElement('td', { style: { textAlign: 'center' } }, rankCell(t)),
            React.createElement('td', { style: { textAlign: 'center' } }, stateChip(t)),
            React.createElement('td', { style: { textAlign: 'center', color: '#64748b', fontFamily: 'SF Mono,monospace', fontSize: 12 } },
                t.last ? fmtDate(t.last.checked_at) : '-'),
            React.createElement('td', { style: { textAlign: 'center', whiteSpace: 'nowrap' } },
                React.createElement('button', {
                    className: 'btn btn-secondary btn-sm',
                    onClick: function (e) { e.stopPropagation(); toggleActive(t); },
                    title: t.active ? '일시중지 — 자동 수집에서 제외' : '재개'
                }, t.active ? '⏸' : '▶'),
                React.createElement('button', {
                    className: 'btn btn-secondary btn-sm',
                    style: { marginLeft: 6 },
                    onClick: function (e) { e.stopPropagation(); removeTarget(t); }
                }, '✕'))
        ));
        if (openKey === key) {
            rows.push(React.createElement('tr', { key: 'x' + t.id },
                React.createElement('td', { colSpan: 6, style: { background: '#faf9ff' } },
                    React.createElement('div', { className: 'subcard', style: { margin: '6px 0' } },
                        window.PlaceRankChart
                            ? React.createElement(window.PlaceRankChart, {
                                series: chartSeries, keyword: t.keyword, days: chartDays,
                                onDays: function (d) { setChartDays(d); loadSeries(t, d); }
                            })
                            : React.createElement('div', { className: 'empty' }, '차트 컴포넌트를 불러올 수 없습니다.'))
                )));
        }
    });

    var kwChipsEls = kws.map(function (k, i) {
        return React.createElement('span', {
            key: k, className: 'kwchip cur',
            style: { margin: '2px 4px 2px 0', cursor: 'pointer' },
            title: '분석 키워드: ' + combinedPreview(k) + ' (클릭 시 제거)',
            onClick: function () { setKws(kws.filter(function (_, j) { return j !== i; })); }
        }, combinedPreview(k) + ' ✕');
    });

    return React.createElement('div', { className: 'place-analysis' },
        React.createElement('div', { className: 'pa-wrap', style: { maxWidth: 1180, margin: '0 auto', padding: '18px 16px 60px' } },

            // ── 헤더 ──
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10, margin: '4px 0 12px' } },
                React.createElement('div', null,
                    React.createElement('h2', { style: { margin: 0, fontSize: 19 } }, '📊 플레이스 추적'),
                    React.createElement('div', { style: { color: '#64748b', fontSize: 12.5, marginTop: 2 } },
                        '등록한 업체×키워드를 추적 PC가 매일 06:30 무인 수집 → 순위 이력 자동 기록')),
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
                    React.createElement('span', {
                        style: { fontSize: 11.5, fontWeight: 700, borderRadius: 999, padding: '3px 10px',
                                 background: extReady ? '#dcfce7' : '#f1f5f9',
                                 border: '1px solid ' + (extReady ? '#bbf7d0' : '#e2e8f0'),
                                 color: extReady ? '#059669' : '#94a3b8' }
                    }, extReady ? '🧩 이 브라우저 추적기 연동됨' : '🧩 이 브라우저엔 추적기 없음'),
                    React.createElement('button', { className: 'btn btn-primary btn-sm', onClick: requestRunNow }, '⟳ 지금 수집'))),

            // ── 등록 카드 ──
            React.createElement('div', { className: 'card', style: { marginBottom: 14 } },
                React.createElement('div', { style: { fontWeight: 800, fontSize: 14.5, marginBottom: 10 } }, '➕ 추적 대상 등록'),
                React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(160px,1.2fr) minmax(120px,0.9fr) minmax(220px,2fr) auto', gap: 10, alignItems: 'end' } },
                    React.createElement('div', null,
                        React.createElement('label', { style: { display: 'block', fontSize: 11.5, fontWeight: 700, color: '#64748b', marginBottom: 4 } }, '업체명 *'),
                        React.createElement('input', { type: 'text', value: bizName, placeholder: '예: 성수동 감성카페',
                            onChange: function (e) { setBizName(e.target.value); },
                            style: { width: '100%', boxSizing: 'border-box', border: '1px solid #e2e8f0', borderRadius: 9, padding: '8px 10px', fontSize: 13 } })),
                    React.createElement('div', null,
                        React.createElement('label', { style: { display: 'block', fontSize: 11.5, fontWeight: 700, color: '#64748b', marginBottom: 4 } }, '지역 *'),
                        React.createElement('input', { type: 'text', value: region, placeholder: '예: 성수동',
                            onChange: function (e) { setRegion(e.target.value); },
                            style: { width: '100%', boxSizing: 'border-box', border: '1px solid #e2e8f0', borderRadius: 9, padding: '8px 10px', fontSize: 13 } })),
                    React.createElement('div', null,
                        React.createElement('label', { style: { display: 'block', fontSize: 11.5, fontWeight: 700, color: '#64748b', marginBottom: 4 } },
                            '추적 키워드 (Enter로 추가 · 최대 10)'),
                        React.createElement('div', { style: { border: '1px solid #e2e8f0', borderRadius: 9, padding: '4px 8px', background: '#fbfcfe', display: 'flex', flexWrap: 'wrap', alignItems: 'center', minHeight: 36 } },
                            kwChipsEls,
                            React.createElement('input', { type: 'text', value: kwInput, placeholder: kws.length ? '' : '예: 카페, 브런치',
                                onChange: function (e) { setKwInput(e.target.value); },
                                onKeyDown: onKwKey,
                                style: { flex: 1, minWidth: 90, border: 0, outline: 'none', background: 'transparent', fontSize: 13, padding: '4px 2px' } }))),
                    React.createElement('button', { className: 'btn btn-primary', onClick: submit, disabled: saving }, saving ? '등록 중…' : '등록')),
                React.createElement('div', { className: 'note est', style: { marginTop: 10 } },
                    'ℹ️ 키워드는 자동으로 「지역 + 키워드」로 저장됩니다(예: 성수동 + 카페 → 성수동 카페). 지역이 포함된 키워드는 검색 위치와 무관하게 순위가 재현됩니다(실측 검증).')),

            // ── 현황 필 ──
            React.createElement('div', { className: 'pills', style: { margin: '2px 0 10px' } },
                React.createElement('span', { className: 'ps ps-g' }, '노출 ' + pills.exposed),
                React.createElement('span', { className: 'ps ps-r' }, '미노출 ' + pills.missing),
                React.createElement('span', { className: 'ps ps-n' }, '미확인 ' + pills.unknown + (pills.none ? ' · 이력 없음 ' + pills.none : ''))),

            // ── 목록 ──
            React.createElement('div', { className: 'card' },
                loading
                    ? React.createElement('div', { className: 'empty' }, '불러오는 중…')
                    : (targets.length === 0
                        ? React.createElement('div', { className: 'empty' }, '아직 추적 대상이 없습니다 — 위에서 업체와 키워드를 등록하면 다음 자동 수집(매일 06:30)부터 순위가 기록됩니다.')
                        : React.createElement('div', { className: 'twrap' },
                            React.createElement('table', { style: { minWidth: 720 } },
                                React.createElement('thead', null, React.createElement('tr', null,
                                    React.createElement('th', { style: { width: 190 } }, '업체'),
                                    React.createElement('th', null, '키워드'),
                                    React.createElement('th', { style: { textAlign: 'center', width: 90 } }, '최근 순위'),
                                    React.createElement('th', { style: { textAlign: 'center', width: 90 } }, '상태'),
                                    React.createElement('th', { style: { textAlign: 'center', width: 90 } }, '최근 수집'),
                                    React.createElement('th', { style: { textAlign: 'center', width: 110 } }, '관리'))),
                                React.createElement('tbody', null, rows))))),

            // ── 안내 ──
            React.createElement('div', { className: 'note ok', style: { marginTop: 12 } },
                '✅ 수집은 「플레이스 순위 추적기」 확장이 설치된 추적 PC(24시간 크롬)가 매일 06:30 자동으로 수행합니다. ',
                '행을 클릭하면 일자별 순위 추이를 볼 수 있고, 수동 「📍 플레이스 분석」과 같은 이력에 이어집니다.')
        )
    );
};
