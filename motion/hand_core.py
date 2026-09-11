"""MediaPipe Hand Landmarker wrapper: video -> per-hand grip / motion signals."""
from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass, field

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    RunningMode,
)

HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)

# 21 hand landmarks
WRIST = 0
THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP = 4, 8, 12, 16, 20
INDEX_MCP, MIDDLE_MCP, PINKY_MCP = 5, 9, 17
FINGERTIPS = (INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]


def ensure_hand_model(path: str | None = None) -> str:
    if path and os.path.exists(path):
        return path
    target = path or os.path.join(
        os.path.expanduser("~/.cache/mediapipe"), "hand_landmarker.task"
    )
    if os.path.exists(target):
        return target
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    print(f"[model] downloading hand_landmarker -> {target}")
    urllib.request.urlretrieve(HAND_MODEL_URL, target)
    return target


@dataclass
class HandObs:
    px: np.ndarray            # (21, 2) pixel coords
    span: float               # wrist -> middle MCP, used to normalise everything
    curl: float               # mean fingertip->palm distance / span. small = fist
    pinch: float              # thumb tip <-> index tip / span
    wrist: np.ndarray         # (2,) pixel coords
    score: float


@dataclass
class HandFrame:
    index: int
    time_s: float
    hands: dict[str, HandObs] = field(default_factory=dict)   # "Left" / "Right"


def _observe(px: np.ndarray, score: float) -> HandObs | None:
    span = float(np.linalg.norm(px[MIDDLE_MCP] - px[WRIST]))
    if span < 1e-3:
        return None
    palm = (px[WRIST] + px[INDEX_MCP] + px[PINKY_MCP]) / 3.0
    curl = float(np.mean([np.linalg.norm(px[t] - palm) for t in FINGERTIPS])) / span
    pinch = float(np.linalg.norm(px[THUMB_TIP] - px[INDEX_TIP])) / span
    return HandObs(px=px, span=span, curl=curl, pinch=pinch, wrist=px[WRIST].copy(), score=score)


def _assign_slots(hf: HandFrame, observed, prev_wrist, width) -> int:
    """Put each detection in the Left/Right slot.

    MediaPipe's handedness flips now and then, and it happily labels two hands
    the same side. Tracking continuity (nearest wrist to the previous frame)
    beats the per-frame label, so that wins whenever a previous frame exists.
    Returns the number of label conflicts seen, for the caller to report.
    """
    conflicts = 0
    gate = 0.35 * width
    taken: set[str] = set()
    pending = []
    for label, obs in observed:
        best, best_d = None, gate
        for side, wrist in prev_wrist.items():
            if side in taken:
                continue
            d = float(np.linalg.norm(obs.wrist - wrist))
            if d < best_d:
                best, best_d = side, d
        if best is not None:
            if best != label:
                conflicts += 1
            hf.hands[best] = obs
            taken.add(best)
        else:
            pending.append((label, obs))
    for label, obs in sorted(pending, key=lambda t: -t[1].score):
        if label in taken:
            conflicts += 1
            label = "Left" if label == "Right" else "Right"
            if label in taken:
                continue
        hf.hands[label] = obs
        taken.add(label)
    return conflicts


def analyse_hands(
    video_path: str,
    model_path: str,
    num_hands: int = 2,
    stride: int = 1,
    max_frames: int | None = None,
    min_confidence: float = 0.5,
    swap_hands: bool = False,
    keep_frames: bool = False,
    progress: bool = True,
):
    """Run the hand landmarker over a video. Returns (meta, frames, raw_frames)."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.VIDEO,
        num_hands=num_hands,
        min_hand_detection_confidence=min_confidence,
        min_hand_presence_confidence=min_confidence,
        min_tracking_confidence=min_confidence,
    )

    frames: list[HandFrame] = []
    raw: list[np.ndarray] = []
    prev_wrist: dict[str, np.ndarray] = {}
    conflicts = 0
    idx, kept = -1, 0
    with HandLandmarker.create_from_options(options) as landmarker:
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            idx += 1
            if idx % stride:
                continue
            if max_frames and kept >= max_frames:
                break
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(image, int(idx / fps * 1000))
            hf = HandFrame(index=idx, time_s=idx / fps)
            observed = []
            for lms, handed in zip(result.hand_landmarks, result.handedness):
                label = handed[0].category_name          # "Left" / "Right"
                if swap_hands:
                    label = "Left" if label == "Right" else "Right"
                px = np.array([[p.x * width, p.y * height] for p in lms], dtype=np.float32)
                obs = _observe(px, float(handed[0].score))
                if obs:
                    observed.append((label, obs))
            conflicts += _assign_slots(hf, observed, prev_wrist, width)
            for side, obs in hf.hands.items():
                prev_wrist[side] = obs.wrist
            for side in list(prev_wrist):
                if side not in hf.hands:
                    prev_wrist.pop(side)
            frames.append(hf)
            if keep_frames:
                raw.append(bgr)
            kept += 1
            if progress and kept % 60 == 0:
                print(f"[hands] {kept} frames processed")
    cap.release()

    seen = {side: sum(1 for f in frames if side in f.hands) for side in ("Left", "Right")}
    meta = {
        "video": os.path.basename(video_path),
        "fps": fps,
        "effective_fps": fps / stride,
        "width": width,
        "height": height,
        "total_frames": total,
        "processed_frames": len(frames),
        "hand_detection_rate": {
            k: round(v / len(frames), 3) if frames else 0.0 for k, v in seen.items()
        },
        "handedness_conflicts": conflicts,
    }
    return meta, frames, raw
