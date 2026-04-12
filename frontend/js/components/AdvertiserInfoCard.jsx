window.AdvertiserInfoCard = function AdvertiserInfoCard(props) {
  if (!props?.data) return null;
  const { imageUrl, productName, keyword1, keyword2 } = props.data;

  if (!productName) return null;

  return (
    <div style={{
      padding: '16px',
      backgroundColor: '#fff',
      borderRadius: '8px',
      border: '1px solid #e5e5e5',
      borderLeft: '4px solid #4f46e5',
      display: 'flex',
      gap: '16px',
      alignItems: 'flex-start'
    }}>
      {/* Product Image */}
      {imageUrl && (
        <div style={{
          flexShrink: 0,
          width: '80px',
          height: '80px',
          borderRadius: '6px',
          overflow: 'hidden',
          backgroundColor: '#f5f5f5',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}>
          <img
            src={imageUrl}
            alt={productName}
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'cover'
            }}
            onError={(e) => {
              e.target.style.display = 'none';
              e.target.parentElement.innerHTML = '<div style="font-size: 24px; color: #ccc;">📦</div>';
            }}
          />
        </div>
      )}

      {/* Info */}
      <div style={{ flex: 1 }}>
        <div style={{
          fontSize: '14px',
          fontWeight: '600',
          color: '#333',
          marginBottom: '12px',
          lineHeight: '1.4'
        }}>
          {productName}
        </div>

        {/* Keywords */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {keyword1 && (
            <span className="badge badge-blue" style={{ fontSize: '11px', padding: '4px 8px' }}>
              {keyword1}
            </span>
          )}
          {keyword2 && (
            <span className="badge badge-blue" style={{ fontSize: '11px', padding: '4px 8px' }}>
              {keyword2}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
