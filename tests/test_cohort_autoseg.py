from pathlib import Path

from app.services import cohort_autoseg


def _exam(root: Path, patient: str, day: str, uid: str) -> dict:
    series = root / patient / f"{day}-CT" / "series"
    series.mkdir(parents=True)
    (series / "slice.dcm").write_bytes(b"dicom")
    return {"patient_id": patient, "day": day, "series": series, "uid": uid, "timepoint_id": series.relative_to(root).as_posix()}


def test_one_series_is_kept_per_study(tmp_path, monkeypatch):
    kept = _exam(tmp_path, "HCC_001", "2000-01-02", "1.2.3")
    empty = tmp_path / "HCC_002" / "2000-02-02-CT"
    empty.mkdir(parents=True)

    def choose(study: Path):
        if study.name.startswith("2000-02-02"):
            raise RuntimeError("aucune série")
        return kept["series"]

    class Header:
        SeriesInstanceUID = "1.2.3"

    monkeypatch.setattr(cohort_autoseg.pydicom, "dcmread", lambda *_args, **_kwargs: Header())
    exams = cohort_autoseg.exams_in_folder(tmp_path, choose)
    assert [(exam["patient_id"], exam["day"], exam["uid"]) for exam in exams] == [("HCC_001", "2000-01-02", "1.2.3")]


def test_a_cohort_runs_in_groups_and_a_failure_does_not_drop_the_other_exam(tmp_path, monkeypatch):
    monkeypatch.setattr(cohort_autoseg, "series_result_dir", lambda uid: tmp_path / "masks" / uid)
    exams = [
        {"patient_id": "HCC_027", "day": "1999-09-03", "series": tmp_path, "uid": "good", "timepoint_id": "HCC_027/study/series"},
        {"patient_id": "HCC_039", "day": "2000-08-26", "series": tmp_path, "uid": "bad", "timepoint_id": "HCC_039/study/series"},
        {"patient_id": "HCC_041", "day": "2000-10-20", "series": tmp_path, "uid": "next", "timepoint_id": "HCC_041/study/series"},
    ]
    calls = []
    published = []

    def remote(batch, _report):
        calls.append([exam["uid"] for exam in batch])
        for exam in batch:
            if exam["uid"] == "bad":
                continue
            exam["dest"].mkdir(parents=True, exist_ok=True)
            (exam["dest"] / "organs.nii.gz").write_bytes(b"organs")
            (exam["dest"] / "lesions.nii.gz").write_bytes(b"lesions")

    result = cohort_autoseg.run_job(
        "liver-ct", exams, lesion_task="liver_lesions", remote=remote,
        publish=lambda exam: published.append(exam["uid"]), chunk=2,
        prepare=lambda exam: tmp_path / "image.nii.gz", ready=lambda _exam: False,
    )
    assert calls == [["good", "bad"], ["next"]]
    assert published == ["good", "next"]
    assert result["done"] == 2
    assert result["failed"] == 1
    assert result["state"] == "error"


def test_a_running_job_is_not_started_twice():
    cohort_autoseg._jobs["liver-ct"] = {**cohort_autoseg._blank(), "state": "running", "detail": "en cours", "total": 4}
    try:
        status = cohort_autoseg.start_cohort("liver-ct", "user")
    finally:
        cohort_autoseg._jobs.pop("liver-ct", None)
    assert status["state"] == "running"
    assert status["detail"] == "en cours"
    assert status["total"] == 4
