"""Organ HU and, when no tumor SEG exists, a cancer-specific lesion mask.

TotalSegmentator runs on the CPU in its own environment. Results are stored
per series before the exam is opened, so the validation page only displays
work that is already finished.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import numpy as np
import SimpleITK as sitk

from app.services.storage import DATA_ROOT

ORGAN_TASK = "total"
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
