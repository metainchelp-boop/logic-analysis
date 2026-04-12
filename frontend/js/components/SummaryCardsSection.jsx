window.SummaryCardsSection = function SummaryCardsSection(props) {
  if (!props?.data) return null;
  const { totalVolume, productCount, goldenCount, compLevel } = props.data;

  return (
    <div className="section">
      <div className="summary-grid">
        <StatCard label="월간 총 검색량" value={totalVolume + '회'} icon="🔍" />
        <StatCard label="네이버 쇼핑 상품 수" value={productCount + '개'} icon="📦" />
        <StatCard label="골든 키워드" value={goldenCount + '개 발견'} icon="💎" />
        <StatCard label="경쟁강도" value={compLevel || '-'} icon="⚡" />
      </div>

      <style>{`
        .summary-grid {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 16px;
        }
        @media (max-width: 1024px) {
          .summary-grid { grid-template-columns: repeat(2, 1fr); }
        }
        @media (max-width: 768px) {
          .summary-grid { grid-template-columns: 1fr; }
        }
      `}</style>
    </div>
  );
};
