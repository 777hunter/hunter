"""뉴스 데이터 로드 모듈.

우선순위:
  1) NEWS_RSS_URL 이 설정되어 있으면 RSS 에서 실시간 수집
  2) 없으면 data/news_<날짜>.json 로컬 파일 사용
  3) 그마저 없으면 빈 목록
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import date
from typing import List
from xml.etree import ElementTree as ET

import requests

from . import config


@dataclass
class NewsItem:
    title: str
    summary: str = ""
    source: str = ""
    url: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str, limit: int = 120) -> str:
    """HTML 태그 제거 및 공백 정리, 길이 제한."""
    if not text:
        return ""
    text = _TAG_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def fetch_news_from_rss(url: str, limit: int) -> List[NewsItem]:
    """RSS 피드에서 뉴스를 가져온다(대부분의 표준 RSS 2.0 지원)."""
    resp = requests.get(url, timeout=15, headers={"User-Agent": "news-card/1.0"})
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    items: List[NewsItem] = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title", default=""), limit=80)
        summary = _clean(item.findtext("description", default=""), limit=120)
        link = (item.findtext("link", default="") or "").strip()
        source = _clean(item.findtext("source", default=""), limit=30)
        if title:
            items.append(NewsItem(title=title, summary=summary, source=source, url=link))
        if len(items) >= limit:
            break
    return items


def load_news_from_file(target: date) -> List[NewsItem]:
    """data/news_<YYYY-MM-DD>.json 에서 뉴스를 읽는다."""
    path = config.DATA_DIR / f"news_{target.isoformat()}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    return [
        NewsItem(
            title=it.get("title", ""),
            summary=it.get("summary", ""),
            source=it.get("source", ""),
            url=it.get("url", ""),
        )
        for it in items
        if it.get("title")
    ]


def get_news(target: date, limit: int | None = None) -> List[NewsItem]:
    """설정에 따라 적절한 소스에서 뉴스를 가져온다."""
    limit = limit or config.NEWS_LIMIT

    if config.NEWS_RSS_URL:
        try:
            items = fetch_news_from_rss(config.NEWS_RSS_URL, limit)
            if items:
                return items
            print("⚠️  RSS 결과가 비어 있어 로컬 데이터로 대체합니다.")
        except Exception as exc:  # 네트워크/파싱 오류 시 로컬로 폴백
            print(f"⚠️  RSS 수집 실패({exc}) → 로컬 데이터로 대체합니다.")

    return load_news_from_file(target)[:limit]
