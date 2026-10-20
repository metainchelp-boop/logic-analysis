"""네이버 관제 엔진 DB 증가 내역 — 읽기 전용 · 집계만 · 업체명·계정번호 미출력.

엔진 DB 를 컨테이너 안 UID 10001 로 mode=ro + query_only + 쓰기 거부 authorizer 로 연다.
보고서 사본 표(판 수·판 크기·날짜별 증가)와 작업 표(날짜·상태별 큰 칸 크기)를 센다.
호스트에서는 DB 파일의 정확한 바이트 수만 본다. 아무것도 지우거나 바꾸지 않는다.
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import json
import os
import re
import subprocess

MODE = 'naver-engine-dbgrowth-v1'
DB_HOST = '/var/lib/metainc/naver-engine/engine.db'

READER = r'''
import json,os,re,socket,sqlite3,time
from pathlib import Path
DAY=re.compile(r'\d{4}-\d{2}-\d{2}')
def auth(action,a1,a2,db,src):
    if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_TRANSACTION):
        return sqlite3.SQLITE_OK
    if action==sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (a2 or '').lower() in ('load_extension','readfile','writefile','shell','eval','fts3_tokenizer') else sqlite3.SQLITE_OK
    if action==sqlite3.SQLITE_PRAGMA and ((a1 or '').lower()=='table_info' or ((a1 or '').lower() in ('page_count','page_size','freelist_count','auto_vacuum') and a2 is None)):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY
def shape(v):
    return re.sub(r'[A-Za-z]','A',re.sub(r'\d','9',v))[:24] if isinstance(v,str) else type(v).__name__
out={};stage='start'
try:
    if os.geteuid()!=10001:
        raise ValueError('READER_IDENTITY')
    def no_network(*a,**k):
        raise ValueError('READER_NETWORK_FORBIDDEN')
    socket.socket.connect=socket.socket.connect_ex=no_network
    path=Path('/var/lib/naver-engine/engine.db')
    c=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,isolation_level=None,timeout=1)
    c.execute('PRAGMA query_only=ON');c.execute('PRAGMA busy_timeout=1000');c.execute('PRAGMA trusted_schema=OFF')
    if c.execute('PRAGMA query_only').fetchone()!=(1,):
        raise ValueError('READER_MODE')
    c.set_authorizer(auth)
    deadline=time.monotonic()+240
    def limit(seconds):
        q=time.monotonic()+seconds
        c.set_progress_handler(lambda:time.monotonic()>=q or time.monotonic()>=deadline,2000)
    def run(sql,args=(),seconds=40):
        limit(seconds)
        try:
            return c.execute(sql,args).fetchall()
        except sqlite3.OperationalError:
            return 'interrupted'
    try:
        stage='pages'
        size=c.execute('PRAGMA page_size').fetchone()[0];pages=c.execute('PRAGMA page_count').fetchone()[0]
        out['pages']=dict(page_size=size,page_count=pages,bytes=size*pages,freelist=c.execute('PRAGMA freelist_count').fetchone()[0],
                          auto_vacuum=c.execute('PRAGMA auto_vacuum').fetchone()[0])
        stage='report_days'
        T='naver_auto_report_snapshot'
        rows=run('SELECT substr(generated_at,1,10) d,count(*),sum(length(CAST(payload_json AS BLOB))) FROM '+T+' GROUP BY d ORDER BY d DESC LIMIT 25',seconds=90)
        out['report_by_day']=rows if rows=='interrupted' else [[d if isinstance(d,str) and DAY.fullmatch(d) else 'OTHER',n,b] for d,n,b in rows]
        stage='report_pairs'
        rows=run('SELECT count(*),max(report_id) FROM '+T+' GROUP BY possibility_id,period_key',seconds=40)
        if rows!='interrupted':
            buckets={}
            for n,_ in rows:
                k='1' if n==1 else '2' if n==2 else '3-5' if n<=5 else '6-10' if n<=10 else '11-20' if n<=20 else '21-50' if n<=50 else '51+'
                buckets[k]=buckets.get(k,0)+1
            out['report_pairs']=dict(pairs=len(rows),revisions_per_pair=buckets,max_revisions=max((n for n,_ in rows),default=0))
        stage='report_period_shapes'
        rows=run('SELECT period_key,count(*) FROM '+T+' GROUP BY period_key',seconds=40)
        if rows!='interrupted':
            shapes={}
            for k,n in rows:
                s=shape(k);item=shapes.setdefault(s,[0,0]);item[0]+=1;item[1]+=n
            out['report_period_shapes']={k:dict(periods=v[0],rows=v[1]) for k,v in sorted(shapes.items())}
        stage='report_superseded'
        rows=run("SELECT substr(s.generated_at,1,10) d,count(*),sum(length(CAST(s.payload_json AS BLOB))) FROM "+T+" s"
            " JOIN (SELECT possibility_id p,period_key k,max(report_id) m FROM "+T+" GROUP BY possibility_id,period_key) x"
            " ON s.possibility_id=x.p AND s.period_key=x.k AND s.report_id<x.m GROUP BY d ORDER BY d DESC LIMIT 25",seconds=120)
        out['report_superseded_by_day']=rows if rows=='interrupted' else [[d if isinstance(d,str) and DAY.fullmatch(d) else 'OTHER',n,b] for d,n,b in rows]
        stage='report_status'
        rows=run('SELECT status,review_status,count(*) FROM '+T+' GROUP BY 1,2',seconds=40)
        out['report_status']=rows if rows=='interrupted' else [[s if isinstance(s,str) and re.fullmatch('[a-z_]{1,32}',s) else 'OTHER',r if isinstance(r,str) and re.fullmatch('[a-z_]{1,32}',r) else 'OTHER',n] for s,r,n in rows]
        stage='jobs'
        jobs={}
        for t in ('naver_auto_structure_job','naver_auto_inspection_job','naver_auto_funnel_job','naver_auto_performance_job'):
            cols=[r[1] for r in c.execute('SELECT * FROM pragma_table_info(?)',(t,))]
            big=[x for x in ('progress_json','reasons_json','campaigns_json') if x in cols]
            expr=','.join('sum(coalesce(length(CAST("'+x+'" AS BLOB)),0))' for x in big)
            rows=run('SELECT cycle_day,status,count(*),'+expr+' FROM "'+t+'" GROUP BY cycle_day,status ORDER BY cycle_day DESC',seconds=60)
            if rows=='interrupted':
                jobs[t]='interrupted';continue
            per={}
            for r in rows:
                d=r[0] if isinstance(r[0],str) and DAY.fullmatch(r[0]) else 'OTHER'
                s=r[1] if isinstance(r[1],str) and re.fullmatch('[a-z_]{1,32}',r[1]) else 'OTHER'
                per.setdefault(d,{})[s]=[r[2]]+list(r[3:])
            jobs[t]=dict(columns=big,by_day=per)
        out['jobs']=jobs
        stage='done'
        if c.total_changes!=0:
            raise ValueError('READER_MUTATION')
    finally:
        c.close()
    out['mutations']=0
    print(json.dumps(out,sort_keys=True,ensure_ascii=True,separators=(',',':')))
except Exception as e:
    msg=str(e) if isinstance(e,ValueError) and re.fullmatch('READER_[A-Z_]{1,40}',str(e) or '') else type(e).__name__
    out.update(failure=msg,stage=stage)
    print(json.dumps(out,sort_keys=True,ensure_ascii=True,separators=(',',':')))
'''


def run(args, timeout=60, data=None, limit=8 * 1024 * 1024):
    result = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise ValueError('CMD_FAILED')
    return result.stdout[:limit]


def main():
    result = dict(mode=MODE, ok=False, mutations=0)
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        files = {}
        for suffix in ('', '-wal', '-shm'):
            try:
                files['engine.db' + suffix] = os.stat(DB_HOST + suffix).st_size
            except FileNotFoundError:
                files['engine.db' + suffix] = None
        result['files'] = files
        result['restore_cap_bytes'] = 2 * 1024 ** 3
        cid = run(['docker', 'ps', '--no-trunc', '--filter', 'label=com.docker.compose.project=naver-engine',
                   '--filter', 'label=com.docker.compose.service=naver-engine', '--format', '{{.ID}}']).decode().split()
        if len(cid) != 1:
            raise ValueError('ENGINE_NOT_FOUND')
        raw = run(['docker', 'exec', '-i', '--user', '10001:10001', cid[0], 'python', '-I', '-B', '-'],
                  data=READER.encode(), timeout=300, limit=512 * 1024)
        result['db'] = json.loads(raw.decode().strip().splitlines()[-1])
        result['ok'] = 'failure' not in result['db']
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', str(error)) else type(error).__name__
    print('NAVER_ENGINE_DBGROWTH_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
