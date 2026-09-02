#!/usr/bin/env node
/* 신고 #246: 실제 분석 공개 진입점(createDoSearch)에서 브랜드스토어 동등 판정 검증.
 * 실행: node frontend/tests/test_brand_store_parity.js */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'analysis.jsx'), 'utf8');
const appSource = fs.readFileSync(path.join(__dirname, '..', 'js', 'components', 'App.jsx'), 'utf8');
const analysisResultsSource = fs.readFileSync(
  path.join(__dirname, '..', 'js', 'components', 'AnalysisResults.jsx'),
  'utf8'
);
const seoDiagnosisSource = fs.readFileSync(
  path.join(__dirname, '..', 'js', 'components', 'SeoDiagnosisSection.jsx'),
  'utf8'
);
const context = {
  console,
  Promise,
  URL,
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

function runAnalysisWithTrace(targetUrl, suppliedProducts, capturedProductName, options) {
  const products = suppliedProducts === undefined ? makeProducts(targetUrl) : suppliedProducts;
  const trace = {
    productSearchCalls: 0,
    auditStatuses: [],
    shopProductStates: [],
    timerDelays: [],
  };
  const originalSetTimeout = context.setTimeout;
  if (options && options.runTimersImmediately) {
    context.setTimeout = (callback, delay) => {
      trace.timerDelays.push(delay);
      callback();
      return trace.timerDelays.length;
    };
  }
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
        trace.productSearchCalls += 1;
        if (options && typeof options.productSearchResponse === 'function') {
          return options.productSearchResponse(trace.productSearchCalls);
        }
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
      setAnalysisData: (data) => {
        if (data) resolve({ analysis: data, trace });
      },
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
      setShopProducts: (value) => { trace.shopProductStates.push(value); },
      setVolumeData: noop,
      setAuditStatus: (value) => { trace.auditStatuses.push(value); },
    };
    try {
      context.window.createDoSearch(deps)(
        '방울양배추', targetUrl, '', '', capturedProductName || ''
      );
    } catch (error) {
      reject(error);
    }
  }).finally(() => {
    context.setTimeout = originalSetTimeout;
  });
}

function runAnalysis(targetUrl, suppliedProducts, capturedProductName) {
  return runAnalysisWithTrace(targetUrl, suppliedProducts, capturedProductName)
    .then((result) => result.analysis);
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
  assert.strictEqual(result.seoDetail.trustworthy.items[0].pass, true);
  assert.strictEqual(result.seoDetail.trustworthy.items[3].pass, true);

  const directBrandProducts = products.map((product) => product.product_id === '9864738770'
    ? { ...product, product_url: url }
    : product);
  const directBrand = await runAnalysis(url, directBrandProducts);
  const catalogRow = result.competitorTable.find((row) => row.name === '신고 대상 정확 상품');
  const directRow = directBrand.competitorTable.find((row) => row.name === '신고 대상 정확 상품');
  assert.strictEqual(result.detailPageQuality.totalScore, directBrand.detailPageQuality.totalScore);
  assert.strictEqual(catalogRow.seoScore, directRow.seoScore);
}

async function testProductIdWinsBeforeUntrustedUrlSubstringMatch() {
  const url = 'https://brand.naver.com/vayapet/products/9864738770';
  const products = [
    {
      rank: 1,
      product_id: '1111111111',
      product_url: `https://mall.example/redirect?next=${url}`,
      product_name: '문자열만 포함한 다른 상품',
      store_name: '다른 판매처',
      price: 9900,
      brand: '다른 브랜드',
      category1: '생활/건강',
      category2: '반려동물',
      image_url: '',
    },
    {
      rank: 2,
      product_id: '9864738770',
      product_url: 'https://search.shopping.naver.com/main/products/9864738770',
      product_name: '정확한 상품 ID 대상',
      store_name: '바야 프리미엄 펫푸드',
      price: 12300,
      brand: '바야',
      category1: '생활/건강',
      category2: '반려동물',
      image_url: '',
    },
  ];

  const result = await runAnalysis(url, products);
  assert.strictEqual(result.targetProductInfo.product_name, '정확한 상품 ID 대상');
}

async function testProductUrlIdMatchUsesExactParsedIdAfterDirectIdMiss() {
  const url = 'https://brand.naver.com/vayapet/products/123';
  const products = [
    {
      rank: 1,
      product_id: '9123',
      product_url: 'https://search.shopping.naver.com/main/products/9123?next=/products/123',
      product_name: '부분 문자열만 겹친 다른 상품',
      store_name: '다른 판매처',
      price: 9900,
      brand: '다른 브랜드',
      category1: '생활/건강',
      category2: '반려동물',
      image_url: '',
    },
    {
      rank: 2,
      product_id: '',
      product_url: 'https://search.shopping.naver.com/catalog/123',
      product_name: '경로에서 정확히 추출한 상품',
      store_name: '바야 프리미엄 펫푸드',
      price: 12300,
      brand: '바야',
      category1: '생활/건강',
      category2: '반려동물',
      image_url: '',
    },
  ];

  const result = await runAnalysis(url, products);
  assert.strictEqual(result.targetProductInfo.product_name, '경로에서 정확히 추출한 상품');
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
  const result = await runAnalysis('https://m.brand.naver.com/vayapet/products/9864738770/');
  assert.strictEqual(result.seoDetail.trustworthy.items[0].pass, true);
  assert.strictEqual(result.seoDetail.trustworthy.items[3].pass, true);
}

async function testMobileSmartstoreKeepsExistingNaverStorePolicy() {
  const result = await runAnalysis('https://m.smartstore.naver.com/vayapet/products/9864738770/');
  assert.strictEqual(result.seoDetail.trustworthy.items[0].pass, true);
  assert.strictEqual(result.seoDetail.trustworthy.items[3].pass, true);
}

async function testUnrelatedHostContainingSmartstoreTextGetsNoNaverStoreCredit() {
  const url = 'https://mall.example/products/9864738770?next=https://smartstore.naver.com/vayapet';
  const result = await runAnalysis(url);

  assert.strictEqual(result.seoDetail.trustworthy.items[0].pass, false);
  assert.strictEqual(result.seoDetail.trustworthy.items[3].pass, false);
}

async function testNaverStoreCreditRequiresExactProductPathAndIgnoresNormalQueryHash() {
  const acceptedUrls = [
    'https://brand.naver.com/vayapet/products/9864738770?foo=1',
    'https://brand.naver.com/vayapet/products/9864738770#detail',
    'https://brand.naver.com/vayapet/products/9864738770?NaPm=tracking#detail',
  ];
  for (const url of acceptedUrls) {
    const result = await runAnalysis(url);
    assert.strictEqual(result.seoDetail.trustworthy.items[0].pass, true, url);
    assert.strictEqual(result.seoDetail.trustworthy.items[3].pass, true, url);
  }

  const rejectedUrls = [
    'https://brand.naver.com/',
    'https://brand.naver.com/vayapet',
    'https://brand.naver.com/vayapet/products/not-a-number',
    'https://brand.naver.com/vayapet/products/9864738770/reviews',
    'https://brand.naver.com/?next=/vayapet/products/9864738770',
    'https://brand.naver.com:443/vayapet/products/9864738770',
    'https://smartstore.naver.com/example/products/12345/reviews',
  ];

  for (const url of rejectedUrls) {
    const result = await runAnalysis(url);
    assert.strictEqual(result.seoDetail.trustworthy.items[0].pass, false, url);
    assert.strictEqual(result.seoDetail.trustworthy.items[3].pass, false, url);
  }
}

async function testProductIdExtractionReadsOnlyRealNvMidQueryParameter() {
  const extract = context.window.extractNaverProductIdFromUrl;
  assert.strictEqual(
    extract('https://search.shopping.naver.com/search/all?nvMid=123#detail'),
    '123'
  );
  assert.strictEqual(
    extract('https://search.shopping.naver.com/search/all#?nvMid=123'),
    ''
  );
  assert.strictEqual(
    extract('https://search.shopping.naver.com/search/all?next=https://x/?nvMid=123'),
    ''
  );
  assert.strictEqual(
    extract('https://search.shopping.naver.com/main/products/9123?next=https://x/?nvMid=123'),
    '9123'
  );
  assert.strictEqual(
    extract('https://search.shopping.naver.com/search/all?nvMid=12x'),
    ''
  );
}

async function testCapturedProductNameSurvivesExtensionBridgeAndMatchingFailure() {
  assert.match(
    appSource,
    /extSearchRef\.current\([\s\S]{0,220}String\(p\.product_name \|\| ''\)/
  );
  assert.match(
    appSource,
    /handleHomeSearch\(kw, url, undefined, html, productName\)/
  );

  const result = await runAnalysis(
    'https://brand.naver.com/vayapet/products/9864738770',
    [{
      rank: 1,
      product_id: '1111111111',
      product_url: 'https://mall.example/products/1111111111',
      product_name: '검색 결과의 다른 상품',
      store_name: '다른 판매처',
      price: 10000,
      brand: '다른 브랜드',
      category1: '생활/건강',
      category2: '반려동물',
      image_url: '',
    }],
    '캡처에서 확보한 브랜드 상품명'
  );

  assert.strictEqual(result.targetProductInfo.product_name, '캡처에서 확보한 브랜드 상품명');
  assert.strictEqual(result.productNameOpt.currentName, '캡처에서 확보한 브랜드 상품명');
  assert.strictEqual(result.seoDetail.trustworthy.items[0].pass, true);
  assert.strictEqual(result.seoDetail.trustworthy.items[3].pass, true);
  const priceScore = result.detailPageQuality.scoreBars.find(
    (row) => row.label === '가격 경쟁력'
  );
  assert.strictEqual(priceScore.score, 0, '미확인 0원을 저렴한 가격으로 채점하면 안 된다');
}

async function testCapturedHtmlMeasurementsOverrideIncompleteSearchFallback() {
  const fallback = {
    product_name: '동결건조 강아지 간식 : 바야 프리미엄 펫푸드',
    price: 0,
    brand: '',
    store_name: 'vayapet',
    category1: '',
    category2: '',
    image_url: '',
  };
  const merged = context.window.mergeSeoCachedProductInfo(
    fallback,
    '동결건조 강아지 간식',
    {
      price: 12300,
      category: '생활/건강>반려동물>강아지 간식>동결건조 간식',
      category1: '생활/건강',
      reviewCount: 540,
      rating: 4.88,
    }
  );

  assert.strictEqual(merged.product_name, '동결건조 강아지 간식');
  assert.strictEqual(merged.price, 12300);
  assert.strictEqual(merged.category1, '생활/건강');
  assert.strictEqual(merged.category2, '반려동물');
  assert.doesNotMatch(merged.product_name, / : /);
  assert.match(seoDiagnosisSource, /buildSeoAnalysisBody/);
}

async function testParsedBrandNameWinsOverOgTitleSuffixInRenderedConsumers() {
  assert.match(
    analysisResultsSource,
    /htmlDetailResult[\s\S]{0,180}productName[\s\S]{0,260}targetProductInfo/
  );
  assert.match(
    analysisResultsSource,
    /cachedProductName:\s*_resolvedProductName/
  );
  assert.match(
    analysisResultsSource,
    /cachedProductInfo:\s*_resolvedProductInfo/
  );
  const htmlNamePos = analysisResultsSource.indexOf('htmlDetailResult && htmlDetailResult.productName');
  const targetNamePos = analysisResultsSource.indexOf('analysisData && analysisData.targetProductInfo && analysisData.targetProductInfo.product_name');
  const advertiserNamePos = analysisResultsSource.indexOf('advertiserReport && advertiserReport.product_info && advertiserReport.product_info.product_name');
  assert.ok(htmlNamePos >= 0 && targetNamePos > htmlNamePos && advertiserNamePos > targetNamePos);
}

async function testEmptyShoppingResultStillKeepsCapturedBrandMeasurementsUsable() {
  const result = await runAnalysis(
    'https://brand.naver.com/vayapet/products/9864738770',
    [],
    '동결건조 강아지 간식'
  );
  assert.strictEqual(result.targetProductInfo.product_name, '동결건조 강아지 간식');
  const merged = context.window.mergeSeoCachedProductInfo(
    result.targetProductInfo,
    '동결건조 강아지 간식',
    {
      price: 12300,
      category: '생활/건강>반려동물>강아지 간식',
      category1: '생활/건강',
    }
  );
  assert.strictEqual(merged.price, 12300);
  assert.strictEqual(merged.category2, '반려동물');
  assert.match(source, /setShopProducts\(prods\)/);
  assert.match(source, /Array\.isArray\(data\.shopProducts\)/);
  assert.match(
    analysisResultsSource,
    /resolveSeoCachedRank\(shopProducts, analysisData\)/
  );
  assert.match(
    seoDiagnosisSource,
    /\[keyword, productUrl,[^\]]*loading[^\]]*htmlReviewData\]/
  );

  const withoutMeasurements = context.window.canAutoRunSeoDiagnosis({
    keyword: '방울양배추',
    productUrl: 'https://brand.naver.com/vayapet/products/9864738770',
    loading: false,
    cachedProductName: '동결건조 강아지 간식',
    shopProducts: [],
    htmlReviewData: null,
  });
  assert.strictEqual(withoutMeasurements, false);

  const exactRequest = context.window.buildSeoAnalysisBody({
    productUrl: 'https://brand.naver.com/vayapet/products/9864738770',
    keyword: '방울양배추',
    cachedRank: 0,
    cachedProductName: '동결건조 강아지 간식',
    cachedProductInfo: result.targetProductInfo,
    cachedTotalVolume: 1000,
    shopProducts: [],
    htmlReviewData: {
      price: 12300,
      category: '생활/건강>반려동물>강아지 간식',
      category1: '생활/건강',
      reviewCount: 540,
      rating: 4.88,
    },
  });
  assert.strictEqual(exactRequest.cached_rank, 0);
  assert.strictEqual(exactRequest.cached_product_info.price, 12300);
  assert.strictEqual(exactRequest.cached_product_info.category2, '반려동물');
  assert.strictEqual(exactRequest.cached_review_count, 540);
  assert.strictEqual(exactRequest.cached_rating, 4.88);
  assert.deepStrictEqual(exactRequest.cached_competitors, []);
}

async function testSuccessfulEmptyShoppingResultIsSettledWithoutRetryOrFailure() {
  const { analysis, trace } = await runAnalysisWithTrace(
    'https://brand.naver.com/vayapet/products/9864738770',
    [],
    '동결건조 강아지 간식',
    { runTimersImmediately: true }
  );

  assert.strictEqual(analysis.targetProductInfo.product_name, '동결건조 강아지 간식');
  assert.strictEqual(trace.productSearchCalls, 1);
  assert.deepStrictEqual(trace.timerDelays, []);
  assert.ok(trace.shopProductStates.some((value) => Array.isArray(value) && value.length === 0));
  const productAuditStates = trace.auditStatuses.flatMap((status) => (
    status && Array.isArray(status.items)
      ? status.items.filter((item) => item.name === '상품 검색').map((item) => item.st)
      : []
  ));
  assert.ok(productAuditStates.length > 0);
  assert.deepStrictEqual([...new Set(productAuditStates)], ['ok']);

  const settledProducts = trace.shopProductStates[trace.shopProductStates.length - 1];
  const cachedRank = context.window.resolveSeoCachedRank(settledProducts, analysis);
  const seoBody = context.window.buildSeoAnalysisBody({
    productUrl: 'https://brand.naver.com/vayapet/products/9864738770',
    keyword: '방울양배추',
    cachedRank,
    cachedProductName: analysis.targetProductInfo.product_name,
    cachedProductInfo: analysis.targetProductInfo,
    shopProducts: settledProducts,
    htmlReviewData: {
      price: 12300,
      category: '생활/건강>반려동물>강아지 간식',
      category1: '생활/건강',
    },
  });
  assert.strictEqual(cachedRank, 0);
  assert.strictEqual(seoBody.cached_rank, 0);
}

async function testFailedShoppingRequestStillRetriesAndSettlesOnLaterEmptySuccess() {
  const { trace } = await runAnalysisWithTrace(
    'https://brand.naver.com/vayapet/products/9864738770',
    [],
    '동결건조 강아지 간식',
    {
      runTimersImmediately: true,
      productSearchResponse(callNumber) {
        if (callNumber < 3) return Promise.reject(new Error('temporary network failure'));
        return Promise.resolve({ success: true, data: { products: [], total: 0 } });
      },
    }
  );

  assert.strictEqual(trace.productSearchCalls, 3);
  assert.deepStrictEqual(trace.timerDelays, [2500, 5000]);
  const productAuditStates = trace.auditStatuses.flatMap((status) => (
    status && Array.isArray(status.items)
      ? status.items.filter((item) => item.name === '상품 검색').map((item) => item.st)
      : []
  ));
  assert.deepStrictEqual(productAuditStates.slice(0, 3), ['retry', 'retry', 'ok']);
  assert.ok(!productAuditStates.includes('fail'));
}

const tests = [
  testBrandStoreUsesSameNaverStorePolicyAsSmartstore,
  testBrandStoreProductIdStillWinsBeforeStoreFallback,
  testProductIdWinsBeforeUntrustedUrlSubstringMatch,
  testProductUrlIdMatchUsesExactParsedIdAfterDirectIdMiss,
  testBrandStoreSlugFallbackWorksAfterProductIdMiss,
  testMobileBrandStoreAlsoUsesNaverStorePolicy,
  testMobileSmartstoreKeepsExistingNaverStorePolicy,
  testUnrelatedHostContainingSmartstoreTextGetsNoNaverStoreCredit,
  testNaverStoreCreditRequiresExactProductPathAndIgnoresNormalQueryHash,
  testProductIdExtractionReadsOnlyRealNvMidQueryParameter,
  testCapturedProductNameSurvivesExtensionBridgeAndMatchingFailure,
  testCapturedHtmlMeasurementsOverrideIncompleteSearchFallback,
  testParsedBrandNameWinsOverOgTitleSuffixInRenderedConsumers,
  testEmptyShoppingResultStillKeepsCapturedBrandMeasurementsUsable,
  testSuccessfulEmptyShoppingResultIsSettledWithoutRetryOrFailure,
  testFailedShoppingRequestStillRetriesAndSettlesOnLaterEmptySuccess,
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
