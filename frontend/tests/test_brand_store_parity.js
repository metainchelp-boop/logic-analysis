#!/usr/bin/env node
/* 신고 #246: 실제 분석 공개 진입점(createDoSearch)에서 브랜드스토어 동등 판정 검증.
 * 실행: node frontend/tests/test_brand_store_parity.js */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'analysis.jsx'), 'utf8');
const context = {
  console,
  Promise,
  setTimeout,
  clearTimeout,
  fmt: (value) => Number(value || 0).toLocaleString('en-US'),
  getCTR: (rank) => rank <= 1 ? 0.08 : rank <= 5 ? 0.03 : rank <= 10 ? 0.015 : 0.003,
  compLabel: (value) => value || '-',
  CTR_TABLE: Array.from({ length: 80 }, (_, index) => Math.max(0.0005, 0.08 / (index + 1))),
  toast: { info() {}, success() {}, warn() {}, error() {} },
};
context.window = context;
vm.createContext(context);
vm.runInContext(source, context, { filename: 'analysis.jsx' });

function makeProducts(targetUrl) {
  const target = {
    rank: 1,
    product_id: '9864738770',
    product_url: targetUrl,
    product_name: '방울양배추 동결건조 강아지 간식',
    store_name: '바야 프리미엄 펫푸드',
    price: 12300,
    brand: '바야',
    category1: '생활/건강',
    category2: '반려동물',
    category3: '강아지간식',
    image_url: '',
  };
  return [target].concat(Array.from({ length: 79 }, (_, index) => ({
    rank: index + 2,
    product_id: String(2000000000 + index),
    product_url: `https://example.com/products/${2000000000 + index}`,
    product_name: `방울양배추 경쟁상품 ${index + 2}`,
    store_name: `경쟁몰${index + 2}`,
    price: 12000 + index,
    brand: '경쟁브랜드',
    category1: '생활/건강',
    category2: '반려동물',
    category3: '강아지간식',
    image_url: '',
  })));
}

function runAnalysis(targetUrl, suppliedProducts) {
  const products = suppliedProducts || makeProducts(targetUrl);
  context.api = {
    post(endpoint) {
      if (endpoint === '/keyword/volume') {
        return Promise.resolve({ success: true, data: [{
          monthlyPcQcCnt: 300,
          monthlyMobileQcCnt: 700,
          monthlyAvePcClkCnt: 3,
          monthlyAveMobileClkCnt: 7,
          plAvgDepth: 5,
          compIdx: '보통',
        }] });
      }
      if (endpoint === '/keywords/related') {
        return Promise.resolve({ success: true, data: {
          related_keywords: [], golden_keywords: [], total_found: 0,
        } });
      }
      if (endpoint === '/products/search') {
        return Promise.resolve({ success: true, data: { products, total: products.length } });
      }
      if (endpoint === '/datalab/analyze') {
        return Promise.resolve({ success: true, data: {
          gender: {}, age: {}, trend: {}, weekday: {},
        } });
      }
      return Promise.resolve({ success: false });
    },
  };

  return new Promise((resolve, reject) => {
    const noop = () => {};
    const deps = {
      cleanProductUrl: (url) => url,
      lastHtmlRef: { current: '' },
      products: [],
      searchIdRef: { current: 0 },
      setAdvertiserLoading: noop,
      setAdvertiserReport: noop,
      setAnalysisData: (data) => { if (data) resolve(data); },
      setCompanyName: noop,
      setDatalabData: noop,
      setDatalabLoading: noop,
      setHtmlDetailResult: noop,
      setHtmlReviewData: noop,
      setRankCheckResult: noop,
      setRelatedData: noop,
      setSearchLoading: noop,
      setSearchedKeyword: noop,
      setSearchedProductUrl: noop,
      setShopProducts: noop,
      setVolumeData: noop,
      setAuditStatus: noop,
    };
    try {
      context.window.createDoSearch(deps)('방울양배추', targetUrl, '', '');
    } catch (error) {
      reject(error);
    }
  });
}

async function testBrandStoreUsesSameNaverStorePolicyAsSmartstore() {
  const smart = await runAnalysis('https://smartstore.naver.com/vayapet/products/9864738770');
  const brand = await runAnalysis('https://brand.naver.com/vayapet/products/9864738770');

  assert.strictEqual(brand.seoDetail.trustworthy.score, smart.seoDetail.trustworthy.score);
  assert.strictEqual(brand.seoDetail.trustworthy.items[0].pass, true);
  assert.strictEqual(brand.seoDetail.trustworthy.items[3].pass, true);
  assert.strictEqual(brand.detailPageQuality.totalScore, smart.detailPageQuality.totalScore);
  assert.strictEqual(brand.competitorTable[0].seoScore, smart.competitorTable[0].seoScore);
}

async function testBrandStoreProductIdStillWinsBeforeStoreFallback() {
  const url = 'https://brand.naver.com/vayapet/products/9864738770';
  const products = [
    {
      rank: 1, product_id: '1111111111',
      product_url: 'https://brand.naver.com/vayapet/products/1111111111',
      product_name: '같은 스토어의 다른 상품', store_name: 'vayapet', price: 10000,
      brand: '바야', category1: '생활/건강', category2: '반려동물', image_url: '',
    },
    {
      rank: 2, product_id: '9864738770',
      product_url: 'https://search.shopping.naver.com/main/products/9864738770',
      product_name: '신고 대상 정확 상품', store_name: '바야 프리미엄 펫푸드', price: 12300,
      brand: '바야', category1: '생활/건강', category2: '반려동물', image_url: '',
    },
  ];

  const result = await runAnalysis(url, products);
  assert.strictEqual(result.targetProductInfo.product_name, '신고 대상 정확 상품');
}

async function testBrandStoreSlugFallbackWorksAfterProductIdMiss() {
  const url = 'https://brand.naver.com/vayapet/products/9864738770';
  const products = [{
    rank: 1, product_id: '1111111111',
    product_url: 'https://brand.naver.com/vayapet/products/1111111111',
    product_name: '브랜드스토어 동일 판매자 상품', store_name: '바야 프리미엄 펫푸드', price: 10000,
    brand: '바야', category1: '생활/건강', category2: '반려동물', image_url: '',
  }];

  const result = await runAnalysis(url, products);
  assert.strictEqual(result.targetProductInfo.product_name, '브랜드스토어 동일 판매자 상품');
}

async function testMobileBrandStoreAlsoUsesNaverStorePolicy() {
  const result = await runAnalysis('https://m.brand.naver.com/vayapet/products/9864738770');
  assert.strictEqual(result.seoDetail.trustworthy.items[0].pass, true);
  assert.strictEqual(result.seoDetail.trustworthy.items[3].pass, true);
}

async function testMobileSmartstoreKeepsExistingNaverStorePolicy() {
  const result = await runAnalysis('https://m.smartstore.naver.com/vayapet/products/9864738770');
  assert.strictEqual(result.seoDetail.trustworthy.items[0].pass, true);
  assert.strictEqual(result.seoDetail.trustworthy.items[3].pass, true);
}

async function testUnrelatedHostContainingSmartstoreTextGetsNoNaverStoreCredit() {
  const url = 'https://mall.example/products/9864738770?next=https://smartstore.naver.com/vayapet';
  const result = await runAnalysis(url);

  assert.strictEqual(result.seoDetail.trustworthy.items[0].pass, false);
  assert.strictEqual(result.seoDetail.trustworthy.items[3].pass, false);
}

const tests = [
  testBrandStoreUsesSameNaverStorePolicyAsSmartstore,
  testBrandStoreProductIdStillWinsBeforeStoreFallback,
  testBrandStoreSlugFallbackWorksAfterProductIdMiss,
  testMobileBrandStoreAlsoUsesNaverStorePolicy,
  testMobileSmartstoreKeepsExistingNaverStorePolicy,
  testUnrelatedHostContainingSmartstoreTextGetsNoNaverStoreCredit,
];
(async () => {
  let failed = 0;
  for (const test of tests) {
    try {
      await test();
      console.log(`PASS  ${test.name}`);
    } catch (error) {
      failed += 1;
      console.error(`FAIL  ${test.name}: ${error.stack || error}`);
    }
  }
  console.log(`\n${tests.length - failed}/${tests.length} passed`);
  process.exitCode = failed ? 1 : 0;
})();
