/* TrackRegisterButton — 분석한 상품을 순위추적에 원클릭 등록
 * 기존 POST /api/products/track 재사용. 자동등록이 아니라 명시적 1클릭(서버 부하 방지). */
window.TrackRegisterButton = function TrackRegisterButton(props) {
  var searchedProductUrl = props.searchedProductUrl;
  var searchedKeyword = props.searchedKeyword;
  var products = props.products;
  var refreshProducts = props.refreshProducts;
  var canEdit = props.canEdit;

  var st = React.useState(false);
  var adding = st[0], setAdding = st[1];

  if (!searchedProductUrl || !searchedKeyword || !canEdit) return null;

  var already = (products || []).find(function(p) { return p.product_url === searchedProductUrl; });
  var alreadyHasKw = already && (already.keywords || []).some(function(k) {
    return (typeof k === 'string' ? k : (k && k.keyword)) === searchedKeyword;
  });

  var onClick = function() {
    if (adding) return;
    setAdding(true);
    api.post('/products/track', { product_url: searchedProductUrl, keywords: [searchedKeyword] })
      .then(function(res) {
        if (res && res.success) {
          if (typeof toast !== 'undefined' && toast.success) toast.success('순위 추적에 등록했습니다. 첫 순위 체크를 시작합니다.');
          if (refreshProducts) refreshProducts();
        } else {
          if (typeof toast !== 'undefined' && toast.error) toast.error((res && res.detail) || '추적 등록에 실패했습니다.');
        }
        setAdding(false);
      })
      .catch(function(e) {
        if (typeof toast !== 'undefined' && toast.error) toast.error('추적 등록 실패: ' + (e.message || '네트워크 오류'));
        setAdding(false);
      });
  };

  var wrap = { display: 'flex', alignItems: 'center', gap: 10, margin: '4px 0 4px', flexWrap: 'wrap' };

  if (already) {
    return React.createElement('div', { className: 'container' },
      React.createElement('div', { style: wrap },
        React.createElement('span', {
          style: { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 10, background: '#ecfdf5', border: '1px solid #a7f3d0', color: '#047857', fontSize: 12.5, fontWeight: 700 }
        }, '✓ 이미 추적 중인 상품입니다' + (alreadyHasKw ? ' (이 키워드 포함)' : '')),
        !alreadyHasKw ? React.createElement('button', {
          onClick: onClick, disabled: adding,
          style: { padding: '8px 14px', borderRadius: 10, border: '1px solid #c7d2fe', background: '#eef2ff', color: '#4f46e5', fontSize: 12.5, fontWeight: 700, cursor: adding ? 'default' : 'pointer' }
        }, adding ? '등록 중...' : '＋ 이 키워드도 추적 추가') : null
      )
    );
  }

  return React.createElement('div', { className: 'container' },
    React.createElement('div', { style: wrap },
      React.createElement('button', {
        onClick: onClick, disabled: adding,
        style: {
          display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderRadius: 10,
          border: 'none', background: adding ? '#94a3b8' : 'linear-gradient(135deg,#4f46e5,#6366f1)', color: '#fff',
          fontSize: 13, fontWeight: 700, cursor: adding ? 'default' : 'pointer', boxShadow: '0 3px 10px rgba(79,70,229,0.3)'
        }
      }, adding ? '⏳ 등록 중...' : '🔍 이 상품 순위 추적 시작'),
      React.createElement('span', { style: { fontSize: 11.5, color: '#94a3b8' } }, '이후 이 키워드의 순위 변화를 자동 기록합니다')
    )
  );
};
