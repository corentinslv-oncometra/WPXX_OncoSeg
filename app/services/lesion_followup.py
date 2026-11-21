"""Number one patient's liver lesions from the exams Détecter has already finished.

Each opened exam keeps image.nii.gz beside the case. Organs and lesions stay in
the autoseg folder of that series. Dates without both masks are left out. The
first remaining date is the reference, in folder-name order.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time

import numpy as np
import SimpleITK as sitk

from app.services.exam_autoseg import mask_matches_image, series_result_dir
from app.services.lesion_tracking import (
    Exam, LesionTrackingError, track, write_result,
)
from app.services.storage import DATA_ROOT

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def patient_token(case) -> str:
    """Group longitudinal exams. A case without a shared patient stays alone."""
    source = case.source or {}
    if source.get("local_patient") and source.get("local_path") is not None:
        return f"local|{case.project_id}|{source['local_path']}|{source['local_patient']}"
    if source.get("source_patient_id"):
        return f"cohort|{case.project_id}|{source['source_patient_id']}"
    return f"case|{case.project_id}|{case.id}"


def collect_exams(case_id: str) -> tuple[list[Exam], list[str], list[str]]:
    """Ready exams of this patient, oldest folder name first, plus dates left out."""
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceCase
    from sqlalchemy import select

    with SessionLocal() as db:
        current = db.get(WorkspaceCase, case_id)
        if current is None:
            raise LesionTrackingError("Examen introuvable.")
        token = patient_token(current)
        cases = list(db.scalars(select(WorkspaceCase).where(WorkspaceCase.project_id == current.project_id)))
    siblings = [case for case in cases if patient_token(case) == token]
    siblings.sort(key=_sort_key)
    chosen, omitted = select_followup_cases(siblings)
    exams: list[Exam] = []
    skipped: list[str] = []
    used: dict[str, int] = {}
    for case in chosen:
        label = _unique_label(_time_label(case), used)
        exam = _exam_from_case(case, label)
        if exam is None:
            skipped.append(label)
        else:
            exams.append(exam)
    if not exams:
        raise LesionTrackingError(
            "Aucun examen de ce patient n’a encore d’organes et de lésions détectés."
        )
    return exams, skipped, omitted


def followup_status(case_id: str) -> dict:
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceCase

    with SessionLocal() as db:
        case = db.get(WorkspaceCase, case_id)
        if case is None:
            raise LesionTrackingError("Examen introuvable.")
        token = patient_token(case)
    ready = (_tracking_dir(token) / "tracking.json").is_file()
    with _lock:
        job = _jobs.get(token)
        payload = _idle() if job is None else _public(job)
    payload["stored"] = ready
    return payload


def start_followup(case_id: str) -> dict:
    """Start the liver numbering for this patient. A run already going is reused."""
    exams, skipped, omitted = collect_exams(case_id)
    token = _token_for(case_id)
    with _lock:
        current = _jobs.get(token)
        if current is not None and current["state"] == "running":
            return _public(current)
        _jobs[token] = {
            "state": "running",
            "detail": "Préparation du suivi…",
            "error": "",
            "baseline": "",
            "skipped": list(skipped),
            "lesions": [],
            "times": [exam.time_id for exam in exams],
            "percent": 4,
            "started_at": time.time(),
            "finished_at": None,
        }
        snapshot = _public(_jobs[token])
    threading.Thread(target=_worker, args=(token, exams, skipped, omitted), name=f"lesion-followup-{token[:24]}", daemon=True).start()
    return snapshot


def _worker(token: str, exams: list[Exam], skipped: list[str], omitted: list[str] | None = None) -> None:
    def report(percent: int, detail: str) -> None:
        _touch(token, percent=percent, detail=detail)

    try:
        result = track(exams, report=report)
        report(96, "Écriture du suivi…")
        write_result(result, exams, _tracking_dir(token))
        _finish(token, {
            "state": "done",
            "detail": _done_detail(result, skipped, omitted or []),
            "error": "",
            "baseline": result.baseline,
            "skipped": list(skipped),
            "lesions": [record.as_dict() for record in result.records],
            "times": [exam.time_id for exam in exams],
            "percent": 100,
        })
    except LesionTrackingError as error:
        _finish(token, _failed(error, skipped, exams))
    except Exception as error:
        logger.exception("Liver lesion tracking failed")
        _finish(token, _failed(error, skipped, exams))


def _touch(token: str, **fields) -> None:
    with _lock:
        job = _jobs.get(token)
        if job is None or job.get("state") != "running":
            return
        if "percent" in fields:
            fields["percent"] = max(int(job.get("percent") or 0), int(fields["percent"]))
        job.update(fields)


def _finish(token: str, payload: dict) -> None:
    with _lock:
        current = _jobs.get(token) or {}
        if "percent" not in payload:
            payload["percent"] = int(current.get("percent") or 0)
        _jobs[token] = {**payload, "started_at": current.get("started_at"), "finished_at": time.time()}


def _failed(error: Exception, skipped: list[str], exams: list[Exam]) -> dict:
    return {
        "state": "error",
        "detail": "",
        "error": str(error),
        "baseline": "",
        "skipped": list(skipped),
        "lesions": [],
        "times": [exam.time_id for exam in exams],
    }


def _exam_from_case(case, time_id: str) -> Exam | None:
    folder = DATA_ROOT / "workspace" / "cases" / case.id
    image_path = folder / "image.nii.gz"
    source = case.source or {}
    uid = str(source.get("series_instance_uid") or case.id)
    stored = series_result_dir(uid)
    organs_path = stored / "organs.nii.gz"
    lesions_path = stored / "lesions.nii.gz"
    if not image_path.is_file() or not organs_path.is_file() or not lesions_path.is_file():
        return None
    image = sitk.ReadImage(str(image_path))
    organs = sitk.ReadImage(str(organs_path))
    lesions = sitk.ReadImage(str(lesions_path))
    if not mask_matches_image(image, organs) or not mask_matches_image(image, lesions):
        return None
    return Exam(
        time_id=time_id,
        ct=sitk.GetArrayFromImage(image).astype(np.float32, copy=False),
        organs=np.rint(sitk.GetArrayFromImage(organs)).astype(np.int32),
        lesions=np.rint(sitk.GetArrayFromImage(lesions)).astype(np.int32),
        spacing_mm=tuple(float(value) for value in image.GetSpacing()),
        origin_mm=tuple(float(value) for value in image.GetOrigin()),
        direction=tuple(float(value) for value in image.GetDirection()),
    )


def _token_for(case_id: str) -> str:
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceCase

    with SessionLocal() as db:
        case = db.get(WorkspaceCase, case_id)
        if case is None:
            raise LesionTrackingError("Examen introuvable.")
        return patient_token(case)


def tracking_folder(case_id: str) -> Path:
    """Directory where this patient's tracking.json and per-date labels are written."""
    return _tracking_dir(_token_for(case_id))


def patient_timeline(case_id: str) -> list[dict]:
    """Every opened exam of this patient, in folder order, with its display date."""
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceCase
    from sqlalchemy import select

    with SessionLocal() as db:
        current = db.get(WorkspaceCase, case_id)
        if current is None:
            raise LesionTrackingError("Examen introuvable.")
        token = patient_token(current)
        cases = list(db.scalars(select(WorkspaceCase).where(WorkspaceCase.project_id == current.project_id)))
    siblings = [case for case in cases if patient_token(case) == token]
    siblings.sort(key=_sort_key)
    chosen, _omitted = select_followup_cases(siblings)
    rows = []
    used: dict[str, int] = {}
    for case in chosen:
        label = _unique_label(_time_label(case), used)
        source = dict(case.source or {})
        rows.append({
            "case_id": case.id,
            "label": label,
            "image": str(DATA_ROOT / "workspace" / "cases" / case.id / "image.nii.gz"),
            "series_uid": str(source.get("series_instance_uid") or case.id),
        })
    return rows


def _tracking_dir(token: str):
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return DATA_ROOT / "workspace" / "tracking" / digest


def _sort_key(case) -> tuple:
    source = case.source or {}
    stamp = case.created_at.isoformat() if case.created_at is not None else ""
    return (str(source.get("local_timepoint") or source.get("visit") or ""), str(case.patient_id), stamp)


def select_followup_cases(cases: list) -> tuple[list, list[str]]:
    """One row per contrast series. A non-contrast series yields when that day has another series."""
    grouped: dict[str, list] = {}
    for case in cases:
        grouped.setdefault(_date_folder(case), []).append(case)
    kept = []
    omitted = []
    for case in cases:
        group = grouped[_date_folder(case)]
        contrast = [item for item in group if not _is_precontrast(item)]
        if contrast and all(item is not case for item in contrast):
            omitted.append(_series_folder(case) or _date_folder(case))
            continue
        kept.append(case)
    return kept, omitted


def _path_parts(case) -> list[str]:
    source = case.source or {}
    raw = str(source.get("local_timepoint") or source.get("visit") or case.patient_id)
    return [part for part in raw.replace("\\", "/").split("/") if part]


def _date_folder(case) -> str:
    parts = _path_parts(case)
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else str(case.patient_id)


def _series_folder(case) -> str:
    parts = _path_parts(case)
    if len(parts) >= 2:
        return parts[-1]
    return ""


def _is_precontrast(case) -> bool:
    return "PRE" in _series_folder(case).upper()


def _time_label(case) -> str:
    return _date_folder(case)


def _unique_label(label: str, used: dict[str, int]) -> str:
    count = used.get(label, 0) + 1
    used[label] = count
    if count == 1:
        return label
    return f"{label} · {count}"


def _done_detail(result, skipped: list[str], omitted: list[str] | None = None) -> str:
    lesion_count = len({record.lesion_id for record in result.records})
    date_count = len(result.labels)
    text = f"{_plural(lesion_count, 'lésion suivie', 'lésions suivies')} sur {_plural(date_count, 'examen', 'examens')}."
    if skipped:
        text += f" {_plural(len(skipped), 'examen ignoré', 'examens ignorés')}, sans détection."
    if omitted:
        text += f" {_plural(len(omitted), 'série sans contraste ignorée', 'séries sans contraste ignorées')}."
    return text


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _idle() -> dict:
    return {
        "state": "idle", "detail": "", "error": "", "baseline": "",
        "skipped": [], "lesions": [], "times": [], "percent": 0, "elapsed_s": 0,
    }


def _public(stored: dict) -> dict:
    started = stored.get("started_at")
    end = stored.get("finished_at") or time.time()
    elapsed = max(0, int(end - started)) if started else 0
    return {
        "state": stored["state"],
        "detail": stored["detail"],
        "error": stored["error"],
        "baseline": stored["baseline"],
        "skipped": list(stored["skipped"]),
        "lesions": list(stored["lesions"]),
        "times": list(stored["times"]),
        "percent": int(stored.get("percent") or 0),
        "elapsed_s": elapsed,
    }
