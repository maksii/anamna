"""Vaccinations: what a dose is, how to read one off a card, and what is missing.

Three things live here because they are one subject.

`VACCINE_CODES` is the eHealth Ukraine dictionary — the codes an electronic
form 063/o prints in brackets beside every dose.  Each maps to the diseases the
product actually protects against, because every question worth asking about a
vaccination record is a disease question ("am I covered against tetanus?"), not
a product one ("do I have a DTaPHibHepBIPV?").

`parse_immunizations` reads dose rows out of a page of text.  It is written
against OCR output, not clean text, and it is deliberately conservative: a dose
is recorded when a date can be read, and the vaccine is identified separately
and may fail.  A dose whose product could not be identified is still a dose that
was given, and it is kept and shown as needing identification — dropping it
would leave the person's card looking shorter than the paper in their hand.

`SCHEDULE` is what three health authorities say an adult needs, with the source
for each and an explicit note where they disagree.  It computes nothing a
guideline does not support, and the strongest signal it uses is not a guideline
at all: a card that says a dose was "2 of 3" is the person's own record telling
them a third is outstanding.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache


PARSER_VERSION = "immunizations/2"


# --- diseases ---------------------------------------------------------------
#
# The key is what the record stores; the English name goes through PHRASES for
# Ukrainian, exactly as health-area names do.  `ua_calendar` marks the diseases
# the Ukrainian national calendar covers for everyone, which is what lets the
# page separate "your ledger holds no dose" from "no country routinely gives
# this".

@dataclass(frozen=True)
class Disease:
    key: str
    name: str
    explanation: str
    ua_calendar: bool = False


DISEASES: dict[str, Disease] = {
    item.key: item
    for item in (
        Disease("tuberculosis", "Tuberculosis", "A bacterial infection of the lungs. The BCG vaccine is given to newborns in Ukraine.", True),
        Disease("diphtheria", "Diphtheria", "A bacterial throat infection that can block the airway. Protection fades, so adults need a booster.", True),
        Disease("tetanus", "Tetanus", "Caused by bacteria entering a wound; it locks the muscles. Protection fades, so adults need a booster.", True),
        Disease("pertussis", "Whooping cough", "A bacterial cough illness, dangerous to infants. Adults are boosted mainly to protect babies around them.", True),
        Disease("polio", "Poliomyelitis", "A virus that can paralyse. Ukraine gives inactivated and oral vaccine in infancy and at six years.", True),
        Disease("hib", "Haemophilus influenzae type b", "A bacterium that causes meningitis in small children. Given in infancy.", True),
        Disease("hepatitis_b", "Hepatitis B", "A virus that damages the liver over years. Given from the second day of life in Ukraine.", True),
        Disease("hepatitis_a", "Hepatitis A", "A liver virus spread through food and water. Recommended rather than routine.", False),
        Disease("measles", "Measles", "A highly contagious virus with serious complications. Two doses give lasting protection.", True),
        Disease("mumps", "Mumps", "A virus that swells the salivary glands and can affect fertility. Given with measles and rubella.", True),
        Disease("rubella", "Rubella", "Mild in itself, but severe for an unborn child. Given with measles and mumps.", True),
        Disease("varicella", "Chickenpox", "A virus most people meet in childhood; more severe in adults. Recommended, not routine.", False),
        Disease("influenza", "Seasonal influenza", "The strains circulating change every year, so protection is given once a season.", False),
        Disease("covid19", "COVID-19", "Caused by the SARS-CoV-2 coronavirus. Which adults should be revaccinated, and how often, is where the three authorities differ most.", False),
        Disease("hpv", "Human papillomavirus", "A virus that causes cervical and other cancers. Given as a course of two or three doses.", True),
        Disease("pneumococcus", "Pneumococcal disease", "A bacterium causing pneumonia and meningitis; risk rises with age and with some long-term conditions.", False),
        Disease("meningococcus_acwy", "Meningococcal A, C, W, Y", "Bacterial meningitis and sepsis from four serogroups, covered by one conjugate vaccine.", False),
        Disease("meningococcus_b", "Meningococcal B", "The serogroup the A/C/W/Y vaccine does not cover; it needs its own product.", False),
        Disease("rotavirus", "Rotavirus", "The commonest cause of severe infant diarrhoea. Given orally in the first months of life.", False),
        Disease("tick_borne_encephalitis", "Tick-borne encephalitis", "A virus carried by ticks in parts of Europe. Given to people exposed to them.", False),
        Disease("rabies", "Rabies", "Almost always fatal once symptoms start. Given before exposure to people at risk, or immediately after a bite.", False),
        Disease("typhoid", "Typhoid fever", "A bacterial illness from contaminated food and water. A travel vaccine.", False),
        Disease("yellow_fever", "Yellow fever", "A mosquito-borne virus. Required for entry to some countries.", False),
        Disease("japanese_encephalitis", "Japanese encephalitis", "A mosquito-borne brain infection in parts of Asia. A travel vaccine.", False),
        Disease("cholera", "Cholera", "A severe diarrhoeal illness from contaminated water. A travel and outbreak vaccine.", False),
        Disease("anthrax", "Anthrax", "An occupational vaccine for people working with livestock or animal products.", False),
        Disease("plague", "Plague", "An occupational vaccine for laboratory and field workers in endemic areas.", False),
        Disease("tularemia", "Tularaemia", "An occupational and regional vaccine, used where the bacterium circulates in wildlife.", False),
        Disease("leptospirosis", "Leptospirosis", "Spread through water contaminated by animal urine; an occupational vaccine.", False),
        Disease("q_fever", "Q fever", "An occupational vaccine for people working with sheep, goats and cattle.", False),
    )
}

_D_T_P = ("diphtheria", "tetanus", "pertussis")
_D_T = ("diphtheria", "tetanus")

#: Every code in the eHealth Ukraine vaccine dictionary, mapped to the diseases
#: its product covers.  Reproduced from the published dictionary; the codes are
#: identifiers and are never translated or reordered.
VACCINE_CODES: dict[str, tuple[str, ...]] = {
    "BCG": ("tuberculosis",),
    "HepB": ("hepatitis_b",),
    "HepA": ("hepatitis_a",),
    "HepAHepB": ("hepatitis_a", "hepatitis_b"),
    "DTaP": _D_T_P,
    "DTwP": _D_T_P,
    "TdaP": _D_T_P,
    "aP": ("pertussis",),
    "DT": _D_T,
    "Td": _D_T,
    "TT": ("tetanus",),
    "Diphtheria": ("diphtheria",),
    "DTIPV": (*_D_T, "polio"),
    "DTPIPV": (*_D_T_P, "polio"),
    "DTaPIPV": (*_D_T_P, "polio"),
    "TdaPIPV": (*_D_T_P, "polio"),
    "TdIPV": (*_D_T, "polio"),
    "DTaPHib": (*_D_T_P, "hib"),
    "DTwPHib": (*_D_T_P, "hib"),
    "DTaPHibIPV": (*_D_T_P, "hib", "polio"),
    "DTaPHepB": (*_D_T_P, "hepatitis_b"),
    "DTwPHepB": (*_D_T_P, "hepatitis_b"),
    "DTaPHepBIPV": (*_D_T_P, "hepatitis_b", "polio"),
    "DTaPHibHepB": (*_D_T_P, "hib", "hepatitis_b"),
    "DTwPHibHepB": (*_D_T_P, "hib", "hepatitis_b"),
    "DTaPHibHepBIPV": (*_D_T_P, "hib", "hepatitis_b", "polio"),
    "DTwPHibHepBIPV": (*_D_T_P, "hib", "hepatitis_b", "polio"),
    "IPV": ("polio",),
    "bOPV": ("polio",),
    "HIB": ("hib",),
    "HibMenC": ("hib", "meningococcus_acwy"),
    "PCV10": ("pneumococcus", "hib"),
    "Pneumo_conj": ("pneumococcus",),
    "Pneumo_ps": ("pneumococcus",),
    "MMR": ("measles", "mumps", "rubella"),
    "MMRV": ("measles", "mumps", "rubella", "varicella"),
    "MR": ("measles", "rubella"),
    "MM": ("measles", "mumps"),
    "Measles": ("measles",),
    "Mumps": ("mumps",),
    "Rubella": ("rubella",),
    "Varicella": ("varicella",),
    "HPV": ("hpv",),
    "Influenza": ("influenza",),
    "Rotavirus": ("rotavirus",),
    "MenA_conj": ("meningococcus_acwy",),
    "MenC_conj": ("meningococcus_acwy",),
    "MenAC": ("meningococcus_acwy",),
    "MenACW": ("meningococcus_acwy",),
    "Men_ACWY_135": ("meningococcus_acwy",),
    "MenB": ("meningococcus_b",),
    "MenBC": ("meningococcus_b", "meningococcus_acwy"),
    "SarsCov2_mRNA": ("covid19",),
    "SarsCov2_RNA": ("covid19",),
    "SarsCov2_DNA": ("covid19",),
    "SarsCov2_RVv": ("covid19",),
    "SarsCov2_nRVv": ("covid19",),
    "SarsCov2_Inact": ("covid19",),
    "SarsCov2_Pr": ("covid19",),
    "SarsCov2_Rc_lp": ("covid19",),
    "TBE": ("tick_borne_encephalitis",),
    "Rabies": ("rabies",),
    "YF": ("yellow_fever",),
    "Typhoid_conj": ("typhoid",),
    "ViPS": ("typhoid",),
    "TyphoidHepA": ("typhoid", "hepatitis_a"),
    "JE_Inactd": ("japanese_encephalitis",),
    "JE_Rec": ("japanese_encephalitis",),
    "JE_LiveAtd": ("japanese_encephalitis",),
    "CHOLERA": ("cholera",),
    "Anthrax": ("anthrax",),
    "Plague": ("plague",),
    "Tularemia": ("tularemia",),
    "Leptospirosis": ("leptospirosis",),
    "Q_Vax": ("q_fever",),
}


def diseases_for(code: str) -> tuple[str, ...]:
    return VACCINE_CODES.get(code, ())


# --- reading a scanned card -------------------------------------------------

#: Cyrillic letters folded onto the Latin letter they are drawn as.  This is a
#: *visual* fold and has nothing to do with the phonetic transliteration in
#: `ingest/text.py`: OCR confuses shapes, not sounds.  «Рпешто. соп» is what
#: tesseract makes of "Pneumo_conj", and «Нерднерв» of "HepAHepB" -- both
#: unrecognisable phonetically and both close enough once the shapes are folded.
#: Both cases of a letter must fold to the same Latin letter, and to the one
#: tesseract actually emits for it.  «внутрішньом'я» comes back as
#: "BHYTPIWHbOM'A": Cyrillic «н» is printed as "H", not "n" -- «п» is the one
#: that reads as "n" -- and the soft sign «ь» is printed as "b".  Getting either
#: of those backwards silently costs every row's route and half the disease
#: keywords, with nothing to show that it happened.
_HOMOGLYPHS = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "З": "3", "І": "I", "Ї": "I", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "Ѕ": "S",
    "Ј": "J", "Г": "R", "П": "N", "И": "U", "Ш": "W", "Д": "A", "Б": "B", "Ь": "B",
    "Й": "I", "Л": "N",
    "а": "a", "в": "b", "е": "e", "і": "i", "ї": "i", "к": "k", "м": "m", "н": "h",
    "о": "o", "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "ѕ": "s", "ј": "j",
    "г": "r", "п": "n", "и": "u", "ш": "w", "д": "a", "б": "b", "з": "3", "л": "n",
    "ь": "b", "й": "i",
})


def fold(text: str) -> str:
    """Down to lowercase Latin letters and digits, shapes folded, nothing else."""
    normalised = unicodedata.normalize("NFKC", text).translate(_HOMOGLYPHS)
    return re.sub(r"[^a-z0-9]+", "", normalised.casefold())


_FOLDED_CODES = {fold(code): code for code in VACCINE_CODES}

_PNEUMOCOCCAL = "пневмококова"

#: Distinctive words from the Ukrainian product descriptions on form 063/o, in
#: the same folded alphabet.  The code in brackets is four to twelve characters
#: and one bad glyph ruins it; «менінгококової інфекції серогрупи В» is forty
#: characters and survives several.  Longest and most specific first: a
#: hepatitis A+B product must not be read as hepatitis B alone, and the
#: meningococcal serogroup is the whole difference between two vaccines.
_TEXT_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (fold(phrase), keys)
    for phrase, keys in (
        ("гепатиту А та гепатиту В", ("hepatitis_a", "hepatitis_b")),
        ("гепатиту A та гепатиту B", ("hepatitis_a", "hepatitis_b")),
        ("дифтерії, правця, кашлюка", _D_T_P),
        ("дифтерії, правця, кашлюку", _D_T_P),
        ("кору, паротиту, краснухи", ("measles", "mumps", "rubella")),
        ("менінгококової інфекції серогрупи В", ("meningococcus_b",)),
        ("менінгококів серогруп", ("meningococcus_acwy",)),
        ("менінгокової інфекції серогруп", ("meningococcus_acwy",)),
        ("вірусом папіломи людини", ("hpv",)),
        ("папіломавірусної", ("hpv",)),
        ("коронавірусної хвороби", ("covid19",)),
        (_PNEUMOCOCCAL, ("pneumococcus",)),
        ("туберкульозу", ("tuberculosis",)),
        ("поліомієліту", ("polio",)),
        ("гемофільної", ("hib",)),
        ("вітряної віспи", ("varicella",)),
        ("ротавірусної", ("rotavirus",)),
        ("кліщового енцефаліту", ("tick_borne_encephalitis",)),
        ("правця та дифтерії", _D_T),
        ("дифтерії та правця", _D_T),
        ("гепатиту В", ("hepatitis_b",)),
        ("гепатиту A", ("hepatitis_a",)),
        ("грипу", ("influenza",)),
        ("правця", ("tetanus",)),
    )
)

#: Wording that names a code on its own when OCR has mangled the bracketed one.
#: Every word must be present: «кон'югована» alone is also the meningococcal
#: product, «пневмококова» alone is also the polysaccharide one.
_CODE_MARKERS: tuple[tuple[tuple[str, ...], str], ...] = tuple(
    (tuple(fold(word) for word in words), code)
    for words, code in (
        ((_PNEUMOCOCCAL, "кон'югована"), "Pneumo_conj"),
        ((_PNEUMOCOCCAL, "полісахаридна"), "Pneumo_ps"),
    )
)


# --- products ---------------------------------------------------------------
#
# Form 063/о names a dose by its eHealth code and a paragraph of description
# ending in the manufacturer — never by the trade name a person would recognise
# or search for.  The code plus the maker printed beside it is enough to name
# the product in almost every case, and where it is not (two products from one
# maker under one code) the lot number's prefix or the trade name itself has to
# say so, or nothing is claimed.  Every entry cites the Ukrainian state register
# and, where the product is authorised there, the EU or US regulator.

_REVIEWED = "2026-11-06"


def _source(region: str, publisher: str, name: str, url: str, identifier: str) -> dict[str, object]:
    return {
        "region": region, "publisher": publisher, "name": name, "url": url,
        "identifier": identifier, "reviewed_at": _REVIEWED, "official": True,
    }


def _ua(name: str, slug: str, number: str) -> dict[str, object]:
    return _source(
        "UA", "МОЗ України - Державний реєстр лікарських засобів", name,
        f"https://www.drlz.com.ua/lz/{slug}", number,
    )


def _ema(name: str, slug: str, number: str) -> dict[str, object]:
    return _source(
        "EU", "European Medicines Agency", f"{name} (EPAR)",
        f"https://www.ema.europa.eu/en/medicines/human/EPAR/{slug}", number,
    )


def _fda(name: str, slug: str, number: str) -> dict[str, object]:
    return _source(
        "US", "U.S. Food and Drug Administration", name,
        f"https://www.fda.gov/vaccines-blood-biologics/vaccines/{slug}", number,
    )


@dataclass(frozen=True)
class Product:
    """One registered vaccine, and how to recognise it on a card."""

    key: str
    trade_name: str
    codes: tuple[str, ...]
    #: The marketing-authorisation holder as the register names it.
    manufacturer: str
    maker_short: str
    #: Spellings of the trade name itself; any one names the product outright.
    name_markers: tuple[str, ...]
    #: Spellings of the maker; enough only when the maker has one product
    #: under the code.
    maker_markers: tuple[str, ...]
    #: The wording form 063/о prints for it, maker included, code excluded.
    printed: tuple[str, ...] = ()
    #: The maker uses these lot prefixes for this product and no other.
    lot_prefixes: tuple[str, ...] = ()
    #: Lot shapes: `@` a letter, `#` a digit, anything else literal.
    lot_templates: tuple[str, ...] = ()
    #: Other registered products the card's wording is equally consistent with.
    alternatives: tuple[str, ...] = ()
    sources: tuple[dict[str, object], ...] = ()


_GSK = ("glaxosmithkline", "glaxo", "глаксосміткляйн")
_GARDASIL_9 = "Gardasil 9"
_PFIZER_EUROPE = "Pfizer Europe MA EEIG"
_MSD = ("sharpdohme", "merck", "msd")

PRODUCTS: tuple[Product, ...] = (
    Product(
        "comirnaty", "Comirnaty", ("SarsCov2_mRNA",), "BioNTech Manufacturing GmbH", "BioNTech/Pfizer",
        ("comirnaty", "комірнаті"), ("biontech", "pfizer"),
        printed=("Вакцина від коронавірусної хвороби на платформі мРНК BioNTech Manufacturing GmbH",),
        lot_templates=("@@####",),
        sources=(
            _ua("КОМІРНАТІ / COMIRNATY (екстрене застосування, 2021-2023)", "komirnati-comirnaty-ua-18592-01-01", "UA/18592/01/01"),
            _ema("Comirnaty", "comirnaty", "EMEA/H/C/005735"),
        ),
    ),
    Product(
        "jcovden", "COVID-19 Vaccine Janssen (Jcovden)", ("SarsCov2_nRVv",), "Janssen-Cilag International NV", "Janssen",
        ("jcovden", "vaccinejanssen"), ("janssen", "янссен"),
        printed=(
            "Вакцина від коронавірусної хвороби на платформі вірусного вектора без здатності до "
            "реплікації Janssen–Cilag International NV",
        ),
        lot_templates=("@@###",),
        sources=(
            _ua("КОВІД-19 ВАКЦИНА ЯНССЕН (екстрене застосування, 2021-2024)", "kovid-19-vaktsyna-yanssen-covid-19-vaccine-janssen-ua-18853-01-01", "UA/18853/01/01"),
            _ema("Jcovden", "jcovden", "EMEA/H/C/005737"),
        ),
    ),
    Product(
        # The card names no product; GSK makes two DTaP-family vaccines.  The
        # AC37B lot prefix is Boostrix's (NPRA Malaysia lot-release register:
        # AC37B383AF … AC37B534AC), and the register's Boostrix title is the
        # wording the card prints, so the prefix is required, not assumed.
        "boostrix", "Boostrix", ("DTaP", "TdaP"), "GlaxoSmithKline Biologicals S.A.", "GSK",
        ("boostrix", "бустрикс"), _GSK,
        printed=(
            "Комбінована вакцина для профілактики дифтерії, правця, кашлюка з ацелюлярним кашлюковим "
            "компонентом (АаКДП) ГлаксоСмітКляйн Біолоджікалз С.А., Бельгія/GlaxoSmithKline "
            "Biologicals S.A., Belgium",
        ),
        lot_prefixes=("AC37B",),
        lot_templates=("AC37B###@@",),
        sources=(
            _ua("БУСТРИКС", "bustryks-kombinovana-vaktsyna-dlia-profilaktyky-dyfterii-ua-14955-01-01", "UA/14955/01/01"),
            _fda("Boostrix", "boostrix", "BL 125106"),
        ),
    ),
    Product(
        "twinrix", "Twinrix", ("HepAHepB",), "GlaxoSmithKline Biologicals S.A.", "GSK",
        ("twinrix", "твінрикс"), _GSK,
        printed=("Вакцина для профілактики гепатиту А та гепатиту В GlaxoSmithKline",),
        lot_templates=("AHABB###@@",),
        sources=(
            _ua("ТВІНРИКС", "tvinryks-vaktsyna-dlia-profilaktyky-hepatytiv-a-inaktyvovana-ua-13056-01-01", "UA/13056/01/01"),
            _ema("Twinrix Adult", "twinrix-adult", "EMEA/H/C/000112"),
            _fda("Twinrix", "twinrix", "BL 103850"),
        ),
    ),
    Product(
        # Both Gardasil 9 and the four-valent Gardasil are registered in
        # Ukraine and the card prints neither name; Gardasil 9 is the one
        # supplied since its 2023 registration, so it is named as probable.
        "gardasil9", _GARDASIL_9, ("HPV",), "Merck Sharp & Dohme B.V.", "MSD",
        ("gardasil9", "гардасил9"), _MSD,
        printed=("Вакцина для профілактики інфекції, викликаної вірусом папіломи людини Merk Sharp & Dohme B. V.",),
        lot_templates=("@######", "@#######"),
        alternatives=("Gardasil",),
        sources=(
            _ua("ГАРДАСИЛ 9", "hardasyl-9-vaktsyna-proty-virusu-papilomy-liudyny-9-valentna-ua-20128-01-01", "UA/20128/01/01"),
            _ema(_GARDASIL_9, "gardasil-9", "EMEA/H/C/003852"),
            _fda(_GARDASIL_9, "gardasil-9", "STN 125508"),
        ),
    ),
    Product(
        "vaxneuvance", "Vaxneuvance", ("Pneumo_conj",), "Merck Sharp & Dohme B.V.", "MSD",
        ("vaxneuvance", "ваксньюванс"), _MSD,
        printed=("Пневмококова кон'югована вакцина Merk Sharp & Dohme B. V.",),
        lot_templates=("@######",),
        sources=(
            _ua("ВАКСНЬЮВАНС", "vaksniuvans-vaktsyna-pnevmokokova-polisakharydna-koniuhovana-ua-20539-01-01", "UA/20539/01/01"),
            _ema("Vaxneuvance", "vaxneuvance", "EMEA/H/C/005477"),
            _fda("Vaxneuvance", "vaxneuvance", "STN 125741"),
        ),
    ),
    Product(
        # Pfizer has two conjugate pneumococcal vaccines, so its name alone
        # identifies neither: each needs its own trade name on the page.
        "prevenar13", "Prevenar 13", ("Pneumo_conj",), _PFIZER_EUROPE, "Pfizer",
        ("prevenar13", "превенар13"), (),
        sources=(
            _ua("ПРЕВЕНАР 13", "prevenar-13-prevenar-13-vaktsyna-pnevmokokova-polisakharydna-ua-15864-01-01", "UA/15864/01/01"),
            _ema("Prevenar 13", "prevenar-13", "EMEA/H/C/001104"),
        ),
    ),
    Product(
        "prevenar20", "Prevenar 20", ("Pneumo_conj",), _PFIZER_EUROPE, "Pfizer",
        ("prevenar20", "превенар20", "apexxnar"), (),
        sources=(
            _ua("ПРЕВЕНАР 20", "prevenar-20-vaktsyna-pnevmokokova-polisakharydna-koniuhovana-ua-21377-01-01", "UA/21377/01/01"),
            _ema("Prevenar 20 (formerly Apexxnar)", "apexxnar", "EMEA/H/C/005451"),
            _fda("Prevnar 20", "prevnar-20", "STN 125731"),
        ),
    ),
    Product(
        "nimenrix", "Nimenrix", ("Men_ACWY_135",), _PFIZER_EUROPE, "Pfizer",
        ("nimenrix", "німенрикс"), ("pfizer",),
        printed=("Кон'югована полісахаридна вакцина проти менінгококів серогруп A, C, W-135 та Y Pfizer",),
        lot_templates=("@@####",),
        sources=(
            _ua("НІМЕНРИКС", "nimenryks-ua-16901-01-01", "UA/16901/01/01"),
            _ema("Nimenrix", "nimenrix", "EMEA/H/C/002226"),
        ),
    ),
    Product(
        "bexsero", "Bexsero", ("MenB",), "GSK Vaccines S.r.l.", "GSK",
        ("bexsero", "бексеро"), _GSK,
        printed=("Вакцина для профілактики менінгококової інфекції серогрупи В GlaxoSmithKline",),
        sources=(
            _ua("БЕКСЕРО", "beksero-vaktsyna-dlia-profilaktyky-meninhokokovoi-infektsii-ua-19683-01-01", "UA/19683/01/01"),
            _ema("Bexsero", "bexsero", "EMEA/H/C/002333"),
            _fda("Bexsero", "bexsero", "BL 125546"),
        ),
    ),
    Product(
        # GC Biopharma supplies Ukraine under one trade name in two
        # registrations — trivalent (current) and quadrivalent (valid until
        # August 2026) — and the card does not print which.
        "gcflu", "GC FLU", ("Influenza",), "GC Biopharma Corp.", "GC Biopharma",
        ("gcflu", "джісіфлю"), ("gcbiopharma", "greencross"),
        printed=("Вакцина для профілактики грипу GC Biopharma Corp.",),
        lot_templates=("Q########",),
        alternatives=("GC FLU Quadrivalent",),
        sources=(
            _ua("ДЖІСІ ФЛЮ / GC FLU", "dzhisi-fliu-gc-flu-vaktsyna-dlia-profilaktyky-hrypu-ua-16223-01-01", "UA/16223/01/01"),
            _source(
                "INT", "World Health Organization (Prequalification)", "GC FLU Quadrivalent",
                "https://extranet.who.int/prequal/vaccines/p/gc-flu-quadrivalent-inj", "WHO PQ",
            ),
        ),
    ),
    Product(
        # Not registered in Ukraine; here so a dose given abroad and typed in
        # by name is still recognised.
        "nuvaxovid", "Nuvaxovid", ("SarsCov2_Pr",), "Sanofi Winthrop Industrie", "Novavax/Sanofi",
        ("nuvaxovid", "нувааксовід"), ("novavax",),
        sources=(_ema("Nuvaxovid", "nuvaxovid", "EMEA/H/C/005808"),),
    ),
)

PRODUCTS_BY_KEY = {product.key: product for product in PRODUCTS}
_PRODUCT_NAME_MARKERS = {
    product.key: tuple(fold(marker) for marker in product.name_markers) for product in PRODUCTS
}
_PRODUCT_MAKER_MARKERS = {
    product.key: tuple(fold(marker) for marker in product.maker_markers) for product in PRODUCTS
}


def match_product(code: str, text: str, lot: str = "") -> Product | None:
    """The registered product a row describes, or None when that is not certain.

    A trade name in the text settles it.  Otherwise the maker printed beside
    the code has to have exactly one product under that code — Pfizer under
    `Pneumo_conj` is two, so it names none.
    """
    folded = fold(text)
    pool = [product for product in PRODUCTS if not code or code in product.codes]
    named = [
        (max(len(marker) for marker in _PRODUCT_NAME_MARKERS[product.key] if marker in folded), product)
        for product in pool
        if any(marker in folded for marker in _PRODUCT_NAME_MARKERS[product.key])
    ]
    if named:
        return max(named, key=lambda item: item[0])[1]
    if not code:
        return None
    made = [
        product for product in pool
        if any(marker in folded for marker in _PRODUCT_MAKER_MARKERS[product.key])
        and (not product.lot_prefixes or lot.upper().startswith(product.lot_prefixes))
    ]
    return made[0] if len(made) == 1 else None


#: What OCR mistakes one lot character for.  Only pairs that are the same shape.
_CONFUSABLE = {"0": "O", "O": "0", "2": "Z", "Z": "2", "4": "A", "A": "4",
               "8": "B", "B": "8", "5": "S", "S": "5", "1": "I", "I": "1"}


def _fits(lot: str, template: str) -> str | None:
    """`lot` coerced into `template`, one confusable character at a time."""
    if len(lot) != len(template):
        return None
    fixed = []
    for char, token in zip(lot, template):
        for candidate in (char, _CONFUSABLE.get(char, "")):
            if not candidate:
                continue
            if (token == "@" and candidate.isalpha()) or (token == "#" and candidate.isdigit()) or candidate == token:
                fixed.append(candidate)
                break
        else:
            return None
    return "".join(fixed)


def normalise_lot(raw: str, templates: tuple[str, ...]) -> str:
    """A lot number read through the shape its maker always prints.

    MSD prints a letter and six or seven digits, so «2007422» is «Z007422»;
    Twinrix is AHABB, three digits, two letters, so «AHABBA90BE» is
    «AHABB490BE»; GC Biopharma's lots open with a Q that OCR drops.  A lot
    that already fits, or that no single-glyph repair makes fit, is left as
    read — the shape is a repair aid, never a reason to invent characters.
    """
    lot = raw.strip().upper()
    if not lot or not templates or any(_fits(lot, template) == lot for template in templates):
        return lot
    for template in templates:
        fixed = _fits(lot, template)
        if fixed is None and template[0] not in "@#":
            fixed = _fits(template[0] + lot, template)
        if fixed:
            return fixed
    return lot


_LOT_KEY = str.maketrans({"Z": "2", "O": "0", "A": "4", "B": "8", "S": "5", "I": "1", "Q": None, "-": None, " ": None})


def lot_key(lot: str) -> str:
    """A lot with every OCR-confusable glyph folded, for telling copies apart."""
    return (lot or "").upper().translate(_LOT_KEY)


def printed_name(ocr_text: str, product: Product | None) -> str:
    """The product cell as the card prints it, when OCR is recognisably that.

    The OCR is snapped onto the known wording only when it is clearly the same
    paragraph; a card that words its product differently keeps its own text.
    """
    if product and product.printed and ocr_text:
        folded = fold(ocr_text)
        for wording in product.printed:
            if difflib.SequenceMatcher(None, folded, fold(wording)).ratio() >= 0.6:
                return wording
    return ocr_text


#: Legal forms printed before a facility's name, by their folded OCR shape.
_LEGAL_FORMS = {
    fold(form).replace("0", "o"): form
    for form in ("ТзОВ", "ТОВ", "КНП", "КП", "ДУ", "ПП", "ПрАТ", "АТ", "ФОП", "КНМП")
}


#: Where the facility's name stops on its header line.  The lookbehind starts
#: a match only at the first blank of a run, which is the only place one can
#: succeed, so a long run of blanks is scanned once instead of once per blank.
#: The first blank is written out so a split enters the run only by consuming
#: one; the rest is taken whole, since a word, never a blank, follows it.
_FACILITY_END_RE = re.compile(r"(?<!\s)\s\s*+(?:адреса|ФОРМА|МЕДИЧНА)\b|\)")


def card_facility(pages: list[dict[str, object]]) -> str:
    """The health facility named in the card's header, or empty.

    Form 063/о prints it on the line under «…належить заклад охорони
    здоров'я»: the facility that keeps the card, not necessarily the one that
    gave every dose on it.
    """
    from .ingest.text import combined_page_text

    marker = fold("заклад охорони здоров")
    for page in pages:
        lines = [line.strip() for line in combined_page_text(page).splitlines() if line.strip()]
        for index, line in enumerate(lines[:-1]):
            if marker not in fold(line):
                continue
            name = _FACILITY_END_RE.split(lines[index + 1])[0].strip(" |-—")
            if not name or fold(name).startswith(fold("Найменування")):
                return ""
            first, _, rest = name.partition(" ")
            form = _LEGAL_FORMS.get(fold(first).replace("0", "o"))
            return f"{form} {rest}".strip() if form and rest else name
    return ""


_DATE_RE = re.compile(r"\b([0-3]\d)[.,/]([01]\d)[.,/](20\d{2}|19\d{2})\b")
_SERIES_RE = re.compile(r"\b([1-9])\s*/\s*([1-9])\b")
#: The card prints «0.5 мл»; OCR renders «мл» as mn, ma, mp, ™n and worse, so
#: the unit is matched loosely and stored as the millilitres it always is.
_QUANTITY_RE = re.compile(r"\b(\d{1,2}[.,]\d)\s*(?:ml|[mм][nлaпp]|™n)\b", re.IGNORECASE)
#: The «Доза» column sits right after «Дата», so a one-decimal number there is
#: the dose even when row reconstruction pushed its «мл» onto another line.
_DATE_QUANTITY_RE = re.compile(r"\b[0-3]\d[.,/][01]\d[.,/](?:19|20)\d{2}\s+(\d{1,2}[.,]\d)(?![\d.,])")
#: A lot number: five to twenty characters of upper-case letters and digits,
#: with at least one digit.  Five, not four, because «3080» is a watermark this
#: card's OCR sprays over every second row and it is the only four-character
#: candidate on the page.
_LOT_RE = re.compile(r"\b(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{4,19}\b")
_ROUTE_MARKER = fold("внутрішньом")
#: Latin letters OCR substitutes for the Cyrillic ones in «Вакцинація».
_TO_CYRILLIC = str.maketrans("abekhiopcxytm", "авекніорсхутм")


def anchor_kind(line: str) -> str | None:
    """'vaccination' / 'revaccination' when a line opens a dose row, else None.

    The row's first column, and only at the start of the line: the folded
    alphabet loses «ц» and «я», so «вакцинація» and «вакцина» fold alike, and
    every «…кон'югована вакцина…» continuation line used to open a row of its
    own and cut the product name — and its maker — off the dose it belonged to.
    OCR also splits the word («Ва кцинація», «Вакцинаці: я»).
    """
    compact = re.sub(r"[\W\d_]+", "", line[:28]).casefold().translate(_TO_CYRILLIC)
    if compact.startswith("ревакцинаці"):
        return "revaccination"
    if compact.startswith("вакцинаці"):
        return "vaccination"
    return None


@dataclass(frozen=True)
class ParsedDose:
    """One dose read off a page, with the lines it was read from."""

    page_number: int
    occurrence_date: str | None
    vaccine_code: str
    diseases: tuple[str, ...]
    product_name: str
    event_kind: str
    dose_number: int | None
    doses_in_series: int | None
    dose_quantity: float | None
    dose_unit: str
    route: str
    lot_number: str
    evidence_text: str
    confidence: float
    trade_name: str = ""
    manufacturer: str = ""
    facility: str = ""
    site: str = ""
    clinician: str = ""


def identify_vaccine(block: str) -> tuple[str, tuple[str, ...]]:
    """Which vaccine a row describes, from its bracketed code or its wording.

    Returns the canonical eHealth code (empty when none could be read) and the
    diseases covered (empty when the row identified nothing).  The two are
    independent on purpose: a row may name a disease clearly in Ukrainian while
    its four-letter code is unreadable, and the disease is the part the record
    is judged on.
    """
    folded_block = fold(block)
    for candidate in re.findall(r"\(([^)]{2,40})\)", block):
        key = fold(candidate)
        if not key:
            continue
        if key in _FOLDED_CODES:
            code = _FOLDED_CODES[key]
            return code, VACCINE_CODES[code]
        close = difflib.get_close_matches(key, _FOLDED_CODES, n=1, cutoff=0.75)
        if close:
            code = _FOLDED_CODES[close[0]]
            return code, VACCINE_CODES[code]
    for words, code in _CODE_MARKERS:
        if all(word in folded_block for word in words):
            return code, VACCINE_CODES[code]
    for marker, keys in _TEXT_MARKERS:
        if marker and marker in folded_block:
            return "", keys
    return "", ()


def _blocks(lines: list[str]) -> list[list[str]]:
    """Split page lines into one group per dose row.

    A row on form 063/o wraps: the product name runs over three or four lines
    while the date, dose and lot sit on whichever of them the column happened to
    reach.  Anchoring on the «Вакцинація» / «Ревакцинація» in the first column
    and taking everything up to the next one keeps a row's own fields together
    and nothing else's.
    """
    anchors = [index for index, line in enumerate(lines) if anchor_kind(line)]
    starts: list[int] = []
    for position, index in enumerate(anchors):
        end = anchors[position + 1] if position + 1 < len(anchors) else len(lines)
        start = index
        # A wrapped product name is a taller cell than the values beside it, so
        # reconstructing rows from word coordinates sometimes emits the values
        # line *above* the name line that anchors the row.  The only dose on
        # page 1 of the card that started this -- «внутрішньом'я 1/1 33
        # 23.02.2025 0.5 мл AC37B478AG» -- landed one line before its own
        # «Вакцинація (DTaP) …» and was dropped in silence.  One line of
        # lookbehind, and only for a row that found no date of its own; if that
        # line belonged to the row above, both rows read the same date and lot
        # and the dose-identity index collapses them back into one.
        if index - 1 > (anchors[position - 1] if position else -1):
            if not any(_DATE_RE.search(line) for line in lines[index:end]):
                start = index - 1
        starts.append(start)
    # Each block ends where the next one *starts*, not at the next anchor.  A
    # row that reached back for its values line must not leave that line in the
    # row above as well: the block above already has its own date, so the extra
    # line only contributes a dose number and a lot that belong to somebody
    # else — a hepatitis dose reported as "1 of 1" because the diphtheria row
    # below it said so.
    return [
        lines[start : (starts[position + 1] if position + 1 < len(starts) else len(lines))]
        for position, start in enumerate(starts)
    ]


#: Where a product name stops.  On the card the name is the widest cell of the
#: row and everything to its right — route, dose number, age, date, millilitres,
#: lot — is a different column that row reconstruction has appended to the same
#: line.  Cutting there is what turns 300 characters of "Ревакцинація (MenB)
#: Вакцина ana профілактики внутрішньом'я 2/2 34 28.03.2026 0.5 mn ABXF48AC …
#: Туберкулінові проби … Дата зняття з обліку" into the sixty a person can read.
_NAME_END_RE = re.compile(
    r"[Вв]нутр|[Bb]HYTP|"
    r"\b[0-3]\d[.,/][01]\d[.,/](?:19|20)\d{2}\b|"
    r"\b[1-9]\s*/\s*[1-9]\b|"
    r"\b\d{1,2}[.,]\d\s*(?:мл|ml|[mм][nлaпp])\b"
)
#: How many lines of the block the name can span.  Four is the tallest name cell
#: on form 063/o (a six-valent vaccine plus its manufacturer's full legal name);
#: past that the block has run into the next row or the page footer.
_NAME_LINES = 4


#: The round «для медичних документів» stamp sits over the middle of the table
#: and OCR reads its arc as this one token on almost every row.  It is page
#: furniture, not part of any product's name.
_WATERMARK_RE = re.compile(r"\b[3зЗ][0оОoO][B8ВвbБ][0оОoO]\b")
#: The row's own «Вакцинація» / «Ревакцинація» label at the start of a line.
#: The leading blanks are taken whole, so when Р and Е are absent the second
#: blank run is empty instead of competing with the first for the same blanks.
_NAME_LABEL_RE = re.compile(r"^\s*+[Рр]?[Ееe]?\s*[Вв]акцина[а-яіїєґ]*\s*[:.-]?")


def product_text(block: list[str]) -> str:
    """The printed product name, without the columns printed beside it."""
    parts = []
    for line in block[:_NAME_LINES]:
        end = _NAME_END_RE.search(line)
        piece = line[: end.start()] if end else line
        piece = _NAME_LABEL_RE.sub("", piece, count=1)
        piece = re.sub(r"\([^)]{2,40}\)", " ", piece, count=1)
        piece = _WATERMARK_RE.sub(" ", piece)
        if piece.strip(" |)(.,:-"):
            parts.append(piece.strip())
    return " ".join(" ".join(parts).split()).strip(" |)(.,:-")[:200]


def _iso(match: re.Match[str]) -> str | None:
    day, month, year = match.groups()
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _block_date(block: list[str]) -> str | None:
    """The first valid date printed in a row, as ISO."""
    for line in block:
        match = _DATE_RE.search(line)
        if match and (occurrence := _iso(match)):
            return occurrence
    return None


def _card_dose(block: list[str], page_number: int, facility: str) -> ParsedDose | None:
    """One row of form 063/o as a dose, or None when the row carries no date."""
    occurrence = _block_date(block)
    if not occurrence:
        # No date, no dose.  The section headers of the empty parts of
        # the card ("Щеплення проти туберкульозу", with its column
        # titles and nothing under them) look exactly like a row until
        # this point, and inventing a dose out of one would put a
        # vaccination in the record that never happened.
        return None
    joined = "\n".join(block)
    code, keys = identify_vaccine(joined)
    folded = fold(joined)
    series = _SERIES_RE.search(joined)
    quantity = _QUANTITY_RE.search(joined) or _DATE_QUANTITY_RE.search(joined)
    lots = _LOT_RE.findall(joined.upper())
    lot = lots[0] if lots else ""
    product = match_product(code, joined, lot)
    if product:
        lot = normalise_lot(lot, product.lot_templates)
    return ParsedDose(
        page_number=page_number,
        occurrence_date=occurrence,
        vaccine_code=code,
        diseases=keys,
        product_name=printed_name(product_text(block), product),
        event_kind=next(filter(None, map(anchor_kind, block)), "vaccination"),
        dose_number=int(series.group(1)) if series else None,
        doses_in_series=int(series.group(2)) if series else None,
        dose_quantity=float(quantity.group(1).replace(",", ".")) if quantity else None,
        dose_unit="мл" if quantity else "",
        route="intramuscular" if _ROUTE_MARKER in folded else "",
        lot_number=lot,
        evidence_text=joined[:2000],
        # Never higher.  Every field above came out of OCR of a
        # photograph, and the record's rule is that nothing is
        # trusted until a person has looked at it.
        confidence=0.6 if keys else 0.3,
        trade_name=product.trade_name if product else "",
        manufacturer=product.manufacturer if product else "",
        facility=facility,
    )


def parse_immunizations(pages: list[dict[str, object]]) -> list[ParsedDose]:
    """Every dose row the pages carry, in the order they were printed."""
    from .ingest.text import combined_page_text

    found: list[ParsedDose] = []
    facility = card_facility(pages)
    for page in pages:
        page_number = int(page["page_number"])
        lines = [line for line in combined_page_text(page).splitlines() if line.strip()]
        for block in _blocks(lines):
            dose = _card_dose(block, page_number, facility)
            if dose is not None:
                found.append(dose)
    return found


def dose_identity(occurrence_date: str | None, lot_number: str) -> tuple[str, str] | None:
    """What makes two rows the same dose: the day it was given and the vial.

    The pair a nurse writes down, and the pair that is unique in practice.
    Form 063/o prints several doses twice — once in the section for the disease
    and again under «Інші щеплення» — and the row-lookbehind that rescues a
    wrapped row can emit a third copy.  Without an identity, one import of one
    card produces sixteen rows for thirteen doses and the person is told they
    have had three vaccinations they never had.
    """
    if not occurrence_date or not lot_number:
        return None
    # Folded, so «2011234» read off one printing and «Z011234» off the other —
    # or off the record a person already corrected — are the same vial.
    return (occurrence_date, lot_key(lot_number))


def _combine(held: ParsedDose, dose: ParsedDose) -> ParsedDose:
    """Two printings of one dose, keeping the best field from each."""
    return ParsedDose(
        page_number=min(held.page_number, dose.page_number),
        occurrence_date=held.occurrence_date,
        vaccine_code=held.vaccine_code or dose.vaccine_code,
        diseases=held.diseases or dose.diseases,
        product_name=max(held.product_name, dose.product_name, key=len),
        # «Ревакцинація» is a stronger claim than «Вакцинація»: one of the
        # two printings says which dose in the course this was, and the
        # other only says a dose happened.
        event_kind="revaccination" if "revaccination" in {held.event_kind, dose.event_kind} else "vaccination",
        dose_number=held.dose_number or dose.dose_number,
        doses_in_series=held.doses_in_series or dose.doses_in_series,
        dose_quantity=held.dose_quantity or dose.dose_quantity,
        dose_unit=held.dose_unit or dose.dose_unit,
        route=held.route or dose.route,
        lot_number=held.lot_number or dose.lot_number,
        evidence_text=f"{held.evidence_text}\n---\n{dose.evidence_text}"[:2000],
        confidence=max(held.confidence, dose.confidence),
        trade_name=held.trade_name or dose.trade_name,
        manufacturer=held.manufacturer or dose.manufacturer,
        facility=held.facility or dose.facility,
        site=held.site or dose.site,
        clinician=held.clinician or dose.clinician,
    )


def merge_doses(doses: list[ParsedDose]) -> list[ParsedDose]:
    """Collapse repeated printings of one dose, keeping the best field from each.

    Not "keep the first": the copy under «Інші щеплення» is the one that prints
    "2/3", while the copy in the hepatitis section is the one whose millilitres
    survived OCR.  Dropping either loses something the card actually says.

    A printing whose lot OCR lost entirely is the same dose as the one printed
    on the same day under the same code with its lot intact — that is how two
    phantom hepatitis doses with no batch number reached a verified record.
    """
    order: list[ParsedDose] = []
    by_identity: dict[tuple[str, str], int] = {}
    lotless: list[ParsedDose] = []
    for dose in doses:
        identity = dose_identity(dose.occurrence_date, dose.lot_number)
        if identity is None:
            lotless.append(dose)
        elif identity in by_identity:
            order[by_identity[identity]] = _combine(order[by_identity[identity]], dose)
        else:
            by_identity[identity] = len(order)
            order.append(dose)
    for dose in lotless:
        twins = [
            index for index, held in enumerate(order)
            if dose.vaccine_code and held.occurrence_date == dose.occurrence_date
            and held.vaccine_code == dose.vaccine_code
        ]
        if len(twins) == 1:
            order[twins[0]] = _combine(order[twins[0]], dose)
        else:
            order.append(dose)
    return order


# --- the «Вакцинації» section of an eHealth visit note -----------------------

#: Cyrillic capitals typed into a Latin lot number («AHABB494AК» on the
#: 18.07.2026 note).  The same glyph, so the same vial.
_LATIN_LOT = str.maketrans("АВЕКМНОРСТХІ", "ABEKMHOPCTXI")
#: Where the left column of a two-column field row stops and the right one
#: starts.  The note prints «Назва вакцини … Виробник …» and «Лікар … Кількість
#: введеної вакцини …» side by side, so a value ends at the next label.
_VISIT_COLUMN_RE = re.compile(
    r"\s+(?:Виробник|Серія вакцин|Термін придатності|Кількість введеної вакцини|"
    r"Одиниці вимірювання|Місце введення|Шлях введення)\b"
)
#: One row of the protocol table: dose, protocol name, author, stage, doses.
#: The name is matched as «ends in a non-blank» after a possessive run of
#: blanks, so neither blank run can trade characters with it; the second
#: branch keeps the one row shape that allows, a name that is all blanks.
_VISIT_PROTOCOL_RE = re.compile(
    r"^([1-9])(?:\s++(.*?\S)|\s(?=\s*?[^\S\n]\s))\s+Міністерство Охорони\s+([1-9])\s+([1-9])\b", re.M
)
_VISIT_FACILITY_RE = re.compile(r"\b(ТзОВ|ТОВ|ПП|КНП|ФОП)\s*«([^»]+)»")


def is_visit_vaccination(text: str) -> bool:
    """Whether a page carries the «Вакцинації» section of an eHealth visit note."""
    return "Назва вакцини" in text and "Серія вакцин" in text


def _visit_field(text: str, label: str) -> str:
    match = re.search(rf"{label}\s+(.+)", text)
    return _VISIT_COLUMN_RE.split(match.group(1))[0].strip() if match else ""


def parse_visit_vaccinations(pages: list[dict[str, object]]) -> list[ParsedDose]:
    """Every dose the «Вакцинації» section of a visit note records.

    The clinic's own eHealth entry for the injection: code, maker, lot, expiry,
    millilitres, site, route, who gave it and which dose of the protocol.  It is
    the fullest written account of a dose there is, so it has to reach the
    record as a dose and not only as a link -- a dose the person typed in by
    hand from memory is then superseded by it (see `store_document_doses`).
    Read from the PDF text layer only: the section is native text, and the
    logo OCR beside it has nothing to add.
    """
    lines = [
        (int(page["page_number"]), line.strip())
        for page in pages
        for line in str(page.get("native_text") or "").splitlines()
        if line.strip()
    ]
    whole = "\n".join(line for _, line in lines)
    facility_match = _VISIT_FACILITY_RE.search(whole)
    facility = f"{facility_match.group(1)} {facility_match.group(2)}" if facility_match else ""
    starts = [index for index, (_, line) in enumerate(lines) if line.startswith("Назва вакцини")]
    found: list[ParsedDose] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        dose = _visit_dose(_visit_block([line for _, line in lines[start:end]]), lines[start][0], facility)
        if dose is not None:
            found.append(dose)
    return found


def _visit_block(block: list[str]) -> list[str]:
    """A dose's lines, cut after its protocol table.

    The protocol table closes a dose; whatever follows it (advice, the
    next visit, the signature) belongs to the note, not to this dose.
    """
    table = next((index for index, line in enumerate(block) if line.startswith("№ дози")), None)
    if table is None:
        return block
    stop = table + 1
    while stop < len(block) and re.match(r"(?:доз\b|[1-9]\s|Здоров)", block[stop]):
        stop += 1
    return block[:stop]


def _visit_name(block: list[str]) -> str:
    """The vaccine's name as the note prints it, up to «Дата та час»."""
    name_parts = []
    for line in block:
        if line.startswith("Дата та час"):
            break
        piece = _VISIT_COLUMN_RE.split(line)[0]
        piece = re.sub(r"^Назва вакцини\s+\S+\s*[‐-]\s*", "", piece)
        if piece.strip():
            name_parts.append(piece.strip())
    return " ".join(" ".join(name_parts).split())[:200]


_CLINICIAN_LABEL = "Лікар, який виконав вакцинацію"


def _visit_clinician(block: list[str]) -> str:
    """Who gave the dose: the label's line plus the line the name wraps onto."""
    for index, line in enumerate(block):
        if not line.startswith(_CLINICIAN_LABEL):
            continue
        first = _VISIT_COLUMN_RE.split(line[len(_CLINICIAN_LABEL):])[0].strip()
        rest = ""
        if index + 1 < len(block):
            rest = re.split(r"\s*[﴾(]|" + _VISIT_COLUMN_RE.pattern, block[index + 1])[0].strip()
        return " ".join(part for part in (first, rest) if part)
    return ""


def _visit_dose_number(protocol: re.Match[str] | None, explained: re.Match[str] | None) -> int | None:
    """The dose's place in its course: the protocol table, else the explanation."""
    if protocol:
        return int(protocol.group(1))
    if explained:
        return int(explained.group(1))
    return None


def _visit_dose(block: list[str], page_number: int, facility: str) -> ParsedDose | None:
    """One dose of a visit note's «Вакцинації» section, or None without a date."""
    text = "\n".join(block)
    when = re.search(r"вакцинації в системі\s+([0-3]\d)\.([01]\d)\.(\d{4})", text)
    occurrence = _iso(when) if when else None
    if not occurrence:
        return None
    code_match = re.match(r"Назва вакцини\s+(\S+)", block[0])
    code = _FOLDED_CODES.get(fold(code_match.group(1)), "") if code_match else ""
    keys = VACCINE_CODES.get(code, ()) if code else identify_vaccine(text)[1]
    lot = _visit_field(text, "Серія вакцин").split(" ")[0].upper().translate(_LATIN_LOT)
    product = match_product(code, text, lot)
    if product:
        lot = normalise_lot(lot, product.lot_templates)
    quantity = re.search(r"Кількість введеної вакцини\s+(\d+[.,]\d+)", text)
    protocol = _VISIT_PROTOCOL_RE.search(text)
    explained = re.search(r"Пояснення проведення вакцинації\s+([1-9])\s*доз", text)
    return ParsedDose(
        page_number=page_number,
        occurrence_date=occurrence,
        vaccine_code=code,
        diseases=tuple(keys),
        product_name=_visit_name(block),
        event_kind="vaccination",
        dose_number=_visit_dose_number(protocol, explained),
        doses_in_series=int(protocol.group(4)) if protocol else None,
        dose_quantity=float(quantity.group(1).replace(",", ".")) if quantity else None,
        dose_unit="мл" if quantity else "",
        route="intramuscular" if _ROUTE_MARKER in fold(_visit_field(text, "Шлях введення")) else "",
        lot_number=lot,
        evidence_text=text[:2000],
        # Printed text, not OCR -- but still not trusted until a person
        # has compared it with the page.
        confidence=0.9 if keys else 0.5,
        trade_name=product.trade_name if product else "",
        manufacturer=product.manufacturer if product else _visit_field(text, "Виробник"),
        facility=facility,
        site=_visit_field(text, "Місце введення").replace("﴾", "(").replace("﴿", ")"),
        clinician=_visit_clinician(block),
    )


def is_vaccination_card(text: str) -> bool:
    """Whether a page is a Ukrainian preventive-vaccination card, form 063/o."""
    folded = fold(text)
    return fold("КАРТА ПРОФІЛАКТИЧНИХ ЩЕПЛЕНЬ") in folded or fold("063/о") in folded or "063o" in folded


# --- what an adult is still owed --------------------------------------------

@dataclass(frozen=True)
class Recommendation:
    """One line of guidance, with who says it and whether they agree."""

    key: str
    diseases: tuple[str, ...]
    #: 'periodic' repeats forever at `interval_days`; 'seasonal' is due once per
    #: influenza season; 'series' is finishing a course the card itself started.
    kind: str
    interval_days: int = 0
    source_ids: tuple[str, ...] = ()
    regions_covered: tuple[str, ...] = ()
    agreement: str = "agreed"


#: Deliberately short.  Everything here is a rule all three authorities state
#: for a healthy adult with no risk condition, which is the only population this
#: page can safely reason about: it knows a person's date of birth and their
#: doses, and nothing about their kidneys, their spleen or their travel plans.
#: Risk-based and travel schedules are named on the page as things to raise with
#: a doctor rather than computed into a due date.
SCHEDULE: tuple[Recommendation, ...] = (
    Recommendation(
        key="td_booster",
        diseases=_D_T,
        kind="periodic",
        interval_days=3652,  # ten years
        source_ids=("moz-595-2011", "cdc-adult-schedule", "ecdc-vaccine-scheduler"),
        regions_covered=("UA", "US", "EU"),
        agreement="agreed",
    ),
    Recommendation(
        key="influenza_season",
        diseases=("influenza",),
        kind="seasonal",
        interval_days=365,
        source_ids=("moz-595-2011", "cdc-adult-schedule", "ecdc-vaccine-scheduler"),
        regions_covered=("UA", "US", "EU"),
        # Not a difference of interval -- all three say once a season -- but of
        # who. The US recommends it for everyone from six months of age; Ukraine
        # and most EU states recommend it for named risk groups and leave
        # everyone else to choose.  Averaging that into one sentence would tell
        # a Ukrainian reader something their own health service does not say.
        agreement="differs",
    ),
    Recommendation(
        key="covid_booster",
        diseases=("covid19",),
        kind="periodic",
        interval_days=365,
        source_ids=("moz-595-2011", "cdc-adult-schedule", "ecdc-vaccine-scheduler"),
        regions_covered=("UA", "US", "EU"),
        # The widest disagreement in adult immunisation right now: for the
        # 2025/26 season US practice moved from a universal recommendation to
        # shared clinical decision-making, while EU states and Ukraine continue
        # to recommend by age and risk group.  Both are recorded; neither is
        # turned into a due date the page pretends is settled.
        agreement="differs",
    ),
)

SCHEDULE_BY_KEY = {item.key: item for item in SCHEDULE}


@lru_cache(maxsize=1)
def schedule_sources() -> dict[str, dict[str, object]]:
    """The cited sources, straight from `data/reference_library.json` by id.

    Read from the library file rather than the seeded `reference_sets` table
    because these sources cite no analyte and so have no curated rule to be
    reached through — but rule 8's requirement stands whatever is being judged:
    a recommendation shown to a person names who publishes it and links it.
    """
    import json

    from .reference import LIBRARY_PATH

    wanted = {key for item in SCHEDULE for key in item.source_ids}
    library = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    return {
        str(source["id"]): source
        for source in library.get("sources", [])
        if str(source.get("id")) in wanted
    }


@dataclass
class Gap:
    """One thing the record suggests is outstanding, and why."""

    key: str
    kind: str  # 'series' | 'due' | 'never_recorded'
    diseases: tuple[str, ...]
    last_date: str | None = None
    due_date: str | None = None
    dose_number: int | None = None
    doses_in_series: int | None = None
    source_ids: tuple[str, ...] = ()
    regions_covered: tuple[str, ...] = ()
    agreement: str = "agreed"
    urgency: str = "later"  # 'overdue' | 'soon' | 'later' | 'unknown'
    extras: dict[str, object] = field(default_factory=dict)


def _urgency(due: date, today: date) -> str:
    if due <= today:
        return "overdue"
    return "soon" if due - today <= timedelta(days=180) else "later"


def _series_gaps(dated: list[dict[str, object]]) -> list[Gap]:
    """Courses the card started and does not show finishing.

    No guideline is consulted: the card printed "2/3" itself.
    """
    gaps: list[Gap] = []
    for keys, dose in _furthest_series_doses(dated).items():
        given, total = int(dose.get("dose_number") or 0), int(dose.get("doses_in_series") or 0)
        if 0 < given < total:
            gaps.append(
                Gap(
                    key="series:" + ",".join(keys),
                    kind="series",
                    diseases=keys,
                    last_date=str(dose["occurrence_date"]),
                    dose_number=given,
                    doses_in_series=total,
                    urgency="soon",
                    extras={"product_name": dose.get("product_name") or ""},
                )
            )
    return gaps


def _furthest_series_doses(dated: list[dict[str, object]]) -> dict[tuple[str, ...], dict[str, object]]:
    """Per course (the diseases a dose covers), its furthest-numbered dose that
    printed a series length; of equal numbers, the latest."""
    started: dict[tuple[str, ...], dict[str, object]] = {}
    for dose in sorted(dated, key=lambda item: str(item["occurrence_date"])):
        keys = tuple(key for key in str(dose.get("diseases") or "").split(",") if key)
        if not keys or not dose.get("doses_in_series"):
            continue
        previous = started.get(keys)
        if previous is None or int(dose.get("dose_number") or 0) >= int(previous.get("dose_number") or 0):
            started[keys] = dose
    return started


def _due_gap(item: Recommendation, last: str | None, due: date, today: date) -> Gap:
    return Gap(
        key=item.key, kind="due", diseases=item.diseases, last_date=last,
        due_date=due.isoformat(), source_ids=item.source_ids,
        regions_covered=item.regions_covered, agreement=item.agreement,
        urgency=_urgency(due, today),
    )


def _seasonal_gap(item: Recommendation, last: str | None, today: date) -> Gap | None:
    """The influenza season item: due once per season, not once per rolling year.

    A season, not a rolling year: the strains are reformulated every
    year, so a dose given last November protects against last winter
    and stops counting when the next season opens.  Northern
    hemisphere seasons are named by the autumn they begin in.
    """
    season_start = date(today.year if today.month >= 9 else today.year - 1, 9, 1)
    if date(today.year, 6, 1) <= today < date(today.year, 9, 1):
        # Between seasons.  Reporting the season that has just ended as
        # overdue is true and useless: nobody can act on it, and the
        # vaccine for the coming one does not exist yet.
        return _due_gap(item, last, date(today.year, 9, 1), today)
    if last is not None and last >= season_start.isoformat():
        return None
    return _due_gap(item, last, season_start, today)


def _schedule_gap(item: Recommendation, dated: list[dict[str, object]], today: date) -> Gap | None:
    """What one recurring adult item says is outstanding, or None."""
    covering = [
        dose for dose in dated
        if set(item.diseases) & set(str(dose.get("diseases") or "").split(","))
    ]
    last = max((str(dose["occurrence_date"]) for dose in covering), default=None)
    if item.kind == "seasonal":
        return _seasonal_gap(item, last, today)
    if last is None:
        return Gap(
            key=item.key, kind="never_recorded", diseases=item.diseases,
            source_ids=item.source_ids, regions_covered=item.regions_covered,
            agreement=item.agreement, urgency="unknown",
        )
    try:
        due = date.fromisoformat(last) + timedelta(days=item.interval_days)
    except ValueError:
        return None
    return _due_gap(item, last, due, today)


def find_gaps(doses: list[dict[str, object]], today: date) -> list[Gap]:
    """What the record itself says is unfinished, then what the schedules say.

    Order matters to a reader: an unfinished course is a specific appointment
    this person's own card says they are part-way through, and it outranks a
    ten-year booster that is six years off.
    """
    dated = [dose for dose in doses if dose.get("occurrence_date")]
    # 1. Courses the card started and does not show finishing, then
    # 2. the recurring adult items.
    gaps = _series_gaps(dated)
    for item in SCHEDULE:
        gap = _schedule_gap(item, dated, today)
        if gap is not None:
            gaps.append(gap)

    rank ={"series": 0, "due": 1, "never_recorded": 2}
    urgency_rank = {"overdue": 0, "soon": 1, "unknown": 2, "later": 3}
    gaps.sort(key=lambda gap: (urgency_rank.get(gap.urgency, 9), rank.get(gap.kind, 9), gap.key))
    return gaps


def calendar_diseases_without_a_dose(doses: list[dict[str, object]]) -> list[str]:
    """Diseases the Ukrainian calendar covers for everyone, with nothing on file.

    Not "you were never vaccinated".  Ukraine's electronic register began in
    2019; anyone born before then had their childhood doses written into a
    paper booklet that no scan of a modern card reproduces.  The page says
    exactly that, and offers the hand-entry form -- this list is a prompt to
    look in a drawer, not a finding.
    """
    held: set[str] = set()
    for dose in doses:
        held.update(key for key in str(dose.get("diseases") or "").split(",") if key)
    return [key for key, item in DISEASES.items() if item.ua_calendar and key not in held]


# --- storage ----------------------------------------------------------------

#: A dose somebody has ruled on.  A re-read of the same card may add doses it
#: missed before, but it never overwrites a person's judgement — the same
#: contract `pipeline.HUMAN_RULED` gives observations.
HUMAN_RULED = ("verified", "corrected", "rejected")

_COLUMNS = (
    "id, owner_user_id, patient_id, document_id, page_number, occurrence_date, vaccine_code, "
    "diseases, product_name, trade_name, manufacturer, facility, event_kind, dose_number, "
    "doses_in_series, dose_quantity, dose_unit, route, lot_number, site, clinician, note, "
    "entry_source, entered_by_user_id, verification_status, evidence_text, confidence, "
    "extraction_method, parser_version, created_at, updated_at"
)


def _document_holdings(connection, owner_user_id: str, document_id: str) -> tuple[
    set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]], dict[tuple[str, str], str]
]:
    """What is already on file from documents: identities, dated codes, lotless codes, holders.

    Everything still on file from a document -- ruled rows, rows from other
    documents -- is the same dose when it matches.  Re-importing the same
    card under a new filename must not double the record.

    `held_by` is the same injection already on file from another document (a
    card row matching a visit note's dose): which row, so the note can fill in
    what the card never records -- where it went in and who gave it.
    """
    protected: set[tuple[str, str]] = set()
    dated_codes: set[tuple[str, str]] = set()
    lotless_codes: set[tuple[str, str]] = set()
    held_by: dict[tuple[str, str], str] = {}
    for row in connection.execute(
        """SELECT id, document_id, occurrence_date, lot_number, vaccine_code FROM immunizations
            WHERE owner_user_id=? AND entry_source <> 'manual'""",
        (owner_user_id,),
    ):
        if identity := dose_identity(row["occurrence_date"], row["lot_number"] or ""):
            protected.add(identity)
            if row["document_id"] != document_id:
                held_by[identity] = row["id"]
        if row["occurrence_date"] and row["vaccine_code"]:
            pair = (row["occurrence_date"], row["vaccine_code"])
            dated_codes.add(pair)
            if not row["lot_number"]:
                lotless_codes.add(pair)
    return protected, dated_codes, lotless_codes, held_by


def _retire_typed(
    connection,
    typed: list[dict[str, object]],
    dose: ParsedDose,
    identity: tuple[str, str] | None,
    pair: tuple[str, str],
    owner_user_id: str,
    document_id: str,
    now: str,
) -> None:
    """Delete the hand-typed rows this document's dose supersedes, auditing each."""
    for row in list(typed):
        same_vial = identity is not None and identity == dose_identity(
            row["occurrence_date"], str(row["lot_number"] or ""))
        same_day = bool(dose.vaccine_code) and pair == (row["occurrence_date"], row["vaccine_code"])
        if not (same_vial or same_day):
            continue
        typed.remove(row)
        connection.execute("DELETE FROM immunizations WHERE id=?", (row["id"],))
        connection.execute(
            """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id,
                                        details_json, created_at)
               VALUES (?, NULL, 'immunization_superseded_by_document', 'immunization', ?, ?, ?)""",
            (owner_user_id, row["id"],
             json.dumps({"document_id": document_id, "typed": row}, ensure_ascii=False, default=str), now),
        )


def _fill_held_dose(connection, dose: ParsedDose, held_id: str) -> None:
    """Give the row already on file the site and clinician only this document records.

    Empty fields only: nothing the other document (or a person) wrote is
    overwritten.
    """
    if not (dose.site or dose.clinician):
        return
    connection.execute(
        """UPDATE immunizations
              SET site = CASE WHEN site = '' THEN ? ELSE site END,
                  clinician = CASE WHEN clinician = '' THEN ? ELSE clinician END
            WHERE id = ?""",
        (dose.site, dose.clinician, held_id),
    )


def _held_by_code(
    dose: ParsedDose, pair: tuple[str, str], lotless_codes: set[tuple[str, str]], dated_codes: set[tuple[str, str]],
) -> bool:
    """Whether day and code already name this dose: the row on file has no lot, or this dose has none."""
    return bool(dose.vaccine_code) and (pair in lotless_codes or (not dose.lot_number and pair in dated_codes))


def store_document_doses(
    connection,
    owner_user_id: str,
    patient_id: str,
    document_id: str,
    doses: list[ParsedDose],
    extraction_method: str,
) -> int:
    """Put a card's doses in the record, idempotently.

    Called on first import and on every re-read.  Rows this document produced
    and nobody has ruled on are replaced wholesale, so a parser improvement
    reaches an already-imported card.  Rows a person verified, corrected or
    rejected are left exactly as they are, and a freshly parsed dose that
    matches one of them by identity is dropped rather than inserted beside it —
    otherwise every re-read would resurrect the row somebody just rejected.

    Identity is the day plus the lot with OCR-confusable glyphs folded, so a
    better reading of a lot («Z011234» where the record holds «2011234») is
    the same dose, not a new one.  A dose on file without a lot is matched by
    day and code instead: a lot that was never read cannot tell two printings
    apart, and the copy that has one is the same injection.
    """
    import uuid

    from .db import utc_now

    connection.execute(
        """DELETE FROM immunizations
           WHERE document_id=? AND entry_source='document' AND verification_status='extracted'""",
        (document_id,),
    )
    # A dose typed in by hand is the person's memory of an injection; the
    # clinic's document is the record of it, with the lot, the site and who
    # gave it.  When both describe the same dose the document's copy wins and
    # the typed one is retired (its content kept in the audit log), instead of
    # the typed row blocking the document's as it used to.
    typed: list[dict[str, object]] = [
        dict(row)
        for row in connection.execute(
            """SELECT * FROM immunizations WHERE owner_user_id=?
                AND entry_source='manual' AND verification_status <> 'rejected'""",
            (owner_user_id,),
        )
    ]
    protected, dated_codes, lotless_codes, held_by = _document_holdings(connection, owner_user_id, document_id)

    now = utc_now()
    written = 0
    for dose in merge_doses(doses):
        identity = dose_identity(dose.occurrence_date, dose.lot_number)
        pair = (dose.occurrence_date or "", dose.vaccine_code)
        _retire_typed(connection, typed, dose, identity, pair, owner_user_id, document_id, now)
        if identity and identity in protected:
            if identity in held_by:
                _fill_held_dose(connection, dose, held_by[identity])
            continue
        if _held_by_code(dose, pair, lotless_codes, dated_codes):
            continue
        if identity:
            protected.add(identity)
        if dose.vaccine_code and dose.occurrence_date:
            dated_codes.add(pair)
        connection.execute(
            f"INSERT INTO immunizations({_COLUMNS}) VALUES ({','.join('?' * 31)})",
            (
                str(uuid.uuid4()), owner_user_id, patient_id, document_id, dose.page_number,
                dose.occurrence_date, dose.vaccine_code, ",".join(dose.diseases),
                dose.product_name, dose.trade_name, dose.manufacturer, dose.facility,
                dose.event_kind, dose.dose_number, dose.doses_in_series,
                dose.dose_quantity, dose.dose_unit, dose.route, dose.lot_number, dose.site, dose.clinician, "",
                "document", None, "extracted", dose.evidence_text, dose.confidence,
                extraction_method, PARSER_VERSION, now, now,
            ),
        )
        written += 1
    return written


def doses_for(connection, owner_user_id: str) -> list[dict[str, object]]:
    """Every dose on file, oldest first, with the document each came from."""
    return [
        dict(row)
        for row in connection.execute(
            """SELECT i.*, d.title document_title, d.original_filename
               FROM immunizations i
               LEFT JOIN documents d ON d.id = i.document_id
               WHERE i.owner_user_id = ? AND i.verification_status <> 'rejected'
               ORDER BY i.occurrence_date IS NULL, i.occurrence_date, i.created_at""",
            (owner_user_id,),
        )
    ]


def visit_notes(connection, owner_user_id: str, doses: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Each dose's other written record: the clinic's note of the visit at
    which it was given («Вакцинації» in a Veselka/Doctor ELEKS note), beside
    the card the row was read from or the person who typed it in.

    The same injection is the same day plus the same vial -- `dose_identity`'s
    rule -- or, for a dose on file without a lot, the same day plus the vaccine
    code the note prints («HepAHepB ‐ Вакцина …»).  Cards are left out: a card
    is where dose rows come from, not a second witness to them.
    """
    candidates = _note_candidates(connection, owner_user_id)
    found: dict[str, list[dict[str, object]]] = {}
    for dose in doses:
        day = str(dose.get("occurrence_date") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        notes = _notes_naming_dose(dose, day, candidates)
        if notes:
            found.setdefault(str(dose["id"]), []).extend(notes)
    return found


def _notes_naming_dose(
    dose: dict[str, object], day: str, candidates: list[tuple[dict[str, object], str, str, str]]
) -> list[dict[str, object]]:
    """The candidate notes, other than the dose's own document, that print its
    day and name it by lot or vaccine code."""
    printed = f"{day[8:10]}.{day[5:7]}.{day[:4]}"
    lot, code = lot_key(str(dose.get("lot_number") or "")), fold(str(dose.get("vaccine_code") or ""))
    return [
        {"id": document["id"], "title": document["title"] or document["original_filename"],
         "report_date": document["report_date"]}
        for document, text, folded, lots in candidates
        if document["id"] != dose.get("document_id") and printed in text and _note_names_dose(lot, code, folded, lots)
    ]


def _note_candidates(connection, owner_user_id: str) -> list[tuple[dict[str, object], str, str, str]]:
    """Every non-card document that mentions a vaccine: row, text, folded text, folded lots."""
    candidates = []
    for row in connection.execute(
        """SELECT d.id, d.title, d.original_filename, d.report_date,
                  group_concat(COALESCE(p.native_text, '') || ' ' || COALESCE(p.ocr_text, ''), ' ') text
             FROM documents d JOIN document_pages p ON p.document_id = d.id
            WHERE d.owner_user_id = ? AND d.duplicate_of_document_id IS NULL
            GROUP BY d.id
           HAVING text LIKE '%акцин%'""",
        (owner_user_id,),
    ):
        text = str(row["text"] or "")
        if is_vaccination_card(text):
            continue
        folded = fold(text)
        candidates.append((dict(row), text, folded, lot_key(folded.upper())))
    return candidates


def _note_names_dose(lot: str, code: str, folded: str, lots: str) -> bool:
    """The same vial, or for a dose without a lot, the same vaccine code."""
    if lot:
        return lot in lots
    return bool(code) and code in folded


def product_for(row: dict[str, object]) -> Product | None:
    """The catalogue entry a stored dose names, by trade name or by its text.

    Rows written before the catalogue existed, and doses typed by hand («Twinrix»
    in the product box), carry no trade name; they are recognised the same way a
    card row is, from what they say.
    """
    stored = str(row.get("trade_name") or "")
    for product in PRODUCTS:
        if stored and product.trade_name == stored:
            return product
    text = " ".join(str(row.get(key) or "") for key in ("trade_name", "product_name", "manufacturer"))
    return match_product(str(row.get("vaccine_code") or ""), text, str(row.get("lot_number") or ""))


# --- review ------------------------------------------------------------------

_DOSES_REASON_RE = re.compile(r"Check \d+ vaccination\(s\)")


def _recounted_params(payload: str | None, unchecked: int) -> str | None:
    """`reason_params_json` with its vaccination count set to `unchecked`.

    None when there is nothing to recount: no payload, unreadable JSON, or no
    catalogue parts in it.
    """
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except ValueError:
        data = None
    parts = data.get("parts") if isinstance(data, dict) else None
    if not parts:
        return None
    for part in parts:
        if part.get("key") == "review.vaccinations_n":
            part.setdefault("params", {})["count"] = unchecked
    return json.dumps(data, ensure_ascii=False)


def _recount_task(connection, task, unchecked: int) -> bool:
    """Bring one open task's "check N vaccinations" up to date; True when it changed."""
    changed = False
    reason = _DOSES_REASON_RE.sub(f"Check {unchecked} vaccination(s)", task["reason"])
    if reason != task["reason"]:
        connection.execute("UPDATE review_tasks SET reason=? WHERE id=?", (reason, task["id"]))
        changed = True
    # The catalogue form of the same reason (review_tasks.reason_params_json)
    # carries the count too; a stale one would be what the page shows.
    payload = task["reason_params_json"] if "reason_params_json" in task.keys() else None
    updated = _recounted_params(payload, unchecked)
    if updated is not None and updated != payload:
        connection.execute("UPDATE review_tasks SET reason_params_json=? WHERE id=?", (updated, task["id"]))
        changed = True
    return changed


def refresh_card_review(connection, owner_user_id: str, document_id: str, actor_user_id: str | None = None) -> str:
    """Keep a card's open review task true to the doses still awaiting a person.

    The task said "check 15 vaccinations" long after every one had been
    confirmed, corrected or set aside, so the card sat in the review queue with
    nothing left to do on it.  Called after every ruling on a dose: while doses
    remain unchecked the count is brought up to date (set-aside doses never
    count); when none remain and nothing else on the document is awaiting a
    person either, the task is resolved and the resolution audited.

    Returns 'resolved', 'counted' or 'unchanged'.
    """
    from .db import utc_now

    tasks = connection.execute(
        """SELECT * FROM review_tasks
            WHERE owner_user_id=? AND entity_type='document' AND entity_id=? AND state='open'""",
        (owner_user_id, document_id),
    ).fetchall()
    if not tasks:
        return "unchanged"
    counts = connection.execute(
        """SELECT COUNT(*) total, COALESCE(SUM(verification_status='extracted'), 0) unchecked
             FROM immunizations WHERE document_id=? AND owner_user_id=?""",
        (document_id, owner_user_id),
    ).fetchone()
    if not counts["total"]:
        return "unchanged"
    unchecked = int(counts["unchecked"])
    if unchecked:
        changed = False
        for task in tasks:
            # Not `changed or ...`: every task is recounted, not only the first.
            changed = _recount_task(connection, task, unchecked) or changed
        return "counted" if changed else "unchanged"
    pending_elsewhere = connection.execute(
        """SELECT EXISTS(SELECT 1 FROM observations WHERE document_id=? AND verification_status='extracted')
                  OR EXISTS(SELECT 1 FROM clinical_findings WHERE document_id=? AND verification_status='extracted')""",
        (document_id, document_id),
    ).fetchone()[0]
    if pending_elsewhere:
        return "unchanged"
    now = utc_now()
    connection.execute(
        """UPDATE review_tasks SET state='resolved', resolution='verify', assigned_user_id=?, resolved_at=?
            WHERE owner_user_id=? AND entity_type='document' AND entity_id=? AND state='open'""",
        (actor_user_id, now, owner_user_id, document_id),
    )
    connection.execute(
        """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at)
           VALUES (?, ?, 'review_resolved_all_doses_decided', 'document', ?, ?, ?)""",
        (owner_user_id, actor_user_id, document_id,
         json.dumps({"tasks": [task["id"] for task in tasks], "doses": int(counts["total"])}), now),
    )
    return "resolved"


# --- correcting stored doses against the card ----------------------------------

#: The fields a transcription settles, in the order a change is reported.
_TRANSCRIBED_FIELDS = (
    "vaccine_code", "diseases", "event_kind", "dose_number", "doses_in_series", "dose_quantity",
    "dose_unit", "route", "lot_number", "page_number", "product_name", "trade_name",
    "manufacturer", "facility",
)


def _transcribed_values(dose: dict[str, object], facility: str) -> dict[str, object]:
    code = str(dose["code"])
    printed = str(dose.get("printed") or "")
    lot = str(dose.get("lot") or "")
    product = match_product(code, printed, lot)
    given, _, total = str(dose.get("dose") or "").partition("/")
    return {
        "vaccine_code": code,
        "diseases": ",".join(diseases_for(code)),
        "event_kind": "revaccination" if dose.get("kind") == "revaccination" else "vaccination",
        "dose_number": int(given) if given.isdigit() else None,
        "doses_in_series": int(total) if total.isdigit() else None,
        "dose_quantity": float(dose["quantity"]) if dose.get("quantity") is not None else None,
        "dose_unit": str(dose.get("unit") or ("мл" if dose.get("quantity") is not None else "")),
        "route": str(dose.get("route") or ""),
        "lot_number": lot,
        "page_number": int(dose["page"]) if dose.get("page") else None,
        "product_name": printed,
        "trade_name": product.trade_name if product else "",
        "manufacturer": product.manufacturer if product else "",
        "facility": facility,
    }


def apply_card_transcription(
    connection, transcription: dict[str, object], *, actor_user_id: str | None = None, apply: bool = False,
) -> list[dict[str, object]]:
    """Bring a card's stored doses into line with a transcription of the card.

    For doses a person already ruled on from OCR that was wrong in ways they
    could not all see — a lot «2007422» confirmed where the card prints
    «Z007422», a «2/2» that OCR never read.  The transcription is a person's
    reading of the card image (kept outside the repository: it is the patient's
    record), matched to the document by its file hash, so the same card under a
    different id on another machine is found.

    Each dose is matched by date and code (or, where the code was never read,
    by date and the folded lot); a dose that matches no row or two rows is
    reported and left alone.  Every changed field is written with its old value
    to `audit_events` (action `immunization_corrected_to_card`), and the row's
    verification status is kept: a verified dose stays verified, with the
    correction on record; an unchecked one stays unchecked.  Running it again
    changes nothing.  `apply=False` reports what would change.
    """
    facility = str(transcription.get("facility") or "")
    report: list[dict[str, object]] = []
    documents = connection.execute(
        "SELECT id, owner_user_id FROM documents WHERE sha256=?", (transcription["document_sha256"],)
    ).fetchall()
    if not documents:
        return [{"problem": "document_not_found", "sha256": transcription["document_sha256"]}]
    for document in documents:
        rows = [
            dict(row) for row in connection.execute(
                "SELECT * FROM immunizations WHERE document_id=? AND verification_status <> 'rejected'",
                (document["id"],),
            )
        ]
        for dose in transcription["doses"]:  # type: ignore[union-attr]
            entry = _transcribe_dose(connection, document, rows, dose, facility, actor_user_id, apply)
            if entry is not None:
                report.append(entry)
        if apply:
            refresh_card_review(connection, document["owner_user_id"], document["id"], actor_user_id)
    return report


def _transcribe_dose(
    connection, document, rows: list[dict[str, object]], dose: dict[str, object], facility: str,
    actor_user_id: str | None, apply: bool,
) -> dict[str, object] | None:
    """One transcribed dose against the card's stored rows: its report entry, or None if nothing changes."""
    from .db import utc_now

    target = _transcribed_values(dose, facility)
    matches = [
        row for row in rows
        if row["occurrence_date"] == dose["date"]
        and (row["vaccine_code"] == target["vaccine_code"]
             or (not row["vaccine_code"] and lot_key(row["lot_number"]) == lot_key(target["lot_number"])))
    ]
    where = {"document_id": document["id"], "date": dose["date"], "code": target["vaccine_code"]}
    if len(matches) != 1:
        return {**where, "problem": "ambiguous" if matches else "missing"}
    row = matches[0]
    changes = {
        name: [row[name], target[name]] for name in _TRANSCRIBED_FIELDS if row[name] != target[name]
    }
    if not changes:
        return None
    entry = {**where, "immunization_id": row["id"], "status": row["verification_status"], "changes": changes}
    if not apply:
        return entry
    now = utc_now()
    try:
        connection.execute(
            f"UPDATE immunizations SET {', '.join(f'{name}=?' for name in changes)}, updated_at=? WHERE id=?",
            (*(target[name] for name in changes), now, row["id"]),
        )
    except sqlite3.IntegrityError as error:
        return {**entry, "problem": f"integrity: {error}"}
    connection.execute(
        """INSERT INTO audit_events(owner_user_id, actor_user_id, action, entity_type, entity_id, details_json, created_at)
           VALUES (?, ?, 'immunization_corrected_to_card', 'immunization', ?, ?, ?)""",
        (document["owner_user_id"], actor_user_id, row["id"],
         json.dumps({"document_id": document["id"], "status_kept": row["verification_status"],
                     "source": "card transcription", "changes": changes}, ensure_ascii=False, default=str),
         now),
    )
    return entry


# --- search ------------------------------------------------------------------

#: Every way a person might ask for this page at all, in both languages and the
#: Russian many Ukrainians still search in.
_GENERIC_TERMS = (
    "vaccination", "vaccinations", "vaccine", "immunization", "immunisation", "jab",
    "щеплення", "щеплень", "вакцина", "вакцинація", "ревакцинація", "імунізація",
    "прививка", "прививки", "вакцинация",
)


def search_entries(connection, owner_user_id: str, locale: str) -> list[dict[str, object]]:
    """One search result per vaccine on file, each carrying every name it goes by.

    Grouped by product, not by dose: thirteen rows for «вакцина» answer nothing,
    while "Twinrix — hepatitis A · hepatitis B, 2 doses, latest 14 Feb 2026"
    answers the question.  `terms` holds the eHealth code, trade name and its
    alternatives, maker (registered and as printed), the printed wording, the
    lot numbers, disease names in English and Ukrainian, and the generic words
    for a vaccination.  The URL opens /vaccinations already filtered to it.
    """
    groups: dict[str, list[dict[str, object]]] = {}
    for dose in doses_for(connection, owner_user_id):
        product = product_for(dose)
        key = (product.trade_name if product else "") or str(dose.get("vaccine_code") or "") \
            or str(dose.get("product_name") or "")
        if key:
            groups.setdefault(key, []).append({**dose, "_product": product})
    entries = [_search_entry(key, doses, locale) for key, doses in groups.items()]
    entries.sort(key=lambda entry: str(entry["title"]).casefold())
    return entries


def _disease_names(keys: list[str]) -> list[str]:
    from .i18n import translate_phrase

    return [translate_phrase(DISEASES[key].name) for key in keys if key in DISEASES]


def _search_entry(key: str, doses: list[dict[str, object]], locale: str) -> dict[str, object]:
    """The search result for one vaccine on file, from every dose of it."""
    from urllib.parse import quote

    from .i18n import activate_locale, format_date_localized, reset_locale, t_plural

    product = doses[0]["_product"]
    codes = sorted({str(dose["vaccine_code"]) for dose in doses if dose.get("vaccine_code")})
    keys = list(dict.fromkeys(k for dose in doses for k in str(dose.get("diseases") or "").split(",") if k))
    latest = max(str(dose.get("occurrence_date") or "") for dose in doses)
    terms: list[str] = [key, *codes, *keys, *_GENERIC_TERMS]
    for language in ("en", "uk"):
        token = activate_locale(language)
        try:
            terms.extend(_disease_names(keys))
        finally:
            reset_locale(token)
    if product:
        terms.extend([product.trade_name, *product.alternatives, product.manufacturer, product.maker_short])
    for dose in doses:
        terms.extend(str(dose.get(name) or "") for name in ("product_name", "manufacturer", "lot_number", "facility"))
    token = activate_locale(locale)
    try:
        diseases = " · ".join(_disease_names(keys))
        subtitle = " · ".join(
            part for part in (
                diseases,
                t_plural("vax.group_count", len(doses)),
                format_date_localized(latest) if latest else "",
            ) if part
        )
    finally:
        reset_locale(token)
    title = key if not product or not codes else f"{key} ({', '.join(codes)})"
    return {
        "kind": "vaccination",
        "title": title,
        "subtitle": subtitle,
        "url": f"/vaccinations?q={quote(key)}",
        "terms": list(dict.fromkeys(term.strip() for term in terms if term and term.strip())),
    }


def _main(argv: list[str]) -> int:
    """`python -m anamna.immunizations apply-card <transcription.json> [--apply]`."""
    if not argv:
        demo()
        return 0
    if argv[0] != "apply-card" or len(argv) < 2:
        print(_main.__doc__)
        return 2
    from .db import connect

    transcription = json.loads(open(argv[1], encoding="utf-8").read())
    apply = "--apply" in argv
    with connect() as connection:
        report = apply_card_transcription(connection, transcription, apply=apply)
        if apply:
            connection.commit()
    print(json.dumps({"applied": apply, "entries": report}, ensure_ascii=False, indent=1, default=str))
    return 0


def demo() -> None:
    """Self-check: the traps this module exists to avoid, on real card text."""
    assert identify_vaccine("(DTaP) Комбінована вакцина")[0] == "DTaP"
    # The two OCR shapes that started this: Cyrillic homoglyphs of Latin codes.
    assert identify_vaccine("(Рпешто. соп)) Пневмококова")[1] == ("pneumococcus",)
    assert identify_vaccine("(Нерднерв) Вакцина для профілактики гепатиту А та гепатиту В")[1] == (
        "hepatitis_a", "hepatitis_b",
    )
    # A dropped final letter must not turn MenB into MenBC or vice versa.
    assert identify_vaccine("(MenB) серогрупи В")[1] == ("meningococcus_b",)
    assert identify_vaccine("(Men_ACWY_135) менінгококів серогруп A, С, W-135 та Y")[1] == (
        "meningococcus_acwy",
    )

    page = {
        "page_number": 2,
        "native_text": "",
        "ocr_text": (
            "Щеплення проти туберкульозу\n"
            "Тип Назва препарату Метод No Вік Дата Доза Серія\n"
            "Ревакцинація (HPV) Вакцина ana профілактики Іінфекції, BHYTPIWHbOM'A 2/3 08.01.2026 0.5 mn 20010299\n"
            "викликаної BIDYCOM папіломи людини 3080\n"
            "Вакцинація (Influenza) Вакцина ana профілактики внутрішньом'я 1/1 33 08.01.2026 0.5 mn 60225011\n"
        ),
    }
    doses = parse_immunizations([page])
    assert len(doses) == 2, doses
    hpv, flu = doses
    assert (hpv.diseases, hpv.event_kind, hpv.occurrence_date) == (("hpv",), "revaccination", "2026-01-08")
    assert (hpv.dose_number, hpv.doses_in_series, hpv.lot_number) == (2, 3, "20010299")
    # Millilitres printed to one decimal: a thousandth of a millilitre apart is the same dose.
    assert math.isclose(hpv.dose_quantity, 0.5, abs_tol=1e-3) and hpv.route == "intramuscular"
    # The empty section above must not become a dose, and «3080» -- a watermark
    # OCR sprays over the page -- must not become a lot number.
    assert flu.lot_number == "60225011", flu.lot_number

    # One dose printed twice, as form 063/o prints it: once with the millilitres
    # legible and once with the place in the course.  One dose must come out,
    # holding both.
    twice = [
        ParsedDose(2, "2026-02-14", "HepAHepB", ("hepatitis_a", "hepatitis_b"), "a", "vaccination",
                   None, None, 1.0, "мл", "", "AHABB481CC", "first", 0.6),
        ParsedDose(2, "2026-02-14", "", (), "a longer printing", "revaccination",
                   2, 3, None, "", "intramuscular", "AHABB481CC", "second", 0.6),
    ]
    only = merge_doses(twice)
    assert len(only) == 1, only
    assert (only[0].dose_number, only[0].doses_in_series) == (2, 3)
    assert (only[0].dose_quantity, only[0].vaccine_code) == (1.0, "HepAHepB")
    assert only[0].event_kind == "revaccination" and only[0].route == "intramuscular"
    # Two doses drawn from the same vial on different days are two doses. The
    # card really does print one lot twice, six weeks apart, for a two-dose
    # MenB course.
    other_day = ParsedDose(2, "2026-03-28", "HepAHepB", ("hepatitis_a",), "a", "vaccination",
                           None, None, None, "", "", "AHABB481CC", "third", 0.6)
    assert len(merge_doses([twice[0], other_day])) == 2

    rows = [
        {"occurrence_date": "2026-01-08", "diseases": "hpv", "dose_number": 2, "doses_in_series": 3},
        {"occurrence_date": "2025-02-23", "diseases": "diphtheria,pertussis,tetanus"},
    ]
    gaps = {gap.key: gap for gap in find_gaps(rows, date(2026, 8, 7))}
    assert gaps["series:hpv"].kind == "series" and gaps["series:hpv"].dose_number == 2
    assert gaps["td_booster"].due_date == "2035-02-23", gaps["td_booster"].due_date
    assert gaps["covid_booster"].kind == "never_recorded"
    assert gaps["influenza_season"].urgency in {"soon", "later"}
    assert "tuberculosis" in calendar_diseases_without_a_dose(rows)
    print("immunizations: ok")


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
