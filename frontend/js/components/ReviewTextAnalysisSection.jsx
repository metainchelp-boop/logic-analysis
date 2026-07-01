/* ReviewTextAnalysisSection — HTML에서 추출한 구매자 리뷰 텍스트 분석 */
window.ReviewTextAnalysisSection = function ReviewTextAnalysisSection(props) {
  var React = window.React;
  var useState = React.useState;
  var data = props.data;     // reviewData.reviewTextAnalysis
  var reviews = props.reviews; // reviewData.reviews (개별 리뷰 배열)
  var totalReviewCount = props.totalReviewCount; // 전체 리뷰 수 (reviewData.reviewCount)

  if (!data || !reviews || reviews.length === 0) return null;

  var showAllState = useState(false);
  var showAll = showAllState[0];
  var setShowAll = showAllState[1];

  var fmt = function(n) { return n != null ? Number(n).toLocaleString('ko-KR') : '-'; };
  var stars = function(n) {
    var full = Math.floor(n);
    var s = '';
    for (var i = 0; i < full; i++) s += '★';
    for (var j = full; j < 5; j++) s += '☆';
    return s;
  };

  var sentimentLabel = { positive: '긍정', negative: '부정', neutral: '중립' };
  var sentimentStyle = {
    positive: { background: '#dcfce7', color: '#166534' },
    negative: { background: '#fee2e2', color: '#991b1b' },
    neutral:  { background: '#f1f5f9', color: '#64748b' }
  };

  var tagColors = [
    'linear-gradient(90deg, #7c3aed, #a78bfa)',
    'linear-gradient(90deg, #3b82f6, #93c5fd)',
    'linear-gradient(90deg, #10b981, #6ee7b7)',
    'linear-gradient(90deg, #f59e0b, #fcd34d)',
    'linear-gradient(90deg, #ec4899, #f9a8d4)',
  ];

  var kwTabState = useState('pos');
  var kwTab = kwTabState[0];
  var setKwTab = kwTabState[1];

  var displayedReviews = showAll ? reviews : reviews.slice(0, 3);
  var remainingCount = reviews.length - 3;

  /* 리뷰 실문장 카피 후보 — 긍정 리뷰에서 실제 문장 추출(문구 창작이 아니라 구매자 표현 인용) */
  var positiveKw = (data.positiveKeywords || []).map(function(k) { return k.keyword; }).filter(Boolean);
  var pickSentence = function(text) {
    var parts = String(text || '').split(/[.!?\n·•]|다\s|요\s/).map(function(s) { return s.trim(); })
      .filter(function(s) { return s.length >= 6 && s.length <= 45; });
    for (var i = 0; i < parts.length; i++) {
      for (var j = 0; j < positiveKw.length; j++) {
        if (positiveKw[j] && parts[i].indexOf(positiveKw[j]) >= 0) return parts[i];
      }
    }
    return parts[0] || null;
  };
  var _seen = {};
  var copyCandidates = [];
  (reviews || []).forEach(function(r) {
    if (copyCandidates.length >= 5) return;
    if (!r || !r.text) return;
    if (!(r.sentiment === 'positive' || (Number(r.rating) || 0) >= 4)) return;
    var s = pickSentence(r.text);
    if (!s) return;
    var key = s.replace(/\s/g, '');
    if (_seen[key]) return;
    _seen[key] = 1;
    copyCandidates.push({ copy: s, rating: r.rating });
  });

  return React.createElement('div', { className: 'section fade-in' },
    React.createElement('div', { className: 'container' },
      React.createElement('div', { className: 'card', style: { padding: '20px 22px' } },

      /* 제목 */
      React.createElement('h3', { className: 'rt-h3' },
        React.createElement('span', { className: 'rt-hic' }, '💬'),
        '리뷰 텍스트 분석',
        React.createElement('span', { className: 'badge b-est' }, '≈ 추정')
      ),
      React.createElement('div', { className: 'rt-desc' }, '상세페이지 HTML에서 추출한 구매자 리뷰 분석 결과'),

      /* 1. 요약 KPI 4개 (.grid4 + .kpi) */
      React.createElement('div', { className: 'grid4', style: { marginBottom: 10 } },
        /* 추출된 리뷰 */
        React.createElement('div', { className: 'kpi' },
          React.createElement('div', { className: 'k' }, '추출 리뷰'),
          React.createElement('div', { className: 'v', style: { fontSize: 20 } },
            fmt(data.totalExtracted),
            React.createElement('small', null, '건')
          ),
          totalReviewCount ? React.createElement('div', { style: { fontSize: 11, color: '#94a3b8', marginTop: 4 } },
            '전체 ' + fmt(totalReviewCount) + '건 중 표본 ' + fmt(data.totalExtracted) + '건'
            + (totalReviewCount > 0 ? ' (' + Math.round(data.totalExtracted / totalReviewCount * 100) + '%)' : '')
          ) : null
        ),
        /* 평균 별점 */
        React.createElement('div', { className: 'kpi' },
          React.createElement('div', { className: 'k' }, '평균 별점'),
          React.createElement('div', { className: 'v', style: { fontSize: 20 } },
            data.avgRating,
            React.createElement('small', null, '★')
          )
        ),
        /* 긍정 비율 */
        React.createElement('div', { className: 'kpi' },
          React.createElement('div', { className: 'k' }, '긍정 비율'),
          React.createElement('div', { className: 'v', style: { fontSize: 20, color: 'var(--ok)' } },
            data.sentiment.positiveRatio,
            React.createElement('small', null, '%')
          )
        ),
        /* 평균 글자수 */
        React.createElement('div', { className: 'kpi' },
          React.createElement('div', { className: 'k' }, '평균 글자수'),
          React.createElement('div', { className: 'v', style: { fontSize: 20 } },
            data.avgChars,
            React.createElement('small', null, '자')
          )
        )
      ),

      /* 2. 핵심 키워드 분석 — 긍정/부정 탭 (.pill-tabs) */
      (data.positiveKeywords.length > 0 || data.negativeKeywords.length > 0) ?
        React.createElement('div', { style: { marginBottom: 20 } },
          /* pill-tabs 탭 버튼 */
          React.createElement('div', { className: 'pill-tabs' },
            React.createElement('button', {
              className: kwTab === 'pos' ? 'on' : '',
              onClick: function() { setKwTab('pos'); }
            }, '긍정 키워드'),
            React.createElement('button', {
              className: kwTab === 'neg' ? 'on' : '',
              onClick: function() { setKwTab('neg'); }
            }, '부정 키워드')
          ),
          /* 긍정 키워드 칩 */
          kwTab === 'pos' ?
            React.createElement('div', null,
              data.positiveKeywords.length > 0 ?
                data.positiveKeywords.map(function(kw, i) {
                  return React.createElement('span', { key: 'pos-' + i, className: 'tag2' },
                    kw.keyword + ' (' + kw.count + ')'
                  );
                })
              : React.createElement('div', { style: { fontSize: 13, color: '#94a3b8', padding: '12px 0' } }, '긍정 키워드가 발견되지 않았습니다')
            )
          :
          /* 부정 키워드 칩 */
            React.createElement('div', null,
              data.negativeKeywords.length > 0 ?
                data.negativeKeywords.map(function(kw, i) {
                  return React.createElement('span', {
                    key: 'neg-' + i,
                    className: 'tag2',
                    style: { background: '#fee2e2', color: '#b91c1c' }
                  }, kw.keyword + ' (' + kw.count + ')');
                })
              : React.createElement('div', { style: { fontSize: 13, color: '#94a3b8', padding: '12px 0' } }, '부정 키워드가 발견되지 않았습니다')
            )
        ) : null,

      /* 3. 구매자 선택 태그 분석 */
      data.tagStats && data.tagStats.length > 0 ?
        React.createElement('div', { style: { marginBottom: 20 } },
          React.createElement('div', { style: { fontSize: 14, fontWeight: 700, color: '#1e293b', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 } },
            React.createElement('span', null, '🏷️'), '구매자 선택 태그 분석'
          ),
          React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
            data.tagStats.map(function(ts, i) {
              var pct = Math.round(ts.count / data.totalExtracted * 100);
              return React.createElement('div', {
                key: 'tag-' + i,
                style: { display: 'flex', alignItems: 'center', gap: 12 }
              },
                React.createElement('div', { style: { width: 80, fontSize: 13, fontWeight: 600, color: '#475569', textAlign: 'right', flexShrink: 0 } }, ts.tag),
                React.createElement('div', { style: { flex: 1, height: 28, background: '#f1f5f9', borderRadius: 8, overflow: 'hidden', position: 'relative' } },
                  React.createElement('div', {
                    style: { height: '100%', width: pct + '%', background: tagColors[i % tagColors.length], borderRadius: 8, display: 'flex', alignItems: 'center', paddingLeft: 12, fontSize: 11, fontWeight: 700, color: '#fff', minWidth: 40 }
                  }, ts.count + '건')
                ),
                React.createElement('div', { style: { fontSize: 12, fontWeight: 600, color: '#64748b', width: 50, textAlign: 'left' } }, pct + '%')
              );
            })
          )
        ) : null,

      /* 4. AI 전략 인사이트 (.sub-card + .st) */
      data.insights && data.insights.length > 0 ?
        React.createElement('div', { className: 'sub-card' },
          React.createElement('div', { className: 'st' }, '🤖 AI 전략 인사이트'),
          React.createElement('div', { style: { fontSize: 12.5, color: '#475569' } },
            data.insights.map(function(insight, i) {
              return React.createElement('div', {
                key: 'insight-' + i,
                style: { lineHeight: 1.8, paddingLeft: 20, position: 'relative' }
              },
                React.createElement('span', { style: { position: 'absolute', left: 0, color: '#6366f1', fontWeight: 700 } }, '→'),
                insight
              );
            })
          )
        ) : null,

      /* 4-1. 리뷰 기반 카피 후보 (구매자 실제 표현) */
      copyCandidates.length > 0 ?
        React.createElement('div', { className: 'sub-card' },
          React.createElement('div', { className: 'st' }, '📝 리뷰 기반 카피 후보'),
          React.createElement('div', { style: { fontSize: 11.5, color: '#94a3b8', marginBottom: 10 } },
            '구매자가 실제 남긴 긍정 리뷰 문장입니다. 상세페이지·광고 카피 소재로 활용하세요(과장 없이 실제 표현 그대로).'),
          React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
            copyCandidates.map(function(c, i) {
              return React.createElement('div', {
                key: 'copy-' + i,
                style: { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10 }
              },
                React.createElement('span', { style: { color: '#f59e0b', fontSize: 12, flexShrink: 0 } }, stars(c.rating)),
                React.createElement('span', { style: { fontSize: 13, fontWeight: 600, color: '#166534', lineHeight: 1.5 } }, '"' + c.copy + '"')
              );
            })
          )
        ) : null,

      /* 5. 리뷰 목록 */
      React.createElement('div', null,
        React.createElement('div', { style: { fontSize: 14, fontWeight: 700, color: '#1e293b', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 } },
          React.createElement('span', null, '📋'), '추출된 리뷰 목록 (표본 분석)',
          React.createElement('span', { style: { fontSize: 11, fontWeight: 500, color: '#94a3b8', marginLeft: 4 } },
            totalReviewCount ? ('전체 ' + fmt(totalReviewCount) + '건 중 ' + reviews.length + '건 표본') : ('(HTML에서 추출된 ' + reviews.length + '건)'))
        ),
        React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 12 } },
          displayedReviews.map(function(review, i) {
            var sentStyle = sentimentStyle[review.sentiment] || sentimentStyle.neutral;
            return React.createElement('div', {
              key: 'review-' + i,
              style: { background: '#f8fafc', borderRadius: 12, padding: '16px 20px', border: '1px solid #e2e8f0', transition: 'all 0.2s' }
            },
              /* 헤더: 별점 + 태그 + 감성 */
              React.createElement('div', {
                style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }
              },
                React.createElement('span', { style: { color: '#f59e0b', fontSize: 13, letterSpacing: 1 } }, stars(review.rating)),
                review.tags && review.tags.map(function(tag, j) {
                  return React.createElement('span', {
                    key: 'tag-' + j,
                    style: { fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 999, background: '#ede9fe', color: '#6d28d9' }
                  }, tag);
                }),
                React.createElement('span', {
                  style: Object.assign({ marginLeft: 'auto', fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 999 }, sentStyle)
                }, sentimentLabel[review.sentiment] || '중립')
              ),
              /* 리뷰 본문 */
              React.createElement('div', {
                style: { fontSize: 13, color: '#334155', lineHeight: 1.7 }
              }, review.text)
            );
          }),

          /* 더 보기 / 접기 버튼 */
          reviews.length > 3 ?
            React.createElement('button', {
              onClick: function() { setShowAll(!showAll); },
              style: {
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                width: '100%', padding: 10, marginTop: 4,
                background: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: 10,
                fontSize: 13, fontWeight: 600, color: '#64748b', cursor: 'pointer'
              }
            },
              showAll ? '▲ 접기' : '▼ 나머지 ' + remainingCount + '건 더 보기'
            ) : null
        )
      )
      )
    )
  );
};
