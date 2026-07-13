"""네이버 커머스 API 어댑터 — 인증(서명+토큰) + 실데이터 조회.

인증 흐름(공식):
  1) timestamp(ms) + client_id 로 비밀번호 문자열 생성
  2) client_secret(=bcrypt salt)으로 bcrypt 해시 → base64 → 전자서명
  3) /external/v1/oauth2/token 으로 access_token 발급
  4) Authorization: Bearer 로 각 API 호출
"""
import time
import base64
import bcrypt
import requests

BASE = "https://api.commerce.naver.com"
TIMEOUT = 15


def _signature(client_id: str, client_secret: str, timestamp: int) -> str:
    pwd = f"{client_id}_{timestamp}".encode("utf-8")
    hashed = bcrypt.hashpw(pwd, client_secret.encode("utf-8"))
    return base64.b64encode(hashed).decode("utf-8")


def get_token(client_id: str, client_secret: str) -> str:
    """access_token 발급. 실패 시 네이버가 준 에러 메시지를 그대로 올림(디버깅용)."""
    ts = int(time.time() * 1000)
    sign = _signature(client_id, client_secret, ts)
    res = requests.post(
        f"{BASE}/external/v1/oauth2/token",
        data={
            "client_id": client_id,
            "timestamp": ts,
            "client_secret_sign": sign,
            "grant_type": "client_credentials",
            "type": "SELF",
        },
        timeout=TIMEOUT,
    )
    if res.status_code != 200:
        raise RuntimeError(f"토큰 발급 실패 ({res.status_code}): {res.text[:400]}")
    token = res.json().get("access_token")
    if not token:
        raise RuntimeError(f"토큰 없음: {res.text[:400]}")
    return token


def fetch_summary(client_id: str, client_secret: str) -> dict:
    """연결 테스트용 — 인증 성공 여부 + 스토어 채널 정보(있으면)를 반환.
    실데이터 조회는 다음 단계에서 주문/매출 엔드포인트로 확장."""
    token = get_token(client_id, client_secret)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    out = {"authenticated": True}

    # 판매자 채널(스토어) 정보
    try:
        r = requests.get(
            f"{BASE}/external/v1/seller/channels", headers=headers, timeout=TIMEOUT
        )
        out["seller_channels_status"] = r.status_code
        out["seller_channels"] = (
            r.json() if r.status_code == 200 else r.text[:400]
        )
    except Exception as e:  # noqa: BLE001
        out["seller_channels_error"] = str(e)

    return out
