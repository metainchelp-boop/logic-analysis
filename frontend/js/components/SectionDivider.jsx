/* SectionDivider — 섹터 구분 헤더 (v6.1 미리보기 디자인) */
window.SectionDivider = function SectionDivider(props) {
  var label = props && props.label ? props.label : '';
  var icon = props && props.icon ? props.icon : '';
  var color = props && props.color ? props.color : '#4f46e5';
  var sub = props && props.sub ? props.sub : '';

  return (
    <div className="report-divider" style={{ maxWidth: 1000, margin: '34px auto 16px', padding: '0 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{
          width: 40, height: 40, borderRadius: 12, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 20, color: '#fff',
          background: 'linear-gradient(135deg, ' + color + ', ' + color + 'cc)',
          boxShadow: '0 4px 12px ' + color + '40'
        }}>{icon}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 900, fontSize: 20, letterSpacing: '-0.5px', color: '#0f172a', lineHeight: 1.2 }}>{label}</div>
          {sub && <div style={{ fontWeight: 500, fontSize: 12, color: '#64748b', marginTop: 2 }}>{sub}</div>}
        </div>
      </div>
    </div>
  );
};
