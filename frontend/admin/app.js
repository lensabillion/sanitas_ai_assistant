// =================== Config ===================
const API_BASE = (
  localStorage.getItem("apiUrl") || "https://sanitas-ai-assistant.onrender.com"
).replace(/\/$/, "");
const END_CLUSTERS = `${API_BASE}/symptoms/clusters`;
console.log("[CFG] API_BASE =", API_BASE);

// Show API base in footer if present
const apiLbl = document.getElementById("apiUrlLabel");
if (apiLbl) apiLbl.textContent = API_BASE;

// ==================== DOM =====================
const daysSel = document.getElementById("days");
const groupSel = document.getElementById("grouping"); // former k
const refreshBtn = document.getElementById("refreshBtn");

const kpiCases = document.getElementById("kpiCases");
const kpiClusters = document.getElementById("kpiClusters");

const barCanvas = document.getElementById("barCanvas");
const barLegend = document.getElementById("barLegend");

const grid = document.getElementById("clusterGrid");
const empty = document.getElementById("emptyState");

// ================== Helpers ===================
function qs(p) {
  return new URLSearchParams(p).toString();
}
function first(...v) {
  return v.find((x) => x !== undefined && x !== null);
}
function arr(v) {
  return Array.isArray(v) ? v : v ? [v] : [];
}

function fitCanvas(cnv) {
  const ratio = window.devicePixelRatio || 1;
  cnv.width = Math.floor(cnv.clientWidth * ratio);
  cnv.height = Math.floor(parseInt(cnv.getAttribute("height"), 10) * ratio);
  const ctx = cnv.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return ctx;
}

function showErrorUI(title, desc) {
  console.error("[DASH ERROR]", title, desc || "");
  if (!empty) return;
  empty.classList.remove("hidden");
  const t = empty.querySelector(".empty-title");
  const d = empty.querySelector(".empty-desc");
  if (t) t.textContent = title || "Error";
  if (d) d.textContent = desc || "";
}

// Build a descriptive title from top symptoms when API gives a generic label
function titleFromSymptoms(symptoms) {
  const clean = (symptoms || []).map((s) => String(s).trim()).filter(Boolean);
  if (!clean.length) return null;
  // take up to 3 top tokens; join with “ • ”
  return clean.slice(0, 3).join(" • ");
}

// ================= Fetch / Normalize =================
async function fetchClusters() {
  const q = { days: (daysSel && daysSel.value) || "30" };

  // Grouping -> only send numeric; never send "auto"
  const gVal = groupSel && groupSel.value;
  if (gVal && /^[0-9]+$/.test(gVal)) q.k = gVal;

  const url = `${END_CLUSTERS}?${qs(q)}`;
  console.log("[REQ] /symptoms/clusters ->", url);

  const res = await fetch(url, { headers: { Accept: "application/json" } });
  const text = await res.text();

  let json;
  try {
    json = text ? JSON.parse(text) : {};
  } catch (e) {
    throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 200)}`);
  }

  if (!res.ok) throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
  console.log("[RES] clusters payload:", json);
  return json;
}

function normalizeMeta(payload, clustersList = []) {
  const meta = payload.meta || {};

  // Try all common field names for total cases
  let cases = first(
    meta.total_cases,
    meta.total_events,
    payload.total_events,
    payload.events,
    meta.events
  );

  // Fallback: sum the per-cluster counts
  if (cases == null || Number.isNaN(cases)) {
    cases = clustersList.reduce((acc, c) => acc + (c.cases || 0), 0);
  }

  // Prefer the actual list length if we have it
  const clusters = clustersList.length || first(meta.active_clusters, 0);

  return {
    cases: Number(cases) || 0,
    clusters,
    _rawCount: clustersList.length,
  };
}

function normalizeClusters(payload) {
  const rawList =
    payload.clusters ||
    (payload.data && payload.data.clusters) ||
    (payload.result && payload.result.clusters) ||
    [];
  const L = Array.isArray(rawList) ? rawList : [];

  return L.map((c, i) => {
    const apiTitle = first(c.title_en, c.title, c.name);
    const symptoms = arr(
      first(c.top_symptoms_en, c.top_symptoms, c.tokens, c.keywords)
    );
    const derivedTitle =
      apiTitle || titleFromSymptoms(symptoms) || `Cluster ${i + 1}`;

    const label =
      derivedTitle.length > 42 ? derivedTitle.slice(0, 40) + "…" : derivedTitle;
    const cases = first(c.events, c.size, c.count, 0);

    const specialties = arr(
      first(
        c.suggested_specialties_en,
        c.suggested_specialties,
        c.top_specialties,
        c.specialties
      )
    );
    const examples = arr(first(c.example_notes_en, c.examples, c.samples));

    return {
      id: c.id || `c_${i + 1}`,
      title: derivedTitle,
      label,
      cases,
      symptoms,
      specialties,
      examples,
    };
  });
}

// ================= Rendering =================
function renderKPIs(meta) {
  if (kpiCases) kpiCases.textContent = meta.cases ?? "—";
  if (kpiClusters) kpiClusters.textContent = meta.clusters ?? "—";
}

/* Vertical bar chart: X = clusters, Y = case count */
function renderBar(clusters) {
  if (!barCanvas) return;
  const ctx = fitCanvas(barCanvas);
  ctx.clearRect(0, 0, barCanvas.width, barCanvas.height);

  const top = [...clusters].sort((a, b) => b.cases - a.cases).slice(0, 6);
  if (!top.length) {
    if (barLegend) barLegend.innerHTML = "";
    return;
  }

  // chart area
  const padding = { top: 20, right: 20, bottom: 64, left: 48 };
  const W = barCanvas.clientWidth - padding.left - padding.right;
  const H =
    barCanvas.height / (window.devicePixelRatio || 1) -
    padding.top -
    padding.bottom;

  const maxVal = Math.max(...top.map((t) => t.cases), 1);
  const barGap = 12;
  const barWidth = Math.max(
    20,
    Math.floor((W - (top.length - 1) * barGap) / top.length)
  );

  ctx.font = "12px system-ui";
  ctx.fillStyle = "#9fb0d0";
  ctx.textAlign = "center";

  top.forEach((c, i) => {
    const x = padding.left + i * (barWidth + barGap);
    const h = Math.max(2, Math.round((c.cases / maxVal) * (H - 20)));
    const y = padding.top + (H - h);

    // bar
    ctx.fillStyle = "#2f6fec";
    ctx.fillRect(x, y, barWidth, h);

    // value above bar
    ctx.fillStyle = "#e9eef9";
    ctx.textBaseline = "bottom";
    ctx.fillText(String(c.cases), x + barWidth / 2, y - 4);

    // label (cluster title) below bar
    ctx.fillStyle = "#9fb0d0";
    ctx.textBaseline = "top";
    const label = c.label;
    // wrap-ish: break long labels into two lines
    const mid = Math.floor(label.length / 2);
    const breakAt = label.indexOf(" ", mid) > 0 ? label.indexOf(" ", mid) : mid;
    const l1 = label.slice(0, breakAt).trim();
    const l2 = label.slice(breakAt).trim();
    ctx.fillText(l1, x + barWidth / 2, padding.top + H + 10);
    if (l2) ctx.fillText(l2, x + barWidth / 2, padding.top + H + 24);
  });

  if (barLegend) {
    barLegend.innerHTML = top
      .map((c) => `<span class="pill">${c.label}</span>`)
      .join("");
  }
}

function makeChip(text) {
  const el = document.createElement("span");
  el.className = "chip";
  el.textContent = text;
  return el;
}

function renderClusterCard(c) {
  const card = document.createElement("div");
  card.className = "card cluster-card";

  // header
  const head = document.createElement("div");
  head.className = "cluster-head";
  const t = document.createElement("div");
  t.className = "cluster-title";
  t.textContent = c.title;
  const b = document.createElement("div");
  b.className = "badge";
  b.textContent = `${c.cases} cases`;
  head.append(t, b);
  card.append(head);

  // symptoms chips
  if (c.symptoms.length) {
    const lbl = document.createElement("div");
    lbl.className = "row-label";
    lbl.textContent = "Top symptoms";
    const chips = document.createElement("div");
    chips.className = "chips";
    c.symptoms.slice(0, 6).forEach((s) => chips.append(makeChip(s)));
    if (c.symptoms.length > 6)
      chips.append(makeChip(`+${c.symptoms.length - 6} more`));
    card.append(lbl, chips);
  }

  // specialties chips
  if (c.specialties.length) {
    const lbl = document.createElement("div");
    lbl.className = "row-label";
    lbl.textContent = "Suggested specialties";
    const chips = document.createElement("div");
    chips.className = "chips";
    c.specialties.slice(0, 4).forEach((s) => chips.append(makeChip(s)));
    if (c.specialties.length > 4)
      chips.append(makeChip(`+${c.specialties.length - 4} more`));
    card.append(lbl, chips);
  }

  // raw example cases
  if (c.examples.length) {
    const div = document.createElement("div");
    div.className = "divider";
    const lbl = document.createElement("div");
    lbl.className = "row-label";
    lbl.textContent = "Example patient notes";
    const box = document.createElement("div");
    c.examples.slice(0, 3).forEach((e) => {
      const p = document.createElement("div");
      p.className = "example";
      p.textContent = e;
      box.append(p);
    });
    card.append(div, lbl, box);
  }

  return card;
}

function renderClusters(list) {
  grid.innerHTML = "";
  if (!list.length) {
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  list.forEach((c) => grid.appendChild(renderClusterCard(c)));
}

// ================== Load Flow ==================
async function load() {
  try {
      const payload  = await fetchClusters();
    const clusters = normalizeClusters(payload);          // compute clusters first
    const meta     = normalizeMeta(payload, clusters); 

    renderKPIs(meta);
    renderBar(clusters);
    renderClusters(clusters);

    if (!meta._rawCount) {
      showErrorUI(
        "No symptom clusters found",
        "Try expanding the date range or adjusting the grouping."
      );
    }
  } catch (err) {
    showErrorUI("Could not load data", err?.message || String(err));
  }
}

// ================== Events =====================
if (refreshBtn)
  refreshBtn.addEventListener("click", (e) => {
    e.preventDefault();
    load();
  });
if (daysSel) daysSel.addEventListener("change", () => load());
if (groupSel) groupSel.addEventListener("change", () => load());

window.addEventListener("load", () => load());
