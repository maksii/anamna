"""Word-start, bilingual matching for the record-wide search on /metrics.

Substring matching is what made "ALT" find «heALTh», "AST" find
«thromboplASTin», «кір» find «осоКІР» and «сон» find «ЦефтріакСОН».  Here a
query word has to be a word of the searched name, the start of one, or the
same Ukrainian word with another case ending («білка» for «білок»,
«лімфоцитів» for «лімфоцити»).  Whole words rank above case endings, case
endings above word starts -- but nothing that matches is dropped, so typing
more letters can only narrow the results, never swap them for others.

Both sides go through `search_key`, so case, Cyrillic/Latin script, the
g/h spelling of «г», apostrophes and lookalike letters typed in the wrong
layout never decide whether a result is found.

Abbreviations and everyday words a person actually types ("цукор", "HRV",
«ЛПНП», "Lp(a)") rarely appear in a lab's printed name, so `SYNONYMS` maps each
to the names the record does use.  This table is search vocabulary, not
user-visible text: it is never rendered, so it carries no translation.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from ..ingest.text import search_key

#: Each tuple is one meaning, spelled every way a person might type it, in both
#: languages.  A query equal to any member also searches for all the others.
_STEPS_UK = "кроки"

SYNONYMS: tuple[tuple[str, ...], ...] = (
    # Laboratory abbreviations
    ("ALT", "АЛТ", "АлАТ", "ALAT", "alanine aminotransferase", "аланінамінотрансфераза"),
    ("AST", "АСТ", "АсАТ", "ASAT", "aspartate aminotransferase", "аспартатамінотрансфераза"),
    ("GGT", "ГГТ", "gamma-glutamyl transferase", "гамма-глутамілтрансфераза"),
    ("ALP", "ЛФ", "alkaline phosphatase", "лужна фосфатаза"),
    ("CRP", "СРБ", "C-reactive protein", "С-реактивний білок"),
    ("hsCRP", "hs-CRP", "High-sensitivity C-reactive protein", "високочутливий С-реактивний білок"),
    ("LDL", "ЛПНП", "ЛПНЩ", "LDL cholesterol", "ліпопротеїди низької щільності", "ліпопротеїни низької щільності"),
    ("HDL", "ЛПВП", "ЛПВЩ", "HDL cholesterol", "ліпопротеїди високої щільності", "ліпопротеїни високої щільності"),
    ("VLDL", "ЛПДНЩ", "ЛПДНП", "VLDL cholesterol"),
    ("Lp(a)", "Lpa", "lipoprotein(a)", "ліпопротеїн (а)"),
    ("TSH", "ТТГ", "thyroid stimulating hormone", "тиреотропний гормон"),
    ("FT4", "fT4", "free thyroxine", "вільний тироксин", "Т4 вільний"),
    ("FT3", "fT3", "free triiodothyronine", "вільний трийодтиронін", "Т3 вільний"),
    ("ESR", "ШОЕ", "ШЗЕ", "erythrocyte sedimentation rate", "швидкість осідання еритроцитів"),
    ("WBC", "white blood cells", "leukocytes", "лейкоцити"),
    ("RBC", "red blood cells", "erythrocytes", "еритроцити"),
    ("PLT", "platelets", "тромбоцити"),
    ("Hb", "Hgb", "HGB", "hemoglobin", "haemoglobin", "гемоглобін"),
    ("HbA1c", "A1c", "glycated hemoglobin", "glycated haemoglobin", "глікований гемоглобін"),
    ("glucose", "blood glucose", "blood sugar", "sugar", "цукор", "цукор крові", "глюкоза"),
    ("eGFR", "GFR", "ШКФ", "estimated glomerular filtration rate", "glomerular filtration rate",
     "швидкість клубочкової фільтрації"),
    ("vitamin D", "вітамін D", "25-OH", "25(OH)D", "25-hydroxyvitamin D", "25-гідроксивітамін D"),
    ("B12", "vitamin B12", "вітамін B12", "cobalamin", "кобаламін"),
    ("ferritin", "феритин"),
    ("creatinine", "креатинін"),
    ("cholesterol", "холестерин", "total cholesterol", "загальний холестерин"),
    ("HBsAg", "hepatitis B surface antigen", "поверхневий антиген гепатиту B"),
    ("IgE", "total IgE", "загальний IgE"),
    ("urine", "сеча", "urinalysis", "аналіз сечі", "загальний аналіз сечі"),
    ("CBC", "complete blood count", "загальний аналіз крові", "ЗАК"),
    # Device measurements
    ("HRV", "ВСР", "heart rate variability", "варіабельність серцевого ритму"),
    ("SpO2", "SpO₂", "blood oxygen", "oxygen saturation", "oxygen", "кисень", "сатурація",
     "насичення киснем", "кисень у крові"),
    ("heart rate", "pulse", "пульс", "ЧСС", "частота серцевих скорочень", "серцевий ритм"),
    ("resting heart rate", "пульс у спокої", "ЧСС у спокої"),
    ("BMI", "ІМТ", "body mass index", "індекс маси тіла"),
    ("weight", "body weight", "вага", "маса тіла", "вага тіла"),
    ("height", "body height", "зріст"),
    ("steps", "step count", _STEPS_UK, "кількість кроків"),
    ("sleep", "sleep duration", "сон", "тривалість сну"),
    ("VO2", "VO2 max", "VO₂ max", "МСК", "максимальне споживання кисню"),
    ("blood pressure", "тиск", "артеріальний тиск"),
    ("calories", "kcal", "калорії", "active energy", "активна енергія"),
    ("respiratory rate", "breathing rate", "частота дихання"),
    ("temperature", "температура", "body temperature", "температура тіла"),
    # Examinations and document kinds
    ("ECG", "EKG", "ЕКГ", "electrocardiogram", "електрокардіограма", "кардіограма"),
    ("ultrasound", "УЗД", "УЗ", "sonography", "сонографія", "ультразвукове дослідження"),
    ("echocardiography", "ЕхоКГ", "echo", "ехокардіографія", "УЗД серця"),
    ("MRI", "МРТ", "magnetic resonance", "магнітно-резонансна томографія"),
    ("CT", "КТ", "computed tomography", "комп'ютерна томографія"),
    ("X-ray", "xray", "radiograph", "рентген", "рентгенограма", "рентгенографія"),
    ("pathology", "histology", "гістологія", "патогістологія", "патоморфологія"),
    ("colonoscopy", "колоноскопія"),
    ("polyp", "поліп"),
    ("adenoma", "аденома"),
    ("thyroid", "щитоподібна", "щитоподібна залоза", "ЩЗ"),
    ("liver", "печінка"),
    ("kidney", "kidneys", "нирки", "нирка"),
    ("allergy", "allergen", "алергія", "алерген"),
    ("birch", "береза", "Bet v 1"),
    ("lab", "laboratory", "лабораторія", "аналізи"),
    # Vaccination vocabulary (product and maker names come from the record itself)
    ("vaccine", "vaccination", "immunization", "immunisation", "вакцина", "щеплення",
     "вакцинація", "імунізація"),
    ("flu", "influenza", "грип"),
    ("tetanus", "правець"),
    ("diphtheria", "дифтерія"),
    ("pertussis", "whooping cough", "кашлюк"),
    ("measles", "кір"),
    ("mumps", "паротит", "епідемічний паротит"),
    ("rubella", "краснуха"),
    ("hepatitis", "гепатит"),
    ("hepatitis A", "гепатит A", "гепатит А"),
    ("hepatitis B", "гепатит B", "гепатит В"),
    ("COVID", "COVID-19", "SARS-CoV-2", "коронавірус", "коронавірусна хвороба"),
    ("polio", "poliomyelitis", "поліомієліт"),
    ("tuberculosis", "TB", "BCG", "туберкульоз", "БЦЖ"),
    ("Pfizer", "Comirnaty", "BioNTech", "Комірнаті"),
    ("Boostrix", "Бустрікс"),
    ("Priorix", "Пріорикс"),
    ("Engerix", "Енджерикс"),
    ("Twinrix", "Твінрикс"),
    # Blood count abbreviations an analyser prints beside only some of the
    # rows they name: "LYM" stood on one of five lymphocyte results.
    ("LYM", "LYMPH", "lymphocytes", "лімфоцити"),
    ("NEU", "NEUT", "neutrophils", "нейтрофіли"),
    ("MON", "MONO", "monocytes", "моноцити"),
    ("EOS", "eosinophils", "еозинофіли"),
    ("BAS", "BASO", "basophils", "базофіли"),
    ("HCT", "hematocrit", "haematocrit", "гематокрит"),
)

#: A query shorter than this, in letters and digits, finds only whole words
#: ("Hb", «КТ», «УЗ»): two letters start too many words to mean anything, and
#: one letter finds nothing at all -- every «л» in «г/л» is a whole word.  The
#: page says so (`metrics.short_query`).
MIN_LETTERS = 3
MIN_ABBREVIATION = 2

#: Scores.  Lower is better; odd scores are the same match on a secondary term
#: (a panel a result belongs to, a vendor) rather than on the item's own name.
EXACT = 0
WHOLE_WORD = 2
#: The same word with another case ending: «гепатит» in «гепатиту», «білка»
#: for «білок», "lymphocytes" for "lymphocyte".
PREFIX = 4
#: The start of a longer word, as a person mid-typing produces ("гемо"), or a
#: synonym reached through such a start («холестер» to "cholesterol").
PARTIAL = 6

#: How a phrase may match: by whole words only (a query too short for
#: anything else), by whole words with any case ending (a synonym's
#: spelling), or also by the start of a word (what was typed).
WHOLE_ONLY, COMPLETE, OPEN = "whole", "complete", "open"

#: Ukrainian noun and adjective case endings, plus the English plural, in
#: their search-key spelling.  Only ever stripped from a stem of four letters
#: or more, so abbreviations never decline.
_ENDINGS = frozenset({"s", "es"} | {
    search_key(ending) for ending in (
        "а", "я", "у", "ю", "о", "е", "є", "і", "ї", "и", "ові", "еві", "єві",
        "ам", "ям", "ами", "ями", "ах", "ях", "ів", "їв", "ей", "ою", "ею", "єю",
        "ом", "ем", "єм", "ий", "ій", "ого", "ього", "ому", "ьому", "им", "ім",
        "ої", "ьої", "их", "іх", "ими", "іми", "ія", "ії", "ію", "ією",
    )
} | {""})
#: Every beginning of an ending: what a half-typed ending looks like.  Closed
#: under prefixes, which is what keeps a shorter query a superset.
_ENDING_STARTS = frozenset(ending[:size] for ending in _ENDINGS for size in range(len(ending) + 1))
_LONGEST_ENDING = max(map(len, _ENDINGS))
_MIN_STEM = 4
_CONSONANTS = frozenset("bcdfhjklmnpqrstvwxz")

#: Letters that look identical in both scripts.  A word typed with the wrong
#: layout for one letter («лiмфоцити» with a Latin i, "СOVID" with a Cyrillic
#: С) is read in the script of most of its letters; a word made only of such
#: letters ("MCH", Synevo's Cyrillic «МСН») is indexed under both readings.
_LATIN_GLYPHS = "ABCEHIKMOPTXYaceiopxy"
_CYRILLIC_GLYPHS = "АВСЕНІКМОРТХУасеіорху"
_TO_CYRILLIC = str.maketrans(_LATIN_GLYPHS, _CYRILLIC_GLYPHS)
_TO_LATIN = str.maketrans(_CYRILLIC_GLYPHS, _LATIN_GLYPHS)
#: «комп'ютерна», «комп’ютерна» and «компютерна» are one word.
_APOSTROPHES = str.maketrans("", "", "'’ʼ`‘")
_WORD = re.compile(r"[^\W_]+")


def _is_cyrillic(char: str) -> bool:
    return "\u0400" <= char <= "\u04ff"


def _is_latin(char: str) -> bool:
    return "a" <= char.lower() <= "z"


@lru_cache(maxsize=65536)
def _readings(raw: str) -> tuple[str, ...]:
    """A typed or printed word as search keys: its own reading first, then the
    other script's when every letter could be either."""
    cyrillic = sum(map(_is_cyrillic, raw))
    latin = sum(map(_is_latin, raw))
    if cyrillic and latin:
        return (search_key(raw.translate(_TO_CYRILLIC if cyrillic >= latin else _TO_LATIN)),)
    own = search_key(raw)
    glyphs = _CYRILLIC_GLYPHS if cyrillic else _LATIN_GLYPHS
    if not (cyrillic or latin) or any(not char.isdigit() and char not in glyphs for char in raw):
        return (own,)
    other = search_key(raw.translate(_TO_LATIN if cyrillic else _TO_CYRILLIC))
    return tuple(dict.fromkeys((own, other)))


def _raw_words(text: str | None) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text or "").translate(_APOSTROPHES))


def words(text: str | None) -> tuple[str, ...]:
    """The words of a query, folded the way every searched name is."""
    return tuple(_readings(raw)[0] for raw in _raw_words(text))


def _drop_fleeting(word: str) -> str | None:
    """«білок» is printed «білка», «вузол» «вузла»: the o/e before a final
    consonant or two drops out when the word declines."""
    for tail in (1, 2):
        cut = len(word) - tail - 1
        if cut >= 3 and word[cut] in "oe" and all(char in _CONSONANTS for char in word[cut + 1:]):
            return word[:cut] + word[cut + 1:]
    return None


@lru_cache(maxsize=65536)
def _variants(raw: str) -> tuple[str, ...]:
    """Every key a printed word is found under: its readings, and each with
    a fleeting vowel dropped."""
    readings = _readings(raw)
    return tuple(dict.fromkeys((*readings, *filter(None, map(_drop_fleeting, readings)))))


Word = tuple[str, ...]
Term = tuple[Word, ...]
Terms = tuple[tuple[Term, int], ...]


def terms(primary: Iterable[str | None], secondary: Iterable[str | None] = ()) -> Terms:
    """Pre-folded searchable names: (words, 0) for the item's own names and
    aliases, (words, 1) for context it merely belongs to.  Each word is the
    tuple of keys it is found under."""
    seen: set[Term] = set()
    out: list[tuple[Term, int]] = []
    for weight, texts in ((0, primary), (1, secondary)):
        for text in texts:
            key = tuple(_variants(raw) for raw in _raw_words(text))
            if key and key not in seen:
                seen.add(key)
                out.append((key, weight))
    return tuple(out)


def _expansions() -> dict[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    table: dict[tuple[str, ...], tuple[tuple[str, ...], ...]] = {}
    for group in SYNONYMS:
        spelled = tuple(dict.fromkeys(key for key in map(words, group) if key))
        for key in spelled:
            table[key] = tuple(dict.fromkeys(table.get(key, ()) + spelled))
    return table


_EXPANSIONS = _expansions()

Phrase = tuple[tuple[str, ...], str, int]


@dataclass(frozen=True)
class Query:
    text: str
    words: tuple[str, ...]
    #: (words, how they may match, the best score they can give): the query
    #: itself first, then every synonym spelling it names or begins.
    phrases: tuple[Phrase, ...]
    #: Fewer than `MIN_LETTERS` letters typed: only whole words are answers.
    #: Counted as typed, not as folded: «щ» is one letter, not "shch".
    short: bool = False


def _key_floor(own: tuple[str, ...], key: tuple[str, ...], short: bool) -> int | None:
    """How the query names synonym `key`: as it is, in any case ending
    («лімфоцитів» names «лімфоцити»), by its start («загальний ан» begins
    «загальний аналіз крові»), or not at all (None)."""
    if short:
        return EXACT if key == own else None
    last = len(own) - 1
    if len(key) <= last or any(_word_tier(word, (have,), COMPLETE) is None for word, have in zip(own[:last], key)):
        return None
    tier = _word_tier(own[last], (key[last],), OPEN)
    if tier is None:
        return None
    return EXACT if tier < PARTIAL and len(key) == len(own) else PARTIAL


def _synonym_phrases(own: tuple[str, ...], short: bool) -> dict[tuple[str, ...], Phrase]:
    """Every spelling of each meaning the query names (scored as it is) or,
    past `MIN_LETTERS`, begins (scored as a word start)."""
    mode = WHOLE_ONLY if short else COMPLETE
    phrases: dict[tuple[str, ...], Phrase] = {}
    for key, group in _EXPANSIONS.items():
        floor = _key_floor(own, key, short)
        if floor is None:
            continue
        for spelling in group:
            if spelling not in phrases or phrases[spelling][2] > floor:
                phrases[spelling] = (spelling, mode, floor)
    return phrases


def parse(text: str) -> Query:
    own = words(text)
    letters = sum(map(len, _raw_words(text)))
    if letters < MIN_ABBREVIATION:
        return Query(text=text.strip(), words=own, phrases=(), short=bool(own))
    short = letters < MIN_LETTERS
    phrases = {own: (own, WHOLE_ONLY if short else OPEN, EXACT)}
    for spelling, phrase in _synonym_phrases(own, short).items():
        phrases.setdefault(spelling, phrase)
    return Query(text=text.strip(), words=own, phrases=tuple(phrases.values()), short=short)


def _inflected(word: str, have: str, endings: frozenset[str]) -> bool:
    """One stem of four letters or more, `word` ending in one of `endings`
    and `have` in a whole case ending: «лімфоцитів» and «лімфоцити»."""
    shared = len(os.path.commonprefix((word, have)))
    low = max(_MIN_STEM, len(word) - _LONGEST_ENDING)
    return any(word[cut:] in endings and have[cut:] in _ENDINGS for cut in range(low, shared + 1))


def _open_forms(word: str) -> tuple[str, ...]:
    """What a half-typed word may still become: itself, without a fleeting
    vowel, and -- for «біло», on its way to «білок» -- without the vowel it
    just typed, so the shorter query finds «білка» as the longer one does."""
    forms = [word, _drop_fleeting(word)]
    if len(word) >= _MIN_STEM and word[-1] in "oe":
        forms.append(word[:-1])
    return tuple(filter(None, forms))


def _word_tier(word: str, have: Word, mode: str) -> int | None:
    if word in have:
        return WHOLE_WORD
    if mode == WHOLE_ONLY:
        return None
    whole = tuple(filter(None, (word, _drop_fleeting(word))))
    if any(_inflected(form, key, _ENDINGS) for form in whole for key in have):
        return PREFIX
    if mode == OPEN and any(
        key.startswith(form) or _inflected(form, key, _ENDING_STARTS)
        for form in _open_forms(word) for key in have
    ):
        return PARTIAL
    return None


class _Matcher:
    """Which printed words answer each query word, worked out once per word
    over the distinct words of everything searched -- a long report repeats
    the same few hundred words, and a request searches thousands of names."""

    def __init__(self, searchables: Iterable[Terms]):
        vocabulary: set[Word] = set()
        for searchable in searchables:
            for term, _ in searchable:
                vocabulary.update(term)
        #: Every rule keeps the first letters, so a query word is only ever
        #: compared with the words that begin like it.
        self._heads: dict[str, set[Word]] = {}
        for have in vocabulary:
            for key in have:
                self._heads.setdefault(key[:MIN_LETTERS], set()).add(have)
        self._found: dict[tuple[str, str], dict[Word, int]] = {}

    def tiers(self, word: str, mode: str) -> dict[Word, int]:
        found = self._found.get((word, mode))
        if found is None:
            found = self._found[word, mode] = {
                have: tier for have in self._candidates(word) if (tier := _word_tier(word, have, mode)) is not None
            }
        return found

    def _candidates(self, word: str) -> set[Word]:
        if len(word) >= MIN_LETTERS:
            return self._heads.get(word[:MIN_LETTERS], set())
        # A short word beside a longer one ("вітамін D", «загальний бі»)
        # still begins words.
        return set().union(*(haves for head, haves in self._heads.items() if head.startswith(word)))


def _term_tier(matcher: _Matcher, phrase: Phrase, term: Term) -> int | None:
    """The weakest word tier of `phrase` against `term`; None when any word misses."""
    spelled, mode, floor = phrase
    found = [matcher.tiers(word, mode) for word in spelled]
    if any(tiers.keys().isdisjoint(term) for tiers in found):
        return None
    if len(spelled) == len(term) and all(word in have for word, have in zip(spelled, term)):
        return floor
    return max(floor, *(min(tiers[have] for have in term if have in tiers) for tiers in found))


def score(query: Query, searchable: Terms, matcher: _Matcher | None = None) -> int | None:
    """How well `searchable` answers `query`; None when it does not at all."""
    matcher = matcher or _Matcher([searchable])
    found = [
        tier + weight
        for term, weight in searchable
        for phrase in query.phrases
        if (tier := _term_tier(matcher, phrase, term)) is not None
    ]
    return min(found, default=None)


def rank(query: Query, groups: dict[str, list[tuple[Terms, object]]]) -> dict[str, list[tuple[int, object]]]:
    """Each group's (score, item) matches, best first, input order kept on ties.

    Nothing that matches is ever dropped for a better match elsewhere: that is
    what made «лімфо» find one conclusion while «лімф» and «лімфоцити» found
    the five lymphocyte results.  Every rule above only widens as a word gets
    shorter, so a word's beginning finds at least what the word finds.
    """
    matcher = _Matcher(searchable for items in groups.values() for searchable, _ in items)
    return {name: _ranked(query, items, matcher) for name, items in groups.items()}


def _ranked(query: Query, items: list[tuple[Terms, object]], matcher: _Matcher) -> list[tuple[int, object]]:
    scored = [
        (value, index, item)
        for index, (searchable, item) in enumerate(items)
        if (value := score(query, searchable, matcher)) is not None
    ]
    return [(value, item) for value, _, item in sorted(scored, key=lambda hit: hit[:2])]
