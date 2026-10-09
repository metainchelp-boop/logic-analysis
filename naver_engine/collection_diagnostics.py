"""현재 일일 대상의 상세점검 원장과 이어읽기 상태를 숫자로만 투영한다."""
import json

from . import morning_progress as CP, store as S
from app.naver_auto import verdict as V


STATUSES = (V.CHECK_OK, V.CHECK_PARTIAL, V.CHECK_DATA_LATE, V.CHECK_KEY_REJECTED,
            V.CHECK_SYSTEM_GAP, V.CHECK_LINK_BROKEN, V.CHECK_LINK_MISSING,
            V.CHECK_NOT_ELIGIBLE, V.CHECK_NOT_CHECKED, V.CHECK_PENDING)
WRITER_KEYS = ('queue_depth', 'busy_duration_ms', 'active_phase', 'last_completed_phase',
               'accepted', 'completed', 'queued_cancel', 'full', 'closed', 'error')


def writer_status(getter):
    """등록된 RAM 콜백의 고정 숫자만. 없음/실패는 0인 정상 상태로 만들지 않는다."""
    try:
        value = getter()
        if not isinstance(value, dict) or set(value) != set(WRITER_KEYS) or any(
                type(value[key]) is not int or not 0 <= value[key] <= 9007199254740991 for key in WRITER_KEYS) \
                or value['active_phase'] > 104 or value['last_completed_phase'] > 104:
            return {'available': False}
        return {'available': True, **{key: value[key] for key in WRITER_KEYS}}
    except Exception:
        return {'available': False}


def project(policies, account_days, checkpoints, decisions, now):
    """식별자·금액·원문은 반환하지 않는다. 날짜와 귀속이 다르면 오늘 완료가 아니다."""
    today = now.astimezone(S.KST).date().isoformat()
    ready = bool(policies) and all(row['source_current'] for row in policies.values())
    daily = {cid: row for cid, row in policies.items() if row['decision'].cadence == 'daily'}
    counts = {key: 0 for key in (*STATUSES, 'recorded', 'rules_not_run', 'unreadable', 'pid_mismatch')}
    progress = {'reading': 0, 'blocked': 0, 'binding_mismatch': 0}
    marks = {row[0]: row[1:] for row in account_days}
    for cid, policy in daily.items():
        mark = marks.get(cid)
        if mark is None or mark[0] != policy['possibility_id']:
            counts['pending'] += 1
            counts['pid_mismatch'] += mark is not None
            continue
        status, raw_rules = mark[1:]
        if status not in STATUSES:
            counts['unreadable'] += 1
            continue
        try:
            rules = json.loads(raw_rules)
            if not isinstance(rules, list) or any(not isinstance(row, list) or len(row) != 2
                    or any(not isinstance(value, str) for value in row) for row in rules):
                raise ValueError()
        except (ValueError, TypeError, RecursionError):
            counts['unreadable'] += 1
            continue
        counts[status] += 1
        counts['recorded'] += 1
        counts['rules_not_run'] += bool(rules)
    by_customer = {}
    for decision in decisions:
        by_customer.setdefault(decision.customer_id, []).append(
            (decision.possibility_id, decision.decision, decision.decision_id))
    for cid, pid, day, binding, status in checkpoints:
        if cid not in daily or status not in ('reading', 'blocked'):
            continue
        policy = daily[cid]
        expected = CP.digest(CP.packed([cid, policy['possibility_id'], today, policy['stage_key'],
            policy['stage_revision'], policy.get('_auto_identity'), sorted(by_customer.get(cid, []))]))
        if pid != policy['possibility_id'] or day != today or binding != expected:
            progress['binding_mismatch'] += 1
        else:
            progress[status] += 1
    targets = len(daily)
    # 대상 없음은 전부 완료가 아니다. ok·규칙 미실행·이어읽기 상태를 따로 대조한다.
    complete = ready and targets > 0 and counts['ok'] == targets and not any(
        counts[key] for key in ('rules_not_run', 'unreadable', 'pid_mismatch')) \
        and progress['reading'] == progress['blocked'] == 0
    return {'scope': 'current_daily_accounts', 'day': today, 'checked_at': now.isoformat(),
            'ready': ready, 'targets': targets if ready else None, 'counts': counts,
            'checkpoints': progress, 'ledger_complete': complete}
