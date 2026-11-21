"""Send one exam to a private Kaggle GPU notebook and bring the masks back.

The API token stays in the user profile (~/.kaggle/access_token) or in
KAGGLE_API_TOKEN. This module never writes it into the repository or a dataset.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import uuid

from app.services.storage import DATA_ROOT

logger = logging.getLogger(__name__)

DATASET_SLUG = "oncometra-exam"
KERNEL_SLUG = "oncometra-totalseg"
PACKAGE = "TotalSegmentator==2.18.0"
ACCELERATOR = "NvidiaTeslaT4"
# CPU images live in kaggle-images; the T4 image is published under kaggle-private-byod.
DOCKER_IMAGE = (
    "gcr.io/kaggle-private-byod/python@sha256:"
    "de153e6d303881930c51286216393d56f56b26458d0661350305a1e8144eea01"
)
KERNEL_SCRIPT = Path(__file__).resolve().parent / "kaggle_kernel" / "run.py"
_TOKEN_RE = re.compile(r"KGAT_[0-9a-fA-F]+")
_remote_lock = threading.Lock()
_session_lock = threading.Lock()
_session_id: int | None = None
_cancel_unsupported = False


class RemoteCancelled(RuntimeError):
    """The reader stopped the Kaggle job before it finished."""


def token_path() -> Path:
    return Path.home() / ".kaggle" / "access_token"


def prefer_remote_gpu() -> None:
    """Send Détecter to a Kaggle GPU unless a device was chosen before startup."""
    os.environ.setdefault("ONCOMETRA_TOTALSEG_DEVICE", "kaggle")


def stage_exam(root: Path, username: str, image: Path, uid: str, lesion_task: str | None, *,
               organs: bool, lesions: bool) -> tuple[Path, Path]:
    """Write the private dataset and the kernel folder. Returns both directories."""
    _check_uid(uid)
    _check_username(username)
    dataset = root / "dataset"
    kernel = root / "kernel"
    dataset.mkdir(parents=True, exist_ok=True)
    kernel.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image, dataset / "image.nii.gz")
    job = {"package": PACKAGE, "exams": [{
        "file": "image.nii.gz", "uid": uid, "organs": organs,
        "lesions": lesions, "lesion_task": lesion_task,
    }]}
    _write_json(dataset / "job.json", job)
    _write_json(dataset / "dataset-metadata.json", {
        "title": "Oncometra exam",
        "id": f"{username}/{DATASET_SLUG}",
        "licenses": [{"name": "other"}],
        "description": "Private Oncometra exam volume. Not for redistribution.",
    })
    shutil.copy2(KERNEL_SCRIPT, kernel / "run.py")
    _write_json(kernel / "kernel-metadata.json", {
        "id": f"{username}/{KERNEL_SLUG}",
        "title": "Oncometra totalseg",
        "code_file": "run.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "machine_shape": ACCELERATOR,
        "docker_image": DOCKER_IMAGE,
        "dataset_sources": [f"{username}/{DATASET_SLUG}"],
    })
    return dataset, kernel


def stage_exams(root: Path, username: str, exams: list[dict]) -> tuple[Path, Path]:
    """Stage several volumes for one GPU session. The notebook runs them one after another."""
    if not exams:
        raise RuntimeError("Aucun examen à envoyer.")
    _check_username(username)
    dataset = root / "dataset"
    kernel = root / "kernel"
    dataset.mkdir(parents=True, exist_ok=True)
    kernel.mkdir(parents=True, exist_ok=True)
    payload = []
    for exam in exams:
        uid = str(exam["uid"])
        _check_uid(uid)
        name = f"{uid}.nii.gz"
        shutil.copy2(exam["image"], dataset / name)
        payload.append({
            "file": name, "uid": uid, "organs": bool(exam.get("organs", True)),
            "lesions": bool(exam.get("lesions")), "lesion_task": exam.get("lesion_task"),
        })
    _write_json(dataset / "job.json", {"package": PACKAGE, "exams": payload})
    _write_json(dataset / "dataset-metadata.json", {
        "title": "Oncometra exam",
        "id": f"{username}/{DATASET_SLUG}",
        "licenses": [{"name": "other"}],
        "description": "Private Oncometra exam volume. Not for redistribution.",
    })
    shutil.copy2(KERNEL_SCRIPT, kernel / "run.py")
    _write_json(kernel / "kernel-metadata.json", {
        "id": f"{username}/{KERNEL_SLUG}",
        "title": "Oncometra totalseg",
        "code_file": "run.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "machine_shape": ACCELERATOR,
        "docker_image": DOCKER_IMAGE,
        "dataset_sources": [f"{username}/{DATASET_SLUG}"],
    })
    return dataset, kernel


def place_outputs(download_root: Path, uid: str, dest: Path, *, need_organs: bool, need_lesions: bool) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    wanted = []
    if need_organs:
        wanted.append("organs.nii.gz")
    if need_lesions:
        wanted.append("lesions.nii.gz")
    missing = []
    for name in wanted:
        source = _find_output(download_root, uid, name)
        if source is None:
            missing.append(name)
            continue
        target = dest / name
        if not target.is_file():
            shutil.copy2(source, target)
    if missing:
        raise RuntimeError("Le notebook GPU n’a pas produit : " + ", ".join(missing))
    gpu_log = _find_log(download_root)
    if gpu_log is not None and not (dest / "nvidia-smi.csv").is_file():
        shutil.copy2(gpu_log, dest / "nvidia-smi.csv")


def ensure_remote_masks(image: Path, uid: str, lesion_task: str | None, dest: Path, report=None, stop=None) -> None:
    """Run the missing organ and lesion tasks on Kaggle, then copy the NIfTI masks."""
    from app.services.exam_autoseg import discard_foreign_mask
    discard_foreign_mask(image, dest / "organs.nii.gz")
    discard_foreign_mask(image, dest / "lesions.nii.gz")
    need_organs = not (dest / "organs.nii.gz").is_file()
    need_lesions = bool(lesion_task) and not (dest / "lesions.nii.gz").is_file()
    if not need_organs and not need_lesions:
        return
    if not image.is_file():
        raise RuntimeError("Le volume de cet examen est introuvable.")
    tell = report or (lambda _detail: None)
    with _remote_lock:
        root = DATA_ROOT / "kaggle-staging" / uuid.uuid4().hex
        download = root / "output"
        try:
            tell("Préparation du volume pour Kaggle…")
            api = _client()
            username = str(api.config_values["username"])
            dataset, kernel = stage_exam(root, username, image, uid, lesion_task, organs=need_organs, lesions=need_lesions)
            ref = f"{username}/{DATASET_SLUG}"
            tell("Envoi du volume vers un dataset privé…")
            _publish_dataset(api, dataset, ref, stop)
            source = f"{ref}/{_dataset_version(api, ref)}"
            metadata = json.loads((kernel / "kernel-metadata.json").read_text(encoding="utf-8"))
            metadata["dataset_sources"] = [source]
            _write_json(kernel / "kernel-metadata.json", metadata)
            tell("Démarrage du notebook GPU…")
            kernel_ref = f"{username}/{KERNEL_SLUG}"
            _push_kernel(api, kernel, kernel_ref, source, stop)
            _wait_kernel(api, kernel_ref, tell, stop)
            _raise_if_stopped(stop)
            tell("Récupération des masques…")
            download.mkdir(parents=True, exist_ok=True)
            api.kernels_output(kernel_ref, str(download), force=True, quiet=True)
            place_outputs(download, uid, dest, need_organs=need_organs, need_lesions=need_lesions)
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"Le GPU Kaggle n’a pas terminé la détection : {_redact(error)}") from error
        finally:
            shutil.rmtree(root, ignore_errors=True)


def ensure_remote_batch(exams: list[dict], report=None) -> None:
    """Run several exams on one Kaggle T4, one after another."""
    pending = []
    from app.services.exam_autoseg import discard_foreign_mask
    for exam in exams:
        dest = Path(exam["dest"])
        image = Path(exam["image"])
        discard_foreign_mask(image, dest / "organs.nii.gz")
        discard_foreign_mask(image, dest / "lesions.nii.gz")
        lesion_task = exam.get("lesion_task")
        need_organs = not (dest / "organs.nii.gz").is_file()
        need_lesions = bool(lesion_task) and not (dest / "lesions.nii.gz").is_file()
        if not need_organs and not need_lesions:
            continue
        if not image.is_file():
            raise RuntimeError(f"Le volume de {exam.get('uid')} est introuvable.")
        pending.append({**exam, "image": image, "dest": dest, "organs": need_organs, "lesions": need_lesions})
    if not pending:
        return
    tell = report or (lambda _detail: None)
    with _remote_lock:
        root = DATA_ROOT / "kaggle-staging" / uuid.uuid4().hex
        download = root / "output"
        try:
            tell(f"Préparation de {len(pending)} volumes pour Kaggle…")
            api = _client()
            username = str(api.config_values["username"])
            dataset, kernel = stage_exams(root, username, pending)
            ref = f"{username}/{DATASET_SLUG}"
            tell("Envoi des volumes vers un dataset privé…")
            _publish_dataset(api, dataset, ref)
            source = f"{ref}/{_dataset_version(api, ref)}"
            metadata = json.loads((kernel / "kernel-metadata.json").read_text(encoding="utf-8"))
            metadata["dataset_sources"] = [source]
            _write_json(kernel / "kernel-metadata.json", metadata)
            tell("Démarrage du notebook GPU…")
            kernel_ref = f"{username}/{KERNEL_SLUG}"
            _push_kernel(api, kernel, kernel_ref, source)
            kernel_error = ""
            try:
                _wait_kernel(api, kernel_ref, tell)
            except RuntimeError as error:
                kernel_error = str(error)
            tell("Récupération des masques…")
            download.mkdir(parents=True, exist_ok=True)
            try:
                api.kernels_output(kernel_ref, str(download), force=True, quiet=True)
            except Exception as error:
                if kernel_error:
                    raise RuntimeError(kernel_error) from error
                raise
            problems = []
            for exam in pending:
                try:
                    place_outputs(download, str(exam["uid"]), exam["dest"],
                                  need_organs=exam["organs"], need_lesions=exam["lesions"])
                except RuntimeError as error:
                    problems.append(str(error))
            if problems:
                detail = " ; ".join(problems)
                if kernel_error:
                    detail = f"{detail} ({kernel_error})"
                raise RuntimeError(detail)
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"Le GPU Kaggle n’a pas terminé la détection : {_redact(error)}") from error
        finally:
            shutil.rmtree(root, ignore_errors=True)


def _client():
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as error:
        raise RuntimeError("Le client Kaggle n’est pas installé dans l’environnement de l’application.") from error
    api = KaggleApi()
    api.authenticate()
    username = api.config_values.get("username")
    if not username:
        raise RuntimeError("Kaggle n’a pas reconnu le jeton. Régénère-le dans les réglages du compte.")
    return api


def _publish_dataset(api, folder: Path, ref: str, stop=None) -> None:
    try:
        if _dataset_exists(api, ref):
            api.dataset_create_version(str(folder), "Refresh the exam volume", quiet=True,
                                       convert_to_csv=False, delete_old_versions=False)
        else:
            api.dataset_create_new(str(folder), public=False, quiet=True, convert_to_csv=False)
    except Exception as error:
        if _dataset_exists(api, ref) and _already_exists(error):
            api.dataset_create_version(str(folder), "Refresh the exam volume", quiet=True,
                                       convert_to_csv=False, delete_old_versions=False)
        else:
            raise
    _wait_dataset(api, ref, stop)


def _dataset_exists(api, ref: str) -> bool:
    try:
        api.dataset_status(ref)
        return True
    except Exception as error:
        text = str(error).lower()
        response = getattr(error, "response", None)
        body = str(getattr(response, "text", "") or "").lower()
        code = getattr(response, "status_code", None)
        # A missing private dataset is reported as a datasets.get denial, not a 404.
        if code in {403, 404} or "not found" in text or "does not exist" in text or "datasets.get" in body:
            return False
        raise


def _wait_dataset(api, ref: str, stop=None) -> None:
    deadline = time.time() + 30 * 60
    while True:
        _raise_if_stopped(stop)
        status = str(api.dataset_status(ref)).lower()
        if "error" in status or "fail" in status:
            raise RuntimeError(f"Kaggle n’a pas accepté le volume ({_redact(status)}).")
        if "ready" in status and _dataset_has_job(api, ref):
            return
        if time.time() > deadline:
            raise RuntimeError("Kaggle n’a pas fini de préparer le volume.")
        _pause(stop, 10)


def _dataset_version(api, ref: str) -> str:
    payload = json.loads(api.dataset_status(ref, format="json"))
    number = payload.get("current_version_number")
    if not number:
        raise RuntimeError("Kaggle n’a pas indiqué la version du volume.")
    return str(number)


def _dataset_has_job(api, ref: str) -> bool:
    try:
        listing = api.dataset_list_files(ref)
    except Exception:
        return False
    files = getattr(listing, "files", None) or []
    return any(getattr(item, "name", "") == "job.json" for item in files)


def _push_kernel(api, folder: Path, kernel_ref: str, dataset_ref: str, stop=None) -> None:
    """Save, prove the new version kept the dataset, then start that notebook.

    A push made the instant a new dataset version becomes ready is stored with
    an empty source and runs against a blank /kaggle/input. The previous
    version can still show the dataset, so the check has to name the version
    that was just saved.
    """
    last = "source absente"
    for attempt in range(4):
        saved = api.kernels_push(str(folder), no_run=True)
        invalid = _invalid_sources(saved)
        if invalid:
            last = ", ".join(invalid)
        elif not _version_has_dataset(api, kernel_ref, saved, dataset_ref):
            last = "source absente après l’enregistrement"
        else:
            running = api.kernels_push(str(folder))
            invalid = _invalid_sources(running)
            if invalid:
                last = ", ".join(invalid)
            elif _version_has_dataset(api, kernel_ref, running, dataset_ref):
                _remember_session(getattr(running, "version_number", None) or getattr(running, "versionNumber", None))
                return
            else:
                last = "source absente au démarrage"
        if attempt < 3:
            _pause(stop, 20)
    raise RuntimeError(f"Kaggle n’a pas attaché le volume privé ({_redact(last)}).")


def _invalid_sources(result) -> list[str]:
    return [str(item) for item in (getattr(result, "invalidDatasetSources", None) or []) if str(item).strip()]


def _version_has_dataset(api, kernel_ref: str, result, dataset_ref: str) -> bool:
    version = getattr(result, "versionNumber", None) or getattr(result, "version_number", None)
    ref = f"{kernel_ref}/{version}" if version else kernel_ref
    sources = _saved_dataset_sources(api, ref)
    slug = "/".join(dataset_ref.split("/")[:2])
    return dataset_ref in sources or slug in sources


def _saved_dataset_sources(api, ref: str) -> list[str]:
    folder = Path(tempfile.mkdtemp(prefix="kaggle-kernel-"))
    try:
        api.kernels_pull(ref, str(folder), metadata=True, quiet=True)
        meta = json.loads((folder / "kernel-metadata.json").read_text(encoding="utf-8"))
        return [str(item) for item in (meta.get("dataset_sources") or []) if str(item).strip()]
    except Exception:
        return []
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _wait_kernel(api, ref: str, tell, stop=None) -> None:
    deadline = time.time() + _kernel_timeout()
    while True:
        _raise_if_stopped(stop)
        state, detail = _kernel_state(api.kernels_status(ref))
        tell(f"GPU Kaggle : {detail or state}")
        if state == "complete":
            return
        if state == "error":
            raise RuntimeError(_kernel_failure(api, ref, detail))
        if time.time() > deadline:
            raise RuntimeError("Le notebook GPU a dépassé le temps prévu.")
        _pause(stop, 20)


def cancel_remote_session() -> None:
    """Ask Kaggle to drop the notebook this detection started.

    A missing id is ignored. An API token without kernelSessions.cancel is remembered
    so later clicks do not repeat the same refusal.
    """
    global _cancel_unsupported
    if _cancel_unsupported:
        return
    session_id = _current_session_id()
    if not session_id:
        return
    api = _client()
    from kagglesdk.kernels.types.kernels_api_service import ApiCancelKernelSessionRequest
    request = ApiCancelKernelSessionRequest()
    request.kernel_session_id = int(session_id)
    try:
        with api.build_kaggle_client() as client:
            response = client.kernels.kernels_api_client.cancel_kernel_session(request)
    except Exception as error:
        if _cancel_permission_denied(error):
            _cancel_unsupported = True
            logger.warning("Kaggle refused to cancel the notebook: this token lacks kernelSessions.cancel. The local wait is stopped.")
            return
        raise
    message = str(getattr(response, "error_message", "") or getattr(response, "errorMessage", "") or "").strip()
    if message:
        raise RuntimeError(_redact(message))


def _cancel_permission_denied(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if getattr(response, "status_code", None) != 403:
        return False
    body = str(getattr(response, "text", "") or error)
    return "kernelSessions.cancel" in body or "PERMISSION_DENIED" in body


def _remember_session(version) -> None:
    global _session_id
    try:
        number = int(version)
    except (TypeError, ValueError):
        return
    if number <= 0:
        return
    with _session_lock:
        _session_id = number


def _current_session_id() -> int | None:
    with _session_lock:
        if _session_id:
            return _session_id
    try:
        api = _client()
        username = str(api.config_values["username"])
        with api.build_kaggle_client() as client:
            response = client.http_client()._session.get(
                "https://www.kaggle.com/api/v1/kernels/pull",
                params={"userName": username, "kernelSlug": KERNEL_SLUG},
                timeout=30,
            )
            response.raise_for_status()
            number = (response.json().get("metadata") or {}).get("currentVersionNumber")
        _remember_session(number)
    except Exception:
        logger.exception("Kaggle session id was not available")
        return None
    with _session_lock:
        return _session_id


def _raise_if_stopped(stop) -> None:
    if stop is not None and stop.is_set():
        raise RemoteCancelled("Détection annulée.")


def _pause(stop, seconds: float) -> None:
    if stop is None:
        time.sleep(seconds)
        return
    if stop.wait(seconds):
        raise RemoteCancelled("Détection annulée.")


def _kernel_failure(api, ref: str, detail: str) -> str:
    excerpt = _kernel_log_excerpt(api, ref)
    if excerpt:
        return excerpt
    return detail or "Le notebook GPU s’est arrêté en erreur."


def _kernel_log_excerpt(api, ref: str) -> str:
    folder = DATA_ROOT / "kaggle-gpu" / "_error-log"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        api.kernels_output(ref, str(folder), force=True, quiet=True)
    except Exception:
        return ""
    logs = sorted(folder.rglob("*.log"))
    if not logs:
        return ""
    raw = logs[0].read_text(encoding="utf-8", errors="replace").strip()
    try:
        events = json.loads(raw)
    except json.JSONDecodeError:
        events = []
    lines = []
    for event in events if isinstance(events, list) else []:
        data = str(event.get("data") or "").strip()
        if not _useful_log_line(data):
            continue
        lines.append(data)
    return " ".join(lines)[-500:]


def _useful_log_line(data: str) -> bool:
    noise = ("SyntaxWarning", "NbConvert", "mistune", "re.sub", "cells[i]", "Escape underscores")
    return bool(data) and not any(token in data for token in noise)


def _kernel_timeout() -> float:
    raw = os.environ.get("ONCOMETRA_KAGGLE_TIMEOUT_S", "").strip()
    if raw.isdigit():
        return float(raw)
    return 3 * 60 * 60


def _kernel_state(response) -> tuple[str, str]:
    if isinstance(response, dict):
        status = response.get("status")
        detail = str(response.get("failureMessage") or response.get("failure_message") or response.get("error") or "")
    else:
        status = getattr(response, "status", None)
        detail = ""
        for attr in ("failureMessage", "failure_message", "error", "error_message", "message"):
            value = getattr(response, attr, None)
            if value:
                detail = _redact(value)
                break
    if status is None:
        return "running", "en attente"
    text = str(getattr(status, "name", status)).strip()
    folded = text.lower().replace("-", "_")
    if any(word in folded for word in ("error", "fail", "cancel")):
        return "error", detail or _redact(text)
    if "complete" in folded or "success" in folded:
        return "complete", detail or "terminé"
    return "running", detail or _redact(text)


def _find_output(root: Path, uid: str, name: str) -> Path | None:
    """A mask is kept only when its name carries this exam. One shared file is not reused."""
    prefixed = f"{uid}__{name}"
    matches = [
        path for path in root.rglob("*")
        if path.is_file() and (path.name == prefixed or (path.parent.name == uid and path.name == name))
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _find_log(root: Path) -> Path | None:
    matches = [path for path in root.rglob("nvidia-smi.csv") if path.is_file()]
    if len(matches) == 1:
        return matches[0]
    return None


def _check_uid(uid: str) -> None:
    if not uid or any(character in uid for character in "\\/\0"):
        raise RuntimeError("Identifiant de série inutilisable.")


def _check_username(username: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        raise RuntimeError("Identifiant Kaggle inutilisable.")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _already_exists(error: Exception) -> bool:
    text = str(error).lower()
    return "409" in text or "already" in text or "exists" in text


def _redact(value) -> str:
    return _TOKEN_RE.sub("KGAT_…", str(value))[:500]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run organ and lesion detection for one NIfTI on a Kaggle GPU.")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--uid", required=True)
    parser.add_argument("--lesion-task", default="liver_lesions")
    parser.add_argument("--dest", type=Path)
    args = parser.parse_args(argv)
    dest = args.dest
    if dest is None:
        from app.services.exam_autoseg import series_result_dir
        dest = series_result_dir(args.uid)
    ensure_remote_masks(args.image, args.uid, args.lesion_task or None, dest, report=print)
    print(dest)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
