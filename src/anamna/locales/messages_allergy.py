"""Messages for the allergy overview page: both supported languages."""
from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # --- page chrome ------------------------------------------------------
    "allergy.page.title": {"en": "Allergy", "uk": "Алергія"},
    "allergy.page.eyebrow": {"en": "Allergy overview", "uk": "Огляд алергії"},
    "allergy.page.lead": {
        "en": "What your allergy blood tests checked, what they found and what the results mean.",
        "uk": "Що перевірили ваші аналізи крові на алергію, що вони знайшли і що означають результати.",
    },
    "allergy.page.test_alex": {"en": "{name} molecular allergy test", "uk": "Молекулярний алергологічний тест {name}"},
    "allergy.page.test_generic": {"en": "Allergen-specific IgE test", "uk": "Аналіз на специфічні IgE до алергенів"},
    "allergy.page.lab": {"en": "Laboratory: {lab}", "uk": "Лабораторія: {lab}"},
    "allergy.page.tested_on": {"en": "Sample taken {date}", "uk": "Зразок узято {date}"},
    "allergy.page.allergens_one": {"en": "{count} allergen tested", "uk": "{count} досліджений алерген"},
    "allergy.page.allergens_few": {"en": "{count} allergens tested", "uk": "{count} досліджені алергени"},
    "allergy.page.allergens_many": {"en": "{count} allergens tested", "uk": "{count} досліджених алергенів"},
    "allergy.page.open_document": {"en": "Open the report", "uk": "Відкрити звіт"},

    # --- the headline -----------------------------------------------------
    "allergy.page.headline_none": {"en": "No sensitisation found", "uk": "Сенсибілізації не виявлено"},
    "allergy.page.headline_none_body_one": {
        "en": "The {count} allergen tested was below the test's cut-off of {cutoff}.",
        "uk": "{count} досліджений алерген нижче порогу тесту {cutoff}.",
    },
    "allergy.page.headline_none_body_few": {
        "en": "All {count} allergens tested were below the test's cut-off of {cutoff}.",
        "uk": "Усі {count} досліджені алергени нижче порогу тесту {cutoff}.",
    },
    "allergy.page.headline_none_body_many": {
        "en": "All {count} allergens tested were below the test's cut-off of {cutoff}.",
        "uk": "Усі {count} досліджених алергенів нижче порогу тесту {cutoff}.",
    },
    "allergy.page.headline_none_body_lab_one": {
        "en": "The {count} allergen tested was below the laboratory's cut-off.",
        "uk": "{count} досліджений алерген нижче порогу лабораторії.",
    },
    "allergy.page.headline_none_body_lab_few": {
        "en": "All {count} allergens tested were below the laboratory's cut-off.",
        "uk": "Усі {count} досліджені алергени нижче порогу лабораторії.",
    },
    "allergy.page.headline_none_body_lab_many": {
        "en": "All {count} allergens tested were below the laboratory's cut-off.",
        "uk": "Усі {count} досліджених алергенів нижче порогу лабораторії.",
    },
    "allergy.page.headline_positive_one": {"en": "Sensitisation found: {count} positive result", "uk": "Виявлено сенсибілізацію: {count} позитивний результат"},
    "allergy.page.headline_positive_few": {"en": "Sensitisation found: {count} positive results", "uk": "Виявлено сенсибілізацію: {count} позитивні результати"},
    "allergy.page.headline_positive_many": {"en": "Sensitisation found: {count} positive results", "uk": "Виявлено сенсибілізацію: {count} позитивних результатів"},
    "allergy.page.headline_uncertain_one": {"en": "{count} borderline result", "uk": "{count} сумнівний результат"},
    "allergy.page.headline_uncertain_few": {"en": "{count} borderline results", "uk": "{count} сумнівні результати"},
    "allergy.page.headline_uncertain_many": {"en": "{count} borderline results", "uk": "{count} сумнівних результатів"},
    "allergy.page.headline_some_body_one": {
        "en": "{count} allergen was tested. A positive result shows sensitisation, not necessarily an allergy: it is read together with your symptoms.",
        "uk": "Досліджено {count} алерген. Позитивний результат показує сенсибілізацію, а не обовʼязково алергію: його оцінюють разом із симптомами.",
    },
    "allergy.page.headline_some_body_few": {
        "en": "{count} allergens were tested. A positive result shows sensitisation, not necessarily an allergy: it is read together with your symptoms.",
        "uk": "Досліджено {count} алергени. Позитивний результат показує сенсибілізацію, а не обовʼязково алергію: його оцінюють разом із симптомами.",
    },
    "allergy.page.headline_some_body_many": {
        "en": "{count} allergens were tested. A positive result shows sensitisation, not necessarily an allergy: it is read together with your symptoms.",
        "uk": "Досліджено {count} алергенів. Позитивний результат показує сенсибілізацію, а не обовʼязково алергію: його оцінюють разом із симптомами.",
    },
    "allergy.page.highest": {"en": "Highest result: {value}.", "uk": "Найвищий результат: {value}."},
    "allergy.page.highest_none": {
        "en": "No allergen was measurable above the lowest value the test reports.",
        "uk": "Жоден алерген не перевищив найменшого значення, яке тест може виміряти.",
    },

    # --- what it means ----------------------------------------------------
    "allergy.page.sensitisation_title": {"en": "Sensitisation is not the same as allergy", "uk": "Сенсибілізація ще не означає алергію"},
    "allergy.page.sensitisation_body": {
        "en": "IgE (immunoglobulin E) is the antibody behind hay fever, food allergy and sting allergy. A positive result means your body has made IgE against that allergen, which is called sensitisation. It is an allergy only when contact with it also causes symptoms, so results are read together with what actually happens to you.",
        "uk": "IgE (імуноглобулін E) це антитіло, яке стоїть за сінною гарячкою, харчовою алергією та алергією на ужалення. Позитивний результат означає, що організм виробив IgE до цього алергену: це називають сенсибілізацією. Алергією вона стає лише тоді, коли контакт з алергеном ще й викликає симптоми, тому результати оцінюють разом із тим, що з вами відбувається насправді.",
    },
    "allergy.page.not_covered_title": {"en": "What a negative result does not rule out", "uk": "Чого не виключає негативний результат"},
    "allergy.page.not_covered.non_ige": {
        "en": "Reactions that do not involve IgE, such as some delayed food reactions of the gut or skin.",
        "uk": "Реакції без участі IgE, наприклад деякі відстрочені харчові реакції з боку кишківника чи шкіри.",
    },
    "allergy.page.not_covered.intolerance": {
        "en": "Food intolerances, such as lactose intolerance: they are not immune reactions.",
        "uk": "Харчову непереносимість, наприклад лактози: це не імунна реакція.",
    },
    "allergy.page.not_covered.drugs": {
        "en": "Reactions to medicines, which are assessed separately.",
        "uk": "Реакції на ліки: їх оцінюють окремо.",
    },
    "allergy.page.not_covered.processed": {
        "en": "Allergens that form or change during cooking, processing or digestion, and so may be missing from the test.",
        "uk": "Алергени, що утворюються або змінюються під час приготування, обробки чи травлення, тож їх може не бути в тесті.",
    },
    "allergy.page.not_covered.venom": {
        "en": "A sting allergy after a long time without stings: the antibody level can fall below what the test detects.",
        "uk": "Алергію на ужалення після тривалої перерви без ужалень: рівень антитіл може знизитися нижче межі виявлення.",
    },
    "allergy.page.not_covered.absent": {
        "en": "Anything that is not on the test. Use the search below to check.",
        "uk": "Усе, чого немає в тесті. Перевірте пошуком нижче.",
    },

    # --- total IgE --------------------------------------------------------
    "allergy.page.total_title": {"en": "Total IgE", "uk": "Загальний IgE"},
    "allergy.page.total_what": {
        "en": "All IgE antibodies in the blood together, whatever they are directed at. It is not used on its own to diagnose an allergy.",
        "uk": "Усі антитіла IgE в крові разом, до чого б вони не були спрямовані. Самостійно для діагностики алергії його не використовують.",
    },
    "allergy.page.total_reference": {"en": "Reference: {range}", "uk": "Референтний інтервал: {range}"},
    "allergy.page.total_open": {"en": "Total IgE over time", "uk": "Загальний IgE з часом"},

    # --- scales and codes -------------------------------------------------
    "allergy.page.scale_title": {"en": "How to read the numbers", "uk": "Як читати числа"},
    "allergy.page.scale_unit": {
        "en": "Results are given in {unit}: thousands of units of allergen-specific IgE per litre of blood. A higher number means more antibody, not a more severe allergy.",
        "uk": "Результати подано в {unit}: тисячі одиниць алергенспецифічного IgE на літр крові. Більше число означає більше антитіл, а не тяжчу алергію.",
    },
    "allergy.page.scale_alex_title": {"en": "ALEX levels", "uk": "Рівні ALEX"},
    "allergy.page.scale_alex_body": {
        "en": "ALEX tests report five levels. Below {cutoff} counts as negative or uncertain. These are not the ImmunoCAP classes 0 to 6 used by other test systems, so numbers from different systems are not directly comparable.",
        "uk": "Тести ALEX повідомляють пʼять рівнів. Нижче {cutoff} результат вважають негативним або невизначеним. Це не класи ImmunoCAP від 0 до 6, які використовують інші тест-системи, тож числа з різних систем не можна порівнювати напряму.",
    },
    "allergy.page.scale_immunocap_title": {"en": "ImmunoCAP classes", "uk": "Класи ImmunoCAP"},
    "allergy.page.scale_immunocap_body": {
        "en": "Results from ImmunoCAP-type tests are graded in classes 0 to 6. The class shows how much antibody was found, not how severe an allergy is.",
        "uk": "Результати тестів типу ImmunoCAP поділяють на класи від 0 до 6. Клас показує кількість антитіл, а не тяжкість алергії.",
    },
    "allergy.cap_alex_0": {"en": "Negative or uncertain", "uk": "Негативний або невизначений"},
    "allergy.cap_alex_1": {"en": "Low IgE level", "uk": "Низький рівень IgE"},
    "allergy.cap_alex_2": {"en": "Moderate IgE level", "uk": "Помірний рівень IgE"},
    "allergy.cap_alex_3": {"en": "High IgE level", "uk": "Високий рівень IgE"},
    "allergy.cap_alex_4": {"en": "Very high IgE level", "uk": "Дуже високий рівень IgE"},
    "allergy.alex_lead": {
        "en": "These results come from an ALEX test, which grades results on its own five levels with a cut-off of {cutoff}. ImmunoCAP classes do not apply to them.",
        "uk": "Ці результати отримано тестом ALEX, який оцінює їх за власними пʼятьма рівнями з порогом {cutoff}. Класи ImmunoCAP до них не застосовують.",
    },
    "allergy.page.codes_title": {"en": "What the codes mean", "uk": "Що означають коди"},
    "allergy.page.codes_body": {
        "en": "Each allergen carries its international WHO/IUIS code: the first letters of the Latin genus and species, then a number for a single protein. Bet v 1 is protein 1 of birch (Betula verrucosa). A code without a number, such as Cyn d, is an extract: everything from that source at once. A code with a number is a component: one purified protein, which shows more precisely what the antibody recognises.",
        "uk": "Кожен алерген має міжнародний код WHO/IUIS: перші літери латинської назви роду та виду, а для окремого білка ще й номер. Bet v 1 це білок 1 берези (Betula verrucosa). Код без номера, як-от Cyn d, означає екстракт: усе з цього джерела разом. Код із номером означає компонент: один очищений білок, який точніше показує, що саме розпізнає антитіло.",
    },
    "allergy.page.extract": {"en": "Extract", "uk": "Екстракт"},
    "allergy.page.component": {"en": "Component", "uk": "Компонент"},

    # --- positives, search, groups ----------------------------------------
    "allergy.page.positives_title": {"en": "Positive and borderline results", "uk": "Позитивні та сумнівні результати"},
    "allergy.page.positives_lead": {
        "en": "Read these together with your symptoms. A doctor or allergist decides what they mean for you.",
        "uk": "Оцінюйте їх разом із симптомами. Що вони означають саме для вас, вирішує лікар або алерголог.",
    },
    "allergy.page.search_title": {"en": "Was I tested for...?", "uk": "Чи перевіряли мене на...?"},
    "allergy.page.search_label": {"en": "Allergen, food, animal or plant", "uk": "Алерген, продукт, тварина чи рослина"},
    "allergy.page.search_placeholder": {"en": "cat, birch, peanut, wasp", "uk": "кіт, береза, арахіс, оса"},
    "allergy.page.search_submit": {"en": "Check", "uk": "Перевірити"},
    "allergy.page.search_clear": {"en": "Clear the search", "uk": "Очистити пошук"},
    "allergy.page.search_found_one": {"en": "{count} allergen source matches \"{query}\"", "uk": "{count} джерело алергенів відповідає запиту «{query}»"},
    "allergy.page.search_found_few": {"en": "{count} allergen sources match \"{query}\"", "uk": "{count} джерела алергенів відповідають запиту «{query}»"},
    "allergy.page.search_found_many": {"en": "{count} allergen sources match \"{query}\"", "uk": "{count} джерел алергенів відповідають запиту «{query}»"},
    "allergy.page.search_none": {
        "en": "Nothing matching \"{query}\" is on your tests. It may be listed under another name; otherwise it was not tested.",
        "uk": "У ваших аналізах немає нічого, що відповідає запиту «{query}». Можливо, його вказано під іншою назвою; інакше його не досліджували.",
    },
    "allergy.page.search_plan": {"en": "Plan a test for it", "uk": "Запланувати аналіз"},
    "allergy.page.groups_title": {"en": "Everything that was tested", "uk": "Усе, що досліджено"},
    "allergy.page.groups_lead": {
        "en": "Grouped by where the allergen comes from. Open a group to see each allergen, its code and its result.",
        "uk": "Згруповано за походженням алергену. Відкрийте групу, щоб побачити кожен алерген, його код і результат.",
    },
    "allergy.page.group_results_one": {"en": "{count} result", "uk": "{count} результат"},
    "allergy.page.group_results_few": {"en": "{count} results", "uk": "{count} результати"},
    "allergy.page.group_results_many": {"en": "{count} results", "uk": "{count} результатів"},
    "allergy.page.group_positive_one": {"en": "{count} positive", "uk": "{count} позитивний"},
    "allergy.page.group_positive_few": {"en": "{count} positive", "uk": "{count} позитивні"},
    "allergy.page.group_positive_many": {"en": "{count} positive", "uk": "{count} позитивних"},
    "allergy.page.group_uncertain_one": {"en": "{count} borderline", "uk": "{count} сумнівний"},
    "allergy.page.group_uncertain_few": {"en": "{count} borderline", "uk": "{count} сумнівні"},
    "allergy.page.group_uncertain_many": {"en": "{count} borderline", "uk": "{count} сумнівних"},
    "allergy.page.group_all_negative": {"en": "All negative", "uk": "Усі негативні"},
    "allergy.page.status.positive": {"en": "Positive", "uk": "Позитивний"},
    "allergy.page.status.uncertain": {"en": "Borderline", "uk": "Сумнівний"},
    "allergy.page.status.negative": {"en": "Negative", "uk": "Негативний"},
    "allergy.page.status.unjudged": {"en": "Not assessed", "uk": "Не оцінено"},
    "allergy.page.earlier": {"en": "Earlier: {date}, {value}", "uk": "Раніше: {date}, {value}"},
    "allergy.page.unverified": {"en": "Not yet checked against the report", "uk": "Ще не звірено зі звітом"},
    "allergy.page.th_allergen": {"en": "Allergen", "uk": "Алерген"},
    "allergy.page.th_value": {"en": "Result", "uk": "Результат"},
    "allergy.page.th_level": {"en": "Level", "uk": "Рівень"},
    "allergy.page.th_family": {"en": "Protein family", "uk": "Родина білків"},

    # --- families ---------------------------------------------------------
    "allergy.page.families_title": {"en": "What the single proteins tell", "uk": "Що показують окремі білки"},
    "allergy.page.families_lead": {
        "en": "Proteins of one family look alike across plants or animals. That explains cross-reactions, where the antibody to one source also reacts to another, and hints at how strong a reaction could be.",
        "uk": "Білки однієї родини схожі в різних рослин чи тварин. Це пояснює перехресні реакції, коли антитіло до одного джерела реагує й на інше, і підказує, наскільки сильною може бути реакція.",
    },
    "allergy.page.family_your_codes": {"en": "On your test: {codes}", "uk": "У вашому тесті: {codes}"},
    "allergy.page.family_positive_codes": {"en": "Positive: {codes}", "uk": "Позитивні: {codes}"},

    # --- next steps, sources, empty state ---------------------------------
    "allergy.page.tests_title": {"en": "Your allergy tests", "uk": "Ваші алергологічні аналізи"},
    "allergy.page.tests_history": {
        "en": "Each allergen lists its earlier results under the latest one.",
        "uk": "Під останнім результатом кожного алергену наведено попередні.",
    },
    "allergy.page.next_title": {"en": "What to do next", "uk": "Що робити далі"},
    "allergy.page.next_symptoms": {
        "en": "If you have symptoms, such as sneezing in one season, a reaction after a food or after a sting, show this report to a doctor or an allergist. They read it together with your history and may add skin tests or a supervised food challenge.",
        "uk": "Якщо є симптоми, як-от чхання в певний сезон, реакція після їжі чи ужалення, покажіть цей звіт лікарю або алергологу. Він оцінить його разом з анамнезом і може додати шкірні проби чи контрольовану провокаційну пробу з продуктом.",
    },
    "allergy.page.next_plan_body": {
        "en": "To check allergens that are not on your tests, or to repeat a test:",
        "uk": "Щоб перевірити алергени, яких немає у ваших аналізах, або повторити аналіз:",
    },
    "allergy.page.next_plan": {"en": "Plan an allergy test", "uk": "Запланувати алергологічний аналіз"},
    "allergy.page.sources_title": {"en": "Sources", "uk": "Джерела"},
    "allergy.page.sources_short": {"en": "Sources", "uk": "Джерела"},
    "allergy.page.sources_regions": {
        "en": "US: United States. EU: Europe. UA: Ukraine. INT: international body or test manufacturer.",
        "uk": "US: США. EU: Європа. UA: Україна. INT: міжнародна організація або виробник тесту.",
    },
    "allergy.page.empty_title": {"en": "No allergy tests in your record yet", "uk": "У вашій картці ще немає алергологічних аналізів"},
    "allergy.page.empty_body": {
        "en": "An allergy blood test measures IgE antibodies to specific allergens. It shows sensitisation; together with your symptoms it helps a doctor confirm or rule out an allergy.",
        "uk": "Аналіз крові на алергію вимірює антитіла IgE до конкретних алергенів. Він показує сенсибілізацію, а разом із симптомами допомагає лікарю підтвердити або виключити алергію.",
    },
    "allergy.page.empty_kinds_title": {"en": "Kinds of allergy blood tests", "uk": "Які бувають аналізи крові на алергію"},
    "allergy.page.kind.single": {
        "en": "Single allergens: one extract at a time, for example cat dander or birch pollen.",
        "uk": "Окремі алергени: один екстракт за раз, наприклад епітелій кота чи пилок берези.",
    },
    "allergy.page.kind.panel": {
        "en": "Panels: a set of common inhaled or food allergens in one order.",
        "uk": "Панелі: набір поширених інгаляційних або харчових алергенів в одному замовленні.",
    },
    "allergy.page.kind.molecular": {
        "en": "Molecular (component) tests: single proteins such as Bet v 1 or Ara h 2, which help tell a genuine sensitisation from a cross-reaction.",
        "uk": "Молекулярні (компонентні) тести: окремі білки, як-от Bet v 1 чи Ara h 2, які допомагають відрізнити справжню сенсибілізацію від перехресної реакції.",
    },
    "allergy.page.kind.multiplex": {
        "en": "Multiplex arrays, such as ALEX² or ImmunoCAP ISAC: hundreds of extracts and proteins from one blood sample.",
        "uk": "Мультиплексні чипи, як-от ALEX² чи ImmunoCAP ISAC: сотні екстрактів і білків з одного зразка крові.",
    },
    "allergy.page.kind.total": {
        "en": "Total IgE: all IgE antibodies together. It does not diagnose an allergy on its own.",
        "uk": "Загальний IgE: усі антитіла IgE разом. Самостійно алергію він не діагностує.",
    },
    "allergy.page.empty_upload": {"en": "Upload a report", "uk": "Завантажити звіт"},
    "allergy.page.panel_link": {"en": "Open the allergy overview", "uk": "Відкрити огляд алергії"},
    "allergy.page.panel_link_body": {
        "en": "Results grouped by where each allergen comes from, with a search and what each protein family means.",
        "uk": "Результати згруповано за походженням алергенів, із пошуком і поясненням кожної родини білків.",
    },

    # --- groups -------------------------------------------------------------
    "allergy.page.group.grass_pollen": {"en": "Grass pollen", "uk": "Пилок злакових трав"},
    "allergy.page.group.tree_pollen": {"en": "Tree pollen", "uk": "Пилок дерев"},
    "allergy.page.group.weed_pollen": {"en": "Weed pollen", "uk": "Пилок бурʼянів"},
    "allergy.page.group.mites": {"en": "House-dust and storage mites", "uk": "Кліщі домашнього пилу та комірні кліщі"},
    "allergy.page.group.animals": {"en": "Pets and farm animals", "uk": "Домашні та свійські тварини"},
    "allergy.page.group.moulds": {"en": "Moulds and yeasts", "uk": "Цвіль і дріжджі"},
    "allergy.page.group.insects": {"en": "Stinging insects and cockroaches", "uk": "Жалючі комахи та таргани"},
    "allergy.page.group.legumes": {"en": "Foods: legumes", "uk": "Продукти: бобові"},
    "allergy.page.group.cereals": {"en": "Foods: grains", "uk": "Продукти: зернові"},
    "allergy.page.group.spices": {"en": "Foods: spices and herbs", "uk": "Продукти: спеції та прянощі"},
    "allergy.page.group.fruits": {"en": "Foods: fruit", "uk": "Продукти: фрукти та ягоди"},
    "allergy.page.group.vegetables": {"en": "Foods: vegetables", "uk": "Продукти: овочі"},
    "allergy.page.group.nuts_seeds": {"en": "Foods: nuts and seeds", "uk": "Продукти: горіхи та насіння"},
    "allergy.page.group.milk": {"en": "Foods: milk", "uk": "Продукти: молоко"},
    "allergy.page.group.egg": {"en": "Foods: egg", "uk": "Продукти: яйце"},
    "allergy.page.group.fish_seafood": {"en": "Foods: fish and seafood", "uk": "Продукти: риба та морепродукти"},
    "allergy.page.group.meat": {"en": "Foods: meat and edible insects", "uk": "Продукти: мʼясо та їстівні комахи"},
    "allergy.page.group.latex": {"en": "Latex", "uk": "Латекс"},
    "allergy.page.group.other": {"en": "Other", "uk": "Інше"},

    # --- protein families -------------------------------------------------
    "allergy.family.pr10.name": {"en": "PR-10 proteins (birch type)", "uk": "Білки PR-10 (березового типу)"},
    "allergy.family.pr10.what": {
        "en": "Plant defence proteins. Bet v 1 in birch pollen is the best known; similar ones are in alder, hazel and beech pollen and in apple, cherry, peach, hazelnut, celery, carrot, soy and peanut.",
        "uk": "Захисні білки рослин. Найвідоміший Bet v 1 з пилку берези; схожі є в пилку вільхи, ліщини та бука, а також у яблуці, черешні, персику, фундуку, селері, моркві, сої та арахісі.",
    },
    "allergy.family.pr10.means": {
        "en": "A positive usually comes from birch-family pollen. Raw fruit, vegetables or nuts may then make the mouth or throat itch (pollen-food syndrome). Heat breaks these proteins down, so well-cooked foods are often tolerated, and severe reactions are rare; large amounts taken quickly, such as soy drinks or smoothies, can occasionally cause more.",
        "uk": "Позитивний результат зазвичай повʼязаний із пилком дерев родини березових. Тоді сирі фрукти, овочі чи горіхи можуть викликати свербіж у роті чи горлі (пилково-харчовий синдром). Нагрівання руйнує ці білки, тому добре приготовану їжу часто переносять, а тяжкі реакції рідкісні; великі кількості, зʼїдені чи випиті швидко, як-от соєві напої чи смузі, зрідка можуть викликати сильнішу реакцію.",
    },
    "allergy.family.ltp.name": {"en": "Lipid transfer proteins (nsLTP)", "uk": "Білки-переносники ліпідів (nsLTP)"},
    "allergy.family.ltp.what": {
        "en": "Sturdy plant proteins, mostly in the peel and seeds of fruit, in nuts, vegetables and some pollens. Pru p 3 from peach is the reference one.",
        "uk": "Стійкі білки рослин, переважно в шкірці та насінні фруктів, у горіхах, овочах і деяких видах пилку. Еталонний із них Pru p 3 з персика.",
    },
    "allergy.family.ltp.means": {
        "en": "They survive heating and digestion, so a positive can go with reactions beyond the mouth, sometimes only when the food is combined with exercise, alcohol or anti-inflammatory painkillers. Worth discussing with an allergist even if past symptoms were mild.",
        "uk": "Вони витримують нагрівання й травлення, тому позитивний результат може супроводжуватися реакціями не лише в роті, іноді тільки коли продукт поєднується з фізичним навантаженням, алкоголем чи протизапальними знеболювальними. Варто обговорити з алергологом, навіть якщо симптоми були легкими.",
    },
    "allergy.family.profilin.name": {"en": "Profilins", "uk": "Профіліни"},
    "allergy.family.profilin.what": {
        "en": "A protein present in almost every pollen and plant food and nearly identical between species, for example Bet v 2, Phl p 12 and Hev b 8.",
        "uk": "Білок, що є майже в усіх видах пилку та рослинних продуктах і майже однаковий у різних видів, наприклад Bet v 2, Phl p 12 і Hev b 8.",
    },
    "allergy.family.profilin.means": {
        "en": "A positive can make many pollen and plant-food results positive at once without showing which plant is the real cause. Reactions are usually mild and limited to the mouth.",
        "uk": "Позитивний результат може зробити позитивними багато результатів до пилку та рослинних продуктів одночасно, не показуючи, яка рослина справжня причина. Реакції зазвичай легкі й обмежуються ротом.",
    },
    "allergy.family.polcalcin.name": {"en": "Polcalcins", "uk": "Полкальцини"},
    "allergy.family.polcalcin.what": {
        "en": "Calcium-binding proteins found only in pollen, for example Phl p 7 and Aln g 4.",
        "uk": "Білки, що звʼязують кальцій і трапляються лише в пилку, наприклад Phl p 7 і Aln g 4.",
    },
    "allergy.family.polcalcin.means": {
        "en": "A positive explains why many different pollens test positive at once. They are not in foods, so they do not cause food reactions.",
        "uk": "Позитивний результат пояснює, чому одночасно позитивні результати до багатьох видів пилку. У продуктах їх немає, тож харчових реакцій вони не викликають.",
    },
    "allergy.family.storage.name": {"en": "Seed storage proteins", "uk": "Запасні білки насіння"},
    "allergy.family.storage.what": {
        "en": "The proteins nuts, peanut, seeds and legumes store for growth: 2S albumins, 7S and 11S globulins, for example Ara h 2 (peanut), Cor a 14 (hazelnut) and Ana o 3 (cashew).",
        "uk": "Білки, які горіхи, арахіс, насіння та бобові запасають для росту: 2S-альбуміни, 7S- і 11S-глобуліни, наприклад Ara h 2 (арахіс), Cor a 14 (фундук) і Ana o 3 (кешʼю).",
    },
    "allergy.family.storage.means": {
        "en": "They resist heat and digestion. A positive points to sensitisation to that food itself rather than a cross-reaction from pollen, and is linked with a higher chance of reactions beyond the mouth. Doctors use some of them, such as Ara h 2, to judge how likely a true food allergy is.",
        "uk": "Вони стійкі до нагрівання й травлення. Позитивний результат вказує на сенсибілізацію саме до цього продукту, а не на перехресну реакцію з пилком, і повʼязаний з вищою ймовірністю реакцій не лише в роті. Деякі з них, як-от Ara h 2, лікарі використовують, щоб оцінити ймовірність справжньої харчової алергії.",
    },
    "allergy.family.tropomyosin.name": {"en": "Tropomyosins", "uk": "Тропоміозини"},
    "allergy.family.tropomyosin.what": {
        "en": "A muscle protein of shellfish, house-dust mites, cockroaches and the fish parasite Anisakis, for example Pen m 1, Der p 10 and Ani s 3.",
        "uk": "Мʼязовий білок ракоподібних і молюсків, кліщів домашнього пилу, тарганів і паразита риби анізакіди, наприклад Pen m 1, Der p 10 і Ani s 3.",
    },
    "allergy.family.tropomyosin.means": {
        "en": "Very alike across these animals, so a positive can cross-react: someone sensitised through mites may also test positive to shrimp. It is a main shrimp and shellfish allergen and survives cooking.",
        "uk": "Дуже схожий у цих тварин, тому можливі перехресні реакції: людина, сенсибілізована через кліщів, може мати позитивний результат і до креветок. Це один із головних алергенів креветок і молюсків, і він витримує приготування.",
    },
    "allergy.family.parvalbumin.name": {"en": "Parvalbumins", "uk": "Парвальбуміни"},
    "allergy.family.parvalbumin.what": {
        "en": "The main allergen of fish muscle, for example Gad m 1 (cod), Cyp c 1 (carp) and Sal s 1 (salmon).",
        "uk": "Головний алерген мʼязів риби, наприклад Gad m 1 (тріска), Cyp c 1 (короп) і Sal s 1 (лосось).",
    },
    "allergy.family.parvalbumin.means": {
        "en": "Heat-stable and alike across many fish, so a positive often means sensitisation to several kinds of fish; whether you react is decided by your history and, if needed, a supervised challenge.",
        "uk": "Стійкий до нагрівання і схожий у багатьох видів риби, тому позитивний результат часто означає сенсибілізацію до кількох видів риби; чи є реакція, вирішують за анамнезом і, за потреби, провокаційною пробою.",
    },
    "allergy.family.serum_albumin.name": {"en": "Serum albumins", "uk": "Сироваткові альбуміни"},
    "allergy.family.serum_albumin.what": {
        "en": "A blood protein of mammals and birds, found in dander, meat, milk and egg yolk, for example Fel d 2, Can f 3, Bos d 6 and Gal d 5.",
        "uk": "Білок крові ссавців і птахів, що є в епітелії, мʼясі, молоці та жовтку, наприклад Fel d 2, Can f 3, Bos d 6 і Gal d 5.",
    },
    "allergy.family.serum_albumin.means": {
        "en": "Alike between animals, so a positive can cross-react between pets, farm animals and their meat or milk, for example cat and pork. Cooking largely destroys it.",
        "uk": "Схожий у різних тварин, тому можливі перехресні реакції між домашніми та свійськими тваринами, їхнім мʼясом чи молоком, наприклад між котом і свининою. Приготування здебільшого його руйнує.",
    },
    "allergy.family.lipocalin.name": {"en": "Lipocalins", "uk": "Ліпокаліни"},
    "allergy.family.lipocalin.what": {
        "en": "Small carrier proteins that animals shed in dander, saliva and urine: main allergens of dog (Can f 1, Can f 2, Can f 4, Can f 6), horse (Equ c 1), mouse (Mus m 1) and cockroach (Bla g 4).",
        "uk": "Невеликі білки-переносники, які тварини виділяють з епітелієм, слиною та сечею: головні алергени собаки (Can f 1, Can f 2, Can f 4, Can f 6), коня (Equ c 1), миші (Mus m 1) і таргана (Bla g 4).",
    },
    "allergy.family.lipocalin.means": {
        "en": "Most of them point to one animal. A few, such as Can f 6, Fel d 4 and Equ c 1, resemble each other, so a positive to one can come with positives to the others.",
        "uk": "Більшість указує на одну тварину. Деякі, як-от Can f 6, Fel d 4 і Equ c 1, схожі між собою, тож позитивний результат до одного може супроводжуватися позитивними до інших.",
    },
    "allergy.family.secretoglobin.name": {"en": "Secretoglobins (uteroglobins)", "uk": "Секретоглобіни (утероглобіни)"},
    "allergy.family.secretoglobin.what": {
        "en": "Fel d 1 is the main cat allergen; related proteins are found in dog and rabbit.",
        "uk": "Fel d 1 головний алерген кота; споріднені білки є в собаки та кролика.",
    },
    "allergy.family.secretoglobin.means": {
        "en": "A positive to Fel d 1 shows genuine sensitisation to cats rather than a cross-reaction.",
        "uk": "Позитивний результат до Fel d 1 показує справжню сенсибілізацію до котів, а не перехресну реакцію.",
    },
    "allergy.family.milk.name": {"en": "Milk proteins", "uk": "Білки молока"},
    "allergy.family.milk.what": {
        "en": "Casein (Bos d 8) and the whey proteins alpha-lactalbumin (Bos d 4) and beta-lactoglobulin (Bos d 5).",
        "uk": "Казеїн (Bos d 8) і сироваткові білки альфа-лактальбумін (Bos d 4) та бета-лактоглобулін (Bos d 5).",
    },
    "allergy.family.milk.means": {
        "en": "Casein survives heating, so a positive to it is more often linked with reactions to baked milk too. Whey proteins are partly changed by heat.",
        "uk": "Казеїн витримує нагрівання, тому позитивний результат до нього частіше повʼязаний і з реакціями на запечене молоко. Сироваткові білки нагрівання частково змінює.",
    },
    "allergy.family.egg.name": {"en": "Egg white proteins", "uk": "Білки яєчного білка"},
    "allergy.family.egg.what": {
        "en": "Ovomucoid (Gal d 1), ovalbumin (Gal d 2), ovotransferrin (Gal d 3) and lysozyme (Gal d 4).",
        "uk": "Овомукоїд (Gal d 1), овальбумін (Gal d 2), овотрансферин (Gal d 3) і лізоцим (Gal d 4).",
    },
    "allergy.family.egg.means": {
        "en": "Ovomucoid withstands heat, so a positive to it is linked with reactions to baked egg as well. The others are largely changed by cooking.",
        "uk": "Овомукоїд витримує нагрівання, тому позитивний результат до нього повʼязаний і з реакціями на запечене яйце. Інші білки приготування здебільшого змінює.",
    },
    "allergy.family.omega5.name": {"en": "Omega-5 gliadin", "uk": "Омега-5-гліадин"},
    "allergy.family.omega5.what": {"en": "A wheat protein (Tri a 19).", "uk": "Білок пшениці (Tri a 19)."},
    "allergy.family.omega5.means": {
        "en": "Linked with wheat allergy, including reactions that happen only when eating wheat is followed by exercise.",
        "uk": "Повʼязаний з алергією на пшеницю, зокрема з реакціями, які виникають лише тоді, коли після пшениці є фізичне навантаження.",
    },
    "allergy.family.venom.name": {"en": "Venom proteins", "uk": "Білки отрути"},
    "allergy.family.venom.what": {
        "en": "Api m 1 and Api m 10 are specific to honey bee venom; Ves v 1, Ves v 5 and Pol d 5 to wasps.",
        "uk": "Api m 1 і Api m 10 властиві лише отруті медоносної бджоли; Ves v 1, Ves v 5 і Pol d 5 отруті ос.",
    },
    "allergy.family.venom.means": {
        "en": "When both bee and wasp results are positive, these show which insect the sensitisation comes from, which matters when choosing venom immunotherapy. A negative result does not rule out a sting allergy after a real reaction.",
        "uk": "Коли позитивні результати і до бджоли, і до оси, ці білки показують, від якої комахи сенсибілізація, а це важливо для вибору імунотерапії отрутою. Негативний результат не виключає алергії на ужалення, якщо реакція вже була.",
    },
    "allergy.family.marker.name": {"en": "Species-specific main allergens", "uk": "Видоспецифічні головні алергени"},
    "allergy.family.marker.what": {
        "en": "Proteins found in one allergen source or a few close relatives, for example Phl p 1 and Phl p 5 (grasses), Amb a 1 (ragweed), Art v 1 (mugwort), Ole e 1 (olive and ash), Der p 1 and Der p 2 (house-dust mites) and Alt a 1 (Alternaria mould).",
        "uk": "Білки, що є в одному джерелі алергенів або кількох близьких до нього, наприклад Phl p 1 і Phl p 5 (злакові трави), Amb a 1 (амброзія), Art v 1 (полин), Ole e 1 (олива та ясен), Der p 1 і Der p 2 (кліщі домашнього пилу) та Alt a 1 (цвіль Alternaria).",
    },
    "allergy.family.marker.means": {
        "en": "A positive points to that source itself as the cause of sensitisation, not to a cross-reaction from something else. Allergists use them when choosing allergen immunotherapy.",
        "uk": "Позитивний результат вказує, що причина сенсибілізації саме це джерело, а не перехресна реакція з чимось іншим. Алергологи враховують їх, обираючи алергенспецифічну імунотерапію.",
    },
    "allergy.family.ccd.name": {"en": "Carbohydrate marker (CCD)", "uk": "Вуглеводний маркер (CCD)"},
    "allergy.family.ccd.what": {
        "en": "Cross-reactive carbohydrate determinants: sugar chains attached to plant and insect proteins. ALEX tests carry a marker for them (Hom s LF) and add a CCD blocker to the sample.",
        "uk": "Перехресно-реактивні вуглеводні детермінанти: ланцюжки цукрів на білках рослин і комах. Тести ALEX містять для них маркер (Hom s LF) і додають до зразка блокатор CCD.",
    },
    "allergy.family.ccd.means": {
        "en": "A positive marker means some positive plant or venom results may come from these sugars, which rarely cause symptoms, so a doctor reads such results with care.",
        "uk": "Позитивний маркер означає, що частина позитивних результатів до рослин чи отрути може бути спричинена цими цукрами, які рідко викликають симптоми, тож лікар оцінює такі результати обережно.",
    },
}

# Allergen sources: ``key|English|Ukrainian``.  Names are the common ones a
# person searches by; the Latin code is printed beside them on the page.
_SOURCE_NAMES = """
cyn_d|Bermuda grass|Свинорий пальчастий (цинодон)
lol_p|Perennial ryegrass|Пажитниця багаторічна
pas_n|Bahia grass|Паспалум
phl_p|Timothy grass|Тимофіївка лучна
phr_c|Common reed|Очерет звичайний
sec_c_pollen|Rye pollen|Жито посівне (пилок)
aca_m|Acacia (silver wattle)|Акація срібляста
ail_a|Tree of heaven|Айлант найвищий
aln_g|Alder|Вільха чорна (клейка)
bet_v|Birch|Береза повисла
bro_pa|Paper mulberry|Шовковиця паперова
cor_a_pollen|Hazel pollen|Ліщина (пилок)
cry_j|Japanese cedar|Криптомерія японська
cup_a|Arizona cypress|Кипарис аризонський
cup_s|Italian cypress|Кипарис вічнозелений
fag_s|Beech|Бук
fra_e|Ash|Ясен звичайний
jug_r_pollen|Walnut tree pollen|Волоський горіх (пилок)
jun_a|Mountain cedar (juniper)|Ялівець мексиканський
mor_r|Red mulberry|Шовковиця червона
ole_e|Olive tree|Олива
pho_d|Date palm|Фінікова пальма
pla_a|Plane tree|Платан кленолистий
pop_n|Black poplar|Тополя чорна (осокір)
ulm_c|Elm|Вʼяз
ama_r|Pigweed (amaranth)|Щириця звичайна (амарант)
amb_a|Ragweed|Амброзія полинолиста
art_v|Mugwort|Полин звичайний
can_s|Hemp|Коноплі посівні
che_a|Lamb's quarters (goosefoot)|Лобода біла
mer_a|Annual mercury|Переліска однорічна
par_j|Wall pellitory|Настінниця розлога
pla_l|Ribwort plantain|Подорожник ланцетолистий
sal_k|Saltwort|Курай поташевий
urt_d|Nettle|Кропива дводомна
der_f|American house-dust mite|Американський кліщ домашнього пилу
der_p|European house-dust mite|Європейський кліщ домашнього пилу
aca_s|Flour mite (Acarus siro)|Борошняний кліщ (Acarus siro)
blo_t|Blomia mite (Blomia tropicalis)|Кліщ Blomia tropicalis
gly_d|Storage mite (Glycyphagus domesticus)|Комірний кліщ (Glycyphagus domesticus)
lep_d|Storage mite (Lepidoglyphus destructor)|Комірний кліщ (Lepidoglyphus destructor)
tyr_p|Mould mite (Tyrophagus putrescentiae)|Кліщ Tyrophagus putrescentiae
can_f|Dog|Собака
cav_p|Guinea pig|Морська свинка
fel_d|Cat|Кіт (кішка)
mus_m|Mouse|Миша хатня
ory_c|Rabbit|Кролик
phod_s|Djungarian hamster|Джунгарський хомʼяк
rat_n|Rat|Щур
bos_d_dander|Cow (dander)|Корова (епітелій)
cap_h_dander|Goat (dander)|Коза (епітелій)
equ_c|Horse|Кінь
ovi_a_dander|Sheep (dander)|Вівця (епітелій)
sus_d_dander|Pig (dander)|Свиня (епітелій)
mala_s|Malassezia (skin yeast)|Малассезія (дріжджі шкіри)
sac_c|Baker's yeast|Пекарські дріжджі
alt_a|Alternaria mould|Цвіль Alternaria
asp_f|Aspergillus mould|Цвіль Aspergillus
cla_h|Cladosporium mould|Цвіль Cladosporium
pen_ch|Penicillium mould|Цвіль Penicillium
api_m|Honey bee|Бджола медоносна
dol_spp|Hornet (Dolichovespula)|Довгоголова оса (Dolichovespula)
pol_d|Paper wasp|Паперова оса
ves_v|Common wasp|Оса звичайна
sol_spp|Fire ant|Вогняна мураха
bla_g|German cockroach|Німецький тарган
per_a|American cockroach|Американський тарган
ara_h|Peanut|Арахіс
cic_a|Chickpea|Нут
gly_m|Soy|Соя
len_c|Lentil|Сочевиця
pha_v|Green bean|Зелена квасоля
pis_s|Pea|Горох
lup_a|Lupin seed|Люпин (насіння)
ave_s|Oat|Овес
che_q|Quinoa|Кіноа
fag_e|Buckwheat|Гречка
hor_v|Barley|Ячмінь
ory_s|Rice|Рис
pan_m|Millet|Пшоно (просо)
sec_c_flour|Rye (flour)|Жито (борошно)
tri_a|Wheat|Пшениця
tri_s|Spelt|Пшениця спельта
zea_m|Maize (corn)|Кукурудза
cap_a|Paprika (bell pepper)|Паприка (солодкий перець)
car_c|Caraway|Кмин звичайний
ori_v|Oregano|Орегано
pet_c|Parsley|Петрушка
pim_a|Anise|Аніс
sin_a|Mustard|Гірчиця
tri_fo|Fenugreek|Пажитник (насіння)
act_d|Kiwi|Ківі
car_p|Papaya|Папайя
cit_s|Orange|Апельсин
cuc_m|Melon|Диня
fic_c|Fig|Інжир
fra_a|Strawberry|Полуниця
mal_d|Apple|Яблуко
man_i|Mango|Манго
mus_a|Banana|Банан
pers_a|Avocado|Авокадо
pru_av|Cherry (sweet cherry)|Черешня
pru_p|Peach|Персик
pyr_c|Pear|Груша
vac_m|Blueberry|Чорниця
vit_v|Grape|Виноград
all_c|Onion|Цибуля
all_s|Garlic|Часник
api_g|Celery|Селера
dau_c|Carrot|Морква
sol_t|Potato|Картопля
sola_l|Tomato|Помідор
ana_o|Cashew|Кешʼю
ber_e|Brazil nut|Бразильський горіх
car_i|Pecan|Пекан
cor_a|Hazelnut|Фундук (лісовий горіх)
jug_r|Walnut|Волоський горіх
mac_i|Macadamia|Макадамія
pis_v|Pistachio|Фісташка
pru_du|Almond|Мигдаль
cuc_p|Pumpkin seed|Гарбузове насіння
hel_a|Sunflower seed|Насіння соняшнику
pap_s|Poppy seed|Мак
ses_i|Sesame|Кунжут
bos_d_milk|Cow's milk|Коровʼяче молоко
cam_d|Camel's milk|Верблюже молоко
cap_h_milk|Goat's milk|Козяче молоко
equ_c_milk|Mare's milk|Кобиляче молоко
ovi_a_milk|Sheep's milk|Овече молоко
gal_d_white|Egg white|Яєчний білок
gal_d_yolk|Egg yolk|Яєчний жовток
ani_s|Anisakis (fish parasite)|Анізакіда (паразит риби)
chi_spp|Crab|Краб
clu_h|Herring|Оселедець
cra_c|Brown shrimp|Креветка піщана
cyp_c|Carp|Короп
gad_m|Cod|Тріска
hom_g|Lobster|Омар
lit_s|White shrimp|Креветка (Litopenaeus)
lol_spp|Squid|Кальмар
myt_e|Mussel|Мідія
ost_e|Oyster|Устриця
pan_b|Northern shrimp|Північна креветка
pec_spp|Scallop|Морський гребінець
pen_m|Black tiger shrimp|Чорна тигрова креветка
raj_c|Thornback ray|Скат (морська лисиця)
rud_spp|Clam|Молюск (Ruditapes)
sal_s|Salmon|Лосось
sco_s|Mackerel|Скумбрія
thu_a|Tuna|Тунець
xip_g|Swordfish|Риба-меч
bos_d_meat|Beef|Яловичина
equ_c_meat|Horse meat|Конина
gal_d_meat|Chicken|Курятина
mel_g|Turkey|Індичатина
ory_meat|Rabbit meat|Кролятина
ovi_a_meat|Lamb|Баранина
sus_d_meat|Pork|Свинина
ach_d|House cricket|Цвіркун хатній
loc_m|Migratory locust|Сарана перелітна
ten_m|Mealworm|Хрущак борошняний
hev_b|Latex|Латекс
fic_b|Weeping fig (ficus)|Фікус
hom_s|Carbohydrate marker (CCD)|Вуглеводний маркер (CCD)
arg_r|Pigeon tick|Голубиний кліщ (Argas reflexus)
"""
for _line in _SOURCE_NAMES.strip().splitlines():
    _key, _en, _uk = _line.split("|")
    MESSAGES[f"allergen.{_key}"] = {"en": _en, "uk": _uk}
del _line, _key, _en, _uk
