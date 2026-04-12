/* ReportSection — 보고서 내보내기 */
window.ReportSection = function ReportSection() {
    const { useState } = React;
    const [format, setFormat] = useState('json');
    const [days, setDays] = useState(30);
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);

    const handleExport = async () => {
        setLoading(true);
        try {
            const res = await api.post('/report/export', { format, date_range: days });
            if (res.success) setData(res.data);
        } catch (e) { alert('보고서 생성 실패'); }
        setLoading(false);
    };

    const handleDownloadCSV = () => {
        if (!data?.content) return;
        const bom = '\uFEFF';
        const blob = new Blob([bom + data.content], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `로직분석_보고서_${new Date().toISOString().slice(0, 10)}.csv`;
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
                <div className="card">
                    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                        <div className="form-group" style={{ marginBottom: 0 }}>
                            <label className="form-label">형식</label>
                            <select className="form-input" style={{ width: 120 }} value={format} onChange={e => setFormat(e.target.value)}>
                                <option value="json">JSON</option>
                                <option value="csv">CSV</option>
                            </select>
                        </div>
                        <div className="form-group" style={{ marginBottom: 0 }}>
                            <label className="form-label">기간</label>
                            <select className="form-input" style={{ width: 120 }} value={days} onChange={e => setDays(Number(e.target.value))}>
                                <option value={7}>최근 7일</option>
                                <option value={14}>최근 14일</option>
                                <option value={30}>최근 30일</option>
                                <option value={90}>최근 90일</option>
                            </select>
                        </div>
                        <button className="btn btn-primary" onClick={handleExport} disabled={loading}>
                            {loading ? '생성 중...' : '보고서 생성'}
                        </button>
                        {data?.format === 'csv' && (
                            <button className="btn btn-secondary" onClick={handleDownloadCSV}>📥 CSV 다운로드</button>
                        )}
                    </div>

                    {data && data.format === 'json' && (
                        <div style={{ marginTop: 16 }}>
                            <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
                                <span className="badge badge-blue">상품 {data.total_products}개</span>
                                <span className="badge badge-green">키워드 {data.total_keywords}개</span>
                                <span className="badge badge-gray">{data.generated_at?.slice(0, 10)}</span>
                            </div>
                            <div className="table-wrap" style={{ maxHeight: 300, overflow: 'auto' }}>
                                <table>
                                    <thead><tr><th>상품명</th><th>키워드</th><th>최근 순위</th><th>이력 수</th></tr></thead>
                                    <tbody>
                                        {(data.items || []).map((item, i) => (
                                            <tr key={i}>
                                                <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.product_name}</td>
                                                <td>{item.keyword}</td>
                                                <td style={{ fontWeight: 600 }}>{item.latest_rank ? `${item.latest_rank}위` : '-'}</td>
                                                <td>{item.history_count}건</td>
                                            </tr>
                                        ))}
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
