/* Luxe Laminate Management System - browser app (no build step needed) */
"use strict";

const S = { token: localStorage.getItem("luxe_token"), user: null, business: "Luxe Laminate", allPerms: {}, timers: [], gstRound: true };
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v) => Number(v || 0);
const rs = (v) => "₹ " + num(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const rs0 = (v) => "₹ " + Math.round(num(v)).toLocaleString("en-IN");
const q3 = (v) => { const n = num(v); return Number.isInteger(n) ? String(n) : n.toFixed(3).replace(/0+$/, ""); };
const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => today().slice(0, 8) + "01";
const fdate = (iso) => iso ? new Date(iso.length === 10 ? iso + "T00:00:00" : iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "";
const fdt = (iso) => iso ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
const can = (p) => S.user && (S.user.role === "owner" || (S.user.permissions || []).includes(p));
const canAny = (...p) => p.some(can);
const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const statusWords = (s) => String(s || "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

function tag(cat, fac, opts = {}) {
  return `<span class="tag ${opts.lg ? "lg" : ""}" title="Customer catalogue number and factory order number">
    <span class="cat"><small>Catalogue</small>${esc(cat)}</span>${fac !== undefined && fac !== null ? `<span class="fac"><small>Factory</small>${esc(fac)}</span>` : ""}</span>`;
}
const SOURCE_LABEL = { MANUAL: "Shop", ONLINE: "Online", DELIVERY: "Delivery", BULK: "Bulk" };
const METHOD_LABEL = { CASH: "Cash (offline)", CHEQUE: "Cheque (offline)", UPI: "UPI (online)", BANK: "Bank transfer / NEFT (online)", CARD: "Card (online)", ONLINE: "Other online" };
const isOffline = (m) => m === "CASH" || m === "CHEQUE";
function methodChip(m) { return `${esc(m)} <span class="chip ${isOffline(m) ? "" : "ok"}">${isOffline(m) ? "Offline" : "Online"}</span>`; }
const methodOptions = () => Object.entries(METHOD_LABEL).map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
function taxChip(m) { return m === "CASH" ? `<span class="chip warn">Cash</span>` : `<span class="chip ok">Bill</span>`; }
function srcChip(s) { return `<span class="chip src">${esc(SOURCE_LABEL[s] || s)}</span>`; }
function chip(text, kind = "") { return `<span class="chip ${kind}">${esc(text)}</span>`; }
function payChip(s) { return chip(statusWords(s), { PAID: "ok", PARTIAL: "warn", UNPAID: "bad", CANCELLED: "" }[s] || ""); }
function foChip(s) { return chip(statusWords(s), { DELIVERED: "ok", CANCELLED: "", READY: "ok", DISPATCHED: "ok", PENDING: "warn" }[s] || ""); }

/* ------------------------------------------------------------------ API */
async function api(path, { method = "GET", body, form, params, raw } = {}) {
  let url = path;
  if (params) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") qs.set(k, v); });
    if ([...qs].length) url += (url.includes("?") ? "&" : "?") + qs;
  }
  const headers = {};
  if (S.token) headers.Authorization = "Bearer " + S.token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(url, { method, headers, body: form || (body !== undefined ? JSON.stringify(body) : undefined) });
  } catch (e) {
    throw Object.assign(new Error("Cannot reach the server. Check that it is running and the network is connected."), { status: 0 });
  }
  if (res.status === 401 && S.token) { logout("Your session ended. Please log in again."); throw new Error("Session ended."); }
  if (raw && res.ok) return res;
  let data = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("json")) data = await res.json();
  if (!res.ok) throw Object.assign(new Error((data && data.detail) || `Request failed (${res.status})`), { status: res.status, data });
  return data;
}
async function openPdf(path, params) {
  const w = window.open("", "_blank");
  try {
    const res = await api(path, { params, raw: true });
    const url = URL.createObjectURL(await res.blob());
    if (w) w.location = url; else location.href = url;
  } catch (e) { if (w) w.close(); toast(e.message, "err"); }
}
async function download(path, params, fallbackName) {
  try {
    const res = await api(path, { params, raw: true });
    const cd = res.headers.get("content-disposition") || "";
    const name = (cd.match(/filename="?([^"]+)"?/) || [])[1] || fallbackName;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = name;
    a.click();
    toast("Downloaded " + name);
  } catch (e) { toast(e.message, "err"); }
}

/* ------------------------------------------------------------------ UI helpers */
function toast(msg, kind = "ok") {
  const el = document.createElement("div");
  el.className = "toast " + (kind === "ok" ? "" : kind);
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 7000 : 3500);
}
function modal(html, { wide = false, onMount } = {}) {
  const root = $("#modal-root");
  const wrap = document.createElement("div");
  wrap.className = "backdrop";
  wrap.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">${html}</div>`;
  root.appendChild(wrap);
  const close = () => { wrap.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) close(); });
  $$("[data-close]", wrap).forEach((b) => b.addEventListener("click", close));
  const box = $(".modal", wrap);
  if (onMount) onMount(box, close);
  const first = $("input:not([type=hidden]), select, textarea", box);
  if (first) first.focus();
  return { box, close };
}
function confirmBox(title, text, okLabel = "Confirm", danger = false) {
  return new Promise((resolve) => {
    const { box, close } = modal(`<h2>${esc(title)}</h2><p>${text}</p>
      <div class="modal-actions"><button class="btn" data-no>Go back</button>
      <button class="btn ${danger ? "danger" : "primary"}" data-yes>${esc(okLabel)}</button></div>`);
    $("[data-no]", box).onclick = () => { close(); resolve(false); };
    $("[data-yes]", box).onclick = () => { close(); resolve(true); };
    $("[data-yes]", box).focus();
  });
}
function promptBox(title, label, okLabel = "Save", { min = 3, value = "" } = {}) {
  return new Promise((resolve) => {
    const { box, close } = modal(`<h2>${esc(title)}</h2><label class="f">${esc(label)}<input data-v value="${esc(value)}"></label>
      <div class="modal-actions"><button class="btn" data-no>Go back</button><button class="btn primary" data-yes>${esc(okLabel)}</button></div>`);
    const go = () => { const v = $("[data-v]", box).value.trim(); if (v.length < min) { toast(`Write at least ${min} characters.`, "warn"); return; } close(); resolve(v); };
    $("[data-no]", box).onclick = () => { close(); resolve(null); };
    $("[data-yes]", box).onclick = go;
    $("[data-v]", box).onkeydown = (e) => { if (e.key === "Enter") go(); };
  });
}
function formData(el) {
  const out = {};
  $$("[name]", el).forEach((i) => { out[i.name] = i.type === "checkbox" ? i.checked : i.value.trim(); });
  return out;
}
function busy(btn, on, label) {
  if (!btn) return;
  if (on) { btn.dataset.label = btn.textContent; btn.textContent = label || "Saving…"; btn.disabled = true; }
  else { btn.textContent = btn.dataset.label || btn.textContent; btn.disabled = false; }
}
function pager(data, onGo) {
  if (!data || data.pages <= 1) return `<div class="pager"><span class="muted small">${data ? data.total : 0} records</span></div>`;
  const id = "pg" + Math.random().toString(36).slice(2, 7);
  setTimeout(() => {
    const el = document.getElementById(id); if (!el) return;
    $("[data-prev]", el).onclick = () => onGo(data.page - 1);
    $("[data-next]", el).onclick = () => onGo(data.page + 1);
  });
  return `<div class="pager" id="${id}"><span class="muted small">${data.total.toLocaleString("en-IN")} records · page ${data.page} of ${data.pages}</span>
    <span class="row"><button class="btn sm" data-prev ${data.page <= 1 ? "disabled" : ""}>Previous</button>
    <button class="btn sm" data-next ${data.page >= data.pages ? "disabled" : ""}>Next</button></span></div>`;
}
function table(cols, rows, { empty = "Nothing here yet.", click, foot } = {}) {
  if (!rows.length) return `<div class="empty">${empty}</div>`;
  const id = "t" + Math.random().toString(36).slice(2, 7);
  if (click) setTimeout(() => { const t = document.getElementById(id); if (t) $$("tr[data-i]", t).forEach((tr) => tr.onclick = (e) => { if (!e.target.closest("button,a,input,select")) click(rows[+tr.dataset.i]); }); });
  return `<div class="table-wrap"><table id="${id}"><thead><tr>${cols.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r, i) => `<tr data-i="${i}" class="${click ? "click" : ""}">${cols.map((c) => `<td class="${c.num ? "num" : ""}">${c.html ? c.html(r) : esc(r[c.key])}</td>`).join("")}</tr>`).join("")}</tbody>
    ${foot ? `<tfoot>${foot}</tfoot>` : ""}</table></div>`;
}

/* ------------------------------------------------------------------ customer & product pickers */
function customerPicker(container, onPick, { allowCreate = true } = {}) {
  container.innerHTML = `<label class="f">Customer name <span class="hint">or phone / area</span>
      <input data-cq placeholder="Type at least 2 letters" autocomplete="off"></label>
    <div class="list-pick" data-cres></div>
    ${allowCreate && canAny("customers.edit", "billing.create") ? `<button class="btn ghost" data-cnew style="margin-top:8px">+ Add a new customer</button>` : ""}`;
  const input = $("[data-cq]", container), res = $("[data-cres]", container);
  const run = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) { res.innerHTML = ""; return; }
    try {
      const data = await api("/api/customers", { params: { q, size: 15 } });
      res.innerHTML = data.items.length ? data.items.map((c, i) => `<button data-i="${i}"><span><b>${esc(c.name)}</b><br><span class="small muted">${esc(c.code)} · ${esc(c.phone || "no phone")}${c.area ? " · " + esc(c.area) : ""}</span></span>
        <span class="small ${num(c.outstanding) > 0 ? "" : "muted"}">${num(c.outstanding) > 0 ? "Owes " + rs(c.outstanding) : "No dues"}</span></button>`).join("")
        : `<div class="muted small" style="padding:8px">No customer with this name yet.</div>${canAny("customers.edit", "billing.create") ? `<button class="btn primary" data-quick style="margin-top:6px">+ Add "${esc(q)}" as new customer</button>` : ""}`;
      const qb = $("[data-quick]", res); if (qb) qb.onclick = () => customerForm(null, onPick, q);
      $$("button[data-i]", res).forEach((b) => b.onclick = () => onPick(data.items[+b.dataset.i]));
    } catch (e) { toast(e.message, "err"); }
  });
  input.addEventListener("input", run);
  const nb = $("[data-cnew]", container);
  if (nb) nb.onclick = () => customerForm(null, onPick, input.value.trim());
  input.focus();
}
function customerForm(c, onSaved, prefill = "") {
  const isPhone = /^\d{5,}$/.test(prefill);
  const { box, close } = modal(`<h2>${c ? "Edit customer" : "New customer"}</h2><form class="stack">
    <div class="grid2"><label class="f">Name<input name="name" required value="${esc(c ? c.name : isPhone ? "" : prefill)}"></label>
    <label class="f">Phone<input name="phone" inputmode="tel" value="${esc(c ? c.phone : isPhone ? prefill : "")}"></label></div>
    <label class="f">Area <span class="hint">e.g. Shela, Tragad, Ghatlodiya, Gota</span><input name="area" list="areaList" value="${esc(c?.area)}"></label><datalist id="areaList"></datalist>
    <div class="grid2"><label class="f">Email<input name="email" type="email" value="${esc(c?.email)}"></label>
    <label class="f">GSTIN <span class="hint">optional</span><input name="gstin" value="${esc(c?.gstin)}"></label></div>
    <label class="f">Address<textarea name="address">${esc(c?.address)}</textarea></label>
    <label class="f">Notes<textarea name="notes">${esc(c?.notes)}</textarea></label>
    ${c ? `<label class="check"><input type="checkbox" name="is_active" ${c.is_active ? "checked" : ""}> Active customer</label>` : ""}
    <div class="modal-actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">${c ? "Save changes" : "Add customer"}</button></div></form>`);
  api("/api/customers", { params: { size: 500, with_balance: false } }).then((d) => { const dl = $("#areaList", box); if (dl) dl.innerHTML = [...new Set(d.items.map((x) => x.area).filter(Boolean))].sort().map((a) => `<option>${esc(a)}</option>`).join(""); }).catch(() => {});
  $("form", box).onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("button.primary", box); busy(btn, true);
    const body = formData(box); if (!c) body.is_active = true;
    try {
      const saved = await api(c ? `/api/customers/${c.id}` : "/api/customers", { method: c ? "PUT" : "POST", body });
      toast(c ? "Customer saved." : `Customer ${saved.code} added.`); close(); onSaved(saved);
    } catch (err) { toast(err.message, "err"); busy(btn, false); }
  };
}
/* Catalogue-number lookup widget: the heart of the system */
function productFinder(container, onFound, { label = "Customer catalogue number", showFactory = true, exactBox = true } = {}) {
  container.innerHTML = `<label class="f">Select product from inventory <span class="hint">click to see the list, or type name, design no. or brand</span>
      <div class="combo"><input data-pq placeholder="Click here to choose a product" autocomplete="off"><div class="combo-list" data-pl hidden></div></div></label>
    <div style="${exactBox ? "" : "display:none"}"><div class="small muted" style="margin:12px 0 2px">or type the exact design / catalogue number</div>
    <div class="row">
      <label class="f" style="flex:0 1 170px">Catalogue book<select data-cat><option value="">Any book</option></select></label>
      <label class="f" style="flex:1 1 220px">${esc(label)}<input class="big" data-no placeholder="e.g. 123" autocomplete="off" inputmode="text"></label>
      <button class="btn primary xl" data-find>Find</button></div></div>
    <div data-res></div>`;
  const sel = $("[data-cat]", container), inp = $("[data-no]", container), res = $("[data-res]", container);
  const pq = $("[data-pq]", container), pl = $("[data-pl]", container);
  let opts = [], hi = -1, total = 0;
  const drawOpts = () => {
    pl.innerHTML = opts.length ? opts.map((p, i) => `<button type="button" data-i="${i}" class="${i === hi ? "hi" : ""}"><span><b>${esc(p.name)}</b><br><span class="small muted">${esc([p.brand, "Design " + p.catalogue_no, p.size, p.finish].filter(Boolean).join(" · "))}</span></span>
      <span class="right nowrap"><b>${rs(p.sale_price)}</b><br><span class="small ${num(p.available_qty) > 0 ? "muted" : ""}">${num(p.available_qty) > 0 ? "Stock " + q3(p.available_qty) + " " + esc(p.unit) : "No stock"}</span></span></button>`).join("")
      + (total > opts.length ? `<div class="small muted" style="padding:8px 12px">Showing ${opts.length} of ${total.toLocaleString("en-IN")}. Type to narrow down.</div>` : "")
      : `<div class="small muted" style="padding:12px">No product found. Check the spelling, or add it in Products & numbers.</div>`;
    pl.hidden = false;
    $$("button[data-i]", pl).forEach((b) => b.onmousedown = (e) => { e.preventDefault(); pick(+b.dataset.i); });
  };
  const loadOpts = debounce(async () => {
    try { const d = await api("/api/products", { params: { q: pq.value.trim(), active: true, size: 40 } }); opts = d.items; total = d.total; hi = opts.length ? 0 : -1; drawOpts(); } catch (e) { toast(e.message, "err"); }
  }, 200);
  const pick = async (i) => {
    const p = opts[i]; if (!p) return;
    pl.hidden = true; pq.value = ""; res.innerHTML = "";
    try { onFound(await api(`/api/products/${p.id}`), res); } catch (e) { toast(e.message, "err"); }
  };
  pq.addEventListener("mousedown", () => { if (pl.hidden) loadOpts(); });
  pq.addEventListener("input", loadOpts);
  pq.addEventListener("blur", () => setTimeout(() => { pl.hidden = true; }, 150));
  pq.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); if (!opts.length) return; hi = (hi + (e.key === "ArrowDown" ? 1 : -1) + opts.length) % opts.length; drawOpts(); const el = $(`button[data-i="${hi}"]`, pl); if (el) el.scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter") { e.preventDefault(); if (!pl.hidden && hi >= 0) pick(hi); }
    else if (e.key === "Escape") pl.hidden = true;
  });
  api("/api/products/catalogues").then((cats) => { sel.innerHTML = `<option value="">Any book</option>` + cats.map((c) => `<option>${esc(c)}</option>`).join(""); if (cats.length <= 1) sel.closest("label").style.display = "none"; }).catch(() => {});
  const show = (p) => onFound(p, res);
  const find = async () => {
    const n = inp.value.trim();
    if (!n) { inp.focus(); return; }
    res.innerHTML = `<p class="muted" style="margin-top:12px">Looking up ${esc(n)}…</p>`;
    try {
      const r = await api("/api/products/lookup", { params: { catalogue_no: n, catalogue: sel.value } });
      if (r.status === "ok") return show(r.product);
      const kind = r.status === "ambiguous" ? "warn" : "bad";
      res.innerHTML = `<div class="result-card ${kind}"><b>${esc(r.message)}</b>
        ${r.matches && r.status === "ambiguous" ? `<div class="list-pick">${r.matches.map((m, i) => `<button data-i="${i}"><span>${tag(m.catalogue_no, showFactory ? m.factory_order_no : null)} &nbsp;<b>${esc(m.name)}</b></span><span class="chip">${esc(m.catalogue)}</span></button>`).join("")}</div>` : ""}</div>`;
      $$("button[data-i]", res).forEach((b) => b.onclick = async () => { const full = await api(`/api/products/${r.matches[+b.dataset.i].id}`); show(full); });
    } catch (e) { res.innerHTML = `<div class="result-card bad">${esc(e.message)}</div>`; }
  };
  $("[data-find]", container).onclick = find;
  inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); find(); } };
  return { focus: () => { inp.value = ""; pq.focus(); }, clear: () => { res.innerHTML = ""; inp.value = ""; pq.value = ""; pq.focus(); } };
}

/* ------------------------------------------------------------------ shell & routing */
const NAV = [
  { group: "Daily work" },
  { id: "dashboard", label: "Dashboard", show: () => can("reports.view") },
  { id: "bill", label: "Customer entry", show: () => can("billing.create") },
  { id: "invoices", label: "All bills", show: () => canAny("billing.create", "customers.view", "payments.record") },
  { id: "payments", label: "Payments", show: () => can("payments.record") },
  { id: "factory", label: "Company orders", show: () => can("factory.manage") },
  { group: "Stock" },
  { id: "products", label: "Products & numbers", show: () => canAny("products.view", "products.edit") },
  { id: "import", label: "Import from Excel", show: () => can("inventory.import") },
  { id: "stock", label: "Stock movements", show: () => canAny("stock.manage") },
  { group: "Business" },
  { id: "reports", label: "Reports", show: () => can("reports.view") },
  { id: "users", label: "Logins & permissions", show: () => S.user.role === "owner" },
  { id: "settings", label: "Settings & backup", show: () => S.user.role !== "customer" },
];
const ROUTES = {};

function renderShell() {
  const items = S.user.role === "customer" ? [{ id: "me", label: "My account", show: () => true }] : NAV;
  let html = "", pendingGroup = null;
  for (const n of items) {
    if (n.group) { pendingGroup = n.group; continue; }
    if (!n.show()) continue;
    if (pendingGroup) { html += `<div class="group">${esc(pendingGroup)}</div>`; pendingGroup = null; }
    html += `<a href="#/${n.id}" data-nav="${n.id}">${esc(n.label)}</a>`;
  }
  $("#app").innerHTML = `<div class="topbar"><button data-menu>Menu</button><span>${esc(S.business)}</span><span></span></div>
    <div class="shell"><nav class="rail" data-rail><div class="brand"><span class="brand-mark"></span>${esc(S.business)}</div>${html}
    <div class="who"><b>${esc(S.user.full_name || S.user.username)}</b>${esc(S.user.role === "owner" ? "Owner" : S.user.role === "staff" ? "Staff" : "Customer")}
    <a href="#/password">Change password</a><a href="#" data-logout>Log out</a><div class="small" style="margin-top:8px;opacity:.75">Version ${esc(S.version || "")}</div></div></nav>
    <main class="main" id="view"></main></div>`;
  $("[data-logout]").onclick = (e) => { e.preventDefault(); logout(); };
  $("[data-menu]").onclick = () => $("[data-rail]").classList.toggle("open");
}
function defaultRoute() {
  if (S.user.role === "customer") return "me";
  if (can("reports.view")) return "dashboard";
  if (can("billing.create")) return "bill";
  const first = NAV.find((n) => n.id && n.show());
  return first ? first.id : "password";
}
async function route() {
  S.timers.forEach(clearInterval); S.timers = [];
  if (!S.user) return;
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const [name, arg] = path.split("/");
  const r = name || defaultRoute();
  $$("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === r));
  $("[data-rail]")?.classList.remove("open");
  const view = $("#view");
  const fn = ROUTES[r];
  if (!fn) { view.innerHTML = `<div class="panel empty">Page not found. <a href="#/">Go to start</a></div>`; return; }
  view.innerHTML = `<p class="muted">Loading…</p>`;
  try { await fn(view, arg, new URLSearchParams(query || "")); }
  catch (e) { if (e.status !== 401) view.innerHTML = `<div class="panel"><div class="notice err">${esc(e.message)}</div></div>`; }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

function logout(msg) {
  S.token = null; S.user = null; localStorage.removeItem("luxe_token");
  renderLogin(msg);
}
function renderLogin(msg) {
  const swatches = ["#8B5E3C", "#C9A27E", "#3E4A4D", "#D8D2C4", "#6B7F6A", "#A8743F"];
  $("#app").innerHTML = `<div class="login"><div class="login-art"><div><div class="brand" style="padding:0 0 24px"><span class="brand-mark"></span>${esc(S.business)}</div>
    <h1>Every catalogue number, matched to its factory number.</h1>
    <p style="max-width:44ch;color:#E2D3C3">Bills, payments, stock and factory orders for the whole shop, in one place.</p></div>
    <div class="strips">${swatches.map((c) => `<div style="background:${c}"></div>`).join("")}</div></div>
    <div class="login-form"><form class="stack"><h2>Log in</h2>${msg ? `<div class="notice">${esc(msg)}</div>` : ""}
    <label class="f">Username<input name="username" autocomplete="username" required></label>
    <label class="f">Password<input name="password" type="password" autocomplete="current-password" required></label>
    <button class="btn primary xl" style="width:100%">Log in</button></form></div></div>`;
  $("form").onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("form button"); busy(btn, true, "Checking…");
    try {
      const r = await api("/api/auth/login", { method: "POST", body: formData($("form")) });
      S.token = r.token; localStorage.setItem("luxe_token", r.token);
      await boot();
    } catch (err) { toast(err.message, "err"); busy(btn, false); }
  };
}
async function boot() {
  if (!S.token) return renderLogin();
  try {
    const r = await api("/api/auth/me");
    S.user = r.user; S.business = r.business; S.allPerms = r.all_permissions; S.gstRound = r.gst_round !== false; S.version = r.version || ""; S.shop = r.shop || { name: r.business, terms: [] };
    document.title = S.business;
    renderShell(); route();
  } catch (e) { if (e.status !== 401) renderLogin(e.message); }
}

/* ------------------------------------------------------------------ dashboard */
ROUTES.dashboard = async (view) => {
  let period = "month";
  view.innerHTML = `<div class="page-head"><div><h1>Dashboard</h1><p class="muted" data-upd></p></div>
    <div class="row"><div class="seg" data-per><button data-v="today">Today</button><button data-v="month" class="on">This month</button><button data-v="all">All time</button></div>
    ${can("billing.create") ? `<a class="btn primary" href="#/bill">+ Customer entry</a>` : ""}</div></div><div data-body></div>`;
  const load = async () => {
    const d = await api("/api/dashboard/simple", { params: { period } });
    $("[data-upd]", view).textContent = `${{ today: "Today", month: "This month", all: "All time" }[period]} · updated ${new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`;
    $("[data-body]", view).innerHTML = `<div class="stack">
      <div class="big4">
        <a class="big-card" href="#/invoices"><div class="l">Orders</div><div class="v">${d.orders}</div><div class="s">Total ${rs0(d.sales_total)}</div></a>
        <div class="big-card ${d.orders_pending ? "warn" : ""}"><div class="l">Orders pending</div><div class="v">${d.orders_pending}</div><div class="s">${d.orders_delivered} delivered</div></div>
        <a class="big-card good" href="#/payments"><div class="l">Payment received</div><div class="v">${rs0(d.payment_received)}</div><div class="s">${d.orders_paid} orders fully paid</div></a>
        <div class="big-card ${num(d.payment_pending) > 0 ? "bad" : ""}"><div class="l">Payment pending</div><div class="v">${rs0(d.payment_pending)}</div><div class="s">All customers owe ${rs0(d.customers_owe_total)}</div></div>
      </div>
      <div class="grid2">
        <div class="panel flush"><div class="panel-head"><h3>Orders to deliver</h3><span class="small muted">${d.orders_pending} pending</span></div>
          ${table([{ label: "Order", html: (r) => `<b>${esc(r.customer)}</b><br><span class="small muted">${esc(r.number)} · ${fdate(r.date)}${r.area ? " · " + esc(r.area) : ""}</span>` },
            { label: "Total", num: true, html: (r) => rs(r.total) },
            { label: "", html: (r) => can("billing.create") ? `<button class="btn sm" data-dlv="${r.id}">Delivered</button>` : "" }],
            d.to_deliver, { empty: "Nothing pending to deliver.", click: (r) => location.hash = `#/invoice/${r.id}` })}</div>
        <div class="panel flush"><div class="panel-head"><h3>Payment pending</h3><a class="btn sm" href="#/customers">All customers</a></div>
          ${table([{ label: "Customer", html: (r) => `<b>${esc(r.name)}</b><br><span class="small muted">${esc([r.phone, r.area].filter(Boolean).join(" · "))}</span>` },
            { label: "Pending", num: true, html: (r) => `<b class="pend-amt">${rs(r.pending)}</b>` },
            { label: "", html: (r) => can("payments.record") ? `<button class="btn sm" data-rcv="${r.customer_id}">Payment received</button>` : "" }],
            d.to_collect, { empty: "No payment pending.", click: (r) => location.hash = `#/customer/${r.customer_id}` })}</div>
      </div>
      <div class="panel flush"><div class="panel-head"><h3>Latest entries</h3><a class="btn sm" href="#/invoices">See all</a></div>
        ${table([{ label: "Date", html: (r) => `<span class="nowrap">${fdate(r.date)}</span>` }, { label: "Customer", html: (r) => `<b>${esc(r.customer)}</b><br><span class="small muted">${esc(r.number)}</span>` },
          { label: "Total", num: true, html: (r) => rs(r.total) }, { label: "Paid", num: true, html: (r) => rs(r.paid) }, { label: "Pending", num: true, html: (r) => num(r.due) > 0 ? `<b class="pend-amt">${rs(r.due)}</b>` : "—" },
          { label: "Status", html: (r) => payChip(r.payment_status) + " " + (r.delivered ? chip("Delivered", "ok") : chip("Not delivered")) }],
          d.recent, { empty: "No entries yet.", click: (r) => location.hash = `#/invoice/${r.id}` })}</div>
    </div>`;
    $$("[data-dlv]", view).forEach((b) => b.onclick = async () => {
      try { await api(`/api/invoices/${b.dataset.dlv}/delivery`, { method: "POST", body: { delivered: true } }); toast("Marked as delivered."); load(); } catch (e) { toast(e.message, "err"); }
    });
    $$("[data-rcv]", view).forEach((b) => b.onclick = async () => {
      try { const c = await api(`/api/customers/${b.dataset.rcv}`); paymentForm(c, { onDone: () => load() }); } catch (e) { toast(e.message, "err"); }
    });
  };
  $$("[data-per] button", view).forEach((b) => b.onclick = () => { period = b.dataset.v; $$("[data-per] button", view).forEach((x) => x.classList.toggle("on", x === b)); load().catch((e) => toast(e.message, "err")); });
  await load();
  S.timers.push(setInterval(() => load().catch(() => {}), 30000));
};

/* ------------------------------------------------------------------ new bill */
function calcLine(l, mode = "BILL") {
  const r2 = (x) => Math.round((x + Number.EPSILON) * 100) / 100;
  const gross = r2(num(l.qty) * num(l.rate));
  const disc = r2(gross * num(l.discount_pct) / 100);
  const taxable = r2(gross - disc);
  let tax = mode === "CASH" ? 0 : r2(taxable * num(l.tax_rate) / 100);
  if (S.gstRound) tax = Math.round(tax);
  return { gross, disc, taxable, tax, total: r2(taxable + tax) };
}
ROUTES.bill = async (view, editId, qs) => {
  const B = { customer: null, lines: [], idem: uid(), editId: editId ? +editId : null, source: "MANUAL", tax_mode: "BILL", notes: "",
    payMode: "PENDING", payAmt: "", payMethod: "CASH", payRef: "" };
  if (B.editId) {
    const inv = await api(`/api/invoices/${B.editId}`);
    if (inv.status !== "ISSUED") throw new Error("Only active bills can be edited.");
    B.customer = inv.customer; B.source = inv.source; B.tax_mode = inv.tax_mode || "BILL"; B.notes = inv.notes; B.number = inv.number; B.invoice_date = inv.invoice_date;
    B.lines = inv.lines.map((l) => ({ product_id: l.product_id, catalogue_no: l.catalogue_no, factory_order_no: l.factory_order_no, name: l.product_name, brand: l.brand, category: l.category || "", unit: l.unit,
      qty: num(l.qty), rate: num(l.rate), list_rate: num(l.rate), discount_pct: num(l.discount_pct), tax_rate: num(l.tax_rate), fulfilment: l.fulfilment,
      dimensions: l.dimensions, finish: l.finish, instructions: l.instructions }));
  } else if (qs.get("customer")) {
    try { B.customer = await api(`/api/customers/${qs.get("customer")}`); } catch (e) { /* ignore */ }
  }
  view.innerHTML = `<div class="page-head"><div><h1>${B.editId ? "Edit entry " + esc(B.number) : "Customer entry"}</h1>
    <p class="muted">${B.editId ? "Changing lines puts old stock back and takes the new quantities out." : "Customer name, products and quantity, payment. The bill is made automatically."}</p></div></div>
    <div class="steps"><div class="stack">
      <section class="panel"><div class="step-title"><span class="step-n">1</span><h2>Customer</h2></div><div data-cust></div></section>
      <section class="panel"><div class="step-title"><span class="step-n">2</span><h2>Products</h2></div><div data-finder></div></section>
      <section class="panel flush"><div class="panel-head"><h3>Items on this bill</h3><span class="muted small" data-count></span></div><div data-lines></div></section>
      <details class="panel"><summary style="cursor:pointer;font-weight:700">Show bill preview <span class="small muted" style="font-weight:400">(how the printed bill will look)</span></summary><div data-preview style="margin-top:12px"></div></details>
    </div>
    <aside class="sticky-side stack"><section class="panel"><div class="step-title"><span class="step-n">3</span><h2>Total and payment</h2></div><div data-side></div></section></aside></div>`;

  const custBox = $("[data-cust]", view);
  const drawCustomer = () => {
    if (B.customer) {
      custBox.innerHTML = `<div class="picked"><span><b>${esc(B.customer.name)}</b><br><span class="small">${esc(B.customer.code)} · ${esc(B.customer.phone || "no phone")}${B.customer.area ? " · " + esc(B.customer.area) : ""}</span></span>
        ${B.editId ? "" : `<button class="btn sm" data-change>Change</button>`}</div><div data-pending style="margin-top:12px"></div>`;
      const ch = $("[data-change]", custBox); if (ch) ch.onclick = () => { B.customer = null; drawCustomer(); drawSide(); };
      if (!B.editId) loadPending();
      finder.focus();
    } else customerPicker(custBox, (c) => { B.customer = c; drawCustomer(); drawSide(); });
  };
  const loadPending = async () => {
    const box = $("[data-pending]", custBox); if (!box || !B.customer) return;
    try {
      const d = await api("/api/invoices", { params: { customer_id: B.customer.id, payment_status: "DUE", size: 20 } });
      if (!d.items.length) { box.innerHTML = `<div class="small muted">No pending payment for this customer.</div>`; return; }
      const totalDue = d.items.reduce((a, i) => a + num(i.due), 0);
      box.innerHTML = `<div class="pend"><div class="row" style="justify-content:space-between;align-items:center"><b>Old pending for this customer</b><b class="pend-amt">${rs(totalDue)}</b></div>
        ${d.items.map((i) => `<div class="pend-row"><span>${fdate(i.invoice_date)} · ${esc(i.number)} · total ${rs(i.total)}</span><span class="nowrap"><b>${rs(i.due)} pending</b>
          ${can("payments.record") ? ` <button class="btn sm" data-recv="${i.id}">Payment received</button>` : ""}</span></div>`).join("")}</div>`;
      $$("[data-recv]", box).forEach((b) => b.onclick = () => paymentForm(B.customer, { invoiceId: +b.dataset.recv, onDone: () => loadPending() }));
    } catch (e) { box.innerHTML = ""; }
  };
  const finder = productFinder($("[data-finder]", view), (p, res) => {
    const canRate = can("billing.override_price");
    const avail = num(p.available_qty);
    const dt = (l, v) => `<div><div class="small muted">${l}</div><div style="font-weight:700">${v}</div></div>`;
    res.innerHTML = `<div class="result-card">
      <div style="font-size:1.25rem;font-weight:700;margin-bottom:10px">${esc(p.name)}</div>
      <div class="detail-grid">
        ${dt("Design no.", esc(p.catalogue_no))}${dt("Company no.", esc(p.factory_order_no))}${dt("Brand", esc(p.brand || "—"))}${dt("Category", esc(p.category || "—"))}
        ${dt("Price per " + esc(p.unit), rs(p.sale_price))}${dt("GST", num(p.tax_rate) + "%")}${dt("In stock", q3(avail) + " " + esc(p.unit))}${dt("Unit", esc(p.unit))}</div>
      <div class="row" style="margin-top:14px;align-items:flex-end">
        <label class="f" style="flex:0 1 140px">Quantity (${esc(p.unit)})<input data-qty type="number" min="0.001" step="any" value="1"></label>
        <label class="f" style="flex:0 1 150px">Rate (₹)<input data-rate type="number" step="0.01" min="0" value="${num(p.sale_price)}" ${canRate ? "" : "readonly title='Only the owner can change the rate'"}></label>
        <button class="btn primary xl" data-add>Add</button><button class="btn ghost" data-cancel>Clear</button></div>
      <div class="small" data-stockmsg style="margin-top:8px"></div></div>`;
    const qIn = $("[data-qty]", res), msg = $("[data-stockmsg]", res);
    const showStock = () => {
      const q = num(qIn.value);
      msg.innerHTML = q > avail ? `<span class="chip warn">Order from company</span> Only ${q3(avail)} in stock, so this item will be ordered from the company (no. ${esc(p.factory_order_no)}) automatically.`
        : `<span class="chip ok">From stock</span> ${q3(avail - q)} ${esc(p.unit)} will be left after this.`;
    };
    qIn.oninput = showStock; showStock();
    qIn.focus(); qIn.select();
    const add = () => {
      const qty = num(qIn.value);
      if (!(qty > 0)) { toast("Enter a quantity above zero.", "warn"); return; }
      const ful = qty > avail ? "FACTORY" : "STOCK";
      B.lines.push({ product_id: p.id, catalogue_no: p.catalogue_no, factory_order_no: p.factory_order_no, name: p.name, brand: p.brand, category: p.category, unit: p.unit, qty,
        rate: num($("[data-rate]", res).value), list_rate: num(p.sale_price), discount_pct: 0, tax_rate: num(p.tax_rate), fulfilment: ful,
        dimensions: ful === "FACTORY" ? (p.size || "") : "", finish: ful === "FACTORY" ? (p.finish || "") : "", instructions: "" });
      finder.clear(); drawLines(); drawSide();
    };
    $("[data-add]", res).onclick = add;
    $$("input", res).forEach((i) => i.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
    $("[data-cancel]", res).onclick = () => finder.clear();
  }, { exactBox: false });
  const drawLines = () => {
    $("[data-count]", view).textContent = B.lines.length ? `${B.lines.length} item${B.lines.length > 1 ? "s" : ""}` : "";
    $("[data-lines]", view).innerHTML = table([
      { label: "Design", html: (l) => `<b class="nowrap">${esc(l.catalogue_no)}</b><br><span class="small muted nowrap">Co. ${esc(l.factory_order_no)}</span>` },
      { label: "Product", html: (l) => `<b>${esc(l.name)}</b><br><span class="small muted">${esc([l.brand, l.category].filter(Boolean).join(" · ") || "—")}</span>${l.fulfilment === "FACTORY" ? `<br>${chip("Order from company", "warn")}` : ""}` },
      { label: "Qty", num: true, html: (l) => `${q3(l.qty)} ${esc(l.unit)}` },
      { label: "Rate", num: true, html: (l) => rs(l.rate) },
      { label: "GST", num: true, html: (l) => rs(calcLine(l, B.tax_mode).tax) },
      { label: "Net", num: true, html: (l) => `<b>${rs(calcLine(l, B.tax_mode).total)}</b><br><button class="btn sm ghost" style="color:var(--red)" data-rm="${B.lines.indexOf(l)}">Remove</button>` },
    ], B.lines, { empty: "No items yet. Type a catalogue number above." });
    $$("[data-rm]", view).forEach((b) => b.onclick = () => { B.lines.splice(+b.dataset.rm, 1); drawLines(); drawSide(); });
  };
  const drawSide = () => {
    const t = B.lines.reduce((a, l) => { const c = calcLine(l, B.tax_mode); a.gross += c.gross; a.disc += c.disc; a.tax += c.tax; a.total += c.total; return a; }, { gross: 0, disc: 0, tax: 0, total: 0 });
    const side = $("[data-side]", view);
    const taxable = t.gross - t.disc;
    const paid = B.payMode === "FULL" ? t.total : B.payMode === "PART" ? num(B.payAmt) : 0;
    const pending = Math.max(0, t.total - paid);
    side.innerHTML = `<table class="totals">
      <tr><td>Total without GST</td><td class="num">${rs(taxable)}</td></tr>${t.disc ? `<tr><td class="small muted">(discount ${rs(t.disc)} already removed)</td><td></td></tr>` : ""}
      <tr><td>GST${B.tax_mode === "CASH" ? " (cash, none)" : ""}</td><td class="num">${rs(t.tax)}</td></tr>
      <tr class="grand"><td>Total with GST</td><td class="num">${rs(t.total)}</td></tr></table>
      <div class="stack" style="margin-top:16px">
      <div><div class="small" style="font-weight:700;margin-bottom:4px">Category</div>
        <div class="seg seg-wrap" data-tax><button type="button" data-v="BILL" class="${B.tax_mode === "BILL" ? "on" : ""}">Bill (with GST)</button><button type="button" data-v="CASH" class="${B.tax_mode === "CASH" ? "on" : ""}">Cash (no GST)</button></div></div>
      <label class="f">Sale type<select data-srcsel>${Object.entries(SOURCE_LABEL).map(([v, l]) => `<option value="${v}" ${B.source === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      ${!B.editId && can("payments.record") ? `<div><div class="small" style="font-weight:700;margin-bottom:4px">Payment</div>
        <div class="seg seg-wrap" data-pmode><button type="button" data-v="PENDING" class="${B.payMode === "PENDING" ? "on" : ""}">Pending</button><button type="button" data-v="PART" class="${B.payMode === "PART" ? "on" : ""}">Part paid</button><button type="button" data-v="FULL" class="${B.payMode === "FULL" ? "on" : ""}">Full paid</button></div></div>
        ${B.payMode === "PART" ? `<label class="f">Amount received (₹)<input data-pamt type="number" min="0" step="0.01" value="${esc(B.payAmt)}" placeholder="0.00"></label>` : ""}
        ${B.payMode !== "PENDING" ? `<div class="grid2"><label class="f">Paid by<select data-pm>${methodOptions()}</select></label><label class="f">Reference<input data-pref value="${esc(B.payRef)}" placeholder="UTR / cheque no."></label></div>` : ""}
        <div class="paybox"><div><span class="muted">Received</span><b data-recvd>${rs(paid)}</b></div><div><span class="muted">Pending</span><b data-pend class="${pending > 0 ? "pend-amt" : ""}">${rs(pending)}</b></div></div>` : ""}
      <details><summary class="small" style="cursor:pointer">More options</summary><div class="stack" style="margin-top:10px">
        <label class="f">Date<input type="date" data-date value="${B.invoice_date || today()}"></label>
        <label class="f">Note (printed on bill)<textarea data-notes>${esc(B.notes)}</textarea></label></div></details>
      <button class="btn primary xl" data-save ${!B.customer || !B.lines.length ? "disabled" : ""}>${B.editId ? "Save changes" : "Save entry"}</button>
      ${!B.customer ? `<p class="small muted">Write the customer name first.</p>` : !B.lines.length ? `<p class="small muted">Add at least one product.</p>` : `<p class="small muted">After saving, the bill opens on screen. You can view, print or download it any time.</p>`}</div>`;
    const pm = $("[data-pm]", side); if (pm) { pm.value = B.payMethod; pm.onchange = () => B.payMethod = pm.value; }
    const pr = $("[data-pref]", side); if (pr) pr.oninput = () => B.payRef = pr.value;
    const pa = $("[data-pamt]", side);
    if (pa) pa.oninput = () => { B.payAmt = pa.value; const pd = Math.max(0, t.total - num(pa.value)); $("[data-recvd]", side).textContent = rs(num(pa.value)); const pe = $("[data-pend]", side); pe.textContent = rs(pd); pe.classList.toggle("pend-amt", pd > 0); };
    $$("[data-pmode] button", side).forEach((b) => b.onclick = () => { B.payMode = b.dataset.v; drawSide(); const a = $("[data-pamt]", side); if (a) a.focus(); });
    const notes = $("[data-notes]", side); if (notes) notes.oninput = () => B.notes = notes.value;
    $$("[data-tax] button", side).forEach((b) => b.onclick = () => { B.tax_mode = b.dataset.v; drawLines(); drawSide(); });
    $("[data-srcsel]", side).onchange = (e) => { B.source = e.target.value; };
    $("[data-preview]", view).innerHTML = billPreview(B, t);
    const full = $("[data-full]", side); if (full) full.onclick = () => $("[data-pamt]", side).value = t.total.toFixed(2);
    $("[data-save]", side).onclick = () => save(t);
  };
  const save = async (t) => {
    const side = $("[data-side]", view);
    const amt = B.editId ? 0 : B.payMode === "FULL" ? t.total : B.payMode === "PART" ? num(B.payAmt) : 0;
    if (B.payMode === "PART" && !B.editId && !(amt > 0)) { toast("Write the amount received, or choose Pending.", "warn"); return; }
    if (amt > t.total + 0.001) { toast("Received amount is more than the total. Choose Full paid, or record the extra as an advance from the customer's page.", "warn"); return; }
    const factoryCount = B.lines.filter((l) => l.fulfilment === "FACTORY").length;
    const ok = await confirmBox(B.editId ? "Save changes?" : "Save this entry?",
      `<b>${esc(B.customer.name)}</b> · ${B.tax_mode === "CASH" ? "Cash (no GST)" : "Bill with GST"} · ${esc(SOURCE_LABEL[B.source])} · ${B.lines.length} items · <b>${rs(t.total)}</b><br>Received now: <b>${rs(amt)}</b>${amt ? " by " + esc(METHOD_LABEL[B.payMethod]) : ""} · Pending: <b>${rs(Math.max(0, t.total - amt))}</b>${factoryCount ? `<br>${factoryCount} item(s) not in stock will be ordered from the company automatically.` : ""}`, B.editId ? "Save changes" : "Save entry");
    if (!ok) return;
    const btn = $("[data-save]", side); busy(btn, true);
    const body = { customer_id: B.customer.id, source: B.source, tax_mode: B.tax_mode, invoice_date: $("[data-date]", side).value || null, notes: B.notes,
      idempotency_key: B.editId ? null : B.idem,
      lines: B.lines.map((l) => ({ product_id: l.product_id, qty: String(l.qty), rate: l.rate !== l.list_rate ? String(l.rate) : null, discount_pct: String(l.discount_pct || 0), fulfilment: l.fulfilment, dimensions: l.dimensions, finish: l.finish, instructions: l.instructions })) };
    if (amt > 0) body.payment = { amount: amt.toFixed(2), method: B.payMethod, reference: B.payRef };
    try {
      const inv = await api(B.editId ? `/api/invoices/${B.editId}` : "/api/invoices", { method: B.editId ? "PUT" : "POST", body });
      toast(`Entry ${inv.number} saved.`);
      billDone(view, inv);
    } catch (e) { toast(e.message, "err"); busy(btn, false); }
  };
  drawCustomer(); drawLines(); drawSide();
};
const _ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
const _TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];
const _two = (n) => n < 20 ? _ONES[n] : _TENS[Math.floor(n / 10)] + (n % 10 ? " " + _ONES[n % 10] : "");
const _three = (n) => [Math.floor(n / 100) ? _ONES[Math.floor(n / 100)] + " Hundred" : "", n % 100 ? _two(n % 100) : ""].filter(Boolean).join(" ");
function amountInWords(v) {
  const total = Math.round(num(v) * 100), rupees = Math.floor(total / 100), paise = total % 100;
  if (!rupees && !paise) return "Zero Rupees Only";
  let n = rupees; const parts = [];
  const crore = Math.floor(n / 1e7); n %= 1e7; const lakh = Math.floor(n / 1e5); n %= 1e5; const th = Math.floor(n / 1000); n %= 1000;
  if (crore) parts.push(_three(crore) + " Crore"); if (lakh) parts.push(_two(lakh) + " Lakh"); if (th) parts.push(_two(th) + " Thousand"); if (n) parts.push(_three(n));
  let text = rupees ? parts.join(" ") + " Rupees" : "";
  if (paise) text = (text ? text + " and " : "") + _two(paise) + " Paise";
  return text + " Only";
}
function billPreview(B, t) {
  const shop = S.shop || {}, c = B.customer, gst = B.tax_mode !== "CASH";
  const rows = B.lines.map((l, i) => { const x = calcLine(l, B.tax_mode); return `<tr><td>${i + 1}</td><td><b>${esc(l.catalogue_no)}</b> ${esc(l.brand || "")} - ${esc(l.name)}</td><td class="num">${q3(l.qty)}</td><td>${esc(l.unit)}</td><td class="num">${num(l.rate).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td><td class="num">${x.taxable.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td></tr>`; }).join("");
  const blank = Array.from({ length: Math.max(0, 5 - B.lines.length) }, () => `<tr><td>&nbsp;</td><td></td><td></td><td></td><td></td><td></td></tr>`).join("");
  const f2 = (v) => num(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `<div class="bp">
    <div class="bp-firm">${esc((shop.name || S.business).toUpperCase())}<div class="small">${esc([shop.address, shop.phone, shop.gstin ? "GSTIN: " + shop.gstin : ""].filter(Boolean).join(" | "))}</div></div>
    <div class="bp-row3"><b>${gst ? "TAX INVOICE" : "DEBIT MEMO (CASH)"}</b><b>${esc((SOURCE_LABEL[B.source] || "").toUpperCase())}</b><b>Original</b></div>
    <div class="bp-party"><div>M/s. : <b>${c ? esc(c.name.toUpperCase()) : "— select customer —"}</b>${c ? `<div class="small">${esc([c.address, c.area, c.phone ? "Mobile: " + c.phone : ""].filter(Boolean).join(", "))}</div>` : ""}</div>
      <div class="bp-meta">Invoice No. : <b>${B.number ? esc(B.number) : "(given on save)"}</b><br>Date : <b>${fdate(B.invoice_date || today())}</b></div></div>
    <table class="bp-t"><thead><tr><th>SrNo</th><th>Product Name</th><th class="num">Qty</th><th>Unit</th><th class="num">Rate</th><th class="num">Amount</th></tr></thead><tbody>${rows}${blank}</tbody></table>
    <div class="bp-foot"><div><b>Rs. (in words) :</b> ${amountInWords(t.total)}</div>
      <table class="bp-tot"><tr><td>Sub Total</td><td class="num">${f2(t.gross)}</td></tr>${t.disc ? `<tr><td>Discount</td><td class="num">- ${f2(t.disc)}</td></tr>` : ""}
      ${gst ? `<tr><td>CGST</td><td class="num">${f2(t.tax / 2)}</td></tr><tr><td>SGST</td><td class="num">${f2(t.tax / 2)}</td></tr>` : ""}
      <tr class="g"><td>Grand Total</td><td class="num">${f2(t.total)}</td></tr></table></div>
    <div class="bp-terms"><div><b>Terms &amp; Condition :</b>${(shop.terms || []).map((x, i) => `<div class="small"><i>${i + 1}. ${esc(x)}</i></div>`).join("")}</div><div class="right small">For, ${esc(shop.name || S.business)}<br><br><i>(Authorized Signatory)</i></div></div>
  </div>`;
}
function invoiceView(inv) {
  const shop = S.shop || {}, c = inv.customer || {}, gst = (inv.tax_mode || "BILL") !== "CASH";
  const f2 = (v) => num(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const rows = inv.lines.map((l, i) => `<tr><td>${i + 1}</td><td><b>${esc(l.catalogue_no)}</b> ${esc(l.brand || "")} - ${esc(l.product_name)}</td><td>${esc(l.hsn || "")}</td><td class="num">${q3(l.qty)}</td><td>${esc(l.unit)}</td><td class="num">${f2(l.rate)}</td><td class="num">${f2(l.taxable)}</td></tr>`).join("");
  const blank = Array.from({ length: Math.max(0, 5 - inv.lines.length) }, () => `<tr><td>&nbsp;</td><td></td><td></td><td></td><td></td><td></td><td></td></tr>`).join("");
  const pays = (inv.payments || []).filter((p) => !p.is_void);
  return `<div class="bp">
    <div class="bp-firm">${esc((shop.name || S.business).toUpperCase())}<div class="small">${esc([shop.address, shop.phone, shop.gstin ? "GSTIN: " + shop.gstin : ""].filter(Boolean).join(" | "))}</div></div>
    <div class="bp-row3"><b>${gst ? "TAX INVOICE" : "DEBIT MEMO (CASH)"}${inv.status === "CANCELLED" ? " - CANCELLED" : ""}</b><b>${esc((SOURCE_LABEL[inv.source] || "").toUpperCase())}</b><b>Original</b></div>
    <div class="bp-party"><div>M/s. : <b>${esc((c.name || inv.customer_name || "").toUpperCase())}</b><div class="small">${esc([c.address, c.area, c.phone ? "Mobile: " + c.phone : "", c.gstin ? "GSTIN: " + c.gstin : ""].filter(Boolean).join(", "))}</div></div>
      <div class="bp-meta">Invoice No. : <b>${esc(inv.number)}</b><br>Date : <b>${fdate(inv.invoice_date)}</b></div></div>
    <table class="bp-t"><thead><tr><th>SrNo</th><th>Product Name</th><th>HSN</th><th class="num">Qty</th><th>Unit</th><th class="num">Rate</th><th class="num">Amount</th></tr></thead><tbody>${rows}${blank}</tbody></table>
    <div class="bp-foot"><div><b>Rs. (in words) :</b> ${amountInWords(inv.total)}${inv.notes ? `<div style="margin-top:6px"><b>Note :</b> ${esc(inv.notes)}</div>` : ""}</div>
      <table class="bp-tot"><tr><td>Sub Total</td><td class="num">${f2(inv.subtotal)}</td></tr>${num(inv.discount_total) ? `<tr><td>Discount</td><td class="num">- ${f2(inv.discount_total)}</td></tr>` : ""}
      ${gst ? `<tr><td>CGST</td><td class="num">${f2(num(inv.tax_total) / 2)}</td></tr><tr><td>SGST</td><td class="num">${f2(num(inv.tax_total) / 2)}</td></tr>` : ""}
      <tr class="g"><td>Grand Total</td><td class="num">${f2(inv.total)}</td></tr><tr><td>Paid</td><td class="num">${f2(inv.settled)}</td></tr>
      <tr class="g"><td>Balance Due</td><td class="num ${num(inv.due) > 0 ? "pend-amt" : ""}">${f2(inv.due)}</td></tr></table></div>
    ${pays.length ? `<div style="padding:6px 8px"><b>Payments received:</b> ${pays.map((p) => `${fdate(p.paid_on)} ${esc(p.method)} ${p.kind === "REFUND" ? "-" : ""}₹${f2(p.amount)}`).join("; ")}</div>` : ""}
    <div class="bp-terms"><div><b>Terms &amp; Condition :</b>${(shop.terms || []).map((x, i) => `<div class="small"><i>${i + 1}. ${esc(x)}</i></div>`).join("")}</div><div class="right small">For, ${esc(shop.name || S.business)}<br><br><i>(Authorized Signatory)</i></div></div>
  </div>`;
}
function downloadBill(inv) { return download(`/api/invoices/${inv.id}/pdf`, null, `${inv.number}.pdf`); }
async function billDone(view, inv) {
  if (!inv.payments) { try { inv = await api(`/api/invoices/${inv.id}`); } catch (e) { /* keep what we have */ } }
  const paid = inv.payment_status === "PAID";
  let custDue = null;
  try { custDue = (await api(`/api/customers/${inv.customer_id}`)).totals.outstanding; } catch (e) { /* ignore */ }
  view.innerHTML = `<div class="steps"><div class="stack">
      <div class="notice ${paid ? "ok" : ""}"><b>Entry ${esc(inv.number)} saved for ${esc(inv.customer.name)}.</b> ${paid ? "Payment complete." : `Pending ${rs(inv.due)}.`}</div>
      <div class="panel">${invoiceView(inv)}</div></div>
    <aside class="sticky-side stack"><div class="panel stack">
      <table class="totals"><tr><td>Total without GST</td><td class="num">${rs(inv.taxable_total)}</td></tr><tr><td>GST</td><td class="num">${rs(inv.tax_total)}</td></tr>
        <tr class="grand"><td>Total with GST</td><td class="num">${rs(inv.total)}</td></tr></table>
      <div class="paybox"><div><span class="muted">Received</span><b>${rs(inv.settled)}</b></div><div><span class="muted">Pending</span><b class="${num(inv.due) > 0 ? "pend-amt" : ""}">${rs(inv.due)}</b></div></div>
      ${custDue !== null ? `<div class="small">Customer's total pending (all entries): <b class="${num(custDue) > 0 ? "pend-amt" : ""}">${rs(custDue)}</b></div>` : ""}
      ${!paid && can("payments.record") ? `<button class="btn primary xl" data-pay>Payment received</button>` : ""}
      <div class="grid2"><button class="btn" data-open>Open / Print</button><button class="btn" data-dl>Download bill</button></div>
      <button class="btn ${inv.delivery_status === "DELIVERED" ? "" : "primary"}" data-deliv>${inv.delivery_status === "DELIVERED" ? "✓ Delivered (undo)" : "Mark as delivered"}</button>
      ${inv.factory_orders && inv.factory_orders.length ? `<div class="notice small">Company order: ${inv.factory_orders.map((f) => `<a href="#/factory/${f.id}">${esc(f.number)}</a>`).join(", ")}</div>` : ""}
      <div class="grid2"><a class="btn" href="#/customer/${inv.customer_id}">Customer account</a><a class="btn" href="#/bill?r=${Date.now()}">New entry</a></div>
    </div></aside></div>`;
  $("[data-open]", view).onclick = () => openPdf(`/api/invoices/${inv.id}/pdf`);
  $("[data-dl]", view).onclick = () => downloadBill(inv);
  $("[data-deliv]", view).onclick = async () => {
    try { await api(`/api/invoices/${inv.id}/delivery`, { method: "POST", body: { delivered: inv.delivery_status !== "DELIVERED" } }); billDone(view, await api(`/api/invoices/${inv.id}`)); } catch (e) { toast(e.message, "err"); }
  };
  const p = $("[data-pay]", view);
  if (p) p.onclick = () => paymentForm(inv.customer, { invoiceId: inv.id, onDone: async () => billDone(view, await api(`/api/invoices/${inv.id}`)) });
  window.scrollTo(0, 0);
}

/* ------------------------------------------------------------------ bills */
ROUTES.invoices = async (view, _a, qs) => {
  const f = { q: qs.get("q") || "", date_from: "", date_to: "", payment_status: qs.get("ps") || "", status: "", source: "", tax_mode: "", page: 1 };
  view.innerHTML = `<div class="page-head"><div><h1>Bills</h1></div>${can("billing.create") ? `<a class="btn primary" href="#/bill">New bill</a>` : ""}</div>
    <div class="panel flush"><div class="panel-head"><div class="row" style="flex:1">
      <label class="f" style="flex:2 1 220px">Search<input data-f="q" placeholder="Bill number, customer name or phone" value="${esc(f.q)}"></label>
      <label class="f">Payment<select data-f="payment_status"><option value="">All</option><option value="DUE">Has balance due</option><option value="UNPAID">Unpaid</option><option value="PARTIAL">Part paid</option><option value="PAID">Paid</option></select></label>
      <label class="f">Category<select data-f="tax_mode"><option value="">All</option><option value="BILL">Bill (GST)</option><option value="CASH">Cash</option></select></label>
      <label class="f">Status<select data-f="status"><option value="">All</option><option value="ISSUED">Active</option><option value="CANCELLED">Cancelled</option></select></label>
      <label class="f">Type<select data-f="source"><option value="">All</option>${Object.entries(SOURCE_LABEL).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
      <label class="f">From<input type="date" data-f="date_from"></label><label class="f">To<input type="date" data-f="date_to"></label></div></div>
      <div data-list></div></div>`;
  $("[data-f=payment_status]", view).value = f.payment_status;
  const load = async () => {
    const d = await api("/api/invoices", { params: { ...f, size: 50 } });
    $("[data-list]", view).innerHTML = table([
      { label: "Bill", html: (r) => `<b>${esc(r.number)}</b><br><span class="small muted">${fdate(r.invoice_date)}</span>` },
      { label: "Type", html: (r) => taxChip(r.tax_mode) + " " + srcChip(r.source) },
      { label: "Customer", key: "customer_name" },
      { label: "Total", num: true, html: (r) => rs(r.total) },
      { label: "Paid", num: true, html: (r) => rs(r.settled) },
      { label: "Due", num: true, html: (r) => `<b>${rs(r.due)}</b>` },
      { label: "Status", html: (r) => payChip(r.payment_status) + (r.delivery_status === "DELIVERED" ? " " + chip("Delivered", "ok") : "") },
    ], d.items, { empty: "No bills match these filters.", click: (r) => location.hash = `#/invoice/${r.id}` }) + pager(d, (p) => { f.page = p; load(); });
  };
  const reload = debounce(() => { f.page = 1; load().catch((e) => toast(e.message, "err")); }, 300);
  $$("[data-f]", view).forEach((i) => i.addEventListener(i.tagName === "INPUT" && i.type !== "date" ? "input" : "change", () => { f[i.dataset.f] = i.value; reload(); }));
  await load();
};

ROUTES.invoice = async (view, id) => {
  const inv = await api(`/api/invoices/${id}`);
  const active = inv.status === "ISSUED";
  view.innerHTML = `<div class="page-head"><div><h1>Bill ${esc(inv.number)}</h1>
      <p class="muted">${fdate(inv.invoice_date)} · <a href="#/customer/${inv.customer_id}">${esc(inv.customer.name)}</a> · ${taxChip(inv.tax_mode)} ${srcChip(inv.source)} ${active ? payChip(inv.payment_status) : chip("Cancelled", "bad")}</p></div>
    <div class="row"><button class="btn primary" data-pdf>Open / Print</button><button class="btn" data-dlb>Download bill</button>
      ${active && can("payments.record") && num(inv.due) > 0 ? `<button class="btn" data-pay>Record payment</button>` : ""}
      ${active ? `<button class="btn" data-dlv>${inv.delivery_status === "DELIVERED" ? "Mark not delivered" : "Mark delivered"}</button>` : ""}
      ${active && can("billing.edit") ? `<a class="btn" href="#/bill/${inv.id}">Edit</a><button class="btn danger" data-cancel>Cancel bill</button>` : ""}
      ${active && can("payments.edit") ? `<button class="btn" data-cn>Credit note</button>` : ""}</div></div>
    ${inv.status === "CANCELLED" ? `<div class="notice err" style="margin-bottom:16px">Cancelled: ${esc(inv.cancel_reason)}</div>` : ""}
    <div class="stack"><div class="panel flush">${table([
      { label: "Product", html: (l) => `${tag(l.catalogue_no, l.factory_order_no)}<br><b>${esc(l.product_name)}</b>${l.fulfilment === "FACTORY" ? `<br>${chip("Factory order", "warn")} <span class="small muted">${esc([l.dimensions, l.finish, l.instructions].filter(Boolean).join(" · "))}</span>` : ""}` },
      { label: "Qty", num: true, html: (l) => `${q3(l.qty)} ${esc(l.unit)}` }, { label: "Rate", num: true, html: (l) => rs(l.rate) },
      { label: "Disc %", num: true, key: "discount_pct" }, { label: "Taxable", num: true, html: (l) => rs(l.taxable) },
      { label: "GST", num: true, html: (l) => `${rs(l.tax_amount)}<br><span class="small muted">${l.tax_rate}%</span>` }, { label: "Amount", num: true, html: (l) => `<b>${rs(l.line_total)}</b>` }], inv.lines)}
      <div style="display:flex;justify-content:flex-end;padding:16px 20px"><table class="totals" style="max-width:340px">
      <tr><td>Subtotal</td><td class="num">${rs(inv.subtotal)}</td></tr><tr><td>Discount</td><td class="num">− ${rs(inv.discount_total)}</td></tr>
      <tr><td>GST</td><td class="num">${rs(inv.tax_total)}</td></tr><tr class="grand"><td>Total</td><td class="num">${rs(inv.total)}</td></tr>
      <tr><td>Paid / adjusted</td><td class="num">${rs(inv.settled)}</td></tr><tr><td><b>Balance due</b></td><td class="num"><b>${rs(inv.due)}</b></td></tr></table></div></div>
    <div class="grid2"><div class="panel flush"><div class="panel-head"><h3>Payments</h3></div>${paymentsTable(inv.payments, () => route())}</div>
    <div class="panel flush"><div class="panel-head"><h3>Factory orders</h3></div>${table([{ label: "Order", html: (o) => `<b>${esc(o.number)}</b>` }, { label: "Status", html: (o) => foChip(o.status) },
      { label: "Factory numbers", html: (o) => o.lines.map((l) => esc(l.factory_order_no)).join(", ") }], inv.factory_orders, { empty: "All items from stock.", click: (o) => can("factory.manage") && (location.hash = `#/factory/${o.id}`) })}
      ${inv.credit_notes.length ? `<div class="panel-head"><h3>Credit notes</h3></div>${table([{ label: "No.", key: "number" }, { label: "Date", html: (n) => fdate(n.note_date) }, { label: "Reason", key: "reason" }, { label: "Amount", num: true, html: (n) => n.is_void ? chip("Void") : rs(n.amount) }], inv.credit_notes)}` : ""}</div></div>
    <details class="panel" open><summary style="cursor:pointer;font-weight:700">Bill</summary><div style="margin-top:12px">${invoiceView(inv)}</div></details></div>`;
  $("[data-pdf]", view).onclick = () => openPdf(`/api/invoices/${inv.id}/pdf`);
  $("[data-dlb]", view).onclick = () => downloadBill(inv);
  const on = (sel, fn) => { const el = $(sel, view); if (el) el.onclick = fn; };
  on("[data-pay]", () => paymentForm(inv.customer, { invoiceId: inv.id, onDone: () => route() }));
  on("[data-cn]", () => creditNoteForm(inv.customer, inv, () => route()));
  on("[data-dlv]", async () => { try { await api(`/api/invoices/${inv.id}/delivery`, { method: "POST", body: { delivered: inv.delivery_status !== "DELIVERED" } }); toast("Delivery status saved."); route(); } catch (e) { toast(e.message, "err"); } });
  on("[data-cancel]", async () => {
    const reason = await promptBox(`Cancel bill ${inv.number}?`, "Reason for cancelling (stock from this bill goes back to the shelf)", "Cancel bill");
    if (!reason) return;
    try { await api(`/api/invoices/${inv.id}/cancel`, { method: "POST", body: { reason } }); toast(`Bill ${inv.number} cancelled.`); route(); } catch (e) { toast(e.message, "err"); }
  });
};

function paymentsTable(pays, refresh) {
  const id = "pt" + Math.random().toString(36).slice(2, 6);
  setTimeout(() => {
    const el = document.getElementById(id); if (!el) return;
    $$("[data-void]", el).forEach((b) => b.onclick = async () => {
      const p = pays.find((x) => x.id === +b.dataset.void);
      const reason = await promptBox(`Void ${p.number}?`, `Reason (amount ${rs(p.amount)} will be removed from the customer's account)`, "Void payment");
      if (!reason) return;
      try { await api(`/api/payments/${p.id}/void`, { method: "POST", body: { reason } }); toast(`${p.number} voided.`); refresh(); } catch (e) { toast(e.message, "err"); }
    });
  });
  return `<div id="${id}">${table([
    { label: "Receipt", html: (p) => `<b>${esc(p.number)}</b><br><span class="small muted">${fdate(p.paid_on)}</span>` },
    { label: "Bill", html: (p) => p.invoice_number ? esc(p.invoice_number) : chip("Advance") },
    { label: "Method", html: (p) => `${methodChip(p.method)}${p.reference ? `<br><span class="small muted">${esc(p.reference)}</span>` : ""}` },
    { label: "Amount", num: true, html: (p) => p.is_void ? `<s>${rs(p.amount)}</s> ${chip("Void")}` : (p.kind === "REFUND" ? "− " : "") + rs(p.amount) },
    { label: "", html: (p) => !p.is_void && can("payments.edit") ? `<button class="btn sm danger" data-void="${p.id}">Void</button>` : "" }], pays, { empty: "No payments yet." })}</div>`;
}

async function paymentForm(customer, { invoiceId = null, onDone } = {}) {
  const acc = await api(`/api/customers/${customer.id}/account`).catch(() => null);
  const open = acc ? acc.invoices.filter((i) => i.status === "ISSUED" && num(i.due) > 0) : [];
  const key = uid();
  const { box, close } = modal(`<h2>Payment received</h2><p><b>${esc(customer.name)}</b> (${esc(customer.code)})${acc ? ` · total pending <b>${rs(acc.totals.outstanding)}</b>` : ""}</p>
    <form class="stack">
      ${can("payments.edit") ? `<div class="seg" data-kind><button type="button" class="on" data-v="PAYMENT">Payment received</button><button type="button" data-v="REFUND">Refund given</button></div>` : ""}
      <label class="f">Against bill<select name="invoice_id"><option value="">Advance / on account (no specific bill)</option>
        ${open.map((i) => `<option value="${i.id}" data-due="${i.due}" ${i.id === invoiceId ? "selected" : ""}>${esc(i.number)} · ${fdate(i.invoice_date)} · due ${rs(i.due)}</option>`).join("")}</select></label>
      <div class="grid2"><label class="f">Amount (₹)<input name="amount" type="number" min="0.01" step="0.01" required></label>
      <label class="f">Date<input name="paid_on" type="date" value="${today()}"></label></div>
      <div class="grid2"><label class="f">Method<select name="method">${methodOptions()}</select></label>
      <label class="f">Reference <span class="hint">UTR, cheque or transaction no.</span><input name="reference"></label></div>
      <label class="f">Notes<input name="notes"></label>
      <div class="modal-actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">Save payment</button></div></form>`);
  let kind = "PAYMENT";
  $$("[data-kind] button", box).forEach((b) => b.onclick = () => { kind = b.dataset.v; $$("[data-kind] button", box).forEach((x) => x.classList.toggle("on", x === b)); $("button.primary", box).textContent = kind === "REFUND" ? "Save refund" : "Save payment"; });
  const sel = $("[name=invoice_id]", box), amt = $("[name=amount]", box);
  const fill = () => { const o = sel.selectedOptions[0]; if (o && o.dataset.due) amt.value = num(o.dataset.due).toFixed(2); };
  sel.onchange = fill; fill();
  const submit = async (confirmDup) => {
    const btn = $("button.primary", box); busy(btn, true);
    const body = { ...formData($("form", box)), customer_id: customer.id, kind, idempotency_key: key, confirm_duplicate: !!confirmDup };
    body.invoice_id = body.invoice_id ? +body.invoice_id : null;
    try {
      const r = await api("/api/payments", { method: "POST", body });
      toast(`${r.number} saved. Customer total pending: ${rs(r.customer_outstanding)}.`); close();
      if (body.invoice_id && kind === "PAYMENT") {
        try { const inv = await api(`/api/invoices/${body.invoice_id}`); toast(num(inv.due) <= 0 ? `Payment complete for ${inv.number}.` : `${inv.number}: ${rs(inv.due)} still pending.`); } catch (e2) { /* ignore */ }
      }
      onDone && onDone(r);
    } catch (e) {
      busy(btn, false);
      if (e.status === 409 && e.data && e.data.needs_confirmation) {
        if (await confirmBox("Possible duplicate payment", esc(e.message), "Yes, save it again")) submit(true);
      } else toast(e.message, "err");
    }
  };
  $("form", box).onsubmit = (e) => { e.preventDefault(); submit(false); };
}
function creditNoteForm(customer, inv, onDone) {
  const { box, close } = modal(`<h2>Credit note</h2><p>${esc(customer.name)}${inv ? ` · bill ${esc(inv.number)} (due ${rs(inv.due)})` : ""}</p>
    <form class="stack"><label class="f">Amount (₹)<input name="amount" type="number" step="0.01" min="0.01" required></label>
    <label class="f">Reason<input name="reason" required placeholder="e.g. Rate correction, damaged item returned"></label>
    <div class="modal-actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">Save credit note</button></div></form>`);
  $("form", box).onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/credit-notes", { method: "POST", body: { ...formData(box), customer_id: customer.id, invoice_id: inv ? inv.id : null } });
      toast(`${r.number} saved. Customer now owes ${rs(r.customer_outstanding)}.`); close(); onDone();
    } catch (err) { toast(err.message, "err"); }
  };
}

/* ------------------------------------------------------------------ customers */
ROUTES.customers = async (view) => {
  const f = { q: "", only_outstanding: false, page: 1 };
  view.innerHTML = `<div class="page-head"><h1>Customers</h1>${canAny("customers.edit", "billing.create") ? `<button class="btn primary" data-new>Add customer</button>` : ""}</div>
    <div class="panel flush"><div class="panel-head"><div class="row" style="flex:1"><label class="f" style="flex:3 1 260px">Search<input data-q placeholder="Name, phone, area, customer ID or bill number"></label>
    <label class="check" style="padding-bottom:12px"><input type="checkbox" data-o> Only customers who owe money</label></div></div><div data-list></div></div>`;
  const load = async () => {
    const d = await api("/api/customers", { params: { ...f, size: 50 } });
    $("[data-list]", view).innerHTML = table([
      { label: "Customer", html: (c) => `<b>${esc(c.name)}</b>${c.is_active ? "" : " " + chip("Inactive")}<br><span class="small muted">${esc(c.code)}</span>` },
      { label: "Phone", key: "phone" }, { label: "Area", key: "area" }, { label: "Owes", num: true, html: (c) => num(c.outstanding) > 0 ? `<b>${rs(c.outstanding)}</b>` : num(c.outstanding) < 0 ? `<span class="muted">Advance ${rs(-num(c.outstanding))}</span>` : `<span class="muted">—</span>` }],
      d.items, { empty: "No customers found.", click: (c) => location.hash = `#/customer/${c.id}` }) + pager(d, (p) => { f.page = p; load(); });
  };
  const reload = debounce(() => { f.page = 1; load().catch((e) => toast(e.message, "err")); });
  $("[data-q]", view).oninput = (e) => { f.q = e.target.value; reload(); };
  $("[data-o]", view).onchange = (e) => { f.only_outstanding = e.target.checked; reload(); };
  const nb = $("[data-new]", view); if (nb) nb.onclick = () => customerForm(null, (c) => location.hash = `#/customer/${c.id}`);
  $("[data-q]", view).focus();
  await load();
};

ROUTES.customer = async (view, id, qs) => {
  if (!can("customers.view")) throw new Error("You don't have permission to open customer accounts.");
  const a = await api(`/api/customers/${id}/account`);
  const c = a.customer, t = a.totals;
  const tab = qs.get("tab") || "bills";
  view.innerHTML = `<div class="page-head"><div><h1>${esc(c.name)}</h1><p class="muted">${esc(c.code)} · ${esc(c.phone || "no phone")}${c.area ? " · " + esc(c.area) : ""}${c.gstin ? " · GSTIN " + esc(c.gstin) : ""}${c.address ? "<br>" + esc(c.address) : ""}</p></div>
    <div class="row">${can("billing.create") ? `<a class="btn primary" href="#/bill?customer=${c.id}">New bill</a>` : ""}
    ${can("payments.record") ? `<button class="btn" data-pay>Record payment</button>` : ""}<button class="btn" data-stmt>Statement PDF</button><button class="btn" data-xls>Download Excel</button>
    ${can("payments.edit") ? `<button class="btn" data-cn>Credit note</button>` : ""}${can("customers.edit") ? `<button class="btn" data-edit>Edit</button>` : ""}
    ${S.user.role === "owner" ? `<button class="btn" data-login>Create customer login</button>` : ""}</div></div>
    <div class="stats" style="margin-bottom:16px"><div class="stat"><div class="l">Total billed</div><div class="v">${rs(t.billed)}</div></div>
      <div class="stat"><div class="l">Payments received</div><div class="v">${rs(t.paid)}</div></div>
      <div class="stat"><div class="l">Refunds · credit notes</div><div class="v">${rs(t.refunded)} · ${rs(t.credited)}</div></div>
      <div class="stat ${num(t.outstanding) > 0 ? "alert" : "key"}"><div class="l">${num(t.outstanding) >= 0 ? "Outstanding balance" : "Advance with us"}</div><div class="v">${rs(Math.abs(num(t.outstanding)))}</div></div></div>
    ${typeBreakdown(a.invoices)}
    <div class="panel flush"><div class="tabs">${[["bills", `Bills (${a.invoices.length})`], ["payments", `Payments (${a.payments.length})`], ["orders", `Orders (${a.orders.length})`], ["products", "Products bought"], ["credit", `Credit notes (${a.credit_notes.length})`]].map(([k, l]) => `<button data-tab="${k}" class="${k === tab ? "on" : ""}">${l}</button>`).join("")}</div><div data-tabbody></div></div>`;
  const body = $("[data-tabbody]", view);
  const draw = (k) => {
    $$("[data-tab]", view).forEach((b) => b.classList.toggle("on", b.dataset.tab === k));
    if (k === "bills") body.innerHTML = table([
      { label: "Bill", html: (i) => `<b>${esc(i.number)}</b><br><span class="small muted">${fdate(i.invoice_date)}</span>` }, { label: "Type", html: (i) => taxChip(i.tax_mode) + " " + srcChip(i.source) },
      { label: "Items", html: (i) => i.lines.map((l) => `${esc(l.product_name)} × ${q3(l.qty)} ${esc(l.unit)}${l.category ? ` <span class="small muted">(${esc(l.category)})</span>` : ""}`).join("<br>") }, { label: "Total", num: true, html: (i) => rs(i.total) },
      { label: "Paid", num: true, html: (i) => rs(i.settled) }, { label: "Due", num: true, html: (i) => `<b>${rs(i.due)}</b>` },
      { label: "Status", html: (i) => payChip(i.payment_status) + " " + (i.status === "ISSUED" ? chip(i.delivery_status === "DELIVERED" ? "Delivered" : "Delivery pending", i.delivery_status === "DELIVERED" ? "ok" : "") : "") },
      { label: "", html: (i) => `<span class="nowrap"><button class="btn sm" data-ipdf="${i.id}">Open</button> <button class="btn sm" data-idl="${i.id}">Download</button></span>` }], a.invoices, { empty: "No bills yet.", click: (i) => location.hash = `#/invoice/${i.id}` });
    if (k === "payments") body.innerHTML = paymentsTable(a.payments, () => route());
    if (k === "orders") body.innerHTML = table([{ label: "Order", html: (o) => `<b>${esc(o.number)}</b><br><span class="small muted">${fdate(o.created_at)}</span>` }, { label: "Status", html: (o) => foChip(o.status) },
      { label: "Items", html: (o) => o.lines.map((l) => `${tag(l.catalogue_no, l.factory_order_no)} ${esc(l.product_name)} × ${q3(l.qty)}`).join("<br>") }], a.orders, { empty: "No factory orders.", click: (o) => can("factory.manage") && (location.hash = `#/factory/${o.id}`) });
    if (k === "products") {
      const m = {};
      a.invoices.filter((i) => i.status === "ISSUED").forEach((i) => i.lines.forEach((l) => { const key = l.catalogue_no + "|" + l.product_name; m[key] = m[key] || { ...l, qty: 0, amount: 0, bills: 0 }; m[key].qty += num(l.qty); m[key].amount += num(l.line_total); m[key].bills++; }));
      const list = Object.values(m).sort((x, y) => (x.category || "~").localeCompare(y.category || "~") || y.amount - x.amount);
      body.innerHTML = table([{ label: "Category", html: (l) => esc(l.category || "—") }, { label: "Product", html: (l) => `${tag(l.catalogue_no, l.factory_order_no)} <b>${esc(l.product_name)}</b>${l.brand ? ` <span class="small muted">${esc(l.brand)}</span>` : ""}` },
        { label: "Total qty", num: true, html: (l) => `${q3(l.qty)} ${esc(l.unit)}` }, { label: "Bills", num: true, key: "bills" }, { label: "Amount", num: true, html: (l) => rs(l.amount) }], list, { empty: "Nothing bought yet." });
    }
    if (k === "credit") body.innerHTML = table([{ label: "No.", key: "number" }, { label: "Date", html: (n) => fdate(n.note_date) }, { label: "Bill", key: "invoice_number" }, { label: "Reason", key: "reason" }, { label: "Amount", num: true, html: (n) => n.is_void ? chip("Void") : rs(n.amount) }], a.credit_notes, { empty: "No credit notes." });
    $$("[data-ipdf]", body).forEach((b) => b.onclick = () => openPdf(`/api/invoices/${b.dataset.ipdf}/pdf`));
    $$("[data-idl]", body).forEach((b) => b.onclick = () => { const i = a.invoices.find((x) => x.id === +b.dataset.idl); downloadBill(i); });
  };
  $$("[data-tab]", view).forEach((b) => b.onclick = () => draw(b.dataset.tab));
  draw(tab);
  const on = (sel, fn) => { const el = $(sel, view); if (el) el.onclick = fn; };
  on("[data-pay]", () => paymentForm(c, { onDone: () => route() }));
  on("[data-xls]", () => download(`/api/customers/${c.id}/export.xlsx`, null, `${c.code}_account.xlsx`));
  on("[data-cn]", () => creditNoteForm(c, null, () => route()));
  on("[data-edit]", () => customerForm(c, () => route()));
  on("[data-login]", () => userForm(null, { role: "customer", customer: c }));
  on("[data-stmt]", () => {
    const { box, close } = modal(`<h2>Customer statement</h2><p class="muted">Leave dates empty for the full history.</p><div class="grid2"><label class="f">From<input type="date" data-from></label><label class="f">To<input type="date" data-to value="${today()}"></label></div>
      <div class="modal-actions"><button class="btn" data-close>Cancel</button><button class="btn primary" data-go>Open PDF</button></div>`);
    $("[data-go]", box).onclick = () => { openPdf(`/api/customers/${c.id}/statement.pdf`, { date_from: $("[data-from]", box).value, date_to: $("[data-to]", box).value }); close(); };
  });
};

function typeBreakdown(invoices) {
  const g = {};
  invoices.filter((i) => i.status === "ISSUED").forEach((i) => { const x = g[i.source] = g[i.source] || { n: 0, total: 0, paid: 0, due: 0 }; x.n++; x.total += num(i.total); x.paid += num(i.settled); x.due += num(i.due); });
  const rows = Object.entries(g).map(([src, x]) => ({ src, ...x }));
  if (!rows.length) return "";
  return `<div class="panel flush" style="margin-bottom:16px"><div class="panel-head"><h3>By bill type</h3></div>${table([
    { label: "Type", html: (r) => srcChip(r.src) }, { label: "Bills", num: true, key: "n" }, { label: "Total with GST", num: true, html: (r) => rs(r.total) },
    { label: "Paid", num: true, html: (r) => rs(r.paid) }, { label: "Still to pay", num: true, html: (r) => `<b>${rs(r.due)}</b>` }], rows)}</div>`;
}

/* ------------------------------------------------------------------ payments page */
ROUTES.payments = async (view) => {
  const f = { date_from: "", date_to: "", method: "", include_void: false, page: 1 };
  view.innerHTML = `<div class="page-head"><h1>Payments</h1><button class="btn primary" data-new>Record payment</button></div>
    <div class="panel flush"><div class="panel-head"><div class="row" style="flex:1"><label class="f">From<input type="date" data-f="date_from"></label><label class="f">To<input type="date" data-f="date_to"></label>
    <label class="f">Method<select data-f="method"><option value="">All</option>${methodOptions()}</select></label>
    <label class="check" style="padding-bottom:12px"><input type="checkbox" data-f="include_void"> Show voided</label></div></div><div data-list></div></div>`;
  const load = async () => {
    const d = await api("/api/payments", { params: { ...f, size: 50 } });
    $("[data-list]", view).innerHTML = table([{ label: "Customer", html: (p) => `<a href="#/customer/${p.customer_id}">${esc(p.customer_name)}</a>` }, ...[
      { label: "Receipt", html: (p) => `<b>${esc(p.number)}</b><br><span class="small muted">${fdate(p.paid_on)}</span>` },
      { label: "Bill", html: (p) => p.invoice_number ? `<a href="#/invoice/${p.invoice_id}">${esc(p.invoice_number)}</a>` : chip("Advance") },
      { label: "Method", html: (p) => `${methodChip(p.method)}<br><span class="small muted">${esc(p.reference)}</span>` },
      { label: "Amount", num: true, html: (p) => p.is_void ? `<s>${rs(p.amount)}</s> ${chip("Void")}` : (p.kind === "REFUND" ? chip("Refund", "warn") + " − " : "") + rs(p.amount) }]], d.items, { empty: "No payments in this period." }) + pager(d, (p) => { f.page = p; load(); });
  };
  $$("[data-f]", view).forEach((i) => i.onchange = () => { f[i.dataset.f] = i.type === "checkbox" ? i.checked : i.value; f.page = 1; load(); });
  $("[data-new]", view).onclick = () => {
    const { box, close } = modal(`<h2>Record payment</h2><p class="muted">First find the customer.</p><div data-cp></div><div class="modal-actions"><button class="btn" data-close>Cancel</button></div>`);
    customerPicker($("[data-cp]", box), (c) => { close(); paymentForm(c, { onDone: () => load() }); }, { allowCreate: false });
  };
  await load();
};

/* ------------------------------------------------------------------ factory orders */
const FO_FLOW = ["PENDING", "APPROVED", "SENT_TO_FACTORY", "IN_PRODUCTION", "READY", "DISPATCHED", "DELIVERED"];
ROUTES.factory = async (view, id, qs) => {
  if (id) return factoryDetail(view, id);
  const f = { status: qs.get("status") || "OPEN", q: "", page: 1 };
  view.innerHTML = `<div class="page-head"><div><h1>Factory orders</h1><p class="muted">Orders go to the factory with the factory number; your catalogue number is shown for checking.</p></div><button class="btn primary" data-new>New stock order</button></div>
    <div class="panel flush"><div class="panel-head"><div class="row" style="flex:1"><div class="seg" data-st style="flex-wrap:wrap"></div>
    <label class="f" style="flex:1 1 220px">Find<input data-q placeholder="Order no., factory no. or catalogue no."></label></div></div><div data-list></div></div>`;
  const load = async () => {
    const d = await api("/api/factory-orders", { params: { ...f, size: 50 } });
    const open = FO_FLOW.slice(0, 6).reduce((s, k) => s + (d.counts[k] || 0), 0);
    $("[data-st]", view).innerHTML = [["OPEN", `Open (${open})`], ...FO_FLOW.map((s) => [s, `${statusWords(s)} (${d.counts[s] || 0})`]), ["CANCELLED", "Cancelled"], ["", "All"]].map(([v, l]) => `<button data-v="${v}" class="${f.status === v ? "on" : ""}">${l}</button>`).join("");
    $$("[data-st] button", view).forEach((b) => b.onclick = () => { f.status = b.dataset.v; f.page = 1; load(); });
    $("[data-list]", view).innerHTML = table([
      { label: "Order", html: (o) => `<b>${esc(o.number)}</b><br><span class="small muted">${fdate(o.created_at)}</span>` },
      { label: "For", html: (o) => esc(o.customer_name) + `<br><span class="small muted">${esc(o.supplier)}</span>` },
      { label: "Items", html: (o) => o.lines.map((l) => `${tag(l.catalogue_no, l.factory_order_no)} × ${q3(l.qty)}`).join("<br>") },
      { label: "Status", html: (o) => foChip(o.status) + (o.expected_date ? `<br><span class="small muted">Due ${fdate(o.expected_date)}</span>` : "") }],
      d.items, { empty: "No orders here.", click: (o) => location.hash = `#/factory/${o.id}` }) + pager(d, (p) => { f.page = p; load(); });
  };
  $("[data-q]", view).oninput = debounce((e) => { f.q = e.target.value; f.page = 1; load(); });
  $("[data-new]", view).onclick = () => newFactoryOrder(() => load());
  await load();
};
async function factoryDetail(view, id) {
  const o = await api(`/api/factory-orders/${id}`);
  const i = FO_FLOW.indexOf(o.status), next = i >= 0 && i < FO_FLOW.length - 1 ? FO_FLOW[i + 1] : null;
  const done = ["DELIVERED", "CANCELLED"].includes(o.status);
  view.innerHTML = `<div class="page-head"><div><h1>Factory order ${esc(o.number)}</h1><p class="muted">${esc(o.supplier)} · for ${o.customer_id ? `<a href="#/customer/${o.customer_id}">${esc(o.customer_name)}</a>` : "stock"}${o.invoice_id ? ` · <a href="#/invoice/${o.invoice_id}">from bill</a>` : ""} · ${foChip(o.status)}</p></div>
    <div class="row"><button class="btn" data-pdf>Print for factory</button>${!done && next ? `<button class="btn primary" data-next>Mark as ${statusWords(next).toLowerCase()}</button>` : ""}
    ${!done ? `<button class="btn" data-move>Other status</button><button class="btn danger" data-cancel>Cancel order</button>` : ""}</div></div>
    <div class="panel" style="margin-bottom:16px"><div class="row" style="gap:6px">${FO_FLOW.map((s, k) => `<span class="chip ${o.status === "CANCELLED" ? "" : k <= i ? "ok" : ""}">${statusWords(s)}</span>`).join("<span class='muted'>›</span>")}</div>
    ${o.customer_id ? `<p class="small muted" style="margin-top:10px">At "Ready" the goods are added to stock and reserved for this customer. At "Dispatched" they leave the stock.</p>` : `<p class="small muted" style="margin-top:10px">Stock order: at "Ready" the goods are added to free stock.</p>`}</div>
    <div class="grid2"><div class="panel flush"><div class="panel-head"><h3>Items</h3></div>${table([
      { label: "Numbers", html: (l) => tag(l.catalogue_no, l.factory_order_no, { lg: false }) }, { label: "Product", html: (l) => `<b>${esc(l.product_name)}</b><br><span class="small muted">${esc([l.dimensions, l.finish].filter(Boolean).join(" · "))}</span>${l.instructions ? `<br><span class="small">${esc(l.instructions)}</span>` : ""}` },
      { label: "Qty", num: true, html: (l) => `${q3(l.qty)} ${esc(l.unit)}` }], o.lines)}</div>
    <div class="panel flush"><div class="panel-head"><h3>History</h3><button class="btn sm" data-edit>Edit date & notes</button></div>${table([{ label: "When", html: (e) => fdt(e.at) }, { label: "Change", html: (e) => `${e.from ? statusWords(e.from) + " › " : ""}<b>${statusWords(e.to)}</b>` }, { label: "Note", key: "note" }], [...o.events].reverse())}
    <div style="padding:14px 20px">${o.expected_date ? `Required by <b>${fdate(o.expected_date)}</b><br>` : ""}${esc(o.notes)}</div></div></div>`;
  const setStatus = async (status, note = "") => {
    try { await api(`/api/factory-orders/${o.id}/status`, { method: "POST", body: { status, note } }); toast(`${o.number} is now ${statusWords(status).toLowerCase()}.`); route(); } catch (e) { toast(e.message, "err"); }
  };
  $("[data-pdf]", view).onclick = () => openPdf(`/api/factory-orders/${o.id}/pdf`);
  const on = (sel, fn) => { const el = $(sel, view); if (el) el.onclick = fn; };
  on("[data-next]", async () => { if (await confirmBox(`Mark ${o.number} as ${statusWords(next).toLowerCase()}?`, next === "READY" ? "The goods will be added to stock." : next === "DISPATCHED" ? "The goods will be taken out of stock." : "", "Yes, update")) setStatus(next); });
  on("[data-cancel]", async () => { const r = await promptBox(`Cancel ${o.number}?`, "Reason", "Cancel order"); if (r) setStatus("CANCELLED", r); });
  on("[data-move]", () => {
    const { box, close } = modal(`<h2>Change status</h2><label class="f">New status<select data-s>${FO_FLOW.slice(i + 1).map((s) => `<option value="${s}">${statusWords(s)}</option>`).join("")}</select></label>
      <label class="f" style="margin-top:12px">Note<input data-n></label><div class="modal-actions"><button class="btn" data-close>Cancel</button><button class="btn primary" data-go>Save</button></div>`);
    $("[data-go]", box).onclick = () => { close(); setStatus($("[data-s]", box).value, $("[data-n]", box).value); };
  });
  on("[data-edit]", () => {
    const { box, close } = modal(`<h2>Edit order</h2><form class="stack"><label class="f">Required by<input type="date" name="expected_date" value="${o.expected_date || ""}"></label><label class="f">Notes<textarea name="notes">${esc(o.notes)}</textarea></label>
      <div class="modal-actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">Save</button></div></form>`);
    $("form", box).onsubmit = async (e) => { e.preventDefault(); const b = formData(box); b.expected_date = b.expected_date || null; try { await api(`/api/factory-orders/${o.id}`, { method: "PATCH", body: b }); close(); route(); } catch (err) { toast(err.message, "err"); } };
  });
}
function newFactoryOrder(onDone) {
  const lines = [];
  let customer = null;
  const { box, close } = modal(`<h2>New factory order</h2><p class="muted">For refilling stock, or for a customer before billing.</p>
    <div data-cbox class="stack"><button class="btn ghost" data-pickc>+ Link to a customer (optional)</button></div><div data-f style="margin-top:12px"></div><div data-l style="margin-top:12px"></div>
    <div class="grid2" style="margin-top:12px"><label class="f">Required by<input type="date" data-exp></label><label class="f">Notes<input data-notes></label></div>
    <div class="modal-actions"><button class="btn" data-close>Cancel</button><button class="btn primary" data-save>Create order</button></div>`, { wide: true });
  const drawL = () => { $("[data-l]", box).innerHTML = table([{ label: "Numbers", html: (l) => tag(l.catalogue_no, l.factory_order_no) }, { label: "Product", key: "name" }, { label: "Qty", num: true, html: (l) => q3(l.qty) }, { label: "Details", html: (l) => esc([l.dimensions, l.finish, l.instructions].filter(Boolean).join(" · ")) }], lines, { empty: "Add items by catalogue number." }); };
  const finder = productFinder($("[data-f]", box), (p, res) => {
    res.innerHTML = `<div class="result-card">${tag(p.catalogue_no, p.factory_order_no, { lg: true })} <b style="margin-left:10px">${esc(p.name)}</b>
      <div class="row" style="margin-top:12px"><label class="f">Quantity<input data-q type="number" min="0.001" step="any" value="1"></label><label class="f">Dimensions<input data-d value="${esc(p.size)}"></label><label class="f">Finish<input data-fi value="${esc(p.finish)}"></label><label class="f">Instructions<input data-i></label><button class="btn primary" data-add>Add</button></div></div>`;
    $("[data-add]", res).onclick = () => { const q = num($("[data-q]", res).value); if (!(q > 0)) return toast("Enter a quantity.", "warn"); lines.push({ product_id: p.id, catalogue_no: p.catalogue_no, factory_order_no: p.factory_order_no, name: p.name, qty: q, dimensions: $("[data-d]", res).value, finish: $("[data-fi]", res).value, instructions: $("[data-i]", res).value }); finder.clear(); drawL(); };
  });
  $("[data-pickc]", box).onclick = () => customerPicker($("[data-cbox]", box), (c) => { customer = c; $("[data-cbox]", box).innerHTML = `<div class="picked"><b>${esc(c.name)}</b><span>${esc(c.code)}</span></div>`; }, { allowCreate: false });
  drawL();
  $("[data-save]", box).onclick = async () => {
    if (!lines.length) return toast("Add at least one item.", "warn");
    try {
      const r = await api("/api/factory-orders", { method: "POST", body: { customer_id: customer ? customer.id : null, expected_date: $("[data-exp]", box).value || null, notes: $("[data-notes]", box).value, lines: lines.map((l) => ({ ...l, qty: String(l.qty) })) } });
      toast(`Created ${r.map((o) => o.number).join(", ")}.`); close(); onDone();
    } catch (e) { toast(e.message, "err"); }
  };
}

/* ------------------------------------------------------------------ products */
let CATS_CACHE = null;
async function categories(force) { if (!CATS_CACHE || force) CATS_CACHE = await api("/api/categories"); return CATS_CACHE; }
ROUTES.products = async (view, _a, qs) => {
  const f = { q: "", category_id: "", catalogue: "", low_stock: qs.get("low") === "1", active: "", page: 1 };
  const [cats, books] = await Promise.all([categories(true), api("/api/products/catalogues")]);
  view.innerHTML = `<div class="page-head"><div><h1>Products & numbers</h1><p class="muted">Each product has one catalogue number (customer's book) and one factory number.</p></div>
    <div class="row">${can("products.edit") ? `<button class="btn primary" data-new>Add product</button><button class="btn" data-cats>Categories</button>` : ""}<button class="btn" data-xlsx>Export Excel</button><button class="btn" data-csv>Export CSV</button></div></div>
    <div class="panel flush"><div class="panel-head"><div class="row" style="flex:1">
      <label class="f" style="flex:2 1 240px">Search<input data-f="q" placeholder="Design/catalogue no., factory no., name or brand"></label>
      <label class="f">Category<select data-f="category_id"><option value="">All</option>${cats.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></label>
      ${books.length > 1 ? `<label class="f">Catalogue book<select data-f="catalogue"><option value="">All</option>${books.map((b) => `<option>${esc(b)}</option>`).join("")}</select></label>` : ""}
      <label class="f">Show<select data-f="active"><option value="">All</option><option value="true">Active</option><option value="false">Switched off</option></select></label>
      <label class="check" style="padding-bottom:12px"><input type="checkbox" data-f="low_stock" ${f.low_stock ? "checked" : ""}> Low stock only</label></div></div><div data-list></div></div>`;
  const load = async () => {
    const d = await api("/api/products", { params: { ...f, size: 50 } });
    $("[data-list]", view).innerHTML = table([
      { label: "Numbers", html: (p) => tag(p.catalogue_no, p.factory_order_no) + (books.length > 1 ? `<br><span class="small muted">${esc(p.catalogue)}</span>` : "") },
      { label: "Product", html: (p) => `<b>${esc(p.name)}</b>${p.is_active ? "" : " " + chip("Off")}<br><span class="small muted">${esc([p.brand, p.category, p.size, p.finish].filter(Boolean).join(" · "))}</span>` },
      { label: "Price", num: true, html: (p) => rs(p.sale_price) + `<br><span class="small muted">per ${esc(p.unit)}</span>` },
      { label: "In stock", num: true, html: (p) => q3(p.stock_qty) + (num(p.reserved_qty) ? `<br><span class="small muted">${q3(p.reserved_qty)} reserved</span>` : "") },
      { label: "Free", num: true, html: (p) => p.low_stock ? chip(q3(p.available_qty), "warn") : q3(p.available_qty) }],
      d.items, { empty: "No products match. Try the exact catalogue number.", click: (p) => productModal(p.id, load) }) + pager(d, (p) => { f.page = p; load(); });
  };
  const reload = debounce(() => { f.page = 1; load().catch((e) => toast(e.message, "err")); });
  $$("[data-f]", view).forEach((i) => i.addEventListener(i.type === "checkbox" || i.tagName === "SELECT" ? "change" : "input", () => { f[i.dataset.f] = i.type === "checkbox" ? i.checked : i.value; reload(); }));
  const nb = $("[data-new]", view); if (nb) nb.onclick = () => productForm(null, load);
  const cb = $("[data-cats]", view); if (cb) cb.onclick = () => categoryManager(() => route());
  $("[data-xlsx]", view).onclick = () => download("/api/products-export", { fmt: "xlsx", q: f.q, category_id: f.category_id }, "products.xlsx");
  $("[data-csv]", view).onclick = () => download("/api/products-export", { fmt: "csv", q: f.q, category_id: f.category_id }, "products.csv");
  await load();
};
async function categoryManager(onChange) {
  const { box, close } = modal(`<h2>Categories</h2><p class="muted">Types of products, e.g. Laminates 1mm, Inner / Liner, Acrylic, Wooden Doors.</p>
    <div class="row" style="flex-wrap:nowrap"><input data-cn placeholder="New category name"><button class="btn primary" data-cadd>Add</button></div>
    <div data-clist style="margin-top:12px"></div><div class="modal-actions"><button class="btn" data-close>Done</button></div>`);
  let changed = false;
  const draw = async () => {
    const cats = await categories(true);
    $("[data-clist]", box).innerHTML = table([{ label: "Category", key: "name" }, { label: "Products", num: true, key: "products" },
      { label: "", html: (c) => `<button class="btn sm" data-ren="${c.id}">Rename</button>` }], cats, { empty: "No categories yet." });
    $$("[data-ren]", box).forEach((b) => b.onclick = async () => {
      const c = cats.find((x) => x.id === +b.dataset.ren);
      const name = await promptBox("Rename category", "Name", "Save", { min: 1, value: c.name });
      if (!name) return;
      try { await api(`/api/categories/${c.id}`, { method: "PUT", body: { name, is_active: true } }); changed = true; draw(); } catch (e) { toast(e.message, "err"); }
    });
  };
  const add = async () => {
    const name = $("[data-cn]", box).value.trim(); if (!name) return;
    try { await api("/api/categories", { method: "POST", body: { name, is_active: true } }); $("[data-cn]", box).value = ""; changed = true; toast(`Category "${name}" added.`); draw(); } catch (e) { toast(e.message, "err"); }
  };
  $("[data-cadd]", box).onclick = add;
  $("[data-cn]", box).onkeydown = (e) => { if (e.key === "Enter") add(); };
  $$("[data-close]", box).forEach((b) => b.addEventListener("click", () => { if (changed && onChange) onChange(); }));
  draw();
}
async function productModal(id, refresh) {
  const p = await api(`/api/products/${id}`);
  const { box, close } = modal(`<div class="row" style="justify-content:space-between;align-items:flex-start"><div><h2 style="margin-bottom:4px">${esc(p.name)}</h2><p class="muted">${esc([p.category, p.size, p.finish, p.catalogue + " book"].filter(Boolean).join(" · "))}</p></div>${tag(p.catalogue_no, p.factory_order_no, { lg: true })}</div>
    <div class="stats" style="margin:12px 0"><div class="stat"><div class="l">Price</div><div class="v">${rs(p.sale_price)}</div><div class="small muted">+${num(p.tax_rate)}% GST, per ${esc(p.unit)}</div></div>
    <div class="stat"><div class="l">In stock</div><div class="v">${q3(p.stock_qty)}</div></div><div class="stat"><div class="l">Reserved</div><div class="v">${q3(p.reserved_qty)}</div></div>
    <div class="stat"><div class="l">Damaged</div><div class="v">${q3(p.damaged_qty)}</div></div>${p.purchase_cost !== undefined ? `<div class="stat"><div class="l">Cost · supplier</div><div class="v">${rs(p.purchase_cost)}</div><div class="small muted">${esc(p.supplier)}</div></div>` : ""}</div>
    ${p.description ? `<p>${esc(p.description)}</p>` : ""}
    <h3>Number mapping history</h3>${table([{ label: "When", html: (h) => fdt(h.changed_at) }, { label: "Before", key: "old" }, { label: "After", key: "new" }, { label: "Reason", key: "reason" }], p.mapping_history, { empty: "Never changed." })}
    <h3 style="margin-top:16px">Recent stock movements</h3>${table([{ label: "When", html: (m) => fdt(m.at) }, { label: "Type", html: (m) => chip(m.kind.replace("_", " ")) }, { label: "Qty", num: true, html: (m) => q3(m.qty) }, { label: "Stock after", num: true, html: (m) => q3(m.stock_after) }, { label: "Note", key: "note" }], p.movements.slice(0, 15), { empty: "No movements." })}
    <div class="modal-actions">${can("stock.manage") ? `<button class="btn" data-stock>Record stock change</button>` : ""}${can("products.edit") ? `<button class="btn primary" data-edit>Edit product</button>` : ""}<button class="btn" data-close>Close</button></div>`, { wide: true });
  const e = $("[data-edit]", box); if (e) e.onclick = () => { close(); productForm(p, refresh); };
  const s = $("[data-stock]", box); if (s) s.onclick = () => { close(); stockForm(p, refresh); };
}
async function productForm(p, refresh) {
  const cats = await categories();
  const showCost = can("costs.view");
  const sups = showCost ? await api("/api/suppliers") : [];
  const { box, close } = modal(`<h2>${p ? "Edit product" : "Add product"}</h2><form class="stack">
    ${p ? `<div class="notice">Changing a number keeps old bills unchanged; the change is saved in history.</div>` : ""}
    <div class="grid2"><label class="f">Design / catalogue no.<input name="catalogue_no" required placeholder="e.g. 926-ZM" value="${esc(p?.catalogue_no)}"></label>
      <label class="f">Company order no.<input name="factory_order_no" required placeholder="number you give the company" value="${esc(p?.factory_order_no)}"></label></div>
    <label class="f">Product name<input name="name" required placeholder="e.g. Zebra Matt Laminate 1mm" value="${esc(p?.name)}"></label>
    <div class="grid2"><label class="f">Brand<input name="brand" list="brandList" placeholder="Luxe, Mocco, Inner…" value="${esc(p?.brand)}"></label><datalist id="brandList"></datalist>
      <label class="f">Category <a href="#" data-newcat class="small" style="font-weight:400">+ new category</a><select name="category_id"><option value="">None</option>${cats.map((c) => `<option value="${c.id}" ${p && p.category_id === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></label></div>
    <div class="grid3"><label class="f">Price per unit (₹)<input name="sale_price" type="number" step="0.01" min="0" required value="${p ? num(p.sale_price) : ""}"></label>
      <label class="f">Unit<select name="unit">${["sheet", "pcs", "sqft", "box", "kg", "ltr"].concat(p && !["sheet", "pcs", "sqft", "box", "kg", "ltr"].includes(p.unit) ? [p.unit] : []).map((u) => `<option ${(p ? p.unit : "sheet") === u ? "selected" : ""}>${u}</option>`).join("")}</select></label>
      <label class="f">GST %<input name="tax_rate" type="number" step="0.01" min="0" max="100" value="${p ? num(p.tax_rate) : 18}"></label></div>
    ${p ? "" : `<label class="f">Stock in hand now<input name="opening_stock" type="number" step="any" min="0" value="0"></label>`}
    <details><summary class="small" style="cursor:pointer;font-weight:700">More details (optional)</summary><div class="stack" style="margin-top:12px">
      <div class="grid3"><label class="f">HSN code<input name="hsn" value="${esc(p?.hsn)}"></label><label class="f">Size<input name="size" value="${esc(p?.size)}"></label><label class="f">Finish<input name="finish" value="${esc(p?.finish)}"></label></div>
      ${showCost ? `<div class="grid2"><label class="f">Purchase cost (₹)<input name="purchase_cost" type="number" step="0.01" min="0" value="${p ? num(p.purchase_cost) : 0}"></label>
        <label class="f">Company / supplier<select name="supplier_id">${sups.map((s) => `<option value="${s.id}" ${p && p.supplier_id === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label></div>` : ""}
      <div class="grid2"><label class="f">Low-stock alert at<input name="reorder_level" type="number" step="any" min="0" value="${p ? num(p.reorder_level) : 0}"></label>
        <label class="f">Catalogue book <span class="hint">only if you have more than one book</span><input name="catalogue" value="${esc(p ? p.catalogue : "MAIN")}"></label></div>
      ${p ? `<label class="f">Reason, if numbers change<input name="mapping_change_reason"></label>` : ""}
      <label class="f">Description<textarea name="description">${esc(p?.description)}</textarea></label>
      <label class="check"><input type="checkbox" name="is_active" ${!p || p.is_active ? "checked" : ""}> Active (can be billed)</label></div></details>
    <div class="modal-actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">${p ? "Save product" : "Add product"}</button></div></form>`, { wide: true });
  $("[data-newcat]", box).onclick = async (e) => {
    e.preventDefault();
    const name = await promptBox("New category", "Category name", "Add", { min: 1 });
    if (!name) return;
    try {
      const c = await api("/api/categories", { method: "POST", body: { name, is_active: true } });
      CATS_CACHE = null;
      const sel = $("[name=category_id]", box); sel.insertAdjacentHTML("beforeend", `<option value="${c.id}">${esc(c.name)}</option>`); sel.value = c.id;
      toast(`Category "${c.name}" added.`);
    } catch (err) { toast(err.message, "err"); }
  };
  api("/api/products", { params: { size: 500 } }).then((d) => { const dl = $("#brandList", box); if (dl) dl.innerHTML = [...new Set(d.items.map((x) => x.brand).filter(Boolean))].sort().map((b) => `<option>${esc(b)}</option>`).join(""); }).catch(() => {});
  $("form", box).onsubmit = async (e) => {
    e.preventDefault();
    const b = formData(box);
    b.category_id = b.category_id ? +b.category_id : null; b.supplier_id = b.supplier_id ? +b.supplier_id : null;
    if (!showCost) b.purchase_cost = p && p.purchase_cost !== undefined ? p.purchase_cost : "0";
    if (p && (b.catalogue_no.toUpperCase() !== p.catalogue_no || b.factory_order_no.toUpperCase() !== p.factory_order_no)) {
      if (!(await confirmBox("Change product numbers?", `Catalogue ${esc(p.catalogue_no)} → factory ${esc(p.factory_order_no)} becomes catalogue <b>${esc(b.catalogue_no)}</b> → factory <b>${esc(b.factory_order_no)}</b>. Old bills keep the old numbers.`, "Change numbers"))) return;
    }
    try {
      const r = await api(p ? `/api/products/${p.id}` : "/api/products", { method: p ? "PUT" : "POST", body: b });
      toast(p ? "Product saved." : `Added ${r.catalogue_no} → ${r.factory_order_no}.`); close(); refresh && refresh();
    } catch (err) { toast(err.message, "err"); }
  };
}

/* ------------------------------------------------------------------ import */
ROUTES.import = async (view, id) => {
  if (id) return importPreview(view, id);
  const hist = await api("/api/imports");
  view.innerHTML = `<div class="page-head"><div><h1>Import inventory from Excel</h1><p class="muted">Upload an .xlsx or .csv. Nothing is saved until you check the preview and press Import.</p></div>
    <button class="btn" data-tpl>Download template</button></div>
    <div class="grid2"><form class="panel stack"><h2>Upload file</h2>
      <label class="f">File<input type="file" name="file" accept=".xlsx,.xlsm,.csv" required></label>
      <label class="f">What should happen<select name="mode"><option value="create">Add new products only (stop if a catalogue number exists)</option><option value="upsert">Add new and update existing products</option></select></label>
      <button class="btn primary xl">Check file</button></form>
    <div class="panel"><h2>Columns</h2><p class="small">Required: <b>catalogue_no</b>, <b>factory_order_no</b>, <b>name</b>. Optional: brand, hsn, catalogue, category, description, size, finish, unit, sale_price, purchase_cost, tax_rate, quantity, reorder_level, supplier.</p>
      <p class="small muted">Common headings like "Customer Catalogue Number", "Factory Order Number", "Product Name", "Price", "Qty" are recognised automatically. Numbers are matched exactly; 0123 and 123 are different.</p></div></div>
    <div class="panel flush" style="margin-top:16px"><div class="panel-head"><h3>Previous imports</h3></div>${table([{ label: "File", key: "filename" }, { label: "When", html: (b) => fdt(b.created_at) },
      { label: "Status", html: (b) => chip(statusWords(b.status), b.status === "COMMITTED" ? "ok" : b.status === "PREVIEW" ? "warn" : "") },
      { label: "Rows", html: (b) => b.summary ? (b.status === "COMMITTED" ? `${b.summary.created ?? 0} new · ${b.summary.updated ?? 0} updated` : `${b.summary.total} rows · ${b.summary.errors} errors`) : "" }],
      hist, { empty: "No imports yet.", click: (b) => b.status === "PREVIEW" && (location.hash = `#/import/${b.id}`) })}</div>`;
  $("[data-tpl]", view).onclick = () => download("/api/imports/template", null, "template.xlsx");
  $("form", view).onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("form button", view); busy(btn, true, "Checking every row…");
    const fd = new FormData(e.target);
    try { const b = await api("/api/imports", { method: "POST", form: fd }); location.hash = `#/import/${b.id}`; }
    catch (err) { toast(err.message, "err"); busy(btn, false); }
  };
};
async function importPreview(view, id) {
  const st = { page: 1 };
  const load = async () => {
    const b = await api(`/api/imports/${id}`, { params: { only_errors: true, page: st.page, size: 50 } });
    const s = b.summary;
    if (b.status !== "PREVIEW") { view.innerHTML = `<div class="panel"><div class="notice">This import is ${statusWords(b.status).toLowerCase()}.</div><a class="btn" href="#/import" style="margin-top:12px">Back</a></div>`; return; }
    const editable = ["catalogue", "catalogue_no", "factory_order_no", "name", "category", "sale_price", "quantity", "supplier"];
    view.innerHTML = `<div class="page-head"><div><h1>Check import: ${esc(b.filename)}</h1><p class="muted">${b.mode === "upsert" ? "Add new and update existing" : "Add new only"}</p></div></div>
      <div class="stats" style="margin-bottom:16px"><div class="stat"><div class="l">Rows in file</div><div class="v">${s.total.toLocaleString("en-IN")}</div></div>
      <div class="stat key"><div class="l">New products</div><div class="v">${s.create.toLocaleString("en-IN")}</div></div><div class="stat key"><div class="l">Updates</div><div class="v">${s.update.toLocaleString("en-IN")}</div></div>
      <div class="stat ${s.errors ? "alert" : ""}"><div class="l">Rows with errors</div><div class="v">${s.errors}</div></div><div class="stat"><div class="l">Rows with warnings</div><div class="v">${s.warnings}</div></div></div>
      ${s.ignored_columns && s.ignored_columns.length ? `<div class="notice" style="margin-bottom:16px">Ignored columns: ${esc(s.ignored_columns.join(", "))}</div>` : ""}
      <div class="panel flush"><div class="panel-head"><h3>${b.rows_total ? "Fix these rows, or remove them" : "All rows are valid"}</h3>
        <div class="row"><button class="btn danger" data-discard>Discard</button>${s.errors ? `<button class="btn" data-skip>Import valid rows, skip ${s.errors} with errors</button>` : ""}
        <button class="btn primary" data-commit ${s.errors ? "disabled" : ""}>Import ${(s.create + s.update).toLocaleString("en-IN")} rows</button></div></div>
        ${b.rows_total ? `<div class="table-wrap"><table><thead><tr><th>Row</th><th>Problem</th>${editable.map((f) => `<th>${esc(f.replace(/_/g, " "))}</th>`).join("")}<th></th></tr></thead><tbody>
        ${b.rows.map((r) => `<tr data-row="${r.row}"><td>${r.row}</td><td style="min-width:260px">${r.errors.map((e) => `<div class="small" style="color:var(--red)">${esc(e)}</div>`).join("")}${r.warnings.map((w) => `<div class="small" style="color:#7A4F10">${esc(w)}</div>`).join("")}</td>
          ${editable.map((f) => `<td><input data-k="${f}" value="${esc(r.data[f])}" style="min-width:${f === "name" ? 180 : 90}px"></td>`).join("")}
          <td class="nowrap"><button class="btn sm primary" data-fix>Save fix</button> <button class="btn sm danger" data-rm>Remove</button></td></tr>`).join("")}</tbody></table></div>${pager({ total: b.rows_total, page: b.page, pages: Math.ceil(b.rows_total / b.size) }, (p) => { st.page = p; load(); })}` : ""}</div>`;
    $$("tr[data-row]", view).forEach((tr) => {
      const rowNo = +tr.dataset.row, orig = b.rows.find((r) => r.row === rowNo);
      $("[data-fix]", tr).onclick = async () => {
        const data = { ...orig.data }; $$("[data-k]", tr).forEach((i) => data[i.dataset.k] = i.value);
        try { const r = await api(`/api/imports/${id}/rows/${rowNo}`, { method: "PUT", body: { data } }); toast(r.row && r.row.errors.length ? "Still has problems: " + r.row.errors[0] : `Row ${rowNo} fixed.`, r.row && r.row.errors.length ? "warn" : "ok"); load(); } catch (e) { toast(e.message, "err"); }
      };
      $("[data-rm]", tr).onclick = async () => { try { await api(`/api/imports/${id}/rows/${rowNo}`, { method: "PUT", body: { data: {}, remove: true } }); toast(`Row ${rowNo} removed from this import.`); load(); } catch (e) { toast(e.message, "err"); } };
    });
    const commit = async (skip) => {
      if (!(await confirmBox("Import now?", `${(s.create + s.update).toLocaleString("en-IN")} rows will be saved${skip ? `, ${s.errors} rows with errors skipped` : ""}.`, "Import"))) return;
      const btn = $(skip ? "[data-skip]" : "[data-commit]", view); busy(btn, true, "Importing…");
      try { const r = await api(`/api/imports/${id}/commit`, { method: "POST", body: { skip_errors: !!skip } }); toast(r.message); location.hash = "#/products"; } catch (e) { toast(e.message, "err"); busy(btn, false); }
    };
    $("[data-commit]", view).onclick = () => commit(false);
    const sk = $("[data-skip]", view); if (sk) sk.onclick = () => commit(true);
    $("[data-discard]", view).onclick = async () => { if (await confirmBox("Discard this import?", "Nothing from this file will be saved.", "Discard", true)) { await api(`/api/imports/${id}/discard`, { method: "POST" }); location.hash = "#/import"; } };
  };
  await load();
}

/* ------------------------------------------------------------------ stock */
function stockForm(p, refresh) {
  const { box, close } = modal(`<h2>Record stock change</h2><p>${tag(p.catalogue_no, p.factory_order_no)} <b>${esc(p.name)}</b><br><span class="muted small">In stock ${q3(p.stock_qty)} · reserved ${q3(p.reserved_qty)} · damaged ${q3(p.damaged_qty)}</span></p>
    <form class="stack"><label class="f">What happened<select name="kind"><option value="IN">Stock received (add)</option><option value="RETURN">Customer returned goods (add)</option>
    <option value="DAMAGE">Found damaged (move to damaged)</option><option value="WRITE_OFF">Throw away damaged stock</option><option value="ADJUST">Correction after counting (+ or −)</option></select></label>
    <label class="f">Quantity <span class="hint">for corrections, use a minus sign to reduce</span><input name="qty" type="number" step="any" required></label>
    <label class="f">Note<input name="note" required placeholder="e.g. Physical count 12 Oct"></label>
    <div class="modal-actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">Save</button></div></form>`);
  $("form", box).onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/stock/movements", { method: "POST", body: { ...formData(box), product_id: p.id } }); toast("Stock updated."); close(); refresh && refresh(); } catch (err) { toast(err.message, "err"); }
  };
}
ROUTES.stock = async (view) => {
  const f = { kind: "", date_from: "", date_to: "", page: 1 };
  const s = await api("/api/stock/summary");
  view.innerHTML = `<div class="page-head"><h1>Stock movements</h1></div>
    <div class="stats" style="margin-bottom:16px"><div class="stat"><div class="l">Active products</div><div class="v">${s.products.toLocaleString("en-IN")}</div></div><div class="stat"><div class="l">Units in stock</div><div class="v">${num(s.stock).toLocaleString("en-IN")}</div></div>
    <div class="stat"><div class="l">Reserved for orders</div><div class="v">${num(s.reserved).toLocaleString("en-IN")}</div></div><div class="stat"><div class="l">Damaged</div><div class="v">${num(s.damaged).toLocaleString("en-IN")}</div></div>
    <a class="stat ${s.low_stock ? "alert" : ""}" href="#/products?low=1" style="text-decoration:none;color:inherit"><div class="l">Low stock</div><div class="v">${s.low_stock}</div></a></div>
    <div class="panel" style="margin-bottom:16px"><h2>Record a change</h2><div data-f></div></div>
    <div class="panel flush"><div class="panel-head"><div class="row" style="flex:1"><label class="f">Type<select data-k="kind"><option value="">All</option>${["IN", "OUT", "RETURN", "DAMAGE", "WRITE_OFF", "ADJUST", "RESERVE", "UNRESERVE", "OUT_RESERVED"].map((k) => `<option value="${k}">${k.replace("_", " ")}</option>`).join("")}</select></label>
    <label class="f">From<input type="date" data-k="date_from"></label><label class="f">To<input type="date" data-k="date_to"></label></div></div><div data-list></div></div>`;
  const load = async () => {
    const d = await api("/api/stock/movements", { params: { ...f, size: 50 } });
    $("[data-list]", view).innerHTML = table([{ label: "When", html: (m) => fdt(m.at) }, { label: "Product", html: (m) => `${tag(m.catalogue_no)} ${esc(m.product_name)}` }, { label: "Type", html: (m) => chip(m.kind.replace("_", " ")) },
      { label: "Qty", num: true, html: (m) => q3(m.qty) }, { label: "Stock after", num: true, html: (m) => q3(m.stock_after) }, { label: "Note", key: "note" }], d.items, { empty: "No movements." }) + pager(d, (p) => { f.page = p; load(); });
  };
  productFinder($("[data-f]", view), (p, res) => { res.innerHTML = ""; stockForm(p, () => route()); }, { label: "Catalogue number" });
  $$("[data-k]", view).forEach((i) => i.onchange = () => { f[i.dataset.k] = i.value; f.page = 1; load(); });
  await load();
};

/* ------------------------------------------------------------------ reports */
ROUTES.reports = async (view, _a, qs) => {
  const f = { tab: qs.get("tab") || "monthly", month: today().slice(0, 7), group: "date", date_from: monthStart(), date_to: today(), category_id: "" };
  const cats = await categories();
  view.innerHTML = `<div class="page-head"><h1>Reports</h1></div><div class="panel flush"><div class="tabs">${[["monthly", "Monthly"], ["sales", "Sales"], ["outstanding", "Pending payments"], ["payments", "Payments received"], ["stock", "Low stock"]].map(([k, l]) => `<button data-tab="${k}">${l}</button>`).join("")}</div>
    <div class="panel-head"><div class="row" style="flex:1" data-filters></div><button class="btn" data-csv>Download CSV</button></div><div data-body></div></div>`;
  const filters = () => {
    const fx = $("[data-filters]", view);
    const dates = `<label class="f">From<input type="date" data-k="date_from" value="${f.date_from}"></label><label class="f">To<input type="date" data-k="date_to" value="${f.date_to}"></label>`;
    if (f.tab === "monthly") fx.innerHTML = `<label class="f">Month<input type="month" data-k="month" value="${f.month}"></label>${S.user.role === "owner" ? `<button class="btn" data-target style="align-self:flex-end">Set sales target</button>` : ""}`;
    else if (f.tab === "sales") fx.innerHTML = `<label class="f">Group by<select data-k="group">${[["date", "Day"], ["month", "Month"], ["customer", "Customer"], ["product", "Product"], ["category", "Category"]].map(([v, l]) => `<option value="${v}" ${f.group === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>${dates}
      <label class="f">Category<select data-k="category_id"><option value="">All</option>${cats.map((c) => `<option value="${c.id}" ${String(f.category_id) === String(c.id) ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></label>`;
    else if (f.tab === "payments") fx.innerHTML = dates;
    else if (f.tab === "stock") fx.innerHTML = `<label class="f">Category<select data-k="category_id"><option value="">All</option>${cats.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></label>`;
    else fx.innerHTML = `<span class="muted">All customers with a balance due, highest first.</span>`;
    $$("[data-k]", fx).forEach((i) => i.onchange = () => { f[i.dataset.k] = i.value; load(); });
    const tb = $("[data-target]", fx);
    if (tb) tb.onclick = async () => {
      const cur = await api("/api/settings/shop");
      const v = await promptBox("Monthly sales target", "Target amount in ₹ (same for every month)", "Save target", { min: 1, value: num(cur.monthly_target) || "" });
      if (v === null) return;
      if (!(num(v) >= 0)) return toast("Enter a number.", "warn");
      try { await api("/api/settings/shop", { method: "PUT", body: { monthly_target: String(num(v)) } }); toast("Target saved."); load(); } catch (e) { toast(e.message, "err"); }
    };
  };
  const params = () => f.tab === "monthly" ? { month: f.month } : f.tab === "sales" ? { group: f.group, date_from: f.date_from, date_to: f.date_to, category_id: f.category_id } : f.tab === "payments" ? { date_from: f.date_from, date_to: f.date_to } : f.tab === "stock" ? { category_id: f.category_id, low_only: true } : {};
  const load = async () => {
    $$("[data-tab]", view).forEach((b) => b.classList.toggle("on", b.dataset.tab === f.tab));
    const body = $("[data-body]", view);
    const d = await api(`/api/reports/${f.tab}`, { params: params() });
    if (f.tab === "monthly") {
      const s = d.summary, pct = Math.min(100, num(s.achieved_pct));
      body.innerHTML = `<div style="padding:16px 20px" class="stack">
        <div class="stats c3">
          <div class="stat key"><div class="l">Sales target</div><div class="v">${rs(s.sales_target)}</div><div class="small muted">${num(s.sales_target) ? num(s.achieved_pct).toFixed(1) + "% achieved" : "Owner can set a target"}</div>
            ${num(s.sales_target) ? `<div style="height:8px;background:#E1E5DF;border-radius:4px;margin-top:6px"><div style="height:8px;width:${pct}%;background:var(--green);border-radius:4px"></div></div>` : ""}</div>
          <div class="stat key"><div class="l">Total net sales</div><div class="v">${rs(s.net)}</div><div class="small muted">${s.bills} bills</div></div>
          <div class="stat"><div class="l">Total gross sales</div><div class="v">${rs(s.gross)}</div></div>
          <div class="stat"><div class="l">Total GST</div><div class="v">${rs(s.gst)}</div></div>
          <div class="stat"><div class="l">Total quantity (sheets)</div><div class="v">${q3(s.qty)}</div><div class="small muted">Avg ${rs(s.avg_rate)} / sheet</div></div>
          <div class="stat"><div class="l">Cash · Bill sales</div><div class="v" style="font-size:1.1rem">${rs(s.cash_sales)} · ${rs(s.bill_sales)}</div></div>
          <div class="stat key"><div class="l">Paid sales</div><div class="v">${rs(s.paid)}</div></div>
          <div class="stat ${num(s.pending) > 0 ? "alert" : ""}"><div class="l">Pending payments</div><div class="v">${rs(s.pending)}</div></div></div>
        <h3 style="margin-top:8px">Area wise</h3></div>
        ${table([{ label: "Area", key: "area" }, { label: "Customers", num: true, key: "customers" }, { label: "Bills", num: true, key: "bills" }, { label: "Qty", num: true, key: "qty" },
          { label: "Gross", num: true, html: (a) => rs(a.gross) }, { label: "GST", num: true, html: (a) => rs(a.gst) }, { label: "Net", num: true, html: (a) => `<b>${rs(a.net)}</b>` },
          { label: "Paid", num: true, html: (a) => rs(a.paid) }, { label: "Pending", num: true, html: (a) => rs(a.pending) }], d.areas, { empty: "No sales this month." })}
        <div class="panel-head" style="border-top:1px solid var(--line)"><h3>Monthly sales tracker</h3></div>
        ${table([{ label: "Date", html: (r) => `<span class="nowrap">${esc(r.date)}</span>` }, { label: "Customer", html: (r) => `<b>${esc(r.customer)}</b><br><span class="small muted">${esc(r.area)}</span>` },
          { label: "Category", html: (r) => r.category === "Cash" ? chip("Cash", "warn") : chip("Bill", "ok") }, { label: "Brand", key: "brand" }, { label: "Design / Code", key: "design" },
          { label: "Qty", num: true, key: "qty" }, { label: "Rate", num: true, html: (r) => rs(r.rate) }, { label: "Gross", num: true, html: (r) => rs(r.gross) },
          { label: "GST", num: true, html: (r) => rs(r.gst) }, { label: "Net", num: true, html: (r) => `<b>${rs(r.net)}</b>` },
          { label: "Payment", html: (r) => chip(r.payment, r.payment === "Paid" ? "ok" : r.payment === "Pending" ? "bad" : "warn") }], d.rows, { empty: "No sales this month." })}`;
    } else if (f.tab === "sales") {
      const cost = d.rows.length && d.rows[0].cost !== undefined;
      const sum = (k) => d.rows.reduce((a, r) => a + num(r[k]), 0);
      body.innerHTML = table([{ label: { date: "Day", month: "Month", customer: "Customer", product: "Product", category: "Category" }[f.group], key: "group" }, { label: "Bills", num: true, key: "bills" }, { label: "Qty", num: true, key: "qty" },
        { label: "Before GST", num: true, html: (r) => rs(r.taxable) }, { label: "GST", num: true, html: (r) => rs(r.tax) }, { label: "Total", num: true, html: (r) => rs(r.total) },
        ...(cost ? [{ label: "Cost", num: true, html: (r) => rs(r.cost) }, { label: "Gross profit", num: true, html: (r) => rs(r.gross_profit) }] : [])], d.rows,
        { empty: "No sales in this period.", foot: d.rows.length ? `<tr><td>Total</td><td></td><td></td><td class="num">${rs(sum("taxable"))}</td><td class="num">${rs(sum("tax"))}</td><td class="num">${rs(sum("total"))}</td>${cost ? `<td class="num">${rs(sum("cost"))}</td><td class="num">${rs(sum("gross_profit"))}</td>` : ""}</tr>` : "" });
    } else if (f.tab === "outstanding") {
      body.innerHTML = table([{ label: "Customer", html: (r) => `<b>${esc(r.name)}</b><br><span class="small muted">${esc(r.code)} · ${esc(r.phone)}</span>` }, { label: "Billed", num: true, html: (r) => rs(r.billed) }, { label: "Paid", num: true, html: (r) => rs(r.paid) }, { label: "Credit notes", num: true, html: (r) => rs(r.credited) }, { label: "Owes", num: true, html: (r) => `<b>${rs(r.outstanding)}</b>` }],
        d.rows, { empty: "Nobody owes money.", click: (r) => location.hash = `#/customer/${r.customer_id}`, foot: `<tr><td>Total</td><td></td><td></td><td></td><td class="num">${rs(d.total)}</td></tr>` });
    } else if (f.tab === "payments") {
      body.innerHTML = table([{ label: "Date", html: (r) => fdate(r.date) }, { label: "Method", key: "method" }, { label: "Type", html: (r) => r.kind === "REFUND" ? chip("Refund", "warn") : "Payment" }, { label: "Count", num: true, key: "count" }, { label: "Amount", num: true, html: (r) => rs(r.amount) }], d.rows, { empty: "No payments in this period." });
    } else {
      body.innerHTML = table([{ label: "Numbers", html: (p) => tag(p.catalogue_no, p.factory_order_no) }, { label: "Product", key: "name" }, { label: "Category", key: "category" }, { label: "Free", num: true, html: (p) => q3(p.available_qty) }, { label: "Reorder at", num: true, html: (p) => q3(p.reorder_level) }], d.rows, { empty: "No products are low." });
    }
  };
  $$("[data-tab]", view).forEach((b) => b.onclick = () => { f.tab = b.dataset.tab; $("[data-csv]", view).textContent = f.tab === "monthly" ? "Download Excel" : "Download CSV"; filters(); load(); });
  $("[data-csv]", view).onclick = () => f.tab === "monthly" ? download("/api/reports/monthly.xlsx", { month: f.month }, `Luxe_Monthly_${f.month}.xlsx`) : download(`/api/reports/${f.tab}`, { ...params(), format: "csv" }, `${f.tab}.csv`);
  $("[data-csv]", view).textContent = f.tab === "monthly" ? "Download Excel" : "Download CSV";
  filters(); await load();
};

/* ------------------------------------------------------------------ users */
ROUTES.users = async (view) => {
  const users = await api("/api/users");
  view.innerHTML = `<div class="page-head"><div><h1>Logins & permissions</h1><p class="muted">Staff see only what you allow. Customers see only their own account.</p></div><button class="btn primary" data-new>Add login</button></div>
    <div class="panel flush">${table([{ label: "User", html: (u) => `<b>${esc(u.full_name || u.username)}</b><br><span class="small muted">${esc(u.username)}</span>` }, { label: "Role", html: (u) => chip(u.role === "owner" ? "Owner" : u.role === "staff" ? "Staff" : "Customer", u.role === "owner" ? "ok" : "") },
      { label: "Access", html: (u) => u.role === "staff" ? `<span class="small">${u.permissions.map((p) => esc(S.allPerms[p] || p)).join(", ") || "Nothing yet"}</span>` : u.role === "owner" ? "Everything" : "Own account only" },
      { label: "Status", html: (u) => u.is_active ? chip("Active", "ok") : chip("Off", "bad") }], users, { click: (u) => userForm(u) })}</div>`;
  $("[data-new]", view).onclick = () => userForm(null);
};
function userForm(u, preset) {
  const isNew = !u;
  const role0 = u ? u.role : (preset && preset.role) || "staff";
  let linked = preset && preset.customer ? preset.customer : null;
  const { box, close } = modal(`<h2>${isNew ? "Add login" : "Edit " + esc(u.username)}</h2><form class="stack">
    ${isNew ? `<div class="grid2"><label class="f">Username<input name="username" required pattern="[A-Za-z0-9_.@-]{3,60}" value="${linked ? esc(linked.phone || "") : ""}"></label><label class="f">Full name<input name="full_name" value="${linked ? esc(linked.name) : ""}"></label></div>
      <div class="grid2"><label class="f">Password<input name="password" type="text" required minlength="6"></label><label class="f">Role<select name="role"><option value="staff">Staff</option><option value="customer">Customer</option><option value="owner">Owner (full access)</option></select></label></div>`
      : `<label class="f">Full name<input name="full_name" value="${esc(u.full_name)}"></label><label class="f">New password <span class="hint">leave empty to keep</span><input name="new_password" type="text" minlength="6"></label>
      <label class="check"><input type="checkbox" name="is_active" ${u.is_active ? "checked" : ""}> Login is active</label>`}
    <div data-perms></div><div data-cust></div>
    <div class="modal-actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">${isNew ? "Create login" : "Save"}</button></div></form>`, { wide: true });
  const roleSel = $("[name=role]", box);
  if (roleSel) roleSel.value = role0;
  const drawRole = () => {
    const role = roleSel ? roleSel.value : u.role;
    $("[data-perms]", box).innerHTML = role === "staff" ? `<h3>What this staff member can do</h3><div class="grid2">${Object.entries(S.allPerms).map(([k, l]) => `<label class="check"><input type="checkbox" data-p="${k}" ${u && u.permissions.includes(k) ? "checked" : ""}> ${esc(l)}</label>`).join("")}</div>` : "";
    const cb = $("[data-cust]", box);
    if (role === "customer" && isNew) {
      if (linked) cb.innerHTML = `<div class="picked"><span>Linked to <b>${esc(linked.name)}</b> (${esc(linked.code)})</span></div>`;
      else customerPicker(cb, (c) => { linked = c; drawRole(); }, { allowCreate: false });
    } else cb.innerHTML = "";
  };
  if (roleSel) roleSel.onchange = drawRole;
  drawRole();
  $("form", box).onsubmit = async (e) => {
    e.preventDefault();
    const b = formData($("form", box));
    const perms = $$("[data-p]", box).filter((i) => i.checked).map((i) => i.dataset.p);
    try {
      if (isNew) {
        if (b.role === "customer" && !linked) return toast("Pick the customer for this login.", "warn");
        await api("/api/users", { method: "POST", body: { username: b.username, full_name: b.full_name, password: b.password, role: b.role, permissions: perms, customer_id: linked ? linked.id : null } });
        toast(`Login ${b.username} created. Share the password safely.`);
      } else {
        await api(`/api/users/${u.id}`, { method: "PATCH", body: { full_name: b.full_name, is_active: b.is_active, new_password: b.new_password || null, permissions: u.role === "staff" ? perms : null } });
        toast("Login saved.");
      }
      close(); if (location.hash.startsWith("#/users")) route();
    } catch (err) { toast(err.message, "err"); }
  };
}

/* ------------------------------------------------------------------ settings */
ROUTES.settings = async (view) => {
  const owner = S.user.role === "owner";
  view.innerHTML = `<div class="page-head"><h1>Settings & backup</h1></div><div class="stack">
    ${can("costs.view") ? `<div class="panel flush"><div class="panel-head"><h3>Companies (factories)</h3><button class="btn sm" data-nsup>Add company</button></div><div data-sups></div></div>` : ""}
    ${owner ? `<div class="panel flush"><div class="panel-head"><h3>Backups</h3><button class="btn primary sm" data-bk>Back up now</button></div><div data-bks></div></div>
    <div class="panel flush"><div class="panel-head"><h3>Activity log</h3><input data-aq placeholder="Filter by action, e.g. payment" style="max-width:280px"></div><div data-audit></div></div>` : ""}
    <div class="panel"><h3>Your password</h3><a class="btn" href="#/password">Change password</a></div></div>`;
  const loadCats = async () => { const c = await categories(true); $("[data-cats]", view).innerHTML = table([{ label: "Name", key: "name" }, { label: "Products", num: true, key: "products" }, { label: "Status", html: (x) => x.is_active ? chip("Active", "ok") : chip("Off") }], c, { click: (x) => catForm(x) }); };
  const catForm = async (x) => { const name = await promptBox(x ? "Rename category" : "New category", "Name", "Save", { min: 1, value: x ? x.name : "" }); if (!name) return; try { await api(x ? `/api/categories/${x.id}` : "/api/categories", { method: x ? "PUT" : "POST", body: { name, is_active: true } }); loadCats(); } catch (e) { toast(e.message, "err"); } };
  const loadSups = async () => { const s = await api("/api/suppliers"); $("[data-sups]", view).innerHTML = table([{ label: "Name", key: "name" }, { label: "Phone", key: "phone" }, { label: "Email", key: "email" }], s, { click: supForm }); };
  const supForm = (s) => {
    const { box, close } = modal(`<h2>${s ? "Edit supplier" : "New supplier"}</h2><form class="stack"><label class="f">Name<input name="name" required value="${esc(s?.name)}"></label><div class="grid2"><label class="f">Phone<input name="phone" value="${esc(s?.phone)}"></label><label class="f">Email<input name="email" value="${esc(s?.email)}"></label></div>
      <label class="f">Address<textarea name="address">${esc(s?.address)}</textarea></label><label class="f">Notes<textarea name="notes">${esc(s?.notes)}</textarea></label><div class="modal-actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">Save</button></div></form>`);
    $("form", box).onsubmit = async (e) => { e.preventDefault(); try { await api(s ? `/api/suppliers/${s.id}` : "/api/suppliers", { method: s ? "PUT" : "POST", body: formData(box) }); close(); loadSups(); } catch (err) { toast(err.message, "err"); } };
  };
  const loadBk = async () => { const b = await api("/api/admin/backups"); $("[data-bks]", view).innerHTML = `<p class="small muted" style="padding:12px 20px 0">${esc(b.database)} · saved in ${esc(b.folder)}. Schedule daily backups as shown in the README.</p>` + table([{ label: "File", key: "name" }, { label: "Size", html: (f) => f.size_mb + " MB" }, { label: "Made", html: (f) => fdt(f.created) }, { label: "", html: (f) => `<button class="btn sm" data-dl="${esc(f.name)}">Download</button>` }], b.files, { empty: "No backups yet." }); $$("[data-dl]", view).forEach((x) => x.onclick = () => download(`/api/admin/backups/${encodeURIComponent(x.dataset.dl)}`, null, x.dataset.dl)); };
  const loadAudit = async (q = "") => { const a = await api("/api/admin/audit", { params: { action: q, size: 40 } }); $("[data-audit]", view).innerHTML = table([{ label: "When", html: (r) => fdt(r.at) }, { label: "Who", key: "user" }, { label: "Action", html: (r) => esc(statusWords(r.action)) }, { label: "Details", html: (r) => `<span class="small">${esc(Object.entries(r.details || {}).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · "))}</span>` }], a.items); };
  if (can("costs.view")) { $("[data-nsup]", view).onclick = () => supForm(null); await loadSups(); }
  if (owner) {
    $("[data-bk]", view).onclick = async (e) => { busy(e.target, true, "Backing up…"); try { const r = await api("/api/admin/backups", { method: "POST" }); toast(r.message); loadBk(); } catch (err) { toast(err.message, "err"); } busy(e.target, false); };
    $("[data-aq]", view).oninput = debounce((e) => loadAudit(e.target.value));
    await Promise.all([loadBk(), loadAudit()]);
  }
};
ROUTES.password = async (view) => {
  view.innerHTML = `<div class="page-head"><h1>Change password</h1></div><form class="panel stack" style="max-width:480px"><label class="f">Current password<input type="password" name="current_password" required autocomplete="current-password"></label>
    <label class="f">New password <span class="hint">at least 6 characters</span><input type="password" name="new_password" required minlength="6" autocomplete="new-password"></label><button class="btn primary">Change password</button></form>`;
  $("form", view).onsubmit = async (e) => { e.preventDefault(); try { const r = await api("/api/auth/change-password", { method: "POST", body: formData(view) }); S.token = r.token; localStorage.setItem("luxe_token", r.token); toast("Password changed. Other devices are logged out."); e.target.reset(); } catch (err) { toast(err.message, "err"); } };
};

/* ------------------------------------------------------------------ customer portal */
ROUTES.me = async (view) => {
  const a = await api("/api/me/account");
  const t = a.totals;
  view.innerHTML = `<div class="page-head"><div><h1>${esc(a.customer.name)}</h1><p class="muted">Customer ID ${esc(a.customer.code)}</p></div><div class="row"><button class="btn primary" data-stmt>Download statement</button><button class="btn" data-xls>Download Excel</button></div></div>
    <div class="stats" style="margin-bottom:16px"><div class="stat"><div class="l">Total billed</div><div class="v">${rs(t.billed)}</div></div><div class="stat"><div class="l">You have paid</div><div class="v">${rs(t.paid)}</div></div>
    <div class="stat ${num(t.outstanding) > 0 ? "alert" : "key"}"><div class="l">${num(t.outstanding) >= 0 ? "Balance to pay" : "Advance with us"}</div><div class="v">${rs(Math.abs(num(t.outstanding)))}</div></div></div>
    ${typeBreakdown(a.invoices)}
    <div class="stack"><div class="panel flush"><div class="panel-head"><h3>Your bills</h3></div>${table([{ label: "Bill", html: (i) => `<b>${esc(i.number)}</b><br><span class="small muted">${fdate(i.invoice_date)}</span>` }, { label: "Type", html: (i) => srcChip(i.source) },
      { label: "Items", html: (i) => i.lines.map((l) => `${tag(l.catalogue_no)} ${esc(l.product_name)} × ${q3(l.qty)}`).join("<br>") }, { label: "Total", num: true, html: (i) => rs(i.total) }, { label: "Due", num: true, html: (i) => rs(i.due) },
      { label: "Status", html: (i) => payChip(i.payment_status) }, { label: "", html: (i) => `<span class="nowrap"><button class="btn sm" data-pdf="${i.id}">Open</button> <button class="btn sm" data-mdl="${i.id}">Download</button></span>` }], a.invoices, { empty: "No bills yet." })}</div>
    <div class="grid2"><div class="panel flush"><div class="panel-head"><h3>Your payments</h3></div>${table([{ label: "Date", html: (p) => fdate(p.paid_on) }, { label: "Method", html: (p) => methodChip(p.method) }, { label: "Bill", html: (p) => esc(p.invoice_number || "Advance") }, { label: "Amount", num: true, html: (p) => (p.kind === "REFUND" ? "Refund " : "") + rs(p.amount) }], a.payments, { empty: "No payments yet." })}</div>
    <div class="panel flush"><div class="panel-head"><h3>Your orders</h3></div>${table([{ label: "Order", html: (o) => `<b>${esc(o.number)}</b><br><span class="small muted">${fdate(o.created_at)}</span>` }, { label: "Items", html: (o) => o.lines.map((l) => `${tag(l.catalogue_no)} × ${q3(l.qty)}`).join("<br>") }, { label: "Status", html: (o) => foChip(o.status) }], a.orders, { empty: "No orders being made." })}</div></div></div>`;
  $$("[data-pdf]", view).forEach((b) => b.onclick = () => openPdf(`/api/me/invoices/${b.dataset.pdf}/pdf`));
  $$("[data-mdl]", view).forEach((b) => b.onclick = () => { const i = a.invoices.find((x) => x.id === +b.dataset.mdl); download(`/api/me/invoices/${i.id}/pdf`, null, `${i.number}.pdf`); });
  $("[data-stmt]", view).onclick = () => openPdf("/api/me/statement.pdf");
  $("[data-xls]", view).onclick = () => download("/api/me/export.xlsx", null, "my_account.xlsx");
};

boot();
