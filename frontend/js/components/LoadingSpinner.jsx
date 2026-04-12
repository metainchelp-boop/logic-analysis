/* LoadingSpinner — 로딩 인디케이터 */
window.LoadingSpinner = function LoadingSpinner({ text = '분석 중...' }) {
    return <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 20, justifyContent: 'center', color: '#64748b', fontSize: 14 }}>
        <span className="spinner" />{text}
    </div>;
};
