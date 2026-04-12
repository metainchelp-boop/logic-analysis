window.SummaryCardsSection = function SummaryCardsSection(props) {
  if (!props?.data) return null;
  const { keyword, rank, totalProducts, score, improvementCount } = props.data;

  if (!keyword) return null;

  return (
    <div className="section">
      <div className="summary-grid">
        <StatCard
          label="분석 키워드"
          value={keyword}
          icon="🔍"
        />
        <StatCard
          label="검색결과 내 순위"
          value={`${rank}위/${fmt(totalProducts)}개`}
          icon="📍"
        />
        <StatCard
          label="광고주 종합점수"
          value={`${score}점`}
          icon="⭐"
        />
        <StatCard
          label="개선 필요 항목"
          value={`${improvementCount}개 항목`}
          icon="⚠️"
        />
      </div>

      <style>{`
        .summary-grid {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 16px;
        }
        @media (max-width: 1024px) {
          .summary-grid {
            grid-template-columns: repeat(2, 1fr);
          }
        }
        @media (max-width: 768px) {
          .summary-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};
