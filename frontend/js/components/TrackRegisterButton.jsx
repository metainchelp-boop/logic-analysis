/* TrackRegisterButton — 분석한 상품을 순위추적에 원클릭 등록
 * 기존 POST /api/products/track 재사용. 자동등록이 아니라 명시적 1클릭(서버 부하 방지).
 *
 * ⚠️ **업체 칸은 빼지 말 것** (2026-09-14 신고 #266 · 17일간 죽어 있던 버튼).
 *    2026-08-28 에 서버가 `client_id` 를 **필수**로 받게 바뀌었다(주인 없는 추적 상품 41개 차단).
 *    그때 `RankTrackingSection` 의 등록 버튼은 「업체 칸이 없으니 죽은 버튼이 된다」며 뺐는데,
 *    **같은 화면에 따로 렌더되는 이 형제 컴포넌트를 빠뜨렸다**(AnalysisResults.jsx).
 *    그래서 이 버튼은 8/28 부터 **누를 때마다 400** 이었다(9/14 실측: 400 10건 · 200 6건).
 *    ⭐ 교훈 — 「죽은 버튼을 뺐다」고 적을 때 **같은 일을 하는 버튼이 몇 개인지부터 센다.**
 *       `grep products/track` 를 했으면 3곳이 나왔다.
 */
window.TrackRegisterButton = function TrackRegisterButton(props) {
  var searchedProductUrl = props.searchedProductUrl;
  var searchedKeyword = props.searchedKeyword;
  var products = props.products;
  var refreshProducts = props.refreshProducts;
  var canEdit = props.canEdit;

  var st = React.useState(false);
  var adding = st[0], setAdding = st[1];

  /* 업체 피커 — 순위 추적 탭(KeywordRankPage)과 **같은 경로·같은 동작**을 쓴다.
     화면마다 다른 규칙으로 고르게 두면 「여기선 되는데 저기선 안 된다」가 또 생긴다. */
  var _q = React.useState(''); var query = _q[0], setQuery = _q[1];
  var _o = React.useState([]); var opts = _o[0], setOpts = _o[1];
  var _c = React.useState(null); var client = _c[0], setClient = _c[1];
  var _m = React.useState(null); var meta = _m[0], setMeta = _m[1];   // {total,truncated,blocked}
  var _e = React.useState(''); var err = _e[0], setErr = _e[1];

  /* 입력이 멈추고 250ms 뒤 한 번만 부른다(글자마다 부르면 서버를 두드린다). */
  React.useEffect(function() {
    var q = (query || '').trim();
    if (client || !q) { setOpts([]); setMeta(null); return; }
    var t = setTimeout(function() {
      api.get('/cd/clients-lookup?q=' + encodeURIComponent(q)).then(function(res) {
        if (res && res.success) {
          setOpts(res.data || []);
          setMeta({ total: res.total || 0, truncated: !!res.truncated, blocked: res.blocked || [] });
        } else { setOpts([]); setMeta(null); }
      }).catch(function() { setOpts([]); setMeta(null); });
    }, 250);
    return function() { clearTimeout(t); };
  }, [query, client]);

  if (!searchedProductUrl || !searchedKeyword || !canEdit) return null;

  var already = (products || []).find(function(p) { return p.product_url === searchedProductUrl; });
  var alreadyHasKw = already && (already.keywords || []).some(function(k) {
    return (typeof k === 'string' ? k : (k && k.keyword)) === searchedKeyword;
  });

  var onClick = function() {
    if (adding) return;
    /* ⚠️ 업체 없이 보내지 않는다 — 서버가 400 으로 거절한다(위 주석 참조).
       화면에서 먼저 막고 이유를 말해 주는 것이 이 수정의 핵심이다. */
    if (!client) { setErr('먼저 업체를 골라 주세요 — 목록에서 고른 업체만 등록됩니다.'); return; }
    setErr('');
    setAdding(true);
    api.post('/products/track', {
      product_url: searchedProductUrl,
      keywords: [searchedKeyword],
      client_id: client.id,
      store_name_hint: props.storeNameHint || undefined
    })
      .then(function(res) {
        if (res && res.success) {
          /* ⚠️ 「등록됨」과 「업체에 이어짐」은 다른 일이다 — 서버가 link 로 따로 답한다.
             성공했다고만 알리면 주인 없는 상품이 또 조용히 생긴다(순위 추적 탭과 같은 규칙). */
          var lk = (res.data && res.data.link) || null;
          if (lk && lk.linked === false) {
            setErr('상품은 등록됐지만 「' + client.name + '」에 잇지 못했습니다'
                   + (lk.reason ? ' — ' + lk.reason : '') + '.');
            if (typeof toast !== 'undefined' && toast.error) toast.error('업체 연결에 실패했습니다 — 순위 추적 탭에서 확인해 주세요.');
          } else {
            if (typeof toast !== 'undefined' && toast.success) toast.success('「' + client.name + '」 상품으로 등록했습니다. 첫 순위 체크를 시작합니다.');
          }
          if (refreshProducts) refreshProducts();
        } else {
          var msg = (res && res.detail) || '추적 등록에 실패했습니다.';
          setErr(msg);
          if (typeof toast !== 'undefined' && toast.error) toast.error(msg);
        }
        setAdding(false);
      })
      .catch(function(e) {
        var msg = '추적 등록 실패: ' + ((e && e.message) || '네트워크 오류');
        setErr(msg);
        if (typeof toast !== 'undefined' && toast.error) toast.error(msg);
        setAdding(false);
      });
  };

  var wrap = { display: 'flex', alignItems: 'center', gap: 10, margin: '4px 0 4px', flexWrap: 'wrap' };
  var inp = { border: '1px solid #cbd5e1', borderRadius: 8, padding: '8px 10px', fontSize: 12.5, fontFamily: 'inherit', background: '#fff', color: '#0f172a', width: 200 };

  /* 업체 고르는 칸 — 직원 운영 도구라 광고주 전달본(내보내기)에서는 제외(no-export) */
  function picker() {
    return React.createElement('div', { className: 'no-export', style: { position: 'relative' } },
      client
        ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, background: '#fff', border: '1px solid #3b82f6', borderRadius: 99, padding: '5px 8px 5px 11px', fontSize: 12.5, fontWeight: 800, color: '#2563eb', maxWidth: 220 } },
            React.createElement('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, client.name),
            React.createElement('button', {
              onClick: function() { setClient(null); setQuery(''); setErr(''); },
              title: '업체 다시 고르기',
              style: { border: 0, background: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '0 2px', fontWeight: 400 }
            }, '✕'))
        : React.createElement('input', {
            style: inp, value: query, placeholder: '업체명 검색 *', autoComplete: 'off',
            onChange: function(e) { setQuery(e.target.value); setErr(''); }
          }),
      !client && opts.length > 0 && React.createElement('div', {
        style: { position: 'absolute', zIndex: 20, left: 0, minWidth: 220, top: 'calc(100% + 4px)', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, boxShadow: '0 8px 20px rgba(15,23,42,.12)', maxHeight: 190, overflow: 'auto' }
      },
        opts.map(function(c) {
          return React.createElement('button', {
            key: c.id,
            onClick: function() { setClient(c); setOpts([]); setMeta(null); setErr(''); },
            style: { display: 'block', width: '100%', textAlign: 'left', border: 0, background: 'none', padding: '7px 11px', fontSize: 12.5, cursor: 'pointer', fontFamily: 'inherit', color: '#0f172a' }
          },
            c.name,
            c.role && c.role !== 'advertiser' && React.createElement('span', {
              style: { marginLeft: 6, fontSize: 10.5, fontWeight: 800, color: '#b45309' }
            }, c.role === 'prospect' ? '가망' : '경쟁사'));
        }),
        meta && meta.truncated && React.createElement('div', {
          style: { padding: '6px 11px', fontSize: 11, color: '#94a3b8', borderTop: '1px solid #f1f5f9' }
        }, meta.total + '곳 중 앞 30곳만 보입니다 — 더 입력해 좁혀 주세요.')
      )
    );
  }

  /* 왜 안 나오는지를 화면이 말한다 — 종전엔 그냥 0건이라 「업체가 사라졌다」로 읽혔다(신고 #265) */
  function hint() {
    if (err) return { color: '#b91c1c', text: err };
    if (client) return { color: '#64748b', text: '「' + client.name + '」 것으로 등록됩니다 — 그 업체 계약이 끝나면 추적도 함께 멈춥니다.' };
    if (meta && opts.length === 0 && (query || '').trim()) {
      if (meta.blocked && meta.blocked.length > 0) {
        return { color: '#b45309', text: '「' + meta.blocked[0].name + '」은(는) 내린 업체라 고를 수 없습니다 — 🏠 대시보드 → 🏢 등록 업체 → 「🗄 내린 업체」에서 ↩ 로 되살려 주세요.' };
      }
      return { color: '#b45309', text: '로직분석에 등록된 업체가 아닙니다 — 아래 「업체 저장」에서 새 업체로 먼저 만들어 주세요.' };
    }
    return { color: '#94a3b8', text: '업체는 목록에서 고른 것만 등록됩니다.' };
  }

  var h = hint();
  var hintEl = React.createElement('div', {
    className: 'no-export',
    style: { fontSize: 11.5, color: h.color, marginTop: 2, flexBasis: '100%' }
  }, h.text);

  if (already) {
    return React.createElement('div', { className: 'container' },
      React.createElement('div', { style: wrap },
        /* no-export: 직원용 운영 상태 표시 — 광고주 전달본(내보내기)에서는 제외 */
        React.createElement('span', {
          className: 'no-export',
          style: { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 10, background: '#ecfdf5', border: '1px solid #a7f3d0', color: '#047857', fontSize: 12.5, fontWeight: 700 }
        }, '✓ 이미 추적 중인 상품입니다' + (alreadyHasKw ? ' (이 키워드 포함)' : '')),
        !alreadyHasKw && picker(),
        !alreadyHasKw ? React.createElement('button', {
          onClick: onClick, disabled: adding || !client,
          className: 'no-export',
          style: { padding: '8px 14px', borderRadius: 10, border: '1px solid #c7d2fe', background: client ? '#eef2ff' : '#f1f5f9', color: client ? '#3b82f6' : '#94a3b8', fontSize: 12.5, fontWeight: 700, cursor: (adding || !client) ? 'default' : 'pointer' }
        }, adding ? '등록 중...' : '＋ 이 키워드도 추적 추가') : null,
        !alreadyHasKw && hintEl
      )
    );
  }

  return React.createElement('div', { className: 'container' },
    React.createElement('div', { style: wrap },
      picker(),
      React.createElement('button', {
        onClick: onClick, disabled: adding || !client,
        style: {
          display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderRadius: 10,
          border: 'none', background: (adding || !client) ? '#94a3b8' : 'linear-gradient(135deg,#3b82f6,#3b82f6)', color: '#fff',
          fontSize: 13, fontWeight: 700, cursor: (adding || !client) ? 'default' : 'pointer', boxShadow: '0 3px 10px rgba(79,70,229,0.3)'
        }
      }, adding ? '⏳ 등록 중...' : '🔍 이 상품 순위 추적 시작'),
      React.createElement('span', { className: 'no-export', style: { fontSize: 11.5, color: '#94a3b8' } }, '이후 이 키워드의 순위 변화를 자동 기록합니다'),
      hintEl
    )
  );
};
