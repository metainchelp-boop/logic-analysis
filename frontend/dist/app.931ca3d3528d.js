
;/* ===== js/utils.js ===== */
/* ===== 로직 분석 — API 헬퍼 & 유틸리티 ===== */

// ===== 앱 버전 (한 곳에서 관리) =====
var APP_VERSION = window.APP_VERSION = 'v7.0.0';

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
      // ⚠️ FastAPI 422(요청 형식 오류)는 detail 이 **객체 배열**이라, 화면들이
      //    toast.error(res.detail) 하면 「[object Object]」만 뜬다(2026-08-05 신고).
      //    detail 을 여기서 한 번만 사람이 읽을 문장으로 바꿔 전 화면을 함께 고친다.
      if (body && typeof body === 'object' && body.detail && typeof body.detail !== 'string') {
        body.detailRaw = body.detail; // 원문 보존(진단용)
        var d = body.detail;
        try {
          if (Array.isArray(d)) {
            body.detail = d.map(function (x) {
              var where = Array.isArray(x && x.loc) ? x.loc.filter(function (v) {
                return v !== 'body';
              }).join('.') : '';
              var msg = x && (x.msg || x.message) || '형식 오류';
              return where ? where + ': ' + msg : msg;
            }).join(' · ');
          } else {
            body.detail = d && (d.msg || d.message) || JSON.stringify(d);
          }
        } catch (e) {
          body.detail = '요청 형식 오류 (' + status + ')';
        }
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
  },
  patch: function (url, body) {
    return fetch(API_BASE + url, {
      method: 'PATCH',
      headers: _authHeaders({
        'Content-Type': 'application/json'
      }),
      body: JSON.stringify(body)
    }).then(_handleResponse).catch(_handleNetworkError);
  }
};

// 숫자 포맷팅
function fmt(n) {
  return n != null ? Number(n).toLocaleString() : '-';
}

// 리뷰 실측 앵커 — '자사 상품' 월판매·월매출 단일 계산(모든 섹션 공통).
//   판매량 추정 배너·시장 규모 보정이 같은 값을 쓰도록 여기서 한 번만 계산한다.
//   가정: 식품 평균 리뷰 작성률 11.6% · 운영 12개월. (rc/rate=누적판매, ÷12=월판매)
window.REVIEW_WRITE_RATE = 0.116;
window.reviewAnchorEstimate = function reviewAnchorEstimate(reviewCount, price) {
  var rc = Number(reviewCount) || 0;
  if (rc <= 0) return null;
  var rate = window.REVIEW_WRITE_RATE;
  var cumSales = Math.round(rc / rate);
  var monthlyUnits = Math.round(cumSales / 12);
  var p = Number(price) || 0;
  return {
    reviewCount: rc,
    cumSales: cumSales,
    monthlyUnits: monthlyUnits,
    monthlyRevenue: p > 0 ? monthlyUnits * p : null
  };
};

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
 *
 * 플레이스 추적도 같은 빌더를 쓴다(2026-08-04 — 스토어와 동일 퀄리티). additive 옵션(미지정 시 기존과 동일):
 *   typeHeader:        표 3번째 컬럼 제목(기본 '유형' — 플레이스는 '상태')
 *   row.type_label:    3번째 컬럼 값(기본 check_type 수동/자동 — 플레이스는 노출/미노출/미확인)
 *   row.rank_null_label: 순위 없음 표기(기본 '미노출' — 플레이스는 '–', 상태 컬럼이 사유를 설명)
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
    ctx.fillText(opts.typeHeader || '유형', colX[2] + 12, tableY + 22);
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
      var rankText = r.rank_position ? r.rank_position + '위' : r.rank_null_label || '미노출';
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
      ctx.fillText(r.type_label || (r.check_type === 'manual' ? '수동' : '자동'), colX[2] + 12, rowY + 20);
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

;/* ===== js/report-capture.js ===== */
/* report-capture.js — 보고서 내보내기 공용 캡처 빌더 (v6.6)
 *
 * ReportSection(수동 HTML 내보내기)과 App(업체 자동저장·저장 보고서 다운로드)이
 * 서로 다른 캡처 함수를 쓰면서 제거 목록이 어긋나 직원용 UI("업체에 저장하시겠습니까",
 * 보고서 내보내기 폼, 추적 안내, 빈 목차 띠, 앱 푸터)가 광고주 전달본에 박제되던 문제를
 * 단일 빌더로 원천 차단한다. 두 경로 모두 이 파일 하나만 수정하면 함께 반영된다.
 *
 * 무손실 원칙: 화면 DOM은 절대 건드리지 않고(clone만 조작), 빌드 실패 시 ''를
 * 반환해 호출부가 기존 실패 처리(알림)로 안전하게 빠지게 한다. */
(function () {
  'use strict';

  /* 전달본에서 제거할 직원용/화면 전용 요소 — 두 캡처 경로 공통(단일 출처) */
  var REMOVE_SELECTORS = ['#sec-report', /* 보고서 내보내기 폼 */
  '#sec-notify', /* 알림 설정 */
  '#sec-save-client', /* 업체 등록/저장 */
  '.anchor-nav-wrap', /* 모바일 목차 껍데기(버튼 제거 후 빈 띠로 남던 유령 요소) */
  '.anchor-nav', '.topbar', '.footer', /* 앱 푸터(버전 문자열) — 전달본은 report-footer 하나만 사용 */
  '.no-export'];

  /* 목차 카드용 디바이더 색 (1~6장 순서 — SectionDivider 호출 색과 동일) */
  var DIVIDER_COLORS = ['#4f46e5', '#0ea5e9', '#ef4444', '#059669', '#7c3aed', '#1e293b'];
  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  /* AI 종합 분석 진행 상태 — AiFeedbackAllSection이 심는 숨김 마커(.ai-state) 판독
   * 'done'=완료 / 'loading'=진행 중 / 'idle'=미시작·오류 / 'none'=섹션 없음 */
  function aiState() {
    try {
      var el = document.querySelector('#sec-ai-feedback .ai-state');
      if (el) return el.getAttribute('data-state') || 'idle';
      return document.getElementById('sec-ai-feedback') ? 'idle' : 'none';
    } catch (e) {
      return 'none';
    }
  }

  /* 차트 canvas → 이미지 치환 + 래퍼 높이 해제(겹침 방지) — 기존 두 경로의 검증된 로직 그대로 */
  function canvasToImages(srcRoot, clone) {
    try {
      var oc = srcRoot.querySelectorAll('canvas');
      var cc = clone.querySelectorAll('canvas');
      for (var i = 0; i < cc.length; i++) {
        var du = '';
        try {
          var ch = window.Chart && window.Chart.getChart ? window.Chart.getChart(oc[i]) : null;
          if (ch) du = ch.toBase64Image('image/png', 1);
        } catch (e1) {}
        if (!du && oc[i] && oc[i].toDataURL) {
          try {
            du = oc[i].toDataURL('image/png');
          } catch (e2) {}
        }
        if (!du) continue;
        var img = document.createElement('img');
        img.src = du;
        img.style.cssText = 'width:100%;height:auto;display:block;margin-bottom:14px;';
        if (cc[i].parentNode) cc[i].parentNode.replaceChild(img, cc[i]);
        var wrap = img.parentNode; /* ChartCanvas가 만든 position:relative;height 고정 래퍼 */
        if (wrap && wrap.style) {
          wrap.style.height = 'auto';
          wrap.style.minHeight = '0';
          wrap.style.position = 'static';
        }
        var box = img.closest && img.closest('.chartbox') || wrap;
        if (box && box.style) {
          box.style.height = 'auto';
          box.style.minHeight = '0';
          box.style.overflow = 'visible';
          box.style.marginBottom = '18px';
        }
      }
    } catch (eC) {}
  }

  /* AI 섹션 미완료 시 → 로딩 문구 박제 대신 '별도 전달' 안내 카드로 대체 */
  function replaceUnfinishedAi(clone) {
    try {
      if (aiState() === 'done') return;
      var aiSec = clone.querySelector('#sec-ai-feedback');
      if (!aiSec || !aiSec.parentNode) return;
      var note = document.createElement('div');
      note.className = 'section';
      var inner = document.createElement('div');
      inner.className = 'container';
      var card = document.createElement('div');
      card.className = 'card';
      card.style.cssText = 'padding:18px 22px;background:#f5f3ff;border:1px solid #ddd6fe;font-size:13px;color:#4c1d95;line-height:1.7;';
      card.textContent = '🤖 METAINC AI 종합 분석 리포트는 분석 완료 후 담당자가 별도로 전달드립니다.';
      inner.appendChild(card);
      note.appendChild(inner);
      aiSec.parentNode.replaceChild(note, aiSec);
    } catch (eA) {}
  }

  /* 실제 렌더된 섹션 디바이더 기준 정적 목차 카드 생성 (표지 아래 삽입)
   * 화면의 좌측 목차(report-toc)는 캡처 범위 밖이라 전달본에서 사라지던 문제 보완 */
  function insertToc(clone) {
    try {
      var divs = clone.querySelectorAll('.report-divider');
      if (divs.length < 2) return; /* 구분 1개 이하면 목차 무의미 */
      var toc = document.createElement('div');
      toc.className = 'section';
      var cont = document.createElement('div');
      cont.className = 'container';
      var card = document.createElement('div');
      card.className = 'card';
      card.style.cssText = 'padding:16px 22px;';
      var title = document.createElement('div');
      title.style.cssText = 'font-size:13px;font-weight:800;color:#0f172a;margin-bottom:10px;';
      title.textContent = '📑 목차';
      card.appendChild(title);
      var grid = document.createElement('div');
      grid.className = 'rpt-grid';
      grid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;';
      for (var i = 0; i < divs.length; i++) {
        var d = divs[i];
        var id = 'rpt-part-' + (i + 1);
        d.id = id;
        /* SectionDivider 구조: .report-divider > div > [아이콘, div > [라벨, 부제]] */
        var label = '',
          sub = '';
        try {
          var txtBox = d.children[0] && d.children[0].children[1];
          if (txtBox) {
            label = (txtBox.children[0] && txtBox.children[0].textContent || '').trim();
            sub = (txtBox.children[1] && txtBox.children[1].textContent || '').trim();
          }
        } catch (eL) {}
        if (!label) label = (d.textContent || '').trim().slice(0, 30);
        var a = document.createElement('a');
        a.href = '#' + id;
        a.style.cssText = 'display:flex;align-items:baseline;gap:8px;text-decoration:none;color:#334155;font-size:12.5px;font-weight:700;line-height:1.5;';
        var dot = document.createElement('span');
        dot.style.cssText = 'width:8px;height:8px;border-radius:3px;flex:none;align-self:center;background:' + (DIVIDER_COLORS[i] || '#4f46e5') + ';';
        a.appendChild(dot);
        var tx = document.createElement('span');
        tx.textContent = label;
        a.appendChild(tx);
        if (sub) {
          var sb = document.createElement('span');
          sb.style.cssText = 'font-size:10.5px;color:#94a3b8;font-weight:500;';
          sb.textContent = sub;
          a.appendChild(sb);
        }
        grid.appendChild(a);
      }
      card.appendChild(grid);
      cont.appendChild(card);
      toc.appendChild(cont);
      /* 표지(.report-cover) 바로 다음, 없으면 맨 앞 */
      var cover = clone.querySelector('.report-cover');
      if (cover && cover.parentNode === clone && cover.nextSibling) clone.insertBefore(toc, cover.nextSibling);else if (cover && cover.parentNode) cover.parentNode.insertBefore(toc, cover.nextSibling);else clone.insertBefore(toc, clone.firstChild);
    } catch (eT) {}
  }

  /* 직원용/인터랙티브 요소 제거 + 입력값 평문화 + 반응형 클래스 부여 + 원격 이미지 안전화 */
  function cleanup(clone) {
    REMOVE_SELECTORS.forEach(function (sel) {
      try {
        clone.querySelectorAll(sel).forEach(function (el) {
          el.remove();
        });
      } catch (e) {}
    });
    clone.querySelectorAll('button, .btn').forEach(function (b) {
      b.remove();
    });
    clone.querySelectorAll('input, select, textarea').forEach(function (inp) {
      var span = document.createElement('span');
      span.textContent = inp.value || '';
      span.style.fontWeight = '600';
      if (inp.parentNode) inp.parentNode.replaceChild(span, inp);
    });
    /* 인라인 grid/flex → 모바일 1열 전환용 훅 클래스 */
    clone.querySelectorAll('[style*="grid-template-columns"]').forEach(function (el) {
      el.classList.add('rpt-grid');
    });
    clone.querySelectorAll('[style*="display: flex"], [style*="display:flex"]').forEach(function (el) {
      el.classList.add('rpt-flex');
    });
    /* 원격 이미지(경쟁사 썸네일 등) — CDN 만료·오프라인 열람 시 깨진 아이콘 대신 자동 숨김 */
    clone.querySelectorAll('img').forEach(function (im) {
      var src = im.getAttribute('src') || '';
      if (/^https?:/i.test(src)) im.setAttribute('onerror', "this.style.display='none'");
    });
  }
  function collectCss() {
    var cssText = '';
    try {
      var sheets = document.styleSheets;
      for (var i = 0; i < sheets.length; i++) {
        try {
          var rules = sheets[i].cssRules || sheets[i].rules;
          for (var j = 0; j < rules.length; j++) cssText += rules[j].cssText + '\n';
        } catch (e) {/* cross-origin 무시 */}
      }
    } catch (e2) {}
    /* 전달본 자체 반응형 보정 — rpt-grid/rpt-flex는 전달본에서만 쓰는 훅이므로 여기서 정의 보장 */
    cssText += '\n@media (max-width: 640px) {\n' + '  .rpt-grid { grid-template-columns: 1fr !important; }\n' + '  .rpt-flex { flex-wrap: wrap !important; }\n' + '}\n';
    return cssText;
  }

  /* 전체 빌드 — opts: { title(필수, 헤더 제목), managerName(선택, 담당자명) }
   * 성공 시 완성 HTML 문자열, 실패 시 '' */
  function buildHtml(opts) {
    try {
      opts = opts || {};
      var srcMain = document.querySelector('.report-main') || document.getElementById('root') && document.getElementById('root').children[0];
      if (!srcMain) return '';
      var clone = srcMain.cloneNode(true);
      canvasToImages(srcMain, clone);
      replaceUnfinishedAi(clone);
      cleanup(clone);
      insertToc(clone);
      var cssText = collectCss();
      var dateStr = new Date().toLocaleDateString('ko-KR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      });
      var headerText = esc(opts.title || '로직 분석 보고서');
      var manager = esc(opts.managerName || '');
      var metaLine = esc(dateStr) + ' · 메타아이앤씨 로직분석' + (manager ? ' · 담당 ' + manager : '');
      var contact = (manager ? '담당 ' + manager + ' · ' : '') + '고객센터 02-2082-2005 · 메타아이앤씨';
      return '<!DOCTYPE html>\n<html lang="ko">\n<head>\n' + '<meta charset="UTF-8">\n'
      /* 운영자 지시: 모바일에서도 PC 화면 축소판으로 열람(1열 재배치 아님) — width=1200 고정 */ + '<meta name="viewport" content="width=1200">\n' + '<title>' + headerText + ' - ' + esc(dateStr) + '</title>\n' + '<style>\n' + '* { margin: 0; padding: 0; box-sizing: border-box; }\n' + 'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", sans-serif; background: #f8fafc; color: #1e293b; }\n'
      /* 표지: 본문 인디고 토큰과 동일 계열(#4f46e5→#7c3aed)로 단일 브랜드색 통일 (구 보라 #6C5CE7 폐기) */ + '.report-header { background: linear-gradient(135deg, #4f46e5, #7c3aed); color: #fff; padding: 38px 20px 34px; text-align: center; }\n' + '.report-header .rh-eyebrow { font-size: 11px; font-weight: 700; letter-spacing: 0.18em; opacity: 0.8; margin-bottom: 8px; }\n' + '.report-header h1 { font-size: 24px; margin-bottom: 8px; letter-spacing: -0.3px; }\n' + '.report-header p { font-size: 13.5px; opacity: 0.88; }\n' + '.report-cta { max-width: 1200px; margin: 28px auto 0; padding: 0 20px; }\n' + '.report-cta .in { background: #1e293b; color: #e2e8f0; border-radius: 16px; padding: 22px 26px; }\n' + '.report-cta .t { font-size: 16px; font-weight: 800; color: #fff; margin-bottom: 6px; }\n' + '.report-cta .d { font-size: 12.5px; color: #cbd5e1; line-height: 1.7; }\n' + '.report-cta .c { display: inline-block; margin-top: 12px; background: #4f46e5; color: #fff; font-size: 13px; font-weight: 800; border-radius: 10px; padding: 9px 18px; }\n' + '.report-footer { text-align: center; padding: 26px 16px 30px; color: #94a3b8; font-size: 12px; border-top: 1px solid #e2e8f0; margin-top: 32px; line-height: 1.8; }\n' + '.report-footer .rf-main { font-size: 13px; font-weight: 700; color: #475569; }\n' + cssText + '\n@media print { .report-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }\n' + '</style>\n</head>\n<body>\n' + '<div class="report-header">\n' + '  <div class="rh-eyebrow">METAINC · 로직분석</div>\n' + '  <h1>' + headerText + '</h1>\n' + '  <p>' + metaLine + '</p>\n' + '</div>\n' + '<div class="report-content" style="max-width:1200px; margin:0 auto; padding:20px;">\n' + clone.outerHTML + '\n' + '</div>\n' + '<div class="report-cta"><div class="in">\n' + '  <div class="t">다음 단계를 함께 진행해요</div>\n' + '  <div class="d">본 보고서의 실행 로드맵(즉시 → 1주 → 1개월)을 담당자와 확정하세요. 궁금하신 점은 언제든 문의 가능합니다.</div>\n' + '  <span class="c">' + esc(contact) + '</span>\n' + '</div></div>\n' + '<div class="report-footer">\n' + '  <div class="rf-main">' + esc(contact) + '</div>\n' + '  <div>본 보고서의 수치는 네이버 공식 API 기준이며, 시장 상황에 따라 변동될 수 있습니다. © 2026 메타아이앤씨</div>\n' + '</div>\n' + '</body>\n</html>';
    } catch (e) {
      try {
        console.error('[ReportCapture] build 실패:', e);
      } catch (e2) {}
      return '';
    }
  }
  window.ReportCapture = {
    buildHtml: buildHtml,
    aiState: aiState,
    REMOVE_SELECTORS: REMOVE_SELECTORS
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
          background: '#3b82f6',
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
          background: '#3b82f6',
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
    IND: '#3b82f6',
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
          /* devicePixelRatio 최소 2: 내보내기(캔버스→PNG) 시 저배율 모니터에서도 선명한 2배 해상도 확보 */
          options: Object.assign({
            responsive: true,
            maintainAspectRatio: false,
            devicePixelRatio: Math.max(window.devicePixelRatio || 1, 2)
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
  var htmlReviewData = props.htmlReviewData;
  var datalabData = props.datalabData;
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
    // R5: AI가 방어자/신규진입을 판단하고 시즌·리뷰격차를 인용하도록 자기상태·리뷰·시즌을 주입
    if (analysisData.reviewAnalysis) sections.review = analysisData.reviewAnalysis;
    if (datalabData && (datalabData.season || datalabData.trend || datalabData.growth)) {
      sections.season = {
        season: datalabData.season,
        trend: datalabData.trend,
        growth: datalabData.growth
      };
    }
    var _myRank = advertiserReport && advertiserReport.ranking && advertiserReport.ranking.current_rank != null ? advertiserReport.ranking.current_rank : analysisData.targetProductInfo && analysisData.targetProductInfo.rank != null ? analysisData.targetProductInfo.rank : null;
    var _myReviews = htmlReviewData && htmlReviewData.reviewCount != null ? htmlReviewData.reviewCount : null;
    var _top5Reviews = analysisData.reviewAnalysis && analysisData.reviewAnalysis.reviewCount ? analysisData.reviewAnalysis.reviewCount.top5 : null;
    sections.mystatus = {
      myRank: _myRank,
      myActualReviews: _myReviews,
      top5AvgReviews: _top5Reviews,
      isDefender: _myRank != null && _myRank <= 10 || _myReviews != null && _myReviews >= 100
    };
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
  }, /* 내보내기용 숨김 상태 마커 — ReportCapture가 읽어 미완료 시 로딩 문구 박제를 차단 */
  React.createElement('span', {
    className: 'ai-state',
    style: {
      display: 'none'
    },
    'data-state': loading ? 'loading' : feedbacks ? 'done' : 'idle'
  }), React.createElement('div', {
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
  }, feedbacks ? '다시 분석' : '✨ AI 종합 분석'), /* no-export: 상태 마커가 실패해도 로딩 문구만은 전달본에서 항상 제거(이중 방어) */
  loading && React.createElement('span', {
    className: 'no-export',
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
      // 크롬 확장 브리지 — 수집된 상품 HTML·URL 자동 주입 (확장 미사용 시 미전달)
      if (typeof initialValues.html === 'string' && initialValues.html) {
        setHtmlInput(initialValues.html);
        setHtmlExpanded(true);
      }
      if (typeof initialValues.productUrl === 'string' && initialValues.productUrl) setManualUrl(initialValues.productUrl);
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
  }, "업체명 ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#dc2626'
    }
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "search-input",
    type: "text",
    placeholder: "보고서 표지용 (필수)",
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
  }, "키워드 ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#dc2626'
    }
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "search-input",
    type: "text",
    placeholder: "분석할 키워드 (예: 무선 이어폰)",
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
  }, "HTML 붙여넣기 ", /*#__PURE__*/React.createElement("span", {
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
  }, "상품 상세페이지 HTML → 상품 URL·리뷰수·평점·찜수 자동 추출")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("textarea", {
    placeholder: "상품 상세페이지 HTML 전체를 붙여넣으세요 (필수) — Ctrl+U 소스보기 후 전체 복사. 상품 URL은 자동 인식됩니다.",
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
  }, "초기화")))), /*#__PURE__*/React.createElement("button", {
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
  }), " 분석 중...") : '분석 실행')), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'block',
      fontSize: 11,
      fontWeight: 600,
      color: '#6b7280',
      marginBottom: 4,
      letterSpacing: '0.02em'
    }
  }, "상품 URL 직접 입력", /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      color: '#94a3b8',
      fontWeight: 400,
      marginLeft: 6
    }
  }, "선택 — HTML에서 URL 자동 인식이 안 될 때만 상품 페이지 주소를 붙여넣으세요")), /*#__PURE__*/React.createElement("input", {
    className: "search-input",
    type: "text",
    placeholder: "예: https://smartstore.naver.com/스토어/products/1234567890 (비워두면 HTML에서 자동 추출)",
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
  }, "🔖"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontWeight: 700,
      color: '#1e40af'
    }
  }, "★ 가장 쉬운 방법: 북마클릿 사용"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: '#3730a3',
      marginLeft: 8
    }
  }, "아래 버튼을 북마크바로 ", /*#__PURE__*/React.createElement("strong", null, "드래그"), " → 스마트스토어에서 클릭 한 번에 HTML 복사")), /*#__PURE__*/React.createElement("a", {
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
  }, "📎 HTML 복사 (북마크바로 드래그)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      color: '#64748b',
      flexShrink: 0
    }
  }, "← 이 파란 버튼을 위쪽 북마크바에 끌어다 놓으세요")))));
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
/* RankTrackingSection — 순위 추적
 * analysisOnly: 스토어 분석 화면 전용 모드 — 키워드별 노출 분석·1회성 조회만 렌더
 * (추적 상품 목록·상품 등록 폼은 📊 키워드 순위 탭에서 관리, 2026-08-04 탭 분리) */
window.RankTrackingSection = function RankTrackingSection({
  products,
  refreshProducts,
  searchedKeyword,
  searchedProductUrl,
  cachedProductName,
  relatedKeywords,
  onNavigateToClient,
  canEdit,
  onRankResult,
  analysisOnly,
  onOpenRankTab
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
  const [exposureFailed, setExposureFailed] = useState(false);
  const [exposureNonce, setExposureNonce] = useState(0);
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
    var key = 'exposure::' + searchedProductUrl + '::' + cachedProductName + '::' + _extraKws.length + '::' + exposureNonce;
    if (lastExposureKey.current === key) return;
    lastExposureKey.current = key;
    var cancelled = false;
    var retries = 0;
    setExposureLoading(true);
    setExposureResult(null);
    setExposureFailed(false);
    function retryOrFail() {
      if (cancelled) return;
      // 네이버 조회 지연/일시 실패 → 최대 1회 자동 재시도 후 폴백(빈 상태로 사라지지 않게)
      if (retries < 1) {
        retries += 1;
        setTimeout(function () {
          if (!cancelled) attempt();
        }, 2500);
      } else {
        setExposureLoading(false);
        setExposureFailed(true);
      }
    }
    function attempt() {
      // 클라이언트 타임아웃(무한 로딩 방지): BE 예산 18s + 네트워크 여유를 두고 32초.
      // (첫 시도가 BE 예산 안에 끝나 불필요한 재시도로 크롤을 두 번 하지 않게 함)
      var timeoutP = new Promise(function (_res, rej) {
        setTimeout(function () {
          rej(new Error('timeout'));
        }, 32000);
      });
      Promise.race([api.post('/rank/keyword-exposure', {
        product_url: searchedProductUrl,
        keyword: searchedKeyword,
        product_name: cachedProductName,
        extra_keywords: _extraKws
      }), timeoutP]).then(function (res) {
        if (cancelled) return;
        if (res && res.success && res.data) {
          setExposureResult(res.data);
          setExposureFailed(false);
          setExposureLoading(false);
        } else {
          retryOrFail();
        }
      }).catch(function () {
        retryOrFail();
      });
    }
    attempt();
    return function () {
      cancelled = true;
    };
  }, [searchedProductUrl, searchedKeyword, cachedProductName, relatedKeywords, exposureNonce]);

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

  /* 키워드 개별 삭제 (건의 2026-07-22, 이예은) — 남기는 키워드의 이력은 유지.
     마지막 1개는 삭제 불가(키워드 0개 상품 방지 → 상품 삭제로 정리). */
  const handleDeleteKeyword = async (keywordId, keyword, siblingCount) => {
    if (siblingCount <= 1) {
      try {
        toast.warn('마지막 키워드는 삭제할 수 없습니다. 상품 전체를 정리하려면 상품 삭제를 이용하세요.');
      } catch (e) {}
      return;
    }
    if (!confirm("'" + keyword + "' 추적을 삭제할까요?\n이 키워드의 순위 이력도 함께 삭제됩니다. (상품과 다른 키워드는 유지)")) return;
    try {
      await api.del('/keywords/' + keywordId);
      try {
        toast.success("'" + keyword + "' 추적이 삭제되었습니다.");
      } catch (e) {}
      refreshProducts();
    } catch (e) {
      toast.error('키워드 삭제 실패: ' + (e.message || '네트워크 오류'));
    }
  };

  /* 키워드 삭제 ✕ 버튼 (canEdit일 때만) — 표의 '관리' 열 셀. 마지막 1개면 비활성 */
  var renderKeywordDeleteCell = function (k, siblingCount, pad) {
    var disabled = siblingCount <= 1;
    return React.createElement('td', {
      style: {
        padding: pad || '6px 10px',
        textAlign: 'center',
        whiteSpace: 'nowrap'
      },
      onClick: function (e) {
        e.stopPropagation();
      } /* 셀 클릭이 행 펼침을 토글하지 않게 */
    }, React.createElement('button', {
      disabled: disabled,
      title: disabled ? '마지막 키워드는 삭제할 수 없습니다 — 상품 삭제를 이용하세요' : '이 키워드 추적 삭제',
      onClick: function (e) {
        e.stopPropagation();
        handleDeleteKeyword(k.id, k.keyword, siblingCount);
      },
      style: {
        border: '1px solid ' + (disabled ? '#e2e8f0' : '#fecaca'),
        background: disabled ? '#f8fafc' : '#fff',
        color: disabled ? '#cbd5e1' : '#dc2626',
        borderRadius: 8,
        width: 26,
        height: 26,
        fontSize: 12,
        fontWeight: 800,
        lineHeight: 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
        padding: 0
      }
    }, '✕'));
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
          border: '1px solid ' + (on ? '#3b82f6' : '#e2e8f0'),
          background: on ? '#3b82f6' : '#fff',
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
                return ctx.parsed.y != null ? ctx.parsed.y + '위' : '200위 밖';
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
    }, '※ 선이 위로 갈수록 상위 노출. 끊긴 구간은 200위 밖입니다.'));
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
  }, "📍"), "키워드별 노출 순위", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅ 실측")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "상품명에서 추출한 키워드별로 네이버 쇼핑 검색 순위를 조회한 결과 (검색 범위: 상위 200개 상품)")), analysisOnly && onOpenRankTab && /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary btn-sm",
    onClick: () => {
      try {
        sessionStorage.setItem('logic_rank_ctx', JSON.stringify({
          searchedKeyword: searchedKeyword || '',
          searchedProductUrl: searchedProductUrl || '',
          cachedProductName: cachedProductName || '',
          relatedKeywords: relatedKeywords || []
        }));
      } catch (e) {}
      onOpenRankTab();
    }
  }, "📊 키워드 순위 탭에서 관리 →"), !analysisOnly && canEdit !== false && /*#__PURE__*/React.createElement("button", {
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
  }, "상품 URL"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "https://smartstore.naver.com/스토어명/products/12345",
    value: newUrl,
    onChange: e => setNewUrl(e.target.value)
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      marginTop: 4
    }
  }, "네이버 스마트스토어 상품 페이지 URL을 입력하세요")), /*#__PURE__*/React.createElement("div", {
    className: "form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "form-label"
  }, "추적 키워드 (쉼표로 구분)"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "예: 스마트워치, 블루투스 이어폰",
    value: newKeywords,
    onChange: e => setNewKeywords(e.target.value)
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      marginTop: 4
    }
  }, "여러 키워드는 쉼표(,)로 구분해서 입력하세요 (최대 10개)")), /*#__PURE__*/React.createElement("button", {
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
  }, "키워드별 노출 순위 분석 중..."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#94a3b8',
      marginTop: 4
    }
  }, "상품명에서 키워드를 추출하여 각각 순위를 조회하고 있습니다")), exposureResult && !exposureLoading && function () {
    // R6: 노출률·노출/400위밖 리스트는 '내 상품 키워드'(source!=='related')만 — 무관 연관어 제외
    var exposed = exposureResult.results.filter(function (r) {
      return r.rank != null && r.source !== 'related';
    });
    var unexposed = exposureResult.results.filter(function (r) {
      return r.rank == null && r.source !== 'related';
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
    }, "노출 ", exposureResult.exposed_count, "개"), /*#__PURE__*/React.createElement("span", {
      className: "ps ps-r"
    }, "200위 밖 ", unexposed.length, "개"), /*#__PURE__*/React.createElement("span", {
      className: "ps ps-n"
    }, "전체 ", exposureResult.total_keywords, "개")), /*#__PURE__*/React.createElement("div", {
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
    }, "노출 키워드")), /*#__PURE__*/React.createElement("div", {
      className: "ratecard"
    }, /*#__PURE__*/React.createElement("div", {
      className: "v",
      style: {
        color: 'var(--red)'
      }
    }, unexposed.length), /*#__PURE__*/React.createElement("div", {
      className: "k"
    }, "200위 밖 키워드")), /*#__PURE__*/React.createElement("div", {
      className: "ratecard"
    }, /*#__PURE__*/React.createElement("div", {
      className: "v",
      style: {
        color: 'var(--pur)'
      }
    }, exposureRate, "%"), /*#__PURE__*/React.createElement("div", {
      className: "k"
    }, "노출률"))), exposureResult.recommended && exposureResult.recommended.length > 0 && /*#__PURE__*/React.createElement("div", {
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
    }, "💡 노출 중인 추천 키워드"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: '#64748b',
        marginBottom: 10,
        lineHeight: 1.5
      }
    }, "검색 키워드가 상위 200위 밖이어도, 아래 키워드로는 지금 노출 중입니다 — 상품명·태그·광고에 활용해 노출을 확보하세요."), /*#__PURE__*/React.createElement("div", {
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
      }, r.rank, "위"));
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
    }, /*#__PURE__*/React.createElement("span", null, "●"), " 노출 키워드"), /*#__PURE__*/React.createElement("div", {
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
      }, r.rank, "위"));
    }), exposed.length === 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: '#94a3b8'
      }
    }, "노출된 키워드가 없습니다")), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 800,
        color: '#ef4444',
        margin: '16px 0 8px',
        display: 'flex',
        alignItems: 'center',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("span", null, "●"), " 200위 밖 키워드"), /*#__PURE__*/React.createElement("div", {
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
    }, "모든 키워드에 노출 중입니다"))), function () {
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
      }, "📉 ", chartTitle ? "'" + chartTitle + "' " : '', "30일 순위 추이 ", /*#__PURE__*/React.createElement("span", {
        className: "badge b-est",
        style: {
          marginLeft: 4
        }
      }, "신규 차트")), kw && kw.id ? renderRankHistoryChart(kw.id, kw.keyword, tp ? {
        storeName: tp.store_name,
        storeUrl: tp.product_url
      } : {}) : /*#__PURE__*/React.createElement("div", {
        style: {
          fontSize: 12,
          color: '#94a3b8',
          padding: '6px 2px',
          lineHeight: 1.7
        }
      }, "지속적인 30일 순위 추이는 ", /*#__PURE__*/React.createElement("b", {
        style: {
          color: '#475569'
        }
      }, "관리자에 상품 등록(추적 요청)"), " 후 매일 스냅샷으로 자동 기록됩니다. 등록되면 이 자리에 추이 그래프가 표시됩니다."));
    }());
  }(), exposureFailed && !exposureLoading && !exposureResult && /*#__PURE__*/React.createElement("div", {
    className: "card fade-in",
    style: {
      textAlign: 'center',
      padding: '22px 16px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 26,
      marginBottom: 8
    }
  }, "🔄"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: '#64748b',
      lineHeight: 1.6,
      marginBottom: 12
    }
  }, "일시적으로 키워드별 노출 순위를 불러오지 못했습니다(네이버 조회 지연). 순위 데이터는 유효하며, 다시 조회하면 표시됩니다."), /*#__PURE__*/React.createElement("button", {
    onClick: function () {
      lastExposureKey.current = '';
      setExposureFailed(false);
      setExposureNonce(function (n) {
        return n + 1;
      });
    },
    style: {
      padding: '9px 18px',
      borderRadius: 10,
      border: 'none',
      background: 'linear-gradient(135deg,#3b82f6,#3b82f6)',
      color: '#fff',
      fontSize: 13,
      fontWeight: 700,
      cursor: 'pointer'
    }
  }, "🔄 다시 조회")), function () {
    if (analysisOnly) return null;
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
      icon: "📦",
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
            color: onNavigateToClient ? '#3b82f6' : 'inherit'
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
        }, React.createElement('table', null, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', null, '키워드'), React.createElement('th', null, '현재 순위'), React.createElement('th', null, '페이지'), React.createElement('th', null, '최근 체크'), canEdit !== false && React.createElement('th', {
          style: {
            width: 52,
            textAlign: 'center'
          }
        }, '관리'))), React.createElement('tbody', null, p.keywords.map(function (k) {
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
          }, '200위 밖')), React.createElement('td', null, k.latest_rank ? Math.ceil(k.latest_rank / 40) + 'P' : '-'), React.createElement('td', {
            style: {
              fontSize: 12,
              color: '#94a3b8'
            }
          }, k.last_checked ? new Date(k.last_checked).toLocaleString('ko') : '-'), canEdit !== false && renderKeywordDeleteCell(k, p.keywords.length, '8px 8px'));
          if (!isOpen) return rowEl;
          var chartRow = React.createElement('tr', {
            key: k.id + '-chart'
          }, React.createElement('td', {
            colSpan: canEdit !== false ? 5 : 4,
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
      }, '200위 밖');
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
          color: '#3b82f6',
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
      }, '최근 체크'), canEdit !== false && React.createElement('th', {
        style: {
          textAlign: 'center',
          padding: '6px 10px',
          color: '#94a3b8',
          fontWeight: 700,
          fontSize: 11,
          width: 44
        }
      }, '관리'))), React.createElement('tbody', null, kws.map(function (k) {
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
        }, k.last_checked ? new Date((k.last_checked || '').replace(' ', 'T')).toLocaleString('ko') : '-'), canEdit !== false && renderKeywordDeleteCell(k, kws.length, '6px 10px'));
        if (!kOpen) return krow;
        return [krow, React.createElement('tr', {
          key: k.id + '-c'
        }, React.createElement('td', {
          colSpan: canEdit !== false ? 4 : 3,
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

;/* ===== js/components/KeywordRankPage.jsx ===== */
/* KeywordRankPage — 📊 키워드 순위 탭 (2026-08-04 탭 분리 1차)
 *
 * 구조(시안 v2 확정): 랜딩 = 광고주 업체 목록(업체별 롤업 KPI·검색·주의 배지,
 * 행 클릭 → 상세) / 상세 = 그 업체의 키워드 보드(순위+전일 Δ·7일 스파크라인·
 * 상태 칩·검색량·페이지). 하단에 기존 RankTrackingSection 을 그대로 마운트해
 * 상품 등록·수동 재확인·1회성 조회 등 기존 기능을 무손실 이전한다.
 * 스토어 분석 → 이 탭 이동 시 sessionStorage 'logic_rank_ctx' 로 검색 컨텍스트를
 * 넘겨받아 노출 확인(1회성 조회)이 이어진다.
 *
 * props: { currentUser, onNavigateToClient(storeName, productUrl) }
 */

/* ---------- 정적 스타일 (렌더 밖) ---------- */
var _krWrap = {
  maxWidth: 1200,
  margin: '0 auto',
  padding: '24px 16px 48px'
};
var _krCard = {
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 14,
  padding: '18px 20px',
  marginBottom: 16
};
var _krKpiGrid = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
  gap: 10,
  marginBottom: 16
};
var _krKpi = {
  background: '#f8fafc',
  border: '1px solid #eef2f6',
  borderRadius: 12,
  padding: '13px 16px'
};
var _krKpiK = {
  fontSize: 11.5,
  fontWeight: 700,
  color: '#94a3b8',
  letterSpacing: '.03em'
};
var _krKpiV = {
  fontSize: 22,
  fontWeight: 800,
  letterSpacing: '-.02em',
  marginTop: 2,
  color: '#0f172a',
  fontVariantNumeric: 'tabular-nums'
};
var _krKpiS = {
  fontSize: 11.5,
  marginTop: 1,
  color: '#94a3b8',
  fontVariantNumeric: 'tabular-nums'
};
var _krTh = {
  textAlign: 'left',
  padding: '9px 12px',
  fontSize: 11.5,
  fontWeight: 700,
  color: '#94a3b8',
  letterSpacing: '.02em',
  borderBottom: '1px solid #e2e8f0',
  whiteSpace: 'nowrap'
};
var _krTd = {
  padding: '11px 12px',
  fontSize: 13,
  color: '#334155',
  borderBottom: '1px solid #f1f5f9',
  verticalAlign: 'middle'
};
function _krChip(kind) {
  var base = {
    display: 'inline-block',
    fontSize: 11.5,
    fontWeight: 800,
    borderRadius: 999,
    padding: '3px 10px',
    whiteSpace: 'nowrap'
  };
  if (kind === 'ok') return Object.assign({}, base, {
    color: '#16a34a',
    background: '#f0fdf4'
  });
  if (kind === 'warn') return Object.assign({}, base, {
    color: '#b45309',
    background: '#fffbeb'
  });
  if (kind === 'info') return Object.assign({}, base, {
    color: '#1d4ed8',
    background: '#eff6ff'
  });
  return Object.assign({}, base, {
    color: '#64748b',
    background: '#f2f4f6'
  });
}
function _krDelta(delta) {
  var base = {
    display: 'inline-block',
    fontSize: 11.5,
    fontWeight: 800,
    borderRadius: 999,
    padding: '2px 8px',
    fontVariantNumeric: 'tabular-nums',
    whiteSpace: 'nowrap'
  };
  if (delta > 0) return {
    style: Object.assign({}, base, {
      color: '#dc2626',
      background: '#fef2f2'
    }),
    label: '▲ ' + delta
  };
  if (delta < 0) return {
    style: Object.assign({}, base, {
      color: '#2563eb',
      background: '#eff6ff'
    }),
    label: '▼ ' + -delta
  };
  return {
    style: Object.assign({}, base, {
      color: '#64748b',
      background: '#f2f4f6'
    }),
    label: delta === 0 ? '—' : 'NEW'
  };
}

/* 7일 스파크라인 — 순위는 낮을수록 좋음(위쪽) */
function _krSparkline(series) {
  var pts = (series || []).filter(function (p) {
    return p.rank !== null && p.rank !== undefined;
  });
  if (pts.length < 2) return React.createElement('span', {
    style: {
      fontSize: 11,
      color: '#cbd5e1'
    }
  }, '—');
  var w = 84,
    h = 26,
    pad = 3;
  var ranks = pts.map(function (p) {
    return p.rank;
  });
  var mn = Math.min.apply(null, ranks),
    mx = Math.max.apply(null, ranks);
  var span = mx - mn || 1;
  var coords = pts.map(function (p, i) {
    var x = pad + (w - pad * 2) * (i / (pts.length - 1));
    var y = pad + (h - pad * 2) * ((p.rank - mn) / span); // 순위↑(숫자↓) = 위
    return x.toFixed(1) + ',' + y.toFixed(1);
  });
  var last = coords[coords.length - 1].split(',');
  var improving = ranks[ranks.length - 1] <= ranks[0];
  var color = improving ? '#16a34a' : '#dc2626';
  return React.createElement('svg', {
    width: w,
    height: h,
    style: {
      display: 'block'
    }
  }, React.createElement('polyline', {
    points: coords.join(' '),
    fill: 'none',
    stroke: color,
    strokeWidth: 1.6,
    strokeLinejoin: 'round',
    strokeLinecap: 'round'
  }), React.createElement('circle', {
    cx: last[0],
    cy: last[1],
    r: 2.4,
    fill: color
  }));
}
window.KeywordRankPage = function KeywordRankPage(props) {
  var useState = React.useState,
    useEffect = React.useEffect,
    useCallback = React.useCallback;
  var currentUser = props.currentUser || {};
  var onNavigateToClient = props.onNavigateToClient;
  var isViewer = currentUser.role === 'viewer';
  var _ov = useState(null);
  var overview = _ov[0],
    setOverview = _ov[1];
  var _ovL = useState(true);
  var ovLoading = _ovL[0],
    setOvLoading = _ovL[1];
  var _sel = useState(null);
  var selected = _sel[0],
    setSelected = _sel[1]; // {id, name}
  var _bd = useState(null);
  var board = _bd[0],
    setBoard = _bd[1];
  var _bdL = useState(false);
  var bdLoading = _bdL[0],
    setBdLoading = _bdL[1];
  var _q = useState('');
  var query = _q[0],
    setQuery = _q[1];
  var _flt = useState('all');
  var filter = _flt[0],
    setFilter = _flt[1]; // all|attention|up|down
  var _bs = useState('rank');
  var boardSort = _bs[0],
    setBoardSort = _bs[1]; // rank|delta|volume|name (2차 확산)
  var _bd2 = useState(7);
  var boardDays = _bd2[0],
    setBoardDays = _bd2[1]; // 추이 기간 7|30
  var _kwi = useState('');
  var kwInput = _kwi[0],
    setKwInput = _kwi[1]; // 추적 키워드 추가 입력
  var _kwb = useState(false);
  var kwBusy = _kwb[0],
    setKwBusy = _kwb[1];
  var _kwm = useState(null);
  var kwMsg = _kwm[0],
    setKwMsg = _kwm[1]; // {ok, text}

  /* 하단 RankTrackingSection 용 — 추적 상품은 이 페이지가 자체 로드 */
  var _pr = useState([]);
  var products = _pr[0],
    setProducts = _pr[1];
  var loadProducts = useCallback(function () {
    api.get('/products').then(function (res) {
      if (res && res.success) setProducts(res.data || []);
    }).catch(function () {});
  }, []);

  /* 스토어 분석 → 탭 이동 핸드오프 (1회 소비) */
  var _ctx = useState(function () {
    try {
      var raw = sessionStorage.getItem('logic_rank_ctx');
      if (raw) {
        sessionStorage.removeItem('logic_rank_ctx');
        return JSON.parse(raw);
      }
    } catch (e) {}
    return null;
  });
  var rankCtx = _ctx[0];

  /* 하단 추적 상품 관리(전체 업체 도구) — 업체 목록에서만, 기본 접힘.
     스토어 분석에서 컨텍스트를 들고 넘어온 경우엔 노출 확인이 이어지도록 자동 펼침 */
  var _tk = useState(!!_ctx[0]);
  var trackingOpen = _tk[0],
    setTrackingOpen = _tk[1];

  /* 키워드 펼침 패널 — 순위 추이 차트(이미지 저장과 동일 데이터) + 기간 선택 + 📸 저장 */
  var _ex = useState(null);
  var expandedKw = _ex[0],
    setExpandedKw = _ex[1];
  var _kd = useState({});
  var kwDays = _kd[0],
    setKwDays = _kd[1]; // { keyword: 7|30|0 }
  var _hc = useState({});
  var histCache = _hc[0],
    setHistCache = _hc[1]; // { keyword: rows(90일) }
  var loadKwHistory = function (client, keyword) {
    if (histCache[keyword]) return;
    api.get('/cd/' + client.id + '/rank-history?keyword=' + encodeURIComponent(keyword) + '&days=90').then(function (res) {
      var rows = res && res.success && res.data || [];
      setHistCache(function (prev) {
        var n = Object.assign({}, prev);
        n[keyword] = rows;
        return n;
      });
    }).catch(function () {
      setHistCache(function (prev) {
        var n = Object.assign({}, prev);
        n[keyword] = [];
        return n;
      });
      try {
        toast.error('순위 이력을 불러오지 못했습니다.');
      } catch (e) {}
    });
  };
  var toggleKw = function (client, keyword) {
    if (expandedKw === keyword) {
      setExpandedKw(null);
      return;
    }
    setExpandedKw(keyword);
    loadKwHistory(client, keyword);
  };
  var _kwPeriodLabel = {
    7: '최근 7일',
    30: '최근 30일',
    0: '전체(90일)'
  };
  var _kwFilterRows = function (rows, days) {
    if (!days) return rows;
    var cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    return rows.filter(function (r) {
      return new Date((r.checked_at || '').replace(' ', 'T')) >= cutoff;
    });
  };
  function renderKwPanel(client, b) {
    var days = kwDays[b.keyword] != null ? kwDays[b.keyword] : 7; // 기본 = 최근 7일
    var all = histCache[b.keyword];
    var rows = all ? _kwFilterRows(all, days) : null;
    var setPeriod = function (d) {
      setKwDays(function (prev) {
        var n = Object.assign({}, prev);
        n[b.keyword] = d;
        return n;
      });
    };
    var header = React.createElement('div', {
      style: {
        display: 'flex',
        gap: 6,
        alignItems: 'center',
        flexWrap: 'wrap',
        marginBottom: 8
      }
    }, [7, 30, 0].map(function (d) {
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
          border: '1px solid ' + (on ? '#3b82f6' : '#e2e8f0'),
          background: on ? '#3b82f6' : '#fff',
          color: on ? '#fff' : '#475569'
        }
      }, _kwPeriodLabel[d]);
    }), React.createElement('button', {
      onClick: function (e) {
        e.stopPropagation();
        window.exportRankHistoryImage({
          rows: all || [],
          storeName: client.name || '업체',
          keyword: b.keyword,
          storeUrl: client.store_url || '',
          days: days
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
    var bodyEl;
    if (!rows) {
      bodyEl = React.createElement('div', {
        style: {
          padding: 8,
          textAlign: 'center',
          fontSize: 12,
          color: '#94a3b8'
        }
      }, '순위 이력 불러오는 중...');
    } else if (rows.length < 2) {
      bodyEl = React.createElement('div', {
        style: {
          padding: 8,
          textAlign: 'center',
          fontSize: 12,
          color: '#94a3b8'
        }
      }, _kwPeriodLabel[days] + ' 추이는 2회 이상의 순위 기록이 필요합니다. (현재 ' + rows.length + '회)');
    } else {
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
      bodyEl = React.createElement(React.Fragment, null, React.createElement('div', {
        style: {
          fontSize: 12,
          fontWeight: 700,
          color: '#0f172a',
          marginBottom: 8
        }
      }, '"' + b.keyword + '" ' + _kwPeriodLabel[days] + ' 순위 추이'), React.createElement(window.ChartCanvas, {
        canvasId: 'cdrank-' + client.id + '-' + encodeURIComponent(b.keyword),
        type: 'line',
        height: 180,
        data: {
          labels: labels,
          datasets: [{
            label: '순위',
            data: data,
            borderColor: '#16a34a',
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
                  return ctx.parsed.y != null ? ctx.parsed.y + '위' : '300위 밖';
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
      }));
    }
    return React.createElement('tr', {
      key: b.keyword + '::panel'
    }, React.createElement('td', {
      colSpan: 8,
      style: {
        padding: '14px 18px 10px',
        background: '#f8fafc',
        borderBottom: '1px solid #e2e8f0'
      }
    }, header, bodyEl));
  }
  var loadOverview = useCallback(function () {
    setOvLoading(true);
    api.get('/cd/rank-overview').then(function (res) {
      if (res && res.success) setOverview(res);else if (res && res.detail) toast.error(res.detail);
    }).catch(function () {
      try {
        toast.error('업체 순위 현황을 불러오지 못했습니다.');
      } catch (e) {}
    }).finally(function () {
      setOvLoading(false);
    });
  }, []);
  useEffect(function () {
    loadOverview();
    loadProducts();
  }, [loadOverview, loadProducts]);
  var loadBoard = function (id, days) {
    setBoard(null);
    setBdLoading(true);
    api.get('/cd/' + id + '/rank-board?days=' + (days || boardDays)).then(function (res) {
      if (res && res.success) setBoard(res);else toast.error(res && res.detail || '키워드 보드를 불러오지 못했습니다.');
    }).catch(function () {
      try {
        toast.error('키워드 보드를 불러오지 못했습니다.');
      } catch (e) {}
    }).finally(function () {
      setBdLoading(false);
    });
  };
  var submitKeyword = function () {
    var kw = kwInput.trim();
    if (!kw || kwBusy || !selected) return;
    setKwBusy(true);
    setKwMsg(null);
    api.post('/cd/' + selected.id + '/track-keyword', {
      keyword: kw
    }).then(function (res) {
      if (res && res.success) {
        setKwMsg({
          ok: true,
          text: res.already ? '「' + kw + '」 — 이미 추적 중인 키워드입니다.' : '「' + kw + '」 ' + (res.message || '등록되었습니다.')
        });
        if (!res.already) {
          setKwInput('');
          loadBoard(selected.id, boardDays);
        }
      } else {
        setKwMsg({
          ok: false,
          text: res && res.detail || '등록하지 못했습니다.'
        });
      }
    }).catch(function (err) {
      setKwMsg({
        ok: false,
        text: err && err.message || '등록하지 못했습니다.'
      });
    }).finally(function () {
      setKwBusy(false);
    });
  };
  var openDetail = function (c) {
    setSelected({
      id: c.id,
      name: c.name
    });
    loadBoard(c.id, boardDays);
    try {
      window.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    } catch (e) {}
  };
  var changeBoardDays = function (d) {
    if (d === boardDays) return;
    setBoardDays(d);
    if (selected) loadBoard(selected.id, d);
  };
  var backToList = function () {
    setSelected(null);
    setBoard(null);
    setKwInput('');
    setKwMsg(null);
  };

  /* ---------- 업체 목록 (랜딩) ---------- */
  function renderList() {
    var totals = overview && overview.totals || {};
    var rows = overview && overview.data || [];
    var q = query.trim().toLowerCase();
    var shown = rows.filter(function (c) {
      if (q && c.name.toLowerCase().indexOf(q) === -1) return false;
      if (filter === 'attention') return c.keywords > 0 && c.exposed === 0;
      if (filter === 'up') return c.up > 0;
      if (filter === 'down') return c.down > 0;
      return true;
    });
    var fchip = function (key, label) {
      var on = filter === key;
      return React.createElement('button', {
        key: key,
        onClick: function () {
          setFilter(on ? 'all' : key);
        },
        style: {
          border: '1px solid ' + (on ? '#3b82f6' : '#e2e8f0'),
          background: on ? '#eff6ff' : '#fff',
          color: on ? '#1d4ed8' : '#475569',
          borderRadius: 999,
          padding: '5px 13px',
          fontSize: 12,
          fontWeight: 700,
          cursor: 'pointer'
        }
      }, label);
    };
    return React.createElement(React.Fragment, null, React.createElement('div', {
      style: _krKpiGrid
    }, React.createElement('div', {
      style: _krKpi
    }, React.createElement('div', {
      style: _krKpiK
    }, isViewer ? '영업 대상 업체' : '광고주 업체'), React.createElement('div', {
      style: _krKpiV
    }, totals.clients != null ? totals.clients : '—'), React.createElement('div', {
      style: _krKpiS
    }, '추적 키워드 ' + (totals.keywords != null ? totals.keywords : '—'))), React.createElement('div', {
      style: _krKpi
    }, React.createElement('div', {
      style: _krKpiK
    }, '노출 중 업체'), React.createElement('div', {
      style: _krKpiV
    }, totals.exposed_clients != null ? totals.exposed_clients : '—'), React.createElement('div', {
      style: _krKpiS
    }, '300위 내 키워드 보유')), React.createElement('div', {
      style: _krKpi
    }, React.createElement('div', {
      style: _krKpiK
    }, '상승 키워드'), React.createElement('div', {
      style: Object.assign({}, _krKpiV, {
        color: '#dc2626'
      })
    }, '▲ ' + (totals.up_total != null ? totals.up_total : '—')), React.createElement('div', {
      style: _krKpiS
    }, '전일 대비 순위 상승')), React.createElement('div', {
      style: _krKpi
    }, React.createElement('div', {
      style: _krKpiK
    }, '하락 키워드'), React.createElement('div', {
      style: Object.assign({}, _krKpiV, {
        color: '#2563eb'
      })
    }, '▼ ' + (totals.down_total != null ? totals.down_total : '—')), React.createElement('div', {
      style: _krKpiS
    }, '전일 대비 순위 하락')), React.createElement('div', {
      style: _krKpi
    }, React.createElement('div', {
      style: _krKpiK
    }, '주의 필요'), React.createElement('div', {
      style: Object.assign({}, _krKpiV, {
        color: (totals.attention || 0) > 0 ? '#b45309' : '#0f172a'
      })
    }, totals.attention != null ? totals.attention : '—'), React.createElement('div', {
      style: _krKpiS
    }, '추적 중인데 노출 0'))), React.createElement('div', {
      style: _krCard
    }, React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        flexWrap: 'wrap',
        marginBottom: 12
      }
    }, React.createElement('input', {
      value: query,
      onChange: function (e) {
        setQuery(e.target.value);
      },
      placeholder: '🔍 업체명 검색',
      style: {
        flex: '1 1 200px',
        maxWidth: 300,
        padding: '8px 13px',
        border: '1px solid #e2e8f0',
        borderRadius: 10,
        fontSize: 13,
        outline: 'none'
      }
    }), fchip('attention', '⚠️ 주의 필요'), fchip('up', '▲ 상승 보유'), fchip('down', '▼ 하락 보유'), React.createElement('span', {
      style: {
        marginLeft: 'auto',
        fontSize: 12,
        color: '#94a3b8'
      }
    }, shown.length + '개 업체')), ovLoading ? React.createElement('div', {
      style: {
        padding: '40px 0',
        textAlign: 'center',
        color: '#94a3b8',
        fontSize: 13
      }
    }, '불러오는 중...') : shown.length === 0 ? React.createElement('div', {
      style: {
        padding: '40px 0',
        textAlign: 'center',
        color: '#94a3b8',
        fontSize: 13
      }
    }, rows.length === 0 ? '등록된 업체가 없습니다. 업체관리 탭에서 업체를 등록하고 키워드 추적을 시작하세요.' : '조건에 맞는 업체가 없습니다.') : React.createElement('div', {
      style: {
        overflowX: 'auto'
      }
    }, React.createElement('table', {
      style: {
        width: '100%',
        borderCollapse: 'collapse'
      }
    }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
      style: _krTh
    }, '업체'), React.createElement('th', {
      style: _krTh
    }, '상태'), React.createElement('th', {
      style: Object.assign({}, _krTh, {
        textAlign: 'right'
      })
    }, '키워드'), React.createElement('th', {
      style: Object.assign({}, _krTh, {
        textAlign: 'right'
      })
    }, '노출'), React.createElement('th', {
      style: Object.assign({}, _krTh, {
        textAlign: 'right'
      })
    }, 'TOP10'), React.createElement('th', {
      style: Object.assign({}, _krTh, {
        textAlign: 'right'
      })
    }, '▲ / ▼'), React.createElement('th', {
      style: _krTh
    }, '대표 키워드'), React.createElement('th', {
      style: _krTh
    }, '최근 확인'))), React.createElement('tbody', null, shown.map(function (c) {
      var attention = c.keywords > 0 && c.exposed === 0;
      var chip = c.keywords === 0 ? React.createElement('span', {
        style: _krChip('mute')
      }, '추적 없음') : attention ? React.createElement('span', {
        style: _krChip('warn')
      }, '노출 0') : React.createElement('span', {
        style: _krChip('ok')
      }, '노출 ' + c.exposed + '/' + c.keywords);
      return React.createElement('tr', {
        key: c.id,
        onClick: function () {
          openDetail(c);
        },
        style: {
          cursor: 'pointer',
          background: attention ? '#fffbeb' : 'transparent'
        },
        onMouseEnter: function (e) {
          e.currentTarget.style.background = '#f8fafc';
        },
        onMouseLeave: function (e) {
          e.currentTarget.style.background = attention ? '#fffbeb' : 'transparent';
        }
      }, React.createElement('td', {
        style: Object.assign({}, _krTd, {
          fontWeight: 700,
          color: '#0f172a',
          whiteSpace: 'nowrap'
        })
      }, c.name), React.createElement('td', {
        style: _krTd
      }, chip), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          textAlign: 'right',
          fontVariantNumeric: 'tabular-nums'
        })
      }, c.keywords), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          textAlign: 'right',
          fontVariantNumeric: 'tabular-nums'
        })
      }, c.exposed), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          textAlign: 'right',
          fontVariantNumeric: 'tabular-nums'
        })
      }, c.top10), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          textAlign: 'right',
          whiteSpace: 'nowrap',
          fontVariantNumeric: 'tabular-nums'
        })
      }, React.createElement('span', {
        style: {
          color: '#dc2626',
          fontWeight: 700
        }
      }, '▲' + c.up), React.createElement('span', {
        style: {
          color: '#cbd5e1',
          margin: '0 4px'
        }
      }, '/'), React.createElement('span', {
        style: {
          color: '#2563eb',
          fontWeight: 700
        }
      }, '▼' + c.down)), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          fontSize: 12,
          color: '#64748b'
        })
      }, (c.top_keywords || []).map(function (t) {
        return t.keyword + ' ' + t.rank + '위';
      }).join(' · ') || '—'), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          fontSize: 12,
          color: '#94a3b8',
          whiteSpace: 'nowrap'
        })
      }, c.last_checked || '—'));
    }))))));
  }

  /* ---------- 업체 상세 (키워드 보드) ---------- */
  function renderDetail() {
    var kpis = board && board.kpis || {};
    var rows = board && board.board || [];
    var client = board && board.client || selected;
    /* 2차 확산: 정렬 — 서버 기본(노출 순위순) 위에 클라이언트 재정렬 */
    var _volNum = function (v) {
      var n = parseInt(String(v || '').replace(/[^0-9]/g, ''), 10);
      return isNaN(n) ? -1 : n;
    };
    rows = rows.slice().sort(function (a, b) {
      if (boardSort === 'delta') return Math.abs(b.delta || 0) - Math.abs(a.delta || 0);
      if (boardSort === 'volume') return _volNum(b.volume) - _volNum(a.volume);
      if (boardSort === 'name') return String(a.keyword).localeCompare(String(b.keyword), 'ko');
      return (a.rank == null) - (b.rank == null) || (a.rank || 0) - (b.rank || 0);
    });
    return React.createElement(React.Fragment, null, React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        marginBottom: 14,
        flexWrap: 'wrap'
      }
    }, React.createElement('button', {
      onClick: backToList,
      style: {
        border: '1px solid #e2e8f0',
        background: '#fff',
        color: '#475569',
        borderRadius: 10,
        padding: '7px 14px',
        fontSize: 12.5,
        fontWeight: 700,
        cursor: 'pointer'
      }
    }, '← 업체 목록'), React.createElement('h2', {
      style: {
        margin: 0,
        fontSize: 19,
        fontWeight: 800,
        color: '#0f172a'
      }
    }, '🏢 ' + (client.name || '')), client.store_url && React.createElement('a', {
      href: client.store_url,
      target: '_blank',
      rel: 'noopener noreferrer',
      style: {
        fontSize: 12,
        color: '#3b82f6',
        fontWeight: 600,
        textDecoration: 'none'
      }
    }, '스토어 열기 ↗'), onNavigateToClient && React.createElement('button', {
      onClick: function () {
        onNavigateToClient(client.name, client.store_url || '');
      },
      style: {
        marginLeft: 'auto',
        border: '1px solid #bfdbfe',
        background: '#eff6ff',
        color: '#1d4ed8',
        borderRadius: 10,
        padding: '7px 14px',
        fontSize: 12.5,
        fontWeight: 700,
        cursor: 'pointer'
      }
    }, '📈 업체관리에서 보기')), React.createElement('div', {
      style: _krKpiGrid
    }, React.createElement('div', {
      style: _krKpi
    }, React.createElement('div', {
      style: _krKpiK
    }, '추적 키워드'), React.createElement('div', {
      style: _krKpiV
    }, kpis.keywords != null ? kpis.keywords : '—')), React.createElement('div', {
      style: _krKpi
    }, React.createElement('div', {
      style: _krKpiK
    }, '노출 중'), React.createElement('div', {
      style: _krKpiV
    }, kpis.exposed != null ? kpis.exposed : '—'), React.createElement('div', {
      style: _krKpiS
    }, '300위 내')), React.createElement('div', {
      style: _krKpi
    }, React.createElement('div', {
      style: _krKpiK
    }, 'TOP 10'), React.createElement('div', {
      style: _krKpiV
    }, kpis.top10 != null ? kpis.top10 : '—')), React.createElement('div', {
      style: _krKpi
    }, React.createElement('div', {
      style: _krKpiK
    }, '상승 / 하락'), React.createElement('div', {
      style: _krKpiV
    }, React.createElement('span', {
      style: {
        color: '#dc2626'
      }
    }, '▲' + (kpis.up != null ? kpis.up : '—')), React.createElement('span', {
      style: {
        color: '#cbd5e1',
        margin: '0 5px',
        fontSize: 16
      }
    }, '/'), React.createElement('span', {
      style: {
        color: '#2563eb'
      }
    }, '▼' + (kpis.down != null ? kpis.down : '—'))), React.createElement('div', {
      style: _krKpiS
    }, '전일 대비'))), React.createElement('div', {
      style: _krCard
    },
    /* 추적 키워드 추가 등록 (2026-08-11 직원 기능 요청) — 서버가 권한·중복·
       영업대상 여부를 최종 판정하므로 입력은 항상 노출, 결과 메시지로 안내 */
    React.createElement('div', {
      style: {
        display: 'flex',
        gap: 8,
        alignItems: 'center',
        flexWrap: 'wrap',
        marginBottom: 10,
        padding: '10px 12px',
        background: '#f8fafc',
        border: '1px dashed #cbd5e1',
        borderRadius: 10
      }
    }, React.createElement('span', {
      style: {
        fontSize: 12.5,
        fontWeight: 700,
        color: '#475569'
      }
    }, '＋ 추적 키워드 등록'), React.createElement('input', {
      value: kwInput,
      disabled: kwBusy,
      onChange: function (e) {
        setKwInput(e.target.value);
      },
      onKeyDown: function (e) {
        if (e.key === 'Enter' && !e.nativeEvent.isComposing) submitKeyword();
      },
      placeholder: '예: 수제쿠키 (Enter)',
      style: {
        flex: '1 1 180px',
        maxWidth: 260,
        padding: '7px 12px',
        border: '1px solid #e2e8f0',
        borderRadius: 9,
        fontSize: 13,
        outline: 'none'
      }
    }), React.createElement('button', {
      onClick: submitKeyword,
      disabled: kwBusy || !kwInput.trim(),
      style: {
        border: 'none',
        background: kwBusy || !kwInput.trim() ? '#93c5fd' : '#3b82f6',
        color: '#fff',
        borderRadius: 9,
        padding: '7px 16px',
        fontSize: 12.5,
        fontWeight: 700,
        cursor: kwBusy || !kwInput.trim() ? 'default' : 'pointer'
      }
    }, kwBusy ? '등록 중…' : '등록'), kwMsg && React.createElement('span', {
      style: {
        fontSize: 12,
        fontWeight: 600,
        color: kwMsg.ok ? '#16a34a' : '#dc2626',
        flexBasis: '100%'
      }
    }, kwMsg.text)), /* 2차 확산: 정렬 · 추이 기간 컨트롤 */
    React.createElement('div', {
      style: {
        display: 'flex',
        gap: 8,
        alignItems: 'center',
        flexWrap: 'wrap',
        marginBottom: 12
      }
    }, React.createElement('select', {
      value: boardSort,
      onChange: function (e) {
        setBoardSort(e.target.value);
      },
      style: {
        border: '1px solid #e2e8f0',
        borderRadius: 9,
        padding: '7px 11px',
        fontSize: 12.5,
        fontWeight: 600,
        color: '#475569',
        background: '#fff'
      }
    }, React.createElement('option', {
      value: 'rank'
    }, '정렬: 순위순'), React.createElement('option', {
      value: 'delta'
    }, '변동 큰 순'), React.createElement('option', {
      value: 'volume'
    }, '검색량 많은 순'), React.createElement('option', {
      value: 'name'
    }, '가나다순')), React.createElement('span', {
      style: {
        display: 'inline-flex',
        border: '1px solid #e2e8f0',
        borderRadius: 9,
        overflow: 'hidden'
      }
    }, [7, 30].map(function (d) {
      var on = boardDays === d;
      return React.createElement('button', {
        key: d,
        onClick: function () {
          changeBoardDays(d);
        },
        style: {
          border: 'none',
          padding: '7px 13px',
          fontSize: 12.5,
          fontWeight: 700,
          cursor: 'pointer',
          background: on ? '#3b82f6' : '#fff',
          color: on ? '#fff' : '#475569'
        }
      }, d + '일');
    })), React.createElement('span', {
      style: {
        fontSize: 12,
        color: '#94a3b8',
        marginLeft: 'auto'
      }
    }, '추이·전일 대비는 매일 08:00 기록 기준')), bdLoading ? React.createElement('div', {
      style: {
        padding: '40px 0',
        textAlign: 'center',
        color: '#94a3b8',
        fontSize: 13
      }
    }, '불러오는 중...') : rows.length === 0 ? React.createElement('div', {
      style: {
        padding: '40px 0',
        textAlign: 'center',
        color: '#94a3b8',
        fontSize: 13
      }
    }, '아직 순위 기록이 없습니다. 위 「＋ 추적 키워드 등록」에 키워드를 넣으면 수 분 안에 첫 순위가 기록됩니다.') : React.createElement('div', {
      style: {
        overflowX: 'auto'
      }
    }, React.createElement('table', {
      style: {
        width: '100%',
        borderCollapse: 'collapse'
      }
    }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
      style: _krTh
    }, '키워드'), React.createElement('th', {
      style: Object.assign({}, _krTh, {
        textAlign: 'right'
      })
    }, '현재 순위'), React.createElement('th', {
      style: _krTh
    }, '전일 대비'), React.createElement('th', {
      style: _krTh
    }, '최근 ' + boardDays + '일'), React.createElement('th', {
      style: Object.assign({}, _krTh, {
        textAlign: 'right'
      })
    }, '월 검색량'), React.createElement('th', {
      style: Object.assign({}, _krTh, {
        textAlign: 'right'
      })
    }, '페이지'), React.createElement('th', {
      style: _krTh
    }, '확인 시각'), React.createElement('th', {
      style: _krTh
    }, '이미지'))), React.createElement('tbody', null, rows.map(function (b) {
      var d = _krDelta(b.delta === null || b.delta === undefined ? b.prev_rank == null && b.rank != null ? undefined : 0 : b.delta);
      var exposed = b.rank !== null && b.rank !== undefined;
      var open = expandedKw === b.keyword;
      var mainRow = React.createElement('tr', {
        key: b.keyword,
        onClick: function () {
          toggleKw(client, b.keyword);
        },
        style: {
          cursor: 'pointer',
          background: open ? '#f8fafc' : 'transparent'
        },
        onMouseEnter: function (e) {
          e.currentTarget.style.background = '#f8fafc';
        },
        onMouseLeave: function (e) {
          e.currentTarget.style.background = open ? '#f8fafc' : 'transparent';
        }
      }, React.createElement('td', {
        style: Object.assign({}, _krTd, {
          fontWeight: 700,
          color: '#0f172a'
        })
      }, React.createElement('span', {
        style: {
          color: '#94a3b8',
          fontSize: 10,
          marginRight: 7
        }
      }, open ? '▼' : '▶'), b.keyword), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          textAlign: 'right'
        })
      }, exposed ? React.createElement('span', {
        style: {
          fontSize: 16,
          fontWeight: 800,
          color: b.rank <= 10 ? '#16a34a' : '#0f172a',
          fontVariantNumeric: 'tabular-nums'
        }
      }, b.rank + '위') : b.pending ? React.createElement('span', {
        style: _krChip('info'),
        title: '등록됨 — 첫 순위 기록을 기다리는 중(보통 수 분)'
      }, '⏳ 기록 대기') : React.createElement('span', null, React.createElement('span', {
        style: _krChip('mute')
      }, '미노출'), (b.unexposed_days || 0) >= 2 && React.createElement('span', {
        style: Object.assign({}, _krChip('warn'), {
          marginLeft: 4
        }),
        title: '연속 미노출 일수'
      }, b.unexposed_days + '일째'))), React.createElement('td', {
        style: _krTd
      }, exposed && b.delta !== null && b.delta !== undefined ? React.createElement('span', {
        style: d.style
      }, d.label) : React.createElement('span', {
        style: {
          fontSize: 11.5,
          color: '#cbd5e1'
        }
      }, '—')), React.createElement('td', {
        style: _krTd
      }, _krSparkline(b.series)), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          textAlign: 'right',
          fontVariantNumeric: 'tabular-nums'
        })
      }, b.volume || '—'), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          textAlign: 'right',
          fontVariantNumeric: 'tabular-nums'
        })
      }, exposed && b.page ? b.page + 'p' : '—'), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          fontSize: 12,
          color: '#94a3b8',
          whiteSpace: 'nowrap'
        })
      }, b.last_checked ? String(b.last_checked).slice(0, 16).replace('T', ' ') : '—'), React.createElement('td', {
        style: Object.assign({}, _krTd, {
          whiteSpace: 'nowrap'
        })
      }, React.createElement('button', {
        onClick: function (e) {
          e.stopPropagation();
          if (!open) toggleKw(client, b.keyword);else setExpandedKw(null);
        },
        title: '순위 추이 그래프 + 이미지(PNG) 저장',
        style: {
          fontSize: 11,
          fontWeight: 700,
          padding: '3px 10px',
          borderRadius: 14,
          cursor: 'pointer',
          border: '1px solid #16a34a',
          background: '#f0fdf4',
          color: '#16a34a'
        }
      }, open ? '▴ 접기' : '📸 그래프·저장')));
      return open ? React.createElement(React.Fragment, {
        key: b.keyword + '::grp'
      }, mainRow, renderKwPanel(client, b)) : mainRow;
    }))))));
  }
  return React.createElement('div', {
    style: _krWrap
  }, React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 10,
      marginBottom: 16,
      flexWrap: 'wrap'
    }
  }, React.createElement('h1', {
    style: {
      margin: 0,
      fontSize: 21,
      fontWeight: 800,
      color: '#0f172a',
      letterSpacing: '-.02em'
    }
  }, '📊 키워드 순위'), React.createElement('span', {
    style: {
      fontSize: 12.5,
      color: '#94a3b8'
    }
  }, selected ? '업체 상세 — 키워드별 추적 현황' : (isViewer ? '내 영업 대상 업체별 순위 추적 현황' : '광고주 업체별 순위 추적 현황') + ' · 매일 아침 자동 기록')), selected ? renderDetail() : renderList(),
  /* ---------- 추적 상품 관리(전체 업체 도구) — 업체 목록에서만, 기본 접힘 ----------
     업체 상세는 그 업체 데이터만 보이도록 여기서 제외한다(운영자 지시 2026-08-04). */
  !selected && React.createElement('div', {
    style: {
      marginTop: 28
    }
  }, React.createElement('button', {
    onClick: function () {
      setTrackingOpen(!trackingOpen);
    },
    style: {
      width: '100%',
      textAlign: 'left',
      border: '1px solid #e2e8f0',
      background: '#fff',
      color: '#334155',
      borderRadius: 12,
      padding: '13px 18px',
      fontSize: 13.5,
      fontWeight: 700,
      cursor: 'pointer'
    }
  }, (trackingOpen ? '▴ ' : '▾ ') + '🛠 추적 상품 관리 — 상품·키워드 등록/삭제 · 수동 재확인 · 노출 분석 (전체 업체)', !trackingOpen && React.createElement('span', {
    style: {
      fontSize: 12,
      fontWeight: 500,
      color: '#94a3b8',
      marginLeft: 8
    }
  }, '펼쳐서 관리')), trackingOpen && React.createElement('div', {
    style: {
      marginTop: 12
    }
  }, React.createElement(window.SectionErrorBoundary, {
    name: '순위 추적'
  }, React.createElement(window.RankTrackingSection, {
    products: products,
    refreshProducts: loadProducts,
    searchedKeyword: rankCtx && rankCtx.searchedKeyword || '',
    searchedProductUrl: rankCtx && rankCtx.searchedProductUrl || '',
    cachedProductName: rankCtx && rankCtx.cachedProductName || '',
    relatedKeywords: rankCtx && rankCtx.relatedKeywords || null,
    onNavigateToClient: onNavigateToClient,
    canEdit: currentUser.role !== 'viewer',
    onRankResult: null
  })))));
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
  }, "🔍"), "키워드 검색량", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅ 실측")), /*#__PURE__*/React.createElement("div", {
    className: "grid3"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "총 검색량"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(total), /*#__PURE__*/React.createElement("small", null, "회/월"))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "PC"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(pc), /*#__PURE__*/React.createElement("small", null, "회 (", pcRatio, "%)"))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "모바일"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(mobile), /*#__PURE__*/React.createElement("small", null, "회 (", mobileRatio, "%)")))), /*#__PURE__*/React.createElement("div", {
    className: "track",
    style: {
      height: 14,
      marginTop: 14,
      display: 'flex'
    }
  }, /*#__PURE__*/React.createElement("i", {
    style: {
      width: pcRatio + '%',
      background: '#3b82f6'
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
  }, /*#__PURE__*/React.createElement("span", null, "● PC ", pcRatio, "%"), /*#__PURE__*/React.createElement("span", null, "모바일 ", mobileRatio, "% ●")), /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, note))));
};

;/* ===== js/components/RelatedKeywordsSection.jsx ===== */
/* RelatedKeywordsSection — 연관/황금 키워드 (v6.6: 연관도 우선 정렬 + 상위 30개 기본 표시)
 * '콤부차' 보고서에 쌀·계란 등 대분류 인기 키워드가 상위를 차지하던 문제 개선:
 * ① 분석 키워드를 포함(또는 포함되는) 키워드를 앞으로 → ② 나머지는 검색량순.
 * 기본 30개만 표시(전달본 다이어트), '전체 보기'는 화면 전용(no-export). 데이터 삭제 없음. */
window.RelatedKeywordsSection = function RelatedKeywordsSection({
  data,
  keyword
}) {
  const {
    useState
  } = React;
  const [tab, setTab] = useState('related');
  const [showAll, setShowAll] = useState(false);
  if (!data) return null;
  const goldenList = data.golden_keywords || [];
  const rawRelated = data.related_keywords || [];

  /* 연관도 우선 정렬 — keyword 미전달 시 기존 순서 그대로(무손실 폴백) */
  var norm = function (v) {
    return String(v || '').replace(/\s/g, '').toLowerCase();
  };
  var base = norm(keyword);
  var isRel = function (k) {
    if (!base) return false;
    var n = norm(k && k.keyword);
    return !!n && (n.indexOf(base) >= 0 || base.indexOf(n) >= 0);
  };
  var relatedList = rawRelated;
  var relCount = 0;
  if (base) {
    var tier1 = [],
      tier2 = [];
    rawRelated.forEach(function (k) {
      (isRel(k) ? tier1 : tier2).push(k);
    });
    var byVol = function (a, b) {
      return (b.totalVolume || 0) - (a.totalVolume || 0);
    };
    tier1.sort(byVol);
    tier2.sort(byVol);
    relatedList = tier1.concat(tier2);
    relCount = tier1.length;
  }
  var SHOW_LIMIT = 30;
  var relatedVisible = tab === 'related' && !showAll ? relatedList.slice(0, SHOW_LIMIT) : relatedList;
  /* 상품명 후보: 연관도 상위 5개 (분석 키워드 자체 제외) */
  var nameCandidates = base ? relatedList.filter(function (k) {
    return isRel(k) && norm(k.keyword) !== base;
  }).slice(0, 5) : [];
  const displayList = tab === 'golden' ? goldenList : relatedVisible;
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
  }, "🔗"), "연관 키워드 분석", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅ 실측"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontWeight: 400,
      color: '#64748b',
      marginLeft: 4
    }
  }, "총 ", fmt(data.total_found), "개 발견")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, base ? '연관도(분석 키워드 포함 우선) → 검색량순 정렬 · 기본 상위 ' + SHOW_LIMIT + '개 표시' : '검색량과 경쟁강도를 기반으로 분류합니다'), /*#__PURE__*/React.createElement("div", {
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
      background: tab === 'related' ? '#3b82f6' : '#f1f5f9',
      color: tab === 'related' ? '#fff' : '#64748b',
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      fontFamily: 'inherit',
      transition: 'all 0.2s'
    }
  }, "연관 키워드 (", relatedList.length, ")"), /*#__PURE__*/React.createElement("button", {
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
  }, "💎 황금 키워드 (", goldenList.length, ")"), tab === 'related' && relatedList.length > SHOW_LIMIT && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "no-export",
    onClick: () => setShowAll(!showAll),
    style: {
      marginLeft: 'auto',
      padding: '10px 16px',
      borderRadius: 10,
      border: '1px solid #e2e8f0',
      background: '#fff',
      color: '#64748b',
      fontSize: 12,
      fontWeight: 600,
      cursor: 'pointer',
      fontFamily: 'inherit'
    }
  }, showAll ? '상위 ' + SHOW_LIMIT + '개만 보기' : '전체 ' + fmt(relatedList.length) + '개 보기')), displayList.length === 0 ? /*#__PURE__*/React.createElement(EmptyState, {
    icon: "💎",
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
  }, "키워드"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'left'
    }
  }, "월간 검색량"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center'
    }
  }, "PC"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center'
    }
  }, "모바일"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center'
    }
  }, "경쟁강도"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'left',
      width: '20%'
    }
  }, "검색량 비율"), tab === 'golden' && /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center'
    }
  }, "추천"))), /*#__PURE__*/React.createElement("tbody", null, displayList.map((k, i) => {
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
    }, "황금")), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 20px',
        fontWeight: 700,
        fontSize: 14,
        color: '#3b82f6'
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
        background: tab === 'golden' ? 'linear-gradient(90deg, #f59e0b, #fbbf24)' : 'linear-gradient(90deg, #3b82f6, #7c3aed)',
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
    }, "진입 추천")));
  }))))), tab === 'related' && nameCandidates.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "sub-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "st"
  }, "✏️ 상품명에 넣을 후보 ", nameCandidates.length, "개"), /*#__PURE__*/React.createElement("div", null, nameCandidates.map(function (k) {
    return /*#__PURE__*/React.createElement("span", {
      key: k.keyword,
      className: "tag2"
    }, k.keyword, " · 월 ", fmt(k.totalVolume));
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      marginTop: 6
    }
  }, "분석 키워드와 직접 연관된 키워드 중 검색량 상위 — 상품명·태그 반영 후보")))));
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
  shopProducts,
  htmlReviewData
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
  const ranWithReview = useRef(false); // HTML 실측 리뷰 반영해 재실행했는지
  // shopProducts ref — React 17 Promise 내 setState 비배치 문제 방지
  // useEffect 실행 시점에 shopProducts prop이 아직 null일 수 있으므로 ref로 최신값 보장
  const shopProductsRef = useRef(shopProducts);
  shopProductsRef.current = shopProducts;
  useEffect(function () {
    if (parentProductUrl) setProductUrl(parentProductUrl);
  }, [parentProductUrl]);
  useEffect(function () {
    autoTriggered.current = false;
    ranWithReview.current = false;
    setResult(null);
  }, [keyword, parentProductUrl]);

  // 자동 실행: 메인 분석 데이터 + shopProducts 모두 도착한 후 실행
  // shopProducts를 deps에 포함하여 데이터 도착 후 재시도 보장.
  // 추가: HTML 실측 리뷰가 SEO 분석 후 늦게 도착하면 실측을 반영해 1회 재실행(리뷰 병목 모순 제거).
  useEffect(function () {
    var canRun = keyword && productUrl && !loading && (cachedRank || cachedProductName || cachedTotalVolume || cachedProductInfo) && shopProducts && shopProducts.length > 0;
    if (!canRun) return;
    var hasReview = htmlReviewData && htmlReviewData.reviewCount != null;
    if (!autoTriggered.current && !result) {
      autoTriggered.current = true;
      ranWithReview.current = hasReview;
      handleAnalyze();
    } else if (hasReview && !ranWithReview.current) {
      ranWithReview.current = true;
      handleAnalyze();
    }
  }, [keyword, productUrl, cachedRank, cachedProductName, cachedTotalVolume, cachedProductInfo, shopProducts, htmlReviewData]);
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
      // HTML 실측 리뷰/평점 → SEO 진단이 순위 추정 대신 실측 사용(리뷰 병목 모순 제거)
      if (htmlReviewData && htmlReviewData.reviewCount != null) seoBody.cached_review_count = htmlReviewData.reviewCount;
      if (htmlReviewData && htmlReviewData.rating != null) seoBody.cached_rating = htmlReviewData.rating;
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
  }, "🔧"), "SEO 종합 진단", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "≈ 추정")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "10개 평가지표로 상품의 검색 노출 상태를 진단합니다"), /*#__PURE__*/React.createElement("div", {
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
    placeholder: "분석할 상품 URL을 입력하세요",
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
  }, "기준 키워드: ", /*#__PURE__*/React.createElement("strong", null, keyword))), loading && /*#__PURE__*/React.createElement(LoadingSpinner, {
    text: "SEO 분석 중..."
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
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(79,70,229,.18)',
        pointBackgroundColor: '#3b82f6',
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
  }, "/100 · ", getScoreLabel(result.scores.total))), /*#__PURE__*/React.createElement("div", {
    className: "scorebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "lbl"
  }, /*#__PURE__*/React.createElement("b", null, "상품명"), /*#__PURE__*/React.createElement("span", {
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
  }, /*#__PURE__*/React.createElement("b", null, "검색순위"), /*#__PURE__*/React.createElement("span", {
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
  }, /*#__PURE__*/React.createElement("b", null, "가격"), /*#__PURE__*/React.createElement("span", {
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
  }, /*#__PURE__*/React.createElement("b", null, "리뷰"), /*#__PURE__*/React.createElement("span", {
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
  }, /*#__PURE__*/React.createElement("b", null, "판매실적"), /*#__PURE__*/React.createElement("span", {
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
  }, /*#__PURE__*/React.createElement("b", null, "평점"), /*#__PURE__*/React.createElement("span", {
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
  }, /*#__PURE__*/React.createElement("b", null, "카테고리"), /*#__PURE__*/React.createElement("span", {
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
  }, /*#__PURE__*/React.createElement("b", null, "브랜드"), /*#__PURE__*/React.createElement("span", {
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
  }, /*#__PURE__*/React.createElement("b", null, "네이버페이"), /*#__PURE__*/React.createElement("span", {
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
  }, /*#__PURE__*/React.createElement("b", null, "최신성"), /*#__PURE__*/React.createElement("span", {
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
  }, "현재 순위: ", /*#__PURE__*/React.createElement("strong", null, result.scores.detail.current_rank, "위"), " · 추정 월 판매: ", /*#__PURE__*/React.createElement("strong", null, (result.scores.detail.est_monthly_sales || 0).toLocaleString(), "건")))), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: 'var(--rt-sub)',
      marginTop: 6
    }
  }, "10개 지표: 상품명·검색순위·가격·리뷰·판매실적·평점·카테고리·브랜드·네이버페이·최신성 (레이더 차트)"), result.suggestions?.length > 0 && /*#__PURE__*/React.createElement("div", {
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
  }, /*#__PURE__*/React.createElement("span", null, "💡"), " 개선 제안"), result.suggestions.map((s, i) => /*#__PURE__*/React.createElement("div", {
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
      background: '#3b82f6',
      color: '#fff',
      fontSize: 11,
      fontWeight: 700,
      flexShrink: 0,
      marginTop: 2
    }
  }, i + 1), s))), /*#__PURE__*/React.createElement("div", {
    className: "note est"
  }, "※ 리뷰 수·평점·판매실적·최신성은 순위 구간별 업계 평균 기반 추정치입니다. 네이버 쇼핑 API 한계로 실제 수치와 차이가 있을 수 있으며, 향후 정밀화 예정입니다.")))));
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
  const reqIdRef = React.useRef(0); // 요청 경합 방지 — 이전 키워드 응답이 새 키워드 화면을 덮어쓰는 것 차단

  // 검색 결과의 1페이지 상품명 자동 채우기 + 자동 분석
  useEffect(function () {
    if (shopProducts && shopProducts.length > 0) {
      var productNames = shopProducts.map(function (p) {
        return p.product_name;
      }).filter(Boolean);
      setNames(productNames.join('\n'));
      // 자동 분석 실행
      if (productNames.length > 0) {
        var myReq = ++reqIdRef.current;
        setLoading(true);
        setResult(null);
        api.post('/product-name/analyze', {
          product_names: productNames,
          keyword: keyword || ''
        }).then(function (res) {
          if (myReq !== reqIdRef.current) return;
          if (res.success) setResult(res.data);
          setLoading(false);
        }).catch(function () {
          if (myReq !== reqIdRef.current) return;
          setLoading(false);
        });
      }
    }
  }, [shopProducts, keyword]);
  const handleAnalyze = async () => {
    const nameList = names.split('\n').map(n => n.trim()).filter(Boolean);
    if (nameList.length === 0) return;
    const myReq = ++reqIdRef.current;
    setLoading(true);
    try {
      const res = await api.post('/product-name/analyze', {
        product_names: nameList,
        keyword: keyword || ''
      });
      if (myReq !== reqIdRef.current) return;
      if (res.success) setResult(res.data);
    } catch (e) {
      alert('분석 실패');
    }
    if (myReq === reqIdRef.current) setLoading(false);
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
  }, "🔤"), "상품명 키워드 분석", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅ 실측")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "경쟁 상품명의 키워드 구성을 분석합니다"), /*#__PURE__*/React.createElement("div", {
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
  }, "상품명 목록 (한 줄에 하나씩)")), /*#__PURE__*/React.createElement("textarea", {
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
    placeholder: "경쟁 상품명을 한 줄에 하나씩 입력하세요...",
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
  }, "📦"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      marginBottom: 6
    }
  }, "분석 상품 수"), /*#__PURE__*/React.createElement("div", {
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
  }, "개")), /*#__PURE__*/React.createElement("div", {
    style: metricCardStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, "📏"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      marginBottom: 6
    }
  }, "평균 상품명 길이"), /*#__PURE__*/React.createElement("div", {
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
  }, "자")), /*#__PURE__*/React.createElement("div", {
    style: metricCardStyle
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      marginBottom: 8
    }
  }, "🎯"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#94a3b8',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      marginBottom: 6
    }
  }, "키워드 포함률"), /*#__PURE__*/React.createElement("div", {
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
  }, "📊 자주 사용된 키워드 TOP 15"), /*#__PURE__*/React.createElement("div", {
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
  }, "키워드"), /*#__PURE__*/React.createElement("th", {
    style: {
      fontWeight: 600,
      fontSize: 12
    }
  }, "등장 횟수"), /*#__PURE__*/React.createElement("th", {
    style: {
      fontWeight: 600,
      fontSize: 12
    }
  }, "사용 비율"))), /*#__PURE__*/React.createElement("tbody", null, result.top_keywords.slice(0, 15).map((k, i) => /*#__PURE__*/React.createElement("tr", {
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
      background: 'linear-gradient(135deg, #3b82f6, #7c3aed)',
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
  }, k.count, "회"), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("div", {
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
      background: 'linear-gradient(135deg, #3b82f6, #7c3aed)',
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

  /* HTML 보고서 — 공용 캡처 빌더(ReportCapture) 사용
   * 업체 자동저장 경로와 동일한 빌더를 써서 직원용 UI가 전달본에 섞이는 것을 원천 차단 */
  var handleHtmlExport = function () {
    /* AI 종합 분석이 진행 중이면 완료 대기를 먼저 권유 (강행 시 해당 섹션은 '별도 전달' 안내로 대체) */
    try {
      if (window.ReportCapture && window.ReportCapture.aiState() === 'loading') {
        var goNow = window.confirm('🤖 AI 종합 분석이 아직 진행 중입니다 (약 20~30초).\n완료 후 내보내면 AI 분석이 보고서에 포함됩니다.\n\n지금 바로 내보내시겠습니까?\n(AI 섹션은 "완료 후 별도 전달" 안내로 대체됩니다)');
        if (!goNow) return;
      }
    } catch (eG) {}
    setLoading(true);
    try {
      var headerText = companyName ? companyName + ' 분석 보고서' : '로직 분석 보고서';
      var fullHtml = window.ReportCapture ? window.ReportCapture.buildHtml({
        title: headerText,
        managerName: props && props.managerName
      }) : '';
      if (!fullHtml) {
        throw new Error('캡처 대상(.report-main)을 찾지 못했습니다');
      }

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
  }, "📄"), "보고서 내보내기"), /*#__PURE__*/React.createElement("div", {
    className: "section-line"
  }), /*#__PURE__*/React.createElement("p", {
    className: "section-subtitle"
  }, "분석 결과를 HTML/JSON/CSV로 다운로드합니다"), /*#__PURE__*/React.createElement("div", {
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
  }, "업체명 (선택)"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    style: {
      width: 160
    },
    placeholder: "업체명 입력",
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
  }, "형식"), /*#__PURE__*/React.createElement("select", {
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
  }, "HTML 보고서"), /*#__PURE__*/React.createElement("option", {
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
  }, "기간"), /*#__PURE__*/React.createElement("select", {
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
  }, "최근 7일"), /*#__PURE__*/React.createElement("option", {
    value: 14
  }, "최근 14일"), /*#__PURE__*/React.createElement("option", {
    value: 30
  }, "최근 30일"), /*#__PURE__*/React.createElement("option", {
    value: 90
  }, "최근 90일"))), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: handleExport,
    disabled: loading
  }, loading ? '생성 중...' : format === 'html' ? '📄 HTML 보고서 다운로드' : '보고서 생성'), data && data.format === 'csv' && /*#__PURE__*/React.createElement("button", {
    className: "btn btn-secondary",
    onClick: handleDownloadCSV
  }, "📥 CSV 다운로드")), format === 'html' && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12,
      padding: '10px 14px',
      background: '#f0f9ff',
      borderRadius: 8,
      fontSize: 13,
      color: '#0369a1'
    }
  }, "💡 현재 페이지에 표시된 모든 분석 결과를 그대로 HTML 파일로 내보냅니다. 먼저 키워드 검색을 완료한 후 보고서를 생성해주세요."), data && data.format === 'json' && /*#__PURE__*/React.createElement("div", {
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
  }, "상품 ", data.total_products, "개"), /*#__PURE__*/React.createElement("span", {
    className: "badge badge-green"
  }, "키워드 ", data.total_keywords, "개"), /*#__PURE__*/React.createElement("span", {
    className: "badge badge-gray"
  }, data.generated_at ? data.generated_at.slice(0, 10) : '')), /*#__PURE__*/React.createElement("div", {
    className: "table-wrap",
    style: {
      maxHeight: 300,
      overflow: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", null, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "상품명"), /*#__PURE__*/React.createElement("th", null, "키워드"), /*#__PURE__*/React.createElement("th", null, "최근 순위"), /*#__PURE__*/React.createElement("th", null, "이력 수"))), /*#__PURE__*/React.createElement("tbody", null, (data.items || []).map(function (item, i) {
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
    }, item.latest_rank ? item.latest_rank + '위' : '-'), /*#__PURE__*/React.createElement("td", null, item.history_count, "건"));
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
  }, "🔔"), "알림 설정"), /*#__PURE__*/React.createElement("div", {
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
  }, "일일 리포트 알림"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginTop: 2
    }
  }, settings.report_time || '09:00', "에 순위 변동 리포트를 발송합니다")), /*#__PURE__*/React.createElement("label", {
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
  }, "솔라피 API가 설정되지 않았습니다. 알림을 사용하려면 환경변수를 설정하세요."))));
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
  }, "⚔️"), "키워드 경쟁강도 분석", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅ 실측")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "상품 수 대비 검색량으로 경쟁 수준을 판단합니다"), /*#__PURE__*/React.createElement("div", {
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
  }, "경쟁지수"), /*#__PURE__*/React.createElement("div", {
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
  }, /*#__PURE__*/React.createElement("span", null, "블루오션"), /*#__PURE__*/React.createElement("span", null, "보통"), /*#__PURE__*/React.createElement("span", null, "레드오션")), /*#__PURE__*/React.createElement("div", {
    className: "grid3",
    style: {
      marginTop: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "등록 상품수"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(productCount))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "월간 검색량"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(searchVolume))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "평균 클릭수"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, fmt(avgCtr)))))), /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, "경쟁지수 ", fmt(compIndex), "(", compLabel, ")", interpretation ? '. ' + interpretation : '.'))));
};

;/* ===== js/components/MarketRevenueSection.jsx ===== */
window.MarketRevenueSection = function MarketRevenueSection(props) {
  if (!props?.data) return null;
  const {
    avgPrice,
    estimatedMonthly,
    estimatedMonthlyRange,
    topProducts,
    conversionRate,
    calculationMethod,
    tolerance
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

  /* ===== 리뷰 실측 앵커 보정 (v6.7) — 판다랭크류와 같은 '실판매 신호' 기반 =====
   * 자사 상품의 실제 누적 리뷰(HTML 수집)로 월판매를 역산(작성률 11.6%·운영 12개월 가정)하고,
   * 그 값을 앵커로 순위 감쇠 곡선(1/rank^0.7)의 절대 수준을 보정해 상위 40개 시장규모를 재계산.
   * 검색량×CTR 모델은 '검색 유입 기여분'이라 실제 시장(재구매·타키워드·광고 유입 포함)보다
   * 크게 작게 나오던 문제 해결. 실리뷰·순위 없으면 이 블록만 생략(기존 표시 그대로 — 무손실). */
  var _rc = Number(props.reviewCount) || 0;
  var _advRank = Number(props.advRank) || 0;
  /* 자사 실측 앵커 — 판매량 추정 배너와 '완전히 같은 값'을 쓰도록 공통 helper 사용 */
  var _anchor = _rc > 0 && window.reviewAnchorEstimate ? window.reviewAnchorEstimate(_rc, props.productPrice) : null;
  var _calib = null;
  if (_anchor && _advRank > 0 && topProducts && topProducts.length >= 3) {
    var _realMonthly = _anchor.monthlyUnits; /* 자사 실측 월판매(추정) — SalesEstimation 배너와 동일 값 */
    var _decay = function (r) {
      return 1 / Math.pow(Math.max(1, r), 0.7);
    };
    var _unit = _realMonthly / _decay(_advRank);
    var _sum = 0;
    topProducts.forEach(function (p) {
      var _pr = Number(p.priceNum) || 0;
      if (_pr > 0) _sum += _unit * _decay(p.rank) * _pr;
    });
    if (_sum > 0) {
      _calib = {
        mid: Math.round(_sum),
        lo: Math.round(_sum * 0.7),
        hi: Math.round(_sum * 1.3),
        realMonthly: Math.round(_realMonthly)
      };
    }
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
  }, "💰"), "시장 규모 & 매출 추정", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "≈ 추정"), tolerance ? /*#__PURE__*/React.createElement("span", {
    className: "badge b-est",
    style: {
      marginLeft: 6
    }
  }, tolerance) : null), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, _calib ? '리뷰 실측 앵커 보정(주 수치) + 검색 유입 기여분(참고)' : '검색량 × 클릭률 × 전환율 × 평균 단가 기반 추정'), _calib && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 12,
      padding: '14px 18px',
      background: '#f0fdf4',
      border: '1px solid #a7f3d0',
      borderRadius: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#047857',
      marginBottom: 8,
      paddingBottom: 8,
      borderBottom: '1px dashed #a7f3d0'
    }
  }, "🧾 ", /*#__PURE__*/React.createElement("b", null, "자사 실측 앵커"), " — 누적 리뷰 ", /*#__PURE__*/React.createElement("b", null, fmt(_rc), "건"), " → 월판매 ", /*#__PURE__*/React.createElement("b", null, "~", fmt(_calib.realMonthly), "건"), _anchor && _anchor.monthlyRevenue != null ? /*#__PURE__*/React.createElement("span", null, " · 월매출 ", /*#__PURE__*/React.createElement("b", null, "~", fmt(_anchor.monthlyRevenue), "원")) : null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, " (판매량 추정 섹션과 동일 값)")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12.5,
      fontWeight: 800,
      color: '#047857',
      marginBottom: 4
    }
  }, "💰 상위 ", topProducts.length, "개 합산 ", /*#__PURE__*/React.createElement("b", null, "시장 규모"), " (리뷰 실측 보정 — 주 수치)"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 24,
      fontWeight: 900,
      color: '#065f46',
      letterSpacing: '-0.5px'
    }
  }, fmt(_calib.lo), "~", fmt(_calib.hi), "원"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11.5,
      color: '#64748b',
      marginTop: 4,
      lineHeight: 1.6
    }
  }, "위 자사 월판매를 기준점으로 상위 ", topProducts.length, "개 상품의 순위·판매가에 적용해 재계산한 ", /*#__PURE__*/React.createElement("b", null, "시장 전체 규모"), "입니다(자사 1개 매출이 아니라 상위권 합산). 재구매·타 키워드·광고 유입이 포함된 실제 시장에 가깝습니다.")), /*#__PURE__*/React.createElement("div", {
    className: "grid3"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, _calib ? '검색 유입 기여분 (참고)' : '월간 시장 규모'), /*#__PURE__*/React.createElement("div", {
    className: "v",
    style: _calib ? {
      fontSize: 18,
      color: '#64748b'
    } : undefined
  }, estimatedMonthlyRange || estimatedMonthly || '-')), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "평균 판매가"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, avgPrice || '-')), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "적용 전환율"), /*#__PURE__*/React.createElement("div", {
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
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "순위"), /*#__PURE__*/React.createElement("th", null, "상품명"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center',
      whiteSpace: 'nowrap'
    }
  }, "CTR"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "예상 판매"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "예상 월 매출"))), /*#__PURE__*/React.createElement("tbody", null, topProducts.map(function (item, idx) {
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
    }, item.estMonthlySalesRange || item.estMonthlySales), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, item.estRevenueRange || item.estRevenue));
  })))), /*#__PURE__*/React.createElement("div", {
    className: "note est"
  }, "≈ 검색량×순위별 클릭률×전환율 기반 ", /*#__PURE__*/React.createElement("b", null, "시장 규모 추정"), "(개별 실판매 아님). 보완 후 리뷰증가 기반으로 정밀화."))));
};

;/* ===== js/components/GoldenKeywordCard.jsx ===== */
window.GoldenKeywordCard = function GoldenKeywordCard(props) {
  // 단일 객체 또는 배열 모두 처리 (data가 없어도 0건 안내를 렌더)
  var raw = props ? props.data : null;
  var items = Array.isArray(raw) ? raw : raw ? [raw] : [];
  var valid = items.filter(function (item) {
    return item && item.name && item.score !== undefined;
  });

  // 0건: 숨기지 않고 대안을 안내 (빈 표/‘없음’이 부정적으로 보이는 문제 개선)
  if (valid.length === 0) {
    return /*#__PURE__*/React.createElement("div", {
      className: "card"
    }, /*#__PURE__*/React.createElement("h3", {
      className: "rt-h3"
    }, /*#__PURE__*/React.createElement("span", {
      className: "rt-hic"
    }, "👑"), "골든 키워드 ", /*#__PURE__*/React.createElement("span", {
      className: "badge b-ok"
    }, "✅ 실측")), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '22px 20px',
        textAlign: 'center',
        background: '#f8fafc',
        borderRadius: 12,
        border: '1px dashed #e2e8f0'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 14,
        fontWeight: 700,
        color: '#475569',
        marginBottom: 6
      }
    }, "지금은 저경쟁 골든 키워드가 발견되지 않았습니다"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: '#94a3b8',
        lineHeight: 1.7
      }
    }, "골든 키워드는 ", /*#__PURE__*/React.createElement("b", null, "검색량은 있으면서 경쟁강도가 낮은"), " 키워드입니다. 대표키워드 주변에는 없지만, 아래 ", /*#__PURE__*/React.createElement("b", null, "연관 키워드"), "의 롱테일(2~3어절 조합)이나 ", /*#__PURE__*/React.createElement("b", null, "세부 상품 속성 키워드"), "로 진입하면 낮은 비용으로 상위 노출을 노릴 수 있습니다.")));
  }
  return /*#__PURE__*/React.createElement("div", {
    className: "card golden-card"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "👑"), "골든 키워드 ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅ 실측")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11.5,
      color: '#92400e',
      margin: '2px 0 10px'
    }
  }, "대표 골든 키워드 기준 — 전체 후보는 연관 키워드의 「황금 키워드」 탭 참조. 브랜드(상표)형 키워드는 상품명에 직접 쓰지 말고 광고 참고용으로만 활용하세요."), /*#__PURE__*/React.createElement("div", {
    className: "grid2"
  }, valid.map(function (item, idx) {
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
    }, "👑 ", name, /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 'auto',
        color: 'var(--est)',
        fontWeight: 900
      }
    }, "점수 ", score, "/100")), /*#__PURE__*/React.createElement("div", {
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
    }, "월 검색량"), " ", /*#__PURE__*/React.createElement("b", null, fmt(volume))), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: '12px'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--sub)'
      }
    }, "경쟁강도"), " ", /*#__PURE__*/React.createElement("b", null, competition)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: '12px'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--sub)'
      }
    }, "평균 클릭"), " ", /*#__PURE__*/React.createElement("b", null, typeof ctr === 'number' ? ctr.toFixed(1) : ctr)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: '12px'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--sub)'
      }
    }, "월 클릭수"), " ", /*#__PURE__*/React.createElement("b", null, fmt(clicks)))), /*#__PURE__*/React.createElement("div", {
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
    label: '평균 광고 개수',
    value: adDepth ? adDepth + '개' : '데이터 없음',
    unit: '',
    tip: '이 키워드로 네이버에서 검색하면 통합검색 상단 파워링크 영역에 광고가 평균 몇 개 노출되는지(네이버 검색광고 「월평균노출광고수」). 많을수록 광고 경쟁이 치열해 입찰가 부담이 큽니다.'
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
  }, "📣"), "검색광고(파워링크) 경쟁 정보", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅ 실측")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "네이버 ", /*#__PURE__*/React.createElement("b", null, "검색광고(파워링크)"), " 기준 — 통합검색 상단 광고 영역의 경쟁 환경입니다.", /*#__PURE__*/React.createElement("b", {
    style: {
      color: '#b45309'
    }
  }, " 이 화면의 쇼핑 검색 순위와는 다른 지표"), "입니다."), /*#__PURE__*/React.createElement("div", {
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
    }, item.label, item.tip && /*#__PURE__*/React.createElement("span", {
      title: item.tip,
      style: {
        marginLeft: 4,
        cursor: 'help',
        color: '#94a3b8',
        fontWeight: 800
      }
    }, "ⓘ")), /*#__PURE__*/React.createElement("div", {
      className: "rt-kpi-v",
      style: {
        fontSize: 20
      }
    }, item.value, item.unit && /*#__PURE__*/React.createElement("small", null, item.unit)));
  })), /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, /*#__PURE__*/React.createElement("b", null, "평균 광고 개수"), " = 이 키워드로 검색했을 때 ", /*#__PURE__*/React.createElement("b", null, "통합검색 상단 파워링크 영역"), "에 광고가 평균 몇 개 붙는지입니다 (네이버 검색광고 「월평균노출광고수」 원본값). 순위가 아니라 ", /*#__PURE__*/React.createElement("b", null, "개수"), "이며, 많을수록 광고 경쟁이 치열해 입찰가 부담이 큽니다.", /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      padding: '9px 12px',
      background: '#fffbeb',
      border: '1px solid #fde68a',
      borderRadius: 8,
      color: '#7c2d12'
    }
  }, "⚠️ ", /*#__PURE__*/React.createElement("b", null, "검색광고(파워링크)와 쇼핑검색은 다릅니다."), /*#__PURE__*/React.createElement("br", null), "· ", /*#__PURE__*/React.createElement("b", null, "검색광고(파워링크)"), " — 네이버 통합검색 결과 상단의 링크형 광고. 이 카드의 지표가 여기 기준입니다.", /*#__PURE__*/React.createElement("br", null), "· ", /*#__PURE__*/React.createElement("b", null, "쇼핑검색"), " — 쇼핑 탭의 상품 목록. 우리 ", /*#__PURE__*/React.createElement("b", null, "순위 추적·노출 순위"), "는 전부 이쪽 기준이며, 그 안의 광고(쇼핑검색광고)도 별개입니다.", /*#__PURE__*/React.createElement("br", null), "즉 이 숫자가 크다고 쇼핑 순위가 나쁜 것은 아닙니다 — ", /*#__PURE__*/React.createElement("b", null, "서로 다른 지면"), "입니다."), "광고 경쟁이 치열할수록 SEO(자연노출)를 병행해 광고비 효율을 확보하는 것이 유리합니다."))));
};

;/* ===== js/components/SummaryCardsSection.jsx ===== */
/* SummaryCardsSection — 종합 요약 (v6.6: 경영자 히어로 요약 + KPI 4칸)
 * 히어로: 6장에 묻혀 있던 종합 진입 점수·현재 순위를 문서 최상단으로 승격.
 *   결론 1문장 + 점수 게이지 + 추천 액션 Top3(섹션 앵커). 데이터가 없으면
 *   히어로만 조용히 생략되고 기존 KPI 카드 레이아웃이 그대로 유지된다(무손실).
 * KPI: 결측값('-'·0)은 초록 ✅ 대신 중립 '집계 없음' 배지로 강등 — 가짜 검증 인상 방지. */
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

  /* ===== 히어로 데이터 파생 (전부 기존 분석 데이터 재사용 — 신규 호출 없음) ===== */
  var adv = props.advertiserReport || null;
  var strategy = adv && adv.entry_strategy || {};
  var score = Number(strategy.overall_score) || 0;
  var ranking = adv && adv.ranking || {};
  var rank = props.rankCheckResult && props.rankCheckResult.rank_position != null ? props.rankCheckResult.rank_position : ranking.current_rank != null ? ranking.current_rank : null;
  var onPage1 = rank != null && rank > 0 && rank <= 40;
  var rating = props.htmlReviewData && props.htmlReviewData.rating != null ? props.htmlReviewData.rating : null;
  var kw = props.keyword || '';
  var scoreColor = score >= 70 ? '#34d399' : score >= 40 ? '#fbbf24' : '#f87171';
  var scoreLabel = score >= 70 ? '양호' : score >= 40 ? '보통' : '개선 필요';

  /* 결론 1문장 — 규칙 기반(실데이터만 인용) */
  var conclusion = '';
  if (rank != null && rank > 0) {
    conclusion = '현재 ' + fmt(rank) + '위' + (onPage1 ? ' (1페이지 진입)' : '');
    if (rating != null && Number(rating) >= 4.5) conclusion += ' · 리뷰 평점 ' + rating + ' 강점';
    conclusion += '. ';
  }
  if (score >= 70) conclusion += '기반이 탄탄해 상위 노출 여력이 충분합니다.';else if (score >= 40) conclusion += '핵심 항목 보완 시 순위 상승 여지가 있습니다.';else if (score > 0) conclusion += '아래 추천 액션부터 순서대로 개선이 필요합니다.';else if (rank != null) conclusion += '아래 보고서에서 항목별 상세 진단을 확인하세요.';

  /* 추천 액션 Top3 — 진입 전략의 심각도 순 상위 3개 (섹션 앵커로 연결) */
  var sevRank = {
    high: 0,
    medium: 1,
    low: 2
  };
  var actions = (strategy.strategies || []).filter(function (s) {
    return s && s.area;
  }).slice().sort(function (a, b) {
    return (sevRank[a.severity] != null ? sevRank[a.severity] : 1) - (sevRank[b.severity] != null ? sevRank[b.severity] : 1);
  }).slice(0, 3);
  var showHero = score > 0 || rank != null && rank > 0;

  /* KPI 결측 판정 — '-'·빈값·0(콤마 포맷 문자열 '0' 포함)은 중립 처리 */
  var isMissing = function (v) {
    if (v == null) return true;
    var s = String(v).trim();
    return s === '' || s === '-' || s === '0';
  };
  var Kpi = function (label, value, unit, opts) {
    opts = opts || {};
    var missing = opts.forceMissing != null ? opts.forceMissing : isMissing(value);
    return /*#__PURE__*/React.createElement("div", {
      className: "kpi"
    }, /*#__PURE__*/React.createElement("div", {
      className: "k"
    }, label, " ", missing ? /*#__PURE__*/React.createElement("span", {
      className: "badge b-n"
    }, "집계 없음") : /*#__PURE__*/React.createElement("span", {
      className: "badge b-ok"
    }, "✅")), /*#__PURE__*/React.createElement("div", {
      className: "v",
      style: {
        color: missing ? '#94a3b8' : undefined,
        fontSize: opts.fontSize
      }
    }, missing ? '—' : value, !missing && unit ? /*#__PURE__*/React.createElement("small", null, unit) : null));
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "section fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "container"
  }, showHero && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      background: 'linear-gradient(135deg, #3b82f6, #7c3aed)',
      border: 'none',
      color: '#fff',
      padding: '22px 26px',
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "rpt-flex",
    style: {
      display: 'flex',
      gap: 20,
      alignItems: 'center',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 220
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 800,
      letterSpacing: '0.14em',
      opacity: 0.8,
      marginBottom: 6
    }
  }, "핵심 결론"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 18,
      fontWeight: 800,
      lineHeight: 1.5,
      letterSpacing: '-0.2px'
    }
  }, kw ? '"' + kw + '" — ' : '', conclusion), actions.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12,
      background: 'rgba(255,255,255,0.12)',
      borderRadius: 12,
      padding: '10px 14px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 800,
      opacity: 0.85,
      marginBottom: 4
    }
  }, "지금 하면 좋은 것 Top ", actions.length), actions.map(function (s, i) {
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        fontSize: 12.5,
        fontWeight: 600,
        padding: '2px 0',
        display: 'flex',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        opacity: 0.75
      }
    }, i + 1, "."), /*#__PURE__*/React.createElement("a", {
      href: "#sec-strategy",
      style: {
        color: '#fff',
        textDecoration: 'none'
      }
    }, s.area, /*#__PURE__*/React.createElement("span", {
      style: {
        opacity: 0.65,
        fontWeight: 500,
        marginLeft: 6,
        fontSize: 11
      }
    }, s.severity === 'high' ? '긴급' : s.severity === 'low' ? '선택' : '권장', " → 진입 전략")));
  }))), score > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 84,
      height: 84,
      borderRadius: '50%',
      margin: '0 auto',
      background: 'conic-gradient(' + scoreColor + ' ' + score * 3.6 + 'deg, rgba(255,255,255,0.22) 0deg)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 64,
      height: 64,
      borderRadius: '50%',
      background: '#5b50e8',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 22,
      fontWeight: 900,
      lineHeight: 1
    }
  }, score), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      opacity: 0.8
    }
  }, "/100"))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      display: 'inline-block',
      fontSize: 11,
      fontWeight: 800,
      background: 'rgba(255,255,255,0.18)',
      borderRadius: 999,
      padding: '3px 12px'
    }
  }, "종합 진입 점수 · ", scoreLabel)))), /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "🎯"), "종합 요약"), /*#__PURE__*/React.createElement("div", {
    className: "grid4"
  }, Kpi('월간 검색량', totalVolume, '회/월'), Kpi('등록 상품수', productCount, '개'), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "골든 키워드 ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅")), /*#__PURE__*/React.createElement("div", {
    className: "v",
    style: {
      color: Number(goldenCount) === 0 ? '#f59e0b' : undefined
    }
  }, goldenCount, /*#__PURE__*/React.createElement("small", null, Number(goldenCount) === 0 ? '개 — 롱테일 권장' : '개 발견'))), Kpi('경쟁강도', compLevel, '', {
    fontSize: '22px'
  })), note && /*#__PURE__*/React.createElement("div", {
    className: "note"
  }, "💡 ", note))));
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
  var gradients = ['linear-gradient(90deg, #3b82f6, #7c3aed)', 'linear-gradient(90deg, #7c3aed, #a78bfa)', 'linear-gradient(90deg, #a78bfa, #c4b5fd)', 'linear-gradient(90deg, #c4b5fd, #ddd6fe)', 'linear-gradient(90deg, #ddd6fe, #ede9fe)'];

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
      }, item.count, "개"), "(", item.ratio, "%)")), /*#__PURE__*/React.createElement("div", {
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
  }, "🗂️"), "카테고리 등록 분석", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅ 실측")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "상위 상품들의 카테고리 분포를 파악합니다"), verdict && /*#__PURE__*/React.createElement("div", {
    className: "note ok",
    style: {
      margin: '0 0 12px'
    }
  }, verdict), categoryLevels && (categoryLevels.large?.length > 0 || categoryLevels.medium?.length > 0 || categoryLevels.small?.length > 0) && /*#__PURE__*/React.createElement("div", {
    className: "sub-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "st"
  }, "레벨별 분포 (1페이지 상품)"), categoryLevels.large && categoryLevels.large.length > 0 && /*#__PURE__*/React.createElement("div", null, categoryLevels.large.map(function (item, idx) {
    return /*#__PURE__*/React.createElement("div", {
      key: idx
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        margin: '6px 0'
      }
    }, /*#__PURE__*/React.createElement("b", null, "대분류"), " ", item.name, " ", item.ratio, "%"), /*#__PURE__*/React.createElement("div", {
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
  }, /*#__PURE__*/React.createElement("b", null, "중분류"), " ", categoryLevels.medium.map(function (item, idx) {
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
  }, /*#__PURE__*/React.createElement("b", null, "소분류"), " ", categoryLevels.small.map(function (item, idx) {
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
  }, "카테고리 전체 경로 분포 (상위 상품 기준)"), /*#__PURE__*/React.createElement("div", {
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
        color: '#3b82f6',
        marginRight: 4
      }
    }, item.count, "개"), "(", item.ratio, "%)")), /*#__PURE__*/React.createElement("div", {
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
  }, "🏷️"), "키워드 & 태그 분석"), /*#__PURE__*/React.createElement("div", {
    className: "section-line"
  }), /*#__PURE__*/React.createElement("p", {
    className: "section-subtitle"
  }, "상품명에서 자주 쓰이는 키워드를 분석합니다"), /*#__PURE__*/React.createElement("div", {
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
  }, "💬 상품명 주요 키워드 TOP ", Math.min(topKeywords.length, 15)), /*#__PURE__*/React.createElement("span", {
    style: {
      padding: '4px 12px',
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 700,
      background: 'linear-gradient(135deg, #eef2ff, #dbeafe)',
      color: '#3b82f6'
    }
  }, "총 ", fmt(totalFound), "개 발견")), /*#__PURE__*/React.createElement("div", {
    className: "table-wrap",
    style: {
      maxHeight: 340,
      overflowY: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", null, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", {
    style: {
      background: 'linear-gradient(135deg, #3b82f6, #7c3aed)'
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
  }, "키워드"), /*#__PURE__*/React.createElement("th", {
    style: {
      color: '#fff',
      fontWeight: 600,
      fontSize: 12
    }
  }, "검색량"), /*#__PURE__*/React.createElement("th", {
    style: {
      color: '#fff',
      fontWeight: 600,
      fontSize: 12
    }
  }, "경쟁도"), /*#__PURE__*/React.createElement("th", {
    style: {
      color: '#fff',
      fontWeight: 600,
      fontSize: 12
    }
  }, "비중"))), /*#__PURE__*/React.createElement("tbody", null, topKeywords.map(function (kw, idx) {
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
        background: kw.isGolden ? 'linear-gradient(135deg, #f59e0b, #d97706)' : 'linear-gradient(135deg, #3b82f6, #7c3aed)',
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
    }, "👑")), /*#__PURE__*/React.createElement("td", {
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
        background: kw.isGolden ? 'linear-gradient(135deg, #f59e0b, #d97706)' : 'linear-gradient(135deg, #3b82f6, #7c3aed)',
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
  }, "🛡️"), "SEO 적합도 · 신뢰도 · 인기도", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "≈ 추정")), /*#__PURE__*/React.createElement("div", {
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
      }, "✔") : /*#__PURE__*/React.createElement("span", {
        className: "n"
      }, "✘"), ' ', item.label);
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
  }, "✏️"), "상품명 SEO 최적화 ", /*#__PURE__*/React.createElement("span", {
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
  }, "현재"), /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("b", null, currentName)), issues && issues.map((item, idx) => /*#__PURE__*/React.createElement("div", {
    key: idx,
    className: "check"
  }, /*#__PURE__*/React.createElement("span", {
    className: item.pass ? 'y' : 'n'
  }, item.pass ? '✔' : '✘'), ' ', item.text)), suggestedName && /*#__PURE__*/React.createElement("div", {
    className: "note",
    style: {
      borderLeftColor: '#ec4899'
    }
  }, /*#__PURE__*/React.createElement("b", null, "✏️ 제안"), /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("b", null, suggestedName), marketerComment && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("br", null), marketerComment)))));
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
  }, "⭐"), "리뷰 & 찜 분석", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅ 실측")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "광고주 상품 vs 경쟁 평균 vs 상위 5개 비교"), function () {
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
          backgroundColor: C.IND || '#3b82f6',
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

  /* 리뷰 실문장 카피 후보 — 긍정 리뷰에서 실제 문장 추출(문구 창작이 아니라 구매자 표현 인용) */
  var positiveKw = (data.positiveKeywords || []).map(function (k) {
    return k.keyword;
  }).filter(Boolean);
  var pickSentence = function (text) {
    var parts = String(text || '').split(/[.!?\n·•]|다\s|요\s/).map(function (s) {
      return s.trim();
    }).filter(function (s) {
      return s.length >= 6 && s.length <= 45;
    });
    for (var i = 0; i < parts.length; i++) {
      for (var j = 0; j < positiveKw.length; j++) {
        if (positiveKw[j] && parts[i].indexOf(positiveKw[j]) >= 0) return parts[i];
      }
    }
    return parts[0] || null;
  };
  var _seen = {};
  var copyCandidates = [];
  (reviews || []).forEach(function (r) {
    if (copyCandidates.length >= 5) return;
    if (!r || !r.text) return;
    if (!(r.sentiment === 'positive' || (Number(r.rating) || 0) >= 4)) return;
    var s = pickSentence(r.text);
    if (!s) return;
    var key = s.replace(/\s/g, '');
    if (_seen[key]) return;
    _seen[key] = 1;
    copyCandidates.push({
      copy: s,
      rating: r.rating
    });
  });
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
  }, '전체 ' + fmt(totalReviewCount) + '건 중 표본 ' + fmt(data.totalExtracted) + '건' + (totalReviewCount > 0 ? function () {
    var pct = data.totalExtracted / totalReviewCount * 100;
    return ' (' + (pct > 0 && pct < 1 ? '<1' : Math.round(pct)) + '%)';
  }() : '')) : null), /* 평균 별점 */
  React.createElement('div', {
    className: 'kpi'
  }, React.createElement('div', {
    className: 'k'
  }, '평균 별점'), React.createElement('div', {
    className: 'v',
    style: {
      fontSize: 20
    }
  }, data.avgRating, React.createElement('small', null, '★'))), /* 긍정 비율 (소표본이면 참고용 표기 — 별점과 어긋난 단정 방지) */
  React.createElement('div', {
    className: 'kpi'
  }, React.createElement('div', {
    className: 'k'
  }, '긍정 비율' + ((Number(data.totalExtracted) || 0) < 10 ? ' (표본 적음·참고용)' : '')), React.createElement('div', {
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
        color: '#3b82f6',
        fontWeight: 700
      }
    }, '→'), insight);
  }))) : null, /* 4-1. 리뷰 기반 카피 후보 (구매자 실제 표현) */
  copyCandidates.length > 0 ? React.createElement('div', {
    className: 'sub-card'
  }, React.createElement('div', {
    className: 'st'
  }, '📝 리뷰 기반 카피 후보'), React.createElement('div', {
    style: {
      fontSize: 11.5,
      color: '#94a3b8',
      marginBottom: 10
    }
  }, '구매자가 실제 남긴 긍정 리뷰 문장입니다. 상세페이지·광고 카피 소재로 활용하세요(과장 없이 실제 표현 그대로).'), React.createElement('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, copyCandidates.map(function (c, i) {
    return React.createElement('div', {
      key: 'copy-' + i,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '10px 14px',
        background: '#f0fdf4',
        border: '1px solid #bbf7d0',
        borderRadius: 10
      }
    }, React.createElement('span', {
      style: {
        color: '#f59e0b',
        fontSize: 12,
        flexShrink: 0
      }
    }, stars(c.rating)), React.createElement('span', {
      style: {
        fontSize: 13,
        fontWeight: 600,
        color: '#166534',
        lineHeight: 1.5
      }
    }, '"' + c.copy + '"'));
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
  }, React.createElement('span', null, '📋'), '추출된 리뷰 목록 (표본 분석)', React.createElement('span', {
    style: {
      fontSize: 11,
      fontWeight: 500,
      color: '#94a3b8',
      marginLeft: 4
    }
  }, totalReviewCount ? '전체 ' + fmt(totalReviewCount) + '건 중 ' + reviews.length + '건 표본' : '(HTML에서 추출된 ' + reviews.length + '건)')), React.createElement('div', {
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
  }, "📄"), "상세페이지 품질 점수", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "≈ 추정")), /*#__PURE__*/React.createElement("div", {
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
  }, "평가 체크리스트"), checklist.map((category, cidx) => category.items && category.items.map((item, iidx) => /*#__PURE__*/React.createElement("div", {
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
  }, "🖼️"), "상세페이지 HTML 분석", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "≈ 추정")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "실제 HTML에서 추출한 데이터 기반 정밀 진단"), /*#__PURE__*/React.createElement("div", {
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
  }, "/100 · ", getScoreLabel(total))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(ScoreBar, {
    label: "이미지",
    score: data.scores.images,
    weight: "30%"
  }), /*#__PURE__*/React.createElement(ScoreBar, {
    label: "텍스트",
    score: data.scores.text,
    weight: "20%"
  }), /*#__PURE__*/React.createElement(ScoreBar, {
    label: "동영상",
    score: data.scores.video,
    weight: "15%"
  }), /*#__PURE__*/React.createElement(ScoreBar, {
    label: "정보 완성도",
    score: data.scores.info,
    weight: "20%"
  }), /*#__PURE__*/React.createElement(ScoreBar, {
    label: "신뢰 요소",
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
    }, "필수 항목 체크리스트"), /*#__PURE__*/React.createElement("div", {
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
  }, /*#__PURE__*/React.createElement("b", null, "개선 제안"), data.suggestions.map((s, i) => /*#__PURE__*/React.createElement("span", {
    key: 'dp-sug-' + i
  }, ' · ', /*#__PURE__*/React.createElement("span", {
    className: 'sev ' + (s.priority === 'high' ? 'high' : s.priority === 'medium' ? 'med' : 'low')
  }, priorityLabel(s.priority)), ' ', s.area ? s.area + ' — ' : '', s.text))))));
};

;/* ===== js/components/SalesEstimationSection.jsx ===== */
/* SalesEstimationSection — 판매량 추정 & 성장 시뮬레이션 (v5) */
window.SalesEstimationSection = function SalesEstimationSection(props) {
  /* [2단계] 리뷰 증가 실측 — 같은 상품의 과거 분석 스냅샷 델타(hooks는 조기 return 이전) */
  var _tr = React.useState(null);
  var trend = _tr[0];
  var setTrend = _tr[1];
  var _url = props.productUrl || '';
  React.useEffect(function () {
    setTrend(null);
    if (!_url) return;
    var alive = true;
    api.get('/cd/review-trend?product_url=' + encodeURIComponent(_url)).then(function (res) {
      if (alive && res && res.success && res.data && res.data.available) setTrend(res.data);
    }).catch(function () {});
    return function () {
      alive = false;
    };
  }, [_url]);
  if (!props?.data) return null;
  const {
    avgPrice,
    monthlySearches,
    estimatedCTR,
    top10Card,
    page1Card,
    page2Card,
    simulations,
    tolerance
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
  }, "📦"), "판매량 추정 & 성장 시뮬레이션", /*#__PURE__*/React.createElement("span", {
    className: "badge b-est"
  }, "≈ 추정"), tolerance ? /*#__PURE__*/React.createElement("span", {
    className: "badge b-est",
    style: {
      marginLeft: 6
    }
  }, tolerance) : null), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "순위별 예상 판매량과 매출 성장 시나리오"), /*#__PURE__*/React.createElement("div", {
    className: "grid3",
    style: {
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "상위10 평균가"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, avgPrice)), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "월간 검색량"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, monthlySearches)), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "예상 전환율"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, estimatedCTR))), props.reviewCount != null && props.reviewCount > 0 && window.reviewAnchorEstimate && function () {
    var est = window.reviewAnchorEstimate(props.reviewCount, props.productPrice);
    if (!est) return null;
    var rc = est.reviewCount;
    var cumSales = est.cumSales;
    var monthly = est.monthlyUnits;
    return /*#__PURE__*/React.createElement("div", {
      className: "note ok",
      style: {
        marginTop: 0,
        marginBottom: 20
      }
    }, /*#__PURE__*/React.createElement("b", null, "🧾 리뷰 기반 추정 (주 수치)"), " — 실제 누적 리뷰 ", /*#__PURE__*/React.createElement("b", null, fmt(rc), "건"), " 기반.", est.monthlyRevenue != null ? /*#__PURE__*/React.createElement("b", null, " 월 매출 환산 ~", fmt(est.monthlyRevenue), "원") : null, "추정 누적 판매 ", /*#__PURE__*/React.createElement("b", null, "~", fmt(cumSales), "건"), ", 월 환산 ", /*#__PURE__*/React.createElement("b", null, "~", fmt(monthly), "건"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#64748b'
      }
    }, " (작성률 11.6% · 운영 12개월 가정). 아래 순위 기반 시나리오는 참고용입니다."), trend && /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 6,
        fontSize: 12.5
      }
    }, "📈 ", /*#__PURE__*/React.createElement("b", null, "실측 리뷰 증가 기반"), " — 최근 ", trend.days, "일간 리뷰 +", fmt(trend.review_delta), "건 → 월판매 ", /*#__PURE__*/React.createElement("b", null, "~", fmt(trend.monthly_sales_est), "건"), props.productPrice > 0 ? /*#__PURE__*/React.createElement("b", null, " · 월 매출 ~", fmt(trend.monthly_sales_est * props.productPrice), "원") : null, /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#64748b'
      }
    }, " (", trend.from_date, "~", trend.to_date, " 분석 기록 비교 — 기간이 쌓일수록 정확해집니다)")));
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
        backgroundColor: [C.OK || '#16a34a', C.IND || '#3b82f6', '#cbd5e1'],
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
  }, "🏆 TOP 10 (1~10위)"), /*#__PURE__*/React.createElement("span", {
    style: {
      padding: '4px 12px',
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 700,
      background: 'rgba(255,255,255,0.25)',
      color: '#fff'
    }
  }, "핵심 구간")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "1위 예상 판매"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#d97706'
    }
  }, fmt(top10Card.rank1Sales), "건")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "5위 예상 판매"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#d97706'
    }
  }, fmt(top10Card.rank5Sales), "건")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "10위 예상 판매"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#d97706'
    }
  }, fmt(top10Card.rank10Sales), "건")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "1위 예상 매출"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#d97706'
    }
  }, top10Card.rank1Revenue)), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRowLast
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "10위 예상 매출"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#d97706'
    }
  }, top10Card.rank10Revenue)), /*#__PURE__*/React.createElement("div", {
    style: v5TotalRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5TotalLabel
  }, "TOP10 합산 매출"), /*#__PURE__*/React.createElement("span", {
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
      background: 'linear-gradient(135deg, #3b82f6, #7c3aed)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      fontWeight: 700,
      color: '#fff'
    }
  }, "📄 1페이지 (1~40위)"), /*#__PURE__*/React.createElement("span", {
    style: {
      padding: '4px 12px',
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 700,
      background: 'rgba(255,255,255,0.25)',
      color: '#fff'
    }
  }, "1페이지")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "평균 판매량"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#3b82f6'
    }
  }, fmt(page1Card.avgSales), "건/월")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "총 예상 판매"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#3b82f6'
    }
  }, fmt(page1Card.totalSales), "건/월")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "최고 매출 (1위)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#3b82f6'
    }
  }, page1Card.maxRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "최저 매출 (40위)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#3b82f6'
    }
  }, page1Card.minRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRowLast
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "평균 매출"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#3b82f6'
    }
  }, page1Card.avgRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5TotalRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5TotalLabel
  }, "1페이지 합산 매출"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 15,
      fontWeight: 800,
      color: '#3b82f6'
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
  }, "📄 2페이지 (41~80위)"), /*#__PURE__*/React.createElement("span", {
    style: {
      padding: '4px 12px',
      borderRadius: 999,
      fontSize: 12,
      fontWeight: 700,
      background: 'rgba(255,255,255,0.25)',
      color: '#fff'
    }
  }, "2페이지")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "평균 판매량"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#475569'
    }
  }, fmt(page2Card.avgSales), "건/월")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "총 예상 판매"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#475569'
    }
  }, fmt(page2Card.totalSales), "건/월")), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "최고 매출 (41위)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#475569'
    }
  }, page2Card.maxRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "최저 매출 (80위)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#475569'
    }
  }, page2Card.minRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5MetricRowLast
  }, /*#__PURE__*/React.createElement("span", {
    style: v5MetricLabel
  }, "평균 매출"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#475569'
    }
  }, page2Card.avgRevenue)), /*#__PURE__*/React.createElement("div", {
    style: v5TotalRow
  }, /*#__PURE__*/React.createElement("span", {
    style: v5TotalLabel
  }, "2페이지 합산 매출"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 15,
      fontWeight: 800,
      color: '#475569'
    }
  }, page2Card.totalRevenue))))), simulations && simulations.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "sub-card",
    style: {
      marginTop: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "st"
  }, "📊 순위별 추정 범위 (전환율 밴드 ", tolerance || '', ")"), /*#__PURE__*/React.createElement("table", {
    className: "rt-table"
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "순위"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "예상 판매(건/월)"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "예상 매출(월)"))), /*#__PURE__*/React.createElement("tbody", null, simulations.map(function (sim, idx) {
    return /*#__PURE__*/React.createElement("tr", {
      key: idx
    }, /*#__PURE__*/React.createElement("td", null, sim.rank, "위"), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, sim.estSalesRange || sim.estSales), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, sim.revenueRange || sim.revenue));
  })))), /*#__PURE__*/React.createElement("div", {
    className: "note est"
  }, "⚠️ 순위별 클릭률(CTR)을 기반으로 추정한 값이며, 실제 판매량은 상품 경쟁력, 리뷰, 가격 등에 따라 달라질 수 있습니다."), props.reviewCount != null && props.reviewCount > 0 && props.productPrice > 0 && function () {
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
    }, "🧾 리뷰 증가 기반 추정 (작성률 식품 11.6%)"), /*#__PURE__*/React.createElement("table", {
      className: "rt-table"
    }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "가정"), periods.map(function (m) {
      return /*#__PURE__*/React.createElement("th", {
        key: m,
        style: {
          textAlign: 'right'
        }
      }, m, "개월");
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
        }, "~", fmt(Math.round(totalSales / 12 * m)), "건");
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
  }, "🏆"), "경쟁사 비교표 (상위 노출 80개 중)", /*#__PURE__*/React.createElement("span", {
    className: "badge b-ok"
  }, "✅ 실측")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "상위 노출 상품들의 핵심 지표를 비교합니다"), hasScore && /*#__PURE__*/React.createElement("div", {
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
  }, "💡 종합점수가 높을수록 네이버 쇼핑 노출 순위가 높아지는 경향이 있습니다. 상품명·가격·리뷰·판매실적 등 10개 지표를 가중 합산한 점수입니다."), /*#__PURE__*/React.createElement("div", {
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
  }, "순위"), hasScore && /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'center',
      width: 70
    }
  }, "종합점수"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'center',
      width: 50
    }
  }, "이미지"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'left'
    }
  }, "상품명"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'left',
      width: 90
    }
  }, "판매처"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'left',
      width: 90
    }
  }, "브랜드"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'right',
      width: 100
    }
  }, "가격"), /*#__PURE__*/React.createElement("th", {
    style: {
      padding: '14px 16px',
      fontSize: 13,
      fontWeight: 600,
      textAlign: 'left',
      width: 100
    }
  }, "카테고리"))), /*#__PURE__*/React.createElement("tbody", null, items.map(function (comp, idx) {
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
  /* part 분할 렌더 (v6.6): 'competition'=경쟁사 비교·격차(3장) / 'strategy'=점수·전략 제안(6장)
   * 미지정('all')이면 기존과 동일하게 전체 렌더 — 하위 호환 보장 */
  var part = props.part || 'all';
  var showComp = part !== 'strategy';
  var showStrat = part !== 'competition';
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

  /* 경쟁 파트만 요청됐는데 보여줄 경쟁 데이터가 없으면 빈 카드 방지 */
  if (part === 'competition' && !advertiserData && !mainBrands) return null;
  return React.createElement('div', {
    id: part === 'competition' ? 'sec-strategy-comp' : 'sec-strategy',
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
  }, part === 'competition' ? '🏆' : '🧭'), part === 'competition' ? '경쟁사 비교 · 격차 분석' : '1페이지 진입 전략 비교 분석'), React.createElement('div', {
    className: 'rt-desc'
  }, part === 'competition' ? '상위 노출 경쟁사와 내 상품의 격차를 진단합니다' : '경쟁사 데이터 기반 1페이지 진입 전략을 제안합니다'), /* === 상품 정보 헤더 (광고주 데이터가 있을 때만) === */
  showComp && advertiserData && React.createElement('div', {
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
  showStrat && advertiserData && React.createElement('div', {
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
  }, (compStats.keyword_in_name_ratio != null ? compStats.keyword_in_name_ratio : '-') + '%'))))), /* === 경쟁사 상위 10개 비교표 === */
  showComp && React.createElement('div', {
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
  }, '\uD83C\uDFC6'), ' 경쟁사 상위 10개 비교표'), /* 시장 요약 v5 MetricCard */
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
  }, '1P 평균가'), React.createElement('div', {
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
      color: '#3b82f6'
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
      background: 'linear-gradient(135deg, #3b82f6, #7c3aed)'
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
        color: '#3b82f6',
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
        color: '#3b82f6',
        border: '1px solid #c7d2fe'
      }
    }, brand);
  }))))), /* === 내 상품 vs 경쟁사 격차 분석 === */
  showComp && gapAnalysis && React.createElement('div', {
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
  }, '\uD83D\uDCCA'), ' 내 상품 vs 경쟁사 격차 분석'), /* 격차 요약 v5 MetricCard */
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
  }, gapAnalysis.priceDiffPct <= -10 ? '경쟁사 대비 저렴' : gapAnalysis.priceDiffPct <= 0 ? '적정 가격대' : gapAnalysis.priceDiffPct <= 10 ? '소폭 비쌈' : '비쌈 → 쿠폰·기획전으로 상쇄 권장 (진입 전략 참조)')), /* 상위3개 vs 내 가격 */
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
  }))), /* === AI 기반 맞춤 진입 전략 제안 === */
  showStrat && strategies.length > 0 && React.createElement('div', {
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
  }, '\uD83E\uDD16'), ' AI 기반 맞춤 진입 전략 제안'), /* 전략 카드들 — 시안 .strat + .st + .sev */
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
        color: '#3b82f6',
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
          background: '#3b82f6',
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
  showStrat && !advertiserData && recommendation && React.createElement('div', {
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
  }, recommendation)), /* 분석 시각 (전략 파트에만 — 분할 렌더 시 중복 방지) */
  showStrat && React.createElement('div', {
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
    color: '#3b82f6',
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
        color: active ? '#3b82f6' : '#64748b',
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
        background: active ? '#3b82f6' : 'transparent',
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
        background: isHov ? 'linear-gradient(180deg, #3b82f6, #3b82f6)' : i >= chartData.length - 5 ? 'linear-gradient(180deg, #818cf8, #3b82f6)' : 'linear-gradient(180deg, #c7d2fe, #a5b4fc)',
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
      background: 'linear-gradient(90deg, #818cf8, #3b82f6)',
      borderRadius: 3
    }
  })), React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#3b82f6',
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
        color: '#3b82f6'
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
        background: '#3b82f6',
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
      color: '#3b82f6',
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
        color: '#3b82f6',
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

;/* ===== js/components/CompetitorCompareSection.jsx ===== */
/* CompetitorCompareSection — 광고주 vs 경쟁사 비교 분석 (1차 + AI 대결 코칭)
 *
 * 업체(광고주) 상세 안에 렌더. 경쟁사 등록(광고주와 동일 분석 흐름 재사용)·목록·삭제 +
 * 선택한 경쟁사와의 좌우 비교(핵심지표·종합 레이더·키워드 갭·따라가야 할 것) + AI 코칭.
 *
 * 무손실 원칙: 경쟁사 미등록/데이터 없음이면 슬롯만 조용히 표시(기존 화면 무영향).
 * 저장된 분석 JSON 구조가 조금씩 달라도 방어적으로 추출(없으면 '집계 없음').
 */
window.CompetitorCompareSection = function CompetitorCompareSection(props) {
  var advClient = props.client; // 선택된 광고주 업체
  var canEdit = props.canEdit !== false;
  var onRegisterCompetitor = props.onRegisterCompetitor; // 경쟁사 등록 모드 진입(App)
  var _R = React;
  var comps = _R.useState([]);
  var competitors = comps[0];
  var setCompetitors = comps[1];
  var sel = _R.useState(null);
  var selectedId = sel[0];
  var setSelectedId = sel[1];
  var cmp = _R.useState(null);
  var compareData = cmp[0];
  var setCompareData = cmp[1];
  var ld = _R.useState(false);
  var loading = ld[0];
  var setLoading = ld[1];
  var coach = _R.useState(null);
  var coaching = coach[0];
  var setCoaching = coach[1];
  var coachLd = _R.useState(false);
  var coachLoading = coachLd[0];
  var setCoachLoading = coachLd[1];
  var advId = advClient && advClient.id;
  /* 영업사원(viewer)은 앵커가 '광고주'가 아니라 '영업 대상'(prospect) — 라벨을 바꾼다 */
  var isViewer = props.isViewer;
  var anchorLabel = isViewer ? '영업 대상' : '광고주';
  /* 경쟁사 등록·삭제 권한: 관리팀(canEdit)뿐 아니라 영업사원도 '본인 영업 대상'에는
     경쟁사를 붙이고 지울 수 있어야 한다(완전 개인 모드). viewer는 스코핑으로 본인 것만 봄. */
  var canManageComp = canEdit || isViewer;
  var loadCompetitors = function () {
    if (!advId) return;
    api.get('/cd/' + advId + '/competitors').then(function (res) {
      if (res && res.success) setCompetitors(res.data || []);
    }).catch(function () {});
  };
  _R.useEffect(function () {
    setCompetitors([]);
    setSelectedId(null);
    setCompareData(null);
    setCoaching(null);
    loadCompetitors();
  }, [advId]);

  /* ── 방어적 지표 추출 (저장된 분석 1건 → 표준 지표) ── */
  function num(v) {
    var n = parseInt(String(v == null ? '' : v).replace(/[^0-9.-]/g, ''), 10);
    return isNaN(n) ? null : n;
  }
  function metrics(analysis) {
    var a = analysis && analysis.analysis_data || {};
    var adv = analysis && analysis.advertiser_data || {};
    var vol = analysis && analysis.volume_data || [];
    var v0 = Array.isArray(vol) && vol[0] || {};
    var hd = a.htmlDetail && a.htmlDetail.reviewData || {};
    var ra = a.reviewAnalysis || {};
    var rc = ra.reviewCount || {};
    var rt = ra.rating || {};
    var rank = adv.ranking && adv.ranking.current_rank != null ? adv.ranking.current_rank : null;
    var price = adv.product_info && adv.product_info.price ? adv.product_info.price : a.marketRevenue && num(a.marketRevenue.avgPrice);
    var reviews = hd.reviewCount != null ? hd.reviewCount : rc.adv != null ? rc.adv : null;
    var rating = hd.rating != null ? hd.rating : rt.adv != null ? Number(rt.adv) : null;
    var score = adv.entry_strategy && adv.entry_strategy.overall_score || null;
    var dq = a.detailPageQuality && (a.detailPageQuality.totalScore || a.detailPageQuality.score) || null;
    var name = adv.product_info && adv.product_info.product_name || a.targetProductInfo && a.targetProductInfo.product_name || '';
    var relKw = (analysis && analysis.related_data && analysis.related_data.related_keywords || []).map(function (k) {
      return typeof k === 'string' ? k : k && k.keyword || '';
    }).filter(Boolean);
    return {
      keyword: analysis ? analysis.keyword : '',
      productName: name,
      rank: rank,
      price: price ? Number(price) : null,
      reviews: reviews != null ? Number(reviews) : null,
      rating: rating,
      score: score ? Number(score) : null,
      detailQuality: dq ? Number(dq) : null,
      compIdx: v0.compIdx || '',
      relatedKeywords: relKw
    };
  }
  var runCompare = function (competitorId) {
    setSelectedId(competitorId);
    setCompareData(null);
    setCoaching(null);
    setLoading(true);
    api.get('/cd/compare?advertiser_id=' + advId + '&competitor_id=' + competitorId).then(function (res) {
      setLoading(false);
      if (res && res.success && res.data) {
        var d = res.data;
        setCompareData({
          advName: d.advertiser.name,
          compName: d.competitor.name,
          adv: metrics(d.advertiser.analysis),
          comp: metrics(d.competitor.analysis),
          advHas: !!d.advertiser.analysis,
          compHas: !!d.competitor.analysis
        });
      }
    }).catch(function () {
      setLoading(false);
    });
  };
  var handleDeleteCompetitor = function (cid, cname) {
    if (!confirm("경쟁사 '" + cname + "'를 삭제할까요? 비교 데이터가 사라집니다.")) return;
    api.del('/cd/' + cid).then(function () {
      try {
        toast.success("경쟁사 '" + cname + "' 삭제됨");
      } catch (e) {}
      if (selectedId === cid) {
        setSelectedId(null);
        setCompareData(null);
      }
      loadCompetitors();
    }).catch(function (e) {
      try {
        toast.error('삭제 실패');
      } catch (e2) {}
    });
  };

  /* ── 비교 계산 (격차·우열) ── */
  function fmtWon(v) {
    return v == null ? '집계 없음' : fmt(v) + '원';
  }
  function pct(a, b) {
    if (a == null || b == null || b === 0) return null;
    return Math.round((a - b) / Math.abs(b) * 100);
  }
  function buildRows(c) {
    var A = c.adv,
      B = c.comp;
    // higherBetter: true면 값 클수록 광고주 우세
    var defs = [{
      k: '노출 순위',
      a: A.rank,
      b: B.rank,
      fmt: function (v) {
        return v == null ? '집계 없음' : v + '위';
      },
      higher: false
    }, {
      k: '판매가',
      a: A.price,
      b: B.price,
      fmt: fmtWon,
      higher: false
    }, {
      k: '리뷰 수',
      a: A.reviews,
      b: B.reviews,
      fmt: function (v) {
        return v == null ? '집계 없음' : fmt(v) + '건';
      },
      higher: true
    }, {
      k: '평점',
      a: A.rating,
      b: B.rating,
      fmt: function (v) {
        return v == null ? '집계 없음' : Number(v).toFixed(1);
      },
      higher: true
    }, {
      k: '종합 진입 점수',
      a: A.score,
      b: B.score,
      fmt: function (v) {
        return v == null ? '집계 없음' : v + '점';
      },
      higher: true
    }, {
      k: '상세페이지 품질',
      a: A.detailQuality,
      b: B.detailQuality,
      fmt: function (v) {
        return v == null ? '집계 없음' : v + '점';
      },
      higher: true
    }];
    return defs.map(function (d) {
      var advWin = null,
        gap = null;
      if (d.a != null && d.b != null) {
        advWin = d.higher ? d.a >= d.b : d.a <= d.b;
        gap = pct(d.a, d.b);
      }
      return {
        label: d.k,
        aStr: d.fmt(d.a),
        bStr: d.fmt(d.b),
        advWin: advWin,
        gap: gap,
        higher: d.higher,
        a: d.a,
        b: d.b
      };
    });
  }

  /* 따라가야 할 것 — 경쟁사가 앞선(광고주 열세) 지표를 격차 큰 순으로 */
  function catchUp(rows) {
    var acts = {
      '리뷰 수': '체험단·구매후기 이벤트로 리뷰 확보',
      '종합 진입 점수': '상품명·태그·상세페이지 SEO 보강',
      '상세페이지 품질': '이미지·성분표·인증마크 등 상세 콘텐츠 보강',
      '노출 순위': '위 항목 개선 + 파워링크 상위 입찰 병행',
      '평점': '리뷰 관리·CS 개선으로 평점 방어'
    };
    return rows.filter(function (r) {
      return r.advWin === false;
    }).sort(function (x, y) {
      return Math.abs(y.gap || 0) - Math.abs(x.gap || 0);
    }).slice(0, 4).map(function (r) {
      return {
        label: r.label,
        gapStr: r.gap != null ? (r.gap > 0 ? '+' : '') + r.gap + '%' : '',
        act: acts[r.label] || '개선 필요'
      };
    });
  }
  function strengths(rows) {
    return rows.filter(function (r) {
      return r.advWin === true;
    }).map(function (r) {
      return r.label;
    });
  }

  /* 키워드 커버리지 갭 — 경쟁사 연관 키워드 중 광고주에 없는 것 */
  function coverageGap(c) {
    var advSet = {};
    (c.adv.relatedKeywords || []).forEach(function (k) {
      advSet[k] = 1;
    });
    return (c.comp.relatedKeywords || []).filter(function (k) {
      return !advSet[k];
    }).slice(0, 8);
  }

  /* 레이더 5축 점수(0~100) — 저장 지표에서 파생 (없으면 50 중립) */
  function radarScores(m, other) {
    function rankScore(r) {
      return r == null ? 50 : Math.max(0, Math.min(100, Math.round(100 - (r - 1) * 1.1)));
    }
    function relPrice(p, q) {
      if (p == null || q == null) return 50;
      return p <= q ? 70 + Math.min(25, Math.round((q - p) / q * 100)) : 50 - Math.min(30, Math.round((p - q) / q * 100));
    }
    function trust(rev, rat) {
      var s = 40;
      if (rev != null) s = Math.min(90, 30 + Math.round(Math.log10(Math.max(1, rev)) * 18));
      if (rat != null) s += Math.round((rat - 4.5) * 20);
      return Math.max(0, Math.min(100, s));
    }
    return [rankScore(m.rank), relPrice(m.price, other.price), trust(m.reviews, m.rating), m.score != null ? m.score : 50, m.detailQuality != null ? m.detailQuality : 50];
  }
  var requestCoaching = function () {
    if (!compareData) return;
    setCoachLoading(true);
    setCoaching(null);
    var rows = buildRows(compareData);
    var summary = rows.map(function (r) {
      return '- ' + r.label + ': ' + anchorLabel + ' ' + r.aStr + ' / 경쟁사 ' + r.bStr + (r.advWin == null ? '' : r.advWin ? ' (' + anchorLabel + ' 우세)' : ' (경쟁사 우세' + (r.gap != null ? ', 격차 ' + r.gap + '%' : '') + ')');
    }).join('\n');
    var gap = coverageGap(compareData);
    if (gap.length) summary += '\n- ' + anchorLabel + '가 놓친 경쟁사 키워드: ' + gap.join(', ');
    api.post('/cd/compare-coaching', {
      advertiser_id: advId,
      competitor_id: selectedId,
      summary: summary
    }).then(function (res) {
      setCoachLoading(false);
      if (res && res.success && res.data) setCoaching(res.data);
    }).catch(function () {
      setCoachLoading(false);
      setCoaching({
        available: false,
        message: 'AI 코칭 생성 실패'
      });
    });
  };

  /* ─────────── 렌더 ─────────── */
  if (!advId) return null;
  var C = window.React.createElement;

  /* 슬롯(등록·목록) */
  var slot = C('div', {
    className: 'card',
    style: {
      padding: '16px 20px',
      marginBottom: 16,
      border: '1px solid #fed7aa',
      background: 'linear-gradient(120deg,#fff,#fff7ed)'
    }
  }, C('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 10
    }
  }, C('span', {
    style: {
      fontSize: 15,
      fontWeight: 800,
      color: '#c2410c'
    }
  }, isViewer ? '⚔️ 경쟁사 비교 (내 영업자료)' : '⚔️ 경쟁사 비교'), C('span', {
    style: {
      fontSize: 11.5,
      color: '#94a3b8'
    }
  }, isViewer ? '— 내가 등록한 경쟁사만 표시 (30일 후 자동 삭제)' : '— 광고주와 나란히 비교할 상대를 등록하세요')), competitors.length === 0 ? C('div', {
    style: {
      fontSize: 12.5,
      color: '#94a3b8',
      padding: '4px 0 10px'
    }
  }, '등록된 경쟁사가 없습니다.') : C('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      marginBottom: 10
    }
  }, competitors.map(function (cc) {
    var isSel = selectedId === cc.id;
    return C('div', {
      key: cc.id,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        background: isSel ? '#fff7ed' : '#fff',
        border: '1px solid ' + (isSel ? '#fdba74' : '#fed7aa'),
        borderRadius: 10,
        padding: '8px 12px'
      }
    }, C('div', {
      style: {
        minWidth: 0,
        flex: 1
      }
    }, C('div', {
      style: {
        fontWeight: 700,
        fontSize: 13,
        color: '#0f172a'
      }
    }, cc.name, !isViewer && cc.mine && C('span', {
      style: {
        marginLeft: 6,
        fontSize: 10,
        fontWeight: 800,
        color: '#4338ca',
        background: '#eef2ff',
        border: '1px solid #c7d2fe',
        borderRadius: 99,
        padding: '1px 7px'
      }
    }, '내 등록'), cc.days_left != null && C('span', {
      title: '영업사원 등록분 — 자동 삭제 예정',
      style: {
        marginLeft: 6,
        fontSize: 10,
        fontWeight: 800,
        color: '#c2410c',
        background: '#fff7ed',
        border: '1px solid #fed7aa',
        borderRadius: 99,
        padding: '1px 7px'
      }
    }, '⏳ ' + cc.days_left + '일 후 삭제')), C('div', {
      style: {
        fontSize: 11,
        color: '#94a3b8'
      }
    }, cc.has_analysis ? '키워드: ' + (cc.latest_keyword || '-') + ' · ' + (cc.latest_date || '') : '분석 기록 없음 — 경쟁사 상품을 분석해 저장하세요')), C('button', {
      onClick: function () {
        runCompare(cc.id);
      },
      disabled: !cc.has_analysis,
      style: {
        fontSize: 11.5,
        fontWeight: 800,
        color: '#fff',
        background: cc.has_analysis ? '#c2410c' : '#cbd5e1',
        border: 'none',
        borderRadius: 8,
        padding: '6px 12px',
        cursor: cc.has_analysis ? 'pointer' : 'not-allowed'
      }
    }, '⚔️ 비교'), canManageComp && C('button', {
      onClick: function () {
        handleDeleteCompetitor(cc.id, cc.name);
      },
      title: '경쟁사 삭제',
      style: {
        fontSize: 12,
        fontWeight: 800,
        color: '#dc2626',
        background: '#fff',
        border: '1px solid #fecaca',
        borderRadius: 8,
        width: 28,
        height: 28,
        cursor: 'pointer'
      }
    }, '✕'));
  })), canManageComp && C('button', {
    onClick: function () {
      if (onRegisterCompetitor) onRegisterCompetitor(advClient);
    },
    style: {
      fontSize: 12.5,
      fontWeight: 800,
      color: '#c2410c',
      background: '#fff',
      border: '1.5px dashed #fdba74',
      borderRadius: 10,
      padding: '9px 14px',
      cursor: 'pointer',
      width: '100%'
    }
  }, isViewer ? '➕ 상위노출 경쟁사 등록 (분석 화면으로 이동 → 경쟁사 상품 분석 → 저장)' : '➕ 경쟁사 등록 (분석 화면에서 경쟁사 상품을 분석 → 저장)'));
  var body = null;
  if (loading) {
    body = C('div', {
      className: 'card',
      style: {
        padding: 24,
        textAlign: 'center',
        color: '#64748b',
        fontSize: 13
      }
    }, '비교 데이터를 불러오는 중…');
  } else if (compareData) {
    var c = compareData;
    if (!c.advHas || !c.compHas) {
      body = C('div', {
        className: 'card',
        style: {
          padding: 18,
          fontSize: 13,
          color: '#92400e',
          background: '#fffbeb',
          border: '1px solid #fde68a'
        }
      }, (!c.advHas ? anchorLabel : '경쟁사') + ' 분석 기록이 없어 비교할 수 없습니다. 해당 업체를 먼저 분석해 저장하세요.');
    } else {
      var rows = buildRows(c);
      var ups = catchUp(rows);
      var strs = strengths(rows);
      var gap = coverageGap(c);
      var rA = radarScores(c.adv, c.comp),
        rB = radarScores(c.comp, c.adv);
      body = C('div', null, /* 대진표 */
      C('div', {
        className: 'card',
        style: {
          padding: '16px 20px',
          marginBottom: 12
        }
      }, C('div', {
        style: {
          display: 'grid',
          gridTemplateColumns: '1fr 44px 1fr',
          gap: 10,
          alignItems: 'center'
        }
      }, C('div', {
        style: {
          textAlign: 'center',
          background: 'linear-gradient(135deg,#eef2ff,#e0e7ff)',
          border: '1px solid #c7d2fe',
          borderRadius: 12,
          padding: '12px 10px'
        }
      }, C('div', {
        style: {
          fontSize: 10.5,
          fontWeight: 800,
          color: '#4338ca'
        }
      }, anchorLabel), C('div', {
        style: {
          fontSize: 15,
          fontWeight: 800,
          color: '#0f172a',
          margin: '3px 0'
        }
      }, c.advName), C('div', {
        style: {
          fontSize: 12,
          color: '#475569'
        }
      }, c.adv.keyword + (c.adv.rank != null ? ' · ' + c.adv.rank + '위' : ''))), C('div', {
        style: {
          width: 44,
          height: 44,
          borderRadius: '50%',
          background: '#0f172a',
          color: '#fff',
          fontWeight: 800,
          fontSize: 13,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '0 auto'
        }
      }, 'VS'), C('div', {
        style: {
          textAlign: 'center',
          background: 'linear-gradient(135deg,#fff7ed,#ffedd5)',
          border: '1px solid #fed7aa',
          borderRadius: 12,
          padding: '12px 10px'
        }
      }, C('div', {
        style: {
          fontSize: 10.5,
          fontWeight: 800,
          color: '#c2410c'
        }
      }, '경쟁사'), C('div', {
        style: {
          fontSize: 15,
          fontWeight: 800,
          color: '#0f172a',
          margin: '3px 0'
        }
      }, c.compName), C('div', {
        style: {
          fontSize: 12,
          color: '#475569'
        }
      }, c.comp.keyword + (c.comp.rank != null ? ' · ' + c.comp.rank + '위' : ''))))), /* 핵심 지표 비교표 */
      C('div', {
        className: 'card',
        style: {
          padding: '16px 20px',
          marginBottom: 12
        }
      }, C('h3', {
        className: 'rt-h3'
      }, C('span', {
        className: 'rt-hic'
      }, '⚔️'), '핵심 지표 비교'), C('table', {
        className: 'rt-table',
        style: {
          width: '100%',
          marginTop: 6
        }
      }, C('thead', null, C('tr', null, C('th', null, '지표'), C('th', {
        style: {
          textAlign: 'center'
        }
      }, anchorLabel), C('th', {
        style: {
          textAlign: 'center'
        }
      }, '경쟁사'), C('th', {
        style: {
          textAlign: 'center'
        }
      }, '우열'))), C('tbody', null, rows.map(function (r, i) {
        var aBg = r.advWin === true ? '#ecfdf5' : r.advWin === false ? '#fef2f2' : undefined;
        var bBg = r.advWin === false ? '#ecfdf5' : r.advWin === true ? '#fef2f2' : undefined;
        return C('tr', {
          key: i
        }, C('td', {
          style: {
            fontWeight: 600
          }
        }, r.label), C('td', {
          style: {
            textAlign: 'center',
            fontWeight: 800,
            background: aBg
          }
        }, r.aStr), C('td', {
          style: {
            textAlign: 'center',
            fontWeight: 800,
            background: bBg
          }
        }, r.bStr), C('td', {
          style: {
            textAlign: 'center'
          }
        }, r.advWin == null ? C('span', {
          style: {
            color: '#cbd5e1'
          }
        }, '—') : C('span', {
          style: {
            fontWeight: 800,
            color: r.advWin ? '#059669' : '#dc2626'
          }
        }, (r.advWin ? '▲ 우세' : '▼ 열세') + (r.gap != null ? ' ' + Math.abs(r.gap) + '%' : ''))));
      })))), /* 종합 레이더 */
      C(window.CompetitorRadar || 'div', {
        advScores: rA,
        compScores: rB
      }), /* 키워드 커버리지 갭 */
      gap.length > 0 && C('div', {
        className: 'card',
        style: {
          padding: '16px 20px',
          marginBottom: 12
        }
      }, C('h3', {
        className: 'rt-h3'
      }, C('span', {
        className: 'rt-hic'
      }, '🔗'), '키워드 커버리지 갭'), C('div', {
        className: 'rt-desc'
      }, '경쟁사가 노출되는데 광고주가 놓친 세부 키워드 — 태그·상품명 반영 후보'), C('div', {
        style: {
          display: 'flex',
          flexWrap: 'wrap',
          gap: 6
        }
      }, gap.map(function (k, i) {
        return C('span', {
          key: i,
          style: {
            fontSize: 12,
            fontWeight: 700,
            background: '#fff7ed',
            color: '#c2410c',
            border: '1px solid #fed7aa',
            borderRadius: 99,
            padding: '4px 11px'
          }
        }, k);
      }))), /* 따라가야 할 것 + 강점 */
      C('div', {
        className: 'card',
        style: {
          padding: '16px 20px',
          marginBottom: 12,
          background: '#0f172a'
        }
      }, C('div', {
        style: {
          fontSize: 14,
          fontWeight: 800,
          color: '#fff',
          marginBottom: 10
        }
      }, '🎯 따라가야 할 것'), ups.length === 0 ? C('div', {
        style: {
          fontSize: 12.5,
          color: '#6ee7b7'
        }
      }, '핵심 지표에서 광고주가 뒤지는 항목이 없습니다. 현 우위를 유지하세요.') : C('div', null, ups.map(function (u, i) {
        return C('div', {
          key: i,
          style: {
            display: 'flex',
            gap: 10,
            padding: '8px 0',
            borderTop: i ? '1px solid #1e293b' : 'none'
          }
        }, C('span', {
          style: {
            width: 22,
            height: 22,
            borderRadius: 7,
            background: '#f97316',
            color: '#fff',
            fontWeight: 800,
            fontSize: 12,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0
          }
        }, i + 1), C('div', {
          style: {
            fontSize: 12.5,
            color: '#e2e8f0'
          }
        }, C('b', {
          style: {
            color: '#fff'
          }
        }, u.label + (u.gapStr ? ' ' + u.gapStr : '')), C('span', {
          style: {
            color: '#fdba74',
            fontWeight: 700
          }
        }, ' → ' + u.act)));
      })), strs.length > 0 && C('div', {
        style: {
          marginTop: 10,
          background: '#052e2b',
          border: '1px solid #134e4a',
          borderRadius: 10,
          padding: '9px 13px',
          fontSize: 12,
          color: '#6ee7b7'
        }
      }, '💪 유지할 강점: ' + strs.join(' · '))), /* AI 대결 코칭 */
      C('div', {
        className: 'card',
        style: {
          padding: '16px 20px',
          marginBottom: 12,
          border: '1px solid #ddd6fe',
          background: '#f5f3ff'
        }
      }, C('div', {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 8
        }
      }, C('span', {
        style: {
          fontSize: 14,
          fontWeight: 800,
          color: '#4c1d95'
        }
      }, '🤖 AI 대결 코칭'), C('span', {
        className: 'badge b-ai'
      }, 'AI')), !coaching && !coachLoading && C('button', {
        onClick: requestCoaching,
        style: {
          fontSize: 12.5,
          fontWeight: 800,
          color: '#fff',
          background: '#7c3aed',
          border: 'none',
          borderRadius: 9,
          padding: '9px 16px',
          cursor: 'pointer'
        }
      }, '“' + c.advName + '가 ' + c.compName + '를 이기려면” 전략 생성'), coachLoading && C('div', {
        style: {
          fontSize: 12.5,
          color: '#7c3aed'
        }
      }, '⏳ AI가 두 업체 데이터를 분석 중… (약 10~20초)'), coaching && coaching.available && C('div', {
        style: {
          fontSize: 13,
          color: '#312e81',
          lineHeight: 1.75,
          whiteSpace: 'pre-wrap'
        }
      }, coaching.text), coaching && !coaching.available && C('div', {
        style: {
          fontSize: 12.5,
          color: '#92400e'
        }
      }, coaching.message || 'AI 코칭을 사용할 수 없습니다.')));
    }
  }
  return C('div', {
    style: {
      marginBottom: 16
    }
  }, slot, body);
};

/* CompetitorRadar — 5축 레이더 (광고주 인디고 / 경쟁사 주황) — 순수 SVG */
window.CompetitorRadar = function CompetitorRadar(props) {
  var C = React.createElement;
  var axes = ['노출', '가격', '신뢰', 'SEO', '콘텐츠'];
  var adv = props.advScores || [50, 50, 50, 50, 50];
  var comp = props.compScores || [50, 50, 50, 50, 50];
  var cx = 130,
    cy = 120,
    R = 82,
    N = 5;
  function pt(i, v) {
    var ang = -Math.PI / 2 + i * 2 * Math.PI / N;
    var r = R * Math.max(0, Math.min(100, v)) / 100;
    return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
  }
  function poly(vals) {
    return vals.map(function (v, i) {
      return pt(i, v).join(',');
    }).join(' ');
  }
  var grid = [25, 50, 75, 100].map(function (f, gi) {
    return C('polygon', {
      key: 'g' + gi,
      points: axes.map(function (_, i) {
        return pt(i, f).join(',');
      }).join(' '),
      fill: 'none',
      stroke: '#e2e8f0'
    });
  });
  var spokes = axes.map(function (ax, i) {
    var p = pt(i, 100);
    var lp = pt(i, 122);
    return C('g', {
      key: 's' + i
    }, C('line', {
      x1: cx,
      y1: cy,
      x2: p[0],
      y2: p[1],
      stroke: '#e2e8f0'
    }), C('text', {
      x: lp[0],
      y: lp[1],
      fontSize: 10,
      fill: '#64748b',
      fontWeight: 700,
      textAnchor: 'middle',
      dominantBaseline: 'middle'
    }, ax));
  });
  return C('div', {
    className: 'card',
    style: {
      padding: '16px 20px',
      marginBottom: 12
    }
  }, C('h3', {
    className: 'rt-h3'
  }, C('span', {
    className: 'rt-hic'
  }, '🕸️'), '종합 레이더'), C('div', {
    style: {
      display: 'flex',
      gap: 16,
      alignItems: 'center',
      flexWrap: 'wrap',
      justifyContent: 'center'
    }
  }, C('svg', {
    width: 260,
    height: 240,
    viewBox: '0 0 260 240'
  }, grid, spokes, C('polygon', {
    points: poly(comp),
    fill: 'rgba(249,115,22,.15)',
    stroke: '#f97316',
    strokeWidth: 2
  }), C('polygon', {
    points: poly(adv),
    fill: 'rgba(79,70,229,.20)',
    stroke: '#3b82f6',
    strokeWidth: 2
  })), C('div', {
    style: {
      fontSize: 12
    }
  }, C('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      marginBottom: 4
    }
  }, C('span', {
    style: {
      width: 12,
      height: 12,
      borderRadius: 3,
      background: '#3b82f6',
      display: 'inline-block'
    }
  }), '광고주'), C('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 6
    }
  }, C('span', {
    style: {
      width: 12,
      height: 12,
      borderRadius: 3,
      background: '#f97316',
      display: 'inline-block'
    }
  }), '경쟁사'))));
};

;/* ===== js/components/SaveToClientSection.jsx ===== */
/* SaveToClientSection — 분석 결과를 업체로 저장하는 섹션
 *
 * 저장 흐름(2026-07 영업팀 전용 재설계):
 *  - 영업사원(viewer) · 진입 컨텍스트 없음 → "영업 대상으로 저장"(role='prospect').
 *    광고주 드롭다운 없음(관리팀 광고주 완전 비노출). 본인만 열람 · 30일 후 자동 삭제.
 *  - 영업 대상/광고주 상세의 "경쟁사 등록" 진입(competitorContext) → 경쟁사 고정 저장.
 *    앵커(연결 대상)가 컨텍스트로 고정되므로 드롭다운 없음.
 *  - 관리팀(manager/admin) · 진입 컨텍스트 없음 → 기존 탭 흐름(새 업체 / 기존 업체 / 경쟁사).
 */
window.SaveToClientSection = function SaveToClientSection({
  keyword,
  productUrl,
  analysisData,
  volumeData,
  relatedData,
  shopProducts,
  advertiserReport,
  detailHtml,
  htmlDetailResult,
  competitorContext,
  onCompetitorSaved,
  isViewer,
  defaultName
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
  var _s9 = useState('');
  var clientSearch = _s9[0];
  var setClientSearch = _s9[1]; // 기존 업체 검색어
  /* 경쟁사 저장(관리팀 경쟁사 탭) — 연결할 광고주 드롭다운 선택 */
  var _sa = useState(null);
  var compAdvId = _sa[0];
  var setCompAdvId = _sa[1];

  /* 저장 유형 판정 */
  var _isViewer = !!isViewer;
  var _compCtx = !!(competitorContext && competitorContext.competitor_of);
  var _anchorName = competitorContext && competitorContext.advName || '';
  /* 영업 대상(prospect) 저장: 영업사원 + 경쟁사 진입 컨텍스트 없음 */
  var _prospectMode = _isViewer && !_compCtx;
  /* 경쟁사 고정 저장: 상세의 '경쟁사 등록' 진입(앵커 고정, 드롭다운 없음) */
  var _fixedCompMode = _compCtx;
  /* 관리팀 전체 탭 흐름(새 업체 / 기존 업체 / 경쟁사 드롭다운) */
  var _fullMode = !_prospectMode && !_fixedCompMode;

  /* 기존 업체(광고주) 목록 로드 — 관리팀 경쟁사 탭 드롭다운/기존 업체 추가용 */
  var loadClients = useCallback(function () {
    api.get('/cd/registered-clients').then(function (res) {
      if (res.success) setExistingClients(res.data || []);
    }).catch(function () {});
  }, []);
  useEffect(function () {
    if (showModal) {
      // 관리팀 전체 흐름 + 영업사원 흐름(경쟁사 서브모드에서 '내 영업 대상' 드롭다운 필요) 모두 목록 로드
      if (_fullMode || _prospectMode) loadClients();
      if (_prospectMode) setSaveMode('prospect');else if (_fixedCompMode) setSaveMode('competitor');
      // 업체명/경쟁사명 자동 채우기 — 비어 있으면 스토어명 등 기본값으로
      if (!clientName && defaultName) setClientName(defaultName);
    }
  }, [showModal, loadClients, _fullMode, _prospectMode, _fixedCompMode, defaultName]);
  if (!keyword || !analysisData) return null;

  /* DOM 캡처 — 공용 빌더(ReportCapture) 사용 (v6.7 통일)
   * 수동 내보내기·자동저장과 동일한 제거 규칙·인디고 표지·PC 축소판 viewport 적용. */
  var captureReportHtml = function () {
    try {
      if (!window.ReportCapture) return '';
      return window.ReportCapture.buildHtml({
        title: keyword + ' 키워드 분석 보고서'
      });
    } catch (e) {
      console.error('DOM capture failed:', e);
      return '';
    }
  };

  /* 순위 저장 후속 호출 (2026-08-05 신설)
     분석 결과를 업체에 저장해도 순위가 어디에도 기록되지 않던 문제 수정 —
     종전엔 /cd/rank-save 를 부르는 곳이 업체관리 화면 1곳뿐이라, 스토어 분석에서
     저장한 건은 아침 배치가 훑기 전까지 순위 이력이 비어 있었다.
     · 상품ID 3형식(nvMid·/products/·/catalog/) 인식 — 서버 규칙과 동일
     · 서버는 admin·manager 전용이라 그 외 권한은 조용히 생략(에러 표시 안 함)
     · 순위를 못 찾았으면 저장하지 않음(허위 미노출 기록 방지 — 8/1~3 오염 선례) */
  var extractPid = function (url) {
    var u = String(url || '');
    var m = u.match(/[?&]nvMid=(\d+)/);
    if (m) return m[1];
    m = u.match(/\/products\/(\d+)/);
    if (m) return m[1];
    m = u.match(/\/catalog\/(\d+)/);
    if (m) return m[1];
    return u;
  };
  var saveRankIfPossible = function (clientId) {
    try {
      if (!clientId || !keyword || !productUrl) return;
      if (isViewer) return; // 서버가 admin·manager 전용 → 영업사원은 호출 자체 생략
      var list = shopProducts || [];
      if (!list || !list.length) return;
      var pid = extractPid(productUrl);
      var hit = null;
      for (var i = 0; i < list.length; i++) {
        var p = list[i];
        if (p.product_id === pid || p.product_url && String(p.product_url).indexOf(pid) !== -1) {
          hit = p;
          break;
        }
      }
      if (!hit || !hit.rank) return; // 못 찾으면 기록하지 않는다
      api.post('/cd/rank-save', {
        client_id: clientId,
        keyword: keyword,
        product_url: productUrl,
        rank_position: hit.rank,
        page_number: Math.ceil(hit.rank / 40)
      }).catch(function () {});
    } catch (e) {}
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

    // 경쟁사 저장 앵커: 진입 컨텍스트(competitorContext) 우선, 아니면 관리팀 경쟁사 탭 드롭다운 선택
    var compOf = competitorContext && competitorContext.competitor_of || (saveMode === 'competitor' ? compAdvId : null);
    var isCompMode = !!compOf;
    var isProspect = _prospectMode && saveMode === 'prospect' && !isCompMode; // 영업 대상 저장(영업사원)

    if (saveMode === 'new' || saveMode === 'prospect' || isCompMode) {
      if (!clientName.trim()) {
        setMessage(isCompMode ? '경쟁사명을 입력해주세요.' : isProspect ? '영업 대상명을 입력해주세요.' : '업체명을 입력해주세요.');
        setSaving(false);
        return;
      }
      if (saveMode === 'competitor' && !_fixedCompMode && !compOf) {
        setMessage(_isViewer ? '연결할 영업 대상을 선택해주세요.' : '연결할 광고주를 선택해주세요.');
        setSaving(false);
        return;
      }
      payload.name = clientName.trim();
      if (isCompMode) {
        // 경쟁사 저장: 앵커(광고주·영업 대상)에 연결된 경쟁사로
        payload.role = 'competitor';
        payload.competitor_of = compOf;
      } else if (isProspect) {
        // 영업 대상 저장(영업사원 개인용)
        payload.role = 'prospect';
      }
      api.post('/cd/quick-register', payload).then(function (res) {
        if (res.success) {
          setSuccess(true);
          setMessage(res.message);
          saveRankIfPossible(res.client_id);
          if (isCompMode && onCompetitorSaved) {
            try {
              onCompetitorSaved();
            } catch (e) {}
          }
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
          saveRankIfPossible(selectedClientId);
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
    setSaveMode(_prospectMode ? 'prospect' : _fixedCompMode ? 'competitor' : 'new');
  };

  /* 트리거 카드 문구/버튼 */
  var _cardTitle, _cardDesc, _cardBtn, _cardHint;
  if (_prospectMode) {
    _cardTitle = '"' + keyword + '" 분석 결과를 내 영업자료로 저장하시겠습니까?';
    _cardDesc = '저장 시 [영업 대상] 또는 [경쟁사]를 고를 수 있습니다. 경쟁사로 고르면 내 영업 대상 목록에서 대상을 선택해 바로 붙일 수 있어요. (본인만 열람 · 30일 후 자동 삭제)';
    _cardBtn = '🎯 영업자료로 저장 (영업 대상 / 경쟁사)';
    _cardHint = '⚔️ 확장으로 경쟁사 상품을 보낸 뒤에도 여기서 [경쟁사]를 골라 대상을 선택하면 됩니다.';
  } else if (_fixedCompMode) {
    _cardTitle = '"' + keyword + '" 분석 결과를 ' + (_anchorName ? '‘' + _anchorName + '’의 ' : '') + '경쟁사로 저장하시겠습니까?';
    _cardDesc = (_anchorName ? '‘' + _anchorName + '’에 ' : '선택한 대상에 ') + '연결된 경쟁사로 저장됩니다.' + (_isViewer ? ' (본인 등록분은 30일 후 자동 삭제)' : '');
    _cardBtn = '⚔️ 경쟁사로 저장';
    _cardHint = '⚔️ 경쟁사로 저장하면 상세에서 대상과 나란히 비교할 수 있습니다.';
  } else {
    _cardTitle = '"' + keyword + '" 분석 결과를 업체에 저장하시겠습니까?';
    _cardDesc = '업체로 저장하면 업체관리 탭에서 일자별 분석 데이터가 누적됩니다.';
    _cardBtn = '업체 등록 / 저장';
    _cardHint = '⚔️ 경쟁사와 비교하려면: 이 업체를 저장한 뒤 [업체관리] → 해당 업체 → "경쟁사 등록"에서 경쟁사 상품을 분석해 추가하세요.';
  }
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
      background: 'linear-gradient(135deg, #3b82f6 0%, #93c5fd 100%)',
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
  }, _cardTitle), React.createElement('div', {
    style: {
      fontSize: 13,
      opacity: 0.85,
      marginBottom: 16
    }
  }, _cardDesc), React.createElement('button', {
    onClick: function () {
      setShowModal(true);
    },
    style: {
      background: '#fff',
      color: '#3b82f6',
      border: 'none',
      padding: '12px 32px',
      borderRadius: 10,
      fontSize: 15,
      fontWeight: 700,
      cursor: 'pointer',
      boxShadow: '0 2px 8px rgba(0,0,0,0.15)'
    }
  }, _cardBtn), React.createElement('div', {
    style: {
      marginTop: 12,
      fontSize: 12,
      opacity: 0.92,
      lineHeight: 1.6
    }
  }, _cardHint))), /* 모달 */
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
  }, _prospectMode ? saveMode === 'competitor' ? '경쟁사 저장' : '영업 대상 저장' : _fixedCompMode ? '경쟁사 저장' : '업체 등록 / 분석 저장'), React.createElement('button', {
    onClick: closeModal,
    style: {
      background: 'none',
      border: 'none',
      fontSize: 20,
      cursor: 'pointer',
      color: '#94a3b8'
    }
  }, '✕')), /* 분석 키워드 표시 */
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
  }, '✅'), React.createElement('div', {
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
      background: '#3b82f6',
      color: '#fff',
      fontSize: 14,
      fontWeight: 600,
      cursor: 'pointer'
    }
  }, '확인'))

  /* 입력 폼 */ : React.createElement('div', null, /* 탭: 관리팀 전체 흐름에서만 (영업사원 흐름은 단일 입력) */
  _fullMode && React.createElement('div', {
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
      background: saveMode === 'new' ? '#3b82f6' : '#f1f5f9',
      color: saveMode === 'new' ? '#fff' : '#64748b',
      border: saveMode === 'new' ? '1px solid #3b82f6' : '1px solid #e2e8f0'
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
      background: saveMode === 'existing' ? '#3b82f6' : '#f1f5f9',
      color: saveMode === 'existing' ? '#fff' : '#64748b',
      border: saveMode === 'existing' ? '1px solid #3b82f6' : '1px solid #e2e8f0'
    }
  }, '기존 업체에 추가 (' + existingClients.length + ')'), React.createElement('button', {
    onClick: function () {
      setSaveMode('competitor');
    },
    style: {
      flex: 1,
      padding: '10px',
      borderRadius: 8,
      fontSize: 13,
      fontWeight: 700,
      cursor: 'pointer',
      background: saveMode === 'competitor' ? '#c2410c' : '#fff7ed',
      color: saveMode === 'competitor' ? '#fff' : '#c2410c',
      border: '1px solid ' + (saveMode === 'competitor' ? '#c2410c' : '#fed7aa')
    }
  }, '⚔️ 경쟁사로 저장')), /* 영업사원(prospect) 흐름: [영업 대상] / [경쟁사] 토글 → 서브모드별 입력 */
  _prospectMode && React.createElement('div', null, /* 유형 토글 */
  React.createElement('div', {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 16
    }
  }, React.createElement('button', {
    onClick: function () {
      setSaveMode('prospect');
    },
    style: {
      flex: 1,
      padding: '10px',
      borderRadius: 8,
      fontSize: 13,
      fontWeight: 700,
      cursor: 'pointer',
      background: saveMode === 'prospect' ? '#3b82f6' : '#eef2ff',
      color: saveMode === 'prospect' ? '#fff' : '#4338ca',
      border: '1px solid ' + (saveMode === 'prospect' ? '#3b82f6' : '#c7d2fe')
    }
  }, '🎯 영업 대상으로'), React.createElement('button', {
    onClick: function () {
      setSaveMode('competitor');
    },
    style: {
      flex: 1,
      padding: '10px',
      borderRadius: 8,
      fontSize: 13,
      fontWeight: 700,
      cursor: 'pointer',
      background: saveMode === 'competitor' ? '#c2410c' : '#fff7ed',
      color: saveMode === 'competitor' ? '#fff' : '#c2410c',
      border: '1px solid ' + (saveMode === 'competitor' ? '#c2410c' : '#fed7aa')
    }
  }, '⚔️ 경쟁사로')), /* 영업 대상 서브모드 — 단일 입력 */
  saveMode !== 'competitor' && React.createElement('div', null, React.createElement('label', {
    style: {
      fontSize: 13,
      color: '#475569',
      fontWeight: 600,
      display: 'block',
      marginBottom: 6
    }
  }, '영업 대상명'), React.createElement('input', {
    className: 'form-input',
    value: clientName,
    onChange: function (e) {
      setClientName(e.target.value);
    },
    placeholder: '영업 대상(업체·상품)명을 입력하세요',
    style: {
      width: '100%',
      marginBottom: 8
    },
    autoFocus: true
  }), React.createElement('div', {
    style: {
      fontSize: 11.5,
      color: '#4338ca',
      background: '#eef2ff',
      border: '1px solid #c7d2fe',
      borderRadius: 8,
      padding: '8px 12px'
    }
  }, '🎯 영업 대상은 [내 영업자료]에 저장되어 본인만 볼 수 있고, 30일 후 자동 삭제됩니다. 저장 후 상위노출 경쟁사를 붙여 비교하세요.')), /* 경쟁사 서브모드 — 내 영업 대상 드롭다운 + 경쟁사명 */
  saveMode === 'competitor' && React.createElement('div', null, React.createElement('label', {
    style: {
      fontSize: 13,
      color: '#475569',
      fontWeight: 600,
      display: 'block',
      marginBottom: 6
    }
  }, '어느 영업 대상의 경쟁사?'), existingClients.length === 0 ? React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#c2410c',
      background: '#fff7ed',
      border: '1px solid #fed7aa',
      borderRadius: 8,
      padding: '10px 12px',
      marginBottom: 12
    }
  }, '아직 등록된 영업 대상이 없습니다. 먼저 [🎯 영업 대상으로]로 이 상품(또는 영업 대상)을 저장한 뒤, 경쟁사를 붙여주세요.') : React.createElement('select', {
    className: 'form-input',
    value: compAdvId || '',
    onChange: function (e) {
      setCompAdvId(e.target.value ? Number(e.target.value) : null);
    },
    style: {
      width: '100%',
      marginBottom: 12
    }
  }, [React.createElement('option', {
    key: '_',
    value: ''
  }, '— 영업 대상 선택 —')].concat(existingClients.map(function (c) {
    return React.createElement('option', {
      key: c.id,
      value: c.id
    }, c.name);
  }))), React.createElement('label', {
    style: {
      fontSize: 13,
      color: '#475569',
      fontWeight: 600,
      display: 'block',
      marginBottom: 6
    }
  }, '경쟁사명'), React.createElement('input', {
    className: 'form-input',
    value: clientName,
    onChange: function (e) {
      setClientName(e.target.value);
    },
    placeholder: '경쟁사명을 입력하세요',
    style: {
      width: '100%',
      marginBottom: 8
    },
    autoFocus: true
  }), React.createElement('div', {
    style: {
      fontSize: 11.5,
      color: '#c2410c',
      background: '#fff7ed',
      border: '1px solid #fed7aa',
      borderRadius: 8,
      padding: '8px 12px'
    }
  }, '⏳ 선택한 영업 대상에 연결된 경쟁사로 저장됩니다. 본인 등록분은 30일 후 자동 삭제됩니다.'))), /* 경쟁사 저장(앵커 고정, 드롭다운 없음) — 상세 '경쟁사 등록' 진입 */
  _fixedCompMode && React.createElement('div', null, _anchorName && React.createElement('div', {
    style: {
      fontSize: 12.5,
      color: '#9a3412',
      background: '#fff7ed',
      border: '1px solid #fed7aa',
      borderRadius: 8,
      padding: '8px 12px',
      marginBottom: 12
    }
  }, '연결 대상: ', React.createElement('b', null, _anchorName)), React.createElement('label', {
    style: {
      fontSize: 13,
      color: '#475569',
      fontWeight: 600,
      display: 'block',
      marginBottom: 6
    }
  }, '경쟁사명'), React.createElement('input', {
    className: 'form-input',
    value: clientName,
    onChange: function (e) {
      setClientName(e.target.value);
    },
    placeholder: '경쟁사명을 입력하세요',
    style: {
      width: '100%',
      marginBottom: 8
    },
    autoFocus: true
  }), _isViewer && React.createElement('div', {
    style: {
      fontSize: 11.5,
      color: '#c2410c',
      background: '#fff7ed',
      border: '1px solid #fed7aa',
      borderRadius: 8,
      padding: '8px 12px'
    }
  }, '⏳ 본인이 등록한 경쟁사는 30일 후 자동 삭제됩니다.')), /* 관리팀 경쟁사 탭: 연결할 광고주 선택 + 경쟁사명 */
  _fullMode && saveMode === 'competitor' && React.createElement('div', {
    style: {
      marginBottom: 16
    }
  }, React.createElement('label', {
    style: {
      fontSize: 13,
      color: '#475569',
      fontWeight: 600,
      display: 'block',
      marginBottom: 6
    }
  }, '연결할 광고주'), React.createElement('select', {
    className: 'form-input',
    value: compAdvId || '',
    onChange: function (e) {
      setCompAdvId(e.target.value ? Number(e.target.value) : null);
    },
    style: {
      width: '100%',
      marginBottom: 12
    }
  }, [React.createElement('option', {
    key: '_',
    value: ''
  }, '— 광고주 선택 —')].concat(existingClients.map(function (c) {
    return React.createElement('option', {
      key: c.id,
      value: c.id
    }, c.name);
  }))), React.createElement('label', {
    style: {
      fontSize: 13,
      color: '#475569',
      fontWeight: 600,
      display: 'block',
      marginBottom: 6
    }
  }, '경쟁사명'), React.createElement('input', {
    className: 'form-input',
    value: clientName,
    onChange: function (e) {
      setClientName(e.target.value);
    },
    placeholder: '경쟁사명을 입력하세요',
    style: {
      width: '100%',
      marginBottom: 8
    },
    autoFocus: true
  })), /* 새 업체 입력(관리팀) */
  _fullMode && saveMode === 'new' && React.createElement('div', null, React.createElement('label', {
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
  }, '같은 이름의 업체가 있으면 해당 업체에 분석이 추가됩니다.')), /* 기존 업체 선택(관리팀) */
  _fullMode && saveMode === 'existing' && React.createElement('div', {
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
  }, '등록된 업체가 없습니다. 새 업체를 등록해주세요.') : function () {
    var q = clientSearch.trim().toLowerCase();
    var filtered = q ? existingClients.filter(function (c) {
      return (c.name || '').toLowerCase().indexOf(q) !== -1 || (c.main_keywords || '').toLowerCase().indexOf(q) !== -1;
    }) : existingClients;
    return React.createElement(React.Fragment, null, /* 업체명 검색 (업체 多 → 빠르게 찾기) */
    React.createElement('input', {
      type: 'text',
      value: clientSearch,
      onChange: function (e) {
        setClientSearch(e.target.value);
      },
      placeholder: '🔍 업체명 검색...',
      style: {
        width: '100%',
        boxSizing: 'border-box',
        padding: '10px 12px',
        borderRadius: 8,
        border: '1px solid #e2e8f0',
        fontSize: 13,
        marginBottom: 8
      }
    }), filtered.length === 0 ? React.createElement('div', {
      style: {
        textAlign: 'center',
        padding: 16,
        color: '#94a3b8',
        fontSize: 13
      }
    }, "'" + clientSearch + "' 검색 결과가 없습니다.") : React.createElement('div', {
      style: {
        maxHeight: 200,
        overflowY: 'auto'
      }
    }, filtered.map(function (c) {
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
          background: isSelected ? '#3b82f6' : '#f8fafc',
          color: isSelected ? '#fff' : '#1e293b',
          border: '1px solid ' + (isSelected ? '#3b82f6' : '#e2e8f0')
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
    })));
  }()), /* 오류 메시지 */
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
      background: saving ? '#94a3b8' : '#3b82f6',
      color: '#fff',
      fontSize: 14,
      fontWeight: 600,
      cursor: saving ? 'default' : 'pointer'
    }
  }, saving ? '저장 중...' : _prospectMode ? saveMode === 'competitor' ? '경쟁사 저장' : '영업 대상 저장' : _fixedCompMode ? '경쟁사 저장' : '분석 결과 저장')))));
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
  var _s3 = useState(function () {
    /* 셸 전역 검색(Ctrl+K) 핸드오프 — 1회 소비 */
    try {
      var g = sessionStorage.getItem('logic_global_q');
      if (g) {
        sessionStorage.removeItem('logic_global_q');
        return g;
      }
    } catch (e) {}
    return '';
  });
  var query = _s3[0];
  var setQuery = _s3[1];
  var _s4 = useState(null);
  var mgrFilter = _s4[0];
  var setMgrFilter = _s4[1]; // 담당자 탭 필터(null=전체)

  // 상위 계정(관리자)만 담당자(등록 직원) 정보를 노출 (매니저는 본인 것만 보므로 불필요)
  var isAdmin = !!(currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin'));
  var _s5 = useState([]);
  var managers = _s5[0];
  var setManagers = _s5[1]; // 배정 가능한 담당자
  var _s6 = useState(null);
  var editMgrId = _s6[0];
  var setEditMgrId = _s6[1]; // 담당자 변경 중인 업체 id

  /* 2차 확산(2026-08-05): 업체별 순위 롤업(rank-overview) — 카드에 대표 키워드
     순위·변동·미니 추이 표시용. 실패해도 카드 기본 표시는 그대로(가산). */
  var _s7 = useState({});
  var rankOv = _s7[0];
  var setRankOv = _s7[1]; // { clientId: overviewItem }
  var _s8 = useState(false);
  var attnOnly = _s8[0];
  var setAttnOnly = _s8[1]; // ⚠️ 주의만 보기

  useEffect(function () {
    api.get('/cd/rank-overview').then(function (res) {
      if (res && res.success && res.data) {
        var m = {};
        res.data.forEach(function (it) {
          m[it.id] = it;
        });
        setRankOv(m);
      }
    }).catch(function () {});
  }, []);

  /* 카드 미니 스파크라인 — 대표 키워드 8일 추이 (낮은 순위 = 위) */
  var miniSpark = function (series) {
    var pts = (series || []).filter(function (p) {
      return p.rank != null;
    });
    if (pts.length < 2) return null;
    var w = 200,
      h = 22,
      pad = 2;
    var rs = pts.map(function (p) {
      return p.rank;
    });
    var mn = Math.min.apply(null, rs),
      mx = Math.max.apply(null, rs);
    var span = mx - mn || 1;
    var coords = pts.map(function (p, i) {
      return (pad + (w - pad * 2) * (i / (pts.length - 1))).toFixed(1) + ',' + (pad + (h - pad * 2) * ((p.rank - mn) / span)).toFixed(1);
    });
    var improving = rs[rs.length - 1] <= rs[0];
    return React.createElement('svg', {
      width: '100%',
      height: h,
      viewBox: '0 0 ' + w + ' ' + h,
      preserveAspectRatio: 'none',
      style: {
        display: 'block',
        margin: '4px 0 2px'
      }
    }, React.createElement('polyline', {
      points: coords.join(' '),
      fill: 'none',
      stroke: improving ? '#16a34a' : '#dc2626',
      strokeWidth: 1.8,
      strokeLinejoin: 'round',
      strokeLinecap: 'round'
    }));
  };
  useEffect(function () {
    if (!isAdmin) return;
    api.get('/clients/assignable-managers').then(function (res) {
      if (res && res.success) setManagers(res.data || []);
    }).catch(function () {});
  }, [isAdmin]);

  // 담당자(created_by) 변경
  var changeManager = function (clientId, managerId) {
    var mid = parseInt(managerId, 10);
    if (!mid) {
      setEditMgrId(null);
      return;
    }
    api.put('/clients/' + clientId + '/manager', {
      manager_id: mid
    }).then(function (res) {
      if (res && res.success) {
        setClients(function (prev) {
          return prev.map(function (c) {
            return c.id === clientId ? Object.assign({}, c, {
              created_by: mid,
              manager_name: res.manager_name
            }) : c;
          });
        });
        try {
          toast.success('담당자를 변경했습니다.');
        } catch (e) {}
      }
      setEditMgrId(null);
    }).catch(function () {
      setEditMgrId(null);
    });
  };

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

  /* 셸 전역 검색 이벤트 — 대시보드에 이미 있을 때도 검색어 반영 */
  useEffect(function () {
    var onSearch = function (ev) {
      if (ev && typeof ev.detail === 'string') {
        setQuery(ev.detail);
        try {
          sessionStorage.removeItem('logic_global_q');
        } catch (e) {}
      }
    };
    window.addEventListener('logic-global-search', onSearch);
    return function () {
      window.removeEventListener('logic-global-search', onSearch);
    };
  }, []);

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

  /* ⚠️ 주의 판정 — 추적 키워드는 있는데 노출 0 (rank-overview 기준) */
  var isAttention = function (c) {
    var ov = rankOv[c.id];
    return !!(ov && ov.keywords > 0 && ov.exposed === 0);
  };

  /* 검색 + 가나다 정렬 */
  var filtered = clients.filter(function (c) {
    // 담당자 탭 필터 (null = 전체)
    if (mgrFilter && (c.manager_name || '(미지정)') !== mgrFilter) return false;
    if (attnOnly && !isAttention(c)) return false;
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
      color: '#3b82f6',
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
  })), /* 2차 확산: KPI 스트립 — 업체·오늘 분석·상승 키워드·주의(클릭 필터) */
  !loading && clients.length > 0 && function () {
    var today = new Date().toISOString().slice(0, 10);
    var analyzedToday = clients.filter(function (c) {
      return c.analyzed_keywords && c.analyzed_keywords[0] && String(c.analyzed_keywords[0].analyzed_date || '').slice(0, 10) === today;
    }).length;
    var upTotal = 0,
      attn = 0,
      hasOv = false;
    clients.forEach(function (c) {
      var ov = rankOv[c.id];
      if (ov) {
        hasOv = true;
        upTotal += ov.up || 0;
        if (isAttention(c)) attn++;
      }
    });
    var kpi = function (k, v, sub, subColor, onClick, active) {
      return React.createElement('div', {
        onClick: onClick || null,
        style: {
          background: active ? '#fffbeb' : '#f8fafc',
          border: '1px solid ' + (active ? '#f59e0b' : '#eef2f6'),
          borderRadius: 12,
          padding: '11px 15px',
          cursor: onClick ? 'pointer' : 'default',
          flex: '1 1 150px',
          minWidth: 140
        }
      }, React.createElement('div', {
        style: {
          fontSize: 11,
          fontWeight: 700,
          color: '#94a3b8',
          letterSpacing: '.03em'
        }
      }, k), React.createElement('div', {
        style: {
          fontSize: 20,
          fontWeight: 800,
          color: '#0f172a',
          marginTop: 1
        }
      }, v), sub && React.createElement('div', {
        style: {
          fontSize: 11,
          color: subColor || '#94a3b8'
        }
      }, sub));
    };
    return React.createElement('div', {
      style: {
        display: 'flex',
        gap: 10,
        flexWrap: 'wrap',
        marginBottom: 16
      }
    }, kpi('내 업체', clients.length, null), kpi('오늘 자동 분석', analyzedToday, '보고서 생성됨'), hasOv && kpi('상승 키워드', '▲ ' + upTotal, '전일 대비', '#16a34a'), hasOv && kpi('주의 필요', attn, attnOnly ? '필터 적용 중 — 클릭 해제' : '노출 0 — 클릭 시 필터', '#b45309', function () {
      setAttnOnly(!attnOnly);
    }, attnOnly));
  }(), /* 담당자별 구분 탭 (상위 계정 전용) — 클릭 시 해당 담당자 업체만 모아보기 */
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
    var ov = rankOv[client.id];
    var attn = isAttention(client);
    var repKw = ov && ov.top_keywords && ov.top_keywords[0];
    var repDelta = null;
    if (ov && ov.rep_series && ov.rep_series.length >= 2) {
      var _rs = ov.rep_series;
      if (_rs[_rs.length - 1].rank != null && _rs[_rs.length - 2].rank != null) {
        repDelta = _rs[_rs.length - 2].rank - _rs[_rs.length - 1].rank; // 양수=상승
      }
    }
    return React.createElement('div', {
      key: client.id,
      style: {
        background: '#fff',
        border: '1px solid ' + (attn ? '#f59e0b' : '#e2e8f0'),
        borderRadius: 12,
        padding: '16px 18px',
        transition: 'all 0.15s ease',
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between'
      },
      onMouseEnter: function (e) {
        e.currentTarget.style.borderColor = '#3b82f6';
        e.currentTarget.style.boxShadow = '0 4px 12px rgba(108,92,231,0.15)';
        e.currentTarget.style.transform = 'translateY(-2px)';
      },
      onMouseLeave: function (e) {
        e.currentTarget.style.borderColor = attn ? '#f59e0b' : '#e2e8f0';
        e.currentTarget.style.boxShadow = '0 1px 2px rgba(0,0,0,0.04)';
        e.currentTarget.style.transform = 'translateY(0)';
      }
    }, /* 업체명 + 대표 키워드 순위(2차 확산) + 마지막 분석 */
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
    }, client.vertical === 'place' && React.createElement('span', {
      title: '플레이스 업체',
      style: {
        marginRight: 4
      }
    }, '📍'), client.name || '(이름 없음)'), /* 대표 키워드 현재 순위 + 변동 + 미니 추이 */
    ov && React.createElement('div', {
      style: {
        marginBottom: 7
      }
    }, repKw ? React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        gap: 6
      }
    }, React.createElement('span', {
      style: {
        fontSize: 12,
        color: '#475569',
        flex: 1,
        minWidth: 0,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, repKw.keyword), React.createElement('span', {
      style: {
        fontSize: 16,
        fontWeight: 800,
        color: repKw.rank <= 10 ? '#16a34a' : '#0f172a'
      }
    }, repKw.rank + '위'), repDelta != null && repDelta !== 0 && React.createElement('span', {
      style: {
        fontSize: 11,
        fontWeight: 800,
        borderRadius: 6,
        padding: '1px 6px',
        color: repDelta > 0 ? '#dc2626' : '#2563eb',
        background: repDelta > 0 ? '#fef2f2' : '#eff6ff'
      }
    }, (repDelta > 0 ? '▲' : '▼') + Math.abs(repDelta))) : ov.keywords > 0 ? React.createElement('div', {
      style: {
        fontSize: 12,
        fontWeight: 700,
        color: '#b45309'
      }
    }, '⚠️ 추적 ' + ov.keywords + '개 전부 미노출') : null, miniSpark(ov.rep_series), ov.keywords > 0 && React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#94a3b8'
      }
    }, '키워드 ' + ov.keywords + ' · 노출 ' + ov.exposed + (ov.top10 ? ' · TOP10 ' + ov.top10 : ''))), React.createElement('div', {
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
        marginBottom: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        flexWrap: 'wrap'
      }
    }, editMgrId === client.id ? React.createElement('select', {
      defaultValue: client.created_by || '',
      onClick: function (e) {
        e.stopPropagation();
      },
      onChange: function (e) {
        e.stopPropagation();
        changeManager(client.id, e.target.value);
      },
      style: {
        fontSize: 11,
        padding: '3px 6px',
        borderRadius: 6,
        border: '1px solid #ddd6fe',
        maxWidth: '100%'
      }
    }, React.createElement('option', {
      value: ''
    }, '담당자 선택...'), managers.map(function (m) {
      return React.createElement('option', {
        key: m.id,
        value: m.id
      }, m.name + (m.role !== 'manager' ? ' (' + m.role + ')' : ''));
    })) : React.createElement(React.Fragment, null, React.createElement('span', null, '👤 담당자: ' + (client.manager_name || '-')), React.createElement('button', {
      onClick: function (e) {
        e.stopPropagation();
        setEditMgrId(client.id);
      },
      style: {
        fontSize: 10,
        fontWeight: 700,
        color: '#6d28d9',
        background: '#ede9fe',
        border: 'none',
        borderRadius: 6,
        padding: '2px 7px',
        cursor: 'pointer'
      }
    }, '변경')))), /* 업체 상세 보기 버튼 */
    React.createElement('button', {
      onClick: function () {
        handleViewClient(client);
      },
      style: {
        display: 'block',
        width: '100%',
        textAlign: 'center',
        background: '#3b82f6',
        color: '#fff',
        border: 'none',
        padding: '8px 0',
        borderRadius: 8,
        fontSize: 12,
        fontWeight: 600,
        cursor: 'pointer'
      }
    }, '업체 상세 보기 →'),
    /* 자동 추적 켜기/끄기 (호출 다이어트) — 계약만료·환불·홀딩 등 관리 중단 업체는
       일일 자동분석·순위추적에서 제외. 기록·조회는 유지. viewer는 조회만 */
    currentUser && currentUser.role !== 'viewer' && React.createElement('button', {
      onClick: function (e) {
        e.stopPropagation();
        var next = client.auto_analysis === 0 ? 1 : 0;
        var label = next === 0 ? '끄기' : '켜기';
        if (!window.confirm('"' + (client.name || '') + '" 자동 추적을 ' + label + ' 할까요?' + (next === 0 ? '\n(계약만료·환불·홀딩 등 관리 중단 업체 권장 — 기록·조회는 그대로 유지됩니다)' : ''))) return;
        api.put('/clients/' + client.id, {
          auto_analysis: next
        }).then(function (res) {
          if (res && (res.success === undefined || res.success)) {
            try {
              toast.success('자동 추적 ' + label + ' 완료: ' + (client.name || ''));
            } catch (e2) {}
            loadClients();
          } else {
            try {
              toast.error('변경 실패: ' + (res && res.detail || '오류'));
            } catch (e2) {}
          }
        }).catch(function (err) {
          try {
            toast.error('변경 실패: ' + (err.message || '네트워크 오류'));
          } catch (e2) {}
        });
      },
      style: {
        display: 'block',
        width: '100%',
        textAlign: 'center',
        marginTop: 6,
        background: client.auto_analysis === 0 ? '#fef3c7' : '#f1f5f9',
        color: client.auto_analysis === 0 ? '#92400e' : '#475569',
        border: '1px solid ' + (client.auto_analysis === 0 ? '#fcd34d' : '#e2e8f0'),
        padding: '6px 0',
        borderRadius: 8,
        fontSize: 11.5,
        fontWeight: 700,
        cursor: 'pointer'
      }
    }, client.auto_analysis === 0 ? '⏸ 자동 추적 꺼짐 — 켜기' : '▶ 자동 추적 중 — 끄기'), /* 중지 상태 배지(viewer 포함 전원에게 보임) */
    client.auto_analysis === 0 && (!currentUser || currentUser.role === 'viewer') && React.createElement('div', {
      style: {
        marginTop: 6,
        textAlign: 'center',
        fontSize: 11,
        fontWeight: 700,
        color: '#92400e'
      }
    }, '⏸ 자동 추적 중지됨'));
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
      background: 'linear-gradient(135deg, #3b82f6 0%, #93c5fd 100%)',
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
      background: '#3b82f6',
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
      borderColor: '#3b82f6'
    },
    inputIcon: {
      marginRight: '12px',
      fontSize: '18px',
      color: '#3b82f6'
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
      background: '#3b82f6',
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
      background: '#2563eb'
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
        color: (analysisCounts[String(user.id)] || 0) > 0 ? '#3b82f6' : '#94a3b8',
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

;/* ===== js/components/AiInsightsView.jsx ===== */
/* AiInsightsView — 광고주(업체) 누적 데이터 기반 AI 자기학습 인사이트 렌더러
 * ClientDashboard의 "AI 인사이트" 탭과 학습센터(LearningCenterPage)에서 공용으로 사용.
 * 렌더링은 ClientDashboard 인라인 블록과 동일(behavior-preserving). 숫자 포맷은 전역 fmt 사용. */
window.AiInsightsView = function AiInsightsView({
  aiLoading,
  aiInsights,
  aiSelectedKeyword,
  setAiSelectedKeyword
}) {
  return /*#__PURE__*/React.createElement("div", null, aiLoading && /*#__PURE__*/React.createElement("div", {
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
  }, "AI 인사이트를 분석 중입니다...")), !aiLoading && !aiInsights && /*#__PURE__*/React.createElement("div", {
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
  }, "아직 분석 데이터가 없어 AI 인사이트를 생성할 수 없습니다."), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      marginTop: 8
    }
  }, "분석을 실행하면 AI가 자동으로 학습하여 인사이트를 제공합니다.")), !aiLoading && aiInsights && /*#__PURE__*/React.createElement("div", null, aiInsights.performance && /*#__PURE__*/React.createElement("div", {
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
  }, '📊', " 업체 성과 패턴", /*#__PURE__*/React.createElement("span", {
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
  }, "상승 키워드"), /*#__PURE__*/React.createElement("div", {
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
  }, "하락 키워드"), /*#__PURE__*/React.createElement("div", {
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
  }, "유지 키워드"), /*#__PURE__*/React.createElement("div", {
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
  }, "총 키워드"), /*#__PURE__*/React.createElement("div", {
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
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "키워드"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center'
    }
  }, "추세"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "초기 순위"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "현재 순위"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "변동"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "평균 순위"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "데이터"))), /*#__PURE__*/React.createElement("tbody", null, aiInsights.performance.keywordSummaries.map(function (s, i) {
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
    }, s.firstRank, "위"), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        fontWeight: 700
      }
    }, s.latestRank, "위"), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        color: s.change > 0 ? '#16a34a' : s.change < 0 ? '#dc2626' : '#64748b',
        fontWeight: 600
      }
    }, s.change > 0 ? '▲' + s.change : s.change < 0 ? '▼' + Math.abs(s.change) : '-'), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right'
      }
    }, s.avgRank, "위"), /*#__PURE__*/React.createElement("td", {
      style: {
        textAlign: 'right',
        color: '#94a3b8'
      }
    }, s.dataPoints, "건"));
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
  }, '🚨', " 경쟁사 이상 감지", aiInsights.competitorAlerts.dangerCount > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      padding: '2px 8px',
      borderRadius: 10,
      background: '#fee2e2',
      color: '#dc2626',
      fontWeight: 600
    }
  }, "위험 ", aiInsights.competitorAlerts.dangerCount, "건"), aiInsights.competitorAlerts.warningCount > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      padding: '2px 8px',
      borderRadius: 10,
      background: '#fef9c3',
      color: '#ca8a04',
      fontWeight: 600
    }
  }, "주의 ", aiInsights.competitorAlerts.warningCount, "건")), /*#__PURE__*/React.createElement("div", {
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
  }, '🔍', " 키워드 발굴 추천", /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      fontWeight: 400
    }
  }, "기존 ", aiInsights.keywordRecommendations.existingCount, "개 키워드에서 ", aiInsights.keywordRecommendations.candidateCount, "개 후보 발굴")), /*#__PURE__*/React.createElement("div", {
    className: "table-wrap",
    style: {
      overflowX: 'auto'
    }
  }, /*#__PURE__*/React.createElement("table", {
    style: {
      fontSize: 13,
      whiteSpace: 'nowrap'
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "추천 키워드"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "월간 검색량"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "연관 등장"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right'
    }
  }, "추천 점수"))), /*#__PURE__*/React.createElement("tbody", null, aiInsights.keywordRecommendations.topRecommended.map(function (kw, i) {
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
    }, kw.appearances, "회"), /*#__PURE__*/React.createElement("td", {
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
  }())));
};

;/* ===== js/components/PlaceClientPanel.jsx ===== */
/* PlaceClientPanel — 로직 분석(업체관리) 탭 안 플레이스 업체 상세 (통합 뷰, 2026-08-05)
 *
 * 운영자 지시: 「로직 분석」 탭에서 스토어·플레이스 구분 없이 업체를 검색해
 * 분석 자료를 한 곳에서 확인. 플레이스 업체(clients.vertical='place')를 선택하면
 * 스토어 분석 스키마(client_analyses) 대신 플레이스 축(place_rank_history)을 읽는다.
 * 기존 플레이스 조회 API(/api/place/keywords·rank-history)와 PlaceRankChart 재사용 —
 * 플레이스 분석·추적 코드는 손대지 않는 읽기 전용 소비.
 *
 * business_key: 업체 저장 시 product_url 이 map.naver.com/p/entry/place/{id} 형식
 * → 'doc:{id}'. id 가 없으면(구 저장분) 안내만 표시.
 *
 * props: { client }  — clients 행 (vertical='place')
 */
window.PlaceClientPanel = function PlaceClientPanel(props) {
  var useState = React.useState,
    useEffect = React.useEffect;
  var client = props.client || {};

  /* 지도 URL → business_key */
  var bk = function () {
    try {
      var m = String(client.naver_store_url || '').match(/entry\/place\/(\d+)/);
      return m ? 'doc:' + m[1] : '';
    } catch (e) {
      return '';
    }
  }();
  var _k = useState(null);
  var kws = _k[0],
    setKws = _k[1]; // [{keyword,rank,state,checked_at}]
  var _sel = useState('');
  var selKw = _sel[0],
    setSelKw = _sel[1];
  var _sr = useState([]);
  var series = _sr[0],
    setSeries = _sr[1];
  var _d = useState(30);
  var days = _d[0],
    setDays = _d[1];
  useEffect(function () {
    setKws(null);
    setSelKw('');
    setSeries([]);
    if (!bk) {
      setKws([]);
      return;
    }
    api.get('/place/keywords?business=' + encodeURIComponent(bk)).then(function (res) {
      var list = res && res.success && res.data && res.data.keywords || [];
      setKws(list);
      if (list.length) setSelKw(list[0].keyword);
    }).catch(function () {
      setKws([]);
    });
  }, [bk, client.id]);
  useEffect(function () {
    if (!bk || !selKw) {
      setSeries([]);
      return;
    }
    api.get('/place/rank-history?business=' + encodeURIComponent(bk) + '&keyword=' + encodeURIComponent(selKw) + '&days=' + days).then(function (res) {
      setSeries(res && res.success && res.data && res.data.series || []);
    }).catch(function () {
      setSeries([]);
    });
  }, [bk, selKw, days]);
  var goPlaceTab = function (hash) {
    try {
      window.location.hash = hash;
    } catch (e) {}
  };
  var chipColor = function (k) {
    if (k.rank != null) return {
      color: '#16a34a',
      background: '#f0fdf4',
      border: '1px solid #bbf7d0'
    };
    if ((k.state || '') === '미확인') return {
      color: '#64748b',
      background: '#f1f5f9',
      border: '1px solid #e2e8f0'
    };
    return {
      color: '#b45309',
      background: '#fffbeb',
      border: '1px solid #fde68a'
    };
  };
  var exposed = (kws || []).filter(function (k) {
    return k.rank != null;
  });
  var best = exposed.length ? exposed.slice().sort(function (a, b) {
    return a.rank - b.rank;
  })[0] : null;
  return React.createElement('div', null, /* KPI */
  kws && kws.length > 0 && React.createElement('div', {
    style: {
      display: 'flex',
      gap: 10,
      flexWrap: 'wrap',
      marginBottom: 16
    }
  }, [['추적 키워드', kws.length, ''], ['노출 중', exposed.length, ''], ['최고 순위', best ? best.rank + '위' : '—', best ? best.keyword : '']].map(function (t, i) {
    return React.createElement('div', {
      key: i,
      style: {
        background: '#f8fafc',
        border: '1px solid #eef2f6',
        borderRadius: 12,
        padding: '11px 16px',
        flex: '1 1 130px'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        fontWeight: 700,
        color: '#94a3b8'
      }
    }, t[0]), React.createElement('div', {
      style: {
        fontSize: 20,
        fontWeight: 800,
        color: '#0f172a'
      }
    }, t[1]), t[2] && React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#94a3b8',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, t[2]));
  })), /* 키워드 칩 */
  React.createElement('div', {
    className: 'card',
    style: {
      padding: 16,
      marginBottom: 16
    }
  }, React.createElement('div', {
    style: {
      fontSize: 15,
      fontWeight: 600,
      marginBottom: 12
    }
  }, '📍 플레이스 분석 키워드' + (kws && kws.length ? ' (' + kws.length + '개)' : '')), kws === null && React.createElement('div', {
    style: {
      color: '#94a3b8',
      fontSize: 13
    }
  }, '불러오는 중...'), kws && kws.length === 0 && React.createElement('div', {
    style: {
      color: '#94a3b8',
      fontSize: 13,
      lineHeight: 1.7
    }
  }, bk ? '아직 이 업체의 플레이스 분석 기록이 없습니다. 「📍 플레이스 분석」 탭에서 분석하면 순위가 하루 1점씩 여기에 쌓입니다.' : '이 업체는 플레이스 식별자(지도 링크) 없이 저장돼 순위 이력을 연결할 수 없습니다. 「📍 플레이스 분석」 탭에서 재분석 후 업체 저장을 다시 하면 자동 연결됩니다.'), kws && kws.length > 0 && React.createElement('div', {
    style: {
      display: 'flex',
      gap: 8,
      flexWrap: 'wrap'
    }
  }, kws.map(function (k, i) {
    var on = selKw === k.keyword;
    var base = {
      padding: '8px 14px',
      borderRadius: 20,
      cursor: 'pointer',
      fontSize: 13,
      fontWeight: 600,
      fontFamily: 'inherit'
    };
    var st = on ? Object.assign(base, {
      background: '#3b82f6',
      color: '#fff',
      border: '1px solid #3b82f6'
    }) : Object.assign(base, chipColor(k));
    return React.createElement('button', {
      key: i,
      onClick: function () {
        setSelKw(k.keyword);
      },
      style: st
    }, k.keyword, React.createElement('span', {
      style: {
        fontSize: 11,
        opacity: .85,
        marginLeft: 6,
        fontWeight: 800
      }
    }, k.rank != null ? k.rank + '위' : k.state || '미노출'));
  }))), /* 순위 추이 차트 (기존 PlaceRankChart 재사용 — 기간 토글·📸 이미지 저장 포함) */
  selKw && React.createElement('div', {
    className: 'card',
    style: {
      padding: 16,
      marginBottom: 16
    }
  }, React.createElement(window.PlaceRankChart, {
    series: series,
    keyword: selKw,
    days: days,
    onDays: function (d) {
      setDays(d);
    },
    businessName: client.name || '플레이스 업체',
    placeUrl: client.naver_store_url || ''
  })), /* 이동 링크 — 분석·추적 실행처 안내 */
  React.createElement('div', {
    style: {
      display: 'flex',
      gap: 10,
      flexWrap: 'wrap',
      background: '#eff6ff',
      border: '1px solid #bfdbfe',
      borderRadius: 12,
      padding: '12px 16px',
      alignItems: 'center'
    }
  }, React.createElement('span', {
    style: {
      fontSize: 13,
      color: '#1d4ed8',
      fontWeight: 700
    }
  }, '📍 플레이스 업체'), React.createElement('span', {
    style: {
      fontSize: 12.5,
      color: '#475569',
      flex: 1,
      minWidth: 200
    }
  }, '새 분석은 「플레이스 분석」 탭에서, 무인 순위 추적 등록은 「플레이스 추적」 탭에서 합니다. 결과는 이 화면에 모입니다.'), React.createElement('button', {
    onClick: function () {
      goPlaceTab('place');
    },
    style: {
      border: '1px solid #3b82f6',
      background: '#fff',
      color: '#1d4ed8',
      borderRadius: 9,
      padding: '7px 13px',
      fontSize: 12.5,
      fontWeight: 800,
      cursor: 'pointer'
    }
  }, '📍 플레이스 분석 →'), React.createElement('button', {
    onClick: function () {
      goPlaceTab('placetrack');
    },
    style: {
      border: '1px solid #3b82f6',
      background: '#fff',
      color: '#1d4ed8',
      borderRadius: 9,
      padding: '7px 13px',
      fontSize: 12.5,
      fontWeight: 800,
      cursor: 'pointer'
    }
  }, '📊 플레이스 추적 →')));
};

;/* ===== js/components/ClientDashboard.jsx ===== */
/* ClientDashboard — 업체별 분석 관리 대시보드 v4.0 (AI 인사이트 탭 추가) */
window.ClientDashboard = function ClientDashboard({
  currentUser,
  onRunAnalysis,
  onRegisterCompetitor,
  onDownloadReport,
  initialSearch,
  canEdit
}) {
  const {
    useState,
    useEffect,
    useCallback
  } = React;

  /* 2026-08-01~03 = 네이버 쇼핑 검색 API 종료 직후 수집 불능 기간(운영자 확정 2026-08-04).
     이 사흘의 순위 없음(NULL)은 '미노출'이 아니라 '수집 중단'으로 표기한다 — 실제 순위 하락으로
     오독되는 것을 막기 위함. 데이터는 삭제하지 않고 표기만 바꾼다. */
  function isOutageRow(r) {
    var d = (r && r.checked_at || '').slice(0, 10);
    return !(r && r.rank_position) && d >= '2026-08-01' && d <= '2026-08-03';
  }
  function rankCellLabel(r) {
    if (r && r.rank_position) return r.rank_position + '위';
    return isOutageRow(r) ? '수집 중단' : '미노출';
  }
  const [clients, setClients] = useState([]);
  const [rankOv, setRankOv] = useState({}); // 2차 확산: 업체별 순위 롤업(상태 점용, 실패 무해)
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
    var _isViewer = currentUser && currentUser.role === 'viewer';
    // 관리팀(canEdit)뿐 아니라 영업사원도 '본인 영업 대상'을 삭제할 수 있다(완전 개인 모드).
    if (canEdit === false && !_isViewer) {
      toast.error('삭제 권한이 없습니다.');
      return;
    }
    var _label = _isViewer ? '영업 대상' : '업체';
    if (!confirm("'" + client.name + "' " + _label + "을(를) 삭제하시겠습니까?\n\n관련된 모든 분석 데이터·순위 이력과 여기에 붙인 경쟁사도 함께 삭제됩니다.\n이 작업은 되돌릴 수 없습니다.")) return;
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
  useEffect(function () {
    api.get('/cd/rank-overview').then(function (res) {
      if (res && res.success && res.data) {
        var m = {};
        res.data.forEach(function (it) {
          m[it.id] = it;
        });
        setRankOv(m);
      }
    }).catch(function () {});
  }, []);
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

  /* 상품ID 추출 — 서버(naver_crawler.extract_product_id_from_url)와 동일한 3형식 인식.
     종전엔 /products/숫자 만 봐서 nvMid=·/catalog/ URL 이면 URL 전체가 pid 로 넘어가
     순위 매칭이 무조건 실패했다(2026-08-05 수정). */
  function extractPid(url) {
    var u = String(url || '');
    var m = u.match(/[?&]nvMid=(\d+)/);
    if (m) return m[1];
    m = u.match(/\/products\/(\d+)/);
    if (m) return m[1];
    m = u.match(/\/catalog\/(\d+)/);
    if (m) return m[1];
    return u;
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
  }, currentUser && currentUser.role === 'viewer' ? '내 영업 대상' : '내 업체 목록', " (", clients.length, ")"), clients.length > 3 && /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "업체명 / 키워드 검색...",
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
  }, "로딩 중..."), !loading && clients.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#94a3b8',
      fontSize: 13,
      padding: '20px 0',
      textAlign: 'center'
    }
  }, currentUser && currentUser.role === 'viewer' ? /*#__PURE__*/React.createElement("span", null, "등록된 영업 대상이 없습니다.", /*#__PURE__*/React.createElement("br", null), "분석 탭에서 영업 대상을 분석해 저장하세요.") : /*#__PURE__*/React.createElement("span", null, "등록된 업체가 없습니다.", /*#__PURE__*/React.createElement("br", null), "분석 탭에서 업체를 등록해주세요.")), !loading && clients.length > 0 && filteredClients.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#94a3b8',
      fontSize: 13,
      padding: '20px 0',
      textAlign: 'center'
    }
  }, "검색 결과가 없습니다."), /*#__PURE__*/React.createElement("div", {
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
        background: isActive ? '#3b82f6' : '#f8fafc',
        color: isActive ? '#fff' : '#1e293b',
        border: '1px solid ' + (isActive ? '#3b82f6' : '#e2e8f0'),
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
        fontSize: 14,
        display: 'flex',
        alignItems: 'center',
        gap: 6
      }
    }, c.vertical === 'place' ? /*#__PURE__*/React.createElement("span", {
      title: "플레이스 업체 — 이 화면에서 순위 확인, 분석은 플레이스 분석 탭"
    }, "📍") : function () {
      var ov = rankOv[c.id];
      if (!ov || !ov.keywords) return null;
      var col = ov.exposed === 0 ? '#f59e0b' : ov.down > ov.up ? '#dc2626' : '#16a34a';
      var tip = ov.exposed === 0 ? '추적 중인데 노출 0 — 점검 필요' : '노출 ' + ov.exposed + '/' + ov.keywords + ' · ▲' + ov.up + ' ▼' + ov.down;
      return /*#__PURE__*/React.createElement("span", {
        title: tip,
        style: {
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: col,
          flexShrink: 0,
          display: 'inline-block'
        }
      });
    }(), /*#__PURE__*/React.createElement("span", {
      style: {
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, c.name || c.business_name)), currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin') && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: '#a78bfa',
        fontWeight: 700,
        marginTop: 2
      }
    }, "👤 담당자: ", c.manager_name || '-'), /*#__PURE__*/React.createElement("div", {
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
    }, c.main_keywords), c.days_left != null && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 10,
        fontWeight: 800,
        marginTop: 4,
        color: isActive ? '#fdba74' : '#c2410c'
      },
      title: "영업 대상은 30일 후 자동 삭제됩니다"
    }, "⏳ ", c.days_left, "일 후 자동 삭제")), canEdit !== false && /*#__PURE__*/React.createElement("button", {
      onClick: function (e) {
        e.stopPropagation();
        /* 자동분석 토글(호출 다이어트) — 계약만료·환불·홀딩 등 관리 중단 업체는
           매일 자동분석·순위추적에서 제외해 API 호출을 아낀다 */
        var next = c.auto_analysis === 0 ? 1 : 0;
        var label = next === 0 ? '중지' : '재개';
        if (!window.confirm('"' + (c.name || c.business_name) + '" 업체의 일일 자동분석·순위추적을 ' + label + '할까요?' + (next === 0 ? '\n(계약만료·환불·홀딩 등 관리 중단 업체 권장 — 기록·조회는 그대로 유지됩니다)' : ''))) return;
        api.put('/clients/' + c.id, {
          auto_analysis: next
        }).then(function (res) {
          if (res && (res.success === undefined || res.success)) {
            c.auto_analysis = next;
            setMessage('자동분석 ' + label + ': ' + (c.name || c.business_name));
            if (typeof loadClients === 'function') loadClients();
          } else {
            setMessage('변경 실패: ' + (res && res.detail || '오류'));
          }
        }).catch(function (err) {
          setMessage('변경 실패: ' + (err.message || '네트워크 오류'));
        });
      },
      title: c.auto_analysis === 0 ? '자동분석 중지됨 — 클릭 시 재개' : '자동분석 중 — 클릭 시 중지(관리 중단 업체용)',
      style: {
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        padding: '2px 4px',
        fontSize: 13,
        flexShrink: 0,
        lineHeight: 1,
        color: c.auto_analysis === 0 ? '#f59e0b' : isActive ? 'rgba(255,255,255,0.5)' : '#cbd5e1'
      }
    }, c.auto_analysis === 0 ? '⏸' : '▶'), (canEdit !== false || currentUser && currentUser.role === 'viewer') && /*#__PURE__*/React.createElement("button", {
      onClick: function (e) {
        deleteClient(c, e);
      },
      title: currentUser && currentUser.role === 'viewer' ? '영업 대상 삭제' : '업체 삭제',
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
  }, "📊"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 16
    }
  }, currentUser && currentUser.role === 'viewer' ? '좌측에서 영업 대상을 선택하세요' : '좌측에서 업체를 선택하세요'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      marginTop: 8
    }
  }, currentUser && currentUser.role === 'viewer' ? '분석 탭에서 영업 대상을 분석·저장하면 여기에 표시됩니다.' : '분석 탭에서 키워드 분석 후 업체를 등록하면 여기에 표시됩니다.')), selectedClient && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
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
  }, selectedClient.vertical === 'place' && /*#__PURE__*/React.createElement("span", {
    title: "플레이스 업체",
    style: {
      marginRight: 6
    }
  }, "📍"), selectedClient.name, selectedClient.vertical === 'place' && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      fontWeight: 800,
      color: '#1d4ed8',
      background: '#eff6ff',
      border: '1px solid #bfdbfe',
      borderRadius: 999,
      padding: '2px 9px',
      marginLeft: 8,
      verticalAlign: 3
    }
  }, "플레이스")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: '#64748b',
      marginTop: 4
    }
  }, selectedClient.main_keywords && /*#__PURE__*/React.createElement("span", null, "키워드: ", selectedClient.main_keywords), selectedClient.naver_store_url && /*#__PURE__*/React.createElement("span", {
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
  }, selectedClient.last_analyzed && '마지막 분석: ' + selectedClient.last_analyzed.slice(0, 10)))), selectedClient.vertical === 'place' && window.PlaceClientPanel && React.createElement(window.PlaceClientPanel, {
    client: selectedClient
  }), selectedClient.vertical !== 'place' && window.CompetitorCompareSection && React.createElement(window.CompetitorCompareSection, {
    client: selectedClient,
    canEdit: canEdit,
    isViewer: currentUser && currentUser.role === 'viewer',
    onRegisterCompetitor: onRegisterCompetitor
  }), selectedClient.vertical !== 'place' && canEdit !== false && /*#__PURE__*/React.createElement(AnalysisForm, {
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
  }), selectedClient.vertical !== 'place' && uniqueKeywords.length > 0 && /*#__PURE__*/React.createElement("div", {
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
  }, "분석 키워드 (", uniqueKeywords.length, "개)"), /*#__PURE__*/React.createElement("div", {
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
        background: isActive ? '#3b82f6' : '#f1f5f9',
        color: isActive ? '#fff' : '#475569',
        border: isActive ? '1px solid #3b82f6' : '1px solid #e2e8f0'
      }
    }, a.keyword, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        opacity: 0.7,
        marginLeft: 6
      }
    }, (a.analyzed_date || '').slice(0, 10)));
  }))), selectedClient.vertical !== 'place' && /*#__PURE__*/React.createElement("div", {
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
      background: viewMode === 'history' ? '#3b82f6' : '#fff',
      color: viewMode === 'history' ? '#fff' : '#475569',
      border: viewMode === 'history' ? 'none' : '1px solid #e2e8f0'
    }
  }, '📊', " 일자별 추이 ", activeKeyword ? '(' + analysisHistory.length + '일)' : ''), /*#__PURE__*/React.createElement("button", {
    onClick: function () {
      setViewMode('rank');
    },
    style: {
      padding: '8px 18px',
      borderRadius: 8,
      fontSize: 13,
      fontWeight: 600,
      cursor: 'pointer',
      background: viewMode === 'rank' ? '#3b82f6' : '#fff',
      color: viewMode === 'rank' ? '#fff' : '#475569',
      border: viewMode === 'rank' ? 'none' : '1px solid #e2e8f0'
    }
  }, '📈', " 순위 이력 ", activeKeyword ? '(' + rankHistory.length + '건)' : ''), /*#__PURE__*/React.createElement("button", {
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
  }, '🤖', " AI 인사이트"), /*#__PURE__*/React.createElement("div", {
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
  }, "\"", activeKeyword, "\" 일자별 분석 추이"), analysisHistory.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      padding: 30,
      color: '#94a3b8',
      fontSize: 13
    }
  }, "아직 누적된 분석 데이터가 없습니다. 매일 분석을 실행하면 여기에 추이가 표시됩니다.") : /*#__PURE__*/React.createElement("div", {
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
  }, "날짜"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "검색량"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "PC 클릭"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "모바일 클릭"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'right',
      whiteSpace: 'nowrap'
    }
  }, "경쟁지수"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center',
      whiteSpace: 'nowrap'
    }
  }, "경쟁수준"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center',
      whiteSpace: 'nowrap'
    }
  }, "광고 경쟁강도"), /*#__PURE__*/React.createElement("th", {
    style: {
      textAlign: 'center',
      whiteSpace: 'nowrap'
    }
  }, "보고서"))), /*#__PURE__*/React.createElement("tbody", null, analysisHistory.slice().reverse().map(function (h, i, arr) {
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
  }, "\"", activeKeyword, "\" 순위 추적 이력"), /*#__PURE__*/React.createElement("div", {
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
  }, '📸', " 이미지 저장 ", '▾'), showExportMenu && /*#__PURE__*/React.createElement("div", {
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
  }, "📊"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 600,
      marginBottom: 6,
      color: '#64748b'
    }
  }, "아직 수집된 순위 데이터가 없습니다"), /*#__PURE__*/React.createElement("div", null, "스케줄러가 6시간 간격으로 자동 수집하며, 매일 오전 7시 전체 분석 시에도 함께 수집됩니다.")) : /*#__PURE__*/React.createElement("div", {
    className: "table-wrap"
  }, /*#__PURE__*/React.createElement("table", null, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "날짜"), /*#__PURE__*/React.createElement("th", null, "순위"), /*#__PURE__*/React.createElement("th", null, "유형"))), /*#__PURE__*/React.createElement("tbody", null, rankHistory.slice().reverse().map(function (r, i, arr) {
    var prevR = arr[i + 1] || null;
    var diff = prevR && r.rank_position && prevR.rank_position ? prevR.rank_position - r.rank_position : null;
    return /*#__PURE__*/React.createElement("tr", {
      key: i
    }, /*#__PURE__*/React.createElement("td", null, (r.checked_at || '').slice(0, 16)), /*#__PURE__*/React.createElement("td", {
      style: {
        fontWeight: 700,
        color: isOutageRow(r) ? '#94a3b8' : undefined,
        fontStyle: isOutageRow(r) ? 'italic' : undefined
      }
    }, rankCellLabel(r), diff != null && diff !== 0 && /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        marginLeft: 6,
        color: diff > 0 ? '#16a34a' : '#dc2626'
      }
    }, diff > 0 ? '▲' + diff : '▼' + Math.abs(diff))), /*#__PURE__*/React.createElement("td", null, r.check_type === 'manual' ? '수동' : '자동'));
  })))))), selectedClient.vertical !== 'place' && !activeKeyword && (viewMode === 'history' || viewMode === 'rank') && /*#__PURE__*/React.createElement("div", {
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
  }, "위에서 키워드를 선택하면 ", viewMode === 'history' ? '일자별 추이' : '순위 이력', "가 표시됩니다.")), selectedClient.vertical !== 'place' && viewMode === 'insights' && /*#__PURE__*/React.createElement(AiInsightsView, {
    aiLoading: aiLoading,
    aiInsights: aiInsights,
    aiSelectedKeyword: aiSelectedKeyword,
    setAiSelectedKeyword: setAiSelectedKeyword
  })))));
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
  }, "새 분석 실행"), /*#__PURE__*/React.createElement("div", {
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
  }, "키워드"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    value: keyword,
    onChange: function (e) {
      setKeyword(e.target.value);
    },
    placeholder: "분석할 키워드",
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
  }, "상품 URL (선택)"), /*#__PURE__*/React.createElement("input", {
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
  }, keyword, " 분석 결과"), onExport && /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: onExport,
    style: {
      fontSize: 13,
      padding: '6px 14px'
    }
  }, "HTML 보고서")), /*#__PURE__*/React.createElement("div", {
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
  }, "월간 검색량"), /*#__PURE__*/React.createElement("div", {
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
  }, "상품 수"), /*#__PURE__*/React.createElement("div", {
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
  }, "경쟁강도"), /*#__PURE__*/React.createElement("div", {
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
  }, "경쟁강도 분석"), /*#__PURE__*/React.createElement("div", {
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
  }, "경쟁지수:"), " ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: data.competitionIndex.compColor
    }
  }, data.competitionIndex.compIndex)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "상품 수:"), " ", /*#__PURE__*/React.createElement("strong", null, fmt(data.competitionIndex.productCount))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "검색량:"), " ", /*#__PURE__*/React.createElement("strong", null, fmt(data.competitionIndex.searchVolume))))), data.marketRevenue && /*#__PURE__*/React.createElement("div", {
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
  }, "시장 규모"), /*#__PURE__*/React.createElement("div", {
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
  }, "평균 가격:"), " ", /*#__PURE__*/React.createElement("strong", null, fmt(data.marketRevenue.avgPrice), "원")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "예상 월 시장:"), " ", /*#__PURE__*/React.createElement("strong", null, fmt(data.marketRevenue.estimatedMonthly), "원")))), data.advertiserInfo && /*#__PURE__*/React.createElement("div", {
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
  }, "광고 경쟁 정보"), /*#__PURE__*/React.createElement("div", {
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
  }, "광고 경쟁강도:"), " ", /*#__PURE__*/React.createElement("strong", null, data.advertiserInfo.compIdx)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    },
    title: "네이버 검색광고(파워링크) 기준 — 이 키워드 검색 시 통합검색 상단에 붙는 광고 평균 개수. 쇼핑검색 순위와는 다른 지표입니다."
  }, "평균 광고 개수 ⓘ:"), " ", /*#__PURE__*/React.createElement("strong", null, data.advertiserInfo.adDepth ? data.advertiserInfo.adDepth + '개' : '데이터 없음')), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "PC 클릭:"), " ", /*#__PURE__*/React.createElement("strong", null, data.advertiserInfo.pcClicks, "회")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#64748b'
    }
  }, "모바일 클릭:"), " ", /*#__PURE__*/React.createElement("strong", null, data.advertiserInfo.mobileClicks, "회")))), !hideHeader && rankHistory && rankHistory.length > 0 && /*#__PURE__*/React.createElement("div", {
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
  }, "순위 추적 이력 (", rankHistory.length, "건)"), /*#__PURE__*/React.createElement("div", {
    className: "table-wrap"
  }, /*#__PURE__*/React.createElement("table", null, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "날짜"), /*#__PURE__*/React.createElement("th", null, "순위"), /*#__PURE__*/React.createElement("th", null, "유형"))), /*#__PURE__*/React.createElement("tbody", null, rankHistory.slice().reverse().map(function (r, i) {
    return /*#__PURE__*/React.createElement("tr", {
      key: i
    }, /*#__PURE__*/React.createElement("td", null, (r.checked_at || '').slice(0, 16)), /*#__PURE__*/React.createElement("td", {
      style: {
        fontWeight: 700,
        color: isOutageRow(r) ? '#94a3b8' : undefined,
        fontStyle: isOutageRow(r) ? 'italic' : undefined
      }
    }, rankCellLabel(r)), /*#__PURE__*/React.createElement("td", null, r.check_type === 'manual' ? '수동' : '자동'));
  }))))));
};

;/* ===== js/components/LearningCenterPage.jsx ===== */
/* LearningCenterPage — 학습센터 (v1.0)
 * 업체관리(광고주)의 데이터를 기반으로, 각 광고주별 AI 자기학습 인사이트
 * (가격최적화·키워드발굴·리뷰감성·광고효율·등록타이밍·성과패턴·경쟁사이상·순위예측)를
 * 한 곳에서 운영/조회한다. 인사이트 렌더링은 공용 컴포넌트 AiInsightsView를 재사용.
 */
window.LearningCenterPage = function LearningCenterPage({
  currentUser
}) {
  const {
    useState,
    useEffect,
    useCallback
  } = React;
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedClient, setSelectedClient] = useState(null);
  const [aiInsights, setAiInsights] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiSelectedKeyword, setAiSelectedKeyword] = useState(null);

  /* 광고주(업체) 목록 로드 — 업체관리와 동일한 소스 */
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

  /* 광고주 선택 → AI 자기학습 인사이트 로드 (업체관리 AI 인사이트 탭과 동일 엔드포인트) */
  var selectClient = function (client) {
    setSelectedClient(client);
    setAiInsights(null);
    setAiSelectedKeyword(null);
    setAiLoading(true);
    api.get('/cd/' + client.id + '/ai-insights').then(function (res) {
      if (res.success) {
        var data = res.data || res;
        setAiInsights(data);
        var kwInsights = data.keywordInsights;
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
  var filteredClients = clients.filter(function (c) {
    if (!searchQuery.trim()) return true;
    var q = searchQuery.trim().toLowerCase();
    return (c.name || '').toLowerCase().indexOf(q) !== -1 || (c.main_keywords || '').toLowerCase().indexOf(q) !== -1 || (c.business_name || '').toLowerCase().indexOf(q) !== -1;
  });

  /* ==================== 광고주 사이드바 아이템 ==================== */
  var renderClientItem = function (c) {
    var isActive = selectedClient && selectedClient.id === c.id;
    return React.createElement('button', {
      key: c.id,
      onClick: function () {
        selectClient(c);
        window.scrollTo({
          top: 0,
          behavior: 'smooth'
        });
      },
      style: {
        display: 'block',
        width: '100%',
        padding: '11px 16px',
        border: 'none',
        cursor: 'pointer',
        textAlign: 'left',
        background: isActive ? '#f0f0ff' : 'transparent',
        borderLeft: isActive ? '3px solid #7C3AED' : '3px solid transparent',
        transition: 'all 0.15s'
      }
    }, React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 6
      }
    }, React.createElement('span', {
      style: {
        fontSize: 13,
        fontWeight: isActive ? 700 : 500,
        color: isActive ? '#6d28d9' : '#334155',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, c.name || c.business_name), currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin') && c.manager_name ? React.createElement('span', {
      style: {
        flexShrink: 0,
        fontSize: 10,
        fontWeight: 600,
        padding: '1px 7px',
        borderRadius: 8,
        background: '#ede9fe',
        color: '#6d28d9'
      }
    }, c.manager_name) : null), c.main_keywords && React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#94a3b8',
        marginTop: 3,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, c.main_keywords));
  };

  /* ==================== 우측 콘텐츠 ==================== */
  var renderRight = function () {
    if (!selectedClient) {
      return React.createElement('div', {
        className: 'card',
        style: {
          padding: 48,
          textAlign: 'center',
          color: '#94a3b8'
        }
      }, React.createElement('div', {
        style: {
          fontSize: 34,
          marginBottom: 12
        }
      }, '🎓'), React.createElement('div', {
        style: {
          fontSize: 15,
          fontWeight: 600,
          color: '#64748b'
        }
      }, '좌측에서 광고주를 선택하세요'), React.createElement('div', {
        style: {
          fontSize: 13,
          marginTop: 8,
          lineHeight: 1.7
        }
      }, '선택한 광고주의 누적 분석 데이터를 바탕으로 AI가 학습한 인사이트(성과 패턴·경쟁사 감지·가격/광고/순위 예측 등)를 보여줍니다.'));
    }
    return React.createElement('div', null, /* 선택된 광고주 헤더 */
    React.createElement('div', {
      className: 'card',
      style: {
        padding: '16px 20px',
        marginBottom: 16,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 8
      }
    }, React.createElement('div', null, React.createElement('div', {
      style: {
        fontSize: 17,
        fontWeight: 700,
        color: '#1e293b'
      }
    }, selectedClient.name), selectedClient.main_keywords && React.createElement('div', {
      style: {
        fontSize: 12,
        color: '#94a3b8',
        marginTop: 3
      }
    }, '주요 키워드: ' + selectedClient.main_keywords)), selectedClient.naver_store_url && React.createElement('a', {
      href: selectedClient.naver_store_url,
      target: '_blank',
      rel: 'noopener noreferrer',
      style: {
        fontSize: 12,
        color: '#7C3AED',
        textDecoration: 'none',
        fontWeight: 600
      }
    }, '스토어 바로가기 →')), /* 공용 AI 인사이트 렌더러 */
    React.createElement(window.AiInsightsView, {
      aiLoading: aiLoading,
      aiInsights: aiInsights,
      aiSelectedKeyword: aiSelectedKeyword,
      setAiSelectedKeyword: setAiSelectedKeyword
    }));
  };
  return React.createElement('div', {
    className: 'container',
    style: {
      paddingTop: 24,
      paddingBottom: 40
    }
  }, /* 헤더 */
  React.createElement('div', {
    style: {
      background: 'linear-gradient(135deg, #7C3AED, #a78bfa)',
      borderRadius: 16,
      padding: '28px 32px',
      marginBottom: 24,
      color: '#fff'
    }
  }, React.createElement('h1', {
    style: {
      fontSize: 24,
      fontWeight: 700,
      marginBottom: 6
    }
  }, '🎓 학습센터'), React.createElement('p', {
    style: {
      fontSize: 14,
      opacity: 0.92,
      lineHeight: 1.6
    }
  }, '광고주(업체)별 누적 분석 데이터를 기반으로 AI가 자기학습한 인사이트를 한 곳에서 운영합니다. 광고주를 선택하면 성과 패턴, 경쟁사 이상 감지, 가격·광고·등록 타이밍, 순위 예측을 확인할 수 있습니다.')), /* 좌우 레이아웃 */
  React.createElement('div', {
    className: 'cd-layout',
    style: {
      display: 'flex',
      gap: 20,
      alignItems: 'flex-start'
    }
  }, /* 좌측: 광고주 목록 */
  React.createElement('div', {
    className: 'cd-sidebar',
    style: {
      width: 260,
      minWidth: 260,
      background: '#fff',
      borderRadius: 14,
      boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
      position: 'sticky',
      top: 80,
      overflow: 'hidden'
    }
  }, React.createElement('div', {
    style: {
      padding: '14px 14px 10px'
    }
  }, React.createElement('div', {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#334155',
      marginBottom: 10
    }
  }, '광고주 목록' + (clients.length ? ' (' + clients.length + ')' : '')), React.createElement('input', {
    className: 'form-input',
    value: searchQuery,
    onChange: function (e) {
      setSearchQuery(e.target.value);
    },
    placeholder: '광고주·키워드 검색',
    style: {
      width: '100%',
      fontSize: 13,
      padding: '7px 10px'
    }
  })), React.createElement('div', {
    style: {
      maxHeight: '70vh',
      overflowY: 'auto',
      borderTop: '1px solid #f1f5f9'
    }
  }, loading ? React.createElement('div', {
    style: {
      padding: 24,
      textAlign: 'center',
      fontSize: 13,
      color: '#94a3b8'
    }
  }, '불러오는 중...') : filteredClients.length === 0 ? React.createElement('div', {
    style: {
      padding: 24,
      textAlign: 'center',
      fontSize: 13,
      color: '#94a3b8'
    }
  }, clients.length === 0 ? '등록된 광고주가 없습니다.' : '검색 결과가 없습니다.') : filteredClients.map(renderClientItem))), /* 우측: 인사이트 */
  React.createElement('div', {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, renderRight())));
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
    background: '#3b82f6',
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
        }, '\u2705 (\uC77C 15\uD68C)'), React.createElement('td', {
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
        }, '\uD83D\uDCA1 Viewer \uACC4\uC815\uC740 \uD558\uB8E8 15\uD68C \uBD84\uC11D \uC81C\uD55C\uC774 \uC788\uC2B5\uB2C8\uB2E4. \uC81C\uD55C \uCD08\uACFC \uC2DC \uB2E4\uC74C \uB0A0 \uC790\uC815\uC5D0 \uCD08\uAE30\uD654\uB429\uB2C8\uB2E4. \uBD84\uC11D \uD69F\uC218\uAC00 \uBD80\uC871\uD558\uBA74 \uAD00\uB9AC\uC790\uC5D0\uAC8C Manager \uC5ED\uD560 \uC2B9\uACA9\uC744 \uC694\uCCAD\uD558\uC138\uC694.')));

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
      background: 'linear-gradient(135deg, #3b82f6, #93c5fd)',
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
        color: isActive ? '#3b82f6' : '#475569',
        borderLeft: isActive ? '3px solid #3b82f6' : '3px solid transparent',
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

;/* ===== js/components/SeoOptimizerPage.jsx ===== */
/* SeoOptimizerPage — 네이버 쇼핑 SEO 최적화 (관리팀 전용 상단 탭)
 * 우리 업무 방식 반영:
 *  - 업체(고객) 연동: 업체 선택 → 키워드/URL 자동입력 → 결과를 업체 기록으로 저장(담당자 이어받기)
 *  - 사내 SEO 규칙: 설정 탭에서 편집한 기준을 AI 생성에 적용 + 화면에 '적용 기준' 표시
 *  - 결과물 산출/공유: 생성 결과를 CSV로 내보내기
 * props: { currentUser }
 */
window.SeoOptimizerPage = function SeoOptimizerPage(props) {
  const {
    useState,
    useEffect
  } = React;
  const [mode, setMode] = useState('generate'); // 'generate' | 'diagnose'

  /* ---------- 업체 연동 ---------- */
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState('');
  const [clientName, setClientName] = useState('');
  const [savedList, setSavedList] = useState([]);

  /* ---------- 사내 규칙(읽기 표시) ---------- */
  const [rules, setRules] = useState('');
  const [showRules, setShowRules] = useState(false);

  /* ---------- 진단 ---------- */
  const [diagKeyword, setDiagKeyword] = useState('');
  const [activeKeyword, setActiveKeyword] = useState('');

  /* ---------- 생성 ---------- */
  const [genKeyword, setGenKeyword] = useState('');
  const [brand, setBrand] = useState('');
  const [category, setCategory] = useState('');
  const [features, setFeatures] = useState('');
  const [genLoading, setGenLoading] = useState(false);
  const [genResult, setGenResult] = useState(null);

  /* 업체 목록 + 사내 규칙 로드 */
  useEffect(function () {
    api.get('/cd/registered-clients').then(function (res) {
      if (res && res.success) setClients(res.data || []);
    }).catch(function () {});
    api.get('/seo/rules').then(function (res) {
      if (res && res.success && res.data) setRules(res.data.rules_text || '');
    }).catch(function () {});
  }, []);

  /* 업체별 저장 이력 로드 */
  const loadSaved = function (cid) {
    if (!cid) {
      setSavedList([]);
      return;
    }
    api.get('/seo/client/' + cid + '/saved').then(function (res) {
      if (res && res.success) setSavedList(res.data || []);
    }).catch(function () {});
  };

  /* 업체 선택 → 키워드/URL 자동입력 + 이력 로드 */
  const handleSelectClient = function (cid) {
    setClientId(cid);
    if (!cid) {
      setClientName('');
      setSavedList([]);
      return;
    }
    var picked = clients.filter(function (c) {
      return String(c.id) === String(cid);
    })[0];
    setClientName(picked ? picked.name : '');
    // 대표 키워드 자동입력 (첫 키워드)
    var kw = picked && picked.main_keywords ? String(picked.main_keywords).split(',')[0].trim() : '';
    if (kw) {
      setGenKeyword(kw);
      setDiagKeyword(kw);
    }
    loadSaved(cid);
  };

  /* ---------- 유틸 ---------- */
  const copy = function (text) {
    try {
      navigator.clipboard.writeText(text);
      if (window.toast && toast.success) toast.success('복사되었습니다');
    } catch (e) {
      if (window.toast && toast.warn) toast.warn('복사에 실패했습니다');
    }
  };
  const handleGenerate = async function () {
    var kw = (genKeyword || '').trim();
    if (!kw) {
      if (window.toast) toast.warn('키워드를 입력하세요');
      return;
    }
    setGenLoading(true);
    setGenResult(null);
    try {
      var body = {
        keyword: kw,
        brand: brand || '',
        category: category || '',
        features: features || ''
      };
      if (clientId) body.client_id = Number(clientId);
      var res = await api.post('/seo/generate', body);
      if (res && res.success) setGenResult(res.data);else if (window.toast) toast.warn(res && res.detail || 'SEO 생성에 실패했습니다.');
    } catch (e) {
      if (window.toast) toast.warn('SEO 생성 요청 실패 — 잠시 후 다시 시도해주세요.');
    }
    setGenLoading(false);
  };

  /* 업체에 저장 (선택한 상품명 기준) */
  const saveToClient = async function (productName) {
    if (!clientId) {
      if (window.toast) toast.warn('먼저 업체를 선택하세요');
      return;
    }
    if (!genResult) return;
    try {
      var res = await api.post('/seo/save-to-client', {
        client_id: Number(clientId),
        keyword: genResult.keyword,
        product_name: productName || genResult.product_names[0] || '',
        tags: genResult.tags || [],
        category: genResult.category || '',
        rationale: genResult.rationale || [],
        source: 'generate'
      });
      if (res && res.success) {
        if (window.toast && toast.success) toast.success('업체 기록에 저장되었습니다');
        loadSaved(clientId);
      } else if (window.toast) {
        toast.warn(res && res.detail || '저장에 실패했습니다.');
      }
    } catch (e) {
      if (window.toast) toast.warn('저장 요청에 실패했습니다.');
    }
  };

  /* 결과물 내보내기 (CSV) */
  const exportCsv = function () {
    if (!genResult) return;
    var rows = [['항목', '내용']];
    if (clientName) rows.push(['업체', clientName]);
    rows.push(['대표 키워드', genResult.keyword]);
    (genResult.product_names || []).forEach(function (nm, i) {
      rows.push(['추천 상품명 ' + (i + 1), nm]);
    });
    rows.push(['추천 태그', (genResult.tags || []).join(', ')]);
    rows.push(['추천 카테고리', genResult.category || '']);
    (genResult.rationale || []).forEach(function (r, i) {
      rows.push(['적용 근거 ' + (i + 1), r]);
    });
    var csv = rows.map(function (r) {
      return r.map(function (cell) {
        var s = String(cell == null ? '' : cell).replace(/"/g, '""');
        return '"' + s + '"';
      }).join(',');
    }).join('\r\n');
    // 엑셀 한글 깨짐 방지 BOM
    var blob = new Blob(['﻿' + csv], {
      type: 'text/csv;charset=utf-8'
    });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    var fn = (clientName ? clientName + '_' : '') + 'SEO_' + (genResult.keyword || '') + '.csv';
    a.download = fn;
    a.click();
    if (window.toast && toast.success) toast.success('CSV로 내보냈습니다');
  };

  /* ---------- 스타일 ---------- */
  var tabBtn = function (active) {
    return {
      padding: '10px 20px',
      borderRadius: 10,
      cursor: 'pointer',
      fontSize: 14,
      fontWeight: 700,
      border: active ? '1px solid #3b82f6' : '1px solid #e2e8f0',
      background: active ? '#3b82f6' : '#fff',
      color: active ? '#fff' : '#475569',
      transition: 'all .15s'
    };
  };
  var chip = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '6px 12px',
    margin: '4px 6px 4px 0',
    background: '#eef2ff',
    color: '#3730a3',
    borderRadius: 999,
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
    border: '1px solid #c7d2fe'
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1080,
      margin: '0 auto',
      padding: '24px 16px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontSize: 22,
      fontWeight: 900,
      margin: '0 0 4px',
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, "🔍 SEO 최적화", /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      fontWeight: 700,
      padding: '2px 9px',
      borderRadius: 999,
      background: '#dbeafe',
      color: '#1d4ed8'
    }
  }, "관리팀 전용")), /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#64748b',
      fontSize: 13
    }
  }, "업체를 선택해 사내 SEO 기준으로 진단·생성하고, 결과를 업체 기록에 저장·공유합니다.")), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '16px 20px',
      marginBottom: 16,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 12,
      alignItems: 'center',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#334155'
    }
  }, "🏢 업체 선택"), /*#__PURE__*/React.createElement("select", {
    className: "form-input",
    value: clientId,
    onChange: function (e) {
      handleSelectClient(e.target.value);
    },
    style: {
      minWidth: 240,
      maxWidth: 360
    }
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "— 업체를 선택하세요 (선택) —"), clients.map(function (c) {
    return /*#__PURE__*/React.createElement("option", {
      key: c.id,
      value: c.id
    }, c.name);
  })), clientName && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: '#0f766e',
      fontWeight: 600
    }
  }, "선택됨: ", clientName, " · 대표키워드 자동입력"), /*#__PURE__*/React.createElement("button", {
    className: "btn",
    style: {
      marginLeft: 'auto',
      padding: '6px 12px',
      fontSize: 12
    },
    onClick: function () {
      setShowRules(!showRules);
    }
  }, "📋 사내 SEO 기준 ", showRules ? '닫기' : '보기')), showRules && /*#__PURE__*/React.createElement("pre", {
    style: {
      marginTop: 12,
      padding: 14,
      background: '#f8fafc',
      border: '1px solid #e2e8f0',
      borderRadius: 10,
      fontSize: 12,
      color: '#334155',
      whiteSpace: 'pre-wrap',
      lineHeight: 1.6,
      maxHeight: 320,
      overflow: 'auto'
    }
  }, rules || '사내 SEO 기준이 아직 설정되지 않았습니다. (설정 탭 → SEO 규칙)')), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10,
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement("button", {
    style: tabBtn(mode === 'generate'),
    onClick: function () {
      setMode('generate');
    }
  }, "✨ SEO 생성"), /*#__PURE__*/React.createElement("button", {
    style: tabBtn(mode === 'diagnose'),
    onClick: function () {
      setMode('diagnose');
    }
  }, "🩺 SEO 진단·점검")), mode === 'generate' && /*#__PURE__*/React.createElement("div", {
    className: "fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '18px 20px',
      marginBottom: 16,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 700,
      fontSize: 14,
      marginBottom: 12
    }
  }, "상품 정보 입력"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 10,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 12,
      color: '#64748b',
      fontWeight: 600
    }
  }, "대표 키워드 ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#ef4444'
    }
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "예: 생멸치 1kg",
    value: genKeyword,
    onChange: function (e) {
      setGenKeyword(e.target.value);
    },
    onKeyDown: function (e) {
      if (e.key === 'Enter') handleGenerate();
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 12,
      color: '#64748b',
      fontWeight: 600
    }
  }, "브랜드 (선택)"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "예: 바다드림",
    value: brand,
    onChange: function (e) {
      setBrand(e.target.value);
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 12,
      color: '#64748b',
      fontWeight: 600
    }
  }, "희망 카테고리 (선택)"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "예: 식품 > 수산물 > 건어물",
    value: category,
    onChange: function (e) {
      setCategory(e.target.value);
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 12,
      color: '#64748b',
      fontWeight: 600
    }
  }, "제품 특징/속성 (선택)"), /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "예: 국내산, 무염, 대용량",
    value: features,
    onChange: function (e) {
      setFeatures(e.target.value);
    }
  }))), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: handleGenerate,
    disabled: genLoading || !genKeyword.trim()
  }, genLoading ? 'AI 생성 중...' : '✨ SEO 생성'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#94a3b8',
      marginTop: 8
    }
  }, "사내 SEO 기준 + 네이버 상위 노출 상품을 반영해 AI가 상품명·태그·카테고리를 제안합니다.")), genLoading && React.createElement(window.LoadingSpinner, {
    text: '네이버 데이터 분석 + AI 생성 중...'
  }), genResult && !genLoading && /*#__PURE__*/React.createElement("div", {
    className: "fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      marginBottom: 12,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn",
    onClick: exportCsv
  }, "📤 결과 내보내기 (CSV)"), clientId ? /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: function () {
      saveToClient(genResult.product_names[0]);
    }
  }, "💾 ", clientName, "에 저장 (1순위)") : /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: '#94a3b8',
      alignSelf: 'center'
    }
  }, "※ 업체를 선택하면 결과를 업체 기록에 저장할 수 있습니다")), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '18px 20px',
      marginBottom: 14,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 800,
      fontSize: 15,
      marginBottom: 12,
      display: 'flex',
      alignItems: 'center',
      gap: 6
    }
  }, "✏️ 추천 상품명 ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      fontWeight: 700,
      padding: '2px 8px',
      borderRadius: 999,
      background: '#fce7f3',
      color: '#9d174d'
    }
  }, "AI")), genResult.product_names.map(function (nm, i) {
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '10px 0',
        borderBottom: i < genResult.product_names.length - 1 ? '1px solid #f1f5f9' : 'none'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 22,
        height: 22,
        flexShrink: 0,
        borderRadius: 6,
        background: '#ec4899',
        color: '#fff',
        fontSize: 11,
        fontWeight: 800,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center'
      }
    }, i + 1), /*#__PURE__*/React.createElement("b", {
      style: {
        flex: 1,
        fontSize: 14,
        lineHeight: 1.5
      }
    }, nm), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: '#94a3b8'
      }
    }, nm.length, "자"), /*#__PURE__*/React.createElement("button", {
      className: "btn",
      style: {
        padding: '4px 10px',
        fontSize: 12
      },
      onClick: function () {
        copy(nm);
      }
    }, "복사"), clientId && /*#__PURE__*/React.createElement("button", {
      className: "btn",
      style: {
        padding: '4px 10px',
        fontSize: 12
      },
      onClick: function () {
        saveToClient(nm);
      }
    }, "이 안 저장"));
  })), genResult.tags && genResult.tags.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '18px 20px',
      marginBottom: 14,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 800,
      fontSize: 15,
      marginBottom: 12,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, "🏷️ 추천 태그 (", genResult.tags.length, ")", /*#__PURE__*/React.createElement("button", {
    className: "btn",
    style: {
      marginLeft: 'auto',
      padding: '4px 10px',
      fontSize: 12
    },
    onClick: function () {
      copy(genResult.tags.join(', '));
    }
  }, "전체 복사")), /*#__PURE__*/React.createElement("div", null, genResult.tags.map(function (tg, i) {
    return /*#__PURE__*/React.createElement("span", {
      key: i,
      style: chip,
      onClick: function () {
        copy(tg);
      }
    }, "#", tg);
  }))), genResult.category && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '18px 20px',
      marginBottom: 14,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 800,
      fontSize: 15,
      marginBottom: 8
    }
  }, "📂 추천 카테고리"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("b", {
    style: {
      fontSize: 14,
      color: '#0f766e'
    }
  }, genResult.category), /*#__PURE__*/React.createElement("button", {
    className: "btn",
    style: {
      padding: '4px 10px',
      fontSize: 12
    },
    onClick: function () {
      copy(genResult.category);
    }
  }, "복사"))), genResult.rationale && genResult.rationale.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '18px 20px',
      marginBottom: 14,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 800,
      fontSize: 15,
      marginBottom: 12
    }
  }, "💡 적용 근거 (사내 기준 반영)"), genResult.rationale.map(function (r, i) {
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        padding: '8px 0',
        borderBottom: i < genResult.rationale.length - 1 ? '1px solid #f1f5f9' : 'none',
        fontSize: 13,
        color: '#334155',
        display: 'flex',
        gap: 10,
        lineHeight: 1.7
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#10b981',
        fontWeight: 800,
        flexShrink: 0
      }
    }, "✔"), r);
  })), /*#__PURE__*/React.createElement("div", {
    className: "note est",
    style: {
      fontSize: 12
    }
  }, "※ AI가 네이버 상위 노출 상품 ", genResult.context && genResult.context.sampled_titles || 0, "건 + 사내 SEO 기준을 반영해 생성한 제안입니다. 등록 전 실제 상품 정보와 맞는지 검토 후 사용하세요.")), clientId && savedList.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '18px 20px',
      marginTop: 8,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 800,
      fontSize: 15,
      marginBottom: 12
    }
  }, "🗂️ ", clientName, " · 저장된 SEO 작업 (", savedList.length, ")"), savedList.map(function (it) {
    return /*#__PURE__*/React.createElement("div", {
      key: it.id,
      style: {
        padding: '10px 0',
        borderBottom: '1px solid #f1f5f9'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        flexWrap: 'wrap'
      }
    }, /*#__PURE__*/React.createElement("b", {
      style: {
        fontSize: 13
      }
    }, it.product_name || '(상품명 없음)'), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: '#94a3b8'
      }
    }, "키워드: ", it.keyword), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: '#cbd5e1',
        marginLeft: 'auto'
      }
    }, (it.created_at || '').slice(0, 10), " · ", it.created_by)), it.tags && it.tags.length > 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: '#3b82f6',
        marginTop: 4
      }
    }, it.tags.map(function (t) {
      return '#' + t;
    }).join(' ')));
  }))), mode === 'diagnose' && /*#__PURE__*/React.createElement("div", {
    className: "fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '18px 20px',
      marginBottom: 8,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 700,
      fontSize: 14,
      marginBottom: 10
    }
  }, "① 기준 키워드 입력"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("input", {
    className: "form-input",
    placeholder: "진단 기준 키워드 (예: 생멸치, 무선이어폰)",
    value: diagKeyword,
    onChange: function (e) {
      setDiagKeyword(e.target.value);
    },
    onKeyDown: function (e) {
      if (e.key === 'Enter') setActiveKeyword(diagKeyword.trim());
    },
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    disabled: !diagKeyword.trim(),
    onClick: function () {
      setActiveKeyword(diagKeyword.trim());
    }
  }, "키워드 적용")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#64748b',
      marginTop: 8
    }
  }, clientName ? /*#__PURE__*/React.createElement("span", null, "업체 ", /*#__PURE__*/React.createElement("b", null, clientName), "의 대표 키워드가 입력되었습니다. ") : null, "키워드를 적용한 뒤, 아래에서 진단할 상품 URL을 입력하면 10개 지표로 SEO 상태를 진단합니다.")), activeKeyword ? React.createElement(window.SeoDiagnosisSection, {
    keyword: activeKeyword
  }) : /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '28px 20px',
      textAlign: 'center',
      color: '#94a3b8',
      borderRadius: 16
    }
  }, "기준 키워드를 먼저 적용해주세요.")));
};

;/* ===== js/components/SeoRulesSection.jsx ===== */
/* SeoRulesSection — 설정 탭: 사내 SEO 규칙 편집 (최고관리자 전용)
 * GET /api/seo/rules, PUT /api/seo/rules
 * 여기서 저장한 기준이 SEO 최적화 탭의 AI 생성에 즉시 반영됨(재배포 불필요).
 */
window.SeoRulesSection = function SeoRulesSection() {
  const {
    useState,
    useEffect
  } = React;
  const [text, setText] = useState('');
  const [orig, setOrig] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  useEffect(function () {
    api.get('/seo/rules').then(function (res) {
      if (res && res.success && res.data) {
        setText(res.data.rules_text || '');
        setOrig(res.data.rules_text || '');
      }
      setLoading(false);
    }).catch(function () {
      setLoading(false);
    });
  }, []);
  const save = async function () {
    if (!text.trim()) {
      if (window.toast) toast.warn('규칙 내용을 입력하세요');
      return;
    }
    setSaving(true);
    try {
      var res = await api.put('/seo/rules', {
        rules_text: text
      });
      if (res && res.success) {
        setOrig(res.data.rules_text || text);
        if (window.toast && toast.success) toast.success('SEO 규칙이 저장되었습니다 — 생성에 즉시 반영됩니다');
      } else if (window.toast) {
        toast.warn(res && res.detail || '저장에 실패했습니다.');
      }
    } catch (e) {
      if (window.toast) toast.warn('저장 요청에 실패했습니다.');
    }
    setSaving(false);
  };
  var dirty = text !== orig;
  return /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '20px 22px',
      marginBottom: 16,
      borderRadius: 16
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "rt-hic"
  }, "📋"), "SEO 사내 규칙"), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "여기서 정한 기준이 ", /*#__PURE__*/React.createElement("b", null, "SEO 최적화 탭의 AI 생성"), "에 즉시 적용됩니다. (상품명 공식·필수요소·금지어·태그/카테고리 기준 등)"), loading ? /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#94a3b8',
      fontSize: 13,
      padding: '12px 0'
    }
  }, "불러오는 중...") : /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("textarea", {
    value: text,
    onChange: function (e) {
      setText(e.target.value);
    },
    spellCheck: false,
    style: {
      width: '100%',
      minHeight: 360,
      padding: 14,
      border: '1px solid #e2e8f0',
      borderRadius: 10,
      fontSize: 13,
      lineHeight: 1.6,
      fontFamily: 'inherit',
      resize: 'vertical',
      whiteSpace: 'pre'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginTop: 10
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: save,
    disabled: saving || !dirty
  }, saving ? '저장 중...' : '저장'), dirty && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: '#f59e0b',
      fontWeight: 600
    }
  }, "● 저장되지 않은 변경사항"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      marginLeft: 'auto'
    }
  }, text.length.toLocaleString(), "자"))));
};

;/* ===== js/components/SectionDivider.jsx ===== */
/* SectionDivider — 섹터 구분 헤더 (v6.1 미리보기 디자인) */
window.SectionDivider = function SectionDivider(props) {
  var label = props && props.label ? props.label : '';
  var icon = props && props.icon ? props.icon : '';
  var color = props && props.color ? props.color : '#3b82f6';
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
  /* 유효성 게이트: 전 연령 0%면 "핵심 타겟 60대 남성(0.0%)" 같은 모순 서술 방지 → 데이터 없음 처리 */
  if (peakAge && !(Number(peakAge.ratio) > 0)) {
    ages = [];
    peakAge = null;
  }
  /* 성별 격차 10%p 미만 = 사실상 무차이 → 특정 성별 타겟 단정 금지 */
  var genderGapSmall = gender ? Math.abs((Number(gender.female) || 0) - (Number(gender.male) || 0)) < 10 : false;
  var ageColors = ['#94a3b8', '#818cf8', '#3b82f6', '#7c3aed', '#a78bfa', '#94a3b8'];
  var ageGrads = ['linear-gradient(90deg, #94a3b8, #cbd5e1)', 'linear-gradient(90deg, #818cf8, #a78bfa)', 'linear-gradient(90deg, #3b82f6, #3b82f6)', 'linear-gradient(90deg, #7c3aed, #8b5cf6)', 'linear-gradient(90deg, #a78bfa, #c4b5fd)', 'linear-gradient(90deg, #94a3b8, #cbd5e1)'];

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
  }, "👥"), "검색 인구통계 — 성별 ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-dl"
  }, "📊 데이터랩")), gender ? /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
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
        backgroundColor: ['#3b82f6', '#ec4899'],
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
  }, genderGapSmall ? '여성 ' + gender.female + '% · 남성 ' + gender.male + '% — 성별 차이가 크지 않아 전 성별 공통 소구가 유리합니다.' : gender.male > gender.female ? '남성 ' + gender.male + '% · 여성 ' + gender.female + '% — 남성 타겟 소구.' : '여성 ' + gender.female + '% · 남성 ' + gender.male + '% — 여성 타겟 소구.')) : /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      padding: 40,
      color: '#94a3b8',
      fontSize: 13
    }
  }, "데이터 없음")), /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "rt-h3"
  }, /*#__PURE__*/React.createElement("span", {
    className: "hic"
  }, "👥"), "검색 인구통계 — 연령 ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-dl"
  }, "📊 데이터랩")), ages.length > 0 ? /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
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
  }, "핵심 타겟: ", /*#__PURE__*/React.createElement("b", null, targetAge, genderGapSmall ? '' : ' ' + targetGender), genderGapSmall || !targetPct ? '' : ' (전체의 약 ' + targetPct + '%)', genderGapSmall ? ' — 성별 무관 공통 소구' : '', ".")) : /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      padding: 40,
      color: '#94a3b8',
      fontSize: 13
    }
  }, "데이터 없음")));
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
  }, "📈"), "키워드 검색량 트렌드 (최근 12개월) ", /*#__PURE__*/React.createElement("span", {
    className: "badge b-dl"
  }, "📊 데이터랩")), /*#__PURE__*/React.createElement("div", {
    className: "grid4",
    style: {
      marginBottom: 6
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "최고 지수"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, d.maxRatio, " ", /*#__PURE__*/React.createElement("small", null, d.maxMonth))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "최저 지수"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, d.minRatio, " ", /*#__PURE__*/React.createElement("small", null, d.minMonth))), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "평균 지수"), /*#__PURE__*/React.createElement("div", {
    className: "v"
  }, d.avgRatio)), /*#__PURE__*/React.createElement("div", {
    className: "kpi"
  }, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "변동폭"), /*#__PURE__*/React.createElement("div", {
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
        borderColor: '#3b82f6',
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
          return m.ratio === d.maxRatio ? '#3b82f6' : m.ratio === d.minRatio ? '#ef4444' : '#fff';
        }),
        pointBorderColor: months.map(function (m) {
          return m.ratio === d.minRatio ? '#ef4444' : '#3b82f6';
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
  }, d.trendNote), /*#__PURE__*/React.createElement("div", {
    className: "note",
    style: {
      marginTop: 6,
      fontSize: 11.5,
      color: '#94a3b8'
    }
  }, "ℹ️ '지수'는 절대 검색량이 아니라 ", /*#__PURE__*/React.createElement("b", null, "기간 내 최고값을 100으로 본 상대값"), "입니다. 증감 추세를 보는 용도이며, 값 자체를 검색 횟수로 해석하지 마세요."))));
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
  }, "🗓️"), "시즌별 수요 예측", /*#__PURE__*/React.createElement("span", {
    className: "badge b-dl"
  }, "📊 데이터랩")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "데이터랩 쇼핑인사이트 기반 시즌 분석"), /*#__PURE__*/React.createElement("div", {
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
    }, "지수 ", Math.round(s.index), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 10,
        fontWeight: 500,
        color: '#94a3b8'
      }
    }, " (상대값)"), isPeak ? ' 🔥' : ''), /*#__PURE__*/React.createElement("div", {
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
  /* 유효성 게이트: 지수가 전부 0이면 "최고: 월요일(지수 0)" 같은 모순 서술이 인쇄되므로 섹션 생략 */
  if (!(Number(d.peakIndex) > 0)) return null;
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
  }, "📅"), "요일별 검색 패턴", /*#__PURE__*/React.createElement("span", {
    className: "badge b-dl"
  }, "📊 데이터랩")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "최근 4주 기준 요일별 검색 트렌드"), /*#__PURE__*/React.createElement(ChartCanvas, {
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
          return day.label === d.peakDay ? '#ec4899' : day.label === d.lowDay ? '#94a3b8' : day.normalized >= 85 ? '#7c3aed' : '#3b82f6';
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
  }, "📈 최고: ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#ec4899'
    }
  }, d.peakDay, "요일"), " (지수 ", Math.round(d.peakIndex), ")"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: '#64748b'
    }
  }, "📉 최저: ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#64748b'
    }
  }, d.lowDay, "요일"), " (지수 ", Math.round(d.lowIndex), ")")))));
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
    main: '#3b82f6',
    grad: 'linear-gradient(90deg, #3b82f6, #818cf8)',
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
  }, "🚀"), "전년 동기 대비 성장률", /*#__PURE__*/React.createElement("span", {
    className: "badge b-dl"
  }, "📊 데이터랩")), /*#__PURE__*/React.createElement("div", {
    className: "rt-desc"
  }, "데이터랩 쇼핑인사이트 기반 전년 대비 검색 트렌드 변화"), props.data.offSeason && /*#__PURE__*/React.createElement("div", {
    style: {
      margin: '8px 0 4px',
      padding: '10px 14px',
      background: '#fffbeb',
      border: '1px solid #fcd34d',
      borderRadius: 10,
      fontSize: 12.5,
      color: '#92400e',
      lineHeight: 1.6
    }
  }, "⚠️ ", /*#__PURE__*/React.createElement("strong", null, "비수기 안내:"), " 현재는 이 키워드의 비수기 구간입니다(현재 지수 ", props.data.currentIndex, " / 연중 최고 ", props.data.peakIndex, "). 낮은 수치·성장률은 계절 저점 때문이며 시장 쇠퇴가 아닙니다 — 성수기 기준으로 해석하세요."), /*#__PURE__*/React.createElement("div", {
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
        border: isRecommended ? '2px solid #3b82f6' : undefined
      }
    }, isRecommended && /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        top: -1,
        right: 16,
        background: '#3b82f6',
        color: '#fff',
        fontSize: 10,
        fontWeight: 700,
        padding: '2px 10px',
        borderRadius: '0 0 6px 6px'
      }
    }, "추천 기준"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        color: '#94a3b8',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        marginBottom: 12
      }
    }, "직전 ", p.label, " 대비"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 32,
        fontWeight: 800,
        color: p.reliable === false ? '#94a3b8' : isPositive ? c.main : '#ef4444',
        marginBottom: 4
      }
    }, p.growth == null || isNaN(p.growth) ? '집계 없음' : (isPositive ? '+' : '') + p.growth + '%', p.reliable === false && p.growth != null && !isNaN(p.growth) && /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 6,
        fontSize: 10,
        fontWeight: 800,
        color: '#92400e',
        background: '#fffbeb',
        border: '1px solid #fcd34d',
        borderRadius: 99,
        padding: '2px 8px',
        verticalAlign: 'middle'
      }
    }, "참고")), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: '#64748b',
        marginBottom: 12
      }
    }, p.reliable === false ? '비수기 · 참고(지수 미미)' : isPositive ? '검색량 증가 추세' : '검색량 감소 추세'), /*#__PURE__*/React.createElement("div", {
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
    }, /*#__PURE__*/React.createElement("span", null, "전년: ", p.previousAvg), /*#__PURE__*/React.createElement("span", null, "올해: ", p.currentAvg)));
  })), props.data.offSeason || avg3m.reliable === false ? /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16,
      padding: '12px 16px',
      background: '#fffbeb',
      borderRadius: 10,
      border: '1px solid #fcd34d',
      fontSize: 12,
      color: '#92400e',
      lineHeight: 1.7
    }
  }, "📈 ", /*#__PURE__*/React.createElement("strong", null, "성장 분석:"), " 현재 비수기 구간이라 전년 대비 성장률은 미세 지수의 변동으로 ", /*#__PURE__*/React.createElement("strong", null, "신뢰도가 낮습니다"), ". 성장세 판단은 성수기 데이터로 하는 것이 정확합니다.") : /*#__PURE__*/React.createElement("div", {
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
  }, "📈 ", /*#__PURE__*/React.createElement("strong", null, "성장 분석:"), " 전년 대비 3개월 평균 기준 ", avg3m.growth > 0 ? '+' : '', avg3m.growth, "%로 ", /*#__PURE__*/React.createElement("strong", null, growthLabel), "입니다.", avg3m.growth > 0 && ' 단기(1개월) 성장률이 장기 평균보다 ' + (periods[0].growth > avg3m.growth ? '높아 현재 상승 모멘텀이 강합니다.' : '낮아 안정적 성장 구간입니다.')))));
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
  }, "🔥"), "카테고리 인기 · 급상승 키워드", /*#__PURE__*/React.createElement("span", {
    className: "badge b-dl"
  }, "📊 데이터랩")), /*#__PURE__*/React.createElement("div", {
    className: "grid2"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "sub-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "st"
  }, "🏆 인기 키워드 TOP"), popular.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#94a3b8',
      padding: '6px 0'
    }
  }, "이 카테고리 기준 집계된 인기 키워드가 없습니다."), popular.length > 0 && /*#__PURE__*/React.createElement("table", {
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
  }, "📈 급상승 키워드"), rising.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#94a3b8',
      padding: '6px 0'
    }
  }, "이 카테고리 기준 급상승 키워드가 집계되지 않았습니다."), rising.length > 0 && /*#__PURE__*/React.createElement("table", {
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
        background: filter === f ? '#3b82f6' : '#f1f5f9',
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
        background: '#3b82f6',
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

;/* ===== js/components/ManagerReassignSection.jsx ===== */
/* ManagerReassignSection — 담당자 재배정 / 퇴사자 업체 일괄 이관 (설정 탭, 관리자 전용) */
window.ManagerReassignSection = function ManagerReassignSection() {
  const {
    useState,
    useEffect,
    useCallback
  } = React;
  const [fromList, setFromList] = useState([]); // 보유 업체 있는 담당자(원본)
  const [toList, setToList] = useState([]); // 배정 가능한 담당자(대상)
  const [fromId, setFromId] = useState('');
  const [toId, setToId] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const load = useCallback(function () {
    api.get('/clients/manager-counts').then(function (res) {
      if (res && res.success) setFromList(res.data || []);
    }).catch(function () {});
    api.get('/clients/assignable-managers').then(function (res) {
      if (res && res.success) setToList(res.data || []);
    }).catch(function () {});
  }, []);
  useEffect(function () {
    load();
  }, [load]);
  var doReassign = function () {
    var f = parseInt(fromId, 10),
      t = parseInt(toId, 10);
    if (!f || !t) {
      setMsg('원본 담당자와 이관 대상을 모두 선택하세요.');
      return;
    }
    if (f === t) {
      setMsg('같은 담당자로는 이관할 수 없습니다.');
      return;
    }
    var fromName = (fromList.find(function (x) {
      return x.id === f;
    }) || {}).name || '';
    var toName = (toList.find(function (x) {
      return x.id === t;
    }) || {}).name || '';
    if (!confirm("'" + fromName + "' 담당 업체를 전부 '" + toName + "'(으)로 이관할까요?")) return;
    setBusy(true);
    setMsg('');
    api.post('/clients/reassign-bulk', {
      from_user_id: f,
      to_user_id: t
    }).then(function (res) {
      setBusy(false);
      if (res && res.success) {
        setMsg('✅ ' + res.moved + '개 업체를 ' + (res.to_name || toName) + '(으)로 이관했습니다.');
        setFromId('');
        setToId('');
        load();
      } else {
        setMsg('이관 실패: ' + (res && res.detail || '오류'));
      }
    }).catch(function (e) {
      setBusy(false);
      setMsg('이관 실패: ' + (e.message || '네트워크 오류'));
    });
  };
  var selStyle = {
    fontSize: 13,
    padding: '8px 10px',
    borderRadius: 8,
    border: '1px solid #e2e8f0',
    minWidth: 220,
    background: '#fff'
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
      fontSize: 16,
      fontWeight: 800,
      color: '#0f172a',
      marginBottom: 4
    }
  }, '👥 담당자 재배정 · 퇴사자 업체 이관'), React.createElement('div', {
    style: {
      fontSize: 12,
      color: '#94a3b8',
      marginBottom: 16
    }
  }, '원본 담당자의 모든 진행중 업체를 다른 담당자에게 한 번에 이관합니다. (퇴사·비활성 계정도 원본으로 선택 가능)'), React.createElement('div', {
    style: {
      display: 'flex',
      gap: 10,
      flexWrap: 'wrap',
      alignItems: 'center'
    }
  }, React.createElement('select', {
    value: fromId,
    onChange: function (e) {
      setFromId(e.target.value);
    },
    style: selStyle
  }, React.createElement('option', {
    value: ''
  }, '원본 담당자 선택...'), fromList.map(function (m) {
    return React.createElement('option', {
      key: m.id,
      value: m.id
    }, m.name + ' (' + m.count + '개)' + (m.is_active ? '' : ' · 퇴사'));
  })), React.createElement('span', {
    style: {
      color: '#94a3b8',
      fontWeight: 700
    }
  }, '→'), React.createElement('select', {
    value: toId,
    onChange: function (e) {
      setToId(e.target.value);
    },
    style: selStyle
  }, React.createElement('option', {
    value: ''
  }, '이관 대상 선택...'), toList.map(function (m) {
    return React.createElement('option', {
      key: m.id,
      value: m.id
    }, m.name + (m.role !== 'manager' ? ' (' + m.role + ')' : ''));
  })), React.createElement('button', {
    onClick: doReassign,
    disabled: busy,
    style: {
      fontSize: 13,
      fontWeight: 700,
      padding: '8px 18px',
      borderRadius: 8,
      cursor: busy ? 'default' : 'pointer',
      border: 'none',
      background: '#3b82f6',
      color: '#fff',
      opacity: busy ? 0.6 : 1
    }
  }, busy ? '이관 중…' : '이관 실행')), msg && React.createElement('div', {
    style: {
      marginTop: 14,
      fontSize: 13,
      fontWeight: 600,
      color: msg.indexOf('✅') === 0 ? '#16a34a' : '#dc2626'
    }
  }, msg));
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
      background: isOpen ? '#64748b' : '#3b82f6',
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
      background: '#3b82f6',
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
      color: activeTab === 'chat' ? '#3b82f6' : '#94a3b8',
      borderBottom: activeTab === 'chat' ? '2px solid #3b82f6' : '2px solid transparent'
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
      color: activeTab === 'feedback' ? '#3b82f6' : '#94a3b8',
      borderBottom: activeTab === 'feedback' ? '2px solid #3b82f6' : '2px solid transparent'
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
        background: isUser ? '#3b82f6' : '#f1f5f9',
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
      background: sending || !input.trim() && !imageB64 ? '#e2e8f0' : '#3b82f6',
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
      background: fbSending || !fbContent.trim() ? '#e2e8f0' : '#3b82f6',
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

;/* ===== js/components/AppShellBar.jsx ===== */
/* AppShellBar — B+A 대개편 셸 (2026-08-05, 대표 확정)
 *
 * 상단 TopBar 를 대체하는 「좌측 사이드바 + 상단 바」. TopBar 와 동일한 props
 * 계약({ activePage, currentUser, health, onNavigate })이라 페이지 블록들은
 * 마운트 치환만으로 이전된다(라우팅·권한 게이트 불변).
 *  - 사이드바: 쇼핑/플레이스/통합 그룹 · 상승 키워드 뱃지(rank-overview totals)
 *    · 접기(수동 토글 localStorage + 좁은 화면 자동) — position:fixed,
 *    본문은 body padding 으로 밀어낸다(페이지 내부 레이아웃 무수정).
 *  - 상단 바: 크럼 · 전역 검색(Ctrl+K, Enter → 대시보드 검색 핸드오프) · 사용자.
 *  - 첫 진입 1회 안내(「메뉴가 왼쪽으로 이동했어요」, localStorage).
 */

var _AS_W = 206,
  _AS_WC = 60,
  _AS_TOP = 50,
  _AS_BANNER = 38;
var _AS_GROUPS = function (cu) {
  var role = cu && cu.role || '';
  return [{
    label: null,
    items: [{
      page: 'home',
      icon: '🏠',
      name: '대시보드'
    }]
  }, {
    label: '쇼핑',
    items: [(role === 'manager' || role === 'superadmin') && {
      page: 'seo',
      icon: '🔍',
      name: 'SEO 최적화'
    }, {
      page: 'analysis',
      icon: '🛒',
      name: '스토어 분석'
    }, {
      page: 'rank',
      icon: '📊',
      name: '키워드 순위',
      badge: 'up'
    }].filter(Boolean)
  }, {
    label: '플레이스',
    items: [{
      page: 'place',
      icon: '📍',
      name: '플레이스 분석'
    }, {
      page: 'placetrack',
      icon: '📊',
      name: '플레이스 추적'
    }]
  }, {
    label: '통합',
    items: [{
      page: 'management',
      icon: '📈',
      name: '로직 분석 (업체)'
    }, {
      page: 'learning',
      icon: '🎓',
      name: '학습센터'
    }, {
      page: 'guide',
      icon: '📖',
      name: '설명서'
    }]
  }, role === 'superadmin' ? {
    label: '관리',
    items: [{
      page: 'settings',
      icon: '⚙️',
      name: '설정'
    }]
  } : null].filter(Boolean);
};
var _AS_CRUMB = {
  home: '홈 / 대시보드',
  seo: '쇼핑 / SEO 최적화',
  analysis: '쇼핑 / 스토어 분석',
  rank: '쇼핑 / 키워드 순위',
  place: '플레이스 / 플레이스 분석',
  placetrack: '플레이스 / 플레이스 추적',
  management: '통합 / 로직 분석 (업체)',
  learning: '통합 / 학습센터',
  guide: '통합 / 설명서',
  settings: '관리 / 설정',
  users: '관리 / 직원'
};
window.AppShellBar = function AppShellBar(props) {
  var useState = React.useState,
    useEffect = React.useEffect,
    useRef = React.useRef;
  var activePage = props.activePage;
  var currentUser = props.currentUser || {};
  var health = props.health;
  var go = props.onNavigate || function () {};
  var _c = useState(function () {
    try {
      var saved = localStorage.getItem('logic_nav_collapsed');
      if (saved != null) return saved === '1';
    } catch (e) {}
    return typeof window !== 'undefined' && window.innerWidth < 1080;
  });
  var collapsed = _c[0],
    setCollapsed = _c[1];
  var _up = useState(null);
  var upTotal = _up[0],
    setUpTotal = _up[1];
  var _q = useState('');
  var q = _q[0],
    setQ = _q[1];
  var _ch = useState(null);
  var colHealth = _ch[0],
    setColHealth = _ch[1]; // 수집 파이프라인 상태
  var _chX = useState(false);
  var colDismissed = _chX[0],
    setColDismissed = _chX[1];
  var _in = useState(function () {
    try {
      return !localStorage.getItem('logic_nav_intro_v7');
    } catch (e) {
      return false;
    }
  });
  var showIntro = _in[0],
    setShowIntro = _in[1];
  var searchRef = useRef(null);

  /* 본문 밀어내기 — 페이지 내부 컨테이너 무수정으로 셸 폭 반영.
     경보 배너가 뜨면 그 높이만큼 더 내려 본문 첫 줄이 가려지지 않게 한다. */
  var _bannerOn = !!(colHealth && !colDismissed);
  useEffect(function () {
    var w = collapsed ? _AS_WC : _AS_W;
    document.body.style.paddingLeft = w + 'px';
    document.body.style.paddingTop = _AS_TOP + (_bannerOn ? _AS_BANNER : 0) + 'px';
    return function () {
      document.body.style.paddingLeft = '';
      document.body.style.paddingTop = '';
    };
  }, [collapsed, _bannerOn]);

  /* 좁은 화면 자동 접힘(수동 설정 없을 때만) */
  useEffect(function () {
    var onR = function () {
      try {
        if (localStorage.getItem('logic_nav_collapsed') != null) return;
      } catch (e) {}
      setCollapsed(window.innerWidth < 1080);
    };
    window.addEventListener('resize', onR);
    return function () {
      window.removeEventListener('resize', onR);
    };
  }, []);

  /* 상승 키워드 뱃지 — 실패 무해 */
  useEffect(function () {
    api.get('/cd/rank-overview').then(function (res) {
      if (res && res.success && res.totals) setUpTotal(res.totals.up_total || 0);
    }).catch(function () {});
  }, []);

  /* 수집 파이프라인 경보 — 오늘 수집이 없으면 전 화면 상단 배너.
     하루 단위로 닫기 기억(다음 날 다시 노출), 조회 실패는 무음(기존 동작 유지) */
  useEffect(function () {
    var today = new Date().toISOString().slice(0, 10);
    try {
      if (localStorage.getItem('logic_collect_alert_off') === today) setColDismissed(true);
    } catch (e) {}
    var load = function () {
      api.get('/collector/health').then(function (res) {
        if (res && res.success && res.state && res.state !== 'ok') setColHealth(res);else setColHealth(null);
      }).catch(function () {});
    };
    load();
    var t = setInterval(load, 10 * 60 * 1000); // 10분 주기 — 낮 만회 수집 시 자동 해제
    return function () {
      clearInterval(t);
    };
  }, []);

  /* Ctrl+K → 검색 포커스 */
  useEffect(function () {
    var onKey = function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        if (searchRef.current) searchRef.current.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return function () {
      window.removeEventListener('keydown', onKey);
    };
  }, []);
  var toggle = function () {
    var next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem('logic_nav_collapsed', next ? '1' : '0');
    } catch (e) {}
  };
  var submitSearch = function () {
    var v = q.trim();
    if (!v) return;
    try {
      sessionStorage.setItem('logic_global_q', v);
    } catch (e) {}
    /* 이미 대시보드에 있어도 반영되게 이벤트 병행(리스트가 리스닝) */
    try {
      window.dispatchEvent(new CustomEvent('logic-global-search', {
        detail: v
      }));
    } catch (e) {}
    setQ('');
    go('home');
  };
  var dismissCollect = function () {
    setColDismissed(true);
    try {
      localStorage.setItem('logic_collect_alert_off', new Date().toISOString().slice(0, 10));
    } catch (e) {}
  };
  var dismissIntro = function () {
    setShowIntro(false);
    try {
      localStorage.setItem('logic_nav_intro_v7', '1');
    } catch (e) {}
  };
  var W = collapsed ? _AS_WC : _AS_W;
  var _r = currentUser.role;
  var roleLabel = _r === 'superadmin' ? '최고관리자' : _r === 'admin' ? '관리자' : _r === 'manager' ? '매니저' : '뷰어';
  var roleBg = _r === 'admin' || _r === 'superadmin' ? '#ede9fe' : _r === 'manager' ? '#dbeafe' : '#f1f5f9';
  var roleFg = _r === 'admin' || _r === 'superadmin' ? '#6d28d9' : _r === 'manager' ? '#1d4ed8' : '#475569';
  var navBtn = function (item) {
    var on = activePage === item.page;
    return React.createElement('button', {
      key: item.page,
      onClick: function () {
        go(item.page);
      },
      title: collapsed ? item.name : undefined,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        width: '100%',
        border: 'none',
        background: on ? '#1d2a44' : 'none',
        color: on ? '#fff' : '#aeb8c8',
        fontFamily: 'inherit',
        fontSize: 13,
        fontWeight: on ? 800 : 600,
        textAlign: 'left',
        borderRadius: 9,
        padding: collapsed ? '9px 0' : '8px 11px',
        cursor: 'pointer',
        justifyContent: collapsed ? 'center' : 'flex-start',
        whiteSpace: 'nowrap'
      },
      onMouseEnter: function (e) {
        if (!on) {
          e.currentTarget.style.background = '#18202f';
          e.currentTarget.style.color = '#e2e8f0';
        }
      },
      onMouseLeave: function (e) {
        if (!on) {
          e.currentTarget.style.background = 'none';
          e.currentTarget.style.color = '#aeb8c8';
        }
      }
    }, React.createElement('span', {
      style: {
        fontSize: 14,
        flex: 'none'
      }
    }, item.icon), !collapsed && React.createElement('span', {
      style: {
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, item.name), !collapsed && item.badge === 'up' && upTotal > 0 && React.createElement('span', {
      style: {
        marginLeft: 'auto',
        fontSize: 10,
        fontWeight: 800,
        background: '#324467',
        color: '#cfe0ff',
        borderRadius: 999,
        padding: '1px 7px'
      }
    }, '▲' + upTotal));
  };
  return React.createElement(React.Fragment, null, /* ── 좌측 사이드바 ── */
  React.createElement('nav', {
    'aria-label': '주요 메뉴',
    style: {
      position: 'fixed',
      top: 0,
      left: 0,
      bottom: 0,
      width: W,
      zIndex: 1000,
      background: '#101623',
      display: 'flex',
      flexDirection: 'column',
      padding: collapsed ? '14px 8px 12px' : '16px 12px 14px',
      gap: 2,
      overflowY: 'auto',
      overflowX: 'hidden',
      transition: 'width .15s ease'
    }
  }, React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      padding: collapsed ? '2px 0 12px' : '4px 10px 14px',
      justifyContent: collapsed ? 'center' : 'flex-start'
    }
  }, collapsed ? React.createElement('span', {
    style: {
      fontWeight: 900,
      color: '#6ea8ff',
      fontSize: 14
    }
  }, 'M') : React.createElement('span', {
    style: {
      fontWeight: 900,
      color: '#fff',
      fontSize: 14.5,
      whiteSpace: 'nowrap'
    }
  }, 'META ', React.createElement('em', {
    style: {
      color: '#6ea8ff',
      fontStyle: 'normal'
    }
  }, '로직분석'))), _AS_GROUPS(currentUser).map(function (g, gi) {
    return React.createElement(React.Fragment, {
      key: gi
    }, g.label && !collapsed && React.createElement('div', {
      style: {
        fontSize: 10,
        fontWeight: 800,
        letterSpacing: '.12em',
        color: '#5b6880',
        padding: '13px 11px 5px'
      }
    }, g.label), g.label && collapsed && React.createElement('div', {
      style: {
        height: 1,
        background: '#1c2534',
        margin: '9px 4px'
      }
    }), g.items.map(navBtn));
  }), React.createElement('div', {
    style: {
      marginTop: 'auto',
      paddingTop: 10,
      borderTop: '1px solid #1c2534'
    }
  }, React.createElement('button', {
    onClick: toggle,
    title: collapsed ? '메뉴 펼치기' : '메뉴 접기',
    style: {
      width: '100%',
      border: 'none',
      background: 'none',
      color: '#5b6880',
      fontSize: 12,
      fontWeight: 700,
      cursor: 'pointer',
      padding: '6px 0',
      fontFamily: 'inherit',
      textAlign: 'center'
    }
  }, collapsed ? '»' : '« 접기'), !collapsed && React.createElement('div', {
    style: {
      fontSize: 11,
      color: '#5b6880',
      padding: '4px 11px 0',
      whiteSpace: 'nowrap'
    }
  }, typeof APP_VERSION !== 'undefined' ? APP_VERSION : '', health && React.createElement('span', {
    style: {
      color: '#4ade80',
      marginLeft: 6,
      fontWeight: 700
    }
  }, '● 정상')))), /* ── 상단 바 ── */
  React.createElement('div', {
    style: {
      position: 'fixed',
      top: 0,
      left: W,
      right: 0,
      height: _AS_TOP,
      zIndex: 999,
      background: '#fff',
      borderBottom: '1px solid #e9ecf0',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '0 18px',
      transition: 'left .15s ease'
    }
  }, React.createElement('span', {
    style: {
      fontSize: 13,
      fontWeight: 700,
      color: '#4e5968',
      whiteSpace: 'nowrap'
    }
  }, _AS_CRUMB[activePage] || ''), showIntro && React.createElement('span', {
    style: {
      fontSize: 11.5,
      fontWeight: 700,
      color: '#1d4ed8',
      background: '#eff4ff',
      border: '1px solid #bfdbfe',
      borderRadius: 999,
      padding: '3px 10px',
      whiteSpace: 'nowrap',
      cursor: 'pointer'
    },
    onClick: dismissIntro,
    title: '닫기'
  }, '💡 메뉴가 왼쪽으로 이동했어요 ✕'), React.createElement('input', {
    ref: searchRef,
    value: q,
    onChange: function (e) {
      setQ(e.target.value);
    },
    onKeyDown: function (e) {
      if (e.key === 'Enter' && !e.nativeEvent.isComposing) submitSearch();
    },
    placeholder: '🔍 업체·키워드 검색 (Ctrl+K)',
    style: {
      marginLeft: 'auto',
      border: '1px solid #e5e8ec',
      borderRadius: 9,
      padding: '6px 12px',
      fontSize: 12.5,
      background: '#f7f8fa',
      minWidth: 150,
      maxWidth: 260,
      flex: '0 1 260px',
      outline: 'none'
    }
  }), React.createElement('span', {
    style: {
      fontSize: 12.5,
      fontWeight: 700,
      color: '#4e5968',
      whiteSpace: 'nowrap'
    }
  }, currentUser.name || currentUser.username), React.createElement('span', {
    style: {
      fontSize: 10.5,
      fontWeight: 800,
      color: roleFg,
      background: roleBg,
      borderRadius: 999,
      padding: '2px 8px',
      whiteSpace: 'nowrap'
    }
  }, roleLabel)), /* ── 수집 중단 경보 배너 (전 화면 공통) ── */
  colHealth && !colDismissed && React.createElement('div', {
    style: {
      position: 'fixed',
      top: _AS_TOP,
      left: W,
      right: 0,
      zIndex: 998,
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '0 18px',
      height: _AS_BANNER,
      fontSize: 12.5,
      fontWeight: 600,
      transition: 'left .15s ease',
      background: colHealth.state === 'down' ? '#fef2f2' : '#fffbeb',
      borderBottom: '1px solid ' + (colHealth.state === 'down' ? '#fecaca' : '#fde68a'),
      color: colHealth.state === 'down' ? '#991b1b' : '#92400e'
    }
  }, React.createElement('span', {
    style: {
      fontSize: 14
    }
  }, colHealth.state === 'down' ? '🚨' : '⚠️'), React.createElement('span', {
    style: {
      fontWeight: 800
    }
  }, colHealth.state === 'down' ? '순위 수집 중단' : '오늘 새벽 수집 미실행'), React.createElement('span', {
    style: {
      flex: 1,
      minWidth: 0,
      fontWeight: 500
    }
  }, colHealth.message || ''), React.createElement('button', {
    onClick: dismissCollect,
    title: '오늘 하루 숨기기',
    style: {
      border: 'none',
      background: 'none',
      cursor: 'pointer',
      fontSize: 13,
      fontWeight: 800,
      color: 'inherit',
      opacity: .65,
      padding: '0 2px',
      fontFamily: 'inherit'
    }
  }, '✕')));
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
  }, '🏠 대시보드'),
  // 🔍 SEO 최적화 — 광고 관리팀(manager) + 최고관리자(superadmin) 전용 (타 세션 의도 위치: 대시보드 다음)
  (currentUser.role === 'manager' || currentUser.role === 'superadmin') && React.createElement('button', {
    onClick: function () {
      go('seo');
    },
    style: _navBtn(activePage === 'seo')
  }, '🔍 SEO 최적화'), React.createElement('button', {
    onClick: function () {
      go('place');
    },
    style: _navBtn(activePage === 'place')
  }, '📍 플레이스 분석'), React.createElement('button', {
    onClick: function () {
      go('placetrack');
    },
    style: _navBtn(activePage === 'placetrack')
  }, '📊 플레이스 추적'), React.createElement('button', {
    onClick: function () {
      go('analysis');
    },
    style: _navBtn(activePage === 'analysis')
  }, '🛒 스토어 분석'), React.createElement('button', {
    onClick: function () {
      go('rank');
    },
    style: _navBtn(activePage === 'rank')
  }, '📊 키워드 순위'), React.createElement('button', {
    onClick: function () {
      go('management');
    },
    style: _navBtn(activePage === 'management')
  }, '📈 로직 분석'), React.createElement('button', {
    onClick: function () {
      go('learning');
    },
    style: _navBtn(activePage === 'learning')
  }, '🎓 학습센터'), React.createElement('button', {
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

;/* ===== js/components/StrengthsHighlightBanner.jsx ===== */
/* StrengthsHighlightBanner — 리포트 상단 '자사 강점 요약' 배너
 * 기존 분석 데이터에서 강점만 파생(신규 데이터 없음). 강점이 1개 이상일 때만 노출. */
window.StrengthsHighlightBanner = function StrengthsHighlightBanner(props) {
  var reviewAnalysis = props.reviewAnalysis;
  var htmlReviewData = props.htmlReviewData;
  var marketRevenue = props.marketRevenue;
  var advertiserReport = props.advertiserReport;
  var datalabGrowth = props.datalabGrowth;
  var parseWon = function (s) {
    return parseInt(String(s == null ? '' : s).replace(/[^0-9]/g, ''), 10) || 0;
  };
  var strengths = [];

  /* 1) 리뷰 경쟁력 — 실측 자사 리뷰수 vs 경쟁 평균 */
  var rc = reviewAnalysis && reviewAnalysis.reviewCount;
  var myReviews = htmlReviewData && htmlReviewData.reviewCount != null ? htmlReviewData.reviewCount : rc && rc.adv != null ? rc.adv : null;
  var avgReviews = rc && rc.avg != null ? rc.avg : null;
  if (myReviews != null && avgReviews != null && avgReviews > 0 && myReviews >= avgReviews) {
    var revMult = myReviews / avgReviews;
    strengths.push({
      icon: '⭐',
      title: '리뷰 경쟁력',
      desc: '경쟁 평균 ' + fmt(avgReviews) + '건 대비 ' + fmt(myReviews) + '건 보유' + (revMult >= 1.2 ? ' (' + revMult.toFixed(1) + '배)' : ''),
      color: '#16a34a',
      bg: '#f0fdf4',
      border: '#bbf7d0'
    });
  }

  /* 2) 가격 경쟁력 — 자사 판매가 vs 1페이지 경쟁 평균가 */
  var myPrice = advertiserReport && advertiserReport.product_info ? advertiserReport.product_info.price || 0 : 0;
  if (!myPrice && marketRevenue) myPrice = parseWon(marketRevenue.avgPrice);
  var compAvg = advertiserReport && advertiserReport.competitor_comparison && advertiserReport.competitor_comparison.stats ? advertiserReport.competitor_comparison.stats.avg_price || 0 : 0;
  if (myPrice > 0 && compAvg > 0 && myPrice <= compAvg) {
    var cheaperPct = Math.round((compAvg - myPrice) / compAvg * 100);
    strengths.push({
      icon: '💰',
      title: '가격 경쟁력',
      desc: cheaperPct > 0 ? '경쟁 평균 대비 ' + cheaperPct + '% 저렴' : '경쟁 평균 수준의 적정가',
      color: '#0ea5e9',
      bg: '#f0f9ff',
      border: '#bae6fd'
    });
  }

  /* 3) 상위 노출 — 현재 순위 10위 이내 */
  var rank = advertiserReport && advertiserReport.ranking ? advertiserReport.ranking.current_rank : null;
  if (rank != null && rank > 0 && rank <= 10) {
    strengths.push({
      icon: '🎯',
      title: '상위 노출 방어',
      desc: '현재 ' + rank + '위 — 이미 상위권 진입',
      color: '#7c3aed',
      bg: '#faf5ff',
      border: '#e9d5ff'
    });
  }

  /* 4) 검색 성장세 — 데이터랩 성장률(신뢰 가능한 값 중 최고) */
  if (datalabGrowth && datalabGrowth.periods && datalabGrowth.periods.length) {
    var best = null;
    datalabGrowth.periods.forEach(function (p) {
      if (p && p.reliable !== false && typeof p.growth === 'number' && p.growth > 0) {
        if (!best || p.growth > best.growth) best = p;
      }
    });
    if (best) {
      strengths.push({
        icon: '🔥',
        title: '검색 성장세',
        desc: '직전 ' + (best.label || '기간') + ' 대비 +' + best.growth + '%',
        color: '#ea580c',
        bg: '#fff7ed',
        border: '#fed7aa'
      });
    }
  }
  if (strengths.length === 0) return null;
  return React.createElement('div', {
    className: 'section fade-in'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    className: 'card',
    style: {
      padding: '18px 20px',
      background: 'linear-gradient(135deg,#eff6ff,#f5f3ff)',
      border: '1px solid #dbeafe'
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
      fontSize: 18
    }
  }, '💪'), React.createElement('span', {
    style: {
      fontSize: 15,
      fontWeight: 800,
      color: '#1e293b'
    }
  }, '한눈에 보는 자사 강점'), React.createElement('span', {
    style: {
      fontSize: 11,
      color: '#94a3b8'
    }
  }, '· 아래 상세 지표에서 근거 확인')), React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
      gap: 10
    }
  }, strengths.map(function (s, i) {
    return React.createElement('div', {
      key: i,
      style: {
        background: s.bg,
        border: '1px solid ' + s.border,
        borderRadius: 12,
        padding: '12px 14px'
      }
    }, React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        marginBottom: 4
      }
    }, React.createElement('span', {
      style: {
        fontSize: 15
      }
    }, s.icon), React.createElement('span', {
      style: {
        fontSize: 13,
        fontWeight: 700,
        color: s.color
      }
    }, s.title)), React.createElement('div', {
      style: {
        fontSize: 12,
        color: '#475569',
        lineHeight: 1.5
      }
    }, s.desc));
  })))));
};

;/* ===== js/components/SeasonUrgencyCountdown.jsx ===== */
/* SeasonUrgencyCountdown — 성수기 긴급성 안내 (데이터랩 시즌 데이터에서 파생)
 * 성수기가 식별될 때만 노출. 비수기엔 역효과 없는 톤으로 안내. */
window.SeasonUrgencyCountdown = function SeasonUrgencyCountdown(props) {
  var season = props.season; // datalabData.season
  if (!season || !season.seasons || !season.seasons.length) return null;
  var seasons = season.seasons;
  var peak = null;
  seasons.forEach(function (s) {
    if (!s) return;
    if (s.peakSeason || s.grade === '최성수기') {
      if (!peak || (s.index || 0) > (peak.index || 0)) peak = s;
    }
  });
  // 최성수기 라벨이 없으면 지수 최고 시즌을 성수기로 간주
  if (!peak) {
    seasons.forEach(function (s) {
      if (s && (!peak || (s.index || 0) > (peak.index || 0))) peak = s;
    });
  }
  if (!peak || !peak.period) return null;

  // "6월 ~ 8월" → 시작월 6
  var mm = String(peak.period).match(/(\d{1,2})\s*월/);
  var startMonth = mm ? parseInt(mm[1], 10) : null;
  if (!startMonth) return null;
  // 끝월(있으면)
  var mm2 = String(peak.period).match(/~\s*(\d{1,2})\s*월/);
  var endMonth = mm2 ? parseInt(mm2[1], 10) : startMonth;
  var now = new Date();
  var curMonth = now.getMonth() + 1; // 1~12

  // 상태 판정
  var inPeak = startMonth <= endMonth ? curMonth >= startMonth && curMonth <= endMonth : curMonth >= startMonth || curMonth <= endMonth; // 겨울처럼 연말~연초 걸침
  var monthsUntil;
  if (inPeak) {
    monthsUntil = 0;
  } else {
    monthsUntil = startMonth - curMonth;
    if (monthsUntil < 0) monthsUntil += 12;
  }
  var box, msg, emoji, col, bg, bd;
  if (inPeak) {
    emoji = '⏰';
    col = '#b91c1c';
    bg = '#fef2f2';
    bd = '#fecaca';
    box = '성수기 진행 중';
    msg = '지금이 ' + peak.name + '(' + peak.period + ') 성수기입니다. 광고·프로모션을 집중할 최적 타이밍입니다.';
  } else if (monthsUntil <= 2) {
    emoji = '🔥';
    col = '#c2410c';
    bg = '#fff7ed';
    bd = '#fed7aa';
    box = '성수기 D-' + monthsUntil + '개월';
    msg = peak.name + ' 성수기(' + peak.period + ')까지 약 ' + monthsUntil + '개월. 지금부터 상품·상세페이지·리뷰를 준비해야 성수기에 상위 노출을 선점합니다.';
  } else {
    emoji = '🗓️';
    col = '#475569';
    bg = '#f8fafc';
    bd = '#e2e8f0';
    box = '다음 성수기까지 ' + monthsUntil + '개월';
    msg = peak.name + ' 성수기(' + peak.period + ')까지 여유가 있습니다. 지금은 비수기 전략(기초 리뷰 확보·콘텐츠 정비)으로 준비하세요.';
  }
  return React.createElement('div', {
    className: 'section fade-in'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    className: 'card',
    style: {
      padding: '16px 20px',
      background: bg,
      border: '1px solid ' + bd,
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      flexWrap: 'wrap'
    }
  }, React.createElement('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      minWidth: 96
    }
  }, React.createElement('div', {
    style: {
      fontSize: 26
    }
  }, emoji), React.createElement('div', {
    style: {
      fontSize: 13,
      fontWeight: 800,
      color: col,
      textAlign: 'center'
    }
  }, box)), React.createElement('div', {
    style: {
      flex: 1,
      minWidth: 220
    }
  }, React.createElement('div', {
    style: {
      fontSize: 13.5,
      fontWeight: 700,
      color: '#1e293b',
      marginBottom: 4
    }
  }, '⏱️ 시즌 타이밍 안내'), React.createElement('div', {
    style: {
      fontSize: 12.5,
      color: '#475569',
      lineHeight: 1.6
    }
  }, msg)))));
};

;/* ===== js/components/RankDeltaROISimulation.jsx ===== */
/* RankDeltaROISimulation — 현재 순위 → 1위 도달 시 예상 성과 증분
 * salesEstimation의 순위별 추정값(실데이터)에서 파생. 값을 지어내지 않음. */
window.RankDeltaROISimulation = function RankDeltaROISimulation(props) {
  var se = props.salesEstimation;
  var currentRank = props.currentRank; // null = 미노출
  if (!se || !se.top10Card) return null;
  var top10 = se.top10Card;
  var n = function (v) {
    return Number(v) || 0;
  };
  var s1 = n(top10.rank1Sales),
    s5 = n(top10.rank5Sales),
    s10 = n(top10.rank10Sales);
  if (s1 <= 0) return null; // 1위 추정치가 없으면 델타 계산 불가

  // 순위 → 예상 월 판매(건) : 1/5/10위 앵커로 선형보간, 10위 밖은 감쇠
  var salesForRank = function (r) {
    if (r == null) return 0; // 미노출 → 0 기준(전량 업사이드)
    if (r <= 1) return s1;
    if (r <= 5) return s1 + (s5 - s1) * (r - 1) / 4;
    if (r <= 10) return s5 + (s10 - s5) * (r - 5) / 5;
    // 10위 밖: 10위 값에서 순위가 낮아질수록 감쇠(최저 10%)
    return Math.max(s10 * Math.pow(0.92, r - 10), s10 * 0.1);
  };
  var isRanked = currentRank != null && currentRank > 0;
  var curSales = Math.round(salesForRank(isRanked ? currentRank : null));
  var tgtSales = Math.round(s1);
  var deltaSales = Math.max(tgtSales - curSales, 0);

  // 이미 1위면 방어 메시지
  var alreadyTop = isRanked && currentRank === 1;
  var curLabel = isRanked ? currentRank + '위' : '미노출';
  var pct = curSales > 0 ? Math.round(deltaSales / curSales * 100) : null;
  var Col = function (title, value, sub, color) {
    return React.createElement('div', {
      style: {
        flex: 1,
        minWidth: 130,
        textAlign: 'center',
        padding: '14px 12px',
        background: '#f8fafc',
        borderRadius: 12,
        border: '1px solid #e2e8f0'
      }
    }, React.createElement('div', {
      style: {
        fontSize: 11,
        fontWeight: 600,
        color: '#94a3b8',
        marginBottom: 6
      }
    }, title), React.createElement('div', {
      style: {
        fontSize: 22,
        fontWeight: 800,
        color: color || '#0f172a'
      }
    }, value), sub ? React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#64748b',
        marginTop: 4
      }
    }, sub) : null);
  };
  return React.createElement('div', {
    className: 'section fade-in'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    className: 'card',
    style: {
      padding: '20px 22px'
    }
  }, React.createElement('h3', {
    className: 'rt-h3'
  }, React.createElement('span', {
    className: 'rt-hic'
  }, '📈'), '순위 상승 시 예상 성과', React.createElement('span', {
    className: 'badge b-est'
  }, '≈ 추정')), React.createElement('div', {
    className: 'rt-desc'
  }, alreadyTop ? '이미 1위입니다 — 방어 관점의 참고 지표입니다.' : '현재 순위 대비 1위 도달 시 예상되는 월 판매 증분(순위별 추정 판매량 기반)'), alreadyTop ? React.createElement('div', {
    style: {
      marginTop: 12,
      padding: '14px 16px',
      background: '#f0fdf4',
      border: '1px solid #bbf7d0',
      borderRadius: 10,
      fontSize: 13,
      color: '#065f46',
      lineHeight: 1.6
    }
  }, '🎉 현재 1위입니다. 예상 월 판매 ~' + fmt(tgtSales) + '건 수준을 유지하려면 리뷰·가격·상세페이지 방어에 집중하세요.') : React.createElement('div', null, React.createElement('div', {
    style: {
      display: 'flex',
      gap: 12,
      marginTop: 12,
      flexWrap: 'wrap',
      alignItems: 'stretch'
    }
  }, Col('현재 (' + curLabel + ')', isRanked ? '~' + fmt(curSales) + '건' : '0건', '예상 월 판매', '#64748b'), Col('목표 (1위)', '~' + fmt(tgtSales) + '건', '예상 월 판매', '#3b82f6'), Col('증분 (Δ)', '+' + fmt(deltaSales) + '건', pct != null ? '현재 대비 +' + pct + '%' : '1위 도달 시 순증', '#16a34a')), React.createElement('div', {
    style: {
      marginTop: 12,
      padding: '10px 14px',
      background: '#fffbeb',
      border: '1px solid #fcd34d',
      borderRadius: 10,
      fontSize: 11.5,
      color: '#92400e',
      lineHeight: 1.6
    }
  }, '※ 순위별 클릭률(CTR) 기반 추정치입니다. 실제 성과는 상품 경쟁력·리뷰·가격·시즌에 따라 달라지며, 순위 상승을 보장하지 않습니다.')))));
};

;/* ===== js/components/CpcBidEstimateSection.jsx ===== */
/* CpcBidEstimateSection — 키워드 예상 CPC·권장 입찰가 (추정)
 * 네이버는 실제 CPC를 제공하지 않으므로, 경쟁지수(실값)+클릭량(실값) 기반의
 * 투명한 추정 밴드로 제시. 절대값이 아니라 '기준선'임을 강하게 고지.
 *
 * + 파워링크 순위별 입찰가 (건의 2026-07-22, 이예은 — 시안 v1 확정):
 *   네이버 검색광고 공식 '입찰가 추정' API로 1~5위 평균 노출 입찰가(PC/모바일) 표를 추가.
 *   데이터 미수신/실패 시 신규 표만 조용히 빠지고 기존 화면과 100% 동일(자동 폴백).
 *   보고서는 화면 DOM을 그대로 복제하므로 이 표가 보고서에도 자동 포함된다. */
window.CpcBidEstimateSection = function CpcBidEstimateSection(props) {
  var keyword = props.keyword || '';

  /* 파워링크 공식 입찰가 — hooks는 조기 return 이전에 선언(Rules of Hooks) */
  var _bs = React.useState(null);
  var bidData = _bs[0];
  var setBidData = _bs[1];
  React.useEffect(function () {
    setBidData(null);
    if (!keyword) return;
    var alive = true;
    var call = function (canRetry) {
      api.post('/keyword/bid-estimate', {
        keyword: keyword
      }).then(function (res) {
        if (!alive) return;
        var d = res && res.success && res.data || null;
        if (d && ((d.pc || []).length > 0 || (d.mobile || []).length > 0)) {
          setBidData(d);
        } else if (canRetry) {
          setTimeout(function () {
            if (alive) call(false);
          }, 3000); // 순간 실패 1회 재조회(검수 철학)
        }
      }).catch(function () {
        if (alive && canRetry) setTimeout(function () {
          if (alive) call(false);
        }, 3000);
      });
    };
    call(true);
    return function () {
      alive = false;
    };
  }, [keyword]);
  var vol = props.volumeData && props.volumeData.length ? props.volumeData[0] : null;
  if (!vol) return null;
  var comp = (vol.compIdx || '').trim();
  // 경쟁지수 → 업종 일반 CPC 밴드(원). 네이버 미제공 → 휴리스틱.
  var bandMap = {
    '높음': {
      base: 900,
      low: 700,
      high: 1200
    },
    '중간': {
      base: 500,
      low: 350,
      high: 700
    },
    '낮음': {
      base: 300,
      low: 200,
      high: 450
    }
  };
  var band = bandMap[comp] || bandMap['중간'];
  var clicks = Math.round((Number(vol.monthlyAvePcClkCnt) || 0) + (Number(vol.monthlyAveMobileClkCnt) || 0));
  var volTotal = (Number(vol.monthlyPcQcCnt) || 0) + (Number(vol.monthlyMobileQcCnt) || 0);
  // 예상 월 광고비(중간 입찰가 × 예상 유입 클릭의 일부). 보수적으로 클릭의 30% 확보 가정.
  var assumedClicks = Math.max(Math.round(clicks * 0.3), 0);
  var estSpendMid = assumedClicks * band.base;
  var won = function (v) {
    return fmt(Math.round(v)) + '원';
  };
  var Kpi = function (k, v, sub, color) {
    return React.createElement('div', {
      className: 'kpi'
    }, React.createElement('div', {
      className: 'k'
    }, k), React.createElement('div', {
      className: 'v',
      style: {
        fontSize: 18,
        color: color || undefined
      }
    }, v), sub ? React.createElement('div', {
      style: {
        fontSize: 11,
        color: '#94a3b8',
        marginTop: 2
      }
    }, sub) : null);
  };

  /* 파워링크 순위별 입찰가 표 (공식 데이터 있을 때만 — 시안 A) */
  var bidTable = null;
  if (bidData) {
    var byPos = {};
    (bidData.pc || []).forEach(function (r) {
      byPos[r.position] = byPos[r.position] || {};
      byPos[r.position].pc = r.bid;
    });
    (bidData.mobile || []).forEach(function (r) {
      byPos[r.position] = byPos[r.position] || {};
      byPos[r.position].mo = r.bid;
    });
    var positions = [1, 2, 3, 4, 5].filter(function (p) {
      return byPos[p];
    });
    var cellR = function (v, bold) {
      return React.createElement('td', {
        style: {
          textAlign: 'right',
          fontWeight: bold ? 800 : undefined
        }
      }, v != null ? won(v) : '—');
    };
    var rows = positions.map(function (p) {
      return React.createElement('tr', {
        key: p
      }, React.createElement('td', null, p === 1 ? React.createElement('b', null, '1위') : p + '위'), cellR(byPos[p].pc, p === 1), cellR(byPos[p].mo, p === 1));
    });
    var mb = bidData.minBid || {};
    if (mb.pc != null || mb.mobile != null) {
      rows.push(React.createElement('tr', {
        key: 'min',
        style: {
          background: '#f8fafc'
        }
      }, React.createElement('td', {
        style: {
          color: '#64748b'
        }
      }, '최소 노출가'), React.createElement('td', {
        style: {
          textAlign: 'right',
          color: '#64748b'
        }
      }, mb.pc != null ? won(mb.pc) : '—'), React.createElement('td', {
        style: {
          textAlign: 'right',
          color: '#64748b'
        }
      }, mb.mobile != null ? won(mb.mobile) : '—')));
    }
    if (rows.length > 0) {
      bidTable = React.createElement('div', {
        style: {
          marginTop: 14,
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 10,
          overflow: 'hidden'
        }
      }, React.createElement('div', {
        style: {
          padding: '10px 14px 0',
          fontSize: 13,
          fontWeight: 800,
          color: '#0f172a'
        }
      }, '🎯 파워링크 순위별 입찰가 ', React.createElement('span', {
        className: 'badge b-ok'
      }, '네이버 공식 추정')), React.createElement('div', {
        style: {
          padding: '2px 14px 8px',
          fontSize: 11.5,
          color: '#64748b'
        }
      }, '네이버 검색광고 API의 순위별 평균 노출 입찰가 — 광고시스템 콘솔의 \'예상 입찰가\'와 같은 소스'), React.createElement('table', {
        className: 'rt-table',
        style: {
          margin: 0
        }
      }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', {
        style: {
          width: 90
        }
      }, '노출 순위'), React.createElement('th', {
        style: {
          textAlign: 'right'
        }
      }, 'PC 입찰가'), React.createElement('th', {
        style: {
          textAlign: 'right'
        }
      }, '모바일 입찰가'))), React.createElement('tbody', null, rows)));
    }
  }
  return React.createElement('div', {
    className: 'section fade-in'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    className: 'card',
    style: {
      padding: '20px 22px'
    }
  }, React.createElement('h3', {
    className: 'rt-h3'
  }, React.createElement('span', {
    className: 'rt-hic'
  }, '💸'), '예상 CPC · 권장 입찰가', React.createElement('span', {
    style: {
      fontSize: 11,
      fontWeight: 500,
      color: '#94a3b8'
    }
  }, '(CPC = 클릭당 광고비)'), React.createElement('span', {
    className: 'badge b-est'
  }, '≈ 추정'), bidTable ? React.createElement('span', {
    className: 'badge b-ok'
  }, '✅ 파워링크 공식 추정 포함') : null), React.createElement('div', {
    className: 'rt-desc'
  }, (keyword ? '"' + keyword + '" ' : '') + '경쟁지수 "' + (comp || '중간') + '" · 월 검색량 ' + fmt(volTotal) + '회 기준 추정' + (bidTable ? ' + 네이버 검색광고 공식 입찰가 추정' : '')), React.createElement('div', {
    className: 'grid4',
    style: {
      marginTop: 10
    }
  }, Kpi('예상 CPC(중간)', won(band.base), '클릭당 예상 단가', '#0f172a'), Kpi('권장 입찰가 범위', fmt(band.low) + '~' + fmt(band.high) + '원', '저가~상위노출가'), Kpi('예상 월 클릭', fmt(clicks) + '회', '네이버 실측 평균클릭'), Kpi('예상 월 광고비', '~' + won(estSpendMid), '클릭 30% 확보 가정', '#3b82f6')), bidTable, React.createElement('div', {
    style: {
      marginTop: 14,
      background: '#f8fafc',
      border: '1px solid #e2e8f0',
      borderRadius: 10,
      overflow: 'hidden'
    }
  }, React.createElement('table', {
    className: 'rt-table',
    style: {
      margin: 0
    }
  }, React.createElement('thead', null, React.createElement('tr', null, React.createElement('th', null, '전략'), React.createElement('th', {
    style: {
      textAlign: 'right'
    }
  }, '입찰가(추정)'), React.createElement('th', null, '기대 효과'))), React.createElement('tbody', null, React.createElement('tr', null, React.createElement('td', null, '저가 진입'), React.createElement('td', {
    style: {
      textAlign: 'right'
    }
  }, won(band.low)), React.createElement('td', null, '노출 제한적·광고비 절약 (SEO 병행 권장)')), React.createElement('tr', null, React.createElement('td', null, '표준'), React.createElement('td', {
    style: {
      textAlign: 'right',
      fontWeight: 700
    }
  }, won(band.base)), React.createElement('td', null, '평균적 노출 확보')), React.createElement('tr', null, React.createElement('td', null, '상위 노출'), React.createElement('td', {
    style: {
      textAlign: 'right'
    }
  }, won(band.high)), React.createElement('td', null, '상단 노출 경쟁 우위 (광고비 부담↑)'))))), React.createElement('div', {
    style: {
      marginTop: 12,
      padding: '10px 14px',
      background: '#fffbeb',
      border: '1px solid #fcd34d',
      borderRadius: 10,
      fontSize: 11.5,
      color: '#92400e',
      lineHeight: 1.6
    }
  }, bidTable ? '※ 순위별 입찰가는 네이버 검색광고의 공식 추정치(최근 실제 입찰·노출 데이터 기반)입니다. 단 실시간 낙찰가는 아니며, 품질지수·순간 경쟁에 따라 실제 지불 단가는 달라질 수 있습니다. 위 전략 밴드는 기존 경쟁지수 기반 참고 추정입니다.' : '※ 네이버는 키워드별 실제 CPC를 제공하지 않습니다. 위 값은 경쟁지수·클릭량 기반 업종 일반 추정 밴드로, 실제 입찰 단가는 광고 시스템의 실시간 경쟁·품질지수에 따라 달라집니다. 집행 전 네이버 검색광고 관리시스템에서 실제 예상 입찰가를 확인하세요.'))));
};

;/* ===== js/components/TrackRegisterButton.jsx ===== */
/* TrackRegisterButton — 분석한 상품을 순위추적에 원클릭 등록
 * 기존 POST /api/products/track 재사용. 자동등록이 아니라 명시적 1클릭(서버 부하 방지). */
window.TrackRegisterButton = function TrackRegisterButton(props) {
  var searchedProductUrl = props.searchedProductUrl;
  var searchedKeyword = props.searchedKeyword;
  var products = props.products;
  var refreshProducts = props.refreshProducts;
  var canEdit = props.canEdit;
  var st = React.useState(false);
  var adding = st[0],
    setAdding = st[1];
  if (!searchedProductUrl || !searchedKeyword || !canEdit) return null;
  var already = (products || []).find(function (p) {
    return p.product_url === searchedProductUrl;
  });
  var alreadyHasKw = already && (already.keywords || []).some(function (k) {
    return (typeof k === 'string' ? k : k && k.keyword) === searchedKeyword;
  });
  var onClick = function () {
    if (adding) return;
    setAdding(true);
    api.post('/products/track', {
      product_url: searchedProductUrl,
      keywords: [searchedKeyword],
      store_name_hint: props.storeNameHint || undefined
    }).then(function (res) {
      if (res && res.success) {
        if (typeof toast !== 'undefined' && toast.success) toast.success('순위 추적에 등록했습니다. 첫 순위 체크를 시작합니다.');
        if (refreshProducts) refreshProducts();
      } else {
        if (typeof toast !== 'undefined' && toast.error) toast.error(res && res.detail || '추적 등록에 실패했습니다.');
      }
      setAdding(false);
    }).catch(function (e) {
      if (typeof toast !== 'undefined' && toast.error) toast.error('추적 등록 실패: ' + (e.message || '네트워크 오류'));
      setAdding(false);
    });
  };
  var wrap = {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    margin: '4px 0 4px',
    flexWrap: 'wrap'
  };
  if (already) {
    return React.createElement('div', {
      className: 'container'
    }, React.createElement('div', {
      style: wrap
    }, /* no-export: 직원용 운영 상태 표시 — 광고주 전달본(내보내기)에서는 제외 */
    React.createElement('span', {
      className: 'no-export',
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '8px 14px',
        borderRadius: 10,
        background: '#ecfdf5',
        border: '1px solid #a7f3d0',
        color: '#047857',
        fontSize: 12.5,
        fontWeight: 700
      }
    }, '✓ 이미 추적 중인 상품입니다' + (alreadyHasKw ? ' (이 키워드 포함)' : '')), !alreadyHasKw ? React.createElement('button', {
      onClick: onClick,
      disabled: adding,
      style: {
        padding: '8px 14px',
        borderRadius: 10,
        border: '1px solid #c7d2fe',
        background: '#eef2ff',
        color: '#3b82f6',
        fontSize: 12.5,
        fontWeight: 700,
        cursor: adding ? 'default' : 'pointer'
      }
    }, adding ? '등록 중...' : '＋ 이 키워드도 추적 추가') : null));
  }
  return React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    style: wrap
  }, React.createElement('button', {
    onClick: onClick,
    disabled: adding,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 8,
      padding: '10px 18px',
      borderRadius: 10,
      border: 'none',
      background: adding ? '#94a3b8' : 'linear-gradient(135deg,#3b82f6,#3b82f6)',
      color: '#fff',
      fontSize: 13,
      fontWeight: 700,
      cursor: adding ? 'default' : 'pointer',
      boxShadow: '0 3px 10px rgba(79,70,229,0.3)'
    }
  }, adding ? '⏳ 등록 중...' : '🔍 이 상품 순위 추적 시작'), React.createElement('span', {
    style: {
      fontSize: 11.5,
      color: '#94a3b8'
    }
  }, '이후 이 키워드의 순위 변화를 자동 기록합니다')));
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
  var auditStatus = props.auditStatus;
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

  /* 광고주/스토어명 자동 채우기 (2026-07-27 수정)
     주의: 백엔드 store_name 은 쇼핑API 매칭·상품페이지 방문이 모두 실패하면
     'URL 슬러그'가 그대로 담긴다. 슬러그가 이메일 아이디인 업체가 있어 표지에
     'chajju2009' 처럼 찍히는 신고가 있었다(윤채은 07-27). 따라서 슬러그와 같은 값은
     '이름 미확보'로 보고, 상세 HTML에서 뽑은 실제 상호명(storeInfo)을 우선 사용한다.
     ※ 슬러그는 순위 매칭 키로 계속 쓰이므로 여기서는 '표시용'만 판단한다. */
  var _urlSlug = function () {
    try {
      var m = (searchedProductUrl || '').match(/smartstore\.naver\.com\/([^\/?#]+)/);
      return m ? decodeURIComponent(m[1]) : '';
    } catch (e) {
      return '';
    }
  }();
  var _isSlug = function (v) {
    return !!v && !!_urlSlug && String(v).trim().toLowerCase() === _urlSlug.trim().toLowerCase();
  };
  var _realStoreName = function () {
    var cands = [htmlDetailResult && htmlDetailResult.storeInfo && htmlDetailResult.storeInfo.name, advertiserReport && advertiserReport.product_info && advertiserReport.product_info.store_name, analysisData && analysisData.targetProductInfo && analysisData.targetProductInfo.store_name, analysisData && analysisData.htmlDetail && analysisData.htmlDetail.storeInfo && analysisData.htmlDetail.storeInfo.name];
    for (var i = 0; i < cands.length; i++) {
      var v = cands[i] && String(cands[i]).trim();
      if (v && !_isSlug(v)) return v; // 슬러그와 같은 값은 이름으로 인정하지 않음
    }
    return '';
  }();
  /* 실제 이름을 못 구하면 최후에만 슬러그(빈 표지보다는 낫다) */
  var _storeName = _realStoreName || _urlSlug || '';
  var _displayCompany = companyName || _storeName;
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
    className: 'badge b-dl'
  }, '📊 데이터랩'), ' 쇼핑인사이트 통계'), React.createElement('div', null, React.createElement('b', {
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
  }, _displayCompany || '-')), React.createElement('div', {
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
  }, new Date().toLocaleDateString('ko'))))),
  /* 배지 범례 — report-main 내부에 두어 전달본(내보내기)에도 포함되게 함
   * (좌측 목차의 범례는 캡처 범위 밖이라 전달본에서 소실되던 문제 보완) */
  analysisData && React.createElement('div', {
    className: 'report-legend'
  }, React.createElement('b', {
    className: 'badge b-ok'
  }, '✅ 실측'), ' 네이버 실제값', React.createElement('span', {
    className: 'rl-sep'
  }, '·'), React.createElement('b', {
    className: 'badge b-dl'
  }, '📊 데이터랩'), ' 쇼핑인사이트 통계', React.createElement('span', {
    className: 'rl-sep'
  }, '·'), React.createElement('b', {
    className: 'badge b-est'
  }, '≈ 추정'), ' 계산·근거 기반', React.createElement('span', {
    className: 'rl-sep'
  }, '·'), React.createElement('b', {
    className: 'badge b-ai'
  }, 'AI'), ' AI 생성'), /* 모바일용 가로 목차 */
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
  }), /* [검수] 데이터 검수 상태 배너 — 항목별 실데이터 확보 현황(✓ 확보 · ↻ 재조회 중 · ✗ 실패) */
  auditStatus && auditStatus.items && auditStatus.items.length > 0 && React.createElement('div', {
    className: 'section fade-in'
  }, React.createElement('div', {
    className: 'container'
  }, React.createElement('div', {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      gap: 10,
      background: '#f8fafc',
      border: '1px solid #e2e8f0',
      borderRadius: 10,
      padding: '10px 14px',
      fontSize: 12.5
    }
  }, React.createElement('b', {
    style: {
      color: '#334155'
    }
  }, auditStatus.phase === 'auditing' ? '🔍 데이터 검수 중…' : '🔍 데이터 검수'), auditStatus.items.map(function (it, i) {
    var color = it.st === 'ok' ? '#059669' : it.st === 'retry' ? '#d97706' : it.st === 'wait' ? '#94a3b8' : '#dc2626';
    var mark = it.st === 'ok' ? '✓' : it.st === 'retry' ? '↻' : it.st === 'wait' ? '…' : '✗';
    return React.createElement('span', {
      key: i,
      style: {
        color: color,
        whiteSpace: 'nowrap',
        fontWeight: 600
      }
    }, mark + ' ' + it.name);
  })))), /* [DATALAB] 로딩 인디케이터 */
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
      color: '#3b82f6',
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
    color: '#3b82f6',
    sub: '광고주가 가장 먼저 보는 핵심 지표'
  }), analysisData && analysisData.summaryCards && React.createElement(window.SectionErrorBoundary, {
    name: '종합 요약'
  }, React.createElement('div', {
    id: 'sec-summary'
  }, React.createElement(SummaryCardsSection, {
    data: analysisData.summaryCards,
    /* 히어로 요약용 — 전부 기존 데이터 재사용(없으면 히어로만 생략) */
    keyword: searchedKeyword,
    advertiserReport: advertiserReport,
    rankCheckResult: rankCheckResult,
    htmlReviewData: htmlReviewData
  }))), /* 자사 강점 요약 배너 (강점 1개 이상일 때만 노출) */
  analysisData && React.createElement(window.SectionErrorBoundary, {
    name: '강점 요약'
  }, React.createElement(window.StrengthsHighlightBanner, {
    reviewAnalysis: analysisData.reviewAnalysis,
    htmlReviewData: htmlReviewData,
    marketRevenue: analysisData.marketRevenue,
    advertiserReport: advertiserReport,
    datalabGrowth: datalabData && datalabData.growth
  })), /* ========== 2. 시장 · 수요 진단 ========== */
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
  })), /* [DATALAB] 일일 한도 소진 안내 — 서버 quotaNotice 수신 시에만 노출 */
  datalabData && datalabData.quotaNotice && React.createElement('div', {
    className: 'section fade-in',
    style: {
      background: '#fffbeb',
      border: '1px solid #fde68a',
      borderRadius: 10,
      padding: '10px 14px',
      color: '#92400e',
      fontSize: 13,
      lineHeight: 1.6
    }
  }, '⏳ ' + datalabData.quotaNotice), /* [DATALAB] 12개월 검색량 트렌드 (꺾은선) */
  datalabData && datalabData.trend && React.createElement(window.SectionErrorBoundary, {
    name: '검색량 트렌드'
  }, React.createElement(window.DatalabTrendSection, {
    data: datalabData.trend
  })), /* [DATALAB] 시즌별 수요 예측 */
  datalabData && datalabData.season && React.createElement(window.SectionErrorBoundary, {
    name: '시즌별 수요'
  }, React.createElement(window.DatalabSeasonSection, {
    data: datalabData.season
  })), /* 성수기 긴급성 안내 (성수기 식별 시) */
  datalabData && datalabData.season && React.createElement(window.SectionErrorBoundary, {
    name: '시즌 긴급성'
  }, React.createElement(window.SeasonUrgencyCountdown, {
    season: datalabData.season
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
    advRank: rankCheckResult && rankCheckResult.rank_position != null ? rankCheckResult.rank_position : advertiserReport && advertiserReport.ranking ? advertiserReport.ranking.current_rank : null,
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
  })), /* 예상 CPC · 권장 입찰가 (추정) */
  analysisData && volumeData && volumeData.length && React.createElement(window.SectionErrorBoundary, {
    name: '예상 CPC'
  }, React.createElement(window.CpcBidEstimateSection, {
    volumeData: volumeData,
    keyword: searchedKeyword
  })), /* 경쟁사 비교표 (상위 80개) */
  analysisData && analysisData.competitorTable && React.createElement(window.SectionErrorBoundary, {
    name: '경쟁사 비교표'
  }, React.createElement(window.CompetitorTableSection, {
    data: analysisData.competitorTable
  })),
  /* 경쟁사 상위 10개 비교 · 격차 분석 — 3장(경쟁 진단)으로 재배치.
   * 같은 컴포넌트를 part로 분할 렌더: 여기선 경쟁 비교/격차만, 전략 제안은 6장에 유지 */
  (advertiserReport || analysisData && analysisData.strategicAnalysis) && !advertiserLoading && React.createElement(window.SectionErrorBoundary, {
    name: '경쟁 격차 분석'
  }, React.createElement(EntryStrategySection, {
    advertiserData: advertiserReport,
    strategicData: analysisData && analysisData.strategicAnalysis,
    keyword: searchedKeyword,
    rankCheckResult: rankCheckResult,
    part: 'competition'
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
  }),
  /* 키워드별 노출 순위 — analysisOnly 모드(노출 분석·1회성 조회만, 보고서 구성 요소).
     추적 상품 목록·등록 관리만 📊 키워드 순위 탭으로 분리(2026-08-04, 직원 신고로
     노출 분석 블록은 복구 — 탭 분리 대상은 '추적 현황 열람'이지 분석 결과가 아님). */
  React.createElement(window.SectionErrorBoundary, {
    name: '순위 추적'
  }, React.createElement(RankTrackingSection, {
    analysisOnly: true,
    onOpenRankTab: props.onOpenRankTab,
    products: products,
    refreshProducts: loadProducts,
    searchedKeyword: searchedKeyword,
    searchedProductUrl: searchedProductUrl,
    cachedProductName: advertiserReport && advertiserReport.product_info && advertiserReport.product_info.product_name ? advertiserReport.product_info.product_name : advertiserReport && advertiserReport.product_name ? advertiserReport.product_name : analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo.product_name : null,
    relatedKeywords: relatedData ? (relatedData.golden_keywords || []).concat(relatedData.related_keywords || []).map(function (k) {
      return typeof k === 'string' ? k : k && k.keyword || '';
    }).filter(Boolean) : [],
    onNavigateToClient: handleNavigateToClient,
    canEdit: currentUser.role !== 'viewer',
    onRankResult: setRankCheckResult
  })), /* 분석 상품 순위추적 원클릭 등록 */
  searchedProductUrl && React.createElement(window.SectionErrorBoundary, {
    name: '추적 등록'
  }, React.createElement(window.TrackRegisterButton, {
    searchedProductUrl: searchedProductUrl,
    searchedKeyword: searchedKeyword,
    products: products,
    refreshProducts: loadProducts,
    canEdit: currentUser.role !== 'viewer',
    storeNameHint: _realStoreName
  })), /* 판매량 추정 */
  analysisData && analysisData.salesEstimation && React.createElement(window.SectionErrorBoundary, {
    name: '판매량 추정'
  }, React.createElement('div', {
    id: 'sec-sales'
  }, React.createElement(SalesEstimationSection, {
    productUrl: searchedProductUrl,
    data: analysisData.salesEstimation,
    reviewCount: htmlReviewData && htmlReviewData.reviewCount || (analysisData.reviewAnalysis && analysisData.reviewAnalysis.reviewCount ? analysisData.reviewAnalysis.reviewCount.adv : null),
    productPrice: analysisData.marketRevenue ? parseInt((analysisData.marketRevenue.avgPrice || '0').replace(/[^0-9]/g, '')) : 0
  }))), /* 순위 상승 시 예상 성과(ROI 델타) */
  analysisData && analysisData.salesEstimation && React.createElement(window.SectionErrorBoundary, {
    name: 'ROI 시뮬레이션'
  }, React.createElement(window.RankDeltaROISimulation, {
    salesEstimation: analysisData.salesEstimation,
    currentRank: rankCheckResult && rankCheckResult.rank_position != null ? rankCheckResult.rank_position : advertiserReport && advertiserReport.ranking ? advertiserReport.ranking.current_rank : null
  })), /* 리뷰 & 찜 분석 */
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
    cachedProductName: advertiserReport && advertiserReport.product_info && advertiserReport.product_info.product_name ? advertiserReport.product_info.product_name : advertiserReport && advertiserReport.product_name ? advertiserReport.product_name : analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo.product_name : null,
    cachedTotalVolume: volumeData && volumeData[0] ? (volumeData[0].monthlyPcQcCnt || 0) + (volumeData[0].monthlyMobileQcCnt || 0) : null,
    cachedProductInfo: analysisData && analysisData.targetProductInfo ? analysisData.targetProductInfo : null,
    shopProducts: shopProducts,
    htmlReviewData: htmlReviewData
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
    data: relatedData,
    keyword: searchedKeyword
  })), /* 골든 키워드 (0건이어도 대안 안내를 렌더) */
  analysisData && React.createElement(window.SectionErrorBoundary, {
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
  }), /* 17. 1페이지 진입 전략 (경쟁 비교표·격차는 3장으로 이동 — part 분할) */
  (advertiserReport || analysisData && analysisData.strategicAnalysis) && !advertiserLoading && React.createElement(window.SectionErrorBoundary, {
    name: '진입 전략'
  }, React.createElement(EntryStrategySection, {
    advertiserData: advertiserReport,
    strategicData: analysisData && analysisData.strategicAnalysis,
    keyword: searchedKeyword,
    rankCheckResult: rankCheckResult,
    part: 'strategy'
  })), /* 19. AI 종합 분석 리포트 */
  analysisData && React.createElement(window.SectionErrorBoundary, {
    name: 'AI 종합 분석'
  }, React.createElement(AiFeedbackAllSection, {
    keyword: searchedKeyword,
    analysisData: analysisData,
    volumeData: volumeData,
    relatedData: relatedData,
    advertiserReport: advertiserReport,
    htmlReviewData: htmlReviewData,
    datalabData: datalabData
  })), /* 20. 업체 등록/저장 — 관리팀은 업체+경쟁사, 영업사원(viewer)은 경쟁사 저장만 */
  analysisData && React.createElement(window.SectionErrorBoundary, {
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
    htmlDetailResult: htmlDetailResult,
    competitorContext: props.competitorContext,
    onCompetitorSaved: props.onCompetitorSaved,
    isViewer: currentUser.role === 'viewer',
    defaultName: _displayCompany
  })), /* 21. 보고서 출력 */
  searchedProductUrl && React.createElement(window.SectionErrorBoundary, {
    name: '보고서'
  }, React.createElement(ReportSection, {
    keyword: searchedKeyword,
    companyName: companyName,
    managerName: currentUser && currentUser.name
  })), /* 알림 설정 (admin/superadmin만) */
  (currentUser.role === 'admin' || currentUser.role === 'superadmin') && React.createElement(window.SectionErrorBoundary, {
    name: '알림 설정'
  }, React.createElement(NotificationSection, null)), /* 푸터 */
  React.createElement(window.Footer, null)) /* report-main 닫기 */) /* report-shell 닫기 */;
};

;/* ===== js/components/PlaceRankChart.jsx ===== */
/* PlaceRankChart — 플레이스 (업체·키워드) 일자별 순위 추이 (역Y축 선형 차트)
 * props: { series:[{date,rank,state}], keyword, days, onDays(days), onSave() }
 * 순위는 낮을수록 상위 → Y축 reverse. 미노출/미확인(rank=null)은 선이 끊김(spanGaps=false).
 * ChartCanvas(Chart.js 래퍼) 재사용 — 쇼핑 순위 추적과 동일 엔진.
 */
window.PlaceRankChart = function PlaceRankChart(props) {
  var series = Array.isArray(props.series) ? props.series : [];
  var keyword = props.keyword || '대표 키워드';
  var days = props.days || 30;
  var onDays = props.onDays || function () {};
  var labels = series.map(function (p) {
    var d = String(p.date || '').split('-');
    return d.length === 3 ? parseInt(d[1], 10) + '/' + parseInt(d[2], 10) : p.date || '';
  });
  var ranks = series.map(function (p) {
    return p.rank == null ? null : p.rank;
  });
  var valid = ranks.filter(function (r) {
    return r != null;
  });
  var maxR = valid.length ? Math.max.apply(null, valid) : 16;
  var yMax = Math.max(16, maxR + 2);
  var OK = window.CHART_COLORS && window.CHART_COLORS.OK || '#16a34a';
  var data = {
    labels: labels,
    datasets: [{
      label: '순위',
      data: ranks,
      borderColor: OK,
      backgroundColor: 'rgba(22,163,74,0.12)',
      fill: true,
      spanGaps: false,
      tension: 0.3,
      pointRadius: 3,
      pointHoverRadius: 5,
      pointBackgroundColor: OK,
      borderWidth: 2.5
    }]
  };
  var options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false
      },
      tooltip: {
        callbacks: {
          label: function (c) {
            return c.parsed.y == null ? '미노출/미확인' : c.parsed.y + '위';
          }
        }
      }
    },
    scales: {
      y: {
        reverse: true,
        min: 1,
        suggestedMax: yMax,
        ticks: {
          stepSize: Math.max(1, Math.round(yMax / 6)),
          callback: function (v) {
            return v + '위';
          }
        },
        title: {
          display: true,
          text: '순위 (낮을수록 상위 ↑)',
          font: {
            size: 10
          }
        },
        grid: {
          color: '#eef2f7'
        }
      },
      x: {
        grid: {
          display: false
        }
      }
    }
  };
  var CANVAS_ID = 'place-rankchart';
  /* 📸 이미지 저장 — 스토어 순위 추적과 동일한 공용 빌더(exportRankHistoryImage)로 렌더
   * (헤더 카드·이력 표·변동 ▲▼·추이 차트·워터마크). 날것 차트 캔버스 덤프는 폴백만. */
  var saveImg = function () {
    try {
      if (!series.length) {
        try {
          toast.warn('저장할 순위 데이터가 없습니다.');
        } catch (e) {}
        return;
      }
      if (window.exportRankHistoryImage) {
        window.exportRankHistoryImage({
          rows: series.map(function (p) {
            return {
              checked_at: p.date || '',
              rank_position: p.rank == null ? null : p.rank,
              type_label: p.state || '미확인',
              rank_null_label: '–'
            };
          }),
          storeName: props.businessName || '플레이스 업체',
          keyword: keyword,
          storeUrl: props.placeUrl || '',
          days: days >= 365 ? 0 : days,
          typeHeader: '상태'
        });
        return;
      }
      var cv = document.getElementById(CANVAS_ID);
      var url = '';
      var ch = window.Chart && window.Chart.getChart && cv ? window.Chart.getChart(cv) : null;
      if (ch) {
        url = ch.toBase64Image('image/png', 1);
      } else if (cv && cv.toDataURL) {
        url = cv.toDataURL('image/png');
      }
      if (!url) {
        try {
          toast.warn('차트가 아직 렌더되지 않았습니다.');
        } catch (e) {}
        return;
      }
      var a = document.createElement('a');
      a.href = url;
      a.download = keyword + '_순위추이_' + new Date().toISOString().slice(0, 10) + '.png';
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      try {
        toast.error('이미지 저장 실패');
      } catch (e2) {}
    }
  };
  var periodBtn = function (label, val) {
    var on = val === 'all' ? days >= 365 : days === val;
    return React.createElement('button', {
      className: on ? 'on' : '',
      onClick: function () {
        onDays(val === 'all' ? 365 : val);
      }
    }, label);
  };
  return React.createElement('div', {
    className: 'subcard'
  }, React.createElement('div', {
    className: 'h'
  }, React.createElement('span', {
    className: 't'
  }, "📉 '" + keyword + "' 순위 추이"), React.createElement('div', {
    className: 'periods'
  }, periodBtn('7일', 7), periodBtn('30일', 30), periodBtn('전체', 'all')), React.createElement('button', {
    className: 'btn btn-success btn-sm',
    style: {
      marginLeft: 7
    },
    onClick: saveImg
  }, '📸 이미지 저장')), series.length === 0 ? React.createElement('div', {
    className: 'empty',
    style: {
      padding: '22px 6px'
    }
  }, '아직 추적 데이터가 없습니다. 이 키워드로 분석할 때마다 순위가 하루 1점씩 누적됩니다.') : React.createElement('div', {
    className: 'chartbox',
    style: {
      height: 200
    }
  }, React.createElement(window.ChartCanvas, {
    type: 'line',
    data: data,
    options: options,
    height: 200,
    canvasId: CANVAS_ID
  })), React.createElement('div', {
    className: 'chartfoot'
  }, '※ 선이 위로 갈수록 상위 노출(1위=맨 위). 끊긴 구간은 200위 밖 또는 미확인. 플레이스는 서버 크롤이 불가해 캡처할 때마다 순위가 저장됩니다.'));
};

;/* ===== js/components/PlaceAnalysisPage.jsx ===== */
/* PlaceAnalysisPage — 로직분석 「플레이스 분석」 화면 (오프라인·지역 업종)
 *
 * 스토어 분석과 동일 엔진 구조를 쓰되, 플레이스 프리셋으로:
 *  - 입력: 업체명·지역·추적 키워드(최대 10개, 분석 대상 1개 선택)·플레이스 검색결과 캡처(HTML)
 *  - 분석: POST /api/seo/analyze { vertical:'place', ... } → 로컬 10지표 점수·순위(3-state)·경쟁사
 *  - 보완 지표(저장수·예약·소식·정보)는 결과 화면에서 인라인 입력 → 재점수화(하이브리드)
 *  - 순위 추적: 캡처마다 순위가 하루 1점 누적 → 역Y축 선형 차트(§2)
 *  - AI 진단: POST /api/ai/feedback-all { vertical:'place', sections:{...} }
 *
 * 확정 시안(2026-07-23 v2) 구조·팔레트를 그대로 이식. 스타일은 css/place.css(.place-analysis 스코프).
 */
window.PlaceAnalysisPage = function PlaceAnalysisPage(props) {
  var React_ = React,
    useState = React.useState,
    useEffect = React.useEffect,
    useRef = React.useRef;
  var currentUser = props.currentUser || {};

  // ── 입력 상태 ──
  var _b = useState('');
  var businessName = _b[0],
    setBusinessName = _b[1];
  var _r = useState('');
  var region = _r[0],
    setRegion = _r[1];
  var _kws = useState([]);
  var keywords = _kws[0],
    setKeywords = _kws[1];
  var _kin = useState('');
  var kwInput = _kin[0],
    setKwInput = _kin[1];
  var _sel = useState('');
  var selectedKw = _sel[0],
    setSelectedKw = _sel[1];
  var _html = useState('');
  var placeHtml = _html[0],
    setPlaceHtml = _html[1];

  // 담당자 보완 지표
  var _supp = useState({
    saves: '',
    photos: '',
    news_days: '',
    info_complete: '',
    has_booking: false,
    has_talk: false,
    has_order: false,
    rep_keyword: false
  });
  var supp = _supp[0],
    setSupp = _supp[1];

  // ── 결과 상태 ──
  var _load = useState(false);
  var loading = _load[0],
    setLoading = _load[1];
  var _res = useState(null);
  var result = _res[0],
    setResult = _res[1];
  var _al = useState(false);
  var aiLoading = _al[0],
    setAiLoading = _al[1];
  var _ai = useState(null);
  var ai = _ai[0],
    setAi = _ai[1];
  var _cs = useState([]);
  var chartSeries = _cs[0],
    setChartSeries = _cs[1];
  var _cd = useState(30);
  var chartDays = _cd[0],
    setChartDays = _cd[1];
  var _ck = useState('');
  var chartKeyword = _ck[0],
    setChartKeyword = _ck[1];
  var _kc = useState([]);
  var kwChips = _kc[0],
    setKwChips = _kc[1];
  var lastHtmlRef = useRef('');
  var aiTimerRef = useRef(null);

  // ── 업체 저장 (스토어 SaveToClientSection 과 동일 규칙 — /cd/quick-register 재사용) ──
  var _sb = useState(false);
  var saveBusy = _sb[0],
    setSaveBusy = _sb[1];
  var _sm = useState(null);
  var saveMsg = _sm[0],
    setSaveMsg = _sm[1];

  // ==================== 유틸 ====================
  var METRIC_ORDER = ['rank', 'relevance', 'visitor_review', 'blog_review', 'save', 'photo', 'booking', 'review_keyword', 'activity', 'info'];
  var MEASURED = {
    rank: 1,
    visitor_review: 1,
    blog_review: 1,
    relevance: 1,
    review_keyword: 1,
    photo: 1
  };
  var scoreCol = function (s) {
    return window.scoreColor ? window.scoreColor(s) : s >= 70 ? '#059669' : s >= 40 ? '#d97706' : '#dc2626';
  };
  var gradeOf = function (t) {
    if (t >= 90) return 'A+';
    if (t >= 83) return 'A';
    if (t >= 77) return 'A-';
    if (t >= 71) return 'B+';
    if (t >= 65) return 'B';
    if (t >= 59) return 'B-';
    if (t >= 52) return 'C+';
    if (t >= 45) return 'C';
    if (t >= 38) return 'C-';
    if (t >= 30) return 'D';
    return 'F';
  };
  var fmtN = function (n) {
    return window.fmt ? window.fmt(n) : n == null ? '-' : String(n);
  };
  var suppPayload = function () {
    var p = {};
    if (supp.saves !== '') p.saves = Number(supp.saves) || 0;
    if (supp.photos !== '') p.photos = Number(supp.photos) || 0;
    if (supp.news_days !== '') p.news_days = Number(supp.news_days);
    if (supp.info_complete !== '') p.info_complete = Math.max(0, Math.min(100, Number(supp.info_complete) || 0));
    p.has_booking = !!supp.has_booking;
    p.has_talk = !!supp.has_talk;
    p.has_order = !!supp.has_order;
    p.rep_keyword = !!supp.rep_keyword;
    return p;
  };

  // ==================== 키워드 관리 ====================
  var addKeyword = function (raw) {
    var t = (raw || '').trim();
    if (!t) return;
    if (keywords.indexOf(t) !== -1) {
      setKwInput('');
      return;
    }
    if (keywords.length >= 10) {
      try {
        toast.warn('추적 키워드는 최대 10개입니다.');
      } catch (e) {}
      return;
    }
    var next = keywords.concat([t]);
    setKeywords(next);
    if (!selectedKw) setSelectedKw(t);
    setKwInput('');
  };
  var removeKeyword = function (kw) {
    var next = keywords.filter(function (k) {
      return k !== kw;
    });
    setKeywords(next);
    if (selectedKw === kw) setSelectedKw(next[0] || '');
  };

  // ==================== 분석 실행 ====================
  var runAnalyze = function (opts) {
    opts = opts || {};
    var kw = selectedKw || keywords[0] || '';
    var html = opts.reuseHtml ? lastHtmlRef.current || placeHtml : placeHtml;
    if (!businessName.trim()) {
      try {
        toast.warn('업체명을 입력해주세요.');
      } catch (e) {}
      return;
    }
    if (!kw) {
      try {
        toast.warn('추적 키워드를 1개 이상 추가하고, 분석할 키워드를 선택하세요.');
      } catch (e) {}
      return;
    }
    if ((html || '').trim().length < 100) {
      try {
        toast.warn('플레이스 검색결과 HTML을 붙여넣어주세요. (북마클릿으로 캡처)');
      } catch (e) {}
      return;
    }
    setLoading(true);
    lastHtmlRef.current = html;
    var body = {
      // ⚠️ product_url 은 SeoAnalysisRequest 의 **필수 필드**다(쇼핑 경로용).
      //    플레이스는 상품 URL 이 없어 안 보냈는데, 그러면 요청이 서버 검증에서
      //    422 로 튕기고 화면엔 「[object Object]」만 떴다(2026-08-05 대표 신고).
      //    플레이스 분기는 product_url 을 읽지 않으므로 빈 문자열로 형식만 맞춘다.
      product_url: '',
      vertical: 'place',
      keyword: kw,
      region: region.trim(),
      target_name: businessName.trim(),
      place_html: html,
      place: suppPayload()
    };
    api.post('/seo/analyze', body).then(function (res) {
      setLoading(false);
      if (res && res.success && res.data) {
        setResult(res.data);
        setChartKeyword(kw);
        loadHistory(res.data.business_key, kw, chartDays);
        loadKeywords(res.data.business_key);
        if (!opts.silent) {
          try {
            window.scrollTo({
              top: 260,
              behavior: 'smooth'
            });
          } catch (e) {}
          fetchAi(res.data);
        }
      } else {
        try {
          toast.error(res && res.detail || '플레이스 분석에 실패했습니다.');
        } catch (e) {}
      }
    }).catch(function () {
      setLoading(false);
    });
  };

  // ==================== 순위 이력·키워드 ====================
  var loadHistory = function (bk, kw, days) {
    if (!bk || !kw) {
      setChartSeries([]);
      return;
    }
    api.get('/place/rank-history?business=' + encodeURIComponent(bk) + '&keyword=' + encodeURIComponent(kw) + '&days=' + (days || 30)).then(function (res) {
      if (res && res.success && res.data) setChartSeries(res.data.series || []);
    }).catch(function () {});
  };
  var loadKeywords = function (bk) {
    if (!bk) return;
    api.get('/place/keywords?business=' + encodeURIComponent(bk)).then(function (res) {
      if (res && res.success && res.data) setKwChips(res.data.keywords || []);
    }).catch(function () {});
  };
  var onChartDays = function (d) {
    setChartDays(d);
    if (result) loadHistory(result.business_key, chartKeyword || selectedKw, d);
  };

  // ==================== AI 진단 ====================
  var fetchAi = function (data) {
    if (!data) return;
    if (aiTimerRef.current) {
      clearTimeout(aiTimerRef.current);
      aiTimerRef.current = null;
    }
    setAiLoading(true);
    setAi(null);
    var sc = data.scores || {};
    var comp = (data.competitors || []).slice(0, 5);
    var sections = {
      rank: {
        keyword: data.keyword,
        region: data.region,
        rank_state: data.rank_state,
        rank: data.rank,
        page: data.page
      },
      review: {
        visitor_review_score: sc.visitor_review,
        blog_review_score: sc.blog_review,
        review_keyword_score: sc.review_keyword
      },
      competition: {
        my_rank: data.rank,
        competitors: comp
      },
      opportunity: {
        scores: sc,
        suggestions: data.suggestions || []
      },
      strategy: {
        total: sc.total,
        scores: sc,
        weights: data.weights
      }
    };
    api.post('/ai/feedback-all', {
      vertical: 'place',
      keyword: data.keyword,
      sections: sections,
      client_name: businessName || '',
      call_type: 'place'
    }).then(function (res) {
      setAiLoading(false);
      if (res && res.success && res.data) setAi(res.data.feedbacks || {});
    }).catch(function () {
      setAiLoading(false);
    });
  };

  // 보완 지표 변경 시 즉시 저장은 안 하고, [재점수화] 버튼으로 반영(불필요한 재호출 방지)
  var rescore = function () {
    runAnalyze({
      reuseHtml: true,
      silent: true
    });
  };
  var resetCapture = function () {
    setPlaceHtml('');
  };

  // ==================== 렌더 헬퍼 ====================
  var htmlKB = placeHtml ? (new Blob([placeHtml]).size / 1024).toFixed(0) : 0;
  var organicHint = function () {
    if (!placeHtml) return '';
    var m = (placeHtml.match(/data-nmb_res-doc-id=/g) || []).length;
    return m ? '오가닉 ' + m + '곳 인식' : '';
  }();
  var bookmarklet = "javascript:(function(){try{var h=document.documentElement.outerHTML;navigator.clipboard.writeText(h).then(function(){alert('\\u2705 \\ud50c\\ub808\\uc774\\uc2a4 HTML '+Math.round(h.length/1024)+'KB \\ubcf5\\uc0ac \\uc644\\ub8cc! \\ub85c\\uc9c1\\ubd84\\uc11d \\uce78\\uc5d0 \\ubd99\\uc5ec\\ub123\\uc73c\\uc138\\uc694.');}).catch(function(){var t=document.createElement('textarea');t.value=h;document.body.appendChild(t);t.select();document.execCommand('copy');document.body.removeChild(t);alert('\\u2705 HTML \\ubcf5\\uc0ac \\uc644\\ub8cc!');});}catch(e){alert('\\u274c \\ubcf5\\uc0ac \\uc2e4\\ud328: '+e.message);}})();";

  // ── 입력 섹션 ──
  var renderInput = function () {
    return React_.createElement('div', {
      className: 'search-section'
    }, React_.createElement('div', {
      className: 'ss-head'
    }, React_.createElement('div', {
      className: 'ic'
    }, '📍'), React_.createElement('div', null, React_.createElement('h3', null, '플레이스 분석 실행'), React_.createElement('div', {
      className: 'sub'
    }, '오프라인·지역 업종 — 상품 HTML 대신 ', React_.createElement('b', null, '플레이스 검색결과'), '를 캡처해 분석합니다'))), React_.createElement('div', {
      className: 'frm'
    },
    // 1행: 업체명 + 키워드
    React_.createElement('div', {
      className: 'grid-in'
    }, React_.createElement('div', {
      className: 'field'
    }, React_.createElement('label', null, '업체명 ', React_.createElement('span', {
      className: 'req'
    }, '*')), React_.createElement('input', {
      className: 'inp' + (businessName ? ' filled' : ''),
      value: businessName,
      onChange: function (e) {
        setBusinessName(e.target.value);
      },
      placeholder: '예: 성수 감성커피'
    })), React_.createElement('div', {
      className: 'field'
    }, React_.createElement('label', null, '추적 키워드 ', React_.createElement('span', {
      className: 'req'
    }, '*'), ' ', React_.createElement('span', {
      style: {
        color: '#94a3b8',
        fontWeight: 400
      }
    }, '(최대 10개 · 칩 클릭=분석 대상 선택)')), React_.createElement('div', {
      className: 'kwbox'
    }, keywords.map(function (kw) {
      return React_.createElement('span', {
        key: kw,
        className: 'kwtag' + (kw === selectedKw ? ' sel' : ''),
        onClick: function () {
          setSelectedKw(kw);
        },
        title: '클릭 = 이 키워드를 분석 대상으로'
      }, kw, React_.createElement('span', {
        className: 'x',
        onClick: function (e) {
          e.stopPropagation();
          removeKeyword(kw);
        }
      }, '×'));
    }), React_.createElement('input', {
      className: 'kwin',
      value: kwInput,
      placeholder: keywords.length ? '키워드 추가…' : '예: 성수동 카페 (Enter)',
      onChange: function (e) {
        setKwInput(e.target.value);
      },
      onKeyDown: function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          addKeyword(kwInput);
        }
      }
    })))),
    // 2행: 지역 + 캡처
    React_.createElement('div', {
      className: 'grid-in'
    }, React_.createElement('div', {
      className: 'field'
    }, React_.createElement('label', null, '지역 ', React_.createElement('span', {
      style: {
        color: '#94a3b8',
        fontWeight: 400
      }
    }, '(동 이름 — 맞춤제안서와 같게)')), React_.createElement('input', {
      className: 'inp' + (region ? ' filled' : ''),
      value: region,
      onChange: function (e) {
        setRegion(e.target.value);
      },
      placeholder: '예: 성수동'
    })), React_.createElement('div', {
      className: 'field'
    }, React_.createElement('label', null, '플레이스 검색결과 캡처 ', React_.createElement('span', {
      className: 'req'
    }, '*'), ' ', React_.createElement('span', {
      style: {
        color: '#94a3b8',
        fontWeight: 400
      }
    }, '(선택한 키워드의 검색결과)')), placeHtml ? React_.createElement('div', {
      className: 'capbox'
    }, React_.createElement('span', {
      className: 'big'
    }, '✓ 검색결과 HTML 붙여넣음'), React_.createElement('span', {
      className: 'kb'
    }, htmlKB + ' KB' + (organicHint ? ' · ' + organicHint : '')), React_.createElement('button', {
      type: 'button',
      className: 're',
      onClick: resetCapture
    }, '↻ 초기화')) : React_.createElement('textarea', {
      className: 'inp',
      style: {
        minHeight: 44
      },
      value: placeHtml,
      onChange: function (e) {
        setPlaceHtml(e.target.value);
      },
      placeholder: '네이버 플레이스 검색결과 페이지 HTML을 붙여넣으세요 (북마클릿 사용)'
    }))),
    // 북마클릿
    React_.createElement('div', {
      className: 'bmk'
    }, React_.createElement('span', {
      style: {
        fontSize: 16
      }
    }, '🔖'), React_.createElement('div', {
      style: {
        flex: 1,
        minWidth: 220
      }
    }, React_.createElement('b', null, '북마클릿(가장 쉬움)'), ' — 오른쪽 파란 버튼을 브라우저 북마크바로 ', React_.createElement('b', null, '드래그'), '해 두면, 네이버 플레이스 ', React_.createElement('b', null, '검색결과 페이지에서 클릭 한 번'), '으로 HTML이 복사됩니다 → 위 칸에 붙여넣기'), React_.createElement('a', {
      className: 'drag',
      href: bookmarklet,
      draggable: 'true',
      onClick: function (e) {
        e.preventDefault();
        try {
          toast.info('클릭하지 말고 브라우저 북마크바로 드래그해서 놓으세요. (북마크바: Ctrl+Shift+B)');
        } catch (er) {}
      }
    }, '📎 플레이스 캡처 (북마크바로 드래그)')),
    // 실행
    React_.createElement('div', {
      className: 'runrow'
    }, React_.createElement('button', {
      className: 'btn btn-primary',
      disabled: loading,
      onClick: function () {
        runAnalyze();
      }
    }, loading ? React_.createElement(React_.Fragment, null, React_.createElement('span', {
      className: 'spin'
    }), ' 분석 중…') : '📍 분석 실행'), React_.createElement('span', {
      className: 'hint'
    }, '담당자 보완 지표(저장수·예약·소식 등)는 결과 화면에서 바로 입력·저장'))));
  };

  // ── 커버 ──
  var renderCover = function () {
    var sc = result.scores || {};
    var total = sc.total || 0;
    var repRank = null,
      repKw = '';
    (kwChips || []).forEach(function (c) {
      if (c.rank != null && (repRank == null || c.rank < repRank)) {
        repRank = c.rank;
        repKw = c.keyword;
      }
    });
    if (repRank == null && result.rank != null) {
      repRank = result.rank;
      repKw = result.keyword;
    }
    var exposedN = (kwChips || []).filter(function (c) {
      return c.state === '노출';
    }).length;
    return React_.createElement('div', {
      className: 'cover'
    }, React_.createElement('div', {
      className: 'ttl'
    }, React_.createElement('h1', null, result.business_name || businessName || '업체'), React_.createElement('span', {
      className: 'rg'
    }, '· ' + (result.region || region || '지역 미지정') + (result.category ? ' · ' + result.category : ''))), React_.createElement('div', {
      className: 'rc-grid'
    }, React_.createElement('div', {
      className: 'rc'
    }, React_.createElement('div', {
      className: 'k'
    }, '추적 키워드'), React_.createElement('div', {
      className: 'v'
    }, (kwChips.length || keywords.length) + '개 ', React_.createElement('small', {
      style: {
        color: '#94a3b8',
        fontWeight: 600
      }
    }, '· 노출 ' + exposedN))), React_.createElement('div', {
      className: 'rc'
    }, React_.createElement('div', {
      className: 'k'
    }, '종합 경쟁력'), React_.createElement('div', {
      className: 'v',
      style: {
        color: scoreCol(total)
      }
    }, total + ' / 100 · ' + gradeOf(total))), React_.createElement('div', {
      className: 'rc'
    }, React_.createElement('div', {
      className: 'k'
    }, '대표키워드 순위'), repRank != null ? React_.createElement('div', {
      className: 'v',
      style: {
        color: '#059669'
      }
    }, repRank + '위 ', React_.createElement('small', {
      style: {
        color: '#94a3b8',
        fontWeight: 600
      }
    }, repKw)) : React_.createElement('div', {
      className: 'v',
      style: {
        color: '#94a3b8'
      }
    }, '미노출')), React_.createElement('div', {
      className: 'rc'
    }, React_.createElement('div', {
      className: 'k'
    }, '분석일 · 데이터'), React_.createElement('div', {
      className: 'v'
    }, (result.analyzed_at || '').slice(0, 10) || '-', React_.createElement('small', {
      style: {
        color: '#94a3b8',
        fontWeight: 600
      }
    }, ' · 캡처+보완')))));
  };

  // ── §1 종합 경쟁력 ──
  var renderSec1 = function () {
    var sc = result.scores || {};
    var labels = result.labels || {};
    var weights = result.weights || {};
    var total = sc.total || 0;
    var col = scoreCol(total);
    // 강·약점 도출
    var arr = METRIC_ORDER.map(function (k) {
      return {
        k: k,
        label: labels[k] || k,
        s: sc[k] || 0
      };
    });
    var strong = arr.filter(function (x) {
      return x.s >= 68;
    }).sort(function (a, b) {
      return b.s - a.s;
    }).slice(0, 3).map(function (x) {
      return x.label;
    });
    var weak = arr.filter(function (x) {
      return x.s < 50;
    }).sort(function (a, b) {
      return a.s - b.s;
    }).slice(0, 3).map(function (x) {
      return x.label;
    });
    return React_.createElement(React_.Fragment, null, React_.createElement('div', {
      className: 'divider'
    }, React_.createElement('div', {
      className: 'tile',
      style: {
        background: 'linear-gradient(135deg,#3b82f6,#3b82f6cc)',
        boxShadow: '0 4px 12px #3b82f640'
      }
    }, '1'), React_.createElement('div', null, React_.createElement('h2', null, '종합 경쟁력'), React_.createElement('div', {
      className: 's'
    }, '플레이스 로컬 10지표 가중 점수 · 강·약점'))), React_.createElement('div', {
      className: 'card'
    }, React_.createElement('h3', {
      className: 'rt-h3'
    }, React_.createElement('span', {
      className: 'rt-hic'
    }, '🎯'), '플레이스 종합 경쟁력 ', React_.createElement('span', {
      className: 'badge b-est'
    }, '≈ 가중')), React_.createElement('div', {
      className: 'rt-desc'
    }, '10개 지표를 0~100점으로 채점하고 가중치(합 1.00)로 종합 점수를 산출합니다. 스토어 분석과 동일한 엔진 구조 — 지표·프리셋만 플레이스로 교체.'), React_.createElement('div', {
      className: 'scorewrap'
    }, React_.createElement('div', {
      className: 'ring',
      style: {
        background: 'conic-gradient(' + col + ' ' + total * 3.6 + 'deg, var(--pa-track) 0)'
      }
    }, React_.createElement('div', {
      className: 'inr'
    }, React_.createElement('div', {
      className: 'n'
    }, total, React_.createElement('small', null, '/100')), React_.createElement('div', {
      className: 'g',
      style: {
        color: col
      }
    }, '등급 ' + gradeOf(total)))), React_.createElement('div', {
      className: 'str'
    }, React_.createElement('div', {
      className: 'row good'
    }, React_.createElement('span', {
      className: 'ic'
    }, '↑'), React_.createElement('div', null, React_.createElement('b', null, '강점'), ' — ', strong.length ? strong.join(' · ') : '지표 보강 필요')), React_.createElement('div', {
      className: 'row bad'
    }, React_.createElement('span', {
      className: 'ic'
    }, '↓'), React_.createElement('div', null, React_.createElement('b', null, '개선 우선'), ' — ', weak.length ? weak.join(' · ') + ' 가 상위권 대비 부족(주황 막대)' : '전반적으로 양호')), React_.createElement('div', {
      className: 'row mid'
    }, React_.createElement('span', {
      className: 'ic'
    }, '→'), React_.createElement('div', null, React_.createElement('b', null, '기회'), ' — 저장·블로그 등 인기도 지표를 보강하면 대표키워드 방어 + 중위 키워드 상승 여지가 큽니다.')))),
    // 10 지표 막대
    React_.createElement('div', {
      className: 'metrics'
    }, METRIC_ORDER.map(function (k) {
      var v = sc[k] || 0;
      var low = v < 50;
      return React_.createElement('div', {
        key: k,
        className: 'scorebar' + (low ? ' low' : '')
      }, React_.createElement('div', {
        className: 'lbl'
      }, React_.createElement('span', {
        className: 'nm'
      }, labels[k] || k, React_.createElement('span', {
        className: 'w'
      }, weights[k] != null ? weights[k].toFixed(2) : ''), React_.createElement('span', {
        className: 'mk ' + (MEASURED[k] ? 'meas' : 'inp')
      }, MEASURED[k] ? '측정' : '보완')), React_.createElement('span', {
        className: 'sc'
      }, v)), React_.createElement('div', {
        className: 'track'
      }, React_.createElement('i', {
        style: {
          width: v + '%'
        }
      })));
    })),
    // 보완 지표 편집
    renderSuppEditor(), React_.createElement('div', {
      className: 'note',
      style: {
        marginTop: 14
      }
    }, React_.createElement('b', null, '측정 vs 보완:'), ' 순위·리뷰·적합도·사진은 캡처에서 ', React_.createElement('b', null, '자동 측정'), ', 저장수·예약·소식·업체정보는 담당자가 ', React_.createElement('b', null, '보완 입력'), '(하이브리드). 보완 지표를 채우고 ', React_.createElement('b', null, '재점수화'), '하면 점수에 반영됩니다.')));
  };
  var chkBtn = function (key, label) {
    return React_.createElement('button', {
      type: 'button',
      className: 'chkb' + (supp[key] ? ' on' : ''),
      onClick: function () {
        var n = Object.assign({}, supp);
        n[key] = !n[key];
        setSupp(n);
      }
    }, (supp[key] ? '✓ ' : '') + label);
  };
  var suppNum = function (key, label, ph) {
    return React_.createElement('div', {
      className: 'suppf'
    }, React_.createElement('label', null, label), React_.createElement('input', {
      className: 'si',
      type: 'number',
      min: 0,
      value: supp[key],
      placeholder: ph || '',
      onChange: function (e) {
        var n = Object.assign({}, supp);
        n[key] = e.target.value;
        setSupp(n);
      }
    }));
  };
  var renderSuppEditor = function () {
    return React_.createElement('div', {
      className: 'suppcard'
    }, React_.createElement('h4', null, '✍️ 담당자 보완 지표'), React_.createElement('div', {
      className: 'sd'
    }, '캡처로 측정되지 않는 지표를 입력하세요. 방문자·블로그 리뷰는 캡처에서 자동 인식되며, 값을 직접 넣으면 그 값이 우선됩니다.'), React_.createElement('div', {
      className: 'suppgrid'
    }, suppNum('saves', '저장수(즐겨찾기)', '예: 1020'), suppNum('photos', '사진 수', '예: 96'), suppNum('news_days', '소식 최근 게시(일 전)', '예: 18'), suppNum('info_complete', '업체정보 완성도(0~100)', '예: 80')), React_.createElement('div', {
      className: 'chk',
      style: {
        marginTop: 12
      }
    }, chkBtn('has_booking', '예약'), chkBtn('has_talk', '톡톡'), chkBtn('has_order', '주문'), chkBtn('rep_keyword', '대표키워드 등록')), React_.createElement('div', {
      className: 'supprow'
    }, React_.createElement('button', {
      className: 'btn btn-primary btn-sm',
      disabled: loading,
      onClick: rescore
    }, loading ? React_.createElement(React_.Fragment, null, React_.createElement('span', {
      className: 'spin'
    }), ' 반영 중…') : '↻ 보완 지표 반영(재점수화)'), React_.createElement('span', {
      className: 'hint',
      style: {
        fontSize: 11.5,
        color: '#94a3b8'
      }
    }, '입력값은 다음 분석에도 유지됩니다.')));
  };

  // ── §2 키워드 노출 순위 ──
  var chipClass = function (c) {
    if (c.state === '미확인' || c.state !== '노출' && c.rank == null && c.state !== '미노출') return 'unk';
    if (c.state === '미노출' || c.rank == null) return 'off';
    if (c.rank <= 10) return '';
    if (c.rank <= 30) return 'warn';
    return 'off';
  };
  var renderSec2 = function () {
    // 입력 키워드 + 서버 추적 키워드 병합
    var map = {};
    (kwChips || []).forEach(function (c) {
      map[c.keyword] = c;
    });
    var union = [];
    keywords.forEach(function (k) {
      if (union.indexOf(k) === -1) union.push(k);
    });
    (kwChips || []).forEach(function (c) {
      if (union.indexOf(c.keyword) === -1) union.push(c.keyword);
    });
    var chips = union.map(function (k) {
      return map[k] || {
        keyword: k,
        rank: null,
        state: '미확인'
      };
    });
    var exposed = chips.filter(function (c) {
      return c.state === '노출';
    });
    var notExp = chips.filter(function (c) {
      return c.state === '미노출';
    });
    var unk = chips.filter(function (c) {
      return c.state === '미확인';
    });
    var rate = chips.length ? Math.round(exposed.length / chips.length * 100) : 0;
    return React_.createElement(React_.Fragment, null, React_.createElement('div', {
      className: 'divider'
    }, React_.createElement('div', {
      className: 'tile',
      style: {
        background: 'linear-gradient(135deg,#059669,#059669cc)',
        boxShadow: '0 4px 12px #05966940'
      }
    }, '2'), React_.createElement('div', null, React_.createElement('h2', null, '키워드 노출 순위'), React_.createElement('div', {
      className: 's'
    }, '지역+키워드 기준 노출/미노출/미확인 · 일자별 추적'))), React_.createElement('div', {
      className: 'card'
    }, React_.createElement('h3', {
      className: 'rt-h3'
    }, React_.createElement('span', {
      className: 'rt-hic'
    }, '📍'), '키워드별 노출 순위 ', React_.createElement('span', {
      className: 'badge b-ok'
    }, '✅ 실측')), React_.createElement('div', {
      className: 'rt-desc'
    }, '캡처한 검색결과에서 내 업체의 오가닉 순위를 키워드별로 찾습니다. ', React_.createElement('b', null, '미확인'), ' = 아직 캡처·분석하지 않은 키워드(실제 미노출과 구분).'), React_.createElement('div', {
      className: 'pills'
    }, React_.createElement('span', {
      className: 'ps ps-g'
    }, '노출 ' + exposed.length + '개'), React_.createElement('span', {
      className: 'ps ps-r'
    }, '미노출 ' + notExp.length + '개'), React_.createElement('span', {
      className: 'ps ps-n'
    }, '미확인 ' + unk.length + '개')), React_.createElement('div', {
      className: 'grid3'
    }, React_.createElement('div', {
      className: 'ratecard g'
    }, React_.createElement('div', {
      className: 'v'
    }, exposed.length), React_.createElement('div', {
      className: 'k'
    }, '노출 키워드')), React_.createElement('div', {
      className: 'ratecard r'
    }, React_.createElement('div', {
      className: 'v'
    }, notExp.length), React_.createElement('div', {
      className: 'k'
    }, '미노출')), React_.createElement('div', {
      className: 'ratecard p'
    }, React_.createElement('div', {
      className: 'v'
    }, rate + '%'), React_.createElement('div', {
      className: 'k'
    }, '노출률'))), React_.createElement('div', {
      className: 'kwgrid'
    }, chips.map(function (c) {
      var cls = chipClass(c);
      var rk = c.state === '미확인' ? '?' : c.rank != null ? c.rank + '위' : '밖';
      return React_.createElement('span', {
        key: c.keyword,
        className: 'kwchip ' + cls + (c.keyword === chartKeyword ? ' cur' : ''),
        onClick: function () {
          setChartKeyword(c.keyword);
          loadHistory(result.business_key, c.keyword, chartDays);
        },
        title: '클릭 = 이 키워드 순위 추이 보기',
        style: {
          cursor: 'pointer'
        }
      }, React_.createElement('span', {
        className: 'rk'
      }, rk), c.keyword + (c.state === '미확인' ? ' · 미확인' : ''));
    })), React_.createElement(window.PlaceRankChart, {
      series: chartSeries,
      keyword: chartKeyword || selectedKw,
      days: chartDays,
      businessName: businessName,
      onDays: onChartDays
    })));
  };

  // ── 업체 저장 카드 (스토어와 동일 규칙: viewer=영업 대상 30일 유예 / 관리팀=광고주 영구) ──
  var saveToClient = function (role) {
    if (saveBusy) return;
    var name = (businessName || '').trim();
    var kw = (selectedKw || keywords[0] || '').trim();
    if (!name) {
      try {
        toast.warn('업체명이 없습니다.');
      } catch (e) {}
      return;
    }
    if (!kw) {
      try {
        toast.warn('키워드가 없습니다.');
      } catch (e) {}
      return;
    }
    // 매칭된 플레이스 doc-id → 지도 링크.
    // ⚠️ 종전엔 `result.rank_info.matched` 를 읽었는데 **응답에 rank_info 키 자체가 없어**
    //    지도 링크가 늘 빈 값이었다(저장한 영업 대상을 다시 열면 빈 패널). 2026-08-05 수정.
    //    서버가 내려주는 place_id 를 쓰고, 없으면 business_key 의 `doc:` 접두에서 뽑는다.
    var pid = '';
    try {
      pid = String(result && result.place_id || '');
      if (!pid) {
        var bk = String(result && result.business_key || '');
        if (bk.indexOf('doc:') === 0) pid = bk.slice(4);
      }
    } catch (e) {}
    setSaveBusy(true);
    setSaveMsg(null);
    api.post('/cd/quick-register', {
      name: name,
      keyword: kw,
      product_url: pid ? 'https://map.naver.com/p/entry/place/' + pid : '',
      vertical: 'place',
      role: role
    }).then(function (res) {
      setSaveBusy(false);
      if (res && res.success) setSaveMsg({
        ok: true,
        text: res.message || '저장되었습니다.'
      });else setSaveMsg({
        ok: false,
        text: res && (typeof res.detail === 'string' ? res.detail : res.error) || '저장에 실패했습니다.'
      });
    }).catch(function () {
      setSaveBusy(false);
      setSaveMsg({
        ok: false,
        text: '저장 중 오류가 발생했습니다.'
      });
    });
  };
  var renderSaveCard = function () {
    var isViewer = currentUser.role === 'viewer';
    var canAdv = currentUser.role === 'manager' || currentUser.role === 'superadmin';
    return React_.createElement('div', {
      className: 'card',
      style: {
        marginTop: 14
      }
    }, React_.createElement('h3', {
      className: 'rt-h3'
    }, React_.createElement('span', {
      className: 'rt-hic'
    }, '💾'), '업체 저장 ', React_.createElement('span', {
      className: 'badge b-ok'
    }, '스토어와 동일 규칙')), React_.createElement('div', {
      className: 'rt-desc'
    }, isViewer ? '이 업체를 내 영업 대상으로 저장합니다 — 본인만 열람 · 30일 후 자동 삭제(재저장 시 연장). 스토어 분석과 동일합니다.' : '이 업체를 광고주로 등록(영구)하거나 영업 대상으로 저장합니다 — 광고주 대시보드 목록·권한이 스토어와 동일한 파이프라인입니다.'), React_.createElement('div', {
      style: {
        display: 'flex',
        gap: 8,
        flexWrap: 'wrap',
        alignItems: 'center'
      }
    }, canAdv && React_.createElement('button', {
      className: 'btn btn-primary',
      disabled: saveBusy,
      onClick: function () {
        saveToClient('advertiser');
      }
    }, saveBusy ? '저장 중…' : '⭐ 광고주로 등록 (영구)'), React_.createElement('button', {
      className: canAdv ? 'btn btn-secondary' : 'btn btn-primary',
      disabled: saveBusy,
      onClick: function () {
        saveToClient('prospect');
      }
    }, saveBusy ? '저장 중…' : '🎯 영업 대상으로 저장' + (isViewer ? ' (30일)' : ''))), saveMsg && React_.createElement('div', {
      className: 'note ' + (saveMsg.ok ? 'ok' : 'est'),
      style: {
        marginTop: 10
      }
    }, (saveMsg.ok ? '✅ ' : '⚠️ ') + saveMsg.text));
  };

  // ── §3 경쟁 비교 ──
  var renderSec3 = function () {
    var comps = (result.competitors || []).slice(0, 5);
    // 내 업체 행(순위만 확정 — 방문자/블로그 리뷰는 응답에 미포함이라 표시 생략)
    var myRow = {
      name: result.business_name || businessName || '내 업체',
      rank: result.rank,
      visitor_reviews: null,
      blog_reviews: null,
      me: true
    };
    var rows = comps.map(function (c) {
      return {
        name: c.name,
        rank: c.rank,
        visitor_reviews: c.visitor_reviews,
        blog_reviews: c.blog_reviews,
        me: false
      };
    });
    rows.push(myRow);
    rows.sort(function (a, b) {
      return (a.rank || 999) - (b.rank || 999);
    });
    var maxV = Math.max.apply(null, rows.map(function (r) {
      return r.visitor_reviews || 0;
    }).concat([1]));
    var rkClass = function (r) {
      return r == null ? '' : r <= 5 ? 'rk-hi' : r <= 15 ? 'rk-mid' : 'rk-lo';
    };
    return React_.createElement(React_.Fragment, null, React_.createElement('div', {
      className: 'divider'
    }, React_.createElement('div', {
      className: 'tile',
      style: {
        background: 'linear-gradient(135deg,#ef4444,#ef4444cc)',
        boxShadow: '0 4px 12px #ef444440'
      }
    }, '3'), React_.createElement('div', null, React_.createElement('h2', null, '경쟁 비교'), React_.createElement('div', {
      className: 's'
    }, "'" + (result.keyword || '') + "' 상위 노출 업체 대비 지표"))), React_.createElement('div', {
      className: 'card'
    }, React_.createElement('h3', {
      className: 'rt-h3'
    }, React_.createElement('span', {
      className: 'rt-hic'
    }, '⚔️'), '상위 노출 경쟁사 비교 ', React_.createElement('span', {
      className: 'badge b-ok'
    }, '✅ 실측')), React_.createElement('div', {
      className: 'rt-desc'
    }, '캡처 검색결과의 상위 오가닉 업체를 내 업체와 정면 비교합니다. 방문자·블로그 리뷰는 캡처에서 인식된 값입니다.'), comps.length === 0 ? React_.createElement('div', {
      className: 'empty'
    }, '캡처에서 경쟁사 지표를 인식하지 못했습니다. 검색결과 HTML을 다시 캡처해 보세요.') : React_.createElement('div', {
      className: 'twrap'
    }, React_.createElement('table', null, React_.createElement('thead', null, React_.createElement('tr', null, React_.createElement('th', null, '순위'), React_.createElement('th', null, '업체'), React_.createElement('th', {
      className: 'n'
    }, '방문자 리뷰'), React_.createElement('th', {
      className: 'n'
    }, '블로그 리뷰'), React_.createElement('th', {
      style: {
        width: 160
      }
    }, '방문자 리뷰 격차'))), React_.createElement('tbody', null, rows.map(function (r, i) {
      var pct = maxV ? Math.round((r.visitor_reviews || 0) / maxV * 100) : 0;
      return React_.createElement('tr', {
        key: i,
        className: r.me ? 'me' : ''
      }, React_.createElement('td', {
        className: 'rkcell ' + rkClass(r.rank)
      }, r.rank != null ? r.rank + '위' : '미노출'), React_.createElement('td', null, r.name || '-', r.me ? React_.createElement('span', {
        className: 'metag'
      }, '내 업체') : null), React_.createElement('td', {
        className: 'n'
      }, fmtN(r.visitor_reviews)), React_.createElement('td', {
        className: 'n'
      }, fmtN(r.blog_reviews)), React_.createElement('td', null, React_.createElement('div', {
        className: 'gap'
      }, React_.createElement('div', {
        className: 'gapbar'
      }, React_.createElement('i', {
        className: 'me-f',
        style: {
          width: pct + '%'
        }
      })))));
    })))), React_.createElement('div', {
      className: 'note est',
      style: {
        marginTop: 13
      }
    }, React_.createElement('b', null, '격차 진단 ≈ 추정:'), ' 방문자·블로그 리뷰가 상위권과 벌어질수록 인기도(순위) 병목이 큽니다. 저장수는 캡처로 인식되지 않으므로 §1 보완 지표에서 입력해 경쟁력에 반영하세요.')));
  };

  // ── §4 AI 진단 ──
  var PLACE_AI_SECTIONS = [{
    key: 'summary',
    label: '종합 진단',
    icon: '🧭'
  }, {
    key: 'rank',
    label: '노출 순위',
    icon: '📍'
  }, {
    key: 'review',
    label: '리뷰 진단',
    icon: '💬'
  }, {
    key: 'competition',
    label: '경쟁 비교',
    icon: '⚔️'
  }, {
    key: 'opportunity',
    label: '기회 발굴',
    icon: '🌱'
  }, {
    key: 'strategy',
    label: '전략·결론',
    icon: '🚀'
  }];
  var renderSec4 = function () {
    var suggestions = result.suggestions || [];
    return React_.createElement(React_.Fragment, null, React_.createElement('div', {
      className: 'divider'
    }, React_.createElement('div', {
      className: 'tile',
      style: {
        background: 'linear-gradient(135deg,#7c3aed,#7c3aedcc)',
        boxShadow: '0 4px 12px #7c3aed40'
      }
    }, '4'), React_.createElement('div', null, React_.createElement('h2', null, 'AI 진단·처방'), React_.createElement('div', {
      className: 's'
    }, '무엇을·왜·얼마나 하면 몇 위가 되는가'))), React_.createElement('div', {
      className: 'card'
    }, React_.createElement('h3', {
      className: 'rt-h3'
    }, React_.createElement('span', {
      className: 'rt-hic'
    }, '🤖'), 'AI 종합 진단 ', React_.createElement('span', {
      className: 'badge b-ai'
    }, 'AI'), React_.createElement('button', {
      className: 'btn btn-secondary btn-sm',
      style: {
        marginLeft: 'auto'
      },
      disabled: aiLoading,
      onClick: function () {
        fetchAi(result);
      }
    }, aiLoading ? '분석 중…' : '↻ 다시 분석')), React_.createElement('div', {
      className: 'rt-desc'
    }, '플레이스 상위노출 로직(적합도·인기도·거리)에 근거한 진단입니다. 근거가 약한 예측은 ‘추정’으로 표기합니다.'),
    // 규칙 기반 처방(즉시)
    React_.createElement('div', {
      style: {
        margin: '6px 0 4px',
        fontSize: 13,
        fontWeight: 800,
        color: '#0f172a'
      }
    }, '개선 처방 (우선순위)'), React_.createElement('div', null, suggestions.map(function (s, i) {
      return React_.createElement('div', {
        key: i,
        className: 'rx'
      }, React_.createElement('span', {
        className: 'no'
      }, i + 1), React_.createElement('div', {
        className: 'tx'
      }, s));
    })),
    // AI 서술
    aiLoading ? React_.createElement('div', {
      className: 'empty'
    }, React_.createElement('span', {
      className: 'spin'
    }), ' AI 종합 진단 생성 중… (10~20초)') : ai ? React_.createElement('div', {
      style: {
        marginTop: 10
      }
    }, PLACE_AI_SECTIONS.filter(function (s) {
      return ai[s.key];
    }).map(function (s) {
      return React_.createElement('div', {
        key: s.key,
        className: 'aiblock'
      }, React_.createElement('h5', null, s.icon + ' ' + s.label), ai[s.key]);
    })) : React_.createElement('div', {
      className: 'note',
      style: {
        marginTop: 10
      }
    }, 'AI 종합 진단은 분석 실행 후 자동 생성됩니다. 「↻ 다시 분석」으로 재생성할 수 있습니다.'), React_.createElement('div', {
      className: 'note',
      style: {
        marginTop: 13
      }
    }, React_.createElement('b', null, '관리 목표(보장 아님):'), ' 순위는 경쟁·거리·알고리즘에 따라 변동하므로 관리기준으로 표기합니다. 저장·블로그·소식 등 인기도 지표를 꾸준히 보강하는 것이 상위 방어의 핵심입니다.')));
  };

  // ==================== 최종 렌더 ====================
  return React_.createElement('div', {
    className: 'place-analysis'
  }, React_.createElement('div', {
    className: 'pa-wrap'
  }, renderInput(), result && renderCover(), result && renderSec1(), result && renderSec2(), result && renderSec3(), result && renderSec4(), result && renderSaveCard(), !result && React_.createElement('div', {
    className: 'card',
    style: {
      textAlign: 'center',
      color: '#94a3b8',
      padding: '34px 20px'
    }
  }, React_.createElement('div', {
    style: {
      fontSize: 30,
      marginBottom: 8
    }
  }, '📍'), React_.createElement('div', {
    style: {
      fontSize: 14,
      fontWeight: 700,
      color: '#64748b'
    }
  }, '업체명·키워드·플레이스 검색결과 캡처를 입력하고 「분석 실행」을 눌러주세요.'), React_.createElement('div', {
    style: {
      fontSize: 12,
      marginTop: 6
    }
  }, '오프라인·지역 업종(카페·식당·병원·미용 등)의 플레이스 상위노출 경쟁력을 진단합니다.'))));
};

;/* ===== js/components/PlaceTrackingPage.jsx ===== */
/* PlaceTrackingPage — 로직분석 「플레이스 추적」 전용 탭 (무인 순위 추적, v1)
 *
 * 확정 시안(2026-08-04 v2, Artifact 790e1710) 기준:
 *  - 추적 대상 등록: 업체명·지역·키워드(최대 10, 지역 자동 합성 — 맞춤제안서와 동일 규칙)
 *  - 추적 현황: 노출/미노출/미확인 필, (업체×키워드) 표, 행 클릭 → 순위 추이(PlaceRankChart 재사용)
 *  - 수집은 「플레이스 순위 추적기」 확장(별개 설치)이 매일 06:30 무인 수행 → /api/place/ingest 기록
 *  - 이 화면은 확장에 추적 목록을 동기화(METAINC_PLACE_TARGETS)하고 즉시 수집(METAINC_PLACE_RUN)을 요청
 *
 * 스파이크 실측(2026-08-04): 키워드에 지역이 포함되면 오가닉 순위는 검색 위치와 무관하게 재현
 *  → 등록 시 지역 합성이 재현성의 핵심(좌표 고정 불필요).
 * 스타일: css/place.css(.place-analysis 스코프) 재사용. */
window.PlaceTrackingPage = function PlaceTrackingPage(props) {
  var useState = React.useState,
    useEffect = React.useEffect,
    useRef = React.useRef;

  // 사용 범주 = 스토어 순위 추적과 동일(2026-08-04 대표 확정):
  // 영업사원(viewer)은 열람만(등록·삭제·일시중지·지금 수집 불가), 관리팀·관리자는 전체 가능. 서버 게이트와 이중.
  var currentUser = props.currentUser;
  var isViewer = !!(currentUser && currentUser.role === 'viewer');

  // ── 목록 상태 ──
  var _t = useState([]);
  var targets = _t[0],
    setTargets = _t[1];
  var _ld = useState(false);
  var loading = _ld[0],
    setLoading = _ld[1];

  // ── 등록 폼 ──
  var _n = useState('');
  var bizName = _n[0],
    setBizName = _n[1];
  var _r = useState('');
  var region = _r[0],
    setRegion = _r[1];
  var _ki = useState('');
  var kwInput = _ki[0],
    setKwInput = _ki[1];
  var _ks = useState([]);
  var kws = _ks[0],
    setKws = _ks[1];
  var _sv = useState(false);
  var saving = _sv[0],
    setSaving = _sv[1];

  // ── 확장 연동 상태 ──
  var _ex = useState(false);
  var extReady = _ex[0],
    setExtReady = _ex[1];

  // ── 행 펼침 차트 ──
  var _open = useState('');
  var openKey = _open[0],
    setOpenKey = _open[1]; // 'bk||keyword'
  var _cs = useState([]);
  var chartSeries = _cs[0],
    setChartSeries = _cs[1];
  var _cd = useState(30);
  var chartDays = _cd[0],
    setChartDays = _cd[1];
  var _pid = useState('');
  var placeIdInput = _pid[0],
    setPlaceIdInput = _pid[1];

  // 플레이스 링크/ID → 숫자 ID 추출 (지도 주소 어느 형식이든: .../place/12345, m.place.naver.com/restaurant/12345/..., 숫자 단독)
  function extractPlaceId(v) {
    v = String(v || '').trim();
    if (!v) return '';
    if (/^\d{5,}$/.test(v)) return v;
    var m = v.match(/(?:place|restaurant|cafe|hairshop|hospital|accommodation|attraction)\/(\d{5,})/);
    if (m) return m[1];
    m = v.match(/(\d{7,})/);
    return m ? m[1] : '';
  }

  // ==================== 확장 브리지 ====================
  // 러너 동기화는 항상 서버 전체 활성 목록(?active=1 — 러너 전용 격리 예외)으로 push:
  // 화면 목록은 본인 것만(개인화)이지만, 무인 수집은 전 직원 등록분을 커버해야 하기 때문.
  function pushTargetsToExt() {
    api.get('/place/track-targets?active=1').then(function (res) {
      if (!(res && res.success)) return;
      var actives = (res.data && res.data.targets || []).map(function (t) {
        return {
          id: t.id,
          business_name: t.business_name,
          region: t.region,
          place_id: t.place_id || '',
          keyword: t.keyword
        };
      });
      window.postMessage({
        type: 'METAINC_PLACE_TARGETS',
        payload: {
          targets: actives
        }
      }, window.location.origin);
    }).catch(function () {});
  }
  useEffect(function () {
    var onMsg = function (ev) {
      if (ev.source !== window || !ev.data) return;
      if (ev.data.type === 'METAINC_PLACE_EXT_READY') {
        setExtReady(true);
        pushTargetsToExt(); // 연동 확인 즉시 목록 동기화
      }
    };
    window.addEventListener('message', onMsg);
    try {
      window.postMessage({
        type: 'METAINC_PLACE_PING'
      }, window.location.origin);
    } catch (e) {}
    return function () {
      window.removeEventListener('message', onMsg);
    };
  }, []);
  function requestRunNow() {
    try {
      window.postMessage({
        type: 'METAINC_PLACE_RUN'
      }, window.location.origin);
    } catch (e) {}
    if (extReady) toast.success('⟳ 이 컴퓨터의 추적기에 수집을 요청했습니다 — 키워드당 30~50초, 완료되면 자동 기록됩니다.');else toast.warn('이 브라우저에 「플레이스 순위 추적기」 확장이 없습니다 — 추적 PC(맥북)에서는 매일 06:30 자동 수집됩니다.');
  }

  // ==================== 데이터 ====================
  function load() {
    setLoading(true);
    api.get('/place/track-targets').then(function (res) {
      setLoading(false);
      if (res && res.success) {
        var list = res.data && res.data.targets || [];
        setTargets(list);
        pushTargetsToExt();
      }
    }).catch(function () {
      setLoading(false);
    });
  }
  useEffect(function () {
    load();
  }, []);

  // ==================== 등록 폼 ====================
  function combinedPreview(kw) {
    var reg = (region || '').trim();
    if (!reg) return kw;
    var norm = function (s) {
      return String(s).toLowerCase().replace(/\s+/g, '');
    };
    return norm(kw).indexOf(norm(reg)) >= 0 ? kw : reg + ' ' + kw;
  }
  function addKw() {
    var v = (kwInput || '').trim().replace(/,$/, '');
    if (!v) return;
    if (kws.length >= 10) {
      toast.warn('키워드는 업체당 최대 10개입니다.');
      return;
    }
    if (kws.indexOf(v) >= 0) {
      setKwInput('');
      return;
    }
    setKws(kws.concat([v]));
    setKwInput('');
  }
  function onKwKey(e) {
    if (e.nativeEvent && e.nativeEvent.isComposing) return; // 한글 IME 중복 방지
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addKw();
    }
  }
  function submit() {
    if (saving) return;
    var name = (bizName || '').trim(),
      reg = (region || '').trim();
    var pending = (kwInput || '').trim();
    var list = pending && kws.indexOf(pending) < 0 && kws.length < 10 ? kws.concat([pending]) : kws;
    if (!name) {
      toast.warn('업체명을 입력해주세요.');
      return;
    }
    if (!reg) {
      toast.warn('지역을 입력해주세요. (예: 성수동 — 순위 재현에 필요)');
      return;
    }
    if (!list.length) {
      toast.warn('추적 키워드를 1개 이상 입력해주세요.');
      return;
    }
    var pid = '';
    if ((placeIdInput || '').trim()) {
      pid = extractPlaceId(placeIdInput);
      if (!pid) {
        toast.warn('플레이스 링크/ID를 인식하지 못했습니다 — 네이버 지도 업체 페이지 주소나 숫자 ID를 붙여넣어주세요. (비워두면 업체명으로 찾습니다)');
        return;
      }
    }
    setSaving(true);
    api.post('/place/track-targets', {
      business_name: name,
      region: reg,
      keywords: list,
      place_id: pid
    }).then(function (res) {
      setSaving(false);
      if (res && res.success) {
        toast.success('✅ 추적 등록: ' + name + ' · 키워드 ' + (res.data && res.data.added || 0) + '개 — 다음 자동 수집부터 기록됩니다.');
        setBizName('');
        setRegion('');
        setKws([]);
        setKwInput('');
        setPlaceIdInput('');
        load();
      } else {
        toast.error(res && res.error || '등록에 실패했습니다.');
      }
    }).catch(function () {
      setSaving(false);
    });
  }

  // ==================== 행 액션 ====================
  function toggleActive(t) {
    api.patch('/place/track-targets/' + t.id, {
      active: !t.active
    }).then(function (res) {
      if (res && res.success) load();
    });
  }
  function removeTarget(t) {
    if (!window.confirm('「' + t.business_name + ' · ' + t.keyword + '」 추적을 삭제할까요?\n(그동안 쌓인 순위 이력은 보존됩니다 — 재등록하면 이어집니다)')) return;
    api.del('/place/track-targets/' + t.id).then(function (res) {
      if (res && res.success) {
        toast.success('삭제했습니다.');
        load();
      }
    });
  }
  function toggleChart(t) {
    var key = (t.business_key || '') + '||' + t.keyword;
    if (openKey === key) {
      setOpenKey('');
      return;
    }
    setOpenKey(key);
    loadSeries(t, chartDays);
  }
  function loadSeries(t, days) {
    if (!t.business_key) {
      setChartSeries([]);
      return;
    }
    api.get('/place/rank-history?business=' + encodeURIComponent(t.business_key) + '&keyword=' + encodeURIComponent(t.keyword) + '&days=' + days).then(function (res) {
      if (res && res.success) setChartSeries(res.data && res.data.series || []);
    });
  }

  // ==================== 렌더 ====================
  var pills = {
    exposed: 0,
    missing: 0,
    unknown: 0,
    none: 0
  };
  targets.forEach(function (t) {
    if (!t.last) pills.none++;else if (t.last.state === '노출') pills.exposed++;else if (t.last.state === '미노출') pills.missing++;else pills.unknown++;
  });

  // 업체별 그룹(카드형) — 스토어 분석과 같은 개념: 업체 카드 안에 그 업체의 키워드·순위가 모임
  var bizGroups = [];
  var bizIdx = {};
  targets.forEach(function (t) {
    var gk = (t.business_name || '') + '|' + (t.region || '');
    if (bizIdx[gk] === undefined) {
      bizIdx[gk] = bizGroups.length;
      bizGroups.push({
        name: t.business_name,
        region: t.region,
        place_id: t.place_id || '',
        items: []
      });
    }
    var g = bizGroups[bizIdx[gk]];
    if (!g.place_id && t.place_id) g.place_id = t.place_id;
    g.items.push(t);
  });
  function bizSummary(g) {
    var s = {
      exposed: 0,
      missing: 0,
      wait: 0,
      best: null
    };
    g.items.forEach(function (t) {
      if (!t.last) s.wait++;else if (t.last.state === '노출') {
        s.exposed++;
        if (t.last.rank != null && (s.best === null || t.last.rank < s.best)) s.best = t.last.rank;
      } else if (t.last.state === '미노출') s.missing++;else s.wait++;
    });
    return s;
  }
  function rankCell(t) {
    if (!t.last || t.last.rank == null) {
      return React.createElement('span', {
        style: {
          color: '#94a3b8',
          fontWeight: 800
        }
      }, t.last && t.last.state === '미노출' ? '–' : '?');
    }
    var r = t.last.rank;
    var col = r <= 10 ? '#059669' : r <= 30 ? '#d97706' : '#dc2626';
    return React.createElement('span', null, React.createElement('span', {
      style: {
        fontFamily: 'SF Mono,JetBrains Mono,monospace',
        fontWeight: 800,
        fontSize: 15,
        color: col
      }
    }, r), React.createElement('span', {
      style: {
        color: '#94a3b8',
        fontSize: 11
      }
    }, '위'));
  }
  function stateChip(t) {
    var st = t.last ? t.last.state : null;
    var cls = st === '노출' ? 'kwchip' : st === '미노출' ? 'kwchip off' : 'kwchip unk';
    var label = st || '이력 없음';
    return React.createElement('span', {
      className: cls,
      style: {
        cursor: 'default'
      }
    }, label);
  }
  function fmtDate(s) {
    if (!s) return '-';
    return String(s).slice(5, 10).replace('-', '.');
  }
  var bizCards = bizGroups.map(function (g, gi) {
    var s = bizSummary(g);
    var rowEls = [];
    g.items.forEach(function (t) {
      var key = (t.business_key || '') + '||' + t.keyword;
      rowEls.push(React.createElement('div', {
        key: 'r' + t.id,
        onClick: function () {
          toggleChart(t);
        },
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 2px',
          borderTop: '1px solid #f1f5f9',
          cursor: 'pointer',
          opacity: t.active ? 1 : 0.45
        }
      }, React.createElement('span', {
        title: t.keyword,
        style: {
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontFamily: 'SF Mono,JetBrains Mono,monospace',
          fontSize: 12.5,
          color: '#334155'
        }
      }, t.keyword), React.createElement('span', {
        style: {
          width: 52,
          textAlign: 'right',
          flexShrink: 0
        }
      }, rankCell(t)), React.createElement('span', {
        style: {
          flexShrink: 0
        }
      }, stateChip(t)), React.createElement('span', {
        style: {
          width: 42,
          textAlign: 'center',
          flexShrink: 0,
          color: '#94a3b8',
          fontFamily: 'SF Mono,monospace',
          fontSize: 11.5
        }
      }, t.last ? fmtDate(t.last.checked_at) : '-'), isViewer ? null : React.createElement('button', {
        className: 'btn btn-secondary btn-sm',
        style: {
          flexShrink: 0
        },
        onClick: function (e) {
          e.stopPropagation();
          toggleActive(t);
        },
        title: t.active ? '일시중지 — 자동 수집에서 제외' : '재개'
      }, t.active ? '⏸' : '▶'), isViewer ? null : React.createElement('button', {
        className: 'btn btn-secondary btn-sm',
        style: {
          flexShrink: 0
        },
        onClick: function (e) {
          e.stopPropagation();
          removeTarget(t);
        }
      }, '✕')));
      if (openKey === key) {
        rowEls.push(React.createElement('div', {
          key: 'x' + t.id,
          className: 'subcard',
          style: {
            margin: '4px 0 8px'
          }
        }, window.PlaceRankChart ? React.createElement(window.PlaceRankChart, {
          series: chartSeries,
          keyword: t.keyword,
          days: chartDays,
          businessName: t.business_name,
          placeUrl: t.place_id ? 'https://map.naver.com/p/entry/place/' + t.place_id : '',
          onDays: function (d) {
            setChartDays(d);
            loadSeries(t, d);
          }
        }) : React.createElement('div', {
          className: 'empty'
        }, '차트 컴포넌트를 불러올 수 없습니다.')));
      }
    });
    return React.createElement('div', {
      key: 'g' + gi,
      className: 'card',
      style: {
        padding: '14px 16px',
        alignSelf: 'start'
      }
    }, React.createElement('div', {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        gap: 8,
        flexWrap: 'wrap',
        marginBottom: 8
      }
    }, React.createElement('div', {
      style: {
        minWidth: 0
      }
    }, React.createElement('div', {
      style: {
        fontWeight: 800,
        fontSize: 15,
        color: '#0f172a'
      }
    }, '📍 ' + (g.name || '')), React.createElement('div', {
      style: {
        color: '#94a3b8',
        fontSize: 11.5,
        marginTop: 1
      }
    }, (g.region || '') + (g.place_id ? ' · ID ' + g.place_id : ''))), React.createElement('div', {
      style: {
        display: 'flex',
        gap: 6,
        alignItems: 'center',
        flexWrap: 'wrap'
      }
    }, s.best != null ? React.createElement('span', {
      style: {
        fontSize: 12.5,
        fontWeight: 800,
        color: '#059669'
      }
    }, '최고 ' + s.best + '위') : null, React.createElement('span', {
      className: 'ps ps-g',
      style: {
        fontSize: 11
      }
    }, '노출 ' + s.exposed), React.createElement('span', {
      className: 'ps ps-r',
      style: {
        fontSize: 11
      }
    }, '미노출 ' + s.missing), s.wait ? React.createElement('span', {
      className: 'ps ps-n',
      style: {
        fontSize: 11
      }
    }, '대기 ' + s.wait) : null)), rowEls);
  });
  var kwChipsEls = kws.map(function (k, i) {
    return React.createElement('span', {
      key: k,
      className: 'kwchip cur',
      style: {
        margin: '2px 4px 2px 0',
        cursor: 'pointer'
      },
      title: '분석 키워드: ' + combinedPreview(k) + ' (클릭 시 제거)',
      onClick: function () {
        setKws(kws.filter(function (_, j) {
          return j !== i;
        }));
      }
    }, combinedPreview(k) + ' ✕');
  });
  return React.createElement('div', {
    className: 'place-analysis'
  }, React.createElement('div', {
    className: 'pa-wrap',
    style: {
      maxWidth: 1180,
      margin: '0 auto',
      padding: '18px 16px 60px'
    }
  },
  // ── 헤더 ──
  React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      flexWrap: 'wrap',
      gap: 10,
      margin: '4px 0 12px'
    }
  }, React.createElement('div', null, React.createElement('h2', {
    style: {
      margin: 0,
      fontSize: 19
    }
  }, '📊 플레이스 추적'), React.createElement('div', {
    style: {
      color: '#64748b',
      fontSize: 12.5,
      marginTop: 2
    }
  }, '등록한 업체×키워드를 추적 PC가 매일 06:30 무인 수집 → 순위 이력 자동 기록')), isViewer ? React.createElement('span', {
    style: {
      fontSize: 11.5,
      fontWeight: 700,
      borderRadius: 999,
      padding: '3px 10px',
      background: '#f1f5f9',
      border: '1px solid #e2e8f0',
      color: '#64748b'
    }
  }, '👁 열람 전용 (등록·관리는 관리팀)') : React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      flexWrap: 'wrap'
    }
  }, React.createElement('span', {
    style: {
      fontSize: 11.5,
      fontWeight: 700,
      borderRadius: 999,
      padding: '3px 10px',
      background: extReady ? '#dcfce7' : '#f1f5f9',
      border: '1px solid ' + (extReady ? '#bbf7d0' : '#e2e8f0'),
      color: extReady ? '#059669' : '#94a3b8'
    }
  }, extReady ? '🧩 이 브라우저 추적기 연동됨' : '🧩 이 브라우저엔 추적기 없음'), React.createElement('button', {
    className: 'btn btn-primary btn-sm',
    onClick: requestRunNow
  }, '⟳ 지금 수집'))),
  // ── 등록 카드 (영업사원은 안내로 대체 — 스토어 순위 추적과 동일 범주) ──
  isViewer ? React.createElement('div', {
    className: 'note est',
    style: {
      marginBottom: 14
    }
  }, '🔒 플레이스 순위 추적 등록·관리는 관리팀 권한입니다(스토어 순위 추적과 동일 기준). ', '영업 대상 분석은 「📍 플레이스 분석」 탭에서 자유롭게 사용할 수 있습니다. 추적이 필요한 업체는 관리팀에 요청해주세요.') : React.createElement('div', {
    className: 'card',
    style: {
      marginBottom: 14
    }
  }, React.createElement('div', {
    style: {
      fontWeight: 800,
      fontSize: 14.5,
      marginBottom: 10
    }
  }, '➕ 추적 대상 등록'), React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'minmax(160px,1.2fr) minmax(120px,0.9fr) minmax(220px,2fr) auto',
      gap: 10,
      alignItems: 'end'
    }
  }, React.createElement('div', null, React.createElement('label', {
    style: {
      display: 'block',
      fontSize: 11.5,
      fontWeight: 700,
      color: '#64748b',
      marginBottom: 4
    }
  }, '업체명 *'), React.createElement('input', {
    type: 'text',
    value: bizName,
    placeholder: '예: 성수동 감성카페',
    onChange: function (e) {
      setBizName(e.target.value);
    },
    style: {
      width: '100%',
      boxSizing: 'border-box',
      border: '1px solid #e2e8f0',
      borderRadius: 9,
      padding: '8px 10px',
      fontSize: 13
    }
  })), React.createElement('div', null, React.createElement('label', {
    style: {
      display: 'block',
      fontSize: 11.5,
      fontWeight: 700,
      color: '#64748b',
      marginBottom: 4
    }
  }, '지역 *'), React.createElement('input', {
    type: 'text',
    value: region,
    placeholder: '예: 성수동',
    onChange: function (e) {
      setRegion(e.target.value);
    },
    style: {
      width: '100%',
      boxSizing: 'border-box',
      border: '1px solid #e2e8f0',
      borderRadius: 9,
      padding: '8px 10px',
      fontSize: 13
    }
  })), React.createElement('div', null, React.createElement('label', {
    style: {
      display: 'block',
      fontSize: 11.5,
      fontWeight: 700,
      color: '#64748b',
      marginBottom: 4
    }
  }, '추적 키워드 (Enter로 추가 · 최대 10)'), React.createElement('div', {
    style: {
      border: '1px solid #e2e8f0',
      borderRadius: 9,
      padding: '4px 8px',
      background: '#fbfcfe',
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      minHeight: 36
    }
  }, kwChipsEls, React.createElement('input', {
    type: 'text',
    value: kwInput,
    placeholder: kws.length ? '' : '예: 카페, 브런치',
    onChange: function (e) {
      setKwInput(e.target.value);
    },
    onKeyDown: onKwKey,
    style: {
      flex: 1,
      minWidth: 90,
      border: 0,
      outline: 'none',
      background: 'transparent',
      fontSize: 13,
      padding: '4px 2px'
    }
  }))), React.createElement('button', {
    className: 'btn btn-primary',
    onClick: submit,
    disabled: saving
  }, saving ? '등록 중…' : '등록')), React.createElement('div', {
    style: {
      marginTop: 10
    }
  }, React.createElement('label', {
    style: {
      display: 'block',
      fontSize: 11.5,
      fontWeight: 700,
      color: '#64748b',
      marginBottom: 4
    }
  }, '플레이스 링크 또는 ID (선택 — 넣으면 이름 대신 ID로 정확 매칭)'), React.createElement('input', {
    type: 'text',
    value: placeIdInput,
    placeholder: '예: https://m.place.naver.com/restaurant/1234567890 · 네이버 지도 업체 페이지 주소를 그대로 붙여넣으세요',
    onChange: function (e) {
      setPlaceIdInput(e.target.value);
    },
    style: {
      width: '100%',
      boxSizing: 'border-box',
      border: '1px solid #e2e8f0',
      borderRadius: 9,
      padding: '8px 10px',
      fontSize: 13
    }
  }), (placeIdInput || '').trim() ? React.createElement('div', {
    style: {
      fontSize: 11.5,
      marginTop: 4,
      fontWeight: 700,
      color: extractPlaceId(placeIdInput) ? '#059669' : '#dc2626'
    }
  }, extractPlaceId(placeIdInput) ? '✓ 인식된 플레이스 ID: ' + extractPlaceId(placeIdInput) : '✕ ID를 인식하지 못했습니다 — 지도 업체 페이지 주소 또는 숫자 ID를 넣어주세요') : null), React.createElement('div', {
    className: 'note est',
    style: {
      marginTop: 10
    }
  }, 'ℹ️ 키워드는 자동으로 「지역 + 키워드」로 저장됩니다(예: 성수동 + 카페 → 성수동 카페). 지역이 포함된 키워드는 검색 위치와 무관하게 순위가 재현됩니다(실측 검증). 플레이스 ID를 비워두면 업체명으로 찾고, 첫 노출 때 ID가 자동 저장됩니다.')),
  // ── 현황 필 ──
  React.createElement('div', {
    className: 'pills',
    style: {
      margin: '2px 0 10px'
    }
  }, React.createElement('span', {
    className: 'ps ps-g'
  }, '노출 ' + pills.exposed), React.createElement('span', {
    className: 'ps ps-r'
  }, '미노출 ' + pills.missing), React.createElement('span', {
    className: 'ps ps-n'
  }, '미확인 ' + pills.unknown + (pills.none ? ' · 이력 없음 ' + pills.none : ''))),
  // ── 목록 (업체별 카드) ──
  loading ? React.createElement('div', {
    className: 'card'
  }, React.createElement('div', {
    className: 'empty'
  }, '불러오는 중…')) : targets.length === 0 ? React.createElement('div', {
    className: 'card'
  }, React.createElement('div', {
    className: 'empty'
  }, '아직 추적 대상이 없습니다 — 위에서 업체와 키워드를 등록하면 다음 자동 수집(매일 06:30)부터 순위가 기록됩니다.')) : React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 430px), 1fr))',
      gap: 12,
      alignItems: 'start'
    }
  }, bizCards),
  // ── 안내 ──
  React.createElement('div', {
    className: 'note ok',
    style: {
      marginTop: 12
    }
  }, '✅ 수집은 「플레이스 순위 추적기」 확장이 설치된 추적 PC(24시간 크롬)가 매일 06:30 자동으로 수행합니다. ', '확장이 없는 PC에서도 등록만 해두면 됩니다 — 추적 PC가 수집 직전 최신 등록 목록을 자동으로 받아 갑니다. ', '키워드 행을 클릭하면 일자별 순위 추이를 볼 수 있고, 수동 「📍 플레이스 분석」과 같은 이력에 이어집니다.')));
};

;/* ===== js/analysis.jsx ===== */
/* analysis.jsx — 분석 실행 로직(_doSearch)을 App.jsx에서 분리
 * window.createDoSearch(deps) → _doSearch 함수 반환. deps로 App의 setter/ref/값 주입. */
window.createDoSearch = function (deps) {
  var cleanProductUrl = deps.cleanProductUrl;
  var lastHtmlRef = deps.lastHtmlRef;
  var products = deps.products;
  var searchIdRef = deps.searchIdRef;
  var setAdvertiserLoading = deps.setAdvertiserLoading;
  var setAdvertiserReport = deps.setAdvertiserReport;
  var setAnalysisData = deps.setAnalysisData;
  var setCompanyName = deps.setCompanyName;
  var setDatalabData = deps.setDatalabData;
  var setDatalabLoading = deps.setDatalabLoading;
  var setHtmlDetailResult = deps.setHtmlDetailResult;
  var setHtmlReviewData = deps.setHtmlReviewData;
  var setRankCheckResult = deps.setRankCheckResult;
  var setRelatedData = deps.setRelatedData;
  var setSearchLoading = deps.setSearchLoading;
  var setSearchedKeyword = deps.setSearchedKeyword;
  var setSearchedProductUrl = deps.setSearchedProductUrl;
  var setShopProducts = deps.setShopProducts;
  var setVolumeData = deps.setVolumeData;
  var setAuditStatus = deps.setAuditStatus || function () {};
  return function _doSearch(keyword, productUrl, inputCompanyName, htmlInput) {
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
    setAuditStatus(null);

    // 검색바에서 HTML이 입력되었으면 상세페이지 분석 + 리뷰 데이터 추출 (비동기)
    if (htmlInput && htmlInput.length >= 100) {
      api.post('/seo/detail-page', {
        html: htmlInput,
        product_url: cleanedUrl || ''
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
    // cleanedUrl 사용: 추적 파라미터 제거 + HTML만 붙여넣은 경우 HTML에서 자동추출된 URL 포함
    // (기존엔 raw productUrl이라 HTML만 붙여넣으면 광고주(진입전략) 분석이 통째로 누락됐음)
    if (cleanedUrl) {
      setAdvertiserLoading(true);
      api.post('/advertiser/analyze', {
        keyword: keyword,
        product_url: cleanedUrl
      }).then(function (res) {
        if (searchIdRef.current !== currentSearchId) return;
        if (res && res.success) setAdvertiserReport(res.data);
        setAdvertiserLoading(false);
      }).catch(function () {
        if (searchIdRef.current !== currentSearchId) return;
        setAdvertiserLoading(false);
      });
    }

    // 병렬로 3개 API 호출 — 실패 항목은 검수(_audit)가 재조회해 '실데이터가 채워진 상태'로만 본처리
    var _auditItems = {};
    var _pushAudit = function (phase) {
      try {
        setAuditStatus({
          phase: phase,
          items: Object.keys(_auditItems).map(function (n) {
            return {
              name: n,
              st: _auditItems[n]
            };
          })
        });
      } catch (e) {}
    };
    var _fetchTriple = function (prev) {
      prev = prev || [null, null, null];
      var ok = {
        vol: !!(prev[0] && prev[0].success && prev[0].data && prev[0].data[0]),
        rel: !!(prev[1] && prev[1].success),
        shop: !!(prev[2] && prev[2].success && prev[2].data && (prev[2].data.products || []).length > 0)
      };
      // 성공한 항목은 재호출하지 않고 그대로 유지 — 실패분만 다시 받는다
      return Promise.all([ok.vol ? Promise.resolve(prev[0]) : api.post('/keyword/volume', [keyword]).catch(function () {
        return prev[0];
      }), ok.rel ? Promise.resolve(prev[1]) : api.post('/keywords/related', {
        keyword: keyword
      }).catch(function () {
        return prev[1];
      }), ok.shop ? Promise.resolve(prev[2]) : api.post('/products/search', {
        keyword: keyword,
        count: 80
      }).catch(function () {
        return prev[2];
      })]);
    };
    var _processResults = function (results) {
      if (searchIdRef.current !== currentSearchId) return; // 이미 다른 검색 시작됨

      var volRes = results[0];
      var relRes = results[1];
      var shopRes = results[2];

      // 모든 API 실패 시 사용자에게 알림
      if ((!volRes || !volRes.success) && (!relRes || !relRes.success) && (!shopRes || !shopRes.success)) {
        toast.error('키워드 분석 데이터를 가져오지 못했습니다. 네트워크를 확인해주세요.');
      }
      // 검색량만 실패한 경우도 명시 경고 — '0회'를 실제값으로 오인하거나 관련 섹션이 조용히 사라지는 것 방지
      else if (!volRes || !volRes.success) {
        (toast.warn || toast.error)('검색량 데이터를 가져오지 못했습니다 — 검색량·경쟁강도·판매추정 지표는 참고용입니다.');
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

        // 전환율 밴드(저/중/고) — 매출/판매량은 단일값이 아니라 '범위'로 추정 (±EST_TOLERANCE)
        var EST_TOLERANCE = 0.30; // 허용오차 밴드 ±30%
        var cvMid = 0.035; // 기준 전환율 3.5%
        var cvLo = cvMid * (1 - EST_TOLERANCE); // 0.0245
        var cvHi = cvMid * (1 + EST_TOLERANCE); // 0.0455

        var topProductsList = prods.slice(0, 40).map(function (p) {
          var ctr = getCTR(p.rank);
          var estSales = Math.max(1, Math.round(totalVol * ctr * cvMid));
          var estSalesLo = Math.max(1, Math.round(totalVol * ctr * cvLo));
          var estSalesHi = Math.max(1, Math.round(totalVol * ctr * cvHi));
          return {
            rank: p.rank,
            name: p.product_name,
            store: p.store_name,
            price: p.price,
            priceStr: fmt(p.price) + '원',
            ctr: ctr,
            estMonthlySales: estSales,
            estMonthlySalesStr: fmt(estSales) + '건',
            estMonthlySalesRange: fmt(estSalesLo) + '~' + fmt(estSalesHi) + '건',
            estRevenue: p.price * estSales,
            estRevenueStr: fmt(p.price * estSales) + '원',
            estRevenueRange: fmt(p.price * estSalesLo) + '~' + fmt(p.price * estSalesHi) + '원'
          };
        });

        // 전체 시장 규모 = 상위 40개 상품 추정 매출 합산 (전환율별로 동일 방식 합산)
        var _marketTotal = function (cv) {
          return prods.slice(0, 40).reduce(function (sum, p) {
            var estSales = Math.max(1, Math.round(totalVol * getCTR(p.rank) * cv));
            return sum + p.price * estSales;
          }, 0);
        };
        var totalMarketRevenue = _marketTotal(cvMid);
        var marketLo = _marketTotal(cvLo);
        var marketHi = _marketTotal(cvHi);

        // '2.5%~4.6% (기준 3.5%, ±30%)' 형태의 전환율 가정 라벨 (백엔드 conv_band_label과 동일)
        var convBandLabel = (cvLo * 100).toFixed(1) + '%~' + (cvHi * 100).toFixed(1) + '% (기준 ' + (cvMid * 100).toFixed(1) + '%, ±' + Math.round(EST_TOLERANCE * 100) + '%)';
        analysis.marketRevenue = {
          avgPrice: fmt(avgPrice) + '원',
          estimatedMonthly: fmt(totalMarketRevenue) + '원',
          estimatedMonthlyRange: fmt(marketLo) + '~' + fmt(marketHi) + '원',
          conversionRate: convBandLabel,
          calculationMethod: 'CTR × 전환율(밴드)',
          tolerance: '±' + Math.round(EST_TOLERANCE * 100) + '%',
          topProducts: topProductsList.map(function (p) {
            return {
              rank: p.rank,
              priceNum: p.price,
              /* 리뷰 실측 보정 계산용 숫자 가격 */
              name: p.name,
              store: p.store,
              price: p.priceStr,
              ctr: (p.ctr * 100).toFixed(1) + '%',
              estMonthlySales: p.estMonthlySalesStr,
              estMonthlySalesRange: p.estMonthlySalesRange,
              estRevenue: p.estRevenueStr,
              estRevenueRange: p.estRevenueRange
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
        // 전환율 밴드(저/중/고) — 판매량/매출은 단일값이 아니라 '범위'로 추정 (±EST_TOLERANCE)
        var SE_TOLERANCE = 0.30; // 허용오차 밴드 ±30%
        var cv = 0.035; // 기준 전환율 3.5%
        var cvLoSE = cv * (1 - SE_TOLERANCE); // 0.0245
        var cvHiSE = cv * (1 + SE_TOLERANCE); // 0.0455
        // '2.5%~4.6% (기준 3.5%, ±30%)' 형태의 전환율 가정 라벨 (백엔드 conv_band_label과 동일)
        var seBandLabel = (cvLoSE * 100).toFixed(1) + '%~' + (cvHiSE * 100).toFixed(1) + '% (기준 ' + (cv * 100).toFixed(1) + '%, ±' + Math.round(SE_TOLERANCE * 100) + '%)';
        // 80위 전체 한번에 계산
        var allRanks = [];
        for (var ci = 0; ci < 80; ci++) {
          var sales = Math.round(totalVol * CTR_TABLE[ci] * cv);
          var salesLo = Math.round(totalVol * CTR_TABLE[ci] * cvLoSE);
          var salesHi = Math.round(totalVol * CTR_TABLE[ci] * cvHiSE);
          allRanks.push({
            sales: sales,
            revenue: sales * avgP,
            salesLo: salesLo,
            salesHi: salesHi,
            revenueLo: salesLo * avgP,
            revenueHi: salesHi * avgP
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

        // 순위별 시뮬레이션 행 (±밴드 범위 포함) — 백엔드 salesEstimation.simulations와 동일 구조
        var _simRanks = [1, 5, 10, 15, 20, 25, 30, 35, 40];
        var simulations = _simRanks.map(function (rank) {
          var r = allRanks[rank - 1];
          return {
            rank: rank,
            estSales: r.sales,
            estSalesRange: fmt(r.salesLo) + '~' + fmt(r.salesHi),
            revenue: fmt(r.revenue) + '원',
            revenueRange: fmt(r.revenueLo) + '~' + fmt(r.revenueHi) + '원'
          };
        });
        analysis.salesEstimation = {
          avgPrice: fmt(avgP) + '원',
          monthlySearches: fmt(totalVol),
          estimatedCTR: 'CTR × 전환율 ' + seBandLabel,
          tolerance: '±' + Math.round(SE_TOLERANCE * 100) + '%',
          simulations: simulations,
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
            color: '#3b82f6'
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
        var cat1 = '',
          cat2 = '',
          cat3 = '';
        var _lv = analysis.categoryAnalysis && analysis.categoryAnalysis.categoryLevels;
        if (_lv) {
          if (_lv.large && _lv.large.length > 0) cat1 = _lv.large[0].name || '';
          if (_lv.medium && _lv.medium.length > 0) cat2 = _lv.medium[0].name || '';
          if (_lv.small && _lv.small.length > 0) cat3 = _lv.small[0].name || '';
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
        /* 검수 루프: 누락 지표만 재조회 — 백엔드 지표별 캐시 덕에 성공분은 API를 다시 쓰지 않음 */
        var _dlKeyMap = {
          '성별': 'gender',
          '연령': 'age',
          '트렌드': 'trend',
          '요일': 'weekday',
          '인기·급상승': 'categoryKeywords'
        };
        var _dlExpected = ['성별', '연령', '트렌드', '요일'];
        if (relKws.length >= 2) _dlExpected.push('인기·급상승');
        _dlExpected.forEach(function (n) {
          _auditItems[n] = 'wait';
        });
        _pushAudit('auditing');
        setDatalabLoading(true);
        var _dlCall = function (dlRound) {
          api.post('/datalab/analyze', {
            keyword: keyword,
            category1: cat1,
            category2: cat2,
            category3: cat3,
            related_keywords: relKws
          }).then(function (dlRes) {
            if (searchIdRef.current !== currentSearchId) return;
            var d = dlRes && dlRes.success && dlRes.data || null;
            if (d) setDatalabData(d);
            var missing = [];
            _dlExpected.forEach(function (n) {
              var okItem = !!(d && d[_dlKeyMap[n]]);
              _auditItems[n] = okItem ? 'ok' : dlRound < 2 ? 'retry' : 'fail';
              if (!okItem) missing.push(n);
            });
            if (missing.length > 0 && dlRound < 2) {
              _pushAudit('auditing');
              setTimeout(function () {
                if (searchIdRef.current !== currentSearchId) return;
                _dlCall(dlRound + 1);
              }, 4000);
            } else {
              _pushAudit('done');
              setDatalabLoading(false);
              if (missing.length > 0) {
                try {
                  (toast.warn || toast.error)('데이터랩 일부 지표 미수신(' + missing.join('·') + ') — 잠시 후 재분석하면 채워집니다.');
                } catch (e) {}
              }
            }
          }).catch(function (e) {
            console.warn('데이터랩 조회 실패:', e);
            if (searchIdRef.current !== currentSearchId) return;
            if (dlRound < 2) {
              setTimeout(function () {
                if (searchIdRef.current === currentSearchId) _dlCall(dlRound + 1);
              }, 4000);
            } else {
              _dlExpected.forEach(function (n) {
                if (_auditItems[n] !== 'ok') _auditItems[n] = 'fail';
              });
              _pushAudit('done');
              setDatalabLoading(false);
            }
          });
        };
        _dlCall(0);
      })();
    };

    /* 🔍 데이터 검수 게이트: 핵심 3종(검색량·연관·상품)이 빈 채로 화면·보고서가 그려지지 않도록,
       실패 항목만 재조회(최대 2회, 2.5s→5s 간격 — 429 버스트가 풀릴 시간)한 뒤 본처리한다.
       재조회로도 못 받으면 그대로 진행하되 검수 배너에 실패로 표시(가짜값 대신 정직한 상태). */
    var _audit = function (results, round) {
      if (searchIdRef.current !== currentSearchId) return;
      var ok = {
        vol: !!(results[0] && results[0].success && results[0].data && results[0].data[0]),
        rel: !!(results[1] && results[1].success),
        shop: !!(results[2] && results[2].success && results[2].data && (results[2].data.products || []).length > 0)
      };
      var retrying = (!ok.vol || !ok.rel || !ok.shop) && round < 2;
      _auditItems['검색량'] = ok.vol ? 'ok' : retrying ? 'retry' : 'fail';
      _auditItems['연관 키워드'] = ok.rel ? 'ok' : retrying ? 'retry' : 'fail';
      _auditItems['상품 검색'] = ok.shop ? 'ok' : retrying ? 'retry' : 'fail';
      _pushAudit(retrying ? 'auditing' : 'collected');
      if (retrying) {
        if (round === 0) {
          try {
            toast.info('🔍 데이터 검수 — 누락 항목을 재조회합니다…');
          } catch (e) {}
        }
        setTimeout(function () {
          if (searchIdRef.current !== currentSearchId) return;
          _fetchTriple(results).then(function (r2) {
            _audit(r2, round + 1);
          });
        }, 2500 + round * 2500);
        return; // 완성(또는 재조회 소진) 전에는 본처리하지 않음
      }
      try {
        _processResults(results);
      } catch (e) {
        console.error('분석 처리 오류:', e);
        try {
          toast.error('분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
        } catch (e2) {}
        setSearchLoading(false);
      }
    };
    _fetchTriple(null).then(function (results) {
      _audit(results, 0);
    }).catch(function (e) {
      if (searchIdRef.current !== currentSearchId) return;
      console.error('검색 오류:', e);
      toast.error('분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
      setSearchLoading(false);
    });
  };
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
    var validPages = ['home', 'place', 'placetrack', 'analysis', 'rank', 'management', 'learning', 'seo', 'guide', 'settings'];
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
  const [auditStatus, setAuditStatus] = useState(null); // 🔍 데이터 검수 상태
  const [rankCheckResult, setRankCheckResult] = useState(null); // 순위 추적 → 진입 전략 공유용
  const searchIdRef = React.useRef(0); // 비동기 요청 경합 방지용
  const lastHtmlRef = React.useRef(''); // #1: 마지막 분석에 쓰인 상세 HTML (업체 저장/재사용용)

  /* 업체 카드 클릭으로 시작된 분석 추적 (자동 저장용) */
  const [currentClientId, setCurrentClientId] = useState(null);
  const [searchBarInitial, setSearchBarInitial] = useState(null);
  const [autoSaveStatus, setAutoSaveStatus] = useState(''); // '', 'saving', 'saved', 'error'

  /* 순위 추적 → 업체관리 이동 시 자동 검색용 */
  const [managementInitialSearch, setManagementInitialSearch] = useState(null);

  /* 경쟁사 등록 모드 — 설정 시 이 분석을 광고주의 경쟁사로 저장 (null=일반) */
  const [competitorContext, setCompetitorContext] = useState(null); // { competitor_of, advName }

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
      // 기존 세션 복원 (SSO 실패 시 폴백으로도 사용 — 오래된 sso 토큰이 유효 세션을 밀어내지 않게)
      var _restoreSession = function () {
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
      };
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
            setAuthChecking(false);
          } else {
            _restoreSession(); // SSO 토큰 만료·검증 실패 → 기존 세션이 있으면 그대로 유지
          }
        }).catch(function () {
          _cleanUrl();
          _restoreSession();
        });
        return; // SSO 처리로 분기
      }
      _restoreSession();
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

  /* 🧩 크롬 확장 브리지 — 확장이 수집한 상품 HTML 수신 → 검색바 자동 주입·분석 자동 시작.
     확장 미설치·미사용 시 이 리스너는 아무 일도 하지 않음(기존 흐름 무영향). */
  const currentUserRef = React.useRef(null);
  currentUserRef.current = currentUser;
  const extSearchRef = React.useRef(null); // handleHomeSearch 최신본 (정의 이후 갱신)
  const lastCaptureRef = React.useRef(0); // 같은 수집물 중복 처리 방지
  useEffect(function () {
    var onExtMsg = function (ev) {
      if (ev.source !== window || !ev.data || ev.data.type !== 'METAINC_EXT_CAPTURE') return;
      if (!currentUserRef.current) return; // 로그인 전 — 확장이 30초간 재시도
      var p = ev.data.payload || {};
      var html = String(p.html || '');
      if (html.length < 1000) return; // 비정상 수집물 무시
      var capId = Number(p.captured_at) || 0;
      if (capId && capId === lastCaptureRef.current) return;
      lastCaptureRef.current = capId || Date.now();
      window.postMessage({
        type: 'METAINC_EXT_ACK'
      }, window.location.origin);
      try {
        toast.success('🧩 확장 수신: 상품 HTML ' + Math.round(html.length / 1024) + 'KB');
      } catch (e) {}
      var kw = String(p.keyword || '').trim();
      if (kw && extSearchRef.current) {
        extSearchRef.current(kw, String(p.product_url || ''), html); // 분석 자동 시작
      } else {
        setSearchBarInitial({
          keyword: kw,
          companyName: String(p.product_name || ''),
          html: html,
          productUrl: String(p.product_url || '')
        });
        setCurrentPage('home');
        try {
          toast.info('키워드 입력 후 분석 실행을 눌러주세요.');
        } catch (e) {}
      }
    };
    window.addEventListener('message', onExtMsg);
    return function () {
      window.removeEventListener('message', onExtMsg);
    };
  }, []);

  /* 📊 플레이스 추적기 브리지 — 무인 수집 결과 수신 → /api/place/ingest 기록 → ACK.
     추적기(별개 확장) 미설치·결과 없음이면 아무 일도 하지 않음(기존 흐름 무영향). */
  const lastPlaceIngestRef = React.useRef(0);
  const placeIngestBusyRef = React.useRef(false);
  useEffect(function () {
    var onPlaceMsg = function (ev) {
      if (ev.source !== window || !ev.data || ev.data.type !== 'METAINC_PLACE_RESULTS') return;
      if (!currentUserRef.current) return; // 로그인 전 — 브리지가 재시도(최대 20시간)
      var p = ev.data.payload || {};
      var results = p.results || [];
      if (!results.length) return;
      var runId = Number(p.created_at) || 0;
      if (runId && runId === lastPlaceIngestRef.current) return; // 같은 수집분 중복 기록 방지
      if (placeIngestBusyRef.current) return; // 기록 중 재시도 무시
      placeIngestBusyRef.current = true;
      api.post('/place/ingest', {
        results: results,
        ran_at: p.ran_at || null,
        source: p.source || null
      }).then(function (res) {
        placeIngestBusyRef.current = false;
        if (res && res.success) {
          lastPlaceIngestRef.current = runId || Date.now();
          window.postMessage({
            type: 'METAINC_PLACE_RESULTS_ACK'
          }, window.location.origin);
          var s = p.summary || {};
          try {
            toast.success('📊 플레이스 무인 수집 기록: 노출 ' + (s.exposed || 0) + ' · 미노출 ' + (s.missing || 0) + (s.unknown ? ' · 미확인 ' + s.unknown : ''));
          } catch (e) {}
        }
      }).catch(function () {
        placeIngestBusyRef.current = false;
      }); // 실패 시 ACK 없음 → 브리지 재시도
    };
    window.addEventListener('message', onPlaceMsg);
    return function () {
      window.removeEventListener('message', onPlaceMsg);
    };
  }, []);

  /* 🧩 경쟁사 등록 모드 복원 — 확장이 연 새 로직 탭에서도 '이 분석 = 경쟁사' 흐름이 이어지게.
     진입(handleRegisterCompetitor) 시 localStorage에 저장한 컨텍스트를, 새 탭 로드 시 30분 이내면 복원.
     (일반 흐름엔 무영향: 저장된 값 없으면 아무 일도 안 함) */
  useEffect(function () {
    try {
      if (competitorContext) return; // 이미 모드면 유지
      var raw = localStorage.getItem('logic_comp_ctx');
      if (!raw) return;
      var ctx = JSON.parse(raw);
      if (ctx && ctx.competitor_of && ctx.ts && Date.now() - ctx.ts < 30 * 60 * 1000) {
        setCompetitorContext({
          competitor_of: ctx.competitor_of,
          advName: ctx.advName
        });
      } else {
        localStorage.removeItem('logic_comp_ctx'); // 만료 → 정리
      }
    } catch (e) {}
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
      background: 'linear-gradient(135deg,#3b82f6,#93c5fd)',
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
          toast.error('일일 분석 제한(15회)을 초과했습니다. 내일 자정에 초기화됩니다.');
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
  var _doSearch = window.createDoSearch({
    cleanProductUrl: cleanProductUrl,
    lastHtmlRef: lastHtmlRef,
    products: products,
    searchIdRef: searchIdRef,
    setAdvertiserLoading: setAdvertiserLoading,
    setAdvertiserReport: setAdvertiserReport,
    setAnalysisData: setAnalysisData,
    setCompanyName: setCompanyName,
    setDatalabData: setDatalabData,
    setDatalabLoading: setDatalabLoading,
    setAuditStatus: setAuditStatus,
    setHtmlDetailResult: setHtmlDetailResult,
    setHtmlReviewData: setHtmlReviewData,
    setRankCheckResult: setRankCheckResult,
    setRelatedData: setRelatedData,
    setSearchLoading: setSearchLoading,
    setSearchedKeyword: setSearchedKeyword,
    setSearchedProductUrl: setSearchedProductUrl,
    setShopProducts: setShopProducts,
    setVolumeData: setVolumeData
  });

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

  /* ==================== 스토어 분석 → 키워드 순위 탭 이동 ====================
     검색 컨텍스트는 RankTrackingSection(analysisOnly)이 sessionStorage('logic_rank_ctx')에 기록한 뒤 호출 */
  var handleOpenRankTab = function () {
    setCurrentPage('rank');
    try {
      window.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    } catch (e) {}
  };

  /* ==================== 경쟁사 등록 모드 진입 ==================== */
  /* 업체 상세의 '경쟁사 등록' → 분석 화면으로 전환. 이후 분석을 저장하면
     광고주(advClient)의 경쟁사로 quick-register 된다(SaveToClientSection이 competitorContext 사용). */
  var handleRegisterCompetitor = function (advClient) {
    if (!advClient) return;
    setCompetitorContext({
      competitor_of: advClient.id,
      advName: advClient.name
    });
    // 확장으로 경쟁사를 보내면 '새 로직 탭'이 열려 이 모드가 사라진다 →
    // 같은 오리진 localStorage에 잠깐(30분) 저장해 새 탭에서 복원(확장 수정 불필요).
    try {
      localStorage.setItem('logic_comp_ctx', JSON.stringify({
        competitor_of: advClient.id,
        advName: advClient.name,
        ts: Date.now()
      }));
    } catch (e) {}
    setCurrentClientId(null);
    setAutoSaveStatus('');
    setSearchBarInitial({
      keyword: '',
      productUrl: '',
      companyName: ''
    });
    setCurrentPage('analysis');
    try {
      window.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    } catch (e) {}
    try {
      toast.info("경쟁사 등록 모드 — '" + advClient.name + "'의 경쟁사 상품을 분석 후 저장하세요.");
    } catch (e) {}
  };

  /* ==================== 업체 카드 클릭 → 자동 분석 ==================== */
  var handleClientClick = function (params) {
    if (!params) return;
    setCompetitorContext(null);
    try {
      localStorage.removeItem('logic_comp_ctx');
    } catch (e) {} // 일반 업체 분석 → 경쟁사 모드 해제
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

  /* DOM 캡처 — 자동 저장/저장 보고서 다운로드용 HTML 생성
   * 공용 빌더(ReportCapture) 사용: 수동 내보내기(ReportSection)와 완전히 동일한 제거 규칙·표지·푸터 적용 */
  var captureAutoReportHtml = function (kw) {
    try {
      if (!window.ReportCapture) return '';
      return window.ReportCapture.buildHtml({
        title: (kw || '키워드') + ' 분석 보고서',
        managerName: currentUser && currentUser.name
      });
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
  // 크롬 확장 브리지에서 자동 분석 시작에 사용(최신 클로저 유지)
  extSearchRef.current = function (kw, url, html) {
    handleHomeSearch(kw, url, undefined, html);
  };

  /* ==================== 페이지별 콘텐츠 렌더링 ==================== */

  /* 홈 탭 — 업체 리스트 + 검색 */
  if (currentPage === 'home') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.AppShellBar, {
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
  if (currentPage === 'management') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.AppShellBar, {
    activePage: 'management',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(window.ClientDashboard, {
    currentUser: currentUser,
    onRunAnalysis: handleClientClick,
    onRegisterCompetitor: handleRegisterCompetitor,
    onDownloadReport: downloadSavedReport,
    initialSearch: managementInitialSearch,
    canEdit: currentUser.role !== 'viewer'
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));

  /* 📊 키워드 순위 탭 — 업체별 순위 추적 (스토어 분석에서 분리, 2026-08-04) */
  if (currentPage === 'rank') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.AppShellBar, {
    activePage: 'rank',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(window.KeywordRankPage, {
    currentUser: currentUser,
    onNavigateToClient: handleNavigateToClient
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));

  /* 플레이스 분석 탭 — 오프라인·지역 업종(자체완결 페이지, 스토어 분석 흐름과 독립) */
  if (currentPage === 'place') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.AppShellBar, {
    activePage: 'place',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(window.PlaceAnalysisPage, {
    currentUser: currentUser
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
  if (currentPage === 'placetrack') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.AppShellBar, {
    activePage: 'placetrack',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(window.PlaceTrackingPage, {
    currentUser: currentUser
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
  if (currentPage === 'learning') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.AppShellBar, {
    activePage: 'learning',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(window.LearningCenterPage, {
    currentUser: currentUser
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
  if (currentPage === 'guide') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.AppShellBar, {
    activePage: 'guide',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(window.UserGuidePage, {
    currentUser: currentUser
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
  if (currentPage === 'seo' && (currentUser.role === 'manager' || currentUser.role === 'superadmin')) return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.AppShellBar, {
    activePage: 'seo',
    currentUser: currentUser,
    health: health,
    onNavigate: setCurrentPage
  }), React.createElement(window.SeoOptimizerPage, {
    currentUser: currentUser
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
  if (currentPage === 'users' && (currentUser.role === 'admin' || currentUser.role === 'superadmin')) return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.AppShellBar, {
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
  if (currentPage === 'settings' && currentUser.role === 'superadmin') return React.createElement(React.Fragment, null, React.createElement('div', null, React.createElement(window.AppShellBar, {
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
  }, React.createElement(window.AnalysisStatsSection, null), React.createElement(ApiUsageSection, null), React.createElement(window.SeoRulesSection, null), React.createElement(NotificationSection, null), React.createElement(window.ManagerReassignSection, null), React.createElement(window.ClientDiagnosticsSection, null), React.createElement(window.FeedbackManagement, null))), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));

  /* ==================== 메인 분석 페이지 ==================== */
  return React.createElement(React.Fragment, null, React.createElement('div', {
    className: 'analysis-page'
  }, /* 네비게이션 바 */
  React.createElement(window.AppShellBar, {
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
  }, autoSaveStatus === 'saving' ? '🔄 분석 완료 후 업체관리에 자동 저장됩니다... (약 25초 대기)' : autoSaveStatus === 'saved' ? '✅ 업체관리 탭에 분석 기록이 자동 저장되었습니다' : autoSaveStatus === 'error' ? '⚠️ 자동 저장에 실패했습니다. 하단의 "업체 등록/저장" 버튼을 이용해주세요' : ''), /* 경쟁사 등록 모드 배너 */
  competitorContext && React.createElement('div', {
    style: {
      background: '#fff7ed',
      color: '#c2410c',
      border: '1px solid #fed7aa',
      padding: '10px 16px',
      fontSize: 13,
      fontWeight: 700,
      textAlign: 'center',
      borderRadius: 10,
      margin: '10px auto',
      maxWidth: 1200
    }
  }, "⚔️ 경쟁사 등록 모드 — 이 분석을 " + (currentUser && currentUser.role === 'viewer' ? '영업 대상' : '광고주') + " '" + competitorContext.advName + "'의 경쟁사로 저장합니다. 경쟁사 상품 페이지에서 확장 프로그램(또는 북마클릿)으로 보내거나 아래에 붙여넣어 분석 후 '경쟁사로 저장'을 누르세요.", React.createElement('button', {
    onClick: function () {
      setCompetitorContext(null);
      try {
        localStorage.removeItem('logic_comp_ctx');
      } catch (e) {}
      try {
        toast.info('일반 분석 모드로 전환했습니다.');
      } catch (e) {}
    },
    style: {
      marginLeft: 12,
      fontSize: 11.5,
      fontWeight: 700,
      color: '#c2410c',
      background: '#fff',
      border: '1px solid #fdba74',
      borderRadius: 7,
      padding: '3px 10px',
      cursor: 'pointer'
    }
  }, '모드 해제')), /* ==================== 보고서 레이아웃: 좌측 목차 + 본문 ==================== */
  React.createElement(window.AnalysisResults, {
    advertiserLoading: advertiserLoading,
    advertiserReport: advertiserReport,
    analysisData: analysisData,
    companyName: companyName,
    currentUser: currentUser,
    datalabData: datalabData,
    datalabLoading: datalabLoading,
    auditStatus: auditStatus,
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
    volumeData: volumeData,
    competitorContext: competitorContext,
    onCompetitorSaved: function () {
      setCompetitorContext(null);
      try {
        localStorage.removeItem('logic_comp_ctx');
      } catch (e) {}
    },
    onOpenRankTab: handleOpenRankTab
  })), React.createElement(window.ChatWidget, {
    currentUser: currentUser
  }));
};

// 앱 렌더링 (ErrorBoundary로 감싸서 빈 화면 방지)
var root = ReactDOM.createRoot(document.getElementById('root'));
root.render(React.createElement(window.ErrorBoundary, null, React.createElement(App, null)));
