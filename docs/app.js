// IdeaGraph Cockpit — Tabs: Ingest / Graph / Review.
// Graph: d3-force + Zoom/Pan + Hover-Tooltip + Fokus + Suche (Obsidian-artig).

// ================= Graph Setup =================
const svg = d3.select("#graph");
const viewport = svg.append("g"); // transformiert durch Zoom
const linkG = viewport.append("g"), nodeG = viewport.append("g");
// Fallback-Größe für den versteckten Graph-Tab beim Start (sonst 0×0 → Kollaps)
let W = 1200, H = 800;

const KIND_COLOR = { "ähnlich": "#3fb950", "kontradiktorisch": "#f85149", "erweitert": "#58a6ff", "same_as": "#bc8cff", "supersedes": "#f0883e", "continues": "#58a6ff" };

const nodes = [], links = [];
const sim = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(links).id(d => d.id).distance(140))
  .force("charge", d3.forceManyBody().strength(-350))
  .force("center", d3.forceCenter(0, 0))
  .alphaDecay(0.02)
  .on("tick", tick);

function size() {
  const el = document.getElementById("graphwrap");
  if (!el) return;
  const w = el.clientWidth, h = el.clientHeight;
  if (w && h) { W = w; H = h; } // nur echte Größe übernehmen (Tab sichtbar)
  svg.attr("viewBox", `0 0 ${W} ${H}`);
  sim.force("center", d3.forceCenter(W / 2, H / 2));
  if (!nodes.length) sim.alpha(0.3).restart();
}
window.addEventListener("resize", () => { size(); if (activeTab === "graph") sim.alpha(0.3).restart(); });

// ---------- Zoom / Pan ----------
const zoom = d3.zoom().scaleExtent([0.12, 6])
  .on("start", () => d3.select("#graphwrap").classed("dragging", true))
  .on("end", () => d3.select("#graphwrap").classed("dragging", false))
  .on("zoom", ev => viewport.attr("transform", ev.transform));
svg.call(zoom);
document.getElementById("zoomIn").onclick = () => svg.transition().call(zoom.scaleBy, 1.4);
document.getElementById("zoomOut").onclick = () => svg.transition().call(zoom.scaleBy, 1 / 1.4);
document.getElementById("zoomReset").onclick = () => svg.transition().call(zoom.transform, d3.zoomIdentity);

function seedPosition(d, i) {
  if (d.x == null) {
    const a = (i / Math.max(nodes.length, 1)) * 2 * Math.PI;
    d.x = W / 2 + 120 * Math.cos(a) + (Math.random() - 0.5) * 40;
    d.y = H / 2 + 120 * Math.sin(a) + (Math.random() - 0.5) * 40;
  }
}

// ---------- Fokus (Obsidian-artig) ----------
let focus = null; // Node-ID im Fokus
function focusSet() {
  if (!focus) return null;
  const s = new Set([focus]);
  links.forEach(l => {
    const a = l.source.id || l.source, b = l.target.id || l.target;
    if (a === focus) s.add(b); if (b === focus) s.add(a);
  });
  return s;
}

// ---------- Hover-Tooltip ----------
const tip = d3.select("#tip");
function moveTip(ev) {
  const r = document.getElementById("graphwrap").getBoundingClientRect();
  tip.style("left", (ev.clientX - r.left + 14) + "px")
     .style("top", (ev.clientY - r.top + 14) + "px");
}
function showTip(ev, d) {
  tip.html(esc(d.text.length > 280 ? d.text.slice(0, 279) + "…" : d.text)).style("opacity", 1);
  moveTip(ev);
}
function hideTip() { tip.style("opacity", 0); }

// ---------- Render ----------
function tick() {
  nodes.forEach(seedPosition);
  const fs = focusSet();

  const ll = linkG.selectAll("line").data(links, d => key(d));
  ll.exit().remove();
  ll.enter().append("line").merge(ll)
    .attr("stroke", d => KIND_COLOR[d.kind] || "#8b949e")
    .attr("stroke-width", 1.5)
    .attr("stroke-dasharray", d => d.pending ? "4 4" : null)
    .attr("opacity", d => {
      if (fs) { const a = d.source.id || d.source, b = d.target.id || d.target; return (fs.has(a) && fs.has(b)) ? 0.9 : 0.08; }
      return d.pending ? 0.5 : 0.9;
    })
    .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
    .attr("x2", d => d.target.x).attr("y2", d => d.target.y);

  const nn = nodeG.selectAll("circle").data(nodes, d => d.id);
  nn.exit().remove();
  nn.enter().append("circle")
    .attr("r", 9)
    .call(drag(sim))
    .on("click", (ev, d) => { ev.stopPropagation(); showDetail(d.id); })
    .on("dblclick", (ev, d) => { ev.stopPropagation(); toggleFocus(d.id); })
    .on("mouseover", (ev, d) => showTip(ev, d))
    .on("mousemove", moveTip)
    .on("mouseout", hideTip)
    .merge(nn)
    .attr("fill", d => (fs && !fs.has(d.id)) ? "#30363d" : (d.id === focus ? "#f0883e" : "#e6edf3"))
    .attr("cx", d => d.x).attr("cy", d => d.y)
    .attr("opacity", d => (fs && !fs.has(d.id)) ? 0.35 : 1);

  const tl = nodeG.selectAll("text").data(nodes, d => d.id);
  tl.exit().remove();
  tl.enter().append("text").attr("dy", -15).attr("text-anchor", "middle")
    .attr("fill", "#8b949e").attr("font-size", 10).merge(tl)
    .attr("opacity", d => (fs && !fs.has(d.id)) ? 0.25 : 1)
    .attr("x", d => d.x).attr("y", d => d.y)
    .text(d => d.text.length > 26 ? d.text.slice(0, 25) + "…" : d.text);
}

function toggleFocus(id) {
  focus = (focus === id) ? null : id;
  const f = document.getElementById("gcount");
  if (f) f.textContent = focus ? `Fokus: ${short(texts[id], 30)} · Doppelklick/Reset zum Lösen` : `${nodes.length} Nodes · ${links.length} Edges`;
  sim.alpha(0.3).restart();
}

const key = d => (d.source.id || d.source) + "|" + (d.target.id || d.target) + "|" + d.kind;

function drag(s) {
  return d3.drag()
    .on("start", (ev, d) => {
      ev.sourceEvent.stopPropagation(); // Zoom-Pan nicht triggern
      if (!ev.active) s.alphaTarget(0.3).restart();
      d.fx = d.x; d.fy = d.y;
    })
    .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
    .on("end", (ev, d) => { if (!ev.active) s.alphaTarget(0); d.fx = null; d.fy = null; });
}
// Doppelklick auf Hintergrund → Fokus lösen
svg.on("dblclick.zoom", null).on("dblclick", () => { if (focus) { focus = null; sim.alpha(0.3).restart(); } });

// ================= State / Daten =================
let texts = {}, pending = [], sel = 0;
let activeTab = "ingest";
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const short = (id, n = 60) => { const t = texts[id] || id; return t.length > n ? t.slice(0, n - 1) + "…" : t; };

async function refresh() {
  const g = await (await fetch("/api/graph")).json();
  g.nodes.forEach(n => { texts[n.id] = n.text; if (!nodes.find(x => x.id === n.id)) nodes.push(n); });
  links.length = 0;
  g.edges.forEach(e => links.push({ source: e.source, target: e.target, kind: e.kind, pending: e.pending, id: e.id }));
  pending = g.edges.filter(e => e.pending);
  if (sel >= pending.length) sel = Math.max(0, pending.length - 1);
  renderCards();
  renderHits();
  const c = document.getElementById("gcount");
  if (c && !focus) c.textContent = `${nodes.length} Nodes · ${links.length} Edges`;
  sim.force("link").links(links).id(d => d.id);
  sim.nodes(nodes);
  sim.alpha(1).restart(); tick();
}

// ================= Tabs =================
function showTab(name) {
  activeTab = name;
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.id === "tab-" + name));
  if (name === "graph") { size(); sim.alpha(0.4).restart(); }
  if (name === "ingest") setTimeout(() => document.getElementById("ingestarea").focus(), 50);
}
document.querySelectorAll("nav button").forEach(b => b.onclick = () => showTab(b.dataset.tab));

// ================= Ingest =================
function ingest() {
  const el = document.getElementById("ingestarea");
  const text = el.value.trim();
  if (!text) return;
  const source = document.getElementById("ingsrc").value;
  const status = document.getElementById("ingstatus");
  status.textContent = "Ingestiere …";
  fetch("/api/ingest", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, source }),
  }).then(async r => {
    if (!r.ok) { status.textContent = "Ingest fehlgeschlagen"; return flash("Ingest fehlgeschlagen", false); }
    const data = await r.json();
    el.value = "";
    if (data.duplicate) {
      status.textContent = `Duplikat — in bestehende Idee „${short(data.node.id, 50)}“ gemergt`;
      flash("Duplikat gemergt", true);
    } else {
      const n = data.suggested ? data.suggested.length : 0;
      status.textContent = `Node erstellt (${data.node.id.slice(0, 8)}) · ${n} Vorschlag/Vorschläge → Review-Tab`;
      flash("Ingestiert — Graph wächst", true);
    }
    await refresh();
  }).catch(() => status.textContent = "Netzwerkfehler");
}
document.getElementById("ingestbtn").onclick = ingest;
document.getElementById("ingestarea").addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); ingest(); }
});

// ================= Graph: Suche & Zentrieren =================
const gnode = document.getElementById("gnode");
let gHits = [];
gnode.addEventListener("input", () => {
  const q = gnode.value.trim().toLowerCase();
  if (!q) { gHits = []; return; }
  gHits = nodes.filter(n => n.text.toLowerCase().includes(q)).slice(0, 12);
});
gnode.addEventListener("keydown", e => {
  if (e.key !== "Enter" || !gHits.length) return;
  const n = nodes.find(x => x.id === gHits[0].id);
  if (!n) return;
  const k = 1.5;
  const t = d3.zoomIdentity.translate(W / 2 - n.x * k, H / 2 - n.y * k).scale(k);
  svg.transition().duration(500).call(zoom.transform, t);
  flash(`→ ${short(n.id, 40)}`);
});

// ================= Node-Detail =================
function showDetail(id) {
  const t = texts[id]; if (!t) return;
  fetch("/api/graph").then(r => r.json()).then(g => {
    const rels = g.edges.filter(e => e.source === id || e.target === id);
    document.getElementById("detailbox").innerHTML = `
      <h3>${esc(t)}</h3>
      <div class="meta">${id}</div>
      <p>${esc(t)}</p>
      <div class="rel"><b>Verbindungen:</b><br>${rels.map(e =>
        `${KIND_COLOR[e.kind] ? "●" : "○"} ${e.kind} → ${short(e.target === id ? e.source : e.target, 40)} ${e.pending ? "(pending)" : ""}`).join("<br>") || "keine"}</div>`;
    document.getElementById("detail").classList.add("show");
  });
}
function hideDetail() { document.getElementById("detail").classList.remove("show"); }
document.getElementById("detail").addEventListener("click", e => { if (e.target.id === "detail") hideDetail(); });

// ================= Review: Pending-Cards =================
function renderCards() {
  const box = document.getElementById("cards");
  if (!pending.length) {
    box.innerHTML = `<div style="color:var(--dim);font-size:12px;line-height:1.7;">Keine offenen Vorschläge.<br><br>
      Ingestiere Ideen im Ingest-Tab — verwandte Ideen erscheinen hier zur Entscheidung.</div>`;
    return;
  }
  box.innerHTML = pending.map((e, i) => `
    <div class="card ${i === sel ? "active" : ""}" data-i="${i}">
      <span class="kind ${esc(e.kind)}">${esc(e.kind)}</span>
      <div class="nodebox"><div class="id">${e.source.slice(0, 8)}</div>${esc(short(e.source))}</div>
      <div class="nodebox"><div class="id">${e.target.slice(0, 8)}</div>${esc(short(e.target))}</div>
      <div class="actions">
        <button class="ok" onclick="resolveEdge('${e.id}',true)">✓ akzeptieren</button>
        <button class="no" onclick="resolveEdge('${e.id}',false)">✗ verwerfen</button>
      </div>
    </div>`).join("");
  box.querySelectorAll(".card").forEach(c => c.addEventListener("click", () => { sel = +c.dataset.i; renderCards(); }));
}
async function resolveEdge(id, accept) {
  const r = await fetch(`/api/edge/${id}/${accept ? "accept" : "reject"}`, { method: "POST" });
  if (!r.ok) return flash("Fehler beim Auflösen", false);
  flash(accept ? "Edge akzeptiert" : "Edge verworfen");
  await refresh();
}

// ================= Review: same_as-Picker =================
let pickA = null, pickB = null;
function renderHits() {
  const box = document.getElementById("hits");
  const q = (document.getElementById("search").value || "").trim().toLowerCase();
  const hits = q ? nodes.filter(n => n.text.toLowerCase().includes(q)).slice(0, 20) : [];
  box.innerHTML = hits.map(n => `<div class="hit ${n.id === pickA ? "pickedA" : ""} ${n.id === pickB ? "pickedB" : ""}" data-id="${n.id}">${esc(short(n.id, 34))}</div>`).join("")
    || (q ? `<div class="hit">keine Treffer</div>` : "");
  box.querySelectorAll(".hit").forEach(h => h.onclick = () => pick(h.dataset.id));
  document.getElementById("slotA").textContent = pickA ? "A: " + short(pickA, 30) : "A: leer";
  document.getElementById("slotB").textContent = pickB ? "B: " + short(pickB, 30) : "B: leer";
  document.getElementById("slotA").classList.toggle("filled", !!pickA);
  document.getElementById("slotB").classList.toggle("filled", !!pickB);
  document.getElementById("linkbtn").disabled = !(pickA && pickB);
}
function pick(id) {
  if (!pickA) pickA = id; else if (!pickB) pickB = id; else { pickA = id; pickB = null; }
  renderHits();
}
document.getElementById("search").addEventListener("input", renderHits);
async function linkPicked() {
  if (!pickA || !pickB) return;
  const r = await fetch("/api/edge", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: pickA, target: pickB, kind: "same_as" }) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); flash(e.error || "Fehler", false); return; }
  flash("same_as verlinkt"); pickA = pickB = null; renderHits(); await refresh();
}
document.getElementById("linkbtn").onclick = linkPicked;

// ================= Keyboard =================
document.addEventListener("keydown", e => {
  const tag = (document.activeElement.tagName || "").toUpperCase();
  const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
  if (typing) return;

  if (e.key === "1") showTab("ingest");
  else if (e.key === "2") showTab("graph");
  else if (e.key === "3") showTab("review");
  else if (e.key === "i") { showTab("ingest"); document.getElementById("ingestarea").focus(); }
  else if (activeTab === "review") {
    if (e.key === "j") { if (pending.length) { sel = Math.min(sel + 1, pending.length - 1); renderCards(); } }
    else if (e.key === "k") { if (pending.length) { sel = Math.max(sel - 1, 0); renderCards(); } }
    else if (e.key === "Enter") { if (pending[sel]) resolveEdge(pending[sel].id, true); }
    else if (e.key === "Escape") { if (pending[sel]) resolveEdge(pending[sel].id, false); }
  }
});

// ================= Flash =================
function flash(msg, ok = true) {
  const f = document.getElementById("flash");
  f.textContent = msg; f.style.borderColor = ok ? "var(--green)" : "var(--red)";
  f.style.color = ok ? "var(--green)" : "var(--red)"; f.style.opacity = 1;
  setTimeout(() => f.style.opacity = 0, 1800);
}

// ================= WebSocket Live =================
const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
ws.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if (m.type === "ingested") { if (m.duplicate) flash("Duplikat erkannt — gemergt"); refresh(); }
  else if (m.type === "edge_resolved" || m.type === "edge_linked") { refresh(); }
};

// ================= Start =================
size();
showTab("ingest");
refresh();
