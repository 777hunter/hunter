"""MediaPipe Pose Landmarker wrapper: video -> per-frame keypoints + joint angles."""
from __future__ import annotations

import math
import os
import urllib.request
from dataclasses import dataclass, field

import cv2
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)
import mediapipe as mp

MODEL_URLS = {
    "lite": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "full": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "heavy": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
}

L = {
    "nose": 0,
    "l_shoulder": 11, "r_shoulder": 12,
    "l_elbow": 13, "r_elbow": 14,
    "l_wrist": 15, "r_wrist": 16,
    "l_hip": 23, "r_hip": 24,
    "l_knee": 25, "r_knee": 26,
    "l_ankle": 27, "r_ankle": 28,
    "l_heel": 29, "r_heel": 30,
    "l_foot": 31, "r_foot": 32,
}

POSE_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10),
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (27, 31), (29, 31),
    (24, 26), (26, 28), (28, 30), (28, 32), (30, 32),
]

ANGLE_SPECS = {
    "l_elbow": ("l_shoulder", "l_elbow", "l_wrist"),
    "r_elbow": ("r_shoulder", "r_elbow", "r_wrist"),
    "l_shoulder": ("l_elbow", "l_shoulder", "l_hip"),
    "r_shoulder": ("r_elbow", "r_shoulder", "r_hip"),
    "l_hip": ("l_shoulder", "l_hip", "l_knee"),
    "r_hip": ("r_shoulder", "r_hip", "r_knee"),
    "l_knee": ("l_hip", "l_knee", "l_ankle"),
    "r_knee": ("r_hip", "r_knee", "r_ankle"),
}


def ensure_model(path: str | None, variant: str = "full") -> str:
    """Return a local .task model path, downloading it once if needed."""
    if path and os.path.exists(path):
        return path
    target = path or os.path.join(
        os.path.expanduser("~/.cache/mediapipe"), f"pose_landmarker_{variant}.task"
    )
    if os.path.exists(target):
        return target
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    url = MODEL_URLS[variant]
    print(f"[model] downloading {variant} -> {target}")
    urllib.request.urlretrieve(url, target)
    return target


def angle_3p(a, b, c) -> float | None:
    """Interior angle at b, in degrees. Points are 2D or 3D arrays."""
    ba, bc = np.asarray(a) - np.asarray(b), np.asarray(c) - np.asarray(b)
    na, nc = np.linalg.norm(ba), np.linalg.norm(bc)
    if na < 1e-6 or nc < 1e-6:
        return None
    cos = float(np.clip(np.dot(ba, bc) / (na * nc), -1.0, 1.0))
    return math.degrees(math.acos(cos))


@dataclass
class Frame:
    index: int
    time_s: float
    detected: bool
    px: np.ndarray | None = None        # (33, 2) pixel coords
    vis: np.ndarray | None = None       # (33,) visibility
    world: np.ndarray | None = None     # (33, 3) metres, hip-centred
    angles: dict = field(default_factory=dict)
    torso_lean: float | None = None     # degrees from vertical


def _angles_from(world: np.ndarray, px: np.ndarray) -> dict:
    src = world if world is not None else px
    out = {}
    for name, (a, b, c) in ANGLE_SPECS.items():
        out[name] = angle_3p(src[L[a]], src[L[b]], src[L[c]])
    return out


def _torso_lean(px: np.ndarray) -> float | None:
    sh = (px[L["l_shoulder"]] + px[L["r_shoulder"]]) / 2
    hp = (px[L["l_hip"]] + px[L["r_hip"]]) / 2
    v = sh - hp
    if np.linalg.norm(v) < 1e-6:
        return None
    # 0 deg = upright torso, positive = leaning forward/back in image plane
    return abs(math.degrees(math.atan2(v[0], -v[1])))


def analyse_video(
    video_path: str,
    model_path: str,
    stride: int = 1,
    max_frames: int | None = None,
    min_confidence: float = 0.5,
    keep_frames: bool = True,
    progress: bool = True,
):
    """Yield (meta, frames). Runs the landmarker in VIDEO mode."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    options = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=min_confidence,
        min_pose_presence_confidence=min_confidence,
        min_tracking_confidence=min_confidence,
    )

    frames: list[Frame] = []
    raw_frames: list[np.ndarray] = []
    idx = -1
    kept = 0
    with PoseLandmarker.create_from_options(options) as landmarker:
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
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int(idx / fps * 1000)
            result = landmarker.detect_for_video(mp_image, ts_ms)
            f = Frame(index=idx, time_s=idx / fps, detected=bool(result.pose_landmarks))
            if f.detected:
                lm = result.pose_landmarks[0]
                f.px = np.array([[p.x * width, p.y * height] for p in lm], dtype=np.float32)
                f.vis = np.array([p.visibility for p in lm], dtype=np.float32)
                if result.pose_world_landmarks:
                    wl = result.pose_world_landmarks[0]
                    f.world = np.array([[p.x, p.y, p.z] for p in wl], dtype=np.float32)
                f.angles = _angles_from(f.world, f.px)
                f.torso_lean = _torso_lean(f.px)
            frames.append(f)
            if keep_frames:
                raw_frames.append(bgr)
            kept += 1
            if progress and kept % 60 == 0:
                print(f"[pose] {kept} frames processed")
    cap.release()

    meta = {
        "video": os.path.basename(video_path),
        "fps": fps,
        "effective_fps": fps / stride,
        "width": width,
        "height": height,
        "total_frames": total,
        "processed_frames": len(frames),
        "detected_frames": sum(1 for f in frames if f.detected),
    }
    meta["detection_rate"] = (
        meta["detected_frames"] / meta["processed_frames"] if frames else 0.0
    )
    return meta, frames, raw_frames
