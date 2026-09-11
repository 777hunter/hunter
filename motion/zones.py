"""작업영역(존) 정의와 요소 자동 명명.

기계가 보는 건 "손이 화면 왼쪽 아래에서 뭔가를 쥐고 가운데로 옮겼다"까지다.
그게 부품박스인지 지그인지는 사람이 한 번 알려줘야 한다. 존을 정의하면
"부품박스 A에서 브래킷 집어 지그에 조립"이 자동으로 만들어진다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

KINDS = {
    "part": "부품",
    "jig": "지그",
    "tool": "공구",
    "output": "배출",
    "inspect": "검사",
    "other": "기타",
}


def _has_batchim(word: str) -> bool:
    """한글 마지막 글자에 받침이 있나. 조사 선택용."""
    for ch in reversed(word.strip()):
        if "가" <= ch <= "힣":
            return (ord(ch) - 0xAC00) % 28 != 0
        if ch.isalnum():
            return ch.isdigit() or ch.lower() in "lmnr"
    return False


def josa(word: str, with_batchim: str, without: str) -> str:
    return word + (with_batchim if _has_batchim(word) else without)


@dataclass
class Zone:
    id: str
    name: str
    kind: str = "other"
    item: str = ""
    rect: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)   # 정규화 x0,y0,x1,y1

    @property
    def centre(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.rect
        return ((x0 + x1) / 2, (y0 + y1) / 2)

    def contains(self, xy) -> bool:
        x0, y0, x1, y1 = self.rect
        return x0 <= xy[0] <= x1 and y0 <= xy[1] <= y1

    def distance(self, xy) -> float:
        """사각형 바깥이면 테두리까지의 거리, 안이면 0."""
        x0, y0, x1, y1 = self.rect
        dx = max(x0 - xy[0], 0.0, xy[0] - x1)
        dy = max(y0 - xy[1], 0.0, xy[1] - y1)
        return float(np.hypot(dx, dy))

    def label(self) -> str:
        return f"{self.name}({KINDS.get(self.kind, self.kind)})"


def load_zones(path: str) -> tuple[list[Zone], dict]:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    zones = []
    for i, z in enumerate(doc.get("zones", [])):
        rect = z.get("rect")
        if not rect or len(rect) != 4:
            raise SystemExit(f"존 {i + 1}번의 rect 가 잘못됐다: {rect}")
        x0, y0, x1, y1 = (float(v) for v in rect)
        zones.append(Zone(id=z.get("id") or f"z{i + 1}", name=z.get("name") or f"영역{i + 1}",
                          kind=z.get("kind", "other"), item=z.get("item", ""),
                          rect=(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))))
    if not zones:
        raise SystemExit(f"{path} 에 존이 하나도 없다")
    return zones, {k: v for k, v in doc.items() if k != "zones"}


def zone_at(zones: list[Zone], xy, tol: float = 0.05) -> Zone | None:
    """점이 속한 존. 어느 사각형에도 안 들어가면 tol 안의 가장 가까운 존."""
    if xy is None:
        return None
    inside = [z for z in zones if z.contains(xy)]
    if inside:      # 겹치면 작은 쪽이 더 구체적인 영역이다
        return min(inside, key=lambda z: (z.rect[2] - z.rect[0]) * (z.rect[3] - z.rect[1]))
    near = min(zones, key=lambda z: z.distance(xy))
    return near if near.distance(xy) <= tol else None


def _item_of(zone: Zone | None, fallback: str = "부품") -> str:
    if zone is None:
        return fallback
    return zone.item or fallback


def name_element(el, zones: list[Zone], tol: float = 0.05) -> dict:
    """요소 이름 초안. 확정은 사람이 한다."""
    g = zone_at(zones, el.grasp_xy, tol)
    r = zone_at(zones, el.release_xy, tol)
    has_u = "U" in el.dom_seq
    sup_hold = "H" in el.sup_seq
    notes = []

    if g is None and r is None:
        name, source = None, "unnamed"
        notes.append("집는 위치와 놓는 위치 모두 정의된 존 밖")
    elif has_u and g is not None and g.kind == "tool":
        target = r.name if r else "작업 위치"
        name = f"{josa(_item_of(g, g.name), '으로', '로')} {target} 작업"
        source = "zone"
    elif g is not None and r is not None and g.id == r.id:
        name = f"{josa(g.name, '에서', '에서')} {'작업' if has_u else '취급'}"
        source = "zone"
    elif g is not None and r is not None:
        pair = (g.kind, r.kind)
        item = _item_of(g, f"{g.name} 부품")
        if r.kind == "inspect":
            name = f"{josa(item, '을', '를')} {r.name}에서 검사"
        elif pair == ("part", "jig"):
            name = f"{josa(item, '을', '를')} {r.name}에 조립"
        elif pair == ("part", "output"):
            name = f"{josa(item, '을', '를')} {r.name}에 적재"
        elif pair == ("jig", "output"):
            name = f"완성품을 {r.name}에 배출"
        elif r.kind == "tool":
            name = f"{josa(item, '을', '를')} {r.name}에 반납"
        else:
            name = f"{josa(g.name, '에서', '에서')} {josa(r.name, '으로', '로')} 이동"
        source = "zone"
    elif g is not None:
        name = f"{josa(g.name, '에서', '에서')} 집기"
        source = "partial"
        notes.append("놓는 위치가 정의된 존 밖")
    else:
        name = f"{r.name}에 놓기"
        source = "partial"
        notes.append("집는 위치가 정의된 존 밖")

    if name and sup_hold:
        name += " (좌수 지지)"

    reach = None
    if el.grasp_xy and el.release_xy:
        reach = float(np.hypot(el.release_xy[0] - el.grasp_xy[0],
                               el.release_xy[1] - el.grasp_xy[1]))
        if reach > 0.5:
            notes.append(f"장거리 이동 (화면 대각선의 {reach / 1.414:.0%})")
    return {"name": name, "source": source, "grasp_zone": g.id if g else None,
            "release_zone": r.id if r else None,
            "reach": None if reach is None else round(reach, 3), "notes": notes}


def annotate_elements(elements, zones: list[Zone], tol: float = 0.05) -> dict:
    """요소마다 이름을 붙이고 존 사용 통계를 낸다."""
    named = 0
    zone_use: dict[str, int] = {z.id: 0 for z in zones}
    gaps = []
    for el in elements:
        info = name_element(el, zones, tol)
        el.name = info["name"]
        el.zone_info = info
        if info["source"] == "zone":
            named += 1
        else:
            gaps.append({"element": el.index + 1, "source": info["source"],
                         "grasp_xy": el.grasp_xy, "release_xy": el.release_xy,
                         "notes": info["notes"]})
        for key in ("grasp_zone", "release_zone"):
            if info[key]:
                zone_use[info[key]] += 1
    return {
        "zones": [{"id": z.id, "name": z.name, "kind": z.kind, "item": z.item,
                   "rect": [round(v, 3) for v in z.rect], "touch_count": zone_use[z.id]}
                  for z in zones],
        "named": named,
        "partial": sum(1 for g in gaps if g["source"] == "partial"),
        "unnamed": sum(1 for g in gaps if g["source"] == "unnamed"),
        "total": len(elements),
        "named_rate": round(named / len(elements), 3) if elements else 0.0,
        "unused_zones": [z.name for z in zones if zone_use[z.id] == 0],
        "coverage_gaps": gaps,
    }
