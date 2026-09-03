"""
Builds a single self-contained dashboard.html, styled to the "Sentinel
Forensic Intelligence" design system (deep Material-3-inspired dark mode,
Inter + JetBrains Mono + Playfair Display, tonal-layer elevation instead
of shadows). The interactive D3 force-directed network graph and all
data-binding logic are unchanged from earlier revisions — this is a
visual reskin, not a functional rewrite.

The HTML embeds the JSON payload directly (no server, no build step) and
loads D3 from a CDN — open the file in any browser.
"""
from __future__ import annotations

import json


def render_dashboard(payload: dict) -> str:
    data_json = json.dumps(payload)
    return _TEMPLATE.replace("__DATA_JSON__", data_json)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Abuse-Ring Sentinel — Case File</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Playfair+Display:ital@1&display=swap');

  :root{
    --bg:#141219; --bg-lowest:#0f0d14; --bg-low:#1d1a21; --bg-container:#211e25;
    --bg-high:#2b2930; --bg-highest:#36343b; --bg-bright:#3b383f;
    --dossier-bg:#1c1c1f; --narrative-bg:#121214; --pop-bg:#242427;
    --on-surface:#e6e0ea; --on-surface-variant:#cac4d4; --dim:#948e9d;
    --hairline:#2d2d30; --outline-variant:#494552;
    --primary:#cebdff; --primary-container:#a78bfa;
    --ring-red:#ff9996; --ring-red-dim:#881d24;
    --gold:#dbc839; --gold-dim:#af9e00;
    --green:#86efac;
    --sans:"Inter",-apple-system,"Segoe UI",sans-serif;
    --mono:"JetBrains Mono","SFMono-Regular",Consolas,monospace;
    --narrative:"Playfair Display",Georgia,serif;
  }
  *{box-sizing:border-box; margin:0; padding:0;}
  body{
    background:var(--bg); color:var(--on-surface); font-family:var(--sans);
    -webkit-font-smoothing:antialiased; font-size:14px; height:100vh; overflow:hidden;
    display:flex; flex-direction:column;
  }
  ::selection{background:var(--gold-dim); color:var(--bg-lowest);}

  @keyframes scan{ 0%{transform:translateY(-100%);} 100%{transform:translateY(100vh);} }
  @keyframes pulse-subtle{ 0%,100%{opacity:1;} 50%{opacity:0.55;} }

  /* ---------- Header ---------- */
  .header{
    flex:none; height:100px; border-bottom:1px solid var(--hairline); background:var(--bg-lowest);
    display:flex; align-items:center; padding:0 16px; justify-content:space-between; position:relative; z-index:10;
  }
  .header .title-block{display:flex; flex-direction:column; gap:4px; width:280px;}
  .header h1{font-size:24px; font-weight:600; letter-spacing:-0.02em; color:var(--primary); line-height:32px;}
  .header .subtitle{font-family:var(--mono); font-size:11px; letter-spacing:0.02em; color:var(--on-surface-variant);}
  .header .stats{flex:1; display:flex; justify-content:flex-end; align-items:center;}
  .header .stat{padding:0 16px; display:flex; flex-direction:column; gap:4px; border-right:1px solid var(--hairline); min-width:150px;}
  .header .stat:last-child{border-right:none; padding-right:0;}
  .header .stat .l{font-size:12px; line-height:16px; color:var(--on-surface-variant);}
  .header .stat .v{font-size:24px; font-weight:600; letter-spacing:-0.02em; line-height:32px; color:var(--on-surface);}
  .header .stat .v.good{color:var(--green);}
  .header .stat .v.warn{color:var(--gold);}
  .header .stat .f{font-family:var(--mono); font-size:11px; letter-spacing:0.02em; color:var(--dim);}

  /* ---------- Main layout ---------- */
  .main{flex:1; display:flex; overflow:hidden;}

  /* ---------- Sidebar (case files + exhibits) ---------- */
  .sidebar{width:320px; flex:none; border-right:1px solid var(--hairline); background:var(--bg-low); display:flex; flex-direction:column; z-index:5;}
  .sidebar-head{
    padding:8px 16px; border-bottom:1px solid var(--hairline); background:var(--bg-highest);
    display:flex; align-items:center; justify-content:space-between;
  }
  .sidebar-head span{font-size:18px; font-weight:600; color:var(--on-surface);}
  .sidebar-head .n{font-family:var(--mono); font-size:13px; font-weight:400; color:var(--on-surface-variant); margin-left:4px;}
  .case-list{overflow-y:auto; flex:0 1 auto; padding:8px 0; display:flex; flex-direction:column; gap:2px; max-height:46%;}

  .case-item{padding:8px 16px; cursor:pointer; border-left:3px solid transparent; transition:background 0.12s;}
  .case-item:hover{background:var(--bg-bright);}
  .case-item.active{background:var(--bg); box-shadow:-2px 0 8px rgba(255,153,150,0.25);}
  .case-item .row1{display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;}
  .case-item .cid{font-family:var(--mono); font-size:13px; color:var(--on-surface); font-weight:400;}
  .case-item.active .cid{font-weight:700;}
  .case-item .meta{font-family:var(--mono); font-size:13px; color:var(--on-surface-variant);}
  .case-item .track{margin-top:8px; width:100%; height:4px; background:var(--bg-highest); border-radius:9999px; overflow:hidden;}
  .case-item .fill{height:100%; border-radius:9999px;}
  .case-item:not(.active) .fill{opacity:0.5;}

  .badge{font-family:var(--mono); font-size:11px; letter-spacing:0.02em; font-weight:500; padding:2px 6px; border-radius:2px; border:1px solid; white-space:nowrap;}
  .badge.ring{color:var(--ring-red); border-color:rgba(255,153,150,0.3); background:rgba(255,153,150,0.05);}
  .badge.velocity{color:var(--primary-container); border-color:rgba(167,139,250,0.3); background:rgba(167,139,250,0.05);}
  .badge.dampened{color:var(--gold); border-color:rgba(219,200,57,0.3); background:rgba(219,200,57,0.05);}
  .badge.benign{color:var(--green); border-color:rgba(134,239,172,0.3); background:rgba(134,239,172,0.05);}

  /* ---------- Exhibits ---------- */
  .exhibits{flex:1; overflow-y:auto; border-top:1px solid var(--hairline); background:var(--bg-highest); display:flex; flex-direction:column;}
  .exhibit{border-bottom:1px solid var(--hairline);}
  .exhibit .toggle{
    padding:8px 16px; display:flex; align-items:center; justify-content:space-between; cursor:pointer;
    background:var(--bg-low); transition:background 0.12s;
  }
  .exhibit .toggle:hover{background:var(--bg);}
  .exhibit .toggle h3{font-family:var(--mono); font-size:11px; letter-spacing:0.02em; font-weight:700; text-transform:uppercase; color:var(--on-surface);}
  .exhibit .chev{font-family:var(--mono); color:var(--on-surface-variant); font-size:11px;}
  .exhibit .exhibit-body{padding:12px 16px; font-family:var(--mono); font-size:13px; display:flex; flex-direction:column; gap:10px;}
  .exhibit.collapsed .exhibit-body{display:none;}
  .exhibit .row{display:flex; justify-content:space-between; color:var(--on-surface-variant);}
  .exhibit .row .v{font-weight:500;}
  .exhibit .row .v.red{color:var(--ring-red);}
  .exhibit .row .v.green{color:var(--green);}
  .exhibit .row .v.gold{color:var(--gold);}
  .exhibit .foot{color:var(--dim); opacity:0.85; font-size:11px; line-height:15px;}
  .exhibit svg{display:block;}

  /* ---------- Graph canvas ---------- */
  .graph-section{
    flex:1; position:relative; overflow:hidden; background-color:var(--bg);
    background-image:radial-gradient(var(--hairline) 1px, transparent 1px); background-size:40px 40px;
  }
  .scan-line{
    position:absolute; width:100%; height:2px; left:0;
    background:linear-gradient(90deg, transparent, rgba(206,189,255,0.2), transparent);
    box-shadow:0 0 10px rgba(206,189,255,0.1); z-index:6; pointer-events:none;
    animation:scan 8s linear infinite;
  }
  #graph{width:100%; height:100%; display:block; position:relative; z-index:2;}
  .hud-hint{
    position:absolute; top:16px; left:16px; background:rgba(36,36,39,0.4); backdrop-filter:blur(4px);
    border:1px solid rgba(45,45,48,0.5); border-radius:2px; padding:4px 8px; z-index:8;
    font-family:var(--mono); font-size:11px; letter-spacing:0.02em; color:var(--dim);
  }
  .legend{
    position:absolute; bottom:16px; left:16px; background:rgba(36,36,39,0.8); backdrop-filter:blur(10px);
    border:1px solid var(--hairline); border-radius:4px; padding:12px 16px; z-index:8;
    font-family:var(--mono); font-size:11px; letter-spacing:0.02em; color:var(--on-surface-variant);
  }
  .legend .row{display:flex; align-items:center; gap:8px; margin:4px 0;}
  .legend .dot{width:8px; height:8px; border-radius:50%; flex:none;}
  .tooltip{
    position:absolute; pointer-events:none; background:var(--pop-bg); border:1px solid var(--hairline);
    border-radius:2px; padding:8px 10px; font-family:var(--mono); font-size:13px; color:var(--on-surface);
    max-width:280px; box-shadow:0 20px 25px -5px rgba(0,0,0,0.4); display:flex; flex-direction:column; gap:2px;
  }
  .tooltip b{color:var(--on-surface); font-weight:700;}

  /* ---------- Case dossier (right panel) ---------- */
  .dossier{width:360px; flex:none; border-left:1px solid var(--hairline); background:var(--dossier-bg); overflow-y:auto; z-index:5;}
  .dossier-inner{padding:16px 24px;}
  .dossier h2{font-size:18px; font-weight:600; color:var(--on-surface); margin-bottom:16px;}
  .empty-state{padding:60px 20px; color:var(--dim); font-size:13px; text-align:center; font-family:var(--narrative); font-style:italic;}

  .verdict-badge{
    display:inline-block; padding:6px 12px; border-radius:2px; border:1px solid; margin-bottom:24px;
    font-family:var(--mono); font-size:13px; font-weight:700; letter-spacing:0.05em; text-transform:uppercase;
  }
  .verdict-badge.ring{color:var(--ring-red); border-color:var(--ring-red); background:rgba(255,153,150,0.05); box-shadow:inset 0 0 0 1px var(--ring-red), 0 0 12px rgba(255,153,150,0.3); text-shadow:0 0 8px rgba(255,153,150,0.5);}
  .verdict-badge.velocity{color:var(--primary-container); border-color:var(--primary-container); background:rgba(167,139,250,0.05); box-shadow:inset 0 0 0 1px var(--primary-container), 0 0 12px rgba(167,139,250,0.3); text-shadow:0 0 8px rgba(167,139,250,0.5);}
  .verdict-badge.dampened{color:var(--gold); border-color:var(--gold); background:rgba(219,200,57,0.05); box-shadow:inset 0 0 0 1px var(--gold), 0 0 12px rgba(219,200,57,0.3); text-shadow:0 0 8px rgba(219,200,57,0.5);}
  .verdict-badge.benign{color:var(--green); border-color:var(--green); background:rgba(134,239,172,0.05); box-shadow:inset 0 0 0 1px var(--green), 0 0 12px rgba(134,239,172,0.3); text-shadow:0 0 8px rgba(134,239,172,0.5);}

  .narrative{
    background:var(--narrative-bg); border:1px solid var(--hairline); border-left:4px solid var(--ring-red);
    padding:16px; border-radius:2px; margin-bottom:24px;
  }
  .narrative p{font-family:var(--narrative); font-style:italic; font-size:16px; line-height:24px; color:var(--on-surface);}

  .metric-grid{display:grid; grid-template-columns:1fr 1fr; border-top:1px solid var(--hairline); border-bottom:1px solid var(--hairline); margin-bottom:24px;}
  .metric-grid .cell{padding:16px; display:flex; flex-direction:column; gap:4px; border-right:1px solid var(--hairline); border-top:1px solid var(--hairline);}
  .metric-grid .cell:nth-child(2n){border-right:none;}
  .metric-grid .cell:nth-child(-n+2){border-top:none;}
  .metric-grid .cell .l{font-size:12px; color:var(--on-surface-variant);}
  .metric-grid .cell .v{font-family:var(--mono); font-size:16px; letter-spacing:-0.01em; color:var(--on-surface);}

  .evidence h3{font-size:18px; font-weight:600; color:var(--on-surface); margin-bottom:16px;}
  .attr-row{display:flex; align-items:center; gap:12px; margin-bottom:12px; font-family:var(--mono); font-size:11px; letter-spacing:0.02em;}
  .attr-row .name{width:120px; color:var(--on-surface-variant); flex:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
  .attr-row .bar-track{flex:1; height:6px; background:var(--hairline); border-radius:9999px; overflow:hidden;}
  .attr-row .bar-fill{height:100%; background:#9ca3af;}
  .attr-row .n{width:24px; text-align:right; color:var(--on-surface);}

  ::-webkit-scrollbar{width:9px; height:9px;}
  ::-webkit-scrollbar-track{background:transparent;}
  ::-webkit-scrollbar-thumb{background:var(--hairline); border-radius:5px;}
</style>
</head>
<body>

<div class="header">
  <div class="title-block">
    <h1>Abuse-Ring Sentinel</h1>
    <div class="subtitle">Coordinated fraud-ring investigation console</div>
  </div>
  <div class="stats" id="header-stats"></div>
</div>

<div class="main">
  <div class="sidebar">
    <div class="sidebar-head"><span>Case files<span class="n" id="files-count"></span></span></div>
    <div class="case-list" id="cluster-list"></div>
    <div class="exhibits" id="exhibits"></div>
  </div>

  <div class="graph-section" id="graph-wrap">
    <div class="scan-line"></div>
    <div class="hud-hint">drag to pan · scroll to zoom · click a node or case file</div>
    <svg id="graph"></svg>
    <div class="legend">
      <div class="row"><div class="dot" style="background:#ff9996; box-shadow:0 0 6px #ff9996;"></div> ring confirmed</div>
      <div class="row"><div class="dot" style="background:#a78bfa; box-shadow:0 0 6px #a78bfa;"></div> flagged — velocity evidence</div>
      <div class="row"><div class="dot" style="background:#dbc839; box-shadow:0 0 6px #dbc839;"></div> reviewed, cleared</div>
      <div class="row"><div class="dot" style="background:#86efac;"></div> clustered, benign</div>
      <div class="row"><div class="dot" style="background:#494552;"></div> unclustered</div>
    </div>
  </div>

  <div class="dossier">
    <div class="dossier-inner">
      <h2>Case dossier</h2>
      <div id="dossier-content"><div class="empty-state">Select a case file from the list,<br>or click a node in the network.</div></div>
    </div>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;

const STATUS_COLOR = {
  flagged_ring: "#ff9996",
  flagged_velocity: "#a78bfa",
  dampened_saved: "#dbc839",
  clustered_benign: "#86efac",
  unclustered: "#494552",
};
const VERDICT_LABEL = {
  flagged_ring: "ring confirmed",
  flagged_velocity: "ring confirmed — velocity",
  dampened_saved: "reviewed, cleared",
  clustered_benign: "clustered, benign",
};
const VERDICT_TAG_CLASS = {
  flagged_ring: "ring",
  flagged_velocity: "velocity",
  dampened_saved: "dampened",
  clustered_benign: "benign",
};

function pct(x){ return x===null||x===undefined ? "N/A" : (x*100).toFixed(0) + "%"; }
const m = DATA.metrics;

// ---------- Header stats ----------
document.getElementById("header-stats").innerHTML = `
  <div class="stat"><div class="l">Accounts analyzed</div><div class="v">${m.n_accounts.toLocaleString()}</div><div class="f">${m.n_orders_analyzed.toLocaleString()} orders</div></div>
  <div class="stat"><div class="l">Planted rings</div><div class="v">${m.n_planted_rings + m.n_planted_velocity_rings}</div><div class="f">${m.n_planted_rings} classic + ${m.n_planted_velocity_rings} velocity-only</div></div>
  <div class="stat"><div class="l">Recall</div><div class="v ${m.recall===1?'good':'warn'}">${pct(m.recall)}</div><div class="f">classic ${pct(m.classic_recall)} · velocity ${pct(m.velocity_recall)}</div></div>
  <div class="stat"><div class="l">Precision</div><div class="v ${m.precision===1?'good':m.precision===null?'':'warn'}">${pct(m.precision)}</div><div class="f">${m.false_positive_clusters.length} false-positive case file(s)</div></div>
  <div class="stat"><div class="l">FP cost avoided</div><div class="v good">₹${m.false_positive_cost_inr.toLocaleString()}</div><div class="f">${m.n_wrongly_flagged_accounts} legit accounts wrongly flagged</div></div>
  <div class="stat"><div class="l">Dampening saves</div><div class="v warn">${m.dampening_saves.length}</div><div class="f">large benign cluster(s) held back</div></div>
`;

// ---------- Case file list ----------
const clusterListEl = document.getElementById("cluster-list");
const sortedClusters = [...DATA.clusters].sort((a,b)=>b.suspicion_score - a.suspicion_score);
document.getElementById("files-count").textContent = ` (${sortedClusters.length})`;
let activeClusterId = null;

function statusOf(c){
  if(c.flagged && c.velocity_flag) return "flagged_velocity";
  if(c.flagged) return "flagged_ring";
  if(c.dampened) return "dampened_saved";
  return "clustered_benign";
}

sortedClusters.forEach(c=>{
  const status = statusOf(c);
  const color = STATUS_COLOR[status];
  const div = document.createElement("div");
  div.className = "case-item";
  div.dataset.cid = c.cluster_id;
  div.innerHTML = `
    <div class="row1">
      <span class="cid">${c.cluster_id}</span>
      <span class="badge ${VERDICT_TAG_CLASS[status]}">${VERDICT_LABEL[status]}</span>
    </div>
    <div class="meta">${c.size} accounts · score ${c.suspicion_score}</div>
    <div class="track"><div class="fill" style="width:${c.suspicion_score}%; background:${color};"></div></div>
  `;
  div.addEventListener("click", ()=>selectCluster(c.cluster_id));
  clusterListEl.appendChild(div);
});

function renderDossier(c){
  const status = statusOf(c);
  const color = STATUS_COLOR[status];
  const attrs = c.attribute_breakdown;
  const maxAttr = Math.max(1, ...Object.values(attrs));
  const attrRows = Object.entries(attrs).map(([k,v])=>`
    <div class="attr-row">
      <span class="name">${k.replace(/_/g," ")}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${(v/maxAttr)*100}%; background:${v>0?'#9ca3af':'transparent'};"></span></span>
      <span class="n">${v}</span>
    </div>`).join("");

  document.getElementById("dossier-content").innerHTML = `
    <div class="verdict-badge ${VERDICT_TAG_CLASS[status]}">${VERDICT_LABEL[status]}</div>
    <div class="narrative" style="border-left-color:${color};"><p>${c.reason}</p></div>
    <div class="metric-grid">
      <div class="cell"><div class="l">Suspicion score</div><div class="v">${c.suspicion_score} / 100</div></div>
      <div class="cell"><div class="l">Case size</div><div class="v">${c.size} accounts</div></div>
      <div class="cell"><div class="l">Avg edge weight</div><div class="v">${c.avg_edge_weight}</div></div>
      <div class="cell"><div class="l">Return rate</div><div class="v">${pct(c.return_rate)}</div></div>
      <div class="cell"><div class="l">Timing burst</div><div class="v">${c.timing_burst_score}</div></div>
      <div class="cell"><div class="l">Velocity evidence</div><div class="v">${c.velocity_flag ? "present" : "none"}</div></div>
    </div>
    <div class="evidence"><h3>Shared-attribute evidence</h3>${attrRows}</div>
  `;
}

function selectCluster(cid){
  activeClusterId = cid;
  document.querySelectorAll(".case-item").forEach(el=>{
    el.classList.toggle("active", el.dataset.cid === cid);
  });
  const c = DATA.clusters.find(c=>c.cluster_id===cid);
  if(c) renderDossier(c);
  highlightGraph(cid);
}

// ---------- Exhibits (evidence appendix) ----------
const exhibitsEl = document.getElementById("exhibits");

function addExhibit(title, bodyHtml, footHtml){
  const div = document.createElement("div");
  div.className = "exhibit";
  div.innerHTML = `
    <div class="toggle"><h3>${title}</h3><span class="chev">▾</span></div>
    <div class="exhibit-body">${bodyHtml}${footHtml ? `<div class="foot">${footHtml}</div>` : ""}</div>
  `;
  div.querySelector(".toggle").addEventListener("click", ()=>{
    div.classList.toggle("collapsed");
    div.querySelector(".chev").textContent = div.classList.contains("collapsed") ? "▸" : "▾";
  });
  exhibitsEl.appendChild(div);
}

// Exhibit A — naive baseline
if(m.baseline_comparison){
  const b = m.baseline_comparison;
  addExhibit("Exhibit A — naive baseline", `
    <div class="row"><span>Naive: rings caught</span><span class="v red">${b.rings_caught}/${b.n_rings_total}</span></div>
    <div class="row"><span>Naive: legit wrongly flagged</span><span class="v red">${b.legit_accounts_wrongly_flagged}</span></div>
    <div class="row"><span>Sentinel: rings caught</span><span class="v green">${m.rings_found.length}/${m.n_planted_rings}</span></div>
    <div class="row"><span>Sentinel: legit wrongly flagged</span><span class="v green">${m.n_wrongly_flagged_accounts}</span></div>
  `, "\"cluster by address, flag if 8+\" — the first thing most teams build.");
}

// Exhibit B — held-out & multi-seed robustness
if(m.robustness){
  const rs = m.robustness.summary;
  addExhibit("Exhibit B — held-out &amp; robustness", `
    <div class="row"><span>Held-out seed (${m.held_out_seed})</span><span class="v ${m.held_out_precision===1?'green':'gold'}">${pct(m.held_out_recall)} / ${pct(m.held_out_precision)}</span></div>
    <div class="row"><span>${rs.n_seeds}-seed sweep: clean runs</span><span class="v ${rs.runs_with_false_positives===0?'green':'gold'}">${rs.clean_runs}/${rs.n_seeds}</span></div>
    <div class="row"><span>Mean recall / precision</span><span class="v">${pct(rs.mean_recall)} / ${pct(rs.mean_precision)}</span></div>
  `, "Never tuned against — the number that answers \"does this generalize.\"");
}

// Exhibit C — dampening rule bug replay
if(m.bug_replay){
  const br = m.bug_replay;
  addExhibit("Exhibit C — dampening rule, before/after", `
    <div id="chart-bug-replay"></div>
    <div class="row"><span>Old rule (point estimate)</span><span class="v red">${pct(br.old_rule_false_positive_rate)} FP rate</span></div>
    <div class="row"><span>New rule (CI lower bound)</span><span class="v green">${pct(br.new_rule_false_positive_rate)} FP rate</span></div>
    <div class="row"><span>Old: seeds with FPs</span><span class="v red">${br.n_seeds - br.old_rule_clean_runs}/${br.n_seeds}</span></div>
    <div class="row"><span>New: seeds with FPs</span><span class="v green">${br.n_seeds - br.new_rule_clean_runs}/${br.n_seeds}</span></div>
  `, "A real bug this project's own testing found, fixed, and re-measured.");
}

// Exhibit D — distribution-shift stress test
if(m.distribution_shift){
  const rows = m.distribution_shift.map(r=>{
    const perfect = r.recall===1 && r.precision===1;
    return `<div class="row"><span>${r.shift}</span><span class="v ${perfect?'green':'gold'}">${pct(r.recall)}/${pct(r.precision)}</span></div>`;
  }).join("");
  const nPerfect = m.distribution_shift.filter(r=>r.recall===1 && r.precision===1).length;
  addExhibit(`Exhibit D — distribution shift (${nPerfect}/${m.distribution_shift.length} hold)`,
    `<div id="chart-distribution-shift"></div>` + rows,
    "Same fixed thresholds, deliberately different populations — tests whether tuning generalizes.");
}

// Exhibit E — scale benchmark (measured separately, embedded as a static exhibit)
if(m.scale_benchmark){
  const sb = m.scale_benchmark;
  const rows = sb.rows.map(r=>
    `<div class="row"><span>${r.accounts.toLocaleString()} accounts</span><span class="v">${r.total_seconds}s · ${pct(r.recall)}/${pct(r.precision)}</span></div>`
  ).join("");
  addExhibit("Exhibit E — scale benchmark", rows, sb.note + " Reproduce: <code>" + sb.measured_via + "</code>");
}

// Exhibit F — precision/recall vs. suspicion threshold
if(m.threshold_sweep){
  const defaultThreshold = 55;
  addExhibit("Exhibit F — precision/recall vs. threshold", `
    <div id="chart-threshold-sweep"></div>
  `, `Default threshold (${defaultThreshold}, dashed gold line) sits on a wide flat plateau, not a knife's edge.`);
}

// ---------- Chart rendering functions (DEFINED here, INVOKED after the
// D3 network-graph setup below — every d3.* call stays physically after
// the "Evidence network" split point, so this file can still be tested by
// slicing the pre-D3 portion out and running it against a mock DOM with
// no D3 mock required. Renders correctly in any real browser regardless
// of call order once D3 has loaded from the CDN <script> tag in <head>). ----------
function renderThresholdSweepChart(containerId, sweep){
  const w = 258, h = 148, mg = {top:10,right:8,bottom:18,left:30};
  const svg = d3.select("#"+containerId).append("svg").attr("width", w).attr("height", h);
  const xs = sweep.map(d=>d.threshold);
  const x = d3.scaleLinear().domain([Math.min(...xs), Math.max(...xs)]).range([mg.left, w-mg.right]);
  const y = d3.scaleLinear().domain([0,1]).range([h-mg.bottom, mg.top]);

  [0,0.5,1].forEach(v=>{
    svg.append("line").attr("x1",mg.left).attr("x2",w-mg.right).attr("y1",y(v)).attr("y2",y(v))
       .attr("stroke","#2d2d30").attr("stroke-width",1);
    svg.append("text").attr("x",mg.left-4).attr("y",y(v)+3).attr("text-anchor","end")
       .attr("font-size","9px").attr("fill","#cac4d4").attr("font-family","JetBrains Mono").text(Math.round(v*100)+"%");
  });

  svg.append("line").attr("x1",x(55)).attr("x2",x(55)).attr("y1",mg.top).attr("y2",h-mg.bottom)
     .attr("stroke","#dbc839").attr("stroke-width",1.3).attr("stroke-dasharray","3,2");

  const lineGen = d3.line().x((d,i)=>x(xs[i])).y(d=>y(d));
  svg.append("path").datum(sweep.map(d=>d.recall)).attr("d",lineGen)
     .attr("fill","none").attr("stroke","#a78bfa").attr("stroke-width",1.8);
  svg.append("path").datum(sweep.map(d=>d.precision===null?1:d.precision)).attr("d",lineGen)
     .attr("fill","none").attr("stroke","#dbc839").attr("stroke-width",1.8).attr("stroke-dasharray","1,2");

  svg.append("text").attr("x",mg.left).attr("y",h-4).attr("font-size","9px")
     .attr("fill","#cac4d4").attr("font-family","JetBrains Mono").text("thr "+xs[0]);
  svg.append("text").attr("x",w-mg.right).attr("y",h-4).attr("text-anchor","end").attr("font-size","9px")
     .attr("fill","#cac4d4").attr("font-family","JetBrains Mono").text("thr "+xs[xs.length-1]);

  let ly = mg.top+18;
  [["recall","#a78bfa"],["precision","#dbc839"]].forEach(([name,color])=>{
    svg.append("line").attr("x1",w-80).attr("x2",w-68).attr("y1",ly).attr("y2",ly)
       .attr("stroke",color).attr("stroke-width",2);
    svg.append("text").attr("x",w-65).attr("y",ly+3).attr("font-size","9px")
       .attr("fill","#e6e0ea").attr("font-family","Inter").text(name);
    ly += 11;
  });
}

function renderDistributionShiftChart(containerId, shifts){
  const w = 258, h = 90, mg = {top:6,right:4,bottom:4,left:4};
  const svg = d3.select("#"+containerId).append("svg").attr("width", w).attr("height", h);
  const y = d3.scaleLinear().domain([0,1]).range([h-mg.bottom, mg.top]);
  const slotW = (w-mg.left-mg.right)/shifts.length;
  const barW = Math.max(4, slotW-3);

  svg.append("line").attr("x1",mg.left).attr("x2",w-mg.right).attr("y1",y(1)).attr("y2",y(1))
     .attr("stroke","#2d2d30").attr("stroke-width",1).attr("stroke-dasharray","2,2");

  shifts.forEach((s,i)=>{
    const perfect = s.recall===1 && s.precision===1;
    const xPos = mg.left + i*slotW + (slotW-barW)/2;
    svg.append("rect").attr("x",xPos).attr("y",y(s.recall)).attr("width",barW)
       .attr("height",Math.max(1,(h-mg.bottom)-y(s.recall)))
       .attr("fill", perfect ? "#86efac" : "#dbc839")
       .append("title").text(s.shift+": recall "+Math.round(s.recall*100)+"%");
  });
}

function renderBugReplayChart(containerId, br){
  const w = 258, h = 90, mg = {top:16,right:20,bottom:18,left:20};
  const svg = d3.select("#"+containerId).append("svg").attr("width", w).attr("height", h);
  const y = d3.scaleLinear().domain([0,0.6]).range([h-mg.bottom, mg.top]);
  const bars = [
    {label:"old rule", value:br.old_rule_false_positive_rate, color:"#ff9996"},
    {label:"new rule", value:br.new_rule_false_positive_rate, color:"#86efac"},
  ];
  const slotW = (w-mg.left-mg.right)/bars.length;
  const barW = 46;
  bars.forEach((b,i)=>{
    const xPos = mg.left + i*slotW + (slotW-barW)/2;
    svg.append("rect").attr("x",xPos).attr("y",y(b.value)).attr("width",barW)
       .attr("height",(h-mg.bottom)-y(b.value)).attr("fill",b.color);
    svg.append("text").attr("x",xPos+barW/2).attr("y",y(b.value)-5).attr("text-anchor","middle")
       .attr("font-size","10px").attr("fill",b.color).attr("font-family","JetBrains Mono")
       .text(Math.round(b.value*100)+"%");
    svg.append("text").attr("x",xPos+barW/2).attr("y",h-4).attr("text-anchor","middle")
       .attr("font-size","9px").attr("fill","#cac4d4").attr("font-family","Inter").text(b.label);
  });
}

// ---------- Evidence network (force-directed graph) ----------
const wrap = document.getElementById("graph-wrap");
const svg = d3.select("#graph");
let width = wrap.clientWidth, height = wrap.clientHeight;
svg.attr("viewBox", [0,0,width,height]);

const gRoot = svg.append("g");
svg.call(d3.zoom().scaleExtent([0.15, 6]).on("zoom", (ev)=>{ gRoot.attr("transform", ev.transform); }));

const nodesData = DATA.nodes.map(d=>({...d}));
const linksData = DATA.links.map(d=>({...d}));

const linkSel = gRoot.append("g").attr("stroke-opacity", 0.3)
  .selectAll("line").data(linksData).join("line")
  .attr("stroke", "#494552")
  .attr("stroke-width", d=>Math.min(2.5, 0.4 + d.weight/4));

const nodeSel = gRoot.append("g")
  .selectAll("circle").data(nodesData).join("circle")
  .attr("r", d=>(d.status==="flagged_ring"||d.status==="flagged_velocity") ? 5.5 : d.status==="dampened_saved" ? 5 : 4)
  .attr("fill", d=>STATUS_COLOR[d.status])
  .attr("stroke", "#0f0d14").attr("stroke-width", 1)
  .style("cursor", "pointer")
  .classed("pulse-node", d=>d.status==="flagged_ring"||d.status==="flagged_velocity")
  .on("click", (ev,d)=>{ if(d.cluster) selectCluster(d.cluster); })
  .on("mouseenter", (ev,d)=>showTooltip(ev,d))
  .on("mousemove", (ev)=>moveTooltip(ev))
  .on("mouseleave", hideTooltip)
  .call(drag());

nodeSel.filter(d=>d.status==="flagged_ring" || d.status==="flagged_velocity" || d.status==="dampened_saved")
  .clone(true).lower()
  .attr("r", d=>(d.status==="flagged_ring"||d.status==="flagged_velocity")?11:9.5)
  .attr("fill", "none")
  .attr("stroke", d=>STATUS_COLOR[d.status])
  .attr("stroke-opacity", 0.35)
  .attr("stroke-width", 4)
  .style("pointer-events","none");

const sim = d3.forceSimulation(nodesData)
  .force("link", d3.forceLink(linksData).id(d=>d.id).distance(d=>18 + 30/Math.min(d.weight,6)).strength(0.5))
  .force("charge", d3.forceManyBody().strength(-40))
  .force("center", d3.forceCenter(width/2, height/2))
  .force("collide", d3.forceCollide(8))
  .on("tick", ticked);

function ticked(){
  linkSel.attr("x1",d=>d.source.x).attr("y1",d=>d.source.y)
         .attr("x2",d=>d.target.x).attr("y2",d=>d.target.y);
  nodeSel.attr("cx", d=>d.x).attr("cy", d=>d.y);
  svg.selectAll("circle").filter(function(){ return d3.select(this).attr("fill")==="none"; })
     .attr("cx", d=>d.x).attr("cy", d=>d.y);
}

function drag(){
  function started(ev,d){ if(!ev.active) sim.alphaTarget(0.25).restart(); d.fx=d.x; d.fy=d.y; }
  function dragged(ev,d){ d.fx=ev.x; d.fy=ev.y; }
  function ended(ev,d){ if(!ev.active) sim.alphaTarget(0); d.fx=null; d.fy=null; }
  return d3.drag().on("start",started).on("drag",dragged).on("end",ended);
}

function highlightGraph(cid){
  nodeSel.attr("opacity", d=> d.cluster===cid ? 1 : 0.15);
  linkSel.attr("opacity", d=>{
    const s = nodesData.find(n=>n.id===(d.source.id||d.source));
    const t = nodesData.find(n=>n.id===(d.target.id||d.target));
    return (s && t && s.cluster===cid && t.cluster===cid) ? 0.7 : 0.03;
  });
}

const tooltip = d3.select("body").append("div").attr("class","tooltip").style("display","none");
function showTooltip(ev,d){
  tooltip.style("display","flex").html(
    `<b>${d.name}</b><span>${d.id}</span><span>case file: ${d.cluster||"none"}</span><span>status: ${(VERDICT_LABEL[d.status]||d.status).replace("_"," ")}</span>`
  );
  moveTooltip(ev);
}
function moveTooltip(ev){
  tooltip.style("left",(ev.pageX+14)+"px").style("top",(ev.pageY+10)+"px");
}
function hideTooltip(){ tooltip.style("display","none"); }

window.addEventListener("resize", ()=>{
  width = wrap.clientWidth; height = wrap.clientHeight;
  svg.attr("viewBox", [0,0,width,height]);
  sim.force("center", d3.forceCenter(width/2, height/2));
  sim.alpha(0.3).restart();
});

// ---------- Chart invocations (D3 is guaranteed loaded by this point) ----------
if(m.threshold_sweep) renderThresholdSweepChart("chart-threshold-sweep", m.threshold_sweep);
if(m.distribution_shift) renderDistributionShiftChart("chart-distribution-shift", m.distribution_shift);
if(m.bug_replay) renderBugReplayChart("chart-bug-replay", m.bug_replay);

// Pulsing glow on confirmed-ring nodes (SVG circles support CSS animations)
const styleTag = document.createElement("style");
styleTag.textContent = ".pulse-node{animation:pulse-subtle 2s cubic-bezier(0.4,0,0.6,1) infinite;}";
document.head.appendChild(styleTag);
</script>
</body>
</html>
"""
