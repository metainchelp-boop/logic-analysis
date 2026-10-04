#!/usr/bin/env python3
"""로컬 합성 보고서 검수 서버. 운영 파일·계정·외부 API를 사용하지 않는다.

실제 UI/WSGI/메모리 Store를 연결한다. 이 파일은 배포 대상이 아니다.
"""
import argparse
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import sqlite3
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
from app import naver_relay as Relay
from app.naver_auto import matching as M
from naver_engine import store as S, reporting as R, web as W, erp_read as E, naver_read as N, session as SE
from naver_engine.tests import test_web as TW, test_alerts as TA, test_account_catalog as TC
from naver_engine.tests.test_catalog_links import make_fixture
from naver_engine.tests.test_reporting import daily_rows


def create_preview():
    fixture = make_fixture(accounts=6, managed=5, campaigns=0)
    st, clock = fixture.store, fixture.clock
    clock.advance(max(1, (datetime.now(R.KST)-clock.now()).total_seconds()))
    now = clock.now()
    names = {11:"모닝테이블 · 합성 예시",12:"온유생활 · 합성 예시",13:"하루정원 · 합성 예시",14:"소담공방 · 합성 예시",15:"계정 연결 확인 · 합성 예시"}
    groups = {TW.A:11,TW.A+1:11,TW.A+2:12,TW.A+3:13,TW.A+4:14,TW.A+5:14}
    for decision in st.link_decisions()[0]:
        st.revoke_decision(decision.decision_id,0,now,"로컬 합성 자료 구성")
    st.record_org(TA.org_body(now,owners=[TA.owner(pid,101 if pid == 13 else 100) for pid in names]),now)
    children = {cid:{"customerId":cid,"adAccountNo":8000000+offset,"adAccountName":names[pid]+(" · 쇼핑" if offset == 1 else " · 검색")}
                for offset,(cid,pid) in enumerate(groups.items())}
    st.record_accounts(N.ChildAccounts(children,{1:6},()),now)
    st.record_account_catalog({"generated_at":now.isoformat(),"total":len(names),"complete":True,
        "items":[TC.company(pid,"사후관리" if pid == 12 else "진행중",company_name=name) for pid,name in names.items()]},
        [E.NaverIdRow(pid,M.VENDOR_NAVER,str(cid)) for cid,pid in groups.items()],now)
    for cid,pid in groups.items():
        st.record_decision(pid,cid,"confirmed",0,now)
    rid = 0
    for kind in ("weekly","monthly"):
        period = R.period(kind,now.date())
        while period.due_at > now:
            period = R.period(kind,period.start-timedelta(days=1))
        prior = R.previous_period(period)
        for pid in (11,12,13):
            cids = [cid for cid,company in groups.items() if company == pid]
            rows, older = daily_rows(period,cids), daily_rows(prior,cids)
            for seq,collection in enumerate((rows,older)):
                for index,row in enumerate(collection):
                    factor = 1 if row["customer_id"] == TW.A else .3
                    row.update(checked_at=now.isoformat(),spend=round((60000 if seq == 0 else 70000)*factor),
                        imp=round(15000*factor),clk=round(400*factor),conversions=round(20*factor),conversion_value=round(240000*factor))
                    if pid == 12:
                        row.update(conversion_complete=False,conversions=None,conversion_value=None)
            payload = R.snapshot(period,cids,rows,now,previous_customers=cids,previous_rows=older)
            payload.update(revision_no=1,validation={"status":"complete","last_checked_at":now.isoformat(),"last_attempt_at":now.isoformat()})
            for account in payload["_account_reports"].values():
                account["validation"] = payload["validation"]
            rid += 1
            st._conn.execute("""INSERT INTO naver_auto_report_snapshot
                (report_id,possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
                VALUES(?,?,?,?,?,?,?,?)""",(rid,pid,period.key,payload["revision_fingerprint"],now.isoformat(),payload["status"],payload["review_status"],json.dumps(payload,ensure_ascii=False)))

    signer = SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET))
    profiles = TW.FakeProfileErp()
    profiles.person(TW.tok(1),0,manager=True,teams=((0,None),))
    profiles.person(TW.tok(3),100)
    def read():
        connection = sqlite3.connect(":memory:",isolation_level=None)
        st._conn.backup(connection)
        return S.Store(connection,":memory:",None,writer=False,clock=clock.now)
    app = W.App(open_read=read,write=lambda fn:fn(st),signer=signer,
        profiles=TW.EP.ErpProfileReader(transport=profiles,env=TW.EXCHANGE_ENV),clock=clock.now,
        owner_verification=True,verified_linking=True)
    return app,st


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=0)
    args = parser.parse_args()
    app,store = create_preview()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self): self.handle_api()
        def do_POST(self): self.handle_api()
        def send(self,status,headers,body):
            self.send_response(status)
            for name,value in headers: self.send_header(name,value)
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def handle_api(self):
            path,_,query = self.path.partition("?")
            if path == "/naver/sso-bootstrap.js":
                body = "window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve("+json.dumps({"code":TW.tok(1),"codeVerifier":TW.VERIFIER})+")};"
                return self.send(200,[("Content-Type","text/javascript; charset=utf-8"),*Relay.PAGE_HEADERS],body.encode())
            if path.startswith(W.PREFIX+"/"):
                body = self.rfile.read(int(self.headers.get("Content-Length",0)))
                env = {"REQUEST_METHOD":self.command,"PATH_INFO":path,"QUERY_STRING":query,
                    "CONTENT_LENGTH":str(len(body)),"CONTENT_TYPE":self.headers.get("Content-Type",""),
                    "wsgi.input":io.BytesIO(body),"HTTP_AUTHORIZATION":self.headers.get("Authorization","")}
                response = {}
                def start(status,headers): response.update(status=int(status.split()[0]),headers=headers)
                output = b"".join(app(env,start))
                return self.send(response["status"],response["headers"],output)
            if path.startswith("/naver/"):
                file = Relay.page_file(ROOT/"backend/naver_page",path[len("/naver/"):])
                if file:
                    body = file.read_bytes()
                    if file.name == "index.html":
                        body = body.replace(b"<body>",b'<body><p class="nr-notice">'+"로컬 검수 · 모든 업체·성과는 합성 예시입니다. 운영 데이터/네이버 호출 없음.".encode()+b"</p>")
                    return self.send(200,[("Content-Type",Relay.page_type(file)),*Relay.PAGE_HEADERS],body)
            return self.send(404,[],b"not found")
    server = HTTPServer(("127.0.0.1",args.port),Handler)
    print("LOCAL_REPORT_PREVIEW="+f"http://127.0.0.1:{server.server_port}/naver/reports",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); store.close()


if __name__ == "__main__": main()
