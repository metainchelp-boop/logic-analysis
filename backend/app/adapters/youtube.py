"""유튜브 어댑터 — 광고주가 등록한 영상 URL들의 조회수·좋아요·댓글수 수집.

YouTube Data API v3 (videos.list, part=snippet,statistics) 사용.
API 키는 회사 공용 1개(env YOUTUBE_API_KEY) — 광고주별이 아님.
자격 필드 video_url = 영상 URL(들), 쉼표/공백/줄바꿈으로 여러 개 가능.
"""
import os
import re

import requests

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
API = "https://www.googleapis.com/youtube/v3/videos"
TIMEOUT = 20

_ID_IN_URL = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|/live/)([A-Za-z0-9_-]{11})")
_BARE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_ids(video_urls: str) -> list:
    """URL 문자열(여러 개)에서 11자리 영상 ID를 순서 유지·중복 제거로 추출."""
    ids = []
    for part in re.split(r"[\s,]+", video_urls or ""):
        part = part.strip()
        if not part:
            continue
        m = _ID_IN_URL.search(part)
        if m:
            ids.append(m.group(1))
        elif _BARE_ID.match(part):
            ids.append(part)
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


COMMENTS_API = "https://www.googleapis.com/youtube/v3/commentThreads"


def fetch_comments(video_urls: str, per_video: int = 20) -> list:
    """등록 영상들의 상위 댓글 텍스트 수집(텍스트 분석용). 키 없으면 빈 리스트."""
    key = os.environ.get("YOUTUBE_API_KEY", "")
    ids = extract_ids(video_urls)
    if not key or not ids:
        return []
    out = []
    for vid in ids:
        try:
            r = requests.get(COMMENTS_API, params={
                "part": "snippet", "videoId": vid, "maxResults": min(per_video, 100),
                "order": "relevance", "textFormat": "plainText", "key": key,
            }, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            for it in r.json().get("items", []):
                txt = (((it.get("snippet") or {}).get("topLevelComment") or {})
                       .get("snippet") or {}).get("textDisplay")
                if txt:
                    out.append(txt.strip()[:300])
        except Exception:  # noqa: BLE001
            continue
    return out


def fetch_performance(video_urls: str) -> dict:
    """등록된 영상들의 통계를 영상별 + 합계로 반환. 수집기·대시보드·AI리포트 공용."""
    ids = extract_ids(video_urls)
    if not ids:
        return {"videos": [], "totals": {"views": 0, "likes": 0, "comments": 0}, "video_count": 0}
    if not API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY 미설정 — 유튜브 공용 API 키가 필요합니다")
    videos = []
    for i in range(0, len(ids), 50):  # API는 호출당 최대 50개
        chunk = ids[i:i + 50]
        r = requests.get(
            API,
            params={"part": "snippet,statistics", "id": ",".join(chunk), "key": API_KEY},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        for it in r.json().get("items", []):
            st = it.get("statistics", {})
            sn = it.get("snippet", {})
            videos.append({
                "video_id": it["id"],
                "title": sn.get("title", ""),
                "channel": sn.get("channelTitle", ""),
                "published": (sn.get("publishedAt", "") or "")[:10],
                "views": int(st.get("viewCount", 0) or 0),
                "likes": int(st.get("likeCount", 0) or 0),       # 비공개면 0
                "comments": int(st.get("commentCount", 0) or 0),
                "url": "https://youtu.be/" + it["id"],
            })
    totals = {
        "views": sum(v["views"] for v in videos),
        "likes": sum(v["likes"] for v in videos),
        "comments": sum(v["comments"] for v in videos),
    }
    return {"videos": videos, "totals": totals, "video_count": len(videos)}
