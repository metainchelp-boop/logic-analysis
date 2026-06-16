/* rankImage.js — 순위 이력 이미지(PNG) 생성 공용 헬퍼
 *
 * 진행중 업체(ClientDashboard)와 순위 추적(RankTrackingSection)이 동일한 이미지를 쓰도록
 * 캔버스 렌더링 로직을 한 곳으로 통합한다.
 *
 * window.exportRankHistoryImage({
 *   rows:      [{ checked_at, rank_position, check_type }, ...],  // 시간순 무관(내부에서 ASC 정렬)
 *   storeName: '업체명',
 *   keyword:   '키워드',
 *   storeUrl:  'https://smartstore.naver.com/...'(선택),
 *   days:      0|7|30|...  // 0/미지정 = 전체, N = 최근 N일
 * })
 */
(function () {
  function roundRect(ctx, x, y, w, h, r, fill, stroke) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
    if (fill) ctx.fill();
    if (stroke) ctx.stroke();
  }

  window.exportRankHistoryImage = function (opts) {
    opts = opts || {};
    var storeName = opts.storeName || '업체';
    var keyword = opts.keyword || '';
    var storeUrl = opts.storeUrl || '';
    var days = opts.days || 0;

    // ASC 정렬(오래된 날짜부터) — 소스 순서 무관하게 보장
    var allData = (opts.rows || []).slice().sort(function (a, b) {
      return String(a.checked_at || '').localeCompare(String(b.checked_at || ''));
    });

    var data = allData;
    var periodLabel = '전체';
    if (days && days > 0) {
      var cutoff = new Date();
      cutoff.setDate(cutoff.getDate() - days);
      data = allData.filter(function (r) { return new Date((r.checked_at || '').replace(' ', 'T')) >= cutoff; });
      periodLabel = '최근 ' + days + '일';
    }
    if (data.length === 0) {
      try { toast.warn('선택한 기간에 순위 데이터가 없습니다.'); } catch (e) {}
      return;
    }

    var padding = 40;
    var headerH = 90;
    var tableRowH = 32;
    var tableHeaderH = 36;
    var tableH = tableHeaderH + data.length * tableRowH;
    var chartH = 220;
    var chartGap = 40;
    var totalW = 720;
    var totalH = headerH + tableH + chartGap + chartH + padding * 2 + 30;

    var canvas = document.createElement('canvas');
    var dpr = window.devicePixelRatio || 2;
    canvas.width = totalW * dpr;
    canvas.height = totalH * dpr;
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, totalW, totalH);

    // 헤더 그라데이션
    var grad = ctx.createLinearGradient(0, 0, totalW, 0);
    grad.addColorStop(0, '#1B2A4A');
    grad.addColorStop(1, '#2d4a7a');
    ctx.fillStyle = grad;
    roundRect(ctx, padding - 10, padding - 10, totalW - padding * 2 + 20, headerH, 12, true, false);

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 20px "Noto Sans KR", sans-serif';
    ctx.fillText(storeName, padding + 10, padding + 24);

    ctx.font = '13px "Noto Sans KR", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.8)';
    var subText = '키워드: ' + keyword;
    if (storeUrl) {
      var dispUrl = storeUrl;
      try { var uu = new URL(dispUrl); if (uu.hostname.indexOf('smartstore') !== -1) dispUrl = uu.origin + uu.pathname; } catch (e) {}
      if (dispUrl.length > 55) dispUrl = dispUrl.slice(0, 55) + '...';
      subText += '   |   URL: ' + dispUrl;
    }
    ctx.fillText(subText, padding + 10, padding + 48);

    ctx.font = '11px "Noto Sans KR", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.6)';
    ctx.fillText('생성일: ' + new Date().toLocaleDateString('ko-KR') + '   |   조회 기간: ' + periodLabel + ' (' + data.length + '건)', padding + 10, padding + 68);

    // 테이블
    var tableY = padding + headerH + 20;
    ctx.font = 'bold 15px "Noto Sans KR", sans-serif';
    ctx.fillStyle = '#1e293b';
    ctx.fillText('"' + keyword + '" 순위 추적 이력 (' + data.length + '건)', padding, tableY);
    tableY += 16;

    var colX = [padding, padding + 250, padding + 430];

    ctx.fillStyle = '#f1f5f9';
    ctx.fillRect(padding, tableY, totalW - padding * 2, tableHeaderH);
    ctx.fillStyle = '#475569';
    ctx.font = 'bold 12px "Noto Sans KR", sans-serif';
    ctx.fillText('날짜', colX[0] + 12, tableY + 22);
    ctx.fillText('순위', colX[1] + 12, tableY + 22);
    ctx.fillText('유형', colX[2] + 12, tableY + 22);
    tableY += tableHeaderH;

    data.forEach(function (r, i) {
      var rowY = tableY + i * tableRowH;
      if (i % 2 === 0) { ctx.fillStyle = '#f8fafc'; ctx.fillRect(padding, rowY, totalW - padding * 2, tableRowH); }
      ctx.strokeStyle = '#e2e8f0'; ctx.lineWidth = 0.5;
      ctx.beginPath(); ctx.moveTo(padding, rowY + tableRowH); ctx.lineTo(totalW - padding, rowY + tableRowH); ctx.stroke();

      ctx.font = '12px "Noto Sans KR", sans-serif';
      ctx.fillStyle = '#334155';
      ctx.fillText((r.checked_at || '').slice(0, 16), colX[0] + 12, rowY + 20);

      var prevR = i > 0 ? data[i - 1] : null;
      var diff = (prevR && r.rank_position && prevR.rank_position) ? prevR.rank_position - r.rank_position : null;
      ctx.font = 'bold 13px "Noto Sans KR", sans-serif';
      var rankText = r.rank_position ? r.rank_position + '위' : '미노출';
      ctx.fillStyle = r.rank_position ? (r.rank_position <= 10 ? '#059669' : r.rank_position <= 40 ? '#d97706' : '#dc2626') : '#94a3b8';
      ctx.fillText(rankText, colX[1] + 12, rowY + 20);

      if (diff != null && diff !== 0) {
        var diffText = diff > 0 ? '▲' + diff : '▼' + Math.abs(diff);
        var tw = ctx.measureText(rankText).width;
        ctx.font = '11px "Noto Sans KR", sans-serif';
        ctx.fillStyle = diff > 0 ? '#16a34a' : '#dc2626';
        ctx.fillText(diffText, colX[1] + 12 + tw + 8, rowY + 20);
      }

      ctx.font = '12px "Noto Sans KR", sans-serif';
      ctx.fillStyle = '#64748b';
      ctx.fillText(r.check_type === 'manual' ? '수동' : '자동', colX[2] + 12, rowY + 20);
    });

    // 라인 차트
    var chartTop = tableY + data.length * tableRowH + chartGap;
    ctx.font = 'bold 15px "Noto Sans KR", sans-serif';
    ctx.fillStyle = '#1e293b';
    ctx.fillText('순위 변동 추이', padding, chartTop);
    chartTop += 20;

    var chartLeft = padding + 40;
    var chartRight = totalW - padding - 20;
    var chartBottom = chartTop + chartH - 30;
    var chartInnerTop = chartTop + 10;

    var validData = data.filter(function (r) { return r.rank_position != null && r.rank_position > 0; });
    if (validData.length > 1) {
      var ranks = validData.map(function (r) { return r.rank_position; });
      var maxRank = Math.max.apply(null, ranks);
      var minRank = Math.min.apply(null, ranks);
      var rankRange = Math.max(maxRank - minRank, 4);
      var yPad = Math.ceil(rankRange * 0.2);
      var yMin = Math.max(1, minRank - yPad);
      var yMax = maxRank + yPad;

      ctx.strokeStyle = '#e2e8f0'; ctx.lineWidth = 0.5;
      ctx.font = '10px "Noto Sans KR", sans-serif'; ctx.fillStyle = '#94a3b8';
      var ySteps = 5;
      for (var yi = 0; yi <= ySteps; yi++) {
        var yVal = Math.round(yMin + (yMax - yMin) * yi / ySteps);
        var yPos = chartInnerTop + (chartBottom - chartInnerTop) * (yi / ySteps);
        ctx.beginPath(); ctx.moveTo(chartLeft, yPos); ctx.lineTo(chartRight, yPos); ctx.stroke();
        ctx.textAlign = 'right'; ctx.fillText(yVal + '위', chartLeft - 6, yPos + 4);
      }
      ctx.textAlign = 'left';

      validData.forEach(function (r, i) {
        var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
        ctx.save(); ctx.font = '9px "Noto Sans KR", sans-serif'; ctx.fillStyle = '#94a3b8';
        ctx.translate(xPos, chartBottom + 12); ctx.rotate(-0.4);
        ctx.fillText((r.checked_at || '').slice(5, 10), 0, 0); ctx.restore();
      });

      ctx.beginPath(); ctx.strokeStyle = '#3b82f6'; ctx.lineWidth = 2.5; ctx.lineJoin = 'round';
      validData.forEach(function (r, i) {
        var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
        var yPos = chartInnerTop + (chartBottom - chartInnerTop) * ((r.rank_position - yMin) / (yMax - yMin));
        if (i === 0) ctx.moveTo(xPos, yPos); else ctx.lineTo(xPos, yPos);
      });
      ctx.stroke();

      ctx.beginPath();
      validData.forEach(function (r, i) {
        var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
        var yPos = chartInnerTop + (chartBottom - chartInnerTop) * ((r.rank_position - yMin) / (yMax - yMin));
        if (i === 0) ctx.moveTo(xPos, yPos); else ctx.lineTo(xPos, yPos);
      });
      ctx.lineTo(chartLeft + (chartRight - chartLeft), chartBottom);
      ctx.lineTo(chartLeft, chartBottom);
      ctx.closePath();
      var areaGrad = ctx.createLinearGradient(0, chartInnerTop, 0, chartBottom);
      areaGrad.addColorStop(0, 'rgba(59, 130, 246, 0.15)');
      areaGrad.addColorStop(1, 'rgba(59, 130, 246, 0.02)');
      ctx.fillStyle = areaGrad; ctx.fill();

      validData.forEach(function (r, i) {
        var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
        var yPos = chartInnerTop + (chartBottom - chartInnerTop) * ((r.rank_position - yMin) / (yMax - yMin));
        ctx.beginPath(); ctx.arc(xPos, yPos, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff'; ctx.fill();
        ctx.strokeStyle = '#3b82f6'; ctx.lineWidth = 2; ctx.stroke();
        ctx.font = 'bold 10px "Noto Sans KR", sans-serif'; ctx.fillStyle = '#1e40af'; ctx.textAlign = 'center';
        ctx.fillText(r.rank_position + '위', xPos, yPos - 10);
      });
      ctx.textAlign = 'left';
    } else {
      ctx.font = '13px "Noto Sans KR", sans-serif'; ctx.fillStyle = '#94a3b8';
      ctx.fillText('차트를 표시하려면 유효한 순위 데이터가 2건 이상 필요합니다.', chartLeft, chartTop + 60);
    }

    // 워터마크
    ctx.font = '10px "Noto Sans KR", sans-serif'; ctx.fillStyle = '#cbd5e1'; ctx.textAlign = 'right';
    ctx.fillText('METAINC 로직분석', totalW - padding, totalH - 12);
    ctx.textAlign = 'left';

    canvas.toBlob(function (blob) {
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = (storeName + '_' + keyword + '_순위이력_' + new Date().toISOString().slice(0, 10) + '.png').replace(/[\/\\?%*:|"<>]/g, '_');
      a.click();
      URL.revokeObjectURL(a.href);
    }, 'image/png');
  };
})();
