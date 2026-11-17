"use strict";
// Thin client for the whole-kiln page: every number comes from the Python simulation
// (/api/kiln/state). This file only sends operator inputs and draws.

const POLL_MS = 400;
const ROW_UNITS = 30;
const FULL_WATER_KG = 600;            // only used to scale the water bars; the value shown is the model's
const ZONE_COLORS = {
  handling: "--c-grey", "pre-drying": "--c-teal", damper: "--c-blue",
  "pre-heating": "--c-orange", firing: "--c-red", cooling: "--c-magenta",
};
const ZONE_ORDER = ["pre-drying", "damper", "pre-heating", "firing", "cooling", "handling"];
// Heat colour scale (°C -> colour). Same stops for the cells, the legend and nothing else.
const HEAT_STOPS = [[0, [29, 31, 58]], [200, [74, 28, 110]], [400, [155, 42, 99]], [600, [217, 71, 47]],
  [800, [247, 162, 27]], [1000, [252, 243, 168]]];
const CONTROL_SPECS = [
  { name: "rpm", label: "Fan speed", unit: "rpm", min: 100, max: 900, step: 10, scale: 1, digits: 0,
    help: "Fixed fan speed. Stage 1 fan, plate and chimney give the suction on the main flue." },
  { name: "ru_per_day", label: "Fire travel rate", unit: "room units/day", min: 4, max: 14, step: 0.5, scale: 1, digits: 1,
    help: "How fast the fire moves round the ring. Site schedule: 9 per day (4.5 rooms)." },
  { name: "fuel_moisture", label: "Firewood moisture", unit: "%", min: 5, max: 50, step: 1, scale: 100, digits: 0,
    help: "Wet basis. The plan feeds wetter wood heavier so the heat stays the same (site: about 22 %)." },
  { name: "charge_size_factor", label: "Charge size factor", unit: "× plan", min: 0.5, max: 1.5, step: 0.05, scale: 1, digits: 2,
    help: "Every charge weighed this much heavier or lighter than the firing plan." },
  { name: "t_amb_c", label: "Ambient temperature", unit: "°C", min: 0, max: 45, step: 1, scale: 1, digits: 0,
    help: "Air entering through the doors, and the outside of the walls and chimney." },
];
const CHARTS = [
  { title: "Exhaust temperature reaching the fan", unit: "°C", series: [
    { key: "t_exhaust_c", label: "Exhaust", color: "--c-magenta" }, { key: "t_ambient_c", label: "Ambient", color: "--c-blue", dash: true }] },
  { title: "Total flow", unit: "kg/s and m³/s", series: [
    { key: "exhaust_kg_s", label: "Gas to the fan (kg/s)", color: "--c-blue", digits: 2 },
    { key: "q_plate_m3_s", label: "At the plate (m³/s)", color: "--c-teal", dash: true, digits: 2 }] },
  { title: "Fan speed", unit: "rpm", series: [{ key: "rpm", label: "Fan", color: "--c-orange", digits: 0 }] },
  { title: "P1 and P2 (gauge, room = 0)", unit: "Pa", series: [
    { key: "p1_pa", label: "P1 before plate", color: "--c-blue" }, { key: "p2_pa", label: "P2 after plate", color: "--c-magenta" }] },
  { title: "Peak temperature in the ring", unit: "°C", series: [
    { key: "peak_point_c", label: "Hottest point reading", color: "--c-red", digits: 0 },
    { key: "peak_tile_c", label: "Hottest tiles", color: "--c-orange", dash: true, digits: 0 }] },
  { title: "Fuel fed in the last hour", unit: "kg", series: [
    { key: "fuel_last_hour_kg", label: "Firewood", color: "--c-green", digits: 0 }] },
];

const state = { records: [], lastTime: -1, kiln: null, running: true, built: false };
const controlEls = {};
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

function heatRgb(t) {
  const v = Math.max(HEAT_STOPS[0][0], Math.min(HEAT_STOPS[HEAT_STOPS.length - 1][0], t));
  for (let i = 1; i < HEAT_STOPS.length; i++) {
    const [t1, c1] = HEAT_STOPS[i];
    const [t0, c0] = HEAT_STOPS[i - 1];
    if (v <= t1) {
      const f = (v - t0) / (t1 - t0);
      return c0.map((c, k) => Math.round(c + (c1[k] - c) * f));
    }
  }
  return HEAT_STOPS[HEAT_STOPS.length - 1][1];
}
const heatColor = (t) => `rgb(${heatRgb(t).join(",")})`;
const inkOn = (t) => { const [r, g, b] = heatRgb(t); return 0.299 * r + 0.587 * g + 0.114 * b > 140 ? "#111" : "#fff"; };

function fitCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return [ctx, width, height];
}

// ------------------------------------------------------------------ controls
function buildControls(snapshot) {
  const host = $("controls");
  for (const spec of CONTROL_SPECS) {
    const wrap = document.createElement("div");
    wrap.className = "param";
    const row = document.createElement("div");
    row.className = "row1";
    const label = document.createElement("label");
    label.className = "name"; label.textContent = spec.label; label.htmlFor = `c-${spec.name}`;
    const value = document.createElement("span");
    value.className = "val";
    const input = document.createElement("input");
    input.type = "range"; input.id = `c-${spec.name}`;
    input.min = spec.min; input.max = spec.max; input.step = spec.step;
    input.addEventListener("input", () => showControl(spec, Number(input.value) / spec.scale));
    input.addEventListener("change", () => {
      api("/api/kiln/params", { [spec.name]: Number(input.value) / spec.scale }).catch((e) => toast(e.message));
    });
    const help = document.createElement("div");
    help.className = "help"; help.textContent = spec.help;
    row.append(label, value);
    wrap.append(row, input, help);
    host.appendChild(wrap);
    controlEls[spec.name] = { input, value, spec };
  }
  const speed = $("speed");
  for (const s of snapshot.speeds) speed.add(new Option(s.label, s.value));
  speed.addEventListener("change", () => api("/api/kiln/control", { speed: Number(speed.value) }).catch((e) => toast(e.message)));
  $("btn-run").addEventListener("click", () => api("/api/kiln/control", { action: state.running ? "pause" : "run" }).catch((e) => toast(e.message)));
  $("btn-reset").addEventListener("click", () => {
    state.records = []; state.lastTime = -1;
    api("/api/kiln/control", { action: "reset" }).catch((e) => toast(e.message));
  });
  $("btn-skip").addEventListener("click", () =>
    api("/api/kiln/upset", { type: "skip", count: Number($("skip-count").value) })
      .then((r) => toast(`Skipping ${$("skip-count").value} charges on fireboxes ${r.units.join(", ")}`)).catch((e) => toast(e.message)));
  $("btn-damper").addEventListener("click", () =>
    api("/api/kiln/upset", { type: "damper", unit: Number($("damper-unit").value), lift_in: Number($("damper-lift").value) }).catch((e) => toast(e.message)));
  $("btn-door").addEventListener("click", () =>
    api("/api/kiln/upset", { type: "door", unit: Number($("door-unit").value), door: $("door-pos").value }).catch((e) => toast(e.message)));
  $("btn-clear").addEventListener("click", () => api("/api/kiln/upset", { type: "clear" }).catch((e) => toast(e.message)));

  for (const u of snapshot.kiln.units) {
    if (u.has_damper) $("damper-unit").add(new Option(`${u.number} (${u.unit})`, u.number));
    if (u.has_door) $("door-unit").add(new Option(`${u.number} (${u.unit})`, u.number));
  }
}

function showControl(spec, value) {
  controlEls[spec.name].value.innerHTML = `${fmt(value * spec.scale, spec.digits)} <small>${spec.unit}</small>`;
}

function syncControls(snapshot) {
  state.running = snapshot.running;
  $("btn-run").textContent = snapshot.running ? "Pause" : "Run";
  if (document.activeElement !== $("speed")) $("speed").value = snapshot.speed;
  for (const { input, spec } of Object.values(controlEls)) {
    const value = snapshot.controls[spec.name];
    if (document.activeElement !== input) input.value = value * spec.scale;
    showControl(spec, document.activeElement === input ? Number(input.value) / spec.scale : value);
  }
  const up = snapshot.kiln.upsets;
  const parts = [];
  for (const [unit, lift] of Object.entries(up.damper_overrides)) parts.push(`damper ${unit} held at ${fmt(lift, 1)} in`);
  for (const [unit, door] of Object.entries(up.door_overrides)) parts.push(`door ${unit} held ${door}`);
  if (up.skip_left > 0) parts.push(`${up.skip_left} charges still to skip`);
  $("upset-status").textContent = parts.length ? `Active: ${parts.join("; ")}.` : "No upsets active.";
}

// ------------------------------------------------------------------ plan view
// East battery (1-30) is the top row, left to right; the west battery (31-60) is the bottom row,
// right to left. Unit 30 (south interconnecting flue) and unit 60 (north) close the ring at the ends.
const RING = { side: 46, zoneTop: 18, cellTop: 34, cellH: 66, flueTop: 150, flueH: 26, gap: 0 };

function ringGeometry(width) {
  const cw = (width - 2 * RING.side) / ROW_UNITS;
  const bottomTop = RING.flueTop + RING.flueH + (RING.flueTop - RING.cellTop - RING.cellH);
  return { cw, bottomTop, height: bottomTop + RING.cellH + 40 };
}

function cellBox(number, g) {
  if (number <= ROW_UNITS) return { x: RING.side + (number - 1) * g.cw, y: RING.cellTop, top: true };
  return { x: RING.side + (2 * ROW_UNITS - number) * g.cw, y: g.bottomTop, top: false };
}

// x, y on the ring for a fractional firebox position (the fire lead).
function leadPoint(lead, g) {
  const n = Math.floor(lead), frac = lead - n;
  const box = cellBox(n, g);
  return { x: box.top ? box.x + frac * g.cw : box.x + g.cw - frac * g.cw, box };
}

function drawRing(kiln) {
  const canvas = $("ring");
  const g0 = ringGeometry(canvas.clientWidth);
  canvas.style.height = `${g0.height}px`;
  const [ctx, width] = fitCanvas(canvas);
  const g = ringGeometry(width);
  const units = kiln.units;
  ctx.font = "11px system-ui, sans-serif";

  // ring ends: the interconnecting flues joining the batteries
  // ring ends: the gas turns from one battery to the other through the interconnecting flues
  const midTop = RING.cellTop + RING.cellH / 2, midBottom = g.bottomTop + RING.cellH / 2;
  const right = RING.side + ROW_UNITS * g.cw, left = RING.side;
  const reach = RING.side - 14, bend = 14;
  ctx.strokeStyle = css("--duct-edge"); ctx.lineWidth = 8; ctx.lineCap = "butt"; ctx.lineJoin = "round";
  for (const [x0, sign] of [[right, 1], [left, -1]]) {
    const xo = x0 + sign * reach;
    ctx.beginPath(); ctx.moveTo(x0, midTop);
    ctx.arcTo(xo, midTop, xo, midTop + bend, bend);
    ctx.arcTo(xo, midBottom, x0, midBottom, bend);
    ctx.lineTo(x0, midBottom); ctx.stroke();
  }
  ctx.fillStyle = css("--muted"); ctx.textAlign = "center"; ctx.textBaseline = "middle";
  const flowArrow = (x0, y0, dy) => { ctx.beginPath(); ctx.moveTo(x0 - 6, y0); ctx.lineTo(x0 + 6, y0); ctx.lineTo(x0, y0 + dy); ctx.closePath(); ctx.fill(); };
  flowArrow(right + reach, (midTop + midBottom) / 2 - 6, 10);           // gas turns down at the south end
  flowArrow(left - reach, (midTop + midBottom) / 2 + 6, -10);           // and up at the north end
  ctx.fillText("S", right + reach - 16, (midTop + midBottom) / 2);
  ctx.fillText("N", left - reach + 16, (midTop + midBottom) / 2);

  // main flue between the batteries
  ctx.fillStyle = css("--duct");
  ctx.fillRect(left, RING.flueTop, right - left, RING.flueH);
  ctx.fillStyle = css("--text"); ctx.font = "12px system-ui, sans-serif";
  ctx.fillText("Main flue  →  ID fan  →  orifice plate  →  chimney", (left + right) / 2, RING.flueTop + RING.flueH / 2);
  ctx.font = "11px system-ui, sans-serif";

  for (const u of units) {
    const b = cellBox(u.number, g);
    const t = u.point_c;
    // cell
    ctx.fillStyle = heatColor(t);
    ctx.fillRect(b.x + 1, b.y, g.cw - 2, RING.cellH);
    if (!u.has_platform) {                       // interconnecting flue: no tiles, drawn hatched
      ctx.save();
      ctx.beginPath(); ctx.rect(b.x + 1, b.y, g.cw - 2, RING.cellH); ctx.clip();
      ctx.strokeStyle = "rgba(255, 255, 255, .35)"; ctx.lineWidth = 1;
      for (let k = -RING.cellH; k < g.cw; k += 7) { ctx.beginPath(); ctx.moveTo(b.x + k, b.y + RING.cellH); ctx.lineTo(b.x + k + RING.cellH, b.y); ctx.stroke(); }
      ctx.restore();
    }
    if (u.charging) { ctx.strokeStyle = css("--c-green"); ctx.lineWidth = 2; ctx.strokeRect(b.x + 2, b.y + 1, g.cw - 4, RING.cellH - 2); }
    ctx.fillStyle = inkOn(t); ctx.textAlign = "center"; ctx.textBaseline = "top";
    ctx.fillText(String(u.number), b.x + g.cw / 2, b.y + 3);
    ctx.font = "600 11px system-ui, sans-serif";
    ctx.fillText(fmt(t, 0), b.x + g.cw / 2, b.y + 22);
    ctx.font = "11px system-ui, sans-serif";
    if (u.unit === "SIF" || u.unit === "NIF") ctx.fillText(u.unit, b.x + g.cw / 2, b.y + 38);
    // tile water bar along the foot of the cell
    if (u.has_platform && u.water_kg > 0) {
      const h = 6, frac = Math.min(1, u.water_kg / FULL_WATER_KG);
      const y = b.y + RING.cellH - h - 2;
      ctx.fillStyle = css("--panel"); ctx.fillRect(b.x + 4, y, g.cw - 8, h);
      ctx.fillStyle = css("--c-blue"); ctx.fillRect(b.x + 4, y, (g.cw - 8) * frac, h);
    }
    // zone strip on the outer side
    const zy = b.top ? RING.zoneTop : g.bottomTop + RING.cellH + 4;
    ctx.fillStyle = css(ZONE_COLORS[u.zone]);
    ctx.fillRect(b.x, zy, g.cw, 6);
    // doors on the outer wall
    if (u.has_door) {
      const dy = b.top ? b.y - 4 : b.y + RING.cellH;
      if (u.door === "closed") { ctx.fillStyle = css("--muted"); ctx.fillRect(b.x + g.cw * 0.3, dy + 1, g.cw * 0.4, 2); }
      else {
        ctx.fillStyle = css(u.door_override ? "--bad" : "--c-green");
        ctx.fillRect(b.x + g.cw * 0.15, dy, g.cw * (u.door === "open" ? 0.7 : 0.35), 4);
      }
    }
    // dampers on the inner wall, joined to the main flue when lifted
    if (u.has_damper) {
      const wallY = b.top ? b.y + RING.cellH : b.y;
      const flueY = b.top ? RING.flueTop : RING.flueTop + RING.flueH;
      const cx = b.x + g.cw / 2;
      if (u.damper_lift_in > 0) {
        ctx.strokeStyle = css(u.damper_override ? "--bad" : "--flow");
        ctx.lineWidth = 2 + 10 * u.damper_share;
        ctx.beginPath(); ctx.moveTo(cx, wallY); ctx.lineTo(cx, flueY); ctx.stroke();
        ctx.fillStyle = css("--text"); ctx.textAlign = "left"; ctx.textBaseline = "middle";
        const ly = b.top ? wallY + 14 : wallY - 14;
        ctx.fillText(`${fmt(u.damper_lift_in, 1)}″`, cx + 7, ly);
        ctx.fillStyle = css("--muted");
        ctx.fillText(`${fmt(u.damper_share * 100, 0)}%`, cx + 7, ly + (b.top ? 13 : -13));
      } else {
        ctx.strokeStyle = css("--muted"); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(cx, b.top ? wallY + 5 : wallY - 5, 3, 0, 2 * Math.PI); ctx.stroke();
      }
    }
    // paper seal on the far (downstream) side of the sealed unit
    if (u.paper_sealed) {
      const sx = b.top ? b.x + g.cw : b.x;
      ctx.strokeStyle = css("--text"); ctx.lineWidth = 4;
      ctx.beginPath(); ctx.moveTo(sx, b.y - 6); ctx.lineTo(sx, b.y + RING.cellH + 6); ctx.stroke();
    }
  }

  // zone names, once per run of equal zones in each row
  ctx.font = "11px system-ui, sans-serif";
  for (const top of [true, false]) {
    const row = units.filter((u) => (u.number <= ROW_UNITS) === top)
      .sort((a, c) => cellBox(a.number, g).x - cellBox(c.number, g).x);
    let start = 0;
    for (let i = 1; i <= row.length; i++) {
      if (i === row.length || row[i].zone !== row[start].zone) {
        const x0 = cellBox(row[start].number, g).x, x1 = cellBox(row[i - 1].number, g).x + g.cw;
        const name = row[start].zone;
        if (ctx.measureText(name).width < x1 - x0 - 4) {
          ctx.fillStyle = css("--text"); ctx.textAlign = "center";
          ctx.textBaseline = top ? "bottom" : "top";
          ctx.fillText(name, (x0 + x1) / 2, top ? RING.zoneTop - 2 : g.bottomTop + RING.cellH + 12);
        }
        start = i;
      }
    }
  }

  // the fire front
  const p = leadPoint(kiln.lead, g);
  ctx.strokeStyle = "#ffd400"; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(p.x, p.box.y - 2); ctx.lineTo(p.x, p.box.y + RING.cellH + 2); ctx.stroke();
  ctx.strokeStyle = "#000"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(p.x - 2, p.box.y - 2); ctx.lineTo(p.x - 2, p.box.y + RING.cellH + 2); ctx.stroke();
  const ty = p.box.top ? RING.cellTop + RING.cellH + 2 : g.bottomTop - 2;
  const dir = p.box.top ? 1 : -1;
  ctx.fillStyle = css("--c-red");
  ctx.beginPath(); ctx.moveTo(p.x, ty); ctx.lineTo(p.x - 7, ty + 12 * dir); ctx.lineTo(p.x + 7, ty + 12 * dir); ctx.closePath(); ctx.fill();
  ctx.fillStyle = css("--text"); ctx.textAlign = "center"; ctx.textBaseline = p.box.top ? "top" : "bottom";
  ctx.font = "600 11px system-ui, sans-serif";
  ctx.fillText("fire", p.x, ty + 13 * dir);
}

function buildRingLegend() {
  const host = $("ring-legend");
  const stops = HEAT_STOPS.map(([t, c]) => `rgb(${c.join(",")}) ${(t / 1000) * 100}%`).join(", ");
  const scale = `<span class="heat-scale"><span>Point temperature</span><i style="background: linear-gradient(90deg, ${stops})"></i><span>0</span><span>500</span><span>1000 °C</span></span>`;
  const zones = ZONE_ORDER.map((z) => `<span><i class="swatch" style="background: var(${ZONE_COLORS[z]})"></i>${z}</span>`).join("");
  const marks = [
    `<span><i class="swatch" style="background: var(--c-green)"></i>door open (wide) / part-open (short)</span>`,
    `<span><i class="swatch line" style="background: var(--flow)"></i>lifted damper: lift in inches, share of the flow</span>`,
    `<span><i class="swatch line" style="background: var(--text)"></i>paper seal</span>`,
    `<span><i class="swatch" style="background: #ffd400"></i>fire front</span>`,
    `<span><i class="swatch" style="background: var(--c-blue)"></i>tile water left</span>`,
    `<span><i class="swatch outline"></i>charge being fed</span>`,
    `<span><i class="swatch" style="background: var(--bad)"></i>upset (held by the operator)</span>`,
  ].join("");
  host.innerHTML = `${scale}<div class="legend">${zones}</div><div class="legend">${marks}</div>`;
}

// ------------------------------------------------------------------ ring profile chart
const PAD = { left: 48, right: 52, top: 10, bottom: 26 };
const PROFILE_SERIES = [
  { key: "point_c", label: "Point (gas, lagged)", color: "--c-red" },
  { key: "tile_c", label: "Tiles", color: "--c-orange" },
  { key: "brick_c", label: "Brick", color: "--c-grey", dash: true },
];

function buildProfileLegend() {
  const host = $("profile-legend");
  host.innerHTML = PROFILE_SERIES.map((s) =>
    `<span><i style="border-top-color: var(${s.color})" class="${s.dash ? "dashed" : ""}"></i>${s.label}</span>`).join("")
    + `<span><i class="bar-swatch"></i>Tile water left (kg, right axis)</span>`
    + `<span><i style="border-top-color: #ffd400"></i>Fire front</span>`;
}

function drawProfile(kiln) {
  const [ctx, width, height] = fitCanvas($("profile"));
  const units = kiln.units;
  const plotW = width - PAD.left - PAD.right, plotH = height - PAD.top - PAD.bottom;
  const x = (n) => PAD.left + ((n - 0.5) / 60) * plotW;
  const tMax = Math.max(1000, ...units.map((u) => u.point_c));
  const y = (t) => PAD.top + (1 - t / tMax) * plotH;
  const yw = (w) => PAD.top + (1 - w / (FULL_WATER_KG * 1.25)) * plotH;
  ctx.font = "11px system-ui, sans-serif";

  for (const u of units) {             // zone shading
    ctx.fillStyle = css(ZONE_COLORS[u.zone]); ctx.globalAlpha = 0.12;
    ctx.fillRect(x(u.number - 0.5), PAD.top, plotW / 60, plotH);
  }
  ctx.globalAlpha = 1;
  for (let t = 0; t <= tMax; t += 200) {
    ctx.strokeStyle = css("--line"); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD.left, y(t)); ctx.lineTo(width - PAD.right, y(t)); ctx.stroke();
    ctx.fillStyle = css("--muted"); ctx.textAlign = "right"; ctx.textBaseline = "middle";
    ctx.fillText(`${t}`, PAD.left - 6, y(t));
  }
  ctx.textAlign = "left";
  for (let w = 0; w <= FULL_WATER_KG; w += 200) ctx.fillText(`${w}`, width - PAD.right + 6, yw(w));
  ctx.save(); ctx.translate(12, PAD.top + plotH / 2); ctx.rotate(-Math.PI / 2); ctx.textAlign = "center";
  ctx.fillText("°C", 0, 0); ctx.restore();
  ctx.save(); ctx.translate(width - 10, PAD.top + plotH / 2); ctx.rotate(Math.PI / 2); ctx.textAlign = "center";
  ctx.fillText("kg water", 0, 0); ctx.restore();
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let n = 1; n <= 60; n += (n === 1 ? 4 : 5)) ctx.fillText(String(n), x(n), height - PAD.bottom + 6);
  ctx.textAlign = "right";
  ctx.fillText("firebox", PAD.left - 6, height - PAD.bottom + 6);

  for (const u of units) {             // water bars
    if (u.water_kg <= 0) continue;
    ctx.fillStyle = css("--c-blue"); ctx.globalAlpha = 0.45;
    const bw = plotW / 60 * 0.7;
    ctx.fillRect(x(u.number) - bw / 2, yw(u.water_kg), bw, yw(0) - yw(u.water_kg));
  }
  ctx.globalAlpha = 1;
  for (const s of PROFILE_SERIES) {
    ctx.strokeStyle = css(s.color); ctx.lineWidth = 2; ctx.setLineDash(s.dash ? [6, 4] : []);
    ctx.beginPath();
    let open = false;
    for (const u of units) {
      const v = u[s.key];
      if (v === null || v === undefined) { open = false; continue; }
      if (open) ctx.lineTo(x(u.number), y(v)); else { ctx.moveTo(x(u.number), y(v)); open = true; }
    }
    ctx.stroke();
  }
  ctx.setLineDash([]);
  const lx = x(kiln.lead);
  ctx.strokeStyle = "#ffd400"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(lx, PAD.top); ctx.lineTo(lx, PAD.top + plotH); ctx.stroke();
}

// ------------------------------------------------------------------ damper shares
function drawDampers(kiln) {
  const lifted = kiln.units.filter((u) => u.damper_lift_in > 0);
  const host = $("dampers");
  if (!lifted.length) { host.textContent = "No damper is lifted."; return; }
  host.innerHTML = "";
  for (const u of lifted) {
    const row = document.createElement("div");
    row.className = "damper-row";
    const name = document.createElement("span");
    name.textContent = `${u.number} (${u.unit})${u.damper_override ? " · held" : ""}`;
    const lift = document.createElement("span");
    lift.className = "num"; lift.textContent = `${fmt(u.damper_lift_in, 1)} in`;
    const bar = document.createElement("div");
    bar.className = "bar";
    const fill = document.createElement("i");
    fill.style.width = `${Math.min(100, u.damper_share * 100)}%`;
    fill.style.background = `var(${u.damper_override ? "--bad" : "--flow"})`;
    bar.appendChild(fill);
    const share = document.createElement("b");
    share.textContent = `${fmt(u.damper_share * 100, 0)} %`;
    const temp = document.createElement("span");
    temp.className = "num muted"; temp.textContent = `${fmt(u.gas_c, 0)} °C`;
    row.append(name, lift, bar, share, temp);
    host.appendChild(row);
  }
}

// ------------------------------------------------------------------ history charts
function buildCharts() {
  const host = $("kiln-charts");
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
    canvas.setAttribute("aria-label", `${chart.title} over the last simulated days`);
    card.append(title, legend, canvas);
    host.appendChild(card);
    chart.canvas = canvas;
  }
}

function drawChart(chart) {
  const [ctx, width, height] = fitCanvas(chart.canvas);
  const records = state.records;
  if (!records.length) return;
  const tStart = records[0].time_s / 3600, tEnd = Math.max(records[records.length - 1].time_s / 3600, tStart + 1);
  let lo = Infinity, hi = -Infinity;
  for (const s of chart.series) for (const r of records) {
    const v = r[s.key];
    if (v !== null && v !== undefined) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  }
  if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
  const pad = Math.max((hi - lo) * 0.1, Math.abs(hi) * 0.02, 0.5);
  lo -= pad; hi += pad;
  const left = 52, right = 10, top = 8, bottom = 22;
  const x = (h) => left + ((h - tStart) / (tEnd - tStart)) * (width - left - right);
  const y = (v) => top + (1 - (v - lo) / (hi - lo)) * (height - top - bottom);
  ctx.font = "11px system-ui, sans-serif";
  const span = hi - lo, rough = span / 4, pow = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= rough) || 10 * pow;
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
    ctx.strokeStyle = css("--line"); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(left, y(v)); ctx.lineTo(width - right, y(v)); ctx.stroke();
    ctx.fillStyle = css("--muted"); ctx.textAlign = "right"; ctx.textBaseline = "middle";
    ctx.fillText(v.toFixed(step < 1 ? 1 : 0), left - 6, y(v));
  }
  const hours = tEnd - tStart;
  const xStep = hours <= 12 ? 2 : hours <= 48 ? 6 : 24;
  ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.fillStyle = css("--muted");
  for (let h = Math.ceil(tStart / xStep) * xStep; h <= tEnd; h += xStep) {
    ctx.fillText(xStep === 24 ? `day ${h / 24}` : `${h} h`, x(h), height - bottom + 6);
  }
  for (const s of chart.series) {
    ctx.strokeStyle = css(s.color); ctx.lineWidth = 2; ctx.setLineDash(s.dash ? [6, 4] : []);
    ctx.beginPath();
    records.forEach((r, i) => { const px = x(r.time_s / 3600), py = y(r[s.key]); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
    ctx.stroke();
  }
  ctx.setLineDash([]);
  const last = records[records.length - 1];
  for (const s of chart.series) chart.valueEls[s.key].textContent = fmt(last[s.key], s.digits === undefined ? 1 : s.digits);
}

// ------------------------------------------------------------------ readouts
function updateReadouts(record, kiln) {
  const days = Math.floor(record.time_s / 86400);
  const rest = record.time_s - days * 86400;
  $("chip-time").textContent = `day ${days}, ${String(Math.floor(rest / 3600)).padStart(2, "0")}:${String(Math.floor((rest % 3600) / 60)).padStart(2, "0")}`;
  const chip = $("chip-status");
  chip.textContent = state.running ? `running · ${record.firing_units} fireboxes firing` : "paused";
  chip.className = "chip " + (state.running ? "ok" : "warn");
  const fireUnit = kiln.units[Math.floor(kiln.lead) - 1];
  $("k-fire").textContent = fmt(kiln.lead, 1);
  $("k-fire-sub").textContent = `firebox (${fireUnit.unit}, ${fireUnit.side})`;
  $("k-peak").textContent = fmt(record.peak_point_c, 0);
  $("k-peak-sub").textContent = `°C at firebox ${record.peak_unit}`;
  $("k-exh").textContent = fmt(record.t_exhaust_c, 0);
  $("k-flow").textContent = fmt(record.exhaust_kg_s, 2);
  $("k-rpm").textContent = fmt(record.rpm, 0);
  $("k-p").textContent = `${fmt(record.p1_pa, 0)} / ${fmt(record.p2_pa, 0)}`;
  $("k-fuel").textContent = fmt(record.fuel_last_hour_kg, 0);
  $("k-err").textContent = record.energy_error_rel === 0 ? "0" : Number(record.energy_error_rel).toExponential(0);
}

// ------------------------------------------------------------------ polling
async function poll() {
  try {
    const snapshot = await api(`/api/kiln/state?since=${state.lastTime}`);
    if (!state.built) { buildControls(snapshot); state.built = true; }
    if (snapshot.time_s < state.lastTime) state.records = [];               // restarted
    for (const r of snapshot.records) state.records.push(r);
    if (state.records.length > 2016) state.records.splice(0, state.records.length - 2016);
    state.lastTime = state.records.length ? state.records[state.records.length - 1].time_s : -1;
    state.kiln = snapshot.kiln;
    syncControls(snapshot);
    if (state.records.length) updateReadouts(state.records[state.records.length - 1], snapshot.kiln);
    drawAll();
  } catch (error) {
    $("chip-status").textContent = "server not reachable";
    $("chip-status").className = "chip bad";
  }
}

function drawAll() {
  if (!state.kiln) return;
  drawRing(state.kiln);
  drawProfile(state.kiln);
  drawDampers(state.kiln);
  for (const chart of CHARTS) drawChart(chart);
}

function init() {
  buildRingLegend();
  buildProfileLegend();
  buildCharts();
  window.addEventListener("resize", drawAll);
  poll();
  setInterval(poll, POLL_MS);
}

init();
