"""
auto_analysis.py — 서버 사이드 전체 분석 엔진 + HTML 보고서 생성
App.jsx handleSearch의 11가지 분석 섹션을 Python으로 동일 구현
스케줄러(_run_daily_client_analysis)에서 호출
"""
import math
import time
import json
import logging
import requests as req_lib
from datetime import datetime
import html as html_module

logger = logging.getLogger(__name__)


# ==================== 연관 키워드 조회 ====================
def get_related_keywords(keyword: str) -> dict:
    """네이버 검색광고 API로 연관 키워드 + 황금 키워드 조회 (main.py /keywords/related 동일 로직)"""
    from naver_crawler import (
        SEARCHAD_API_KEY, SEARCHAD_SECRET_KEY, SEARCHAD_CUSTOMER_ID,
        _generate_searchad_signature, _safe_int, _safe_float
    )
    import re as _re

    all_keywords = []

    if not (SEARCHAD_API_KEY and SEARCHAD_SECRET_KEY and SEARCHAD_CUSTOMER_ID):
        return {"golden_keywords": [], "related_keywords": [], "total_found": 0}

    uri = "/keywordstool"
    url = f"https://api.searchad.naver.com{uri}"
    params = {"hintKeywords": keyword, "showDetail": "1"}
    data = {}

    for attempt in range(3):
        try:
            timestamp = str(int(time.time() * 1000))
            signature = _generate_searchad_signature(timestamp, "GET", uri)
            headers = {
                "X-Timestamp": timestamp,
                "X-API-KEY": SEARCHAD_API_KEY,
                "X-Customer": SEARCHAD_CUSTOMER_ID,
                "X-Signature": signature,
            }
            resp = req_lib.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(0.5)
            else:
                logger.warning(f"검색광고 API 실패: {e}")

    store_suffixes = ['스토어', '몰', '마켓', '샵', 'store', 'shop', 'mall', 'market',
                      '공식', '본사', '직영', '판매', '무역', '상사', '유통', '컴퍼니',
                      '코리아', '글로벌', '엔터', '그룹', '홈', '닷컴', '.com', '.co.kr']

    def _is_store(kw, seed):
        kw_lower = kw.lower().strip()
        seed_lower = seed.lower().strip()
        seed_words = [w for w in seed_lower.split() if len(w) >= 2]
        has_match = any(w in kw_lower for w in seed_words) if seed_words else (seed_lower in kw_lower)
        has_suffix = any(s in kw_lower for s in store_suffixes)
        is_short_en = len(kw) <= 12 and _re.match(r'^[a-zA-Z0-9]+$', kw)
        if has_suffix and not has_match:
            return True
        if is_short_en and not has_match:
            return True
        return False

    for kd in data.get("keywordList", []):
        rel_kw = kd.get("relKeyword", "")
        pc = _safe_int(kd.get("monthlyPcQcCnt"))
        mobile = _safe_int(kd.get("monthlyMobileQcCnt"))
        total_volume = pc + mobile
        comp_idx = kd.get("compIdx", "")
        is_store_name = _is_store(rel_kw, keyword)

        seed_words = [w for w in keyword.lower().split() if len(w) >= 2]
        has_relevance = any(w in rel_kw.lower() for w in seed_words) if seed_words else (keyword.lower() in rel_kw.lower())

        is_golden = (100 <= total_volume <= 5000 and comp_idx in ("낮음", "LOW") and not is_store_name and has_relevance)

        all_keywords.append({
            "keyword": rel_kw,
            "monthlyPcQcCnt": pc,
            "monthlyMobileQcCnt": mobile,
            "totalVolume": total_volume,
            "compIdx": comp_idx,
            "isGolden": is_golden,
            "isStoreName": is_store_name,
            "monthlyAvePcClkCnt": _safe_float(kd.get("monthlyAvePcClkCnt")),
            "monthlyAveMobileClkCnt": _safe_float(kd.get("monthlyAveMobileClkCnt")),
        })

    golden = sorted([k for k in all_keywords if k["isGolden"]], key=lambda x: -x["totalVolume"])
    others = sorted([k for k in all_keywords if not k["isGolden"]], key=lambda x: -x["totalVolume"])

    return {
        "seed_keyword": keyword,
        "golden_keywords": golden[:20],
        "related_keywords": others[:30],
        "total_found": len(all_keywords),
    }


# ==================== 전체 분석 계산 (App.jsx handleSearch 동일) ====================
def compute_full_analysis(keyword: str, vol_data: dict, prods: list, related_data: dict,
                          total_shop_products: int = 0) -> dict:
    """프론트엔드 App.jsx handleSearch의 분석 계산 로직을 Python으로 완전 재현
    total_shop_products: 네이버 쇼핑 API의 전체 상품 수 (프론트엔드와 동일하게 사용)"""

    total_vol = 0
    if vol_data:
        pc = vol_data.get('monthlyPcQcCnt', 0)
        mobile = vol_data.get('monthlyMobileQcCnt', 0)
        if isinstance(pc, str) and '< 10' in str(pc): pc = 5
        if isinstance(mobile, str) and '< 10' in str(mobile): mobile = 5
        total_vol = int(pc or 0) + int(mobile or 0)

    # 프론트엔드와 동일: 네이버 API total 우선, 없으면 len(prods) 사용
    product_count = total_shop_products if total_shop_products > 0 else len(prods)
    analysis = {}

    def fmt(n):
        try:
            return f"{int(n):,}"
        except (ValueError, TypeError):
            return str(n)

    def comp_label(idx):
        if idx in ('낮음', 'LOW'): return '쉬움'
        if idx in ('높음', 'HIGH'): return '어려움'
        return '보통'

    # 1. 경쟁강도 계산
    if product_count > 0 and total_vol > 0:
        raw_idx = product_count / total_vol
        comp_pct = min(98, max(2, round(math.log10(raw_idx * 10 + 1) / math.log10(101) * 100)))
        if comp_pct <= 30:
            c_label, c_color = '블루오션', '#059669'
        elif comp_pct <= 70:
            c_label, c_color = '보통', '#d97706'
        else:
            c_label, c_color = '레드오션', '#dc2626'

        avg_ctr = 0
        if vol_data:
            avg_ctr = float(vol_data.get('monthlyAvePcClkCnt', 0) or 0) + float(vol_data.get('monthlyAveMobileClkCnt', 0) or 0)

        if comp_pct <= 30:
            comment = f'월간 검색량 {fmt(total_vol)}회 대비 등록 상품 {fmt(product_count)}개로, 공급이 수요를 따라가지 못하는 시장입니다. 신규 진입 시 상위 노출 가능성이 높습니다.'
        elif comp_pct <= 70:
            comment = f'월간 검색량 {fmt(total_vol)}회에 상품 {fmt(product_count)}개가 경쟁 중인 시장입니다. 가격 경쟁력·리뷰 확보·상품명 최적화 등 차별화 전략이 필요합니다.'
        else:
            comment = f'월간 검색량 {fmt(total_vol)}회 대비 상품 {fmt(product_count)}개로, 공급 과잉 상태입니다. 세부 키워드(롱테일) 전략을 권장합니다.'

        analysis['competitionIndex'] = {
            'compIndex': round(raw_idx, 2), 'compPercent': comp_pct,
            'compLabel': c_label, 'compColor': c_color,
            'productCount': product_count, 'searchVolume': total_vol,
            'avgCtr': avg_ctr, 'interpretation': comment,
        }

    # 2. 시장 규모 추정
    def _get_ctr(rank):
        if rank == 1: return 0.08
        if rank == 2: return 0.06
        if rank == 3: return 0.05
        if rank == 4: return 0.04
        if rank == 5: return 0.03
        if rank <= 10: return 0.015
        if rank <= 20: return 0.008
        if rank <= 40: return 0.003
        return 0.001

    if prods:
        prices = [p.get('price', 0) for p in prods if p.get('price', 0) > 0]
        avg_price = round(sum(prices) / len(prices)) if prices else 0
        conv_rate = 0.035

        top_products = []
        for p in prods[:40]:
            rank = p.get('rank', 40)
            ctr = _get_ctr(rank)
            est_sales = max(1, round(total_vol * ctr * conv_rate))
            top_products.append({
                'rank': rank, 'name': p.get('product_name', ''),
                'store': p.get('store_name', ''), 'price': fmt(p.get('price', 0)) + '원',
                'ctr': f'{ctr*100:.1f}%', 'estMonthlySales': fmt(est_sales) + '건',
                'estRevenue': fmt(p.get('price', 0) * est_sales) + '원',
            })

        total_market = sum(p.get('price', 0) * max(1, round(total_vol * _get_ctr(p.get('rank', 40)) * conv_rate)) for p in prods[:20])

        analysis['marketRevenue'] = {
            'avgPrice': fmt(avg_price) + '원', 'estimatedMonthly': fmt(total_market) + '원',
            'conversionRate': '3.5%', 'calculationMethod': 'CTR × 전환율',
            'topProducts': top_products,
        }

    # 3. 키워드 트렌드
    rd = related_data or {}
    if total_vol > 0 and rd.get('related_keywords') and len(rd['related_keywords']) > 0:
        sub_kw = rd['related_keywords'][0]
        ci = analysis.get('competitionIndex', {})
        analysis['keywordTrend'] = {
            'mainKeyword': keyword, 'subKeyword': sub_kw['keyword'],
            'mainVolume': total_vol, 'subVolume': sub_kw.get('totalVolume', 0),
            'mainDifficulty': '쉬움' if ci.get('compIndex', 1) < 0.5 else ('보통' if ci.get('compIndex', 1) < 1.0 else '어려움'),
            'subDifficulty': comp_label(sub_kw.get('compIdx', '')),
        }

    # 4. 골든 키워드
    if rd.get('golden_keywords') and len(rd['golden_keywords']) > 0:
        filtered = [gk for gk in rd['golden_keywords'] if not gk.get('isStoreName')]
        gk = filtered[0] if filtered else rd['golden_keywords'][0]
        gk_vol = gk.get('totalVolume', 0)
        gk_clicks = (gk.get('monthlyAvePcClkCnt', 0) or 0) + (gk.get('monthlyAveMobileClkCnt', 0) or 0)
        analysis['goldenKeyword'] = {
            'name': gk['keyword'], 'volume': gk_vol,
            'competition': comp_label(gk.get('compIdx', '')),
            'ctr': gk_clicks, 'clicks': round(gk_vol * 0.05),
            'reason': f'"{gk["keyword"]}"은(는) 월간 검색량 {fmt(gk_vol)}회, 경쟁강도 "{comp_label(gk.get("compIdx",""))}" 수준으로 상위 노출 진입 비용이 낮습니다.',
        }

    # 5. 광고주 정보
    if vol_data:
        analysis['advertiserInfo'] = {
            'adDepth': vol_data.get('plAvgDepth', 0),
            'pcClicks': str(round(float(vol_data.get('monthlyAvePcClkCnt', 0) or 0), 1)),
            'mobileClicks': str(round(float(vol_data.get('monthlyAveMobileClkCnt', 0) or 0), 1)),
            'compIdx': vol_data.get('compIdx', '-'),
        }

    # 6. 종합 요약 카드
    analysis['summaryCards'] = {
        'totalVolume': fmt(total_vol), 'productCount': fmt(product_count),
        'goldenCount': len(rd.get('golden_keywords', [])),
        'compLevel': analysis.get('competitionIndex', {}).get('compLabel', '-'),
    }

    # 7. 카테고리 분석 (대>중>소 계층 경로)
    if prods:
        # 전체 경로 분석
        fullpath_map = {}
        cat1_map = {}
        cat2_map = {}
        cat3_map = {}
        for p in prods:
            c1 = p.get('category1', '') or ''
            c2 = p.get('category2', '') or ''
            c3 = p.get('category3', '') or ''
            # 전체 경로 조합
            parts = [x for x in [c1, c2, c3] if x]
            full_path = ' > '.join(parts) if parts else '기타'
            fullpath_map[full_path] = fullpath_map.get(full_path, 0) + 1
            if c1: cat1_map[c1] = cat1_map.get(c1, 0) + 1
            if c2: cat2_map[c2] = cat2_map.get(c2, 0) + 1
            if c3: cat3_map[c3] = cat3_map.get(c3, 0) + 1

        total = len(prods)
        # 전체 경로 분포
        categories = sorted([{'name': k, 'count': v, 'ratio': round(v / total * 100)} for k, v in fullpath_map.items()], key=lambda x: -x['count'])
        # 레벨별 분포
        cat1_list = sorted([{'name': k, 'count': v, 'ratio': round(v / total * 100)} for k, v in cat1_map.items()], key=lambda x: -x['count'])
        cat2_list = sorted([{'name': k, 'count': v, 'ratio': round(v / total * 100)} for k, v in cat2_map.items()], key=lambda x: -x['count'])
        cat3_list = sorted([{'name': k, 'count': v, 'ratio': round(v / total * 100)} for k, v in cat3_map.items()], key=lambda x: -x['count'])

        top_cat = categories[0] if categories else {'name': '-', 'ratio': 0}
        analysis['categoryAnalysis'] = {
            'verdict': f'{top_cat["name"]} 카테고리에 {top_cat["ratio"]}% 등록',
            'mainCategory': top_cat['name'],
            'categories': categories[:8],
            'categoryLevels': {
                'large': cat1_list[:5],
                'medium': cat2_list[:5],
                'small': cat3_list[:5],
            },
        }

    # 8. 키워드 태그
    if rd:
        all_kws = (rd.get('golden_keywords', []) + rd.get('related_keywords', []))[:15]
        analysis['keywordTags'] = {
            'topKeywords': [{'keyword': k['keyword'], 'volume': fmt(k.get('totalVolume', 0)), 'comp': comp_label(k.get('compIdx', '')), 'isGolden': k.get('isGolden', False)} for k in all_kws],
            'totalFound': rd.get('total_found', len(all_kws)),
        }

    # 9. 경쟁사 비교표
    if prods:
        analysis['competitorTable'] = []
        for p in prods[:20]:
            analysis['competitorTable'].append({
                'rank': p.get('rank', '-'), 'name': p.get('product_name', ''),
                'store': p.get('store_name', ''), 'price': fmt(p.get('price', 0)) + '원',
                'brand': p.get('brand', '-'),
                'category': ' > '.join([x for x in [p.get('category1',''), p.get('category2',''), p.get('category3','')] if x]) or '-',
            })

    # 10. 판매량 추정
    if prods and total_vol > 0:
        top10 = prods[:10]
        avg_p = round(sum(p.get('price', 0) for p in top10) / max(len(top10), 1))
        cv = 0.035
        analysis['salesEstimation'] = {
            'avgPrice': fmt(avg_p) + '원', 'monthlySearches': fmt(total_vol),
            'estimatedCTR': 'CTR × 3.5%',
            'simulations': [
                {'rank': 1, 'estSales': round(total_vol * 0.08 * cv), 'revenue': fmt(round(total_vol * 0.08 * cv * avg_p)) + '원'},
                {'rank': 5, 'estSales': round(total_vol * 0.03 * cv), 'revenue': fmt(round(total_vol * 0.03 * cv * avg_p)) + '원'},
                {'rank': 10, 'estSales': round(total_vol * 0.015 * cv), 'revenue': fmt(round(total_vol * 0.015 * cv * avg_p)) + '원'},
                {'rank': 15, 'estSales': round(total_vol * 0.010 * cv), 'revenue': fmt(round(total_vol * 0.010 * cv * avg_p)) + '원'},
                {'rank': 20, 'estSales': round(total_vol * 0.008 * cv), 'revenue': fmt(round(total_vol * 0.008 * cv * avg_p)) + '원'},
                {'rank': 25, 'estSales': round(total_vol * 0.006 * cv), 'revenue': fmt(round(total_vol * 0.006 * cv * avg_p)) + '원'},
                {'rank': 30, 'estSales': round(total_vol * 0.005 * cv), 'revenue': fmt(round(total_vol * 0.005 * cv * avg_p)) + '원'},
                {'rank': 35, 'estSales': round(total_vol * 0.004 * cv), 'revenue': fmt(round(total_vol * 0.004 * cv * avg_p)) + '원'},
                {'rank': 40, 'estSales': round(total_vol * 0.003 * cv), 'revenue': fmt(round(total_vol * 0.003 * cv * avg_p)) + '원'},
            ],
        }

    # 11. 진입 전략
    if len(prods) >= 10 and total_vol > 0:
        top5 = prods[:5]
        avg5 = round(sum(p.get('price', 0) for p in top5) / 5)
        prices5 = [p.get('price', 0) for p in top5]
        brands = {}
        for p in top5:
            b = p.get('brand') or p.get('store_name', '')
            brands[b] = brands.get(b, 0) + 1
        ci = analysis.get('competitionIndex', {})
        analysis['strategicAnalysis'] = {
            'avgTop5Price': fmt(avg5) + '원',
            'priceRange': fmt(min(prices5)) + '원 ~ ' + fmt(max(prices5)) + '원',
            'monthlyVolume': fmt(total_vol),
            'mainBrands': ', '.join(list(brands.keys())[:5]),
            'recommendation': '현재 시장은 블루오션입니다. 빠른 진입을 추천합니다.' if ci.get('compIndex', 1) < 0.5
                else ('경쟁이 적당합니다. 가격/리뷰 전략에 집중하세요.' if ci.get('compIndex', 1) < 1.0
                else '경쟁이 치열합니다. 차별화된 상세페이지와 리뷰 확보가 핵심입니다.'),
        }

    return analysis


# ==================== HTML 보고서 생성 ====================
def generate_html_report(keyword: str, company_name: str, analysis: dict,
                         vol_data: dict = None, related_data: dict = None) -> str:
    """분석 데이터로 HTML 보고서 생성 (분석 탭과 동일한 포맷)"""
    # XSS 방지
    keyword = html_module.escape(keyword)
    company_name = html_module.escape(company_name)
    date_str = datetime.now().strftime('%Y년 %m월 %d일')

    def fmt(n):
        try: return f"{int(n):,}"
        except (ValueError, TypeError): return str(n)

    sections_html = []

    # 종합 요약
    sc = analysis.get('summaryCards', {})
    if sc:
        sections_html.append(f'''
        <div class="section">
            <h2>📊 종합 요약</h2>
            <div class="card-row">
                <div class="stat-card blue"><div class="label">월간 검색량</div><div class="value">{sc.get('totalVolume','-')}</div></div>
                <div class="stat-card green"><div class="label">상품 수</div><div class="value">{sc.get('productCount','-')}</div></div>
                <div class="stat-card purple"><div class="label">경쟁강도</div><div class="value">{sc.get('compLevel','-')}</div></div>
                <div class="stat-card orange"><div class="label">골든키워드</div><div class="value">{sc.get('goldenCount',0)}개</div></div>
            </div>
        </div>''')

    # 경쟁강도
    ci = analysis.get('competitionIndex', {})
    if ci:
        sections_html.append(f'''
        <div class="section">
            <h2>🔥 경쟁강도 분석</h2>
            <div class="info-box">
                <div class="metric"><span>경쟁지수</span><strong style="color:{ci.get('compColor','#333')}">{ci.get('compIndex','-')}</strong></div>
                <div class="metric"><span>경쟁수준</span><strong style="color:{ci.get('compColor','#333')}">{ci.get('compLabel','-')} ({ci.get('compPercent',0)}%)</strong></div>
                <div class="metric"><span>상품 수</span><strong>{fmt(ci.get('productCount',0))}</strong></div>
                <div class="metric"><span>검색량</span><strong>{fmt(ci.get('searchVolume',0))}</strong></div>
            </div>
            <p class="comment">{ci.get('interpretation','')}</p>
        </div>''')

    # 시장 규모
    mr = analysis.get('marketRevenue', {})
    if mr:
        sections_html.append(f'''
        <div class="section">
            <h2>💰 시장 규모 추정</h2>
            <div class="info-box">
                <div class="metric"><span>평균 가격</span><strong>{mr.get('avgPrice','-')}</strong></div>
                <div class="metric"><span>예상 월 시장</span><strong>{mr.get('estimatedMonthly','-')}</strong></div>
                <div class="metric"><span>전환율</span><strong>{mr.get('conversionRate','-')}</strong></div>
            </div>
        </div>''')

    # 광고 정보
    ai = analysis.get('advertiserInfo', {})
    if ai:
        sections_html.append(f'''
        <div class="section">
            <h2>📢 광고 경쟁 정보</h2>
            <div class="info-box">
                <div class="metric"><span>광고 경쟁강도</span><strong>{ai.get('compIdx','-')}</strong></div>
                <div class="metric"><span>노출 깊이</span><strong>{ai.get('adDepth','-')}</strong></div>
                <div class="metric"><span>PC 클릭</span><strong>{ai.get('pcClicks','-')}회</strong></div>
                <div class="metric"><span>모바일 클릭</span><strong>{ai.get('mobileClicks','-')}회</strong></div>
            </div>
        </div>''')

    # 골든 키워드
    gk = analysis.get('goldenKeyword', {})
    if gk:
        sections_html.append(f'''
        <div class="section">
            <h2>🏆 골든 키워드</h2>
            <div class="golden-box">
                <div class="golden-name">{gk.get('name','')}</div>
                <div class="golden-detail">검색량 {fmt(gk.get('volume',0))}회 | 경쟁 {gk.get('competition','-')}</div>
                <p>{gk.get('reason','')}</p>
            </div>
        </div>''')

    # 경쟁사 비교표
    ct = analysis.get('competitorTable', [])
    if ct:
        rows = ''
        for p in ct:
            rows += f'<tr><td>{p.get("rank","")}</td><td>{p.get("name","")[:30]}</td><td>{p.get("store","")}</td><td>{p.get("price","")}</td><td>{p.get("brand","")}</td><td>{p.get("category","")}</td></tr>'
        sections_html.append(f'''
        <div class="section">
            <h2>🏪 경쟁사 비교 (상위 20)</h2>
            <table><thead><tr><th>순위</th><th>상품명</th><th>스토어</th><th>가격</th><th>브랜드</th><th>카테고리</th></tr></thead>
            <tbody>{rows}</tbody></table>
        </div>''')

    # 판매량 추정
    se = analysis.get('salesEstimation', {})
    if se:
        sim_rows = ''
        for s in se.get('simulations', []):
            sim_rows += f'<tr><td>{s["rank"]}위</td><td>{s["estSales"]}건</td><td>{s["revenue"]}</td></tr>'
        sections_html.append(f'''
        <div class="section">
            <h2>📈 판매량 추정 시뮬레이션</h2>
            <div class="info-box">
                <div class="metric"><span>평균 가격</span><strong>{se.get('avgPrice','')}</strong></div>
                <div class="metric"><span>월 검색량</span><strong>{se.get('monthlySearches','')}</strong></div>
            </div>
            <table><thead><tr><th>목표 순위</th><th>예상 판매</th><th>예상 매출</th></tr></thead>
            <tbody>{sim_rows}</tbody></table>
        </div>''')

    # 진입 전략
    sa = analysis.get('strategicAnalysis', {})
    if sa:
        sections_html.append(f'''
        <div class="section">
            <h2>🎯 1페이지 진입 전략</h2>
            <div class="info-box">
                <div class="metric"><span>상위5 평균가</span><strong>{sa.get('avgTop5Price','')}</strong></div>
                <div class="metric"><span>가격 범위</span><strong>{sa.get('priceRange','')}</strong></div>
                <div class="metric"><span>월 검색량</span><strong>{sa.get('monthlyVolume','')}</strong></div>
                <div class="metric"><span>주요 브랜드</span><strong>{sa.get('mainBrands','')}</strong></div>
            </div>
            <p class="comment">{sa.get('recommendation','')}</p>
        </div>''')

    # 카테고리 분석
    ca = analysis.get('categoryAnalysis', {})
    if ca:
        cat_items = ''.join(f'<span class="tag">{c["name"]} ({c["ratio"]}%)</span>' for c in ca.get('categories', []))
        sections_html.append(f'''
        <div class="section">
            <h2>📂 카테고리 분석</h2>
            <p><strong>{ca.get('verdict','')}</strong></p>
            <div class="tags">{cat_items}</div>
        </div>''')

    # 키워드 태그
    kt = analysis.get('keywordTags', {})
    if kt:
        kw_items = ''.join(
            f'<span class="tag {"golden" if k.get("isGolden") else ""}">{k["keyword"]} ({k["volume"]})</span>'
            for k in kt.get('topKeywords', [])
        )
        sections_html.append(f'''
        <div class="section">
            <h2>🏷️ 연관 키워드 ({kt.get('totalFound',0)}개)</h2>
            <div class="tags">{kw_items}</div>
        </div>''')

    body = '\n'.join(sections_html)
    title_name = f'{company_name} - ' if company_name else ''

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_name}{keyword} 키워드 분석 보고서 - {date_str}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif; background:#f8fafc; color:#1e293b; line-height:1.6; }}
.report-header {{ background:linear-gradient(135deg,#6C5CE7,#a29bfe); color:#fff; padding:50px 20px; text-align:center; }}
.report-header h1 {{ font-size:28px; margin-bottom:8px; }}
.report-header p {{ font-size:14px; opacity:0.85; }}
.container {{ max-width:1100px; margin:0 auto; padding:20px; }}
.section {{ background:#fff; border-radius:14px; padding:24px 28px; margin-bottom:20px; box-shadow:0 1px 3px rgba(0,0,0,0.06); }}
.section h2 {{ font-size:18px; font-weight:700; margin-bottom:16px; color:#1e293b; }}
.card-row {{ display:flex; gap:12px; flex-wrap:wrap; }}
.stat-card {{ flex:1; min-width:140px; border-radius:12px; padding:20px; text-align:center; }}
.stat-card .label {{ font-size:12px; color:#64748b; margin-bottom:4px; }}
.stat-card .value {{ font-size:26px; font-weight:700; }}
.stat-card.blue {{ background:#eff6ff; color:#1d4ed8; }}
.stat-card.green {{ background:#f0fdf4; color:#16a34a; }}
.stat-card.purple {{ background:#faf5ff; color:#7c3aed; }}
.stat-card.orange {{ background:#fff7ed; color:#ea580c; }}
.info-box {{ display:flex; gap:20px; flex-wrap:wrap; margin-bottom:12px; }}
.metric {{ flex:1; min-width:120px; }}
.metric span {{ display:block; font-size:12px; color:#94a3b8; }}
.metric strong {{ font-size:16px; }}
.comment {{ font-size:14px; color:#475569; line-height:1.7; margin-top:10px; padding:14px; background:#f8fafc; border-radius:8px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#f1f5f9; padding:10px 12px; text-align:left; font-weight:600; color:#475569; border-bottom:2px solid #e2e8f0; }}
td {{ padding:10px 12px; border-bottom:1px solid #f1f5f9; word-break:break-all; }}
tr:hover {{ background:#fafbfc; }}
.url-wrap {{ word-break:break-all; overflow-wrap:break-word; max-width:100%; }}
.golden-box {{ background:linear-gradient(135deg,#fef3c7,#fde68a); border-radius:12px; padding:20px; }}
.golden-name {{ font-size:22px; font-weight:700; color:#92400e; margin-bottom:6px; }}
.golden-detail {{ font-size:13px; color:#a16207; margin-bottom:10px; }}
.golden-box p {{ font-size:13px; color:#78350f; line-height:1.6; }}
.tags {{ display:flex; gap:8px; flex-wrap:wrap; }}
.tag {{ padding:6px 14px; border-radius:20px; font-size:12px; background:#f1f5f9; color:#475569; }}
.tag.golden {{ background:#fef3c7; color:#92400e; font-weight:600; }}
.report-footer {{ text-align:center; padding:30px; color:#94a3b8; font-size:12px; border-top:1px solid #e2e8f0; margin-top:20px; }}
@media print {{ .report-header {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }} }}
</style>
</head>
<body>
<div class="report-header">
<h1>{title_name}{keyword} 키워드 분석 보고서</h1>
<p>{date_str} | 메타아이앤씨 로직 분석 시스템 (자동 생성)</p>
</div>
<div class="container">
{body}
</div>
<div class="report-footer">
<p>&copy; 2026 메타아이앤씨 &mdash; 로직 분석 시스템 | 매일 새벽 자동 분석 보고서</p>
</div>
</body>
</html>'''


# ==================== 전체 분석 실행 (스케줄러에서 호출) ====================
def run_single_analysis(client_id: int, client_name: str, keyword: str, product_url: str = '',
                        cached_prods: list = None, cached_total: int = 0, cached_vol: dict = None,
                        cached_related: dict = None) -> dict:
    """단일 키워드 전체 분석 → DB 저장까지 (스케줄러에서 호출)

    cached_prods/cached_total/cached_vol/cached_related가 제공되면
    해당 데이터를 재사용하여 API 호출을 건너뜀 (통합 스케줄러용)
    """
    import sqlite3, os

    from naver_crawler import get_keyword_volume, search_products, find_product_rank

    DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
    today = datetime.now().strftime('%Y-%m-%d')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1. 검색량 조회 (캐시 없으면 API 호출)
    vol_data = cached_vol or {}
    if not vol_data:
        try:
            vol_list = get_keyword_volume([keyword])
            if vol_list and len(vol_list) > 0:
                vol_data = vol_list[0]
        except Exception as e:
            logger.warning(f"  [{keyword}] 검색량 조회 실패: {e}")
        time.sleep(1)

    # 2. 상품 검색 (캐시 없으면 API 호출)
    prods = cached_prods if cached_prods is not None else []
    total_shop_products = cached_total if cached_total > 0 else 0
    if cached_prods is None:
        try:
            from naver_crawler import search_naver_shopping_api, _parse_api_item
            shop_result = search_naver_shopping_api(keyword, display=40)
            total_shop_products = shop_result.get("total", 0)
            items = shop_result.get("items", [])
            prods = [_parse_api_item(item, idx + 1) for idx, item in enumerate(items)]
        except Exception as e:
            logger.warning(f"  [{keyword}] 상품 검색 실패: {e}")
        time.sleep(1)

    # 3. 연관 키워드 (캐시 없으면 API 호출)
    related_data = cached_related or {}
    if not related_data:
        try:
            related_data = get_related_keywords(keyword)
        except Exception as e:
            logger.warning(f"  [{keyword}] 연관 키워드 조회 실패: {e}")
        time.sleep(1)

    # 4. 전체 분석 계산 (App.jsx handleSearch 동일, 네이버 API total 전달)
    analysis = compute_full_analysis(keyword, vol_data, prods, related_data,
                                     total_shop_products=total_shop_products)

    # 5. HTML 보고서 생성
    report_html = generate_html_report(keyword, client_name, analysis, vol_data, related_data)

    # 6. DB 저장 (UPSERT)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")

        existing = conn.execute(
            "SELECT id FROM client_analyses WHERE client_id=? AND keyword=? AND analyzed_date=?",
            (client_id, keyword, today)
        ).fetchone()

        params = (
            product_url,
            json.dumps(analysis, ensure_ascii=False),
            json.dumps(vol_data, ensure_ascii=False),
            json.dumps(related_data, ensure_ascii=False),
            json.dumps(prods[:20] if prods else [], ensure_ascii=False),
            json.dumps({}, ensure_ascii=False),  # advertiser_json — 자동분석에는 광고주 데이터 없음
            report_html,
            now,
        )

        if existing:
            conn.execute("""
                UPDATE client_analyses SET product_url=?, analysis_json=?, volume_json=?,
                    related_json=?, shop_products_json=?, advertiser_json=?,
                    report_html=?, updated_at=?
                WHERE client_id=? AND keyword=? AND analyzed_date=?
            """, params + (client_id, keyword, today))
        else:
            conn.execute("""
                INSERT INTO client_analyses
                (client_id, keyword, product_url, analysis_json, volume_json,
                 related_json, shop_products_json, advertiser_json, report_html,
                 analyzed_date, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (client_id, keyword) + params[:7] + (today, now, now))

        # 순위 추적 (당일 중복 방지 — 일자별 1회 원칙)
        # cached_prods가 있으면 캐시에서 순위 검색 (API 호출 없음)
        if product_url and prods:
            try:
                existing_rank = conn.execute(
                    """SELECT id FROM client_rank_history
                       WHERE client_id=? AND keyword=? AND DATE(checked_at)=?""",
                    (client_id, keyword, today)
                ).fetchone()

                if not existing_rank:
                    if cached_prods is not None:
                        from naver_crawler import find_product_rank_from_cache
                        rank, page, _ = find_product_rank_from_cache(keyword, product_url, prods)
                    else:
                        rank, page, _ = find_product_rank(keyword, product_url, max_pages=2)
                    if rank:
                        conn.execute("""
                            INSERT INTO client_rank_history
                            (client_id, keyword, product_url, rank_position, page_number, check_type, checked_at)
                            VALUES (?, ?, ?, ?, ?, 'scheduled', ?)
                        """, (client_id, keyword, product_url, rank, page, now))
                else:
                    logger.info(f"  [{keyword}] 오늘 순위 기록 이미 존재 — 스킵")
            except Exception as e:
                logger.warning(f"  [{keyword}] 순위 추적 실패: {e}")
            if cached_prods is None:
                time.sleep(1)

        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"  [{keyword}] DB 저장 실패: {e}")
        raise
    finally:
        conn.close()

    return {
        'keyword': keyword,
        'total_vol': analysis.get('summaryCards', {}).get('totalVolume', 0),
        'product_count': len(prods),
        'has_report': bool(report_html),
    }
