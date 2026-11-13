"""Busy and failure states wired into the metrics, changes and chart pages."""
from pathlib import Path

from anamna.locales.messages import MESSAGES

WEB = Path(__file__).resolve().parents[2] / "src" / "anamna" / "web"


def _read(rel):
    return (WEB / rel).read_text(encoding="utf-8")


def test_new_keys_in_both_locales():
    entry = MESSAGES["metrics.search_retry"]
    assert entry["en"] and entry["uk"]


def test_live_search_marks_input_busy_and_reports_failure():
    html = _read("templates/results.html")
    assert 'role="alert"' in html and "search_retry" in html
    assert "form.setAttribute('aria-busy', 'true')" in html
    assert "failure.hidden = false" in html


def test_changes_ai_and_period_use_shared_busy_helper():
    html = _read("templates/results.html")
    assert "anamnaBusy.track(button" in html
    assert "anamnaBusy?.navigating(period)" in html


def test_device_chart_switches_track_the_pressed_button():
    js = _read("static/device-chart.js")
    assert js.count("refresh(button, activeSource)") == 2
    assert "track(button, load(id))" in js
    assert "host.setAttribute('aria-busy', 'true')" in js


def test_busy_css_present():
    css = _read("static/app.css")
    assert '.live-search[aria-busy="true"]::after' in css
    assert '.dynamic-chart[aria-busy="true"]' in css
