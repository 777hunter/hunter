#!/usr/bin/env python3
"""존 정의용 배경 프레임을 뽑는다.

zone_tool.html 은 브라우저가 재생할 수 있는 영상(H.264 등)만 직접 읽는다.
코덱이 안 맞으면 이걸로 PNG 를 먼저 뽑아서 이미지로 불러오면 된다.

    python motion/grab_frame.py work.mp4 --at 5.0 --out frame.png
"""
from __future__ import annotations

import argparse

import cv2
import numpy as np


def sharpest_frame(cap, start_f: int, end_f: int, samples: int = 12):
    """구간에서 가장 덜 흔들린 프레임. 라플라시안 분산이 클수록 선명하다."""
    best, best_score = None, -1.0
    for f in np.linspace(start_f, end_f, samples, dtype=int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
        ok, img = cap.read()
        if not ok:
            continue
        score = float(cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
        if score > best_score:
            best, best_score = img, score
    return best, best_score


def main():
    ap = argparse.ArgumentParser(description="영상에서 존 정의용 프레임 추출")
    ap.add_argument("video")
    ap.add_argument("--at", type=float, default=None, help="초 단위 시점 (기본: 영상 중간)")
    ap.add_argument("--window", type=float, default=1.0, help="이 구간에서 가장 선명한 프레임을 고른다")
    ap.add_argument("--out", default="frame.png")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"영상을 열 수 없다: {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    at = args.at if args.at is not None else (total / fps) / 2
    centre = int(at * fps)
    half = int(args.window * fps / 2)
    img, score = sharpest_frame(cap, max(0, centre - half), min(total - 1, centre + half))
    cap.release()
    if img is None:
        raise SystemExit("프레임을 읽지 못했다")
    cv2.imwrite(args.out, img)
    print(f"{args.out}  {img.shape[1]}x{img.shape[0]}  {at:.2f}초 부근  선명도 {score:.0f}")


if __name__ == "__main__":
    main()
