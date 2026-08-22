/* 최소한의 SVG 차트 렌더러 — 외부 의존성 없음.
   막대 두께 24px 상한, 데이터 끝 4px 라운드, 선 2px, 마커 8px, 세그먼트 사이 2px 간격. */
const NS = "http://www.w3.org/2000/svg";
const SURFACE = "#fcfcfb";
const el = (n, a = {}) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); return e; };
const fmt = (v) => v.toLocaleString("ko-KR");

function frame(host, w, h) {
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img" });
  host.appendChild(svg);
  return svg;
}
function niceMax(raw, ticks = 4) {
  const rough = raw / ticks, mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].find(m => m * mag >= rough) * mag;
  return step * ticks;
}
function yAxis(svg, x0, x1, yTop, yBot, max, ticks = 4, unit = "") {
  for (let i = 0; i <= ticks; i++) {
    const v = (max / ticks) * i, y = yBot - (yBot - yTop) * (i / ticks);
    svg.appendChild(el("line", { x1: x0, x2: x1, y1: y, y2: y, stroke: i ? "#e1e0d9" : "#c3c2b7", "stroke-width": 1 }));
    const t = el("text", { x: x0 - 8, y: y + 4, "text-anchor": "end", "font-size": 10.5, fill: "#898781" });
    t.textContent = fmt(Math.round(v)) + unit; svg.appendChild(t);
  }
}
/* 위쪽 모서리만 둥근 세로 막대 */
function topRounded(x, y, w, h, r) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
}
function rightRounded(x, y, w, h, r) {
  r = Math.min(r, h / 2, w);
  return `M${x},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} L${x},${y + h} Z`;
}

/* 세로 막대 (단일/누적) */
function columns(host, { cats, series, height = 220, unit = "", labelLast = false }) {
  const w = 640, h = height, pad = { l: 46, r: 14, t: 14, b: 26 };
  const svg = frame(host, w, h);
  const totals = cats.map((_, i) => series.reduce((s, ss) => s + ss.values[i], 0));
  const max = niceMax(Math.max(...totals) * 1.08);
  yAxis(svg, pad.l, w - pad.r, pad.t, h - pad.b, max, 4, unit);
  const band = (w - pad.l - pad.r) / cats.length;
  const bw = Math.min(24, band * 0.55);
  cats.forEach((c, i) => {
    const cx = pad.l + band * i + band / 2 - bw / 2;
    let acc = 0;
    series.forEach((s, si) => {
      const v = s.values[i];
      const y0 = (h - pad.b) - (acc + v) / max * (h - pad.b - pad.t);
      const y1 = (h - pad.b) - acc / max * (h - pad.b - pad.t);
      let bh = y1 - y0;
      if (si < series.length - 1) bh = Math.max(0, bh); // 위 세그먼트가 2px 갭을 만든다
      const gap = si === series.length - 1 ? 0 : 0;
      const top = si === series.length - 1;
      const d = top ? topRounded(cx, y0, bw, bh - gap, 4)
                    : `M${cx},${y0 + 2} h${bw} v${Math.max(0, bh - 2)} h${-bw} Z`;
      svg.appendChild(el("path", { d, fill: s.color }));
      acc += v;
    });
    const t = el("text", { x: cx + bw / 2, y: h - pad.b + 15, "text-anchor": "middle", "font-size": 10.5, fill: "#898781" });
    t.textContent = c; svg.appendChild(t);
    if (labelLast && i === cats.length - 1) {
      const y = (h - pad.b) - totals[i] / max * (h - pad.b - pad.t);
      const lab = el("text", { x: cx + bw / 2, y: y - 8, "text-anchor": "middle", "font-size": 11.5, fill: "#0b0b0b", "font-weight": 650 });
      lab.textContent = fmt(totals[i]) + unit; svg.appendChild(lab);
    }
  });
  return svg;
}

/* 다중 꺾은선 (+ 선택적 영역) */
function lines(host, { x, series, height = 230, unit = "", area = false, yMax }) {
  const w = 640, h = height, pad = { l: 46, r: 54, t: 14, b: 26 };
  const svg = frame(host, w, h);
  const max = yMax || niceMax(Math.max(...series.flatMap(s => s.values)) * 1.12);
  yAxis(svg, pad.l, w - pad.r, pad.t, h - pad.b, max, 4, unit);
  const px = i => pad.l + (w - pad.l - pad.r) * (i / (x.length - 1));
  const py = v => (h - pad.b) - (v / max) * (h - pad.b - pad.t);
  x.forEach((c, i) => {
    if (x.length > 8 && i % 2) return;
    const t = el("text", { x: px(i), y: h - pad.b + 15, "text-anchor": "middle", "font-size": 10.5, fill: "#898781" });
    t.textContent = c; svg.appendChild(t);
  });
  series.forEach(s => {
    const d = s.values.map((v, i) => `${i ? "L" : "M"}${px(i)},${py(v)}`).join(" ");
    if (area) svg.appendChild(el("path", { d: `${d} L${px(x.length - 1)},${h - pad.b} L${px(0)},${h - pad.b} Z`, fill: s.color, "fill-opacity": .1 }));
    svg.appendChild(el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const li = s.values.length - 1;
    svg.appendChild(el("circle", { cx: px(li), cy: py(s.values[li]), r: 4, fill: s.color, stroke: SURFACE, "stroke-width": 2 }));
    const t = el("text", { x: px(li) + 9, y: py(s.values[li]) + 4, "font-size": 11, fill: "#52514e", "font-weight": 600 });
    t.textContent = fmt(s.values[li]) + unit; svg.appendChild(t);
  });
  return svg;
}

/* 가로 막대 */
function hbars(host, { data, height, unit = "", color = "#2a78d6", width = 640, rowH = 30 }) {
  const w = width, h = height || data.length * rowH + 16;
  const pad = { l: Math.round(Math.min(116, w * 0.3)), r: Math.round(Math.min(56, w * 0.17)), t: 8, b: 8 };
  const svg = frame(host, w, h);
  const max = Math.max(...data.map(d => d.value)) * 1.05;
  data.forEach((d, i) => {
    const y = pad.t + i * rowH, bh = Math.min(18, rowH - 12);
    const bw = (w - pad.l - pad.r) * (d.value / max);
    svg.appendChild(el("path", { d: rightRounded(pad.l, y + (rowH - bh) / 2 - 4, Math.max(bw, 3), bh, 4), fill: d.color || color }));
    const lab = el("text", { x: pad.l - 10, y: y + rowH / 2 - 0, "text-anchor": "end", "font-size": 11.5, fill: "#52514e" });
    lab.textContent = d.label; svg.appendChild(lab);
    const val = el("text", { x: pad.l + Math.max(bw, 3) + 8, y: y + rowH / 2, "font-size": 11.5, fill: "#0b0b0b", "font-weight": 600 });
    val.textContent = fmt(d.value) + unit; svg.appendChild(val);
  });
  return svg;
}

/* 히트맵 (연속 값 = 단일 색상 램프) */
function heatmap(host, { rows, cols, values, unit = "" }) {
  const w = 640, cell = 30, pad = { l: 92, t: 22 };
  const h = pad.t + rows.length * cell + 8;
  const svg = frame(host, w, h);
  const cw = (w - pad.l - 12) / cols.length;
  const max = Math.max(...values.flat()), min = Math.min(...values.flat());
  const ramp = ["#cde2fb", "#9ec5f4", "#6da7ec", "#2a78d6", "#1c5cab", "#104281"];
  cols.forEach((c, j) => {
    const t = el("text", { x: pad.l + cw * j + cw / 2, y: 14, "text-anchor": "middle", "font-size": 10.5, fill: "#898781" });
    t.textContent = c; svg.appendChild(t);
  });
  rows.forEach((r, i) => {
    const t = el("text", { x: pad.l - 10, y: pad.t + cell * i + cell / 2 + 4, "text-anchor": "end", "font-size": 11, fill: "#52514e" });
    t.textContent = r; svg.appendChild(t);
    cols.forEach((c, j) => {
      const v = values[i][j];
      if (v === null || v === undefined) {
        svg.appendChild(el("rect", { x: pad.l + cw * j + 1, y: pad.t + cell * i + 1, width: cw - 2, height: cell - 2, rx: 4, fill: "none", stroke: "#e1e0d9", "stroke-width": 1 }));
        return;
      }
      const k = Math.min(ramp.length - 1, Math.round((v - min) / ((max - min) || 1) * (ramp.length - 1)));
      svg.appendChild(el("rect", { x: pad.l + cw * j + 1, y: pad.t + cell * i + 1, width: cw - 2, height: cell - 2, rx: 4, fill: ramp[k] }));
      const tv = el("text", { x: pad.l + cw * j + cw / 2, y: pad.t + cell * i + cell / 2 + 4, "text-anchor": "middle", "font-size": 10.5, fill: k >= 3 ? "#fff" : "#0b0b0b" });
      tv.textContent = v + unit; svg.appendChild(tv);
    });
  });
  return svg;
}

/* 스파크라인 */
function sparkline(host, values, color = "#2a78d6") {
  const w = 160, h = 40, svg = frame(host, w, h);
  const max = Math.max(...values), min = Math.min(...values);
  const px = i => (w - 8) * (i / (values.length - 1)) + 4;
  const py = v => h - 6 - (v - min) / ((max - min) || 1) * (h - 14);
  const d = values.map((v, i) => `${i ? "L" : "M"}${px(i)},${py(v)}`).join(" ");
  svg.appendChild(el("path", { d: `${d} L${px(values.length - 1)},${h} L${px(0)},${h} Z`, fill: color, "fill-opacity": .1 }));
  svg.appendChild(el("path", { d, fill: "none", stroke: color, "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" }));
  svg.appendChild(el("circle", { cx: px(values.length - 1), cy: py(values[values.length - 1]), r: 4, fill: color, stroke: SURFACE, "stroke-width": 2 }));
  return svg;
}

/* 범위 막대 — 최저~최고처럼 구간을 나타낼 때 (0 기준선이 무의미한 값) */
function rangeBars(host, { cats, lo, hi, yMin, yMax, unit = "", color = "#eb6834", height = 230 }) {
  const w = 640, h = height, pad = { l: 46, r: 14, t: 20, b: 26 };
  const svg = frame(host, w, h);
  const lo0 = yMin !== undefined ? yMin : Math.floor(Math.min(...lo) / 5) * 5 - 5;
  const hi0 = yMax !== undefined ? yMax : Math.ceil(Math.max(...hi) / 5) * 5;
  const py = v => (h - pad.b) - (v - lo0) / (hi0 - lo0) * (h - pad.b - pad.t);
  for (let v = lo0; v <= hi0; v += (hi0 - lo0) / 4) {
    svg.appendChild(el("line", { x1: pad.l, x2: w - pad.r, y1: py(v), y2: py(v), stroke: v === lo0 ? "#c3c2b7" : "#e1e0d9", "stroke-width": 1 }));
    const t = el("text", { x: pad.l - 8, y: py(v) + 4, "text-anchor": "end", "font-size": 10.5, fill: "#898781" });
    t.textContent = Math.round(v) + unit; svg.appendChild(t);
  }
  const band = (w - pad.l - pad.r) / cats.length, bw = Math.min(14, band * 0.42);
  const peak = hi.indexOf(Math.max(...hi));
  cats.forEach((c, i) => {
    const x = pad.l + band * i + band / 2 - bw / 2;
    const y = py(hi[i]), bh = py(lo[i]) - y;
    svg.appendChild(el("rect", { x, y, width: bw, height: bh, rx: bw / 2, fill: i === peak ? "#d03b3b" : color }));
    const t = el("text", { x: x + bw / 2, y: h - pad.b + 15, "text-anchor": "middle", "font-size": 10.5, fill: "#898781" });
    t.textContent = c; svg.appendChild(t);
    if (i === peak) {
      const lab = el("text", { x: x + bw / 2, y: y - 7, "text-anchor": "middle", "font-size": 11.5, "font-weight": 650, fill: "#0b0b0b" });
      lab.textContent = hi[i] + unit; svg.appendChild(lab);
    }
  });
  return svg;
}
