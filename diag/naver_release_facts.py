"""네이버 관제 다음 판 준비용 사실 확인 — 읽기 전용 · 비밀값 미출력.

지금 판(711a245)의 준비 실행 번호·적용 작업 번호(배포 기록 JSON 의 해당 칸만)와,
배포 봉투 공개 인증서(recipient.pem — 공개 인증서이며 개인키는 읽지 않는다)의 sha256·만료일·본문을 확인한다.
아무것도 지우거나 바꾸지 않는다. 진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import hashlib
import json
import os
import re
import subprocess

MODE = 'naver-release-facts-v1'
ROOT = '/srv/metainc/ad-deploy-staging'
CURRENT = '711a245ea14b590a83eb6746b760ce53275b6602'
CERT = '/etc/metainc/naver-deploy-envelope/recipient.pem'
HEX32 = re.compile(r'[0-9a-f]{32}')
RUN = re.compile(r'[0-9]{6,15}')


def safe(value, pattern):
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def main():
    result = dict(mode=MODE, ok=False, mutations=0)
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        with open(ROOT + '/receipts/preview-start-' + CURRENT + '.json') as f:
            started = json.load(f)
        with open(ROOT + '/receipts/preview-' + CURRENT + '.json') as f:
            prepared = json.load(f)
        op = safe(started.get('operation_id'), HEX32)
        package = prepared.get('package') if isinstance(prepared.get('package'), dict) else {}
        result['current'] = dict(
            stage=started.get('stage') if started.get('stage') in ('internal_ready', 'prepared') else 'OTHER',
            source_ok=started.get('source_commit') == CURRENT,
            previous=(started.get('previous_commit') or '')[:7] if isinstance(started.get('previous_commit'), str) else None,
            operation_id=op, prepare_run=safe(package.get('run_id'), RUN),
            code_upgrade_receipt=bool(op) and os.path.isfile(ROOT + '/receipts/code-upgrade-' + op + '.json'),
            started_keys=sorted(k for k in started if re.fullmatch('[a-z_]{1,40}', k)),
            prepared_keys=sorted(k for k in prepared if re.fullmatch('[a-z_]{1,40}', k)))
        body = open(CERT, 'rb').read()
        if not body.startswith(b'-----BEGIN CERTIFICATE-----\n') or len(body) > 4096 or b'PRIVATE' in body:
            raise ValueError('CERT_SHAPE')
        end = subprocess.run(['openssl', 'x509', '-noout', '-enddate', '-subject'], input=body, capture_output=True, timeout=20)
        result['envelope'] = dict(sha256=hashlib.sha256(body).hexdigest(),
                                  info=[l for l in end.stdout.decode('ascii', 'replace').splitlines() if re.fullmatch(r'(notAfter|subject)=[ -~]{1,120}', l)],
                                  pem=body.decode('ascii'))
        result['ok'] = True
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', str(error)) else type(error).__name__
    print('NAVER_RELEASE_FACTS_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
