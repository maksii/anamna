from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast

from .text import collapse_space, parse_decimal


# Bump this whenever a rule in this file changes what comes out of a page.  It
# is the only thing that can tell a stored observation read by last month's
# parser from one read by today's, and `/documents` offers a re-read of exactly
# the files it names.  Two changes reached `main` without a bump -- 196 lines of
# new rules in 4472233, and the Latin unit spellings below -- so every row those
# produced is indistinguishable from a row the previous parser produced.
PARSER_VERSION = "2026.11.07-5"

#: The kinds of report this module reads values out of.  Everything else --
#: ultrasound, MRI, consultation, pathology, radiology -- it returns nothing
#: for by design, because those carry a written conclusion rather than a table
#: of numbers.  Named rather than left inline because the review reason has to
#: tell "this kind of report has no numbers in it" apart from "the parser read
#: these pages and found none", and the second is a defect while the first is
#: the expected shape of the document.
PARSED_CLINICAL_TYPES = frozenset(
    {"laboratory", "allergy", "microbiology", "blood_pressure", "electrocardiogram"}
)
#: Ultrasound is read for the measurements its protocols print with a norm
#: beside them -- an echo's «Виміри / Межі норми» table, a duplex scan's
#: «N=50-104», a thyroid lobe's «N- 7.5 cm3» -- and for nothing else: the
#: written conclusion is not read here, and a soft-tissue scan prints no such
#: table and yields nothing.  Kept out of `PARSED_CLINICAL_TYPES` on purpose:
#: that set is what tells the pipeline "a report of this kind with no values is
#: a parser that missed them", and an ultrasound with no measured table is
#: complete as it stands.
ULTRASOUND_TYPES = frozenset({"ultrasound"})
NUMBER = r"[<>≤≥]?\s*\d+(?:[.,]\d+)?%?"
#: A printed decimal, «55» or «0,85».
_DECIMAL = r"\d+(?:[.,]\d+)?"
#: The comparator a printed value opens with («<0.15», «≥100»).
_COMPARATOR = re.compile(r"[<>≤≥]")
#: A word broken at its hyphen over two lines: «Trypsin-» / «Inhibitor».
_HYPHEN_BREAK = re.compile(r"(?<=\w)- (?=\w)")
# Deliberately a closed allowlist, not "any unit-shaped token".  The same page
# that carries a result also carries antibiotic disk potencies ("Амікацин 30
# мкг"), ultrasound dimensions ("розмірами 12 мм") and drug doses ("мільгама 1
# т") in the identical "<name> <number> <unit>" shape -- a permissive pattern
# ingests all of them as observations.  The cost is the opposite failure: a
# real analyte whose unit is missing here is dropped in silence, which is how
# HBsAg, TSH, MCV, MCH, MCHC, MPV, PDW, RDW-SD and ESR went missing from two
# Synevo panels.  So: add a unit only with a source line that proves it, and
# keep longer forms ahead of the shorter ones they contain.
UNIT_PATTERN = (
    r"ммоль/л|мкмоль/л|мкмоль\/л|мкМО/мл|нг/мл|пг/мл|мг/дл|г/дл|г/л|мг/л|мкг/мл|мкг/л|"
    r"ммо/л|мМО/л|мо/мл|мо/л|мекв/л|од/л|Од/л|ОД/л|пмоль/л|нмоль/л|"
    r"клітин/мкл|тис/мкл|кл/мкл|цл/мкл|мл|"
    r"х\s*10\*\d+/л|10\^\d+/L|10\^\d+|секунди|сек|мм/год\.?|F/л|fL|фл|pg|%|індекс|коефіцієнт|"
    # Latin-script spellings.  Every one of these is the printed form of a unit
    # the allowlist already accepted in Cyrillic, and until they were added the
    # allowlist held six Latin forms in total: a report that writes "mmol/L"
    # rather than «ммоль/л» lost every row it had.  The record already proves
    # the case -- three St. Paraskeva rows print "IU/ml", "mg/l" and "mg/dl",
    # and each needed its own hardcoded pattern further down this file to
    # survive, one analyte at a time.  Cyrillic bare «мм», «мм.» and «мкг» are
    # excluded because they are imaging dimensions and antibiotic disk
    # potencies, and so is Latin "mm" for the same reason and from the same
    # documents; "mm/h" and "mm/hr" carry the "/h" that makes them a rate.
    r"µmol/L|umol/L|mmol/L|nmol/L|pmol/L|"
    r"µIU/mL|uIU/mL|mIU/L|IU/mL|IU/L|mEq/L|U/L|"
    r"mg/dL|mg/L|g/dL|g/L|ng/mL|pg/mL|µg/L|ug/L|"
    r"cells/µL|cells/uL|mm/hr|mm/h|mL|"
    # Synevo's urinalysis dipstick prints its unit column as «Ery/µL» and
    # «Leu/µL» («Еритроцити не виявлені Ery/µL не виявлені»); unparsed, the
    # unit leaked into the reference text.
    r"Ery/µL|Leu/µL|"
    # Expert Hospital's urinalysis prints its unit after the name, behind a
    # comma (result N1):
    #     Питома вага, г/мл 1,035 від 1,01 до 1,03
    #     Лейкоцити (WBC), в п/з 0-1 0-5
    #     Еритроцити змінені, в п/з 0 0-2
    # «в п/з» is «в полі зору», per high-power field.  Neither was accepted,
    # so the unit stayed glued to the name and `unit_raw` was empty.
    r"г/мл|в\s*п/з|"
    r"kUA/L|kU/L|КУО/г|COI|R|AI|пг|"
    # Synevo prints free T4 in nanograms per decilitre, insulin in micro-units
    # and the CA 15-3 / CA 125 tumour markers in units per millilitre:
    #     Тироксин вільний (T4 вільний) 1.35 нг/дл Діти:
    #     Інсулін 6.45 мкОд/мл 2.6 - 24.9
    #     Онкомаркер молочної залози (СА 15-3) 17.4 Од/мл <26.2
    # Absent, all three rows were dropped without a trace.  Ahead of bare «Од»,
    # which both of the last two contain.
    r"нг/дл|мкОд/мл|Од/мл|Од"
)
# «мкМО/л» is deliberately absent.  Read literally it is µIU/L, one thousandth
# of «мкМО/мл» (µIU/mL), which the pattern does accept and folds to mIU/L.  A
# laboratory printing it almost certainly means µIU/mL, but "almost certainly"
# is not a conversion factor: folding it to mIU/L would publish a TSH a
# thousand times its true value against a curated band, and leaving it unfolded
# would give TSH a second unit.  Dropping the row is the only one of the three
# that cannot state something false.  Same reasoning excludes "mU/L": milli-
# units are not milli-*international* units outside the assays where the two
# happen to be numerically defined as equal.
# Proof for the bare "10^n" form, from two Synevo panels in this record:
#     Лейкоцити (WBC) 6.41 10^9 Діти: <1 року: 6.5 - 12.5
#     Еритроцити (RBC) 5.13 10^12 Діти: <1 року: 3.3 - 4.9
#     Тромбоцити (PLT) 300 10^9 Діти: <1 року: 180.0 - 400.0
# The "/л" sits in a separate text object and never reaches the line, so the
# allowlist rejected the unit and dropped the row.  White cells, red cells and
# platelets -- the three headline numbers of a complete blood count -- were
# absent from both panels while their percentage differentials were kept, so
# the pages read as though the counts had never been run.  The longer
# "10^n/L" form stays ahead of this one in the alternation so it still wins.


@dataclass(frozen=True)
class ParsedObservation:
    raw_name: str
    value_numeric: float | None
    value_text: str | None
    comparator: str | None
    unit_raw: str | None
    reference_text: str | None
    reference_low: float | None
    reference_high: float | None
    page_number: int
    evidence_text: str
    confidence: float
    extraction_method: str = "native_pdf_text_parser"
    observed_at: str | None = None
    #: The part of the report a row was printed in, where one report prints
    #: the same analyte twice (a urinalysis dipstick and its microscopy).  Only
    #: `parse_document`'s de-duplication reads it; it is not stored.
    section: str | None = None
    #: Whether each printed bound admits the value equal to it.  «< 0.2» is a
    #: strict limit and «≤ 0.2» / «до 0.2» is not; storing both as inclusive put
    #: a yeast count of exactly 0.2 inside a men's limit printed as «< 0.2».
    reference_low_inclusive: bool = True
    reference_high_inclusive: bool = True
    #: The laboratory's own reading of the row where the parser can state it
    #: from what is printed -- a dipstick scale, a class legend, a categorical
    #: «+» against «(не виявлено)».  `None` leaves it to the bounds.
    vendor_interpretation: str | None = None
    #: The numeric token exactly as printed («1,80», «0.40»), so the number of
    #: decimals the laboratory reported survives `float()`.  `None` when the
    #: stored value is not that token (a folded density); a colony count keeps
    #: the count as printed, «1.0 x 10^5».
    value_printed: str | None = None
    #: The material the row was measured in («цільна кров», «сироватка
    #: крові», «сеча») where the report prints it as its own phrase.
    specimen: str | None = None
    #: Free text the report prints beside a reading (Garmin's «Примітки»).
    note: str | None = None
    #: Per-sex bounds a protocol prints in a shape no band reader handles
    #: («43-95 г/м2 (жінки) 49-115 г/м2 (чоловіки)»).  Parser-internal like
    #: `section`: `parse_document` turns it into bounds when it knows the sex.
    sex_bands: dict[str, tuple[float, float]] | None = None


@dataclass(frozen=True)
class ParseIssue:
    """A printed line the parser recognised but could not read.

    Not an observation: nothing about it is safe to store as a value.  The
    pipeline turns each one into a review task, so a result the parser lost
    is visible to a person instead of reading as though it was never printed.
    ``kind`` is a stable key («unparsed_known_analyte», «unknown_antibiotic»).
    """

    page_number: int
    kind: str
    raw_name: str
    evidence_text: str


# A row can carry only one demographic-neutral interval.  Age-, sex-, or
# pregnancy-specific text must not be silently reduced to its first pair of
# numbers and applied to a different patient - nor displayed to them as if it
# were their range.  One predicate, used by the parser and by the display layer.
DEMOGRAPHIC_REFERENCE_RE = re.compile(
    r"новонарод|дитин|діт|рок(?:ів|и|у)?\b|місяц|чолов|жін|вагіт|триместр|"
    # «12-16р.: 40-65» is an age band spelled the way EskuLab spells it in the
    # blood count.  Without this the whole segmented-neutrophil block read as
    # one plain interval and `reference_bounds` returned its first pair -- the
    # under-ones' 15-45 -- so a normal adult 46% was one point above "range".
    r"\d\s*р\b|\d\s*р[.:]|"
    r"newborn|child|years?\b|months?\b|male|female|pregnan|trimester",
    re.I,
)


#: Words a reference column uses to name an *abnormal* band.  Their presence
#: beside a ">" threshold flips what that threshold means.  «Клінічно значуща
#: кількість» is the same statement in a microbiology report: it says where a
#: colonisation starts to matter, not where a healthy range begins.
ABNORMAL_BAND_RE = re.compile(r"високий|підвищен|низьк(?:ий|е|а)|знижен|значущ", re.I)

#: A power of ten, written the way a PCR report writes its threshold:
#: «>10^4 ГЄ/мл».  Every pattern in `reference_bounds` stops at the caret, so
#: the bound would be stored as 10 -- a thousandfold low, silently, on a number
#: that decides whether an organism is colonising the patient.  Refuse instead:
#: `reference_bounds` refuses whatever it cannot read exactly, and this is not
#: an exception to that.
POWER_NOTATION_RE = re.compile(r"\d\s*\^\s*\d")

#: Words naming a band that is *not* the healthy one.  Immediately before an
#: interval they mark it as some other tier of the same scale, not the range
#: the patient should be in.
#: A decimal standing alone inside what claims to be an analyte name.  "B12",
#: "25-гідроксивітамін" and "10^9" are part of names; "7,35" never is.
#: The first digit is written out (`\d\d*+`, not `\d+`) so that a search has no
#: repetition to enter without consuming a digit; with the lookbehind, a run of
#: digits is entered once, at its start, instead of at every position in it.
#: The rest of the run is taken whole: a separator, never a digit, follows it.
SWALLOWED_VALUE = re.compile(r"(?<![\w^-])\d\d*+[.,]\d+(?!\w)")

NON_NORMAL_BAND_RE = re.compile(
    r"equivocal|borderline|intermediate|positive|сумнівн|гранично|позитивн|"
    # Every ending, not just the nominative.  A tier is named in whatever case
    # the sentence puts it in -- «< 2,2 дуже високого ризику» inflects both
    # words -- and matching only «високий» let the strictest treatment target on
    # a four-tier SCORE2 scale be published as this man's reference interval.
    r"передіабет|предіабет|висок\w*|підвищ\w*|"
    # LDL cholesterol names its tiers a third way, and neither word above
    # catches either of them: «вище оптимального рівня» is the band immediately
    # over the optimum, «Верхній пороговий рівень» the one over that.  With both
    # unrecognised the above-optimal 2,59-3,34 was taken as the patient's
    # reference on the same line where the lab puts his optimum below 2,59 -- so
    # an LDL of 3.0 mmol/L reported as inside the laboratory's own range.
    # «пороговий» names a threshold and never a healthy interval, so it stands
    # alone; «вище» does not -- it is an ordinary comparative -- so it is
    # matched only where it qualifies a level.  «оптимальний рівень», the band
    # that *is* this patient's, contains neither and stays selectable.
    r"вище\s+оптимальн\w*|порогов\w*|"
    # Synevo's cholesterol scale names its middle band «Умовний ризик».
    r"умовн\w*\s+ризик\w*|"
    # Faecal elastase prints «> 200 - нормальна екзокринна функція / 100 - 200
    # - помірна форма недостатності / < 100 - важка форма недостатності».
    # With the insufficiency tier unrecognised, 100 - 200 was read as the
    # reference and a normal 277.6 was published as high.
    r"недостатн\w*",
    re.I,
)

#: A reference given per time of day («Ранок (7:00-10:00): 5-25 Вечір
#: (16:00-20:00): 2.5-12.5», cortisol).  Two intervals for two collection
#: times are not one interval: read as one, the clock times themselves became
#: the bounds («00-10») and a morning cortisol of 12.0 was published as high.
#: `reference_limits` refuses it; `time_of_day_bands` reads the bands so a
#: value inside every one of them (or outside every one) can still be judged.
_TIME_OF_DAY_WORD = r"ранок|ранку|вранці|вечір|вечора|увечері|morning|evening"
TIME_OF_DAY_RE = re.compile(rf"\d{{1,2}}:\d{{2}}\s*[-–—]\s*\d{{1,2}}:\d{{2}}|\b(?:{_TIME_OF_DAY_WORD})\b", re.I)
_TIME_OF_DAY_BAND = re.compile(
    rf"\b(?:{_TIME_OF_DAY_WORD})\b\s*(?:\([^)]*\))?\s*:\s*"
    r"(?P<low>\d+(?:\.\d+)?)\s*[-–—]\s*(?P<high>\d+(?:\.\d+)?)",
    re.I,
)


def time_of_day_bands(reference: str | None) -> list[tuple[float, float]]:
    """The «label (time): low - high» bands of a per-time-of-day reference."""
    if not reference or not TIME_OF_DAY_RE.search(reference):
        return []
    value = reference.replace(",", ".")
    bands = [(float(found["low"]), float(found["high"])) for found in _TIME_OF_DAY_BAND.finditer(value)]
    return bands if len(bands) >= 2 else []


#: One tier of a scale that labels each interval after it: «<2.0 - показник
#: гіпопроліферативного компонента анемії», «0.8 - 1.2 - відсутність ризику».
_LABELLED_TIER = re.compile(
    r"(?:[<>≤≥]\s*)?\d+(?:\.\d+)?\s*%?(?:\s*[-–—]\s*[<>≤≥]?\s*\d+(?:\.\d+)?\s*%?)?"
    r"\s*[-–—]\s*(?P<label>[^\W\d_][^<>≤≥\d;]*)"
)
#: The words a tier uses to say it is the healthy one.
_HEALTHY_TIER = re.compile(r"норм|негатив|відсутн|оптимальн|здоров|negative|normal|absent|optimal|healthy", re.I)


def interpretive_scale(reference: str | None) -> bool:
    """A scale of labelled tiers none of which is named as the healthy one.

    The reticulocyte index prints «<2.0 - показник гіпопроліферативного
    компонента анемії / >2-3 - показник збільшення виникнення еритроцитів»:
    two readings of what a value means, not a normal interval.  Taken as one,
    2-3 became the "range" and an index of 0.15 was published as low.  A
    scale that does name its healthy tier («<5.2 - Відсутність ризику», «<0.9
    - негативний результат») is read by the band logic below as before.
    """
    if not reference:
        return False
    labels = [found["label"] for found in _LABELLED_TIER.finditer(reference.replace(",", "."))]
    return len(labels) >= 2 and not any(_HEALTHY_TIER.search(label) for label in labels)


def refused_reference(reference: str | None) -> bool:
    """A printed reference that is known not to be an interval at all.

    Narrower than "`reference_limits` found no bounds": a demographic block
    has an interval for somebody, and a stored bound read from it by a
    layout-aware parser is kept.  A per-time-of-day or purely interpretive
    scale has none for anybody, so a bound stored from it is an error.
    """
    return bool(reference) and (bool(TIME_OF_DAY_RE.search(reference or "")) or interpretive_scale(reference))

#: A reference that announces itself as a treatment target is not a reference
#: interval.  Non-HDL cholesterol prints four ESC/EAS targets, one per
#: cardiovascular risk group, and nothing on the page says which group this
#: patient is in -- so whichever the print order put first was being published
#: as his limit.  Which one that was moved when the column order was fixed,
#: from the moderate-risk 3.4 to the very-high-risk 2.2, and neither is his.
#: A block that also carries plain demographic bands (uric acid prints the
#: men's and women's intervals before its gout targets) never reaches here:
#: `applicable_band` picks the band first and this sees only that band's text.
TARGET_SCALE_RE = re.compile(r"цільов|терапевтичн|treatment target|therapeutic target", re.I)


def demographic_reference(reference: str | None) -> bool:
    """True when a printed reference interval is qualified by age or sex."""
    if not reference:
        return False
    return bool(DEMOGRAPHIC_REFERENCE_RE.search(reference.replace(",", ".")))


#: A limit written as a share of another analyte: «До 75% від загального»
#: (indirect bilirubin as a fraction of total bilirubin).  Its number is not in
#: the row's own unit, so reading it as a bound stored "75 µmol/L" as the upper
#: limit of an indirect bilirubin of 6.68 µmol/L.
RELATIVE_PERCENT_RE = re.compile(r"\d\s*%\s*від\b", re.I)

#: The label a multi-band scale gives its healthy band.  Where a scale names
#: one, that band *is* the reference, whatever order the bands were printed
#: in: «негативний: <0.9 сумнівний: 0,9-1,0 позитивний: ≥1,0» is "below 0.9",
#: not the equivocal 0.9-1.0 that the first number pair would give.
#: Deliberately only the immunoassay word: a risk or optimum tier («оптимальний
#: рівень», «Низький рівень ризику») is a tier and stays refused.
#: «Здорове населення» ("healthy population") is the same statement in
#: EskuLab's vitamin D scale: «Ризик дефіциту: <20.0 Ризик недостатнього
#: вживання: 20.0 - <30.0 Здорове населення: 30.0 - 100.0», where the first pair
#: of numbers is the insufficiency tier.
_NORMAL_LABEL = r"негатив\w*|negative|здоров\w*\s+населенн\w*"
_LIMIT = r"(?:від\s*)?[<>≤≥]?\s*-?\d+(?:\.\d+)?(?:\s*(?:до|[-–—])\s*[<≤]?\s*-?\d+(?:\.\d+)?)?"
_NORMAL_BAND_FIRST = re.compile(
    rf"(?:{_NORMAL_LABEL})\s*(?:результат\w*)?\s*(?:\([^)]*\))?\s*[:\-–]?\s*(?P<limit>{_LIMIT})", re.I
)
_NORMAL_BAND_AFTER = re.compile(
    rf"(?P<limit>[<>≤≥]\s*-?\d+(?:\.\d+)?)\s*[-–—:]?\s*(?:{_NORMAL_LABEL})", re.I
)


class ReferenceLimits(tuple):
    """(low, high, low_inclusive, high_inclusive) read off a printed reference."""

    __slots__ = ()

    def __new__(cls, low=None, high=None, low_inclusive=True, high_inclusive=True):
        return super().__new__(cls, (low, high, low_inclusive, high_inclusive))

    low = property(lambda self: self[0])
    high = property(lambda self: self[1])
    low_inclusive = property(lambda self: self[2])
    high_inclusive = property(lambda self: self[3])


#: Where one band of a printed scale stops and the next begins.
_BAND_BREAK = re.compile(r"[;\n\d<>≤≥]")


def _named_abnormal(value: str, start: int, end: int) -> bool:
    """Is the limit at value[start:end] labelled as some band other than the healthy one?

    The window before it has to cover the whole label, not just the word next
    to the numbers.  «Помірно підвищений рівень ризику: 75-125» puts
    thirty-four characters between "підвищений" and its interval, so at 24 the
    tier went unrecognised and a lipoprotein(a) of 178 was judged against the
    moderately-raised band as though it were the healthy one.

    A band can also be named *after* its interval -- Expert prints «До 5,2;
    5,2-6,2 гранично високий рівень; >6,2 високий рівень».  That is read only
    when the interval is not itself introduced by a «label:», because in that
    layout the words after it are the next band's label.
    """
    # Each window stops at the neighbouring band's numbers: what lies past them
    # labels that band, not this one.
    preceding = _BAND_BREAK.split(value[max(0, start - 48) : start])[-1]
    if NON_NORMAL_BAND_RE.search(preceding):
        return True
    following = _BAND_BREAK.split(value[end : end + 48])[0]
    return not preceding.rstrip().endswith(":") and bool(NON_NORMAL_BAND_RE.search(following))


#: «від 3.5 до 5.0», «3.5 - 5.0», «0.9 - <1.0» (an exclusive upper bound).
#: The first digit is written out and the rest of its run taken whole, so a
#: search enters the run only by consuming a digit; what follows the run is a
#: point, a blank or the «до»/dash, never a digit that could be given back.
_BETWEEN_LIMITS = re.compile(
    r"(?:від\s*)?(-?\d\d*+(?:\.\d+)?)\s*(?:до|[-–—])\s*(?:(?P<strict><)\s*)?(-?\d+(?:\.\d+)?)", re.I
)
_UPPER_LIMIT = re.compile(r"(?P<word>до|<|≤)\s*(-?\d+(?:\.\d+)?)", re.I)
_LOWER_LIMIT = re.compile(r"(?P<word>від|>|≥)\s*(-?\d+(?:\.\d+)?)", re.I)


def _refused_band_labelled(value: str, start: int) -> bool:
    """Does a «label:» introduce the limit at ``start``?"""
    return bool(re.search(r"[^\W\d_]", _BAND_BREAK.split(value[:start])[-1]))


def _one_sided_limits(value: str, *, labelled_scale: bool, refused: bool) -> ReferenceLimits:
    """The «до X» / «від X» reading of a reference with no usable «a - b»."""
    upper = _UPPER_LIMIT.search(value)
    if upper and refused and _refused_band_labelled(value, upper.start()):
        upper = None
    if upper and not (labelled_scale and _named_abnormal(value, upper.start(), upper.end())):
        return ReferenceLimits(None, float(upper.group(2)), True, upper.group("word") != "<")
    lower = _LOWER_LIMIT.search(value)
    if lower is None:
        return ReferenceLimits()
    if (refused and _refused_band_labelled(value, lower.start())) or (
        labelled_scale and _named_abnormal(value, lower.start(), lower.end())
    ):
        return ReferenceLimits()
    # "> 6.2 високий" says where *abnormality* begins, not where normality
    # does.  Read as a lower bound it means "6.2 and above is fine", which
    # would have put a green laboratory claim on a total cholesterol of
    # 8.1 mmol/L that the same line calls high.  Refuse instead: curated
    # guidance outranks the vendor anyway, and no interval at all is
    # recoverable where an inverted one is not.
    if ABNORMAL_BAND_RE.search(value):
        return ReferenceLimits()
    return ReferenceLimits(float(lower.group(2)), None, lower.group("word") != ">", True)


def _plain_limits(value: str, *, labelled_scale: bool) -> ReferenceLimits:
    between = _BETWEEN_LIMITS.search(value)
    if not between:
        return _one_sided_limits(value, labelled_scale=labelled_scale, refused=False)
    # A scale that names each of its bands is not one interval, and the
    # first pair of numbers in it is usually the *middle* band: the
    # antinuclear-antibody line "Negative <1.0; equivocal 1.0-1.2;
    # positive >1.2" yielded 1.0-1.2, the equivocal zone, published as the
    # patient's reference interval.
    if not _named_abnormal(value, between.start(), between.end()):
        return ReferenceLimits(
            float(between.group(1)), float(between.group(3)), True, not between.group("strict")
        )
    if not labelled_scale:
        return ReferenceLimits()
    # A refused middle band leaves the scale's other bands, but only an
    # *unlabelled* one: «До 5,2» on the cholesterol line above is the
    # healthy band, «Низький рівень ризику: < 75» is still a named tier.
    value = value[: between.start()] + " ; " + value[between.end() :]
    return _one_sided_limits(value, labelled_scale=labelled_scale, refused=True)


def reference_limits(reference: str | None) -> ReferenceLimits:
    """Bounds and their inclusivity from a printed reference interval.

    Strict «<»/«>» are exclusive; «≤», «≥», «до», «від» and a plain «a - b»
    include the bound.  Anything not readable exactly -- a demographic block,
    a treatment-target scale, a power of ten, a share of another analyte --
    yields no bounds at all.
    """
    if not reference:
        return ReferenceLimits()
    value = reference.replace(",", ".")
    # A lone zero («0.0» beside NRBC or reactive lymphocytes) is the value the
    # laboratory expects: a count that cannot be negative has nothing to be
    # but at most zero.  Read as no reference, an NRBC of 0.2 % against it was
    # left with no direction.  Only zero: a lone «5» could be either limit.
    if re.fullmatch(r"\s*0(?:\.0+)?\s*", value):
        return ReferenceLimits(None, 0.0, True, True)
    if refused_reference(value):
        return ReferenceLimits()
    if (
        demographic_reference(value)
        or TARGET_SCALE_RE.search(value)
        or POWER_NOTATION_RE.search(value)
        or RELATIVE_PERCENT_RE.search(value)
        # A dipstick's «+» scale is tiers, not an interval; its cut-off is
        # read by `dipstick_threshold`, and «200 - 203 = ++++» is no range.
        or _PLUS_TIER.search(value)
    ):
        return ReferenceLimits()
    labelled_scale = bool(NON_NORMAL_BAND_RE.search(value))
    if labelled_scale:
        normal = _named_normal_band(value)
        if normal is not None:
            return normal
    return _plain_limits(value, labelled_scale=labelled_scale)


def _named_normal_band(value: str) -> ReferenceLimits | None:
    """The limits of the band a labelled scale names as negative, if it names one."""
    # Whichever comes first on the line -- a number or a label -- says
    # which way round the scale is written.  Read the other way, «<0.9 -
    # негативний результат 0.9 - <1.0 - сіра зона» pairs "negative" with
    # the grey zone that follows it.
    label = re.search(_NORMAL_LABEL, value, re.I)
    number = re.search(r"\d", value)
    # A label followed by its colon introduces the numbers after it, however
    # many bands came before: «Ризик дефіциту: <20.0 ... Здорове населення:
    # 30.0 - 100.0» is not "<30.0 is healthy".
    introduces = bool(label) and bool(
        re.match(r"\s*(?:результат\w*)?\s*(?:\([^)]*\))?\s*:", value[label.end():], re.I)
    )
    limit_first = bool(label and number and number.start() < label.start()) and not introduces
    normal = (_NORMAL_BAND_AFTER if limit_first else _NORMAL_BAND_FIRST).search(value)
    if normal:
        limits = _plain_limits(normal.group("limit"), labelled_scale=False)
        if limits.low is not None or limits.high is not None:
            return limits
    return None


def reference_bounds(reference: str | None) -> tuple[float | None, float | None]:
    limits = reference_limits(reference)
    return limits.low, limits.high


def split_comma_unit(name: str) -> tuple[str, str | None]:
    """«Білок в сечі, г/л» -> («Білок в сечі», «г/л»); anything else unchanged.

    Only the comma form: a bare trailing token is too often part of a name
    ("R" and "AI" are on the allowlist) for a pass that reads every vendor.
    """
    head, comma, tail = name.rpartition(",")
    if comma and re.fullmatch(UNIT_PATTERN, tail.strip(), re.I):
        return head.strip(), tail.strip()
    return name, None


def split_name_unit(prefix: str) -> tuple[str, str | None]:
    prefix = collapse_space(prefix).strip(" ,")
    name, unit = split_comma_unit(prefix)
    if unit:
        return name, unit
    trailing = re.match(rf"^(.+?)\s+({UNIT_PATTERN})$", prefix, re.I)
    if trailing:
        return trailing.group(1).strip(), trailing.group(2).strip()
    return prefix, None


def valid_analyte_name(name: str) -> bool:
    name = name.strip()
    folded = name.casefold()
    return (
        len(name) >= 2
        and name[0].isalpha()
        and any(char.isalpha() for char in name)
        # Fragments of a reference interval that wrapped onto their own line.
        # "рівень;" is the tail of "високий рівень" and was read as an analyte
        # named "level" with a value of 6.2 -- the threshold from the scale it
        # belongs to.
        and folded.strip(";.,") not in {"від", "крові", "нормальний або", "приносний", "рівень"}
        and not any(
            token in folded
            for token in (
                "пацієнт", "тел:", "ліцензі", "стор.", "дата ",
                "показник результат", "лікар", "прилад ",
                "метод дослідження", "результат",
            )
        )
    )


CATEGORICAL_VALUE = (
    r"помірночутливий|резистентний|стійкий|чутливий|не виявлено|не виявлений|не виявлена|не виявлені|негативний|позитивний|"
    # «в нормі» is the locative Expert Hospital prints on its dipstick pads --
    # «Глюкоза, ммоль/л в нормі» (result N1) -- and without it the whole
    # row vanished: no observation, no review task.
    r"прозора|каламутна|бурштиновий|жовтий|сліди|в нормі|норма|нормальний|нормальна"
)

# An antibiogram row wears the same "<name> <number> <unit>" clothes as a
# result row -- "Бензилпеніцилін 1 од Стійкий" -- but the number is the disk
# potency and the verdict after it is the finding.  Reading it as a value of
# 1.0 would publish a meaningless number and silently drop the resistance.
SUSCEPTIBILITY_VERDICT = r"помірно\s*чутлив\w*|чутлив\w*|стійк\w*|резистентн\w*"


def has_result_header(text: str) -> bool:
    return bool(
        re.search(
            r"Показник\s+Результат|РЕЗУЛЬТАТ\s+НОРМА|Назва дослідження\s+Результат|"
            r"Результат дослідження|антигени\s+діапазон",
            text,
            re.I,
        )
    )


#: The header row a categorical table opens with.  Expert's capitals header
#: «ПОКАЗНИК РЕЗУЛЬТАТ НОРМА» is matched by it too: the pattern is
#: case-insensitive, and the text after the header is the table either way.
_CATEGORICAL_HEADER = re.compile(r"Показник\s+Результат(?:\s+Од\.)?(?:\s+Одиниці)?(?:\s+Референтн\w*)?", re.I)
_CATEGORICAL_FOOTER = re.compile(r"Результати (?:лабораторних )?досліджень не є|Дослідження виконала", re.I)
_CATEGORICAL_ROW = re.compile(
    rf"^(?P<name>.+?)\s+(?P<value>{CATEGORICAL_VALUE})(?:\s+(?P<unit>{UNIT_PATTERN}))?(?:\s+(?P<ref>.*))?$",
    re.I,
)
_BLOOD_GROUP_ROW = re.compile(r"^(Група крові)\s+([ABАВOОIІVХ]+\s*\([^)]*\))$", re.I)


def _categorical_row(candidate: str, page_number: int) -> ParsedObservation | None:
    match = _CATEGORICAL_ROW.match(candidate)
    if not match:
        return None
    name = match.group("name").strip(" ,-:")
    if (
        not valid_analyte_name(name)
        or name.casefold() == "результат"
        or re.fullmatch(CATEGORICAL_VALUE, name, re.I)
        or any(symbol in name for symbol in "<>≤≥")
    ):
        return None
    value = match.group("value")
    reference = (match.group("ref") or "").strip() or None
    unit = match.group("unit")
    if not unit:
        # Expert Hospital puts the unit before the value, behind a
        # comma: «Лейкоцити в сечі, кл/мкл негативний».
        name, unit = split_comma_unit(name)
    return ParsedObservation(
        raw_name=name,
        value_numeric=None,
        value_text=value,
        comparator=None,
        unit_raw=unit,
        reference_text=reference,
        reference_low=None,
        reference_high=None,
        page_number=page_number,
        evidence_text=candidate,
        confidence=0.91,
    )


def parse_categorical_rows(text: str, page_number: int) -> list[ParsedObservation]:
    if not has_result_header(text):
        return []
    body = _CATEGORICAL_HEADER.split(text, maxsplit=1)[-1]
    body = _CATEGORICAL_FOOTER.split(body, maxsplit=1)[0]
    lines = [collapse_space(line) for line in body.splitlines() if collapse_space(line)]
    observations: list[ParsedObservation] = []
    for index, line in enumerate(lines):
        candidates = [line, f"{lines[index - 1]} {line}"] if index > 0 else [line]
        found = next(
            (row for row in (_categorical_row(candidate, page_number) for candidate in candidates) if row), None
        )
        if found:
            observations.append(found)
    # Blood group exports omit both a unit and reference interval.
    for line in lines:
        match = _BLOOD_GROUP_ROW.match(line)
        if match:
            observations.append(
                ParsedObservation(
                    raw_name=match.group(1), value_numeric=None, value_text=match.group(2),
                    comparator=None, unit_raw=None, reference_text=None,
                    reference_low=None, reference_high=None, page_number=page_number,
                    evidence_text=line, confidence=0.96,
                )
            )
    return observations


def parse_pcr_sections(text: str, page_number: int) -> list[ParsedObservation]:
    """Quantitative PCR results, which EskuLab prints as a panel, not a row.

    Ureaplasma is written out over six labelled lines -- «Вид дослідження»,
    «Метод дослідження», «Прилад», «Результат», «Клінічно значуща кількість» --
    instead of the table every other organism on the same page sits in.  The
    last of those lines is the report's own threshold, and it was the only row
    on the page that reached the record with no reference at all: a reader
    seeing "не виявлено" had nothing telling them what quantity would have
    mattered.  It is kept as text.  `reference_bounds` refuses to turn it into
    a number, which is correct twice over -- «>10^4» says where colonisation
    *begins*, not where health ends, and the caret would otherwise be read as
    a bound of 10.
    """
    pattern = re.compile(
        rf"(?P<name>Виявлення ДНК\s+[^\n]+\(ПЛР\)\s*\(кількісне визначення\))"
        rf"(?:(?!Виявлення ДНК).)*?Результат\s+(?P<value>{CATEGORICAL_VALUE})\s*(?P<unit>Г[ЄЕ]/мл)?"
        # Anchored straight onto the result line, because it is the next line
        # printed.  A lazy gap in front of an optional group matches nothing
        # every time -- the engine takes the empty option and never looks.
        rf"(?:\s*(?P<threshold>Клінічно значуща кількість\s+[^\n]+))?",
        re.I | re.S,
    )
    observations = []
    for match in pattern.finditer(text):
        evidence = collapse_space(match.group(0))
        threshold = match.group("threshold")
        reference = collapse_space(threshold) if threshold else None
        observations.append(
            ParsedObservation(
                raw_name=collapse_space(match.group("name")), value_numeric=None,
                value_text=match.group("value"), comparator=None, unit_raw=match.group("unit"),
                reference_text=reference, reference_low=None, reference_high=None,
                page_number=page_number, evidence_text=evidence, confidence=0.94,
            )
        )
    return observations


def parse_unitless_numeric_rows(text: str, page_number: int) -> list[ParsedObservation]:
    if not has_result_header(text):
        return []
    pattern = re.compile(
        rf"^(?P<name>[A-Za-zА-Яа-яІіЇїЄєҐґΓγ].+?)\s+(?P<value>{NUMBER})\s+(?P<ref>(?:від|до|<|>|≤|≥|-?\d+(?:[.,]\d+)?\s*[-–—]).*)$",
        re.I,
    )
    observations: list[ParsedObservation] = []
    for line in [collapse_space(item) for item in text.splitlines() if collapse_space(item)]:
        match = pattern.match(line)
        if not match:
            continue
        name = match.group("name").strip(" ,-:")
        if not valid_analyte_name(name):
            continue
        raw_value = match.group("value").replace(" ", "")
        numeric = parse_decimal(raw_value)
        if numeric is None:
            continue
        reference = match.group("ref")
        low, high = reference_bounds(reference)
        comparator_match = _COMPARATOR.match(raw_value)
        observations.append(
            ParsedObservation(
                raw_name=name, value_numeric=numeric, value_text=None,
                comparator=comparator_match.group(0) if comparator_match else None,
                unit_raw="%" if raw_value.endswith("%") else None,
                reference_text=reference, reference_low=low, reference_high=high,
                page_number=page_number, evidence_text=line, confidence=0.91,
            )
        )
    return observations


#: The end of an Expert Hospital label printed below its value: an optional
#: bracketed code and its comma, then a unit, and nothing else on the line.
EXPERT_WRAPPED_TAIL = re.compile(
    rf"^(?:(?P<code>\([^()]*\))\s*,\s*)?(?P<unit>{UNIT_PATTERN})$", re.I
)


#: The reference column may open with the band's own name rather than a
#: number.  On the lipid panel the total-cholesterol row reads
#: "Холестерин загальний, ммоль/л 8,1 високий рівень; >6,2 високий", with
#: the rest of the scale wrapped onto the lines above and below it.  Without
#: "високий" in this list the row matched nothing at all and the single most
#: important number on a lipid panel -- 8.1 mmol/L, the highest in the
#: record, and flagged as high by the laboratory itself -- was absent.
_EXPERT_DIRECT = re.compile(
    rf"^(?P<prefix>.+?)\s+(?P<value>{NUMBER})\s+"
    rf"(?P<ref>(?:від|до|<|>|≤|≥|Негатив|Сумнів|Позитив|високий|низьк|"
    rf"оптимальн|граничн|-?\d+(?:[.,]\d+)?\s*[-–—]).*)$",
    re.I,
)
#: A row whose reference is absent, or written as a scale of "+" symbols
#: wrapped across the neighbouring lines, matches nothing above and used to
#: be dropped whole -- ketones, urine bilirubin and urobilinogen were all
#: missing from a urinalysis that reported them.  The discriminator is the
#: unit: this vendor writes "<name>, <unit> <value>", and requiring a comma
#: and a known unit immediately before the number keeps prose out.
_EXPERT_UNIT_FIRST = re.compile(
    rf"^(?P<prefix>.+?,\s*(?:{UNIT_PATTERN}))\s+(?P<value>{NUMBER})(?:\s+(?P<ref>.*))?$",
    re.I,
)
#: Microscopy rows state their result as an HPF range or a plus scale --
#: «Лейкоцити (WBC), в п/з 0-1 0-5», «Слиз, в п/з + (не виявлено)» -- which
#: is neither a number nor a categorical word, so both passes above dropped
#: the row whole.  The mucus «+», present against a "не виявлено" reference,
#: was an abnormal finding entirely absent from the record.  Stored as text,
#: the way parse_st_paraskeva stores «0-1-2 в п/з».  The reference starts at
#: the first non-blank after the gap and runs to the end of the line, so the
#: gap and the reference never compete for the same blank.  A row that ends
#: in blanks instead takes the last of them as its reference, as «\s+(.+)$»
#: did; that shape is its own pattern, tried second.
_EXPERT_MICROSCOPY_ROW = r"^(?P<name>.+?,\s*в\s*п/з)\s+(?P<value>\d+(?:-\d+){1,2}|\+{1,4})"
_EXPERT_MICROSCOPY = re.compile(_EXPERT_MICROSCOPY_ROW + r"(?:\s+(?P<ref>\S.*+))?$")
_EXPERT_MICROSCOPY_BLANK_END = re.compile(_EXPERT_MICROSCOPY_ROW + r"\s+(?P<ref>[^\S\n])$")


def _expert_microscopy_match(line: str) -> re.Match[str] | None:
    """A microscopy row, the referenced shape first.  Trying the blank-ended
    shape second finds what one «\\s+(.+)$» pattern found: where it fits, only
    blanks follow the value, so no longer name could fit the first shape."""
    return _EXPERT_MICROSCOPY.match(line) or _EXPERT_MICROSCOPY_BLANK_END.match(line)


_EXPERT_HEADER = re.compile(r"ПОКАЗНИК\s+РЕЗУЛЬТАТ\s+(?:НОРМА|РЕФЕРЕНТНІ\s+ЗНАЧЕННЯ)", re.I)
_EXPERT_FOOTER = re.compile(r"Результати досліджень не є", re.I)


def _expert_body_lines(text: str) -> list[str]:
    """The non-empty lines between Expert's table header and its footer."""
    body = _EXPERT_HEADER.split(text, maxsplit=1)[-1]
    body = _EXPERT_FOOTER.split(body, maxsplit=1)[0]
    return [collapse_space(line) for line in body.splitlines() if collapse_space(line)]


def _expert_direct_match(lines: list[str], index: int):
    """The narrowest window ending at line ``index`` that reads as a row.

    Returns (candidate, line indexes, match, name, unit) or None.
    """
    windows: list[tuple[str, set[int]]] = [(lines[index], {index})]
    if index > 0:
        windows.append((f"{lines[index - 1]} {lines[index]}", {index - 1, index}))
    if index > 1:
        windows.append((f"{lines[index - 2]} {lines[index - 1]} {lines[index]}", {index - 2, index - 1, index}))
    for candidate, indexes in windows:
        match = _EXPERT_DIRECT.match(candidate)
        if not match:
            continue
        name, unit = split_name_unit(match.group("prefix"))
        if (
            not valid_analyte_name(name)
            or SWALLOWED_VALUE.search(name)
            # A wrapped unit line on its own («х 10*9/л») is not a name;
            # the wider window that includes the label above it is.
            or re.fullmatch(UNIT_PATTERN, name, re.I)
        ):
            # The prefix ran past the real result to reach a number the
            # reference column happened to allow: "Холестерин загальний,
            # ммоль/л 7,35 рівень; >6,2 високий рівень" matched with 6.2 --
            # the threshold -- as the value and everything before it as the
            # analyte's name.  A decimal standing on its own is a
            # measurement, never part of a name.
            continue
        return candidate, indexes, match, name, unit
    return None


def _expert_numeric(
    name: str, raw_value: str, unit: str | None, reference: str | None, page_number: int,
    evidence: str, confidence: float,
) -> ParsedObservation | None:
    """An Expert text row whose result is a number, with its comparator."""
    numeric = parse_decimal(raw_value)
    if numeric is None:
        return None
    low, high = reference_bounds(reference)
    comparator_match = _COMPARATOR.match(raw_value)
    return ParsedObservation(
        raw_name=name,
        value_numeric=numeric,
        value_text=None,
        comparator=comparator_match.group(0) if comparator_match else None,
        unit_raw=unit,
        reference_text=reference,
        reference_low=low,
        reference_high=high,
        page_number=page_number,
        evidence_text=evidence,
        confidence=confidence,
    )


def _with_wrapped_tail(lines: list[str], used: set[int], selected: tuple):
    """``selected`` (candidate, indexes, match, name, unit) with the label's
    wrapped tail taken in, when the line under the row is one.

    The label wrapped and its end landed *under* the value line:
        Абсолютне значення суміші (моноцити, базофіли та еозинофіли)
        0,7 від 0,1 до 0,9
        (MID#), х 10*9/л
    or, wrapped one bracket later, «... (MID#),» / value / «х 10*9/л».
    The tail carries the unit and, in the first shape, the code that
    tells MID# (count) from MID% (fraction) -- the same trap as Synevo's
    RDW-SD/RDW-CV.  Taken only when the row has no unit of its own and
    either the tail brings a code or the label ended on a comma.
    """
    candidate, indexes, match, name, unit = selected
    following = max(indexes) + 1
    if unit or following >= len(lines) or following in used:
        return selected
    tail = EXPERT_WRAPPED_TAIL.match(lines[following])
    if not (tail and (tail.group("code") or match.group("prefix").rstrip().endswith(","))):
        return selected
    if tail.group("code"):
        name = f"{name} {tail.group('code')}"
    return f"{candidate} {lines[following]}", indexes | {following}, match, name, tail.group("unit")


def _expert_direct_rows(lines: list[str], page_number: int, used: set[int]) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    for index in range(len(lines)):
        selected = _expert_direct_match(lines, index)
        if not selected or selected[1] & used:
            continue
        candidate, indexes, match, name, unit = _with_wrapped_tail(lines, used, selected)
        raw_value = match.group("value").replace(" ", "")
        item = _expert_numeric(
            name, raw_value, "%" if raw_value.endswith("%") and not unit else unit,
            match.group("ref").strip(), page_number, candidate, 0.93,
        )
        if item is None:
            continue
        observations.append(item)
        used.update(indexes)
    return observations


def _expert_unit_first_rows(lines: list[str], page_number: int, used: set[int]) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    for index, line in enumerate(lines):
        match = None if index in used else _EXPERT_UNIT_FIRST.match(line)
        if not match:
            continue
        name, unit = split_name_unit(match.group("prefix"))
        if not valid_analyte_name(name):
            continue
        item = _expert_numeric(
            name, match.group("value").replace(" ", ""), unit,
            (match.group("ref") or "").strip() or None, page_number, line, 0.90,
        )
        if item is None:
            continue
        observations.append(item)
        used.add(index)
    return observations


def _expert_microscopy_rows(lines: list[str], page_number: int, used: set[int]) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    for index, line in enumerate(lines):
        match = None if index in used else _expert_microscopy_match(line)
        if not match:
            continue
        name, unit = split_comma_unit(match.group("name").strip(" ,-:"))
        if not valid_analyte_name(name):
            continue
        observations.append(
            ParsedObservation(
                raw_name=name,
                value_numeric=None,
                value_text=match.group("value"),
                comparator=None,
                unit_raw=unit,
                reference_text=(match.group("ref") or "").strip() or None,
                reference_low=None,
                reference_high=None,
                page_number=page_number,
                evidence_text=line,
                confidence=0.90,
            )
        )
        used.add(index)
    return observations


def parse_expert_page(text: str, page_number: int) -> list[ParsedObservation]:
    """Expert Hospital's results read as text: three passes, each taking the
    lines the passes before it left unread."""
    if not _EXPERT_HEADER.search(text):
        return []
    lines = _expert_body_lines(text)
    used: set[int] = set()
    observations = _expert_direct_rows(lines, page_number, used)
    observations += _expert_unit_first_rows(lines, page_number, used)
    observations += _expert_microscopy_rows(lines, page_number, used)
    return observations


#: A phrase naming the material a row was measured in, printed glued to or
#: under the analyte name: «Глікований гемоглобін (HbA1c)цільна кров»,
#: «Антинуклеарні антитіла (ANA)сироватка крові».  Longest first.
SPECIMEN_PHRASE = re.compile(
    r"(?P<specimen>сироватка\s+крові|цільна\s+кров|плазма\s+крові|сироватка|сеча|кал)\s*$", re.I
)

#: What an Expert result cell holds: a number (with %, comparator), an HPF
#: range «0-1-2», a plus scale, or one of the categorical words.
_EXPERT_VALUE = re.compile(
    rf"^(?:(?P<number>{NUMBER})|(?P<range>\d+(?:-\d+){{1,2}})|(?P<plus>\+{{1,4}})|"
    rf"(?P<word>(?:{CATEGORICAL_VALUE}|негативн\w*|позитивн\w*|виявлено)(?:\s+результат)?))$",
    re.I,
)


#: The header row, word for word.  The blood count prints «РЕФЕРЕНТНІ
#: ЗНАЧЕННЯ» where every other panel prints «НОРМА»; matching only the latter
#: left a whole blood count (27 results) with no observations at all.
_EXPERT_TABLE_HEADERS = (
    ["ПОКАЗНИК", "РЕЗУЛЬТАТ", "НОРМА"],
    ["ПОКАЗНИК", "РЕЗУЛЬТАТ", "РЕФЕРЕНТНІ", "ЗНАЧЕННЯ"],
)


def parse_expert_table(words: list, page_number: int) -> list[ParsedObservation] | None:
    """Read an Expert Hospital results table off the page's word positions.

    The table is three columns -- ПОКАЗНИК, РЕЗУЛЬТАТ, НОРМА -- and every cell
    is centred vertically in its row, so a long label or a long reference
    wraps *above and below* the value line.  Flattened to text the pieces
    interleave with the neighbouring rows: HbA1c's reference arrived as three
    fragments around its value, so a constant was hardcoded in its place (and
    then printed on a report whose own reference was «4.0 - 5.7»); the
    total-cholesterol scale lost its first band; vitamin D and ANA each needed
    a parser of their own that stored an English label; an HBsAg label lost the
    «В (HbsAg)» that wrapped under its value; and every dipstick pad of the
    urinalysis lost its «+» scale.

    Columns are taken from the header row and each line is given to the value
    line nearest it.  Returns ``None`` when the page draws no such table, so
    the caller falls back to the text passes (scans have no word positions).
    """
    lines = _word_lines(words)
    header_index = next(
        (
            index for index, line in enumerate(lines)
            if [word[3] for word in line] in _EXPERT_TABLE_HEADERS
        ),
        None,
    )
    if header_index is None:
        return None
    header = lines[header_index]
    columns = (header[1][0] - 20.0, header[2][0] - 55.0)
    body: list[list[tuple[float, float, float, str]]] = []
    for line in lines[header_index + 1 :]:
        if _EXPERT_TABLE_END.match(" ".join(word[3] for word in line)):
            break
        body.append(line)
    anchors = [index for index, line in enumerate(body) if _expert_cells(line, columns)[1]]
    if not anchors:
        return []
    members: dict[int, list[int]] = {anchor: [] for anchor in anchors}
    for index, line in enumerate(body):
        top = line[0][2]
        nearest = min(anchors, key=lambda anchor, top=top: (abs(body[anchor][0][2] - top), -anchor))
        members[nearest].append(index)
    observations: list[ParsedObservation] = []
    for anchor in anchors:
        rows = sorted(members[anchor], key=lambda index: body[index][0][2])
        item = _expert_table_row(body, anchor, rows, columns, page_number)
        if item is not None:
            observations.append(item)
    return observations


_EXPERT_TABLE_END = re.compile(r"Результати досліджень\b|Лікар\b|Сайт лікарні")


def _expert_cells(line, columns: tuple[float, float]):
    """A table line's words split into the name, value and reference columns."""
    value_from, reference_from = columns
    name = [w for w in line if w[0] < value_from]
    value = [w for w in line if value_from <= w[0] < reference_from]
    reference = [w for w in line if w[0] >= reference_from]
    return name, value, reference


def _expert_table_row(
    body: list, anchor: int, rows: list[int], columns: tuple[float, float], page_number: int
) -> ParsedObservation | None:
    """One row of the table: its value line ``anchor`` and the lines around it."""
    name_parts, reference_parts = [], []
    for index in rows:
        name_words, _, reference_words = _expert_cells(body[index], columns)
        name_parts.extend(word[3] for word in name_words)
        reference_parts.extend(word[3] for word in reference_words)
    value = collapse_space(" ".join(word[3] for word in _expert_cells(body[anchor], columns)[1]))
    # A word broken at its hyphen over two lines rejoins without the space.
    label = _HYPHEN_BREAK.sub("-", collapse_space(" ".join(name_parts))).strip(" ,-:")
    reference = _HYPHEN_BREAK.sub("-", collapse_space(" ".join(reference_parts))) or None
    evidence = collapse_space(f"{label} {value} {reference or ''}")
    # «(HbA1c)цільна кров» -- the specimen printed hard against the label.
    specimen = None
    found = SPECIMEN_PHRASE.search(label)
    if found and found.start() > 0 and (label[found.start() - 1] in ") " ):
        specimen = collapse_space(found.group("specimen"))
        label = label[: found.start()].strip(" ,")
    name, unit = split_name_unit(label)
    shape = _EXPERT_VALUE.match(value)
    if not valid_analyte_name(name) or re.fullmatch(UNIT_PATTERN, name, re.I):
        return None
    # Anything else in the result column of a row the table drew is a
    # qualitative result in a shape not listed above -- «А(ІІ)», «(+)
    # позитивний» -- and is kept as text rather than dropped.
    if not (shape and shape.group("number")):
        return ParsedObservation(
            raw_name=name, value_numeric=None, value_text=value, comparator=None,
            unit_raw=unit, reference_text=reference, reference_low=None,
            reference_high=None, page_number=page_number, evidence_text=evidence,
            confidence=0.93, specimen=specimen,
        )
    raw_value = value.replace(" ", "")
    numeric = parse_decimal(raw_value)
    if numeric is None:
        return None
    limits = reference_limits(reference)
    comparator = _COMPARATOR.match(raw_value)
    return ParsedObservation(
        raw_name=name, value_numeric=numeric, value_text=None,
        comparator=comparator.group(0) if comparator else None,
        unit_raw="%" if raw_value.endswith("%") and not unit else unit,
        reference_text=reference, reference_low=limits.low, reference_high=limits.high,
        reference_low_inclusive=limits.low_inclusive,
        reference_high_inclusive=limits.high_inclusive,
        page_number=page_number, evidence_text=evidence, confidence=0.95,
        specimen=specimen,
    )


#: A wrapped analyte label: the printed name runs past its own value and
#: finishes on the next line, carrying the parenthesised abbreviation that says
#: which measurement it actually was.  Two rows on the Synevo CBC print an
#: identical first line and are told apart only down here:
#:
#:     Ширина розподілення еритроцитів 36.6 фл 35.0 - 46.0
#:     (RDW-SD)
#:     Ширина розподілення еритроцитів 12.1 % 12.0 - 15.0
#:     (RDW-CV)
#:
#: Without the tail both become "Red cell distribution width, CV" and a 36.6 fL
#: spread is published as a 36.6 % one - four times the upper limit, an alarm
#: for a normal result.  Only a fragment that opens lowercase or with a bracket
#: continues a name; a capitalised line is the next reference band, not a tail.
NAME_CONTINUATION = re.compile(r"^(?P<tail>\([^)]*\)|[a-zа-яіїєґ][^()]*\([^)]*\))")

#: A word of a label printed in capitals: Synevo qualifies the assay that way
#: and wraps the qualifier under its own value -- «Тиреотропний гормон. 1.61
#: мкМО/мл» over «ВИСОКОЧУТЛИВИЙ,» over «БІОТИН-НЕЗАЛЕЖНИЙ».  Four letters at
#: least, Cyrillic only, so a reference band («Дорослі:») or a Latin method
#: code never reads as one.
_CAPS_WORD = re.compile(r"^[А-ЯІЇЄҐ][А-ЯІЇЄҐ'-]{3,}[,.]?$")
#: A lowercase word continuing a label that ended on a comma: «Вірус гепатиту
#: B (HBV), HBcorAg,» over «антитіла сумарні ≤1.0 - ...».
_LOWER_WORD = re.compile(r"^[a-zа-яіїєґ'][a-zа-яіїєґ'-]*,?$")
#: Lowercase words that open a reference column rather than finish a label.
_NOT_A_NAME_WORD = {"від", "до", "або", "чоловіки", "жінки", "діти", "дорослі"}


def wrapped_label_tail(raw_name: str, following: list[str]) -> str | None:
    """The rest of a Synevo label that wrapped under its own value, or None.

    The tail sits at the start of the next line, before that line's reference
    column, and is recognised by what the first line left open:

    * an unclosed bracket takes words up to and including the bracket that
      closes it -- «(ЛПВЩ,» + «HDL) Чоловіки: ≥1.0» is «(ЛПВЩ, HDL)», and
      «25-» + «(OH)D) Дефіцит» is «25-(OH)D)».  No closing bracket on the next
      line means no tail: guessing where the label ends would be worse than
      the cut-off name;
    * a trailing comma takes a run of lowercase words («антитіла сумарні»)
      or of capitals;
    * a trailing full stop takes only capitals («ВИСОКОСПЕЦИФІЧНИЙ.
      БІОІНТАКТНИЙ»).  A capitals run that ends on a comma continues onto the
      line after.
    """
    name = raw_name.rstrip()
    if not following:
        return None
    depth = name.count("(") - name.count(")")
    if depth > 0:
        return _bracket_tail(name, following[0], depth)
    if depth < 0 or not name.endswith((",", ".")):
        return None
    words = _label_tail_words(following, lowercase_allowed=name.endswith(","))
    if not words:
        return None
    return collapse_space(f"{name} {' '.join(words)}").rstrip(",")


def _bracket_tail(name: str, line: str, depth: int) -> str | None:
    """``name`` completed up to the bracket on ``line`` that closes it."""
    # A capitalised line is the next reference band, never the inside of
    # a bracket -- except a bracket opening again: «(OH)D)».
    opener = line.split()[0]
    if not (opener[0].islower() or opener[0] == "(" or opener.endswith(")")):
        return None
    for position, char in enumerate(line):
        depth += (char == "(") - (char == ")")
        if depth == 0:
            tail = line[: position + 1]
            glue = "" if name.endswith("-") else " "
            return f"{name}{glue}{tail}"
    return None


_CLOSED_CODE = re.compile(r"^\([^()\s]{2,12}\)$")


def _label_tail_words(following: list[str], *, lowercase_allowed: bool) -> list[str]:
    """The words that finish a label ending on a comma or a full stop."""
    words: list[str] = []
    for line in following[:3]:
        taken = 0
        for token in line.split():
            lower = (
                lowercase_allowed
                and _LOWER_WORD.match(token)
                and token.strip(",") not in _NOT_A_NAME_WORD
            )
            if words and lowercase_allowed and _CLOSED_CODE.match(token):
                # The abbreviation closing a lowercase run: «Пероксидаза
                # щитоподібної залози,» / «антитіла (АТПО) Метод: ...».
                words.append(token)
                return words
            if not (lower or _CAPS_WORD.match(token)):
                break
            words.append(token)
            taken += 1
        # Only a run of capitals that stops on a comma carries on below.
        if not (taken and words[-1].endswith(",") and _CAPS_WORD.match(words[-1])):
            break
    return words


#: A reference interval that prints one limit per sex and wraps after the
#: first.  EskuLab's automated urinalysis puts the female limit on the value
#: line and the male limit on the line below:
#:
#:     Лейкоцити в мкл (WBC) 107.6 кл/мкл жінки < 28.0
#:     чоловіки < 11.2
#:
#: Matching one line at a time keeps only the half that happened to be printed
#: first.  For a male patient that is the wrong half and the right one is gone:
#: 107.6 leukocytes per microlitre -- nearly ten times his own limit, and
#: marked pyuria -- sat in the record against a female threshold that
#: `reference_applies` then correctly refused, leaving the count with no bar at
#: all.  The tail is picked up here and both clauses travel together;
#: `applicable_reference_bounds` chooses the one that describes the patient.
SEX_REFERENCE_CONTINUATION = re.compile(
    r"^(?P<sex>чоловіки|жінки|men|women|male|female)\b\s*(?:[<>≤≥]\s*)?\d", re.I
)
_MALE_REFERENCE = re.compile(r"чолов|\bmale\b|\bmen\b", re.I)
_FEMALE_REFERENCE = re.compile(r"жін|\bfemale\b|\bwomen\b", re.I)


def sex_reference_tail(reference: str | None, following: list[str]) -> str | None:
    """The other sex's limit, when it wrapped away from its own row.

    The two halves are not always adjacent: this vendor's PDF interleaves a
    fragment of the neighbouring column between them, so the male limit lands
    two lines below the female one.  A short lookahead finds it.

    The guard that makes the lookahead safe is not the distance but the sexes:
    a tail is only taken when the reference already names one sex and the
    candidate names the other.  A line naming the same sex, or naming none,
    belongs to some other row.
    """
    if not reference:
        return None
    has_male = bool(_MALE_REFERENCE.search(reference))
    has_female = bool(_FEMALE_REFERENCE.search(reference))
    if has_male == has_female:  # names both already, or neither
        return None
    wanted = _FEMALE_REFERENCE if has_male else _MALE_REFERENCE
    for line in following:
        if SEX_REFERENCE_CONTINUATION.match(line) and wanted.match(line):
            return line
    return None


_UNIT_ROW = re.compile(
    rf"^(?P<name>.+?)\s+(?P<value>{NUMBER})\s+(?P<unit>{UNIT_PATTERN})(?:\s+(?P<ref>.*))?$",
    re.I,
)
_SUSCEPTIBILITY_REFERENCE = re.compile(rf"^(?:{SUSCEPTIBILITY_VERDICT})\b", re.I)


def _lines_before_next_row(lines: list[str], start: int, stop: int) -> list[str]:
    """``lines[start:stop]`` up to, not including, the next result row."""
    taken: list[str] = []
    for candidate in lines[start:stop]:
        if _UNIT_ROW.match(candidate):
            break
        taken.append(candidate)
    return taken


def _unit_row_name(printed: str, following: list[str]) -> str:
    """The row's label, with a tail that wrapped onto the lines below.

    A name whose own brackets already close takes a bracketed tail
    (RDW-SD / RDW-CV).  An unclosed "(" means the wrap fell inside the
    bracket - "Вітамін Д (25-гідроксивітамін D, 25-" continues "(OH)D)"
    - and `wrapped_label_tail` completes it up to the closing bracket
    rather than gluing a fragment on.  It reads the name as printed,
    before the strip, because the trailing comma, hyphen or full stop
    is what says the label goes on.
    """
    name = printed.strip(" ,-:.")
    wrapped = wrapped_label_tail(printed, following)
    if wrapped:
        return collapse_space(wrapped).strip(" ,-:.")
    if following and name.count("(") == name.count(")"):
        tail = NAME_CONTINUATION.match(following[0])
        if tail:
            return collapse_space(f"{name} {tail.group('tail')}")
    return name


def _electrolyte_name(name: str) -> str:
    """One label per ionised electrolyte, however the row printed it."""
    if re.search(r"\(K\)", name, re.I) or name.casefold().startswith("калій"):
        return "Калій (іонізований) (K), сироватка крові"
    if name.casefold().startswith("натрій"):
        return "Натрій (іонізований) (Na), сироватка крові"
    if name.casefold().startswith("кальцій іонізований"):
        return "Кальцій іонізований (сироватка)"
    return name


def _unit_row_reference(match: re.Match, lines: list[str], index: int) -> str | None:
    """The row's printed reference, with the other sex's limit if it wrapped below."""
    reference = (match.group("ref") or "").strip() or None
    # Stop the lookahead at the next result row: past it, any reference
    # belongs to that row and not to this one.
    tail = sex_reference_tail(reference, _lines_before_next_row(lines, index + 1, index + 5))
    return f"{reference} {tail}" if tail else reference


def parse_unit_rows(text: str, page_number: int) -> list[ParsedObservation]:
    lines = [collapse_space(line) for line in text.splitlines() if collapse_space(line)]
    observations: list[ParsedObservation] = []
    for index, line in enumerate(lines):
        match = _UNIT_ROW.match(line)
        if not match:
            continue
        name = _unit_row_name(match.group("name"), _lines_before_next_row(lines, index + 1, index + 4))
        if not valid_analyte_name(name):
            continue
        name = _electrolyte_name(name)
        raw_value = match.group("value").replace(" ", "")
        numeric = parse_decimal(raw_value)
        if numeric is None:
            continue
        reference = _unit_row_reference(match, lines, index)
        if reference and _SUSCEPTIBILITY_REFERENCE.match(reference):
            continue
        low, high = reference_bounds(reference)
        comparator_match = _COMPARATOR.match(raw_value)
        observations.append(
            ParsedObservation(
                raw_name=name,
                value_numeric=numeric,
                value_text=None,
                comparator=comparator_match.group(0) if comparator_match else None,
                unit_raw=match.group("unit"),
                reference_text=reference,
                reference_low=low,
                reference_high=high,
                page_number=page_number,
                evidence_text=line,
                confidence=0.95,
            )
        )
    return observations


_HBA1C_LABEL = re.compile(r"Глікований гемоглобін\s*\(HbA1c\)", re.I)
#: «5.6 % 4.0 - 5.7»: the value, then whatever of the reference shares its
#: line.  The blanks after «%» are taken whole and the reference runs to the
#: end of the line: giving a blank back could never rescue a failed «$».
_HBA1C_VALUE = re.compile(r"(\d+[.,]\d+)\s*%\s*+(.*+)$")


def parse_wrapped_hba1c(text: str, page_number: int) -> list[ParsedObservation]:
    """HbA1c printed as a wrapped cell, for a page read without word positions.

    The label, its value and its three-band reference are interleaved over
    five lines (see `parse_expert_table`, which reads the same page by column
    when it can).  The reference is whatever the body prints that is neither
    the label, its specimen tail, nor the value -- the printed scale, never a
    constant: the constant this replaced was the 2025-02 report's scale, and
    was then shown on a report that prints «4.0 - 5.7».
    """
    if not _EXPERT_HEADER.search(text):
        return []
    lines = _expert_body_lines(text)
    label_index = next((index for index, line in enumerate(lines) if _HBA1C_LABEL.match(line)), None)
    if label_index is None or label_index + 1 >= len(lines):
        return []
    label_line = lines[label_index]
    label = _HBA1C_LABEL.match(label_line).group(0)
    if re.search(r"\d", label_line[len(label) :]):
        return []  # a one-line row; the direct passes read it
    value = _HBA1C_VALUE.match(lines[label_index + 1])
    if not value:
        return []
    numeric = parse_decimal(value.group(1))
    glued = label_line[len(label) :].strip()
    tail = lines[label_index + 2] if label_index + 2 < len(lines) else ""
    specimen_tail = tail if glued and re.fullmatch(r"[а-яіїєґ']+", tail) else None
    specimen = collapse_space(f"{glued} {specimen_tail or ''}") or None
    skipped = {label_index, label_index + 2} if specimen_tail else {label_index}
    reference_parts = [
        value.group(2) if index == label_index + 1 else line
        for index, line in enumerate(lines)
        if index not in skipped
    ]
    reference = collapse_space(" ".join(part for part in reference_parts if part)) or None
    limits = reference_limits(reference)
    return [
        ParsedObservation(
            raw_name=label, value_numeric=numeric, value_text=None, comparator=None, unit_raw="%",
            reference_text=reference, reference_low=limits.low, reference_high=limits.high,
            reference_low_inclusive=limits.low_inclusive, reference_high_inclusive=limits.high_inclusive,
            page_number=page_number,
            evidence_text=collapse_space(f"{label} {value.group(1)}% {reference or ''}"),
            confidence=0.93, specimen=specimen,
        )
    ]


#: «HLA-B27», «HLA B 27», «HLA B–27».
_HLA_B27 = re.compile(r"HLA\s*B\s*(?:[-–]\s*)?27", re.I)


def parse_hla_b27(text: str, page_number: int) -> list[ParsedObservation]:
    if not _HLA_B27.search(text):
        return []
    # OCR of the result image sometimes glues one stray glyph to «не»
    # («Результат іне виявлено»).  Only directly before «не», so a stray mark
    # can never turn «не виявлено» into a positive «виявлено».
    match = re.search(r"(?:^|\n)\s*Результат\s+(?:[іi1l|](?=не\s))?(не виявлено|виявлено)\s*(?:$|\n)", text, re.I)
    if not match:
        return []
    return [
        ParsedObservation(
            raw_name="Виявлення носійства гену HLA B-27",
            value_numeric=None, value_text=match.group(1), comparator=None,
            unit_raw=None, reference_text=None, reference_low=None,
            reference_high=None, page_number=page_number,
            evidence_text=collapse_space(match.group(0)), confidence=0.92,
        )
    ]


#: ALEX prints its cut-off in the legend at the foot of each page:
#: «Молекулярний алерген IgE < 0,3 негативна або сумнівна».
ALEX_LEGEND = re.compile(r"IgE\s*<\s*(?P<cut>\d+[,.]\d+)\s+негативн\w*\s+або\s+сумнівн\w*", re.I)


def _alex_rows(words: list) -> list[tuple[str, str | None, str, str]] | None:
    """(name, comparator, value, evidence) per ALEX row, read by column.

    A row whose common name is too long for its cell wraps it *around* the
    value line: «Акація срібляста (Рід тропічних» / «Aca m < 0,10» /
    «дерев)».  Read as text the value line alone was the row, so the allergen
    was stored as the bare code «Aca m»; and «Подорожник ланцетолистий < 0,10»
    over «Pla l» lost its code instead.  Each column is joined top to bottom
    over the lines within a few points of the value line, then the columns in
    printed order: common name, code, protein family.
    """
    lines = _word_lines(words)
    header = next(
        (line for line in lines if [word[3] for word in line][:3] == ["Позначення", "E/M", "Алерген"]),
        None,
    )
    if header is None:
        return None
    code_from = header[2][0] - 5.0
    family_from = next((word[0] for word in header if word[3] == "Сімейство"), code_from + 80.0) - 5.0
    bounds = (code_from, family_from, family_from + 100.0)
    rows = []
    for index, line in enumerate(lines):
        row = _alex_row(lines, index, bounds)
        if row is not None:
            rows.append(row)
    return rows


def _alex_row(lines: list, index: int, bounds: tuple[float, float, float]):
    """(name, comparator, value, evidence) for the ALEX value line ``lines[index]``, or None."""
    line = lines[index]
    value_from = bounds[2]
    value_words = [word for word in line if word[0] >= value_from]
    if not value_words or not re.fullmatch(r"\d+[,.]\d+", value_words[-1][3]):
        return None
    comparator = "<" if any(word[3] == "<" for word in value_words) else None
    top = line[0][2]
    group = [line] + [
        other for other in lines[max(0, index - 2) : index + 3]
        if other is not line
        and abs(other[0][2] - top) <= 8.0
        and not any(word[0] >= value_from for word in other)
    ]
    group.sort(key=lambda item: item[0][2])
    # A word broken at its hyphen rejoins without a space: «Trypsin-» /
    # «Inhibitor» is Trypsin-Inhibitor.
    name = collapse_space(
        " ".join(_HYPHEN_BREAK.sub("-", " ".join(column)) for column in _alex_columns(group, bounds))
    )
    evidence = collapse_space(f"{name} {'< ' if comparator else ''}{value_words[-1][3]}")
    return name, comparator, value_words[-1][3], evidence


def _alex_columns(group: list, bounds: tuple[float, float, float]) -> list[list[str]]:
    """The words of a row's lines, top to bottom, sorted into name, code and family."""
    code_from, family_from, value_from = bounds
    columns: list[list[str]] = [[], [], []]
    for member in group:
        for word in member:
            if word[0] < code_from:
                columns[0].append(word[3])
            elif word[0] < family_from:
                columns[1].append(word[3])
            elif word[0] < value_from:
                columns[2].append(word[3])
    return columns


#: The unit every ALEX² allergen row is printed in.
ALEX_UNIT = "kUA/L"
_ALEX_RESULT_LINE = re.compile(r"^(?P<name>.*?\S)\s+(?P<comparator><\s*)?(?P<value>\d+[,.]\d+)$")


def _alex_observation(
    name: str, value: float, comparator: str | None, reference: str, cut: float | None,
    page_number: int, evidence: str,
) -> ParsedObservation:
    return ParsedObservation(
        raw_name=name, value_numeric=value, value_text=None, comparator=comparator,
        unit_raw=ALEX_UNIT, reference_text=reference, reference_low=None,
        reference_high=cut, reference_high_inclusive=False,
        page_number=page_number, evidence_text=evidence, confidence=0.99,
    )


def _alex_text_rows(lines: list[str]):
    """(name, comparator, value, evidence) per ALEX row of a page read as text."""
    for index, line in enumerate(lines):
        match = _ALEX_RESULT_LINE.match(line)
        if not match:
            continue
        name = match.group("name").strip(" ,-:")
        evidence = line
        if name == "<" and index + 1 < len(lines):
            # In three ALEX rows the PDF text objects place the numeric cell
            # immediately before its analyte-name cell.
            evidence = f"{lines[index + 1]} {line}"
            match = _ALEX_RESULT_LINE.match(evidence)
            if not match:
                continue
            name = match.group("name").strip(" ,-:")
        if not valid_analyte_name(name):
            continue
        value = parse_decimal(match.group("value"))
        if value is None:
            continue
        yield name, "<" if match.group("comparator") else None, value, evidence


def _total_ige(text: str, page_number: int) -> ParsedObservation | None:
    total = re.search(r"Загальний IgE:\s*(\d+(?:[.,]\d+)?)\s*kU/L", text, re.I)
    if not total:
        return None
    adult = re.search(r"Дорослі:\s*<\s*(\d+(?:[.,]\d+)?)\s*kU/l", text, re.I)
    return ParsedObservation(
        raw_name="Загальний IgE", value_numeric=parse_decimal(total.group(1)),
        value_text=None, comparator=None, unit_raw="kU/L",
        reference_text=collapse_space(adult.group(0)) if adult else None,
        reference_low=None,
        reference_high=parse_decimal(adult.group(1)) if adult else None,
        reference_high_inclusive=False,
        page_number=page_number, evidence_text=collapse_space(total.group(0)),
        confidence=0.99,
    )


#: Biocheck's POLYCHECK food panel («Харчова 20-I»): code, allergen, class
#: and specific IgE per line -- «f17 Лісовий горіх 1 0 .52», «f02 Молоко 0
#: <0.15».  The text layer splits a decimal at its point («0 .52»).  The
#: unit is printed only in the table-header image, «IgE [kU/l]».
_POLYCHECK_PAGE = re.compile(r"Biocheck|POLYCHECK", re.I)
_POLYCHECK_ROW = re.compile(
    r"^(?P<code>[a-z]{1,2}\d{1,3})\s+(?P<name>\S.*?)\s+(?P<cls>[0-6])\s+"
    r"(?P<comparator><)?\s*(?P<value>\d+(?:\s?[.,]\s?\d+)?)$"
)
#: The class legend, classes 0-6: «0 <0.35 Антитіла відсутні … 6 >= 100 …».
_POLYCHECK_BAND = re.compile(
    r"(?<![\d.])(?P<cls>[0-6])\s+(?P<range>(?:<|>=|≥)\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*-\s*<?\s*\d+(?:[.,]\d+)?)"
    r"\s+(?P<label>[^\d<>=≥]+?)(?=\s+[0-6]\s+(?:[<>≥]|\d)|$)"
)
POLYCHECK_UNIT = "kU/L"


def parse_polycheck_panel(text: str, page_number: int) -> list[ParsedObservation]:
    """Each allergen of a POLYCHECK panel, with its class kept.

    The reading follows the autoimmune chip from the same maker: the value
    keeps its comparator, the reference is the legend's class-0 band, the
    class gives the laboratory's reading, and the legend line of the row's
    own class is kept as the row's note.  Allergen codes («f17», «k202»)
    are printed names and are kept verbatim.
    """
    if not _POLYCHECK_PAGE.search(text):
        return []
    lines = [collapse_space(item) for item in text.splitlines() if collapse_space(item)]
    bands = _autoimmune_bands(lines, _POLYCHECK_BAND)
    negative = bands.get(0)
    observations: list[ParsedObservation] = []
    for line in lines:
        row = _POLYCHECK_ROW.match(line)
        if not row:
            continue
        printed = re.sub(r"\s", "", row.group("value"))
        value = parse_decimal(printed)
        if value is None:
            continue
        klass = int(row.group("cls"))
        band = bands.get(klass)
        observations.append(
            ParsedObservation(
                raw_name=f"{row.group('code')} {row.group('name')}", value_numeric=value, value_text=None,
                comparator=row.group("comparator"), unit_raw=POLYCHECK_UNIT,
                reference_text=negative[0] if negative else None, reference_low=None,
                reference_high=negative[2] if negative else None, reference_high_inclusive=False,
                page_number=page_number, evidence_text=line, confidence=0.95, value_printed=printed,
                # The legend calls class 0 «Антитіла відсутні» and every class
                # above it a concentration of antibodies, «Дуже низька» first:
                # class 1 is a sensitisation, where the autoimmune chip's
                # class 1 is «гранична норма».
                vendor_interpretation="within_vendor_range" if klass == 0 else "positive",
                note=f"{klass} {band[0]}" if band else None,
            )
        )
    return observations


def parse_allergy_panel(text: str, page_number: int, words: list | None = None) -> list[ParsedObservation]:
    if ALEX_UNIT not in text or not re.search(r"Позначення\s+E/M\s+Алерген", text, re.I):
        return []
    observations: list[ParsedObservation] = []
    legend = ALEX_LEGEND.search(text)
    # The printed cut-off, in the report's own words; the English sentence it
    # replaces was the application's paraphrase, shown on Ukrainian pages.
    reference = collapse_space(legend.group(0)) if legend else "IgE < 0.3 kUA/L - negative or doubtful"
    cut = parse_decimal(legend.group("cut")) if legend else 0.3
    by_column = _alex_rows(words) if words else None
    if by_column is not None:
        for name, comparator, raw_value, evidence in by_column:
            value = parse_decimal(raw_value)
            if value is not None and valid_analyte_name(name):
                observations.append(_alex_observation(name, value, comparator, reference, cut, page_number, evidence))
    else:
        lines = [collapse_space(item) for item in text.splitlines() if collapse_space(item)]
        observations.extend(
            _alex_observation(name, value, comparator, reference, cut, page_number, evidence)
            for name, comparator, value, evidence in _alex_text_rows(lines)
        )
    total = _total_ige(text, page_number)
    if total is not None:
        observations.append(total)
    return observations


#: «Staphylococcus aureus 10^5 КУО/г».  The gap before the power is taken
#: whole: the power cannot start inside it, so there is nothing to give back.
#: The shortest name «.+?» could take never ends in a blank (the gap would
#: have had it) unless it is one blank alone, so the name is written as
#: exactly that: one blank, or anything ending in a non-blank.
_COLONY_POWER_ROW = re.compile(r"^(?P<name>[^\S\n]|[^\n]*?\S)\s++10\^(?P<power>\d+)\s+КУО/г$", re.I)


def parse_microbiology_narrative(text: str, page_number: int) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    no_growth = re.search(
        r"Росту\s+(?P<name>аеробної\s+та\s+факультативно[-–]анаеробної\s+мікробіоти)\s+не\s+виявлено",
        text,
        re.I,
    )
    if no_growth:
        observations.append(
            ParsedObservation(
                raw_name="Ріст аеробної та факультативно-анаеробної мікробіоти",
                value_numeric=None, value_text="не виявлено", comparator=None,
                unit_raw=None, reference_text=None, reference_low=None,
                reference_high=None, page_number=page_number,
                evidence_text=collapse_space(no_growth.group(0)), confidence=0.99,
            )
        )
    beta = re.search(
        r"(?P<name>(?:бета|beta|6eta)[-–]haemolyticum\s+Streptococcus)\s+(?:не|He)\s+виявлено",
        text,
        re.I,
    )
    if beta:
        observations.append(
            ParsedObservation(
                raw_name="beta-haemolyticum Streptococcus", value_numeric=None,
                value_text="не виявлено", comparator=None, unit_raw=None,
                reference_text=None, reference_low=None, reference_high=None,
                page_number=page_number, evidence_text=collapse_space(beta.group(0)),
                confidence=0.86,
            )
        )
    for line in [collapse_space(item) for item in text.splitlines() if collapse_space(item)]:
        count = _COLONY_POWER_ROW.match(line)
        if count and valid_analyte_name(count.group("name")):
            observations.append(
                ParsedObservation(
                    raw_name=count.group("name").strip(" ,-:"),
                    value_numeric=float(10 ** int(count.group("power"))),
                    value_text=None, comparator=None, unit_raw="КУО/г",
                    reference_text=None, reference_low=None, reference_high=None,
                    page_number=page_number, evidence_text=line, confidence=0.86,
                )
            )
    # «10^5» survives OCR as «1045», «105» or «10145» -- the caret read as a
    # 4, as nothing, or as «14».  Anchored on the unit and the organism that
    # follow it, so no other number on the page can take this shape.
    split_count = re.search(
        r"10(?:\^|4|14|1)?5\s+[KК][УY][OО]/[гr]\s+Pseudomonas\s+aeruginosa",
        text,
        re.I,
    )
    if split_count and not any(item.raw_name == "Pseudomonas aeruginosa" for item in observations):
        observations.append(
            ParsedObservation(
                raw_name="Pseudomonas aeruginosa", value_numeric=100000.0,
                value_text=None, comparator=None, unit_raw="КУО/г",
                reference_text=None, reference_low=None, reference_high=None,
                page_number=page_number, evidence_text=collapse_space(split_count.group(0)),
                confidence=0.84,
            )
        )
    return observations


#: The antigens of Biocheck's «Аутоімунна стандартна-Х панель» (G4003), in the
#: spelling the chip report prints.  The panel arrives only as a picture, so
#: every name is OCR and is matched against this list rather than trusted.
AUTOIMMUNE_ANTIGENS = (
    "Ro/SS-A 52", "La/SS-B", "CENP-B", "Scl-70", "dsDNA", "Jo-1", "MPO", "PR3",
    "AMA M2", "LC 1", "LKM 1", "PM/Scl 100", "SRP 54", "SP 100", "gp 210", "Ku",
    "Sm", "U1-snRNP",
)

#: Cyrillic letters OCR reads in place of their Latin twins, and the reverse
#: shapes it reads for digits: «МРО» is MPO, «РВЗ» is PR3.
_TO_LATIN = str.maketrans(
    "АВЕКМНОРСТХаеікморстухЗІ", "ABEKMHOPCTXaeikmopctyx3I"
)


def _fold_key(text: str) -> str:
    return re.sub(r"[\s.\-/,]", "", text.translate(_TO_LATIN)).casefold()


def _closest(name: str, known, cutoff: float, *, with_score: bool = False):
    """The one known name ``name`` is an OCR reading of, or None.

    Two-letter names («Ku», «Sm») must match exactly: at that length one
    misread letter is a different word, not a typo.
    """
    from difflib import SequenceMatcher

    target = _fold_key(name)
    if not target:
        return None
    scored = sorted(
        (
            (SequenceMatcher(None, target, key).ratio(), item)
            for item in known
            for key in [_fold_key(item)]
            if len(key) > 2 or key == target
        ),
        reverse=True,
    )
    if not scored or scored[0][0] < cutoff:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0] and scored[1][1] != scored[0][1]:
        return None
    return scored[0] if with_score else scored[0][1]


#: One legend band: «0 <0.30 негативний результат», «1 0.30 - «0.80 гранична
#: норма», «4 >= 10 високо позитивний».  OCR prints «<» as «».
_AUTOIMMUNE_BAND = re.compile(
    r"(?<![\d.])(?P<cls>[0-4])\s+(?P<range>(?:[<«‹]|>=|≥)\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*-\s*[<«‹]?\s*\d+(?:[.,]\d+)?)"
    r"\s+(?P<label>[^\d<«‹>=≥]+?)(?=\s+[0-4]\s+(?:[<«‹>≥]|\d)|$)"
)
_AUTOIMMUNE_READING = {0: "within_vendor_range", 1: "borderline"}


def parse_autoimmune_panel(
    text: str, page_number: int, issues: list[ParseIssue] | None = None
) -> list[ParsedObservation]:
    """Each antigen of the chip: its measured IgG and the class the legend gives it.

    The row prints antigen, class (0-4) and IgG in kU/l («Ro/SS-A 52 0 <0.15»),
    and the legend under the table defines the classes.  The old reader
    accepted one shape only -- class 0, «<0.15» -- and stored the value as the
    number 0 with «<0.15» as its reference: a reading of «below the assay's
    floor» became "exactly zero", the reference was the measuring limit rather
    than the negative band, and any positive antigen, being some other shape,
    vanished without a trace.  Now the value keeps its comparator, the
    reference is the legend's class-0 band, and a known antigen whose line
    cannot be read is reported through ``issues`` instead of dropped.
    """
    if not _AUTOIMMUNE_PAGE.search(text):
        return []
    lines = [collapse_space(item) for item in text.splitlines() if collapse_space(item)]
    bands = _autoimmune_bands(lines)
    observations: list[ParsedObservation] = []
    for line in lines:
        best = _autoimmune_best_split(line)
        if best is None:
            continue
        _, antigen, _candidate, match = best
        if match is None:
            # The line names an antigen and carries no readable result.
            if issues is not None:
                issues.append(ParseIssue(page_number, "unparsed_known_analyte", antigen, line))
            continue
        item = _autoimmune_observation(line, best, bands, page_number)
        if item is not None:
            observations.append(item)
    return observations


def _autoimmune_observation(
    line: str, best: tuple, bands: dict[int, tuple[str, float | None, float | None]], page_number: int
) -> ParsedObservation | None:
    """One antigen's reading, from the split ``_autoimmune_best_split`` chose."""
    _, antigen, candidate, match = best
    value = parse_decimal(match.group("value").replace(" ", "."))
    if value is None:
        return None
    negative = bands.get(0)
    comparator = "<" if match.group("comparator") in {"<", "«", "‹"} else match.group("comparator")
    klass = int(match.group("cls")) if match.group("cls") else _autoimmune_class(value, comparator, bands)
    return ParsedObservation(
        raw_name=antigen, value_numeric=value, value_text=None, comparator=comparator,
        unit_raw="kU/L",
        reference_text=negative[0] if negative else None,
        reference_low=None,
        reference_high=negative[2] if negative else None,
        reference_high_inclusive=False,
        page_number=page_number, evidence_text=line,
        confidence=0.90 if antigen == candidate.strip(" .") else 0.84,
        value_printed=match.group("value").replace(" ", "."),
        vendor_interpretation=(
            None if klass is None else _AUTOIMMUNE_READING.get(klass, "positive")
        ),
    )


#: The chip report: its table heading or the panel's own name.
_AUTOIMMUNE_PAGE = re.compile(r"антигени\s.*діапазон|ауто[їі]мунн.*стандартна", re.I | re.S)
#: Class, comparator and IgG.  OCR drops the decimal point as often as not:
#: «<0 15» is <0.15.  The gap after the class is taken whole: what follows it
#: starts with a comparator or a digit, never with more space.
_AUTOIMMUNE_TAIL = re.compile(
    r"^(?:(?P<cls>[0-4])\s++)?(?P<comparator>[<«‹>])?\s*(?P<value>\d+(?:[.,]\d+|\s\d{2})?)$"
)


def _autoimmune_bands(
    lines: list[str], pattern: re.Pattern[str] = _AUTOIMMUNE_BAND
) -> dict[int, tuple[str, float | None, float | None]]:
    """The legend: class -> (printed band, low, high)."""
    bands: dict[int, tuple[str, float | None, float | None]] = {}
    for line in lines:
        for band in pattern.finditer(line):
            limits = re.findall(_DECIMAL, band.group("range"))
            numbers = [parse_decimal(item) for item in limits]
            printed = collapse_space(f"{band.group('range')} {band.group('label')}").replace("«", "<")
            if len(numbers) == 2:
                bands[int(band.group("cls"))] = (printed, numbers[0], numbers[1])
            elif re.match(r"[<«‹]", band.group("range")):
                bands[int(band.group("cls"))] = (printed, None, numbers[0])
            else:
                bands[int(band.group("cls"))] = (printed, numbers[0], None)
    return bands


def _autoimmune_best_split(line: str) -> tuple[float, str, str, re.Match | None] | None:
    """(score, antigen, printed name, result match) for the best name/result split.

    Where the name ends is decided by the antigen list, not by the first
    number: «Ro/SS-A 52» and «SRP 54» carry digits of their own.  Every
    split is tried and the one whose name reads most like an antigen wins.
    """
    tokens = line.split()
    best: tuple[float, str, str, re.Match | None] | None = None
    for cut in range(len(tokens), 0, -1):
        name = " ".join(tokens[:cut]).strip(" .")
        tail = _AUTOIMMUNE_TAIL.match(" ".join(tokens[cut:])) if cut < len(tokens) else None
        if cut < len(tokens) and tail is None:
            continue
        found = _closest(name, AUTOIMMUNE_ANTIGENS, 0.6, with_score=True)
        if found and (best is None or found[0] > best[0]):
            best = (found[0], found[1], name, tail)
    return best


def _autoimmune_class(
    value: float, comparator: str | None, bands: dict[int, tuple[str, float | None, float | None]]
) -> int | None:
    """The class the legend gives a value whose class column did not survive OCR.

    Only when the value sits inside one band.
    """
    for number, (_, low, high) in sorted(bands.items()):
        if (low is None or value >= low) and (high is None or value < high or (comparator == "<" and value <= high)):
            return number
    return None


def _numeric_observation(
    name: str,
    raw_value: str,
    unit: str | None,
    reference: str | None,
    page_number: int,
    evidence: str,
    confidence: float = 0.99,
    observed_at: str | None = None,
) -> ParsedObservation | None:
    value = parse_decimal(raw_value)
    if value is None:
        return None
    low, high = reference_bounds(reference)
    # `parse_decimal` drops a leading «<»; the comparator has to be kept here
    # or «<1» is stored as the measured value 1 (EskuLab amino acids;
    # calprotectin «<24.0»).
    comparator = _COMPARATOR.match(raw_value.strip())
    return ParsedObservation(
        raw_name=name,
        value_numeric=value,
        value_text=None,
        comparator=comparator.group(0) if comparator else None,
        unit_raw=unit,
        reference_text=reference,
        reference_low=low,
        reference_high=high,
        page_number=page_number,
        evidence_text=evidence,
        confidence=confidence,
        observed_at=observed_at,
    )


def relative_density(printed: str) -> str:
    """Fold urine relative density onto the decimal scale everyone else uses.

    Urine sits between about 1.000 and 1.060 relative to water.  Laboratories
    with an integer column print that as 1000-1060, so "1005" and "1.005" are
    the same measurement written for two different forms.  Only the integer
    window is folded: 1.005 is already decimal, and a number outside both
    windows is left exactly as printed rather than guessed at.
    """
    value = parse_decimal(printed.strip())
    if value is None or not 1000 <= value <= 1100:
        return printed
    return f"{value / 1000:.3f}"


def parse_st_paraskeva(text: str, page_number: int) -> list[ParsedObservation]:
    """Parse the Ukrainian MOH 210/о, 225/о and 228/о forms used by St. Paraskeva.

    Every row is stored under the label the form prints («Еритроцити (RBC)»,
    «Гемоглобін(HGB)»), not an English name this parser used to substitute:
    the original-name line on a Ukrainian page read "Red blood cell count"
    where the paper says «Еритроцити (RBC):».  Translation is the display's
    job, and the concept catalogue resolves the printed label.
    """
    clean = collapse_space(text.replace("\u00ad", "-").replace("\u2011", "-"))
    if re.search(r"ФОРМА\s*№\s*210/о", clean, re.I):
        return _paraskeva_urinalysis(clean, page_number)
    if re.search(r"ФОРМА\s*№\s*225/о", clean, re.I):
        return _paraskeva_blood_count(clean, page_number)
    if re.search(r"ФОРМА\s*№\s*228/о", clean, re.I):
        return _paraskeva_rows(clean, _PARASKEVA_RHEUMATOLOGY, page_number)
    return []


def _paraskeva_label(match: re.Match) -> str:
    return collapse_space(match.group("label")).strip(" :")


#: Form 210/о, read as text: (pattern), each giving its label, value and norm.
_PARASKEVA_URINE_TEXT = (
    r"(?P<label>Білок)\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
    r"(?P<label>Глюкоза)\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
    r"(?P<label>Кетони)\s+(?P<v>.+?)\s+(?P<r>негативно)",
    r"(?P<label>Уробіліноген)\s+(?P<v>.+?)\s+(?P<r>негативно)",
    r"(?P<label>Білірубін)\s+(?P<v>.+?)\s+(?P<r>0[.,]5\s*mg/dl)",
    r"(?P<label>Нітрити)\s+(?P<v>.+?)\s+(?P<r>негативно)",
    r"(?P<label>Еритроцити\s*\(змінені\))\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
    r"(?P<label>Еритроцити\s*\(не змінені\))\s+(?P<v>.+?в п/з)\s+(?P<r>0\s*[-–]\s*1\s*в п/з)",
    r"(?P<label>Лейкоцити)\s+(?P<v>.+?в п/з)\s+(?P<r>1\s*[-–]\s*6\s*в п/з)",
    r"(?P<label>Слиз)\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
    r"(?P<label>Солі)\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
)
#: The relative density and the pH, read as numbers.
_PARASKEVA_URINE_NUMBERS = (
    # Relative density is printed two ways.  Most laboratories print
    # "1,025"; this MOH form prints the same quantity multiplied by a
    # thousand, "1005 1005-1030", because the column is integer-only.
    # Both spellings are accepted and folded to the decimal form by
    # relative_density() below -- stored as printed, one series read
    # "1.025 -> 1005 -> 1.035" and the reference library judged a
    # perfectly ordinary urine against an interval a thousand times
    # smaller than the number beside it.
    r"(?P<label>Питома густина)\s+(?P<v>\d+(?:[.,]\d+)?)\s+(?P<r>\d+(?:[.,]\d+)?\s*[-–]\s*\d+(?:[.,]\d+)?)",
    r"(?P<label>pH)\s+(?P<v>\d+(?:[.,]\d+)?)\s+(?P<r>\d+(?:[.,]\d+)?\s*[-–]\s*\d+(?:[.,]\d+)?)",
)
#: The epithelium and the casts are printed as sub-rows under a heading --
#: «Епітелій» over «плоский», «перехідний», «нирковий» -- and the row's label
#: is the two together.
_PARASKEVA_URINE_SUBROWS = (
    (
        "Епітелій",
        (
            r"(?P<label>плоский)\s+(?P<v>.+?в п/з)\s+(?P<r>поодинокий в п/з)",
            r"(?P<label>перехідний)\s+(?P<v>.+?в препараті)\s+(?P<r>поодинокий в препараті)",
            r"(?P<label>нирковий)\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
        ),
    ),
    (
        "Циліндри",
        (
            r"(?P<label>гіалінові)\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
            r"(?P<label>зернисті)\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
            r"(?P<label>епітеліальні)\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
            r"(?P<label>буропігментовані)\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
            r"(?P<label>восковидні)\s+(?P<v>.+?)\s+(?P<r>не виявлено)",
        ),
    ),
)


def _paraskeva_text_row(clean: str, pattern: str, page_number: int, heading: str = "") -> ParsedObservation | None:
    match = re.search(pattern, clean, re.I)
    if not match:
        return None
    label = collapse_space(f"{heading} {_paraskeva_label(match)}")
    return ParsedObservation(
        raw_name=label, value_numeric=None, value_text=collapse_space(match.group("v")),
        comparator=None, unit_raw=None, reference_text=collapse_space(match.group("r")),
        reference_low=None, reference_high=None, page_number=page_number,
        evidence_text=collapse_space(match.group(0)), confidence=0.99,
    )


def _split_range(text: str) -> list[str]:
    r"""``re.split(r"\s*[-–]\s*", text)``, without a pattern a split can enter
    at every space: the parts around each dash, the space beside it removed."""
    parts = re.split("[-–]", text)
    last = len(parts) - 1
    split: list[str] = []
    for index, part in enumerate(parts):
        if index:
            part = part.lstrip()
        if index < last:
            part = part.rstrip()
        split.append(part)
    return split


def _paraskeva_number_row(clean: str, pattern: str, page_number: int) -> ParsedObservation | None:
    match = re.search(pattern, clean, re.I)
    if not match:
        return None
    value, reference = match.group("v"), match.group("r")
    if _paraskeva_label(match) == "Питома густина":
        value = relative_density(value)
        reference = "-".join(relative_density(part) for part in _split_range(reference))
    return _numeric_observation(
        _paraskeva_label(match), value, None, reference, page_number, collapse_space(match.group(0))
    )


def _paraskeva_urinalysis(clean: str, page_number: int) -> list[ParsedObservation]:
    """Form 210/о, the urinalysis."""
    rows = [
        _paraskeva_text_row(clean, r"(?P<label>Колір)\s+(?P<v>.+?)\s+(?P<r>Солом'яно-жовтий)", page_number),
        _paraskeva_text_row(clean, r"(?P<label>Прозорість)\s+(?P<v>.+?)\s+(?P<r>Прозора)", page_number),
    ]
    rows += [_paraskeva_number_row(clean, pattern, page_number) for pattern in _PARASKEVA_URINE_NUMBERS]
    rows += [_paraskeva_text_row(clean, pattern, page_number) for pattern in _PARASKEVA_URINE_TEXT]
    rows += [
        _paraskeva_text_row(clean, pattern, page_number, heading)
        for heading, patterns in _PARASKEVA_URINE_SUBROWS
        for pattern in patterns
    ]
    return [row for row in rows if row]


#: The unit printed in the blood count's results.
_PER_LITRE_10_9 = "10^9/L"
#: Form 225/о, the blood count: (English name, pattern, unit).  The name is
#: documentation only; the row is stored under the label the form prints.
_PARASKEVA_BLOOD_COUNT = (
    ("Erythrocyte sedimentation rate", r"ШОЕ\s*\((?:ESR|SER)\).*?мм/год\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "мм/год"),
    ("Hemoglobin", r"Гемоглобін\s*\(HGB\)\s*:\s*г/л\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "г/л"),
    ("Hematocrit", r"Гематокрит\s*\([^)]*\)\s*:\s*%\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "%"),
    ("Red blood cell count", r"Еритроцити\s*\(RBC\)\s*:\s*10\*12\s*клітин/л\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "10^12/L"),
    ("Mean corpuscular volume", r"Середній об'єм еритроцита\s*\(MCV\)\s*:\s*фл\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "fL"),
    ("Mean corpuscular hemoglobin", r"Середній вміст HGB в еритроциті\s*\(MCH\)\s*:\s*пг\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "pg"),
    ("Mean corpuscular hemoglobin concentration", r"Середня концентрація HGB в\s+г/\s*л\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)\s+еритроциті\s*\(MCHC\)", "g/L"),
    ("Red cell distribution width, CV", r"Ширина розподілу еритроцитів\s*\(RDW\)\s*:\s*%\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "%"),
    ("Platelet count", r"Тромбоцити\s*\(PLT\)\s*:\s*10\*9\s*клітин/л\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", _PER_LITRE_10_9),
    ("Mean platelet volume", r"Середній об'єм тромбоцита\s*\(MPV\)\s*:\s*фл\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "fL"),
    ("White blood cell count", r"Лейкоцити\s*\(WBC\)\s*-\s*абс\.?\s*:\s*10\*9\s*клітин/л\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", _PER_LITRE_10_9),
    ("Granulocytes, absolute", r"Нейтрофіли\s*\(GRAN\)\s*-\s*абс\.?\s*:\s*10\*9\s*клітин/л\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", _PER_LITRE_10_9),
    ("Granulocytes", r"Нейтрофіли\s*\(GRAN\)\s*-\s*%\s*:\s*%\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "%"),
    ("Lymphocytes, absolute", r"Лімфоцити\s*\(LYM\)\s*-\s*абс\.?\s*:\s*10\*9\s*клітин/л\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", _PER_LITRE_10_9),
    ("Lymphocytes", r"Лімфоцити\s*\(LYM\)\s*-\s*%\s*:?[ ]*%\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "%"),
    ("Mixed white cells, absolute", r"Моноцити\s*\(MID\)\s*-\s*абс\.?\s*:\s*10\*9\s*клітин/л\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", _PER_LITRE_10_9),
    ("Mixed white cells", r"Моноцити\s*\(MID\)\s*-\s*%\s*:\s*%\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)", "%"),
)
#: Form 228/о: rheumatoid factor and C-reactive protein.
_PARASKEVA_RHEUMATOLOGY = (
    ("Rheumatoid factor", r"Ревматоїдний фактор\s+(\d+(?:[.,]\d+)?)\s+IU/ml\s+(<\s*\d+(?:[.,]\d+)?)", "IU/ml"),
    ("C-reactive protein", r"С-реактивний білок\s+(\d+(?:[.,]\d+)?)\s+mg/l\s+(<\s*\d+(?:[.,]\d+)?)", "mg/l"),
)
_PARASKEVA_DIFFERENTIAL = (
    "Базофіли", "Еозинофіли", "Паличкоядерні нейтрофіли", "Сегментоядерні нейтрофіли", "Лімфоцити", "Моноцити",
)


def _paraskeva_rows(clean: str, specs, page_number: int) -> list[ParsedObservation]:
    """One numeric row per spec that matches, stored under its printed label."""
    observations: list[ParsedObservation] = []
    for _name, pattern, unit in specs:
        match = re.search(pattern, clean, re.I)
        if match:
            item = _numeric_observation(
                _printed_label(match), match.group(1), unit, match.group(2), page_number,
                collapse_space(match.group(0)),
            )
            if item:
                observations.append(item)
    return observations


def _paraskeva_blood_count(clean: str, page_number: int) -> list[ParsedObservation]:
    """Form 225/о, and the leukocyte differential printed under it."""
    observations = _paraskeva_rows(clean, _PARASKEVA_BLOOD_COUNT, page_number)
    morphology = clean.split("Морфологія лейкоцитів", 1)
    if len(morphology) != 2:
        return observations
    section = morphology[1]
    for name in _PARASKEVA_DIFFERENTIAL:
        match = re.search(
            rf"{re.escape(name)}\s+%\s+(\d+(?:[.,]\d+)?)\s+([0-9.,]+\s*[-–]\s*[0-9.,]+)",
            section,
            re.I,
        )
        if match:
            item = _numeric_observation(
                name, match.group(1), "%", match.group(2), page_number,
                collapse_space(match.group(0)),
            )
            if item:
                observations.append(item)
    return observations


#: The unit column a form row prints after its label.
_FORM_UNIT = re.compile(r"(?:мм/год|г/\s*л|%|10\*\d+\s*клітин/л|фл|пг|IU/ml|mg/l)$", re.I)


def _without_unit_column(prefix: str) -> str:
    r"""``prefix`` less a trailing «: <unit>», spaces included.

    Read from the right -- space, the unit, space, the colon, space -- which
    removes exactly what ``re.sub(r"\s*:?\s*(?:<unit>)?\s*$", "", prefix)``
    did, without a pattern a substitution would start at every space.
    """
    prefix = prefix.rstrip()
    unit = _FORM_UNIT.search(prefix)
    if unit:
        prefix = prefix[: unit.start()].rstrip()
    return prefix.removesuffix(":").rstrip()


def _printed_label(match: re.Match) -> str:
    """The label a form row prints, read off the row a spec matched.

    Everything before the value, less the unit column and the colon.  MCHC
    wraps its label around the value («Середня концентрація HGB в г/ л 339,0
    310 - 380 еритроциті(MCHC)»), so its tail is taken from after it.
    """
    whole = match.group(0)
    prefix = _without_unit_column(whole[: match.start(1) - match.start(0)])
    tail = re.search(r"\s(еритроциті\s*\(MCHC\))$", whole, re.I)
    label = f"{prefix} {tail.group(1)}" if tail else prefix
    return collapse_space(label).strip(" :")


GARMIN_MONTHS = {
    "січ.": 1, "лют.": 2, "бер.": 3, "квіт.": 4, "трав.": 5, "черв.": 6,
    "лип.": 7, "серп.": 8, "вер.": 9, "жовт.": 10, "лист.": 11, "груд.": 12,
}


#: EskuLab prints its results as a table, and flattening a table to text throws
#: away the one thing that says which column a word was in.  The specimen is
#: indented under the analyte name, so «Приносний матеріал, сеча» arrives
#: looking exactly like a continuation of that name; the reference cell wraps
#: over the lines below its own row, so «діти: 3.33 - 5.55» arrives looking
#: exactly like a result.  Both mistakes have reached this record -- the second
#: as six analytes named after the age group whose threshold they carried, the
#: first as thirteen urinalysis rows whose name ended "Приносний матеріал,".
#: Reading the x position settles both, and needs no heuristic at all.
#:
#: The boundaries sit in the whitespace between the printed columns, measured
#: off the header row that every EskuLab report places identically --
#: Показник@28.3 Результат@231.0 Одиниці@316.3 Референтні@416.6 -- and checked
#: against the widest content on either side of each boundary across all six
#: reports in this record.  They are not the header positions: values are
#: centred in their column («солом`яний» starts at 229.3) and the reference
#: block starts well left of its own heading (378.4 against 416.6).
ESKULAB_PANEL_COLUMNS = (218.0, 295.0, 375.0)

#: The coprogram prints a narrower table, and gives its first column no heading
#: at all: Результат@200.4, Референтні@402.0.
ESKULAB_STOOL_COLUMNS = (170.0, 300.0)

#: How far right of the left margin a word can start and still be part of the
#: analyte name.  Names begin at 28.3; the specimen printed under them is
#: indented to 117 or 181 depending on how the line wrapped, which is the only
#: thing distinguishing «сечі» -- the tail of "К-сть клітин схожих на атипові в
#: мкл сечі" -- from «сеча», the specimen, one letter away from it.
ESKULAB_NAME_INDENT = 40.0

#: The collection time, printed under every row of a urinalysis.  Its own
#: right-hand column carries the continuation of the reference block above it,
#: so the row is skipped without ending the analyte it sits under.
ESKULAB_ROW_NOISE = re.compile(r"^Час відбору", re.I)

#: What separates one panel from the next, and the table from the page.  A
#: report of several panels prints all of this *between* them, mid-page: its
#: own header row, its own signature block, then the next panel's heading.
#: Order N2 puts three panels on page 2 alone, so treating any of it as
#: the end of the table lost every panel below the first -- eleven of them
#: across twelve pages.  None of it belongs to an analyte either, which is how
#: «Сторінка 1 з 3» reached a reference interval, so a row matching this ends
#: whatever row is open and starts nothing.
ESKULAB_END = re.compile(
    r"^(?:Примітки|Дослідження виконала|Завідувач|Пункт забору|ЕЛаб|"
    r"\*?Сфера акредитації|Діагноз не може|досліджень проводиться|відповідальності|"
    r"Ф(?:ОР)?_\d|Зам\s?овлення|Пацієнт:|Результати дослідження|Показник|Л:\d|"
    r"Здоров|Даний результат|При собі|Вид дослідження|Метод дослідження|Прилад|"
    r"Клінічно значуща|Досліджуваний|Визначення чутливості)",
    re.I,
)

#: The page number, printed by itself at the foot of the reference column.
ESKULAB_PAGE_FOOTER = re.compile(r"^Сторінка\s+\d+\s+з\s+\d+$", re.I)

#: The specimen, printed under the analyte name.  It is normally indented, but
#: when it wraps the tail returns to the left margin, where it is
#: indistinguishable by position from a name that wrapped.  A closed vocabulary
#: rather than a pattern, because «сечі» -- the tail of "К-сть клітин схожих на
#: атипові в мкл сечі" -- differs from «сеча», the specimen, by one letter.
#: «кал»: a stool test wraps «Приносний» / «матеріал, кал», and without it the
#: tail was read as more of the name («Панкреатична еластаза (кал) матеріал,
#: кал»).
ESKULAB_SPECIMEN_WORDS = frozenset(
    """приносний матеріал сеча сироватка сироватці крові кров цільна
       плазма зак виділення кал""".split()
)


def _eskulab_specimen(fragment: str) -> bool:
    """True when a left-margin fragment is the wrapped tail of the specimen."""
    words = [word.strip(" ,.").casefold() for word in fragment.split()]
    return bool(words) and all(word in ESKULAB_SPECIMEN_WORDS for word in words)

#: A panel heading -- "5. F0502 Пакет №3. Ниркові проби".  Always a digit, a
#: full stop, then a letter-and-four-digits catalogue code, which no analyte
#: name has.  Distinguishing this from "1. С-пептид 2.41 нг/мл" is the whole
#: reason the numbering cannot simply be stripped.
ESKULAB_SECTION = re.compile(r"^\d+\.\s+[A-ZА-ЯІЇЄҐ]\d{4}\b")

#: The phrase a dipstick legend uses for its negative band.  The result column
#: prints "-" and the legend defines what that means: «не виявлена (-) 250 = ++
#: …» maps (-) to "not detected", so the row is a negative finding rather than
#: an empty one.  Only the leading phrase is taken; the rest of the legend is
#: the colour scale.
ESKULAB_NEGATIVE = re.compile(r"^(не виявлен\w+|в нормі|негативн\w+)", re.I)


def eskulab_table_page(words: list) -> bool:
    """True when the page draws one of the tables the column parser reads.

    Checked before parsing rather than after, so that a page which draws a
    table and yields no rows is reported as it is instead of being handed to
    the parsers that read the page as flat text.
    """
    text = " ".join(word[3] for word in words)
    return bool(
        re.search(r"Показник\s+Результат|Мікроорганізм|Копрограма", text)
        or re.search(r"Результат\s+Референтні", text)
    )


#: How wide a gap inside one cell means the report drew two columns there.
#: The reference column's second column starts around x=470 against a first at
#: x=378, and no single phrase leaves this much space between two words.
ESKULAB_CELL_GAP = 18.0

#: How close to the measured sub-column x a word must start to be counted as
#: beginning it.  Every genuine start on a page sits at one x to a tenth of a
#: point; the near misses are ordinary words that happen to land there, and at
#: 0.5 the two populations do not overlap in any report in this record.
ESKULAB_COLUMN_TOLERANCE = 0.5

#: How many lines must agree before a measured x is trusted as the sub-column.
#: Two lines that both happen to break at the same place is a coincidence; a
#: printed column repeats down the whole block.
ESKULAB_COLUMN_VOTES = 3


def _eskulab_reference_split(words: list, edge: float) -> tuple[float, float] | None:
    """Where the reference cell's two printed sub-columns begin on this page.

    Splitting each line on its own wide gap works only while the left
    sub-column's text stops well short of the right one.  It does not: «Діти до
    5 днів: <185.0 Діти 6-12 років: <17.0» leaves eight points between the two
    columns, under any threshold that does not also split ordinary phrases, so
    the two intervals arrive interleaved.  That is how a 34-year-old man's γ-GT
    came to be stored against a block whose every separable band belonged to a
    child, and was then shown to him as "not applicable to this age or sex" --
    the report prints «Чоловіки: 8.0-61.0» directly above it.

    The columns themselves are straight, so the lines that do split measure them
    for the lines that do not.  Both edges are returned, because the right one
    alone is not enough to recognise the layout: a reference short enough to be
    printed as a single centred line can end at the same x the right sub-column
    begins at, and reading «Чоловік: 0,04-0,54 / Жінки: 0,04-0,36» that way gave
    the men's eosinophil count the women's lower limit.  A line only obeys the
    split when it starts at one edge or the other.

    Returns ``None`` when too few lines agree, leaving the gap rule to act alone
    on a report that prints one sub-column.
    """
    lines: dict[float, list[tuple[float, float]]] = {}
    for x0, x1, top, _text in words:
        if x0 < edge:
            continue
        key = next((seen for seen in lines if abs(seen - top) <= 2.0), top)
        lines.setdefault(key, []).append((x0, x1))

    def vote(tally: dict[float, int], x0: float) -> None:
        key = next((seen for seen in tally if abs(seen - x0) <= ESKULAB_COLUMN_TOLERANCE), x0)
        tally[key] = tally.get(key, 0) + 1

    splits: dict[float, int] = {}
    lefts: dict[float, int] = {}
    starts: dict[float, int] = {}
    for top in sorted(lines):
        row = sorted(lines[top])
        vote(lefts, row[0][0])
        previous: float | None = None
        for x0, x1 in row:
            if previous is not None and x0 - previous >= ESKULAB_CELL_GAP:
                vote(splits, x0)
            vote(starts, x0)
            previous = x1
    if not splits or not lefts:
        return None

    # A wide gap proves a column starts there; the lines that agree with it
    # need not have one.  A left-column label that runs almost to the right
    # one leaves two points («Новонароджені (1 день):» / «Дорослі: 4.11 -
    # 5.89») -- an ordinary space -- yet its right-hand word starts on the
    # same x to a tenth of a point.  Counting only wide gaps found two such
    # lines per block, one short of a column, and the newborn label took the
    # adults' interval.
    def support(x: float) -> int:
        return sum(count for start, count in starts.items() if abs(start - x) <= ESKULAB_COLUMN_TOLERANCE)

    split = max(splits, key=lambda x: (support(x), splits[x], -x))
    left, _ = max(lefts.items(), key=lambda item: (item[1], item[0]))
    if support(split) < ESKULAB_COLUMN_VOTES or left >= split - ESKULAB_CELL_GAP:
        return None
    return left, split


#: A digit run meeting a letter run, or a word meeting a comparator, with no
#: space between them.  Both are shapes a laboratory writes on purpose --
#: «<10мм/год», «2тиж.» -- so this pattern alone proves nothing; it is only
#: consulted for a word that also straddles the measured sub-column boundary,
#: at the character the boundary falls on.
#: The third shape is one number's last digit meeting the next number's first:
#: serum iron prints «Діти (Ж) 13-15 років: 5.4» hard against «Діти (Ч) 13-15
#: років: 4.7-19.7» and the extractor returns «5.44.7-19.7».  Left glued, the
#: girls' band reads as the nonsense 5.44.7 and the boys' band loses its
#: interval entirely -- the label is stored with nothing after it.  Written
#: narrowly on purpose: a decimal that has *finished* meeting a decimal that is
#: *starting*, which is what a column boundary looks like and what «13.0-19.0»
#: crossing the same x innocently does not.
#: What starts across the boundary is as often an age as a value, and an age
#: band is written in whole numbers: «Жінки 12-17 років: <24.01-3 років: <33.0»
#: is «<24.0» meeting «1-3 років», «<25.06-12 років» is «<25.0» meeting «6-12».
#: Requiring the *following* number to carry a decimal missed both, and with
#: them ALT's 1-3-years band and AST's 6-12-years band -- unreachable, which is
#: what let the newborn band win for a child of either age.  A whole-number
#: range is admitted only when it is a whole-number range all the way through:
#: the trailing guard is what keeps «2,59-3,34» one interval rather than «2,5»
#: meeting «9-3,34», and «5.83-34.5» from becoming «5.8» and «3-34.5».
#: The fourth is a number meeting an age band written with an exclusive upper
#: age, «1-<12 р.»: oestradiol's «Період овуляції: 32.1-517» runs into the next
#: column's «1-<12 р.: <15.0» and comes back as «32.1-5171-<12», the ovulation
#: band ending at 5171 and the children's band losing its label.
ESKULAB_GLUE = re.compile(
    r"(?<=\d)(?=[^\W\d_])"
    r"|(?<=[^\W\d_])(?=[<>≤≥])"
    r"|(?<=[.,]\d)(?=\d+[.,]\d|\d{1,3}[-–—]\d{1,3}(?![\d.,]))"
    r"|(?<=\d)(?=\d{1,2}[-–—]<)"
)


def _unglue(text: str, x0: float, x1: float, split: float) -> list[str]:
    """Separate two words the extractor joined across the sub-column boundary.

    «діти від 0-10 днів: 1,9-2,6» ends hard against «дорослі 18-60 років:» in
    the next printed column, with no space, so `extract_words` returns the one
    token «1,9-2,6дорослі» -- and the adult label is carried off into the
    paediatric column, four bands away from the interval it governs.  Calcium
    was left with no interval that described this patient at all.

    Narrow on purpose.  Plenty of centred single-column references cross this x
    innocently (`13.0-19.0`, `Чоловіки/Жінки:`), so a split needs a break in the
    word's own character classes at the boundary's own position, to within one
    character.  Nothing else is touched.
    """
    if not (x0 < split < x1) or len(text) < 2:
        return [text]
    cut = round(len(text) * (split - x0) / (x1 - x0))
    candidates = [
        match.start()
        for match in ESKULAB_GLUE.finditer(text)
        if 0 < match.start() < len(text) and abs(match.start() - cut) <= 1
    ]
    if not candidates:
        return [text]
    at = min(candidates, key=lambda start: abs(start - cut))
    return [text[:at], text[at:]]


def _eskulab_rows(
    words: list, boundaries: tuple[float, ...]
) -> list[tuple[list[str], list[str], float]]:
    """Group words into the rows and columns the report actually printed.

    A row counts as a table row only when no word crosses a column boundary.
    Prose does cross -- the page furniture, the panel headings, and the
    free-form blocks EskuLab uses for quantitative PCR all run straight through
    the gaps between columns -- so this one test is also what separates the
    table from everything else on the page.
    """
    lines: dict[float, list[tuple[float, float, float, str]]] = {}
    for x0, x1, top, text in words:
        key = next((seen for seen in lines if abs(seen - top) <= 2.0), top)
        lines.setdefault(key, []).append((x0, x1, top, text))
    measured = _eskulab_reference_split(words, boundaries[-1])
    rows: list[tuple[list[str], list[str], float]] = []
    for top in sorted(lines):
        row = sorted(lines[top])
        if any(x0 < edge < x1 for x0, x1, _, _ in row for edge in boundaries):
            continue
        # «Сторінка 1 з 3» on a line of its own sits inside the reference
        # column, below the page's last row, and was stored as the end of
        # that row's interval («жінки < 100.0 чоловіки < 26.4 Сторінка 1 з 3»).
        if ESKULAB_PAGE_FOOTER.match(" ".join(text for _, _, _, text in row)):
            continue
        rows.append(_eskulab_row(row, boundaries, measured))
    return rows


def _eskulab_row(
    row: list[tuple[float, float, float, str]],
    boundaries: tuple[float, ...],
    measured: tuple[float, float] | None,
) -> tuple[list[str], list[str], float]:
    """(cells, reference sub-columns, indent) of one printed table line."""
    last = len(boundaries)
    columns: list[list[str]] = [[] for _ in range(last + 1)]
    reference = [(x0, x1, text) for x0, x1, _, text in row if x0 >= boundaries[-1]]
    for x0, _x1, _top, text in row:
        index = sum(1 for edge in boundaries if x0 >= edge)
        if index < last:
            columns[index].append(text)
    # The reference cell is often two printed columns of its own, and
    # flattening them in reading order interleaves both: «оптимальний
    # рівень: < 2,59» beside «Високий пороговий рівень: 4,14-4,89» comes
    # back as "оптимальний Високий пороговий рівень: < 2,59 рівень:
    # 4,14-4,89".  A line laid out on the two measured edges is split there;
    # anything else -- a short reference centred in its cell, a page with no
    # measurable second column -- falls back to the wide-gap rule, which
    # leaves a genuine single column untouched.
    aligned = bool(reference) and measured is not None and any(
        abs(reference[0][0] - anchor) <= ESKULAB_COLUMN_TOLERANCE for anchor in measured
    )
    segments = _eskulab_measured_cells(reference, measured[1]) if aligned else _eskulab_gap_cells(reference)
    columns[last] = [word for segment in segments for word in segment]
    cells = [collapse_space(" ".join(column)) for column in columns]
    # Empty sub-columns are kept: `parse_eskulab` reads a block by position,
    # and a line printed only in the right column has to stay in the right
    # column or its band lands under the wrong heading.
    return cells, [collapse_space(" ".join(s)) for s in segments], row[0][0]


def _eskulab_measured_cells(reference: list[tuple[float, float, str]], split: float) -> list[list[str]]:
    """The reference words of a line laid out on the measured sub-columns."""
    left_cell: list[str] = []
    right_cell: list[str] = []
    for x0, x1, text in reference:
        for piece_index, piece in enumerate(_unglue(text, x0, x1, split)):
            # Once a line crosses into the right sub-column it stays
            # there; the second half of a glued word is already across.
            if piece_index or abs(x0 - split) <= ESKULAB_COLUMN_TOLERANCE or right_cell:
                right_cell.append(piece)
            else:
                left_cell.append(piece)
    return [left_cell, right_cell]


def _eskulab_gap_cells(reference: list[tuple[float, float, str]]) -> list[list[str]]:
    """The reference words of a line, split wherever a wide gap separates them."""
    segments: list[list[str]] = [[]]
    previous_x1: float | None = None
    for x0, x1, text in reference:
        if previous_x1 is not None and x0 - previous_x1 >= ESKULAB_CELL_GAP:
            segments.append([])
        segments[-1].append(text)
        previous_x1 = x1
    return segments


def _eskulab_result(
    name: str, result: str, unit: str | None, band: str | None, page_number: int, evidence: str
) -> ParsedObservation:
    """A row with something in its result column: a number, or a categorical finding."""
    observation = _numeric_observation(
        name=name,
        raw_value=result,
        unit=None if unit == "-" else unit,
        reference=band,
        page_number=page_number,
        evidence=evidence,
    )
    if observation is not None:
        return observation
    # A result column that is not a number is a categorical finding:
    # «солом`яний» for urine colour, «А (II)» for blood group.
    return ParsedObservation(
        raw_name=name,
        value_numeric=None,
        value_text=collapse_space(result),
        comparator=None,
        unit_raw=None if unit == "-" else unit,
        reference_text=band,
        reference_low=None,
        reference_high=None,
        page_number=page_number,
        evidence_text=evidence,
        confidence=0.96,
    )


def _eskulab_observation(
    name: str, result: str, unit: str, reference: list[str], page_number: int
) -> ParsedObservation | None:
    """One finished table row, numeric or categorical."""
    name = collapse_space(name).strip(" .,:;")
    # The analyte's position in the panel, printed ahead of its name: "1.
    # С-пептид", "2. Холестерин не-ЛПВЩ".  It is not part of the name, and the
    # leading digit made the shared name check reject the row outright.  Only
    # the numbering goes -- «25-Гідроксивітамін D» leads with its position on
    # the molecule and keeps it, which is why this cannot simply strip digits.
    # Both at once is «2. 25-Гідроксивітамін D»: requiring a letter straight
    # after the numbering left it on, and the row was rejected.
    name = re.sub(r"^\d+\.\s+(?=[^\W\d_]|\d+-[^\W\d_])", "", name)
    if not valid_analyte_name(name) and not re.match(r"^\d+-[^\W\d_]", name):
        return None
    # The whole printed block is kept, every band of it.  Reducing it here to
    # the one line beginning «Дорослі» threw away the rest of what the
    # laboratory published -- including, on eleven analytes in order N2,
    # the only band that described this patient, because the adult row is
    # headed «Чоловіки» or «Дорослі (ч)» and not «Дорослі» at all.  Choosing
    # among the bands is `health.applicable_band`'s job: it knows the reader's
    # age and sex, which the parser does not, and it is the same choice the
    # display and the verdict both have to make.
    band = collapse_space(" ".join(part for part in reference if part)) or None
    joined = band or ""
    unit = unit.strip() or None
    evidence = collapse_space(f"{name} {result} {unit or ''} {joined}")
    if result and result != "-":
        return _eskulab_result(name, result, unit, band, page_number, evidence)
    # An empty result column with a unit and a legend under it is a dipstick
    # pad that read negative -- the legend itself defines "-" as «не виявлена».
    # An empty result with no unit and no legend is a section heading
    # («Фізико-хімічні властивості»), which is not a finding at all.
    negative = ESKULAB_NEGATIVE.match(joined) if (unit and joined) else None
    # A dash in every column -- «Каламутність(рівень) (C-CLOUD) - - -» -- is
    # the analyser's reading against a reference that is itself a dash: no
    # turbidity, as printed.  A heading prints no unit and no reference.
    printed_dash = unit is not None and joined == "-"
    if negative is None and not printed_dash:
        return None
    return ParsedObservation(
        raw_name=name,
        value_numeric=None,
        value_text=negative.group(1) if negative else "-",
        comparator=None,
        unit_raw=None if unit == "-" else unit,
        reference_text=band,
        reference_low=None,
        reference_high=None,
        page_number=page_number,
        evidence_text=evidence,
        confidence=0.94,
    )


#: The column headings a results table prints over its first two columns.
_INDICATOR_HEADING = "Показник"
_RESULT_HEADING = "Результат"


def _eskulab_header(rows: list[tuple[list[str], list[str], float]]) -> int | None:
    """The index of the «Показник | Результат» header row, or None."""
    return next(
        (
            index
            for index, (cells, _, _) in enumerate(rows)
            if cells[0].startswith(_INDICATOR_HEADING) and cells[1].startswith(_RESULT_HEADING)
        ),
        None,
    )


def _eskulab_material(text: str) -> str | None:
    """The specimen a «цільна кров ЗАК» / «Приносний матеріал, сеча» line names."""
    material = collapse_space(text)
    phrase = SPECIMEN_PHRASE.search(material) or re.search(
        r"сироватка\s+крові|цільна\s+кров|плазма|сироватка|сеча|кал", material, re.I
    )
    return phrase.group(0) if phrase else None


class _EskulabPanel:
    """The analyte row being read off an EskuLab panel, until the next one starts."""

    def __init__(self, page_number: int) -> None:
        self.page_number = page_number
        self.observations: list[ParsedObservation] = []
        self.name = self.result = self.unit = ""
        # One list per printed sub-column of the reference cell, read top to
        # bottom and then left to right, which is the order the block was
        # written in.
        self.reference: list[list[str]] = []
        # The specimen printed under the name («цільна кров ЗАК», «Приносний
        # матеріал, сеча»): not part of the name, but the row's material.
        self.specimen: list[str] = []

    def collect(self, parts: list[str]) -> None:
        for index, part in enumerate(parts):
            while len(self.reference) <= index:
                self.reference.append([])
            self.reference[index].append(part)

    def flush(self) -> None:
        if self.name:
            found = _eskulab_observation(
                self.name, self.result, self.unit,
                [p for column in self.reference for p in column], self.page_number,
            )
            if found is not None:
                self.observations.append(replace(found, specimen=_eskulab_material(" ".join(self.specimen))))
        self.name = self.result = self.unit = ""
        self.reference = []
        self.specimen = []

    def read(self, cells: list[str], segments: list[str], indent: float) -> None:
        first, _value, _measure, band = cells
        if ESKULAB_END.match(first) or ESKULAB_SECTION.match(first):
            self.flush()
            return
        if ESKULAB_ROW_NOISE.match(first):
            if band and self.name:
                self.collect(segments)
            return
        self._read_table_line(cells, segments, indent < ESKULAB_NAME_INDENT)

    def _read_table_line(self, cells: list[str], segments: list[str], left_margin: bool) -> None:
        first, value, measure, band = cells
        # At the left margin a specimen word is the specimen's wrapped tail
        # only once the indented specimen has begun («сироватка» / «крові»).
        # Before that it ends the name: «Концентрація Ig А в сироватці» /
        # «крові», with «сироватка крові» indented under it.
        specimen = _eskulab_specimen(first) and (not left_margin or bool(self.specimen))
        if first and not value and self.name and specimen:
            self.specimen.append(first)
        # A second table, printed inside the rows the reference column wraps
        # over.  Order N2 puts the Панченков/Вестергрен conversion under
        # the ESR result: its heading crosses the column boundaries and is
        # dropped, but its body is two clean columns and was read as more of the
        # ESR reference -- «Чоловіки 17-50р: <15мм/год ... 1-20 20-40 40-70
        # 50-90 60-100 70-110», a sex-specific limit trailed by seven intervals
        # belonging to a different method.  Indented, named and valueless is
        # what an analyte's own continuation lines are never: those are either
        # at the left margin or the specimen.
        if not left_margin and first and not value and not specimen:
            self.flush()
            return
        if left_margin and first and value:
            self.flush()
            self.name, self.result, self.unit = first, value, measure
            self.reference = []
            self.collect(segments)
            return
        if left_margin and not value and any(char.isalpha() for char in first) and not specimen:
            self._continue_name(first)
        if band:
            self.collect(segments)

    def _continue_name(self, first: str) -> None:
        # A name too long for its column, continued on the next line:
        # "Скупчення лейкоцитів (WBC" / "Clumps)".  A name broken *at* a
        # hyphen rejoins without one — «Ширина розподілу еритроцитів
        # (RDW-» / «SD)» is (RDW-SD), and the abbreviation is the only
        # thing separating a 36.1 fL spread from a 12.0 % one.
        if not self.name:
            self.name = first
        elif self.name.endswith("-"):
            self.name += first
        else:
            self.name = f"{self.name} {first}"


def parse_eskulab(words: list, page_number: int) -> list[ParsedObservation]:
    """Read the EskuLab results table off the page's word positions.

    Returns nothing for a page that does not print the four-column header --
    the microbiology and quantitative-PCR reports use other layouts, and the
    shared passes already read those.
    """
    rows = _eskulab_rows(words, ESKULAB_PANEL_COLUMNS)
    header = _eskulab_header(rows)
    if header is None:
        return []
    panel = _EskulabPanel(page_number)
    for cells, segments, indent in rows[header + 1 :]:
        panel.read(cells, segments, indent)
    panel.flush()
    return panel.observations + _eskulab_notes(words, page_number)


#: The free-text notes row a blood count or urinalysis closes with:
#: «Примітки (зак) Токсигенна зернистість окремих нейтрофілів.»  It usually
#: prints «-»; when it prints anything else that is a finding of the smear.
_ESKULAB_NOTES = re.compile(r"^Примітки\b", re.I)


def _eskulab_notes(words: list, page_number: int) -> list[ParsedObservation]:
    """Each notes row that says something, as a text result.

    The note runs straight across the result, unit and reference columns, so
    `_eskulab_rows` drops the line as prose, and `ESKULAB_END` ends the panel
    on its label: the one morphology finding of a blood count was stored
    nowhere.  Words right of the name column on the label's line, and on the
    lines that continue it there, are the note.
    """
    lines = _word_lines(words)
    observations: list[ParsedObservation] = []
    for index, line in enumerate(lines):
        if line[0][0] >= ESKULAB_NAME_INDENT or not _ESKULAB_NOTES.match(line[0][3]):
            continue
        label = collapse_space(" ".join(word[3] for word in line if word[0] < ESKULAB_PANEL_COLUMNS[0]))
        note = [word[3] for word in line if word[0] >= ESKULAB_PANEL_COLUMNS[0]]
        specimen = None
        for following in lines[index + 1 : index + 4]:
            if following[0][0] >= ESKULAB_PANEL_COLUMNS[0]:
                note.extend(word[3] for word in following)
                continue
            text = " ".join(word[3] for word in following)
            if _eskulab_specimen(text):
                specimen = _eskulab_material(text)
            break
        value = collapse_space(" ".join(note))
        if not value or value == "-":
            continue
        observations.append(
            ParsedObservation(
                raw_name=label, value_numeric=None, value_text=value, comparator=None,
                unit_raw=None, reference_text=None, reference_low=None, reference_high=None,
                page_number=page_number, evidence_text=f"{label} {value}", confidence=0.94,
                specimen=specimen,
            )
        )
    return observations


def eskulab_leading_reference(words: list) -> str | None:
    """Reference lines at the top of a page, before its first result row.

    They are the end of the previous page's last block: ESR's «Чоловіки
    старші 50р: <20мм/год», «Жінки 17-50р: …» printed over the page break,
    where the page they belong to cannot see them.  `parse_document` hands
    them back to that row when it reads the pages together.
    """
    rows = _eskulab_rows(words, ESKULAB_PANEL_COLUMNS)
    header = _eskulab_header(rows)
    if header is None:
        return None
    parts: list[str] = []
    for cells, _segments, _indent in rows[header + 1 :]:
        first, value, _measure, band = cells
        if value or (first and not _eskulab_specimen(first)) or ESKULAB_END.match(first):
            break
        if band:
            parts.append(band)
    return collapse_space(" ".join(parts)) or None


#: Quantities a coprogram reports, as opposed to the sub-headings it reports
#: them under.  «М'язові волокна» is followed by «змінені» and «не змінені»,
#: each with its own quantity underneath, and both sit in the same column.
ESKULAB_STOOL_QUANTITY = re.compile(
    r"^(?:не виявлено|поодиноко|невелика к-сть|значна к-сть|помірна к-сть|"
    r"незначна к-сть|велика к-сть|\d+[.,]?\d*|.*в п/з)",
    re.I,
)


def _eskulab_stool_header(rows: list[tuple[list[str], list[str], float]], page_text: str) -> int | None:
    """Where the coprogram's rows start: after its header row, from the top of
    a page that continues it (-1), or None for a page that is no coprogram."""
    header = next(
        (
            index
            for index, (cells, _, _) in enumerate(rows)
            if cells[1].startswith(_RESULT_HEADING) and cells[2].startswith("Референтні")
        ),
        None,
    )
    if header is not None:
        return header if "Копрограма" in page_text else None
    if "Мікроорганізм" in page_text or _INDICATOR_HEADING in page_text:
        # The page announces a table of its own, so it is not the tail of this
        # one.  Without this the culture report was read as a coprogram: two
        # organisms relabelled «(кал)» and «Амоксицилін-клавуланова» -- half an
        # antibiotic name -- published with «кислота» as its result.
        return None
    # A coprogram that runs past one page prints no heading on the second
    # and no header row either: «Найпростіші | не виявлено | не виявлено»
    # simply continues the table.  Three results -- protozoa, helminth eggs
    # and yeast-like fungal elements -- were left unread because of it.
    # The column geometry is identical, so a page whose rows fill the same
    # three cells at the same three positions is the rest of the table.
    continuation = sum(
        1
        for cells, _, indent in rows
        if indent < ESKULAB_NAME_INDENT and all(cells) and not ESKULAB_END.match(cells[0])
    )
    return -1 if continuation >= 2 else None


class _EskulabStool:
    """The coprogram row being read: a flat row, or a nested parent's sub-rows."""

    def __init__(self, page_number: int) -> None:
        self.page_number = page_number
        self.observations: list[ParsedObservation] = []
        self.name = self.value = self.band = ""
        self.parent = self.parent_band = self.subheading = ""

    def flush(self) -> None:
        if self.name and self.value:
            found = _eskulab_observation(
                f"{self.name} (кал)", self.value, "", [self.band], self.page_number
            )
            if found is not None:
                self.observations.append(found)
        self.name = self.value = self.band = ""

    def read_name(self, first: str, result: str, reference: str) -> None:
        """A line that starts at the left margin."""
        if result:
            self.flush()
            self.name, self.value, self.band = first, result, reference
            self.parent, self.subheading = "", ""
        elif reference:
            # A parent with no result of its own: the sub-headings under it
            # carry the results, and its reference covers all of them.
            self.flush()
            self.parent, self.parent_band, self.subheading = first, reference, ""
        elif self.parent and not self.name:
            self.parent = f"{self.parent} {first}".strip()
        else:
            self.name = f"{self.name} {first}".strip() if self.name else first

    def read_result(self, result: str, reference: str) -> None:
        """A line with nothing at the left margin."""
        if not result:
            if reference and self.name:
                self.band = f"{self.band} {reference}".strip()
            return
        if not self.parent:
            # A flat row with a second answer under its first: «Запах» ticks
            # «специфічний» and, on the line below, «каловий».  Both are the
            # result; keeping only the first published a stool odour the
            # laboratory had qualified.
            if self.name and self.value:
                self.value = f"{self.value}, {result}"
                if reference:
                    self.band = f"{self.band} {reference}".strip()
            return
        # Inside a nested block the result column alternates sub-heading and
        # quantity.  Naming the quantities is what tells the two apart --
        # counting alone mis-pairs the moment a sub-heading wraps.
        if not ESKULAB_STOOL_QUANTITY.match(result):
            self.subheading = result
            return
        found = _eskulab_observation(
            f"{self.parent} {self.subheading}".strip() + " (кал)",
            result, "", [self.parent_band], self.page_number,
        )
        if found is not None:
            self.observations.append(found)
        self.subheading = ""


def parse_eskulab_stool(words: list, page_number: int) -> list[ParsedObservation]:
    """Read the coprogram, whose table gives its first column no heading.

    Most rows are flat -- «Слиз | не виявлено | не виявлено» -- and their names
    wrap over the lines below («Залишки» / «неперетравленої» / «їжі»).  Four
    are nested: a parent that reports no result of its own, then alternating
    sub-heading and quantity lines sharing one column.  A wrapped name and a
    nested parent look alike from the left margin; what separates them is that
    the parent states a reference and a wrapped fragment states nothing.

    Every name is qualified with the specimen, because on this table they are
    not qualified at all: «Колір», «Лейкоцити», «Еритроцити» and «Слиз» are
    printed bare and resolve straight onto the urine concepts of the same name.
    A stool colour of «коричневий» filed as a urine colour is brown urine, and
    stool leukocytes would join the urinary series and be judged against it.
    """
    # The panel heading names its own material -- "F9014 Копрограма (матеріал:
    # Приносний матеріал, кал)" -- and it is prose, so it spans the columns and
    # never reaches `rows`.  Requiring it is also what keeps this parser off
    # any other two-column table EskuLab may print.
    page_text = " ".join(text for _, _, _, text in words)
    rows = _eskulab_rows(words, ESKULAB_STOOL_COLUMNS)
    header = _eskulab_stool_header(rows, page_text)
    if header is None:
        return []
    stool = _EskulabStool(page_number)
    for cells, _segments, indent in rows[header + 1 :]:
        first, result, reference = cells
        if ESKULAB_END.match(first) or ESKULAB_SECTION.match(first):
            break
        if first and indent < ESKULAB_NAME_INDENT:
            stool.read_name(first, result, reference)
        else:
            stool.read_result(result, reference)
    stool.flush()
    return stool.observations


#: Garmin's categories, longest first: «Нормальний» is a substring of
#: «Високий нормальний», so a first-substring match filed every high-normal
#: reading as normal.
GARMIN_CATEGORIES = ("Високий нормальний", "Ступінь 2", "Ступінь 1", "Нормальний")


def _interleaves(text: str, first: str, second: str) -> str | None:
    """What is left of ``text`` once ``first`` and then ``second`` are taken out
    as interleaved subsequences, or None when they are not both in it.

    Garmin draws each category twice -- the badge in its column, wrapped, and a
    second unwrapped copy five points to the right and half a point lower --
    and a text layer sorted by x merges the two letter by letter:
    «ВиВсиоскоикйи й нормальний» is «Високий » and «Високий нормальний»
    shuffled together, and «нормал+ьванлиьйсакор» is the end of the second
    copy shuffled with the note «+вальсакор» printed under it.  Taking the
    copies out greedily, left to right, leaves the note in printed order.
    """
    rest: list[str] = []
    a = b = 0
    for char in text:
        if a < len(first) and char == first[a]:
            a += 1
        elif b < len(second) and char == second[b]:
            b += 1
        else:
            rest.append(char)
    if a < len(first) or b < len(second):
        return None
    return "".join(rest)


def garmin_category(cell: str, next_line: str = "") -> tuple[str | None, str]:
    """The category printed in a reading row, and whatever note follows it.

    ``cell`` is the row's text after «bpm»; ``next_line`` is the line under it,
    where the badge copy wraps («нормальний») when the category is two words.
    """
    for category in GARMIN_CATEGORIES:
        words = category.split()
        # The wrapped badge keeps only its first line on the reading row; the
        # unwrapped copy carries the whole category.  An unwrapped single copy
        # (a renderer that draws it once) is the last case tried.
        heads = [" ".join(words[:cut]) + (" " if cut < len(words) else "") for cut in range(len(words), 0, -1)]
        for head in heads:
            left = _interleaves(cell, head, category)
            if left is not None:
                return category, collapse_space(left)
        if cell.startswith(category):
            return category, collapse_space(cell[len(category) :])
        if len(words) > 1 and next_line == " ".join(words[1:]) and cell.startswith(words[0]):
            return category, collapse_space(cell[len(words[0]) :])
    return None, collapse_space(cell)


GARMIN_DATE = re.compile(
    r"(\d{1,2})\s+(січ\.|лют\.|бер\.|квіт\.|трав\.|черв\.|лип\.|серп\.|вер\.|жовт\.|лист\.|груд\.)\s+(\d{4})",
    re.I,
)
#: «08:15 128 Сис. / 82 Діас. 64 bpm Нормальний».  The category and the note
#: after it run to the end of the line, so nothing after them can make the
#: engine give them back; the blanks before them are taken whole for the same
#: reason.
GARMIN_READING = re.compile(
    r"^(\d{2}:\d{2})\s+(\d{2,3})\s+Сис\.\s*/\s*(\d{2,3})\s+Діас\.\s+(\d{2,3})\s+bpm(?:\s++(.*+))?$",
    re.I,
)
GARMIN_WEEK_VALUES = re.compile(r"^(\d{2,3})\s*-\s*(\d{2,3})\s+(\d{2,3})\s*-\s*(\d{2,3})\s+(\d+)$")
GARMIN_WEEK = re.compile(
    r"^(\d{1,2})\s+(січ\.|лют\.|бер\.|квіт\.|трав\.|черв\.|лип\.|серп\.|вер\.|жовт\.|лист\.|груд\.)\s*-\s*"
    r"(\d{1,2})\s+(січ\.|лют\.|бер\.|квіт\.|трав\.|черв\.|лип\.|серп\.|вер\.|жовт\.|лист\.|груд\.)\s+(\d{4})$",
    re.I,
)


def _garmin_lines(page: dict[str, object]) -> list[str]:
    return [collapse_space(line) for line in str(page.get("native_text") or "").splitlines() if collapse_space(line)]


def _garmin_reading_rows(
    reading: re.Match, line: str, following: str, observed_at: str, page_number: int
) -> list[ParsedObservation]:
    """The three numbers of one reading row, and its category when it prints one."""
    observations: list[ParsedObservation] = []
    category, note = garmin_category(reading.group(5) or "", following)
    # The evidence is the row as printed, with the doubled badge undone.
    evidence = collapse_space(
        f"{line[: reading.start(5)] if reading.group(5) else line} {category or ''} {note}"
    )
    for name, value, unit in (
        ("Systolic blood pressure", reading.group(2), "mmHg"),
        ("Diastolic blood pressure", reading.group(3), "mmHg"),
        ("Pulse rate", reading.group(4), "bpm"),
    ):
        item = _numeric_observation(name, value, unit, None, page_number, evidence, observed_at=observed_at)
        if item:
            observations.append(replace(item, note=note or None))
    if category:
        observations.append(
            ParsedObservation(
                raw_name="Blood pressure category", value_numeric=None,
                value_text=category, comparator=None, unit_raw=None,
                reference_text=None, reference_low=None, reference_high=None,
                page_number=page_number, evidence_text=evidence, confidence=0.99,
                observed_at=observed_at, note=note or None,
            )
        )
    return observations


def _garmin_readings(pages: list[dict[str, object]]) -> list[ParsedObservation]:
    """Individual readings, each under the last date heading printed above it."""
    observations: list[ParsedObservation] = []
    current_date: str | None = None
    for page in pages:
        page_number = int(page["page_number"])
        lines = _garmin_lines(page)
        for line_index, line in enumerate(lines):
            date_match = GARMIN_DATE.fullmatch(line)
            if date_match:
                current_date = f"{int(date_match.group(3)):04d}-{GARMIN_MONTHS[date_match.group(2).casefold()]:02d}-{int(date_match.group(1)):02d}"
                continue
            reading = GARMIN_READING.match(line)
            if not reading or not current_date:
                continue
            following = lines[line_index + 1] if line_index + 1 < len(lines) else ""
            observations.extend(
                _garmin_reading_rows(reading, line, following, f"{current_date}T{reading.group(1)}:00", page_number)
            )
    return observations


def _garmin_weekly(pages: list[dict[str, object]]) -> list[ParsedObservation]:
    """The one-year export reports weekly ranges rather than individual readings."""
    observations: list[ParsedObservation] = []
    for page in pages:
        page_number = int(page["page_number"])
        lines = _garmin_lines(page)
        for index, line in enumerate(lines[:-1]):
            values = GARMIN_WEEK_VALUES.match(line)
            period = GARMIN_WEEK.match(lines[index + 1])
            if not values or not period:
                continue
            observed_at = f"{int(period.group(5)):04d}-{GARMIN_MONTHS[period.group(4).casefold()]:02d}-{int(period.group(3)):02d}"
            evidence = f"{lines[index + 1]} {line}"
            for name, value, unit in (
                ("Weekly systolic blood pressure minimum", values.group(1), "mmHg"),
                ("Weekly systolic blood pressure maximum", values.group(2), "mmHg"),
                ("Weekly diastolic blood pressure minimum", values.group(3), "mmHg"),
                ("Weekly diastolic blood pressure maximum", values.group(4), "mmHg"),
                ("Weekly blood pressure reading count", values.group(5), "count"),
            ):
                item = _numeric_observation(name, value, unit, None, page_number, evidence, observed_at=observed_at)
                if item:
                    observations.append(item)
    return observations


def parse_garmin_blood_pressure(pages: list[dict[str, object]]) -> list[ParsedObservation]:
    return _garmin_readings(pages) + _garmin_weekly(pages)


#: The rhythm Kardia determined, on the line under its label or beside it.
KARDIA_DETERMINATION = re.compile(r"Kardia Advanced Determination:\s*([^\n*]+)")
KARDIA_DURATION = re.compile(r"Duration:\s*(\d+(?:[.,]\d+)?)\s*s\b")


def _kardia_recorded_at(text: str) -> str | None:
    recorded = re.search(
        r"([A-Z][a-z]+,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s+[AP]M)",
        text,
        re.I,
    )
    if not recorded:
        return None
    try:
        return datetime.strptime(recorded.group(1), "%A, %b %d, %Y, %I:%M %p").isoformat()
    except ValueError:
        return None


def _kardia_rhythm(text: str, page_number: int, observed_at: str | None) -> ParsedObservation | None:
    # The rhythm determination is the *result* of an electrocardiogram, and
    # this parser used to drop it: a 6-lead ECG entered the record as one
    # number, a pulse of 77, with "Normal Sinus Rhythm" left in the page
    # text and nowhere else.  A pulse rate is something a finger on a wrist
    # produces; the reason to record an ECG at all is the rhythm.
    determination = KARDIA_DETERMINATION.search(text)
    # Kardia offers a determination only for recordings of at least 30
    # seconds, so the duration says whether the rhythm was eligible to be
    # judged.  It is a fact about the recording, not a measurement of the
    # person, and stored as one it became a vital sign with a trend chart;
    # it travels as the rhythm row's note instead.
    duration = KARDIA_DURATION.search(text)
    if not determination:
        return None
    return ParsedObservation(
        raw_name="Heart rhythm",
        value_numeric=None,
        value_text=collapse_space(determination.group(1)),
        comparator=None,
        unit_raw=None,
        reference_text=None,
        reference_low=None,
        reference_high=None,
        page_number=page_number,
        evidence_text=collapse_space(determination.group(0)),
        confidence=0.99,
        observed_at=observed_at,
        note=collapse_space(duration.group(0)) if duration else None,
    )


def parse_kardia_ecg(pages: list[dict[str, object]]) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    for page in pages:
        page_number = int(page["page_number"])
        text = str(page.get("native_text") or "")
        if "EKG Recording Overview" not in text and "ECG Recording Overview" not in text:
            continue
        heart_rate = re.search(r"\b(\d{2,3})\s*BPM\b", text, re.I)
        observed_at = _kardia_recorded_at(text)
        if heart_rate:
            evidence = collapse_space(heart_rate.group(0))
            item = _numeric_observation(
                "Pulse rate", heart_rate.group(1), "bpm", None,
                page_number, evidence, observed_at=observed_at,
            )
            if item:
                observations.append(item)
        rhythm = _kardia_rhythm(text, page_number, observed_at)
        if rhythm is not None:
            observations.append(rhythm)
    return observations


# --- measurements printed in visit notes, consultations and ECG reports ------

#: Narrative clinic documents.  They carry a written conclusion (read by
#: ``health._report_findings``) and, beside it, the few numbers the clinician
#: measured at the visit: temperature, pulse, breathing, saturation, pressure,
#: weight and height, or an ECG's intervals.  Only those labelled measurements
#: are read here -- never the prose, and never the laboratory values a
#: consultation quotes from another report («Глюкоза 5,95, глікований
#: гемоглобін 5,26…»), which are already in the record from the laboratory's
#: own document and would be counted twice.  Kept out of
#: ``PARSED_CLINICAL_TYPES`` for the same reason ultrasound is: a consultation
#: with no measured values is complete as it stands, not a parser failure.
VISIT_MEASUREMENT_TYPES = frozenset({"consultation", "clinical_report"})

# Each unit spelling below is proven by a line in the record (Veselka /
# Doctor ELEKS notes, 2025-12 to 2026-08) and accepted only in the column or
# behind the label that gives it its meaning -- a bare «хв» is minutes anywhere
# else, and «%» or «см» on their own are anything at all:
#     «Температура: 36,6 ° C»                          primary-care visit note
#     «Частота дихання: 18 /хв SpO2: 97 %»
#     «ЧСС: 67 уд/хв. Тони серця: звучні»
#     «Вага тіла 110 кг.» / «Зріст тіла 186 см.»       cardiology consultation
#     «Температура тіла А. Т. ЧСС ЧД Сатурація»        ...its vitals table, whose
#     «36,6 ˚С мм.рт.ст 62 уд/в 16 хв 98 %»            А.Т. cell is left empty
#     «АТ: права рука 120/80 мм.рт.ст.‐ ліва рука 120/80 мм.рт.ст.»
#     «ЧСС PQ QRS QT QTc ﴾Bazett﴿ QTc ﴾Sagie/Framingham﴿»   ECG report
#     «66 уд/хв 140 мсек 80 мсек 380 мсек 399 мсек 394 мсек»
_VISIT_TEMPERATURE = r"[°˚º]\s*[CС]"
_VISIT_BPM = r"уд\s*/\s*(?:хв|в)"
_VISIT_MMHG = r"мм\.?\s*рт\.?\s*ст\.?"
_VISIT_MS = r"мсек"

#: Plausible physiological limits.  A number outside them is a misread (a
#: date, a dose, a phone number), not a measurement, and is dropped.
_VISIT_LIMITS = {
    "temperature": (30.0, 45.0), "respiratory_rate": (4, 80), "spo2": (50, 100),
    "heart_rate": (20, 250), "weight": (2, 400), "height": (40, 250), "bmi": (10, 90),
    "systolic": (50, 300), "diastolic": (20, 200),
    "pq": (40, 500), "qrs": (30, 300), "qt": (150, 800), "qtc": (150, 800),
}

#: (kind, label, value, unit) for a labelled value inside a sentence.  The
#: colon is required there: «Синусовий ритм з ЧСС 66 уд/хв» in an ECG's
#: conclusion restates the table above it, and «температури тіла понад 38,5»
#: is advice, not a reading.  Without a colon only a line holding nothing but
#: the label and its value is read (``_VISIT_LINE``).
_VISIT_FIELDS = (
    ("temperature", r"Температура(?:\s+тіла)?", r"\d{2}(?:[.,]\d)?", _VISIT_TEMPERATURE),
    ("respiratory_rate", r"Частота\s+дихання|ЧД", r"\d{1,2}", r"/\s*хв"),
    ("spo2", r"SpO2|SpO₂|Сатурація", r"\d{2,3}", r"%"),
    ("heart_rate", r"ЧСС", r"\d{2,3}", _VISIT_BPM),
    ("weight", r"Вага(?:\s+тіла)?|Маса\s+тіла", r"\d{1,3}(?:[.,]\d{1,2})?", r"кг"),
    ("height", r"Зріст(?:\s+тіла)?", r"\d{2,3}(?:[.,]\d)?", r"см"),
    # Printed without a unit: «Індекс маси тіла ﴾ІМТ﴿ [Співвідношення] 31,8».
    (
        "bmi",
        r"Індекс\s+маси\s+тіла(?:\s*[﴾(]\s*ІМТ\s*[﴿)])?(?:\s*\[[^\]\n]{1,40}\])?|ІМТ",
        r"\d{2}(?:[.,]\d{1,2})?",
        None,
    ),
)


def _visit_pattern(label: str, value: str, unit: str | None, *, whole_line: bool) -> re.Pattern[str]:
    tail = rf"\s*(?P<unit>{unit})(?!\w)" if unit else r"(?![\d.,]*\d)"
    if whole_line:
        return re.compile(rf"^(?P<label>{label})\s+(?P<value>{value}){tail}\.?$")
    return re.compile(rf"(?<!\w)(?P<label>{label})\s*:\s*(?P<value>{value}){tail}")


_VISIT_INLINE = tuple(
    (kind, _visit_pattern(label, value, unit, whole_line=False)) for kind, label, value, unit in _VISIT_FIELDS
)
_VISIT_LINE = tuple(
    (kind, _visit_pattern(label, value, unit, whole_line=True)) for kind, label, value, unit in _VISIT_FIELDS
)
#: A temperature quoted inside a diagnosis: «Субфебрильна Т (37.2 -на
#: прийомі)» (St. Paraskeva, 2022-03-12; a soft hyphen before «на»).  No unit
#: is printed, but «субфебрильна» names a raised body temperature, which is a
#: Celsius reading in every Ukrainian note.  «на прийомі» -- measured at the
#: visit -- is required, so a dose or a value quoted from history is not read.
_VISIT_FEVER = re.compile(
    r"(?<!\w)(?:Суб)?[Фф]ебрильн\w*\s+Т\s*\(\s*(?P<value>\d{2}[.,]\d)\s*(?:[\u00ad\-‐]\s*)?на\s+прийомі\s*\)"
)
_VISIT_BP_LABEL = re.compile(r"(?<!\w)(?:АТ|А\.\s*Т\.|Артеріальний\s+тиск)\s*:")
#: One reading after «АТ:», with the arm when the note names one.
_VISIT_BP_READING = re.compile(
    rf"(?:(?P<site>(?:прав|лів)\w*\s+рук\w*)\s*:?\s*)?(?P<systolic>\d{{2,3}})\s*/\s*(?P<diastolic>\d{{2,3}})\s*(?P<unit>{_VISIT_MMHG})"
)

#: Header-row tables: a line of column names, then a line of values under
#: them.  Each column says which unit its cell may carry; a row that does not
#: line up cell for cell with its header is not read at all.
_VISIT_COLUMNS = (
    ("temperature", r"Температура(?:\s+тіла)?", _VISIT_TEMPERATURE),
    ("blood_pressure", r"А\.\s*Т\.|АТ", _VISIT_MMHG),
    ("heart_rate", r"ЧСС", _VISIT_BPM),
    # The ЧД column prints a bare «хв»: breaths per minute by its header.
    ("respiratory_rate", r"ЧД", r"/\s*хв|хв"),
    ("spo2", r"Сатурація|SpO2", r"%"),
    ("qtc", r"QTc\s*[﴾(][^﴿)\n]{1,40}[﴿)]", _VISIT_MS),
    ("pq", r"PQ", _VISIT_MS),
    ("qrs", r"QRS", _VISIT_MS),
    ("qt", r"QT", _VISIT_MS),
)
_VISIT_COLUMN = re.compile(
    r"\s*(?:" + "|".join(rf"(?P<{kind}>{label})(?!\w)" for kind, label, _ in _VISIT_COLUMNS) + r")"
)
_VISIT_CELL = re.compile(
    rf"\s*(?P<value>\d{{1,3}}(?:[.,]\d+)?(?:\s*/\s*\d{{2,3}})?)?\s*"
    rf"(?P<unit>{_VISIT_TEMPERATURE}|{_VISIT_MMHG}|{_VISIT_BPM}|/\s*хв|хв|{_VISIT_MS}|%)(?!\w)"
)
_VISIT_COLUMN_UNIT = {kind: re.compile(unit) for kind, _, unit in _VISIT_COLUMNS}
_ECG_COLUMNS = frozenset({"pq", "qrs", "qt", "qtc"})
_VISIT_DATE = re.compile(r"Дата\s+(?:візиту|взаємодії)\s*:\s*(\d{1,2})\.(\d{1,2})\.(\d{4})")


def _visit_label(label: str) -> str:
    """The label as a name: ornate brackets made plain, a bracketed scale dropped."""
    label = label.replace("﴾", "(").replace("﴿", ")")
    return collapse_space(re.sub(r"\[[^\]]*\]", " ", label))


def _visit_date(pages: list[dict[str, object]]) -> str | None:
    for page in pages:
        found = _VISIT_DATE.search(str(page.get("native_text") or "") + "\n" + str(page.get("ocr_text") or ""))
        if found:
            try:
                return datetime(int(found.group(3)), int(found.group(2)), int(found.group(1))).date().isoformat()
            except ValueError:
                return None
    return None


def _visit_value(
    kind: str, name: str, printed: str, unit: str | None, page_number: int, evidence: str,
    observed_at: str | None, specimen: str | None = None,
) -> ParsedObservation | None:
    value = parse_decimal(printed)
    low, high = _VISIT_LIMITS[kind]
    if value is None or not low <= value <= high:
        return None
    return ParsedObservation(
        raw_name=name, value_numeric=value, value_text=None, comparator=None,
        unit_raw=collapse_space(unit) if unit else None, reference_text=None,
        reference_low=None, reference_high=None, page_number=page_number,
        evidence_text=evidence, confidence=0.95, observed_at=observed_at,
        value_printed=printed, specimen=specimen,
    )


def _visit_pressure(match: re.Match, page_number: int, evidence: str, observed_at: str | None):
    # The arm is the reading's site, kept as `specimen` the way an ultrasound
    # keeps the side of a paired organ: one concept, so both arms share one
    # trend and one verdict, yet two identical «120/80» readings stay two rows.
    site = collapse_space(match.group("site")).casefold() if match.group("site") else None
    for kind, name in (("systolic", "Систолічний артеріальний тиск"), ("diastolic", "Діастолічний артеріальний тиск")):
        item = _visit_value(kind, name, match.group(kind), match.group("unit"), page_number, evidence, observed_at, site)
        if item:
            yield item


def _visit_columns(header: str) -> list[tuple[str, str]] | None:
    """(kind, printed name) of each column a header line names, or None."""
    columns: list[tuple[str, str]] = []
    position = 0
    while position < len(header):
        found = _VISIT_COLUMN.match(header, position)
        if not found or found.end() == position:
            return None
        kind = found.lastgroup or ""
        columns.append((kind, found.group(kind)))
        position = found.end()
    return columns


def _visit_cells(values: str) -> list[re.Match] | None:
    """Each cell of a value line, or None when the line is not all cells."""
    cells: list[re.Match] = []
    position = 0
    while position < len(values):
        found = _VISIT_CELL.match(values, position)
        if not found:
            return None
        cells.append(found)
        position = found.end()
    return cells


def _visit_table(header: str, values: str) -> list[tuple[str, str, re.Match]] | None:
    """(kind, printed column name, cell) for each filled cell, or None."""
    columns = _visit_columns(header)
    if columns is None:
        return None
    cells = _visit_cells(values)
    if cells is None or len(columns) < 3 or len(cells) != len(columns):
        return None
    if not all(_VISIT_COLUMN_UNIT[kind].fullmatch(cell.group("unit")) for (kind, _), cell in zip(columns, cells)):
        return None
    ecg = any(kind in _ECG_COLUMNS for kind, _ in columns)
    named = []
    for (kind, label), cell in zip(columns, cells):
        if kind == "heart_rate" and ecg:
            label = "ЧСС (ЕКГ)"
        if cell.group("value"):
            named.append((kind, _visit_label(label), cell))
    return named


def _visit_table_rows(
    table: list[tuple[str, str, re.Match]], evidence: str, page_number: int, observed_at: str | None
) -> list[ParsedObservation]:
    found: list[ParsedObservation] = []
    for kind, name, cell in table:
        if kind == "blood_pressure":
            reading = _VISIT_BP_READING.fullmatch(cell.group(0).strip())
            if reading:
                found.extend(_visit_pressure(reading, page_number, evidence, observed_at))
            continue
        item = _visit_value(kind, name, cell.group("value"), cell.group("unit"), page_number, evidence, observed_at)
        if item:
            found.append(item)
    return found


def _visit_line_rows(line: str, page_number: int, observed_at: str | None) -> list[ParsedObservation]:
    """The labelled values, the quoted fever and the pressures on one line."""
    found: list[ParsedObservation] = []
    whole = next(((kind, match) for kind, pattern in _VISIT_LINE if (match := pattern.match(line))), None)
    matches = [whole] if whole else [
        (kind, match) for kind, pattern in _VISIT_INLINE for match in pattern.finditer(line)
    ]
    for kind, match in matches:
        item = _visit_value(
            kind, _visit_label(match.group("label")), match.group("value"),
            match.groupdict().get("unit"), page_number, line, observed_at,
        )
        if item:
            found.append(item)
    for match in _VISIT_FEVER.finditer(line):
        item = _visit_value(
            "temperature", "Температура тіла", match.group("value"), "°C", page_number, line, observed_at,
        )
        if item:
            found.append(item)
    label = _VISIT_BP_LABEL.search(line)
    if label:
        for reading in _VISIT_BP_READING.finditer(line, label.end()):
            found.extend(_visit_pressure(reading, page_number, line, observed_at))
    return found


def _visit_text(text: str, page_number: int, observed_at: str | None) -> list[ParsedObservation]:
    found: list[ParsedObservation] = []
    lines = [line for line in (collapse_space(raw) for raw in text.splitlines()) if line]
    for index, line in enumerate(lines):
        table = _visit_table(line, lines[index + 1]) if index + 1 < len(lines) else None
        if table:
            found.extend(_visit_table_rows(table, f"{line}\n{lines[index + 1]}", page_number, observed_at))
        else:
            found.extend(_visit_line_rows(line, page_number, observed_at))
    return found


def parse_visit_measurements(pages: list[dict[str, object]]) -> list[ParsedObservation]:
    """The measured values a clinic note prints beside its narrative.

    Labelled values only, each with a unit its label or column admits, inside
    plausible limits; the visit's own date («Дата візиту», «Дата взаємодії»)
    when the note prints one, else the caller falls back to the report date.
    An empty field («Вага: кг.») yields nothing.
    """
    observed_at = _visit_date(pages)
    observations: list[ParsedObservation] = []
    seen: set[tuple[object, ...]] = set()
    for page in pages:
        page_number = int(page["page_number"])
        for field, method, confidence_cap in (
            ("native_text", "native_pdf_text_parser", 1.0),
            ("ocr_text", "embedded_image_ocr_parser", 0.90),
        ):
            for item in _visit_text(str(page.get(field) or ""), page_number, observed_at):
                key = (item.page_number, item.raw_name, item.value_numeric, item.specimen)
                if key in seen:
                    continue
                seen.add(key)
                observations.append(
                    replace(item, extraction_method=method, confidence=min(item.confidence, confidence_cap))
                )
    return observations


#: The microbiology table: «Мікроорганізм@28 Результат@243.8 Референтні@378.4».
#: Organism names end by 207.5 («E.сoli із зміненими властивостями») and the
#: result column starts at 243.8; counts end by 340.9 («… КУО/мл»).
ESKULAB_CULTURE_COLUMNS = (220.0, 375.0)

#: A colony count the result column prints: «1.0 x 10^7 КУО/г», «<1.0 x 10^5
#: КУО/г», and the bacteriuria line's «1,0*10^3 КУО/мл».  The comparator is
#: part of the reading: «<1.0 x 10^5» is the assay's floor, not a count.
_CULTURE_COUNT = re.compile(
    r"^(?P<comparator>[<>≤≥])?\s*(?P<printed>(?P<mantissa>\d+(?:[.,]\d+)?)\s*[xх×*]\s*10\^(?P<power>\d+))"
    r"(?:\s*(?P<unit>КУО(?:/\S+)?))?$",
    re.I,
)

#: «Ступінь бактеріурії 1,0*10^3 КУО/мл»: a count printed inside the name column.
_CULTURE_INLINE_COUNT = re.compile(
    r"^(?P<name>[^\W\d_][^\d]*?)\s+(?P<count>\d+(?:[.,]\d+)?\s*[xх×*]\s*10\^\d+\s*КУО/\S+)$", re.I
)

#: «(матеріал: Приносний матеріал, кал)», printed under each section heading
#: or at the end of its last line.
_CULTURE_MATERIAL = re.compile(r"\(матеріал:\s*(?:приносний\s+матеріал,\s*)?(?P<specimen>[^()]+?)\s*(?:\)|$)", re.I)

#: «Антибіотики/Антимікотики Staphylococcus epidermidis»: whose antibiogram follows.
_CULTURE_ANTIBIOGRAM_HEAD = re.compile(r"^Антибіотики/Антимікотики\b\s*(?P<organism>.*)$", re.I)

#: An antibiogram row: the antibiotic, an optional disk potency, and the
#: verdict -- «Бензилпеніцилін 1 од Стійкий».  The potency is what the paper
#: disk held, never a measurement of the patient, so it is matched only to be
#: discarded; the verdict is the finding, EUCAST's «збільшена експозиція»
#: qualifier included.
ESKULAB_ANTIBIOGRAM = re.compile(
    rf"^(?P<name>[^\W\d_][^\d]*?)(?:\s+\d+(?:[.,]\d+)?\s*(?:мкг|од)\.?)?\s+"
    rf"(?P<verdict>(?:{SUSCEPTIBILITY_VERDICT})(?:,\s*збільшена експозиція)?)$",
    re.I,
)


def _culture_row(
    name: str, result: str, reference: str, page_number: int, specimen: str | None
) -> ParsedObservation | None:
    """One organism row: a colony count, or a printed «не виявлено»."""
    name = collapse_space(name)
    if not valid_analyte_name(name):
        return None
    evidence = collapse_space(f"{name} {result} {reference}")
    count = _CULTURE_COUNT.match(result)
    if count:
        mantissa = parse_decimal(count.group("mantissa"))
        if mantissa is None:
            return None
        return ParsedObservation(
            raw_name=name, value_numeric=mantissa * (10 ** int(count.group("power"))), value_text=None,
            comparator=count.group("comparator"), unit_raw=count.group("unit"),
            # A power-of-ten reference yields no bounds (`POWER_NOTATION_RE`);
            # the printed text is kept whole.
            reference_text=reference or None, reference_low=None, reference_high=None,
            page_number=page_number, evidence_text=evidence, confidence=0.97,
            value_printed=collapse_space(count.group("printed")), specimen=specimen,
        )
    if not re.match(r"^(?:не\s+)?виявлен\w*", result, re.I):
        return None
    return ParsedObservation(
        raw_name=name, value_numeric=None, value_text=collapse_space(result), comparator=None,
        unit_raw=None, reference_text=reference or None, reference_low=None, reference_high=None,
        page_number=page_number, evidence_text=evidence, confidence=0.96, specimen=specimen,
    )


def _antibiogram_row(
    line: str, page_number: int, specimen: str | None, organism: str | None
) -> ParsedObservation | None:
    match = ESKULAB_ANTIBIOGRAM.match(line)
    if not match:
        return None
    name = collapse_space(match.group("name")).strip(" ,.:;")
    if not valid_analyte_name(name):
        return None
    # The organism goes in the note and the section: the verdict is about
    # that isolate, and two isolates on one page each have an «Амікацин».
    return ParsedObservation(
        raw_name=name, value_numeric=None, value_text=collapse_space(match.group("verdict")),
        comparator=None, unit_raw=None, reference_text=None, reference_low=None, reference_high=None,
        page_number=page_number, evidence_text=line, confidence=0.95,
        specimen=specimen, note=organism, section=organism,
    )


class _EskulabCulture:
    """A microbiology page read top to bottom: sections, organism rows, antibiograms."""

    def __init__(self, page_number: int) -> None:
        self.page_number = page_number
        self.observations: list[ParsedObservation] = []
        self.specimen: str | None = None
        self.organism: str | None = None
        self.in_table = False
        # The row a name-column line with nothing else on it continues
        # («Escherichia coli з нормальними» / «властивостями»).
        self.open_row: int | None = None

    def read(self, line: list[tuple[float, float, float, str]]) -> None:
        text = collapse_space(" ".join(word[3] for word in line))
        material = _CULTURE_MATERIAL.search(text)
        if material:
            self.specimen, self.organism, self.in_table = collapse_space(material.group("specimen")), None, False
            return
        head = _CULTURE_ANTIBIOGRAM_HEAD.match(text)
        if head:
            self.organism = collapse_space(head.group("organism")) or self.organism
            self.in_table = False
            return
        if ESKULAB_SECTION.match(text):
            self.organism, self.specimen, self.in_table = None, None, False
            return
        antibiotic = _antibiogram_row(text, self.page_number, self.specimen, self.organism)
        if antibiotic is not None:
            self.observations.append(antibiotic)
            self.in_table, self.open_row = False, None
            return
        if text.startswith("Мікроорганізм") and _RESULT_HEADING in text:
            self.in_table, self.open_row = True, None
            return
        if line[0][0] >= ESKULAB_CULTURE_COLUMNS[0] and any(item.raw_name == text for item in self.observations):
            # The organism's own antibiogram sub-heading, printed off the
            # margin with no label: «Staphylococcus aureus» again.
            self.organism, self.in_table, self.open_row = text, False, None
            return
        if self.in_table:
            self._read_table_line(line)

    def _read_table_line(self, line: list[tuple[float, float, float, str]]) -> None:
        name_to, result_to = ESKULAB_CULTURE_COLUMNS
        if any(x0 < edge < x1 for x0, x1, _, _ in line for edge in ESKULAB_CULTURE_COLUMNS):
            # Prose runs across the columns: the commentary under a table
            # («Виявлений збудник … є контамінантом»), a signature.  The
            # table is over.
            self.in_table, self.open_row = False, None
            return
        name = collapse_space(" ".join(word[3] for word in line if word[0] < name_to))
        result = collapse_space(" ".join(word[3] for word in line if name_to <= word[0] < result_to))
        reference = collapse_space(" ".join(word[3] for word in line if word[0] >= result_to))
        if name and result:
            row = _culture_row(name, result, reference, self.page_number, self.specimen)
            self.observations.extend([row] if row is not None else [])
            self.open_row = len(self.observations) - 1 if row is not None else None
            return
        inline = _CULTURE_INLINE_COUNT.match(name) if name and not reference else None
        if inline:
            row = _culture_row(inline.group("name"), inline.group("count"), "", self.page_number, self.specimen)
            self.observations.extend([row] if row is not None else [])
            self.open_row = None
            return
        if name and not reference and self.open_row is not None:
            item = self.observations[self.open_row]
            joined = f"{item.raw_name} {name}"
            self.observations[self.open_row] = replace(
                item, raw_name=joined, evidence_text=item.evidence_text.replace(item.raw_name, joined, 1)
            )


def parse_eskulab_culture(words: list, page_number: int) -> list[ParsedObservation]:
    """Read the organisms a culture grew, and the antibiogram under them.

    One page can carry several sections -- a urine culture, then a stool
    dysbacteriosis culture -- each naming its own material under its
    heading.  Every row takes the material of the section it sits in and
    every susceptibility verdict the isolate whose antibiogram it is in;
    taking the page's first material put a stool isolate's resistances on the
    urine culture.  The table has three columns, organism, result and
    reference: read as two, every row with a reference was lost, the
    abnormal Staphylococcus counts among them.  A count is kept as printed
    («1.0 x 10^7»), comparator and all.

    The verdicts are read from the rebuilt text lines rather than by column,
    because the longest antibiotic names span the column boundary
    («Триметоприм-сульфаметоксазол» ends at 202.8), and the antibiogram is
    read on a page of its own too: it runs on past the page break under its
    «Антибіотики/Антимікотики <organism>» heading and nothing else.  The
    verdict is stored as text and the disk potency is never a value: storing
    «Бензилпеніцилін 1 од» as 1.0 would publish a meaningless number and drop
    the resistance, which is the finding that changes an antibiotic choice.
    """
    lines = _word_lines(words)
    texts = [" ".join(word[3] for word in line) for line in lines]
    if not any(text.startswith("Мікроорганізм") or _CULTURE_ANTIBIOGRAM_HEAD.match(text) for text in texts):
        return []
    culture = _EskulabCulture(page_number)
    for line in lines:
        culture.read(line)
    return culture.observations


#: The express urine microbiology checklist (J1008, J1014): a group label at
#: the margin («Мікроорганізми:»), the organism at 189.9 and the answer at
#: 483.2 -- «Escherichia coli … Не виявлено».
ESKULAB_EXPRESS_COLUMNS = (180.0, 470.0)
_EXPRESS_ANSWER = re.compile(r"^(?:не\s+)?виявлен\w*$", re.I)


def parse_eskulab_express(words: list, page_number: int) -> list[ParsedObservation]:
    """Each organism of an express microbiology checklist, with its answer.

    The page has no results table -- a lone «Результат» heading and then one
    line per organism -- so nothing read it and all ten results of the urinary
    panel were lost.  A line is a result when its middle column names
    something and its answer column says «Виявлено» or «Не виявлено»; «не
    визначається» against the susceptibility lines is no result.
    """
    lines = _word_lines(words)
    if not any([word[3] for word in line] == [_RESULT_HEADING] for line in lines):
        return []
    label_to, answer_from = ESKULAB_EXPRESS_COLUMNS
    specimen: str | None = None
    observations: list[ParsedObservation] = []
    for line in lines:
        material = _CULTURE_MATERIAL.search(collapse_space(" ".join(word[3] for word in line)))
        if material:
            specimen = collapse_space(material.group("specimen"))
            continue
        name = collapse_space(" ".join(word[3] for word in line if label_to <= word[0] < answer_from))
        answer = collapse_space(" ".join(word[3] for word in line if word[0] >= answer_from))
        if not (name and _EXPRESS_ANSWER.match(answer)) or not valid_analyte_name(name):
            continue
        observations.append(
            ParsedObservation(
                raw_name=name, value_numeric=None, value_text=answer, comparator=None, unit_raw=None,
                reference_text=None, reference_low=None, reference_high=None, page_number=page_number,
                evidence_text=f"{name} {answer}", confidence=0.95, specimen=specimen,
            )
        )
    return observations


#: The partner laboratory's coprogram, attached to an EskuLab order as a page
#: of its own: «Показники@100.8 Результат@249.3 Од. виміру@352.4 Реф.
#: значення@451.1».  Names end by 175.4, results run 212.8-335.0 (centred),
#: units 349.6-408.6 and references start at 424.3.
PARTNER_COPROGRAM_COLUMNS = (200.0, 345.0, 420.0)
_PARTNER_COPROGRAM_HEADER = ["Показники", "Результат", "Од.", "виміру", "Реф.", "значення"]
_PARTNER_COPROGRAM_END = re.compile(r"^(?:КОМЕНТАР|Керівник|Результати досліджень)", re.I)


def parse_partner_coprogram(words: list, page_number: int) -> list[ParsedObservation]:
    """The rows of the partner laboratory's coprogram form.

    Every cell is centred on its row, so a cell that wraps spreads above and
    below the name: «Дорослі: оформлений; Діти:» sits over «Форма», and
    «допускається неоформлений.» under it.  Each line belongs to the name
    nearest it; the cells are joined top to bottom.  Names are qualified with
    the specimen, as on EskuLab's own coprogram, or «Колір» and «Лейкоцити»
    resolve onto the urine concepts of the same name.
    """
    lines = _word_lines(words)
    header = next(
        (index for index, line in enumerate(lines) if [word[3] for word in line] == _PARTNER_COPROGRAM_HEADER),
        None,
    )
    if header is None:
        return []
    name_to = PARTNER_COPROGRAM_COLUMNS[0]
    body: list[list[tuple[float, float, float, str]]] = []
    for line in lines[header + 1 :]:
        if _PARTNER_COPROGRAM_END.match(line[0][3]):
            break
        body.append(line)
    anchors = [index for index, line in enumerate(body) if line[0][0] < name_to]
    if not anchors:
        return []
    groups: dict[int, list[list[tuple[float, float, float, str]]]] = {anchor: [] for anchor in anchors}
    for line in body:
        top = line[0][2]
        nearest = min(anchors, key=lambda anchor: abs(body[anchor][0][2] - top))
        groups[nearest].append(line)
    observations: list[ParsedObservation] = []
    for anchor in anchors:
        cells: list[list[str]] = [[], [], [], []]
        for line in sorted(groups[anchor], key=lambda item: item[0][2]):
            for x0, _x1, _top, text in line:
                cells[sum(1 for edge in PARTNER_COPROGRAM_COLUMNS if x0 >= edge)].append(text)
        name, result, unit, reference = (collapse_space(" ".join(cell)) for cell in cells)
        if not result:
            continue  # the «30511 Копрограма» heading
        found = _eskulab_observation(f"{name} (кал)", result, unit, [reference], page_number)
        if found is not None:
            observations.append(found)
    return observations


#: Synevo's urinalysis prints the dipstick and then a manual microscopy of the
#: sediment under this heading, and the two halves repeat analyte names: a
#: «Лейкоцити» and an «Еритроцити» in each.  Read as flat text the microscopy
#: rows were lost three ways -- «до 5.0 в п/з» and «незмінені» are not words
#: the categorical pass knows, «поодинокі в / препараті» and «в невеликій /
#: кількості» wrap under their own row with the reference column in between,
#: and the microscopy «Еритроцити не виявлені» collapsed into the dipstick row
#: of the same name and value.  The columns say which word is which.
SYNEVO_SEDIMENT_HEADING = re.compile(r"^Ручна мікроскопія осаду сечі$", re.I)
SYNEVO_SEDIMENT_END = re.compile(
    r"^(?:Результати лабораторних|Примітка|Обробка матеріалу|Стор\.\s*\d)", re.I
)


def _word_lines(words: list) -> list[list[tuple[float, float, float, str]]]:
    """Words grouped into printed lines, each sorted left to right.

    Two points of tolerance: Synevo sets a row's value one point below its
    name, and the next printed line is ten points further down.
    """
    lines: dict[float, list[tuple[float, float, float, str]]] = {}
    for x0, x1, top, text in words:
        key = next((seen for seen in lines if abs(seen - top) <= 2.0), top)
        lines.setdefault(key, []).append((x0, x1, top, text))
    return [sorted(lines[top]) for top in sorted(lines)]


def _synevo_columns(lines: list[list[tuple[float, float, float, str]]]) -> tuple[float, float, float] | None:
    """Where the value, unit and reference columns start, off the «Результат … Од.» header."""
    header = next(
        (
            line for line in lines
            if any(word[3] == _RESULT_HEADING for word in line) and any(word[3] == "Од." for word in line)
        ),
        None,
    )
    if header is None:
        return None
    result_x = next(word[0] for word in header if word[3] == _RESULT_HEADING)
    unit_x = next(word[0] for word in header if word[3] == "Од.")
    # Values are centred under «Результат», so a long one starts well left of
    # it («не виявлені (в нормі - не виявлені)» 23 points left); units sit under «Од.»; the reference column starts past it.
    return result_x - 25.0, unit_x - 12.0, unit_x + 25.0


def _sediment_section(lines: list[list[tuple[float, float, float, str]]]) -> list | None:
    """The lines under the microscopy heading, up to the block that closes it."""
    start = next(
        (
            index for index, line in enumerate(lines)
            if SYNEVO_SEDIMENT_HEADING.match(collapse_space(" ".join(word[3] for word in line)))
        ),
        None,
    )
    if start is None:
        return None
    section: list[list[tuple[float, float, float, str]]] = []
    for line in lines[start + 1 :]:
        if SYNEVO_SEDIMENT_END.match(line[0][3] + " " + " ".join(word[3] for word in line[1:3])):
            break
        section.append(line)
    return section


def _sediment_column(x0: float, columns: tuple[float, float, float]) -> str:
    value_from, unit_from, reference_from = columns
    if x0 < value_from:
        return "name"
    if x0 < unit_from:
        return "value"
    if x0 < reference_from:
        return "unit"
    return "reference"


def _sediment_observation(
    row: list[list[tuple[float, float, float, str]]], columns: tuple[float, float, float], page_number: int
) -> ParsedObservation | None:
    cells: dict[str, list[str]] = {"name": [], "value": [], "unit": [], "reference": []}
    for line in row:
        for x0, _x1, _top, text in line:
            cells[_sediment_column(x0, columns)].append(text)
    name = collapse_space(" ".join(cells["name"])).strip(" ,-:")
    value = collapse_space(" ".join(cells["value"]))
    if not value or not valid_analyte_name(name):
        return None
    numeric = parse_decimal(value) if re.fullmatch(_DECIMAL, value) else None
    return ParsedObservation(
        raw_name=name,
        value_numeric=numeric,
        value_text=None if numeric is not None else value,
        comparator=None,
        unit_raw=collapse_space(" ".join(cells["unit"])) or None,
        reference_text=collapse_space(" ".join(cells["reference"])) or None,
        reference_low=None,
        reference_high=None,
        page_number=page_number,
        evidence_text=collapse_space(
            " ".join(" ".join(word[3] for word in line) for line in row)
        ),
        confidence=0.91,
        section="sediment",
    )


def parse_synevo_sediment(words: list, page_number: int) -> list[ParsedObservation]:
    """The manual-microscopy rows of a Synevo urinalysis, read by column.

    Every row carries ``section="sediment"`` so that `parse_document` keeps
    the microscopy «Еритроцити» apart from the dipstick row of the same name
    and value; the lab itself tells the two apart only by position.
    """
    lines = _word_lines(words)
    columns = _synevo_columns(lines)
    if columns is None:
        return []
    section = _sediment_section(lines)
    if section is None:
        return []
    rows: list[list[list[tuple[float, float, float, str]]]] = []
    for line in section:
        name_words = [word for word in line if word[0] < columns[0]]
        if name_words and name_words[0][3][:1].isupper():
            rows.append([line])
        elif rows:
            rows[-1].append(line)
    observations: list[ParsedObservation] = []
    for row in rows:
        item = _sediment_observation(row, columns, page_number)
        if item is not None:
            observations.append(item)
    return observations


#: The norm Synevo sometimes prints inside the result cell itself:
#: «не виявлені (в нормі - не виявлені)».
_SYNEVO_INLINE_NORM = re.compile(r"^(?P<value>.+?)\s*(?P<norm>\(в нормі[^)]*\))$", re.I)
_SYNEVO_GENOTYPE = re.compile(r"^(?:гомозиготне|гетерозиготне)\s+носійство$", re.I)
_SYNEVO_NUMBER = re.compile(rf"(?P<comparator>[<>≤≥])?\s*(?P<number>{_DECIMAL})")


def _synevo_unitless_rows(lines: list, columns: tuple[float, float, float]) -> list[tuple[int, list[int], str | None]]:
    """(first line, every line, heading) of each table row up to the microscopy or the footer.

    A row starts on a line whose name column's first word carries a capital; every other
    line -- a wrapped name («найпростіших»), a wrapped value («невеликій» /
    «кількості»), more of the reference block -- continues the row above.  A
    name with an unclosed bracket continues even onto a capital («HDL)»).
    """
    value_from = columns[0]
    header = next(
        (index for index, line in enumerate(lines)
         if any(word[3] == _RESULT_HEADING for word in line) and any(word[3] == "Од." for word in line)),
        None,
    )
    rows: list[tuple[int, list[int], str | None]] = []
    heading: str | None = None
    for index in range(header + 1 if header is not None else len(lines), len(lines)):
        line = lines[index]
        text = collapse_space(" ".join(word[3] for word in line))
        if SYNEVO_SEDIMENT_HEADING.match(text) or SYNEVO_SEDIMENT_END.match(text):
            break
        name = " ".join(word[3] for word in line if word[0] < value_from)
        open_name = bool(rows) and _unclosed_bracket(
            " ".join(word[3] for row_line in rows[-1][1] for word in lines[row_line] if word[0] < value_from)
        )
        # «pH» opens lowercase; a wrapped name tail («найпростіших») has no capital.
        if any(char.isupper() for char in name.split(" ")[0]) and not open_name:
            if not any(word[0] >= value_from for word in line):
                heading = name  # a section heading: «Копрограма»
            rows.append((index, [index], heading))
        elif rows:
            rows[-1][1].append(index)
    return rows


def _unclosed_bracket(name: str) -> bool:
    return name.count("(") > name.count(")")


def parse_synevo_unitless(words: list, page_number: int) -> list[ParsedObservation]:
    """Synevo rows with nothing in the unit column, read by column.

    A coprogram row wraps its *result* under itself, with the reference cell
    in between: «Дріжджовий грибок | виявлений в | не виявлений» over
    «невеликій» over «кількості».  Read as flat text the categorical pass took
    «виявлений в» as more of the name and the reference «не виявлений» as the
    result -- yeast the laboratory found was published as not found.  The
    columns say which word is which; rows with a unit stay with the text
    passes, which read them well.  Rows carry their section heading so the
    coprogram's «Яйця гельмінтів» is not merged into the parasite panel's.
    """
    lines = _word_lines(words)
    columns = _synevo_columns(lines)
    if columns is None:
        return []
    observations: list[ParsedObservation] = []
    for first, row, heading in _synevo_unitless_rows(lines, columns):
        cells: dict[str, list[str]] = {"name": [], "value": [], "unit": [], "reference": []}
        for index in row:
            for x0, _x1, _top, text in lines[index]:
                cells[_sediment_column(x0, columns)].append(text)
        name = collapse_space(" ".join(cells["name"])).strip(" ,-:")
        value = collapse_space(" ".join(cells["value"]))
        if not value or cells["unit"] or not valid_analyte_name(name):
            continue
        reference = _synevo_block(lines, first, columns) or None
        inline = _SYNEVO_INLINE_NORM.match(value) if not reference else None
        if inline:
            # «не виявлені (в нормі - не виявлені)» is all result column (the
            # words start inside it, left of the reference header), the row's
            # reference column is empty, and the lab's own record has no norm
            # for it.  Moved into the reference, a gloss in the result cell was
            # published as an interval the laboratory never printed.
            value = inline.group("value")
        if not reference and not inline and not _SYNEVO_GENOTYPE.match(value):
            # A result row prints its norm; a line with none is a panel heading
            # or a note in the result column («Звіт з описом лабораторних
            # показників | Ваш результат готовий ...»), and stays with the
            # text passes as before.  The exception is a genotype, printed
            # under its own PCR heading with no norm: «ПЛР. Фолатний цикл.
            # MTRR (66 A>G)» over «Гомозиготне носійство».
            continue
        number = _SYNEVO_NUMBER.fullmatch(value)
        # A block of several lines is a labelled scale (coprogram pH: «7. 0 -
        # 7.5: в нормі», «5.5 – 6.75: кисла», ...); its first pair of numbers
        # is not the interval («0 - 7.5» put an acidic 6.75 inside it), so only
        # a one-line reference gives bounds.
        first_reference = collapse_space(" ".join(word[3] for word in lines[first] if word[0] >= columns[2]))
        limits = reference_limits(reference) if number and reference == first_reference else ReferenceLimits()
        observations.append(ParsedObservation(
            raw_name=name,
            value_numeric=parse_decimal(number.group("number")) if number else None,
            value_text=None if number else value,
            comparator=number.group("comparator") if number else None,
            unit_raw=None,
            reference_text=reference,
            reference_low=limits.low,
            reference_high=limits.high,
            page_number=page_number,
            evidence_text=collapse_space(" ".join(" ".join(word[3] for word in lines[index]) for index in row)),
            confidence=0.93,
            value_printed=number.group("number") if number else None,
            section=heading,
        ))
    return observations


_US_NUMBER = r"_*(\d+(?:[.,]\d+)?)_*"


def _us_row(
    name: str, value: str, unit: str, evidence: str, page_number: int, *,
    reference: str | None = None, low: float | None = None, high: float | None = None,
    specimen: str | None = None, reading: str | None = None,
    bands: dict[str, tuple[float, float]] | None = None,
) -> ParsedObservation | None:
    number = parse_decimal(value)
    if number is None:
        return None
    return ParsedObservation(
        raw_name=name, value_numeric=number, value_text=None, comparator=None, unit_raw=unit,
        reference_text=reference, reference_low=low, reference_high=high,
        page_number=page_number, evidence_text=collapse_space(evidence).replace("_", ""),
        confidence=0.9, specimen=specimen, vendor_interpretation=reading,
        value_printed=value, sex_bands=bands,
    )


def parse_ultrasound(text: str, page_number: int, previous: str = "") -> list[ParsedObservation]:
    """The measurements an ultrasound protocol prints with a norm, or that the
    contract names as worth a trend: LV mass index, carotid PSV and IMT,
    thyroid volume, liver size, common bile duct, bladder wall.

    Each is stored under the catalogue's English concept name -- these rows
    have no laboratory label to keep, the protocol prints them as prose -- with
    the printed sentence as evidence, the side or lobe as ``specimen``, and the
    protocol's own norm where it prints one.  A protocol's verbal judgement of
    the same organ («Печінка збільшена», «Стінка потовщена») is its vendor
    interpretation.  Nothing is inferred that the page does not say.
    """
    lines = [collapse_space(line) for line in text.splitlines() if collapse_space(line)]
    flat = " ".join(lines)
    rows: list[ParsedObservation | None] = [
        *_us_lv_mass_index(lines, page_number),
        *_us_common_carotid(flat, page_number),
    ]
    for found in re.finditer(r"КІМ\s+(?P<side>справа|зліва)\s+(?P<value>\d+(?:[.,]\d+)?)\s*мм", flat):
        rows.append(_us_row("Carotid intima-media thickness", found.group("value"), "мм",
                            found.group(0), page_number, specimen=found.group("side")))
    rows.extend(_us_thyroid_volume(flat, page_number))
    rows.extend((_us_liver(flat, page_number), _us_bile_duct(flat, page_number), _us_bladder_wall(flat, page_number)))
    observations = [row for row in rows if row is not None]
    observations.extend(_us_abdomen(flat, page_number, _us_heading(previous)))
    observations.extend(_us_thyroid(flat, page_number))
    observations.extend(_us_echo(lines, page_number))
    observations.extend(_us_duplex(flat, page_number))
    observations.extend(_us_soft_tissue(flat, lines, page_number))
    return observations


#: «43-95 г/м2».  The first digit is written out so that a search has no
#: repetition to enter without consuming one; the rest of the run is taken
#: whole, since a blank or the dash follows it.
_US_LVMI_BAND = re.compile(r"(\d\d*+)\s*-\s*(\d+)\s*г/м2")
#: The unit of every peak systolic velocity a duplex protocol prints.
_CM_PER_S = "см/сек"


def _us_lv_mass_index(lines: list[str], page_number: int) -> list[ParsedObservation | None]:
    """Echo: «Індекс маси міокарда ЛШ» with one band per sex printed around it."""
    rows: list[ParsedObservation | None] = []
    for index, line in enumerate(lines):
        if not line.startswith("Індекс маси міокарда ЛШ"):
            continue
        window = lines[max(0, index - 1) : index + 3]
        joined = " ".join(window)
        bands = list(_US_LVMI_BAND.finditer(joined))
        sexes = re.findall(r"\((жінки|чоловіки)\)", joined)
        value = _us_lv_mass_value([line] + lines[index + 1 : index + 3])
        if value is None or len(bands) != len(sexes):
            continue
        per_sex = {
            ("male" if sex == "чоловіки" else "female"): (float(band.group(1)), float(band.group(2)))
            for band, sex in zip(bands, sexes)
        }
        reference = " ".join(f"{band.group(0)} ({sex})" for band, sex in zip(bands, sexes))
        evidence = " ".join(
            item for item in window
            if "г/м2" in item or item.startswith("Індекс маси") or re.fullmatch(r"\(?(?:жінки|чоловіки)\)?|\d+(?:[.,]\d+)?", item)
        )
        rows.append(_us_row("Left ventricular mass index", value, "г/м2", evidence, page_number,
                            reference=reference, bands=per_sex))
    return rows


def _us_lv_mass_value(candidates: list[str]) -> str | None:
    """The first number on the label line or the two under it, bands taken out."""
    for candidate in candidates:
        rest = _US_LVMI_BAND.sub(" ", candidate.replace("Індекс маси міокарда ЛШ", " "))
        found = re.match(r"^\s*(\d+(?:[.,]\d+)?)\b", rest)
        if found:
            return found.group(1)
    return None


def _us_common_carotid(flat: str, page_number: int) -> list[ParsedObservation | None]:
    """Duplex: «Загальна сонна артерія, права 89 N=50-104», or wrapped so the
    side lands on the line below the value."""
    rows: list[ParsedObservation | None] = []
    for found in re.finditer(
        r"Загальна сонна\s+артерія,?\s*(?P<side>права|ліва)?(?:(?!N=).){0,80}?\s(?P<value>\d{2,3})\s+N=(?P<low>\d+)-(?P<high>\d+)",
        flat,
    ):
        side = found.group("side")
        if not side:
            # Wrapped: «Загальна сонна артерія, …» / «89 N=50-104» / «права …».
            after = re.split(r"артерія|N=", flat[found.end() : found.end() + 60])[0]
            wrapped = re.search(r"\b(права|ліва)\b", after)
            side = wrapped.group(1) if wrapped else None
        if not side:
            continue
        rows.append(_us_row(
            "Peak systolic velocity, common carotid artery", found.group("value"), _CM_PER_S,
            found.group(0), page_number, reference=f"N={found.group('low')}-{found.group('high')}",
            low=float(found.group("low")), high=float(found.group("high")), specimen=side,
        ))
    return rows


def _us_thyroid_volume(flat: str, page_number: int) -> list[ParsedObservation | None]:
    """Thyroid: «Права частка : … Об’єм : 6 N- 7.5 cm3», «Сумарний об’єм: 12.5 сm3 N- 13cm3»."""
    return [
        _us_row(
            "Thyroid volume", found.group("value"), "cm3", found.group(0), page_number,
            reference=found.group("ref").replace("сm3", "cm3"), high=parse_decimal(found.group("high")),
            specimen=found.group("site"),
        )
        for found in re.finditer(
            r"(?P<site>Права частка|Ліва частка|Сумарний)[^О]{0,60}?(?:Об['’]єм|об['’]єм)\s*:\s*(?P<value>\d+(?:[.,]\d+)?)\s*(?:[cс]m3)?\s*"
            r"(?P<ref>N-\s*(?P<high>\d+(?:[.,]\d+)?)\s*[cс]m3(?:\s*\([^)]*\))?)",
            flat,
        )
    ]


def _us_liver(flat: str, page_number: int) -> ParsedObservation | None:
    """Abdomen.  The liver's verbal judgement sits on the heading line above."""
    liver = re.search(
        rf"Печінка(?P<verdict>[^:.]*?)(?:в розмірах)?:\s*Права частка:\s*Косий вертикальний[^)]*\)\s*{_US_NUMBER}\s*мм",
        flat,
    ) or re.search(rf"Печінка:\s*розміри:\s*Права доля\s+{_US_NUMBER}\s*мм", flat)
    if not liver:
        return None
    verdict = (liver.groupdict().get("verdict") or "").strip()
    reading = None
    if re.search(r"\bне\s+збільшена", verdict):
        reading = "within_vendor_range"
    elif "збільшена" in verdict:
        reading = "high"
    number = next(group for group in liver.groups()[::-1] if group)
    return _us_row("Liver craniocaudal size", number, "мм", liver.group(0), page_number,
                   specimen="права частка", reading=reading)


def _us_bile_duct(flat: str, page_number: int) -> ParsedObservation | None:
    duct = re.search(rf"Холедох[^.]*?{_US_NUMBER}\s*мм\.?\s*\((?P<ref>норма\s+(?P<high>\d+(?:[.,]\d+)?)\s*мм)\)", flat)
    if not duct:
        return None
    return _us_row("Common bile duct diameter", duct.group(1), "мм", duct.group(0), page_number,
                   reference=duct.group("ref"), high=parse_decimal(duct.group("high")))


def _us_bladder_wall(flat: str, page_number: int) -> ParsedObservation | None:
    wall = re.search(rf"Стінка\s+(?P<negation>не\s+)?потовщена\s*[-–]\s*{_US_NUMBER}\s*мм", flat) or re.search(
        rf"Сечовий міхур:.*?стінка:[^;]*?товщиною\s+{_US_NUMBER}\s*мм", flat
    )
    if not wall:
        return None
    groups = wall.groupdict()
    reading = None
    if "negation" in groups:
        reading = "within_vendor_range" if groups["negation"] else "high"
    number = next(group for group in wall.groups()[::-1] if group and re.match(r"\d", group))
    return _us_row("Bladder wall thickness", number, "мм", wall.group(0), page_number, reading=reading)


def _us_n(group: str) -> str:
    """A printed size, with the blank-form underscores Expert leaves around it («_81_», «23__»)."""
    return rf"_*(?P<{group}>\d+(?:[.,]\d+)?)_*"


#: «81 * 35.1», «_81_ х _23_» (Cyrillic х), «9,4х4,6», «116,4 x 56,9».
_US_TIMES = r"\s*[*xхXХ×]\s*"
_US_PAIR = rf"{_us_n('a')}{_US_TIMES}{_us_n('b')}\s*мм"
#: The organ headings an abdominal protocol prints, Expert's and Veselka's
#: alike.  A measurement is read only inside its own organ's text, so the
#: «Розмірами: A * B мм» every organ prints cannot be filed under another one.
_US_ORGAN = re.compile(
    r"(Печінка|Жовчевий міхур|Підшлункова залоза|Права нирка|Ліва нирка|Селезінка|Сечовий міхур|ВИСНОВОК|Висновок)"
)


def _us_heading(text: str) -> str | None:
    """The organ a page break fell inside: the last heading on the previous page."""
    found = _US_ORGAN.findall(text or "")
    return found[-1] if found else None


def _us_segments(flat: str, carried: str | None) -> dict[str, str]:
    """Each organ's text.  Text above the first heading belongs to ``carried``:
    Expert's 2025-02-01 protocol breaks the page inside «Сечовий міхур», so its
    volume opens page 2 with no heading of its own."""
    parts = _US_ORGAN.split(flat)
    segments: dict[str, str] = {}
    if carried and parts[0].strip():
        segments[carried] = parts[0]
    for heading, body in zip(parts[1::2], parts[2::2]):
        segments[heading] = (segments.get(heading, "") + " " + heading + body).strip()
    return segments


def _us_evidence(segment: str, found: re.Match) -> str:
    """The organ's heading through the match, so the evidence names the organ
    («Права нирка Розмірами: 119.1 * 66.1мм») -- or the match alone when the
    heading is too far above it to quote."""
    return segment[: found.end()] if found.start() <= 100 else found.group(0)


def _us_size(
    name: str, found: re.Match, group: str, evidence: str, page_number: int, *,
    specimen: str | None = None, reading: str | None = None,
) -> ParsedObservation | None:
    """«до 9.3 мм» is a size stated as an upper limit, kept with its «≤»."""
    item = _us_row(name, found.group(group), "мм", evidence, page_number, specimen=specimen, reading=reading)
    if item is not None and re.search(rf"\bдо\s*_*{re.escape(found.group(group))}", found.group(0)):
        item = replace(item, comparator="≤")
    return item


def _us_pair(
    long_name: str, short_name: str, found: re.Match, page_number: int, *,
    specimen: str | None = None, reading: str | None = None, evidence: str | None = None,
) -> list[ParsedObservation]:
    """«A * B мм» with no axis printed: the larger figure is the organ's length
    (a kidney, spleen or gallbladder is always longest along its long axis) and
    the smaller its width.  Sorting, not the printed order, decides which."""
    a, b = found.group("a"), found.group("b")
    longer, shorter = (a, b) if parse_decimal(a) >= parse_decimal(b) else (b, a)
    evidence = evidence or found.group(0)
    rows = [
        _us_row(long_name, longer, "мм", evidence, page_number, specimen=specimen, reading=reading),
        _us_row(short_name, shorter, "мм", evidence, page_number, specimen=specimen),
    ]
    return [row for row in rows if row is not None]


def _us_abdomen(flat: str, page_number: int, carried: str | None) -> list[ParsedObservation]:
    """Every size an abdominal protocol prints beside the liver's right lobe,
    the bile duct and the bladder wall, which ``parse_ultrasound`` reads above.

    Expert Hospital («Ліва частка: 70.6 мм.», «Розмірами: 119.1 * 66.1мм.
    Товщина паренхіми до 14мм.») and Veselka («Ліва доля 69,0 мм», «розміри:
    124,5 х 63,7 мм ... паренхіма: товщиною 20,6 мм») print the same
    measurements in two templates; both land on one concept each, so the
    trends line up across clinics.  A bladder's three unlabelled dimensions
    are not read: which axis is which is not printed, and the volume the
    protocol prints beside them is the measurement that is read.
    """
    segments = _us_segments(flat, carried)
    rows: list[ParsedObservation | None] = [
        *_us_liver_sizes(segments.get("Печінка", ""), page_number),
        *_us_gallbladder(segments.get("Жовчевий міхур", ""), page_number),
        *_us_pancreas(segments.get("Підшлункова залоза", ""), page_number),
    ]
    for heading, side in (("Права нирка", "права"), ("Ліва нирка", "ліва")):
        rows.extend(_us_kidney(segments.get(heading, ""), side, page_number))
    rows.extend(_us_spleen(segments.get("Селезінка", ""), page_number))
    rows.extend(_us_bladder_volume(segments.get("Сечовий міхур", ""), page_number))
    return [row for row in rows if row is not None]


def _us_liver_sizes(liver: str, page_number: int) -> list[ParsedObservation | None]:
    rows: list[ParsedObservation | None] = []
    found = re.search(rf"Ліва (?:частка|доля):?\s*{_us_n('v')}\s*мм", liver)
    if found:
        rows.append(_us_size("Liver left lobe size", found, "v", _us_evidence(liver, found), page_number,
                             specimen="ліва частка"))
    found = re.search(rf"Ворітна вена[^.]*?(?:до\s*)?{_us_n('v')}\s*мм", liver)
    if found:
        rows.append(_us_size("Portal vein diameter", found, "v", found.group(0), page_number))
    return rows


def _us_gallbladder(gallbladder: str, page_number: int) -> list[ParsedObservation]:
    found = re.search(rf"розмір\w*:\s*{_US_PAIR}", gallbladder)
    if not found:
        return []
    return _us_pair("Gallbladder length", "Gallbladder width", found, page_number,
                    evidence=_us_evidence(gallbladder, found))


def _us_pancreas(pancreas: str, page_number: int) -> list[ParsedObservation | None]:
    rows: list[ParsedObservation | None] = []
    for part, name in (("головка", "Pancreatic head size"), ("тіло", "Pancreatic body size"), ("хвіст", "Pancreatic tail size")):
        found = re.search(rf"\b{part}\s*{_us_n('v')}\s*мм", pancreas)
        if found:
            rows.append(_us_size(name, found, "v", _us_evidence(pancreas, found), page_number))
    found = re.search(
        rf"Діаметр селезінкової вени[^()]*?(?:до\s*)?{_us_n('v')}\s*мм"
        rf"(?:\s*\((?P<ref>норма\s+до\s+(?P<high>\d+(?:[.,]\d+)?)\s*мм)\))?",
        pancreas,
    )
    if found:
        vein = _us_size("Splenic vein diameter", found, "v", found.group(0), page_number)
        if vein is not None and found.group("ref"):
            vein = replace(vein, reference_text=found.group("ref"), reference_high=parse_decimal(found.group("high")))
        rows.append(vein)
    return rows


def _us_kidney(kidney: str, side: str, page_number: int) -> list[ParsedObservation | None]:
    rows: list[ParsedObservation | None] = []
    found = re.search(rf"(?:Розмірами|розміри):\s*{_US_PAIR}", kidney)
    if found:
        rows.extend(_us_pair("Kidney length", "Kidney width", found, page_number, specimen=side,
                             evidence=_us_evidence(kidney, found)))
    found = re.search(rf"(?:Товщина паренхіми|паренхіма:\s*товщиною)\s*(?:до\s*)?{_us_n('v')}\s*мм", kidney)
    if found:
        rows.append(_us_size("Renal parenchymal thickness", found, "v", _us_evidence(kidney, found),
                             page_number, specimen=side))
    # «поодинокі кристали солей 1мм-2мм»: the size range of the crystals,
    # stored as its upper end -- the largest crystal is what a stone
    # threshold is read against, and the evidence keeps the whole range.
    found = re.search(rf"кристали солей\s*{_us_n('a')}\s*мм\s*[-–]\s*{_us_n('b')}\s*мм", kidney)
    if found:
        largest = max((found.group("a"), found.group("b")), key=parse_decimal)
        rows.append(_us_row("Largest renal salt crystal size", largest, "мм", found.group(0), page_number, specimen=side))
    return rows


def _us_spleen(spleen: str, page_number: int) -> list[ParsedObservation]:
    found = re.search(rf"(?:Розмірами|розміри):\s*{_US_PAIR}", spleen)
    if not found:
        return []
    reading = None
    if re.search(r"\bне\s+збільшена", spleen, re.I):
        reading = "within_vendor_range"
    elif re.search(r"\bзбільшена", spleen, re.I):
        reading = "high"
    return _us_pair("Spleen length", "Spleen thickness", found, page_number, reading=reading,
                    evidence=_us_evidence(spleen, found))


def _us_bladder_volume(bladder: str, page_number: int) -> list[ParsedObservation | None]:
    rows: list[ParsedObservation | None] = []
    # «V= 35см³»: the text layer drops the superscript and leaves «35см .»,
    # which read as printed would be a length.  Behind «V=» it is a volume.
    found = re.search(rf"\bV\s*=\s*{_us_n('v')}\s*(?:см3|см³|cm3|cm³|см)(?![а-яіїєґ])", bladder)
    if found:
        rows.append(_us_row("Urinary bladder volume", found.group("v"), "см3", found.group(0), page_number))
    found = re.search(rf"об['’]ємом\s*(?:до\s*)?{_us_n('v')}\s*мл", bladder)
    if found:
        volume = _us_row("Urinary bladder volume", found.group("v"), "мл", found.group(0), page_number)
        if volume is not None and re.search(r"\bдо\s", found.group(0)):
            volume = replace(volume, comparator="≤")
        rows.append(volume)
    return rows


def _us_thyroid(flat: str, page_number: int) -> list[ParsedObservation]:
    """Isthmus, lobe length and the TI-RADS category per lobe.

    «Права частка : 15.4 / 17.8 / 47мм.» prints three unlabelled figures.  The
    largest is the lobe's length -- a thyroid lobe is always longest
    craniocaudally -- and is read; the other two are width and depth in an
    order the page does not state, so they are not.  The lobe's volume, which
    is computed from all three, is read above.
    """
    rows: list[ParsedObservation | None] = []
    found = re.search(rf"перешийок\s*{_us_n('v')}\s*мм", flat)
    if found:
        rows.append(_us_row("Thyroid isthmus thickness", found.group("v"), "мм", found.group(0), page_number))
    for found in re.finditer(
        rf"(?P<site>Права частка|Ліва частка)\s*:\s*{_us_n('a')}\s*/\s*{_us_n('b')}\s*/\s*{_us_n('c')}\s*мм", flat
    ):
        length = max((found.group("a"), found.group("b"), found.group("c")), key=parse_decimal)
        rows.append(_us_row("Thyroid lobe length", length, "мм", found.group(0), page_number, specimen=found.group("site")))
    scale = re.search(r"TI-?RADS\s*:?(?P<body>(?:\s*(?:Права|Ліва) частка\s*[-–]\s*\d\s*категорі\w*)+)", flat)
    for found in re.finditer(r"(?P<site>Права частка|Ліва частка)\s*[-–]\s*(?P<v>\d)\s*категорі\w*", scale.group("body") if scale else ""):
        item = _us_row("Thyroid TI-RADS category", found.group("v"), "", found.group(0), page_number, specimen=found.group("site"))
        rows.append(replace(item, unit_raw=None, evidence_text=f"TI-RADS: {item.evidence_text}") if item else None)
    return [row for row in rows if row is not None]


#: Expert's echocardiogram table: label, value, then its norm in centimetres.
_US_ECHO_ROWS = (
    ("Правий шлуночок", "Right ventricular diameter"),
    ("Міжшлуночкова перетинка, діастола", "Interventricular septal thickness, diastole"),
    ("Лівий шлуночок, діастола", "Left ventricular end-diastolic diameter"),
    ("Стінка ЛШ, діастола", "Left ventricular posterior wall thickness, diastole"),
    ("Діаметр висхідної аорти", "Ascending aorta diameter"),
    ("Діаметр аорти на рівні синусів Вальсальви", "Aortic root diameter at the sinuses of Valsalva"),
    ("Ліве передсердя", "Left atrial diameter"),
)
_US_RANGE = r"(?P<ref>(?P<low>\d+(?:[.,]\d+)?)\s*[-–—]\s*(?P<high>\d+(?:[.,]\d+)?)\s*{unit})"
#: «Фракція викиду Понад 55% Понад 55%»: the value, then the norm.
_US_EJECTION_FRACTION = re.compile(
    rf"Фракція викиду\s+(?P<over>Понад\s*)?(?P<v>{_DECIMAL})\s*%\s*(?P<ref>Понад\s*(?P<low>{_DECIMAL})\s*%)?"
)


def _us_echo(lines: list[str], page_number: int) -> list[ParsedObservation]:
    """The echocardiogram's measurement table and its valve Doppler row.

    LV mass index is read by ``parse_ultrasound`` above and is not touched
    here.  «Фракція викиду Понад 55% | Понад 55%» is stored as «> 55 %»: the
    page states a lower limit, not a number, and the row is within the norm
    the page prints beside it.
    """
    rows: list[ParsedObservation | None] = []
    for line in lines:
        rows.extend(_us_echo_table_rows(line, page_number))
        found = _US_EJECTION_FRACTION.fullmatch(line)
        if found:
            rows.append(_us_ejection_fraction(found, line, page_number))
    rows.extend(_us_valve_doppler(lines, page_number))
    return [row for row in rows if row is not None]


def _us_echo_table_rows(line: str, page_number: int) -> list[ParsedObservation | None]:
    rows: list[ParsedObservation | None] = []
    for label, name in _US_ECHO_ROWS:
        found = re.fullmatch(rf"{label}\s+(?P<v>\d+(?:[.,]\d+)?)\s+{_US_RANGE.format(unit='см')}", line)
        if found:
            rows.append(_us_row(
                name, found.group("v"), "см", line, page_number, reference=found.group("ref"),
                low=parse_decimal(found.group("low")), high=parse_decimal(found.group("high")),
            ))
    return rows


def _us_ejection_fraction(found: re.Match, line: str, page_number: int) -> ParsedObservation | None:
    item = _us_row("Left ventricular ejection fraction", found.group("v"), "%", line, page_number, reference=found.group("ref"))
    if item is not None and found.group("over"):
        item = replace(item, comparator=">")
    if item is not None and found.group("ref"):
        low = parse_decimal(found.group("low"))
        # «Понад 55%» against «Понад 55%» is within the norm; finalise
        # would otherwise read a value equal to a strict limit as low.
        reading = "within_vendor_range" if found.group("over") and item.value_numeric >= low else None
        item = replace(item, reference_low=low, reference_low_inclusive=False, vendor_interpretation=reading)
    return item


def _us_valve_doppler(lines: list[str], page_number: int) -> list[ParsedObservation | None]:
    rows: list[ParsedObservation | None] = []
    header = next((i for i, line in enumerate(lines) if re.fullmatch(r"Мітральний\s+Аортальний\s+Тристулковий\s+Легеневий", line)), None)
    extra = next((line for line in lines[header or 0 :] if line.startswith("Додаткові дані")), None) if header is not None else None
    if not extra:
        return rows
    cells = re.split(r"(?=Δ\s*[РP]\s*ма[хx]|[TТ]асс)", extra[len("Додаткові дані"):])[1:]
    # ponytail: only the two cells a concept exists for are read; the
    # mitral and aortic gradients are blank on every report in the record.
    # Add their concepts when one prints a value.
    if len(cells) != 4:
        return rows
    gradient = re.match(r"Δ\s*[РP]\s*ма[хx]\s*(?P<v>\d+(?:[.,]\d+)?)\s*(?P<unit>мм\.?\s*рт\.?\s*ст\.?)", cells[2].strip())
    if gradient:
        rows.append(_us_row("Tricuspid valve peak pressure gradient", gradient.group("v"), gradient.group("unit"),
                            f"Тристулковий: {cells[2].strip()}", page_number))
    acceleration = re.match(r"[TТ]асс\s*(?P<v>\d+(?:[.,]\d+)?)\s*мсек", cells[3].strip())
    if acceleration:
        rows.append(_us_row("Pulmonary artery acceleration time", acceleration.group("v"), "мсек",
                            f"Легеневий: {cells[3].strip()}", page_number))
    return rows


_US_CAROTID = {"Внутрішня": "internal", "Зовнішня": "external"}


def _us_duplex(flat: str, page_number: int) -> list[ParsedObservation]:
    """Internal and external carotid and vertebral PSV, and vertebral diameter.

    The common carotid is read by ``parse_ultrasound`` above.  The vertebral
    rows wrap around their own value: «…хід рівний , D=» / «Хребцева артерія
    ПРАВА 39 N=20-61» / «4.0 мм (N 2,5-4,4 мм)», and on the left side «D= 4.0»
    above and «мм (N…)» below -- so the diameter is read from the text around
    the PSV with the PSV itself taken out.
    """
    rows: list[ParsedObservation | None] = []
    for found in re.finditer(
        r"(?P<vessel>Внутрішня|Зовнішня) сонна(?:\s+артерія,?)?\s*(?P<side>права|ліва)?(?:(?!N=|сонна).){0,80}?\s"
        r"(?P<v>\d{2,3})\s+N=(?P<low>\d+)-(?P<high>\d+)",
        flat,
    ):
        # Wrapped as the common carotid can be: «Внутрішня сонна Кровоплин …
        # хід» / «67 N=37-105» / «артерія, права правильний».
        side = found.group("side") or next(
            iter(re.findall(r"^\s*(?:артерія,?\s*)?(права|ліва)\b", flat[found.end() : found.end() + 40])), None
        )
        if not side:
            continue
        rows.append(_us_row(
            f"Peak systolic velocity, {_US_CAROTID[found.group('vessel')]} carotid artery", found.group("v"), _CM_PER_S,
            found.group(0), page_number, reference=f"N={found.group('low')}-{found.group('high')}",
            low=float(found.group("low")), high=float(found.group("high")), specimen=side,
        ))
    vertebral = list(re.finditer(
        r"Хребцева\s+артерія\s+(?P<side>ПРАВА|ЛІВА|права|ліва)\s+(?P<v>\d{2,3})\s+N=(?P<low>\d+)-(?P<high>\d+)", flat
    ))
    for index, found in enumerate(vertebral):
        side = found.group("side").casefold()
        rows.append(_us_row(
            "Peak systolic velocity, vertebral artery", found.group("v"), _CM_PER_S, found.group(0), page_number,
            reference=f"N={found.group('low')}-{found.group('high')}",
            low=float(found.group("low")), high=float(found.group("high")), specimen=side,
        ))
        start = vertebral[index - 1].end() if index else max(0, found.start() - 120)
        end = vertebral[index + 1].start() if index + 1 < len(vertebral) else found.end() + 120
        before, after = flat[start : found.start()], flat[found.end() : end]
        # A «D=» above the row is this row's only while its «(N …)» is still to come.
        opened = before.rfind("D=")
        around = before[opened:] + " " + after if opened >= 0 and "(N" not in before[opened:] else after
        diameter = re.search(
            rf"D=\s*{_us_n('v')}\s*мм\s*\((?P<ref>N\s*(?P<low>\d+(?:[.,]\d+)?)\s*-\s*(?P<high>\d+(?:[.,]\d+)?)\s*мм)\)",
            around,
        )
        if diameter:
            rows.append(_us_row(
                "Vertebral artery diameter", diameter.group("v"), "мм", f"{found.group(0)} {diameter.group(0)}", page_number,
                reference=diameter.group("ref"), low=parse_decimal(diameter.group("low")),
                high=parse_decimal(diameter.group("high")), specimen=side,
            ))
    return [row for row in rows if row is not None]


#: «Локалізація патологічного процесу - ліве плече».  The site runs to the end
#: of the line, so nothing after it can make the engine give it back.
#: The site starts at the first non-blank after the dash, so the gap and the
#: site never compete for a blank; only a line that ends in blanks makes the
#: site the last of them, as «\s*(.+)$» would.
_US_LESION_SITE = re.compile(r"Локалізація патологічного процесу\s*[-–]\s*(?P<site>\S.*+|[^\S\n])$")


def _us_soft_tissue(flat: str, lines: list[str], page_number: int) -> list[ParsedObservation]:
    """A soft-tissue lesion's two diameters, filed under the site the page names.

    «утвір ... розміром 9.2 * 7.1мм» (Expert), «утворення розмірами
    9,4х4,6мм» (Veselka).  The site goes in ``specimen`` so two lesions in
    different places never share one trend.  The depth beside it is not read:
    Veselka printed it «1,3 м», a unit no depth under the skin can have.
    """
    found = re.search(rf"(?:утвір|утворення)(?:(?!\.\s).){{0,200}}?розмір\w*\s*{_US_PAIR}", flat)
    if not found:
        return []
    site = None
    for line in lines:
        located = _US_LESION_SITE.match(line)
        located = located or re.search(r"В ділянці\s*['‘’]?інтересу['‘’]?\s*[﴾(](?P<site>[^﴿)]+)[﴿)]", line)
        if located:
            site = collapse_space(located.group("site")).strip(" .,")
            break
    return _us_pair("Soft tissue lesion largest diameter", "Soft tissue lesion smaller diameter", found, page_number, specimen=site)


#: Antibiotics an antibiogram in this record prints, plus the EUCAST agents the
#: same laboratories test, in their Ukrainian spelling.  A susceptibility row
#: is accepted only under one of these names: the culture reports arrive as
#: pictures, and OCR read «Іміпенем» as «ImineHem» -- which then became an
#: antibiotic of its own, with its own trend page.  A name within OCR distance
#: of a known one is filed under it; anything else goes to review.
KNOWN_ANTIBIOTICS = (
    "Азитроміцин", "Азтреонам", "Амікацин", "Амоксицилін", "Амоксицилін-клавуланова кислота",
    "Ампіцилін", "Ампіцилін-сульбактам", "Бензилпеніцилін", "Ванкоміцин", "Гентаміцин",
    "Даптоміцин", "Доксициклін", "Доріпенем", "Еритроміцин", "Ертапенем", "Іміпенем", "Кларитроміцин",
    "Кліндаміцин", "Колістин", "Левофлоксацин", "Лінезолід", "Меропенем", "Міноциклін",
    "Моксифлоксацин", "Нетилміцин", "Нітрофурантоїн", "Норфлоксацин", "Оксацилін",
    "Офлоксацин", "Піперацилін", "Піперацилін-тазобактам", "Рифампіцин", "Рокситроміцин",
    "Тейкопланін", "Тетрациклін", "Тигециклін", "Тобраміцин", "Триметоприм-сульфаметоксазол",
    "Фосфоміцин", "Фузидова кислота", "Фуразидин", "Хлорамфенікол", "Цефаклор", "Цефазолін",
    "Цефалексин", "Цефепім", "Цефокситин", "Цефіксим", "Цефоперазон", "Цефоперазон-сульбактам",
    "Цефотаксим", "Цефподоксим", "Цефтазидим", "Цефтазидим-авібактам", "Цефтазидим-авіабактам",
    "Цефтаролін", "Цефтолозан-тазобактам", "Цефтріаксон", "Цефуроксим", "Ципрофлоксацин",
)

#: Latin letters a Cyrillic word is read as.  «ImineHem» is «Іміпенем» seen
#: through these: І→I, м→m, п→n, н→H.
_TO_SHAPE = str.maketrans(
    "аАвВеЕіІїкКмМнНоОпПрРсСтТуУхХиИ",
    "aABBeEiIikKmMHHoOnnpPcCTTyYxXuU",
)


def known_antibiotic(name: str) -> str | None:
    """The antibiotic a printed (or OCR-read) name refers to, or None."""
    from difflib import SequenceMatcher

    folded = collapse_space(name).casefold()
    for known in KNOWN_ANTIBIOTICS:
        if known.casefold() == folded:
            return known
    shape = folded.translate(_TO_SHAPE).casefold()
    scored = sorted(
        (SequenceMatcher(None, shape, known.casefold().translate(_TO_SHAPE).casefold()).ratio(), known)
        for known in KNOWN_ANTIBIOTICS
    )
    ratio, known = scored[-1]
    return known if ratio >= 0.85 else None


def _review_antibiotics(
    observations: list[ParsedObservation], page_number: int, issues: list[ParseIssue] | None
) -> list[ParsedObservation]:
    kept = []
    for item in observations:
        if not (item.value_text and re.fullmatch(rf"(?:{SUSCEPTIBILITY_VERDICT})(?:,.*)?", item.value_text, re.I)):
            kept.append(item)
            continue
        known = known_antibiotic(item.raw_name)
        if known is None:
            if issues is not None:
                issues.append(ParseIssue(page_number, "unknown_antibiotic", item.raw_name, item.evidence_text))
            continue
        if known.casefold() != collapse_space(item.raw_name).casefold():
            item = replace(item, raw_name=known, confidence=min(item.confidence, 0.8))
        kept.append(item)
    return kept


#: Reference-column lines that end a block: method, reagent and analyser
#: notes, notes on how the limits were set, the page footer.
_BLOCK_END = re.compile(
    r"^(?:Метод|Реагент|Аналізатор|Виконано|Цільові\s+рівні|Примітка|Результати\s+лаборатор|Обробка|Стор\.|"
    # Anti-Müllerian hormone: «Референтні межі данного аналізу відповідають 5-му
    # – 95-му процентилю» and «Довідково: Референтні межі для жінок з СПКЯ: 2.41
    # - 17.1» say where the limits come from and give another population's
    # interval -- neither is this row's reference.
    r"Референтні\s+межі|Довідково)",
    re.I,
)
#: A line of a reference block that says how the value was measured
#: («Безціанидовий SLS-метод», «Гідродинамічне фокусування з імпедансним
#: методом», «Лейкоцити визначаються за активністю лейкоцитестерази.»,
#: «Виконано на аналізаторі ...»), not what is normal.  Shared with the lab
#: record reader, whose reference lines carry the same notes.
METHOD_NOTE_RE = re.compile(
    r"метод|аналізатор|реагент|тест-систем|обладнан|^\s*виконано|визнача\w*ся\s+за\b|визначенн|фокусуванн",
    re.I,
)
_METHOD_INTERVAL_RE = re.compile(r"\d\s*[-–]\s*\d|[<>≤≥]\s*\d|\bдо\s+\d")


def method_note(line: str) -> bool:
    """A reference line that names a method, reagent or analyser and gives no interval."""
    return bool(METHOD_NOTE_RE.search(line)) and not _METHOD_INTERVAL_RE.search(line)


#: A line opening with an asterisk is either a citation («*Згідно наданих
#: рекомендацій Roehrl et al.,», «**Враховуючи рекомендації ...») or a band the
#: citation refers to («*Діти: <2 років: ≤0.4», «**Вагітні жінки:»).  A
#: population word or a «label:» says which.
_FOOTNOTE = re.compile(r"^\*+\s*(?!\S[^:]{0,40}:)")
_BAND_START = re.compile(
    r"^\**\s*(?:Діти|Дорослі|Чоловіки|Жінки|Новонар|Вагітн|[IІ]{1,3}\s+триместр|[<>≤≥]?\s*\d+\s*[-–]?\s*\d*\s*(?:рок|років|міс|дн|тиж))",
    re.I,
)


def synevo_reference_blocks(words: list) -> dict[str, str]:
    """Every result row's whole printed reference block, keyed by its value line.

    Synevo prints one row's reference as a column of bands under the value
    line -- «Діти: <1 року: 3.3 - 4.9» / «1-6 років: …» / … / «Дорослі:» /
    «Чоловіки: 4.0 - 5.0» / «Жінки: 3.7 - 4.7» -- and the text passes read one
    line, so every such row was stored with its first band only: a child's
    interval, which a 33-year-old man was then told did not apply to him,
    while the band that did sat four lines lower.  The red count he was
    flagged on by the laboratory showed green.

    Read by column, the block is every reference-column line from the value
    line down to whichever comes first: the next result row, a line with
    nothing in the reference column (a section heading), or a method or
    note line.  A citation footnote («*Згідно наданих рекомендацій ...») is
    skipped with its continuation lines, and the block goes on at the next
    band after it.  The name column's wrapped tail («еритроцитів (ШОЕ, ESR)»)
    and the unit's («клітин/л») sit on the same lines and are simply not in
    the column.
    """
    lines = _word_lines(words)
    columns = _synevo_columns(lines)
    if columns is None:
        return {}
    value_from, unit_from, _reference_from = columns
    blocks: dict[str, str] = {}
    for index, line in enumerate(lines):
        if any(value_from <= word[0] < unit_from for word in line):
            blocks[collapse_space(" ".join(word[3] for word in line))] = _synevo_block(lines, index, columns)
    return blocks


def _synevo_block(lines: list, index: int, columns: tuple[float, float, float]) -> str:
    """The reference block that starts on the value line ``lines[index]``.

    Every line of the block is kept, words and all: the coagulation panel's
    INR prints its interval under a sentence («Згідно з рекомендаціями
    міжнародних протоколів ... Не приймають антикоагулянтні препарати: 0.8 –
    1.2»), homocysteine its second set of bands under «Для людей з додатковим
    споживанням фолатів:», a genotype its risk lines («Гетерозиготне носійство
    – ризик»).  Stopping at the first line without a number kept a fragment of
    the sentence and none of the intervals.
    """
    value_from, unit_from, reference_from = columns
    parts = [" ".join(word[3] for word in lines[index] if word[0] >= reference_from)]
    in_footnote = False
    for following in lines[index + 1 : index + 40]:
        if any(value_from <= word[0] < unit_from for word in following):
            break
        reference = collapse_space(" ".join(word[3] for word in following if word[0] >= reference_from))
        if not reference or _BLOCK_END.match(reference) or method_note(reference):
            break
        if _FOOTNOTE.match(reference):
            in_footnote = True
            continue
        if in_footnote and not _BAND_START.match(reference):
            continue
        in_footnote = False
        parts.append(reference)
    return collapse_space(" ".join(parts))


def _with_reference(item: ParsedObservation, reference: str | None) -> ParsedObservation:
    limits = reference_limits(reference)
    return cast(ParsedObservation, replace(
        item, reference_text=reference, reference_low=limits.low, reference_high=limits.high,
        reference_low_inclusive=limits.low_inclusive, reference_high_inclusive=limits.high_inclusive,
    ))


def _eskulab_page(
    text: str, page_number: int, words: list, issues: list[ParseIssue] | None
) -> list[ParsedObservation] | None:
    """The rows of an EskuLab page its column parser owns, or None.

    The column parser owns any page it read rows from, and any page that
    draws a table even when it read none.  That second half matters:
    falling back to the shared passes on an empty result is what put
    «діти: 3.33 - 5.55» in the record as an analyte named "children" --
    a page whose panels were all skipped read as "no table here" and went
    straight to the parser that cannot see columns at all.  A page with
    neither rows nor a header is genuinely something else (the
    quantitative-PCR blocks, the microbiology narrative) and falls
    through to the passes that read those.
    """
    table = (
        parse_eskulab(words, page_number)
        + parse_eskulab_stool(words, page_number)
        + parse_eskulab_culture(words, page_number)
        + parse_eskulab_express(words, page_number)
        + parse_partner_coprogram(words, page_number)
    )
    if table or eskulab_table_page(words):
        return _review_antibiotics(
            table + parse_pcr_sections(text, page_number), page_number, issues
        )
    return None


def _expert_text_passes(text: str, page_number: int) -> list[ParsedObservation]:
    """An Expert Hospital page read without its word positions."""
    observations = parse_expert_page(text, page_number) + parse_unit_rows(text, page_number)
    wrapped_hba1c = parse_wrapped_hba1c(text, page_number)
    if wrapped_hba1c:
        observations = [
            item for item in observations if "глікований гемоглобін" not in item.raw_name.casefold()
        ] + wrapped_hba1c
    return observations


def _shared_passes(
    vendor: str, text: str, page_number: int, words: list | None, issues: list[ParseIssue] | None
) -> list[ParsedObservation]:
    observations: list[ParsedObservation] = []
    expert_table = (
        parse_expert_table(words, page_number) if vendor == "Expert Hospital" and words else None
    )
    if expert_table is not None:
        # The column reader owns every row of a page whose table it found;
        # the flat passes below would read the same wrapped cells as
        # fragments.
        observations.extend(expert_table)
    elif vendor == "Expert Hospital":
        observations.extend(_expert_text_passes(text, page_number))
    else:
        observations.extend(parse_unit_rows(text, page_number))
        observations.extend(parse_unitless_numeric_rows(text, page_number))
    if expert_table is None:
        observations.extend(parse_categorical_rows(text, page_number))
    observations.extend(parse_pcr_sections(text, page_number))
    observations.extend(parse_hla_b27(text, page_number))
    observations.extend(parse_autoimmune_panel(text, page_number, issues))
    return observations


def _with_culture_material(observations: list[ParsedObservation], text: str) -> list[ParsedObservation]:
    """Every row without a specimen takes the one a microbiology page prints.

    Expert prints the specimen above the results («Матеріал: мазок із
    зіву») rather than in the title an EskuLab culture carries it in, so
    every row on the page takes it from that line.
    """
    material = re.search(r"^\s*Матеріал\s*:\s*(?P<specimen>[^\n:]{3,60}?)\s*$", text, re.M | re.I)
    if not material:
        return observations
    specimen = collapse_space(material.group("specimen")).casefold()
    return [item if item.specimen else replace(item, specimen=specimen) for item in observations]


def _sediment_text(text: str) -> str:
    """The microscopy section of a Synevo page, as one line, its closing line included.

    The closing line is part of the section here because the categorical
    pass also reads a row glued to the line after it («Сперматозоїди не
    виявлені ... Примітка:»).
    """
    lines = [collapse_space(line) for line in text.splitlines() if collapse_space(line)]
    start = next((i for i, line in enumerate(lines) if SYNEVO_SEDIMENT_HEADING.match(line)), None)
    section: list[str] = []
    for line in lines[start:] if start is not None else []:
        section.append(line)
        if len(section) > 1 and SYNEVO_SEDIMENT_END.match(line):
            break
    return " ".join(section)


def _synevo_by_column(
    observations: list[ParsedObservation], text: str, words: list, page_number: int
) -> list[ParsedObservation]:
    """Synevo rows given their whole reference block, and the microscopy read by column."""
    blocks = synevo_reference_blocks(words)
    observations = [
        _with_reference(item, blocks[item.evidence_text])
        if item.evidence_text in blocks
        and len(blocks[item.evidence_text]) > len(item.reference_text or "")
        and blocks[item.evidence_text].startswith(item.reference_text or "")
        else item
        for item in observations
    ]
    # The column reader owns every unit-less row it read: a flat reading of the
    # same printed line is the one that swapped a wrapped result for its norm.
    unitless = parse_synevo_unitless(words, page_number)
    if unitless:
        row_texts = [item.evidence_text for item in unitless]
        observations = [
            item for item in observations
            if not any(row.startswith(item.evidence_text) or item.evidence_text.startswith(row) for row in row_texts)
        ] + unitless
    sediment = parse_synevo_sediment(words, page_number)
    if sediment:
        # The column reader owns the microscopy section: whatever the flat
        # passes read inside it is replaced, so a row is neither lost to
        # them nor read twice.
        section_text = _sediment_text(text)
        observations = [item for item in observations if item.evidence_text not in section_text] + sediment
    return _synevo_rows_in_place(observations, words)


#: The order's package heading, «Пакет №183 (CHECK-UP. ... + звіт з описом /
#: лабораторних показників)»: its «+ звіт з описом» sits in the result column
#: and the column header «Індикатор зони підвищеної уваги» in the reference
#: one, so it was stored as a result.  A package is never an analyte.
_SYNEVO_PACKAGE = re.compile(r"^Пакет\s*№\s*\d+", re.I)
#: The specimen Synevo prints in front of one row's name: «Аналіз крові:
#: Швидкість осідання еритроцитів (ШОЕ, ESR)».  It is the material, not part
#: of the analyte's name; left on, the ESR filed under a name no other
#: report uses.
SPECIMEN_LABEL = re.compile(r"^Аналіз\s+крові\s*:\s*(?=\S)", re.I)
#: A gene and its polymorphism, as a PCR heading names them: «ПЛР. Фолатний
#: цикл. MTHFR (1298 A>C)», «PAI-1 (-675 5G>4G)».
_GENE_VARIANT = re.compile(
    r"\b(?P<gene>[A-Z][A-Z0-9-]{1,9})\s*\(\s*(?P<variant>-?\d+\s*\d*[ACGT]\s*>\s*\d*[ACGT])\s*\)"
)
#: A row name that names no analyte on its own -- one step of a test whose
#: name is the heading above it: «Вовчаковий антикоагулянт» / «Скринінговий
#: тест 37.9 сек» / «Підтверджуючий тест 34.3 сек».
_SUBTEST_NAME = re.compile(r"^(?:скринінгов\w*|підтверджуюч\w*)\s+тест\w*$", re.I)


def without_specimen_label(name: str) -> str:
    """«Аналіз крові: Швидкість осідання ...» -> «Швидкість осідання ...»."""
    return SPECIMEN_LABEL.sub("", name)


def _synevo_rows_in_place(observations: list[ParsedObservation], words: list) -> list[ParsedObservation]:
    """What only the page around a row says about it.

    * a package heading read as a row is dropped;
    * the specimen label in front of a name is taken off;
    * a unit whose tail wrapped onto the next line («10^9» / «клітин/л») is
      joined again;
    * a row named by the heading above it takes that heading: the gene and
      variant of a genotype (MTHFR 1298 A>C and 677 C>T were one name, so two
      different tests merged into one series), the test a «Скринінговий тест»
      belongs to.
    """
    lines = _word_lines(words)
    columns = _synevo_columns(lines)
    if columns is None:
        return observations
    texts = [collapse_space(" ".join(word[3] for word in line)) for line in lines]
    finished: list[ParsedObservation] = []
    claimed: set[int] = set()
    for item in observations:
        if _SYNEVO_PACKAGE.match(item.raw_name):
            continue
        changes: dict[str, object] = {}
        name = without_specimen_label(item.raw_name)
        # Two rows can print the same line (both MTHFR genotypes read
        # «Метілентетрагідрофолатредуктаза Мутація відсутня ...»): each takes
        # the first such line not yet taken, in page order.
        index = next(
            (
                number for number, text in enumerate(texts)
                if number not in claimed and len(text) > 4 and item.evidence_text.startswith(text)
            ),
            None,
        )
        if index is not None:
            claimed.add(index)
            heading = _synevo_heading_above(lines, texts, index, columns[0])
            variant = _GENE_VARIANT.search(heading or "")
            if variant:
                # «Метілентетрагідрофолатредуктаза (MTHFR 677 C>T)»: the enzyme as
                # printed, then the gene and variant that tell the two MTHFR tests apart.
                name = f"{name} ({variant['gene']} {collapse_space(variant['variant'])})"
            elif heading and _SUBTEST_NAME.match(name):
                name = f"{heading}, {name[:1].lower()}{name[1:]}"
            tail = _wrapped_unit_tail(item.unit_raw, lines, index, columns)
            if tail:
                changes["unit_raw"] = f"{item.unit_raw} {tail}"
        if name != item.raw_name:
            changes["raw_name"] = name
        finished.append(cast(ParsedObservation, replace(item, **changes)) if changes else item)
    return finished


def _synevo_heading_above(lines: list, texts: list[str], index: int, value_from: float) -> str | None:
    """The nearest line above row ``index`` that is a heading: words in the name column only, opening
    on a capital, and not the wrapped end of a name above it."""
    for above in range(index - 1, -1, -1):
        line = lines[above]
        if any(word[0] >= value_from for word in line):
            row_name = " ".join(word[3] for word in line if word[0] < value_from)
            if row_name and not _SUBTEST_NAME.match(row_name):
                return None  # another result row: no heading between it and this one
            continue  # a reference or method line, or a sibling step of the same test
        text = texts[above]
        if _RESULT_HEADING in text or not text[:1].isupper():
            return None
        if above > 0 and _unclosed_bracket(" ".join(word[3] for word in lines[above - 1] if word[0] < value_from)):
            return None
        return text
    return None


#: The second line of a count's unit: Synevo prints «10^9» beside the value
#: and «клітин/л» under it.
_UNIT_TAIL = re.compile(r"^клітин/л$", re.I)


def _wrapped_unit_tail(unit: str | None, lines: list, index: int, columns: tuple[float, float, float]) -> str | None:
    """The unit column's word on the line under row ``index``, when it finishes a «10^n» unit."""
    if not unit or not re.fullmatch(r"10\^\d+", unit) or index + 1 >= len(lines):
        return None
    _value_from, unit_from, reference_from = columns
    below = [word[3] for word in lines[index + 1] if unit_from <= word[0] < reference_from]
    tail = " ".join(below)
    return tail if _UNIT_TAIL.match(tail) else None


#: The page footer of Synevo's illustrated companion report («звіт з описом
#: лабораторних показників»): «<patient> / Пакет № <n> (...) / <date> /
#: cтор. <page>», the «c» Latin.  That PDF re-presents the results of a report the
#: record already holds, as one card per analyte and then two summary tables
#: printed side by side.  Read as text the tables interleave: the patient's
#: name became part of an analyte label, free T4 was stored under «HBsAg», and
#: one row's reference took the next column's tumour marker.  Nothing on it is
#: a reading the main report lacks, so none of it is read.
#: The ParseIssue kind that says a page is such a companion: the pipeline
#: then explains the empty document instead of reporting missed results.
COMPANION_SUMMARY = "companion_summary"
SYNEVO_SUMMARY_FOOTER = re.compile(
    r"/\s*Пакет\s*№\s*\d+[^/\n]*/\s*\d{2}\.\d{2}\.\d{4}\s*/\s*[cс]тор\.\s*\d+\s*$", re.M
)


def parse_source_text(
    vendor: str,
    clinical_type: str,
    text: str,
    page_number: int,
    words: list | None = None,
    issues: list[ParseIssue] | None = None,
) -> list[ParsedObservation]:
    if SYNEVO_SUMMARY_FOOTER.search(text):
        if issues is not None:
            issues.append(ParseIssue(page_number, COMPANION_SUMMARY, "", ""))
        return []
    st_paraskeva = parse_st_paraskeva(text, page_number)
    if st_paraskeva:
        return st_paraskeva
    # Checked before the type: the POLYCHECK panel prints its field labels as
    # pictures, so the same page is typed «allergy» or «laboratory» depending
    # on what the classifier can read, and is the same panel either way.
    polycheck = parse_polycheck_panel(text, page_number)
    if polycheck:
        return polycheck
    if clinical_type == "allergy":
        return parse_allergy_panel(text, page_number, words)
    # EskuLab draws a table, and the generic passes read the parts of it that
    # wrap -- the specimen under the name, the reference cell under the row --
    # as more results.  Its own parser reads the columns instead, so where it
    # recognises the page it replaces every shared pass rather than adding to
    # them.  It returns nothing for the layouts it does not draw as a table
    # (quantitative PCR, microbiology), and those fall through unchanged.
    if vendor == "EskuLab" and words:
        eskulab = _eskulab_page(text, page_number, words, issues)
        if eskulab is not None:
            return eskulab
    observations = _shared_passes(vendor, text, page_number, words, issues)
    if clinical_type == "microbiology":
        observations.extend(parse_microbiology_narrative(text, page_number))
        observations = _with_culture_material(observations, text)
    observations = _review_antibiotics(observations, page_number, issues)
    if vendor == "Synevo" and words:
        observations = _synevo_by_column(observations, text, words, page_number)
    return observations




#: One tier of a dipstick scale, either way round: «+=25», «+++≥100» (Expert)
#: or «25 = +», «500 = +++» (EskuLab).  «+-» is the trace tier, which is not
#: a positive one, and is excluded by refusing a plus run that touches a minus.
_PLUS_TIER = re.compile(
    r"(?<![+\-\d])(?P<plus>\+{1,4})(?![+\-])\s*[=≥]\s*(?P<num>\d+(?:[.,]\d+)?)"
    r"|(?P<num2>\d+(?:[.,]\d+)?)\s*=\s*(?P<plus2>\+{1,4})(?![+\-])"
)
_NEGATIVE_WORDS = re.compile(r"не\s+виявлен\w*|негативн\w*|в\s+нормі|нормальн\w*|відсутн\w*", re.I)
_POSITIVE_TEXT = re.compile(r"^(?:\+{1,4}|виявлен\w*|позитивн\w*(?:\s*\(\+\))?)$", re.I)


def dipstick_threshold(reference: str | None) -> float | None:
    """The concentration a dipstick scale calls «+», or None if it is no such scale.

    «не виявлені / 25 = + / 75 = ++ / 500 = +++» prints its own cut-off: 25
    leukocytes/µL is the first positive tier.  Read as text, the row had no
    bounds at all and a positive pad was shown as unjudged.
    """
    if not reference:
        return None
    for tier in _PLUS_TIER.finditer(reference):
        plus = tier.group("plus") or tier.group("plus2")
        if len(plus) == 1:
            return parse_decimal(tier.group("num") or tier.group("num2"))
    return None


_SCALE_LABEL = {
    "within_vendor_range": r"негатив\w*|negative",
    "borderline": r"сумнівн\w*|сіра\s+зона|equivocal|borderline",
    "positive": r"(?:низько\s+|високо\s+)?позитивн\w*|positive",
}
_SCALE_LIMIT = r"[<>≤≥]?\s*\d+(?:\.\d+)?(?:\s*[-–—]\s*[<≤]?\s*\d+(?:\.\d+)?)?"
_ANY_SCALE_LABEL = "|".join(f"(?P<{key}>{pattern})" for key, pattern in _SCALE_LABEL.items())
_LABEL_FIRST = re.compile(
    rf"(?:{_ANY_SCALE_LABEL})\s*(?:результат\w*)?\s*(?:\([^)]*\))?\s*[:\-–]?\s*(?P<limit>{_SCALE_LIMIT})", re.I
)
_LIMIT_FIRST = re.compile(rf"(?P<limit>{_SCALE_LIMIT})\s*[-–—:]?\s*(?:{_ANY_SCALE_LABEL})", re.I)


def _scale_bands(text: str) -> list[tuple[str, ReferenceLimits]]:
    """(reading, limits) for each named band of a scale, in printed order."""
    first_label = re.search("|".join(_SCALE_LABEL.values()), text, re.I)
    first_number = re.search(r"\d", text)
    if not first_label or not first_number:
        return []
    pattern = _LIMIT_FIRST if first_number.start() < first_label.start() else _LABEL_FIRST
    return [
        (next(key for key in _SCALE_LABEL if found.group(key)), reference_limits(found.group("limit")))
        for found in pattern.finditer(text)
    ]


def scale_interpretation(value: float, reference: str | None) -> str | None:
    """Which named band of a negative / equivocal / positive scale holds the value.

    ANA prints «Негативний (-):<1.0 Сумнівний: 1.0-1.2 Позитивний (+):>1.2»
    and HBsAg «<0.9 - негативний результат 0.9 - <1.0 - сіра зона ≥1.0 -
    позитивний результат».  The bands are the laboratory's reading; a value in
    the equivocal zone is "borderline", not "high".  Needs two named bands, and
    returns None when the value sits in none of them.
    """
    if not reference:
        return None
    bands = _scale_bands(reference.replace(",", "."))
    if len(bands) < 2:
        return None
    for reading, limits in bands:
        if limits.low is None and limits.high is None:
            continue
        above = limits.low is None or value > limits.low or (limits.low_inclusive and value == limits.low)
        below = limits.high is None or value < limits.high or (limits.high_inclusive and value == limits.high)
        if above and below:
            return reading
    return None


def _demographic_limits(
    reference: str, age_years: int | None, sex: str | None
) -> ReferenceLimits | None:
    """This patient's band of a block printed for several populations."""
    from ..health import applicable_band, applicable_reference_bounds

    band = applicable_band(reference, age_years, sex)
    if band is not None:
        limits = reference_limits(band.rsplit(":", 1)[-1])
        if limits.low is not None or limits.high is not None:
            return limits
    low, high = applicable_reference_bounds(reference, age_years, sex)
    if low is None and high is None:
        return None
    text = reference.replace(",", ".")

    def strict(number: float | None, signs: str) -> bool:
        if number is None:
            return False
        token = re.escape(f"{number:g}")
        return bool(re.search(rf"[{signs}]\s*{token}(?:\.0+)?(?![\d.])", text))

    return ReferenceLimits(low, high, not strict(low, ">"), not strict(high, "<"))


#: A blood-group value: Latin and Cyrillic letters and numerals both occur
#: («А (II)», «А(ІІ)», «0(I)»), so one result read off two reports was two
#: different values.
_BLOOD_GROUP_NAME = re.compile(r"^(?:група\s+крові|резус)", re.I)
_TO_LATIN_GROUP = str.maketrans("АВОІ", "ABOI")

#: The specimen a printed name carries in brackets or behind a comma.
_NAME_SPECIMEN = re.compile(
    r"(?:\(|,\s*)(?P<specimen>сироватка\s+крові|сироватка|цільна\s+кров|плазма(?:\s+крові)?|сеча|кал)\)?\s*$", re.I
)


def _printed_token(item: ParsedObservation) -> str | None:
    if item.value_numeric is None:
        return None
    if item.value_printed and (
        parse_decimal(item.value_printed) == item.value_numeric
        # A colony count as printed, «1.0 x 10^5»: no decimal token equals it.
        or POWER_NOTATION_RE.search(item.value_printed)
    ):
        return item.value_printed
    evidence = item.evidence_text or ""
    start = len(item.raw_name) if evidence.startswith(item.raw_name) else 0
    for token in re.finditer(r"(?<![\w.,:/^])(\d+(?:[.,]\d+)?)(?![\d^])", evidence[start:]):
        if parse_decimal(token.group(1)) == item.value_numeric:
            return token.group(1)
    return None


def _blood_group_changes(item: ParsedObservation) -> tuple[dict[str, object], str | None]:
    """(changes, reference) for a blood-group row, whose column prints every
    possible answer -- which is not a reference."""
    if not _BLOOD_GROUP_NAME.match(item.raw_name):
        return {}, item.reference_text
    changes: dict[str, object] = {"reference_text": None}
    if item.value_text:
        changes["value_text"] = re.sub(r"\s+(?=\()", "", item.value_text.translate(_TO_LATIN_GROUP))
    return changes, None


def _printed_inclusivity(item: ParsedObservation, reference: str | None) -> ReferenceLimits:
    """The row's bounds, inclusive or not as the printed comparator says."""
    bounds = ReferenceLimits(
        item.reference_low, item.reference_high, item.reference_low_inclusive, item.reference_high_inclusive
    )
    limits = reference_limits(reference)
    if (limits.low, limits.high) == (bounds.low, bounds.high) and (bounds.low is not None or bounds.high is not None):
        return ReferenceLimits(bounds.low, bounds.high, limits.low_inclusive, limits.high_inclusive)
    return bounds


def _dipstick_reading(
    item: ParsedObservation, reference: str | None, bounds: ReferenceLimits, reading: str | None
) -> tuple[ReferenceLimits, str | None]:
    """A «+» scale's cut-off as an exclusive upper bound, and the pad's reading."""
    threshold = dipstick_threshold(reference)
    if threshold is None:
        return bounds, reading
    if item.value_numeric is not None:
        return (
            ReferenceLimits(None, threshold, True, False),
            reading or ("high" if item.value_numeric >= threshold else "within_vendor_range"),
        )
    if item.value_text and _POSITIVE_TEXT.match(item.value_text.strip()):
        return bounds, reading or "positive"
    return bounds, reading


def _patient_bounds(
    item: ParsedObservation, reference: str | None, bounds: ReferenceLimits, age_years: int | None, sex: str | None
) -> ReferenceLimits:
    """This patient's bounds, for a numeric row whose printed block names several populations."""
    if item.value_numeric is None or bounds.low is not None or bounds.high is not None or not reference:
        return bounds
    if item.sex_bands and sex in item.sex_bands:
        low, high = item.sex_bands[sex]
        return ReferenceLimits(low, high, bounds.low_inclusive, bounds.high_inclusive)
    if demographic_reference(reference) and (age_years is not None or sex):
        patient = _demographic_limits(reference, age_years, sex)
        if patient is not None:
            return patient
    return bounds


def _numeric_reading(item: ParsedObservation, reference: str | None, bounds: ReferenceLimits) -> str | None:
    """The reading a named scale gives a number, or the one a strict limit does."""
    value = item.value_numeric
    reading = scale_interpretation(value, reference)
    if reading is not None:
        return reading
    # The case a plain «>» comparison gets wrong: a value exactly on a
    # strict limit is outside it -- unless the value is itself printed below
    # (or above) that number: carnosine «<1.0» against «<1» is inside.
    if (bounds.high is not None and not bounds.high_inclusive and value == bounds.high
            and item.comparator not in {"<", "≤"}):
        return "high"
    if (bounds.low is not None and not bounds.low_inclusive and value == bounds.low
            and item.comparator not in {">", "≥"}):
        return "low"
    return None


def finalise(
    item: ParsedObservation, age_years: int | None = None, sex: str | None = None
) -> ParsedObservation:
    """Everything decided once the row is read, the same way for every layout.

    * bound inclusivity from the printed comparator (DOCA-09);
    * a dipstick «+» scale becomes an exclusive upper bound at its first
      positive tier, and the laboratory's reading of the pad (DOCA-11);
    * a qualitative «+» against a «не виявлено» norm is positive (DOCC-05);
    * a named negative/equivocal/positive scale gives the band's reading;
    * this patient's band of a demographic block, when the caller knows the
      patient (DOCB-02);
    * a text result carries no unit (CLIN-30), except the unit of the printed
      «+» scale a dipstick pad was read on;
    * the printed numeric token, and the specimen named in the label.
    """
    changes, reference = _blood_group_changes(item)
    bounds = _printed_inclusivity(item, reference)
    bounds, reading = _dipstick_reading(item, reference, bounds, item.vendor_interpretation)
    if reading is None and item.value_numeric is None and item.value_text and reference:
        if _POSITIVE_TEXT.match(item.value_text.strip()) and _NEGATIVE_WORDS.search(reference):
            reading = "positive"
    bounds = _patient_bounds(item, reference, bounds, age_years, sex)
    if reading is None and item.value_numeric is not None:
        reading = _numeric_reading(item, reference, bounds)
    changes.update(
        reference_low=bounds.low, reference_high=bounds.high,
        reference_low_inclusive=bounds.low_inclusive, reference_high_inclusive=bounds.high_inclusive,
        vendor_interpretation=reading, value_printed=_printed_token(item),
    )
    # A pad read on a printed concentration scale keeps that scale's unit:
    # «не виявлені» beside «мг/дл» and «10 = + 30 = ++» is a position on a
    # mg/dL scale.  Dropped, the store filled in the concept's own unit
    # instead, and ketones read on a mg/dL pad were labelled mmol/L.
    on_scale = dipstick_threshold(reference) is not None
    if item.value_numeric is None and item.unit_raw and not on_scale and not re.search(r"\d", item.value_text or ""):
        changes["unit_raw"] = None
    if item.specimen is None:
        found = _NAME_SPECIMEN.search(item.raw_name)
        if found:
            changes["specimen"] = collapse_space(found.group("specimen"))
    return cast(ParsedObservation, replace(item, **changes))


# --- SILAB prints read from a scan ------------------------------------------
#
# The partner clinic «Мати та дитина» (ТОВ «НЕОМЕД 2007») hands its results out
# of SILAB, its laboratory information system, and people keep them as browser
# prints of the clinic portal: one screenshot per page, nothing but OCR to read.
# OCR of those screenshots drops strokes and whole cells: «Ступінь чистоти III»
# arrives as «І», «tt» or «Il», «33 генотип» as «38», «в п/з» as «вп/з» or
# «n/s», a unit as «т».  So this reader knows the form instead of guessing at
# it: every row is a printed name it knows, in the section that prints it, with
# a value, unit and reference each of the shape that row prints.  A row that
# does not read exactly so is left out -- review reports it missing, which is
# true, where a reading of the noise would put a wrong value in the record.

SILAB_PRINT = re.compile(r"системи\s+SILAB|mdclinics|НЕОМЕД|NEOMED", re.I)
#: Synevo's own copy of the same order prints its rows in no fixed order, so a
#: smear row there cannot be told to be vaginal or cervical from where it sits.
SILAB_PORTAL_COPY = re.compile(r"Дата забору матеріалу", re.I)

#: «не виявлені»; OCR reads the lower-case «не» as the Latin capitals «He»,
#: which `_silab_clean` folds to «Не», so the case is put back by `_silab_case`.
_S_NEG = r"[Нн]е виявлен(?:і|а|о|ий)"
_S_QTY = r"[ву] (?:помірній|великій|невеликій) кількості"
_S_FIELD = r"\d{1,3}-\d{1,3} в ?п/з\.?"
_S_RANGE = r"\d{1,3}(?:[.,]\d{1,3})? ?- ?\d{1,3}(?:[.,]\d{1,3})?"
#: Junk OCR leaves in front of a cell: the table rule, an opening quote, a stray bracket.
_S_JUNK = r"[\s|'‘’\"«(*]*"

#: The section headings, as OCR still reads them, and the key of their rows.
_SILAB_SECTIONS = (
    (re.compile(r"^Аналіз сечі(?: загальний|:? Мікроскопія осаду)", re.I), "urine"),
    (re.compile(r"^Аналіз \S{1,4} мазка на мікрофлору", re.I), "smear"),
    (re.compile(r"^Цитологія на атипові клітини", re.I), "cytology"),
    (re.compile(r"^ПЛР\. ВПЛ \S{3} \(генотипування, якісне", re.I), "hpv"),
    (re.compile(r"^ПАП.тест методом рідинної цитології", re.I), "pap"),
    (re.compile(r"^ПЛР\b|^Цитологічні дослідження|^Загальна клініка|^Бакпосів|^\d+\. Панель", re.I), None),
)
#: Where a row's printed cells stop: the page footer and the method notes under a row.
_SILAB_END = re.compile(r"^(?:Результати (?:лаборатор|пабор)|Обробка|Стор|Примітка|Дата друку|Показник)", re.I)
_SILAB_NOTE = re.compile(
    r"^\(?(?:Метод|Реагенти|Аналізатор|Ан[ап]лізатор|сертифіковані|\S+ визначаються за|активністю|"
    r"лейкоцитестерази|псевдопероксидази)",
    re.I,
)
_SILAB_SITE = re.compile(r"^(?:ТОЧКА|TOUKA)\s*[\dЗ]?\s+(?P<site>URETRA|VAGINA|CERVIX)\b\s*[;:]?\s*(?P<rest>.*)$")
#: The fourteen high-risk genotypes the panel prints, in its order.
SILAB_HPV_GENOTYPES = frozenset({16, 18, 31, 33, 35, 39, 45, 51, 52, 56, 58, 59, 66, 68})


@dataclass(frozen=True)
class _SilabRow:
    """One printed row of the form: its label, and the shape of each cell."""

    name: str
    value: str
    unit: str | None = None
    reference: str | None = None
    #: Plus-tiers of a dipstick scale printed one per line under the row.
    tiers: int = 0
    #: The end of the label, wrapped onto the line under the value.
    name_tail: str | None = None
    #: The value or reference cell may wrap onto lines that match this.
    wrap: str | None = None
    #: A pattern for the label where `name` is not printed verbatim: a
    #: numbered row, a label wrapped or spelt otherwise than the stored name.
    label: str | None = None


def _silab_urine_rows() -> tuple[_SilabRow, ...]:
    simple = (
        "Еритроцити (дисморфізм)", "Клітини ниркового епітелію", "Клітини епітелію сечового міхура",
        "Гіалінові циліндри", "Еритроцитарні циліндри", "Лейкоцитарні циліндри", "Воскоподібні циліндри",
        "Зернисті циліндри", "Епітеліальні циліндри", "Кристали трипельфосфатів", "Кристали оксалату кальцію",
        "Кристали сечової кислоти", "Кристали біурата амонію", "Кристали карбонату кальцію",
        "Кристали білірубіну", "Кристали фосфату кальцію", "Кристали фосфорнокислого вапна", "Аморфні фосфати",
        "Аморфні урати", "Бактерії", "Дріжджеподібні гриби", "Трихомонади", "Сперматозоїди", "Нітрити", "Слиз",
    )
    found = rf"{_S_NEG}|виявлен(?:і|а|о|ий)|\+{{1,4}}|{_S_QTY}"
    return (
        _SilabRow(
            "Колір", r"(?:світло-|темно-|солом'яно-)?жовтий|бурштиновий|безбарвний|червоний|бурий|коричневий",
            reference="від світло-жовтого до жовтого кольору", wrap="кольору",
        ),
        _SilabRow("Прозорість", r"прозора|(?:злегка )?каламутна", reference="прозора"),
        _SilabRow("Відносна щільність", r"1[.,]0\d\d", unit="г/мл", reference=r"1\.0\d\d ?- ?1\.0\d\d"),
        _SilabRow("pH", r"\d(?:[.,]\d)?", reference=r"\d\.\d ?- ?\d\.\d"),
        _SilabRow("Лейкоцити", rf"{_S_NEG}|\d+", unit=r"Leu/[µu]L", reference=_S_NEG, tiers=3),
        _SilabRow("Еритроцити", rf"{_S_NEG}|\d+", unit=r"Ery/[µu]L", reference=_S_NEG, tiers=5),
        _SilabRow("Білок", rf"{_S_NEG}|\d+(?:[.,]\d+)?", unit="г/л", reference=_S_NEG, tiers=4),
        _SilabRow("Глюкоза", rf"{_S_NEG}|\d+(?:[.,]\d+)?", unit="ммоль/л", reference=_S_NEG, tiers=4),
        _SilabRow("Кетонові тіла", rf"{_S_NEG}|\d+(?:[.,]\d+)?", unit="ммоль/л", reference=_S_NEG, tiers=4),
        _SilabRow("Уробіліноген", r"сліди|\d+", unit="мкмоль/л", reference="сліди", tiers=4),
        _SilabRow("Білірубін", rf"{_S_NEG}|\d+", unit="мкмоль/л", reference=_S_NEG, tiers=3),
        # Microscopy: counted per microlitre, which is the unit OCR loses most.
        _SilabRow("Лейкоцити", r"\d+-\d+|<\d+|\d+", unit=r"/[µu]L", reference=r"<\d+"),
        _SilabRow("Еритроцити", r"\d+-\d+|<\d+|\d+", unit=r"/[µu]L", reference=r"<\d+"),
        _SilabRow(
            "Клітини плоского епітелію", rf"{_S_NEG}|поодинокі(?: в препараті)?|\d+-\d+",
            unit=r"/[µu]L", reference=rf"{_S_NEG}, 1-15",
        ),
        _SilabRow(
            "Клітини перехідного епітелію", rf"{_S_NEG}|поодинокі(?: в препараті)?|\d+-\d+",
            unit=r"/[µu]L", reference=rf"{_S_NEG}, 1-5",
        ),
        *(_SilabRow(name, found, reference=_S_NEG) for name in simple),
    )


_SILAB_ROWS: dict[str, tuple[_SilabRow, ...]] = {
    "urine": _silab_urine_rows(),
    "smear": (
        _SilabRow(
            "Лейкоцити",
            rf"{_S_FIELD}|(?:в тяжах слизу(?: майже)? )?вкривають все поле зору|в тяжах слизу- ?\d{{1,3}}-\d{{1,3}}",
        ),
        _SilabRow("Еритроцити", rf"{_S_NEG}|{_S_FIELD}|поодинокі в п/з\.?"),
        _SilabRow("Епітелій", _S_QTY),
        _SilabRow("Слиз", rf"{_S_QTY}|{_S_NEG}"),
        _SilabRow(
            "Флора", rf"(?:дрібні палички|палички|коки) {_S_QTY}", wrap=rf"(?:дрібні палички|палички|коки) {_S_QTY}"
        ),
        _SilabRow("Trichomonas vaginalis", _S_NEG),
        _SilabRow("Дріжджоподібний грибок", rf"{_S_NEG}|(?:міцелій|спори|бластоспори) {_S_QTY}"),
    ),
    "cytology": tuple(
        # A written result wraps over as many lines as it needs; the value
        # pattern, not the wrap, is what keeps noise out.
        _SilabRow(name, value, label=label, wrap=r".+")
        for name, label, value in (
            (
                "Плоский епітелій ({n})", r"Плоский епітелій \((?P<n>\d)\)",
                rf"Клітини {_S_QTY}, розташовані окремо(?:, (?:невеликими )?(?:групами|пластами))*\.",
            ),
            (
                "Залозистий епітелій ({n})", r"Залозистий епітелій \((?P<n>\d)\)",
                rf"Клітини {_S_QTY}, розташовані окремо(?:, (?:невеликими )?(?:групами|пластами))*\.",
            ),
            (
                "Опис морфологічних змін плоского епітелію", r"Опис морфологічних змін плоск\S* епітел\S*",
                r"Ядра поодиноких клітин незначно збільшені\. Реактивні зміни\.|Не виявлені зміни\.",
            ),
            (
                "Опис морфологічних змін залозистого епітелію", r"Опис морфологічних змін залозист\S* епітел\S*",
                r"Ядра поодиноких клітин незначно збільшені\. Реактивні зміни\.|Не виявлені зміни\.",
            ),
            (
                "Клітинні зміни, не пов'язані з неопластичним процесом",
                r"Клітинні зміни, не пов'язані з неопластичним",
                r"Не виявлені зміни\.|Плоскоклітинна метаплазія\.",
            ),
            ("Лейкоцити ({n})", r"Лейкоцити \((?P<n>\d)\)", rf"[ВУ] (?:помірній|великій|невеликій) кількості\."),
            ("Інфекційні агенти", r"Інфекційні агенти", r"Не виявлені\.|Виявлені\."),
            # Synevo's print of the same test calls the conclusion
            # «Цитоморфологічний висновок»; one name keeps both on one concept.
            (
                "Цитоморфологічний висновок", r"Висновок:?|Цитоморфологічний висновок",
                r"Тип [IV]{1,3}\. (?:Запальний тип мазка\.|Запалення\.?)(?: Реактивні зміни клітин плоского епітелію\.)?",
            ),
        )
    ),
    "hpv": (),
    "pap": (
        _SilabRow(
            "Оцінка якості матеріалу/препарату урогенітального зішкрібу", r"Матеріал (?:не)?задовільний",
            label=r"Оцінка якості матеріалу/препарату", name_tail="урогенітального зішкрібу",
        ),
        _SilabRow("Специфічні інфекційні агенти", r"Не виявлені|Виявлені"),
        _SilabRow(
            "Клітинні зміни, не пов'язані з неопластичними процесами", r"Не виявлені|Виявлені",
            label=r"Клітинні зміни, не пов'язані з", name_tail="неопластичними процесами",
        ),
        _SilabRow("Реактивні зміни", r"Запальні \(включаючи репаративні\) виражені|Не виявлені"),
        _SilabRow("Висновок: зміни плаского епітелію", r"NILM, \(тип [IV]{1,3}, запальний тип мазка\)|NILM|Не виявлені"),
        _SilabRow("Висновок: зміни залозистого епітелію", r"Не виявлені"),
    ),
}
#: A roman numeral OCR has not touched: Latin capitals only.  «Il», «tI», a
#: Cyrillic «І» or «ПІ» are what «III» became on these scans, so none of them
#: is read as a grade at all.
_SILAB_GRADE = re.compile(r"^Висновок Ступінь чистоти (?P<grade>I{1,3}|IV)\.?$")
_SILAB_GENOTYPE = re.compile(rf"^(?P<type>\d{{2}}) генотип (?P<value>{_S_NEG}|виявлено){_S_JUNK}(?P<ref>{_S_NEG})$")
#: BD FocalPoint's quintile rank: its label wraps under the value, the method text beside it.
_SILAB_QUINTILE = re.compile(r"^Квінтильний ранг препарату за (?P<rank>[1-5]) Автоматизована система\b")
#: The tail as OCR reads it: «технологією ВО РосаїРоїпі» is BD FocalPoint.
_SILAB_QUINTILE_TAIL = re.compile(r"^технологією \S{2} \S+")


def _silab_clean(line: str) -> str:
    """One OCR line with the homoglyphs a scan swaps in folded back.

    «He виявлені» is «Не виявлені» in Latin letters; «невиявлена» lost its space.
    """
    line = collapse_space(line)
    line = re.sub(r"^[|'‘’\"«\[]+\s*", "", line)
    line = re.sub(r"^\((?=[^\W\d_]{4})", "", line)
    line = re.sub(r"(?<![^\W\d_])H(?=e ?виявл)", "Н", line)
    line = re.sub(r"(?<![^\W\d_])h(?=e ?виявл)", "н", line)
    line = re.sub(r"(?<=[НнHh])e(?= ?виявл)", "е", line)
    return re.sub(r"\b([Нн]е)виявл", r"\1 виявл", line)


def _silab_case(text: str | None, section: str | None) -> str | None:
    """«не виявлені» as the urine, smear and PCR tables print it: lower case."""
    if text and section in {"urine", "smear", "hpv"} and text.startswith("Не виявл"):
        return "н" + text[1:]
    return text


def _silab_noise(line: str) -> bool:
    """A line OCR made out of a stamp, a rule or a signature: under three letters."""
    return len(re.findall(r"[^\W\d_]", line)) < 3


def _silab_section(line: str) -> tuple[bool, str | None]:
    for pattern, key in _SILAB_SECTIONS:
        if pattern.search(line):
            return True, key
    return False, None


def _silab_label(row: _SilabRow, line: str) -> re.Match[str] | None:
    pattern = rf"(?:{row.label or re.escape(row.name)})(?= |$)"
    # The first letter's case is the one thing OCR gets wrong on a clean label.
    return re.match(pattern, line) or re.match(pattern, line[:1].upper() + line[1:])


def _silab_row_start(section: str | None, line: str) -> bool:
    return any(_silab_label(row, line) for row in _SILAB_ROWS.get(section or "", ()))


def _silab_cells(lines: list[str], index: int, section: str | None) -> list[str]:
    """The lines under row `index` that belong to it, up to the next row.

    Every label is printed with a capital, and a wrapped cell goes on in lower
    case (a reference's «кольору», a scale's «25 = +»): a capitalised line is
    the next row even when OCR spoiled its label.  A cytology result is
    written in sentences, so there only a label OCR could read ends it.
    """
    cells: list[str] = []
    in_note = False
    for line in lines[index + 1:]:
        if (
            _silab_section(line)[0] or _SILAB_SITE.match(line) or _SILAB_END.match(line)
            or line.startswith("Висновок") or _silab_row_start(section, line)
            or _SILAB_GENOTYPE.match(line) or (section != "cytology" and line[0].isupper())
        ):
            break
        if _SILAB_NOTE.match(line):
            in_note = True
        if in_note or (_silab_noise(line) and not _SILAB_TIER.fullmatch(line)):
            continue
        cells.append(line)
    return cells


_SILAB_TIER = re.compile(r"(\d+(?:[.,]\d+)?) ?= ?(\++)")


def _silab_tiers(lines: list[str], count: int) -> str | None:
    """«25 = + 100 = ++ 500 = +++» when exactly `count` rising tiers were read."""
    tiers = []
    for position, line in enumerate(lines, start=1):
        found = _SILAB_TIER.fullmatch(line)
        if not found or len(found.group(2)) != position:
            return None
        if tiers and parse_decimal(found.group(1)) <= parse_decimal(tiers[-1][0]):
            return None
        tiers.append((found.group(1), found.group(2)))
    if len(tiers) != count:
        return None
    return " ".join(f"{number} = {plus}" for number, plus in tiers)


def _silab_observation(
    name: str, value: str, unit: str | None, reference: str | None, evidence: str, page_number: int,
    *, specimen: str | None = None, section: str | None = None,
) -> ParsedObservation:
    value = re.sub(r"(\d) ?- ?(\d)", r"\1-\2", re.sub(r"в ?п/з", "в п/з", value))
    number = re.fullmatch(r"(?P<comparator>[<>])?(?P<number>\d+(?:[.,]\d+)?)", value)
    item = ParsedObservation(
        raw_name=name, value_numeric=parse_decimal(number.group("number")) if number else None,
        value_text=None if number else value, comparator=number.group("comparator") if number else None,
        unit_raw=unit, reference_text=None, reference_low=None, reference_high=None,
        page_number=page_number, evidence_text=evidence, confidence=0.9, value_printed=None,
        specimen=specimen, section=section,
    )
    return _with_reference(item, reference)


def _silab_cells_match(row: _SilabRow, rest: str, cells: list[str]) -> tuple[str, str | None, str | None] | None:
    """The row's value, unit and reference read from its line and the lines under it, or None."""
    unit = rf"{_S_JUNK}(?P<unit>{row.unit})" if row.unit else ""
    reference = rf"{_S_JUNK}(?P<ref>{row.reference})" if row.reference else ""
    if row.wrap and cells and all(re.fullmatch(row.wrap, cell) for cell in cells):
        rest, cells = " ".join([rest, *cells]), []
    found = re.fullmatch(rf"{_S_JUNK}(?P<value>{row.value})\*?{unit}{reference}", rest)
    if not found:
        return None
    value = found.group("value")
    printed_unit = re.sub(r"[µu]L$", "µL", found.group("unit")) if row.unit else None
    printed = found.group("ref") if row.reference else None
    if row.tiers:
        scale = _silab_tiers(cells, row.tiers)
        # A number on a dipstick is one of the tiers it was read against.
        if not scale or (value[0].isdigit() and not re.search(rf"(?<![\d.]){re.escape(value)} =", scale)):
            return None
        return value, printed_unit, f"{printed} {scale}"
    if cells:
        return None
    if printed and re.fullmatch(_S_RANGE, printed):
        printed = re.sub(r" ?- ?", " - ", printed)
    return value, printed_unit, printed


def _silab_row(
    section: str, line: str, cells: list[str], page_number: int, site: str | None
) -> ParsedObservation | None:
    for row in _SILAB_ROWS[section]:
        label = _silab_label(row, line)
        if not label:
            continue
        name = row.name.format(**label.groupdict()) if label.groupdict() else row.name
        if row.name_tail:
            if not cells or cells[0] != row.name_tail:
                continue
            cells = cells[1:]
        read = _silab_cells_match(row, line[label.end():].strip(), cells)
        if read is None:
            continue
        value, unit, reference = read
        value, reference = _silab_case(value, section), _silab_case(reference, section)
        microscopy = section == "urine" and (row.unit or "").startswith("/")
        return _silab_observation(
            name, value, unit, reference, " ".join([line, *cells]), page_number,
            specimen="сеча" if section == "urine" else site,
            section="Мікроскопія осаду сечі" if microscopy else None,
        )
    return None


def parse_silab_page(
    text: str, page_number: int, *, sites_in_order: bool = True, state: dict[str, str | None] | None = None
) -> list[ParsedObservation]:
    """Every row of one scanned SILAB page this reader recognises with confidence.

    ``state`` carries the section and smear site over a page break: a page
    opens with the rows the previous one ran out of room for, above its own
    repeated heading.  It is updated in place for the next page.
    """
    state = {} if state is None else state
    lines = [line for line in (_silab_clean(raw) for raw in text.splitlines()) if line]
    observations: list[ParsedObservation] = []
    section, site = state.get("section"), state.get("site")
    for index, line in enumerate(lines):
        heading, key = _silab_section(line)
        if heading:
            section, site = key, None
            continue
        if section is None:
            continue
        if section == "smear":
            found = _SILAB_SITE.match(line)
            if found:
                site = found.group("site") if sites_in_order else None
                if site and found.group("rest") == "Матеріал відсутній":
                    observations.append(_silab_observation(
                        "Мазок на мікрофлору", "Матеріал відсутній", None, None, line, page_number, specimen=site,
                    ))
                continue
            if site and line == "Матеріал відсутній":
                observations.append(_silab_observation(
                    "Мазок на мікрофлору", line, None, None, line, page_number, specimen=site,
                ))
                continue
            grade = _SILAB_GRADE.match(line)
            if grade:
                observations.append(_silab_observation("Ступінь чистоти", grade.group("grade"), None, None, line, page_number))
                site = None
                continue
            if not site:
                continue
        if section == "hpv":
            found = _SILAB_GENOTYPE.match(line)
            if found and int(found.group("type")) in SILAB_HPV_GENOTYPES:
                observations.append(_silab_observation(
                    f"{found.group('type')} генотип", _silab_case(found.group("value"), section), None,
                    _silab_case(found.group("ref"), section), line, page_number,
                ))
            continue
        if section == "pap":
            found = _SILAB_QUINTILE.match(line)
            if found and index + 1 < len(lines) and _SILAB_QUINTILE_TAIL.match(lines[index + 1]):
                observations.append(_silab_observation(
                    "Квінтильний ранг препарату за технологією BD FocalPoint", found.group("rank"), None, None,
                    f"{line} {lines[index + 1]}", page_number,
                ))
                continue
        row = _silab_row(section, line, _silab_cells(lines, index, section), page_number, site)
        if row is not None:
            observations.append(row)
    state.update(section=section, site=site)
    return observations


def silab_print(pages: list[dict[str, object]]) -> str | None:
    """«form» for a SILAB print, «portal» for Synevo's copy of one, else None."""
    text = "\n".join(str(page.get(field) or "") for page in pages for field in ("native_text", "ocr_text"))
    if not SILAB_PRINT.search(text):
        return None
    return "portal" if SILAB_PORTAL_COPY.search(text) else "form"


def _unique_genotypes(observations: list[ParsedObservation]) -> list[ParsedObservation]:
    """Genotype rows whose number the document prints once.

    A misread number (33 read as 38 is caught by the panel; 56 read as 58 is
    not) shows as the same genotype twice, and neither reading can be trusted.
    """
    counts: dict[str, int] = {}
    for item in observations:
        if item.raw_name.endswith(" генотип"):
            counts[item.raw_name] = counts.get(item.raw_name, 0) + 1
    return [item for item in observations if counts.get(item.raw_name, 1) == 1]


def _special_layout_rows(clinical_type: str, pages: list[dict[str, object]]) -> list[ParsedObservation] | None:
    """The rows of a report read whole rather than page by page, or None."""
    if clinical_type in ULTRASOUND_TYPES:
        texts = ["\n".join(str(page.get(field) or "") for field in ("native_text", "ocr_text")) for page in pages]
        # The previous page goes along so a measurement whose organ heading
        # fell above the page break is still read under that organ.
        return [
            item
            for index, page in enumerate(pages)
            for item in parse_ultrasound(texts[index], int(page["page_number"]), texts[index - 1] if index else "")
        ]
    if clinical_type in VISIT_MEASUREMENT_TYPES:
        return parse_visit_measurements(pages)
    if clinical_type == "blood_pressure":
        return parse_garmin_blood_pressure(pages)
    if clinical_type == "electrocardiogram":
        # A clinic's ECG report prints its intervals in a table; a Kardia
        # export prints none.  Both are read, so a classifier that files the
        # clinic's report as an ECG does not cost it its values.
        return [*parse_kardia_ecg(pages), *parse_visit_measurements(pages)]
    return None


def _carry_leading_reference(observations: list[ParsedObservation], page_words: list, page_number: int) -> None:
    """Give the previous page's last block the reference lines that opened this page."""
    carried = eskulab_leading_reference(page_words)
    last = len(observations) - 1
    if carried and observations[last].page_number == page_number - 1 and observations[last].reference_text:
        observations[last] = _with_reference(
            observations[last], f"{observations[last].reference_text} {carried}"
        )


def _page_rows(
    vendor: str, clinical_type: str, page: dict[str, object], columns_own_page: bool,
    issues: list[ParseIssue] | None, silab: str | None = None, silab_state: dict | None = None,
) -> list[ParsedObservation]:
    """Every row of one page, from its native text layer and from its OCR."""
    page_number = int(page["page_number"])
    rows: list[ParsedObservation] = []
    for field, method, confidence_cap in (
        ("native_text", "native_pdf_text_parser", 1.0),
        ("ocr_text", "embedded_image_ocr_parser", 0.90),
    ):
        if field == "ocr_text" and columns_own_page:
            continue
        text = str(page.get(field) or "")
        if not text.strip():
            continue
        # Word positions describe the native text layer only; OCR of an
        # embedded image has its own geometry and none of it is this.
        words = page.get("words") if field == "native_text" else None
        # A scanned SILAB print is read by the reader that knows its form,
        # and by nothing else: the flat passes read its OCR noise as values.
        read = (
            parse_silab_page(text, page_number, sites_in_order=silab == "form", state=silab_state)
            if silab and field == "ocr_text"
            else parse_source_text(vendor, clinical_type, text, page_number, words, issues)
        )
        for observation in read:
            rows.append(
                replace(
                    observation,
                    extraction_method=method,
                    confidence=min(observation.confidence, confidence_cap),
                )
            )
    return rows


def _distinct_rows(observations: list[ParsedObservation]) -> list[ParsedObservation]:
    """One row per printed result, however many passes read it."""
    unique: dict[tuple, ParsedObservation] = {}
    for observation in observations:
        key = (
            observation.page_number,
            collapse_space(observation.raw_name).casefold(),
            observation.value_numeric,
            observation.value_text or observation.unit_raw,
            observation.section,
            observation.specimen,
        )
        unique.setdefault(key, observation)
    values = list(unique.values())
    # A row whose name is another row's name with that row's value glued on
    # is the same result read with the value as part of the label.
    return [
        item
        for item in values
        if not any(
            other is not item
            and other.page_number == item.page_number
            and other.evidence_text == item.evidence_text
            and item.raw_name.casefold().startswith(other.raw_name.casefold() + " ")
            and other.value_numeric is not None
            and str(other.value_numeric).rstrip("0").rstrip(".") in item.raw_name
            for other in values
        )
    ]


def parse_document(
    vendor: str,
    clinical_type: str,
    pages: list[dict[str, object]],
    *,
    issues: list[ParseIssue] | None = None,
    age_years: int | None = None,
    sex: str | None = None,
) -> list[ParsedObservation]:
    """Every observation on ``pages``, finalised.

    ``issues`` collects lines the parser recognised and could not read (the
    pipeline makes each a review task).  ``age_years`` and ``sex`` -- the
    patient's at the report date, ``sex`` as stored in ``sex_at_birth`` --
    let a block printed for several populations yield this patient's bounds;
    without them those rows keep their full printed block and no bounds.
    Passing consecutive pages of one report together lets a reference block
    that runs over a page break be read whole.
    """
    special = _special_layout_rows(clinical_type, pages)
    if special is not None:
        return [finalise(item, age_years, sex) for item in special]
    if clinical_type not in PARSED_CLINICAL_TYPES:
        return []
    observations: list[ParsedObservation] = []
    silab, silab_state = silab_print(pages), {}
    for page in pages:
        page_words = page.get("words")
        # An EskuLab page whose native layer draws the table is read from its
        # columns, so the OCR pass over the same page is skipped entirely.  It
        # carries no word positions, which would send it to the passes that
        # read the page as flat text -- and read the reference block under
        # each row as more results, which is the bug the columns exist to fix.
        columns_own_page = bool(vendor == "EskuLab" and page_words and eskulab_table_page(page_words))
        if columns_own_page and observations:
            # The previous page's last block, continued over the break.
            _carry_leading_reference(observations, page_words, int(page["page_number"]))
        observations.extend(_page_rows(vendor, clinical_type, page, columns_own_page, issues, silab, silab_state))
    if silab:
        observations = _unique_genotypes(observations)
    observations = _antibiogram_material(observations)
    return [finalise(item, age_years, sex) for item in _distinct_rows(observations)]


def _antibiogram_material(observations: list[ParsedObservation]) -> list[ParsedObservation]:
    """An antibiogram continued over a page break keeps its isolate's material.

    The second page reprints «Антибіотики/Антимікотики <organism>» and
    nothing about the specimen, which was named on the page before.
    """
    material = {
        item.note: item.specimen
        for item in observations
        if item.note and item.section == item.note and item.specimen
    }
    return [
        replace(item, specimen=material[item.note])
        if item.note and item.section == item.note and not item.specimen and item.note in material
        else item
        for item in observations
    ]


#: A trailing «, <unit>» or specimen phrase is presentation, not identity:
#: Expert prints «Лейкоцити (WBC), в п/з» where a re-read without the suffix
#: yields «Лейкоцити (WBC)».
def label_key(raw_name: str) -> str:
    """The form of a printed label two parses of one row agree on.

    Casefolded, whitespace collapsed, a trailing «, <unit>» and a trailing
    specimen phrase removed, Cyrillic look-alikes of Latin letters folded
    («(МСН)» is «(MCH)»), punctuation other than brackets dropped.
    """
    name, _unit = split_comma_unit(collapse_space(raw_name))
    name = _NAME_SPECIMEN.sub("", name).strip(" ,")
    name = name.translate(_TO_LATIN).casefold()
    name = re.sub(r"[^\w()%#+/.-]+", " ", name)
    return collapse_space(name)


def same_label(stored: str, parsed: str) -> bool:
    """Do two printed labels name one row?

    Equal keys, or one key a whole-word prefix of the other -- the shorter one
    lost the tail that wrapped onto the next line («… вірусу гепатиту» and
    «… вірусу гепатиту В (HbsAg)»).  At least three words must agree, so a bare
    «Лейкоцити» never pairs with «Лейкоцити в мкл (WBC)».
    """
    a, b = label_key(stored), label_key(parsed)
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    return len(short.split()) >= 3 and long.startswith(short + " ")
