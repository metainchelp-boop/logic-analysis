/*
 * ChartCanvas — Chart.js 재사용 래퍼 (광고주 보고서 차트 통일용)
 * 사용: <ChartCanvas type="bar" data={...} options={...} height={220} />
 * - canvas ref에 Chart 인스턴스 생성, 언마운트/데이터변경 시 destroy
 * - Chart 전역 미로드 시 안전 가드(차트 영역만 비움, 앱은 정상)
 */
(function () {
  // 보고서 공통 색상 팔레트 (미리보기 시안과 동일)
  window.CHART_COLORS = {
    IND: '#4f46e5',   // 인디고(주색)
    PUR: '#9333ea',   // 보라
    PINK: '#ec4899',  // 핑크(내 상품 강조)
    OK: '#16a34a',    // 초록(긍정)
    RED: '#ef4444',   // 빨강(경고)
    BLUE: '#2563eb',  // 파랑
    WARN: '#f59e0b',  // 주황(경쟁)
    GRID: '#eef2f7',  // 연한 격자/잔여
    SOFT: '#a5b4fc',  // 연인디고(보조 막대)
    SOFT2: '#c7d2fe'  // 더 연한 인디고
  };

  // 세로 그라데이션 헬퍼 (라인/영역 채우기용)
  window.chartGrad = function (ctx, c1, c2, h) {
    var g = ctx.createLinearGradient(0, 0, 0, h || 220);
    g.addColorStop(0, c1);
    g.addColorStop(1, c2);
    return g;
  };

  // 천단위 콤마
  window.chartComma = function (v) {
    if (v == null) return '';
    return String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  };

  window.ChartCanvas = function ChartCanvas(props) {
    var canvasRef = React.useRef(null);
    var chartRef = React.useRef(null);
    var height = props.height || 220;

    React.useEffect(function () {
      if (typeof Chart === 'undefined') return; // Chart.js 아직 미로드 — 가드
      var el = canvasRef.current;
      if (!el) return;

      // 이전 인스턴스 정리
      if (chartRef.current) {
        try { chartRef.current.destroy(); } catch (e) {}
        chartRef.current = null;
      }

      try {
        chartRef.current = new Chart(el.getContext('2d'), {
          type: props.type,
          data: props.data,
          options: Object.assign({ responsive: true, maintainAspectRatio: false }, props.options || {})
        });
      } catch (e) {
        if (window.console) console.warn('[ChartCanvas] render 실패:', e);
      }

      return function () {
        if (chartRef.current) {
          try { chartRef.current.destroy(); } catch (e) {}
          chartRef.current = null;
        }
      };
      // data/options/type 변경 시 재생성
    }, [JSON.stringify(props.data), JSON.stringify(props.options), props.type, height]);

    return React.createElement('div', {
      style: Object.assign({ position: 'relative', height: height, width: '100%' }, props.style || {})
    }, React.createElement('canvas', { ref: canvasRef, id: props.canvasId }));
  };
})();
