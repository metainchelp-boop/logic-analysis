/* PlaceRankChart — 플레이스 (업체·키워드) 일자별 순위 추이 (역Y축 선형 차트)
 * props: { series:[{date,rank,state}], keyword, days, onDays(days), onSave() }
 * 순위는 낮을수록 상위 → Y축 reverse. 미노출/미확인(rank=null)은 선이 끊김(spanGaps=false).
 * ChartCanvas(Chart.js 래퍼) 재사용 — 쇼핑 순위 추적과 동일 엔진.
 */
window.PlaceRankChart = function PlaceRankChart(props) {
    var series = Array.isArray(props.series) ? props.series : [];
    var keyword = props.keyword || '대표 키워드';
    var days = props.days || 30;
    var onDays = props.onDays || function(){};

    var labels = series.map(function(p) {
        var d = String(p.date || '').split('-');
        return d.length === 3 ? (parseInt(d[1], 10) + '/' + parseInt(d[2], 10)) : (p.date || '');
    });
    var ranks = series.map(function(p) { return (p.rank == null ? null : p.rank); });
    var valid = ranks.filter(function(r) { return r != null; });
    var maxR = valid.length ? Math.max.apply(null, valid) : 16;
    var yMax = Math.max(16, maxR + 2);
    var OK = (window.CHART_COLORS && window.CHART_COLORS.OK) || '#16a34a';

    var data = {
        labels: labels,
        datasets: [{
            label: '순위', data: ranks,
            borderColor: OK, backgroundColor: 'rgba(22,163,74,0.12)',
            fill: true, spanGaps: false, tension: 0.3,
            pointRadius: 3, pointHoverRadius: 5, pointBackgroundColor: OK, borderWidth: 2.5
        }]
    };
    var options = {
        responsive: true, maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: function(c) { return (c.parsed.y == null) ? '미노출/미확인' : (c.parsed.y + '위'); } } }
        },
        scales: {
            y: {
                reverse: true, min: 1, suggestedMax: yMax,
                ticks: { stepSize: Math.max(1, Math.round(yMax / 6)), callback: function(v) { return v + '위'; } },
                title: { display: true, text: '순위 (낮을수록 상위 ↑)', font: { size: 10 } },
                grid: { color: '#eef2f7' }
            },
            x: { grid: { display: false } }
        }
    };

    var CANVAS_ID = 'place-rankchart';
    var saveImg = function() {
        try {
            var cv = document.getElementById(CANVAS_ID);
            var url = '';
            var ch = (window.Chart && window.Chart.getChart && cv) ? window.Chart.getChart(cv) : null;
            if (ch) { url = ch.toBase64Image('image/png', 1); }
            else if (cv && cv.toDataURL) { url = cv.toDataURL('image/png'); }
            if (!url) { try { toast.warn('차트가 아직 렌더되지 않았습니다.'); } catch(e) {} return; }
            var a = document.createElement('a');
            a.href = url;
            a.download = keyword + '_순위추이_' + new Date().toISOString().slice(0, 10) + '.png';
            document.body.appendChild(a); a.click(); a.remove();
        } catch (e) {
            try { toast.error('이미지 저장 실패'); } catch(e2) {}
        }
    };

    var periodBtn = function(label, val) {
        var on = (val === 'all') ? (days >= 365) : (days === val);
        return React.createElement('button', {
            className: on ? 'on' : '', onClick: function() { onDays(val === 'all' ? 365 : val); }
        }, label);
    };

    return React.createElement('div', { className: 'subcard' },
        React.createElement('div', { className: 'h' },
            React.createElement('span', { className: 't' }, "📉 '" + keyword + "' 순위 추이"),
            React.createElement('div', { className: 'periods' },
                periodBtn('7일', 7), periodBtn('30일', 30), periodBtn('전체', 'all')
            ),
            React.createElement('button', { className: 'btn btn-success btn-sm', style: { marginLeft: 7 }, onClick: saveImg }, '📸 이미지 저장')
        ),
        series.length === 0
            ? React.createElement('div', { className: 'empty', style: { padding: '22px 6px' } },
                '아직 추적 데이터가 없습니다. 이 키워드로 분석할 때마다 순위가 하루 1점씩 누적됩니다.')
            : React.createElement('div', { className: 'chartbox', style: { height: 200 } },
                React.createElement(window.ChartCanvas, { type: 'line', data: data, options: options, height: 200, canvasId: CANVAS_ID })),
        React.createElement('div', { className: 'chartfoot' },
            '※ 선이 위로 갈수록 상위 노출(1위=맨 위). 끊긴 구간은 200위 밖 또는 미확인. 플레이스는 서버 크롤이 불가해 캡처할 때마다 순위가 저장됩니다.')
    );
};
