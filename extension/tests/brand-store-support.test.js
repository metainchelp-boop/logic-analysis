'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const extensionDir = path.resolve(__dirname, '..');
const manifest = JSON.parse(
  fs.readFileSync(path.join(extensionDir, 'manifest.json'), 'utf8')
);
const popupSource = fs.readFileSync(path.join(extensionDir, 'popup.js'), 'utf8');
const popupHtml = fs.readFileSync(path.join(extensionDir, 'popup.html'), 'utf8');
const productContentSource = fs.readFileSync(
  path.join(extensionDir, 'content-smartstore.js'),
  'utf8'
);

function test(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    console.error(error.stack);
    process.exitCode = 1;
  }
}

function runPopup(url) {
  const sentMessages = [];
  let closeCount = 0;
  const elements = {
    'pg-status': { textContent: '', className: '' },
    'send-btn': {
      disabled: true,
      addEventListener: function (eventName, callback) {
        if (eventName === 'click') this.click = callback;
      }
    },
    'extension-version': { textContent: '' }
  };
  const context = {
    URL,
    chrome: {
      runtime: {
        getManifest: function () { return manifest; }
      },
      tabs: {
        query: function (_query, callback) {
          callback([{ id: 246, url: url }]);
        },
        sendMessage: function (tabId, message, callback) {
          sentMessages.push({ tabId: tabId, message: message });
          if (callback) callback();
        }
      }
    },
    document: {
      addEventListener: function (eventName, callback) {
        assert.equal(eventName, 'DOMContentLoaded');
        callback();
      },
      getElementById: function (id) {
        return elements[id];
      }
    },
    window: { close: function () { closeCount += 1; } }
  };

  vm.runInNewContext(popupSource, context, { filename: 'extension/popup.js' });
  elements.sentMessages = sentMessages;
  elements.getCloseCount = function () { return closeCount; };
  return elements;
}

function runProductContentScript(rawUrl) {
  const parsedUrl = new URL(rawUrl);
  const elements = new Map();

  function makeElement(id) {
    return {
      id: id || '',
      value: '',
      textContent: '',
      className: '',
      disabled: false,
      innerHTML: '',
      addEventListener: function () {},
      focus: function () {},
      remove: function () { elements.delete(this.id); }
    };
  }

  const body = makeElement('body');
  body.scrollHeight = 1000;
  body.appendChild = function (element) {
    elements.set(element.id, element);
    const idPattern = /id="([^"]+)"/g;
    let match;
    while ((match = idPattern.exec(element.innerHTML))) {
      if (!elements.has(match[1])) elements.set(match[1], makeElement(match[1]));
    }
  };

  const fakeWindow = { scrollTo: function () {} };
  fakeWindow.top = fakeWindow;
  const context = {
    chrome: {
      runtime: {
        onMessage: { addListener: function () {} },
        sendMessage: function () {},
        lastError: null
      }
    },
    document: {
      body: body,
      documentElement: { outerHTML: '<html></html>' },
      title: '테스트 상품',
      createElement: function () { return makeElement(''); },
      getElementById: function (id) { return elements.get(id) || null; },
      querySelector: function () { return null; }
    },
    location: {
      href: rawUrl,
      pathname: parsedUrl.pathname
    },
    Promise,
    setInterval: function () { return 1; },
    setTimeout,
    window: fakeWindow
  };

  vm.runInNewContext(productContentSource, context, {
    filename: 'extension/content-smartstore.js'
  });
  return elements.has('metainc-logic-fab');
}

test('supported Naver Store hosts receive the product-page content script', function () {
  const supportedMatches = [
    'https://smartstore.naver.com/*',
    'https://brand.naver.com/*',
    'https://m.brand.naver.com/*'
  ];
  const productScript = manifest.content_scripts.find(function (entry) {
    return entry.js && entry.js.includes('content-smartstore.js');
  });

  assert.ok(productScript, 'product-page content script must be declared');
  supportedMatches.forEach(function (match) {
    assert.ok(manifest.host_permissions.includes(match), `missing host permission: ${match}`);
    assert.ok(productScript.matches.includes(match), `missing content-script match: ${match}`);
  });
});

test('popup enables only exact product pages on supported Naver Store hosts', function () {
  const supportedUrls = [
    'https://smartstore.naver.com/metainc/products/12345',
    'https://brand.naver.com/vayapet/products/9864738770?NaPm=sample#detail',
    'https://m.brand.naver.com/vayapet/products/9864738770/'
  ];
  const blockedUrls = [
    'https://brand.naver.com/vayapet',
    'https://brand.naver.com/vayapet/products/not-a-number',
    'https://brand.naver.com/vayapet/products/9864738770/reviews',
    'https://evilbrand.naver.com/vayapet/products/9864738770',
    'https://brand.naver.com.example.com/vayapet/products/9864738770'
  ];

  supportedUrls.forEach(function (url) {
    const elements = runPopup(url);
    assert.equal(elements['pg-status'].textContent, '네이버 스토어 상품 ✓', url);
    assert.equal(elements['send-btn'].disabled, false, url);
  });
  blockedUrls.forEach(function (url) {
    const elements = runPopup(url);
    assert.equal(elements['pg-status'].textContent, '상품 페이지 아님', url);
    assert.equal(elements['send-btn'].disabled, true, url);
  });
});

test('product content script injects its panel only on exact product paths', function () {
  assert.equal(
    runProductContentScript('https://brand.naver.com/vayapet/products/9864738770'),
    true
  );
  assert.equal(
    runProductContentScript('https://m.brand.naver.com/vayapet/products/9864738770/'),
    true
  );
  assert.equal(
    runProductContentScript('https://brand.naver.com/vayapet/products/9864738770/reviews'),
    false
  );
  assert.equal(
    runProductContentScript('https://brand.naver.com/section/vayapet/products/9864738770'),
    false
  );
});

test('popup displays the bumped manifest version instead of a hardcoded version', function () {
  assert.notEqual(manifest.version, '1.1.2');
  assert.match(popupHtml, /<small id="extension-version"><\/small>/);
  assert.doesNotMatch(popupHtml, /<small[^>]*>v\d/);

  const elements = runPopup('https://brand.naver.com/vayapet/products/9864738770');
  assert.equal(elements['extension-version'].textContent, `v${manifest.version}`);
});

test('supported product pages preserve the existing popup-to-capture trigger', function () {
  const elements = runPopup('https://brand.naver.com/vayapet/products/9864738770');

  assert.equal(typeof elements['send-btn'].click, 'function');
  elements['send-btn'].click();
  assert.equal(elements.sentMessages.length, 1);
  assert.equal(elements.sentMessages[0].tabId, 246);
  assert.equal(elements.sentMessages[0].message.type, 'METAINC_TRIGGER');
  assert.equal(elements.getCloseCount(), 1);
});
