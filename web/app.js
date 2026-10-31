const $ = (s) => document.querySelector(s);
const RECORD = new URLSearchParams(location.search).has("record");
const STEP_MS = RECORD ? 1000 : 700; // slower in recording mode so captions can be read
const TOUR_PAUSE_MS = RECORD ? 2500 : 1800;
const TYPES = {
  clean: "Clean run: tools have the answer",
  A: "Planted: the final answer states something no tool returned",
  B: "Planted: the agent invents a tool argument",
  C: "Planted: a tool returns nothing, the answer gives specifics anyway",
};
const PATHS = { anthropic: "Anthropic", chat: "Chat Completions", responses: "Responses API" };
const TOUR = [
  ["shoes_item_fab", "responses", "1/3 · Responses API, the final answer fabricates"],
  ["refund_wrong_real_order", "chat", "2/3 · The agent refunds an order the user never mentioned"],
  ["refund_clean", "anthropic", "3/3 · A clean run: no false alarms"],
];
let DATA, playing = false;

if (RECORD) document.body.classList.add("record");
const sleep = (ms) => new Promise((r) => setTimeout(r, matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : ms));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const ticks = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");
const path = () => document.querySelector("input[name=path]:checked").value;

function stat(label, h, key, pct) {
  const s = h[key].stock, a = h[key].adapter;
  const fmt = (v) => (pct ? `${v.pct}%` : `${v.hits}/${v.n}`);
  return `<div class="stat"><small>${label}</small>
    <b><span class="from">${fmt(s)}</span> → <span class="to">${fmt(a)}</span></b>
    <span>stock → with adapter${pct ? ` · ${a.hits}/${a.n} runs` : ""}</span></div>`;
}

function badge(name, b) {
  if (!b) return "";
  const cls = b.pending ? "pending" : b.state;
  return `<div class="badge"><small>${name}</small><em class="${cls}">${esc(b.pending ? "…" : b.label)}</em></div>`;
}

function body(s) {
  if (s.kind === "tool_call") {
    const args = Object.entries(s.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
    return `<div class="args">${esc(s.name)}(${esc(args)})</div>`;
  }
  if (s.kind === "tool_result") return `<div class="result">${esc(s.text)}</div>`;
  return `<div class="text">${esc(s.text)}</div>`;
}

const KIND = { user: "User", tool_call: "Tool call", tool_result: "Tool result", assistant_text: "Final answer" };

function renderStep(run, i, scored) {
  const s = run.steps[i];
  const scorable = s.kind === "tool_call" || s.kind === "assistant_text";
  const pend = (b) => (scored ? b : b && { ...b, pending: true });
  const firstBad = scored && run.first_bad === i;
  const li = document.createElement("li");
  li.className = "step" + (firstBad ? " first-bad" : "");
  li.innerHTML = `<div class="row"><div><div class="kind">${i + 1} · ${KIND[s.kind]}</div>${body(s)}</div>
    ${scorable ? `<div class="badges">${badge("Latent (stock)", pend(s.stock))}${badge("With adapter", pend(s.adapter))}</div>` : ""}</div>
    ${firstBad && s.reason ? `<div class="reason">${ticks(s.reason)}</div>` : ""}`;
  li.onclick = () => openDrawer(s, i);
  return li;
}

function openDrawer(s, i) {
  $("#drawer-title").textContent = `Step ${i + 1} · ${KIND[s.kind]}`;
  const notScored = s.kind === "tool_call"
    ? "Not sent. This turn only has tool calls, so auto_instrument() counts it as skipped_tool_only."
    : "This step is input, not a model answer. Nothing is scored.";
  $("#drawer-stock").textContent = s.stock?.sent || notScored;
  let a = s.adapter?.sent || "This step is input, not a model answer. Nothing is scored.";
  if (s.adapter?.latent_read != null)
    a += `\n\nLatent read of this call: ${s.adapter.latent_read} (reference only; tool calls are flagged on argument provenance)`;
  $("#drawer-adapter").textContent = a;
  $("#drawer").showModal();
}

async function play(run, caption) {
  const tl = $("#timeline");
  tl.innerHTML = "";
  $("#summary").hidden = true;
  $("#caption").textContent = caption || `${TYPES[run.type]} · ${PATHS[run.path]}`;
  for (let i = 0; i < run.steps.length; i++) {
    const li = renderStep(run, i, false);
    tl.append(li);
    li.scrollIntoView({ block: "nearest", behavior: "smooth" });
    await sleep(STEP_MS / 2);
    li.replaceWith(renderStep(run, i, true));
    await sleep(STEP_MS / 2);
  }
  $("#summary").textContent = run.summary;
  $("#summary").hidden = false;
  $("#summary").scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function guard(fn) {
  if (playing) return;
  playing = true;
  document.querySelectorAll("button.primary,button.ghost").forEach((b) => (b.disabled = true));
  try { await fn(); } finally {
    playing = false;
    document.querySelectorAll("button.primary,button.ghost").forEach((b) => (b.disabled = false));
  }
}

function select(id, p) {
  $("#scenario").value = id;
  document.querySelector(`input[name=path][value=${p}]`).checked = true;
}

$("#run").onclick = () => guard(() => play(DATA.runs[`${$("#scenario").value}|${path()}`]));
$("#tour").onclick = () => guard(async () => {
  for (const [id, p, cap] of TOUR) {
    select(id, p);
    await play(DATA.runs[`${id}|${p}`], cap);
    await sleep(TOUR_PAUSE_MS);
  }
});
$("#how-open").onclick = () => $("#how").showModal();

// Live mode: the server runs the real agent and the real Latent SDK, streaming steps over SSE.
$("#live").onclick = () => guard(() => new Promise((done) => {
  const run = { steps: [], first_bad: null, type: "", path: path() };
  $("#timeline").innerHTML = "";
  $("#summary").hidden = true;
  $("#live-pill").hidden = false;
  $("#caption").textContent = `Live run · ${PATHS[path()]}`;
  const es = new EventSource(`/api/live?scenario=${encodeURIComponent($("#scenario").value)}&path=${path()}`);
  es.addEventListener("step", (e) => {
    const s = JSON.parse(e.data);
    run.steps.push(s);
    if (run.first_bad == null && s.adapter?.state === "flag") run.first_bad = run.steps.length - 1;
    $("#timeline").append(renderStep(run, run.steps.length - 1, true));
  });
  es.addEventListener("summary", (e) => {
    $("#summary").textContent = JSON.parse(e.data).summary;
    $("#summary").hidden = false;
    es.close(); $("#live-pill").hidden = true; done();
  });
  es.onerror = () => { es.close(); $("#live-pill").hidden = true; $("#caption").textContent = "Live run failed."; done(); };
}));

(async () => {
  DATA = await (await fetch("demo_data/demo.json")).json();
  const h = DATA.headline;
  $("#stats").innerHTML = stat("Hallucinations caught", h, "caught") +
    stat("Tool-call hallucinations caught", h, "tool_caught") +
    stat("First bad step found", h, "first_bad_step", true);
  const seen = new Set();
  for (const r of Object.values(DATA.runs)) {
    if (seen.has(r.scenario)) continue;
    seen.add(r.scenario);
    $("#scenario").add(new Option(`${r.scenario.replaceAll("_", " ")} (${r.type === "clean" ? "clean" : "type " + r.type})`, r.scenario));
  }
  select("refund_wrong_real_order", "chat");
  try { if ((await (await fetch("/api/config")).json()).live) $("#live").hidden = false; } catch {}
})();
