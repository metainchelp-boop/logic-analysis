"""전산 60초·1회용 코드를 서버 자격증명과 PKCE로 교환한다."""
import os
import re
import json

import requests
from fastapi import HTTPException

EXCHANGE_URL = "https://api.metainc.co.kr/api/sso/exchange"
CONSUMER_ORIGIN = "https://logic.metainc.co.kr"
MAX_RESPONSE_BYTES = 64 * 1024


def exchange_identity(code: str, code_verifier: str) -> dict:
    key = os.getenv("SSO_EXCHANGE_CLIENT_KEY", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", key):
        raise HTTPException(status_code=503, detail="전산 연결 로그인이 준비되지 않았습니다.")
    try:
        with requests.Session() as session:
            # 환경 프록시·netrc를 읽지 않고 인증키를 고정 HTTPS 주소에만 보낸다.
            session.trust_env = False
            response = session.post(
                EXCHANGE_URL,
                json={"destination": "LOGIC_ANALYSIS", "code": code, "codeVerifier": code_verifier},
                headers={"X-Sso-Client-Key": key},
                timeout=(3, 8), allow_redirects=False, stream=True,
            )
            try:
                if response.status_code in (400, 401, 403, 409, 410):
                    raise HTTPException(status_code=401, detail="전산에서 다시 열어 로그인해 주세요.")
                if response.status_code in (429, 503):
                    raise HTTPException(status_code=503, detail="전산 연결 로그인을 잠시 이용할 수 없습니다.")
                if response.status_code != 200:
                    raise ValueError("unexpected exchange status")
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ValueError("exchange response too large")
                    body.extend(chunk)
                envelope = json.loads(body)
            finally:
                response.close()
        if not isinstance(envelope, dict) or type(envelope.get("status")) is not int or envelope["status"] != 200:
            raise ValueError("invalid exchange envelope")
        identity = envelope.get("result")
        if not isinstance(identity, dict):
            raise ValueError("invalid identity")
        if (type(identity.get("idx")) is not int or identity["idx"] < 0
                or not isinstance(identity.get("id"), str) or not 1 <= len(identity["id"].strip()) <= 100
                or not isinstance(identity.get("name"), str) or type(identity.get("isManager")) is not bool
                or "authority" not in identity or not isinstance(identity.get("teamList"), list)):
            raise ValueError("invalid identity")
        authority = identity["authority"]
        if authority is not None and (not isinstance(authority, dict) or "name" not in authority
                                      or authority["name"] is not None and not isinstance(authority["name"], str)):
            raise ValueError("invalid identity")
        if any(not isinstance(team, dict) or not isinstance(team.get("name"), str) for team in identity["teamList"]):
            raise ValueError("invalid identity")
        return identity
    except HTTPException:
        raise
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        # 응답·코드·검증값·헤더·예외 본문을 로그 또는 클라이언트에 복사하지 않는다.
        raise HTTPException(status_code=502, detail="전산 연결 로그인을 완료하지 못했습니다.") from None
