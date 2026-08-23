// IdeaGraph Cockpit — Keyboard-first, ein Screen, d3-force + Inbox.
const svg = d3.select("#graph");
let W = window.innerWidth, H = window.innerHeight;
svg.attr("width", W).attr("height", H);

const nodes = [], links = [];
const sim = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(links).id(d => d.id).distance(140))
  .force("charge", d3.forceManyBody().strength(-350))
  .force("center", d3.forceCenter(W / 2 - 190, H / 2))
  .alphaDecay(0.02)
  .on("tick", tick);

// Nodes ohne Position starten verteilt statt kollabiert im Ursprung
function seedPosition(d, i) {
  if (d.x == null) {
    const angle = (i / Math.max(nodes.length, 1)) * 2 * Math.PI;
    d.x = W / 2 - 190 + 120 * Math.cos(angle) + (Math.random() - 0.5) * 40;
    d.y = H / 2 + 120 * Math.sin(angle) + (Math.random() - 0.5) * 40;
  }
}

const linkG = svg.append("g"), nodeG = svg.append("g");
const KIND_COLOR = { "ähnlich": "#3fb950", "kontradiktorisch": "#f85149", "erweitert": "#58a6ff", "same_as": "#bc8cff" };

function tick() {
  nodes.forEach(seedPosition);
  const ll = linkG.selectAll("line").data(links, d => key(d));
  ll.exit().remove();
  ll.enter().append("line").merge(ll)
    .attr("stroke", d => KIND_COLOR[d.kind] || "#8b949e")
    .attr("stroke-width", 1.5)
    .attr("stroke-dasharray", d => d.pending ? "4 4" : null)
    .attr("opacity", d => d.pending ? 0.5 : 0.9)
    .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
    .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  const nn = nodeG.selectAll("circle").data(nodes, d => d.id);
  nn.exit().remove();
  nn.enter().append("circle").attr("r", 9).call(drag(sim)).on("click", (ev, d) => showDetail(d.id)).merge(nn)
    .attr("fill", "#e6edf3")
    .attr("cx", d => d.x).attr("cy", d => d.y);
  const tl = nodeG.selectAll("text").data(nodes, d => d.id);
  tl.exit().remove();
  tl.enter().append("text").attr("dy", -15).attr("text-anchor", "middle")
    .attr("fill", "#8b949e").attr("font-size", 10).merge(tl)
    .attr("x", d => d.x).attr("y", d => d.y)
    .text(d => d.text.length > 26 ? d.text.slice(0, 25) + "…" : d.text);
}
const key = d => (d.source.id || d.source) + "|" + (d.target.id || d.target) + "|" + d.kind;

function drag(s) {
  return d3.drag()
    .on("start", (ev, d) => { if (!ev.active) s.alphaTarget(.3).restart(); d.fx = d.x; d.fy = d.y; })
    .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
    .on("end", (ev, d) => { if (!ev.active) s.alphaTarget(0); d.fx = null; d.fy = null; });
}

// ---------- State ----------
let texts = {}, pending = [], sel = 0;
window._texts = texts;

async function refresh() {
  const g = await (await fetch("/api/graph")).json();
  g.nodes.forEach(n => { texts[n.id] = n.text; if (!nodes.find(x => x.id === n.id)) nodes.push(n); });
  links.length = 0;
  g.edges.forEach(e => links.push({ source: e.source, target: e.target, kind: e.kind, pending: e.pending, id: e.id }));
  pending = g.edges.filter(e => e.pending);
  if (sel >= pending.length) sel = Math.max(0, pending.length - 1);
  renderCards();
  // forceLink muss neu initialisieren, damit String-IDs zu Node-Objekten aufgelöst werden
  sim.force("link").links(links).id(d => d.id);
  sim.nodes(nodes);
  sim.alpha(1).restart(); tick();
}

function short(id, n = 60) {
  const t = texts[id] || id;
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}

function renderCards() {
  document.querySelector("#inbox h2").textContent =
    pending.length ? `Inbox · ${pending.length} pending` : "Inbox";
  const box = document.getElementById("cards");
  if (!pending.length) {
    box.innerHTML = `<div id="empty">Keine offenen Vorschläge.<br><br>
      Ingestiere Ideen — der Suggester schlägt Verbindungen vor,
      du entscheidest hier.</div>`;
    return;
  }
  box.innerHTML = pending.map((e, i) => `
    <div class="card ${i === sel ? "active" : ""}" data-i="${i}">
      <span class="kind">${e.kind}</span><span class="sim">↔</span>
      <div class="pair"><div>${esc(short(e.source))}</div><div>${esc(short(e.target))}</div></div>
      <div class="actions">
        <button class="ok" onclick="resolve('${e.id}',true)">✓ akzeptieren ⏎</button>
        <button class="no" onclick="resolve('${e.id}',false)">✗ verwerfen esc</button>
      </div>
    </div>`).join("");
  box.querySelectorAll(".card").forEach(c =>
    c.addEventListener("click", () => { sel = +c.dataset.i; renderCards(); highlightPending(sel); }));
}

const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

function flash(msg, ok = true) {
  const f = document.getElementById("flash");
  f.textContent = msg;
  f.style.borderColor = ok ? "var(--green)" : "var(--red)";
  f.style.color = ok ? "var(--green)" : "var(--red)";
  f.style.opacity = 1;
  setTimeout(() => f.style.opacity = 0, 1800);
}

async function resolve(id, accept) {
  const r = await fetch(`/api/edge/${id}/${accept ? "accept" : "reject"}`, { method: "POST" });
  if (!r.ok) return flash("Fehler beim Auflösen", false);
  flash(accept ? "Edge akzeptiert" : "Edge verworfen");
  await refresh();
}

async function ingest() {
  const el = document.getElementById("text");
  if (!el.value.trim()) return;
  const r = await fetch("/api/ingest", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: el.value }),
  });
  el.value = ""; el.blur();
  if (!r.ok) return flash("Ingest fehlgeschlagen", false);
  const data = await r.json();
  if (data.duplicate) {
    flash(`Duplikat — gemergt in „${short(data.node.id, 40)}"`, true);
    const n = nodes.find(x => x.id === data.node.id);
    if (n) { n.dupPulse = Date.now(); }
  } else {
    flash("Ingestiert — Graph wächst");
  }
  await refresh();
}

// ---------- Node-Detail ----------
let detailOpen = false;
function showDetail(id) {
  const t = texts[id]; if (!t) return;
  fetch("/api/graph").then(r => r.json()).then(g => {
    const rels = g.edges.filter(e => e.source === id || e.target === id);
    document.getElementById("detailbox").innerHTML = `
      <h3>${esc(t)}</h3>
      <div class="meta">${id}</div>
      <p>${esc(t)}</p>
      <div class="rel"><b>Verbindungen:</b><br>${rels.map(e =>
        `${KIND_COLOR[e.kind] ? "●" : "○"} ${e.kind} → ${short(e.target === id ? e.source : e.target, 40)}
         ${e.pending ? "(pending)" : ""}`).join("<br>") || "keine"}</div>`;
    document.getElementById("detail").classList.add("show");
    detailOpen = true;
  });
}
function hideDetail() {
  document.getElementById("detail").classList.remove("show");
  detailOpen = false;
}

// ---------- WebSocket Live ----------
const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
ws.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if (m.type === "ingested") {
    if (m.duplicate) flash("Duplikat erkannt — in bestehende Idee gemergt");
    refresh();
  }
};

// ---------- Keyboard ----------
document.getElementById("text").addEventListener("keydown", e => {
  if (e.key === "Enter") ingest();
  if (e.key === "Escape") e.target.blur();
});

function highlightPending(i) { /* Karten sind Quelle der Wahrheit; Graph bleibt statisch */ }

window.addEventListener("keydown", e => {
  const inField = document.activeElement.tagName === "INPUT";
  if (inField) return;

  if (detailOpen) {
    if (e.key === "Escape") hideDetail();
    return;
  }
  switch (e.key) {
    case "i": e.preventDefault(); document.getElementById("text").focus(); break;
    case "j": if (pending.length) { sel = Math.min(sel + 1, pending.length - 1); renderCards(); } break;
    case "k": if (pending.length) { sel = Math.max(sel - 1, 0); renderCards(); } break;
    case "Enter":
      if (pending[sel]) resolve(pending[sel].id, true);
      break;
    case "Escape":
      if (pending[sel]) resolve(pending[sel].id, false);
      break;
    case " ": {
      // Space: Text des aktuell gewählten Paares im Graph zeigen
      if (pending[sel]) showDetail(pending[sel].target);
      else if (nodes.length) showDetail(nodes[0].id);
      e.preventDefault();
      break;
    }
  }
});
document.getElementById("detail").addEventListener("click", e => {
  if (e.target.id === "detail") hideDetail();
});

refresh();
