#!/usr/bin/env node
/*
 * 프론트 번들 빌드 — 브라우저 인-Babel 제거용
 *
 * index.html의 <script src="js/..."> 로드 순서를 그대로 읽어, 각 파일을
 * Babel(preset-react)로 변환(= 브라우저가 하던 것과 동일)한 뒤 한 파일로 연결한다.
 * 출력: dist/app.<contenthash>.js  (해시 파일명 → 캐시 깨짐 자동 해결)
 *
 * ⚠️ 컴포넌트(.jsx)를 수정하면 이 스크립트를 다시 실행해 번들을 갱신해야 한다:
 *      node frontend/build.js
 *    (CI 자동화는 후속 작업)
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// babel 위치: 로컬 node_modules → /tmp/node_modules 순으로 탐색
function reqBabel(name) {
  for (const base of [path.join(__dirname, '..', 'node_modules'), '/tmp/node_modules']) {
    try { return require(path.join(base, name)); } catch (e) {}
  }
  throw new Error('babel 모듈을 찾을 수 없습니다: ' + name);
}
const babel = reqBabel('@babel/core');
const presetReact = reqBabel('@babel/preset-react');

const FRONTEND = __dirname;

// 로드 순서는 build.manifest.json에서 읽는다 (index.html은 번들만 로드하므로 더 이상 목록을 갖지 않음)
const manifestPath = path.join(FRONTEND, 'build.manifest.json');
const files = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
if (!Array.isArray(files) || files.length === 0) { console.error('build.manifest.json이 비어있음'); process.exit(1); }

// "use strict"를 넣지 않는다 — 현재 앱은 비엄격 스크립트로 동작하므로 동일하게 유지
let out = '';
for (const rel of files) {
  const full = path.join(FRONTEND, rel);
  const code = fs.readFileSync(full, 'utf8');
  const res = babel.transformSync(code, {
    presets: [presetReact],
    filename: rel,
    compact: false,
    babelrc: false,
    configFile: false,
  });
  // 파일 경계에 ';\n' 안전 구분자 — 연결 시 ASI 문제 방지
  out += '\n;/* ===== ' + rel + ' ===== */\n' + res.code + '\n';
}

const hash = crypto.createHash('sha256').update(out).digest('hex').slice(0, 12);
const distDir = path.join(FRONTEND, 'dist');
fs.mkdirSync(distDir, { recursive: true });

// 이전 번들 정리(해시 다른 것 제거)
for (const f of fs.readdirSync(distDir)) {
  if (/^app\.[0-9a-f]+\.js$/.test(f)) fs.unlinkSync(path.join(distDir, f));
}
const bundleName = `app.${hash}.js`;
fs.writeFileSync(path.join(distDir, bundleName), out);
// 빌드 메타(해시) 기록 — index 갱신 스크립트가 참조
fs.writeFileSync(path.join(distDir, 'bundle.json'), JSON.stringify({ bundle: bundleName, files: files.length }, null, 2));
console.log(`✅ 빌드 완료: dist/${bundleName}  (${(out.length / 1024).toFixed(0)}KB, ${files.length}개 파일)`);

// index.html / index.bundle.html의 번들 참조를 새 해시로 자동 갱신 (해시 갱신 누락 방지)
for (const htmlFile of ['index.html', 'index.bundle.html']) {
  const p = path.join(FRONTEND, htmlFile);
  if (!fs.existsSync(p)) continue;
  const h = fs.readFileSync(p, 'utf8');
  const replaced = h.replace(/dist\/app\.[0-9a-f]+\.js/g, 'dist/' + bundleName);
  if (replaced !== h) { fs.writeFileSync(p, replaced); console.log(`  ↳ ${htmlFile} 번들 참조 갱신`); }
}
