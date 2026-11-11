from pathlib import Path
import zipfile

from scripts.run_hcc_kaggle_queue import canonical_patient, choose_series, study_for, write_gpu_workbook


def test_patient_numbers_keep_three_digits():
    assert canonical_patient("HCC-91") == "HCC_091"
    assert canonical_patient("HCC-05") == "HCC_005"
    assert canonical_patient("HCC_027") == "HCC_027"


def test_hcc005_uses_the_contrast_series_of_the_requested_day():
    study = study_for(Path("data/TCIA_Data/hcc_tace_seg/HCC_005"), "1999-01-23")
    series = choose_series(study)
    assert "LIVER 3 PHASE" in series.name
    assert "PRE" not in series.name.upper()


def test_gpu_workbook_is_an_excel_file(tmp_path):
    source = tmp_path / "nvidia-smi.csv"
    source.write_text("timestamp,name\n2026-11-09,Tesla T4\n", encoding="utf-8")
    workbook = tmp_path / "HCC_027_1999-09-03.xlsx"
    write_gpu_workbook(source, workbook, ["HCC_027", "1999-09-03", "102"])
    with zipfile.ZipFile(workbook) as book:
        sheet = book.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "Tesla T4" in sheet
    assert "HCC_027" in sheet
