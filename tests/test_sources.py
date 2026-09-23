"""Парсинг ответов площадок на зафиксированных фрагментах реальной выдачи.

Фикстуры сняты с живых ответов, поэтому тесты ловят изменение формата
источника, но при этом не ходят в сеть.
"""

from jobparser.config import Config
from jobparser.sources.hh import HHSource
from jobparser.sources.linkedin import LinkedInSource

SEARCH = Config.load().search

HH_RSS = """<?xml version='1.0' encoding='utf-8'?>
<rss version="2.0"><channel><title>HeadHunter Vacancy</title>
<item>
  <pubDate>2026-09-02T15:01:48.709+03:00</pubDate>
  <title>Бизнес-аналитик (стажер) &amp;mdash; отдел отчетности</title>
  <link>https://hh.ru/vacancy/136896841</link>
  <description><![CDATA[<p>Вакансия компании: PepsiCo</p> <p>Создана: 02.09.2026</p> <p>Регион: Москва</p> <p>Предполагаемый уровень месячного дохода: до 123 100 &#8381;</p>]]></description>
</item>
<item>
  <pubDate>2026-09-10T13:48:57.299+03:00</pubDate>
  <title>GR Директор</title>
  <link>https://hh.ru/vacancy/137205425</link>
  <description><![CDATA[<p>Вакансия компании: СНС, Группа компаний</p> <p>Создана: 10.09.2026</p> <p>Регион: Москва</p> <p>Предполагаемый уровень месячного дохода: не указан</p>]]></description>
</item>
</channel></rss>"""

LINKEDIN_HTML = """
<li>
 <div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:4462500029">
  <a class="base-card__full-link" href="https://ru.linkedin.com/jobs/view/junior-analyst-at-acme-4462500029?position=1&amp;refId=xyz"></a>
  <div class="base-search-card__info">
   <h3 class="base-search-card__title">Junior Financial Analyst</h3>
   <h4 class="base-search-card__subtitle"><a href="#">ACME Corp</a></h4>
   <div class="base-search-card__metadata">
    <span class="job-search-card__location">Агломерация Москвы</span>
    <time class="job-search-card__listdate" datetime="2026-09-11"></time>
   </div>
  </div>
 </div>
</li>
"""


def make_source(cls, cfg=None):
    return cls(cfg or {"enabled": True}, SEARCH, session=None)


def test_hh_rss_parsing():
    items = make_source(HHSource)._parse_feed(HH_RSS)
    assert len(items) == 2

    first = items[0]
    assert first.external_id == "136896841"
    assert first.company == "PepsiCo"
    assert first.area == "Москва"
    assert first.salary == "до 123 100 ₽"
    assert first.url == "https://hh.ru/vacancy/136896841"
    # В заголовках фида сущности экранированы дважды: «&amp;mdash;».
    assert "—" in first.title
    assert first.published_at is not None


def test_hh_rss_treats_unspecified_salary_as_empty():
    items = make_source(HHSource)._parse_feed(HH_RSS)
    assert items[1].salary is None


def test_hh_rss_survives_broken_xml():
    assert make_source(HHSource)._parse_feed("<rss><item>обрыв") == []


def test_linkedin_card_parsing():
    items = make_source(LinkedInSource)._parse(LINKEDIN_HTML)
    assert len(items) == 1

    vacancy = items[0]
    assert vacancy.external_id == "4462500029"
    assert vacancy.title == "Junior Financial Analyst"
    assert vacancy.company == "ACME Corp"
    assert vacancy.area == "Агломерация Москвы"
    # Хвост трекинга в ссылке ломал бы дедупликацию между запусками.
    assert vacancy.url == "https://ru.linkedin.com/jobs/view/junior-analyst-at-acme-4462500029"


def test_linkedin_moscow_agglomeration_passes_city_filter():
    """«Агломерация Москвы» — это Москва, регион отбрасывать вакансию не должен.

    Проверяем именно причину отказа: по баллам junior на полный день
    отсеивается отдельным правилом, и это здесь ни при чём.
    """
    from jobparser.filters import is_relevant

    vacancy = make_source(LinkedInSource)._parse(LINKEDIN_HTML)[0]
    _, _, reason = is_relevant(vacancy, SEARCH)
    assert "регион" not in reason
