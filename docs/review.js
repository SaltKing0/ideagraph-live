// IdeaGraph Review — Inbox-Arbeit + same_as-Verlinken, keyboard-first.
const $ = id => document.getElementById(id);

let nodes = {}, pending = [], sel = 0;
let pickA = null, pickB = null;

function short(id, n = 70) {
  const t = (nodes[id] || { text: id }).text.replace(/\n/g, " ");
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}
const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

function flash(msg, ok = true) {
  const f = $("flash");
  f.textContent = msg;
  f.style.borderColor = ok ? "var(--green)" : "var(--red)";
  f.style.color = ok ? "var(--green)" : "var(--red)";
  f.style.opacity = 1;
  setTimeout(() => f.style.opacity = 0, 1800);
}

async function refresh() {
  const g = await (await fetch("/api/graph")).json();
  nodes = {};
  g.nodes.forEach(n => nodes[n.id] = n);
  pending = g.edges.filter(e => e.pending);
  if (sel >= pending.length) sel = Math.max(0, pending.length - 1);
  $("count").textContent = `${pending.length} pending`;
  renderCards();
}

// ---------- Inbox ----------
function renderCards() {
  const box = $("cards");
  if (!pending.length) {
    box.innerHTML = `<div style="color:var(--dim);font-size:13px;">Keine offenen Vorschläge. 🎉</div>`;
    return;
  }
  box.innerHTML = pending.map((e, i) => `
    <div class="card ${i === sel ? "active" : ""}" data-i="${i}">
      <span class="kind ${e.kind}">${e.kind}</span>
      <div class="side-label">A</div>
      <div class="nodebox pickable" onclick="pickFromCard('${e.source}', this)">
        <span class="id">${e.source}</span><br>${esc(short(e.source))}</div>
      <div class="side-label">B</div>
      <div class="nodebox pickable" onclick="pickFromCard('${e.target}', this)">
        <span class="id">${e.target}</span><br>${esc(short(e.target))}</div>
      <div class="actions">
        <button class="ok" onclick="resolve('${e.id}',true)">✓ akzeptieren ⏎</button>
        <button class="no" onclick="resolve('${e.id}',false)">✗ verwerfen esc</button>
      </div>
    </div>`).join("");
  const active = box.querySelector(".card.active");
  if (active) active.scrollIntoView({ block: "nearest" });
}

async function resolve(id, accept) {
  const r = await fetch(`/api/edge/${id}/${accept ? "accept" : "reject"}`, { method: "POST" });
  if (!r.ok) return flash("Fehler beim Auflösen", false);
  flash(accept ? "Edge akzeptiert" : "Edge verworfen");
  await refresh();
}

// ---------- same_as-Picker ----------
function pick(id) {
  if (pickA === id || pickB === id) return; // gleiche Node nicht mit sich selbst
  if (!pickA) pickA = id;
  else if (!pickB) pickB = id;
  else { pickA = id; pickB = null; } // dritter Klick startet neu
  renderPick();
}

window.pickFromCard = (id, el) => { pick(id); el.blur(); };

function renderPick() {
  const a = $("slotA"), b = $("slotB"), btn = $("linkbtn");
  a.textContent = "A: " + (pickA ? short(pickA, 40) : "leer");
  b.textContent = "B: " + (pickB ? short(pickB, 40) : "leer");
  a.classList.toggle("filled", !!pickA);
  b.classList.toggle("filled", !!pickB);
  btn.disabled = !(pickA && pickB);
  btn.textContent = pickA && pickB
    ? `${short(pickA, 12)} ⇄ ${short(pickB, 12)} ⏎` : "verlinken ⏎";
}

async function link() {
  if (!(pickA && pickB)) return;
  const r = await fetch("/api/edge", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: pickA, target: pickB, kind: "same_as" }),
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); return flash(e.error || "Link fehlgeschlagen", false); }
  flash("same_as verlinkt");
  pickA = pickB = null;
  renderPick();
  await refresh();
}

// Suche
$("search").addEventListener("input", () => {
  const q = $("search").value.trim().toLowerCase();
  const hits = $("hits");
  if (!q) return hits.innerHTML = "";
  const found = Object.values(nodes)
    .filter(n => n.text.toLowerCase().includes(q)).slice(0, 8);
  hits.innerHTML = found.map(n =>
    `<div class="hit ${n.id === pickA ? "pickedA" : ""} ${n.id === pickB ? "pickedB" : ""}"
          onclick="searchPick('${n.id}')"><span class="id">${n.id.slice(0, 8)}</span>${esc(short(n.id, 55))}</div>`).join("");
});
window.searchPick = id => { pick(id); $("search").value = ""; $("hits").innerHTML = ""; };

$("linkbtn").addEventListener("click", link);

// ---------- Keyboard ----------
document.addEventListener("keydown", e => {
  const inField = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
  switch (e.key) {
    case "s": if (!inField) { e.preventDefault(); $("search").focus(); } break;
    case "x": if (!inField && (pickA || pickB)) { pickA = pickB = null; renderPick(); } break;
    case "j": if (!inField && pending.length) { sel = Math.min(sel + 1, pending.length - 1); renderCards(); } break;
    case "k": if (!inField && pending.length) { sel = Math.max(sel - 1, 0); renderCards(); } break;
    case "Enter":
      if (inField) break;
      if (pickA && pickB) link();
      else if (pending[sel]) resolve(pending[sel].id, true);
      break;
    case "Escape":
      if (inField) { document.activeElement.blur(); }
      else if (pending[sel]) resolve(pending[sel].id, false);
      break;
  }
});

refresh();
