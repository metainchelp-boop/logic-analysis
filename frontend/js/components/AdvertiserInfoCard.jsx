window.AdvertiserInfoCard = function AdvertiserInfoCard(props) {
  if (!props?.data) return null;
  const { adDepth, pcClicks, mobileClicks, compIdx } = props.data;

  var num = typeof fmt === 'function' ? fmt : function (x) { return x; };

  var items = [
    { label: '평균 광고 개수', value: adDepth ? (adDepth + '개') : '데이터 없음', unit: '',
      tip: '이 키워드로 네이버에서 검색하면 통합검색 상단 파워링크 영역에 광고가 평균 몇 개 노출되는지(네이버 검색광고 「월평균노출광고수」). 많을수록 광고 경쟁이 치열해 입찰가 부담이 큽니다.' },
    { label: 'PC 평균 클릭수', value: (pcClicks || pcClicks === 0) ? num(pcClicks) : '-', unit: '회' },
    { label: '모바일 평균 클릭수', value: (mobileClicks || mobileClicks === 0) ? num(mobileClicks) : '-', unit: '회' },
    { label: '광고 경쟁강도', value: compIdx || '-', unit: '' }
  ];

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
          <h3 className="rt-h3"><span className="rt-hic">📣</span>검색광고(파워링크) 경쟁 정보<span className="badge b-ok">✅ 실측</span></h3>
          <div className="rt-desc">네이버 <b>검색광고(파워링크)</b> 기준 — 통합검색 상단 광고 영역의 경쟁 환경입니다.
            <b style={{ color: '#b45309' }}> 이 화면의 쇼핑 검색 순위와는 다른 지표</b>입니다.</div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
            {items.map(function(item, idx) {
              return (
                <div key={idx} className="rt-kpi">
                  <div className="rt-kpi-k">
                    {item.label}
                    {item.tip && <span title={item.tip} style={{ marginLeft: 4, cursor: 'help', color: '#94a3b8', fontWeight: 800 }}>ⓘ</span>}
                  </div>
                  <div className="rt-kpi-v" style={{ fontSize: 20 }}>
                    {item.value}{item.unit && <small>{item.unit}</small>}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="note">
            <b>평균 광고 개수</b> = 이 키워드로 검색했을 때 <b>통합검색 상단 파워링크 영역</b>에 광고가 평균 몇 개 붙는지입니다
            (네이버 검색광고 「월평균노출광고수」 원본값). 순위가 아니라 <b>개수</b>이며, 많을수록 광고 경쟁이 치열해 입찰가 부담이 큽니다.
            <div style={{ marginTop: 8, padding: '9px 12px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, color: '#7c2d12' }}>
              ⚠️ <b>검색광고(파워링크)와 쇼핑검색은 다릅니다.</b><br />
              · <b>검색광고(파워링크)</b> — 네이버 통합검색 결과 상단의 링크형 광고. 이 카드의 지표가 여기 기준입니다.<br />
              · <b>쇼핑검색</b> — 쇼핑 탭의 상품 목록. 우리 <b>순위 추적·노출 순위</b>는 전부 이쪽 기준이며, 그 안의 광고(쇼핑검색광고)도 별개입니다.<br />
              즉 이 숫자가 크다고 쇼핑 순위가 나쁜 것은 아닙니다 — <b>서로 다른 지면</b>입니다.
            </div>
            광고 경쟁이 치열할수록 SEO(자연노출)를 병행해 광고비 효율을 확보하는 것이 유리합니다.
          </div>
        </div>
      </div>
    </div>
  );
};
