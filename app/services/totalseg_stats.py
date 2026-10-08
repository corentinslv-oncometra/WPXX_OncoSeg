"""TotalSegmentator organ and lesion stats, adapted from OncoRadar.

The patient index stays in the synced catalog. This job only reads the local
DICOM folder already recorded on the dataset and writes a separate result table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import sys
import shutil
import subprocess
import threading

import SimpleITK as sitk
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal
from app.oncometra_models import CatalogDataset, CatalogPatientIndex
from app.services.storage import DATA_ROOT

ORGAN_VOLUME_MM3 = 1_000
LESION_VOLUME_MM3 = 1
_SKIP_DESC = ("scout", "localizer", "topogram", "gated")
_CT = {"CT", "CTPT"}
_SKIP_MOD = {"RTSTRUCT", "SEG", "SR", "PR", "RTPLAN", "RTDOSE", "KO", "DOC"}
_LUNG_TASK = "lung_nodules"
_LIVER_TASK = "liver_lesions"
_KIDNEY_TASK = "kidney_cysts"
_TASK_SITE = {_LUNG_TASK: "LUNG", _LIVER_TASK: "LIVER", _KIDNEY_TASK: "KIDNEY"}
_PROCESS_LOCK = threading.Lock()
_PROCESS: subprocess.Popen | None = None


class TotalsegError(Exception):
    pass


@dataclass
class SeriesRef:
    patient_id: str
    study_date: str
    series_uid: str
    modality: str
    description: str
    files: list[Path] = field(default_factory=list)

    @property
    def n_files(self) -> int:
        return len(self.files)


def installed() -> bool:
    try:
        _binary()
    except TotalsegError:
        return False
    return True


def ready(dataset: CatalogDataset) -> bool:
    path = Path(dataset.dicom_path) if dataset.dicom_path else None
    return bool(dataset.indexed_patients and path and path.is_dir())


def lesion_tasks_for(organs: list[str], tumor_hint: str = "") -> list[str]:
    names = {str(name).lower() for name in organs if str(name).strip()}
    found: list[str] = []
    if any("lung" in name and "vessel" not in name for name in names):
        found.append(_LUNG_TASK)
    if any(name == "liver" or name.startswith("liver_") for name in names):
        found.append(_LIVER_TASK)
    if any(name.startswith("kidney") and "cyst" not in name for name in names):
        found.append(_KIDNEY_TASK)
    hint = tumor_hint.lower()
    if "lung" in hint or "pulm" in hint:
        return [task for task in found if task == _LUNG_TASK]
    if "liver" in hint or "hepat" in hint:
        return [task for task in found if task == _LIVER_TASK]
    if "kidney" in hint or "renal" in hint:
        return [task for task in found if task == _KIDNEY_TASK]
    return found


def organs_present(stats: dict, *, min_volume: float = ORGAN_VOLUME_MM3) -> list[str]:
    names = []
    for raw_name, payload in (stats or {}).items():
        volume = _volume_mm3(payload)
        if volume is None or volume < min_volume:
            continue
        names.append(str(raw_name))
    return names


def compact_organs(names: list[str]) -> str:
    seen = []
    for name in names:
        label = _major_organ(name)
        if label and label not in seen:
            seen.append(label)
    return ", ".join(seen)


def format_volume(mm3: float) -> str:
    if mm3 >= 1000:
        return f"{mm3 / 1000:.1f} cm³"
    return f"{mm3:.0f} mm³"


def lesion_line(item: dict) -> str:
    size = str(item.get("size") or "").strip()
    site = str(item.get("site") or "").strip()
    if size and site:
        return f"{site} · {size}"
    return size or site


def pick_series(candidates: list[SeriesRef]) -> SeriesRef | None:
    usable = [item for item in candidates if item.n_files >= 8 and item.modality in _CT and not _is_skip_desc(item.description)]
    pool = usable or [item for item in candidates if item.n_files >= 8 and item.modality in _CT]
    if not pool:
        return None
    pool.sort(key=lambda item: item.n_files, reverse=True)
    return pool[0]


def timepoint(value: str) -> str:
    text = (value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8 and digits[:8].isdigit():
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return text[:64]


def group_series(root: Path, should_stop=None) -> dict[str, dict[str, list[SeriesRef]]]:
    grouped: dict[tuple[str, str, str], SeriesRef] = {}
    for index, path in enumerate(_dicom_files(root)):
        if should_stop and index % 100 == 0 and should_stop():
            break
        meta = _read_meta(path)
        if meta is None:
            continue
        patient_id, stamp, uid, modality, description = meta
        if not patient_id or not stamp or not uid or modality in _SKIP_MOD:
            continue
        key = (patient_id, stamp, uid)
        item = grouped.get(key)
        if item is None:
            item = SeriesRef(patient_id, stamp, uid, modality, description)
            grouped[key] = item
        item.files.append(path)
    by_patient: dict[str, dict[str, list[SeriesRef]]] = {}
    for item in grouped.values():
        by_patient.setdefault(item.patient_id, {}).setdefault(item.study_date, []).append(item)
    return by_patient


def stop_running() -> None:
    global _PROCESS
    with _PROCESS_LOCK:
        process = _PROCESS
    if process is not None and process.poll() is None:
        process.kill()
    names = ("TotalSegmentator.exe", "totalsegmentator.exe", "TotalSegmentator", "totalsegmentator")
    if os.name == "nt":
        for name in names:
            subprocess.run(["taskkill", "/IM", name, "/F"], capture_output=True, text=True)


def execute(dataset_id: str, *, run_task=None, series_tree=None) -> dict:
    runner = run_task or run_totalseg_task
    with SessionLocal() as db:
        dataset = db.get(CatalogDataset, dataset_id)
        if dataset is None:
            raise TotalsegError("Dataset not found")
        if series_tree is None and not ready(dataset):
            raise TotalsegError("Set a local DICOM folder on an indexed dataset before running TotalSegmentator.")
        folder = Path(dataset.dicom_path) if dataset.dicom_path else None
        tumor_hint = dataset.tumor_detail or ""
        dataset.totalseg_status = "running"
        dataset.totalseg_error = ""
        dataset.totalseg_detail = "Scanning local DICOM folder…"
        db.commit()
        patients = list(db.scalars(select(CatalogPatientIndex).where(CatalogPatientIndex.dataset_id == dataset_id)
                                   .order_by(CatalogPatientIndex.source_id)))

    def stopped() -> bool:
        with SessionLocal() as db:
            current = db.get(CatalogDataset, dataset_id)
            return current is None or current.totalseg_status != "running"

    scanned = ran = skipped = errors = 0
    last_error = ""
    cache = DATA_ROOT / "totalseg" / dataset_id
    try:
        tree = series_tree if series_tree is not None else group_series(folder, should_stop=stopped)
        normalized = {}
        for patient_id, visits in tree.items():
            for stamp, series in visits.items():
                normalized.setdefault(patient_id, {}).setdefault(timepoint(stamp), []).extend(series)
        for position, patient in enumerate(patients, start=1):
            if stopped():
                _detail(dataset_id, "Stopped.")
                return {"scanned": scanned, "ran": ran, "skipped": skipped, "errors": errors}
            _detail(dataset_id, f"{patient.source_id} · {position}/{len(patients)} patients · {ran} visits measured · {skipped} skipped · {errors} errors")
            incoming = []
            by_date = normalized.get(patient.source_id) or {}
            for stamp in [timepoint(str(item)) for item in (patient.study_dates or []) if str(item).strip()]:
                scanned += 1
                chosen = pick_series(by_date.get(stamp) or [])
                if chosen is None:
                    skipped += 1
                    continue
                try:
                    observation = _run_visit(runner, cache, chosen, tumor_hint=tumor_hint)
                except TotalsegError as exc:
                    if "not installed" in str(exc).lower() or "not on path" in str(exc).lower():
                        raise
                    errors += 1
                    last_error = str(exc)[:180]
                    continue
                except Exception as exc:
                    errors += 1
                    last_error = str(exc)[:180]
                    continue
                if observation is None:
                    skipped += 1
                    continue
                incoming.append(observation)
                ran += 1
            if incoming:
                _store_visits(patient.id, incoming)
            if last_error:
                _detail(dataset_id, f"{patient.source_id} · {position}/{len(patients)} · last: {last_error}")
        if not stopped():
            with SessionLocal() as db:
                dataset = db.get(CatalogDataset, dataset_id)
                dataset.totalseg_status = "done"
                dataset.totalseg_error = ""
                dataset.totalseg_at = datetime.utcnow()
                dataset.totalseg_detail = f"{ran} visits measured · {skipped} skipped · {errors} errors"
                if not scanned:
                    dataset.totalseg_detail = "No indexed visits to measure."
                db.commit()
        return {"scanned": scanned, "ran": ran, "skipped": skipped, "errors": errors}
    except Exception as exc:
        with SessionLocal() as db:
            dataset = db.get(CatalogDataset, dataset_id)
            if dataset is not None and dataset.totalseg_status == "running":
                dataset.totalseg_status = "error"
                dataset.totalseg_error = str(exc)[:300]
                dataset.totalseg_detail = ""
                db.commit()
        raise


def run_totalseg_task(task: str, series_dir: Path, out_dir: Path) -> dict:
    global _PROCESS
    existing = out_dir / "statistics.json"
    if existing.is_file():
        return _read_stats(existing)
    binary = _binary()
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [binary, "-i", str(series_dir), "-o", str(out_dir / "segmentations.nii.gz"),
               "-ta", task, "--ml", "--statistics", "--device", _device()]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    with _PROCESS_LOCK:
        _PROCESS = process
    try:
        stdout, stderr = process.communicate(timeout=3_600)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise TotalsegError(f"TotalSegmentator timed out on task {task}.") from exc
    finally:
        with _PROCESS_LOCK:
            if _PROCESS is process:
                _PROCESS = None
    if process.returncode:
        err = (stderr or stdout or "TotalSegmentator failed").strip()[:240]
        raise TotalsegError(f"TotalSegmentator failed ({task}): {err}")
    if not existing.is_file():
        raise TotalsegError(f"TotalSegmentator produced no statistics.json for {task}.")
    return _read_stats(existing)


def _run_visit(runner, cache: Path, series: SeriesRef, *, tumor_hint: str) -> dict | None:
    series_dir = _materialize(series, cache / "series" / series.series_uid)
    total_stats = runner("total", series_dir, cache / series.series_uid / "total")
    present = organs_present(total_stats)
    tasks = lesion_tasks_for(present, tumor_hint)
    site = size = used = ""
    quote = [f"task=total organs={compact_organs(present) or 'none'}"]
    for task in tasks:
        lesion_stats = runner(task, series_dir, cache / series.series_uid / task)
        volume = _task_volume(lesion_stats, task)
        if volume is None or volume < LESION_VOLUME_MM3:
            continue
        site = _TASK_SITE.get(task, task)
        size = format_volume(volume)
        used = task
        quote.append(f"task={task} volume={volume:.1f} mm3")
        break
    if not series.study_date:
        return None
    return {"timepoint": series.study_date, "organs": compact_organs(present), "site": site, "size": size,
            "lesion_task": used, "source": "totalseg", "quote": " · ".join(quote),
            "series_uid": series.series_uid, "organ_stats": _compact_stats(total_stats)}


def _store_visits(patient_id: str, incoming: list[dict]) -> None:
    with SessionLocal() as db:
        patient = db.get(CatalogPatientIndex, patient_id)
        if patient is None:
            return
        by_date = {}
        for item in patient.totalseg or []:
            if isinstance(item, dict) and item.get("timepoint"):
                by_date[timepoint(str(item["timepoint"]))] = item
        for item in incoming:
            by_date[timepoint(str(item.get("timepoint") or ""))] = item
        patient.totalseg = [by_date[key] for key in sorted(by_date) if key]
        flag_modified(patient, "totalseg")
        db.commit()


def _detail(dataset_id: str, text: str) -> None:
    with SessionLocal() as db:
        dataset = db.get(CatalogDataset, dataset_id)
        if dataset is not None and dataset.totalseg_status == "running":
            dataset.totalseg_detail = text[:500]
            db.commit()


def _materialize(series: SeriesRef, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        return dest
    for index, src in enumerate(series.files):
        if not src.is_file():
            continue
        suffix = src.suffix if src.suffix else ".dcm"
        shutil.copy2(src, dest / f"{index:05d}{suffix}")
    return dest


def _binary() -> str:
    for name in ("TotalSegmentator", "totalsegmentator"):
        found = shutil.which(name)
        if found:
            return found
    names = ("TotalSegmentator.exe", "TotalSegmentator.cmd", "totalsegmentator.exe", "totalsegmentator.cmd")
    folders = (Path(sys.executable).resolve().parent, Path(sys.executable).resolve().parent / "Scripts")
    for folder in folders:
        for name in names:
            path = folder / name
            if path.is_file():
                return str(path)
    raise TotalsegError("TotalSegmentator is not installed or not on PATH.")


def _device() -> str:
    forced = (os.environ.get("ONCOMETRA_TOTALSEG_DEVICE") or os.environ.get("ONCORADAR_TOTALSEG_DEVICE") or "").strip().lower()
    if forced in {"cpu", "gpu", "mps"}:
        return forced
    if shutil.which("nvidia-smi"):
        return "gpu"
    return "cpu"


def _major_organ(name: str) -> str:
    folded = name.lower()
    for label, needles in (
        ("lung", ("lung",)), ("liver", ("liver",)), ("kidney", ("kidney",)), ("spleen", ("spleen",)),
        ("pancreas", ("pancreas",)), ("brain", ("brain",)), ("heart", ("heart",)),
        ("colon", ("colon",)), ("prostate", ("prostate",)),
    ):
        if any(needle in folded for needle in needles):
            return label
    return ""


def _volume_mm3(payload) -> float | None:
    raw = payload.get("volume", payload.get("volume_mm3")) if isinstance(payload, dict) else payload
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _task_volume(stats: dict, task: str) -> float | None:
    keys = {
        _LUNG_TASK: ("lung_nodules", "lung_nodule", "nodule", "nodules"),
        _LIVER_TASK: ("liver_lesions", "liver_lesion", "liver_tumor", "liver_tumors"),
        _KIDNEY_TASK: ("kidney_cyst_left", "kidney_cyst_right", "kidney_cysts", "kidney_cyst"),
    }.get(task, (task,))
    organs = {"liver", "lung", "kidney", "kidney_left", "kidney_right", "spleen", "pancreas"}
    best = None
    for name, payload in (stats or {}).items():
        folded = str(name).lower()
        if folded in organs or not any(key == folded or key in folded for key in keys):
            continue
        volume = _volume_mm3(payload)
        if volume is not None and (best is None or volume > best):
            best = volume
    return best


def _compact_stats(stats: dict) -> list[dict]:
    rows = []
    for raw_name, payload in (stats or {}).items():
        volume = _volume_mm3(payload)
        if volume is None or volume < 100:
            continue
        name = str(raw_name)
        rows.append({"name": name, "label": name.replace("_", " "), "volume_mm3": volume, "volume": format_volume(volume)})
    rows.sort(key=lambda item: item["label"].lower())
    return rows


def _read_stats(path: Path) -> dict:
    import json
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _is_skip_desc(description: str) -> bool:
    folded = description.lower()
    return any(token in folded for token in _SKIP_DESC)


def _dicom_files(root: Path) -> list[Path]:
    skipped = {".nii", ".gz", ".json", ".txt", ".csv", ".png", ".jpg", ".jpeg", ".html", ".xml", ".zip", ".py", ".md"}
    return [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() not in skipped]


def _read_meta(path: Path):
    reader = sitk.ImageFileReader()
    reader.SetFileName(str(path))
    try:
        reader.ReadImageInformation()
    except Exception:
        return None

    def tag(code: str) -> str:
        return reader.GetMetaData(code).strip() if reader.HasMetaDataKey(code) else ""

    patient = tag("0010|0020")
    stamp = timepoint(tag("0008|0020"))
    uid = tag("0020|000e")
    modality = tag("0008|0060").upper()
    description = tag("0008|103e")
    if not patient or not uid:
        return None
    return patient, stamp, uid, modality, description
