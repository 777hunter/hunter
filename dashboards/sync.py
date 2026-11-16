#!/usr/bin/env python3
"""대시보드 총괄 허브 자동 편입 스크립트.

발행된 허브 HTML 안에 들어 있는 레지스트리(<script id="state">)를 읽어,
Artifact 목록에서 뽑은 대시보드 목록과 대조한 뒤

  * 목록에 없던 대시보드를 status="new" / cat="unsorted" 로 새로 편입하고
  * 이미 있는 항목의 최종 수정일(과 제목·아이콘)을 갱신하고
  * 관리자가 "목록에서 제거"한 항목(tombstones)은 다시 넣지 않고
  * 숨김·설명·분류 등 사람이 손댄 값은 절대 건드리지 않는다.

데이터와 코드의 출처가 다르다:
  * 레지스트리(데이터)는 --html 로 받은 발행본이 기준이다. 화면에서 저장한 값이 여기 있다.
  * 앱 코드(<style id="appcss">, <script id="app">)는 저장소의 hub.html(--out)이 기준이다.
    발행본의 코드가 저장소와 다르면 저장소 코드에 발행본 데이터를 얹고 "앱 코드 갱신"으로
    보고한다. 그래야 저장소에서 고친 코드가 다음 동기화 때 옛 코드로 되돌아가지 않는다.

항목 상태(status):
  new   : 자동으로 들어왔고 사람이 아직 안 봄  ← 이 스크립트가 편입할 때, 즐겨찾기 가져오기
  ready : 사람이 확인함                          ← 허브 화면의 편집 확인·숨김·수동 추가
  tombstones 에 있는 id 는 items 에 없어야 하고, 이 스크립트는 다시 넣지 않는다.

사용법:
    python3 sync.py --html hub.html --list artifacts.json
    python3 sync.py --html downloaded.html --list artifacts.json --out hub.html
    python3 sync.py --html downloaded.html --list artifacts.json --out hub.html --json
    python3 sync.py --check --html hub.html          # 레지스트리 불변식만 검사 (문제 있으면 종료 코드 1)

--json 은 사람이 읽는 줄 대신 아래 한 줄 JSON 을 출력한다(자동화·에이전트용):
    {"changed": bool, "added": [...], "updated": [...], "ignored": [...],
     "code_updated": bool, "problems": [...], "log": [...], "out": "...", "items": N, "tombstones": N}

artifacts.json 은 Artifact 목록에서 만든 배열:
    [{"id": "...", "title": "...", "url": "...", "icon": "🌡️", "updated": "2026-08-26"}]
"""

import argparse
import datetime
import json
import os
import re
import sys

STATE_RE = re.compile(
    r'(<script id="state" type="application/json">)(.*?)(</script>)', re.S
)
UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I
)

APP_PARTS = [
    re.compile(r'<style id="appcss">(.*?)</style>', re.S),
    re.compile(r'<script id="app">(.*?)</script>', re.S),
]

DEFAULT_ICON = "▤"  # ▤
ITEM_STATUSES = ("new", "ready")


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


def app_code(html: str):
    """앱 코드(CSS·JS) 부분만 뽑는다. 발행본의 문서 껍데기 모양과 상관없이 비교하기 위함."""
    parts = []
    for rx in APP_PARTS:
        m = rx.search(html)
        parts.append(m.group(1).strip() if m else None)
    return tuple(parts)


def check(state: dict) -> list:
    """레지스트리 불변식 위반을 사람이 읽는 문장 목록으로 돌려준다."""
    problems = []
    cats = {c.get("id") for c in state.get("categories", [])}
    tombs = {str(t).lower() for t in state.get("tombstones", [])}
    seen = set()
    for it in state.get("items", []):
        iid = str(it.get("id", "")).lower()
        name = it.get("title") or iid or "(id 없음)"
        if not iid:
            problems.append("id 없음: %s" % name)
        elif iid in seen:
            problems.append("id 중복: %s" % iid)
        seen.add(iid)
        if iid in tombs:
            problems.append("제외 목록(tombstones)에 있는데 등록돼 있음: %s" % name)
        if it.get("status") not in ITEM_STATUSES:
            problems.append("알 수 없는 상태 %r: %s" % (it.get("status"), name))
        if cats and it.get("cat") not in cats:
            problems.append("알 수 없는 분류 %r: %s" % (it.get("cat"), name))
        for key in ("hidden", "pinned"):
            if not isinstance(it.get(key, False), bool):
                problems.append("%s 값이 참/거짓이 아님: %s" % (key, name))
        if not it.get("url"):
            problems.append("주소 없음: %s" % name)
    return problems


def norm_id(entry: dict) -> str:
    raw = entry.get("id") or ""
    if not raw:
        m = UUID_RE.search(entry.get("url", ""))
        raw = m.group(1) if m else ""
    return raw.lower()


# 이미 등록된 항목에서 동기화가 바꿔도 되는 필드와 그 조건. 여기 없는 필드
# (설명·분류·숨김·고정·태그·상태)는 사람이 정하는 값이라 절대 바꾸지 않는다.
UPDATE_RULES = (
    ("updated", "최종 수정일", lambda item, new: True),
    ("title", "제목", lambda item, new: not item.get("titleLocked")),         # 사람이 고친 제목은 유지
    ("icon", "아이콘", lambda item, new: item.get("icon", DEFAULT_ICON) == DEFAULT_ICON),  # 기본 아이콘일 때만
    ("url", "주소", lambda item, new: True),
)


def new_item(aid: str, entry: dict) -> dict:
    return {
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


def merge(state: dict, incoming: list) -> dict:
    items = state.setdefault("items", [])
    tombs = {t.lower() for t in state.setdefault("tombstones", [])}
    self_id = (state.get("selfId") or "").lower()
    by_id = {it["id"].lower(): it for it in items}
    log = []
    result = {"added": [], "updated": [], "ignored": []}

    for entry in incoming:
        aid = norm_id(entry)
        if not aid or aid == self_id:
            continue
        if aid in tombs:
            log.append("제외됨(무시): %s" % entry.get("title", aid))
            result["ignored"].append(aid)
            continue

        item = by_id.get(aid)
        if item is None:
            items.append(new_item(aid, entry))
            by_id[aid] = items[-1]
            log.append("신규 편입: %s" % entry.get("title", aid))
            result["added"].append(aid)
            continue

        changed = []
        for key, label, allowed in UPDATE_RULES:
            new = entry.get(key)
            if new and new != item.get(key) and allowed(item, new):
                item[key] = new
                changed.append(label)
        if changed:
            log.append("갱신(%s): %s" % (", ".join(changed), item["title"]))
            result["updated"].append(aid)

    state["syncedAt"] = today()
    result["log"] = log
    return result


def sync(html: str, incoming: list, repo_html: str | None = None, self_id: str | None = None,
         repo_label: str = "저장소") -> tuple:
    """파일을 읽고 쓰지 않는 핵심 계산. (결과 HTML, 레지스트리, 요약) 을 돌려준다.

    html      : 발행본. 데이터(레지스트리)의 기준
    repo_html : 저장소의 hub.html. 있으면 화면 코드의 기준
    """
    state = read_state(html)
    if self_id:
        state["selfId"] = self_id.lower()
    result = merge(state, incoming)
    log = result["log"]

    shell, code_updated = html, False
    if repo_html is not None and STATE_RE.search(repo_html) and all(app_code(repo_html)):
        if app_code(repo_html) != app_code(html):
            code_updated = True
            log.append("앱 코드 갱신: 발행본의 화면 코드가 %s와 달라 %s 코드로 맞춤" % (repo_label, repo_label))
        shell = repo_html

    summary = {
        "changed": bool(result["added"] or result["updated"] or code_updated),
        "added": result["added"],
        "updated": result["updated"],
        "ignored": result["ignored"],
        "code_updated": code_updated,
        "problems": check(state),
        "log": log,
        "items": len(state["items"]),
        "tombstones": len(state["tombstones"]),
    }
    return write_state(shell, state), state, summary


def report(summary: dict) -> str:
    """사람이 읽는 출력. "변경 없음" 문구는 주간 루틴이 그대로 읽으므로 바꾸지 않는다.
    제외됨(무시) 줄만 있으면 바뀐 것이 없으므로 역시 "변경 없음"."""
    return "\n".join(summary["log"]) if summary["changed"] else "변경 없음"


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main() -> None:
    ap = argparse.ArgumentParser(description="허브 레지스트리에 새 대시보드를 자동 편입합니다.")
    ap.add_argument("--html", required=True, help="허브 HTML (발행본 또는 저장소의 hub.html)")
    ap.add_argument("--list", help="Artifact 목록 JSON 파일 (--check 가 아니면 필수)")
    ap.add_argument("--out", help="결과 HTML 경로 (기본: --html 을 덮어씀)")
    ap.add_argument("--registry", help="같이 갱신할 registry.json 경로")
    ap.add_argument("--self-id", help="허브 자신의 artifact id (목록에서 제외)")
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 변경 내역만 출력")
    ap.add_argument("--json", action="store_true", help="결과를 한 줄 JSON 으로 출력 (자동화용)")
    ap.add_argument("--check", action="store_true",
                    help="--html 의 레지스트리 불변식만 검사. 문제가 있으면 종료 코드 1")
    args = ap.parse_args()

    html = read(args.html)

    if args.check:
        problems = check(read_state(html))
        if args.json:
            print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False))
        else:
            print("\n".join(problems) if problems else "문제 없음")
        sys.exit(1 if problems else 0)

    if not args.list:
        ap.error("--list 가 필요합니다 (--check 만 쓸 때는 빼도 됩니다)")
    incoming = json.loads(read(args.list))
    if isinstance(incoming, dict):
        incoming = incoming.get("items", [])

    # 앱 코드는 저장소(--out) 쪽이 기준. 발행본과 다르면 저장소 코드에 데이터를 얹는다.
    out = args.out or args.html
    repo_html = read(out) if out != args.html and os.path.exists(out) else None
    out_html, state, summary = sync(html, incoming, repo_html, args.self_id, "저장소(%s)" % out)
    summary["out"] = None if args.dry_run else out

    for p in summary["problems"]:
        print("경고: " + p, file=sys.stderr)

    if not args.dry_run:
        write(out, out_html)
        if args.registry:
            write(args.registry, json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
        return
    print(report(summary))
    if not args.dry_run:
        print("→ %s (등록 %d건, 제외 %d건)" % (out, len(state["items"]), len(state["tombstones"])))


if __name__ == "__main__":
    main()
