"""환경설정 로더.

.env 파일(있으면)과 환경변수에서 설정값을 읽어옵니다.
외부 라이브러리 없이 아주 간단한 .env 파서를 직접 구현했습니다.
"""

from __future__ import annotations

import os
from pathlib import Path

# 프로젝트 루트 (이 파일 기준 한 단계 위)
ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """.env 파일을 읽어 os.environ 에 채운다(이미 설정된 값은 덮어쓰지 않음)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 이미 실제 환경변수로 지정된 값이 우선(예: GitHub Actions Secrets)
        os.environ.setdefault(key, value)


# 모듈 임포트 시점에 .env 자동 로드
_load_dotenv(ROOT / ".env")


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def get_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, "").strip() or default)
    except ValueError:
        return default


# 자주 쓰는 값들
KAKAO_REST_API_KEY = get("KAKAO_REST_API_KEY")
KAKAO_ACCESS_TOKEN = get("KAKAO_ACCESS_TOKEN")
KAKAO_REFRESH_TOKEN = get("KAKAO_REFRESH_TOKEN")
NEWS_RSS_URL = get("NEWS_RSS_URL")
NEWS_LIMIT = get_int("NEWS_LIMIT", 5)
CARD_IMAGE_URL = get("CARD_IMAGE_URL")

# 갱신된 토큰을 저장할 파일 경로
TOKEN_FILE = ROOT / "kakao_token.json"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
