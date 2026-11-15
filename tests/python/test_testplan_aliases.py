"""Matching lab catalogues to concepts and to each other (testplan_aliases)."""

import pytest

from anamna import testplan, testplan_aliases
from anamna.ingest.concepts import CONCEPT_DEFINITIONS, stable_concept_id

SEEDED = {stable_concept_id(str(definition["name"])) for definition in CONCEPT_DEFINITIONS}


def item(item_id, name, *parameters, price=100.0):
    return {"id": item_id, "code": item_id, "name": name, "price": price, "final_price": price, "fees": [],
            "parameters": [{"id": pid, "name": pname} for pid, pname in parameters], "synonyms": []}


def keys(lab, *items, aliases=None, learned=None):
    return {i["id"]: i for i in testplan.keyed(list(items), lab, lab.title(), aliases or {}, learned or {}, {})}


# --- names -------------------------------------------------------------------------


def test_cyrillic_homoglyphs_and_learned_aliases_meet():
    # A learned alias spelled in Latin finds the catalogue's Cyrillic «МСН».
    aliases = {"індекс еритроцитів (mch)": [("Synevo", "mean-corpuscular-hemoglobin")]}
    got = keys("esculab", item("1", "ЗАК", ("901", "Індекс еритроцитів (МСН)"), ("902", "Інше")), aliases=aliases)
    assert got["1"]["parameter_keys"][0] == ["mean-corpuscular-hemoglobin"]


def test_bracketed_codes_and_serum_qualifiers():
    got = keys("esculab",
               item("1", "Калій (сироватка)", ("901", "Калій (сироватка)")),
               item("2", "РФ", ("902", "Ревматоїдний фактор (РФ)")),
               item("3", "Ретикулоцити", ("903", "Гемоглобін (RET-He)")),
               item("4", "Анти-MCV", ("904", "Цитрульований віментин (MCV), антитіла IgG")),
               item("5", "Протромбін", ("905", "Протромбіновий тест (ПЧ, % за Квіком, МНВ / INR)")),
               item("6", "Гени", ("906", "Панель спадкових форм раку (ALK, EGFR, NGS)")))
    assert got["1"]["keys"] == ["potassium"]
    assert got["2"]["keys"] == ["rheumatoid-factor"]          # «РФ» is its initialism
    assert got["3"]["keys"] == ["esculab:903"]                # reticulocyte haemoglobin is not haemoglobin
    assert got["4"]["keys"] == ["esculab:904"]                # anti-MCV is not mean corpuscular volume
    assert got["5"]["keys"] == ["esculab:905"]                # three analytes in one bracket name none
    assert got["6"]["keys"] == ["esculab:906"]                # the EGFR gene is not the eGFR


def test_search_synonyms_are_not_names():
    genetics = {**item("1", "Генетична панель «DNA Skin»", ("901", "Генетична панель «DNA Skin»")), "synonyms": ["CRP"]}
    assert keys("esculab", genetics)["1"]["keys"] == ["esculab:901"]


def test_curated_wrong_resolutions_keep_the_labs_key():
    got = keys("synevo", item("9326", "Анти-MCV", ("9326", "Цитрульований віментин (MCV), антитіла IgG")),
               item("10019", "hs-CRP", ("10019", "C-реактивний білок, високочутливий (C-Reactive Protein, High Sensitivity)")))
    assert got["9326"]["keys"] == ["synevo:9326"]
    assert got["10019"]["keys"] == ["high-sensitivity-c-reactive-protein"]


# --- specimens ---------------------------------------------------------------------


def test_urine_and_blood_stay_apart():
    urinalysis = item("1", "Аналіз добової сечі на білок, глюкозу та кетони", ("310", "глюкоза"), ("309", "білок"))
    package = item("2", "Пакет №1. Стандартний", ("310", "глюкоза"), ("32", "Глюкоза (сироватка)"), ("280", "Лейкоцити (WBC)"))
    got = keys("esculab", urinalysis, package)
    # The package's «глюкоза» is the urinalysis's: the smallest item listing it says urine.
    assert got["2"]["parameter_keys"] == [["urine-glucose"], ["blood-glucose"], ["white-blood-cell-count"]]
    assert keys("synevo", item("1175", "Креатинін (сеча)", ("1175", "Креатинін (сеча)")))["1175"]["keys"] != ["creatinine"]
    assert keys("synevo", item("1", "Сечова кислота", ("1", "Сечова кислота")))["1"]["keys"] == ["uric-acid"]


def test_a_24_hour_collection_never_covers_spot_urine():
    daily = {**item("F6003", "Аналіз добової сечі на білок, глюкозу та кетони", ("310", "глюкоза"), ("309", "білок")),
             "material": ["сеча (добова)"]}
    package = {**item("M0537", "Програма «Перед щепленням»", ("310", "глюкоза"), ("308", "реакція"),
                      ("935", "еритроцити свіжі"), ("318", "циліндри"), ("312", "лейкоцити")),
               "material": ["цільна кров", "сеча"]}
    automated = item("F6001", "ЗАС автоматизований", ("1114", "Каламутність(рівень) (C-CLOUD)"), ("1106", "Глюкоза (C-GLU)"))
    got = keys("esculab", daily, package, automated)
    assert got["F6003"]["keys"] == ["esculab:24h:310", "esculab:24h:309"]
    assert got["M0537"]["parameter_keys"] == [["urine-glucose"], ["urine-ph"], ["urine-erythrocytes-unchanged"],
                                              ["total-casts-in-urine"], ["esculab:312"]]
    assert got["F6001"]["keys"] == ["urine-appearance", "urine-glucose"]


def test_fee_ids_get_the_lab_prefix_once():
    fees = [{"id": "370", "name": "Відбір", "price": 80.0}, {"id": "synevo:intake:6001", "name": "Забір", "price": 90.0}]
    got = keys("synevo", {**item("1", "Тест", ("1", "Тест")), "fees": fees})["1"]
    assert [fee["id"] for fee in got["fees"]] == ["synevo:370", "synevo:intake:6001"]


def test_the_coprogram_covers_its_findings_only():
    got = keys("esculab", item("F9014", "Копрограма", ("1490", "Копрограма")))["F9014"]["keys"]
    assert "stool-ph" in got and "stool-helminth-eggs" in got and set(got) <= SEEDED
    assert len(got) == len(testplan.WHOLE_TESTS["копрограма"])


def test_headings_and_notes_measure_nothing():
    got = keys("esculab", item("1", "ЗАС", ("1106", "Глюкоза (C-GLU)"), ("1142", "Мікроскопія сечі"),
                               ("1143", "Примітки (зас)")))
    assert got["1"]["parameter_keys"] == [["urine-glucose"], [], []]
    assert got["1"]["keys"] == ["urine-glucose"]


def test_whole_examinations_and_derived_keys():
    zak = item("4018", "ЗАК", ("name:ahaлiзkpobipoзгophytий(зak)", "Аналіз крові розгорнутий (ЗАК)"))
    assert {"hemoglobin", "platelet-count", "neutrophils-absolute"} <= set(keys("synevo", zak)["4018"]["keys"])
    creatinine = keys("esculab", item("247", "Креатинін", ("247", "Креатинін")))["247"]["keys"]
    assert creatinine == ["creatinine", "estimated-glomerular-filtration-rate-ckd-epi-2021"]


# --- across labs -------------------------------------------------------------------


def test_one_unmapped_analyte_at_two_labs_is_one_requirement():
    esculab = keys("esculab", item("A2006", "Лютеїнізуючий гормон (ЛГ, LH)", ("18", "Лютеїнізуючий гормон (ЛГ)"),
                                   price=300.0))["A2006"]
    synevo = keys("synevo", item("1009", "Лютеїнізуючий гормон (ЛГ)", ("1009", "Лютеїнізуючий гормон (ЛГ)"),
                                 price=250.0))["1009"]
    assert esculab["keys"] == synevo["keys"] == ["x:luteinizing-hormone"]
    plan = testplan.optimise([esculab, synevo], {"x:luteinizing-hormone"})
    assert [chosen["id"] for chosen in plan["items"]] == ["1009"] and not plan["missing"]
    assert not testplan.optimise([esculab], {"x:luteinizing-hormone"})["missing"]


def test_specific_ige_meets_by_allergen_code_and_molecule():
    assert testplan_aliases.allergen_key("алерген арахіс (f13), специфічні IgE") == "x:sige:f13"
    assert testplan_aliases.allergen_key("Алерген. Екстракт. Арахіс (земляний горіх, f13), антитіла IgE") == "x:sige:f13"
    assert testplan_aliases.allergen_key("Пеніцилін V (с2) Пеніцилін V (с2), специфічні IgE") == "x:sige:c2"
    assert (testplan_aliases.allergen_key("Алергокомпонент берези rBet v1 PR-10, sIgE (t215)")
            == testplan_aliases.allergen_key("Алерген. Молекула. Береза (rBet v1), антитіла IgE") == "x:sige:bet-v-1")
    assert testplan_aliases.allergen_key("Загальний Ig E") is None
    assert testplan_aliases.allergen_key("Алерген f13, антитіла IgG4") is None


# --- the curated table itself --------------------------------------------------------


def test_no_parameter_is_curated_twice_or_to_two_concepts():
    seen = {}
    tables = [(key, (concept,)) for key, (concept, _) in testplan_aliases.CONCEPTS.items()]
    tables += [(key, ()) for key in testplan_aliases.UNMAPPED]
    tables += [((lab, pid), (shared,)) for shared, members in testplan_aliases.SAME.items() for lab, pid, _ in members]
    tables += [(key, keys) for key, (keys, _) in testplan_aliases.WHOLE.items()]
    for key, targets in tables:
        assert key not in seen, f"{key} is curated as {seen[key]} and {targets}"
        seen[key] = targets
    assert seen == {key: tuple(value) for key, value in testplan_aliases.CURATED.items()}


def test_curated_concepts_exist_and_shared_keys_do_not_hide_one():
    named = [concept for concept, _ in testplan_aliases.CONCEPTS.values()]
    named += [key for keys, _ in testplan_aliases.WHOLE.values() for key in keys if ":" not in key]
    named += [key for implied in testplan_aliases.IMPLIED.values() for key in implied]
    named += list(testplan_aliases.IMPLIED)
    assert set(named) <= SEEDED
    whole_x = {key for keys, _ in testplan_aliases.WHOLE.values() for key in keys if key.startswith("x:")}
    assert whole_x <= set(testplan_aliases.SAME)
    for shared, members in testplan_aliases.SAME.items():
        assert shared.startswith("x:") and members
        for lab, _, name in members:
            # A shared key stands for something we have no concept for; once
            # a concept exists, the entry belongs in CONCEPTS instead.
            found = testplan.resolve(name, name, lab, {}, None)
            assert found is None or testplan_aliases.DISTINCT_FROM.get(shared, ("",))[0] == found, (shared, name)


@pytest.mark.parametrize("lab,parameter,name,target", [
    ("synevo", "1011", "Пролактин", "prolactin"),
    ("esculab", "20", "Пролактин (ПРЛ)", "prolactin"),
    ("synevo", "1015", "Естрадіол (E2)", "estradiol"),
    ("synevo", "1020", "Кортизол (сироватка)", "cortisol"),
    ("esculab", "36", "Індекс HOMA", "homa-index-reported-model-unspecified"),
    ("synevo", "1033", "β-ХГЛ загальний (хоріонічний гонадотропін загальний)", "total-beta-hcg"),
    ("esculab", "58", "Хоріонічний гонадотропін (пренатальна діагностика 12-21тв)", "total-beta-hcg"),
    ("esculab", "298", "Д-димер", "d-dimer"),
    ("synevo", "1606", "α-Амілаза панкреатична", "pancreatic-amylase"),
    ("synevo", "1038", "Імуноглобулін A (IgA, сироватка)", "total-immunoglobulin-a"),
    ("esculab", "141", "Сумарні (Ig A, Ig M, Ig G) до лямблій", "giardia-total-antibodies"),
    ("synevo", "2058", "Ascaris lumbricoides, антитіла IgG", "ascaris-igg-antibodies"),
    ("esculab", "143", "Антитіла Іg G до токсокар (Toxocara)", "toxocara-igg-antibodies"),
    ("synevo", "9169", "Гліадин, антитіла IgG", "gliadin-igg-antibodies"),
    ("synevo", "2108", "Тканинна трансглутаміназа, антитіла IgG", "tissue-transglutaminase-igg-antibodies"),
    ("esculab", "2885", "альбумін", "albumin-fraction"),
])
def test_seeded_metrics_are_orderable_by_their_own_requirement(lab, parameter, name, target):
    offering = keys(lab, item("offering", name, (parameter, name)))["offering"]
    assert offering["parameter_keys"] == [[target]]
    assert testplan.optimise([offering], {target})["missing"] == []


def test_seeded_coeliac_members_reach_whole_panel_coverage():
    offering = keys("esculab", item("coeliac", "Панель Целіакія", ("341", "Панель Целіакія")))["coeliac"]
    assert "tissue-transglutaminase-igg-antibodies" in offering["keys"]
    offering = keys("esculab", item("coeliac2", "Панель Целіакія 2", ("342", "Панель Целіакія 2")))["coeliac2"]
    assert "total-immunoglobulin-a" in offering["keys"]


def test_assay_fraction_specimen_and_model_distinctions_remain_orderable_separately():
    offerings = keys("esculab",
                     item("cortisol", "Кортизол", ("27", "Кортизол")),
                     item("saliva", "Кортизол (слина)", ("1549", "Кортизол (слина)")),
                     item("total", "ХГЛ", ("57", "Хоріонічний гонадотропін (бета-ХГЛ)")),
                     item("free", "Вільна бета-ХГЛ", ("47", "Вільний Бета-ХГЛ (8-13 тиждень вагітності)")),
                     item("gliadin", "Гліадин IgG", ("339", "антиГліадин (Gliadin) IgG")),
                     item("deamidated", "Деамінований гліадин IgG", ("2017", "Антитіла IgG до гліадину (деамінізовані пептиди), ELiA")),
                     item("homa2", "Індекс HOMA", ("unknown-homa2", "Індекс HOMA2")))
    assert offerings["cortisol"]["keys"] == ["cortisol"]
    assert offerings["saliva"]["keys"] == ["x:cortisol-saliva"]
    assert offerings["total"]["keys"] == ["total-beta-hcg"]
    assert offerings["free"]["keys"] == ["x:hcg-free-beta"]
    assert offerings["gliadin"]["keys"] == ["gliadin-igg-antibodies"]
    assert offerings["deamidated"]["keys"] == ["x:gliadin-deamidated-igg"]
    assert offerings["homa2"]["keys"] == ["esculab:unknown-homa2"]


def test_specific_parameters_are_never_replaced_by_a_generic_order_title():
    offerings = keys("esculab",
                     item("retic", "Ретикулоцити", ("unknown-rethe", "Гемоглобін (RET-He)")),
                     item("saliva", "Кортизол", ("unknown-saliva", "Кортизол (слина)")),
                     item("serology", "Helicobacter pylori", ("unknown-igg", "Ig G до Хелікобактер пілорі (Helicobacter Pylori)")),
                     item("breath", "Helicobacter pylori", ("unknown-breath", "Дихальний тест (Helicobacter pylori)")),
                     item("placeholder", "Калій", ("unknown-placeholder", "Результат")))
    assert offerings["retic"]["keys"] == ["esculab:unknown-rethe"]
    assert offerings["saliva"]["keys"] == ["esculab:unknown-saliva"]
    assert offerings["serology"]["keys"] == ["esculab:unknown-igg"]
    assert offerings["breath"]["keys"] == ["esculab:unknown-breath"]
    assert offerings["placeholder"]["keys"] == ["potassium"]
