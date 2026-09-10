"""서블릭(Therblig) 자동 태깅.

손 랜드마크에서 뽑은 두 신호(쥠 정도, 손목 속도)로 8종 서블릭을 붙인다.
길브레스의 18종 중 손 운동학만으로 판정 가능한 것만 다룬다. 나머지
(찾기/선택/조립/분해/검사/미리놓기/계획)는 대상물과 시선 정보가 필요해서
여기서는 내지 않는다. README의 '한계' 참고.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

# 기호, 한글명, 길브레스 분류(1=유효, 2=준비/보조, 3=무효), 차트 색
THERBLIGS = {
    "G":  ("쥐기", "Grasp", 1, "#d1495b"),
    "TL": ("운반", "Transport Loaded", 1, "#2a9d8f"),
    "TE": ("빈손이동", "Transport Empty", 1, "#8ab17d"),
    "RL": ("내려놓기", "Release Load", 1, "#f4a261"),
    "U":  ("사용", "Use", 1, "#6a4c93"),
    "P":  ("바로놓기", "Position", 2, "#457b9d"),
    "H":  ("잡고있기", "Hold", 3, "#b08968"),
    "D":  ("지연", "Delay", 3, "#e9c46a"),
    "-":  ("손 미검출", "Not detected", 0, "#d9d9d9"),
}
CLASS_NAMES = {1: "제1류(유효)", 2: "제2류(준비·보조)", 3: "제3류(무효)", 0: "미검출"}


@dataclass
class Config:
    close_curl: float = 0.65     # 이 아래면 쥔 상태 (주먹 기준 실측 0.28)
    open_curl: float = 1.05      # 이 위면 편 상태 (편 손 실측 1.5)
    grasp_rate: float = 1.2      # |d(curl)/dt|, 쥐기/놓기 전이 판정
    max_transition_s: float = 0.6
    still_speed: float = 0.6     # 손목 속도, 단위: 손 길이/초
    move_speed: float = 1.8
    use_ratio: float = 2.2       # 경로길이/순변위. 높으면 왕복 = 사용
    use_window_s: float = 0.5
    min_segment_s: float = 0.15
    smooth_window: int = 5


def _smooth(sig: np.ndarray, window: int) -> np.ndarray:
    s = sig.astype(np.float64).copy()
    good = ~np.isnan(s)
    if good.sum() < 2:
        return s
    idx = np.arange(len(s))
    s = np.interp(idx, idx[good], s[good])
    if window > 1:
        k = np.ones(window) / window
        s = np.convolve(np.pad(s, (window // 2, window // 2), mode="edge"), k, mode="valid")[: len(sig)]
    s[~good] = np.nan          # 결측은 보간 후에도 결측으로 되돌린다
    return s


def compute_signals(frames, side: str, fps: float, cfg: Config) -> dict:
    n = len(frames)
    curl = np.full(n, np.nan)
    wrist = np.full((n, 2), np.nan)
    span = np.full(n, np.nan)
    for i, f in enumerate(frames):
        obs = f.hands.get(side)
        if obs is not None:
            curl[i], span[i] = obs.curl, obs.span
            wrist[i] = obs.wrist
    present = ~np.isnan(curl)

    curl_s = _smooth(curl, cfg.smooth_window)
    dcurl = np.full(n, np.nan)
    filled = np.nan_to_num(curl_s, nan=np.nanmean(curl_s) if present.any() else 0.0)
    if n > 2:
        dcurl[1:-1] = (filled[2:] - filled[:-2]) / 2.0 * fps
    dcurl[~present] = np.nan

    speed = np.full(n, np.nan)
    for i in range(1, n):
        if present[i] and present[i - 1] and span[i] > 1e-3:
            speed[i] = float(np.linalg.norm(wrist[i] - wrist[i - 1])) / span[i] * fps
    speed = _smooth(speed, cfg.smooth_window)

    # 왕복 운동 지표: 창 안의 경로 길이 / 순변위
    win = max(3, int(cfg.use_window_s * fps))
    osc = np.full(n, np.nan)
    for i in range(n):
        a, b = max(0, i - win // 2), min(n, i + win // 2 + 1)
        seg = wrist[a:b]
        ok = ~np.isnan(seg[:, 0])
        if ok.sum() < 3:
            continue
        seg = seg[ok]
        path = float(np.sum(np.linalg.norm(np.diff(seg, axis=0), axis=1)))
        net = float(np.linalg.norm(seg[-1] - seg[0]))
        osc[i] = path / max(net, 1e-3)
    return {"curl": curl_s, "dcurl": dcurl, "speed": speed, "osc": osc, "present": present}


def _grip_state(curl: np.ndarray, cfg: Config) -> np.ndarray:
    """히스테리시스로 쥠(True)/폄(False) 상태를 만든다. 결측은 직전 상태 유지."""
    state = np.zeros(len(curl), dtype=bool)
    cur = False
    for i, v in enumerate(curl):
        if not np.isnan(v):
            if cur and v > cfg.open_curl:
                cur = False
            elif not cur and v < cfg.close_curl:
                cur = True
        state[i] = cur
    return state


def label_frames(sig: dict, fps: float, cfg: Config) -> np.ndarray:
    n = len(sig["curl"])
    labels = np.full(n, "-", dtype="<U2")
    present, speed, osc = sig["present"], sig["speed"], sig["osc"]
    grip = _grip_state(sig["curl"], cfg)

    for i in range(n):
        if not present[i]:
            continue
        sp = speed[i] if not np.isnan(speed[i]) else 0.0
        if grip[i]:
            if sp > cfg.move_speed:
                labels[i] = "TL"
            elif not np.isnan(osc[i]) and osc[i] > cfg.use_ratio and sp > cfg.still_speed:
                labels[i] = "U"
            elif sp > cfg.still_speed:
                labels[i] = "P"
            else:
                labels[i] = "H"
        else:
            labels[i] = "TE" if sp > cfg.still_speed else "D"

    # 쥠 상태가 바뀌는 지점만 G/RL 로 덮어쓴다. 전이 구간은 손가락이 실제로
    # 움직이는(=|dcurl| 이 큰) 프레임까지만 확장한다.
    dcurl, cap = sig["dcurl"], max(1, int(cfg.max_transition_s * fps))
    for i in range(1, n):
        if grip[i] == grip[i - 1]:
            continue
        tag = "G" if grip[i] else "RL"
        lo = hi = i
        while lo > 0 and i - lo < cap and not np.isnan(dcurl[lo - 1]) \
                and abs(dcurl[lo - 1]) > cfg.grasp_rate * 0.4:
            lo -= 1
        while hi + 1 < n and hi - i < cap and not np.isnan(dcurl[hi + 1]) \
                and abs(dcurl[hi + 1]) > cfg.grasp_rate * 0.4:
            hi += 1
        for j in range(lo, hi + 1):
            if present[j]:
                labels[j] = tag
    return labels


def build_segments(labels: np.ndarray, times: np.ndarray, cfg: Config) -> list[dict]:
    if len(labels) == 0:
        return []
    dt = float(np.median(np.diff(times))) if len(times) > 1 else 0.0
    segs = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            segs.append({"therblig": str(labels[start]),
                         "start_s": float(times[start]),
                         "end_s": float(times[i - 1]) + dt})
            start = i

    # 짧은 조각은 이웃에 흡수시킨다. 쥐기/놓기는 원래 짧으므로 2프레임 이상이면 지킨다.
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for i, s in enumerate(segs):
            dur = s["end_s"] - s["start_s"]
            protected = s["therblig"] in ("G", "RL") and dur >= 2 * dt
            if dur >= cfg.min_segment_s or protected:
                continue
            prev_s = segs[i - 1] if i > 0 else None
            next_s = segs[i + 1] if i + 1 < len(segs) else None
            pick = max([x for x in (prev_s, next_s) if x],
                       key=lambda x: x["end_s"] - x["start_s"])
            pick["start_s"] = min(pick["start_s"], s["start_s"])
            pick["end_s"] = max(pick["end_s"], s["end_s"])
            segs.pop(i)
            changed = True
            break

    merged = [segs[0]]
    for s in segs[1:]:
        if s["therblig"] == merged[-1]["therblig"]:
            merged[-1]["end_s"] = s["end_s"]
        else:
            merged.append(s)
    for s in merged:
        s["start_s"] = round(s["start_s"], 3)
        s["end_s"] = round(s["end_s"], 3)
        s["dur_s"] = round(s["end_s"] - s["start_s"], 3)
        s["name_ko"] = THERBLIGS[s["therblig"]][0]
        s["class"] = THERBLIGS[s["therblig"]][2]
    return merged


def _cycles(segs: list[dict]) -> dict:
    """G 로 시작해 RL 로 끝나면 1사이클.

    loaded = 쥐고 있던 시간(G 시작 ~ RL 끝), period = 다음 사이클까지의 반복 주기.
    표준시간 산출에는 period, 낭비 분석에는 loaded 를 본다.
    """
    cycles, open_g = [], None
    for s in segs:
        if s["therblig"] == "G" and open_g is None:
            open_g = s
        elif s["therblig"] == "RL" and open_g is not None:
            cycles.append({"start_s": open_g["start_s"], "release_s": s["end_s"],
                           "loaded_s": round(s["end_s"] - open_g["start_s"], 2)})
            open_g = None
    for a, b in zip(cycles, cycles[1:]):
        a["period_s"] = round(b["start_s"] - a["start_s"], 2)
    periods = [c["period_s"] for c in cycles if "period_s" in c]
    loaded = [c["loaded_s"] for c in cycles]
    return {"count": len(cycles),
            "mean_period_seconds": round(float(np.mean(periods)), 2) if periods else None,
            "sd_period_seconds": round(float(np.std(periods)), 2) if periods else None,
            "mean_loaded_seconds": round(float(np.mean(loaded)), 2) if loaded else None,
            "list": cycles}


def summarise_side(segs: list[dict], total_s: float) -> dict:
    by_t, by_c = {}, {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
    for s in segs:
        by_t.setdefault(s["therblig"], {"seconds": 0.0, "count": 0})
        by_t[s["therblig"]]["seconds"] += s["dur_s"]
        by_t[s["therblig"]]["count"] += 1
        by_c[s["class"]] += s["dur_s"]
    for k, v in by_t.items():
        v["seconds"] = round(v["seconds"], 2)
        v["share"] = round(v["seconds"] / total_s, 3) if total_s else 0.0
        v["name_ko"] = THERBLIGS[k][0]
    tracked = total_s - by_c[0]
    return {
        "by_therblig": dict(sorted(by_t.items(), key=lambda kv: -kv[1]["seconds"])),
        "by_class": {CLASS_NAMES[c]: round(sec, 2) for c, sec in by_c.items()},
        "effective_share": round(by_c[1] / tracked, 3) if tracked > 0 else None,
        "waste_share": round(by_c[3] / tracked, 3) if tracked > 0 else None,
        "cycles": _cycles(segs),
        "segments": segs,
    }


def summarise(per_side: dict, times: np.ndarray) -> dict:
    total_s = float(times[-1] - times[0]) if len(times) > 1 else 0.0
    out = {"duration_s": round(total_s, 2),
           "hands": {side: summarise_side(segs, total_s) for side, segs in per_side.items()}}

    # 양수동작분석의 핵심: 한 손이 노는 시간
    if len(per_side) == 2:
        grids = {side: _label_grid(segs, times) for side, segs in per_side.items()}
        left, right = grids.get("Left"), grids.get("Right")
        if left is not None and right is not None:
            dt = float(np.median(np.diff(times))) if len(times) > 1 else 0.0
            idle = {"D", "H", "-"}
            both = sum(1 for a, b in zip(left, right) if a in idle and b in idle) * dt
            one = sum(1 for a, b in zip(left, right) if (a in idle) != (b in idle)) * dt
            out["two_hand"] = {"both_idle_s": round(both, 2),
                               "one_idle_s": round(one, 2),
                               "both_working_s": round(max(total_s - both - one, 0.0), 2)}
    return out


def _label_grid(segs: list[dict], times: np.ndarray) -> list[str]:
    grid = ["-"] * len(times)
    for s in segs:
        for i, t in enumerate(times):
            if s["start_s"] <= t < s["end_s"]:
                grid[i] = s["therblig"]
    return grid


def config_dict(cfg: Config) -> dict:
    return asdict(cfg)
