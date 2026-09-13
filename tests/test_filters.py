from datetime import datetime, timedelta, timezone

from jobparser.config import Config
from jobparser.filters import apply_filters, is_relevant, normalize
from jobparser.models import Vacancy

SEARCH = Config.load().search


def make(
    title,
    *,
    company="ООО Ромашка",
    text="",
    area="Москва",
    salary=None,
    prefiltered=False,
    experience_years=None,
):
    return Vacancy(
        source="test",
        external_id=title,
        title=title,
        company=company,
        url="https://example.com/1",
        salary=salary,
        requirements=text or None,
        area=area,
        raw_text=text,
        level_prefiltered=prefiltered,
        experience_years=experience_years,
    )


def test_normalize_splits_punctuation():
    assert normalize("BI-аналитик (Junior)") == " bi аналитик junior "
    assert "стажер" in normalize("Стажёр-аналитик")


def test_junior_analyst_passes():
    ok, score, _ = is_relevant(make("Junior бизнес-аналитик"), SEARCH)
    assert ok and score > 5


def test_internship_passes():
    ok, _, _ = is_relevant(make("Стажировка: финансовый аналитик"), SEARCH)
    assert ok


def test_senior_rejected():
    ok, _, reason = is_relevant(make("Senior BI-аналитик"), SEARCH)
    assert not ok and "стоп-слово" in reason


def test_analyst_without_level_rejected():
    ok, _, reason = is_relevant(make("Аналитик бизнес-процессов"), SEARCH)
    assert not ok and "junior" in reason


def test_analyst_without_level_passes_if_source_prefiltered():
    ok, _, _ = is_relevant(make("Аналитик бизнес-процессов", prefiltered=True), SEARCH)
    assert ok


def test_required_experience_rejected():
    ok, _, reason = is_relevant(
        make("Junior аналитик данных", text="Требуется опыт работы от 3 лет в BI"), SEARCH
    )
    assert not ok and "опыт" in reason


def test_other_city_rejected():
    ok, _, reason = is_relevant(make("Стажер бизнес-аналитик", area="Казань"), SEARCH)
    assert not ok and "регион" in reason


def test_unrelated_role_rejected():
    ok, _, _ = is_relevant(make("Стажер-курьер"), SEARCH)
    assert not ok


def test_role_only_in_description_rejected():
    # Реальный случай из выдачи trudvsem: «аналитика обращений» в обязанностях
    # затаскивала клиентский саппорт в дайджест.
    ok, _, reason = is_relevant(
        make("Стажер специалиста по работе с клиентами", text="аналитика обращений клиентов"),
        SEARCH,
    )
    assert not ok and "в названии" in reason


def test_numeric_experience_rejected():
    # trudvsem отдаёт опыт числом; «Младший финансовый аналитик, опыт 4 года»
    # формально проходил по названию.
    ok, _, reason = is_relevant(
        make("Младший финансовый аналитик", experience_years=4), SEARCH
    )
    assert not ok and "опыт" in reason


def test_word_boundary_prefix_match():
    # «аналитик» должен ловить падежи, но не срабатывать внутри чужого слова.
    ok, _, _ = is_relevant(make("Стажер отдела аналитики"), SEARCH)
    assert ok
    ok, _, _ = is_relevant(make("Junior специалист по комбинаторике"), SEARCH)
    assert not ok


def test_fresh_vacancy_ranks_higher():
    fresh = make("Junior бизнес-аналитик", company="A")
    fresh.published_at = datetime.now(timezone.utc)
    old = make("Junior бизнес-аналитик", company="B")
    old.published_at = datetime.now(timezone.utc) - timedelta(days=10)

    result = apply_filters([old, fresh], SEARCH)
    assert [v.company for v in result] == ["A", "B"]


def test_cross_source_duplicates_collapse():
    a = make("Junior бизнес-аналитик")
    b = make("junior бизнес аналитик!")
    b.source = "other"
    assert len(apply_filters([a, b], SEARCH)) == 1
