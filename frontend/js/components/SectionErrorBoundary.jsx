/* SectionErrorBoundary — 섹션별 에러 경계 (해당 섹션만 에러 표시, 나머지 정상 동작) */
(function() {
    function SectionErrorBoundary(props) {
        React.Component.call(this, props);
        this.state = { hasError: false, errorMsg: '' };
        this.handleRetry = this.handleRetry.bind(this);
    }
    SectionErrorBoundary.prototype = Object.create(React.Component.prototype);
    SectionErrorBoundary.prototype.constructor = SectionErrorBoundary;
    SectionErrorBoundary.getDerivedStateFromError = function(error) {
        return { hasError: true, errorMsg: String(error && error.message || error || '') };
    };
    SectionErrorBoundary.prototype.componentDidCatch = function(error, info) {
        var name = this.props.name || '알 수 없는 섹션';
        console.error('[SectionError:' + name + ']', error, info);
    };
    SectionErrorBoundary.prototype.handleRetry = function() {
        this.setState({ hasError: false, errorMsg: '' });
    };
    SectionErrorBoundary.prototype.render = function() {
        if (this.state.hasError) {
            var name = this.props.name || '섹션';
            return React.createElement('div', {
                className: 'section',
                style: { margin: '12px 0' }
            },
                React.createElement('div', {
                    className: 'container',
                    style: { background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 12, padding: '24px 20px', textAlign: 'center' }
                },
                    React.createElement('div', { style: { fontSize: 24, marginBottom: 8 } }, '\u26A0\uFE0F'),
                    React.createElement('div', { style: { fontSize: 14, fontWeight: 600, color: '#991b1b', marginBottom: 4 } },
                        name + ' 로드 중 오류가 발생했습니다'
                    ),
                    React.createElement('div', { style: { fontSize: 12, color: '#b91c1c', marginBottom: 12, opacity: 0.7 } },
                        this.state.errorMsg
                    ),
                    React.createElement('button', {
                        onClick: this.handleRetry,
                        style: { background: '#6C5CE7', color: '#fff', border: 'none', padding: '8px 20px', borderRadius: 6, fontSize: 13, fontWeight: 500, cursor: 'pointer', marginRight: 8 }
                    }, '\uB2E4\uC2DC \uC2DC\uB3C4')
                )
            );
        }
        return this.props.children;
    };
    window.SectionErrorBoundary = SectionErrorBoundary;
})();
