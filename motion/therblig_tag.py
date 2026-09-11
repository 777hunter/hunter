#!/usr/bin/env python3
"""동영상 -> 손 랜드마크 -> 서블릭 자동 태깅 -> 양수동작분석표.

사용 예:
    python motion/therblig_tag.py work.mp4 --out-dir out --annotate
"""
from __future__ import annotations

import argparse
import csv
import json
import os

import cv2
import numpy as np

from hand_core import HAND_CONNECTIONS
from pipeline import SIDES, run_therblig
from simo import render_simo
from therblig import THERBLIGS, Config, config_dict


def bgr(hex_colour: str):
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


def write_frame_csv(path, frames, sigs, labels):
    cols = ["frame", "time_s"]
    for s in SIDES:
        cols += [f"{s.lower()}_{k}" for k in ("curl", "speed", "osc", "therblig")]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for i, f in enumerate(frames):
            row = [f.index, round(f.time_s, 3)]
            for s in SIDES:
                sig, lab = sigs[s], labels[s]
                vals = [sig[k][i] for k in ("curl", "speed", "osc")]
                row += [None if np.isnan(v) else round(float(v), 3) for v in vals]
                row.append(str(lab[i]))
            w.writerow(row)


def write_segment_csv(path, summary):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["hand", "therblig", "name_ko", "class", "start_s", "end_s", "dur_s"])
        for side in SIDES:
            if side not in summary["hands"]:
                continue
            for s in summary["hands"][side]["segments"]:
                w.writerow([side, s["therblig"], s["name_ko"], s["class"],
                            s["start_s"], s["end_s"], s["dur_s"]])


def annotate(frames, raw, labels, meta, path):
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"),
                             meta["effective_fps"], (meta["width"], meta["height"]))
    for i, (f, img) in enumerate(zip(frames, raw)):
        for side in SIDES:
            obs = f.hands.get(side)
            tag = str(labels[side][i])
            if obs is None:
                continue
            colour = bgr(THERBLIGS[tag][3])
            p = obs.px.astype(int)
            for a, b in HAND_CONNECTIONS:
                cv2.line(img, tuple(p[a]), tuple(p[b]), colour, 2, cv2.LINE_AA)
            for x, y in p:
                cv2.circle(img, (x, y), 2, (255, 255, 255), -1, cv2.LINE_AA)
            wx, wy = p[0]
            cv2.putText(img, f"{side[0]}:{tag}", (wx - 20, wy + 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(img, f"{side[0]}:{tag}", (wx - 20, wy + 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2, cv2.LINE_AA)
        hud = f"t={f.time_s:6.2f}s   L:{labels['Left'][i]:<2}  R:{labels['Right'][i]:<2}"
        cv2.putText(img, hud, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, hud, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
        writer.write(img)
    writer.release()


def main():
    ap = argparse.ArgumentParser(description="therblig auto-tagging from video")
    ap.add_argument("video")
    ap.add_argument("--out-dir", default="motion_out")
    ap.add_argument("--model", default=None, help="hand_landmarker.task 경로 (없으면 자동 다운로드)")
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--min-confidence", type=float, default=0.5)
    ap.add_argument("--swap-hands", action="store_true", help="거울 촬영이라 좌우가 뒤집힌 경우")
    ap.add_argument("--annotate", action="store_true")
    ap.add_argument("--title", default=None, help="분석표 제목")
    cfg_default = Config()
    for name, val in config_dict(cfg_default).items():
        ap.add_argument(f"--{name.replace('_', '-')}", type=type(val), default=val,
                        help=f"기본값 {val}")
    args = ap.parse_args()

    cfg = Config(**{k: getattr(args, k) for k in config_dict(cfg_default)})
    os.makedirs(args.out_dir, exist_ok=True)

    res = run_therblig(args.video, args.model, stride=args.stride, max_frames=args.max_frames,
                       min_confidence=args.min_confidence, swap_hands=args.swap_hands,
                       keep_frames=args.annotate, cfg=cfg)
    meta, frames, raw = res["meta"], res["frames"], res["raw"]
    times, sigs, labels = res["times"], res["sigs"], res["labels"]
    summary = res["summary"]

    stem = os.path.splitext(os.path.basename(args.video))[0]
    out = {
        "frames_csv": os.path.join(args.out_dir, f"{stem}_therblig_frames.csv"),
        "segments_csv": os.path.join(args.out_dir, f"{stem}_therblig_segments.csv"),
        "summary_json": os.path.join(args.out_dir, f"{stem}_therblig_summary.json"),
        "simo_svg": os.path.join(args.out_dir, f"{stem}_simo.svg"),
    }
    write_frame_csv(out["frames_csv"], frames, sigs, labels)
    write_segment_csv(out["segments_csv"], summary)
    with open(out["summary_json"], "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    render_simo(summary, out["simo_svg"], args.title or f"서블릭 양수동작분석표 · {stem}")
    if args.annotate:
        out["video"] = os.path.join(args.out_dir, f"{stem}_therblig.mp4")
        annotate(frames, raw, labels, meta, out["video"])

    brief = {"검출률": meta["hand_detection_rate"],
             "좌우라벨_교정": meta["handedness_conflicts"],
             "전체_초": summary["duration_s"]}
    for side in SIDES:
        h = summary["hands"][side]
        brief[side] = {"유효비율": h["effective_share"], "무효비율": h["waste_share"],
                       "사이클": h["cycles"]["count"], "평균주기초": h["cycles"]["mean_period_seconds"],
                       "상위동작": list(h["by_therblig"])[:4]}
    if "two_hand" in summary:
        brief["양손"] = summary["two_hand"]
    print(json.dumps(brief, indent=2, ensure_ascii=False))
    print("\n" + "\n".join(f"{k:14s}: {v}" for k, v in out.items()))


if __name__ == "__main__":
    main()
