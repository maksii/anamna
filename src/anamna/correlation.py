"""How one measurement moves with another, and how strongly.

**Method.** Spearman's rank correlation, computed with the standard library's
``statistics.correlation(..., method="ranked")``.  Spearman rather than Pearson
for two reasons this record supplies daily:

* *Outliers.* The device history holds 51 000-step travel days and 0.02-hour
  sleep artefacts from a watch that was taken off mid-night.  Pearson squares
  the distance to the mean, so a handful of those days can invent or erase an
  association across three thousand honest ones.  Ranking flattens them to "the
  largest value", which is all they reliably are.
* *Shape.* A relationship between sleep and resting heart rate is monotonic
  long before it is linear.  Spearman answers "when one goes up, does the other
  follow?", which is the question the interface actually asks on the page.

**Strength wording** follows Schober P, Boer C, Schwarte LA. *Correlation
Coefficients: Appropriate Use and Interpretation.* Anesthesia & Analgesia.
2018;126(5):1763-1768. doi:10.1213/ANE.0000000000002864 —
https://doi.org/10.1213/ANE.0000000000002864 — whose bands are |r| < 0.10
negligible, < 0.40 weak, < 0.70 moderate, < 0.90 strong, otherwise very strong.
The same paper is cited to the reader in the explanation block, because a
number labelled "moderate" with nobody behind the label is an opinion.

Nothing here touches a database, a request or a locale: a series is a list of
``(day, value)`` and a day is the join key throughout.  Correlation is not
causation and this module cannot know the difference — the interface says so
in words, next to every number it prints.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, timedelta
import statistics

from .panels import MEASUREMENT_TWINS

#: One value per day, ascending by day.  ``day`` is ``YYYY-MM-DD``.
Series = list[tuple[str, float]]
#: ``(day, primary_value, companion_value)``.
Pair = tuple[str, float, float]


#: How a companion reading is matched to a primary reading.
ALIGNMENTS = ("same_day", "prev_day", "avg7", "avg30")

#: The trailing window each averaging alignment uses, in calendar days.
WINDOW_DAYS = {"avg7": 7, "avg30": 30}

#: A trailing average over one or two recorded days is not an average, it is
#: one of those days wearing a wider label.  Below this the pair is dropped.
MIN_WINDOW_DAYS = 3

#: Fewer overlapping days than this and the explorer refuses to draw: with five
#: points a rank correlation can reach ±1.0 on noise alone.
MIN_PAIRS_EXPLORER = 6

#: Schober et al. 2018, Table 1.  Read as "|r| below this cutoff is called...".
STRENGTH_BANDS = ((0.10, "negligible"), (0.40, "weak"), (0.70, "moderate"), (0.90, "strong"))


def _device(key: str) -> str:
    """The catalog id of a device metric — the same id the pages and API use."""
    return f"device:{key}"


def _pairs_with(one: str, others: tuple[str, ...]) -> set[frozenset[str]]:
    return {frozenset((one, other)) for other in others}


_SLEEP_STAGES = ("sleep_core", "sleep_rem", "sleep_deep", "sleep_awake")

# ponytail: curated by hand, and it grows as noise shows up on the page. There
# is no derivation rule to write here — "steps and walking distance are the same
# walk" is domain knowledge, not something the schema records. A pair listed
# here is only withheld from the *suggestions*; the picker still offers it, so
# nothing becomes unreachable, and a wrong entry costs a suggestion rather than
# an answer. Upgrade path if it ever gets long: a `derived_from` column on the
# metric definition, which nothing needs today.
#: Pairs where a strong correlation is arithmetic rather than a finding: one
#: metric is computed from the other, so "steps and walking distance move
#: together" is a restatement of how they were recorded, not something learned.
TRIVIAL_PAIRS: frozenset[frozenset[str]] = frozenset(
    _pairs_with(_device("steps"), (_device("walking_running_distance"),))
    | _pairs_with(
        _device("sleep_duration"),
        (_device("time_in_bed"), *(_device(stage) for stage in _SLEEP_STAGES)),
    )
    | _pairs_with(_device("time_in_bed"), tuple(_device(stage) for stage in _SLEEP_STAGES))
    # Weight and the BMI computed from it; read under the concept id now that
    # the scale's days live on the concept page.
    | _pairs_with("body-weight", ("body-mass-index", _device("lean_body_mass")))
    | _pairs_with(_device("walking_speed"), (_device("walking_step_length"),))
    | _pairs_with(_device("daily_heart_rate"), (_device("walking_heart_rate"),))
    # A concept and its device twin are one quantity reaching the record by
    # two paths, so correlating them measures the import, not the person.
    # A merely related pair (clinic pulse, watch resting rate) is a finding.
    | {
        frozenset((concept_id, _device(key)))
        for concept_id, twins in MEASUREMENT_TWINS.items()
        for key, relation in twins
        if relation in {"same", "method"}
    }
)


def _ordinal(day: str) -> int:
    return date.fromisoformat(day).toordinal()


def averaged_side(primary: Series, companion: Series, align: str) -> str | None:
    """Which of the two series gets the trailing mean — the denser one.

    ``None`` for the day-join alignments, which average nothing.

    The rule is "average the side that has more days", and the reason is that
    the other way round produces nothing at all.  Averaging the *companion*
    around each primary reading works only while the companion is the
    frequently-measured one: ask for the 30-day mean of a lipid panel around
    each of 150 blood-pressure days and every window holds one draw or none,
    the three-day minimum drops every pair, and a page that should read
    "cholesterol against the month of blood pressure before it" reads "fewer
    than six days carry both measurements".  Anchoring on the sparser series
    asks the question the reader meant either way round.
    """
    if align not in WINDOW_DAYS or not primary or not companion:
        return None
    # Tie goes to the primary as the anchor, so a page compared against a
    # metric of equal length keeps its own readings as the fixed points.
    return "companion" if len(primary) <= len(companion) else "primary"


def align_pairs(primary: Series, companion: Series, align: str) -> list[Pair]:
    """Match the two series up day by day, ready to correlate.

    ``same_day`` is an inner join and ``prev_day`` joins the day before, both
    of which need the two metrics measured at a similar cadence.  ``avg7`` and
    ``avg30`` are what make a twice-yearly blood draw comparable with a daily
    wearable: the *sparser* series anchors, each of its readings keeping its
    own value, and the denser one contributes its trailing mean over
    ``[d-(w-1), d]`` — "the month of sleep before this test", or equally "the
    month of blood pressure before this cholesterol result".

    Whichever side was averaged, a pair is always
    ``(day, primary_value, companion_value)``: callers correlate and plot in
    terms of the metric whose page they are on, and must never have to ask
    which way round the arguments came back.
    """
    if align not in ALIGNMENTS:
        raise ValueError(f"unknown alignment: {align}")
    if not primary or not companion:
        return []
    primary = sorted(primary)
    companion = sorted(companion)

    if align in ("same_day", "prev_day"):
        return _day_join(primary, companion, align)

    window = WINDOW_DAYS[align]
    anchored_on_primary = averaged_side(primary, companion, align) == "companion"
    anchor, averaged = (primary, companion) if anchored_on_primary else (companion, primary)
    days = [_ordinal(day) for day, _ in averaged]
    values = [value for _, value in averaged]
    matched = []
    for day, value in anchor:
        end = _ordinal(day)
        # Inclusive at both ends: avg7 over [d-6, d] is seven calendar days,
        # the seventh of which is the anchor reading's own day.
        low = bisect_left(days, end - window + 1)
        high = bisect_right(days, end)
        # The minimum is a rule about the *mean*, so it applies to the side
        # being averaged and never to the single anchor reading.
        if high - low < MIN_WINDOW_DAYS:
            continue
        mean = statistics.fmean(values[low:high])
        matched.append((day, value, mean) if anchored_on_primary else (day, mean, value))
    return matched


def _day_join(primary: Series, companion: Series, align: str) -> list[Pair]:
    """``same_day`` / ``prev_day``: each primary day joined to one companion day."""
    offset = timedelta(days=1 if align == "prev_day" else 0)
    lookup = dict(companion)
    matched = []
    for day, value in primary:
        other = lookup.get((date.fromisoformat(day) - offset).isoformat())
        if other is not None:
            matched.append((day, value, other))
    return matched


def _direction(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "none"


def rolling_mean_series(series: Series, window: int) -> Series:
    """Trailing mean over the days actually recorded, one point per input day.

    Deliberately without ``MIN_WINDOW_DAYS``: this draws the curve the reader
    sees, it is not the statistic.  Dropping the first fortnight of a 30-day
    mean would leave a gap at the left edge of every chart with no reader-
    visible reason for it, and no coefficient is computed from this output.
    """
    series = sorted(series)
    days = [_ordinal(day) for day, _ in series]
    values = [value for _, value in series]
    return [
        (day, statistics.fmean(values[bisect_left(days, days[index] - window + 1) : index + 1]))
        for index, (day, _) in enumerate(series)
    ]


def strength(r: float | None) -> str:
    """Schober's word for this coefficient's magnitude."""
    if r is None:
        return "none"
    magnitude = abs(r)
    for cutoff, name in STRENGTH_BANDS:
        if magnitude < cutoff:
            return name
    return "very_strong"


def correlate(pairs: list[Pair]) -> dict[str, object]:
    """Spearman's rho over every pair, with the word that describes it.

    ``r`` is ``None`` rather than 0.0 when there is nothing to compute — one
    pair, or a series that never changes.  A constant series has no ranks to
    correlate, and reporting 0.0 would claim "no association" where the honest
    answer is "no measurement".
    """
    count = len(pairs)
    unknown = {"n": count, "r": None, "strength": "none", "direction": "none"}
    if count < 2:
        return unknown
    try:
        value = statistics.correlation(
            [pair[1] for pair in pairs], [pair[2] for pair in pairs], method="ranked"  # NOSONAR python:S930 -- method= exists since Python 3.12, which pyproject requires
        )
    except statistics.StatisticsError:
        return unknown
    return {
        "n": count,
        "r": value,
        "strength": strength(value),
        "direction": _direction(value),
    }


def regression(pairs: list[Pair]) -> dict[str, float] | None:
    """Least-squares line for the scatter view: companion is X, primary is Y."""
    if len(pairs) < 2:
        return None
    try:
        line = statistics.linear_regression([pair[2] for pair in pairs], [pair[1] for pair in pairs])
    except statistics.StatisticsError:
        return None
    return {"slope": line.slope, "intercept": line.intercept}


def sample_evenly(items: list, limit: int = 400) -> list:
    """Thin any day-ordered list to at most ``limit``, keeping first and last.

    Used for both the scatter's pairs and each drawn series, which is why it
    takes a plain list rather than one shape.

    Never bucket means: averaging a scatter shrinks its spread, and a tighter
    cloud reads as a stronger relationship than the data supports.  ``r`` and
    ``n`` are computed on the full set before this runs, so the number under
    the chart always describes every day and only the drawing is thinned.
    """
    if limit < 2 or len(items) <= limit:
        return items
    step = (len(items) - 1) / (limit - 1)
    return [items[round(index * step)] for index in range(limit)]


def suggest(
    primary_id: str,
    primary_series: Series,
    candidates: dict[str, Series],
    align: str,
    *,
    min_pairs: int = 8,
    min_abs_r: float = 0.15,
    top: int = 5,
) -> list[dict[str, object]]:
    """The companions worth offering unprompted, strongest first.

    A suggestion is a claim the page makes on its own, so the bar is higher
    than the explorer's: enough overlapping days to mean something, and enough
    signal to be worth a reader's attention.  Trivial pairs are skipped here
    and here only — the picker still offers them.
    """
    found: list[dict[str, object]] = []
    for candidate_id, series in candidates.items():
        if candidate_id == primary_id:
            continue
        if frozenset((primary_id, candidate_id)) in TRIVIAL_PAIRS:
            continue
        summary = correlate(align_pairs(primary_series, series, align))
        r = summary["r"]
        if r is None or summary["n"] < min_pairs or abs(float(r)) < min_abs_r:
            continue
        found.append({"id": candidate_id, **summary})
    # Ties broken by id so the same record always produces the same page.
    found.sort(key=lambda item: (-abs(float(item["r"])), str(item["id"])))
    return found[:top]
