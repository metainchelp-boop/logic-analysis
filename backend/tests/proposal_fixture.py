"""맞춤제안서(v3) 시험용 인계 자료 — 실제 보고서 한 건의 **모양과 숫자**를 본떴다.

⚠️ 이 저장소는 공개다 — 업체명·상품 주소는 가짜로 바꿨다(숫자·구조만 실제 보고서와 같다).
"""


def bundle():
    months = [['24.11', 19.6], ['24.12', 18.8], ['25.1', 21.9], ['25.2', 17.3], ['25.3', 19.6], ['25.4', 30.5],
              ['25.5', 22.2], ['25.6', 19.6], ['25.8', 18.3], ['25.9', 27.8], ['25.10', 26.1], ['25.11', 18.5],
              ['26.1', 21.3], ['26.2', 18.6], ['26.3', 39.6], ['26.4', 100], ['26.5', 96.8], ['26.6', 16.3],
              ['26.7', 21.3], ['26.8', 22.9], ['26.9', 16.3], ['26.10', 16.3]]
    related = [
        ("커피원두", 6040, 20300, "중간"), ("아라비카커피", 760, 9440, "높음"), ("원두1KG", 950, 3030, "중간"),
        ("커피원두추천", 590, 2130, "높음"), ("로스터리", 380, 1890, "높음"), ("로스팅원두", 310, 1640, "높음"),
        ("원두콩", 220, 1270, "높음"), ("커피원두1KG", 420, 1010, "높음"), ("원두추천", 450, 940, "높음"),
        ("맛있는원두", 200, 750, "중간"), ("홀빈원두", 210, 640, "중간"), ("원두커피1KG", 210, 620, "중간"),
        ("스페셜티원두", 170, 400, "중간"), ("당일로스팅원두", 100, 310, "높음"),
    ]
    return {
        "v3": True,
        "keyword": "블렌드원두",
        "name": "테스트상점",
        "storeUrl": "https://smartstore.naver.com/example/products/1",
        "productName": "블렌드원두 1kg 당일로스팅 고소한 커피 브라질 에티오피아",
        "volume": [{"relKeyword": "블렌드원두", "monthlyPcQcCnt": 50, "monthlyMobileQcCnt": 60,
                    "monthlyAvePcClkCnt": 0.6, "monthlyAveMobileClkCnt": 0.5, "compIdx": "높음", "plAvgDepth": 8}],
        "related": {
            "related_keywords": [{"keyword": k, "monthlyPcQcCnt": pc, "monthlyMobileQcCnt": mo,
                                  "totalVolume": pc + mo, "compIdx": c} for k, pc, mo, c in related],
            "golden_keywords": [], "total_found": 124,
        },
        "shopProducts": [],
        "datalab": {
            "trend": {"months": [{"label": l, "ratio": v} for l, v in months]},
            "weekday": {"days": [{"label": "월", "index": 62.5}, {"label": "화", "index": 75}, {"label": "수", "index": 100},
                                 {"label": "목", "index": 62.5}, {"label": "금", "index": 70.9},
                                 {"label": "토", "index": 0}, {"label": "일", "index": 0}], "peakDay": "수"},
            "categoryKeywords": {
                "popular": [{"keyword": "원두1KG", "volume": 3980, "growth": 33.3}, {"keyword": "커피원두1KG", "volume": 1430},
                            {"keyword": "커피원두", "volume": 26340}, {"keyword": "아라비카커피", "volume": 10200},
                            {"keyword": "커피원두추천", "volume": 2720}, {"keyword": "로스터리", "volume": 2270}],
                "rising": [{"keyword": "원두1KG", "volume": 3980, "growth": 33.3}],
            },
        },
        "advertiser": {
            "product_info": {"product_name": "", "price": 0},
            "ranking": {"current_rank": None, "total_searched": 0},
            "competitor_comparison": {"items": [], "stats": {}},
            "entry_strategy": {"overall_score": 50, "strategies": [
                {"area": "가격 포지셔닝 & 소구점", "severity": "medium", "insights": ["내 상품 가격 34,000원 (브라우저 실측)"],
                 "recommendations": [{"name": "고객 참여형 이벤트", "reason": "비슷한 가격대에서는 리뷰 이벤트·알림받기로 체감 혜택을 만들어 차별화하세요."},
                                     {"name": "마케팅 메세지", "reason": "기존 고객에게 재구매 유도 메세지를 발송하여 반복 매출을 확보하세요."}]},
                {"area": "상품명 SEO 최적화", "severity": "high", "insights": ["상품명에 메인 키워드가 앞쪽에 없습니다"],
                 "recommendations": [{"name": "SEO 최적화", "reason": "상품명·카테고리·속성값 전반 진단·최적화"},
                                     {"name": "쇼핑검색광고", "reason": "상품명 최적화 전까지 광고로 즉시 노출을 확보하여 판매 데이터를 축적하세요."}]},
                {"area": "실행 로드맵", "severity": "info", "insights": ["x"], "recommendations": []},
            ]},
        },
        "analysis": {},
        "htmlDetail": {
            "metrics": {"total_images": 23, "text_length": 2078, "video_count": 0, "has_delivery_info": True,
                        "has_return_info": True, "has_gift_info": True, "has_certification": True,
                        "has_review_section": True, "has_spec_table": False},
            "scores": {"total": 81},
            "suggestions": [],
            "storeInfo": {"name": "테스트상점", "source": "channelName"},
            "reviewData": {
                "reviewCount": 50, "rating": 4.88, "price": 34000, "category": "식품>음료>커피>원두/생두",
                "reviews": [
                    {"rating": 5, "text": "패키지만 좀 더 좋아지면 만점입니다… 가격대비 너무 좋은 맛과 향이에요 밸런스도 좋구요… 밀봉가능한 찍찍부착이나 좀더 두꺼운 패키지로 업그레이드 요청드립니다..", "sentiment": "positive"},
                    {"rating": 5, "text": "블렌딩 원두 여러곳 마셔봤는데, 특유의 고소한 맛은 좋으면서도 단조로운 느낌은 또 아니고, 정말 만족하면서 마시는 원두입니다.", "sentiment": "positive"},
                    {"rating": 4, "text": "여러곳에서 주문 했었는데 정착 하려고요 재주문 했어요~", "sentiment": "neutral"},
                    {"rating": 5, "text": "맛있어요 신선하고 향 좋아요  산미 조금. 고소함.", "sentiment": "positive"},
                ],
                "reviewTextAnalysis": {"totalExtracted": 11, "avgChars": 54,
                                       "sentiment": {"positive": 7, "neutral": 4, "positiveRatio": 64},
                                       "positiveKeywords": [{"keyword": "맛있", "count": 4}, {"keyword": "좋아", "count": 2},
                                                            {"keyword": "만족", "count": 2}, {"keyword": "고소", "count": 2}],
                                       "negativeKeywords": [], "tagStats": [{"tag": "맛 만족도", "count": 11}]},
            },
        },
        "screen": {"seo": {"scores": {"total": 31}, "suggestions": [{"text": "상품명이 너무 짧습니다. 핵심 키워드와 속성을 추가하세요."}]},
                   "bid": {"low": 700, "base": 1200, "high": 2400},
                   "ai": {"full_text": "AI 종합 의견 예시"}},
    }
