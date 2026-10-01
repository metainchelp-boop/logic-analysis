"""관제 전용 ASGI 앱. 기존 광고센터 앱·DB 초기화·수집기를 실행하지 않는다.

기존 nginx는 /naver/ 및 /api/naver-auto만 이 앱의 UNIX 소켓으로 보낸다.
권한·읽기 전용 판정은 기존 중계 뒤의 관제 엔진이 수행한다.
"""
from fastapi import FastAPI

from .routers.naver import router

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
app.include_router(router)
