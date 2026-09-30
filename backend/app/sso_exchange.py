"""광고센터 전용 단회 로그인 교환. HTTP 강등·재시도·넘겨주기·환경 프록시 없음."""
import json
import os
import re
import urllib.error
import urllib.request

URL = 'https://api.metainc.co.kr/api/sso/exchange'
SHAPE = re.compile(r'[A-Za-z0-9_-]{43}')
MAX_RESPONSE = 64 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _send(req, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            return response.status, response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as error:
        error.close()
        return error.code, b''


def valid(value):
    return isinstance(value, str) and SHAPE.fullmatch(value) is not None


def exchange(code, verifier, *, env=None, send=None):
    """(ok, 최소 신원) / (rejected|outage, None). 원문을 예외·로그에 싣지 않는다."""
    if not valid(code) or not valid(verifier):
        return 'rejected', None
    key = (os.environ if env is None else env).get('SSO_AD_CENTER_CLIENT_KEY', '')
    if not isinstance(key, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', key):
        return 'outage', None
    try:
        request = urllib.request.Request(URL, method='POST', headers={
            'X-Sso-Client-Key':key, 'Accept':'application/json', 'Content-Type':'application/json',
        }, data=json.dumps({'destination':'AD_CENTER','code':code,'codeVerifier':verifier}).encode('ascii'))
        status, body = (send or _send)(request, 8)
        if status in (401, 403):
            return 'rejected', None
        if status != 200 or not isinstance(body, bytes) or len(body) > MAX_RESPONSE:
            return 'outage', None
        result = json.loads(body)
        if not isinstance(result, dict) or result.get('status') != 200:
            return 'outage', None
        profile = result.get('result')
        if not isinstance(profile, dict) or not isinstance(profile.get('id'), str) or not 1 <= len(profile['id'].strip()) <= 100:
            return 'outage', None
        return 'ok', profile
    except Exception:
        return 'outage', None
