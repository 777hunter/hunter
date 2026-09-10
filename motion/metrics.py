"""Signals derived from pose frames: rep counting, ROM, tempo, activity segments."""
from __future__ import annotations

import numpy as np

from pose_core import L


def _fill_and_smooth(sig: np.ndarray, window: int = 5) -> np.ndarray:
    """Linear-interpolate NaN gaps, then moving average."""
    s = sig.astype(np.float64).copy()
    idx = np.arange(len(s))
    good = ~np.isnan(s)
    if good.sum() < 2:
        return s
    s = np.interp(idx, idx[good], s[good])
    if window > 1:
        k = np.ones(window) / window
        s = np.convolve(np.pad(s, (window // 2, window // 2), mode="edge"), k, mode="valid")[: len(sig)]
    return s


def _mean_angle(frames, keys) -> np.ndarray:
    out = []
    for f in frames:
        vals = [f.angles.get(k) for k in keys] if f.detected else []
        vals = [v for v in vals if v is not None]
        out.append(float(np.mean(vals)) if vals else np.nan)
    return np.array(out)


def _hands_height(frames) -> np.ndarray:
    """1.0 = wrists well above shoulders, 0.0 = wrists at hip level. Scale-free."""
    out = []
    for f in frames:
        if not f.detected:
            out.append(np.nan)
            continue
        p = f.px
        sh_y = (p[L["l_shoulder"]][1] + p[L["r_shoulder"]][1]) / 2
        hip_y = (p[L["l_hip"]][1] + p[L["r_hip"]][1]) / 2
        torso = abs(hip_y - sh_y)
        if torso < 1e-3:
            out.append(np.nan)
            continue
        wr_y = (p[L["l_wrist"]][1] + p[L["r_wrist"]][1]) / 2
        out.append(float((hip_y - wr_y) / torso) - 1.0)  # 0 at shoulder line
    return np.array(out)


# signal, low threshold, high threshold, where a rep starts ("high" = extended)
EXERCISES = {
    "squat":        dict(signal=lambda fr: _mean_angle(fr, ["l_knee", "r_knee"]),  low=105, high=160, unit="deg"),
    "pushup":       dict(signal=lambda fr: _mean_angle(fr, ["l_elbow", "r_elbow"]), low=100, high=155, unit="deg"),
    "curl":         dict(signal=lambda fr: _mean_angle(fr, ["l_elbow", "r_elbow"]), low=60,  high=150, unit="deg"),
    "situp":        dict(signal=lambda fr: _mean_angle(fr, ["l_hip", "r_hip"]),     low=80,  high=145, unit="deg"),
    "jumping_jack": dict(signal=_hands_height,                                     low=-0.2, high=0.6, unit="ratio"),
}


def count_reps(sig: np.ndarray, times: np.ndarray, low: float, high: float):
    """Hysteresis counter. A rep = high -> below low -> back above high."""
    reps = []
    state = "high" if (not np.isnan(sig[0]) and sig[0] >= high) else "unknown"
    start_t = None
    bottom = None
    for t, v in zip(times, sig):
        if np.isnan(v):
            continue
        if state in ("high", "unknown") and v <= low:
            state = "low"
            start_t = start_t if start_t is not None else t
            bottom = v
        elif state == "low":
            bottom = min(bottom, v)
            if v >= high:
                reps.append({"end_s": round(float(t), 2),
                             "start_s": round(float(start_t), 2) if start_t is not None else None,
                             "bottom": round(float(bottom), 1)})
                state = "high"
                start_t = None
        elif v >= high:
            state = "high"
            start_t = t
    return reps


def activity_profile(frames, fps: float):
    """Normalised whole-body motion speed per frame (torso lengths per second)."""
    speeds = np.full(len(frames), np.nan)
    for i in range(1, len(frames)):
        a, b = frames[i - 1], frames[i]
        if not (a.detected and b.detected):
            continue
        p = b.px
        sh = (p[L["l_shoulder"]] + p[L["r_shoulder"]]) / 2
        hp = (p[L["l_hip"]] + p[L["r_hip"]]) / 2
        torso = float(np.linalg.norm(sh - hp))
        if torso < 1e-3:
            continue
        step = float(np.mean(np.linalg.norm(p - a.px, axis=1)))
        speeds[i] = step / torso * fps
    return _fill_and_smooth(speeds, window=7)


def segment_activity(speed: np.ndarray, times: np.ndarray, threshold: float, min_len_s: float = 0.4):
    segs = []
    active = speed > threshold
    i = 0
    while i < len(active):
        if active[i]:
            j = i
            while j + 1 < len(active) and active[j + 1]:
                j += 1
            if times[j] - times[i] >= min_len_s:
                segs.append({"start_s": round(float(times[i]), 2),
                             "end_s": round(float(times[j]), 2),
                             "peak_speed": round(float(np.nanmax(speed[i:j + 1])), 2)})
            i = j + 1
        else:
            i += 1
    return segs


def summarise(frames, meta, exercises=("auto",)):
    times = np.array([f.time_s for f in frames])
    fps = meta["effective_fps"]
    names = list(EXERCISES) if "auto" in exercises else list(exercises)

    results = {}
    for name in names:
        spec = EXERCISES[name]
        raw = spec["signal"](frames)
        sig = _fill_and_smooth(raw)
        reps = count_reps(sig, times, spec["low"], spec["high"])
        rom = float(np.nanmax(sig) - np.nanmin(sig)) if np.isfinite(sig).any() else 0.0
        durations = [r["end_s"] - r["start_s"] for r in reps if r["start_s"] is not None]
        results[name] = {
            "reps": len(reps),
            "rom": round(rom, 1),
            "unit": spec["unit"],
            "mean_rep_seconds": round(float(np.mean(durations)), 2) if durations else None,
            "rep_times": reps,
            "_signal": sig,
        }

    primary = None
    ranked = [n for n in names if results[n]["reps"] > 0]
    if ranked:
        primary = max(ranked, key=lambda n: (results[n]["reps"], results[n]["rom"]))

    speed = activity_profile(frames, fps)
    thr = float(np.nanpercentile(speed, 60)) if np.isfinite(speed).any() else 0.0
    thr = max(thr, 0.15)
    segments = segment_activity(speed, times, thr)

    angle_stats = {}
    for key in ("l_knee", "r_knee", "l_elbow", "r_elbow", "l_hip", "r_hip"):
        vals = np.array([f.angles.get(key, np.nan) if f.detected else np.nan for f in frames],
                        dtype=np.float64)
        vals = np.array([np.nan if v is None else v for v in vals], dtype=np.float64)
        if np.isfinite(vals).any():
            angle_stats[key] = {"min": round(float(np.nanmin(vals)), 1),
                                "max": round(float(np.nanmax(vals)), 1),
                                "mean": round(float(np.nanmean(vals)), 1)}

    symmetry = {}
    for side_a, side_b, label in (("l_knee", "r_knee", "knee"), ("l_elbow", "r_elbow", "elbow")):
        a = np.array([f.angles.get(side_a) if f.detected and f.angles.get(side_a) else np.nan for f in frames], dtype=np.float64)
        b = np.array([f.angles.get(side_b) if f.detected and f.angles.get(side_b) else np.nan for f in frames], dtype=np.float64)
        d = np.abs(a - b)
        if np.isfinite(d).any():
            symmetry[label] = {"mean_lr_gap_deg": round(float(np.nanmean(d)), 1),
                               "max_lr_gap_deg": round(float(np.nanmax(d)), 1)}

    return {
        "primary_exercise": primary,
        "exercises": {k: {kk: vv for kk, vv in v.items() if kk != "_signal"} for k, v in results.items()},
        "angle_stats_deg": angle_stats,
        "symmetry": symmetry,
        "activity": {"speed_threshold": round(thr, 2),
                     "active_seconds": round(sum(s["end_s"] - s["start_s"] for s in segments), 2),
                     "segments": segments},
        "_signals": {k: v["_signal"] for k, v in results.items()},
        "_speed": speed,
    }
