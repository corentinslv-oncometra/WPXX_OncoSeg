"""TotalSegmentator organ and lesion tasks for one private Kaggle GPU session.

This file is copied to the kernel as-is. It must not read credentials or import the app.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path


def _job(root: Path = Path("/kaggle/input")):
    matches = sorted(path for path in root.rglob("job.json") if path.is_file())
    if len(matches) != 1:
        preview = []
        if root.is_dir():
            preview = [str(path.relative_to(root)) for path in sorted(root.rglob("*")) if path.is_file()][:12]
        raise SystemExit(f"Attendu un seul job.json, trouvé {len(matches)}. Aperçu : {preview or 'entrée vide'}.")
    payload = json.loads(matches[0].read_text(encoding="utf-8"))
    return matches[0].parent, payload


def _install(package: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", package])
    import torch
    if not torch.cuda.is_available():
        raise SystemExit("CUDA n’est pas disponible après l’installation. Le notebook doit tourner sur un GPU T4.")


def _binary() -> str:
    found = shutil.which("TotalSegmentator") or shutil.which("totalsegmentator")
    if not found:
        raise SystemExit("La commande TotalSegmentator est introuvable dans le notebook.")
    return found


def _run(binary: str, image: Path, output: Path, task: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [binary, "-i", str(image), "-o", str(output), "-ta", task,
               "--ml", "--statistics", "--statistics_extra", "--device", "gpu"]
    print(" ".join(command), flush=True)
    subprocess.check_call(command)


def _execute_exams(exams, run) -> list[str]:
    """Run exams one after another. One failure does not cancel the next."""
    errors: list[str] = []
    for exam in exams:
        try:
            run(exam)
        except (Exception, SystemExit) as error:
            errors.append(f"{exam.get('uid')}: {error}")
    return errors


def _watch_gpu(stop: threading.Event, path: Path) -> None:
    """Sample the Kaggle GPU until segmentation finishes. The file comes back with the masks."""
    query = ["nvidia-smi", "--query-gpu=timestamp,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"]
    while not stop.is_set():
        try:
            completed = subprocess.run(query, capture_output=True, text=True, timeout=20)
            line = (completed.stdout or completed.stderr or "nvidia-smi sans sortie").strip().replace("\n", " | ")
        except Exception as error:
            line = f"erreur,,,,,,,{error}"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        stop.wait(15)


def _volume(folder: Path, name: str) -> Path:
    """Kaggle stores a gzipped NIfTI as image.nii after it decompresses the upload."""
    image = folder / name
    if image.is_file():
        return image
    if name.endswith(".gz") and (folder / name[:-3]).is_file():
        return folder / name[:-3]
    raise SystemExit(f"Volume introuvable : {name}")


def main() -> None:
    folder, payload = _job()
    written = Path("/kaggle/working")
    written.mkdir(parents=True, exist_ok=True)
    gpu_log = written / "nvidia-smi.csv"
    gpu_log.write_text("timestamp,name,utilization_gpu_percent,utilization_memory_percent,memory_used_mib,memory_total_mib,temperature_c,power_w\n", encoding="utf-8")
    stop = threading.Event()
    watcher = threading.Thread(target=_watch_gpu, args=(stop, gpu_log), daemon=True)
    watcher.start()
    try:
        _install(str(payload.get("package") or "TotalSegmentator==2.18.0"))
        binary = _binary()

        def run_exam(exam) -> None:
            image = _volume(folder, str(exam["file"]))
            uid = str(exam["uid"])
            if exam.get("organs", True):
                _run(binary, image, written / f"{uid}__organs.nii.gz", "total")
            lesion_task = exam.get("lesion_task")
            if exam.get("lesions") and lesion_task:
                _run(binary, image, written / f"{uid}__lesions.nii.gz", str(lesion_task))
            elif exam.get("lesions"):
                raise RuntimeError("La détection des lésions est demandée sans tâche.")

        errors = _execute_exams(payload.get("exams") or [], run_exam)
        (written / "results.json").write_text(json.dumps({"errors": errors}, ensure_ascii=False), encoding="utf-8")
        if errors:
            raise SystemExit(" ; ".join(errors))
        print("Masques écrits.", flush=True)
    finally:
        stop.set()
        watcher.join(timeout=5)


if __name__ == "__main__":
    main()
