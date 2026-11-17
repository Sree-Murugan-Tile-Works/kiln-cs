"use strict";
// The picture of the exhaust path. Every number drawn here comes from the `profile` object the
// Python simulation sends in /api/state; this file only turns it into shapes.
//
//   tube colour      = gas temperature
//   particles        = gas molecules per unit volume (pressure / temperature), same scale inside
//                      the tube and in the sky, so the two can be compared by eye
//   particle speed   = gas velocity, at the chimney's height scale
//
// Heights are to scale. Tube widths are drawn WIDTH_EXAGGERATION times wider so there is room for
// the particles. Horizontal distances are schematic.

const Scene = (() => {
  const WIDTH_EXAGGERATION = 3;
  const PARTICLES_PER_PX2 = 0.02;        // at the density of outside air at ground level
  const SKY_BAND_PX = 12;
  const GROUND_PX = 74;
  const TOP_MARGIN_PX = 44;
  const HEADROOM = 1.14;                 // sky kept above the chimney top, as a multiple of its height
  const MAX_FRAME_S = 0.05;
  const TEMP_STOPS = [[43, 108, 176], [86, 180, 233], [246, 224, 94], [237, 137, 54], [197, 48, 48]];
  const FT_PER_M = 3.28084;

  let canvas, ctx, strip, stripCtx;
  let profile = null, record = null, values = {};
  let exaggerate = true, moving = true;
  let layout = null, cells = [], skyCache = null, skyKey = "";
  let fanAngle = 0, lastFrame = 0;

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? "–" : Number(v).toFixed(d);
  const densityOf = (item) => exaggerate ? item.density_exaggerated : item.density_true;

  // Small seeded random generator, so sky dots stay where they are from frame to frame.
  function seeded(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function tempRange() {
    const lo = profile.ground.t_amb_c;
    const hottest = Math.max(...profile.stations.map((s) => s.t_c));
    return [lo, Math.max(hottest, lo + 40)];
  }

  function tempColor(t) {
    const [lo, hi] = tempRange();
    const f = Math.max(0, Math.min(1, (t - lo) / (hi - lo))) * (TEMP_STOPS.length - 1);
    const i = Math.min(TEMP_STOPS.length - 2, Math.floor(f));
    const k = f - i;
    const c = TEMP_STOPS[i].map((v, j) => Math.round(v + (TEMP_STOPS[i + 1][j] - v) * k));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  }

  // ---------------------------------------------------------------- layout
  function sizeCanvas(c) {
    const ratio = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (c.width !== Math.round(w * ratio) || c.height !== Math.round(h * ratio)) {
      c.width = Math.round(w * ratio); c.height = Math.round(h * ratio);
    }
    const context = c.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return [context, w, h];
  }

  function computeLayout(w, h) {
    const g = profile.geometry;
    const groundY = h - GROUND_PX;
    const pxPerM = (groundY - TOP_MARGIN_PX) / (g.height_m * HEADROOM);
    const tube = (metres) => metres * pxPerM * WIDTH_EXAGGERATION;
    const ductW = Math.max(14, tube(g.duct_diameter_m));
    const baseW = Math.max(10, tube(g.bottom_side_m)), topW = Math.max(6, tube(g.top_side_m));
    const chimX = w * 0.84;
    const kilnLeft = w * 0.02, kilnRight = w * 0.17;
    return {
      w, h, groundY, pxPerM, ductW, baseW, topW, chimX, kilnLeft, kilnRight,
      ductY: groundY - ductW / 2,                    // centre line of the horizontal duct
      fanX: w * 0.36, fanR: ductW * 0.85, plateX: w * 0.56, restrictionX: w * 0.69,
      chimTopY: groundY - g.height_m * pxPerM,
      zToY: (z) => groundY - z * pxPerM,
      sideToW: (side) => Math.max(6, tube(side)),
    };
  }

  // ---------------------------------------------------------------- particle cells
  // The tube is cut into cells. Each cell keeps as many particles as its gas density asks for and
  // moves them along the flow at the gas velocity; a particle leaving a cell re-enters at its start.
  function buildCells() {
    const L = layout, by = Object.fromEntries(profile.stations.map((s) => [s.key, s]));
    const list = [];
    const horizontal = (x0, x1, from, to) => {
      const n = Math.max(1, Math.round((x1 - x0) / 36));
      for (let i = 0; i < n; i++) {
        const f = (i + 0.5) / n, a = x0 + (x1 - x0) * i / n, b = x0 + (x1 - x0) * (i + 1) / n;
        list.push({ kind: "h", x0: a, x1: b, y: L.ductY, w: L.ductW,
          density: densityOf(from) + (densityOf(to) - densityOf(from)) * f,
          v: to.v_m_s || 0, area: (b - a) * L.ductW, length: b - a });
      }
    };
    horizontal(L.kilnRight, L.fanX - L.fanR, by.kiln, by.fan_in);
    horizontal(L.fanX + L.fanR, L.plateX, by.fan_out, by.p1);
    horizontal(L.plateX, L.restrictionX, by.p2, by.p2);
    horizontal(L.restrictionX, L.chimX - L.baseW / 2, by.chimney_base, by.chimney_base);
    const dz = profile.geometry.height_m / profile.chimney.length;
    for (const s of profile.chimney) {
      const y0 = L.zToY(s.z_m - dz / 2), y1 = L.zToY(s.z_m + dz / 2), width = L.sideToW(s.side_m);
      list.push({ kind: "v", x: L.chimX, y0, y1, w: width, density: densityOf(s), v: s.v_m_s,
        area: (y0 - y1) * width, length: y0 - y1 });
    }
    // Keep the particles of cells that still exist, so a new profile does not make them jump.
    list.forEach((cell, i) => {
      const old = cells[i];
      cell.particles = old && old.kind === cell.kind ? old.particles : [];
      cell.dither = old ? old.dither : Math.random();
      const wanted = Math.floor(cell.density * cell.area * PARTICLES_PER_PX2 + cell.dither);
      while (cell.particles.length < wanted) cell.particles.push({ a: Math.random(), b: Math.random() });
      cell.particles.length = Math.min(cell.particles.length, wanted);
    });
    cells = list;
  }

  function moveParticles(dt) {
    for (const cell of cells) {
      const step = cell.v * layout.pxPerM * dt / cell.length;
      for (const p of cell.particles) {
        p.a += step;
        if (p.a >= 1) { p.a -= Math.floor(p.a); p.b = Math.random(); }
      }
    }
  }

  // ---------------------------------------------------------------- sky
  function outsideDensityAt(z) {
    const points = [[0, densityOf(profile.ground)]];
    for (const s of profile.chimney) points.push([s.z_m, densityOf(s.outside)]);
    points.push([profile.top.z_m, densityOf(profile.top.outside)]);
    for (let i = 1; i < points.length; i++) {
      if (z <= points[i][0]) {
        const [z0, d0] = points[i - 1], [z1, d1] = points[i];
        return d0 + (d1 - d0) * (z - z0) / (z1 - z0);
      }
    }
    const [z0, d0] = points[points.length - 2], [z1, d1] = points[points.length - 1];
    return Math.max(0.03, d1 + (d1 - d0) * (z - z1) / (z1 - z0));     // above the chimney top
  }

  function drawSky() {
    const L = layout;
    const key = [L.w, L.h, exaggerate, profile.geometry.height_m, profile.top.outside.density_exaggerated.toFixed(3)].join("|");
    if (key !== skyKey) {
      skyKey = key;
      skyCache = document.createElement("canvas");
      const ratio = window.devicePixelRatio || 1;
      skyCache.width = Math.round(L.w * ratio); skyCache.height = Math.round(L.h * ratio);
      const c = skyCache.getContext("2d");
      c.setTransform(ratio, 0, 0, ratio, 0, 0);
      const gradient = c.createLinearGradient(0, 0, 0, L.groundY);
      gradient.addColorStop(0, "#2f7fd6"); gradient.addColorStop(1, "#9ccdf2");
      c.fillStyle = gradient; c.fillRect(0, 0, L.w, L.groundY);
      c.fillStyle = "rgba(255,255,255,0.78)";
      for (let y = 0, band = 0; y < L.groundY; y += SKY_BAND_PX, band++) {
        const z = (L.groundY - (y + SKY_BAND_PX / 2)) / L.pxPerM;
        const random = seeded(1000 + band);
        const count = Math.round(outsideDensityAt(z) * L.w * SKY_BAND_PX * PARTICLES_PER_PX2);
        for (let i = 0; i < count; i++) c.fillRect(random() * L.w, y + random() * SKY_BAND_PX, 1.6, 1.6);
      }
    }
    ctx.drawImage(skyCache, 0, 0, L.w, L.h);
  }

  // ---------------------------------------------------------------- drawing helpers
  function label(x, y, lines, align = "center") {
    ctx.font = "12px system-ui, 'Segoe UI', sans-serif";
    const width = Math.max(...lines.map((t) => ctx.measureText(t).width)) + 12, height = lines.length * 15 + 6;
    let left = align === "center" ? x - width / 2 : align === "right" ? x - width : x;
    left = Math.max(2, Math.min(layout.w - width - 2, left));
    ctx.fillStyle = "rgba(255,255,255,0.9)";
    ctx.strokeStyle = "rgba(20,30,45,0.35)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(left, y, width, height, 5); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#16202c"; ctx.textAlign = "left"; ctx.textBaseline = "top";
    lines.forEach((text, i) => {
      ctx.font = (i === 0 ? "600 " : "") + "12px system-ui, 'Segoe UI', sans-serif";
      ctx.fillText(text, left + 6, y + 4 + i * 15);
    });
  }

  function leader(x0, y0, x1, y1) {
    ctx.strokeStyle = "rgba(20,30,45,0.55)"; ctx.lineWidth = 1; ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); ctx.setLineDash([]);
  }

  function drawTube() {
    const L = layout, by = Object.fromEntries(profile.stations.map((s) => [s.key, s]));
    const top = L.ductY - L.ductW / 2, edge = "#243140";
    // ground
    ctx.fillStyle = "#6f7b5c"; ctx.fillRect(0, L.groundY, L.w, L.h - L.groundY);
    ctx.fillStyle = "#58634a"; ctx.fillRect(0, L.groundY, L.w, 3);
    // horizontal duct, one colour: the gas keeps its temperature until the chimney
    ctx.fillStyle = tempColor(by.fan_in.t_c);
    ctx.fillRect(L.kilnRight, top, L.chimX - L.kilnRight, L.ductW);
    // chimney, slice by slice
    const dz = profile.geometry.height_m / profile.chimney.length;
    for (const s of profile.chimney) {
      const y0 = L.zToY(s.z_m - dz / 2), y1 = L.zToY(s.z_m + dz / 2);
      const w0 = L.sideToW(s.side_m + (profile.geometry.bottom_side_m - profile.geometry.top_side_m) / profile.chimney.length / 2);
      const w1 = L.sideToW(s.side_m - (profile.geometry.bottom_side_m - profile.geometry.top_side_m) / profile.chimney.length / 2);
      ctx.fillStyle = tempColor(s.t_c);
      ctx.beginPath();
      ctx.moveTo(L.chimX - w0 / 2, y0 + 0.5); ctx.lineTo(L.chimX + w0 / 2, y0 + 0.5);
      ctx.lineTo(L.chimX + w1 / 2, y1); ctx.lineTo(L.chimX - w1 / 2, y1); ctx.closePath(); ctx.fill();
    }
    // outlines
    ctx.strokeStyle = edge; ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(L.kilnRight, top); ctx.lineTo(L.chimX - L.baseW / 2, top);
    ctx.lineTo(L.chimX - L.topW / 2, L.chimTopY);
    ctx.moveTo(L.chimX + L.topW / 2, L.chimTopY); ctx.lineTo(L.chimX + L.baseW / 2, L.groundY);
    ctx.lineTo(L.kilnRight, L.groundY);
    ctx.stroke();
    // kiln
    ctx.fillStyle = "#a5553a"; ctx.strokeStyle = edge;
    const kilnTop = L.groundY - Math.max(L.ductW * 2.1, 70);
    ctx.beginPath(); ctx.roundRect(L.kilnLeft, kilnTop, L.kilnRight - L.kilnLeft, L.groundY - kilnTop, [26, 26, 0, 0]);
    ctx.fill(); ctx.stroke();
    ctx.fillStyle = tempColor(by.kiln.t_c);
    ctx.fillRect(L.kilnRight - 14, top + 1, 15, L.ductW - 1);
    // orifice plate: two bars leaving the bore open
    const gap = L.ductW * profile.geometry.plate_beta, bar = (L.ductW - gap) / 2;
    ctx.fillStyle = "#101820";
    ctx.fillRect(L.plateX - 3, top, 6, bar); ctx.fillRect(L.plateX - 3, top + bar + gap, 6, bar);
    // restriction: a throat whose opening follows the restriction free area
    const ductArea = Math.PI / 4 * profile.geometry.duct_diameter_m ** 2;
    const open = Math.max(0.12, Math.min(1, Math.sqrt((values.restriction_free_area_m2 || ductArea) / ductArea)));
    const pinch = L.ductW * (1 - open) / 2;
    if (pinch > 1) {
      ctx.fillStyle = "#3b4756";
      ctx.beginPath(); ctx.moveTo(L.restrictionX - 14, top); ctx.lineTo(L.restrictionX, top + pinch); ctx.lineTo(L.restrictionX + 14, top); ctx.fill();
      ctx.beginPath(); ctx.moveTo(L.restrictionX - 14, L.groundY); ctx.lineTo(L.restrictionX, L.groundY - pinch); ctx.lineTo(L.restrictionX + 14, L.groundY); ctx.fill();
    }
  }

  function drawFan() {
    const L = layout;
    ctx.save(); ctx.translate(L.fanX, L.ductY);
    ctx.fillStyle = "#eef2f7"; ctx.strokeStyle = "#243140"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(0, 0, L.fanR, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.rotate(fanAngle);
    ctx.strokeStyle = "#2a6fdb"; ctx.lineWidth = Math.max(4, L.fanR * 0.2); ctx.lineCap = "round";
    for (let i = 0; i < 3; i++) {
      ctx.rotate(Math.PI * 2 / 3);
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, -L.fanR * 0.78); ctx.stroke();
    }
    ctx.fillStyle = "#16202c"; ctx.beginPath(); ctx.arc(0, 0, Math.max(3, L.fanR * 0.14), 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }

  function drawParticles() {
    ctx.fillStyle = "rgba(10,16,24,0.72)";
    for (const cell of cells) {
      for (const p of cell.particles) {
        if (cell.kind === "h") {
          ctx.fillRect(cell.x0 + p.a * (cell.x1 - cell.x0), cell.y - cell.w / 2 + 2 + p.b * (cell.w - 5), 2, 2);
        } else {
          ctx.fillRect(cell.x - cell.w / 2 + 2 + p.b * (cell.w - 5), cell.y0 - p.a * (cell.y0 - cell.y1), 2, 2);
        }
      }
    }
  }

  function drawLabels() {
    const L = layout, by = Object.fromEntries(profile.stations.map((s) => [s.key, s]));
    const top = L.ductY - L.ductW / 2, calcs = profile.calcs, g = profile.geometry;
    const above = top - 44, below = L.groundY + 8;
    const kilnTop = L.groundY - Math.max(L.ductW * 2.1, 70);
    label((L.kilnLeft + L.kilnRight) / 2, kilnTop + 10, ["Kiln", `${fmt(by.kiln.t_c)} °C`, `${fmt(by.kiln.p_gauge_pa)} Pa`]);
    label(L.fanX - L.fanR - 46, above, ["Fan inlet", `${fmt(by.fan_in.p_gauge_pa)} Pa`]);
    label(L.fanX, below, [`Fan ${fmt(record ? record.rpm_actual : null)} rpm`, `adds ${fmt(calcs.budget.sources.fan_pa)} Pa`]);
    label(L.plateX - 34, above, ["P1", `${fmt(by.p1.p_gauge_pa, 1)} Pa`], "right");
    label(L.plateX + 6, above, ["P2", `${fmt(by.p2.p_gauge_pa, 1)} Pa`], "left");
    leader(L.plateX - 12, top, L.plateX - 40, above + 36); leader(L.plateX + 12, top, L.plateX + 14, above + 36);
    label(L.plateX, below, ["Orifice plate", `ΔP ${fmt(by.p1.p_gauge_pa - by.p2.p_gauge_pa, 1)} Pa`, `${fmt(calcs.q_plate_m3_s, 2)} m³/s`]);
    label(L.restrictionX + 4, below, ["Restriction", `−${fmt(calcs.budget.losses.restriction_pa)} Pa`], "left");
    label(L.chimX - L.baseW / 2 - 8, above, ["Chimney base", `${fmt(by.chimney_base.p_gauge_pa)} Pa`], "right");
    const midY = (L.chimTopY + L.groundY) / 2;
    label(L.chimX - L.baseW / 2 - 12, midY - 20, ["Chimney", `draft ${fmt(calcs.budget.sources.draft_pa)} Pa`,
      `${fmt(g.height_m, 1)} m (${fmt(g.height_m * FT_PER_M)} ft)`], "right");
    label(L.chimX + L.topW / 2 + 8, L.chimTopY - 4, ["Top", `${fmt(profile.top.t_c)} °C`, `${fmt(profile.top.v_m_s, 1)} m/s`,
      `${fmt(g.top_side_m, 2)} m square`], "left");
    // outside air at the height of the chimney top, and at the ground
    ctx.strokeStyle = "rgba(255,255,255,0.75)"; ctx.setLineDash([6, 5]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, L.chimTopY); ctx.lineTo(L.chimX - L.topW / 2 - 4, L.chimTopY); ctx.stroke(); ctx.setLineDash([]);
    const sky = profile.top.outside;
    label(8, L.chimTopY + 6, [`Outside air at ${fmt(g.height_m, 1)} m`, `${fmt(sky.p_abs_pa)} Pa`,
      `${fmt(sky.rho, 3)} kg/m³`, `${fmt(profile.ground.p_abs_pa - sky.p_abs_pa)} Pa below ground level`], "left");
    label(8, kilnTop - 76, ["Outside air at ground", `${fmt(profile.ground.p_abs_pa)} Pa`,
      `${fmt(profile.ground.rho, 3)} kg/m³`, `${fmt(profile.ground.t_amb_c, 1)} °C`], "left");
  }

  function drawLegend() {
    const L = layout, [lo, hi] = tempRange(), x = L.w - 150, y = L.h - 30, w = 120;
    const gradient = ctx.createLinearGradient(x, 0, x + w, 0);
    TEMP_STOPS.forEach((c, i) => gradient.addColorStop(i / (TEMP_STOPS.length - 1), `rgb(${c[0]},${c[1]},${c[2]})`));
    ctx.fillStyle = gradient; ctx.fillRect(x, y, w, 10);
    ctx.strokeStyle = "#16202c"; ctx.lineWidth = 1; ctx.strokeRect(x, y, w, 10);
    ctx.fillStyle = "#ffffff"; ctx.font = "11px system-ui, sans-serif"; ctx.textBaseline = "top";
    ctx.textAlign = "left"; ctx.fillText(`${fmt(lo)} °C`, x, y + 13);
    ctx.textAlign = "right"; ctx.fillText(`${fmt(hi)} °C`, x + w, y + 13);
    ctx.textAlign = "center"; ctx.fillText("gas temperature", x + w / 2, y - 14);
  }

  function frame(now) {
    requestAnimationFrame(frame);
    if (!profile || !canvas.clientWidth) return;
    const dt = Math.min(MAX_FRAME_S, (now - lastFrame) / 1000 || 0);
    lastFrame = now;
    let w, h;
    [ctx, w, h] = sizeCanvas(canvas);
    if (!layout || layout.w !== w || layout.h !== h) { layout = computeLayout(w, h); buildCells(); }
    if (moving) {
      moveParticles(dt);
      fanAngle += (record ? record.rpm_actual : 0) / 60 * Math.PI * 2 * dt;
    }
    ctx.clearRect(0, 0, w, h);
    drawSky(); drawTube(); drawParticles(); drawFan(); drawLabels(); drawLegend();
  }

  // ---------------------------------------------------------------- pressure strip
  function drawStrip() {
    if (!profile || !layout || !strip.clientWidth) return;
    let w, h;
    [stripCtx, w, h] = sizeCanvas(strip);
    const c = stripCtx, L = layout, by = Object.fromEntries(profile.stations.map((s) => [s.key, s]));
    const losses = profile.calcs.budget.losses, pad = { top: 16, bottom: 22, right: 12 };
    const recovered = by.chimney_base.p_gauge_pa + losses.restriction_pa;       // after the plate's pressure recovery
    const chimneyX = (z) => L.chimX + (z / profile.geometry.height_m) * (w - pad.right - L.chimX);
    const points = [
      [L.kilnRight, by.kiln.p_gauge_pa], [L.fanX - L.fanR, by.fan_in.p_gauge_pa], [L.fanX + L.fanR, by.fan_out.p_gauge_pa],
      [L.plateX - 3, by.p1.p_gauge_pa], [L.plateX + 3, by.p2.p_gauge_pa], [L.plateX + 26, recovered],
      [L.restrictionX - 6, recovered], [L.restrictionX + 6, by.chimney_base.p_gauge_pa], [L.chimX, by.chimney_base.p_gauge_pa],
      ...profile.chimney.map((s) => [chimneyX(s.z_m), s.p_gauge_local_pa]),
      [w - pad.right - 1, profile.top.p_gauge_local_pa], [w - pad.right, 0],
    ];
    let lo = Math.min(0, ...points.map((p) => p[1])), hi = Math.max(0, ...points.map((p) => p[1]));
    const span = Math.max(hi - lo, 20); lo -= span * 0.12; hi += span * 0.12;
    const y = (v) => pad.top + (1 - (v - lo) / (hi - lo)) * (h - pad.top - pad.bottom);
    c.clearRect(0, 0, w, h);
    c.fillStyle = css("--strip-chimney"); c.fillRect(L.chimX, pad.top, w - pad.right - L.chimX, h - pad.top - pad.bottom);
    for (const [sign, color] of [[1, css("--strip-pressure")], [-1, css("--strip-suction")]]) {
      c.fillStyle = color; c.beginPath(); c.moveTo(points[0][0], y(0));
      for (const [px, value] of points) c.lineTo(px, y(sign > 0 ? Math.max(0, value) : Math.min(0, value)));
      c.lineTo(points[points.length - 1][0], y(0)); c.closePath(); c.fill();
    }
    c.strokeStyle = css("--muted"); c.lineWidth = 1; c.setLineDash([3, 3]);
    c.beginPath(); c.moveTo(L.kilnLeft, y(0)); c.lineTo(w - pad.right, y(0)); c.stroke(); c.setLineDash([]);
    c.strokeStyle = css("--text"); c.lineWidth = 2; c.beginPath();
    points.forEach(([px, value], i) => (i ? c.lineTo(px, y(value)) : c.moveTo(px, y(value))));
    c.stroke();
    c.font = "11px system-ui, sans-serif"; c.fillStyle = css("--text"); c.textBaseline = "bottom"; c.textAlign = "center";
    const mark = (px, value, text) => {
      const ty = value >= 0 ? y(value) - 4 : y(value) + 15;
      c.fillText(`${text} ${fmt(value)}`, Math.max(40, Math.min(w - 44, px)), ty);
    };
    mark(L.fanX - L.fanR - 22, by.fan_in.p_gauge_pa, "fan in");
    mark(L.fanX + L.fanR + 24, by.fan_out.p_gauge_pa, "fan out");
    mark(L.plateX - 30, by.p1.p_gauge_pa, "P1");
    c.fillText(`P2 ${fmt(by.p2.p_gauge_pa)}`, L.plateX + 8, y(by.p2.p_gauge_pa) + 15);
    mark(L.chimX - 30, by.chimney_base.p_gauge_pa, "base");
    c.fillStyle = css("--muted"); c.textBaseline = "top"; c.textAlign = "left";
    c.fillText("dashed line: 0 = room, or outside air at the same height", L.kilnLeft, 1);
    c.textAlign = "center";
    c.fillText("up the chimney →", (L.chimX + w - pad.right) / 2, h - pad.bottom + 5);
    c.fillText("along the duct →", (L.kilnRight + L.chimX) / 2, h - pad.bottom + 5);
  }

  // ---------------------------------------------------------------- public
  return {
    init(sceneCanvas, stripCanvas) {
      canvas = sceneCanvas; strip = stripCanvas;
      requestAnimationFrame(frame);
    },
    update(newProfile, latestRecord, serverValues, running) {
      profile = newProfile; record = latestRecord; values = serverValues || {};
      const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      moving = running && !reduced;
      if (canvas.clientWidth) {
        layout = computeLayout(canvas.clientWidth, canvas.clientHeight);
        buildCells();
        drawStrip();
      }
    },
    setExaggerate(on) {
      exaggerate = on;
      if (profile && layout) { buildCells(); skyKey = ""; }
    },
    widthExaggeration: WIDTH_EXAGGERATION,
  };
})();
