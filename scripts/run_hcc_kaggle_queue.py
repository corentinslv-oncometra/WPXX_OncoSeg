"""Run liver-lesion detection for the chosen HCC-TACE exams, one Kaggle GPU at a time.

Each notebook samples nvidia-smi while TotalSegmentator runs. The samples are
saved as one Excel file per exam under data/kaggle-gpu/.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import zipfile
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pydicom
import SimpleITK as sitk

from app.services.dicom_seg import referenced_series_uids, sibling_seg_files
from app.services.exam_autoseg import series_result_dir
from app.services.imaging import read_dicom_series_from_dir

DATASET = Path("data/TCIA_Data/hcc_tace_seg")
GPU_LOGS = Path("data/kaggle-gpu")
VOLUMES = Path("data/kaggle-queue")
# The third date is the study actually on disk when the requested day is absent.
QUEUE = (
    ("HCC-027", "1999-09-03", ""),
    ("HCC-039", "2000-08-26", ""),
    ("HCC-041", "2000-10-20", ""),
    ("HCC-043", "2000-12-19", ""),
    ("HCC-054", "2002-09-18", "2002-09-28"),
    ("HCC-065", "2003-04-26", ""),
    ("HCC-91", "2005-10-17", ""),
    ("HCC-92", "2005-10-10", ""),
    ("HCC-93", "2005-11-01", ""),
    ("HCC-94", "2005-12-26", ""),
    ("HCC-05", "1999-01-23", ""),
)


def canonical_patient(token: str) -> str:
    prefix, number = token.upper().replace("-", "_").split("_", 1)
    return f"{prefix}_{int(number):03d}"


def study_for(patient: Path, day: str) -> Path:
    matches = sorted(path for path in patient.iterdir() if path.is_dir() and path.name.startswith(day))
    if len(matches) == 1:
        return matches[0]
    available = ", ".join(path.name[:10] for path in sorted(patient.iterdir()) if path.is_dir()) or "aucune"
    if not matches:
        raise RuntimeError(f"{patient.name} n’a pas d’étude au {day}. Dates présentes : {available}.")
    raise RuntimeError(f"{patient.name} a plusieurs études au {day}.")


def choose_series(study: Path) -> Path:
    """Prefer the CT cited by the tumor SEG, then a contrast series, then the longest one."""
    cited: set[str] = set()
    series = [path for path in study.iterdir() if path.is_dir()]
    if series:
        for path in sibling_seg_files(series[0]):
            dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
            cited.update(referenced_series_uids(dataset))
    ranked = []
    for path in series:
        if "segment" in path.name.lower():
            continue
        files = sorted(path.glob("*.dcm"))
        if len(files) < 20:
            continue
        header = pydicom.dcmread(str(files[0]), stop_before_pixels=True, force=True)
        if str(getattr(header, "Modality", "")).upper() != "CT":
            continue
        uid = str(header.SeriesInstanceUID)
        contrast = "PRE" not in path.name.upper()
        ranked.append((uid in cited, contrast, len(files), path.name, path, uid))
    if not ranked:
        raise RuntimeError(f"Aucune série CT exploitable dans {study.name}.")
    ranked.sort(reverse=True)
    return ranked[0][4]


def resolve(patient_token: str, requested_day: str, actual_day: str = "") -> tuple[str, str, Path, str]:
    patient_id = canonical_patient(patient_token)
    day = actual_day or requested_day
    study = study_for(DATASET / patient_id, day)
    series = choose_series(study)
    header = pydicom.dcmread(str(next(series.glob("*.dcm"))), stop_before_pixels=True, force=True)
    return patient_id, day, series, str(header.SeriesInstanceUID)


def write_gpu_workbook(csv_path: Path, workbook: Path, title: list[str]) -> None:
    rows = [title, ["timestamp", "gpu", "utilisation_gpu_%", "utilisation_memoire_%", "memoire_utilisee_MiB", "memoire_totale_MiB", "temperature_C", "puissance_W"]]
    if csv_path.is_file():
        lines = [line for line in csv_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows.extend(line.split(",") for line in lines[1:])
    else:
        rows.append(["nvidia-smi absent du résultat Kaggle", "", "", "", "", "", "", ""])
    workbook.parent.mkdir(parents=True, exist_ok=True)
    _write_xlsx(workbook, rows)


def _write_xlsx(path: Path, rows: list[list[str]]) -> None:
    sheet_rows = []
    for index, row in enumerate(rows, start=1):
        cells = []
        for column, value in enumerate(row):
            ref = f"{chr(65 + column)}{index}"
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        sheet_rows.append(f'<row r="{index}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as book:
        book.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""")
        book.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""")
        book.writestr("xl/workbook.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="nvidia-smi" sheetId="1" r:id="rId1"/></sheets></workbook>""")
        book.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""")
        book.writestr("xl/worksheets/sheet1.xml", sheet)


def _volume(series: Path, uid: str) -> Path:
    target = VOLUMES / uid / "image.nii.gz"
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    image = read_dicom_series_from_dir(series)
    sitk.WriteImage(image, str(target), True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Détection des lésions HCC sur les GPU Kaggle, un examen après l'autre.")
    parser.add_argument("--dry-run", action="store_true", help="Affiche les séries choisies sans rien envoyer.")
    parser.add_argument("--force", action="store_true", help="Relance même si le masque de lésions est déjà sur le disque.")
    args = parser.parse_args()
    if not args.dry_run:
        from app.services.kaggle_autoseg import ensure_remote_masks
    for token, requested, replacement in QUEUE:
        patient_id, day, series, uid = resolve(token, requested, replacement)
        note = f" (date demandée {requested}, étude trouvée le {day})" if replacement else ""
        print(f"{patient_id} {day}{note} -> {series.relative_to(DATASET)}", flush=True)
        if args.dry_run:
            continue
        dest = series_result_dir(uid)
        lesions = dest / "lesions.nii.gz"
        if lesions.is_file() and not args.force:
            print("  Masque de lésions déjà présent, examen laissé de côté.", flush=True)
            continue
        if args.force and lesions.is_file():
            lesions.unlink()
        image = _volume(series, uid)
        ensure_remote_masks(image, uid, "liver_lesions", dest, report=lambda detail: print(f"  {detail}", flush=True))
        workbook = GPU_LOGS / f"{patient_id}_{day}.xlsx"
        write_gpu_workbook(dest / "nvidia-smi.csv", workbook, [patient_id, day, series.name])
        print(f"  Excel : {workbook}", flush=True)


if __name__ == "__main__":
    main()
