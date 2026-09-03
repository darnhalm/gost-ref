"""Эталоны взяты из примеров к самим стандартам и методичек библиотек,
проверяющих эти стандарты (ГОСТ Р 7.0.5-2008 прил. А; ГОСТ Р 7.0.100-2018;
ГОСТ Р 7.0.108-2022). Тест держит пунктуацию: любое расхождение в
предписанных знаках ломает сборку."""

import pytest

import gost_ref as g
from gost_ref.model import Person
from gost_ref.text import normalize_date, normalize_pages


# --------------------------------------------------------------------------
# Имена
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw, surname, initials", [
    ("Иванов И. И.", "Иванов", "И. И."),
    ("Иванов И.И.", "Иванов", "И. И."),
    ("И. И. Иванов", "Иванов", "И. И."),
    ("Иванов, И. И.", "Иванов", "И. И."),
    ("Иванов Иван Иванович", "Иванов", "И. И."),
    ("Rancier M.", "Rancier", "M."),
    ("Bates E.", "Bates", "E."),
])
def test_person_parse(raw, surname, initials):
    p = Person.parse(raw)
    assert p.surname == surname
    assert p.short == initials


def test_person_heading_forms():
    p = Person.parse("Лихачев Дмитрий Сергеевич")
    assert p.heading(comma=False) == "Лихачев Д. С."
    assert p.heading(comma=True) == "Лихачев, Д. С."
    assert p.responsibility() == "Д. С. Лихачев"
    assert p.full() == "Лихачев Дмитрий Сергеевич"


# --------------------------------------------------------------------------
# ГОСТ Р 7.0.5-2008
# --------------------------------------------------------------------------

def test_705_book_without_publisher():
    out = g.format_reference(dict(
        type="book", authors="Лисичкин В. А., Шелепин Л. А.",
        title="Война после войны", subtitle="информационная оккупация продолжается",
        city="Москва", year="2005", total_pages="416"), "7.0.5")
    assert out == ("Лисичкин В. А., Шелепин Л. А. Война после войны : "
                   "информационная оккупация продолжается. М., 2005. 416 с.")


def test_705_book_with_pages():
    out = g.format_reference(dict(
        type="book", authors="Кутепов В. И., Виноградова А. Г.",
        title="Искусство Средних веков", city="Ростов-на-Дону",
        year="2006", pages="144-251"), "7.0.5")
    assert out == "Кутепов В. И., Виноградова А. Г. Искусство Средних веков. Ростов н/Д, 2006. С. 144–251."


def test_705_article():
    out = g.format_reference(dict(
        type="article", authors="Егоров В. В., Грибова И. В.",
        title="Упущенные возможности экономического роста России",
        container="Проблемы машиностроения и автоматизации",
        year="2003", issue="2"), "7.0.5")
    assert out == ("Егоров В. В., Грибова И. В. Упущенные возможности экономического роста "
                   "России // Проблемы машиностроения и автоматизации. 2003. № 2.")


def test_705_four_authors_start_with_title():
    out = g.format_reference(dict(
        type="book", authors=["Азрилиян А. Н.", "Иванов И. И.", "Петров П. П.", "Сидоров С. С."],
        title="Краткий экономический словарь", edition="2-е изд., перераб. и доп.",
        city="Москва", publisher="Ин-т новой экономики", year="2002",
        total_pages="1087"), "7.0.5")
    assert out.startswith("Краткий экономический словарь / А. Н. Азрилиян [и др.].")
    assert out.endswith("М. : Ин-т новой экономики, 2002. 1087 с.")


def test_705_no_area_dash():
    out = g.format_reference(dict(type="book", title="Заглавие", city="Москва", year="2020"), "7.0.5")
    assert "—" not in out


# --------------------------------------------------------------------------
# ГОСТ Р 7.0.100-2018
# --------------------------------------------------------------------------

def test_700100_book_full_city_and_content_type():
    out = g.format_reference(dict(
        type="book", authors="Головницкая Н. П.",
        title="Производство продуктов питания по-немецки", subtitle="учебное пособие",
        organization="Волгоградский государственный аграрный университет",
        city="Волгоград", publisher="Волгоградский ГАУ", year="2019",
        total_pages="88"), "7.0.100", content_type=True)
    assert out == ("Головницкая, Н. П. Производство продуктов питания по-немецки : "
                   "учебное пособие / Н. П. Головницкая ; Волгоградский государственный "
                   "аграрный университет. — Волгоград : Волгоградский ГАУ, 2019. — 88 с. "
                   "— Текст : непосредственный.")


def test_700100_article_content_type_before_slashes():
    out = g.format_reference(dict(
        type="article", authors="Козаченко Ю. В.",
        title="Акариформные клещи и иммунопатология в трудах отечественных исследователей",
        container="Аспирант и соискатель", year="2018", issue="2 (104)",
        pages="19-21"), "7.0.100", content_type=True)
    assert "— Текст : непосредственный // Аспирант и соискатель." in out
    assert out.endswith("— С. 19–21.")


def test_700100_city_never_abbreviated():
    out = g.format_reference(dict(type="book", title="Заглавие", city="СПб.",
                                  publisher="Наука", year="2020"), "7.0.100")
    assert "Санкт-Петербург : Наука, 2020" in out


def test_700100_electronic_gets_electronic_content_type():
    out = g.format_reference(dict(
        type="website", title="Правительство Российской Федерации",
        subtitle="официальный сайт", city="Москва",
        update_note="Обновляется в течение суток",
        url="http://government.ru", access_date="19.02.2018"), "7.0.100",
        content_type=True)
    assert out.endswith("— Текст : электронный.")
    assert "(дата обращения: 19.02.2018)" in out


def test_700100_four_authors_all_named():
    out = g.format_reference(dict(
        type="book", authors="Говдя В. В.; Дегальцева Ж. В.; Чужинов С. В.; Шулепина С. А.",
        title="Управленческий учет", subtitle="монография", editors="Говдя В. В.",
        city="Краснодар", publisher="КубГАУ", year="2017", total_pages="149"), "7.0.100")
    assert out.startswith("Управленческий учет : монография / В. В. Говдя, Ж. В. Дегальцева,")
    assert "; под редакцией В. В. Говдя." in out


def test_700100_no_double_period_before_area_dash():
    out = g.format_reference(dict(type="book", title="Заглавие", city="Москва",
                                  year="2020", total_pages="100"), "7.0.100",
                             content_type=True)
    assert ".. —" not in out
    assert "— 100 с. — Текст" in out


def test_700100_dissertation():
    out = g.format_reference(dict(
        type="abstract", authors="Величковский Борис Борисович",
        title="Функциональная организация рабочей памяти", specialty="19.00.01",
        specialty_name="Общая психология, психология личности, история психологии",
        degree="доктора психологических наук",
        institution="Московский государственный университет им. М. В. Ломоносова",
        city="Москва", year="2017", total_pages="44"), "7.0.100")
    assert "специальность 19.00.01 «Общая психология" in out
    assert "автореферат диссертации на соискание ученой степени доктора психологических наук" in out
    assert "/ Величковский Борис Борисович ; Московский государственный университет" in out


# --------------------------------------------------------------------------
# ГОСТ 7.1-2003
# --------------------------------------------------------------------------

def test_71_general_material_designation():
    out = g.format_reference(dict(
        type="book", authors="Лихачев Д. С.", title="Русская культура",
        city="Санкт-Петербург", publisher="Искусство", year="2007",
        total_pages="440"), "7.1")
    assert out.startswith("Лихачев, Д. С. Русская культура [Текст]")
    assert "– СПб. : Искусство, 2007. – 440 с." in out
    assert "Текст : непосредственный" not in out


# --------------------------------------------------------------------------
# ГОСТ Р 7.0.108-2022
# --------------------------------------------------------------------------

def test_700108_network_article():
    out = g.format_reference(dict(
        type="article", authors="Дирина А. И.",
        title="Право военнослужащих Российской Федерации на свободу ассоциаций",
        container="Военное право", container_subtitle="сетевой журн.", year="2007",
        url="http://www.voennoepravo.ru/node/2149",
        publication_date="19.09.2007"), "7.0.108")
    assert out.endswith("Дата публикации: 19.09.2007.")
    assert "// Военное право : сетевой журн. 2007." in out


def test_700108_falls_back_when_not_online():
    """Стандарт распространяется только на сетевые документы."""
    fields = dict(type="book", authors="Лихачев Д. С.", title="Русская культура",
                  city="Санкт-Петербург", year="2007", total_pages="440")
    assert g.format_reference(fields, "7.0.108") == g.format_reference(fields, "7.0.5")


# --------------------------------------------------------------------------
# Латиница
# --------------------------------------------------------------------------

def test_latin_source_uses_latin_labels():
    out = g.format_reference(dict(
        type="article", authors="Bates E.", title="The Social Life of Musical Instruments",
        container="Ethnomusicology", year="2012", volume="56", issue="3",
        pages="363-395"), "7.0.5")
    assert "Vol. 56, No. 3. P. 363–395." in out


# --------------------------------------------------------------------------
# Разбор
# --------------------------------------------------------------------------

def test_parse_article():
    out = g.parse("Иванов И.И. Виртуальные копии // Вопросы музеологии. 2021. №3. С.45-52.")
    f = out["fields"]
    assert f["type"] == "article"
    assert f["title"] == "Виртуальные копии"
    assert f["container"] == "Вопросы музеологии"
    assert f["year"] == "2021" and f["issue"] == "3" and f["pages"] == "45–52"


def test_parse_latin_article():
    f = g.parse("Bates E. The Social Life of Musical Instruments // Ethnomusicology. "
                "2012. Vol. 56, No. 3. P. 363-395. DOI: 10.5406/ethnomusicology.56.3.0363")["fields"]
    assert f["volume"] == "56" and f["issue"] == "3"
    assert f["doi"] == "10.5406/ethnomusicology.56.3.0363"
    assert f["container"] == "Ethnomusicology"


def test_reformat_autofixes_medium():
    out = g.reformat("Сайт : официальный сайт. - URL: http://example.ru. - Текст : непосредственный.",
                     "7.0.100")
    assert out["autofixes"]
    assert out["fields"]["medium"] == "electronic"


# --------------------------------------------------------------------------
# Проверки
# --------------------------------------------------------------------------

def test_validate_catches_electronic_on_print():
    report = g.validate(dict(type="book", title="Заглавие", city="Москва",
                             year="2020", medium="electronic"))
    assert not report["ok"]
    assert any(e["code"] == "electronic-no-url" for e in report["errors"])


def test_validate_catches_url_without_access_date():
    report = g.validate(dict(type="webpage", title="Заглавие", url="http://example.ru"))
    assert any(e["code"] == "no-access-date" for e in report["errors"])


def test_validate_catches_future_access_date():
    report = g.validate(dict(type="webpage", title="Т", url="http://e.ru",
                             access_date="01.01.2099"))
    assert any(e["code"] == "future-date" for e in report["errors"])


def test_validate_string_requires_content_type_for_700100():
    from gost_ref.validate import check_string
    issues = check_string("Иванов, И. И. Заглавие. — Москва : Наука, 2020. — 100 с.", "7.0.100")
    assert any(i["code"] == "no-content-type" for i in issues)


# --------------------------------------------------------------------------
# Список и повторные ссылки
# --------------------------------------------------------------------------

def test_build_list_sorts_cyrillic_before_latin():
    out = g.build_list([
        dict(type="book", authors="Bates E.", title="Instruments", city="Oxford", year="2012"),
        dict(type="book", authors="Аренс В. Ж.", title="Азбука", city="Москва", year="2006"),
    ], "7.0.100")
    assert out["entries"][0]["reference"].startswith("Аренс")
    assert out["entries"][1]["reference"].startswith("Bates")
    assert out["text"].startswith("1. Аренс")


def test_repeat_references():
    assert g.ibid("25") == "Там же. С. 25."
    assert g.ibid() == "Там же."
    assert g.op_cit("Мигунова Т. Л.", "364") == "Мигунова Т. Л. Указ. соч. С. 364."
    assert g.short_form(dict(authors="Лисичкин В. А., Шелепин Л. А.",
                             title="Война после войны наступает снова"), "212") == \
        "Лисичкин В. А., Шелепин Л. А. Война после войны наступает … С. 212."
    assert g.cited_from(dict(type="book", authors="Иванов И. И.", title="Заглавие",
                             city="Москва", year="2020")).startswith("Цит. по: Иванов И. И.")


# --------------------------------------------------------------------------
# Мелочи
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("45-52", "45–52"), ("С. 45-52", "45–52"), ("45 — 52", "45–52"), ("286", "286"),
])
def test_normalize_pages(raw, expected):
    assert normalize_pages(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("2018-02-19", "19.02.2018"), ("19.02.2018", "19.02.2018"),
    ("1.2.2018", "01.02.2018"), ("17 октября 2003 г.", "17.10.2003"),
])
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


def test_nbsp_option():
    out = g.format_reference(dict(type="book", authors="Иванов И. И.", title="Заглавие",
                                  city="Москва", year="2020", total_pages="100"),
                             "7.0.100", nbsp=True)
    assert " " in out


# --------------------------------------------------------------------------
# Валидатор не должен ругаться на собственный корректный вывод
# --------------------------------------------------------------------------

_CLEAN_CASES = [
    dict(type="book", authors="Лисичкин В. А., Шелепин Л. А.", title="Война после войны",
         subtitle="информационная оккупация", city="Москва", year="2005", total_pages="416"),
    dict(type="book", authors="Говдя В. В.; Дегальцева Ж. В.; Чужинов С. В.; Шулепина С. А.",
         title="Управленческий учет", subtitle="монография", editors="Говдя В. В.",
         city="Краснодар", publisher="КубГАУ", year="2017", total_pages="149"),
    dict(type="article", authors="Козаченко Ю. В.", title="Акариформные клещи",
         container="Аспирант и соискатель", year="2018", issue="2 (104)", pages="19-21"),
    dict(type="website", title="Правительство Российской Федерации", subtitle="официальный сайт",
         city="Москва", update_note="Обновляется в течение суток",
         url="http://government.ru", access_date="19.02.2018"),
    dict(type="article", authors="Московская А. А.", title="Между благами", container="Мониторинг",
         year="2017", issue="6", pages="31-35", url="http://wciom.ru/x.pdf",
         access_date="11.03.2017"),
    dict(type="abstract", authors="Величковский Борис Борисович", title="Рабочая память",
         specialty="19.00.01", specialty_name="Общая психология",
         degree="доктора психологических наук", institution="МГУ им. М. В. Ломоносова",
         city="Москва", year="2017", total_pages="44"),
    dict(type="standard", doc_number="ГОСТ Р 7.0.5-2008", title="Библиографическая ссылка",
         subtitle="общие требования", city="Москва", publisher="Стандартинформ",
         year="2008", total_pages="19"),
    dict(type="chapter", authors="Лихачев Д. С.", title="Образ города",
         container="Историческое краеведение", container_subtitle="сб. науч. ст.",
         city="Киев", year="1991", pages="183-188"),
    dict(type="article", authors="Rancier M.", title="The Musical Instrument as National Archive",
         container="Ethnomusicology", year="2014", volume="58", issue="3", pages="379-404",
         doi="10.5406/ethnomusicology.58.3.0379"),
    dict(type="treaty", title="Конвенция об охране нематериального культурного наследия",
         adopted="Париж, 17 октября 2003 г.", city="Москва", year="2003"),
]


@pytest.mark.parametrize("fields", _CLEAN_CASES)
@pytest.mark.parametrize("standard", ["7.0.5", "7.0.100", "7.1", "7.0.108"])
def test_no_false_positives_on_own_output(fields, standard):
    from gost_ref.validate import check_string
    out = g.format_reference(fields, standard)
    issues = [i for i in check_string(out, standard) if i["level"] in ("error", "warning")]
    assert not issues, f"{standard}: {out}\n{issues}"


def test_prescribed_marks_are_not_flagged():
    """« ; » между группами ответственности, « : » перед подзаголовком и
    многоточие в «дис. ...» — предписанные знаки, а не ошибки пунктуации."""
    from gost_ref.validate import check_string
    text = ("Иванов, И. И. Заглавие : подзаголовок / И. И. Иванов ; "
            "Организация. — Москва : Наука, 2020. — 100 с. — Текст : непосредственный.")
    codes = {i["code"] for i in check_string(text, "7.0.100")}
    assert "space-before-punct" not in codes
    assert "colon-no-space-before" not in codes


def test_urls_are_masked_before_punctuation_checks():
    """«http://», «//» и «10.5406/» внутри URL и DOI не должны читаться
    как предписанные знаки ГОСТа."""
    from gost_ref.validate import check_string
    text = ("Иванов И. И. Заглавие // Журнал. 2020. № 1. С. 5–9. "
            "URL: http://example.ru/a//b (дата обращения: 01.02.2020). "
            "DOI 10.1234/abc.def")
    codes = {i["code"] for i in check_string(text, "7.0.5")}
    assert not {"colon-no-spaces", "colon-no-space-before",
                "slashes-no-space", "slashes-no-space-before"} & codes


# --------------------------------------------------------------------------
# Отклонения snoska.info от предписанной пунктуации
# --------------------------------------------------------------------------

SNOSKA_SAMPLE = ("Пантелеев А.С. Звездин А.Л. Векселя, взаимозачеты: бухгалтерский учет "
                 "и налогообложение. – 4-е изд. – М.: Омега-Л, 2010. – 176 с.")


def test_catches_snoska_style_deviations():
    """Образец с сайта snoska.info: инициалы слиты, двоеточие без пробела слева,
    тире между областями в подстрочной ссылке."""
    from gost_ref.validate import check_string
    codes = {i["code"] for i in check_string(SNOSKA_SAMPLE, "7.0.5")}
    assert "initials-no-space" in codes
    assert "colon-no-space-before" in codes
    assert "area-dash-in-reference" in codes


def test_same_data_our_705_output():
    out = g.format_reference(dict(
        type="book", authors="Пантелеев А. С.; Звездин А. Л.",
        title="Векселя, взаимозачеты", subtitle="бухгалтерский учет и налогообложение",
        edition="4-е изд.", city="Москва", publisher="Омега-Л",
        year="2010", total_pages="176"), "7.0.5")
    assert out == ("Пантелеев А. С., Звездин А. Л. Векселя, взаимозачеты : "
                   "бухгалтерский учет и налогообложение. 4-е изд. М. : Омега-Л, 2010. 176 с.")


def test_catches_hyphen_used_as_area_separator():
    """get6() в makelink.js возвращает ' - ' — дефис, а не тире.
    Строки из таких генераторов приходят в старых списках."""
    from gost_ref.validate import check_string
    text = ("Пантелеев А.С., Звездин А.Л. Векселя. - 4-е изд. - М.: Омега-Л, "
            "2010. - 176 с.")
    assert "hyphen-as-area-dash" in {i["code"] for i in check_string(text, "7.0.5")}


def test_catches_et_al_without_brackets():
    from gost_ref.validate import check_string
    text = "Теория государства и права / Алексеев С.С., Архипов С.И. и др. М., 1998. 496 с."
    assert "et-al-no-brackets" in {i["code"] for i in check_string(text, "7.0.5")}


def test_our_et_al_is_bracketed():
    out = g.format_reference(dict(
        type="book", authors=["Алексеев С. С.", "Архипов С. И.", "Карельский В. М.", "Игнатенко Г. В."],
        title="Теория государства и права", city="Москва", publisher="Норма",
        year="1998", total_pages="496"), "7.0.5")
    assert "[и др.]" in out


# --------------------------------------------------------------------------
# Определение типа источника
# --------------------------------------------------------------------------

@pytest.mark.parametrize("expected, raw", [
    # приметы служебных оборотов
    ("abstract", "Величковский Б. Б. Рабочая память: автореф. дис. ... д-ра психол. наук. М., 2017. 44 с."),
    ("dissertation", "Иванов И. И. Двойники: дис. ... канд. культурологии: 24.00.01. М., 2021. 210 с."),
    ("standard", "ГОСТ Р 7.0.100-2018. Библиографическая запись. М.: Стандартинформ, 2018. 124 с."),
    ("law", "Об информации: Федеральный закон № 149-ФЗ // СЗ РФ. 2006. № 31."),
    ("law", "О развитии генетических технологий: приказ Минобрнауки от 1 ноября 2019 г. № 1224."),
    ("treaty", "Конвенция об охране нематериального культурного наследия. Париж, 2003."),
    ("treaty", "Рекомендация ЮНЕСКО об охране движимых культурных ценностей. Париж, 1978."),
    ("archive", "НА РК. Ф. 480. Оп. 2. № 104/65. Л. 34."),
    ("website", "Правительство РФ: официальный сайт. URL: http://government.ru (дата обращения: 19.02.2018)."),
    # вывод по строению строки
    ("article", "Козаченко Ю. В. Клещи // Аспирант и соискатель. 2018. № 2. С. 19-21."),
    ("chapter", "Лихачев Д. С. Образ города // Историческое краеведение. Киев, 1991. С. 183-188."),
    ("webpage", "Инвестиции останутся сырьевыми // Prognosis.Ru. "
                "URL: http://prognosis.ru/news/invest.html (дата обращения: 19.03.2007)."),
    ("book", "Лихачев Д. С. Русская культура. СПб.: Искусство, 2007. 440 с."),
])
def test_type_detection(expected, raw):
    assert g.parse(raw)["fields"].get("type") == expected


@pytest.mark.parametrize("raw", [
    # служебное слово внутри заглавия не должно менять тип
    "Петров П. П. Приказы и распоряжения в делопроизводстве. М.: Дело, 2015. 180 с.",
    "Иванов И. И. Указатель имён. М., 2020. 90 с.",
    "Сидоров С. С. Конвенциональность в искусстве. СПб., 2018. 200 с.",
    "Дисней У. Искусство анимации. М.: Эксмо, 2019. 320 с.",
    "Постановкина А. А. Теория постановки голоса. М., 2019. 150 с.",
])
def test_title_words_do_not_hijack_type(raw):
    assert g.parse(raw)["fields"].get("type") == "book"


def test_url_words_do_not_hijack_type():
    """Слово из адреса не должно решать за описание."""
    raw = ("Смирнов А. А. Заглавие // Журнал. 2020. № 4. С. 10-20. "
           "URL: http://site.ru/prikaz/dissertaciya/konvenciya.html "
           "(дата обращения: 01.02.2020).")
    assert g.parse(raw)["fields"].get("type") == "article"


# --------------------------------------------------------------------------
# Тип показывается человеку и правится человеком
# --------------------------------------------------------------------------

def test_detection_is_reported_in_russian():
    out = g.reformat("Лихачев Д. С. Образ города // Историческое краеведение. Киев, 1991. С. 183-188.")
    assert out["type"] == "chapter"
    assert out["type_label"] == "глава книги или статья в сборнике"
    d = out["type_detection"]
    assert d["confidence"] == "средняя"
    assert d["reason"]
    assert {a["type"] for a in d["alternatives"]} == {"article", "webpage"}


def test_high_confidence_when_marker_found():
    out = g.reformat("Величковский Б. Б. Память: автореф. дис. ... д-ра психол. наук. М., 2017. 44 с.")
    d = out["type_detection"]
    assert d["confidence"] == "высокая"
    assert "автореф" in d["reason"]


def test_low_confidence_falls_back_to_book():
    out = g.reformat("Лихачев Д. С. Русская культура. СПб.: Искусство, 2007. 440 с.")
    assert out["type"] == "book"
    assert out["type_detection"]["confidence"] == "низкая"


def test_uncertain_type_adds_a_note():
    out = g.reformat("Лихачев Д. С. Образ города // Историческое краеведение. Киев, 1991. С. 183-188.")
    assert any("Тип определён как" in n for n in out["parse_notes"])
    assert "how_to_override" in out


def test_type_override_changes_the_result():
    raw = "Лихачев Д. С. Образ города // Историческое краеведение. Киев, 1991. С. 183-188."
    as_chapter = g.reformat(raw, "7.0.100")
    as_article = g.reformat(raw, "7.0.100", type_override="article")
    assert as_chapter["reference"] != as_article["reference"]
    assert as_article["type_label"] == "статья в журнале"
    assert as_article["type_detection"]["confidence"] == "задано вручную"
    # подсказку про правку не показываем тому, кто уже поправил
    assert "how_to_override" not in as_article


def test_unknown_override_is_refused_with_the_list():
    out = g.reformat("Заглавие. М., 2020.", type_override="книжка")
    assert "error" in out
    assert "book" in out["known_types"]


def test_format_reference_reports_type_label():
    out = g.format_and_check(dict(type="abstract", title="Заглавие", city="Москва", year="2020"))
    assert out["type_label"] == "автореферат диссертации"


# --------------------------------------------------------------------------
# Регрессии, найденные на настоящем списке литературы
# (списки восьми статей КиберЛенинки, 71 запись, eval/cyberleninka_refs.json)
# --------------------------------------------------------------------------

def test_list_number_does_not_swallow_the_author():
    """Главный провал первого прогона: «1. », «[3] », «11 » в начале записи
    блокировали опознание заголовка, и автор целиком уезжал в заглавие."""
    for raw in ("1. Баруткина Л.П. Мультимедиа в музейной экспозиции // Вестник. 2011. № 4. С. 106-108.",
                "[2] Ванеева О.В. Интерактивные технологии // Труды. 2015. № 212. С. 189-196.",
                "12) Бородкин Л.И. Виртуальная реконструкция // Вестник. 2014. № 3. С. 1-9."):
        f = g.parse(raw)["fields"]
        assert f.get("list_number")
        assert f["authors"], raw
        assert not f["title"].startswith(("1.", "[2]", "12"))


def test_ocr_glued_surname_and_initials():
    """PDF склеивает фамилию с инициалом: «СурковаК.В.», «АбишеваВ.Т.»."""
    f = g.reformat("СурковаК.В. Образование в контексте виртуализации музея "
                   "// Музейная эпистема. СПб., 2009.")["fields"]
    assert f["authors"][0]["surname"] == "Суркова"
    assert f["authors"][0]["initials"] == "К. В."
    assert f["title"] == "Образование в контексте виртуализации музея"


def test_editor_after_slash_is_not_an_author():
    f = g.reformat("Словарь актуальных музейных терминов / под ред. М.Е. Каулен, "
                   "А.А. Сундиева // Музей. 2009. № 5.")["fields"]
    assert not f.get("authors")
    assert [p["surname"] for p in f["editors"]] == ["Каулен", "Сундиева"]
    assert f["title"] == "Словарь актуальных музейных терминов"


def test_compiler_after_slash():
    f = g.reformat("Звонарская тетрадь / сост.: Т. В. Липкина, А. В. Талашкин. "
                   "- Новосибирск: Твердый знак, 2013. - 150 с.")["fields"]
    assert not f.get("authors")
    assert [p["surname"] for p in f["compilers"]] == ["Липкина", "Талашкин"]


def test_imprint_separated_by_dash():
    """Стиль ГОСТ 7.1: «. - Город: Издательство. - Год. - N с.»"""
    f = g.parse("1. Барбан Е.С. Джазовые опыты. - Санкт-Петербург: Композитор. "
                "- 2007. - 336 с.")["fields"]
    assert f["city"] == "Санкт-Петербург"
    assert f["publisher"] == "Композитор"
    assert f["year"] == "2007" and f["total_pages"] == "336"
    assert f["title"] == "Джазовые опыты"


def test_abbreviated_city_keeps_its_period():
    f = g.parse("1. Горохов В. А. Колокола земли Русской. - М.: Вече, 2009. - 320 с.")["fields"]
    assert f["city"] == "М."
    assert f["publisher"] == "Вече"
    out = g.format_reference(f, "7.0.100")
    assert "Москва : Вече, 2009" in out


def test_year_inside_a_quoted_title_is_not_an_imprint_year():
    """«The War of 1812» — часть заглавия, а не год издания."""
    f = g.parse('Virtual Museum «The War of 1812». URL: https://example.org '
                '(дата обращения: 10.10.2015).')["fields"]
    assert "year" not in f
    assert f["title"] == "Virtual Museum «The War of 1812»"


def test_edition_keeps_its_qualifiers():
    f = g.parse("5. Оловянишников Н. И. История колоколов. - 2-е изд., доп. "
                "- М.: Т-во П. И. Оловянишникова и сыновей, 1912. - 456 с.")["fields"]
    assert f["edition"] == "2-е изд., доп."
    assert f["title"] == "История колоколов"


def test_hyphen_inside_a_title_survives():
    """« - » — разделитель областей только перед годом, номером, страницами
    или городом. Перед строчной буквой это тире внутри заглавия."""
    f = g.parse("[3] Долак Я. Музейная экспозиция - музейная коммуникация "
                "// Вопросы музеологии. - 2010, № 1. -С. 106-107.")["fields"]
    assert f["title"] == "Музейная экспозиция - музейная коммуникация"
    assert f["container"] == "Вопросы музеологии"
    assert f["year"] == "2010" and f["issue"] == "1" and f["pages"] == "106–107"


def test_dissertation_word_is_not_torn_apart():
    f = g.parse("4. Мозгот С.А. Категория пространства в музыкальном искусстве: "
                "диссертация ... докт. искусствоведения: 17.00.02 / "
                "Мозгот Светлана Анатольевна. - Новосибирск. - 2018. - 366 с.")["fields"]
    assert f["type"] == "dissertation"
    assert f["specialty"] == "17.00.02"
    assert "искусствоведения" in f["degree"]
    assert "диссертац" not in f["title"] and "ия." not in f["title"]


def test_page_of_a_website_needs_no_year():
    """У страницы сайта года издания нет по природе — это не пропуск."""
    report = g.validate(dict(type="webpage", title="Заглавие",
                             url="http://example.ru", access_date="01.02.2020"))
    assert not any(w["code"] == "no-year" for w in report["warnings"])


# --------------------------------------------------------------------------
# Регрессии с выверенного списка (диссертация, ГОСТ Р 7.0.100-2018,
# 200 записей — eval/corpus_diss.json)
# --------------------------------------------------------------------------

def test_extent_survives_the_area_dash():
    """«— 250 с. — Текст : непосредственный»: запрет «не перед тире» отсекал
    сам разделитель областей и терял объём у каждой второй записи."""
    f = g.parse("Иванов, И. И. Заглавие / И. И. Иванов. – Москва : Наука, 2020. "
                "– 250 с. – Текст : непосредственный.")["fields"]
    assert f["total_pages"] == "250"
    assert f["city"] == "Москва" and f["publisher"] == "Наука"


def test_specialty_clause_parsed_whole():
    """Оборот «: специальность 09.00.11 «Название»» разбирается целиком,
    иначе форматтер добавлял свой второй такой же."""
    f = g.parse("Канныкин, С. В. Бытие текста в культуре : специальность 09.00.11 "
                "«Социальная философия» : автореф. дис. … канд. филос. наук / "
                "Канныкин С. В. – Воронеж, 2001. – 24 с.")["fields"]
    assert f["type"] == "abstract"
    assert f["specialty"] == "09.00.11"
    assert f["specialty_name"] == "Социальная философия"
    assert f["title"] == "Бытие текста в культуре"
    out = g.format_reference(f, "7.0.100")
    assert out.count("специальность") == 1


def test_single_char_ellipsis_in_dissertation():
    """«дис. …» одним знаком, а не тремя точками."""
    f = g.parse("Ананьев, В. Г. Зарубежная музеология : специальность 24.00.03 "
                "«Музееведение» : дис. … д-ра ист. наук / Ананьев Виталий "
                "Геннадиевич ; СПбГУ. — Санкт-Петербург, 2018. — 400 с.")["fields"]
    assert f["type"] == "dissertation"
    assert f["title"] == "Зарубежная музеология"
    assert f["institution"] == "СПбГУ"


def test_all_authors_from_the_responsibility_statement():
    """В заголовке стоит только первый автор; полный перечень — после « / »."""
    f = g.reformat("Корнилова, К. С. Аудитория музеев / К. С. Корнилова, "
                   "П. С. Громова. — Текст : непосредственный // Вестник. "
                   "— 2020. — № 4. — С. 10–20.")["fields"]
    assert [p["surname"] for p in f["authors"]] == ["Корнилова", "Громова"]


def test_translator_group_is_kept():
    f = g.reformat("Бауман, З. Текучая современность / З. Бауман ; "
                   "[пер. с англ. С. А. Комаров]. — Санкт-Петербург : Питер, "
                   "2008. — 240 с.")["fields"]
    assert f["translators"][0]["surname"] == "Комаров"
    assert [p["surname"] for p in f["authors"]] == ["Бауман"]


def test_double_slash_typo_before_responsibility():
    """«Заглавие // И. О. Фамилия. — … // Журнал» — первое «//» опечатка."""
    out = g.reformat("Именнова, Л. С. Музей в информационную эпоху // Л. С. Именнова. "
                     "– Текст : непосредственный // Вестник МГУКИ. – 2010. – № 6. "
                     "– С. 39–45.")
    assert out["fields"]["container"] == "Вестник МГУКИ"
    assert any("два «//»" in n for n in out["parse_notes"])


# --------------------------------------------------------------------------
# Область вида содержания факультативна
# --------------------------------------------------------------------------

def test_content_type_can_be_omitted():
    """ГОСТ Р 7.0.100-2018 делит элементы на обязательные, условно обязательные
    и факультативные; область вида содержания в обязательные не входит."""
    fields = dict(type="book", authors="Иванов И. И.", title="Заглавие",
                  city="Москва", publisher="Наука", year="2024", total_pages="240")
    with_area = g.format_reference(fields, "7.0.100", content_type=True)
    without = g.format_reference(fields, "7.0.100")   # по умолчанию не выводится
    assert with_area.endswith("— Текст : непосредственный.")
    assert "Текст :" not in without
    assert without.endswith("— 240 с.")


def test_missing_content_type_is_a_note_not_an_error():
    fields = dict(type="book", authors="Иванов И. И.", title="Заглавие",
                  city="Москва", publisher="Наука", year="2024", total_pages="240")
    report = g.format_and_check(fields, "7.0.100", content_type=False)
    assert report["ok"], "отсутствие факультативного элемента — не ошибка"
    assert not any(e["code"] == "no-content-type" for e in report["errors"])
    assert any(n["code"] == "no-content-type" for n in report["notes"])


def test_medium_conflict_is_still_an_error():
    """Факультативность области не отменяет запрета на противоречие:
    если область выведена, она должна отражать действительность."""
    report = g.validate(dict(type="book", title="Заглавие", city="Москва",
                             year="2024", url="http://example.ru",
                             access_date="01.02.2024", medium="print"))
    assert any(e["code"] == "medium-conflict" for e in report["errors"])


def test_content_type_is_off_by_default():
    """Факультативный элемент не ставится, пока его не потребовали."""
    fields = dict(type="book", authors="Иванов И. И.", title="Заглавие",
                  city="Москва", publisher="Наука", year="2024", total_pages="240")
    assert "Текст :" not in g.format_reference(fields, "7.0.100")


def test_area_dash_absence_is_only_a_note():
    """П. 4.6.4 ГОСТ Р 7.0.100-2018 разрешает заменять «точку и тире» точкой."""
    from gost_ref.validate import check_string
    issues = check_string("Иванов, И. И. Заглавие. Москва : Наука, 2024. 240 с.", "7.0.100")
    dash = [i for i in issues if i["code"] == "no-area-dash"]
    assert dash and dash[0]["level"] == "note"


def test_abbreviated_city_is_a_warning_not_an_error():
    from gost_ref.validate import check_string
    issues = check_string("Иванов, И. И. Заглавие. — М.: Наука, 2024. — 240 с.", "7.0.100")
    city = [i for i in issues if i["code"] == "abbreviated-city"]
    assert city and city[0]["level"] == "warning"


def test_nothing_is_invented_when_data_is_missing():
    """Пустое поле остаётся пустым, а недостача попадает в замечания."""
    r = g.format_and_check(dict(type="book", authors="Иванов И. И.",
                                title="Заглавие"), "7.0.100")
    assert r["reference"] == "Иванов, И. И. Заглавие / И. И. Иванов."
    codes = {w["code"] for w in r["warnings"]}
    assert {"no-year", "no-city", "no-publisher", "no-extent"} <= codes


# --------------------------------------------------------------------------
# Сноска и запись выдаются парой
# --------------------------------------------------------------------------

def test_pair_returns_footnote_and_record():
    """Поля одни и те же, формы разные — спрашивать «сноска или список» незачем."""
    r = g.format_pair(dict(type="article", authors="Козаченко Ю. В.",
                           title="Клещи", container="Аспирант и соискатель",
                           year="2018", issue="2", pages="19-21"))
    assert r["footnote"]["standard"] == "7.0.5"
    assert r["record"]["standard"] == "7.0.100"
    # сноска без тире областей, запись — с ними
    assert "—" not in r["footnote"]["text"]
    assert "—" in r["record"]["text"]
    assert r["type_label"] == "статья в журнале"


def test_pair_uses_700108_for_network_sources():
    r = g.format_pair(dict(type="webpage", title="Заглавие",
                           container="Сайт", url="http://example.ru",
                           access_date="01.02.2024"))
    assert r["footnote"]["standard"] == "7.0.108"


def test_pair_can_use_71_for_the_record():
    r = g.format_pair(dict(type="book", authors="Иванов И. И.", title="Заглавие",
                           city="Москва", publisher="Наука", year="2024",
                           total_pages="240"), record_standard="7.1")
    assert r["record"]["standard"] == "7.1"
    assert "[Текст]" in r["record"]["text"]


# ---------------------------------------------------------------------------
# Обозначение нормативного акта из раздельных полей
#
# Дефект, найденный на приказе Минкультуры № 827: номер и дата, поданные
# полями doc_number/adopted, вставали в записи вторым двоеточием
# («: 827 : 23.07.2020»), а из сетевой сноски пропадали вовсе — форматтер
# 7.0.108 их вообще не читал.
# ---------------------------------------------------------------------------

from gost_ref.text import act_designation, title_with_designation


def test_designation_bare_fields_get_prefixes():
    assert act_designation("827", "23.07.2020") == "от 23.07.2020 № 827"


def test_designation_keeps_already_formatted_values():
    assert act_designation("№ 827", "от 23.07.2020") == "от 23.07.2020 № 827"


def test_designation_verb_form_goes_in_brackets_after_number():
    assert act_designation("827", "принят Государственной Думой 21.07.2020") == \
        "№ 827 (принят Государственной Думой 21.07.2020)"


def test_designation_single_field():
    assert act_designation("131-ФЗ", "") == "№ 131-ФЗ"
    assert act_designation("", "06.10.2003") == "от 06.10.2003"
    assert act_designation("", "") == ""


def test_designation_attaches_to_subtitle_without_colon():
    assert title_with_designation("Об утверждении Правил", "приказ Минкультуры",
                                  "827", "23.07.2020") == \
        "Об утверждении Правил : приказ Минкультуры от 23.07.2020 № 827"


def test_law_designation_identical_across_standards():
    fields = {"type": "law", "title": "Об объектах культурного наследия",
              "subtitle": "Федеральный закон",
              "doc_number": "73-ФЗ", "adopted": "25.06.2002"}
    tail = "Федеральный закон от 25.06.2002 № 73-ФЗ"
    for key in ("7.0.5", "7.0.100", "7.1"):
        assert tail in g.format_reference(fields, key), key


def test_law_designation_survives_network_footnote():
    # Сетевая сноска идёт по 7.0.108 — раньше обозначение там терялось.
    out = g.format_pair({
        "type": "law", "title": "Об утверждении Единых правил",
        "subtitle": "приказ Министерства культуры Российской Федерации",
        "doc_number": "827", "adopted": "23.07.2020", "year": "2020",
        "container": "Министерство культуры Российской Федерации",
        "container_subtitle": "официальный сайт",
        "url": "https://culture.gov.ru/documents/pravila/",
        "access_date": "17.08.2026",
    })
    assert out["footnote"]["standard"] == "7.0.108"
    for form in ("footnote", "record"):
        assert "от 23.07.2020 № 827" in out[form]["text"], form
        assert " : 827 " not in out[form]["text"], form


def test_standard_designation_stays_before_title_in_network_reference():
    out = g.format_reference({
        "type": "standard", "doc_number": "ГОСТ Р 56891.2-2016",
        "title": "Сохранение объектов культурного наследия",
        "url": "https://protect.gost.ru/document.aspx?id=203312",
        "access_date": "03.09.2026",
    }, "7.0.108")
    assert out.startswith("ГОСТ Р 56891.2-2016. Сохранение")
