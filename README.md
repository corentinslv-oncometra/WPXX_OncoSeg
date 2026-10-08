# Oncometra Imaging Workspace

The unified workspace connects dataset discovery and cohort preparation to the
existing CT/MRI annotation, review, and approved-feature-file workflows. Run
`app.oncometra:app`; do not use the legacy PACS/RIS entry point.

- **Datasets (administrators):** TCIA/IDC metadata discovery, OncoRadar catalog
  import, source evidence, access conditions, separate commercial-use review,
  acquisition status and paginated cohort manifests.
- **Projects:** administrator-created cancer-of-origin cohorts, CT or MRI,
  versioned guidelines, target-site lists and explicit project membership.
- **Worklist / annotation / review:** existing independent readings, editable
  model proposals, immutable submissions and independent approval remain intact.
- **Engineering:** idempotent metadata refresh, stable series identities,
  portable project manifests, audit events and a leased catalog job worker.

See [integration decisions and limitations](docs/oncoradar-integration.md) and
[the local runbook](docs/unified-workspace.md). This is a public-data
demo, not a clinically validated or multi-tenant production system.

## Existing Annotation Demo

This branch deploys the standalone **CT / MRI annotation and radiomics demo**,
not the legacy PACS/RIS application described below. Use `app.oncometra:app`.

- Authenticated reader, reviewer, and administrator accounts; independent masks.
- Seven tumor projects, with five real public, tumor-positive example volumes.
- Multi-planar annotation, multi-lesion editing, undo, completion and independent approval.
- NIfTI / NRRD mask export, image-and-mask bundles, and original DICOM download for DICOM imports.
- Real PyRadiomics extraction pinned to image, mask revision, and protocol hashes.

See [the local demo guide](docs/oncometra-demo.md) for setup and limitations.
Accounts, uploads, and extraction results stay in `APP_STORAGE_ROOT` (default
`./data`). Do not upload patient or company-private data.

## Legacy Prototype Reference

The following describes the older `app.main` application. It is not exposed by
the Oncometra demo entry point and is retained as development history.

### CT Early Response Web App (Prototype)

See [docs/ai-native-pacs-ris-blueprint.md](docs/ai-native-pacs-ris-blueprint.md) for the broader product direction that extends this prototype toward an AI-native PACS/RIS platform.

See [docs/mvp-scaffold.md](docs/mvp-scaffold.md) for the current MVP scaffold that adds a worklist, reporting, AI task tracking, and local fine-tune queue.

This project provides a working prototype for an AI-native PACS/RIS workstation with an early treatment response CT workflow:

- Bulk upload DICOM folders with metadata extraction, or upload DICOM zip/NIfTI studies across CT, MRI, ultrasound, mammography, and X-ray-style modalities
- Review studies in an embedded PACS viewer with single-series or comparison layouts, active-series selection, modality presets, mouse window/level, inversion, zoom, cine stack playback, axial/coronal/sagittal MPR, measurements, and segmentation mask editing
- Manage a RIS worklist with scheduling and billing charge capture
- Draft reports in a browser word processor and insert AI outputs or saved measurements
- Dictate reports through hosted browser speech recognition or a local/open-source speech-to-text adapter such as Whisper.cpp
- Upload baseline CT and early follow-up CT (2-6 weeks) for the early-response workflow
- Run semi-automatic lesion segmentation using open-source tooling adapters
- Review and edit segmentation slice-by-slice in a web viewer
- Produce an early response score from 0-100
- Train a radiomics regression model from labeled prior studies

## Stack

- Backend: FastAPI
- Imaging I/O: SimpleITK
- Segmentation adapters:
  - `TotalSegmentator` CLI adapter (if installed)
  - region-growing fallback (bounded seeded grower)
- Radiomics/modeling: handcrafted radiomics + lightweight linear regression
- Speech-to-text: optional open-source Whisper.cpp adapter
- Hosted dictation fallback: browser `SpeechRecognition` when the backend model is not configured
- Frontend: HTML/CSS/vanilla JS PACS/RIS workstation

## Run

From the project directory, create a virtual environment and install into it:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-demo.txt
python -m app.oncometra
```

Once `.venv` is activated, `python` is that environment. SQLite and images stay
under `.\data`, and the workspace opens at `http://127.0.0.1:8020`. The first
start creates user `saad` and writes the password to `data\admin-password.txt`
unless `ONCOMETRA_ADMIN_PASSWORD` is already set.

`powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1` creates `.venv`,
installs the dependencies there, and starts the app.

The older PACS/RIS prototype is still available with `uvicorn app.main:app --reload`
after `pip install -r requirements.txt`. Open `http://127.0.0.1:8000`.

Configuration starts from [.env.example](.env.example).

## Data format

Upload either:

- DICOM folder: select a local folder from the bulk import panel
- NIfTI: `.nii` or `.nii.gz`
- DICOM archive: `.zip` containing one imaging series

For single-frame X-ray, mammography, or ultrasound studies, upload the primary series and leave the comparison upload empty. Folder imports and single-frame studies store a one-slice volume internally so the same viewer controls still work.

## API overview

- `POST /api/studies` create a study workspace from baseline/follow-up uploads
- `POST /api/dicom/bulk` create one worklist-ready study per DICOM series in a folder upload
- `GET /api/worklist` list reading queue items
- `GET /api/studies/{id}/workspace` retrieve study, worklist, report, AI, and integration context
- `PATCH /api/studies/{id}/worklist` update workflow status and assignment
- `GET /api/studies/{id}/report` read the current draft report
- `PUT /api/studies/{id}/report` save report draft or finalize it
- `GET /api/studies/{id}/slice` retrieve an image + mask plane PNG with window/MPR options
- `PUT /api/studies/{id}/mask/slice` persist edited slice mask
- `GET /api/studies/{id}/measurements` list viewer measurements
- `POST /api/studies/{id}/measurements` save a viewer measurement
- `POST /api/studies/{id}/segment/auto` run semi-auto segmentation
- `POST /api/studies/{id}/ai/tasks` run scaffolded AI tasks
- `GET /api/schedule` and `POST /api/schedule` manage RIS appointments
- `GET /api/billing` and `POST /api/billing` manage billing items
- `GET /api/speech/status` inspect the local speech engine
- `POST /api/speech/transcribe` transcribe browser microphone audio when Whisper.cpp is configured
- `GET /api/models` inspect the indexed model catalog
- `POST /api/model/train` fit the radiomics model from labels
- `GET /api/training-runs` inspect fine-tune requests

## Dictation

The report dictation button uses browser speech recognition when available. To enable local backend dictation, install Whisper.cpp and ffmpeg, download a Whisper model, then set:

```bash
STT_PROVIDER=whisper_cpp
WHISPER_CPP_BINARY=/path/to/whisper-cli
WHISPER_CPP_MODEL=/path/to/ggml-base.en.bin
FFMPEG_BINARY=ffmpeg
```

## Notes for production hardening

- Add authentication, audit logging, and PHI controls
- Replace fallback segmentation with tumor-site-specific foundation models
- Add DICOM metadata QC and orientation normalization checks
- Version models and require external validation before clinical use
- Add uncertainty calibration and confidence intervals

## Important

This is a research/prototyping codebase and is **not** a regulated clinical decision system.
