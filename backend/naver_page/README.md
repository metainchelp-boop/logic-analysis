# /naver/ 화면 파일 자리 (S13)

- 관제 화면 파일은 **여기**(`backend/naver_page/`)에 둔다 — `backend/static/` 안에 두지 않는다.
  `static/` 은 광고센터 정적 마운트(`app.mount("/", StaticFiles)`)라 `//naver/` 같은 다른 주소 철자로 스위치를 건너뛰고 열린다(S12 검토).
- 내주는 곳은 `app/routers/naver.py` 하나뿐 — 스위치(`NAVER_AUTO_WEB=on`)가 켜져 있을 때만 · 확장자 html·js·css·png·svg·woff2·ico 만 ·
  화면 머리(CSP `script-src 'self'` · `connect-src 'self'` · `Referrer-Policy: no-referrer` · `no-store`)가 붙는다.
- 화면은 인라인 스크립트 없이 파일로, **절대 경로**(`/naver/app.js`)로, 바깥 주소 0 으로 만든다.
- 이 파일(README.md)은 확장자 때문에 밖으로 나가지 않는다.
