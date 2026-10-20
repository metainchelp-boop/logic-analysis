"""네이버 관제 상세점검·구조·구매 수집 완주 원인 실측 — 밤 백업을 일회용 컨테이너에 복원한 사본에서만(운영 DB 무접촉).

1) 가장 최근 로컬 백업을 지금 판 이미지(382f143)의 공식 복원 검증 도구로 임시 폴더에 복원(검증 통과본만).
2) 네트워크 없는 별도 일회용 컨테이너에서 그 사본을 immutable 읽기 전용으로 열어
   어제(백업 날짜 전날, 하루 전체) 상세점검·구조·구매 작업의 상태·진행 깊이·방문 횟수·완주 계정 크기를 세고,
   엔진 코드 그대로 ERP 업체 목록 지문 계산·계정 권한 확인 한 번에 드는 시간과 그 안의 지문 계산 횟수를 잰다
   (읽기만 · 기준 시각 = 백업 1분 전, 곧 어제 마지막 순간).
3) 임시 폴더를 지운다. 출력은 상태 코드·숫자·시간대만 — 업체명·계정번호·고객번호·본문 미출력.
엔진 컨테이너의 CPU·메모리 몫을 쓰지 않는다(별도 컨테이너). 진단 전용 갈래 — main 에 합치지 않는다.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import time
import zipfile
from datetime import datetime, timedelta, timezone

MODE = 'naver-inspection-facts-v1'
LOCAL = '/var/backups/metainc/naver-engine/local'
DRILL = '/var/backups/metainc/restore-drill'
IMAGE = 'metainc/naver-engine:382f143ad72a5fb0389d79ba0fac199566016e8b'
NAME = re.compile(r'naver-(\d{8}T\d{6}Z)-[0-9a-f]{32}\.zip')
KST = timezone(timedelta(hours=9))
BASE = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true', '--pids-limit', '64', '--memory', '1g', '--cpus', '1',
        '--label', 'metainc.naver.restore-drill=1']

READER = r'''
import collections,json,os,re,socket,sqlite3,sys,time
from datetime import date,datetime,timedelta,timezone
def no_network(*a,**k):
    raise ValueError('NETWORK_FORBIDDEN')
socket.socket.connect=socket.socket.connect_ex=no_network
sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
KST=timezone(timedelta(hours=9))
CODE=re.compile(r'[A-Za-z][A-Za-z0-9_]{0,40}')
def code(v):
    return 'NONE' if v is None else (v if isinstance(v,str) and CODE.fullmatch(v) else 'OTHER')
def bucket(n,edges=(0,1,5,10,20,50,100,200,400)):
    if n is None: return 'none'
    last=None
    for e in edges:
        if n<e: return '<%d'%e
        last=e
    return '>=%d'%last
D=os.environ['FACTS_DAY'];NOW=datetime.fromisoformat(os.environ['FACTS_NOW'])
if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',D) or NOW.tzinfo is None:
    raise ValueError('FACTS_CONFIG')
out={'day':D}
c=sqlite3.connect('file:/drill/out/snapshot.sqlite?mode=ro&immutable=1',uri=True)
c.execute('PRAGMA query_only=ON');c.execute('PRAGMA temp_store=FILE')
def q(sql,args=()):
    return c.execute(sql,args).fetchall()
days=[(date.fromisoformat(D)-timedelta(days=i)).isoformat() for i in range(7)]
# A. 상세점검 일일 작업 상태(지난 7일)
mix={}
for d in days:
    rows=q("SELECT status,error_code,count(*),sum(progress_json IS NOT NULL) FROM naver_auto_inspection_job WHERE kind='daily' AND cycle_day=? GROUP BY 1,2",(d,))
    mix[d]={code(s)+'/'+code(e):[n,p] for s,e,n,p in rows}
out['inspection_daily_mix']=mix
# B·C. 어제 끝나지 못한 작업의 진행 깊이와 방문 횟수(체크포인트 안 시각의 25초 넘는 틈 = 다른 회차)
depth=collections.Counter();visits=collections.Counter();tasks_per_visit=[];frac=[];qlens=[];camps=[]
def times(p):
    for name in ('entities','performance','campaign_budget_details'):
        v=p.get(name)
        if isinstance(v,dict):
            for x in v.values():
                if isinstance(x,dict) and isinstance(x.get('checked_at'),str): yield x['checked_at']
    t=p.get('targets')
    if isinstance(t,dict):
        for g in t.values():
            if isinstance(g,dict):
                for x in g.values():
                    if isinstance(x,dict) and isinstance(x.get('checked_at'),str): yield x['checked_at']
unfinished=0
for status,raw in q("SELECT status,progress_json FROM naver_auto_inspection_job WHERE kind='daily' AND cycle_day=? AND status<>'ok'",(D,)):
    unfinished+=1
    try:
        p=json.loads(raw) if raw else None
    except Exception:
        p=None
    if not isinstance(p,dict):
        depth['no_checkpoint']+=1;continue
    ni=p.get('next_index') if type(p.get('next_index')) is int else None
    ql=len(p['queue']) if isinstance(p.get('queue'),list) else None
    depth[bucket(ni)]+=1
    if ql: qlens.append(ql);frac.append((ni or 0)/ql)
    if isinstance(p.get('campaigns'),list): camps.append(len(p['campaigns']))
    ts=[]
    for s in times(p):
        try: ts.append(datetime.fromisoformat(s).timestamp())
        except Exception: pass
    ts.sort()
    if ts:
        v=1+sum(1 for a,b in zip(ts,ts[1:]) if b-a>25)
        visits[min(v,12)]+=1
        if ni: tasks_per_visit.append(ni/v)
def stats(xs):
    if not xs: return None
    xs=sorted(xs);return dict(n=len(xs),avg=round(sum(xs)/len(xs),2),p50=round(xs[len(xs)//2],2),p90=round(xs[int(len(xs)*0.9)],2),max=round(xs[-1],2))
out['inspection_unfinished']=dict(rows=unfinished,next_index=dict(depth),visits_since_start=dict(sorted(visits.items())),
    tasks_per_visit=stats(tasks_per_visit),done_fraction=stats(frac),queue_length=stats(qlens),campaigns=stats(camps))
# D. 완주(ok) 계정의 크기 · 전날도 완주했는지(지난 7일)
okd={}
for d in days:
    rows=q("SELECT customer_id,progress_json FROM naver_auto_inspection_job WHERE kind='daily' AND status='ok' AND cycle_day=?",(d,))
    prev={r[0] for r in q("SELECT customer_id FROM naver_auto_inspection_job WHERE kind='daily' AND status='ok' AND cycle_day=?",((date.fromisoformat(d)-timedelta(days=1)).isoformat(),))}
    ql=[];cp=[]
    for cid,raw in rows:
        try:
            p=json.loads(raw) if raw else {}
        except Exception:
            p={}
        if isinstance(p.get('queue'),list): ql.append(len(p['queue']))
        if isinstance(p.get('campaigns'),list): cp.append(len(p['campaigns']))
    okd[d]=dict(ok=len(rows),also_ok_previous_day=sum(1 for r in rows if r[0] in prev),queue_length=stats(ql),
                campaigns=dict(collections.Counter(bucket(x,(1,2,5,10)) for x in cp)))
out['inspection_ok']=okd
# E. 성과 수집 완주 계정의 캠페인 수(어제) — 캠페인 0개 계정 수가 상세점검 완주 수와 비슷한지
rows=q("SELECT json_array_length(campaigns_json) FROM naver_auto_performance_job WHERE kind='daily' AND status='ok' AND cycle_day=? AND campaigns_json IS NOT NULL",(D,))
out['performance_ok_campaigns']=dict(collections.Counter(bucket(r[0],(1,2,5,10,20)) for r in rows))
# F. 구매 수집(어제) — 종류·상태 × 캠페인 수 × 진행 위치
fun=collections.Counter()
for kind,status,raw in q("SELECT kind,status,progress_json FROM naver_auto_funnel_job WHERE cycle_day=?",(D,)):
    try:
        p=json.loads(raw) if raw else None
    except Exception:
        p=None
    nc=len(p['campaigns']) if isinstance(p,dict) and isinstance(p.get('campaigns'),list) else None
    ni=p.get('next_index') if isinstance(p,dict) and type(p.get('next_index')) is int else None
    fun[code(kind)+'/'+code(status)+'|c'+bucket(nc,(1,5,10))+'|i'+bucket(ni,(1,5,10))]+=1
out['funnel']=dict(sorted(fun.items()))
# G. 어제 일일 상세점검 줄의 원천 묶음 종류 수(바뀔 때마다 이어읽기가 끊길 수 있는 값)
out['inspection_binding_variants']={k:q("SELECT count(DISTINCT "+k+") FROM naver_auto_inspection_job WHERE kind='daily' AND cycle_day=?",(D,))[0][0]
                                   for k in ('matching_fingerprint','snapshot_at','catalog_at','generation','stage_revision')}
# H. 사람의 연결 결정(지난 7일, 날짜별 개수)
try:
    out['link_decisions']={d:q("SELECT count(*) FROM naver_auto_link_decision WHERE substr(decided_at,1,10)=?",(d,))[0][0] for d in days}
    out['link_revocations']={d:q("SELECT count(*) FROM naver_auto_link_decision WHERE substr(revoked_at,1,10)=?",(d,))[0][0] for d in days}
except sqlite3.Error as e:
    out['link_decisions']=type(e).__name__
# I. 표별 상태·오류 코드(어제)
errs={}
for t in ('naver_auto_inspection_job','naver_auto_structure_job','naver_auto_funnel_job','naver_auto_performance_job'):
    errs[t]={code(s)+'/'+code(e):n for s,e,n in q("SELECT status,error_code,count(*) FROM "+t+" WHERE cycle_day=? GROUP BY 1,2",(D,))}
out['status_by_table']=errs
# J. 구조 일일 작업(어제) — 진행 위치 합(회차 수 근사)
st=collections.Counter();ni_sum=0;qsum=[]
for status,ni,ql in q("SELECT status,json_extract(progress_json,'$.next_index'),json_array_length(progress_json,'$.queue') FROM naver_auto_structure_job WHERE cycle_day=? AND job_key LIKE 'structure:%:daily:%'",(D,)):
    st[code(status)]+=1
    if type(ni) is int: ni_sum+=ni
    if type(ql) is int: qsum.append(ql)
out['structure_daily']=dict(status=dict(st),next_index_sum=ni_sum,queue_length=stats(qsum))
# K. 어제 상세점검 마지막 시도 시각(시간대별)
hours=collections.Counter()
for h,s,n in q("SELECT substr(checked_at,12,2),status,count(*) FROM naver_auto_inspection_job WHERE kind='daily' AND cycle_day=? GROUP BY 1,2",(D,)):
    hours[(h if isinstance(h,str) and re.fullmatch(r'\d\d',h) else 'xx')+'/'+code(s)]+=n
out['inspection_last_attempt_hour']=dict(sorted(hours.items()))
# L. 엔진 코드 그대로 — ERP 업체 목록 크기와 지문·권한 확인 한 번의 시간(백업 시각 기준 · 읽기만)
timing={}
try:
    raw=q("SELECT value FROM naver_auto_meta WHERE key='account_catalog'")
    body=json.loads(raw[0][0]) if raw else None
    timing['catalog_bytes']=len(raw[0][0]) if raw else None
    if isinstance(body,dict):
        timing['catalog_items']=len(body.get('items') or []);timing['catalog_ids']=len(body.get('ids') or [])
    from naver_engine import store as S, inspection_catalog as IC
    if isinstance(body,dict):
        runs=[]
        for _ in range(3):
            t=time.perf_counter();IC.content_digest(body);runs.append(time.perf_counter()-t)
        timing['content_digest_seconds']=[round(x,3) for x in runs]
    c.set_authorizer(S._authorizer(S.PHASE_READ))
    st=S.Store(c,'/drill/out/snapshot.sqlite',None,writer=False)
    runs=[]
    for _ in range(3):
        t=time.perf_counter();proof=st._inspection_catalog_proof(NOW);runs.append(time.perf_counter()-t)
    timing['catalog_proof_seconds']=[round(x,3) for x in runs];timing['catalog_proof_found']=proof is not None
    jobs=S._rows(c.execute("SELECT * FROM naver_auto_inspection_job WHERE kind='daily' AND cycle_day=? AND status IN ('partial','retry') ORDER BY checked_at DESC LIMIT 5",(D,)))
    runs=[];results=collections.Counter();digests=[]
    real=IC.content_digest
    def counted(body):
        counted.n+=1
        return real(body)
    IC.content_digest=counted
    for job in jobs:
        counted.n=0
        t=time.perf_counter()
        try:
            results[str(bool(st.inspection_account_valid(job,NOW)))]+=1
        except Exception as e:
            results[type(e).__name__]+=1
        runs.append(time.perf_counter()-t);digests.append(counted.n)
    IC.content_digest=real
    timing['account_valid_seconds']=[round(x,3) for x in runs];timing['account_valid_results']=dict(results)
    timing['account_valid_digest_calls']=digests
    pjobs=S._rows(c.execute("SELECT * FROM naver_auto_structure_job WHERE cycle_day=? AND status<>'ok' ORDER BY checked_at DESC LIMIT 3",(D,)))
    runs=[]
    for job in pjobs:
        t=time.perf_counter()
        try: st.structure_account_valid(job,NOW)
        except Exception: pass
        runs.append(time.perf_counter()-t)
    timing['structure_valid_seconds']=[round(x,3) for x in runs]
except Exception as e:
    timing['error']=type(e).__name__
out['timing']=timing
c.close()
print(json.dumps(out,sort_keys=True,ensure_ascii=True,separators=(',',':')))
'''


def free_gb():
    fs = os.statvfs('/var/backups')
    return round(fs.f_bavail * fs.f_frsize / 1073741824, 2)


def docker(name, args, data=None, timeout=600):
    try:
        return subprocess.run(BASE + ['--name', name] + args, input=data, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=120)
        raise ValueError('READER_TIMEOUT')


def main():
    result = dict(mode=MODE, ok=False, mutations=0)
    made = False
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        now = datetime.now(KST)
        minute = now.hour * 60 + now.minute
        if minute >= 23 * 60 + 30 or minute < 60:
            raise ValueError('BACKUP_WINDOW')
        names = sorted(n for n in os.listdir(LOCAL) if NAME.fullmatch(n))
        if not names:
            raise ValueError('NO_LOCAL_BACKUP')
        archive = os.path.join(LOCAL, names[-1])
        st = os.lstat(archive)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_mode & 0o077:
            raise ValueError('ARCHIVE_UNSAFE')
        with zipfile.ZipFile(archive) as packed:
            if packed.getinfo('manifest.json').file_size > 1024 * 1024:
                raise ValueError('MANIFEST_SIZE')
            created = datetime.fromisoformat(json.loads(packed.read('manifest.json'))['created_at'])
        kst_date = created.astimezone(KST).date()
        result['archive'] = dict(created_kst=created.astimezone(KST).strftime('%Y-%m-%d %H:%M'), bytes=st.st_size)
        result['free_gb_before'] = free_gb()
        if result['free_gb_before'] < 6:
            raise ValueError('NOT_ENOUGH_SPACE')
        if os.path.lexists(DRILL):
            raise ValueError('DRILL_DIR_EXISTS')
        os.mkdir(DRILL, 0o700)
        made = True
        os.chown(DRILL, st.st_uid, st.st_gid)
        os.chmod(DRILL, 0o700)
        user = '%d:%d' % (st.st_uid, st.st_uid)
        started = time.monotonic()
        restored = docker('naver-inspection-facts-restore', ['--user', user, '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m',
                          '-v', archive + ':/in/archive.zip:ro', '-v', DRILL + ':/drill', IMAGE,
                          'python', '-m', 'naver_runtime.restore_check', '--archive', '/in/archive.zip',
                          '--expected-kst-date', kst_date.isoformat(), '--output-dir', '/drill/out'], timeout=600)
        lines = restored.stdout.decode('utf-8', 'replace').strip().splitlines()
        status = json.loads(lines[-1]).get('status') if lines else None
        result['restore'] = dict(exit=restored.returncode, status=status if status in ('verified', 'failed') else 'OTHER',
                                 seconds=round(time.monotonic() - started, 1))
        if status != 'verified':
            raise ValueError('RESTORE_NOT_VERIFIED')
        started = time.monotonic()
        reader = docker('naver-inspection-facts-read', ['-i', '--user', user, '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=1g',
                        '-e', 'SQLITE_TMPDIR=/tmp', '-e', 'FACTS_DAY=' + (kst_date - timedelta(days=1)).isoformat(),
                        '-e', 'FACTS_NOW=' + (created - timedelta(seconds=60)).astimezone(KST).isoformat(),
                        '-v', DRILL + ':/drill:ro', IMAGE, 'python', '-B', '-'], data=READER.encode(), timeout=840)
        lines = reader.stdout.decode('utf-8', 'replace').strip().splitlines()
        result['reader_exit'] = reader.returncode
        result['reader_seconds'] = round(time.monotonic() - started, 1)
        if reader.returncode != 0 or not lines:
            tail = reader.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:] if reader.stderr else []
            result['reader_error'] = re.sub(r'[^A-Za-z_:. ]', '', tail[0])[:80] if tail else None
            raise ValueError('READER_FAILED')
        result['facts'] = json.loads(lines[-1])
        result['ok'] = True
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', str(error)) else type(error).__name__
    finally:
        if made and os.path.isdir(DRILL) and not os.path.islink(DRILL):
            shutil.rmtree(DRILL, ignore_errors=True)
        result['drill_dir_removed'] = not os.path.lexists(DRILL)
        result['free_gb_after'] = free_gb()
        print('NAVER_INSPECTION_FACTS_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
