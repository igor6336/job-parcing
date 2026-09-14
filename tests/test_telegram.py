"""Рассылка нескольким получателям."""

import pytest

from jobparser.config import Secrets
from jobparser.telegram import TelegramError, send_messages


class FakeResponse:
    def __init__(self, status_code=200, text="{}"):
        self.status_code = status_code
        self.text = text


class FakeSession:
    """Отдаёт 400 «chat not found» для чатов из broken."""

    def __init__(self, broken=()):
        self.broken = set(broken)
        self.sent = []

    def post(self, url, json=None, timeout=None):
        chat_id = json["chat_id"]
        if chat_id in self.broken:
            return FakeResponse(400, '{"description":"Bad Request: chat not found"}')
        self.sent.append((chat_id, json["text"]))
        return FakeResponse()


def test_chat_ids_parsed_from_any_separator(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111, 222;333 444")
    assert Secrets.from_env().telegram_chat_ids == ["111", "222", "333", "444"]


def test_duplicate_chat_id_collapses(monkeypatch):
    # Иначе один и тот же человек получил бы дайджест дважды.
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111,111, 222")
    assert Secrets.from_env().telegram_chat_ids == ["111", "222"]


def test_every_recipient_gets_every_message():
    session = FakeSession()
    delivered = send_messages(session, "token", ["111", "222"], ["часть 1", "часть 2"])
    assert delivered == ["111", "222"]
    assert len(session.sent) == 4


def test_one_broken_recipient_does_not_block_others():
    # Друг не написал боту → «chat not found». Остальные всё равно получают.
    session = FakeSession(broken={"222"})
    delivered = send_messages(session, "token", ["111", "222", "333"], ["дайджест"])
    assert delivered == ["111", "333"]
    assert [chat for chat, _ in session.sent] == ["111", "333"]


def test_all_recipients_broken_raises():
    # Если не дошло вообще никому — это ошибка, историю обновлять нельзя.
    session = FakeSession(broken={"111", "222"})
    with pytest.raises(TelegramError):
        send_messages(session, "token", ["111", "222"], ["дайджест"])


def test_plain_string_still_works():
    session = FakeSession()
    assert send_messages(session, "token", "111", ["дайджест"]) == ["111"]


def test_backup_run_stays_silent_after_digest_sent(tmp_path):
    """Резервный запуск не должен слать второе «новых нет» за день."""
    from jobparser.dedup import SeenStore

    store = SeenStore(tmp_path / "seen.json")
    assert not store.sent_today()

    store.mark_digest_sent()
    store.save()

    reloaded = SeenStore(tmp_path / "seen.json")
    assert reloaded.sent_today()
    # Служебная запись не должна попадать в счётчик истории вакансий.
    assert len(reloaded) == 0
