# Running the unified workspace

## Local run

PyRadiomics has no published build for Python 3.14, so feature extraction stays
unavailable on that interpreter. The rest of the workspace runs with the
`python` on your PATH.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-demo.txt
python -m app.oncometra
```

On a new database, the seed creates username `saad` and writes a random initial
password to `$APP_STORAGE_ROOT/admin-password.txt` unless
`ONCOMETRA_ADMIN_PASSWORD` is set. Existing accounts are not reset.
Do not commit or publish that file. Open `http://127.0.0.1:8020`.

SQLite (`workflow.db`) and image files share `APP_STORAGE_ROOT`. Back up that
directory. TLS, external access, company identity management and clinical
operations are not configured by this demo.

For a separate metadata worker, set `CATALOG_WORKER_MODE=external` for the web app,
then run `python -m app.catalog_worker` with the same `APP_STORAGE_ROOT`.
`--once` processes one eligible job. Expired leases can be reclaimed; failed jobs
can be requested again from Datasets. SQLite allows one writer at a time, so keep
the web process and the worker on the same machine and avoid a second web process.

## Bring in OncoRadar metadata

Obtain a consistent copy of its SQLite database. In Datasets, choose
**Sync OncoRadar index** and point it at that file (by default
`WP05_OncoRadar/data/oncoradar.sqlite`). The read is read-only. It copies the
dataset record (trial, site, histology, access, license, DICOM folder, and
related summaries). The patient list stays in WP05. Repeat syncs refresh this
record and keep curated notes.

The JSON exporter writes the same fields, for a smaller extract:

```bash
python scripts/export_oncoradar_catalog.py /path/to/oncoradar-backup.sqlite > catalog.json
```

**Import OncoRadar catalog** still accepts that JSON. The per-request bound is
500 datasets / 4 MB, which is too small for a full patient index. Use the sync
button for the live database. OncoRadar's `false` longitudinal default becomes
unknown, not a verified absence of follow-up. A stored DICOM path does not
copy the scans and does not by itself mean they are loaded for annotation.

## Cohort manifest contract

Import via a dataset's **Prepare cohort** action. One record identifies one series.
Do not include patient names, dates of birth or direct identifying metadata.

```json
{
  "records": [
    {
      "external_id": "SUBJECT-001-baseline-CT",
      "patient_id": "SUBJECT-001",
      "modality": "CT",
      "study_uid": "1.2.3.4",
      "series_uid": "1.2.3.4.5",
      "visit": "baseline",
      "metadata": {"sequence": "Portal venous"}
    }
  ]
}
```

For NIfTI, study/series UIDs can be empty, but the external ID must remain stable.
Use a different external ID for follow-up or another sequence. Changing patient,
modality or DICOM identities for an existing external ID is rejected. Reference
label updates are not part of metadata re-indexing.

## Verification

```bash
ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest tests
node --check app/static/platform-workspace.mjs
node --test tests/viewer-fullscreen.test.mjs
```

`test_platform.py` exercises project permissions, frozen guideline versions,
catalog/annotation isolation, atomic cohort refresh, imports through annotation,
manifest exports, DICOM UID matching and restart-safe/fenced catalog publication.
Unit tests do not establish clinical performance.

Verified locally on 2026-09-27 with Python 3.11:

- 28 Python tests passed, including real LiteMedSAM inference in all three planes
  and approval-bound PyRadiomics extraction. An initial cold-start axial timeout
  passed on a separate rerun and on the complete suite; no inference latency SLA
  is established by these tests.
- 9 fullscreen JavaScript tests passed; both workspace modules passed syntax checks.
- Live public discovery returned 176 IDC and 156 TCIA collection records. These
  counts describe the source response that day, not verified CT/MRI tumor cohorts.
- Browser checks covered admin project creation, dataset discovery/filtering,
  the cohort dialog, a public lung CT in the viewer and frozen guideline display.
