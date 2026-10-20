"""네이버 관제 엔진 DB 표별 크기 실측 — 밤 백업을 일회용 컨테이너에 복원한 사본에서만 잰다(운영 DB 무접촉).

1) 가장 최근 로컬 백업을 지금 판 이미지(382f143)의 공식 복원 검증 도구로 임시 폴더에 복원(검증 통과본만).
2) 네트워크 없는 별도 일회용 컨테이너에서 그 사본을 immutable 읽기 전용으로 열어
   dbstat 로 표·색인별 바이트, 보고서 사본의 날짜별·상태별·최신판/지난판 바이트, 같은 내용 반복 판 수를 센다.
3) 임시 폴더를 지운다. 출력은 표 이름(코드 식별자)과 숫자만 — 업체명·계정번호·본문 미출력.
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

MODE = 'naver-db-census-v1'
LOCAL = '/var/backups/metainc/naver-engine/local'
DRILL = '/var/backups/metainc/restore-drill'
IMAGE = 'metainc/naver-engine:382f143ad72a5fb0389d79ba0fac199566016e8b'
NAME = re.compile(r'naver-(\d{8}T\d{6}Z)-[0-9a-f]{32}\.zip')
KST = timezone(timedelta(hours=9))
BASE = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true', '--pids-limit', '64', '--memory', '1g', '--cpus', '1',
        '--label', 'metainc.naver.restore-drill=1']

CENSUS = r'''
import collections,hashlib,json,os,re,socket,sqlite3,time
def no_network(*a,**k):
    raise ValueError('NETWORK_FORBIDDEN')
socket.socket.connect=socket.socket.connect_ex=no_network
DAY=re.compile(r'\d{4}-\d{2}-\d{2}')
TABLE=re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')
VOLATILE=re.compile(r'(^|_)(at|time|timestamp|generated|updated|created|checked|observed|revision|report_id|id)$')
out={}
c=sqlite3.connect('file:/drill/out/snapshot.sqlite?mode=ro&immutable=1',uri=True)
c.execute('PRAGMA query_only=ON');c.execute('PRAGMA temp_store=FILE')
started=time.monotonic()
size=c.execute('PRAGMA page_size').fetchone()[0];pages=c.execute('PRAGMA page_count').fetchone()[0]
out['pages']=dict(page_size=size,page_count=pages,bytes=size*pages,freelist=c.execute('PRAGMA freelist_count').fetchone()[0])
owner={r[0]:r[1] for r in c.execute("SELECT name,tbl_name FROM sqlite_master WHERE type IN ('table','index')")}
per={}
try:
    rows=c.execute('SELECT name,pgsize,ncell,payload,unused FROM dbstat WHERE aggregate=TRUE').fetchall()
except sqlite3.Error:
    rows=c.execute('SELECT name,sum(pgsize),sum(ncell),sum(payload),sum(unused) FROM dbstat GROUP BY name').fetchall()
for name,pg,nc,pl,un in rows:
    t=owner.get(name,name)
    if not TABLE.fullmatch(t or ''):
        t='OTHER'
    item=per.setdefault(t,dict(bytes=0,index_bytes=0,payload=0,unused=0))
    if name==t:
        item['bytes']+=pg;item['payload']+=pl;item['unused']+=un
    else:
        item['index_bytes']+=pg
counts={}
for t in per:
    if t!='OTHER' and t in owner and owner[t]==t:
        counts[t]=c.execute('SELECT count(*) FROM "'+t+'"').fetchone()[0]
for t,item in per.items():
    item['rows']=counts.get(t)
    item['avg_row_bytes']=round((item['bytes']+item['index_bytes'])/counts[t]) if counts.get(t) else None
out['tables']=dict(sorted(per.items(),key=lambda kv:-(kv[1]['bytes']+kv[1]['index_bytes'])))
out['dbstat_seconds']=round(time.monotonic()-started,1)
# 보고서 사본
T='naver_auto_report_snapshot'
cols=[r[1] for r in c.execute('SELECT * FROM pragma_table_info(?)',(T,))]
out['report_columns']=[x for x in cols if TABLE.fullmatch(x)]
need=[x for x in ('report_id','possibility_id','period_key','revision_no','generated_at','status','review_status') if x in cols]
started=time.monotonic()
by_day=collections.defaultdict(lambda:[0,0]);by_status=collections.defaultdict(lambda:[0,0])
pairs=collections.defaultdict(list)
for r in c.execute('SELECT '+','.join(need)+',length(CAST(payload_json AS BLOB)),payload_json FROM '+T+' ORDER BY rowid'):
    rec=dict(zip(need,r[:len(need)]));n=r[len(need)];body=r[len(need)+1]
    d=(rec.get('generated_at') or '')[:10];d=d if DAY.fullmatch(d) else 'OTHER'
    by_day[d][0]+=1;by_day[d][1]+=n
    s=str(rec.get('status'))+'/'+str(rec.get('review_status'))
    by_status[s if re.fullmatch('[a-z_/]{1,40}',s) else 'OTHER'][0]+=1;by_status[s if re.fullmatch('[a-z_/]{1,40}',s) else 'OTHER'][1]+=n
    exact=hashlib.sha256(body.encode() if isinstance(body,str) else (body or b'')).hexdigest()
    try:
        obj=json.loads(body)
        def strip(x):
            if isinstance(x,dict):
                return {k:strip(v) for k,v in x.items() if not VOLATILE.search(k)}
            if isinstance(x,list):
                return [strip(v) for v in x]
            return x
        loose=hashlib.sha256(json.dumps(strip(obj),sort_keys=True).encode()).hexdigest()
    except Exception:
        loose=exact
    pairs[(rec.get('possibility_id'),rec.get('period_key'))].append((rec.get('revision_no') or 0,rec.get('report_id') or 0,d,n,exact,loose,rec.get('status')))
latest_bytes=superseded_bytes=dup_exact=dup_loose=dup_exact_bytes=dup_loose_bytes=0
super_by_day=collections.defaultdict(lambda:[0,0]);gaps=0;latest_by_status=collections.Counter()
for key,items in pairs.items():
    items.sort()
    nums=[i[0] for i in items]
    if nums!=list(range(1,len(items)+1)):
        gaps+=1
    for idx,it in enumerate(items):
        if idx==len(items)-1:
            latest_bytes+=it[3];latest_by_status[str(it[6])]+=1
        else:
            superseded_bytes+=it[3];super_by_day[it[2]][0]+=1;super_by_day[it[2]][1]+=it[3]
        if idx>0 and it[4]==items[idx-1][4]:
            dup_exact+=1;dup_exact_bytes+=it[3]
        if idx>0 and it[5]==items[idx-1][5]:
            dup_loose+=1;dup_loose_bytes+=it[3]
out['report']=dict(rows=sum(v[0] for v in by_day.values()),payload_bytes=sum(v[1] for v in by_day.values()),
    pairs=len(pairs),latest_bytes=latest_bytes,superseded_bytes=superseded_bytes,
    revision_numbering_not_contiguous=gaps,
    same_as_previous_exact=[dup_exact,dup_exact_bytes],same_as_previous_ignoring_time_fields=[dup_loose,dup_loose_bytes],
    by_generated_day=dict(sorted(by_day.items())),superseded_by_generated_day=dict(sorted(super_by_day.items())),
    by_status=dict(sorted(by_status.items())),latest_by_status={k:v for k,v in latest_by_status.items() if re.fullmatch('[a-z_]{1,32}|None',k)},
    seconds=round(time.monotonic()-started,1))
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
        raise ValueError('CENSUS_TIMEOUT')


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
        kst_date = created.astimezone(KST).date().isoformat()
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
        restored = docker('naver-db-census-restore', ['--user', user, '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m',
                          '-v', archive + ':/in/archive.zip:ro', '-v', DRILL + ':/drill', IMAGE,
                          'python', '-m', 'naver_runtime.restore_check', '--archive', '/in/archive.zip',
                          '--expected-kst-date', kst_date, '--output-dir', '/drill/out'], timeout=600)
        lines = restored.stdout.decode('utf-8', 'replace').strip().splitlines()
        status = json.loads(lines[-1]).get('status') if lines else None
        result['restore'] = dict(exit=restored.returncode, status=status if status in ('verified', 'failed') else 'OTHER',
                                 seconds=round(time.monotonic() - started, 1))
        if status != 'verified':
            raise ValueError('RESTORE_NOT_VERIFIED')
        started = time.monotonic()
        census = docker('naver-db-census-read', ['-i', '--user', user, '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=1g',
                        '-e', 'SQLITE_TMPDIR=/tmp', '-v', DRILL + ':/drill:ro', IMAGE, 'python', '-I', '-B', '-'],
                        data=CENSUS.encode(), timeout=840)
        lines = census.stdout.decode('utf-8', 'replace').strip().splitlines()
        result['census_exit'] = census.returncode
        result['census_seconds'] = round(time.monotonic() - started, 1)
        if census.returncode != 0 or not lines:
            tail = census.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:] if census.stderr else []
            result['census_error'] = re.sub(r'[^A-Za-z_:. ]', '', tail[0])[:80] if tail else None
            raise ValueError('CENSUS_FAILED')
        result['db'] = json.loads(lines[-1])
        result['ok'] = True
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', str(error)) else type(error).__name__
    finally:
        if made and os.path.isdir(DRILL) and not os.path.islink(DRILL):
            shutil.rmtree(DRILL, ignore_errors=True)
        result['drill_dir_removed'] = not os.path.lexists(DRILL)
        result['free_gb_after'] = free_gb()
        print('NAVER_DB_CENSUS_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
