"""작업요소 분할과 사이클 정합.

서블릭 -> 작업요소 -> 사이클 -> 표준 순서. 작업표준서의 뼈대가 여기서 나온다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# 요소의 끝으로 삼는 서블릭. 내려놓기와 사용 완료가 자연스러운 작업요소 구분점이다.
BREAKPOINTS = ("RL", "U")
IDLE = {"D", "H", "-"}


@dataclass
class Element:
    index: int
    start_s: float
    end_s: float
    dom_seq: list[str] = field(default_factory=list)
    sup_seq: list[str] = field(default_factory=list)
    grasp_xy: tuple[float, float] | None = None
    release_xy: tuple[float, float] | None = None
    cycle: int | None = None
    position: int | None = None
    out_of_order: bool = False
    name: str | None = None

    @property
    def dur_s(self) -> float:
        return round(self.end_s - self.start_s, 3)

    @property
    def signature(self) -> str:
        return ">".join(self.dom_seq)

    def to_dict(self) -> dict:
        return {"index": self.index, "cycle": self.cycle, "position": self.position,
                "out_of_order": self.out_of_order,
                "name": self.name, "start_s": round(self.start_s, 2),
                "end_s": round(self.end_s, 2), "dur_s": self.dur_s,
                "signature": self.signature, "support": ">".join(self.sup_seq),
                "grasp_xy": None if self.grasp_xy is None else [round(v, 3) for v in self.grasp_xy],
                "release_xy": None if self.release_xy is None else [round(v, 3) for v in self.release_xy]}


def dominant_hand(per_side: dict) -> str:
    """G(쥐기) 횟수가 많은 쪽. 동수면 유효 동작 시간이 긴 쪽."""
    score = {}
    for side, segs in per_side.items():
        grasps = sum(1 for s in segs if s["therblig"] == "G")
        active = sum(s["dur_s"] for s in segs if s["therblig"] not in IDLE)
        score[side] = (grasps, active)
    return max(score, key=lambda s: score[s])


def _wrist_at(frames, times: np.ndarray, side: str, t: float, meta: dict):
    i = int(np.argmin(np.abs(times - t)))
    for j in range(max(0, i - 3), min(len(frames), i + 4)):
        obs = frames[j].hands.get(side)
        if obs is not None:
            return (float(obs.wrist[0]) / meta["width"], float(obs.wrist[1]) / meta["height"])
    return None


def split_elements(per_side: dict, dom: str, frames, times: np.ndarray, meta: dict,
                   breakpoints=BREAKPOINTS, min_dur_s: float = 0.4) -> list[Element]:
    """우세손의 RL/U 종료 지점을 요소 구분점으로 삼아 타임라인을 끊는다.

    구분점 사이의 모든 시간이 어느 요소엔가 속하도록 빈틈 없이 자른다. 앞쪽의
    빈손이동과 대기는 그 다음 작업을 위한 준비이므로 뒤따르는 요소에 포함된다.
    """
    dom_segs = per_side[dom]
    sup = "Left" if dom == "Right" else "Right"
    sup_segs = per_side.get(sup, [])
    if not dom_segs:
        return []

    cuts = [s["end_s"] for s in dom_segs if s["therblig"] in breakpoints]
    if not cuts:
        return []
    timeline_end = dom_segs[-1]["end_s"]
    if timeline_end - cuts[-1] > min_dur_s:
        cuts.append(timeline_end)

    elements, start = [], dom_segs[0]["start_s"]
    for end in cuts:
        if end - start < min_dur_s:
            continue
        el = Element(index=len(elements), start_s=start, end_s=end)
        el.dom_seq = [s["therblig"] for s in dom_segs
                      if s["end_s"] > start and s["start_s"] < end and s["therblig"] != "-"]
        el.sup_seq = [s["therblig"] for s in sup_segs
                      if s["end_s"] > start and s["start_s"] < end and s["therblig"] != "-"]
        for tag, attr in (("G", "grasp_xy"), ("RL", "release_xy")):
            hit = [s for s in dom_segs
                   if s["therblig"] == tag and s["end_s"] > start and s["start_s"] < end]
            if hit:
                mid = (hit[0]["start_s"] + hit[0]["end_s"]) / 2
                setattr(el, attr, _wrist_at(frames, times, dom, mid, meta))
        if el.grasp_xy is None:
            el.grasp_xy = _wrist_at(frames, times, dom, start, meta)
        if el.release_xy is None:
            el.release_xy = _wrist_at(frames, times, dom, end, meta)
        elements.append(el)
        start = end
    return elements


def feature_matrix(elements: list[Element]) -> np.ndarray:
    """요소를 비교 가능한 벡터로. 집는 위치와 놓는 위치가 요소의 정체성을 가른다."""
    med = float(np.median([e.dur_s for e in elements])) or 1.0
    rows = []
    for e in elements:
        g = e.grasp_xy or (0.5, 0.5)
        r = e.release_xy or (0.5, 0.5)
        rows.append([g[0] * 2, g[1] * 2, r[0] * 2, r[1] * 2,
                     min(e.dur_s / med, 3.0) * 0.5,
                     1.0 if "U" in e.dom_seq else 0.0,
                     0.6 if "H" in e.sup_seq else 0.0])
    return np.array(rows, dtype=np.float64)


def _dist(F: np.ndarray, i: int, j: int) -> float:
    return float(np.linalg.norm(F[i] - F[j]))


def detect_period(F: np.ndarray, max_period: int | None = None,
                  tol: float = 0.25) -> tuple[int, float | None]:
    """요소 시퀀스의 반복 주기를 찾는다.

    주기 p의 비용은 "p칸 떨어진 요소끼리의 거리 중앙값"이다. 평균이 아니라
    중앙값을 쓰는 이유는 한 사이클에서 순서가 바뀌어도 주기 판정이 흔들리지
    않게 하기 위해서다. 참주기의 배수도 비용이 똑같이 낮으므로, 최소 비용에서
    데이터 전체 산포의 tol 배 안에 드는 가장 짧은 주기를 고른다.

    반환: (주기, 반복 신뢰도). 신뢰도는 같은 위치끼리의 거리를 다른 위치끼리의
    거리와 비교한 값이고, 주기가 1이면 비교 대상이 없어 None.
    """
    n = len(F)
    if n < 2:
        return (max(n, 1), None)
    baseline = float(np.median([_dist(F, i, j) for i in range(n) for j in range(i + 1, n)]))
    cap = max_period or max(1, n // 2)
    costs = {}
    for p in range(1, cap + 1):
        pairs = [_dist(F, i, i + p) for i in range(n - p)]
        if len(pairs) >= 2:
            costs[p] = float(np.median(pairs))
    if not costs:
        return (1, None)
    floor = min(costs.values())
    threshold = floor + tol * baseline
    period = min(p for p, c in costs.items() if c <= threshold)

    if period == 1:
        return (1, None)
    across = [_dist(F, i, j) for i in range(n) for j in range(i + 1, n) if (j - i) % period]
    if not across:
        return (period, None)
    scale = float(np.median(across)) or 1e-9
    conf = float(np.clip(1.0 - costs[period] / scale, 0.0, 1.0))
    if conf < 0.2:
        # 같은 위치끼리가 다른 위치끼리보다 딱히 닮지 않았다 = 주기 구조가 없다.
        return (1, None)
    return (period, round(conf, 3))


def split_cycles(elements: list[Element], period: int, F: np.ndarray) -> list[list[Element]]:
    """주기로 끊되, 사이클 시작점(오프셋)은 위치별 분산이 가장 작은 쪽으로 고른다."""
    n = len(elements)
    if period < 1 or n < period:
        return [elements]
    best_off, best_var = 0, float("inf")
    for off in range(period):
        groups = [[] for _ in range(period)]
        for i in range(off, n):
            groups[(i - off) % period].append(i)
        var = float(np.mean([np.mean(np.var(F[idx], axis=0)) for idx in groups if len(idx) > 1]
                            or [float("inf")]))
        if var < best_var:
            best_off, best_var = off, var
    cycles = []
    for s in range(best_off, n - period + 1, period):
        chunk = elements[s:s + period]
        for pos, el in enumerate(chunk):
            el.position = pos
            el.cycle = len(cycles)
        cycles.append(chunk)
    return cycles


def dtw_align(ref_F: np.ndarray, cyc_F: np.ndarray, gap: float) -> list[tuple[int | None, int | None]]:
    """참조 사이클과 대상 사이클을 정렬한다. 누락/추가 요소는 한쪽이 None."""
    m, k = len(ref_F), len(cyc_F)
    dp = np.full((m + 1, k + 1), np.inf)
    dp[0, 0] = 0.0
    for i in range(m + 1):
        for j in range(k + 1):
            if i < m:
                dp[i + 1, j] = min(dp[i + 1, j], dp[i, j] + gap)
            if j < k:
                dp[i, j + 1] = min(dp[i, j + 1], dp[i, j] + gap)
            if i < m and j < k:
                d = float(np.linalg.norm(ref_F[i] - cyc_F[j]))
                dp[i + 1, j + 1] = min(dp[i + 1, j + 1], dp[i, j] + d)
    i, j, out = m, k, []
    while i > 0 or j > 0:
        cur = dp[i, j]
        if i > 0 and j > 0 and np.isclose(cur, dp[i - 1, j - 1] + float(np.linalg.norm(ref_F[i - 1] - cyc_F[j - 1]))):
            out.append((i - 1, j - 1)); i, j = i - 1, j - 1
        elif i > 0 and np.isclose(cur, dp[i - 1, j] + gap):
            out.append((i - 1, None)); i -= 1
        else:
            out.append((None, j - 1)); j -= 1
    return list(reversed(out))


def _iqr(vals) -> float:
    return float(np.percentile(vals, 75) - np.percentile(vals, 25)) if len(vals) > 1 else 0.0


def build_standard(cycles: list[list[Element]], F: np.ndarray, elements: list[Element]) -> dict:
    """사이클들을 정렬해 표준 순서와 요소별 시간, 변동 구간을 뽑는다."""
    idx_of = {id(e): i for i, e in enumerate(elements)}
    feats = [F[[idx_of[id(e)] for e in cyc]] for cyc in cycles]
    gap = float(np.median([np.linalg.norm(F[i] - F[j])
                           for i in range(len(F)) for j in range(i + 1, len(F))])) if len(F) > 1 else 1.0
    gap = max(gap, 1e-6)

    # 다른 사이클과 가장 닮은 사이클을 참조로
    ref = 0
    if len(cycles) > 1:
        costs = []
        for a in range(len(cycles)):
            tot = 0.0
            for b in range(len(cycles)):
                if a == b:
                    continue
                al = dtw_align(feats[a], feats[b], gap)
                tot += sum(float(np.linalg.norm(feats[a][i] - feats[b][j]))
                           if i is not None and j is not None else gap for i, j in al)
            costs.append(tot)
        ref = int(np.argmin(costs))

    m = len(cycles[ref])
    slots: list[list[Element | None]] = [[None] * len(cycles) for _ in range(m)]
    extras = []
    for c, cyc in enumerate(cycles):
        if c == ref:
            for i, el in enumerate(cyc):
                slots[i][c] = el
            continue
        for i, j in dtw_align(feats[ref], feats[c], gap):
            if i is not None and j is not None:
                slots[i][c] = cyc[j]
            elif j is not None:
                cyc[j].position = None
                extras.append({"cycle": c, "element": cyc[j].index,
                               "start_s": round(cyc[j].start_s, 2)})

    # 누락과 추가가 같은 사이클에서 짝지어지면 그건 빠진 게 아니라 순서가 바뀐 것이다.
    variations = []
    for ex in list(extras):
        c, el = ex["cycle"], elements[ex["element"]]
        fe = F[idx_of[id(el)]]
        empty = [pos for pos in range(m) if slots[pos][c] is None
                 and any(e is not None for e in slots[pos])]
        if not empty:
            continue
        def _centre(pos):
            present = [F[idx_of[id(e)]] for e in slots[pos] if e is not None]
            return np.median(np.vstack(present), axis=0)
        best = min(empty, key=lambda pos: float(np.linalg.norm(fe - _centre(pos))))
        if float(np.linalg.norm(fe - _centre(best))) <= gap:
            slots[best][c] = el
            el.position, el.out_of_order = best, True
            extras.remove(ex)
            variations.append({"cycle": c, "position": best, "type": "reorder",
                               "detail": f"{best + 1}번 요소를 {ex['start_s']}초에 다른 순서로 수행"})

    standard = []
    for pos, row in enumerate(slots):
        present = [e for e in row if e is not None]
        for e in present:
            e.position = pos
        durs = [e.dur_s for e in present]
        sigs = [e.signature for e in present]
        mode_sig = max(set(sigs), key=sigs.count) if sigs else ""
        median = float(np.median(durs)) if durs else 0.0
        iqr = _iqr(durs)
        flags = []
        if any(e.out_of_order for e in present):
            flags.append("순서 이탈")
        if len(present) < len(cycles):
            flags.append("누락")
            for c, e in enumerate(row):
                if e is None:
                    variations.append({"cycle": c, "position": pos, "type": "missing",
                                       "detail": f"{pos + 1}번 요소가 이 사이클에 없음"})
        if median > 0 and iqr / median > 0.3:
            flags.append("산포")
            variations.append({"cycle": None, "position": pos, "type": "spread",
                               "detail": f"IQR/중앙값 {iqr / median:.2f}"})
        if sigs and sigs.count(mode_sig) / len(sigs) < 0.8:
            flags.append("동작구성 불일치")
        standard.append({
            "position": pos + 1, "signature": mode_sig,
            "median_s": round(median, 2), "iqr_s": round(iqr, 2),
            "min_s": round(min(durs), 2) if durs else None,
            "max_s": round(max(durs), 2) if durs else None,
            "presence": f"{len(present)}/{len(cycles)}", "flags": flags,
            "support_used": any("H" in e.sup_seq or "U" in e.sup_seq for e in present),
        })
    for ex in extras:
        variations.append({"cycle": ex["cycle"], "position": None, "type": "extra",
                           "detail": f"표준에 없는 요소가 {ex['start_s']}초에 추가됨"})

    cyc_secs = [round(c[-1].end_s - c[0].start_s, 2) for c in cycles]
    return {
        "reference_cycle": ref + 1,
        "cycle_count": len(cycles),
        "elements_per_cycle": m,
        "cycle_seconds": {"median": round(float(np.median(cyc_secs)), 2),
                          "iqr": round(_iqr(cyc_secs), 2), "values": cyc_secs},
        "net_time_s": round(sum(s["median_s"] for s in standard), 2),
        "standard": standard,
        "variations": variations,
    }
