#!/usr/bin/env python3
"""동영상 -> 포즈 키포인트 -> 관절 각도 / 반복 횟수 / 동작 구간 분석.

사용 예:
    python motion/analyze.py squat.mp4 --out-dir out --exercise squat --annotate
"""
from __future__ import annotations

import argparse
import csv
import json
import os

import cv2
import numpy as np

from metrics import EXERCISES, summarise
from pose_core import L, POSE_CONNECTIONS, analyse_video, ensure_model

ANGLE_KEYS = ["l_elbow", "r_elbow", "l_shoulder", "r_shoulder",
              "l_hip", "r_hip", "l_knee", "r_knee"]


def write_csv(path, frames, speed, dump_landmarks=False):
    header = ["frame", "time_s", "detected"] + ANGLE_KEYS + ["torso_lean", "motion_speed"]
    if dump_landmarks:
        header += [f"lm{i}_{a}" for i in range(33) for a in ("x", "y", "vis")]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for f, sp in zip(frames, speed):
            row = [f.index, round(f.time_s, 3), int(f.detected)]
            row += [None if not f.detected or f.angles.get(k) is None else round(f.angles[k], 1)
                    for k in ANGLE_KEYS]
            row += [None if f.torso_lean is None else round(f.torso_lean, 1),
                    None if not np.isfinite(sp) else round(float(sp), 3)]
            if dump_landmarks:
                if f.detected:
                    for i in range(33):
                        row += [round(float(f.px[i][0]), 1), round(float(f.px[i][1]), 1),
                                round(float(f.vis[i]), 3)]
                else:
                    row += [None] * 99
            w.writerow(row)


def rep_counts_per_frame(frames, rep_times):
    ends = sorted(r["end_s"] for r in rep_times)
    counts, i = [], 0
    for f in frames:
        while i < len(ends) and ends[i] <= f.time_s:
            i += 1
        counts.append(i)
    return counts


def draw(frame_bgr, f, label_lines, colour=(0, 220, 120)):
    img = frame_bgr
    if f.detected:
        p = f.px.astype(int)
        for a, b in POSE_CONNECTIONS:
            if f.vis[a] > 0.3 and f.vis[b] > 0.3:
                cv2.line(img, tuple(p[a]), tuple(p[b]), colour, 2, cv2.LINE_AA)
        for i, (x, y) in enumerate(p):
            if f.vis[i] > 0.3:
                cv2.circle(img, (x, y), 3, (40, 40, 240), -1, cv2.LINE_AA)
        for key, joint in (("l_knee", "l_knee"), ("r_knee", "r_knee"),
                           ("l_elbow", "l_elbow"), ("r_elbow", "r_elbow")):
            v = f.angles.get(key)
            if v is not None and f.vis[L[joint]] > 0.5:
                x, y = p[L[joint]]
                cv2.putText(img, f"{v:.0f}", (x + 6, y - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
    y = 30
    for line in label_lines:
        cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
        y += 30
    return img


def main():
    ap = argparse.ArgumentParser(description="video motion / action analysis")
    ap.add_argument("video")
    ap.add_argument("--out-dir", default="motion_out")
    ap.add_argument("--model", default=None, help="pose_landmarker .task 경로 (없으면 자동 다운로드)")
    ap.add_argument("--model-variant", default="full", choices=["lite", "full", "heavy"])
    ap.add_argument("--exercise", default="auto",
                    choices=["auto", *EXERCISES.keys()], nargs="+")
    ap.add_argument("--stride", type=int, default=1, help="N프레임마다 1장만 처리")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--min-confidence", type=float, default=0.5)
    ap.add_argument("--annotate", action="store_true", help="스켈레톤 오버레이 영상 저장")
    ap.add_argument("--dump-landmarks", action="store_true", help="CSV에 33개 키포인트 원본 포함")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    model = ensure_model(args.model, args.model_variant)

    meta, frames, raw = analyse_video(
        args.video, model, stride=args.stride, max_frames=args.max_frames,
        min_confidence=args.min_confidence,
    )
    if not frames:
        raise SystemExit("no frames decoded")

    exercises = args.exercise if isinstance(args.exercise, list) else [args.exercise]
    summary = summarise(frames, meta, tuple(exercises))
    speed = summary.pop("_speed")
    summary.pop("_signals")

    stem = os.path.splitext(os.path.basename(args.video))[0]
    csv_path = os.path.join(args.out_dir, f"{stem}_frames.csv")
    json_path = os.path.join(args.out_dir, f"{stem}_summary.json")
    write_csv(csv_path, frames, speed, args.dump_landmarks)
    with open(json_path, "w") as fh:
        json.dump({"meta": meta, **summary}, fh, indent=2, ensure_ascii=False)

    video_path = None
    if args.annotate:
        video_path = os.path.join(args.out_dir, f"{stem}_annotated.mp4")
        primary = summary["primary_exercise"]
        counts = (rep_counts_per_frame(frames, summary["exercises"][primary]["rep_times"])
                  if primary else [0] * len(frames))
        writer = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*"mp4v"),
                                 meta["effective_fps"], (meta["width"], meta["height"]))
        for f, bgr, c, sp in zip(frames, raw, counts, speed):
            lines = [f"t={f.time_s:5.2f}s  {'POSE' if f.detected else 'NO POSE'}"]
            if primary:
                lines.append(f"{primary}: {c} reps")
            if np.isfinite(sp):
                lines.append(f"motion {sp:.2f}")
            writer.write(draw(bgr, f, lines))
        writer.release()

    print(json.dumps({"meta": meta,
                      "primary_exercise": summary["primary_exercise"],
                      "reps": {k: v["reps"] for k, v in summary["exercises"].items()},
                      "activity": summary["activity"]["active_seconds"]},
                     indent=2, ensure_ascii=False))
    print(f"\ncsv    : {csv_path}\njson   : {json_path}"
          + (f"\nvideo  : {video_path}" if video_path else ""))


if __name__ == "__main__":
    main()
