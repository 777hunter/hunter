"""양수동작분석표(SIMO chart)를 SVG로 그린다."""
from __future__ import annotations

from therblig import THERBLIGS, CLASS_NAMES

SIDE_KO = {"Left": "좌수", "Right": "우수"}


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _nice_step(duration: float) -> float:
    for step in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
        if duration / step <= 12:
            return step
    return 900.0


def render_simo(summary: dict, path: str, title: str = "서블릭 양수동작분석표") -> str:
    hands = summary["hands"]
    sides = [s for s in ("Left", "Right") if s in hands]
    dur = max(summary["duration_s"], 0.001)

    ml, mr, mt = 96, 24, 92
    plot_w, row_h, gap = 900, 44, 18
    width = ml + plot_w + mr
    rows_h = len(sides) * row_h + (len(sides) - 1) * gap
    used = sorted({s["therblig"] for side in sides for s in hands[side]["segments"]},
                  key=lambda k: list(THERBLIGS).index(k))
    legend_rows = (len(used) + 3) // 4
    bars_top = mt + rows_h + 56
    height = bars_top + len(sides) * 30 + 24 + legend_rows * 24 + 28

    def x(t: float) -> float:
        return ml + (t / dur) * plot_w

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
         f'viewBox="0 0 {width} {height}" font-family="Pretendard, \'Malgun Gothic\', '
         f'\'Apple SD Gothic Neo\', system-ui, sans-serif">',
         f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
         f'<text x="{ml}" y="34" font-size="18" font-weight="700" fill="#1a1a1a">{_esc(title)}</text>',
         f'<text x="{ml}" y="56" font-size="12" fill="#666">전체 {dur:.1f}초 · '
         f'자동 태깅(손 운동학 기반), 검토 필요</text>']

    # 시간축
    step = _nice_step(dur)
    t = 0.0
    while t <= dur + 1e-6:
        px = x(t)
        p.append(f'<line x1="{px:.1f}" y1="{mt - 10}" x2="{px:.1f}" y2="{mt + rows_h}" '
                 f'stroke="#e6e6e6" stroke-width="1"/>')
        p.append(f'<text x="{px:.1f}" y="{mt - 16}" font-size="11" fill="#888" '
                 f'text-anchor="middle">{t:g}s</text>')
        t += step

    # 동작 블록
    for r, side in enumerate(sides):
        y = mt + r * (row_h + gap)
        p.append(f'<text x="{ml - 12}" y="{y + row_h / 2 + 5}" font-size="13" fill="#333" '
                 f'text-anchor="end" font-weight="600">{SIDE_KO.get(side, side)}</text>')
        p.append(f'<rect x="{ml}" y="{y}" width="{plot_w}" height="{row_h}" fill="#fafafa" '
                 f'stroke="#e0e0e0"/>')
        for s in hands[side]["segments"]:
            x0, x1 = x(s["start_s"]), x(s["end_s"])
            w = max(x1 - x0, 1.0)
            colour = THERBLIGS[s["therblig"]][3]
            p.append(f'<rect x="{x0:.1f}" y="{y}" width="{w:.1f}" height="{row_h}" '
                     f'fill="{colour}" stroke="#ffffff" stroke-width="0.5">'
                     f'<title>{_esc(s["name_ko"])} ({s["therblig"]}) '
                     f'{s["start_s"]:.2f}-{s["end_s"]:.2f}s, {s["dur_s"]:.2f}s</title></rect>')
            if w > 22:
                p.append(f'<text x="{x0 + w / 2:.1f}" y="{y + row_h / 2 + 4}" font-size="11" '
                         f'fill="#ffffff" text-anchor="middle" font-weight="600">'
                         f'{s["therblig"]}</text>')

    # 분류별 시간 구성비
    p.append(f'<text x="{ml}" y="{bars_top - 14}" font-size="12" fill="#333" '
             f'font-weight="600">분류별 시간 구성비</text>')
    class_colour = {"제1류(유효)": "#2a9d8f", "제2류(준비·보조)": "#457b9d",
                    "제3류(무효)": "#e9c46a", "미검출": "#d9d9d9"}
    for r, side in enumerate(sides):
        y = bars_top + r * 30
        p.append(f'<text x="{ml - 12}" y="{y + 14}" font-size="12" fill="#333" '
                 f'text-anchor="end">{SIDE_KO.get(side, side)}</text>')
        cx = ml
        for cname, secs in hands[side]["by_class"].items():
            w = (secs / dur) * plot_w
            if w <= 0:
                continue
            p.append(f'<rect x="{cx:.1f}" y="{y}" width="{w:.1f}" height="20" '
                     f'fill="{class_colour.get(cname, "#ccc")}">'
                     f'<title>{_esc(cname)} {secs:.1f}s ({secs / dur * 100:.0f}%)</title></rect>')
            if w > 42:
                p.append(f'<text x="{cx + w / 2:.1f}" y="{y + 14}" font-size="10" fill="#fff" '
                         f'text-anchor="middle">{secs / dur * 100:.0f}%</text>')
            cx += w

    # 범례
    ly = bars_top + len(sides) * 30 + 26
    for i, key in enumerate(used):
        ko, en, cls, colour = THERBLIGS[key]
        cx = ml + (i % 4) * 230
        cy = ly + (i // 4) * 24
        p.append(f'<rect x="{cx}" y="{cy}" width="12" height="12" fill="{colour}"/>')
        p.append(f'<text x="{cx + 18}" y="{cy + 11}" font-size="11" fill="#444">'
                 f'{key} · {_esc(ko)} · {_esc(CLASS_NAMES[cls])}</text>')
    p.append("</svg>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(p))
    return path
