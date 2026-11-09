"""Organ HU and a cancer-specific lesion mask for one exam.

TotalSegmentator runs on the CPU in its own environment. A reader can start it
for the open exam; the validation page never launches it for a whole cohort.
An existing DICOM SEG tumor stays in place so the automatic lesion can be compared with it.
"""

from __future__ import annotations

from functools import lru_cache
import json
import logging
from pathlib import Path
import subprocess
import threading

import numpy as np
import SimpleITK as sitk

from app.services.storage import DATA_ROOT

logger = logging.getLogger(__name__)
ORGAN_TASK = "total"
_status_lock = threading.Lock()
_status: dict[str, dict] = {}
_active_case: str | None = None
# Open tasks only. Kidney cysts are not a tumor model and are intentionally absent.
_LESION_TASKS = (
    (("hepatocellular", "hepat", "liver", "hcc"), "liver_lesions", ("lesion", "tumor")),
    (("lung", "pulm", "nsclc", "sclc", "bronch"), "lung_nodules", ("nodule",)),
)


def autoseg_root() -> Path:
    return DATA_ROOT / "autoseg"


def series_result_dir(series_uid: str) -> Path:
    return autoseg_root() / series_uid


def lesion_task_for_cancer(cancer: str) -> tuple[str, tuple[str, ...]] | None:
    folded = (cancer or "").lower()
    for needles, task, labels in _LESION_TASKS:
        if any(needle in folded for needle in needles):
            return task, labels
    return None


def hu_rows(ct: np.ndarray, labels: np.ndarray, names: dict[int, str], voxel_mm3: float) -> list[dict]:
    rows = []
    for label_id, name in names.items():
        values = ct[labels == int(label_id)]
        if values.size < 8:
            continue
        values = values.astype(np.float64, copy=False)
        rows.append({
            "name": str(name),
            "label": str(name).replace("_", " "),
            "voxels": int(values.size),
            "volume_mm3": round(float(values.size) * voxel_mm3, 1),
            "hu_mean": round(float(values.mean()), 1),
            "hu_median": round(float(np.median(values)), 1),
            "hu_std": round(float(values.std()), 1),
            "hu_min": round(float(values.min()), 1),
            "hu_max": round(float(values.max()), 1),
            "hu_p05": round(float(np.percentile(values, 5)), 1),
            "hu_p25": round(float(np.percentile(values, 25)), 1),
            "hu_p75": round(float(np.percentile(values, 75)), 1),
            "hu_p95": round(float(np.percentile(values, 95)), 1),
        })
    rows.sort(key=lambda item: item["label"].lower())
    return rows


def binary_labels(labels: np.ndarray, names: dict[int, str], needles: tuple[str, ...]) -> np.ndarray:
    mask = np.zeros(labels.shape, dtype=np.uint8)
    for label_id, name in names.items():
        folded = str(name).lower()
        if any(needle in folded for needle in needles) and "vessel" not in folded:
            mask[labels == int(label_id)] = 1
    return mask


def totalseg_python() -> Path:
    path = Path(__file__).resolve().parents[2] / ".venv-totalseg" / "Scripts" / "python.exe"
    if not path.is_file():
        raise FileNotFoundError("TotalSegmentator n’est pas installé dans .venv-totalseg.")
    return path


def totalseg_cli() -> Path:
    folder = totalseg_python().parent
    for name in ("TotalSegmentator.exe", "TotalSegmentator.cmd", "totalsegmentator.exe"):
        path = folder / name
        if path.is_file():
            return path
    raise FileNotFoundError("La commande TotalSegmentator est introuvable.")


@lru_cache(maxsize=4)
def class_names(task: str) -> dict[int, str]:
    script = Path(__file__).resolve().parent / "ts_class_map.py"
    completed = subprocess.run(
        [str(totalseg_python()), str(script), task],
        check=True, capture_output=True, text=True,
    )
    payload = json.loads(completed.stdout)
    return {int(key): str(value) for key, value in payload.items()}


def on_reference_grid(reference, moving):
    if tuple(int(n) for n in moving.GetSize()) == tuple(int(n) for n in reference.GetSize()) and np.allclose(moving.GetOrigin(), reference.GetOrigin(), atol=1e-2) and np.allclose(moving.GetSpacing(), reference.GetSpacing(), atol=1e-3) and np.allclose(moving.GetDirection(), reference.GetDirection(), atol=1e-4):
        return moving
    return sitk.Resample(moving, reference, sitk.Transform(), sitk.sitkNearestNeighbor, 0, moving.GetPixelID())


def load_organ_table(case_dir: Path) -> dict | None:
    path = case_dir / "organs.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def attach_stored_result(case_id: str) -> None:
    """Copy a finished one-exam result onto the case without replacing a DICOM SEG."""
    from app.db import SessionLocal
    from app.oncometra import image_directory
    from app.oncometra_models import WorkspaceCase

    with SessionLocal() as db:
        case = db.get(WorkspaceCase, case_id)
        if case is None:
            return
        source = dict(case.source or {})
    uid = str(source.get("series_instance_uid") or "")
    stored = series_result_dir(uid)
    table = stored / "hu.json"
    if not uid or not table.is_file():
        return
    folder = image_directory(case)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "organs.json").write_text(table.read_text(encoding="utf-8"), encoding="utf-8")
    reference = folder / "reference.nii.gz"
    tumor = stored / "tumor.nii.gz"
    image_path = folder / "image.nii.gz"
    if reference.exists() or not tumor.is_file() or not image_path.is_file():
        return
    image = sitk.ReadImage(str(image_path))
    mask_image = on_reference_grid(image, sitk.ReadImage(str(tumor)))
    mask = sitk.GetArrayFromImage(mask_image).astype(np.uint8)
    if mask.shape != tuple(reversed(image.GetSize())) or not int(mask.sum()):
        return
    aligned = sitk.GetImageFromArray(mask)
    aligned.CopyInformation(image)
    sitk.WriteImage(aligned, str(reference), True)
    source["tumor_from_model"] = True
    source["reference_voxels"] = int(mask.sum())
    with SessionLocal() as db:
        row = db.get(WorkspaceCase, case_id)
        if row is not None:
            row.source = source
            db.commit()


def organ_color(label_id: int) -> list[int]:
    """Stable distinct color. The same TotalSegmentator label keeps the same hue."""
    hue = (float(label_id) * 137.508) % 360.0
    saturation, value = 0.72, 0.95
    chroma = value * saturation
    match = chroma * (1 - abs((hue / 60.0) % 2 - 1))
    base = value - chroma
    sector = int(hue // 60) % 6
    red, green, blue = (
        (chroma, match, 0.0), (match, chroma, 0.0), (0.0, chroma, match),
        (0.0, match, chroma), (match, 0.0, chroma), (chroma, 0.0, match),
    )[sector]
    return [int(round((channel + base) * 255)) for channel in (red, green, blue)]


def run_totalseg(task: str, source: Path, output: Path, *, fast: bool) -> None:
    command = [str(totalseg_cli()), "-i", str(source), "-o", str(output), "-ta", task,
               "--ml", "--statistics", "--statistics_extra", "--device", "cpu"]
    if fast:
        command.append("--fast")
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode:
        lines = [line.strip() for line in (completed.stderr or completed.stdout or "").splitlines() if line.strip()]
        detail = lines[-1][:240] if lines else f"code {completed.returncode}"
        raise RuntimeError(f"TotalSegmentator a échoué ({task}) : {detail}")


def detection_status(case_id: str) -> dict:
    with _status_lock:
        current = _status.get(case_id)
        if current:
            return dict(current)
    return {"state": "idle", "detail": "", "error": "", "seeded": False}


def _set_status(case_id: str, **fields) -> None:
    with _status_lock:
        current = dict(_status.get(case_id) or {"state": "idle", "detail": "", "error": "", "seeded": False})
        current.update(fields)
        _status[case_id] = current


def start_detection(case_id: str, study_id: str) -> dict:
    global _active_case
    with _status_lock:
        active = _status.get(_active_case or "", {})
        if _active_case and _active_case != case_id and active.get("state") == "running":
            raise RuntimeError("Une détection est déjà en cours sur un autre examen.")
        current = _status.get(case_id) or {}
        if current.get("state") == "running":
            return dict(current)
        _active_case = case_id
        _status[case_id] = {"state": "running", "detail": "Préparation de l’examen…", "error": "", "seeded": False}
    threading.Thread(target=_detect_worker, args=(case_id, study_id), daemon=True).start()
    return detection_status(case_id)


def _detect_worker(case_id: str, study_id: str) -> None:
    global _active_case
    try:
        result = execute_case(case_id, study_id, report=_set_status)
        _set_status(case_id, state="done", detail=result["detail"], error="", seeded=result["seeded"])
    except Exception as error:
        logger.exception("Automatic detection failed for %s", case_id)
        _set_status(case_id, state="error", detail="", error=str(error), seeded=False)
    finally:
        with _status_lock:
            if _active_case == case_id:
                _active_case = None


def execute_case(case_id: str, study_id: str, runner=None, report=None) -> dict:
    """Segment one exam. An existing organ file is reused instead of running twice."""
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceCase, WorkspaceProject

    runner = runner or run_totalseg
    report = report or (lambda _case, **_fields: None)
    with SessionLocal() as db:
        case = db.get(WorkspaceCase, case_id)
        if case is None:
            raise RuntimeError("Examen introuvable.")
        project = db.get(WorkspaceProject, case.project_id)
        source = dict(case.source or {})
        cancer = project.cancer_origin if project else ""
    folder = DATA_ROOT / "workspace" / "cases" / case_id
    image_path = folder / "image.nii.gz"
    if not image_path.is_file():
        raise RuntimeError("Le volume de cet examen est introuvable.")
    image = sitk.ReadImage(str(image_path))
    uid = str(source.get("series_instance_uid") or case_id)
    stored = series_result_dir(uid)
    stored.mkdir(parents=True, exist_ok=True)
    report(case_id, state="running", detail="Segmentation des organes…")
    organs_path = stored / "organs.nii.gz"
    if not organs_path.is_file():
        runner(ORGAN_TASK, image_path, organs_path, fast=True)
    names = class_names(ORGAN_TASK)
    labels = sitk.GetArrayFromImage(on_reference_grid(image, sitk.ReadImage(str(organs_path))))
    labels = np.rint(labels).astype(np.uint16)
    spacing = image.GetSpacing()
    voxel_mm3 = float(spacing[0] * spacing[1] * spacing[2])
    organ_labels = labels
    present = [int(value) for value in np.unique(organ_labels) if int(value) > 0]
    legend = [{"id": label_id, "name": names.get(label_id, f"label_{label_id}"),
               "label": names.get(label_id, f"Label {label_id}").replace("_", " "),
               "color": organ_color(label_id)} for label_id in present]
    tumor_task = None
    tumor_note = ""
    seeded = False
    lesion_mask = None
    seg_kept = bool(source.get("seg_used") or source.get("tumor_from_seg"))
    chosen = lesion_task_for_cancer(cancer)
    if chosen is None:
        tumor_note = "Aucun modèle ouvert de lésion ne correspond à ce type de cancer."
        if seg_kept:
            tumor_note += " Le segment SEG est conservé."
    else:
        tumor_task, needles = chosen
        report(case_id, state="running", detail="Segmentation des lésions…")
        lesions_path = stored / "lesions.nii.gz"
        if not lesions_path.is_file():
            try:
                runner(tumor_task, image_path, lesions_path, fast=False)
            except Exception as error:
                tumor_note = f"Organes prêts. La détection des lésions a échoué : {error}"
                if seg_kept:
                    tumor_note += " Le segment SEG est conservé."
                lesions_path = None
        if lesions_path and lesions_path.is_file():
            lesion_names = class_names(tumor_task)
            lesion_labels = np.rint(sitk.GetArrayFromImage(on_reference_grid(
                image, sitk.ReadImage(str(lesions_path))))).astype(np.uint16)
            mask = binary_labels(lesion_labels, lesion_names, needles)
            if int(mask.sum()):
                lesion_mask = mask
                tumor = sitk.GetImageFromArray(mask.astype(np.uint8))
                tumor.CopyInformation(image)
                sitk.WriteImage(tumor, str(stored / "tumor.nii.gz"), True)
                outcome = _record_ai_lesion(study_id, mask)
                seeded = outcome == "added"
                tumor_note = f"Lésions proposées par {tumor_task}."
                if seeded:
                    tumor_note += " La lésion « AI lesion detection » a été ajoutée."
                elif outcome == "covered":
                    tumor_note += " Elle est déjà couverte par une lésion enregistrée."
                if seg_kept:
                    tumor_note += " Le segment SEG est conservé pour la comparaison."
                elif not seeded and (folder / "reference.nii.gz").exists():
                    tumor_note += " Le brouillon déjà commencé n’a pas été remplacé."
            else:
                tumor_note = f"La tâche {tumor_task} n’a trouvé aucune lésion."
                if seg_kept:
                    tumor_note += " Le segment SEG est conservé."
    if lesion_mask is not None:
        labels = organ_labels.copy()
        labels[lesion_mask > 0] = np.uint16(65000)
        legend.append({"id": 65000, "name": "lesion", "label": "Lésion", "color": [220, 0, 0]})
    volume = sitk.GetImageFromArray(labels)
    volume.CopyInformation(image)
    sitk.WriteImage(volume, str(folder / "organ_labels.nii.gz"), True)
    report(case_id, state="running", detail="Calcul des unités Hounsfield…")
    payload = {
        "cancer": cancer, "organ_task": ORGAN_TASK, "organ_mode": "fast", "device": "cpu",
        "tumor_task": tumor_task, "tumor_note": tumor_note, "legend": legend,
        "organs": hu_rows(sitk.GetArrayFromImage(image), organ_labels, names, voxel_mm3),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    (folder / "organs.json").write_text(text, encoding="utf-8")
    (stored / "hu.json").write_text(text, encoding="utf-8")
    detail = f"{len(present)} organes colorés. {tumor_note}"
    return {"detail": detail, "seeded": seeded}


AI_LESION_NAME = "AI lesion detection"


def _record_ai_lesion(study_id: str, lesion_mask) -> str:
    """Add the detected lesion to the annotation list without replacing another lesion."""
    from fastapi import HTTPException
    from app.db import SessionLocal
    from app.lung_api import current_mask, image_for, nodules_for, save_revision, check_editable
    from app.models import AnnotationHead
    from app.oncometra import user_payload
    from app.oncometra_models import WorkspaceAssignment, WorkspaceUser
    from app.services.nodules import MAX_NODULE_LABEL, new_nodule

    with SessionLocal() as db:
        head = db.get(AnnotationHead, study_id)
        assignment = db.get(WorkspaceAssignment, study_id)
        user = db.get(WorkspaceUser, assignment.user_id) if assignment else None
        if head is None or user is None:
            return "skipped"
        try:
            check_editable(db, head)
            image = image_for(str(study_id))
        except HTTPException:
            return "skipped"
        mask = current_mask(head, image)
        detected = np.asarray(lesion_mask) > 0
        if mask.shape != detected.shape or not int(detected.sum()):
            return "skipped"
        if head.revision_id:
            nodules = nodules_for(db, head)
            existing = next((item for item in nodules if item.get("name") == AI_LESION_NAME), None)
            if existing:
                label = int(existing["label"])
                mask[mask == label] = 0
            else:
                label = max(int(item["label"]) for item in nodules) + 1
                if label > MAX_NODULE_LABEL:
                    return "skipped"
                nodule = new_nodule(label)
                nodule["name"] = AI_LESION_NAME
                nodule["color"] = [0, 188, 255]
                nodules = [*nodules, nodule]
        else:
            label = 1
            nodule = new_nodule(label)
            nodule["name"] = AI_LESION_NAME
            nodule["color"] = [0, 188, 255]
            nodules = [nodule]
        painted = detected & ((mask == 0) | (mask == label))
        if not int(painted.sum()):
            return "covered"
        mask[painted] = np.uint8(label)
        db.info["annotation_actor"] = user_payload(user)
        save_revision(db, head, image, mask, "ai-lesion",
                      {"source": AI_LESION_NAME, "nodule_label": label}, nodules, changed_nodule=label)
        return "added"


def organ_overlay(case_dir: Path) -> dict | None:
    table = load_organ_table(case_dir)
    labels = case_dir / "organ_labels.nii.gz"
    if not table or not labels.is_file() or not table.get("legend"):
        return None
    return {"legend": table["legend"], "encoding": "uint16-le", "tumor_note": table.get("tumor_note") or ""}
