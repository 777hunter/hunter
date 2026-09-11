"""TWI 작업지도서(Job Instruction) 3열 문서의 내용을 만든다.

주요단계는 M1·M2가 낸 작업요소, 사진은 M3이 뽑은 1순위 컷.
급소는 관측 데이터에서 근거가 있는 것만 초안으로 낸다.
급소의 이유는 영상에 정보가 없으므로 빈칸으로 두고 작성자가 채운다.
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw

from cycle_chart import POS_COLOURS
from shots import _font, find_font

SIDE_KO = {"Left": "좌수", "Right": "우수"}
VARIATION_KO = {"reorder": "순서 이탈", "missing": "누락",
                "extra": "표준 외 요소", "spread": "시간 산포"}


def key_points_for(row: dict, std: dict) -> list[dict]:
    """관측에서 근거가 나온 급소만. 근거 없는 급소는 만들지 않는다."""
    pts = []
    flags = row.get("flags", [])
    sup = SIDE_KO.get("Left" if std.get("dominant_hand") == "Right" else "Right", "반대손")

    if "순서 이탈" in flags:
        cycles = sorted({v["cycle"] + 1 for v in std.get("variations", [])
                         if v["type"] == "reorder" and v.get("position") == row["position"] - 1
                         and v.get("cycle") is not None})
        where = f"(사이클 {', '.join(map(str, cycles))}번)" if cycles else ""
        pts.append({"text": f"이 순서를 지킬 것. 관측 중 순서가 바뀐 사이클이 있었다 {where}".strip(),
                    "source": "자동"})
    if "누락" in flags:
        pts.append({"text": f"빠뜨리기 쉬움. 관측 {row['presence']} 회만 수행됨", "source": "자동"})
    if "산포" in flags and row["median_s"]:
        pts.append({"text": f"작업시간 편차 큼 (중앙값 {row['median_s']}초, "
                            f"범위 {row['min_s']}~{row['max_s']}초). 방법이 안정돼 있지 않다",
                    "source": "자동"})
    if "동작구성 불일치" in flags:
        pts.append({"text": "사이클마다 손동작 구성이 달랐다. 방법을 통일할 것", "source": "자동"})
    if "장거리 이동" in flags:
        pts.append({"text": "손 이동 거리가 길다. 부품 배치를 재검토할 것", "source": "자동"})
    if row.get("support_used"):
        pts.append({"text": f"{sup}으로 부품을 지지", "source": "자동"})
    if "U" in (row.get("signature") or ""):
        pts.append({"text": "공구 사용 구간. 체결 상태를 확인할 것", "source": "자동"})
    if not pts:
        pts.append({"text": "", "source": "빈칸"})
    return pts


def cycle_chart_png(std: dict, path: str, font_path: str | None,
                    width: int = 1600, row_h: int = 44) -> str | None:
    """부록용 사이클 정합 차트. SVG 변환기를 요구하지 않도록 PIL 로 직접 그린다."""
    cycles: dict[int, list[dict]] = {}
    for el in std.get("elements", []):
        if el.get("cycle") is not None:
            cycles.setdefault(el["cycle"], []).append(el)
    if not cycles:
        return None
    order = sorted(cycles)
    span = max(max(e["end_s"] for e in cyc) - min(e["start_s"] for e in cyc)
               for cyc in cycles.values()) or 1.0

    left, top, gap, pad = 150, 18, 10, 24
    plot_w = width - left - pad
    height = top + (len(order) + 1) * (row_h + gap) + 40
    img = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_row, f_blk = _font(font_path, 18), _font(font_path, 16)

    def x(t):
        return left + t / span * plot_w

    for s in range(0, int(span) + 1, max(1, int(span // 10) or 1)):
        d.line([(x(s), top - 8), (x(s), height - 34)], fill=(232, 232, 232))
        d.text((x(s) - 8, height - 30), f"{s}s", font=f_blk, fill=(140, 140, 140))

    y = top
    d.text((pad, y + row_h / 2 - 10), "표준(중앙값)", font=f_row, fill=(30, 36, 34))
    acc = 0.0
    for row in std["standard"]:
        colour = POS_COLOURS[(row["position"] - 1) % len(POS_COLOURS)]
        rgb = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
        d.rectangle([x(acc), y, x(acc + row["median_s"]), y + row_h], fill=rgb, outline=(255, 255, 255))
        if x(acc + row["median_s"]) - x(acc) > 22:
            d.text((x(acc) + 8, y + row_h / 2 - 9), str(row["position"]), font=f_blk, fill=(255, 255, 255))
        acc += row["median_s"]
    y += row_h + gap + 6

    for c in order:
        cyc = sorted(cycles[c], key=lambda e: e["start_s"])
        t0 = cyc[0]["start_s"]
        d.text((pad, y + row_h / 2 - 10), f"사이클 {c + 1}", font=f_row, fill=(60, 66, 64))
        for el in cyc:
            pos = el.get("position")
            colour = POS_COLOURS[pos % len(POS_COLOURS)] if pos is not None else "#B03A2E"
            rgb = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
            x0, x1 = x(el["start_s"] - t0), x(el["end_s"] - t0)
            d.rectangle([x0, y, x1, y + row_h], fill=rgb,
                        outline=(123, 36, 28) if el.get("out_of_order") or pos is None else (255, 255, 255))
            if x1 - x0 > 22:
                lab = "!" if pos is None else f"{pos + 1}{'*' if el.get('out_of_order') else ''}"
                d.text((x0 + 8, y + row_h / 2 - 9), lab, font=f_blk, fill=(255, 255, 255))
        y += row_h + gap
    img.save(path)
    return path


def build_spec(std: dict, shots: dict | None, header: dict, out_dir: str) -> dict:
    font_path = find_font(header.get("font"))
    shot_by_pos = {}
    for entry in (shots or {}).get("positions", []):
        if entry["shots"]:
            shot_by_pos[entry["position"]] = entry["shots"][0]
    shot_dir = os.path.join(out_dir, "shots")

    steps, blanks = [], []
    for row in std["standard"]:
        pos = row["position"]
        photo = None
        s = shot_by_pos.get(pos)
        if s:
            path = os.path.join(shot_dir, s["annotated"] or s["file"])
            if os.path.exists(path):
                with Image.open(path) as im:
                    w, h = im.size
                photo = {"path": os.path.abspath(path), "aspect": round(h / w, 4),
                         "caption": f'{s["kind_ko"]} · {s["time_s"]}초'}
        if photo is None:
            blanks.append(f"{pos}번 단계 사진 없음 — 직접 촬영해 넣을 것")

        kps = key_points_for(row, std)
        if all(k["source"] == "빈칸" for k in kps):
            blanks.append(f"{pos}번 단계 급소 — 관측에서 나온 신호가 없다. 작성자가 판단할 것")
        steps.append({
            "no": pos,
            "name": row.get("name") or row.get("signature") or f"{pos}번 요소",
            "auto_name": bool(row.get("name")),
            "time_s": row["median_s"],
            "spread": f'{row["min_s"]}~{row["max_s"]}초' if row.get("min_s") is not None else "",
            "presence": row["presence"],
            "signature": row["signature"],
            "photo": photo,
            "key_points": kps,
            "reasons": "",
        })
        blanks.append(f"{pos}번 단계 '급소의 이유' — 영상에 없는 정보")

    meta = std.get("meta", {})
    dom = std.get("dominant_hand")
    obs = [
        ("관측 사이클", f'{std["cycle_count"]}회'),
        ("작업요소", f'{std["elements_per_cycle"]}개'),
        ("사이클타임 중앙값", f'{std["cycle_seconds"]["median"]}초 (IQR {std["cycle_seconds"]["iqr"]}초)'),
        ("정미시간", f'{std["net_time_s"]}초'),
        ("레이팅 / 여유율", f'{std.get("rating", 1.0)} / {std.get("allowance", 0.0):.0%}'),
        ("표준시간", f'{std.get("standard_time_s", "-")}초'),
        ("기준 손", SIDE_KO.get(dom, dom or "-")),
        ("손 검출률", ", ".join(f'{SIDE_KO.get(k, k)} {v:.0%}'
                             for k, v in (meta.get("hand_detection_rate") or {}).items())),
        ("원본 영상", meta.get("video", "-")),
    ]
    if std["cycle_count"] < 5:
        blanks.append(f'관측 사이클이 {std["cycle_count"]}회뿐 — 표준으로 쓰려면 5회 이상 재촬영')
    if std.get("rating", 1.0) == 1.0:
        blanks.append("레이팅 1.0 — 수행도 평가를 하지 않은 값이다. 평가 후 다시 산출할 것")

    variations = []
    for v in std.get("variations", []):
        where = "전체" if v.get("cycle") is None else f'사이클 {v["cycle"] + 1}'
        variations.append({"where": where, "type": VARIATION_KO.get(v["type"], v["type"]),
                           "detail": v["detail"]})

    chart = cycle_chart_png(std, os.path.join(out_dir, "ji_cycles.png"), font_path)
    chart_meta = None
    if chart:
        with Image.open(chart) as im:
            w, h = im.size
        chart_meta = {"path": os.path.abspath(chart), "aspect": round(h / w, 4)}

    cyc_rows = []
    for i, secs in enumerate(std["cycle_seconds"]["values"], 1):
        delta = secs - std["cycle_seconds"]["median"]
        cyc_rows.append({"no": i, "seconds": secs, "delta": f"{delta:+.2f}"})

    return {
        "header": header,
        "observation": obs,
        "steps": steps,
        "variations": variations,
        "cycle_rows": cyc_rows,
        "chart": chart_meta,
        "blanks": blanks,
        "font_name": header.get("font_name", "맑은 고딕"),
    }
