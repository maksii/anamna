"""Special tests: the planner's second mode.  A person comes with a question
(an allergy, their DNA, an infection, a long-term condition, feeling unwell
now) rather than with results the record already tracks.

An :class:`Entry` is one question and the requirement keys that answer it.
A key is either one the labs already share (a concept such as
``hepatitis-b-surface-antigen``, a cross-lab ``x:`` key such as
``x:ebv-vca-igg``), or ``sp:<marker>``: a :class:`Marker` is a kind of test
found by the item's own name (a genetic test, an allergy panel), and
:func:`tag` adds its key to every catalogue item that is one.  The planner's
solver then covers the keys as it covers any analyte: the cheapest mix of
single tests and packages at each lab, no second solver.

A marker only lists items that answer the same question: a broad name
(«Епштейн-Барр» is twelve different tests) is never a marker; the shared
serology keys say exactly which test is meant.

A marker can also answer other entries (``also``): ALEX measures the
allergens of every smaller allergy panel, so the solver weighs one ALEX
against those panels together and buys whichever is cheaper.

A topic (:data:`TOPICS`) groups entries; on the page it ticks and unticks
them as a routine preset does its results.  Item names are Ukrainian at
both labs; Synevo spells some Latin gene names with Cyrillic lookalikes
(«МТНFR»), so a name is matched as printed and with them folded.  Every
pattern was checked against the stored Esculab and Synevo catalogues of
November 2026; ``tests/python/test_testplan_special.py`` holds examples.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import testplan

_ALL = ("single", "set", "genetic")


@dataclass(frozen=True)
class Marker:
    id: str
    pattern: str
    exclude: str | None = None
    kinds: tuple[str, ...] = _ALL
    #: Other keys such an item answers as well.
    also: tuple[str, ...] = ()
    #: Genes that make a sequencing panel this test whatever its name: every
    #: one must be on the panel's gene list (the lab's own description), and
    #: the panel must be for this purpose (``purpose``, on its name and
    #: description).  BRCA2 is also on a Fanconi anaemia panel and CFTR on an
    #: immunodeficiency one, read there for those diseases only.
    genes: frozenset[str] = frozenset()
    purpose: str | None = None
    #: The variant itself (an rs number, a nucleotide change), found in a
    #: description that lists variants (:data:`VARIANT_LIST` rs numbers or
    #: more): Esculab's «DNA Health» names HFE C282Y and LCT -13910 only there.
    variant: str | None = None
    #: A standard the item's description says it meets («рівень Tier 3
    #: згідно з рекомендаціями ACMG 2021»).
    stated: str | None = None

    @property
    def key(self) -> str:
        return f"sp:{self.id}"


@dataclass(frozen=True)
class Standard:
    """A preset that ticks the tests a published standard names: the ACMG
    carrier screening tiers, the GA²LEN airborne allergen panel."""
    id: str
    topic: str
    entries: tuple[str, ...]


@dataclass(frozen=True)
class Entry:
    id: str
    topic: str
    keys: tuple[str, ...]
    #: Your DNA does not change: measured once is measured.
    once: bool = False
    #: Why once is enough: "dna" (a genotype cannot change) or "lifetime_level"
    #: (a blood level set mostly by genes, which guidance says to measure at
    #: least once in adult life but which a doctor may still repeat).
    once_kind: str = "dna"
    #: Offered to one sex only ("M" / "F"); to both when the sex is unknown.
    sex: str | None = None
    #: The record's category whose results this test also gives (an
    #: allergen panel's are among a multiplex test's 300).
    category: str | None = None


_BLOOD_COUNT = ("hemoglobin", "red-blood-cell-count", "hematocrit", "mean-corpuscular-volume",
                "mean-corpuscular-hemoglobin", "mean-corpuscular-hemoglobin-concentration",
                "red-cell-distribution-width-cv", "platelet-count", "white-blood-cell-count", "neutrophils",
                "lymphocytes", "monocytes", "eosinophils", "basophils", "erythrocyte-sedimentation-rate")
_URINE = ("urine-specific-gravity", "urine-ph", "urine-protein", "urine-glucose", "urine-ketones",
          "urine-nitrite", "urine-leukocytes", "urine-erythrocytes", "urine-bacteria")
_GENE = ("genetic", "set", "single")
#: The GA²LEN pan-European panel of airborne allergens (Heinzerling et al.,
#: Allergy 2009;64:1498-1506; the EAACI skin prick test standard, Allergy
#: 2013;68:1253-1264), by ImmunoCAP extract code: hazel, alder, birch,
#: plane, cypress, timothy grass, olive, mugwort, ragweed, Parietaria,
#: Alternaria, Cladosporium, Aspergillus, the two house dust mites, cat,
#: dog, German cockroach.  Defined for skin tests; blood tests read the same
#: sources as specific IgE.
GA2LEN = ("t4", "t2", "t3", "t11", "t23", "g6", "t9", "w6", "w1", "w21", "m6", "m2", "m3", "d1", "d2", "e1", "e5",
          "i6")
#: Every allergen an entry asks for by code, each named in the catalogue
#: (``special.allergen_<code>``).
ALLERGENS = (*GA2LEN, "i1", "i3")
#: A panel for inherited cancer risk, by its name or description.
_INHERITED_CANCER = r"спадков\w* (форм\w* )?рак|\bOnco|hereditary cancer"

MARKERS: tuple[Marker, ...] = (
    # Allergy: panels by what they screen.
    # ALEX (about 300 allergens and total IgE) measures what every smaller
    # panel below does: airborne, food, cat (e1) and dog (e5), house dust
    # mites (d1, d2), bee (i1) and wasp (i3) venom, and every source of the
    # GA²LEN panel (an ALEX² result of November 2025 holds all 18).
    Marker("allergy-multiplex", r"\bALEX", exclude=r"\bFOX\b",
           also=("total-immunoglobulin-e", "sp:allergy-phadiatop", "sp:allergy-inhalant", "sp:allergy-food",
                 "x:sige:i1", "x:sige:i3", *(f"x:sige:{code}" for code in GA2LEN))),
    Marker("allergy-phadiatop", r"phadiatop|фадіатоп", exclude=r"infant|інфант|дітей"),
    Marker("allergy-inhalant", r"астма|інгаляційн\w* панел|алергопанель інгаляц|сезонна алерг|поліноз",
           exclude=r"дит|діт|інсект|phadiatop|фадіатоп|синусит"),
    Marker("allergy-food", r"харчов\w* алерг|\bCRD\b|\(fx5\)",
           exclude=r"дит|діт|непереносим|гіперчутлив|молоко|пшениц|горіх"),
    # Your DNA.
    Marker("gen-lactose", r"непереносим\w* лактоз|лактозн\w* непереносим", kinds=_GENE,
           variant=r"rs4988235|13910"),
    # Synevo names its HLA-DQ2/DQ8 test «Генетика. Целіакія».
    Marker("gen-celiac", r"DQ2|DQ8|Генетика\. Целіакія", kinds=_GENE, variant=r"DQ2|DQ8"),
    Marker("gen-hemochromatosis", r"гемохромат|\bHFE\b", kinds=_GENE, variant=r"rs1800562|C282Y"),
    Marker("gen-f5", r"лейден|F5-Leiden|\bFVL\b", kinds=_GENE, variant=r"rs6025\b|1691\s*G\s*>\s*A"),
    Marker("gen-f2", r"протромбін\w* G20210A|\bF2-протромбін|\(FII\)|FII мутац|протромбін F2", kinds=_GENE,
           variant=r"rs1799963|20210\s*G\s*>\s*A"),
    Marker("gen-mthfr", r"MTHFR", kinds=_GENE, variant=r"rs1801133|677\s*C\s*>\s*T"),
    # Hereditary cancer panels count when they hold the genes, by the genes
    # in their name or on the gene list of their description (GenPlan Onco's
    # 252 names none in its title).  A panel named for another cancer still
    # reads them (OncoRisk Prostate holds BRCA1, BRCA2 and the four Lynch
    # genes for less than the Lynch panel alone), so the cancer's name never
    # rules one out; a somatic (tumour) panel answers nothing inherited.
    Marker("gen-brca", r"(?=.*BRCA1)(?=.*BRCA2)|Генетика\. BRCA\)", exclude=r"OncoTarget|соматичн",
           kinds=_GENE, genes=frozenset({"BRCA1", "BRCA2"}),
           purpose=_INHERITED_CANCER),
    Marker("gen-lynch", r"синдрому? Лінча|\bLynch\b|(?=.*MLH1)(?=.*MSH2)(?=.*MSH6)(?=.*PMS2)",
           exclude=r"OncoTarget|соматичн", kinds=_GENE, genes=frozenset({"MLH1", "MSH2", "MSH6", "PMS2"}),
           purpose=_INHERITED_CANCER),
    # Expanded carrier screening (GenPlan Baby, Synevo CarrierSeq): hundreds
    # of recessive diseases a couple could pass on.  Cystic fibrosis is
    # always among them (CFTR on Esculab's gene lists; Synevo's description
    # names «муковісцидоз» but publishes no gene list).  F5 Leiden, F2
    # G20210A, MTHFR, LCT and HLA are risk variants a carrier screen does not
    # report (its F5 and F2 are there for rare factor deficiencies), so those
    # markers go by name only.
    # SMA carrier status is SMN1 copy number: a heterozygous carrier test or
    # an SMN copy-number count, never the homozygous (diagnostic) one.
    Marker("gen-sma", r"гетерозиготн\w* носійств\w* СМА|спінальн\w* м\W?язов\w* атроф\w*, гетерозиготн|"
                      r"копійність генів SMN|\(SMA, ген SMN1\)", exclude=r"гомозиготн", kinds=_GENE,
           genes=frozenset({"SMN1"}), purpose=r"carrier|носійств", variant=r"SMN1"),
    # ACMG 2021 carrier screening tiers (Gregg et al., Genet Med 2021;23:
    # 1793-1806): Tier 1 cystic fibrosis and SMA; Tier 2 conditions with a
    # carrier frequency of 1 in 100 or more; Tier 3 1 in 200 or more and the
    # X-linked ones.  Each tier holds the one below.  A panel counts for a
    # tier only when its own description says so (GenPlan Baby: «рівень
    # Tier 3 згідно з рекомендаціями ACMG 2021»); no lab sells Tier 2 alone.
    Marker("gen-tier3", r"(?!)", kinds=("genetic",), stated=r"Tier\s*3",
           also=("sp:gen-tier2", "sp:gen-cftr", "sp:gen-sma")),
    Marker("gen-tier2", r"(?!)", kinds=("genetic",), stated=r"Tier\s*2\b", also=("sp:gen-cftr", "sp:gen-sma")),
    Marker("gen-carrier", r"Carrier\s*Screening|CarrierSeq", kinds=_GENE, also=("sp:gen-cftr", "sp:gen-sma")),
    # Pancreatitis panels read a few CFTR variants, not the carrier panel.
    Marker("gen-cftr", r"муковісцидоз|\bCFTR\b", exclude=r"панкреатит", kinds=_GENE, genes=frozenset({"CFTR"}),
           purpose=r"муковісцидоз|carrier|носійств", variant=r"F508del"),
    # Warfarin dosing reads both genes (CPIC 2017): VKORC1 alone is half the panel.
    Marker("gen-warfarin", r"(?=.*VKORC1)(?=.*CYP2C9)", kinds=_GENE, genes=frozenset({"VKORC1", "CYP2C9"}),
           variant=r"(?=[\s\S]*CYP2C9)(?=[\s\S]*rs9923231)"),
    # Infections without a shared key.  «ВІЛ» in capitals: «Т4 віл» is free T4.
    Marker("hiv", r"(?-i:ВІЛ)|\bHIV\b", exclude=r"навантаж|РНК|ПЛР|генотип|резист", kinds=("single",)),
    Marker("sti-pcr", r"ІПСШ", kinds=("set",)),
    Marker("hpv-hr", r"14 генотип|ВПЛ ВКР \(генотип", kinds=("single", "set")),
    Marker("covid", r"SARS-CoV-2|COVID|коронавірус", exclude=r"антитіл|IgG|IgM|спайк|пакет|NLR|прогноз",
           kinds=("single", "set")),
    Marker("flu", r"грипу? (А|A)\b|Influenza virus A|Вірус грипу A", exclude=r"Haemophilus|пакет",
           kinds=("single", "set")),
    Marker("strep-a", r"зів\w*.*(pyogenes|групи А)", exclude=r"agalactiae"),
    Marker("urine-culture", r"мікробіологічне дослідження сечі із визначенням|Бакпосів\. Сеча\. Антибіотикограма"),
    Marker("gut-bacteria", r"(Гострі )?кишков\w* інфекц\w*.*(Shigella|Бактерії)", kinds=("set",)),
    Marker("gut-viruses", r"(Гострі )?кишков\w* інфекц\w*.*(Rotavirus|Віруси)", kinds=("set",)),
)

_SP = {marker.id: marker.key for marker in MARKERS}

ENTRIES: tuple[Entry, ...] = (
    # --- allergy -------------------------------------------------------------
    Entry("total-ige", "allergy", ("total-immunoglobulin-e",)),
    Entry("allergy-phadiatop", "allergy", (_SP["allergy-phadiatop"],), category="allergy"),
    Entry("allergy-multiplex", "allergy", (_SP["allergy-multiplex"],), category="allergy"),
    Entry("allergy-inhalant", "allergy", (_SP["allergy-inhalant"],), category="allergy"),
    Entry("allergy-food", "allergy", (_SP["allergy-food"],), category="allergy"),
    Entry("allergy-pets", "allergy", ("x:sige:e1", "x:sige:e5"), category="allergy"),
    Entry("allergy-mites", "allergy", ("x:sige:d1", "x:sige:d2"), category="allergy"),
    Entry("allergy-venom", "allergy", ("x:sige:i1", "x:sige:i3"), category="allergy"),
    Entry("allergy-ga2len", "allergy", tuple(f"x:sige:{code}" for code in GA2LEN), category="allergy"),
    Entry("tryptase", "allergy", ("x:tryptase",)),
    # --- your DNA --------------------------------------------------------------
    Entry("gen-lactose", "genetics", (_SP["gen-lactose"],), once=True),
    Entry("gen-celiac", "genetics", (_SP["gen-celiac"],), once=True),
    Entry("gen-hemochromatosis", "genetics", (_SP["gen-hemochromatosis"],), once=True),
    Entry("gen-thrombophilia", "genetics", (_SP["gen-f5"], _SP["gen-f2"]), once=True),
    Entry("gen-mthfr", "genetics", (_SP["gen-mthfr"],), once=True),
    Entry("gen-gilbert", "genetics", ("x:ugt1a1-gilbert-genotype",), once=True),
    Entry("gen-hla-b27", "genetics", ("hla-b27",), once=True),
    Entry("gen-brca", "genetics", (_SP["gen-brca"],), once=True),
    Entry("gen-lynch", "genetics", (_SP["gen-lynch"],), once=True),
    Entry("gen-cftr", "genetics", (_SP["gen-cftr"],), once=True),
    Entry("gen-carrier-t1", "genetics", (_SP["gen-cftr"], _SP["gen-sma"]), once=True),
    Entry("gen-carrier-t2", "genetics", (_SP["gen-tier2"],), once=True),
    Entry("gen-carrier-t3", "genetics", (_SP["gen-tier3"],), once=True),
    Entry("gen-warfarin", "genetics", (_SP["gen-warfarin"],), once=True),
    # --- infections --------------------------------------------------------------
    Entry("hbv", "infections", ("hepatitis-b-surface-antigen",)),
    Entry("hcv", "infections", ("hepatitis-c-total-antibodies",)),
    Entry("hiv", "infections", (_SP["hiv"],)),
    Entry("syphilis", "infections", ("treponema-pallidum-total-antibodies",)),
    Entry("hbv-immunity", "infections", ("x:anti-hbs",)),
    Entry("measles-immunity", "infections", ("x:measles-igg",)),
    Entry("rubella-immunity", "infections", ("x:rubella-igg",)),
    Entry("vzv-immunity", "infections", ("x:vzv-igg",)),
    Entry("ebv", "infections", ("x:ebv-vca-igg", "x:ebv-vca-igm", "x:ebv-ebna-igg")),
    Entry("cmv", "infections", ("x:cmv-igg", "x:cmv-igm")),
    Entry("hsv", "infections", ("x:hsv-1-2-igg",)),
    Entry("h-pylori", "infections", ("h-pylori-stool-antigen",)),
    Entry("borrelia", "infections", ("x:borrelia-igg", "x:borrelia-igm")),
    Entry("sti-pcr", "infections", (_SP["sti-pcr"],)),
    Entry("hpv", "infections", (_SP["hpv-hr"],), sex="F"),
    # --- long-term conditions -------------------------------------------------
    Entry("hba1c", "chronic", ("hemoglobin-a1c",)),
    Entry("kidney-acr", "chronic", ("x:urine-albumin-creatinine-ratio",)),
    Entry("lipoprotein-a", "chronic", ("lipoprotein-a",), once=True, once_kind="lifetime_level"),
    Entry("thyroid-tpo", "chronic", ("thyroid-peroxidase-antibodies",)),
    Entry("celiac-serology", "chronic", ("x:ttg-iga", "x:immunoglobulin-a")),
    Entry("rheumatoid", "chronic", ("x:ccp-igg", "rheumatoid-factor")),
    Entry("ana", "chronic", ("x:ana-ift",)),
    Entry("calprotectin", "chronic", ("x:calprotectin-stool",)),
    # --- feeling unwell now -----------------------------------------------------
    Entry("blood-count", "urgent", _BLOOD_COUNT),
    Entry("crp", "urgent", ("c-reactive-protein",)),
    Entry("urinalysis", "urgent", _URINE),
    Entry("procalcitonin", "urgent", ("x:procalcitonin",)),
    Entry("flu-covid", "urgent", (_SP["covid"], _SP["flu"])),
    Entry("strep-a", "urgent", (_SP["strep-a"],)),
    Entry("urine-culture", "urgent", (_SP["urine-culture"],)),
    Entry("gut-infection", "urgent", (_SP["gut-bacteria"], _SP["gut-viruses"])),
    Entry("d-dimer", "urgent", ("x:d-dimer",)),
)

BY_ID = {entry.id: entry for entry in ENTRIES}
TOPICS: tuple[str, ...] = ("allergy", "genetics", "infections", "chronic", "urgent")
#: Presets for published standards, shown beside the topics.
STANDARDS: tuple[Standard, ...] = (
    Standard("acmg-tier1", "genetics", ("gen-carrier-t1",)),
    Standard("acmg-tier2", "genetics", ("gen-carrier-t2",)),
    Standard("acmg-tier3", "genetics", ("gen-carrier-t3",)),
    Standard("ga2len", "allergy", ("allergy-ga2len",)),
)

_HOMOGLYPHS = str.maketrans("АВСЕНКМОРТХІаеорсхі", "ABCEHKMOPTXIaeopcxi")
_COMPILED = [(marker, re.compile(marker.pattern, re.IGNORECASE),
              re.compile(marker.exclude, re.IGNORECASE) if marker.exclude else None) for marker in MARKERS]


#: rs numbers a description must list before its variants count: a list,
#: not a passing mention (Synevo's F2 test mentions F5 Leiden in its text).
VARIANT_LIST = 3
_RS = re.compile(r"\brs\d{3,}")


def _said(pattern, exclude, text: str) -> bool:
    """``pattern`` in ``text`` (as printed, or with Cyrillic lookalikes
    folded to Latin), and ``exclude`` in neither."""
    folded = text.translate(_HOMOGLYPHS)
    return bool(pattern.search(text) or pattern.search(folded)) \
        and not (exclude and (exclude.search(text) or exclude.search(folded)))


def matches(item: dict) -> list[str]:
    """The keys markers give an item, then what each also answers.  A
    marker holds, within its kinds, when the item's name meets its pattern,
    or one of the item's rows does (a package of the F5 and F2 tests is
    both), or every one of its genes is on the item's gene list for its
    purpose (``genes``/``description``, the lab's page), or its variant is
    in a description that lists variants.  An exclusion met by the item's
    name rules it out entirely; one met by a row rules that row out.  Kinds
    bind the item's own name, genes and variants; a row counts in any item."""
    name = str(item.get("name") or "")
    kind = testplan.item_kind(item)
    rows = [str(row.get("name") or "") for row in item.get("parameters") or ()]
    listed = set(item.get("genes") or ())
    described = str(item.get("description") or "")
    about = f"{name} {described}"
    variants = len(set(_RS.findall(described))) >= VARIANT_LIST

    def holds(marker, pattern, exclude) -> bool:
        if exclude and _said(exclude, None, name):
            return False
        # A row is a test of its own, whatever kind of item holds it.
        if any(_said(pattern, exclude, row) for row in rows if row != name):
            return True
        if kind not in marker.kinds:
            return False
        if _said(pattern, exclude, name):
            return True
        if marker.genes and marker.genes <= listed \
                and (not marker.purpose or re.search(marker.purpose, about, re.IGNORECASE)):
            return True
        if marker.stated and re.search(marker.stated, described):
            return True
        return bool(variants and marker.variant and re.search(marker.variant, described))

    hits = [marker for marker, pattern, exclude in _COMPILED if holds(marker, pattern, exclude)]
    return list(dict.fromkeys([*(m.key for m in hits), *(k for m in hits for k in m.also)]))


def tag(items: list[dict]) -> list[dict]:
    """Items with their ``sp:`` keys added to ``keys`` (what the solver
    covers).  ``parameter_keys`` is left as it was, so a marker is never
    counted as a result the item reports."""
    out = []
    for item in items:
        found = [key for key in matches(item) if key not in item["keys"]]
        out.append({**item, "keys": [*item["keys"], *found]} if found else item)
    return out


def for_sex(sex: str | None) -> list[Entry]:
    """The entries offered to a person of ``sex`` ("M", "F" or None)."""
    return [entry for entry in ENTRIES if entry.sex is None or sex is None or entry.sex == sex]
