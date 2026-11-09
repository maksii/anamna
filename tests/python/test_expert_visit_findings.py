"""Expert Hospital visit notes, as findings.

Synthetic text in the shape of the in-app records Anamna composes into a PDF
for Expert Hospital (title, «Лікар: …», the «Складено Anamna …» line that runs
to the page's width, then «Скарги:», «Анамнез:», «Огляд:», «Діагноз:»,
«Рекомендації:»).  Each test is one shape a reviewer found mis-read: an ENT
diagnosis filed under the lungs, a headache visit filed under the heart by its
normal examination, a pre-operative note filed under the kidneys, a quoted
breath test taken for the visit's conclusion, recommendations glued together
or cut short, and a line of advice dropped because it contained the patient's
first name.  Names and dates are invented.
"""
from anamna.health import (
    _clean_block,
    _complaints_span,
    _conclusion_span,
    _diagnosis_areas,
    _extract_recommendations,
    _report_filing,
    _report_summary,
    _strip_letterhead,
)
from anamna.ingest.text import search_key

from test_clinical_findings import add_report, findings, ledger  # noqa: F401

COMPOSED = (
    "Лікарня «Експерт» · Expert Hospital\nДата: 08.02.2025\nЛікар: Тестенко Олена Іванівна ({specialty})\n"
    "Складено Anamna із запису висновку c0000001 в застосунку Лікарні «Експерт»; файлу клініка не\n"
    "видала. / Composed by Anamna from Expert Hospital's in-app record c0000001; the clinic issued no file.\n"
)


def note(title: str, specialty: str, body: str) -> str:
    return f"{title}\n{COMPOSED.format(specialty=specialty)}{body}"


def read(title: str, text: str) -> tuple[str, str, tuple[str, str, tuple[str, ...]]]:
    """(summary, recommendations, filing) the way `_report_candidate` reads a consultation."""
    span = _conclusion_span(text, "consultation") or _complaints_span(text)
    summary = _report_summary(text, span)
    recommendations = _extract_recommendations(text, span[2]) if span else ""
    filing = _report_filing({"document_title": title, "original_filename": ""}, "consultation", text, span, summary)
    return summary, recommendations, filing


# --- 1. ENT: the upper airway is not the lungs ---------------------------------

def test_upper_airway_codes_and_nose_words_are_ent_and_the_lower_airway_stays_lungs():
    assert _diagnosis_areas("J31.0 Хронічний риніт") == ("ent",)
    assert _diagnosis_areas("J35.0 Хронічний тонзиліт") == ("ent",)
    assert _diagnosis_areas("J34.2 Зміщена носова перегородка") == ("ent",)
    assert _diagnosis_areas("викривлення носової перегородки") == ("ent",)
    assert _diagnosis_areas("H65.0 Гострий середній отит") == ("ent",)
    assert _diagnosis_areas("J20.9 Гострий бронхіт") == ("lungs",)
    # The skin of the ear or the nose is the dermatologist's.
    assert _diagnosis_areas("L82 - Себорейний кератоз , кератома лівої вушної раковини") == ("skin",)


def test_an_ent_visit_with_only_an_examination_is_filed_under_ent():
    title = "Консультація отоларинголога"
    text = note(title, "Отоларинголог", (
        "Скарги:\nзатруднення носового дихання, виділення з носа слизистого характеру,нічний\nхрап\n"
        "Анамнез:\nХворіє протягом тривалого часу\n"
        "Огляд:\nПереділка носа викривлена, S- подібної форми, слизова оболонка носа\n"
        "блідо-рожева, набрякла. Носові раковини гіпертрофовані.\n"
        "Рекомендації:\nКТ носа та додаткових пазух\n"
    ))
    summary, recommendations, filing = read(title, text)
    assert filing == ("consult_ent", "ENT consultation", ("ent",))
    assert summary.startswith("Скарги: затруднення носового дихання") and "Огляд: Переділка носа викривлена" in summary
    assert recommendations == "КТ носа та додаткових пазух"


def test_an_ent_diagnosis_on_a_discharge_summary_is_ent(ledger):  # noqa: F811
    settings, owner, patient = ledger
    text = note("Виписка зі стаціонару Ehealth", "Хірург", "Діагноз:\nJ34.2 Зміщена носова перегородка\n")
    add_report(settings, owner, patient, "discharge", "clinical_report", "Виписка зі стаціонару Ehealth", [text])
    [row] = [row for row in findings(settings) if row["document_id"] == "discharge"]
    assert row["health_area"] == "ent"
    # The document's own title is not letterhead.
    assert row["original_text"].startswith("Виписка зі стаціонару Ehealth")


# --- 2. Specialties, and a specialty's own area over its complaints -------------

def test_rheumatology_endoscopy_and_anaesthesia_have_their_own_titles():
    def title_of(title, specialty, body):
        return read(title, note(title, specialty, body))[2][:2]

    assert title_of("Консультація ревматолога", "Ревматолог", "Діагноз:\nM25.5 Біль в суглобі\n") == (
        "consult_rheumatology", "Rheumatology consultation")
    assert title_of("Консультація ендоскопіста", "Ендоскопіст",
                    "Діагноз:\nЯвища термінального ілеїту. Поліпи прямої кишки.\n") == ("consult_endoscopy", "Endoscopy")
    assert title_of("Консультація анестезіолога", "Анестезіолог", "Діагноз:\nвикривлення носової перегородки\n") == (
        "consult_anaesthesia", "Pre-operative anaesthesia assessment")


def test_a_gastroenterology_visit_without_a_diagnosis_is_not_filed_under_the_brain_by_a_headache():
    title = "Консультація гастроентеролога"
    text = note(title, "Гастроентеролог", "Скарги:\nіноді печія та головний біль\nАнамнез:\nхворіє довготривало.\n")
    summary, _, filing = read(title, text)
    assert summary == "Скарги: іноді печія та головний біль"
    assert filing == ("consult_gastro", "Gastroenterology consultation", ("digestive",))


def test_pancreatitis_and_pancreatic_insufficiency_are_under_liver_and_pancreas():
    assert "liver" in _diagnosis_areas("Хронічний панкреатит . Синдром надмірного бактеріального росту у кишківнику.")
    assert "liver" in _diagnosis_areas("Панкреатична еластаза в калі - 45,83 ( норма від 200 )")


# --- 3. No diagnosis written: complaints first, the exam never files ------------

HEADACHE = note("Консультація терапевта", "Терапевт", (
    "Скарги:\nперіодичний біль голови, тиск у скронях з обох боків.\n"
    "Анамнез:\nвважає себе хворою декілька місяців.\n"
    "Огляд:\nслизові зіву блідо-рожеві, ЧД - 16/хв, тони серця звучні, ритмічні, ЧСС -\n78/хв.\nЖивіт не болючий.\n"
    "Рекомендації:\n1). ЗАК з формулою.\n2). Консультація невропатолога.\n"
))


def test_a_headache_visit_is_filed_by_its_complaints_not_by_its_normal_heart_sounds():
    summary, recommendations, filing = read("Консультація терапевта", HEADACHE)
    assert summary == (
        "Скарги: періодичний біль голови, тиск у скронях з обох боків. "
        "Огляд: слизові зіву блідо-рожеві, ЧД - 16/хв, тони серця звучні, ритмічні, ЧСС - 78/хв. Живіт не болючий."
    )
    assert filing == ("consult_gp", "General practitioner consultation", ("brain",))
    assert recommendations == "1). ЗАК з формулою. 2). Консультація невропатолога."


def test_a_specialist_visit_reads_its_complaints_before_its_examination():
    title = "Консультація ревматолога"
    text = note(title, "Ревматолог", (
        "Скарги:\nCкарги на болі в колінних суглобах після тривалого перебування у незмінній позі,\n"
        "оніміння в/н кінцівках.\nАнамнез:\nСкарги відмітив 2 роки тому.\n"
        "Огляд:\nШкіра блідо-рожева, чиста. Дефігурації та деформації суглобів - відсутні.\n"
        "Рекомендації:\n1.Повторна консультація після дообстеження.\n"
    ))
    summary, _, filing = read(title, text)
    assert summary.startswith("Скарги: Cкарги на болі в колінних суглобах")
    assert summary.endswith("Огляд: Шкіра блідо-рожева, чиста. Дефігурації та деформації суглобів - відсутні.")
    assert filing == ("consult_rheumatology", "Rheumatology consultation", ("joints",))


def test_complaints_that_say_nothing_leave_the_examination_as_the_summary():
    title = "Консультація гастроентеролога"
    text = note(title, "Гастроентеролог", (
        "Скарги:\nутримуються.\nАнамнез:\nв анамнезі Гастрит.\n"
        "Огляд:\nКопрограма від 18.05.2026р: кал неоформлений.\nРекомендації:\n1. Дотримання режиму харчування.\n"
    ))
    assert read(title, text)[0] == "Копрограма від 18.05.2026р: кал неоформлений."


PRE_OP = note("Консультація анестезіолога", "Анестезіолог", (
    "Скарги:\nнемає\n"
    "Анамнез:\nГХ І ст 2 ст ризик помірний. Палить 20 цигарок на день.\n"
    "-септопластика,загальна анестезія, пацієнт планується на оперативне втручання -\n"
    "висічення аноректальної нориці,ВКС, не застрахований\n"
    "Огляд:\nЗагальний стан задовільний. Зріст 185 см, вага 109 кг.\n"
    "В легенях аускультативно дихання везикулярне,хрипів немає. Сечовипускання самостійне.\n"
    "Ступень операційно-анестезіологічного ризику АSA ІІ. Планується в/венна анестезія\nзі igel-повітреводом.\n"
    "Рекомендації:\n1)еластична компресія н/кінцівок\n2)не пити за 3 години до операції\n3)не їсти за 12 годин до операції\n"
))


def test_a_pre_operative_note_reads_its_risk_grade_and_is_filed_by_the_planned_operation():
    summary, recommendations, filing = read("Консультація анестезіолога", PRE_OP)
    assert summary == "Ступень операційно-анестезіологічного ризику АSA ІІ. Планується в/венна анестезія зі igel-повітреводом."
    # Never the kidneys of «Сечовипускання самостійне» or the lungs of a normal auscultation.
    assert filing == ("consult_anaesthesia", "Pre-operative anaesthesia assessment", ("digestive",))
    assert recommendations == (
        "1)еластична компресія н/кінцівок; 2)не пити за 3 години до операції; 3)не їсти за 12 годин до операції"
    )


def test_the_pre_operative_note_is_one_digestive_finding(ledger):  # noqa: F811
    settings, owner, patient = ledger
    add_report(settings, owner, patient, "preop", "consultation", "Консультація анестезіолога", [PRE_OP])
    rows = [row for row in findings(settings) if row["document_id"] == "preop"]
    assert [(row["health_area"], row["title"]) for row in rows] == [("digestive", "Pre-operative anaesthesia assessment")]


# --- 4. A one-letter word in clean text is a word -------------------------------

def test_a_letter_naming_a_shape_is_kept_and_ocr_edge_debris_still_goes():
    assert _clean_block("С подібний сколіоз хребта.") == "С подібний сколіоз хребта."
    assert _clean_block("S подібна деформація.") == "S подібна деформація."
    assert _clean_block("ої збагачений за рахунок судинного компоненту. Корені\nС структурні.") == (
        "збагачений за рахунок судинного компоненту. Корені структурні."
    )


# --- 5. A study quoted under the examination is not the visit's conclusion ------

def test_a_breath_test_quoted_under_the_examination_is_not_the_conclusion():
    title = "Консультація гастроентеролога"
    for wrap in (" ", "\n"):
        text = note(title, "Гастроентеролог", (
            "Скарги:\nна періодичне відчуття дискомфорту в ділянці живота, здуття.\n"
            "Анамнез:\nпогіршення стану відмічає близько 1 міс.\n"
            "Огляд:\nОб-но: Живіт при пальпації мякий, здутий.\n"
            "Дихальний тест на визначення надмірного бактерійного росту у кишківнику від\n"
            f"25.09.24р:{wrap}Висновок: надмірного бактерійного росту у кишківнику не виявлено.\n"
            "Панкреатична еластаза в калі - 45,83 ( норма від 200 ) .\n"
            "Рекомендації:\n1. Дотримання режиму харчування.\n"
        ))
        summary, _, filing = read(title, text)
        assert summary.startswith("Скарги: на періодичне відчуття дискомфорту"), wrap
        assert "Дихальний тест на визначення надмірного бактерійного росту у кишківнику від 25.09.24р" in summary
        assert filing[2] == ("digestive", "liver")


# --- 6. Recommendations: one item per line, never split inside a bracket -------

def recommendations_of(specialty: str, advice: str) -> str:
    text = note("Консультація", specialty, f"Діагноз:\nZ71.8 Інше уточнене консультування\nРекомендації:\n{advice}")
    return read("Консультація", text)[1]


def test_a_wrapped_brand_name_inside_its_bracket_is_one_item():
    assert recommendations_of("Отоларинголог", (
        "1. Промивання носа ізотонічним сольовим розчином 3-4 р/д ( Хьюмер, Пшик, Аква\nМарис)\n"
        "Зволоження приміщення 50-60%\n"
    )) == "1. Промивання носа ізотонічним сольовим розчином 3-4 р/д ( Хьюмер, Пшик, Аква Марис); Зволоження приміщення 50-60%"


def test_numbered_items_are_kept_apart_with_or_without_a_space_after_the_number():
    assert recommendations_of("Алерголог", "1. Обмежити прості вуглеводи\n2.Безлактоза дієта 3 тижні\n3) Виключити молочку\n") == (
        "1. Обмежити прості вуглеводи; 2.Безлактоза дієта 3 тижні; 3) Виключити молочку"
    )


def test_lower_case_items_on_short_lines_are_kept_apart_and_a_wrapped_line_is_joined():
    assert recommendations_of("Ортопед", (
        "спостереження\nмрт колін та поперекового та грудного відділу хребта\n"
        "серрата 1 т 3 р на день 30 днів\nаплікатор КУзнецова\nмасаж та лфк\n"
    )) == ("спостереження; мрт колін та поперекового та грудного відділу хребта; серрата 1 т 3 р на день 30 днів; "
           "аплікатор КУзнецова; масаж та лфк")
    assert recommendations_of("Кардіолог", "Аторис 20мг 1т 1р ввечері\nконтроль ліпідограми через 8 тижнів\n") == (
        "Аторис 20мг 1т 1р ввечері; контроль ліпідограми через 8 тижнів"
    )
    # A line that ran to the page's width wrapped; one opening on «та» continues.
    assert recommendations_of("Гастроентеролог", (
        "Харчування збалансоване, раціональне, за методом \"здорової тарілки\", їжа овочі і\n"
        "різноманітна (щодня овочі і зелень).\nКонсультації спеціалістів\nта інструментальні методи обстеження\n"
    )) == ("Харчування збалансоване, раціональне, за методом \"здорової тарілки\", їжа овочі і різноманітна "
           "(щодня овочі і зелень); Консультації спеціалістів та інструментальні методи обстеження")


def test_a_line_ending_in_a_full_stop_ends_its_item():
    assert recommendations_of("Ревматолог", (
        "Раціональне харчування. Контроль маси тіла. Консультація дієтолога.\n"
        "Таб. Ексіб 90 мг 1 раз на день у разі болю.\nПовторна консультація після дообстеження.\n"
    )) == ("Раціональне харчування. Контроль маси тіла. Консультація дієтолога; "
           "Таб. Ексіб 90 мг 1 раз на день у разі болю; Повторна консультація після дообстеження.")


def test_a_wrapped_last_word_after_a_figure_is_kept():
    assert recommendations_of("Терапевт", (
        "Дексалгін саше: по 1 саше, 3 раз в 1 День (дні), 01.01.2024–07.01.2024, на курс 21\nсаше\n"
    )).endswith("на курс 21 саше")


def test_the_treatment_plan_under_its_own_heading_is_kept_and_a_wrapped_word_in_the_history_starts_nothing():
    title = "Консультація гастроентеролога"
    text = note(title, "Гастроентеролог", (
        "Скарги:\nіноді печія\nАнамнез:\nтакож у лютому консультований кардіологом - надані профільні\n"
        "рекомендації.\nобстеження від 2.08.2025 :\n-ниркові проби :норма\n"
        "Рекомендації:\n1.модифікація способу життя( рекомендації надано)\n4.медикаментозне лікування:\n"
        "- нольпаза ( пантопразол) 40мг 2р/ добу\n-урсіс 500мг 1 капс перед сном\n"
    ))
    assert read(title, text)[1] == (
        "1.модифікація способу життя( рекомендації надано); 4.медикаментозне лікування: "
        "- нольпаза ( пантопразол) 40мг 2р/ добу -урсіс 500мг 1 капс перед сном"
    )
    # Form 028/о's empty medication table under a heading of its own still ends the advice.
    table = ("Рекомендовано:\n- плавання\n- коректор постави носити по 1-2 год на день\n"
             "Медикаментозне лікування\nМедикамент К-сть План лікування\n")
    assert _extract_recommendations(table) == "плавання - коректор постави носити по 1-2 год на день"


# --- 7. The patient's name, as a whole word --------------------------------------

def test_a_word_that_contains_the_first_name_is_not_the_name():
    identity = (search_key("Марк"), search_key("Тестенко"), "01.03.1990")
    text = "Онкомаркери в нормі.\nПацієнт Марка Тестенка оглянуто.\nКонтроль через місяць.\nНароджений 01.03.1990р."
    assert _strip_letterhead(text, identity) == "Онкомаркери в нормі.\nКонтроль через місяць."


# --- 8. Letterhead: the document's title stays, a wrapped doctor's line goes whole

def test_a_wrapped_doctor_line_leaves_no_orphan_and_the_ehealth_title_stays():
    text = (
        "Консультація сімейного лікаря EHealth\nЛікарня «Експерт» · Expert Hospital\nДата: 09.02.2025\n"
        "Лікар: Тестенко Олена Іванівна (Завідувач поліклініки, Сімейний лікар, Терапевт,\nПедіатр)\n"
        "Огляд:\nЗагальний стан - задовільний.\n"
    )
    assert _strip_letterhead(text) == (
        "Консультація сімейного лікаря EHealth\nЛікарня «Експерт» · Expert Hospital\nДата: 09.02.2025\n"
        "Огляд:\nЗагальний стан - задовільний."
    )
    # An order sheet's column header is still form furniture.
    assert _strip_letterhead("Назва послуги К-сть Дата Ehealth\nКонсультація кардіолога 1") == "Консультація кардіолога 1"


# --- 9. An area is given whole sentences ------------------------------------------

def test_each_area_gets_whole_sentences_and_a_dash_never_parts_them(ledger):  # noqa: F811
    settings, owner, patient = ledger
    text = note("Консультація гастроентеролога", "Гастроентеролог", (
        "Діагноз:\nХронічний панкреатит . Синдром надмірного бактеріального росту у\n"
        "кишківнику.Дисбіоз кишківника ( виявлено Staphylococcus epidermidis/, елементи\n"
        "гриба , подібного до дріжджевого - у великій кількості).\nРекомендації:\n1. Копрограма .\n"
    ))
    add_report(settings, owner, patient, "pancreatitis", "consultation", "Консультація гастроентеролога", [text])
    by_area = {row["health_area"]: row["summary_uk"] for row in findings(settings) if row["document_id"] == "pancreatitis"}
    assert by_area == {
        "liver": "Хронічний панкреатит.",
        "digestive": "Синдром надмірного бактеріального росту у кишківнику. Дисбіоз кишківника ( виявлено "
                     "Staphylococcus epidermidis/, елементи гриба , подібного до дріжджевого - у великій кількості).",
    }


def test_a_pancreas_result_inside_an_examination_stays_with_its_value(ledger):  # noqa: F811
    settings, owner, patient = ledger
    text = note("Консультація гастроентеролога", "Гастроентеролог", (
        "Скарги:\nна періодичне відчуття дискомфорту в ділянці живота, здуття.\n"
        "Анамнез:\nпогіршення стану відмічає близько 1 міс.\n"
        "Огляд:\nОб-но: Живіт при пальпації мякий, здутий.\n"
        "Копрограма від 25.09.24р: кал оформлений, клітковина. йодофільна флора, крохмаль.слиз.\n"
        "Панкреатична еластаза в калі - 45,83 ( норма від 200 ) .\nРекомендації:\n1. Дотримання режиму харчування.\n"
    ))
    add_report(settings, owner, patient, "elastase", "consultation", "Консультація гастроентеролога", [text])
    by_area = {row["health_area"]: row["summary_uk"] for row in findings(settings) if row["document_id"] == "elastase"}
    assert by_area["liver"] == "Панкреатична еластаза в калі - 45,83 ( норма від 200 )."
    assert by_area["digestive"].endswith("крохмаль.слиз.") and "45,83" not in by_area["digestive"]


def test_one_sentence_listing_two_organs_is_still_parted_between_them():
    from anamna.health import _area_finding

    summary = ("На момент огляду УЗ ознаки- дифузних змін печінки і підшлункової залози "
               "-незначні сольові нашарування в нирках без порушення уродинаміки")
    item = {"areas": ("liver", "kidneys"), "summary": summary, "summary_en": "", "summary_uk": summary}
    assert _area_finding(item, "liver")["summary_uk"] == (
        "На момент огляду УЗ ознаки- дифузних змін печінки і підшлункової залози")
    kidneys = _area_finding(item, "kidneys")
    assert kidneys["summary_uk"] == "незначні сольові нашарування в нирках без порушення уродинаміки"
    # The liver's diffuse changes put no kidney under attention.
    assert kidneys["status"] == "information"


def test_a_coded_diagnosis_goes_to_the_area_its_code_names():
    from anamna.health import _area_finding, _diagnosis_areas

    summary = "E78.2 - Змішана гіперліпідемія. E04.1 Нетоксичний одновузловий зоб."
    item = {"areas": ("heart", "thyroid"), "summary": summary, "summary_en": "", "summary_uk": summary}
    assert _area_finding(item, "thyroid")["summary_uk"] == "E04.1 Нетоксичний одновузловий зоб."
    assert "зоб" not in _area_finding(item, "heart")["summary_uk"]
    # «зоб» is the goitre as a word, never the start of «зобов'язання».
    assert _diagnosis_areas("Дифузний зоб I ст.") == ("thyroid",)
    assert "thyroid" not in _diagnosis_areas("Зобов'язання пацієнта виконано")
