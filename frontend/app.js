// DocuMind frontend: auth, multi-PDF workspace, find/replace editor, persistent chats. Plain ES module.
const $ = (s) => document.querySelector(s);
const h = (t, a = {}, ...k) => { const e = document.createElement(t); for (const [x, v] of Object.entries(a)) x.startsWith("on") ? e.addEventListener(x.slice(2), v) : e.setAttribute(x, v); e.append(...k.flat()); return e; };
const BASE = window.API_BASE || "http://localhost:8000", Z = 1.5;
const S = { tok: localStorage.tok || "", user: null, files: [], cur: null, chats: [], chat: null, sel: new Set(), m: [], mi: -1, rev: 0 };

function toast(msg, err) { const t = h("div", { class: "toast", style: err ? "background:var(--danger);color:#fff" : "" }, msg); $("#toasts").append(t); setTimeout(() => t.remove(), 4500); }
async function call(p, o = {}, raw) {
  const hd = { ...(o.json ? { "Content-Type": "application/json" } : {}), ...(S.tok ? { Authorization: "Bearer " + S.tok } : {}) };
  let r; try { r = await fetch(BASE + p, { method: o.method || "GET", headers: hd, body: o.json ? JSON.stringify(o.json) : o.body }); } catch { throw new Error("Cannot reach backend at " + BASE); }
  if (r.status === 401 && S.tok) { logout(); throw new Error("Session expired - please log in"); }
  if (!r.ok) { let d = ""; try { d = (await r.json()).detail; } catch {} throw new Error(typeof d === "string" && d ? d : "Request failed (" + r.status + ")"); }
  return raw ? r : r.json();
}
const post = (p, json) => call(p, { method: "POST", json: json || {} });
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };

/* ---------- theme ---------- */
if (localStorage.theme) document.documentElement.dataset.theme = localStorage.theme;
$("#themeBtn").onclick = () => { const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = t; localStorage.theme = t; };
$("#menuBtn").onclick = () => { $("#sidebar").classList.add("open"); $("#scrim").classList.add("show"); };
$("#scrim").onclick = () => { $("#sidebar").classList.remove("open"); $("#scrim").classList.remove("show"); };

/* ---------- auth ---------- */
let mode = "login";
function setMode(m) { mode = m; $("#authTitle").textContent = m === "login" ? "Welcome back" : "Create your account"; $("#nameRow").hidden = m === "login"; $("#authBtn").textContent = m === "login" ? "Log in" : "Sign up"; $("#authSwitch").textContent = m === "login" ? "No account? Sign up" : "Have an account? Log in"; $("#aPass").autocomplete = m === "login" ? "current-password" : "new-password"; $("#authErr").textContent = ""; }
$("#authSwitch").onclick = () => setMode(mode === "login" ? "signup" : "login");
$("#authForm").onsubmit = async (e) => {
  e.preventDefault(); $("#authErr").textContent = "";
  try {
    const body = { email: $("#aEmail").value, password: $("#aPass").value, ...(mode === "signup" ? { full_name: $("#aName").value } : {}) };
    S.tok = (await post("/auth/" + mode, body)).token; localStorage.tok = S.tok; boot();
  } catch (err) { $("#authErr").textContent = err.message; }
};
function logout() { S.tok = ""; localStorage.removeItem("tok"); $("#app").hidden = true; $("#auth").hidden = false; }
$("#logout").onclick = () => { $("#profile").close(); logout(); };
$("#profileBtn").onclick = () => { const u = S.user; $("#pInfo").replaceChildren(...[["User ID", u.user_id], ["Name", u.full_name], ["Email", u.email], ["Joined", new Date(u.created_at * 1000).toLocaleString()]].flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])); $("#profile").showModal(); };

/* ---------- files ---------- */
async function loadFiles() { S.files = (await call("/files")).files; if (S.cur) S.cur = S.files.find((f) => f.file_id === S.cur.file_id) || null; renderFiles(); }
function renderFiles() {
  $("#fileCount").textContent = S.files.length;
  $("#fileList").replaceChildren(...(S.files.length ? S.files.map((f) => {
    const cb = h("input", { type: "checkbox", "aria-label": "Use " + f.filename + " in chat" }); cb.checked = S.sel.has(f.file_id);
    cb.onchange = () => (cb.checked ? S.sel.add(f.file_id) : S.sel.delete(f.file_id));
    return h("li", { class: "doc-row" + (S.cur?.file_id === f.file_id ? " on" : "") }, cb,
      h("div", { onclick: () => openFile(f.file_id) }, h("div", { class: "doc-name" }, f.filename), h("div", { class: "doc-meta" }, `${f.page_count} pg · ${(f.file_size / 1024).toFixed(0)} KB`)),
      h("button", { class: "doc-action", "aria-label": "Delete " + f.filename, onclick: guard(() => delFile(f)) }, "🗑"));
  }) : [h("li", { class: "empty-note" }, "No files yet — drop a PDF above.")]));
}
async function delFile(f) { if (!confirm(`Delete "${f.filename}" permanently?`)) return; await call("/files/" + f.file_id, { method: "DELETE" }); S.sel.delete(f.file_id); if (S.cur?.file_id === f.file_id) { S.cur = null; showFile(); } await loadFiles(); }
async function upload(list) {
  for (const f of list) {
    const row = h("div", { class: "queue-item" }, f.name + " — uploading…"); $("#upStatus").append(row);
    try { const fd = new FormData(); fd.append("files", f); const r = (await call("/files", { method: "POST", body: fd })).results[0]; row.textContent = `${f.name} — ${r.status}${r.reason ? ": " + r.reason : ""}`; }
    catch (e) { row.textContent = `${f.name} — failed: ${e.message}`; }
  }
  await loadFiles(); if (!S.cur && S.files[0]) openFile(S.files[0].file_id);
}
$("#fileInput").onchange = (e) => { upload([...e.target.files]); e.target.value = ""; };
$("#drop").ondragover = (e) => { e.preventDefault(); $("#drop").classList.add("dragover"); };
$("#drop").ondragleave = () => $("#drop").classList.remove("dragover");
$("#drop").ondrop = (e) => { e.preventDefault(); $("#drop").classList.remove("dragover"); upload([...e.dataTransfer.files]); };

/* ---------- viewer ---------- */
const io = new IntersectionObserver((es) => es.forEach(async (e) => {
  if (!e.isIntersecting) return; const pg = e.target; io.unobserve(pg);
  try {
    const r = await call(`/files/${S.cur.file_id}/page/${pg.dataset.n}?v=${S.rev}`, {}, true);
    const img = h("img", { alt: "Page " + pg.dataset.n }); img.onload = () => { pg.style.aspectRatio = img.naturalWidth + "/" + img.naturalHeight; drawHl(pg); }; img.src = URL.createObjectURL(await r.blob()); pg.prepend(img);
  } catch (err) { pg.textContent = err.message; }
}), { rootMargin: "500px" });
function showFile() {
  $("#curName").textContent = S.cur ? S.cur.filename : "No PDF open"; renderFiles(); S.rev++;
  const box = $("#pages"); box.replaceChildren();
  if (!S.cur) return box.append(h("p", { class: "muted" }, "Select or upload a PDF to view and edit it."));
  if (!/\.pdf$/i.test(S.cur.filename)) return box.append(h("p", { class: "muted" }, "Preview and editing are available for PDFs only."));
  for (let n = 1; n <= S.cur.page_count; n++) { const pg = h("div", { class: "pg", "data-n": n }); box.append(pg); io.observe(pg); }
  $("#undo").disabled = S.cur.head <= 0; $("#redo").disabled = S.cur.head >= S.cur.maxv;
}
function drawHl(pg) {
  pg.querySelectorAll(".hl").forEach((x) => x.remove()); const img = pg.querySelector("img"); if (!img?.naturalWidth) return;
  S.m.forEach((m, i) => { if (m.page != pg.dataset.n) return; const [x0, y0, x1, y1] = m.rect.map((v) => v * Z); const W = img.naturalWidth, H = img.naturalHeight;
    pg.append(h("div", { class: "hl" + (i === S.mi ? " cur" : ""), style: `left:${x0 / W * 100}%;top:${y0 / H * 100}%;width:${(x1 - x0) / W * 100}%;height:${(y1 - y0) / H * 100}%` })); });
}
async function openFile(id) { S.cur = S.files.find((f) => f.file_id === id); S.m = []; S.mi = -1; $("#fq").value = ""; renderMatches(); showFile(); $("#sidebar").classList.remove("open"); $("#scrim").classList.remove("show"); }
async function find(keep) {
  const q = $("#fq").value; if (!S.cur || !q.trim()) { S.m = []; S.mi = -1; return renderMatches(); }
  S.m = (await call(`/files/${S.cur.file_id}/matches?q=${encodeURIComponent(q)}`)).matches;
  S.mi = S.m.length ? Math.min(keep ?? 0, S.m.length - 1) : -1; renderMatches(); if (S.mi >= 0) go(S.mi);
}
function renderMatches() {
  const cm = S.m[S.mi]; $("#lineEdit").hidden = !cm; if (cm) $("#lineTxt").value = cm.line || "";
  $("#fCount").textContent = S.m.length ? `Match ${S.mi + 1} of ${S.m.length}` : "0 matches";
  $("#mList").replaceChildren(...S.m.map((m, i) => h("li", { class: i === S.mi ? "cur" : "", onclick: () => go(i) }, `Match ${i + 1} of ${S.m.length} — Page ${m.page}: `, m.snippet)));
  document.querySelectorAll(".pg").forEach(drawHl);
}
function go(i) { if (!S.m.length) return; S.mi = (i + S.m.length) % S.m.length; renderMatches(); document.querySelector(`.pg[data-n="${S.m[S.mi].page}"]`)?.scrollIntoView({ block: "center" }); document.querySelector("#mList li.cur")?.scrollIntoView({ block: "nearest" }); }
async function afterEdit(st, keep) { Object.assign(S.cur, st); S.files = S.files.map((f) => (f.file_id === st.file_id ? { ...f, ...st } : f)); showFile(); await find(keep); }
let t; $("#fq").oninput = () => { clearTimeout(t); t = setTimeout(guard(() => find()), 250); };
$("#fq").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); go(S.mi + (e.shiftKey ? -1 : 1)); }
});
$("#fNext").onclick = () => go(S.mi + 1); $("#fPrev").onclick = () => go(S.mi - 1);
$("#rOne").onclick = guard(async () => { const m = S.m[S.mi]; if (!m) return toast("Select a match first", true); const keep = S.mi; await afterEdit(await post(`/files/${S.cur.file_id}/replace`, { page: m.page, rect: m.rect, q: $("#fq").value, new_text: $("#fr").value }), keep); toast("Replaced this occurrence"); });
$("#rAll").onclick = guard(async () => { if (!S.m.length) return toast("Nothing to replace", true); if (!confirm(`Replace all ${S.m.length} matches?`)) return; await afterEdit(await post(`/files/${S.cur.file_id}/replace_all`, { q: $("#fq").value, new_text: $("#fr").value })); toast("Replaced all matches"); });
$("#undo").onclick = guard(async () => afterEdit(await post(`/files/${S.cur.file_id}/undo`)));
$("#redo").onclick = guard(async () => afterEdit(await post(`/files/${S.cur.file_id}/redo`)));
$("#commit").onclick = guard(async () => { if (!S.cur) return; await post(`/files/${S.cur.file_id}/commit`); toast("Saved and re-indexed for chat"); });
$("#dl").onclick = guard(async () => { if (!S.cur) return; const b = await (await call(`/files/${S.cur.file_id}/download`, {}, true)).blob(); const a = h("a", { href: URL.createObjectURL(b), download: S.cur.filename.replace(/\.\w+$/, "") + "_edited.pdf" }); a.click(); URL.revokeObjectURL(a.href); });

/* ---------- chats ---------- */
async function loadChats() { S.chats = (await call("/chats")).chats; renderChats(); }
function renderChats() {
  const f = $("#chatSearch").value.toLowerCase(), list = S.chats.filter((c) => c.title.toLowerCase().includes(f));
  $("#chatList").replaceChildren(...(list.length ? list.map((c) => h("li", { class: "chat-item" + (S.chat?.chat_id === c.chat_id ? " on" : "") },
    h("button", { class: "link-btn", onclick: guard(() => openChat(c.chat_id)) }, c.title),
    h("button", { class: "doc-action", "aria-label": "Delete chat " + c.title, onclick: guard(() => delChat(c)) }, "🗑"))) : [h("li", { class: "empty-note" }, "No chats yet.")]));
}
$("#chatSearch").oninput = renderChats;
async function openChat(id) {
  S.chat = await call("/chats/" + id); S.sel = new Set(S.chat.linked_pdf_ids); renderChats(); renderFiles(); renderLog();
  const first = S.files.find((f) => S.sel.has(f.file_id)); if (first && S.cur?.file_id !== first.file_id) openFile(first.file_id);
}
async function delChat(c) { if (!confirm(`Delete chat "${c.title}"? This cannot be undone.`)) return; await call("/chats/" + c.chat_id, { method: "DELETE" }); if (S.chat?.chat_id === c.chat_id) { S.chat = null; renderLog(); } await loadChats(); }
$("#newChat").onclick = () => { S.chat = null; renderChats(); renderLog(); $("#q").focus(); };
function msgNode(m) {
  if (m.role === "user") return h("div", { class: "message user" }, m.content);
  const body = h("div", { class: "answer-text" });
  window.marked && window.DOMPurify ? (body.innerHTML = DOMPurify.sanitize(marked.parse(m.content))) : (body.textContent = m.content);
  const box = h("div", { class: "message assistant" + (m.no_relevant_content ? " info" : "") }, body);
  if (m.sources?.length) box.append(h("div", { class: "source-wrap" }, h("div", { class: "source-heading" }, "Sources"), m.sources.map((s, i) =>
    h("details", { class: "source-card" }, h("summary", {}, h("span", { class: "source-number" }, `[${i + 1}]`), h("span", { class: "source-title" }, s.source_name || "document"),
      h("span", { class: "source-meta" }, `p.${s.page_number} · ${s.similarity.toFixed(2)}`)), h("div", { class: "source-full" }, s.text)))));
  return box;
}
function renderLog() {
  const msgs = S.chat?.messages || [];
  $("#log").replaceChildren(...(msgs.length ? msgs.map(msgNode) : [h("div", { class: "welcome" }, h("h2", {}, "Ask your PDFs"), h("p", {}, "Tick the PDFs to use as context (none ticked = all your files), then ask a question."))]));
  $("#log").scrollTop = $("#log").scrollHeight;
}
let busy = false;
async function send() {
  const q = $("#q").value.trim(); if (!q || busy) return; busy = true; $("#send").disabled = true; $("#q").value = ""; autosize();
  try {
    if (!S.chat) S.chat = { ...(await post("/chats", { linked_pdf_ids: [...S.sel] })), messages: [] };
    S.chat.messages.push({ role: "user", content: q }); renderLog();
    const typing = h("div", { class: "message assistant typing" }, h("i"), h("i"), h("i")); $("#log").append(typing); typing.scrollIntoView();
    const r = await post(`/chats/${S.chat.chat_id}/ask`, { question: q, linked_pdf_ids: [...S.sel] });
    S.chat.messages.push({ role: "assistant", content: r.answer, sources: r.sources, no_relevant_content: r.no_relevant_content }); renderLog(); await loadChats();
  } catch (e) { toast(e.message, true); S.chat?.messages.pop(); renderLog(); $("#log").append(h("div", { class: "message error", role: "alert" }, "Could not get an answer: " + e.message)); $("#q").value = q; autosize(); }
  busy = false; $("#send").disabled = false; $("#q").focus();
}
const autosize = () => { const q = $("#q"); q.style.height = "auto"; q.style.height = Math.max(44, Math.min(q.scrollHeight, 160)) + "px"; $("#cnt").textContent = `${q.value.length} / 4000`; };
$("#form").onsubmit = (e) => { e.preventDefault(); send(); };
document.querySelector(".composer-inner").onclick = () => $("#q").focus(); $("#q").oninput = autosize;
$("#q").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
});

/* ---------- boot ---------- */
async function boot() {
  if (!S.tok) { setMode("login"); $("#auth").hidden = false; return; }
  try {
    S.user = await call("/auth/me"); $("#auth").hidden = true; $("#app").hidden = false; $("#who").textContent = S.user.full_name;
    await Promise.all([loadFiles(), loadChats()]); showFile(); renderLog(); $("#q").focus();
    if (S.chats[0]) openChat(S.chats[0].chat_id);
  } catch (e) { $("#auth").hidden = false; $("#authErr").textContent = e.message; }
}
boot();

/* zoom */
let zoom = 1; const setZoom = (z) => { zoom = Math.max(0.5, Math.min(2, z)); $("#pages").style.setProperty("--zoom", zoom); };
$("#zOut").onclick = () => setZoom(zoom - 0.2); $("#zIn").onclick = () => setZoom(zoom + 0.2);

/* edit the whole line around a match (change neighbouring words too) */
const applyLine = guard(async () => { const m = S.m[S.mi]; if (!m) return; const keep = S.mi;
  await afterEdit(await post(`/files/${S.cur.file_id}/edit_line`, { page: m.page, rect: m.rect, new_text: $("#lineTxt").value }), keep); toast("Line updated"); });
$("#lineBtn").onclick = applyLine;
$("#lineTxt").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); applyLine(); } });
