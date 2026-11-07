# Patient overview and history

The overview leads with blood, heart, activity and sleep, followed by every health
area. Values are drawn from the owner-scoped metric catalog, with review status,
recording date and a direct link to the full measurement. There is no composite
health score and no new medical interpretation in this presentation layer.

Area pages have direct section navigation and distinct introductory context.
Blood leads into related panels and laboratory evidence; heart brings pressure,
rhythm and clinical records together; activity presents daily bars and period
means; sleep presents nightly stage estimates and their selected source. Device
overview pages lead with health readings before adapter and import information.

## Selection and coverage

`web/experience.py` accepts catalog data already selected by the domain layer.
It must never reconcile device readings or classify clinical values. The source
policy, preferred source and alternatives come from `devices/queries.py` and
`devices/reconcile.py`. The source preference form is rendered only when the
route supplies `can_manage_sources`; permission checks remain in the route.

Each tracker offers a recording-coverage strip and a keyboard-accessible
disclosure of exact daily values. A missing value is a gap, never zero. Sleep
nights include the selected source when available. The last-recorded date is
shown explicitly because historical exports do not necessarily reach today.

Device trends offer 30 days, 90 days, one year and all history. Windows include
exactly the requested number of calendar days and use the same latest-date
anchor across sources. Means and extrema are computed from original selected
points in that window, before chart thinning. Alternate sources remain available
even when the selected nightly source has no values for a sleep-stage metric.

Laboratory and device chart points use elapsed time on the horizontal axis.
Device lines break across missing days. Axis labels leave enough physical space
to remain readable when many measurements cluster on similar dates. Existing
averaging disclosures and original history tables remain available.

## Assets and verification

The participating templates load `patient-experience.css` and
`patient-experience.js` using `asset()` for cache invalidation. CSS uses existing
theme tokens and the established 620, 760 and 1100 pixel breakpoints. Translated
copy lives in `locales/messages.py`; client summaries reuse the chart locale
formatters and receive labels from rendered HTML.

Run `tests/python/test_patient_experience.py` for immutability, empty coverage,
zero-value handling and calendar placement, and
`node --test tests/js/*.test.mjs` for period changes, missing values,
time-label spacing and tooltip escaping. The integration regression set includes
`test_web_tracker.py`, `test_web_metrics.py`, `test_web_panels.py`,
`test_web_i18n.py`, `test_i18n.py` and `test_static_assets.py`.

Required viewports for live verification are 375×667, 390×844, 820×1180 and 1180×820,
in both English and Ukrainian, including dark mode and reduced motion.
