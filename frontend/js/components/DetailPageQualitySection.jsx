window.DetailPageQualitySection = function DetailPageQualitySection(props) {
  if (!props?.data) return null;
  const { totalScore, grade, gradeColor, scoreBars, checklist, comment } = props.data;

  if (totalScore === undefined) return null;

  return (
    <div className="section">
      <h2 className="section-title">🎯 상세페이지 품질 점수 진단</h2>

      {/* Score Header */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '2fr 1fr',
        gap: '20px',
        marginBottom: '32px',
        marginTop: '20px'
      }}>
        <div style={{
          backgroundColor: '#f9fafb',
          border: '1px solid #e5e7eb',
          borderRadius: '12px',
          padding: '24px',
          display: 'flex',
          alignItems: 'center',
          gap: '20px'
        }}>
          <div style={{
            fontSize: '48px',
            fontWeight: '700',
            color: '#1f2937',
            minWidth: '80px',
            textAlign: 'center'
          }}>
            {totalScore}
          </div>
          <div style={{
            fontSize: '13px',
            color: '#666',
            lineHeight: '1.8'
          }}>
            <div style={{ marginBottom: '4px' }}>전체 점수</div>
            <div style={{ fontSize: '11px', color: '#999' }}>100점 만점</div>
          </div>
        </div>

        {grade && (
          <div style={{
            backgroundColor: gradeColor || '#f0f9ff',
            border: `2px solid ${gradeColor === '#dbeafe' ? '#93c5fd' : gradeColor === '#dcfce7' ? '#86efac' : gradeColor === '#fef3c7' ? '#fcd34d' : '#fca5a5'}`,
            borderRadius: '12px',
            padding: '24px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <div style={{ fontSize: '11px', color: '#666', marginBottom: '8px' }}>등급</div>
            <div style={{
              fontSize: '36px',
              fontWeight: '700',
              color: '#1f2937'
            }}>
              {grade}
            </div>
          </div>
        )}
      </div>

      {/* Score Bars */}
      {scoreBars && scoreBars.length > 0 && (
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
            세부 항목 점수
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {scoreBars.map((bar, idx) => {
              const percent = (bar.score / bar.maxScore) * 100;
              return (
                <div key={idx}>
                  <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '6px',
                    fontSize: '12px'
                  }}>
                    <span style={{ fontWeight: '600', color: '#333' }}>{bar.label}</span>
                    <span style={{ color: '#666' }}>{bar.score}/{bar.maxScore}</span>
                  </div>
                  <div style={{
                    width: '100%',
                    height: '8px',
                    backgroundColor: '#e5e7eb',
                    borderRadius: '4px',
                    overflow: 'hidden'
                  }}>
                    <div style={{
                      width: `${percent}%`,
                      height: '100%',
                      backgroundColor: bar.color || '#3b82f6',
                      transition: 'width 0.3s ease'
                    }}></div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Checklist */}
      {checklist && checklist.length > 0 && (
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
            평가 항목 체크리스트
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {checklist.map((category, cidx) => (
              <div key={cidx}>
                <div style={{
                  fontSize: '12px',
                  fontWeight: '600',
                  color: '#666',
                  marginBottom: '8px',
                  paddingBottom: '8px',
                  borderBottom: '1px solid #e5e7eb'
                }}>
                  {category.category}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {category.items && category.items.map((item, iidx) => (
                    <div key={iidx} style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '8px',
                      fontSize: '12px',
                      color: '#333',
                      marginLeft: '12px'
                    }}>
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        minWidth: '18px',
                        height: '18px',
                        marginTop: '1px',
                        fontSize: '14px',
                        flexShrink: 0
                      }}>
                        {item.pass ? '✓' : '✗'}
                      </span>
                      <span>{item.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Comment */}
      {comment && (
        <div style={{
          background: 'linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)',
          border: '2px solid #fcd34d',
          borderRadius: '8px',
          padding: '14px 16px',
          fontSize: '13px',
          color: '#333',
          lineHeight: '1.6'
        }}>
          <strong style={{ display: 'block', marginBottom: '6px', color: '#b45309' }}>💡 분석 코멘트</strong>
          {comment}
        </div>
      )}

      <style>{`
        .detail-quality-section {
          margin-top: 20px;
        }
      `}</style>
    </div>
  );
};
