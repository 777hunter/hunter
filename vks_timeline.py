#!/usr/bin/env python3
"""
vks_timeline — Confluence(vks.vatech.com) 페이지의 수정 이력을 기간·시간 간격별로 정리

한 위키 페이지가 특정 기간 동안 어떻게 바뀌어 왔는지를,
'하루 단위(전일)' 또는 'N시간 간격'으로 묶어 Claude가 요약해 줍니다.

흐름:
  1) Confluence REST API로 페이지의 버전(수정) 이력을 가져온다
  2) 지정한 기간(--from ~ --to)으로 거른다
  3) 날짜 또는 N시간 간격으로 버전들을 묶는다
  4) 각 구간에서 '직전 대비 무엇이 바뀌었는지'를 Claude가 요약한다
  5) 타임라인 리포트로 출력(필요하면 파일 저장)

사용 예:
  # 먼저 연결/인증부터 확인 (Claude 호출 없음, 토큰만 있으면 됨)
  python vks_timeline.py --page 123456 --from 2026-06-01 --to 2026-06-17 --list-versions

  # 하루 단위로 변경 내용 요약
  python vks_timeline.py --page 123456 --from 2026-06-01 --to 2026-06-17 --bucket day

  # 6시간 간격으로 요약, 파일로 저장
  python vks_timeline.py --page "https://vks.vatech.com/pages/viewpage.action?pageId=123456" \\
      --from 2026-06-15 --to 2026-06-17 --bucket 6h --save report.md

환경변수:
  VKS_BASE_URL   기본 https://vks.vatech.com
  VKS_TOKEN      Confluence 개인 액세스 토큰(PAT)  ← 필수
  VKS_AUTH       bearer(기본) 또는 basic
  VKS_USER       VKS_AUTH=basic 일 때 사용자 ID
  VKS_INSECURE   사내 인증서 문제로 TLS 검증을 끄려면 1 (권장하지 않음)
  ANTHROPIC_API_KEY   요약(Claude) 사용 시 필수
"""

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, date, time
from html import unescape
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import requests

# ──────────────────────────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────────────────────────

MODEL = "claude-opus-4-8"          # 요약에 쓸 Claude 모델
KST = ZoneInfo("Asia/Seoul")       # 날짜/시간 구간을 한국 시간 기준으로 묶음

# Claude에 한 번에 보내는 본문/디프 길이 상한 (너무 길어지는 것 방지)
MAX_DIFF_CHARS = 12000
MAX_BODY_CHARS = 12000


# ──────────────────────────────────────────────────────────────────────────
# Confluence API 클라이언트
# ──────────────────────────────────────────────────────────────────────────

class Confluence:
    def __init__(self):
        self.base = os.environ.get("VKS_BASE_URL", "https://vks.vatech.com").rstrip("/")
        token = os.environ.get("VKS_TOKEN")
        if not token:
            sys.exit("오류: 환경변수 VKS_TOKEN(Confluence 개인 액세스 토큰)이 필요합니다.")

        self.session = requests.Session()
        auth_mode = os.environ.get("VKS_AUTH", "bearer").lower()
        if auth_mode == "basic":
            user = os.environ.get("VKS_USER")
            if not user:
                sys.exit("오류: VKS_AUTH=basic 이면 VKS_USER(사용자 ID)도 필요합니다.")
            self.session.auth = (user, token)
        else:  # bearer (Confluence Server/DC 개인 액세스 토큰)
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers["Accept"] = "application/json"

        if os.environ.get("VKS_INSECURE") == "1":
            self.session.verify = False
            requests.packages.urllib3.disable_warnings()  # 경고 숨김

    def _get(self, path, **params):
        url = f"{self.base}/rest/api/{path.lstrip('/')}"
        r = self.session.get(url, params=params, timeout=30)
        if r.status_code == 401:
            sys.exit("오류: 인증 실패(401). VKS_TOKEN/VKS_AUTH 설정을 확인하세요.")
        if r.status_code == 404:
            sys.exit(f"오류: 찾을 수 없음(404). 페이지 ID나 주소를 확인하세요.\n  {url}")
        r.raise_for_status()
        return r.json()

    def page_info(self, page_id):
        """페이지 기본 정보(제목, 현재 버전 번호)."""
        data = self._get(f"content/{page_id}", expand="version,space")
        return {
            "title": data.get("title", f"(제목없음 {page_id})"),
            "current_version": data["version"]["number"],
            "space": data.get("space", {}).get("key", ""),
        }

    def list_versions(self, page_id):
        """페이지의 모든 버전 이력을 가져온다(페이지네이션 포함)."""
        versions = []
        start, limit = 0, 100
        while True:
            data = self._get(f"content/{page_id}/version", start=start, limit=limit)
            for v in data.get("results", []):
                versions.append(
                    {
                        "number": v["number"],
                        "when": v["when"],                       # ISO8601 문자열
                        "by": v.get("by", {}).get("displayName", "?"),
                        "message": (v.get("message") or "").strip(),
                        "minor": v.get("minorEdit", False),
                    }
                )
            if data.get("size", 0) < limit:
                break
            start += limit
        return versions

    def version_body_text(self, page_id, number, current_version):
        """특정 버전의 본문을 가져와 순수 텍스트로 변환."""
        if number == current_version:
            data = self._get(f"content/{page_id}", expand="body.storage")
        else:
            # 과거 버전 본문 조회
            data = self._get(
                f"content/{page_id}",
                status="historical",
                version=number,
                expand="body.storage",
            )
        storage = data.get("body", {}).get("storage", {}).get("value", "")
        return html_to_text(storage)


# ──────────────────────────────────────────────────────────────────────────
# 보조 함수
# ──────────────────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br", "li", "tr", "h1", "h2", "h3", "h4", "div"):
            self.parts.append("\n")


def html_to_text(html: str) -> str:
    """Confluence storage(HTML 유사) 본문을 읽기 좋은 텍스트로 변환."""
    parser = _TextExtractor()
    parser.feed(html)
    text = unescape("".join(parser.parts))
    # 빈 줄 정리
    lines = [ln.rstrip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if ln.strip() == "":
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()


def parse_when(s: str) -> datetime:
    """Confluence의 ISO8601 시간 문자열을 KST datetime으로 변환."""
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt.astimezone(KST)


def resolve_page_id(value: str) -> str:
    """페이지 ID 또는 Confluence URL에서 숫자 페이지 ID를 추출."""
    if value.isdigit():
        return value
    m = re.search(r"pageId=(\d+)", value)
    if m:
        return m.group(1)
    m = re.search(r"/pages/(\d+)", value)
    if m:
        return m.group(1)
    sys.exit(
        "오류: 페이지 ID를 알 수 없습니다. 숫자 ID를 쓰거나, 'pageId=' 또는 "
        "'/pages/숫자' 가 포함된 주소를 넣어주세요."
    )


def bucket_key(dt: datetime, bucket: str) -> datetime:
    """버전 시각을 구간의 시작 시각으로 내림(floor)."""
    if bucket == "day":
        return datetime.combine(dt.date(), time.min, tzinfo=KST)
    # "Nh" 형태 (예: 6h)
    hours = int(bucket[:-1])
    floored_hour = (dt.hour // hours) * hours
    return dt.replace(hour=floored_hour, minute=0, second=0, microsecond=0)


def bucket_label(start: datetime, bucket: str) -> str:
    if bucket == "day":
        return start.strftime("%Y-%m-%d (%a)")
    hours = int(bucket[:-1])
    end = start + timedelta(hours=hours)
    return start.strftime("%Y-%m-%d %H:%M") + " ~ " + end.strftime("%H:%M")


# ──────────────────────────────────────────────────────────────────────────
# Claude 요약
# ──────────────────────────────────────────────────────────────────────────

def make_anthropic():
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("오류: 요약을 하려면 ANTHROPIC_API_KEY 가 필요합니다.")
    return anthropic.Anthropic()


def summarize_baseline(client, title, text):
    """기간 시작 시점의 페이지 핵심 내용을 요약."""
    text = text[:MAX_BODY_CHARS]
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system="너는 위키 문서를 한국어로 간결히 요약하는 도우미다.",
        messages=[{
            "role": "user",
            "content": f"다음은 위키 페이지 '{title}'의 기간 시작 시점 내용이다. "
                       f"핵심을 3~5문장으로 요약해줘.\n\n{text}",
        }],
    )
    return next(b.text for b in resp.content if b.type == "text").strip()


def summarize_change(client, title, label, edits, diff_text):
    """한 구간에서 직전 대비 바뀐 내용을 요약."""
    diff_text = diff_text[:MAX_DIFF_CHARS] or "(텍스트 차이가 감지되지 않음 — 서식/표 등 변경일 수 있음)"
    edit_lines = "\n".join(
        f"- {e['when_str']} {e['by']}"
        + (f" : {e['message']}" if e["message"] else "")
        + (" (minor)" if e["minor"] else "")
        for e in edits
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system="너는 위키 문서의 변경 이력을 한국어로 정리하는 도우미다. "
               "주어진 편집 목록과 본문 차이(diff)를 보고, 이 구간에 '무엇이 "
               "추가/수정/삭제되었는지' 핵심만 불릿으로 정리한다. 사소한 오타·서식은 묶어서 짧게.",
        messages=[{
            "role": "user",
            "content": f"위키 페이지: {title}\n구간: {label}\n\n"
                       f"[이 구간의 편집 기록]\n{edit_lines}\n\n"
                       f"[직전 구간 대비 본문 차이(unified diff)]\n{diff_text}",
        }],
    )
    return next(b.text for b in resp.content if b.type == "text").strip()


# ──────────────────────────────────────────────────────────────────────────
# 메인 로직
# ──────────────────────────────────────────────────────────────────────────

def run(args):
    page_id = resolve_page_id(args.page)
    cf = Confluence()
    info = cf.page_info(page_id)

    # 기간 경계 (KST, --to 는 그 날 끝까지 포함)
    start_dt = datetime.combine(date.fromisoformat(args.date_from), time.min, tzinfo=KST)
    end_dt = datetime.combine(date.fromisoformat(args.date_to), time.max, tzinfo=KST)

    all_versions = cf.list_versions(page_id)
    for v in all_versions:
        v["dt"] = parse_when(v["when"])
        v["when_str"] = v["dt"].strftime("%Y-%m-%d %H:%M")
    in_range = sorted(
        [v for v in all_versions if start_dt <= v["dt"] <= end_dt],
        key=lambda v: v["dt"],
    )

    print(f"# {info['title']}  (pageId={page_id}, space={info['space']})")
    print(f"기간: {args.date_from} ~ {args.date_to} (KST)")
    print(f"전체 버전 {len(all_versions)}개 중 기간 내 편집 {len(in_range)}건\n")

    if not in_range:
        print("해당 기간에 수정된 내역이 없습니다.")
        return

    # --list-versions: Claude 없이 버전 목록만 확인 (연결/인증 점검용)
    if args.list_versions:
        for v in in_range:
            tag = " (minor)" if v["minor"] else ""
            msg = f" — {v['message']}" if v["message"] else ""
            print(f"  v{v['number']:>4}  {v['when_str']}  {v['by']}{tag}{msg}")
        return

    # 구간별로 버전 묶기
    buckets: dict[datetime, list[dict]] = {}
    for v in in_range:
        buckets.setdefault(bucket_key(v["dt"], args.bucket), []).append(v)
    ordered_keys = sorted(buckets)

    client = make_anthropic()

    # 기간 시작 직전 상태를 기준선으로 잡기 위해, 각 구간의 '마지막 버전' 본문을 사용해
    # 직전 구간과 비교한다. 첫 구간은 본문 자체를 요약.
    import difflib

    report_lines = [
        f"# {info['title']} — 변경 타임라인",
        f"- 페이지: {cf.base}/pages/viewpage.action?pageId={page_id}",
        f"- 기간: {args.date_from} ~ {args.date_to} (KST), 묶음 단위: {args.bucket}",
        "",
    ]

    prev_text = None
    for key in ordered_keys:
        edits = buckets[key]
        label = bucket_label(key, args.bucket)
        last_v = edits[-1]  # 구간 끝 상태
        cur_text = cf.version_body_text(page_id, last_v["number"], info["current_version"])

        print(f"\n## {label}  (편집 {len(edits)}건)")
        report_lines.append(f"## {label}  (편집 {len(edits)}건)")

        if prev_text is None:
            summary = summarize_baseline(client, info["title"], cur_text)
            block = "**[시작 시점 내용 요약]**\n" + summary
        else:
            diff = "\n".join(
                difflib.unified_diff(
                    prev_text.splitlines(),
                    cur_text.splitlines(),
                    lineterm="",
                    n=2,
                )
            )
            summary = summarize_change(client, info["title"], label, edits, diff)
            block = summary

        print(block)
        report_lines.append(block)
        report_lines.append("")
        prev_text = cur_text

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        print(f"\n리포트를 '{args.save}' 에 저장했습니다.")


def main():
    p = argparse.ArgumentParser(
        description="Confluence(vks) 페이지의 수정 이력을 기간·시간 간격별로 정리"
    )
    p.add_argument("--page", required=True, help="페이지 ID 또는 Confluence URL")
    p.add_argument("--from", dest="date_from", required=True, help="시작일 YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", required=True, help="종료일 YYYY-MM-DD (그 날 포함)")
    p.add_argument(
        "--bucket",
        default="day",
        help="묶음 단위: 'day'(전일) 또는 'Nh'(예: 6h, 12h). 기본 day",
    )
    p.add_argument(
        "--list-versions",
        action="store_true",
        help="요약 없이 기간 내 버전 목록만 출력 (연결/인증 점검용)",
    )
    p.add_argument("--save", help="리포트를 저장할 파일 경로(.md)")
    args = p.parse_args()

    # --bucket 형식 검증
    if args.bucket != "day" and not re.fullmatch(r"\d+h", args.bucket):
        p.error("--bucket 은 'day' 또는 'Nh'(예: 6h) 형식이어야 합니다.")

    run(args)


if __name__ == "__main__":
    main()
