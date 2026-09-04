/* ClientListSection — 메인 분석 페이지 업체 리스트 (v3.7)
 * 등록된 업체 카드를 가나다순으로 표시하고, 클릭 시 자동 분석 실행
 */
window.ClientListSection = function ClientListSection({ currentUser, onClientClick, onNavigateToClient }) {
    var useState = React.useState;
    var useEffect = React.useEffect;
    var useCallback = React.useCallback;

    var _s1 = useState([]); var clients = _s1[0]; var setClients = _s1[1];
    var _s2 = useState(true); var loading = _s2[0]; var setLoading = _s2[1];
    var _s3 = useState(function() {
        /* 셸 전역 검색(Ctrl+K) 핸드오프 — 1회 소비 */
        try {
            var g = sessionStorage.getItem('logic_global_q');
            if (g) { sessionStorage.removeItem('logic_global_q'); return g; }
        } catch (e) {}
        return '';
    }); var query = _s3[0]; var setQuery = _s3[1];
    var _s4 = useState(null); var mgrFilter = _s4[0]; var setMgrFilter = _s4[1]; // 담당자 탭 필터(null=전체)

    // 상위 계정(관리자)만 담당자(등록 직원) 정보를 노출 (매니저는 본인 것만 보므로 불필요)
    var isAdmin = !!(currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin'));

    var _s5 = useState([]); var managers = _s5[0]; var setManagers = _s5[1];     // 배정 가능한 담당자
    var _s6 = useState(null); var editMgrId = _s6[0]; var setEditMgrId = _s6[1]; // 담당자 변경 중인 업체 id

    /* 2차 확산(2026-08-05): 업체별 순위 롤업(rank-overview) — 카드에 대표 키워드
       순위·변동·미니 추이 표시용. 실패해도 카드 기본 표시는 그대로(가산). */
    var _s7 = useState({}); var rankOv = _s7[0]; var setRankOv = _s7[1];         // { clientId: overviewItem }
    var _s8 = useState(false); var attnOnly = _s8[0]; var setAttnOnly = _s8[1];  // ⚠️ 주의만 보기

    /* ⚠️ 2026-08-27 의 「추적 상태(추적 중/꺼짐)」 2칸 필터는 아래 5칸으로 대체됐다.
       그때 라벨을 「진행중」으로 쓰지 말라고 적어 뒀는데, 이제는 전산 단계를 실제로
       받아 저장하므로(contract_stage) 「진행중」이 전산의 그 단계와 같은 뜻이 됐다.
       즉 지금의 ▶ 진행중 칸은 「추적 중」과 다르다 — 환불중·홀딩중·삭제 필요를 뺀 나머지다. */

    /* 칸 나누기(2026-08-28 대표 확정) — null=전체 / run·refund·hold·delete·check.
       ⚠️ 판정은 **서버가 한다**(client_buckets.py). 화면이 같은 규칙을 또 구현하면
          두 곳이 갈려 「목록에는 있는데 숫자는 다른」 상태가 된다. 여기서는 c.bucket 을 읽기만 한다. */
    var _sB = useState(null); var bucket = _sB[0], setBucket = _sB[1];
    var _sS = useState(false); var syncing = _sS[0], setSyncing = _sS[1];
    var _sM = useState(null); var syncMsg = _sM[0], setSyncMsg = _sM[1];
    /* 보고서 담당자 정렬(신고 #256) — 전산 현재 담당자에 맞춰 보고서 소유(열람 권한)를 즉시 맞춘다. */
    var _sO = useState(false); var syncingOwner = _sO[0], setSyncingOwner = _sO[1];
    var _sOM = useState(null); var ownerMsg = _sOM[0], setOwnerMsg = _sOM[1];

    /* 내린 업체(보관) — 2026-08-30 대표 확정 「지우지 말고 목록에서 내리기」.
       ⚠️ 내리면 관리 목록(`/my-clients` = status='active')에서 빠지므로, **되돌릴 자리**가
          함께 있어야 한다. 이 목록이 없으면 되돌릴 길 없는 한 방향 문이 된다. */
    var _sA = useState([]); var archived = _sA[0], setArchived = _sA[1];
    var _sAB = useState(null); var archBusy = _sAB[0], setArchBusy = _sAB[1];   // 처리 중인 업체 id

    var pullStages = function() {
        setSyncing(true); setSyncMsg(null);
        api.post('/cd/contract-stage-sync', {}).then(function(res) {
            if (res && res.success) {
                var d = res.data || {};
                setSyncMsg({ ok: true, text: '전산에서 계약 단계를 가져왔습니다 — 단계 저장 ' + (d.staged || 0) + '곳' });
                loadClients();   // 새 단계 값으로 목록을 다시 그린다
            } else {
                setSyncMsg({ ok: false, text: (res && res.detail) || '가져오지 못했습니다.' });
            }
        }).catch(function(e) {
            setSyncMsg({ ok: false, text: '가져오지 못했습니다 — ' + ((e && e.message) || '네트워크 오류') });
        }).then(function() { setSyncing(false); });
    };

    /* 보고서 담당자 정렬(신고 #256) — 04:20 배치와 같은 서버 함수(/cd/report-owner-sync)를 부른다.
       전산에서 담당자를 방금 바꾼 직후, 다음 날 04:20 을 기다리지 않고 즉시 열람 권한을 맞춘다. */
    var syncOwners = function() {
        setSyncingOwner(true); setOwnerMsg(null);
        api.post('/cd/report-owner-sync', {}).then(function(res) {
            if (res && res.success) {
                var d = res.data || {};
                setOwnerMsg({ ok: true, text: '전산 현재 담당자에 맞춰 보고서 소유를 정렬했습니다 — ' + (d.changed || 0) + '곳 이동'
                    + (d.created_accounts ? (' · 계정 생성 ' + d.created_accounts) : '')
                    + (d.aligned_already ? (' · 이미 맞음 ' + d.aligned_already) : '') });
            } else {
                setOwnerMsg({ ok: false, text: (res && res.detail) || '정렬하지 못했습니다.' });
            }
        }).catch(function(e) {
            setOwnerMsg({ ok: false, text: '정렬하지 못했습니다 — ' + ((e && e.message) || '네트워크 오류') });
        }).then(function() { setSyncingOwner(false); });
    };

    useEffect(function() {
        api.get('/cd/rank-overview').then(function(res) {
            if (res && res.success && res.data) {
                var m = {};
                res.data.forEach(function(it) { m[it.id] = it; });
                setRankOv(m);
            }
        }).catch(function() {});
    }, []);

    /* 카드 미니 스파크라인 — 대표 키워드 8일 추이 (낮은 순위 = 위) */
    var miniSpark = function(series) {
        var pts = (series || []).filter(function(p) { return p.rank != null; });
        if (pts.length < 2) return null;
        var w = 200, h = 22, pad = 2;
        var rs = pts.map(function(p) { return p.rank; });
        var mn = Math.min.apply(null, rs), mx = Math.max.apply(null, rs);
        var span = (mx - mn) || 1;
        var coords = pts.map(function(p, i) {
            return (pad + (w - pad * 2) * (i / (pts.length - 1))).toFixed(1) + ',' +
                   (pad + (h - pad * 2) * ((p.rank - mn) / span)).toFixed(1);
        });
        var improving = rs[rs.length - 1] <= rs[0];
        return React.createElement('svg', { width: '100%', height: h, viewBox: '0 0 ' + w + ' ' + h, preserveAspectRatio: 'none', style: { display: 'block', margin: '4px 0 2px' } },
            React.createElement('polyline', { points: coords.join(' '), fill: 'none', stroke: improving ? '#16a34a' : '#dc2626', strokeWidth: 1.8, strokeLinejoin: 'round', strokeLinecap: 'round' }));
    };

    useEffect(function() {
        if (!isAdmin) return;
        api.get('/clients/assignable-managers').then(function(res) {
            if (res && res.success) setManagers(res.data || []);
        }).catch(function() {});
    }, [isAdmin]);

    // 담당자(created_by) 변경
    var changeManager = function(clientId, managerId) {
        var mid = parseInt(managerId, 10);
        if (!mid) { setEditMgrId(null); return; }
        api.put('/clients/' + clientId + '/manager', { manager_id: mid }).then(function(res) {
            if (res && res.success) {
                setClients(function(prev) {
                    return prev.map(function(c) { return c.id === clientId ? Object.assign({}, c, { created_by: mid, manager_name: res.manager_name }) : c; });
                });
                try { toast.success('담당자를 변경했습니다.'); } catch(e) {}
            }
            setEditMgrId(null);
        }).catch(function() { setEditMgrId(null); });
    };

    /* 목록에서 내리기 / 되돌리기 — 2026-08-30 대표 확정.
       ⚠️ **지우는 게 아니라 내린다**: status='terminated' 로 바꾸면 관리 목록·추적에서
          빠지지만 순위 기록·분석 보고서는 그대로 남고 되돌릴 수 있다. 이번 주 키워드
          「그만 재기」와 같은 방식이라 직원이 외울 규칙이 하나로 유지된다.
       ⚠️ 저장은 자동 추적 토글이 이미 쓰는 경로(`PUT /clients/{id}`)를 그대로 쓴다 —
          권한 경계도 그것과 같다(조회 전용 계정은 버튼 자체가 안 보인다). */
    var setClientStatus = function(client, next) {
        if (archBusy) return;
        var toArchive = next === 'terminated';
        if (toArchive && !window.confirm(
                '「' + (client.name || '') + '」 목록에서 내릴까요?\n\n'
                + '· 관리 목록과 순위 추적에서 빠집니다.\n'
                + '· 순위 기록·분석 보고서는 그대로 보존됩니다.\n'
                + '· 「🗄 내린 업체」 탭에서 언제든 되돌릴 수 있습니다.\n\n'
                + '기록까지 완전히 지우려면 업체 리스트의 삭제를 쓰세요.')) return;
        setArchBusy(client.id);
        api.put('/clients/' + client.id, { status: next }).then(function(res) {
            if (res && (res.success === undefined || res.success)) {
                try {
                    toast.success(toArchive
                        ? '「' + (client.name || '') + '」 목록에서 내렸습니다 — 기록은 그대로입니다.'
                        : '「' + (client.name || '') + '」 되돌렸습니다 — 관리 목록으로 돌아갑니다.');
                } catch (e) {}
                loadClients(); loadArchived();
            } else {
                try { toast.error((res && res.detail) || '처리하지 못했습니다.'); } catch (e) {}
            }
        }).catch(function(err) {
            try { toast.error((err && err.message) || '처리하지 못했습니다.'); } catch (e) {}
        }).finally(function() { setArchBusy(null); });
    };

    /* 업체 목록 로드 */
    var loadClients = useCallback(function() {
        setLoading(true);
        api.get('/cd/my-clients').then(function(res) {
            if (res.success) setClients(res.data || []);
            setLoading(false);
        }).catch(function() { setLoading(false); });
    }, []);

    var loadArchived = useCallback(function() {
        api.get('/cd/archived-clients').then(function(res) {
            if (res && res.success) setArchived(res.data || []);
        }).catch(function() {});   // 실패해도 관리 목록은 그대로 — 탭 수만 0으로 보인다
    }, []);

    useEffect(function() { loadClients(); loadArchived(); }, [loadClients, loadArchived]);

    /* 셸 전역 검색 이벤트 — 대시보드에 이미 있을 때도 검색어 반영 */
    useEffect(function() {
        var onSearch = function(ev) {
            if (ev && typeof ev.detail === 'string') {
                setQuery(ev.detail);
                try { sessionStorage.removeItem('logic_global_q'); } catch (e) {}
            }
        };
        window.addEventListener('logic-global-search', onSearch);
        return function() { window.removeEventListener('logic-global-search', onSearch); };
    }, []);

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

    /* ⚠️ 주의 판정 — 추적 키워드는 있는데 노출 0 (rank-overview 기준) */
    var isAttention = function(c) {
        var ov = rankOv[c.id];
        return !!(ov && ov.keywords > 0 && ov.exposed === 0);
    };

    /* 검색 + 가나다 정렬 */
    var filtered = clients
        .filter(function(c) {
            // 담당자 탭 필터 (null = 전체)
            if (mgrFilter && (c.manager_name || '(미지정)') !== mgrFilter) return false;
            if (attnOnly && !isAttention(c)) return false;
            // 칸 나누기 — 판정은 서버(c.bucket). 옛 서버 응답이면 bucket 이 없어
            // 전부 '진행중'으로 흡수한다(배포 순서가 어긋나도 목록이 비지 않게).
            if (bucket && (c.bucket || 'run') !== bucket) return false;
            if (!query.trim()) return true;
            var q = query.trim().toLowerCase();
            return (c.name || '').toLowerCase().indexOf(q) !== -1
                || (c.main_keywords || '').toLowerCase().indexOf(q) !== -1;
        })
        .slice()
        .sort(function(a, b) {
            return (a.name || '').localeCompare(b.name || '', 'ko');
        });

    /* 업체 상세 보기 핸들러 — 진행중 업체 탭 상세 화면으로 이동 */
    var handleViewClient = function(client) {
        if (onNavigateToClient) {
            onNavigateToClient(client.name || '', client.naver_store_url || '');
        }
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
                    }, '🏢 등록 업체', clients.length > 0 && React.createElement('span', { style: { fontSize: 14, fontWeight: 500, color: '#3b82f6', marginLeft: 4 } }, '(' + clients.length + '개)')),
                    React.createElement('p', {
                        style: { fontSize: 13, color: '#64748b', margin: '4px 0 0 0' }
                    }, '업체 상세 보기를 클릭하면 분석 이력과 순위를 확인할 수 있습니다.')
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

            /* 2차 확산: KPI 스트립 — 업체·오늘 분석·상승 키워드·주의(클릭 필터) */
            !loading && clients.length > 0 && (function() {
                var today = new Date().toISOString().slice(0, 10);
                var analyzedToday = clients.filter(function(c) {
                    return c.analyzed_keywords && c.analyzed_keywords[0] && String(c.analyzed_keywords[0].analyzed_date || '').slice(0, 10) === today;
                }).length;
                var upTotal = 0, attn = 0, hasOv = false;
                clients.forEach(function(c) {
                    var ov = rankOv[c.id];
                    if (ov) { hasOv = true; upTotal += (ov.up || 0); if (isAttention(c)) attn++; }
                });
                var kpi = function(k, v, sub, subColor, onClick, active) {
                    return React.createElement('div', {
                        onClick: onClick || null,
                        style: { background: active ? '#fffbeb' : '#f8fafc', border: '1px solid ' + (active ? '#f59e0b' : '#eef2f6'), borderRadius: 12, padding: '11px 15px', cursor: onClick ? 'pointer' : 'default', flex: '1 1 150px', minWidth: 140 }
                    },
                        React.createElement('div', { style: { fontSize: 11, fontWeight: 700, color: '#94a3b8', letterSpacing: '.03em' } }, k),
                        React.createElement('div', { style: { fontSize: 20, fontWeight: 800, color: '#0f172a', marginTop: 1 } }, v),
                        sub && React.createElement('div', { style: { fontSize: 11, color: subColor || '#94a3b8' } }, sub)
                    );
                };
                return React.createElement('div', { style: { display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 } },
                    kpi('내 업체', clients.length, null),
                    kpi('오늘 자동 분석', analyzedToday, '보고서 생성됨'),
                    hasOv && kpi('상승 키워드', '▲ ' + upTotal, '전일 대비', '#16a34a'),
                    hasOv && kpi('주의 필요', attn, attnOnly ? '필터 적용 중 — 클릭 해제' : '노출 0 — 클릭 시 필터', '#b45309',
                        function() { setAttnOnly(!attnOnly); }, attnOnly)
                );
            })(),

            /* ---------- 칸 나누기 (2026-08-28 대표 확정) ----------
               진행중 / 환불중 / 홀딩중 / 삭제 필요 / 확인 필요.
               ⚠️ 영업사원(viewer)에게는 안 띄운다 — 그 화면은 영업 대상만 보이는데
                  계약 단계·자동 추적은 광고주에게만 도는 개념이라 칸이 늘 하나로 쏠린다. */
            !loading && clients.length > 0 && currentUser && currentUser.role !== 'viewer' && (function() {
                var n = { run: 0, refund: 0, hold: 0, delete: 0, check: 0 };
                clients.forEach(function(c) { var b = c.bucket || 'run'; if (n[b] != null) n[b]++; });
                var staged = clients.filter(function(c) { return !!c.contract_stage; }).length;
                var mkTab = function(label, val, count, color, bg, border) {
                    var on = bucket === val;
                    return React.createElement('button', { key: label, onClick: function() { setBucket(on ? null : val); },
                        style: { fontSize: 12, fontWeight: 700, padding: '6px 12px', borderRadius: 999, cursor: 'pointer', whiteSpace: 'nowrap',
                                 border: '1px solid ' + (on ? color : border), background: on ? color : bg, color: on ? '#fff' : color } },
                        label + ' ' + count);
                };
                return React.createElement('div', { style: { marginBottom: 16 } },
                    React.createElement('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' } },
                        mkTab('전체', null, clients.length, '#475569', '#f8fafc', '#e2e8f0'),
                        mkTab('▶ 진행중', 'run', n.run, '#047857', '#ecfdf5', '#a7f3d0'),
                        mkTab('↩ 환불중', 'refund', n.refund, '#6d28d9', '#f5f3ff', '#ddd6fe'),
                        mkTab('⏸ 홀딩중', 'hold', n.hold, '#b45309', '#fffbeb', '#fcd34d'),
                        mkTab('🗑 삭제 필요', 'delete', n.delete, '#b91c1c', '#fef2f2', '#fecaca'),
                        mkTab('🔍 확인 필요', 'check', n.check, '#0369a1', '#f0f9ff', '#bae6fd'),
                        /* 내린 업체 — 이 칸이 있어야 「내리기」가 되돌릴 수 있는 일이 된다 */
                        mkTab('🗄 내린 업체', 'archived', archived.length, '#334155', '#f1f5f9', '#cbd5e1'),
                        isAdmin && React.createElement('button', {
                            onClick: pullStages, disabled: syncing,
                            title: '전산에서 계약 단계(환불중·홀딩중·계약 만료)를 지금 가져옵니다',
                            style: { marginLeft: 'auto', fontSize: 12, fontWeight: 700, padding: '6px 12px', borderRadius: 999,
                                     cursor: syncing ? 'not-allowed' : 'pointer', border: '1px solid #cbd5e1',
                                     background: '#fff', color: syncing ? '#94a3b8' : '#334155', whiteSpace: 'nowrap' }
                        }, syncing ? '가져오는 중…' : '⟳ 계약 단계 지금 가져오기'),
                        isAdmin && React.createElement('button', {
                            onClick: syncOwners, disabled: syncingOwner,
                            title: '전산의 현재 담당자에 맞춰 보고서 소유(열람 권한)를 지금 정렬합니다 (신고 #256)',
                            style: { fontSize: 12, fontWeight: 700, padding: '6px 12px', borderRadius: 999,
                                     cursor: syncingOwner ? 'not-allowed' : 'pointer', border: '1px solid #cbd5e1',
                                     background: '#fff', color: syncingOwner ? '#94a3b8' : '#334155', whiteSpace: 'nowrap' }
                        }, syncingOwner ? '정렬 중…' : '⟳ 보고서 담당자 정렬')
                    ),
                    /* ⚠️ 단계를 한 번도 못 받았으면 그 사실을 말해 준다. 안 그러면
                       환불중·홀딩중이 0으로 보여 「환불 업체가 없다」고 오해한다. */
                    staged === 0 && React.createElement('div', {
                        style: { marginTop: 8, fontSize: 11.5, color: '#b45309', background: '#fffbeb',
                                 border: '1px solid #fde68a', borderRadius: 8, padding: '7px 11px' }
                    }, '아직 전산에서 계약 단계를 받아오지 않았습니다 — 환불중·홀딩중이 0으로 보입니다. '
                     + (isAdmin ? '오른쪽 「⟳ 계약 단계 지금 가져오기」를 한 번 눌러 주세요.' : '관리자가 한 번 가져오면 채워집니다.')
                     + ' (매일 04:00 에도 자동으로 갱신됩니다.)'),
                    syncMsg && React.createElement('div', {
                        style: { marginTop: 8, fontSize: 11.5, color: syncMsg.ok ? '#047857' : '#b91c1c' }
                    }, syncMsg.text),
                    ownerMsg && React.createElement('div', {
                        style: { marginTop: 8, fontSize: 11.5, color: ownerMsg.ok ? '#047857' : '#b91c1c' }
                    }, ownerMsg.text),
                    bucket === 'delete' && React.createElement('div', {
                        style: { marginTop: 8, fontSize: 11.5, color: '#64748b' }
                    }, '더 이상 추적할 이유가 없는 등록건입니다. 사유를 확인하고 「🗄 목록에서 내리기」를 누르면 화면이 정리됩니다 — 순위 기록은 그대로 보존되고, 「🗄 내린 업체」 탭에서 언제든 되돌릴 수 있습니다.'),
                    bucket === 'archived' && React.createElement('div', {
                        style: { marginTop: 8, fontSize: 11.5, color: '#64748b' }
                    }, '목록에서 내린 업체입니다. 기록은 그대로 남아 있고, ↩ 를 누르면 관리 목록으로 돌아옵니다 — 추적도 함께 재개됩니다.'),
                    bucket === 'check' && React.createElement('div', {
                        style: { marginTop: 8, fontSize: 11.5, color: '#64748b' }
                    }, '수집이 5회 연속 실패해 포기된 키워드가 있는 업체입니다. 오타이거나 검색이 안 되는 말입니다 — 고치면 되살아납니다.'),
                    (bucket === 'refund' || bucket === 'hold') && React.createElement('div', {
                        style: { marginTop: 8, fontSize: 11.5, color: '#64748b' }
                    }, '추적이 자동으로 멈춰 있습니다. 전산에서 단계를 되돌리면 다음 날 04:00 에 자동으로 재개됩니다 — 여기서 손댈 것이 없습니다.')
                );
            })(),

            /* 담당자별 구분 탭 (상위 계정 전용) — 클릭 시 해당 담당자 업체만 모아보기 */
            isAdmin && !loading && clients.length > 0 && (function() {
                var counts = {};
                clients.forEach(function(c) { var m = c.manager_name || '(미지정)'; counts[m] = (counts[m] || 0) + 1; });
                var names = Object.keys(counts).sort(function(a, b) { return counts[b] - counts[a]; });
                var mkTab = function(label, val, count) {
                    var on = mgrFilter === val;
                    return React.createElement('button', { key: label, onClick: function() { setMgrFilter(val); },
                        style: { fontSize: 12, fontWeight: 700, padding: '6px 12px', borderRadius: 999, cursor: 'pointer', whiteSpace: 'nowrap',
                                 border: '1px solid ' + (on ? '#6d28d9' : '#e9d5ff'), background: on ? '#6d28d9' : '#faf5ff', color: on ? '#fff' : '#6d28d9' } },
                        label + (count != null ? ' ' + count : ''));
                };
                return React.createElement('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 16, paddingBottom: 14, borderBottom: '1px dashed #e2e8f0' } },
                    React.createElement('span', { style: { fontSize: 12, color: '#94a3b8', fontWeight: 700, marginRight: 2 } }, '담당자별 보기'),
                    mkTab('전체', null, clients.length),
                    names.map(function(m) { return mkTab('👤 ' + m, m, counts[m]); })
                );
            })(),

            /* 로딩 */
            loading && React.createElement('div', {
                style: { textAlign: 'center', padding: '40px 20px', color: '#64748b', fontSize: 14 }
            }, '업체 목록 불러오는 중...'),

            /* 빈 상태 */
            bucket !== 'archived' && !loading && filtered.length === 0 && clients.length === 0 && React.createElement('div', {
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

            /* 결과 없음 — 필터 때문인지 검색 때문인지 갈라서 알려준다.
               「검색 결과가 없습니다」만 뜨면 필터를 켜 둔 걸 잊고 데이터가 없다고 오해한다. */
            bucket !== 'archived' && !loading && filtered.length === 0 && clients.length > 0 && React.createElement('div', {
                style: { textAlign: 'center', padding: '30px 20px', color: '#94a3b8', fontSize: 13 }
            },
                bucket
                    ? React.createElement(React.Fragment, null,
                        React.createElement('div', null,
                            ({ run: '▶ 진행중', refund: '↩ 환불중', hold: '⏸ 홀딩중',
                               'delete': '🗑 삭제 필요', check: '🔍 확인 필요',
                               archived: '🗄 내린 업체' }[bucket] || bucket)
                            + ' 칸에 해당하는 업체가 없습니다.'),
                        React.createElement('button', {
                            onClick: function() { setBucket(null); },
                            style: { marginTop: 10, fontSize: 12, fontWeight: 700, padding: '6px 14px', borderRadius: 999,
                                     border: '1px solid #cbd5e1', background: '#fff', color: '#475569', cursor: 'pointer' }
                        }, '필터 해제')
                      )
                    : '검색 결과가 없습니다.'
            ),

            /* 내린 업체 그리드 (2026-08-30) — 되돌리기 전용.
               ⚠️ 일부러 가볍다: 순위 롤업·분석 집계를 붙이지 않는다. 여기서 할 일은
                  「왜 내렸는지 보고 되돌릴지 정하는 것」 하나뿐이다. */
            bucket === 'archived' && !loading && React.createElement('div', {
                style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))', gap: 14 }
            },
                archived.length === 0
                    ? React.createElement('div', { style: { gridColumn: '1 / -1', textAlign: 'center', padding: '30px 20px', color: '#94a3b8', fontSize: 13 } },
                        '내린 업체가 없습니다. 「🗑 삭제 필요」 칸에서 정리하면 여기에 쌓입니다.')
                    : archived.map(function(a) {
                        return React.createElement('div', {
                            key: a.id,
                            style: { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: '13px 14px' }
                        },
                            React.createElement('div', { style: { fontSize: 14, fontWeight: 800, color: '#0f172a', marginBottom: 3 } }, a.name || ''),
                            React.createElement('div', { style: { fontSize: 11.5, color: '#94a3b8', marginBottom: 8 } },
                                '내린 날 ' + String(a.updated_at || '').slice(0, 10)),
                            React.createElement('div', { style: { display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 9 } },
                                (a.delete_reasons || []).map(function(r) {
                                    return React.createElement('span', {
                                        key: r,
                                        style: { fontSize: 10.5, fontWeight: 800, padding: '2px 8px', borderRadius: 999,
                                                 background: '#f1f5f9', color: '#475569', border: '1px solid #e2e8f0' }
                                    }, r);
                                })),
                            currentUser && currentUser.role !== 'viewer' && React.createElement('button', {
                                onClick: function() { setClientStatus(a, 'active'); },
                                disabled: archBusy === a.id,
                                style: { display: 'block', width: '100%', textAlign: 'center', borderRadius: 8, padding: '7px 0',
                                         fontSize: 11.5, fontWeight: 800, cursor: archBusy === a.id ? 'default' : 'pointer',
                                         background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe' }
                            }, archBusy === a.id ? '되돌리는 중…' : '↩ 되돌리기')
                        );
                    })
            ),

            /* 업체 카드 그리드 */
            bucket !== 'archived' && !loading && filtered.length > 0 && React.createElement('div', {
                style: {
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
                    gap: 14
                }
            },
                filtered.map(function(client) {
                    var lastDate = getLastAnalyzedText(client);
                    var ov = rankOv[client.id];
                    var attn = isAttention(client);
                    var repKw = ov && ov.top_keywords && ov.top_keywords[0];
                    var repDelta = null;
                    if (ov && ov.rep_series && ov.rep_series.length >= 2) {
                        var _rs = ov.rep_series;
                        if (_rs[_rs.length - 1].rank != null && _rs[_rs.length - 2].rank != null) {
                            repDelta = _rs[_rs.length - 2].rank - _rs[_rs.length - 1].rank; // 양수=상승
                        }
                    }

                    return React.createElement('div', {
                        key: client.id,
                        style: {
                            background: '#fff',
                            border: '1px solid ' + (attn ? '#f59e0b' : '#e2e8f0'),
                            borderRadius: 12,
                            padding: '16px 18px',
                            transition: 'all 0.15s ease',
                            boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'space-between'
                        },
                        onMouseEnter: function(e) {
                            e.currentTarget.style.borderColor = '#3b82f6';
                            e.currentTarget.style.boxShadow = '0 4px 12px rgba(108,92,231,0.15)';
                            e.currentTarget.style.transform = 'translateY(-2px)';
                        },
                        onMouseLeave: function(e) {
                            e.currentTarget.style.borderColor = attn ? '#f59e0b' : '#e2e8f0';
                            e.currentTarget.style.boxShadow = '0 1px 2px rgba(0,0,0,0.04)';
                            e.currentTarget.style.transform = 'translateY(0)';
                        }
                    },
                        /* 업체명 + 대표 키워드 순위(2차 확산) + 마지막 분석 */
                        React.createElement('div', null,
                            React.createElement('div', {
                                style: { fontSize: 15, fontWeight: 700, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginBottom: 6 }
                            },
                                client.vertical === 'place' && React.createElement('span', { title: '플레이스 업체', style: { marginRight: 4 } }, '📍'),
                                client.name || '(이름 없음)'),

                            /* 대표 키워드 현재 순위 + 변동 + 미니 추이 */
                            ov && React.createElement('div', { style: { marginBottom: 7 } },
                                repKw
                                    ? React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 6 } },
                                        React.createElement('span', { style: { fontSize: 12, color: '#475569', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, repKw.keyword),
                                        React.createElement('span', { style: { fontSize: 16, fontWeight: 800, color: repKw.rank <= 10 ? '#16a34a' : '#0f172a' } }, repKw.rank + '위'),
                                        repDelta != null && repDelta !== 0 && React.createElement('span', {
                                            style: { fontSize: 11, fontWeight: 800, borderRadius: 6, padding: '1px 6px',
                                                     color: repDelta > 0 ? '#dc2626' : '#2563eb', background: repDelta > 0 ? '#fef2f2' : '#eff6ff' }
                                        }, (repDelta > 0 ? '▲' : '▼') + Math.abs(repDelta)))
                                    : (ov.keywords > 0
                                        ? React.createElement('div', { style: { fontSize: 12, fontWeight: 700, color: '#b45309' } }, '⚠️ 추적 ' + ov.keywords + '개 전부 미노출')
                                        : null),
                                miniSpark(ov.rep_series),
                                ov.keywords > 0 && React.createElement('div', { style: { fontSize: 11, color: '#94a3b8' } },
                                    '키워드 ' + ov.keywords + ' · 노출 ' + ov.exposed + (ov.top10 ? ' · TOP10 ' + ov.top10 : ''))
                            ),

                            React.createElement('div', {
                                style: { fontSize: 11, color: '#dc2626', marginBottom: isAdmin ? 4 : 12 }
                            }, '마지막 분석: ' + lastDate),
                            isAdmin && React.createElement('div', {
                                style: { fontSize: 11, color: '#6d28d9', fontWeight: 700, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }
                            },
                                editMgrId === client.id
                                    ? React.createElement('select', {
                                        defaultValue: client.created_by || '',
                                        onClick: function(e){ e.stopPropagation(); },
                                        onChange: function(e){ e.stopPropagation(); changeManager(client.id, e.target.value); },
                                        style: { fontSize: 11, padding: '3px 6px', borderRadius: 6, border: '1px solid #ddd6fe', maxWidth: '100%' }
                                    },
                                        React.createElement('option', { value: '' }, '담당자 선택...'),
                                        managers.map(function(m){ return React.createElement('option', { key: m.id, value: m.id }, m.name + (m.role !== 'manager' ? ' (' + m.role + ')' : '')); })
                                    )
                                    : React.createElement(React.Fragment, null,
                                        React.createElement('span', null, '👤 담당자: ' + (client.manager_name || '-')),
                                        React.createElement('button', { onClick: function(e){ e.stopPropagation(); setEditMgrId(client.id); },
                                            style: { fontSize: 10, fontWeight: 700, color: '#6d28d9', background: '#ede9fe', border: 'none', borderRadius: 6, padding: '2px 7px', cursor: 'pointer' } }, '변경')
                                    )
                            )
                        ),

                        /* 업체 상세 보기 버튼 */
                        React.createElement('button', {
                            onClick: function() { handleViewClient(client); },
                            style: {
                                display: 'block',
                                width: '100%',
                                textAlign: 'center',
                                background: '#3b82f6',
                                color: '#fff',
                                border: 'none',
                                padding: '8px 0',
                                borderRadius: 8,
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: 'pointer'
                            }
                        }, '업체 상세 보기 →'),

                        /* ---------- 기간이 지난 업체는 버튼 대신 사실을 말한다 (2026-08-28) ----------
                           ⚠️ 종전엔 추적 종료일이 지나 수집·기록이 전부 멈춘 업체에도
                              「▶ 자동 추적 중 — 끄기」가 떠서 배지(기간 지남)와 버튼이 서로
                              다른 말을 했다(대표 화면 검증에서 발견). 종료일이 지나면 자격
                              판정(tracking_eligibility)이 스위치와 무관하게 그 업체를 빼므로,
                              버튼을 눌러도 아무 일도 일어나지 않는 죽은 버튼이었다.
                           판정은 서버가 내려준 delete_reasons 를 그대로 쓴다 — 화면이 날짜를
                           다시 계산하면 자정 부근·시간대 차이로 서버와 어긋난다. */
                        (client.delete_reasons || []).indexOf('기간 지남') >= 0 && React.createElement('div', {
                            style: { display: 'block', width: '100%', textAlign: 'center', marginTop: 6,
                                     background: '#fef2f2', color: '#991b1b', border: '1px solid #fecaca',
                                     padding: '6px 0', borderRadius: 8, fontSize: 11.5, fontWeight: 700 }
                        }, '⏸ 기간이 지나 추적 안 함' + (client.track_until ? ' — 종료일 ' + client.track_until : '')),
                        (client.delete_reasons || []).indexOf('기간 지남') >= 0 && currentUser && currentUser.role !== 'viewer' && React.createElement('div', {
                            style: { marginTop: 4, textAlign: 'center', fontSize: 10.5, color: '#94a3b8' }
                        }, '전산에서 계약 단계를 옮기면 다음 날 04:00에 자동 재개됩니다'),

                        /* 자동 추적 켜기/끄기 (호출 다이어트) — 계약만료·환불·홀딩 등 관리 중단 업체는
                           일일 자동분석·순위추적에서 제외. 기록·조회는 유지. viewer는 조회만 */
                        (client.delete_reasons || []).indexOf('기간 지남') < 0 &&
                        currentUser && currentUser.role !== 'viewer' && React.createElement('button', {
                            onClick: function(e) {
                                e.stopPropagation();
                                var next = (client.auto_analysis === 0) ? 1 : 0;
                                var label = next === 0 ? '끄기' : '켜기';
                                if (!window.confirm('"' + (client.name || '') + '" 자동 추적을 ' + label + ' 할까요?' + (next === 0 ? '\n(계약만료·환불·홀딩 등 관리 중단 업체 권장 — 기록·조회는 그대로 유지됩니다)' : ''))) return;
                                api.put('/clients/' + client.id, { auto_analysis: next }).then(function(res) {
                                    if (res && (res.success === undefined || res.success)) {
                                        try { toast.success('자동 추적 ' + label + ' 완료: ' + (client.name || '')); } catch (e2) {}
                                        loadClients();
                                    } else {
                                        try { toast.error('변경 실패: ' + ((res && res.detail) || '오류')); } catch (e2) {}
                                    }
                                }).catch(function(err) {
                                    try { toast.error('변경 실패: ' + (err.message || '네트워크 오류')); } catch (e2) {}
                                });
                            },
                            style: {
                                display: 'block',
                                width: '100%',
                                textAlign: 'center',
                                marginTop: 6,
                                background: client.auto_analysis === 0 ? '#fef3c7' : '#f1f5f9',
                                color: client.auto_analysis === 0 ? '#92400e' : '#475569',
                                border: '1px solid ' + (client.auto_analysis === 0 ? '#fcd34d' : '#e2e8f0'),
                                padding: '6px 0',
                                borderRadius: 8,
                                fontSize: 11.5,
                                fontWeight: 700,
                                cursor: 'pointer'
                            }
                        }, client.auto_analysis === 0 ? '⏸ 자동 추적 꺼짐 — 켜기' : '▶ 자동 추적 중 — 끄기'),

                        /* 🗄 목록에서 내리기 — 「삭제 필요」 칸에서만 (2026-08-30 대표 확정).
                           ⚠️ 찾은 자리에서 바로 정리하게 한다. 종전에는 안내문이 「여기서 바로
                              지우지는 않습니다」라고만 말해, 정리하려면 업체 리스트로 건너가야 했다.
                           ⚠️ **진짜 삭제가 아니다** — 기록을 지우지 않고 목록에서만 내린다.
                              「전산에 없음」은 이름이 한 글자 달라 못 찾은 것일 수 있어(유성프레쉬→
                              유성프레시 실사례) 그 자리에서 하드 삭제를 시키면 멀쩡한 이력이 날아간다. */
                        client.bucket === 'delete' && currentUser && currentUser.role !== 'viewer'
                        && React.createElement('button', {
                            onClick: function(e) { e.stopPropagation(); setClientStatus(client, 'terminated'); },
                            disabled: archBusy === client.id,
                            title: '관리 목록·추적에서 내립니다 — 순위 기록은 보존되고 「🗄 내린 업체」 탭에서 되돌릴 수 있습니다',
                            style: { display: 'block', width: '100%', textAlign: 'center', marginTop: 6,
                                     background: '#f1f5f9', color: '#334155', border: '1px solid #cbd5e1',
                                     padding: '6px 0', borderRadius: 8, fontSize: 11.5, fontWeight: 700,
                                     cursor: archBusy === client.id ? 'default' : 'pointer' }
                        }, archBusy === client.id ? '내리는 중…' : '🗄 목록에서 내리기'),

                        /* 중지 상태 배지(viewer 포함 전원에게 보임) */
                        (client.delete_reasons || []).indexOf('기간 지남') < 0 &&
                        client.auto_analysis === 0 && (!currentUser || currentUser.role === 'viewer') && React.createElement('div', {
                            style: { marginTop: 6, textAlign: 'center', fontSize: 11, fontWeight: 700, color: '#92400e' }
                        }, '⏸ 자동 추적 중지됨'),

                        /* ---------- 왜 이 칸에 있는지 (2026-08-28) ----------
                           ⚠️ 사유를 안 적으면 「삭제 필요」에 왜 들어왔는지 몰라 손을 못 댄다.
                              한 업체가 여러 사유에 걸릴 수 있어 전부 보여 준다. */
                        (function() {
                            var chips = [];
                            var st = client.contract_stage;
                            if (st && (client.bucket === 'refund' || client.bucket === 'hold')) {
                                chips.push({ t: st + ' · 일시정지', c: '#6d28d9', bg: '#f5f3ff', bd: '#ddd6fe' });
                            }
                            (client.delete_reasons || []).forEach(function(r) {
                                chips.push({ t: r, c: '#b91c1c', bg: '#fef2f2', bd: '#fecaca' });
                            });
                            if (client.needs_check) {
                                chips.push({ t: '수집 실패 — 키워드 확인', c: '#0369a1', bg: '#f0f9ff', bd: '#bae6fd' });
                            }
                            if (!chips.length) return null;
                            return React.createElement('div', {
                                style: { marginTop: 6, display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'center' }
                            }, chips.map(function(ch, i) {
                                return React.createElement('span', {
                                    key: i,
                                    style: { fontSize: 10.5, fontWeight: 800, borderRadius: 999, padding: '2px 8px',
                                             color: ch.c, background: ch.bg, border: '1px solid ' + ch.bd, whiteSpace: 'nowrap' }
                                }, ch.t);
                            }));
                        })()
                    );
                })
            )
        )
    );
};
