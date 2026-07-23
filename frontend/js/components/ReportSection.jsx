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

    /* HTML 보고서 — 공용 캡처 빌더(ReportCapture) 사용
     * 업체 자동저장 경로와 동일한 빌더를 써서 직원용 UI가 전달본에 섞이는 것을 원천 차단 */
    var handleHtmlExport = function() {
        /* AI 종합 분석이 진행 중이면 완료 대기를 먼저 권유 (강행 시 해당 섹션은 '별도 전달' 안내로 대체) */
        try {
            if (window.ReportCapture && window.ReportCapture.aiState() === 'loading') {
                var goNow = window.confirm('🤖 AI 종합 분석이 아직 진행 중입니다 (약 20~30초).\n완료 후 내보내면 AI 분석이 보고서에 포함됩니다.\n\n지금 바로 내보내시겠습니까?\n(AI 섹션은 "완료 후 별도 전달" 안내로 대체됩니다)');
                if (!goNow) return;
            }
        } catch(eG) {}
        setLoading(true);
        try {
            var headerText = companyName ? companyName + ' 분석 보고서' : '로직 분석 보고서';
            var fullHtml = window.ReportCapture
                ? window.ReportCapture.buildHtml({ title: headerText, managerName: props && props.managerName })
                : '';
            if (!fullHtml) { throw new Error('캡처 대상(.report-main)을 찾지 못했습니다'); }

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
