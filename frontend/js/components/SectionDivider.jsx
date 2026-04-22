/* SectionDivider — 섹터 간 시각적 구분선 (v5) */
window.SectionDivider = function SectionDivider(props) {
  var label = props && props.label ? props.label : '';
  var icon = props && props.icon ? props.icon : '';
  var color = props && props.color ? props.color : '#4f46e5';

  return (
    <div style={{
      maxWidth: 960, margin: '0 auto', padding: '12px 24px'
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12
      }}>
        <div style={{ flex: 1, height: 1, background: 'linear-gradient(90deg, transparent, ' + color + '33, transparent)' }}></div>
        {label && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '4px 14px', borderRadius: 999,
            background: color + '10', border: '1px solid ' + color + '22',
            fontSize: 11, fontWeight: 600, color: color, letterSpacing: '0.03em', whiteSpace: 'nowrap'
          }}>
            {icon && <span>{icon}</span>}
            {label}
          </div>
        )}
        <div style={{ flex: 1, height: 1, background: 'linear-gradient(90deg, transparent, ' + color + '33, transparent)' }}></div>
      </div>
    </div>
  );
};
