/* EmptyState — 빈 상태 표시 */
window.EmptyState = function EmptyState({ icon = '📊', text = '데이터가 없습니다' }) {
    return <div className="empty-state"><div className="empty-icon">{icon}</div><p>{text}</p></div>;
};
