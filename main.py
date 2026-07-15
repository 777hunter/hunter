#!/usr/bin/env python3
"""뉴스 카드 생성 & 카카오톡 자동 송출 CLI.

사용 예)
  python main.py                      # 오늘 날짜 카드 생성(HTML) + 카카오 전송 시도
  python main.py --date 2026-07-15    # 특정 날짜
  python main.py --no-send            # 카드만 생성(전송 안 함)
  python main.py --png                # HTML 을 PNG 로도 렌더링(playwright 필요)
  python main.py --template feed      # 카카오 피드 카드로 전송(기본: text)
  python main.py --dry-run            # 카카오로 보낼 내용만 출력(실제 전송 X)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime

from news_card import card, config, kakao, news


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="뉴스 카드 생성 & 카카오톡 자동 송출")
    p.add_argument("--date", help="대상 날짜 (YYYY-MM-DD, 기본: 오늘)")
    p.add_argument("--title", default="오늘의 뉴스", help="카드 제목")
    p.add_argument("--limit", type=int, default=None, help="뉴스 개수")
    p.add_argument("--template", choices=["text", "feed"], default="text",
                   help="카카오 템플릿 종류 (기본: text)")
    p.add_argument("--no-send", action="store_true", help="카카오 전송 없이 카드만 생성")
    p.add_argument("--png", action="store_true", help="HTML 을 PNG 로도 렌더링")
    p.add_argument("--dry-run", action="store_true", help="전송 대신 보낼 내용을 출력")
    return p.parse_args(argv)


def resolve_date(value: str | None) -> date:
    if not value:
        return date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def main(argv=None) -> int:
    args = parse_args(argv)
    target = resolve_date(args.date)

    # 1) 뉴스 수집
    items = news.get_news(target, limit=args.limit)
    print(f"📰 {card.korean_date(target)} · 뉴스 {len(items)}건 로드")
    for i, it in enumerate(items, start=1):
        print(f"   {i}. {it.title}")

    if not items:
        print("⚠️  뉴스가 없습니다. data/news_<날짜>.json 을 만들거나 NEWS_RSS_URL 을 설정하세요.")

    # 2) HTML 카드 생성
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    html_content = card.build_html_card(target, items, title=args.title)
    html_path = config.OUTPUT_DIR / f"card_{target.isoformat()}.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"🖼️  HTML 카드 생성: {html_path}")

    if args.png:
        png_path = config.OUTPUT_DIR / f"card_{target.isoformat()}.png"
        if card.render_png(html_content, png_path):
            print(f"🖼️  PNG 카드 생성: {png_path}")

    # 3) 카카오 템플릿 생성
    if args.template == "feed":
        template = card.build_kakao_feed_template(target, items, title=args.title)
    else:
        template = card.build_kakao_text_template(target, items, title=args.title)

    if args.dry_run:
        print("\n🔎 [dry-run] 카카오로 보낼 템플릿:")
        print(json.dumps(template, ensure_ascii=False, indent=2))
        return 0

    # 4) 카카오 전송
    if args.no_send:
        print("⏭️  --no-send 옵션: 전송을 건너뜁니다.")
        return 0

    try:
        kakao.send_to_me(template)
    except kakao.KakaoError as exc:
        print(f"❌ 카카오 전송 실패: {exc}", file=sys.stderr)
        print("   토큰 설정을 확인하세요(.env). 카드(HTML)는 정상 생성되었습니다.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
