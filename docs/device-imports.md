# Device imports

Anamna reads file exports from Apple Health, Garmin, Oura and Kardia. Importers stream the source
files, keep the original path and a fingerprint of each one, and store compact daily aggregates
with the device source that produced them. Re-importing the same export is idempotent.

Apple Health often holds records written by Oura, Garmin Connect and other apps. Those keep their
own source vendor; they are not relabelled as Apple measurements. Where several sources report the
same metric, the person chooses a preferred source and the others stay available.

For continuous updates instead of periodic exports, see the Oura and Garmin API connections in
[provider-integrations.md](provider-integrations.md) and [OpenWearables](openwearables-webhooks.md).

## Two ways to import

**Web upload.** Upload the export ZIP on the upload page (archives up to 6 GB are sent in chunks;
single documents up to 32 MB). The archive is recognized by its layout (`export.xml` for Apple
Health, `DI_CONNECT` for Garmin, the Takeout tables for Oura) or by vendor-specific field names, and
the vendor can also be named explicitly on the form. The unpacked export is kept under
`sources/uploads/`, because ECG and workout events point at files inside it.

**Command line.** Point the importer at the unpacked export directory (or a single file):

```bash
uv run anamna devices import --email you@example.com --vendor apple_health --path <export directory>
uv run anamna devices import --email you@example.com --vendor garmin --path <export directory>
uv run anamna devices import --email you@example.com --vendor oura --path <export directory or data.zip contents>
uv run anamna devices import --email you@example.com --vendor kardia --path <report.pdf>
```

Keep each export unmodified, in its own dated directory, outside the repository or in an ignored
location such as `sources/`. The repository ignores a local `Device_Vendor_stats/` directory for
the same purpose.

## Apple Health

On the iPhone: Health app, tap your profile picture, **Export All Health Data**. The result is
`export.zip`, which unpacks to `apple_health_export/` with:

- `export.xml`: all records (read in one streaming pass, so multi-gigabyte files are fine);
- `electrocardiograms/*.csv`: Apple Watch ECG recordings, with their waveforms;
- `workout-routes/*.gpx`: workout routes.

Upload `export.zip` as is, or give the CLI the `apple_health_export` directory.

## Garmin

Request a full account export from Garmin (Garmin account, **Data Management**, **Export Your
Data**). Garmin emails a link to a ZIP some time later. It contains a `DI_CONNECT` tree of JSON and
CSV files plus ZIP archives of FIT files.

The importer reads the health-bearing JSON and CSV records (daily summaries, sleep, Body Battery,
stress, intensity minutes, Index Scale body composition, blood pressure entries) and reconciles the
FIT archives with them so a reading present in both is stored once. Implausible scale captures are
kept in provenance metadata with an explicit exclusion rather than silently dropped.

Validate a Garmin or Kardia import against the database without changing it:

```bash
uv run python scripts/validate_device_imports.py --garmin <export directory> --kardia <report.pdf>
```

## Oura

Request your data export from your Oura account on the web. Oura delivers `data.zip` (the
"Takeout" layout of semicolon-separated CSV tables). Older API-shaped JSON and CSV exports are
accepted too.

The Takeout tables are mapped file by file, so the three generic `score` columns in different
tables cannot be confused. Validate an archive without writing patient data to the database:

```bash
uv run python scripts/validate_oura_export.py --oura <data.zip or its extracted directory>
```

The validator fails on an unrecognized populated table or a new column in a normalized table. Raw
sensor streams, precise location, product settings and manufacturer recommendations remain
losslessly in the private source export; the report distinguishes these retained tables from
normalized health metrics instead of silently dropping them.

Oura reports HRV as RMSSD and Apple Health as SDNN; the two are stored as separate metrics and never
converted into each other.

## Kardia

Export an ECG from the Kardia app as its PDF report. The importer links the ECG event, the reported
heart rate, the recording time and duration, and the algorithm's determination back to the PDF,
which is also kept as a source document with its full waveform. The algorithm's wording is shown
as the device's determination, never as a clinician's diagnosis.

## Privacy

Device exports are health data. Never commit them; `sources/`, `data/` and `Device_Vendor_stats/`
are gitignored, and the Docker build context excludes everything but application code.
