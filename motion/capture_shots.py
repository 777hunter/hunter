#!/usr/bin/env python3
"""M3 — 작업요소별 대표 사진 자동 캡처.

build_standard.py 가 만든 *_standard.json 을 읽어 요소마다 후보 3장을 뽑고
존과 손을 표시한 주석본, 그리고 검수용 대표 사진 시트를 만든다.

    python motion/capture_shots.py work.mp4 --standard out/work_standard.json \
        --zones zones.json --out-dir out
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

import cv2
from hand_core import ensure_hand_model
from shots import (
    MOMENT_KO,
    Shot,
    annotate,
    candidate_requests,
    contact_sheet,
    find_font,
    pick_shots,
    read_frames,
    score_requests,
)
from zones import load_zones


def representative_elements(std: dict) -> list[dict]:
    """위치마다 중앙값에 가장 가까운 사이클의 요소를 대표로 고른다.

    제일 빠른 사이클을 쓰면 표준서 사진이 실제와 달라진다. 전형적인 한 번을 쓴다.
    """
    by_pos: dict[int, list[dict]] = {}
    for el in std["elements"]:
        if el["position"] is None:
            continue
        by_pos.setdefault(el["position"], []).append(el)
    reps = []
    for s in std["standard"]:
        pos = s["position"] - 1
        cands = by_pos.get(pos, [])
        if not cands:
            continue
        rep = min(cands, key=lambda e: abs(e["dur_s"] - s["median_s"]))
        reps.append({**rep, "name": s.get("name") or rep.get("name"),
                     "median_s": s["median_s"]})
    return reps


def main():
    ap = argparse.ArgumentParser(description="작업요소별 대표 사진 캡처")
    ap.add_argument("video")
    ap.add_argument("--standard", required=True, help="build_standard.py 가 만든 *_standard.json")
    ap.add_argument("--zones", default=None)
    ap.add_argument("--out-dir", default="standard_out")
    ap.add_argument("--model", default=None)
    ap.add_argument("--per-element", type=int, default=3, help="요소당 후보 장수")
    ap.add_argument("--window", type=float, default=0.4, help="결정적 순간 앞뒤로 살펴볼 구간(초)")
    ap.add_argument("--samples", type=int, default=5, help="한 순간에서 뽑아볼 프레임 수")
    ap.add_argument("--font", default=None, help="한글 TTF 경로")
    args = ap.parse_args()

    with open(args.standard, encoding="utf-8") as fh:
        std = json.load(fh)
    fps = std["meta"]["effective_fps"]
    zones = load_zones(args.zones)[0] if args.zones else None
    font_path = find_font(args.font)
    shot_dir = os.path.join(args.out_dir, "shots")
    os.makedirs(shot_dir, exist_ok=True)

    reps = representative_elements(std)
    if not reps:
        raise SystemExit("표준 요소가 없다. build_standard.py 를 먼저 돌릴 것.")

    reqs = candidate_requests(reps, fps, args.window, args.samples)
    frames = read_frames(args.video, {r["frame"] for r in reqs})
    print(f"[shots] 후보 {len(reqs)}개 중 {len(frames)}프레임 로드")

    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=ensure_hand_model(args.model)),
        running_mode=RunningMode.IMAGE, num_hands=2, min_hand_detection_confidence=0.4)
    with HandLandmarker.create_from_options(options) as lm:
        scored = score_requests(reqs, frames, lm, side_hint=std.get("dominant_hand"))
    print(f"[shots] 손이 잡힌 후보 {len(scored)}개")

    picked = pick_shots(scored, per_element=args.per_element)
    by_el = {e["index"]: e for e in reps}
    stem = os.path.splitext(os.path.basename(args.video))[0]

    out_entries, per_pos = [], {}
    for pos in sorted({s.position for s in picked}):
        ranked = sorted([s for s in picked if s.position == pos], key=lambda s: -s.score)
        for rank, shot in enumerate(ranked, 1):
            el = by_el[shot.element]
            base = f"{stem}_e{pos + 1:02d}_{rank}_{shot.kind}"
            shot.path = os.path.join(shot_dir, base + ".jpg")
            shot.annot_path = os.path.join(shot_dir, base + "_annot.jpg")
            img = frames[shot.frame]
            cv2.imwrite(shot.path, img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            cv2.imwrite(shot.annot_path, annotate(img, shot, el, zones, font_path),
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
        per_pos[pos] = [s.to_dict() for s in ranked]
        if ranked:
            out_entries.append({"annot": ranked[0].annot_path})

    sheet = contact_sheet(out_entries, os.path.join(args.out_dir, f"{stem}_shots.png"), font_path)
    doc = {
        "video": os.path.basename(args.video),
        "font": font_path,
        "per_element": args.per_element,
        "positions": [{"position": pos + 1,
                       "name": next((s["name"] for s in std["standard"]
                                     if s["position"] == pos + 1), None),
                       "shots": per_pos[pos]} for pos in sorted(per_pos)],
    }
    shots_json = os.path.join(args.out_dir, f"{stem}_shots.json")
    with open(shots_json, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)

    print()
    for entry in doc["positions"]:
        top = entry["shots"][0]
        alts = ", ".join(f'{s["kind_ko"]}({s["score"]:.2f})' for s in entry["shots"][1:])
        print(f'  {entry["position"]}. {entry["name"] or "(이름 없음)":<30} '
              f'대표: {top["kind_ko"]} {top["time_s"]}초 (점수 {top["score"]:.2f})'
              + (f' | 대안: {alts}' if alts else ""))
    missing = [s["position"] for s in std["standard"]
               if s["position"] - 1 not in per_pos]
    if missing:
        print(f"\n[경고] 사진을 못 뽑은 요소: {missing} — 그 구간에서 손이 검출되지 않았다")
    if not font_path:
        print("\n[경고] 한글 폰트를 못 찾았다. --font 로 TTF 경로를 줄 것 "
              "(없으면 캡션이 네모로 나온다)")
    print(f"\nshots_json    : {shots_json}\ncontact_sheet : {sheet}\nshot_dir      : {shot_dir}")


if __name__ == "__main__":
    main()
