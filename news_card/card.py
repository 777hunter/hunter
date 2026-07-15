"""뉴스 카드 생성 모듈.

- build_html_card(): 보기 좋은 HTML 뉴스 카드 생성
- render_png():      (선택) Playwright 로 HTML → PNG 변환
- build_kakao_feed_template() / build_kakao_text_template(): 카카오 전송용 템플릿 오브젝트
"""

from __future__ import annotations

import html
from datetime import date
from typing import List

from . import config
from .news import NewsItem

_WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


def korean_date(target: date) -> str:
    """2026-07-15 → '2026년 7월 15일 (수)'"""
    wd = _WEEKDAY_KR[target.weekday()]
    return f"{target.year}년 {target.month}월 {target.day}일 ({wd})"


# ─────────────────────────── HTML 카드 ───────────────────────────

def build_html_card(target: date, items: List[NewsItem], title: str = "오늘의 뉴스") -> str:
    date_label = korean_date(target)

    rows = []
    for i, it in enumerate(items, start=1):
        t = html.escape(it.title)
        s = html.escape(it.summary)
        src = html.escape(it.source) if it.source else ""
        link = html.escape(it.url) if it.url else "#"
        src_html = f'<span class="src">{src}</span>' if src else ""
        summary_html = f'<p class="summary">{s}</p>' if s else ""
        rows.append(
            f"""
        <li class="item">
          <span class="num">{i}</span>
          <div class="body">
            <a class="title" href="{link}" target="_blank" rel="noopener">{t}</a>
            {summary_html}
            {src_html}
          </div>
        </li>"""
        )

    items_html = "\n".join(rows) if rows else '<li class="empty">표시할 뉴스가 없습니다.</li>'

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · {date_label}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif;
    background: #f0f2f5; padding: 24px; display: flex; justify-content: center;
  }}
  .card {{
    width: 100%; max-width: 480px; background: #fff; border-radius: 20px;
    overflow: hidden; box-shadow: 0 12px 40px rgba(0,0,0,.12);
  }}
  .header {{
    background: linear-gradient(135deg, #FEE500 0%, #FFCE00 100%);
    color: #1a1a1a; padding: 28px 26px 22px;
  }}
  .header .kicker {{ font-size: 13px; font-weight: 700; letter-spacing: 2px; opacity: .65; }}
  .header h1 {{ font-size: 28px; font-weight: 800; margin: 6px 0 4px; }}
  .header .date {{ font-size: 15px; font-weight: 600; opacity: .8; }}
  .list {{ list-style: none; padding: 8px 0; }}
  .item {{ display: flex; gap: 14px; padding: 18px 26px; border-bottom: 1px solid #f2f2f2; }}
  .item:last-child {{ border-bottom: none; }}
  .num {{
    flex: 0 0 28px; height: 28px; border-radius: 50%; background: #1a1a1a; color: #FEE500;
    font-weight: 800; font-size: 14px; display: flex; align-items: center; justify-content: center;
  }}
  .body {{ flex: 1; min-width: 0; }}
  .title {{ font-size: 16px; font-weight: 700; color: #1a1a1a; text-decoration: none; line-height: 1.4; }}
  .title:hover {{ text-decoration: underline; }}
  .summary {{ font-size: 13.5px; color: #666; margin-top: 5px; line-height: 1.5; }}
  .src {{ display: inline-block; margin-top: 7px; font-size: 12px; color: #999; }}
  .empty {{ padding: 40px; text-align: center; color: #999; }}
  .footer {{ padding: 16px 26px; text-align: center; font-size: 12px; color: #aaa; background: #fafafa; }}
</style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="kicker">NEWS CARD</div>
      <h1>{html.escape(title)}</h1>
      <div class="date">{date_label}</div>
    </div>
    <ul class="list">{items_html}
    </ul>
    <div class="footer">카카오톡 뉴스 카드 · 매일 자동 발송</div>
  </div>
</body>
</html>"""


def render_png(html_content: str, out_path) -> bool:
    """(선택 기능) Playwright 가 설치되어 있으면 HTML 을 PNG 로 렌더링한다.

    성공하면 True, Playwright 미설치 등으로 실패하면 False 를 반환한다.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ℹ️  playwright 미설치 → PNG 렌더링을 건너뜁니다 (HTML 은 정상 생성됨).")
        return False

    # 사전 설치된 크로미움 경로를 환경변수로 지정할 수 있게 지원(선택)
    import os
    exe = os.environ.get("CHROMIUM_PATH") or None
    launch_kwargs = {"executable_path": exe} if exe else {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page(viewport={"width": 528, "height": 900}, device_scale_factor=2)
            page.set_content(html_content, wait_until="networkidle")
            card = page.query_selector(".card")
            (card or page).screenshot(path=str(out_path))
            browser.close()
        return True
    except Exception as exc:
        print(f"⚠️  PNG 렌더링 실패: {exc}")
        return False


# ─────────────────────────── 카카오 템플릿 ───────────────────────────

def build_kakao_text_template(target: date, items: List[NewsItem], title: str = "오늘의 뉴스") -> dict:
    """카카오 '텍스트' 기본 템플릿. 이미지 호스팅 없이 가장 확실하게 전송된다."""
    lines = [f"📰 {title} ({korean_date(target)})", ""]
    for i, it in enumerate(items, start=1):
        lines.append(f"{i}. {it.title}")
        if it.summary:
            lines.append(f"   {it.summary}")
    text = "\n".join(lines)
    # 카카오 텍스트 템플릿은 최대 200자. 넘으면 잘라낸다.
    if len(text) > 200:
        text = text[:197] + "…"

    link_url = next((it.url for it in items if it.url), "https://www.kakaocorp.com")
    return {
        "object_type": "text",
        "text": text,
        "link": {"web_url": link_url, "mobile_web_url": link_url},
        "button_title": "자세히 보기",
    }


def build_kakao_feed_template(target: date, items: List[NewsItem], title: str = "오늘의 뉴스") -> dict:
    """카카오 '피드' 기본 템플릿(대표 뉴스 + 이미지 + 버튼)."""
    head = items[0] if items else NewsItem(title="표시할 뉴스가 없습니다.")
    desc_lines = [f"{i}. {it.title}" for i, it in enumerate(items, start=1)]
    description = "\n".join(desc_lines)[:400]

    link_url = head.url or "https://www.kakaocorp.com"
    content = {
        "title": f"📰 {title} · {korean_date(target)}",
        "description": description,
        "link": {"web_url": link_url, "mobile_web_url": link_url},
    }
    if config.CARD_IMAGE_URL:
        content["image_url"] = config.CARD_IMAGE_URL
        content["image_width"] = 800
        content["image_height"] = 400

    return {
        "object_type": "feed",
        "content": content,
        "buttons": [
            {"title": "자세히 보기", "link": {"web_url": link_url, "mobile_web_url": link_url}}
        ],
    }
