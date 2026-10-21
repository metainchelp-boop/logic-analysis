"""네이버 관제 저장 내보내기(상품·시장) 실행 상태 — 읽기 전용 · 상태값·시각·개수만 · 업체명·자료 본문 미출력.

운영 서버(root)에서 한 번 실행한다. 배포 도구는 교체 전에 내보내기 서비스의 마지막 결과가
성공인지, 타이머가 켜져 있는지, 내보낸 묶음이 30시간 안에 만들어졌는지 본다(`naver_saved_exports.verify`).
그 세 가지를 systemctl·journalctl·파일 정보로 읽기만 한다. 묶음 파일은 형식 필드와 시각·개수만 본다.
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timedelta, timezone

MODE = 'naver-export-facts-v1'
KST = timezone(timedelta(hours=9))
KINDS = ('product', 'market')
OUTPUTS = {'product': '/var/lib/metainc/naver-product-source',
           'market': '/var/lib/metainc/naver-market-source'}
MAX_BUNDLE = 5 * 1024 * 1024
CODE = re.compile(r'[A-Za-z][A-Za-z0-9_.:-]{0,63}')
FIXED = re.compile(r'\b[A-Z][A-Z0-9_]{3,63}\b')
STAMP = re.compile(r'[A-Za-z]{3} [0-9: -]{10,25}[A-Z]{2,5}')


def code(value):
    return value if isinstance(value, str) and CODE.fullmatch(value) else (None if value is None else 'OTHER')


def run(args, timeout=20, limit=4 * 1024 * 1024):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    return result.returncode, result.stdout[:limit]


def show(unit, props):
    try:
        rc, raw = run(['systemctl', 'show', unit, '--property=' + ','.join(props)])
        values = dict(line.split('=', 1) for line in raw.decode('ascii', 'replace').splitlines() if '=' in line)
        out = {}
        for key in props:
            value = values.get(key)
            if value and STAMP.fullmatch(value):
                out[key] = value
            elif key in ('ExecMainStatus', 'NRestarts') and value is not None and value.isdigit():
                out[key] = int(value)
            else:
                out[key] = code(value) if value else None
        return out
    except Exception as error:
        return dict(available=False, error=type(error).__name__)


def state(args):
    try:
        rc, raw = run(args)
        return dict(rc=rc, value=code(raw.decode('ascii', 'replace').strip() or None))
    except Exception as error:
        return dict(available=False, error=type(error).__name__)


def journal(unit):
    try:
        rc, raw = run(['journalctl', '--no-pager', '-o', 'short-iso', '--since', '48 hours ago', '--unit=' + unit], timeout=30)
        counts, codes, last = {}, {}, {}
        for line in raw.decode('utf-8', 'replace').splitlines():
            at = line[:25] if re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}', line) else None
            m = re.search(r'Main process exited, code=(exited|killed|dumped), status=([0-9]{1,3})', line)
            key = None
            if m:
                key = 'exit:%s:%s' % (m[1], m[2])
            elif re.search(r'Failed with result \'([a-z-]{1,32})\'', line):
                key = 'failed:' + re.search(r'Failed with result \'([a-z-]{1,32})\'', line)[1]
            elif re.search(r'\bFinished\b', line):
                key = 'finished'
            elif re.search(r'\bStarting\b|\bStarted\b', line):
                key = 'started'
            if key:
                counts[key] = counts.get(key, 0) + 1
                if at:
                    last[key] = at
            found = set(re.findall(r'"code":"([A-Z][A-Z0-9_]{2,63})"', line))   # 내보내기 emit() 의 고정 코드
            found.update(t for t in FIXED.findall(line)
                         if t.startswith(('EXPORT_', 'COORDINATOR_', 'READER_', 'SOURCE_', 'BUNDLE_', 'PRODUCT_', 'MARKET_', 'SAVED_')))
            for token in found:
                codes[token] = codes.get(token, 0) + 1
        return dict(rc=rc, counts=counts, last=last, codes=codes)
    except Exception as error:
        return dict(available=False, error=type(error).__name__)


def bundle(kind, now):
    folder = OUTPUTS[kind]
    path = os.path.join(folder, 'bundle.json')
    try:
        d = os.lstat(folder)
        out = dict(directory=dict(is_dir=stat.S_ISDIR(d.st_mode), mode=oct(stat.S_IMODE(d.st_mode)), gid=d.st_gid))
        info = os.lstat(path)
        out['file'] = dict(regular=stat.S_ISREG(info.st_mode), mode=oct(stat.S_IMODE(info.st_mode)), gid=info.st_gid,
                           bytes=info.st_size,
                           modified=datetime.fromtimestamp(info.st_mtime, timezone.utc).astimezone(KST).strftime('%Y-%m-%d %H:%M'))
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BUNDLE:
            out['parsed'] = False
            return out
        with open(path, 'rb') as stream:
            value = json.loads(stream.read(MAX_BUNDLE + 1))
        fields = sorted(value) if isinstance(value, dict) else None
        out['fields_ok'] = fields == ['complete', 'exported_at', 'schema_version', 'stores']
        out['schema_version'] = value.get('schema_version') if isinstance(value, dict) and type(value.get('schema_version')) is int else None
        out['complete'] = value.get('complete') if isinstance(value, dict) and type(value.get('complete')) is bool else None
        stores = value.get('stores') if isinstance(value, dict) else None
        out['stores'] = len(stores) if isinstance(stores, list) else None
        field = 'products' if kind == 'product' else 'cohorts'
        if isinstance(stores, list):
            out[field] = sum(len(row.get(field)) for row in stores if isinstance(row, dict) and isinstance(row.get(field), list))
        at = datetime.fromisoformat(value['exported_at']) if isinstance(value, dict) and isinstance(value.get('exported_at'), str) else None
        if at is not None and at.utcoffset() is not None:
            out['exported_at'] = at.astimezone(KST).strftime('%Y-%m-%d %H:%M')
            out['age_hours'] = round((now - at).total_seconds() / 3600, 2)
            out['fresh_for_deploy'] = -300 <= (now - at).total_seconds() <= 30 * 3600
        return out
    except Exception as error:
        return dict(available=False, error=type(error).__name__)


def main():
    result = dict(mode=MODE, ok=False, mutations=0, stage='preflight')
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        now = datetime.now(timezone.utc)
        result['now'] = now.astimezone(KST).strftime('%Y-%m-%d %H:%M')
        result['stage'] = 'units'
        kinds = {}
        for kind in KINDS:
            item = {}
            for suffix in ('export', 'export-reader'):
                unit = 'naver-%s-%s.service' % (kind, suffix)
                item[suffix] = show(unit, ('Result', 'ExecMainStatus', 'ActiveState', 'SubState', 'NRestarts',
                                           'ExecMainStartTimestamp', 'ExecMainExitTimestamp'))
                item[suffix]['deploy_check_ok'] = (item[suffix].get('Result') == 'success' and item[suffix].get('ExecMainStatus') == 0)
                item[suffix + '_journal_48h'] = journal(unit)
            timer = 'naver-%s-export.timer' % kind
            item['timer'] = show(timer, ('ActiveState', 'SubState', 'UnitFileState', 'LastTriggerUSec', 'NextElapseUSecRealtime', 'Result'))
            item['timer_enabled'] = state(['systemctl', 'is-enabled', timer])
            item['timer_active'] = state(['systemctl', 'is-active', timer])
            item['bundle'] = bundle(kind, now)
            kinds[kind] = item
        result['kinds'] = kinds
        result['deploy_checks_pass'] = all(
            k['export']['deploy_check_ok'] and k['export-reader']['deploy_check_ok']
            and k['timer_enabled'].get('rc') == 0 and k['timer_active'].get('rc') == 0
            and k['bundle'].get('fresh_for_deploy') is True and k['bundle'].get('complete') is True
            for k in kinds.values())
        result['ok'] = True
        result['stage'] = 'done'
    except Exception as error:
        text = str(error)
        result['error'] = text if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', text) else type(error).__name__
    print('NAVER_EXPORT_FACTS_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
