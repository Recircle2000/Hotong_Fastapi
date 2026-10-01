from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from functools import lru_cache
from typing import Any, Iterable

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from services.push import PushNotification


logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
# 토큰이 더는 이 앱의 것이 아니라는 뜻이라 DB에서 지워도 되는 오류들.
STALE_TOKEN_ERRORS = {"UNREGISTERED", "SENDER_ID_MISMATCH"}


class FcmClient:
    def __init__(self, credentials: service_account.Credentials, project_id: str) -> None:
        self._credentials = credentials
        self._project_id = project_id
        self._lock = threading.Lock()

    @property
    def endpoint(self) -> str:
        return f"https://fcm.googleapis.com/v1/projects/{self._project_id}/messages:send"

    def _access_token(self) -> str:
        with self._lock:
            if not self._credentials.valid:
                self._credentials.refresh(GoogleAuthRequest())
            return self._credentials.token

    async def send_all(self, notifications: Iterable[PushNotification]) -> list[str]:
        """Send each notification and return tokens that FCM reports as stale."""
        notifications = list(notifications)
        if not notifications:
            return []
        access_token = await asyncio.to_thread(self._access_token)
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=10) as client:
            results = await asyncio.gather(
                *(self._send(client, headers, item) for item in notifications),
                return_exceptions=True,
            )
        stale = []
        for item, result in zip(notifications, results):
            if isinstance(result, Exception):
                logger.warning("FCM send failed: %s", result)
            elif result:
                stale.append(item.token)
        return stale

    async def _send(self, client: httpx.AsyncClient, headers: dict[str, str], item: PushNotification) -> bool:
        response = await client.post(self.endpoint, headers=headers, json={"message": build_message(item)})
        if response.status_code == 200:
            return False
        if is_stale_token_response(response.status_code, response.text):
            return True
        logger.warning("FCM send rejected (%s): %s", response.status_code, response.text[:300])
        return False


def build_message(item: PushNotification) -> dict[str, Any]:
    return {
        "token": item.token,
        "notification": {"title": item.title, "body": item.body},
        "data": item.data,
        "android": {
            "priority": "high",
            "notification": {"tag": item.collapse_key},
        },
        "apns": {
            "headers": {"apns-collapse-id": item.collapse_key},
            "payload": {"aps": {"sound": "default", "thread-id": item.collapse_key}},
        },
    }


def is_stale_token_response(status_code: int, text: str) -> bool:
    if status_code == 404:
        return True
    try:
        details = json.loads(text).get("error", {}).get("details", [])
    except (ValueError, AttributeError):
        return False
    return any(
        isinstance(detail, dict) and detail.get("errorCode") in STALE_TOKEN_ERRORS
        for detail in details
    )


def _load_service_account_info() -> dict[str, Any] | None:
    raw = os.getenv("FCM_SERVICE_ACCOUNT_JSON")
    if raw:
        return json.loads(raw)
    path = os.getenv("FCM_SERVICE_ACCOUNT_FILE")
    if path:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    return None


@lru_cache(maxsize=1)
def get_fcm_client() -> FcmClient | None:
    """서비스 계정이 설정되지 않았으면 None을 돌려주고, 그때는 푸시를 보내지 않는다."""
    try:
        info = _load_service_account_info()
    except (OSError, ValueError):
        logger.exception("Failed to load FCM service account")
        return None
    if not info:
        return None
    credentials = service_account.Credentials.from_service_account_info(info, scopes=[FCM_SCOPE])
    project_id = os.getenv("FCM_PROJECT_ID") or info["project_id"]
    return FcmClient(credentials, project_id)
