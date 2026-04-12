window.StrategicAnalysisSection = function StrategicAnalysisSection(props) {
  if (!props?.data) return null;
  const { groups, briefing } = props.data;

  if (!groups || groups.length === 0) return null;

  const getGroupColor = (color) => {
    const colors = {
      'blue': { bg: '#dbeafe', border: '#93c5fd', text: '#1976d2' },
      'green': { bg: '#dcfce7', border: '#86efac', text: '#16a34a' },
      'yellow': { bg: '#fef3c7', border: '#fcd34d', text: '#b45309' },
      'red': { bg: '#fee2e2', border: '#fca5a5', text: '#dc2626' },
      'purple': { bg: '#f3e5f5', border: '#d8b4fe', text: '#8b5cf6' },
      'pink': { bg: '#fce7f3', border: '#f472b6', text: '#be185d' }
    };
    return colors[color] || colors['blue'];
  };

  return (
    <div className="section">
      <h2 className="section-title">🎯 1페이지 진입 전략 비교 분석</h2>

      {/* Group Cards */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '24px',
        marginTop: '20px',
        marginBottom: '32px'
      }}>
        {groups.map((group, gidx) => {
          const colorScheme = getGroupColor(group.color);

          return (
            <div key={gidx} style={{
              backgroundColor: '#fff',
              border: `2px solid ${colorScheme.border}`,
              borderRadius: '12px',
              padding: '20px'
            }}>
              {/* Group Header */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '20px',
                paddingBottom: '16px',
                borderBottom: `1px solid ${colorScheme.border}`
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{
                    backgroundColor: colorScheme.text,
                    color: '#fff',
                    padding: '6px 12px',
                    borderRadius: '20px',
                    fontSize: '12px',
                    fontWeight: '600'
                  }}>
                    {group.label}
                  </span>
                  <span style={{
                    fontSize: '13px',
                    color: '#666'
                  }}>
                    평균: <strong style={{ color: colorScheme.text }}>{group.avgScore?.toFixed(1) || '-'}</strong>
                  </span>
                </div>

                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px'
                }}>
                  <span style={{
                    fontSize: '13px',
                    color: '#333'
                  }}>
                    광고주: <strong>{group.advScore?.toFixed(1) || '-'}</strong>
                  </span>
                  {group.scoreDiff !== undefined && (
                    <span style={{
                      backgroundColor: group.scoreDiffColor === 'green' ? '#dcfce7' : group.scoreDiffColor === 'red' ? '#fee2e2' : '#f3f4f6',
                      color: group.scoreDiffColor === 'green' ? '#16a34a' : group.scoreDiffColor === 'red' ? '#dc2626' : '#666',
                      padding: '4px 8px',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: '600'
                    }}>
                      {group.scoreDiff > 0 ? '+' : ''}{group.scoreDiff?.toFixed(1) || '-'}
                    </span>
                  )}
                </div>
              </div>

              {/* Metrics Table */}
              {group.metrics && group.metrics.length > 0 && (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    minWidth: '800px',
                    fontSize: '12px'
                  }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #e5e7eb', backgroundColor: '#f9fafb' }}>
                        <th style={{
                          padding: '10px 8px',
                          textAlign: 'left',
                          fontWeight: '600',
                          color: '#666',
                          maxWidth: '200px'
                        }}>핵심 지표</th>
                        <th style={{
                          padding: '10px 8px',
                          textAlign: 'right',
                          fontWeight: '600',
                          color: '#666',
                          minWidth: '80px'
                        }}>광고주</th>
                        <th style={{
                          padding: '10px 8px',
                          textAlign: 'right',
                          fontWeight: '600',
                          color: '#666',
                          minWidth: '80px'
                        }}>TOP 평균</th>
                        <th style={{
                          padding: '10px 8px',
                          textAlign: 'center',
                          fontWeight: '600',
                          color: '#666',
                          minWidth: '100px'
                        }}>격차</th>
                        <th style={{
                          padding: '10px 8px',
                          textAlign: 'left',
                          fontWeight: '600',
                          color: '#666',
                          minWidth: '180px'
                        }}>점수 비교</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.metrics.map((metric, midx) => (
                        <tr key={midx} style={{ borderBottom: '1px solid #e5e7eb' }}>
                          <td style={{
                            padding: '10px 8px',
                            color: '#333',
                            maxWidth: '200px',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap'
                          }}>
                            <div>{metric.name}</div>
                            <div style={{
                              fontSize: '10px',
                              color: '#999',
                              marginTop: '2px'
                            }}>
                              (가중치: {metric.weight}%)
                            </div>
                          </td>
                          <td style={{
                            padding: '10px 8px',
                            textAlign: 'right',
                            color: '#333',
                            fontWeight: '600'
                          }}>
                            {metric.advValue || '-'}
                          </td>
                          <td style={{
                            padding: '10px 8px',
                            textAlign: 'right',
                            color: '#666'
                          }}>
                            {metric.avgValue || '-'}
                          </td>
                          <td style={{
                            padding: '10px 8px',
                            textAlign: 'center',
                            color: metric.gapColor === 'green' ? '#16a34a' : metric.gapColor === 'red' ? '#dc2626' : '#666',
                            fontWeight: '600',
                            fontSize: '11px'
                          }}>
                            {metric.gap || '-'}
                          </td>
                          <td style={{
                            padding: '10px 8px',
                            textAlign: 'left'
                          }}>
                            <div style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: '8px'
                            }}>
                              <div style={{
                                flex: 1,
                                display: 'flex',
                                gap: '2px',
                                height: '16px',
                                borderRadius: '4px',
                                overflow: 'hidden',
                                backgroundColor: '#e5e7eb'
                              }}>
                                <div style={{
                                  width: `${metric.scorePercent || 0}%`,
                                  backgroundColor: metric.barColor || colorScheme.text,
                                  transition: 'width 0.3s ease'
                                }}></div>
                                <div style={{
                                  width: `${(metric.refPercent || 0) - (metric.scorePercent || 0)}%`,
                                  backgroundColor: '#d1d5db',
                                  opacity: 0.5
                                }}></div>
                              </div>
                              <span style={{
                                fontSize: '10px',
                                color: '#666',
                                minWidth: '30px',
                                textAlign: 'right'
                              }}>
                                {metric.score?.toFixed(1) || '-'}
                              </span>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Briefing Section */}
      {briefing && (
        <div style={{
          backgroundColor: '#f0fdf4',
          border: '2px solid #86efac',
          borderLeft: '6px solid #16a34a',
          borderRadius: '8px',
          padding: '16px',
          fontSize: '13px',
          color: '#333',
          lineHeight: '1.7'
        }}>
          <strong style={{
            display: 'block',
            marginBottom: '8px',
            color: '#16a34a',
            fontSize: '14px'
          }}>
            📌 1페이지 진입 전략 브리핑
          </strong>
          <div style={{ whiteSpace: 'pre-wrap' }}>
            {briefing}
          </div>
        </div>
      )}

      <style>{`
        @media (max-width: 1200px) {
          table {
            font-size: 11px;
          }
          td, th {
            padding: 8px 6px !important;
          }
        }
      `}</style>
    </div>
  );
};
