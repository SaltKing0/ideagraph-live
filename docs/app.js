// IdeaGraph Live — d3-force, Vanilla-JS, kein Build-Step.
const svg = d3.select("#graph");
const width = window.innerWidth, height = window.innerHeight;
svg.attr("width", width).attr("height", height);

const nodes = [], links = [];
const sim = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(links).id(d => d.id).distance(120))
  .force("charge", d3.forceManyBody().strength(-300))
  .force("center", d3.forceCenter(width / 2, height / 2 + 30))
  .on("tick", tick);

const linkG = svg.append("g"), nodeG = svg.append("g");

function color(kind) {
  return { "ähnlich": "#3fb950", "kontradiktorisch": "#f85149", "erweitert": "#58a6ff" }[kind] || "#8b949e";
}

function tick() {
  const ll = linkG.selectAll("line").data(links, d => d.source.id + d.target.id + d.kind);
  ll.exit().remove();
  ll.enter().append("line")
    .merge(ll)
    .attr("stroke", d => color(d.kind))
    .attr("stroke-width", 1.5)
    .attr("stroke-dasharray", d => d.pending ? "4 4" : null)
    .attr("opacity", d => d.pending ? 0.5 : 0.9);

  const nn = nodeG.selectAll("circle").data(nodes, d => d.id);
  nn.exit().remove();
  nn.enter().append("circle").attr("r", 8).call(drag(sim))
    .on("click", (ev, d) => alert(d.text))
    .merge(nn)
    .attr("fill", "#e6edf3");

  const tl = nodeG.selectAll("text").data(nodes, d => d.id);
  tl.exit().remove();
  tl.enter().append("text").attr("dy", -14).attr("text-anchor", "middle")
    .attr("fill", "#8b949e").attr("font-size", 11).merge(tl)
    .text(d => d.text.length > 28 ? d.text.slice(0, 27) + "…" : d.text);
}

function drag(sim) {
  return d3.drag()
    .on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
    .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
    .on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; });
}

function sync(graph) {
  graph.nodes.forEach(n => { if (!nodes.find(x => x.id === n.id)) nodes.push(n); });
  graph.edges.forEach(e => {
    if (!links.find(l => l.source === e.source && l.target === e.target && l.kind === e.kind)) {
      links.push({ source: e.source, target: e.target, kind: e.kind, pending: e.pending });
    }
  });
  renderPending();
  sim.alpha(1).restart();
  tick();
}

function renderPending() {
  const box = document.getElementById("pending");
  fetch("/api/graph").then(r => r.json()).then(g => {
    const pending = g.edges.filter(e => e.pending);
    box.innerHTML = pending.map(e =>
      `<div class="pend">Vorschlag: <b>${e.kind}</b> → ${short(e.target)}
        <button class="ok" onclick="resolve('${e.id}',true)">✓</button>
        <button onclick="resolve('${e.id}',false)">✗</button></div>`).join("");
    window._nodeTexts = Object.fromEntries(g.nodes.map(n => [n.id, n.text]));
  });
}
function short(id) {
  const t = (window._nodeTexts || {})[id];
  return t ? (t.length > 40 ? t.slice(0, 39) + "…" : t) : id;
}
async function resolve(id, accept) {
  await fetch(`/api/edge/${id}/${accept ? "accept" : "reject"}`, { method: "POST" });
  location.reload();
}

async function ingest() {
  const el = document.getElementById("text");
  if (!el.value.trim()) return;
  await fetch("/api/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: el.value }),
  });
  el.value = "";
}

document.getElementById("text").addEventListener("keydown", e => { if (e.key === "Enter") ingest(); });

fetch("/api/graph").then(r => r.json()).then(sync);

const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
ws.onmessage = ev => {
  const msg = JSON.parse(ev.data);
  if (msg.type === "ingested") {
    if (!nodes.find(x => x.id === msg.node.id)) nodes.push(msg.node);
    msg.edges.forEach(e => links.push({ source: e.source, target: e.target, kind: e.kind, pending: e.pending }));
    renderPending();
    sim.alpha(1).restart(); tick();
  } else if (msg.type === "edge_resolved") {
    renderPending();
    if (!msg.accepted) location.reload();
  }
};
