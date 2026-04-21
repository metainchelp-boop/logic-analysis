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

  // HTML에서 추출된 실제 리뷰 데이터 (상세페이지 품질 진단 시)
  const html = props.htmlReviewData || null;
  const hasHtmlData = html && (html.reviewCount != null || html.rating != null || html.wishCount != null);

  const renderMetricCard = (title, emoji, bgColor, borderColor, value, htmlValue, unit) => {
    return (
      <div style={{
        backgroundColor: bgColor,
        border: `2px solid ${borderColor}`,
        borderRadius: '12px',
        padding: '16px',
        minHeight: '200px',
        position: 'relative'
      }}>
        <div style={{
          fontSize: '13px',
          fontWeight: '600',
          color: '#666',
          marginBottom: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '6px'
        }}>
          <span>{emoji}</span>
          <span>{title}</span>
        </div>

        {/* HTML 실제 데이터가 있으면 실제 값을 크게 표시 */}
        {htmlValue != null ? (
          <div>
            <div style={{
              display: 'inline-block',
              backgroundColor: '#059669',
              color: '#fff',
              fontSize: '10px',
              fontWeight: '700',
              padding: '2px 8px',
              borderRadius: '10px',
              marginBottom: '8px'
            }}>
              실제 데이터
            </div>
            <div style={{
              fontSize: '28px',
              fontWeight: '700',
              color: '#059669',
              marginBottom: '8px'
            }}>
              {fmt(htmlValue)}{unit || ''}
            </div>
            <div style={{
              fontSize: '11px',
              color: '#888',
              marginBottom: '12px',
              paddingBottom: '12px',
              borderBottom: '1px solid rgba(0, 0, 0, 0.1)'
            }}>
              <div style={{ marginBottom: '3px', color: '#999' }}>
                <span style={{ textDecoration: 'line-through' }}>추정: {fmt(value.adv)}</span>
              </div>
              <div style={{ marginBottom: '3px' }}>
                <strong>경쟁 평균:</strong> {fmt(value.avg)}
              </div>
              <div>
                <strong>상위5:</strong> {fmt(value.top5)}
              </div>
            </div>
          </div>
        ) : (
          <div>
            <div style={{
              display: 'inline-block',
              backgroundColor: '#94a3b8',
              color: '#fff',
              fontSize: '10px',
              fontWeight: '700',
              padding: '2px 8px',
              borderRadius: '10px',
              marginBottom: '8px'
            }}>
              추정치
            </div>
            <div style={{
              fontSize: '28px',
              fontWeight: '700',
              color: '#1f2937',
              marginBottom: '12px'
            }}>
              {fmt(value.adv)}
            </div>
            <div style={{
              fontSize: '12px',
              color: '#666',
              marginBottom: '12px',
              paddingBottom: '12px',
              borderBottom: '1px solid rgba(0, 0, 0, 0.1)'
            }}>
              <div style={{ marginBottom: '4px' }}>
                <strong>평균:</strong> {fmt(value.avg)}
              </div>
              <div>
                <strong>상위5:</strong> {fmt(value.top5)}
              </div>
            </div>
          </div>
        )}

        <div style={{
          fontSize: '12px',
          color: value.gapColor === 'green' ? '#16a34a' : value.gapColor === 'red' ? '#dc2626' : '#f59e0b',
          fontWeight: '600'
        }}>
          {value.gapLabel}
        </div>
      </div>
    );
  };

  return (
    <div className="section" style={{ maxWidth: '1200px', margin: '0 auto', padding: '12px 24px' }}>
      <h2 className="section-title">⭐ 리뷰 & 찜 분석</h2>

      {/* HTML 실제 데이터 안내 배너 */}
      {hasHtmlData && (
        <div style={{
          background: 'linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%)',
          border: '1px solid #6ee7b7',
          borderRadius: '8px',
          padding: '10px 16px',
          marginTop: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '13px',
          color: '#065f46'
        }}>
          <span style={{ fontSize: '16px' }}>✅</span>
          <span><strong>상세페이지 HTML에서 실제 리뷰 데이터를 추출했습니다.</strong> 초록색 값이 실제 수치입니다.</span>
        </div>
      )}

      {!hasHtmlData && (
        <div style={{
          background: '#f8fafc',
          border: '1px dashed #cbd5e1',
          borderRadius: '8px',
          padding: '10px 16px',
          marginTop: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '12px',
          color: '#64748b'
        }}>
          <span style={{ fontSize: '14px' }}>💡</span>
          <span>위의 <strong>상세페이지 품질 진단</strong>에 HTML을 업로드하면, 실제 리뷰수/평점/찜수를 추출하여 표시합니다.</span>
        </div>
      )}

      {/* Comparison Cards Grid */}
      <div className="review-cards-grid" style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: '20px',
        marginTop: '20px',
        marginBottom: '32px'
      }}>
        {renderMetricCard(
          '리뷰수',
          '💬',
          hasHtmlData && html.reviewCount != null ? '#dcfce7' : '#dbeafe',
          hasHtmlData && html.reviewCount != null ? '#86efac' : '#93c5fd',
          reviewCount,
          html ? html.reviewCount : null,
          '건'
        )}
        {renderMetricCard(
          '평점',
          '⭐',
          hasHtmlData && html.rating != null ? '#dcfce7' : '#e9d5ff',
          hasHtmlData && html.rating != null ? '#86efac' : '#d8b4fe',
          rating,
          html ? html.rating : null,
          '점'
        )}
        {renderMetricCard(
          '찜수',
          '💛',
          hasHtmlData && html.wishCount != null ? '#dcfce7' : '#fef3c7',
          hasHtmlData && html.wishCount != null ? '#86efac' : '#fcd34d',
          wishCount,
          html ? html.wishCount : null,
          '건'
        )}
      </div>

      {/* Gap Visualization */}
      <div style={{
        backgroundColor: '#fff',
        border: '1px solid #e5e7eb',
        borderRadius: '12px',
        padding: '20px',
        marginBottom: '20px'
      }}>
        <div style={{
          fontSize: '13px',
          fontWeight: '600',
          color: '#1f2937',
          marginBottom: '16px'
        }}>
          경쟁력 격차 분석
        </div>

        {/* Review Gap */}
        <div style={{ marginBottom: '16px' }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '8px',
            fontSize: '12px'
          }}>
            <span style={{ fontWeight: '600', color: '#333' }}>리뷰수 격차</span>
            <span style={{ color: '#666' }}>{reviewGapPercent}%</span>
          </div>
          <div style={{
            width: '100%',
            height: '8px',
            backgroundColor: '#e5e7eb',
            borderRadius: '4px',
            overflow: 'hidden'
          }}>
            <div style={{
              width: `${Math.min(100, Math.max(0, reviewGapPercent))}%`,
              height: '100%',
              backgroundColor: reviewGapPercent > 0 ? '#16a34a' : '#dc2626',
              transition: 'width 0.3s ease'
            }}></div>
          </div>
        </div>

        {/* Rating Gap */}
        <div style={{ marginBottom: '16px' }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '8px',
            fontSize: '12px'
          }}>
            <span style={{ fontWeight: '600', color: '#333' }}>평점 격차</span>
            <span style={{ color: '#666' }}>{ratingGapPercent}%</span>
          </div>
          <div style={{
            width: '100%',
            height: '8px',
            backgroundColor: '#e5e7eb',
            borderRadius: '4px',
            overflow: 'hidden'
          }}>
            <div style={{
              width: `${Math.min(100, Math.max(0, ratingGapPercent))}%`,
              height: '100%',
              backgroundColor: ratingGapPercent > 0 ? '#16a34a' : '#dc2626',
              transition: 'width 0.3s ease'
            }}></div>
          </div>
        </div>

        {/* Wish Gap */}
        <div>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '8px',
            fontSize: '12px'
          }}>
            <span style={{ fontWeight: '600', color: '#333' }}>찜수 격차</span>
            <span style={{ color: '#666' }}>{wishGapPercent}%</span>
          </div>
          <div style={{
            width: '100%',
            height: '8px',
            backgroundColor: '#e5e7eb',
            borderRadius: '4px',
            overflow: 'hidden'
          }}>
            <div style={{
              width: `${Math.min(100, Math.max(0, wishGapPercent))}%`,
              height: '100%',
              backgroundColor: wishGapPercent > 0 ? '#16a34a' : '#dc2626',
              transition: 'width 0.3s ease'
            }}></div>
          </div>
        </div>
      </div>

      {/* Strategy Comment */}
      {strategy && (
        <div style={{
          backgroundColor: '#f0fdf4',
          border: '2px solid #86efac',
          borderLeft: '6px solid #16a34a',
          borderRadius: '8px',
          padding: '14px 16px',
          fontSize: '13px',
          color: '#333',
          lineHeight: '1.6'
        }}>
          <strong style={{ display: 'block', marginBottom: '6px', color: '#16a34a' }}>📊 전략 코멘트</strong>
          {strategy}
        </div>
      )}

      <style>{`
        @media (max-width: 1024px) {
          .review-cards-grid {
            grid-template-columns: repeat(2, 1fr);
          }
        }
        @media (max-width: 768px) {
          .review-cards-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};
