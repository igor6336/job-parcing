"""Отправка в Telegram через Bot API."""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramError(RuntimeError):
    pass


def _send_one(session: requests.Session, url: str, chat_id: str, text: str) -> None:
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


def send_messages(
    session: requests.Session,
    token: str,
    chat_ids: str | list[str],
    messages: list[str],
) -> list[str]:
    """Рассылает дайджест всем получателям.

    Возвращает список чатов, до которых сообщения дошли. Сбой у одного
    получателя не отменяет отправку остальным: чаще всего это значит, что
    человек ещё не написал боту («chat not found»), и наказывать за это
    остальных незачем.
    """
    if isinstance(chat_ids, str):
        chat_ids = [chat_ids]

    url = API_URL.format(token=token)
    delivered: list[str] = []
    failures: list[str] = []

    for chat_id in chat_ids:
        try:
            for index, text in enumerate(messages):
                _send_one(session, url, chat_id, text)
                if index + 1 < len(messages):
                    time.sleep(1)  # лимит Bot API ~30 сообщений/сек, здесь запас
            delivered.append(chat_id)
        except TelegramError as exc:
            failures.append(chat_id)
            log.error("чат %s: доставка не удалась — %s", chat_id, exc)

    log.info(
        "доставлено в %d из %d чатов (сообщений каждому: %d)",
        len(delivered),
        len(chat_ids),
        len(messages),
    )
    if failures and not delivered:
        raise TelegramError(f"ни один получатель не получил дайджест: {failures}")
    return delivered
