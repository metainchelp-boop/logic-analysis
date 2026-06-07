window.ReviewAnalysisSection = function ReviewAnalysisSection(props) {
  if (!props?.data) return null;
  const {
    reviewCount,
    rating,
    wishCount,
    reviewGapPercent,
    ratingGapPercent,
    wishGapPercent,
    strategy
  } = props.data;

  if (!reviewCount || !rating || !wishCount) return null;

  // HTML에서 추출된 실제 리뷰 데이터
  const html = props.htmlReviewData || null;
  const hasHtmlData = html && (html.reviewCount != null || html.rating != null || html.wishCount != null);

  var fmt = function(n) { return n != null ? Number(n).toLocaleString('ko-KR') : '-'; };

  var renderCard = function(title, emoji, value, htmlValue, unit, gapPercent) {
    var myVal = hasHtmlData && htmlValue != null ? htmlValue : value.adv;
    var avgVal = value.avg;
    var top5Val = value.top5;
    var gap = gapPercent;
    var isPositive = gap > 0;
    var gapColor = isPositive ? '#10b981' : '#ef4444';
    var gapBg = isPositive ? '#ecfdf5' : '#fef2f2';
    var gapArrow = isPositive ? '▲' : '▼';

    return (
      <div style={{
        background: '#fff',
        borderRadius: 16,
        padding: '24px 20px',
        border: '1px solid #e2e8f0',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        borderLeft: '4px solid #7c3aed'
      }}>
        {/* Header */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 20
        }}>
          <span style={{ fontSize: 18 }}>{emoji}</span>
          <span style={{
            fontSize: 14,
            fontWeight: 700,
            color: '#1e293b'
          }}>{title}</span>
          {hasHtmlData && htmlValue != null && (
            <span style={{
              marginLeft: 'auto',
              padding: '2px 8px',
              borderRadius: 999,
              fontSize: 10,
              fontWeight: 700,
              background: '#ecfdf5',
              color: '#10b981'
            }}>실제 데이터</span>
          )}
        </div>

        {/* 3-column: 내 상품 / 경쟁 평균 / 상위 5 */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr 1fr',
          gap: 12,
          textAlign: 'center'
        }}>
          {/* 내 상품 */}
          <div style={{
            background: '#f8fafc',
            borderRadius: 12,
            padding: '16px 8px'
          }}>
            <div style={{
              fontSize: 11,
              fontWeight: 600,
              color: '#94a3b8',
              marginBottom: 8
            }}>내 상품</div>
            <div style={{
              fontSize: 18,
              fontWeight: 800,
              color: hasHtmlData && htmlValue != null ? '#10b981' : '#0f172a'
            }}>{fmt(myVal)}</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{unit}</div>
          </div>

          {/* 경쟁 평균 */}
          <div style={{
            background: '#f8fafc',
            borderRadius: 12,
            padding: '16px 8px'
          }}>
            <div style={{
              fontSize: 11,
              fontWeight: 600,
              color: '#94a3b8',
              marginBottom: 8
            }}>경쟁 평균</div>
            <div style={{
              fontSize: 18,
              fontWeight: 800,
              color: '#64748b'
            }}>{fmt(avgVal)}</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{unit}</div>
          </div>

          {/* 상위 5 */}
          <div style={{
            background: '#f8fafc',
            borderRadius: 12,
            padding: '16px 8px'
          }}>
            <div style={{
              fontSize: 11,
              fontWeight: 600,
              color: '#94a3b8',
              marginBottom: 8
            }}>상위 5</div>
            <div style={{
              fontSize: 18,
              fontWeight: 800,
              color: '#64748b'
            }}>{fmt(top5Val)}</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{unit}</div>
          </div>
        </div>

      </div>
    );
  };

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="card" style={{ padding: '20px 22px' }}>
        <h3 className="rt-h3"><span className="rt-hic">⭐</span>리뷰 &amp; 찜 분석<span className="badge b-ok">✅ 실측</span></h3>
        <div className="rt-desc">광고주 상품 vs 경쟁 평균 vs 상위 5개 비교</div>

        {/* HTML 실제 데이터 안내 배너 */}
        {hasHtmlData && (
          <div style={{
            background: 'linear-gradient(135deg, #ecfdf5, #d1fae5)',
            border: '1px solid #6ee7b7',
            borderRadius: 12,
            padding: '12px 20px',
            marginTop: 12,
            marginBottom: 20,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontSize: 13,
            color: '#065f46'
          }}>
            <span style={{ fontSize: 18 }}>✅</span>
            <span><strong>상세페이지 HTML에서 실제 리뷰 데이터를 추출했습니다.</strong> 초록색 값이 실제 수치입니다.</span>
          </div>
        )}

        {!hasHtmlData && (
          <div style={{
            background: '#f8fafc',
            border: '1px dashed #cbd5e1',
            borderRadius: 12,
            padding: '12px 20px',
            marginTop: 12,
            marginBottom: 20,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontSize: 12,
            color: '#64748b'
          }}>
            <span style={{ fontSize: 16 }}>💡</span>
            <span>위의 <strong>상세페이지 품질 진단</strong>에 HTML을 업로드하면, 실제 리뷰수/평점/찜수를 추출하여 표시합니다.</span>
          </div>
        )}

        {/* Cards Grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 20,
          marginBottom: 24
        }}>
          {renderCard(
            '리뷰 수',
            '📝',
            reviewCount,
            html ? html.reviewCount : null,
            '건',
            reviewGapPercent
          )}
          {renderCard(
            '평점',
            '⭐',
            rating,
            html ? html.rating : null,
            '점',
            ratingGapPercent
          )}
          {renderCard(
            '찜 수',
            '💛',
            wishCount,
            html ? html.wishCount : null,
            '건',
            wishGapPercent
          )}
        </div>

        {/* 리뷰·평점·찜 비교 그룹 막대 차트 */}
        {(function() {
          var C = window.CHART_COLORS || {};
          var num = function(v) { return (v == null || isNaN(Number(v))) ? 0 : Number(v); };
          var mineReview = (hasHtmlData && html && html.reviewCount != null) ? html.reviewCount : reviewCount.adv;
          var mineRating = (hasHtmlData && html && html.rating != null) ? html.rating : rating.adv;
          var mineWish = (hasHtmlData && html && html.wishCount != null) ? html.wishCount : wishCount.adv;
          var mine = [num(mineReview), num(mineRating) * 100, num(mineWish)];
          var avg = [num(reviewCount.avg), num(rating.avg) * 100, num(wishCount.avg)];
          var top5 = [num(reviewCount.top5), num(rating.top5) * 100, num(wishCount.top5)];
          var anyVal = mine.concat(avg, top5).some(function(v) { return v > 0; });
          if (!anyVal) return null;
          var fmtTip = function(ctx) {
            var raw = ctx.parsed.y;
            var label = ctx.dataset.label + ': ';
            if (ctx.dataIndex === 1) return label + (raw / 100).toFixed(1) + '점';
            return label + (window.chartComma ? window.chartComma(raw) : raw);
          };
          return (
            <div style={{ background: '#fff', borderRadius: 16, padding: '24px 20px', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.04)', marginBottom: 24 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 6 }}>리뷰 · 평점 · 찜 비교</div>
              <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 14 }}>값 차이가 커서 로그 눈금으로 표시합니다. 평점은 비교를 위해 ×100 환산했습니다(툴팁은 실제 점수).</div>
              <ChartCanvas
                type="bar"
                height={260}
                data={{
                  labels: ['리뷰 수', '평점(×100)', '찜 수'],
                  datasets: [
                    { label: '내 상품', data: mine, backgroundColor: C.OK || '#10b981', borderRadius: 5 },
                    { label: '경쟁 평균', data: avg, backgroundColor: '#94a3b8', borderRadius: 5 },
                    { label: '상위 5', data: top5, backgroundColor: C.IND || '#4f46e5', borderRadius: 5 }
                  ]
                }}
                options={{
                  plugins: {
                    legend: { position: 'bottom' },
                    tooltip: { callbacks: { label: fmtTip } }
                  },
                  scales: { y: { type: 'logarithmic', ticks: { callback: function(v) { return window.chartComma ? window.chartComma(v) : v; } } } }
                }}
              />
            </div>
          );
        })()}

        {/* Strategy Comment */}
        {strategy && (
          <div style={{
            background: 'linear-gradient(135deg, #f0fdf4, #ecfdf5)',
            border: '1px solid #bbf7d0',
            borderRadius: 12,
            padding: '16px 20px'
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 12
            }}>
              <span style={{
                padding: '4px 12px',
                borderRadius: 999,
                fontSize: 12,
                fontWeight: 700,
                background: '#10b981',
                color: '#fff'
              }}>전략</span>
              <span style={{
                fontSize: 13,
                fontWeight: 700,
                color: '#10b981'
              }}>전략 코멘트</span>
            </div>
            <div style={{
              fontSize: 13,
              color: '#0f172a',
              lineHeight: 1.7
            }}>
              {strategy}
            </div>
          </div>
        )}
        </div>
      </div>
    </div>
  );
};
