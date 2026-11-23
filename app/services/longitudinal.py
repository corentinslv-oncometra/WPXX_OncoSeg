"""Side-by-side lesion follow-up for one patient.

The tracking file already numbers lesions. This module adds the geometry the
viewer needs: the axial slice at the centre of each lesion, and a rigid Z
shift that puts every date into the baseline coordinate system.
"""

from __future__ import annotations

import json
import os

import numpy as np
import SimpleITK as sitk

from app.services.lesion_followup import followup_running, patient_timeline, tracking_folder
from app.services.lesion_tracking import LesionTrackingError, _safe_name

_MAX_LESION_NUMBER = 65535


class LongitudinalError(LesionTrackingError):
    pass


class NumberSwapRequired(LongitudinalError):
    """The requested number already belongs to another lesion. The caller must confirm the exchange."""


def native_z_mm(slice_index: int, origin_z: float, spacing_z: float, direction_zz: float) -> float:
    return float(origin_z + slice_index * spacing_z * direction_zz)


def slice_for_registered_z(target_mm: float, origin_z: float, spacing_z: float, direction_zz: float, shift_mm: float, count: int) -> int:
    """Slice whose registered Z is closest to target_mm."""
    step = float(spacing_z) * float(direction_zz)
    if count <= 0 or abs(step) < 1e-6:
        return 0
    index = int(np.rint((float(target_mm) - float(shift_mm) - float(origin_z)) / step))
    return max(0, min(count - 1, index))


def registered_shift(centers: list[dict]) -> float:
    deltas = [
        float(item["registered_z_mm"]) - float(item["z_mm"])
        for item in centers
        if item.get("registered_z_mm") is not None and item.get("z_mm") is not None
    ]
    if not deltas:
        return 0.0
    return round(float(np.median(deltas)), 3)


def lesion_centers(labels: np.ndarray, origin, spacing, direction) -> list[dict]:
    """Centre of each numbered lesion on its own axial grid."""
    labels = np.asarray(labels)
    direction_m = np.asarray(direction, dtype=float).reshape(3, 3)
    origin_v = np.asarray(origin, dtype=float)
    spacing_v = np.asarray(spacing, dtype=float)
    centers = []
    for lesion_id in [int(value) for value in np.unique(labels) if int(value) > 0]:
        zyx = np.argwhere(labels == lesion_id)
        mean_zyx = zyx.astype(float).mean(axis=0)
        index_xyz = np.array([mean_zyx[2], mean_zyx[1], mean_zyx[0]])
        point = origin_v + direction_m @ (index_xyz * spacing_v)
        centers.append({
            "lesion_id": lesion_id,
            "axial_index": int(np.clip(int(np.rint(mean_zyx[0])), 0, labels.shape[0] - 1)),
            "z_mm": round(float(point[2]), 3),
        })
    return centers


def evolution_rows(records: list[dict], times: list[str]) -> list[dict]:
    """One row per lesion. The percentage is that lesion's own change at the last exam."""
    rows = []
    lesion_ids = sorted({int(record["lesion_id"]) for record in records})
    for lesion_id in lesion_ids:
        by_time = {record["time_id"]: record for record in records if int(record["lesion_id"]) == lesion_id}
        volumes = {time_id: None if by_time.get(time_id) is None else by_time[time_id].get("volume_cm3") for time_id in times}
        latest = by_time.get(times[-1]) if times else None
        origin = next((by_time[time_id] for time_id in times if time_id in by_time), None)
        rows.append({
            "lesion_id": lesion_id,
            "status": None if latest is None else latest.get("status"),
            "volumes": volumes,
            "delta_percent": _lesion_delta(volumes, times),
            "event": None if origin is None else origin.get("event"),
            "parent_ids": [] if origin is None else list(origin.get("parent_ids") or []),
            "measures": {time_id: _measure(by_time.get(time_id)) for time_id in times},
        })
    return rows


def _lesion_delta(volumes: dict, times: list[str]) -> float | None:
    """Signed change of this lesion from its previous volume to the last exam."""
    if len(times) < 2:
        return None
    last = volumes.get(times[-1])
    last_value = 0.0 if not isinstance(last, (int, float)) else float(last)
    reference = None
    for time_id in reversed(times[:-1]):
        value = volumes.get(time_id)
        if isinstance(value, (int, float)) and float(value) > 0:
            reference = float(value)
            break
    if reference is None:
        return None
    return round((last_value - reference) / reference * 100.0, 1)


def _measure(record: dict | None) -> dict | None:
    """Characteristics shown for one lesion at one date. An empty mask stays a short absence."""
    if record is None:
        return None
    volume = record.get("volume_cm3")
    absent = volume in (None, 0)
    return {
        "status": record.get("status") or ("disparue" if absent else None),
        "volume_cm3": 0.0 if absent else volume,
        "long_axis_3d_mm": None if absent else record.get("long_axis_3d_mm"),
        "long_axis_axial_mm": None if absent else record.get("long_axis_axial_mm"),
        "hu_mean": None if absent else record.get("hu_mean"),
    }


def longitudinal_bundle(case_id: str, user_id: str) -> dict:
    """Dates, lesion centres and the evolution table for the viewer."""
    folder = tracking_folder(case_id)
    path = folder / "tracking.json"
    if not path.is_file():
        raise LongitudinalError("Aucun suivi enregistré pour ce patient.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    times = [str(time_id) for time_id in payload.get("times") or []]
    records = list(payload.get("lesions") or [])
    if _missing_registration(records):
        raise LongitudinalError("Le suivi enregistré n’a pas de position recalée.")
    timeline = {row["label"]: row for row in patient_timeline(case_id)}
    studies = _studies_for_user(user_id, [row["case_id"] for row in timeline.values()])
    dates = []
    for time_id in times:
        row = timeline.get(time_id)
        if row is None:
            continue
        study_id = studies.get(row["case_id"])
        if study_id is None:
            continue
        geometry = _image_geometry(row["image"])
        labels = _read_labels(folder / f"{_safe_name(time_id)}.nii.gz")
        centers = lesion_centers(labels, geometry["origin_xyz"], geometry["spacing_xyz"], geometry["direction"]) if labels is not None else []
        recorded = [record for record in records if record.get("time_id") == time_id]
        by_id = {int(record["lesion_id"]): record for record in recorded}
        for center in centers:
            stored = by_id.get(center["lesion_id"]) or {}
            center["registered_z_mm"] = stored.get("registered_z_mm", center["z_mm"])
            center["status"] = stored.get("status")
            center["volume_cm3"] = stored.get("volume_cm3")
        dates.append({
            **geometry,
            "time_id": time_id,
            "study_id": study_id,
            "shift_mm": registered_shift(centers),
            "lesions": centers,
        })
    if not dates:
        raise LongitudinalError("Le suivi existe, mais aucun examen n’est ouvert pour l’afficher.")
    return {
        "baseline": payload.get("baseline") or dates[0]["time_id"],
        "dates": dates,
        "rows": evolution_rows(records, [item["time_id"] for item in dates]),
    }


def number_mapping(known: set[int], source: int, target: int, *, swap: bool) -> dict[int, int]:
    """Rename one identity, or exchange it with another. The result is a permutation, never a merge."""
    if source < 1 or target < 1 or source > _MAX_LESION_NUMBER or target > _MAX_LESION_NUMBER:
        raise LongitudinalError(f"Le numéro doit être un entier entre 1 et {_MAX_LESION_NUMBER}.")
    if source not in known:
        raise LongitudinalError(f"Le numéro {source} n’est pas dans ce suivi.")
    if source == target:
        return {}
    if target in known and not swap:
        raise NumberSwapRequired(f"N{target} est déjà une lésion. Échanger N{source} et N{target} pour toutes les dates ?")
    if target in known:
        return {source: target, target: source}
    return {source: target}


def apply_id_map(labels: np.ndarray, mapping: dict[int, int]) -> np.ndarray:
    """Apply a permutation to label voxels. Each voxel is read from the original number."""
    if not mapping:
        return np.asarray(labels)
    source = np.asarray(labels)
    if source.size and int(source.max()) > _MAX_LESION_NUMBER:
        raise LongitudinalError("Un masque contient un numéro trop grand.")
    table = np.arange(_MAX_LESION_NUMBER + 1, dtype=np.uint16)
    for old, new in mapping.items():
        table[int(old)] = np.uint16(new)
    return table[source.astype(np.uint16, copy=False)]


def remap_records(records: list[dict], mapping: dict[int, int]) -> list[dict]:
    """Move every record and every parent or child reference with the same permutation."""
    if not mapping:
        return records
    remapped = []
    for record in records:
        item = dict(record)
        item["lesion_id"] = mapping.get(int(item["lesion_id"]), int(item["lesion_id"]))
        item["parent_ids"] = [mapping.get(int(value), int(value)) for value in item.get("parent_ids") or []]
        item["child_ids"] = [mapping.get(int(value), int(value)) for value in item.get("child_ids") or []]
        remapped.append(item)
    return remapped


def commit_number_change(folder, source: int, target: int, *, swap: bool) -> bool:
    """Rewrite tracking.json and every date mask. Returns True when two numbers were exchanged."""
    path = folder / "tracking.json"
    if not path.is_file():
        raise LongitudinalError("Aucun suivi enregistré pour ce patient.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = list(payload.get("lesions") or [])
    known = {int(record["lesion_id"]) for record in records}
    loaded = []
    for time_id in _tracked_times(payload, records):
        label_path = folder / f"{_safe_name(time_id)}.nii.gz"
        if not label_path.is_file():
            continue
        image = sitk.ReadImage(str(label_path))
        array = np.rint(sitk.GetArrayFromImage(image)).astype(np.uint16)
        known.update(int(value) for value in np.unique(array) if int(value) > 0)
        loaded.append((label_path, image, array))
    mapping = number_mapping(known, int(source), int(target), swap=swap)
    if not mapping:
        return False
    payload["lesions"] = remap_records(records, mapping)
    payload["number_changes"] = [*list(payload.get("number_changes") or []), {
        "from": int(source), "to": int(target), "swapped": target in known and int(source) != int(target),
    }][-20:]
    pending = []
    try:
        for label_path, image, array in loaded:
            changed = sitk.GetImageFromArray(apply_id_map(array, mapping))
            changed.CopyInformation(image)
            temporary = label_path.with_name(f".{label_path.name}.renumber.nii.gz")
            sitk.WriteImage(changed, str(temporary), True)
            pending.append(temporary)
        temporary_json = folder / ".tracking.json.renumber"
        temporary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        pending.append(temporary_json)
        for label_path, _image, _array in loaded:
            os.replace(label_path.with_name(f".{label_path.name}.renumber.nii.gz"), label_path)
        os.replace(temporary_json, path)
        pending.clear()
    finally:
        for temporary in pending:
            temporary.unlink(missing_ok=True)
    return bool(mapping.get(int(source)) == int(target) and mapping.get(int(target)) == int(source))


def renumber_lesion(case_id: str, user_id: str, source: int, target: int, *, swap: bool) -> dict:
    """Change one lesion number for the whole follow-up and return the viewer bundle."""
    if followup_running(case_id):
        raise LongitudinalError("Un calcul de suivi est en cours. Le numéro pourra être modifié quand il sera terminé.")
    swapped = commit_number_change(tracking_folder(case_id), source, target, swap=swap)
    bundle = longitudinal_bundle(case_id, user_id)
    bundle["renumber"] = {"from": int(source), "to": int(target), "swapped": swapped}
    return bundle


def _tracked_times(payload: dict, records: list[dict]) -> list[str]:
    times = [str(time_id) for time_id in payload.get("times") or []]
    if times:
        return times
    return sorted({str(record.get("time_id")) for record in records if record.get("time_id")})


def label_volume(case_id: str, time_id: str) -> np.ndarray:
    folder = tracking_folder(case_id)
    labels = _read_labels(folder / f"{_safe_name(time_id)}.nii.gz")
    if labels is None:
        raise LongitudinalError("Le masque numéroté de cette date est introuvable.")
    known = {row["label"] for row in patient_timeline(case_id)}
    if time_id not in known:
        raise LongitudinalError("Cette date n’appartient pas à ce patient.")
    return np.ascontiguousarray(labels.astype("<u2"))


def _missing_registration(records: list[dict]) -> bool:
    """Files written before the registered Z was stored cannot align different slice counts."""
    present = [record for record in records if record.get("volume_cm3")]
    return any("registered_z_mm" not in record for record in present)


def _studies_for_user(user_id: str, case_ids: list[str]) -> dict[str, str]:
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceAssignment
    from sqlalchemy import select

    if not case_ids:
        return {}
    with SessionLocal() as db:
        rows = db.execute(select(WorkspaceAssignment.case_id, WorkspaceAssignment.study_id).where(
            WorkspaceAssignment.user_id == user_id,
            WorkspaceAssignment.case_id.in_(case_ids),
        )).all()
    return {case_id: study_id for case_id, study_id in rows}


def _image_geometry(path: str) -> dict:
    reader = sitk.ImageFileReader()
    reader.SetFileName(path)
    reader.ReadImageInformation()
    return {
        "size_xyz": [int(value) for value in reader.GetSize()],
        "spacing_xyz": [float(value) for value in reader.GetSpacing()],
        "origin_xyz": [float(value) for value in reader.GetOrigin()],
        "direction": [float(value) for value in reader.GetDirection()],
    }


def _read_labels(path) -> np.ndarray | None:
    if not path.is_file():
        return None
    array = sitk.GetArrayFromImage(sitk.ReadImage(str(path)))
    return np.rint(array).astype(np.uint16)
