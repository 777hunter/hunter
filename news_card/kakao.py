"""카카오톡 메시지 전송 클라이언트.

지원 기능:
  - refresh_access_token(): 리프레시 토큰으로 액세스 토큰 자동 재발급
  - send_to_me():   '나에게 보내기'(메모) API 로 전송  → talk_message 권한만 있으면 됨
  - send_to_friends(): 친구에게 보내기 API (추가 권한/검수 필요)

참고 문서: https://developers.kakao.com/docs/latest/ko/message/rest-api
"""

from __future__ import annotations

import json
from typing import List

import requests

from . import config

TOKEN_REFRESH_URL = "https://kauth.kakao.com/oauth/token"
MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
FRIENDS_SEND_URL = "https://kapi.kakao.com/v1/api/talk/friends/message/default/send"


class KakaoError(RuntimeError):
    pass


def _load_saved_access_token() -> str:
    """이전에 갱신해 저장해 둔 토큰이 있으면 우선 사용."""
    if config.TOKEN_FILE.exists():
        try:
            data = json.loads(config.TOKEN_FILE.read_text(encoding="utf-8"))
            return data.get("access_token", "")
        except Exception:
            return ""
    return ""


def _save_access_token(token: str) -> None:
    config.TOKEN_FILE.write_text(
        json.dumps({"access_token": token}, ensure_ascii=False), encoding="utf-8"
    )


def refresh_access_token() -> str:
    """리프레시 토큰으로 새 액세스 토큰을 발급받는다."""
    if not (config.KAKAO_REST_API_KEY and config.KAKAO_REFRESH_TOKEN):
        raise KakaoError("리프레시하려면 KAKAO_REST_API_KEY 와 KAKAO_REFRESH_TOKEN 이 필요합니다.")

    resp = requests.post(
        TOKEN_REFRESH_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": config.KAKAO_REST_API_KEY,
            "refresh_token": config.KAKAO_REFRESH_TOKEN,
        },
        timeout=15,
    )
    payload = resp.json()
    if resp.status_code != 200 or "access_token" not in payload:
        raise KakaoError(f"토큰 갱신 실패: {payload}")

    token = payload["access_token"]
    _save_access_token(token)
    print("🔄 액세스 토큰을 새로 발급했습니다.")
    return token


def _current_access_token() -> str:
    """사용할 액세스 토큰을 결정한다(env → 저장파일 순)."""
    return config.KAKAO_ACCESS_TOKEN or _load_saved_access_token()


def _post_template(url: str, access_token: str, template_object: dict, extra: dict | None = None):
    data = {"template_object": json.dumps(template_object, ensure_ascii=False)}
    if extra:
        data.update(extra)
    return requests.post(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        data=data,
        timeout=15,
    )


def _send_with_retry(url: str, template_object: dict, extra: dict | None = None) -> dict:
    """전송하되, 401(토큰 만료) 이면 리프레시 후 1회 재시도한다."""
    token = _current_access_token()
    if not token:
        raise KakaoError("액세스 토큰이 없습니다. .env 의 KAKAO_ACCESS_TOKEN 또는 KAKAO_REFRESH_TOKEN 을 설정하세요.")

    resp = _post_template(url, token, template_object, extra)

    if resp.status_code == 401 and config.KAKAO_REFRESH_TOKEN:
        # 토큰 만료 → 갱신 후 재시도
        token = refresh_access_token()
        resp = _post_template(url, token, template_object, extra)

    payload = {}
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}

    if resp.status_code != 200:
        raise KakaoError(f"전송 실패(HTTP {resp.status_code}): {payload}")
    return payload


def send_to_me(template_object: dict) -> dict:
    """'나에게 보내기'(메모) 로 전송."""
    result = _send_with_retry(MEMO_SEND_URL, template_object)
    print("✅ 카카오톡(나에게 보내기) 전송 완료.")
    return result


def send_to_friends(template_object: dict, receiver_uuids: List[str]) -> dict:
    """친구에게 보내기. receiver_uuids 는 친구 목록 API 로 조회한 uuid 리스트.

    ※ 이 기능은 카카오 비즈니스 채널 연결 및 권한 검수가 필요합니다.
    """
    extra = {"receiver_uuids": json.dumps(receiver_uuids, ensure_ascii=False)}
    result = _send_with_retry(FRIENDS_SEND_URL, template_object, extra)
    print(f"✅ 카카오톡(친구 {len(receiver_uuids)}명) 전송 완료.")
    return result
