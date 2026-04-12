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

  const renderMetricCard = (title, emoji, bgColor, borderColor, value) => {
    return (
      <div style={{
        backgroundColor: bgColor,
        border: `2px solid ${borderColor}`,
        borderRadius: '12px',
        padding: '16px',
        minHeight: '200px'
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
    <div className="section">
      <h2 className="section-title">⭐ 리뷰 & 찜 분석</h2>

      {/* Comparison Cards Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: '20px',
        marginTop: '20px',
        marginBottom: '32px'
      }}>
        {renderMetricCard(
          '리뷰수',
          '💬',
          '#dbeafe',
          '#93c5fd',
          reviewCount
        )}
        {renderMetricCard(
          '평점',
          '⭐',
          '#e9d5ff',
          '#d8b4fe',
          rating
        )}
        {renderMetricCard(
          '찜수',
          '💛',
          '#fef3c7',
          '#fcd34d',
          wishCount
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
