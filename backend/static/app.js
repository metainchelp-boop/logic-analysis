// ===== 메타 광고주 통합 대시보드 — Sprint 1 프론트 (가벼운 화면) =====
const API = "/api";
let TOKEN = localStorage.getItem("token") || "";
let ME = JSON.parse(localStorage.getItem("me") || "null");

const CHANNELS = [
  { key: "naver_commerce", name: "네이버 커머스(스토어)", color: "#03c75a", tcolor: "#fff", abbr: "N",
    hint: "판매자센터 › 커머스 API센터 발급 → 매출·주문 자동",
    fields: [{ k: "app_id", label: "애플리케이션 ID" }, { k: "app_secret", label: "시크릿", pw: true }] },
  { key: "naver_searchad", name: "네이버 검색광고", color: "#1ec800", tcolor: "#fff", abbr: "광",
    hint: "검색광고 › 도구 › API 사용 관리 → ROAS·키워드 자동",
    fields: [{ k: "customer_id", label: "Customer ID" }, { k: "api_license", label: "API 라이선스" }, { k: "secret_key", label: "비밀키", pw: true }] },
  { key: "kakao", name: "카카오모먼트", color: "#fee500", tcolor: "#3c1e1e", abbr: "K",
    hint: "카카오비즈니스 › 모먼트 › API",
    fields: [{ k: "account_id", label: "광고계정 ID" }, { k: "rest_key", label: "REST API 키", pw: true }] },
  { key: "youtube", name: "유튜브", color: "#ff0000", tcolor: "#fff", abbr: "▶",
    hint: "영상 URL만 입력(여러 개는 쉼표). API키는 회사 공용",
    fields: [{ k: "video_url", label: "영상 URL" }] },
  { key: "meta_chehum", name: "메타체험단", color: "#6c5ce7", tcolor: "#fff", abbr: "체",
    hint: "메타체험단에 등록된 광고주 ID와 매칭",
    fields: [{ k: "advertiser_id", label: "체험단 광고주 ID" }] },
  { key: "daangn", name: "당근(엑셀 업로드)", color: "#ff6f0f", tcolor: "#fff", abbr: "당",
    hint: "당근은 API가 없어 엑셀 업로드 방식 (다음 스프린트)",
    fields: [] },
];

const $ = (s, el = document) => el.querySelector(s);
const app = () => document.getElementById("app");
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(TOKEN ? { Authorization: "Bearer " + TOKEN } : {}), ...(opts.headers || {}) },
  });
  if (res.status === 401) { logout(); throw new Error("로그인이 필요합니다"); }
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "오류가 발생했습니다"); }
  return res.status === 204 ? null : res.json();
}

function toast(msg) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 1800);
}

// ===== 로그인 =====
function renderLogin() {
  app().innerHTML = `
    <div class="login-wrap"><div class="login-box">
      <div class="brand"><div class="logo">메타<span>아이앤씨</span></div><div class="tag">광고주 통합 대시보드 · 마케터 전용</div></div>
      <div class="card">
        <h1>로그인</h1><div class="desc">전산 계정으로 들어오세요.</div>
        <div class="fg"><label>이메일</label><input id="email" value="kim@metainc.co.kr"></div>
        <div class="fg"><label>비밀번호</label><input id="pw" type="password" value="kim1234"></div>
        <button class="btn-primary" id="loginBtn">로그인</button>
        <div class="err" id="loginErr"></div>
        <div class="demo-accounts">🔑 데모 계정 (클릭 시 자동 입력):<br>
          <b>담당자</b> <code data-e="kim@metainc.co.kr" data-p="kim1234">kim@metainc.co.kr</code> ·
          <b>팀장</b> <code data-e="lead@metainc.co.kr" data-p="lead1234">lead</code> ·
          <b>대표</b> <code data-e="admin@metainc.co.kr" data-p="admin1234">admin</code></div>
      </div>
    </div></div>`;
  $("#loginBtn").onclick = doLogin;
  $("#pw").onkeydown = (e) => { if (e.key === "Enter") doLogin(); };
  document.querySelectorAll(".demo-accounts code").forEach((c) => c.onclick = () => { $("#email").value = c.dataset.e; $("#pw").value = c.dataset.p; });
}

async function doLogin() {
  $("#loginErr").textContent = "";
  try {
    const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ email: $("#email").value.trim(), password: $("#pw").value }) });
    TOKEN = data.access_token; ME = data.user;
    localStorage.setItem("token", TOKEN); localStorage.setItem("me", JSON.stringify(ME));
    renderHome();
  } catch (e) { $("#loginErr").textContent = e.message; }
}

function logout() {
  TOKEN = ""; ME = null; localStorage.removeItem("token"); localStorage.removeItem("me");
  renderLogin();
}

// ===== 공통 셸 =====
function shell(active, inner) {
  const roleKr = { staff: "담당자", lead: "팀장", admin: "대표" }[ME.role] || ME.role;
  return `<div class="shell">
    <aside class="nav">
      <div class="logo">메타<span>아이앤씨</span> 전산</div>
      <div class="group">광고주 대시보드</div>
      <a class="${active === "home" ? "active" : ""}" id="navHome">➕ 광고주 등록·관리</a>
      <a>📊 통합 대시보드 <span style="color:var(--muted);font-size:11px">(다음)</span></a>
      <a>📄 AI 리포트 <span style="color:var(--muted);font-size:11px">(다음)</span></a>
      <div style="flex:1"></div>
      <div class="me"><div class="n">${esc(ME.name)}</div><div class="r">${roleKr} · ${esc(ME.email)}</div></div>
      <a id="navLogout">↩︎ 로그아웃</a>
    </aside>
    <main class="main">${inner}</main>
  </div>`;
}
function bindShell() { const h = $("#navHome"); if (h) h.onclick = renderHome; $("#navLogout").onclick = logout; }

// ===== 홈: 광고주 목록 =====
async function renderHome() {
  app().innerHTML = shell("home", `<div class="page-head"><div><h1>광고주 관리</h1><div class="sub">담당 광고주를 등록하고 채널 API를 연결합니다.</div></div><button class="btn blue" id="newBtn">+ 신규 광고주 등록</button></div><div id="list">불러오는 중…</div>`);
  bindShell();
  $("#newBtn").onclick = () => renderForm(null);
  try {
    const clients = await api("/clients");
    if (!clients.length) { $("#list").innerHTML = `<div class="empty">아직 등록된 광고주가 없어요.<br>우측 상단 <b>+ 신규 광고주 등록</b>으로 시작하세요.</div>`; return; }
    $("#list").innerHTML = `<div class="grid">${clients.map(cardHtml).join("")}</div>`;
    clients.forEach((c) => { $("#card-" + c.id).onclick = () => renderForm(c.id); });
  } catch (e) { $("#list").innerHTML = `<div class="empty" style="color:var(--red)">${esc(e.message)}</div>`; }
}

function cardHtml(c) {
  const chips = CHANNELS.map((ch) => {
    const on = c.channels.find((x) => x.channel === ch.key && x.status === "connected");
    return `<span style="width:22px;height:22px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:900;background:${on ? ch.color : "#e8ebf1"};color:${on ? ch.tcolor : "#aab1bd"}">${ch.abbr}</span>`;
  }).join(" ");
  return `<div class="acard" id="card-${c.id}">
    <div class="top"><div class="av">${esc(c.name[0] || "?")}</div><div><div class="nm">${esc(c.name)}</div><div class="cat">${esc(c.category || "-")}</div></div>
      <span class="st ${c.status}">${{ active: "진행중", paused: "일시정지", ended: "종료" }[c.status] || c.status}</span></div>
    <div style="display:flex;gap:5px;margin-bottom:10px">${chips}</div>
    <div class="meta"><span>담당 <b>${esc(c.owner_name || "-")}</b></span><span>연동 <b>${c.connected_count}/6</b></span></div>
  </div>`;
}

// ===== 등록/편집 폼 =====
async function renderForm(id) {
  let c = { name: "", category: "", status: "active", contact: "", contract_start: "", memo: "", channels: [] };
  if (id) { try { c = await api("/clients/" + id); } catch (e) { toast(e.message); return; } }
  const chMap = {}; (c.channels || []).forEach((x) => (chMap[x.channel] = x));

  const channelsHtml = CHANNELS.map((ch) => {
    const ex = chMap[ch.key];
    const conn = ex && ex.status === "connected";
    const fields = ch.fields.map((f) => {
      const masked = ex && ex.fields_masked ? ex.fields_masked[f.k] : "";
      return `<div class="fg"><label>${f.label}</label><input data-ch="${ch.key}" data-k="${f.k}" type="${f.pw ? "password" : "text"}" placeholder="${masked ? esc(masked) + " (비우면 기존 유지)" : ""}"></div>`;
    }).join("");
    return `<div class="channel">
      <div class="chan-head"><div class="logo" style="background:${ch.color};color:${ch.tcolor}">${ch.abbr}</div><div class="name">${ch.name}</div>
        <span class="status ${conn ? "connected" : "disconnected"}">${conn ? "연결됨" : "미연결"}</span></div>
      ${fields || `<div class="fg hint">${ch.hint}</div>`}
      ${fields ? `<div class="fg hint">${ch.hint}</div>` : ""}
    </div>`;
  }).join("");

  app().innerHTML = shell("home", `
    <div class="page-head"><div><h1>${id ? "광고주 편집" : "신규 광고주 등록"}</h1><div class="sub">기본 정보 + 채널 API를 입력하면 저장됩니다.</div></div>
      <button class="btn ghost" id="backBtn">← 목록</button></div>
    <fieldset><legend>① 기본 정보</legend>
      <div class="two"><div class="fg"><label>광고주명 / 브랜드 *</label><input id="f-name" value="${esc(c.name)}"></div>
        <div class="fg"><label>업종 / 카테고리</label><input id="f-category" value="${esc(c.category || "")}"></div></div>
      <div class="two"><div class="fg"><label>계약 상태</label><select id="f-status">
        <option value="active" ${c.status === "active" ? "selected" : ""}>진행중</option>
        <option value="paused" ${c.status === "paused" ? "selected" : ""}>일시정지</option>
        <option value="ended" ${c.status === "ended" ? "selected" : ""}>종료</option></select></div>
        <div class="fg"><label>계약 시작일</label><input id="f-contract" type="date" value="${esc(c.contract_start || "")}"></div></div>
      <div class="two"><div class="fg"><label>담당자 연락처</label><input id="f-contact" value="${esc(c.contact || "")}"></div>
        <div class="fg"><label>메모</label><input id="f-memo" value="${esc(c.memo || "")}"></div></div>
    </fieldset>
    <fieldset><legend>② 채널 연동 <span style="font-size:11px;color:var(--sub);font-weight:500">(키는 암호화 저장됩니다)</span></legend>${channelsHtml}</fieldset>
    <div class="save-bar">
      ${id ? `<button class="btn danger" id="delBtn">삭제</button>` : ""}
      <button class="btn ghost" id="cancelBtn">취소</button>
      <button class="btn green" id="saveBtn">💾 저장</button>
    </div>`);
  bindShell();
  $("#backBtn").onclick = renderHome; $("#cancelBtn").onclick = renderHome;
  if (id) $("#delBtn").onclick = () => delClient(id);
  $("#saveBtn").onclick = () => saveClient(id);
}

function collectChannels() {
  return CHANNELS.map((ch) => {
    const fields = {};
    ch.fields.forEach((f) => {
      const el = document.querySelector(`input[data-ch="${ch.key}"][data-k="${f.k}"]`);
      if (el && el.value.trim()) fields[f.k] = el.value.trim();
    });
    return { channel: ch.key, mode: ch.key === "naver_searchad" ? "delegated" : (ch.key === "daangn" ? "upload" : "direct"), fields };
  });
}

async function saveClient(id) {
  const name = $("#f-name").value.trim();
  if (!name) { toast("광고주명을 입력하세요"); return; }
  const payload = {
    name, category: $("#f-category").value.trim(), status: $("#f-status").value,
    contact: $("#f-contact").value.trim(), contract_start: $("#f-contract").value,
    memo: $("#f-memo").value.trim(), channels: collectChannels(),
  };
  try {
    await api(id ? "/clients/" + id : "/clients", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
    toast(id ? "저장되었습니다" : "등록되었습니다");
    renderHome();
  } catch (e) { toast(e.message); }
}

async function delClient(id) {
  if (!confirm("이 광고주를 삭제할까요? 되돌릴 수 없습니다.")) return;
  try { await api("/clients/" + id, { method: "DELETE" }); toast("삭제되었습니다"); renderHome(); }
  catch (e) { toast(e.message); }
}

// ===== 시작 =====
if (TOKEN && ME) renderHome(); else renderLogin();
