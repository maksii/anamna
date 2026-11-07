"""Electrocardiogram reading, beat detection and strip drawing.

The waveform is the one part of a record where a plausible wrong number is
worse than no number, so these tests pin the three places one can appear.  A
T wave counted as a beat doubles the reported rate; a motion burst counted as
a beat inflates variability into a finding that is not there; and a lane that
was a fixed 24 mm tall - +/-1.2 mV - drew every real R wave in this record
outside its own viewBox, so the tallest part of the trace, the part being
read, was the part that got clipped off.

The synthetic signals are built here rather than loaded so the true answer is
known: a T wave at 40% of R amplitude is tall enough that a naive threshold
detector double-counts it, and a burst is inserted at a known time so the
excluded-interval count can be checked against it.  The real Kardia and Apple
fixtures are private data and skip when absent.
"""

from __future__ import annotations

import math
import re
import statistics
from pathlib import Path

import pytest

from anamna.devices import ecg
from anamna.devices.ecg import LEAD_ORDER, Recording

RATE = 500.0
RR_SECONDS = 0.8  # 75 bpm
R_MV = 1.0
T_MV = 0.4  # 40% of R: a plain amplitude threshold cannot tell them apart
QRS_SIGMA = 0.012  # narrow and steep
T_SIGMA = 0.050  # later, lower, broader
T_OFFSET = 0.28

REAL_KARDIA = Path("sources/2026/monitoring/2026-08-03__kardia__6-lead-ecg.pdf")
REAL_APPLE = Path(
    "Device_Vendor_stats/apple_health/imports/2026-08-03/apple_health_export"
    "/electrocardiograms"
)


# --- synthetic signals -------------------------------------------------------


def _bell(samples, centre_seconds, amplitude, sigma_seconds, rate=RATE):
    """Add one bell-shaped deflection centred on ``centre_seconds``."""
    centre = centre_seconds * rate
    spread = sigma_seconds * rate
    first = max(0, int(centre - 4 * spread))
    last = min(len(samples), int(centre + 4 * spread) + 1)
    for index in range(first, last):
        samples[index] += amplitude * math.exp(-0.5 * ((index - centre) / spread) ** 2)


def _beat_times(count, first=0.4, jitter=0.0):
    """R-wave times, with a deterministic wobble so clean SDNN is not zero."""
    times, when = [], first
    for index in range(count):
        times.append(when)
        when += RR_SECONDS + jitter * math.sin(index * 1.7)
    return times


def _signal(times, duration, t_mv=T_MV):
    """A QRS spike at each time, each followed by its own broader T wave."""
    samples = [0.0] * int(duration * RATE)
    for when in times:
        _bell(samples, when, R_MV, QRS_SIGMA)
        _bell(samples, when + T_OFFSET, t_mv, T_SIGMA)
    return samples


def _recording(leads, rate=RATE, mm_per_second=25.0, mm_per_mv=10.0):
    return Recording(
        recorded_at="2026-08-03T10:00:00",
        device="Synthetic",
        vendor="Synthetic",
        classification="Sinus Rhythm",
        sample_rate=rate,
        leads=leads,
        mm_per_second=mm_per_second,
        mm_per_mv=mm_per_mv,
    )


def _naive_peaks(samples, threshold):
    """Upward threshold crossings - the detector ``r_peaks`` has to beat."""
    peaks, above = [], False
    for index, value in enumerate(samples):
        if value >= threshold and not above:
            peaks.append(index)
        above = value >= threshold
    return peaks


def _trace_ys(svg):
    """Every y coordinate in the ``.ecg-trace`` path data of one row."""
    ys = []
    for path in re.findall(r'class="ecg-trace" d="([^"]*)"', svg):
        for top, floor in re.findall(r"[ML]-?[\d.]+ (-?[\d.]+)V(-?[\d.]+)", path):
            ys += [float(top), float(floor)]
    return ys


# --- beat detection ----------------------------------------------------------


def test_r_peaks_finds_every_beat_and_no_t_wave():
    times = _beat_times(20)
    samples = _signal(times, duration=16.0)
    # The T wave is a genuine hazard, not a token bump: an amplitude threshold
    # low enough to catch every R also catches every T, and doubles the rate.
    t_index = int((times[0] + T_OFFSET) * RATE)
    assert samples[t_index] > 0.35 * R_MV
    assert len(_naive_peaks(samples, 0.35 * R_MV)) == 2 * len(times)

    # Slope, energy and a QRS-width moving sum keep only the complexes.
    peaks = ecg.r_peaks(samples, RATE)

    assert len(peaks) == len(times)
    # Each detection sits on an R wave, not on the T wave 0.28 s after it.
    for peak, when in zip(peaks, times):
        assert abs(peak / RATE - when) < 0.02

    measured = ecg.measure(_recording({"I": samples}))
    assert measured["beats"] == 20
    assert measured["heart_rate"] == pytest.approx(60 / RR_SECONDS, abs=1.0)
    assert measured["rr_mean_ms"] == pytest.approx(RR_SECONDS * 1000, abs=20)


def test_motion_burst_is_excluded_instead_of_becoming_variability():
    times = _beat_times(24, jitter=0.02)
    clean = _signal(times, duration=20.0)
    clean_measured = ecg.measure(_recording({"I": clean}))

    # One motion burst: an extra sharp complex 0.4 s after the sixth beat,
    # splitting one normal interval into two implausibly short ones.
    noisy = list(clean)
    _bell(noisy, times[5] + 0.4, 0.9 * R_MV, QRS_SIGMA)
    noisy_measured = ecg.measure(_recording({"I": noisy}))

    assert noisy_measured["beats"] == clean_measured["beats"] + 1
    assert noisy_measured["excluded_intervals"] >= 2
    assert clean_measured["excluded_intervals"] == 0

    # The rate comes off the median, so one burst does not move it.
    assert noisy_measured["heart_rate"] == pytest.approx(60 / RR_SECONDS, abs=1.0)

    # Variability is defined on the normal intervals only.  Taken over every
    # interval instead - which is what a regression here would do - the burst
    # alone would multiply SDNN several times over.
    naive = statistics.stdev(noisy_measured["rr_intervals"]) * 1000
    assert naive > 3 * clean_measured["sdnn_ms"]
    assert noisy_measured["sdnn_ms"] == pytest.approx(clean_measured["sdnn_ms"], abs=3.0)
    assert noisy_measured["rmssd_ms"] == pytest.approx(clean_measured["rmssd_ms"], abs=5.0)


def test_too_few_beats_reports_none_rather_than_a_filled_in_number():
    flat = ecg.measure(_recording({"I": [0.0] * int(10 * RATE)}))
    assert flat["beats"] == 0
    assert flat["heart_rate"] is None
    assert flat["heart_rate_min"] is None
    assert flat["heart_rate_max"] is None
    assert flat["rr_mean_ms"] is None
    assert flat["sdnn_ms"] is None
    assert flat["rmssd_ms"] is None

    # A single beat has no interval behind it, so it has no rate either.
    brief = _signal(_beat_times(1, first=0.2), duration=0.5)
    assert ecg.r_peaks(brief, RATE) == []
    assert ecg.measure(_recording({"I": brief}))["heart_rate"] is None

    # Two beats give one interval - enough for a rate, not for a deviation.
    pair = _signal(_beat_times(2, first=0.4), duration=2.0)
    two = ecg.measure(_recording({"I": pair}))
    assert two["heart_rate"] == pytest.approx(60 / RR_SECONDS, abs=1.0)
    assert two["sdnn_ms"] is None
    assert two["rmssd_ms"] is None


# --- Apple CSV ---------------------------------------------------------------


APPLE_HEADER = """Name,Ivan Petrenko
Date of Birth,"14 Mar 1990"
Recorded Date,2024-01-04 13:38:52 +0300
Classification,Sinus Rhythm
Symptoms,Fluttering
Software Version,1.90
Device,"Watch7,5"
Sample Rate,512 hertz


Lead,Lead I
Unit,{unit}

"""


def _apple_csv(path, samples, unit="µV"):
    path.write_text(APPLE_HEADER.format(unit=unit) + "\n".join(samples) + "\n", encoding="utf-8")
    return path


def test_apple_csv_reads_the_header_and_converts_microvolts_to_millivolts(tmp_path):
    source = _apple_csv(tmp_path / "ecg.csv", ["-197.325", "-63.878", "0", "812.5", "-15.489"])

    recording = ecg.read(source)

    assert recording is not None
    assert recording.recorded_at == "2024-01-04T13:38:52+03:00"
    assert recording.device == "Watch7,5"
    assert recording.vendor == "Apple Health"
    assert recording.classification == "Sinus Rhythm"
    assert recording.symptoms == "Fluttering"
    assert recording.sample_rate == 512.0
    assert recording.primary_lead == "I"
    assert recording.leads["I"][0] == pytest.approx(-0.197325)
    assert recording.leads["I"][3] == pytest.approx(0.8125)
    assert recording.sample_count == 5


def test_apple_csv_in_millivolts_is_not_rescaled_again(tmp_path):
    source = _apple_csv(tmp_path / "mv.csv", ["-0.197325", "0.8125"], unit="mV")

    recording = ecg.read(source)

    assert recording.leads["I"] == pytest.approx([-0.197325, 0.8125])


def test_apple_csv_written_in_a_decimal_comma_locale_reads_the_same(tmp_path):
    point = _apple_csv(tmp_path / "point.csv", ["-197.325", "63.878", "0.0"])
    comma = _apple_csv(tmp_path / "comma.csv", ["-197,325", "63,878", "0,0"])

    assert ecg.read(comma).leads["I"] == pytest.approx(ecg.read(point).leads["I"])
    assert ecg.read(comma).leads["I"][0] == pytest.approx(-0.197325)


# --- degradation -------------------------------------------------------------


def test_read_returns_none_instead_of_raising(tmp_path):
    broken = tmp_path / "flattened.pdf"
    broken.write_bytes(b"not a pdf")
    assert ecg.read(broken) is None

    headers_only = tmp_path / "empty.csv"
    headers_only.write_text(APPLE_HEADER.format(unit="µV"), encoding="utf-8")
    assert ecg.read(headers_only) is None

    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("-197.325\n", encoding="utf-8")
    assert ecg.read(unsupported) is None

    assert ecg.read_cached(tmp_path / "absent.csv") is None


def test_read_cached_returns_the_same_recording_for_an_unchanged_file(tmp_path):
    source = _apple_csv(tmp_path / "cached.csv", ["-197.325", "63.878"])
    assert ecg.read_cached(source) is ecg.read_cached(source)


# --- strip drawing -----------------------------------------------------------


def _viewbox(svg):
    box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    return float(box.group(1)), float(box.group(2))


@pytest.mark.parametrize("peak_mv", [2.5, 0.3])
def test_strip_never_draws_the_trace_outside_its_viewbox(peak_mv):
    times = _beat_times(24)
    samples = [value * peak_mv / R_MV for value in _signal(times, duration=20.0)]
    rows = ecg.strip_rows(_recording({"I": samples, "II": samples}))

    assert len(rows) == math.ceil(20.0 / ecg.SECONDS_PER_ROW)
    assert max(abs(value) for value in samples) == pytest.approx(peak_mv, rel=0.01)

    for row in rows:
        _, height = _viewbox(row["svg"])
        ys = _trace_ys(row["svg"])
        assert ys, "the row drew no trace at all"
        assert min(ys) >= 0, f"trace clipped above the viewBox at {min(ys)}"
        assert max(ys) <= height, f"trace clipped below the viewBox at {max(ys)}"


def test_a_differently_calibrated_export_is_drawn_at_its_own_scale():
    """The stated calibration reaches the drawing, rather than being assumed.

    It used to be handed over as prose and read back with a regex that required
    a `Scale:` prefix the prose never carried, so every strip was silently drawn
    at 25mm/s and 10mm/mV whatever the report said.
    """
    samples = [value * 0.5 / R_MV for value in _signal(_beat_times(12), duration=10.0)]
    standard = ecg.strip_rows(_recording({"I": samples}), seconds_per_row=6.0)[0]
    doubled = ecg.strip_rows(
        _recording({"I": samples}, mm_per_second=50.0, mm_per_mv=20.0), seconds_per_row=6.0
    )[0]

    paper = lambda svg: float(re.search(r'class="ecg-paper"[^>]*width="([\d.]+)"', svg).group(1))
    excursion = lambda svg: max(_trace_ys(svg)) - min(_trace_ys(svg))

    assert paper(doubled["svg"]) == pytest.approx(2 * paper(standard["svg"]))
    assert excursion(doubled["svg"]) == pytest.approx(2 * excursion(standard["svg"]), rel=0.02)


def test_strip_rows_cover_the_recording_in_order():
    samples = _signal(_beat_times(24), duration=20.0)
    rows = ecg.strip_rows(_recording({"I": samples}), seconds_per_row=5.0)

    assert len(rows) == math.ceil(20.0 / 5.0)
    assert [row["index"] for row in rows] == [0, 1, 2, 3]
    assert [row["start_seconds"] for row in rows] == [0.0, 5.0, 10.0, 15.0]
    assert rows[-1]["end_seconds"] == pytest.approx(20.0)
    assert rows[0]["label"] == "0-5 s"


def test_strip_is_calibrated_paper_not_a_fitted_plot():
    times = _beat_times(12)
    small = [value * 0.5 / R_MV for value in _signal(times, duration=10.0)]
    large = [value * 2 for value in small]

    seconds_per_row = 6.0
    small_rows = ecg.strip_rows(_recording({"I": small}), seconds_per_row=seconds_per_row)
    large_rows = ecg.strip_rows(_recording({"I": large}), seconds_per_row=seconds_per_row)

    # Paper is 25 mm wide per second, whatever is drawn on it.
    paper = re.search(r'class="ecg-paper"[^>]*width="([\d.]+)"', small_rows[0]["svg"])
    assert float(paper.group(1)) == pytest.approx(seconds_per_row * 25.0)
    width, _ = _viewbox(small_rows[0]["svg"])
    assert width == pytest.approx(ecg.LABEL_GUTTER_MM + seconds_per_row * 25.0)

    # And 10 mm tall per millivolt: doubling the signal doubles the excursion
    # rather than being scaled back to fit the lane.  Both lanes are the same
    # height, so the extra millimetres are scale and not a grown lane.
    def excursion(rows):
        ys = _trace_ys(rows[0]["svg"])
        return max(ys) - min(ys)

    def span_mv(samples):
        return max(samples) - min(samples)

    assert _viewbox(small_rows[0]["svg"])[1] == _viewbox(large_rows[0]["svg"])[1]
    assert excursion(small_rows) == pytest.approx(span_mv(small) * 10.0, abs=0.2)
    assert excursion(large_rows) == pytest.approx(span_mv(large) * 10.0, abs=0.2)
    assert excursion(large_rows) == pytest.approx(2 * excursion(small_rows), abs=0.2)


def test_leads_are_drawn_in_the_printed_order_whatever_order_they_arrived_in():
    samples = _signal(_beat_times(10), duration=8.0)
    scrambled = {"aVF": samples, "II": samples, "I": samples, "III": samples}
    recording = _recording(scrambled)

    assert list(recording.leads) != ["I", "II", "III", "aVF"]
    assert recording.primary_lead == "I"

    # The labels moved out of the <svg> into a sticky overlay so they stay
    # visible while the strip scrolls sideways; the printed order they are
    # emitted in is the invariant, not where they are drawn.
    labels = ecg.strip_rows(recording)[0]["lead_names"]
    assert labels == ["I", "II", "III", "aVF"]
    assert labels == [name for name in LEAD_ORDER if name in scrambled]


def test_primary_lead_falls_back_to_whatever_is_present():
    assert _recording({"II": [0.0], "aVR": [0.0]}).primary_lead == "II"
    assert _recording({}).primary_lead == ""


# --- real fixtures, skipped on a checkout without the private data -----------


def _fixture(relative):
    path = Path(__file__).resolve().parents[2] / relative
    if not path.exists():
        pytest.skip(f"private fixture absent: {relative}")
    return path


def test_real_kardia_pdf_recovers_six_calibrated_leads():
    recording = ecg.read_cached(_fixture(REAL_KARDIA))

    assert recording is not None
    assert list(recording.leads) == list(LEAD_ORDER)
    assert recording.vendor == "Kardia"
    assert recording.device == "Kardia 6L"
    assert recording.sample_rate == 300
    assert recording.duration_seconds == pytest.approx(30.0, abs=0.05)
    assert recording.classification == "Normal Sinus Rhythm"
    assert recording.recorded_at.startswith("2026-08-03T13:44")
    assert recording.scale_text == "25mm/s, 10mm/mV"
    # The calibration is carried in scale_text, so it must not be repeated in
    # the filter description it was printed beside.
    assert "Enhanced Filter" in recording.filter_text
    assert "Scale:" not in recording.filter_text
    assert "mm/mV" not in recording.filter_text

    measured = ecg.measure(recording)
    assert measured["lead"] == "I"
    assert measured["heart_rate"] == pytest.approx(77, abs=2)  # the report prints 77 BPM


def test_real_kardia_strip_stays_inside_its_viewbox():
    recording = ecg.read_cached(_fixture(REAL_KARDIA))
    rows = ecg.strip_rows(recording)

    assert len(rows) == math.ceil(recording.duration_seconds / ecg.SECONDS_PER_ROW)
    for row in rows:
        _, height = _viewbox(row["svg"])
        ys = _trace_ys(row["svg"])
        assert ys
        assert min(ys) >= 0
        assert max(ys) <= height


def test_real_apple_csv_measures_a_plausible_rate():
    directory = _fixture(REAL_APPLE)
    sources = sorted(directory.glob("*.csv"))
    if not sources:
        pytest.skip("no Apple electrocardiogram exports present")

    recording = ecg.read(sources[0])
    assert recording is not None
    assert recording.vendor == "Apple Health"
    assert recording.sample_rate == pytest.approx(512, abs=16)
    assert recording.duration_seconds == pytest.approx(30, abs=2)
    # Microvolts became millivolts: a wrist trace lives well inside +/-5 mV.
    assert max(abs(value) for value in recording.leads["I"]) < 5.0

    measured = ecg.measure(recording)
    assert 50 <= measured["heart_rate"] <= 110
    assert measured["sdnn_ms"] is not None
