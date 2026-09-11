#!/usr/bin/env python3
"""실제 영상을 돌리기 전 점검과 임계값 추천.

10분짜리 영상을 다 돌린 뒤에 "손이 안 잡혔다"를 알면 늦다. 몇십 프레임만
표본으로 떠서 쓸 수 있는 영상인지 먼저 판정하고, 그 영상에 맞는 쥠 임계값과
속도 임계값을 추천한다.

    python motion/preflight.py work.mp4 --out-dir out
"""
from __future__ import annotations

import argparse
import json
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw

import mediapipe as mp
from hand_core import _observe, ensure_hand_model
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
from shots import _font, find_font


def otsu_split(values: np.ndarray, bins: int = 64):
    """1차원 오츠 임계. 쥔 상태와 편 상태를 가르는 지점을 찾는다.

    반환: (임계값, 분리도 0~1). 분리도가 낮으면 두 무리로 안 갈린다는 뜻이다.
    """
    if len(values) < 8:
        return None, 0.0
    hist, edges = np.histogram(values, bins=bins)
    centres = (edges[:-1] + edges[1:]) / 2
    prob = hist / max(hist.sum(), 1)
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * centres)
    mu_t = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = (mu_t * omega - mu) ** 2 / (omega * (1 - omega))
    if not np.isfinite(sigma_b).any():
        return None, 0.0
    # 두 무리가 뚜렷하면 그 사이 어디를 잘라도 분산이 같다. argmax 는 그 구간의
    # 첫 칸을 집어 낮은 무리 바로 위에 붙는다. 평평한 구간의 가운데를 쓴다.
    peak = float(np.nanmax(sigma_b))
    plateau = np.where(sigma_b >= peak * 0.99)[0]
    k = int(plateau[len(plateau) // 2])
    total_var = float(np.var(values)) or 1e-9
    return float(centres[k]), float(np.clip(peak / total_var, 0, 1))


def sample_video(video: str, model: str, samples: int, min_conf: float, burst: int = 5):
    """영상 곳곳에서 연속 프레임 덩어리(버스트)로 표본을 뜬다.

    띄엄띄엄 뜨면 손목 속도를 잴 수 없다. 버스트 안에서는 프레임이 연속이라
    본 파이프라인이 쓰는 것과 같은 눈금의 속도가 나온다.
    """
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"영상을 열 수 없다: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    burst = max(2, burst)
    n_bursts = max(2, samples // burst)
    starts = np.linspace(0, max(total - burst, 0), n_bursts, dtype=int)
    burst_of = {}
    for bi, st in enumerate(starts):
        for f in range(int(st), min(int(st) + burst, max(total, 1))):
            burst_of.setdefault(f, bi)
    wanted = sorted(burst_of)

    obs, idx, k = [], -1, 0
    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model),
        running_mode=RunningMode.IMAGE, num_hands=2,
        min_hand_detection_confidence=min_conf)
    with HandLandmarker.create_from_options(options) as lm:
        while k < len(wanted):
            if not cap.grab():
                break
            idx += 1
            if idx != wanted[k]:
                continue
            ok, img = cap.retrieve()
            while k < len(wanted) and wanted[k] <= idx:
                k += 1
            if not ok:
                continue
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            row = {"frame": idx, "time_s": idx / fps, "burst": burst_of[idx], "hands": []}
            for lms, handed in zip(res.hand_landmarks, res.handedness):
                px = np.array([[p.x * width, p.y * height] for p in lms], dtype=np.float32)
                o = _observe(px, float(handed[0].score))
                if o:
                    row["hands"].append({"side": handed[0].category_name, "curl": o.curl,
                                         "span": o.span, "score": o.score,
                                         "wrist": o.wrist.tolist()})
            obs.append(row)
    cap.release()
    return {"fps": fps, "width": width, "height": height, "total_frames": total,
            "duration_s": total / fps if fps else 0.0, "samples": obs}


def diagnose(data: dict) -> dict:
    obs = data["samples"]
    hit = [r for r in obs if r["hands"]]
    rate = len(hit) / len(obs) if obs else 0.0
    curls = np.array([h["curl"] for r in hit for h in r["hands"]])
    spans = np.array([h["span"] for r in hit for h in r["hands"]])
    sides = [h["side"] for r in hit for h in r["hands"]]

    split, sep = otsu_split(curls) if len(curls) else (None, 0.0)
    rec = {}
    if split is not None and sep >= 0.35:
        lo, hi = float(np.percentile(curls[curls <= split], 75)), \
                 float(np.percentile(curls[curls > split], 25))
        rec["close_curl"] = round(max(lo, split - 0.25), 2)
        rec["open_curl"] = round(min(hi, split + 0.25), 2)
    elif len(curls):
        # 두 무리로 안 갈린다. 분포 양끝으로 잡고 사람이 확인하게 한다.
        rec["close_curl"] = round(float(np.percentile(curls, 30)), 2)
        rec["open_curl"] = round(float(np.percentile(curls, 70)), 2)

    # 속도는 같은 버스트 안의 연속 프레임끼리만 잰다
    speeds = []
    prev, prev_t, prev_burst = None, None, None
    for r in obs:
        cur = {h["side"]: (np.array(h["wrist"]), h["span"]) for h in r["hands"]}
        if prev is not None and r.get("burst") == prev_burst:
            dt = r["time_s"] - prev_t
            for side, (w, span) in cur.items():
                if side in prev and span > 1e-3 and dt > 0:
                    speeds.append(float(np.linalg.norm(w - prev[side][0])) / span / dt)
        prev, prev_t, prev_burst = cur, r["time_s"], r.get("burst")
    speeds = np.array(speeds)

    verdict, reasons, warns = "진행 가능", [], []
    if rate < 0.7:
        verdict = "재촬영 권장"
        reasons.append(f"손 검출률 {rate:.0%} — 0.7 미만이면 요소 분할이 무너진다")
    elif rate < 0.9:
        verdict = "조건부 진행"
        warns.append(f"손 검출률 {rate:.0%} — 검출 안 된 구간의 결과는 믿지 말 것")
    if len(spans) and float(np.median(spans)) < 40:
        verdict = "재촬영 권장" if verdict != "재촬영 권장" else verdict
        reasons.append(f"손 크기 중앙값 {np.median(spans):.0f}px — 너무 작다. 더 가까이 찍을 것")
    if data["fps"] < 24:
        warns.append(f"{data['fps']:.0f}fps — 쥐기 전이를 놓칠 수 있다. 60fps 권장")
    if sep < 0.35 and len(curls):
        warns.append(f"쥠·폄 분리도 {sep:.2f} — 두 무리로 안 갈린다. "
                     "공구를 계속 쥐고 있거나 손이 잘 안 보이는 영상일 수 있다. "
                     "추천 임계값을 그대로 믿지 말 것")
    if data["duration_s"] < 30:
        warns.append(f"길이 {data['duration_s']:.0f}초 — 5사이클 이상 담겼는지 확인할 것")
    left = sides.count("Left")
    if left == 0 or left == len(sides):
        warns.append("한쪽 손만 검출됐다. 양수동작분석은 나오지 않는다")

    return {
        "verdict": verdict, "reasons": reasons, "warnings": warns,
        "detection_rate": round(rate, 3),
        "hand_span_px": {"median": round(float(np.median(spans)), 1) if len(spans) else None,
                         "min": round(float(spans.min()), 1) if len(spans) else None},
        "curl": {"n": int(len(curls)), "separation": round(sep, 3),
                 "split": round(split, 3) if split else None,
                 "p10": round(float(np.percentile(curls, 10)), 2) if len(curls) else None,
                 "p90": round(float(np.percentile(curls, 90)), 2) if len(curls) else None},
        "speed": {"p40": round(float(np.percentile(speeds, 40)), 2) if len(speeds) else None,
                  "p75": round(float(np.percentile(speeds, 75)), 2) if len(speeds) else None},
        "recommend": {**rec,
                      **({"still_speed": round(float(np.percentile(speeds, 40)), 2),
                          "move_speed": round(float(np.percentile(speeds, 75)), 2)}
                         if len(speeds) > 8 else {})},
        "_curls": curls, "_speeds": speeds, "_obs": obs,
    }


def chart(diag: dict, data: dict, path: str, font_path: str | None) -> str:
    W, H, pad = 1180, 470, 26
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_t, f_s, f_x = _font(font_path, 20), _font(font_path, 14), _font(font_path, 12)
    d.text((pad, 16), "사전 점검", font=f_t, fill=(20, 26, 24))
    d.text((pad, 44), f'{data["width"]}x{data["height"]} · {data["fps"]:.0f}fps · '
                      f'{data["duration_s"]:.0f}초 · 검출률 {diag["detection_rate"]:.0%} · '
                      f'판정 {diag["verdict"]}', font=f_s, fill=(90, 98, 94))

    def hist(x0, y0, w, h, values, marks, title, fmt="{:.2f}"):
        d.text((x0, y0 - 22), title, font=f_s, fill=(40, 46, 44))
        d.rectangle([x0, y0, x0 + w, y0 + h], outline=(215, 219, 213))
        if not len(values):
            d.text((x0 + 10, y0 + h / 2), "데이터 없음", font=f_s, fill=(150, 150, 150))
            return
        counts, edges = np.histogram(values, bins=36)
        top = counts.max() or 1
        bw = w / len(counts)
        for i, c in enumerate(counts):
            bh = c / top * (h - 10)
            d.rectangle([x0 + i * bw + 1, y0 + h - bh, x0 + (i + 1) * bw - 1, y0 + h],
                        fill=(120, 160, 158))
        lo, hi = float(edges[0]), float(edges[-1])
        for value, colour, name in marks:
            if value is None or not (lo <= value <= hi):
                continue
            px = x0 + (value - lo) / max(hi - lo, 1e-9) * w
            d.line([(px, y0), (px, y0 + h)], fill=colour, width=2)
            d.text((min(px + 4, x0 + w - 70), y0 + 4), f"{name} {fmt.format(value)}",
                   font=f_x, fill=colour)
        d.text((x0, y0 + h + 6), fmt.format(lo), font=f_x, fill=(150, 150, 150))
        d.text((x0 + w - 40, y0 + h + 6), fmt.format(hi), font=f_x, fill=(150, 150, 150))

    rec = diag["recommend"]
    hist(pad, 110, 540, 150, diag["_curls"],
         [(rec.get("close_curl"), (200, 60, 70), "쥠"), (rec.get("open_curl"), (40, 110, 150), "폄")],
         f'쥠 정도(curl) 분포 — 분리도 {diag["curl"]["separation"]:.2f}')
    hist(pad + 590, 110, 540, 150, diag["_speeds"],
         [(rec.get("still_speed"), (200, 60, 70), "정지"), (rec.get("move_speed"), (40, 110, 150), "이동")],
         "손목 속도 분포 (손 길이/초)", "{:.1f}")

    y = 310
    d.text((pad, y), "시간대별 손 검출", font=f_s, fill=(40, 46, 44))
    obs = diag["_obs"]
    bw = (W - 2 * pad) / max(len(obs), 1)
    for i, r in enumerate(obs):
        n = len(r["hands"])
        colour = (200, 205, 200) if n == 0 else ((120, 160, 158) if n == 1 else (42, 120, 110))
        d.rectangle([pad + i * bw, y + 22, pad + (i + 1) * bw - 0.5, y + 52], fill=colour)
    d.text((pad, y + 58), "회색 미검출 · 연두 한 손 · 진초록 양손", font=f_x, fill=(140, 145, 142))

    ty = y + 84
    for line in (diag["reasons"] + diag["warnings"])[:3]:
        d.text((pad, ty), "· " + line, font=f_x, fill=(150, 90, 30))
        ty += 18
    img.save(path)
    return path


def main():
    ap = argparse.ArgumentParser(description="영상 사전 점검과 임계값 추천")
    ap.add_argument("video")
    ap.add_argument("--out-dir", default="standard_out")
    ap.add_argument("--model", default=None)
    ap.add_argument("--samples", type=int, default=150, help="표본으로 뜰 프레임 수")
    ap.add_argument("--burst", type=int, default=5,
                    help="한 지점에서 연속으로 뜰 프레임 수 (속도 측정용)")
    ap.add_argument("--min-confidence", type=float, default=0.4)
    ap.add_argument("--font", default=None)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    data = sample_video(args.video, ensure_hand_model(args.model),
                        args.samples, args.min_confidence, burst=args.burst)
    diag = diagnose(data)
    stem = os.path.splitext(os.path.basename(args.video))[0]
    png = chart(diag, data, os.path.join(args.out_dir, f"{stem}_preflight.png"),
                find_font(args.font))
    doc = {k: v for k, v in diag.items() if not k.startswith("_")}
    doc["video"] = {k: v for k, v in data.items() if k != "samples"}
    out = os.path.join(args.out_dir, f"{stem}_preflight.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)

    print(f'{data["width"]}x{data["height"]} · {data["fps"]:.0f}fps · {data["duration_s"]:.0f}초')
    print(f'손 검출률 {diag["detection_rate"]:.0%} · 손 크기 중앙값 '
          f'{diag["hand_span_px"]["median"]}px · 쥠/폄 분리도 {diag["curl"]["separation"]:.2f}')
    print(f'\n판정: {diag["verdict"]}')
    for r in diag["reasons"]:
        print(f"  ! {r}")
    for w in diag["warnings"]:
        print(f"  · {w}")
    if diag["recommend"]:
        opts = " ".join(f'--{k.replace("_","-")} {v}' for k, v in diag["recommend"].items())
        print(f"\n추천 임계값 (이대로 붙여 쓰면 된다)\n  {opts}")
    print(f"\npreflight_json : {out}\npreflight_png  : {png}")


if __name__ == "__main__":
    main()
