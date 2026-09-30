/* 운영 접속 없음: 모든 URL은 Playwright route에서 응답하거나 차단한다. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { test } = require('node:test');
const { chromium } = require('playwright');

const bootstrap = fs.readFileSync(path.join(__dirname, '../js/sso-bootstrap.js'), 'utf8');
const requestId = 'R'.repeat(43), code = 'C'.repeat(43);
const erp = 'https://metainc.co.kr', logic = 'https://logic.metainc.co.kr';

async function fixture() {
    const browser = await chromium.launch({ headless: true, chromiumSandbox: true });
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const exchange = [], unexpected = [], probes = [];
    const parentHtml = `<meta name="referrer" content="origin"><button id="open">열기</button><script>
      window.popup=null; window.ready=null;
      document.querySelector('#open').onclick=function(){
        window.popup=window.open('about:blank','_blank');
        popup.document.write('<meta name="referrer" content="origin">'); popup.document.close();
        popup.location.replace('${logic}/?sso_start=${requestId}');
      };
      window.addEventListener('message',function(event){
        if(event.source===popup && event.origin==='${logic}' && event.data.type==='METAINC_SSO_READY' && event.data.requestId==='${requestId}')window.ready=event.data;
      });
      window.sendCode=function(){popup.postMessage({type:'METAINC_SSO_CODE',requestId:'${requestId}',code:'${code}'},'${logic}');};
      </script>`;
    const childHtml = `<meta name="referrer" content="no-referrer"><script>${bootstrap}</script>
      <script src="/probe.js"></script><script>
      window.ssoResult='waiting';
      window.__metaincSso.consume().then(function(credentials){
        return fetch('/api/auth/sso-code',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(credentials),credentials:'omit',cache:'no-store',redirect:'error'});
      }).then(function(r){window.ssoResult=r.ok?'success':'denied';}).catch(function(){window.ssoResult='denied';});
      </script>`;
    await context.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url());
        if (url.origin === erp && url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: parentHtml });
        if (url.origin === logic && url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: childHtml });
        if (url.origin === logic && url.pathname === '/probe.js') {
            probes.push(request.headers());
            return route.fulfill({ contentType: 'application/javascript', body: 'window.probeUrl=location.href;' });
        }
        if (url.origin === logic && url.pathname === '/api/auth/sso-code') {
            exchange.push({ body: request.postDataJSON(), headers: request.headers() });
            return route.fulfill({ contentType: 'application/json', body: '{"success":true}' });
        }
        if (url.origin === 'https://evil.invalid') {
            return route.fulfill({ contentType: 'text/html', body: `<script>
              opener.postMessage({type:'METAINC_SSO_CODE',requestId:'${requestId}',code:'${code}'},'${logic}');
            </script>` });
        }
        unexpected.push(url.origin + url.pathname);
        return route.abort();
    });
    return { browser, context, exchange, unexpected, probes };
}

test('실제 팝업의 referrer/opener/PKCE 교환과 즉시 주소 제거', async () => {
    const f = await fixture();
    try {
        const parent = await f.context.newPage();
        await parent.goto(erp);
        const popupPromise = parent.waitForEvent('popup');
        await parent.click('#open');
        const child = await popupPromise;
        await parent.waitForFunction(() => window.ready !== null);
        const ready = await parent.evaluate(() => window.ready);
        assert.equal(await child.evaluate(() => document.referrer), erp + '/');
        assert.equal(await child.evaluate(() => window.probeUrl), logic + '/');
        assert.equal(ready.codeVerifier, undefined);
        // 같은 출처여도 실제 opener가 아닌 창의 응답은 받아들이지 않는다.
        await parent.evaluate(({ code, requestId, logic }) => {
            const frame = document.createElement('iframe'); document.body.appendChild(frame);
            frame.contentWindow.target = window.popup;
            frame.contentWindow.eval(`target.postMessage(${JSON.stringify({ type: 'METAINC_SSO_CODE', requestId, code })},${JSON.stringify(logic)});`);
        }, { code, requestId, logic });
        await child.evaluate(() => new Promise(resolve => setTimeout(resolve, 50)));
        assert.equal(f.exchange.length, 0);
        const attackerPromise = f.context.waitForEvent('page');
        await child.evaluate(() => window.open('https://evil.invalid', '_blank'));
        const attacker = await attackerPromise;
        await attacker.waitForLoadState();
        await child.evaluate(() => new Promise(resolve => setTimeout(resolve, 50)));
        assert.equal(f.exchange.length, 0);
        await parent.evaluate(() => window.sendCode());
        await child.waitForFunction(() => window.ssoResult === 'success');
        assert.equal(f.exchange.length, 1);
        assert.equal(f.exchange[0].body.code, code);
        assert.equal(createHash('sha256').update(f.exchange[0].body.codeVerifier).digest('base64url'), ready.codeChallenge);
        assert.equal(f.exchange[0].headers.origin, logic);
        assert.equal(f.exchange[0].headers.cookie, undefined);
        assert.equal(await child.evaluate(() => window.opener), null);
        assert.equal(await child.evaluate(() => sessionStorage.length + localStorage.length), 0);
        assert.equal(f.probes[0].referer, undefined);
        assert.deepEqual(f.unexpected, []);
    } finally { await f.browser.close(); }
});

test('직접 코드 주소는 실제 브라우저에서도 교환하지 않는다', async () => {
    const f = await fixture();
    try {
        const child = await f.context.newPage();
        await child.goto(logic + '/?code=' + code);
        await child.waitForFunction(() => window.ssoResult === 'denied');
        assert.equal(child.url(), logic + '/');
        assert.equal(f.exchange.length, 0);
        assert.equal(f.probes[0].referer, undefined);
        assert.deepEqual(f.unexpected, []);
    } finally { await f.browser.close(); }
});
