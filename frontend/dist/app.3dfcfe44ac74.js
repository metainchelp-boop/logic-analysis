
;/* ===== js/utils.js ===== */
/* ===== 로직 분석 — API 헬퍼 & 유틸리티 ===== */

// ===== 앱 버전 (한 곳에서 관리) =====
var APP_VERSION = window.APP_VERSION = 'v6.5.2';

// ===== 401 중복 새로고침 방지 플래그 =====
var _isAuthRedirecting = false;

// ===== 토스트 알림 시스템 =====
var toast = function () {
  var container = null;
  function _getContainer() {
    if (container) return container;
    container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;display:flex;flex-direction:column;gap:8px;pointer-events:none;';
    document.body.appendChild(container);
    return container;
  }
  function show(message, type) {
    var colors = {
      error: {
        bg: '#FEE2E2',
        border: '#EF4444',
        text: '#991B1B',
        icon: '\u274C'
      },
      success: {
        bg: '#DCFCE7',
        border: '#22C55E',
        text: '#166534',
        icon: '\u2705'
      },
      warn: {
        bg: '#FEF9C3',
        border: '#EAB308',
        text: '#854D0E',
        icon: '\u26A0\uFE0F'
      },
      info: {
        bg: '#DBEAFE',
        border: '#3B82F6',
        text: '#1E40AF',
        icon: '\u2139\uFE0F'
      }
    };
    var c = colors[type] || colors.info;
    var el = document.createElement('div');
    el.style.cssText = 'background:' + c.bg + ';border:1px solid ' + c.border + ';color:' + c.text + ';padding:12px 18px;border-radius:10px;font-size:13px;font-weight:500;box-shadow:0 4px 12px rgba(0,0,0,0.12);pointer-events:auto;max-width:380px;opacity:0;transform:translateX(40px);transition:all 0.3s ease;';
    el.textContent = c.icon + '  ' + message;
    _getContainer().appendChild(el);
    requestAnimationFrame(function () {
      el.style.opacity = '1';
      el.style.transform = 'translateX(0)';
    });
    setTimeout(function () {
      el.style.opacity = '0';
      el.style.transform = 'translateX(40px)';
      setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 300);
    }, type === 'error' ? 5000 : 3000);
  }
  return {
    error: function (msg) {
      show(msg, 'error');
    },
    success: function (msg) {
      show(msg, 'success');
    },
    warn: function (msg) {
      show(msg, 'warn');
    },
    info: function (msg) {
      show(msg, 'info');
    }
  };
}();

// API 헬퍼 (인증 토큰 자동 포함 + 에러 토스트)
var API_BASE = '/api';
function _authHeaders(extra) {
  var headers = {};
  try {
    var token = sessionStorage.getItem('logic_token');
    if (token) headers['Authorization'] = 'Bearer ' + token;
  } catch (e) {}
  if (extra) {
    for (var k in extra) headers[k] = extra[k];
  }
  return headers;
}
function _handleResponse(r) {
  if (!r.ok) {
    var status = r.status;
    if (status === 401) {
      // 세션 만료로 리로드하는 조건:
      // 1) 로그인 API가 아닐 것 (로그인 실패 401은 정상)
      // 2) 현재 토큰이 있을 것 (비로그인 상태면 리로드 불필요)
      // 3) 아직 리다이렉트 중이 아닐 것 (중복 방지)
      var isLoginRequest = r.url && r.url.indexOf('/auth/login') !== -1;
      var hasToken = false;
      try {
        hasToken = !!sessionStorage.getItem('logic_token');
      } catch (e) {}
      if (!isLoginRequest && hasToken && !_isAuthRedirecting) {
        _isAuthRedirecting = true;
        toast.error('인증이 만료되었습니다. 다시 로그인해주세요.');
        try {
          sessionStorage.removeItem('logic_token');
          sessionStorage.removeItem('logic_user');
        } catch (e) {}
        setTimeout(function () {
          location.reload();
        }, 1500);
        return Promise.resolve({
          success: false,
          detail: '인증 만료'
        });
      }
    } else if (status === 403) {
      toast.error('접근 권한이 없습니다.');
    } else if (status >= 500) {
      toast.error('서버 오류가 발생했습니다. (' + status + ')');
    }
    return r.json().catch(function () {
      return {
        success: false,
        detail: '요청 실패 (' + status + ')'
      };
    }).then(function (body) {
      if (body && typeof body === 'object' && !body.hasOwnProperty('success')) {
        body.success = false;
      }
      return body;
    });
  }
  return r.json().then(function (body) {
    if (body && typeof body === 'object' && !body.hasOwnProperty('success')) {
      body.success = true;
    }
    return body;
  });
}
function _handleNetworkError(e) {
  toast.error('네트워크 연결 오류 — 인터넷 연결을 확인해주세요.');
  throw e;
}
var api = {
  get: function (url) {
    return fetch(API_BASE + url, {
      headers: _authHeaders()
    }).then(_handleResponse).catch(_handleNetworkError);
  },
  post: function (url, body) {
    return fetch(API_BASE + url, {
      method: 'POST',
      headers: _authHeaders({
        'Content-Type': 'application/json'
      }),
      body: JSON.stringify(body)
    }).then(_handleResponse).catch(_handleNetworkError);
  },
  put: function (url, body) {
    return fetch(API_BASE + url, {
      method: 'PUT',
      headers: _authHeaders({
        'Content-Type': 'application/json'
      }),
      body: JSON.stringify(body)
    }).then(_handleResponse).catch(_handleNetworkError);
  },
  del: function (url) {
    return fetch(API_BASE + url, {
      method: 'DELETE',
      headers: _authHeaders()
    }).then(_handleResponse).catch(_handleNetworkError);
  }
};

// 숫자 포맷팅
function fmt(n) {
  return n != null ? Number(n).toLocaleString() : '-';
}

// 경쟁강도 라벨
function compLabel(c) {
  var map = {
    '낮음': '낮음',
    'LOW': '낮음',
    '보통': '보통',
    'MEDIUM': '보통',
    '높음': '높음',
    'HIGH': '높음',
    '': '-'
  };
  return map[c] || c || '-';
}

// 경쟁강도 배지 클래스
function compClass(c) {
  var low = ['낮음', 'LOW', ''];
  var mid = ['보통', 'MEDIUM'];
  if (low.indexOf(c) !== -1) return 'badge-green';
  if (mid.indexOf(c) !== -1) return 'badge-amber';
  return 'badge-red';
}

// ===== 공통 유틸리티 (리팩토링 v3.9.11) =====

// 순위 뱃지 (1~3위 금/은/동)
function getRankBadge(rank) {
  if (rank <= 3) {
    var cls = rank === 1 ? 'gold' : rank === 2 ? 'silver' : 'bronze';
    return React.createElement('span', {
      className: 'rank-badge ' + cls
    }, rank);
  }
  return rank;
}

// SEO 점수 색상
function scoreColor(s) {
  return s >= 70 ? '#059669' : s >= 40 ? '#d97706' : '#dc2626';
}

// SEO 점수 배경색
function scoreBg(s) {
  return s >= 70 ? '#ecfdf5' : s >= 40 ? '#fffbeb' : '#fef2f2';
}

// 순위별 CTR 테이블 (1~80위, 업계 벤치마크)
var CTR_TABLE = [0.080, 0.070, 0.060, 0.050, 0.030, 0.025, 0.020, 0.018, 0.016, 0.015, 0.013, 0.012, 0.011, 0.010, 0.010, 0.009, 0.009, 0.008, 0.008, 0.008, 0.007, 0.007, 0.006, 0.006, 0.006, 0.005, 0.005, 0.005, 0.005, 0.005, 0.004, 0.004, 0.004, 0.004, 0.004, 0.003, 0.003, 0.003, 0.003, 0.003, 0.0028, 0.0026, 0.0024, 0.0022, 0.0020, 0.0019, 0.0018, 0.0017, 0.0016, 0.0015, 0.0014, 0.0013, 0.0013, 0.0012, 0.0012, 0.0011, 0.0011, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010, 0.0010];

// CTR 가져오기 (rank: 1-based)
function getCTR(rank) {
  return rank >= 1 && rank <= CTR_TABLE.length ? CTR_TABLE[rank - 1] : 0.001;
}

// 붙여넣은 상품 페이지 HTML에서 상품 URL 자동 추출 (URL 따로 입력 불필요)
// 우선순위: og:url 메타 → canonical → HTML 내 네이버 쇼핑 상품 URL 패턴
// 지원 호스트: smartstore / brand(브랜드스토어) / shopping(가격비교) + m. 서브도메인
var _naverProductUrlRe = /https?:\/\/(?:[a-z0-9-]+\.)*(?:smartstore|brand|shopping)\.naver\.com(?:\/[A-Za-z0-9_-]+)?\/(?:products|catalog)\/\d+/g;
// og:url/canonical 검증용 — 가격비교(search.shopping.naver.com/catalog/123)처럼
// 도메인 바로 뒤에 catalog/products가 오는 경우까지 허용 (중간 경로 0개 이상)
var _naverProductUrlTest = /naver\.com\/(?:[\w-]+\/)*(?:products|catalog)\/\d+/;
function extractProductUrlFromHtml(html) {
  if (!html || typeof html !== 'string') return '';
  try {
    // JSON(window 상태 등) 안의 URL은 슬래시가 "\/" 로 이스케이프돼 있어
    // 정규식이 못 잡는다 → 사본에서 슬래시를 복원해 함께 검사한다.
    var h = html.indexOf('\\/') >= 0 ? html.replace(/\\\//g, '/') : html;
    var m;
    m = h.match(/<meta[^>]+property=["']og:url["'][^>]*content=["']([^"']+)["']/i) || h.match(/<meta[^>]+content=["']([^"']+)["'][^>]*property=["']og:url["']/i);
    if (m && m[1] && _naverProductUrlTest.test(m[1])) return m[1].split('?')[0];
    m = h.match(/<link[^>]+rel=["']canonical["'][^>]*href=["']([^"']+)["']/i) || h.match(/<link[^>]+href=["']([^"']+)["'][^>]*rel=["']canonical["']/i);
    if (m && m[1] && _naverProductUrlTest.test(m[1])) return m[1].split('?')[0];
    // 3) HTML 내 네이버 쇼핑 상품 URL 중 '가장 많이 등장하는 것' = 본 상품
    //    (추천/광고 상품은 보통 1번만 나옴 → 빈도로 본 상품 구별, 2회 이상만 신뢰)
    //    smartstore 외에 brand(브랜드스토어)·shopping(가격비교)·m. 모바일도 인식
    var all = h.match(_naverProductUrlRe);
    if (all && all.length) {
      var counts = {};
      for (var i = 0; i < all.length; i++) {
        var u = all[i].split('?')[0];
        counts[u] = (counts[u] || 0) + 1;
      }
      var best = '',
        bestN = 0;
      for (var k in counts) {
        if (counts[k] > bestN) {
          bestN = counts[k];
          best = k;
        }
      }
      if (best && bestN >= 2) return best;
      // 2회 미만이라도 후보 상품 URL이 '단 하나'뿐이면 그것이 본 상품
      // (추천/광고 상품이 섞이지 않은 경우 → 오인식 위험 없이 추출 성공률 향상)
      if (best && Object.keys(counts).length === 1) return best;
    }
    // 못 찾으면 빈값 — '가짜 채널(/main/)·아무 상품번호'로 엉뚱한 상품을 잡는 것보다 안전.
    return '';
  } catch (e) {
    return '';
  }
}

// 저장용 상세분석 경량화 — 리뷰 배열을 20개로 제한(목록 조회 비대화 방지)
function trimHtmlDetail(hd) {
  if (!hd || typeof hd !== 'object') return hd;
  try {
    var copy = Object.assign({}, hd);
    if (copy.reviewData && Array.isArray(copy.reviewData.reviews)) {
      copy.reviewData = Object.assign({}, copy.reviewData, {
        reviews: copy.reviewData.reviews.slice(0, 20)
      });
    }
    return copy;
  } catch (e) {
    return hd;
  }
}

;/* ===== js/rankImage.js ===== */
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
      data = allData.filter(function (r) {
        return new Date((r.checked_at || '').replace(' ', 'T')) >= cutoff;
      });
      periodLabel = '최근 ' + days + '일';
    }
    if (data.length === 0) {
      try {
        toast.warn('선택한 기간에 순위 데이터가 없습니다.');
      } catch (e) {}
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
      try {
        var uu = new URL(dispUrl);
        if (uu.hostname.indexOf('smartstore') !== -1) dispUrl = uu.origin + uu.pathname;
      } catch (e) {}
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
      if (i % 2 === 0) {
        ctx.fillStyle = '#f8fafc';
        ctx.fillRect(padding, rowY, totalW - padding * 2, tableRowH);
      }
      ctx.strokeStyle = '#e2e8f0';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(padding, rowY + tableRowH);
      ctx.lineTo(totalW - padding, rowY + tableRowH);
      ctx.stroke();
      ctx.font = '12px "Noto Sans KR", sans-serif';
      ctx.fillStyle = '#334155';
      ctx.fillText((r.checked_at || '').slice(0, 16), colX[0] + 12, rowY + 20);
      var prevR = i > 0 ? data[i - 1] : null;
      var diff = prevR && r.rank_position && prevR.rank_position ? prevR.rank_position - r.rank_position : null;
      ctx.font = 'bold 13px "Noto Sans KR", sans-serif';
      var rankText = r.rank_position ? r.rank_position + '위' : '미노출';
      ctx.fillStyle = r.rank_position ? r.rank_position <= 10 ? '#059669' : r.rank_position <= 40 ? '#d97706' : '#dc2626' : '#94a3b8';
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
    var validData = data.filter(function (r) {
      return r.rank_position != null && r.rank_position > 0;
    });
    if (validData.length > 1) {
      var ranks = validData.map(function (r) {
        return r.rank_position;
      });
      var maxRank = Math.max.apply(null, ranks);
      var minRank = Math.min.apply(null, ranks);
      var rankRange = Math.max(maxRank - minRank, 4);
      var yPad = Math.ceil(rankRange * 0.2);
      var yMin = Math.max(1, minRank - yPad);
      var yMax = maxRank + yPad;
      ctx.strokeStyle = '#e2e8f0';
      ctx.lineWidth = 0.5;
      ctx.font = '10px "Noto Sans KR", sans-serif';
      ctx.fillStyle = '#94a3b8';
      var ySteps = 5;
      for (var yi = 0; yi <= ySteps; yi++) {
        var yVal = Math.round(yMin + (yMax - yMin) * yi / ySteps);
        var yPos = chartInnerTop + (chartBottom - chartInnerTop) * (yi / ySteps);
        ctx.beginPath();
        ctx.moveTo(chartLeft, yPos);
        ctx.lineTo(chartRight, yPos);
        ctx.stroke();
        ctx.textAlign = 'right';
        ctx.fillText(yVal + '위', chartLeft - 6, yPos + 4);
      }
      ctx.textAlign = 'left';
      validData.forEach(function (r, i) {
        var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
        ctx.save();
        ctx.font = '9px "Noto Sans KR", sans-serif';
        ctx.fillStyle = '#94a3b8';
        ctx.translate(xPos, chartBottom + 12);
        ctx.rotate(-0.4);
        ctx.fillText((r.checked_at || '').slice(5, 10), 0, 0);
        ctx.restore();
      });
      ctx.beginPath();
      ctx.strokeStyle = '#3b82f6';
      ctx.lineWidth = 2.5;
      ctx.lineJoin = 'round';
      validData.forEach(function (r, i) {
        var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
        var yPos = chartInnerTop + (chartBottom - chartInnerTop) * ((r.rank_position - yMin) / (yMax - yMin));
        if (i === 0) ctx.moveTo(xPos, yPos);else ctx.lineTo(xPos, yPos);
      });
      ctx.stroke();
      ctx.beginPath();
      validData.forEach(function (r, i) {
        var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
        var yPos = chartInnerTop + (chartBottom - chartInnerTop) * ((r.rank_position - yMin) / (yMax - yMin));
        if (i === 0) ctx.moveTo(xPos, yPos);else ctx.lineTo(xPos, yPos);
      });
      ctx.lineTo(chartLeft + (chartRight - chartLeft), chartBottom);
      ctx.lineTo(chartLeft, chartBottom);
      ctx.closePath();
      var areaGrad = ctx.createLinearGradient(0, chartInnerTop, 0, chartBottom);
      areaGrad.addColorStop(0, 'rgba(59, 130, 246, 0.15)');
      areaGrad.addColorStop(1, 'rgba(59, 130, 246, 0.02)');
      ctx.fillStyle = areaGrad;
      ctx.fill();
      validData.forEach(function (r, i) {
        var xPos = chartLeft + (chartRight - chartLeft) * (i / (validData.length - 1));
        var yPos = chartInnerTop + (chartBottom - chartInnerTop) * ((r.rank_position - yMin) / (yMax - yMin));
        ctx.beginPath();
        ctx.arc(xPos, yPos, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.fill();
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.font = 'bold 10px "Noto Sans KR", sans-serif';
        ctx.fillStyle = '#1e40af';
        ctx.textAlign = 'center';
        ctx.fillText(r.rank_position + '위', xPos, yPos - 10);
      });
      ctx.textAlign = 'left';
    } else {
      ctx.font = '13px "Noto Sans KR", sans-serif';
      ctx.fillStyle = '#94a3b8';
      ctx.fillText('차트를 표시하려면 유효한 순위 데이터가 2건 이상 필요합니다.', chartLeft, chartTop + 60);
    }

    // 워터마크
    ctx.font = '10px "Noto Sans KR", sans-serif';
    ctx.fillStyle = '#cbd5e1';
    ctx.textAlign = 'right';
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

;/* ===== js/components/ErrorBoundary.jsx ===== */
/* ErrorBoundary — React 에러 경계 (빈 화면 방지) */
(function () {
  function ErrorBoundary(props) {
    React.Component.call(this, props);
    this.state = {
      hasError: false,
      errorMsg: ''
    };
  }
  ErrorBoundary.prototype = Object.create(React.Component.prototype);
  ErrorBoundary.prototype.constructor = ErrorBoundary;
  ErrorBoundary.getDerivedStateFromError = function (error) {
    return {
      hasError: true,
      errorMsg: String(error && error.message || error || '')
    };
  };
  ErrorBoundary.prototype.componentDidCatch = function (error, info) {
    console.error('[ErrorBoundary]', error, info);
  };
  ErrorBoundary.prototype.render = function () {
    var self = this;
    if (this.state.hasError) {
      return React.createElement('div', {
        style: {
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#fef2f2',
          padding: 20
        }
      }, React.createElement('div', {
        style: {
          background: '#fff',
          borderRadius: 16,
          padding: 40,
          maxWidth: 480,
          width: '100%',
          textAlign: 'center',
          boxShadow: '0 4px 20px rgba(0,0,0,0.08)'
        }
      }, React.createElement('div', {
        style: {
          fontSize: 48,
          marginBottom: 16
        }
      }, '\u26A0'), React.createElement('h2', {
        style: {
          marginBottom: 12,
          color: '#1e293b'
        }
      }, '\uD654\uBA74 \uB85C\uB4DC \uC624\uB958'), React.createElement('p', {
        style: {
          color: '#64748b',
          marginBottom: 20,
          fontSize: 14
        }
      }, this.state.errorMsg), React.createElement('button', {
        onClick: function () {
          window.location.reload();
        },
        style: {
          background: '#6C5CE7',
          color: '#fff',
          border: 'none',
          padding: '12px 28px',
          borderRadius: 8,
          fontSize: 14,
          fontWeight: 600,
          cursor: 'pointer'
        }
      }, '\uC0C8\uB85C\uACE0\uCE68')));
    }
    return this.props.children;
  };
  window.ErrorBoundary = ErrorBoundary;
})();

;/* ===== js/components/SectionErrorBoundary.jsx ===== */
/* SectionErrorBoundary — 섹션별 에러 경계 (해당 섹션만 에러 표시, 나머지 정상 동작) */
(function () {
  function SectionErrorBoundary(props) {
    React.Component.call(this, props);
    this.state = {
      hasError: false,
      errorMsg: ''
    };
    this.handleRetry = this.handleRetry.bind(this);
  }
  SectionErrorBoundary.prototype = Object.create(React.Component.prototype);
  SectionErrorBoundary.prototype.constructor = SectionErrorBoundary;
  SectionErrorBoundary.getDerivedStateFromError = function (error) {
    return {
      hasError: true,
      errorMsg: String(error && error.message || error || '')
    };
  };
  SectionErrorBoundary.prototype.componentDidCatch = function (error, info) {
    var name = this.props.name || '알 수 없는 섹션';
    console.error('[SectionError:' + name + ']', error, info);
  };
  SectionErrorBoundary.prototype.handleRetry = function () {
    this.setState({
      hasError: false,
      errorMsg: ''
    });
  };
  SectionErrorBoundary.prototype.render = function () {
    if (this.state.hasError) {
      var name = this.props.name || '섹션';
      return React.createElement('div', {
        className: 'section',
        style: {
          margin: '12px 0'
        }
      }, React.createElement('div', {
        className: 'container',
        style: {
          background: '#fef2f2',
          border: '1px solid #fecaca',
          borderRadius: 12,
          padding: '24px 20px',
          textAlign: 'center'
        }
      }, React.createElement('div', {
        style: {
          fontSize: 24,
          marginBottom: 8
        }
      }, '\u26A0\uFE0F'), React.createElement('div', {
        style: {
          fontSize: 14,
          fontWeight: 600,
          color: '#991b1b',
          marginBottom: 4
        }
      }, name + ' 로드 중 오류가 발생했습니다'), React.createElement('div', {
        style: {
          fontSize: 12,
          color: '#b91c1c',
          marginBottom: 12,
          opacity: 0.7
        }
      }, this.state.errorMsg), React.createElement('button', {
        onClick: this.handleRetry,
        style: {
          background: '#6C5CE7',
          color: '#fff',
          border: 'none',
          padding: '8px 20px',
          borderRadius: 6,
          fontSize: 13,
          fontWeight: 500,
          cursor: 'pointer',
          marginRight: 8
        }
      }, '\uB2E4\uC2DC \uC2DC\uB3C4')));
    }
    return this.props.children;
  };
  window.SectionErrorBoundary = SectionErrorBoundary;
})();

;/* ===== js/components/ChartCanvas.jsx ===== */
/*
 * ChartCanvas — Chart.js 재사용 래퍼 (광고주 보고서 차트 통일용)
 * 사용: <ChartCanvas type="bar" data={...} options={...} height={220} />
 * - canvas ref에 Chart 인스턴스 생성, 언마운트/데이터변경 시 destroy
 * - Chart 전역 미로드 시 안전 가드(차트 영역만 비움, 앱은 정상)
 */
(function () {
  // 보고서 공통 색상 팔레트 (미리보기 시안과 동일)
  window.CHART_COLORS = {
    IND: '#4f46e5',
    // 인디고(주색)
    PUR: '#9333ea',
    // 보라
    PINK: '#ec4899',
    // 핑크(내 상품 강조)
    OK: '#16a34a',
    // 초록(긍정)
    RED: '#ef4444',
    // 빨강(경고)
    BLUE: '#2563eb',
    // 파랑
    WARN: '#f59e0b',
    // 주황(경쟁)
    GRID: '#eef2f7',
    // 연한 격자/잔여
    SOFT: '#a5b4fc',
    // 연인디고(보조 막대)
    SOFT2: '#c7d2fe' // 더 연한 인디고
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
        try {
          chartRef.current.destroy();
        } catch (e) {}
        chartRef.current = null;
      }
      try {
        chartRef.current = new Chart(el.getContext('2d'), {
          type: props.type,
          data: props.data,
          options: Object.assign({
            responsive: true,
            maintainAspectRatio: false
          }, props.options || {})
        });
      } catch (e) {
        if (window.console) console.warn('[ChartCanvas] render 실패:', e);
      }
      return function () {
        if (chartRef.current) {
          try {
            chartRef.current.destroy();
          } catch (e) {}
          chartRef.current = null;
        }
      };
      // data/options/type 변경 시 재생성
    }, [JSON.stringify(props.data), JSON.stringify(props.options), props.type, height]);
    return React.createElement('div', {
      style: Object.assign({
        position: 'relative',
        height: height,
        width: '100%'
      }, props.style || {})
    }, React.createElement('canvas', {
      ref: canvasRef,
      id: props.canvasId
    }));
  };
})();

;/* ===== js/components/AiFeedbackAllSection.jsx ===== */
/* AiFeedbackAllSection — METAINC AI 통합 피드백 (1회 호출) */
window.AiFeedbackAllSection = function AiFeedbackAllSection(props) {
  var keyword = props.keyword;
  var analysisData = props.analysisData;
  var volumeData = props.volumeData;
  var relatedData = props.relatedData;
  var advertiserReport = props.advertiserReport;
  var _loading = React.useState(false);
  var loading = _loading[0];
  var setLoading = _loading[1];
  var _feedbacks = React.useState(null);
  var feedbacks = _feedbacks[0];
  var setFeedbacks = _feedbacks[1];
  var _fullText = React.useState('');
  var fullText = _fullText[0];
  var setFullText = _fullText[1];
  var _error = React.useState('');
  var error = _error[0];
  var setError = _error[1];
  var _lastKeyword = React.useRef('');
  var _timerRef = React.useRef(null);
  var _expanded = React.useState(true);
  var expanded = _expanded[0];
  var setExpanded = _expanded[1];
  if (!keyword || !analysisData) return null;
  var sectionConfig = [{
    key: 'volume',
    label: '검색량 분석',
    icon: '🔍'
  }, {
    key: 'market',
    label: '시장 규모',
    icon: '💰'
  }, {
    key: 'competition',
    label: '경쟁강도',
    icon: '⚔️'
  }, {
    key: 'related',
    label: '연관 키워드',
    icon: '🔗'
  }, {
    key: 'trend',
    label: '키워드 트렌드',
    icon: '📈'
  }, {
    key: 'golden',
    label: '골든 키워드',
    icon: '🏆'
  }, {
    key: 'competitor',
    label: '경쟁사 비교',
    icon: '🏪'
  }, {
    key: 'sales',
    label: '판매량 추정',
    icon: '📊'
  }, {
    key: 'strategy',
    label: '진입 전략',
    icon: '🎯'
  }, {
    key: 'summary',
    label: 'METAINC 종합 인사이트',
    icon: '💡'
  }];
  var buildSections = function () {
    var sections = {};
    if (volumeData) sections.volume = volumeData;
    if (analysisData.marketRevenue) sections.market = analysisData.marketRevenue;
    if (analysisData.competitionIndex) sections.competition = analysisData.competitionIndex;
    if (relatedData) sections.related = relatedData;
    if (analysisData.keywordTrend) sections.trend = analysisData.keywordTrend;
    if (analysisData.goldenKeyword) sections.golden = analysisData.goldenKeyword;
    if (analysisData.competitorTable) sections.competitor = analysisData.competitorTable;
    if (analysisData.salesEstimation) sections.sales = analysisData.salesEstimation;
    if (advertiserReport || analysisData && analysisData.strategicAnalysis) {
      sections.strategy = {
        advertiserReport: advertiserReport,
        strategicAnalysis: analysisData.strategicAnalysis
      };
    }
    return sections;
  };
  var doFetch = function () {
    var sections = buildSections();
    if (Object.keys(sections).length === 0) {
      setError('분석 데이터가 아직 준비되지 않았습니다.');
      return;
    }
    setLoading(true);
    setError('');
    setFeedbacks(null);
    setFullText('');
    api.post('/ai/feedback-all', {
      keyword: keyword,
      sections: sections
    }).then(function (res) {
      if (res && res.success && res.data) {
        setFeedbacks(res.data.feedbacks);
        setFullText(res.data.full_text || '');
      } else {
        setError(res && res.error || 'AI 피드백 생성 실패');
      }
      setLoading(false);
    }).catch(function (e) {
      setError('AI 피드백 요청 실패: ' + (e.message || '네트워크 오류'));
      setLoading(false);
    });
  };

  /* 키워드가 변경되면 자동 실행 (20초 딜레이 — 모든 분석 완료 대기) */
  React.useEffect(function () {
    if (!keyword || !analysisData) return;
    if (_lastKeyword.current && _lastKeyword.current !== keyword) {
      if (_timerRef.current) {
        clearTimeout(_timerRef.current);
        _timerRef.current = null;
      }
      _lastKeyword.current = '';
      setFeedbacks(null);
      setFullText('');
      setError('');
    }
    if (_lastKeyword.current === keyword) return;
    _lastKeyword.current = keyword;
    _timerRef.current = setTimeout(function () {
      _timerRef.current = null;
      doFetch();
    }, 20000);
  }, [keyword, analysisData]);
  React.useEffect(function () {
    return function () {
      if (_timerRef.current) clearTimeout(_timerRef.current);
    };
  }, []);
  return React.createElement('section', {
    id: 'sec-ai-feedback',
    className: 'section'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    className: 'card',
    style: {
      padding: '20px 22px',
      border: '2px dashed #c7d2fe',
      background: 'linear-gradient(135deg,#eef2ff,#faf5ff)'
    }
  }, /* 헤더 */
  React.createElement('div', {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      gap: 12
    }
  }, React.createElement('div', null, React.createElement('h3', {
    className: 'rt-h3'
  }, React.createElement('span', {
    className: 'rt-hic'
  }, '🤖'), 'METAINC AI 종합 분석 리포트', React.createElement('span', {
    className: 'badge b-ai'
  }, 'AI')), React.createElement('div', {
    className: 'rt-desc'
  }, keyword ? '"' + keyword + '" 키워드를 AI가 전체 데이터를 종합해 작성한 분석' : 'AI가 전체 데이터를 종합해 작성한 분석')), React.createElement('div', {
    style: {
      display: 'flex',
      gap: 8,
      alignItems: 'center',
      flexShrink: 0
    }
  }, feedbacks && React.createElement('button', {
    onClick: function () {
      setExpanded(!expanded);
    },
    style: {
      background: '#f1f5f9',
      border: '1px solid #e2e8f0',
      color: '#475569',
      padding: '6px 14px',
      borderRadius: 8,
      fontSize: 12,
      cursor: 'pointer'
    }
  }, expanded ? '접기' : '펼치기'), !loading && React.createElement('button', {
    onClick: doFetch,
    style: {
      background: 'linear-gradient(135deg, #38bdf8, #0ea5e9)',
      color: '#fff',
      border: 'none',
      padding: '8px 20px',
      borderRadius: 8,
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      boxShadow: '0 4px 12px rgba(14, 165, 233, 0.4)'
    }
  }, feedbacks ? '다시 분석' : '✨ AI 종합 분석'), loading && React.createElement('span', {
    style: {
      fontSize: 13,
      color: '#0ea5e9',
      fontWeight: 500
    }
  }, '⏳ AI 분석 중... (약 20~30초)'))), /* 에러 */
  error && React.createElement('div', {
    style: {
      marginTop: 12,
      padding: '10px 14px',
      background: '#fef2f2',
      border: '1px solid #fecaca',
      borderRadius: 8,
      fontSize: 13,
      color: '#b91c1c'
    }
  }, error), /* 피드백 내용 */
  feedbacks && expanded && React.createElement('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
      marginTop: 18
    }
  }, sectionConfig.map(function (sec) {
    var content = feedbacks[sec.key];
    if (!content) return null;
    var isSummary = sec.key === 'summary';
    return React.createElement('div', {
      key: sec.key,
      style: {
        background: isSummary ? '#fffbeb' : '#f8fafc',
        borderRadius: 12,
        padding: '16px 20px',
        border: isSummary ? '1px solid #fde68a' : '1px solid #e2e8f0'
      }
    }, React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 10
      }
    }, React.createElement('span', {
      style: {
        fontSize: 16
      }
    }, sec.icon), React.createElement('span', {
      style: {
        fontSize: 14,
        fontWeight: 700,
        color: isSummary ? '#b45309' : '#0369a1'
      }
    }, sec.label)), React.createElement('div', {
      style: {
        fontSize: 13,
        lineHeight: 1.75,
        color: '#334155',
        whiteSpace: 'pre-wrap'
      }
    }, content));
  })))));
};

;/* ===== js/components/LoadingSpinner.jsx ===== */
/* LoadingSpinner — 로딩 인디케이터 */
window.LoadingSpinner = function LoadingSpinner({
  text = '분석 중...'
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: 20,
      justifyContent: 'center',
      color: '#64748b',
      fontSize: 14
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "spinner"
  }), text);
};

;/* ===== js/components/EmptyState.jsx ===== */
/* EmptyState — 빈 상태 표시 */
window.EmptyState = function EmptyState({
  icon = '📊',
  text = '데이터가 없습니다'
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "empty-state"
  }, /*#__PURE__*/React.createElement("div", {
    className: "empty-icon"
  }, icon), /*#__PURE__*/React.createElement("p", null, text));
};

;/* ===== js/components/StatCard.jsx ===== */
/* StatCard — 스탯 카드 위젯 */
window.StatCard = function StatCard({
  icon,
  iconColor,
  label,
  value,
  sub
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, icon && /*#__PURE__*/React.createElement("div", {
    className: `stat-icon ${iconColor}`
  }, icon), /*#__PURE__*/React.createElement("div", {
    className: "stat-label"
  }, label), /*#__PURE__*/React.createElement("div", {
    className: "stat-value"
  }, value), sub && /*#__PURE__*/React.createElement("div", {
    className: "stat-sub"
  }, sub));
};

;/* ===== js/components/SearchBar.jsx ===== */
/* SearchBar — 통합 검색바 (업체명 + 키워드 + 상품 URL + HTML 붙여넣기 + 북마클릿) */
window.SearchBar = function SearchBar({
  onSearch,
  loading,
  initialValues
}) {
  const {
    useState,
    useEffect,
    useRef
  } = React;
  const [keyword, setKeyword] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [htmlInput, setHtmlInput] = useState('');
  const [htmlExpanded, setHtmlExpanded] = useState(false);
  const [manualUrl, setManualUrl] = useState(''); // 자동 추출 실패 시 안전망

  /* 북마클릿: 스마트스토어에서 클릭하면 HTML을 클립보드에 복사 */
  const bookmarkletCode = "javascript:(function(){try{var h=document.documentElement.outerHTML;navigator.clipboard.writeText(h).then(function(){alert('\\u2705 HTML '+Math.round(h.length/1024)+'KB \\ubcf5\\uc0ac \\uc644\\ub8cc!\\n\\n\\ub85c\\uc9c1\\ubd84\\uc11d \\ud398\\uc774\\uc9c0\\uc758 HTML \\ubd99\\uc5ec\\ub123\\uae30 \\uce78\\uc5d0 \\ubd99\\uc5ec\\ub123\\uc73c\\uc138\\uc694.');}).catch(function(e){var t=document.createElement('textarea');t.value=h;document.body.appendChild(t);t.select();document.execCommand('copy');document.body.removeChild(t);alert('\\u2705 HTML '+Math.round(h.length/1024)+'KB \\ubcf5\\uc0ac \\uc644\\ub8cc! \\ub85c\\uc9c1\\ubd84\\uc11d\\uc5d0 \\ubd99\\uc5ec\\ub123\\uc73c\\uc138\\uc694.');});}catch(e){alert('\\u274c \\ubcf5\\uc0ac \\uc2e4\\ud328: '+e.message);}})();";

  /* 외부에서 초기값 전달 시 입력 필드 업데이트 (업체 카드 클릭 시 사용) */
  useEffect(function () {
    if (initialValues && typeof initialValues === 'object') {
      if (typeof initialValues.keyword === 'string') setKeyword(initialValues.keyword);
      if (typeof initialValues.companyName === 'string') setCompanyName(initialValues.companyName);
    }
  }, [initialValues]);
  const handleSubmit = e => {
    e.preventDefault();
    // 3가지 필수: 업체명 + 키워드 + HTML. 상품 URL은 HTML에서 자동 추출.
    if (!companyName.trim()) {
      try {
        toast.warn('업체명을 입력해주세요.');
      } catch (e2) {}
      return;
    }
    if (!keyword.trim()) {
      try {
        toast.warn('키워드를 입력해주세요.');
      } catch (e2) {}
      return;
    }
    var html = (htmlInput || '').trim();
    if (html.length < 100) {
      try {
        toast.warn('상품 상세페이지 HTML을 붙여넣어주세요. (Ctrl+U 소스 전체 복사)');
      } catch (e2) {}
      return;
    }
    var url = typeof extractProductUrlFromHtml === 'function' ? extractProductUrlFromHtml(html) : '';
    // 자동 추출 실패 시: 수동 입력한 URL을 안전망으로 사용 (직원이 막히지 않도록)
    if (!url) {
      var mu = (manualUrl || '').trim().split('#')[0];
      if (mu && /naver\.com\/(?:[\w-]+\/)*(?:products|catalog)\/\d+/.test(mu)) {
        url = mu.split('?')[0];
      } else {
        try {
          toast.error('HTML에서 상품 URL을 못 찾았어요. 아래 "상품 URL 직접 입력" 칸에 상품 페이지 주소를 붙여넣어 주세요.');
        } catch (e2) {}
        return;
      }
    }
    onSearch(keyword.trim(), url, companyName.trim(), html);
  };
  const htmlSizeKB = htmlInput ? (new Blob([htmlInput]).size / 1024).toFixed(1) : 0;
  const canSubmit = !!(companyName.trim() && keyword.trim() && (htmlInput || '').trim().length >= 100);
  return /*#__PURE__*/React.createElement("div", {
    className: "search-section"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("form", {
    onSubmit: handleSubmit,
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '10px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '240px 1fr',
      gap: '10px',
      alignItems: 'end'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'block',
      fontSize: 11,
      fontWeight: 600,
      color: '#6b7280',
      marginBottom: 4,
      letterSpacing: '0.02em'
    }
  }, "\uC5C5\uCCB4\uBA85 ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#dc2626'
    }
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "search-input",
    type: "text",
    placeholder: "\uBCF4\uACE0\uC11C \uD45C\uC9C0\uC6A9 (\uD544\uC218)",
    value: companyName,
    onChange: e => setCompanyName(e.target.value),
    style: {
      width: '100%',
      fontSize: 13
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'block',
      fontSize: 11,
      fontWeight: 600,
      color: '#6b7280',
      marginBottom: 4,
      letterSpacing: '0.02em'
    }
  }, "\uD0A4\uC6CC\uB4DC ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#dc2626'
    }
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "search-input",
    type: "text",
    placeholder: "\uBD84\uC11D\uD560 \uD0A4\uC6CC\uB4DC (\uC608: \uBB34\uC120 \uC774\uC5B4\uD3F0)",
    value: keyword,
    onChange: e => setKeyword(e.target.value),
    style: {
      width: '100%'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr auto',
      gap: '10px',
      alignItems: 'end'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'block',
      fontSize: 11,
      fontWeight: 600,
      color: '#6b7280',
      marginBottom: 4,
      letterSpacing: '0.02em'
    }
  }, "HTML \uBD99\uC5EC\uB123\uAE30 ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#dc2626'
    }
  }, "*"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      color: '#94a3b8',
      fontWeight: 400,
      marginLeft: 6
    }
  }, "\uC0C1\uD488 \uC0C1\uC138\uD398\uC774\uC9C0 HTML \u2192 \uC0C1\uD488 URL\xB7\uB9AC\uBDF0\uC218\xB7\uD3C9\uC810\xB7\uCC1C\uC218 \uC790\uB3D9 \uCD94\uCD9C")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("textarea", {
    placeholder: "\uC0C1\uD488 \uC0C1\uC138\uD398\uC774\uC9C0 HTML \uC804\uCCB4\uB97C \uBD99\uC5EC\uB123\uC73C\uC138\uC694 (\uD544\uC218) \u2014 Ctrl+U \uC18C\uC2A4\uBCF4\uAE30 \uD6C4 \uC804\uCCB4 \uBCF5\uC0AC. \uC0C1\uD488 URL\uC740 \uC790\uB3D9 \uC778\uC2DD\uB429\uB2C8\uB2E4.",
    value: htmlInput,
    onChange: e => setHtmlInput(e.target.value),
    style: {
      width: '100%',
      height: htmlExpanded ? 120 : 44,
      padding: '10px 14px',
      border: '2px solid ' + (htmlInput ? '#a7f3d0' : '#e5e7eb'),
      borderRadius: 10,
      fontSize: 12,
      fontFamily: 'inherit',
      outline: 'none',
      background: htmlInput ? '#f0fdf4' : '#f9fafb',
      resize: 'none',
      transition: 'all 0.2s',
      overflow: htmlExpanded ? 'auto' : 'hidden'
    },
    onFocus: () => setHtmlExpanded(true),
    onBlur: () => {
      if (!htmlInput) setHtmlExpanded(false);
    }
  }), htmlInput && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 8,
      right: 8,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      color: '#059669',
      fontWeight: 600,
      background: '#ecfdf5',
      padding: '2px 8px',
      borderRadius: 10
    }
  }, htmlSizeKB, " KB"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => {
      setHtmlInput('');
      setHtmlExpanded(false);
    },
    style: {
      border: 'none',
      background: '#fef2f2',
      color: '#dc2626',
      fontSize: 11,
      padding: '2px 8px',
      borderRadius: 10,
      cursor: 'pointer',
      fontWeight: 600
    }
  }, "\uCD08\uAE30\uD654")))), /*#__PURE__*/React.createElement("button", {
    className: "btn-search",
    type: "submit",
    disabled: loading || !canSubmit,
    style: {
      height: 44,
      marginBottom: 0,
      opacity: loading || !canSubmit ? 0.55 : 1
    },
    title: canSubmit ? '' : '업체명·키워드·HTML 3가지를 모두 입력하세요'
  }, loading ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    className: "spinner",
    style: {
      width: 16,
      height: 16,
      borderWidth: 2
    }
  }), " \uBD84\uC11D \uC911...") : '분석 실행')), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'block',
      fontSize: 11,
      fontWeight: 600,
      color: '#6b7280',
      marginBottom: 4,
      letterSpacing: '0.02em'
    }
  }, "\uC0C1\uD488 URL \uC9C1\uC811 \uC785\uB825", /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      color: '#94a3b8',
      fontWeight: 400,
      marginLeft: 6
    }
  }, "\uC120\uD0DD \u2014 HTML\uC5D0\uC11C URL \uC790\uB3D9 \uC778\uC2DD\uC774 \uC548 \uB420 \uB54C\uB9CC \uC0C1\uD488 \uD398\uC774\uC9C0 \uC8FC\uC18C\uB97C \uBD99\uC5EC\uB123\uC73C\uC138\uC694")), /*#__PURE__*/React.createElement("input", {
    className: "search-input",
    type: "text",
    placeholder: "\uC608: https://smartstore.naver.com/\uC2A4\uD1A0\uC5B4/products/1234567890 (\uBE44\uC6CC\uB450\uBA74 HTML\uC5D0\uC11C \uC790\uB3D9 \uCD94\uCD9C)",
    value: manualUrl,
    onChange: e => setManualUrl(e.target.value),
    style: {
      width: '100%',
      fontSize: 12
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '8px 14px',
      background: '#eff6ff',
      borderRadius: 10,
      border: '1px solid #bfdbfe'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 16
    }
  }, "\uD83D\uDD16"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontWeight: 700,
      color: '#1e40af'
    }
  }, "\u2605 \uAC00\uC7A5 \uC26C\uC6B4 \uBC29\uBC95: \uBD81\uB9C8\uD074\uB9BF \uC0AC\uC6A9"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: '#3730a3',
      marginLeft: 8
    }
  }, "\uC544\uB798 \uBC84\uD2BC\uC744 \uBD81\uB9C8\uD06C\uBC14\uB85C ", /*#__PURE__*/React.createElement("strong", null, "\uB4DC\uB798\uADF8"), " \u2192 \uC2A4\uB9C8\uD2B8\uC2A4\uD1A0\uC5B4\uC5D0\uC11C \uD074\uB9AD \uD55C \uBC88\uC5D0 HTML \uBCF5\uC0AC")), /*#__PURE__*/React.createElement("a", {
    href: bookmarkletCode,
    onClick: e => {
      e.preventDefault();
      alert('이 버튼을 클릭하지 말고, 브라우저 북마크바로 드래그해서 놓으세요!\n\n북마크바가 안 보이면 Chrome에서 ⌘+Shift+B (Mac) / Ctrl+Shift+B (Windows) 로 표시할 수 있습니다.');
    },
    draggable: "true",
    style: {
      display: 'inline-block',
      padding: '6px 14px',
      background: '#1e40af',
      color: '#fff',
      fontWeight: 700,
      fontSize: 12,
      borderRadius: 6,
      textDecoration: 'none',
      cursor: 'grab',
      boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
      whiteSpace: 'nowrap',
      flexShrink: 0
    }
  }, "\uD83D\uDCCE HTML \uBCF5\uC0AC (\uBD81\uB9C8\uD06C\uBC14\uB85C \uB4DC\uB798\uADF8)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      color: '#64748b',
      flexShrink: 0
    }
  }, "\u2190 \uC774 \uD30C\uB780 \uBC84\uD2BC\uC744 \uC704\uCABD \uBD81\uB9C8\uD06C\uBC14\uC5D0 \uB04C\uC5B4\uB2E4 \uB193\uC73C\uC138\uC694")))));
};

;/* ===== js/components/DashboardSummary.jsx ===== */
/* DashboardSummary — 대시보드 요약 카드 (v2) */
window.DashboardSummary = function DashboardSummary({
  products,
  searchResult
}) {
  var useState = React.useState;
  var useEffect = React.useEffect;
  var _s1 = useState(0);
  var analysisCount = _s1[0];
  var setAnalysisCount = _s1[1];
  var _s2 = useState(0);
  var reportCount = _s2[0];
  var setReportCount = _s2[1];
  useEffect(function () {
    api.get('/cd/today-stats').then(function (res) {
      if (res && res.success && res.data) {
        setAnalysisCount(res.data.analysis_count || 0);
        setReportCount(res.data.report_count || 0);
      }
    }).catch(function () {});
  }, []);
  var totalKeywords = products.reduce(function (sum, p) {
    return sum + (p.keywords && p.keywords.length || 0);
  }, 0);
  return React.createElement('div', {
    className: 'section fade-in'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    className: 'card-grid card-grid-4'
  }, React.createElement(StatCard, {
    label: '추적 상품',
    value: products.length,
    sub: '등록된 상품 수'
  }), React.createElement(StatCard, {
    label: '추적 키워드',
    value: totalKeywords,
    sub: '모니터링 중'
  }), React.createElement(StatCard, {
    label: '당일 분석',
    value: analysisCount,
    sub: '수동 분석 횟수'
  }), React.createElement(StatCard, {
    label: '보고서 출력',
    value: reportCount,
    sub: '당일 출력 건수'
  }))));
};

;/* ===== js/components/RankTrackingSection.jsx ===== */
/* RankTrackingSection — 순위 추적 */
window.RankTrackingSection = function RankTrackingSection({
  products,
  refreshProducts,
  searchedKeyword,
  searchedProductUrl,
  cachedProductName,
  relatedKeywords,
  onNavigateToClient,
  canEdit,
  onRankResult
}) {
  const {
    useState,
    useEffect,
    useRef
  } = React;
  const [showAddForm, setShowAddForm] = useState(false);
  const [newUrl, setNewUrl] = useState('');
  const [newKeywords, setNewKeywords] = useState('');
  const [adding, setAdding] = useState(false);
  const [refreshing, setRefreshing] = useState({});
  const [expandedProduct, setExpandedProduct] = useState(null);
  const [expandedKeyword, setExpandedKeyword] = useState(null);
  const [historyData, setHistoryData] = useState({});
  const [historyDays, setHistoryDays] = useState({}); // { keywordId: 7|30|365 } 기간 선택
  const [trackedSearch, setTrackedSearch] = useState(''); // 업체/상품 검색
  const [trackedSort, setTrackedSort] = useState('company'); // company|rank|checked
  const lastAutoRegistered = useRef('');
  const productsRef = useRef(products);
  productsRef.current = products;

  // 1회성 순위 조회 결과 (DB 저장 안 함)
  const [tempRankResult, setTempRankResult] = useState(null);
  const [tempRankLoading, setTempRankLoading] = useState(false);
  const lastTempCheckKey = useRef('');

  // 키워드별 노출 분석
  const [exposureResult, setExposureResult] = useState(null);
  const [exposureLoading, setExposureLoading] = useState(false);
  const lastExposureKey = useRef('');

  // 검색 컨텍스트(광고주)가 바뀌면 캐시 전체 초기화
  useEffect(function () {
    setHistoryData({});
    setExpandedProduct(null);
    setTempRankResult(null);
    setExposureResult(null);
    lastTempCheckKey.current = '';
    lastExposureKey.current = '';
  }, [searchedProductUrl, searchedKeyword]);

  // 검색 시 1회성 순위 조회 (DB 미저장)
  useEffect(function () {
    if (!searchedKeyword || !searchedProductUrl) {
      setTempRankResult(null);
      return;
    }
    var key = searchedProductUrl + '::' + searchedKeyword;
    if (lastTempCheckKey.current === key) return;
    lastTempCheckKey.current = key;
    setTempRankLoading(true);
    setTempRankResult(null);
    api.post('/rank/check', {
      keyword: searchedKeyword,
      product_url: searchedProductUrl
    }).then(function (res) {
      if (res && res.success && res.data) {
        setTempRankResult(res.data);
        if (onRankResult) onRankResult(res.data);
      } else if (res && !res.success && res.detail) {
        toast.error(res.detail);
      }
      setTempRankLoading(false);
    }).catch(function () {
      setTempRankLoading(false);
    });
  }, [searchedKeyword, searchedProductUrl, canEdit]);

  // 키워드별 노출 분석 (상품명 기반)
  // cachedProductName이 도착한 후에만 호출 (타이밍 버그 v5.4.16 수정)
  useEffect(function () {
    if (!searchedProductUrl || !searchedKeyword) {
      setExposureResult(null);
      return;
    }
    // cachedProductName이 아직 없으면 대기 (나중에 prop이 채워지면 재실행)
    if (!cachedProductName) return;
    var _extraKws = (relatedKeywords || []).filter(Boolean);
    var key = 'exposure::' + searchedProductUrl + '::' + cachedProductName + '::' + _extraKws.length;
    if (lastExposureKey.current === key) return;
    lastExposureKey.current = key;
    setExposureLoading(true);
    setExposureResult(null);
    api.post('/rank/keyword-exposure', {
      product_url: searchedProductUrl,
      keyword: searchedKeyword,
      product_name: cachedProductName,
      extra_keywords: _extraKws
    }).then(function (res) {
      if (res && res.success && res.data) {
        setExposureResult(res.data);
      } else if (res && !res.success) {
        toast.warn('키워드 노출 분석: ' + (res.detail || '분석에 실패했습니다'));
      }
      setExposureLoading(false);
    }).catch(function () {
      toast.error('키워드 노출 분석 요청 실패');
      setExposureLoading(false);
    });
  }, [searchedProductUrl, searchedKeyword, cachedProductName, relatedKeywords]);

  // 분석 중인 상품이 추적 등록돼 있으면 30일 순위 추이 차트용 이력을 미리 로드
  useEffect(function () {
    if (!searchedProductUrl || !products) return;
    var tp = products.find(function (p) {
      return p.product_url === searchedProductUrl;
    });
    if (!tp) return;
    var kw = (tp.keywords || []).find(function (k) {
      return k.latest_rank;
    }) || (tp.keywords || [])[0];
    if (kw && kw.id) loadHistory(kw.id);
  }, [searchedProductUrl, products]);

  // 자동 등록 + 자동 순위체크 제거 — 수동 버튼으로만 실행 (서버 부하 방지)
  // 기존 DB 데이터(스케줄러 수집분)만 표시, 필요시 사용자가 직접 새로고침

  const handleAdd = async () => {
    if (!newUrl || !newKeywords) return;
    setAdding(true);
    try {
      const kws = newKeywords.split(',').map(k => k.trim()).filter(Boolean);
      await api.post('/products/track', {
        product_url: newUrl,
        keywords: kws
      });
      setNewUrl('');
      setNewKeywords('');
      setShowAddForm(false);
      refreshProducts();
    } catch (e) {
      toast.error('등록 실패: ' + (e.message || '네트워크 오류'));
    }
    setAdding(false);
  };
  const handleRefresh = async productId => {
    setRefreshing(prev => ({
      ...prev,
      [productId]: true
    }));
    try {
      await api.post(`/rank/refresh/${productId}`);
      setTimeout(() => {
        refreshProducts();
        setRefreshing(prev => ({
          ...prev,
          [productId]: false
        }));
      }, 5000);
    } catch (e) {
      toast.error('순위 체크 실패: ' + (e.message || '네트워크 오류'));
      setRefreshing(prev => ({
        ...prev,
        [productId]: false
      }));
    }
  };
  const handleDelete = async productId => {
    if (!confirm('이 상품을 삭제하시겠습니까?')) return;
    try {
      await api.del(`/products/${productId}`);
      refreshProducts();
    } catch (e) {
      toast.error('삭제 실패: ' + (e.message || '네트워크 오류'));
    }
  };
  const loadHistory = async (keywordId, days) => {
    days = days || 30;
    var cacheKey = keywordId + ':' + days;
    if (historyData[cacheKey]) return;
    try {
      const res = await api.get(`/rank/history/${keywordId}?days=${days}`);
      if (res.success) setHistoryData(prev => {
        var n = Object.assign({}, prev);
        n[cacheKey] = res.data;
        return n;
      });
    } catch (e) {
      toast.error('순위 이력 조회 실패');
    }
  };
  var _periodLabel = {
    7: '최근 7일',
    30: '최근 30일',
    365: '전체기간'
  };

  // 키워드 순위 추이 라인차트 (펼침 행) — 기간 선택(7/30/전체) + 이미지 저장
  //   meta: { storeName, storeUrl } — 이미지 헤더/파일명용 (선택)
  var renderRankHistoryChart = function (keywordId, keywordLabel, meta) {
    var days = historyDays[keywordId] || 30;
    var cacheKey = keywordId + ':' + days;
    var rows = historyData[cacheKey];
    var setPeriod = function (d) {
      setHistoryDays(function (prev) {
        var n = Object.assign({}, prev);
        n[keywordId] = d;
        return n;
      });
      loadHistory(keywordId, d);
    };
    var canvasId = 'rankchart-' + keywordId;
    var periodBtns = React.createElement('div', {
      style: {
        display: 'flex',
        gap: 6,
        alignItems: 'center',
        marginBottom: 8,
        flexWrap: 'wrap'
      }
    }, [7, 30, 365].map(function (d) {
      var on = days === d;
      return React.createElement('button', {
        key: d,
        onClick: function (e) {
          e.stopPropagation();
          setPeriod(d);
        },
        style: {
          fontSize: 11,
          fontWeight: 700,
          padding: '3px 10px',
          borderRadius: 14,
          cursor: 'pointer',
          border: '1px solid ' + (on ? '#4f46e5' : '#e2e8f0'),
          background: on ? '#4f46e5' : '#fff',
          color: on ? '#fff' : '#475569'
        }
      }, _periodLabel[d]);
    }), React.createElement('button', {
      onClick: function (e) {
        e.stopPropagation();
        window.exportRankHistoryImage({
          rows: historyData[cacheKey] || [],
          storeName: meta && meta.storeName || '',
          keyword: keywordLabel,
          storeUrl: meta && meta.storeUrl || '',
          days: days === 365 ? 0 : days
        });
      },
      style: {
        marginLeft: 'auto',
        fontSize: 11,
        fontWeight: 700,
        padding: '3px 10px',
        borderRadius: 14,
        cursor: 'pointer',
        border: '1px solid #16a34a',
        background: '#f0fdf4',
        color: '#16a34a'
      }
    }, '📸 이미지 저장'));
    if (!rows) {
      return React.createElement('div', {
        style: {
          padding: '12px 16px'
        }
      }, periodBtns, React.createElement('div', {
        style: {
          padding: '8px',
          textAlign: 'center',
          fontSize: 12,
          color: '#94a3b8'
        }
      }, '순위 이력 불러오는 중...'));
    }
    if (rows.length < 2) {
      return React.createElement('div', {
        style: {
          padding: '12px 16px'
        }
      }, periodBtns, React.createElement('div', {
        style: {
          padding: '8px',
          textAlign: 'center',
          fontSize: 12,
          color: '#94a3b8'
        }
      }, _periodLabel[days] + ' 추이는 2회 이상의 순위 기록이 필요합니다. (현재 ' + rows.length + '회)'));
    }
    var labels = rows.map(function (r) {
      var d = new Date((r.checked_at || '').replace(' ', 'T'));
      return isNaN(d) ? '' : d.getMonth() + 1 + '/' + d.getDate();
    });
    var data = rows.map(function (r) {
      return r.rank_position && r.rank_position > 0 ? r.rank_position : null;
    });
    var valid = data.filter(function (v) {
      return v != null;
    });
    var maxRank = valid.length ? Math.max.apply(null, valid) : 40;
    var C = window.CHART_COLORS || {
      OK: '#16a34a'
    };
    return React.createElement('div', {
      style: {
        padding: '12px 16px 4px'
      }
    }, periodBtns, React.createElement('div', {
      style: {
        fontSize: 12,
        fontWeight: 700,
        color: '#0f172a',
        marginBottom: 8
      }
    }, '"' + keywordLabel + '" ' + _periodLabel[days] + ' 순위 추이'), React.createElement(window.ChartCanvas, {
      canvasId: canvasId,
      type: 'line',
      height: 180,
      data: {
        labels: labels,
        datasets: [{
          label: '순위',
          data: data,
          borderColor: C.OK,
          backgroundColor: 'rgba(22,163,74,.12)',
          fill: true,
          tension: 0.35,
          pointRadius: 2.5,
          borderWidth: 2.5,
          spanGaps: true
        }]
      },
      options: {
        plugins: {
          legend: {
            display: false
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.parsed.y != null ? ctx.parsed.y + '위' : '400위 밖';
              }
            }
          }
        },
        scales: {
          y: {
            reverse: true,
            suggestedMin: 1,
            suggestedMax: Math.max(16, maxRank + 2),
            title: {
              display: true,
              text: '순위 (낮을수록 상위 ↑)'
            },
            ticks: {
              precision: 0
            }
          }
        }
      }
    }), React.createElement('div', {
      style: {
        fontSize: 10,
        color: '#94a3b8',
        marginTop: 4
      }
    }, '※ 선이 위로 갈수록 상위 노출. 끊긴 구간은 400위 밖입니다.'));
  };

  // 1회성 순위 결과 블록 카드 렌더링
  var renderTempRankCard = function () {
    if (!searchedProductUrl || !searchedKeyword) return null;

    // 로딩 중
    if (tempRankLoading) {
      return React.createElement('div', {
        className: 'card fade-in',
        style: {
          textAlign: 'center',
          padding: '24px 16px',
          color: '#64748b'
        }
      }, React.createElement('div', {
        style: {
          fontSize: 14
        }
      }, '순위 조회 중...'));
    }

    // 결과 없음
    if (!tempRankResult) return null;
    var d = tempRankResult;
    var pInfo = d.product_info || {};
    var rank = d.rank_position;
    var rankColor = rank && rank > 0 ? rank <= 10 ? '#059669' : rank <= 40 ? '#d97706' : '#dc2626' : '#94a3b8';
    var rankLabel = rank && rank > 0 ? rank <= 10 ? '상위권' : rank <= 40 ? '중위권' : '하위권' : '미노출';
    var pageNum = rank && rank > 0 ? Math.ceil(rank / 40) : 0;
    return React.createElement('div', {
      className: 'fade-in',
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 12
      }
    },
    // 상품 정보 바
    React.createElement('div', {
      className: 'card',
      style: {
        display: 'flex',
        gap: 12,
        alignItems: 'center',
        padding: '12px 16px'
      }
    }, pInfo.image_url && React.createElement('img', {
      src: pInfo.image_url,
      alt: '',
      style: {
        width: 44,
        height: 44,
        borderRadius: 8,
        objectFit: 'cover',
        flexShrink: 0
      }
    }), React.createElement('div', {
      style: {
        minWidth: 0,
        flex: 1
      }
    }, React.createElement('div', {
      style: {
        fontWeight: 600,
        fontSize: 13,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, pInfo.product_name || '상품 정보'), React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, (pInfo.store_name || '-') + (pInfo.price > 0 ? '  ·  ' + fmt(pInfo.price) + '원' : ''))), React.createElement('span', {
      style: {
        background: '#eff6ff',
        color: '#3b82f6',
        fontSize: 10,
        padding: '3px 8px',
        borderRadius: 6,
        flexShrink: 0,
        fontWeight: 500
      }
    }, '실시간 조회')),
    // 핵심 지표 블록 카드 (3열 그리드 — 아이콘 없음)
    React.createElement('div', {
      className: 'card-grid card-grid-3'
    }, React.createElement('div', {
      className: 'card',
      style: {
        padding: '16px 20px'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b',
        marginBottom: 6
      }
    }, '검색 키워드'), React.createElement('div', {
      style: {
        fontSize: 20,
        fontWeight: 800,
        color: '#0f172a'
      }
    }, d.keyword), React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#94a3b8',
        marginTop: 4
      }
    }, '분석 대상 키워드')), React.createElement('div', {
      className: 'card',
      style: {
        padding: '16px 20px'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b',
        marginBottom: 6
      }
    }, '현재 순위'), React.createElement('div', {
      style: {
        fontSize: 20,
        fontWeight: 800,
        color: rankColor
      }
    }, rank && rank > 0 ? rank + '위' : '미노출'), React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#94a3b8',
        marginTop: 4
      }
    }, rankLabel)), React.createElement('div', {
      className: 'card',
      style: {
        padding: '16px 20px'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b',
        marginBottom: 6
      }
    }, '노출 페이지'), React.createElement('div', {
      style: {
        fontSize: 20,
        fontWeight: 800,
        color: '#0f172a'
      }
    }, pageNum > 0 ? pageNum + 'P' : '-'), React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#94a3b8',
        marginTop: 4
      }
    }, pageNum > 0 ? pageNum === 1 ? '1페이지 노출' : pageNum + '페이지 노출' : '검색 결과 없음'))),
    // 안내 문구
    React.createElement('div', {
      style: {
        padding: '8px 12px',
        background: '#f8fafc',
        borderRadius: 6,
        fontSize: 11,
        color: '#94a3b8',
        lineHeight: '1.5'
      }
    }, '이 결과는 1회성 조회입니다. 지속적인 순위 추적은 관리자에게 상품 등록을 요청하세요.'));
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "section",
    id: "sec-rank"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDCCD"), "\uD0A4\uC6CC\uB4DC\uBCC4 \uB178\uCD9C \uC21C\uC704", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uC2E4\uCE21")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uC0C1\uD488\uBA85\uC5D0\uC11C \uCD94\uCD9C\uD55C \uD0A4\uC6CC\uB4DC\uBCC4\uB85C \uB124\uC774\uBC84 \uC1FC\uD551 \uAC80\uC0C9 \uC21C\uC704\uB97C \uC870\uD68C\uD55C \uACB0\uACFC (\uAC80\uC0C9 \uBC94\uC704: \uC0C1\uC704 400\uAC1C \uC0C1\uD488)")), canEdit !== false && /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary btn-sm",
    onClick: () => setShowAddForm(!showAddForm)
  }, showAddForm ? '취소' : '+ 상품 등록')), showAddForm && /*#__PURE__*/React.createElement("div", {
    className: "card fade-in",
    style: {
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "form-label"
  }, "\uC0C1\uD488 URL"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "https://smartstore.naver.com/\uC2A4\uD1A0\uC5B4\uBA85/products/12345",
    value: newUrl,
    onChange: e => setNewUrl(e.target.value)
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      marginTop: 4
    }
  }, "\uB124\uC774\uBC84 \uC2A4\uB9C8\uD2B8\uC2A4\uD1A0\uC5B4 \uC0C1\uD488 \uD398\uC774\uC9C0 URL\uC744 \uC785\uB825\uD558\uC138\uC694")), /*#__PURE__*/React.createElement("div", {
    className: "form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "form-label"
  }, "\uCD94\uC801 \uD0A4\uC6CC\uB4DC (\uC27C\uD45C\uB85C \uAD6C\uBD84)"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "\uC608: \uC2A4\uB9C8\uD2B8\uC6CC\uCE58, \uBE14\uB8E8\uD22C\uC2A4 \uC774\uC5B4\uD3F0",
    value: newKeywords,
    onChange: e => setNewKeywords(e.target.value)
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      marginTop: 4
    }
  }, "\uC5EC\uB7EC \uD0A4\uC6CC\uB4DC\uB294 \uC27C\uD45C(,)\uB85C \uAD6C\uBD84\uD574\uC11C \uC785\uB825\uD558\uC138\uC694 (\uCD5C\uB300 10\uAC1C)")), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: handleAdd,
    disabled: adding || !newUrl.trim() || !newKeywords.trim()
  }, adding ? '등록 중...' : '상품 등록')), exposureLoading && /*#__PURE__*/React.createElement("div", {
    className: "card fade-in",
    style: {
      textAlign: 'center',
      padding: '24px 16px',
      color: '#64748b',
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14
    }
  }, "\uD0A4\uC6CC\uB4DC\uBCC4 \uB178\uCD9C \uC21C\uC704 \uBD84\uC11D \uC911..."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#94a3b8',
      marginTop: 4
    }
  }, "\uC0C1\uD488\uBA85\uC5D0\uC11C \uD0A4\uC6CC\uB4DC\uB97C \uCD94\uCD9C\uD558\uC5EC \uAC01\uAC01 \uC21C\uC704\uB97C \uC870\uD68C\uD558\uACE0 \uC788\uC2B5\uB2C8\uB2E4")), exposureResult && !exposureLoading && function () {
    var exposed = exposureResult.results.filter(function (r) {
      return r.rank != null;
    });
    var unexposed = exposureResult.results.filter(function (r) {
      return r.rank == null;
    });
    var exposureRate = exposureResult.total_keywords > 0 ? Math.round(exposureResult.exposed_count / exposureResult.total_keywords * 100) : 0;
    return /*#__PURE__*/React.createElement("div", {
      className: "fade-in",
      style: {
        marginTop: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'flex-end',
        gap: 8,
        marginBottom: 12
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "ps ps-g"
    }, "\uB178\uCD9C ", exposureResult.exposed_count, "\uAC1C"), /*#__PURE__*/React.createElement("span", {
      className: "ps ps-r"
    }, "400\uC704 \uBC16 ", unexposed.length, "\uAC1C"), /*#__PURE__*/React.createElement("span", {
      className: "ps ps-n"
    }, "\uC804\uCCB4 ", exposureResult.total_keywords, "\uAC1C")), /*#__PURE__*/React.createElement("div", {
      className: "grid3",
      style: {
        marginBottom: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "ratecard"
    }, /*#__PURE__*/React.createElement("div", {
      className: "v",
      style: {
        color: 'var(--ok)'
      }
    }, exposureResult.exposed_count), /*#__PURE__*/React.createElement("div", {
      className: "k"
    }, "\uB178\uCD9C \uD0A4\uC6CC\uB4DC")), /*#__PURE__*/React.createElement("div", {
      className: "ratecard"
    }, /*#__PURE__*/React.createElement("div", {
      className: "v",
      style: {
        color: 'var(--red)'
      }
    }, unexposed.length), /*#__PURE__*/React.createElement("div", {
      className: "k"
    }, "400\uC704 \uBC16 \uD0A4\uC6CC\uB4DC")), /*#__PURE__*/React.createElement("div", {
      className: "ratecard"
    }, /*#__PURE__*/React.createElement("div", {
      className: "v",
      style: {
        color: 'var(--pur)'
      }
    }, exposureRate, "%"), /*#__PURE__*/React.createElement("div", {
      className: "k"
    }, "\uB178\uCD9C\uB960"))), exposureResult.recommended && exposureResult.recommended.length > 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        background: '#f5f3ff',
        border: '1px solid #ddd6fe',
        borderRadius: 12,
        padding: '14px 16px',
        marginBottom: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 800,
        color: '#6d28d9',
        marginBottom: 4,
        display: 'flex',
        alignItems: 'center',
        gap: 6
      }
    }, "\uD83D\uDCA1 \uB178\uCD9C \uC911\uC778 \uCD94\uCC9C \uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: '#64748b',
        marginBottom: 10,
        lineHeight: 1.5
      }
    }, "\uAC80\uC0C9 \uD0A4\uC6CC\uB4DC\uAC00 \uC0C1\uC704 400\uC704 \uBC16\uC774\uC5B4\uB3C4, \uC544\uB798 \uD0A4\uC6CC\uB4DC\uB85C\uB294 \uC9C0\uAE08 \uB178\uCD9C \uC911\uC785\uB2C8\uB2E4 \u2014 \uC0C1\uD488\uBA85\xB7\uD0DC\uADF8\xB7\uAD11\uACE0\uC5D0 \uD65C\uC6A9\uD574 \uB178\uCD9C\uC744 \uD655\uBCF4\uD558\uC138\uC694."), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexWrap: 'wrap',
        gap: 8
      }
    }, exposureResult.recommended.map(function (r, idx) {
      return /*#__PURE__*/React.createElement("span", {
        key: idx,
        style: {
          background: '#fff',
          border: '1px solid #ddd6fe',
          borderRadius: 999,
          padding: '6px 12px',
          fontSize: 13,
          fontWeight: 600,
          color: '#1e293b',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6
        }
      }, r.keyword, /*#__PURE__*/React.createElement("span", {
        style: {
          fontWeight: 800,
          color: r.rank <= 10 ? '#16a34a' : '#ca8a04'
        }
      }, r.rank, "\uC704"));
    }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 800,
        color: '#10b981',
        margin: '6px 0 8px',
        display: 'flex',
        alignItems: 'center',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("span", null, "\u25CF"), " \uB178\uCD9C \uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexWrap: 'wrap',
        gap: 8
      }
    }, exposed.map(function (r, idx) {
      return /*#__PURE__*/React.createElement("span", {
        key: idx,
        className: r.rank <= 10 ? 'kwchip' : 'kwchip warn'
      }, r.keyword, " ", /*#__PURE__*/React.createElement("span", {
        className: "rk"
      }, r.rank, "\uC704"));
    }), exposed.length === 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: '#94a3b8'
      }
    }, "\uB178\uCD9C\uB41C \uD0A4\uC6CC\uB4DC\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4")), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 800,
        color: '#ef4444',
        margin: '16px 0 8px',
        display: 'flex',
        alignItems: 'center',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("span", null, "\u25CF"), " 400\uC704 \uBC16 \uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexWrap: 'wrap',
        gap: 8
      }
    }, unexposed.map(function (r, idx) {
      return /*#__PURE__*/React.createElement("span", {
        key: idx,
        className: "kwchip off"
      }, r.keyword);
    }), unexposed.length === 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: '#94a3b8'
      }
    }, "\uBAA8\uB4E0 \uD0A4\uC6CC\uB4DC\uC5D0 \uB178\uCD9C \uC911\uC785\uB2C8\uB2E4"))), function () {
      var tp = (products || []).find(function (p) {
        return p.product_url === searchedProductUrl;
      });
      var kw = tp && ((tp.keywords || []).find(function (k) {
        return k.latest_rank;
      }) || (tp.keywords || [])[0]);
      var topExposed = exposed.length ? exposed.slice().sort(function (a, b) {
        return a.rank - b.rank;
      })[0] : null;
      var chartTitle = kw ? kw.keyword : topExposed ? topExposed.keyword : '';
      return /*#__PURE__*/React.createElement("div", {
        className: "sub-card",
        style: {
          marginTop: 16
        }
      }, /*#__PURE__*/React.createElement("div", {
        className: "st"
      }, "\uD83D\uDCC9 ", chartTitle ? "'" + chartTitle + "' " : '', "30\uC77C \uC21C\uC704 \uCD94\uC774 ", /*#__PURE__*/React.createElement("span", {
        className: "badge b-est",
        style: {
          marginLeft: 4
        }
      }, "\uC2E0\uADDC \uCC28\uD2B8")), kw && kw.id ? renderRankHistoryChart(kw.id, kw.keyword, tp ? {
        storeName: tp.store_name,
        storeUrl: tp.product_url
      } : {}) : /*#__PURE__*/React.createElement("div", {
        style: {
          fontSize: 12,
          color: '#94a3b8',
          padding: '6px 2px',
          lineHeight: 1.7
        }
      }, "\uC9C0\uC18D\uC801\uC778 30\uC77C \uC21C\uC704 \uCD94\uC774\uB294 ", /*#__PURE__*/React.createElement("b", {
        style: {
          color: '#475569'
        }
      }, "\uAD00\uB9AC\uC790\uC5D0 \uC0C1\uD488 \uB4F1\uB85D(\uCD94\uC801 \uC694\uCCAD)"), " \uD6C4 \uB9E4\uC77C \uC2A4\uB0C5\uC0F7\uC73C\uB85C \uC790\uB3D9 \uAE30\uB85D\uB429\uB2C8\uB2E4. \uB4F1\uB85D\uB418\uBA74 \uC774 \uC790\uB9AC\uC5D0 \uCD94\uC774 \uADF8\uB798\uD504\uAC00 \uD45C\uC2DC\uB429\uB2C8\uB2E4."));
    }());
  }(), function () {
    // viewer는 등록된 상품 목록 표시 안 함
    if (canEdit === false) {
      // 1회성 결과도 없고 로딩도 아닌 경우에만 빈 상태 표시
      if (!tempRankResult && !tempRankLoading && searchedProductUrl) return null;
      if (!searchedProductUrl) return null;
      return null;
    }
    var filtered = searchedProductUrl ? products.filter(function (p) {
      return p.product_url === searchedProductUrl;
    }) : products;
    if (filtered.length === 0) return /*#__PURE__*/React.createElement(EmptyState, {
      icon: "\uD83D\uDCE6",
      text: searchedProductUrl ? "해당 상품의 순위 추적 데이터가 아직 없습니다. 상품이 등록되면 자동으로 표시됩니다." : "추적 중인 상품이 없습니다. 상품을 등록해보세요."
    });

    /* ===== 특정 업체 분석 결과 → 기존 가로 리스트형 ===== */
    if (searchedProductUrl) {
      return /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          flexDirection: 'column',
          gap: 12
        }
      }, filtered.map(function (p) {
        return React.createElement('div', {
          className: 'card fade-in',
          key: p.id
        }, React.createElement('div', {
          style: {
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 12,
            flexWrap: 'wrap'
          }
        }, React.createElement('div', {
          style: {
            display: 'flex',
            gap: 12,
            flex: 1,
            minWidth: 0,
            cursor: onNavigateToClient ? 'pointer' : 'default'
          },
          onClick: onNavigateToClient ? function () {
            onNavigateToClient(p.store_name || '', p.product_url || '');
          } : undefined,
          title: onNavigateToClient ? '클릭하여 업체관리에서 상세 보기' : ''
        }, p.image_url && React.createElement('img', {
          src: p.image_url,
          alt: '',
          style: {
            width: 56,
            height: 56,
            borderRadius: 8,
            objectFit: 'cover',
            flexShrink: 0
          }
        }), React.createElement('div', {
          style: {
            minWidth: 0
          }
        }, React.createElement('div', {
          style: {
            fontWeight: 600,
            fontSize: 14,
            marginBottom: 2,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            color: onNavigateToClient ? '#4f46e5' : 'inherit'
          }
        }, p.product_name || '상품', onNavigateToClient && React.createElement('span', {
          style: {
            fontSize: 11,
            color: '#818cf8',
            marginLeft: 6,
            fontWeight: 400
          }
        }, '→ 업체관리')), React.createElement('div', {
          style: {
            fontSize: 12,
            color: '#64748b'
          }
        }, p.store_name || '-'), p.price > 0 && React.createElement('div', {
          style: {
            fontSize: 13,
            fontWeight: 600,
            color: '#0f172a',
            marginTop: 2
          }
        }, fmt(p.price) + '원'))), canEdit !== false && React.createElement('div', {
          style: {
            display: 'flex',
            gap: 6,
            flexShrink: 0
          }
        }, React.createElement('button', {
          className: 'btn btn-secondary btn-sm',
          onClick: function () {
            handleRefresh(p.id);
          },
          disabled: refreshing[p.id]
        }, refreshing[p.id] ? '체크 중' : '↻ 순위체크'), React.createElement('button', {
          className: 'btn btn-danger btn-sm',
          onClick: function () {
            handleDelete(p.id);
          }
        }, '삭제'))), (p.keywords || []).length > 0 && React.createElement('div', {
          className: 'table-wrap',
          style: {
            marginTop: 14
          }
        }, React.createElement('table', null, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', null, '키워드'), React.createElement('th', null, '현재 순위'), React.createElement('th', null, '페이지'), React.createElement('th', null, '최근 체크'))), React.createElement('tbody', null, p.keywords.map(function (k) {
          var isOpen = expandedKeyword === k.id;
          var rowEl = React.createElement('tr', {
            key: k.id,
            style: {
              cursor: 'pointer',
              background: isOpen ? '#f8fafc' : undefined
            },
            onClick: function () {
              var next = isOpen ? null : k.id;
              setExpandedKeyword(next);
              if (next) loadHistory(k.id);
            }
          }, React.createElement('td', {
            style: {
              fontWeight: 500
            }
          }, React.createElement('span', {
            style: {
              color: '#cbd5e1',
              marginRight: 6,
              fontSize: 11
            }
          }, isOpen ? '▼' : '▶'), k.keyword), React.createElement('td', null, k.latest_rank ? React.createElement('span', {
            style: {
              fontWeight: 700,
              color: k.latest_rank <= 10 ? '#059669' : k.latest_rank <= 40 ? '#d97706' : '#dc2626'
            }
          }, k.latest_rank + '위') : React.createElement('span', {
            className: 'badge badge-gray'
          }, '400위 밖')), React.createElement('td', null, k.latest_rank ? Math.ceil(k.latest_rank / 40) + 'P' : '-'), React.createElement('td', {
            style: {
              fontSize: 12,
              color: '#94a3b8'
            }
          }, k.last_checked ? new Date(k.last_checked).toLocaleString('ko') : '-'));
          if (!isOpen) return rowEl;
          var chartRow = React.createElement('tr', {
            key: k.id + '-chart'
          }, React.createElement('td', {
            colSpan: 4,
            style: {
              padding: 0,
              background: '#f8fafc'
            }
          }, renderRankHistoryChart(k.id, k.keyword, {
            storeName: p.store_name,
            storeUrl: p.product_url
          })));
          return [rowEl, chartRow];
        })))));
      }));
    }

    /* ===== 전체 상품 → 스캔형 표 (검색·정렬·업체명 강조 + 이력 펼침) ===== */
    var _q = (trackedSearch || '').trim().toLowerCase();
    var _bestRank = function (p) {
      var rs = (p.keywords || []).map(function (k) {
        return k.latest_rank;
      }).filter(function (r) {
        return r && r > 0;
      });
      return rs.length ? Math.min.apply(null, rs) : null;
    };
    var _lastChecked = function (p) {
      var ts = (p.keywords || []).map(function (k) {
        return k.last_checked;
      }).filter(Boolean).sort();
      return ts.length ? ts[ts.length - 1] : null;
    };
    var _exposedCount = function (p) {
      return (p.keywords || []).filter(function (k) {
        return k.latest_rank && k.latest_rank > 0;
      }).length;
    };
    var displayed = filtered.filter(function (p) {
      if (!_q) return true;
      return (p.store_name || '').toLowerCase().indexOf(_q) >= 0 || (p.product_name || '').toLowerCase().indexOf(_q) >= 0;
    }).slice().sort(function (a, b) {
      if (trackedSort === 'rank') {
        var ra = _bestRank(a),
          rb = _bestRank(b);
        return (ra == null ? 99999 : ra) - (rb == null ? 99999 : rb);
      }
      if (trackedSort === 'checked') {
        return String(_lastChecked(b) || '').localeCompare(String(_lastChecked(a) || ''));
      }
      return (a.store_name || '').localeCompare(b.store_name || '', 'ko');
    });
    var _thS = {
      textAlign: 'left',
      padding: '9px 12px',
      borderBottom: '2px solid #e2e8f0',
      color: '#64748b',
      fontWeight: 700,
      whiteSpace: 'nowrap',
      fontSize: 12,
      background: '#f8fafc'
    };
    var _thC = Object.assign({}, _thS, {
      textAlign: 'center'
    });
    var _rankBadge = function (rk) {
      if (!rk) return React.createElement('span', {
        style: {
          fontSize: 12,
          color: '#94a3b8',
          fontWeight: 600
        }
      }, '400위 밖');
      var c = rk <= 10 ? '#059669' : rk <= 40 ? '#d97706' : '#dc2626';
      return React.createElement('span', {
        style: {
          fontWeight: 800,
          color: c
        }
      }, rk + '위', React.createElement('span', {
        style: {
          fontSize: 10,
          color: '#94a3b8',
          fontWeight: 600,
          marginLeft: 4
        }
      }, Math.ceil(rk / 40) + 'P'));
    };
    return React.createElement('div', null, React.createElement('div', {
      style: {
        display: 'flex',
        gap: 8,
        flexWrap: 'wrap',
        alignItems: 'center',
        margin: '4px 0 12px'
      }
    }, React.createElement('input', {
      className: 'form-input',
      placeholder: '🔎 업체명·상품명 검색',
      value: trackedSearch,
      onChange: function (e) {
        setTrackedSearch(e.target.value);
      },
      style: {
        maxWidth: 280,
        fontSize: 13
      }
    }), React.createElement('select', {
      className: 'form-input',
      value: trackedSort,
      onChange: function (e) {
        setTrackedSort(e.target.value);
      },
      style: {
        maxWidth: 150,
        fontSize: 13
      }
    }, React.createElement('option', {
      value: 'company'
    }, '업체명순'), React.createElement('option', {
      value: 'rank'
    }, '최고순위순'), React.createElement('option', {
      value: 'checked'
    }, '최근체크순')), React.createElement('span', {
      style: {
        fontSize: 12,
        color: '#94a3b8',
        marginLeft: 'auto'
      }
    }, '총 ' + displayed.length + '개')), React.createElement('div', {
      style: {
        overflowX: 'auto',
        border: '1px solid #eef2f7',
        borderRadius: 12
      }
    }, React.createElement('table', {
      style: {
        width: '100%',
        borderCollapse: 'collapse',
        fontSize: 13
      }
    }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
      style: _thS
    }, '업체명'), React.createElement('th', {
      style: _thS
    }, '상품명'), React.createElement('th', {
      style: _thC
    }, '최고 순위'), React.createElement('th', {
      style: _thC
    }, '노출 키워드'), React.createElement('th', {
      style: _thC
    }, '최근 체크'), canEdit !== false && React.createElement('th', {
      style: _thC
    }, '관리'))), React.createElement('tbody', null, displayed.length === 0 ? React.createElement('tr', null, React.createElement('td', {
      colSpan: 6,
      style: {
        padding: 24,
        textAlign: 'center',
        color: '#94a3b8'
      }
    }, _q ? '검색 결과가 없습니다.' : '추적 중인 상품이 없습니다. 상품을 등록해보세요.')) : displayed.map(function (p) {
      var kws = p.keywords || [];
      var isOpen = expandedProduct === p.id;
      var lc = _lastChecked(p);
      var rowMain = React.createElement('tr', {
        key: p.id,
        style: {
          cursor: 'pointer',
          borderTop: '1px solid #f1f5f9',
          background: isOpen ? '#f5f3ff' : '#fff'
        },
        onClick: function () {
          setExpandedProduct(isOpen ? null : p.id);
        }
      }, React.createElement('td', {
        style: {
          padding: '10px 12px',
          fontWeight: 800,
          color: '#0f172a',
          whiteSpace: 'nowrap',
          maxWidth: 220,
          overflow: 'hidden',
          textOverflow: 'ellipsis'
        }
      }, React.createElement('span', {
        style: {
          color: '#a78bfa',
          marginRight: 6,
          fontSize: 11
        }
      }, isOpen ? '▼' : '▶'), p.store_name || '-'), React.createElement('td', {
        style: {
          padding: '10px 12px',
          color: '#475569',
          maxWidth: 360,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        },
        title: p.product_name || ''
      }, p.product_name || '-'), React.createElement('td', {
        style: {
          padding: '10px 12px',
          textAlign: 'center'
        }
      }, _rankBadge(_bestRank(p))), React.createElement('td', {
        style: {
          padding: '10px 12px',
          textAlign: 'center',
          color: '#475569',
          whiteSpace: 'nowrap'
        }
      }, _exposedCount(p) + ' / ' + kws.length), React.createElement('td', {
        style: {
          padding: '10px 12px',
          textAlign: 'center',
          fontSize: 12,
          color: '#94a3b8',
          whiteSpace: 'nowrap'
        }
      }, lc ? new Date((lc || '').replace(' ', 'T')).toLocaleDateString('ko') : '-'), canEdit !== false && React.createElement('td', {
        style: {
          padding: '10px 12px',
          textAlign: 'center',
          whiteSpace: 'nowrap'
        }
      }, React.createElement('button', {
        className: 'btn btn-secondary btn-sm',
        style: {
          fontSize: 11,
          padding: '4px 8px'
        },
        onClick: function (e) {
          e.stopPropagation();
          handleRefresh(p.id);
        },
        disabled: refreshing[p.id],
        title: '순위 체크'
      }, refreshing[p.id] ? '체크중' : '↻'), React.createElement('button', {
        className: 'btn btn-danger btn-sm',
        style: {
          fontSize: 11,
          padding: '4px 8px',
          marginLeft: 4
        },
        onClick: function (e) {
          e.stopPropagation();
          handleDelete(p.id);
        },
        title: '삭제'
      }, '✕')));
      if (!isOpen) return rowMain;
      var detail = React.createElement('tr', {
        key: p.id + '-d'
      }, React.createElement('td', {
        colSpan: 6,
        style: {
          padding: 0,
          background: '#faf5ff'
        }
      }, React.createElement('div', {
        style: {
          padding: '8px 12px 14px'
        }
      }, onNavigateToClient && React.createElement('button', {
        onClick: function () {
          onNavigateToClient(p.store_name || '', p.product_url || '');
        },
        style: {
          fontSize: 11,
          fontWeight: 700,
          color: '#4f46e5',
          background: '#ede9fe',
          border: 'none',
          borderRadius: 8,
          padding: '4px 10px',
          cursor: 'pointer',
          marginBottom: 8
        }
      }, '업체관리에서 상세 보기 →'), kws.length === 0 ? React.createElement('div', {
        style: {
          fontSize: 12,
          color: '#94a3b8',
          padding: '8px 0'
        }
      }, '추적 키워드가 없습니다.') : React.createElement('table', {
        style: {
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: 12,
          background: '#fff',
          borderRadius: 8,
          overflow: 'hidden'
        }
      }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
        style: {
          textAlign: 'left',
          padding: '6px 10px',
          color: '#94a3b8',
          fontWeight: 700,
          fontSize: 11
        }
      }, '키워드'), React.createElement('th', {
        style: {
          textAlign: 'left',
          padding: '6px 10px',
          color: '#94a3b8',
          fontWeight: 700,
          fontSize: 11
        }
      }, '현재 순위'), React.createElement('th', {
        style: {
          textAlign: 'left',
          padding: '6px 10px',
          color: '#94a3b8',
          fontWeight: 700,
          fontSize: 11
        }
      }, '최근 체크'))), React.createElement('tbody', null, kws.map(function (k) {
        var kOpen = expandedKeyword === k.id;
        var krow = React.createElement('tr', {
          key: k.id,
          style: {
            cursor: 'pointer',
            borderTop: '1px solid #f1f5f9',
            background: kOpen ? '#f8fafc' : undefined
          },
          onClick: function () {
            var next = kOpen ? null : k.id;
            setExpandedKeyword(next);
            if (next) loadHistory(k.id, historyDays[k.id] || 30);
          }
        }, React.createElement('td', {
          style: {
            padding: '6px 10px',
            fontWeight: 600,
            color: '#1e293b'
          }
        }, React.createElement('span', {
          style: {
            color: '#cbd5e1',
            marginRight: 5,
            fontSize: 9
          }
        }, kOpen ? '▼' : '▶'), k.keyword), React.createElement('td', {
          style: {
            padding: '6px 10px'
          }
        }, _rankBadge(k.latest_rank)), React.createElement('td', {
          style: {
            padding: '6px 10px',
            fontSize: 11,
            color: '#94a3b8'
          }
        }, k.last_checked ? new Date((k.last_checked || '').replace(' ', 'T')).toLocaleString('ko') : '-'));
        if (!kOpen) return krow;
        return [krow, React.createElement('tr', {
          key: k.id + '-c'
        }, React.createElement('td', {
          colSpan: 3,
          style: {
            padding: 0,
            background: '#f8fafc'
          }
        }, renderRankHistoryChart(k.id, k.keyword, {
          storeName: p.store_name,
          storeUrl: p.product_url
        })))];
      }))))));
      return [rowMain, detail];
    })))));
  }())));
};

;/* ===== js/components/KeywordVolumeSection.jsx ===== */
/* KeywordVolumeSection — 키워드 검색량 (v6.1 미리보기 디자인) */
window.KeywordVolumeSection = function KeywordVolumeSection({
  keyword,
  data
}) {
  if (!data || !data.length) return null;
  const item = data[0];
  const pc = item?.monthlyPcQcCnt || 0;
  const mobile = item?.monthlyMobileQcCnt || 0;
  const total = pc + mobile;
  const pcRatio = total > 0 ? Math.round(pc / total * 100) : 0;
  const mobileRatio = total > 0 ? Math.round(mobile / total * 100) : 0;
  var note = mobileRatio >= 70 ? '모바일 비중 ' + mobileRatio + '% — 모바일 최적화 상세페이지가 매우 중요합니다.' : mobileRatio >= 50 ? '모바일과 PC가 균형 잡힌 키워드입니다. 양쪽 모두 최적화가 필요합니다.' : 'PC 비중 ' + pcRatio + '% — PC 기반 상세페이지 최적화에 집중하세요.';
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in",
    id: "sec-volume"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "hic"
  }, "\uD83D\uDD0D"), "\uD0A4\uC6CC\uB4DC \uAC80\uC0C9\uB7C9", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uC2E4\uCE21")), /*#__PURE__*/React.createElement("div", {
    className: "grid3"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uCD1D \uAC80\uC0C9\uB7C9"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(total), /*#__PURE__*/React.createElement("small", null, "\uD68C/\uC6D4"))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "PC"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(pc), /*#__PURE__*/React.createElement("small", null, "\uD68C (", pcRatio, "%)"))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uBAA8\uBC14\uC77C"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(mobile), /*#__PURE__*/React.createElement("small", null, "\uD68C (", mobileRatio, "%)")))), /*#__PURE__*/React.createElement("div", {
    className: "track",
    style: {
      height: 14,
      marginTop: 14,
      display: 'flex'
    }
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: pcRatio + '%',
      background: '#6366f1'
    }
  }), /*#__PURE__*/React.createElement("i", {
    style: {
      width: mobileRatio + '%',
      background: '#ec4899'
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      fontSize: 11,
      color: 'var(--sub)',
      marginTop: 5
    }
  }, /*#__PURE__*/React.createElement("span", null, "\u25CF PC ", pcRatio, "%"), /*#__PURE__*/React.createElement("span", null, "\uBAA8\uBC14\uC77C ", mobileRatio, "% \u25CF")), /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, note))));
};

;/* ===== js/components/RelatedKeywordsSection.jsx ===== */
/* RelatedKeywordsSection — 연관/황금 키워드 (v5) */
window.RelatedKeywordsSection = function RelatedKeywordsSection({
  data
}) {
  const {
    useState
  } = React;
  const [tab, setTab] = useState('related');
  if (!data) return null;
  const goldenList = data.golden_keywords || [];
  const relatedList = data.related_keywords || [];
  const displayList = tab === 'golden' ? goldenList : relatedList;
  const maxVol = displayList.reduce(function (m, k) {
    return Math.max(m, k.totalVolume || 0);
  }, 1);

  /* 경쟁강도 색상 맵 */
  var compColorMap = {
    '높음': '#ef4444',
    '보통': '#f59e0b',
    '낮음': '#10b981'
  };
  var compBgMap = {
    '높음': '#fef2f2',
    '보통': '#fffbeb',
    '낮음': '#f0fdf4'
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in",
    id: "sec-related"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDD17"), "\uC5F0\uAD00 \uD0A4\uC6CC\uB4DC \uBD84\uC11D", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uC2E4\uCE21"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontWeight: 400,
      color: '#64748b',
      marginLeft: 4
    }
  }, "\uCD1D ", fmt(data.total_found), "\uAC1C \uBC1C\uACAC")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uAC80\uC0C9\uB7C9\uACFC \uACBD\uC7C1\uAC15\uB3C4\uB97C \uAE30\uBC18\uC73C\uB85C \uBD84\uB958\uD569\uB2C8\uB2E4"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setTab('related'),
    style: {
      padding: '10px 20px',
      borderRadius: 10,
      border: 'none',
      background: tab === 'related' ? '#4f46e5' : '#f1f5f9',
      color: tab === 'related' ? '#fff' : '#64748b',
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      fontFamily: 'inherit',
      transition: 'all 0.2s'
    }
  }, "\uC5F0\uAD00 \uD0A4\uC6CC\uB4DC (", relatedList.length, ")"), /*#__PURE__*/React.createElement("button", {
    onClick: () => setTab('golden'),
    style: {
      padding: '10px 20px',
      borderRadius: 10,
      border: 'none',
      background: tab === 'golden' ? '#f59e0b' : '#f1f5f9',
      color: tab === 'golden' ? '#fff' : '#64748b',
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      fontFamily: 'inherit',
      transition: 'all 0.2s'
    }
  }, "\uD83D\uDC8E \uD669\uAE08 \uD0A4\uC6CC\uB4DC (", goldenList.length, ")")), displayList.length === 0 ? /*#__PURE__*/React.createElement(EmptyState, {
    icon: "\uD83D\uDC8E",
    text: tab === 'golden' ? '황금 키워드가 없습니다 (검색량 100~5,000 + 경쟁 낮음 조건)' : '연관 키워드가 없습니다'
  }) : /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 0,
      overflow: 'hidden',
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxHeight: 540,
      overflowY: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", {
    className: "rt-table",
    style: {
      width: '100%',
      borderCollapse: 'collapse'
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center',
      width: 40
    }
  }, "#"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'left'
    }
  }, "\uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'left'
    }
  }, "\uC6D4\uAC04 \uAC80\uC0C9\uB7C9"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center'
    }
  }, "PC"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center'
    }
  }, "\uBAA8\uBC14\uC77C"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center'
    }
  }, "\uACBD\uC7C1\uAC15\uB3C4"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'left',
      width: '20%'
    }
  }, "\uAC80\uC0C9\uB7C9 \uBE44\uC728"), tab === 'golden' && /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center'
    }
  }, "\uCD94\uCC9C"))), /*#__PURE__*/React.createElement("tbody", null, displayList.map((k, i) => {
    var volPct = maxVol > 0 ? Math.min(100, Math.round((k.totalVolume || 0) / maxVol * 100)) : 0;
    var cLabel = compLabel(k.compIdx);
    return /*#__PURE__*/React.createElement("tr", {
      key: k.keyword,
      style: {
        borderBottom: '1px solid #e2e8f0',
        background: i % 2 === 0 ? '#fff' : '#f8fafc'
      }
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 16px',
        textAlign: 'center',
        color: '#94a3b8',
        fontSize: 13,
        whiteSpace: 'nowrap',
        minWidth: 32
      }
    }, i + 1), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 20px',
        fontWeight: 600,
        fontSize: 14,
        color: '#0f172a'
      }
    }, k.keyword, k.isGolden && /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-block',
        marginLeft: 6,
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 10,
        fontWeight: 700,
        background: '#fef3c7',
        color: '#92400e'
      }
    }, "\uD669\uAE08")), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 20px',
        fontWeight: 700,
        fontSize: 14,
        color: '#4f46e5'
      }
    }, fmt(k.totalVolume)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 16px',
        textAlign: 'center',
        fontSize: 13,
        color: '#64748b'
      }
    }, fmt(k.monthlyPcQcCnt)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 16px',
        textAlign: 'center',
        fontSize: 13,
        color: '#64748b'
      }
    }, fmt(k.monthlyMobileQcCnt)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 16px',
        textAlign: 'center'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-block',
        padding: '4px 12px',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
        background: compBgMap[cLabel] || '#f1f5f9',
        color: compColorMap[cLabel] || '#64748b'
      }
    }, cLabel)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 20px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        height: 6,
        borderRadius: 3,
        background: '#f1f5f9',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: volPct + '%',
        height: '100%',
        borderRadius: 3,
        background: tab === 'golden' ? 'linear-gradient(90deg, #f59e0b, #fbbf24)' : 'linear-gradient(90deg, #4f46e5, #7c3aed)',
        transition: 'width 0.8s ease'
      }
    }))), tab === 'golden' && /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 16px',
        textAlign: 'center'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-block',
        padding: '4px 12px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        background: '#f0fdf4',
        color: '#166534'
      }
    }, "\uC9C4\uC785 \uCD94\uCC9C")));
  }))))))));
};

;/* ===== js/components/SeoDiagnosisSection.jsx ===== */
/* SeoDiagnosisSection — SEO 종합 진단 (v5 풀버전) */
window.SeoDiagnosisSection = function SeoDiagnosisSection({
  keyword,
  productUrl: parentProductUrl,
  competitorData,
  cachedRank,
  cachedProductName,
  cachedTotalVolume,
  cachedProductInfo,
  shopProducts
}) {
  const {
    useState,
    useEffect,
    useRef
  } = React;
  const [productUrl, setProductUrl] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const autoTriggered = useRef(false);
  // shopProducts ref — React 17 Promise 내 setState 비배치 문제 방지
  // useEffect 실행 시점에 shopProducts prop이 아직 null일 수 있으므로 ref로 최신값 보장
  const shopProductsRef = useRef(shopProducts);
  shopProductsRef.current = shopProducts;
  useEffect(function () {
    if (parentProductUrl) setProductUrl(parentProductUrl);
  }, [parentProductUrl]);
  useEffect(function () {
    autoTriggered.current = false;
    setResult(null);
  }, [keyword, parentProductUrl]);

  // 자동 실행: 메인 분석 데이터 + shopProducts 모두 도착한 후 실행
  // shopProducts를 deps에 포함하여 데이터 도착 후 재시도 보장
  useEffect(function () {
    if (keyword && productUrl && !autoTriggered.current && !result && !loading && (cachedRank || cachedProductName || cachedTotalVolume || cachedProductInfo) && shopProducts && shopProducts.length > 0) {
      autoTriggered.current = true;
      handleAnalyze();
    }
  }, [keyword, productUrl, cachedRank, cachedProductName, cachedTotalVolume, cachedProductInfo, shopProducts]);
  const handleAnalyze = async () => {
    if (!productUrl || !keyword) return;
    setLoading(true);
    try {
      var seoBody = {
        product_url: productUrl,
        keyword: keyword
      };
      // 메인 분석 데이터 재활용 → 네이버 API 중복 호출 방지
      if (cachedRank != null) seoBody.cached_rank = cachedRank;
      if (cachedProductName) seoBody.cached_product_name = cachedProductName;
      if (cachedTotalVolume != null) seoBody.cached_total_volume = cachedTotalVolume;
      if (cachedProductInfo) seoBody.cached_product_info = cachedProductInfo;
      // shopProducts에서 competitor 정보 추출 (ref로 최신값 읽기)
      var currentShopProducts = shopProductsRef.current;
      if (currentShopProducts && currentShopProducts.length > 0) {
        seoBody.cached_competitors = currentShopProducts.slice(0, 80).map(function (p) {
          return {
            product_id: p.product_id || '',
            product_name: p.product_name,
            price: p.price,
            store_name: p.store_name,
            brand: p.brand,
            category1: p.category1,
            category2: p.category2,
            product_url: p.product_url
          };
        });
      }
      const res = await api.post('/seo/analyze', seoBody);
      if (res.success) setResult(res.data);else toast.warn(res.detail || 'SEO 분석 데이터 일부를 가져오지 못했습니다.');
    } catch (e) {
      toast.warn('SEO 분석 요청 실패 — 잠시 후 다시 시도해주세요.');
    }
    setLoading(false);
  };

  /* v5 유틸 */
  const getScoreColor = s => s >= 70 ? '#10b981' : s >= 40 ? '#f59e0b' : '#ef4444';
  const getScoreLabel = s => s >= 70 ? '양호' : s >= 40 ? '보통' : '개선필요';
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in",
    id: "sec-seo"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDD27"), "\u2460 SEO \uC885\uD569 \uC9C4\uB2E8", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "\u2248 \uCD94\uC815")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "10\uAC1C \uD3C9\uAC00\uC9C0\uD45C\uB85C \uC0C1\uD488\uC758 \uAC80\uC0C9 \uB178\uCD9C \uC0C1\uD0DC\uB97C \uC9C4\uB2E8\uD569\uB2C8\uB2E4"), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      marginBottom: 16,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "\uBD84\uC11D\uD560 \uC0C1\uD488 URL\uC744 \uC785\uB825\uD558\uC138\uC694",
    value: productUrl,
    onChange: e => setProductUrl(e.target.value),
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: handleAnalyze,
    disabled: loading || !productUrl || !keyword
  }, loading ? '분석 중...' : 'SEO 진단')), keyword && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginTop: 8
    }
  }, "\uAE30\uC900 \uD0A4\uC6CC\uB4DC: ", /*#__PURE__*/React.createElement("strong", null, keyword))), loading && /*#__PURE__*/React.createElement(LoadingSpinner, {
    text: "SEO \uBD84\uC11D \uC911..."
  }), result && !loading && /*#__PURE__*/React.createElement("div", {
    className: "fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "grid2",
    style: {
      alignItems: 'center',
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "chartbox sm"
  }, /*#__PURE__*/React.createElement(ChartCanvas, {
    type: "radar",
    height: 320,
    data: {
      labels: ['상품명', '검색순위', '가격', '리뷰', '판매', '평점', '카테고리', '브랜드', '네이버페이', '최신성'],
      datasets: [{
        label: 'SEO 점수',
        data: [result.scores.title || 0, result.scores.rank || 0, result.scores.price || 0, result.scores.review || 0, result.scores.sales || 0, result.scores.rating || 0, result.scores.category || 0, result.scores.brand || 0, result.scores.naverpay || 0, result.scores.freshness || 0],
        borderColor: '#4f46e5',
        backgroundColor: 'rgba(79,70,229,.18)',
        pointBackgroundColor: '#4f46e5',
        borderWidth: 2
      }]
    },
    options: {
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              return ctx.label + ' ' + ctx.parsed.r + '점';
            }
          }
        }
      },
      scales: {
        r: {
          beginAtZero: true,
          max: 100,
          ticks: {
            display: false
          },
          pointLabels: {
            font: {
              size: 11
            }
          }
        }
      }
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 34,
      fontWeight: 900,
      color: getScoreColor(result.scores.total)
    }
  }, result.scores.total), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--rt-sub)'
    }
  }, "/100 \xB7 ", getScoreLabel(result.scores.total))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "\uC0C1\uD488\uBA85"), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, "15%")), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: (result.scores.title || 0) + '%'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "\uAC80\uC0C9\uC21C\uC704"), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, "15%")), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: (result.scores.rank || 0) + '%'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "\uAC00\uACA9"), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, "12%")), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: (result.scores.price || 0) + '%'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "\uB9AC\uBDF0"), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, "12%")), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: (result.scores.review || 0) + '%'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "\uD310\uB9E4\uC2E4\uC801"), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, "10%")), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: (result.scores.sales || 0) + '%'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "\uD3C9\uC810"), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, "8%")), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: (result.scores.rating || 0) + '%'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "\uCE74\uD14C\uACE0\uB9AC"), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, "8%")), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: (result.scores.category || 0) + '%'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "\uBE0C\uB79C\uB4DC"), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, "8%")), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: (result.scores.brand || 0) + '%'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "\uB124\uC774\uBC84\uD398\uC774"), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, "6%")), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: (result.scores.naverpay || 0) + '%'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "\uCD5C\uC2E0\uC131"), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, "6%")), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: (result.scores.freshness || 0) + '%'
    }
  }))), result.scores.detail?.current_rank && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      fontSize: 12,
      color: 'var(--rt-sub)',
      lineHeight: 1.6,
      textAlign: 'center'
    }
  }, "\uD604\uC7AC \uC21C\uC704: ", /*#__PURE__*/React.createElement("strong", null, result.scores.detail.current_rank, "\uC704"), " \xB7 \uCD94\uC815 \uC6D4 \uD310\uB9E4: ", /*#__PURE__*/React.createElement("strong", null, (result.scores.detail.est_monthly_sales || 0).toLocaleString(), "\uAC74")))), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: 'var(--rt-sub)',
      marginTop: 6
    }
  }, "10\uAC1C \uC9C0\uD45C: \uC0C1\uD488\uBA85\xB7\uAC80\uC0C9\uC21C\uC704\xB7\uAC00\uACA9\xB7\uB9AC\uBDF0\xB7\uD310\uB9E4\uC2E4\uC801\xB7\uD3C9\uC810\xB7\uCE74\uD14C\uACE0\uB9AC\xB7\uBE0C\uB79C\uB4DC\xB7\uB124\uC774\uBC84\uD398\uC774\xB7\uCD5C\uC2E0\uC131 (\uB808\uC774\uB354 \uCC28\uD2B8)"), result.suggestions?.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 700,
      fontSize: 14,
      marginBottom: 14,
      display: 'flex',
      alignItems: 'center',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("span", null, "\uD83D\uDCA1"), " \uAC1C\uC120 \uC81C\uC548"), result.suggestions.map((s, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      padding: '10px 0',
      borderBottom: i < result.suggestions.length - 1 ? '1px solid #f1f5f9' : 'none',
      fontSize: 13,
      color: '#334155',
      display: 'flex',
      gap: 10,
      lineHeight: 1.7
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 22,
      height: 22,
      borderRadius: 6,
      background: '#4f46e5',
      color: '#fff',
      fontSize: 11,
      fontWeight: 700,
      flexShrink: 0,
      marginTop: 2
    }
  }, i + 1), s))), /*#__PURE__*/React.createElement("div", {
    className: "note est"
  }, "\u203B \uB9AC\uBDF0 \uC218\xB7\uD3C9\uC810\xB7\uD310\uB9E4\uC2E4\uC801\xB7\uCD5C\uC2E0\uC131\uC740 \uC21C\uC704 \uAD6C\uAC04\uBCC4 \uC5C5\uACC4 \uD3C9\uADE0 \uAE30\uBC18 \uCD94\uC815\uCE58\uC785\uB2C8\uB2E4. \uB124\uC774\uBC84 \uC1FC\uD551 API \uD55C\uACC4\uB85C \uC2E4\uC81C \uC218\uCE58\uC640 \uCC28\uC774\uAC00 \uC788\uC744 \uC218 \uC788\uC73C\uBA70, \uD5A5\uD6C4 \uC815\uBC00\uD654 \uC608\uC815\uC785\uB2C8\uB2E4.")))));
};

;/* ===== js/components/ProductNameSection.jsx ===== */
/* ProductNameSection — 상품명 키워드 분석 */
window.ProductNameSection = function ProductNameSection({
  keyword,
  shopProducts
}) {
  const {
    useState,
    useEffect
  } = React;
  const [names, setNames] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  // 검색 결과의 1페이지 상품명 자동 채우기 + 자동 분석
  useEffect(function () {
    if (shopProducts && shopProducts.length > 0) {
      var productNames = shopProducts.map(function (p) {
        return p.product_name;
      }).filter(Boolean);
      setNames(productNames.join('\n'));
      // 자동 분석 실행
      if (productNames.length > 0) {
        setLoading(true);
        setResult(null);
        api.post('/product-name/analyze', {
          product_names: productNames,
          keyword: keyword || ''
        }).then(function (res) {
          if (res.success) setResult(res.data);
          setLoading(false);
        }).catch(function () {
          setLoading(false);
        });
      }
    }
  }, [shopProducts, keyword]);
  const handleAnalyze = async () => {
    const nameList = names.split('\n').map(n => n.trim()).filter(Boolean);
    if (nameList.length === 0) return;
    setLoading(true);
    try {
      const res = await api.post('/product-name/analyze', {
        product_names: nameList,
        keyword: keyword || ''
      });
      if (res.success) setResult(res.data);
    } catch (e) {
      alert('분석 실패');
    }
    setLoading(false);
  };
  const metricCardStyle = {
    background: '#fff',
    borderRadius: 16,
    padding: 24,
    border: '1px solid #e2e8f0',
    boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
    textAlign: 'center'
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in",
    id: "sec-productname"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDD24"), "\uC0C1\uD488\uBA85 \uD0A4\uC6CC\uB4DC \uBD84\uC11D", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uC2E4\uCE21")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uACBD\uC7C1 \uC0C1\uD488\uBA85\uC758 \uD0A4\uC6CC\uB4DC \uAD6C\uC131\uC744 \uBD84\uC11D\uD569\uB2C8\uB2E4"), /*#__PURE__*/React.createElement("div", {
    className: "no-export",
    style: {
      background: '#fff',
      borderRadius: 16,
      padding: 24,
      border: '1px solid #e2e8f0',
      boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
      marginBottom: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 12,
      fontWeight: 600,
      color: '#64748b',
      textTransform: 'uppercase',
      letterSpacing: '0.05em'
    }
  }, "\uC0C1\uD488\uBA85 \uBAA9\uB85D (\uD55C \uC904\uC5D0 \uD558\uB098\uC529)")), /*#__PURE__*/React.createElement("textarea", {
    style: {
      width: '100%',
      height: 100,
      padding: 12,
      border: '1.5px solid #e2e8f0',
      borderRadius: 12,
      fontFamily: 'inherit',
      fontSize: 13,
      resize: 'vertical',
      outline: 'none',
      background: '#f8fafc',
      color: '#0f172a',
      boxSizing: 'border-box'
    },
    placeholder: "\uACBD\uC7C1 \uC0C1\uD488\uBA85\uC744 \uD55C \uC904\uC5D0 \uD558\uB098\uC529 \uC785\uB825\uD558\uC138\uC694...",
    value: names,
    onChange: e => setNames(e.target.value)
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: handleAnalyze,
    disabled: loading || !names.trim(),
    style: {
      borderRadius: 12,
      padding: '10px 24px',
      fontWeight: 700
    }
  }, loading ? '분석 중...' : '상품명 분석'))), result && /*#__PURE__*/React.createElement("div", {
    className: "fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3, 1fr)',
      gap: 16,
      marginBottom: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: metricCardStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, "\uD83D\uDCE6"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      marginBottom: 6
    }
  }, "\uBD84\uC11D \uC0C1\uD488 \uC218"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: '#0f172a'
    }
  }, result.total_analyzed), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#64748b'
    }
  }, "\uAC1C")), /*#__PURE__*/React.createElement("div", {
    style: metricCardStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, "\uD83D\uDCCF"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      marginBottom: 6
    }
  }, "\uD3C9\uADE0 \uC0C1\uD488\uBA85 \uAE38\uC774"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: '#0f172a'
    }
  }, result.avg_name_length), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#64748b'
    }
  }, "\uC790")), /*#__PURE__*/React.createElement("div", {
    style: metricCardStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, "\uD83C\uDFAF"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      marginBottom: 6
    }
  }, "\uD0A4\uC6CC\uB4DC \uD3EC\uD568\uB960"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: '#0f172a'
    }
  }, result.keyword_coverage != null ? result.keyword_coverage : '-'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#64748b'
    }
  }, "%"))), result.top_keywords?.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#fff',
      borderRadius: 16,
      padding: 24,
      border: '1px solid #e2e8f0',
      boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 700,
      color: '#0f172a',
      marginBottom: 16
    }
  }, "\uD83D\uDCCA \uC790\uC8FC \uC0AC\uC6A9\uB41C \uD0A4\uC6CC\uB4DC TOP 15"), /*#__PURE__*/React.createElement("div", {
    className: "table-wrap",
    style: {
      maxHeight: 282,
      overflowY: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", {
    className: "rt-table"
  }, /*#__PURE__*/React.createElement("thead", {
    style: {
      position: 'sticky',
      top: 0,
      zIndex: 1
    }
  }, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    style: {
      fontWeight: 600,
      fontSize: 12
    }
  }, "#"), /*#__PURE__*/React.createElement("th", {
    style: {
      fontWeight: 600,
      fontSize: 12
    }
  }, "\uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("th", {
    style: {
      fontWeight: 600,
      fontSize: 12
    }
  }, "\uB4F1\uC7A5 \uD69F\uC218"), /*#__PURE__*/React.createElement("th", {
    style: {
      fontWeight: 600,
      fontSize: 12
    }
  }, "\uC0AC\uC6A9 \uBE44\uC728"))), /*#__PURE__*/React.createElement("tbody", null, result.top_keywords.slice(0, 15).map((k, i) => /*#__PURE__*/React.createElement("tr", {
    key: k.word,
    style: {
      background: i % 2 === 0 ? '#fff' : '#f8fafc'
    }
  }, /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 26,
      height: 26,
      background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
      color: '#fff',
      borderRadius: '50%',
      fontSize: 11,
      fontWeight: 700
    }
  }, i + 1)), /*#__PURE__*/React.createElement("td", {
    style: {
      fontWeight: 600,
      color: '#0f172a'
    }
  }, k.word), /*#__PURE__*/React.createElement("td", {
    style: {
      color: '#0f172a'
    }
  }, k.count, "\uD68C"), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      maxWidth: 120,
      height: 8,
      borderRadius: 8,
      background: '#f1f5f9',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: Math.min(k.ratio, 100) + '%',
      height: '100%',
      borderRadius: 8,
      background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
      transition: 'width 0.3s ease'
    }
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: '#64748b',
      minWidth: 36
    }
  }, k.ratio, "%")))))))))))));
};

;/* ===== js/components/ReportSection.jsx ===== */
/* ReportSection — 보고서 내보내기 (DOM 복제 HTML + JSON/CSV) */
window.ReportSection = function ReportSection(props) {
  var propKeyword = props && props.keyword || '';
  var propCompanyName = props && props.companyName || '';
  const {
    useState,
    useEffect
  } = React;
  const [format, setFormat] = useState('html');
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [companyName, setCompanyName] = useState(propCompanyName);

  /* props에서 업체명이 바뀌면 반영 */
  useEffect(function () {
    if (propCompanyName) setCompanyName(propCompanyName);
  }, [propCompanyName]);

  /* HTML 보고서 — 현재 페이지 DOM 복제 */
  var handleHtmlExport = function () {
    setLoading(true);
    try {
      /*
       * 페이지의 모든 분석 결과를 DOM 순서대로 자동 캡처
       * App 루트의 직접 자식 요소를 순회하여
       * 네비게이션/검색바/보고서/알림/푸터를 제외한 모든 콘텐츠를 수집
       */
      /* ★ 보고서 본문(.report-main)을 통째로 캡처 — 모든 섹션 포함 + 스코프 CSS(.report-main ...) 유지 */
      var captured = [];
      var srcMain = document.querySelector('.report-main');
      if (srcMain) {
        captured.push(srcMain.cloneNode(true));
      } else {
        /* 폴백: .section 클래스 기반(있을 때만) */
        var allSections = document.querySelectorAll('.section');
        allSections.forEach(function (s) {
          if (s.id === 'sec-report' || s.id === 'sec-notify') return;
          captured.push(s.cloneNode(true));
        });
      }

      /* ★ 차트 canvas → 이미지(toDataURL) 변환 (canvas는 outerHTML에 그림이 안 담겨 빈칸이 됨) */
      try {
        var _origCanvas = (srcMain || document).querySelectorAll('canvas');
        captured.forEach(function (node) {
          var _cloneCanvas = node.querySelectorAll('canvas');
          for (var _ci = 0; _ci < _cloneCanvas.length; _ci++) {
            try {
              var _du = '';
              /* Chart.js 인스턴스가 있으면 toBase64Image가 가장 안정적 */
              try {
                var _ch = window.Chart && window.Chart.getChart ? window.Chart.getChart(_origCanvas[_ci]) : null;
                if (_ch) _du = _ch.toBase64Image('image/png', 1);
              } catch (eChart) {}
              if (!_du && _origCanvas[_ci] && _origCanvas[_ci].toDataURL) _du = _origCanvas[_ci].toDataURL('image/png');
              if (!_du) continue;
              var _img = document.createElement('img');
              _img.src = _du;
              _img.style.cssText = 'width:100%;height:auto;display:block;margin-bottom:14px;';
              if (_cloneCanvas[_ci].parentNode) _cloneCanvas[_ci].parentNode.replaceChild(_img, _cloneCanvas[_ci]);
              /* ★겹침방지(핵심): 이미지의 직속 부모(차트 래퍼, height:NNNpx 고정)와 .chartbox 모두 높이 해제 →
                 이미지가 비율대로 늘어나도 래퍼가 정확히 감싸 아래 노트와 겹치지 않게 */
              var _wrap = _img.parentNode; /* ChartCanvas가 만든 position:relative;height:NNNpx 래퍼 */
              if (_wrap && _wrap.style) {
                _wrap.style.height = 'auto';
                _wrap.style.minHeight = '0';
                _wrap.style.position = 'static';
              }
              var _box = _img.closest && _img.closest('.chartbox') || _wrap;
              if (_box && _box.style) {
                _box.style.height = 'auto';
                _box.style.minHeight = '0';
                _box.style.overflow = 'visible';
                _box.style.marginBottom = '18px';
              }
            } catch (eImg) {}
          }
        });
      } catch (eCanvas) {}

      /* 클론에서 no-export / 인터랙티브 요소 제거 */
      captured.forEach(function (node) {
        var noExport = node.querySelectorAll('.no-export');
        noExport.forEach(function (el) {
          el.remove();
        });
        var btns = node.querySelectorAll('button, .btn');
        btns.forEach(function (b) {
          b.remove();
        });
        var inputs = node.querySelectorAll('input, select, textarea');
        inputs.forEach(function (inp) {
          var span = document.createElement('span');
          span.textContent = inp.value || '';
          span.style.fontWeight = '600';
          inp.parentNode.replaceChild(span, inp);
        });
        /* grid 레이아웃 요소에 반응형 클래스 추가 */
        var gridEls = node.querySelectorAll('[style*="grid-template-columns"]');
        gridEls.forEach(function (el) {
          el.classList.add('rpt-grid');
        });
        var flexEls = node.querySelectorAll('[style*="display: flex"], [style*="display:flex"]');
        flexEls.forEach(function (el) {
          el.classList.add('rpt-flex');
        });
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
          } catch (e) {/* cross-origin 무시 */}
        }
      } catch (e) {}

      /* 섹션 HTML 합치기 */
      var bodyHtml = '';
      captured.forEach(function (node) {
        bodyHtml += node.outerHTML + '\n';
      });
      var dateStr = new Date().toLocaleDateString('ko-KR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      });
      var headerText = companyName ? companyName + ' 분석 보고서' : '로직 분석 보고서';
      var fullHtml = '<!DOCTYPE html>\n<html lang="ko">\n<head>\n' + '<meta charset="UTF-8">\n' + '<meta name="viewport" content="width=1200">\n' + '<title>' + headerText + ' - ' + dateStr + '</title>\n' + '<style>\n' + '* { margin: 0; padding: 0; box-sizing: border-box; }\n' + 'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #1e293b; }\n' + '.report-header { background: linear-gradient(135deg, #6C5CE7, #a29bfe); color: #fff; padding: 40px 20px; text-align: center; }\n' + '.report-header h1 { font-size: 24px; margin-bottom: 8px; }\n' + '.report-header p { font-size: 14px; opacity: 0.85; }\n' + '.report-footer { text-align: center; padding: 30px; color: #94a3b8; font-size: 12px; border-top: 1px solid #e2e8f0; margin-top: 40px; }\n' + cssText + '\n@media print { .report-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }\n' + '</style>\n</head>\n<body>\n' + '<div class="report-header">\n' + '  <h1>' + headerText + '</h1>\n' + '  <p>' + dateStr + ' | 메타아이앤씨 로직 분석 시스템</p>\n' + '</div>\n' + '<div class="report-content" style="max-width:1200px; margin:0 auto; padding:20px;">\n' + bodyHtml + '</div>\n' + '<div class="report-footer">\n' + '  <p>\u00A9 2026 \uba54\ud0c0\uc544\uc774\uc564\uc528 \u2014 \ub85c\uc9c1 \ubd84\uc11d \uc2dc\uc2a4\ud15c | \ubcf8 \ubcf4\uace0\uc11c\ub294 \uc790\ub3d9 \uc0dd\uc131\ub418\uc5c8\uc2b5\ub2c8\ub2e4.</p>\n' + '</div>\n' + '</body>\n</html>';

      /* 다운로드 */
      var blob = new Blob([fullHtml], {
        type: 'text/html;charset=utf-8'
      });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      var fileName = (companyName || '로직분석') + '_보고서_' + new Date().toISOString().slice(0, 10) + '.html';
      a.download = fileName;
      a.click();
      URL.revokeObjectURL(url);
      alert('HTML 보고서가 다운로드되었습니다.');
    } catch (e) {
      alert('HTML 보고서 생성 실패: ' + e.message);
    }
    setLoading(false);
  };

  /* JSON/CSV 보고서 (기존) */
  var handleDataExport = async function () {
    setLoading(true);
    try {
      var res = await api.post('/report/export', {
        format: format,
        date_range: days
      });
      if (res.success) setData(res.data);
    } catch (e) {
      alert('보고서 생성 실패');
    }
    setLoading(false);
  };
  var handleExport = function () {
    if (format === 'html') {
      handleHtmlExport();
    } else {
      handleDataExport();
    }
  };
  var handleDownloadCSV = function () {
    if (!data || !data.content) return;
    var bom = '\uFEFF';
    var blob = new Blob([bom + data.content], {
      type: 'text/csv;charset=utf-8;'
    });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (companyName || '로직분석') + '_보고서_' + new Date().toISOString().slice(0, 10) + '.csv';
    a.click();
    URL.revokeObjectURL(url);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in",
    id: "sec-report"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "section-title"
  }, /*#__PURE__*/React.createElement("span", {
    className: "icon",
    style: {
      background: '#eff6ff'
    }
  }, "\uD83D\uDCC4"), "\uBCF4\uACE0\uC11C \uB0B4\uBCF4\uB0B4\uAE30"), /*#__PURE__*/React.createElement("div", {
    className: "section-line"
  }), /*#__PURE__*/React.createElement("p", {
    className: "section-subtitle"
  }, "\uBD84\uC11D \uACB0\uACFC\uB97C HTML/JSON/CSV\uB85C \uB2E4\uC6B4\uB85C\uB4DC\uD569\uB2C8\uB2E4"), /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 12,
      alignItems: 'flex-end',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "form-group",
    style: {
      marginBottom: 0
    }
  }, /*#__PURE__*/React.createElement("label", {
    className: "form-label"
  }, "\uC5C5\uCCB4\uBA85 (\uC120\uD0DD)"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    style: {
      width: 160
    },
    placeholder: "\uC5C5\uCCB4\uBA85 \uC785\uB825",
    value: companyName,
    onChange: function (e) {
      setCompanyName(e.target.value);
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "form-group",
    style: {
      marginBottom: 0
    }
  }, /*#__PURE__*/React.createElement("label", {
    className: "form-label"
  }, "\uD615\uC2DD"), /*#__PURE__*/React.createElement("select", {
    className: "form-input",
    style: {
      width: 140
    },
    value: format,
    onChange: function (e) {
      setFormat(e.target.value);
    }
  }, /*#__PURE__*/React.createElement("option", {
    value: "html"
  }, "HTML \uBCF4\uACE0\uC11C"), /*#__PURE__*/React.createElement("option", {
    value: "json"
  }, "JSON"), /*#__PURE__*/React.createElement("option", {
    value: "csv"
  }, "CSV"))), format !== 'html' && /*#__PURE__*/React.createElement("div", {
    className: "form-group",
    style: {
      marginBottom: 0
    }
  }, /*#__PURE__*/React.createElement("label", {
    className: "form-label"
  }, "\uAE30\uAC04"), /*#__PURE__*/React.createElement("select", {
    className: "form-input",
    style: {
      width: 120
    },
    value: days,
    onChange: function (e) {
      setDays(Number(e.target.value));
    }
  }, /*#__PURE__*/React.createElement("option", {
    value: 7
  }, "\uCD5C\uADFC 7\uC77C"), /*#__PURE__*/React.createElement("option", {
    value: 14
  }, "\uCD5C\uADFC 14\uC77C"), /*#__PURE__*/React.createElement("option", {
    value: 30
  }, "\uCD5C\uADFC 30\uC77C"), /*#__PURE__*/React.createElement("option", {
    value: 90
  }, "\uCD5C\uADFC 90\uC77C"))), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: handleExport,
    disabled: loading
  }, loading ? '생성 중...' : format === 'html' ? '📄 HTML 보고서 다운로드' : '보고서 생성'), data && data.format === 'csv' && /*#__PURE__*/React.createElement("button", {
    className: "btn btn-secondary",
    onClick: handleDownloadCSV
  }, "\uD83D\uDCE5 CSV \uB2E4\uC6B4\uB85C\uB4DC")), format === 'html' && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12,
      padding: '10px 14px',
      background: '#f0f9ff',
      borderRadius: 8,
      fontSize: 13,
      color: '#0369a1'
    }
  }, "\uD83D\uDCA1 \uD604\uC7AC \uD398\uC774\uC9C0\uC5D0 \uD45C\uC2DC\uB41C \uBAA8\uB4E0 \uBD84\uC11D \uACB0\uACFC\uB97C \uADF8\uB300\uB85C HTML \uD30C\uC77C\uB85C \uB0B4\uBCF4\uB0C5\uB2C8\uB2E4. \uBA3C\uC800 \uD0A4\uC6CC\uB4DC \uAC80\uC0C9\uC744 \uC644\uB8CC\uD55C \uD6C4 \uBCF4\uACE0\uC11C\uB97C \uC0DD\uC131\uD574\uC8FC\uC138\uC694."), data && data.format === 'json' && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 16,
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "badge badge-blue"
  }, "\uC0C1\uD488 ", data.total_products, "\uAC1C"), /*#__PURE__*/React.createElement("span", {
    className: "badge badge-green"
  }, "\uD0A4\uC6CC\uB4DC ", data.total_keywords, "\uAC1C"), /*#__PURE__*/React.createElement("span", {
    className: "badge badge-gray"
  }, data.generated_at ? data.generated_at.slice(0, 10) : '')), /*#__PURE__*/React.createElement("div", {
    className: "table-wrap",
    style: {
      maxHeight: 300,
      overflow: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", null, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "\uC0C1\uD488\uBA85"), /*#__PURE__*/React.createElement("th", null, "\uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("th", null, "\uCD5C\uADFC \uC21C\uC704"), /*#__PURE__*/React.createElement("th", null, "\uC774\uB825 \uC218"))), /*#__PURE__*/React.createElement("tbody", null, (data.items || []).map(function (item, i) {
    return /*#__PURE__*/React.createElement("tr", {
      key: i
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        maxWidth: 200,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, item.product_name), /*#__PURE__*/React.createElement("td", null, item.keyword), /*#__PURE__*/React.createElement("td", {
      style: {
        fontWeight: 600
      }
    }, item.latest_rank ? item.latest_rank + '위' : '-'), /*#__PURE__*/React.createElement("td", null, item.history_count, "\uAC74"));
  }))))))));
};

;/* ===== js/components/NotificationSection.jsx ===== */
/* NotificationSection — 알림 설정 */
window.NotificationSection = function NotificationSection() {
  const {
    useState,
    useEffect
  } = React;
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/notify/settings').then(res => {
      if (res.success) setSettings(res.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);
  const toggleNotify = async enabled => {
    const res = await api.put('/notify/settings', {
      notify_enabled: enabled
    });
    if (res.success) setSettings(res.data);
  };
  if (loading) return null;
  if (!settings) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "section",
    id: "sec-notify"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "section-title"
  }, /*#__PURE__*/React.createElement("span", {
    className: "icon",
    style: {
      background: '#fffbeb'
    }
  }, "\uD83D\uDD14"), "\uC54C\uB9BC \uC124\uC815"), /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 600,
      fontSize: 14
    }
  }, "\uC77C\uC77C \uB9AC\uD3EC\uD2B8 \uC54C\uB9BC"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginTop: 2
    }
  }, settings.report_time || '09:00', "\uC5D0 \uC21C\uC704 \uBCC0\uB3D9 \uB9AC\uD3EC\uD2B8\uB97C \uBC1C\uC1A1\uD569\uB2C8\uB2E4")), /*#__PURE__*/React.createElement("label", {
    className: "toggle"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: settings.notify_enabled || false,
    onChange: e => toggleNotify(e.target.checked)
  }), /*#__PURE__*/React.createElement("span", {
    className: "toggle-track"
  }))), !settings.solapi_configured && /*#__PURE__*/React.createElement("div", {
    className: "alert alert-info",
    style: {
      marginTop: 12,
      marginBottom: 0
    }
  }, "\uC194\uB77C\uD53C API\uAC00 \uC124\uC815\uB418\uC9C0 \uC54A\uC558\uC2B5\uB2C8\uB2E4. \uC54C\uB9BC\uC744 \uC0AC\uC6A9\uD558\uB824\uBA74 \uD658\uACBD\uBCC0\uC218\uB97C \uC124\uC815\uD558\uC138\uC694."))));
};

;/* ===== js/components/CompetitionIndexSection.jsx ===== */
window.CompetitionIndexSection = function CompetitionIndexSection(props) {
  if (!props?.data) return null;
  const {
    compIndex,
    compPercent,
    compLabel,
    compColor,
    productCount,
    searchVolume,
    avgCtr,
    interpretation
  } = props.data;
  if (compPercent === undefined && compIndex === undefined) return null;
  var pct = typeof compPercent === 'number' ? compPercent : Math.min(98, Math.round(Math.log10(compIndex * 10 + 1) / Math.log10(101) * 100));
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\u2694\uFE0F"), "\uD0A4\uC6CC\uB4DC \uACBD\uC7C1\uAC15\uB3C4 \uBD84\uC11D", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uC2E4\uCE21")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uC0C1\uD488 \uC218 \uB300\uBE44 \uAC80\uC0C9\uB7C9\uC73C\uB85C \uACBD\uC7C1 \uC218\uC900\uC744 \uD310\uB2E8\uD569\uB2C8\uB2E4"), /*#__PURE__*/React.createElement("div", {
    className: "grid2",
    style: {
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      width: 172,
      height: 172
    }
  }, /*#__PURE__*/React.createElement(ChartCanvas, {
    type: "doughnut",
    height: 172,
    style: {
      height: 172,
      width: 172
    },
    data: {
      labels: ['경쟁', '여유'],
      datasets: [{
        data: [pct, Math.max(0, 100 - pct)],
        backgroundColor: [compColor, (window.CHART_COLORS || {}).GRID || '#eef2f7'],
        borderWidth: 0
      }]
    },
    options: {
      cutout: '70%',
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          enabled: false
        }
      }
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 24,
      fontWeight: 900,
      color: compColor,
      lineHeight: 1.1
    }
  }, fmt(compIndex)), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#64748b',
      marginTop: 3
    }
  }, "\uACBD\uC7C1\uC9C0\uC218"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 700,
      color: compColor,
      marginTop: 2
    }
  }, compLabel)))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "band"
  }, /*#__PURE__*/React.createElement("span", {
    className: "mk",
    style: {
      left: 'calc(' + pct + '% - 2px)'
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      fontSize: 11,
      color: '#64748b'
    }
  }, /*#__PURE__*/React.createElement("span", null, "\uBE14\uB8E8\uC624\uC158"), /*#__PURE__*/React.createElement("span", null, "\uBCF4\uD1B5"), /*#__PURE__*/React.createElement("span", null, "\uB808\uB4DC\uC624\uC158")), /*#__PURE__*/React.createElement("div", {
    className: "grid3",
    style: {
      marginTop: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uB4F1\uB85D \uC0C1\uD488\uC218"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(productCount))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uC6D4\uAC04 \uAC80\uC0C9\uB7C9"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(searchVolume))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uD3C9\uADE0 \uD074\uB9AD\uC218"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(avgCtr)))))), /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, "\uACBD\uC7C1\uC9C0\uC218 ", fmt(compIndex), "(", compLabel, ")", interpretation ? '. ' + interpretation : '.'))));
};

;/* ===== js/components/MarketRevenueSection.jsx ===== */
window.MarketRevenueSection = function MarketRevenueSection(props) {
  if (!props?.data) return null;
  const {
    avgPrice,
    estimatedMonthly,
    topProducts,
    conversionRate,
    calculationMethod
  } = props.data;
  if (!topProducts || topProducts.length === 0) return null;
  var C = window.CHART_COLORS || {};
  var parseWon = function (s) {
    return parseInt(String(s).replace(/[^0-9]/g, ''), 10) || 0;
  };
  /* 순위별 예상 월 매출 차트용 데이터 (상위 10위, 만원 단위) */
  var revTop = (topProducts || []).slice(0, 10);
  var revLabels = revTop.map(function (it) {
    return it.rank + '위';
  });
  var revValues = revTop.map(function (it) {
    return Math.round(parseWon(it.estRevenue) / 10000);
  });
  var hasRevChart = revValues.some(function (v) {
    return v > 0;
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDCB0"), "\uC2DC\uC7A5 \uADDC\uBAA8 & \uB9E4\uCD9C \uCD94\uC815", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "\u2248 \uCD94\uC815")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uAC80\uC0C9\uB7C9 \xD7 \uD074\uB9AD\uB960 \xD7 \uC804\uD658\uC728 \xD7 \uD3C9\uADE0 \uB2E8\uAC00 \uAE30\uBC18 \uCD94\uC815"), /*#__PURE__*/React.createElement("div", {
    className: "grid3"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uC6D4\uAC04 \uC2DC\uC7A5 \uADDC\uBAA8"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, estimatedMonthly || '-')), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uD3C9\uADE0 \uD310\uB9E4\uAC00"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, avgPrice || '-')), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uC801\uC6A9 \uC804\uD658\uC728"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, conversionRate || '3.0%'))), hasRevChart && /*#__PURE__*/React.createElement("div", {
    className: "chartbox",
    style: {
      marginTop: 14
    }
  }, /*#__PURE__*/React.createElement(ChartCanvas, {
    type: "bar",
    height: 240,
    data: {
      labels: revLabels,
      datasets: [{
        label: '예상 월 매출(만원)',
        data: revValues,
        backgroundColor: function (ctx) {
          return ctx.dataIndex < 3 ? C.IND : C.SOFT;
        },
        borderRadius: 6
      }]
    },
    options: {
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              return (window.chartComma ? window.chartComma(ctx.parsed.y) : ctx.parsed.y) + '만원';
            }
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            callback: function (v) {
              return (window.chartComma ? window.chartComma(v) : v) + '만';
            }
          }
        }
      }
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "rt-scroll"
  }, /*#__PURE__*/React.createElement("table", {
    className: "rt-table",
    style: {
      marginTop: 0
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "\uC21C\uC704"), /*#__PURE__*/React.createElement("th", null, "\uC0C1\uD488\uBA85"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center',
      whiteSpace: 'nowrap'
    }
  }, "CTR"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "\uC608\uC0C1 \uD310\uB9E4"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "\uC608\uC0C1 \uC6D4 \uB9E4\uCD9C"))), /*#__PURE__*/React.createElement("tbody", null, topProducts.map(function (item, idx) {
    var isMyProduct = item.isMyProduct || false;
    return /*#__PURE__*/React.createElement("tr", {
      key: idx,
      style: isMyProduct ? {
        background: '#fff7ed'
      } : {}
    }, /*#__PURE__*/React.createElement("td", null, item.rank), /*#__PURE__*/React.createElement("td", {
      style: {
        fontWeight: isMyProduct ? 700 : 400,
        wordBreak: 'keep-all'
      }
    }, item.name, isMyProduct ? ' 👈' : ''), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'center',
        whiteSpace: 'nowrap'
      }
    }, item.ctr), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, item.estMonthlySales), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, item.estRevenue));
  })))), /*#__PURE__*/React.createElement("div", {
    className: "note est"
  }, "\u2248 \uAC80\uC0C9\uB7C9\xD7\uC21C\uC704\uBCC4 \uD074\uB9AD\uB960\xD7\uC804\uD658\uC728 \uAE30\uBC18 ", /*#__PURE__*/React.createElement("b", null, "\uC2DC\uC7A5 \uADDC\uBAA8 \uCD94\uC815"), "(\uAC1C\uBCC4 \uC2E4\uD310\uB9E4 \uC544\uB2D8). \uBCF4\uC644 \uD6C4 \uB9AC\uBDF0\uC99D\uAC00 \uAE30\uBC18\uC73C\uB85C \uC815\uBC00\uD654."))));
};

;/* ===== js/components/GoldenKeywordCard.jsx ===== */
window.GoldenKeywordCard = function GoldenKeywordCard(props) {
  if (!props?.data) return null;

  // 단일 객체 또는 배열 모두 처리
  const items = Array.isArray(props.data) ? props.data : [props.data];
  if (!items.length) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDC51"), "\uACE8\uB4E0 \uD0A4\uC6CC\uB4DC ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uC2E4\uCE21")), /*#__PURE__*/React.createElement("div", {
    className: "grid2"
  }, items.map(function (item, idx) {
    if (!item || !item.name || item.score === undefined) return null;
    const {
      name,
      score,
      volume,
      competition,
      ctr,
      clicks,
      reason
    } = item;
    const scorePercent = Math.min(100, score / 100 * 100);
    return /*#__PURE__*/React.createElement("div", {
      key: idx,
      className: "sub-card"
    }, /*#__PURE__*/React.createElement("div", {
      className: "st"
    }, "\uD83D\uDC51 ", name, /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 'auto',
        color: 'var(--est)',
        fontWeight: 900
      }
    }, "\uC810\uC218 ", score)), /*#__PURE__*/React.createElement("div", {
      className: "grid2",
      style: {
        gap: '8px',
        margin: '8px 0'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: '12px'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--sub)'
      }
    }, "\uC6D4 \uAC80\uC0C9\uB7C9"), " ", /*#__PURE__*/React.createElement("b", null, fmt(volume))), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: '12px'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--sub)'
      }
    }, "\uACBD\uC7C1\uAC15\uB3C4"), " ", /*#__PURE__*/React.createElement("b", null, competition)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: '12px'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--sub)'
      }
    }, "\uD3C9\uADE0 \uD074\uB9AD"), " ", /*#__PURE__*/React.createElement("b", null, typeof ctr === 'number' ? ctr.toFixed(1) : ctr)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: '12px'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--sub)'
      }
    }, "\uC6D4 \uD074\uB9AD\uC218"), " ", /*#__PURE__*/React.createElement("b", null, fmt(clicks)))), /*#__PURE__*/React.createElement("div", {
      className: "track"
    }, /*#__PURE__*/React.createElement("i", {
      style: {
        width: Math.round(scorePercent) + '%'
      }
    })), reason && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: '11.5px',
        color: 'var(--sub)',
        marginTop: '6px'
      }
    }, reason));
  })));
};

;/* ===== js/components/AdvertiserInfoCard.jsx ===== */
window.AdvertiserInfoCard = function AdvertiserInfoCard(props) {
  if (!props?.data) return null;
  const {
    adDepth,
    pcClicks,
    mobileClicks,
    compIdx
  } = props.data;
  var num = typeof fmt === 'function' ? fmt : function (x) {
    return x;
  };
  var items = [{
    label: '광고 노출 깊이',
    value: adDepth ? '상위 ' + adDepth + '개' : '-',
    unit: ''
  }, {
    label: 'PC 평균 클릭수',
    value: pcClicks || pcClicks === 0 ? num(pcClicks) : '-',
    unit: '회'
  }, {
    label: '모바일 평균 클릭수',
    value: mobileClicks || mobileClicks === 0 ? num(mobileClicks) : '-',
    unit: '회'
  }, {
    label: '광고 경쟁강도',
    value: compIdx || '-',
    unit: ''
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDCE3"), "\uAD11\uACE0 \uACBD\uC7C1 \uC815\uBCF4", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uC2E4\uCE21")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uB124\uC774\uBC84 \uAC80\uC0C9\uAD11\uACE0 \uAE30\uC900 \u2014 \uC774 \uD0A4\uC6CC\uB4DC\uC5D0 \uAD11\uACE0\uB85C \uB4E4\uC5B4\uC62C \uB54C\uC758 \uACBD\uC7C1 \uD658\uACBD"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 12
    }
  }, items.map(function (item, idx) {
    return /*#__PURE__*/React.createElement("div", {
      key: idx,
      className: "rt-kpi"
    }, /*#__PURE__*/React.createElement("div", {
      className: "rt-kpi-k"
    }, item.label), /*#__PURE__*/React.createElement("div", {
      className: "rt-kpi-v",
      style: {
        fontSize: 20
      }
    }, item.value, item.unit && /*#__PURE__*/React.createElement("small", null, item.unit)));
  })), /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, "\uAD11\uACE0 \uACBD\uC7C1\uC774 \uCE58\uC5F4\uD560\uC218\uB85D \uC785\uCC30\uAC00 \uBD80\uB2F4\uC774 \uCEE4\uC9C0\uBBC0\uB85C, SEO(\uC790\uC5F0\uB178\uCD9C)\uB97C \uBCD1\uD589\uD574 \uAD11\uACE0\uBE44 \uD6A8\uC728\uC744 \uD655\uBCF4\uD558\uB294 \uAC83\uC774 \uC720\uB9AC\uD569\uB2C8\uB2E4."))));
};

;/* ===== js/components/SummaryCardsSection.jsx ===== */
/* SummaryCardsSection — 종합 요약 (시안: 한 카드 + ✅배지 KPI 4칸) */
window.SummaryCardsSection = function SummaryCardsSection(props) {
  if (!props?.data) return null;
  const {
    totalVolume,
    productCount,
    goldenCount,
    compLevel,
    note
  } = props.data;
  // ★ totalVolume/productCount 는 App.jsx에서 이미 fmt() 적용된 문자열 → 그대로 출력(이중 포맷 NaN 방지)

  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83C\uDFAF"), "\uC885\uD569 \uC694\uC57D"), /*#__PURE__*/React.createElement("div", {
    className: "grid4"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uC6D4\uAC04 \uAC80\uC0C9\uB7C9 ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705")), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, totalVolume, /*#__PURE__*/React.createElement("small", null, "\uD68C/\uC6D4"))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uB4F1\uB85D \uC0C1\uD488\uC218 ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705")), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, productCount, /*#__PURE__*/React.createElement("small", null, "\uAC1C"))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uACE8\uB4E0 \uD0A4\uC6CC\uB4DC ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705")), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, goldenCount, /*#__PURE__*/React.createElement("small", null, "\uAC1C \uBC1C\uACAC"))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uACBD\uC7C1\uAC15\uB3C4 ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705")), /*#__PURE__*/React.createElement("div", {
    className: "v",
    style: {
      fontSize: '22px'
    }
  }, compLevel || '-'))), note && /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, "\uD83D\uDCA1 ", note))));
};

;/* ===== js/components/CategoryAnalysisSection.jsx ===== */
window.CategoryAnalysisSection = function CategoryAnalysisSection(props) {
  if (!props?.data) return null;
  const {
    verdict,
    mainCategory,
    categories,
    categoryLevels
  } = props.data;
  if (!categories || categories.length === 0) return null;
  var gradients = ['linear-gradient(90deg, #4f46e5, #7c3aed)', 'linear-gradient(90deg, #7c3aed, #a78bfa)', 'linear-gradient(90deg, #a78bfa, #c4b5fd)', 'linear-gradient(90deg, #c4b5fd, #ddd6fe)', 'linear-gradient(90deg, #ddd6fe, #ede9fe)'];

  /* 레벨별 분포 차트 렌더링 */
  var renderLevelChart = function (title, items, color) {
    if (!items || items.length === 0) return null;
    return /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 200
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 700,
        color: '#0f172a',
        marginBottom: 12
      }
    }, title), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 10
      }
    }, items.map(function (item, idx) {
      return /*#__PURE__*/React.createElement("div", {
        key: idx
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          justifyContent: 'space-between',
          marginBottom: 4,
          alignItems: 'center'
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 12,
          fontWeight: 600,
          color: '#334155'
        }
      }, item.name), /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 11,
          color: '#64748b'
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          fontWeight: 700,
          color: color,
          marginRight: 3
        }
      }, item.count, "\uAC1C"), "(", item.ratio, "%)")), /*#__PURE__*/React.createElement("div", {
        style: {
          height: 6,
          borderRadius: 6,
          background: '#f1f5f9',
          overflow: 'hidden'
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          width: item.ratio + '%',
          height: '100%',
          borderRadius: 6,
          background: color,
          opacity: 1 - idx * 0.15,
          transition: 'width 0.8s ease'
        }
      })));
    })));
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDDC2\uFE0F"), "\uCE74\uD14C\uACE0\uB9AC \uB4F1\uB85D \uBD84\uC11D", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uC2E4\uCE21")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uC0C1\uC704 \uC0C1\uD488\uB4E4\uC758 \uCE74\uD14C\uACE0\uB9AC \uBD84\uD3EC\uB97C \uD30C\uC545\uD569\uB2C8\uB2E4"), verdict && /*#__PURE__*/React.createElement("div", {
    className: "note ok",
    style: {
      margin: '0 0 12px'
    }
  }, verdict), categoryLevels && (categoryLevels.large?.length > 0 || categoryLevels.medium?.length > 0 || categoryLevels.small?.length > 0) && /*#__PURE__*/React.createElement("div", {
    className: "sub-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "st"
  }, "\uB808\uBCA8\uBCC4 \uBD84\uD3EC (1\uD398\uC774\uC9C0 \uC0C1\uD488)"), categoryLevels.large && categoryLevels.large.length > 0 && /*#__PURE__*/React.createElement("div", null, categoryLevels.large.map(function (item, idx) {
    return /*#__PURE__*/React.createElement("div", {
      key: idx
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        margin: '6px 0'
      }
    }, /*#__PURE__*/React.createElement("b", null, "\uB300\uBD84\uB958"), " ", item.name, " ", item.ratio, "%"), /*#__PURE__*/React.createElement("div", {
      className: "track"
    }, /*#__PURE__*/React.createElement("i", {
      style: {
        width: item.ratio + '%'
      }
    })));
  })), categoryLevels.medium && categoryLevels.medium.length > 0 && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12.5,
      margin: '10px 0 6px'
    }
  }, /*#__PURE__*/React.createElement("b", null, "\uC911\uBD84\uB958"), " ", categoryLevels.medium.map(function (item, idx) {
    return item.name + ' ' + item.ratio + '%' + (idx < categoryLevels.medium.length - 1 ? ' · ' : '');
  }).join('')), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: categoryLevels.medium[0].ratio + '%'
    }
  }))), categoryLevels.small && categoryLevels.small.length > 0 && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12.5,
      margin: '10px 0 6px'
    }
  }, /*#__PURE__*/React.createElement("b", null, "\uC18C\uBD84\uB958"), " ", categoryLevels.small.map(function (item, idx) {
    return item.name + ' ' + item.ratio + '%' + (idx < categoryLevels.small.length - 1 ? ' · ' : '');
  }).join('')), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: categoryLevels.small[0].ratio + '%'
    }
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#fff',
      borderRadius: 16,
      padding: 24,
      border: '1px solid #e2e8f0',
      boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      fontWeight: 700,
      color: '#0f172a',
      marginBottom: 20
    }
  }, "\uCE74\uD14C\uACE0\uB9AC \uC804\uCCB4 \uACBD\uB85C \uBD84\uD3EC (\uC0C1\uC704 \uC0C1\uD488 \uAE30\uC900)"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 16
    }
  }, categories.map(function (item, idx) {
    var gradient = gradients[Math.min(idx, gradients.length - 1)];
    return /*#__PURE__*/React.createElement("div", {
      key: idx
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        marginBottom: 8,
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontWeight: 600,
        fontSize: 13,
        color: '#0f172a'
      }
    }, item.name), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: '#64748b'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontWeight: 700,
        color: '#4f46e5',
        marginRight: 4
      }
    }, item.count, "\uAC1C"), "(", item.ratio, "%)")), /*#__PURE__*/React.createElement("div", {
      style: {
        height: 10,
        borderRadius: 10,
        background: '#f1f5f9',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: item.ratio + '%',
        height: '100%',
        borderRadius: 10,
        background: gradient,
        transition: 'width 0.8s ease'
      }
    })));
  }))))));
};

;/* ===== js/components/KeywordTagSection.jsx ===== */
window.KeywordTagSection = function KeywordTagSection(props) {
  if (!props?.data) return null;
  const {
    topKeywords,
    totalFound
  } = props.data;
  if (!topKeywords || topKeywords.length === 0) return null;
  const maxVolume = Math.max.apply(null, topKeywords.map(function (kw) {
    return typeof kw.volume === 'number' ? kw.volume : 0;
  })) || 1;
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "section-title"
  }, /*#__PURE__*/React.createElement("span", {
    className: "icon",
    style: {
      background: 'linear-gradient(135deg, #eef2ff, #dbeafe)'
    }
  }, "\uD83C\uDFF7\uFE0F"), "\uD0A4\uC6CC\uB4DC & \uD0DC\uADF8 \uBD84\uC11D"), /*#__PURE__*/React.createElement("div", {
    className: "section-line"
  }), /*#__PURE__*/React.createElement("p", {
    className: "section-subtitle"
  }, "\uC0C1\uD488\uBA85\uC5D0\uC11C \uC790\uC8FC \uC4F0\uC774\uB294 \uD0A4\uC6CC\uB4DC\uB97C \uBD84\uC11D\uD569\uB2C8\uB2E4"), /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#fff',
      borderRadius: 16,
      padding: 24,
      border: '1px solid #e2e8f0',
      boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 700,
      color: '#0f172a'
    }
  }, "\uD83D\uDCAC \uC0C1\uD488\uBA85 \uC8FC\uC694 \uD0A4\uC6CC\uB4DC TOP ", Math.min(topKeywords.length, 15)), /*#__PURE__*/React.createElement("span", {
    style: {
      padding: '4px 12px',
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 700,
      background: 'linear-gradient(135deg, #eef2ff, #dbeafe)',
      color: '#4f46e5'
    }
  }, "\uCD1D ", fmt(totalFound), "\uAC1C \uBC1C\uACAC")), /*#__PURE__*/React.createElement("div", {
    className: "table-wrap",
    style: {
      maxHeight: 340,
      overflowY: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", null, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", {
    style: {
      background: 'linear-gradient(135deg, #4f46e5, #7c3aed)'
    }
  }, /*#__PURE__*/React.createElement("th", {
    style: {
      color: '#fff',
      fontWeight: 600,
      fontSize: 12
    }
  }, "#"), /*#__PURE__*/React.createElement("th", {
    style: {
      color: '#fff',
      fontWeight: 600,
      fontSize: 12
    }
  }, "\uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("th", {
    style: {
      color: '#fff',
      fontWeight: 600,
      fontSize: 12
    }
  }, "\uAC80\uC0C9\uB7C9"), /*#__PURE__*/React.createElement("th", {
    style: {
      color: '#fff',
      fontWeight: 600,
      fontSize: 12
    }
  }, "\uACBD\uC7C1\uB3C4"), /*#__PURE__*/React.createElement("th", {
    style: {
      color: '#fff',
      fontWeight: 600,
      fontSize: 12
    }
  }, "\uBE44\uC911"))), /*#__PURE__*/React.createElement("tbody", null, topKeywords.map(function (kw, idx) {
    var barPercent = typeof kw.volume === 'number' ? Math.round(kw.volume / maxVolume * 100) : 0;
    return /*#__PURE__*/React.createElement("tr", {
      key: idx,
      style: {
        background: idx % 2 === 0 ? '#fff' : '#f8fafc'
      }
    }, /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 28,
        height: 28,
        background: kw.isGolden ? 'linear-gradient(135deg, #f59e0b, #d97706)' : 'linear-gradient(135deg, #4f46e5, #7c3aed)',
        color: '#fff',
        borderRadius: '50%',
        fontSize: 11,
        fontWeight: 700
      }
    }, idx + 1)), /*#__PURE__*/React.createElement("td", {
      style: {
        fontWeight: 600,
        color: '#0f172a',
        fontSize: 13
      }
    }, kw.keyword, kw.isGolden && /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 6
      }
    }, "\uD83D\uDC51")), /*#__PURE__*/React.createElement("td", {
      style: {
        fontSize: 13,
        color: '#0f172a'
      }
    }, fmt(kw.volume)), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
      style: {
        padding: '4px 12px',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
        background: kw.comp === '낮음' ? '#ecfdf5' : kw.comp === '높음' ? '#fef2f2' : '#fffbeb',
        color: kw.comp === '낮음' ? '#10b981' : kw.comp === '높음' ? '#ef4444' : '#f59e0b'
      }
    }, kw.comp)), /*#__PURE__*/React.createElement("td", {
      style: {
        minWidth: 120
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        height: 8,
        borderRadius: 8,
        background: '#f1f5f9',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: barPercent + '%',
        height: '100%',
        borderRadius: 8,
        background: kw.isGolden ? 'linear-gradient(135deg, #f59e0b, #d97706)' : 'linear-gradient(135deg, #4f46e5, #7c3aed)',
        transition: 'width 0.3s ease'
      }
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: '#64748b',
        minWidth: 32,
        textAlign: 'right'
      }
    }, barPercent, "%"))));
  })))))));
};

;/* ===== js/components/SeoDetailSection.jsx ===== */
window.SeoDetailSection = function SeoDetailSection(props) {
  if (!props?.data) return null;
  const {
    relevance,
    trustworthy,
    popularity
  } = props.data;
  if (!relevance || !trustworthy || !popularity) return null;
  var categories = [{
    title: '적합도',
    icon: '🎯',
    data: relevance,
    gradient: 'linear-gradient(135deg, #fef3c7, #fde68a)',
    borderColor: '#fcd34d',
    color: '#92400e',
    bg: '#fffbeb'
  }, {
    title: '신뢰도',
    icon: '🛡️',
    data: trustworthy,
    gradient: 'linear-gradient(135deg, #dbeafe, #bfdbfe)',
    borderColor: '#93c5fd',
    color: '#1e40af',
    bg: '#eff6ff'
  }, {
    title: '인기도',
    icon: '🔥',
    data: popularity,
    gradient: 'linear-gradient(135deg, #fce7f3, #fbcfe8)',
    borderColor: '#f472b6',
    color: '#9d174d',
    bg: '#fdf2f8'
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDEE1\uFE0F"), "\u2461 SEO \uC801\uD569\uB3C4 \xB7 \uC2E0\uB8B0\uB3C4 \xB7 \uC778\uAE30\uB3C4", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "\u2248 \uCD94\uC815")), /*#__PURE__*/React.createElement("div", {
    className: "grid3"
  }, categories.map(function (cat, catIdx) {
    return /*#__PURE__*/React.createElement("div", {
      key: catIdx,
      className: "sub-card"
    }, /*#__PURE__*/React.createElement("div", {
      className: "st"
    }, cat.icon, " ", cat.title, /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 'auto',
        fontWeight: 900
      }
    }, cat.data.score)), cat.data.items && cat.data.items.map(function (item, idx) {
      return /*#__PURE__*/React.createElement("div", {
        key: idx,
        className: "check"
      }, item.pass ? /*#__PURE__*/React.createElement("span", {
        className: "y"
      }, "\u2714") : /*#__PURE__*/React.createElement("span", {
        className: "n"
      }, "\u2718"), ' ', item.label);
    }));
  })))));
};

;/* ===== js/components/ProductNameOptSection.jsx ===== */
window.ProductNameOptSection = function ProductNameOptSection(props) {
  if (!props?.data) return null;
  const {
    currentName,
    issues,
    suggestedName,
    marketerComment
  } = props.data;
  if (!currentName) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\u270F\uFE0F"), "\uC0C1\uD488\uBA85 SEO \uCD5C\uC801\uD654 ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ai"
  }, "AI")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--sub)'
    }
  }, "\uD604\uC7AC"), /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("b", null, currentName)), issues && issues.map((item, idx) => /*#__PURE__*/React.createElement("div", {
    key: idx,
    className: "check"
  }, /*#__PURE__*/React.createElement("span", {
    className: item.pass ? 'y' : 'n'
  }, item.pass ? '✔' : '✘'), ' ', item.text)), suggestedName && /*#__PURE__*/React.createElement("div", {
    className: "note",
    style: {
      borderLeftColor: '#ec4899'
    }
  }, /*#__PURE__*/React.createElement("b", null, "\u270F\uFE0F \uC81C\uC548"), /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("b", null, suggestedName), marketerComment && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("br", null), marketerComment)))));
};

;/* ===== js/components/ReviewAnalysisSection.jsx ===== */
window.ReviewAnalysisSection = function ReviewAnalysisSection(props) {
  if (!props?.data) return null;
  const {
    reviewCount,
    rating,
    wishCount,
    strategy
  } = props.data;
  if (!reviewCount || !rating || !wishCount) return null;

  // HTML에서 추출된 실제 리뷰 데이터 (있으면 내 상품 값으로 사용)
  const html = props.htmlReviewData || null;
  const hasHtmlData = html && (html.reviewCount != null || html.rating != null || html.wishCount != null);
  var fmt = function (n) {
    return n != null ? Number(n).toLocaleString('ko-KR') : '-';
  };
  var num = function (v) {
    return v == null || isNaN(Number(v)) ? 0 : Number(v);
  };
  var mineReview = hasHtmlData && html && html.reviewCount != null ? html.reviewCount : reviewCount.adv;
  var top5Review = reviewCount.top5;

  // 시안 톤 노트: '부족 지적 → 해결방안' 논리 (광고주 보고서, 실데이터 기반)
  var noteText;
  if (top5Review && mineReview < top5Review) {
    noteText = '리뷰 ' + fmt(mineReview) + '건(상위5 평균 ' + fmt(top5Review) + '건 대비 부족) — 구매 전환의 가장 큰 병목. 체험단으로 단기 확보 필요.';
  } else if (reviewCount.avg && mineReview < reviewCount.avg) {
    noteText = '리뷰 ' + fmt(mineReview) + '건(경쟁 평균 ' + fmt(reviewCount.avg) + '건 대비 부족) — 구매 전환의 핵심 지표. 체험단으로 단기 확보 필요.';
  } else {
    noteText = '리뷰 ' + fmt(mineReview) + '건 — 경쟁 대비 양호. 평점·재구매 관리로 전환율을 끌어올리세요.';
  }
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\u2B50"), "\uB9AC\uBDF0 & \uCC1C \uBD84\uC11D", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uC2E4\uCE21")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uAD11\uACE0\uC8FC \uC0C1\uD488 vs \uACBD\uC7C1 \uD3C9\uADE0 vs \uC0C1\uC704 5\uAC1C \uBE44\uAD50"), function () {
    var C = window.CHART_COLORS || {};
    var mineRating = hasHtmlData && html && html.rating != null ? html.rating : rating.adv;
    var mineWish = hasHtmlData && html && html.wishCount != null ? html.wishCount : wishCount.adv;
    var mine = [num(mineReview), num(mineRating) * 100, num(mineWish)];
    var avg = [num(reviewCount.avg), num(rating.avg) * 100, num(wishCount.avg)];
    var top5 = [num(reviewCount.top5), num(rating.top5) * 100, num(wishCount.top5)];
    var anyVal = mine.concat(avg, top5).some(function (v) {
      return v > 0;
    });
    if (!anyVal) return null;
    var fmtTip = function (ctx) {
      var raw = ctx.parsed.y;
      var label = ctx.dataset.label + ': ';
      if (ctx.dataIndex === 1) return label + (raw / 100).toFixed(1) + '점';
      return label + (window.chartComma ? window.chartComma(raw) : raw);
    };
    return /*#__PURE__*/React.createElement("div", {
      className: "chartbox"
    }, /*#__PURE__*/React.createElement(ChartCanvas, {
      type: "bar",
      height: 280,
      data: {
        labels: ['리뷰 수', '평점(×100)', '찜 수'],
        datasets: [{
          label: '내 상품',
          data: mine,
          backgroundColor: '#ec4899',
          borderRadius: 5
        }, {
          label: '경쟁 평균',
          data: avg,
          backgroundColor: '#94a3b8',
          borderRadius: 5
        }, {
          label: '상위 5',
          data: top5,
          backgroundColor: C.IND || '#4f46e5',
          borderRadius: 5
        }]
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom'
          },
          tooltip: {
            callbacks: {
              label: fmtTip
            }
          }
        },
        scales: {
          y: {
            type: 'logarithmic',
            ticks: {
              callback: function (v) {
                return window.chartComma ? window.chartComma(v) : v;
              }
            }
          }
        }
      }
    }));
  }(), noteText && /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, noteText))));
};

;/* ===== js/components/ReviewTextAnalysisSection.jsx ===== */
/* ReviewTextAnalysisSection — HTML에서 추출한 구매자 리뷰 텍스트 분석 */
window.ReviewTextAnalysisSection = function ReviewTextAnalysisSection(props) {
  var React = window.React;
  var useState = React.useState;
  var data = props.data; // reviewData.reviewTextAnalysis
  var reviews = props.reviews; // reviewData.reviews (개별 리뷰 배열)
  var totalReviewCount = props.totalReviewCount; // 전체 리뷰 수 (reviewData.reviewCount)

  if (!data || !reviews || reviews.length === 0) return null;
  var showAllState = useState(false);
  var showAll = showAllState[0];
  var setShowAll = showAllState[1];
  var fmt = function (n) {
    return n != null ? Number(n).toLocaleString('ko-KR') : '-';
  };
  var stars = function (n) {
    var full = Math.floor(n);
    var s = '';
    for (var i = 0; i < full; i++) s += '★';
    for (var j = full; j < 5; j++) s += '☆';
    return s;
  };
  var sentimentLabel = {
    positive: '긍정',
    negative: '부정',
    neutral: '중립'
  };
  var sentimentStyle = {
    positive: {
      background: '#dcfce7',
      color: '#166534'
    },
    negative: {
      background: '#fee2e2',
      color: '#991b1b'
    },
    neutral: {
      background: '#f1f5f9',
      color: '#64748b'
    }
  };
  var tagColors = ['linear-gradient(90deg, #7c3aed, #a78bfa)', 'linear-gradient(90deg, #3b82f6, #93c5fd)', 'linear-gradient(90deg, #10b981, #6ee7b7)', 'linear-gradient(90deg, #f59e0b, #fcd34d)', 'linear-gradient(90deg, #ec4899, #f9a8d4)'];
  var kwTabState = useState('pos');
  var kwTab = kwTabState[0];
  var setKwTab = kwTabState[1];
  var displayedReviews = showAll ? reviews : reviews.slice(0, 3);
  var remainingCount = reviews.length - 3;
  return React.createElement('div', {
    className: 'section fade-in'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    className: 'card',
    style: {
      padding: '20px 22px'
    }
  }, /* 제목 */
  React.createElement('h3', {
    className: 'rt-h3'
  }, React.createElement('span', {
    className: 'rt-hic'
  }, '💬'), '리뷰 텍스트 분석', React.createElement('span', {
    className: 'badge b-est'
  }, '≈ 추정')), React.createElement('div', {
    className: 'rt-desc'
  }, '상세페이지 HTML에서 추출한 구매자 리뷰 분석 결과'), /* 1. 요약 KPI 4개 (.grid4 + .kpi) */
  React.createElement('div', {
    className: 'grid4',
    style: {
      marginBottom: 10
    }
  }, /* 추출된 리뷰 */
  React.createElement('div', {
    className: 'kpi'
  }, React.createElement('div', {
    className: 'k'
  }, '추출 리뷰'), React.createElement('div', {
    className: 'v',
    style: {
      fontSize: 20
    }
  }, fmt(data.totalExtracted), React.createElement('small', null, '건')), totalReviewCount ? React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      marginTop: 4
    }
  }, '전체 ' + fmt(totalReviewCount) + '건 중') : null), /* 평균 별점 */
  React.createElement('div', {
    className: 'kpi'
  }, React.createElement('div', {
    className: 'k'
  }, '평균 별점'), React.createElement('div', {
    className: 'v',
    style: {
      fontSize: 20
    }
  }, data.avgRating, React.createElement('small', null, '★'))), /* 긍정 비율 */
  React.createElement('div', {
    className: 'kpi'
  }, React.createElement('div', {
    className: 'k'
  }, '긍정 비율'), React.createElement('div', {
    className: 'v',
    style: {
      fontSize: 20,
      color: 'var(--ok)'
    }
  }, data.sentiment.positiveRatio, React.createElement('small', null, '%'))), /* 평균 글자수 */
  React.createElement('div', {
    className: 'kpi'
  }, React.createElement('div', {
    className: 'k'
  }, '평균 글자수'), React.createElement('div', {
    className: 'v',
    style: {
      fontSize: 20
    }
  }, data.avgChars, React.createElement('small', null, '자')))), /* 2. 핵심 키워드 분석 — 긍정/부정 탭 (.pill-tabs) */
  data.positiveKeywords.length > 0 || data.negativeKeywords.length > 0 ? React.createElement('div', {
    style: {
      marginBottom: 20
    }
  }, /* pill-tabs 탭 버튼 */
  React.createElement('div', {
    className: 'pill-tabs'
  }, React.createElement('button', {
    className: kwTab === 'pos' ? 'on' : '',
    onClick: function () {
      setKwTab('pos');
    }
  }, '긍정 키워드'), React.createElement('button', {
    className: kwTab === 'neg' ? 'on' : '',
    onClick: function () {
      setKwTab('neg');
    }
  }, '부정 키워드')), /* 긍정 키워드 칩 */
  kwTab === 'pos' ? React.createElement('div', null, data.positiveKeywords.length > 0 ? data.positiveKeywords.map(function (kw, i) {
    return React.createElement('span', {
      key: 'pos-' + i,
      className: 'tag2'
    }, kw.keyword + ' (' + kw.count + ')');
  }) : React.createElement('div', {
    style: {
      fontSize: 13,
      color: '#94a3b8',
      padding: '12px 0'
    }
  }, '긍정 키워드가 발견되지 않았습니다')) : /* 부정 키워드 칩 */
  React.createElement('div', null, data.negativeKeywords.length > 0 ? data.negativeKeywords.map(function (kw, i) {
    return React.createElement('span', {
      key: 'neg-' + i,
      className: 'tag2',
      style: {
        background: '#fee2e2',
        color: '#b91c1c'
      }
    }, kw.keyword + ' (' + kw.count + ')');
  }) : React.createElement('div', {
    style: {
      fontSize: 13,
      color: '#94a3b8',
      padding: '12px 0'
    }
  }, '부정 키워드가 발견되지 않았습니다'))) : null, /* 3. 구매자 선택 태그 분석 */
  data.tagStats && data.tagStats.length > 0 ? React.createElement('div', {
    style: {
      marginBottom: 20
    }
  }, React.createElement('div', {
    style: {
      fontSize: 14,
      fontWeight: 700,
      color: '#1e293b',
      marginBottom: 14,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, React.createElement('span', null, '🏷️'), '구매자 선택 태그 분석'), React.createElement('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, data.tagStats.map(function (ts, i) {
    var pct = Math.round(ts.count / data.totalExtracted * 100);
    return React.createElement('div', {
      key: 'tag-' + i,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 12
      }
    }, React.createElement('div', {
      style: {
        width: 80,
        fontSize: 13,
        fontWeight: 600,
        color: '#475569',
        textAlign: 'right',
        flexShrink: 0
      }
    }, ts.tag), React.createElement('div', {
      style: {
        flex: 1,
        height: 28,
        background: '#f1f5f9',
        borderRadius: 8,
        overflow: 'hidden',
        position: 'relative'
      }
    }, React.createElement('div', {
      style: {
        height: '100%',
        width: pct + '%',
        background: tagColors[i % tagColors.length],
        borderRadius: 8,
        display: 'flex',
        alignItems: 'center',
        paddingLeft: 12,
        fontSize: 11,
        fontWeight: 700,
        color: '#fff',
        minWidth: 40
      }
    }, ts.count + '건')), React.createElement('div', {
      style: {
        fontSize: 12,
        fontWeight: 600,
        color: '#64748b',
        width: 50,
        textAlign: 'left'
      }
    }, pct + '%'));
  }))) : null, /* 4. AI 전략 인사이트 (.sub-card + .st) */
  data.insights && data.insights.length > 0 ? React.createElement('div', {
    className: 'sub-card'
  }, React.createElement('div', {
    className: 'st'
  }, '🤖 AI 전략 인사이트'), React.createElement('div', {
    style: {
      fontSize: 12.5,
      color: '#475569'
    }
  }, data.insights.map(function (insight, i) {
    return React.createElement('div', {
      key: 'insight-' + i,
      style: {
        lineHeight: 1.8,
        paddingLeft: 20,
        position: 'relative'
      }
    }, React.createElement('span', {
      style: {
        position: 'absolute',
        left: 0,
        color: '#6366f1',
        fontWeight: 700
      }
    }, '→'), insight);
  }))) : null, /* 5. 리뷰 목록 */
  React.createElement('div', null, React.createElement('div', {
    style: {
      fontSize: 14,
      fontWeight: 700,
      color: '#1e293b',
      marginBottom: 14,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, React.createElement('span', null, '📋'), '추출된 리뷰 목록', React.createElement('span', {
    style: {
      fontSize: 11,
      fontWeight: 500,
      color: '#94a3b8',
      marginLeft: 4
    }
  }, '(HTML에서 추출된 ' + reviews.length + '건)')), React.createElement('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 12
    }
  }, displayedReviews.map(function (review, i) {
    var sentStyle = sentimentStyle[review.sentiment] || sentimentStyle.neutral;
    return React.createElement('div', {
      key: 'review-' + i,
      style: {
        background: '#f8fafc',
        borderRadius: 12,
        padding: '16px 20px',
        border: '1px solid #e2e8f0',
        transition: 'all 0.2s'
      }
    }, /* 헤더: 별점 + 태그 + 감성 */
    React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 8,
        flexWrap: 'wrap'
      }
    }, React.createElement('span', {
      style: {
        color: '#f59e0b',
        fontSize: 13,
        letterSpacing: 1
      }
    }, stars(review.rating)), review.tags && review.tags.map(function (tag, j) {
      return React.createElement('span', {
        key: 'tag-' + j,
        style: {
          fontSize: 10,
          fontWeight: 600,
          padding: '2px 8px',
          borderRadius: 999,
          background: '#ede9fe',
          color: '#6d28d9'
        }
      }, tag);
    }), React.createElement('span', {
      style: Object.assign({
        marginLeft: 'auto',
        fontSize: 10,
        fontWeight: 700,
        padding: '2px 8px',
        borderRadius: 999
      }, sentStyle)
    }, sentimentLabel[review.sentiment] || '중립')), /* 리뷰 본문 */
    React.createElement('div', {
      style: {
        fontSize: 13,
        color: '#334155',
        lineHeight: 1.7
      }
    }, review.text));
  }), /* 더 보기 / 접기 버튼 */
  reviews.length > 3 ? React.createElement('button', {
    onClick: function () {
      setShowAll(!showAll);
    },
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      width: '100%',
      padding: 10,
      marginTop: 4,
      background: '#f8fafc',
      border: '1px dashed #cbd5e1',
      borderRadius: 10,
      fontSize: 13,
      fontWeight: 600,
      color: '#64748b',
      cursor: 'pointer'
    }
  }, showAll ? '▲ 접기' : '▼ 나머지 ' + remainingCount + '건 더 보기') : null)))));
};

;/* ===== js/components/DetailPageQualitySection.jsx ===== */
window.DetailPageQualitySection = function DetailPageQualitySection(props) {
  if (!props?.data) return null;
  const {
    totalScore,
    grade,
    gradeColor,
    scoreBars,
    checklist,
    comment
  } = props.data;
  if (totalScore === undefined) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDCC4"), "\u2462 \uC0C1\uC138\uD398\uC774\uC9C0 \uD488\uC9C8 \uC810\uC218", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "\u2248 \uCD94\uC815")), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      marginBottom: '8px'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: '30px',
      fontWeight: '900'
    }
  }, totalScore), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--sub)'
    }
  }, "/100", grade ? ' · ' + String(grade).replace(/등급$/, '') + '등급' : '')), scoreBars && scoreBars.map((bar, idx) => {
    const percent = bar.maxScore ? Math.round(bar.score / bar.maxScore * 100) : bar.percent || 0;
    return /*#__PURE__*/React.createElement("div", {
      key: idx,
      className: "scorebar"
    }, /*#__PURE__*/React.createElement("div", {
      className: "lbl"
    }, /*#__PURE__*/React.createElement("b", null, bar.label)), /*#__PURE__*/React.createElement("div", {
      className: "track"
    }, /*#__PURE__*/React.createElement("i", {
      style: {
        width: percent + '%'
      }
    })));
  }), checklist && checklist.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "sub-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "st"
  }, "\uD3C9\uAC00 \uCCB4\uD06C\uB9AC\uC2A4\uD2B8"), checklist.map((category, cidx) => category.items && category.items.map((item, iidx) => /*#__PURE__*/React.createElement("div", {
    key: cidx + '-' + iidx,
    className: "check"
  }, /*#__PURE__*/React.createElement("span", {
    className: item.pass ? 'y' : 'n'
  }, item.pass ? '✔' : '✘'), " ", item.text)))), comment && /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, comment))));
};

;/* ===== js/components/HtmlDetailAnalysisSection.jsx ===== */
/* HtmlDetailAnalysisSection — 상세페이지 HTML 분석 결과 표시 (v5) */
/* SearchBar에서 입력된 HTML → /seo/detail-page API 결과를 시각화 */
window.HtmlDetailAnalysisSection = function HtmlDetailAnalysisSection({
  data
}) {
  if (!data || !data.scores) return null;
  const getScoreColor = s => s >= 70 ? '#10b981' : s >= 40 ? '#f59e0b' : '#ef4444';
  const getScoreLabel = s => s >= 70 ? '우수' : s >= 40 ? '보통' : '미흡';
  const priorityLabel = p => p === 'high' ? '긴급' : p === 'medium' ? '권장' : '선택';
  const ScoreBar = ({
    label,
    score,
    weight
  }) => /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, label), /*#__PURE__*/React.createElement("span", {
    className: "w"
  }, weight)), /*#__PURE__*/React.createElement("div", {
    className: "track"
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: score + '%'
    }
  })));
  const total = data.scores.total;
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDDBC\uFE0F"), "\u2463 \uC0C1\uC138\uD398\uC774\uC9C0 HTML \uBD84\uC11D", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "\u2248 \uCD94\uC815")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uC2E4\uC81C HTML\uC5D0\uC11C \uCD94\uCD9C\uD55C \uB370\uC774\uD130 \uAE30\uBC18 \uC815\uBC00 \uC9C4\uB2E8"), /*#__PURE__*/React.createElement("div", {
    className: "grid2",
    style: {
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      padding: '6px 0'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      width: 180,
      height: 180
    }
  }, /*#__PURE__*/React.createElement(ChartCanvas, {
    type: "doughnut",
    height: 180,
    style: {
      height: 180,
      width: 180
    },
    data: {
      labels: ['점수', '잔여'],
      datasets: [{
        data: [total, Math.max(0, 100 - total)],
        backgroundColor: [getScoreColor(total), '#f1f5f9'],
        borderWidth: 0
      }]
    },
    options: {
      maintainAspectRatio: false,
      cutout: '78%',
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          enabled: false
        }
      }
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 30,
      fontWeight: 900,
      color: getScoreColor(total),
      lineHeight: 1.1
    }
  }, total), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#64748b',
      marginTop: 2
    }
  }, "/100 \xB7 ", getScoreLabel(total))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(ScoreBar, {
    label: "\uC774\uBBF8\uC9C0",
    score: data.scores.images,
    weight: "30%"
  }), /*#__PURE__*/React.createElement(ScoreBar, {
    label: "\uD14D\uC2A4\uD2B8",
    score: data.scores.text,
    weight: "20%"
  }), /*#__PURE__*/React.createElement(ScoreBar, {
    label: "\uB3D9\uC601\uC0C1",
    score: data.scores.video,
    weight: "15%"
  }), /*#__PURE__*/React.createElement(ScoreBar, {
    label: "\uC815\uBCF4 \uC644\uC131\uB3C4",
    score: data.scores.info,
    weight: "20%"
  }), /*#__PURE__*/React.createElement(ScoreBar, {
    label: "\uC2E0\uB8B0 \uC694\uC18C",
    score: data.scores.trust,
    weight: "15%"
  }))), data.metrics && /*#__PURE__*/React.createElement("div", {
    className: "grid4",
    style: {
      marginTop: 10
    }
  }, [{
    label: '상품 이미지',
    num: data.metrics.total_images,
    unit: '장',
    good: data.metrics.total_images >= 10
  }, {
    label: '텍스트 길이',
    num: data.metrics.text_length > 1000 ? (data.metrics.text_length / 1000).toFixed(1) + 'K' : data.metrics.text_length,
    unit: '자',
    good: data.metrics.text_length >= 500
  }, {
    label: '동영상',
    num: data.metrics.video_count,
    unit: '개',
    good: data.metrics.video_count > 0
  }, {
    label: '페이지 크기',
    num: data.metrics.html_size_kb,
    unit: 'KB',
    good: data.metrics.html_size_kb >= 50
  }].map((item, i) => /*#__PURE__*/React.createElement("div", {
    key: 'dp-metric-' + i,
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, item.label), /*#__PURE__*/React.createElement("div", {
    className: "v",
    style: {
      color: item.good ? undefined : 'var(--red)'
    }
  }, item.num, /*#__PURE__*/React.createElement("small", null, item.unit))))), data.metrics && (() => {
    const checkItems = [{
      label: '배송 정보 (무료배송/당일출고)',
      checked: data.metrics.has_delivery_info
    }, {
      label: '교환/반품/환불 정책',
      checked: data.metrics.has_return_info
    }, {
      label: '사은품/증정 혜택',
      checked: data.metrics.has_gift_info
    }, {
      label: '인증/수상/특허 표시',
      checked: data.metrics.has_certification
    }, {
      label: '구매 후기/리뷰 섹션',
      checked: data.metrics.has_review_section
    }, {
      label: '스펙/사양 테이블',
      checked: data.metrics.has_spec_table
    }];
    const half = Math.ceil(checkItems.length / 2);
    const cols = [checkItems.slice(0, half), checkItems.slice(half)];
    return /*#__PURE__*/React.createElement("div", {
      className: "sub-card"
    }, /*#__PURE__*/React.createElement("div", {
      className: "st"
    }, "\uD544\uC218 \uD56D\uBAA9 \uCCB4\uD06C\uB9AC\uC2A4\uD2B8"), /*#__PURE__*/React.createElement("div", {
      className: "grid2"
    }, cols.map((col, ci) => /*#__PURE__*/React.createElement("div", {
      key: 'dp-check-col-' + ci
    }, col.map((item, i) => /*#__PURE__*/React.createElement("div", {
      key: 'dp-check-' + ci + '-' + i,
      className: "check"
    }, /*#__PURE__*/React.createElement("span", {
      className: item.checked ? 'y' : 'n'
    }, item.checked ? '✔' : '✘'), " ", item.label))))));
  })(), data.suggestions && data.suggestions.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "note est"
  }, /*#__PURE__*/React.createElement("b", null, "\uAC1C\uC120 \uC81C\uC548"), data.suggestions.map((s, i) => /*#__PURE__*/React.createElement("span", {
    key: 'dp-sug-' + i
  }, ' · ', /*#__PURE__*/React.createElement("span", {
    className: 'sev ' + (s.priority === 'high' ? 'high' : s.priority === 'medium' ? 'med' : 'low')
  }, priorityLabel(s.priority)), ' ', s.area ? s.area + ' — ' : '', s.text))))));
};

;/* ===== js/components/SalesEstimationSection.jsx ===== */
/* SalesEstimationSection — 판매량 추정 & 성장 시뮬레이션 (v5) */
window.SalesEstimationSection = function SalesEstimationSection(props) {
  if (!props?.data) return null;
  const {
    avgPrice,
    monthlySearches,
    estimatedCTR,
    top10Card,
    page1Card,
    page2Card
  } = props.data;
  if (!top10Card || !page1Card || !page2Card) return null;
  var C = window.CHART_COLORS || {};
  /* 순위별 예상 월 판매량 차트 데이터 */
  var salesBars = [{
    label: '1위',
    val: Number(top10Card.rank1Sales) || 0
  }, {
    label: '5위',
    val: Number(top10Card.rank5Sales) || 0
  }, {
    label: '10위',
    val: Number(top10Card.rank10Sales) || 0
  }];
  var hasSalesChart = salesBars.some(function (b) {
    return b.val > 0;
  });

  /* v5 카드 스타일 */
  var v5Card = {
    borderRadius: 16,
    background: '#fff',
    border: '1px solid #e2e8f0',
    boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
  };
  var v5MetricRow = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '10px 0',
    borderBottom: '1px solid #f1f5f9'
  };
  var v5MetricRowLast = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '10px 0'
  };
  var v5MetricLabel = {
    fontSize: 12,
    color: '#64748b',
    fontWeight: 500
  };
  var v5TotalRow = {
    background: '#f8fafc',
    borderRadius: 10,
    padding: '14px 16px',
    marginTop: 12,
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center'
  };
  var v5TotalLabel = {
    fontSize: 12,
    fontWeight: 700,
    color: '#64748b'
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDCE6"), "\uD310\uB9E4\uB7C9 \uCD94\uC815 & \uC131\uC7A5 \uC2DC\uBBAC\uB808\uC774\uC158", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "\u2248 \uCD94\uC815")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uC21C\uC704\uBCC4 \uC608\uC0C1 \uD310\uB9E4\uB7C9\uACFC \uB9E4\uCD9C \uC131\uC7A5 \uC2DC\uB098\uB9AC\uC624"), /*#__PURE__*/React.createElement("div", {
    className: "grid3",
    style: {
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uD3C9\uADE0 \uC0C1\uD488 \uB2E8\uAC00"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, avgPrice)), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uC6D4\uAC04 \uAC80\uC0C9\uB7C9"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, monthlySearches)), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uC608\uC0C1 \uC804\uD658\uC728"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, estimatedCTR))), props.reviewCount != null && props.reviewCount > 0 && function () {
    var rc = props.reviewCount;
    var rate = 0.116; // 식품 평균 리뷰 작성률
    var cumSales = Math.round(rc / rate);
    var monthly = Math.round(cumSales / 12); // 운영 12개월 가정
    return /*#__PURE__*/React.createElement("div", {
      className: "note ok",
      style: {
        marginTop: 0,
        marginBottom: 20
      }
    }, /*#__PURE__*/React.createElement("b", null, "\uD83E\uDDFE \uB9AC\uBDF0 \uAE30\uBC18 \uCD94\uC815 (\uB354 \uC815\uD655)"), " \u2014 \uC2E4\uC81C \uB204\uC801 \uB9AC\uBDF0 ", /*#__PURE__*/React.createElement("b", null, fmt(rc), "\uAC74"), " \uAE30\uBC18. \uCD94\uC815 \uB204\uC801 \uD310\uB9E4 ", /*#__PURE__*/React.createElement("b", null, "~", fmt(cumSales), "\uAC74"), ", \uC6D4 \uD658\uC0B0 ", /*#__PURE__*/React.createElement("b", null, "~", fmt(monthly), "\uAC74"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#64748b'
      }
    }, " (\uC791\uC131\uB960 11.6% \xB7 \uC6B4\uC601 12\uAC1C\uC6D4 \uAC00\uC815). \uC544\uB798 \uC21C\uC704 \uAE30\uBC18 \uC2DC\uB098\uB9AC\uC624\uB294 \uCC38\uACE0\uC6A9\uC785\uB2C8\uB2E4."));
  }(), hasSalesChart && /*#__PURE__*/React.createElement("div", {
    className: "chartbox",
    style: {
      marginBottom: 20
    }
  }, /*#__PURE__*/React.createElement(ChartCanvas, {
    type: "bar",
    height: 220,
    data: {
      labels: salesBars.map(function (b) {
        return b.label;
      }),
      datasets: [{
        label: '예상 월 판매(건)',
        data: salesBars.map(function (b) {
          return b.val;
        }),
        backgroundColor: [C.OK || '#16a34a', C.IND || '#4f46e5', '#cbd5e1'],
        borderRadius: 6
      }]
    },
    options: {
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              return (window.chartComma ? window.chartComma(ctx.parsed.y) : ctx.parsed.y) + '건/월';
            }
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            callback: function (v) {
              return window.chartComma ? window.chartComma(v) : v;
            }
          }
        }
      }
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3, 1fr)',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      ...v5Card,
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '16px 20px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      background: 'linear-gradient(135deg, #f59e0b, #d97706)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      fontWeight: 700,
      color: '#fff'
    }
  }, "\uD83C\uDFC6 TOP 10 (1~10\uC704)"), /*#__PURE__*/React.createElement("span", {
    style: {
      padding: '4px 12px',
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 700,
      background: 'rgba(255,255,255,0.25)',
      color: '#fff'
    }
  }, "\uD575\uC2EC \uAD6C\uAC04")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "1\uC704 \uC608\uC0C1 \uD310\uB9E4"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#d97706'
    }
  }, fmt(top10Card.rank1Sales), "\uAC74")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "5\uC704 \uC608\uC0C1 \uD310\uB9E4"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#d97706'
    }
  }, fmt(top10Card.rank5Sales), "\uAC74")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "10\uC704 \uC608\uC0C1 \uD310\uB9E4"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#d97706'
    }
  }, fmt(top10Card.rank10Sales), "\uAC74")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "1\uC704 \uC608\uC0C1 \uB9E4\uCD9C"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#d97706'
    }
  }, top10Card.rank1Revenue)), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRowLast
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "10\uC704 \uC608\uC0C1 \uB9E4\uCD9C"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#d97706'
    }
  }, top10Card.rank10Revenue)), /*#__PURE__*/React.createElement("div", {
    style: v5TotalRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5TotalLabel
  }, "TOP10 \uD569\uC0B0 \uB9E4\uCD9C"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 15,
      fontWeight: 800,
      color: '#d97706'
    }
  }, top10Card.totalRevenue)))), /*#__PURE__*/React.createElement("div", {
    style: {
      ...v5Card,
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '16px 20px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      background: 'linear-gradient(135deg, #4f46e5, #7c3aed)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      fontWeight: 700,
      color: '#fff'
    }
  }, "\uD83D\uDCC4 1\uD398\uC774\uC9C0 (1~40\uC704)"), /*#__PURE__*/React.createElement("span", {
    style: {
      padding: '4px 12px',
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 700,
      background: 'rgba(255,255,255,0.25)',
      color: '#fff'
    }
  }, "1\uD398\uC774\uC9C0")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "\uD3C9\uADE0 \uD310\uB9E4\uB7C9"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#4f46e5'
    }
  }, fmt(page1Card.avgSales), "\uAC74/\uC6D4")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "\uCD1D \uC608\uC0C1 \uD310\uB9E4"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#4f46e5'
    }
  }, fmt(page1Card.totalSales), "\uAC74/\uC6D4")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "\uCD5C\uACE0 \uB9E4\uCD9C (1\uC704)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#4f46e5'
    }
  }, page1Card.maxRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "\uCD5C\uC800 \uB9E4\uCD9C (40\uC704)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#4f46e5'
    }
  }, page1Card.minRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRowLast
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "\uD3C9\uADE0 \uB9E4\uCD9C"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#4f46e5'
    }
  }, page1Card.avgRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5TotalRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5TotalLabel
  }, "1\uD398\uC774\uC9C0 \uD569\uC0B0 \uB9E4\uCD9C"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 15,
      fontWeight: 800,
      color: '#4f46e5'
    }
  }, page1Card.totalRevenue)))), /*#__PURE__*/React.createElement("div", {
    style: {
      ...v5Card,
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '16px 20px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      background: 'linear-gradient(135deg, #64748b, #475569)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      fontWeight: 700,
      color: '#fff'
    }
  }, "\uD83D\uDCC4 2\uD398\uC774\uC9C0 (41~80\uC704)"), /*#__PURE__*/React.createElement("span", {
    style: {
      padding: '4px 12px',
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 700,
      background: 'rgba(255,255,255,0.25)',
      color: '#fff'
    }
  }, "2\uD398\uC774\uC9C0")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "\uD3C9\uADE0 \uD310\uB9E4\uB7C9"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#475569'
    }
  }, fmt(page2Card.avgSales), "\uAC74/\uC6D4")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "\uCD1D \uC608\uC0C1 \uD310\uB9E4"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#475569'
    }
  }, fmt(page2Card.totalSales), "\uAC74/\uC6D4")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "\uCD5C\uACE0 \uB9E4\uCD9C (41\uC704)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#475569'
    }
  }, page2Card.maxRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "\uCD5C\uC800 \uB9E4\uCD9C (80\uC704)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#475569'
    }
  }, page2Card.minRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRowLast
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "\uD3C9\uADE0 \uB9E4\uCD9C"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#475569'
    }
  }, page2Card.avgRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5TotalRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5TotalLabel
  }, "2\uD398\uC774\uC9C0 \uD569\uC0B0 \uB9E4\uCD9C"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 15,
      fontWeight: 800,
      color: '#475569'
    }
  }, page2Card.totalRevenue))))), /*#__PURE__*/React.createElement("div", {
    className: "note est"
  }, "\u26A0\uFE0F \uC21C\uC704\uBCC4 \uD074\uB9AD\uB960(CTR)\uC744 \uAE30\uBC18\uC73C\uB85C \uCD94\uC815\uD55C \uAC12\uC774\uBA70, \uC2E4\uC81C \uD310\uB9E4\uB7C9\uC740 \uC0C1\uD488 \uACBD\uC7C1\uB825, \uB9AC\uBDF0, \uAC00\uACA9 \uB4F1\uC5D0 \uB530\uB77C \uB2EC\uB77C\uC9C8 \uC218 \uC788\uC2B5\uB2C8\uB2E4."), props.reviewCount != null && props.reviewCount > 0 && props.productPrice > 0 && function () {
    var rc = props.reviewCount;
    var price = props.productPrice;
    var reviewRates = [{
      label: '보수(작성률 5%)',
      rate: 0.05
    }, {
      label: '평균(11.6%)',
      rate: 0.116
    }, {
      label: '적극(이벤트)',
      rate: 0.20
    }];
    var periods = [3, 6, 12];
    return /*#__PURE__*/React.createElement("div", {
      className: "sub-card"
    }, /*#__PURE__*/React.createElement("div", {
      className: "st"
    }, "\uD83E\uDDFE \uB9AC\uBDF0 \uC99D\uAC00 \uAE30\uBC18 \uCD94\uC815 (\uC791\uC131\uB960 \uC2DD\uD488 11.6%)"), /*#__PURE__*/React.createElement("table", {
      className: "rt-table"
    }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "\uAC00\uC815"), periods.map(function (m) {
      return /*#__PURE__*/React.createElement("th", {
        key: m,
        style: {
          textAlign: 'right'
        }
      }, m, "\uAC1C\uC6D4");
    }))), /*#__PURE__*/React.createElement("tbody", null, reviewRates.map(function (rr) {
      var totalSales = Math.round(rc / rr.rate);
      return /*#__PURE__*/React.createElement("tr", {
        key: rr.label
      }, /*#__PURE__*/React.createElement("td", null, rr.label), periods.map(function (m) {
        return /*#__PURE__*/React.createElement("td", {
          key: m,
          style: {
            textAlign: 'right'
          }
        }, "~", fmt(Math.round(totalSales / 12 * m)), "\uAC74");
      }));
    }))));
  }())));
};

;/* ===== js/components/CompetitorTableSection.jsx ===== */
window.CompetitorTableSection = function CompetitorTableSection(props) {
  if (!props?.data) return null;
  var items = Array.isArray(props.data) ? props.data : props.data.competitors || [];
  if (items.length === 0) return null;
  var hasScore = items.some(function (item) {
    return typeof item.seoScore === 'number';
  });
  var medalEmoji = ['🥇', '🥈', '🥉'];
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83C\uDFC6"), "\uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C (\uC0C1\uC704 \uB178\uCD9C 80\uAC1C \uC911)", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uC2E4\uCE21")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uC0C1\uC704 \uB178\uCD9C \uC0C1\uD488\uB4E4\uC758 \uD575\uC2EC \uC9C0\uD45C\uB97C \uBE44\uAD50\uD569\uB2C8\uB2E4"), hasScore && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 16,
      padding: '14px 18px',
      background: 'linear-gradient(135deg, #f0f9ff, #e0f2fe)',
      borderRadius: 12,
      border: '1px solid #bae6fd',
      fontSize: 13,
      color: '#0369a1',
      lineHeight: 1.7
    }
  }, "\uD83D\uDCA1 \uC885\uD569\uC810\uC218\uAC00 \uB192\uC744\uC218\uB85D \uB124\uC774\uBC84 \uC1FC\uD551 \uB178\uCD9C \uC21C\uC704\uAC00 \uB192\uC544\uC9C0\uB294 \uACBD\uD5A5\uC774 \uC788\uC2B5\uB2C8\uB2E4. \uC0C1\uD488\uBA85\xB7\uAC00\uACA9\xB7\uB9AC\uBDF0\xB7\uD310\uB9E4\uC2E4\uC801 \uB4F1 10\uAC1C \uC9C0\uD45C\uB97C \uAC00\uC911 \uD569\uC0B0\uD55C \uC810\uC218\uC785\uB2C8\uB2E4."), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 0,
      overflow: 'hidden',
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxHeight: 580,
      overflowY: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", {
    className: "rt-table",
    style: {
      width: '100%',
      borderCollapse: 'collapse',
      minWidth: hasScore ? 900 : 800
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'center',
      width: 50
    }
  }, "\uC21C\uC704"), hasScore && /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'center',
      width: 70
    }
  }, "\uC885\uD569\uC810\uC218"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'center',
      width: 50
    }
  }, "\uC774\uBBF8\uC9C0"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'left'
    }
  }, "\uC0C1\uD488\uBA85"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'left',
      width: 90
    }
  }, "\uD310\uB9E4\uCC98"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'left',
      width: 90
    }
  }, "\uBE0C\uB79C\uB4DC"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'right',
      width: 100
    }
  }, "\uAC00\uACA9"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'left',
      width: 100
    }
  }, "\uCE74\uD14C\uACE0\uB9AC"))), /*#__PURE__*/React.createElement("tbody", null, items.map(function (comp, idx) {
    return /*#__PURE__*/React.createElement("tr", {
      key: idx,
      style: {
        borderBottom: '1px solid #e2e8f0',
        background: idx % 2 === 0 ? '#fff' : '#f8fafc'
      }
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '14px 16px',
        textAlign: 'center'
      }
    }, comp.rank <= 3 ? /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 14,
        fontWeight: 700,
        color: '#0f172a'
      }
    }, medalEmoji[comp.rank - 1], comp.rank) : /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 14,
        fontWeight: 700,
        color: '#64748b'
      }
    }, comp.rank)), hasScore && /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '14px 16px',
        textAlign: 'center'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-block',
        padding: '4px 12px',
        borderRadius: 999,
        fontSize: 13,
        fontWeight: 700,
        color: scoreColor(comp.seoScore),
        background: scoreBg(comp.seoScore),
        border: '1px solid ' + scoreColor(comp.seoScore) + '33'
      }
    }, comp.seoScore)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '8px 16px',
        textAlign: 'center'
      }
    }, comp.image ? React.createElement('img', {
      src: comp.image,
      alt: '',
      style: {
        width: 44,
        height: 44,
        objectFit: 'cover',
        borderRadius: 8
      },
      onError: function (e) {
        e.target.style.display = 'none';
      }
    }) : React.createElement('span', {
      style: {
        color: '#d1d5db',
        fontSize: 22
      }
    }, '📦')), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '14px 16px',
        fontWeight: 500,
        fontSize: 14,
        color: '#0f172a',
        maxWidth: 220,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, comp.name), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '14px 16px',
        fontSize: 12,
        color: '#6b7280'
      }
    }, comp.store), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '14px 16px',
        fontSize: 12,
        color: '#6b7280'
      }
    }, comp.brand), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '14px 16px',
        textAlign: 'right',
        fontWeight: 600,
        fontSize: 14,
        color: '#0f172a'
      }
    }, comp.price), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '14px 16px',
        fontSize: 12,
        color: '#6b7280'
      }
    }, comp.category));
  }))))))));
};

;/* ===== js/components/EntryStrategySection.jsx ===== */
/* EntryStrategySection — 1페이지 진입 전략 비교 분석 (v5) */
window.EntryStrategySection = function EntryStrategySection(props) {
  var advertiserData = props.advertiserData; // from /advertiser/analyze
  var strategicData = props.strategicData; // from App.jsx client-side calc
  var keyword = props.keyword || '';
  var rankCheckResult = props.rankCheckResult; // from RankTrackingSection (순위 추적 결과 공유)

  if (!advertiserData && !strategicData) return null;

  // 순위 데이터: rankCheckResult(순위 추적)가 있으면 우선 사용, 없으면 advertiser 데이터 사용
  var ranking = advertiserData && advertiserData.ranking || {};
  if (rankCheckResult && rankCheckResult.rank_position != null) {
    ranking = Object.assign({}, ranking, {
      current_rank: rankCheckResult.rank_position,
      page_number: rankCheckResult.page_number,
      is_on_page1: rankCheckResult.rank_position <= 40
    });
  }
  var productInfo = advertiserData && advertiserData.product_info || {};
  var comparison = advertiserData && advertiserData.competitor_comparison || {};
  var compItems = comparison.items || [];
  var compStats = comparison.stats || {};
  var strategy = advertiserData && advertiserData.entry_strategy || {};
  var strategies = strategy.strategies || [];
  var overallScore = strategy.overall_score || 0;

  // strategicData fallback
  var stData = strategicData || {};
  var avgTop5Price = stData.avgTop5Price || '-';
  var priceRange = stData.priceRange || '-';
  var monthlyVolume = stData.monthlyVolume || '-';
  var mainBrands = stData.mainBrands || '';
  var recommendation = stData.recommendation || '';

  // 상위 10개 추출
  var top5Items = compItems.slice(0, 10);

  /* 헬퍼 함수들 */
  var severityColor = function (s) {
    if (s === 'high') return '#ef4444';
    if (s === 'medium') return '#f59e0b';
    if (s === 'low') return '#10b981';
    return '#64748b';
  };
  var severityBg = function (s) {
    if (s === 'high') return '#fef2f2';
    if (s === 'medium') return '#fffbeb';
    if (s === 'low') return '#f0fdf4';
    return '#f8fafc';
  };
  var scoreColor = overallScore >= 70 ? '#10b981' : overallScore >= 40 ? '#f59e0b' : '#ef4444';
  var scoreLabel = overallScore >= 70 ? '양호' : overallScore >= 40 ? '보통' : '개선 필요';

  /* v5 card style */
  var v5Card = {
    borderRadius: 16,
    background: '#fff',
    border: '1px solid #e2e8f0',
    boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
  };

  /* 격차 분석 데이터 계산 */
  var gapAnalysis = null;
  if (advertiserData && productInfo.price > 0 && compItems.length >= 3) {
    var myPrice = productInfo.price;
    var myRank = ranking.current_rank || null;
    var avgCompPrice = compStats.avg_price || 0;
    var top3Avg = compItems.slice(0, 3).reduce(function (s, c) {
      return s + c.price;
    }, 0) / Math.min(3, compItems.length);
    var priceDiffPct = avgCompPrice > 0 ? Math.round((myPrice - avgCompPrice) / avgCompPrice * 100) : 0;
    var priceVsTop3Pct = top3Avg > 0 ? Math.round((myPrice - top3Avg) / top3Avg * 100) : 0;
    var kwInNameCount = compItems.filter(function (c) {
      return c.has_keyword_in_name;
    }).length;
    var kwInNameRatio = compItems.length > 0 ? Math.round(kwInNameCount / compItems.length * 100) : 0;
    var myHasKw = productInfo.product_name && keyword && productInfo.product_name.replace(/\s/g, '').toLowerCase().indexOf(keyword.replace(/\s/g, '').toLowerCase()) >= 0;
    gapAnalysis = {
      myPrice: myPrice,
      myRank: myRank,
      avgCompPrice: avgCompPrice,
      top3AvgPrice: Math.round(top3Avg),
      priceDiffPct: priceDiffPct,
      priceVsTop3Pct: priceVsTop3Pct,
      compKwRatio: kwInNameRatio,
      myHasKeyword: myHasKw,
      avgNameLength: compStats.avg_name_length || 0,
      myNameLength: productInfo.product_name ? productInfo.product_name.length : 0,
      isOnPage1: ranking.is_on_page1 || false
    };
  }

  /* 시안(.gapbar) 격차 바 시각화 컴포넌트 — .me=내 상품, .cp=경쟁 평균 마커 */
  var GapBar = function (barProps) {
    var label = barProps.label;
    var myVal = barProps.myVal;
    var compVal = barProps.compVal;
    var unit = barProps.unit || '';
    var reverse = barProps.reverse || false;
    var max = Math.max(myVal, compVal) * 1.2 || 1;
    var myPct = Math.min(myVal / max * 100, 100);
    var compPct = Math.min(compVal / max * 100, 100);
    var myBetter = reverse ? myVal <= compVal : myVal >= compVal;
    return React.createElement('div', {
      className: 'gapbar'
    }, React.createElement('div', {
      className: 'row'
    }, React.createElement('span', {
      className: 'nm'
    }, label), React.createElement('div', {
      className: 'b'
    }, React.createElement('div', {
      className: 'me',
      style: {
        width: myPct + '%'
      }
    }), React.createElement('div', {
      className: 'cp',
      style: {
        left: compPct + '%'
      }
    })), React.createElement('span', {
      style: {
        fontSize: 11,
        color: myBetter ? '#10b981' : '#ef4444',
        fontWeight: 700,
        flexShrink: 0
      }
    }, '내 ' + fmt(myVal) + unit + ' · 경쟁 ' + fmt(compVal) + unit)));
  };
  return React.createElement('div', {
    id: 'sec-strategy',
    className: 'section fade-in'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    className: 'card',
    style: {
      padding: '20px 22px'
    }
  }, /* === 섹션 헤더 === */
  React.createElement('h3', {
    className: 'rt-h3'
  }, React.createElement('span', {
    className: 'rt-hic'
  }, '🧭'), '1페이지 진입 전략 비교 분석'), React.createElement('div', {
    className: 'rt-desc'
  }, '경쟁사 데이터 기반 1페이지 진입 전략을 제안합니다'), /* === 상품 정보 헤더 (광고주 데이터가 있을 때만) === */
  advertiserData && React.createElement('div', {
    style: {
      background: '#fff',
      borderRadius: 16,
      padding: '20px 24px',
      marginBottom: 24,
      display: 'flex',
      flexWrap: 'wrap',
      gap: 20,
      alignItems: 'center',
      border: '1px solid #e2e8f0',
      boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
    }
  }, productInfo.image_url && React.createElement('img', {
    src: productInfo.image_url,
    alt: '',
    style: {
      width: 60,
      height: 60,
      borderRadius: 12,
      objectFit: 'cover',
      border: '1px solid #e2e8f0'
    },
    onError: function (e) {
      e.target.style.display = 'none';
    }
  }), React.createElement('div', {
    style: {
      flex: 1,
      minWidth: 200
    }
  }, React.createElement('div', {
    style: {
      fontWeight: 700,
      fontSize: 15,
      color: '#0f172a',
      marginBottom: 4
    }
  }, productInfo.product_name || '상품 정보 로딩 중...'), React.createElement('div', {
    style: {
      fontSize: 13,
      color: '#64748b'
    }
  }, productInfo.store_name && React.createElement('span', {
    style: {
      marginRight: 12
    }
  }, '판매처: ' + productInfo.store_name), productInfo.price > 0 && React.createElement('span', null, '가격: ' + fmt(productInfo.price) + '원'))), React.createElement('div', {
    style: {
      display: 'flex',
      gap: 12,
      alignItems: 'center'
    }
  }, /* 순위 배지 */
  React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: '10px 18px',
      background: '#f8fafc',
      borderRadius: 12,
      minWidth: 80,
      border: '1px solid #e2e8f0'
    }
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: ranking.current_rank ? '#0f172a' : '#ef4444'
    }
  }, ranking.current_rank ? ranking.current_rank + '위' : '미노출'), React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      fontWeight: 600
    }
  }, '현재 순위')), /* 종합 점수 - conic gradient circle */
  React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: '10px 18px',
      background: '#f8fafc',
      borderRadius: 12,
      minWidth: 80,
      border: '1px solid #e2e8f0'
    }
  }, React.createElement('div', {
    style: {
      width: 48,
      height: 48,
      borderRadius: '50%',
      margin: '0 auto 4px',
      background: 'conic-gradient(' + scoreColor + ' ' + overallScore * 3.6 + 'deg, #f1f5f9 0deg)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, React.createElement('div', {
    style: {
      width: 38,
      height: 38,
      borderRadius: '50%',
      background: '#f8fafc',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: 14,
      fontWeight: 800,
      color: scoreColor
    }
  }, overallScore)), React.createElement('div', {
    style: {
      fontSize: 11,
      color: scoreColor,
      fontWeight: 600
    }
  }, scoreLabel)))), /* === 종합 진입 점수 + KPI (시안 .grid2 + .kpi) === */
  advertiserData && React.createElement('div', {
    className: 'grid2',
    style: {
      alignItems: 'center',
      marginBottom: 6
    }
  }, React.createElement('div', {
    style: {
      textAlign: 'center'
    }
  }, React.createElement('div', {
    style: {
      fontSize: 13,
      color: '#64748b'
    }
  }, '종합 진입 점수'), React.createElement('div', {
    style: {
      fontSize: 40,
      fontWeight: 900,
      color: scoreColor
    }
  }, overallScore, React.createElement('span', {
    style: {
      fontSize: 16,
      color: '#64748b'
    }
  }, '/100'))), React.createElement('div', null, React.createElement('div', {
    className: 'grid2'
  }, React.createElement('div', {
    className: 'kpi'
  }, React.createElement('div', {
    className: 'k'
  }, '1P 평균가'), React.createElement('div', {
    className: 'v',
    style: {
      fontSize: 18
    }
  }, compStats.avg_price ? fmt(compStats.avg_price) : avgTop5Price)), React.createElement('div', {
    className: 'kpi'
  }, React.createElement('div', {
    className: 'k'
  }, '키워드 포함률'), React.createElement('div', {
    className: 'v',
    style: {
      fontSize: 18
    }
  }, (compStats.keyword_in_name_ratio != null ? compStats.keyword_in_name_ratio : '-') + '%'))))), /* === 1. 경쟁사 상위 10개 비교표 === */
  React.createElement('div', {
    style: {
      marginBottom: 28
    }
  }, React.createElement('h3', {
    style: {
      fontSize: 16,
      fontWeight: 700,
      color: '#0f172a',
      marginBottom: 16,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, React.createElement('span', {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 28,
      height: 28,
      borderRadius: 8,
      background: 'linear-gradient(135deg, #eef2ff, #dbeafe)',
      fontSize: 14
    }
  }, '\uD83C\uDFC6'), ' 1. 경쟁사 상위 10개 비교표'), /* 시장 요약 v5 MetricCard */
  React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 12,
      marginBottom: 16
    }
  }, React.createElement('div', {
    style: Object.assign({}, v5Card, {
      textAlign: 'center',
      padding: 24
    })
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, '\uD83D\uDCB0'), React.createElement('div', {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      marginBottom: 6
    }
  }, '평균 가격'), React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: '#0f172a'
    }
  }, compStats.avg_price ? fmt(compStats.avg_price) + '원' : avgTop5Price)), React.createElement('div', {
    style: Object.assign({}, v5Card, {
      textAlign: 'center',
      padding: 24
    })
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, '\uD83D\uDCC8'), React.createElement('div', {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      marginBottom: 6
    }
  }, '가격 범위'), React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: '#0f172a'
    }
  }, compStats.min_price ? fmt(compStats.min_price) + '~' + fmt(compStats.max_price) + '원' : priceRange)), React.createElement('div', {
    style: Object.assign({}, v5Card, {
      textAlign: 'center',
      padding: 24
    })
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, '\uD83D\uDD0D'), React.createElement('div', {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      marginBottom: 6
    }
  }, '월간 검색량'), React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: '#4f46e5'
    }
  }, monthlyVolume + '회')), React.createElement('div', {
    style: Object.assign({}, v5Card, {
      textAlign: 'center',
      padding: 24
    })
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, '\uD83D\uDD24'), React.createElement('div', {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      marginBottom: 6
    }
  }, '키워드 포함률'), React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: '#7c3aed'
    }
  }, compStats.keyword_in_name_ratio ? compStats.keyword_in_name_ratio + '%' : '-'))), /* v5 비교표 — gradient header */
  top5Items.length > 0 ? React.createElement('div', {
    style: Object.assign({}, v5Card, {
      overflow: 'hidden'
    })
  }, React.createElement('table', {
    style: {
      minWidth: 700,
      width: '100%',
      borderCollapse: 'collapse'
    }
  }, React.createElement('thead', null, React.createElement('tr', {
    style: {
      background: 'linear-gradient(135deg, #4f46e5, #7c3aed)'
    }
  }, React.createElement('th', {
    style: {
      textAlign: 'center',
      width: 45,
      padding: '12px 8px',
      color: '#fff',
      fontSize: 12,
      fontWeight: 600
    }
  }, '순위'), React.createElement('th', {
    style: {
      textAlign: 'center',
      width: 45,
      padding: '12px 4px',
      color: '#fff',
      fontSize: 12,
      fontWeight: 600
    }
  }, ''), React.createElement('th', {
    style: {
      textAlign: 'left',
      padding: '12px 8px',
      color: '#fff',
      fontSize: 12,
      fontWeight: 600
    }
  }, '상품명'), React.createElement('th', {
    style: {
      textAlign: 'left',
      width: 80,
      padding: '12px 8px',
      color: '#fff',
      fontSize: 12,
      fontWeight: 600
    }
  }, '판매처'), React.createElement('th', {
    style: {
      textAlign: 'right',
      width: 90,
      padding: '12px 8px',
      color: '#fff',
      fontSize: 12,
      fontWeight: 600
    }
  }, '가격'), React.createElement('th', {
    style: {
      textAlign: 'center',
      width: 60,
      padding: '12px 8px',
      color: '#fff',
      fontSize: 12,
      fontWeight: 600
    }
  }, '키워드'), React.createElement('th', {
    style: {
      textAlign: 'left',
      width: 100,
      padding: '12px 8px',
      color: '#fff',
      fontSize: 12,
      fontWeight: 600
    }
  }, '카테고리'))), React.createElement('tbody', null, top5Items.map(function (c, idx) {
    var isMyProduct = ranking.current_rank && c.rank === ranking.current_rank;
    var rowBg = isMyProduct ? '#eef2ff' : idx % 2 === 0 ? '#fff' : '#f8fafc';
    return React.createElement('tr', {
      key: idx,
      style: {
        background: rowBg,
        borderBottom: '1px solid #f1f5f9'
      }
    }, React.createElement('td', {
      style: {
        textAlign: 'center',
        fontWeight: 600,
        padding: '10px 8px',
        fontSize: 13
      }
    }, c.rank <= 3 ? React.createElement('span', {
      style: {
        display: 'inline-block',
        width: 26,
        height: 26,
        lineHeight: '26px',
        borderRadius: '50%',
        background: c.rank === 1 ? '#f59e0b' : c.rank === 2 ? '#94a3b8' : '#b45309',
        color: '#fff',
        fontSize: 12,
        fontWeight: 700
      }
    }, c.rank) : c.rank), React.createElement('td', {
      style: {
        textAlign: 'center',
        padding: '8px 4px'
      }
    }, c.image_url ? React.createElement('img', {
      src: c.image_url,
      alt: '',
      style: {
        width: 36,
        height: 36,
        objectFit: 'cover',
        borderRadius: 8
      },
      onError: function (e) {
        e.target.style.display = 'none';
      }
    }) : null), React.createElement('td', {
      style: {
        maxWidth: 220,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        fontSize: 13,
        padding: '10px 8px',
        color: '#0f172a'
      }
    }, isMyProduct && React.createElement('span', {
      style: {
        color: '#4f46e5',
        marginRight: 4,
        fontWeight: 700
      }
    }, '[내 상품]'), c.product_name), React.createElement('td', {
      style: {
        fontSize: 12,
        color: '#64748b',
        padding: '10px 8px'
      }
    }, c.store_name), React.createElement('td', {
      style: {
        textAlign: 'right',
        fontWeight: 600,
        fontSize: 13,
        padding: '10px 8px',
        color: '#0f172a'
      }
    }, fmt(c.price) + '원'), React.createElement('td', {
      style: {
        textAlign: 'center',
        padding: '10px 8px'
      }
    }, React.createElement('span', {
      style: {
        display: 'inline-block',
        padding: '4px 12px',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
        background: c.has_keyword_in_name ? '#ecfdf5' : '#fef2f2',
        color: c.has_keyword_in_name ? '#10b981' : '#ef4444'
      }
    }, c.has_keyword_in_name ? 'O' : 'X')), React.createElement('td', {
      style: {
        fontSize: 11,
        color: '#64748b',
        padding: '10px 8px'
      }
    }, c.category));
  })))) : (/* strategicData만 있을 때 — 주요 브랜드/판매처 표시 */
  mainBrands && React.createElement('div', {
    style: Object.assign({}, v5Card, {
      padding: 24
    })
  }, React.createElement('h4', {
    style: {
      fontSize: 14,
      fontWeight: 700,
      color: '#0f172a',
      marginBottom: 14
    }
  }, '\uD83C\uDFE2 주요 브랜드/판매처'), React.createElement('div', {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8
    }
  }, mainBrands.split(', ').map(function (brand, idx) {
    return React.createElement('span', {
      key: idx,
      style: {
        padding: '4px 12px',
        background: 'linear-gradient(135deg, #eef2ff, #dbeafe)',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
        color: '#4f46e5',
        border: '1px solid #c7d2fe'
      }
    }, brand);
  }))))), /* === 2. 내 상품 vs 경쟁사 격차 분석 === */
  gapAnalysis && React.createElement('div', {
    style: {
      marginBottom: 28
    }
  }, React.createElement('h3', {
    style: {
      fontSize: 16,
      fontWeight: 700,
      color: '#0f172a',
      marginBottom: 16,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, React.createElement('span', {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 28,
      height: 28,
      borderRadius: 8,
      background: 'linear-gradient(135deg, #eef2ff, #dbeafe)',
      fontSize: 14
    }
  }, '\uD83D\uDCCA'), ' 2. 내 상품 vs 경쟁사 격차 분석'), /* 격차 요약 v5 MetricCard */
  React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 12,
      marginBottom: 20
    }
  }, /* 가격 격차 */
  React.createElement('div', {
    style: Object.assign({}, v5Card, {
      padding: 24,
      textAlign: 'center'
    })
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, '\uD83D\uDCB0'), React.createElement('div', {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      marginBottom: 6
    }
  }, '가격 경쟁력'), React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: gapAnalysis.priceDiffPct <= 0 ? '#10b981' : gapAnalysis.priceDiffPct <= 10 ? '#f59e0b' : '#ef4444'
    }
  }, (gapAnalysis.priceDiffPct > 0 ? '+' : '') + gapAnalysis.priceDiffPct + '%'), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginTop: 4
    }
  }, gapAnalysis.priceDiffPct <= -10 ? '경쟁사 대비 저렴' : gapAnalysis.priceDiffPct <= 0 ? '적정 가격대' : gapAnalysis.priceDiffPct <= 10 ? '소폭 비쌈' : '가격 조정 필요')), /* 상위3개 vs 내 가격 */
  React.createElement('div', {
    style: Object.assign({}, v5Card, {
      padding: 24,
      textAlign: 'center'
    })
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, '\uD83E\uDD47'), React.createElement('div', {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      marginBottom: 6
    }
  }, 'TOP3 대비 가격'), React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: gapAnalysis.priceVsTop3Pct <= 0 ? '#10b981' : '#f59e0b'
    }
  }, (gapAnalysis.priceVsTop3Pct > 0 ? '+' : '') + gapAnalysis.priceVsTop3Pct + '%'), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginTop: 4
    }
  }, 'TOP3 평균: ' + fmt(gapAnalysis.top3AvgPrice) + '원')), /* 키워드 포함 여부 */
  React.createElement('div', {
    style: Object.assign({}, v5Card, {
      padding: 24,
      textAlign: 'center'
    })
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, '\uD83D\uDD24'), React.createElement('div', {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      marginBottom: 6
    }
  }, '키워드 포함'), React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: gapAnalysis.myHasKeyword ? '#10b981' : '#ef4444'
    }
  }, gapAnalysis.myHasKeyword ? '포함 \u2705' : '미포함 \u274C'), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginTop: 4
    }
  }, '경쟁사 포함률: ' + gapAnalysis.compKwRatio + '%')), /* 1페이지 진입 여부 */
  React.createElement('div', {
    style: Object.assign({}, v5Card, {
      padding: 24,
      textAlign: 'center'
    })
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, '\uD83D\uDCC4'), React.createElement('div', {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      marginBottom: 6
    }
  }, '1페이지 진입'), React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 800,
      color: gapAnalysis.isOnPage1 ? '#10b981' : '#ef4444'
    }
  }, gapAnalysis.isOnPage1 ? '진입 \u2705' : '미진입 \u274C'), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginTop: 4
    }
  }, gapAnalysis.myRank ? '현재 ' + gapAnalysis.myRank + '위' : '순위권 밖'))), /* 격차 바 차트 — 시안 .sub-card + .st + .gapbar */
  React.createElement('div', {
    className: 'sub-card'
  }, React.createElement('div', {
    className: 'st'
  }, '\uD83D\uDCCA 내 상품 vs 경쟁사 격차'), React.createElement(GapBar, {
    label: '가격',
    myVal: gapAnalysis.myPrice,
    compVal: gapAnalysis.avgCompPrice,
    unit: '원',
    reverse: true
  }), React.createElement(GapBar, {
    label: '상품명 길이',
    myVal: gapAnalysis.myNameLength,
    compVal: gapAnalysis.avgNameLength,
    unit: '자'
  }), gapAnalysis.myRank && React.createElement(GapBar, {
    label: '순위',
    myVal: gapAnalysis.myRank,
    compVal: 3,
    unit: '위',
    reverse: true
  }))), /* === 3. AI 기반 맞춤 진입 전략 제안 === */
  strategies.length > 0 && React.createElement('div', {
    style: {
      marginBottom: 20
    }
  }, React.createElement('h3', {
    style: {
      fontSize: 16,
      fontWeight: 700,
      color: '#0f172a',
      marginBottom: 16,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, React.createElement('span', {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 28,
      height: 28,
      borderRadius: 8,
      background: 'linear-gradient(135deg, #eef2ff, #dbeafe)',
      fontSize: 14
    }
  }, '\uD83E\uDD16'), ' 3. AI 기반 맞춤 진입 전략 제안'), /* 전략 카드들 — 시안 .strat + .st + .sev */
  React.createElement('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 16
    }
  }, strategies.map(function (s, idx) {
    var insights = s.insights || [];
    var actions = s.actions || [];
    var recs = s.recommendations || [];
    /* 심각도 → 시안 클래스(high/med/low) + 라벨 매핑 */
    var sevClass = s.severity === 'high' ? 'high' : s.severity === 'low' ? 'low' : 'med';
    var sevLabel = s.severity === 'high' ? '긴급' : s.severity === 'low' ? '선택' : '권장';
    return React.createElement('div', {
      key: idx,
      className: 'strat ' + sevClass
    }, /* 카드 헤더 — .st + .sev */
    React.createElement('div', {
      className: 'st'
    }, s.icon ? React.createElement('span', null, s.icon) : null, React.createElement('span', {
      style: {
        flex: 1
      }
    }, s.area), React.createElement('span', {
      className: 'sev ' + sevClass
    }, sevLabel)), /* 카드 바디 */
    React.createElement('div', {
      style: {
        marginTop: 8
      }
    }, /* 분석 인사이트 */
    insights.length > 0 && React.createElement('div', {
      style: {
        marginBottom: actions.length > 0 || recs.length > 0 ? 16 : 0
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        fontWeight: 700,
        color: '#94a3b8',
        textTransform: 'uppercase',
        letterSpacing: 1,
        marginBottom: 10
      }
    }, 'INSIGHT'), insights.map(function (insight, i) {
      return React.createElement('div', {
        key: i,
        style: {
          fontSize: 13,
          color: '#0f172a',
          lineHeight: 1.7,
          padding: '5px 0',
          display: 'flex',
          gap: 8
        }
      }, React.createElement('span', {
        style: {
          color: severityColor(s.severity),
          flexShrink: 0,
          marginTop: 2
        }
      }, '\u25B8'), React.createElement('span', null, insight));
    })), /* 액션 아이템 */
    actions.length > 0 && React.createElement('div', {
      style: {
        background: '#f8fafc',
        borderRadius: 12,
        padding: '16px 20px',
        border: '1px solid #e2e8f0',
        marginBottom: recs.length > 0 ? 16 : 0
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        fontWeight: 700,
        color: severityColor(s.severity),
        textTransform: 'uppercase',
        letterSpacing: 1,
        marginBottom: 10
      }
    }, 'ACTION PLAN'), actions.map(function (action, i) {
      return React.createElement('div', {
        key: i,
        style: {
          fontSize: 13,
          color: '#0f172a',
          lineHeight: 1.7,
          padding: '6px 0',
          borderBottom: i < actions.length - 1 ? '1px solid #e2e8f0' : 'none',
          display: 'flex',
          gap: 10
        }
      }, React.createElement('span', {
        style: {
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 22,
          height: 22,
          borderRadius: 6,
          background: severityColor(s.severity),
          color: '#fff',
          fontSize: 11,
          fontWeight: 700,
          flexShrink: 0,
          marginTop: 1
        }
      }, i + 1), React.createElement('span', null, action));
    })), /* 추천 광고 품목 */
    recs.length > 0 && React.createElement('div', {
      style: {
        background: 'linear-gradient(135deg, #eef2ff, #faf5ff)',
        borderRadius: 12,
        padding: '16px 20px',
        border: '1px solid #c7d2fe'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        fontWeight: 700,
        color: '#4f46e5',
        textTransform: 'uppercase',
        letterSpacing: 1,
        marginBottom: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 6
      }
    }, React.createElement('span', {
      style: {
        fontSize: 13
      }
    }, '\uD83D\uDCE2'), 'RECOMMENDED SERVICE'), recs.map(function (rec, i) {
      return React.createElement('div', {
        key: i,
        style: {
          padding: '8px 0',
          borderBottom: i < recs.length - 1 ? '1px solid #ddd6fe' : 'none',
          display: 'flex',
          gap: 10,
          alignItems: 'flex-start'
        }
      }, React.createElement('span', {
        style: {
          display: 'inline-flex',
          alignItems: 'center',
          padding: '4px 12px',
          borderRadius: 999,
          background: '#4f46e5',
          color: '#fff',
          fontSize: 12,
          fontWeight: 700,
          flexShrink: 0,
          whiteSpace: 'nowrap',
          marginTop: 1
        }
      }, rec.name), React.createElement('span', {
        style: {
          fontSize: 12,
          color: '#64748b',
          lineHeight: 1.6
        }
      }, rec.reason));
    }))));
  }))), /* 종합 전략 추천 (strategicData 기반 — advertiserData 없을 때만) */
  !advertiserData && recommendation && React.createElement('div', {
    style: {
      background: '#f0fdf4',
      border: '1px solid #bbf7d0',
      borderRadius: 16,
      padding: '20px 24px',
      borderLeft: '4px solid #10b981',
      marginBottom: 20
    }
  }, React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 12
    }
  }, React.createElement('span', {
    style: {
      fontSize: 16
    }
  }, '\uD83D\uDCCC'), React.createElement('span', {
    style: {
      fontWeight: 700,
      fontSize: 14,
      color: '#065f46'
    }
  }, '종합 진입 전략'), React.createElement('span', {
    style: {
      padding: '4px 12px',
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 700,
      color: '#fff',
      background: '#10b981',
      marginLeft: 'auto'
    }
  }, '전략')), React.createElement('p', {
    style: {
      lineHeight: 1.7,
      color: '#0f172a',
      fontSize: 13,
      margin: 0
    }
  }, recommendation)), /* 분석 시각 */
  React.createElement('div', {
    style: {
      marginTop: 16,
      padding: '12px 16px',
      background: '#f8fafc',
      borderRadius: 12,
      fontSize: 12,
      color: '#94a3b8',
      textAlign: 'center',
      border: '1px solid #e2e8f0'
    }
  }, '네이버 공식 API 기준 분석 결과이며, 실제 검색 노출 순위와 차이가 있을 수 있습니다.', advertiserData && advertiserData.analyzed_at ? ' | 분석 시각: ' + new Date(advertiserData.analyzed_at).toLocaleString('ko-KR') : ''), /* 반응형 스타일 */
  React.createElement('style', null, '\n@media (max-width: 768px) {\n  #sec-strategy .card-grid-4 { grid-template-columns: 1fr 1fr !important; }\n}\n'))));
};

;/* ===== js/components/ApiUsageSection.jsx ===== */
/* ApiUsageSection — API 사용량 및 비용 대시보드 (superadmin 전용, v3.9.13) */
window.ApiUsageSection = function ApiUsageSection() {
  var useState = React.useState;
  var useEffect = React.useEffect;
  var _s = useState(null);
  var data = _s[0];
  var setData = _s[1];
  var _l = useState(true);
  var loading = _l[0];
  var setLoading = _l[1];
  var _t = useState('overview');
  var tab = _t[0];
  var setTab = _t[1];
  var _p = useState('month');
  var period = _p[0];
  var setPeriod = _p[1];
  var _h = useState(null);
  var hovered = _h[0];
  var setHovered = _h[1];
  var _e = useState('');
  var errMsg = _e[0];
  var setErrMsg = _e[1];
  useEffect(function () {
    api.get('/admin/api-usage').then(function (res) {
      if (res.success) {
        setData(res.data);
      } else {
        setErrMsg(res.error || res.detail || 'API 데이터 로드 실패');
        // 빈 데이터로 초기화하여 UI는 표시
        setData({
          today: {
            calls: 0,
            cost_krw: 0,
            input_tokens: 0,
            output_tokens: 0
          },
          month: {
            calls: 0,
            cost_krw: 0,
            input_tokens: 0,
            output_tokens: 0
          },
          avg_cost: 0,
          daily_avg_cost: 0,
          daily: [],
          clients: [],
          logs: []
        });
      }
      setLoading(false);
    }).catch(function (e) {
      setErrMsg('네트워크 오류: ' + (e.message || ''));
      setData({
        today: {
          calls: 0,
          cost_krw: 0,
          input_tokens: 0,
          output_tokens: 0
        },
        month: {
          calls: 0,
          cost_krw: 0,
          input_tokens: 0,
          output_tokens: 0
        },
        avg_cost: 0,
        daily_avg_cost: 0,
        daily: [],
        clients: [],
        logs: []
      });
      setLoading(false);
    });
  }, []);
  if (loading) return React.createElement('div', {
    className: 'section',
    id: 'sec-api-usage'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: '40px 0',
      color: '#94a3b8'
    }
  }, '로딩 중...')));
  if (!data) return null;
  var daily = data.daily || [];
  var clients = data.clients || [];
  var logs = data.logs || [];
  var today = data.today || {};
  var month = data.month || {};
  var avgCost = data.avg_cost || 0;
  var dailyAvg = data.daily_avg_cost || 0;

  // 기간별 일별 데이터
  var chartData = period === 'week' ? daily.slice(-7) : daily;
  var maxCost = Math.max.apply(null, chartData.map(function (d) {
    return d.cost_krw;
  }).concat([1]));
  var tabs = [{
    key: 'overview',
    label: '비용 요약'
  }, {
    key: 'clients',
    label: '업체별 분석'
  }, {
    key: 'logs',
    label: '호출 로그'
  }];
  var summaryCards = [{
    label: '오늘 비용',
    value: fmt(today.cost_krw || 0) + '원',
    sub: (today.calls || 0) + '회 호출',
    icon: '📊',
    color: '#6366f1',
    bg: '#eef2ff'
  }, {
    label: '이번 달 누적',
    value: fmt(month.cost_krw || 0) + '원',
    sub: (month.calls || 0) + '회 호출',
    icon: '📅',
    color: '#8b5cf6',
    bg: '#f5f3ff'
  }, {
    label: '1회 평균 비용',
    value: avgCost + '원',
    sub: 'Claude Sonnet 4',
    icon: '⚡',
    color: '#0ea5e9',
    bg: '#f0f9ff'
  }, {
    label: '일 평균 비용',
    value: fmt(dailyAvg) + '원',
    sub: '일 평균 ' + (month.calls ? Math.round(month.calls / 30) : 0) + '회',
    icon: '📈',
    color: '#10b981',
    bg: '#ecfdf5'
  }];
  var totalClientCost = clients.reduce(function (s, c) {
    return s + c.cost_krw;
  }, 0) || 1;
  var totalInputTokens = month.input_tokens || 0;
  var totalOutputTokens = month.output_tokens || 0;
  var totalTokenCost = totalInputTokens * 3 + totalOutputTokens * 15;
  var inputPct = totalTokenCost > 0 ? Math.round(totalInputTokens * 3 / totalTokenCost * 100) : 25;
  var outputPct = 100 - inputPct;
  return React.createElement('div', {
    className: 'section',
    id: 'sec-api-usage'
  }, React.createElement('div', {
    className: 'container'
  }, /* 헤더 */
  React.createElement('div', {
    className: 'section-title'
  }, React.createElement('span', {
    className: 'icon',
    style: {
      background: '#eef2ff'
    }
  }, '💰'), 'API 사용량 및 비용'), React.createElement('p', {
    style: {
      fontSize: 13,
      color: '#94a3b8',
      margin: '-8px 0 16px 0'
    }
  }, 'Claude AI API 호출 내역과 비용을 실시간으로 확인합니다.'), errMsg && React.createElement('div', {
    style: {
      padding: '12px 16px',
      background: '#fffbeb',
      borderRadius: 8,
      border: '1px solid #fde68a',
      fontSize: 13,
      color: '#92400e',
      marginBottom: 16
    }
  }, '아직 분석 데이터가 없습니다. 키워드 분석을 실행하면 비용이 자동으로 기록됩니다.'), /* 요약 카드 4개 */
  React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 12,
      marginBottom: 20
    }
  }, summaryCards.map(function (c, i) {
    return React.createElement('div', {
      key: i,
      className: 'card',
      style: {
        background: 'linear-gradient(135deg, ' + c.bg + ', #fff)',
        borderLeft: '3px solid ' + c.color,
        padding: 16
      }
    }, React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 8
      }
    }, React.createElement('span', {
      style: {
        fontSize: 16
      }
    }, c.icon), React.createElement('span', {
      style: {
        fontSize: 12,
        color: '#64748b',
        fontWeight: 500
      }
    }, c.label)), React.createElement('div', {
      style: {
        fontSize: 20,
        fontWeight: 700,
        color: '#1e293b',
        marginBottom: 2
      }
    }, c.value), React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#94a3b8'
      }
    }, c.sub));
  })), /* 탭 전환 */
  React.createElement('div', {
    style: {
      display: 'flex',
      gap: 4,
      marginBottom: 16,
      background: '#f1f5f9',
      borderRadius: 10,
      padding: 4
    }
  }, tabs.map(function (t) {
    var active = tab === t.key;
    return React.createElement('button', {
      key: t.key,
      onClick: function () {
        setTab(t.key);
      },
      style: {
        flex: 1,
        padding: '8px 16px',
        border: 'none',
        cursor: 'pointer',
        borderRadius: 8,
        fontSize: 13,
        fontWeight: 600,
        background: active ? '#fff' : 'transparent',
        color: active ? '#4f46e5' : '#64748b',
        boxShadow: active ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
        transition: 'all 0.2s'
      }
    }, t.label);
  })), /* ========== 비용 요약 탭 ========== */
  tab === 'overview' && React.createElement('div', null, /* 일별 차트 */
  React.createElement('div', {
    className: 'card',
    style: {
      marginBottom: 16
    }
  }, React.createElement('div', {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 16
    }
  }, React.createElement('div', {
    style: {
      fontWeight: 600,
      fontSize: 15,
      color: '#1e293b'
    }
  }, '일별 비용 추이'), React.createElement('div', {
    style: {
      display: 'flex',
      gap: 4,
      background: '#f8fafc',
      borderRadius: 8,
      padding: 2
    }
  }, ['7일', '30일'].map(function (p) {
    var active = period === 'week' && p === '7일' || period === 'month' && p === '30일';
    return React.createElement('button', {
      key: p,
      onClick: function () {
        setPeriod(p === '7일' ? 'week' : 'month');
      },
      style: {
        padding: '4px 12px',
        border: 'none',
        borderRadius: 6,
        fontSize: 12,
        cursor: 'pointer',
        fontWeight: 500,
        background: active ? '#6366f1' : 'transparent',
        color: active ? '#fff' : '#64748b'
      }
    }, p);
  }))), /* 바 차트 */
  React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'flex-end',
      gap: 3,
      height: 160,
      padding: '0 4px'
    }
  }, chartData.map(function (d, i) {
    var h = Math.max(d.cost_krw / maxCost * 140, 2);
    var isHov = hovered === i;
    return React.createElement('div', {
      key: i,
      style: {
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'flex-end',
        height: '100%',
        cursor: 'pointer',
        position: 'relative'
      },
      onMouseEnter: function () {
        setHovered(i);
      },
      onMouseLeave: function () {
        setHovered(null);
      }
    }, isHov && React.createElement('div', {
      style: {
        position: 'absolute',
        bottom: h + 8,
        background: '#1e293b',
        color: '#fff',
        padding: '4px 8px',
        borderRadius: 6,
        fontSize: 11,
        whiteSpace: 'nowrap',
        zIndex: 10,
        boxShadow: '0 2px 8px rgba(0,0,0,0.2)'
      }
    }, d.day.slice(5) + ' | ' + d.calls + '회 | ' + fmt(d.cost_krw) + '원'), React.createElement('div', {
      style: {
        width: '100%',
        height: h,
        borderRadius: '3px 3px 0 0',
        background: isHov ? 'linear-gradient(180deg, #6366f1, #4f46e5)' : i >= chartData.length - 5 ? 'linear-gradient(180deg, #818cf8, #6366f1)' : 'linear-gradient(180deg, #c7d2fe, #a5b4fc)',
        transition: 'all 0.2s'
      }
    }));
  })), chartData.length > 0 && React.createElement('div', {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      fontSize: 10,
      color: '#94a3b8',
      marginTop: 6,
      padding: '0 4px'
    }
  }, React.createElement('span', null, chartData[0].day.slice(5)), React.createElement('span', null, period === 'week' ? '최근 7일' : '최근 30일'), React.createElement('span', null, chartData[chartData.length - 1].day.slice(5)))), /* 비용 구성 분석 */
  React.createElement('div', {
    className: 'card'
  }, React.createElement('div', {
    style: {
      fontWeight: 600,
      fontSize: 15,
      color: '#1e293b',
      marginBottom: 16
    }
  }, '비용 구성 분석'), React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 16
    }
  }, /* 입력 토큰 */
  React.createElement('div', {
    style: {
      background: '#f8fafc',
      borderRadius: 10,
      padding: 16
    }
  }, React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginBottom: 8,
      fontWeight: 500
    }
  }, '입력 토큰 (Input)'), React.createElement('div', {
    style: {
      fontSize: 13,
      color: '#1e293b',
      marginBottom: 4
    }
  }, '이번 달: ' + fmt(totalInputTokens) + ' 토큰'), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#94a3b8'
    }
  }, '단가: $3 / 1M 토큰'), React.createElement('div', {
    style: {
      marginTop: 8,
      height: 6,
      background: '#e2e8f0',
      borderRadius: 3,
      overflow: 'hidden'
    }
  }, React.createElement('div', {
    style: {
      width: inputPct + '%',
      height: '100%',
      background: 'linear-gradient(90deg, #818cf8, #6366f1)',
      borderRadius: 3
    }
  })), React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#6366f1',
      marginTop: 4,
      fontWeight: 600
    }
  }, '전체 비용의 약 ' + inputPct + '%')), /* 출력 토큰 */
  React.createElement('div', {
    style: {
      background: '#f8fafc',
      borderRadius: 10,
      padding: 16
    }
  }, React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginBottom: 8,
      fontWeight: 500
    }
  }, '출력 토큰 (Output)'), React.createElement('div', {
    style: {
      fontSize: 13,
      color: '#1e293b',
      marginBottom: 4
    }
  }, '이번 달: ' + fmt(totalOutputTokens) + ' 토큰'), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#94a3b8'
    }
  }, '단가: $15 / 1M 토큰'), React.createElement('div', {
    style: {
      marginTop: 8,
      height: 6,
      background: '#e2e8f0',
      borderRadius: 3,
      overflow: 'hidden'
    }
  }, React.createElement('div', {
    style: {
      width: outputPct + '%',
      height: '100%',
      background: 'linear-gradient(90deg, #a78bfa, #8b5cf6)',
      borderRadius: 3
    }
  })), React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#8b5cf6',
      marginTop: 4,
      fontWeight: 600
    }
  }, '전체 비용의 약 ' + outputPct + '%'))))), /* ========== 업체별 분석 탭 ========== */
  tab === 'clients' && React.createElement('div', {
    className: 'card'
  }, React.createElement('div', {
    style: {
      fontWeight: 600,
      fontSize: 15,
      color: '#1e293b',
      marginBottom: 16
    }
  }, '업체별 API 사용 비용'), clients.length === 0 ? React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: '40px 0',
      color: '#94a3b8',
      fontSize: 13
    }
  }, '아직 업체별 사용 데이터가 없습니다.') : React.createElement('div', {
    style: {
      overflowX: 'auto'
    }
  }, React.createElement('table', {
    style: {
      width: '100%',
      borderCollapse: 'collapse',
      fontSize: 13
    }
  }, React.createElement('thead', null, React.createElement('tr', {
    style: {
      borderBottom: '2px solid #e2e8f0'
    }
  }, ['업체명', '키워드 수', '분석 횟수', '이번 달 비용', '비중'].map(function (h) {
    return React.createElement('th', {
      key: h,
      style: {
        padding: '10px 12px',
        textAlign: h === '업체명' ? 'left' : 'center',
        color: '#64748b',
        fontWeight: 600,
        fontSize: 12
      }
    }, h);
  }))), React.createElement('tbody', null, clients.map(function (c, i) {
    var pct = Math.round(c.cost_krw / totalClientCost * 100);
    return React.createElement('tr', {
      key: i,
      style: {
        borderBottom: '1px solid #f1f5f9',
        background: i % 2 === 0 ? '#fafbfc' : '#fff'
      }
    }, React.createElement('td', {
      style: {
        padding: 12,
        fontWeight: 600,
        color: '#1e293b'
      }
    }, c.client_name), React.createElement('td', {
      style: {
        padding: 12,
        textAlign: 'center',
        color: '#64748b'
      }
    }, c.keyword_count + '개'), React.createElement('td', {
      style: {
        padding: 12,
        textAlign: 'center',
        color: '#64748b'
      }
    }, c.calls + '회'), React.createElement('td', {
      style: {
        padding: 12,
        textAlign: 'center',
        fontWeight: 700,
        color: '#4f46e5'
      }
    }, fmt(c.cost_krw) + '원'), React.createElement('td', {
      style: {
        padding: 12,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        justifyContent: 'center'
      }
    }, React.createElement('div', {
      style: {
        width: 60,
        height: 6,
        background: '#e2e8f0',
        borderRadius: 3,
        overflow: 'hidden'
      }
    }, React.createElement('div', {
      style: {
        width: pct + '%',
        height: '100%',
        background: '#6366f1',
        borderRadius: 3
      }
    })), React.createElement('span', {
      style: {
        fontSize: 11,
        color: '#64748b',
        minWidth: 30
      }
    }, pct + '%'))));
  }), /* 합계 행 */
  React.createElement('tr', {
    style: {
      borderTop: '2px solid #e2e8f0',
      background: '#f8fafc'
    }
  }, React.createElement('td', {
    style: {
      padding: 12,
      fontWeight: 700,
      color: '#1e293b'
    }
  }, '합계'), React.createElement('td', {
    style: {
      padding: 12,
      textAlign: 'center',
      fontWeight: 600,
      color: '#64748b'
    }
  }, clients.reduce(function (s, c) {
    return s + c.keyword_count;
  }, 0) + '개'), React.createElement('td', {
    style: {
      padding: 12,
      textAlign: 'center',
      fontWeight: 600,
      color: '#64748b'
    }
  }, clients.reduce(function (s, c) {
    return s + c.calls;
  }, 0) + '회'), React.createElement('td', {
    style: {
      padding: 12,
      textAlign: 'center',
      fontWeight: 700,
      color: '#4f46e5',
      fontSize: 14
    }
  }, fmt(totalClientCost) + '원'), React.createElement('td', {
    style: {
      padding: 12,
      textAlign: 'center',
      fontWeight: 600,
      color: '#64748b',
      fontSize: 11
    }
  }, '100%'))))), React.createElement('div', {
    style: {
      marginTop: 16,
      padding: '12px 16px',
      background: '#fffbeb',
      borderRadius: 8,
      border: '1px solid #fde68a',
      fontSize: 12,
      color: '#92400e'
    }
  }, '자동 분석 (매일 07:00)과 수동 분석 비용이 합산됩니다. 키워드가 많은 업체일수록 비용이 높아집니다.')), /* ========== 호출 로그 탭 ========== */
  tab === 'logs' && React.createElement('div', {
    className: 'card'
  }, React.createElement('div', {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 16
    }
  }, React.createElement('div', {
    style: {
      fontWeight: 600,
      fontSize: 15,
      color: '#1e293b'
    }
  }, '최근 API 호출 내역'), React.createElement('div', {
    style: {
      padding: '4px 12px',
      background: '#f0f9ff',
      borderRadius: 6,
      fontSize: 12,
      color: '#0369a1',
      fontWeight: 500
    }
  }, '오늘 ' + (today.calls || 0) + '건')), logs.length === 0 ? React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: '40px 0',
      color: '#94a3b8',
      fontSize: 13
    }
  }, '아직 호출 내역이 없습니다.') : React.createElement('div', {
    style: {
      overflowX: 'auto'
    }
  }, React.createElement('table', {
    style: {
      width: '100%',
      borderCollapse: 'collapse',
      fontSize: 12,
      minWidth: 700
    }
  }, React.createElement('thead', null, React.createElement('tr', {
    style: {
      borderBottom: '2px solid #e2e8f0'
    }
  }, ['#', '시간', '키워드', '업체', '유형', '입력', '출력', '비용', '상태'].map(function (h) {
    return React.createElement('th', {
      key: h,
      style: {
        padding: '8px 10px',
        textAlign: h === '키워드' || h === '업체' ? 'left' : 'center',
        color: '#64748b',
        fontWeight: 600,
        fontSize: 11,
        whiteSpace: 'nowrap'
      }
    }, h);
  }))), React.createElement('tbody', null, logs.map(function (log, i) {
    var timeStr = log.called_at ? log.called_at.slice(11, 16) : '';
    var typeLabel = log.call_type === 'auto' ? '자동 분석' : '수동 분석';
    return React.createElement('tr', {
      key: i,
      style: {
        borderBottom: '1px solid #f1f5f9',
        background: log.status === 'error' ? '#fef2f2' : i % 2 === 0 ? '#fafbfc' : '#fff'
      }
    }, React.createElement('td', {
      style: {
        padding: '8px 10px',
        textAlign: 'center',
        color: '#94a3b8',
        fontSize: 11
      }
    }, log.id), React.createElement('td', {
      style: {
        padding: '8px 10px',
        textAlign: 'center',
        fontFamily: 'monospace',
        color: '#475569'
      }
    }, timeStr), React.createElement('td', {
      style: {
        padding: '8px 10px',
        fontWeight: 500,
        color: '#1e293b'
      }
    }, log.keyword || '-'), React.createElement('td', {
      style: {
        padding: '8px 10px',
        color: log.client_name ? '#64748b' : '#cbd5e1'
      }
    }, log.client_name || '키워드 분석'), React.createElement('td', {
      style: {
        padding: '8px 10px',
        textAlign: 'center'
      }
    }, React.createElement('span', {
      style: {
        padding: '2px 8px',
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 500,
        background: log.call_type === 'auto' ? '#dbeafe' : '#f0fdf4',
        color: log.call_type === 'auto' ? '#1d4ed8' : '#15803d'
      }
    }, typeLabel)), React.createElement('td', {
      style: {
        padding: '8px 10px',
        textAlign: 'center',
        color: '#64748b',
        fontFamily: 'monospace',
        fontSize: 11
      }
    }, fmt(log.input_tokens)), React.createElement('td', {
      style: {
        padding: '8px 10px',
        textAlign: 'center',
        color: '#64748b',
        fontFamily: 'monospace',
        fontSize: 11
      }
    }, fmt(log.output_tokens)), React.createElement('td', {
      style: {
        padding: '8px 10px',
        textAlign: 'center',
        fontWeight: 600,
        color: '#4f46e5',
        fontSize: 12
      }
    }, log.cost_krw + '원'), React.createElement('td', {
      style: {
        padding: '8px 10px',
        textAlign: 'center'
      }
    }, React.createElement('span', {
      style: {
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: log.status === 'success' ? '#22c55e' : '#ef4444'
      }
    })));
  })))))));
};

;/* ===== js/components/SaveToClientSection.jsx ===== */
/* SaveToClientSection — 분석 결과를 업체로 저장하는 섹션 */
window.SaveToClientSection = function SaveToClientSection({
  keyword,
  productUrl,
  analysisData,
  volumeData,
  relatedData,
  shopProducts,
  advertiserReport,
  detailHtml,
  htmlDetailResult
}) {
  var _React = React;
  var useState = _React.useState;
  var useEffect = _React.useEffect;
  var useCallback = _React.useCallback;
  var _s = useState(false);
  var showModal = _s[0];
  var setShowModal = _s[1];
  var _s2 = useState([]);
  var existingClients = _s2[0];
  var setExistingClients = _s2[1];
  var _s3 = useState('new');
  var saveMode = _s3[0];
  var setSaveMode = _s3[1];
  var _s4 = useState('');
  var clientName = _s4[0];
  var setClientName = _s4[1];
  var _s5 = useState(null);
  var selectedClientId = _s5[0];
  var setSelectedClientId = _s5[1];
  var _s6 = useState(false);
  var saving = _s6[0];
  var setSaving = _s6[1];
  var _s7 = useState('');
  var message = _s7[0];
  var setMessage = _s7[1];
  var _s8 = useState(false);
  var success = _s8[0];
  var setSuccess = _s8[1];

  /* 기존 업체 목록 로드 */
  var loadClients = useCallback(function () {
    api.get('/cd/registered-clients').then(function (res) {
      if (res.success) setExistingClients(res.data || []);
    }).catch(function () {});
  }, []);
  useEffect(function () {
    if (showModal) loadClients();
  }, [showModal, loadClients]);
  if (!keyword || !analysisData) return null;

  /* DOM 캡처 — ReportSection과 동일한 로직으로 분석 화면 HTML 생성 */
  var captureReportHtml = function () {
    try {
      var captured = [];
      var rootEl = document.getElementById('root');
      if (rootEl && rootEl.children[0]) {
        var appDiv = rootEl.children[0];
        var children = Array.from(appDiv.children);
        children.forEach(function (child) {
          if (child.classList.contains('topbar')) return;
          if (child.querySelector && child.querySelector('.anchor-nav')) return;
          var style = child.getAttribute('style') || '';
          if (style.indexOf('sticky') !== -1 && style.indexOf('top') !== -1 && child.querySelector && child.querySelector('.anchor-btn')) return;
          if (child.id === 'sec-report') return;
          if (child.id === 'sec-notify') return;
          if (child.id === 'sec-save-client') return;
          if (child.querySelector && child.querySelector('#sec-report')) return;
          if (child.querySelector && child.querySelector('#sec-notify')) return;
          if (child.querySelector && child.querySelector('#sec-save-client')) return;
          if (child.tagName === 'FOOTER') return;
          if (!child.innerHTML || child.innerHTML.trim() === '') return;
          if (child.querySelector && child.querySelector('.loading-spinner')) return;
          captured.push(child.cloneNode(true));
        });
      }
      if (captured.length === 0) {
        var allSections = document.querySelectorAll('.section');
        allSections.forEach(function (s) {
          if (s.id === 'sec-report' || s.id === 'sec-notify' || s.id === 'sec-save-client') return;
          captured.push(s.cloneNode(true));
        });
      }
      captured.forEach(function (node) {
        var btns = node.querySelectorAll('button, .btn');
        btns.forEach(function (b) {
          b.remove();
        });
        var inputs = node.querySelectorAll('input, select, textarea');
        inputs.forEach(function (inp) {
          var span = document.createElement('span');
          span.textContent = inp.value || '';
          span.style.fontWeight = '600';
          inp.parentNode.replaceChild(span, inp);
        });
      });
      var cssText = '';
      try {
        var sheets = document.styleSheets;
        for (var i = 0; i < sheets.length; i++) {
          try {
            var rules = sheets[i].cssRules || sheets[i].rules;
            for (var j = 0; j < rules.length; j++) {
              cssText += rules[j].cssText + '\n';
            }
          } catch (e) {}
        }
      } catch (e) {}
      var bodyHtml = '';
      captured.forEach(function (node) {
        bodyHtml += node.outerHTML + '\n';
      });
      var dateStr = new Date().toLocaleDateString('ko-KR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      });
      var headerText = keyword + ' 키워드 분석 보고서';
      return '<!DOCTYPE html>\n<html lang="ko">\n<head>\n' + '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n' + '<title>' + headerText + ' - ' + dateStr + '</title>\n<style>\n' + '* { margin: 0; padding: 0; box-sizing: border-box; }\n' + 'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #1e293b; }\n' + '.report-header { background: linear-gradient(135deg, #6C5CE7, #a29bfe); color: #fff; padding: 40px 20px; text-align: center; }\n' + '.report-header h1 { font-size: 24px; margin-bottom: 8px; }\n' + '.report-header p { font-size: 14px; opacity: 0.85; }\n' + '.report-footer { text-align: center; padding: 30px; color: #94a3b8; font-size: 12px; border-top: 1px solid #e2e8f0; margin-top: 40px; }\n' + cssText + '\n@media print { .report-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }\n' + '</style>\n</head>\n<body>\n' + '<div class="report-header">\n<h1>' + headerText + '</h1>\n' + '<p>' + dateStr + ' | \uba54\ud0c0\uc544\uc774\uc564\uc528 \ub85c\uc9c1 \ubd84\uc11d \uc2dc\uc2a4\ud15c</p>\n</div>\n' + '<div style="max-width:1200px; margin:0 auto; padding:20px;">\n' + bodyHtml + '</div>\n' + '<div class="report-footer">\n<p>\u00A9 2026 \uba54\ud0c0\uc544\uc774\uc564\uc528 \u2014 \ub85c\uc9c1 \ubd84\uc11d \uc2dc\uc2a4\ud15c | \ubcf8 \ubcf4\uace0\uc11c\ub294 \uc790\ub3d9 \uc0dd\uc131\ub418\uc5c8\uc2b5\ub2c8\ub2e4.</p>\n</div>\n' + '</body>\n</html>';
    } catch (e) {
      console.error('DOM capture failed:', e);
      return '';
    }
  };
  var handleSave = function () {
    setSaving(true);
    setMessage('');

    /* DOM 캡처로 HTML 보고서 생성 */
    var reportHtml = captureReportHtml();
    var payload = {
      keyword: keyword,
      product_url: productUrl || '',
      analysis_data: htmlDetailResult ? Object.assign({}, analysisData, {
        htmlDetail: trimHtmlDetail(htmlDetailResult)
      }) : analysisData,
      volume_data: volumeData || {},
      related_data: relatedData || {},
      shop_products: (shopProducts || []).slice(0, 20),
      advertiser_data: advertiserReport || {},
      report_html: reportHtml,
      detail_html: detailHtml || ''
    };
    if (saveMode === 'new') {
      if (!clientName.trim()) {
        setMessage('업체명을 입력해주세요.');
        setSaving(false);
        return;
      }
      payload.name = clientName.trim();
      api.post('/cd/quick-register', payload).then(function (res) {
        if (res.success) {
          setSuccess(true);
          setMessage(res.message);
        } else {
          var errMsg = typeof res.detail === 'string' ? res.detail : '저장에 실패했습니다.';
          setMessage(errMsg);
        }
        setSaving(false);
      }).catch(function (e) {
        setMessage('서버 오류가 발생했습니다.');
        setSaving(false);
      });
    } else {
      if (!selectedClientId) {
        setMessage('업체를 선택해주세요.');
        setSaving(false);
        return;
      }
      payload.client_id = selectedClientId;
      api.post('/cd/analyze', payload).then(function (res) {
        if (res.success) {
          setSuccess(true);
          setMessage(res.message);
        } else {
          var errMsg = typeof res.detail === 'string' ? res.detail : '저장에 실패했습니다.';
          setMessage(errMsg);
        }
        setSaving(false);
      }).catch(function (e) {
        setMessage('서버 오류가 발생했습니다.');
        setSaving(false);
      });
    }
  };
  var closeModal = function () {
    setShowModal(false);
    setMessage('');
    setSuccess(false);
    setClientName('');
    setSelectedClientId(null);
    setSaveMode('new');
  };
  return React.createElement('div', {
    id: 'sec-save-client',
    className: 'section',
    style: {
      paddingBottom: 20
    }
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    className: 'card',
    style: {
      padding: '24px 28px',
      background: 'linear-gradient(135deg, #6C5CE7 0%, #a29bfe 100%)',
      color: '#fff',
      textAlign: 'center',
      borderRadius: 14
    }
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 700,
      marginBottom: 8
    }
  }, '"' + keyword + '" 분석 결과를 업체에 저장하시겠습니까?'), React.createElement('div', {
    style: {
      fontSize: 13,
      opacity: 0.85,
      marginBottom: 16
    }
  }, '업체로 저장하면 업체관리 탭에서 일자별 분석 데이터가 누적됩니다.'), React.createElement('button', {
    onClick: function () {
      setShowModal(true);
    },
    style: {
      background: '#fff',
      color: '#6C5CE7',
      border: 'none',
      padding: '12px 32px',
      borderRadius: 10,
      fontSize: 15,
      fontWeight: 700,
      cursor: 'pointer',
      boxShadow: '0 2px 8px rgba(0,0,0,0.15)'
    }
  }, '업체 등록 / 저장'))), /* 모달 */
  showModal && React.createElement('div', {
    style: {
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0,0,0,0.5)',
      zIndex: 9999,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    },
    onClick: function (e) {
      if (e.target === e.currentTarget) closeModal();
    }
  }, React.createElement('div', {
    className: 'responsive-modal',
    style: {
      background: '#fff',
      borderRadius: 16,
      padding: 28,
      width: 420,
      maxWidth: '92vw',
      boxShadow: '0 20px 60px rgba(0,0,0,0.3)'
    }
  }, /* 헤더 */
  React.createElement('div', {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 20
    }
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 700,
      color: '#1e293b'
    }
  }, '업체 등록 / 분석 저장'), React.createElement('button', {
    onClick: closeModal,
    style: {
      background: 'none',
      border: 'none',
      fontSize: 20,
      cursor: 'pointer',
      color: '#94a3b8'
    }
  }, '\u2715')), /* 분석 키워드 표시 */
  React.createElement('div', {
    style: {
      background: '#f8fafc',
      borderRadius: 10,
      padding: '12px 16px',
      marginBottom: 16,
      fontSize: 13,
      color: '#475569'
    }
  }, React.createElement('span', {
    style: {
      fontWeight: 600
    }
  }, '키워드: '), keyword, productUrl && React.createElement('span', null, ' | URL: ' + (productUrl.length > 40 ? productUrl.slice(0, 40) + '...' : productUrl))), /* 성공 메시지 */
  success ? React.createElement('div', null, React.createElement('div', {
    style: {
      background: '#f0fdf4',
      border: '1px solid #bbf7d0',
      borderRadius: 10,
      padding: '20px',
      textAlign: 'center',
      marginBottom: 16
    }
  }, React.createElement('div', {
    style: {
      fontSize: 32,
      marginBottom: 8
    }
  }, '\u2705'), React.createElement('div', {
    style: {
      fontSize: 15,
      fontWeight: 600,
      color: '#16a34a'
    }
  }, message)), React.createElement('button', {
    onClick: closeModal,
    style: {
      width: '100%',
      padding: '12px',
      borderRadius: 10,
      border: 'none',
      background: '#6C5CE7',
      color: '#fff',
      fontSize: 14,
      fontWeight: 600,
      cursor: 'pointer'
    }
  }, '확인'))

  /* 입력 폼 */ : React.createElement('div', null, /* 탭: 새 업체 / 기존 업체 */
  React.createElement('div', {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 16
    }
  }, React.createElement('button', {
    onClick: function () {
      setSaveMode('new');
    },
    style: {
      flex: 1,
      padding: '10px',
      borderRadius: 8,
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      background: saveMode === 'new' ? '#6C5CE7' : '#f1f5f9',
      color: saveMode === 'new' ? '#fff' : '#64748b',
      border: saveMode === 'new' ? '1px solid #6C5CE7' : '1px solid #e2e8f0'
    }
  }, '새 업체 등록'), React.createElement('button', {
    onClick: function () {
      setSaveMode('existing');
    },
    style: {
      flex: 1,
      padding: '10px',
      borderRadius: 8,
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      background: saveMode === 'existing' ? '#6C5CE7' : '#f1f5f9',
      color: saveMode === 'existing' ? '#fff' : '#64748b',
      border: saveMode === 'existing' ? '1px solid #6C5CE7' : '1px solid #e2e8f0'
    }
  }, '기존 업체에 추가 (' + existingClients.length + ')')), /* 새 업체 입력 */
  saveMode === 'new' && React.createElement('div', null, React.createElement('label', {
    style: {
      fontSize: 13,
      color: '#475569',
      fontWeight: 600,
      display: 'block',
      marginBottom: 6
    }
  }, '업체명'), React.createElement('input', {
    className: 'form-input',
    value: clientName,
    onChange: function (e) {
      setClientName(e.target.value);
    },
    placeholder: '업체명을 입력하세요',
    style: {
      width: '100%',
      marginBottom: 4
    },
    autoFocus: true
  }), React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      marginBottom: 16
    }
  }, '같은 이름의 업체가 있으면 해당 업체에 분석이 추가됩니다.')), /* 기존 업체 선택 */
  saveMode === 'existing' && React.createElement('div', {
    style: {
      marginBottom: 16
    }
  }, existingClients.length === 0 ? React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: 20,
      color: '#94a3b8',
      fontSize: 13
    }
  }, '등록된 업체가 없습니다. 새 업체를 등록해주세요.') : React.createElement('div', {
    style: {
      maxHeight: 200,
      overflowY: 'auto'
    }
  }, existingClients.map(function (c) {
    var isSelected = selectedClientId === c.id;
    return React.createElement('div', {
      key: c.id,
      onClick: function () {
        setSelectedClientId(c.id);
      },
      style: {
        padding: '10px 14px',
        borderRadius: 8,
        cursor: 'pointer',
        marginBottom: 4,
        background: isSelected ? '#6C5CE7' : '#f8fafc',
        color: isSelected ? '#fff' : '#1e293b',
        border: '1px solid ' + (isSelected ? '#6C5CE7' : '#e2e8f0')
      }
    }, React.createElement('div', {
      style: {
        fontWeight: 600,
        fontSize: 14
      }
    }, c.name), c.main_keywords && React.createElement('div', {
      style: {
        fontSize: 11,
        opacity: 0.7,
        marginTop: 2
      }
    }, c.main_keywords));
  }))), /* 오류 메시지 */
  message && !success && React.createElement('div', {
    style: {
      color: '#dc2626',
      fontSize: 13,
      marginBottom: 12,
      padding: '8px 12px',
      background: '#fef2f2',
      borderRadius: 8
    }
  }, message), /* 저장 버튼 */
  React.createElement('button', {
    onClick: handleSave,
    disabled: saving,
    style: {
      width: '100%',
      padding: '12px',
      borderRadius: 10,
      border: 'none',
      background: saving ? '#94a3b8' : '#6C5CE7',
      color: '#fff',
      fontSize: 14,
      fontWeight: 600,
      cursor: saving ? 'default' : 'pointer'
    }
  }, saving ? '저장 중...' : '분석 결과 저장')))));
};

;/* ===== js/components/ClientListSection.jsx ===== */
/* ClientListSection — 메인 분석 페이지 업체 리스트 (v3.7)
 * 등록된 업체 카드를 가나다순으로 표시하고, 클릭 시 자동 분석 실행
 */
window.ClientListSection = function ClientListSection({
  currentUser,
  onClientClick,
  onNavigateToClient
}) {
  var useState = React.useState;
  var useEffect = React.useEffect;
  var useCallback = React.useCallback;
  var _s1 = useState([]);
  var clients = _s1[0];
  var setClients = _s1[1];
  var _s2 = useState(true);
  var loading = _s2[0];
  var setLoading = _s2[1];
  var _s3 = useState('');
  var query = _s3[0];
  var setQuery = _s3[1];
  var _s4 = useState(null);
  var mgrFilter = _s4[0];
  var setMgrFilter = _s4[1]; // 담당자 탭 필터(null=전체)

  // 상위 계정(관리자)만 담당자(등록 직원) 정보를 노출 (매니저는 본인 것만 보므로 불필요)
  var isAdmin = !!(currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin'));

  /* 업체 목록 로드 */
  var loadClients = useCallback(function () {
    setLoading(true);
    api.get('/cd/my-clients').then(function (res) {
      if (res.success) setClients(res.data || []);
      setLoading(false);
    }).catch(function () {
      setLoading(false);
    });
  }, []);
  useEffect(function () {
    loadClients();
  }, [loadClients]);

  /* 업체에서 대표 키워드/상품URL 추출 */
  var getClientAnalysisParams = function (client) {
    // 1순위: 최근 분석한 키워드 + URL
    if (client.analyzed_keywords && client.analyzed_keywords.length > 0) {
      var latest = client.analyzed_keywords[0]; // 서버에서 analyzed_date DESC 정렬
      return {
        keyword: latest.keyword,
        productUrl: latest.product_url || '',
        companyName: client.name,
        clientId: client.id,
        lastDate: latest.analyzed_date || ''
      };
    }
    // 2순위: main_keywords에서 첫 키워드
    if (client.main_keywords) {
      var firstKw = String(client.main_keywords).split(',')[0].trim();
      if (firstKw) {
        return {
          keyword: firstKw,
          productUrl: client.naver_store_url || '',
          companyName: client.name,
          clientId: client.id,
          lastDate: ''
        };
      }
    }
    return null;
  };

  /* 대표 키워드 텍스트 */
  var getRepresentativeKeyword = function (client) {
    if (client.analyzed_keywords && client.analyzed_keywords.length > 0) {
      return client.analyzed_keywords[0].keyword;
    }
    if (client.main_keywords) {
      return String(client.main_keywords).split(',')[0].trim();
    }
    return '-';
  };

  /* 마지막 분석 일자 텍스트 */
  var getLastAnalyzedText = function (client) {
    if (client.analyzed_keywords && client.analyzed_keywords.length > 0) {
      var d = client.analyzed_keywords[0].analyzed_date;
      return d || '-';
    }
    return '미분석';
  };

  /* 검색 + 가나다 정렬 */
  var filtered = clients.filter(function (c) {
    // 담당자 탭 필터 (null = 전체)
    if (mgrFilter && (c.manager_name || '(미지정)') !== mgrFilter) return false;
    if (!query.trim()) return true;
    var q = query.trim().toLowerCase();
    return (c.name || '').toLowerCase().indexOf(q) !== -1 || (c.main_keywords || '').toLowerCase().indexOf(q) !== -1;
  }).slice().sort(function (a, b) {
    return (a.name || '').localeCompare(b.name || '', 'ko');
  });

  /* 업체 상세 보기 핸들러 — 진행중 업체 탭 상세 화면으로 이동 */
  var handleViewClient = function (client) {
    if (onNavigateToClient) {
      onNavigateToClient(client.name || '', client.naver_store_url || '');
    }
  };

  /* ==================== 렌더링 ==================== */
  return React.createElement('div', {
    className: 'section',
    style: {
      paddingTop: 24,
      paddingBottom: 24
    }
  }, React.createElement('div', {
    className: 'container'
  }, /* 헤더 */
  React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: 16,
      flexWrap: 'wrap',
      gap: 12
    }
  }, React.createElement('div', null, React.createElement('h2', {
    style: {
      fontSize: 20,
      fontWeight: 700,
      color: '#1e293b',
      margin: 0,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, '🏢 등록 업체', clients.length > 0 && React.createElement('span', {
    style: {
      fontSize: 14,
      fontWeight: 500,
      color: '#6366f1',
      marginLeft: 4
    }
  }, '(' + clients.length + '개)')), React.createElement('p', {
    style: {
      fontSize: 13,
      color: '#64748b',
      margin: '4px 0 0 0'
    }
  }, '업체 상세 보기를 클릭하면 분석 이력과 순위를 확인할 수 있습니다.')), React.createElement('input', {
    type: 'text',
    placeholder: '업체명/키워드 검색...',
    value: query,
    onChange: function (e) {
      setQuery(e.target.value);
    },
    style: {
      padding: '8px 14px',
      fontSize: 13,
      border: '1px solid #e2e8f0',
      borderRadius: 8,
      minWidth: 240,
      outline: 'none'
    }
  })), /* 담당자별 구분 탭 (상위 계정 전용) — 클릭 시 해당 담당자 업체만 모아보기 */
  isAdmin && !loading && clients.length > 0 && function () {
    var counts = {};
    clients.forEach(function (c) {
      var m = c.manager_name || '(미지정)';
      counts[m] = (counts[m] || 0) + 1;
    });
    var names = Object.keys(counts).sort(function (a, b) {
      return counts[b] - counts[a];
    });
    var mkTab = function (label, val, count) {
      var on = mgrFilter === val;
      return React.createElement('button', {
        key: label,
        onClick: function () {
          setMgrFilter(val);
        },
        style: {
          fontSize: 12,
          fontWeight: 700,
          padding: '6px 12px',
          borderRadius: 999,
          cursor: 'pointer',
          whiteSpace: 'nowrap',
          border: '1px solid ' + (on ? '#6d28d9' : '#e9d5ff'),
          background: on ? '#6d28d9' : '#faf5ff',
          color: on ? '#fff' : '#6d28d9'
        }
      }, label + (count != null ? ' ' + count : ''));
    };
    return React.createElement('div', {
      style: {
        display: 'flex',
        gap: 8,
        flexWrap: 'wrap',
        alignItems: 'center',
        marginBottom: 16,
        paddingBottom: 14,
        borderBottom: '1px dashed #e2e8f0'
      }
    }, React.createElement('span', {
      style: {
        fontSize: 12,
        color: '#94a3b8',
        fontWeight: 700,
        marginRight: 2
      }
    }, '담당자별 보기'), mkTab('전체', null, clients.length), names.map(function (m) {
      return mkTab('👤 ' + m, m, counts[m]);
    }));
  }(), /* 로딩 */
  loading && React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: '40px 20px',
      color: '#64748b',
      fontSize: 14
    }
  }, '업체 목록 불러오는 중...'), /* 빈 상태 */
  !loading && filtered.length === 0 && clients.length === 0 && React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: '40px 20px',
      background: '#f8fafc',
      borderRadius: 12,
      border: '1px dashed #cbd5e1'
    }
  }, React.createElement('div', {
    style: {
      fontSize: 40,
      marginBottom: 8
    }
  }, '📋'), React.createElement('div', {
    style: {
      fontSize: 14,
      color: '#475569',
      fontWeight: 600,
      marginBottom: 4
    }
  }, '등록된 업체가 없습니다'), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#94a3b8'
    }
  }, '상단에서 직접 키워드를 입력해 분석하거나, 업체관리 탭에서 업체를 먼저 등록해주세요.')), /* 검색 결과 없음 */
  !loading && filtered.length === 0 && clients.length > 0 && React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: '30px 20px',
      color: '#94a3b8',
      fontSize: 13
    }
  }, '검색 결과가 없습니다.'), /* 업체 카드 그리드 */
  !loading && filtered.length > 0 && React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
      gap: 14
    }
  }, filtered.map(function (client) {
    var lastDate = getLastAnalyzedText(client);
    return React.createElement('div', {
      key: client.id,
      style: {
        background: '#fff',
        border: '1px solid #e2e8f0',
        borderRadius: 12,
        padding: '16px 18px',
        transition: 'all 0.15s ease',
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between'
      },
      onMouseEnter: function (e) {
        e.currentTarget.style.borderColor = '#6c5ce7';
        e.currentTarget.style.boxShadow = '0 4px 12px rgba(108,92,231,0.15)';
        e.currentTarget.style.transform = 'translateY(-2px)';
      },
      onMouseLeave: function (e) {
        e.currentTarget.style.borderColor = '#e2e8f0';
        e.currentTarget.style.boxShadow = '0 1px 2px rgba(0,0,0,0.04)';
        e.currentTarget.style.transform = 'translateY(0)';
      }
    }, /* 업체명 + 마지막 분석 */
    React.createElement('div', null, React.createElement('div', {
      style: {
        fontSize: 15,
        fontWeight: 700,
        color: '#1e293b',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        marginBottom: 6
      }
    }, client.name || '(이름 없음)'), React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#dc2626',
        marginBottom: isAdmin ? 4 : 12
      }
    }, '마지막 분석: ' + lastDate), isAdmin && React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#6d28d9',
        fontWeight: 700,
        marginBottom: 12
      }
    }, '👤 담당자: ' + (client.manager_name || '-'))), /* 업체 상세 보기 버튼 */
    React.createElement('button', {
      onClick: function () {
        handleViewClient(client);
      },
      style: {
        display: 'block',
        width: '100%',
        textAlign: 'center',
        background: '#6c5ce7',
        color: '#fff',
        border: 'none',
        padding: '8px 0',
        borderRadius: 8,
        fontSize: 12,
        fontWeight: 600,
        cursor: 'pointer'
      }
    }, '업체 상세 보기 →'));
  }))));
};

;/* ===== js/components/LoginPage.jsx ===== */
window.LoginPage = function LoginPage(props) {
  var React = window.React;
  var useState = React.useState;
  var username = useState('');
  var usernameValue = username[0];
  var setUsername = username[1];
  var password = useState('');
  var passwordValue = password[0];
  var setPassword = password[1];
  var error = useState('');
  var errorValue = error[0];
  var setError = error[1];
  var loading = useState(false);
  var loadingValue = loading[0];
  var setLoading = loading[1];
  var handleSubmit = function (e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    if (!usernameValue.trim() || !passwordValue.trim()) {
      setError('아이디와 비밀번호를 입력해주세요');
      setLoading(false);
      return;
    }

    // 로그인 요청 (15초 타임아웃)
    var controller = new AbortController();
    var timeout = setTimeout(function () {
      controller.abort();
    }, 15000);
    fetch('/api/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        username: usernameValue,
        password: passwordValue
      }),
      signal: controller.signal
    }).then(function (r) {
      clearTimeout(timeout);
      return r.json().then(function (body) {
        body._status = r.status;
        return body;
      });
    }).then(function (data) {
      setLoading(false);
      if (data._status !== 200 || data.success === false) {
        setError(data.detail || data.message || '아이디 또는 비밀번호가 올바르지 않습니다.');
        return;
      }
      if (props.onLogin) {
        props.onLogin(data.user, data.token);
      }
    }).catch(function (err) {
      clearTimeout(timeout);
      setLoading(false);
      if (err.name === 'AbortError') {
        setError('서버 응답 시간 초과 — 잠시 후 다시 시도해주세요.');
      } else {
        setError('네트워크 오류 — 인터넷 연결을 확인해주세요.');
      }
    });
  };
  var styles = {
    container: {
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #6C5CE7 0%, #a29bfe 100%)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '"Noto Sans KR", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      padding: '20px'
    },
    card: {
      background: 'white',
      borderRadius: '12px',
      boxShadow: '0 10px 40px rgba(0, 0, 0, 0.15)',
      padding: '48px 40px',
      width: '100%',
      maxWidth: '400px'
    },
    header: {
      textAlign: 'center',
      marginBottom: '40px'
    },
    logo: {
      fontSize: '48px',
      marginBottom: '16px'
    },
    title: {
      fontSize: '28px',
      fontWeight: '700',
      color: '#2d3436',
      marginBottom: '8px'
    },
    subtitle: {
      fontSize: '14px',
      color: '#636e72',
      marginBottom: '16px'
    },
    badge: {
      display: 'inline-block',
      background: '#6C5CE7',
      color: 'white',
      padding: '4px 12px',
      borderRadius: '20px',
      fontSize: '12px',
      fontWeight: '600'
    },
    form: {
      display: 'flex',
      flexDirection: 'column'
    },
    formGroup: {
      marginBottom: '20px'
    },
    inputWrapper: {
      display: 'flex',
      alignItems: 'center',
      border: '1px solid #dfe6e9',
      borderRadius: '8px',
      padding: '0 12px',
      transition: 'border-color 0.3s'
    },
    inputWrapperFocus: {
      borderColor: '#6C5CE7'
    },
    inputIcon: {
      marginRight: '12px',
      fontSize: '18px',
      color: '#6C5CE7'
    },
    input: {
      flex: 1,
      border: 'none',
      padding: '12px 0',
      fontSize: '14px',
      outline: 'none',
      fontFamily: 'inherit'
    },
    button: {
      background: '#6C5CE7',
      color: 'white',
      border: 'none',
      padding: '12px 24px',
      borderRadius: '8px',
      fontSize: '16px',
      fontWeight: '600',
      cursor: loadingValue ? 'not-allowed' : 'pointer',
      transition: 'background 0.3s',
      opacity: loadingValue ? 0.7 : 1,
      marginTop: '12px'
    },
    buttonHover: {
      background: '#5f3dc4'
    },
    error: {
      background: '#fff5f5',
      border: '1px solid #fab1a0',
      color: '#d63031',
      padding: '12px',
      borderRadius: '6px',
      fontSize: '14px',
      marginBottom: '20px',
      textAlign: 'center'
    },
    loadingText: {
      opacity: 0.7
    }
  };
  return React.createElement('div', {
    style: styles.container
  }, React.createElement('div', {
    style: styles.card
  }, React.createElement('div', {
    style: styles.header
  }, React.createElement('img', {
    src: '/img/logo_light.png',
    alt: 'META INC',
    style: {
      height: 48,
      width: 'auto',
      marginBottom: 16
    }
  }), React.createElement('div', {
    style: styles.title
  }, '로직 분석'), React.createElement('div', {
    style: styles.subtitle
  }, '네이버 쇼핑 키워드 분석 & 순위 추적'), React.createElement('div', {
    style: {
      marginTop: '16px'
    }
  }, React.createElement('span', {
    style: styles.badge
  }, (window.APP_VERSION || 'v3.9') + ' 에이전시'))), errorValue && React.createElement('div', {
    style: styles.error
  }, errorValue), React.createElement('form', {
    style: styles.form,
    onSubmit: handleSubmit
  }, React.createElement('div', {
    style: styles.formGroup
  }, React.createElement('div', {
    style: styles.inputWrapper
  }, React.createElement('span', {
    style: styles.inputIcon
  }, '👤'), React.createElement('input', {
    type: 'text',
    placeholder: '아이디',
    value: usernameValue,
    onChange: function (e) {
      setUsername(e.target.value);
    },
    style: styles.input,
    disabled: loadingValue
  }))), React.createElement('div', {
    style: styles.formGroup
  }, React.createElement('div', {
    style: styles.inputWrapper
  }, React.createElement('span', {
    style: styles.inputIcon
  }, '🔒'), React.createElement('input', {
    type: 'password',
    placeholder: '비밀번호',
    value: passwordValue,
    onChange: function (e) {
      setPassword(e.target.value);
    },
    style: styles.input,
    disabled: loadingValue
  }))), React.createElement('button', {
    type: 'submit',
    style: styles.button,
    disabled: loadingValue,
    onMouseEnter: function (e) {
      if (!loadingValue) e.target.style.background = styles.buttonHover.background;
    },
    onMouseLeave: function (e) {
      e.target.style.background = styles.button.background;
    }
  }, loadingValue ? '로그인 중...' : '로그인'))));
};

;/* ===== js/components/UserManagementPage.jsx ===== */
window.UserManagementPage = function UserManagementPage(props) {
  var useState = React.useState;
  var useEffect = React.useEffect;
  var currentUser = props.currentUser;
  var token = props.token;
  var _useState = useState([]);
  var users = _useState[0];
  var setUsers = _useState[1];
  var _useState2 = useState(false);
  var showModal = _useState2[0];
  var setShowModal = _useState2[1];
  var _useState3 = useState(null);
  var editingUser = _useState3[0];
  var setEditingUser = _useState3[1];
  var _useState4 = useState({
    username: '',
    name: '',
    password: '',
    role: 'viewer'
  });
  var formData = _useState4[0];
  var setFormData = _useState4[1];
  var _useState5 = useState('');
  var message = _useState5[0];
  var setMessage = _useState5[1];
  var _useState6 = useState(null);
  var expandedUserId = _useState6[0];
  var setExpandedUserId = _useState6[1];
  var _useState7 = useState([]);
  var loginLogs = _useState7[0];
  var setLoginLogs = _useState7[1];
  var _useState8 = useState(false);
  var logsLoading = _useState8[0];
  var setLogsLoading = _useState8[1];
  var _useState9 = useState({});
  var analysisCounts = _useState9[0];
  var setAnalysisCounts = _useState9[1];
  var _useState11 = useState({});
  var todayCounts = _useState11[0];
  var setTodayCounts = _useState11[1];
  var _useState10 = useState('all');
  var roleFilter = _useState10[0];
  var setRoleFilter = _useState10[1];

  // Fetch users + analysis counts on mount
  useEffect(function () {
    fetchUsers();
    fetchAnalysisCounts();
  }, []);
  var toggleLoginLogs = function (userId) {
    if (expandedUserId === userId) {
      setExpandedUserId(null);
      setLoginLogs([]);
      return;
    }
    setExpandedUserId(userId);
    setLogsLoading(true);
    setLoginLogs([]);
    api.get('/auth/users/' + userId + '/login-logs?days=7').then(function (data) {
      if (data.success) setLoginLogs(data.data || []);
      setLogsLoading(false);
    }).catch(function () {
      setLogsLoading(false);
    });
  };
  var fetchAnalysisCounts = function () {
    api.get('/auth/users/analysis-counts').then(function (data) {
      if (data.success) {
        setAnalysisCounts(data.data || {});
        setTodayCounts(data.today || {});
      }
    }).catch(function () {});
  };
  var fetchUsers = function () {
    api.get('/auth/users').then(function (data) {
      // 백엔드가 배열을 직접 반환하므로 배열/객체 모두 처리
      var userList = Array.isArray(data) ? data : data.users || [];
      setUsers(userList);
      setMessage('');
    }).catch(function (e) {
      setMessage('사용자 조회 실패: ' + (e.message || '네트워크 오류'));
    });
  };
  var handleOpenModal = function (user) {
    if (user) {
      setEditingUser(user);
      setFormData({
        username: user.username,
        name: user.name,
        password: '',
        role: user.role
      });
    } else {
      setEditingUser(null);
      setFormData({
        username: '',
        name: '',
        password: '',
        role: 'viewer'
      });
    }
    setShowModal(true);
  };
  var handleCloseModal = function () {
    setShowModal(false);
    setEditingUser(null);
    setFormData({
      username: '',
      name: '',
      password: '',
      role: 'viewer'
    });
  };
  var handleSaveUser = function () {
    if (!formData.username || !formData.name) {
      setMessage('아이디와 이름을 입력하세요.');
      return;
    }

    // 신규 등록 시 비밀번호 필수 검증
    if (!editingUser && (!formData.password || formData.password.length < 6)) {
      setMessage('비밀번호를 6자 이상 입력하세요.');
      return;
    }
    var url = editingUser ? '/api/auth/users/' + editingUser.id : '/api/auth/users';
    var method = editingUser ? 'PUT' : 'POST';
    var body = {
      username: formData.username,
      name: formData.name,
      role: formData.role
    };
    if (formData.password) {
      body.password = formData.password;
    }
    var apiCall = editingUser ? api.put('/auth/users/' + editingUser.id, body) : api.post('/auth/users', body);
    apiCall.then(function (data) {
      if (data && data.success === false) {
        setMessage('저장 실패: ' + (data.detail || '알 수 없는 오류'));
        return;
      }
      // 수정 모드에서 비밀번호가 입력된 경우 → 비밀번호 리셋 API 추가 호출
      if (editingUser && formData.password && formData.password.length >= 6) {
        api.put('/auth/users/' + editingUser.id + '/reset-password', {
          new_password: formData.password
        }).then(function (pwRes) {
          if (pwRes && pwRes.success) {
            setMessage('사용자 수정 + 비밀번호 변경 완료');
          } else {
            setMessage('사용자 수정 완료 (비밀번호 변경 실패: ' + (pwRes.detail || '오류') + ')');
          }
          handleCloseModal();
          fetchUsers();
        }).catch(function () {
          setMessage('사용자 수정 완료 (비밀번호 변경 실패)');
          handleCloseModal();
          fetchUsers();
        });
        return;
      }
      setMessage(editingUser ? '사용자 수정 완료' : '사용자 추가 완료');
      handleCloseModal();
      fetchUsers();
    }).catch(function (e) {
      setMessage('저장 실패: ' + (e.message || '네트워크 오류'));
    });
  };
  var handleDeleteUser = function (userId, username) {
    if (userId === currentUser.id) {
      setMessage('자신의 계정은 삭제할 수 없습니다.');
      return;
    }
    if (!window.confirm(username + ' 사용자를 삭제하시겠습니까?')) return;
    api.del('/auth/users/' + userId).then(function (data) {
      if (data && data.success === false) {
        setMessage('삭제 실패: ' + (data.detail || '알 수 없는 오류'));
        return;
      }
      setMessage('사용자 삭제 완료');
      fetchUsers();
    }).catch(function (e) {
      setMessage('삭제 실패: ' + (e.message || '네트워크 오류'));
    });
  };
  var getRoleBadge = function (role) {
    var roleMap = {
      admin: '관리자',
      manager: '매니저',
      viewer: '뷰어'
    };
    var roleColors = {
      admin: '#8B5CF6',
      manager: '#3B82F6',
      viewer: '#9CA3AF'
    };
    return React.createElement('span', {
      style: {
        backgroundColor: roleColors[role],
        color: 'white',
        padding: '4px 12px',
        borderRadius: '12px',
        fontSize: '12px',
        fontWeight: 'bold'
      }
    }, roleMap[role] || role);
  };
  var getStatusBadge = function (status) {
    var isActive = status === 'active';
    return React.createElement('span', {
      style: {
        backgroundColor: isActive ? '#10B981' : '#EF4444',
        color: 'white',
        padding: '4px 12px',
        borderRadius: '12px',
        fontSize: '12px'
      }
    }, isActive ? '활성' : '비활성');
  };
  return React.createElement('div', {
    style: {
      padding: '20px',
      fontFamily: 'sans-serif'
    }
  }, React.createElement('div', {
    style: {
      marginBottom: '20px'
    }
  }, React.createElement('h1', {
    style: {
      color: '#6B21A8',
      marginBottom: '20px'
    }
  }, '👥 직원 관리'), React.createElement('button', {
    onClick: function () {
      handleOpenModal(null);
    },
    style: {
      backgroundColor: '#8B5CF6',
      color: 'white',
      border: 'none',
      padding: '10px 20px',
      borderRadius: '6px',
      cursor: 'pointer',
      fontSize: '14px',
      fontWeight: 'bold'
    }
  }, '새 직원 추가')), message && React.createElement('div', {
    style: {
      backgroundColor: '#F0F9FF',
      border: '1px solid #8B5CF6',
      color: '#6B21A8',
      padding: '12px',
      borderRadius: '6px',
      marginBottom: '20px',
      fontSize: '14px'
    }
  }, message), /* 권한별 필터 탭 */
  React.createElement('div', {
    style: {
      display: 'flex',
      gap: '8px',
      marginBottom: '16px',
      flexWrap: 'wrap'
    }
  }, [{
    key: 'all',
    label: '전체',
    color: '#6B21A8'
  }, {
    key: 'admin',
    label: '관리자',
    color: '#8B5CF6'
  }, {
    key: 'manager',
    label: '매니저',
    color: '#3B82F6'
  }, {
    key: 'viewer',
    label: '뷰어',
    color: '#9CA3AF'
  }].map(function (tab) {
    var isActive = roleFilter === tab.key;
    var count = tab.key === 'all' ? users.length : users.filter(function (u) {
      return u.role === tab.key;
    }).length;
    return React.createElement('button', {
      key: tab.key,
      onClick: function () {
        setRoleFilter(tab.key);
      },
      style: {
        padding: '8px 20px',
        borderRadius: '8px',
        border: isActive ? '2px solid ' + tab.color : '1px solid #e5e7eb',
        background: isActive ? tab.color : '#fff',
        color: isActive ? '#fff' : '#374151',
        fontSize: '13px',
        fontWeight: isActive ? '700' : '500',
        cursor: 'pointer',
        transition: 'all 0.15s'
      }
    }, tab.label + ' (' + count + ')');
  })), React.createElement('div', {
    style: {
      overflowX: 'auto',
      backgroundColor: 'white',
      borderRadius: '8px',
      boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
    }
  }, React.createElement('table', {
    style: {
      width: '100%',
      borderCollapse: 'collapse',
      fontSize: '14px'
    }
  }, React.createElement('thead', {}, React.createElement('tr', {
    style: {
      backgroundColor: '#F3E8FF',
      borderBottom: '2px solid #8B5CF6'
    }
  }, React.createElement('th', {
    style: {
      padding: '12px',
      textAlign: 'left',
      fontWeight: 'bold',
      color: '#6B21A8'
    }
  }, '아이디'), React.createElement('th', {
    style: {
      padding: '12px',
      textAlign: 'left',
      fontWeight: 'bold',
      color: '#6B21A8'
    }
  }, '이름'), React.createElement('th', {
    style: {
      padding: '12px',
      textAlign: 'left',
      fontWeight: 'bold',
      color: '#6B21A8'
    }
  }, '역할'), React.createElement('th', {
    style: {
      padding: '12px',
      textAlign: 'left',
      fontWeight: 'bold',
      color: '#6B21A8'
    }
  }, '상태'), React.createElement('th', {
    style: {
      padding: '12px',
      textAlign: 'left',
      fontWeight: 'bold',
      color: '#6B21A8'
    }
  }, '등록일'), React.createElement('th', {
    style: {
      padding: '12px',
      textAlign: 'center',
      fontWeight: 'bold',
      color: '#6B21A8'
    }
  }, '당일'), React.createElement('th', {
    style: {
      padding: '12px',
      textAlign: 'center',
      fontWeight: 'bold',
      color: '#6B21A8'
    }
  }, '누적'), React.createElement('th', {
    style: {
      padding: '12px',
      textAlign: 'left',
      fontWeight: 'bold',
      color: '#6B21A8'
    }
  }, '액션'))), React.createElement('tbody', {}, users.filter(function (u) {
    return roleFilter === 'all' || u.role === roleFilter;
  }).map(function (user, idx) {
    var isExpanded = expandedUserId === user.id;
    return React.createElement(React.Fragment, {
      key: user.id
    }, React.createElement('tr', {
      style: {
        backgroundColor: isExpanded ? '#EDE9FE' : idx % 2 === 0 ? 'white' : '#F9F5FF',
        borderBottom: '1px solid #E9D5FF',
        cursor: 'pointer'
      },
      onClick: function () {
        toggleLoginLogs(user.id);
      }
    }, React.createElement('td', {
      style: {
        padding: '12px'
      }
    }, user.username), React.createElement('td', {
      style: {
        padding: '12px'
      }
    }, user.name), React.createElement('td', {
      style: {
        padding: '12px'
      }
    }, getRoleBadge(user.role)), React.createElement('td', {
      style: {
        padding: '12px'
      }
    }, getStatusBadge(user.status || 'active')), React.createElement('td', {
      style: {
        padding: '12px',
        fontSize: '12px',
        color: '#666'
      }
    }, new Date(user.created_at || user.createdAt).toLocaleDateString('ko-KR')), React.createElement('td', {
      style: {
        padding: '12px',
        textAlign: 'center'
      }
    }, React.createElement('span', {
      style: {
        display: 'inline-block',
        minWidth: 36,
        padding: '4px 10px',
        borderRadius: 999,
        fontSize: 13,
        fontWeight: 700,
        color: (todayCounts[String(user.id)] || 0) > 0 ? '#2563eb' : '#94a3b8',
        background: (todayCounts[String(user.id)] || 0) > 0 ? '#dbeafe' : '#f1f5f9'
      }
    }, String(todayCounts[String(user.id)] || 0) + '건')), React.createElement('td', {
      style: {
        padding: '12px',
        textAlign: 'center'
      }
    }, React.createElement('span', {
      style: {
        display: 'inline-block',
        minWidth: 36,
        padding: '4px 10px',
        borderRadius: 999,
        fontSize: 13,
        fontWeight: 700,
        color: (analysisCounts[String(user.id)] || 0) > 0 ? '#6c5ce7' : '#94a3b8',
        background: (analysisCounts[String(user.id)] || 0) > 0 ? '#ede9fe' : '#f1f5f9'
      }
    }, String(analysisCounts[String(user.id)] || 0) + '건')), React.createElement('td', {
      style: {
        padding: '12px'
      }
    }, React.createElement('button', {
      onClick: function (e) {
        e.stopPropagation();
        handleOpenModal(user);
      },
      style: {
        backgroundColor: '#8B5CF6',
        color: 'white',
        border: 'none',
        padding: '6px 12px',
        borderRadius: '4px',
        cursor: 'pointer',
        fontSize: '12px',
        marginRight: '6px'
      }
    }, '수정'), user.id !== currentUser.id && React.createElement('button', {
      onClick: function (e) {
        e.stopPropagation();
        handleDeleteUser(user.id, user.username);
      },
      style: {
        backgroundColor: '#EF4444',
        color: 'white',
        border: 'none',
        padding: '6px 12px',
        borderRadius: '4px',
        cursor: 'pointer',
        fontSize: '12px'
      }
    }, '삭제'))), isExpanded && React.createElement('tr', {
      key: user.id + '-logs'
    }, React.createElement('td', {
      colSpan: 8,
      style: {
        padding: '16px 20px',
        background: '#F5F3FF',
        borderBottom: '2px solid #C4B5FD'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 13,
        fontWeight: 600,
        color: '#6B21A8',
        marginBottom: 8
      }
    }, '📋 최근 7일 접속 이력 — ' + user.name + ' (' + user.username + ')'), logsLoading ? React.createElement('div', {
      style: {
        fontSize: 13,
        color: '#888'
      }
    }, '로딩 중...') : loginLogs.length === 0 ? React.createElement('div', {
      style: {
        fontSize: 13,
        color: '#94a3b8'
      }
    }, '최근 7일간 접속 기록이 없습니다.') : React.createElement('table', {
      style: {
        width: '100%',
        fontSize: 12,
        borderCollapse: 'collapse'
      }
    }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
      style: {
        padding: '6px 10px',
        textAlign: 'left',
        color: '#6B21A8',
        borderBottom: '1px solid #DDD6FE'
      }
    }, '접속 일시'), React.createElement('th', {
      style: {
        padding: '6px 10px',
        textAlign: 'left',
        color: '#6B21A8',
        borderBottom: '1px solid #DDD6FE'
      }
    }, 'IP 주소'))), React.createElement('tbody', null, loginLogs.map(function (log) {
      return React.createElement('tr', {
        key: log.id
      }, React.createElement('td', {
        style: {
          padding: '5px 10px',
          borderBottom: '1px solid #EDE9FE'
        }
      }, new Date(log.login_at).toLocaleString('ko-KR')), React.createElement('td', {
        style: {
          padding: '5px 10px',
          borderBottom: '1px solid #EDE9FE',
          color: '#64748b'
        }
      }, log.ip_address || '-'));
    }))))));
  })))), showModal && React.createElement('div', {
    style: {
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.5)',
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      zIndex: 1000
    }
  }, React.createElement('div', {
    style: {
      backgroundColor: 'white',
      padding: '24px',
      borderRadius: '8px',
      width: '90%',
      maxWidth: '400px',
      boxShadow: '0 10px 25px rgba(0,0,0,0.2)'
    }
  }, React.createElement('h2', {
    style: {
      color: '#6B21A8',
      marginBottom: '16px'
    }
  }, editingUser ? '직원 수정' : '새 직원 추가'), React.createElement('div', {
    style: {
      marginBottom: '12px'
    }
  }, React.createElement('label', {
    style: {
      display: 'block',
      fontSize: '12px',
      fontWeight: 'bold',
      color: '#666',
      marginBottom: '4px'
    }
  }, '아이디'), React.createElement('input', {
    type: 'text',
    value: formData.username,
    onChange: function (e) {
      setFormData(Object.assign({}, formData, {
        username: e.target.value
      }));
    },
    disabled: !!editingUser,
    style: {
      width: '100%',
      padding: '8px',
      border: '1px solid #D8B4FE',
      borderRadius: '4px',
      boxSizing: 'border-box',
      opacity: editingUser ? 0.6 : 1
    }
  })), React.createElement('div', {
    style: {
      marginBottom: '12px'
    }
  }, React.createElement('label', {
    style: {
      display: 'block',
      fontSize: '12px',
      fontWeight: 'bold',
      color: '#666',
      marginBottom: '4px'
    }
  }, '이름'), React.createElement('input', {
    type: 'text',
    value: formData.name,
    onChange: function (e) {
      setFormData(Object.assign({}, formData, {
        name: e.target.value
      }));
    },
    style: {
      width: '100%',
      padding: '8px',
      border: '1px solid #D8B4FE',
      borderRadius: '4px',
      boxSizing: 'border-box'
    }
  })), !editingUser && React.createElement('div', {
    style: {
      marginBottom: '12px'
    }
  }, React.createElement('label', {
    style: {
      display: 'block',
      fontSize: '12px',
      fontWeight: 'bold',
      color: '#666',
      marginBottom: '4px'
    }
  }, '비밀번호'), React.createElement('input', {
    type: 'password',
    value: formData.password,
    onChange: function (e) {
      setFormData(Object.assign({}, formData, {
        password: e.target.value
      }));
    },
    style: {
      width: '100%',
      padding: '8px',
      border: '1px solid #D8B4FE',
      borderRadius: '4px',
      boxSizing: 'border-box'
    }
  })), editingUser && React.createElement('div', {
    style: {
      marginBottom: '12px'
    }
  }, React.createElement('label', {
    style: {
      display: 'block',
      fontSize: '12px',
      fontWeight: 'bold',
      color: '#666',
      marginBottom: '4px'
    }
  }, '새 비밀번호 (선택)'), React.createElement('input', {
    type: 'password',
    value: formData.password,
    onChange: function (e) {
      setFormData(Object.assign({}, formData, {
        password: e.target.value
      }));
    },
    style: {
      width: '100%',
      padding: '8px',
      border: '1px solid #D8B4FE',
      borderRadius: '4px',
      boxSizing: 'border-box'
    }
  })), React.createElement('div', {
    style: {
      marginBottom: '16px'
    }
  }, React.createElement('label', {
    style: {
      display: 'block',
      fontSize: '12px',
      fontWeight: 'bold',
      color: '#666',
      marginBottom: '4px'
    }
  }, '역할'), React.createElement('select', {
    value: formData.role,
    onChange: function (e) {
      setFormData(Object.assign({}, formData, {
        role: e.target.value
      }));
    },
    style: {
      width: '100%',
      padding: '8px',
      border: '1px solid #D8B4FE',
      borderRadius: '4px',
      boxSizing: 'border-box'
    }
  }, React.createElement('option', {
    value: 'viewer'
  }, '뷰어'), React.createElement('option', {
    value: 'manager'
  }, '매니저'), React.createElement('option', {
    value: 'admin'
  }, '관리자'))), React.createElement('div', {
    style: {
      display: 'flex',
      gap: '8px',
      justifyContent: 'flex-end'
    }
  }, React.createElement('button', {
    onClick: handleCloseModal,
    style: {
      backgroundColor: '#E9D5FF',
      color: '#6B21A8',
      border: 'none',
      padding: '10px 20px',
      borderRadius: '4px',
      cursor: 'pointer',
      fontWeight: 'bold'
    }
  }, '취소'), React.createElement('button', {
    onClick: handleSaveUser,
    style: {
      backgroundColor: '#8B5CF6',
      color: 'white',
      border: 'none',
      padding: '10px 20px',
      borderRadius: '4px',
      cursor: 'pointer',
      fontWeight: 'bold'
    }
  }, '저장')))));
};

;/* ===== js/components/ClientDashboard.jsx ===== */
/* ClientDashboard — 업체별 분석 관리 대시보드 v4.0 (AI 인사이트 탭 추가) */
window.ClientDashboard = function ClientDashboard({
  currentUser,
  onRunAnalysis,
  onDownloadReport,
  initialSearch,
  canEdit
}) {
  const {
    useState,
    useEffect,
    useCallback
  } = React;
  const [clients, setClients] = useState([]);
  const [selectedClient, setSelectedClient] = useState(null);
  const [analyses, setAnalyses] = useState([]);
  const [rankHistory, setRankHistory] = useState([]);
  const [analysisHistory, setAnalysisHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [activeKeyword, setActiveKeyword] = useState(null);
  const [activeAnalysis, setActiveAnalysis] = useState(null);
  const [viewMode, setViewMode] = useState('history');
  const [message, setMessage] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportMenuRef = React.useRef(null);
  const [aiInsights, setAiInsights] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiSelectedKeyword, setAiSelectedKeyword] = useState(null);

  // 드롭다운 외부 클릭 시 닫기
  useEffect(function () {
    if (!showExportMenu) return;
    var handleClick = function (e) {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target)) {
        setShowExportMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return function () {
      document.removeEventListener('mousedown', handleClick);
    };
  }, [showExportMenu]);

  /* 업체 목록 로드 */
  var loadClients = useCallback(function () {
    setLoading(true);
    api.get('/cd/my-clients').then(function (res) {
      if (res.success) setClients(res.data || []);
      setLoading(false);
    }).catch(function () {
      setLoading(false);
    });
  }, []);
  useEffect(function () {
    loadClients();
  }, [loadClients]);

  /* initialSearch prop으로 순위추적에서 이동 시 해당 업체 자동 선택 */
  useEffect(function () {
    if (!initialSearch || !clients.length) return;
    var searchUrl = (initialSearch.productUrl || '').toLowerCase();
    var searchStore = (initialSearch.storeName || '').toLowerCase();
    if (!searchUrl && !searchStore) return;
    var matched = null;
    for (var i = 0; i < clients.length; i++) {
      var c = clients[i];
      var clientUrl = (c.naver_store_url || '').toLowerCase();
      var clientName = (c.name || '').toLowerCase();
      // URL 매칭 (부분 포함)
      if (searchUrl && clientUrl && (searchUrl.indexOf(clientUrl) !== -1 || clientUrl.indexOf(searchUrl) !== -1)) {
        matched = c;
        break;
      }
      // 스토어명 매칭
      if (searchStore && clientName && (searchStore.indexOf(clientName) !== -1 || clientName.indexOf(searchStore) !== -1)) {
        matched = c;
        break;
      }
    }
    if (matched) {
      selectClient(matched);
    } else if (searchStore) {
      setSearchQuery(searchStore);
    }
  }, [initialSearch, clients]);

  /* 업체 삭제 */
  var deleteClient = function (client, e) {
    e.stopPropagation();
    if (canEdit === false) {
      toast.error('삭제 권한이 없습니다.');
      return;
    }
    if (!confirm("'" + client.name + "' 업체를 삭제하시겠습니까?\n\n관련된 모든 분석 데이터와 순위 이력이 함께 삭제됩니다.\n이 작업은 되돌릴 수 없습니다.")) return;
    api.del('/cd/' + client.id).then(function (res) {
      if (res.success) {
        if (selectedClient && selectedClient.id === client.id) {
          setSelectedClient(null);
          setActiveKeyword(null);
          setActiveAnalysis(null);
        }
        loadClients();
      } else {
        alert(res.detail || '삭제에 실패했습니다.');
      }
    }).catch(function () {
      alert('서버 오류가 발생했습니다.');
    });
  };

  /* 업체 검색 필터 */
  var filteredClients = clients.filter(function (c) {
    if (!searchQuery.trim()) return true;
    var q = searchQuery.trim().toLowerCase();
    return (c.name || '').toLowerCase().indexOf(q) !== -1 || (c.main_keywords || '').toLowerCase().indexOf(q) !== -1 || (c.business_name || '').toLowerCase().indexOf(q) !== -1;
  });

  /* 업체 선택 → 저장된 분석 로드 (경량 summary 모드) */
  var selectClient = function (client) {
    setSelectedClient(client);
    setActiveKeyword(null);
    setActiveAnalysis(null);
    setRankHistory([]);
    setAnalysisHistory([]);
    setAiInsights(null);
    setAiSelectedKeyword(null);
    setViewMode('history');
    loadAnalyses(client.id);
    loadAiInsights(client.id);
  };
  var loadAnalyses = function (clientId) {
    api.get('/cd/' + clientId + '/analysis?summary=true').then(function (res) {
      if (res.success) setAnalyses(res.data || []);
    }).catch(function () {});
  };

  /* AI 인사이트 로드 */
  var loadAiInsights = function (clientId) {
    setAiLoading(true);
    setAiInsights(null);
    api.get('/cd/' + clientId + '/ai-insights').then(function (res) {
      if (res.success) {
        setAiInsights(res.data || res);
        // 키워드별 인사이트가 있으면 첫 번째 키워드 자동 선택
        var kwInsights = (res.data || res).keywordInsights;
        if (kwInsights) {
          var firstKw = Object.keys(kwInsights)[0];
          if (firstKw) setAiSelectedKeyword(firstKw);
        }
      }
      setAiLoading(false);
    }).catch(function () {
      setAiLoading(false);
    });
  };

  /* 키워드별 고유 목록 추출 */
  var getUniqueKeywords = function () {
    var kwMap = {};
    analyses.forEach(function (a) {
      if (!kwMap[a.keyword] || a.analyzed_date > kwMap[a.keyword].analyzed_date) {
        kwMap[a.keyword] = a;
      }
    });
    return Object.values(kwMap);
  };

  /* 키워드 분석 실행 + 저장 */
  var runAnalysis = function (keyword, productUrl) {
    if (!selectedClient || !keyword) return;
    setAnalyzing(true);
    setMessage('');
    Promise.all([api.post('/keyword/volume', [keyword]).catch(function () {
      return null;
    }), api.post('/keywords/related', {
      keyword: keyword
    }).catch(function () {
      return null;
    }), api.post('/products/search', {
      keyword: keyword,
      count: 40
    }).catch(function () {
      return null;
    })]).then(function (results) {
      var volRes = results[0];
      var relRes = results[1];
      var shopRes = results[2];
      var vol = volRes && volRes.success && volRes.data && volRes.data[0] ? volRes.data[0] : null;
      var totalVol = vol ? (vol.monthlyPcQcCnt || 0) + (vol.monthlyMobileQcCnt || 0) : 0;
      var prods = shopRes && shopRes.success && shopRes.data ? shopRes.data.products || [] : [];
      var rd = relRes && relRes.success ? relRes.data : null;
      var productCount = shopRes && shopRes.success && shopRes.data ? shopRes.data.total || prods.length : prods.length;
      var analysis = {};
      if (productCount > 0 && totalVol > 0) {
        var compIdx = (productCount / totalVol).toFixed(2);
        analysis.competitionIndex = {
          compIndex: parseFloat(compIdx),
          compLabel: compIdx < 0.5 ? '블루오션' : compIdx < 1.0 ? '보통' : '레드오션',
          compColor: compIdx < 0.5 ? '#16a34a' : compIdx < 1.0 ? '#d97706' : '#dc2626',
          productCount: productCount,
          searchVolume: totalVol
        };
      }
      if (prods.length > 0) {
        var prices = prods.map(function (p) {
          return p.price;
        }).filter(function (p) {
          return p > 0;
        });
        var avgPrice = prices.length > 0 ? Math.round(prices.reduce(function (a, b) {
          return a + b;
        }, 0) / prices.length) : 0;
        analysis.marketRevenue = {
          avgPrice: avgPrice,
          estimatedMonthly: avgPrice * totalVol
        };
      }
      if (totalVol > 0) {
        analysis.summaryCards = {
          totalVolume: totalVol,
          productCount: productCount,
          compLevel: analysis.competitionIndex ? analysis.competitionIndex.compLabel : '-'
        };
      }
      if (vol) {
        analysis.advertiserInfo = {
          adDepth: vol.plAvgDepth || 0,
          pcClicks: (vol.monthlyAvePcClkCnt || 0).toFixed(1),
          mobileClicks: (vol.monthlyAveMobileClkCnt || 0).toFixed(1),
          compIdx: vol.compIdx || '-'
        };
      }
      api.post('/cd/analyze', {
        client_id: selectedClient.id,
        keyword: keyword,
        product_url: productUrl || '',
        analysis_data: analysis,
        volume_data: volRes && volRes.success ? volRes.data : {},
        related_data: rd || {},
        shop_products: prods.slice(0, 20),
        advertiser_data: vol || {}
      }).then(function (saveRes) {
        setMessage(saveRes.message || '저장 완료');
        loadAnalyses(selectedClient.id);
        viewKeywordAnalysis(keyword);
        if (productUrl && prods.length > 0) {
          var found = null;
          var pid = extractPid(productUrl);
          for (var i = 0; i < prods.length; i++) {
            if (prods[i].product_id === pid || prods[i].product_url && prods[i].product_url.indexOf(pid) !== -1) {
              found = {
                rank: prods[i].rank,
                page: 1
              };
              break;
            }
          }
          if (found) {
            api.post('/cd/rank-save', {
              client_id: selectedClient.id,
              keyword: keyword,
              product_url: productUrl,
              rank_position: found.rank,
              page_number: found.page
            });
          }
        }
        setAnalyzing(false);
      }).catch(function () {
        setAnalyzing(false);
      });
    }).catch(function () {
      setAnalyzing(false);
    });
  };
  function extractPid(url) {
    var m = url.match(/products\/(\d+)/);
    return m ? m[1] : url;
  }

  /* 키워드별 분석 보기 (히스토리 + 순위 병렬 로드) */
  var viewKeywordAnalysis = function (keyword) {
    if (!selectedClient) return;
    setActiveKeyword(keyword);
    setViewMode('history');

    /* 병렬 로드: 히스토리 + 순위 이력을 동시에 요청 */
    var historyReq = api.get('/cd/' + selectedClient.id + '/history?keyword=' + encodeURIComponent(keyword)).catch(function () {
      return {
        success: false
      };
    });
    var rankReq = api.get('/cd/' + selectedClient.id + '/rank-history?keyword=' + encodeURIComponent(keyword)).catch(function () {
      return {
        success: false
      };
    });
    Promise.all([historyReq, rankReq]).then(function (results) {
      if (results[0] && results[0].success) setAnalysisHistory(results[0].data || []);
      if (results[1] && results[1].success) setRankHistory(results[1].data || []);
    });
  };

  /* HTML 보고서 다운로드 — 저장된 HTML 사용 */
  var downloadReport = function (dateStr) {
    if (!selectedClient || !activeKeyword) return;
    var targetDate = dateStr || activeAnalysis && activeAnalysis.analyzed_date || '';
    if (!targetDate) {
      alert('보고서 날짜를 확인할 수 없습니다.');
      return;
    }
    api.get('/cd/' + selectedClient.id + '/report-html?keyword=' + encodeURIComponent(activeKeyword) + '&date=' + targetDate).then(function (res) {
      if (res.success && res.html) {
        var blob = new Blob([res.html], {
          type: 'text/html;charset=utf-8'
        });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = (selectedClient.name || '업체') + '_' + activeKeyword + '_보고서_' + targetDate + '.html';
        a.click();
        URL.revokeObjectURL(a.href);
      } else {
        alert('해당 날짜의 HTML 보고서가 없습니다.\n분석 탭에서 업체 저장 시 보고서가 자동 생성됩니다.');
      }
    }).catch(function () {
      alert('보고서를 불러올 수 없습니다.');
    });
  };
  var exportReport = function () {
    downloadReport(null);
  };
  function _fmt(n) {
    return n != null ? Number(n).toLocaleString('ko-KR') : '-';
  }

  /* ========== 순위 이력 이미지 내보내기 ========== */
  var exportRankImage = function (days) {
    setShowExportMenu(false);
    if (!selectedClient || !activeKeyword || rankHistory.length === 0) return;
    // 공용 헬퍼로 통합 — 순위 추적 페이지와 동일한 이미지 생성
    window.exportRankHistoryImage({
      rows: rankHistory,
      storeName: selectedClient.name || '업체명',
      keyword: activeKeyword,
      storeUrl: selectedClient.naver_store_url || '',
      days: days
    });
  };
  var uniqueKeywords = getUniqueKeywords();

  /* ==================== 렌더링 ==================== */
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: 'calc(100vh - 60px)',
      background: '#f0f2f5'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "container cd-layout",
    style: {
      display: 'flex',
      gap: 20,
      paddingTop: 20,
      minHeight: 'calc(100vh - 80px)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "cd-sidebar",
    style: {
      width: 280,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16,
      fontWeight: 700,
      marginBottom: 12
    }
  }, "\uB0B4 \uC5C5\uCCB4 \uBAA9\uB85D (", clients.length, ")"), clients.length > 3 && /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "\uC5C5\uCCB4\uBA85 / \uD0A4\uC6CC\uB4DC \uAC80\uC0C9...",
    value: searchQuery,
    onChange: function (e) {
      setSearchQuery(e.target.value);
    },
    style: {
      width: '100%',
      marginBottom: 10,
      fontSize: 13,
      padding: '8px 12px'
    }
  }), loading && /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#64748b',
      fontSize: 13
    }
  }, "\uB85C\uB529 \uC911..."), !loading && clients.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#94a3b8',
      fontSize: 13,
      padding: '20px 0',
      textAlign: 'center'
    }
  }, "\uB4F1\uB85D\uB41C \uC5C5\uCCB4\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.", /*#__PURE__*/React.createElement("br", null), "\uBD84\uC11D \uD0ED\uC5D0\uC11C \uC5C5\uCCB4\uB97C \uB4F1\uB85D\uD574\uC8FC\uC138\uC694."), !loading && clients.length > 0 && filteredClients.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#94a3b8',
      fontSize: 13,
      padding: '20px 0',
      textAlign: 'center'
    }
  }, "\uAC80\uC0C9 \uACB0\uACFC\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4."), /*#__PURE__*/React.createElement("div", {
    style: {
      maxHeight: 'calc(100vh - 220px)',
      overflowY: 'auto'
    }
  }, filteredClients.map(function (c) {
    var isActive = selectedClient && selectedClient.id === c.id;
    return /*#__PURE__*/React.createElement("div", {
      key: c.id,
      onClick: function () {
        selectClient(c);
      },
      style: {
        padding: '12px 14px',
        borderRadius: 8,
        cursor: 'pointer',
        marginBottom: 6,
        background: isActive ? '#1B2A4A' : '#f8fafc',
        color: isActive ? '#fff' : '#1e293b',
        border: '1px solid ' + (isActive ? '#1B2A4A' : '#e2e8f0'),
        transition: 'all 0.15s'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontWeight: 600,
        fontSize: 14
      }
    }, c.name || c.business_name), currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin') && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: '#a78bfa',
        fontWeight: 700,
        marginTop: 2
      }
    }, "\uD83D\uDC64 \uB2F4\uB2F9\uC790: ", c.manager_name || '-'), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        opacity: 0.7,
        marginTop: 2
      }
    }, c.unique_keyword_count > 0 ? '키워드 ' + c.unique_keyword_count + '개' : '', c.total_analysis_days > 0 ? ' | ' + c.total_analysis_days + '일 분석' : '', !c.unique_keyword_count && !c.total_analysis_days ? '미분석' : ''), c.main_keywords && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        opacity: 0.6,
        marginTop: 4,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, c.main_keywords)), canEdit !== false && /*#__PURE__*/React.createElement("button", {
      onClick: function (e) {
        deleteClient(c, e);
      },
      title: "\uC5C5\uCCB4 \uC0AD\uC81C",
      style: {
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        padding: '2px 6px',
        fontSize: 14,
        color: isActive ? 'rgba(255,255,255,0.5)' : '#cbd5e1',
        flexShrink: 0,
        lineHeight: 1
      },
      onMouseOver: function (e) {
        e.target.style.color = '#ef4444';
      },
      onMouseOut: function (e) {
        e.target.style.color = isActive ? 'rgba(255,255,255,0.5)' : '#cbd5e1';
      }
    }, '\u2715')));
  })))), /*#__PURE__*/React.createElement("div", {
    className: "cd-main",
    style: {
      flex: 1,
      minWidth: 0
    }
  }, !selectedClient && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 40,
      textAlign: 'center',
      color: '#94a3b8'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 48,
      marginBottom: 12
    }
  }, "\uD83D\uDCCA"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16
    }
  }, "\uC88C\uCE21\uC5D0\uC11C \uC5C5\uCCB4\uB97C \uC120\uD0DD\uD558\uC138\uC694"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      marginTop: 8
    }
  }, "\uBD84\uC11D \uD0ED\uC5D0\uC11C \uD0A4\uC6CC\uB4DC \uBD84\uC11D \uD6C4 \uC5C5\uCCB4\uB97C \uB4F1\uB85D\uD558\uBA74 \uC5EC\uAE30\uC5D0 \uD45C\uC2DC\uB429\uB2C8\uB2E4.")), selectedClient && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 20,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 20,
      fontWeight: 700
    }
  }, selectedClient.name), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: '#64748b',
      marginTop: 4
    }
  }, selectedClient.main_keywords && /*#__PURE__*/React.createElement("span", null, "\uD0A4\uC6CC\uB4DC: ", selectedClient.main_keywords), selectedClient.naver_store_url && /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 12
    }
  }, "URL: ", function () {
    try {
      var u = new URL(selectedClient.naver_store_url);
      if (u.hostname.indexOf('smartstore.naver.com') !== -1) return u.origin + u.pathname;
    } catch (e) {}
    return selectedClient.naver_store_url.length > 60 ? selectedClient.naver_store_url.slice(0, 60) + '...' : selectedClient.naver_store_url;
  }()))), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#94a3b8'
    }
  }, selectedClient.last_analyzed && '마지막 분석: ' + selectedClient.last_analyzed.slice(0, 10)))), canEdit !== false && /*#__PURE__*/React.createElement(AnalysisForm, {
    client: selectedClient,
    onAnalyze: onRunAnalysis ? function (keyword, productUrl) {
      /* 분석 탭으로 전환하여 실제 분석 실행 + 자동 저장 */
      var params = {
        keyword: keyword,
        productUrl: productUrl || '',
        companyName: selectedClient.name || '',
        clientId: selectedClient.id,
        detailHtml: selectedClient.detail_html || '' // #1: 저장된 상세HTML 재사용
      };
      onRunAnalysis(params);
    } : runAnalysis,
    analyzing: analyzing,
    message: message
  }), uniqueKeywords.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 16,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      marginBottom: 12
    }
  }, "\uBD84\uC11D \uD0A4\uC6CC\uB4DC (", uniqueKeywords.length, "\uAC1C)"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      flexWrap: 'wrap'
    }
  }, uniqueKeywords.map(function (a, i) {
    var isActive = activeKeyword === a.keyword;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      onClick: function () {
        viewKeywordAnalysis(a.keyword);
      },
      style: {
        padding: '8px 16px',
        borderRadius: 20,
        cursor: 'pointer',
        fontSize: 13,
        background: isActive ? '#1B2A4A' : '#f1f5f9',
        color: isActive ? '#fff' : '#475569',
        border: isActive ? '1px solid #1B2A4A' : '1px solid #e2e8f0'
      }
    }, a.keyword, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        opacity: 0.7,
        marginLeft: 6
      }
    }, (a.analyzed_date || '').slice(0, 10)));
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: function () {
      setViewMode('history');
    },
    style: {
      padding: '8px 18px',
      borderRadius: 8,
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      background: viewMode === 'history' ? '#1B2A4A' : '#fff',
      color: viewMode === 'history' ? '#fff' : '#475569',
      border: viewMode === 'history' ? 'none' : '1px solid #e2e8f0'
    }
  }, '📊', " \uC77C\uC790\uBCC4 \uCD94\uC774 ", activeKeyword ? '(' + analysisHistory.length + '일)' : ''), /*#__PURE__*/React.createElement("button", {
    onClick: function () {
      setViewMode('rank');
    },
    style: {
      padding: '8px 18px',
      borderRadius: 8,
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      background: viewMode === 'rank' ? '#1B2A4A' : '#fff',
      color: viewMode === 'rank' ? '#fff' : '#475569',
      border: viewMode === 'rank' ? 'none' : '1px solid #e2e8f0'
    }
  }, '📈', " \uC21C\uC704 \uC774\uB825 ", activeKeyword ? '(' + rankHistory.length + '건)' : ''), /*#__PURE__*/React.createElement("button", {
    onClick: function () {
      setViewMode('insights');
    },
    style: {
      padding: '8px 18px',
      borderRadius: 8,
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      background: viewMode === 'insights' ? '#7C3AED' : '#fff',
      color: viewMode === 'insights' ? '#fff' : '#7C3AED',
      border: viewMode === 'insights' ? 'none' : '1px solid #DDD6FE'
    }
  }, '🤖', " AI \uC778\uC0AC\uC774\uD2B8"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  })), activeKeyword && (viewMode === 'history' || viewMode === 'rank') && /*#__PURE__*/React.createElement("div", null, viewMode === 'history' && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16,
      fontWeight: 700,
      marginBottom: 16
    }
  }, "\"", activeKeyword, "\" \uC77C\uC790\uBCC4 \uBD84\uC11D \uCD94\uC774"), analysisHistory.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      padding: 30,
      color: '#94a3b8',
      fontSize: 13
    }
  }, "\uC544\uC9C1 \uB204\uC801\uB41C \uBD84\uC11D \uB370\uC774\uD130\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4. \uB9E4\uC77C \uBD84\uC11D\uC744 \uC2E4\uD589\uD558\uBA74 \uC5EC\uAE30\uC5D0 \uCD94\uC774\uAC00 \uD45C\uC2DC\uB429\uB2C8\uB2E4.") : /*#__PURE__*/React.createElement("div", {
    className: "table-wrap",
    style: {
      overflowX: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", {
    style: {
      minWidth: 750,
      fontSize: 13,
      whiteSpace: 'nowrap'
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    style: {
      whiteSpace: 'nowrap'
    }
  }, "\uB0A0\uC9DC"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "\uAC80\uC0C9\uB7C9"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "PC \uD074\uB9AD"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "\uBAA8\uBC14\uC77C \uD074\uB9AD"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "\uACBD\uC7C1\uC9C0\uC218"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center',
      whiteSpace: 'nowrap'
    }
  }, "\uACBD\uC7C1\uC218\uC900"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center',
      whiteSpace: 'nowrap'
    }
  }, "\uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center',
      whiteSpace: 'nowrap'
    }
  }, "\uBCF4\uACE0\uC11C"))), /*#__PURE__*/React.createElement("tbody", null, analysisHistory.slice().reverse().map(function (h, i, arr) {
    /* 최신이 위 → 더 과거(아래쪽, i+1)와 비교해 변동 계산 */
    var prevH = arr[i + 1] || null;
    var compIdxDiff = prevH && h.comp_index != null && prevH.comp_index != null ? (h.comp_index - prevH.comp_index).toFixed(2) : null;
    /* 경쟁수준 퍼센트 색상 */
    var cpVal = h.comp_percent;
    var cpColor = cpVal != null ? cpVal <= 30 ? '#16a34a' : cpVal <= 70 ? '#ca8a04' : '#dc2626' : '#64748b';
    var cpBg = cpVal != null ? cpVal <= 30 ? '#dcfce7' : cpVal <= 70 ? '#fef9c3' : '#fee2e2' : '#f1f5f9';
    var cpLabel = cpVal != null ? cpVal <= 30 ? '블루오션' : cpVal <= 70 ? '보통' : '레드오션' : '-';
    /* 광고 경쟁강도 배지 색상 */
    var adIdx = h.ad_comp_idx || '-';
    var adColor = adIdx === '높음' || adIdx === 'HIGH' ? '#dc2626' : adIdx === '중간' || adIdx === 'MEDIUM' ? '#ca8a04' : adIdx === '낮음' || adIdx === 'LOW' ? '#16a34a' : '#64748b';
    var adBg = adIdx === '높음' || adIdx === 'HIGH' ? '#fee2e2' : adIdx === '중간' || adIdx === 'MEDIUM' ? '#fef9c3' : adIdx === '낮음' || adIdx === 'LOW' ? '#dcfce7' : '#f1f5f9';
    return /*#__PURE__*/React.createElement("tr", {
      key: i
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        fontWeight: 600,
        whiteSpace: 'nowrap'
      }
    }, h.date), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, h.search_volume || '-'), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, h.pc_clicks || '-'), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, h.mobile_clicks || '-'), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, h.comp_index != null ? h.comp_index : '-', compIdxDiff && compIdxDiff != '0.00' && /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        marginLeft: 4,
        color: compIdxDiff > 0 ? '#dc2626' : '#16a34a'
      }
    }, compIdxDiff > 0 ? '+' : '', compIdxDiff)), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'center',
        whiteSpace: 'nowrap'
      }
    }, cpVal != null ? /*#__PURE__*/React.createElement("span", {
      style: {
        padding: '2px 6px',
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        background: cpBg,
        color: cpColor
      }
    }, cpLabel, " ", cpVal, "%") : '-'), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'center',
        whiteSpace: 'nowrap'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        padding: '2px 6px',
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        background: adBg,
        color: adColor
      }
    }, adIdx)), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'center'
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: function () {
        var row = (analyses || []).find(function (a) {
          return a.analyzed_date === h.date && (!activeKeyword || a.keyword === activeKeyword);
        });
        if (row && onDownloadReport) {
          onDownloadReport(Object.assign({}, row, {
            client_id: selectedClient ? selectedClient.id : null,
            companyName: selectedClient ? selectedClient.name : ''
          }));
        } else {
          downloadReport(h.date);
        }
      },
      style: {
        padding: '4px 10px',
        borderRadius: 6,
        fontSize: 11,
        cursor: 'pointer',
        background: '#f0f9ff',
        color: '#0369a1',
        border: '1px solid #bae6fd',
        fontWeight: 600
      }
    }, "HTML")));
  }))))), viewMode === 'rank' && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16,
      fontWeight: 700
    }
  }, "\"", activeKeyword, "\" \uC21C\uC704 \uCD94\uC801 \uC774\uB825"), /*#__PURE__*/React.createElement("div", {
    ref: exportMenuRef,
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: function () {
      setShowExportMenu(!showExportMenu);
    },
    style: {
      padding: '6px 14px',
      borderRadius: 8,
      fontSize: 12,
      fontWeight: 600,
      cursor: 'pointer',
      background: '#f0f9ff',
      color: '#0369a1',
      border: '1px solid #bae6fd',
      display: 'flex',
      alignItems: 'center',
      gap: 6
    }
  }, '📸', " \uC774\uBBF8\uC9C0 \uC800\uC7A5 ", '▾'), showExportMenu && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: '100%',
      right: 0,
      marginTop: 4,
      zIndex: 100,
      background: '#fff',
      borderRadius: 10,
      boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
      border: '1px solid #e2e8f0',
      minWidth: 160,
      overflow: 'hidden'
    }
  }, [{
    label: '최근 7일',
    days: 7
  }, {
    label: '최근 30일',
    days: 30
  }, {
    label: '최근 60일',
    days: 60
  }, {
    label: '전체 기간',
    days: 0
  }].map(function (opt) {
    return React.createElement('button', {
      key: opt.days,
      onClick: function () {
        exportRankImage(opt.days);
      },
      style: {
        display: 'block',
        width: '100%',
        padding: '10px 16px',
        background: 'none',
        border: 'none',
        borderBottom: '1px solid #f1f5f9',
        textAlign: 'left',
        fontSize: 13,
        cursor: 'pointer',
        color: '#334155',
        fontWeight: 500
      },
      onMouseOver: function (e) {
        e.target.style.background = '#f0f9ff';
      },
      onMouseOut: function (e) {
        e.target.style.background = 'none';
      }
    }, opt.label);
  })))), rankHistory.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      padding: 40,
      color: '#94a3b8',
      fontSize: 13
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 32,
      marginBottom: 12
    }
  }, "\uD83D\uDCCA"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 600,
      marginBottom: 6,
      color: '#64748b'
    }
  }, "\uC544\uC9C1 \uC218\uC9D1\uB41C \uC21C\uC704 \uB370\uC774\uD130\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4"), /*#__PURE__*/React.createElement("div", null, "\uC2A4\uCF00\uC904\uB7EC\uAC00 6\uC2DC\uAC04 \uAC04\uACA9\uC73C\uB85C \uC790\uB3D9 \uC218\uC9D1\uD558\uBA70, \uB9E4\uC77C \uC624\uC804 7\uC2DC \uC804\uCCB4 \uBD84\uC11D \uC2DC\uC5D0\uB3C4 \uD568\uAED8 \uC218\uC9D1\uB429\uB2C8\uB2E4.")) : /*#__PURE__*/React.createElement("div", {
    className: "table-wrap"
  }, /*#__PURE__*/React.createElement("table", null, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "\uB0A0\uC9DC"), /*#__PURE__*/React.createElement("th", null, "\uC21C\uC704"), /*#__PURE__*/React.createElement("th", null, "\uC720\uD615"))), /*#__PURE__*/React.createElement("tbody", null, rankHistory.slice().reverse().map(function (r, i, arr) {
    var prevR = arr[i + 1] || null;
    var diff = prevR && r.rank_position && prevR.rank_position ? prevR.rank_position - r.rank_position : null;
    return /*#__PURE__*/React.createElement("tr", {
      key: i
    }, /*#__PURE__*/React.createElement("td", null, (r.checked_at || '').slice(0, 16)), /*#__PURE__*/React.createElement("td", {
      style: {
        fontWeight: 700
      }
    }, r.rank_position ? r.rank_position + '위' : '미노출', diff != null && diff !== 0 && /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        marginLeft: 6,
        color: diff > 0 ? '#16a34a' : '#dc2626'
      }
    }, diff > 0 ? '▲' + diff : '▼' + Math.abs(diff))), /*#__PURE__*/React.createElement("td", null, r.check_type === 'manual' ? '수동' : '자동'));
  })))))), !activeKeyword && (viewMode === 'history' || viewMode === 'rank') && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 40,
      textAlign: 'center',
      color: '#94a3b8'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 32,
      marginBottom: 12
    }
  }, '👆'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      fontWeight: 500
    }
  }, "\uC704\uC5D0\uC11C \uD0A4\uC6CC\uB4DC\uB97C \uC120\uD0DD\uD558\uBA74 ", viewMode === 'history' ? '일자별 추이' : '순위 이력', "\uAC00 \uD45C\uC2DC\uB429\uB2C8\uB2E4.")), viewMode === 'insights' && /*#__PURE__*/React.createElement("div", null, aiLoading && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 40,
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 32,
      marginBottom: 12
    }
  }, '🤖'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      color: '#64748b'
    }
  }, "AI \uC778\uC0AC\uC774\uD2B8\uB97C \uBD84\uC11D \uC911\uC785\uB2C8\uB2E4...")), !aiLoading && !aiInsights && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 40,
      textAlign: 'center',
      color: '#94a3b8'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 32,
      marginBottom: 12
    }
  }, '📊'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      fontWeight: 500
    }
  }, "\uC544\uC9C1 \uBD84\uC11D \uB370\uC774\uD130\uAC00 \uC5C6\uC5B4 AI \uC778\uC0AC\uC774\uD2B8\uB97C \uC0DD\uC131\uD560 \uC218 \uC5C6\uC2B5\uB2C8\uB2E4."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      marginTop: 8
    }
  }, "\uBD84\uC11D\uC744 \uC2E4\uD589\uD558\uBA74 AI\uAC00 \uC790\uB3D9\uC73C\uB85C \uD559\uC2B5\uD558\uC5EC \uC778\uC0AC\uC774\uD2B8\uB97C \uC81C\uACF5\uD569\uB2C8\uB2E4.")), !aiLoading && aiInsights && /*#__PURE__*/React.createElement("div", null, aiInsights.performance && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 20,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16,
      fontWeight: 700,
      marginBottom: 16,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, '📊', " \uC5C5\uCCB4 \uC131\uACFC \uD328\uD134", /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      padding: '2px 8px',
      borderRadius: 10,
      fontWeight: 600,
      background: aiInsights.performance.overallTrend === '상승세' ? '#dcfce7' : aiInsights.performance.overallTrend === '하락세' ? '#fee2e2' : '#f1f5f9',
      color: aiInsights.performance.overallTrend === '상승세' ? '#16a34a' : aiInsights.performance.overallTrend === '하락세' ? '#dc2626' : '#64748b'
    }
  }, aiInsights.performance.overallTrend)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 12,
      flexWrap: 'wrap',
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 100,
      background: '#f0fdf4',
      borderRadius: 10,
      padding: 14,
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#64748b'
    }
  }, "\uC0C1\uC2B9 \uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 22,
      fontWeight: 700,
      color: '#16a34a'
    }
  }, aiInsights.performance.improving)), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 100,
      background: '#fee2e2',
      borderRadius: 10,
      padding: 14,
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#64748b'
    }
  }, "\uD558\uB77D \uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 22,
      fontWeight: 700,
      color: '#dc2626'
    }
  }, aiInsights.performance.declining)), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 100,
      background: '#f1f5f9',
      borderRadius: 10,
      padding: 14,
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#64748b'
    }
  }, "\uC720\uC9C0 \uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 22,
      fontWeight: 700,
      color: '#64748b'
    }
  }, aiInsights.performance.stable)), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 100,
      background: '#dbeafe',
      borderRadius: 10,
      padding: 14,
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#64748b'
    }
  }, "\uCD1D \uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 22,
      fontWeight: 700,
      color: '#1e40af'
    }
  }, aiInsights.performance.totalKeywords))), aiInsights.performance.keywordSummaries && aiInsights.performance.keywordSummaries.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "table-wrap",
    style: {
      overflowX: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", {
    style: {
      fontSize: 13,
      whiteSpace: 'nowrap'
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "\uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center'
    }
  }, "\uCD94\uC138"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "\uCD08\uAE30 \uC21C\uC704"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "\uD604\uC7AC \uC21C\uC704"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "\uBCC0\uB3D9"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "\uD3C9\uADE0 \uC21C\uC704"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "\uB370\uC774\uD130"))), /*#__PURE__*/React.createElement("tbody", null, aiInsights.performance.keywordSummaries.map(function (s, i) {
    var trendColor = s.trend === '상승' ? '#16a34a' : s.trend === '하락' ? '#dc2626' : '#64748b';
    var trendBg = s.trend === '상승' ? '#dcfce7' : s.trend === '하락' ? '#fee2e2' : '#f1f5f9';
    return /*#__PURE__*/React.createElement("tr", {
      key: i
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        fontWeight: 600
      }
    }, s.keyword), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'center'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        padding: '2px 8px',
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        background: trendBg,
        color: trendColor
      }
    }, s.trend)), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right'
      }
    }, s.firstRank, "\uC704"), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        fontWeight: 700
      }
    }, s.latestRank, "\uC704"), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        color: s.change > 0 ? '#16a34a' : s.change < 0 ? '#dc2626' : '#64748b',
        fontWeight: 600
      }
    }, s.change > 0 ? '▲' + s.change : s.change < 0 ? '▼' + Math.abs(s.change) : '-'), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right'
      }
    }, s.avgRank, "\uC704"), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        color: '#94a3b8'
      }
    }, s.dataPoints, "\uAC74"));
  })))), aiInsights.performance.advice && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 14,
      padding: 12,
      background: '#faf5ff',
      borderRadius: 8,
      fontSize: 13,
      color: '#6b21a8',
      lineHeight: 1.6
    }
  }, '💡', " ", aiInsights.performance.advice)), aiInsights.competitorAlerts && aiInsights.competitorAlerts.totalAlerts > 0 && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 20,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16,
      fontWeight: 700,
      marginBottom: 16,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, '🚨', " \uACBD\uC7C1\uC0AC \uC774\uC0C1 \uAC10\uC9C0", aiInsights.competitorAlerts.dangerCount > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      padding: '2px 8px',
      borderRadius: 10,
      background: '#fee2e2',
      color: '#dc2626',
      fontWeight: 600
    }
  }, "\uC704\uD5D8 ", aiInsights.competitorAlerts.dangerCount, "\uAC74"), aiInsights.competitorAlerts.warningCount > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      padding: '2px 8px',
      borderRadius: 10,
      background: '#fef9c3',
      color: '#ca8a04',
      fontWeight: 600
    }
  }, "\uC8FC\uC758 ", aiInsights.competitorAlerts.warningCount, "\uAC74")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, aiInsights.competitorAlerts.alerts.map(function (alert, i) {
    var severityStyles = {
      danger: {
        bg: '#fef2f2',
        border: '#fecaca',
        color: '#991b1b',
        icon: '🔴'
      },
      warning: {
        bg: '#fffbeb',
        border: '#fde68a',
        color: '#92400e',
        icon: '🟡'
      },
      success: {
        bg: '#f0fdf4',
        border: '#bbf7d0',
        color: '#166534',
        icon: '🟢'
      },
      info: {
        bg: '#eff6ff',
        border: '#bfdbfe',
        color: '#1e40af',
        icon: '🔵'
      }
    };
    var st = severityStyles[alert.severity] || severityStyles.info;
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        padding: '10px 14px',
        background: st.bg,
        border: '1px solid ' + st.border,
        borderRadius: 8,
        fontSize: 13
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        color: st.color,
        fontWeight: 600
      }
    }, st.icon, " ", alert.message), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: '#94a3b8'
      }
    }, (alert.date || '').slice(0, 10))), alert.detail && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: '#64748b',
        marginTop: 4
      }
    }, alert.detail));
  }))), aiInsights.keywordRecommendations && aiInsights.keywordRecommendations.topRecommended && aiInsights.keywordRecommendations.topRecommended.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 20,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16,
      fontWeight: 700,
      marginBottom: 16,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, '🔍', " \uD0A4\uC6CC\uB4DC \uBC1C\uAD74 \uCD94\uCC9C", /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      fontWeight: 400
    }
  }, "\uAE30\uC874 ", aiInsights.keywordRecommendations.existingCount, "\uAC1C \uD0A4\uC6CC\uB4DC\uC5D0\uC11C ", aiInsights.keywordRecommendations.candidateCount, "\uAC1C \uD6C4\uBCF4 \uBC1C\uAD74")), /*#__PURE__*/React.createElement("div", {
    className: "table-wrap",
    style: {
      overflowX: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", {
    style: {
      fontSize: 13,
      whiteSpace: 'nowrap'
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "\uCD94\uCC9C \uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "\uC6D4\uAC04 \uAC80\uC0C9\uB7C9"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "\uC5F0\uAD00 \uB4F1\uC7A5"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "\uCD94\uCC9C \uC810\uC218"))), /*#__PURE__*/React.createElement("tbody", null, aiInsights.keywordRecommendations.topRecommended.map(function (kw, i) {
    return /*#__PURE__*/React.createElement("tr", {
      key: i
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        fontWeight: 600
      }
    }, kw.keyword), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right'
      }
    }, fmt(kw.volume)), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right'
      }
    }, kw.appearances, "\uD68C"), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        padding: '2px 8px',
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        background: kw.score >= 5 ? '#dcfce7' : kw.score >= 2 ? '#fef9c3' : '#f1f5f9',
        color: kw.score >= 5 ? '#16a34a' : kw.score >= 2 ? '#ca8a04' : '#64748b'
      }
    }, kw.score)));
  }))))), aiInsights.keywordInsights && Object.keys(aiInsights.keywordInsights).length > 0 && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      flexWrap: 'wrap',
      marginBottom: 16
    }
  }, Object.keys(aiInsights.keywordInsights).map(function (kw) {
    var isActive = aiSelectedKeyword === kw;
    return /*#__PURE__*/React.createElement("button", {
      key: kw,
      onClick: function () {
        setAiSelectedKeyword(kw);
      },
      style: {
        padding: '6px 14px',
        borderRadius: 20,
        cursor: 'pointer',
        fontSize: 12,
        background: isActive ? '#7C3AED' : '#f5f3ff',
        color: isActive ? '#fff' : '#7C3AED',
        border: isActive ? '1px solid #7C3AED' : '1px solid #DDD6FE'
      }
    }, '🔑', " ", kw);
  })), aiSelectedKeyword && aiInsights.keywordInsights[aiSelectedKeyword] && function () {
    var kwData = aiInsights.keywordInsights[aiSelectedKeyword];
    return React.createElement('div', null, /* ⑧ 순위 예측 */
    kwData.rankPrediction && React.createElement('div', {
      className: 'card',
      style: {
        padding: 20,
        marginBottom: 16
      }
    }, React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700,
        marginBottom: 16
      }
    }, '🔮 순위 예측 — "' + aiSelectedKeyword + '"'), kwData.rankPrediction.ready === false ? React.createElement('div', {
      style: {
        textAlign: 'center',
        padding: 20,
        color: '#94a3b8',
        fontSize: 13
      }
    }, kwData.rankPrediction.message) : React.createElement('div', null, React.createElement('div', {
      style: {
        display: 'flex',
        gap: 12,
        flexWrap: 'wrap',
        marginBottom: 16
      }
    }, React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 110,
        background: '#f1f5f9',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '현재 순위'), React.createElement('div', {
      style: {
        fontSize: 22,
        fontWeight: 700
      }
    }, kwData.rankPrediction.currentRank + '위')), React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 110,
        background: '#dbeafe',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '7일 후 예측'), React.createElement('div', {
      style: {
        fontSize: 22,
        fontWeight: 700,
        color: '#1e40af'
      }
    }, kwData.rankPrediction.predicted7d + '위')), React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 110,
        background: '#ede9fe',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '14일 후 예측'), React.createElement('div', {
      style: {
        fontSize: 22,
        fontWeight: 700,
        color: '#6d28d9'
      }
    }, kwData.rankPrediction.predicted14d + '위')), React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 110,
        background: '#faf5ff',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '30일 후 예측'), React.createElement('div', {
      style: {
        fontSize: 22,
        fontWeight: 700,
        color: '#9333ea'
      }
    }, kwData.rankPrediction.predicted30d + '위'))), React.createElement('div', {
      style: {
        display: 'flex',
        gap: 16,
        flexWrap: 'wrap',
        fontSize: 13,
        color: '#475569'
      }
    }, React.createElement('span', null, '추세: ', React.createElement('strong', {
      style: {
        color: kwData.rankPrediction.trend === '상승' ? '#16a34a' : kwData.rankPrediction.trend === '하락' ? '#dc2626' : '#64748b'
      }
    }, kwData.rankPrediction.trend)), React.createElement('span', null, '신뢰도: ', React.createElement('strong', null, kwData.rankPrediction.confidence, ' (R²=', kwData.rankPrediction.rSquared, ')')), React.createElement('span', null, '데이터: ', React.createElement('strong', null, kwData.rankPrediction.dataPoints, '건'))), React.createElement('div', {
      style: {
        marginTop: 10,
        padding: 10,
        background: '#f8fafc',
        borderRadius: 8,
        fontSize: 12,
        color: '#64748b'
      }
    }, kwData.rankPrediction.trendDesc))), /* ① 가격 최적화 */
    kwData.priceOptimization && React.createElement('div', {
      className: 'card',
      style: {
        padding: 20,
        marginBottom: 16
      }
    }, React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700,
        marginBottom: 16
      }
    }, '💰 가격 최적화 — "' + aiSelectedKeyword + '"'), React.createElement('div', {
      style: {
        display: 'flex',
        gap: 12,
        flexWrap: 'wrap',
        marginBottom: 16
      }
    }, React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 130,
        background: '#f0fdf4',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '추천 가격대'), React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700,
        color: '#16a34a'
      }
    }, fmt(kwData.priceOptimization.recommendedRange.low) + ' ~ ' + fmt(kwData.priceOptimization.recommendedRange.high) + '원')), React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 100,
        background: '#eff6ff',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '상위5 평균'), React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700
      }
    }, fmt(kwData.priceOptimization.avgTop5) + '원')), React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 100,
        background: '#f1f5f9',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '중위 가격'), React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700
      }
    }, fmt(kwData.priceOptimization.median) + '원'))), React.createElement('div', {
      style: {
        padding: 12,
        background: '#faf5ff',
        borderRadius: 8,
        fontSize: 13,
        color: '#6b21a8'
      }
    }, '💡 전략: ', React.createElement('strong', null, kwData.priceOptimization.strategy), ' — ', kwData.priceOptimization.strategyDesc)), /* ④ 광고 효율 */
    kwData.adEfficiency && React.createElement('div', {
      className: 'card',
      style: {
        padding: 20,
        marginBottom: 16
      }
    }, React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700,
        marginBottom: 16,
        display: 'flex',
        alignItems: 'center',
        gap: 10
      }
    }, '📣 광고 효율 — "' + aiSelectedKeyword + '"', React.createElement('span', {
      style: {
        fontSize: 14,
        padding: '2px 10px',
        borderRadius: 10,
        fontWeight: 700,
        background: kwData.adEfficiency.grade === 'A' ? '#dcfce7' : kwData.adEfficiency.grade === 'B' ? '#dbeafe' : kwData.adEfficiency.grade === 'C' ? '#fef9c3' : '#fee2e2',
        color: kwData.adEfficiency.grade === 'A' ? '#16a34a' : kwData.adEfficiency.grade === 'B' ? '#1e40af' : kwData.adEfficiency.grade === 'C' ? '#ca8a04' : '#dc2626'
      }
    }, kwData.adEfficiency.grade + '등급')), React.createElement('div', {
      style: {
        display: 'flex',
        gap: 12,
        flexWrap: 'wrap',
        marginBottom: 16
      }
    }, React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 100,
        background: '#f8fafc',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '효율 점수'), React.createElement('div', {
      style: {
        fontSize: 28,
        fontWeight: 700,
        color: kwData.adEfficiency.efficiencyScore >= 70 ? '#16a34a' : kwData.adEfficiency.efficiencyScore >= 40 ? '#ca8a04' : '#dc2626'
      }
    }, kwData.adEfficiency.efficiencyScore)), React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 100,
        background: '#f8fafc',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '검색량'), React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700
      }
    }, fmt(kwData.adEfficiency.totalVolume))), React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 100,
        background: '#f8fafc',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, 'CTR'), React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700
      }
    }, kwData.adEfficiency.ctr + '%')), React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 100,
        background: '#f8fafc',
        borderRadius: 10,
        padding: 14,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '현재 순위'), React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700
      }
    }, kwData.adEfficiency.currentRank ? kwData.adEfficiency.currentRank + '위' : '미측정'))), React.createElement('div', {
      style: {
        padding: 12,
        background: '#faf5ff',
        borderRadius: 8,
        fontSize: 13,
        color: '#6b21a8'
      }
    }, '💡 ' + kwData.adEfficiency.advice)), /* ⑤ 최적 등록 타이밍 */
    kwData.optimalTiming && React.createElement('div', {
      className: 'card',
      style: {
        padding: 20,
        marginBottom: 16
      }
    }, React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700,
        marginBottom: 16
      }
    }, '⏰ 최적 등록 타이밍 — "' + aiSelectedKeyword + '"'), kwData.optimalTiming.ready === false ? React.createElement('div', {
      style: {
        textAlign: 'center',
        padding: 20,
        color: '#94a3b8',
        fontSize: 13
      }
    }, kwData.optimalTiming.message) : React.createElement('div', null, /* 요일별 막대 */
    kwData.optimalTiming.weekdayData && React.createElement('div', {
      style: {
        display: 'flex',
        gap: 6,
        alignItems: 'flex-end',
        height: 120,
        marginBottom: 16
      }
    }, kwData.optimalTiming.weekdayData.map(function (d) {
      var maxRank = Math.max.apply(null, kwData.optimalTiming.weekdayData.map(function (x) {
        return x.avgRank;
      }));
      var barH = maxRank > 0 ? Math.max(20, d.avgRank / maxRank * 100) : 40;
      return React.createElement('div', {
        key: d.day,
        style: {
          flex: 1,
          textAlign: 'center'
        }
      }, React.createElement('div', {
        style: {
          fontSize: 11,
          fontWeight: 600,
          marginBottom: 4,
          color: d.isBest ? '#16a34a' : d.isWorst ? '#dc2626' : '#64748b'
        }
      }, d.avgRank + '위'), React.createElement('div', {
        style: {
          height: barH,
          borderRadius: '6px 6px 0 0',
          margin: '0 auto',
          width: '70%',
          background: d.isBest ? '#22c55e' : d.isWorst ? '#ef4444' : '#94a3b8'
        }
      }), React.createElement('div', {
        style: {
          fontSize: 12,
          fontWeight: 600,
          marginTop: 6,
          color: d.isBest ? '#16a34a' : d.isWorst ? '#dc2626' : '#334155'
        }
      }, d.day));
    })), React.createElement('div', {
      style: {
        padding: 12,
        background: '#faf5ff',
        borderRadius: 8,
        fontSize: 13,
        color: '#6b21a8'
      }
    }, '💡 ' + kwData.optimalTiming.advice))), /* ③ 리뷰 감성 */
    kwData.reviewSentiment && React.createElement('div', {
      className: 'card',
      style: {
        padding: 20,
        marginBottom: 16
      }
    }, React.createElement('div', {
      style: {
        fontSize: 16,
        fontWeight: 700,
        marginBottom: 16
      }
    }, '💬 리뷰 감성 분석 — "' + aiSelectedKeyword + '"'), kwData.reviewSentiment.alert && React.createElement('div', {
      style: {
        marginBottom: 12,
        padding: 10,
        borderRadius: 8,
        fontSize: 13,
        background: kwData.reviewSentiment.alert.indexOf('급증') !== -1 ? '#fee2e2' : '#dcfce7',
        color: kwData.reviewSentiment.alert.indexOf('급증') !== -1 ? '#991b1b' : '#166534'
      }
    }, '⚠️ ' + kwData.reviewSentiment.alert), kwData.reviewSentiment.latest && React.createElement('div', {
      style: {
        display: 'flex',
        gap: 12,
        flexWrap: 'wrap',
        marginBottom: 12
      }
    }, React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 100,
        background: '#dcfce7',
        borderRadius: 10,
        padding: 12,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '긍정'), React.createElement('div', {
      style: {
        fontSize: 18,
        fontWeight: 700,
        color: '#16a34a'
      }
    }, kwData.reviewSentiment.latest.positiveRate + '%')), React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 100,
        background: '#fee2e2',
        borderRadius: 10,
        padding: 12,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '부정'), React.createElement('div', {
      style: {
        fontSize: 18,
        fontWeight: 700,
        color: '#dc2626'
      }
    }, kwData.reviewSentiment.latest.negativeRate + '%')), React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 100,
        background: '#f1f5f9',
        borderRadius: 10,
        padding: 12,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b'
      }
    }, '중립'), React.createElement('div', {
      style: {
        fontSize: 18,
        fontWeight: 700,
        color: '#64748b'
      }
    }, (100 - kwData.reviewSentiment.latest.positiveRate - kwData.reviewSentiment.latest.negativeRate).toFixed(1) + '%'))), React.createElement('div', {
      style: {
        fontSize: 12,
        color: '#94a3b8'
      }
    }, '분석 데이터: ' + kwData.reviewSentiment.dataPoints + '건')));
  }())))))));
};

/* ==================== 분석 실행 폼 ==================== */
window.AnalysisForm = function AnalysisForm({
  client,
  onAnalyze,
  analyzing,
  message
}) {
  const [keyword, setKeyword] = React.useState('');
  const [productUrl, setProductUrl] = React.useState('');
  React.useEffect(function () {
    if (client && client.main_keywords) {
      var first = client.main_keywords.split(',')[0].trim();
      if (first) setKeyword(first);
    }
    if (client && client.naver_store_url) {
      // 스마트스토어 URL에서 추적 파라미터 제거
      var url = client.naver_store_url;
      try {
        var u = new URL(url);
        if (u.hostname.indexOf('smartstore.naver.com') !== -1) {
          url = u.origin + u.pathname;
        }
      } catch (e) {}
      setProductUrl(url);
    }
  }, [client]);
  return /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 16,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      marginBottom: 12
    }
  }, "\uC0C8 \uBD84\uC11D \uC2E4\uD589"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10,
      alignItems: 'flex-end',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 150
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 12,
      color: '#64748b',
      display: 'block',
      marginBottom: 4
    }
  }, "\uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    value: keyword,
    onChange: function (e) {
      setKeyword(e.target.value);
    },
    placeholder: "\uBD84\uC11D\uD560 \uD0A4\uC6CC\uB4DC",
    style: {
      width: '100%'
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1.5,
      minWidth: 200
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 12,
      color: '#64748b',
      display: 'block',
      marginBottom: 4
    }
  }, "\uC0C1\uD488 URL (\uC120\uD0DD)"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    value: productUrl,
    onChange: function (e) {
      setProductUrl(e.target.value);
    },
    placeholder: "https://smartstore.naver.com/...",
    style: {
      width: '100%'
    }
  })), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: function () {
      onAnalyze(keyword, productUrl);
    },
    disabled: analyzing || !keyword,
    style: {
      whiteSpace: 'nowrap'
    }
  }, analyzing ? '분석 중...' : '분석 실행')), message && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 10,
      fontSize: 13,
      color: '#16a34a'
    }
  }, message));
};

/* ==================== 분석 결과 뷰 ==================== */
window.AnalysisResultView = function AnalysisResultView({
  keyword,
  data,
  rankHistory,
  onExport,
  hideHeader
}) {
  function fmt(n) {
    return n != null ? Number(n).toLocaleString('ko-KR') : '-';
  }
  return /*#__PURE__*/React.createElement("div", null, data.summaryCards && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 20,
      marginBottom: 16
    }
  }, !hideHeader && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16,
      fontWeight: 700
    }
  }, keyword, " \uBD84\uC11D \uACB0\uACFC"), onExport && /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: onExport,
    style: {
      fontSize: 13,
      padding: '6px 14px'
    }
  }, "HTML \uBCF4\uACE0\uC11C")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 12,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 120,
      background: '#f0f9ff',
      borderRadius: 10,
      padding: 16,
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#64748b'
    }
  }, "\uC6D4\uAC04 \uAC80\uC0C9\uB7C9"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 24,
      fontWeight: 700,
      color: '#0f172a'
    }
  }, fmt(data.summaryCards.totalVolume))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 120,
      background: '#f0fdf4',
      borderRadius: 10,
      padding: 16,
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#64748b'
    }
  }, "\uC0C1\uD488 \uC218"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 24,
      fontWeight: 700,
      color: '#0f172a'
    }
  }, fmt(data.summaryCards.productCount))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 120,
      background: '#faf5ff',
      borderRadius: 10,
      padding: 16,
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#64748b'
    }
  }, "\uACBD\uC7C1\uAC15\uB3C4"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 24,
      fontWeight: 700,
      color: data.competitionIndex ? data.competitionIndex.compColor : '#0f172a'
    }
  }, data.summaryCards.compLevel)))), data.competitionIndex && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 16,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      marginBottom: 10
    }
  }, "\uACBD\uC7C1\uAC15\uB3C4 \uBD84\uC11D"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 20,
      flexWrap: 'wrap',
      fontSize: 14
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "\uACBD\uC7C1\uC9C0\uC218:"), " ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: data.competitionIndex.compColor
    }
  }, data.competitionIndex.compIndex)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "\uC0C1\uD488 \uC218:"), " ", /*#__PURE__*/React.createElement("strong", null, fmt(data.competitionIndex.productCount))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "\uAC80\uC0C9\uB7C9:"), " ", /*#__PURE__*/React.createElement("strong", null, fmt(data.competitionIndex.searchVolume))))), data.marketRevenue && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 16,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      marginBottom: 10
    }
  }, "\uC2DC\uC7A5 \uADDC\uBAA8"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 20,
      flexWrap: 'wrap',
      fontSize: 14
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "\uD3C9\uADE0 \uAC00\uACA9:"), " ", /*#__PURE__*/React.createElement("strong", null, fmt(data.marketRevenue.avgPrice), "\uC6D0")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "\uC608\uC0C1 \uC6D4 \uC2DC\uC7A5:"), " ", /*#__PURE__*/React.createElement("strong", null, fmt(data.marketRevenue.estimatedMonthly), "\uC6D0")))), data.advertiserInfo && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 16,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      marginBottom: 10
    }
  }, "\uAD11\uACE0 \uACBD\uC7C1 \uC815\uBCF4"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 20,
      flexWrap: 'wrap',
      fontSize: 14
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "\uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4:"), " ", /*#__PURE__*/React.createElement("strong", null, data.advertiserInfo.compIdx)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "\uB178\uCD9C \uAE4A\uC774:"), " ", /*#__PURE__*/React.createElement("strong", null, data.advertiserInfo.adDepth)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "PC \uD074\uB9AD:"), " ", /*#__PURE__*/React.createElement("strong", null, data.advertiserInfo.pcClicks, "\uD68C")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "\uBAA8\uBC14\uC77C \uD074\uB9AD:"), " ", /*#__PURE__*/React.createElement("strong", null, data.advertiserInfo.mobileClicks, "\uD68C")))), !hideHeader && rankHistory && rankHistory.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 16,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      marginBottom: 10
    }
  }, "\uC21C\uC704 \uCD94\uC801 \uC774\uB825 (", rankHistory.length, "\uAC74)"), /*#__PURE__*/React.createElement("div", {
    className: "table-wrap"
  }, /*#__PURE__*/React.createElement("table", null, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "\uB0A0\uC9DC"), /*#__PURE__*/React.createElement("th", null, "\uC21C\uC704"), /*#__PURE__*/React.createElement("th", null, "\uC720\uD615"))), /*#__PURE__*/React.createElement("tbody", null, rankHistory.slice().reverse().map(function (r, i) {
    return /*#__PURE__*/React.createElement("tr", {
      key: i
    }, /*#__PURE__*/React.createElement("td", null, (r.checked_at || '').slice(0, 16)), /*#__PURE__*/React.createElement("td", {
      style: {
        fontWeight: 700
      }
    }, r.rank_position ? r.rank_position + '위' : '미노출'), /*#__PURE__*/React.createElement("td", null, r.check_type === 'manual' ? '수동' : '자동'));
  }))))));
};

;/* ===== js/components/UserGuidePage.jsx ===== */
/* UserGuidePage — 내부 직원용 사용자 가이드북 (v3.9 Enhanced) */
window.UserGuidePage = function UserGuidePage({
  currentUser
}) {
  const {
    useState
  } = React;
  const [activeSection, setActiveSection] = useState('overview');
  var sections = [{
    id: 'overview',
    icon: '\uD83D\uDCCB',
    label: '프로그램 개요'
  }, {
    id: 'cost',
    icon: '\uD83D\uDCB0',
    label: '비용 안내'
  }, {
    id: 'quickstart',
    icon: '\uD83D\uDE80',
    label: '빠른 시작 가이드'
  }, {
    id: 'login',
    icon: '\uD83D\uDD10',
    label: '로그인 & 권한'
  }, {
    id: 'analysis',
    icon: '\uD83D\uDCCA',
    label: '분석 탭 사용법'
  }, {
    id: 'data',
    icon: '\uD83D\uDCC8',
    label: '데이터 해석 방법'
  }, {
    id: 'management',
    icon: '\uD83C\uDFE2',
    label: '업체관리 사용법'
  }, {
    id: 'rank',
    icon: '\uD83C\uDFC6',
    label: '순위 추적 해석'
  }, {
    id: 'report',
    icon: '\uD83D\uDCC4',
    label: '보고서 활용'
  }, {
    id: 'advanced',
    icon: '\u2699\uFE0F',
    label: '고급 활용법'
  }, {
    id: 'tips',
    icon: '\uD83D\uDCA1',
    label: '실전 활용 팁'
  }, {
    id: 'faq',
    icon: '\u2753',
    label: '자주 묻는 질문'
  }];
  var cardStyle = {
    background: '#fff',
    borderRadius: 14,
    padding: '28px 32px',
    marginBottom: 20,
    boxShadow: '0 1px 4px rgba(0,0,0,0.06)'
  };
  var h2Style = {
    fontSize: 20,
    fontWeight: 700,
    color: '#1e293b',
    marginBottom: 18,
    display: 'flex',
    alignItems: 'center',
    gap: 8
  };
  var h3Style = {
    fontSize: 16,
    fontWeight: 700,
    color: '#334155',
    marginTop: 24,
    marginBottom: 10
  };
  var h4Style = {
    fontSize: 14,
    fontWeight: 700,
    color: '#475569',
    marginTop: 18,
    marginBottom: 8
  };
  var pStyle = {
    fontSize: 14,
    color: '#475569',
    lineHeight: 1.8,
    marginBottom: 12
  };
  var tipBoxStyle = {
    background: '#eff6ff',
    border: '1px solid #bfdbfe',
    borderRadius: 10,
    padding: '14px 18px',
    marginBottom: 14,
    fontSize: 13,
    color: '#1e40af',
    lineHeight: 1.7
  };
  var warnBoxStyle = {
    background: '#fef3c7',
    border: '1px solid #fde68a',
    borderRadius: 10,
    padding: '14px 18px',
    marginBottom: 14,
    fontSize: 13,
    color: '#92400e',
    lineHeight: 1.7
  };
  var costBoxStyle = {
    background: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: 10,
    padding: '14px 18px',
    marginBottom: 14,
    fontSize: 13,
    color: '#991b1b',
    lineHeight: 1.7
  };
  var successBoxStyle = {
    background: '#f0fdf4',
    border: '1px solid #bbf7d0',
    borderRadius: 10,
    padding: '14px 18px',
    marginBottom: 14,
    fontSize: 13,
    color: '#166534',
    lineHeight: 1.7
  };
  var tableStyle = {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 13,
    marginBottom: 16
  };
  var thStyle = {
    background: '#f1f5f9',
    padding: '10px 14px',
    textAlign: 'left',
    fontWeight: 600,
    color: '#475569',
    borderBottom: '2px solid #e2e8f0'
  };
  var tdStyle = {
    padding: '10px 14px',
    borderBottom: '1px solid #f1f5f9',
    color: '#334155'
  };
  var tdCenterStyle = {
    padding: '10px 14px',
    borderBottom: '1px solid #f1f5f9',
    color: '#334155',
    textAlign: 'center'
  };
  var tdRightStyle = {
    padding: '10px 14px',
    borderBottom: '1px solid #f1f5f9',
    color: '#334155',
    textAlign: 'right',
    fontWeight: 600
  };
  var badgeStyle = function (bg, color) {
    return {
      display: 'inline-block',
      padding: '2px 10px',
      borderRadius: 10,
      fontSize: 11,
      fontWeight: 600,
      background: bg,
      color: color,
      marginRight: 4
    };
  };
  var stepNumStyle = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 24,
    height: 24,
    borderRadius: '50%',
    background: '#6C5CE7',
    color: '#fff',
    fontSize: 12,
    fontWeight: 700,
    marginRight: 8,
    flexShrink: 0
  };
  var stepRowStyle = {
    display: 'flex',
    alignItems: 'flex-start',
    marginBottom: 14
  };
  var dividerStyle = {
    border: 'none',
    borderTop: '1px solid #e2e8f0',
    margin: '24px 0'
  };
  var renderContent = function () {
    switch (activeSection) {
      /* ==================== 프로그램 개요 ==================== */
      case 'overview':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\uD83D\uDCCB \uD504\uB85C\uADF8\uB7A8 \uAC1C\uC694'), React.createElement('p', {
          style: pStyle
        }, '\uB85C\uC9C1 \uBD84\uC11D\uC740 \uB124\uC774\uBC84 \uC1FC\uD551 \uD0A4\uC6CC\uB4DC\uC758 \uC2DC\uC7A5 \uACBD\uC7C1 \uD604\uD669\uC744 AI \uAE30\uBC18\uC73C\uB85C \uBD84\uC11D\uD558\uACE0, \uB4F1\uB85D\uB41C \uC5C5\uCCB4\uC758 \uC0C1\uD488 \uC21C\uC704\uB97C \uC790\uB3D9 \uCD94\uC801\uD558\uB294 \uB0B4\uBD80 \uC5C5\uBB34 \uB3C4\uAD6C\uC785\uB2C8\uB2E4. \uB9E4\uC77C \uC0C8\uBCBD 5\uC2DC\uC5D0 \uC804\uCCB4 \uC5C5\uCCB4\uC758 \uD0A4\uC6CC\uB4DC\uB97C \uC790\uB3D9 \uBD84\uC11D\uD558\uC5EC \uC77C\uC790\uBCC4 \uCD94\uC774\uB97C \uB204\uC801 \uAD00\uB9AC\uD569\uB2C8\uB2E4.'), React.createElement('p', {
          style: pStyle
        }, '\uBD84\uC11D \uACB0\uACFC\uB294 11\uAC00\uC9C0 \uC139\uC158(\uACBD\uC7C1\uAC15\uB3C4, \uC2DC\uC7A5\uADDC\uBAA8, \uACE8\uB4E0\uD0A4\uC6CC\uB4DC, \uAD11\uACE0\uBD84\uC11D, \uACBD\uC7C1\uC0AC \uBE44\uAD50 \uB4F1)\uC73C\uB85C \uAD6C\uC131\uB418\uBA70, \uAC01 \uC139\uC158\uC5D0 Claude AI\uAC00 \uB9DE\uCDA4\uD615 \uD53C\uB4DC\uBC31\uC744 \uC81C\uACF5\uD569\uB2C8\uB2E4. HTML \uBCF4\uACE0\uC11C\uB85C \uB2E4\uC6B4\uB85C\uB4DC\uD558\uC5EC \uACE0\uAC1D \uBBF8\uD305\uC774\uB098 \uB0B4\uBD80 \uBCF4\uACE0\uC5D0 \uD65C\uC6A9\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uC8FC\uC694 \uAE30\uB2A5'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uAE30\uB2A5'), React.createElement('th', {
          style: thStyle
        }, '\uC124\uBA85'), React.createElement('th', {
          style: thStyle
        }, '\uC704\uCE58'))), React.createElement('tbody', null, [['\uD0A4\uC6CC\uB4DC \uBD84\uC11D', '\uAC80\uC0C9\uB7C9, \uACBD\uC7C1\uAC15\uB3C4, \uC2DC\uC7A5\uADDC\uBAA8, \uACE8\uB4E0\uD0A4\uC6CC\uB4DC \uB4F1 11\uAC00\uC9C0 + AI \uD53C\uB4DC\uBC31', '\uBD84\uC11D \uD0ED'], ['\uC5C5\uCCB4\uAD00\uB9AC', '\uC5C5\uCCB4\uBCC4 \uD0A4\uC6CC\uB4DC \uBD84\uC11D \uB204\uC801, \uC77C\uC790\uBCC4 \uCD94\uC774, \uC21C\uC704 \uC774\uB825', '\uC5C5\uCCB4\uAD00\uB9AC \uD0ED'], ['\uC790\uB3D9 \uBD84\uC11D', '\uB9E4\uC77C 05:00 \uC804\uCCB4 \uC5C5\uCCB4 \uD0A4\uC6CC\uB4DC \uC790\uB3D9 \uBD84\uC11D + HTML \uBCF4\uACE0\uC11C', '\uC790\uB3D9 (\uC2A4\uCF00\uC904\uB7EC)'], ['\uC21C\uC704 \uCD94\uC801', '\uB4F1\uB85D \uC0C1\uD488\uC758 \uD0A4\uC6CC\uB4DC\uBCC4 \uB124\uC774\uBC84 \uC1FC\uD551 \uC21C\uC704 \uC790\uB3D9 \uAE30\uB85D', '\uC5C5\uCCB4\uAD00\uB9AC > \uC21C\uC704 \uC774\uB825'], ['HTML \uBCF4\uACE0\uC11C', '\uBD84\uC11D \uACB0\uACFC\uB97C \uAE54\uB054\uD55C HTML \uBB38\uC11C\uB85C \uB2E4\uC6B4\uB85C\uB4DC', '\uBD84\uC11D \uD0ED \uD558\uB2E8 / \uC5C5\uCCB4\uAD00\uB9AC'], ['AI \uD53C\uB4DC\uBC31', 'Claude AI\uAC00 \uAC01 \uBD84\uC11D \uC139\uC158\uC5D0 \uB9DE\uCDA4\uD615 \uC804\uB7B5 \uC81C\uC548', '\uBD84\uC11D \uACB0\uACFC \uB0B4 \uAC01 \uC139\uC158']].map(function (row, i) {
          return React.createElement('tr', {
            key: i
          }, React.createElement('td', {
            style: Object.assign({}, tdStyle, {
              fontWeight: 600,
              whiteSpace: 'nowrap'
            })
          }, row[0]), React.createElement('td', {
            style: tdStyle
          }, row[1]), React.createElement('td', {
            style: Object.assign({}, tdStyle, {
              whiteSpace: 'nowrap'
            })
          }, row[2]));
        }))), React.createElement('h3', {
          style: h3Style
        }, '\uC2DC\uC2A4\uD15C \uAD6C\uC131\uB3C4'), React.createElement('div', {
          style: tipBoxStyle
        }, '\uD504\uB860\uD2B8\uC5D4\uB4DC: React \uAE30\uBC18 SPA (Single Page Application)\n\uBC31\uC5D4\uB4DC: FastAPI (Python) + SQLite \uB370\uC774\uD130\uBCA0\uC774\uC2A4\n\uC678\uBD80 API: \uB124\uC774\uBC84 \uAC80\uC0C9\uAD11\uACE0 API + \uB124\uC774\uBC84 \uC1FC\uD551 \uB370\uC774\uD130\uC218\uC9D1(Bright Data)\nAI \uC5D4\uC9C4: Claude API (Anthropic) \u2014 \uBD84\uC11D \uACB0\uACFC \uD53C\uB4DC\uBC31 \uC0DD\uC131\n\uC11C\uBC84: Docker \uCEE8\uD14C\uC774\uB108 \uAE30\uBC18 VPS \uBC30\uD3EC')), /* 운영 시간표 */
        React.createElement('div', {
          style: cardStyle
        }, React.createElement('h3', {
          style: Object.assign({}, h3Style, {
            marginTop: 0
          })
        }, '\uC6B4\uC601 \uC2DC\uAC04\uD45C'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uC2DC\uAC04'), React.createElement('th', {
          style: thStyle
        }, '\uC791\uC5C5'), React.createElement('th', {
          style: thStyle
        }, '\uBE44\uC6A9 \uBC1C\uC0DD'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC624\uC804 07:00'), React.createElement('td', {
          style: tdStyle
        }, '\uC790\uB3D9 \uBD84\uC11D \uC2A4\uCF00\uC904\uB7EC \uC2E4\uD589 (\uC804\uCCB4 \uC5C5\uCCB4 \uD0A4\uC6CC\uB4DC \uBD84\uC11D + \uC21C\uC704 \uCCB4\uD06C)'), React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#dcfce7', '#16a34a')
        }, 'API\uBE44\uC6A9\uB9CC (AI \uBBF8\uD638\uCD9C)'))), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC5C5\uBB34 \uC2DC\uAC04'), React.createElement('td', {
          style: tdStyle
        }, '\uC9C1\uC6D0 \uC218\uB3D9 \uBD84\uC11D (\uBD84\uC11D \uD0ED \uB610\uB294 \uC5C5\uCCB4\uAD00\uB9AC\uC5D0\uC11C \uC2E4\uD589)'), React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#fee2e2', '#dc2626')
        }, 'API + AI \uBE44\uC6A9 \uBC1C\uC0DD'))), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC218\uC2DC'), React.createElement('td', {
          style: tdStyle
        }, '\uC21C\uC704 \uC774\uB825 \uC870\uD68C, \uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC, \uB370\uC774\uD130 \uD655\uC778'), React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#dcfce7', '#16a34a')
        }, '\uBB34\uB8CC (\uC800\uC7A5\uB41C \uB370\uC774\uD130 \uC870\uD68C)')))))));

      /* ==================== 비용 안내 ==================== */
      case 'cost':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\uD83D\uDCB0 \uBD84\uC11D \uBE44\uC6A9 \uC548\uB0B4'), React.createElement('p', {
          style: pStyle
        }, '\uBD84\uC11D\uC744 \uC2E4\uD589\uD560 \uB54C\uB9C8\uB2E4 \uC678\uBD80 API \uD638\uCD9C \uBE44\uC6A9\uC774 \uBC1C\uC0DD\uD569\uB2C8\uB2E4. \uBD88\uD544\uC694\uD55C \uBD84\uC11D\uC744 \uC904\uC774\uACE0, \uD6A8\uC728\uC801\uC73C\uB85C \uC0AC\uC6A9\uD574\uC57C \uD68C\uC0AC \uBE44\uC6A9\uC744 \uC808\uAC10\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'), React.createElement('div', {
          style: costBoxStyle
        }, '\u26A0\uFE0F \uC911\uC694: \uBD84\uC11D \uBC84\uD2BC\uC744 \uB204\uB97C \uB54C\uB9C8\uB2E4 \uC2E4\uC81C \uBE44\uC6A9\uC774 \uBC1C\uC0DD\uD569\uB2C8\uB2E4. \uD14C\uC2A4\uD2B8 \uBAA9\uC801\uC758 \uBB34\uC758\uBBF8\uD55C \uBC18\uBCF5 \uBD84\uC11D\uC740 \uC790\uC81C\uD574\uC8FC\uC138\uC694.'), React.createElement('h3', {
          style: h3Style
        }, '\uBE44\uC6A9 \uBC1C\uC0DD \uAD6C\uC870'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uD56D\uBAA9'), React.createElement('th', {
          style: thStyle
        }, '\uC124\uBA85'), React.createElement('th', {
          style: Object.assign({}, thStyle, {
            textAlign: 'right'
          })
        }, '\uBE44\uC6A9'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, 'Claude AI \uD53C\uB4DC\uBC31'), React.createElement('td', {
          style: tdStyle
        }, '\uBD84\uC11D \uACB0\uACFC 9\uAC1C \uC139\uC158\uC5D0 AI\uAC00 \uB9DE\uCDA4\uD615 \uC804\uB7B5 \uC81C\uC548'), React.createElement('td', {
          style: tdRightStyle
        }, '1\uD68C \uD638\uCD9C\uB2F9 $0.012 (\uC57D 17\uC6D0)')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, 'Bright Data \uB370\uC774\uD130 \uC218\uC9D1'), React.createElement('td', {
          style: tdStyle
        }, '\uB124\uC774\uBC84 \uC1FC\uD551 \uC0C1\uC704 \uC0C1\uD488 \uB370\uC774\uD130 \uD06C\uB864\uB9C1'), React.createElement('td', {
          style: tdRightStyle
        }, '\uBD84\uC11D 1\uAC74\uB2F9 \uD3EC\uD568')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uB124\uC774\uBC84 \uAC80\uC0C9\uAD11\uACE0 API'), React.createElement('td', {
          style: tdStyle
        }, '\uAC80\uC0C9\uB7C9, \uD074\uB9AD\uC218, \uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4 \uC870\uD68C'), React.createElement('td', {
          style: tdRightStyle
        }, '\uBB34\uB8CC (API \uD0A4 \uAE30\uBC18)')))), React.createElement('h3', {
          style: h3Style
        }, '\uBD84\uC11D 1\uAC74\uB2F9 \uBE44\uC6A9'), React.createElement('div', {
          style: Object.assign({}, cardStyle, {
            background: '#fafafa',
            padding: '20px 24px',
            boxShadow: 'none',
            border: '1px solid #e2e8f0'
          })
        }, React.createElement('div', {
          style: {
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 12
          }
        }, React.createElement('div', {
          style: {
            textAlign: 'center',
            flex: 1,
            minWidth: 120
          }
        }, React.createElement('div', {
          style: {
            fontSize: 12,
            color: '#94a3b8',
            marginBottom: 4
          }
        }, 'AI \uD53C\uB4DC\uBC31 9\uC139\uC158'), React.createElement('div', {
          style: {
            fontSize: 24,
            fontWeight: 700,
            color: '#dc2626'
          }
        }, '$0.11'), React.createElement('div', {
          style: {
            fontSize: 11,
            color: '#94a3b8'
          }
        }, '\uC57D 155\uC6D0')), React.createElement('div', {
          style: {
            fontSize: 20,
            color: '#cbd5e1'
          }
        }, '+'), React.createElement('div', {
          style: {
            textAlign: 'center',
            flex: 1,
            minWidth: 120
          }
        }, React.createElement('div', {
          style: {
            fontSize: 12,
            color: '#94a3b8',
            marginBottom: 4
          }
        }, '\uB370\uC774\uD130 \uC218\uC9D1 + API'), React.createElement('div', {
          style: {
            fontSize: 24,
            fontWeight: 700,
            color: '#f59e0b'
          }
        }, '$0.03~'), React.createElement('div', {
          style: {
            fontSize: 11,
            color: '#94a3b8'
          }
        }, '\uC57D 40\uC6D0~')), React.createElement('div', {
          style: {
            fontSize: 20,
            color: '#cbd5e1'
          }
        }, '='), React.createElement('div', {
          style: {
            textAlign: 'center',
            flex: 1,
            minWidth: 120
          }
        }, React.createElement('div', {
          style: {
            fontSize: 12,
            color: '#94a3b8',
            marginBottom: 4
          }
        }, '\uBD84\uC11D 1\uAC74 \uCD1D\uBE44\uC6A9'), React.createElement('div', {
          style: {
            fontSize: 24,
            fontWeight: 700,
            color: '#1e293b'
          }
        }, '\uC57D 200\uC6D0'), React.createElement('div', {
          style: {
            fontSize: 11,
            color: '#94a3b8'
          }
        }, '\uD0A4\uC6CC\uB4DC 1\uAC1C \uAE30\uC900'))))), /* 월간 비용 시뮬레이션 */
        React.createElement('div', {
          style: cardStyle
        }, React.createElement('h3', {
          style: Object.assign({}, h3Style, {
            marginTop: 0
          })
        }, '\uD300 \uADDC\uBAA8\uBCC4 \uC6D4\uAC04 \uBE44\uC6A9 \uC2DC\uBBAC\uB808\uC774\uC158'), React.createElement('p', {
          style: pStyle
        }, '\uC544\uB798\uB294 AI \uD53C\uB4DC\uBC31 \uBE44\uC6A9\uB9CC \uAE30\uC900\uC73C\uB85C \uC0B0\uCD9C\uD55C \uC608\uC0C1 \uC6D4\uAC04 \uBE44\uC6A9\uC785\uB2C8\uB2E4.'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uC2DC\uB098\uB9AC\uC624'), React.createElement('th', {
          style: Object.assign({}, thStyle, {
            textAlign: 'center'
          })
        }, '\uC9C1\uC6D0 \uC218'), React.createElement('th', {
          style: Object.assign({}, thStyle, {
            textAlign: 'center'
          })
        }, '\uC77C \uBD84\uC11D \uD69F\uC218'), React.createElement('th', {
          style: Object.assign({}, thStyle, {
            textAlign: 'center'
          })
        }, '\uC6D4 \uCD1D \uBD84\uC11D'), React.createElement('th', {
          style: Object.assign({}, thStyle, {
            textAlign: 'right'
          })
        }, '\uC608\uC0C1 \uC6D4 \uBE44\uC6A9'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC18C\uADDC\uBAA8'), React.createElement('td', {
          style: tdCenterStyle
        }, '3\uBA85'), React.createElement('td', {
          style: tdCenterStyle
        }, '\uC778\uB2F9 5\uAC74'), React.createElement('td', {
          style: tdCenterStyle
        }, '450\uAC74'), React.createElement('td', {
          style: Object.assign({}, tdRightStyle, {
            color: '#16a34a'
          })
        }, '\uC57D 7.2\uB9CC\uC6D0')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC911\uADDC\uBAA8'), React.createElement('td', {
          style: tdCenterStyle
        }, '5\uBA85'), React.createElement('td', {
          style: tdCenterStyle
        }, '\uC778\uB2F9 10\uAC74'), React.createElement('td', {
          style: tdCenterStyle
        }, '1,500\uAC74'), React.createElement('td', {
          style: Object.assign({}, tdRightStyle, {
            color: '#f59e0b'
          })
        }, '\uC57D 23.5\uB9CC\uC6D0')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uB300\uADDC\uBAA8'), React.createElement('td', {
          style: tdCenterStyle
        }, '10\uBA85'), React.createElement('td', {
          style: tdCenterStyle
        }, '\uC778\uB2F9 15\uAC74'), React.createElement('td', {
          style: tdCenterStyle
        }, '4,500\uAC74'), React.createElement('td', {
          style: Object.assign({}, tdRightStyle, {
            color: '#dc2626'
          })
        }, '\uC57D 71\uB9CC\uC6D0')))), React.createElement('div', {
          style: warnBoxStyle
        }, '\u26A0\uFE0F \uC704 \uAE08\uC561\uC740 AI \uD53C\uB4DC\uBC31 \uBE44\uC6A9\uB9CC \uAE30\uC900\uC785\uB2C8\uB2E4. Bright Data \uB370\uC774\uD130 \uC218\uC9D1 \uBE44\uC6A9\uC774 \uCD94\uAC00\uB85C \uBC1C\uC0DD\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.\n\uBD84\uC11D \uD69F\uC218 = \uD0A4\uC6CC\uB4DC 1\uAC1C\uB2F9 1\uAC74\uC73C\uB85C \uACC4\uC0B0\uD569\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uC0C8\uBCBD \uC790\uB3D9 \uBD84\uC11D\uC740 \uBB34\uB8CC\uC785\uB2C8\uB2E4'), React.createElement('div', {
          style: successBoxStyle
        }, '\u2705 \uC624\uC804 07:00 \uC790\uB3D9 \uBD84\uC11D \uC2A4\uCF00\uC904\uB7EC\uB294 AI \uD53C\uB4DC\uBC31\uC744 \uD638\uCD9C\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.\n\u2705 \uC608\uC2DC: 50\uAC1C \uC5C5\uCCB4 \u00D7 \uD0A4\uC6CC\uB4DC 3\uAC1C = \uD558\uB8E8 150\uAC74 \uC790\uB3D9 \uBD84\uC11D \u2192 AI \uBE44\uC6A9 0\uC6D0\n\u2705 \uAE30\uBCF8 \uB370\uC774\uD130(\uAC80\uC0C9\uB7C9, \uACBD\uC7C1\uC9C0\uC218, \uC21C\uC704 \uB4F1)\uB294 \uBB34\uB8CC\uB85C \uC218\uC9D1\uB429\uB2C8\uB2E4.\n\u2139\uFE0F AI \uD53C\uB4DC\uBC31\uC774 \uD544\uC694\uD55C \uACBD\uC6B0 \uC5C5\uBB34 \uC2DC\uAC04\uC5D0 \uC218\uB3D9\uC73C\uB85C \uBD84\uC11D\uC744 \uC2E4\uD589\uD574\uC8FC\uC138\uC694.'), React.createElement('h3', {
          style: h3Style
        }, '\uBE44\uC6A9 \uC808\uAC10 \uC694\uB839'), React.createElement('div', {
          style: tipBoxStyle
        }, '\uD83D\uDCA1 \uAC19\uC740 \uD0A4\uC6CC\uB4DC\uB97C \uD558\uB8E8\uC5D0 \uC5EC\uB7EC \uBC88 \uBD84\uC11D\uD558\uC9C0 \uB9C8\uC138\uC694. \uC2DC\uC7A5 \uB370\uC774\uD130\uB294 \uC77C\uB2E8\uC704\uB85C \uBCC0\uD569\uB2C8\uB2E4.\n\uD83D\uDCA1 \uC0C8\uBCBD \uC790\uB3D9 \uBD84\uC11D\uC73C\uB85C \uCDA9\uBD84\uD55C \uACBD\uC6B0, \uC218\uB3D9 \uBD84\uC11D \uC5C6\uC774 \uC800\uC7A5\uB41C \uB370\uC774\uD130\uB9CC \uD655\uC778\uD558\uC138\uC694.\n\uD83D\uDCA1 \uD14C\uC2A4\uD2B8 \uBAA9\uC801\uC758 \uBC18\uBCF5 \uBD84\uC11D\uC740 \uBE44\uC6A9\uB9CC \uBC1C\uC0DD\uD558\uACE0 \uC758\uBBF8 \uC5C6\uB294 \uACB0\uACFC\uAC00 \uB098\uC635\uB2C8\uB2E4.\n\uD83D\uDCA1 \uC5C5\uCCB4\uAD00\uB9AC\uC5D0\uC11C \uC77C\uC790\uBCC4 \uCD94\uC774\uB97C \uD655\uC778\uD558\uB294 \uAC83\uC740 \uBB34\uB8CC\uC785\uB2C8\uB2E4 (\uC774\uBBF8 \uC800\uC7A5\uB41C \uB370\uC774\uD130 \uC870\uD68C).')));

      /* ==================== 빠른 시작 가이드 ==================== */
      case 'quickstart':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\uD83D\uDE80 \uBE60\uB978 \uC2DC\uC791 \uAC00\uC774\uB4DC'), React.createElement('p', {
          style: pStyle
        }, '\uCC98\uC74C \uC0AC\uC6A9\uD558\uC2DC\uB294 \uBD84\uC744 \uC704\uD55C 5\uBD84 \uD575\uC2EC \uAC00\uC774\uB4DC\uC785\uB2C8\uB2E4. \uC544\uB798 \uC21C\uC11C\uB300\uB85C \uB530\uB77C\uD558\uC138\uC694.'), React.createElement('div', {
          style: stepRowStyle
        }, React.createElement('span', {
          style: stepNumStyle
        }, '1'), React.createElement('div', null, React.createElement('div', {
          style: {
            fontWeight: 600,
            fontSize: 14,
            color: '#1e293b',
            marginBottom: 4
          }
        }, '\uB85C\uADF8\uC778'), React.createElement('p', {
          style: Object.assign({}, pStyle, {
            marginBottom: 0
          })
        }, '\uAD00\uB9AC\uC790\uAC00 \uBC1C\uAE09\uD55C \uACC4\uC815(ID/\uBE44\uBC00\uBC88\uD638)\uC73C\uB85C \uB85C\uADF8\uC778\uD569\uB2C8\uB2E4. \uCD5C\uCD08 \uB85C\uADF8\uC778 \uD6C4 \uBC18\uB4DC\uC2DC \uBE44\uBC00\uBC88\uD638\uB97C \uBCC0\uACBD\uD574\uC8FC\uC138\uC694.'))), React.createElement('div', {
          style: stepRowStyle
        }, React.createElement('span', {
          style: stepNumStyle
        }, '2'), React.createElement('div', null, React.createElement('div', {
          style: {
            fontWeight: 600,
            fontSize: 14,
            color: '#1e293b',
            marginBottom: 4
          }
        }, '\uBD84\uC11D \uD0ED\uC5D0\uC11C \uD0A4\uC6CC\uB4DC \uBD84\uC11D'), React.createElement('p', {
          style: Object.assign({}, pStyle, {
            marginBottom: 0
          })
        }, '\uBD84\uC11D \uD0ED\uC73C\uB85C \uC774\uB3D9 \u2192 \uD0A4\uC6CC\uB4DC \uC785\uB825 (ex: "\uBB34\uC120\uC774\uC5B4\uD3F0") \u2192 \uBD84\uC11D \uBC84\uD2BC \uD074\uB9AD. \uACB0\uACFC\uAC00 \uC57D 5~10\uCD08 \uD6C4 11\uAC00\uC9C0 \uC139\uC158\uC73C\uB85C \uD45C\uC2DC\uB429\uB2C8\uB2E4.'))), React.createElement('div', {
          style: stepRowStyle
        }, React.createElement('span', {
          style: stepNumStyle
        }, '3'), React.createElement('div', null, React.createElement('div', {
          style: {
            fontWeight: 600,
            fontSize: 14,
            color: '#1e293b',
            marginBottom: 4
          }
        }, 'AI \uD53C\uB4DC\uBC31 \uD655\uC778'), React.createElement('p', {
          style: Object.assign({}, pStyle, {
            marginBottom: 0
          })
        }, '\uAC01 \uBD84\uC11D \uC139\uC158 \uD558\uB2E8\uC5D0 Claude AI\uC758 \uB9DE\uCDA4\uD615 \uC804\uB7B5 \uC81C\uC548\uC774 \uD45C\uC2DC\uB429\uB2C8\uB2E4. \uC2DC\uC7A5 \uD604\uD669\uC5D0 \uB300\uD55C \uD575\uC2EC \uC778\uC0AC\uC774\uD2B8\uB97C \uD655\uC778\uD558\uC138\uC694.'))), React.createElement('div', {
          style: stepRowStyle
        }, React.createElement('span', {
          style: stepNumStyle
        }, '4'), React.createElement('div', null, React.createElement('div', {
          style: {
            fontWeight: 600,
            fontSize: 14,
            color: '#1e293b',
            marginBottom: 4
          }
        }, '\uC5C5\uCCB4 \uB4F1\uB85D & \uCD94\uC801'), React.createElement('p', {
          style: Object.assign({}, pStyle, {
            marginBottom: 0
          })
        }, '\uBD84\uC11D \uACB0\uACFC\uAC00 \uB9C8\uC74C\uC5D0 \uB4E4\uBA74 "\uC5C5\uCCB4\uC5D0 \uC800\uC7A5" \uBC84\uD2BC\uC744 \uB20C\uB7EC \uC5C5\uCCB4\uAD00\uB9AC\uC5D0 \uB4F1\uB85D\uD558\uC138\uC694. \uC774\uD6C4 \uC77C\uC790\uBCC4 \uCD94\uC774\uC640 \uC21C\uC704 \uBCC0\uD654\uB97C \uC790\uB3D9 \uCD94\uC801\uD569\uB2C8\uB2E4.'))), React.createElement('div', {
          style: stepRowStyle
        }, React.createElement('span', {
          style: stepNumStyle
        }, '5'), React.createElement('div', null, React.createElement('div', {
          style: {
            fontWeight: 600,
            fontSize: 14,
            color: '#1e293b',
            marginBottom: 4
          }
        }, '\uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC'), React.createElement('p', {
          style: Object.assign({}, pStyle, {
            marginBottom: 0
          })
        }, '\uBD84\uC11D \uACB0\uACFC \uD558\uB2E8 "HTML \uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC" \uBC84\uD2BC\uC73C\uB85C \uBCF4\uACE0\uC11C\uB97C \uC800\uC7A5\uD558\uC138\uC694. \uACE0\uAC1D \uBBF8\uD305\uC774\uB098 \uB0B4\uBD80 \uBCF4\uACE0\uC5D0 \uD65C\uC6A9\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'))), React.createElement('hr', {
          style: dividerStyle
        }), React.createElement('div', {
          style: successBoxStyle
        }, '\u2705 \uCD95\uD558\uD569\uB2C8\uB2E4! \uC704 5\uB2E8\uACC4\uB9CC \uC54C\uBA74 \uAE30\uBCF8\uC801\uC778 \uC0AC\uC6A9\uC774 \uAC00\uB2A5\uD569\uB2C8\uB2E4.\n\uB354 \uC790\uC138\uD55C \uC0AC\uC6A9\uBC95\uC740 \uC88C\uCE21 \uBA54\uB274\uC758 \uAC01 \uD56D\uBAA9\uC744 \uCC38\uACE0\uD574\uC8FC\uC138\uC694.')));

      /* ==================== 로그인 & 권한 ==================== */
      case 'login':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\uD83D\uDD10 \uB85C\uADF8\uC778 & \uAD8C\uD55C \uCCB4\uACC4'), React.createElement('p', {
          style: pStyle
        }, '\uB85C\uADF8\uC778 \uD6C4 \uBD80\uC5EC\uB41C \uC5ED\uD560(Role)\uC5D0 \uB530\uB77C \uC811\uADFC \uAC00\uB2A5\uD55C \uAE30\uB2A5\uC774 \uB2E4\uB985\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uC5ED\uD560\uBCC4 \uAD8C\uD55C \uBE44\uAD50'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uC5ED\uD560'), React.createElement('th', {
          style: thStyle
        }, '\uBD84\uC11D'), React.createElement('th', {
          style: thStyle
        }, '\uC5C5\uCCB4\uAD00\uB9AC'), React.createElement('th', {
          style: thStyle
        }, '\uC5C5\uCCB4 \uB4F1\uB85D/\uC0AD\uC81C'), React.createElement('th', {
          style: thStyle
        }, '\uC9C1\uC6D0 \uAD00\uB9AC'), React.createElement('th', {
          style: thStyle
        }, '\uC54C\uB9BC \uC124\uC815'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#fee2e2', '#dc2626')
        }, 'Admin')), React.createElement('td', {
          style: tdCenterStyle
        }, '\u2705'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u2705'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u2705'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u2705'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u2705')), React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#dbeafe', '#1d4ed8')
        }, 'Manager')), React.createElement('td', {
          style: tdCenterStyle
        }, '\u2705'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u2705'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u2705 (\uBCF8\uC778 \uB4F1\uB85D\uBD84)'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u274C'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u274C')), React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#f1f5f9', '#64748b')
        }, 'Viewer')), React.createElement('td', {
          style: tdCenterStyle
        }, '\u2705 (\uC77C 3\uD68C)'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u2705 (\uC804\uCCB4 \uC5C5\uCCB4 \uC870\uD68C)'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u274C'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u274C'), React.createElement('td', {
          style: tdCenterStyle
        }, '\u274C')))), React.createElement('h3', {
          style: h3Style
        }, '\uBE44\uBC00\uBC88\uD638 \uBCC0\uACBD'), React.createElement('p', {
          style: pStyle
        }, '\uC0C1\uB2E8 \uD0ED\uBC14 \uC6B0\uCE21\uC758 "\uBE44\uBC00\uBC88\uD638 \uBCC0\uACBD" \uBC84\uD2BC\uC744 \uD074\uB9AD\uD558\uBA74 \uD604\uC7AC \uBE44\uBC00\uBC88\uD638\uC640 \uC0C8 \uBE44\uBC00\uBC88\uD638\uB97C \uC785\uB825\uD558\uB294 \uD31D\uC5C5\uC774 \uB098\uD0C0\uB0A9\uB2C8\uB2E4.'), React.createElement('div', {
          style: warnBoxStyle
        }, '\u26A0\uFE0F \uCD5C\uCD08 \uB85C\uADF8\uC778 \uD6C4 \uBC18\uB4DC\uC2DC \uBE44\uBC00\uBC88\uD638\uB97C \uBCC0\uACBD\uD574\uC8FC\uC138\uC694. \uCD08\uAE30 \uBE44\uBC00\uBC88\uD638\uB294 \uBCF4\uC548\uC5D0 \uCDE8\uC57D\uD569\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uB85C\uADF8\uC778 \uC774\uB825'), React.createElement('p', {
          style: pStyle
        }, '\uAD00\uB9AC\uC790\uB294 \uC9C1\uC6D0 \uAD00\uB9AC \uD0ED\uC5D0\uC11C \uAC01 \uACC4\uC815\uC758 \uB85C\uADF8\uC778 \uC774\uB825(\uC2DC\uAC04, IP \uC8FC\uC18C)\uC744 \uD655\uC778\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4. \uBE44\uC815\uC0C1\uC801\uC778 \uC811\uADFC\uC774 \uAC10\uC9C0\uB418\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C \uBB38\uC758\uD558\uC138\uC694.'), React.createElement('div', {
          style: tipBoxStyle
        }, '\uD83D\uDCA1 Viewer \uACC4\uC815\uC740 \uD558\uB8E8 3\uD68C \uBD84\uC11D \uC81C\uD55C\uC774 \uC788\uC2B5\uB2C8\uB2E4. \uC81C\uD55C \uCD08\uACFC \uC2DC \uB2E4\uC74C \uB0A0 \uC790\uC815\uC5D0 \uCD08\uAE30\uD654\uB429\uB2C8\uB2E4. \uBD84\uC11D \uD69F\uC218\uAC00 \uBD80\uC871\uD558\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C Manager \uC5ED\uD560 \uC2B9\uACA9\uC744 \uC694\uCCAD\uD558\uC138\uC694.')));

      /* ==================== 분석 탭 사용법 ==================== */
      case 'analysis':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\uD83D\uDCCA \uBD84\uC11D \uD0ED \uC0AC\uC6A9\uBC95'), React.createElement('h3', {
          style: h3Style
        }, '1\uB2E8\uACC4: \uD0A4\uC6CC\uB4DC \uC785\uB825'), React.createElement('p', {
          style: pStyle
        }, '\uC0C1\uB2E8 \uAC80\uC0C9\uCC3D\uC5D0 \uBD84\uC11D\uD558\uB824\uB294 \uD0A4\uC6CC\uB4DC\uB97C \uC785\uB825\uD569\uB2C8\uB2E4. \uC608: "\uAC74\uAC15\uC74C\uB8CC", "\uB538\uAE30", "\uBB34\uC120\uC774\uC5B4\uD3F0".'), React.createElement('div', {
          style: tipBoxStyle
        }, '\uD83D\uDCA1 \uD0A4\uC6CC\uB4DC \uC785\uB825 \uD301:\n\u2022 \uB108\uBB34 \uB113\uC740 \uD0A4\uC6CC\uB4DC(\uC608: "\uC637") \uBCF4\uB2E4 \uAD6C\uCCB4\uC801\uC778 \uD0A4\uC6CC\uB4DC(\uC608: "\uC5EC\uC131 \uACE8\uD504\uC6E8\uC5B4")\uAC00 \uB354 \uC720\uC6A9\uD569\uB2C8\uB2E4.\n\u2022 \uC0C1\uD488 URL(\uC120\uD0DD)\uC744 \uD568\uAED8 \uC785\uB825\uD558\uBA74 \uD574\uB2F9 \uC0C1\uD488\uC758 \uC21C\uC704\uC640 \uACBD\uC7C1\uC0AC \uBE44\uAD50 \uBD84\uC11D\uC774 \uCD94\uAC00\uB429\uB2C8\uB2E4.\n\u2022 \uD0A4\uC6CC\uB4DC\uB294 \uC18C\uBE44\uC790\uAC00 \uC2E4\uC81C\uB85C \uAC80\uC0C9\uD560 \uBC95\uD55C \uB2E8\uC5B4\uB85C \uC785\uB825\uD558\uC138\uC694.'), React.createElement('h3', {
          style: h3Style
        }, '2\uB2E8\uACC4: \uBD84\uC11D \uACB0\uACFC \uD655\uC778'), React.createElement('p', {
          style: pStyle
        }, '\uBD84\uC11D\uC740 \uC57D 5~10\uCD08 \uC18C\uC694\uB429\uB2C8\uB2E4. \uC644\uB8CC\uB418\uBA74 \uC544\uB798 11\uAC00\uC9C0 \uC139\uC158\uC774 \uC21C\uC11C\uB300\uB85C \uD45C\uC2DC\uB429\uB2C8\uB2E4:'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: Object.assign({}, thStyle, {
            width: 30
          })
        }, '#'), React.createElement('th', {
          style: thStyle
        }, '\uC139\uC158'), React.createElement('th', {
          style: thStyle
        }, '\uD655\uC778 \uD3EC\uC778\uD2B8'), React.createElement('th', {
          style: thStyle
        }, 'AI \uD53C\uB4DC\uBC31'))), React.createElement('tbody', null, [['1', '\uC885\uD569 \uC694\uC57D \uCE74\uB4DC', '\uAC80\uC0C9\uB7C9, \uC0C1\uD488 \uC218, \uACBD\uC7C1\uAC15\uB3C4, \uACE8\uB4E0\uD0A4\uC6CC\uB4DC \uC218', '\u2705'], ['2', '\uACBD\uC7C1\uAC15\uB3C4 \uBD84\uC11D', '\uBE14\uB8E8\uC624\uC158/\uBCF4\uD1B5/\uB808\uB4DC\uC624\uC158 \uD310\uC815 \uBC0F \uACBD\uC7C1\uC9C0\uC218', '\u2705'], ['3', '\uC2DC\uC7A5 \uADDC\uBAA8 \uCD94\uC815', '\uD3C9\uADE0\uAC00\uACA9, \uC608\uC0C1 \uC6D4 \uC2DC\uC7A5\uADDC\uBAA8, \uC804\uD658\uC728 \uAE30\uBC18', '\u2705'], ['4', '\uD0A4\uC6CC\uB4DC \uD2B8\uB80C\uB4DC', '\uBA54\uC778 vs \uC11C\uBE0C \uD0A4\uC6CC\uB4DC \uBE44\uAD50', '\u2705'], ['5', '\uACE8\uB4E0 \uD0A4\uC6CC\uB4DC', '\uAC80\uC0C9\uB7C9 100~5,000 + \uACBD\uC7C1 \uB0AE\uC74C \uCD94\uCC9C', '\u2705'], ['6', '\uAD11\uACE0 \uACBD\uC7C1 \uC815\uBCF4', '\uAD11\uACE0 \uC785\uCC30 \uACBD\uC7C1\uAC15\uB3C4, PC/\uBAA8\uBC14\uC77C \uD074\uB9AD\uC218', '\u2705'], ['7', '\uCE74\uD14C\uACE0\uB9AC \uBD84\uC11D', '\uC0C1\uC704 \uC0C1\uD488\uB4E4\uC758 \uCE74\uD14C\uACE0\uB9AC \uBD84\uD3EC', '\u2705'], ['8', '\uC5F0\uAD00 \uD0A4\uC6CC\uB4DC \uD0DC\uADF8', '\uACE8\uB4E0\uD0A4\uC6CC\uB4DC \uD3EC\uD568 \uC5F0\uAD00 \uD0A4\uC6CC\uB4DC \uBAA9\uB85D', '\u2014'], ['9', '\uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C', '\uC0C1\uC704 20\uAC1C \uC0C1\uD488\uC758 \uAC00\uACA9/\uBE0C\uB79C\uB4DC/\uCE74\uD14C\uACE0\uB9AC', '\u2705'], ['10', '\uD310\uB9E4\uB7C9 \uCD94\uC815', '\uC21C\uC704\uBCC4 \uC608\uC0C1 \uD310\uB9E4\uB7C9\uACFC \uB9E4\uCD9C \uC2DC\uBBAC\uB808\uC774\uC158', '\u2705'], ['11', '1\uD398\uC774\uC9C0 \uC9C4\uC785 \uC804\uB7B5', '\uC0C1\uC704 5\uC704 \uD3C9\uADE0\uAC00, \uAC00\uACA9 \uBC94\uC704, \uC804\uB7B5 \uC81C\uC548', '\u2705']].map(function (row, i) {
          return React.createElement('tr', {
            key: i
          }, React.createElement('td', {
            style: Object.assign({}, tdStyle, {
              fontWeight: 600
            })
          }, row[0]), React.createElement('td', {
            style: tdStyle
          }, row[1]), React.createElement('td', {
            style: tdStyle
          }, row[2]), React.createElement('td', {
            style: tdCenterStyle
          }, row[3]));
        }))), React.createElement('h3', {
          style: h3Style
        }, '3\uB2E8\uACC4: \uACB0\uACFC \uD65C\uC6A9'), React.createElement('p', {
          style: pStyle
        }, '\uBD84\uC11D \uACB0\uACFC \uD558\uB2E8\uC5D0\uC11C \uB2E4\uC74C \uC791\uC5C5\uC744 \uC120\uD0DD\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4:'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uBC84\uD2BC'), React.createElement('th', {
          style: thStyle
        }, '\uAE30\uB2A5'), React.createElement('th', {
          style: thStyle
        }, '\uC5B8\uC81C \uC0AC\uC6A9'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC5C5\uCCB4\uC5D0 \uC800\uC7A5'), React.createElement('td', {
          style: tdStyle
        }, '\uBD84\uC11D \uACB0\uACFC\uB97C \uC5C5\uCCB4\uAD00\uB9AC\uC5D0 \uB4F1\uB85D'), React.createElement('td', {
          style: tdStyle
        }, '\uC9C0\uC18D\uC801\uC73C\uB85C \uCD94\uC801\uD560 \uD0A4\uC6CC\uB4DC\uC77C \uB54C')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, 'HTML \uBCF4\uACE0\uC11C'), React.createElement('td', {
          style: tdStyle
        }, '\uBD84\uC11D \uACB0\uACFC\uB97C HTML \uD30C\uC77C\uB85C \uB2E4\uC6B4\uB85C\uB4DC'), React.createElement('td', {
          style: tdStyle
        }, '\uACE0\uAC1D \uBBF8\uD305, \uB0B4\uBD80 \uBCF4\uACE0, \uAE30\uB85D \uBCF4\uAD00')))), React.createElement('div', {
          style: warnBoxStyle
        }, '\u26A0\uFE0F \uBD84\uC11D \uC2E4\uD589 \uC2DC \uBE48 \uD398\uC774\uC9C0\uAC00 \uB098\uD0C0\uB098\uBA74 Ctrl+Shift+R(\uAC15\uB825 \uC0C8\uB85C\uACE0\uCE68)\uC744 \uC2DC\uB3C4\uD574\uC8FC\uC138\uC694. \uBB38\uC81C\uAC00 \uC9C0\uC18D\uB418\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C \uBB38\uC758\uD558\uC138\uC694.')));

      /* ==================== 데이터 해석 방법 ==================== */
      case 'data':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\uD83D\uDCC8 \uB370\uC774\uD130 \uD574\uC11D \uBC29\uBC95'), React.createElement('h3', {
          style: h3Style
        }, '\uACBD\uC7C1\uC9C0\uC218 (Competition Index)'), React.createElement('p', {
          style: pStyle
        }, '\uACBD\uC7C1\uC9C0\uC218 = \uB124\uC774\uBC84 \uC1FC\uD551 \uC804\uCCB4 \uC0C1\uD488 \uC218 \u00F7 \uC6D4\uAC04 \uAC80\uC0C9\uB7C9. \uC218\uC694 \uB300\uBE44 \uACF5\uAE09\uC758 \uBE44\uC728\uC744 \uB098\uD0C0\uB0C5\uB2C8\uB2E4.'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uACBD\uC7C1\uC9C0\uC218'), React.createElement('th', {
          style: thStyle
        }, '\uACBD\uC7C1\uC218\uC900'), React.createElement('th', {
          style: thStyle
        }, '\uC758\uBBF8'), React.createElement('th', {
          style: thStyle
        }, '\uC804\uB7B5'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, '0.5 \uBBF8\uB9CC'), React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#dcfce7', '#16a34a')
        }, '\uBE14\uB8E8\uC624\uC158')), React.createElement('td', {
          style: tdStyle
        }, '\uC218\uC694 > \uACF5\uAE09, \uC9C4\uC785 \uC720\uB9AC'), React.createElement('td', {
          style: tdStyle
        }, '\uBE60\uB978 \uC9C4\uC785 \uCD94\uCC9C')), React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, '0.5 ~ 1.0'), React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#fef9c3', '#ca8a04')
        }, '\uBCF4\uD1B5')), React.createElement('td', {
          style: tdStyle
        }, '\uC218\uC694 \u2248 \uACF5\uAE09, \uACBD\uC7C1 \uC801\uB2F9'), React.createElement('td', {
          style: tdStyle
        }, '\uCC28\uBCC4\uD654 \uC804\uB7B5 \uD544\uC694')), React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, '1.0 \uC774\uC0C1'), React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#fee2e2', '#dc2626')
        }, '\uB808\uB4DC\uC624\uC158')), React.createElement('td', {
          style: tdStyle
        }, '\uACF5\uAE09 > \uC218\uC694, \uACBD\uC7C1 \uCE58\uC5F4'), React.createElement('td', {
          style: tdStyle
        }, '\uB871\uD14C\uC77C \uD0A4\uC6CC\uB4DC \uACF5\uB7B5')))), React.createElement('h3', {
          style: h3Style
        }, '\uACBD\uC7C1\uC218\uC900 \uD37C\uC13C\uD2B8'), React.createElement('p', {
          style: pStyle
        }, '\uACBD\uC7C1\uC9C0\uC218\uB97C 0~100% \uC2A4\uCF00\uC77C\uB85C \uBCC0\uD658\uD55C \uAC12\uC785\uB2C8\uB2E4. 30% \uC774\uD558\uBA74 \uBE14\uB8E8\uC624\uC158, 30~70%\uBA74 \uBCF4\uD1B5, 70% \uC774\uC0C1\uC774\uBA74 \uB808\uB4DC\uC624\uC158\uC73C\uB85C \uD310\uC815\uD569\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4'), React.createElement('p', {
          style: pStyle
        }, '\uB124\uC774\uBC84 \uAC80\uC0C9\uAD11\uACE0 API\uC5D0\uC11C \uC81C\uACF5\uD558\uB294 \uAD11\uACE0 \uC785\uCC30 \uACBD\uC7C1 \uC218\uC900\uC785\uB2C8\uB2E4.'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uB4F1\uAE09'), React.createElement('th', {
          style: thStyle
        }, '\uC758\uBBF8'), React.createElement('th', {
          style: thStyle
        }, '\uC2DC\uC0AC\uC810'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#dcfce7', '#16a34a')
        }, '\uB0AE\uC74C')), React.createElement('td', {
          style: tdStyle
        }, '\uAD11\uACE0 \uC785\uCC30 \uACBD\uC7C1\uC774 \uC801\uC74C'), React.createElement('td', {
          style: tdStyle
        }, '\uB0AE\uC740 \uAD11\uACE0\uBE44\uB85C \uC0C1\uC704 \uB178\uCD9C \uAC00\uB2A5')), React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#fef9c3', '#ca8a04')
        }, '\uC911\uAC04')), React.createElement('td', {
          style: tdStyle
        }, '\uC801\uB2F9\uD55C \uC218\uC900\uC758 \uAD11\uACE0 \uACBD\uC7C1'), React.createElement('td', {
          style: tdStyle
        }, '\uD0C0\uAC9F\uD305\uACFC \uC785\uCC30 \uC804\uB7B5 \uD544\uC694')), React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, React.createElement('span', {
          style: badgeStyle('#fee2e2', '#dc2626')
        }, '\uB192\uC74C')), React.createElement('td', {
          style: tdStyle
        }, '\uAD11\uACE0 \uC785\uCC30 \uACBD\uC7C1\uC774 \uCE58\uC5F4'), React.createElement('td', {
          style: tdStyle
        }, '\uB192\uC740 \uAD11\uACE0\uBE44 \uC608\uC0C1, SEO \uBCD1\uD589 \uAD8C\uC7A5')))), React.createElement('h3', {
          style: h3Style
        }, 'PC / \uBAA8\uBC14\uC77C \uD074\uB9AD\uC218'), React.createElement('p', {
          style: pStyle
        }, '\uC6D4 \uD3C9\uADE0 PC \uBC0F \uBAA8\uBC14\uC77C \uD074\uB9AD\uC218\uC785\uB2C8\uB2E4. \uD074\uB9AD\uC218\uAC00 \uB192\uC744\uC218\uB85D \uAD6C\uB9E4 \uC758\uD5A5\uC774 \uB192\uC740 \uD0A4\uC6CC\uB4DC\uC785\uB2C8\uB2E4. \uBAA8\uBC14\uC77C \uD074\uB9AD\uC774 PC\uBCF4\uB2E4 5\uBC30 \uC774\uC0C1 \uB192\uC73C\uBA74 \uBAA8\uBC14\uC77C \uCD5C\uC801\uD654\uAC00 \uD2B9\uD788 \uC911\uC694\uD569\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uC2DC\uC7A5\uADDC\uBAA8'), React.createElement('p', {
          style: pStyle
        }, '\uC0C1\uC704 20\uAC1C \uC0C1\uD488\uC758 \uC608\uC0C1 \uC6D4 \uB9E4\uCD9C \uD569\uACC4\uC785\uB2C8\uB2E4. \uAC80\uC0C9\uB7C9 \u00D7 \uC21C\uC704\uBCC4 CTR \u00D7 \uC804\uD658\uC728(3.5%) \u00D7 \uC0C1\uD488 \uAC00\uACA9\uC73C\uB85C \uCD94\uC815\uD569\uB2C8\uB2E4. \uC2E4\uC81C \uB9E4\uCD9C\uACFC\uB294 \uCC28\uC774\uAC00 \uC788\uC73C\uBBF4\uB85C \uC0C1\uB300\uC801 \uBE44\uAD50 \uC9C0\uD45C\uB85C \uD65C\uC6A9\uD558\uC138\uC694.'), React.createElement('h3', {
          style: h3Style
        }, '\uACE8\uB4E0 \uD0A4\uC6CC\uB4DC \uD310\uC815 \uAE30\uC900'), React.createElement('p', {
          style: pStyle
        }, '\uC544\uB798 \uC870\uAC74\uC744 \uBAA8\uB450 \uB9CC\uC871\uD558\uB294 \uD0A4\uC6CC\uB4DC\uAC00 \uACE8\uB4E0 \uD0A4\uC6CC\uB4DC\uB85C \uBD84\uB958\uB429\uB2C8\uB2E4:'), React.createElement('div', {
          style: tipBoxStyle
        }, '\u2022 \uC6D4\uAC04 \uAC80\uC0C9\uB7C9 100 ~ 5,000\uD68C\n\u2022 \uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4: \uB0AE\uC74C\n\u2022 \uC2A4\uD1A0\uC5B4\uBA85\uC774 \uC544\uB2CC \uC2E4\uC81C \uC0C1\uD488 \uD0A4\uC6CC\uB4DC\n\u2022 \uC6D0\uB798 \uAC80\uC0C9 \uD0A4\uC6CC\uB4DC\uC640 \uC5F0\uAD00\uC131\uC774 \uC788\uC74C'), React.createElement('h3', {
          style: h3Style
        }, '\uB370\uC774\uD130 \uD574\uC11D \uC2DC \uC8FC\uC758\uC0AC\uD56D'), React.createElement('div', {
          style: warnBoxStyle
        }, '\u26A0\uFE0F \uBAA8\uB4E0 \uC218\uCE58\uB294 \uCD94\uC815\uCE58\uC785\uB2C8\uB2E4. \uC808\uB300\uC801\uC778 \uC218\uCE58\uBCF4\uB2E4 \uD0A4\uC6CC\uB4DC \uAC04 \uC0C1\uB300 \uBE44\uAD50\uC5D0 \uD65C\uC6A9\uD558\uC138\uC694.\n\u26A0\uFE0F \uAC80\uC0C9\uB7C9\uACFC \uD074\uB9AD\uC218\uB294 \uC6D4\uAC04 \uD3C9\uADE0\uCE58\uC774\uBBC0\uB85C \uC2DC\uC990 \uBCC0\uB3D9\uC774 \uD06C\uB2C8 \uCC38\uACE0\uD574\uC8FC\uC138\uC694.\n\u26A0\uFE0F AI \uD53C\uB4DC\uBC31\uC740 \uCC38\uACE0\uC6A9\uC774\uBA70 \uCD5C\uC885 \uC758\uC0AC\uACB0\uC815\uC740 \uC2DC\uC7A5 \uC0C1\uD669\uACFC \uACBD\uD5D8\uC744 \uBC14\uD0D5\uC73C\uB85C \uD310\uB2E8\uD558\uC138\uC694.')));

      /* ==================== 업체관리 사용법 ==================== */
      case 'management':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\uD83C\uDFE2 \uC5C5\uCCB4\uAD00\uB9AC \uC0AC\uC6A9\uBC95'), React.createElement('h3', {
          style: h3Style
        }, '\uC5C5\uCCB4 \uB4F1\uB85D \uBC29\uBC95'), React.createElement('p', {
          style: pStyle
        }, '\uC5C5\uCCB4\uB97C \uB4F1\uB85D\uD558\uB294 \uBC29\uBC95\uC740 2\uAC00\uC9C0\uC785\uB2C8\uB2E4:'), React.createElement('div', {
          style: tipBoxStyle
        }, '\uBC29\uBC95 1\uFE0F\u20E3  \uD648 \uD0ED\uC5D0\uC11C \uC5C5\uCCB4 \uCE74\uB4DC \uD074\uB9AD \u2192 \uBD84\uC11D \uC2E4\uD589 \u2192 \uC790\uB3D9 \uC800\uC7A5\n\uBC29\uBC95 2\uFE0F\u20E3  \uBD84\uC11D \uD0ED\uC5D0\uC11C \uD0A4\uC6CC\uB4DC \uBD84\uC11D \uD6C4 \uD558\uB2E8 "\uC5C5\uCCB4\uC5D0 \uC800\uC7A5" \uD074\uB9AD'), React.createElement('h3', {
          style: h3Style
        }, '\uC5C5\uCCB4 \uC0C1\uC138 \uD654\uBA74 \uAD6C\uC131'), React.createElement('p', {
          style: pStyle
        }, '\uC5C5\uCCB4\uB97C \uC120\uD0DD\uD558\uBA74 \uB4F1\uB85D\uB41C \uD0A4\uC6CC\uB4DC \uBAA9\uB85D\uC774 \uD45C\uC2DC\uB429\uB2C8\uB2E4. \uD0A4\uC6CC\uB4DC\uB97C \uD074\uB9AD\uD558\uBA74 \uB450 \uAC00\uC9C0 \uBDF0\uB97C \uC804\uD658\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4:'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uBDF0'), React.createElement('th', {
          style: thStyle
        }, '\uB0B4\uC6A9'), React.createElement('th', {
          style: thStyle
        }, '\uD65C\uC6A9'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC77C\uC790\uBCC4 \uCD94\uC774'), React.createElement('td', {
          style: tdStyle
        }, '\uB0A0\uC9DC\uBCC4 \uAC80\uC0C9\uB7C9, \uD074\uB9AD\uC218, \uACBD\uC7C1\uC9C0\uC218, \uC2DC\uC7A5\uADDC\uBAA8 \uBCC0\uD654'), React.createElement('td', {
          style: tdStyle
        }, '\uC2DC\uC7A5 \uD2B8\uB80C\uB4DC \uD30C\uC545, \uACBD\uC7C1 \uBCC0\uD654 \uBAA8\uB2C8\uD130\uB9C1')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC21C\uC704 \uC774\uB825'), React.createElement('td', {
          style: tdStyle
        }, '\uC0C1\uD488\uC758 \uD0A4\uC6CC\uB4DC\uBCC4 \uB124\uC774\uBC84 \uC1FC\uD551 \uC21C\uC704 \uBCC0\uD654'), React.createElement('td', {
          style: tdStyle
        }, 'SEO \uD6A8\uACFC \uD655\uC778, \uC21C\uC704 \uC0C1\uC2B9/\uD558\uB77D \uCD94\uC801')))), React.createElement('h3', {
          style: h3Style
        }, '\uC77C\uC790\uBCC4 \uCD94\uC774 \uD14C\uC774\uBE14 \uD56D\uBAA9 \uC124\uBA85'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uD56D\uBAA9'), React.createElement('th', {
          style: thStyle
        }, '\uC124\uBA85'), React.createElement('th', {
          style: thStyle
        }, '\uD65C\uC6A9 \uD3EC\uC778\uD2B8'))), React.createElement('tbody', null, [['\uAC80\uC0C9\uB7C9', '\uD574\uB2F9 \uD0A4\uC6CC\uB4DC\uC758 \uC6D4\uAC04 PC + \uBAA8\uBC14\uC77C \uAC80\uC0C9 \uD69F\uC218', '\uAC80\uC0C9\uB7C9 \uCD94\uC774\uB85C \uC2DC\uC990 \uD310\uB2E8'], ['PC \uD074\uB9AD', '\uC6D4 \uD3C9\uADE0 PC \uAD11\uACE0 \uD074\uB9AD\uC218', '\uAD11\uACE0 \uD6A8\uACFC \uD310\uB2E8'], ['\uBAA8\uBC14\uC77C \uD074\uB9AD', '\uC6D4 \uD3C9\uADE0 \uBAA8\uBC14\uC77C \uAD11\uACE0 \uD074\uB9AD\uC218', '\uBAA8\uBC14\uC77C \uBE44\uC911 \uD310\uB2E8'], ['\uACBD\uC7C1\uC9C0\uC218', '\uC0C1\uD488 \uC218 \u00F7 \uAC80\uC0C9\uB7C9 (\uB0AE\uC744\uC218\uB85D \uC720\uB9AC)', '\uACBD\uC7C1 \uBCC0\uD654 \uCD94\uC801'], ['\uACBD\uC7C1\uC218\uC900', '\uACBD\uC7C1\uC9C0\uC218\uB97C \uBC31\uBD84\uC728\uB85C \uBCC0\uD658', '\uBE68\uAC04\uC0C9\uC774\uBA74 \uACBD\uACE0'], ['\uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4', '\uB124\uC774\uBC84 \uAC80\uC0C9\uAD11\uACE0 \uC785\uCC30 \uACBD\uC7C1 \uC218\uC900', '\uAD11\uACE0\uBE44 \uC608\uCE21'], ['\uC2DC\uC7A5\uADDC\uBAA8', '\uC0C1\uC704 20\uAC1C \uC0C1\uD488 \uAE30\uC900 \uC608\uC0C1 \uC6D4 \uB9E4\uCD9C \uD569\uACC4', '\uC2DC\uC7A5 \uAC00\uCE58 \uD310\uB2E8'], ['\uBCF4\uACE0\uC11C', 'HTML \uD615\uC2DD\uC758 \uC0C1\uC138 \uBD84\uC11D \uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC', '\uACE0\uAC1D \uC81C\uCD9C\uC6A9']].map(function (row, i) {
          return React.createElement('tr', {
            key: i
          }, React.createElement('td', {
            style: Object.assign({}, tdStyle, {
              fontWeight: 600,
              whiteSpace: 'nowrap'
            })
          }, row[0]), React.createElement('td', {
            style: tdStyle
          }, row[1]), React.createElement('td', {
            style: Object.assign({}, tdStyle, {
              fontSize: 12,
              color: '#64748b'
            })
          }, row[2]));
        }))), React.createElement('h3', {
          style: h3Style
        }, '\uC5C5\uCCB4 \uC0AD\uC81C \uC2DC \uC8FC\uC758\uC0AC\uD56D'), React.createElement('div', {
          style: warnBoxStyle
        }, '\u26A0\uFE0F \uC5C5\uCCB4\uB97C \uC0AD\uC81C\uD558\uBA74 \uD574\uB2F9 \uC5C5\uCCB4\uC758 \uBAA8\uB4E0 \uD0A4\uC6CC\uB4DC, \uBD84\uC11D \uC774\uB825, \uC21C\uC704 \uAE30\uB85D\uC774 \uD568\uAED8 \uC601\uAD6C \uC0AD\uC81C\uB429\uB2C8\uB2E4.\n\uC0AD\uC81C \uC804 \uBC18\uB4DC\uC2DC \uD544\uC694\uD55C \uBCF4\uACE0\uC11C\uB97C \uBBF8\uB9AC \uB2E4\uC6B4\uB85C\uB4DC\uD574\uB450\uC138\uC694.\nManager \uACC4\uC815\uC740 \uBCF8\uC778\uC774 \uB4F1\uB85D\uD55C \uC5C5\uCCB4\uB9CC \uC0AD\uC81C\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uC790\uB3D9 \uBD84\uC11D \uC2A4\uCF00\uC904'), React.createElement('div', {
          style: successBoxStyle
        }, '\u23F0 \uB9E4\uC77C \uC624\uC804 07:00 \u2014 \uB4F1\uB85D\uB41C \uBAA8\uB4E0 \uC5C5\uCCB4\uC758 \uD0A4\uC6CC\uB4DC\uB97C \uC790\uB3D9 \uBD84\uC11D\uD558\uACE0 HTML \uBCF4\uACE0\uC11C\uB97C \uC0DD\uC131\uD569\uB2C8\uB2E4.\n\u23F0 \uC21C\uC704 \uCCB4\uD06C\uB294 \uC790\uB3D9 \uBD84\uC11D \uC2DC \uD568\uAED8 \uC218\uD589\uB418\uBA70, \uD558\uB8E8 1\uD68C\uB9CC \uAE30\uB85D\uB429\uB2C8\uB2E4.\n\u2705 \uC790\uB3D9 \uBD84\uC11D\uC740 AI \uD53C\uB4DC\uBC31\uC744 \uD638\uCD9C\uD558\uC9C0 \uC54A\uC544 \uCD94\uAC00 \uBE44\uC6A9\uC774 \uBC1C\uC0DD\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.')));

      /* ==================== 순위 추적 해석 ==================== */
      case 'rank':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\uD83C\uDFC6 \uC21C\uC704 \uCD94\uC801 \uD574\uC11D'), React.createElement('p', {
          style: pStyle
        }, '\uC21C\uC704 \uC774\uB825\uC740 \uC5C5\uCCB4\uAD00\uB9AC\uC5D0\uC11C \uD0A4\uC6CC\uB4DC\uB97C \uC120\uD0DD\uD55C \uD6C4 "\uC21C\uC704 \uC774\uB825" \uD0ED\uC5D0\uC11C \uD655\uC778\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uC21C\uC704 \uB370\uC774\uD130 \uC77D\uAE30'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uD56D\uBAA9'), React.createElement('th', {
          style: thStyle
        }, '\uC124\uBA85'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC21C\uC704'), React.createElement('td', {
          style: tdStyle
        }, '\uB124\uC774\uBC84 \uC1FC\uD551 \uAC80\uC0C9 \uACB0\uACFC\uC5D0\uC11C\uC758 \uC704\uCE58 (1\uC704 = \uCD5C\uC0C1\uB2E8)')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uBCC0\uB3D9'), React.createElement('td', {
          style: tdStyle
        }, '\uC774\uC804 \uB300\uBE44 \uC21C\uC704 \uBCC0\uD654 (\uCD08\uB85D\uC0C9 \u25B2 = \uC0C1\uC2B9, \uBE68\uAC04\uC0C9 \u25BC = \uD558\uB77D)')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC720\uD615'), React.createElement('td', {
          style: tdStyle
        }, '\uC790\uB3D9 = \uC2A4\uCF00\uC904\uB7EC \uC790\uB3D9 \uCCB4\uD06C, \uC218\uB3D9 = \uC0AC\uC6A9\uC790\uAC00 \uC9C1\uC811 \uC2E4\uD589')))), React.createElement('h3', {
          style: h3Style
        }, '\uC21C\uC704 \uD574\uC11D \uAC00\uC774\uB4DC'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uC21C\uC704'), React.createElement('th', {
          style: thStyle
        }, '\uB178\uCD9C \uC704\uCE58'), React.createElement('th', {
          style: thStyle
        }, '\uC608\uC0C1 CTR'), React.createElement('th', {
          style: thStyle
        }, '\uC758\uBBF8'), React.createElement('th', {
          style: thStyle
        }, '\uAD8C\uC7A5 \uC561\uC158'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, '1~5\uC704'), React.createElement('td', {
          style: tdStyle
        }, '1\uD398\uC774\uC9C0 \uC0C1\uB2E8'), React.createElement('td', {
          style: tdStyle
        }, '3~8%'), React.createElement('td', {
          style: tdStyle
        }, '\uCD5C\uC6B0\uC218 \u2014 \uB192\uC740 \uD2B8\uB798\uD53D'), React.createElement('td', {
          style: tdStyle
        }, '\uD604 \uC0C1\uD0DC \uC720\uC9C0, \uB9AC\uBDF0 \uAD00\uB9AC')), React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, '6~20\uC704'), React.createElement('td', {
          style: tdStyle
        }, '1\uD398\uC774\uC9C0'), React.createElement('td', {
          style: tdStyle
        }, '0.8~1.5%'), React.createElement('td', {
          style: tdStyle
        }, '\uC591\uD638 \u2014 \uC548\uC815\uC801 \uB178\uCD9C'), React.createElement('td', {
          style: tdStyle
        }, '\uC0C1\uC704 5\uC704 \uC9C4\uC785 \uC704\uD574 \uAC00\uACA9/\uC0C1\uC138\uD398\uC774\uC9C0 \uAC1C\uC120')), React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, '21~40\uC704'), React.createElement('td', {
          style: tdStyle
        }, '2\uD398\uC774\uC9C0'), React.createElement('td', {
          style: tdStyle
        }, '0.3%'), React.createElement('td', {
          style: tdStyle
        }, '\uAC1C\uC120 \uD544\uC694'), React.createElement('td', {
          style: tdStyle
        }, '\uB9AC\uBDF0/\uAC00\uACA9/\uC0C1\uD488\uBA85 \uCD5C\uC801\uD654')), React.createElement('tr', null, React.createElement('td', {
          style: tdStyle
        }, '\uC21C\uC704 \uC5C6\uC74C'), React.createElement('td', {
          style: tdStyle
        }, '2\uD398\uC774\uC9C0 \uC774\uD6C4'), React.createElement('td', {
          style: tdStyle
        }, '< 0.1%'), React.createElement('td', {
          style: tdStyle
        }, '\uB178\uCD9C \uBBF8\uBBF8'), React.createElement('td', {
          style: tdStyle
        }, '\uC0C1\uD488\uBA85/\uCE74\uD14C\uACE0\uB9AC \uC7AC\uAC80\uD1A0, \uACE8\uB4E0\uD0A4\uC6CC\uB4DC \uACF5\uB7B5')))), React.createElement('h3', {
          style: h3Style
        }, '\uC21C\uC704 \uBCC0\uB3D9 \uD328\uD134\uBCC4 \uB300\uC751'), React.createElement('div', {
          style: tipBoxStyle
        }, '\u25B2 3\uC77C \uC5F0\uC18D \uC0C1\uC2B9: \uD604\uC7AC \uC804\uB7B5\uC774 \uD6A8\uACFC\uC801, \uD604 \uC0C1\uD0DC \uC720\uC9C0\n\u25BC 3\uC77C \uC5F0\uC18D \uD558\uB77D: \uACBD\uC7C1\uC0AC \uBD84\uC11D \uD544\uC694, \uAC00\uACA9/\uB9AC\uBDF0/\uC0C1\uC138\uD398\uC774\uC9C0 \uC810\uAC80\n\u2194 \uD070 \uB4F1\uB77D\uC774 \uBC18\uBCF5: \uD0A4\uC6CC\uB4DC \uACBD\uC7C1\uC774 \uCE58\uC5F4\uD55C \uC0C1\uD0DC, \uBCF4\uC870 \uD0A4\uC6CC\uB4DC \uBD84\uC0B0 \uD544\uC694\n\u2014 \uC21C\uC704 \uBCC0\uB3D9 \uC5C6\uC74C: \uC548\uC815\uC801\uC774\uC9C0\uB9CC \uC131\uC7A5 \uC5EC\uC9C0 \uD655\uC778 \uD544\uC694'), React.createElement('div', {
          style: warnBoxStyle
        }, '\u26A0\uFE0F \uC21C\uC704\uB294 \uB124\uC774\uBC84 \uC1FC\uD551 API(\uC720\uC0AC\uB3C4\uC21C) \uAE30\uC900\uC774\uBA70, \uC2E4\uC81C \uBE0C\uB77C\uC6B0\uC800 \uAC80\uC0C9 \uACB0\uACFC(\uAD00\uB828\uB3C4\uC21C)\uC640 \uCC28\uC774\uAC00 \uC788\uC744 \uC218 \uC788\uC2B5\uB2C8\uB2E4. \uCC38\uACE0 \uC9C0\uD45C\uB85C \uD65C\uC6A9\uD574\uC8FC\uC138\uC694.')));

      /* ==================== 보고서 활용 ==================== */
      case 'report':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\uD83D\uDCC4 \uBCF4\uACE0\uC11C \uD65C\uC6A9'), React.createElement('h3', {
          style: h3Style
        }, 'HTML \uBCF4\uACE0\uC11C\uB780?'), React.createElement('p', {
          style: pStyle
        }, '\uBD84\uC11D \uACB0\uACFC\uB97C \uD558\uB098\uC758 HTML \uD30C\uC77C\uB85C \uC815\uB9AC\uD55C \uBB38\uC11C\uC785\uB2C8\uB2E4. \uBE0C\uB77C\uC6B0\uC800\uC5D0\uC11C \uC5F4\uC5B4 \uBC14\uB85C \uD655\uC778\uD558\uAC70\uB098 \uC778\uC1C4(PDF \uBCC0\uD658)\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC \uBC29\uBC95'), React.createElement('div', {
          style: tipBoxStyle
        }, '\uBC29\uBC95 1\uFE0F\u20E3  \uBD84\uC11D \uD0ED \u2014 \uBD84\uC11D \uC644\uB8CC \uD6C4 \uD398\uC774\uC9C0 \uCD5C\uD558\uB2E8 "HTML \uBCF4\uACE0\uC11C \uB2E4\uC6B4\uB85C\uB4DC" \uBC84\uD2BC\n\uBC29\uBC95 2\uFE0F\u20E3  \uC5C5\uCCB4\uAD00\uB9AC \uD0ED \u2014 \uC77C\uC790\uBCC4 \uCD94\uC774 \uD14C\uC774\uBE14\uC758 "HTML" \uBC84\uD2BC (\uB0A0\uC9DC\uBCC4 \uBCF4\uACE0\uC11C)'), React.createElement('h3', {
          style: h3Style
        }, '\uBCF4\uACE0\uC11C \uD3EC\uD568 \uB0B4\uC6A9'), React.createElement('p', {
          style: pStyle
        }, '\uBCF4\uACE0\uC11C\uC5D0\uB294 \uC885\uD569 \uC694\uC57D, \uACBD\uC7C1\uAC15\uB3C4 \uBD84\uC11D, \uC2DC\uC7A5 \uADDC\uBAA8 \uCD94\uC815, \uAD11\uACE0 \uACBD\uC7C1 \uC815\uBCF4, \uACE8\uB4E0 \uD0A4\uC6CC\uB4DC, \uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C, \uD310\uB9E4\uB7C9 \uCD94\uC815, \uC9C4\uC785 \uC804\uB7B5, \uCE74\uD14C\uACE0\uB9AC \uBD84\uC11D, \uD0A4\uC6CC\uB4DC \uD0DC\uADF8, AI \uD53C\uB4DC\uBC31\uC774 \uD3EC\uD568\uB429\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uD65C\uC6A9 \uC0AC\uB840'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uC0C1\uD669'), React.createElement('th', {
          style: thStyle
        }, '\uD65C\uC6A9 \uBC29\uBC95'), React.createElement('th', {
          style: thStyle
        }, '\uD575\uC2EC \uC139\uC158'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uACE0\uAC1D \uBBF8\uD305'), React.createElement('td', {
          style: tdStyle
        }, '\uBCF4\uACE0\uC11C\uB97C \uC778\uC1C4\uD558\uAC70\uB098 \uD654\uBA74 \uACF5\uC720\uD558\uC5EC \uC2DC\uC7A5 \uD604\uD669 \uC124\uBA85'), React.createElement('td', {
          style: tdStyle
        }, '\uC885\uD569\uC694\uC57D, \uACBD\uC7C1\uAC15\uB3C4, \uC9C4\uC785\uC804\uB7B5')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uB0B4\uBD80 \uBCF4\uACE0'), React.createElement('td', {
          style: tdStyle
        }, '\uC77C\uC790\uBCC4 \uBCF4\uACE0\uC11C\uB97C \uBE44\uAD50\uD558\uC5EC \uC2DC\uC7A5 \uBCC0\uD654 \uCD94\uC774 \uBCF4\uACE0'), React.createElement('td', {
          style: tdStyle
        }, '\uC2DC\uC7A5\uADDC\uBAA8, \uD2B8\uB80C\uB4DC, \uD310\uB9E4\uB7C9')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uC804\uB7B5 \uC218\uB9BD'), React.createElement('td', {
          style: tdStyle
        }, '\uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C\uC640 \uC9C4\uC785 \uC804\uB7B5\uC744 \uAE30\uBC18\uC73C\uB85C \uAC00\uACA9/\uB9C8\uCF00\uD305 \uC804\uB7B5 \uC218\uB9BD'), React.createElement('td', {
          style: tdStyle
        }, '\uACBD\uC7C1\uC0AC\uBE44\uAD50, AI\uD53C\uB4DC\uBC31')), React.createElement('tr', null, React.createElement('td', {
          style: Object.assign({}, tdStyle, {
            fontWeight: 600
          })
        }, '\uD0A4\uC6CC\uB4DC \uBC1C\uAD74'), React.createElement('td', {
          style: tdStyle
        }, '\uACE8\uB4E0 \uD0A4\uC6CC\uB4DC \uBAA9\uB85D\uC744 \uD65C\uC6A9\uD558\uC5EC \uC0C8\uB85C\uC6B4 \uD0A4\uC6CC\uB4DC \uAD11\uACE0 \uC804\uB7B5 \uC218\uB9BD'), React.createElement('td', {
          style: tdStyle
        }, '\uACE8\uB4E0\uD0A4\uC6CC\uB4DC, \uC5F0\uAD00\uD0A4\uC6CC\uB4DC')))), React.createElement('div', {
          style: tipBoxStyle
        }, '\uD83D\uDCA1 \uBCF4\uACE0\uC11C\uB97C PDF\uB85C \uBCC0\uD658\uD558\uB824\uBA74 \uBE0C\uB77C\uC6B0\uC800\uC5D0\uC11C HTML \uD30C\uC77C\uC744 \uC5F4\uACE0 Ctrl+P(\uC778\uC1C4) \u2192 "PDF\uB85C \uC800\uC7A5"\uC744 \uC120\uD0DD\uD558\uC138\uC694.')));

      /* ==================== 고급 활용법 ==================== */
      case 'advanced':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\u2699\uFE0F \uACE0\uAE09 \uD65C\uC6A9\uBC95'), React.createElement('p', {
          style: pStyle
        }, '\uAE30\uBCF8 \uAE30\uB2A5\uC5D0 \uC775\uC219\uD574\uC9C4 \uBD84\uC744 \uC704\uD55C \uACE0\uAE09 \uD65C\uC6A9 \uD301\uC785\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uACBD\uC7C1\uC0AC \uBE44\uAD50 \uBD84\uC11D \uD65C\uC6A9'), React.createElement('p', {
          style: pStyle
        }, '\uBD84\uC11D \uC2DC \uC0C1\uD488 URL\uC744 \uD568\uAED8 \uC785\uB825\uD558\uBA74 \uD574\uB2F9 \uC0C1\uD488\uC758 \uC21C\uC704\uC640 \uACBD\uC7C1\uC0AC \uB300\uBE44 \uC704\uCE58\uB97C \uD655\uC778\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'), React.createElement('div', {
          style: tipBoxStyle
        }, '\uD83D\uDCA1 \uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C\uC5D0\uC11C \uD655\uC778\uD560 \uAC83:\n\u2022 \uC0C1\uC704 5\uAC1C \uC0C1\uD488\uC758 \uD3C9\uADE0 \uAC00\uACA9 vs \uB0B4 \uC0C1\uD488 \uAC00\uACA9\n\u2022 \uC0C1\uC704 \uC0C1\uD488\uB4E4\uC758 \uB9AC\uBDF0 \uC218 \u2014 \uB9AC\uBDF0 50\uAC1C \uBBF8\uB9CC\uC774\uBA74 \uCD94\uACA9 \uAC00\uB2A5\n\u2022 \uBE0C\uB79C\uB4DC \uC0C1\uD488 \uBE44\uC728 \u2014 \uBE0C\uB79C\uB4DC \uBE44\uC728\uC774 \uB0AE\uC73C\uBA74 \uC18C\uADDC\uBAA8 \uC140\uB7EC\uC5D0\uAC8C \uAE30\uD68C\n\u2022 \uCE74\uD14C\uACE0\uB9AC \uBD84\uD3EC \u2014 \uC0C1\uC704 \uC0C1\uD488\uC774 \uC5B4\uB5A4 \uCE74\uD14C\uACE0\uB9AC\uC5D0 \uB4F1\uB85D\uB418\uC5B4 \uC788\uB294\uC9C0 \uD655\uC778'), React.createElement('h3', {
          style: h3Style
        }, 'AI \uD53C\uB4DC\uBC31 \uC81C\uB300\uB85C \uD65C\uC6A9\uD558\uAE30'), React.createElement('p', {
          style: pStyle
        }, '\uAC01 \uBD84\uC11D \uC139\uC158\uC758 AI \uD53C\uB4DC\uBC31\uC740 \uD574\uB2F9 \uB370\uC774\uD130\uB97C \uBC14\uD0D5\uC73C\uB85C \uC0DD\uC131\uB41C \uB9DE\uCDA4\uD615 \uC804\uB7B5 \uC81C\uC548\uC785\uB2C8\uB2E4.'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, 'AI \uD53C\uB4DC\uBC31 \uC704\uCE58'), React.createElement('th', {
          style: thStyle
        }, '\uD65C\uC6A9 \uBC29\uBC95'))), React.createElement('tbody', null, [['\uACBD\uC7C1\uAC15\uB3C4 \uD53C\uB4DC\uBC31', '\uC2DC\uC7A5 \uC9C4\uC785 \uC5EC\uBD80 \uD310\uB2E8\uC758 \uADFC\uAC70\uB85C \uD65C\uC6A9'], ['\uC2DC\uC7A5\uADDC\uBAA8 \uD53C\uB4DC\uBC31', '\uB9E4\uCD9C \uAE30\uB300\uCE58 \uC124\uC815\uC758 \uCC38\uACE0\uC790\uB8CC'], ['\uACE8\uB4E0\uD0A4\uC6CC\uB4DC \uD53C\uB4DC\uBC31', '\uAD11\uACE0 \uD0A4\uC6CC\uB4DC \uC120\uC815 \uC2DC \uC6B0\uC120\uC21C\uC704 \uCC38\uACE0'], ['\uACBD\uC7C1\uC0AC\uBE44\uAD50 \uD53C\uB4DC\uBC31', '\uACE0\uAC1D \uC81C\uC548\uC11C\uC5D0 \uACBD\uC7C1 \uD604\uD669 \uC124\uBA85 \uC2DC \uD65C\uC6A9'], ['\uC9C4\uC785\uC804\uB7B5 \uD53C\uB4DC\uBC31', '\uAD6C\uCCB4\uC801\uC778 \uAC00\uACA9/\uD3EC\uC9C0\uC154\uB2DD \uC804\uB7B5\uC758 \uCD9C\uBC1C\uC810']].map(function (row, i) {
          return React.createElement('tr', {
            key: i
          }, React.createElement('td', {
            style: Object.assign({}, tdStyle, {
              fontWeight: 600
            })
          }, row[0]), React.createElement('td', {
            style: tdStyle
          }, row[1]));
        }))), React.createElement('h3', {
          style: h3Style
        }, '\uBCF5\uC218 \uD0A4\uC6CC\uB4DC \uAD50\uCC28 \uBD84\uC11D'), React.createElement('p', {
          style: pStyle
        }, '\uAC19\uC740 \uC0C1\uD488\uC5D0 \uB300\uD574 \uC5EC\uB7EC \uD0A4\uC6CC\uB4DC\uB97C \uBD84\uC11D\uD558\uBA74 \uC5B4\uB5A4 \uD0A4\uC6CC\uB4DC\uAC00 \uAC00\uC7A5 \uD6A8\uACFC\uC801\uC778\uC9C0 \uBE44\uAD50\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'), React.createElement('div', {
          style: tipBoxStyle
        }, '\uD83D\uDCA1 \uC608\uC2DC: "\uBB34\uC120\uC774\uC5B4\uD3F0" vs "\uBE14\uB8E8\uD22C\uC2A4 \uC774\uC5B4\uD3F0" vs "TWS \uC774\uC5B4\uD3F0"\n\u2192 \uAC01\uAC01 \uBD84\uC11D\uD558\uC5EC \uACBD\uC7C1\uC9C0\uC218, \uAC80\uC0C9\uB7C9, \uC2DC\uC7A5\uADDC\uBAA8\uB97C \uBE44\uAD50\uD558\uBA74\n\u2192 \uAC00\uC7A5 \uD6A8\uC728\uC801\uC778 \uD0A4\uC6CC\uB4DC\uB97C \uCC3E\uC744 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'), React.createElement('h3', {
          style: h3Style
        }, '\uC77C\uC790\uBCC4 \uCD94\uC774\uB85C \uC2DC\uC7A5 \uBCC0\uD654 \uAC10\uC9C0'), React.createElement('p', {
          style: pStyle
        }, '\uC5C5\uCCB4\uAD00\uB9AC\uC758 \uC77C\uC790\uBCC4 \uCD94\uC774 \uB370\uC774\uD130\uB97C \uC8FC\uAE30\uC801\uC73C\uB85C \uD655\uC778\uD558\uBA74 \uC2DC\uC7A5 \uBCC0\uD654\uB97C \uC870\uAE30\uC5D0 \uAC10\uC9C0\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'), React.createElement('table', {
          style: tableStyle
        }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
          style: thStyle
        }, '\uBCC0\uD654 \uC2E0\uD638'), React.createElement('th', {
          style: thStyle
        }, '\uC758\uBBF8'), React.createElement('th', {
          style: thStyle
        }, '\uB300\uC751'))), React.createElement('tbody', null, [['\uACBD\uC7C1\uC9C0\uC218 3\uC77C \uC5F0\uC18D \uC0C1\uC2B9', '\uC2E0\uADDC \uC140\uB7EC \uC9C4\uC785 \uC2E0\uD638', '\uCC28\uBCC4\uD654 \uAC15\uD654, \uAD11\uACE0 \uC804\uB7B5 \uC870\uC815'], ['\uAC80\uC0C9\uB7C9 \uAE09\uC99D', '\uC2DC\uC990/\uD2B8\uB80C\uB4DC \uD0A4\uC6CC\uB4DC', '\uBE60\uB978 \uC7AC\uACE0 \uD655\uBCF4, \uAD11\uACE0 \uAC15\uD654'], ['\uAD11\uACE0 \uACBD\uC7C1 "\uB0AE\uC74C\u2192\uB192\uC74C"', '\uAD11\uACE0 \uB2E8\uAC00 \uC0C1\uC2B9 \uC608\uC0C1', '\uC608\uC0B0 \uC870\uC815, SEO \uBCD1\uD589 \uAC15\uD654'], ['\uC2DC\uC7A5\uADDC\uBAA8 \uAC10\uC18C', '\uC218\uC694 \uAC10\uC18C \uB610\uB294 \uAC00\uACA9 \uD558\uB77D', '\uB300\uCCB4 \uD0A4\uC6CC\uB4DC \uBC1C\uAD74, \uD3EC\uD2B8\uD3F4\uB9AC\uC624 \uB2E4\uBCC0\uD654']].map(function (row, i) {
          return React.createElement('tr', {
            key: i
          }, React.createElement('td', {
            style: Object.assign({}, tdStyle, {
              fontWeight: 600
            })
          }, row[0]), React.createElement('td', {
            style: tdStyle
          }, row[1]), React.createElement('td', {
            style: tdStyle
          }, row[2]));
        })))));

      /* ==================== 실전 활용 팁 ==================== */
      case 'tips':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\uD83D\uDCA1 \uC2E4\uC804 \uD65C\uC6A9 \uD301'), React.createElement('h3', {
          style: h3Style
        }, '\uC2E0\uADDC \uC0C1\uD488 \uC9C4\uC785 \uD310\uB2E8 \uCCB4\uD06C\uB9AC\uC2A4\uD2B8'), React.createElement('div', {
          style: tipBoxStyle
        }, '1. \uD0A4\uC6CC\uB4DC \uBD84\uC11D\uC5D0\uC11C \uACBD\uC7C1\uC9C0\uC218 0.5 \uBBF8\uB9CC(\uBE14\uB8E8\uC624\uC158) \uD655\uC778\n2. \uACE8\uB4E0 \uD0A4\uC6CC\uB4DC\uAC00 3\uAC1C \uC774\uC0C1 \uC788\uB294\uC9C0 \uD655\uC778\n3. \uC2DC\uC7A5\uADDC\uBAA8\uAC00 \uCD5C\uC18C 100\uB9CC\uC6D0 \uC774\uC0C1\uC778\uC9C0 \uD655\uC778\n4. \uC0C1\uC704 5\uC704 \uD3C9\uADE0\uAC00\uACA9\uACFC \uB0B4 \uC0C1\uD488 \uAC00\uACA9 \uBE44\uAD50\n5. AI \uC9C4\uC785 \uC804\uB7B5 \uD53C\uB4DC\uBC31 \uD655\uC778\n\u2192 \uC704 \uC870\uAC74\uC744 \uBAA8\uB450 \uB9CC\uC871\uD558\uBA74 \uC9C4\uC785 \uC801\uAE30!'), React.createElement('h3', {
          style: h3Style
        }, '\uAE30\uC874 \uC0C1\uD488 \uAC1C\uC120'), React.createElement('div', {
          style: tipBoxStyle
        }, '1. \uC5C5\uCCB4\uAD00\uB9AC\uC5D0\uC11C \uC21C\uC704 \uC774\uB825 \uCD94\uC801 \u2192 \uC21C\uC704 \uD558\uB77D \uD0A4\uC6CC\uB4DC \uC2DD\uBCC4\n2. \uD574\uB2F9 \uD0A4\uC6CC\uB4DC\uB85C \uC7AC\uBD84\uC11D \u2192 \uACBD\uC7C1\uC0AC \uBE44\uAD50\uD45C\uC5D0\uC11C \uC0C1\uC704 \uC0C1\uD488 \uD655\uC778\n3. \uC0C1\uC704 \uC0C1\uD488 \uB300\uBE44 \uAC00\uACA9/\uB9AC\uBDF0/\uC0C1\uC138\uD398\uC774\uC9C0 \uBE44\uAD50\n4. AI \uD53C\uB4DC\uBC31\uC758 \uAC1C\uC120 \uC81C\uC548 \uD655\uC778\n\u2192 \uBD80\uC871\uD55C \uBD80\uBD84\uC744 \uBCF4\uAC15\uD558\uBA74 \uC21C\uC704 \uD68C\uBCF5 \uAC00\uB2A5'), React.createElement('h3', {
          style: h3Style
        }, '\uC77C\uC790\uBCC4 \uCD94\uC774 \uBAA8\uB2C8\uD130\uB9C1'), React.createElement('div', {
          style: tipBoxStyle
        }, '\u2022 \uACBD\uC7C1\uC9C0\uC218\uAC00 3\uC77C \uC5F0\uC18D \uC0C1\uC2B9 \u2192 \uC2E0\uADDC \uC140\uB7EC \uC9C4\uC785 \uC2E0\uD638, \uCC28\uBCC4\uD654 \uAC15\uD654 \uD544\uC694\n\u2022 \uAC80\uC0C9\uB7C9\uC774 \uAE09\uC99D \u2192 \uC2DC\uC988/\uD2B8\uB80C\uB4DC \uD0A4\uC6CC\uB4DC, \uBE60\uB978 \uC7AC\uACE0 \uD655\uBCF4 \uAC80\uD1A0\n\u2022 \uAD11\uACE0 \uACBD\uC7C1\uAC15\uB3C4 "\uB0AE\uC74C\u2192\uB192\uC74C" \uC804\uD658 \u2192 \uAD11\uACE0 \uB2E8\uAC00 \uC0C1\uC2B9 \uC608\uC0C1, \uC608\uC0B0 \uC870\uC815 \uD544\uC694'), React.createElement('h3', {
          style: h3Style
        }, '\uC790\uC8FC \uD558\uB294 \uC2E4\uC218'), React.createElement('div', {
          style: warnBoxStyle
        }, '\u274C \uACBD\uC7C1\uC9C0\uC218\uB9CC \uBCF4\uACE0 \uC9C4\uC785 \uACB0\uC815 \u2192 \uC2DC\uC7A5\uADDC\uBAA8\uAC00 \uB108\uBB34 \uC791\uC73C\uBA74 \uB9E4\uCD9C\uC774 \uB098\uC624\uC9C0 \uC54A\uC74C\n\u274C \uC21C\uC704\uB9CC \uCD94\uC801\uD558\uACE0 \uC7AC\uBD84\uC11D \uC548 \uD568 \u2192 \uC2DC\uC7A5 \uBCC0\uD654\uB97C \uB193\uCE60 \uC218 \uC788\uC74C\n\u274C \uD558\uB098\uC758 \uD0A4\uC6CC\uB4DC\uC5D0\uB9CC \uC758\uC874 \u2192 \uBC18\uB4DC\uC2DC \uC5F0\uAD00/\uACE8\uB4E0 \uD0A4\uC6CC\uB4DC\uB3C4 \uD568\uAED8 \uB4F1\uB85D\n\u274C \uBCF4\uACE0\uC11C\uB97C \uC800\uC7A5\uD558\uC9C0 \uC54A\uC74C \u2192 \uC77C\uC790\uBCC4 HTML \uBCF4\uACE0\uC11C\uB85C \uBCC0\uD654 \uCD94\uC774 \uAE30\uB85D \uD544\uC218\n\u274C \uAC19\uC740 \uD0A4\uC6CC\uB4DC \uBC18\uBCF5 \uBD84\uC11D \u2192 \uBE44\uC6A9\uB9CC \uBC1C\uC0DD, \uD558\uB8E8 1\uD68C\uBA74 \uCDA9\uBD84')));

      /* ==================== 자주 묻는 질문 ==================== */
      case 'faq':
        return React.createElement('div', null, React.createElement('div', {
          style: cardStyle
        }, React.createElement('h2', {
          style: h2Style
        }, '\u2753 \uC790\uC8FC \uBB3B\uB294 \uC9C8\uBB38'), [{
          q: '\uBD84\uC11D \uACB0\uACFC\uAC00 \uC5B4\uC81C\uC640 \uAC19\uC740\uB370 \uB2E4\uC2DC \uBD84\uC11D\uD574\uC57C \uD558\uB098\uC694?',
          a: '\uC2DC\uC7A5 \uB370\uC774\uD130\uB294 \uC77C\uB2E8\uC704\uB85C \uBCC0\uD569\uB2C8\uB2E4. \uAC19\uC740 \uB0A0 \uBC18\uBCF5 \uBD84\uC11D\uC740 \uBE44\uC6A9\uB9CC \uBC1C\uC0DD\uD569\uB2C8\uB2E4. \uC5C5\uCCB4\uAD00\uB9AC\uC758 \uC800\uC7A5\uB41C \uB370\uC774\uD130\uB97C \uD655\uC778\uD558\uC138\uC694.'
        }, {
          q: '\uC0C8\uBCBD \uC790\uB3D9 \uBD84\uC11D\uACFC \uC218\uB3D9 \uBD84\uC11D\uC758 \uCC28\uC774\uB294?',
          a: '\uC790\uB3D9 \uBD84\uC11D\uC740 \uAE30\uBCF8 \uB370\uC774\uD130(\uAC80\uC0C9\uB7C9, \uACBD\uC7C1\uC9C0\uC218 \uB4F1)\uB9CC \uC218\uC9D1\uD558\uBA70 AI \uD53C\uB4DC\uBC31\uC744 \uD638\uCD9C\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4(= \uBB34\uB8CC). \uC218\uB3D9 \uBD84\uC11D\uC740 AI \uD53C\uB4DC\uBC31\uC774 \uD3EC\uD568\uB418\uC5B4 \uBE44\uC6A9\uC774 \uBC1C\uC0DD\uD569\uB2C8\uB2E4.'
        }, {
          q: 'Viewer \uACC4\uC815\uC758 \uBD84\uC11D \uC81C\uD55C\uC740 \uC5B8\uC81C \uCD08\uAE30\uD654\uB418\uB098\uC694?',
          a: '\uB9E4\uC77C \uC790\uC815(00:00)\uC5D0 \uCD08\uAE30\uD654\uB429\uB2C8\uB2E4. \uBD84\uC11D \uD69F\uC218\uAC00 \uBD80\uC871\uD558\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C Manager \uC5ED\uD560 \uC2B9\uACA9\uC744 \uC694\uCCAD\uD558\uC138\uC694.'
        }, {
          q: '\uBCF4\uACE0\uC11C\uB97C PDF\uB85C \uBC1B\uC744 \uC218 \uC788\uB098\uC694?',
          a: 'HTML \uBCF4\uACE0\uC11C\uB97C \uBE0C\uB77C\uC6B0\uC800\uC5D0\uC11C \uC5F4\uACE0 Ctrl+P \u2192 "PDF\uB85C \uC800\uC7A5"\uC744 \uC120\uD0DD\uD558\uBA74 PDF\uB85C \uBCC0\uD658\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.'
        }, {
          q: '\uC5C5\uCCB4\uB97C \uC0AD\uC81C\uD558\uBA74 \uB370\uC774\uD130\uB3C4 \uC0AC\uB77C\uC9C0\uB098\uC694?',
          a: '\uB124, \uC5C5\uCCB4 \uC0AD\uC81C \uC2DC \uD574\uB2F9 \uC5C5\uCCB4\uC758 \uBAA8\uB4E0 \uD0A4\uC6CC\uB4DC, \uBD84\uC11D \uC774\uB825, \uC21C\uC704 \uAE30\uB85D\uC774 \uC601\uAD6C \uC0AD\uC81C\uB429\uB2C8\uB2E4. \uC0AD\uC81C \uC804 \uBCF4\uACE0\uC11C\uB97C \uBBF8\uB9AC \uB2E4\uC6B4\uB85C\uB4DC\uD574\uB450\uC138\uC694.'
        }, {
          q: '\uBD84\uC11D \uC2DC \uBE48 \uD398\uC774\uC9C0\uAC00 \uB098\uC640\uC694.',
          a: 'Ctrl+Shift+R(\uAC15\uB825 \uC0C8\uB85C\uACE0\uCE68)\uC744 \uC2DC\uB3C4\uD574\uC8FC\uC138\uC694. \uBB38\uC81C\uAC00 \uC9C0\uC18D\uB418\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C \uBB38\uC758\uD558\uC138\uC694.'
        }, {
          q: 'AI \uD53C\uB4DC\uBC31\uC774 \uD56D\uC0C1 \uC815\uD655\uD55C\uAC00\uC694?',
          a: 'AI \uD53C\uB4DC\uBC31\uC740 \uB370\uC774\uD130 \uAE30\uBC18\uC758 \uCC38\uACE0\uC6A9 \uC81C\uC548\uC785\uB2C8\uB2E4. \uCD5C\uC885 \uD310\uB2E8\uC740 \uC2DC\uC7A5 \uC0C1\uD669\uACFC \uACBD\uD5D8\uC744 \uBC14\uD0D5\uC73C\uB85C \uD558\uC138\uC694.'
        }].map(function (item, i) {
          return React.createElement('div', {
            key: i,
            style: {
              marginBottom: 16
            }
          }, React.createElement('h4', {
            style: h4Style
          }, 'Q. ' + item.q), React.createElement('p', {
            style: Object.assign({}, pStyle, {
              paddingLeft: 16,
              borderLeft: '3px solid #e2e8f0'
            })
          }, 'A. ' + item.a));
        }), React.createElement('hr', {
          style: dividerStyle
        }), React.createElement('div', {
          style: tipBoxStyle
        }, '\uD83D\uDCA1 \uC704\uC5D0 \uC5C6\uB294 \uC9C8\uBB38\uC740 \uAD00\uB9AC\uC790\uC5D0\uAC8C \uBB38\uC758\uD574\uC8FC\uC138\uC694.')));
      default:
        return null;
    }
  };

  /* ==================== 메인 레이아웃 ==================== */
  return React.createElement('div', {
    className: 'container',
    style: {
      paddingTop: 24,
      paddingBottom: 40
    }
  }, /* 헤더 */
  React.createElement('div', {
    style: {
      background: 'linear-gradient(135deg, #6C5CE7, #a29bfe)',
      borderRadius: 16,
      padding: '32px 36px',
      marginBottom: 24,
      color: '#fff'
    }
  }, React.createElement('h1', {
    style: {
      fontSize: 24,
      fontWeight: 700,
      marginBottom: 6
    }
  }, '\uD83D\uDCD6 \uC0AC\uC6A9\uC790 \uAC00\uC774\uB4DC\uBD81'), React.createElement('p', {
    style: {
      fontSize: 14,
      opacity: 0.85
    }
  }, '\uB85C\uC9C1 \uBD84\uC11D \uD504\uB85C\uADF8\uB7A8 \uB0B4\uBD80 \uC9C1\uC6D0\uC6A9 \uC0AC\uC6A9 \uC548\uB0B4\uC11C \u2014 \uC0AC\uC6A9 \uBC29\uBC95, \uB370\uC774\uD130 \uD574\uC11D, \uBE44\uC6A9 \uC548\uB0B4, \uD65C\uC6A9 \uD301')), /* 좌우 레이아웃 */
  React.createElement('div', {
    className: 'cd-layout',
    style: {
      display: 'flex',
      gap: 20,
      alignItems: 'flex-start'
    }
  }, /* 좌측 메뉴 */
  React.createElement('div', {
    className: 'cd-sidebar',
    style: {
      width: 200,
      minWidth: 200,
      background: '#fff',
      borderRadius: 14,
      padding: '12px 0',
      boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
      position: 'sticky',
      top: 80
    }
  }, sections.map(function (s) {
    var isActive = activeSection === s.id;
    return React.createElement('button', {
      key: s.id,
      onClick: function () {
        setActiveSection(s.id);
        window.scrollTo({
          top: 0,
          behavior: 'smooth'
        });
      },
      style: {
        display: 'block',
        width: '100%',
        padding: '10px 18px',
        border: 'none',
        cursor: 'pointer',
        textAlign: 'left',
        fontSize: 13,
        fontWeight: isActive ? 700 : 400,
        background: isActive ? '#f0f0ff' : 'transparent',
        color: isActive ? '#6C5CE7' : '#475569',
        borderLeft: isActive ? '3px solid #6C5CE7' : '3px solid transparent',
        transition: 'all 0.15s'
      }
    }, s.icon + ' ' + s.label);
  })), /* 우측 콘텐츠 */
  React.createElement('div', {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, renderContent())));
};

;/* ===== js/components/SectionDivider.jsx ===== */
/* SectionDivider — 섹터 구분 헤더 (v6.1 미리보기 디자인) */
window.SectionDivider = function SectionDivider(props) {
  var label = props && props.label ? props.label : '';
  var icon = props && props.icon ? props.icon : '';
  var color = props && props.color ? props.color : '#4f46e5';
  var sub = props && props.sub ? props.sub : '';
  return /*#__PURE__*/React.createElement("div", {
    className: "report-divider"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 40,
      height: 40,
      borderRadius: 12,
      flexShrink: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: 20,
      color: '#fff',
      background: 'linear-gradient(135deg, ' + color + ', ' + color + 'cc)',
      boxShadow: '0 4px 12px ' + color + '40'
    }
  }, icon), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 900,
      fontSize: 20,
      letterSpacing: '-0.5px',
      color: '#0f172a',
      lineHeight: 1.2
    }
  }, label), sub && /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 500,
      fontSize: 12,
      color: '#64748b',
      marginTop: 2
    }
  }, sub))));
};

;/* ===== js/components/DatalabDemographicsSection.jsx ===== */
/* DatalabDemographicsSection — 성별 + 연령대별 검색 비율 (v5) */
window.DatalabDemographicsSection = function DatalabDemographicsSection(props) {
  if (!props?.data) return null;
  var gender = props.data.gender;
  var age = props.data.age;
  if (!gender && !age) return null;
  var ages = age && age.ages ? age.ages : [];
  var maxAge = ages.length > 0 ? Math.max.apply(null, ages.map(function (a) {
    return a.ratio;
  })) : 1;
  var peakAge = ages.length > 0 ? ages.reduce(function (a, b) {
    return a.ratio > b.ratio ? a : b;
  }) : null;
  var ageColors = ['#94a3b8', '#818cf8', '#4f46e5', '#7c3aed', '#a78bfa', '#94a3b8'];
  var ageGrads = ['linear-gradient(90deg, #94a3b8, #cbd5e1)', 'linear-gradient(90deg, #818cf8, #a78bfa)', 'linear-gradient(90deg, #4f46e5, #6366f1)', 'linear-gradient(90deg, #7c3aed, #8b5cf6)', 'linear-gradient(90deg, #a78bfa, #c4b5fd)', 'linear-gradient(90deg, #94a3b8, #cbd5e1)'];

  /* 핵심 타겟 계산 */
  var targetGender = gender ? gender.female > gender.male ? '여성' : '남성' : '';
  var targetAge = peakAge ? peakAge.label : '';
  var targetPct = gender && peakAge ? gender.female > gender.male ? (peakAge.ratio * gender.female / 100).toFixed(1) : (peakAge.ratio * gender.male / 100).toFixed(1) : '';
  return /*#__PURE__*/React.createElement("div", {
    className: "grid2"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "hic"
  }, "\uD83D\uDC65"), "\uAC80\uC0C9 \uC778\uAD6C\uD1B5\uACC4 \u2014 \uC131\uBCC4 ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uB370\uC774\uD130\uB7A9")), gender ? /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(ChartCanvas, {
    type: "doughnut",
    height: 180,
    data: {
      labels: ['남성', '여성'],
      datasets: [{
        data: [gender.male, gender.female],
        backgroundColor: ['#4f46e5', '#ec4899'],
        borderWidth: 0
      }]
    },
    options: {
      cutout: '62%',
      plugins: {
        legend: {
          position: 'bottom'
        },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              return ctx.label + ' ' + ctx.parsed + '%';
            }
          }
        }
      }
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, gender.male > gender.female ? '남성 ' + gender.male + '% · 여성 ' + gender.female + '% — 남성 타겟 소구.' : '여성 ' + gender.female + '% · 남성 ' + gender.male + '% — 여성 타겟 소구.')) : /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      padding: 40,
      color: '#94a3b8',
      fontSize: 13
    }
  }, "\uB370\uC774\uD130 \uC5C6\uC74C")), /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "hic"
  }, "\uD83D\uDC65"), "\uAC80\uC0C9 \uC778\uAD6C\uD1B5\uACC4 \u2014 \uC5F0\uB839 ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uB370\uC774\uD130\uB7A9")), ages.length > 0 ? /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(ChartCanvas, {
    type: "bar",
    height: 200,
    data: {
      labels: ages.map(function (a) {
        return a.label + (peakAge && a.label === peakAge.label ? ' 🔥' : '');
      }),
      datasets: [{
        label: '검색 비율',
        data: ages.map(function (a) {
          return a.ratio;
        }),
        backgroundColor: ages.map(function (a) {
          return peakAge && a.label === peakAge.label ? '#7c3aed' : '#c7d2fe';
        }),
        borderRadius: 6
      }]
    },
    options: {
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              return ctx.parsed.y + '%';
            }
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            callback: function (v) {
              return v + '%';
            }
          }
        }
      }
    }
  })), peakAge && /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, "\uD575\uC2EC \uD0C0\uAC9F: ", /*#__PURE__*/React.createElement("b", null, targetAge, " ", targetGender), " (\uC804\uCCB4\uC758 \uC57D ", targetPct, "%).")) : /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      padding: 40,
      color: '#94a3b8',
      fontSize: 13
    }
  }, "\uB370\uC774\uD130 \uC5C6\uC74C")));
};

;/* ===== js/components/DatalabTrendSection.jsx ===== */
/* DatalabTrendSection — 12개월 검색량 트렌드 꺾은선 그래프 (v5) */
window.DatalabTrendSection = function DatalabTrendSection(props) {
  if (!props?.data || !props.data.months || props.data.months.length < 3) return null;
  var d = props.data;
  var months = d.months;

  /* SVG 치수 */
  var W = 680,
    H = 220,
    PAD_L = 42,
    PAD_R = 20,
    PAD_T = 25,
    PAD_B = 40;
  var chartW = W - PAD_L - PAD_R;
  var chartH = H - PAD_T - PAD_B;
  var maxR = d.maxRatio || Math.max.apply(null, months.map(function (m) {
    return m.ratio;
  })) || 100;
  var step = chartW / Math.max(months.length - 1, 1);
  function x(i) {
    return PAD_L + i * step;
  }
  function y(v) {
    return PAD_T + chartH - v / maxR * chartH;
  }

  /* 꺾은선 포인트 */
  var points = months.map(function (m, i) {
    return x(i) + ',' + y(m.ratio);
  }).join(' ');
  /* 영역 폴리곤 (아래쪽 채움) */
  var area = x(0) + ',' + (PAD_T + chartH) + ' ' + points + ' ' + x(months.length - 1) + ',' + (PAD_T + chartH);

  /* 그리드 라인 (25 단위) */
  var gridLines = [0, 25, 50, 75, 100].filter(function (v) {
    return v <= maxR;
  });
  if (maxR > 100) gridLines.push(Math.round(maxR));
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDCC8"), "\uD0A4\uC6CC\uB4DC \uAC80\uC0C9\uB7C9 \uD2B8\uB80C\uB4DC (\uCD5C\uADFC 12\uAC1C\uC6D4) ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uB370\uC774\uD130\uB7A9")), /*#__PURE__*/React.createElement("div", {
    className: "grid4",
    style: {
      marginBottom: 6
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uCD5C\uACE0 \uC9C0\uC218"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, d.maxRatio, " ", /*#__PURE__*/React.createElement("small", null, d.maxMonth))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uCD5C\uC800 \uC9C0\uC218"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, d.minRatio, " ", /*#__PURE__*/React.createElement("small", null, d.minMonth))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uD3C9\uADE0 \uC9C0\uC218"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, d.avgRatio)), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "\uBCC0\uB3D9\uD3ED"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, d.range, /*#__PURE__*/React.createElement("small", null, "p")))), /*#__PURE__*/React.createElement("div", {
    className: "chartbox"
  }, /*#__PURE__*/React.createElement(ChartCanvas, {
    type: "line",
    height: 240,
    data: {
      labels: months.map(function (m) {
        return m.label;
      }),
      datasets: [{
        label: '검색 지수',
        data: months.map(function (m) {
          return m.ratio;
        }),
        borderColor: '#4f46e5',
        backgroundColor: function (c) {
          if (!c.chart.ctx) return 'rgba(79,70,229,.12)';
          return window.chartGrad ? window.chartGrad(c.chart.ctx, 'rgba(79,70,229,.22)', 'rgba(79,70,229,0)', 240) : 'rgba(79,70,229,.12)';
        },
        fill: true,
        tension: 0.4,
        borderWidth: 2.5,
        pointRadius: months.map(function (m) {
          return m.ratio === d.maxRatio || m.ratio === d.minRatio ? 6 : 3;
        }),
        pointBackgroundColor: months.map(function (m) {
          return m.ratio === d.maxRatio ? '#4f46e5' : m.ratio === d.minRatio ? '#ef4444' : '#fff';
        }),
        pointBorderColor: months.map(function (m) {
          return m.ratio === d.minRatio ? '#ef4444' : '#4f46e5';
        }),
        pointBorderWidth: 2
      }]
    },
    options: {
      plugins: {
        legend: {
          display: false
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          suggestedMax: d.maxRatio || 100
        }
      }
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, d.trendNote))));
};

;/* ===== js/components/DatalabSeasonSection.jsx ===== */
/* DatalabSeasonSection — 시즌별 수요 예측 (v6) */
window.DatalabSeasonSection = function DatalabSeasonSection(props) {
  if (!props?.data || !props.data.seasons || props.data.seasons.length === 0) return null;
  var d = props.data;
  var seasons = d.seasons;
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDDD3\uFE0F"), "\uC2DC\uC98C\uBCC4 \uC218\uC694 \uC608\uCE21", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uB370\uC774\uD130\uB7A9")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uB370\uC774\uD130\uB7A9 \uC1FC\uD551\uC778\uC0AC\uC774\uD2B8 \uAE30\uBC18 \uC2DC\uC98C \uBD84\uC11D"), /*#__PURE__*/React.createElement("div", {
    className: "grid4"
  }, seasons.map(function (s, i) {
    var isPeak = s.peakSeason || s.grade === '최성수기';
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      className: isPeak ? 'seasoncard peak' : 'seasoncard'
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 22
      }
    }, s.icon), /*#__PURE__*/React.createElement("b", null, s.name), /*#__PURE__*/React.createElement("div", {
      className: "desc",
      style: {
        margin: '2px 0'
      }
    }, s.period), /*#__PURE__*/React.createElement("div", {
      style: {
        fontWeight: 800,
        color: isPeak ? '#c2410c' : undefined
      }
    }, "\uC9C0\uC218 ", Math.round(s.index), isPeak ? ' 🔥' : ''), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: isPeak ? '#c2410c' : 'var(--sub)'
      }
    }, s.grade));
  })), d.insight && /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, d.insight))));
};

;/* ===== js/components/DatalabWeekdaySection.jsx ===== */
/* DatalabWeekdaySection — 요일별 검색 패턴 (v5) */
window.DatalabWeekdaySection = function DatalabWeekdaySection(props) {
  if (!props?.data || !props.data.days || props.data.days.length === 0) return null;
  var d = props.data;
  var days = d.days;
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: 24
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDCC5"), "\uC694\uC77C\uBCC4 \uAC80\uC0C9 \uD328\uD134", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uB370\uC774\uD130\uB7A9")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uCD5C\uADFC 4\uC8FC \uAE30\uC900 \uC694\uC77C\uBCC4 \uAC80\uC0C9 \uD2B8\uB80C\uB4DC"), /*#__PURE__*/React.createElement(ChartCanvas, {
    type: "bar",
    height: 200,
    data: {
      labels: days.map(function (day) {
        return day.label + (day.label === d.peakDay ? ' 🔥' : '');
      }),
      datasets: [{
        label: '검색 지수',
        data: days.map(function (day) {
          return Math.round(day.normalized);
        }),
        backgroundColor: days.map(function (day) {
          return day.label === d.peakDay ? '#ec4899' : day.label === d.lowDay ? '#94a3b8' : day.normalized >= 85 ? '#7c3aed' : '#4f46e5';
        }),
        borderRadius: 6
      }]
    },
    options: {
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              return '지수 ' + ctx.parsed.y;
            }
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true
        }
      }
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'center',
      gap: 24,
      marginTop: 16,
      paddingTop: 12,
      borderTop: '1px solid #f1f5f9'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: '#64748b'
    }
  }, "\uD83D\uDCC8 \uCD5C\uACE0: ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#ec4899'
    }
  }, d.peakDay, "\uC694\uC77C"), " (\uC9C0\uC218 ", Math.round(d.peakIndex), ")"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: '#64748b'
    }
  }, "\uD83D\uDCC9 \uCD5C\uC800: ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#64748b'
    }
  }, d.lowDay, "\uC694\uC77C"), " (\uC9C0\uC218 ", Math.round(d.lowIndex), ")")))));
};

;/* ===== js/components/DatalabGrowthSection.jsx ===== */
/* DatalabGrowthSection — 전년 동기 대비 성장률 (v5) */
window.DatalabGrowthSection = function DatalabGrowthSection(props) {
  if (!props?.data || !props.data.periods || props.data.periods.length === 0) return null;
  var periods = props.data.periods;
  var colors = [{
    main: '#22c55e',
    grad: 'linear-gradient(90deg, #22c55e, #4ade80)',
    bg: '#f0fdf4'
  }, {
    main: '#4f46e5',
    grad: 'linear-gradient(90deg, #4f46e5, #818cf8)',
    bg: '#eef2ff'
  }, {
    main: '#f59e0b',
    grad: 'linear-gradient(90deg, #f59e0b, #fbbf24)',
    bg: '#fffbeb'
  }];

  /* 전체 성장 판단 */
  var avg3m = periods.length > 1 ? periods[1] : periods[0];
  var growthLabel = avg3m.growth > 10 ? '빠른 성장세' : avg3m.growth > 0 ? '완만한 성장세' : avg3m.growth > -10 ? '보합세' : '하락세';
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDE80"), "\uC804\uB144 \uB3D9\uAE30 \uB300\uBE44 \uC131\uC7A5\uB960", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uB370\uC774\uD130\uB7A9")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "\uB370\uC774\uD130\uB7A9 \uC1FC\uD551\uC778\uC0AC\uC774\uD2B8 \uAE30\uBC18 \uC804\uB144 \uB300\uBE44 \uAC80\uC0C9 \uD2B8\uB80C\uB4DC \uBCC0\uD654"), /*#__PURE__*/React.createElement("div", {
    className: "card-grid card-grid-3"
  }, periods.map(function (p, i) {
    var c = colors[i] || colors[0];
    var isRecommended = i === 1;
    var isPositive = p.growth >= 0;
    var barWidth = Math.min(Math.abs(p.growth) + 50, 100);
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      className: "card",
      style: {
        padding: 24,
        textAlign: 'center',
        position: 'relative',
        border: isRecommended ? '2px solid #4f46e5' : undefined
      }
    }, isRecommended && /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        top: -1,
        right: 16,
        background: '#4f46e5',
        color: '#fff',
        fontSize: 10,
        fontWeight: 700,
        padding: '2px 10px',
        borderRadius: '0 0 6px 6px'
      }
    }, "\uCD94\uCC9C \uAE30\uC900"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        color: '#94a3b8',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        marginBottom: 12
      }
    }, "\uC9C1\uC804 ", p.label, " \uB300\uBE44"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 32,
        fontWeight: 800,
        color: isPositive ? c.main : '#ef4444',
        marginBottom: 4
      }
    }, isPositive ? '+' : '', p.growth, "%"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: '#64748b',
        marginBottom: 12
      }
    }, isPositive ? '검색량 증가 추세' : '검색량 감소 추세'), /*#__PURE__*/React.createElement("div", {
      style: {
        height: 6,
        background: '#e2e8f0',
        borderRadius: 3,
        overflow: 'hidden',
        marginBottom: 10
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        height: '100%',
        width: barWidth + '%',
        borderRadius: 3,
        background: isPositive ? c.grad : 'linear-gradient(90deg, #ef4444, #f87171)'
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        fontSize: 11,
        color: '#94a3b8'
      }
    }, /*#__PURE__*/React.createElement("span", null, "\uC804\uB144: ", p.previousAvg), /*#__PURE__*/React.createElement("span", null, "\uC62C\uD574: ", p.currentAvg)));
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16,
      padding: '12px 16px',
      background: '#f0fdf4',
      borderRadius: 10,
      border: '1px solid #a7f3d0',
      fontSize: 12,
      color: '#065f46',
      lineHeight: 1.7
    }
  }, "\uD83D\uDCC8 ", /*#__PURE__*/React.createElement("strong", null, "\uC131\uC7A5 \uBD84\uC11D:"), " \uC804\uB144 \uB300\uBE44 3\uAC1C\uC6D4 \uD3C9\uADE0 \uAE30\uC900 ", avg3m.growth > 0 ? '+' : '', avg3m.growth, "%\uB85C ", /*#__PURE__*/React.createElement("strong", null, growthLabel), "\uC785\uB2C8\uB2E4.", avg3m.growth > 0 && ' 단기(1개월) 성장률이 장기 평균보다 ' + (periods[0].growth > avg3m.growth ? '높아 현재 상승 모멘텀이 강합니다.' : '낮아 안정적 성장 구간입니다.')))));
};

;/* ===== js/components/DatalabCategoryKeywordsSection.jsx ===== */
/* DatalabCategoryKeywordsSection — 카테고리 인기 키워드 TOP (v6) */
window.DatalabCategoryKeywordsSection = function DatalabCategoryKeywordsSection(props) {
  if (!props?.data) return null;
  var popular = props.data.popular || [];
  var rising = props.data.rising || [];
  if (popular.length === 0 && rising.length === 0) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "\uD83D\uDD25"), "\uCE74\uD14C\uACE0\uB9AC \uC778\uAE30 \xB7 \uAE09\uC0C1\uC2B9 \uD0A4\uC6CC\uB4DC", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "\u2705 \uB370\uC774\uD130\uB7A9")), /*#__PURE__*/React.createElement("div", {
    className: "grid2"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "sub-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "st"
  }, "\uD83C\uDFC6 \uC778\uAE30 \uD0A4\uC6CC\uB4DC TOP"), /*#__PURE__*/React.createElement("table", {
    className: "rt-table"
  }, /*#__PURE__*/React.createElement("tbody", null, popular.map(function (kw, i) {
    return /*#__PURE__*/React.createElement("tr", {
      key: i
    }, /*#__PURE__*/React.createElement("td", null, i + 1), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("b", null, kw.keyword)), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right'
      }
    }, i === 0 ? '검색 ' : '', fmt(kw.volume)));
  }))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "sub-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "st"
  }, "\uD83D\uDCC8 \uAE09\uC0C1\uC2B9 \uD0A4\uC6CC\uB4DC"), /*#__PURE__*/React.createElement("table", {
    className: "rt-table"
  }, /*#__PURE__*/React.createElement("tbody", null, rising.map(function (kw, i) {
    var isPositive = kw.growth >= 0;
    var growthAbs = Math.abs(kw.growth);
    var psClass = isPositive ? 'ps ps-g' : 'ps ps-r';
    var arrow = isPositive ? '▲' : '▼';
    return /*#__PURE__*/React.createElement("tr", {
      key: i
    }, /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("b", null, kw.keyword)), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right'
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: psClass
    }, arrow, " ", isPositive ? '+' : '', kw.growth, "%")));
  })))))), /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, props.data.note || '급상승 키워드를 상품명 · 태그에 반영하면 시즌 트렌드 수혜를 빠르게 받을 수 있습니다.'))));
};

;/* ===== js/components/FeedbackManagement.jsx ===== */
/* FeedbackManagement — 피드백 관리 (manager/superadmin용) v1.1 (리팩토링) */

// 상수를 컴포넌트 외부로 추출 (매 렌더링마다 재생성 방지)
var _fbCategoryLabels = {
  error: '오류 신고',
  request: '기능 요청',
  opinion: '의견/건의',
  general: '일반'
};
var _fbCategoryColors = {
  error: {
    bg: '#fee2e2',
    color: '#dc2626'
  },
  request: {
    bg: '#dbeafe',
    color: '#2563eb'
  },
  opinion: {
    bg: '#ede9fe',
    color: '#7c3aed'
  },
  general: {
    bg: '#f1f5f9',
    color: '#64748b'
  }
};
var _fbStatusLabels = {
  pending: '대기',
  resolved: '처리완료',
  in_progress: '처리중'
};
var _fbStatusColors = {
  pending: {
    bg: '#fef9c3',
    color: '#ca8a04'
  },
  resolved: {
    bg: '#dcfce7',
    color: '#16a34a'
  },
  in_progress: {
    bg: '#dbeafe',
    color: '#2563eb'
  }
};
var _fbFilterOptions = ['all', 'pending', 'resolved'];
window.FeedbackManagement = function FeedbackManagement() {
  const {
    useState,
    useEffect,
    useCallback
  } = React;
  const [feedbacks, setFeedbacks] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('all');
  const [replyingId, setReplyingId] = useState(null);
  const [replyText, setReplyText] = useState('');
  var loadFeedbacks = useCallback(function () {
    setLoading(true);
    var url = filter === 'all' ? '/chat/feedback' : '/chat/feedback?status=' + filter;
    api.get(url).then(function (res) {
      if (res.success) setFeedbacks(res.data || []);
      setLoading(false);
    }).catch(function () {
      setLoading(false);
    });
  }, [filter]);
  var loadStats = useCallback(function () {
    api.get('/chat/feedback/stats').then(function (res) {
      if (res.success) setStats(res.data);
    }).catch(function () {});
  }, []);
  useEffect(function () {
    loadFeedbacks();
    loadStats();
  }, [loadFeedbacks, loadStats]);
  var updateFeedback = useCallback(function (id, status, reply) {
    var body = {};
    if (status) body.status = status;
    if (reply !== undefined) body.admin_reply = reply;
    api.put('/chat/feedback/' + id, body).then(function (res) {
      if (res.success) {
        toast.success('피드백이 업데이트되었습니다.');
        loadFeedbacks();
        loadStats();
        setReplyingId(null);
        setReplyText('');
      }
    }).catch(function () {});
  }, [loadFeedbacks, loadStats]);
  var categoryLabels = _fbCategoryLabels;
  var categoryColors = _fbCategoryColors;
  var statusLabels = _fbStatusLabels;
  var statusColors = _fbStatusColors;
  return React.createElement('div', {
    className: 'card',
    style: {
      padding: 20,
      marginBottom: 20
    }
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 700,
      marginBottom: 16,
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, '💬 피드백 관리', stats && React.createElement('span', {
    style: {
      fontSize: 12,
      padding: '2px 8px',
      borderRadius: 10,
      background: '#fee2e2',
      color: '#dc2626',
      fontWeight: 600
    }
  }, '대기 ' + stats.pending + '건')), /* 통계 요약 */
  stats && React.createElement('div', {
    style: {
      display: 'flex',
      gap: 12,
      flexWrap: 'wrap',
      marginBottom: 16
    }
  }, React.createElement('div', {
    style: {
      flex: 1,
      minWidth: 100,
      background: '#f8fafc',
      borderRadius: 10,
      padding: 12,
      textAlign: 'center'
    }
  }, React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#64748b'
    }
  }, '전체'), React.createElement('div', {
    style: {
      fontSize: 20,
      fontWeight: 700
    }
  }, stats.total)), React.createElement('div', {
    style: {
      flex: 1,
      minWidth: 100,
      background: '#fef9c3',
      borderRadius: 10,
      padding: 12,
      textAlign: 'center'
    }
  }, React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#ca8a04'
    }
  }, '대기'), React.createElement('div', {
    style: {
      fontSize: 20,
      fontWeight: 700,
      color: '#ca8a04'
    }
  }, stats.pending)), React.createElement('div', {
    style: {
      flex: 1,
      minWidth: 100,
      background: '#dcfce7',
      borderRadius: 10,
      padding: 12,
      textAlign: 'center'
    }
  }, React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#16a34a'
    }
  }, '완료'), React.createElement('div', {
    style: {
      fontSize: 20,
      fontWeight: 700,
      color: '#16a34a'
    }
  }, stats.resolved)), stats.byCategory && Object.keys(stats.byCategory).map(function (cat) {
    var cc = categoryColors[cat] || categoryColors.general;
    return React.createElement('div', {
      key: cat,
      style: {
        flex: 1,
        minWidth: 100,
        background: cc.bg,
        borderRadius: 10,
        padding: 12,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: cc.color
      }
    }, categoryLabels[cat] || cat), React.createElement('div', {
      style: {
        fontSize: 20,
        fontWeight: 700,
        color: cc.color
      }
    }, stats.byCategory[cat]));
  })), /* 필터 */
  React.createElement('div', {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 16
    }
  }, _fbFilterOptions.map(function (f) {
    var label = f === 'all' ? '전체' : statusLabels[f] || f;
    return React.createElement('button', {
      key: f,
      onClick: function () {
        setFilter(f);
      },
      style: {
        padding: '6px 14px',
        borderRadius: 8,
        fontSize: 12,
        fontWeight: 600,
        cursor: 'pointer',
        background: filter === f ? '#1B2A4A' : '#f1f5f9',
        color: filter === f ? '#fff' : '#64748b',
        border: 'none'
      }
    }, label);
  })), /* 피드백 리스트 */
  loading && React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: 20,
      color: '#94a3b8'
    }
  }, '로딩 중...'), !loading && feedbacks.length === 0 && React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: 30,
      color: '#94a3b8',
      fontSize: 13
    }
  }, '아직 접수된 피드백이 없습니다.'), !loading && feedbacks.map(function (fb) {
    var cc = categoryColors[fb.category] || categoryColors.general;
    var sc = statusColors[fb.status] || statusColors.pending;
    return React.createElement('div', {
      key: fb.id,
      style: {
        padding: '14px 16px',
        marginBottom: 8,
        borderRadius: 10,
        border: '1px solid #e2e8f0',
        background: '#fff'
      }
    }, /* 상단: 카테고리/상태/날짜 */
    React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 8
      }
    }, React.createElement('span', {
      style: {
        padding: '2px 8px',
        borderRadius: 8,
        fontSize: 11,
        fontWeight: 600,
        background: cc.bg,
        color: cc.color
      }
    }, categoryLabels[fb.category] || fb.category), React.createElement('span', {
      style: {
        padding: '2px 8px',
        borderRadius: 8,
        fontSize: 11,
        fontWeight: 600,
        background: sc.bg,
        color: sc.color
      }
    }, statusLabels[fb.status] || fb.status), React.createElement('span', {
      style: {
        fontSize: 12,
        color: '#94a3b8'
      }
    }, fb.username), React.createElement('div', {
      style: {
        flex: 1
      }
    }), React.createElement('span', {
      style: {
        fontSize: 11,
        color: '#94a3b8'
      }
    }, (fb.created_at || '').slice(0, 16))), /* 내용 */
    React.createElement('div', {
      style: {
        fontSize: 13,
        color: '#1e293b',
        lineHeight: 1.6,
        marginBottom: 8
      }
    }, fb.content), /* 관리자 답변 */
    fb.admin_reply && React.createElement('div', {
      style: {
        padding: 10,
        background: '#f0fdf4',
        borderRadius: 8,
        fontSize: 12,
        color: '#166534',
        marginBottom: 8
      }
    }, '💬 관리자 답변: ' + fb.admin_reply), /* 액션 버튼 */
    React.createElement('div', {
      style: {
        display: 'flex',
        gap: 8
      }
    }, fb.status !== 'resolved' && React.createElement('button', {
      onClick: function () {
        updateFeedback(fb.id, 'resolved');
      },
      style: {
        padding: '4px 10px',
        borderRadius: 6,
        fontSize: 11,
        cursor: 'pointer',
        background: '#dcfce7',
        color: '#16a34a',
        border: '1px solid #bbf7d0',
        fontWeight: 600
      }
    }, '✓ 처리완료'), React.createElement('button', {
      onClick: function () {
        setReplyingId(replyingId === fb.id ? null : fb.id);
        setReplyText(fb.admin_reply || '');
      },
      style: {
        padding: '4px 10px',
        borderRadius: 6,
        fontSize: 11,
        cursor: 'pointer',
        background: '#dbeafe',
        color: '#2563eb',
        border: '1px solid #bfdbfe',
        fontWeight: 600
      }
    }, '💬 답변')), /* 답변 입력 */
    replyingId === fb.id && React.createElement('div', {
      style: {
        marginTop: 8,
        display: 'flex',
        gap: 8
      }
    }, React.createElement('input', {
      value: replyText,
      onChange: function (e) {
        setReplyText(e.target.value);
      },
      placeholder: '답변을 입력하세요...',
      style: {
        flex: 1,
        padding: '6px 10px',
        borderRadius: 6,
        border: '1px solid #e2e8f0',
        fontSize: 12,
        outline: 'none'
      }
    }), React.createElement('button', {
      onClick: function () {
        updateFeedback(fb.id, null, replyText);
      },
      style: {
        padding: '6px 12px',
        borderRadius: 6,
        fontSize: 11,
        cursor: 'pointer',
        background: '#1B2A4A',
        color: '#fff',
        border: 'none',
        fontWeight: 600
      }
    }, '저장')));
  }));
};

;/* ===== js/components/ClientDiagnosticsSection.jsx ===== */
/* ClientDiagnosticsSection — 업체 데이터 점검 (admin/superadmin 전용, 조회 전용) v1.0
 * '진행중(active) 업체 일부 사라짐' 원인 파악용 패널.
 *  - 상태별 업체 수
 *  - 등록자(created_by) 없는 active 업체 (manager에게 안 보여 사라짐처럼 보일 수 있음)
 *  - 최근 paused/terminated로 바뀐 업체 (의도치 않은 상태 변경 의심)
 */
var _cdStatusLabels = {
  active: '진행중(active)',
  paused: '일시중지(paused)',
  terminated: '종료(terminated)'
};
var _cdStatusColors = {
  active: {
    bg: '#dcfce7',
    color: '#16a34a'
  },
  paused: {
    bg: '#fef9c3',
    color: '#ca8a04'
  },
  terminated: {
    bg: '#fee2e2',
    color: '#dc2626'
  }
};
window.ClientDiagnosticsSection = function ClientDiagnosticsSection() {
  const {
    useState,
    useEffect,
    useCallback
  } = React;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  var load = useCallback(function () {
    setLoading(true);
    api.get('/clients/diagnostics').then(function (res) {
      if (res.success) setData(res.data);
      setLoading(false);
    }).catch(function () {
      setLoading(false);
    });
  }, []);
  useEffect(function () {
    load();
  }, [load]);
  var renderTable = function (rows, cols) {
    return React.createElement('div', {
      style: {
        overflowX: 'auto'
      }
    }, React.createElement('table', {
      style: {
        width: '100%',
        borderCollapse: 'collapse',
        fontSize: 12
      }
    }, React.createElement('thead', null, React.createElement('tr', null, cols.map(function (c) {
      return React.createElement('th', {
        key: c.key,
        style: {
          textAlign: 'left',
          padding: '6px 8px',
          borderBottom: '1px solid #e2e8f0',
          color: '#64748b',
          fontWeight: 600,
          whiteSpace: 'nowrap'
        }
      }, c.label);
    }))), React.createElement('tbody', null, rows.map(function (row, i) {
      return React.createElement('tr', {
        key: i
      }, cols.map(function (c) {
        return React.createElement('td', {
          key: c.key,
          style: {
            padding: '6px 8px',
            borderBottom: '1px solid #f1f5f9',
            color: '#1e293b',
            whiteSpace: 'nowrap'
          }
        }, c.render ? c.render(row[c.key], row) : row[c.key] == null ? '-' : String(row[c.key]));
      }));
    }))));
  };
  var byStatus = data && data.byStatus || {};
  var recentInactive = data && data.recentInactive || [];
  return React.createElement('div', {
    className: 'card',
    style: {
      padding: 20,
      marginBottom: 20
    }
  }, React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginBottom: 16
    }
  }, React.createElement('div', {
    style: {
      fontSize: 18,
      fontWeight: 700
    }
  }, '🔎 업체 데이터 점검'), React.createElement('div', {
    style: {
      flex: 1
    }
  }), React.createElement('button', {
    onClick: load,
    style: {
      padding: '6px 14px',
      borderRadius: 8,
      fontSize: 12,
      fontWeight: 600,
      cursor: 'pointer',
      background: '#f1f5f9',
      color: '#334155',
      border: '1px solid #e2e8f0'
    }
  }, '↻ 새로고침')), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginBottom: 16,
      lineHeight: 1.6
    }
  }, "업체 데이터 점검용입니다. 상태별 업체 수와 최근 일시중지/종료된 업체를 확인할 수 있습니다."), loading && React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: 20,
      color: '#94a3b8'
    }
  }, '불러오는 중...'), !loading && data && React.createElement(React.Fragment, null, /* 서버 디스크 사용량 */
  data.disk && function () {
    var dk = data.disk;
    var pct = dk.usedPercent || 0;
    var color = pct >= 90 ? {
      bg: '#fee2e2',
      bar: '#dc2626',
      text: '#dc2626'
    } : pct >= 75 ? {
      bg: '#fef9c3',
      bar: '#ca8a04',
      text: '#ca8a04'
    } : {
      bg: '#dcfce7',
      bar: '#16a34a',
      text: '#16a34a'
    };
    return React.createElement('div', {
      style: {
        marginBottom: 20
      }
    }, React.createElement('div', {
      style: {
        fontSize: 13,
        fontWeight: 700,
        color: '#334155',
        margin: '4px 0 8px',
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, '💾 서버 디스크 사용량', React.createElement('span', {
      style: {
        fontSize: 12,
        fontWeight: 700,
        color: color.text
      }
    }, pct + '%'), pct >= 90 && React.createElement('span', {
      style: {
        fontSize: 11,
        color: '#dc2626',
        fontWeight: 600
      }
    }, '⚠️ 정리 필요')), /* 사용률 막대 */
    React.createElement('div', {
      style: {
        height: 14,
        borderRadius: 7,
        background: '#e2e8f0',
        overflow: 'hidden',
        marginBottom: 8
      }
    }, React.createElement('div', {
      style: {
        width: Math.min(pct, 100) + '%',
        height: '100%',
        background: color.bar,
        transition: 'width 0.3s'
      }
    })), React.createElement('div', {
      style: {
        display: 'flex',
        gap: 12,
        flexWrap: 'wrap',
        fontSize: 12,
        color: '#475569'
      }
    }, React.createElement('span', null, '전체 ' + dk.totalGB + 'GB'), React.createElement('span', null, '사용 ' + dk.usedGB + 'GB'), React.createElement('span', {
      style: {
        fontWeight: 600
      }
    }, '여유 ' + dk.freeGB + 'GB'), React.createElement('span', {
      style: {
        color: '#94a3b8'
      }
    }, '| DB ' + dk.dbSizeGB + 'GB · 백업 ' + dk.backupCount + '개(' + dk.backupTotalGB + 'GB)')));
  }(), /* 상태별 업체 수 */
  React.createElement('div', {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#334155',
      margin: '4px 0 8px'
    }
  }, '상태별 업체 수'), React.createElement('div', {
    style: {
      display: 'flex',
      gap: 12,
      flexWrap: 'wrap',
      marginBottom: 20
    }
  }, ['active', 'paused', 'terminated'].map(function (st) {
    var cc = _cdStatusColors[st];
    return React.createElement('div', {
      key: st,
      style: {
        flex: 1,
        minWidth: 120,
        background: cc.bg,
        borderRadius: 10,
        padding: 12,
        textAlign: 'center'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        color: cc.color
      }
    }, _cdStatusLabels[st]), React.createElement('div', {
      style: {
        fontSize: 22,
        fontWeight: 700,
        color: cc.color
      }
    }, byStatus[st] || 0));
  })), /* (등록자 없는 진행중 업체 항목 제거 — clients.created_by가 NOT NULL이라 항상 0건이라 무의미) */

  /* 최근 paused/terminated */
  React.createElement('div', {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#334155',
      margin: '4px 0 8px'
    }
  }, '최근 일시중지/종료된 업체 (최대 30건)'), recentInactive.length === 0 ? React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#94a3b8'
    }
  }, '없음.') : renderTable(recentInactive, [{
    key: 'id',
    label: 'ID'
  }, {
    key: 'name',
    label: '업체명'
  }, {
    key: 'status',
    label: '상태',
    render: function (v) {
      return _cdStatusLabels[v] || v;
    }
  }, {
    key: 'updated_at',
    label: '변경일',
    render: function (v) {
      return (v || '').slice(0, 16);
    }
  }])));
};

;/* ===== js/components/AnalysisStatsSection.jsx ===== */
/* AnalysisStatsSection — 로직 분석 실행 건수 통계 (설정 탭, 최고관리자 전용) v1.0
 *  - 요약 카드: 총 실행 / 이번 달 / 오늘
 *  - 직원별 표: 이름·역할 + 오늘/이번 달/누적 실행 건수
 *  데이터: daily_usage.query_count (분석 실행마다 +1, 모든 역할 카운트)
 */
var _asRoleLabels = {
  superadmin: '최고관리자',
  admin: '관리자',
  manager: '매니저',
  viewer: '뷰어'
};
var _asRoleColors = {
  superadmin: {
    bg: '#ede9fe',
    color: '#6d28d9'
  },
  admin: {
    bg: '#dbeafe',
    color: '#2563eb'
  },
  manager: {
    bg: '#dcfce7',
    color: '#16a34a'
  },
  viewer: {
    bg: '#f1f5f9',
    color: '#64748b'
  }
};
window.AnalysisStatsSection = function AnalysisStatsSection() {
  const {
    useState,
    useEffect,
    useCallback
  } = React;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [openId, setOpenId] = useState(null); // 로그인 이력 펼친 직원
  const [logs, setLogs] = useState({}); // { userId: [ {login_at, ip_address} ] }
  const [logLoading, setLogLoading] = useState(false);
  var toggleLogs = function (uid) {
    if (openId === uid) {
      setOpenId(null);
      return;
    }
    setOpenId(uid);
    if (!logs[uid]) {
      setLogLoading(true);
      api.get('/auth/users/' + uid + '/login-logs?limit=10').then(function (res) {
        setLogs(function (prev) {
          var n = Object.assign({}, prev);
          n[uid] = res && res.success ? res.data || [] : [];
          return n;
        });
        setLogLoading(false);
      }).catch(function () {
        setLogLoading(false);
      });
    }
  };
  var load = useCallback(function () {
    setLoading(true);
    api.get('/auth/analysis-stats').then(function (res) {
      if (res && res.success) setData(res);
      setLoading(false);
    }).catch(function () {
      setLoading(false);
    });
  }, []);
  useEffect(function () {
    load();
  }, [load]);
  var card = function (label, value, color, bg) {
    return React.createElement('div', {
      key: label,
      style: {
        flex: 1,
        minWidth: 140,
        padding: '16px 18px',
        background: bg,
        borderRadius: 12,
        border: '1px solid ' + color + '22'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 28,
        fontWeight: 800,
        color: color,
        lineHeight: 1.1
      }
    }, fmt(value)), React.createElement('div', {
      style: {
        fontSize: 12,
        color: '#64748b',
        marginTop: 4,
        fontWeight: 600
      }
    }, label));
  };
  var th = function (label, align) {
    return React.createElement('th', {
      key: label,
      style: {
        textAlign: align || 'left',
        padding: '10px 12px',
        borderBottom: '2px solid rgba(255,255,255,0.25)',
        color: '#ffffff',
        fontWeight: 700,
        whiteSpace: 'nowrap',
        fontSize: 12.5,
        letterSpacing: '0.01em'
      }
    }, label);
  };
  var numCell = function (v, strong) {
    return React.createElement('td', {
      style: {
        textAlign: 'right',
        padding: '8px 10px',
        borderBottom: '1px solid #f1f5f9',
        fontWeight: strong ? 700 : 500,
        color: v > 0 ? '#0f172a' : '#cbd5e1',
        fontVariantNumeric: 'tabular-nums'
      }
    }, fmt(v) + '건');
  };
  var renderLogs = function (uid) {
    var list = logs[uid];
    if (!list) {
      return React.createElement('div', {
        style: {
          fontSize: 12,
          color: '#94a3b8',
          padding: '6px 0'
        }
      }, logLoading ? '로그인 이력 불러오는 중…' : '불러오는 중…');
    }
    if (list.length === 0) {
      return React.createElement('div', {
        style: {
          fontSize: 12,
          color: '#94a3b8',
          padding: '6px 0'
        }
      }, '로그인 이력이 없습니다.');
    }
    return React.createElement('div', null, React.createElement('div', {
      style: {
        fontSize: 11,
        fontWeight: 700,
        color: '#64748b',
        marginBottom: 6
      }
    }, '🕑 최근 로그인 이력 (최대 10개)'), React.createElement('div', {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 3
      }
    }, list.map(function (lg, i) {
      return React.createElement('div', {
        key: lg.id || i,
        style: {
          display: 'flex',
          gap: 12,
          fontSize: 12,
          color: '#475569',
          fontVariantNumeric: 'tabular-nums'
        }
      }, React.createElement('span', {
        style: {
          color: '#94a3b8',
          width: 14,
          textAlign: 'right'
        }
      }, i + 1), React.createElement('span', {
        style: {
          fontWeight: 600,
          color: '#0f172a'
        }
      }, lg.login_at || '-'), lg.ip_address && React.createElement('span', {
        style: {
          color: '#94a3b8'
        }
      }, 'IP ' + lg.ip_address));
    })));
  };
  return React.createElement('div', {
    style: {
      background: '#fff',
      borderRadius: 16,
      padding: '22px 24px',
      boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      marginBottom: 20
    }
  }, React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: 16
    }
  }, React.createElement('div', null, React.createElement('h3', {
    style: {
      margin: 0,
      fontSize: 16,
      fontWeight: 800,
      color: '#0f172a'
    }
  }, '📊 로직 분석 실행 건수'), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#94a3b8',
      marginTop: 2
    }
  }, '분석 실행마다 집계 (모든 직원 포함)')), React.createElement('button', {
    onClick: load,
    disabled: loading,
    style: {
      border: '1px solid #e2e8f0',
      background: '#f8fafc',
      color: '#475569',
      fontSize: 12,
      fontWeight: 600,
      padding: '6px 12px',
      borderRadius: 8,
      cursor: loading ? 'default' : 'pointer'
    }
  }, loading ? '불러오는 중…' : '↻ 새로고침')), !data && loading && React.createElement('div', {
    style: {
      padding: 24,
      textAlign: 'center',
      color: '#94a3b8',
      fontSize: 13
    }
  }, '불러오는 중…'), !data && !loading && React.createElement('div', {
    style: {
      padding: 24,
      textAlign: 'center',
      color: '#94a3b8',
      fontSize: 13
    }
  }, '데이터를 불러오지 못했습니다.'), data && React.createElement(React.Fragment, null,
  // 요약 카드
  React.createElement('div', {
    style: {
      display: 'flex',
      gap: 12,
      flexWrap: 'wrap',
      marginBottom: 20
    }
  }, card('총 누적 실행', data.total, '#6d28d9', '#f5f3ff'), card('이번 달', data.this_month, '#2563eb', '#eff6ff'), card('오늘', data.today, '#16a34a', '#f0fdf4')),
  // 직원별 표
  React.createElement('div', {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#334155',
      marginBottom: 4
    }
  }, '직원별 실행 건수'), React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      marginBottom: 8
    }
  }, '직원을 클릭하면 최근 로그인 이력(최대 10개)을 볼 수 있어요.'), React.createElement('div', {
    style: {
      overflowX: 'auto'
    }
  }, React.createElement('table', {
    style: {
      width: '100%',
      borderCollapse: 'collapse',
      fontSize: 13
    }
  }, React.createElement('thead', null, React.createElement('tr', null, th('직원'), th('권한'), th('오늘', 'right'), th('이번 달', 'right'), th('누적', 'right'))), React.createElement('tbody', null, (data.per_user || []).map(function (u) {
    var rc = _asRoleColors[u.role] || _asRoleColors.viewer;
    var isOpen = openId === u.user_id;
    var rows = [React.createElement('tr', {
      key: u.user_id,
      onClick: function () {
        toggleLogs(u.user_id);
      },
      style: {
        cursor: 'pointer',
        background: isOpen ? '#f8fafc' : 'transparent'
      }
    }, React.createElement('td', {
      style: {
        padding: '8px 10px',
        borderBottom: '1px solid #f1f5f9',
        fontWeight: 600,
        color: '#0f172a'
      }
    }, React.createElement('span', {
      style: {
        display: 'inline-block',
        width: 14,
        color: '#94a3b8',
        fontSize: 10
      }
    }, isOpen ? '▼' : '▶'), u.name), React.createElement('td', {
      style: {
        padding: '8px 10px',
        borderBottom: '1px solid #f1f5f9'
      }
    }, React.createElement('span', {
      style: {
        fontSize: 11,
        fontWeight: 700,
        padding: '2px 8px',
        borderRadius: 10,
        background: rc.bg,
        color: rc.color
      }
    }, _asRoleLabels[u.role] || u.role)), numCell(u.today), numCell(u.month), numCell(u.total, true))];
    if (isOpen) {
      rows.push(React.createElement('tr', {
        key: u.user_id + '_logs'
      }, React.createElement('td', {
        colSpan: 5,
        style: {
          padding: '4px 10px 12px 24px',
          borderBottom: '1px solid #f1f5f9',
          background: '#f8fafc'
        }
      }, renderLogs(u.user_id))));
    }
    return React.createElement(React.Fragment, {
      key: 'f_' + u.user_id
    }, rows);
  }), (!data.per_user || data.per_user.length === 0) && React.createElement('tr', null, React.createElement('td', {
    colSpan: 5,
    style: {
      padding: 18,
      textAlign: 'center',
      color: '#94a3b8'
    }
  }, '실행 기록이 없습니다.')))))));
};

;/* ===== js/components/ChatWidget.jsx ===== */
/* ChatWidget — 플로팅 AI 채팅 + 의견함 위젯 v2.2 (이미지 첨부 지원) */

// 타임스탬프 헬퍼 (컴포넌트 외부 — 매 렌더링마다 재생성 방지)
var _chatNow = function () {
  return new Date().toISOString().slice(0, 19).replace('T', ' ');
};

// 의견함 카테고리 옵션 (상수)
var _categoryOptions = [{
  value: 'error',
  label: '오류 신고',
  icon: '🚨',
  desc: '버그, 에러, 오작동',
  color: '#dc2626',
  bg: '#fee2e2'
}, {
  value: 'request',
  label: '기능 요청',
  icon: '💡',
  desc: '새 기능, 개선 요청',
  color: '#2563eb',
  bg: '#dbeafe'
}, {
  value: 'opinion',
  label: '의견/건의',
  icon: '💬',
  desc: '사용 후기, 제안',
  color: '#7c3aed',
  bg: '#ede9fe'
}];
var _fbTagMap = {
  error: '#오류',
  request: '#요청',
  opinion: '#의견'
};
window.ChatWidget = function ChatWidget({
  currentUser
}) {
  const {
    useState,
    useEffect,
    useRef,
    useCallback
  } = React;
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'feedback'
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [unread, setUnread] = useState(0);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const fileInputRef = useRef(null);

  // 이미지 첨부 상태
  const [imagePreview, setImagePreview] = useState(null); // 미리보기 data URL
  const [imageB64, setImageB64] = useState(null); // base64 데이터 (서버 전송용)
  const [imageType, setImageType] = useState(null); // MIME 타입

  // 의견함 상태
  const [fbCategory, setFbCategory] = useState('');
  const [fbContent, setFbContent] = useState('');
  const [fbSending, setFbSending] = useState(false);
  const [fbSent, setFbSent] = useState(false);

  // 의견함 이미지 첨부 상태 (채팅 탭과 분리)
  const [fbImagePreview, setFbImagePreview] = useState(null); // 미리보기 data URL
  const [fbImageB64, setFbImageB64] = useState(null); // base64 데이터 (서버 전송용)
  const [fbImageType, setFbImageType] = useState(null); // MIME 타입
  const fbFileInputRef = useRef(null);

  // 내 피드백 이력
  const [myFeedback, setMyFeedback] = useState([]);
  const [fbHistoryLoaded, setFbHistoryLoaded] = useState(false);

  // isOpen을 ref로도 추적 (useCallback 내부에서 최신값 참조)
  const isOpenRef = useRef(isOpen);
  useEffect(function () {
    isOpenRef.current = isOpen;
  }, [isOpen]);

  // 채팅 이력 로드
  var loadHistory = useCallback(function () {
    api.get('/chat/history').then(function (res) {
      if (res.success && res.data) {
        setMessages(res.data);
      }
    }).catch(function () {});
  }, []);

  // 내 피드백 이력 로드
  var loadMyFeedback = useCallback(function () {
    api.get('/chat/my-feedback').then(function (res) {
      if (res.success && res.data) {
        setMyFeedback(res.data);
        setFbHistoryLoaded(true);
      }
    }).catch(function () {});
  }, []);
  useEffect(function () {
    if (currentUser) loadHistory();
  }, [currentUser, loadHistory]);

  // 의견함 탭 열 때 피드백 이력 로드
  useEffect(function () {
    if (isOpen && activeTab === 'feedback' && currentUser) loadMyFeedback();
  }, [isOpen, activeTab, currentUser, loadMyFeedback]);

  // 채팅 열 때 스크롤
  useEffect(function () {
    if (isOpen && activeTab === 'chat' && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({
        behavior: 'smooth'
      });
    }
    if (isOpen && activeTab === 'chat') {
      setUnread(0);
      if (inputRef.current) inputRef.current.focus();
    }
  }, [isOpen, messages.length, activeTab]);

  // 이미지 파일 선택 핸들러
  var handleImageSelect = useCallback(function (e) {
    var file = e.target.files && e.target.files[0];
    if (!file) return;

    // 타입 검증
    var allowed = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
    if (allowed.indexOf(file.type) < 0) {
      toast.error('PNG, JPG, GIF, WebP 이미지만 첨부 가능합니다.');
      e.target.value = '';
      return;
    }
    // 크기 검증 (5MB)
    if (file.size > 5 * 1024 * 1024) {
      toast.error('이미지 크기는 5MB 이하만 가능합니다.');
      e.target.value = '';
      return;
    }
    var reader = new FileReader();
    reader.onload = function (ev) {
      setImagePreview(ev.target.result);
      // data:image/png;base64,xxxxx → base64 부분만 추출
      var b64 = ev.target.result.split(',')[1];
      setImageB64(b64);
      setImageType(file.type);
    };
    reader.readAsDataURL(file);
    e.target.value = ''; // 같은 파일 재선택 허용
  }, []);
  var clearImage = useCallback(function () {
    setImagePreview(null);
    setImageB64(null);
    setImageType(null);
  }, []);

  // 의견함 이미지 선택 핸들러
  var handleFbImageSelect = useCallback(function (e) {
    var file = e.target.files && e.target.files[0];
    if (!file) return;

    // 타입 검증
    var allowed = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
    if (allowed.indexOf(file.type) < 0) {
      toast.error('PNG, JPG, GIF, WebP 이미지만 첨부 가능합니다.');
      e.target.value = '';
      return;
    }
    // 크기 검증 (5MB)
    if (file.size > 5 * 1024 * 1024) {
      toast.error('이미지 크기는 5MB 이하만 가능합니다.');
      e.target.value = '';
      return;
    }
    var reader = new FileReader();
    reader.onload = function (ev) {
      setFbImagePreview(ev.target.result);
      var b64 = ev.target.result.split(',')[1];
      setFbImageB64(b64);
      setFbImageType(file.type);
    };
    reader.readAsDataURL(file);
    e.target.value = ''; // 같은 파일 재선택 허용
  }, []);
  var clearFbImage = useCallback(function () {
    setFbImagePreview(null);
    setFbImageB64(null);
    setFbImageType(null);
  }, []);

  // 메시지 전송 (useCallback으로 안정적 참조)
  var sendMessage = useCallback(function () {
    var msg = input.trim();
    if (!msg && !imageB64 || sending) return;
    setSending(true);
    setInput('');
    var userMsg = {
      role: 'user',
      content: msg || '(이미지)',
      created_at: _chatNow(),
      image_url: imagePreview
    };
    setMessages(function (prev) {
      return prev.concat([userMsg]);
    });
    var payload = {
      message: msg || '이 이미지를 분석해주세요.'
    };
    if (imageB64) {
      payload.image = imageB64;
      payload.image_type = imageType;
    }
    clearImage();
    api.post('/chat/send', payload).then(function (res) {
      var aiMsg = {
        role: 'assistant',
        content: res.success ? res.response : res.detail || '오류가 발생했습니다.',
        created_at: _chatNow()
      };
      setMessages(function (prev) {
        return prev.concat([aiMsg]);
      });
      if (!isOpenRef.current) setUnread(function (n) {
        return n + 1;
      });
      setSending(false);
    }).catch(function () {
      setMessages(function (prev) {
        return prev.concat([{
          role: 'assistant',
          content: '네트워크 오류가 발생했습니다.',
          created_at: _chatNow()
        }]);
      });
      setSending(false);
    });
  }, [input, sending, imageB64, imageType, imagePreview, clearImage]);
  var handleKeyDown = useCallback(function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }, [sendMessage]);

  // 의견함 전송
  var sendFeedback = useCallback(function () {
    if (!fbCategory || !fbContent.trim() || fbSending) return;
    setFbSending(true);
    var msgWithTag = (_fbTagMap[fbCategory] || '') + ' ' + fbContent.trim();
    var payload = {
      message: msgWithTag
    };
    if (fbImageB64) {
      payload.image = fbImageB64;
      payload.image_type = fbImageType;
    }
    api.post('/chat/send', payload).then(function (res) {
      setFbSending(false);
      setFbSent(true);
      setFbContent('');
      setFbCategory('');
      clearFbImage();
      loadMyFeedback(); // 이력 새로고침
      setTimeout(function () {
        setFbSent(false);
      }, 3000);
    }).catch(function () {
      setFbSending(false);
      toast.error('전송에 실패했습니다.');
    });
  }, [fbCategory, fbContent, fbSending, fbImageB64, fbImageType, clearFbImage]);

  // 마크다운 간이 렌더링 (XSS 방지: 먼저 HTML 이스케이프 후 제한된 마크다운만 허용)
  var renderContent = function (text) {
    if (!text) return '';
    var html = String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/`(.*?)`/g, '<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px;font-size:12px">$1</code>').replace(/\n/g, '<br/>');
    return {
      __html: html
    };
  };
  if (!currentUser) return null;
  var categoryOptions = _categoryOptions;
  return React.createElement('div', null, /* 플로팅 버튼 — 회사 로고 */
  React.createElement('button', {
    onClick: function () {
      setIsOpen(!isOpen);
    },
    style: {
      position: 'fixed',
      bottom: 24,
      right: 24,
      zIndex: 10000,
      width: 56,
      height: 56,
      borderRadius: '50%',
      background: isOpen ? '#64748b' : '#1B2A4A',
      color: '#fff',
      border: 'none',
      cursor: 'pointer',
      boxShadow: '0 4px 20px rgba(27,42,74,0.4)',
      fontSize: 24,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      transition: 'all 0.2s ease',
      transform: isOpen ? 'scale(0.9)' : 'scale(1)',
      overflow: 'hidden',
      padding: 0
    },
    onMouseOver: function (e) {
      e.currentTarget.style.transform = 'scale(1.1)';
    },
    onMouseOut: function (e) {
      e.currentTarget.style.transform = isOpen ? 'scale(0.9)' : 'scale(1)';
    }
  }, isOpen ? '✕' : React.createElement('img', {
    src: 'img/logo_light.png',
    alt: 'METAINC',
    style: {
      width: 32,
      height: 32,
      objectFit: 'contain'
    }
  }), /* 읽지 않은 메시지 뱃지 */
  !isOpen && unread > 0 && React.createElement('span', {
    style: {
      position: 'absolute',
      top: -4,
      right: -4,
      width: 20,
      height: 20,
      borderRadius: '50%',
      background: '#ef4444',
      color: '#fff',
      fontSize: 11,
      fontWeight: 700,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, unread)), /* 메인 패널 */
  isOpen && React.createElement('div', {
    style: {
      position: 'fixed',
      bottom: 90,
      right: 24,
      zIndex: 10000,
      width: 380,
      height: 540,
      borderRadius: 16,
      background: '#fff',
      boxShadow: '0 8px 40px rgba(0,0,0,0.18)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      border: '1px solid #e2e8f0'
    }
  }, /* 헤더 */
  React.createElement('div', {
    style: {
      padding: '12px 18px',
      background: '#1B2A4A',
      color: '#fff',
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, React.createElement('img', {
    src: 'img/logo_light.png',
    alt: 'METAINC',
    style: {
      width: 28,
      height: 28,
      objectFit: 'contain'
    }
  }), React.createElement('div', null, React.createElement('div', {
    style: {
      fontSize: 13,
      fontWeight: 700
    }
  }, 'METAINC 로직 분석 AI'), React.createElement('div', {
    style: {
      fontSize: 10,
      opacity: 0.7
    }
  }, '질문 & 의견함')), React.createElement('div', {
    style: {
      flex: 1
    }
  }), React.createElement('button', {
    onClick: function () {
      setIsOpen(false);
    },
    style: {
      background: 'none',
      border: 'none',
      color: '#fff',
      fontSize: 18,
      cursor: 'pointer',
      opacity: 0.8
    }
  }, '✕')), /* 탭 바 */
  React.createElement('div', {
    style: {
      display: 'flex',
      borderBottom: '1px solid #e2e8f0',
      background: '#f8fafc'
    }
  }, React.createElement('button', {
    onClick: function () {
      setActiveTab('chat');
    },
    style: {
      flex: 1,
      padding: '10px 0',
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      background: 'none',
      border: 'none',
      color: activeTab === 'chat' ? '#1B2A4A' : '#94a3b8',
      borderBottom: activeTab === 'chat' ? '2px solid #1B2A4A' : '2px solid transparent'
    }
  }, '💬 AI 채팅'), React.createElement('button', {
    onClick: function () {
      setActiveTab('feedback');
    },
    style: {
      flex: 1,
      padding: '10px 0',
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      background: 'none',
      border: 'none',
      color: activeTab === 'feedback' ? '#1B2A4A' : '#94a3b8',
      borderBottom: activeTab === 'feedback' ? '2px solid #1B2A4A' : '2px solid transparent'
    }
  }, '📝 의견함')), /* ===== AI 채팅 탭 ===== */
  activeTab === 'chat' && React.createElement(React.Fragment, null, /* 메시지 영역 */
  React.createElement('div', {
    style: {
      flex: 1,
      overflowY: 'auto',
      padding: 14,
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, messages.length === 0 && React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: '40px 20px',
      color: '#94a3b8'
    }
  }, React.createElement('img', {
    src: 'img/logo_dark.png',
    alt: 'METAINC',
    style: {
      width: 48,
      height: 48,
      objectFit: 'contain',
      marginBottom: 12,
      opacity: 0.6
    }
  }), React.createElement('div', {
    style: {
      fontSize: 14,
      fontWeight: 600,
      marginBottom: 8,
      color: '#475569'
    }
  }, 'METAINC 로직 분석 AI'), React.createElement('div', {
    style: {
      fontSize: 12,
      lineHeight: 1.6
    }
  }, '로직 분석 프로그램 사용법이 궁금하신가요?', React.createElement('br'), '무엇이든 질문해 주세요!')), messages.map(function (m, i) {
    var isUser = m.role === 'user';
    return React.createElement('div', {
      key: i,
      style: {
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start'
      }
    }, React.createElement('div', {
      style: {
        maxWidth: '80%',
        padding: '10px 14px',
        borderRadius: 12,
        background: isUser ? '#1B2A4A' : '#f1f5f9',
        color: isUser ? '#fff' : '#1e293b',
        fontSize: 13,
        lineHeight: 1.6,
        borderBottomRightRadius: isUser ? 4 : 12,
        borderBottomLeftRadius: isUser ? 12 : 4
      }
    }, /* 이미지 표시 */
    m.image_url && React.createElement('img', {
      src: m.image_url,
      alt: '첨부 이미지',
      style: {
        maxWidth: '100%',
        maxHeight: 200,
        borderRadius: 8,
        marginBottom: m.content && m.content !== '(이미지)' ? 8 : 0,
        cursor: 'pointer',
        display: 'block'
      },
      onClick: function () {
        window.open(m.image_url, '_blank');
      }
    }), /* 텍스트 (이미지만 보낸 경우 '(이미지)' 표시 제외) */
    m.content && m.content !== '(이미지)' && React.createElement('div', {
      dangerouslySetInnerHTML: renderContent(m.content)
    }), React.createElement('div', {
      style: {
        fontSize: 10,
        marginTop: 4,
        opacity: 0.5,
        textAlign: isUser ? 'right' : 'left'
      }
    }, (m.created_at || '').slice(11, 16))));
  }), sending && React.createElement('div', {
    style: {
      display: 'flex',
      justifyContent: 'flex-start'
    }
  }, React.createElement('div', {
    style: {
      padding: '10px 14px',
      borderRadius: 12,
      background: '#f1f5f9',
      fontSize: 13,
      color: '#94a3b8',
      borderBottomLeftRadius: 4
    }
  }, '✨ AI가 답변을 작성 중입니다...')), React.createElement('div', {
    ref: messagesEndRef
  })), /* 이미지 미리보기 */
  imagePreview && React.createElement('div', {
    style: {
      padding: '8px 14px',
      borderTop: '1px solid #e2e8f0',
      background: '#f8fafc',
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, React.createElement('img', {
    src: imagePreview,
    alt: '미리보기',
    style: {
      width: 48,
      height: 48,
      objectFit: 'cover',
      borderRadius: 8,
      border: '1px solid #e2e8f0'
    }
  }), React.createElement('span', {
    style: {
      fontSize: 12,
      color: '#64748b',
      flex: 1
    }
  }, '이미지 첨부됨'), React.createElement('button', {
    onClick: clearImage,
    style: {
      background: '#fee2e2',
      color: '#dc2626',
      border: 'none',
      borderRadius: 6,
      padding: '4px 8px',
      fontSize: 11,
      cursor: 'pointer',
      fontWeight: 600
    }
  }, '삭제')), /* 입력 영역 */
  React.createElement('div', {
    style: {
      padding: '10px 14px',
      borderTop: imagePreview ? 'none' : '1px solid #e2e8f0',
      background: '#fff',
      display: 'flex',
      gap: 8,
      alignItems: 'flex-end'
    }
  }, /* 숨겨진 파일 입력 */
  React.createElement('input', {
    ref: fileInputRef,
    type: 'file',
    accept: 'image/png,image/jpeg,image/gif,image/webp',
    style: {
      display: 'none'
    },
    onChange: handleImageSelect
  }), /* 이미지 첨부 버튼 */
  React.createElement('button', {
    onClick: function () {
      if (fileInputRef.current) fileInputRef.current.click();
    },
    disabled: sending,
    title: '이미지 첨부 (5MB 이하)',
    style: {
      width: 36,
      height: 36,
      borderRadius: '50%',
      background: imagePreview ? '#dbeafe' : '#f1f5f9',
      color: imagePreview ? '#2563eb' : '#64748b',
      border: 'none',
      cursor: sending ? 'default' : 'pointer',
      fontSize: 18,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
      transition: 'all 0.15s ease'
    }
  }, '📷'), React.createElement('textarea', {
    ref: inputRef,
    value: input,
    onChange: function (e) {
      setInput(e.target.value);
    },
    onKeyDown: handleKeyDown,
    placeholder: imagePreview ? '이미지에 대해 질문하세요...' : '질문을 입력하세요...',
    rows: 1,
    style: {
      flex: 1,
      padding: '8px 12px',
      borderRadius: 10,
      border: '1px solid #e2e8f0',
      outline: 'none',
      resize: 'none',
      fontSize: 13,
      lineHeight: 1.5,
      fontFamily: 'inherit',
      maxHeight: 80,
      overflowY: 'auto'
    }
  }), React.createElement('button', {
    onClick: sendMessage,
    disabled: sending || !input.trim() && !imageB64,
    style: {
      width: 36,
      height: 36,
      borderRadius: '50%',
      background: sending || !input.trim() && !imageB64 ? '#e2e8f0' : '#1B2A4A',
      color: '#fff',
      border: 'none',
      cursor: sending || !input.trim() && !imageB64 ? 'default' : 'pointer',
      fontSize: 16,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0
    }
  }, '➤'))), /* ===== 의견함 탭 ===== */
  activeTab === 'feedback' && React.createElement('div', {
    style: {
      flex: 1,
      overflowY: 'auto',
      padding: 18,
      display: 'flex',
      flexDirection: 'column',
      gap: 16
    }
  }, /* 완료 메시지 */
  fbSent && React.createElement('div', {
    style: {
      padding: '16px 20px',
      background: '#dcfce7',
      borderRadius: 12,
      textAlign: 'center'
    }
  }, React.createElement('div', {
    style: {
      fontSize: 28,
      marginBottom: 8
    }
  }, '✅'), React.createElement('div', {
    style: {
      fontSize: 14,
      fontWeight: 600,
      color: '#166534'
    }
  }, '의견이 접수되었습니다!'), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#166534',
      marginTop: 4
    }
  }, '소중한 의견 감사합니다.')), /* 안내 */
  !fbSent && React.createElement(React.Fragment, null, React.createElement('div', {
    style: {
      fontSize: 13,
      color: '#475569',
      lineHeight: 1.6
    }
  }, '로직 분석 프로그램에 대한 의견을 남겨주세요.', React.createElement('br'), '오류, 기능 요청, 개선 사항 등 무엇이든 환영합니다!'), /* 카테고리 선택 */
  React.createElement('div', null, React.createElement('div', {
    style: {
      fontSize: 12,
      fontWeight: 600,
      color: '#334155',
      marginBottom: 8
    }
  }, '카테고리 선택'), React.createElement('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, categoryOptions.map(function (cat) {
    var isSelected = fbCategory === cat.value;
    return React.createElement('button', {
      key: cat.value,
      onClick: function () {
        setFbCategory(cat.value);
      },
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '10px 14px',
        borderRadius: 10,
        cursor: 'pointer',
        background: isSelected ? cat.bg : '#f8fafc',
        border: isSelected ? '2px solid ' + cat.color : '1px solid #e2e8f0',
        textAlign: 'left',
        transition: 'all 0.15s ease'
      }
    }, React.createElement('span', {
      style: {
        fontSize: 20
      }
    }, cat.icon), React.createElement('div', null, React.createElement('div', {
      style: {
        fontSize: 13,
        fontWeight: 600,
        color: isSelected ? cat.color : '#334155'
      }
    }, cat.label), React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#94a3b8'
      }
    }, cat.desc)));
  }))), /* 내용 입력 */
  fbCategory && React.createElement('div', null, React.createElement('div', {
    style: {
      fontSize: 12,
      fontWeight: 600,
      color: '#334155',
      marginBottom: 8
    }
  }, '내용'), React.createElement('textarea', {
    value: fbContent,
    onChange: function (e) {
      setFbContent(e.target.value);
    },
    placeholder: fbCategory === 'error' ? '어떤 오류가 발생했나요? 상황을 자세히 적어주세요...' : fbCategory === 'request' ? '어떤 기능이 있으면 좋겠나요?...' : '의견이나 건의 사항을 자유롭게 적어주세요...',
    rows: 4,
    style: {
      width: '100%',
      padding: '10px 14px',
      borderRadius: 10,
      border: '1px solid #e2e8f0',
      outline: 'none',
      resize: 'vertical',
      fontSize: 13,
      lineHeight: 1.5,
      fontFamily: 'inherit',
      boxSizing: 'border-box'
    }
  }), /* 이미지 첨부 (선택) */
  React.createElement('input', {
    type: 'file',
    accept: 'image/png,image/jpeg,image/gif,image/webp',
    ref: fbFileInputRef,
    onChange: handleFbImageSelect,
    style: {
      display: 'none'
    }
  }), fbImagePreview ? React.createElement('div', {
    style: {
      marginTop: 8,
      position: 'relative',
      display: 'inline-block'
    }
  }, React.createElement('img', {
    src: fbImagePreview,
    style: {
      maxWidth: '100%',
      maxHeight: 160,
      borderRadius: 10,
      border: '1px solid #e2e8f0',
      display: 'block'
    }
  }), React.createElement('button', {
    onClick: clearFbImage,
    title: '이미지 제거',
    style: {
      position: 'absolute',
      top: 6,
      right: 6,
      width: 24,
      height: 24,
      borderRadius: '50%',
      background: 'rgba(0,0,0,0.6)',
      color: '#fff',
      border: 'none',
      cursor: 'pointer',
      fontSize: 14,
      lineHeight: '24px',
      padding: 0
    }
  }, '×')) : React.createElement('button', {
    onClick: function () {
      if (fbFileInputRef.current) fbFileInputRef.current.click();
    },
    style: {
      marginTop: 8,
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      padding: '8px 12px',
      borderRadius: 10,
      background: '#f8fafc',
      border: '1px dashed #cbd5e1',
      color: '#64748b',
      fontSize: 12,
      fontWeight: 600,
      cursor: 'pointer'
    }
  }, '🖼️ 이미지 첨부 (선택)'), React.createElement('button', {
    onClick: sendFeedback,
    disabled: fbSending || !fbContent.trim(),
    style: {
      marginTop: 10,
      width: '100%',
      padding: '10px 0',
      borderRadius: 10,
      background: fbSending || !fbContent.trim() ? '#e2e8f0' : '#1B2A4A',
      color: fbSending || !fbContent.trim() ? '#94a3b8' : '#fff',
      border: 'none',
      fontSize: 13,
      fontWeight: 600,
      cursor: fbSending || !fbContent.trim() ? 'default' : 'pointer'
    }
  }, fbSending ? '전송 중...' : '의견 보내기')), /* ===== 내 의견 이력 ===== */
  React.createElement('div', {
    style: {
      marginTop: 8,
      borderTop: '1px solid #e2e8f0',
      paddingTop: 16
    }
  }, React.createElement('div', {
    style: {
      fontSize: 12,
      fontWeight: 600,
      color: '#334155',
      marginBottom: 10,
      display: 'flex',
      alignItems: 'center',
      gap: 6
    }
  }, '📋 내 의견 이력'), myFeedback.length === 0 && fbHistoryLoaded && React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#94a3b8',
      textAlign: 'center',
      padding: '12px 0'
    }
  }, '아직 등록한 의견이 없습니다.'), myFeedback.map(function (fb) {
    var _catInfo = {
      error: {
        icon: '🚨',
        label: '오류',
        color: '#dc2626',
        bg: '#fee2e2'
      },
      request: {
        icon: '💡',
        label: '요청',
        color: '#2563eb',
        bg: '#dbeafe'
      },
      opinion: {
        icon: '💬',
        label: '의견',
        color: '#7c3aed',
        bg: '#ede9fe'
      }
    };
    var catInfo = _catInfo[fb.category] || _catInfo.opinion;
    var _statusMap = {
      pending: {
        label: '접수됨',
        color: '#f59e0b',
        bg: '#fffbeb'
      },
      in_progress: {
        label: '처리중',
        color: '#3b82f6',
        bg: '#dbeafe'
      },
      resolved: {
        label: '완료',
        color: '#10b981',
        bg: '#dcfce7'
      }
    };
    var statusInfo = _statusMap[fb.status] || _statusMap.pending;
    return React.createElement('div', {
      key: fb.id,
      style: {
        padding: '10px 12px',
        borderRadius: 10,
        background: '#f8fafc',
        border: '1px solid #e2e8f0',
        marginBottom: 8,
        fontSize: 12
      }
    }, /* 헤더: 카테고리 + 상태 + 날짜 */
    React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        marginBottom: 6
      }
    }, React.createElement('span', {
      style: {
        padding: '2px 6px',
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 600,
        color: catInfo.color,
        background: catInfo.bg
      }
    }, catInfo.icon + ' ' + catInfo.label), React.createElement('span', {
      style: {
        padding: '2px 6px',
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 600,
        color: statusInfo.color,
        background: statusInfo.bg
      }
    }, statusInfo.label), React.createElement('span', {
      style: {
        flex: 1
      }
    }), React.createElement('span', {
      style: {
        fontSize: 10,
        color: '#94a3b8'
      }
    }, (fb.created_at || '').slice(0, 16))), /* 내용 (태그 제거) */
    React.createElement('div', {
      style: {
        color: '#334155',
        lineHeight: 1.5,
        wordBreak: 'break-word'
      }
    }, (fb.content || '').replace(/^#\S+\s*/, '')), /* 관리자 답변 */
    fb.admin_reply && React.createElement('div', {
      style: {
        marginTop: 8,
        padding: '8px 10px',
        borderRadius: 8,
        background: '#eff6ff',
        border: '1px solid #bfdbfe',
        fontSize: 11,
        color: '#1e40af',
        lineHeight: 1.5
      }
    }, React.createElement('div', {
      style: {
        fontWeight: 600,
        marginBottom: 2,
        fontSize: 10
      }
    }, '💼 관리자 답변'), fb.admin_reply), /* 완료 시간 */
    fb.resolved_at && React.createElement('div', {
      style: {
        marginTop: 4,
        fontSize: 10,
        color: '#10b981'
      }
    }, '✅ 처리 완료: ' + fb.resolved_at.slice(0, 16)));
  }))))));
};

;/* ===== js/components/TopBar.jsx ===== */
/* TopBar — 상단 카테고리 바 (App.jsx에서 분리)
 * props: { activePage, currentUser, health, onNavigate(page) }
 */
var _navBtnBase = {
  padding: '7px 16px',
  borderRadius: 8,
  cursor: 'pointer',
  fontSize: 13,
  transition: 'all 0.2s'
};
var _navBtnActive = Object.assign({}, _navBtnBase, {
  background: '#3b82f6',
  color: '#fff',
  border: '1px solid #3b82f6',
  fontWeight: 700
});
var _navBtnInactive = Object.assign({}, _navBtnBase, {
  background: '#ffffff',
  color: '#475569',
  border: '1px solid #f0d2d2',
  fontWeight: 500
});
var _navUserStyle = {
  color: '#475569',
  fontSize: 13,
  fontWeight: 600
};
var _topbarContainer = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'flex-start',
  flexWrap: 'wrap',
  minHeight: 48,
  padding: '8px 24px',
  gap: 10
};
var _versionBadge = {
  fontSize: 11,
  color: '#94a3b8',
  background: '#f1f5f9',
  padding: '2px 8px',
  borderRadius: 10,
  fontWeight: 400
};
var _healthBadge = {
  background: '#dcfce7',
  color: '#16a34a',
  fontSize: 11,
  padding: '2px 8px',
  borderRadius: 10,
  fontWeight: 600
};
function _navBtn(active) {
  return active ? _navBtnActive : _navBtnInactive;
}
window.TopBar = function TopBar(props) {
  var activePage = props.activePage;
  var currentUser = props.currentUser || {};
  var health = props.health;
  var go = props.onNavigate || function () {};
  return React.createElement('div', {
    className: 'topbar'
  }, React.createElement('div', {
    className: 'container',
    style: _topbarContainer
  }, React.createElement('div', {
    className: 'logo',
    style: {
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      gap: 8
    },
    onClick: function () {
      go('home');
    }
  }, React.createElement('img', {
    src: '/img/logo_light.png',
    alt: 'META INC',
    style: {
      height: 28,
      width: 'auto',
      display: 'block'
    }
  }), React.createElement('span', {
    style: _versionBadge
  }, APP_VERSION), (activePage === 'analysis' || activePage === 'home') && health && React.createElement('span', {
    style: _healthBadge
  }, '● 정상')), React.createElement('div', {
    className: 'topbar-nav-btns',
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      flexWrap: 'wrap',
      marginLeft: 8
    }
  }, React.createElement('button', {
    onClick: function () {
      go('home');
    },
    style: _navBtn(activePage === 'home')
  }, '🏠 대시보드'), React.createElement('button', {
    onClick: function () {
      go('analysis');
    },
    style: _navBtn(activePage === 'analysis')
  }, '📍 순위 추적'), React.createElement('button', {
    onClick: function () {
      go('management');
    },
    style: _navBtn(activePage === 'management')
  }, '📈 로직 분석'), React.createElement('button', {
    onClick: function () {
      go('guide');
    },
    style: _navBtn(activePage === 'guide')
  }, '📖 설명서'),
  // 👥 직원 탭 제거 — SSO(ERP 연동)로 계정 자동 관리, 로그인 이력/실행 건수는 ⚙️설정 탭으로 통합
  currentUser.role === 'superadmin' && React.createElement('button', {
    onClick: function () {
      go('settings');
    },
    style: _navBtn(activePage === 'settings')
  }, '⚙️ 설정')), React.createElement('div', {
    className: 'topbar-user-area',
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginLeft: 'auto'
    }
  }, React.createElement('span', {
    style: _navUserStyle
  }, currentUser.name || currentUser.username), function () {
    var _r = currentUser.role;
    var _label = _r === 'superadmin' ? '최고관리자' : _r === 'admin' ? '관리자' : _r === 'manager' ? '매니저' : '뷰어';
    var _isAdmin = _r === 'admin' || _r === 'superadmin';
    var _bg = _isAdmin ? '#ede9fe' : _r === 'manager' ? '#dbeafe' : '#f1f5f9';
    var _fg = _isAdmin ? '#6d28d9' : _r === 'manager' ? '#1d4ed8' : '#475569';
    return React.createElement('span', {
      title: '내 권한',
      style: {
        fontSize: 11,
        fontWeight: 800,
        padding: '2px 9px',
        borderRadius: 999,
        background: _bg,
        color: _fg,
        whiteSpace: 'nowrap'
      }
    }, _label);
  }())));
};

;/* ===== js/components/Footer.jsx ===== */
/* Footer — 하단 푸터 (App.jsx에서 분리, 중복 제거) */
window.Footer = function Footer() {
  return React.createElement('footer', {
    className: 'footer'
  }, React.createElement('div', {
    className: 'container'
  }, '© 2026 메타아이앤씨 — 로직 분석 ' + APP_VERSION + ' | 네이버 쇼핑 키워드 분석 & 순위 추적'));
};

;/* ===== js/components/AnalysisResults.jsx ===== */
/* AnalysisResults — 메인 분석결과 렌더 (App.jsx에서 분리)
 * report-shell(좌측 목차 + 본문 전 섹션). App의 상태/핸들러를 props로 받음. */
window.AnalysisResults = function AnalysisResults(props) {
  var advertiserLoading = props.advertiserLoading;
  var advertiserReport = props.advertiserReport;
  var analysisData = props.analysisData;
  var companyName = props.companyName;
  var currentUser = props.currentUser;
  var datalabData = props.datalabData;
  var datalabLoading = props.datalabLoading;
  var handleNavigateToClient = props.handleNavigateToClient;
  var htmlDetailResult = props.htmlDetailResult;
  var htmlReviewData = props.htmlReviewData;
  var lastHtmlRef = props.lastHtmlRef;
  var loadProducts = props.loadProducts;
  var products = props.products;
  var rankCheckResult = props.rankCheckResult;
  var relatedData = props.relatedData;
  var scrollTo = props.scrollTo;
  var searchLoading = props.searchLoading;
  var searchedKeyword = props.searchedKeyword;
  var searchedProductUrl = props.searchedProductUrl;
  var sections = props.sections;
  var setRankCheckResult = props.setRankCheckResult;
  var shopProducts = props.shopProducts;
  var volumeData = props.volumeData;
  return React.createElement('div', {
    className: 'report-shell'
  }, /* 좌측 고정 목차 (와이드 화면 전용) — 분석 결과(섹션 2개 이상)가 있을 때만 표시 */
  sections.length > 1 && React.createElement('nav', {
    className: 'report-toc'
  }, React.createElement('div', {
    className: 'report-toc-title'
  }, '목차'), sections.map(function (s) {
    return React.createElement('a', {
      key: s.id,
      className: 'report-toc-link',
      onClick: function () {
        scrollTo(s.id);
      }
    }, React.createElement('span', {
      className: 'report-toc-n'
    }, s.icon), s.label);
  }), React.createElement('div', {
    className: 'report-toc-legend'
  }, React.createElement('div', null, React.createElement('b', {
    className: 'badge b-ok'
  }, '✅ 실측'), ' 네이버 실제값'), React.createElement('div', null, React.createElement('b', {
    className: 'badge b-est'
  }, '≈ 추정'), ' 계산·근거기반'), React.createElement('div', null, React.createElement('b', {
    className: 'badge b-ai'
  }, 'AI'), ' AI 생성'))), /* 본문 시작 (이후 모든 섹션이 report-main의 자식) */
  React.createElement('div', {
    className: 'report-main'
  }, /* 보고서 표지(광고주 정보) 카드 */
  analysisData && React.createElement('div', {
    className: 'report-cover'
  }, React.createElement('div', {
    className: 'report-cover-head'
  }, React.createElement('span', {
    className: 'rc-ic'
  }, '📋'), React.createElement('span', {
    className: 'rc-title'
  }, '로직 분석 보고서')), React.createElement('div', {
    className: 'rc-grid'
  }, React.createElement('div', {
    className: 'rc-field'
  }, React.createElement('div', {
    className: 'rc-k'
  }, '광고주 / 스토어'), React.createElement('div', {
    className: 'rc-v'
  }, companyName || '-')), React.createElement('div', {
    className: 'rc-field'
  }, React.createElement('div', {
    className: 'rc-k'
  }, '분석 키워드'), React.createElement('div', {
    className: 'rc-v'
  }, searchedKeyword || '-')), React.createElement('div', {
    className: 'rc-field'
  }, React.createElement('div', {
    className: 'rc-k'
  }, '상품 URL'), React.createElement('div', {
    className: 'rc-v rc-url',
    title: searchedProductUrl || ''
  }, searchedProductUrl || '-')), React.createElement('div', {
    className: 'rc-field'
  }, React.createElement('div', {
    className: 'rc-k'
  }, '분석일'), React.createElement('div', {
    className: 'rc-v'
  }, new Date().toLocaleDateString('ko'))))), /* 모바일용 가로 목차 */
  React.createElement('div', {
    className: 'anchor-nav-wrap'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    className: 'anchor-nav'
  }, sections.map(function (s) {
    return React.createElement('button', {
      key: s.id,
      className: 'anchor-btn',
      onClick: function () {
        scrollTo(s.id);
      }
    }, React.createElement('span', {
      className: 'anchor-icon'
    }, s.icon), s.label);
  })))), /* 1페이지 진입 전략 비교 분석 (통합) — 로딩 */
  advertiserLoading && !advertiserReport && React.createElement('div', {
    id: 'sec-strategy',
    className: 'section'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement(LoadingSpinner, {
    text: '1페이지 진입 전략 분석 중... 약 10~15초 소요됩니다'
  }))), /* 대시보드 요약 — 분석 전 메인 화면에서만 표시, 특정 업체 분석 시 숨김 */
  !searchedProductUrl && React.createElement(DashboardSummary, {
    products: products,
    searchResult: relatedData
  }), /* [DATALAB] 로딩 인디케이터 */
  analysisData && !datalabData && datalabLoading && React.createElement('div', {
    className: 'section fade-in',
    style: {
      textAlign: 'center',
      padding: '24px 0'
    }
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 10,
      color: '#64748b',
      fontSize: 13
    }
  }, React.createElement('div', {
    className: 'spinner-small'
  }), '데이터랩 쇼핑인사이트 분석 중...'))), /* (검색 전 안내 제거 — 공간 낭비 없이 추적상품/순위 목록이 바로 보이도록) */

  /* 검색 로딩 */
  searchLoading && React.createElement('div', {
    className: 'section'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    style: {
      textAlign: 'center',
      padding: '40px 20px'
    }
  }, React.createElement('span', {
    className: 'spinner',
    style: {
      width: 32,
      height: 32,
      borderWidth: 3,
      marginBottom: 16,
      display: 'inline-block'
    }
  }), React.createElement('div', {
    style: {
      fontSize: 15,
      fontWeight: 600,
      color: '#4f46e5',
      marginBottom: 6
    }
  }, '"' + searchedKeyword + '" 분석 중...'), React.createElement('div', {
    style: {
      fontSize: 13,
      color: '#94a3b8'
    }
  }, '검색량·경쟁강도·시장규모를 종합 분석하고 있습니다. 약 5~10초 소요됩니다.')))), /* ==================== 보고서 6단계 흐름 (v6.0 — 광고주 발송용 재배치) ==================== */

  /* ========== 1. 종합 요약 ========== */
  analysisData && React.createElement(window.SectionDivider, {
    label: '1. 종합 요약',
    icon: '📋',
    color: '#4f46e5',
    sub: '광고주가 가장 먼저 보는 핵심 지표'
  }), analysisData && analysisData.summaryCards && React.createElement(window.SectionErrorBoundary, {
    name: '종합 요약'
  }, React.createElement('div', {
    id: 'sec-summary'
  }, React.createElement(SummaryCardsSection, {
    data: analysisData.summaryCards
  }))), /* ========== 2. 시장 · 수요 진단 ========== */
  analysisData && React.createElement(window.SectionDivider, {
    label: '2. 시장 · 수요 진단',
    icon: '📊',
    color: '#0ea5e9',
    sub: '검색량 · 트렌드 · 시즌 · 인구 · 요일 · 성장 · 시장규모'
  }), /* 키워드 검색량 */
  volumeData && React.createElement(window.SectionErrorBoundary, {
    name: '키워드 검색량'
  }, React.createElement(KeywordVolumeSection, {
    keyword: searchedKeyword,
    data: volumeData
  })), /* [DATALAB] 12개월 검색량 트렌드 (꺾은선) */
  datalabData && datalabData.trend && React.createElement(window.SectionErrorBoundary, {
    name: '검색량 트렌드'
  }, React.createElement(window.DatalabTrendSection, {
    data: datalabData.trend
  })), /* [DATALAB] 시즌별 수요 예측 */
  datalabData && datalabData.season && React.createElement(window.SectionErrorBoundary, {
    name: '시즌별 수요'
  }, React.createElement(window.DatalabSeasonSection, {
    data: datalabData.season
  })), /* [DATALAB] 성별 + 연령대별 검색 비율 */
  datalabData && (datalabData.gender || datalabData.age) && React.createElement(window.SectionErrorBoundary, {
    name: '검색 인구통계'
  }, React.createElement(window.DatalabDemographicsSection, {
    data: datalabData
  })), /* [DATALAB] 요일별 검색 패턴 */
  datalabData && datalabData.weekday && React.createElement(window.SectionErrorBoundary, {
    name: '요일별 패턴'
  }, React.createElement(window.DatalabWeekdaySection, {
    data: datalabData.weekday
  })), /* [DATALAB] 전년 동기 대비 성장률 */
  datalabData && datalabData.growth && React.createElement(window.SectionErrorBoundary, {
    name: '전년 성장률'
  }, React.createElement(window.DatalabGrowthSection, {
    data: datalabData.growth
  })), /* [DATALAB] 카테고리 인기 키워드 TOP */
  datalabData && datalabData.categoryKeywords && React.createElement(window.SectionErrorBoundary, {
    name: '카테고리 인기 키워드'
  }, React.createElement(window.DatalabCategoryKeywordsSection, {
    data: datalabData.categoryKeywords
  })), /* 시장 규모 & 매출 추정 */
  analysisData && analysisData.marketRevenue && React.createElement(window.SectionErrorBoundary, {
    name: '시장 규모'
  }, React.createElement('div', {
    id: 'sec-market'
  }, React.createElement(MarketRevenueSection, {
    data: analysisData.marketRevenue,
    reviewCount: htmlReviewData && htmlReviewData.reviewCount || (analysisData.reviewAnalysis && analysisData.reviewAnalysis.reviewCount ? analysisData.reviewAnalysis.reviewCount.adv : null),
    productPrice: analysisData.marketRevenue ? parseInt((analysisData.marketRevenue.avgPrice || '0').replace(/[^0-9]/g, '')) : 0
  }))), /* ========== 3. 경쟁 진단 ========== */
  analysisData && React.createElement(window.SectionDivider, {
    label: '3. 경쟁 진단',
    icon: '⚔️',
    color: '#ef4444',
    sub: '경쟁강도 · 광고경쟁 · 경쟁사 · 카테고리'
  }), /* 키워드 경쟁강도 */
  analysisData && analysisData.competitionIndex && React.createElement(window.SectionErrorBoundary, {
    name: '경쟁강도'
  }, React.createElement('div', {
    id: 'sec-competition'
  }, React.createElement(CompetitionIndexSection, {
    data: analysisData.competitionIndex
  }))), /* 광고 경쟁 정보 */
  analysisData && analysisData.advertiserInfo && React.createElement(window.SectionErrorBoundary, {
    name: '광고 경쟁 정보'
  }, React.createElement(AdvertiserInfoCard, {
    data: analysisData.advertiserInfo
  })), /* 경쟁사 비교표 (상위 80개) */
  analysisData && analysisData.competitorTable && React.createElement(window.SectionErrorBoundary, {
    name: '경쟁사 비교표'
  }, React.createElement(window.CompetitorTableSection, {
    data: analysisData.competitorTable
  })), /* 카테고리 등록 분석 */
  analysisData && analysisData.categoryAnalysis && React.createElement(window.SectionErrorBoundary, {
    name: '카테고리 분석'
  }, React.createElement(CategoryAnalysisSection, {
    data: analysisData.categoryAnalysis
  })), /* ========== 4. 내 상품 현황 ========== */
  analysisData && React.createElement(window.SectionDivider, {
    label: '4. 내 상품 현황',
    icon: '🛒',
    color: '#059669',
    sub: '노출순위 · 판매추정 · 리뷰 · SEO 4종'
  }), /* 키워드별 노출 순위 */
  React.createElement(window.SectionErrorBoundary, {
    name: '순위 추적'
  }, React.createElement(RankTrackingSection, {
    products: products,
    refreshProducts: loadProducts,
    searchedKeyword: searchedKeyword,
    searchedProductUrl: searchedProductUrl,
    cachedProductName: advertiserReport && advertiserReport.product_name ? advertiserReport.product_name : analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo.product_name : null,
    relatedKeywords: relatedData ? (relatedData.golden_keywords || []).concat(relatedData.related_keywords || []).map(function (k) {
      return typeof k === 'string' ? k : k && k.keyword || '';
    }).filter(Boolean) : [],
    onNavigateToClient: handleNavigateToClient,
    canEdit: currentUser.role !== 'viewer',
    onRankResult: setRankCheckResult
  })), /* 판매량 추정 */
  analysisData && analysisData.salesEstimation && React.createElement(window.SectionErrorBoundary, {
    name: '판매량 추정'
  }, React.createElement('div', {
    id: 'sec-sales'
  }, React.createElement(SalesEstimationSection, {
    data: analysisData.salesEstimation,
    reviewCount: htmlReviewData && htmlReviewData.reviewCount || (analysisData.reviewAnalysis && analysisData.reviewAnalysis.reviewCount ? analysisData.reviewAnalysis.reviewCount.adv : null),
    productPrice: analysisData.marketRevenue ? parseInt((analysisData.marketRevenue.avgPrice || '0').replace(/[^0-9]/g, '')) : 0
  }))), /* 리뷰 & 찜 분석 */
  analysisData && analysisData.reviewAnalysis && React.createElement(window.SectionErrorBoundary, {
    name: '리뷰 분석'
  }, React.createElement(window.ReviewAnalysisSection, {
    data: analysisData.reviewAnalysis,
    htmlReviewData: htmlReviewData
  })), /* 리뷰 텍스트 분석 */
  htmlReviewData && htmlReviewData.reviews && htmlReviewData.reviews.length > 0 && React.createElement(window.SectionErrorBoundary, {
    name: '리뷰 텍스트 분석'
  }, React.createElement(window.ReviewTextAnalysisSection, {
    data: htmlReviewData.reviewTextAnalysis,
    reviews: htmlReviewData.reviews,
    totalReviewCount: htmlReviewData.reviewCount
  })), /* SEO 종합 진단 */
  searchedProductUrl && React.createElement(window.SectionErrorBoundary, {
    name: 'SEO 진단'
  }, React.createElement(SeoDiagnosisSection, {
    keyword: searchedKeyword,
    productUrl: searchedProductUrl,
    competitorData: analysisData && analysisData.competitorTable,
    cachedRank: analysisData && analysisData.seoDetail ? analysisData.seoDetail.popularity.items[0].pass !== undefined ? function () {
      var rankText = analysisData.seoDetail.popularity.items[0].label;
      var m = rankText.match(/(\d+)위/);
      return m ? parseInt(m[1]) : null;
    }() : null : null,
    cachedProductName: advertiserReport && advertiserReport.product_name ? advertiserReport.product_name : analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo.product_name : null,
    cachedTotalVolume: volumeData && volumeData[0] ? (volumeData[0].monthlyPcQcCnt || 0) + (volumeData[0].monthlyMobileQcCnt || 0) : null,
    cachedProductInfo: analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo : null,
    shopProducts: shopProducts
  })), /* SEO 상세 분석 (적합도/신뢰도/인기도) */
  analysisData && analysisData.seoDetail && React.createElement(window.SectionErrorBoundary, {
    name: 'SEO 상세'
  }, React.createElement(window.SeoDetailSection, {
    data: analysisData.seoDetail
  })), /* 상세페이지 품질 진단 */
  analysisData && analysisData.detailPageQuality && React.createElement(window.SectionErrorBoundary, {
    name: '상세페이지 품질'
  }, React.createElement(window.DetailPageQualitySection, {
    data: analysisData.detailPageQuality
  })), /* 상세페이지 HTML 분석 */
  htmlDetailResult && React.createElement(window.SectionErrorBoundary, {
    name: '상세페이지 HTML 분석'
  }, React.createElement(window.HtmlDetailAnalysisSection, {
    data: htmlDetailResult
  })), /* ========== 5. 기회 발굴 ========== */
  analysisData && React.createElement(window.SectionDivider, {
    label: '5. 기회 발굴',
    icon: '💎',
    color: '#7c3aed',
    sub: '연관키워드 · 골든키워드 · 상품명 최적화'
  }), /* 연관 키워드 */
  relatedData && React.createElement(window.SectionErrorBoundary, {
    name: '연관 키워드'
  }, React.createElement(RelatedKeywordsSection, {
    data: relatedData
  })), /* 골든 키워드 */
  analysisData && analysisData.goldenKeyword && React.createElement(window.SectionErrorBoundary, {
    name: '골든 키워드'
  }, React.createElement('div', {
    id: 'sec-golden'
  }, React.createElement(GoldenKeywordCard, {
    data: analysisData.goldenKeyword
  }))), /* 상품명 키워드 분석 (키워드&태그 통합) */
  searchedProductUrl && React.createElement(window.SectionErrorBoundary, {
    name: '상품명 분석'
  }, React.createElement(ProductNameSection, {
    keyword: searchedKeyword,
    shopProducts: shopProducts
  })), /* 상품명 SEO 최적화 제안 */
  analysisData && analysisData.productNameOpt && React.createElement(window.SectionErrorBoundary, {
    name: '상품명 최적화'
  }, React.createElement(window.ProductNameOptSection, {
    data: analysisData.productNameOpt
  })), /* ========== 6. 전략 · 결론 ========== */
  analysisData && React.createElement(window.SectionDivider, {
    label: '6. 전략 · 결론',
    icon: '🧭',
    color: '#1e293b',
    sub: '진입전략 · AI 종합 · 보고서 내보내기'
  }), /* 17. 1페이지 진입 전략 비교 분석 */
  (advertiserReport || analysisData && analysisData.strategicAnalysis) && !advertiserLoading && React.createElement(window.SectionErrorBoundary, {
    name: '진입 전략'
  }, React.createElement(EntryStrategySection, {
    advertiserData: advertiserReport,
    strategicData: analysisData && analysisData.strategicAnalysis,
    keyword: searchedKeyword,
    rankCheckResult: rankCheckResult
  })), /* 19. AI 종합 분석 리포트 */
  analysisData && React.createElement(window.SectionErrorBoundary, {
    name: 'AI 종합 분석'
  }, React.createElement(AiFeedbackAllSection, {
    keyword: searchedKeyword,
    analysisData: analysisData,
    volumeData: volumeData,
    relatedData: relatedData,
    advertiserReport: advertiserReport
  })), /* 20. 업체 등록/저장 (viewer는 숨김) */
  analysisData && currentUser.role !== 'viewer' && React.createElement(window.SectionErrorBoundary, {
    name: '업체 저장'
  }, React.createElement(SaveToClientSection, {
    keyword: searchedKeyword,
    productUrl: searchedProductUrl,
    analysisData: analysisData,
    volumeData: volumeData,
    relatedData: relatedData,
    shopProducts: shopProducts,
    advertiserReport: advertiserReport,
    detailHtml: lastHtmlRef.current,
    htmlDetailResult: htmlDetailResult
  })), /* 21. 보고서 출력 */
  searchedProductUrl && React.createElement(window.SectionErrorBoundary, {
    name: '보고서'
  }, React.createElement(ReportSection, {
    keyword: searchedKeyword,
    companyName: companyName
  })), /* 알림 설정 (admin/superadmin만) */
  (currentUser.role === 'admin' || currentUser.role === 'superadmin') && React.createElement(window.SectionErrorBoundary, {
    name: '알림 설정'
  }, React.createElement(NotificationSection, null)), /* 푸터 */
  React.createElement(window.Footer, null)) /* report-main 닫기 */) /* report-shell 닫기 */;
};

;/* ===== js/components/App.jsx ===== */
/* App — 메인 앱 컴포넌트 (v3 에이전시) */
/* APP_VERSION은 utils.js에서 전역 선언 */

/* ==================== 정적 스타일 (렌더 밖 — 매번 재생성 방지) ==================== */

window.App = function App() {
  const {
    useState,
    useEffect,
    useCallback
  } = React;

  /* ==================== 인증 상태 ==================== */
  const [currentUser, setCurrentUser] = useState(null);
  const [authToken, setAuthToken] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);
  // URL hash에서 현재 페이지 복원 (새로고침 시 탭 유지)
  var _getPageFromHash = function () {
    var hash = window.location.hash.replace('#', '');
    var validPages = ['home', 'analysis', 'management', 'guide', 'settings'];
    return validPages.indexOf(hash) !== -1 ? hash : 'home';
  };
  const [currentPage, setCurrentPage] = useState(_getPageFromHash);

  /* ==================== 기존 상태 (hooks는 반드시 조건문 전에) ==================== */
  const [health, setHealth] = useState(false);
  const [products, setProducts] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchedKeyword, setSearchedKeyword] = useState('');
  const [volumeData, setVolumeData] = useState(null);
  const [relatedData, setRelatedData] = useState(null);
  const [analysisData, setAnalysisData] = useState(null);
  const [shopProducts, setShopProducts] = useState(null);
  const [advertiserReport, setAdvertiserReport] = useState(null);
  const [advertiserLoading, setAdvertiserLoading] = useState(false);
  const [htmlReviewData, setHtmlReviewData] = useState(null);
  const [htmlDetailResult, setHtmlDetailResult] = useState(null);
  const [searchedProductUrl, setSearchedProductUrl] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [datalabData, setDatalabData] = useState(null);
  const [datalabLoading, setDatalabLoading] = useState(false);
  const [rankCheckResult, setRankCheckResult] = useState(null); // 순위 추적 → 진입 전략 공유용
  const searchIdRef = React.useRef(0); // 비동기 요청 경합 방지용
  const lastHtmlRef = React.useRef(''); // #1: 마지막 분석에 쓰인 상세 HTML (업체 저장/재사용용)

  /* 업체 카드 클릭으로 시작된 분석 추적 (자동 저장용) */
  const [currentClientId, setCurrentClientId] = useState(null);
  const [searchBarInitial, setSearchBarInitial] = useState(null);
  const [autoSaveStatus, setAutoSaveStatus] = useState(''); // '', 'saving', 'saved', 'error'

  /* 순위 추적 → 업체관리 이동 시 자동 검색용 */
  const [managementInitialSearch, setManagementInitialSearch] = useState(null);
  var saveAuth = function (user, token) {
    setCurrentUser(user);
    setAuthToken(token);
    try {
      sessionStorage.setItem('logic_token', token);
      sessionStorage.setItem('logic_user', JSON.stringify(user));
    } catch (e) {}
  };
  var clearAuth = function () {
    setCurrentUser(null);
    setAuthToken(null);
    setCurrentPage('analysis');
    try {
      sessionStorage.removeItem('logic_token');
      sessionStorage.removeItem('logic_user');
    } catch (e) {}
  };
  useEffect(function () {
    try {
      // 0) 전산(ERP) SSO 자동 로그인: URL ?sso=<토큰> 있으면 우선 처리
      var _ssoTok = '';
      try {
        _ssoTok = new URLSearchParams(window.location.search).get('sso') || '';
      } catch (e) {}
      if (_ssoTok) {
        var _cleanUrl = function () {
          try {
            var u = new URL(window.location.href);
            u.searchParams.delete('sso');
            window.history.replaceState({}, document.title, u.pathname + u.search + u.hash);
          } catch (e) {}
        };
        fetch('/api/auth/sso', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            token: _ssoTok
          })
        }).then(function (r) {
          return r.json();
        }).then(function (data) {
          _cleanUrl();
          if (data && data.success && data.token && data.user) {
            saveAuth(data.user, data.token);
          }
          setAuthChecking(false);
        }).catch(function () {
          _cleanUrl();
          setAuthChecking(false);
        });
        return; // SSO 처리로 분기 — 아래 세션복원 스킵
      }
      // 기존 세션 복원
      var savedToken = sessionStorage.getItem('logic_token');
      if (savedToken) {
        fetch('/api/auth/me', {
          headers: {
            'Authorization': 'Bearer ' + savedToken
          }
        }).then(function (r) {
          return r.json();
        }).then(function (data) {
          if (data && data.id) {
            setCurrentUser(data);
            setAuthToken(savedToken);
          } else if (data && data.success && data.user) {
            setCurrentUser(data.user);
            setAuthToken(savedToken);
          }
          setAuthChecking(false);
        }).catch(function () {
          setAuthChecking(false);
        });
      } else {
        setAuthChecking(false);
      }
    } catch (e) {
      setAuthChecking(false);
    }
  }, []);

  // URL hash ↔ currentPage 동기화
  useEffect(function () {
    if (currentPage) {
      window.location.hash = currentPage;
    }
  }, [currentPage]);
  useEffect(function () {
    var onHashChange = function () {
      var page = _getPageFromHash();
      setCurrentPage(page);
    };
    window.addEventListener('hashchange', onHashChange);
    return function () {
      window.removeEventListener('hashchange', onHashChange);
    };
  }, []);

  // 헬스체크
  useEffect(function () {
    if (currentUser) {
      api.get('/health').then(function (res) {
        setHealth(res.status === 'ok');
      }).catch(function () {
        setHealth(false);
      });
    }
  }, [currentUser]);

  // 상품 목록 로드
  var loadProducts = useCallback(function () {
    api.get('/products').then(function (res) {
      if (res.success) setProducts(res.data);
    }).catch(function () {});
  }, []);
  useEffect(function () {
    if (currentUser) loadProducts();
  }, [loadProducts, currentUser]);

  /* 업체 연동 자동 저장 — Rules of Hooks에 따라 early return 이전에 선언.
     실제 저장 조건은 effect 내부에서 가드 (로그인 전에는 currentClientId가 null이라 no-op). */
  useEffect(function () {
    if (!currentClientId) return;
    if (!analysisData) return;
    if (searchLoading) return;
    if (currentUser && currentUser.role === 'viewer') return; // 뷰어는 자동저장 금지
    if (autoSaveStatus === 'saving' || autoSaveStatus === 'saved') return;
    setAutoSaveStatus('saving');
    var savedClientId = currentClientId;
    var savedKeyword = searchedKeyword;
    var savedUrl = searchedProductUrl;
    var mounted = true;
    var nestedTimers = [];
    var timer = setTimeout(function () {
      if (!mounted) return;
      var reportHtml = typeof captureAutoReportHtml === 'function' ? captureAutoReportHtml(savedKeyword) : '';
      api.post('/cd/analyze', {
        client_id: savedClientId,
        keyword: savedKeyword,
        product_url: savedUrl || '',
        analysis_data: htmlDetailResult ? Object.assign({}, analysisData, {
          htmlDetail: trimHtmlDetail(htmlDetailResult)
        }) : analysisData,
        volume_data: volumeData || {},
        related_data: relatedData || {},
        shop_products: (shopProducts || []).slice(0, 20),
        advertiser_data: advertiserReport || {},
        report_html: reportHtml,
        detail_html: lastHtmlRef.current || ''
      }).then(function (res) {
        if (!mounted) return;
        if (res && res.success) {
          setAutoSaveStatus('saved');
          nestedTimers.push(setTimeout(function () {
            if (mounted) setAutoSaveStatus('');
          }, 4000));
        } else {
          setAutoSaveStatus('error');
          nestedTimers.push(setTimeout(function () {
            if (mounted) setAutoSaveStatus('');
          }, 5000));
        }
      }).catch(function () {
        if (!mounted) return;
        setAutoSaveStatus('error');
        nestedTimers.push(setTimeout(function () {
          if (mounted) setAutoSaveStatus('');
        }, 5000));
      });
    }, 25000);
    return function () {
      mounted = false;
      clearTimeout(timer);
      nestedTimers.forEach(function (t) {
        clearTimeout(t);
      });
    };
  }, [analysisData, currentClientId, searchLoading, autoSaveStatus]);
  if (authChecking) return React.createElement('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
      background: 'linear-gradient(135deg,#6C5CE7,#a29bfe)',
      gap: 16
    }
  }, React.createElement('img', {
    src: '/img/logo_dark.png',
    alt: 'META INC',
    style: {
      height: 40,
      width: 'auto',
      marginBottom: 8
    }
  }), React.createElement('span', {
    className: 'spinner',
    style: {
      width: 28,
      height: 28,
      borderWidth: 3,
      borderColor: 'rgba(255,255,255,0.3)',
      borderTopColor: '#fff'
    }
  }), React.createElement('div', {
    style: {
      color: '#fff',
      fontSize: 14,
      fontWeight: 500,
      opacity: 0.8
    }
  }, '시스템 연결 중...'));
  if (!currentUser) return React.createElement(window.LoginPage, {
    onLogin: saveAuth
  });

  // 수동 검색 (SearchBar 제출): 업체 자동연동 해제
  var handleManualSearch = function (keyword, productUrl, inputCompanyName, htmlInput) {
    setCurrentClientId(null);
    setAutoSaveStatus('');
    handleSearch(keyword, productUrl, inputCompanyName, htmlInput);
  };

  // 상품 URL 정리 — 불필요한 추적 파라미터 제거
  var cleanProductUrl = function (url) {
    if (!url) return '';
    try {
      var u = new URL(url);
      // smartstore URL이면 path만 유지 (NaPm, nl-query 등 제거)
      if (u.hostname.indexOf('smartstore.naver.com') !== -1) {
        return u.origin + u.pathname;
      }
      // 그 외 URL은 NaPm, nl-query 파라미터만 제거
      u.searchParams.delete('NaPm');
      u.searchParams.delete('nl-query');
      return u.toString();
    } catch (e) {
      return url;
    }
  };

  // 통합 검색 (htmlInput: 검색바에서 입력된 HTML — 상세페이지 분석 + 리뷰 추출에 사용)
  var handleSearch = function (keyword, productUrl, inputCompanyName, htmlInput) {
    // Viewer 일일 분석 횟수 체크 (백엔드 연동)
    if (currentUser && currentUser.role === 'viewer') {
      api.get('/cd/usage/check').then(function (usageRes) {
        if (usageRes && usageRes.success && usageRes.data && !usageRes.data.can_query) {
          toast.error('일일 분석 제한(3회)을 초과했습니다. 내일 자정에 초기화됩니다.');
          return;
        }
        // 제한 내 → 카운트 증가 후 실제 분석 실행
        api.post('/cd/usage/increment').then(function () {
          _doSearch(keyword, productUrl, inputCompanyName, htmlInput);
        }).catch(function () {
          _doSearch(keyword, productUrl, inputCompanyName, htmlInput);
        });
      }).catch(function () {
        _doSearch(keyword, productUrl, inputCompanyName, htmlInput);
      });
      return;
    }
    // 관리자/매니저도 수동 분석 카운팅
    api.post('/cd/usage/increment').catch(function () {});
    _doSearch(keyword, productUrl, inputCompanyName, htmlInput);
  };
  var _doSearch = function (keyword, productUrl, inputCompanyName, htmlInput) {
    lastHtmlRef.current = htmlInput || ''; // #1: 저장/재사용용 상세 HTML 보관
    if (inputCompanyName !== undefined) setCompanyName(inputCompanyName);
    var cleanedUrl = cleanProductUrl(productUrl);
    // URL을 안 넣어도 됨: 붙여넣은 HTML에서 상품 URL 자동 추출 → 순위/광고주 분석 정상 동작
    if (!cleanedUrl && htmlInput && typeof extractProductUrlFromHtml === 'function') {
      var _autoUrl = extractProductUrlFromHtml(htmlInput);
      if (_autoUrl) {
        cleanedUrl = cleanProductUrl(_autoUrl);
        try {
          toast.info('HTML에서 상품 URL을 자동 인식했습니다.');
        } catch (e) {}
      }
    }
    var currentSearchId = ++searchIdRef.current; // 새 검색마다 ID 증가
    setSearchLoading(true);
    setSearchedKeyword(keyword);
    setSearchedProductUrl(cleanedUrl);
    setVolumeData(null);
    setRelatedData(null);
    setAnalysisData(null);
    setShopProducts(null);
    setAdvertiserReport(null);
    setAdvertiserLoading(false);
    setHtmlReviewData(null);
    setHtmlDetailResult(null);
    setDatalabData(null);
    setDatalabLoading(false);
    setRankCheckResult(null);

    // 검색바에서 HTML이 입력되었으면 상세페이지 분석 + 리뷰 데이터 추출 (비동기)
    if (htmlInput && htmlInput.length >= 100) {
      api.post('/seo/detail-page', {
        html: htmlInput,
        product_url: productUrl || ''
      }).then(function (res) {
        if (searchIdRef.current !== currentSearchId) return; // 이미 다른 검색 시작됨
        if (res && res.success && res.data) {
          setHtmlDetailResult(res.data);
          if (res.data.reviewData) {
            setHtmlReviewData(res.data.reviewData);
          }
          toast.success('상세페이지 HTML 분석 완료');
        } else if (res && !res.success) {
          toast.error('상세페이지 분석 실패: ' + (res.detail || '서버 오류'));
        }
      }).catch(function (e) {
        if (searchIdRef.current !== currentSearchId) return;
        console.warn('HTML 상세페이지 분석 실패:', e.message);
        toast.error('상세페이지 분석 요청 실패 — ' + (e.message || '네트워크 오류'));
      });
    }

    // 광고주 상품 URL이 있으면 광고주 분석 API 호출
    if (productUrl) {
      setAdvertiserLoading(true);
      api.post('/advertiser/analyze', {
        keyword: keyword,
        product_url: productUrl
      }).then(function (res) {
        if (searchIdRef.current !== currentSearchId) return;
        if (res && res.success) setAdvertiserReport(res.data);
        setAdvertiserLoading(false);
      }).catch(function () {
        if (searchIdRef.current !== currentSearchId) return;
        setAdvertiserLoading(false);
      });
    }

    // 병렬로 3개 API 호출
    Promise.all([api.post('/keyword/volume', [keyword]).catch(function () {
      return null;
    }), api.post('/keywords/related', {
      keyword: keyword
    }).catch(function () {
      return null;
    }), api.post('/products/search', {
      keyword: keyword,
      count: 80
    }).catch(function () {
      return null;
    })]).then(function (results) {
      if (searchIdRef.current !== currentSearchId) return; // 이미 다른 검색 시작됨

      var volRes = results[0];
      var relRes = results[1];
      var shopRes = results[2];

      // 모든 API 실패 시 사용자에게 알림
      if ((!volRes || !volRes.success) && (!relRes || !relRes.success) && (!shopRes || !shopRes.success)) {
        toast.error('키워드 분석 데이터를 가져오지 못했습니다. 네트워크를 확인해주세요.');
      }
      if (volRes && volRes.success) setVolumeData(volRes.data);
      if (relRes && relRes.success) setRelatedData(relRes.data);
      var prods = shopRes && shopRes.success && shopRes.data ? shopRes.data.products : [];
      var totalShopProducts = shopRes && shopRes.success && shopRes.data ? shopRes.data.total : 0;
      if (prods.length > 0) setShopProducts(prods);

      // 검색량 데이터 추출
      var vol = volRes && volRes.success && volRes.data && volRes.data[0] ? volRes.data[0] : null;
      var totalVol = vol ? (vol.monthlyPcQcCnt || 0) + (vol.monthlyMobileQcCnt || 0) : 0;
      var productCount = totalShopProducts || prods.length;

      // 연관 키워드 데이터
      var rd = relRes && relRes.success && relRes.data ? relRes.data : null;

      // ==================== 분석 데이터 계산 ====================
      var analysis = {};

      // 1. 경쟁강도 계산 (백분율 변환)
      if (productCount > 0 && totalVol > 0) {
        var rawIdx = productCount / totalVol;
        // 백분율 변환: rawIdx 0→0%, 0.5→30%, 1.0→50%, 2.0→70%, 5.0→90%, 10+→98%
        // 로그 스케일로 자연스럽게 매핑
        var compPercent = Math.min(98, Math.round(Math.log10(rawIdx * 10 + 1) / Math.log10(101) * 100));
        compPercent = Math.max(2, compPercent);
        var compLevel, compColor;
        if (compPercent <= 30) {
          compLevel = '블루오션';
          compColor = '#059669';
        } else if (compPercent <= 70) {
          compLevel = '보통';
          compColor = '#d97706';
        } else {
          compLevel = '레드오션';
          compColor = '#dc2626';
        }

        // 전문 코멘트 2~3줄 (실제 데이터 기반)
        var avgCtrVal = vol ? (vol.monthlyAvePcClkCnt || 0) + (vol.monthlyAveMobileClkCnt || 0) : 0;
        var compComment = '';
        if (compPercent <= 30) {
          compComment = '월간 검색량 ' + fmt(totalVol) + '회 대비 등록 상품 ' + fmt(productCount) + '개로, 공급이 수요를 따라가지 못하는 시장입니다. ';
          compComment += '신규 진입 시 상위 노출 가능성이 높으며, 상품 등록만으로도 검색 트래픽을 확보할 수 있는 최적의 타이밍입니다.';
          if (avgCtrVal > 0) compComment += ' 평균 클릭수 ' + avgCtrVal.toFixed(1) + '회로 구매 의향이 높은 키워드입니다.';
        } else if (compPercent <= 70) {
          compComment = '월간 검색량 ' + fmt(totalVol) + '회에 상품 ' + fmt(productCount) + '개가 경쟁 중인 시장입니다. ';
          compComment += '진입은 가능하지만, 가격 경쟁력·리뷰 확보·상품명 최적화 등 차별화 전략이 필요합니다. ';
          compComment += '상위 10위 이내 진입을 목표로 SEO 최적화에 집중하세요.';
        } else {
          compComment = '월간 검색량 ' + fmt(totalVol) + '회 대비 상품 ' + fmt(productCount) + '개로, 공급 과잉 상태의 치열한 시장입니다. ';
          compComment += '기존 상위 셀러들이 리뷰·판매 실적을 선점하고 있어, 동일 키워드로의 진입은 높은 광고비를 수반합니다. ';
          compComment += '세부 키워드(롱테일) 전략이나 틈새 카테고리를 공략하는 것을 권장합니다.';
        }
        analysis.competitionIndex = {
          compIndex: parseFloat(rawIdx.toFixed(2)),
          compPercent: compPercent,
          compLabel: compLevel,
          compColor: compColor,
          productCount: productCount,
          searchVolume: totalVol,
          avgCtr: avgCtrVal,
          interpretation: compComment
        };
      }

      // 2. 시장 규모 추정 (CTR × 전환율 기반)
      if (prods.length > 0) {
        var prices = prods.map(function (p) {
          return p.price;
        }).filter(function (p) {
          return p > 0;
        });
        var avgPrice = prices.length > 0 ? Math.round(prices.reduce(function (a, b) {
          return a + b;
        }, 0) / prices.length) : 0;
        var conversionRate = 0.035; // 전환율 3.5%

        var topProductsList = prods.slice(0, 40).map(function (p) {
          var ctr = getCTR(p.rank);
          var estSales = Math.max(1, Math.round(totalVol * ctr * conversionRate));
          return {
            rank: p.rank,
            name: p.product_name,
            store: p.store_name,
            price: p.price,
            priceStr: fmt(p.price) + '원',
            ctr: ctr,
            estMonthlySales: estSales,
            estMonthlySalesStr: fmt(estSales) + '건',
            estRevenue: p.price * estSales,
            estRevenueStr: fmt(p.price * estSales) + '원'
          };
        });

        // 전체 시장 규모 = 상위 40개 상품 추정 매출 합산
        var totalMarketRevenue = topProductsList.slice(0, 40).reduce(function (sum, p) {
          return sum + p.estRevenue;
        }, 0);
        analysis.marketRevenue = {
          avgPrice: fmt(avgPrice) + '원',
          estimatedMonthly: fmt(totalMarketRevenue) + '원',
          conversionRate: '3.5%',
          calculationMethod: 'CTR × 전환율',
          topProducts: topProductsList.map(function (p) {
            return {
              rank: p.rank,
              name: p.name,
              store: p.store,
              price: p.priceStr,
              ctr: (p.ctr * 100).toFixed(1) + '%',
              estMonthlySales: p.estMonthlySalesStr,
              estRevenue: p.estRevenueStr
            };
          })
        };
      }

      // 3. 키워드 트렌드
      if (totalVol > 0 && rd && rd.related_keywords && rd.related_keywords.length > 0) {
        var subKw = rd.related_keywords[0];
        analysis.keywordTrend = {
          mainKeyword: keyword,
          subKeyword: subKw.keyword,
          mainVolume: totalVol,
          subVolume: subKw.totalVolume || 0,
          mainDifficulty: function () {
            var ci = analysis.competitionIndex;
            return ci && ci.compIndex < 0.5 ? '쉬움' : ci && ci.compIndex < 1.0 ? '보통' : '어려움';
          }(),
          subDifficulty: subKw.compIdx === '낮음' || subKw.compIdx === 'LOW' ? '쉬움' : subKw.compIdx === '높음' || subKw.compIdx === 'HIGH' ? '어려움' : '보통',
          mainDiffColor: analysis.competitionIndex ? analysis.competitionIndex.compColor : '#94a3b8',
          subDiffColor: subKw.compIdx === '낮음' || subKw.compIdx === 'LOW' ? '#16a34a' : subKw.compIdx === '높음' || subKw.compIdx === 'HIGH' ? '#dc2626' : '#d97706'
        };
      }

      // 4. 골든 키워드 (스토어명 필터링 적용)
      if (rd && rd.golden_keywords && rd.golden_keywords.length > 0) {
        // 스토어명이 아닌 키워드만 필터 (백엔드에서 이미 필터하지만 이중 안전장치)
        var filteredGolden = rd.golden_keywords.filter(function (gk) {
          return !gk.isStoreName;
        });
        var gk = filteredGolden.length > 0 ? filteredGolden[0] : rd.golden_keywords[0];
        var gkVolume = gk.totalVolume || 0;
        var gkClicks = gk.monthlyAvePcClkCnt ? gk.monthlyAvePcClkCnt + gk.monthlyAveMobileClkCnt : 0;
        var gkClickRate = gkVolume > 0 ? (gkClicks / gkVolume * 100).toFixed(1) : 0;

        // 디테일한 추천 이유 생성
        var gkReason = '"' + gk.keyword + '"은(는) 월간 검색량 ' + fmt(gkVolume) + '회로 안정적인 수요가 존재합니다. ';
        if (gkClicks > 0) {
          gkReason += '평균 클릭수 ' + gkClicks.toFixed(1) + '회(클릭률 ' + gkClickRate + '%)로 구매 의도가 높은 키워드입니다. ';
        }
        gkReason += '경쟁강도 "' + compLabel(gk.compIdx) + '" 수준이라 상위 노출 진입 비용이 낮습니다. ';
        gkReason += '메인 키워드 "' + keyword + '"의 세부 키워드로 상품명에 함께 포함시키면 추가 유입을 확보할 수 있습니다.';
        analysis.goldenKeyword = {
          name: gk.keyword,
          score: gk.score || (gkVolume ? Math.round(gkVolume / 100) : 0),
          volume: gkVolume,
          competition: compLabel(gk.compIdx),
          ctr: gkClicks,
          clicks: Math.round(gkVolume * 0.05),
          reason: gkReason
        };
      }

      // 5. 광고주 상품 정보
      if (vol) {
        analysis.advertiserInfo = {
          adDepth: vol.plAvgDepth || 0,
          pcClicks: (vol.monthlyAvePcClkCnt || 0).toFixed(1),
          mobileClicks: (vol.monthlyAveMobileClkCnt || 0).toFixed(1),
          compIdx: vol.compIdx || '-'
        };
      }

      // 6. 종합 요약 카드
      analysis.summaryCards = {
        totalVolume: fmt(totalVol),
        productCount: fmt(productCount),
        goldenCount: rd ? (rd.golden_keywords || []).length : 0,
        compLevel: analysis.competitionIndex ? analysis.competitionIndex.compLabel : '-'
      };

      // 7. 카테고리 분석 (대>중>소 계층 경로)
      if (prods.length > 0) {
        var fullpathMap = {};
        var cat1Map = {};
        var cat2Map = {};
        var cat3Map = {};
        prods.forEach(function (p) {
          var c1 = p.category1 || '';
          var c2 = p.category2 || '';
          var c3 = p.category3 || '';
          var parts = [c1, c2, c3].filter(function (x) {
            return x;
          });
          var fullPath = parts.length > 0 ? parts.join(' > ') : '기타';
          fullpathMap[fullPath] = (fullpathMap[fullPath] || 0) + 1;
          if (c1) cat1Map[c1] = (cat1Map[c1] || 0) + 1;
          if (c2) cat2Map[c2] = (cat2Map[c2] || 0) + 1;
          if (c3) cat3Map[c3] = (cat3Map[c3] || 0) + 1;
        });
        var total = prods.length;
        var categories = Object.keys(fullpathMap).map(function (k) {
          return {
            name: k,
            count: fullpathMap[k],
            ratio: Math.round(fullpathMap[k] / total * 100)
          };
        }).sort(function (a, b) {
          return b.count - a.count;
        });
        var makeLevelList = function (map) {
          return Object.keys(map).map(function (k) {
            return {
              name: k,
              count: map[k],
              ratio: Math.round(map[k] / total * 100)
            };
          }).sort(function (a, b) {
            return b.count - a.count;
          }).slice(0, 5);
        };
        var topCat = categories[0] || {
          name: '-',
          ratio: 0
        };
        analysis.categoryAnalysis = {
          verdict: topCat.name + ' 카테고리에 ' + topCat.ratio + '% 등록',
          mainCategory: topCat.name,
          categories: categories.slice(0, 8),
          categoryLevels: {
            large: makeLevelList(cat1Map),
            medium: makeLevelList(cat2Map),
            small: makeLevelList(cat3Map)
          }
        };
      }

      // 8. 키워드 & 태그 분석
      if (rd) {
        var allKws = (rd.golden_keywords || []).concat(rd.related_keywords || []);
        analysis.keywordTags = {
          topKeywords: allKws.slice(0, 15).map(function (k) {
            return {
              keyword: k.keyword,
              volume: k.totalVolume || 0,
              comp: compLabel(k.compIdx),
              isGolden: k.isGolden
            };
          }),
          totalFound: rd.total_found || allKws.length
        };
      }

      // 9. 경쟁사 비교표 (종합점수 포함)
      if (prods.length > 0) {
        // 상위 20개 평균가격 (가격 경쟁력 계산용)
        var compPrices = prods.slice(0, 20).map(function (p) {
          return p.price;
        }).filter(function (p) {
          return p > 0;
        });
        var avgCompPrice = compPrices.length > 0 ? compPrices.reduce(function (a, b) {
          return a + b;
        }, 0) / compPrices.length : 0;
        // 최다 카테고리 (카테고리 적합도 계산용)
        var catCounts = {};
        prods.slice(0, 80).forEach(function (p) {
          var cat = p.category2 || p.category1 || '';
          if (cat) catCounts[cat] = (catCounts[cat] || 0) + 1;
        });
        var topCat = '';
        var topCatCount = 0;
        Object.keys(catCounts).forEach(function (k) {
          if (catCounts[k] > topCatCount) {
            topCat = k;
            topCatCount = catCounts[k];
          }
        });
        analysis.competitorTable = prods.slice(0, 80).map(function (p) {
          // --- 종합점수 계산 (백엔드 SEO 로직과 동일 가중치) ---
          // 1. 상품명 (15%) — 키워드 포함 여부
          var kwInTitle = keyword.toLowerCase().split(' ').some(function (w) {
            return p.product_name.toLowerCase().indexOf(w) >= 0;
          });
          var nameLen = p.product_name.length;
          var titleSc = (kwInTitle ? 40 : 0) + (nameLen >= 20 && nameLen <= 50 ? 30 : nameLen >= 10 ? 20 : 10) + 20;

          // 2. 가격 경쟁력 (12%)
          var priceSc = 50;
          if (p.price > 0 && avgCompPrice > 0) {
            var pr = p.price / avgCompPrice;
            priceSc = pr <= 0.85 ? 100 : pr <= 1.0 ? 80 : pr <= 1.15 ? 60 : pr <= 1.3 ? 40 : 20;
          }

          // 3. 순위 (15%)
          var rankSc = p.rank <= 10 ? 100 : p.rank <= 20 ? 80 : p.rank <= 40 ? 60 : 40;

          // 4. 리뷰 추정 (12%)
          var reviewSc = p.rank <= 5 ? 95 : p.rank <= 10 ? 80 : p.rank <= 20 ? 60 : 40;

          // 5. 평점 추정 (8%)
          var ratingSc = p.rank <= 10 ? 90 : p.rank <= 20 ? 75 : p.rank <= 40 ? 60 : 45;

          // 6. 판매실적 추정 (10%)
          var salesSc = p.rank <= 5 ? 95 : p.rank <= 10 ? 80 : p.rank <= 20 ? 60 : 40;

          // 7. 카테고리 적합도 (8%)
          var pCat = p.category2 || p.category1 || '';
          var catSc = pCat === topCat ? 100 : pCat ? 60 : 20;

          // 8. 브랜드 (8%)
          var brandSc = (p.brand ? 40 : 0) + (p.store_name ? 30 : 0) + (p.product_url && p.product_url.indexOf('smartstore.naver.com') >= 0 ? 30 : 0);
          brandSc = Math.min(brandSc, 100);

          // 9. 네이버페이 (6%)
          var npSc = p.product_url && p.product_url.indexOf('smartstore.naver.com') >= 0 ? 100 : 50;

          // 10. 최신성 (6%)
          var freshSc = p.rank <= 20 ? 80 : p.rank <= 40 ? 60 : 40;
          var totalSc = Math.round(titleSc * 0.15 + priceSc * 0.12 + rankSc * 0.15 + reviewSc * 0.12 + ratingSc * 0.08 + salesSc * 0.10 + catSc * 0.08 + brandSc * 0.08 + npSc * 0.06 + freshSc * 0.06);
          return {
            rank: p.rank,
            name: p.product_name,
            store: p.store_name,
            price: fmt(p.price) + '원',
            brand: p.brand || '-',
            category: p.category2 || p.category1 || '-',
            image: p.image_url,
            seoScore: totalSc
          };
        });
      }

      // 10. 판매량 추정 카드형 (TOP10 / 1페이지 / 2페이지) — CTR_TABLE 전역 사용
      if (prods.length > 0 && totalVol > 0) {
        var top10p = prods.slice(0, 10);
        var avgP = Math.round(top10p.reduce(function (s, p) {
          return s + p.price;
        }, 0) / top10p.length);
        var cv = 0.035;
        // 80위 전체 한번에 계산
        var allRanks = [];
        for (var ci = 0; ci < 80; ci++) {
          var sales = Math.round(totalVol * CTR_TABLE[ci] * cv);
          allRanks.push({
            sales: sales,
            revenue: sales * avgP
          });
        }
        // TOP 10 집계
        var top10Rev = 0;
        for (var ci = 0; ci < 10; ci++) top10Rev += allRanks[ci].revenue;
        // 1페이지 (1~40) 집계
        var p1Sales = 0,
          p1Total = 0;
        for (var ci = 0; ci < 40; ci++) {
          p1Sales += allRanks[ci].sales;
          p1Total += allRanks[ci].revenue;
        }
        // 2페이지 (41~80) 집계
        var p2Sales = 0,
          p2Total = 0;
        for (var ci = 40; ci < 80; ci++) {
          p2Sales += allRanks[ci].sales;
          p2Total += allRanks[ci].revenue;
        }
        analysis.salesEstimation = {
          avgPrice: fmt(avgP) + '원',
          monthlySearches: fmt(totalVol),
          estimatedCTR: 'CTR × 3.5%',
          top10Card: {
            rank1Sales: allRanks[0].sales,
            rank5Sales: allRanks[4].sales,
            rank10Sales: allRanks[9].sales,
            rank1Revenue: fmt(allRanks[0].revenue) + '원',
            rank10Revenue: fmt(allRanks[9].revenue) + '원',
            totalRevenue: fmt(top10Rev) + '원'
          },
          page1Card: {
            avgSales: Math.round(p1Sales / 40),
            totalSales: p1Sales,
            maxRevenue: fmt(allRanks[0].revenue) + '원',
            minRevenue: fmt(allRanks[39].revenue) + '원',
            avgRevenue: fmt(Math.round(p1Total / 40)) + '원',
            totalRevenue: fmt(p1Total) + '원'
          },
          page2Card: {
            avgSales: Math.round(p2Sales / 40),
            totalSales: p2Sales,
            maxRevenue: fmt(allRanks[40].revenue) + '원',
            minRevenue: fmt(allRanks[79].revenue) + '원',
            avgRevenue: fmt(Math.round(p2Total / 40)) + '원',
            totalRevenue: fmt(p2Total) + '원'
          }
        };
      }

      // 11. 1페이지 진입 전략 비교
      if (prods.length >= 10 && totalVol > 0) {
        var topItems = prods.slice(0, 10);
        var topPrices = topItems.map(function (p) {
          return p.price;
        });
        var avgTopPrice = Math.round(topPrices.reduce(function (s, v) {
          return s + v;
        }, 0) / topPrices.length);
        var minPrice = Math.min.apply(null, topPrices);
        var maxPrice = Math.max.apply(null, topPrices);
        var ci = analysis.competitionIndex;
        analysis.strategicAnalysis = {
          avgTop5Price: fmt(avgTopPrice) + '원',
          priceRange: fmt(minPrice) + '원 ~ ' + fmt(maxPrice) + '원',
          monthlyVolume: fmt(totalVol),
          mainBrands: function () {
            var brands = {};
            topItems.forEach(function (p) {
              var b = p.brand || p.store_name;
              brands[b] = (brands[b] || 0) + 1;
            });
            return Object.keys(brands).slice(0, 5).join(', ');
          }(),
          recommendation: ci && ci.compIndex < 0.5 ? '현재 시장은 블루오션입니다. 빠른 진입을 추천합니다.' : ci && ci.compIndex < 1.0 ? '경쟁이 적당합니다. 가격/리뷰 전략에 집중하세요.' : '경쟁이 치열합니다. 차별화된 상세페이지와 리뷰 확보가 핵심입니다.'
        };
      }

      // URL에서 스토어명 추출 (매칭 검증용 — 섹션 12, 13에서 공통 사용)
      var _storeMatch = cleanedUrl ? cleanedUrl.match(/smartstore\.naver\.com\/([^\/]+)/) : null;
      var _targetStoreName = _storeMatch ? _storeMatch[1].toLowerCase() : '';
      // 안전한 advProd 매칭 헬퍼 (스토어 URL 슬러그 교차 검증)
      var _findAdvProd = function (prodList) {
        if (!cleanedUrl) return null;
        // 1차: 전체 URL 포함 매칭 (가장 정확)
        var found = prodList.find(function (p) {
          return p.product_url && p.product_url.indexOf(cleanedUrl) >= 0;
        });
        if (found) return found;
        // 2차: 채널상품ID(URL의 /products/ID)로 매칭
        var pidMatch = cleanedUrl.match(/\/products\/(\d+)/);
        if (pidMatch) {
          var pid = pidMatch[1];
          // 2-a: product_id 필드 직접 비교
          found = prodList.find(function (p) {
            return p.product_id && String(p.product_id) === pid;
          });
          if (found) return found;
          // 2-b: product_url에 PID 포함 (네이버 API link = /main/products/채널ID)
          found = prodList.find(function (p) {
            return p.product_url && p.product_url.indexOf(pid) >= 0;
          });
          if (found) return found;
        }
        // 3차: 스토어명으로 매칭 (URL/PID 매칭 실패 시 — store_name 또는 URL 슬러그)
        if (_targetStoreName) {
          found = prodList.find(function (p) {
            // store_name 필드 직접 비교
            if ((p.store_name || '').toLowerCase() === _targetStoreName) return true;
            // product_url에서 스토어 슬러그 추출하여 비교
            var pSlugMatch = (p.product_url || '').match(/smartstore\.naver\.com\/([^\/\?]+)/);
            if (pSlugMatch && pSlugMatch[1].toLowerCase() === _targetStoreName) return true;
            return false;
          });
        }
        return found || null;
      };

      // 12. 리뷰 분석 (상위 상품 기반 추정)
      if (prods.length >= 5) {
        var top5 = prods.slice(0, 5);
        var top20 = prods.slice(0, 20);
        var allProds = prods.slice(0, 80);

        // 리뷰 수 추정 (순위 기반 로그 감소 모델)
        var estReviews = function (rank) {
          return Math.max(1, Math.round(2000 / Math.pow(rank, 0.7)));
        };
        var advReview = cleanedUrl ? function () {
          var advProd = _findAdvProd(prods);
          return advProd ? estReviews(advProd.rank) : estReviews(40);
        }() : estReviews(40);
        var avgReview = Math.round(top20.reduce(function (s, p) {
          return s + estReviews(p.rank);
        }, 0) / top20.length);
        var top5Review = Math.round(top5.reduce(function (s, p) {
          return s + estReviews(p.rank);
        }, 0) / top5.length);

        // 평점 추정 (상위 4.5~4.9, 하위 4.0~4.5)
        var estRating = function (rank) {
          return Math.round((4.9 - (rank - 1) * 0.012) * 10) / 10;
        };
        var advRating = cleanedUrl ? function () {
          var advProd = _findAdvProd(prods);
          return advProd ? estRating(advProd.rank) : estRating(40);
        }() : estRating(40);
        var avgRating = Math.round(top20.reduce(function (s, p) {
          return s + estRating(p.rank);
        }, 0) / top20.length * 10) / 10;
        var top5Rating = Math.round(top5.reduce(function (s, p) {
          return s + estRating(p.rank);
        }, 0) / top5.length * 10) / 10;

        // 찜 수 추정
        var estWish = function (rank) {
          return Math.max(5, Math.round(500 / Math.pow(rank, 0.6)));
        };
        var advWish = cleanedUrl ? function () {
          var advProd = _findAdvProd(prods);
          return advProd ? estWish(advProd.rank) : estWish(40);
        }() : estWish(40);
        var avgWish = Math.round(top20.reduce(function (s, p) {
          return s + estWish(p.rank);
        }, 0) / top20.length);
        var top5Wish = Math.round(top5.reduce(function (s, p) {
          return s + estWish(p.rank);
        }, 0) / top5.length);
        var reviewGap = avgReview > 0 ? Math.round((advReview - avgReview) / avgReview * 100) : 0;
        var ratingGap = avgRating > 0 ? Math.round((advRating - avgRating) / avgRating * 100) : 0;
        var wishGap = avgWish > 0 ? Math.round((advWish - avgWish) / avgWish * 100) : 0;
        analysis.reviewAnalysis = {
          reviewCount: {
            adv: advReview,
            avg: avgReview,
            top5: top5Review,
            gapColor: reviewGap >= 0 ? '#16a34a' : '#dc2626',
            gapLabel: (reviewGap >= 0 ? '+' : '') + reviewGap + '%'
          },
          rating: {
            adv: advRating.toFixed(1),
            avg: avgRating.toFixed(1),
            top5: top5Rating.toFixed(1),
            gapColor: ratingGap >= 0 ? '#16a34a' : '#dc2626',
            gapLabel: (ratingGap >= 0 ? '+' : '') + ratingGap + '%'
          },
          wishCount: {
            adv: advWish,
            avg: avgWish,
            top5: top5Wish,
            gapColor: wishGap >= 0 ? '#16a34a' : '#dc2626',
            gapLabel: (wishGap >= 0 ? '+' : '') + wishGap + '%'
          },
          reviewGapPercent: reviewGap,
          ratingGapPercent: ratingGap,
          wishGapPercent: wishGap,
          strategy: reviewGap < 0 ? '리뷰 수가 경쟁 평균보다 부족합니다. 체험단/구매 후기 이벤트를 통해 리뷰를 확보하세요.' : '리뷰 수가 경쟁 평균 이상입니다. 평점 관리에 집중하세요.'
        };
      }

      // 13. SEO 상세 분석 (상품URL 있을 때)
      if (prods.length > 0) {
        // 공통 헬퍼로 안전하게 매칭
        var advProd = _findAdvProd(prods);
        // advProd가 없으면 (광고주 상품 매칭 실패) prods[0]을 사용하지 않음
        var targetProd = advProd;
        if (targetProd) {
          var kwWords = keyword.toLowerCase().split(/\s+/);
          var titleLower = targetProd.product_name.toLowerCase();
          // 공백 무시 매칭도 인정: 네이버는 띄어쓰기와 무관하게 키워드를 매칭하므로
          // '브로멜라인효소'(붙임)와 '브로멜라인 효소'(띄움)를 동일하게 취급한다.
          var titleNoSpace = titleLower.replace(/\s+/g, '');
          var kwNoSpace = keyword.toLowerCase().replace(/\s+/g, '');
          var kwInTitle = kwWords.every(function (w) {
            return titleLower.indexOf(w) >= 0;
          }) || kwNoSpace.length > 0 && titleNoSpace.indexOf(kwNoSpace) >= 0;
          var titleLen = targetProd.product_name.length;
          var isSmartStore = targetProd.product_url && targetProd.product_url.indexOf('smartstore.naver.com') >= 0;
          var hasBrand = !!targetProd.brand;
          var hasCategory = !!(targetProd.category2 || targetProd.category1);
          var myRank = targetProd.rank || null;
          var myRankLabel = myRank ? myRank + '위' : '미노출';
          var relScore = (kwInTitle ? 40 : 0) + (titleLen >= 20 && titleLen <= 50 ? 30 : titleLen >= 10 ? 15 : 5) + (hasCategory ? 30 : 10);
          var trustScore = (isSmartStore ? 35 : 15) + (hasBrand ? 30 : 10) + (myRank && myRank <= 20 ? 35 : myRank && myRank <= 40 ? 20 : 10);
          var popScore = (myRank && myRank <= 5 ? 40 : myRank && myRank <= 10 ? 30 : myRank && myRank <= 20 ? 20 : 10) + (myRank && myRank <= 10 ? 30 : myRank && myRank <= 20 ? 20 : 10) + (myRank && myRank <= 10 ? 30 : myRank && myRank <= 30 ? 20 : 10);
          analysis.seoDetail = {
            relevance: {
              score: relScore,
              items: [{
                pass: kwInTitle,
                label: '키워드 "' + keyword + '"이(가) 상품명에 포함됨'
              }, {
                pass: titleLen >= 20 && titleLen <= 50,
                label: '상품명 길이 적절 (' + titleLen + '자)'
              }, {
                pass: hasCategory,
                label: '카테고리 정보 존재: ' + (targetProd.category2 || targetProd.category1 || '없음')
              }, {
                pass: kwWords.length > 1 && kwInTitle,
                label: '복합 키워드 완전 포함'
              }]
            },
            trustworthy: {
              score: trustScore,
              items: [{
                pass: isSmartStore,
                label: '네이버 스마트스토어 입점'
              }, {
                pass: hasBrand,
                label: '브랜드 등록: ' + (targetProd.brand || '미등록')
              }, {
                pass: myRank && myRank <= 20,
                label: myRank ? '상위 노출 달성 (현재 ' + myRankLabel + ')' : '검색 결과 내 미노출'
              }, {
                pass: isSmartStore,
                label: '네이버페이 결제 지원'
              }]
            },
            popularity: {
              score: popScore,
              items: [{
                pass: myRank && myRank <= 10,
                label: myRank ? '검색 결과 ' + myRankLabel + (myRank <= 10 ? ' (상위 10위 이내)' : '') : '검색 결과 내 미노출'
              }, {
                pass: myRank && myRank <= 20,
                label: '추정 리뷰 수 경쟁력 있음'
              }, {
                pass: myRank && myRank <= 10,
                label: '추정 판매량 상위권'
              }, {
                pass: myRank && myRank <= 30,
                label: '찜 수 평균 이상 추정'
              }]
            }
          };

          // 14. 상세페이지 품질 진단
          var dpScores = [{
            label: '상품명 최적화',
            score: kwInTitle ? titleLen >= 20 && titleLen <= 50 ? 95 : 70 : 30,
            maxScore: 100,
            color: '#6366f1'
          }, {
            label: '가격 경쟁력',
            score: function () {
              var avgP = prods.slice(0, 20).reduce(function (s, p) {
                return s + p.price;
              }, 0) / 20;
              return targetProd.price <= avgP ? 85 : targetProd.price <= avgP * 1.2 ? 60 : 35;
            }(),
            maxScore: 100,
            color: '#22c55e'
          }, {
            label: '브랜드/스토어 신뢰도',
            score: (hasBrand ? 40 : 0) + (isSmartStore ? 40 : 20) + 10,
            maxScore: 100,
            color: '#f59e0b'
          }, {
            label: '카테고리 적합도',
            score: hasCategory ? 80 : 30,
            maxScore: 100,
            color: '#06b6d4'
          }, {
            label: '검색 노출 순위',
            score: myRank ? myRank <= 5 ? 95 : myRank <= 10 ? 80 : myRank <= 20 ? 60 : myRank <= 40 ? 40 : 20 : 10,
            maxScore: 100,
            color: '#ec4899'
          }];
          var dpTotal = Math.round(dpScores.reduce(function (s, b) {
            return s + b.score;
          }, 0) / dpScores.length);
          var dpGrade = dpTotal >= 80 ? 'A등급' : dpTotal >= 60 ? 'B등급' : dpTotal >= 40 ? 'C등급' : 'D등급';
          var dpGradeColor = dpTotal >= 80 ? '#dcfce7' : dpTotal >= 60 ? '#dbeafe' : dpTotal >= 40 ? '#fef3c7' : '#fee2e2';
          analysis.detailPageQuality = {
            totalScore: dpTotal,
            grade: dpGrade,
            gradeColor: dpGradeColor,
            scoreBars: dpScores,
            checklist: [{
              category: '상품명',
              items: [{
                pass: kwInTitle,
                text: '메인 키워드 포함'
              }, {
                pass: titleLen >= 20,
                text: '상품명 20자 이상'
              }, {
                pass: titleLen <= 50,
                text: '상품명 50자 이하 (과도하지 않음)'
              }]
            }, {
              category: '가격/혜택',
              items: [{
                pass: targetProd.price > 0,
                text: '정상 가격 등록'
              }, {
                pass: isSmartStore,
                text: '네이버페이 지원'
              }]
            }, {
              category: '신뢰도',
              items: [{
                pass: hasBrand,
                text: '브랜드 등록 완료'
              }, {
                pass: isSmartStore,
                text: '스마트스토어 입점'
              }, {
                pass: hasCategory,
                text: '정확한 카테고리 설정'
              }]
            }],
            comment: dpTotal >= 80 ? '상세페이지 품질이 우수합니다. 현재 전략을 유지하세요.' : dpTotal >= 60 ? '전반적으로 양호하나 일부 개선이 필요합니다.' : '상세페이지 개선이 시급합니다. 상품명과 가격 경쟁력을 우선 확인하세요.'
          };

          // 15. 상품명 SEO 최적화 제안
          var nameIssues = [];
          nameIssues.push({
            pass: kwInTitle,
            text: kwInTitle ? '메인 키워드 "' + keyword + '" 포함됨' : '메인 키워드 "' + keyword + '" 미포함 — 상품명에 추가 필요'
          });
          nameIssues.push({
            pass: titleLen >= 20 && titleLen <= 50,
            text: titleLen < 20 ? '상품명이 너무 짧음 (' + titleLen + '자) — 20자 이상 권장' : titleLen > 50 ? '상품명이 너무 김 (' + titleLen + '자) — 50자 이하 권장' : '상품명 길이 적절 (' + titleLen + '자)'
          });
          var hasSpecialChars = /[★☆♥♡●○■□▶◀※@#$%^&*]/.test(targetProd.product_name);
          nameIssues.push({
            pass: !hasSpecialChars,
            text: hasSpecialChars ? '특수문자/이모지 포함 — SEO에 불리할 수 있음' : '불필요한 특수문자 없음'
          });
          var hasDuplicateWords = function () {
            var words = targetProd.product_name.split(/\s+/);
            var seen = {};
            return words.some(function (w) {
              if (seen[w]) return true;
              seen[w] = true;
              return false;
            });
          }();
          nameIssues.push({
            pass: !hasDuplicateWords,
            text: hasDuplicateWords ? '중복 단어 존재 — 제거 권장' : '중복 단어 없음'
          });

          // 추천 상품명 생성
          var suggested = targetProd.product_name;
          if (!kwInTitle) {
            suggested = keyword + ' ' + targetProd.product_name;
            // 중복 단어 토큰 제거 (키워드와 기존 상품명에 같은 단어가 겹치면 한 번만 유지)
            var _seenWord = {};
            suggested = suggested.split(/\s+/).filter(function (w) {
              if (!w) return false;
              var lw = w.toLowerCase();
              if (_seenWord[lw]) return false;
              _seenWord[lw] = true;
              return true;
            }).join(' ');
            if (suggested.length > 50) suggested = suggested.substring(0, 50).trim();
          }
          analysis.productNameOpt = {
            currentName: targetProd.product_name,
            issues: nameIssues,
            suggestedName: suggested !== targetProd.product_name ? suggested : null,
            marketerComment: kwInTitle ? '상품명에 메인 키워드가 포함되어 있어 기본적인 SEO는 충족합니다. 연관 키워드를 추가하면 노출이 더 개선될 수 있습니다.' : '상품명에 메인 키워드 "' + keyword + '"가 없습니다. 상품명 앞부분에 키워드를 배치하면 검색 노출이 크게 개선됩니다.'
          };
        }
      }

      // SEO 진단용 targetProd 정보 저장 (get_product_info API 호출 제거용)
      if (targetProd) {
        analysis.targetProductInfo = {
          product_name: targetProd.product_name,
          price: targetProd.price,
          brand: targetProd.brand || '',
          store_name: targetProd.store_name || '',
          category1: targetProd.category1 || '',
          category2: targetProd.category2 || '',
          image_url: targetProd.image_url || ''
        };
      } else if (_targetStoreName && prods.length > 0) {
        // URL/PID/스토어 3단계 매칭 모두 실패해도 스토어 정보는 전달
        // → 백엔드에서 cached_competitors 스토어명 매칭으로 get_product_info 호출 방지
        var _sameStoreProd = prods.find(function (p) {
          return (p.store_name || '').toLowerCase() === _targetStoreName || ((p.product_url || '').match(/smartstore\.naver\.com\/([^\/\?]+)/) || [])[1] === _targetStoreName;
        });
        analysis.targetProductInfo = {
          product_name: _sameStoreProd ? _sameStoreProd.product_name : '',
          price: _sameStoreProd ? _sameStoreProd.price : 0,
          brand: _sameStoreProd ? _sameStoreProd.brand || '' : '',
          store_name: _sameStoreProd ? _sameStoreProd.store_name || _targetStoreName : _targetStoreName,
          category1: _sameStoreProd ? _sameStoreProd.category1 || '' : '',
          category2: _sameStoreProd ? _sameStoreProd.category2 || '' : '',
          image_url: _sameStoreProd ? _sameStoreProd.image_url || '' : ''
        };
      }
      setAnalysisData(Object.keys(analysis).length > 0 ? analysis : null);
      setSearchLoading(false);

      /* 데이터랩 쇼핑인사이트 비동기 호출 (분석 완료 후) */
      (function () {
        var cat1 = '';
        if (analysis.categoryAnalysis && analysis.categoryAnalysis.categoryLevels && analysis.categoryAnalysis.categoryLevels.large && analysis.categoryAnalysis.categoryLevels.large.length > 0) {
          cat1 = analysis.categoryAnalysis.categoryLevels.large[0].name || '';
        }
        var relKws = [];
        if (analysis.keywordTags && analysis.keywordTags.topKeywords) {
          relKws = analysis.keywordTags.topKeywords.map(function (k) {
            return {
              keyword: k.keyword,
              totalVolume: parseInt(String(k.volume || '0').replace(/,/g, ''))
            };
          });
        }
        setDatalabLoading(true);
        api.post('/datalab/analyze', {
          keyword: keyword,
          category1: cat1,
          related_keywords: relKws
        }).then(function (dlRes) {
          if (searchIdRef.current !== currentSearchId) return;
          if (dlRes && dlRes.success && dlRes.data) {
            setDatalabData(dlRes.data);
          }
        }).catch(function (e) {
          console.warn('데이터랩 조회 실패 (무시):', e);
        }).finally(function () {
          setDatalabLoading(false);
        });
      })();
    }).catch(function (e) {
      if (searchIdRef.current !== currentSearchId) return;
      console.error('검색 오류:', e);
      toast.error('분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
      setSearchLoading(false);
    });
  };

  /* ==================== 순위 추적 → 업체관리 이동 ==================== */
  var handleNavigateToClient = function (storeName, productUrl) {
    setManagementInitialSearch({
      storeName: storeName || '',
      productUrl: productUrl || ''
    });
    setCurrentPage('management');
    try {
      window.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    } catch (e) {}
  };

  /* ==================== 업체 카드 클릭 → 자동 분석 ==================== */
  var handleClientClick = function (params) {
    if (!params) return;
    setCurrentClientId(params.clientId);
    setSearchBarInitial({
      keyword: params.keyword || '',
      productUrl: params.productUrl || '',
      companyName: params.companyName || ''
    });
    setAutoSaveStatus('');
    setCurrentPage('analysis');
    try {
      window.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    } catch (e) {}
    // #1: 업체에 저장된 상세 HTML이 있으면 자동 주입 → 리뷰 텍스트/상세 분석 자동 표시
    handleSearch(params.keyword, params.productUrl || '', params.companyName || '', params.detailHtml || null);
  };

  /* DOM 캡처 — 자동 저장용 HTML 보고서 생성 (SaveToClientSection과 동일 로직) */
  /* (본 함수는 hook이 아니라 일반 함수이므로 early return 이후 위치에 있어도 됨) */
  var captureAutoReportHtml = function (kw) {
    try {
      var captured = [];
      // 화면의 실제 보고서 본문(.report-main)을 통째로 캡처 → 화면과 동일
      var srcRoot = document.querySelector('.report-main') || document.getElementById('root') && document.getElementById('root').children[0];
      if (srcRoot) {
        var cloneRoot = srcRoot.cloneNode(true);
        // 차트(canvas) → 이미지 변환 (정적 HTML에서도 보이도록)
        try {
          var _oc = srcRoot.querySelectorAll('canvas');
          var _cc = cloneRoot.querySelectorAll('canvas');
          for (var _i = 0; _i < _cc.length; _i++) {
            var _du = '';
            var _o = _oc[_i];
            var _ch = window.Chart && window.Chart.getChart && _o ? window.Chart.getChart(_o) : null;
            if (_ch) {
              try {
                _du = _ch.toBase64Image('image/png', 1);
              } catch (e) {}
            }
            if (!_du && _o && _o.toDataURL) {
              try {
                _du = _o.toDataURL('image/png');
              } catch (e) {}
            }
            if (!_du) continue;
            var _img = document.createElement('img');
            _img.src = _du;
            _img.style.cssText = 'width:100%;height:auto;display:block;margin-bottom:14px;';
            if (_cc[_i].parentNode) _cc[_i].parentNode.replaceChild(_img, _cc[_i]);
            // 겹침방지(핵심): 이미지 직속 부모(차트 래퍼 height:NNNpx 고정) + .chartbox 모두 높이 해제
            var _wrap2 = _img.parentNode;
            if (_wrap2 && _wrap2.style) {
              _wrap2.style.height = 'auto';
              _wrap2.style.minHeight = '0';
              _wrap2.style.position = 'static';
            }
            var _box2 = _img.closest && _img.closest('.chartbox') || _wrap2;
            if (_box2 && _box2.style) {
              _box2.style.height = 'auto';
              _box2.style.minHeight = '0';
              _box2.style.overflow = 'visible';
              _box2.style.marginBottom = '18px';
            }
          }
        } catch (e) {}
        captured.push(cloneRoot);
      }
      captured.forEach(function (node) {
        // 내보내기 제외 영역 제거 (보고서/알림/업체저장/네비/버튼/입력)
        ['#sec-report', '#sec-notify', '#sec-save-client', '.anchor-nav', '.topbar', '.no-export'].forEach(function (sel) {
          node.querySelectorAll(sel).forEach(function (el) {
            el.remove();
          });
        });
        node.querySelectorAll('button, .btn').forEach(function (b) {
          b.remove();
        });
        node.querySelectorAll('input, select, textarea').forEach(function (inp) {
          var span = document.createElement('span');
          span.textContent = inp.value || '';
          span.style.fontWeight = '600';
          if (inp.parentNode) inp.parentNode.replaceChild(span, inp);
        });
      });
      var cssText = '';
      try {
        var sheets = document.styleSheets;
        for (var i = 0; i < sheets.length; i++) {
          try {
            var rules = sheets[i].cssRules || sheets[i].rules;
            for (var j = 0; j < rules.length; j++) {
              cssText += rules[j].cssText + '\n';
            }
          } catch (e) {}
        }
      } catch (e) {}
      var bodyHtml = '';
      captured.forEach(function (node) {
        bodyHtml += node.outerHTML + '\n';
      });
      var dateStr = new Date().toLocaleDateString('ko-KR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      });
      // XSS 방지: HTML 특수문자 이스케이프
      var _esc = function (s) {
        var d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
      };
      var headerText = _esc(kw || '키워드') + ' 분석 보고서';
      return '<!DOCTYPE html>\n<html lang="ko">\n<head>\n' + '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n' + '<title>' + headerText + ' - ' + dateStr + '</title>\n<style>\n' + '* { margin: 0; padding: 0; box-sizing: border-box; }\n' + 'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #1e293b; }\n' + '.report-header { background: linear-gradient(135deg, #6C5CE7, #a29bfe); color: #fff; padding: 40px 20px; text-align: center; }\n' + '.report-header h1 { font-size: 24px; margin-bottom: 8px; }\n' + '.report-header p { font-size: 14px; opacity: 0.85; }\n' + '.report-footer { text-align: center; padding: 30px; color: #94a3b8; font-size: 12px; border-top: 1px solid #e2e8f0; margin-top: 40px; }\n' + cssText + '\n</style>\n</head>\n<body>\n' + '<div class="report-header">\n<h1>' + headerText + '</h1>\n' + '<p>' + dateStr + ' | 메타아이앤씨 로직 분석 시스템</p>\n</div>\n' + '<div style="max-width:1200px; margin:0 auto; padding:20px;">\n' + bodyHtml + '</div>\n' + '<div class="report-footer">\n<p>© 2026 메타아이앤씨 — 로직 분석 시스템 | 자동 저장된 보고서</p>\n</div>\n' + '</body>\n</html>';
    } catch (e) {
      console.error('자동 DOM capture 실패:', e);
      return '';
    }
  };

  /* 저장된 분석 데이터를 실제 분석 화면으로 재렌더 → 화면과 동일하게 HTML 다운로드 (옵션 A) */
  var downloadSavedReport = function (saved) {
    if (!saved) {
      toast.error('보고서 데이터가 없습니다.');
      return;
    }
    var kw = saved.keyword || '';
    // 1) 저장 데이터를 화면 상태에 주입 → 분석 화면(React 컴포넌트)으로 그대로 렌더
    setCurrentClientId(saved.client_id || null);
    setCompanyName(saved.companyName || saved.client_name || '');
    setSearchedKeyword(kw);
    setSearchedProductUrl(saved.product_url || '');
    setAnalysisData(saved.analysis_data || null);
    setVolumeData(saved.volume_data || null);
    setRelatedData(saved.related_data || null);
    setShopProducts(saved.shop_products || []);
    setAdvertiserReport(saved.advertiser_data || null);
    // Phase2: 저장된 상세분석(analysis_data.htmlDetail) 주입 → 상세HTML분석·리뷰텍스트 렌더
    var _hd = saved.analysis_data && saved.analysis_data.htmlDetail;
    setHtmlDetailResult(_hd || null);
    setHtmlReviewData(_hd && _hd.reviewData ? _hd.reviewData : null);
    setCurrentPage('analysis');
    try {
      window.scrollTo({
        top: 0
      });
    } catch (e) {}
    toast.info('보고서를 화면에 불러오는 중… 잠시 후 자동 다운로드됩니다.');
    // 2) 차트가 그려질 시간을 준 뒤 화면 그대로 캡처 → 다운로드
    setTimeout(function () {
      try {
        var htmlStr = captureAutoReportHtml(kw);
        if (!htmlStr) {
          toast.error('보고서 생성에 실패했습니다.');
          return;
        }
        var blob = new Blob([htmlStr], {
          type: 'text/html;charset=utf-8'
        });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = (saved.companyName || saved.client_name || '업체') + '_' + kw + '_보고서_' + (saved.analyzed_date || '') + '.html';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
        toast.success('보고서를 다운로드했습니다. (화면과 동일)');
      } catch (e) {
        toast.error('보고서 다운로드 실패: ' + (e && e.message ? e.message : ''));
      }
    }, 3000);
  };

  // 앵커 네비게이션 (페이지 렌더링 순서와 동일하게 정렬)
  var sections = [{
    id: 'sec-rank',
    label: '순위 추적',
    icon: '📍'
  }, {
    id: 'sec-summary',
    label: '종합요약',
    icon: '📊',
    show: !!(analysisData && analysisData.summaryCards)
  }, {
    id: 'sec-volume',
    label: '검색량',
    icon: '🔍',
    show: !!volumeData
  }, {
    id: 'sec-market',
    label: '시장규모',
    icon: '💰',
    show: !!(analysisData && analysisData.marketRevenue)
  }, {
    id: 'sec-sales',
    label: '판매추정',
    icon: '💵',
    show: !!(analysisData && analysisData.salesEstimation)
  }, {
    id: 'sec-competition',
    label: '경쟁강도',
    icon: '⚔️',
    show: !!(analysisData && analysisData.competitionIndex)
  }, {
    id: 'sec-related',
    label: '연관키워드',
    icon: '🔗',
    show: !!relatedData
  }, {
    id: 'sec-golden',
    label: '골든키워드',
    icon: '🌟',
    show: !!(analysisData && analysisData.goldenKeyword)
  }, {
    id: 'sec-competitor',
    label: '경쟁사',
    icon: '🏆',
    show: !!(analysisData && analysisData.competitorTable)
  }, {
    id: 'sec-seo',
    label: 'SEO 진단',
    icon: '🎯',
    show: !!searchedProductUrl
  }, {
    id: 'sec-productname',
    label: '상품명',
    icon: '✏️',
    show: !!searchedProductUrl
  }, {
    id: 'sec-strategy',
    label: '진입전략',
    icon: '🚀',
    show: !!(advertiserReport || advertiserLoading || analysisData && analysisData.strategicAnalysis)
  }, {
    id: 'sec-report',
    label: '보고서',
    icon: '📄',
    show: !!searchedProductUrl
  }].filter(function (s) {
    return s.show !== false;
  });
  var scrollTo = function (id) {
    var el = document.getElementById(id);
    if (el) el.scrollIntoView({
      behavior: 'smooth',
      block: 'start'
    });
  };

  /* ==================== Topbar 스타일 (정적 객체는 컴포넌트 밖에 선언) ==================== */

  /* ==================== 홈에서 검색 시 분석 탭으로 전환하는 핸들러 ==================== */
  var handleHomeSearch = function (keyword, productUrl, inputCompanyName, htmlInput) {
    setCurrentClientId(null);
    setAutoSaveStatus('');
    setCurrentPage('analysis');
    handleSearch(keyword, productUrl, inputCompanyName, htmlInput);
  };

  /* ==================== 페이지별 콘텐츠 렌더링 ==================== */

  /* 홈 탭 — 업체 리스트 + 검색 */
  if (currentPage === 'home') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.TopBar, {
    activePage: 'home',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(SearchBar, {
    onSearch: handleHomeSearch,
    loading: searchLoading,
    initialValues: searchBarInitial
  }), /* 업체 연동 자동저장 상태 배너 */
  currentClientId && autoSaveStatus && React.createElement('div', {
    style: {
      background: autoSaveStatus === 'saved' ? '#dcfce7' : autoSaveStatus === 'error' ? '#fee2e2' : '#e0e7ff',
      color: autoSaveStatus === 'saved' ? '#166534' : autoSaveStatus === 'error' ? '#991b1b' : '#3730a3',
      padding: '10px 0',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'center',
      borderBottom: '1px solid rgba(0,0,0,0.05)'
    }
  }, autoSaveStatus === 'saving' ? '🔄 분석 완료 후 업체관리에 자동 저장됩니다...' : autoSaveStatus === 'saved' ? '✅ 업체관리 탭에 분석 기록이 자동 저장되었습니다' : autoSaveStatus === 'error' ? '⚠️ 자동 저장에 실패했습니다. 분석 완료 후 하단 "업체 등록/저장" 버튼을 이용해주세요' : ''), /* 등록 업체 리스트 */
  React.createElement(window.ClientListSection, {
    currentUser: currentUser,
    onClientClick: handleClientClick,
    onNavigateToClient: handleNavigateToClient
  }), /* 푸터 */
  React.createElement(window.Footer, null)), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
  if (currentPage === 'management') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.TopBar, {
    activePage: 'management',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(window.ClientDashboard, {
    currentUser: currentUser,
    onRunAnalysis: handleClientClick,
    onDownloadReport: downloadSavedReport,
    initialSearch: managementInitialSearch,
    canEdit: currentUser.role !== 'viewer'
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
  if (currentPage === 'guide') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.TopBar, {
    activePage: 'guide',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(window.UserGuidePage, {
    currentUser: currentUser
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
  if (currentPage === 'users' && (currentUser.role === 'admin' || currentUser.role === 'superadmin')) return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.TopBar, {
    activePage: 'users',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(window.UserManagementPage, {
    currentUser: currentUser,
    token: authToken
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
  if (currentPage === 'settings' && currentUser.role === 'superadmin') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.TopBar, {
    activePage: 'settings',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement('div', {
    style: {
      maxWidth: 1000,
      margin: '0 auto',
      padding: '24px 16px'
    }
  }, React.createElement(window.AnalysisStatsSection, null), React.createElement(ApiUsageSection, null), React.createElement(NotificationSection, null), React.createElement(window.ClientDiagnosticsSection, null), React.createElement(window.FeedbackManagement, null))), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));

  /* ==================== 메인 분석 페이지 ==================== */
  return React.createElement(React.Fragment, null, React.createElement('div', {
    className: 'analysis-page'
  }, /* 네비게이션 바 */
  React.createElement(window.TopBar, {
    activePage: 'analysis',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(SearchBar, {
    onSearch: handleManualSearch,
    loading: searchLoading,
    initialValues: searchBarInitial
  }), /* 업체 연동 자동저장 상태 배너 */
  currentClientId && autoSaveStatus && React.createElement('div', {
    style: {
      background: autoSaveStatus === 'saved' ? '#dcfce7' : autoSaveStatus === 'error' ? '#fee2e2' : '#e0e7ff',
      color: autoSaveStatus === 'saved' ? '#166534' : autoSaveStatus === 'error' ? '#991b1b' : '#3730a3',
      padding: '10px 0',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'center',
      borderBottom: '1px solid rgba(0,0,0,0.05)'
    }
  }, autoSaveStatus === 'saving' ? '🔄 분석 완료 후 업체관리에 자동 저장됩니다... (약 25초 대기)' : autoSaveStatus === 'saved' ? '✅ 업체관리 탭에 분석 기록이 자동 저장되었습니다' : autoSaveStatus === 'error' ? '⚠️ 자동 저장에 실패했습니다. 하단의 "업체 등록/저장" 버튼을 이용해주세요' : ''), /* ==================== 보고서 레이아웃: 좌측 목차 + 본문 ==================== */
  React.createElement(window.AnalysisResults, {
    advertiserLoading: advertiserLoading,
    advertiserReport: advertiserReport,
    analysisData: analysisData,
    companyName: companyName,
    currentUser: currentUser,
    datalabData: datalabData,
    datalabLoading: datalabLoading,
    handleNavigateToClient: handleNavigateToClient,
    htmlDetailResult: htmlDetailResult,
    htmlReviewData: htmlReviewData,
    lastHtmlRef: lastHtmlRef,
    loadProducts: loadProducts,
    products: products,
    rankCheckResult: rankCheckResult,
    relatedData: relatedData,
    scrollTo: scrollTo,
    searchLoading: searchLoading,
    searchedKeyword: searchedKeyword,
    searchedProductUrl: searchedProductUrl,
    sections: sections,
    setRankCheckResult: setRankCheckResult,
    shopProducts: shopProducts,
    volumeData: volumeData
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
};

// 앱 렌더링 (ErrorBoundary로 감싸서 빈 화면 방지)
var root = ReactDOM.createRoot(document.getElementById('root'));
root.render(React.createElement(window.ErrorBoundary, null, React.createElement(App, null)));
