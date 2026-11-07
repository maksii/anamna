from copy import deepcopy

import pytest

from anamna.web.experience import _sparkline, build_area_experience, build_overview


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_featured_heart_sources_keep_provider_chain_without_repeating_vendor(tmp_path, locale):
    from fastapi.testclient import TestClient
    from anamna.db import connect
    from anamna.security import create_session
    from anamna.web.app import create_app
    from test_web_tracker import build, seed_days, day

    settings, user = build(tmp_path)
    with connect(settings) as db:
        patient = db.execute("SELECT id FROM patients WHERE owner_user_id=?", (user,)).fetchone()[0]
    seed_days(settings, user, patient, "resting_heart_rate", "Resting heart rate", "device_recovery", "bpm", "average", [(day(0), 58)])
    source = "OpenWearables · apple · Fixture Watch"
    with connect(settings) as db:
        db.execute("UPDATE device_metric_days SET source_vendor='OpenWearables', source_name=? WHERE metric_key='resting_heart_rate'", (source,))
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user)
    client.cookies.set("anamna_session", token)
    page = client.get(f"/areas/heart?lang={locale}")
    assert page.status_code == 200
    # One readable name per source: the origin, then the transport (UX-14).
    assert '<small>Fixture Watch · OpenWearables</small>' in page.text
    assert 'OpenWearables · OpenWearables' not in page.text
    renderer = page.template.environment.from_string('{% from "_experience.html" import source_label with context %}{{ source_label(vendor, name) }}')
    for vendor, name, expected in [
        ("Oura", "Oura", "Oura"),
        ("OpenWearables", "openwearables · apple · Fixture Watch", "openwearables · apple · Fixture Watch"),
        ("Apple Health", "Fixture Watch", "Apple Health · Fixture Watch"),
        ("", "Fixture Watch", "Fixture Watch"),
    ]:
        assert renderer.render(**{**page.context, "vendor": vendor, "name": name}) == expected


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_matched_hdl_category_is_distinguished_from_the_shaded_target(tmp_path, locale):
    from test_web_panels import build
    _, _, client = build(tmp_path)
    page = client.get(f"/metrics/hdl-cholesterol?lang={locale}")
    assert page.status_code == 200
    verdict = page.context["verdict"]
    assert verdict["authority"] == "curated"
    assert verdict["interpretation"] == "normal"
    # Sandbox audit CLIN-02 / DOCB-12: a benign verdict is its own target. HDL
    # 1.42 used to read "Within range" beside "below the target interval
    # >=1.55" -- the optional protective band shaded as if it were the goal.
    assert verdict["target_is_matched_band"] is True
    assert verdict["out_of_range_side"] is None
    assert verdict["target_low"] == 1.0
    assert 'data-distinct-target="true"' not in page.text
    assert ("below the target interval" if locale == "en" else "нижче цільового інтервалу") not in page.text
    # The protective band is still listed, labelled as what it is.
    assert ("protective" if locale == "en" else "захисним") in page.text


def test_overview_preserves_review_and_selected_values_without_health_score():
    card = {
        "id": "device:steps", "area_ids": ["activity"], "value_text": "9,021",
        "value_numeric": 9021, "verification_status": "device_measurement",
        "latest_date": "2026-09-08", "series": [
            {"date": "2026-09-01", "value": 0},
            {"date": "2026-09-08", "value": 9021},
        ],
    }
    areas = [{"id": "activity", "metrics": [card], "evidence_count": 1}]
    snapshot = deepcopy((areas, card))
    result = build_overview(areas, [card], {})
    feature = result["focus"][0]["featured_metrics"][0]
    assert feature["value_numeric"] == 9021
    assert feature["verification_status"] == "device_measurement"
    assert feature["experience_spark"] == "4.00,36.00 216.00,6.00"
    assert "score" not in result
    assert (areas, card) == snapshot


def test_sparkline_uses_real_time_and_retains_zero_and_gaps():
    path = _sparkline([
        {"date": "2026-09-01", "value": 0},
        {"date": "2026-09-02", "value": 10},
        {"date": "2026-09-11", "value": 5},
        {"date": "invalid", "value": 99},
        {"date": "2026-09-04", "value": float("nan")},
    ])
    assert path == "4.00,36.00 25.20,6.00 216.00,21.00"
    assert len(path.split()) == 3
    assert _sparkline([{"date": "2026-09-01", "value": 4}]) == ""


def test_sleep_only_coverage_uses_recorded_nights_not_empty_calendar_days():
    area = {"id": "sleep", "metrics": []}
    tracker = {"cards": [], "sleep": {"nights": [
        {"day": "2026-09-01", "asleep": 7.5, "has_stages": False},
        {"day": "2026-09-02", "asleep": None, "has_stages": True},
        {"day": "2026-09-03", "asleep": None, "has_stages": False},
    ]}}
    result = build_area_experience(area, [], tracker)
    assert result["latest_device"] == "2026-09-02"
    assert result["has_tracker"]


def test_empty_overview_never_invents_record_coverage():
    result = build_overview([{"id": "blood", "metrics": [], "evidence_count": 0}], [], {})
    assert result["focus"][0]["featured_metrics"] == []
    assert result["recorded_areas"] == 0
    assert result["latest_medical"] is None
    assert result["latest_device"] is None


def test_real_dashboard_area_context_renders_directory_measurement_count(tmp_path):
    from fastapi.testclient import TestClient
    from anamna.security import create_session
    from anamna.web.app import create_app
    from test_web_tracker import build

    settings, user_id = build(tmp_path)
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    response = client.get("/")
    assert response.status_code == 200
    areas = response.context["experience"]["areas"]
    activity = next(area for area in areas if area["id"] == "activity")
    assert activity["metric_count"] == 1
    directory = response.text.split('class="px-directory-grid"', 1)[1].split('</nav>', 1)[0]
    activity_link = directory.split('href="/areas/activity"', 1)[1].split('</a>', 1)[0]
    assert 'class="px-directory-count"' in activity_link
    # The count names what it counts ("1 result" / «1 показник»), never a bare number.
    import re
    assert re.search(r'px-directory-count">1 \w+ <span class="an-chevron" data-dir="right" aria-hidden="true">', activity_link), activity_link


@pytest.mark.parametrize("locale", ["en", "uk"])
def test_device_area_headers_lead_with_actual_coverage_and_keep_sections_reachable(tmp_path, locale):
    from fastapi.testclient import TestClient
    from anamna.security import create_session
    from anamna.web.app import create_app
    from test_web_tracker import build, day

    settings, user_id = build(tmp_path)
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set("anamna_session", token)
    for area in ("activity", "sleep", "mobility"):
        response = client.get(f"/areas/{area}?lang={locale}")
        assert response.status_code == 200
        hero = response.text.split('class="area-detail-hero px-device-area-hero">', 1)[1].split('</section>', 1)[0]
        assert "area-evidence-summary" not in hero
        assert "area-scope-note" not in hero
        assert "eyebrow" not in hero
        assert f'<dd>{response.context["measurement_count"]}</dd>' in hero
        if area in ("activity", "sleep"):
            assert f'<time datetime="{day(0)}">' in hero
        else:
            # No mobility recordings were seeded: do not borrow another area's date.
            assert '<time ' not in hero
        sections = response.text.split('<details class="px-area-sections">', 1)[1].split('</details>', 1)[0]
        assert 'href="#area-sources"' in sections
        assert 'id="area-findings"' in response.text
        assert 'id="area-sources"' in response.text
        assert 'experience.' not in hero
        if response.context["tracker"]:
            assert 'href="#area-daily"' in sections
            assert response.text.index('<details class="px-area-sections">') < response.text.index('id="area-daily"')

    clinical = client.get(f"/areas/blood?lang={locale}")
    assert 'class="area-evidence-summary"' in clinical.text
    assert 'class="area-scope-note"' not in clinical.text  # scope notes were cut from every area page
    assert 'class="px-area-sections"' not in clinical.text


def test_dense_device_chart_keeps_every_daily_point_and_latest_date(tmp_path):
    import json
    from datetime import timedelta
    from fastapi.testclient import TestClient
    from anamna.db import connect
    from anamna.security import create_session
    from anamna.web.app import create_app
    from test_web_tracker import build, seed_days, day, GAP_DAY, ANCHOR

    settings, user_id = build(tmp_path)
    with connect(settings) as db:
        patient_id = db.execute('SELECT id FROM patients WHERE owner_user_id=?', (user_id,)).fetchone()['id']
    seed_days(settings, user_id, patient_id, 'steps', 'Daily steps', 'device_activity', 'steps', 'sum',
              [(GAP_DAY, 10000)] + [(day(offset), 5000+offset) for offset in range(60,800)])
    with connect(settings) as db:
        db.execute("""INSERT INTO device_metric_days
                      (id,owner_user_id,patient_id,import_id,source_name,source_vendor,metric_key,metric_name,category,day,aggregation,unit,value,sample_count,created_at)
                      SELECT 'oura-'||id,owner_user_id,patient_id,import_id,'Oura','Oura',metric_key,metric_name,category,day,aggregation,unit,value+100,1,created_at
                      FROM device_metric_days WHERE metric_key='steps' AND source_name='Apple Watch'""")
        expected = {(row['source_name'],row['day']):row['value'] for row in db.execute("SELECT source_name,day,value FROM device_metric_days WHERE metric_key='steps'")}
    client = TestClient(create_app(settings))
    token, _ = create_session(settings, user_id)
    client.cookies.set('anamna_session', token)
    response = client.get('/devices/metrics/steps')
    assert response.status_code == 200
    payload = json.loads(json.dumps(response.context['chart_payload']))
    assert response.context['total_days'] == 800

    # Columnar series (PERF-03): the page inlines the last year; the whole
    # selected series and each source's own series load from the API.
    def points(data):
        columns = data['points']
        return [{'date': d, 'value': v, 'source': data['labels'][s]}
                for d, v, s in zip(columns['d'], columns['v'], columns['s'])]

    assert payload['complete'] is False and payload['combined']['d'][-1] == ANCHOR.isoformat()
    combined = points(client.get(payload['full_url']).json())
    assert len(combined) == 800
    assert combined[-1]['date'] == ANCHOR.isoformat()
    assert [point['date'] for point in combined] == sorted(point['date'] for point in combined)
    for point in combined:
        assert point['value'] == expected[('Apple Watch', point['date'])]
    assert len(payload['sources']) == 2
    for source in payload['sources']:
        assert source['label']
        series = points(client.get(source['url']).json())
        assert len(series) == 800
        assert series[-1]['date'] == ANCHOR.isoformat()
        name = 'Oura' if 'Oura' in source['label'] else 'Apple Watch'
        for point in series:
            assert point['value'] == expected[(name, point['date'])]
    cutoff = (ANCHOR-timedelta(days=29)).isoformat()
    window = [point for point in combined if point['date'] >= cutoff]
    assert len(window) == 30 and window[0]['date'] == cutoff
    assert 'class="active" data-days="30"' in response.text
    script = client.get('/static/device-chart.js').text
    assert "globalThis.AnamnaExperience.dailyWindow(all(), days, newest())" in script
    assert "svg.addEventListener('click'" in script
