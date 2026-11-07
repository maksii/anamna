from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from pypdf import PdfReader

from .catalog import metric
from .ecg import measure, read_cached
from .models import Aggregate, DeviceEvent, ParsedDeviceExport


RECORDED = re.compile(
    r"(?P<value>[A-Z][a-z]+,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s+[AP]M)",
    re.I,
)
HEART_RATE = re.compile(r"\b(\d{2,3})\s*BPM\b", re.I)
DURATION = re.compile(r"Duration:\s*(\d+)\s*s", re.I)
DETERMINATION = re.compile(r"Kardia Advanced Determination:\s*([^\r\n*]+)", re.I)
DATE_OF_BIRTH = re.compile(r"Date Of Birth\s*(\d{2}/\d{2}/\d{4})", re.I)
SEX = re.compile(r"Sex\s*(Male|Female|Intersex|Unknown)", re.I)


def _recorded_at(text: str) -> datetime | None:
    match = RECORDED.search(text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("value"), "%A, %b %d, %Y, %I:%M %p")
    except ValueError:
        return None


def _report_fields(first_page: str, recording) -> tuple[datetime, float, int | None, str] | None:
    """Recorded time, heart rate, length in seconds and classification of one
    report, or None when the report lacks a time or a rate."""
    recorded = _recorded_at(first_page)
    heart_rate = HEART_RATE.search(first_page)
    # The report's own vector traces, when the export still carries
    # them: they supply the rate a summary-only PDF omits, the exact
    # recording length, and the strip the web view draws.
    measured = measure(recording) if recording else {}
    if recorded is None and recording is not None and recording.recorded_at:
        recorded = datetime.fromisoformat(recording.recorded_at)
    # The printed rate is the vendor's own reading and stays canonical;
    # the measured one only fills a gap it leaves.
    value = float(heart_rate.group(1)) if heart_rate else measured.get("heart_rate")
    if recorded is None or value is None:
        return None
    duration = DURATION.search(first_page)
    seconds = None
    if duration:
        seconds = int(duration.group(1))
    elif recording:
        seconds = round(recording.duration_seconds)
    determination = DETERMINATION.search(first_page)
    classification = determination.group(1).strip() if determination else "Unclassified"
    if classification == "Unclassified" and recording is not None:
        classification = recording.classification
    return recorded, float(value), seconds, classification


def _update_identity(identity: dict[str, str], first_page: str) -> None:
    dob = DATE_OF_BIRTH.search(first_page)
    sex = SEX.search(first_page)
    if dob:
        identity["date_of_birth"] = datetime.strptime(dob.group(1), "%m/%d/%Y").date().isoformat()
    if sex:
        identity["biological_sex"] = sex.group(1).casefold()


class KardiaAdapter:
    key = "kardia"
    vendor_name = "Kardia"
    website = "https://www.alivecor.com/"

    def _build_pair(self, path: Path, first_page: str, recording, fields) -> tuple[Aggregate, DeviceEvent]:
        recorded, value, seconds, classification = fields
        started_at = recorded.isoformat()
        day = recorded.date().isoformat()
        leads = len(recording.leads) if recording else 0
        six_lead = "6L Recording" in first_page or leads > 1
        source_name = "Kardia 6L" if six_lead else "Kardia"

        aggregate = Aggregate(
            metric("ecg_heart_rate", "ECG heart rate", "device_recovery", "bpm", "latest"),
            day,
            source_name,
            self.vendor_name,
        )
        aggregate.add(value, started_at)
        event = DeviceEvent(
            source_name=source_name,
            source_vendor=self.vendor_name,
            event_type="Electrocardiogram",
            started_at=started_at,
            ended_at=(recorded + timedelta(seconds=seconds)).isoformat() if seconds else None,
            value_text=classification,
            value_numeric=value,
            unit="bpm",
            source_file=str(path.resolve()),
        )
        return aggregate, event

    def parse(self, source: Path, **_options) -> ParsedDeviceExport:
        paths = [source] if source.is_file() else sorted(source.rglob("*.pdf"))
        aggregates: list[Aggregate] = []
        events: list[DeviceEvent] = []
        classifications: Counter[str] = Counter()
        days: list[str] = []
        page_count = 0
        identity: dict[str, str] = {}
        waveforms = 0
        lead_counts: Counter[str] = Counter()

        for path in paths:
            reader = PdfReader(path)
            page_count += len(reader.pages)
            first_page = reader.pages[0].extract_text() or "" if reader.pages else ""
            recording = read_cached(path)
            if recording is not None and recording.leads:
                waveforms += 1
                lead_counts[str(len(recording.leads))] += 1
            fields = _report_fields(first_page, recording)
            if fields is None:
                continue
            aggregate, event = self._build_pair(path, first_page, recording, fields)
            days.append(aggregate.day)
            classifications[fields[3]] += 1
            aggregates.append(aggregate)
            events.append(event)
            _update_identity(identity, first_page)
        earliest = min(days) if days else None
        latest = max(days) if days else None

        if not events:
            raise ValueError(f"No recognizable Kardia ECG recording found under {source}")
        return ParsedDeviceExport(
            aggregates=aggregates,
            events=events,
            raw_record_count=len(events),
            export_started_at=earliest,
            export_ended_at=latest,
            metadata={
                "pdf_files": len(paths),
                "pdf_pages": page_count,
                "classifications": dict(classifications),
                "waveform_recordings": waveforms,
                "lead_counts": dict(lead_counts),
                "source_vendor_counts": {self.vendor_name: len(events)},
                "identity": identity,
            },
        )
