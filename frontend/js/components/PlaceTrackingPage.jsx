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

    // 사용 범주 = 스토어 순위 추적과 동일(2026-08-04 대표 확정):
    // 영업사원(viewer)은 열람만(등록·삭제·일시중지·지금 수집 불가), 관리팀·관리자는 전체 가능. 서버 게이트와 이중.
    var currentUser = props.currentUser;
    var isViewer = !!(currentUser && currentUser.role === 'viewer');

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

    var _pid = useState('');      var placeIdInput = _pid[0], setPlaceIdInput = _pid[1];

    // 플레이스 링크/ID → 숫자 ID 추출 (지도 주소 어느 형식이든: .../place/12345, m.place.naver.com/restaurant/12345/..., 숫자 단독)
    function extractPlaceId(v) {
        v = String(v || '').trim();
        if (!v) return '';
        if (/^\d{5,}$/.test(v)) return v;
        var m = v.match(/(?:place|restaurant|cafe|hairshop|hospital|accommodation|attraction)\/(\d{5,})/);
        if (m) return m[1];
        m = v.match(/(\d{7,})/);
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
                pushTargetsToExt();
            }
        }).catch(function () { setLoading(false); });
    }
    useEffect(function () { load(); }, []);

    // ==================== 등록 폼 ====================
    // ⚠️ 합성 규칙은 utils.js `placeCombineKeyword` 하나만 쓴다(서버 규칙과 1:1).
    //    종전엔 여기서 따로 계산해 '미사동'+'미사리맛집' → '미사동 미사리맛집' 을 미리보기가
    //    그대로 보여줬다(2026-08-11 직원 신고). 규칙을 두 벌 두면 반드시 어긋난다.
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

    // 업체별 그룹(카드형) — 스토어 분석과 같은 개념: 업체 카드 안에 그 업체의 키워드·순위가 모임
    var bizGroups = [];
    var bizIdx = {};
    targets.forEach(function (t) {
        var gk = (t.business_name || '') + '|' + (t.region || '');
        if (bizIdx[gk] === undefined) {
            bizIdx[gk] = bizGroups.length;
            bizGroups.push({ name: t.business_name, region: t.region, place_id: t.place_id || '', items: [] });
        }
        var g = bizGroups[bizIdx[gk]];
        if (!g.place_id && t.place_id) g.place_id = t.place_id;
        g.items.push(t);
    });
    function bizSummary(g) {
        var s = { exposed: 0, missing: 0, wait: 0, best: null };
        g.items.forEach(function (t) {
            if (!t.last) s.wait++;
            else if (t.last.state === '노출') {
                s.exposed++;
                if (t.last.rank != null && (s.best === null || t.last.rank < s.best)) s.best = t.last.rank;
            }
            else if (t.last.state === '미노출') s.missing++;
            else s.wait++;
        });
        return s;
    }

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

    var bizCards = bizGroups.map(function (g, gi) {
        var s = bizSummary(g);
        var rowEls = [];
        g.items.forEach(function (t) {
            var key = (t.business_key || '') + '||' + t.keyword;
            rowEls.push(React.createElement('div', {
                key: 'r' + t.id,
                onClick: function () { toggleChart(t); },
                style: { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 2px',
                         borderTop: '1px solid #f1f5f9', cursor: 'pointer', opacity: t.active ? 1 : 0.45 }
            },
                React.createElement('span', { title: t.keyword,
                    style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                             fontFamily: 'SF Mono,JetBrains Mono,monospace', fontSize: 12.5, color: '#334155' } }, t.keyword),
                React.createElement('span', { style: { width: 52, textAlign: 'right', flexShrink: 0 } }, rankCell(t)),
                React.createElement('span', { style: { flexShrink: 0 } }, stateChip(t)),
                React.createElement('span', { style: { width: 42, textAlign: 'center', flexShrink: 0, color: '#94a3b8', fontFamily: 'SF Mono,monospace', fontSize: 11.5 } },
                    t.last ? fmtDate(t.last.checked_at) : '-'),
                isViewer ? null : React.createElement('button', {
                    className: 'btn btn-secondary btn-sm', style: { flexShrink: 0 },
                    onClick: function (e) { e.stopPropagation(); toggleActive(t); },
                    title: t.active ? '일시중지 — 자동 수집에서 제외' : '재개'
                }, t.active ? '⏸' : '▶'),
                isViewer ? null : React.createElement('button', {
                    className: 'btn btn-secondary btn-sm', style: { flexShrink: 0 },
                    onClick: function (e) { e.stopPropagation(); removeTarget(t); }
                }, '✕')
            ));
            if (openKey === key) {
                rowEls.push(React.createElement('div', { key: 'x' + t.id, className: 'subcard', style: { margin: '4px 0 8px' } },
                    window.PlaceRankChart
                        ? React.createElement(window.PlaceRankChart, {
                            series: chartSeries, keyword: t.keyword, days: chartDays,
                            businessName: t.business_name,
                            placeUrl: t.place_id ? 'https://map.naver.com/p/entry/place/' + t.place_id : '',
                            onDays: function (d) { setChartDays(d); loadSeries(t, d); }
                        })
                        : React.createElement('div', { className: 'empty' }, '차트 컴포넌트를 불러올 수 없습니다.')));
            }
        });
        return React.createElement('div', { key: 'g' + gi, className: 'card', style: { padding: '14px 16px', alignSelf: 'start' } },
            React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', marginBottom: 8 } },
                React.createElement('div', { style: { minWidth: 0 } },
                    React.createElement('div', { style: { fontWeight: 800, fontSize: 15, color: '#0f172a' } }, '📍 ' + (g.name || '')),
                    React.createElement('div', { style: { color: '#94a3b8', fontSize: 11.5, marginTop: 1 } },
                        (g.region || '') + (g.place_id ? ' · ID ' + g.place_id : ''))),
                React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' } },
                    s.best != null ? React.createElement('span', { style: { fontSize: 12.5, fontWeight: 800, color: '#059669' } }, '최고 ' + s.best + '위') : null,
                    React.createElement('span', { className: 'ps ps-g', style: { fontSize: 11 } }, '노출 ' + s.exposed),
                    React.createElement('span', { className: 'ps ps-r', style: { fontSize: 11 } }, '미노출 ' + s.missing),
                    s.wait ? React.createElement('span', { className: 'ps ps-n', style: { fontSize: 11 } }, '대기 ' + s.wait) : null)),
            rowEls);
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
                isViewer
                    ? React.createElement('span', {
                        style: { fontSize: 11.5, fontWeight: 700, borderRadius: 999, padding: '3px 10px',
                                 background: '#f1f5f9', border: '1px solid #e2e8f0', color: '#64748b' }
                    }, '👁 열람 전용 (등록·관리는 관리팀)')
                    : React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
                        React.createElement('span', {
                            style: { fontSize: 11.5, fontWeight: 700, borderRadius: 999, padding: '3px 10px',
                                     background: extReady ? '#dcfce7' : '#f1f5f9',
                                     border: '1px solid ' + (extReady ? '#bbf7d0' : '#e2e8f0'),
                                     color: extReady ? '#059669' : '#94a3b8' }
                        }, extReady ? '🧩 이 브라우저 추적기 연동됨' : '🧩 이 브라우저엔 추적기 없음'),
                        React.createElement('button', { className: 'btn btn-primary btn-sm', onClick: requestRunNow }, '⟳ 지금 수집'))),

            // ── 등록 카드 (영업사원은 안내로 대체 — 스토어 순위 추적과 동일 범주) ──
            isViewer
                ? React.createElement('div', { className: 'note est', style: { marginBottom: 14 } },
                    '🔒 플레이스 순위 추적 등록·관리는 관리팀 권한입니다(스토어 순위 추적과 동일 기준). ',
                    '영업 대상 분석은 「📍 플레이스 분석」 탭에서 자유롭게 사용할 수 있습니다. 추적이 필요한 업체는 관리팀에 요청해주세요.')
                : React.createElement('div', { className: 'card', style: { marginBottom: 14 } },
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
                React.createElement('div', { style: { marginTop: 10 } },
                    React.createElement('label', { style: { display: 'block', fontSize: 11.5, fontWeight: 700, color: '#64748b', marginBottom: 4 } },
                        '플레이스 링크 또는 ID (선택 — 넣으면 이름 대신 ID로 정확 매칭)'),
                    React.createElement('input', { type: 'text', value: placeIdInput,
                        placeholder: '예: https://m.place.naver.com/restaurant/1234567890 · 네이버 지도 업체 페이지 주소를 그대로 붙여넣으세요',
                        onChange: function (e) { setPlaceIdInput(e.target.value); },
                        style: { width: '100%', boxSizing: 'border-box', border: '1px solid #e2e8f0', borderRadius: 9, padding: '8px 10px', fontSize: 13 } }),
                    (placeIdInput || '').trim()
                        ? React.createElement('div', { style: { fontSize: 11.5, marginTop: 4, fontWeight: 700,
                            color: extractPlaceId(placeIdInput) ? '#059669' : '#dc2626' } },
                            extractPlaceId(placeIdInput)
                                ? '✓ 인식된 플레이스 ID: ' + extractPlaceId(placeIdInput)
                                : '✕ ID를 인식하지 못했습니다 — 지도 업체 페이지 주소 또는 숫자 ID를 넣어주세요')
                        : null),
                React.createElement('div', { className: 'note est', style: { marginTop: 10 } },
                    'ℹ️ 키워드는 자동으로 「지역 + 키워드」로 저장됩니다(예: 성수동 + 카페 → 성수동 카페). 지역이 포함된 키워드는 검색 위치와 무관하게 순위가 재현됩니다(실측 검증). 플레이스 ID를 비워두면 업체명으로 찾고, 첫 노출 때 ID가 자동 저장됩니다.')),

            // ── 현황 필 ──
            React.createElement('div', { className: 'pills', style: { margin: '2px 0 10px' } },
                React.createElement('span', { className: 'ps ps-g' }, '노출 ' + pills.exposed),
                React.createElement('span', { className: 'ps ps-r' }, '미노출 ' + pills.missing),
                React.createElement('span', { className: 'ps ps-n' }, '미확인 ' + pills.unknown + (pills.none ? ' · 이력 없음 ' + pills.none : ''))),

            // ── 목록 (업체별 카드) ──
            loading
                ? React.createElement('div', { className: 'card' },
                    React.createElement('div', { className: 'empty' }, '불러오는 중…'))
                : (targets.length === 0
                    ? React.createElement('div', { className: 'card' },
                        React.createElement('div', { className: 'empty' }, '아직 추적 대상이 없습니다 — 위에서 업체와 키워드를 등록하면 다음 자동 수집(매일 06:30)부터 순위가 기록됩니다.'))
                    : React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 430px), 1fr))', gap: 12, alignItems: 'start' } }, bizCards)),

            // ── 안내 ──
            React.createElement('div', { className: 'note ok', style: { marginTop: 12 } },
                '✅ 수집은 「플레이스 순위 추적기」 확장이 설치된 추적 PC(24시간 크롬)가 매일 06:30 자동으로 수행합니다. ',
                '확장이 없는 PC에서도 등록만 해두면 됩니다 — 추적 PC가 수집 직전 최신 등록 목록을 자동으로 받아 갑니다. ',
                '키워드 행을 클릭하면 일자별 순위 추이를 볼 수 있고, 수동 「📍 플레이스 분석」과 같은 이력에 이어집니다.')
        )
    );
};
