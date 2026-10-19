"""네이버 관제 엔진 상태 점검 — 읽기 전용 · 집계만 · 업체명·계정번호 미출력.

운영 서버(root)에서 한 번 실행한다. 엔진 컨테이너·서비스 상태를 docker/systemctl 로 읽고,
엔진 DB 는 컨테이너 안에서 UID 10001 로 `mode=ro` + `query_only` + 쓰기 거부 authorizer 로 연다.
출력은 상태값·오류 코드·개수·시각뿐이다. 진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone

MODE = 'naver-engine-health-v1'
KST = timezone(timedelta(hours=9))
CODE = re.compile(r'[A-Za-z][A-Za-z0-9_.:-]{0,63}')
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')

READER = r'''
import json,os,re,socket,sqlite3,time
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
KST=timezone(timedelta(hours=9))
CODE=re.compile(r'[A-Za-z][A-Za-z0-9_.:-]{0,63}')
DAY=re.compile(r'\d{4}-\d{2}-\d{2}')
def code(v):
    return v if isinstance(v,str) and CODE.fullmatch(v) else (None if v is None else 'OTHER')
def day(v):
    return v if isinstance(v,str) and DAY.fullmatch(v) else 'OTHER'
def stamp(v):
    if not isinstance(v,str) or len(v)>48:
        return None
    try:
        d=datetime.fromisoformat(v.replace('Z','+00:00'))
        if d.tzinfo is None:
            return None
        return d.astimezone(KST).strftime('%Y-%m-%d %H:%M')
    except ValueError:
        return None
def auth(action,a1,a2,db,src):
    if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_TRANSACTION):
        return sqlite3.SQLITE_OK
    if action==sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (a2 or '').lower() in ('load_extension','readfile','writefile','shell','eval','fts3_tokenizer') else sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY
try:
    if os.geteuid()!=10001:
        raise ValueError('READER_IDENTITY')
    def no_network(*a,**k):
        raise ValueError('READER_NETWORK_FORBIDDEN')
    socket.socket.connect=socket.socket.connect_ex=no_network
    path=Path('/var/lib/naver-engine/engine.db')
    if path.is_symlink() or not path.is_file():
        raise ValueError('READER_DATABASE_PATH')
    c=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,isolation_level=None,timeout=1)
    c.execute('PRAGMA query_only=ON');c.execute('PRAGMA busy_timeout=1000');c.execute('PRAGMA trusted_schema=OFF')
    if c.execute('PRAGMA query_only').fetchone()!=(1,):
        raise ValueError('READER_MODE')
    c.set_authorizer(auth)
    deadline=time.monotonic()+20
    c.set_progress_handler(lambda:time.monotonic()>=deadline,1000)
    stage='begin';out={}
    c.execute('BEGIN')
    try:
        now=datetime.now(KST);today=now.date();since=(today-timedelta(days=2)).isoformat()
        out['observed_at']=now.strftime('%Y-%m-%d %H:%M')
        stage='schema'
        row=c.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()
        out['schema']=row[0] if row and isinstance(row[0],str) and re.fullmatch(r'\d{1,4}',row[0]) else None
        stage='accounts'
        out['accounts_present']=c.execute('SELECT count(*) FROM naver_auto_account WHERE present=1').fetchone()[0]
        stage='check_run'
        out['check_runs']=[dict(run_date=day(r[0]),started=stamp(r[1]),finished=stamp(r[2]),status=code(r[3]),
            accounts_total=r[4],accounts_ok=r[5],error_kind=code(r[6])) for r in c.execute(
            'SELECT run_date,started_at,finished_at,status,accounts_total,accounts_ok,error_kind FROM naver_auto_check_run ORDER BY run_id DESC LIMIT 6')]
        def jobs(table,extra_kind=True):
            kind='kind' if extra_kind else "'-'"
            rows=c.execute('SELECT '+kind+',cycle_day,status,count(*),sum(attempts>=3),max(checked_at),count(DISTINCT customer_id),sum(progress_json IS NOT NULL) FROM '+table
                +' WHERE cycle_day>=? GROUP BY 1,2,3 ORDER BY 2 DESC,1,3',(since,)).fetchall()
            errs=c.execute('SELECT '+kind+',cycle_day,status,error_code,count(*) FROM '+table
                +' WHERE cycle_day>=? AND error_code IS NOT NULL GROUP BY 1,2,3,4 ORDER BY 5 DESC LIMIT 40',(since,)).fetchall()
            return dict(groups=[dict(kind=code(r[0]),day=day(r[1]),status=code(r[2]),count=r[3],attempts_3plus=r[4],
                last_checked=stamp(r[5]),customers=r[6],with_checkpoint=r[7]) for r in rows],
                errors=[dict(kind=code(r[0]),day=day(r[1]),status=code(r[2]),error_code=code(r[3]),count=r[4]) for r in errs])
        stage='inspection';out['inspection']=jobs('naver_auto_inspection_job')
        stage='performance';out['performance']=jobs('naver_auto_performance_job')
        stage='funnel';out['funnel']=jobs('naver_auto_funnel_job')
        stage='structure';out['structure']=jobs('naver_auto_structure_job',extra_kind=False)
        stage='morning'
        out['morning']=[dict(day=day(r[0]),status=code(r[1]),count=r[2]) for r in c.execute(
            'SELECT day,status,count(*) FROM naver_auto_morning_progress WHERE day>=? GROUP BY 1,2 ORDER BY 1 DESC,2',(since,))]
        stage='reports'
        out['report_jobs_by_state']=[dict(state=code(r[0]),count=r[1]) for r in c.execute(
            'SELECT state,count(*) FROM naver_auto_report_schedule_job GROUP BY 1 ORDER BY 1')]
        recent=(now-timedelta(days=2)).isoformat()
        out['report_jobs_recent']=[dict(state=code(r[0]),diagnostic=code(r[1]),count=r[2],last_updated=stamp(r[3])) for r in c.execute(
            "SELECT state,json_extract(payload_json,'$.diagnostic.code'),count(*),max(json_extract(payload_json,'$.updated_at')) "
            "FROM naver_auto_report_schedule_job WHERE json_extract(payload_json,'$.updated_at')>=? GROUP BY 1,2 ORDER BY 3 DESC LIMIT 30",(recent,))]
        stage='done'
        if c.total_changes!=0:
            raise ValueError('READER_MUTATION')
    finally:
        try:
            if c.in_transaction:
                c.execute('ROLLBACK')
        finally:
            c.close()
    out['mutations']=0
    print(json.dumps(out,sort_keys=True,ensure_ascii=True,separators=(',',':')))
except Exception as e:
    msg=str(e) if isinstance(e,ValueError) and re.fullmatch('READER_[A-Z_]{1,40}',str(e) or '') else type(e).__name__
    print(json.dumps({'failure':msg,'stage':locals().get('stage')}))
'''


def code(value):
    return value if isinstance(value, str) and CODE.fullmatch(value) else (None if value is None else 'OTHER')


def run(args, timeout=20, data=None, limit=8 * 1024 * 1024):
    result = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise ValueError('CMD_FAILED:' + os.path.basename(args[0]))
    return result.stdout[:limit], result.stderr[:limit]


def docker_stamp(value):
    if not isinstance(value, str) or not re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', value):
        return None
    if value.startswith('0001-'):
        return None
    at = datetime.strptime(value[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    return at.astimezone(KST).strftime('%Y-%m-%d %H:%M')


def container(project, service):
    raw, _ = run(['docker', 'ps', '-a', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + project,
                  '--filter', 'label=com.docker.compose.service=' + service, '--format', '{{.ID}}'])
    ids = [x for x in raw.decode().split() if re.fullmatch('[0-9a-f]{64}', x)]
    if len(ids) != 1:
        return None, dict(found=len(ids))
    cid = ids[0]
    fmt = ('{"running":{{json .State.Running}},"status":{{json .State.Status}},"started":{{json .State.StartedAt}},'
           '"exit_code":{{json .State.ExitCode}},"oom_killed":{{json .State.OOMKilled}},"restarts":{{json .RestartCount}},'
           '"image":{{json .Image}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"user":{{json .Config.User}},'
           '"memory_limit":{{json .HostConfig.Memory}},"nano_cpus":{{json .HostConfig.NanoCpus}}}')
    raw, _ = run(['docker', 'inspect', '--format', fmt, cid])
    state = json.loads(raw)
    label, _ = run(['docker', 'image', 'inspect', '--format',
                    '{{json (index .Config.Labels "metainc.naver.preview.source")}}', state['image']])
    source = json.loads(label)
    view = dict(found=1, running=state['running'] is True, status=code(state['status']),
                started=docker_stamp(state['started']), exit_code=state['exit_code'],
                oom_killed=state['oom_killed'] is True, restarts=state['restarts'],
                readonly=state['readonly'] is True, user=code(state['user']),
                memory_limit_mb=(state['memory_limit'] or 0) // (1024 * 1024),
                cpus=(state['nano_cpus'] or 0) / 1e9,
                source_commit=source if isinstance(source, str) and re.fullmatch('[0-9a-f]{40}', source) else None)
    return cid, view


def stats(cid):
    try:
        raw, _ = run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', cid], timeout=30)
        item = json.loads(raw)
        cpu = re.fullmatch(r'([0-9.]{1,8})%', item.get('CPUPerc', ''))
        mem = re.fullmatch(r'([0-9.]{1,8})%', item.get('MemPerc', ''))
        return dict(cpu_percent=float(cpu[1]) if cpu else None, memory_percent=float(mem[1]) if mem else None)
    except Exception:
        return dict(available=False)


def systemd(unit):
    try:
        raw, _ = run(['systemctl', 'show', unit, '--property=ActiveState,SubState,NRestarts,ExecMainStartTimestamp'])
        props = dict(line.split('=', 1) for line in raw.decode().splitlines() if '=' in line)
        return dict(active=code(props.get('ActiveState')), sub=code(props.get('SubState')),
                    restarts=int(props['NRestarts']) if props.get('NRestarts', '').isdigit() else None,
                    main_started=props.get('ExecMainStartTimestamp') or None
                    if re.fullmatch(r'[A-Za-z]{3} [0-9: -]{10,25}[A-Z]{2,5}', props.get('ExecMainStartTimestamp') or '') else None)
    except Exception:
        return dict(available=False)


def journal_exits(unit):
    try:
        raw, _ = run(['journalctl', '--no-pager', '-o', 'cat', '--since', '24 hours ago', '--unit=' + unit], timeout=20)
        counts = {}
        for line in raw.decode('utf-8', 'replace').splitlines():
            m = re.search(r'Main process exited, code=(exited|killed|dumped), status=([0-9]{1,3})', line)
            key = 'exit:%s:%s' % (m[1], m[2]) if m else ('started' if re.search(r'^Started ', line) else None)
            if key:
                counts[key] = counts.get(key, 0) + 1
        return counts
    except Exception:
        return dict(available=False)


PATTERNS = (
    ('job_failed', re.compile(r'예약 작업 실패: ([a-z_]{1,32}) ([A-Za-z][A-Za-z0-9_]{0,63})')),
    ('cycle_failed', re.compile(r'예약 회차 실패: ([A-Za-z][A-Za-z0-9_]{0,63})')),
    ('report_job_failed', re.compile(r'보고서 예약 작업 실패: ([A-Za-z][A-Za-z0-9_]{0,63})')),
    ('failure_record_failed', re.compile(r'예약 작업 실패 기록을 저장하지 못했습니다()')),
    ('api_store_busy', re.compile(r'화면 API 저장소 바쁨: ([A-Za-z][A-Za-z0-9_]{0,63})')),
    ('api_store_refused', re.compile(r'화면 API 저장소 거절: ([A-Za-z][A-Za-z0-9_]{0,63})')),
    ('api_store_error', re.compile(r'화면 API 저장소 오류: ([A-Za-z][A-Za-z0-9_]{0,63})')),
    ('api_unexpected', re.compile(r'화면 API 뜻밖의 오류: ([A-Za-z][A-Za-z0-9_]{0,63})')),
    ('api_response_failed', re.compile(r'화면 API 응답 만들기 실패: ([A-Za-z][A-Za-z0-9_]{0,63})')),
    ('audit_write_failed', re.compile(r'열람·쓰기 기록 실패: ([A-Za-z][A-Za-z0-9_]{0,63})')),
    ('ai_job_state_failed', re.compile(r'AI 작업 상태 기록 실패()')),
    ('preview_failed', re.compile(r'미리보기 실패: ([A-Za-z][A-Za-z0-9_]{0,63})')),
    ('relay_failed', re.compile(r'관제 엔진 중계 실패: ([A-Za-z][A-Za-z0-9_-]{0,63})')),
    ('traceback', re.compile(r'Traceback \(most recent call last\)()')),
)


def log_counts(cid):
    try:
        out, err = run(['docker', 'logs', '--since', '24h', '--tail', '20000', '--timestamps', cid], timeout=60)
        lines = (out + b'\n' + err).decode('utf-8', 'replace').splitlines()
        counts, last = {}, {}
        for line in lines:
            tick, _, message = line.partition(' ')
            for name, pattern in PATTERNS:
                m = pattern.search(message)
                if m:
                    key = name + ''.join(':' + g for g in m.groups() if g)
                    counts[key] = counts.get(key, 0) + 1
                    at = docker_stamp(tick)
                    if at and (key not in last or at > last[key]):
                        last[key] = at
                    break
        items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:40]
        return dict(lines=len(lines), sample_limit_reached=len(lines) >= 20000,
                    events=[dict(event=k, count=v, last=last.get(k)) for k, v in items])
    except Exception:
        return dict(available=False)


def storage():
    root = '/var/lib/metainc/naver-engine'
    try:
        files = {}
        for label, suffix in (('database', ''), ('wal', '-wal')):
            path = os.path.join(root, 'engine.db' + suffix)
            files[label + '_mb'] = round(os.lstat(path).st_size / 1048576, 1) if os.path.isfile(path) else None
        fs = os.statvfs(root)
        files['disk_free_gb'] = round(fs.f_bavail * fs.f_frsize / 1073741824, 1)
        return files
    except Exception:
        return dict(available=False)


def main():
    result = dict(mode=MODE, ok=False, mutations=0, stage='preflight')
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        result['stage'] = 'engine'
        cid, engine = container('naver-engine', 'naver-engine')
        result['engine'] = engine
        result['engine_service'] = systemd('metainc-naver-engine.service')
        result['engine_journal_24h'] = journal_exits('metainc-naver-engine.service')
        rid, relay = container('naver-relay', 'naver-relay')
        result['relay'] = relay
        result['storage'] = storage()
        if cid is None or not engine.get('running'):
            raise ValueError('ENGINE_NOT_RUNNING')
        result['engine_usage'] = stats(cid)
        result['stage'] = 'logs'
        result['engine_logs_24h'] = log_counts(cid)
        if rid is not None:
            result['relay_logs_24h'] = log_counts(rid)
        result['stage'] = 'database'
        raw, _ = run(['docker', 'exec', '-i', '--user', '10001:10001', cid, 'python', '-I', '-B', '-'],
                     data=READER.encode(), timeout=40, limit=256 * 1024)
        db = json.loads(raw.decode().strip().splitlines()[-1])
        result['database'] = db
        result['stage'] = 'postflight'
        _, after = container('naver-engine', 'naver-engine')
        result['engine_unchanged'] = all(after.get(k) == engine.get(k) for k in ('running', 'started', 'restarts', 'source_commit'))
        result['ok'] = 'failure' not in db and result['engine_unchanged']
        result['stage'] = 'done'
    except Exception as error:
        text = str(error)
        result['error'] = text if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}(:[a-z]{1,20})?', text) else type(error).__name__
    print('NAVER_ENGINE_HEALTH_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
