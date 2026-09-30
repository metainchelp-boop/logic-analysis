"""임시 DB만 사용하는 실제 광고센터 인증 라우터 검증. app.main/수집기 미기동."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import Base, engine, SessionLocal
from app import models, security, sso_exchange
from app.routers import auth

Base.metadata.create_all(bind=engine)
app=FastAPI()
app.include_router(auth.router,prefix='/api')
client=TestClient(app)
CODE,VERIFIER='C'*42+'A','V'*42+'A'
seen=set()
current={'id':'person','name':'Example','idx':0,'isManager':False,'authority':{'name':'관리'},'teamList':[{'name':'광고 관리팀'}]}

def erp(req,timeout):
    payload=json.loads(req.data)
    assert payload['destination']=='AD_CENTER' and payload['codeVerifier']==VERIFIER
    assert req.get_header('X-sso-client-key')==os.environ['SSO_AD_CENTER_CLIENT_KEY']
    if payload['code'] in seen: return 401,b''
    seen.add(payload['code'])
    return 200,json.dumps({'status':200,'result':current}).encode()

def post(code=CODE, **kwargs):
    return client.post('/api/auth/sso-code',json={'code':code,'codeVerifier':VERIFIER}, **kwargs)

out={}
with patch.object(sso_exchange,'_send',side_effect=erp):
    response=post()
    out['created']=response.status_code
    out['role']=response.json()['user']['role']
    out['cache']=response.headers.get('cache-control')
    out['replay']=post().status_code
    with SessionLocal() as db:
        user=db.query(models.User).filter(models.User.email=='erp:person').one()
        user.role='admin';db.commit()
    current['teamList']=[]
    out['admin_preserved']=post('A'*43).json()['user']['role']
    current['id']='viewer'
    out['viewer']=post('B'*42+'A').json()['user']['role']
    out['cross_origin']=post('D'*42+'A',headers={'Origin':'https://evil.invalid'}).status_code
    bad=client.post('/api/auth/sso-code',json={'code':'PRIVATE_BAD_MARKER','codeVerifier':VERIFIER})
    out['bad_shape']=bad.status_code
    out['no_echo']='PRIVATE_BAD_MARKER' not in bad.text
    assert bad.headers.get('cache-control') == 'no-store'
    duplicate=client.post('/api/auth/sso-code',content=json.dumps({'code':CODE,'codeVerifier':VERIFIER})[:-1]+',"code":"'+CODE+'"}',headers={'content-type':'application/json'})
    assert duplicate.status_code == 400
    out['too_big']=client.post('/api/auth/sso-code',content=b'x'*1025,headers={'content-type':'application/json'}).status_code
    with patch.object(auth,'_erp_profile',return_value=('ok',current)):
        out['legacy']=client.post('/api/auth/sso',json={'token':'legacy-token'}).status_code
print(json.dumps(out))
