"""Import a DICOM folder that is already stored under the app data directory.

The browser upload stays capped. A collection of several gigabytes is read
from disk, one series at a time, and turned into cohort exams.
"""

from pathlib import Path
import threading
from uuid import uuid4

import numpy as np
import SimpleITK as sitk

from app.services.imaging import read_dicom_series_from_dir
from app.services.lung_geometry import MAX_VOXELS
from app.services.storage import DATA_ROOT


_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_catalogs: dict[str, dict] = {}


def resolve_data_dir(relative: str) -> Path:
    text = relative.strip().replace("\\", "/").lstrip("/")
    if not text or ".." in Path(text).parts or text.split("/", 1)[0] == "workspace":
        raise ValueError("Choisissez un dossier de dataset à l’intérieur de data.")
    root = DATA_ROOT.resolve()
    candidate = (root / text).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise ValueError("Choisissez un dossier de dataset à l’intérieur de data.")
    if not candidate.is_dir():
        raise ValueError("Ce dossier est introuvable dans data.")
    return candidate


def _study_date(name: str) -> str:
    parts = name.split("-")
    if len(parts) >= 3 and len(parts[0]) == 4 and parts[0].isdigit() and len(parts[1]) == 2 and len(parts[2]) == 2:
        return f"{parts[0]}-{parts[1]}-{parts[2]}"
    return name[:40]


def _series_label(name: str) -> str:
    parts = name.split("-")
    if len(parts) >= 2 and parts[1] and not parts[1].isdigit():
        return parts[1][:40]
    return parts[0][:40]


def scan_catalog(relative: str) -> dict:
    """List patients and timepoints from folder names and file counts. Pixels stay on disk."""
    root = resolve_data_dir(relative)
    cached = _catalogs.get(str(root))
    if cached:
        return cached
    catalog = _scan_catalog(root, relative)
    _catalogs[str(root)] = catalog
    return catalog


def _scan_catalog(root: Path, relative: str) -> dict:
    patients = []
    for patient_dir in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name):
        timepoints = []
        for study_dir in sorted((path for path in patient_dir.iterdir() if path.is_dir()), key=lambda path: path.name):
            for series_dir in sorted((path for path in study_dir.iterdir() if path.is_dir()), key=lambda path: path.name):
                slices = sum(1 for path in series_dir.iterdir() if path.is_file() and path.suffix.lower() == ".dcm")
                if slices < 2:
                    continue
                date = _study_date(study_dir.name)
                label = _series_label(series_dir.name)
                timepoints.append({
                    "id": series_dir.relative_to(root).as_posix(),
                    "label": f"{date} · {label} · {slices} coupes",
                    "slices": slices,
                })
        if timepoints:
            timepoints.sort(key=lambda item: item["label"])
            patients.append({"id": patient_dir.name, "timepoints": timepoints})
    text = relative.strip().replace("\\", "/").lstrip("/")
    return {"path": text, "patients": patients}


def _locate(catalog: dict, patient_id: str, timepoint_id: str):
    patients = catalog["patients"]
    patient_index = next((index for index, patient in enumerate(patients) if patient["id"] == patient_id), None)
    if patient_index is None:
        raise ValueError("Ce patient est introuvable dans le dossier.")
    timepoints = patients[patient_index]["timepoints"]
    time_index = next((index for index, item in enumerate(timepoints) if item["id"] == timepoint_id), None)
    if time_index is None:
        raise ValueError("Ce temps est introuvable pour ce patient.")
    return patient_index, time_index


def _neighbor(patients, patient_index, time_index, step):
    target = patient_index + step
    if target < 0 or target >= len(patients):
        return None
    timepoints = patients[target]["timepoints"]
    chosen = min(time_index, len(timepoints) - 1)
    return {"patient_id": patients[target]["id"], "timepoint_id": timepoints[chosen]["id"]}


def catalog_position(relative: str, patient_id: str, timepoint_id: str) -> dict:
    catalog = scan_catalog(relative)
    patients = catalog["patients"]
    patient_index, time_index = _locate(catalog, patient_id, timepoint_id)
    timepoints = patients[patient_index]["timepoints"]
    current = timepoints[time_index]
    return {
        "path": catalog["path"],
        "patient_id": patient_id,
        "timepoint_id": timepoint_id,
        "label": current["label"],
        "patient_index": patient_index,
        "patient_count": len(patients),
        "timepoint_index": time_index,
        "timepoint_count": len(timepoints),
        "previous_timepoint": None if time_index == 0 else {"patient_id": patient_id, "timepoint_id": timepoints[time_index - 1]["id"]},
        "next_timepoint": None if time_index + 1 >= len(timepoints) else {"patient_id": patient_id, "timepoint_id": timepoints[time_index + 1]["id"]},
        "previous_patient": _neighbor(patients, patient_index, time_index, -1),
        "next_patient": _neighbor(patients, patient_index, time_index, 1),
    }


def ensure_local_case(project_id: str, relative: str, patient_id: str, timepoint_id: str) -> str:
    """Read one series into the cohort. An exam already opened for this timepoint is reused."""
    from app.db import SessionLocal
    from app.oncometra import image_directory
    from app.oncometra_models import WorkspaceCase, WorkspaceProject
    from app import lung_api as lung
    from sqlalchemy import select

    catalog = scan_catalog(relative)
    _locate(catalog, patient_id, timepoint_id)
    root = resolve_data_dir(relative)
    series_dir = (root / timepoint_id).resolve()
    if not series_dir.is_relative_to(root) or not series_dir.is_dir():
        raise ValueError("Cette série est introuvable dans le dossier.")
    with SessionLocal() as db:
        project = db.get(WorkspaceProject, project_id)
        if project is None:
            raise ValueError("Cohorte introuvable")
        modality = project.modality
        existing = list(db.scalars(select(WorkspaceCase).where(WorkspaceCase.project_id == project_id)))
    for case in existing:
        source = case.source or {}
        if source.get("local_path") == catalog["path"] and source.get("local_patient") == patient_id and source.get("local_timepoint") == timepoint_id:
            _store_tumor_reference(case.id, series_dir)
            return case.id
    names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(series_dir))
    if len(names) < 2:
        raise ValueError("Cette série n’a pas assez de coupes pour être ouverte.")
    header = _header(names[0])
    if header["rows"] * header["cols"] * len(names) > MAX_VOXELS:
        raise ValueError("Ce volume dépasse la taille ouvrable dans la visionneuse.")
    image = read_dicom_series_from_dir(series_dir)
    lung.validate_image(image)
    if header["modality"] and header["modality"] != modality:
        raise ValueError(f"Cette série est en {header['modality']}, la cohorte attend du {modality}.")
    if not np.isfinite(sitk.GetArrayViewFromImage(image)).all():
        raise ValueError("Valeurs d’image non finies")
    image = sitk.DICOMOrient(image, "LPS")
    if not np.allclose(image.GetDirection(), np.eye(3).ravel(), atol=1e-4):
        raise ValueError("Acquisition oblique")
    position = catalog_position(relative, patient_id, timepoint_id)
    exam_id = f"{patient_id} · {position['label']}"[:100]
    case = WorkspaceCase(
        id=str(uuid4()), project_id=project_id, patient_id=exam_id, modality=modality,
        source={
            "source": "Dossier local", "license": "User-provided; rights attested",
            "sequence": position["label"], "series_instance_uid": header["series_uid"],
            "study_instance_uid": header["study_uid"], "local_path": catalog["path"],
            "local_patient": patient_id, "local_timepoint": timepoint_id, "reference_voxels": 0,
        },
    )
    destination = image_directory(case)
    destination.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(destination / "image.nii.gz"), True)
    with SessionLocal() as db:
        db.add(case)
        db.commit()
    _store_tumor_reference(case.id, series_dir)
    return case.id


def _store_tumor_reference(case_id: str, series_dir: Path) -> None:
    from app.db import SessionLocal
    from app.oncometra import image_directory
    from app.oncometra_models import WorkspaceCase
    from app.services.dicom_seg import study_has_seg, tumor_mask_for_series, write_reference

    with SessionLocal() as db:
        case = db.get(WorkspaceCase, case_id)
        if case is None:
            return
        source = dict(case.source or {})
    folder = image_directory(case)
    reference = folder / "reference.nii.gz"
    source["seg_present"] = study_has_seg(series_dir)
    if reference.exists() and source.get("tumor_from_seg"):
        source["seg_used"] = True
        _save_case_source(case_id, source)
        return
    image_path = folder / "image.nii.gz"
    if not image_path.exists():
        source["seg_used"] = False
        _save_case_source(case_id, source)
        return
    mask = tumor_mask_for_series(sitk.ReadImage(str(image_path)), series_dir)
    if mask is None:
        source["seg_used"] = bool(source.get("tumor_from_seg"))
        _save_case_source(case_id, source)
        return
    write_reference(sitk.ReadImage(str(image_path)), mask, reference)
    source["tumor_from_seg"] = True
    source["seg_used"] = True
    source["reference_voxels"] = int(mask.sum())
    _save_case_source(case_id, source)


def _save_case_source(case_id: str, source: dict) -> None:
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceCase
    with SessionLocal() as db:
        row = db.get(WorkspaceCase, case_id)
        if row is not None:
            row.source = source
            db.commit()


def import_status(project_id: str) -> dict:
    with _lock:
        current = _jobs.get(project_id)
        if not current:
            return {"state": "idle", "message": "Aucun import de dossier en cours."}
        return dict(current)


def start_folder_import(project_id: str, relative: str, user_id: str) -> dict:
    resolve_data_dir(relative)
    with _lock:
        current = _jobs.get(project_id)
        if current and current["state"] == "running":
            return dict(current)
        _jobs[project_id] = {
            "state": "running", "path": relative, "total": 0, "done": 0,
            "imported": 0, "skipped": 0, "message": "Lecture du dossier…",
        }
    threading.Thread(target=_run, args=(project_id, relative, user_id), daemon=True).start()
    return import_status(project_id)


def _update(project_id: str, **fields) -> None:
    with _lock:
        _jobs[project_id].update(fields)


def _series_folders(root: Path) -> list[Path]:
    return sorted({path.parent for path in root.rglob("*.dcm") if path.is_file()})


def _header(path: str) -> dict:
    reader = sitk.ImageFileReader()
    reader.SetFileName(path)
    reader.LoadPrivateTagsOff()
    reader.ReadImageInformation()

    def tag(key: str) -> str:
        return reader.GetMetaData(key).strip() if reader.HasMetaDataKey(key) else ""

    rows = int(tag("0028|0010") or 0)
    cols = int(tag("0028|0011") or 0)
    return {
        "modality": tag("0008|0060").upper(),
        "patient_id": " ".join(tag("0010|0020").split()),
        "series_uid": tag("0020|000e"),
        "study_uid": tag("0020|000d"),
        "description": " ".join(tag("0008|103e").split()),
        "rows": rows,
        "cols": cols,
    }


def _exam_id(base: str, used: set[str]) -> str:
    cleaned = "".join(ch for ch in base if ch.isprintable()).strip()[:80] or "EXAMEN"
    candidate = cleaned
    number = 2
    while candidate in used:
        suffix = f"-S{number}"
        candidate = cleaned[:100 - len(suffix)] + suffix
        number += 1
    used.add(candidate)
    return candidate


def _run(project_id: str, relative: str, user_id: str) -> None:
    from app.db import SessionLocal
    from app.oncometra import audit, image_directory
    from app.oncometra_models import WorkspaceCase, WorkspaceProject, WorkspaceUser
    from app import lung_api as lung
    from sqlalchemy import select

    imported = skipped = 0
    try:
        root = resolve_data_dir(relative)
        folders = _series_folders(root)
        _update(project_id, total=len(folders), message=f"0 / {len(folders)} séries")
        with SessionLocal() as db:
            project = db.get(WorkspaceProject, project_id)
            if project is None:
                raise ValueError("Cohorte introuvable")
            modality = project.modality
            existing = list(db.scalars(select(WorkspaceCase).where(WorkspaceCase.project_id == project_id)))
            used_ids = {case.patient_id for case in existing}
            known_series = {str((case.source or {}).get("series_instance_uid") or "") for case in existing}
        known_series.discard("")
        for index, folder in enumerate(folders, start=1):
            try:
                series_ids = list(sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(folder)) or [])
            except RuntimeError:
                skipped += 1
                _update(project_id, done=index, imported=imported, skipped=skipped,
                        message=f"{index} / {len(folders)} séries · {imported} importées")
                continue
            for series_id in series_ids:
                names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(folder), series_id)
                if len(names) < 2:
                    skipped += 1
                    continue
                header = _header(names[0])
                series_uid = header["series_uid"] or series_id
                if header["modality"] != modality or series_uid in known_series:
                    skipped += 1
                    continue
                if header["rows"] * header["cols"] * len(names) > MAX_VOXELS:
                    skipped += 1
                    continue
                try:
                    image = read_dicom_series_from_dir(folder, series_id)
                    lung.validate_image(image)
                    if not np.isfinite(sitk.GetArrayViewFromImage(image)).all():
                        raise ValueError("Valeurs d’image non finies")
                    image = sitk.DICOMOrient(image, "LPS")
                    if not np.allclose(image.GetDirection(), np.eye(3).ravel(), atol=1e-4):
                        raise ValueError("Acquisition oblique")
                except (ValueError, RuntimeError):
                    skipped += 1
                    continue
                exam_id = _exam_id(header["patient_id"] or folder.parent.parent.name, used_ids)
                case = WorkspaceCase(
                    id=str(uuid4()), project_id=project_id, patient_id=exam_id, modality=modality,
                    source={
                        "source": "Dossier local", "license": "User-provided; rights attested",
                        "sequence": header["description"], "series_instance_uid": series_uid,
                        "study_instance_uid": header["study_uid"], "local_path": relative,
                        "reference_voxels": 0,
                    },
                )
                destination = image_directory(case)
                destination.mkdir(parents=True, exist_ok=True)
                sitk.WriteImage(image, str(destination / "image.nii.gz"), True)
                with SessionLocal() as db:
                    db.add(case)
                    db.commit()
                known_series.add(series_uid)
                imported += 1
            _update(project_id, done=index, imported=imported, skipped=skipped,
                    message=f"{index} / {len(folders)} séries · {imported} importées · {skipped} laissées de côté")
        with SessionLocal() as db:
            user = db.get(WorkspaceUser, user_id)
            if user:
                audit(db, user, "local_folder_imported", project_id,
                      {"path": relative, "imported": imported, "skipped": skipped})
                db.commit()
        _update(project_id, state="done", imported=imported, skipped=skipped,
                message=f"Terminé. {imported} examens importés, {skipped} séries laissées de côté.")
    except Exception as error:
        _update(project_id, state="failed", imported=imported, skipped=skipped,
                message=str(error) or "L’import du dossier a échoué.")
