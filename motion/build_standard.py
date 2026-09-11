#!/usr/bin/env python3
"""M1 — 동영상에서 작업요소와 표준 순서를 뽑는다.

    python motion/build_standard.py work.mp4 --out-dir out --allowance 0.15

서블릭 태깅 -> 작업요소 분할 -> 사이클 탐지/정합 -> 표준 순서와 요소별 시간.
요소 이름과 급소는 여기서 나오지 않는다(M2, M4).
"""
from __future__ import annotations

import argparse
import csv
import json
import os

import numpy as np

from cycle_chart import render_cycles
from elements import (
    build_standard,
    detect_period,
    dominant_hand,
    feature_matrix,
    split_cycles,
    split_elements,
)
from pipeline import run_therblig
from therblig import Config, config_dict
from zones import annotate_elements, load_zones


def write_elements_csv(path, elements):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["element", "cycle", "position", "name", "start_s", "end_s", "dur_s",
                    "signature", "support", "grasp_zone", "release_zone", "reach",
                    "grasp_x", "grasp_y", "release_x", "release_y", "notes"])
        for e in elements:
            d = e.to_dict()
            g, r = d["grasp_xy"] or [None, None], d["release_xy"] or [None, None]
            w.writerow([d["index"] + 1,
                        None if d["cycle"] is None else d["cycle"] + 1,
                        None if d["position"] is None else d["position"] + 1,
                        d["name"], d["start_s"], d["end_s"], d["dur_s"], d["signature"],
                        d["support"], d["grasp_zone"], d["release_zone"], d["reach"],
                        g[0], g[1], r[0], r[1], "; ".join(d["notes"])])


def write_standard_csv(path, std, rating, allowance):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["순번", "작업요소(초안)", "동작구성", "중앙값(초)", "IQR(초)", "최소", "최대",
                    "출현", "정미시간(초)", "표준시간(초)", "보조손", "비고"])
        for s in std["standard"]:
            net = s["median_s"] * rating
            w.writerow([s["position"], s.get("name") or "", s["signature"], s["median_s"], s["iqr_s"],
                        s["min_s"], s["max_s"], s["presence"], round(net, 2),
                        round(net * (1 + allowance), 2),
                        "사용" if s["support_used"] else "", ", ".join(s["flags"])])
        net_total = std["net_time_s"] * rating
        w.writerow([])
        w.writerow(["합계", "", "", std["net_time_s"], "", "", "", "",
                    round(net_total, 2), round(net_total * (1 + allowance), 2), "", ""])
        w.writerow(["레이팅", rating, "여유율", allowance, "", "", "", "", "", "",
                    "레이팅과 여유율은 사람이 정한 값"])


def main():
    ap = argparse.ArgumentParser(description="작업요소 분할과 표준 순서 도출")
    ap.add_argument("video")
    ap.add_argument("--out-dir", default="standard_out")
    ap.add_argument("--model", default=None)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--min-confidence", type=float, default=0.5)
    ap.add_argument("--swap-hands", action="store_true")
    ap.add_argument("--dominant", choices=["auto", "Left", "Right"], default="auto")
    ap.add_argument("--period", type=int, default=0, help="사이클당 요소 수를 알면 직접 지정")
    ap.add_argument("--min-element-s", type=float, default=0.4)
    ap.add_argument("--zones", default=None, help="zone_tool.html 로 만든 zones.json")
    ap.add_argument("--zone-tol", type=float, default=0.05,
                    help="존 바깥이라도 이 거리 안이면 그 존으로 본다 (화면 비율)")
    ap.add_argument("--rating", type=float, default=1.0, help="수행도 평가 계수 (사람이 정함)")
    ap.add_argument("--allowance", type=float, default=0.15, help="여유율 (사람이 정함)")
    ap.add_argument("--title", default=None)
    cfg_default = Config()
    for name, val in config_dict(cfg_default).items():
        ap.add_argument(f"--{name.replace('_', '-')}", type=type(val), default=val)
    args = ap.parse_args()

    cfg = Config(**{k: getattr(args, k) for k in config_dict(cfg_default)})
    os.makedirs(args.out_dir, exist_ok=True)

    res = run_therblig(args.video, args.model, stride=args.stride, max_frames=args.max_frames,
                       min_confidence=args.min_confidence, swap_hands=args.swap_hands,
                       keep_frames=False, cfg=cfg)
    meta, frames, times, per_side = res["meta"], res["frames"], res["times"], res["per_side"]

    dom = dominant_hand(per_side) if args.dominant == "auto" else args.dominant
    elements = split_elements(per_side, dom, frames, times, meta, min_dur_s=args.min_element_s)
    if len(elements) < 2:
        raise SystemExit(f"작업요소를 {len(elements)}개밖에 못 찾았다. "
                         "쥐기/놓기가 검출되는지 therblig_tag.py 로 먼저 확인할 것.")

    zone_report = None
    if args.zones:
        zone_list, _ = load_zones(args.zones)
        zone_report = annotate_elements(elements, zone_list, tol=args.zone_tol)

    F = feature_matrix(elements)
    if args.period > 0:
        period, conf = args.period, None
    else:
        period, conf = detect_period(F)
    cycles = split_cycles(elements, period, F)
    std = build_standard(cycles, F, elements)
    std["dominant_hand"] = dom
    std["period_elements"] = period
    std["period_confidence"] = conf
    std["rating"] = args.rating
    std["allowance"] = args.allowance
    std["standard_time_s"] = round(std["net_time_s"] * args.rating * (1 + args.allowance), 2)
    hands = res["summary"].get("hands", {})
    std["therblig"] = {
        side: {k: v for k, v in h.items() if k != "segments"} for side, h in hands.items()
    }
    std["two_hand"] = res["summary"].get("two_hand")
    std["zones"] = zone_report
    std["meta"] = meta
    std["elements"] = [e.to_dict() for e in elements]

    stem = os.path.splitext(os.path.basename(args.video))[0]
    out = {
        "elements_csv": os.path.join(args.out_dir, f"{stem}_elements.csv"),
        "standard_csv": os.path.join(args.out_dir, f"{stem}_standard.csv"),
        "standard_json": os.path.join(args.out_dir, f"{stem}_standard.json"),
        "cycles_svg": os.path.join(args.out_dir, f"{stem}_cycles.svg"),
    }
    write_elements_csv(out["elements_csv"], elements)
    write_standard_csv(out["standard_csv"], std, args.rating, args.allowance)
    with open(out["standard_json"], "w", encoding="utf-8") as fh:
        json.dump(std, fh, indent=2, ensure_ascii=False)
    render_cycles(std, cycles, out["cycles_svg"], args.title or f"사이클 정합 · {stem}")

    warn = []
    rate = meta["hand_detection_rate"].get(dom, 0)
    if rate < 0.9:
        warn.append(f"우세손 검출률 {rate:.0%} — 0.9 미만이면 결과를 믿지 말 것")
    if conf is not None and conf < 0.6:
        warn.append(f"주기 신뢰도 {conf} — 사이클 분할이 불안정하다. --period 로 직접 지정할 것")
    if std["cycle_count"] < 5:
        warn.append(f"사이클 {std['cycle_count']}회 — 표준으로 쓰려면 5회 이상 필요")

    print(json.dumps({
        "우세손": dom,
        "작업요소": len(elements),
        "사이클당_요소": period,
        "주기_신뢰도": conf,
        "사이클": std["cycle_count"],
        "사이클타임_중앙값": std["cycle_seconds"]["median"],
        "사이클타임_IQR": std["cycle_seconds"]["iqr"],
        "정미시간": std["net_time_s"],
        "표준시간": std["standard_time_s"],
        "변동": len(std["variations"]),
        "명명률": None if not zone_report else zone_report["named_rate"],
        "부분명명": None if not zone_report else zone_report["partial"],
    }, indent=2, ensure_ascii=False))
    if zone_report:
        print("\n[작업요소 초안]")
        for s in std["standard"]:
            print(f"  {s['position']}. {s.get('name') or '(이름 없음)':<34} "
                  f"{s['median_s']:>5.2f}초  {s['signature']}")
    if zone_report and zone_report["unused_zones"]:
        warn.append("한 번도 안 쓰인 존: " + ", ".join(zone_report["unused_zones"]))
    if zone_report and zone_report["named_rate"] < 0.8:
        warn.append(f"완전 명명 {zone_report['named']}/{zone_report['total']} "
                    f"(부분 {zone_report['partial']}, 미명명 {zone_report['unnamed']}) — "
                    "존이 덜 정의됐다. zone_tool.html 에 elements.csv 를 얹어 "
                    "점이 찍혔는데 존이 없는 자리를 확인할 것")

    if std["variations"]:
        print("\n[변동 구간]")
        for v in std["variations"][:10]:
            cyc = "전체" if v["cycle"] is None else f"사이클 {v['cycle'] + 1}"
            print(f"  {cyc}: {v['detail']}")
    if warn:
        print("\n[경고]")
        for w in warn:
            print(f"  ! {w}")
    print("\n" + "\n".join(f"{k:14s}: {v}" for k, v in out.items()))


if __name__ == "__main__":
    main()
