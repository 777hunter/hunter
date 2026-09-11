"""사이클 정합 차트: 사이클마다 같은 순서로 하고 있는지 한눈에 본다."""
from __future__ import annotations

POS_COLOURS = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
               "#937860", "#DA8BC3", "#7F7F7F", "#CCB974", "#64B5CD"]
EXTRA_COLOUR = "#B03A2E"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_cycles(std: dict, cycles, path: str, title: str = "사이클 정합") -> str:
    rows = len(cycles) + 1
    ml, mr, mt = 92, 20, 74
    plot_w, row_h, gap = 900, 30, 9
    width = ml + plot_w + mr
    span = max([c[-1].end_s - c[0].start_s for c in cycles]
               + [sum(s["median_s"] for s in std["standard"])]) or 1.0
    n_pos = len(std["standard"])
    legend_rows = (n_pos + 2) // 3
    height = mt + rows * (row_h + gap) + 26 + legend_rows * 22 + 20

    def x(t):
        return ml + (t / span) * plot_w

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
         f'viewBox="0 0 {width} {height}" font-family="Pretendard, \'Malgun Gothic\', '
         f'\'Apple SD Gothic Neo\', system-ui, sans-serif">',
         f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
         f'<text x="{ml}" y="30" font-size="17" font-weight="700" fill="#1a1a1a">{_esc(title)}</text>',
         f'<text x="{ml}" y="50" font-size="12" fill="#666">'
         f'사이클 {std["cycle_count"]}회 · 요소 {n_pos}개 · 중앙 사이클타임 '
         f'{std["cycle_seconds"]["median"]}초 · 참조 사이클 {std["reference_cycle"]}번</text>']

    step = 1 if span <= 12 else (2 if span <= 30 else 5)
    t = 0.0
    while t <= span + 1e-6:
        p.append(f'<line x1="{x(t):.1f}" y1="{mt - 8}" x2="{x(t):.1f}" '
                 f'y2="{mt + rows * (row_h + gap)}" stroke="#ededed" stroke-width="1"/>')
        p.append(f'<text x="{x(t):.1f}" y="{mt - 14}" font-size="10" fill="#999" '
                 f'text-anchor="middle">{t:g}s</text>')
        t += step

    def band(y, label, blocks, bold=False):
        weight = "700" if bold else "400"
        p.append(f'<text x="{ml - 10}" y="{y + row_h / 2 + 4}" font-size="12" fill="#333" '
                 f'text-anchor="end" font-weight="{weight}">{_esc(label)}</text>')
        p.append(f'<rect x="{ml}" y="{y}" width="{plot_w}" height="{row_h}" fill="#fafafa" '
                 f'stroke="#e8e8e8"/>')
        for t0, t1, pos, tip, odd in blocks:
            x0, w = x(t0), max(x(t1) - x(t0), 1.2)
            colour = EXTRA_COLOUR if pos is None else POS_COLOURS[pos % len(POS_COLOURS)]
            if pos is None:
                extra = ' stroke="#7B241C" stroke-dasharray="3 2"'
            elif odd:
                extra = ' stroke="#7B241C" stroke-dasharray="4 2"'
            else:
                extra = ' stroke="#fff"'
            p.append(f'<rect x="{x0:.1f}" y="{y + 2}" width="{w:.1f}" height="{row_h - 4}" rx="2" '
                     f'fill="{colour}"{extra} stroke-width="1"><title>{_esc(tip)}</title></rect>')
            if w > 18:
                lab = "!" if pos is None else (str(pos + 1) + ("*" if odd else ""))
                p.append(f'<text x="{x0 + w / 2:.1f}" y="{y + row_h / 2 + 4}" font-size="11" '
                         f'fill="#fff" text-anchor="middle" font-weight="600">{lab}</text>')

    y = mt
    acc, blocks = 0.0, []
    for s in std["standard"]:
        blocks.append((acc, acc + s["median_s"], s["position"] - 1,
                       f'{s["position"]}번 {s.get("name") or s["signature"]} · '
                       f'중앙값 {s["median_s"]}초 · IQR {s["iqr_s"]}초', False))
        acc += s["median_s"]
    band(y, "표준(중앙값)", blocks, bold=True)
    y += row_h + gap + 4

    for c, cyc in enumerate(cycles):
        t0 = cyc[0].start_s
        blocks = [(e.start_s - t0, e.end_s - t0, e.position,
                   f'{"표준 외" if e.position is None else str(e.position + 1) + "번"}'
                   f'{" (순서 이탈)" if e.out_of_order else ""} · {e.dur_s}초 · {e.signature}',
                   e.out_of_order) for e in cyc]
        band(y, f"사이클 {c + 1}", blocks)
        y += row_h + gap

    ly = y + 16
    for i, s in enumerate(std["standard"]):
        cx = ml + (i % 3) * 306
        cy = ly + (i // 3) * 22
        p.append(f'<rect x="{cx}" y="{cy}" width="11" height="11" '
                 f'fill="{POS_COLOURS[i % len(POS_COLOURS)]}"/>')
        flag = (" · " + ", ".join(s["flags"])) if s["flags"] else ""
        title = s.get("name") or s["signature"]
        p.append(f'<text x="{cx + 17}" y="{cy + 10}" font-size="10.5" fill="#444">'
                 f'{s["position"]}. {_esc(title)} · {s["median_s"]}s{_esc(flag)}</text>')
    p.append("</svg>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(p))
    return path
