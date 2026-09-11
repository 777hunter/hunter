/* TWI 작업지도서(3열) .docx 렌더러.
 * build_ji.py 가 만든 스펙 JSON 을 받아 문서를 찍는다.
 *   node ji_sheet.js spec.json out.docx
 */
const fs = require("fs");
const path = require("path");
const {
  AlignmentType, BorderStyle, Document, HeadingLevel, ImageRun, PageBreak,
  PageOrientation, Packer, Paragraph, ShadingType, Table, TableCell, TableRow,
  TextRun, VerticalAlign, WidthType,
} = require("docx");

const [, , specPath, outPath] = process.argv;
if (!specPath || !outPath) {
  console.error("사용법: node ji_sheet.js spec.json out.docx");
  process.exit(1);
}
const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
const FONT = spec.font_name || "맑은 고딕";

const INK = "1A1F1D", MUTED = "6B7370", ACCENT = "1E4F52", WARN = "8E5A16";
const HEAD_BG = "E8EDEA", BLANK_BG = "FBF4E8";
const USABLE = 15398;                       // A4 가로 - 좌우 여백
const COLS = [720, 3500, 3400, 3900, 3878]; // 순번 사진 주요단계 급소 이유

const run = (text, o = {}) => new TextRun({
  text: String(text ?? ""), font: FONT, size: o.size || 18,
  bold: !!o.bold, color: o.color || INK, italics: !!o.italics,
});
const para = (text, o = {}) => new Paragraph({
  alignment: o.align, spacing: { before: o.before || 0, after: o.after ?? 40 },
  children: Array.isArray(text) ? text : [run(text, o)],
  ...(o.border ? { border: o.border } : {}),
});
const cell = (children, o = {}) => new TableCell({
  width: { size: o.width, type: WidthType.DXA },
  columnSpan: o.span, verticalAlign: o.valign || VerticalAlign.TOP,
  margins: { top: 70, bottom: 70, left: 90, right: 90 },
  shading: o.fill ? { type: ShadingType.CLEAR, fill: o.fill, color: "auto" } : undefined,
  children: Array.isArray(children) ? children : [children],
});
const table = (rows, widths) => new Table({
  columnWidths: widths, width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
  rows,
});
const label = (t, w, fill) => cell(para(t, { bold: true, size: 16, color: MUTED }),
  { width: w, fill: fill || HEAD_BG });
const value = (t, w) => cell(para(t, { size: 18 }), { width: w });
const blankCell = (w, hint) => cell(para(hint || "", { size: 16, color: MUTED, italics: true }),
  { width: w, fill: BLANK_BG });

function image(meta, widthPx) {
  if (!meta || !fs.existsSync(meta.path)) return null;
  const ext = path.extname(meta.path).toLowerCase();
  return new ImageRun({
    data: fs.readFileSync(meta.path),
    type: ext === ".png" ? "png" : "jpg",
    transformation: { width: widthPx, height: Math.round(widthPx * meta.aspect) },
  });
}

/* ── 표제와 관리 정보 ───────────────────────────────────────── */
const h = spec.header || {};
const body = [
  para([run("작업지도서", { size: 34, bold: true }),
        run("   Job Instruction Sheet", { size: 18, color: MUTED })], { after: 60 }),
  para(h.job_name || "(작업명 미기입)",
    { size: 24, color: ACCENT, bold: true, after: 140 }),
  table([
    new TableRow({ children: [
      label("문서번호", 1900), value(h.doc_no || "", 2200),
      label("개정", 1200), value(h.revision || "", 1400),
      label("작성일", 1400), value(h.date || "", 1900),
      label("작성자", 1400), value(h.author || "", 1900),
      label("승인", 1200), value("", 1898),
    ] }),
  ], [1900, 2200, 1200, 1400, 1400, 1900, 1400, 1900, 1200, 1898]),
  para("", { after: 120 }),
  table([
    new TableRow({ children: [
      label("공정명", 1500), value(h.process || "", 2600),
      label("설비", 1200), blankCell(2600, h.equipment || "기입 필요"),
      label("치공구", 1300), blankCell(2600, h.tooling || "기입 필요"),
      label("보호구", 1300), blankCell(2298, h.ppe || "기입 필요"),
    ] }),
  ], [1500, 2600, 1200, 2600, 1300, 2600, 1300, 2298]),
  para("", { after: 120 }),
];

/* ── 관측 요약: 라벨/값 3쌍씩 ──────────────────────────────── */
const obsRows = [];
const W = [1800, 3333, 1800, 3333, 1800, 3332];
for (let i = 0; i < spec.observation.length; i += 3) {
  const cells = [];
  for (let j = 0; j < 3; j++) {
    const item = spec.observation[i + j];
    cells.push(label(item ? item[0] : "", W[j * 2]));
    cells.push(value(item ? item[1] : "", W[j * 2 + 1]));
  }
  obsRows.push(new TableRow({ children: cells }));
}
body.push(para("관측 요약", { bold: true, size: 20, after: 60 }));
body.push(table(obsRows, W));
body.push(para([
  run("이 문서는 작업 영상 분석으로 만든 ", { size: 16, color: WARN }),
  run("초안", { size: 16, color: WARN, bold: true }),
  run("이다. 주요단계와 시간은 관측값이지만, 급소의 이유와 음영 칸은 작성자가 채워야 한다. "
      + "승인 전에는 현장에 게시하지 말 것.", { size: 16, color: WARN }),
], { before: 140, after: 160 }));

/* ── 작업분해표 ────────────────────────────────────────────── */
const headRow = new TableRow({
  tableHeader: true,
  children: [
    cell(para("순번", { bold: true, size: 17, align: AlignmentType.CENTER }), { width: COLS[0], fill: HEAD_BG }),
    cell(para("사진", { bold: true, size: 17 }), { width: COLS[1], fill: HEAD_BG }),
    cell(para("주요단계", { bold: true, size: 17 }), { width: COLS[2], fill: HEAD_BG }),
    cell(para("급소", { bold: true, size: 17 }), { width: COLS[3], fill: HEAD_BG }),
    cell(para("급소의 이유", { bold: true, size: 17 }), { width: COLS[4], fill: HEAD_BG }),
  ],
});

const stepRows = spec.steps.map((s) => {
  const img = image(s.photo, 215);
  const photoCell = img
    ? cell([new Paragraph({ children: [img], spacing: { after: 30 } }),
            para(s.photo.caption, { size: 14, color: MUTED })], { width: COLS[1] })
    : blankCell(COLS[1], "사진 없음 — 직접 촬영");

  const stepCell = cell([
    para(s.name, { size: 19, bold: true }),
    para(`${s.time_s}초` + (s.spread ? `  (${s.spread})` : ""), { size: 15, color: MUTED }),
    para(`동작 ${s.signature} · 관측 ${s.presence}`, { size: 14, color: MUTED }),
  ], { width: COLS[2] });

  const kpParas = s.key_points.map((k) =>
    k.source === "빈칸"
      ? para("(관측에서 나온 신호 없음 — 기입 필요)", { size: 16, color: MUTED, italics: true })
      : para([run("· ", { size: 17, color: ACCENT }), run(k.text, { size: 17 })]));
  const kpCell = cell(kpParas, { width: COLS[3] });

  const filled = (s.reasons || "").trim();
  const reasonCell = filled
    ? cell(filled.split(/\n+/).map((line) => para(line, { size: 17 })), { width: COLS[4] })
    : cell([
        para("", { size: 17, after: 260,
          border: { bottom: { style: BorderStyle.DOTTED, size: 4, color: "BBBBBB" } } }),
        para("", { size: 17, after: 260,
          border: { bottom: { style: BorderStyle.DOTTED, size: 4, color: "BBBBBB" } } }),
      ], { width: COLS[4], fill: BLANK_BG });

  return new TableRow({
    children: [
      cell(para(String(s.no), { bold: true, size: 20, align: AlignmentType.CENTER }), { width: COLS[0] }),
      photoCell, stepCell, kpCell, reasonCell,
    ],
  });
});

body.push(para("작업분해", { bold: true, size: 20, after: 60 }));
body.push(table([headRow, ...stepRows], COLS));

/* ── 부록 ──────────────────────────────────────────────────── */
body.push(new Paragraph({ children: [new PageBreak()] }));
body.push(para("부록 A. 관측 기록", { size: 24, bold: true, after: 100 }));

const cycW = [1400, 1800, 1800];
body.push(para("사이클별 소요시간", { bold: true, size: 18, after: 50 }));
body.push(table([
  new TableRow({ tableHeader: true, children: [
    label("사이클", cycW[0]), label("소요시간", cycW[1]), label("중앙값 대비", cycW[2]),
  ] }),
  ...spec.cycle_rows.map((r) => new TableRow({ children: [
    value(`${r.no}회차`, cycW[0]), value(`${r.seconds}초`, cycW[1]), value(r.delta, cycW[2]),
  ] })),
], cycW));

body.push(para("변동 구간", { bold: true, size: 18, before: 200, after: 50 }));
if (spec.variations.length) {
  const vw = [2200, 2200, 7000];
  body.push(table([
    new TableRow({ tableHeader: true, children: [
      label("위치", vw[0]), label("종류", vw[1]), label("내용", vw[2]),
    ] }),
    ...spec.variations.map((v) => new TableRow({ children: [
      value(v.where, vw[0]), value(v.type, vw[1]), value(v.detail, vw[2]),
    ] })),
  ], vw));
} else {
  body.push(para("관측 구간에서 표준 순서를 벗어난 사이클이 없었다.", { size: 17, color: MUTED }));
}

const chartImg = image(spec.chart, 1010);
if (chartImg) {
  body.push(new Paragraph({ children: [new PageBreak()] }));
  body.push(para("부록 B. 사이클 정합", { size: 24, bold: true, after: 100 }));
  body.push(new Paragraph({ children: [chartImg] }));
  body.push(para("맨 윗줄이 표준(중앙값), 아래가 관측한 각 사이클. 숫자는 요소 순번이고 "
    + "붉은 테두리와 * 는 표준 순서를 벗어난 요소다.", { size: 16, color: MUTED, before: 80 }));
}

/* ── 부록 C. 포카요케 리스크 ───────────────────────────────── */
if ((spec.risks || []).length) {
  body.push(new Paragraph({ children: [new PageBreak()] }));
  body.push(para("부록 C. 포카요케 리스크 신호", { size: 24, bold: true, after: 60 }));
  const sm = spec.risk_summary || {};
  body.push(para(
    sm.defect_source
      ? `신호 ${sm.total}건 · 불량 이력이 연결된 신호 ${sm.defect_linked}건. `
        + "키워드 매칭이므로 연결이 맞는지 한 번 확인할 것."
      : `신호 ${sm.total}건. 불량 이력을 붙이지 않았으므로 아래 심각도는 관측 신호만 보고 `
        + "매긴 값이다. 실제 우선순위는 불량 이력이나 공정 FMEA 를 붙여야 나온다.",
    { size: 16, color: WARN, after: 120 }));

  const rw = [1000, 2500, 2400, 3100, 2000, 4398];
  const sevFill = { "상": "F6DFDA", "중": "F6EAD7", "하": "EDEFEA" };
  const riskRows = [new TableRow({ tableHeader: true, children: [
    label("심각도", rw[0]), label("신호", rw[1]), label("대상 단계", rw[2]),
    label("근거", rw[3]), label("의심 불량 / 이력", rw[4]), label("포카요케 후보", rw[5]),
  ] })];
  for (const r of spec.risks) {
    riskRows.push(new TableRow({ children: [
      cell([para(r.severity, { bold: true, size: 18, align: AlignmentType.CENTER }),
            para(r.id, { size: 13, color: MUTED, align: AlignmentType.CENTER })],
           { width: rw[0], fill: sevFill[r.severity] || HEAD_BG }),
      cell(para(r.signal, { size: 17, bold: true }), { width: rw[1] }),
      cell(para(r.target, { size: 16 }), { width: rw[2] }),
      cell([para(r.evidence, { size: 16 }),
            ...(r.needs ? [para(r.needs, { size: 14, color: WARN, italics: true })] : [])],
           { width: rw[3] }),
      cell([para(r.suspect, { size: 16 }),
            ...(r.defects ? [para(r.defects, { size: 16, bold: true, color: WARN })] : [])],
           { width: rw[4] }),
      cell(r.measures.map((m) => para("· " + m, { size: 16 })), { width: rw[5] }),
    ] }));
  }
  body.push(table(riskRows, rw));
  body.push(para("채택 여부와 투자 판단은 사람이 한다. 이 표는 영상에서 나온 신호와 "
    + "일반적인 대책 후보를 짝지어 놓은 것이다.", { size: 15, color: MUTED, before: 100 }));
}

/* ── 미기입 체크리스트와 서명 ──────────────────────────────── */
body.push(new Paragraph({ children: [new PageBreak()] }));
body.push(para("승인 전 채워야 할 항목", { size: 24, bold: true, after: 100 }));
spec.blanks.forEach((b, i) => {
  body.push(para([run("☐  ", { size: 18 }), run(b, { size: 17 })], { after: 70 }));
  if (i === spec.blanks.length - 1) body.push(para("", { after: 160 }));
});

const sigW = [2600, 3400, 2600, 3400];
body.push(para("검토 및 승인", { bold: true, size: 20, before: 200, after: 60 }));
body.push(table([
  new TableRow({ children: [
    label("작성", sigW[0]), blankCell(sigW[1], "서명 / 일자"),
    label("검토", sigW[2]), blankCell(sigW[3], "서명 / 일자"),
  ] }),
  new TableRow({ children: [
    label("승인", sigW[0]), blankCell(sigW[1], "서명 / 일자"),
    label("게시일", sigW[2]), blankCell(sigW[3], ""),
  ] }),
], sigW));

const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: 18, color: INK } } } },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838, orientation: PageOrientation.LANDSCAPE },
        margin: { top: 720, right: 720, bottom: 720, left: 720 },
      },
    },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(outPath, buf);
  console.log(`${outPath}  ${(buf.length / 1024).toFixed(0)} KB  단계 ${spec.steps.length}개`);
});
