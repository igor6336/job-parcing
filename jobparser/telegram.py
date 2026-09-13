"""Отправка в Telegram через Bot API."""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramError(RuntimeError):
    pass


def send_messages(
    session: requests.Session,
    token: str,
    chat_id: str,
    messages: list[str],
) -> int:
    """Отправляет сообщения подряд. Возвращает число доставленных."""
    url = API_URL.format(token=token)
    sent = 0

    for index, text in enumerate(messages):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            response = session.post(url, json=payload, timeout=30)
        except requests.RequestException as exc:
            raise TelegramError(f"сеть недоступна: {exc}") from exc

        if response.status_code != 200:
            # Тело ответа Telegram содержит описание ошибки, но не токен.
            raise TelegramError(
                f"Telegram вернул HTTP {response.status_code}: {response.text[:300]}"
            )

        sent += 1
        if index + 1 < len(messages):
            time.sleep(1)  # лимит Bot API: ~30 сообщений/сек, здесь запас с избытком

    log.info("отправлено сообщений: %d", sent)
    return sent
