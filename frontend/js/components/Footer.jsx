/* Footer — 하단 푸터 (App.jsx에서 분리, 중복 제거) */
window.Footer = function Footer() {
    return React.createElement('footer', { className: 'footer' },
        React.createElement('div', { className: 'container' },
            '© 2026 메타아이앤씨 — 로직 분석 ' + APP_VERSION + ' | 네이버 쇼핑 키워드 분석 & 순위 추적'
        )
    );
};
