import json
import os
from pathlib import Path

import pytest

from app.services import kaggle_autoseg


def test_staging_keeps_the_token_out_and_requests_a_private_gpu(tmp_path):
    image = tmp_path / "ct.nii.gz"
    image.write_bytes(b"nifti")
    dataset, kernel = kaggle_autoseg.stage_exam(
        tmp_path / "stage", "reader", image, "1.2.3.4", "liver_lesions", organs=True, lesions=True,
    )
    job = json.loads((dataset / "job.json").read_text(encoding="utf-8"))
    meta = json.loads((kernel / "kernel-metadata.json").read_text(encoding="utf-8"))
    dataset_meta = json.loads((dataset / "dataset-metadata.json").read_text(encoding="utf-8"))
    assert job["exams"] == [{
        "file": "image.nii.gz", "uid": "1.2.3.4", "organs": True, "lesions": True, "lesion_task": "liver_lesions",
    }]
    assert (dataset / "image.nii.gz").read_bytes() == b"nifti"
    assert not (dataset / "run.py").exists()
    assert meta["is_private"] is True
    assert meta["enable_gpu"] is True
    assert meta["enable_internet"] is True
    assert meta["machine_shape"] == "NvidiaTeslaT4"
    assert meta["docker_image"].startswith("gcr.io/kaggle-private-byod/python@")
    assert "docker_image_pinning_type" not in meta
    assert meta["dataset_sources"] == ["reader/oncometra-exam"]
    assert dataset_meta["id"] == "reader/oncometra-exam"
    blob = json.dumps({"job": job, "kernel": meta, "dataset": dataset_meta})
    assert "KGAT_" not in blob
    assert (kernel / "run.py").read_text(encoding="utf-8").startswith('"""TotalSegmentator')


def test_a_batch_sends_several_exams_without_running_them_together(tmp_path):
    first = tmp_path / "one.nii.gz"
    second = tmp_path / "two.nii.gz"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    dataset, _kernel = kaggle_autoseg.stage_exams(tmp_path / "stage", "reader", [
        {"image": first, "uid": "1.2.3", "organs": True, "lesions": True, "lesion_task": "liver_lesions"},
        {"image": second, "uid": "1.2.4", "organs": True, "lesions": True, "lesion_task": "liver_lesions"},
    ])
    job = json.loads((dataset / "job.json").read_text(encoding="utf-8"))
    assert "parallel" not in job
    assert [exam["file"] for exam in job["exams"]] == ["1.2.3.nii.gz", "1.2.4.nii.gz"]
    assert (dataset / "1.2.3.nii.gz").read_bytes() == b"one"


def test_the_notebook_runs_exams_one_after_another_and_keeps_going_after_one_failure():
    from app.services.kaggle_kernel.run import _execute_exams

    order = []
    inside = 0
    peak = 0

    def run(exam):
        nonlocal inside, peak
        if exam["uid"] == "bad":
            raise RuntimeError("oom")
        inside += 1
        peak = max(peak, inside)
        order.append(exam["uid"])
        inside -= 1

    exams = [{"uid": "a"}, {"uid": "bad"}, {"uid": "b"}, {"uid": "c"}]
    errors = _execute_exams(exams, run)
    assert peak == 1
    assert order == ["a", "b", "c"]
    assert errors == ["bad: oom"]


def test_masks_land_in_the_series_folder_without_replacing_an_existing_one(tmp_path):
    uid = "1.2.840"
    download = tmp_path / "output" / uid
    download.mkdir(parents=True)
    (download / "organs.nii.gz").write_bytes(b"organs")
    (download / "lesions.nii.gz").write_bytes(b"lesions")
    (tmp_path / "output" / "nvidia-smi.csv").write_text("timestamp,name\n2026,T4\n", encoding="utf-8")
    dest = tmp_path / "autoseg"
    (dest / "organs.nii.gz").parent.mkdir(parents=True)
    (dest / "organs.nii.gz").write_bytes(b"kept")
    kaggle_autoseg.place_outputs(tmp_path / "output", uid, dest, need_organs=True, need_lesions=True)
    assert (dest / "organs.nii.gz").read_bytes() == b"kept"
    assert (dest / "lesions.nii.gz").read_bytes() == b"lesions"
    assert "T4" in (dest / "nvidia-smi.csv").read_text(encoding="utf-8")


def test_a_shared_mask_file_is_not_given_to_every_exam(tmp_path):
    download = tmp_path / "output"
    download.mkdir()
    (download / "organs.nii.gz").write_bytes(b"shared")
    with pytest.raises(RuntimeError, match="organs.nii.gz"):
        kaggle_autoseg.place_outputs(download, "1.2.3", tmp_path / "dest", need_organs=True, need_lesions=False)
    owned = download / "1.2.3__organs.nii.gz"
    owned.write_bytes(b"owned")
    dest = tmp_path / "placed"
    kaggle_autoseg.place_outputs(download, "1.2.3", dest, need_organs=True, need_lesions=False)
    assert (dest / "organs.nii.gz").read_bytes() == b"owned"


def test_a_failed_notebook_names_the_missing_mask(tmp_path):
    with pytest.raises(RuntimeError, match="lesions.nii.gz"):
        kaggle_autoseg.place_outputs(tmp_path, "uid", tmp_path / "dest", need_organs=False, need_lesions=True)


def test_errors_do_not_repeat_the_token():
    assert kaggle_autoseg._redact("header KGAT_" + "ab" * 16) == "header KGAT_…"


def test_startup_stays_on_cpu_unless_a_device_was_chosen(monkeypatch):
    monkeypatch.setenv("ONCOMETRA_TOTALSEG_DEVICE", "placeholder")
    os.environ.pop("ONCOMETRA_TOTALSEG_DEVICE")
    kaggle_autoseg.prefer_remote_gpu()
    assert os.environ["ONCOMETRA_TOTALSEG_DEVICE"] == "cpu"
    monkeypatch.setenv("ONCOMETRA_TOTALSEG_DEVICE", "kaggle")
    kaggle_autoseg.prefer_remote_gpu()
    assert os.environ["ONCOMETRA_TOTALSEG_DEVICE"] == "kaggle"


def test_a_missing_private_dataset_is_created_instead_of_failing():
    class Missing(Exception):
        def __init__(self):
            super().__init__("403 Client Error")
            self.response = type("Response", (), {
                "status_code": 403,
                "text": "Permission 'datasets.get' was denied",
            })()

    class Api:
        def dataset_status(self, ref):
            raise Missing()

    assert kaggle_autoseg._dataset_exists(Api(), "reader/oncometra-exam") is False


def test_kernel_status_words():
    assert kaggle_autoseg._kernel_state(type("S", (), {"status": "COMPLETE"})()) == ("complete", "terminé")
    assert kaggle_autoseg._kernel_state(type("S", (), {"status": "RUNNING"})()) == ("running", "RUNNING")
    state, detail = kaggle_autoseg._kernel_state(type("S", (), {"status": "ERROR", "error": "out of memory"})())
    assert state == "error" and detail == "out of memory"
    assert kaggle_autoseg._kernel_state({"status": "ERROR", "failureMessage": "dataset manquant"}) == ("error", "dataset manquant")


def test_the_notebook_finds_job_json_in_a_nested_input(tmp_path):
    from app.services.kaggle_kernel.run import _job
    folder = tmp_path / "datasets" / "reader" / "oncometra-exam"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text('{"exams":[]}', encoding="utf-8")
    found, payload = _job(tmp_path)
    assert found == folder
    assert payload == {"exams": []}


def test_the_notebook_reads_the_volume_kaggle_decompresses(tmp_path):
    from app.services.kaggle_kernel.run import _volume
    (tmp_path / "image.nii").write_bytes(b"nii")
    assert _volume(tmp_path, "image.nii.gz") == tmp_path / "image.nii"
    (tmp_path / "image.nii.gz").write_bytes(b"gz")
    assert _volume(tmp_path, "image.nii.gz") == tmp_path / "image.nii.gz"


def test_a_push_is_repeated_until_the_dataset_stays_attached(tmp_path, monkeypatch):
    monkeypatch.setattr(kaggle_autoseg.time, "sleep", lambda _seconds: None)
    kernel = tmp_path / "kernel"
    kernel.mkdir()

    class Api:
        def __init__(self):
            self.pushes = 0

        def kernels_push(self, folder, no_run=False):
            self.pushes += 1
            invalid = ["reader/oncometra-exam"] if self.pushes == 1 else []
            return type("Response", (), {"invalidDatasetSources": invalid, "versionNumber": self.pushes})()

        def kernels_pull(self, ref, dest, metadata=True, quiet=True):
            Path(dest).mkdir(parents=True, exist_ok=True)
            sources = ["reader/oncometra-exam"] if self.pushes >= 2 else [""]
            (Path(dest) / "kernel-metadata.json").write_text(
                json.dumps({"dataset_sources": sources}), encoding="utf-8",
            )

    api = Api()
    kaggle_autoseg._push_kernel(api, kernel, "reader/oncometra-totalseg", "reader/oncometra-exam")
    assert api.pushes == 3


def test_push_fails_when_the_dataset_never_attaches(tmp_path, monkeypatch):
    monkeypatch.setattr(kaggle_autoseg.time, "sleep", lambda _seconds: None)
    kernel = tmp_path / "kernel"
    kernel.mkdir()

    class Api:
        def kernels_push(self, folder, no_run=False):
            return type("Response", (), {"invalidDatasetSources": ["reader/oncometra-exam"], "versionNumber": 1})()

    with pytest.raises(RuntimeError, match="n’a pas attaché"):
        kaggle_autoseg._push_kernel(Api(), kernel, "reader/oncometra-totalseg", "reader/oncometra-exam")


def test_dataset_version_comes_from_the_status_payload():
    class Api:
        def dataset_status(self, ref, format=None):
            return json.dumps({"status": "ready", "current_version_number": 4})

    assert kaggle_autoseg._dataset_version(Api(), "reader/oncometra-exam") == "4"


def test_log_excerpt_skips_notebook_converter_noise():
    assert kaggle_autoseg._useful_log_line("Attendu un seul job.json, trouvé 0.")
    assert not kaggle_autoseg._useful_log_line("cells[i][c] = re.sub('\\\\|', '|', cell)")
    assert not kaggle_autoseg._useful_log_line("text = re.sub(r'_', '\\_', text) # Escape underscores in display text")
