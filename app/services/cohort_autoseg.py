"""Segment every exam of a cohort on one Kaggle T4, one after another.

A study contributes one CT series: the series cited by the tumor SEG when it
exists, otherwise the contrast series. Masks already on disk are not sent again.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import threading

import pydicom
import SimpleITK as sitk
from sqlalchemy import select

from app.services.exam_autoseg import lesion_task_for_cancer, series_result_dir
from app.services.imaging import read_dicom_series_from_dir
from app.services.storage import DATA_ROOT

# One notebook install, then the exams of that session, one after another.
CHUNK = 8
_lock = threading.Lock()
_jobs: dict[str, dict] = {}


class CohortAutosegError(Exception):
    pass


def exams_in_folder(root: Path, choose) -> list[dict]:
    """One chosen CT series per study folder."""
    exams = []
    patients = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name)
    for patient in patients:
        studies = sorted((path for path in patient.iterdir() if path.is_dir()), key=lambda path: path.name)
        for study in studies:
            try:
                series = choose(study)
            except Exception:
                continue
            if series is None or not series.is_dir():
                continue
            files = sorted(series.glob("*.dcm"))
            if not files:
                continue
            header = pydicom.dcmread(str(files[0]), stop_before_pixels=True, force=True)
            uid = str(getattr(header, "SeriesInstanceUID", "") or "")
            if not uid:
                continue
            name = study.name
            day = name[:10] if len(name) >= 10 and name[4:5] == "-" and name[7:8] == "-" else name
            exams.append({
                "patient_id": patient.name,
                "day": day,
                "series": series,
                "uid": uid,
                "timepoint_id": series.relative_to(root).as_posix(),
            })
    return exams


def cohort_status(project_id: str) -> dict:
    with _lock:
        job = _jobs.get(project_id)
        if job is not None:
            return _public(job)
    saved = _read_status(project_id)
    if saved is None:
        return _public(_blank())
    if saved.get("state") == "running":
        saved["state"] = "error"
        saved["error"] = "Le calcul a été interrompu. Relancez-le : les masques déjà écrits sont repris."
        saved["current"] = []
    return _public(saved)


def start_cohort(project_id: str, user_id: str) -> dict:
    with _lock:
        current = _jobs.get(project_id)
        if current and current.get("state") == "running":
            return _public(current)
        relative, _root, lesion_task = _cohort_context(project_id)
        job = _blank()
        job.update({
            "state": "running", "detail": "Lecture des examens…", "user_id": user_id,
            "relative": relative, "lesion_task": lesion_task,
        })
        _jobs[project_id] = job
        _write_status(project_id, job)
    threading.Thread(target=_worker, args=(project_id,), daemon=True).start()
    return cohort_status(project_id)


def run_job(project_id: str, exams: list[dict], *, lesion_task: str | None, remote, publish, chunk: int = CHUNK, report=None, prepare=None, ready=None) -> dict:
    """Segment exams in groups. `remote` receives one group, `publish` one finished exam."""
    tell = report or (lambda **_fields: None)
    prepare = prepare or (lambda exam: _volume(project_id, exam))
    ready = ready or (lambda exam: _published(project_id, exam["uid"], lesion_task))
    pending = []
    skipped = 0
    for exam in exams:
        if ready(exam):
            skipped += 1
            continue
        pending.append(exam)
    done = failed = 0
    errors: list[str] = []
    tell(total=len(exams), skipped=skipped, done=0, failed=0, detail=f"{len(pending)} examens à calculer, {skipped} déjà prêts.")
    width = max(1, chunk)
    for start in range(0, len(pending), width):
        group = pending[start:start + width]
        labels = [f"{exam['patient_id']} {exam['day']}" for exam in group]
        tell(current=labels, detail="GPU Kaggle, un examen à la fois · " + labels[0])
        prepared = []
        for exam in group:
            try:
                image = prepare(exam)
                prepared.append({**exam, "image": image, "dest": series_result_dir(exam["uid"]), "lesion_task": lesion_task})
            except Exception as error:
                failed += 1
                errors.append(f"{exam['patient_id']} {exam['day']}: {error}")
        if prepared:
            try:
                remote(prepared, lambda detail: tell(detail=detail, current=labels))
            except Exception as error:
                errors.append(str(error))
        for exam in prepared:
            dest = series_result_dir(exam["uid"])
            if not _masks_ready(dest, lesion_task):
                failed += 1
                if not any(exam["uid"] in item for item in errors):
                    errors.append(f"{exam['patient_id']} {exam['day']}: masque absent")
                continue
            try:
                publish(exam)
            except Exception as error:
                failed += 1
                errors.append(f"{exam['patient_id']} {exam['day']}: {error}")
                continue
            done += 1
        tell(done=done, failed=failed, detail=f"{done} terminés · {failed} échecs · {skipped} déjà prêts")
    state = "error" if failed else "done"
    detail = f"{done} examens segmentés, {skipped} déjà prêts, {failed} échecs."
    return {"state": state, "detail": detail, "total": len(exams), "done": done, "skipped": skipped, "failed": failed, "current": [], "error": errors[-1] if errors else ""}


def _worker(project_id: str) -> None:
    from scripts.run_hcc_kaggle_queue import choose_series
    from app.services.kaggle_autoseg import ensure_remote_batch

    try:
        with _lock:
            job = _jobs[project_id]
            relative = job["relative"]
            lesion_task = job["lesion_task"]
            user_id = job["user_id"]
        root = (DATA_ROOT / relative).resolve()
        exams = exams_in_folder(root, choose_series)

        def report(**fields):
            _update(project_id, **fields)

        result = run_job(
            project_id, exams, lesion_task=lesion_task, remote=ensure_remote_batch,
            publish=lambda exam: _publish(project_id, user_id, relative, exam), report=report,
        )
        _update(project_id, state=result["state"], detail=result["detail"], error=result["error"], current=[])
    except Exception as error:
        _update(project_id, state="error", detail="", error=str(error)[:500], current=[])


def _publish(project_id: str, user_id: str, relative: str, exam: dict) -> None:
    from app.oncometra import SessionLocal, WorkspaceCase, WorkspaceUser, create_assignment
    from app.services.exam_autoseg import execute_case
    from app.services.local_dicom_import import ensure_local_case

    case_id = ensure_local_case(project_id, relative, exam["patient_id"], exam["timepoint_id"])
    with SessionLocal() as db:
        case = db.get(WorkspaceCase, case_id)
        user = db.get(WorkspaceUser, user_id)
        if case is None or user is None:
            raise CohortAutosegError("Le cas ou le compte a disparu.")
        assignment = create_assignment(db, case, user)
        study_id = assignment.study_id
    execute_case(case_id, study_id)


def _volume(project_id: str, exam: dict) -> Path:
    cache = DATA_ROOT / "kaggle-queue" / exam["uid"] / "image.nii.gz"
    if cache.is_file():
        return cache
    image = _case_image(project_id, exam["uid"])
    if image is not None:
        return image
    cache.parent.mkdir(parents=True, exist_ok=True)
    volume = read_dicom_series_from_dir(exam["series"])
    sitk.WriteImage(volume, str(cache), True)
    return cache


def _case_image(project_id: str, uid: str) -> Path | None:
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceCase

    with SessionLocal() as db:
        cases = db.scalars(select(WorkspaceCase).where(WorkspaceCase.project_id == project_id))
        for case in cases:
            if str((case.source or {}).get("series_instance_uid") or "") != uid:
                continue
            image = DATA_ROOT / "workspace" / "cases" / case.id / "image.nii.gz"
            if image.is_file():
                return image
    return None


def _published(project_id: str, uid: str, lesion_task: str | None) -> bool:
    if not _masks_ready(series_result_dir(uid), lesion_task):
        return False
    from app.db import SessionLocal
    from app.oncometra_models import WorkspaceCase

    with SessionLocal() as db:
        cases = db.scalars(select(WorkspaceCase).where(WorkspaceCase.project_id == project_id))
        for case in cases:
            if str((case.source or {}).get("series_instance_uid") or "") != uid:
                continue
            return (DATA_ROOT / "workspace" / "cases" / case.id / "organs.json").is_file()
    return False


def _masks_ready(dest: Path, lesion_task: str | None) -> bool:
    if not (dest / "organs.nii.gz").is_file():
        return False
    if lesion_task and not (dest / "lesions.nii.gz").is_file():
        return False
    return True


def _cohort_context(project_id: str) -> tuple[str, Path, str | None]:
    from app.db import SessionLocal
    from app.oncometra_models import CatalogDataset, ProjectDataset, WorkspaceCase, WorkspaceProject

    with SessionLocal() as db:
        project = db.get(WorkspaceProject, project_id)
        if project is None:
            raise CohortAutosegError("Cohorte introuvable.")
        if project.modality != "CT":
            raise CohortAutosegError("AI segmentation couvre les cohortes CT. TotalSegmentator ne segmente pas cette modalité ici.")
        link = db.scalar(select(ProjectDataset).where(ProjectDataset.project_id == project_id))
        dataset = db.get(CatalogDataset, link.dataset_id) if link else None
        raw = (dataset.dicom_path if dataset else "") or ""
        if not raw:
            counts: Counter[str] = Counter()
            for case in db.scalars(select(WorkspaceCase).where(WorkspaceCase.project_id == project_id)):
                path = str((case.source or {}).get("local_path") or "")
                if path:
                    counts[path] += 1
            raw = counts.most_common(1)[0][0] if counts else ""
        chosen = lesion_task_for_cancer(project.cancer_origin or project.name)
    if not raw:
        raise CohortAutosegError("Cette cohorte n’a pas de dossier DICOM. Importez un examen ou renseignez le dossier du dataset.")
    root = _data_folder(raw)
    return root.relative_to(DATA_ROOT.resolve()).as_posix(), root, chosen[0] if chosen else None


def _data_folder(raw: str) -> Path:
    text = raw.strip().replace("\\", "/")
    root = DATA_ROOT.resolve()
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / text.lstrip("/")
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root) or not candidate.is_dir() or candidate == root:
        raise CohortAutosegError("Le dossier DICOM de la cohorte est introuvable dans data.")
    return candidate


def _blank() -> dict:
    return {
        "state": "idle", "detail": "", "error": "", "total": 0, "done": 0, "skipped": 0,
        "failed": 0, "current": [], "user_id": "", "relative": "", "lesion_task": None,
    }


def _public(job: dict) -> dict:
    return {key: job.get(key) for key in ("state", "detail", "error", "total", "done", "skipped", "failed", "current")}


def _update(project_id: str, **fields) -> None:
    with _lock:
        job = _jobs.setdefault(project_id, _blank())
        job.update(fields)
        _write_status(project_id, job)


def _status_path(project_id: str) -> Path:
    safe = "".join(character for character in project_id if character.isalnum() or character in "-_")
    return DATA_ROOT / "kaggle-gpu" / "cohort-status" / f"{safe or 'cohort'}.json"


def _write_status(project_id: str, job: dict) -> None:
    path = _status_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_public(job), ensure_ascii=False), encoding="utf-8")


def _read_status(project_id: str) -> dict | None:
    path = _status_path(project_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
