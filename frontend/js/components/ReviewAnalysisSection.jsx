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
              fontSize: 24,
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
              fontSize: 24,
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
              fontSize: 24,
              fontWeight: 800,
              color: '#64748b'
            }}>{fmt(top5Val)}</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{unit}</div>
          </div>
        </div>

        {/* Gap */}
        <div style={{
          marginTop: 16,
          textAlign: 'center'
        }}>
          <span style={{
            display: 'inline-block',
            padding: '4px 14px',
            borderRadius: 999,
            fontSize: 13,
            fontWeight: 700,
            background: gapBg,
            color: gapColor
          }}>
            {gapArrow} {Math.abs(gap)}%
          </span>
        </div>
      </div>
    );
  };

  return (
    <div className="section fade-in">
      <div className="container">
        <div className="section-title">
          <span className="icon" style={{ background: 'linear-gradient(135deg, #eef2ff, #dbeafe)' }}>⭐</span>
          리뷰 &amp; 찜 분석
        </div>
        <div className="section-line"></div>
        <p className="section-subtitle">광고주 상품 vs 경쟁 평균 vs 상위 5개 비교</p>

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
  );
};
