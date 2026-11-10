"""What to do before a lab visit, as a short checklist.

Labs publish preparation per test.  A plan of thirty tests repeats one
paragraph thirty times with small differences, wrapped in logistics,
addresses, notes for infants and boilerplate.  Here each item's own text is
split into clauses and matched against a small catalogue of rules (fasting,
alcohol, PSA waits, urine collection, ...).  A rule keeps the strictest number
any item states, never one the labs do not print, and the page shows the
curated wording from ``plan.prep_*`` in the reader's language.  A clause that
matches no rule contributes nothing: the lab's own words stay one click away
on each test's page.

The numbers come from the labs' texts (Esculab's per-good ``ua_rules``,
Synevo's ``PrepRuleText``); see ``tests/python/test_plan_prep.py`` for the
sentences each rule is read from.
"""
from __future__ import annotations

import re

from .i18n import t, t_plural

# --- reading a duration ---------------------------------------------------------------

_WORDS = {"один": 1, "одну": 1, "одна": 1, "два": 2, "дві": 2, "двох": 2, "три": 3, "трьох": 3,
          "чотири": 4, "чотирьох": 4, "п'ять": 5, "п'яти": 5, "шість": 6, "шести": 6, "сім": 7, "семи": 7}
_NUM = r"(\d+|" + "|".join(sorted(map(re.escape, _WORDS), key=len, reverse=True)) + r")"
_DUR_TEXT = rf"(?<!\w){_NUM}(?:\s*-\s*{_NUM})?(?:-?(?:х|ти))?\s*(год|хв|доб|діб|дн|день|дня|тиж)"
_DUR = re.compile(_DUR_TEXT)
#: The same pattern without groups, to embed in a rule's context.
DUR = re.sub(r"\((?!\?)", "(?:", _DUR_TEXT)
_MINUTES = {"min": 1, "h": 60, "d": 1440, "w": 10080}


def _unit(word: str) -> str:
    if word.startswith("год"):
        return "h"
    if word.startswith("хв"):
        return "min"
    if word.startswith("тиж"):
        return "w"
    return "d"


def durations(text: str) -> list[tuple[int, int, str]]:
    """Every ``(low, high, unit)`` the clause states: «8-12 год», «3-х діб»,
    «через три тижні», «шестигодинної», «напередодні» (24 h), «протягом доби»."""
    out = [(_count(a), _count(b or a), _unit(unit)) for a, b, unit in _DUR.findall(text)]
    if "напередодні" in text or "за день до" in text:
        out.append((24, 24, "h"))
    if re.search(r"(?:протягом|впродовж|продовж|за)\s+(?:доби|добу)\b", text):
        out.append((1, 1, "d"))
    return out


def _count(word: str) -> int:
    return int(word) if word.isdigit() else _WORDS[word]


def minutes(value: tuple[int, int, str], high: bool = True) -> int:
    return (value[1] if high else value[0]) * _MINUTES[value[2]]


def fmt(value: tuple[int, int, str]) -> str:
    low, high, unit = value
    n = str(high) if low == high else f"{low}-{high}"
    if unit == "d":
        return t_plural("plan.prep_days", high, n=n)
    if unit == "w":
        return t_plural("plan.prep_weeks", high, n=n)
    return t("plan.prep_hours" if unit == "h" else "plan.prep_minutes", n=n)


# --- reading a clause -----------------------------------------------------------------

_SPLIT = re.compile(r";|(?<=[.!?])\s+|\s\*|,\s+а\s+")
_CHILD = re.compile(r"діт|дитин|грудн|немовл|новонародж")
_WOMEN = re.compile(r"жін|вагітн|менстру|\bмц\b|піхв|вагінал|гінеколог|спринцюв")
_MEN = re.compile(r"чолов|простат|еякул|сім'явиверж|статевого члена|передміхур|крайню плоть")


def clauses(text: str) -> list[str]:
    """The lab's text as lower-case clauses, apostrophes and dashes unified."""
    text = (text or "").replace("﻿", "").casefold()
    text = re.sub(r"[’ʼ`]", "'", re.sub(r"[–—−]", "-", text))
    return [part.strip() for part in _SPLIT.split(" ".join(text.split())) if part and part.strip(" .!-")]


# --- the rules ------------------------------------------------------------------------

def _rule(name, find, kind="flag", *, unless=None, dur=None, sex=None, child=False, material=None,
          not_material=None, value=None):
    """``kind``: ``flag`` (no number), ``max`` (an abstention: the longest wins,
    «6-12 год» counts as 12), ``range`` (fasting: the window with the latest
    start wins), ``min`` (a delivery deadline: the shortest wins) or
    ``variant`` (``value(clause)`` names it; each distinct one is its own line)."""
    return {"name": name, "find": re.compile(find), "kind": kind, "unless": unless and re.compile(unless),
            "dur": dur and re.compile(dur), "sex": sex, "child": child, "material": material,
            "not_material": not_material, "value": value}


def _times(clause: str) -> tuple[str, ...] | None:
    found = re.findall(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", clause)
    return tuple(re.sub(r"\s+", "", window) for window in found) or None


def _cycle(clause: str) -> str | None:
    found = re.search(r"(?<!\d)(\d\d*+)\s*+-\s*+(\d++)\W{0,3}+(?:го\s++)?(?:день|дня|дні)\s++(?:мц|менструал)", clause) \
        or re.search(r"з\s+(\d+)-?го\s+до\s+(\d+)-?го\s+дня\s+менструал", clause)
    return f"{found.group(1)}-{found.group(2)}" if found else None


_DAY = (("пон", "пн"), ("вів", "вт"), ("сер", "ср"), ("чет", "чт"), ("п'ят", "пт"), ("суб", "сб"), ("нед", "нд"))
_DAY_WORD = r"(понеділ\w*|вівтор\w*|серед\w*|четвер\w*|п'ятниц\w*|субот\w*|неділ\w*|пн|вт|ср|чт|пт|сб|нд)"


def _day(word: str) -> int:
    return next(index for index, prefixes in enumerate(_DAY) if word.startswith(prefixes))


def _weekdays(clause: str) -> tuple[int, ...] | None:
    found = re.search(rf"(?:з\s+)?{_DAY_WORD}\.?\s*(?:-|по|до)\s*{_DAY_WORD}\b", clause)
    if found:
        days = tuple(range(_day(found.group(1)), _day(found.group(2)) + 1))
    else:
        found = re.search(rf"у\s+{_DAY_WORD}\s+(?:та|і)\s+{_DAY_WORD}\b", clause)
        days = tuple(sorted({_day(found.group(1)), _day(found.group(2))})) if found else ()
    return days if days and len(days) < 7 else None


#: Display order: the evening before first, fasting at the top, then the
#: samples to bring, then what only some tests ask, then the logistics.
RULES = [
    _rule("fasting", r"натщ|голодуван|після (?:останнього )?(?:прийому )?їжі|не їсти(?!\s+продукт)"
                     r"|(?:виключити|не|від)\s+(?:вжива\w*\s+|прийом\w*\s+|прийма\w*\s+|споживання\s+)?їж", "range"),
    _rule("water", r"(?:допуска\w*|допустим\w*|можна пити)[^;]*вод"),
    _rule("alcohol", r"алкогол|\bпив[оа]\b", "max"),
    _rule("smoking", r"\b(?:палі|палит|курі|курит|курін)", "max"),
    _rule("exercise", r"фізичн|стрес|емоційн", "max", unless=r"велосипед"),
    _rule("heat", r"саун|лазн|\bбан[юяі]\b|гаряч\w*\s+ванн|теплов", "max", unless=r"живіт"),
    _rule("sex", r"статев\w*\s+(?:контакт|стосунк|акт)|еякуля|сім'явиверж", "max",
          unless=r"після статев|еякулят|перед еякуляц|після еякуляц",
          # «не менше 48 годин і не більше 5 діб»: the abstinence is the lower bound.
          dur=r"^(?:(?!не більше).)*"),
    _rule("cycling", r"велосипед", "max"),
    _rule("medicines", r"\bлік(?:и|ів|ами)\b|лікарськ|діурет|проносн|біодобав|гормональні препарати",
          unless=r"антибакт|антибіот|протимікоз|протигриб|противірус"),
    _rule("morning", r"першій половині дня|\bвранці\b|\bзранку\b",
          unless=r"сеч|слин|\bкал|ліжк|стрічк"),
    _rule("time", r"час\s+(?:прийому\s+)?відбору\s+зразка", "variant", value=_times),
    _rule("wake_within", rf"не пізніше,?\s*ніж\s+через\s+{DUR}\s+після\s+пробудж", "variant",
          value=lambda c: next(iter(durations(c.split("пізніше", 1)[1])), None)),
    _rule("wake_after", rf"через\s+{DUR}\s+після\s+пробудж", "variant", unless=r"пізніше",
          value=lambda c: next(iter(durations(c.split("через", 1)[1])), None)),
    _rule("rest", r"стані спокою|відпочи|заспокоїт", "max", unless=r"ліжк|статев"),
    # Samples: one line each, built from what the item's own text adds.
    _rule("urine_morning", r"ранков\w*\s+(?:порці|сеч)|порці\w*\s+ранков", unless=r"перш\w*\s+порці",
          material="сеч"),
    _rule("urine_midstream", r"середн\w*\s+порці", material="сеч"),
    _rule("urine_wash", r"туалет\w*\s+(?:рук\s+і\s+)?(?:зовнішніх\s+)?статев", material="сеч"),
    _rule("urine_tampon", r"тампон", sex="F", material="сеч"),
    _rule("urine_sterile", r"стерильн[^;]*(?:сеч|контейнер)|(?:сеч|контейнер)[^;]*стерильн", material="сеч"),
    _rule("urine_food", r"колір сечі", material="сеч"),
    _rule("urine_within", r"доставит|перевищувати", "min", material="сеч",
          dur=rf"(?:не повинно перевищувати|доставити\w*(?:\s+\S+){{0,4}}\s+протягом)\s+{DUR}"),
    _rule("urine_now", r"одразу\s+доставля", material="сеч"),
    _rule("urine_first", r"перш\w*\s+порці", unless=r"спуст|вилива", material="сеч"),
    _rule("stool_fresh", r"свіжовид", material="кал"),
    _rule("stool_sterile", r"стерильн", material="кал"),
    _rule("stool_enema", r"клізм|касторов|вазелінов", unless=r"очищенн", material="кал"),
    _rule("stool_procedures", r"колоноскоп|ректороманоскоп|інструментальн", "max", material="кал"),
    _rule("stool_diet", r"припинити вживання|не вживати препарат|дотримуватися дієти", "max",
          unless=r"за показаннями", material="кал"),
    _rule("stool_within", r"доставит", "min", material="кал",
          dur=rf"доставити\w*(?:\s+\S+){{0,4}}\s+протягом\s+{DUR}"),
    _rule("stool_now", r"одразу\s+доставля", material="кал"),
    # What only some tests ask.
    _rule("psa", r"ректальн|урологічн|масаж\w*\s+простат", "max", unless=r"свіч",
          dur=rf"(?:раніше|через)[^;]*?{DUR}"),
    _rule("psa_biopsy", r"біопс\w*,?\s+простат|біопс\w*\s+передміхур", "max",
          dur=rf"(?:раніше|через)[^;]*?{DUR}"),
    _rule("thyroid_scan", r"щитоподібн[^;]*(?:біопс|скануван)|(?:біопс|скануван)[^;]*щитоподібн", "max"),
    _rule("thyroid_surgery", r"радіоактивн\w*\s+йод|хірургічн\w*\s+лікуванн\w*\s+(?:щз|щитоподібн)", "max"),
    _rule("biotin", r"біотин", "max"),
    _rule("antibiotics", r"антибакт|антибіот|протимікоз|протигриб", "max", unless=r"антибіотикограм",
          dur=rf"через\s+{DUR}"),
    _rule("menstruation", r"менструац", "max", unless=r"цикл|оператор|овуляц", sex="F",
          dur=rf"через\s+{DUR}\s+після\s+(?:її\s+)?закінчен"),
    _rule("cycle_day", r"мц|менструал", "variant", sex="F", value=_cycle),
    # Babies and small children: shown only when the record is not an adult's.
    _rule("infant_fasting", r"до 1 року", "range", child=True),
    _rule("toddler_fasting", r"від 1 до 5 років", "range", child=True),
    _rule("child_water", r"до 5 років[^;]*вод", "max", child=True),
    _rule("infant_feed", r"годуван", child=True),
    # Where and when the sample can be taken at all.
    _rule("weekdays", r"понеділ|вівтор|серед|четвер|п'ятниц|\bпн\b|\bвт\b|\bчт\b|\bпт\b", "variant", value=_weekdays),
    _rule("some_points", r"не у всіх відділеннях|лише на (?:тих )?пз|лише пз|тільки у відділеннях|за наступними адресами|забір проводиться у м\.|наявність відповідної позначки|уточнити (?:чи є|наявність)"),
    _rule("referral", r"(?:тільки|лише)[^;]*(?:направленн|скеруванн)", unless=r"вагітн"),
    _rule("doctor", r"(?:забір|взяття)\s+(?:\S+\s+){0,3}?(?:проводить|здійснюється)\s+(?:ваш\s+)?лікар|лікарська маніпуляція"),
    _rule("bring", r"приносн", not_material=r"сеч|кал"),
]


def _material(item: dict) -> str:
    return " ".join(item.get("material") or []).casefold()


def _other_audience(clause: str, is_child: bool, sex: str | None, adult: bool) -> bool:
    return bool((is_child and adult) or (sex == "M" and _WOMEN.search(clause)) or (sex == "F" and _MEN.search(clause)))


def _rule_applies(rule: dict, clause: str, is_child: bool, sex: str | None, material: str) -> bool:
    if rule["child"] != is_child or (rule["sex"] and sex not in (None, rule["sex"])):
        return False
    if (rule["material"] and rule["material"] not in material) or \
            (rule["not_material"] and re.search(rule["not_material"], material)):
        return False
    return bool(rule["find"].search(clause)) and not (rule["unless"] and rule["unless"].search(clause))


def _clause_hits(clause: str, index: int, material: str, sex: str | None, adult: bool, found: dict) -> None:
    is_child = bool(_CHILD.search(clause))
    if _other_audience(clause, is_child, sex, adult):
        return
    for rule in RULES:
        if _rule_applies(rule, clause, is_child, sex, material):
            found.setdefault(rule["name"], []).append({"item": index, "value": _value(rule, clause)})


def hits(items: list[dict], sex: str | None, adult: bool) -> dict[str, list[dict]]:
    """``{rule: [{"item": index, "value": ...}]}`` over ``items`` (each with its
    preparation text in ``prep``), for a record of ``sex`` ("M"/"F"/None):
    clauses about the other sex, and about children for an adult, are skipped."""
    found: dict[str, list[dict]] = {}
    for index, item in enumerate(items):
        material = _material(item)
        for clause in clauses(item.get("prep") or ""):
            _clause_hits(clause, index, material, sex, adult, found)
        # The sample itself says what to bring, whatever the text adds.
        if "сеч" in material:
            found.setdefault("urine_24h" if "добов" in material else "urine", []).append({"item": index, "value": None})
        if re.search(r"\bкал\b", material):
            found.setdefault("stool", []).append({"item": index, "value": None})
    return found


def _value(rule: dict, clause: str):
    if rule["kind"] == "variant":
        return rule["value"](clause)
    if rule["kind"] == "flag":
        return None
    scope = " ".join(match.group(0) for match in rule["dur"].finditer(clause)) if rule["dur"] else clause
    found = durations(scope)
    if not found:
        return None
    if rule["kind"] == "range":
        return max(found, key=lambda d: (minutes(d, high=False), minutes(d)))
    pick = min if rule["kind"] == "min" else max
    best = pick(found, key=minutes)
    return (best[1], best[1], best[2])


# --- the checklist --------------------------------------------------------------------

#: A rule asked by more tests than this (or by every test in the plan) is
#: the visit's own rule; asked by fewer it belongs to those tests' lines.
# ponytail: a fixed cut-off; a share of the plan if plans grow far beyond ~40 items.
FEW = 3

#: What a person calls the test a line is for, matched in the item's name,
#: the names of the results it reports and its sample.  The first that matches wins,
#: unless the rule prefers another (PREFER); none: the result's own name.
TOPICS = (
    ("psa", r"\bпса\b|\bpsa\b|простат"),
    ("thyroglobulin", r"тиреоглобулін(?!у)|\(тг|\bтг\)"),
    ("cortisol", r"кортизол"),
    ("prolactin", r"пролактин"),
    ("coprogram", r"копрограм"),
    ("urine_culture", r"посів[^;]*сеч|бакпосів"),
    ("swab", r"урогеніт|зішкріб|мазок"),
    ("urine_24h", r"добов"),
    ("acr", r"альбумін-креатинін|альбумін у сечі"),
    ("urinalysis", r"аналіз сечі|\(зас"),
    ("hormones", r"\bфсг\b|\bлг\b|естрадіол|тестостерон|прогестерон"),
)
_HORMONE_TIMING = ("cortisol", "prolactin", "hormones")
PREFER = {"time": _HORMONE_TIMING, "rest": _HORMONE_TIMING, "wake_within": _HORMONE_TIMING,
          "wake_after": _HORMONE_TIMING, "sex": ("psa", "prolactin", "hormones"),
          "heat": ("psa", "prolactin", "hormones")}
#: Rules that name their own analyte, whatever the item is called.
FIXED = {"psa": "psa", "psa_biopsy": "psa", "cycling": "psa", "thyroid_scan": "thyroglobulin",
         "thyroid_surgery": "thyroglobulin"}

#: Rules that can be the whole visit's (fasting, the day before, when to come).
GENERAL = ("fasting", "alcohol", "smoking", "exercise", "heat", "sex", "rest", "wake_within", "wake_after")
#: The abstentions, in the order they are listed; the one carrying its own
#: «і» / «or» goes last so a list never reads «X і Y і Z».
ABSTAIN = ("alcohol", "smoking", "heat", "sex", "cycling", "exercise")
#: A test's own line, waits first, then its abstentions.
WAITS = ("fasting", "time", "wake_within", "wake_after", "rest", "psa", "psa_biopsy", "thyroid_scan",
         "thyroid_surgery")
KIND = {rule["name"]: rule["kind"] for rule in RULES}


def _key(kind: str):
    if kind == "range":
        return lambda v: (minutes(v, high=False), minutes(v))
    if kind == "min":
        return lambda v: -minutes(v)
    return minutes


def _strictest(entries: list[dict], kind: str) -> tuple[object, set[int], object]:
    """``(strictest value, items that need it, the value for every other item)``;
    the last is None when the strictest one is the plan's own rule."""
    valued = [e for e in entries if e["value"] is not None]
    if not valued:
        return None, set(), None
    key = _key(kind)
    best = max((e["value"] for e in valued), key=key)
    needing = {e["item"] for e in valued if key(e["value"]) == key(best)}
    rest = [e["value"] for e in valued if e["item"] not in needing]
    if rest and len(needing) <= FEW:
        return best, needing, max(rest, key=key)
    return best, set(), None


def topic(item: dict, rule: str | None = None) -> str:
    """The short name a person knows the test by: «ПСА», «Кортизол»."""
    if rule in FIXED:
        return t(f"plan.prep_topic_{FIXED[rule]}")
    text = " ".join([item.get("name") or ""] + [p.get("name") or "" for p in item.get("parameters") or []]
                    + list(item.get("material") or [])).casefold()
    own = [name for name, pattern in TOPICS if re.search(pattern, text)]
    chosen = next((name for name in PREFER.get(rule, ()) if name in own), own[0] if own else None)
    if chosen:
        return t(f"plan.prep_topic_{chosen}")
    covers = item.get("covers_names") or []
    return covers[0] if covers else item.get("label") or item.get("name") or ""


def _join(words: list[str]) -> str:
    """«алкоголю, паління, навантажень і стресу»; the last word may carry
    its own conjunction, then commas only."""
    conj = f" {t('plan.prep_and')} "
    if len(words) < 2 or conj in words[-1]:
        return ", ".join(words)
    return ", ".join(words[:-1]) + conj + words[-1]


def _abstain(values: dict[str, tuple]) -> list[tuple[tuple, str]]:
    """``[(duration, «3 дні без велосипеда і сауни»)]``, one per duration."""
    by: dict[int, list] = {}
    for name in ABSTAIN:
        if values.get(name):
            by.setdefault(minutes(values[name]), [values[name], []])[1].append(t(f"plan.prep_noun_{name}"))
    return [(value, _join(nouns)) for _, (value, nouns) in sorted(by.items())]


def _give(specific: dict[str, dict], items: list[dict], rule: str, index: int, value) -> None:
    slot = specific.setdefault(topic(items[index], rule), {})
    if value is None:
        slot.setdefault(rule, None)
    elif KIND[rule] == "variant":
        slot[rule] = slot.get(rule) or value
    elif slot.get(rule) is None or _key(KIND[rule])(value) > _key(KIND[rule])(slot[rule]):
        slot[rule] = value


def _specific_entries(rule: str, entries: list[dict], n: int, general: dict, dieting: set) -> list[dict]:
    """The entries that keep a rule on their own line: all of them, unless most of the visit asks the rule,
    which makes it general (at its usual number) and leaves only the tests that need a stricter one."""
    indexes = {e["item"] for e in entries}
    if rule not in GENERAL or not (len(indexes) > FEW or len(indexes) == n):
        return entries
    best, needing, base = _strictest(entries, KIND[rule])
    general[rule] = base if base is not None else best
    return [e for e in entries if e["item"] in needing and not (rule == "alcohol" and e["item"] in dieting)]


def _topics(items: list[dict], found: dict[str, list[dict]]) -> tuple[dict, dict]:
    """``(the visit's own values, {topic: {rule: value}})``: a rule most tests
    ask stays general at its usual number and a stricter number a few tests
    need moves to those tests' lines; a rule only a few tests ask is theirs."""
    n = len(items)
    general: dict[str, object] = {}
    specific: dict[str, dict] = {}
    # A stool test's own diet already bans alcohol for its days.
    dieting = {e["item"] for e in found.get("stool_diet", [])}
    for rule in WAITS + ABSTAIN:
        entries = found.get(rule, [])
        if not entries:
            continue
        for e in _specific_entries(rule, entries, n, general, dieting):
            _give(specific, items, rule, e["item"], e["value"])
    return general, specific


def _topic_line(name: str, slot: dict) -> str | None:
    waits = []
    for rule in WAITS:
        value = slot.get(rule)
        if not value:
            continue
        if rule == "psa_biopsy" and slot.get("psa") and minutes(value) <= minutes(slot["psa"]):
            continue  # «any urological procedure» already covers the biopsy
        if rule == "time":
            waits.append(t("plan.prep_part_time", times=f" {t('plan.prep_or')} ".join(value)))
        else:
            waits.append(t(f"plan.prep_part_{rule}", d=fmt(value)))
    abstain = [t("plan.prep_part_abstain", d=fmt(value), list=nouns) for value, nouns in _abstain(slot)]
    parts = [", ".join(chunk) for chunk in (waits, abstain) if chunk]
    return "; ".join(parts) or None


def _infant_water_lines(items: list[dict], found, value) -> list[str]:
    lines = []
    for name in ("infant_fasting", "toddler_fasting", "child_water"):
        if name in found and value(name):
            ml = next((m for e in found[name] for m in re.findall(r"(?<!\d)(\d\d*+-\d++)\s*+мл", " ".join(
                clauses(items[e["item"]].get("prep") or "")))), "")
            lines.append(t(f"plan.prep_rule_{name}", d=fmt(value(name)), ml=ml))
    return lines


def _whole_rules(items: list[dict], found, general, value) -> list[str]:
    whole = []
    if "fasting" in general:
        text = t("plan.prep_rule_fasting", d=fmt(general["fasting"])) if general["fasting"] \
            else t("plan.prep_rule_fasting_plain")
        whole.append(text + (" " + t("plan.prep_rule_water") if "water" in found else ""))
    for duration, nouns in _abstain(general):
        whole.append(t("plan.prep_rule_abstain", d=fmt(duration), list=nouns))
    if "medicines" in found:
        whole.append(t("plan.prep_rule_medicines"))
    when = [t(f"plan.prep_part_{rule}", d=fmt(general[rule]))
            for rule in ("wake_within", "wake_after", "rest") if general.get(rule)]
    if "morning" in found or when:
        whole.append(t("plan.prep_rule_when", parts=", ".join([t("plan.prep_when_morning")] * ("morning" in found) + when)))
    whole += _infant_water_lines(items, found, value)
    if "infant_feed" in found:
        whole.append(t("plan.prep_rule_infant_feed"))
    return whole


def _topic_lines(specific: dict) -> list[str]:
    order = [t(f"plan.prep_topic_{name}") for name, _ in TOPICS]
    # Tests asking the very same thing share a line: «КФК, ЛДГ: натщесерце 12 год».
    same: dict[str, list[str]] = {}
    for name in sorted(specific, key=lambda name: (order.index(name) if name in order else len(order), name)):
        parts = _topic_line(name, specific[name])
        if parts:
            same.setdefault(parts, []).append(name)
    return [t("plan.prep_rule_topic", topic=", ".join(names), parts=parts) for parts, names in same.items()]


def _drug_lines(items: list[dict], found, names, value) -> list[str]:
    tests = []
    if "antibiotics" in found:
        tests.append(t("plan.prep_rule_antibiotics", d=fmt(value("antibiotics")), tests=names("antibiotics"))
                     if value("antibiotics") else t("plan.prep_rule_antibiotics_plain", tests=names("antibiotics")))
    if "biotin" in found:
        doses = [m for e in found["biotin"] for m in re.findall(r">\s*(\d+)\s*мг", (items[e["item"]].get("prep") or "").casefold())]
        tests.append(t("plan.prep_rule_biotin", d=fmt(value("biotin")), mg=max(doses, key=int))
                     if value("biotin") and doses else t("plan.prep_rule_biotin_plain"))
    if "menstruation" in found:
        tests.append(t("plan.prep_rule_menstruation", d=fmt(value("menstruation"))) if value("menstruation")
                     else t("plan.prep_rule_menstruation_plain"))
    return tests


def _weekday_text(days: tuple) -> str:
    span = len(days) > 2 and days == tuple(range(days[0], days[-1] + 1))
    if span:
        return "-".join(t(f"plan.prep_weekday_{d}") for d in (days[0], days[-1]))
    return ", ".join(t(f"plan.prep_weekday_{d}") for d in days)


def _cycle_lines(items: list[dict], found) -> list[str]:
    tests = [t("plan.prep_rule_cycle_day", days=days)
             for days in dict.fromkeys(e["value"] for e in found.get("cycle_day", []) if e["value"])]
    for days in dict.fromkeys(e["value"] for e in found.get("weekdays", []) if e["value"]):
        own = ", ".join(dict.fromkeys(topic(items[e["item"]]) for e in found["weekdays"] if e["value"] == days))
        tests.append(t("plan.prep_rule_weekdays", days=_weekday_text(days), tests=own))
    return tests


def _referral_lines(found, names) -> list[str]:
    return [t(f"plan.prep_rule_{name}", tests=names(name))
            for name in ("some_points", "referral", "doctor", "bring") if name in found]


def sections(items: list[dict], found: dict[str, list[dict]]) -> list[dict]:
    """``[{"key", "heading", "lines"}]``: for the whole visit, the samples to
    bring, then what particular tests ask, each line short and named by the
    analyte, never by the package that carries it."""
    general, specific = _topics(items, found)

    def names(rule: str) -> str:
        return ", ".join(dict.fromkeys(topic(items[e["item"]], rule) for e in found[rule]))

    def value(rule: str):
        return _strictest(found[rule], KIND[rule])[0]

    whole = _whole_rules(items, found, general, value)
    samples: list[str] = []
    _samples(found, samples.append, value)
    tests = (_topic_lines(specific) + _drug_lines(items, found, names, value)
             + _cycle_lines(items, found) + _referral_lines(found, names))
    return [{"key": key, "heading": t(f"plan.prep_group_{key}"), "lines": found_lines}
            for key, found_lines in (("general", whole), ("samples", samples), ("tests", tests)) if found_lines]


def _step_key(part: str, name: str) -> str:
    if part == "sterile":
        return "plan.prep_sample_sterile"
    return f"plan.prep_{name}"


def _sample_steps(sample: str, parts: tuple, found, value) -> tuple[list, list]:
    before, said = [], [t("plan.prep_sample_home")]
    for part in parts:
        name = f"{sample}_{part}"
        if name not in found:
            continue
        if part in ("procedures", "diet"):
            if value(name):
                before.append(t(f"plan.prep_{name}", d=fmt(value(name))))
        elif part == "food":
            before.append(t(f"plan.prep_{name}"))
        elif part == "midstream" and "urine_morning" in found:
            said[-1] = t("plan.prep_urine_morning_midstream")
        else:
            said.append(t(_step_key(part, name)))
    return before, said


def _sample_line(sample: str, parts: tuple, found, value) -> str:
    before, said = _sample_steps(sample, parts, found, value)
    within = value(f"{sample}_within") if f"{sample}_within" in found else None
    if within:
        said.append(t("plan.prep_sample_within", d=fmt(within)))
    elif f"{sample}_now" in found:
        said.append(t("plan.prep_sample_now"))
    return t(f"plan.prep_rule_{sample}", parts="; ".join(", ".join(part) for part in (before, said) if part))


def _samples(found, add, value) -> None:
    """One line per sample to bring: what to do in the days before, then how
    to collect it: «Сеча: напередодні без буряка...; зберіть удома й принесіть, ...»."""
    for sample, parts in (("urine", ("food", "morning", "midstream", "wash", "tampon", "sterile")),
                          ("stool", ("procedures", "diet", "fresh", "sterile", "enema"))):
        if sample not in found:
            continue
        add(_sample_line(sample, parts, found, value))
    for name in ("urine_24h", "urine_first"):
        if name in found:
            add(t(f"plan.prep_rule_{name}"))


def gist(found: dict[str, list[dict]]) -> str:
    """The summary line: «Натщесерце 8-12 год, зранку, зразок сечі»."""
    parts = []
    if "fasting" in found:
        # One visit, one draw: the strictest window is the one to keep.
        value = _strictest(found["fasting"], "range")[0]
        parts.append(t("plan.prep_gist_fasting", d=fmt(value)) if value else t("plan.prep_gist_fasting_plain"))
    if "morning" in found:
        parts.append(t("plan.prep_gist_morning"))
    if "urine" in found or "urine_24h" in found:
        parts.append(t("plan.prep_gist_urine"))
    if "stool" in found:
        parts.append(t("plan.prep_gist_stool"))
    text = ", ".join(parts)
    return text[:1].upper() + text[1:]


def checklist(items: list[dict], *, sex: str | None, adult: bool, vendors: dict[str, str]) -> dict:
    """``{"gist", "groups": [{"vendor", "sections": [{"key", "heading", "lines"}]}]}``
    for one plan's items (``prep`` holding each one's text).  A plan from two
    labs is listed per lab only when their checklists differ."""
    labs = list(dict.fromkeys(item["lab"] for item in items))
    every = hits(items, sex, adult)
    per_lab = {}
    if len(labs) > 1:
        for lab in labs:
            own = [item for item in items if item["lab"] == lab]
            per_lab[lab] = sections(own, hits(own, sex, adult))
    if len({str([s["lines"] for s in found]) for found in per_lab.values()}) > 1:
        groups = [{"vendor": vendors.get(lab, lab), "sections": found} for lab, found in per_lab.items() if found]
    else:
        found = sections(items, every)
        groups = [{"vendor": None, "sections": found}] if found else []
    return {"gist": gist(every), "groups": groups}
