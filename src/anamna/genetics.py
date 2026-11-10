"""/genetics: what DNA tests a person has and what the common ones answer.

Two jobs, kept apart on the page:

* the record's results about the person's own genes (HLA-B27 and the like),
  told apart from results that only carry «ДНК» in their name: a PCR test
  finds a germ's DNA, a dsDNA test finds antibodies; neither reads a gene;
* the genetic tests the planner offers (``testplan_special`` topic
  ``genetics``), grouped by what they are for, each with who it helps, when
  it does not, where the guidelines differ, the price and its sources.

Every explanation is a message (``messages_genetics``); this module holds
which sources back it.  Sources were fetched and read in November 2026;
Ukrainian ones are Ukrainian-authored (dec.gov.ua, zakon.rada.gov.ua) or are
flagged as the Duodecim translation (guidelines.moz.gov.ua, Finnish
originals of 2014-2018).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import testplan, testplan_special
from .reference import _text_keys


@dataclass(frozen=True)
class Source:
    region: str  # US / EU / UA / INT
    publisher: str
    name: str
    url: str
    identifier: str = ""
    #: A Ukrainian translation of a Finnish Duodecim guideline, not a
    #: Ukrainian-authored document.
    duodecim: bool = False


_MP = "U.S. National Library of Medicine, MedlinePlus Genetics"
_MOZ = "Міністерство охорони здоров’я України"
_DUO = "МОЗ України / Duodecim Medical Publications"
_DPWG = "Dutch Pharmacogenetics Working Group (KNMP)"

SOURCES: dict[str, Source] = {
    # general
    "medlineplus-dna": Source("US", _MP, "What is DNA?", "https://medlineplus.gov/genetics/understanding/basics/dna/"),
    "cdc-genetic-testing": Source("US", "Centers for Disease Control and Prevention", "Genetic Testing",
                                  "https://www.cdc.gov/genomics-and-health/counseling-testing/genetic-testing.html"),
    "fda-dtc-tests": Source("US", "U.S. Food and Drug Administration", "Direct-to-Consumer Tests",
                            "https://www.fda.gov/medical-devices/in-vitro-diagnostics/direct-consumer-tests"),
    "eshg-dtc-2010": Source("EU", "European Society of Human Genetics",
                            "Statement of the ESHG on direct-to-consumer genetic testing for health-related purposes",
                            "https://pmc.ncbi.nlm.nih.gov/articles/PMC3002858/",
                            "Eur J Hum Genet 2010;18:1271-3, doi:10.1038/ejhg.2010.129"),
    "moz-nastanova-01117": Source("UA", _DUO, "Настанова 01117. Генетичне тестування",
                                  "https://guidelines.moz.gov.ua/documents/3831", "ebm01117, 2017", duodecim=True),
    # lactose
    "medlineplus-lactose": Source("US", _MP, "Lactose intolerance",
                                  "https://medlineplus.gov/genetics/condition/lactose-intolerance/"),
    "efsa-lactose-2010": Source("EU", "European Food Safety Authority, NDA Panel",
                                "Scientific Opinion on lactose thresholds in lactose intolerance and galactosaemia",
                                "https://doi.org/10.2903/j.efsa.2010.1777", "EFSA Journal 2010;8(9):1777"),
    "moz-nastanova-00193": Source("UA", _DUO, "Настанова 00193. Непереносимість лактози",
                                  "https://guidelines.moz.gov.ua/documents/3086", "ebm00193, 2018", duodecim=True),
    # celiac
    "medlineplus-celiac": Source("US", _MP, "Celiac disease", "https://medlineplus.gov/genetics/condition/celiac-disease/"),
    "acg-celiac-2023": Source("US", "American College of Gastroenterology",
                              "ACG Guidelines Update: Diagnosis and Management of Celiac Disease",
                              "https://pubmed.ncbi.nlm.nih.gov/36602836/",
                              "Am J Gastroenterol 2023;118:59-76, doi:10.14309/ajg.0000000000002075"),
    "esscd-2019": Source("EU", "European Society for the Study of Coeliac Disease",
                         "ESsCD guideline for coeliac disease and other gluten-related disorders",
                         "https://pmc.ncbi.nlm.nih.gov/articles/PMC6545713/",
                         "United European Gastroenterol J 2019;7:583-613, doi:10.1177/2050640619844125"),
    "espghan-2020": Source("EU", "European Society for Paediatric Gastroenterology, Hepatology and Nutrition",
                           "ESPGHAN Guidelines for Diagnosing Coeliac Disease 2020",
                           "https://pubmed.ncbi.nlm.nih.gov/31568151/",
                           "J Pediatr Gastroenterol Nutr 2020;70:141-156, doi:10.1097/MPG.0000000000002497"),
    "moz-nastanova-00192": Source("UA", _DUO, "Настанова 00192. Целіакія", "https://guidelines.moz.gov.ua/documents/3085",
                                  "ebm00192, 2016", duodecim=True),
    # haemochromatosis
    "medlineplus-hh": Source("US", _MP, "Hereditary hemochromatosis",
                             "https://medlineplus.gov/genetics/condition/hereditary-hemochromatosis/"),
    "acg-hh-2019": Source("US", "American College of Gastroenterology", "ACG Clinical Guideline: Hereditary Hemochromatosis",
                          "https://pubmed.ncbi.nlm.nih.gov/31335359/",
                          "Am J Gastroenterol 2019;114:1202-1218, doi:10.14309/ajg.0000000000000315"),
    "easl-hh-2022": Source("EU", "European Association for the Study of the Liver",
                           "EASL Clinical Practice Guidelines on haemochromatosis",
                           "https://easl.eu/wp-content/uploads/2022/06/PIIS01688278220021121.pdf",
                           "J Hepatol 2022;77:479-502, doi:10.1016/j.jhep.2022.03.033"),
    "moz-nastanova-00519": Source("UA", _DUO, "Настанова 00519. Гемохроматоз", "https://guidelines.moz.gov.ua/documents/3355",
                                  "ebm00519, 2014", duodecim=True),
    # thrombophilia
    "medlineplus-fvl": Source("US", _MP, "Factor V Leiden thrombophilia",
                              "https://medlineplus.gov/genetics/condition/factor-v-leiden-thrombophilia/"),
    "medlineplus-prothrombin": Source("US", _MP, "Prothrombin thrombophilia",
                                      "https://medlineplus.gov/genetics/condition/prothrombin-thrombophilia/"),
    "ash-thrombophilia-2023": Source("US", "American Society of Hematology",
                                     "ASH 2023 guidelines for management of venous thromboembolism: thrombophilia testing",
                                     "https://pmc.ncbi.nlm.nih.gov/articles/PMC10709681/",
                                     "Blood Adv 2023;7:7101-7138, doi:10.1182/bloodadvances.2023010177"),
    "eshre-rpl-2022": Source("EU", "European Society of Human Reproduction and Embryology",
                             "ESHRE guideline: recurrent pregnancy loss, update 2022",
                             "https://www.eshre.eu/-/media/sitecore-files/Guidelines/Recurrent-pregnancy-loss/2022/"
                             "ESHRE-RPL-Guideline-_-Update-2022_-Final-Version-January-2023_v2.pdf",
                             "Hum Reprod Open 2023;hoad002, doi:10.1093/hropen/hoad002"),
    "moz-nastanova-00107": Source("UA", _DUO, "Настанова 00107. Лабораторна оцінка тромбофілії",
                                  "https://guidelines.moz.gov.ua/documents/3010", "ebm00107, 2017", duodecim=True),
    # MTHFR
    "acmg-mthfr-2013": Source("US", "American College of Medical Genetics and Genomics",
                              "ACMG Practice Guideline: lack of evidence for MTHFR polymorphism testing",
                              "https://pubmed.ncbi.nlm.nih.gov/23288205/",
                              "Genet Med 2013;15:153-6, doi:10.1038/gim.2012.165"),
    "acmg-mthfr-2020": Source("US", "American College of Medical Genetics and Genomics",
                              "Addendum: ACMG Practice Guideline: lack of evidence for MTHFR polymorphism testing",
                              "https://pubmed.ncbi.nlm.nih.gov/32533132/",
                              "Genet Med 2020;22:2125, doi:10.1038/s41436-020-0843-0"),
    "medlineplus-mthfr": Source("US", _MP, "MTHFR gene", "https://medlineplus.gov/genetics/gene/mthfr/"),
    # Gilbert
    "medlineplus-gilbert": Source("US", _MP, "Gilbert syndrome", "https://medlineplus.gov/genetics/condition/gilbert-syndrome/"),
    "orphanet-357": Source("EU", "Orphanet (INSERM)", "Gilbert syndrome", "https://www.orpha.net/en/disease/detail/357",
                           "ORPHA:357"),
    "dpwg-irinotecan": Source("EU", _DPWG, "DPWG guideline for the gene-drug interaction between UGT1A1 and irinotecan",
                              "https://www.clinpgx.org/guidelineAnnotation/PA166104951",
                              "Eur J Hum Genet 2023;31:982-987, doi:10.1038/s41431-022-01243-2"),
    "fda-pgx-table": Source("US", "U.S. Food and Drug Administration",
                            "Table of Pharmacogenomic Biomarkers in Drug Labeling",
                            "https://www.fda.gov/drugs/science-and-research-drugs/table-pharmacogenomic-biomarkers-drug-labeling"),
    "moz-nastanova-00214": Source("UA", _DUO, "Настанова 00214. Синдром Жильбера",
                                  "https://guidelines.moz.gov.ua/documents/3104", "ebm00214, 2017", duodecim=True),
    # HLA-B27
    "medlineplus-as": Source("US", _MP, "Ankylosing spondylitis",
                             "https://medlineplus.gov/genetics/condition/ankylosing-spondylitis/"),
    "medlineplus-hla-b": Source("US", _MP, "HLA-B gene", "https://medlineplus.gov/genetics/gene/hla-b/"),
    "asas-axspa-2009": Source("INT", "Assessment of SpondyloArthritis international Society (ASAS)",
                              "ASAS classification criteria for axial spondyloarthritis, part II",
                              "https://pubmed.ncbi.nlm.nih.gov/19297344/", "Ann Rheum Dis 2009;68:777-783"),
    "asas-eular-2022": Source("EU", "ASAS / European Alliance of Associations for Rheumatology (EULAR)",
                              "ASAS-EULAR recommendations for the management of axial spondyloarthritis: 2022 update",
                              "https://pubmed.ncbi.nlm.nih.gov/36270658/"),
    "acr-axspa-2019": Source("US", "American College of Rheumatology / Spondylitis Association of America / SPARTAN",
                             "2019 Update of the ACR/SAA/SPARTAN Recommendations for Ankylosing Spondylitis and "
                             "Non-radiographic Axial Spondyloarthritis", "https://pubmed.ncbi.nlm.nih.gov/31436026/"),
    "moz-1582-2025": Source("UA", _MOZ, "Стандарт медичної допомоги «Аксіальний спондилоартрит»",
                            "https://www.dec.gov.ua/files/02Ck2YDEQ2/dn_1582_17102025_dod.pdf",
                            "Наказ МОЗ від 17.10.2025 № 1582"),
    "moz-nastanova-00443": Source("UA", _DUO, "Настанова 00443. Анкілозуючий спондиліт та аксіальний спондилоартрит",
                                  "https://guidelines.moz.gov.ua/documents/3296", "ebm00443, 2017", duodecim=True),
    "moz-nastanova-00440": Source("UA", _DUO, "Настанова 00440. Специфічні ознаки і симптоми у пацієнтів із "
                                  "запальними захворюваннями суглобів", "https://guidelines.moz.gov.ua/documents/3876",
                                  "ebm00440, 2017", duodecim=True),
    # BRCA
    "uspstf-brca-2019": Source("US", "U.S. Preventive Services Task Force (USPSTF)",
                               "BRCA-Related Cancer: Risk Assessment, Genetic Counseling, and Genetic Testing",
                               "https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/"
                               "brca-related-cancer-risk-assessment-genetic-counseling-and-genetic-testing", "2019"),
    "medlineplus-brca1": Source("US", _MP, "BRCA1 gene", "https://medlineplus.gov/genetics/gene/brca1/"),
    "moz-195-2025": Source("UA", _MOZ, "Стандарт медичної допомоги «Рак молочної залози»",
                           "https://www.dec.gov.ua/wp-content/uploads/2025/02/smd_195_rak-molochnoyi-zalozy.pdf",
                           "Наказ МОЗ від 03.02.2025 № 195"),
    # Lynch
    "medlineplus-lynch": Source("US", _MP, "Lynch syndrome", "https://medlineplus.gov/genetics/condition/lynch-syndrome/"),
    "cdc-lynch": Source("US", "Centers for Disease Control and Prevention", "About Lynch Syndrome",
                        "https://www.cdc.gov/colorectal-cancer-hereditary/about/lynch-syndrome.html"),
    "ehtg-escp-2021": Source("EU", "European Hereditary Tumour Group / European Society of Coloproctology",
                             "European guidelines from the EHTG and ESCP for Lynch syndrome (Mallorca guidelines, 3rd ed.)",
                             "https://pmc.ncbi.nlm.nih.gov/articles/PMC10364896/",
                             "Br J Surg 2021;108:484-498, doi:10.1002/bjs.11902"),
    "moz-512-2025": Source("UA", _MOZ, "Уніфікований клінічний протокол «Рак ободової кишки»",
                           "https://www.dec.gov.ua/wp-content/uploads/2025/03/ykpmd_512_21032025_dod_2.pdf",
                           "Наказ МОЗ від 21.03.2025 № 512"),
    "moz-1368-2024": Source("UA", _MOZ, "Порядок скринінгу і ранньої діагностики колоректального раку",
                            "https://zakon.rada.gov.ua/laws/show/z1275-24", "Наказ МОЗ від 05.08.2024 № 1368"),
    # CFTR
    "medlineplus-cf": Source("US", _MP, "Cystic fibrosis", "https://medlineplus.gov/genetics/condition/cystic-fibrosis/"),
    "medlineplus-cftr": Source("US", _MP, "CFTR gene", "https://medlineplus.gov/genetics/gene/cftr/"),
    "acmg-carrier-2021": Source("US", "American College of Medical Genetics and Genomics",
                                "Screening for autosomal recessive and X-linked conditions during pregnancy and "
                                "preconception", "https://pmc.ncbi.nlm.nih.gov/articles/PMC8488021/",
                                "Genet Med 2021;23:1793-1806, doi:10.1038/s41436-021-01203-z"),
    "eshg-ecs-2016": Source("EU", "European Society of Human Genetics", "Responsible implementation of expanded carrier "
                            "screening", "https://pmc.ncbi.nlm.nih.gov/articles/PMC4867464/",
                            "Eur J Hum Genet 2016;24:e1-e12, doi:10.1038/ejhg.2015.271"),
    "moz-723-2016": Source("UA", _MOZ, "Уніфікований клінічний протокол «Муковісцидоз»",
                           "https://www.dec.gov.ua/files/pK4oNUDRr3/2016_723_ykpmd_mkvsz.pdf",
                           "Наказ МОЗ від 15.07.2016 № 723"),
    "moz-kn-723-2016": Source("UA", _MOZ, "Адаптована клінічна настанова «Муковісцидоз»",
                              "https://www.dec.gov.ua/wp-content/uploads/2019/11/2016_723_akn_mkvsz.pdf", "КН 2016-723"),
    # warfarin
    "fda-coumadin": Source("US", "U.S. Food and Drug Administration", "COUMADIN (warfarin sodium) prescribing information",
                           "https://www.accessdata.fda.gov/drugsatfda_docs/label/2017/009218s118lbl.pdf",
                           "NDA 009218/S-118, 2017"),
    "cpic-warfarin-2017": Source("INT", "Clinical Pharmacogenetics Implementation Consortium (CPIC)",
                                 "CPIC Guideline for Pharmacogenetics-Guided Warfarin Dosing: 2017 Update",
                                 "https://pmc.ncbi.nlm.nih.gov/articles/PMC5546947/",
                                 "Clin Pharmacol Ther 2017;102:397-404, doi:10.1002/cpt.668"),
    "medlineplus-warfarin": Source("US", _MP, "Warfarin sensitivity",
                                   "https://medlineplus.gov/genetics/condition/warfarin-sensitivity/"),
    "dpwg-warfarin": Source("EU", _DPWG, "DPWG guideline: warfarin and VKORC1",
                            "https://www.clinpgx.org/guidelineAnnotation/PA166182841"),
    "moz-597-2016": Source("UA", _MOZ, "Уніфікований клінічний протокол «Фібриляція передсердь»",
                           "https://www.dec.gov.ua/files/z1SvrCHFgv/2016_597_ykpmd_fibrpreds.pdf",
                           "Наказ МОЗ від 15.06.2016 № 597"),
    "moz-nastanova-00110": Source("UA", _DUO, "Настанова 00110. Терапія варфарином",
                                  "https://guidelines.moz.gov.ua/documents/3013", "ebm00110, 2017", duodecim=True),
}

#: The sources of the page's general statements: DNA is the same throughout
#: life and in every cell; a genetic test goes with counselling.
GENERAL = ("medlineplus-dna", "cdc-genetic-testing", "fda-dtc-tests", "eshg-dtc-2010", "moz-nastanova-01117")

#: What each test's explanation rests on (``genetics.entry.<id>.*`` messages).
ENTRY_SOURCES: dict[str, tuple[str, ...]] = {
    "gen-lactose": ("medlineplus-lactose", "efsa-lactose-2010", "moz-nastanova-00193"),
    "gen-celiac": ("medlineplus-celiac", "acg-celiac-2023", "esscd-2019", "espghan-2020", "moz-nastanova-00192"),
    "gen-hemochromatosis": ("medlineplus-hh", "acg-hh-2019", "easl-hh-2022", "moz-nastanova-00519"),
    "gen-thrombophilia": ("medlineplus-fvl", "medlineplus-prothrombin", "ash-thrombophilia-2023", "eshre-rpl-2022",
                          "moz-nastanova-00107"),
    "gen-mthfr": ("acmg-mthfr-2013", "acmg-mthfr-2020", "medlineplus-mthfr", "eshre-rpl-2022"),
    "gen-gilbert": ("medlineplus-gilbert", "orphanet-357", "dpwg-irinotecan", "fda-pgx-table", "moz-nastanova-00214"),
    "gen-hla-b27": ("medlineplus-as", "medlineplus-hla-b", "asas-axspa-2009", "asas-eular-2022", "acr-axspa-2019",
                    "moz-1582-2025", "moz-nastanova-00443", "moz-nastanova-00440"),
    "gen-brca": ("uspstf-brca-2019", "medlineplus-brca1", "fda-dtc-tests", "eshg-dtc-2010", "moz-195-2025"),
    "gen-lynch": ("medlineplus-lynch", "cdc-lynch", "ehtg-escp-2021", "moz-512-2025", "moz-1368-2024"),
    "gen-cftr": ("medlineplus-cf", "medlineplus-cftr", "acmg-carrier-2021", "eshg-ecs-2016", "moz-723-2016",
                 "moz-kn-723-2016"),
    "gen-carrier-t1": ("acmg-carrier-2021", "eshg-ecs-2016", "medlineplus-cf", "moz-723-2016"),
    "gen-carrier-t2": ("acmg-carrier-2021", "eshg-ecs-2016"),
    "gen-carrier-t3": ("acmg-carrier-2021", "eshg-ecs-2016", "moz-723-2016"),
    "gen-warfarin": ("fda-coumadin", "cpic-warfarin-2017", "medlineplus-warfarin", "dpwg-warfarin", "moz-597-2016",
                     "moz-nastanova-00110"),
}
#: Tests whose guidelines disagree between regions (``genetics.entry.<id>.differs``).
DIFFERS = frozenset({"gen-hemochromatosis", "gen-thrombophilia", "gen-hla-b27", "gen-brca", "gen-lynch", "gen-cftr",
                     "gen-carrier-t1", "gen-carrier-t2", "gen-carrier-t3",
                     "gen-warfarin"})
#: What a result means, by printed outcome (``genetics.result.<id>.absent`` / ``.present``).
RESULT_TEXTS = frozenset({"gen-hla-b27"})

#: The tests grouped by what a person would come for.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("food", ("gen-lactose", "gen-celiac")),
    ("blood", ("gen-thrombophilia", "gen-hemochromatosis", "gen-mthfr")),
    ("liver", ("gen-gilbert",)),
    ("joints", ("gen-hla-b27",)),
    ("cancer", ("gen-brca", "gen-lynch")),
    ("carrier", ("gen-carrier-t1", "gen-carrier-t2", "gen-carrier-t3", "gen-cftr")),
    ("medicines", ("gen-warfarin",)),
)
ENTRIES = tuple(entry for entry in testplan_special.ENTRIES if entry.topic == "genetics")

#: A concept a result can carry, to the test it answers (``x:`` keys are
#: the labs' shared ones; a concept of that name is the same test).
_CONCEPT_ENTRY = {key.removeprefix("x:"): entry.id for entry in ENTRIES for key in entry.keys
                  if not key.startswith("sp:")}
_MARKER_ENTRIES: dict[str, list[str]] = {}
for _entry in ENTRIES:
    for _key in _entry.keys:
        if _key.startswith("sp:"):
            _MARKER_ENTRIES.setdefault(_key, []).append(_entry.id)

_GENE_CATEGORIES = frozenset({"immunogenetics", "genetics"})
_GERM_CATEGORIES = frozenset({"infection", "microbiology"})
_NUCLEIC = re.compile(r"ДНК|\bDNA\b|ПЛР|\bPCR\b|РНК|\bRNA\b", re.IGNORECASE)
#: A name that says it reads a gene («носійство гену», «генотип», "mutation").
_GENE_WORDS = re.compile(r"\bген(у|а|ів|и|ом|ам|і)?\b|генетик|генетичн|генотип|мутаці|поліморфізм|\bgenes?\b|genetic"
                         r"|genotyp|mutation|polymorphism", re.IGNORECASE)
#: Acquired (somatic, tumour) changes, followed over time rather than settled
#: once: a JAK2, BCR-ABL or EGFR result is repeated as the disease is watched.
_SOMATIC = re.compile(r"соматичн|пухлин|онко|лейкоз|лейкем|мієло|somatic|tumou?r|oncolog|leuk(a)?emi|\bBCR[-/ ]?ABL"
                      r"|\bJAK2\b|\bEGFR\b|\bKRAS\b|\bBRAF\b|\bCALR\b|\bMPL\b", re.IGNORECASE)
_GENETIC_ITEM = sorted(testplan.GENETIC_GROUPS)[:1]

#: The printed outcome, read as words ("не виявлено" is "not detected"):
#: which explanation applies, never a verdict on the value.
_ABSENT = frozenset({"not detected", "negative", "absent", "not found",
                     "не виявлено", "не виявлений", "негативний", "негативно", "відсутній"})
_PRESENT = frozenset({"detected", "positive", "present", "found",
                      "виявлено", "виявлений", "позитивний", "позитивно", "присутній"})


def kind(concept_id: str, category: str, raw_name: str) -> str | None:
    """``gene`` (reads the person's own genes), ``germ`` (finds a germ's DNA
    or RNA), ``antibody`` (antibodies against DNA) or None."""
    if category in _GENE_CATEGORIES or concept_id in _CONCEPT_ENTRY:
        return "gene"
    if category in _GERM_CATEGORIES:
        return "germ" if _NUCLEIC.search(raw_name) or concept_id.endswith(("-dna", "-pcr", "-rna")) else None
    if category == "autoimmune":
        return "antibody" if "dna" in concept_id or _NUCLEIC.search(raw_name) else None
    return "gene" if _GENE_WORDS.search(raw_name) else None


def entry_for(concept_id: str, raw_name: str) -> list[str]:
    """The planner's genetic tests a gene result answers: by concept, else by
    the test's printed name (the planner's own markers)."""
    if concept_id in _CONCEPT_ENTRY:
        return [_CONCEPT_ENTRY[concept_id]]
    found = testplan_special.matches({"name": raw_name, "groups": _GENETIC_ITEM})
    return list(dict.fromkeys(e for key in found for e in _MARKER_ENTRIES.get(key, ())))


def _once_only(entry: str | None, raw_name: str) -> bool:
    """A planner test a person needs only once: the result is a known test and
    the change it reads is inherited, not acquired in a tumour."""
    return entry is not None and not _SOMATIC.search(raw_name)


def outcome(value_text: str | None) -> str | None:
    """``absent`` / ``present`` when the lab printed one of those words."""
    keys = _text_keys(value_text)
    if keys & _ABSENT:
        return "absent"
    if keys & _PRESENT:
        return "present"
    return None


def sources(ids) -> list[Source]:
    return [SOURCES[i] for i in ids]


def overview(connection, owner_id: str, cards: list[dict], offers: dict[str, list[dict]]) -> dict:
    """Everything the page shows.  ``cards`` are the record's metric cards
    (one per concept, already judged); ``offers`` is the planner's
    ``special_offers`` for :data:`ENTRIES`."""
    by_id = {str(card["id"]): card for card in cards if not card.get("is_device")}
    rows = connection.execute(
        """SELECT o.concept_id, c.category, o.raw_name, o.value_text FROM observations o
           JOIN concepts c ON c.id = o.concept_id
           WHERE o.owner_user_id = ? AND o.verification_status <> 'rejected'
           ORDER BY o.observed_at DESC""", (owner_id,)).fetchall()
    seen: dict[str, dict] = {}
    for concept_id, category, raw_name, value_text in rows:
        concept_id, raw_name = str(concept_id), str(raw_name or "")
        if concept_id in seen or concept_id not in by_id:
            continue
        found = kind(concept_id, str(category or ""), raw_name)
        if found:
            seen[concept_id] = {"kind": found, "raw_name": raw_name, "value_text": value_text}
    genes, germs, antibodies, done = [], [], [], {}
    for concept_id, row in seen.items():
        card = by_id[concept_id]
        if row["kind"] == "gene":
            entries = entry_for(concept_id, row["raw_name"])
            entry = entries[0] if entries else None
            result = outcome(row["value_text"])
            genes.append({"card": card, "entry": entry, "outcome": result if entry in RESULT_TEXTS else None,
                          "once": _once_only(entry, row["raw_name"]),
                          "sources": sources(ENTRY_SOURCES.get(entry) or GENERAL)})
            for entry_id in entries:
                done.setdefault(entry_id, card)
        else:
            (germs if row["kind"] == "germ" else antibodies).append(card)
    genes.sort(key=lambda item: str(item["card"].get("latest_date") or ""), reverse=True)
    for group in (germs, antibodies):  # newest first, A to Z within a day
        group.sort(key=lambda card: testplan.alphabetical(str(card["name"])))
        group.sort(key=lambda card: str(card.get("latest_date") or ""), reverse=True)
    priced = any(offers.values())
    groups = []
    for group_id, entry_ids in GROUPS:
        tests = []
        for entry_id in entry_ids:
            listed = offers.get(entry_id) or []
            tests.append({"id": entry_id, "offers": listed, "cheapest": listed[0] if listed else None,
                          "done": done.get(entry_id), "differs": entry_id in DIFFERS,
                          "sources": sources(ENTRY_SOURCES[entry_id]),
                          "plan_url": f"/plan-tests?special=1&touched=1&sx={entry_id}"})
        groups.append({"id": group_id, "tests": tests})
    return {"genes": genes, "germs": germs, "antibodies": antibodies, "groups": groups, "priced": priced,
            "general_sources": sources(GENERAL), "topic_url": "/plan-tests?special=1&preset=genetics"}
