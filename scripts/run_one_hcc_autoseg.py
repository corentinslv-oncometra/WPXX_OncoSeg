"""Prepare organs, HU and, if needed, a liver-lesion mask for one HCC-TACE exam."""

from pathlib import Path
import json
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pydicom
import SimpleITK as sitk

from app.services.dicom_seg import _tumor_numbers, referenced_series_uids, sibling_seg_files
from app.services.exam_autoseg import (
    autoseg_root, binary_labels, class_names, hu_rows, lesion_task_for_cancer,
    on_reference_grid, series_result_dir, totalseg_cli,
)
from app.services.imaging import read_dicom_series_from_dir

CANCER = "Hepatocellular carcinoma (HCC)"
DATASET = Path("data/TCIA_Data/hcc_tace_seg")


def _uniform_slices(series_dir: Path) -> int:
    names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(series_dir))
    if len(names) < 20:
        return 0
    positions = []
    for name in names:
        header = pydicom.dcmread(name, stop_before_pixels=True, force=True)
        positions.append(float(header.ImagePositionPatient[2]))
    gaps = np.diff(sorted(positions))
    if not len(gaps) or float(np.max(np.abs(gaps)) - np.median(np.abs(gaps))) > 1.0:
        return 0
    return len(names)


def _has_tumor_seg(series_dir: Path) -> bool:
    header = pydicom.dcmread(str(next(series_dir.glob("*.dcm"))), stop_before_pixels=True, force=True)
    uid = str(header.SeriesInstanceUID)
    for path in sibling_seg_files(series_dir):
        dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        cited = referenced_series_uids(dataset)
        if cited and uid not in cited:
            continue
        if _tumor_numbers(dataset):
            return True
    return False


def choose_series() -> Path:
    without_seg = []
    for patient in sorted(path for path in DATASET.iterdir() if path.is_dir()):
        for study in sorted(path for path in patient.iterdir() if path.is_dir()):
            series = [path for path in study.iterdir() if path.is_dir()]
            volumes = []
            tumor_seg = False
            for item in series:
                count = _uniform_slices(item)
                if not count:
                    continue
                if _has_tumor_seg(item):
                    tumor_seg = True
                else:
                    volumes.append((count, item))
            if volumes and not tumor_seg:
                volumes.sort()
                without_seg.append(volumes[0])
    if not without_seg:
        raise SystemExit("Aucun examen CT uniforme sans fichier SEG de tumeur.")
    without_seg.sort(key=lambda item: abs(item[0] - 80))
    return without_seg[0][1]


def _run(task: str, source: Path, output: Path, *, fast: bool) -> None:
    command = [str(totalseg_cli()), "-i", str(source), "-o", str(output), "-ta", task,
               "--ml", "--statistics", "--statistics_extra", "--device", "cpu"]
    if fast:
        command.append("--fast")
    completed = subprocess.run(command)
    if completed.returncode:
        raise SystemExit(f"TotalSegmentator a échoué pour {task} (code {completed.returncode}).")


def main() -> None:
    series = choose_series()
    header = pydicom.dcmread(str(next(series.glob("*.dcm"))), stop_before_pixels=True, force=True)
    uid = str(header.SeriesInstanceUID)
    destination = series_result_dir(uid)
    destination.mkdir(parents=True, exist_ok=True)
    image = sitk.DICOMOrient(read_dicom_series_from_dir(series), "LPS")
    ct_path = destination / "image.nii.gz"
    sitk.WriteImage(image, str(ct_path), True)
    organs_path = destination / "organs.nii.gz"
    if not organs_path.is_file():
        _run("total", ct_path, organs_path, fast=False)
    names = class_names("total")
    labels = sitk.GetArrayFromImage(on_reference_grid(image, sitk.ReadImage(str(organs_path))))
    spacing = image.GetSpacing()
    voxel_mm3 = float(spacing[0] * spacing[1] * spacing[2])
    tumor_task = None
    tumor_note = "Un fichier SEG de tumeur est déjà présent."
    if not _has_tumor_seg(series):
        chosen = lesion_task_for_cancer(CANCER)
        if chosen is None:
            tumor_note = "Aucun modèle ouvert de tumeur ne correspond à ce type de cancer."
        else:
            tumor_task, needles = chosen
            tumor_path = destination / "lesions.nii.gz"
            if not tumor_path.is_file():
                _run(tumor_task, ct_path, tumor_path, fast=False)
            lesion_names = class_names(tumor_task)
            lesion_labels = sitk.GetArrayFromImage(on_reference_grid(image, sitk.ReadImage(str(tumor_path))))
            mask = binary_labels(lesion_labels, lesion_names, needles)
            if int(mask.sum()):
                tumor = sitk.GetImageFromArray(mask)
                tumor.CopyInformation(image)
                sitk.WriteImage(tumor, str(destination / "tumor.nii.gz"), True)
                tumor_note = f"Pas de fichier SEG : tâche {tumor_task}."
            else:
                tumor_note = f"La tâche {tumor_task} n’a trouvé aucune lésion."
    payload = {
        "cancer": CANCER,
        "organ_task": "total",
        "organ_mode": "full",
        "device": "cpu",
        "tumor_task": tumor_task,
        "tumor_note": tumor_note,
        "organs": hu_rows(sitk.GetArrayFromImage(image), labels, names, voxel_mm3),
    }
    (destination / "hu.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    relative = series.resolve().relative_to(Path("data").resolve()).as_posix()
    (autoseg_root() / "chosen.json").write_text(json.dumps({
        "series_uid": uid, "series": relative, "slices": int(image.GetSize()[2]),
        "organs": len(payload["organs"]), "tumor_note": tumor_note,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"series": relative, "slices": int(image.GetSize()[2]), "organs": len(payload["organs"]), "tumor_note": tumor_note}, ensure_ascii=False))


if __name__ == "__main__":
    main()
