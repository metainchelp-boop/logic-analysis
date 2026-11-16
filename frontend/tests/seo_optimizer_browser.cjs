/* Offline React DOM regression. No real sites, provider calls, installs, or writes
 * to the shared dependency tree. Production uses React 18.2.0; this harness uses
 * the available read-only React 18.3.1 UMD runtime by default. React 18.2.0 can
 * be selected with SEO_TEST_REACT_DEPS; the JSX transformer stays independent. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const deps = process.env.SEO_TEST_REACT_DEPS || '/Users/sinyosub/Documents/Codex/2026-09-14/new-chat/work/homepage-tones-frontend/node_modules';
const runtimeDeps = process.env.SEO_TEST_RUNTIME_DEPS || '/Users/sinyosub/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const transformDeps = process.env.SEO_TEST_TRANSFORM_DEPS || deps;
const { transformSync } = require(path.join(transformDeps, 'esbuild'));
const reactVersion = require(path.join(deps, 'react/package.json')).version;
const { chromium } = require(path.join(runtimeDeps, 'playwright'));
const sourceDir = path.join(__dirname, '../js/components');

async function main() {
    const browser = await chromium.launch({ headless: true, channel: 'chrome' });
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    let externalRequests = 0;
    await context.route('**/*', route => { externalRequests++; return route.abort(); });
    const page = await context.newPage();
    page.setDefaultTimeout(2500);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    try {
        await page.setContent('<!doctype html><html lang="ko"><body><div id="root"></div></body></html>');
        for (const file of ['styles.css', 'report-theme.css', 'place.css']) {
            await page.addStyleTag({ content: fs.readFileSync(path.join(__dirname, '../css', file), 'utf8') });
        }
        for (const file of ['react/umd/react.development.js', 'react-dom/umd/react-dom.development.js']) {
            await page.addScriptTag({ content: fs.readFileSync(path.join(deps, file), 'utf8') });
        }
        await page.evaluate(() => {
            window.calls = [];
            window.pending = {};
            window.delayed = {};
            window.notices = [];
            window.saved = [];
            window.toast = { warn: text => notices.push(text), success: text => notices.push(text) };
            window.SeoDiagnosisSection = ({ keyword }) => React.createElement('div', { 'data-testid': 'diagnosis' }, keyword);
            window.LoadingSpinner = ({ text }) => React.createElement('div', null, text);
            window.api = {
                get: async function(url) {
                    calls.push({ method: 'GET', url });
                    if (delayed[url]) return new Promise(resolve => { pending[url] = resolve; });
                    if (url === '/cd/registered-clients') return { success: true, data: [
                        { id: 1, name: '가상 업체 가', main_keywords: '기존 키워드' },
                        { id: 2, name: '가상 업체 나', main_keywords: '다른 키워드' }
                    ] };
                    if (url === '/seo/rules') return { success: true, data: { rules_text: '구 기준', version: 'legacy-v1', recommended_rules_text: '개정 기준', recommended_version: 'rules-v2', is_recommended_active: false } };
                    if (url.endsWith('/products')) return { success: true, data: [{
                        product_key: 'p' + url.split('/')[3], product_url: 'https://example.invalid/products/123', keyword: '연결 키워드', product_name: '확인 상품', brand: '확인 브랜드', category: '확인 카테고리', features: '확인 속성',
                        current_values: { product_name: '확인 상품', tags: null, page_title: '현재 제목', meta_description: null }
                    }] };
                    if (url.endsWith('/saved')) return { success: true, data: url.includes('/1/') ? saved : [] };
                    throw new Error('Unexpected fake GET: ' + url);
                },
                post: async function(url, body) {
                    calls.push({ method: 'POST', url, body });
                    if (delayed[url]) return new Promise(resolve => { pending[url] = resolve; });
                    if (url === '/seo/generate') return { success: true, data: window.lastGeneration = {
                        keyword: body.keyword, product_names: ['추천 상품', '다른 추천 상품'], tags: ['관련 태그'], category: '확인 카테고리', rationale: ['사실 기반'], generation_id: 'draft-1', product_url: body.product_url,
                        current_values: body.current_values, rules_version: 'rules-v2',
                        recommendation: { product_name: '추천 상품', tags: ['관련 태그'], page_title: '추천 제목', meta_description: '추천 설명' },
                        field_reasons: { product_name: ['중복을 정리'], tags: ['관련어만 사용'], page_title: ['고유한 제목'], meta_description: ['사실적인 설명'] },
                        evidence: { status: 'partial', label: '부분 자료 2/20', coverage: 2, collected_date: '2026-10-18', observed_at: null, surface: null, ads_verified: false, verified_top20: false, products: [{ rank: 1, product_name: '관측 상품', product_url: 'https://example.invalid/one' }], common_terms: [{ term: '관련어', count: 1, ratio: 0.5 }], notes: ['광고 제외 미확인'] }
                    } };
                    if (url === '/seo/save-to-client') {
                        saved = [{ id: 9, keyword: body.keyword, product_name: body.product_name, tags: body.tags, created_at: '2026-10-18', created_by: '가상 검토자', review: { approved_values: body.approved_values, decisions: body.decisions, product_url: body.product_url, rules_version: 'rules-v2', reviewed_by: '가상 검토자', reviewed_at: '2026-10-18', original: lastGeneration } }];
                        return { success: true, data: { id: 9 } };
                    }
                    if (url === '/seo/rules/activate-recommended') return { success: true, data: { rules_text: '개정 기준', version: 'rules-v2', recommended_rules_text: '개정 기준', recommended_version: 'rules-v2', is_recommended_active: true } };
                    throw new Error('Unexpected fake POST: ' + url);
                },
                put: async function(url, body) { calls.push({ method: 'PUT', url, body }); return { success: true, data: { rules_text: body.rules_text, version: 'edited-v3' } }; }
            };
            window.copied = '';
            Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { copied = text; } } });
            window.csvText = '';
            URL.createObjectURL = blob => { blob.text().then(text => { csvText = text; }); return 'blob:offline-test'; };
            URL.revokeObjectURL = () => {};
            HTMLAnchorElement.prototype.click = function() {};
        });
        for (const file of ['SeoOptimizerPage.jsx', 'SeoRulesSection.jsx']) {
            await page.addScriptTag({ content: transformSync(fs.readFileSync(path.join(sourceDir, file), 'utf8'), { loader: 'jsx' }).code });
        }
        await page.evaluate(() => {
            window.root = ReactDOM.createRoot(document.getElementById('root'));
            window.mountOptimizer = () => root.render(React.createElement(SeoOptimizerPage, { currentUser: { role: 'manager' } }));
            mountOptimizer();
        });
        await page.locator('select').first().selectOption('1');
        await page.getByLabel('연결 상품').selectOption('p1');
        assert.equal(await page.getByLabel('대표 키워드').inputValue(), '연결 키워드');
        await page.getByText('상품 사실·현재값 확인 및 보완', { exact: true }).click();
        assert.equal(await page.getByLabel('브랜드', { exact: true }).inputValue(), '확인 브랜드');
        assert.equal(await page.getByLabel('현재 판매자 태그').inputValue(), '');
        await page.getByRole('button', { name: '검수 추천 생성', exact: true }).click();
        await page.getByTestId('seo-review').waitFor();
        if (process.env.SEO_TEST_SCREENSHOT) await page.screenshot({ path: process.env.SEO_TEST_SCREENSHOT, fullPage: true });
        for (const label of ['상품명', '판매자 태그', '페이지 타이틀', '메타 디스크립션']) {
            assert.equal(await page.getByLabel(label + ' 검토 결정', { exact: true }).inputValue(), 'hold');
        }
        assert.equal(await page.getByRole('button', { name: '승인본 저장', exact: true }).isDisabled(), true);
        assert.equal(await page.getByRole('button', { name: '승인본 복사', exact: true }).isDisabled(), true);
        await page.getByLabel('상품명 검토 결정', { exact: true }).selectOption('adopt');
        await page.getByLabel('페이지 타이틀 검토 결정', { exact: true }).selectOption('edit');
        await page.getByLabel('페이지 타이틀 수정값', { exact: true }).fill('  =수식처럼 보이는 검토 제목  ');
        await page.getByRole('checkbox').check();
        await page.evaluate(() => { delayed['/seo/save-to-client'] = true; });
        await page.getByRole('button', { name: '승인본 저장', exact: true }).evaluate(button => { button.click(); button.click(); });
        await page.waitForFunction(() => !!pending['/seo/save-to-client']);
        let saves = await page.evaluate(() => calls.filter(call => call.url === '/seo/save-to-client'));
        assert.equal(saves.length, 1, 'same-tick duplicate approval must not call API twice');
        assert.deepEqual(saves[0].body.approved_values, { product_name: '추천 상품', tags: null, page_title: '=수식처럼 보이는 검토 제목', meta_description: null });
        assert.deepEqual(saves[0].body.decisions, { product_name: 'adopt', tags: 'hold', page_title: 'edit', meta_description: 'hold' });
        assert.equal(saves[0].body.reviewed, true);
        await page.evaluate(() => {
            const body = calls.find(call => call.url === '/seo/save-to-client').body;
            saved = [{ id: 9, keyword: body.keyword, product_name: body.product_name, tags: body.tags, created_at: '2026-10-18', created_by: '가상 검토자', review: { approved_values: body.approved_values, decisions: body.decisions, product_url: body.product_url, rules_version: 'rules-v2', reviewed_by: '가상 검토자', reviewed_at: '2026-10-18', original: lastGeneration } }];
            pending['/seo/save-to-client']({ success: true, data: { id: 9 } });
            delete delayed['/seo/save-to-client'];
        });
        await page.getByRole('button', { name: '승인본 저장됨', exact: true }).waitFor();
        await page.getByRole('button', { name: '승인본 복사', exact: true }).click();
        await page.waitForFunction(() => copied.includes('페이지 타이틀: =수식처럼 보이는 검토 제목'));
        assert.match(await page.evaluate(() => copied), /판매자 태그: 미확인/);
        await page.getByRole('button', { name: '검수 결과 CSV', exact: true }).click();
        await page.waitForFunction(() => csvText.length > 0);
        const csv = await page.evaluate(() => csvText);
        for (const text of ['메타 디스크립션', '변경 이유', '검토 상태', '2026-10-18', 'rules-v2']) {
            assert.ok(csv.includes(text), 'CSV contains ' + text);
        }
        assert.ok(csv.includes('"\'=수식처럼 보이는 검토 제목"'), 'CSV prefixes formula-like content');
        await page.evaluate(() => { root.unmount(); root = ReactDOM.createRoot(document.getElementById('root')); mountOptimizer(); });
        await page.getByLabel('업체 선택', { exact: true }).selectOption('1');
        await page.getByText(/승인 기록 · rules-v2/).click();
        await page.getByText('저장 당시 추천 원본·근거', { exact: true }).click();
        await page.getByText(/자료 상태: 부분 자료 2\/20/).waitFor();
        await page.getByRole('button', { name: '저장된 승인본 복사', exact: true }).click();
        assert.match(await page.evaluate(() => copied), /메타 디스크립션: 미확인/);
        await page.getByRole('button', { name: '🩺 SEO 진단·점검', exact: true }).click();
        await page.getByRole('button', { name: '키워드 적용', exact: true }).click();
        assert.equal(await page.getByTestId('diagnosis').innerText(), '기존 키워드');
        await page.getByRole('button', { name: '✨ SEO 생성', exact: true }).click();

        // A late generation cannot reappear after a keyword or fact is changed.
        await page.getByLabel('연결 상품').selectOption('p1');
        await page.evaluate(() => { delayed['/seo/generate'] = true; });
        await page.getByRole('button', { name: '검수 추천 생성', exact: true }).click();
        await page.waitForFunction(() => !!pending['/seo/generate']);
        await page.getByLabel('대표 키워드', { exact: true }).fill('새 키워드');
        await page.evaluate(() => { pending['/seo/generate']({ success: true, data: { generation_id: 'late', recommendation: { product_name: '늦은 응답', tags: [], page_title: '', meta_description: '' } } }); delete delayed['/seo/generate']; });
        assert.equal(await page.getByTestId('seo-review').count(), 0);

        // Both old company product lists and history must be discarded.
        await page.evaluate(() => { delayed['/seo/client/1/products'] = true; delayed['/seo/client/1/saved'] = true; });
        await page.getByLabel('업체 선택', { exact: true }).selectOption('2');
        await page.getByLabel('업체 선택', { exact: true }).selectOption('1');
        await page.waitForFunction(() => pending['/seo/client/1/products'] && pending['/seo/client/1/saved']);
        await page.getByLabel('업체 선택', { exact: true }).selectOption('2');
        await page.getByLabel('연결 상품').selectOption('p2');
        await page.evaluate(() => {
            pending['/seo/client/1/products']({ success: true, data: [{ product_key: 'wrong-company', product_name: '다른 업체 늦은 상품' }] });
            pending['/seo/client/1/saved']({ success: true, data: [{ id: 88, product_name: '다른 업체 늦은 이력' }] });
            delete delayed['/seo/client/1/products']; delete delayed['/seo/client/1/saved'];
        });
        assert.equal(await page.getByText('다른 업체 늦은 상품').count(), 0);
        assert.equal(await page.getByText('다른 업체 늦은 이력').count(), 0);
        await page.evaluate(() => { delayed['/seo/client/1/products'] = true; delayed['/seo/client/1/saved'] = true; delete pending['/seo/client/1/products']; delete pending['/seo/client/1/saved']; });
        await page.getByLabel('업체 선택', { exact: true }).selectOption('1');
        await page.waitForFunction(() => pending['/seo/client/1/products'] && pending['/seo/client/1/saved']);
        await page.evaluate(() => {
            pending['/seo/client/1/products']({ success: false, detail: '조회 실패' });
            pending['/seo/client/1/saved']({ success: false, detail: '조회 실패' });
        });
        await page.getByText(/연결 상품을 불러오지 못했습니다/).waitFor();
        assert.equal(await page.getByText('연결 상품이 없습니다. 아래 사실정보를 직접 입력할 수 있습니다.').count(), 0);
        await page.getByText(/저장 이력을 불러오지 못했습니다/).waitFor();

        await page.evaluate(() => { root.render(React.createElement(SeoRulesSection)); });
        await page.getByRole('button', { name: '개정 기준 활성화', exact: true }).waitFor();
        await page.evaluate(() => { window.confirm = () => false; });
        await page.getByRole('button', { name: '개정 기준 활성화', exact: true }).click();
        assert.equal(await page.evaluate(() => calls.filter(call => call.url === '/seo/rules/activate-recommended').length), 0, 'cancel must not activate');
        await page.getByLabel('사내 SEO 규칙', { exact: true }).fill('직접 작성한 기준');
        assert.equal(await page.getByRole('button', { name: '개정 기준 활성화', exact: true }).isDisabled(), true);
        await page.getByRole('button', { name: '저장', exact: true }).click();
        await page.getByText(/edited-v3/).waitFor();
        assert.equal(await page.getByLabel('사내 SEO 규칙', { exact: true }).inputValue(), '직접 작성한 기준');
        await page.evaluate(() => { window.confirm = () => true; delayed['/seo/rules/activate-recommended'] = true; });
        await page.getByRole('button', { name: '개정 기준 활성화', exact: true }).evaluate(button => { button.click(); button.click(); });
        await page.waitForFunction(() => !!pending['/seo/rules/activate-recommended']);
        assert.equal(await page.evaluate(() => calls.filter(call => call.url === '/seo/rules/activate-recommended').length), 1, 'activation mutex');
        await page.evaluate(() => pending['/seo/rules/activate-recommended']({ success: true, data: { rules_text: '개정 기준', version: 'rules-v2', recommended_rules_text: '개정 기준', recommended_version: 'rules-v2', is_recommended_active: true } }));
        await page.getByText('개정 기준 사용 · rules-v2', { exact: true }).waitFor();
        assert.equal(await page.getByLabel('사내 SEO 규칙', { exact: true }).inputValue(), '개정 기준');

        // Existing records without a review and every fact-edit invalidation stay supported.
        await page.evaluate(() => {
            delayed = {}; pending = {};
            saved.push({ id: 10, product_name: '옛 저장 상품', keyword: '옛 키워드', tags: ['옛태그'], review: null });
            root.render(React.createElement(SeoOptimizerPage, { currentUser: { role: 'superadmin' } }));
        });
        await page.getByLabel('업체 선택', { exact: true }).selectOption('1');
        await page.getByText('옛 저장 상품', { exact: true }).waitFor();
        await page.getByText(/이전 형식 기록 · 검수 상태 미확인/).waitFor();
        await page.getByLabel('연결 상품').selectOption('p1');
        await page.getByText('상품 사실·현재값 확인 및 보완', { exact: true }).click();
        for (const label of ['상품 URL', '브랜드', '카테고리', '확인된 특징·속성', '현재 상품명', '현재 판매자 태그', '현재 페이지 타이틀', '현재 메타 디스크립션']) {
            await page.getByRole('button', { name: '검수 추천 생성', exact: true }).click();
            await page.getByTestId('seo-review').waitFor();
            await page.getByLabel(label, { exact: true }).fill(label === '상품 URL' ? 'https://example.invalid/changed' : '수정 사실');
            assert.equal(await page.getByTestId('seo-review').count(), 0, label + ' invalidates previous review');
        }
        await page.getByRole('button', { name: '검수 추천 생성', exact: true }).click();
        await page.getByTestId('seo-review').waitFor();
        await page.getByText('다른 상품명 후보', { exact: true }).click();
        await page.getByRole('button', { name: '이 상품명 선택', exact: true }).click();
        assert.equal(await page.getByLabel('상품명 수정값', { exact: true }).inputValue(), '다른 추천 상품');
        await page.getByLabel('연결 상품').selectOption('');
        assert.equal(await page.getByTestId('seo-review').count(), 0, 'product change invalidates');

        // A successful save arriving after a company switch cannot mark the new company approved.
        await page.getByLabel('연결 상품').selectOption('p1');
        await page.getByRole('button', { name: '검수 추천 생성', exact: true }).click();
        await page.getByTestId('seo-review').waitFor();
        await page.getByRole('checkbox').check();
        await page.evaluate(() => { delayed['/seo/save-to-client'] = true; });
        await page.getByRole('button', { name: '승인본 저장', exact: true }).click();
        await page.waitForFunction(() => !!pending['/seo/save-to-client']);
        await page.getByLabel('업체 선택', { exact: true }).selectOption('2');
        await page.evaluate(() => pending['/seo/save-to-client']({ success: true, data: { id: 20 } }));
        assert.equal(await page.getByRole('button', { name: '승인본 저장됨', exact: true }).count(), 0);
        assert.equal(await page.getByTestId('seo-review').count(), 0);
        const callCount = await page.evaluate(() => calls.length);
        await page.evaluate(() => root.render(React.createElement(SeoOptimizerPage, { currentUser: { role: 'viewer' } })));
        await page.getByRole('alert').filter({ hasText: '관리팀·최고관리자 전용' }).waitFor();
        assert.equal(await page.evaluate(() => calls.length), callCount, 'viewer guard has no API calls');
        assert.equal(await page.getByLabel('업체 선택').count(), 0);

        // Company-free general recommendations and errors do not become approved records.
        await page.evaluate(() => { root.unmount(); root = ReactDOM.createRoot(document.getElementById('root')); delayed = {}; pending = {}; mountOptimizer(); });
        await page.getByLabel('대표 키워드', { exact: true }).fill('일반 키워드');
        await page.getByRole('button', { name: '검수 추천 생성', exact: true }).click();
        await page.getByTestId('seo-review').waitFor();
        assert.equal(await page.getByRole('button', { name: '승인본 저장', exact: true }).isDisabled(), true);
        await page.getByLabel('대표 키워드', { exact: true }).fill('실패 확인 키워드');
        await page.evaluate(() => { delayed['/seo/generate'] = true; });
        await page.getByRole('button', { name: '검수 추천 생성', exact: true }).click();
        await page.waitForFunction(() => !!pending['/seo/generate']);
        await page.evaluate(() => { pending['/seo/generate']({ success: false, detail: '한도 확인이 필요합니다. 안전 오류 코드: quota_exceeded' }); delete pending['/seo/generate']; });
        await page.getByRole('alert').filter({ hasText: 'quota_exceeded' }).waitFor();
        assert.equal(await page.getByTestId('seo-review').count(), 0);
        await page.getByRole('button', { name: '검수 추천 생성', exact: true }).click();
        await page.waitForFunction(() => !!pending['/seo/generate']);
        await page.evaluate(() => pending['/seo/generate']({ success: true, data: { product_names: ['잘못된 옛 형식'] } }));
        await page.getByRole('alert').filter({ hasText: '생성 응답에 검수용 네 항목이 없습니다' }).waitFor();
        assert.equal(await page.getByTestId('seo-review').count(), 0);
        const unexpected = await page.evaluate(() => calls.filter(call => !['/cd/registered-clients', '/seo/rules', '/seo/generate', '/seo/save-to-client', '/seo/rules/activate-recommended'].includes(call.url) && !/^\/seo\/client\/\d+\/(saved|products)$/.test(call.url)));
        assert.deepEqual(unexpected, [], 'only approved internal endpoints are called');
        assert.equal(externalRequests, 0);
        assert.deepEqual(errors, []);
        assert.equal(await page.evaluate(() => React.version), reactVersion);
        console.log('PASS: offline SEO review flow (React ' + reactVersion + '; production 18.2.0), external requests = 0');
    } finally {
        await browser.close();
    }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
