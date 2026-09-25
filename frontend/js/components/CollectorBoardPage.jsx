/* CollectorBoardPage — 🛰 수집 현황판 (대표 지시 2026-09-25)
 *
 * 대표 원문: 「이게 잘 작동하는지도 확인하는, 그리고 매일 수집기 관련 데이터를 확인할 수 있는 별도의 페이지를
 * 만들어서 현황판으로 볼수 있게 개발하자. 매번 여기서 물어볼수 없어.」
 *
 * 서버 = GET /api/collector/board(로그인 · 읽기 전용 · 규칙은 backend/collector_board.py 한 곳).
 * 지금까지 진단 워크플로로 손으로 재던 것을 그대로 옮겼다:
 *   판정 줄(진짜 차단 · 기계 · 설정 · 미전송 · 나누기 · 순위 기록) → 오늘 숫자 → 시간대별 → 14일 추이
 *   → 기계 → 막힘 사유(진짜 차단과 진단 보고를 갈라서) → 멈춘 이유 → 순위 기록 → 순위 읽기 도우미.
 *
 * ⚠️ 못 잰 값(null)은 「미확인」으로 쓴다 — 0 으로 그리지 않는다(이 저장소 규칙).
 * ⚠️ 「막힘 보고」 숫자를 그대로 「차단」이라 쓰지 않는다(9/18 교훈) — 대부분이 진단 보고다.
 * 스타일 상수(_kr*)는 KeywordRankPage.jsx 것을 그대로 쓴다(번들 순서상 먼저 로드).
 */
var _cbLevel = {
    ok:      { bg: '#f0fdf4', bd: '#bbf7d0', fg: '#15803d', mark: '정상' },
    warn:    { bg: '#fffbeb', bd: '#fde68a', fg: '#b45309', mark: '확인' },
    bad:     { bg: '#fef2f2', bd: '#fecaca', fg: '#b91c1c', mark: '문제' },
    unknown: { bg: '#f8fafc', bd: '#e2e8f0', fg: '#64748b', mark: '미확인' }
};
var _CB_REFRESH_MS = 5 * 60 * 1000;

function _cbNum(v) { return (v === null || v === undefined) ? '미확인' : Number(v).toLocaleString('ko-KR'); }
function _cbAgo(min) {
    if (min === null || min === undefined) return '미확인';
    if (min < 1) return '방금';
    if (min < 60) return min + '분 전';
    if (min < 60 * 24) return Math.floor(min / 60) + '시간 전';
    return Math.floor(min / 1440) + '일 전';
}
function _cbSection(title, sub, body) {
    return React.createElement('div', { style: _krCard },
        React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12, flexWrap: 'wrap' } },
            React.createElement('div', { style: { fontSize: 15, fontWeight: 800, color: '#0f172a' } }, title),
            sub ? React.createElement('div', { style: { fontSize: 12, color: '#64748b' } }, sub) : null),
        body);
}
function _cbTable(heads, rows, empty) {
    if (!rows || !rows.length) return React.createElement('div', { style: { fontSize: 12.5, color: '#94a3b8', padding: '8px 2px' } }, empty || '없음');
    return React.createElement('div', { style: { overflowX: 'auto' } },
        React.createElement('table', { style: { width: '100%', borderCollapse: 'collapse' } },
            React.createElement('thead', null, React.createElement('tr', null,
                heads.map(function(h, i) { return React.createElement('th', { key: i, style: _krTh }, h); }))),
            React.createElement('tbody', null, rows.map(function(r, i) {
                return React.createElement('tr', { key: i }, r.map(function(c, j) {
                    return React.createElement('td', { key: j, style: Object.assign({}, _krTd, { fontVariantNumeric: 'tabular-nums' }) }, c);
                }));
            }))));
}

/* 막대 — 두 값(시도·완료)을 같은 축에. 최대값이 0 이면 빈 막대. */
function _cbBars(items, maxV, label) {
    var h = 96;
    return React.createElement('div', { style: { display: 'flex', alignItems: 'flex-end', gap: 3, height: h + 22, overflowX: 'auto' } },
        items.map(function(it, i) {
            var a = it.a === null || it.a === undefined ? null : it.a;
            var b = it.b === null || it.b === undefined ? null : it.b;
            var ha = maxV > 0 && a !== null ? Math.max(a ? 2 : 0, Math.round(a / maxV * h)) : 0;
            var hb = maxV > 0 && b !== null ? Math.max(b ? 2 : 0, Math.round(b / maxV * h)) : 0;
            return React.createElement('div', { key: i, title: it.title, style: { flex: '1 0 16px', minWidth: 16, display: 'flex', flexDirection: 'column', alignItems: 'center' } },
                React.createElement('div', { style: { position: 'relative', width: '100%', height: h } },
                    React.createElement('div', { style: { position: 'absolute', bottom: 0, left: '12%', right: '12%', height: ha, background: '#dbeafe', borderRadius: '3px 3px 0 0' } }),
                    React.createElement('div', { style: { position: 'absolute', bottom: 0, left: '30%', right: '30%', height: hb, background: '#3b82f6', borderRadius: '3px 3px 0 0' } }),
                    (a === null && b === null) ? React.createElement('div', { style: { position: 'absolute', bottom: 0, width: '100%', textAlign: 'center', fontSize: 10, color: '#cbd5e1' } }, '·') : null),
                React.createElement('div', { style: { fontSize: 10, color: it.hi ? '#0f172a' : '#94a3b8', fontWeight: it.hi ? 800 : 500, marginTop: 4, whiteSpace: 'nowrap' } }, it.label));
        }));
}
function _cbLegend(aName, bName) {
    var dot = function(c) { return { display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: c, marginRight: 4, verticalAlign: '-1px' }; };
    return React.createElement('div', { style: { fontSize: 11.5, color: '#64748b', marginTop: 6 } },
        React.createElement('span', { style: dot('#dbeafe') }), aName, '　',
        React.createElement('span', { style: dot('#3b82f6') }), bName);
}

window.CollectorBoardPage = function CollectorBoardPage(props) {
    var useState = React.useState, useEffect = React.useEffect, useCallback = React.useCallback;
    var currentUser = props.currentUser || {};
    var isViewer = currentUser.role !== 'superadmin';   // 대표 확정 「나만 보게 해」 — 최고관리자만

    // undefined = 불러오는 중 · null = 못 불러옴 · 객체 = 현황
    var _d = useState(undefined); var data = _d[0], setData = _d[1];
    var _e = useState(''); var err = _e[0], setErr = _e[1];
    var _l = useState(false); var loading = _l[0], setLoading = _l[1];
    var _o = useState(false); var showOld = _o[0], setShowOld = _o[1];

    var load = useCallback(function() {
        if (isViewer) return;
        setLoading(true);
        Promise.resolve().then(function() { return api.get('/collector/board'); }).then(function(res) {
            if (res && res.success) { setData(res); setErr(''); }
            else { setData(function(prev) { return prev === undefined ? null : prev; }); setErr((res && (res.detail || res.error)) || '현황을 불러오지 못했습니다.'); }
        }).catch(function(e) {
            setData(function(prev) { return prev === undefined ? null : prev; });
            setErr((e && e.message) || '현황을 불러오지 못했습니다.');
        }).then(function() { setLoading(false); });
    }, [isViewer]);

    useEffect(function() {
        load();
        var t = setInterval(load, _CB_REFRESH_MS);
        return function() { clearInterval(t); };
    }, [load]);

    var head = React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' } },
        React.createElement('div', { style: { flex: '1 1 auto' } },
            React.createElement('div', { style: { fontSize: 20, fontWeight: 800, color: '#0f172a', letterSpacing: '-.02em' } }, '🛰 수집 현황판'),
            React.createElement('div', { style: { fontSize: 12.5, color: '#64748b', marginTop: 2 } },
                '쇼핑 순위 수집기와 순위 읽기 도우미가 오늘 제대로 돌았는지 한 화면에서 봅니다. 5분마다 새로 불러옵니다.')),
        data ? React.createElement('div', { style: { fontSize: 12, color: '#64748b', textAlign: 'right' } },
            '기준일 ', React.createElement('b', { style: { color: '#0f172a' } }, data.today), React.createElement('br'),
            '불러온 시각 ', data.generatedAt) : null,
        React.createElement('button', { style: _krOpsBtn, onClick: load, disabled: loading }, loading ? '불러오는 중…' : '↻ 새로고침'));

    if (isViewer) return React.createElement('div', { style: _krWrap }, head,
        React.createElement('div', { style: _krCard }, '수집 현황판은 최고관리자만 볼 수 있습니다.'));
    if (data === undefined) return React.createElement('div', { style: _krWrap }, head,
        React.createElement('div', { style: _krCard }, '불러오는 중…'));
    if (data === null) return React.createElement('div', { style: _krWrap }, head,
        React.createElement('div', { style: Object.assign({}, _krCard, { color: '#b91c1c' }) }, '⚠ ' + (err || '현황을 불러오지 못했습니다.') + ' — 잠시 뒤 ↻ 새로고침을 눌러 주세요.'));

    var s = data.summary || {};
    var hourNow = new Date().getHours();

    // ① 판정 줄
    var verdicts = React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 10, marginBottom: 16 } },
        (data.verdicts || []).map(function(v) {
            var c = _cbLevel[v.level] || _cbLevel.unknown;
            return React.createElement('div', { key: v.key, style: { background: c.bg, border: '1px solid ' + c.bd, borderRadius: 12, padding: '11px 14px' } },
                React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
                    React.createElement('span', { style: { fontSize: 12, fontWeight: 800, color: '#334155' } }, v.title),
                    React.createElement('span', { style: { fontSize: 11, fontWeight: 800, color: c.fg, border: '1px solid ' + c.bd, background: '#fff', borderRadius: 999, padding: '1px 8px' } }, c.mark)),
                React.createElement('div', { style: { fontSize: 12.5, color: c.fg, marginTop: 5, lineHeight: 1.45 } }, v.text));
        }));

    // ② 오늘 숫자
    var tiles = React.createElement('div', { style: _krKpiGrid },
        _cbKpi('오늘 재야 할 키워드', _cbNum(s.universe), '수집 대상 전체'),
        _cbKpi('완료', _cbNum(s.completed), '300위까지 본 것 ' + _cbNum(s.full) + ' · 대상 다 찾음 ' + _cbNum(s.found), '#15803d'),
        _cbKpi('부분 수집', _cbNum(s.partial), '보다가 멈춤(내일 다시 잰다)', '#b45309'),
        _cbKpi('아직 안 봄', _cbNum(s.notTried), '오늘 한 번도 시도 안 함'),
        _cbKpi('시도 횟수', _cbNum(s.attempts), '수집기가 올린 결과 수'),
        _cbKpi('도우미가 읽은 화면', _cbNum(s.human), '사람이 넘긴 화면'),
        _cbKpi('진짜 차단', _cbNum(s.realBlocks), '퍼즐·차단 문구', (s.realBlocks > 0) ? '#b91c1c' : '#15803d'),
        _cbKpi('진단 보고', _cbNum(s.diagBlocks), '차단이 아님 — 2페이지 불변 등'));

    // ③ 시간대별
    var hr = data.hourly;
    var hourly = hr ? (function() {
        var mx = 0; hr.forEach(function(r) { mx = Math.max(mx, r.attempts || 0, r.completed || 0); });
        return React.createElement('div', null,
            _cbBars(hr.map(function(r) {
                var future = r.hour > hourNow;
                return { a: future ? null : r.attempts, b: future ? null : r.completed, label: String(r.hour), hi: r.hour === hourNow,
                         title: r.hour + '시 — 시도 ' + r.attempts + ' · 완료 ' + r.completed };
            }), mx),
            _cbLegend('시도', '완료'));
    })() : React.createElement('div', { style: { color: '#94a3b8', fontSize: 12.5 } }, '시간대별 기록을 읽지 못했습니다(미확인).');

    // ④ 14일 추이
    var hist = data.history || [];
    var hmx = 0; hist.forEach(function(r) { hmx = Math.max(hmx, r.attempts || 0, r.completed || 0); });
    var history = React.createElement('div', null,
        _cbBars(hist.map(function(r) {
            return { a: r.attempts, b: r.completed, label: r.day.slice(5).replace('-', '/'), hi: r.day === data.today,
                     title: r.day + ' — 시도 ' + _cbNum(r.attempts) + ' · 완료 ' + _cbNum(r.completed) };
        }), hmx),
        _cbLegend('시도', '완료'),
        React.createElement('div', { style: { marginTop: 12 } },
            _cbTable(['날짜', '완료', '300위까지', '대상 다 찾음', '부분', '시도', '도우미 화면', '진짜 차단', '진단 보고'],
                hist.slice().reverse().map(function(r) {
                    return [r.day, _cbNum(r.completed), _cbNum(r.full), _cbNum(r.found), _cbNum(r.partial), _cbNum(r.attempts), _cbNum(r.human),
                        React.createElement('span', { style: { color: r.realBlocks > 0 ? '#b91c1c' : undefined, fontWeight: r.realBlocks > 0 ? 800 : 400 } }, _cbNum(r.realBlocks)),
                        _cbNum(r.diagBlocks)];
                }))));

    // ⑤ 기계
    var machineRows = function(list) {
        return (list || []).map(function(m) {
            var up = m.uploadSummary;
            return [
                React.createElement('b', null, m.machine + '번'),
                m.ext_version ? 'v' + m.ext_version : '미확인',
                React.createElement('span', { style: { color: m.stale ? '#b91c1c' : '#334155', fontWeight: m.stale ? 800 : 400 } }, m.status || '미확인'),
                _cbAgo(m.minutes_since),
                (m.day_total ? (m.day_done || 0) + ' / ' + m.day_total : '미확인'),
                m.settingsText || '미확인',
                up ? (up.count ? up.count + '건 쌓임' : '없음') : '미보고',
                m.last_error ? String(m.last_error).slice(0, 40) : '—'
            ];
        });
    };
    var mHeads = ['기계', '버전', '상태', '마지막 신호', '오늘 몫(완료/전체)', '서버 설정', '미전송', '마지막 오류'];
    var machines = React.createElement('div', null,
        data.machines === null
            ? React.createElement('div', { style: { color: '#94a3b8', fontSize: 12.5 } }, '기계 신호를 읽지 못했습니다(미확인).')
            : _cbTable(mHeads, machineRows(data.machines), '신호를 보내는 기계가 없습니다.'),
        (data.oldMachines && data.oldMachines.length) ? React.createElement('div', { style: { marginTop: 10 } },
            React.createElement('button', { style: _krOpsBtn, onClick: function() { setShowOld(!showOld); } },
                (showOld ? '▾ ' : '▸ ') + '옛 설치본 ' + data.oldMachines.length + '개 — 3일 넘게 조용한 기록(교체 전 버전 · 고장 아님)'),
            showOld ? React.createElement('div', { style: { marginTop: 8 } }, _cbTable(mHeads, machineRows(data.oldMachines))) : null) : null);

    // ⑥ 막힘 사유
    var codeRows = function(b) {
        if (!b) return null;
        return b.codes.map(function(c) {
            var tag = c.kind === 'real' ? { t: '진짜 차단', c: '#b91c1c' } : c.kind === 'diag' ? { t: '진단 보고', c: '#64748b' } : { t: '기타', c: '#b45309' };
            return [React.createElement('span', { style: { color: tag.c, fontWeight: 800 } }, tag.t), c.label, _cbNum(c.count)];
        });
    };
    var blockBox = function(title, b) {
        return React.createElement('div', { style: { flex: '1 1 320px', minWidth: 0 } },
            React.createElement('div', { style: { fontSize: 12.5, fontWeight: 800, color: '#334155', marginBottom: 6 } },
                title, b ? ' — 진짜 차단 ' + b.real + ' · 진단 ' + b.diag + ' · 기타 ' + b.other : ' — 미확인'),
            b ? _cbTable(['구분', '사유', '건수'], codeRows(b), '보고 없음')
              : React.createElement('div', { style: { color: '#94a3b8', fontSize: 12.5 } }, '막힘 보고를 읽지 못했습니다.'));
    };
    var rr = data.recentRealBlocks;
    var blocks = React.createElement('div', null,
        React.createElement('div', { style: { display: 'flex', gap: 16, flexWrap: 'wrap' } },
            blockBox('오늘', data.blocksToday), blockBox('최근 7일', data.blocksWeek)),
        React.createElement('div', { style: { marginTop: 14, fontSize: 12.5, fontWeight: 800, color: '#334155', marginBottom: 6 } }, '최근 7일 진짜 차단 목록'),
        rr === null ? React.createElement('div', { style: { color: '#94a3b8', fontSize: 12.5 } }, '미확인')
            : _cbTable(['시각', '키워드', '페이지', '사유', '수집기 버전'],
                (rr || []).map(function(r) { return [r.at, r.keyword, r.page, r.code, r.version || '—']; }),
                '최근 7일 진짜 차단 없음 — 정상'));

    // ⑦ 멈춘 이유
    var sr = data.stopReasons;
    var stops = sr === null ? React.createElement('div', { style: { color: '#94a3b8', fontSize: 12.5 } }, '미확인')
        : _cbTable(['이유(수집기가 적은 것)', '건수'], (sr || []).map(function(r) { return [r.label ? r.reason + ' — ' + r.label : r.reason, _cbNum(r.count)]; }), '오늘 부분 수집 없음');

    // ⑧ 순위 기록
    var w = data.rankWrites || {};
    var writes = React.createElement('div', { style: _krKpiGrid },
        _cbKpi('업체 순위 오늘 기록', _cbNum(w.clients), '그중 순위 못 찾음 ' + _cbNum(w.clientsMissing)),
        _cbKpi('추적 상품 순위 오늘 기록', _cbNum(w.products), '마지막 기록 ' + (w.productsLastAt || '미확인')));

    // ⑨ 순위 읽기 도우미
    var hv = data.helper;
    var helper;
    if (!hv) {
        helper = React.createElement('div', { style: { color: '#94a3b8', fontSize: 12.5 } }, '도우미 기록을 읽지 못했습니다(미확인).');
    } else {
        var lc = hv.loginCompare || {};
        var lcRow = function(k, name) {
            var x = lc[k] || {};
            return [name, _cbNum(x.pairs), _krHvPct(x.samePos), _krHvPct(x.overlap)];
        };
        helper = React.createElement('div', null,
            React.createElement('div', { style: { fontSize: 12.5, fontWeight: 800, color: '#334155', marginBottom: 6 } }, '오늘 PC별'),
            hv.pcs === null ? React.createElement('div', { style: { color: '#94a3b8', fontSize: 12.5 } }, '미확인')
                : _cbTable(['PC', '읽은 화면', '키워드', '300위까지 끝냄', '대상 다 찾음', '마지막'],
                    (hv.pcs || []).map(function(p) { return ['PC ' + p.pc + '번', _cbNum(p.uploads), _cbNum(p.keywords), _cbNum(p.complete), _cbNum(p.allFound), p.lastAt || '—']; }),
                    '오늘 도우미가 읽은 화면이 없습니다. 설치한 PC 에서 추적 키워드를 검색하면 여기에 쌓입니다.'),
            React.createElement('div', { style: { fontSize: 12.5, fontWeight: 800, color: '#334155', margin: '14px 0 6px' } },
                '로그인 화면 대조(최근 7일) — 같은 키워드를 수집기와 도우미가 둘 다 봤을 때 순위가 얼마나 같은가'),
            _cbTable(['화면 상태', '대조 쌍', '같은 자리 비율', '상위 20개 겹침'],
                [lcRow('out', '로그아웃'), lcRow('in', '로그인'), lcRow('unknown', '미확인')]),
            React.createElement('div', { style: { fontSize: 11.5, color: '#64748b', marginTop: 6 } },
                '로그인 화면도 지금은 ' + (hv.loggedInRecorded ? '기록합니다' : '기록하지 않습니다') +
                ' — 로그인과 로그아웃의 비율이 크게 다르면 로그인 화면 기록을 끄는 것을 검토합니다.'),
            React.createElement('div', { style: { fontSize: 12.5, fontWeight: 800, color: '#334155', margin: '14px 0 6px' } }, '최근 읽은 화면'),
            hv.recent === null ? React.createElement('div', { style: { color: '#94a3b8', fontSize: 12.5 } }, '미확인')
                : _cbTable(['시각', 'PC', '키워드', '읽은 깊이', '대상 찾음', '화면', '적힘'],
                    (hv.recent || []).slice(0, 15).map(function(r) {
                        return [r.at, 'PC ' + r.pc + '번', r.keyword, '1~' + r.covered + '위' + (r.complete ? ' · 끝' : ''),
                            (r.targets ? r.found + ' / ' + r.targets : '—'), _krHvLogin[r.loggedIn] || '미확인', r.recorded ? '예' : '아니오'];
                    }), '아직 없음'));
    }

    var guide = React.createElement('div', { style: { fontSize: 12, color: '#64748b', lineHeight: 1.7, padding: '4px 2px 0' } },
        React.createElement('b', { style: { color: '#334155' } }, '읽는 법 — '),
        '맨 위 판정 줄이 모두 「정상」이면 오늘은 따로 볼 것이 없습니다. ',
        '「진짜 차단」이 1건이라도 있으면 수집기를 켜 둔 PC 에서 네이버쇼핑 화면을 직접 열어 보안 확인(퍼즐)이 떠 있는지 봐 주세요 — 퍼즐은 사람만 풉니다. ',
        '「진단 보고」는 차단이 아닙니다(2페이지를 눌러도 화면이 그대로였다는 등 수집기가 스스로 남긴 기록). ',
        '「미확인」은 0 이 아니라 그 값을 읽지 못했다는 뜻입니다.');

    return React.createElement('div', { style: _krWrap },
        head,
        err ? React.createElement('div', { style: { fontSize: 12.5, color: '#b45309', marginBottom: 10 } }, '⚠ 방금 새로 불러오기에 실패했습니다 — 아래는 직전 값입니다. (' + err + ')') : null,
        verdicts,
        tiles,
        _cbSection('오늘 시간대별', '연한 막대 = 시도 · 진한 막대 = 완료 · 지나지 않은 시간은 비워 둡니다', hourly),
        _cbSection('최근 14일', '완료가 며칠째 줄어들면 수집기를 확인할 때입니다', history),
        _cbSection('수집 기계', '5분마다 오는 살아있음 신호 기준 · 15분 넘게 신호가 없으면 끊김', machines),
        _cbSection('막힘 보고 — 진짜 차단과 진단 보고를 나눠서', null, blocks),
        _cbSection('부분 수집이 멈춘 이유(오늘)', '완료로 반영되지 않은 시도만', stops),
        _cbSection('순위 기록', '수집한 결과가 업체·추적 상품 순위로 실제 적혔는지', writes),
        _cbSection('📖 순위 읽기 도우미', '직원 PC 에서 사람이 직접 넘긴 화면으로 채운 순위 · 네이버에 요청을 보내지 않습니다', helper),
        guide);
};

function _cbKpi(k, v, sub, color) {
    return React.createElement('div', { style: _krKpi },
        React.createElement('div', { style: _krKpiK }, k),
        React.createElement('div', { style: Object.assign({}, _krKpiV, color ? { color: color } : {}) }, v),
        sub ? React.createElement('div', { style: _krKpiS }, sub) : null);
}
