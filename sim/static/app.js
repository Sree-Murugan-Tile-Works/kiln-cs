"use strict";
// Thin client: every number comes from the Python simulation. This file only builds the sliders
// from /api/specs, sends changes to the server, and draws what /api/state returns.

const POLL_MS = 300;
const MAX_KEPT_RECORDS = 3600;
const OPEN_GROUPS = new Set(["Weather", "Kiln gas", "Chimney"]);
const FT_PER_M = 3.28084;
const FAULT_LABELS = { none: "Normal", open: "Open circuit (8000)", stuck: "Stuck signal" };
const CHANNEL_INFO = { p1: ["P1 transmitter", "Pa"], p2: ["P2 transmitter", "Pa"], t: ["Temperature transmitter", "°C"] };

const state = { specs: [], defaults: {}, records: [], lastTime: -1, windowS: 600, hoverTime: null, serverValues: {} };
const sliders = {};          // name -> {input, valueEl, wrapper, spec}
const pending = {};          // slider changes waiting to be sent
let sendTimer = null;

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

async function api(path, body) {
  const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

let toastTimer = null;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
}

function fmt(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return Number(value).toFixed(digits);
}

function decimalsFor(step) {
  const text = String(step);
  return text.includes(".") ? text.split(".")[1].length : 0;
}

// ------------------------------------------------------------------ parameter sliders
function buildSliders() {
  const host = $("groups");
  host.innerHTML = "";
  const groups = new Map();
  for (const spec of state.specs) {
    if (!groups.has(spec.group)) groups.set(spec.group, []);
    groups.get(spec.group).push(spec);
  }
  for (const [name, specs] of groups) {
    const details = document.createElement("details");
    details.className = "group";
    details.open = OPEN_GROUPS.has(name);
    const summary = document.createElement("summary");
    summary.textContent = name;
    details.appendChild(summary);
    for (const spec of specs) details.appendChild(buildSlider(spec));
    host.appendChild(details);
  }
}

function buildSlider(spec) {
  const wrapper = document.createElement("div");
  wrapper.className = "param";
  const row = document.createElement("div");
  row.className = "row1";
  const label = document.createElement("label");
  label.className = "name";
  label.textContent = spec.label;
  const valueEl = document.createElement("span");
  valueEl.className = "val";
  const input = document.createElement("input");
  input.id = "p-" + spec.name;
  label.htmlFor = input.id;
  if (spec.kind === "bool") {
    input.type = "checkbox";
    input.addEventListener("change", () => queueChange(spec, input.checked ? 1 : 0));
  } else {
    input.type = "range";
    input.min = spec.min; input.max = spec.max; input.step = spec.step;
    input.addEventListener("input", () => queueChange(spec, Number(input.value)));
  }
  row.append(label, valueEl);
  const help = document.createElement("div");
  help.className = "help";
  help.textContent = spec.help;
  wrapper.append(row, input, help);
  sliders[spec.name] = { input, valueEl, wrapper, spec };
  return wrapper;
}

function showSliderValue(name, value) {
  const { input, valueEl, wrapper, spec } = sliders[name];
  if (spec.kind === "bool") {
    input.checked = value >= 0.5;
    valueEl.textContent = value >= 0.5 ? "on" : "off";
  } else {
    // Chimney sizes were given in feet, so show feet next to the metres.
    const feet = spec.group === "Chimney" && spec.unit === "m" ? ` (${fmt(value * FT_PER_M, 1)} ft)` : "";
    valueEl.innerHTML = `${fmt(value, decimalsFor(spec.step))} <small>${spec.unit === "-" ? "" : spec.unit}${feet}</small>`;
  }
  wrapper.classList.toggle("changed", Math.abs(value - state.defaults[name]) > 1e-9);
}

function queueChange(spec, value) {
  showSliderValue(spec.name, value);
  pending[spec.name] = value;
  clearTimeout(sendTimer);
  sendTimer = setTimeout(flushChanges, 120);
}

async function flushChanges() {
  const changes = { ...pending };
  for (const key of Object.keys(pending)) delete pending[key];
  try {
    await api("/api/params", changes);
  } catch (error) {
    toast(error.message);
  }
}

function syncSliders(values) {
  state.serverValues = values;
  for (const [name, value] of Object.entries(values)) {
    if (!sliders[name] || name in pending || document.activeElement === sliders[name].input) continue;
    if (sliders[name].spec.kind !== "bool") sliders[name].input.value = value;
    showSliderValue(name, value);
  }
}

// ------------------------------------------------------------------ controls
function currentMode() {
  return document.querySelector("#mode-seg button.active").dataset.mode;
}

function commandText() {
  const mode = currentMode();
  if (mode === "PID") return `PID ${$("sp").value}`;
  if (mode === "MAN") return `MAN ${$("man").value}`;
  return "OFF";
}

function showMode(mode) {
  document.querySelectorAll("#mode-seg button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $("grp-sp").hidden = mode !== "PID";
  $("grp-man").hidden = mode !== "MAN";
}

function sendCommand() {
  $("sp-val").textContent = Number($("sp").value).toFixed(1);
  $("man-val").textContent = $("man").value;
  api("/api/command", { text: commandText() }).catch((e) => toast(e.message));
}

function buildControls(faults) {
  document.querySelectorAll("#mode-seg button").forEach((button) =>
    button.addEventListener("click", () => { showMode(button.dataset.mode); sendCommand(); }));
  $("sp").addEventListener("input", sendCommand);
  $("man").addEventListener("input", sendCommand);
  $("btn-run").addEventListener("click", () =>
    api("/api/control", { action: state.running ? "pause" : "run" }).catch((e) => toast(e.message)));
  $("btn-reset").addEventListener("click", () => {
    state.records = []; state.lastTime = -1;
    api("/api/control", { action: "reset" }).catch((e) => toast(e.message));
  });
  $("btn-defaults").addEventListener("click", () => api("/api/params", { reset: true }).catch((e) => toast(e.message)));
  $("speed").addEventListener("change", () => api("/api/control", { speed: Number($("speed").value) }).catch((e) => toast(e.message)));
  $("window").addEventListener("change", () => { state.windowS = Number($("window").value); drawAll(); });
  $("exaggerate").addEventListener("change", () => { Scene.setExaggerate($("exaggerate").checked); showSceneNote(); });

  const host = $("fault-rows");
  for (const channel of Object.keys(CHANNEL_INFO)) {
    const [label, unit] = CHANNEL_INFO[channel];
    const row = document.createElement("div");
    row.className = "fault-row";
    const name = document.createElement("span");
    name.textContent = label;
    const select = document.createElement("select");
    select.id = `fault-${channel}`;
    select.setAttribute("aria-label", `${label} fault`);
    for (const fault of faults) select.add(new Option(FAULT_LABELS[fault] || fault, fault));
    select.addEventListener("change", () => api("/api/fault", { channel, fault: select.value }).catch((e) => toast(e.message)));
    const offsetWrap = document.createElement("span");
    const offset = document.createElement("input");
    offset.type = "number"; offset.step = "1"; offset.value = "0"; offset.id = `offset-${channel}`;
    offset.setAttribute("aria-label", `${label} drift`);
    offset.addEventListener("change", () => api("/api/fault", { channel, offset: Number(offset.value) }).catch((e) => toast(e.message)));
    const unitEl = document.createElement("span");
    unitEl.className = "unit";
    unitEl.textContent = ` ${unit} drift (reads high by this much)`;
    offsetWrap.append(offset, unitEl);
    row.append(name, select, offsetWrap);
    host.appendChild(row);
  }
}

function syncControls(snapshot) {
  state.running = snapshot.running;
  $("btn-run").textContent = snapshot.running ? "Pause" : "Run";
  const speedSelect = $("speed");
  if (!speedSelect.options.length) for (const s of snapshot.speeds) speedSelect.add(new Option(`${s}×`, s));
  if (document.activeElement !== speedSelect) speedSelect.value = snapshot.speed;

  const [mode, value] = snapshot.command.split(/\s+/);
  const idle = document.activeElement !== $("sp") && document.activeElement !== $("man");
  if (idle && ["PID", "MAN", "OFF"].includes(mode.toUpperCase())) {
    showMode(mode.toUpperCase());
    if (mode.toUpperCase() === "PID") $("sp").value = value;
    if (mode.toUpperCase() === "MAN") $("man").value = value;
    $("sp-val").textContent = Number($("sp").value).toFixed(1);
    $("man-val").textContent = $("man").value;
  }
  for (const channel of Object.keys(CHANNEL_INFO)) {
    if (document.activeElement !== $(`fault-${channel}`)) $(`fault-${channel}`).value = snapshot.faults[channel];
    if (document.activeElement !== $(`offset-${channel}`)) $(`offset-${channel}`).value = snapshot.offsets[channel];
  }
}

// ------------------------------------------------------------------ live readouts
function statusChip(record) {
  const chip = $("chip-status");
  const map = {
    PID: ["PID control", "ok"], MANUAL: ["Manual speed", "ok"],
    OFF_SAFE_RPM: ["OFF → safe speed", "warn"], SENSOR_FAULT_SAFE_RPM: ["Sensor fault → safe speed", "bad"],
  };
  let [text, level] = map[record.status] || [record.status, "warn"];
  if (record.pressure_out_of_range) { text += " · P1/P2 outside transmitter range"; level = "warn"; }
  if (record.in_resonance_band) { text += " · fan in resonance band"; level = "warn"; }
  chip.textContent = record.stalled ? `${text} · no flow (stalled)` : text;
  chip.className = "chip " + (record.stalled ? "bad" : level);
}

function updateReadouts(record) {
  $("chip-time").textContent = `t = ${Math.floor(record.time_s / 60)} min ${Math.round(record.time_s % 60)} s`;
  statusChip(record);
  $("k-true").textContent = fmt(record.flow_true_m3s, 2);
  $("k-est").textContent = fmt(record.flow_estimate_m3s, 2);
  $("k-nat").textContent = fmt(record.flow_natural_only_m3s, 2);
  $("k-rpm").textContent = fmt(record.rpm_actual, 0);
  $("k-pid").textContent = record.pid_output === null ? "–" : fmt(Math.max(0, Math.min(1, record.pid_output)) * 100, 0);
  $("k-legacy").textContent = fmt(record.flow_legacy, 1);
}

// ------------------------------------------------------------------ picture note and calculations
function showSceneNote() {
  const factor = state.profile ? state.profile.pressure_exaggeration : 100;
  const widths = `Heights are to scale; tube widths are drawn ${Scene.widthExaggeration}× wider; horizontal distances are schematic.`;
  $("scene-note").textContent = $("exaggerate").checked
    ? `NOT TO SCALE: pressure differences are drawn ${factor}× larger so they can be seen. Each dot stands for gas molecules per unit volume (pressure ÷ temperature). The numbers are true values. ${widths}`
    : `True scale: each dot stands for gas molecules per unit volume (pressure ÷ temperature). Only the temperature effect is visible, because pressures here differ from atmospheric by less than 1 %. ${widths}`;
}

const BUDGET_PARTS = {
  sources: [["kiln_gauge_pa", "Kiln pressure", "--c-teal"], ["draft_pa", "Natural draft", "--c-green"], ["fan_pa", "Fan", "--c-orange"]],
  losses: [["kiln_pa", "Kiln and flue", "--c-red"], ["fan_to_plate_pa", "Fan-to-plate duct", "--c-grey"],
    ["plate_pa", "Plate (permanent)", "--c-magenta"], ["restriction_pa", "Restriction", "--c-blue"],
    ["chimney_friction_pa", "Chimney friction", "--c-teal"], ["exit_pa", "Chimney exit", "--c-green"]],
};

function drawBudget(budget) {
  const totals = {};
  for (const side of ["sources", "losses"]) {
    totals[side] = BUDGET_PARTS[side].reduce((sum, [key]) => sum + Math.max(0, budget[side][key]), 0);
  }
  const scale = Math.max(totals.sources, totals.losses, 1e-9);
  const legend = $("budget-legend");
  legend.innerHTML = "";
  for (const side of ["sources", "losses"]) {
    const bar = $(`bar-${side}`);
    bar.innerHTML = "";
    for (const [key, name, color] of BUDGET_PARTS[side]) {
      const value = budget[side][key];
      if (value > 0.05) {
        const part = document.createElement("i");
        part.style.width = `${(value / scale) * 100}%`;
        part.style.background = `var(${color})`;
        part.title = `${name}: ${fmt(value, 1)} Pa`;
        bar.appendChild(part);
      }
      const item = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.style.borderTopColor = `var(${color})`;
      const number = document.createElement("b");
      number.textContent = fmt(value, 1);
      item.append(swatch, document.createTextNode(`${name} `), number);
      legend.appendChild(item);
    }
    $(`sum-${side}`).textContent = `${fmt(totals[side], 0)} Pa`;
  }
}

function calcCard(title, rows) {
  const card = document.createElement("div");
  card.className = "calc-card";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const list = document.createElement("dl");
  for (const [name, value] of rows) {
    const dt = document.createElement("dt"); dt.textContent = name;
    const dd = document.createElement("dd"); dd.textContent = value;
    list.append(dt, dd);
  }
  card.append(heading, list);
  return card;
}

function updateCalcs(profile) {
  const c = profile.calcs, by = Object.fromEntries(profile.stations.map((s) => [s.key, s]));
  const thousands = (v) => Math.round(v).toLocaleString("en-US");
  drawBudget(c.budget);
  const grid = $("calc-grid");
  grid.innerHTML = "";
  grid.append(
    calcCard("Flow", [["Mass flow", `${fmt(c.mass_flow_kg_s, 2)} kg/s`], ["", `${fmt(c.mass_flow_t_h, 1)} t/h`],
      ["At the plate", `${fmt(c.q_plate_m3_s, 2)} m³/s`],
      ["Push from draft", c.draft_share === null ? "–" : `${fmt(c.draft_share * 100, 0)} %`]]),
    calcCard("Velocity", [["Kiln opening", `${fmt(c.velocity.kiln_opening_m_s, 1)} m/s`], ["Duct", `${fmt(c.velocity.duct_m_s, 1)} m/s`],
      ["Plate bore", `${fmt(c.velocity.plate_bore_m_s, 1)} m/s`], ["Chimney base", `${fmt(c.velocity.chimney_base_m_s, 1)} m/s`],
      ["Chimney exit", `${fmt(c.velocity.chimney_exit_m_s, 1)} m/s`]]),
    calcCard("Pressure (absolute)", [["P1", `${thousands(by.p1.p_abs_pa)} Pa`], ["P2", `${thousands(by.p2.p_abs_pa)} Pa`],
      ["Air at ground", `${thousands(profile.ground.p_abs_pa)} Pa`], ["Air at chimney top", `${thousands(profile.top.outside.p_abs_pa)} Pa`]]),
    calcCard("Density", [["Gas at the plate", `${fmt(by.p1.rho, 3)} kg/m³`], ["Gas at chimney top", `${fmt(profile.top.rho, 3)} kg/m³`],
      ["Air at ground", `${fmt(profile.ground.rho, 3)} kg/m³`], ["Air at chimney top", `${fmt(profile.top.outside.rho, 3)} kg/m³`]]),
    calcCard("Fan power", [["Air power", `${fmt(c.fan_air_power_w / 1000, 2)} kW`], ["Shaft (estimate)", `${fmt(c.fan_shaft_power_w / 1000, 2)} kW`]]),
    calcCard("Heat", [["Carried above ambient", `${fmt(c.heat_carried_w / 1000, 0)} kW`], ["Lost through chimney wall", `${fmt(c.heat_lost_chimney_w / 1000, 0)} kW`],
      ["Gas at chimney top", `${fmt(profile.top.t_c, 0)} °C`],
      ["Time in chimney", c.residence_time_chimney_s === null ? "–" : `${fmt(c.residence_time_chimney_s, 0)} s`]]),
    calcCard("Reynolds number", [["Duct", thousands(c.reynolds.duct)], ["Chimney base", thousands(c.reynolds.chimney_base)],
      ["Chimney top", thousands(c.reynolds.chimney_top)]]),
  );
  const imbalance = c.budget.imbalance_pa;
  $("calc-note").textContent = `${c.viscosity_note} Pushing minus resisting is ${fmt(imbalance, 1)} Pa: it is zero when the flow is steady and non-zero while the gas is speeding up or slowing down.`;

}

// ------------------------------------------------------------------ charts
const CHARTS = [
  { id: "flow", title: "Flow through the plate", unit: "m³/s", series: [
    { key: "setpoint_m3s", label: "Setpoint", color: "--c-grey", dash: true },
    { key: "flow_true_m3s", label: "True flow", color: "--c-blue" },
    { key: "flow_estimate_m3s", label: "Controller's estimate", color: "--c-orange" },
    { key: "flow_natural_only_m3s", label: "Natural draft alone", color: "--c-green", dash: true } ] },
  { id: "rpm", title: "Fan speed (shaded: resonance band)", unit: "rpm", band: ["resonance_low_rpm", "resonance_high_rpm"], series: [
    { key: "rpm_commanded", label: "Commanded", color: "--c-orange", dash: true },
    { key: "rpm_actual", label: "Actual shaft", color: "--c-blue" } ] },
  { id: "press", title: "Pressures (gauge, room = 0)", unit: "Pa", series: [
    { key: "p1_pa", label: "P1 before plate", color: "--c-blue" },
    { key: "p2_pa", label: "P2 after plate", color: "--c-magenta" },
    { key: "p_fan_in_pa", label: "Fan inlet", color: "--c-red" },
    { key: "p_chimney_base_pa", label: "Chimney base", color: "--c-teal", dash: true },
    { key: "draft_pa", label: "Natural draft", color: "--c-green" },
    { key: "fan_dp_pa", label: "Fan adds", color: "--c-orange" } ] },
  { id: "legacy", title: "Legacy formula value (not m³/s; shown for comparison, not used for control)", unit: "old units", series: [
    { key: "flow_legacy", label: "calc_pv", color: "--c-magenta" } ] },
  { id: "temp", title: "Temperatures", unit: "°C", series: [
    { key: "t_gas_c", label: "Exhaust gas at the plate", color: "--c-magenta" },
    { key: "t_chimney_mean_c", label: "Chimney gas (mean)", color: "--c-orange" },
    { key: "t_chimney_top_c", label: "Chimney top", color: "--c-teal", dash: true },
    { key: "t_ambient_c", label: "Outside air", color: "--c-blue" } ] },
];

function buildCharts() {
  const host = $("chart-host");
  for (const chart of CHARTS) {
    const card = document.createElement("div");
    card.className = "chart-card";
    const title = document.createElement("h3");
    title.textContent = `${chart.title} (${chart.unit})`;
    const legend = document.createElement("div");
    legend.className = "legend";
    chart.valueEls = {};
    for (const s of chart.series) {
      const item = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.style.borderTopColor = `var(${s.color})`;
      if (s.dash) swatch.classList.add("dashed");
      const value = document.createElement("b");
      value.textContent = "–";
      chart.valueEls[s.key] = value;
      item.append(swatch, document.createTextNode(s.label + " "), value);
      legend.appendChild(item);
    }
    const canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `${chart.title} over time`);
    canvas.addEventListener("mousemove", (event) => {
      const rect = canvas.getBoundingClientRect();
      const frac = (event.clientX - rect.left - PAD.left) / (rect.width - PAD.left - PAD.right);
      const [start, span] = timeAxis();
      state.hoverTime = start + Math.max(0, Math.min(1, frac)) * span;
      drawAll();
    });
    canvas.addEventListener("mouseleave", () => { state.hoverTime = null; drawAll(); });
    card.append(title, legend, canvas);
    host.appendChild(card);
    chart.canvas = canvas;
  }
}

const PAD = { left: 52, right: 10, top: 8, bottom: 22 };

function niceTicks(lo, hi, count = 4) {
  const span = hi - lo || 1;
  const rough = span / count;
  const pow = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= rough) || 10 * pow;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
  return { ticks, step };
}

function recordAt(time) {
  const records = state.records;
  let lo = 0, hi = records.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (records[mid].time_s < time) lo = mid + 1; else hi = mid; }
  return records[lo];
}

// The visible time window: it grows from t = 0 until the history exceeds the chosen length, then scrolls.
function timeAxis() {
  const end = state.records.length ? state.records[state.records.length - 1].time_s : 0;
  const start = Math.max(0, end - state.windowS);
  return [start, Math.max(end - start, 10)];
}

function drawChart(chart) {
  const canvas = chart.canvas;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const records = state.records;
  if (!records.length) return;

  const tEnd = records[records.length - 1].time_s;
  const [tStart, tSpan] = timeAxis();
  const visible = records.filter((r) => r.time_s >= tStart);
  let lo = Infinity, hi = -Infinity;
  for (const s of chart.series) for (const r of visible) {
    const v = r[s.key];
    if (v !== null && v !== undefined) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  }
  if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
  const pad = Math.max((hi - lo) * 0.1, Math.abs(hi) * 0.02, 0.5);
  lo -= pad; hi += pad;

  const x = (t) => PAD.left + ((t - tStart) / tSpan) * (width - PAD.left - PAD.right);
  const y = (v) => PAD.top + (1 - (v - lo) / (hi - lo)) * (height - PAD.top - PAD.bottom);

  ctx.font = "11px system-ui, sans-serif";
  ctx.lineWidth = 1;
  const { ticks, step } = niceTicks(lo, hi);
  const digits = step < 1 ? 1 : 0;
  for (const tick of ticks) {
    ctx.strokeStyle = css("--line");
    ctx.beginPath(); ctx.moveTo(PAD.left, y(tick)); ctx.lineTo(width - PAD.right, y(tick)); ctx.stroke();
    ctx.fillStyle = css("--muted"); ctx.textAlign = "right"; ctx.textBaseline = "middle";
    ctx.fillText(tick.toFixed(digits), PAD.left - 6, y(tick));
  }
  if (chart.band) {                // shaded band, e.g. the fan's resonance speeds
    const [bandLo, bandHi] = chart.band.map((name) => state.serverValues[name]);
    if (bandHi > bandLo && bandHi > lo && bandLo < hi) {
      ctx.fillStyle = css("--strip-suction");
      ctx.fillRect(PAD.left, y(Math.min(hi, bandHi)), width - PAD.left - PAD.right, y(Math.max(lo, bandLo)) - y(Math.min(hi, bandHi)));
    }
  }
  if (lo < 0 && hi > 0) {          // zero line for the pressure chart
    ctx.strokeStyle = css("--muted"); ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(PAD.left, y(0)); ctx.lineTo(width - PAD.right, y(0)); ctx.stroke(); ctx.setLineDash([]);
  }
  ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.fillStyle = css("--muted");
  const xStep = tSpan <= 120 ? 30 : tSpan <= 600 ? 120 : 600;
  for (let t = Math.ceil(tStart / xStep) * xStep; t <= tEnd; t += xStep) {
    ctx.fillText(t >= 3600 ? `${(t / 60).toFixed(0)}m` : `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, "0")}`, x(t), height - PAD.bottom + 6);
  }

  for (const s of chart.series) {
    ctx.strokeStyle = css(s.color); ctx.lineWidth = 2; ctx.setLineDash(s.dash ? [6, 4] : []);
    ctx.beginPath();
    let open = false;
    for (const r of visible) {
      const v = r[s.key];
      if (v === null || v === undefined) { open = false; continue; }      // gap while a signal is missing
      if (open) ctx.lineTo(x(r.time_s), y(v)); else { ctx.moveTo(x(r.time_s), y(v)); open = true; }
    }
    ctx.stroke();
  }
  ctx.setLineDash([]);

  const shown = state.hoverTime === null ? records[records.length - 1] : recordAt(state.hoverTime);
  if (state.hoverTime !== null && shown) {
    ctx.strokeStyle = css("--muted"); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x(shown.time_s), PAD.top); ctx.lineTo(x(shown.time_s), height - PAD.bottom); ctx.stroke();
  }
  for (const s of chart.series) chart.valueEls[s.key].textContent = fmt(shown[s.key], s.key.startsWith("rpm") || chart.unit === "°C" ? 0 : 1);
}

function drawAll() { for (const chart of CHARTS) drawChart(chart); }

// ------------------------------------------------------------------ polling
async function poll() {
  try {
    const snapshot = await api(`/api/state?since=${state.lastTime}`);
    if (snapshot.time_s < state.lastTime) { state.records = []; }          // simulation was restarted
    for (const record of snapshot.records) state.records.push(record);
    if (state.records.length > MAX_KEPT_RECORDS) state.records.splice(0, state.records.length - MAX_KEPT_RECORDS);
    if (state.records.length) state.lastTime = state.records[state.records.length - 1].time_s;
    else state.lastTime = -1;
    syncSliders(snapshot.values);
    syncControls(snapshot);
    if (state.records.length) updateReadouts(state.records[state.records.length - 1]);
    if (snapshot.profile) {
      state.profile = snapshot.profile;
      Scene.update(snapshot.profile, state.records[state.records.length - 1] || null, snapshot.values, snapshot.running);
      updateCalcs(snapshot.profile);
      showSceneNote();
    }
    drawAll();
  } catch (error) {
    $("chip-status").textContent = "server not reachable";
    $("chip-status").className = "chip bad";
  }
}

async function init() {
  const specs = await api("/api/specs");
  state.specs = specs.specs;
  state.defaults = specs.defaults;
  buildSliders();
  buildControls(specs.faults);
  buildCharts();
  Scene.init($("scene"), $("strip"));
  Scene.setExaggerate($("exaggerate").checked);
  const first = await api("/api/state");
  syncSliders(first.values);
  window.addEventListener("resize", drawAll);
  await poll();
  setInterval(poll, POLL_MS);
}

init().catch((error) => toast(`Could not start: ${error.message}`));
