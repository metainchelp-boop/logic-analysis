"""
ai_insights.py — AI 자기학습 인사이트 모듈
8개 기능: 가격 최적화, 키워드 발굴, 리뷰 감성, 광고 효율, 등록 타이밍,
         업체 성과 패턴, 경쟁사 이상 감지, 순위 예측
"""
import os
import json
import logging
import sqlite3
from datetime import datetime, timedelta, date
from collections import defaultdict
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ==================== ① 가격 최적화 추천 ====================
def get_price_optimization(client_id: int, keyword: str) -> Optional[Dict]:
    """경쟁 상품 가격 분석 기반 최적 가격대 추천"""
    conn = _get_conn()
    try:
        # 최근 분석의 shop_products_json 조회
        row = conn.execute("""
            SELECT shop_products_json, analysis_json
            FROM client_analyses
            WHERE client_id = ? AND keyword = ? AND shop_products_json IS NOT NULL
            ORDER BY analyzed_date DESC LIMIT 1
        """, (client_id, keyword)).fetchone()

        if not row or not row['shop_products_json']:
            return None

        products = json.loads(row['shop_products_json'])
        if not products or len(products) < 3:
            return None

        # 상위 상품 가격 분석
        prices = []
        for p in products:
            price = p.get('lprice') or p.get('price') or p.get('hprice')
            if price:
                try:
                    prices.append(int(str(price).replace(',', '')))
                except (ValueError, TypeError):
                    continue

        if len(prices) < 3:
            return None

        prices.sort()
        top5_prices = prices[:5]
        top10_prices = prices[:10]
        top20_prices = prices[:20]

        avg_top5 = sum(top5_prices) / len(top5_prices)
        avg_top10 = sum(top10_prices) / len(top10_prices)
        median = prices[len(prices) // 2]

        # 가격대 구간 분석
        low_range = int(prices[0] * 0.9)
        high_range = int(prices[min(9, len(prices) - 1)] * 1.1)

        # 추천 전략 결정
        if avg_top5 < avg_top10 * 0.8:
            strategy = "저가 전략"
            strategy_desc = "상위 5개 상품이 전체 평균보다 20% 이상 저렴합니다. 가격 경쟁력이 순위에 큰 영향을 미치는 카테고리입니다."
        elif avg_top5 > avg_top10 * 1.2:
            strategy = "프리미엄 전략"
            strategy_desc = "상위 상품들이 높은 가격대를 형성하고 있습니다. 품질/브랜드 중심의 프리미엄 전략이 유효합니다."
        else:
            strategy = "중간가 전략"
            strategy_desc = "상위 상품들의 가격이 고르게 분포되어 있습니다. 적정 가격에 리뷰/서비스 차별화가 중요합니다."

        return {
            "keyword": keyword,
            "recommendedRange": {"low": low_range, "high": high_range},
            "avgTop5": int(avg_top5),
            "avgTop10": int(avg_top10),
            "median": int(median),
            "minPrice": prices[0],
            "maxPrice": prices[-1],
            "strategy": strategy,
            "strategyDesc": strategy_desc,
            "sampleSize": len(prices),
        }
    except Exception as e:
        logger.error(f"[가격최적화] {e}")
        return None
    finally:
        conn.close()


# ==================== ② 키워드 자동 발굴 ====================
def get_keyword_recommendations(client_id: int) -> Optional[Dict]:
    """기존 분석 데이터 기반 신규 키워드 추천"""
    conn = _get_conn()
    try:
        # 이 업체의 기존 키워드 조회
        rows = conn.execute("""
            SELECT keyword, analysis_json, volume_json, analyzed_date
            FROM client_analyses
            WHERE client_id = ?
            ORDER BY analyzed_date DESC
        """, (client_id,)).fetchall()

        if not rows:
            return None

        existing_keywords = set()
        keyword_volumes = {}
        related_keywords_pool = defaultdict(lambda: {"count": 0, "totalVolume": 0})

        for row in rows:
            kw = row['keyword']
            existing_keywords.add(kw)

            # 검색량 추출
            if row['volume_json']:
                try:
                    vol = json.loads(row['volume_json'])
                    if isinstance(vol, list) and vol:
                        v = vol[0]
                        total = (v.get('monthlyPcQcCnt', 0) or 0) + (v.get('monthlyMobileQcCnt', 0) or 0)
                        keyword_volumes[kw] = total
                except (json.JSONDecodeError, TypeError):
                    pass

            # 연관 키워드 추출
            if row['analysis_json']:
                try:
                    analysis = json.loads(row['analysis_json'])
                    related = analysis.get('relatedKeywords', [])
                    for rk in related:
                        rk_name = rk.get('keyword', rk.get('relKeyword', ''))
                        if rk_name and rk_name not in existing_keywords:
                            vol = rk.get('totalVolume', 0) or rk.get('monthlyPcQcCnt', 0) or 0
                            related_keywords_pool[rk_name]["count"] += 1
                            related_keywords_pool[rk_name]["totalVolume"] = max(
                                related_keywords_pool[rk_name]["totalVolume"], vol
                            )
                except (json.JSONDecodeError, TypeError):
                    pass

        # 추천 키워드 선별: 여러 분석에서 반복 등장하고 검색량 높은 것
        candidates = []
        for kw, info in related_keywords_pool.items():
            if info["count"] >= 1 and info["totalVolume"] > 0:
                score = info["count"] * 0.4 + (info["totalVolume"] / 1000) * 0.6
                candidates.append({
                    "keyword": kw,
                    "volume": info["totalVolume"],
                    "appearances": info["count"],
                    "score": round(score, 1),
                })

        candidates.sort(key=lambda x: -x["score"])

        # 고검색량 미사용 키워드
        high_volume = [c for c in candidates if c["volume"] >= 5000][:5]
        # 자주 등장하는 연관 키워드
        frequent = sorted(candidates, key=lambda x: -x["appearances"])[:5]
        # 종합 추천
        top_recommended = candidates[:10]

        return {
            "existingCount": len(existing_keywords),
            "candidateCount": len(candidates),
            "topRecommended": top_recommended,
            "highVolume": high_volume,
            "frequent": frequent,
        }
    except Exception as e:
        logger.error(f"[키워드발굴] {e}")
        return None
    finally:
        conn.close()


# ==================== ③ 리뷰 감성 변화 추적 ====================
# 간단한 한국어 감성 사전
_POSITIVE_WORDS = [
    '좋아', '좋은', '최고', '만족', '추천', '맛있', '신선', '빠른', '깔끔', '친절',
    '훌륭', '대박', '완벽', '감동', '재구매', '또 구매', '또 시킬', '또 살', '강추',
    '괜찮', '적당', '합리', '가성비', '알찬', '든든', '풍부', '부드러', '고소',
]
_NEGATIVE_WORDS = [
    '별로', '실망', '아쉬', '불만', '교환', '환불', '반품', '늦', '느리', '불친절',
    '비싸', '작은', '적은', '부족', '상태', '훼손', '파손', '변질', '곰팡이', '냄새',
    '찜찜', '짜증', '화나', '최악', '다시.*않', '비추', '후회',
]


def _analyze_sentiment(text: str) -> str:
    """간단한 감성 분류: positive / negative / neutral"""
    if not text:
        return "neutral"
    text_lower = text.lower()
    pos_count = sum(1 for w in _POSITIVE_WORDS if w in text_lower)
    neg_count = sum(1 for w in _NEGATIVE_WORDS if w in text_lower)
    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    return "neutral"


def get_review_sentiment_trend(client_id: int, keyword: str) -> Optional[Dict]:
    """분석 이력 기반 리뷰 감성 변화 추적"""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT analyzed_date, analysis_json
            FROM client_analyses
            WHERE client_id = ? AND keyword = ? AND analysis_json IS NOT NULL
            ORDER BY analyzed_date ASC
        """, (client_id, keyword)).fetchall()

        if not rows:
            return None

        trend = []
        for row in rows:
            try:
                analysis = json.loads(row['analysis_json'])
                reviews = analysis.get('reviews', [])
                if not reviews:
                    continue

                sentiments = {"positive": 0, "negative": 0, "neutral": 0}
                for review in reviews:
                    text = review.get('content', '') or review.get('text', '')
                    sentiment = _analyze_sentiment(text)
                    sentiments[sentiment] += 1

                total = sum(sentiments.values())
                if total > 0:
                    trend.append({
                        "date": row['analyzed_date'],
                        "positive": sentiments["positive"],
                        "negative": sentiments["negative"],
                        "neutral": sentiments["neutral"],
                        "total": total,
                        "positiveRate": round(sentiments["positive"] / total * 100, 1),
                        "negativeRate": round(sentiments["negative"] / total * 100, 1),
                    })
            except (json.JSONDecodeError, TypeError):
                continue

        if not trend:
            return None

        # 최근 vs 이전 비교
        latest = trend[-1] if trend else None
        alert = None
        if len(trend) >= 2:
            prev_neg_rate = trend[-2]["negativeRate"]
            curr_neg_rate = trend[-1]["negativeRate"]
            if curr_neg_rate > prev_neg_rate + 15:
                alert = f"부정 리뷰 비율이 {prev_neg_rate}%에서 {curr_neg_rate}%로 급증했습니다."
            elif curr_neg_rate < prev_neg_rate - 15:
                alert = f"부정 리뷰 비율이 {prev_neg_rate}%에서 {curr_neg_rate}%로 개선되었습니다."

        return {
            "keyword": keyword,
            "trend": trend,
            "latest": latest,
            "alert": alert,
            "dataPoints": len(trend),
        }
    except Exception as e:
        logger.error(f"[리뷰감성] {e}")
        return None
    finally:
        conn.close()


# ==================== ④ 광고 효율 예측 ====================
def get_ad_efficiency(client_id: int, keyword: str) -> Optional[Dict]:
    """검색량 × 경쟁강도 × 순위 기반 광고 효율 분석"""
    conn = _get_conn()
    try:
        # 최근 분석 데이터
        row = conn.execute("""
            SELECT analysis_json, volume_json
            FROM client_analyses
            WHERE client_id = ? AND keyword = ? AND volume_json IS NOT NULL
            ORDER BY analyzed_date DESC LIMIT 1
        """, (client_id, keyword)).fetchone()

        if not row:
            return None

        volume_data = {}
        try:
            vol_list = json.loads(row['volume_json'])
            if isinstance(vol_list, list) and vol_list:
                volume_data = vol_list[0]
        except (json.JSONDecodeError, TypeError):
            return None

        pc_vol = volume_data.get('monthlyPcQcCnt', 0) or 0
        mobile_vol = volume_data.get('monthlyMobileQcCnt', 0) or 0
        total_volume = pc_vol + mobile_vol
        comp_idx = volume_data.get('compIdx', '') or ''
        pc_clicks = volume_data.get('monthlyAvePcClkCnt', 0) or 0
        mobile_clicks = volume_data.get('monthlyAveMoClkCnt', 0) or 0
        total_clicks = pc_clicks + mobile_clicks

        if total_volume == 0:
            return None

        # 경쟁 강도 점수화
        comp_score_map = {"높음": 3, "중간": 2, "낮음": 1}
        comp_score = comp_score_map.get(comp_idx, 2)

        # 클릭률 계산
        ctr = round(total_clicks / total_volume * 100, 2) if total_volume > 0 else 0

        # 최근 순위 조회
        rank_row = conn.execute("""
            SELECT rank_position FROM client_rank_history
            WHERE client_id = ? AND keyword = ? AND rank_position IS NOT NULL
            ORDER BY checked_at DESC LIMIT 1
        """, (client_id, keyword)).fetchone()

        current_rank = rank_row['rank_position'] if rank_row else None

        # 효율 점수 계산 (0~100)
        # 높은 검색량 + 낮은 경쟁 + 좋은 순위 = 높은 효율
        volume_score = min(total_volume / 10000 * 30, 30)  # 최대 30점
        comp_penalty = comp_score * 10  # 경쟁 높을수록 감점
        rank_score = 0
        if current_rank and current_rank <= 400:
            rank_score = max(0, (400 - current_rank) / 400 * 40)  # 최대 40점

        efficiency = round(volume_score - comp_penalty + rank_score + ctr * 2, 1)
        efficiency = max(0, min(100, efficiency))

        # 등급 판정
        if efficiency >= 70:
            grade = "A"
            advice = "효율이 매우 높은 키워드입니다. 광고 예산을 유지하거나 확대하세요."
        elif efficiency >= 50:
            grade = "B"
            advice = "적정 수준의 효율입니다. 순위 개선에 집중하면 효율이 크게 올라갈 수 있습니다."
        elif efficiency >= 30:
            grade = "C"
            advice = "효율이 낮은 편입니다. 경쟁이 치열하다면 롱테일 키워드로 전환을 고려하세요."
        else:
            grade = "D"
            advice = "광고 효율이 매우 낮습니다. 다른 키워드로 예산 재배분을 권장합니다."

        return {
            "keyword": keyword,
            "totalVolume": total_volume,
            "competition": comp_idx,
            "currentRank": current_rank,
            "ctr": ctr,
            "efficiencyScore": efficiency,
            "grade": grade,
            "advice": advice,
            "breakdown": {
                "volumeScore": round(volume_score, 1),
                "compPenalty": comp_penalty,
                "rankScore": round(rank_score, 1),
                "ctrBonus": round(ctr * 2, 1),
            },
        }
    except Exception as e:
        logger.error(f"[광고효율] {e}")
        return None
    finally:
        conn.close()


# ==================== ⑤ 최적 등록 타이밍 ====================
def get_optimal_timing(client_id: int, keyword: str) -> Optional[Dict]:
    """요일별 검색 패턴 + 순위 변동 기반 최적 등록 타이밍 추천"""
    conn = _get_conn()
    try:
        # 순위 이력에서 요일별 패턴 분석
        rows = conn.execute("""
            SELECT checked_at, rank_position
            FROM client_rank_history
            WHERE client_id = ? AND keyword = ? AND rank_position IS NOT NULL
            ORDER BY checked_at ASC
        """, (client_id, keyword)).fetchall()

        if len(rows) < 3:
            return {"keyword": keyword, "message": "데이터 부족 — 3일 이상 순위 이력이 필요합니다.", "ready": False}

        # 요일별 평균 순위
        weekday_names = ['월', '화', '수', '목', '금', '토', '일']
        weekday_ranks = defaultdict(list)
        for row in rows:
            try:
                dt = datetime.strptime(row['checked_at'][:10], '%Y-%m-%d')
                weekday_ranks[dt.weekday()].append(row['rank_position'])
            except (ValueError, TypeError):
                continue

        if not weekday_ranks:
            return None

        weekday_avg = {}
        for wd, ranks in weekday_ranks.items():
            weekday_avg[wd] = round(sum(ranks) / len(ranks), 1)

        # 최적 요일 = 평균 순위가 가장 좋은(낮은) 요일
        best_day = min(weekday_avg, key=weekday_avg.get)
        worst_day = max(weekday_avg, key=weekday_avg.get)

        # 순위 변동 패턴
        rank_changes = []
        for i in range(1, len(rows)):
            prev_rank = rows[i - 1]['rank_position']
            curr_rank = rows[i]['rank_position']
            if prev_rank and curr_rank:
                rank_changes.append(prev_rank - curr_rank)  # 양수 = 순위 상승

        avg_volatility = round(sum(abs(c) for c in rank_changes) / len(rank_changes), 1) if rank_changes else 0

        weekday_data = []
        for wd in range(7):
            if wd in weekday_avg:
                weekday_data.append({
                    "day": weekday_names[wd],
                    "avgRank": weekday_avg[wd],
                    "dataCount": len(weekday_ranks[wd]),
                    "isBest": wd == best_day,
                    "isWorst": wd == worst_day,
                })

        return {
            "keyword": keyword,
            "ready": True,
            "bestDay": weekday_names[best_day],
            "bestDayRank": weekday_avg[best_day],
            "worstDay": weekday_names[worst_day],
            "worstDayRank": weekday_avg[worst_day],
            "volatility": avg_volatility,
            "weekdayData": weekday_data,
            "advice": f"{weekday_names[best_day]}요일에 평균 순위가 가장 좋습니다({weekday_avg[best_day]}위). 상품 등록/수정은 {weekday_names[best_day]}요일 이전에 완료하는 것을 권장합니다.",
            "totalDataPoints": len(rows),
        }
    except Exception as e:
        logger.error(f"[등록타이밍] {e}")
        return None
    finally:
        conn.close()


# ==================== ⑥ 업체별 성과 패턴 학습 ====================
def get_client_performance_pattern(client_id: int) -> Optional[Dict]:
    """업체의 분석 이력 기반 성과 패턴 분석"""
    conn = _get_conn()
    try:
        # 분석 이력 조회
        analyses = conn.execute("""
            SELECT keyword, analyzed_date, volume_json, analysis_json
            FROM client_analyses
            WHERE client_id = ?
            ORDER BY analyzed_date ASC
        """, (client_id,)).fetchall()

        # 순위 이력 조회
        ranks = conn.execute("""
            SELECT keyword, rank_position, checked_at
            FROM client_rank_history
            WHERE client_id = ? AND rank_position IS NOT NULL
            ORDER BY checked_at ASC
        """, (client_id,)).fetchall()

        if not analyses and not ranks:
            return None

        # 키워드별 성과 추이
        keyword_performance = defaultdict(lambda: {
            "volumes": [], "ranks": [], "dates": [],
            "first_rank": None, "latest_rank": None
        })

        for row in ranks:
            kw = row['keyword']
            keyword_performance[kw]["ranks"].append(row['rank_position'])
            keyword_performance[kw]["dates"].append(row['checked_at'])
            if keyword_performance[kw]["first_rank"] is None:
                keyword_performance[kw]["first_rank"] = row['rank_position']
            keyword_performance[kw]["latest_rank"] = row['rank_position']

        for row in analyses:
            kw = row['keyword']
            if row['volume_json']:
                try:
                    vol = json.loads(row['volume_json'])
                    if isinstance(vol, list) and vol:
                        total = (vol[0].get('monthlyPcQcCnt', 0) or 0) + (vol[0].get('monthlyMobileQcCnt', 0) or 0)
                        keyword_performance[kw]["volumes"].append(total)
                except (json.JSONDecodeError, TypeError):
                    pass

        # 키워드별 성과 요약
        keyword_summaries = []
        improving = 0
        declining = 0
        stable = 0

        for kw, perf in keyword_performance.items():
            first = perf["first_rank"]
            latest = perf["latest_rank"]
            ranks_list = perf["ranks"]

            if first and latest and len(ranks_list) >= 2:
                change = first - latest  # 양수 = 순위 상승
                avg_rank = round(sum(ranks_list) / len(ranks_list), 1)
                best_rank = min(ranks_list)
                worst_rank = max(ranks_list)

                if change > 5:
                    trend = "상승"
                    improving += 1
                elif change < -5:
                    trend = "하락"
                    declining += 1
                else:
                    trend = "유지"
                    stable += 1

                keyword_summaries.append({
                    "keyword": kw,
                    "firstRank": first,
                    "latestRank": latest,
                    "change": change,
                    "trend": trend,
                    "avgRank": avg_rank,
                    "bestRank": best_rank,
                    "worstRank": worst_rank,
                    "dataPoints": len(ranks_list),
                    "avgVolume": round(sum(perf["volumes"]) / len(perf["volumes"])) if perf["volumes"] else None,
                })

        keyword_summaries.sort(key=lambda x: -abs(x["change"]))

        # 전체 성과 요약
        total_keywords = len(keyword_performance)
        analysis_days = len(set(r['analyzed_date'] for r in analyses)) if analyses else 0

        return {
            "totalKeywords": total_keywords,
            "analysisDays": analysis_days,
            "improving": improving,
            "declining": declining,
            "stable": stable,
            "keywordSummaries": keyword_summaries[:10],  # 상위 10개
            "overallTrend": "상승세" if improving > declining else ("하락세" if declining > improving else "안정"),
            "advice": _generate_performance_advice(improving, declining, stable, keyword_summaries),
        }
    except Exception as e:
        logger.error(f"[성과패턴] {e}")
        return None
    finally:
        conn.close()


def _generate_performance_advice(improving, declining, stable, summaries):
    """성과 기반 맞춤 조언 생성"""
    if not summaries:
        return "아직 충분한 데이터가 없습니다. 분석을 계속 진행하면 성과 패턴이 드러납니다."

    advice_parts = []
    if improving > declining:
        advice_parts.append(f"전체적으로 순위가 상승 추세입니다 ({improving}개 키워드 상승).")
    elif declining > improving:
        declining_kws = [s["keyword"] for s in summaries if s["trend"] == "하락"][:3]
        advice_parts.append(f"순위 하락 키워드({declining}개)에 주의가 필요합니다: {', '.join(declining_kws)}")

    # 가장 성과 좋은 키워드
    best = [s for s in summaries if s["trend"] == "상승"]
    if best:
        advice_parts.append(f"가장 성과가 좋은 키워드: '{best[0]['keyword']}' ({best[0]['change']}순위 상승)")

    return " ".join(advice_parts) if advice_parts else "안정적인 순위를 유지 중입니다."


# ==================== ⑦ 경쟁사 이상 감지 ====================
def get_competitor_alerts(client_id: int) -> Optional[Dict]:
    """상위 경쟁 상품 변동 감지"""
    conn = _get_conn()
    try:
        # 이 업체의 키워드 목록
        keywords = conn.execute("""
            SELECT DISTINCT keyword FROM client_analyses WHERE client_id = ?
        """, (client_id,)).fetchall()

        if not keywords:
            return None

        alerts = []

        for kw_row in keywords:
            keyword = kw_row['keyword']

            # 최근 2개 분석의 shop_products_json 비교
            recent = conn.execute("""
                SELECT analyzed_date, shop_products_json
                FROM client_analyses
                WHERE client_id = ? AND keyword = ? AND shop_products_json IS NOT NULL
                ORDER BY analyzed_date DESC LIMIT 2
            """, (client_id, keyword)).fetchall()

            if len(recent) < 2:
                continue

            try:
                curr_products = json.loads(recent[0]['shop_products_json'])
                prev_products = json.loads(recent[1]['shop_products_json'])
            except (json.JSONDecodeError, TypeError):
                continue

            if not curr_products or not prev_products:
                continue

            # 상위 10개 상품 비교
            curr_top10 = {p.get('productId', p.get('product_id', '')): p for p in curr_products[:10]}
            prev_top10 = {p.get('productId', p.get('product_id', '')): p for p in prev_products[:10]}

            curr_ids = set(curr_top10.keys())
            prev_ids = set(prev_top10.keys())

            # 신규 진입 상품
            new_entries = curr_ids - prev_ids
            for pid in new_entries:
                if pid:
                    p = curr_top10[pid]
                    alerts.append({
                        "keyword": keyword,
                        "type": "new_entry",
                        "severity": "warning",
                        "message": f"'{keyword}' 상위 10위에 새로운 상품 진입",
                        "detail": p.get('title', p.get('name', '알 수 없음'))[:40],
                        "rank": p.get('rank', '?'),
                        "date": recent[0]['analyzed_date'],
                    })

            # 이탈 상품
            exited = prev_ids - curr_ids
            for pid in exited:
                if pid:
                    p = prev_top10[pid]
                    alerts.append({
                        "keyword": keyword,
                        "type": "exit",
                        "severity": "info",
                        "message": f"'{keyword}' 상위 10위에서 상품 이탈",
                        "detail": p.get('title', p.get('name', '알 수 없음'))[:40],
                        "rank": "10위 밖",
                        "date": recent[0]['analyzed_date'],
                    })

        # 자체 순위 급변동 감지
        rank_rows = conn.execute("""
            SELECT keyword, rank_position, checked_at
            FROM client_rank_history
            WHERE client_id = ? AND rank_position IS NOT NULL
            ORDER BY checked_at DESC LIMIT 100
        """, (client_id,)).fetchall()

        keyword_ranks = defaultdict(list)
        for r in rank_rows:
            keyword_ranks[r['keyword']].append({
                "rank": r['rank_position'],
                "date": r['checked_at']
            })

        for kw, rank_list in keyword_ranks.items():
            if len(rank_list) >= 2:
                latest = rank_list[0]["rank"]
                prev = rank_list[1]["rank"]
                change = prev - latest  # 양수 = 상승

                if abs(change) >= 20:
                    alerts.append({
                        "keyword": kw,
                        "type": "rank_surge" if change > 0 else "rank_drop",
                        "severity": "success" if change > 0 else "danger",
                        "message": f"'{kw}' 순위 {'급상승' if change > 0 else '급하락'} ({abs(change)}순위)",
                        "detail": f"{prev}위 → {latest}위",
                        "rank": latest,
                        "date": rank_list[0]["date"][:10],
                    })

        # 심각도순 정렬
        severity_order = {"danger": 0, "warning": 1, "success": 2, "info": 3}
        alerts.sort(key=lambda x: severity_order.get(x["severity"], 4))

        return {
            "totalAlerts": len(alerts),
            "alerts": alerts[:20],  # 최대 20개
            "dangerCount": sum(1 for a in alerts if a["severity"] == "danger"),
            "warningCount": sum(1 for a in alerts if a["severity"] == "warning"),
        }
    except Exception as e:
        logger.error(f"[경쟁사감지] {e}")
        return None
    finally:
        conn.close()


# ==================== ⑧ 순위 예측 모델 ====================
def get_rank_prediction(client_id: int, keyword: str) -> Optional[Dict]:
    """순위 이력 기반 단순 추세 예측"""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT rank_position, checked_at
            FROM client_rank_history
            WHERE client_id = ? AND keyword = ? AND rank_position IS NOT NULL
            ORDER BY checked_at ASC
        """, (client_id, keyword)).fetchall()

        if len(rows) < 5:
            return {
                "keyword": keyword,
                "ready": False,
                "message": f"데이터 부족 — 현재 {len(rows)}건, 최소 5건 이상 필요합니다.",
            }

        ranks = [r['rank_position'] for r in rows]
        dates = [r['checked_at'][:10] for r in rows]

        # 단순 선형 회귀 (최소자승법)
        n = len(ranks)
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(ranks) / n

        numerator = sum((x[i] - x_mean) * (ranks[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator

        intercept = y_mean - slope * x_mean

        # 7일 후 예측
        predicted_7d = round(slope * (n + 7) + intercept)
        predicted_14d = round(slope * (n + 14) + intercept)
        predicted_30d = round(slope * (n + 30) + intercept)

        # 예측값 범위 제한
        predicted_7d = max(1, predicted_7d)
        predicted_14d = max(1, predicted_14d)
        predicted_30d = max(1, predicted_30d)

        # 추세 판단
        if slope < -1:
            trend = "상승"
            trend_desc = f"매일 약 {abs(slope):.1f}순위씩 상승하는 추세입니다."
        elif slope > 1:
            trend = "하락"
            trend_desc = f"매일 약 {slope:.1f}순위씩 하락하는 추세입니다."
        else:
            trend = "안정"
            trend_desc = "순위가 안정적으로 유지되고 있습니다."

        # 신뢰도 (R² 계산)
        ss_res = sum((ranks[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
        ss_tot = sum((ranks[i] - y_mean) ** 2 for i in range(n))
        r_squared = round(1 - ss_res / ss_tot, 3) if ss_tot > 0 else 0
        confidence = "높음" if r_squared >= 0.7 else ("보통" if r_squared >= 0.4 else "낮음")

        return {
            "keyword": keyword,
            "ready": True,
            "currentRank": ranks[-1],
            "predicted7d": predicted_7d,
            "predicted14d": predicted_14d,
            "predicted30d": predicted_30d,
            "trend": trend,
            "trendDesc": trend_desc,
            "slope": round(slope, 2),
            "rSquared": r_squared,
            "confidence": confidence,
            "dataPoints": n,
            "recentRanks": [{"date": dates[i], "rank": ranks[i]} for i in range(max(0, n - 14), n)],
        }
    except Exception as e:
        logger.error(f"[순위예측] {e}")
        return None
    finally:
        conn.close()


# ==================== 통합 조회 ====================
def get_all_client_insights(client_id: int) -> Dict:
    """업체 상세 페이지용 — 모든 AI 인사이트 한 번에 조회"""
    result = {}

    # 성과 패턴 (⑥)
    try:
        perf = get_client_performance_pattern(client_id)
        if perf:
            result["performance"] = perf
    except Exception as e:
        logger.error(f"[AI인사이트-성과] {e}")

    # 경쟁사 감지 (⑦)
    try:
        alerts = get_competitor_alerts(client_id)
        if alerts:
            result["competitorAlerts"] = alerts
    except Exception as e:
        logger.error(f"[AI인사이트-경쟁] {e}")

    # 키워드 추천 (②)
    try:
        kw_rec = get_keyword_recommendations(client_id)
        if kw_rec:
            result["keywordRecommendations"] = kw_rec
    except Exception as e:
        logger.error(f"[AI인사이트-키워드] {e}")

    # 키워드별 인사이트 (①③④⑤⑧)
    conn = _get_conn()
    try:
        keywords = conn.execute("""
            SELECT DISTINCT keyword FROM client_analyses WHERE client_id = ?
        """, (client_id,)).fetchall()

        keyword_insights = {}
        for kw_row in keywords:
            kw = kw_row['keyword']
            kw_data = {}

            price = get_price_optimization(client_id, kw)
            if price:
                kw_data["priceOptimization"] = price

            ad_eff = get_ad_efficiency(client_id, kw)
            if ad_eff:
                kw_data["adEfficiency"] = ad_eff

            timing = get_optimal_timing(client_id, kw)
            if timing:
                kw_data["optimalTiming"] = timing

            prediction = get_rank_prediction(client_id, kw)
            if prediction:
                kw_data["rankPrediction"] = prediction

            sentiment = get_review_sentiment_trend(client_id, kw)
            if sentiment:
                kw_data["reviewSentiment"] = sentiment

            if kw_data:
                keyword_insights[kw] = kw_data

        if keyword_insights:
            result["keywordInsights"] = keyword_insights
    except Exception as e:
        logger.error(f"[AI인사이트-키워드별] {e}")
    finally:
        conn.close()

    return result
