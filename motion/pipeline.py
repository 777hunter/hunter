"""서블릭 태깅까지의 공통 실행 경로. CLI들이 이걸 공유한다."""
from __future__ import annotations

import numpy as np

from hand_core import analyse_hands, ensure_hand_model
from therblig import Config, build_segments, compute_signals, config_dict, label_frames, summarise

SIDES = ("Left", "Right")


def run_therblig(
    video: str,
    model: str | None = None,
    stride: int = 1,
    max_frames: int | None = None,
    min_confidence: float = 0.5,
    swap_hands: bool = False,
    keep_frames: bool = False,
    cfg: Config | None = None,
) -> dict:
    cfg = cfg or Config()
    meta, frames, raw = analyse_hands(
        video, ensure_hand_model(model), num_hands=2, stride=stride, max_frames=max_frames,
        min_confidence=min_confidence, swap_hands=swap_hands, keep_frames=keep_frames,
    )
    if not frames:
        raise SystemExit("no frames decoded")

    times = np.array([f.time_s for f in frames])
    fps = meta["effective_fps"]
    sigs, labels, per_side = {}, {}, {}
    for side in SIDES:
        sigs[side] = compute_signals(frames, side, fps, cfg)
        labels[side] = label_frames(sigs[side], fps, cfg)
        per_side[side] = build_segments(labels[side], times, cfg)

    summary = summarise(per_side, times)
    summary["meta"] = meta
    summary["config"] = config_dict(cfg)
    return {"meta": meta, "frames": frames, "raw": raw, "times": times,
            "sigs": sigs, "labels": labels, "per_side": per_side, "summary": summary}
