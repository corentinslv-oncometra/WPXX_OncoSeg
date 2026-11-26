"""Number one patient's lesions from the exams Détecter has already finished.

Each opened exam keeps image.nii.gz beside the case. Organs and lesions stay in
the autoseg folder of that series. A calendar day contributes one CT series:
the chest for a lung cancer, or a whole-body CT if that chest is missing; the
series that contains the liver for a liver cancer, portal venous when several
do. PET and scout series are left out. Dates without both masks are left out.
The first remaining date is the reference, in folder-name order.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time

import numpy as np
import SimpleITK as sitk

from app.services.exam_autoseg import binary_labels, class_names, lesion_task_for_cancer, mask_matches_image, series_result_dir
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


def collect_exams(case_id: str) -> tuple[list[Exam], list[str], list[str], str]:
    """Ready exams of this patient, oldest folder name first, plus dates left out."""
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceCase, WorkspaceProject
    from sqlalchemy import select

    with SessionLocal() as db:
        current = db.get(WorkspaceCase, case_id)
        if current is None:
            raise LesionTrackingError("Examen introuvable.")
        project = db.get(WorkspaceProject, current.project_id)
        cancer = project.cancer_origin if project else ""
        token = patient_token(current)
        cases = list(db.scalars(select(WorkspaceCase).where(WorkspaceCase.project_id == current.project_id)))
    siblings = [case for case in cases if patient_token(case) == token]
    siblings.sort(key=_sort_key)
    chosen, omitted = select_followup_cases(siblings, cancer)
    exams: list[Exam] = []
    skipped: list[str] = []
    used: dict[str, int] = {}
    for case in chosen:
        label = _unique_label(_time_label(case), used)
        exam = _exam_from_case(case, label, cancer)
        if exam is None:
            skipped.append(label)
        else:
            exams.append(exam)
    if not exams:
        raise LesionTrackingError(
            "Aucun examen de ce patient n’a encore d’organes et de lésions détectés."
        )
    return exams, skipped, omitted, _followup_organ(cancer) or ""


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
    exams, skipped, omitted, organ = collect_exams(case_id)
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
    threading.Thread(target=_worker, args=(token, exams, skipped, omitted, organ), name=f"lesion-followup-{token[:24]}", daemon=True).start()
    return snapshot


def _worker(token: str, exams: list[Exam], skipped: list[str], omitted: list[str] | None = None, organ: str = "") -> None:
    def report(percent: int, detail: str) -> None:
        _touch(token, percent=percent, detail=detail)

    try:
        result = track(exams, report=report, organ=organ)
        report(96, "Écriture du suivi…")
        with _lock:
            if (_jobs.get(token) or {}).get("state") == "running":
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


def followup_lesion_labels(labels: np.ndarray, cancer: str) -> np.ndarray:
    """Keep the lesion class of this cancer.

    The lung nodule file also stores the whole lung as its own label. That lung
    is not a lesion. The same rule as the viewer keeps the nodule class only.
    """
    chosen = lesion_task_for_cancer(cancer)
    if chosen is None:
        return labels
    task, needles = chosen
    return binary_labels(labels, class_names(task), needles).astype(np.int32)


def _exam_from_case(case, time_id: str, cancer: str = "") -> Exam | None:
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
        lesions=followup_lesion_labels(np.rint(sitk.GetArrayFromImage(lesions)), cancer),
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


def followup_running(case_id: str) -> bool:
    """True while Suivre is still writing this patient's numbers."""
    token = _token_for(case_id)
    with _lock:
        return (_jobs.get(token) or {}).get("state") == "running"


def patient_timeline(case_id: str) -> list[dict]:
    """Every opened exam of this patient, in folder order, with its display date."""
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceCase, WorkspaceProject
    from sqlalchemy import select

    with SessionLocal() as db:
        current = db.get(WorkspaceCase, case_id)
        if current is None:
            raise LesionTrackingError("Examen introuvable.")
        project = db.get(WorkspaceProject, current.project_id)
        cancer = project.cancer_origin if project else ""
        token = patient_token(current)
        cases = list(db.scalars(select(WorkspaceCase).where(WorkspaceCase.project_id == current.project_id)))
    siblings = [case for case in cases if patient_token(case) == token]
    siblings.sort(key=_sort_key)
    chosen, _omitted = select_followup_cases(siblings, cancer)
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


# One CT series per calendar day. The organ of the cancer comes first, then the
# phase. Portal venous is the phase used to measure a liver lesion.
_PORTAL = 4
_ARTERIAL = 3
_CONTRAST = 2
_DELAYED = 1
_NONCONTRAST = 0
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TOKEN_C = re.compile(r"(^|[^A-Z])C([^A-Z]|$)")
_NOT_CT_VOLUME = re.compile(r"(^|[^A-Z])(PET|TOPOGRAM|TOPO|SCOUT|LOCALIZER|LOCALISER)([^A-Z]|$)")
_BROAD_TORSO = re.compile(r"(^|[^A-Z])(WB|CAP)([^A-Z]|$)|WHOLE BODY|WHOLEBODY|CHESTABD")
_LUNG_FIELD = re.compile(r"CHEST|THORAX|LUNG|PULMON")
_LIVER_FIELD = re.compile(r"LIVER|HEPAT|ABDOMEN|(^|[^A-Z])ABD([^A-Z]|$)")
_OUTSIDE_LIVER = re.compile(r"CHEST|THORAX|LUNG|PULMON|HEAD|BRAIN|PELVIS")


def select_followup_cases(cases: list, cancer: str = "") -> tuple[list, list[str]]:
    """One CT series per calendar day, covering the organ of this cancer.

    PET and scout series are left out. A lung cancer prefers a chest CT, then a
    whole-body CT. A liver cancer prefers a series that contains the liver, and
    the portal venous phase when several do. The folder name only breaks a tie.
    """
    organ = _followup_organ(cancer)
    grouped: dict[str, list] = {}
    order: list[str] = []
    omitted: list[str] = []
    for case in cases:
        if not _is_ct_volume(case):
            omitted.append(_series_folder(case) or _calendar_day(case))
            continue
        day = _calendar_day(case)
        if day not in grouped:
            order.append(day)
            grouped[day] = []
        grouped[day].append(case)
    kept = []
    for day in order:
        group = grouped[day]
        chosen = max(group, key=lambda item: _adequacy_key(item, organ))
        kept.append(chosen)
        for case in group:
            if case is not chosen:
                omitted.append(_series_folder(case) or day)
    return kept, omitted


def _followup_organ(cancer: str) -> str | None:
    chosen = lesion_task_for_cancer(cancer)
    if chosen is None:
        return None
    task = chosen[0]
    if task == "lung_nodules":
        return "lung"
    if task == "liver_lesions":
        return "liver"
    return None


def _is_ct_volume(case) -> bool:
    """A diagnostic CT. PET and scout views are not used to measure a lesion."""
    modality = str(getattr(case, "modality", "") or "").strip().upper()
    if modality and modality != "CT":
        return False
    return _NOT_CT_VOLUME.search(_series_text(case).upper()) is None


def _adequacy_key(case, organ: str | None) -> tuple:
    source = case.source or {}
    indexed = 1 if source.get("seg_used") or source.get("tumor_from_seg") else 0
    return (_coverage_rank(case, organ), _phase_rank(case), indexed, _series_folder(case))


def _coverage_rank(case, organ: str | None) -> int:
    """How well this series shows the organ. 2 is a dedicated chest, 1 covers it."""
    if organ is None:
        return 0
    named = _field_rank(_series_text(case), organ)
    present = _organ_present(case, organ)
    if organ == "lung":
        if named == 2 and present is not False:
            return 2
        if present is True or (named == 1 and present is not False):
            return 1
        return 0
    # An unnamed liver series stays in the pool: HCC phases are often called only "portal".
    if present is False or (present is None and named == 0):
        return 0
    return 1


def _field_rank(text: str, organ: str) -> int | None:
    """2 is a chest CT, 1 a series that covers the torso, 0 a field that misses the organ."""
    folded = text.upper()
    broad = _BROAD_TORSO.search(folded) is not None
    if organ == "lung":
        if broad:
            return 1
        if _LUNG_FIELD.search(folded):
            return 2
        if _LIVER_FIELD.search(folded) or re.search(r"HEAD|BRAIN|PELVIS", folded):
            return 0
        return None
    if broad or _LIVER_FIELD.search(folded):
        return 1
    if _OUTSIDE_LIVER.search(folded):
        return 0
    return None


def _organ_present(case, organ: str) -> bool | None:
    """Whether the segmented organs include this one. None when no table exists."""
    source = case.source or {}
    uid = str(source.get("series_instance_uid") or "")
    if not uid:
        return None
    table = series_result_dir(uid) / "hu.json"
    if not table.is_file():
        return None
    try:
        payload = json.loads(table.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    names = [
        str(row.get("name") or "").lower()
        for row in payload.get("organs") or []
        if isinstance(row, dict)
    ]
    if organ == "lung":
        return any("lung" in name for name in names)
    return any(name == "liver" or name.startswith("liver_") for name in names)


def _phase_rank(case) -> int:
    """Portal venous outranks arterial, then any other contrast series, then a plain series."""
    named = _named_phase(_series_text(case))
    if named in {_PORTAL, _ARTERIAL, _DELAYED, _NONCONTRAST}:
        return named
    measured = _enhancement_rank(case)
    if measured is not None:
        return measured
    if named is not None:
        return named
    return _NONCONTRAST


def _named_phase(text: str) -> int | None:
    folded = text.upper()
    if re.search(r"(^|[^A-Z])PRE([^A-Z]|$)", folded) or "NONCON" in folded or "W/O" in folded or "WITHOUT" in folded:
        return _NONCONTRAST
    if "ARTERIAL" in folded or "LATE ART" in folded or re.search(r"(^|[^A-Z])ART([^A-Z]|$)", folded):
        return _ARTERIAL
    if "PORTAL" in folded or re.search(r"(^|[^A-Z])VENOUS([^A-Z]|$)", folded) or "PVP" in folded:
        return _PORTAL
    if "DELAY" in folded or "EQUILIBRIUM" in folded:
        return _DELAYED
    if "C-A-P" in folded or "PHASE" in folded or "CONTRAST" in folded or "W/C" in folded or _TOKEN_C.search(folded):
        return _CONTRAST
    return None


def _enhancement_rank(case) -> int | None:
    """Classify an unnamed series from the aorta, the portal vein and the liver."""
    source = case.source or {}
    uid = str(source.get("series_instance_uid") or "")
    if not uid:
        return None
    table = series_result_dir(uid) / "hu.json"
    if not table.is_file():
        return None
    try:
        payload = json.loads(table.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    means = {
        str(row.get("name")): row.get("hu_mean")
        for row in payload.get("organs") or []
        if isinstance(row, dict)
    }
    aorta, portal, liver = means.get("aorta"), means.get("portal_vein_and_splenic_vein"), means.get("liver")
    if not all(isinstance(value, (int, float)) for value in (aorta, portal, liver)):
        return None
    return _rank_from_enhancement(float(aorta), float(portal), float(liver))


def _rank_from_enhancement(aorta: float, portal: float, liver: float) -> int:
    if aorta < 90 and portal < 80 and liver < 80:
        return _NONCONTRAST
    if portal >= 120 and portal + 20 >= aorta and liver >= 80:
        return _PORTAL
    if aorta >= 150 and aorta - portal >= 80 and portal < 130:
        return _ARTERIAL
    if aorta >= 120 or portal >= 100:
        return _CONTRAST
    return _NONCONTRAST


def _calendar_day(case) -> str:
    folder = _date_folder(case)
    match = _DATE.search(folder)
    if match:
        return match.group(0)
    return folder


def _series_text(case) -> str:
    source = case.source or {}
    return f"{_series_folder(case)} {source.get('sequence') or ''}"


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
        text += f" {_plural(len(omitted), 'autre série du même jour écartée', 'autres séries du même jour écartées')}."
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
