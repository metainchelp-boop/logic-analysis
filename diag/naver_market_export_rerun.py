"""시장 내보내기 1회 재실행 — 매일 10:35 타이머가 하는 실행을 지금 한 번만 똑같이 돌린다 · 상태값·시각·개수만 출력.

운영 서버(root)에서 한 번 실행한다. 미리보기(CLEANUP_APPLY=0)는 조건만 보고 끝낸다.
실행(APPLY_NAVER_MARKET_EXPORT_RERUN)은 아래 조건이 모두 맞을 때만 `systemctl start naver-market-export.service` 를
한 번 부른다 — 설치된 단위 파일·코드·타이머·원천 DB·엔진은 바꾸지 않는다. 바뀌는 것은 엔진이 읽는 시장 묶음 파일
(`/var/lib/metainc/naver-market-source/bundle.json`)뿐이고, 이 파일은 원래 매일 새로 쓰인다.

조건: 마지막 실행이 실패 상태이고 지금 돌고 있지 않을 것 · 타이머가 켜져 있을 것 · 타이머 시각(10:25~10:45)과
밤 작업 시간(23:30~01:00)이 아닐 것. 재실행이 또 실패해도 상태는 지금과 같다(실패 기록이 하나 더 남을 뿐).
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

MODE = 'naver-market-export-rerun-v1'
KST = timezone(timedelta(hours=9))
APPLY = os.environ.get('CLEANUP_APPLY') == '1'
SERVICE = 'naver-market-export.service'
READER = 'naver-market-export-reader.service'
TIMER = 'naver-market-export.timer'
BUNDLE = '/var/lib/metainc/naver-market-source/bundle.json'
CODE = re.compile(r'[A-Za-z][A-Za-z0-9_.:-]{0,63}')
STAMP = re.compile(r'[A-Za-z]{3} [0-9: -]{10,25}[A-Z]{2,5}')
PROPS = ('Result', 'ExecMainStatus', 'ActiveState', 'SubState', 'ExecMainStartTimestamp', 'ExecMainExitTimestamp')


def code(value):
    return value if isinstance(value, str) and CODE.fullmatch(value) else (None if value is None else 'OTHER')


def run(args, timeout=20):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    return result.returncode, result.stdout[:65536]


def show(unit):
    rc, raw = run(['systemctl', 'show', unit, '--property=' + ','.join(PROPS)])
    values = dict(line.split('=', 1) for line in raw.decode('ascii', 'replace').splitlines() if '=' in line)
    out = {}
    for key in PROPS:
        value = values.get(key)
        if value and STAMP.fullmatch(value):
            out[key] = value
        elif key == 'ExecMainStatus' and value is not None and value.isdigit():
            out[key] = int(value)
        else:
            out[key] = code(value) if value else None
    return out


def bundle(now):
    try:
        with open(BUNDLE, 'rb') as stream:
            value = json.loads(stream.read(5 * 1024 * 1024 + 1))
        at = datetime.fromisoformat(value['exported_at'])
        stores = value.get('stores') if isinstance(value.get('stores'), list) else []
        return dict(exported_at=at.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S'),
                    age_hours=round((now - at).total_seconds() / 3600, 2), complete=value.get('complete') is True,
                    stores=len(stores), cohorts=sum(len(s.get('cohorts') or []) for s in stores if isinstance(s, dict)))
    except Exception as error:
        return dict(available=False, error=type(error).__name__)


def journal_codes(unit, since):
    rc, raw = run(['journalctl', '--no-pager', '-o', 'cat', '--since', since, '--unit=' + unit], timeout=20)
    found = {}
    for token in re.findall(r'"code":"([A-Z][A-Z0-9_]{2,63})"', raw.decode('utf-8', 'replace')):
        found[token] = found.get(token, 0) + 1
    return found


def main():
    result = dict(mode=MODE, ok=False, apply=APPLY, mutations=0, stage='preflight')
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        now = datetime.now(timezone.utc)
        local = now.astimezone(KST)
        result['now'] = local.strftime('%Y-%m-%d %H:%M:%S')
        minutes = local.hour * 60 + local.minute
        before = dict(service=show(SERVICE), reader=show(READER), bundle=bundle(now))
        rc_enabled, _ = run(['systemctl', 'is-enabled', TIMER])
        rc_active, _ = run(['systemctl', 'is-active', TIMER])
        before['timer_enabled'], before['timer_active'] = rc_enabled == 0, rc_active == 0
        result['before'] = before
        checks = dict(
            last_run_failed=before['service'].get('Result') not in (None, 'success'),
            not_running=before['service'].get('ActiveState') in ('failed', 'inactive')
                        and before['reader'].get('ActiveState') in ('failed', 'inactive'),
            timer_on=before['timer_enabled'] and before['timer_active'],
            outside_timer_window=not (10 * 60 + 25 <= minutes <= 10 * 60 + 45),
            outside_night_window=not (minutes >= 23 * 60 + 30 or minutes < 60))
        result['checks'] = checks
        if not all(checks.values()):
            raise ValueError('PRECONDITION')
        if not APPLY:
            result.update(ok=True, stage='preview')
            return
        result['stage'] = 'start'
        since = local.strftime('%Y-%m-%d %H:%M:%S')
        rc, _ = run(['systemctl', 'start', SERVICE], timeout=150)
        result['mutations'] = 1
        result['start_rc'] = rc
        result['stage'] = 'postflight'
        after_now = datetime.now(timezone.utc)
        after = dict(service=show(SERVICE), reader=show(READER), bundle=bundle(after_now))
        after['codes'] = dict(service=journal_codes(SERVICE, since), reader=journal_codes(READER, since))
        result['after'] = after
        result['deploy_check_ok'] = (after['service'].get('Result') == 'success' and after['service'].get('ExecMainStatus') == 0
                                     and after['reader'].get('Result') == 'success' and after['reader'].get('ExecMainStatus') == 0)
        result['ok'] = rc == 0 and result['deploy_check_ok']
        result['stage'] = 'done'
    except Exception as error:
        text = str(error)
        result['error'] = text if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', text) else type(error).__name__
    finally:
        print('NAVER_MARKET_EXPORT_RERUN_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
