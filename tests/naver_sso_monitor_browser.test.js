/* 실제 Chromium opener/postMessage/PKCE 합성 회귀. 모든 HTTP는 메모리 fixture로 처리한다. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {webcrypto} = require('node:crypto');
const {chromium} = require('playwright');
const test = require('node:test');
const bootstrap = fs.readFileSync(path.join(__dirname, '../backend/naver_page/sso-bootstrap.js'), 'utf8');

test('Chromium: referrer가 없는 정상 opener도 정확한 메시지 출처와 PKCE로만 로그인한다', async () => {
  const browser = await chromium.launch(process.env.NAVER_SCREEN_CHROMIUM ? {executablePath:process.env.NAVER_SCREEN_CHROMIUM} : {});
  try {
    for (const origin of ['https://metainc.co.kr', 'http://metainc.co.kr', 'https://www.metainc.co.kr', 'http://www.metainc.co.kr']) {
      const context = await browser.newContext();
      const unexpected = [];
      try {
        await context.route('**/*', async route => {
          const url = new URL(route.request().url());
          if (url.href === origin + '/entry') return route.fulfill({contentType:'text/html', body:
            '<meta name="referrer" content="no-referrer"><button id="open">관제 열기</button><script>' +
            'window.ready=[];let popup;const requestId="R".repeat(43);' +
            'addEventListener("message",event=>{const data=event.data;' +
            'if(event.origin!=="https://watch.invalid"||event.source!==popup||!data||data.type!=="METAINC_SSO_READY"||data.requestId!==requestId)return;' +
            'window.ready.push(data);popup.postMessage({type:"METAINC_SSO_CODE",requestId,code:"C".repeat(43)},"https://watch.invalid");});' +
            'document.getElementById("open").onclick=()=>popup=window.open("https://watch.invalid/naver/?sso_start="+requestId,"_blank");</script>'});
          if (url.origin === 'https://watch.invalid' && url.pathname === '/naver/') return route.fulfill({contentType:'text/html', body:
            '<script src="/naver/sso-bootstrap.js"></script><script>' +
            'window.__metaincSso.consume().then(value=>window.result=value,error=>window.failure=error.entryCode);</script>'});
          if (url.origin === 'https://watch.invalid' && url.pathname === '/naver/sso-bootstrap.js') return route.fulfill({contentType:'application/javascript', body:bootstrap});
          unexpected.push(url.pathname); return route.abort();
        });
        const opener = await context.newPage();
        await opener.goto(origin + '/entry');
        const opened = context.waitForEvent('page');
        await opener.click('#open');
        const popup = await opened;
        await popup.waitForFunction(() => !!window.result || !!window.failure);
        const child = await popup.evaluate(() => ({referrer:document.referrer, result:window.result, failure:window.failure,
          openerDetached:window.opener === null, query:location.search}));
        assert.equal(child.referrer, '');
        assert.equal(child.failure, undefined);
        assert.equal(child.openerDetached, true);
        assert.equal(child.query, '');
        assert.equal(child.result.code, 'C'.repeat(43));
        const ready = await opener.evaluate(() => window.ready);
        assert.equal(ready.length, 1);
        const digest = await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(child.result.codeVerifier));
        assert.equal(Buffer.from(digest).toString('base64url'), ready[0].codeChallenge);
        assert.deepEqual(unexpected, []);
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
});
