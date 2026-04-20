/* ErrorBoundary — React 에러 경계 (빈 화면 방지) */
(function() {
    function ErrorBoundary(props) {
        React.Component.call(this, props);
        this.state = { hasError: false, errorMsg: '' };
    }
    ErrorBoundary.prototype = Object.create(React.Component.prototype);
    ErrorBoundary.prototype.constructor = ErrorBoundary;
    ErrorBoundary.getDerivedStateFromError = function(error) {
        return { hasError: true, errorMsg: String(error && error.message || error || '') };
    };
    ErrorBoundary.prototype.componentDidCatch = function(error, info) {
        console.error('[ErrorBoundary]', error, info);
    };
    ErrorBoundary.prototype.render = function() {
        var self = this;
        if (this.state.hasError) {
            return React.createElement('div', {
                style: { minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#fef2f2', padding: 20 }
            },
                React.createElement('div', {
                    style: { background: '#fff', borderRadius: 16, padding: 40, maxWidth: 480, width: '100%', textAlign: 'center', boxShadow: '0 4px 20px rgba(0,0,0,0.08)' }
                },
                    React.createElement('div', { style: { fontSize: 48, marginBottom: 16 } }, '\u26A0'),
                    React.createElement('h2', { style: { marginBottom: 12, color: '#1e293b' } }, '\uD654\uBA74 \uB85C\uB4DC \uC624\uB958'),
                    React.createElement('p', { style: { color: '#64748b', marginBottom: 20, fontSize: 14 } }, this.state.errorMsg),
                    React.createElement('button', {
                        onClick: function() { window.location.reload(); },
                        style: { background: '#6C5CE7', color: '#fff', border: 'none', padding: '12px 28px', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer' }
                    }, '\uC0C8\uB85C\uACE0\uCE68')
                )
            );
        }
        return this.props.children;
    };
    window.ErrorBoundary = ErrorBoundary;
})();
