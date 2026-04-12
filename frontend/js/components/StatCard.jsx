/* StatCard — 스탯 카드 위젯 */
window.StatCard = function StatCard({ icon, iconColor, label, value, sub }) {
    return (
        <div className="card">
            <div className={`stat-icon ${iconColor}`}>{icon}</div>
            <div className="stat-label">{label}</div>
            <div className="stat-value">{value}</div>
            {sub && <div className="stat-sub">{sub}</div>}
        </div>
    );
};
