"""One-shot diagnosis or explicitly approved new backup. Encrypted stdout only."""
import base64
import collections
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.parse

KST = dt.timezone(dt.timedelta(hours=9))
ENDPOINTS = {'/api/collector/' + p for p in
             ['keywords', 'requests', 'serp', 'blocked', 'health', 'status', 'control']}


def command(args, payload=None, timeout=25):
    return subprocess.run(args, input=payload, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, check=False)


def tail_bytes(path, limit):
    with open(path, 'rb') as f:
        start = max(0, os.fstat(f.fileno()).st_size-limit)
        f.seek(start)
        if start:
            f.readline()
        return f.read(limit).decode('utf-8', 'replace'), start > 0


def access_summary(paths, now):
    cutoff = now-dt.timedelta(hours=36)
    rows, networks, buckets, coverage = {}, {}, collections.Counter(), []
    pattern = re.compile(r'^(\S+) \S+ \S+ \[([^]]+)\] "([A-Z]+) ([^ ]+) HTTP/[^\"]+" (\d{3})')
    for path in paths:
        try:
            content, bounded = tail_bytes(path, 32*1024*1024)
        except OSError as e:
            coverage.append({'file': pathlib.Path(path).name, 'error': type(e).__name__})
            continue
        matched, malformed, dates = 0, 0, []
        for line in content.splitlines():
            m = pattern.match(line)
            if not m:
                continue
            ip, stamp, method, url, status = m.groups()
            try:
                at = dt.datetime.strptime(stamp, '%d/%b/%Y:%H:%M:%S %z').astimezone(KST)
            except ValueError:
                continue
            if not cutoff <= at <= now+dt.timedelta(minutes=2):
                continue
            try:
                parsed = urllib.parse.urlsplit(url)
                query = urllib.parse.parse_qs(parsed.query, max_num_fields=20)
            except ValueError:
                malformed += 1
                continue
            if parsed.path not in ENDPOINTS:
                continue
            worker = query.get('worker', ['unspecified'])[0]
            worker = worker if re.fullmatch(r'[0-9]{1,3}', worker) else 'unspecified'
            family = 'Windows' if 'Windows' in line else ('Mac' if 'Macintosh' in line else 'other')
            net = networks.setdefault(ip, 'network-'+str(len(networks)+1))
            key = (net, family, worker, parsed.path, method, int(status))
            s = rows.setdefault(key, {'network': net, 'clientFamily': family,
                'workerQueryZeroBased': worker, 'endpoint': parsed.path, 'method': method,
                'status': int(status), 'count': 0, 'firstAt': at.isoformat(),
                'lastAt': at.isoformat(), 'last30Minutes': 0})
            s['count'] += 1
            s['firstAt'] = min(s['firstAt'], at.isoformat())
            s['lastAt'] = max(s['lastAt'], at.isoformat())
            s['last30Minutes'] += int(at >= now-dt.timedelta(minutes=30))
            minute = at.replace(minute=(at.minute//5)*5, second=0, microsecond=0).isoformat()
            buckets[(net, worker, parsed.path, int(status), minute)] += 1
            matched += 1
            dates.append(at.isoformat())
        coverage.append({'file': pathlib.Path(path).name, 'tailLimited': bounded, 'matched': matched,
                         'malformedUrlsSkipped': malformed,
                         'firstAt': min(dates) if dates else None, 'lastAt': max(dates) if dates else None})
    return {'scope': 'last36h; each log tail <=32MiB; network labels are not PC identities',
            'coverage': coverage, 'groups': list(rows.values()),
            'fiveMinuteCounts': [{'network': k[0], 'worker': k[1], 'endpoint': k[2],
                 'status': k[3], 'at': k[4], 'count': v} for k, v in sorted(buckets.items())]}


def error_summary(text):
    markers = {'UPSTREAM_TIMEOUT': r'upstream timed out', 'CONNECTION_REFUSED': r'connection refused',
        'NO_SPACE': r'no space left', 'DB_LOCKED': r'database is locked',
        'DB_READONLY': r'readonly database', 'MEMORY': r'out of memory|oomkill',
        'FETCH_FAILED': r'failed to fetch', 'CAPTCHA': r'captcha|BLOCKED:',
        'TRACEBACK': r'Traceback', 'TIMEOUT': r'timed out|TimeoutError|timeout',
        'SHOPPING_API_404': r'쇼핑 검색 API 404\(서비스 종료\)',
        'NAVER_API_RETRIES_EXHAUSTED': r'네이버 API 요청 실패 \(재시도 소진\)',
        'SEARCH_AD_API_RETRIES_EXHAUSTED': r'검색광고 API 요청 실패 \(재시도 소진\)',
        'NAVER_API_KEY_MISSING': r'네이버 API 키가 설정되지 않았습니다',
        'RANK_INPUT_EMPTY': r'검색 결과 0건',
        'RANK_RECORD_FAILED': r'순위 (기록 중단|추적 실패|추적 전체 실패|저장 실패)',
        'POSTUPLOAD_RANK_FAILED': r'\[collector\] 순위 즉시 기록 실패',
        'HTTP_429': r'\b429\b|Too Many Requests',
        'HTTP_403': r'\b403\b|Forbidden',
        'HTTP_404': r'\b404\b|Not Found',
        'HTTP_5XX': r'\b50[0234]\b',
        'NGINX_FILE_MISSING': r'open\(\).*failed \(2: No such file or directory\)',
        'NGINX_PERMISSION_DENIED': r'Permission denied',
        'NGINX_DIRECTORY_INDEX': r'directory index .* is forbidden',
        'NGINX_SSL_HANDSHAKE': r'SSL_do_handshake\(\) failed',
        'NGINX_BAD_REQUEST': r'client sent invalid|client sent too long|client intended to send too large',
        'CLIENT_CLOSED': r'client prematurely closed|client closed connection',
        'CONNECTION_RESET': r'connection reset by peer|ERR_CONNECTION_RESET',
        'DNS_RESOLUTION_FAILED': r'Name or service not known|Temporary failure in name resolution|ERR_NAME_NOT_RESOLVED',
        'SQL_SCHEMA_ERROR': r'no such (table|column)|has no column named',
        'ERROR': r'\bERROR\b|Exception'}
    counts, recent = collections.Counter(), []
    for line in text.splitlines():
        found = [code for code, pat in markers.items() if re.search(pat, line, re.I)]
        if found:
            counts.update(found)
            stamp = re.match(r'^(\d{4}[-/]\d{2}[-/]\d{2}[T ][0-9:.+Z-]+)', line)
            recent.append({'at': stamp.group(1) if stamp else None, 'categories': found})
    return {'counts': dict(counts), 'recent': recent[-60:]}


def backup_collect(bundle):
    if bundle.get('approval') != 'approved-backup-only-20260921-op1':
        raise ValueError('BACKUP_APPROVAL_REQUIRED')
    report = {'observedAt': dt.datetime.now(KST).isoformat(),
              'mode': 'APPROVED_NEW_BACKUP_AND_ISOLATED_RESTORE_ONLY'}
    args = ['docker', 'exec', '-i', '-e', 'PYTHONDONTWRITEBYTECODE=1', 'logic-analysis',
            'python3', '-', '--job-dir', '/app/data/backups/collector-validation-20260921-op1']
    result = command(args, bundle['backupScript'].encode(), timeout=220)
    # Do not surface stderr or arbitrary process output on parse failure.
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or type(value.get('passed')) is not bool:
        raise ValueError('INVALID_BACKUP_RESULT')
    report['backup'] = value
    report['commandExitCode'] = result.returncode
    report['finishedAt'] = dt.datetime.now(KST).isoformat()
    return report


def collect(bundle):
    operation = bundle.get('operation', 'read_only')
    if operation == 'backup_verify':
        return backup_collect(bundle)
    if operation != 'read_only':
        raise ValueError('INVALID_OPERATION')
    now = dt.datetime.now(KST)
    report = {'observedAt': now.isoformat(), 'mode': 'READ_ONLY_NO_APP_IMPORTS'}
    report['access'] = access_summary(['/var/log/nginx/access.log.1', '/var/log/nginx/access.log'], now)
    for key, args in (
        ('container', ['docker', 'inspect', '-f', '{"state":{{json .State}},"restartCount":{{.RestartCount}}}', 'logic-analysis']),
        ('database', ['docker', 'exec', '-i', 'logic-analysis', 'python3', '-'])):
        try:
            p = command(args, bundle['dbScript'].encode() if key == 'database' else None,
                        90 if key == 'database' else 10)
            if p.returncode:
                report[key] = {'probeError': 'NONZERO_EXIT', 'exitCode': p.returncode}
            else:
                value = json.loads(p.stdout)
                if key == 'container':
                    state = value.get('state', {})
                    value = {'restartCount': value.get('restartCount'), 'state': {k: state.get(k)
                        for k in ['Status', 'Running', 'OOMKilled', 'ExitCode', 'StartedAt', 'FinishedAt']}}
                report[key] = value
        except Exception as e:
            report[key] = {'probeError': type(e).__name__}
    try:
        p = command(['docker', 'logs', '--since', '12h', '--tail', '2500', '--timestamps', 'logic-analysis'], timeout=15)
        report['applicationErrors'] = error_summary((p.stdout+p.stderr).decode('utf-8', 'replace'))
        report['applicationErrors']['commandExitCode'] = p.returncode
    except Exception as e:
        report['applicationErrors'] = {'probeError': type(e).__name__}
    try:
        text, bounded = tail_bytes('/var/log/nginx/error.log', 2*1024*1024)
        report['nginxErrors'] = error_summary(text)
        report['nginxErrors']['tailLimited'] = bounded
    except OSError as e:
        report['nginxErrors'] = {'probeError': type(e).__name__}
    d = shutil.disk_usage('/var/log')
    report['hostDiskBytes'] = {'total': d.total, 'used': d.used, 'free': d.free}
    return report


def encrypted_main(bundle):
    # Only a public certificate is temporarily written; report stays in memory.
    with tempfile.TemporaryDirectory(prefix='collector-diag-cert-') as tmp:
        cert = pathlib.Path(tmp)/'recipient.pem'
        cert.write_text(bundle['certificate'])
        args = ['openssl', 'cms', '-encrypt', '-binary', '-aes-256-cbc', '-outform', 'DER', str(cert)]
        preflight = command(args, b'ENCRYPTION_PREFLIGHT', 10)
        if preflight.returncode != 0 or not preflight.stdout:
            raise RuntimeError('ENCRYPTION_UNAVAILABLE')
        payload = json.dumps(collect(bundle), ensure_ascii=True, separators=(',', ':')).encode()
        encrypted = command(args, payload, 15)
        if encrypted.returncode != 0 or not encrypted.stdout:
            raise RuntimeError('ENCRYPTION_FAILED')
        encoded = base64.b64encode(encrypted.stdout).decode('ascii')
        print('DIAG_ENCRYPTED_BEGIN')
        for i in range(0, len(encoded), 4096):
            print('ENC:'+encoded[i:i+4096])
        print('DIAG_ENCRYPTED_END')


if __name__ == '__main__':
    try:
        def deadline(_signal, _frame):
            raise SystemExit(124)
        signal.signal(signal.SIGALRM, deadline)
        signal.alarm(250 if DIAG_BUNDLE.get('operation') == 'backup_verify' else 160)
        encrypted_main(DIAG_BUNDLE)
    except BaseException:
        print('DIAG_FAILED_NO_PLAINTEXT_OUTPUT')
        sys.exit(1)
    finally:
        signal.alarm(0)
