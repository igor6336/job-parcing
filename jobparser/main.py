"""Точка входа: собрать вакансии -> отфильтровать -> вычесть уже отправленные -> Telegram."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import Config, Secrets
from .dedup import SeenStore
from .filters import apply_filters
from .formatter import build_markdown, build_messages
from .sources import SOURCES
from .telegram import TelegramError, send_messages
from .utils import make_session

log = logging.getLogger("jobparser")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ежедневный дайджест вакансий в Telegram")
    parser.add_argument("--config", default=None, help="путь к config.yaml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="не отправлять в Telegram и не менять файл состояния",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="игнорировать историю отправок (полезно при первом запуске)",
    )
    parser.add_argument("--limit", type=int, default=None, help="переопределить max_results")
    parser.add_argument("--out", default=None, help="сохранить дайджест в Markdown-файл")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def collect(config: Config, secrets: Secrets, session) -> list:
    vacancies = []
    for name, source_cls in SOURCES.items():
        source = source_cls(config.source(name), config.search, session, secrets)
        vacancies.extend(source.safe_fetch())
    return vacancies


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = Config.load(args.config)
    secrets = Secrets.from_env()
    session = make_session()

    raw = collect(config, secrets, session)
    log.info("всего собрано: %d", len(raw))
    if not raw:
        log.error("ни один источник не вернул данных — проверьте сеть и логи выше")

    relevant = apply_filters(raw, config.search)
    log.info("после фильтрации: %d", len(relevant))

    store = SeenStore(
        config.dedup.get("state_file", "state/seen.json"),
        int(config.dedup.get("ttl_days", 60)),
    )
    fresh = relevant if args.no_dedup else store.filter_new(relevant)
    log.info("новых с прошлого запуска: %d (в истории %d записей)", len(fresh), len(store))

    limit = args.limit or int(config.search.get("max_results", 25))
    fresh = fresh[:limit]

    header = config.telegram.get("header", "Вакансии")
    messages = build_messages(fresh, header)

    if not fresh:
        # Расписание GitHub Actions ненадёжно и пропускает запуски, поэтому
        # workflow дублирует их резервными. Если дайджест сегодня уже ушёл,
        # резервный запуск молчит, иначе за день приходило бы несколько
        # сообщений «новых вакансий нет».
        if store.sent_today():
            log.info("дайджест сегодня уже отправлен — резервный запуск молчит")
            return 0
        if config.telegram.get("notify_when_empty", True):
            messages = [config.telegram.get("empty_message", "Новых вакансий нет.")]
        else:
            log.info("нечего отправлять — выходим")
            return 0

    if args.out:
        Path(args.out).write_text(build_markdown(fresh, header), encoding="utf-8")
        log.info("дайджест сохранён в %s", args.out)

    if args.dry_run:
        print("\n\n".join(messages))
        return 0

    chat_ids = secrets.telegram_chat_ids
    if not (secrets.telegram_token and chat_ids):
        log.error("не заданы TELEGRAM_BOT_TOKEN и/или TELEGRAM_CHAT_ID")
        return 2

    try:
        send_messages(session, secrets.telegram_token, chat_ids, messages)
    except TelegramError as exc:
        log.error("отправка не удалась: %s", exc)
        return 3

    # Состояние обновляем только после успешной доставки, иначе вакансии
    # потеряются: они будут помечены отправленными, но пользователь их не увидит.
    # Достаточно одного дошедшего получателя — иначе чат, который «отвалился»,
    # заставлял бы остальных получать один и тот же дайджест каждый день.
    if fresh:
        store.mark_sent(fresh)
    store.mark_digest_sent()
    removed = store.prune()
    store.save()
    log.info("состояние сохранено (удалено устаревших записей: %d)", removed)

    return 0


if __name__ == "__main__":
    sys.exit(main())
