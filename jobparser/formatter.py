"""Сборка дайджеста: карточка вакансии -> сообщения в пределах лимита Telegram."""

from __future__ import annotations

from html import escape

from .models import Vacancy
from .utils import truncate

TELEGRAM_LIMIT = 4096
CHUNK_LIMIT = 3800  # запас на заголовок и служебные строки


def _line(emoji: str, value: str | None) -> str | None:
    if not value:
        return None
    return f"{emoji} {escape(value)}"


def format_vacancy(vacancy: Vacancy, index: int) -> str:
    schedule_parts = [p for p in (vacancy.schedule, vacancy.employment) if p]
    schedule = " · ".join(dict.fromkeys(schedule_parts)) or None

    lines = [
        f"<b>{index}. {escape(vacancy.title)}</b>",
        _line("🏢", vacancy.company or "—"),
        # Зарплату показываем всегда: «не указана» — это тоже информация.
        _line("💰", vacancy.salary or "не указана"),
        # График и требования опускаем, если источник их не отдал: у RSS-фида
        # hh этих полей нет в принципе, и строки-заглушки делали бы вид,
        # будто данные потерялись.
        _line("🗓", schedule),
        _line("📋", truncate(vacancy.requirements, 230) if vacancy.requirements else None),
        f'🔗 <a href="{escape(vacancy.url, quote=True)}">Откликнуться</a> · <i>{escape(vacancy.source)}</i>',
    ]
    return "\n".join(line for line in lines if line)


def build_messages(vacancies: list[Vacancy], header: str) -> list[str]:
    """Разбивает дайджест на сообщения, не разрывая карточку вакансии."""
    if not vacancies:
        return []

    blocks = [format_vacancy(v, i) for i, v in enumerate(vacancies, start=1)]
    head = f"<b>{escape(header)}</b>\nНайдено новых: {len(vacancies)}"

    messages: list[str] = []
    current = head
    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if len(candidate) > CHUNK_LIMIT and current not in (head, ""):
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)

    # Страховка на случай одной аномально длинной карточки.
    return [m[:TELEGRAM_LIMIT] for m in messages]


def build_markdown(vacancies: list[Vacancy], header: str) -> str:
    """Тот же дайджест в Markdown — для локального прогона и артефакта workflow."""
    lines = [f"# {header}", "", f"Найдено новых: {len(vacancies)}", ""]
    for index, vacancy in enumerate(vacancies, start=1):
        schedule_parts = [p for p in (vacancy.schedule, vacancy.employment) if p]
        lines += [
            f"## {index}. {vacancy.title}",
            f"- **Компания:** {vacancy.company or '—'}",
            f"- **Зарплата:** {vacancy.salary or 'не указана'}",
            f"- **График:** {' · '.join(dict.fromkeys(schedule_parts)) or 'не указан'}",
            f"- **Требования:** {truncate(vacancy.requirements, 300) if vacancy.requirements else '—'}",
            f"- **Отклик:** {vacancy.url}",
            f"- **Источник:** {vacancy.source}",
            "",
        ]
    return "\n".join(lines)
