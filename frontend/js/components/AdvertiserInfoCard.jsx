window.AdvertiserInfoCard = function AdvertiserInfoCard(props) {
  if (!props?.data) return null;
  const { adDepth, pcClicks, mobileClicks, compIdx } = props.data;

  return (
    <div className="section">
      <h2 className="section-title">📢 광고 경쟁 정보</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginTop: '16px' }}>
        <div style={{ padding: '16px', backgroundColor: '#f0f7ff', borderRadius: '8px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', color: '#666', marginBottom: '8px' }}>광고 노출 깊이</div>
          <div style={{ fontSize: '24px', fontWeight: '700', color: '#1976d2' }}>{adDepth || 0}</div>
        </div>
        <div style={{ padding: '16px', backgroundColor: '#f0fdf4', borderRadius: '8px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', color: '#666', marginBottom: '8px' }}>PC 평균 클릭수</div>
          <div style={{ fontSize: '24px', fontWeight: '700', color: '#16a34a' }}>{pcClicks}회</div>
        </div>
        <div style={{ padding: '16px', backgroundColor: '#fef3c7', borderRadius: '8px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', color: '#666', marginBottom: '8px' }}>모바일 평균 클릭수</div>
          <div style={{ fontSize: '24px', fontWeight: '700', color: '#b45309' }}>{mobileClicks}회</div>
        </div>
        <div style={{ padding: '16px', backgroundColor: '#fce7f3', borderRadius: '8px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', color: '#666', marginBottom: '8px' }}>광고 경쟁강도</div>
          <div style={{ fontSize: '24px', fontWeight: '700', color: '#be185d' }}>{compIdx || '-'}</div>
        </div>
      </div>
    </div>
  );
};
