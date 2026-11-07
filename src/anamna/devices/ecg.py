"""Electrocardiogram waveforms: read the samples, then measure them.

Two devices write the same recording in two shapes.  Kardia prints a PDF whose
traces survive as vector polylines, calibrated by the ``25mm/s, 10mm/mV`` line
the report itself carries; Apple exports one CSV of microvolts per recording.
Both are read here into millivolts on a common timebase, so one beat detector
produces one set of measurements whichever device recorded the strip.

Nothing here is a diagnosis.  The measurements are geometry - where the R peaks
fall and how far apart they are - and the vendor's own rhythm determination is
carried through untouched beside them.
"""

from __future__ import annotations

import csv
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Iterable
from functools import lru_cache
from html import escape
from pathlib import Path

import pdfplumber
from markupsafe import Markup
from pdfplumber.utils.exceptions import PdfminerException

from ..i18n import format_number_localized, t


#: PDF user-space units per millimetre (72 dpi against the 25.4 mm inch).
PT_PER_MM = 72 / 25.4

#: Kardia 6L prints the limb leads in this order down the page.
LEAD_ORDER = ("I", "II", "III", "aVR", "aVL", "aVF")

#: The paper speed and gain the report states.  Kardia has never shipped
#: anything but 25mm/s and 10mm/mV, but the value is read rather than assumed
#: so a differently calibrated export cannot be silently mis-scaled.
SCALE = re.compile(r"Scale:\s*([\d.]+)\s*mm/s\s*,\s*([\d.]+)\s*mm/mV", re.I)
FILTER_LINE = re.compile(r"((?:Enhanced|Standard|Basic)\s+Filter[^\n]*)", re.I)
DEFAULT_MM_PER_SECOND = 25.0
DEFAULT_MM_PER_MV = 10.0

#: A physiologic beat-to-beat interval.  Anything outside is a detection
#: artefact and is excluded from the interval statistics rather than reported.
MIN_RR_SECONDS = 0.30  # 200 bpm
MAX_RR_SECONDS = 2.40  # 25 bpm


@dataclass(frozen=True)
class Recording:
    """One ECG strip: the metadata printed on it and the samples under it."""

    recorded_at: str
    device: str
    vendor: str
    classification: str
    sample_rate: float
    #: Lead name -> millivolts, one entry per sample, in recording order.
    leads: dict[str, list[float]] = field(default_factory=dict)
    #: The calibration the report stated, carried as the two numbers it is
    #: rather than as prose to be parsed back out.  Handing the drawing code a
    #: string and having it re-read the string is how a differently calibrated
    #: export gets silently drawn at the default gain.
    mm_per_second: float = DEFAULT_MM_PER_SECOND
    mm_per_mv: float = DEFAULT_MM_PER_MV
    filter_text: str = ""
    symptoms: str = ""
    source_file: str = ""

    @property
    def scale_text(self) -> str:
        # Display text, so it follows the reader's locale: "25 мм/с, 10 мм/мВ".
        return t(
            "ecg.scale_text",
            speed=format_number_localized(self.mm_per_second, 2),
            gain=format_number_localized(self.mm_per_mv, 2),
        )

    @property
    def sample_count(self) -> int:
        return max((len(samples) for samples in self.leads.values()), default=0)

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / self.sample_rate if self.sample_rate else 0.0

    @property
    def primary_lead(self) -> str:
        """The lead a determination is read on: lead I when it is present."""
        return "I" if "I" in self.leads else next(iter(self.leads), "")


# --- Kardia PDF --------------------------------------------------------------


def _lead_baselines(page) -> dict[str, float]:
    """Lead name -> the y of its printed label, which sits on its baseline.

    The label is a far steadier anchor than the grid: the 1 mm gridlines run the
    full page width and there are hundreds of them, while each lead is named
    exactly once in the left margin.
    """
    baselines: dict[str, float] = {}
    for word in page.extract_words():
        name = word["text"]
        if name in LEAD_ORDER and word["x0"] < 100 and name not in baselines:
            baselines[name] = (word["top"] + word["bottom"]) / 2
    return baselines


def _trace_segments(page) -> list[dict[str, object]]:
    """The waveform polyline segments, in draw order.

    The trace is stroked as one short segment per sample in a plain black with
    a scalar colour; the calibration pulse and the chart axes on the summary
    pages use an explicit RGB black, and the grid is grey or lavender.
    """
    return [
        line
        for line in page.lines
        if line.get("stroking_color") == 0 and 0 < abs(line["x1"] - line["x0"]) < 1
    ]


def _polyline(segments: list[dict[str, object]]) -> list[tuple[float, float]]:
    """Chain per-sample segments back into the (x, y) points that drew them.

    ``pdfplumber`` normalises every line to a bounding box, so ``y0``/``y1``
    lose which end belongs to which x; ``pts`` keeps the original order and is
    used instead.  Consecutive segments share a point, which is emitted once.
    """
    points: list[tuple[float, float]] = []
    for segment in segments:
        pts = segment.get("pts") or ()
        if len(pts) < 2:
            continue
        start, end = pts[0], pts[-1]
        if not points or points[-1] != start:
            points.append((float(start[0]), float(start[1])))
        points.append((float(end[0]), float(end[1])))
    return points


def _place_page(
    by_lead: dict[str, list[tuple[float, float]]],
    page_points: dict[str, list[dict[str, object]]],
    left: float,
    offset: float,
) -> float:
    """Append one page's points to each lead, shifted to follow the previous page.

    Returns the width the page consumed.
    """
    width = 0.0
    for name, page_segments in page_points.items():
        points = _polyline(page_segments)
        width = max(width, max(x for x, _ in points) - left)
        by_lead.setdefault(name, []).extend((x - left + offset, y) for x, y in points)
    return width


def _read_pages(pages) -> tuple[str, float, float, dict[str, list[tuple[float, float]]]]:
    """The header text, printed calibration and per-lead (x, y) points of every page."""
    header = ""
    mm_per_second, mm_per_mv = DEFAULT_MM_PER_SECOND, DEFAULT_MM_PER_MV
    by_lead: dict[str, list[tuple[float, float]]] = {}
    page_widths: list[float] = []
    for page in pages:
        segments = _trace_segments(page)
        baselines = _lead_baselines(page)
        if not segments or not baselines:
            continue
        if not header:
            header = page.extract_text() or ""
            scale = SCALE.search(header)
            if scale:
                mm_per_second, mm_per_mv = float(scale.group(1)), float(scale.group(2))
        # A page holds one time window of every lead; the next page
        # continues it, so the offset is the width already consumed.
        left, page_points = _assign_to_leads(segments, baselines)
        page_widths.append(_place_page(by_lead, page_points, left, sum(page_widths)))
    return header, mm_per_second, mm_per_mv, by_lead


def read_kardia_pdf(path: Path) -> Recording | None:
    """Read a Kardia ECG report into millivolt samples, or ``None``.

    ``None`` means the PDF carries no recoverable trace - a scanned or
    flattened export, say - which is a normal outcome and never an error: the
    printed heart rate and determination are still read elsewhere.
    """
    with pdfplumber.open(path) as pdf:
        cover = pdf.pages[0].extract_text() or "" if pdf.pages else ""
        header, mm_per_second, mm_per_mv, by_lead = _read_pages(pdf.pages)

    if not by_lead:
        return None

    pt_per_second = PT_PER_MM * mm_per_second
    pt_per_mv = PT_PER_MM * mm_per_mv
    rate = _sample_rate(by_lead, pt_per_second)
    leads: dict[str, list[float]] = {}
    for name in LEAD_ORDER:
        points = by_lead.get(name)
        if not points:
            continue
        # The isoelectric line dominates a strip, so its median is the zero
        # level; it also absorbs the baseline wander a fixed grid row cannot.
        baseline = statistics.median([y for _, y in points])
        # y grows downward in PDF space, so a rising R wave is a falling y.
        leads[name] = [(baseline - y) / pt_per_mv for _, y in points]

    recorded = _kardia_recorded_at(cover or header)
    determination = re.search(r"Kardia Advanced Determination:\s*([^\r\n*]+)", cover or header, re.I)
    filters = FILTER_LINE.search(header)
    return Recording(
        recorded_at=recorded or "",
        device="Kardia 6L" if len(leads) > 1 else "Kardia",
        vendor="Kardia",
        classification=determination.group(1).strip() if determination else "Unclassified",
        sample_rate=rate,
        leads=leads,
        mm_per_second=mm_per_second,
        mm_per_mv=mm_per_mv,
        # The calibration is printed on the same line as the filters and is
        # carried separately, so it is cut out of the filter description here
        # rather than repeated in both fields.
        filter_text=SCALE.sub("", filters.group(1)).strip(" ,") if filters else "",
        source_file=str(path),
    )


def _nearest_lead(centre: float, baselines: dict[str, float], spacing: float) -> str | None:
    name = min(baselines, key=lambda key: abs(centre - baselines[key]))
    return name if abs(centre - baselines[name]) <= spacing else None


def _assign_to_leads(
    segments: list[dict[str, object]], baselines: dict[str, float]
) -> tuple[float, dict[str, list[dict[str, object]]]]:
    """Group a page's segments by the lead band they sit in, with the left edge."""
    spacing = _band_spacing(baselines)
    left = min(segment["x0"] for segment in segments)
    page_points: dict[str, list[dict[str, object]]] = {}
    for segment in segments:
        name = _nearest_lead((segment["top"] + segment["bottom"]) / 2, baselines, spacing)
        if name is not None:
            page_points.setdefault(name, []).append(segment)
    return left, page_points


def _band_spacing(baselines: dict[str, float]) -> float:
    """Half the distance between neighbouring leads, as an assignment radius."""
    values = sorted(baselines.values())
    if len(values) < 2:
        return math.inf
    gaps = [second - first for first, second in zip(values, values[1:])]
    return min(gaps) / 2


def _sample_rate(by_lead: dict[str, list[tuple[float, float]]], pt_per_second: float) -> float:
    """Samples per second, measured off the plot rather than assumed.

    One sample is one segment of constant width, so the sampling interval is
    read straight from the geometry; a rate within half a percent of a whole
    number is reported as that number.
    """
    xs = [x for x, _ in next(iter(by_lead.values()))]
    steps = sorted(second - first for first, second in zip(xs, xs[1:]) if second > first)
    if not steps:
        return 0.0
    step = steps[len(steps) // 2]
    rate = pt_per_second / step
    rounded = round(rate)
    return float(rounded) if rounded and abs(rate - rounded) / rounded < 0.005 else rate


def _kardia_recorded_at(text: str) -> str | None:
    match = re.search(
        r"([A-Z][a-z]+,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s+[AP]M)", text
    )
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%A, %b %d, %Y, %I:%M %p").isoformat()
    except ValueError:
        return None


# --- Apple Health CSV --------------------------------------------------------


def _decimal(fields: list[str]) -> float | None:
    """A number that may have been split in two by a decimal comma.

    Apple writes the export in the phone's locale, so ``-197,325`` arrives as
    two CSV columns.  Joining them on a point reads both conventions.
    """
    text = ".".join(part.strip() for part in fields if part.strip())
    try:
        return float(re.sub(r"[^\d.eE+-]", "", text))
    except ValueError:
        return None


def _apple_rows(rows: Iterable[list[str]]) -> tuple[dict[str, str], dict[str, list[float]]]:
    """Split an Apple ECG CSV into its ``key,value`` header lines and the samples."""
    metadata: dict[str, str] = {}
    leads: dict[str, list[float]] = {}
    lead = "I"
    unit_scale = 0.001  # the export is microvolts unless it says otherwise
    for row in rows:
        if not row or not row[0].strip():
            continue
        key = row[0].strip()
        sample = _decimal(row) if len(row) < 3 and not key[:1].isalpha() else None
        if sample is not None:
            leads.setdefault(lead, []).append(sample * unit_scale)
            continue
        value = ",".join(row[1:]).strip()
        if key == "Lead":
            lead = _apple_lead_name(value)
        elif key == "Unit":
            unit_scale = _apple_unit_scale(value)
        else:
            metadata[key] = value
    return metadata, leads


def _apple_lead_name(value: str) -> str:
    return value.removeprefix("Lead").strip() or value or "I"


def _apple_unit_scale(value: str) -> float:
    return 1.0 if value.casefold().startswith(("mv", "мв")) else 0.001


def read_apple_csv(path: Path) -> Recording | None:
    """Read one Apple Watch electrocardiogram export into millivolts."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        metadata, leads = _apple_rows(csv.reader(handle))
    if not leads:
        return None

    rate = _decimal(re.sub(r"[^\d.,]", "", metadata.get("Sample Rate", "")).split(",")) or 512.0
    recorded = metadata.get("Recorded Date", "")
    try:
        recorded_at = datetime.strptime(recorded, "%Y-%m-%d %H:%M:%S %z").isoformat()
    except ValueError:
        recorded_at = recorded
    return Recording(
        recorded_at=recorded_at,
        device=metadata.get("Device", "Apple Watch").strip('"'),
        vendor="Apple Health",
        classification=metadata.get("Classification", "Unclassified"),
        sample_rate=rate,
        leads=leads,
        symptoms=metadata.get("Symptoms", ""),
        source_file=str(path),
    )


def read(path: Path) -> Recording | None:
    """Read whichever of the supported ECG file shapes ``path`` holds.

    A file that cannot be opened or carries no trace returns ``None``.  The
    waveform is an enrichment of a record that already stands on its printed
    header, so a scanned, flattened or truncated export must degrade to that
    header rather than fail the import that contains it.
    """
    suffix = path.suffix.casefold()
    try:
        if suffix == ".pdf":
            return read_kardia_pdf(path)
        if suffix == ".csv":
            return read_apple_csv(path)
    except (OSError, ValueError, KeyError, IndexError, TypeError, PdfminerException):
        return None
    return None


@lru_cache(maxsize=8)
def _read_stamped(path: str, modified_ns: int) -> Recording | None:
    return read(Path(path))


def read_cached(path: Path) -> Recording | None:
    """``read`` memoised on the file's modification time.

    Recovering six leads from a Kardia PDF costs a couple of seconds, which is
    fine once per import and not fine once per page view.
    """
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    return _read_stamped(str(path), stamp)


# --- beat detection ----------------------------------------------------------


#: A second complex cannot follow inside the absolute refractory period; one
#: arriving before the relative period is over is a T wave unless it climbs as
#: steeply as the QRS before it.  Both are the Pan-Tompkins constants.
REFRACTORY_SECONDS = 0.20
T_WAVE_SECONDS = 0.36
T_WAVE_SLOPE_RATIO = 0.5


def r_peaks(samples: list[float], rate: float) -> list[int]:
    """Sample indices of the R waves, by a miniature Pan-Tompkins.

    Slope, then energy, then a QRS-width moving sum: each step suppresses the
    P and T waves relative to the QRS, after which one threshold, a refractory
    period and a slope comparison separate the beats from their own T waves.
    """
    count = len(samples)
    if count < rate or rate <= 0:
        return []
    slope = [0.0] * count
    for index in range(2, count - 2):
        slope[index] = (
            2 * samples[index + 2] + samples[index + 1]
            - samples[index - 1] - 2 * samples[index - 2]
        )
    width = max(1, int(0.12 * rate))  # one QRS complex
    energy = [value * value for value in slope]
    integrated = [0.0] * count
    running = 0.0
    for index, value in enumerate(energy):
        running += value
        if index >= width:
            running -= energy[index - width]
        integrated[index] = running

    ranked = sorted(integrated)
    threshold = 0.35 * ranked[int(len(ranked) * 0.99)]
    if threshold <= 0:
        return []
    candidates = _qrs_candidates(samples, slope, integrated, threshold, width)
    return _reject_t_waves(candidates, rate)


def _qrs_candidates(
    samples: list[float], slope: list[float], integrated: list[float], threshold: float, width: int
) -> list[tuple[int, float]]:
    """One (peak, steepness) per above-threshold run of the integrated signal."""
    candidates: list[tuple[int, float]] = []
    start = None
    for index, value in enumerate(integrated):
        if value >= threshold and start is None:
            start = index
        elif value < threshold and start is not None:
            candidates.append(_candidate(samples, slope, start, index, width))
            start = None
    if start is not None:
        candidates.append(_candidate(samples, slope, start, len(samples), width))
    return candidates


def _reject_t_waves(candidates: list[tuple[int, float]], rate: float) -> list[int]:
    """Merge double detections and drop T waves from the candidate complexes."""
    peaks: list[int] = []
    steepness: list[float] = []
    for peak, incline in candidates:
        if peaks:
            gap = (peak - peaks[-1]) / rate
            if gap < REFRACTORY_SECONDS:
                # Two detections of one complex: the steeper one is the R wave.
                if incline > steepness[-1]:
                    peaks[-1], steepness[-1] = peak, incline
                continue
            if gap < T_WAVE_SECONDS and incline < T_WAVE_SLOPE_RATIO * steepness[-1]:
                continue
        peaks.append(peak)
        steepness.append(incline)
    return peaks


def _candidate(
    samples: list[float], slope: list[float], start: int, end: int, width: int
) -> tuple[int, float]:
    """The R wave inside one above-threshold run, and how steeply it rose.

    The moving sum lags the complex it integrates by about its own width, so
    the search window is pulled back before taking the largest deflection.
    """
    low = max(0, start - width)
    high = min(len(samples), end + 1)
    peak = max(range(low, high), key=lambda index: abs(samples[index]))
    return peak, max(abs(value) for value in slope[low:high])


#: An interval this far from the median is a detection artefact, not a beat.
#: A wrist recording picks up motion bursts the detector reads as two fast
#: complexes; variability statistics are defined on normal-to-normal intervals
#: precisely so such bursts cannot masquerade as heart-rate variability.
NN_TOLERANCE = 0.20


def measure(recording: Recording, lead: str | None = None) -> dict[str, object]:
    """Rate and rhythm-interval statistics for one lead of a recording.

    Every number is derived from the R-peak positions.  Rate is taken from the
    median interval and variability from the normal-to-normal ones, so a motion
    artefact shifts neither; how many intervals were set aside is reported
    alongside rather than hidden.  A statistic with too few beats behind it is
    ``None``, never a filled-in value.
    """
    name = lead or recording.primary_lead
    samples = recording.leads.get(name) or []
    rate = recording.sample_rate
    peaks = r_peaks(samples, rate)
    intervals = [
        (second - first) / rate
        for first, second in zip(peaks, peaks[1:])
        if MIN_RR_SECONDS <= (second - first) / rate <= MAX_RR_SECONDS
    ]
    result: dict[str, object] = {
        "lead": name,
        "beats": len(peaks),
        "sample_rate": rate,
        "duration_seconds": recording.duration_seconds,
        "peaks": peaks,
        "rr_intervals": intervals,
        "excluded_intervals": 0,
        "heart_rate": None,
        "heart_rate_min": None,
        "heart_rate_max": None,
        "rr_mean_ms": None,
        "sdnn_ms": None,
        "rmssd_ms": None,
    }
    if not intervals:
        return result
    median = statistics.median(intervals)
    normal = [
        value if abs(value - median) <= NN_TOLERANCE * median else None
        for value in intervals
    ]
    kept = [value for value in normal if value is not None]
    result["excluded_intervals"] = len(intervals) - len(kept)
    if not kept:
        kept, normal = intervals, list(intervals)
    result["heart_rate"] = 60.0 / median
    result["heart_rate_min"] = 60.0 / max(kept)
    result["heart_rate_max"] = 60.0 / min(kept)
    result["rr_mean_ms"] = statistics.fmean(kept) * 1000
    if len(kept) > 1:
        result["sdnn_ms"] = statistics.stdev(kept) * 1000
        # A successive difference needs both of its intervals to be normal.
        differences = [
            second - first
            for first, second in zip(normal, normal[1:])
            if first is not None and second is not None
        ]
        if differences:
            result["rmssd_ms"] = math.sqrt(statistics.fmean([d * d for d in differences])) * 1000
    return result


def heart_rate(path: Path) -> float | None:
    """The measured heart rate of an ECG file, for the import path."""
    recording = read(path)
    if recording is None:
        return None
    return measure(recording).get("heart_rate")  # type: ignore[return-value]


# --- drawing -----------------------------------------------------------------
#
# The strip is drawn in millimetres on the same 25mm/s by 10mm/mV paper the
# device printed, so the familiar pink grid means what it means on paper: one
# small square is 0.04 s across and 0.1 mV tall.  Only the page zoom differs
# from a printout, and the grid travels with the trace to say so.

SECONDS_PER_ROW = 7.5
#: How much paper each lead gets.  The default suits a quiet trace; a taller
#: deflection grows the lane rather than being cut off at the edge of it, with
#: no upper bound - a clipped R wave is a lie about amplitude, and a capped
#: lane is just a clipped R wave at a politer threshold.  The scale is never
#: touched to make a signal fit: a small square means 0.1 mV or the grid means
#: nothing.
# ponytail: one motion spike therefore squashes the rest of the strip; give
# each row its own lane if that ever shows up on a real recording.
MM_PER_LEAD = 24.0
#: Clear air between the tallest deflection and the neighbouring lane.
LEAD_MARGIN_MM = 2.0
LABEL_GUTTER_MM = 9.0
#: Envelope columns per millimetre.  One column is 0.5 mm - well under a screen
#: pixel at any sane zoom - and carries the minimum and maximum of the samples
#: inside it, so an R wave survives the decimation that keeps the page small.
COLUMNS_PER_MM = 2


def _envelope(
    samples: list[float], start: int, end: int, columns: int
) -> list[tuple[int, float, float]]:
    """Per drawing column: its index, and the lowest and highest sample in it."""
    span = end - start
    if span <= 0 or columns <= 0:
        return []
    envelope: list[tuple[int, float, float]] = []
    for column in range(columns):
        first = start + span * column // columns
        last = max(first + 1, start + span * (column + 1) // columns)
        chunk = samples[first:last]
        if chunk:
            envelope.append((column, min(chunk), max(chunk)))
    return envelope


def strip_rows(
    recording: Recording, seconds_per_row: float = SECONDS_PER_ROW
) -> list[dict[str, object]]:
    """The recording drawn as stacked SVG rows, one time window each."""
    rate = recording.sample_rate
    total = recording.sample_count
    if not rate or not total or not recording.leads:
        return []
    mm_per_second, mm_per_mv = recording.mm_per_second, recording.mm_per_mv
    per_row = max(1, int(round(seconds_per_row * rate)))
    row_mm = seconds_per_row * mm_per_second
    width = LABEL_GUTTER_MM + row_mm
    names = [name for name in LEAD_ORDER if name in recording.leads]
    names += [name for name in recording.leads if name not in names]
    # One lane height for the whole strip, sized to the largest deflection
    # anywhere in it: rows of differing heights would make the same beat look
    # like two different beats.
    peak = max(
        (max(abs(value) for value in samples) for samples in recording.leads.values() if samples),
        default=0.0,
    )
    lane = max(MM_PER_LEAD, 2 * (peak * mm_per_mv + LEAD_MARGIN_MM))
    height = lane * len(names)
    columns = max(1, int(row_mm * COLUMNS_PER_MM))

    rows: list[dict[str, object]] = []
    for index, start in enumerate(range(0, total, per_row)):
        end = min(total, start + per_row)
        body = [
            f'<svg class="ecg-strip" viewBox="0 0 {width:g} {height:g}" '
            f'preserveAspectRatio="xMidYMid meet" role="img" '
            f'aria-label="{escape(_row_label(recording, start, end))}">',
            f'<defs><pattern id="ecg-mm-{index}" width="1" height="1" patternUnits="userSpaceOnUse">'
            f'<path class="ecg-grid-minor" d="M1 0V1M0 1H1"/></pattern>'
            f'<pattern id="ecg-cm-{index}" width="5" height="5" patternUnits="userSpaceOnUse">'
            f'<rect width="5" height="5" fill="url(#ecg-mm-{index})"/>'
            f'<path class="ecg-grid-major" d="M5 0V5M0 5H5"/></pattern></defs>',
            f'<rect class="ecg-paper" x="{LABEL_GUTTER_MM:g}" y="0" width="{row_mm:g}" '
            f'height="{height:g}" fill="url(#ecg-cm-{index})"/>',
        ]
        for position, name in enumerate(names):
            samples = recording.leads[name]
            middle = lane * position + lane / 2
            # A lead that runs out early gets proportionally fewer columns, so
            # it ends where it ends instead of being stretched across the row.
            stop = min(end, len(samples))
            envelope = _envelope(
                samples, start, stop, max(1, round(columns * (stop - start) / (end - start)))
            )
            if not envelope:
                continue
            step = row_mm / columns
            # Top of the column, then straight down to its floor: two samples
            # share one x, so the second needs only a vertical command.
            path = "".join(
                f"{'M' if order == 0 else 'L'}{LABEL_GUTTER_MM + column * step:.2f} "
                f"{middle - high * mm_per_mv:.2f}V{middle - low * mm_per_mv:.2f}"
                for order, (column, low, high) in enumerate(envelope)
            )
            body.append(
                f'<path class="ecg-baseline" d="M{LABEL_GUTTER_MM:g} {middle:g}H{width:g}"/>'
                f'<path class="ecg-trace" d="{path}"/>'
            )
        body.append("</svg>")
        rows.append(
            {
                "index": index,
                "start_seconds": start / rate,
                "end_seconds": end / rate,
                "label": _row_label(recording, start, end),
                # Built from numbers and an escaped label only, so it is safe markup.
                "svg": Markup("".join(body)),
                # Drawn as an HTML overlay outside the SVG (see ecg_detail.html)
                # rather than as in-image <text>: the strip scrolls horizontally
                # on a phone, and text baked into the scrolling image scrolls
                # away with it, leaving an unlabelled trace. Same order as the
                # lanes, top to bottom, so a template can zip them 1:1.
                "lead_names": names,
            }
        )
    return rows


def _row_label(recording: Recording, start: int, end: int) -> str:
    rate = recording.sample_rate or 1
    return t(
        "ecg.row_label",
        start=format_number_localized(start / rate, 2),
        end=format_number_localized(end / rate, 2),
    )
