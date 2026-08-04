/* DatalabCategoryKeywordsSection — 카테고리 인기 키워드 TOP (v6) */
window.DatalabCategoryKeywordsSection = function DatalabCategoryKeywordsSection(props) {
  if (!props?.data) return null;
  var popular = props.data.popular || [];
  var rising = props.data.rising || [];
  if (popular.length === 0 && rising.length === 0) return null;

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
          <h3 className="rt-h3"><span className="rt-hic">🔥</span>카테고리 인기 · 급상승 키워드<span className="badge b-dl">📊 데이터랩</span></h3>
          <div className="grid2">
            {/* 인기 키워드 TOP */}
            <div>
              <div className="sub-card">
                <div className="st">🏆 인기 키워드 TOP</div>
                {popular.length === 0 && <div style={{ fontSize: 12, color: '#94a3b8', padding: '6px 0' }}>이 카테고리 기준 집계된 인기 키워드가 없습니다.</div>}
                {popular.length > 0 && <table className="rt-table">
                  <tbody>
                    {popular.map(function(kw, i) {
                      return (
                        <tr key={i}>
                          <td>{i + 1}</td>
                          <td><b>{kw.keyword}</b></td>
                          <td style={{ textAlign: 'right' }}>{i === 0 ? '검색 ' : ''}{fmt(kw.volume)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>}
              </div>
            </div>

            {/* 급상승 키워드 */}
            <div>
              <div className="sub-card">
                <div className="st">📈 급상승 키워드</div>
                {rising.length === 0 && <div style={{ fontSize: 12, color: '#94a3b8', padding: '6px 0' }}>이 카테고리 기준 급상승 키워드가 집계되지 않았습니다.</div>}
                {rising.length > 0 && <table className="rt-table">
                  <tbody>
                    {rising.map(function(kw, i) {
                      var isPositive = kw.growth >= 0;
                      var growthAbs = Math.abs(kw.growth);
                      var psClass = isPositive ? 'ps ps-g' : 'ps ps-r';
                      var arrow = isPositive ? '▲' : '▼';
                      return (
                        <tr key={i}>
                          <td><b>{kw.keyword}</b></td>
                          <td style={{ textAlign: 'right' }}>
                            <span className={psClass}>{arrow} {isPositive ? '+' : ''}{kw.growth}%</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>}
              </div>
            </div>
          </div>

          <div className="note">
            {props.data.note || '급상승 키워드를 상품명 · 태그에 반영하면 시즌 트렌드 수혜를 빠르게 받을 수 있습니다.'}
          </div>
        </div>
      </div>
    </div>
  );
};
