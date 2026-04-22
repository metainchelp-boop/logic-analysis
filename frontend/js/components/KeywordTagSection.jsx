window.KeywordTagSection = function KeywordTagSection(props) {
  if (!props?.data) return null;
  const { topKeywords, totalFound } = props.data;

  if (!topKeywords || topKeywords.length === 0) return null;

  const maxVolume = Math.max.apply(null, topKeywords.map(function(kw) { return typeof kw.volume === 'number' ? kw.volume : 0; })) || 1;

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' }}>🏷️</span>
          키워드 &amp; 태그 분석
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">상품명에서 자주 쓰이는 키워드를 분석합니다</p>

        <div style={{
          background: '#fff',
          borderRadius: 16,
          padding: 24,
          border: '1px solid #e2e8f0',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>
              💬 상품명 주요 키워드 TOP {Math.min(topKeywords.length, 15)}
            </div>
            <span style={{
              padding: '4px 12px',
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 700,
              background: 'linear-gradient(135deg, #eef2ff, #dbeafe)',
              color: '#4f46e5'
            }}>총 {fmt(totalFound)}개 발견</span>
          </div>

          <div className="table-wrap" style={{ maxHeight: 340, overflowY: 'auto' }}>
            <table>
              <thead>
                <tr style={{ background: 'linear-gradient(135deg, #4f46e5, #7c3aed)' }}>
                  <th style={{ color: '#fff', fontWeight: 600, fontSize: 12 }}>#</th>
                  <th style={{ color: '#fff', fontWeight: 600, fontSize: 12 }}>키워드</th>
                  <th style={{ color: '#fff', fontWeight: 600, fontSize: 12 }}>검색량</th>
                  <th style={{ color: '#fff', fontWeight: 600, fontSize: 12 }}>경쟁도</th>
                  <th style={{ color: '#fff', fontWeight: 600, fontSize: 12 }}>비중</th>
                </tr>
              </thead>
              <tbody>
                {topKeywords.map(function(kw, idx) {
                  var barPercent = typeof kw.volume === 'number' ? Math.round((kw.volume / maxVolume) * 100) : 0;
                  return (
                    <tr key={idx} style={{ background: idx % 2 === 0 ? '#fff' : '#f8fafc' }}>
                      <td>
                        <span style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          width: 28,
                          height: 28,
                          background: kw.isGolden
                            ? 'linear-gradient(135deg, #f59e0b, #d97706)'
                            : 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                          color: '#fff',
                          borderRadius: '50%',
                          fontSize: 11,
                          fontWeight: 700
                        }}>{idx + 1}</span>
                      </td>
                      <td style={{ fontWeight: 600, color: '#0f172a', fontSize: 13 }}>
                        {kw.keyword}
                        {kw.isGolden && <span style={{ marginLeft: 6 }}>👑</span>}
                      </td>
                      <td style={{ fontSize: 13, color: '#0f172a' }}>{fmt(kw.volume)}</td>
                      <td>
                        <span style={{
                          padding: '4px 12px',
                          borderRadius: 999,
                          fontSize: 12,
                          fontWeight: 700,
                          background: kw.comp === '낮음' ? '#ecfdf5' : kw.comp === '높음' ? '#fef2f2' : '#fffbeb',
                          color: kw.comp === '낮음' ? '#10b981' : kw.comp === '높음' ? '#ef4444' : '#f59e0b'
                        }}>{kw.comp}</span>
                      </td>
                      <td style={{ minWidth: 120 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{
                            flex: 1,
                            height: 8,
                            borderRadius: 8,
                            background: '#f1f5f9',
                            overflow: 'hidden'
                          }}>
                            <div style={{
                              width: barPercent + '%',
                              height: '100%',
                              borderRadius: 8,
                              background: kw.isGolden
                                ? 'linear-gradient(135deg, #f59e0b, #d97706)'
                                : 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                              transition: 'width 0.3s ease'
                            }}></div>
                          </div>
                          <span style={{ fontSize: 11, color: '#64748b', minWidth: 32, textAlign: 'right' }}>{barPercent}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};
