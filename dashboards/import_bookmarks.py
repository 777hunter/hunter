#!/usr/bin/env python3
"""브라우저 즐겨찾기 내보내기 파일을 허브 레지스트리로 가져옵니다.

크롬/엣지/웨일의 "즐겨찾기 관리 → 내보내기"가 만드는 HTML(넷스케이프 형식)을 읽어
허브(<script id="state">)에 없는 항목만 새로 편입합니다.

  * 이미 있는 항목은 주소(또는 아티팩트 id)로 알아보고 건드리지 않습니다.
  * "목록에서 제거"한 항목(tombstones)은 다시 넣지 않습니다.
  * claude 아티팩트 주소면 아티팩트 id를 그대로 써서, 주간 자동 동기화와 짝이 맞습니다.
    그 외 주소(사내 시스템 등)는 bm-<해시> id를 받아 동기화가 건드리지 않습니다.
  * 즐겨찾기 폴더 이름은 태그로 남겨 나중에 분류하기 쉽게 합니다.

사용법:
    python3 import_bookmarks.py --html hub.html --bookmarks bookmarks.html --dry-run
    python3 import_bookmarks.py --html hub.html --bookmarks bookmarks.html \
        --folder 대시보드 --out hub.html --registry registry.json
"""

import argparse
import datetime
import hashlib
import html as htmllib
import json
import re
import sys

STATE_RE = re.compile(
    r'(<script id="state" type="application/json">)(.*?)(</script>)', re.S
)
UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I
)
# <DT><H3 ...>폴더</H3>  /  <DT><A HREF="...">제목</A>  /  </DL>
TOKEN_RE = re.compile(
    r'<H3[^>]*>(?P<folder>.*?)</H3>|<A\s+[^>]*HREF="(?P<href>[^"]*)"[^>]*>(?P<title>.*?)</A>|(?P<close></DL>)',
    re.I | re.S,
)

DEFAULT_ICON = "▤"


def today() -> str:
    return datetime.date.today().isoformat()


def clean(raw: str) -> str:
    return htmllib.unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def parse_bookmarks(text: str) -> list:
    """[{title, url, folder}] 순서대로 반환."""
    stack, out = [], []
    for m in TOKEN_RE.finditer(text):
        if m.group("folder") is not None:
            stack.append(clean(m.group("folder")))
        elif m.group("close") is not None:
            if stack:
                stack.pop()
        else:
            url = htmllib.unescape(m.group("href") or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                continue  # javascript:, place:, 파일 북마크는 건너뜀
            out.append(
                {
                    "title": clean(m.group("title")) or url,
                    "url": url,
                    "folder": stack[-1] if stack else "",
                }
            )
    return out


def entry_id(url: str) -> str:
    m = UUID_RE.search(url)
    if m:
        return m.group(1).lower()
    return "bm-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def merge(state: dict, marks: list, folder: str | None) -> list:
    items = state.setdefault("items", [])
    tombs = {t.lower() for t in state.setdefault("tombstones", [])}
    self_id = (state.get("selfId") or "").lower()
    known_ids = {it["id"].lower() for it in items}
    known_urls = {it.get("url", "").rstrip("/") for it in items}
    log = []

    for mark in marks:
        if folder and mark["folder"] != folder:
            continue
        mid = entry_id(mark["url"])
        if mid == self_id or mid in tombs:
            continue
        if mid in known_ids or mark["url"].rstrip("/") in known_urls:
            log.append("이미 등록됨(건너뜀): %s" % mark["title"])
            continue

        items.append(
            {
                "id": mid,
                "url": mark["url"],
                "title": mark["title"],
                "icon": DEFAULT_ICON,
                "cat": "unsorted",
                "desc": "",
                "tags": [mark["folder"]] if mark["folder"] else [],
                "updated": today(),
                "added": today(),
                "hidden": False,
                "pinned": False,
                "status": "new",
                "titleLocked": True,
            }
        )
        known_ids.add(mid)
        known_urls.add(mark["url"].rstrip("/"))
        log.append("신규 편입: %s (%s)" % (mark["title"], mark["folder"] or "폴더 없음"))

    state["syncedAt"] = today()
    return log


def main() -> None:
    ap = argparse.ArgumentParser(description="즐겨찾기 내보내기 파일을 허브에 가져옵니다.")
    ap.add_argument("--html", required=True, help="허브 HTML")
    ap.add_argument("--bookmarks", required=True, help="브라우저 즐겨찾기 내보내기 HTML")
    ap.add_argument("--folder", help="이 폴더 안의 항목만 가져오기")
    ap.add_argument("--out", help="결과 HTML 경로 (기본: --html 을 덮어씀)")
    ap.add_argument("--registry", help="같이 갱신할 registry.json 경로")
    ap.add_argument("--list-folders", action="store_true", help="폴더 목록만 출력")
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 변경 내역만 출력")
    args = ap.parse_args()

    marks = parse_bookmarks(open(args.bookmarks, encoding="utf-8", errors="replace").read())

    if args.list_folders:
        seen = {}
        for mark in marks:
            seen[mark["folder"]] = seen.get(mark["folder"], 0) + 1
        for name, n in sorted(seen.items(), key=lambda kv: -kv[1]):
            print("%4d건  %s" % (n, name or "(폴더 없음)"))
        return

    html_text = open(args.html, encoding="utf-8").read()
    m = STATE_RE.search(html_text)
    if not m:
        sys.exit('오류: <script id="state"> 블록을 찾지 못했습니다.')
    state = json.loads(m.group(2))

    log = merge(state, marks, args.folder)
    print("\n".join(log) if log else "가져올 항목이 없습니다")

    if args.dry_run:
        return

    blob = json.dumps(state, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    out = args.out or args.html
    open(out, "w", encoding="utf-8").write(
        STATE_RE.sub(lambda x: x.group(1) + blob + x.group(3), html_text, count=1)
    )
    if args.registry:
        with open(args.registry, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    print("→ %s (등록 %d건)" % (out, len(state["items"])))


if __name__ == "__main__":
    main()
