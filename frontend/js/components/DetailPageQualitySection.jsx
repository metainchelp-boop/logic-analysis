window.DetailPageQualitySection = function DetailPageQualitySection(props) {
  if (!props?.data) return null;
  const { totalScore, grade, gradeColor, scoreBars, checklist, comment } = props.data;

  if (totalScore === undefined) return null;

  return (
    <div className="section fade-in">
      <div className="container">
      <div className="card" style={{ padding: '20px 22px' }}>
      <h3 className="rt-h3"><span className="rt-hic">📄</span>상세페이지 품질 점수<span className="badge b-est">≈ 추정</span></h3>

      {/* Score Header */}
      <div style={{ textAlign: 'center', marginBottom: '8px' }}>
        <span style={{ fontSize: '30px', fontWeight: '900' }}>{totalScore}</span>
        <span style={{ color: 'var(--sub)' }}>/100{grade ? ' · ' + String(grade).replace(/등급$/, '') + '등급' : ''}</span>
      </div>

      {/* Score Bars */}
      {scoreBars && scoreBars.map((bar, idx) => {
        const percent = bar.maxScore ? Math.round((bar.score / bar.maxScore) * 100) : (bar.percent || 0);
        return (
          <div key={idx} className="scorebar">
            <div className="lbl"><b>{bar.label}</b></div>
            <div className="track"><i style={{ width: percent + '%' }}></i></div>
          </div>
        );
      })}

      {/* Checklist */}
      {checklist && checklist.length > 0 && (
        <div className="sub-card">
          <div className="st">평가 체크리스트</div>
          {checklist.map((category, cidx) => (
            category.items && category.items.map((item, iidx) => (
              <div key={cidx + '-' + iidx} className="check">
                <span className={item.pass ? 'y' : 'n'}>{item.pass ? '✔' : '✘'}</span> {item.text}
              </div>
            ))
          ))}
        </div>
      )}

      {/* Comment */}
      {comment && (
        <div className="note">{comment}</div>
      )}

      </div>
      </div>
    </div>
  );
};
