/* CompetitorCompareSection — 광고주 vs 경쟁사 비교 분석 (1차 + AI 대결 코칭)
 *
 * 업체(광고주) 상세 안에 렌더. 경쟁사 등록(광고주와 동일 분석 흐름 재사용)·목록·삭제 +
 * 선택한 경쟁사와의 좌우 비교(핵심지표·종합 레이더·키워드 갭·따라가야 할 것) + AI 코칭.
 *
 * 무손실 원칙: 경쟁사 미등록/데이터 없음이면 슬롯만 조용히 표시(기존 화면 무영향).
 * 저장된 분석 JSON 구조가 조금씩 달라도 방어적으로 추출(없으면 '집계 없음').
 */
window.CompetitorCompareSection = function CompetitorCompareSection(props) {
  var advClient = props.client;                 // 선택된 광고주 업체
  var canEdit = props.canEdit !== false;
  var onRegisterCompetitor = props.onRegisterCompetitor;  // 경쟁사 등록 모드 진입(App)
  var _R = React;
  var comps = _R.useState([]); var competitors = comps[0]; var setCompetitors = comps[1];
  var sel = _R.useState(null); var selectedId = sel[0]; var setSelectedId = sel[1];
  var cmp = _R.useState(null); var compareData = cmp[0]; var setCompareData = cmp[1];
  var ld = _R.useState(false); var loading = ld[0]; var setLoading = ld[1];
  var coach = _R.useState(null); var coaching = coach[0]; var setCoaching = coach[1];
  var coachLd = _R.useState(false); var coachLoading = coachLd[0]; var setCoachLoading = coachLd[1];

  var advId = advClient && advClient.id;

  var loadCompetitors = function() {
    if (!advId) return;
    api.get('/cd/' + advId + '/competitors').then(function(res) {
      if (res && res.success) setCompetitors(res.data || []);
    }).catch(function() {});
  };
  _R.useEffect(function() { setCompetitors([]); setSelectedId(null); setCompareData(null); setCoaching(null); loadCompetitors(); }, [advId]);

  /* ── 방어적 지표 추출 (저장된 분석 1건 → 표준 지표) ── */
  function num(v) { var n = parseInt(String(v == null ? '' : v).replace(/[^0-9.-]/g, ''), 10); return isNaN(n) ? null : n; }
  function metrics(analysis) {
    var a = (analysis && analysis.analysis_data) || {};
    var adv = (analysis && analysis.advertiser_data) || {};
    var vol = (analysis && analysis.volume_data) || [];
    var v0 = (Array.isArray(vol) && vol[0]) || {};
    var hd = (a.htmlDetail && a.htmlDetail.reviewData) || {};
    var ra = a.reviewAnalysis || {};
    var rc = ra.reviewCount || {};
    var rt = ra.rating || {};
    var rank = (adv.ranking && adv.ranking.current_rank != null) ? adv.ranking.current_rank : null;
    var price = (adv.product_info && adv.product_info.price) ? adv.product_info.price
      : (a.marketRevenue && num(a.marketRevenue.avgPrice));
    var reviews = (hd.reviewCount != null) ? hd.reviewCount : (rc.adv != null ? rc.adv : null);
    var rating = (hd.rating != null) ? hd.rating : (rt.adv != null ? Number(rt.adv) : null);
    var score = (adv.entry_strategy && adv.entry_strategy.overall_score) || null;
    var dq = (a.detailPageQuality && (a.detailPageQuality.totalScore || a.detailPageQuality.score)) || null;
    var name = (adv.product_info && adv.product_info.product_name)
      || (a.targetProductInfo && a.targetProductInfo.product_name) || '';
    var relKw = ((analysis && analysis.related_data && analysis.related_data.related_keywords) || [])
      .map(function(k) { return typeof k === 'string' ? k : (k && k.keyword) || ''; }).filter(Boolean);
    return {
      keyword: analysis ? analysis.keyword : '', productName: name,
      rank: rank, price: price ? Number(price) : null, reviews: reviews != null ? Number(reviews) : null,
      rating: rating, score: score ? Number(score) : null, detailQuality: dq ? Number(dq) : null,
      compIdx: v0.compIdx || '', relatedKeywords: relKw
    };
  }

  var runCompare = function(competitorId) {
    setSelectedId(competitorId); setCompareData(null); setCoaching(null); setLoading(true);
    api.get('/cd/compare?advertiser_id=' + advId + '&competitor_id=' + competitorId).then(function(res) {
      setLoading(false);
      if (res && res.success && res.data) {
        var d = res.data;
        setCompareData({
          advName: d.advertiser.name, compName: d.competitor.name,
          adv: metrics(d.advertiser.analysis), comp: metrics(d.competitor.analysis),
          advHas: !!d.advertiser.analysis, compHas: !!d.competitor.analysis
        });
      }
    }).catch(function() { setLoading(false); });
  };

  var handleDeleteCompetitor = function(cid, cname) {
    if (!confirm("경쟁사 '" + cname + "'를 삭제할까요? 비교 데이터가 사라집니다.")) return;
    api.del('/cd/' + cid).then(function() {
      try { toast.success("경쟁사 '" + cname + "' 삭제됨"); } catch (e) {}
      if (selectedId === cid) { setSelectedId(null); setCompareData(null); }
      loadCompetitors();
    }).catch(function(e) { try { toast.error('삭제 실패'); } catch (e2) {} });
  };

  /* ── 비교 계산 (격차·우열) ── */
  function fmtWon(v) { return v == null ? '집계 없음' : fmt(v) + '원'; }
  function pct(a, b) { if (a == null || b == null || b === 0) return null; return Math.round((a - b) / Math.abs(b) * 100); }

  function buildRows(c) {
    var A = c.adv, B = c.comp;
    // higherBetter: true면 값 클수록 광고주 우세
    var defs = [
      { k: '노출 순위', a: A.rank, b: B.rank, fmt: function(v){ return v == null ? '집계 없음' : v + '위'; }, higher: false },
      { k: '판매가', a: A.price, b: B.price, fmt: fmtWon, higher: false },
      { k: '리뷰 수', a: A.reviews, b: B.reviews, fmt: function(v){ return v == null ? '집계 없음' : fmt(v) + '건'; }, higher: true },
      { k: '평점', a: A.rating, b: B.rating, fmt: function(v){ return v == null ? '집계 없음' : Number(v).toFixed(1); }, higher: true },
      { k: '종합 진입 점수', a: A.score, b: B.score, fmt: function(v){ return v == null ? '집계 없음' : v + '점'; }, higher: true },
      { k: '상세페이지 품질', a: A.detailQuality, b: B.detailQuality, fmt: function(v){ return v == null ? '집계 없음' : v + '점'; }, higher: true }
    ];
    return defs.map(function(d) {
      var advWin = null, gap = null;
      if (d.a != null && d.b != null) {
        advWin = d.higher ? (d.a >= d.b) : (d.a <= d.b);
        gap = pct(d.a, d.b);
      }
      return { label: d.k, aStr: d.fmt(d.a), bStr: d.fmt(d.b), advWin: advWin, gap: gap, higher: d.higher, a: d.a, b: d.b };
    });
  }

  /* 따라가야 할 것 — 경쟁사가 앞선(광고주 열세) 지표를 격차 큰 순으로 */
  function catchUp(rows) {
    var acts = {
      '리뷰 수': '체험단·구매후기 이벤트로 리뷰 확보',
      '종합 진입 점수': '상품명·태그·상세페이지 SEO 보강',
      '상세페이지 품질': '이미지·성분표·인증마크 등 상세 콘텐츠 보강',
      '노출 순위': '위 항목 개선 + 파워링크 상위 입찰 병행',
      '평점': '리뷰 관리·CS 개선으로 평점 방어'
    };
    return rows.filter(function(r) { return r.advWin === false; })
      .sort(function(x, y) { return Math.abs(y.gap || 0) - Math.abs(x.gap || 0); })
      .slice(0, 4)
      .map(function(r) { return { label: r.label, gapStr: (r.gap != null ? (r.gap > 0 ? '+' : '') + r.gap + '%' : ''), act: acts[r.label] || '개선 필요' }; });
  }
  function strengths(rows) {
    return rows.filter(function(r) { return r.advWin === true; }).map(function(r) { return r.label; });
  }

  /* 키워드 커버리지 갭 — 경쟁사 연관 키워드 중 광고주에 없는 것 */
  function coverageGap(c) {
    var advSet = {}; (c.adv.relatedKeywords || []).forEach(function(k){ advSet[k] = 1; });
    return (c.comp.relatedKeywords || []).filter(function(k){ return !advSet[k]; }).slice(0, 8);
  }

  /* 레이더 5축 점수(0~100) — 저장 지표에서 파생 (없으면 50 중립) */
  function radarScores(m, other) {
    function rankScore(r) { return r == null ? 50 : Math.max(0, Math.min(100, Math.round(100 - (r - 1) * 1.1))); }
    function relPrice(p, q) { if (p == null || q == null) return 50; return p <= q ? 70 + Math.min(25, Math.round((q - p) / q * 100)) : 50 - Math.min(30, Math.round((p - q) / q * 100)); }
    function trust(rev, rat) { var s = 40; if (rev != null) s = Math.min(90, 30 + Math.round(Math.log10(Math.max(1, rev)) * 18)); if (rat != null) s += Math.round((rat - 4.5) * 20); return Math.max(0, Math.min(100, s)); }
    return [
      rankScore(m.rank),
      relPrice(m.price, other.price),
      trust(m.reviews, m.rating),
      m.score != null ? m.score : 50,
      m.detailQuality != null ? m.detailQuality : 50
    ];
  }

  var requestCoaching = function() {
    if (!compareData) return;
    setCoachLoading(true); setCoaching(null);
    var rows = buildRows(compareData);
    var summary = rows.map(function(r) {
      return '- ' + r.label + ': 광고주 ' + r.aStr + ' / 경쟁사 ' + r.bStr
        + (r.advWin == null ? '' : (r.advWin ? ' (광고주 우세)' : ' (경쟁사 우세' + (r.gap != null ? ', 격차 ' + r.gap + '%' : '') + ')'));
    }).join('\n');
    var gap = coverageGap(compareData);
    if (gap.length) summary += '\n- 광고주가 놓친 경쟁사 키워드: ' + gap.join(', ');
    api.post('/cd/compare-coaching', { advertiser_id: advId, competitor_id: selectedId, summary: summary }).then(function(res) {
      setCoachLoading(false);
      if (res && res.success && res.data) setCoaching(res.data);
    }).catch(function() { setCoachLoading(false); setCoaching({ available: false, message: 'AI 코칭 생성 실패' }); });
  };

  /* ─────────── 렌더 ─────────── */
  if (!advId) return null;
  var C = window.React.createElement;

  /* 슬롯(등록·목록) */
  var slot = C('div', { className: 'card', style: { padding: '16px 20px', marginBottom: 16, border: '1px solid #fed7aa', background: 'linear-gradient(120deg,#fff,#fff7ed)' } },
    C('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 } },
      C('span', { style: { fontSize: 15, fontWeight: 800, color: '#c2410c' } }, '⚔️ 경쟁사 비교'),
      C('span', { style: { fontSize: 11.5, color: '#94a3b8' } }, '— 광고주와 나란히 비교할 상대를 등록하세요')
    ),
    competitors.length === 0
      ? C('div', { style: { fontSize: 12.5, color: '#94a3b8', padding: '4px 0 10px' } }, '등록된 경쟁사가 없습니다.')
      : C('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 } },
          competitors.map(function(cc) {
            var isSel = selectedId === cc.id;
            return C('div', { key: cc.id, style: { display: 'flex', alignItems: 'center', gap: 10, background: isSel ? '#fff7ed' : '#fff', border: '1px solid ' + (isSel ? '#fdba74' : '#fed7aa'), borderRadius: 10, padding: '8px 12px' } },
              C('div', { style: { minWidth: 0, flex: 1 } },
                C('div', { style: { fontWeight: 700, fontSize: 13, color: '#0f172a' } }, cc.name),
                C('div', { style: { fontSize: 11, color: '#94a3b8' } }, cc.has_analysis ? ('키워드: ' + (cc.latest_keyword || '-') + ' · ' + (cc.latest_date || '')) : '분석 기록 없음 — 경쟁사 상품을 분석해 저장하세요')
              ),
              C('button', { onClick: function() { runCompare(cc.id); }, disabled: !cc.has_analysis,
                style: { fontSize: 11.5, fontWeight: 800, color: '#fff', background: cc.has_analysis ? '#c2410c' : '#cbd5e1', border: 'none', borderRadius: 8, padding: '6px 12px', cursor: cc.has_analysis ? 'pointer' : 'not-allowed' } }, '⚔️ 비교'),
              canEdit && C('button', { onClick: function() { handleDeleteCompetitor(cc.id, cc.name); }, title: '경쟁사 삭제',
                style: { fontSize: 12, fontWeight: 800, color: '#dc2626', background: '#fff', border: '1px solid #fecaca', borderRadius: 8, width: 28, height: 28, cursor: 'pointer' } }, '✕')
            );
          })
        ),
    canEdit && C('button', { onClick: function() { if (onRegisterCompetitor) onRegisterCompetitor(advClient); },
      style: { fontSize: 12.5, fontWeight: 800, color: '#c2410c', background: '#fff', border: '1.5px dashed #fdba74', borderRadius: 10, padding: '9px 14px', cursor: 'pointer', width: '100%' } },
      '➕ 경쟁사 등록 (분석 화면에서 경쟁사 상품을 분석 → 저장)')
  );

  var body = null;
  if (loading) {
    body = C('div', { className: 'card', style: { padding: 24, textAlign: 'center', color: '#64748b', fontSize: 13 } }, '비교 데이터를 불러오는 중…');
  } else if (compareData) {
    var c = compareData;
    if (!c.advHas || !c.compHas) {
      body = C('div', { className: 'card', style: { padding: 18, fontSize: 13, color: '#92400e', background: '#fffbeb', border: '1px solid #fde68a' } },
        (!c.advHas ? '광고주' : '경쟁사') + ' 분석 기록이 없어 비교할 수 없습니다. 해당 업체를 먼저 분석해 저장하세요.');
    } else {
      var rows = buildRows(c);
      var ups = catchUp(rows); var strs = strengths(rows); var gap = coverageGap(c);
      var rA = radarScores(c.adv, c.comp), rB = radarScores(c.comp, c.adv);

      body = C('div', null,
        /* 대진표 */
        C('div', { className: 'card', style: { padding: '16px 20px', marginBottom: 12 } },
          C('div', { style: { display: 'grid', gridTemplateColumns: '1fr 44px 1fr', gap: 10, alignItems: 'center' } },
            C('div', { style: { textAlign: 'center', background: 'linear-gradient(135deg,#eef2ff,#e0e7ff)', border: '1px solid #c7d2fe', borderRadius: 12, padding: '12px 10px' } },
              C('div', { style: { fontSize: 10.5, fontWeight: 800, color: '#4338ca' } }, '광고주'),
              C('div', { style: { fontSize: 15, fontWeight: 800, color: '#0f172a', margin: '3px 0' } }, c.advName),
              C('div', { style: { fontSize: 12, color: '#475569' } }, c.adv.keyword + (c.adv.rank != null ? ' · ' + c.adv.rank + '위' : ''))
            ),
            C('div', { style: { width: 44, height: 44, borderRadius: '50%', background: '#0f172a', color: '#fff', fontWeight: 800, fontSize: 13, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto' } }, 'VS'),
            C('div', { style: { textAlign: 'center', background: 'linear-gradient(135deg,#fff7ed,#ffedd5)', border: '1px solid #fed7aa', borderRadius: 12, padding: '12px 10px' } },
              C('div', { style: { fontSize: 10.5, fontWeight: 800, color: '#c2410c' } }, '경쟁사'),
              C('div', { style: { fontSize: 15, fontWeight: 800, color: '#0f172a', margin: '3px 0' } }, c.compName),
              C('div', { style: { fontSize: 12, color: '#475569' } }, c.comp.keyword + (c.comp.rank != null ? ' · ' + c.comp.rank + '위' : ''))
            )
          )
        ),
        /* 핵심 지표 비교표 */
        C('div', { className: 'card', style: { padding: '16px 20px', marginBottom: 12 } },
          C('h3', { className: 'rt-h3' }, C('span', { className: 'rt-hic' }, '⚔️'), '핵심 지표 비교'),
          C('table', { className: 'rt-table', style: { width: '100%', marginTop: 6 } },
            C('thead', null, C('tr', null,
              C('th', null, '지표'), C('th', { style: { textAlign: 'center' } }, '광고주'),
              C('th', { style: { textAlign: 'center' } }, '경쟁사'), C('th', { style: { textAlign: 'center' } }, '우열'))),
            C('tbody', null, rows.map(function(r, i) {
              var aBg = r.advWin === true ? '#ecfdf5' : r.advWin === false ? '#fef2f2' : undefined;
              var bBg = r.advWin === false ? '#ecfdf5' : r.advWin === true ? '#fef2f2' : undefined;
              return C('tr', { key: i },
                C('td', { style: { fontWeight: 600 } }, r.label),
                C('td', { style: { textAlign: 'center', fontWeight: 800, background: aBg } }, r.aStr),
                C('td', { style: { textAlign: 'center', fontWeight: 800, background: bBg } }, r.bStr),
                C('td', { style: { textAlign: 'center' } }, r.advWin == null
                  ? C('span', { style: { color: '#cbd5e1' } }, '—')
                  : C('span', { style: { fontWeight: 800, color: r.advWin ? '#059669' : '#dc2626' } },
                      (r.advWin ? '▲ 우세' : '▼ 열세') + (r.gap != null ? ' ' + Math.abs(r.gap) + '%' : '')))
              );
            }))
          )
        ),
        /* 종합 레이더 */
        C(window.CompetitorRadar || 'div', { advScores: rA, compScores: rB }),
        /* 키워드 커버리지 갭 */
        gap.length > 0 && C('div', { className: 'card', style: { padding: '16px 20px', marginBottom: 12 } },
          C('h3', { className: 'rt-h3' }, C('span', { className: 'rt-hic' }, '🔗'), '키워드 커버리지 갭'),
          C('div', { className: 'rt-desc' }, '경쟁사가 노출되는데 광고주가 놓친 세부 키워드 — 태그·상품명 반영 후보'),
          C('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 6 } }, gap.map(function(k, i) {
            return C('span', { key: i, style: { fontSize: 12, fontWeight: 700, background: '#fff7ed', color: '#c2410c', border: '1px solid #fed7aa', borderRadius: 99, padding: '4px 11px' } }, k);
          }))
        ),
        /* 따라가야 할 것 + 강점 */
        C('div', { className: 'card', style: { padding: '16px 20px', marginBottom: 12, background: '#0f172a' } },
          C('div', { style: { fontSize: 14, fontWeight: 800, color: '#fff', marginBottom: 10 } }, '🎯 따라가야 할 것'),
          ups.length === 0
            ? C('div', { style: { fontSize: 12.5, color: '#6ee7b7' } }, '핵심 지표에서 광고주가 뒤지는 항목이 없습니다. 현 우위를 유지하세요.')
            : C('div', null, ups.map(function(u, i) {
                return C('div', { key: i, style: { display: 'flex', gap: 10, padding: '8px 0', borderTop: i ? '1px solid #1e293b' : 'none' } },
                  C('span', { style: { width: 22, height: 22, borderRadius: 7, background: '#f97316', color: '#fff', fontWeight: 800, fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 } }, i + 1),
                  C('div', { style: { fontSize: 12.5, color: '#e2e8f0' } },
                    C('b', { style: { color: '#fff' } }, u.label + (u.gapStr ? ' ' + u.gapStr : '')),
                    C('span', { style: { color: '#fdba74', fontWeight: 700 } }, ' → ' + u.act))
                );
              })),
          strs.length > 0 && C('div', { style: { marginTop: 10, background: '#052e2b', border: '1px solid #134e4a', borderRadius: 10, padding: '9px 13px', fontSize: 12, color: '#6ee7b7' } },
            '💪 유지할 강점: ' + strs.join(' · '))
        ),
        /* AI 대결 코칭 */
        C('div', { className: 'card', style: { padding: '16px 20px', marginBottom: 12, border: '1px solid #ddd6fe', background: '#f5f3ff' } },
          C('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 } },
            C('span', { style: { fontSize: 14, fontWeight: 800, color: '#4c1d95' } }, '🤖 AI 대결 코칭'),
            C('span', { className: 'badge b-ai' }, 'AI')),
          !coaching && !coachLoading && C('button', { onClick: requestCoaching,
            style: { fontSize: 12.5, fontWeight: 800, color: '#fff', background: '#7c3aed', border: 'none', borderRadius: 9, padding: '9px 16px', cursor: 'pointer' } },
            '“' + c.advName + '가 ' + c.compName + '를 이기려면” 전략 생성'),
          coachLoading && C('div', { style: { fontSize: 12.5, color: '#7c3aed' } }, '⏳ AI가 두 업체 데이터를 분석 중… (약 10~20초)'),
          coaching && coaching.available && C('div', { style: { fontSize: 13, color: '#312e81', lineHeight: 1.75, whiteSpace: 'pre-wrap' } }, coaching.text),
          coaching && !coaching.available && C('div', { style: { fontSize: 12.5, color: '#92400e' } }, coaching.message || 'AI 코칭을 사용할 수 없습니다.')
        )
      );
    }
  }

  return C('div', { style: { marginBottom: 16 } }, slot, body);
};

/* CompetitorRadar — 5축 레이더 (광고주 인디고 / 경쟁사 주황) — 순수 SVG */
window.CompetitorRadar = function CompetitorRadar(props) {
  var C = React.createElement;
  var axes = ['노출', '가격', '신뢰', 'SEO', '콘텐츠'];
  var adv = props.advScores || [50, 50, 50, 50, 50];
  var comp = props.compScores || [50, 50, 50, 50, 50];
  var cx = 130, cy = 120, R = 82, N = 5;
  function pt(i, v) { var ang = -Math.PI / 2 + i * 2 * Math.PI / N; var r = R * Math.max(0, Math.min(100, v)) / 100; return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)]; }
  function poly(vals) { return vals.map(function(v, i) { return pt(i, v).join(','); }).join(' '); }
  var grid = [25, 50, 75, 100].map(function(f, gi) {
    return C('polygon', { key: 'g' + gi, points: axes.map(function(_, i) { return pt(i, f).join(','); }).join(' '), fill: 'none', stroke: '#e2e8f0' });
  });
  var spokes = axes.map(function(ax, i) {
    var p = pt(i, 100); var lp = pt(i, 122);
    return C('g', { key: 's' + i },
      C('line', { x1: cx, y1: cy, x2: p[0], y2: p[1], stroke: '#e2e8f0' }),
      C('text', { x: lp[0], y: lp[1], fontSize: 10, fill: '#64748b', fontWeight: 700, textAnchor: 'middle', dominantBaseline: 'middle' }, ax));
  });
  return C('div', { className: 'card', style: { padding: '16px 20px', marginBottom: 12 } },
    C('h3', { className: 'rt-h3' }, C('span', { className: 'rt-hic' }, '🕸️'), '종합 레이더'),
    C('div', { style: { display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'center' } },
      C('svg', { width: 260, height: 240, viewBox: '0 0 260 240' },
        grid, spokes,
        C('polygon', { points: poly(comp), fill: 'rgba(249,115,22,.15)', stroke: '#f97316', strokeWidth: 2 }),
        C('polygon', { points: poly(adv), fill: 'rgba(79,70,229,.20)', stroke: '#4f46e5', strokeWidth: 2 })
      ),
      C('div', { style: { fontSize: 12 } },
        C('div', { style: { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 } }, C('span', { style: { width: 12, height: 12, borderRadius: 3, background: '#4f46e5', display: 'inline-block' } }), '광고주'),
        C('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } }, C('span', { style: { width: 12, height: 12, borderRadius: 3, background: '#f97316', display: 'inline-block' } }), '경쟁사'))
    )
  );
};
