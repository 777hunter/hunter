"""M5 — 포카요케 리스크 신호 검출.

영상에서 나오는 건 리스크 신호뿐이다. "이 불량이 난다"는 사실은 영상에 없으므로
불량 이력이나 공정 FMEA 를 붙여야 대책이 된다. 여기서는 근거가 있는 신호를 뽑고
포카요케 후보를 제안하는 데까지만 한다. 채택은 사람이 한다.
"""
from __future__ import annotations

import csv
import os

import numpy as np

SEV_ORDER = {"상": 0, "중": 1, "하": 2}
PREVENT, DETECT = "예방(원인 차단)", "검출(발견)"


def _bump(sev: str) -> str:
    return {"하": "중", "중": "상", "상": "상"}[sev]


def _cycles_of(std: dict) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for el in std.get("elements", []):
        if el.get("cycle") is not None:
            out.setdefault(el["cycle"], []).append(el)
    for cyc in out.values():
        cyc.sort(key=lambda e: e["start_s"])
    return out


def _name_of(std: dict, position: int) -> str:
    for row in std["standard"]:
        if row["position"] == position:
            return row.get("name") or row.get("signature") or f"{position}번 요소"
    return f"{position}번 요소"


def r_reorder(std, zones, ctx):
    out = []
    for row in std["standard"]:
        if "순서 이탈" not in (row.get("flags") or []):
            continue
        cycles = sorted({v["cycle"] + 1 for v in std.get("variations", [])
                         if v["type"] == "reorder" and v.get("position") == row["position"] - 1
                         and v.get("cycle") is not None})
        out.append({
            "signal": "작업 순서가 사이클마다 다름",
            "positions": [row["position"]],
            "evidence": f'사이클 {", ".join(map(str, cycles))}번에서 순서가 바뀜'
                        if cycles else "관측 중 순서 변동",
            "basis": "사이클 정합에서 표준 순서와 다른 위치에 수행됨",
            "suspect": ["공정 누락", "오조립", "체결 순서 오류"],
            "countermeasures": [
                {"type": PREVENT, "text": "지그 인터록 — 앞 공정이 끝나야 다음 부품이 안착되게"},
                {"type": PREVENT, "text": "부품 공급 순서화 — 키트화, 순차 배출 슈트"},
                {"type": DETECT, "text": "순차 점등 — 다음 집을 곳만 불이 들어오게"},
            ],
            "severity": "중",
        })
    return out


def r_spread(std, zones, ctx):
    out = []
    for row in std["standard"]:
        med, iqr = row.get("median_s") or 0, row.get("iqr_s") or 0
        if not med or iqr / med <= 0.3:
            continue
        ratio = iqr / med
        out.append({
            "signal": "작업시간 산포가 큼",
            "positions": [row["position"]],
            "evidence": f'중앙값 {med}초, IQR {iqr}초 (비 {ratio:.2f}), '
                        f'범위 {row.get("min_s")}~{row.get("max_s")}초',
            "basis": "사이클 간 소요시간 분포",
            "suspect": ["작업 난이도 과다", "부품 편차", "치공구 불량", "숙련도 편차"],
            "countermeasures": [
                {"type": PREVENT, "text": "치공구 개선 — 위치결정 핀, 안내 챔퍼 추가"},
                {"type": PREVENT, "text": "부품 공급 위치·자세 고정 — 방향 맞춰 공급"},
                {"type": DETECT, "text": "사이클타임 이상 감지 — 상한 초과 시 경보"},
            ],
            "severity": "상" if ratio > 0.5 else "중",
        })
    return out


def r_no_check_after_use(std, zones, ctx):
    """체결·가공 직후에 확인으로 볼 만한 정지 동작이 없는 경우."""
    inspect_ids = {z.id for z in (zones or []) if z.kind == "inspect"}
    out, seen = [], set()
    for cyc in _cycles_of(std).values():
        for i, el in enumerate(cyc):
            use_s = (el.get("therblig_s") or {}).get("U", 0)
            if use_s < 0.3 or el.get("position") is None:
                continue
            rest = cyc[i + 1:]
            pause = sum((r.get("therblig_s") or {}).get(t, 0)
                        for r in rest[:1] for t in ("D", "H"))
            touched = any(r.get("grasp_zone") in inspect_ids or r.get("release_zone") in inspect_ids
                          for r in rest)
            if pause >= 0.4 or touched:
                continue
            pos = el["position"] + 1
            if pos in seen:
                continue
            seen.add(pos)
            out.append({
                "signal": "체결·가공 직후 확인 동작 없음",
                "positions": [pos],
                "evidence": f'사용(U) {use_s:.1f}초 뒤 정지·검사 동작이 {pause:.1f}초에 그침',
                "basis": "요소 내 서블릭 구성과 다음 요소의 정지시간",
                "suspect": ["체결 누락", "토크 미달", "미압입"],
                "countermeasures": [
                    {"type": DETECT, "text": "토크 카운터 — 규정 횟수·토크 미달 시 다음 공정 잠금"},
                    {"type": DETECT, "text": "비전 확인 — 체결부 유무·색 마킹 판정"},
                    {"type": PREVENT, "text": "체결 후 자동 마킹 — 미마킹품은 육안으로 걸러짐"},
                ],
                "severity": "상",
                "needs": "검사 존이 정의돼 있지 않으면 오검출일 수 있다" if not inspect_ids else None,
            })
    return out


def r_hold_heavy(std, zones, ctx):
    """한 손이 잡고만 있는 시간이 긴 요소. 고정 지그로 없앨 수 있는 낭비다."""
    shares: dict[int, list[float]] = {}
    for el in std.get("elements", []):
        if el.get("position") is None or not el.get("dur_s"):
            continue
        hold = ((el.get("sup_therblig_s") or {}).get("H", 0)
                + (el.get("therblig_s") or {}).get("H", 0))
        shares.setdefault(el["position"] + 1, []).append(hold / el["dur_s"])
    out = []
    for pos, vals in shares.items():
        share = float(np.median(vals))
        if share <= 0.2:
            continue
        out.append({
            "signal": "잡고만 있는 시간이 김",
            "positions": [pos],
            "evidence": f'요소 시간의 {share:.0%} 가 Hold',
            "basis": "요소별 서블릭 H 비중 (사이클 중앙값)",
            "suspect": ["위치 어긋남", "손 피로 누적", "양손 작업 불가"],
            "countermeasures": [
                {"type": PREVENT, "text": "고정 지그·클램프 도입으로 Hold 제거"},
                {"type": PREVENT, "text": "부품 자중으로 안착되는 받침 형상"},
            ],
            "severity": "중",
        })
    return out


def r_rework(std, zones, ctx):
    out = []
    for v in std.get("variations", []):
        if v["type"] != "extra":
            continue
        out.append({
            "signal": "표준에 없는 동작이 추가됨",
            "positions": [],
            "evidence": f'사이클 {v["cycle"] + 1}번 — {v["detail"]}',
            "basis": "사이클 정합에서 참조 사이클에 대응되지 않는 요소",
            "suspect": ["재작업", "부품 떨어뜨림", "1회 성공률 미달"],
            "countermeasures": [
                {"type": PREVENT, "text": "1회 성공률 저해 요인 추적 — 해당 구간 영상 확인"},
                {"type": DETECT, "text": "재작업 발생 기록 — 빈도가 잡혀야 원인이 보인다"},
            ],
            "severity": "상",
        })
    return out


def r_similar_parts(std, zones, ctx):
    """부품 존이 서로 붙어 있으면 집을 때 헷갈린다."""
    parts = [z for z in (zones or []) if z.kind == "part"]
    out = []
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            # 사각형 사이의 실제 간격. 중심 기준으로 재면 큰 존일수록 멀어 보인다.
            dx = max(a.rect[0] - b.rect[2], b.rect[0] - a.rect[2], 0.0)
            dy = max(a.rect[1] - b.rect[3], b.rect[1] - a.rect[3], 0.0)
            gap = float(np.hypot(dx, dy))
            if gap > 0.06:
                continue
            unnamed = not (a.item and b.item)
            out.append({
                "signal": "부품 공급 위치가 서로 인접",
                "positions": [],
                "evidence": f'{a.name} 과 {b.name} 의 간격 {gap:.3f} (화면 비율)'
                            + (" · 품명이 지정되지 않아 구분 근거가 없다" if unnamed else ""),
                "basis": "존 정의 좌표",
                "suspect": ["오품 조립", "좌우 대칭 부품 혼입"],
                "countermeasures": [
                    {"type": PREVENT, "text": "공급 위치 분리 — 손이 닿는 순서로 거리 확보"},
                    {"type": PREVENT, "text": "형상·색 구분 — 대칭 부품은 비대칭 형상으로"},
                    {"type": DETECT, "text": "부품별 픽투라이트 — 집어야 할 박스만 점등"},
                ],
                "severity": "중",
            })
    return out


def r_long_reach(std, zones, ctx):
    out = []
    for row in std["standard"]:
        if "장거리 이동" not in (row.get("flags") or []):
            continue
        out.append({
            "signal": "손 이동 거리가 김",
            "positions": [row["position"]],
            "evidence": "집는 위치와 놓는 위치가 화면 대각선의 절반 이상 떨어져 있다",
            "basis": "요소별 집는 지점과 놓는 지점 사이 거리",
            "suspect": ["작업 피로", "사이클타임 손실"],
            "countermeasures": [
                {"type": PREVENT, "text": "부품 공급 위치를 작업점 가까이 이동"},
                {"type": PREVENT, "text": "동작경제 원칙 — 정상 작업역 안으로 배치"},
            ],
            "severity": "하",
        })
    return out


def r_idle_hand(std, zones, ctx):
    two = std.get("two_hand") or {}
    total = sum(v for v in two.values() if isinstance(v, (int, float))) or 0
    if not total:
        return []
    out = []
    one = two.get("one_idle_s", 0) / total
    both = two.get("both_idle_s", 0) / total
    if one > 0.5:
        out.append({
            "signal": "한 손만 일하고 있음",
            "positions": [],
            "evidence": f'한 손이 노는 시간 {one:.0%} ({two.get("one_idle_s")}초)',
            "basis": "양손 서블릭 동시 분석",
            "suspect": ["작업 배분 불균형", "지그 부재"],
            "countermeasures": [
                {"type": PREVENT, "text": "양손 동시 작업으로 재설계 — 좌우 대칭 배치"},
                {"type": PREVENT, "text": "노는 손이 다음 부품을 미리 집도록 순서 조정"},
            ],
            "severity": "하",
        })
    if both > 0.25:
        out.append({
            "signal": "양손이 동시에 노는 시간이 김",
            "positions": [],
            "evidence": f'양손 유휴 {both:.0%} ({two.get("both_idle_s")}초)',
            "basis": "양손 서블릭 동시 분석",
            "suspect": ["설비 대기", "부품 공급 지연"],
            "countermeasures": [
                {"type": PREVENT, "text": "대기 원인 제거 — 설비 사이클과 수작업 분리"},
                {"type": PREVENT, "text": "대기 중 수행 가능한 요소를 앞당김"},
            ],
            "severity": "하",
        })
    return out


RULES = [r_reorder, r_spread, r_no_check_after_use, r_hold_heavy,
         r_rework, r_similar_parts, r_long_reach, r_idle_hand]


def load_defects(path: str) -> list[dict]:
    """불량 이력 CSV. 열 이름: 불량모드, 건수(선택), 키워드(선택)."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            mode = (r.get("불량모드") or r.get("mode") or "").strip()
            if not mode:
                continue
            rows.append({
                "mode": mode,
                "count": int(float(r.get("건수") or r.get("count") or 0) or 0),
                "keyword": (r.get("키워드") or r.get("keyword") or mode).strip(),
            })
    return rows


def link_defects(risks: list[dict], std: dict, defects: list[dict]) -> None:
    """불량 이력 키워드를 요소 이름·신호 이름에 맞춰 붙인다. 붙으면 심각도를 한 단계 올린다.

    단순 문자열 포함 매칭이라 사람이 한 번 봐야 한다. 키워드를 좁게 쓸수록 정확하다.
    """
    for risk in risks:
        hits = []
        names = " ".join(_name_of(std, p) for p in risk["positions"]) or ""
        # 관측에서 나온 것(요소 이름, 신호 이름)에만 맞춘다. 의심 불량 목록은
        # 이쪽에서 쓴 예시 문구라 여기에 맞추면 아무 신호에나 다 붙는다.
        haystack = f'{names} {risk["signal"]}'
        for d in defects:
            if d["keyword"] and d["keyword"] in haystack:
                hits.append(d)
        if hits:
            risk["defects"] = [{"mode": d["mode"], "count": d["count"]} for d in hits]
            risk["severity"] = _bump(risk["severity"])


def detect(std: dict, zones=None, defects=None) -> dict:
    ctx = {}
    risks = []
    for rule in RULES:
        risks.extend(rule(std, zones, ctx))
    for i, r in enumerate(risks, 1):
        r["id"] = f"R{i:02d}"
        r["names"] = [_name_of(std, p) for p in r["positions"]]
        r.setdefault("needs", None)
        r.setdefault("defects", [])
    if defects:
        link_defects(risks, std, defects)
    risks.sort(key=lambda r: (SEV_ORDER[r["severity"]], r["id"]))

    by_sev = {s: sum(1 for r in risks if r["severity"] == s) for s in ("상", "중", "하")}
    return {
        "risks": risks,
        "summary": {"total": len(risks), "by_severity": by_sev,
                    "defect_linked": sum(1 for r in risks if r["defects"]),
                    "defect_source": bool(defects)},
    }


def write_csv(path: str, doc: dict) -> str:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ID", "심각도", "신호", "대상 단계", "근거 수치", "의심 불량",
                    "포카요케 후보", "연결된 불량 이력", "판단 근거", "비고"])
        for r in doc["risks"]:
            w.writerow([
                r["id"], r["severity"], r["signal"],
                ", ".join(f'{p}. {n}' for p, n in zip(r["positions"], r["names"])) or "공정 전체",
                r["evidence"], " / ".join(r["suspect"]),
                " / ".join(f'[{c["type"]}] {c["text"]}' for c in r["countermeasures"]),
                " / ".join(f'{d["mode"]}({d["count"]}건)' for d in r["defects"]),
                r["basis"], r.get("needs") or "",
            ])
    return path
