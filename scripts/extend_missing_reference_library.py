"""Public, sourced definitions for laboratory targets found by the catalog audit.

This module never reads patient records. It does not adopt the performing
laboratories' assay-specific numerical cutoffs as universal intervals.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from anamna.ingest.concepts import CONCEPT_DEFINITIONS, stable_concept_id

REVIEWED_AT = "2026-11-15"


def _source(key, region, publisher, name, url, identifier, *, official=True,
            kind="clinical_publication", note=None):
    result = dict(id=key, region=region, publisher=publisher, name=name, url=url,
                  identifier=identifier, reviewed_at=REVIEWED_AT, official=official, kind=kind)
    if note:
        result["access_note"] = note
    return result


def _catalogue(key, region, publisher, name, url, identifier, *, note=None):
    """A laboratory's own test catalogue or sample form: never an official body's publication."""
    return _source(key, region, publisher, name, url, identifier,
                   official=False, kind="laboratory_catalogue", note=note)


SOURCES = [
    _catalogue("mayo-amh1-2026", "US", "Mayo Clinic Laboratories", "Antimullerian Hormone, Serum",
            "https://www.mayocliniclabs.com/test-catalog/Overview/608824", "AMH1; test 608824"),
    _catalogue("mayo-eest-2026", "US", "Mayo Clinic Laboratories", "Estradiol, Serum",
            "https://www.mayocliniclabs.com/test-catalog/overview/81816", "EEST; test 81816"),
    _catalogue("mayo-prl-2026", "US", "Mayo Clinic Laboratories", "Prolactin, Serum",
            "https://www.mayocliniclabs.com/test-catalog/Overview/85670", "PRL; test 85670"),
    _catalogue("mayo-cort-2026", "US", "Mayo Clinic Laboratories", "Cortisol, Serum",
            "https://www.mayocliniclabs.com/test-catalog/overview/8545", "CORT; test 8545"),
    _catalogue("mayo-amiso-2026", "US", "Mayo Clinic Laboratories", "Amylase, Isoenzymes, Serum",
            "https://www.mayocliniclabs.com/test-catalog/overview/604930", "AMISO; test 604930"),
    _catalogue("mayo-iga-2026", "US", "Mayo Clinic Laboratories", "Immunoglobulin A (IgA), Serum",
            "https://www.mayocliniclabs.com/test-catalog/overview/8157", "IGA; test 8157"),
    _catalogue("mayo-ttgg-2026", "US", "Mayo Clinic Laboratories", "Tissue Transglutaminase Antibody, IgG, Serum",
            "https://www.mayocliniclabs.com/test-catalog/overview/800355", "TTGG; test 800355"),
    _catalogue("mayo-ema-2026", "US", "Mayo Clinic Laboratories", "Endomysial Antibodies, IgA, Serum",
            "https://www.mayocliniclabs.com/test-catalog/Overview/9360", "EMA; test 9360"),
    _catalogue("synevo-gliadin-igg-9169", "UA", "Сінево Україна", "Гліадин, антитіла IgG",
            "https://www.synevo.ua/tests/9169", "Дослідження 9169",
            note="Used to identify the reported native/unspecified gliadin IgG assay, not to substitute it for deamidated gliadin peptide IgG or endorse screening claims."),
    _catalogue("synevo-ascaris-igg-2058", "UA", "Сінево Україна", "Ascaris lumbricoides, антитіла IgG",
            "https://www.synevo.ua/tests/2058", "Дослідження 2058"),
    _source("cdc-toxocariasis-2026", "US", "Centers for Disease Control and Prevention", "Clinical Overview of Toxocariasis",
            "https://www.cdc.gov/toxocariasis/hcp/clinical-overview/index.html", "CDC clinical overview: toxocariasis"),
    _catalogue("synevo-giardia-total-2056", "UA", "Сінево Україна", "Giardia (лямблії), антитіла сумарні",
            "https://www.synevo.ua/tests/2056", "Дослідження 2056"),
    _catalogue("dila-giardia-total-2026", "UA", "Медична лабораторія ДІЛА", "Антитіла до Giardia lamblia сумарні: зразок результату",
            "https://dila.ua/labdir/get-file-example/10749.html", "ДІЛА дослідження 10749; published sample report",
            note="Public laboratory sample, not a patient record. Notes low serological specificity and possible cross-reactions."),
    _source("cdc-syphilis-laboratory-2024", "US", "Centers for Disease Control and Prevention", "CDC Laboratory Recommendations for Syphilis Testing, United States, 2024",
            "https://www.cdc.gov/mmwr/volumes/73/rr/rr7301a1.htm", "MMWR 2024;73(RR-1):1-32"),
    _catalogue("medlab-folate-genotypes-6111", "UA", "МедЛаб", "Генетика метаболізму фолатів, методом ПЛР",
            "https://medlabtest.ua/uk/patients/analizy/genetika-metabolizma-folatov-plazma-edta-metodom-pcr", "Дослідження 6111",
            note="Used only for names and identities of MTHFR C677T/A1298C, MTR A2756G and MTRR A66G. The provider's broad disease-risk claims and numerical enzyme-activity estimates are not adopted."),
    _source("cdc-mthfr-facts-2026", "US", "Centers for Disease Control and Prevention", "MTHFR Gene Variant and Folic Acid Facts",
            "https://www.cdc.gov/folic-acid/data-research/mthfr/index.html", "CDC MTHFR gene-variant facts, 16 July 2026"),
    _source("oxford-homa-faq-2026", "EU", "University of Oxford Diabetes Trials Unit", "HOMA Calculator: Frequently Asked Questions",
            "https://www.rdm.ox.ac.uk/about/our-facilities-and-units/DTU/software/homa/faq", "HOMA Calculator FAQ, questions 3 and 10",
            note="Page read in full on 2026-11-15. Question 3: HOMA is a steady-state model, so only values seen in a fasting subject should be used. Question 10: there are no defined thresholds for normal and abnormal HOMA values, because they depend on the glucose, insulin and C-peptide assays. No numerical cutoff or model conversion is adopted."),
    _source("fda-roma-k103358", "US", "US Food and Drug Administration", "ROMA: Indications for Use",
            "https://www.accessdata.fda.gov/cdrh_docs/pdf10/k103358.pdf", "510(k) K103358"),
    _source("nice-roma-htg453", "EU", "National Institute for Health and Care Excellence", "Tests in secondary care to identify people at high risk of ovarian cancer: diagnostic tests",
            "https://www.nice.org.uk/guidance/htg453/chapter/the-diagnostic-tests", "HTG453, section 3"),
    _source("fda-total-beta-hcg-k233581", "US", "US Food and Drug Administration", "VITROS Total beta-hCG II: substantial equivalence determination",
            "https://www.accessdata.fda.gov/cdrh_docs/reviews/K233581.pdf", "510(k) K233581"),
    _source("wgo-h-pylori-2021", "INT", "World Gastroenterology Organisation", "Global Guideline: Helicobacter pylori",
            "https://www.worldgastroenterology.org/UserFiles/file/guidelines/helicobacter-pylori-english-2021.pdf", "WGO Global Guidelines, Helicobacter pylori, May 2021"),
]

# Canonical name, Ukrainian name, cited sources, definition EN/UK, context EN/UK.
DEFINITIONS = (
    ("Total beta-hCG", "Загальний бета-ХГЛ (хоріонічний гонадотропін людини)", ("fda-total-beta-hcg-k233581",),
     "A quantitative human chorionic gonadotropin measurement reported as total beta-hCG.",
     "Кількісне визначення хоріонічного гонадотропіну людини, повідомлене як загальний бета-ХГЛ.",
     "Interpret with the assay, pregnancy context and laboratory report. Total beta-hCG is distinct from a free beta-subunit measurement; no pregnancy week or diagnosis is inferred from one value.",
     "Оцінюйте разом із методом, контекстом вагітності та лабораторним висновком. Загальний бета-ХГЛ відрізняється від вільної бета-субодиниці; за одним значенням не визначають термін вагітності чи діагноз."),
    ("Anti-Mullerian hormone", "Антимюллерів гормон (АМГ)", ("mayo-amh1-2026",),
     "A hormone produced by ovarian granulosa cells and testicular Sertoli cells, measured in blood.",
     "Гормон, що утворюється в гранульозних клітинах яєчників та клітинах Сертолі яєчок і визначається в крові.",
     "Its meaning depends on age, sex and clinical purpose. AMH assays are not standardized: an Advanced assay label is retained, and results from different methods are not treated as interchangeable.",
     "Значення залежить від віку, статі та мети дослідження. Методи визначення АМГ не стандартизовані: позначку Advanced зберігають, а результати різних методів не вважають взаємозамінними."),
    ("Estradiol", "Естрадіол", ("mayo-eest-2026",),
     "A circulating estrogen hormone measured to assess reproductive and endocrine function.",
     "Естрогенний гормон крові, який визначають для оцінки репродуктивної та ендокринної функції.",
     "Interpret with age, sex, menstrual or menopausal stage, medicines and the assay. A single universal interval does not cover these contexts.",
     "Оцінюйте з урахуванням віку, статі, фази циклу або менопаузи, ліків і методу. Один універсальний інтервал не охоплює ці обставини."),
    ("Prolactin", "Пролактин", ("mayo-prl-2026",),
     "A pituitary hormone involved in milk production and reproductive regulation.",
     "Гормон гіпофіза, що бере участь в утворенні молока та регуляції репродуктивної функції.",
     "Pregnancy, physiological stress, medicines, macroprolactin and assay interference can affect the result. Use the report's assay-specific interpretation and clinical context.",
     "На результат можуть впливати вагітність, фізіологічний стрес, ліки, макропролактин та інтерференція методу. Враховуйте лабораторне тлумачення для цього методу та клінічний контекст."),
    ("Cortisol", "Кортизол", ("mayo-cort-2026",),
     "An adrenal steroid hormone measured in blood to assess adrenal function.",
     "Стероїдний гормон надниркових залоз, який визначають у крові для оцінки їхньої функції.",
     "Collection time and whether this was a baseline, stimulation or suppression sample are essential. Blood cortisol must stay separate from salivary or urinary free cortisol.",
     "Важливі час забору та тип проби: базальна, стимуляційна або супресійна. Кортизол крові зберігається окремо від кортизолу слини та вільного кортизолу сечі."),
    ("Pancreatic amylase", "Панкреатична амілаза", ("mayo-amiso-2026",),
     "The pancreatic isoenzyme component of amylase activity in blood.",
     "Активність панкреатичного ізоферменту амілази в крові.",
     "Read with total amylase and clinical findings. Pancreatic and salivary isoenzymes are different components; pancreatic amylase is not an alias for total alpha-amylase.",
     "Оцінюйте разом із загальною амілазою та клінічними даними. Панкреатичний і слинний ізоферменти — різні компоненти; панкреатична амілаза не є іншою назвою загальної альфа-амілази."),
    ("Total immunoglobulin A", "Загальний імуноглобулін A (IgA)", ("mayo-iga-2026",),
     "The total concentration of immunoglobulin A antibodies in serum.",
     "Загальна концентрація антитіл класу імуноглобуліну A в сироватці.",
     "Used in immune evaluation and to help interpret IgA-based celiac tests. Total IgA is distinct from an IgA antibody directed at a particular antigen; age and the laboratory method matter.",
     "Використовується для оцінки імунітету та тлумачення IgA-тестів на целіакію. Загальний IgA відрізняється від IgA-антитіл до конкретного антигену; важливі вік та лабораторний метод."),
    ("Tissue transglutaminase IgG antibodies", "Антитіла IgG до тканинної трансглутамінази", ("mayo-ttgg-2026",),
     "IgG antibodies directed against tissue transglutaminase, used in celiac disease assessment.",
     "Антитіла IgG до тканинної трансглутамінази, що використовуються під час обстеження на целіакію.",
     "This is a different antibody class from tissue transglutaminase IgA. Read with total IgA, the testing algorithm and the performing assay's interpretation, especially when IgA is deficient.",
     "Це інший клас антитіл, ніж IgA до тканинної трансглутамінази. Оцінюйте разом із загальним IgA, алгоритмом обстеження та тлумаченням методу, особливо за дефіциту IgA."),
    ("Endomysial IgA antibodies", "Антитіла IgA до ендомізію", ("mayo-ema-2026",),
     "IgA anti-endomysial antibodies measured during celiac disease assessment.",
     "Антитіла IgA до ендомізію, які визначають під час обстеження на целіакію.",
     "A qualitative screen and a dilution titer describe different aspects of the assay. Preserve the laboratory's wording and titer rather than converting a titer into an antibody concentration.",
     "Якісний скринінг і титр розведення описують різні аспекти дослідження. Зберігайте лабораторне формулювання та титр, не перетворюючи його на концентрацію антитіл."),
    ("Gliadin IgG antibodies", "Антитіла IgG до гліадину", ("synevo-gliadin-igg-9169",),
     "IgG antibodies directed against gliadin, a component of gluten.",
     "Антитіла IgG до гліадину — складової глютену.",
     "This label does not establish a deamidated gliadin peptide assay. Keep it separate from that test and use the laboratory's method and interpretation instead of borrowing another assay's cutoff.",
     "Ця назва не доводить використання тесту на деамідовані пептиди гліадину. Зберігайте показник окремо та використовуйте метод і тлумачення лабораторії, не запозичуючи меж іншого тесту."),
    ("Ascaris IgG antibodies", "Антитіла IgG до Ascaris lumbricoides", ("synevo-ascaris-igg-2058",),
     "IgG antibodies against Ascaris lumbricoides measured by the reporting laboratory.",
     "Антитіла IgG до Ascaris lumbricoides, визначені лабораторією.",
     "Antibodies can reflect current or previous exposure. This serology is not a stool parasite count and does not independently prove active infection; preserve the assay's own interpretation.",
     "Антитіла можуть відображати поточний або перенесений контакт. Це не кількість паразитів у калі й не самостійний доказ активної інфекції; зберігайте тлумачення конкретного методу."),
    ("Toxocara IgG antibodies", "Антитіла IgG до Toxocara", ("cdc-toxocariasis-2026",),
     "IgG antibodies against Toxocara used with exposure history and clinical findings.",
     "Антитіла IgG до Toxocara, які оцінюють разом з історією контакту та клінічними даними.",
     "Detectable antibodies may reflect past infection, and a serum result alone does not establish current disease. Ocular disease may have low or absent serum antibodies.",
     "Виявлені антитіла можуть відображати перенесену інфекцію; результат сироватки сам по собі не доводить поточного захворювання. За ураження очей антитіл у сироватці може бути мало або не бути."),
    ("Giardia total antibodies", "Сумарні антитіла до Giardia lamblia", ("synevo-giardia-total-2056", "dila-giardia-total-2026"),
     "Combined antibody reactivity to Giardia lamblia, as reported by the assay.",
     "Сумарна реактивність антитіл до Giardia lamblia за повідомленням методу.",
     "Antibody testing is distinct from stool antigen or microscopic detection. Serological cross-reactions can limit specificity; this result alone is not confirmation of active giardiasis.",
     "Дослідження антитіл відрізняється від виявлення антигену або паразита в калі. Перехресні серологічні реакції можуть обмежувати специфічність; один такий результат не підтверджує активного лямбліозу."),
    ("Syphilis non-treponemal screening test", "Нетрепонемний скринінговий тест на сифіліс", ("cdc-syphilis-laboratory-2024",),
     "A non-treponemal serological screening reaction, such as a reported microprecipitation test.",
     "Нетрепонемна серологічна скринінгова реакція, зокрема повідомлена реакція мікропреципітації.",
     "Non-treponemal and treponemal tests measure different antibody reactions and are interpreted together. A reactive screen alone does not establish the diagnosis; keep its method and titer if reported.",
     "Нетрепонемні й трепонемні тести визначають різні реакції антитіл та оцінюються разом. Реактивний скринінг сам по собі не встановлює діагнозу; зберігайте метод і титр, якщо їх повідомлено."),
    ("HOMA index (reported, model unspecified)", "Індекс HOMA (повідомлений, модель не зазначена)", ("oxford-homa-faq-2026",),
     "A laboratory-reported homeostasis model assessment index for which the model version is not stated.",
     "Повідомлений лабораторією індекс гомеостатичної моделі оцінки, версію якої не зазначено.",
     "HOMA uses fasting steady-state inputs. An unspecified reported index is not silently relabeled HOMA1-IR or HOMA2-IR, and is not recalculated from nonfasting glucose or an assumed model.",
     "HOMA використовує показники натще у сталому стані. Індекс без зазначеної моделі не перейменовується автоматично на HOMA1-IR або HOMA2-IR і не перераховується з глюкози не натще чи за припущеною моделлю."),
    ("ROMA, premenopausal", "ROMA для пременопаузи", ("fda-roma-k103358", "nice-roma-htg453"),
     "The premenopausal Risk of Ovarian Malignancy Algorithm result combining HE4 and CA 125 with menopausal status.",
     "Результат алгоритму ризику злоякісності яєчників ROMA для пременопаузи, що поєднує HE4, CA 125 і менопаузальний статус.",
     "Intended to assist assessment of a known adnexal mass in a surgical evaluation, not population screening or a stand-alone diagnosis. Assay-specific scales and cutoffs differ; preserve the reported premenopausal result separately.",
     "Допомагає оцінювати відоме утворення придатків у межах підготовки до операції, а не для популяційного скринінгу чи самостійного діагнозу. Шкали й межі залежать від методів; результат для пременопаузи зберігається окремо."),
    ("ROMA, postmenopausal", "ROMA для постменопаузи", ("fda-roma-k103358", "nice-roma-htg453"),
     "The postmenopausal Risk of Ovarian Malignancy Algorithm result combining HE4 and CA 125 with menopausal status.",
     "Результат алгоритму ризику злоякісності яєчників ROMA для постменопаузи, що поєднує HE4, CA 125 і менопаузальний статус.",
     "Intended for assessment of a known adnexal mass alongside clinical and imaging findings. The postmenopausal equation differs from the premenopausal equation, and the assay's reported scale must be retained.",
     "Призначений для оцінки відомого утворення придатків разом із клінічними даними та візуалізацією. Формула для постменопаузи відрізняється від формули для пременопаузи; слід зберігати повідомлену шкалу методу."),
    ("H. pylori test, method unspecified", "Тест на H. pylori, метод не зазначено", ("wgo-h-pylori-2021",),
     "A reported Helicobacter pylori test whose source does not establish the test method.",
     "Повідомлений тест на Helicobacter pylori, джерело якого не встановлює метод дослідження.",
     "Breath testing, stool antigen, antibody testing and biopsy-based methods detect different evidence. Keep an unspecified result separate until the source identifies the method; do not infer it from nearby tests.",
     "Дихальні тести, антиген калу, антитіла та біопсійні методи виявляють різні докази. Зберігайте невизначений результат окремо, доки джерело не уточнить метод; не визначайте його за сусідніми тестами."),
)

GENOTYPES = (
    ("MTHFR C677T genotype", "Генотип MTHFR C677T", "MTHFR", "C677T"),
    ("MTHFR A1298C genotype", "Генотип MTHFR A1298C", "MTHFR", "A1298C"),
    ("MTR A2756G genotype", "Генотип MTR A2756G", "MTR", "A2756G"),
    ("MTRR A66G genotype", "Генотип MTRR A66G", "MTRR", "A66G"),
)


def additions() -> list[dict]:
    definitions = {item["name"]: item for item in CONCEPT_DEFINITIONS}
    sources = {item["id"]: item for item in SOURCES}
    rows = list(DEFINITIONS)
    for name, uk_name, gene, variant in GENOTYPES:
        citations = ("medlab-folate-genotypes-6111", "cdc-mthfr-facts-2026") if gene == "MTHFR" else ("medlab-folate-genotypes-6111",)
        rows.append((name, uk_name, citations,
                     f"The reported DNA genotype at the {variant} variant of the {gene} gene, part of folate-related metabolism.",
                     f"Повідомлений генотип ДНК для варіанта {variant} гена {gene}, що бере участь в обміні фолатів.",
                     "A genotype records an inherited variant, not a nutrient level or a diagnosis. Preserve the laboratory's allele notation and method; no numerical reference interval or disease-risk verdict is assigned.",
                     "Генотип описує успадкований варіант, а не рівень поживної речовини чи діагноз. Зберігайте лабораторне позначення алелів і метод; числовий референтний інтервал або висновок про ризик захворювання не встановлюється."))
    entries = []
    for name, uk_name, ids, description, uk_description, context, uk_context in rows:
        if name not in definitions:
            raise ValueError(f"Catalog definition must be added before reference guidance: {name}")
        entry = dict(concept_id=stable_concept_id(name), canonical_name=name,
                     unit=definitions[name]["unit"], kind="no_universal_target", bands=[],
                     source_ids=list(ids), source_id=ids[0],
                     regions_covered=sorted({sources[key]["region"] for key in ids}),
                     # One source, or several that agree no universal target exists.
                     agreement="single_source" if len(ids) == 1 else "concordant",
                     short_description=description, why_it_matters=context,
                     retest_interval_months=None, retest_rationale=None,
                     uk=dict(name=uk_name, short_description=uk_description,
                             why_it_matters=uk_context, band_labels={}))
        if name.startswith("ROMA"):
            entry["jurisdiction_note"] = "FDA-cleared and NICE-described ROMA implementations use assay-specific scales and decision cutoffs. No cutoff is transferred between them."
            entry["uk"]["jurisdiction_note"] = "Схвалені FDA та описані NICE реалізації ROMA мають шкали й межі рішень, залежні від методу. Межі не переносять між ними."
        if name.endswith(" genotype"):
            entry["not_a_measurement"] = True
            entry["never_verdict"] = True
        entries.append(entry)
    return entries


def extend(library: dict) -> dict[str, int]:
    """Add only absent public entries; preserve every existing band and source."""
    known_sources = {item["id"] for item in library["sources"]}
    known_analytes = {item["concept_id"] for item in library["analytes"]}
    sources = [copy.deepcopy(item) for item in SOURCES if item["id"] not in known_sources]
    entries = [item for item in additions() if item["concept_id"] not in known_analytes]
    library["sources"].extend(sources)
    library["analytes"].extend(entries)
    return {"sources_added": len(sources), "analytes_added": len(entries)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=Path("data/reference_library.json"))
    args = parser.parse_args()
    library = json.loads(args.library.read_text(encoding="utf-8"))
    counts = extend(library)
    args.library.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
