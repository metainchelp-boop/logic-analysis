/* ReportSection — 보고서 내보내기 (DOM 복제 HTML + JSON/CSV) */
window.ReportSection = function ReportSection(props) {
    var propKeyword = props && props.keyword || '';
    var propCompanyName = props && props.companyName || '';
    const { useState, useEffect } = React;
    const [format, setFormat] = useState('html');
    const [days, setDays] = useState(30);
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [companyName, setCompanyName] = useState(propCompanyName);

    /* props에서 업체명이 바뀌면 반영 */
    useEffect(function() {
        if (propCompanyName) setCompanyName(propCompanyName);
    }, [propCompanyName]);

    /* HTML 보고서 — 현재 페이지 DOM 복제 */
    var handleHtmlExport = function() {
        setLoading(true);
        try {
            /*
             * 페이지의 모든 분석 결과를 DOM 순서대로 자동 캡처
             * App 루트의 직접 자식 요소를 순회하여
             * 네비게이션/검색바/보고서/알림/푸터를 제외한 모든 콘텐츠를 수집
             */
            var captured = [];
            var rootEl = document.getElementById('root');
            if (rootEl && rootEl.children[0]) {
                var appDiv = rootEl.children[0];
                var children = Array.from(appDiv.children);
                children.forEach(function(child) {
                    /* 상단 네비게이션 요소 건너뛰기 */
                    if (child.classList.contains('topbar')) return;
                    if (child.querySelector && child.querySelector('.anchor-nav')) return;

                    /* 검색바 건너뛰기 */
                    if (child.classList.contains('search-section')) return;
                    var style = child.getAttribute('style') || '';
                    if (style.indexOf('sticky') !== -1 && style.indexOf('top') !== -1 && child.querySelector && child.querySelector('.anchor-btn')) return;

                    /* 보고서/알림/푸터 건너뛰기 */
                    if (child.id === 'sec-report') return;
                    if (child.id === 'sec-notify') return;
                    if (child.querySelector && child.querySelector('#sec-report')) return;
                    if (child.querySelector && child.querySelector('#sec-notify')) return;
                    if (child.tagName === 'FOOTER') return;

                    /* 빈 요소 건너뛰기 (조건부 렌더링으로 내용 없는 경우) */
                    if (!child.innerHTML || child.innerHTML.trim() === '') return;

                    /* 로딩 스피너 건너뛰기 */
                    if (child.querySelector && child.querySelector('.loading-spinner')) return;

                    captured.push(child.cloneNode(true));
                });
            }

            /* 폴백: 루트 탐색 실패 시 .section 클래스 기반 */
            if (captured.length === 0) {
                var allSections = document.querySelectorAll('.section');
                allSections.forEach(function(s) {
                    if (s.id === 'sec-report' || s.id === 'sec-notify') return;
                    captured.push(s.cloneNode(true));
                });
            }

            /* 클론에서 인터랙티브 요소 제거 + 반응형 클래스 부여 */
            captured.forEach(function(node) {
                var btns = node.querySelectorAll('button, .btn');
                btns.forEach(function(b) { b.remove(); });
                var inputs = node.querySelectorAll('input, select, textarea');
                inputs.forEach(function(inp) {
                    var span = document.createElement('span');
                    span.textContent = inp.value || '';
                    span.style.fontWeight = '600';
                    inp.parentNode.replaceChild(span, inp);
                });
                /* grid 레이아웃 요소에 반응형 클래스 추가 */
                var gridEls = node.querySelectorAll('[style*="grid-template-columns"]');
                gridEls.forEach(function(el) { el.classList.add('rpt-grid'); });
                var flexEls = node.querySelectorAll('[style*="display: flex"], [style*="display:flex"]');
                flexEls.forEach(function(el) { el.classList.add('rpt-flex'); });
            });

            /* CSS 수집 */
            var cssText = '';
            try {
                var sheets = document.styleSheets;
                for (var i = 0; i < sheets.length; i++) {
                    try {
                        var rules = sheets[i].cssRules || sheets[i].rules;
                        for (var j = 0; j < rules.length; j++) {
                            cssText += rules[j].cssText + '\n';
                        }
                    } catch(e) { /* cross-origin 무시 */ }
                }
            } catch(e) {}

            /* 섹션 HTML 합치기 */
            var bodyHtml = '';
            captured.forEach(function(node) {
                bodyHtml += node.outerHTML + '\n';
            });

            var dateStr = new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
            var headerText = companyName ? companyName + ' 분석 보고서' : '로직 분석 보고서';

            var fullHtml = '<!DOCTYPE html>\n<html lang="ko">\n<head>\n'
                + '<meta charset="UTF-8">\n'
                + '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                + '<title>' + headerText + ' - ' + dateStr + '</title>\n'
                + '<style>\n'
                + '* { margin: 0; padding: 0; box-sizing: border-box; }\n'
                + 'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #1e293b; }\n'
                + '.report-header { background: linear-gradient(135deg, #6C5CE7, #a29bfe); color: #fff; padding: 40px 20px; text-align: center; }\n'
                + '.report-header h1 { font-size: 24px; margin-bottom: 8px; }\n'
                + '.report-header p { font-size: 14px; opacity: 0.85; }\n'
                + '.report-footer { text-align: center; padding: 30px; color: #94a3b8; font-size: 12px; border-top: 1px solid #e2e8f0; margin-top: 40px; }\n'
                + cssText
                + '\n/* 반응형 — 모바일/태블릿/PC 대응 */\n'
                + '@media (max-width: 768px) {\n'
                + '  .report-header { padding: 24px 12px !important; }\n'
                + '  .report-header h1 { font-size: 18px !important; }\n'
                + '  .report-header p { font-size: 12px !important; }\n'
                + '  .report-content { padding: 8px !important; }\n'
                + '  .section, .card { padding: 12px !important; margin-bottom: 12px !important; }\n'
                + '  .container { padding: 0 4px !important; }\n'
                + '  .rpt-grid { grid-template-columns: 1fr !important; }\n'
                + '  .rpt-flex { flex-wrap: wrap !important; }\n'
                + '  .rpt-flex > div { min-width: 100% !important; flex: 1 1 100% !important; }\n'
                + '  div[style*="grid-template-columns"] { grid-template-columns: 1fr !important; }\n'
                + '  div[style*="display: flex"][style*="gap"] { flex-wrap: wrap !important; }\n'
                + '  div[style*="display:flex"][style*="gap"] { flex-wrap: wrap !important; }\n'
                + '  table { font-size: 11px !important; display: block !important; overflow-x: auto !important; }\n'
                + '  table th, table td { padding: 6px 4px !important; white-space: nowrap !important; }\n'
                + '  div[style*="font-size: 24px"], div[style*="font-size:24px"] { font-size: 18px !important; }\n'
                + '  div[style*="font-size: 28px"], div[style*="font-size:28px"] { font-size: 20px !important; }\n'
                + '  div[style*="font-size: 32px"], div[style*="font-size:32px"] { font-size: 22px !important; }\n'
                + '  img { max-width: 100% !important; height: auto !important; }\n'
                + '  .section-title { font-size: 15px !important; }\n'
                + '  .report-footer { padding: 16px !important; }\n'
                + '}\n'
                + '@media (min-width: 769px) and (max-width: 1024px) {\n'
                + '  .report-content { padding: 16px !important; }\n'
                + '  .rpt-grid { grid-template-columns: 1fr 1fr !important; }\n'
                + '  div[style*="grid-template-columns: 1fr 1fr 1fr"] { grid-template-columns: 1fr 1fr !important; }\n'
                + '}\n'
                + '@media print { .report-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }\n'
                + '</style>\n</head>\n<body>\n'
                + '<div class="report-header">\n'
                + '  <h1>' + headerText + '</h1>\n'
                + '  <p>' + dateStr + ' | 메타아이앤씨 로직 분석 시스템</p>\n'
                + '</div>\n'
                + '<div class="report-content" style="max-width:1200px; margin:0 auto; padding:20px;">\n'
                + bodyHtml
                + '</div>\n'
                + '<div class="report-footer">\n'
                + '  <p>\u00A9 2026 \uba54\ud0c0\uc544\uc774\uc564\uc528 \u2014 \ub85c\uc9c1 \ubd84\uc11d \uc2dc\uc2a4\ud15c | \ubcf8 \ubcf4\uace0\uc11c\ub294 \uc790\ub3d9 \uc0dd\uc131\ub418\uc5c8\uc2b5\ub2c8\ub2e4.</p>\n'
                + '</div>\n'
                + '</body>\n</html>';

            /* 다운로드 */
            var blob = new Blob([fullHtml], { type: 'text/html;charset=utf-8' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            var fileName = (companyName || '로직분석') + '_보고서_' + new Date().toISOString().slice(0, 10) + '.html';
            a.download = fileName;
            a.click();
            URL.revokeObjectURL(url);
            alert('HTML 보고서가 다운로드되었습니다.');
        } catch(e) {
            alert('HTML 보고서 생성 실패: ' + e.message);
        }
        setLoading(false);
    };

    /* JSON/CSV 보고서 (기존) */
    var handleDataExport = async function() {
        setLoading(true);
        try {
            var res = await api.post('/report/export', { format: format, date_range: days });
            if (res.success) setData(res.data);
        } catch(e) { alert('보고서 생성 실패'); }
        setLoading(false);
    };

    var handleExport = function() {
        if (format === 'html') { handleHtmlExport(); }
        else { handleDataExport(); }
    };

    var handleDownloadCSV = function() {
        if (!data || !data.content) return;
        var bom = '\uFEFF';
        var blob = new Blob([bom + data.content], { type: 'text/csv;charset=utf-8;' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = (companyName || '로직분석') + '_보고서_' + new Date().toISOString().slice(0, 10) + '.csv';
        a.click();
        URL.revokeObjectURL(url);
    };

    return (
        <div className="section fade-in" id="sec-report">
            <div className="container">
                <div className="section-title">
                    <span className="icon" style={{ background: '#eff6ff' }}>📄</span>
                    보고서 내보내기
                </div>
                <div className="section-line"></div>
                <p className="section-subtitle">분석 결과를 HTML/JSON/CSV로 다운로드합니다</p>
                <div className="card">
                    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                        <div className="form-group" style={{ marginBottom: 0 }}>
                            <label className="form-label">업체명 (선택)</label>
                            <input className="form-input" style={{ width: 160 }} placeholder="업체명 입력" value={companyName} onChange={function(e) { setCompanyName(e.target.value); }} />
                        </div>
                        <div className="form-group" style={{ marginBottom: 0 }}>
                            <label className="form-label">형식</label>
                            <select className="form-input" style={{ width: 140 }} value={format} onChange={function(e) { setFormat(e.target.value); }}>
                                <option value="html">HTML 보고서</option>
                                <option value="json">JSON</option>
                                <option value="csv">CSV</option>
                            </select>
                        </div>
                        {format !== 'html' && (
                            <div className="form-group" style={{ marginBottom: 0 }}>
                                <label className="form-label">기간</label>
                                <select className="form-input" style={{ width: 120 }} value={days} onChange={function(e) { setDays(Number(e.target.value)); }}>
                                    <option value={7}>최근 7일</option>
                                    <option value={14}>최근 14일</option>
                                    <option value={30}>최근 30일</option>
                                    <option value={90}>최근 90일</option>
                                </select>
                            </div>
                        )}
                        <button className="btn btn-primary" onClick={handleExport} disabled={loading}>
                            {loading ? '생성 중...' : format === 'html' ? '📄 HTML 보고서 다운로드' : '보고서 생성'}
                        </button>
                        {data && data.format === 'csv' && (
                            <button className="btn btn-secondary" onClick={handleDownloadCSV}>📥 CSV 다운로드</button>
                        )}
                    </div>
                    {format === 'html' && (
                        <div style={{ marginTop: 12, padding: '10px 14px', background: '#f0f9ff', borderRadius: 8, fontSize: 13, color: '#0369a1' }}>
                            💡 현재 페이지에 표시된 모든 분석 결과를 그대로 HTML 파일로 내보냅니다. 먼저 키워드 검색을 완료한 후 보고서를 생성해주세요.
                        </div>
                    )}

                    {data && data.format === 'json' && (
                        <div style={{ marginTop: 16 }}>
                            <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
                                <span className="badge badge-blue">상품 {data.total_products}개</span>
                                <span className="badge badge-green">키워드 {data.total_keywords}개</span>
                                <span className="badge badge-gray">{data.generated_at ? data.generated_at.slice(0, 10) : ''}</span>
                            </div>
                            <div className="table-wrap" style={{ maxHeight: 300, overflow: 'auto' }}>
                                <table>
                                    <thead><tr><th>상품명</th><th>키워드</th><th>최근 순위</th><th>이력 수</th></tr></thead>
                                    <tbody>
                                        {(data.items || []).map(function(item, i) {
                                            return (
                                                <tr key={i}>
                                                    <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.product_name}</td>
                                                    <td>{item.keyword}</td>
                                                    <td style={{ fontWeight: 600 }}>{item.latest_rank ? item.latest_rank + '위' : '-'}</td>
                                                    <td>{item.history_count}건</td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
