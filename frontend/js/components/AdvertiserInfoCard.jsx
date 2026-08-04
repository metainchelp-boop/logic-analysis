window.AdvertiserInfoCard = function AdvertiserInfoCard(props) {
  if (!props?.data) return null;
  const { adDepth, pcClicks, mobileClicks, compIdx } = props.data;

  var num = typeof fmt === 'function' ? fmt : function (x) { return x; };

  var items = [
    { label: '광고 노출 깊이', value: adDepth ? ('상위 ' + adDepth + '개') : '-', unit: '' },
    { label: 'PC 평균 클릭수', value: (pcClicks || pcClicks === 0) ? num(pcClicks) : '-', unit: '회' },
    { label: '모바일 평균 클릭수', value: (mobileClicks || mobileClicks === 0) ? num(mobileClicks) : '-', unit: '회' },
    { label: '광고 경쟁강도', value: compIdx || '-', unit: '' }
  ];

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
          <h3 className="rt-h3"><span className="rt-hic">📣</span>광고 경쟁 정보<span className="badge b-ok">✅ 실측</span></h3>
          <div className="rt-desc">네이버 검색광고 기준 — 이 키워드에 광고로 들어올 때의 경쟁 환경</div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
            {items.map(function(item, idx) {
              return (
                <div key={idx} className="rt-kpi">
                  <div className="rt-kpi-k">{item.label}</div>
                  <div className="rt-kpi-v" style={{ fontSize: 20 }}>
                    {item.value}{item.unit && <small>{item.unit}</small>}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="note">'광고 노출 깊이 = 상위 N개'는 이 키워드에서 검색광고가 평균적으로 <b>상위 몇 번째 슬롯까지 노출</b>되는지를 뜻합니다(값이 클수록 광고 노출 경쟁이 넓음). 광고 경쟁이 치열할수록 입찰가 부담이 커지므로, SEO(자연노출)를 병행해 광고비 효율을 확보하는 것이 유리합니다.</div>
        </div>
      </div>
    </div>
  );
};
