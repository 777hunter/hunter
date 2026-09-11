"""요소별 대표 사진 선정과 주석.

아무 프레임이나 뽑으면 손이 흐릿하거나 부품이 손에 가려 아무것도 안 보인다.
좋은 사진에는 규칙이 있다. 쥐기가 막 끝난 순간, 위치가 확정된 순간, 사용 중.
거기에 흔들림과 검출 신뢰도로 거른다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from hand_core import HAND_CONNECTIONS

MOMENT_KO = {
    "grasp_end": "쥐기 완료",
    "position_end": "위치 확정",
    "release_start": "놓기 직전",
    "use_mid": "사용 중",
    "mid": "요소 중간",
}
# 작업표준서에 붙였을 때 정보량이 큰 순간일수록 가중치가 높다
MOMENT_WEIGHT = {"grasp_end": 1.0, "position_end": 0.95, "use_mid": 0.9,
                 "release_start": 0.85, "mid": 0.5}

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
]


def find_font(explicit: str | None = None) -> str | None:
    for path in ([explicit] if explicit else []) + FONT_CANDIDATES:
        if path and os.path.exists(path):
            return path
    return None


def _font(path: str | None, size: int):
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


@dataclass
class Shot:
    position: int
    element: int
    kind: str
    time_s: float
    frame: int
    score: float
    sharpness: float
    hand_score: float
    hand_px: np.ndarray | None = None
    path: str = ""
    annot_path: str = ""

    def to_dict(self) -> dict:
        return {"position": self.position, "element": self.element, "kind": self.kind,
                "kind_ko": MOMENT_KO.get(self.kind, self.kind),
                "time_s": round(self.time_s, 2), "frame": self.frame,
                "score": round(self.score, 3), "sharpness": round(self.sharpness, 1),
                "hand_score": round(self.hand_score, 3),
                "file": os.path.basename(self.path),
                "annotated": os.path.basename(self.annot_path)}


def sharpness(img: np.ndarray, box=None) -> float:
    """라플라시안 분산. 손 주변만 본다. 배경이 흐려도 손이 선명하면 쓸 수 있다."""
    roi = img
    if box is not None:
        x0, y0, x1, y1 = box
        roi = img[max(0, y0):y1, max(0, x0):x1]
        if roi.size == 0:
            roi = img
    grey = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def candidate_requests(elements: list[dict], fps: float, window_s: float, samples: int):
    """요소마다 결정적 순간 주변의 프레임 번호를 모은다."""
    reqs = []
    for el in elements:
        for kind, t in (el.get("moments") or {}).items():
            half = window_s / 2
            for tt in np.linspace(max(t - half, el["start_s"]),
                                  min(t + half, el["end_s"]), samples):
                reqs.append({"element": el["index"], "position": el["position"],
                             "kind": kind, "time_s": float(tt),
                             "frame": int(round(float(tt) * fps))})
    return reqs


def read_frames(video: str, frame_ids: set[int]) -> dict[int, np.ndarray]:
    """필요한 프레임만 순차 스캔으로 읽는다. 무작위 탐색보다 빠르고 안정적이다."""
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"영상을 열 수 없다: {video}")
    wanted = sorted(frame_ids)
    out, idx, k = {}, -1, 0
    while k < len(wanted):
        ok = cap.grab()
        if not ok:
            break
        idx += 1
        if idx == wanted[k]:
            ok, img = cap.retrieve()
            if ok:
                out[idx] = img
            while k < len(wanted) and wanted[k] <= idx:
                k += 1
    cap.release()
    return out


def score_requests(reqs, frames_by_id, landmarker, side_hint: str | None = None):
    """각 후보 프레임을 채점한다. 손이 안 잡히면 탈락."""
    import mediapipe as mp
    scored = []
    for r in reqs:
        img = frames_by_id.get(r["frame"])
        if img is None:
            continue
        h, w = img.shape[:2]
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        if not res.hand_landmarks:
            continue
        best_i, best_score = 0, -1.0
        for i, handed in enumerate(res.handedness):
            sc = float(handed[0].score)
            if side_hint and handed[0].category_name == side_hint:
                sc += 0.5
            if sc > best_score:
                best_i, best_score = i, sc
        lm = res.hand_landmarks[best_i]
        px = np.array([[p.x * w, p.y * h] for p in lm], dtype=np.float32)
        pad = 0.35 * float(np.ptp(px[:, 0]) + np.ptp(px[:, 1])) / 2
        box = (int(px[:, 0].min() - pad), int(px[:, 1].min() - pad),
               int(px[:, 0].max() + pad), int(px[:, 1].max() + pad))
        scored.append({**r, "sharpness": sharpness(img, box), "hand_px": px,
                       "hand_score": float(res.handedness[best_i][0].score)})
    return scored


def pick_shots(scored, per_element: int = 3, min_gap_s: float = 0.25) -> list[Shot]:
    """요소마다 상위 N장. 서로 다른 순간에서 고르고, 너무 가까운 프레임은 뺀다."""
    by_el: dict[int, list] = {}
    for s in scored:
        by_el.setdefault(s["element"], []).append(s)

    shots: list[Shot] = []
    for el, cands in by_el.items():
        sharp = [c["sharpness"] for c in cands]
        lo, hi = min(sharp), max(sharp)
        rng = (hi - lo) or 1.0
        for c in cands:
            c["score"] = (0.6 * (c["sharpness"] - lo) / rng
                          + 0.2 * c["hand_score"]
                          + 0.2 * MOMENT_WEIGHT.get(c["kind"], 0.5))
        cands.sort(key=lambda c: -c["score"])
        chosen, kinds = [], set()
        for c in cands:
            if any(abs(c["time_s"] - x["time_s"]) < min_gap_s for x in chosen):
                continue
            # 같은 순간에서 두 장 뽑느니 다른 순간 한 장이 낫다
            if c["kind"] in kinds and len(kinds) < len(
                    {x["kind"] for x in cands}) and len(chosen) < per_element:
                continue
            chosen.append(c)
            kinds.add(c["kind"])
            if len(chosen) >= per_element:
                break
        for c in chosen:
            shots.append(Shot(position=c["position"], element=c["element"], kind=c["kind"],
                              time_s=c["time_s"], frame=c["frame"], score=c["score"],
                              sharpness=c["sharpness"], hand_score=c["hand_score"],
                              hand_px=c["hand_px"]))
    return shots


def _pil_text(img_bgr, boxes):
    """한글은 OpenCV 로 못 찍는다. PIL 로 얹고 돌려준다."""
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil, "RGBA")
    for box in boxes:
        if box.get("bg"):
            d.rectangle(box["bg"], fill=box.get("bg_fill", (18, 22, 20, 205)))
        d.text(box["xy"], box["text"], font=box["font"], fill=box.get("fill", (255, 255, 255)))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def annotate(img, shot: Shot, element: dict, zones, font_path: str | None):
    """존 사각형, 손 골격, 캡션을 얹는다."""
    out = img.copy()
    h, w = out.shape[:2]
    zone_by_id = {z.id: z for z in (zones or [])}
    info = element.get("zone_info") or element
    highlight = [(info.get("grasp_zone"), (91, 73, 209), "집는 곳"),
                 (info.get("release_zone"), (143, 157, 42), "놓는 곳")]
    overlay = out.copy()
    for zid, colour, _ in highlight:
        z = zone_by_id.get(zid)
        if z is None:
            continue
        x0, y0, x1, y1 = (int(z.rect[0] * w), int(z.rect[1] * h),
                          int(z.rect[2] * w), int(z.rect[3] * h))
        cv2.rectangle(overlay, (x0, y0), (x1, y1), colour, -1)
        cv2.rectangle(out, (x0, y0), (x1, y1), colour, 2)
    out = cv2.addWeighted(overlay, 0.14, out, 0.86, 0)

    if shot.hand_px is not None:
        p = shot.hand_px.astype(int)
        for a, b in HAND_CONNECTIONS:
            cv2.line(out, tuple(p[a]), tuple(p[b]), (20, 20, 20), 4, cv2.LINE_AA)
            cv2.line(out, tuple(p[a]), tuple(p[b]), (255, 255, 255), 2, cv2.LINE_AA)
        for x, y in p:
            cv2.circle(out, (x, y), 3, (60, 220, 250), -1, cv2.LINE_AA)

    bar = max(44, int(h * 0.09))
    big = _font(font_path, max(16, int(bar * 0.42)))
    small = _font(font_path, max(12, int(bar * 0.28)))
    name = element.get("name") or element.get("signature", "")
    title = f"{shot.position + 1}. {name}"
    sub = (f'{MOMENT_KO.get(shot.kind, shot.kind)} · {shot.time_s:.2f}초 · '
           f'요소 {element["dur_s"]:.2f}초')
    boxes = [
        {"bg": [0, h - bar, w, h], "xy": (14, h - bar + bar * 0.12), "text": title, "font": big},
        {"xy": (14, h - bar + bar * 0.58), "text": sub, "font": small, "fill": (186, 196, 192)},
    ]
    for zid, colour, label in highlight:
        z = zone_by_id.get(zid)
        if z is None:
            continue
        x0, y0 = int(z.rect[0] * w), int(z.rect[1] * h)
        tag = f"{label}: {z.name}"
        tw = int(small.getlength(tag)) + 14 if hasattr(small, "getlength") else len(tag) * 9
        boxes.append({"bg": [x0, max(y0 - int(bar * 0.42), 0), x0 + tw,
                             max(y0 - int(bar * 0.42), 0) + int(bar * 0.42)],
                      "bg_fill": (colour[2], colour[1], colour[0], 235),
                      "xy": (x0 + 7, max(y0 - int(bar * 0.42), 0) + int(bar * 0.06)),
                      "text": tag, "font": small})
    return _pil_text(out, boxes)


def contact_sheet(entries, path: str, font_path: str | None, cols: int = 3, cell_w: int = 460):
    """요소별 대표 사진 한 장으로. 검수할 때 이것만 보면 된다."""
    if not entries:
        return None
    imgs = []
    for e in entries:
        img = cv2.imread(e["annot"])
        if img is None:
            continue
        scale = cell_w / img.shape[1]
        imgs.append(cv2.resize(img, (cell_w, int(img.shape[0] * scale))))
    if not imgs:
        return None
    cell_h = max(i.shape[0] for i in imgs)
    rows = (len(imgs) + cols - 1) // cols
    pad, head = 10, 56
    sheet = np.full((head + rows * (cell_h + pad) + pad, cols * (cell_w + pad) + pad, 3),
                    244, np.uint8)
    for i, img in enumerate(imgs):
        r, c = divmod(i, cols)
        y, x = head + r * (cell_h + pad), pad + c * (cell_w + pad)
        sheet[y:y + img.shape[0], x:x + cell_w] = img
    title = _font(font_path, 24)
    sheet = _pil_text(sheet, [{"xy": (pad + 4, 14),
                               "text": f"작업요소 대표 사진 {len(imgs)}컷",
                               "font": title, "fill": (24, 30, 28)}])
    cv2.imwrite(path, sheet)
    return path
