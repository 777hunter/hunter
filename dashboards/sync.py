#!/usr/bin/env python3
"""대시보드 총괄 허브 자동 편입 스크립트.

발행된 허브 HTML 안에 들어 있는 레지스트리(<script id="state">)를 읽어,
Artifact 목록에서 뽑은 대시보드 목록과 대조한 뒤

  * 목록에 없던 대시보드를 status="new" / cat="unsorted" 로 새로 편입하고
  * 이미 있는 항목의 최종 수정일(과 제목·아이콘)을 갱신하고
  * 관리자가 "목록에서 제거"한 항목(tombstones)은 다시 넣지 않고
  * 숨김·설명·분류 등 사람이 손댄 값은 절대 건드리지 않는다.

사용법:
    python3 sync.py --html hub.html --list artifacts.json
    python3 sync.py --html downloaded.html --list artifacts.json --out hub.html

artifacts.json 은 Artifact 목록에서 만든 배열:
    [{"id": "...", "title": "...", "url": "...", "icon": "🌡️", "updated": "2026-08-26"}]
"""

import argparse
import datetime
import json
import re
import sys

STATE_RE = re.compile(
    r'(<script id="state" type="application/json">)(.*?)(</script>)', re.S
)
UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I
)

DEFAULT_ICON = "▤"  # ▤


def today() -> str:
    return datetime.date.today().isoformat()


def read_state(html: str) -> dict:
    m = STATE_RE.search(html)
    if not m:
        sys.exit("오류: <script id=\"state\"> 블록을 찾지 못했습니다.")
    return json.loads(m.group(2))


def write_state(html: str, state: dict) -> str:
    blob = json.dumps(state, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    return STATE_RE.sub(lambda m: m.group(1) + blob + m.group(3), html, count=1)


def norm_id(entry: dict) -> str:
    raw = entry.get("id") or ""
    if not raw:
        m = UUID_RE.search(entry.get("url", ""))
        raw = m.group(1) if m else ""
    return raw.lower()


def merge(state: dict, incoming: list) -> list:
    items = state.setdefault("items", [])
    tombs = {t.lower() for t in state.setdefault("tombstones", [])}
    self_id = (state.get("selfId") or "").lower()
    by_id = {it["id"].lower(): it for it in items}
    log = []

    for entry in incoming:
        aid = norm_id(entry)
        if not aid or aid == self_id:
            continue
        if aid in tombs:
            log.append("제외됨(무시): %s" % entry.get("title", aid))
            continue

        item = by_id.get(aid)
        if item is None:
            items.append(
                {
                    "id": aid,
                    "url": entry.get("url", ""),
                    "title": entry.get("title", "제목 없음"),
                    "icon": entry.get("icon") or DEFAULT_ICON,
                    "cat": "unsorted",
                    "desc": "",
                    "tags": [],
                    "updated": entry.get("updated", today()),
                    "added": today(),
                    "hidden": False,
                    "pinned": False,
                    "status": "new",
                }
            )
            log.append("신규 편입: %s" % entry.get("title", aid))
            continue

        changed = []
        upd = entry.get("updated")
        if upd and upd != item.get("updated"):
            item["updated"] = upd
            changed.append("최종 수정일")
        title = entry.get("title")
        if title and not item.get("titleLocked") and title != item.get("title"):
            item["title"] = title
            changed.append("제목")
        icon = entry.get("icon")
        if icon and item.get("icon", DEFAULT_ICON) == DEFAULT_ICON and icon != DEFAULT_ICON:
            item["icon"] = icon
            changed.append("아이콘")
        url = entry.get("url")
        if url and url != item.get("url"):
            item["url"] = url
            changed.append("주소")
        if changed:
            log.append("갱신(%s): %s" % (", ".join(changed), item["title"]))

    state["syncedAt"] = today()
    return log


def main() -> None:
    ap = argparse.ArgumentParser(description="허브 레지스트리에 새 대시보드를 자동 편입합니다.")
    ap.add_argument("--html", required=True, help="허브 HTML (발행본 또는 저장소의 hub.html)")
    ap.add_argument("--list", required=True, help="Artifact 목록 JSON 파일")
    ap.add_argument("--out", help="결과 HTML 경로 (기본: --html 을 덮어씀)")
    ap.add_argument("--registry", help="같이 갱신할 registry.json 경로")
    ap.add_argument("--self-id", help="허브 자신의 artifact id (목록에서 제외)")
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 변경 내역만 출력")
    args = ap.parse_args()

    html = open(args.html, encoding="utf-8").read()
    incoming = json.load(open(args.list, encoding="utf-8"))
    if isinstance(incoming, dict):
        incoming = incoming.get("items", [])

    state = read_state(html)
    if args.self_id:
        state["selfId"] = args.self_id.lower()

    log = merge(state, incoming)

    if args.dry_run:
        print("\n".join(log) if log else "변경 없음")
        return

    out = args.out or args.html
    open(out, "w", encoding="utf-8").write(write_state(html, state))
    if args.registry:
        with open(args.registry, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    print("\n".join(log) if log else "변경 없음")
    print("→ %s (등록 %d건, 제외 %d건)" % (out, len(state["items"]), len(state["tombstones"])))


if __name__ == "__main__":
    main()
