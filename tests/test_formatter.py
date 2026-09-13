from jobparser.formatter import CHUNK_LIMIT, TELEGRAM_LIMIT, build_messages, format_vacancy
from jobparser.models import Vacancy
from jobparser.utils import format_salary


def make(index: int) -> Vacancy:
    return Vacancy(
        source="hh.ru",
        external_id=str(index),
        title=f"Junior аналитик {index}",
        company="Компания & Co",
        url=f"https://hh.ru/vacancy/{index}",
        salary="от 80 000 ₽",
        schedule="Полный день",
        employment="Стажировка",
        requirements="Excel, SQL, базовое знание BI",
    )


def test_card_contains_all_requested_fields():
    card = format_vacancy(make(1), 1)
    assert "Компания &amp; Co" in card  # html-экранирование
    assert "от 80 000 ₽" in card
    assert "Полный день · Стажировка" in card
    assert "Excel, SQL" in card
    assert 'href="https://hh.ru/vacancy/1"' in card


def test_messages_respect_telegram_limit():
    messages = build_messages([make(i) for i in range(80)], "Дайджест")
    assert len(messages) > 1
    assert all(len(m) <= TELEGRAM_LIMIT for m in messages)
    assert all(len(m) <= CHUNK_LIMIT + 200 for m in messages)


def test_no_messages_for_empty_list():
    assert build_messages([], "Дайджест") == []


def test_salary_formats():
    assert format_salary(80000, 120000, "RUR") == "80 000–120 000 ₽"
    assert format_salary(80000, None, "RUR", gross=False) == "от 80 000 ₽ (на руки)"
    assert format_salary(None, 60000, "RUR") == "до 60 000 ₽"
    assert format_salary(None, None, "RUR") is None
